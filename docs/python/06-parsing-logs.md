---
title: "06. Разбор логов и отчёты"
description: "Блок → Python для DevOps → тема 6 из 8."
---

# 06. Разбор логов и отчёты

> Блок → **Python для DevOps** → тема 6 из 8.
> Аналог в bash: `grep | awk | sort | uniq -c | sort -rn` из [04_advanced_text_fu.md](/linux/04-advanced-text-fu).
> Пока задача укладывается в одну строку — бери awk. Когда нужны перцентили, группировки
> по нескольким полям, JSON-вывод и тесты — Python.
>
> **После темы ты умеешь:** писать регулярки с именованными группами, разбирать nginx access.log,
> CSV и JSON-lines, считать топы через `Counter` и группировки через `defaultdict`, обрабатывать
> файлы любого размера генераторами (включая `.gz` и stdin), считать перцентили и выдавать отчёт
> текстом, JSON или CSV с кодом выхода для алерта.

---

## 🗺️ Карта темы

```text
 ИСТОЧНИКИ                   РАЗБОР                  АГРЕГАЦИЯ                 ВЫВОД
 ─────────                   ──────                  ─────────                 ─────
 access.log, *.gz ──┐        re + (?P&lt;name&gt;...)      Counter → топ IP/URL      таблица (f-строки)
 journalctl -o json ┼─► генератор ──► dict ──►       defaultdict → по часам ─► JSON (для машин)
 app.jsonl          │   строк         или None       statistics → p50/p95/p99  CSV (в таблицы)
 export.csv ────────┘   (O(1) памяти) json.loads     фильтр по времени         код выхода (алерт)
                                      csv.DictReader
```text
---

## 1. Регулярные выражения в Python

```python
import re

DURATION_RE = re.compile(r"took (?P&lt;ms&gt;\d+)ms")        # ⭐ компилировать один раз, вне цикла

m = DURATION_RE.search("GET /api/users took 153ms")
if m:                                                  # нет совпадения → None
    ms = int(m.group("ms"))                            # или m["ms"], m.groupdict()
```text
| Метод | Что делает |
|-------|-----------|
| `p.search(s)` | Первое совпадение **где угодно** в строке |
| `p.match(s)` | Совпадение **с начала** строки (частая ошибка — ждать поиска по всей строке) |
| `p.fullmatch(s)` | Вся строка целиком |
| `p.findall(s)` | Список совпадений (с группами — список кортежей) |
| `p.finditer(s)` | Итератор объектов `Match` |
| `p.sub(repl, s)` | Замена: `re.sub(r"/\d+", "/{id}", path)` |

- Строки regex — всегда raw: `r"\d+\.\d+"`.
- `.*` жадный: в `"a" "b"` выражение `"(.*)"` захватит `a" "b`. Нужно `"([^"]*)"` или `.*?`.
- `re.VERBOSE` позволяет писать длинные выражения по строкам с комментариями.

---

## 2. ⭐ Разбор nginx access.log

Формат `combined` (плюс частое дополнение `$request_time` в конце):

```text
$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent" $request_time
10.0.0.7 - - [27/Sep/2026:10:15:32 +0300] "GET /api/users/42?x=1 HTTP/1.1" 200 512 "-" "curl/8.5.0" 0.153
```text
```python
import re
from datetime import datetime

LINE_RE = re.compile(
    r'(?P&lt;ip&gt;\S+) \S+ (?P&lt;user&gt;\S+) \[(?P&lt;time&gt;[^\]]+)\] '
    r'"(?P&lt;method&gt;[A-Z]+) (?P&lt;path&gt;\S+) [^"]*" '
    r'(?P&lt;status&gt;\d{3}) (?P&lt;size&gt;\d+|-) '
    r'"(?P&lt;referer&gt;[^"]*)" "(?P&lt;ua&gt;[^"]*)"'
    r'(?: (?P&lt;rt&gt;\d+(?:\.\d+)?))?'                 # $request_time — если есть
)

def parse_line(line: str) -> dict | None:
    m = LINE_RE.match(line)
    if not m:
        return None                                  # мусор, сканеры, битые строки — не падаем
    d = m.groupdict()
    return {
        "ip": d["ip"],
        "time": datetime.strptime(d["time"], "%d/%b/%Y:%H:%M:%S %z"),   # aware-дата с зоной
        "method": d["method"],
        "path": d["path"].split("?", 1)[0],          # без query string
        "status": int(d["status"]),
        "size": 0 if d["size"] == "-" else int(d["size"]),
        "ua": d["ua"],
        "rt": float(d["rt"]) if d["rt"] else None,
    }
```text
Строки вида `"\x16\x03\x01..."` (TLS-рукопожатие на HTTP-порт) или `"-" 400` не совпадут — их считают
отдельным счётчиком «нераспознано», а не роняют скрипт.

