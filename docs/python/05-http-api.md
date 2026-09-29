---
title: "05. HTTP и API: requests, httpx, ретраи, пагинация"
description: "Блок → Python для DevOps → тема 5 из 8."
---

# 05. HTTP и API: requests, httpx, ретраи, пагинация

> Блок → **Python для DevOps** → тема 5 из 8.
> Аналог в bash: `curl -sSf --max-time --retry` + `jq` из [26_bash_devops_practice.md](/linux/26-bash-devops-practice).
>
> **После темы ты умеешь:** ходить в HTTP API через `requests`/`httpx` с таймаутами, ретраями
> и экспоненциальной задержкой, брать токены из окружения, разбирать JSON, проходить пагинацию
> и уважать rate limit; писать скрипты для GitLab API, отправлять уведомления в Telegram-бота
> и проверять пачку URL параллельно.

---

## 🗺️ Карта темы

```text
 скрипт ──► Session: пул соединений + общие заголовки + токен из env
               │
               ├── timeout=(connect, read)          ← ВСЕГДА, иначе висит вечно
               ├── Retry + backoff на сеть/429/5xx   ← только идемпотентные запросы
               ├── raise_for_status()               ← 4xx/5xx → исключение, а не «успех»
               ├── resp.json()                      ← dict / list
               ├── пагинация: Link / X-Next-Page / cursor → генератор
               └── rate limit: 429 + Retry-After, RateLimit-* заголовки
                                 │
            ┌────────────────────┼─────────────────────┐
       GitLab API          Telegram Bot API       health-check 50 URL
       (пайплайны)         (уведомления)          (ThreadPoolExecutor)
```text
---

## 1. requests: основы

```python
import requests

r = requests.get(
    "https://gitlab.example.com/api/v4/projects",
    params={"membership": "true", "per_page": 100},    # → ?membership=true&per_page=100
    headers={"PRIVATE-TOKEN": token},
    timeout=(3.05, 30),
)
r.raise_for_status()                 # 4xx/5xx → requests.HTTPError
projects = r.json()                  # list[dict]

r = requests.post(url, json={"name": "backup", "enabled": True}, timeout=10)   # json= сам сериализует и ставит Content-Type
```text
| Атрибут ответа | Что внутри |
|----------------|-----------|
| `r.status_code`, `r.ok` | Код, `True` для < 400 |
| `r.json()` / `r.text` / `r.content` | Разобранный JSON / строка / байты |
| `r.headers["Content-Type"]` | Заголовки (регистр не важен) |
| `r.links` | Разобранный заголовок `Link` (пагинация) |
| `r.elapsed.total_seconds()` | Время ответа |
| `r.url` | Итоговый URL после редиректов |

```text
requests.RequestException
 ├── ConnectionError          ← DNS, отказ соединения, TLS
 ├── Timeout ── ConnectTimeout, ReadTimeout
 ├── HTTPError                ← из raise_for_status()
 ├── RetryError               ← ретраи по статусу исчерпаны
 └── JSONDecodeError          ← r.json() на HTML/пустом теле (ещё и подкласс ValueError)
```text
---

## 2. ⭐ Таймауты — всегда

У `requests` **нет таймаута по умолчанию**: зависший сервер = зависший скрипт, CI-job или cron.

```python
requests.get(url, timeout=10)          # 10 с на соединение и 10 с на ожидание данных
requests.get(url, timeout=(3.05, 30))  # connect=3.05 с, read=30 с — отдельно
```text
- **connect** — сколько ждать установления TCP/TLS; маленький (2-5 с).
- **read** — сколько ждать **между байтами** ответа, а не общее время. Сервер, отдающий
  по байту раз в 20 секунд, не упадёт по `read=30` никогда. Нужен общий дедлайн —
  считай его сам (`time.monotonic()`) или ставь `timeout` на весь процесс.
- `httpx` по умолчанию ставит 5 секунд — но лучше задавать явно.

---

## 3. Session, авторизация, TLS

```python
import os, requests

def make_session(headers: dict[str, str] | None = None) -> requests.Session:
    s = requests.Session()                        # переиспользует TCP/TLS-соединения
    s.headers.update({"User-Agent": "ops-scripts/1.0", **(headers or {})})
    return s

token = os.environ.get("GITLAB_TOKEN") or sys.exit("GITLAB_TOKEN не задан")
gl = make_session({"PRIVATE-TOKEN": token})       # GitLab
api = make_session({"Authorization": f"Bearer {os.environ['API_TOKEN']}"})   # типичный Bearer
requests.get(url, auth=("user", os.environ["PASS"]), timeout=10)             # Basic
```text
| TLS | Как |
|-----|-----|
| Обычный сертификат | Ничего не делать: `verify=True` по умолчанию |
| Корпоративный CA | `verify="/etc/ssl/certs/corp-ca.pem"` или env `REQUESTS_CA_BUNDLE` |
| Клиентский сертификат (mTLS) | `cert=("client.crt", "client.key")` |
| `verify=False` | ⚠️ Только на стенде и осознанно — иначе MITM не заметишь |

Прокси из `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` requests подхватывает сам.

---

## 4. ⭐ Ретраи с экспоненциальной задержкой

**Что ретраить:** сетевые ошибки, таймауты, `429`, `502`, `503`, `504` (иногда `500`).
**Что не ретраить:** `400`, `401`, `403`, `404`, `422` — повтор ничего не изменит.
**Только идемпотентные** запросы: `GET`, `HEAD`, `PUT`, `DELETE`. `POST` повторяют, только если
API поддерживает ключ идемпотентности — иначе получишь два пайплайна / два сообщения.

**Вариант 1 — встроенный `urllib3.Retry`** (ретраи прозрачно для кода):

