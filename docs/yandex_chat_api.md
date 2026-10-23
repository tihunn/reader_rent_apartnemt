# Яндекс Недвижимость: как устроены чаты (по записи разведчика от 23.10.2026)

Это внутренние запросы сайта, а не публичное API: Яндекс может их поменять без предупреждения.
Отдельной страницы чата нет (`/chat/` — 404). Чат открывается виджетом по иконке-облачку «Чат» в шапке `realty.yandex.ru`.

## Защита

- Запрос не из браузера (Playwright `context.request`, curl) Яндекс обрывает (`ECONNRESET`).
- Запрос из страницы без нужных заголовков тоже обрывает (`Failed to fetch`).
- Нужные заголовки: `x-csrf-token`, `x-vertis-platform: desktop`, `x-vertis-rgid`, `x-vertis-service: REALTY`.
  Токен не совпадает с кукой `_csrf_token`, поэтому робот берёт все эти заголовки из запроса, который сайт делает сам при открытии чата, и повторяет их.

## Запросы

Всё — `POST https://realty.yandex.ru/chat/ajax/`, тело `{"items":[{"path":"<действие>","params":{…}}]}`, ответ — массив результатов.

| Действие (`path`) | `params` | Ответ |
|---|---|---|
| `bootstrap` | `{"session":"<uuid>"}` | настройки виджета |
| `chat/chat_list` | `{"page":0,"pageSize":10}` | `chatList[]`: `id`, `me` (мой id), `type`, `subject.title`, `users[].profile` (`alias`, `full_name`), `messages` |
| `chat/open_chat_room` | `{"room_id"}` | `{}` |
| `chat/chat_messages` | `{"asc":false,"count":15,"room_id"[, "from":"<id сообщения>"]}` | `messages[]`: `id`, `room_id`, `author`, `created`, `payload.content_type` (`TEXT_PLAIN`), `payload.value` — текст |
| `chat/message_add` | `{"provided_id":"<uuid>","room_id","text"}` | `message` — созданное сообщение |
| `chat/chat_read` | `{"room_id"}` | `{"id","status":true}` |

Ещё есть `GET https://realty.yandex.ru/gate/chat/has_unread/` → `hasUnreadMessages`.

## Websocket

`wss://push.yandex.ru/v2/subscribe/websocket?sign=…&ts=…&service=realty&user=<мой id>&client=realty-front-chat&session=…`
Открывается, только когда открыт виджет чата.

- новое сообщение: `{"operation":"chat_new_message","message":"<JSON строкой>"}`, внутри `{"message":{"author","created","id","payload":{"contentType","value"},"roomId"},"previousMessageId"}`;
- прочтение: `"operation":"chat_room_read"`;
- `{"operation":"ping","server-interval-sec":60}` раз в минуту.

## Ограничение робота

Что пришло, пока робот не работал, узнать нельзя: в списке чатов нет счётчика непрочитанных. Поэтому при запуске робот запоминает старое и пересылает только то, что придёт после запуска.