⭐ Если nginx твой — проще сразу писать JSON-лог, и regex не нужен:

```nginx
log_format json escape=json '{"time":"$time_iso8601","ip":"$remote_addr","method":"$request_method",'
                            '"uri":"$uri","status":$status,"bytes":$body_bytes_sent,"rt":$request_time}';
access_log /var/log/nginx/access.json.log json;
```text
---

## 3. Генераторы: файл любого размера, `.gz` и stdin

```python
import fileinput

def read_lines(files: list[str]):
    """Строки из файлов (.gz — прозрачно) или из stdin, если files пуст или '-'."""
    with fileinput.input(files or ["-"], openhook=fileinput.hook_compressed,
                         encoding="utf-8", errors="replace") as f:
        yield from f

lines = read_lines(["access.log", "access.log.1", "access.log.2.gz"])
records = (r for r in map(parse_line, lines) if r)           # конвейер генераторов
errors = (r for r in records if r["status"] >= 500)
for r in errors:                                             # память O(1) на любом объёме
    ...
```text
```bash
zcat /var/log/nginx/access.log.*.gz | ./top_nginx.py          # stdin
./top_nginx.py /var/log/nginx/access.log*                     # файлы, включая .gz
```text
⚠️ `f.read()` и `f.readlines()` на 5 ГБ логе — 5+ ГБ в памяти и OOM-kill.
⚠️ Без `errors="replace"` первая же строка с битыми байтами уронит разбор с `UnicodeDecodeError`.

---

## 4. Агрегация: Counter, defaultdict, перцентили

```python
from collections import Counter, defaultdict
import re

NUM_RE = re.compile(r"/\d+")

ips, statuses, paths = Counter(), Counter(), Counter()
rt_by_path = defaultdict(list)                          # ключ → список, без if key not in
errors_per_min = Counter()

for r in records:
    ips[r["ip"]] += 1
    statuses[r["status"]] += 1
    path = NUM_RE.sub("/{id}", r["path"])               # /users/42 → /users/{id}
    paths[path] += 1
    if r["rt"] is not None:
        rt_by_path[path].append(r["rt"])
    if r["status"] >= 500:
        errors_per_min[r["time"].strftime("%H:%M")] += 1

ips.most_common(10)                                     # [('10.0.0.7', 5123), ...]
sum(statuses.values())                                  # всего запросов
```text
**Перцентили:**

```python
import math, statistics

def percentile(values: list[float], p: float) -> float:
    """Nearest-rank: значение, меньше или равно которому p% наблюдений."""
    s = sorted(values)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]

q = statistics.quantiles(values, n=100, method="inclusive")   # 99 точек, нужно >= 2 значений
p50, p95, p99 = q[49], q[94], q[98]                           # интерполяция между точками
```text
Для десятков миллионов строк не храни все значения — считай корзины, как histogram в Prometheus:
`buckets[bisect.bisect_left(BOUNDS, rt)] += 1`.

⚠️ Нормализация путей обязательна: без неё «топ URL» — это миллион уникальных `/users/&lt;id&gt;`.

---

## 5. CSV

```python
import csv, sys

with open("export.csv", newline="", encoding="utf-8") as f:      # ⭐ newline="" для csv
    for row in csv.DictReader(f):                                # row — dict по заголовку
        print(row["host"], int(row["cpu"]))

writer = csv.DictWriter(sys.stdout, fieldnames=["path", "count", "p95"])
writer.writeheader()
writer.writerow({"path": "/api/users/{id}", "count": 5123, "p95": 0.412})
```text
Excel в русской локали ждёт разделитель `;` — `csv.writer(f, delimiter=";")`.

---

## 6. JSON-lines: journald, docker, приложения

```python
import json, logging

log = logging.getLogger(__name__)

def read_jsonl(lines):
    for n, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            log.warning("строка %d: не JSON: %.80s", n, line)
```text
| Источник | Как получить | Полезные поля |
|----------|--------------|---------------|
| journald | `journalctl -u nginx -o json --since "1 hour ago"` | `MESSAGE`, `PRIORITY` (0-7), `_SYSTEMD_UNIT`, `__REALTIME_TIMESTAMP` (мкс) |
| Docker json-file | `/var/lib/docker/containers/&lt;id&gt;/&lt;id&gt;-json.log` | `log`, `stream`, `time` |
| Приложение | свой JSON-логгер (тема 04) | `level`, `msg`, `ts`, контекст |
| nginx | `log_format ... escape=json` | всё, что задано в формате |

```python
r = subprocess.run(["journalctl", "-u", "nginx", "--since", "1 hour ago", "-o", "json", "--no-pager"],
                   capture_output=True, text=True, check=True, timeout=60)
errors = [e for e in read_jsonl(r.stdout.splitlines()) if int(e.get("PRIORITY", 6)) <= 3]
```text
⚠️ `MESSAGE` бывает не строкой, а массивом чисел — так journald кодирует сообщения с не-UTF-8 байтами.