```python
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

def make_session(headers: dict[str, str] | None = None) -> requests.Session:
    retry = Retry(
        total=5,
        backoff_factor=1,                              # паузы: 0, 2, 4, 8, 16 с (растут ×2, не больше 120)
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS"}),   # без POST
        respect_retry_after_header=True,               # для 429/503 ждать сколько сказал сервер
    )
    adapter = HTTPAdapter(max_retries=retry)
    s = requests.Session()
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"User-Agent": "ops-scripts/1.0", **(headers or {})})
    return s
```text
Когда попытки по статусу кончились, летит `requests.exceptions.RetryError`.

**Вариант 2 — tenacity** (декоратор, гибкая логика, логирование попыток):

```python
import logging, requests
from tenacity import (before_sleep_log, retry, retry_if_exception,
                      stop_after_attempt, wait_exponential_jitter)

log = logging.getLogger(__name__)
RETRY_STATUSES = {429, 500, 502, 503, 504}

def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    return (isinstance(exc, requests.HTTPError) and exc.response is not None
            and exc.response.status_code in RETRY_STATUSES)

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),   # 1, 2, 4, 8... + случайная добавка
    retry=retry_if_exception(_retryable),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,                                      # после последней попытки — исходное исключение
)
def get_json(session: requests.Session, url: str, **params) -> dict | list:
    r = session.get(url, params=params, timeout=(3.05, 30))
    r.raise_for_status()
    return r.json()
```text
Зачем **jitter** (случайная добавка): 100 экземпляров скрипта, упавших одновременно, иначе
повторят запрос тоже одновременно и снова положат API.

---

## 5. JSON: разбор и сборка

```python
r = session.get(url, timeout=10)
r.raise_for_status()
if "application/json" not in r.headers.get("Content-Type", ""):
    raise RuntimeError(f"ожидался JSON, пришло {r.headers.get('Content-Type')}: {r.text[:200]}")
data = r.json()
name = data.get("owner", {}).get("name", "—")          # необязательные поля — через get

session.post(url, json={"ref": "main", "variables": [{"key": "ENV", "value": "prod"}]}, timeout=10)
# ⚠️ data={"a": 1} — это form-urlencoded, а не JSON
```text
`r.json()` на `204 No Content` или HTML-странице ошибки прокси (502 от nginx) → `JSONDecodeError`.

---

## 6. Пагинация

| Тип | Как узнать следующую страницу | Где встречается |
|-----|-------------------------------|-----------------|
| `page` + `per_page` | Заголовки `X-Next-Page`, `X-Total-Pages` или `Link: <...>; rel="next"` | GitLab, GitHub |
| Cursor / keyset | Токен/ссылка на следующую страницу в ответе или `Link` | GitLab keyset, Slack, большинство новых API |
| `offset` + `limit` | Пока ответ не короче `limit` | Старые API |

```python
from collections.abc import Iterator

def paginate(session: requests.Session, url: str, params: dict | None = None,
             per_page: int = 100) -> Iterator[dict]:
    """Все элементы со всех страниц, по одному. Следует заголовку Link: rel="next"."""
    params = {**(params or {}), "per_page": per_page}
    while url:
        r = session.get(url, params=params, timeout=(3.05, 30))
        r.raise_for_status()
        yield from r.json()
        url = r.links.get("next", {}).get("url")    # None на последней странице
        params = None                               # в next-URL параметры уже есть
```text
⚠️ По умолчанию GitLab отдаёт **20** элементов. Скрипт без пагинации «работает» на тестовом
проекте и молча теряет данные на реальной группе.

---

## 7. Rate limit

```text
   запрос ─► 429 Too Many Requests
             Retry-After: 30                 ← подождать 30 с
             RateLimit-Remaining: 0          ← (GitLab) сколько запросов осталось в окне
             RateLimit-Reset: 1790000000     ← когда окно обнулится (epoch)
```text
- `urllib3.Retry` с `respect_retry_after_header=True` сам ждёт `Retry-After` для 429/503.
- Не долби API параллельно в 50 потоков: ограничивай `max_workers`, делай паузы.
- Смотри `RateLimit-Remaining` и притормаживай заранее, а не после 429.
- Telegram на 429 кладёт паузу в тело ответа: `{"parameters": {"retry_after": 5&#125;&#125;`.

---

## 8. Пример: GitLab — упавшие пайплайны группы за N часов

```python
#!/usr/bin/env python3
"""failed_pipelines — упавшие пайплайны во всех проектах группы за последние N часов."""
import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

log = logging.getLogger("failed_pipelines")
# make_session() и paginate() — из разделов 4 и 6


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("group", help="id или полный путь группы, например devops/infra")
    p.add_argument("--hours", type=int, default=24)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    token = os.environ.get("GITLAB_TOKEN") or sys.exit("GITLAB_TOKEN не задан")
    api = os.environ.get("GITLAB_URL", "https://gitlab.com").rstrip("/") + "/api/v4"
    s = make_session({"PRIVATE-TOKEN": token})
    since = (datetime.now(timezone.utc) - timedelta(hours=args.hours)).isoformat()

    failed = 0
    projects = paginate(s, f"{api}/groups/{quote(args.group, safe='')}/projects",
                        {"include_subgroups": "true", "archived": "false", "simple": "true"})
    for project in projects:
        pipelines = paginate(s, f"{api}/projects/{project['id']}/pipelines",
                             {"status": "failed", "updated_after": since})
        for pl in pipelines:
            failed += 1
            print(f"{project['path_with_namespace']:&lt;40} #{pl['id']:<10} {pl['ref']:<25} {pl['web_url']}")
    log.info("упавших пайплайнов за %d ч: %d", args.hours, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```text
Путь группы кодируется (`devops/infra` → `devops%2Finfra`) — так требует GitLab API.
Токену хватает scope `read_api`.

---

