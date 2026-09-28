---
title: "06. HTTP"
description: "Структура запроса/ответа, методы, коды состояния, curl, keep-alive, кеширование — конспект и задачи"
---

# 06. HTTP — протокол, на котором держится всё

> Роадмап → 2.5 Сети → протокол **HTTP**.
> **После темы ты умеешь:** прочитать запрос и ответ целиком, объяснить любой код состояния,
> отличить 502 от 504 по причине и понимать, что делает keep-alive, кеш и HTTP/2.

---

## 🗺️ Схема: из чего состоит обмен

```text:no-line-numbers
ЗАПРОС                                  ОТВЕТ
┌──────────────────────────────┐        ┌──────────────────────────────┐
│ GET /api/users?id=5 HTTP/1.1 │        │ HTTP/1.1 200 OK              │ ← стартовая строка
├──────────────────────────────┤        ├──────────────────────────────┤
│ Host: example.com            │        │ Content-Type: application/json│
│ User-Agent: curl/8.5.0       │        │ Content-Length: 47            │ ← заголовки
│ Accept: application/json     │        │ Cache-Control: max-age=60     │
│ Authorization: Bearer xxx    │        │ Set-Cookie: session=abc       │
├──────────────────────────────┤        ├──────────────────────────────┤
│ (пустая строка)              │        │ (пустая строка)               │
├──────────────────────────────┤        ├──────────────────────────────┤
│ тело (для POST/PUT)          │        │ {"id":5,"name":"Alice"}       │ ← тело
└──────────────────────────────┘        └──────────────────────────────┘
```

⭐ HTTP — **текстовый** (до версии 2) протокол поверх TCP, без состояния (stateless):
сервер не помнит предыдущий запрос, «память» создают куки и токены.

---

## 1. Методы

| Метод | Смысл | Идемпотентный? | Тело |
|-------|-------|----------------|------|
| `GET` | Получить ресурс | Да | Нет |
| `HEAD` | Как GET, но только заголовки | Да | Нет |
| `POST` | ⭐ Создать / выполнить действие | **Нет** | Да |
| `PUT` | Полностью заменить ресурс | Да | Да |
| `PATCH` | Частично изменить | Нет | Да |
| `DELETE` | Удалить | Да | Обычно нет |
| `OPTIONS` | Какие методы поддерживаются; ⭐ CORS preflight | Да | Нет |

**Идемпотентность** — повторный вызов не меняет результат. Это не теория: ретраить в скриптах
и балансировщиках можно только идемпотентные запросы (см. bash 26 в блоке Linux).

---

## 2. Коды состояния — обязательно наизусть

| Класс | Смысл |
|-------|-------|
| 1xx | Информационные (`101 Switching Protocols` — WebSocket) |
| 2xx | Успех |
| 3xx | Перенаправление |
| 4xx | Ошибка **клиента** |
| 5xx | Ошибка **сервера** |

| Код | Значение | Что делать DevOps'у |
|-----|----------|---------------------|
| 200 | OK | — |
| 201 | Created | Ответ на успешный POST |
| 204 | No Content | Успех без тела |
| 301 | Moved Permanently | ⭐ Кешируется браузером «навсегда» — осторожно с редиректом http→https |
| 302 / 307 | Временный редирект | 307 сохраняет метод и тело |
| 304 | Not Modified | Кеш клиента актуален (ETag / If-Modified-Since) |
| 400 | Bad Request | Кривой запрос/JSON |
| 401 | Unauthorized | Нет или неверная аутентификация |
| 403 | Forbidden | Аутентифицирован, но нет прав (или права на файлы у nginx!) |
| 404 | Not Found | Нет ресурса/маршрута |
| 405 | Method Not Allowed | Метод не поддерживается эндпоинтом |
| 413 | Payload Too Large | ⭐ `client_max_body_size` в nginx |
| 429 | Too Many Requests | Сработал rate limit |
| **500** | Internal Server Error | Упало **приложение** — смотри логи приложения |
| **502** | ⭐ Bad Gateway | Прокси не смог подключиться к бэкенду или получил мусор |
| **503** | Service Unavailable | Сервис перегружен/выключен, нет живых бэкендов |
| **504** | ⭐ Gateway Timeout | Бэкенд не ответил вовремя (`proxy_read_timeout`) |

⭐ **Вопрос с собеса: 502 vs 504.** 502 — «я вообще не смог получить нормальный ответ»
(бэкенд лежит, порт закрыт, процесс упал). 504 — «я дождался, но истёк таймаут»
(бэкенд жив, но медленный: тяжёлый запрос, блокировки в БД).