---

## 7. Фильтр по времени

```python
from datetime import datetime, timedelta, timezone

since = datetime.now(timezone.utc) - timedelta(minutes=15)
recent = (r for r in records if r["time"] >= since)      # aware vs aware — зоны учтутся сами
```text
nginx пишет локальное время со смещением (`+0300`), `%z` делает дату aware — сравнение с UTC
корректно. ⚠️ Если в логе нет зоны, а сравниваешь с `datetime.now(timezone.utc)` — `TypeError`
или (хуже) тихий сдвиг на несколько часов при ручном `replace(tzinfo=...)`.

---

## 8. ⭐ Собираем: анализатор access.log

```python
#!/usr/bin/env python3
"""top_nginx — отчёт по nginx access.log: топ IP/URL, коды, 5xx, перцентили времени ответа."""
import argparse, json, sys
from collections import Counter, defaultdict
# LINE_RE, parse_line, read_lines, percentile, NUM_RE — из разделов выше


def analyze(lines) -> dict:
    total = bad = 0
    ips, statuses, paths = Counter(), Counter(), Counter()
    rts: list[float] = []
    rt_by_path = defaultdict(list)
    for line in lines:
        r = parse_line(line)
        if r is None:
            bad += 1
            continue
        total += 1
        path = NUM_RE.sub("/{id}", r["path"])
        ips[r["ip"]] += 1
        statuses[r["status"]] += 1
        paths[path] += 1
        if r["rt"] is not None:
            rts.append(r["rt"])
            rt_by_path[path].append(r["rt"])
    err5xx = sum(n for code, n in statuses.items() if code >= 500)
    return {
        "total": total, "unparsed": bad,
        "error_rate": err5xx / total if total else 0.0,
        "statuses": dict(sorted(statuses.items())),
        "top_ips": ips.most_common(10),
        "top_paths": paths.most_common(10),
        "latency": {f"p{p}": percentile(rts, p) for p in (50, 95, 99)} if rts else {},
        "slowest_paths": sorted(((p, percentile(v, 95)) for p, v in rt_by_path.items() if len(v) >= 20),
                                key=lambda x: x[1], reverse=True)[:5],
    }


def print_text(rep: dict) -> None:
    print(f"Запросов: {rep['total']:,} (нераспознано: {rep['unparsed']}), 5xx: {rep['error_rate']:.2%}")
    print("Коды:", "  ".join(f"{c}={n}" for c, n in rep["statuses"].items()))
    print("\nТоп IP:")
    for ip, n in rep["top_ips"]:
        print(f"  {ip:&lt;18}{n:&gt;10,}")
    print("\nТоп URL:")
    for path, n in rep["top_paths"]:
        print(f"  {path:&lt;45}{n:&gt;10,}")
    if rep["latency"]:
        print("\nВремя ответа:", "  ".join(f"{k}={v * 1000:.0f}ms" for k, v in rep["latency"].items()))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("files", nargs="*", help="логи (.gz тоже); без аргументов — stdin")
    p.add_argument("--json", action="store_true", help="вывести отчёт в JSON")
    p.add_argument("--max-error-rate", type=float, default=0.05, help="порог доли 5xx для кода 1")
    args = p.parse_args(argv)

    rep = analyze(read_lines(args.files))
    if args.json:
        json.dump(rep, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print_text(rep)
    return 1 if rep["error_rate"] > args.max_error_rate else 0


if __name__ == "__main__":
    sys.exit(main())
```text
```bash
./top_nginx.py /var/log/nginx/access.log*
./top_nginx.py --json access.log | jq '.latency'
zcat access.log.*.gz | ./top_nginx.py --max-error-rate 0.01 || echo "много 5xx!"
```text
---

## 9. Производительность

- Regex компилируется **один раз**; дешёвый предфильтр `if '" 5' not in line: continue` перед regex
  ускоряет выборку 5xx в разы.
- Python медленнее `grep`/`awk` в несколько раз, но гигабайт лога обрабатывает за десятки секунд — обычно
  достаточно. Нужно быстрее — предфильтр `zgrep` и передача через stdin.
- Разбор — **CPU-задача**: потоки не помогут (GIL). Много ротированных файлов → `ProcessPoolExecutor`,
  по процессу на файл, результаты `Counter` складываются (`total += c`).
- Хранить все значения ради перцентилей — O(n) памяти; для огромных объёмов — корзины.

---

## 10. Грабли

