"""Домклик: держит открытым сайт в Chrome, ловит новые сообщения и отправляет ответы.

Как устроены чаты — docs/domclick_chat_api.md. Коротко:
- новые сообщения приходят по websocket (Centrifugo), канал auth-chat:individual#<мой casId>,
  событие {"action": "add", "data": {"message": {...}, "room": {...}}};
- отправка — POST .../rooms/<комната>/messages, прочитано — PATCH туда же;
- на случай обрыва раз в POLL_SEC проверяем комнаты с непрочитанными.
"""
import asyncio
import json
import secrets
import time
import uuid

from sitebase import SiteBase, async_playwright

START_URL = "https://domclick.ru/"
ME = "https://api.domclick.ru/auth/me"
API = "https://ipoteka.domclick.ru/chat/api/v3"
WS_PART = "soba.domclick.ru"
POLL_SEC = 60


def reqid():
    return secrets.token_hex(5)


class Domclick(SiteBase):
    name = "domclick"
    # без этого заголовка чат-API отвечает 400 «'X-Service' header is mandatory»
    headers = {"x-service": "web/widget/1.0.1/build-number-null"}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.rooms = {}          # room_id -> (кто, объявление, ссылка)

    def _remember_room(self, room):
        rid = room.get("_id")
        if not rid:
            return
        others = [m for m in room.get("members", []) if m.get("casId") not in (self.my_id, -900)]
        who = ", ".join(f"{m.get('displayName') or ''} ({m.get('description') or m.get('role') or ''})".strip()
                        for m in others)
        banner = room.get("banner") or {}
        self.rooms[rid] = {"who": who, "title": room.get("name") or "",
                           "url": banner.get("redirectUrl") or START_URL}

    async def _handle_message(self, m, room=None):
        mid = m.get("_id")
        if not mid or mid in self.seen:
            return
        self.seen.add(mid)
        self.save_state()
        if room:
            self._remember_room(room)
        if m.get("type") != "message" or m.get("fromCasId") in (self.my_id, -900):
            return  # своё или системное («Чат создан» и т. п.)
        rid = m.get("roomId")
        info = self.rooms.get(rid, {})
        await self.on_message({
            "site": self.name,
            "chat_id": rid,
            "message_id": mid,
            "text": m.get("message") or "",
            "kind": m.get("type"),
            "files": len(m.get("files") or []),
            "user_id": m.get("fromCasId"),
            "who": info.get("who", ""),
            "title": info.get("title", ""),
            "url": info.get("url", START_URL),
        })

    async def poll(self, first=False):
        """Проверка комнат с непрочитанными: на случай, если websocket что-то пропустил."""
        if not self.my_id:
            me = await self.fetch(ME)
            if me and me.get("casId"):
                self.my_id = me["casId"]
        data = await self.fetch(f"{API}/rooms?list=main&reqid={reqid()}&limit=50&offset=0")
        if data is None:
            return
        self.clear_alert()
        for room in data.get("data") or []:
            self._remember_room(room)
            unread = room.get("unreadCount") or 0
            if not unread:
                continue
            hist = await self.fetch(f"{API}/rooms/{room['_id']}/messages?reqid={reqid()}&limit=50&offset=0")
            msgs = sorted((hist or {}).get("data") or [], key=lambda x: x.get("time", 0))
            if first:
                theirs = [m for m in msgs if m.get("type") == "message" and m.get("fromCasId") != self.my_id]
                keep = theirs[-unread:]
                self.seen.update(m["_id"] for m in msgs if m not in keep and m.get("_id"))
                msgs = keep
            for m in msgs:
                await self._handle_message(m, room)
        self.save_state()

    async def send(self, chat_id, text):
        body = {"type": "message", "message": text, "uuid": str(uuid.uuid4())}
        r = await self.fetch(f"{API}/rooms/{chat_id}/messages?reqid={reqid()}&bot_buttons=true", "POST", body)
        if r is None:
            return False
        if r.get("data", {}).get("_id"):
            self.seen.add(r["data"]["_id"])
        await self.fetch(f"{API}/rooms/{chat_id}/messages?reqid={reqid()}", "PATCH", {"readBy": self.my_id})
        return True

    def _on_ws(self, ws):
        if WS_PART not in ws.url:
            return

        def frame(payload):
            # Centrifugo может прислать несколько JSON в одном кадре, по одному на строку
            for line in str(payload).splitlines():
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                pub = ((data.get("push") or {}).get("pub") or {}).get("data")
                if not isinstance(pub, dict) or pub.get("action") != "add":
                    continue
                inner = pub.get("data") or {}
                if isinstance(inner.get("message"), dict):
                    asyncio.ensure_future(self._handle_message(inner["message"], inner.get("room")))

        ws.on("framereceived", frame)

    async def run(self):
        async with async_playwright() as p:
            await self.launch(p)
            self.page.on("websocket", self._on_ws)
            await self.page.goto(START_URL)
            await asyncio.sleep(5)
            await self.poll(first=True)
            if not self.my_id:
                await self.alert("не вижу аккаунт, наверное нужно войти (через Сбер ID).")
            print(f"[domclick] работаю, мой id {self.my_id}, комнат {len(self.rooms)}")
            last_reload = time.time()
            while True:
                await asyncio.sleep(POLL_SEC)
                try:
                    if time.time() - last_reload > 3 * 3600:
                        await self.page.reload()
                        last_reload = time.time()
                    await self.poll()
                except Exception as e:
                    print(f"[domclick] ошибка проверки: {e}")
