---
title: "02. Python-минимум для скриптов"
description: "Блок → Python для DevOps → тема 2 из 8."
---

# 02. Python-минимум для скриптов

> Блок → **Python для DevOps** → тема 2 из 8.
> Это не курс Python с нуля, а сжатая шпаргалка для того, кто уже программирует на другом
> языке: что есть в Python, как это пишут в скриптах и где грабли.
>
> **После темы ты умеешь:** уверенно работать со строками и f-строками, списками, словарями
> и множествами, писать comprehension, функции, обрабатывать исключения, пользоваться `with`,
> type hints и dataclass — и обходить грабли, на которых спотыкаются пришедшие из других языков.

---

## 🗺️ Карта темы

```text
  ДАННЫЕ                      УПРАВЛЕНИЕ                   НАДЁЖНОСТЬ
  ──────                      ──────────                   ──────────
  str / bytes / f-строки      if / for / while             try / except / else / finally
  int / float / bool / None   comprehension                raise, raise ... from, свои ошибки
  list / tuple                функции: *args, **kwargs, *  with — контекстные менеджеры
  dict / set                  генераторы (yield)           type hints + dataclass
        └───────────────────── всё это нужно, чтобы ─────────────────────┘
              разбирать JSON и логи, звать API и не падать молча
```text
---

## 1. Типы и «истинность»

| Тип | Литерал | Заметка |
|-----|---------|---------|
| `int` | `42`, `1_000_000`, `0o755`, `0xff` | Без переполнения, любой длины |
| `float` | `3.14`, `1e9` | `0.1 + 0.2 != 0.3` |
| `bool` | `True`, `False` | Подкласс `int`: `True + True == 2` |
| `None` | `None` | «Нет значения», проверять через `is None` |
| `str` | `"text"`, `'text'`, `"""много строк"""` | Unicode, неизменяемая |
| `bytes` | `b"raw"` | Сырые байты: сеть, subprocess без `text=True` |
| `list` | `[1, 2]` | Изменяемый список |
| `tuple` | `(1, 2)`, `(1,)` | Неизменяемый; «вернуть несколько значений» |
| `dict` | `{"k": 1}` | Словарь, порядок вставки сохраняется |
| `set` | `{1, 2}`, `set()` | Уникальные элементы; `{}` — это пустой **dict** |

```python
# Ложные значения: 0, 0.0, "", [], {}, set(), None, False — всё остальное истинно
if not hosts:                 # пустой список
    sys.exit("список хостов пуст")
if port is None:              # ⭐ None — через is
    port = 22

int("42"); float("0.5"); str(42)
bool("False")                 # ⚠️ True: непустая строка
"1" + 1                       # TypeError — Python не приводит типы молча
```text
---

## 2. Строки и f-строки

```python
line = "  web1 10.0.0.5 running  \n"
line.strip()                        # 'web1 10.0.0.5 running'
line.split()                        # ['web1', '10.0.0.5', 'running'] — по любым пробелам
"a,b,,c".split(",")                 # ['a', 'b', '', 'c']
"key=value=x".partition("=")        # ('key', '=', 'value=x') — делит по первому
"/var/log/nginx".rsplit("/", 1)     # ['/var/log', 'nginx']
"v1.2.3".removeprefix("v")          # '1.2.3'
"app.log".endswith((".log", ".gz")) # можно кортеж вариантов
", ".join(["web1", "web2"])         # 'web1, web2' — join вызывают у разделителя
"ERROR" in line.upper()             # поиск подстроки
text.splitlines()                   # строки без \n
```text
```python
host, pct, n = "web1", 93.456, 1234567
f"{host}: {pct:.1f}%"               # 'web1: 93.5%'
f"{n:,}"                            # '1,234,567'
f"{host:&lt;10}|{n:&gt;12}"               # выравнивание в таблицах: влево / вправо
f"{host!r}"                         # "'web1'" — repr, видно пробелы и кавычки
f"{pct=}"                           # 'pct=93.456' — отладка
f"{datetime.now():%Y-%m-%d_%H%M}"   # формат даты прямо в f-строке
r"\d+\.\d+"                         # raw-строка: для regex и путей Windows
```text
**str vs bytes:** из сети, сокетов и `subprocess` без `text=True` приходят `bytes`.

```python
raw = b"caf\xc3\xa9 \xff"
raw.decode("utf-8")                    # UnicodeDecodeError из-за \xff
raw.decode("utf-8", errors="replace")  # 'café �' — для логов с мусором
"текст".encode("utf-8")                # str → bytes
```text
---

## 3. Коллекции