## 9. Пример: уведомление в Telegram

```python
import html, os, requests

def send_telegram(text: str, *, silent: bool = False) -&gt; None:
    token = os.environ["TG_BOT_TOKEN"]            # от @BotFather
    chat_id = os.environ["TG_CHAT_ID"]            # узнать: написать боту → GET .../getUpdates
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text[:4096],                  # лимит длины сообщения
            "parse_mode": "HTML",
            "disable_notification": silent,
            "link_preview_options": {"is_disabled": True},
        },
        timeout=(3.05, 10),
    )
    if not r.ok:
        # ⚠️ не логируем r.url и исключения requests целиком — в URL токен бота
        raise RuntimeError(f"Telegram: {r.status_code} {r.json().get('description', '')}")

host, err = "web1", "disk / 93% &lt;warning&gt;"
send_telegram(f"🔥 <b>{html.escape(host)}</b>\n<code>{html.escape(err)}</code>")
```text
⚠️ С `parse_mode=HTML` любые `<`, `>`, `&` из логов ломают разметку → `400 Bad Request: can't parse entities`.
Всё, что пришло извне, — через `html.escape()`.

---

## 10. Пример: health-check списка URL параллельно

```python
#!/usr/bin/env python3
"""healthcheck — проверяет список URL, код выхода 1, если хоть один недоступен."""
import sys, time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests


@dataclass
class Result:
    url: str
    ok: bool
    status: int | None
    ms: float
    error: str = ""


def check(url: str, timeout: float = 5.0) -> Result:
    start = time.monotonic()
    try:
        r = requests.get(url, timeout=timeout, allow_redirects=True)
        return Result(url, r.status_code < 400, r.status_code, (time.monotonic() - start) * 1000)
    except requests.RequestException as e:
        return Result(url, False, None, (time.monotonic() - start) * 1000, type(e).__name__)


def main() -> int:
    urls = [line.strip() for line in sys.stdin if line.strip() and not line.startswith("#")]
    with ThreadPoolExecutor(max_workers=20) as pool:          # I/O-задачи: потоки подходят отлично
        results = list(pool.map(check, urls))
    for r in sorted(results, key=lambda r: r.ok):
        mark = "✅" if r.ok else "❌"
        print(f"{mark} {r.status or '---':>3} {r.ms:7.0f} ms  {r.url}  {r.error}")
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
```text
```bash
printf '%s\n' https://example.com http://localhost:9 https://httpbin.org/status/503 | ./healthcheck.py
```text
Потоки + GIL: пока поток ждёт сеть, GIL отпущен — 20 потоков проверяют 20 URL одновременно.
Для тысяч URL — `httpx.AsyncClient` + `asyncio`.

---

## 11. httpx — современная альтернатива

```python
import httpx

with httpx.Client(
    base_url="https://gitlab.example.com/api/v4",
    headers={"PRIVATE-TOKEN": token},
    timeout=httpx.Timeout(10.0, connect=3.0),
    transport=httpx.HTTPTransport(retries=3),     # ⚠️ ретраи только на ошибках соединения
    follow_redirects=True,                        # по умолчанию httpx НЕ идёт за редиректом
) as client:
    r = client.get("/projects", params={"per_page": 100})
    r.raise_for_status()
```text
```python
import asyncio, httpx

async def fetch_all(urls: list[str]) -> list[httpx.Response | BaseException]:
    limits = httpx.Limits(max_connections=50)
    async with httpx.AsyncClient(timeout=5.0, limits=limits) as client:
        return await asyncio.gather(*(client.get(u) for u in urls), return_exceptions=True)

results = asyncio.run(fetch_all(urls))
```text
| | requests | httpx |
|---|----------|-------|
| Таймаут по умолчанию | Нет ⚠️ | 5 с |
| Редиректы | Идёт сам | Только с `follow_redirects=True` |
| Ретраи по статусу | `urllib3.Retry` | Нет встроенных — tenacity |
| async | Нет | `AsyncClient` |
| HTTP/2 | Нет | `http2=True` (пакет `httpx[http2]`) |
| Когда | Скрипты, огромная база примеров | Новый код, async, тысячи запросов |

---

## 12. Грабли

| Грабля | Что происходит | Правильно |
|--------|----------------|-----------|
| Нет `timeout` | Скрипт/CI висит часами | `timeout=(3.05, 30)` всегда |
| Нет `raise_for_status()` | 500 считается успехом, дальше `KeyError`/`JSONDecodeError` | Проверять статус сразу |
| Ретрай `POST` | Два пайплайна, два сообщения, два платежа | Ретраить идемпотентное |
| Ретраи без паузы и лимита | Скрипт сам добивает лежащий API | backoff + jitter + `stop_after_attempt` |
| Ретрай на 401/404 | Бессмысленные повторы | Только сеть, 429, 5xx |
| Игнор пагинации | Обработаны первые 20 элементов из 3000 | Генератор по `Link`/`X-Next-Page` |
| `verify=False` | Отключена защита от MITM, токен можно перехватить | `verify="/path/ca.pem"` |
| Токен в URL (Telegram) попал в лог | Утечка бота | Не логировать URL и исключения целиком |
| `data=` вместо `json=` | API получает форму, отвечает 400/415 | `json=payload` |
| Новый `requests.get` на каждый из 1000 запросов к одному API | Новое TCP/TLS-соединение каждый раз | `Session` |
| `read`-таймаут = «общий таймаут» | Медленный сервер тянет бесконечно | Общий дедлайн отдельно |
| Внешний текст в HTML-сообщении Telegram | `can't parse entities` | `html.escape()` |

---

## 💼 Как это в DevOps

- Почти вся «интеграционная» автоматизация — это HTTP: GitLab/GitHub API (пайплайны, MR, релизы),
  Telegram/Slack (уведомления), Vault, Grafana (аннотации деплоев), Alertmanager, облачные API.
