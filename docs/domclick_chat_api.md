# Домклик: как устроены чаты (по записи разведчика от 22.10.2026)

Это внутренние запросы сайта, а не публичное API: Домклик может их поменять без предупреждения.
Вход — через Сбер ID (`id.sber.ru` → `sbol-auth.domclick.ru`), его делаешь руками один раз в профиле робота.

## Обязательный заголовок

Все запросы к `ipoteka.domclick.ru/chat/api/v3/...` требуют заголовок
`x-service: web/widget/1.0.1/build-number-null`, иначе ответ 400 `'X-Service' header is mandatory`.
Ко всем запросам сайт добавляет `reqid=<10 hex>` — случайный id, повторяем так же.

Запросы робот делает через Playwright (`context.request`), а не `fetch` из страницы:
из страницы запрос с этим заголовком падает на проверке CORS.

## Запросы

| Что | Запрос | Ответ |
|---|---|---|
| Кто я | `GET https://api.domclick.ru/auth/me` | `casId` — мой id |
| Непрочитанные | `GET .../chat/api/v3/state?reqid=…` | `data.unreadCounters[]` |
| Комнаты | `GET .../chat/api/v3/rooms?list=main&reqid=…&limit=50&offset=0` | `data[]`: `_id`, `name` («Аренда: 28 тыс - улица Текучёва, 39»), `unreadCount`, `members[]` (`casId`, `displayName`, `description` — «Арендатор»), `banner.redirectUrl` — ссылка на объявление |
| Сообщения | `GET .../rooms/<id>/messages?reqid=…&limit=50&offset=0&mode=reply_on&mentions_on=true` | `data[]`: `_id`, `time` (мс), `fromCasId`, `type` (`message`/`system`), `message` — текст |
| Отправить | `POST .../rooms/<id>/messages?reqid=…&bot_buttons=true`, тело `{"type":"message","message":"текст","uuid":"<uuid4>"}` | 201, `data` — созданное сообщение |
| Прочитано | `PATCH .../rooms/<id>/messages?reqid=…`, тело `{"readBy":<мой casId>}` | |

Системные сообщения (`fromCasId: -900`, «Чат создан») не пересылаем.

## Websocket (Centrifugo)

`wss://soba.domclick.ru/connection/websocket?cf_protocol_version=v2`

- сайт подписывается на `auth-chat:individual#<мой casId>`;
- новое сообщение: `{"push":{"channel":"auth-chat:individual#…","pub":{"data":{"action":"add","data":{"message":{…},"room":{…}}}}}}`;
- изменение комнаты и прочтение: `"action":"update"`;
- «в сети» сайт держит сам: `{"rpc":{"method":"ChatSetOnline"}}` раз в ~5 минут, пока страница открыта;
- в одном кадре может прийти несколько JSON, по одному на строку.