---

## 3. Заголовки, которые встречаются каждый день

**Запроса:**

| Заголовок | Зачем |
|-----------|-------|
| `Host` | ⭐ Обязателен в HTTP/1.1: по нему сервер выбирает виртуальный хост |
| `User-Agent` | Кто клиент (часто используется для блокировок) |
| `Accept`, `Accept-Encoding` | Какие форматы и сжатие понимает клиент |
| `Authorization` | `Bearer <token>` / `Basic base64(user:pass)` |
| `Cookie` | Сессия |
| `Content-Type` | Формат тела (`application/json`, `multipart/form-data`) |
| `X-Forwarded-For`, `X-Real-IP` | ⭐ Реальный IP клиента, добавляет прокси |
| `X-Forwarded-Proto` | Исходная схема (http/https) до терминации TLS |
| `If-None-Match`, `If-Modified-Since` | Условный запрос → может вернуть 304 |

**Ответа:**

| Заголовок | Зачем |
|-----------|-------|
| `Content-Type`, `Content-Length` | Что и сколько |
| `Transfer-Encoding: chunked` | Длина заранее неизвестна (стриминг) |
| `Cache-Control`, `ETag`, `Expires` | Управление кешированием |
| `Set-Cookie` | Установка куки (`HttpOnly`, `Secure`, `SameSite`) |
| `Location` | Куда редиректить (с 3xx) |
| `Server` | Кто ответил (часто скрывают) |
| `Strict-Transport-Security` | HSTS — только HTTPS |
| `Access-Control-Allow-Origin` | ⭐ CORS |
| `Retry-After` | Когда повторить (с 429/503) |

---

## 4. curl как основной инструмент

```bash
curl -v https://example.com                 # весь обмен: > запрос, < ответ
curl -sI https://example.com                # только заголовки (HEAD)
curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' https://example.com
curl -L https://example.com                 # идти за редиректами
curl -H 'Authorization: Bearer T' -H 'Accept: application/json' https://api/x
curl -X POST -H 'Content-Type: application/json' -d '{"a":1}' https://api/x
curl -d @payload.json https://api/x
curl --resolve example.com:443:10.0.0.5 https://example.com   # ⭐ обойти DNS: проверить конкретный бэкенд
curl -x http://proxy:3128 https://example.com                 # через прокси
curl --http1.1 / --http2 / --http3 https://example.com
curl -w '@curl-format.txt' -o /dev/null -s https://example.com  # тайминги по этапам
```

**Разбор времени ответа (отличает «сеть тормозит» от «приложение тормозит»):**

```bash
curl -s -o /dev/null -w \
 'dns=%{time_namelookup} connect=%{time_connect} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total}\n' \
 https://example.com
```

- большой `time_namelookup` → проблема DNS;
- большой `time_connect` → сеть/TCP;
- большой `time_appconnect` → TLS-хендшейк;
- большой `time_starttransfer` (TTFB) → ⭐ думает бэкенд;
- разрыв между TTFB и total → медленная передача тела/канал.

---

## 5. Keep-alive, пайплайнинг и версии протокола

| Версия | Транспорт | Главное отличие |
|--------|-----------|-----------------|
| HTTP/1.0 | TCP | Одно соединение = один запрос |
| **HTTP/1.1** | TCP | ⭐ Keep-alive по умолчанию, `Host`, chunked, кеширование |
| **HTTP/2** | TCP + TLS | Мультиплексирование в одном соединении, бинарный, сжатие заголовков (HPACK), server push |
| **HTTP/3** | ⭐ **QUIC поверх UDP** | Нет head-of-line blocking на уровне TCP, быстрое восстановление, 0-RTT |

```bash
curl -sI --http2 https://example.com | head -1     # HTTP/2 200
curl -sI --http3 https://cloudflare.com | head -1  # если поддерживается
```

⭐ Частый вопрос: «что нового в HTTP/2» → мультиплексирование (много запросов в одном TCP-соединении
без блокировки друг друга), бинарный формат, сжатие заголовков. «В HTTP/3» → тот же
мультиплексинг, но поверх QUIC/UDP, поэтому потеря одного пакета не тормозит все потоки.

---

## 6. Кеширование

```text:no-line-numbers
Cache-Control: max-age=3600, public      ← кешировать час
Cache-Control: no-cache                  ← кеш есть, но перед выдачей проверь у сервера
Cache-Control: no-store                  ← вообще не кешировать (персональные данные)
ETag: "a1b2c3"                           ← версия ресурса
```

