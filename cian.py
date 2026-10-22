"""ЦИАН: держит открытым чат в Chrome, ловит новые сообщения и отправляет ответы.

Как устроены чаты — docs/cian_chat_api.md. Коротко:
- новые сообщения приходят по websocket сайта событием {"type": "message"};
- отправка — тот же websocket, сообщение {"type": "message", "message": {"chatId", "text"}};
- на случай обрыва раз в POLL_SEC проверяем список чатов обычным запросом.
"""
import asyncio
import json
import time
import uuid

from sitebase import SiteBase, async_playwright

DIALOGS_URL = "https://www.cian.ru/dialogs/"
CHATS_GET = "https://chats.cian.ru/chats/v3/web/chats/get/"
HISTORY = "https://chats.cian.ru/chats/v3/web/history/messages/?chatId={chat_id}&limit=50"
MARK_READ = "https://chats.cian.ru/chats/v1/messages/read/"
WS_PART = "wss.cian.ru/chats"
POLL_SEC = 60

# Запоминаем сокеты чатов, которые открывает сам сайт: через них и отправляем.
INIT_SCRIPT = """
(() => {
  const Orig = window.WebSocket;
  window.__cianChatWs = [];
  window.WebSocket = function (url, protocols) {
    const ws = protocols === undefined ? new Orig(url) : new Orig(url, protocols);
    if (String(url).includes('%s')) window.__cianChatWs.push(ws);
    return ws;
  };
  window.WebSocket.prototype = Orig.prototype;
  Object.assign(window.WebSocket, Orig);
})();
""" % WS_PART

SEND_JS = """
([frame]) => {
  const open = (window.__cianChatWs || []).filter(w => w.readyState === 1);
  if (!open.length) return false;
  open[open.length - 1].send(frame);
  return true;
}
"""


class Cian(SiteBase):
    name = "cian"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.chats = {}          # chat_id -> карточка чата (кто, объявление, ссылка)

    # ---------- чаты ----------

    def _remember_chat(self, chat):
        cid = chat.get("chatId")
        if not cid:
            return
        card = (chat.get("header") or {}).get("card") or {}
        title = ((chat.get("header") or {}).get("title") or {})
        offer = chat.get("offer") or {}
        if offer.get("userId") and not self.my_id:
            self.my_id = offer["userId"]
        self.chats[cid] = {
            "who": " ".join(x for x in (title.get("primaryText"), title.get("secondaryText")) if x),
            "card": card.get("title") or chat.get("description") or "",
            "url": f"{DIALOGS_URL}?chatId={cid}",
        }

    async def _handle_message(self, m):
        mid = m.get("messageId")
        if not mid or mid in self.seen:
            return
        self.seen.add(mid)
        self.save_state()
        if self.my_id and m.get("userId") == self.my_id:
            return  # своё сообщение (отправленное с сайта или нами)
        cid = m.get("chatId")
        if cid not in self.chats:
            await self.poll()
        info = self.chats.get(cid, {})
        await self.on_message({
            "site": self.name,
            "chat_id": cid,
            "message_id": mid,
            "text": m.get("text") or "",
            "kind": m.get("type"),
            "files": len(m.get("files") or []),
            "user_id": m.get("userId"),
            "who": info.get("who", ""),
            "title": info.get("card", ""),
            "url": info.get("url", f"{DIALOGS_URL}?chatId={cid}"),
        })

    async def poll(self, first=False):
        """Проверка списком чатов: на случай, если websocket что-то пропустил."""
        data = await self.fetch(CHATS_GET, "POST", {"limit": 25, "status": "active"})
        if data is None:
            return
        self.clear_alert()
        for chat in data.get("chats", []):
            self._remember_chat(chat)
        for chat in data.get("chats", []):
            last = chat.get("lastMessage") or {}
            if not last.get("messageId") or last["messageId"] in self.seen:
                continue
            if self.my_id and last.get("userId") == self.my_id:
                self.seen.add(last["messageId"])
                continue
            if first and not chat.get("unreadMessagesCount"):
                self.seen.add(last["messageId"])   # старое и уже прочитанное — не пересылаем
                continue
            hist = await self.fetch(HISTORY.format(chat_id=chat["chatId"]))
            msgs = sorted((hist or {}).get("messages", []), key=lambda x: x.get("created", ""))
            if first:
                # при запуске пересылаем только непрочитанные, остальное считаем старым
                theirs = [m for m in msgs if m.get("userId") != self.my_id]
                keep = theirs[-chat.get("unreadMessagesCount", 0):]
                self.seen.update(m["messageId"] for m in msgs if m not in keep and m.get("messageId"))
                msgs = keep
            for m in msgs:
                await self._handle_message(m)
        self.save_state()

    # ---------- отправка ----------

    async def send(self, chat_id, text):
        if not self.my_id:
            await self.poll()
        frame = json.dumps({"type": "message", "message": {"chatId": chat_id, "text": text, "reply": None},
                            "uid": str(uuid.uuid4()), "userId": self.my_id}, ensure_ascii=False)
        ok = await self.page.evaluate(SEND_JS, [frame])
        if not ok:
            # сокет мог закрыться — перезагрузим страницу и попробуем ещё раз
            await self.page.reload()
            await asyncio.sleep(5)
            ok = await self.page.evaluate(SEND_JS, [frame])
        if ok:
            await self.fetch(MARK_READ, "POST", {"chatId": chat_id})
        return ok

    # ---------- запуск ----------

    def _on_ws(self, ws):
        if WS_PART not in ws.url:
            return

        def frame(payload):
            try:
                data = json.loads(payload)
            except (TypeError, ValueError):
                return
            if data.get("type") == "message" and isinstance(data.get("message"), dict):
                asyncio.ensure_future(self._handle_message(data["message"]))
            elif isinstance(data.get("chat"), dict):
                self._remember_chat(data["chat"])

        ws.on("framereceived", frame)

    async def run(self):
        async with async_playwright() as p:
            await self.launch(p, INIT_SCRIPT)
            self.page.on("websocket", self._on_ws)
            await self.page.goto(DIALOGS_URL)
            await asyncio.sleep(3)
            if "dialogs" not in self.page.url:
                await self.alert("не открылась страница сообщений, наверное нужно войти в аккаунт.")
            await self.poll(first=True)
            print(f"[cian] работаю, мой id {self.my_id}, чатов {len(self.chats)}")
            last_reload = time.time()
            while True:
                await asyncio.sleep(POLL_SEC)
                try:
                    if time.time() - last_reload > 3 * 3600:   # раз в 3 часа освежаем страницу
                        await self.page.reload()
                        last_reload = time.time()
                    await self.poll()
                except Exception as e:  # страница перезагружается, сеть моргнула и т. п.
                    print(f"[cian] ошибка проверки: {e}")
