# ЦИАН: как устроены чаты (по записи разведчика от 22.10.2026)

Это внутренние запросы сайта, а не публичное API: ЦИАН может их поменять без предупреждения.
Все запросы идут с куками залогиненного браузера, поэтому робот вызывает их из открытой страницы (`fetch` с `credentials: "include"`).

## Страницы

- Список чатов: `https://www.cian.ru/dialogs/`
- Конкретный чат: `https://www.cian.ru/dialogs/?chatId=offer_<userId собеседника>_<id объявления>`

## Чтение — найдено

| Что | Запрос | Ответ |
|---|---|---|
| Сколько непрочитанных | `GET https://api.cian.ru/chats/v1/get-total-unread-messages-count/` | `{"unread": 0}` |
| Список чатов | `POST https://chats.cian.ru/chats/v3/web/chats/get/`, тело `{"limit":25,"status":"active"}` | `chats[]`: `chatId`, `rowVersion`, `unreadMessagesCount`, `users[]`, `offer` (id, адрес, цена), `lastMessage` |
| История чата | `GET https://chats.cian.ru/chats/v3/web/history/messages/?chatId=<chatId>&limit=100` | `messages[]`: `messageId`, `userId` (кто написал), `created`, `type` (`text`…), `text`, `files`; `canLoadMore` |
| Файлы чата | `GET https://chats.cian.ru/chats/v1/get-latest-chat-files/?chatId=<chatId>&offset=0` | `files` |

Как понять, что пришло новое: у чата растёт `rowVersion`, а у `lastMessage.userId` стоит не мой id. Мой `userId` = `offer.userId` (владелец объявления).

## Websocket — частично

`wss://wss.cian.ru/chats/v5/endpoint-desktop/`

Видели только статусы «в сети»:
- от сайта: `{"type":"status","uid":"<uuid>","userId":<мой id>,"requestedUserIds":[<id собеседника>],"action":"subscribe"}`
- в ответ: `{"type":"status","status":{"userId":<id>,"lastActionDatetime":"..."}}`

Событие о новом сообщении в записи не попалось, потому что за время записи никто не написал.

## Отправка — не найдено

В записи нет ни одной отправки. Нужна ещё одна запись, в которой ты отправишь сообщение в чат.

## План робота

1. Держать открытой вкладку `/dialogs/` в отдельном профиле Chrome. Так сайт, вероятно, считает тебя «в сети».
2. Раз в 30–60 секунд вызывать «список чатов». Где вырос `rowVersion`, брать историю и пересылать новые чужие сообщения в Telegram.
3. Ответ из Telegram отправлять тем же запросом, что и сайт. Если его не получится повторить — открывать чат и вписывать текст в поле ввода, как человек.
4. Если сайт выкинул из аккаунта или показал капчу, написать в бота «зайди и реши».
