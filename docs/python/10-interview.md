---
title: "10. Вопросы с собеседований: Python для DevOps"
description: "Блок → Python для DevOps → собеседование."
---

# 10. Вопросы с собеседований: Python для DevOps

> Блок → **Python для DevOps** → собеседование.
> На позиции DevOps/SRE Python спрашивают не как у разработчиков: алгоритмы и классы — редко,
> а вот «напиши скрипт, который...», subprocess, HTTP с ретраями, разбор логов и работа с API
> инфраструктуры — почти всегда. Часто дают live-coding на 20-30 минут.

---

## 🎯 Часть 1. Восемь вопросов, которые задают почти всегда

### 1. Когда ты пишешь на bash, а когда на Python?

> «Bash — для склейки готовых утилит: entrypoint контейнера, wait-for, короткие обёртки над `tar`,
> `rsync`, `pg_dump`, шаги CI. Он есть везде и короче на простых задачах. Python — как только появляются
> JSON глубже одного уровня, HTTP API с пагинацией и ретраями, структуры данных, нужны тесты или SDK
> (boto3, kubernetes). Практический порог — 100-200 строк или первый `jq` внутри цикла. И важная
> граница с другой стороны: настройку серверов делаю Ansible'ом, инфраструктуру — Terraform'ом,
> а не циклом на Python.»

---

### 2. Как правильно запустить внешнюю команду из Python?

```python
r = subprocess.run(["pg_dump", "-Fc", "-f", out, db],
                   check=True, capture_output=True, text=True, timeout=900)
```text
> «Через `subprocess.run` со списком аргументов: `check=True` превращает ненулевой код в исключение,
> `timeout` не даёт висеть вечно, `text=True` — строки вместо байтов. Обрабатываю
> `CalledProcessError` (с `stderr` в сообщении), `TimeoutExpired` и `FileNotFoundError`.
> `shell=True` с переменными не использую — это инъекция команд, плюс проблемы с пробелами
> и кодами выхода; пайпы и глобы делаю средствами Python. `os.system` — наследие, без таймаутов
> и нормальных кодов. Если ненулевой код — это ответ (`grep`, `systemctl is-active`), `check` не ставлю
> и смотрю `returncode`.»

---

### 3. Как ты управляешь зависимостями и окружением?

> «Системный Python не трогаю — он для пакетов ОС, современные дистрибутивы и так запрещают
> `pip install` в систему (PEP 668). У каждого проекта свой venv, зависимости зафиксированы
> lock-файлом: `uv.lock` или `requirements.txt` с точными версиями, собранный `pip-compile`/`uv pip compile`.
> В CI ставлю строго по lock (`uv sync --locked`). CLI-утилиты вроде ruff или ansible ставлю через
> `pipx`/`uv tool`. На серверах скрипт живёт в `/opt/&lt;tool&gt;` со своим venv и запускается абсолютным
> путём к его python, либо доставляется Docker-образом.»

---

### 4. Как сделать надёжный HTTP-запрос из скрипта?

> «Пять вещей. Таймаут всегда — у requests его нет по умолчанию. `raise_for_status()` сразу после запроса.
> Ретраи только временных ошибок — сеть, таймауты, 429, 502-504 — с экспоненциальной задержкой, jitter
> и лимитом попыток; через `urllib3.Retry` на Session или tenacity. Ретраю только идемпотентные методы —
> `POST` повторять нельзя без ключа идемпотентности, иначе будут дубли. И уважаю rate limit:
> `Retry-After` на 429, ограничение параллельности. Плюс Session для переиспользования соединений,
> токен из окружения и пагинация до последней страницы.»

---

### 5. Как обработать лог на 10 ГБ на машине с 1 ГБ памяти?