Клиент с ETag шлёт `If-None-Match: "a1b2c3"` → сервер отвечает `304 Not Modified` без тела.
Это самый дешёвый способ разгрузить и канал, и бэкенд.

---

## 7. Что ломается в реальной жизни

| Симптом | Причина |
|---------|---------|
| 502 сразу | Бэкенд не запущен, неверный `proxy_pass`, упал воркер |
| 504 через 60 с | Бэкенд медленный, дефолтный `proxy_read_timeout 60s` |
| 413 при загрузке файла | `client_max_body_size` в nginx (по умолчанию 1 МБ) |
| 400 Bad Request на длинный URL/куки | `large_client_header_buffers` |
| Бесконечный редирект | Приложение видит `http` (из-за терминации TLS) и редиректит на `https` — нужен `X-Forwarded-Proto` |
| CORS-ошибка в браузере | Нет `Access-Control-Allow-Origin`; в curl при этом всё работает |
| Все клиенты с одним IP в логах | Прокси не передаёт `X-Forwarded-For` / не настроен `real_ip` |
| «Сайт открылся у меня, но не у пользователя» | Кеш, 301 в браузере, CDN, разный DNS |

---

## 💼 Как это в DevOps

- `curl -v` и `curl -w` — базовый инструмент диагностики любого сервиса.
- Коды 5xx — это SLI: доля 5xx и p95-латентность лежат в основе алертов.
- Health-check'и и пробы k8s — это HTTP-запросы с ожидаемым кодом.
- Заголовки `X-Forwarded-*` — обязательная часть конфигурации любого reverse proxy.
- Access-логи nginx (код, время ответа, upstream_time) — главный источник для разбора инцидентов
  (см. тему [12](/network/12-nginx) и Linux/03 «Text-Fu»).

---

## 🧪 Мини-лаба

```bash
vagrant ssh web
sudo apt install -y nginx curl jq

# 1. Полный обмен
curl -v http://localhost/ 2>&1 | head -30

# 2. Только заголовки и код
curl -sI http://localhost/ | head -5
curl -s -o /dev/null -w 'код=%{http_code} время=%{time_total}s\n' http://localhost/

# 3. Тайминги по этапам
curl -s -o /dev/null -w 'dns=%{time_namelookup} conn=%{time_connect} tls=%{time_appconnect} ttfb=%{time_starttransfer} total=%{time_total}\n' https://example.com

# 4. Коды состояния своими руками
sudo mkdir -p /var/www/html/secret && echo secret | sudo tee /var/www/html/secret/index.html >/dev/null
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/            # 200
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/нет-такого  # 404
sudo chmod 000 /var/www/html/secret/index.html
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/secret/     # 403 ← права на файл!
sudo rm -rf /var/www/html/secret
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost/    # 405

# 5. 502 и 504 — увидеть разницу
sudo tee /etc/nginx/sites-available/lab >/dev/null <<'EOS'
server {
  listen 8080;
  location /dead  { proxy_pass http://127.0.0.1:9999; }           # никто не слушает → 502
  location /slow  { proxy_pass http://127.0.0.1:9001; proxy_read_timeout 3s; }  # медленный → 504
}
EOS
sudo ln -sf /etc/nginx/sites-available/lab /etc/nginx/sites-enabled/lab
sudo nginx -t && sudo systemctl reload nginx
curl -s -o /dev/null -w '502? -> %{http_code}\n' http://localhost:8080/dead
# медленный бэкенд:
(while true; do printf 'HTTP/1.1 200 OK\r\n\r\n' | nc -l -p 9001 -q0 >/dev/null; sleep 10; done) &
BG=$!
curl -s -o /dev/null -w '504? -> %{http_code}\n' --max-time 10 http://localhost:8080/slow
kill $BG 2>/dev/null

# 6. Редирект и Location
curl -sI -H 'Host: example.com' http://example.com | grep -iE 'HTTP/|location'
curl -sIL http://example.com | grep -E 'HTTP/'      # вся цепочка редиректов

# 7. Кеш и 304
etag=$(curl -sI http://localhost/ | awk '/ETag/{print $2}' | tr -d '\r')
curl -s -o /dev/null -w '%{http_code}\n' -H "If-None-Match: $etag" http://localhost/   # 304

# 8. Виртуальные хосты и Host-заголовок
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: несуществующий.local' http://localhost/

# 9. Версии протокола
curl -sI --http1.1 https://example.com | head -1
curl -sI --http2 https://example.com | head -1

# 10. POST с JSON
curl -s -X POST -H 'Content-Type: application/json' -d '{"a":1}' https://httpbin.org/post | jq '.json'

# 11. Обход DNS (проверить конкретный бэкенд)
curl -s -o /dev/null -w '%{http_code}\n' --resolve example.com:80:93.184.216.34 http://example.com/

# 12. Уборка
sudo rm -f /etc/nginx/sites-enabled/lab && sudo systemctl reload nginx
```