```python
# list
hosts = ["web1", "web2"]
hosts.append("web3"); hosts.extend(["db1", "db2"])
hosts[0], hosts[-1], hosts[:2], hosts[::-1]      # первый, последний, срез, разворот
first, *rest = hosts                             # распаковка
"db1" in hosts                                   # O(n)
sorted(servers, key=lambda s: s["cpu"], reverse=True)[:5]   # топ-5 по CPU

# dict
pod = {"name": "api-7d9", "status": {"phase": "Running"&#125;&#125;
pod["name"]                          # KeyError, если ключа нет
pod.get("labels", {})                # ⭐ безопасно, с дефолтом
pod.get("status", {}).get("phase")   # цепочка для вложенного JSON
pod.setdefault("labels", {})["app"] = "api"
for key, value in pod.items(): ...
merged = defaults | overrides        # слияние, правый выигрывает (3.9+)
pod.pop("tmp", None)                 # удалить, не падая

# set
inventory = {"web1", "web2", "db1"}
monitored = {"web1", "db1"}
inventory - monitored                # {'web2'} — есть в инвентори, нет в мониторинге
inventory & monitored                # пересечение
inventory | monitored                # объединение
```text
| Встроенная функция | Пример |
|--------------------|--------|
| `enumerate` | `for i, host in enumerate(hosts, start=1):` |
| `zip` | `for host, ip in zip(hosts, ips):` |
| `any` / `all` | `if any(r.status_code >= 500 for r in responses):` |
| `sum` / `min` / `max` | `max(pods, key=lambda p: p.restarts)` |
| `sorted` | Возвращает новый список; `list.sort()` сортирует на месте и возвращает `None` |

---

## 4. Comprehension и генераторы

```python
names   = [p["name"] for p in pods]                               # list
failed  = [p["name"] for p in pods if p["phase"] == "Failed"]     # с фильтром
by_name = {p["name"]: p["phase"] for p in pods}                   # dict
ns      = {p["namespace"] for p in pods}                          # set
total   = sum(p["restarts"] for p in pods)                         # генератор — без списка в памяти
```text
```python
def read_errors(path):          # функция-генератор: отдаёт по строке, память O(1)
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "ERROR" in line:
                yield line.rstrip("\n")

for err in read_errors("/var/log/app.log"):
    print(err)
```text
⚠️ Comprehension длиннее одной строки или с двумя вложенными `for` — перепиши обычным циклом.

---

## 5. Функции

```python
def check_port(host: str, port: int = 22, *, timeout: float = 3.0) -> bool:
    """True, если порт открыт. timeout — только именованный (после *)."""
    ...

check_port("web1")                      # port=22
check_port("web1", 443, timeout=1)      # check_port("web1", 443, 1) — TypeError

def run_all(*hosts: str, **opts) -> None:   # *args — кортеж, **kwargs — dict
    for h in hosts:
        check_port(h, **opts)

def disk_stats(path: str) -> tuple[int, int]:
    usage = shutil.disk_usage(path)
    return usage.used, usage.free           # вернуть «несколько значений»

used, free = disk_stats("/")
```text
Функции — обычные объекты: их передают как колбэки (`key=`, `ThreadPoolExecutor.map`).
Декоратор — функция, оборачивающая другую функцию:

```python
import functools, time

def timed(func):
    @functools.wraps(func)              # сохраняет имя и докстринг оригинала
    def wrapper(*args, **kwargs):
        start = time.monotonic()
        try:
            return func(*args, **kwargs)
        finally:
            log.info("%s: %.2fs", func.__name__, time.monotonic() - start)
    return wrapper

@timed
def backup(): ...
```text
---

## 6. ⭐ Исключения

```text
BaseException
 ├── SystemExit, KeyboardInterrupt        ← их НЕ ловят «случайно»
 └── Exception
      ├── OSError ── FileNotFoundError, PermissionError, TimeoutError, ConnectionError
      ├── ValueError ── json.JSONDecodeError, UnicodeDecodeError
      ├── KeyError, IndexError, TypeError
      ├── subprocess.CalledProcessError, subprocess.TimeoutExpired
      └── requests.RequestException ── ConnectionError, Timeout, HTTPError
```text
```python
class ConfigError(Exception):
    """Ошибка конфигурации — понятна пользователю, без traceback."""

def load_config(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"нет файла конфига: {path}") from None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path}: битый JSON, строка {e.lineno}") from e

def main() -> int:
    try:
        cfg = load_config(Path("config.json"))
    except ConfigError as e:
        log.error("%s", e)             # ожидаемая ошибка: коротко, код 2
        return 2
    except Exception:
        log.exception("неожиданная ошибка")   # неожиданная: с traceback, код 1
        return 1
    else:
        log.info("конфиг загружен: %d ключей", len(cfg))   # выполняется, если не было исключения
        return 0
    finally:
        cleanup()                      # выполняется ВСЕГДА
```text
Правила:
- Лови **конкретные** исключения там, где знаешь, что с ними делать.
- `except Exception` — только на верхнем уровне (`main`), с `log.exception`.
- ⚠️ Голый `except:` ловит и `KeyboardInterrupt`/`SystemExit` — скрипт не прервать Ctrl+C.
- `except ...: pass` — молча проглоченная ошибка, самая дорогая грабля в автоматизации.
- EAFP вместо LBYL: `path.unlink(missing_ok=True)` или `try/except FileNotFoundError`
  надёжнее, чем `if path.exists(): path.unlink()` (файл могут удалить между проверкой и действием).

---

## 7. Контекстные менеджеры (`with`)

`with` гарантирует освобождение ресурса даже при исключении — аналог `trap ... EXIT` в bash.