> «Читаю построчно — итерация по файлу или генератор, `.gz` через `gzip.open(..., "rt")` или
> `fileinput` с `hook_compressed`. В памяти держу только агрегаты: `Counter` для топов,
> корзины вместо списков значений для перцентилей. Regex компилирую один раз, дешёвый предфильтр
> подстрокой — до regex. Битые строки считаю, а не падаю на них; файл открываю с `errors="replace"`.
> Если нужно быстрее — разбор CPU-bound, поэтому процессы по файлам, а не потоки. А системно такие
> вопросы должен закрывать Loki/ELK и JSON-логи.»

---

### 6. GIL: потоки, процессы или asyncio?

> «GIL не даёт двум потокам одновременно выполнять Python-байткод, но отпускается на I/O. Поэтому
> для I/O — опросить 50 URL, выполнить команду на 30 хостах по SSH — отлично работают потоки
> (`ThreadPoolExecutor`). Для сотен и тысяч одновременных запросов — asyncio (`httpx.AsyncClient`).
> Для CPU-задач — разбор гигабайтов логов, сжатие, хеши — процессы (`ProcessPoolExecutor`),
> потоки там не ускорят. В ops-скриптах 90% задач — I/O, так что чаще всего хватает пула потоков.»

---

### 7. Как сделать скрипт, который не страшно запустить в проде?

> «Разрушительные действия — dry-run по умолчанию, реальное выполнение по `--apply`, плюс лимит
> на количество изменений за запуск. Идемпотентность: повторный запуск не ломает и не дублирует.
> Логи через `logging` в stderr, данные — в stdout, осмысленные коды выхода. Таймауты на всё внешнее.
> Секреты — из окружения или файлов, никогда в аргументах и логах. Lock от параллельного запуска.
> Явные цели: для k8s — явный контекст, а не текущий. Атомарная запись файлов. И тесты на самое
> опасное — какие команды и запросы уйдут, — с моками subprocess и HTTP.»

---

### 8. Как тестировать скрипт, который вызывает внешние команды и API?

> «Сначала структура: логику выношу в чистые функции — их тестирую без моков, через `parametrize`.
> Края тонкие: `subprocess.run` мокаю через `mock.patch` в модуле, где он вызывается, и проверяю
> аргументы — что ушёл правильный `pg_dump`, с `check` и `timeout`, — и обработку ошибок через
> `side_effect`. HTTP мокаю библиотекой `responses` (или `respx` для httpx): регистрирую ответы, включая
> 503 и сетевые ошибки, проверяю ретраи и тело запроса. Файлы — в `tmp_path`, env — через `monkeypatch`,
> CLI — вызовом `main(argv)` с проверкой кода выхода и `capsys`. Всё это гоняется в CI вместе с ruff.»

---

## 📚 Часть 2. 40 вопросов по темам

### Язык и основы
1. **Изменяемые и неизменяемые типы?** list/dict/set — изменяемые; int/str/tuple/frozenset — нет. Важно для дефолтов и ключей словаря.
2. **Что не так с `def f(x=[])`?** Список создаётся один раз и общий для всех вызовов → `x=None`.
3. **`is` vs `==`?** Идентичность объекта vs равенство значений; `is` — только для `None`/`True`/`False`.
4. **Что такое генератор?** Функция с `yield`: значения по одному по запросу, O(1) памяти.
5. **Что такое декоратор?** Функция-обёртка над функцией: ретраи, тайминг, логирование; `functools.wraps`.
6. **Контекстный менеджер?** `with` гарантирует освобождение ресурса; свой — `@contextmanager`.
7. **`try/except/else/finally`?** else — если не было исключения; finally — всегда.
8. **Почему нельзя голый `except:`?** Ловит `KeyboardInterrupt`/`SystemExit`, прячет ошибки.
9. **Как скопировать вложенный dict?** `copy.deepcopy`; `.copy()` — поверхностно.
10. **Зачем type hints и dataclass?** Читаемость, проверка IDE/mypy; dataclass — именованные поля вместо dict.