- Таймауты и ретраи отличают скрипт, который «иногда падает, перезапусти», от надёжного инструмента.
  В CI это разница между стабильным пайплайном и вечными ручными ретраями.
- Health-check-скрипты с уведомлением — первая автоматизация на многих проектах до полноценного
  мониторинга; позже их заменяет blackbox_exporter ([04_exporters.md](/monitoring/04-exporters)).
- Токены — только из env/CI-переменных (masked) и с минимальными правами (`read_api`, а не `api`).
- На собесе любят спросить: «как сделать надёжный HTTP-вызов?» — ответ: таймаут, ретраи с backoff
  и jitter, идемпотентность, `raise_for_status`, rate limit.

---

## 📌 Шпаргалка

| Хочу | Код |
|------|-----|
| GET с параметрами | `s.get(url, params={...}, timeout=(3.05, 30))` |
| POST JSON | `s.post(url, json=payload, timeout=10)` |
| Ошибку на 4xx/5xx | `r.raise_for_status()` |
| Сессия с заголовками | `s = requests.Session(); s.headers.update({...})` |
| Ретраи | `HTTPAdapter(max_retries=Retry(total=5, backoff_factor=1, status_forcelist=...))` |
| Ретраи декоратором | `@retry(stop=stop_after_attempt(5), wait=wait_exponential_jitter(...))` |
| Токен | `os.environ["TOKEN"]` → заголовок |
| Свой CA | `verify="/path/ca.pem"` / `REQUESTS_CA_BUNDLE` |
| Следующая страница | `r.links.get("next", {}).get("url")` / `r.headers.get("X-Next-Page")` |
| Все страницы | генератор `paginate()` с `yield from r.json()` |
| Пауза по 429 | `Retry(respect_retry_after_header=True)` / заголовок `Retry-After` |
| Параллельно N URL | `ThreadPoolExecutor(max_workers=20).map(check, urls)` |
| Тысячи URL | `httpx.AsyncClient` + `asyncio.gather` |
| Экранировать для Telegram HTML | `html.escape(text)` |
| Закодировать путь GitLab | `urllib.parse.quote("group/sub", safe="")` |

---

## 🧠 Что запомнить

1. `timeout` в каждом запросе: у requests его нет по умолчанию.
2. `raise_for_status()` сразу после запроса — иначе ошибка всплывёт позже и непонятно где.
3. Ретраить сеть, 429 и 5xx; не ретраить 4xx; `POST` — только с идемпотентностью.
4. Экспоненциальная задержка + jitter + лимит попыток — иначе ретраи добивают лежащий сервис.
5. `Session` — переиспользование соединений и общие заголовки/ретраи.
6. Пагинация обязательна: GitLab по умолчанию отдаёт 20 элементов.
7. 429 → уважать `Retry-After`, ограничивать параллельность.
8. Токены — из окружения, с минимальными правами, никогда в логах (осторожно с URL Telegram).
9. Для I/O потоки работают отлично (GIL отпускается на ожидании сети); для тысяч запросов — asyncio/httpx.
10. `verify=False` — не решение, решение — правильный CA-бандл.

➡️ Дальше: [06_parsing_logs.md](/python/06-parsing-logs) · Задачи: 05_http_api_tasks.md


---

### Блок A. Теория


**A1.** Что будет, если вызвать `requests.get(url)` без `timeout` и сервер не отвечает?

<details><summary>Ответ</summary>

Запрос будет ждать бесконечно (пока ОС не закроет соединение, что может занять часы):
висит скрипт, cron-задача, CI-job.

</details>

**A2.** Чем connect-таймаут отличается от read-таймаута? Почему `read=30` не значит «запрос не дольше 30 секунд»?

<details><summary>Ответ</summary>

Connect — ожидание установки соединения, read — ожидание **очередной порции** данных.
Сервер, присылающий байт раз в 20 секунд, никогда не превысит `read=30`, а запрос длится сколько угодно.

</details>

**A3.** Зачем `raise_for_status()`? Что будет без него, если API вернул 500 с HTML?

<details><summary>Ответ</summary>

Превращает 4xx/5xx в исключение `HTTPError`. Без него скрипт попытается разобрать HTML
как JSON (`JSONDecodeError`) или получит dict без нужных ключей (`KeyError`) далеко от причины.

</details>

**A4.** Зачем `requests.Session`? Назови три преимущества.

<details><summary>Ответ</summary>

Переиспользование TCP/TLS-соединений (быстрее), общие заголовки и авторизация,
общая политика ретраев через адаптер, cookies.

</details>

**A5.** ⭐ Какие ошибки имеет смысл ретраить, а какие нет? Почему?

<details><summary>Ответ</summary>

Ретраить: сетевые ошибки, таймауты, 429, 502, 503, 504 — временные проблемы. Не ретраить:

</details>

**A6.** Что такое идемпотентность и почему нельзя бездумно ретраить `POST`?

<details><summary>Ответ</summary>

Повтор запроса даёт тот же эффект, что и один запрос. `GET`, `PUT`, `DELETE` идемпотентны,
`POST` — нет: если ответ потерялся, а запрос выполнился, повтор создаст второй объект.

</details>

**A7.** Что такое экспоненциальная задержка и jitter? Зачем jitter?

<details><summary>Ответ</summary>

Пауза перед повтором растёт в геометрической прогрессии (1, 2, 4, 8...). Jitter — случайная
добавка, чтобы множество клиентов не повторяли запросы синхронно и не создавали волну нагрузки.

</details>

**A8.** Чем отличаются ретраи через `urllib3.Retry` и через tenacity? Когда что удобнее?

<details><summary>Ответ</summary>

