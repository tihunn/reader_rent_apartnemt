"""Разведчик чатов: открывает Chrome и записывает, какие данные сайт грузит для чатов.

Запуск: python recon.py <сайт>      например: python recon.py domclick
Сайты и их стартовые страницы — в SITES ниже.
1. Откроется Chrome с отдельным профилем этого сайта (profile_<сайт> рядом со скриптом).
2. Войди на сайт сам, руками. Вход сохранится в профиле, в следующий раз входить не придётся.
3. Открой «Сообщения», пощёлкай пару чатов, отправь себе тестовое сообщение
   с другого аккаунта или ответь в каком-нибудь чате.
4. Закрой окно браузера. Всё записанное будет в папке recon_<сайт>/.

Скрипт ничего не нажимает и не отправляет, он только слушает, что сайт качает.
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

HERE = Path(__file__).parent
# сайт: (стартовая страница, кусок домена, запросы к которому записываем)
SITES = {
    "cian": ("https://www.cian.ru/", "cian"),
    "domclick": ("https://domclick.ru/", "domclick"),
}
MAX_BODY = 300_000
# что не интересно: картинки, счётчики, реклама
SKIP = ("yandex", "google", "mc.", "top-fwz", "adfox", "sentry", "metrika", ".png", ".jpg", ".svg", ".woff")


async def main(site):
    start_url, domain = SITES[site]
    PROFILE = HERE / f"profile_{site}"
    OUT = HERE / f"recon_{site}"
    OUT.mkdir(exist_ok=True)
    log = (OUT / f"log_{time.strftime('%Y%m%d_%H%M%S')}.jsonl").open("a", encoding="utf-8")
    count = 0

    def write(rec):
        rec["t"] = time.time()
        log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        log.flush()

    async def on_response(resp):
        nonlocal count
        url = resp.url
        if domain not in urlparse(url).netloc or any(s in url for s in SKIP):
            return
        if resp.request.resource_type not in ("xhr", "fetch"):
            return
        try:
            body = (await resp.text())[:MAX_BODY]
        except Exception:
            body = None
        count += 1
        write({"kind": "http", "method": resp.request.method, "url": url, "status": resp.status,
               "req_body": (resp.request.post_data or "")[:20000], "body": body})
        print(f"[{count}] {resp.request.method} {resp.status} {url[:140]}")

    def on_ws(ws):
        print(f"[ws] открыт {ws.url}")
        write({"kind": "ws_open", "url": ws.url})
        ws.on("framereceived", lambda p: write({"kind": "ws_in", "url": ws.url, "data": str(p)[:MAX_BODY]}))
        ws.on("framesent", lambda p: write({"kind": "ws_out", "url": ws.url, "data": str(p)[:MAX_BODY]}))

    def watch(page):
        page.on("websocket", on_ws)
        page.on("framenavigated", lambda fr: fr == page.main_frame and (
            print(f"[вкладка] {fr.url}"), write({"kind": "nav", "url": fr.url})))

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            PROFILE, channel="chrome", headless=False, viewport=None,
            args=["--disable-blink-features=AutomationControlled"])
        ctx.on("response", on_response)
        ctx.on("page", watch)
        for pg in ctx.pages:
            watch(pg)
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(start_url)
        print(f"Браузер открыт. Войди на {site}, открой сообщения/чаты, потом закрой окно.")
        closed = asyncio.Event()
        ctx.on("close", lambda _: closed.set())
        await closed.wait()
    log.close()
    print(f"Готово, записано запросов: {count}. Папка: {OUT}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in SITES:
        sys.exit("Укажи сайт: " + ", ".join(SITES))
    asyncio.run(main(sys.argv[1]))