| Грабля | Что происходит | Правильно |
|--------|----------------|-----------|
| `re.match` вместо `re.search` | Совпадение ищется только с начала строки | `search` для поиска внутри |
| `"(.*)"` для полей в кавычках | Жадно съедает несколько полей | `"([^"]*)"` |
| `m.group(...)` без проверки `m` | `AttributeError: 'NoneType'` на первой битой строке | `if not m: return None` |
| `readlines()` / `read()` на большом файле | OOM | Итерация по файлу / генераторы |
| `open` без `errors="replace"` | `UnicodeDecodeError` на мусорных запросах | `encoding="utf-8", errors="replace"` |
| Топ URL без нормализации | Миллион «уникальных» путей | `re.sub(r"/\d+", "/{id}", path)`, без `?query` |
| Среднее вместо перцентилей | Хвост медленных запросов не виден | p95/p99 |
| Перцентили «среднее по серверам» | Математически бессмысленно | Собрать значения/корзины вместе, потом считать |
| `csv` без `newline=""` | Пустые строки, ломаются поля с переводами строк | `open(..., newline="")` |
| Забыты `.1` и `.gz` при ротации | Отчёт за сутки видит только последние часы | Все `access.log*` через `hook_compressed` |
| `statistics.quantiles` на 1 значении | `StatisticsError` | Проверять длину / свой `percentile()` |
| Потоки для разбора | Не быстрее из-за GIL | Процессы (`ProcessPoolExecutor`) |

---

## 💼 Как это в DevOps

- «Сколько 5xx было ночью и на каких эндпоинтах», «кто долбит API», «какой p99 после релиза» —
  типичные вопросы разбора инцидента, когда полноценного мониторинга логов ещё нет или он не покрывает случай.
- Скрипт-анализатор с кодом выхода встраивают в cron/CI: после деплоя прогнать по свежему логу
  и упасть, если доля 5xx выросла — простая форма canary-проверки.
- JSON-логи (nginx `escape=json`, приложения) снимают необходимость в regex и напрямую ложатся в Loki/ELK —
  стоит добиваться их везде, где есть влияние на формат.
- `journalctl -o json` и `kubectl ... -o json` — те же JSON-lines/JSON: разбор одинаковый.
- Результаты анализа часто превращают в метрики (textfile collector, тема 07) — и дальше алертят уже в Prometheus.

---

## 📌 Шпаргалка

| Хочу | Python |
|------|--------|
| Regex один раз | `RE = re.compile(r"...")` |
| Именованная группа | `(?P&lt;name&gt;...)` → `m["name"]` / `m.groupdict()` |
| Поле в кавычках | `"(?P&lt;ua&gt;[^"]*)"` |
| Нормализовать путь | `re.sub(r"/\d+", "/{id}", path.split("?", 1)[0])` |
| Дата nginx | `datetime.strptime(s, "%d/%b/%Y:%H:%M:%S %z")` |
| Файлы + .gz + stdin | `fileinput.input(files or ["-"], openhook=fileinput.hook_compressed, encoding="utf-8", errors="replace")` |
| Читать .gz | `gzip.open(p, "rt", encoding="utf-8", errors="replace")` |
| Топ-10 | `Counter(...).most_common(10)` |
| Группировка в списки | `defaultdict(list)` |
| Сложить счётчики | `c1 + c2` / `total.update(c)` |
| Перцентили | `statistics.quantiles(v, n=100)[94]` → p95 |
| CSV читать / писать | `csv.DictReader(f)` / `csv.DictWriter(f, fieldnames=...)` + `newline=""` |
| JSON-lines | `json.loads(line)` в `try/except JSONDecodeError` |
| journald | `journalctl -o json` → `PRIORITY <= 3` — ошибки |
| Отчёт в JSON | `json.dump(rep, sys.stdout, ensure_ascii=False, indent=2)` |

---

## 🧠 Что запомнить

1. Regex компилируй один раз, поля в кавычках — `[^"]*`, группы — именованные.
2. Строку, которая не разобралась, считают, а не роняют скрипт.
3. Файлы читаются построчно генераторами: память не зависит от размера лога.
4. `fileinput` + `hook_compressed` + `errors="replace"` — стандартный вход: файлы, `.gz`, stdin.
5. `Counter.most_common` — топы, `defaultdict(list)` — группировки.
6. Пути нормализуй (`/{id}`, без query) — иначе топы бессмысленны.
7. Время ответа — перцентилями, не средним; перцентили не усредняют между источниками.
8. Даты из логов — aware (`%z`), сравнение — с `datetime.now(timezone.utc)`.
9. Отчёт: человеку — таблица, машине — JSON в stdout, алерту — код выхода.
10. Разбор логов — CPU-задача: для ускорения процессы, а не потоки; а лучше — JSON-логи и Loki.

➡️ Дальше: [07_infra_libs.md](/python/07-infra-libs) · Задачи: 06_parsing_logs_tasks.md


---

### Блок A. Теория


**A1.** Чем `re.match`, `re.search` и `re.fullmatch` отличаются? Приведи пример, где путают.

<details><summary>Ответ</summary>

`match` — только с начала строки, `search` — первое вхождение где угодно, `fullmatch` — вся строка.
Путают, когда `re.match(r"ERROR", line)` не находит `2026-09-27 ERROR ...`.