---

## 📌 Шпаргалка

| Команда / код | Смысл |
|---------------|-------|
| `curl -v URL` | Весь обмен с заголовками |
| `curl -sI URL` | Только заголовки ответа |
| `curl -s -o /dev/null -w '%{http_code}'` | Только код ответа |
| `curl -w 'ttfb=%{time_starttransfer}'` | ⭐ Разбор задержки по этапам |
| `curl -L` | Следовать редиректам |
| `curl --resolve host:port:IP` | Обойти DNS |
| `curl -H 'Host: x'` | Проверить виртуальный хост |
| 301/302/307 | Постоянный / временный редирект |
| 401 / 403 | Не аутентифицирован / нет прав |
| 413 | Тело больше `client_max_body_size` |
| 429 | Rate limit, смотри `Retry-After` |
| 500 | Упало приложение |
| 502 | ⭐ Прокси не достучался до бэкенда |
| 503 | Нет живых бэкендов / перегрузка |
| 504 | ⭐ Бэкенд не ответил вовремя |

---

## 🧠 Что запомнить

1. HTTP — текстовый stateless-протокол поверх TCP: стартовая строка, заголовки, пустая строка, тело.
2. `Host` обязателен в HTTP/1.1 — по нему выбирается виртуальный хост.
3. Идемпотентны GET/PUT/DELETE/HEAD; POST — нет, поэтому его нельзя слепо ретраить.
4. 4xx — вина клиента, 5xx — сервера; 502 = «не достучался», 504 = «не дождался».
5. 403 у статики часто означает права на файлы, а не авторизацию.
6. `X-Forwarded-For` / `X-Forwarded-Proto` — иначе бэкенд видит IP прокси и не ту схему.
7. Тайминги `curl -w` разделяют DNS, TCP, TLS, TTFB и передачу — это первое, что делают
   при «тормозит».
8. HTTP/2 — мультиплексирование поверх TCP, HTTP/3 — то же поверх QUIC/UDP.
9. Кеширование: `Cache-Control` + `ETag` → `304 Not Modified` вместо повторной передачи.
10. CORS живёт в браузере: `curl` работает, а страница — нет, значит смотри
    `Access-Control-Allow-Origin`.

---

## Задачи

> Стенд: nginx на `web` (192.168.56.10).

---

### Блок A. Теория

**A1.** Из чего состоит HTTP-запрос и HTTP-ответ? Назови все части по порядку.

<details><summary>Ответ</summary>

Запрос: стартовая строка (метод, путь, версия), заголовки, пустая строка, тело
(опционально). Ответ: стартовая строка (версия, код, причина), заголовки, пустая строка, тело.

</details>

**A2.** Что значит «HTTP stateless» и чем тогда держится сессия пользователя?

<details><summary>Ответ</summary>

Сервер не хранит состояние между запросами: каждый запрос самодостаточен. Сессию
эмулируют куками с идентификатором сессии, токенами (JWT/Bearer) или параметрами запроса.

</details>

**A3.** Какие методы идемпотентны и почему это важно для ретраев?

<details><summary>Ответ</summary>

GET, HEAD, PUT, DELETE, OPTIONS — повторный вызов не меняет результат; POST и PATCH —
нет. Балансировщик или скрипт может безопасно ретраить только идемпотентные запросы,
иначе получим дубли операций.

</details>

**A4.** Зачем нужен заголовок `Host` и что было до HTTP/1.1?

<details><summary>Ответ</summary>

`Host` позволяет разместить много сайтов на одном IP: сервер выбирает виртуальный хост
по нему. В HTTP/1.0 заголовка не было, поэтому на один IP приходился один сайт.

</details>

**A5.** Назови классы кодов и по 3 примера из каждого.

<details><summary>Ответ</summary>

1xx — информационные (100 Continue, 101 Switching Protocols); 2xx — успех (200, 201, 204);
3xx — редиректы (301, 302, 304); 4xx — ошибка клиента (400, 401, 403, 404, 429);
5xx — ошибка сервера (500, 502, 503, 504).

