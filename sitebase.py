"""Общее для всех сайтов: браузер с профилем, запросы из страницы, состояние, тревоги.

Каждый сайт (cian.py, domclick.py, ...) наследуется от SiteBase и делает:
- run()            — открыть браузер и слушать новые сообщения;
- send(chat_id, text) — отправить ответ в чат;
и для каждого нового чужого сообщения вызывает self.on_message(dict) с полями:
site, chat_id, message_id, text, kind, files, user_id, who, title, url.
"""
import json
from pathlib import Path

from playwright.async_api import async_playwright

# Признаки «тебя выкинуло из аккаунта» в ответах сайтов (ЦИАН при этом отвечает 400, а не 401)
LOGGED_OUT_HINTS = ("X-Real-UserId", "авториз", "Unauthorized", "not authenticated")


class SiteBase:
    name = "base"
    headers = {}   # служебные заголовки, которые сайт добавляет к своим запросам

    def __init__(self, here: Path, on_message, on_alert, headless=False):
        self.profile_dir = here / f"profile_{self.name}"
        self.state_file = here / f"state_{self.name}.json"
        self.on_message = on_message
        self.on_alert = on_alert
        self.headless = headless
        self.page = None
        self.my_id = None
        self.seen = set()        # id сообщений, которые уже обработаны
        self._alerted = False
        if self.state_file.exists():
            st = json.loads(self.state_file.read_text(encoding="utf-8"))
            self.seen = set(st.get("seen", []))
            self.my_id = st.get("my_id")

    def save_state(self):
        seen = list(self.seen)[-5000:]
        self.state_file.write_text(json.dumps({"seen": seen, "my_id": self.my_id}), encoding="utf-8")

    async def alert(self, text):
        """Сообщить человеку один раз, пока проблема не пройдёт (см. clear_alert)."""
        if not self._alerted:
            self._alerted = True
            await self.on_alert(f"{self.name.upper()}: {text}")

    def clear_alert(self):
        self._alerted = False

    async def fetch(self, url, method="GET", body=None):
        """Запрос с куками залогиненного браузера. Возвращает JSON или None.
        Идёт через Playwright, а не из страницы: так нет проблем с CORS и чужими обёртками fetch."""
        origin = "/".join(self.page.url.split("/")[:3])
        headers = {"origin": origin, "referer": self.page.url, **self.headers}
        if body is not None:
            headers["content-type"] = "application/json"
        resp = await self.page.context.request.fetch(
            url, method=method, headers=headers, data=None if body is None else json.dumps(body))
        status, text = resp.status, await resp.text()
        logged_out = status == 400 and any(h.lower() in text.lower() for h in LOGGED_OUT_HINTS)
        if status in (401, 403) or logged_out:
            await self.alert("сайт не пускает (код %s). Похоже, выкинуло из аккаунта: зайди в браузер на сервере и войди." % status)
            return None
        if status not in (200, 201):
            print(f"[{self.name}] {method} {url} -> {status} {text[:200]}")
            return None
        try:
            return json.loads(text) if text else {}
        except ValueError:
            return {}

    async def launch(self, playwright, init_script=None):
        ctx = await playwright.chromium.launch_persistent_context(
            self.profile_dir, channel="chrome", headless=self.headless, viewport=None,
            args=["--disable-blink-features=AutomationControlled"])
        if init_script:
            await ctx.add_init_script(init_script)
        self.page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        return ctx

    async def run(self):
        raise NotImplementedError

    async def send(self, chat_id, text):
        raise NotImplementedError


__all__ = ["SiteBase", "async_playwright"]