```python
with open("/etc/hosts", encoding="utf-8") as f:     # файл закроется сам
    data = f.read()

with open(src, "rb") as fin, open(dst, "wb") as fout:
    shutil.copyfileobj(fin, fout)

with tempfile.TemporaryDirectory() as tmp:          # каталог удалится сам
    ...

with contextlib.suppress(FileNotFoundError):        # «игнорировать именно это»
    Path("/tmp/app.lock").unlink()
```text
Свой менеджер через генератор:

```python
from contextlib import contextmanager

@contextmanager
def step(name: str):
    log.info("▶ %s", name)
    start = time.monotonic()
    try:
        yield
    except Exception:
        log.error("✖ %s упал через %.1fs", name, time.monotonic() - start)
        raise
    log.info("✔ %s за %.1fs", name, time.monotonic() - start)

with step("дамп базы"):
    run_dump()
```text
---

## 8. Type hints и dataclass

```python
from collections.abc import Iterator

def parse(lines: Iterator[str], limit: int | None = None) -> dict[str, int]: ...
```text
Подсказки типов **не проверяются** при запуске — их читают IDE, `mypy`/`pyright` и коллеги.
В скриптах пиши их хотя бы в сигнатурах функций.

```python
from dataclasses import dataclass, field, asdict

@dataclass
class Host:
    name: str
    ip: str
    port: int = 22
    tags: list[str] = field(default_factory=list)   # ⚠️ не tags: list = []

h = Host("web1", "10.0.0.5", tags=["web"])
print(h)                     # Host(name='web1', ip='10.0.0.5', port=22, tags=['web'])
h.port                       # атрибуты вместо h["port"] — опечатка сразу видна
asdict(h)                    # → dict → json.dumps(...)
Host(**{"name": "db1", "ip": "10.0.0.9", "prot": 5432})   # TypeError: unexpected 'prot'

@dataclass(frozen=True)      # неизменяемый: удобно для конфига
class Settings:
    endpoint: str
    timeout: float = 10.0
```text
---

## 9. Даты и время

```python
from datetime import datetime, timedelta, timezone

now = datetime.now(timezone.utc)               # ⭐ «aware» время с зоной
stamp = now.strftime("%Y-%m-%d_%H%M%S")         # имя файла бэкапа
cutoff = now - timedelta(days=7)
datetime.fromisoformat("2026-09-27T10:00:00Z")  # ISO-строка из API (Z понимается с 3.11)
time.time()          # epoch-секунды: для mtime файлов и метрик
time.monotonic()     # для замера длительности (не прыгает при смене системного времени)
```text
⚠️ Сравнение «naive» (`datetime.now()`) и «aware» дат → `TypeError`.
`datetime.utcnow()` устарел с 3.12 — пиши `datetime.now(timezone.utc)`.

---

## 10. Стандартная библиотека девопса

| Модуль | Для чего |
|--------|----------|
| `os`, `sys` | Переменные окружения, argv, выход |
| `pathlib`, `shutil`, `tempfile` | Файлы, каталоги, копирование, временные файлы (тема 03) |
| `subprocess`, `signal` | Внешние команды, сигналы (тема 03) |
| `argparse`, `logging`, `json`, `tomllib` | CLI, логи, конфиги (тема 04) |
| `urllib.request` | HTTP без внешних зависимостей (для совсем минимальных скриптов) |
| `re`, `csv`, `collections`, `statistics` | Разбор логов и отчёты (тема 06) |
| `concurrent.futures` | Параллельно опросить 50 хостов/URL |
| `socket`, `ssl`, `hashlib` | Проверка порта, срок сертификата, контрольные суммы |
| `tarfile`, `gzip`, `zipfile` | Архивы и сжатые логи |

---

## 11. Грабли для пришедших из других языков

| Грабля | Что происходит | Правильно |
|--------|----------------|-----------|
| `def f(items=[])` | Список создаётся **один раз** и копится между вызовами | `items=None`, внутри `if items is None: items = []` |
| `x is 1000`, `s is "ok"` | Сравнение идентичности, работает «через раз» | `==`; `is` — только для `None`, `True`, `False` |
| `b = a` для списка | Это та же ссылка: правка `b` меняет `a` | `a.copy()`, `copy.deepcopy(a)` |
| Удаление из списка/словаря в цикле по нему | Пропуски или `RuntimeError` | Итерироваться по копии или собрать новый |
| `result = hosts.sort()` | `None` | `sorted(hosts)` |
| `7 / 2` | `3.5` | Целочисленно — `7 // 2` |
| `round(2.5)` | `2` (банковское округление) | Осознанно или `decimal` |
| `open(p)` без `encoding` | Кодировка из локали: в контейнере с `LANG=C` — сюрпризы | `encoding="utf-8"` всегда |
| `json.dumps({1: "a"})` | Ключ станет строкой `"1"` | Помнить: ключи JSON — только строки |
| `("a")` | Это строка, не кортеж | `("a",)` |
| `list = [...]`, `id = 5`, `type = "x"` | Перекрыта встроенная функция | Другие имена: `hosts`, `pod_id`, `kind` |
| `[lambda: i for i in range(3)]` | Все вернут `2` (позднее связывание) | `lambda i=i: i` |
| `except:` / `except Exception: pass` | Ошибки исчезают бесследно | Конкретный тип + лог |