`urllib3.Retry` — прозрачно на уровне транспорта, для статусов и сетевых ошибок, уважает
`Retry-After`. tenacity — декоратор на любую функцию: свои условия, логирование попыток,
ретраи всей операции (запрос + проверка ответа), не только HTTP.

</details>

**A9.** Какие бывают виды пагинации? Как узнать следующую страницу в GitLab API?

<details><summary>Ответ</summary>

`page/per_page` (с заголовками или `Link`), cursor/keyset (ссылка/токен на следующую
страницу), `offset/limit`. GitLab — заголовки `X-Next-Page` и `Link: <...>; rel="next"`.

</details>

**A10.** Что такое rate limit, код 429 и заголовок `Retry-After`?

<details><summary>Ответ</summary>

Ограничение числа запросов за окно времени. 429 — «слишком много запросов»,
`Retry-After` — через сколько секунд (или когда) можно повторить.

</details>

**A11.** Чем `json=payload` отличается от `data=payload` в `requests.post`?

<details><summary>Ответ</summary>

`json=` сериализует в JSON и ставит `Content-Type: application/json`; `data=` с dict
отправляет форму `application/x-www-form-urlencoded`.

</details>

**A12.** Как правильно работать с внутренним API на корпоративном сертификате? Почему не `verify=False`?

<details><summary>Ответ</summary>

Указать CA-бандл: `verify="/etc/ssl/certs/corp-ca.pem"` или `REQUESTS_CA_BUNDLE`,
либо добавить CA в системное хранилище. `verify=False` отключает проверку сервера: подмену (MITM)
и утечку токена не заметишь.

</details>

**A13.** Почему потоки (`ThreadPoolExecutor`) ускоряют проверку 50 URL, несмотря на GIL?

<details><summary>Ответ</summary>

Потоки почти всё время ждут сеть, а на ожидании I/O GIL отпускается — ожидания идут параллельно.

</details>

**A14.** Чем httpx отличается от requests? Назови четыре отличия.

<details><summary>Ответ</summary>

Таймаут по умолчанию 5 с; не следует за редиректами без `follow_redirects=True`; есть
`AsyncClient`; поддержка HTTP/2; встроенные ретраи транспорта только на ошибках соединения.

</details>

**A15.** Где в Telegram Bot API прячется токен и почему это важно для логирования?

<details><summary>Ответ</summary>

Прямо в URL: `https://api.telegram.org/bot&lt;TOKEN&gt;/sendMessage`. Сообщения исключений
requests содержат URL — `log.error("%s", e)` отправит токен в логи.

</details>

---

### Блок B. «Что выведет / что тут не так»


```text:no-line-numbers
# B1.
```text
```text:no-line-numbers
r = requests.get("https://api.internal/v1/deploys")
```text
```text:no-line-numbers
for d in r.json():
```text
```text:no-line-numbers
    print(d["id"])
```text
```text:no-line-numbers
# B2.
```text
```text:no-line-numbers
r = requests.get(url, timeout=10)
```text
```text:no-line-numbers
if r.status_code == 200:
```text
```text:no-line-numbers
    data = r.json()
```text
```text:no-line-numbers
print(data["items"])
```text
```text:no-line-numbers
# B3.
```text
```text:no-line-numbers
retry = Retry(total=5, backoff_factor=1, status_forcelist=(500, 502, 503),
```text
```text:no-line-numbers
              allowed_methods=None)
```text
```text:no-line-numbers
session.mount("https://", HTTPAdapter(max_retries=retry))
```text
```text:no-line-numbers
session.post(f"{api}/projects/42/pipeline", json={"ref": "main"}, timeout=10)
```text
```text:no-line-numbers
# B4.
```text
```text:no-line-numbers
def fetch(url):
```text
```text:no-line-numbers
    for attempt in range(100):
```text
```text:no-line-numbers
        try:
```text
```text:no-line-numbers
            return requests.get(url, timeout=5).json()
```text
```text:no-line-numbers
        except Exception:
```text
```text:no-line-numbers
            continue
```text
```text:no-line-numbers
# B5.
```text
```text:no-line-numbers
r = requests.get(f"{api}/groups/42/projects", headers=h, timeout=10)
```text
```text:no-line-numbers
print(len(r.json()))                     # в группе 340 проектов
```text
```text:no-line-numbers
# B6.
```text
```text:no-line-numbers
requests.post(webhook, data={"text": "deploy ok"}, timeout=5)     # API ждёт JSON
```text
```text:no-line-numbers
# B7.
```text
```text:no-line-numbers
try:
```text
```text:no-line-numbers
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json=msg, timeout=5).raise_for_status()
```text
```text:no-line-numbers
except requests.RequestException as e:
```text
```text:no-line-numbers
    log.error("не отправилось: %s", e)
```text
```text:no-line-numbers
# B8.
```text
```text:no-line-numbers
r = requests.get("https://vault.corp.local/v1/sys/health", verify=False, timeout=5)
```text
```text:no-line-numbers
# B9.
```text
```text:no-line-numbers
send_telegram(f"<b>Ошибка:</b> {stderr}")     # stderr = "value must be < 10 & > 0"
```text
```text:no-line-numbers
# B10.
```text
```text:no-line-numbers
for url in urls:                          # 1000 запросов к одному API
```text
```text:no-line-numbers
    requests.get(url, headers=h, timeout=10)
```text
```text:no-line-numbers
# B11.
```text
```text:no-line-numbers
client = httpx.Client()
```text
```text:no-line-numbers
r = client.get("http://example.com/old-path")    # сервер отвечает 301
```text
```text:no-line-numbers
print(r.status_code)
```text
```text:no-line-numbers
# B12.
```text
```text:no-line-numbers
r = requests.delete(f"{api}/items/7", timeout=10)
```text
```text:no-line-numbers
r.raise_for_status()
```text
```text:no-line-numbers
print(r.json())                          # API отвечает 204 No Content
```text
---