</details>

**A6.** Разница 301 и 302. Чем опасен 301 при ошибке конфигурации?

<details><summary>Ответ</summary>

301 — постоянный: браузеры и кеши запоминают его надолго (иногда «навсегда»);
302/307 — временный. Ошибочно настроенный 301 (например, на неверный домен) остаётся
в браузерах пользователей даже после исправления конфигурации.

</details>

**A7.** Разница 401 и 403. Почему статика может отдавать 403?

<details><summary>Ответ</summary>

401 — не аутентифицирован (нет/неверные креды, сервер шлёт `WWW-Authenticate`);
403 — аутентификация не поможет, доступ запрещён. У статики 403 обычно означает,
что у процесса nginx нет прав на чтение файла или на проход по каталогу (`x` на директориях).

</details>

**A8.** ⭐ Разница 502, 503 и 504. Какие логи смотреть в каждом случае?

<details><summary>Ответ</summary>

502 — прокси не получил корректный ответ (бэкенд не поднят, порт закрыт, процесс упал);
503 — сервис недоступен (нет живых upstream, перегрузка, режим обслуживания);
504 — истёк таймаут ожидания ответа. В 502 смотрят `error.log` nginx и статус бэкенда,
в 504 — логи и профилирование приложения/БД, в 503 — состояние пула бэкендов и лимиты.

</details>

**A9.** Что означает 413 и где это настраивается?

<details><summary>Ответ</summary>

Тело запроса больше разрешённого: в nginx — `client_max_body_size` (по умолчанию 1 МБ),
плюс лимиты самого приложения.

</details>

**A10.** Для чего нужны `X-Forwarded-For` и `X-Forwarded-Proto`?

<details><summary>Ответ</summary>

При проксировании бэкенд видит адрес прокси. `X-Forwarded-For` передаёт цепочку
реальных клиентских адресов, `X-Forwarded-Proto` — исходную схему (https), чтобы приложение
не строило неправильные ссылки и не уходило в редирект-петлю.

</details>

**A11.** Что такое `ETag` и как получается ответ 304?

<details><summary>Ответ</summary>

`ETag` — идентификатор версии ресурса. Клиент присылает `If-None-Match`;
если версия не изменилась, сервер отвечает `304 Not Modified` без тела.

</details>

**A12.** Что такое keep-alive и что он даёт с точки зрения TCP?

<details><summary>Ответ</summary>

Переиспользование одного TCP-соединения для нескольких запросов: экономит
три рукопожатия и TLS-хендшейк, снижает задержку и число TIME_WAIT.

</details>

**A13.** Что нового в HTTP/2 по сравнению с 1.1? А в HTTP/3?

<details><summary>Ответ</summary>

HTTP/2: бинарный формат, мультиплексирование потоков в одном соединении,
сжатие заголовков HPACK, приоритеты, server push. HTTP/3: то же поверх QUIC/UDP —
нет head-of-line blocking на транспортном уровне, быстрый хендшейк (0-RTT),
миграция соединения при смене сети.

</details>

**A14.** Что такое CORS и почему ошибка видна в браузере, но не в curl?

<details><summary>Ответ</summary>

Механизм браузера, ограничивающий кросс-доменные запросы. Браузер шлёт preflight
(OPTIONS) и проверяет `Access-Control-Allow-*`. curl эти правила не применяет, поэтому
из консоли всё «работает».

</details>

**A15.** Как по таймингам curl понять, где именно теряется время?

<details><summary>Ответ</summary>

`time_namelookup` — DNS, `time_connect` — TCP, `time_appconnect` — TLS,
`time_starttransfer` — TTFB (обдумывание бэкендом), `time_total` — всё вместе.
Сравнивая соседние значения, локализуешь этап.

</details>

---

### Блок B. «Что делает команда / какой будет код»

```bash
B1.  curl -sI https://example.com
B2.  curl -s -o /dev/null -w '%{http_code}\n' https://example.com/nope
B3.  curl -L http://example.com
B4.  curl --resolve api.local:443:10.0.0.7 https://api.local/health
B5.  curl -H 'Host: admin.local' http://192.168.56.10/
B6.  curl -X POST -d '{"a":1}' -H 'Content-Type: application/json' http://api/x
B7.  curl -s -o /dev/null -w '%{time_starttransfer}\n' https://example.com
B8.  curl -sI --http2 https://example.com | head -1
B9.  curl -H 'If-None-Match: "abc"' -sI http://site/file.css
B10. curl -u user:pass https://example.com/private
```