```python
def add_host(host, hosts=[]):       # ⚠️
    hosts.append(host)
    return hosts

add_host("web1")    # ['web1']
add_host("web2")    # ['web1', 'web2']  ← сюрприз
```text
---

## 💼 Как это в DevOps

- 80% кода скриптов — это разбор dict/list из JSON (API, `kubectl -o json`, `terraform show -json`)
  и строк из логов. `dict.get` с дефолтом и comprehension решают большую часть задач.
- Исключения — основа надёжности: ожидаемые ошибки превращаются в понятное сообщение
  и код выхода, неожиданные — в traceback в логе, но никогда не в тишину.
- dataclass вместо «словаря со строковыми ключами» ловит опечатки в полях конфига и делает
  код читаемым для коллег.
- Даты в UTC и aware-формате — иначе ротация бэкапов «съедает» не те файлы при смене часового пояса.
- На ревью Python-скриптов чаще всего находят: mutable default, голый `except`, `open` без
  `encoding`, отсутствие таймаутов (тема 05).

---

## 📌 Шпаргалка

| Хочу | Код |
|------|-----|
| Безопасно достать ключ | `d.get("k", default)` |
| Вложенный ключ JSON | `d.get("a", {}).get("b")` |
| Слить словари | `defaults \| overrides` |
| Уникальные значения | `set(items)` / `sorted(set(items))` |
| Разница двух списков | `set(a) - set(b)` |
| Фильтр списка | `[x for x in xs if cond(x)]` |
| Словарь из списка | `{x.name: x for x in xs}` |
| Топ-N | `sorted(xs, key=lambda x: x.v, reverse=True)[:n]` |
| Нумерация | `for i, x in enumerate(xs, 1):` |
| Строка-таблица | `f"{name:&lt;20}{count:&gt;8}"` |
| Число с разделителями | `f"{n:,}"` / `f"{x:.2f}"` |
| bytes → str | `b.decode("utf-8", errors="replace")` |
| Своё исключение | `class MyError(Exception): ...` |
| Сменить тип ошибки | `raise MyError("...") from e` |
| Гарантированная очистка | `try: ... finally: ...` / `with` |
| Игнорировать конкретную ошибку | `contextlib.suppress(FileNotFoundError)` |
| Структура с полями | `@dataclass` |
| Текущее время UTC | `datetime.now(timezone.utc)` |
| Длительность операции | `time.monotonic()` до и после |

---

## 🧠 Что запомнить

1. Проверка на `None` — через `is None`; всё остальное сравнивают `==`.
2. `dict.get()` с дефолтом — главный инструмент для чужого JSON.
3. Comprehension — для коротких преобразований; сложную логику — обычным циклом.
4. Генераторы (`yield`) обрабатывают файлы любого размера за O(1) памяти.
5. Лови конкретные исключения, `except Exception` — только в `main()` с `log.exception`.
6. `raise ... from e` сохраняет причину; своё исключение даёт понятное сообщение без traceback.
7. `with` освобождает ресурсы при любом исходе — это `trap EXIT` из мира Python.
8. Изменяемые значения по умолчанию (`[]`, `{}`) — грабля №1; в dataclass — `field(default_factory=...)`.
9. `open(..., encoding="utf-8")` всегда; время — `datetime.now(timezone.utc)`.
10. Type hints не проверяются при запуске, но делают скрипт понятным и ловят ошибки в IDE/mypy.

➡️ Дальше: [03_files_os_subprocess.md](/python/03-files-os-subprocess) · Задачи: 02_basics_for_scripts_tasks.md


---

### Блок A. Теория


**A1.** Какие значения в Python ложные? Почему `bool("False")` — это `True`?

<details><summary>Ответ</summary>

`0`, `0.0`, `""`, `[]`, `{}`, `set()`, `()`, `None`, `False`. `bool()` у строки проверяет
только пустоту — `"False"` непустая, значит истинна.

</details>

**A2.** Чем `is` отличается от `==`? Когда уместен `is`?

<details><summary>Ответ</summary>

`==` сравнивает значения, `is` — что это один и тот же объект. `is` уместен для синглтонов:
`None`, `True`, `False`.

</details>

**A3.** Чем `list` отличается от `tuple`, а `dict` от `set`? Как создать пустое множество?

<details><summary>Ответ</summary>

list изменяемый, tuple нет (годится как ключ словаря и для «возврата нескольких значений»).
dict — пары ключ-значение, set — только уникальные ключи. Пустое множество — `set()`, `{}` — это dict.

</details>

**A4.** Почему `d["key"]` и `d.get("key")` ведут себя по-разному? Что выбрать для JSON из API?

<details><summary>Ответ</summary>

`d["key"]` бросает `KeyError`, `d.get("key", default)` возвращает дефолт. Для чужого JSON —
`get`, потому что поля бывают необязательными.

</details>

**A5.** Что такое comprehension и когда его лучше не писать?

<details><summary>Ответ</summary>

Короткая запись построения list/dict/set из итерируемого: `[x for x in xs if ...]`.
Не пиши, если внутри побочные эффекты, два вложенных цикла или логика не помещается в строку.

</details>

**A6.** Что такое генератор и почему он важен для обработки логов?

