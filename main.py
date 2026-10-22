"""Робот: чаты сайтов → Telegram-бот, ответы из бота → обратно в чат на сайте.

Запуск: python main.py          — с Telegram (нужен config.json)
        python main.py --dry    — без Telegram: только печатает новые сообщения в консоль
Какие сайты включены — "sites" в config.json (по умолчанию все из SITE_CLASSES).
Для --dry можно перечислить сайты: python main.py --dry domclick

В Telegram: чтобы ответить человеку, ответь (reply) на пересланное ботом сообщение.
Команды: /status — работает ли робот.
"""
import asyncio
import json
import sys
from pathlib import Path

from telethon import events

from bot_test import load_config, make_client
from cian import Cian
from domclick import Domclick

HERE = Path(__file__).parent
SITE_CLASSES = {"cian": Cian, "domclick": Domclick}
LINKS_FILE = HERE / "state_links.json"   # id сообщения в Telegram -> (сайт, чат)


def fmt(msg):
    head = f"🏠 {msg['site'].upper()} · {msg['title']}".strip(" ·")
    body = msg["text"] or ""
    if msg["kind"] != "text" or msg["files"]:
        body += f"\n[{msg['kind']}, файлов: {msg['files']} — смотри на сайте]"
    return f"{head}\n👤 {msg['who']}\n\n{body}\n\n{msg['url']}"


async def keep_running(site, on_alert):
    """Если сайт упал (браузер закрыли, сеть пропала), перезапускаем его через минуту."""
    while True:
        try:
            await site.run()
        except Exception as e:
            print(f"[{site.name}] упал: {e}")
            await on_alert(f"{site.name.upper()}: робот упал ({e}), перезапускаю через минуту.")
        await asyncio.sleep(60)


async def run_dry(names):
    async def on_message(msg):
        print("\n=== НОВОЕ ===\n" + fmt(msg))

    async def on_alert(text):
        print("\n!!! " + text)

    sites = [SITE_CLASSES[n](HERE, on_message, on_alert) for n in names]
    await asyncio.gather(*(keep_running(s, on_alert) for s in sites))


async def run_bot():
    cfg = load_config()
    owner = int(cfg.get("owner_id") or 0)
    if not owner:
        sys.exit("В config.json нет owner_id. Запусти bot_test.bat, напиши боту и впиши chat_id.")
    links = json.loads(LINKS_FILE.read_text(encoding="utf-8")) if LINKS_FILE.exists() else {}
    client = make_client(cfg, "bot")
    await client.start(bot_token=cfg["bot_token"])
    sites = {}

    async def on_message(msg):
        sent = await client.send_message(owner, fmt(msg), link_preview=False)
        links[str(sent.id)] = [msg["site"], msg["chat_id"]]
        LINKS_FILE.write_text(json.dumps(links), encoding="utf-8")

    async def on_alert(text):
        await client.send_message(owner, "⚠️ " + text)

    @client.on(events.NewMessage(from_users=owner))
    async def from_owner(event):
        if event.raw_text.strip() == "/status":
            await event.reply("Работаю. Сайты: " + ", ".join(sites))
            return
        if not event.is_reply:
            await event.reply("Чтобы ответить человеку, сделай reply на его сообщение.")
            return
        target = links.get(str(event.reply_to_msg_id))
        if not target:
            await event.reply("Не знаю, к какому чату относится это сообщение.")
            return
        site, chat_id = target
        ok = await sites[site].send(chat_id, event.raw_text)
        await event.reply("✅ отправлено" if ok else "❌ не отправилось, проверь браузер на сервере")

    for n in cfg.get("sites") or list(SITE_CLASSES):
        sites[n] = SITE_CLASSES[n](HERE, on_message, on_alert)
    await client.send_message(owner, "🤖 Робот запущен: " + ", ".join(sites))
    await asyncio.gather(*(keep_running(s, on_alert) for s in sites.values()),
                         client.run_until_disconnected())


if __name__ == "__main__":
    if "--dry" in sys.argv:
        asyncio.run(run_dry([a for a in sys.argv[1:] if a in SITE_CLASSES] or list(SITE_CLASSES)))
    else:
        asyncio.run(run_bot())