### Файлы, процессы, ОС
11. **Как атомарно записать файл?** Временный файл в том же каталоге → `fsync` → `os.replace`.
12. **Чем опасен `shell=True`?** Инъекция, пробелы/кавычки, таймаут не убивает детей шелла.
13. **Что значит отрицательный `returncode`?** Процесс убит сигналом (-9, -15).
14. **Почему Python-контейнер долго останавливается?** PID 1 без обработчика SIGTERM → ждёт SIGKILL.
15. **Как обработать SIGTERM?** `signal.signal(SIGTERM, handler)` → флаг/`Event`, цикл завершает работу.
16. **Как не запустить cron-скрипт дважды?** `fcntl.flock` на lock-файл или systemd-таймер.
17. **Как безопасно распаковать чужой архив?** `tarfile.extractall(dst, filter="data")`.

### CLI, логи, конфиги
18. **argparse или click/typer?** argparse — без зависимостей; click/typer — большие утилиты.
19. **Почему `logging`, а не `print`?** Уровни, время, stderr, настройка без правки кода.
20. **Куда писать логи в контейнере?** В stdout/stderr, сбор — задача платформы.
21. **Как безопасно читать YAML?** `yaml.safe_load`; помнить `no` → `False`, `1.10` → `1.1`.
22. **Приоритет настроек?** CLI > env > файл > дефолт; секреты — env/файлы.

### HTTP и API
23. **Какие ошибки ретраить?** Сеть, таймауты, 429, 502-504; не 4xx.
24. **Что такое jitter?** Случайная добавка к паузе, чтобы клиенты не ретраили синхронно.
25. **Как пройти пагинацию GitLab?** `Link: rel="next"`/`X-Next-Page`, `per_page=100`.
26. **requests vs httpx?** httpx: таймаут по умолчанию, async, HTTP/2; requests: проще, `urllib3.Retry`.
27. **Почему не `verify=False`?** Отключает проверку сервера; правильно — CA-бандл.

### Логи и данные
28. **`re.match` vs `re.search`?** С начала строки vs где угодно.
29. **Как посчитать топ-10?** `Counter(...).most_common(10)`.
30. **Как посчитать p95?** `statistics.quantiles(v, n=100)[94]`; не усреднять перцентили разных источников.
31. **Как читать `journalctl`?** `-o json` → JSON-lines → `json.loads` построчно.

### Инфраструктурные библиотеки
32. **Как выполнить команду на 100 хостах?** fabric `ThreadingGroup` / paramiko + пул потоков, таймауты.
33. **Почему не `AutoAddPolicy`?** Отключает проверку ключа хоста → MITM.
34. **Как скрипт в поде ходит в API k8s?** `load_incluster_config()`, ServiceAccount + RBAC.
35. **Чем опасен `load_kube_config()` без контекста?** Возьмёт текущий контекст — может быть прод.
36. **Как получить все объекты S3, если их > 1000?** `get_paginator("list_objects_v2")`.
37. **boto3 с MinIO?** `endpoint_url`, path-style адресация, ключи из env.
38. **Как отдать метрику из cron-задачи?** Textfile collector (`write_to_textfile`), для CI — Pushgateway.

### Упаковка и качество
39. **Что такое pyproject.toml и entry point?** Метаданные, зависимости, `[project.scripts]` → команда.
40. **Какие правила Dockerfile для Python?** slim, зависимости до кода, non-root, exec-форма, `.dockerignore`.

---

## 💻 Часть 3. Задачи «напиши скрипт» — с решениями

### Задача 1. Удалить файлы старше N дней (с dry-run)

```python
#!/usr/bin/env python3
import argparse, logging, sys, time
from pathlib import Path

log = logging.getLogger("cleanup")

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("path", type=Path)
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--pattern", default="*")
    p.add_argument("--apply", action="store_true")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not a.path.is_dir() or a.path.resolve() == Path("/"):
        log.error("недопустимый каталог: %s", a.path)
        return 2
    cutoff = time.time() - a.days * 86400
    old = [f for f in a.path.rglob(a.pattern) if f.is_file() and f.stat().st_mtime < cutoff]
    total = sum(f.stat().st_size for f in old)             # до удаления
    for f in old:
        log.info("%s %s", "удаляю" if a.apply else "[dry-run]", f)
        if a.apply:
            f.unlink(missing_ok=True)
    log.info("итого %d файлов, %.1f МБ", len(old), total / 2**20)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```text