<details><summary>Ответ</summary>

Функция с `yield` или выражение `(x for x in ...)`: значения вычисляются по одному по запросу.
Файл в гигабайты читается построчно за постоянную память.

</details>

**A7.** Что делают `*args`, `**kwargs` и одиночная `*` в сигнатуре функции?

<details><summary>Ответ</summary>

`*args` собирает лишние позиционные аргументы в кортеж, `**kwargs` — именованные в dict.
Одиночная `*` делает все следующие параметры только именованными.

</details>

**A8.** ⭐ Почему изменяемое значение по умолчанию (`def f(x=[])`) — ошибка? Как правильно?

<details><summary>Ответ</summary>

Значение по умолчанию вычисляется один раз при определении функции; список общий
для всех вызовов и копит данные. Правильно: `x=None` и `if x is None: x = []`.

</details>

**A9.** Объясни `try / except / else / finally`: когда выполняется каждая ветка?

<details><summary>Ответ</summary>

`try` — основной код; `except` — если было подходящее исключение; `else` — если исключения
не было; `finally` — всегда, даже при `return` и необработанном исключении.

</details>

**A10.** Зачем `raise ... from e` и чем `from None` отличается от `from e`?

<details><summary>Ответ</summary>

`from e` сохраняет исходную ошибку как причину (видна в traceback — удобно для отладки).
`from None` скрывает цепочку — когда исходная ошибка ничего не добавляет к понятному сообщению.

</details>

**A11.** Почему голый `except:` и `except Exception: pass` опасны в автоматизации?

<details><summary>Ответ</summary>

Ошибка исчезает бесследно: скрипт «успешен», мониторинг зелёный, а работа не сделана.
Голый `except` к тому же ловит `KeyboardInterrupt` и `SystemExit` — скрипт нельзя остановить.

</details>

**A12.** Что гарантирует `with`? Приведи четыре примера контекстных менеджеров из stdlib.

<details><summary>Ответ</summary>

Освобождение ресурса при любом исходе блока. Примеры: `open()`,
`tempfile.TemporaryDirectory()`, `requests.Session()`, `subprocess.Popen`, `threading.Lock()`,
`contextlib.suppress()`.

</details>

**A13.** Проверяются ли type hints при запуске? Зачем тогда их писать?

<details><summary>Ответ</summary>

Нет. Их используют IDE, `mypy`/`pyright` в CI и люди — это документация, которая не устаревает.

</details>

**A14.** Что даёт `@dataclass` по сравнению с обычным dict? Как задать поле-список по умолчанию?

<details><summary>Ответ</summary>

Именованные поля (опечатка — ошибка, а не молчаливый `None`), автоматические `__init__`,
`__repr__`, `__eq__`, значения по умолчанию, `asdict`. Список по умолчанию —
`field(default_factory=list)`.

</details>

**A15.** Чем «naive» дата отличается от «aware»? Почему для бэкапов и логов важна UTC?

<details><summary>Ответ</summary>

Aware-дата содержит часовой пояс, naive — нет. Сравнивать их нельзя. UTC исключает
сюрпризы с переходами времени и разными зонами серверов.

</details>

---

### Блок B. «Что выведет / что тут не так»


```text:no-line-numbers
# B1.
```text
```text:no-line-numbers
def add(host, hosts=[]):
```text
```text:no-line-numbers
    hosts.append(host)
```text
```text:no-line-numbers
    return hosts
```text
```text:no-line-numbers
add("web1"); print(add("web2"))
```text
```text:no-line-numbers
# B2.
```text
```text:no-line-numbers
a = [1, 2, 3]
```text
```text:no-line-numbers
b = a
```text
```text:no-line-numbers
b.append(4)
```text
```text:no-line-numbers
print(a)
```text
```text:no-line-numbers
# B3.
```text
```text:no-line-numbers
print(bool("0"), bool(0), bool([]), bool([0]), bool(None))
```text
```text:no-line-numbers
# B4.
```text
```text:no-line-numbers
d = {"a": 1}
```text
```text:no-line-numbers
print(d.get("b"), d.get("b", 0))
```text
```text:no-line-numbers
print(d["b"])
```text
```text:no-line-numbers
# B5.
```text
```text:no-line-numbers
hosts = ["web1", "web2", "db1"]
```text
```text:no-line-numbers
for h in hosts:
```text
```text:no-line-numbers
    if h.startswith("web"):
```text
```text:no-line-numbers
        hosts.remove(h)
```text
```text:no-line-numbers
print(hosts)
```text
```text:no-line-numbers
# B6.
```text
```text:no-line-numbers
x = sorted([3, 1, 2])
```text
```text:no-line-numbers
y = [3, 1, 2].sort()
```text
```text:no-line-numbers
print(x, y)
```text
```text:no-line-numbers
# B7.
```text
```text:no-line-numbers
print(7 / 2, 7 // 2, -7 // 2, round(2.5), round(3.5))
```text
```text:no-line-numbers
# B8.
```text
```text:no-line-numbers
try:
```text
```text:no-line-numbers
    int("3.5")
```text
```text:no-line-numbers
except ValueError as e:
```text
```text:no-line-numbers
    print("bad:", e)
```text
```text:no-line-numbers
finally:
```text
```text:no-line-numbers
    print("done")
```text
```text:no-line-numbers
# B9.
```text
```text:no-line-numbers
funcs = [lambda: i for i in range(3)]
```text
```text:no-line-numbers
print([f() for f in funcs])
```text
```text:no-line-numbers
# B10.
```text
```text:no-line-numbers
import json
```text
```text:no-line-numbers
print(json.dumps({1: "a", "b": None, "c": True}))
```text
```text:no-line-numbers
# B11.
```text
```text:no-line-numbers
t = ("web1")
```text
```text:no-line-numbers
print(type(t), len(t))
```text
```text:no-line-numbers
# B12.
```text
```text:no-line-numbers
while True:
```text
```text:no-line-numbers
    try:
```text
```text:no-line-numbers
        check_all_hosts()
```text
```text:no-line-numbers
        time.sleep(30)
```text
```text:no-line-numbers
    except:
```text
```text:no-line-numbers
        pass
```text
```text:no-line-numbers
# B13.
```text
```text:no-line-numbers
def f():
```text
```text:no-line-numbers
    try:
```text
```text:no-line-numbers
        return "try"
```text
```text:no-line-numbers
    finally:
```text
```text:no-line-numbers
        print("finally")
```text
```text:no-line-numbers
print(f())
```text
```text:no-line-numbers
# B14.
```text
```text:no-line-numbers
from datetime import datetime, timezone
```text
```text:no-line-numbers
print(datetime.now() < datetime.now(timezone.utc))
```text
```text:no-line-numbers
# B15.
```text
```text:no-line-numbers
seen = {}
```text
```text:no-line-numbers
seen.add("web1")
```text
```text:no-line-numbers
# B16.
```text
```text:no-line-numbers
print(f"{'web1':&lt;6}|{42:&gt;5}|{3.14159:.2f}|{1234567:,}")
```text
---