</details>

**A2.** Зачем `re.compile` и где его вызывать?

<details><summary>Ответ</summary>

Чтобы разбирать шаблон один раз, а не на каждой строке (у `re` есть кэш, но явная компиляция
понятнее и надёжнее). Вызывать на уровне модуля, вне цикла.

</details>

**A3.** Что такое именованные группы и чем они удобнее нумерованных?

<details><summary>Ответ</summary>

`(?P&lt;name&gt;...)` — обращение по имени (`m["status"]`), `groupdict()` сразу даёт dict,
выражение читается и не ломается при добавлении новых групп.

</details>

**A4.** Почему `"(.*)"` плохо ловит поле в кавычках? Как правильно?

<details><summary>Ответ</summary>

`.*` жадный и захватывает до последней кавычки в строке — несколько полей сразу.
Правильно `"([^"]*)"` (всё, кроме кавычки) или ленивый `.*?`.

</details>

**A5.** Как устроен формат `combined` nginx? Какие поля и в каком порядке?

<details><summary>Ответ</summary>

`$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent"`.

</details>

**A6.** ⭐ Почему логи читают построчно генераторами, а не `readlines()`?

<details><summary>Ответ</summary>

Генератор держит в памяти одну строку, объём файла не важен; `readlines()` грузит весь файл.

</details>

**A7.** Как одной конструкцией читать и обычные файлы, и `.gz`, и stdin?

<details><summary>Ответ</summary>

`fileinput.input(files or ["-"], openhook=fileinput.hook_compressed, encoding="utf-8", errors="replace")`.

</details>

**A8.** Что делает `Counter` и чем `most_common` заменяет `sort | uniq -c | sort -rn`?

<details><summary>Ответ</summary>

Словарь-счётчик: `Counter(iterable)` считает вхождения, `most_common(n)` — n самых частых
с количеством, одним вызовом.

</details>

**A9.** Зачем `defaultdict(list)`? Что было бы без него?

<details><summary>Ответ</summary>

Автоматически создаёт пустой список для нового ключа. Без него — `if key not in d: d[key] = []`
или `d.setdefault(key, []).append(x)`.

</details>

**A10.** ⭐ Почему время ответа описывают перцентилями, а не средним? Почему нельзя усреднять перцентили разных серверов?

<details><summary>Ответ</summary>

Среднее прячет «хвост»: 99 запросов по 50 мс и один на 10 с дают среднее ~150 мс, а p99 = 10 с.
Перцентиль — порядковая статистика: p95 объединённых данных не равен среднему p95 частей.

</details>

**A11.** Зачем нормализовать пути перед подсчётом топа?

<details><summary>Ответ</summary>

Иначе каждый `/users/123`, `/users/124` — отдельный путь, топ состоит из единичных запросов
и не показывает, какой эндпоинт нагружен.

</details>

**A12.** Зачем при работе с `csv` открывать файл с `newline=""`?

<details><summary>Ответ</summary>

Модуль `csv` сам управляет переводами строк; без `newline=""` на Windows появляются пустые строки,
а поля с переводами строк внутри кавычек разбираются неправильно.

</details>

**A13.** Что такое JSON-lines? Какие источники в DevOps отдают логи в этом формате?

<details><summary>Ответ</summary>

Один JSON-объект на строку. journald (`-o json`), Docker json-file, приложения с JSON-логгером,
nginx с `escape=json`, многие облачные экспорты.

</details>

**A14.** Как корректно фильтровать записи «за последние 15 минут», если в логе локальное время с `+0300`?

<details><summary>Ответ</summary>

Разбирать время с `%z` (aware-дата), сравнивать с `datetime.now(timezone.utc) - timedelta(minutes=15)`:
aware-даты сравниваются с учётом зон.

</details>

**A15.** Разбор большого лога медленный. Помогут ли потоки? Что поможет?

<details><summary>Ответ</summary>

Нет: разбор — CPU-задача, GIL не даст потокам работать параллельно. Помогут предфильтр подстрокой,
`ProcessPoolExecutor` по файлам, предварительный `grep`, а системно — JSON-логи и Loki/ELK.

</details>

---

### Блок B. «Что выведет / что тут не так»