Что оценивают: dry-run по умолчанию, защита от `/`, `missing_ok`, логи, код выхода.

---

### Задача 2. Топ-10 IP из access.log

```python
import sys
from collections import Counter

counts = Counter()
with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
    for line in f:                              # построчно — лог может быть огромным
        ip, _, _ = line.partition(" ")
        if ip:
            counts[ip] += 1
for ip, n in counts.most_common(10):
    print(f"{n:>8}  {ip}")
```text
Bash-эквивалент, который стоит назвать сразу: `awk '{print $1}' access.log | sort | uniq -c | sort -rn | head`.

---

### Задача 3. Проверить список URL, ненулевой код при любой ошибке

```python
import sys
from concurrent.futures import ThreadPoolExecutor
import requests

def check(url: str) -> tuple[str, bool, str]:
    try:
        r = requests.get(url, timeout=5)
        return url, r.status_code < 400, str(r.status_code)
    except requests.RequestException as e:
        return url, False, type(e).__name__

urls = [u.strip() for u in open(sys.argv[1], encoding="utf-8") if u.strip()]
with ThreadPoolExecutor(max_workers=20) as pool:
    results = list(pool.map(check, urls))
for url, ok, info in results:
    print(f"{'OK ' if ok else 'ERR'} {info:&lt;16} {url}")
sys.exit(0 if all(ok for _, ok, _ in results) else 1)
```text
Что оценивают: таймаут, обработка исключений, параллельность для I/O, код выхода.

---

### Задача 4. Декоратор retry с экспоненциальной задержкой

```python
import functools, logging, random, time

log = logging.getLogger(__name__)

def retry(times: int = 5, base: float = 1.0, max_delay: float = 30.0,
          exceptions: tuple[type[BaseException], ...] = (Exception,)):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, times + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == times:
                        raise                                   # последняя попытка — отдать ошибку
                    delay = min(max_delay, base * 2 ** (attempt - 1)) * random.uniform(0.5, 1.5)
                    log.warning("%s: попытка %d/%d: %s; жду %.1fs",
                                func.__name__, attempt, times, e, delay)
                    time.sleep(delay)
        return wrapper
    return decorator

@retry(times=4, exceptions=(ConnectionError, TimeoutError))
def fetch_status() -&gt; str: ...
```text
Что оценивают: декоратор с параметрами, `wraps`, ограниченный список исключений, backoff + jitter,
повторный `raise` исходной ошибки.

---

### Задача 5. Найти дубликаты файлов в каталоге

```python
import hashlib, sys
from collections import defaultdict
from pathlib import Path

def find_duplicates(root: Path) -> list[list[Path]]:
    by_size = defaultdict(list)
    for p in root.rglob("*"):
        if p.is_file() and not p.is_symlink():
            by_size[p.stat().st_size].append(p)
    by_hash = defaultdict(list)
    for same_size in by_size.values():
        if len(same_size) < 2:
            continue                                     # уникальный размер — точно не дубликат
        for p in same_size:
            with p.open("rb") as f:
                by_hash[hashlib.file_digest(f, "sha256").hexdigest()].append(p)
    return [paths for paths in by_hash.values() if len(paths) > 1]

for group in find_duplicates(Path(sys.argv[1])):
    print(*group, sep="\n  ", end="\n\n")
```text
Что оценивают: предфильтр по размеру (не хешировать всё подряд), потоковое хеширование, `defaultdict`.

---

### Задача 6. Поды с рестартами больше N во всех неймспейсах