### Блок C. Практика


### C1. Разбор вывода команды
Дан вывод `df -P` (вставь свой или возьми этот):
```text:no-line-numbers
Filesystem     1024-blocks     Used Available Capacity Mounted on
```text
```text:no-line-numbers
/dev/sda1         41152736 35012345   4027812      90% /
```text
```text:no-line-numbers
tmpfs              2014028        0   2014028       0% /dev/shm
```text
```text:no-line-numbers
/dev/sdb1        103081248 51234567  46587845      53% /data
```text
**1.** Преврати его в список словарей `{"fs", "size", "used", "avail", "pct", "mount"}` (числа — `int`).

<details><summary>Ответ</summary>

```python
def parse_df(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines()[1:]:
        fs, size, used, avail, pct, mount = line.split(maxsplit=5)
        rows.append({"fs": fs, "size": int(size), "used": int(used),
                     "avail": int(avail), "pct": int(pct.rstrip("%")), "mount": mount})
    return rows

print([r["mount"] for r in parse_df(text) if r["pct"] > 80])
```text
</details>

**2.** Выведи точки монтирования, где занято больше 80%.

<details><summary>Ответ</summary>

```python
import json
from collections import Counter

pods = json.load(open("pods.json", encoding="utf-8"))["items"]
print(Counter(p["status"].get("phase", "Unknown") for p in pods))

def restarts(pod: dict) -> int:
    return sum(cs.get("restartCount", 0) for cs in pod["status"].get("containerStatuses", []))

noisy = sorted((p for p in pods if restarts(p) > 3), key=restarts, reverse=True)
for p in noisy:
    print(f'{p["metadata"]["namespace"]}/{p["metadata"]["name"]}: {restarts(p)}')
print({p["metadata"]["namespace"] for p in pods})
```text
</details>

**3.** Сделай то же на реальном выводе: `subprocess.run(["df", "-P"], capture_output=True, text=True).stdout`.

<details><summary>Ответ</summary>

`inventory - monitored` → `{'web2', 'web3'}`; `monitored - inventory` → `{'old-db'}`;
`inventory & monitored` → `{'web1', 'db1'}`.

</details>

### C2. 🔑 JSON подов
Получи `kubectl get pods -A -o json > pods.json` (или составь JSON из 5 подов вручную:
`metadata.name`, `metadata.namespace`, `status.phase`, `status.containerStatuses[].restartCount`).
**1.** Посчитай количество подов по `phase` (словарь).

<details><summary>Ответ</summary>

```python
def parse_df(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines()[1:]:
        fs, size, used, avail, pct, mount = line.split(maxsplit=5)
        rows.append({"fs": fs, "size": int(size), "used": int(used),
                     "avail": int(avail), "pct": int(pct.rstrip("%")), "mount": mount})
    return rows

print([r["mount"] for r in parse_df(text) if r["pct"] > 80])
```text
</details>

**2.** Выведи поды, у которых суммарных рестартов больше 3, отсортированные по убыванию.

<details><summary>Ответ</summary>