```text:no-line-numbers
# B1.
```text
```text:no-line-numbers
import re
```text
```text:no-line-numbers
print(re.match(r"\d+", "code 500"), re.search(r"\d+", "code 500").group())
```text
```text:no-line-numbers
# B2.
```text
```text:no-line-numbers
line = '1.2.3.4 - - [...] "GET / HTTP/1.1" 200 5 "-" "curl/8" "extra"'
```text
```text:no-line-numbers
print(re.search(r'"(.*)"', line).group(1))
```text
```text:no-line-numbers
# B3.
```text
```text:no-line-numbers
m = LINE_RE.match(line)
```text
```text:no-line-numbers
status = int(m.group("status"))           # на строке с мусором
```text
```text:no-line-numbers
# B4.
```text
```text:no-line-numbers
print(re.findall(r"(\w+)=(\d+)", "a=1 b=2 c=x"))
```text
```text:no-line-numbers
# B5.
```text
```text:no-line-numbers
from collections import Counter
```text
```text:no-line-numbers
c = Counter(["200", "500", "200", "404", "200"])
```text
```text:no-line-numbers
print(c.most_common(2), c["302"])
```text
```text:no-line-numbers
# B6.
```text
```text:no-line-numbers
from collections import defaultdict
```text
```text:no-line-numbers
d = defaultdict(list)
```text
```text:no-line-numbers
d["/api"].append(0.1)
```text
```text:no-line-numbers
print(d["/health"], len(d))
```text
```text:no-line-numbers
# B7.
```text
```text:no-line-numbers
with open("/var/log/nginx/access.log") as f:
```text
```text:no-line-numbers
    lines = f.readlines()                 # файл 6 ГБ
```text
```text:no-line-numbers
# B8.
```text
```text:no-line-numbers
import statistics
```text
```text:no-line-numbers
print(statistics.mean([0.05] * 99 + [10.0]))
```text
```text:no-line-numbers
# B9.
```text
```text:no-line-numbers
p95_total = (p95_web1 + p95_web2 + p95_web3) / 3
```text
```text:no-line-numbers
# B10.
```text
```text:no-line-numbers
since = datetime.now() - timedelta(minutes=15)
```text
```text:no-line-numbers
recent = [r for r in records if r["time"] >= since]    # r["time"] получен через %z
```text
```text:no-line-numbers
# B11.
```text
```text:no-line-numbers
for line in gzip.open("access.log.2.gz"):
```text
```text:no-line-numbers
    if "500" in line:
```text
```text:no-line-numbers
        print(line)
```text
```text:no-line-numbers
# B12.
```text
```text:no-line-numbers
paths = Counter(r["path"] for r in records)     # path = "/api/users/8812?token=abc"
```text
```text:no-line-numbers
print(paths.most_common(5))
```text
---

### Блок C. Практика


### C1. Регулярки-разминка
Из строк вида `2026-09-27 10:15:32 INFO req_id=ab12 GET /api/users took 153ms` вытащи:
дату-время, уровень, `req_id`, метод, путь, длительность (int). Сделай одним `re.compile` с именованными группами.

### C2. 🔑 Парсер строки nginx
Напиши `LINE_RE` и `parse_line(line) -> dict | None` для формата `combined` + `$request_time`.
Проверь на пяти строках: нормальная, без `request_time`, с `-` вместо размера, с запросом `"\x16\x03\x01"`,
полный мусор. Две последние должны давать `None`.

### C3. 🔑 Топы
По логу на 200 тыс. строк выведи:
**1.** Топ-10 IP.

<details><summary>Ответ</summary>

```python
APP_RE = re.compile(
    r"(?P&lt;ts&gt;\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (?P&lt;level&gt;[A-Z]+) req_id=(?P&lt;req&gt;\w+) "
    r"(?P&lt;method&gt;[A-Z]+) (?P&lt;path&gt;\S+) took (?P&lt;ms&gt;\d+)ms"
)
m = APP_RE.search(line)
rec = {**m.groupdict(), "ms": int(m["ms"])} if m else None
```text
</details>

**2.** Топ-10 путей с нормализацией (`/{id}`, без query).
**3.** Распределение кодов ответа и долю 5xx.

<details><summary>Ответ</summary>

Минута-рекордсмен: `errors_per_min.most_common(1)`. Результат п.1 совпадает с awk-конвейером.

</details>

**4.** Число 5xx по минутам, минуту-рекордсмен.
Сравни результат п.1 с `awk '{print $1}' access.log | sort | uniq -c | sort -rn | head`.

<details><summary>Ответ</summary>

Среднее заметно ниже p95/p99 при экспоненциальном распределении — хвост «прячется».

</details>

### C4. Перцентили
**1.** Посчитай среднее, p50, p95, p99 времени ответа по всему логу.

<details><summary>Ответ</summary>

```python
APP_RE = re.compile(
    r"(?P&lt;ts&gt;\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (?P&lt;level&gt;[A-Z]+) req_id=(?P&lt;req&gt;\w+) "
    r"(?P&lt;method&gt;[A-Z]+) (?P&lt;path&gt;\S+) took (?P&lt;ms&gt;\d+)ms"
)
m = APP_RE.search(line)
rec = {**m.groupdict(), "ms": int(m["ms"])} if m else None
```text
</details>

**2.** То же по каждому нормализованному пути (только пути с ≥ 20 запросами).
**3.** Объясни разницу между средним и p99 на своих цифрах.

<details><summary>Ответ</summary>

