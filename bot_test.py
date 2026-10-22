"""Проверка бота: подключается к Telegram через tg-ws-proxy и отвечает «работаю».

Нужен файл config.json рядом со скриптом (образец — config.example.json):
  bot_token  — токен от @BotFather
  api_id, api_hash — с https://my.telegram.org → API development tools
                     (Telethon без них не подключается, даже для бота)
  use_proxy  — true на компьютере в России, false там, где Telegram не заблокирован
Секрет прокси скрипт сам берёт из настроек tg-ws-proxy (%APPDATA%/TgWsProxy/config.json).

Запуск: python bot_test.py, потом напиши боту в Telegram /start.
Твой chat_id скрипт напечатает: его надо вписать в config.json как owner_id,
чтобы бот слушался только тебя.
"""
import json
import os
from pathlib import Path

from telethon import TelegramClient, connection, events

HERE = Path(__file__).parent


def load_config():
    cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    proxy_cfg = Path(os.environ.get("APPDATA", "")) / "TgWsProxy" / "config.json"
    if cfg.get("use_proxy") and not cfg.get("proxy_secret") and proxy_cfg.exists():
        p = json.loads(proxy_cfg.read_text(encoding="utf-8"))
        cfg.setdefault("proxy_host", p.get("host", "127.0.0.1"))
        cfg.setdefault("proxy_port", p.get("port", 1443))
        cfg["proxy_secret"] = "dd" + p["secret"]
    return cfg


def make_client(cfg, session_name):
    kw = {}
    if cfg.get("use_proxy"):
        kw["connection"] = connection.ConnectionTcpMTProxyRandomizedIntermediate
        kw["proxy"] = (cfg.get("proxy_host", "127.0.0.1"), int(cfg.get("proxy_port", 1443)), cfg["proxy_secret"])
    return TelegramClient(str(HERE / session_name), int(cfg["api_id"]), cfg["api_hash"], **kw)


def main():
    cfg = load_config()
    client = make_client(cfg, "bot")

    @client.on(events.NewMessage)
    async def handler(event):
        print(f"сообщение от chat_id={event.chat_id}: {event.raw_text!r}")
        await event.reply(f"Работаю. Твой chat_id: {event.chat_id}")

    client.start(bot_token=cfg["bot_token"])
    print("Бот запущен. Напиши ему /start в Telegram. Остановить: Ctrl+C")
    client.run_until_disconnected()


if __name__ == "__main__":
    main()