```python
import json
from collections import Counter

pods = json.load(open("pods.json", encoding="utf-8"))["items"]
print(Counter(p["status"].get("phase", "Unknown") for p in pods))

def restarts(pod: dict) -> int:
    return sum(cs.get("restartCount", 0) for cs in pod["status"].get("containerStatuses", []))

noisy = sorted((p for p in pods if restarts(p) > 3), key=restarts, reverse=True)
for p in noisy:
    print(f'{p["metadata"]["namespace"]}/{p["metadata"]["name"]}: {restarts(p)}')
print({p["metadata"]["namespace"] for p in pods})
```text
</details>

**3.** Выведи множество неймспейсов.

<details><summary>Ответ</summary>

`inventory - monitored` → `{'web2', 'web3'}`; `monitored - inventory` → `{'old-db'}`;
`inventory & monitored` → `{'web1', 'db1'}`.

</details>

**4.** Учти, что у Pending-подов может не быть `containerStatuses` — скрипт не должен падать.

<details><summary>Ответ</summary>

```python
class ConfigError(Exception): ...

def load_config(path: Path) -> dict:
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"нет файла {path}") from None
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path}: битый JSON (строка {e.lineno})") from e
    if "endpoint" not in cfg:
        raise ConfigError(f"{path}: нет обязательного ключа endpoint")
    return cfg
```text
</details>

### C3. Множества
Есть `inventory = {"web1", "web2", "web3", "db1"}` и `monitored = {"web1", "db1", "old-db"}`.
Выведи: что не под мониторингом; что мониторится, но уже удалено из инвентори; общее.

### C4. 🔑 Исключения
Напиши `load_config(path) -> dict` для JSON-файла со своим `ConfigError`:
- нет файла → `ConfigError("нет файла ...")`;
- битый JSON → `ConfigError` с номером строки;
- нет обязательного ключа `endpoint` → `ConfigError`.
`main()` возвращает 2 на `ConfigError` (короткое сообщение) и 1 на любую другую ошибку (с traceback).
Проверь все три сценария и коды выхода.

### C5. Контекстный менеджер
Напиши `step(name)` через `@contextmanager`: логирует начало, длительность и падение.
Оберни в него `time.sleep(1)` и функцию, которая бросает `RuntimeError`. Убедись, что
исключение не проглатывается.

### C6. dataclass
Опиши `@dataclass Host(name, ip, port=22, tags=[])` (правильно!). Загрузи список хостов
из JSON, отфильтруй по тегу `web`, сохрани обратно через `asdict` + `json.dump`.
Что будет, если в JSON попадёт лишний ключ?

### C7. Генератор против списка
**1.** Сгенерируй файл на 1 млн строк: `python3 -c 'import random; [print("ERROR" if random.random()<.01 else "INFO", i) for i in range(10**6)]' > big.log`.

<details><summary>Ответ</summary>

```python
def parse_df(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines()[1:]:
        fs, size, used, avail, pct, mount = line.split(maxsplit=5)
        rows.append({"fs": fs, "size": int(size), "used": int(used),
                     "avail": int(avail), "pct": int(pct.rstrip("%")), "mount": mount})
    return rows

print([r["mount"] for r in parse_df(text) if r["pct"] > 80])
```text
</details>

**2.** Посчитай строки с `ERROR` двумя способами: `f.readlines()` и генератор.

<details><summary>Ответ</summary>

```python
import json
from collections import Counter

pods = json.load(open("pods.json", encoding="utf-8"))["items"]
print(Counter(p["status"].get("phase", "Unknown") for p in pods))

def restarts(pod: dict) -> int:
    return sum(cs.get("restartCount", 0) for cs in pod["status"].get("containerStatuses", []))

noisy = sorted((p for p in pods if restarts(p) > 3), key=restarts, reverse=True)
for p in noisy:
    print(f'{p["metadata"]["namespace"]}/{p["metadata"]["name"]}: {restarts(p)}')
print({p["metadata"]["namespace"] for p in pods})
```text
</details>

**3.** Сравни пиковую память: `/usr/bin/time -v python3 s.py 2>&1 | grep Maximum`.

<details><summary>Ответ</summary>

`inventory - monitored` → `{'web2', 'web3'}`; `monitored - inventory` → `{'old-db'}`;
`inventory & monitored` → `{'web1', 'db1'}`.

</details>

### C8. Даты и ротация
Есть имена файлов вида `db_2026-09-20_0300.sql.gz`. Напиши функцию, которая из списка имён
возвращает те, что старше N дней относительно «сейчас» (UTC). Дату бери из имени, а не из mtime.

### C9. Декоратор
Напиши декоратор `@timed`, логирующий длительность функции, и проверь на двух функциях.
Убедись, что `func.__name__` у обёрнутой функции сохранился (`functools.wraps`).

---

### Блок D. Инциденты


**D1.** Долгоживущий демон на каждом цикле отправляет в Telegram всё больше дублей «упавших хостов».
В коде: `def collect(host, failed=[]): ...`. Что происходит?

<details><summary>Ответ</summary>

Список по умолчанию общий для всех вызовов и копит хосты между циклами.
`failed=None` → `if failed is None: failed = []`.

</details>

**D2.** Скрипт мониторинга не останавливается по Ctrl+C и `systemctl stop` ждёт 90 секунд. В чём может быть дело?

<details><summary>Ответ</summary>

