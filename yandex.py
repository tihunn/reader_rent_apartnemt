"""Яндекс Недвижимость: держит открытым чат в Chrome, ловит новые сообщения и отправляет ответы.

Как устроены чаты — docs/yandex_chat_api.md. Коротко:
- всё идёт через POST https://realty.yandex.ru/chat/ajax/ с телом {"items":[{"path":..,"params":..}]};
- без заголовков x-csrf-token и x-vertis-* сервер просто рвёт соединение, поэтому
  робот подсматривает их в запросах, которые сайт делает сам, и повторяет;
- запросы идут изнутри страницы (fetch): запросы не из браузера Яндекс тоже рвёт;
- новые сообщения приходят по websocket push.yandex.ru (операция chat_new_message),
  он открывается, только когда открыт чат (иконка-облачко в шапке);
- на случай обрыва раз в 10–50 минут проверяем список чатов.
"""
import asyncio
import json
import time
import uuid

from sitebase import SiteBase, async_playwright, poll_delay

START_URL = "https://realty.yandex.ru/"
AJAX = "https://realty.yandex.ru/chat/ajax/"
WS_PART = "push.yandex.ru"
CHAT_ICON = "[class*=NavBarLink__link]"   # ссылка «Чат» (облачко) в шапке

AJAX_JS = """
async ([url, body, headers]) => {
  const r = await fetch(url, {method: 'POST', credentials: 'include',
                              headers: Object.assign({'content-type': 'application/json'}, headers), body});
  return {status: r.status, text: await r.text()};
}
"""


class Yandex(SiteBase):
    name = "yandex"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.rooms = {}          # room_id -> (кто, объявление)
        self.site_headers = {}   # x-csrf-token и x-vertis-*, подсмотренные у сайта

    # ---------- запросы ----------

    def _on_request(self, req):
        if "/chat/ajax/" in req.url:
            h = req.headers
            got = {k: v for k, v in h.items() if k == "x-csrf-token" or k.startswith("x-vertis-")}
            if got.get("x-csrf-token"):
                self.site_headers = got

    async def ajax(self, path, params):
        """Один вызов chat/ajax. Возвращает результат или None."""
        if not self.site_headers:
            await self._open_chat()
        body = json.dumps({"items": [{"path": path, "params": params}]}, ensure_ascii=False)
        try:
            r = await self.page.evaluate(AJAX_JS, [AJAX, body, self.site_headers])
        except Exception as e:   # сервер оборвал соединение — обычно протух токен
            print(f"[yandex] {path}: {e}")
            self.site_headers = {}
            return None
        if r["status"] in (401, 403):
            await self.alert("сайт не пускает (код %s). Похоже, выкинуло из аккаунта: зайди в браузер на сервере и войди." % r["status"])
            return None
        if r["status"] != 200:
            print(f"[yandex] {path} -> {r['status']} {r['text'][:200]}")
            return None
        data = json.loads(r["text"])
        return data[0] if isinstance(data, list) and data else data

    async def _open_chat(self):
        """Открыть чат иконкой в шапке: так сайт откроет websocket и сделает запрос с токеном."""
        # обычный клик Playwright сюда не проходит (подпись «Чат» скрыта), жмём из страницы
        found = False
        for _ in range(15):   # шапка дорисовывается не сразу
            found = await self.page.evaluate("""(sel) => {
              const el = [...document.querySelectorAll(sel)].find(e => (e.textContent || '').trim() === 'Чат');
              if (el) el.click();
              return !!el;
            }""", CHAT_ICON)
            if found:
                break
            await asyncio.sleep(1)
        if not found:
            await self.alert("открой чат сам: нажми облачко «Чат» в шапке сайта в окне Chrome на сервере. "
                             "Если облачка нет — значит, выкинуло из аккаунта, войди заново.")
        for _ in range(20):
            if self.site_headers:
                return
            await asyncio.sleep(0.5)

    # ---------- чаты ----------

    def _remember_room(self, room):
        rid = room.get("id")
        if not rid:
            return
        if room.get("me"):
            self.my_id = str(room["me"])
        others = [u for u in room.get("users", []) if str(u.get("id")) != self.my_id]
        who = ", ".join(((u.get("profile") or {}).get("alias") or (u.get("profile") or {}).get("full_name") or u.get("id") or "")
                        for u in others)
        self.rooms[rid] = {"who": who, "title": (room.get("subject") or {}).get("title") or ""}

    async def _handle_message(self, m):
        mid = m.get("id")
        if not mid or mid in self.seen:
            return
        self.seen.add(mid)
        self.save_state()
        if str(m.get("author")) == str(self.my_id):
            return
        rid = m.get("room_id") or m.get("roomId")
        if rid not in self.rooms:
            await self.poll()
        info = self.rooms.get(rid, {})
        payload = m.get("payload") or {}
        kind = payload.get("content_type") or payload.get("contentType") or ""
        await self.on_message({
            "site": self.name,
            "chat_id": rid,
            "message_id": mid,
            "text": payload.get("value") or "",
            "kind": "text" if kind == "TEXT_PLAIN" else kind.lower(),
            "files": 0,
            "user_id": m.get("author"),
            "who": info.get("who", ""),
            "title": info.get("title", ""),
            "url": START_URL,
        })

    async def poll(self, first=False):
        data = await self.ajax("chat/chat_list", {"page": 0, "pageSize": 20})
        if data is None:
            return
        self.clear_alert()
        for room in data.get("chatList", []):
            self._remember_room(room)
        for room in data.get("chatList", []):
            hist = await self.ajax("chat/chat_messages", {"asc": False, "count": 15, "room_id": room["id"]})
            msgs = sorted((hist or {}).get("messages", []), key=lambda x: x.get("created", ""))
            if first:
                # что пришло, пока робот не работал, узнать нельзя: старое просто запоминаем
                self.seen.update(m["id"] for m in msgs if m.get("id"))
                continue
            for m in msgs:
                await self._handle_message(m)
        self.save_state()

    async def send(self, chat_id, text):
        r = await self.ajax("chat/message_add", {"provided_id": str(uuid.uuid4()), "room_id": chat_id, "text": text})
        if not r or not (r.get("message") or {}).get("id"):
            return False
        self.seen.add(r["message"]["id"])
        await self.ajax("chat/chat_read", {"room_id": chat_id})
        return True

    # ---------- запуск ----------

    def _on_ws(self, ws):
        if WS_PART not in ws.url:
            return

        def frame(payload):
            try:
                data = json.loads(payload)
            except (TypeError, ValueError):
                return
            if data.get("operation") != "chat_new_message":
                return
            try:
                inner = json.loads(data.get("message") or "{}")
            except ValueError:
                return
            m = inner.get("message")
            if isinstance(m, dict):
                asyncio.ensure_future(self._handle_message(m))

        ws.on("framereceived", frame)

    async def run(self):
        async with async_playwright() as p:
            await self.launch(p)
            self.page.on("request", self._on_request)
            self.page.on("websocket", self._on_ws)
            await self.page.goto(START_URL)
            await asyncio.sleep(5)
            await self._open_chat()
            await self.poll(first=True)
            print(f"[yandex] работаю, мой id {self.my_id}, чатов {len(self.rooms)}")
            last_reload = time.time()
            while True:
                await asyncio.sleep(poll_delay())
                try:
                    if time.time() - last_reload > 3 * 3600:
                        self.site_headers = {}
                        await self.page.reload()
                        await asyncio.sleep(5)
                        await self._open_chat()
                        last_reload = time.time()
                    await self.poll()
                except Exception as e:
                    print(f"[yandex] ошибка проверки: {e}")