- **B1.** Заголовки ответа (HEAD-запрос).
- **B2.** `404`.
- **B3.** Загрузит страницу, следуя редиректам.
- **B4.** Обратится по адресу 10.0.0.7, но с именем и SNI `api.local` — проверка конкретного бэкенда.
- **B5.** Проверка виртуального хоста `admin.local` на конкретном сервере.
- **B6.** POST с JSON-телом.
- **B7.** Только TTFB.
- **B8.** Первая строка ответа с версией протокола (`HTTP/2 200`).
- **B9.** Условный запрос: при совпадении ETag вернётся 304.
- **B10.** Basic-аутентификация.

**B11.** Какой код вернётся в каждом случае:
1. запрошен несуществующий путь;
2. у файла права 000, nginx его читает;
3. POST на location, где разрешён только GET;
4. загрузка файла 50 МБ при `client_max_body_size 1m`;
5. бэкенд в `proxy_pass` не запущен;
6. бэкенд отвечает 90 секунд при `proxy_read_timeout 60s`;
7. в приложении необработанное исключение.

<details><summary>Ответ</summary>

1) 404; 2) 403; 3) 405; 4) 413; 5) 502; 6) 504; 7) 500.

</details>

---

### Блок C. Практика

**C1. Разбор обмена.** Сделай `curl -v` к любому сайту и распиши построчно: что отправил
клиент (все заголовки), что вернул сервер, какая версия протокола, было ли переиспользовано
соединение.

<details><summary>Ответ</summary>

В выводе `-v`: строки `>` — запрос (метод, путь, `Host`, `User-Agent`, `Accept`),
`<` — ответ (код, заголовки), `* Connection #0 to host ... left intact` — соединение оставлено
для переиспользования (keep-alive), `* ALPN: server accepted h2` — согласован HTTP/2.

</details>

**C2. Коллекция кодов.** На своём nginx воспроизведи руками: 200, 301, 304, 400, 403, 404,
405, 413, 502, 504. Для каждого сохрани команду и краткое объяснение причины.

<details><summary>Ответ</summary>

Примеры: 301 — `return 301 https://$host$request_uri;`; 304 — условный запрос с ETag;
400 — `curl -H $'X-Bad: \x01' …` или слишком длинные заголовки; 403 — `chmod 000` на файл;
405 — `limit_except GET { deny all; }`; 413 — `client_max_body_size 1k` и загрузка большего файла.

</details>

**C3. 502 vs 504.** Настрой два location: один на несуществующий бэкенд, второй — на
намеренно медленный. Покажи разницу в кодах, времени ответа и записях в `error.log` nginx.

<details><summary>Ответ</summary>

`/dead` → 502 мгновенно, в `error.log`: `connect() failed (111: Connection refused)
while connecting to upstream`. `/slow` → 504 через `proxy_read_timeout`, в логе:
`upstream timed out (110: Connection timed out) while reading response header from upstream`.

</details>

**C4. Тайминги.** Сравни `curl -w` для: локального nginx, внешнего сайта по HTTP,
внешнего сайта по HTTPS, заведомо медленного эндпоинта. Сделай вывод, где теряется время
в каждом случае.

<details><summary>Ответ</summary>

Локальный nginx: все тайминги околонулевые. Внешний HTTP: заметен `time_connect`.
HTTPS: добавляется `time_appconnect` (TLS). Медленный эндпоинт: разрыв между `time_connect`
и `time_starttransfer` — думает бэкенд.

</details>

**C5. Виртуальные хосты.** Настрой на одном IP два server-блока с разными `server_name`
и покажи, что выбор зависит только от заголовка `Host`. Проверь через `curl -H 'Host: …'`
и через `--resolve`.

<details><summary>Ответ</summary>

Два `server` с разными `server_name`, один `listen 80`. `curl -H 'Host: a.local'`
и `curl -H 'Host: b.local'` дадут разные ответы, хотя IP один. При отсутствии совпадения
отвечает `default_server`.

</details>

**C6. Реальный IP клиента.** Поставь nginx перед простым бэкендом (`python3 -m http.server`
или второй nginx), покажи, что бэкенд видит IP прокси, затем настрой `X-Forwarded-For`
и `real_ip` и покажи корректный адрес в логах.

<details><summary>Ответ</summary>