Минута-рекордсмен: `errors_per_min.most_common(1)`. Результат п.1 совпадает с awk-конвейером.

</details>

### C5. 🔑 Анализатор целиком
Собери `top_nginx.py` из конспекта:
- файлы (включая `.gz`) или stdin;
- `--json` — отчёт в stdout, логи — в stderr;
- `--max-error-rate` — код 1 при превышении;
- `--since 15m` — только записи за последние N минут/часов (разбор `15m`, `2h`).
Проверь: `zcat access.log.gz | ./top_nginx.py --json | jq .error_rate`.

### C6. journald
Выведи топ-5 systemd-юнитов по числу сообщений уровня `err` и выше за последние сутки:
`journalctl -p err --since "24 hours ago" -o json` → группировка по `_SYSTEMD_UNIT`
(у части записей его нет — считай их как `kernel/other`).

### C7. CSV
**1.** Сохрани «топ путей с count, p50, p95» в `report.csv` через `DictWriter`.

<details><summary>Ответ</summary>

```python
APP_RE = re.compile(
    r"(?P&lt;ts&gt;\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (?P&lt;level&gt;[A-Z]+) req_id=(?P&lt;req&gt;\w+) "
    r"(?P&lt;method&gt;[A-Z]+) (?P&lt;path&gt;\S+) took (?P&lt;ms&gt;\d+)ms"
)
m = APP_RE.search(line)
rec = {**m.groupdict(), "ms": int(m["ms"])} if m else None
```text
</details>

**2.** Сделай версию с `delimiter=";"` и открой в LibreOffice/Excel.
**3.** Прочитай файл обратно через `DictReader` и выведи пути с p95 > 300 мс.

<details><summary>Ответ</summary>

Минута-рекордсмен: `errors_per_min.most_common(1)`. Результат п.1 совпадает с awk-конвейером.

</details>

### C8. Логи Docker
Запусти контейнер, который пишет в stdout и stderr
(`docker run -d --name noisy alpine sh -c 'while true; do echo ok; echo fail >&2; sleep 1; done'`).
Найди его json-файл лога (`docker inspect -f '&#123;&#123;.LogPath&#125;&#125;' noisy`, нужен `sudo`) и посчитай строки
по `stream`, выведи последние 5 записей stderr с временем.

### C9. Скорость
**1.** Сгенерируй 2 млн строк, замерь время анализатора (`time`).

<details><summary>Ответ</summary>

```python
APP_RE = re.compile(
    r"(?P&lt;ts&gt;\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (?P&lt;level&gt;[A-Z]+) req_id=(?P&lt;req&gt;\w+) "
    r"(?P&lt;method&gt;[A-Z]+) (?P&lt;path&gt;\S+) took (?P&lt;ms&gt;\d+)ms"
)
m = APP_RE.search(line)
rec = {**m.groupdict(), "ms": int(m["ms"])} if m else None
```text
</details>

**2.** Добавь предфильтр подстрокой для режима «только 5xx» и замерь снова.
**3.** Разрежь лог на 4 файла (`split -n l/4`), обработай через `ProcessPoolExecutor` (по процессу на файл),
   сложи `Counter`'ы. Сравни время.

<details><summary>Ответ</summary>

Минута-рекордсмен: `errors_per_min.most_common(1)`. Результат п.1 совпадает с awk-конвейером.

</details>

### C10. Окно по времени
Сгенерируй лог с текущими датами (генератор из шапки) и посчитай долю 5xx только за последние 5 минут.
Убедись, что сравнение идёт aware-датами и не ломается, если часовой пояс машины — UTC, а в логе `+0300`.

---

### Блок D. Инциденты


**D1.** Анализатор месяц работал, а сегодня упал на строке 1 234 567: `AttributeError: 'NoneType' object has no attribute 'group'`. Что случилось и как сделать устойчиво?

<details><summary>Ответ</summary>

В лог попала строка другого формата (сканер, обрезанная запись, смена `log_format`), regex не
совпал, `m` — `None`. Возвращать `None`, считать нераспознанные строки и выводить их долю в отчёте.

</details>

**D2.** В отчёте «топ URL» 50 тысяч строк по одному запросу. Почему отчёт бесполезен и как исправить?

<details><summary>Ответ</summary>

Пути не нормализованы: id в пути и query string делают каждый запрос уникальным.
`re.sub(r"/\d+", "/{id}", path.split("?", 1)[0])` (плюс UUID-паттерн при надобности).

</details>

**D3.** На сервере с 2 ГБ памяти скрипт падает, в `dmesg` — `Out of memory: Killed process (python3)`. Лог — 8 ГБ. Что в коде?

<details><summary>Ответ</summary>

Весь файл читается в память (`read()`/`readlines()`/список всех записей) или все значения
копятся в списках. Итерация генераторами, агрегаты вместо сырых данных, корзины вместо списков времени.

</details>