### Блок C. Практика


### C1. Разминка с httpbin
**1.** `GET /get` с параметрами `env=prod&page=2` — убедись, что они пришли (`args` в ответе).
**2.** Пошли свой заголовок `X-Request-Id` и найди его в ответе `/headers`.

<details><summary>Ответ</summary>

1 — `ReadTimeout`; 2 — `ConnectTimeout` примерно через 2 с; 3 — не упадёт: байты приходят
каждые ~2 с, read-таймаут между ними не превышается.
```python
deadline = time.monotonic() + 8
with requests.get(url, stream=True, timeout=(3, 5)) as r:
    r.raise_for_status()
    chunks = []
    for chunk in r.iter_content(1024):
        chunks.append(chunk)
        if time.monotonic() > deadline:
            raise TimeoutError("общий дедлайн 8 с превышен")
```text
</details>

**3.** `POST /post` с `json=` и с `data=` — сравни поля `json`, `form` и `Content-Type` в ответе.

<details><summary>Ответ</summary>

«Капризный» сервис:
```python
from http.server import BaseHTTPRequestHandler, HTTPServer
n = 0
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        global n; n += 1
        self.send_response(503 if n <= 3 else 200); self.end_headers()
HTTPServer(("127.0.0.1", 8765), H).serve_forever()
```text
С `backoff_factor=1` паузы 0, 2, 4 с — проходит на 4-й попытке примерно через 6 с.
После исчерпания попыток на `/status/503` — `requests.exceptions.RetryError`. `POST` не ретраится
(нет в `allowed_methods`). 404 — одна попытка: его нет в `status_forcelist`.

</details>

**4.** Проверь `/bearer` с токеном из переменной окружения и без него (коды 200/401).
### C2. 🔑 Таймауты
**1.** `GET /delay/10` с `timeout=3` — какое исключение?
**2.** `GET http://10.255.255.1` с `timeout=(2, 10)` — какое исключение и через сколько секунд?

<details><summary>Ответ</summary>

1 — `ReadTimeout`; 2 — `ConnectTimeout` примерно через 2 с; 3 — не упадёт: байты приходят
каждые ~2 с, read-таймаут между ними не превышается.
```python
deadline = time.monotonic() + 8
with requests.get(url, stream=True, timeout=(3, 5)) as r:
    r.raise_for_status()
    chunks = []
    for chunk in r.iter_content(1024):
        chunks.append(chunk)
        if time.monotonic() > deadline:
            raise TimeoutError("общий дедлайн 8 с превышен")
```text
</details>

**3.** `GET /drip?duration=20&numbytes=10` с `timeout=5` — упадёт ли запрос? Почему?

<details><summary>Ответ</summary>

«Капризный» сервис:
```python
from http.server import BaseHTTPRequestHandler, HTTPServer
n = 0
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        global n; n += 1
        self.send_response(503 if n <= 3 else 200); self.end_headers()
HTTPServer(("127.0.0.1", 8765), H).serve_forever()
```text
С `backoff_factor=1` паузы 0, 2, 4 с — проходит на 4-й попытке примерно через 6 с.
После исчерпания попыток на `/status/503` — `requests.exceptions.RetryError`. `POST` не ретраится
(нет в `allowed_methods`). 404 — одна попытка: его нет в `status_forcelist`.

</details>

**4.** Реализуй общий дедлайн: запрос с `stream=True`, чтение `iter_content` и проверка
   `time.monotonic()` — прерывать, если суммарно дольше 8 секунд.
### C3. 🔑 Ретраи на urllib3.Retry
**1.** Собери `make_session()` из конспекта.
**2.** Подними «капризный» сервис (3 первых запроса — 503, дальше 200) — например, маленький
   `http.server` на Python — и убедись, что запрос проходит с 4-й попытки. Замерь паузы.

<details><summary>Ответ</summary>

1 — `ReadTimeout`; 2 — `ConnectTimeout` примерно через 2 с; 3 — не упадёт: байты приходят
каждые ~2 с, read-таймаут между ними не превышается.
```python
deadline = time.monotonic() + 8
with requests.get(url, stream=True, timeout=(3, 5)) as r:
    r.raise_for_status()
    chunks = []
    for chunk in r.iter_content(1024):
        chunks.append(chunk)
        if time.monotonic() > deadline:
            raise TimeoutError("общий дедлайн 8 с превышен")
```text
</details>

**3.** `GET /status/503` на httpbin — какое исключение после исчерпания попыток?

<details><summary>Ответ</summary>

«Капризный» сервис:
```python
from http.server import BaseHTTPRequestHandler, HTTPServer
n = 0
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        global n; n += 1
        self.send_response(503 if n <= 3 else 200); self.end_headers()
HTTPServer(("127.0.0.1", 8765), H).serve_forever()
```text
С `backoff_factor=1` паузы 0, 2, 4 с — проходит на 4-й попытке примерно через 6 с.
После исчерпания попыток на `/status/503` — `requests.exceptions.RetryError`. `POST` не ретраится
(нет в `allowed_methods`). 404 — одна попытка: его нет в `status_forcelist`.

</details>

**4.** Убедись, что `POST /status/503` не ретраится.
**5.** `GET /status/404` — сколько попыток? Почему?

<details><summary>Ответ</summary>

Для большой группы запросов = `ceil(N / 100)`; `RateLimit-Remaining` уменьшается с каждым.

</details>

### C4. tenacity
Перепиши C3 на tenacity: ретраить сеть и 429/5xx, 5 попыток, `wait_exponential_jitter`,
логировать каждую повторную попытку через `before_sleep_log`. Сравни объём и гибкость.