```nginx
location / {
  proxy_pass http://127.0.0.1:8000;
  proxy_set_header Host $host;
  proxy_set_header X-Real-IP $remote_addr;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto $scheme;
}
```
На бэкенде (если это тоже nginx): `set_real_ip_from 192.168.56.0/24; real_ip_header X-Forwarded-For;`.

</details>

**C7. Кеширование.** Настрой `Cache-Control` и `ETag` для статики, покажи цепочку
200 → 304, измерь разницу во времени и объёме переданных данных.

<details><summary>Ответ</summary>

`add_header Cache-Control "max-age=3600";` — повторный запрос с `If-None-Match`
даёт 304 и нулевой размер тела (`%{size_download}` = 0).

</details>

**C8. Бесконечный редирект.** Воспроизведи петлю редиректов (приложение редиректит на https,
прокси ходит по http) и почини через `X-Forwarded-Proto`. Как это выглядит в `curl -L`?

<details><summary>Ответ</summary>

В `curl -L` видно повторяющуюся цепочку 301 на один и тот же URL, curl прерывается
по `--max-redirs`. Починка — передавать `X-Forwarded-Proto $scheme` и научить приложение
ему доверять (trusted proxies).

</details>

**C9. Скрипт HTTP-мониторинга.** `httpcheck.sh <url> <ожидаемый код> <макс_сек>` —
проверяет код и время ответа, печатает строку для лога и возвращает 0/1/2 в стиле
мониторинга (связь с bash-темой про надёжные скрипты).

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
set -uo pipefail
url="${1:?}"; want="${2:-200}"; max="${3:-2}"
read -r code t < <(curl -s -o /dev/null -w '%{http_code} %{time_total}' --max-time 10 "$url")
printf '%s code=%s time=%ss\n' "$url" "$code" "$t"
[[ "$code" == "$want" ]] || exit 2
awk -v t="$t" -v m="$max" 'BEGIN{exit !(t>m)}' && exit 1
exit 0
```

</details>

**C10. Анализ access.log.** По логам nginx посчитай: распределение кодов, долю 5xx,
топ-10 URL по количеству, топ-10 по времени ответа, и найди всплеск ошибок по минутам.

<details><summary>Ответ</summary>

```bash
LOG=/var/log/nginx/access.log
awk '{print $9}' $LOG | sort | uniq -c | sort -rn            # коды
awk '$9 ~ /^5/' $LOG | wc -l                                  # 5xx
awk '{print $7}' $LOG | sort | uniq -c | sort -rn | head      # топ URL
awk '{print $NF, $7}' $LOG | sort -rn | head                  # топ по времени (при log_format с $request_time)
awk '$9 ~ /^5/ {print substr($4,2,17)}' $LOG | uniq -c        # всплески по минутам
```

</details>

---

### Блок D. Инциденты

**D1.** Пользователи видят 502, при этом приложение «работает» (процесс жив, порт слушается).
Что проверить и почему 502 всё равно возможен?

<details><summary>Ответ</summary>

«Процесс жив» ≠ «отвечает»: воркеры заняты, приложение не принимает соединения,
слушает не тот адрес/порт (127.0.0.1 вместо 0.0.0.0), отдаёт некорректный HTTP,
или сработал лимит соединений/файрвол между прокси и бэкендом. Смотреть `error.log` nginx,
`ss -tlnp` на бэкенде, логи приложения.

</details>

**D2.** После деплоя часть запросов отдаёт 504, нагрузка не выросла. Где искать?

<details><summary>Ответ</summary>

Долгие запросы к БД (блокировки, отсутствие индекса после миграции), внешние вызовы
без таймаута, нехватка воркеров. Смотреть `upstream_response_time` в логах, метрики БД,
профиль эндпоинта; временно поднять `proxy_read_timeout` — не лечение, а отсрочка.

</details>

**D3.** Загрузка аватарки падает с ошибкой, в логах nginx `client intended to send too large body`.

<details><summary>Ответ</summary>

Увеличить `client_max_body_size` в nginx (и соответствующий лимит в приложении),
перезагрузить конфиг; для больших файлов — прямая загрузка в объектное хранилище.

</details>

**D4.** Браузер уходит в бесконечный редирект, curl без `-L` показывает 301 на тот же адрес.

<details><summary>Ответ</summary>

Приложение считает, что пришли по http, и редиректит на https; прокси терминирует TLS
и ходит на бэкенд по http. Лечение: `proxy_set_header X-Forwarded-Proto $scheme` и настройка
приложения доверять этому заголовку.

</details>

**D5.** В логах приложения все запросы приходят с одного IP — адреса балансировщика.
Что настроить и в каком порядке (nginx → приложение)?

<details><summary>Ответ</summary>

На прокси добавить `X-Forwarded-For`/`X-Real-IP`, на бэкенде — доверять им
(`set_real_ip_from` + `real_ip_header` в nginx, `ProxyFix`/trusted proxies в приложении).
Порядок важен: доверять заголовку можно только от известных прокси, иначе клиент подделает IP.

</details>

**D6.** Фронтенд получает ошибку CORS, хотя API отвечает 200 в curl. Что происходит
и что нужно добавить?

<details><summary>Ответ</summary>

Браузер блокирует ответ, потому что нет `Access-Control-Allow-Origin` (и, для
нетривиальных запросов, не обработан preflight OPTIONS). Нужно добавить заголовки CORS
на API или проксировать фронт и API под одним origin.

</details>

**D7.** После включения HTTP/2 часть старых клиентов перестала работать. Что могло случиться?

<details><summary>Ответ</summary>

HTTP/2 требует TLS и ALPN: старые клиенты без поддержки ALPN/современных шифров
не договариваются. Также ломаются клиенты, зависевшие от особенностей HTTP/1.1.
Решение — оставить fallback на HTTP/1.1 (обычно он есть) и проверить набор шифров.

</details>

**D8.** Сайт «тормозит»: TTFB 3 секунды, остальное быстро. На каком компоненте проблема
и что смотреть дальше?

<details><summary>Ответ</summary>

Время уходит на бэкенд (TTFB). Дальше: логи `upstream_response_time`, медленные
запросы в БД, внешние зависимости, GC/пул потоков приложения, трассировка.

</details>

**D9.** Мониторинг говорит «200 OK», а пользователи видят ошибку на странице. Как это возможно
и как исправить проверку?

<details><summary>Ответ</summary>

Проверка смотрит только код ответа, а страница содержит ошибку в теле (или ошибка
на фронтенде). Нужно проверять содержимое (`curl -s | grep`), отдельный `/health`,
который реально ходит в зависимости, и синтетический мониторинг сценария.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Из чего состоит HTTP-запрос?

<details><summary>Ответ</summary>

Стартовая строка, заголовки, пустая строка, тело.

</details>

**2.** Какие методы HTTP ты знаешь? Какие идемпотентны?

<details><summary>Ответ</summary>

GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS; идемпотентны GET/HEAD/PUT/DELETE/OPTIONS.

</details>

**3.** Что означают коды 301, 401, 403, 404, 500, 502, 504?

<details><summary>Ответ</summary>

301 — постоянный редирект; 401 — не аутентифицирован; 403 — доступ запрещён;
404 — не найдено; 500 — ошибка приложения; 502 — прокси не достучался; 504 — таймаут.

</details>

**4.** В чём разница между 502 и 504?

<details><summary>Ответ</summary>

502 — бэкенд недоступен/ответил мусором; 504 — не ответил вовремя.

</details>

**5.** Зачем нужен заголовок Host?

<details><summary>Ответ</summary>

Для выбора виртуального хоста на общем IP.

</details>

**6.** Что такое keep-alive?

<details><summary>Ответ</summary>

Переиспользование TCP-соединения для нескольких запросов.

</details>

**7.** Чем HTTP/2 отличается от HTTP/1.1?

<details><summary>Ответ</summary>

Мультиплексирование, бинарный формат, сжатие заголовков.

</details>

**8.** Что такое CORS?

<details><summary>Ответ</summary>

Браузерная политика кросс-доменных запросов на основе заголовков `Access-Control-*`.

</details>

**9.** Как посмотреть, где теряется время при медленном ответе?

<details><summary>Ответ</summary>

`curl -w` с разбивкой: DNS, connect, TLS, TTFB, total.

</details>

**10.** Как проксирование влияет на определение IP клиента?

<details><summary>Ответ</summary>

Бэкенд видит IP прокси; реальный адрес передаётся через `X-Forwarded-For`
и требует доверия к прокси.

</details>

---

### 🎯 Чек-лист

- [ ] Читаю `curl -v` целиком и понимаю каждую строку
- [ ] Знаю коды наизусть, включая 413, 429, 502, 503, 504
- [ ] Объясню 502 vs 504 и знаю, какие логи смотреть
- [ ] Умею разбирать задержку по таймингам curl
- [ ] Настроил проксирование с `X-Forwarded-For`/`Proto`
- [ ] Воспроизвёл 10 разных кодов руками
- [ ] Понимаю CORS и почему curl его не видит