Голый `except:` в главном цикле ловит `KeyboardInterrupt`; SIGTERM без обработчика
у PID 1 в контейнере игнорируется (тема 03). Лови `Exception`, обрабатывай SIGTERM.

</details>

**D3.** Скрипт очистки логов в контейнере падает с `UnicodeDecodeError`, а на ноутбуке работает. Почему и как чинить?

<details><summary>Ответ</summary>

`open()` без `encoding` берёт кодировку из локали: в контейнере `LANG` не задан →
ASCII/`C`. Плюс в логах бывают битые байты. `open(p, encoding="utf-8", errors="replace")`.

</details>

**D4.** После переезда на сервер с другим часовым поясом ротация удалила «свежие» бэкапы. Какая ошибка в коде вероятна?

<details><summary>Ответ</summary>

Использовались naive-даты (`datetime.now()`) в локальном времени сервера, а имена файлов —
в UTC (или наоборот). Везде `datetime.now(timezone.utc)` и UTC в именах.

</details>

**D5.** Скрипт генерирует конфиги для 10 сервисов из шаблона-словаря, и у всех оказался порт последнего сервиса. Код: `cfg = template; cfg["port"] = svc.port; configs.append(cfg)`.

<details><summary>Ответ</summary>

`cfg = template` не копирует: все элементы списка — один и тот же словарь.
`cfg = copy.deepcopy(template)` (или `{**template, "port": ...}` для плоского).

</details>

**D6.** Скрипт проверки API неделю писал «OK», хотя API отдавал 500. В коде `except Exception: pass`. Как переписать?

<details><summary>Ответ</summary>

Ловить конкретные ошибки (`requests.RequestException`), логировать и возвращать ненулевой
код; «OK» писать только после `raise_for_status()` и проверки ответа.

</details>

**D7.** Скрипт «обнови, если версия новее» считает `"1.10" < "1.9"` истиной и откатывает версии. Почему и как сравнивать?

<details><summary>Ответ</summary>

Строки сравниваются посимвольно: `"1.1" < "1.9"`. Сравнивай кортежи чисел
`tuple(map(int, v.split(".")))` или `packaging.version.Version`.

</details>

**D8.** Скрипт по подам падает с `KeyError: 'containerStatuses'` раз в несколько запусков. Почему нестабильно и как исправить?

<details><summary>Ответ</summary>

У подов в `Pending`/`ContainerCreating` ещё нет `containerStatuses` — ошибка зависит
от того, в каком состоянии поды в момент запуска. `pod["status"].get("containerStatuses", [])`.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Чем list отличается от tuple?

<details><summary>Ответ</summary>

list изменяемый, tuple неизменяемый и может быть ключом словаря.

</details>

**2.** Какие типы изменяемые, а какие нет? Почему это важно?

<details><summary>Ответ</summary>

Изменяемые: list, dict, set, объекты классов; неизменяемые: int, float, str, tuple, bytes,
   frozenset. Важно для значений по умолчанию, ключей словаря и «копий» по ссылке.

</details>

**3.** Что такое генератор и чем он отличается от списка?

<details><summary>Ответ</summary>

Генератор отдаёт значения по одному по запросу и не хранит их все; список — в памяти целиком.

</details>

**4.** Как работает `try/except/else/finally`?

<details><summary>Ответ</summary>

`try` — код; `except` — при исключении; `else` — без исключения; `finally` — всегда.

</details>

**5.** Что такое контекстный менеджер? Как написать свой?

<details><summary>Ответ</summary>

Объект с `__enter__`/`__exit__`, гарантирующий освобождение ресурса в `with`;
   проще всего — `@contextlib.contextmanager` с `yield`.

</details>

**6.** Что такое декоратор?

<details><summary>Ответ</summary>

Функция, принимающая функцию и возвращающая обёртку с дополнительным поведением
   (логирование, ретраи, замер времени).

</details>

**7.** Почему нельзя делать `def f(x=[])`?

<details><summary>Ответ</summary>

Значение по умолчанию создаётся один раз и разделяется между вызовами.

</details>

**8.** Чем `is` отличается от `==`?

<details><summary>Ответ</summary>

`==` — равенство значений, `is` — один и тот же объект.

</details>

**9.** Что такое `*args` и `**kwargs`?

<details><summary>Ответ</summary>

Произвольные позиционные (кортеж) и именованные (dict) аргументы.

</details>

**10.** Как скопировать вложенный словарь, чтобы правка копии не меняла оригинал?

<details><summary>Ответ</summary>

`copy.deepcopy(d)`; `d.copy()` и `dict(d)` копируют только верхний уровень.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Пишу f-строки с выравниванием и форматированием чисел без подсказок
- [ ] Достаю данные из вложенного JSON через `get` с дефолтами
- [ ] Пользуюсь set для сравнения списков хостов
- [ ] Пишу comprehension и знаю, когда вместо него нужен цикл
- [ ] Читаю большие файлы генераторами
- [ ] Ловлю конкретные исключения, пишу свои, пользуюсь `raise ... from`
- [ ] Пишу свой контекстный менеджер через `@contextmanager`
- [ ] Описываю структуры данных dataclass'ами
- [ ] Работаю с датами в UTC (aware)
- [ ] Назову 5 граблей Python и как их обойти