### C5. 🔑 Пагинация GitLab
**1.** Получи список своих проектов: `GET /api/v4/projects?membership=true` — без пагинации и с генератором `paginate()`.
**2.** Возьми публичную группу с большим числом проектов (например, `gitlab-org`), посчитай проекты
   с `per_page=100`. Сколько запросов ушло?

<details><summary>Ответ</summary>

1 — `ReadTimeout`; 2 — `ConnectTimeout` примерно через 2 с; 3 — не упадёт: байты приходят
каждые ~2 с, read-таймаут между ними не превышается.
```python
deadline = time.monotonic() + 8
with requests.get(url, stream=True, timeout=(3, 5)) as r:
    r.raise_for_status()
    chunks = []
    for chunk in r.iter_content(1024):
        chunks.append(chunk)
        if time.monotonic() > deadline:
            raise TimeoutError("общий дедлайн 8 с превышен")
```text
</details>

**3.** Выведи заголовки `X-Next-Page`, `X-Total-Pages`, `Link`, `RateLimit-Remaining` первого ответа.

<details><summary>Ответ</summary>

«Капризный» сервис:
```python
from http.server import BaseHTTPRequestHandler, HTTPServer
n = 0
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        global n; n += 1
        self.send_response(503 if n <= 3 else 200); self.end_headers()
HTTPServer(("127.0.0.1", 8765), H).serve_forever()
```text
С `backoff_factor=1` паузы 0, 2, 4 с — проходит на 4-й попытке примерно через 6 с.
После исчерпания попыток на `/status/503` — `requests.exceptions.RetryError`. `POST` не ретраится
(нет в `allowed_methods`). 404 — одна попытка: его нет в `status_forcelist`.

</details>

### C6. Упавшие пайплайны
Доведи скрипт `failed_pipelines.py` из конспекта до рабочего состояния для своей группы или проекта:
вывод таблицей, `--hours`, `--json` (данные в stdout, логи в stderr), код выхода 1, если есть упавшие.

### C7. 🔑 Telegram-уведомление
**1.** Создай бота у @BotFather, напиши ему, получи `chat_id` через `getUpdates`.
**2.** Реализуй `send_telegram(text, silent=False)` с HTML-разметкой и `html.escape` для внешних данных.

<details><summary>Ответ</summary>

1 — `ReadTimeout`; 2 — `ConnectTimeout` примерно через 2 с; 3 — не упадёт: байты приходят
каждые ~2 с, read-таймаут между ними не превышается.
```python
deadline = time.monotonic() + 8
with requests.get(url, stream=True, timeout=(3, 5)) as r:
    r.raise_for_status()
    chunks = []
    for chunk in r.iter_content(1024):
        chunks.append(chunk)
        if time.monotonic() > deadline:
            raise TimeoutError("общий дедлайн 8 с превышен")
```text
</details>

**3.** Отправь сообщение с `<`, `>` и `&` в тексте — без экранирования и с ним.

<details><summary>Ответ</summary>

«Капризный» сервис:
```python
from http.server import BaseHTTPRequestHandler, HTTPServer
n = 0
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        global n; n += 1
        self.send_response(503 if n <= 3 else 200); self.end_headers()
HTTPServer(("127.0.0.1", 8765), H).serve_forever()
```text
С `backoff_factor=1` паузы 0, 2, 4 с — проходит на 4-й попытке примерно через 6 с.
После исчерпания попыток на `/status/503` — `requests.exceptions.RetryError`. `POST` не ретраится
(нет в `allowed_methods`). 404 — одна попытка: его нет в `status_forcelist`.

</details>

**4.** Сделай так, чтобы при ошибке в логах не было токена (проверь, подменив токен на неверный).
### C8. 🔑 Health-checker
`healthcheck.py --config urls.yaml`:
```text:no-line-numbers
targets:
```text
```text:no-line-numbers
  - name: httpbin-ok
```text
```text:no-line-numbers
    url: http://localhost:8080/status/200
```text
```text:no-line-numbers
  - name: httpbin-slow
```text
```text:no-line-numbers
    url: http://localhost:8080/delay/3
```text
```text:no-line-numbers
    timeout: 2
```text
```text:no-line-numbers
  - name: httpbin-500
```text
```text:no-line-numbers
    url: http://localhost:8080/status/500
```text
```text:no-line-numbers
    expect_status: 200
```text
- параллельная проверка (`ThreadPoolExecutor`), таймаут на цель (дефолт 5 с);
- таблица: имя, статус, время, ошибка; код выхода 1 при любой неудаче;
- с `--notify` — одно сводное сообщение в Telegram только о проблемных целях.

### C9. Потоки против asyncio
Проверь 50 раз `http://localhost:8080/delay/1` тремя способами: последовательно, `ThreadPoolExecutor(20)`,
`httpx.AsyncClient` + `asyncio.gather`. Замерь время каждого варианта.

### C10. Ограничитель скорости
Напиши класс `RateLimiter(rate_per_sec)` с методом `wait()`, который гарантирует не больше N
вызовов в секунду, и прогони через него 30 запросов к httpbin при `rate=5`. Сколько заняло?

---

### Блок D. Инциденты


**D1.** Nightly CI-job раз в неделю висит до таймаута в 1 час на шаге «получить список релизов». Что в коде почти наверняка не так?

<details><summary>Ответ</summary>

Нет `timeout` в запросе: раз в неделю API или сеть «подвисают», и запрос ждёт бесконечно.

</details>

**D2.** После сетевого сбоя скрипт релиза создал три одинаковых пайплайна и три тега. Почему?

<details><summary>Ответ</summary>

Ретраился неидемпотентный `POST` (ретраи на уровне Session с `allowed_methods=None`
или ручной цикл): запросы доходили, а ответы терялись. Не ретраить `POST` или использовать
ключ идемпотентности/проверять, создан ли объект.