**D4.** Скрипт показывает 0 ошибок «за последний час», хотя в логе их сотни. В коде даты разбираются без `%z` и сравниваются с `datetime.now(timezone.utc)` после `replace(tzinfo=timezone.utc)`. Что не так?

<details><summary>Ответ</summary>

Локальное время лога (`+0300`) помечено как UTC — сдвиг на 3 часа: «последний час» по UTC
смотрит в будущее относительно записей. Разбирать с `%z`, не подменять зону руками.

</details>

**D5.** После волны сканеров анализатор падает с `UnicodeDecodeError: 'utf-8' codec can't decode byte 0x16`. Что сделать?

<details><summary>Ответ</summary>

Открывать лог с `errors="replace"` (и `encoding="utf-8"`); строки, не подходящие под regex, считать нераспознанными.

</details>

**D6.** p99 в отчёте скрипта сильно отличается от p99 на дашборде Grafana. Назови три причины.

<details><summary>Ответ</summary>

Разные окна и выборки (лог за сутки vs `rate[5m]`); Grafana считает `histogram_quantile` по корзинам —
точность ограничена границами корзин; усреднение перцентилей по инстансам где-то в цепочке;
разные источники (лог балансировщика vs метрики приложения).

</details>

**D7.** Ежедневный отчёт в 09:00 не видит ночных ошибок. Логи ротируются logrotate в полночь. Почему?

<details><summary>Ответ</summary>

Скрипт читает только `access.log`, а ночь уже в `access.log.1`/`.gz`. Читать все `access.log*`
и фильтровать по времени.

</details>

**D8.** Отчёт в CSV открывается в Excel одной колонкой, а между строками пустые строки. Что поправить?

<details><summary>Ответ</summary>

Разделитель `;` для русской локали Excel и `newline=""` при открытии файла; при надобности
`encoding="utf-8-sig"` (BOM), чтобы Excel распознал UTF-8.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как найти топ-10 IP по access.log (bash и Python)?

<details><summary>Ответ</summary>

bash: `awk '{print $1}' access.log | sort | uniq -c | sort -rn | head`; Python: `Counter(...).most_common(10)`.

</details>

**2.** Как обработать лог в 10 ГБ на машине с 1 ГБ памяти?

<details><summary>Ответ</summary>

Построчно генератором, храня только агрегаты (Counter, корзины); `.gz` — через `gzip.open(..., "rt")`.

</details>

**3.** Как посчитать p95 времени ответа по логу?

<details><summary>Ответ</summary>

Собрать `$request_time` и взять `statistics.quantiles(values, n=100)[94]` или nearest-rank по отсортированным.

</details>

**4.** Чем search отличается от match в `re`?

<details><summary>Ответ</summary>

`match` — с начала строки, `search` — где угодно.

</details>

**5.** Как прочитать `.gz` лог без распаковки на диск?

<details><summary>Ответ</summary>

`gzip.open(path, "rt", encoding="utf-8")` или `zcat file | script`.

</details>

**6.** Почему JSON-логи удобнее текстовых?

<details><summary>Ответ</summary>

Поля без regex, типы, многострочные ошибки не разваливаются, прямой импорт в Loki/ELK.

</details>

**7.** Что такое `Counter` и `defaultdict`?

<details><summary>Ответ</summary>

`Counter` — словарь-счётчик с `most_common`; `defaultdict` — словарь с автосозданием значения по умолчанию.

</details>

**8.** Как ускорить разбор большого лога в Python?

<details><summary>Ответ</summary>

Компилировать regex, предфильтр подстрокой, не держать всё в памяти, процессы по файлам, предварительный grep.

</details>

**9.** Как узнать, сколько было 5xx за последние 15 минут?

<details><summary>Ответ</summary>

Разобрать время с зоной, отфильтровать `time >= now_utc - 15m`, посчитать `status >= 500`.

</details>

**10.** Когда разбор логов лучше отдать awk/grep, а когда писать на Python?

<details><summary>Ответ</summary>

awk/grep — разовые однострочники и простые подсчёты; Python — перцентили, группировки по нескольким
    полям, JSON-вывод, повторное использование и тесты.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Пишу regex с именованными группами и `[^"]*` для полей в кавычках
- [ ] Разбираю nginx combined в dict и не падаю на мусорных строках
- [ ] Читаю файлы, `.gz` и stdin генераторами через `fileinput`
- [ ] Считаю топы `Counter`, группировки `defaultdict`, нормализую пути
- [ ] Считаю p50/p95/p99 и объясняю, почему не среднее
- [ ] Разбираю JSON-lines (journald, docker) и пишу/читаю CSV
- [ ] Фильтрую по времени aware-датами
- [ ] Выдаю отчёт текстом, JSON и кодом выхода
- [ ] Знаю, как ускорить разбор (предфильтр, процессы) и почему не потоки
- [ ] Могу объяснить, когда хватает awk, а когда нужен Python