```python
import sys
from kubernetes import client, config

config.load_kube_config(context=sys.argv[1])
threshold = int(sys.argv[2]) if len(sys.argv) > 2 else 5
rows = []
for pod in client.CoreV1Api().list_pod_for_all_namespaces(_request_timeout=30).items:
    restarts = sum(cs.restart_count for cs in pod.status.container_statuses or [])
    if restarts > threshold:
        rows.append((restarts, pod.metadata.namespace, pod.metadata.name))
for restarts, ns, name in sorted(rows, reverse=True):
    print(f"{restarts:>5}  {ns}/{name}")
sys.exit(1 if rows else 0)
```text
Что оценивают: явный контекст, `container_statuses or []`, snake_case-поля, сортировка, код выхода.
Устный бонус: `kubectl get pods -A --sort-by='.status.containerStatuses[0].restartCount'`.

---

### Задача 7. Сколько дней осталось до истечения TLS-сертификатов

```python
import socket, ssl, sys
from datetime import datetime, timezone

def days_left(host: str, port: int = 443, timeout: float = 5.0) -> int:
    ctx = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            not_after = tls.getpeercert()["notAfter"]        # 'Jun  1 12:00:00 2026 GMT'
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), tz=timezone.utc)
    return (expires - datetime.now(timezone.utc)).days

bad = 0
for host in sys.argv[1:]:
    try:
        d = days_left(host)
        print(f"{host:&lt;30} {d:&gt;4} дн. {'⚠️' if d < 14 else ''}")
        bad += d < 14
    except (OSError, ssl.SSLError) as e:                     # истёкший/невалидный — тоже SSLError
        print(f"{host:<30} ошибка: {e}")
        bad += 1
sys.exit(1 if bad else 0)
```text
Что оценивают: таймаут соединения, SNI (`server_hostname`), aware-даты, обработка невалидных сертификатов.

---

## 🧠 Как отвечать: практические приёмы

1. **Начинай с уточнений.** «Лог какого размера? Нужен dry-run? Куда выводить результат?» —
   это то, что отличает инженера эксплуатации от решателя задачек.
2. **Сначала рабочая простая версия, потом улучшения.** Проговори, что добавишь в прод-версию:
   таймауты, логи, коды выхода, тесты.
3. **Называй bash-эквивалент.** Для задач вроде «топ IP» покажи, что знаешь `awk | sort | uniq -c`,
   и объясни, когда Python оправдан.
4. **Думай о безопасности вслух.** dry-run, явный контекст k8s, секреты из env, `shell=True` — нет.
5. **Приводи свои цифры и артефакты.** «У меня уборщик подов работает CronJob'ом с RBAC на три verbs,
   dry-run по умолчанию и лимитом удалений» звучит сильнее любой теории.
6. **Честно отделяй уровень.** «Тесты с моками пишу для своих утилит, опыта в команде с большим
   codebase пока нет» — нормальный ответ для джуна; выдуманный опыт видно по первому уточняющему вопросу.

---

## ✅ Финальный самоконтроль

- [ ] Объясню выбор bash vs Python через критерии
- [ ] Напишу `subprocess.run` правильно и объясню, почему не `shell=True`
- [ ] Расскажу про venv, lock-файлы, PEP 668 и доставку утилиты
- [ ] Напишу надёжный HTTP-вызов: таймаут, ретраи с backoff и jitter, идемпотентность
- [ ] Обработаю большой лог генераторами и посчитаю топ и p95
- [ ] Объясню GIL и выбор между потоками, процессами и asyncio
- [ ] Перечислю, что делает скрипт безопасным для прода
- [ ] Расскажу, как тестировать скрипт с subprocess и HTTP
- [ ] Напишу с нуля за 10 минут: очистку с dry-run, проверку URL, декоратор retry
- [ ] Покажу свои утилиты из лаб и объясню решения в них

➡️ Смежные блоки: [Linux: bash](/linux/26-bash-devops-practice) · [Kubernetes](/kubernetes/) ·
[CI/CD](/cicd/05-gitlab-ci-basics) · [Мониторинг](/monitoring/)