</details>

**D3.** Отчёт по группе показывает 20 проектов, а в группе их 340. Что забыто?

<details><summary>Ответ</summary>

Пагинация: без неё GitLab отдаёт первые 20.

</details>

**D4.** Токен Telegram-бота нашли в логах Loki. В коде только `log.error("ошибка отправки: %s", e)`. Как он туда попал?

<details><summary>Ответ</summary>

Сообщение исключения requests содержит URL запроса, а в URL Telegram — токен.
Логировать только статус и `description` ответа, исключения — без URL.

</details>

**D5.** Скрипт к внутреннему API падает с `SSLError: CERTIFICATE_VERIFY_FAILED`. Коллега предлагает `verify=False`. Что предложишь вместо этого?

<details><summary>Ответ</summary>

Получить корневой/промежуточный сертификат компании и указать `verify="/path/ca.pem"`
(или `REQUESTS_CA_BUNDLE`, или добавить в системное хранилище через `update-ca-certificates`
— но requests по умолчанию берёт бандл `certifi`, поэтому переменная надёжнее).

</details>

**D6.** Ночной скрипт массовой правки через API после 300-го запроса получает 429 и помечает оставшиеся 700 объектов как «ошибка». Как переделать?

<details><summary>Ответ</summary>

Уважать `Retry-After` (ретраи на 429 с паузой), заранее ограничивать скорость (RateLimiter,
меньше потоков), смотреть `RateLimit-Remaining`, продолжать с места остановки, а не помечать как ошибку.

</details>

**D7.** `r.json()` иногда падает с `JSONDecodeError: Expecting value: line 1 column 1`. API «всегда отвечает JSON». Что может приходить на самом деле?

<details><summary>Ответ</summary>

HTML-страница ошибки от балансировщика/прокси (502/504), пустой ответ 204, редирект
на страницу логина, обрезанный ответ. Проверять статус и `Content-Type` до `r.json()`.

</details>

**D8.** Во время аварии health-checker каждую минуту шлёт в Telegram одно и то же, и чат «утонул». Как исправить?

<details><summary>Ответ</summary>

Хранить состояние (файл/Redis): уведомлять только при смене статуса (ok → fail и fail → ok),
повторять напоминание не чаще раза в N минут, группировать проблемы в одно сообщение.
А в перспективе — Alertmanager с группировкой.

</details>

**D9.** Скрипт работает с ноутбука, а на сервере в корпоративной сети не достукивается до внешнего API, хотя `curl` с сервера работает. Что проверить?

<details><summary>Ответ</summary>

Переменные прокси: у `curl` в шелле `HTTPS_PROXY` есть, а у скрипта (cron/systemd) — нет;
или `NO_PROXY` не включает внутренние адреса. Проверить `env | grep -i proxy` в окружении запуска.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как сделать надёжный HTTP-запрос из скрипта?

<details><summary>Ответ</summary>

Таймаут, `raise_for_status`, ретраи с backoff и jitter только для идемпотентных запросов и временных
   ошибок, лимит попыток, Session, токен из env.

</details>

**2.** Какие ошибки стоит ретраить и как?

<details><summary>Ответ</summary>

Сеть, таймауты, 429, 502/503/504 — с экспоненциальной паузой и лимитом; 4xx — не ретраить.

</details>

**3.** Что такое экспоненциальная задержка и jitter?

<details><summary>Ответ</summary>

Пауза растёт ×2 после каждой неудачи; jitter — случайная добавка против синхронных волн повторов.

</details>

**4.** Что такое идемпотентность HTTP-методов?

<details><summary>Ответ</summary>

Повтор даёт тот же результат: GET, PUT, DELETE, HEAD — да; POST — нет.

</details>

**5.** Как пройти все страницы ответа API?

<details><summary>Ответ</summary>

Цикл/генератор по `Link: rel="next"`, `X-Next-Page` или cursor до пустой следующей страницы.

</details>

**6.** Что делать при 429?

<details><summary>Ответ</summary>

Подождать `Retry-After`, снизить скорость/параллельность, повторить.

</details>

**7.** Как хранить и передавать токены для API в скриптах и CI?

<details><summary>Ответ</summary>

Переменные окружения / masked-переменные CI / Vault; минимальные права; не в git, не в аргументах, не в логах.

</details>

**8.** Как проверить 100 URL быстро?

<details><summary>Ответ</summary>

`ThreadPoolExecutor` на 20-50 потоков или `httpx.AsyncClient` + `asyncio.gather` с лимитом соединений.

</details>

**9.** Чем отличаются requests и httpx?

<details><summary>Ответ</summary>

httpx: таймаут по умолчанию, async, HTTP/2, редиректы только явно; requests: проще, больше примеров,
   ретраи через `urllib3.Retry`.

</details>

**10.** Как отправить уведомление в Telegram из скрипта?

<details><summary>Ответ</summary>

`POST https://api.telegram.org/bot&lt;TOKEN&gt;/sendMessage` с `chat_id` и `text`, таймаутом,
    экранированием HTML и без логирования URL.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Ставлю `timeout` в каждый запрос и понимаю connect vs read
- [ ] Вызываю `raise_for_status()` и проверяю `Content-Type` перед `json()`
- [ ] Собираю `Session` с ретраями `urllib3.Retry` и знаю, что ретраить
- [ ] Умею ретраи на tenacity с jitter и логированием
- [ ] Не ретраю `POST` без идемпотентности
- [ ] Прохожу пагинацию GitLab генератором
- [ ] Обрабатываю 429 и ограничиваю скорость
- [ ] Отправляю уведомления в Telegram без утечки токена и с `html.escape`
- [ ] Проверяю десятки URL параллельно потоками, сотни — через asyncio
- [ ] Беру токены только из окружения, с минимальными правами
