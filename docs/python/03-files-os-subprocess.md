---
title: "03. Файлы, ОС и внешние команды"
description: "Блок → Python для DevOps → тема 3 из 8."
---

# 03. Файлы, ОС и внешние команды

> Блок → **Python для DevOps** → тема 3 из 8.
> Аналог в bash: [25_bash_robust.md](/linux/25-bash-robust) — `set -euo pipefail`, `trap`,
> временные файлы, коды выхода. Здесь то же самое, но средствами Python.
>
> **После темы ты умеешь:** работать с путями через `pathlib`, копировать и удалять через `shutil`,
> писать файлы атомарно, читать переменные окружения, запускать внешние команды через
> `subprocess.run` правильно (`check`, `capture_output`, `text`, `timeout`, без `shell=True`),
> обрабатывать коды выхода и сигналы, собирать и распаковывать архивы.

---

## 🗺️ Карта темы

```text
                         Python-скрипт
   ┌───────────┬────────────┬───────────┴───┬──────────────┬─────────────┐
 pathlib     shutil      os.environ      subprocess      signal        tarfile/gzip
 пути, glob, copy/move,  настройки и     внешние         SIGTERM →     архивы,
 read/write  rmtree,     секреты из      команды,        аккуратное    сжатые логи,
             disk_usage  окружения       коды выхода     завершение    hashlib
   │                                         │
 tempfile + os.replace                  shlex.quote / shlex.split
 атомарная запись                       (если без шелла никак)
```text
---

## 1. pathlib — пути как объекты

```python
from pathlib import Path

base = Path("/var/backups")
dump = base / "pg" / "db_2026-09-27.sql.gz"    # склейка через /
dump.name, dump.stem, dump.suffix, dump.suffixes  # 'db_...sql.gz', 'db_...sql', '.gz', ['.sql', '.gz']
dump.parent                                     # /var/backups/pg
dump.with_suffix(".tmp")                        # заменить последнее расширение
Path.home(), Path.cwd()
Path(__file__).resolve().parent                 # ⭐ каталог самого скрипта (для соседних файлов)

dump.exists(), dump.is_file(), dump.is_dir()
dump.parent.mkdir(parents=True, exist_ok=True)  # mkdir -p
dump.unlink(missing_ok=True)                    # rm -f
dump.stat().st_size, dump.stat().st_mtime       # размер, время изменения (epoch)

sorted(Path("/var/log/nginx").glob("*.log"))    # в каталоге
list(Path("/srv").rglob("*.pyc"))               # рекурсивно
```text
| bash / os.path | pathlib |
|----------------|---------|
| `"$dir/$file"` / `os.path.join` | `Path(dir) / file` |
| `basename`, `dirname` | `.name`, `.parent` |
| `[ -f x ]`, `[ -d x ]` | `.is_file()`, `.is_dir()` |
| `mkdir -p` | `.mkdir(parents=True, exist_ok=True)` |
| `rm -f` | `.unlink(missing_ok=True)` |
| `cat file` | `.read_text(encoding="utf-8")` |
| `find . -name '*.log'` | `.rglob("*.log")` |
| `realpath` | `.resolve()` |

⚠️ `Path("/backups") / "/etc/passwd"` даёт `/etc/passwd`: абсолютная правая часть «перебивает»
левую. Имена из внешних данных проверяй.

---

## 2. Чтение и запись файлов

| Режим | Смысл |
|-------|-------|
| `"r"` / `"rb"` | Чтение текста / байтов |
| `"w"` | Перезапись (файл обнуляется **сразу** при открытии) |
| `"a"` | Дописать в конец |
| `"x"` | Создать, упасть, если уже есть — защита от перезаписи |

```python
text = Path("/etc/hostname").read_text(encoding="utf-8").strip()
Path("report.txt").write_text("ok\n", encoding="utf-8")

with open("/var/log/app.log", encoding="utf-8", errors="replace") as f:
    for line in f:                  # построчно, без загрузки в память
        ...
```text
⭐ **Атомарная запись** — конфиг или метрика никогда не бывают «наполовину записанными»:

```python
import os, tempfile

def atomic_write(path: Path, data: str, mode: int = 0o644) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")   # та же ФС!
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())    # данные на диске, а не в кэше
        os.chmod(tmp, mode)
        os.replace(tmp, path)       # атомарная подмена (rename)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
```text
`os.replace` атомарен только в пределах одной файловой системы — поэтому временный файл
создаётся в том же каталоге, а не в `/tmp`.

---

## 3. shutil и tempfile

| Функция | Аналог | Заметка |
|---------|--------|---------|
| `shutil.copy2(src, dst)` | `cp -p` | С временем модификации и правами |
| `shutil.copytree(src, dst, dirs_exist_ok=True)` | `cp -r` | `ignore=shutil.ignore_patterns("*.pyc", ".git")` |
| `shutil.move(src, dst)` | `mv` | Между ФС — копирование + удаление |
| `shutil.rmtree(path)` | `rm -rf` | ⚠️ Проверь путь перед вызовом |
| `shutil.disk_usage("/")` | `df` | `total, used, free` в байтах |
| `shutil.which("pg_dump")` | `command -v` | `None`, если не найден |
| `shutil.chown(p, user="app", group="app")` | `chown` | |
| `shutil.make_archive(...)` | `tar czf` | См. раздел 9 |

```python
with tempfile.TemporaryDirectory(prefix="backup-") as tmp:   # удалится сам, даже при ошибке
    work = Path(tmp)
    ...
```text
⚠️ Не пиши во «вшитый» `/tmp/myscript.tmp`: два экземпляра скрипта затрут друг друга,
а предсказуемое имя — классическая дыра (symlink-атака).

---

## 4. Переменные окружения

```python
import os
os.environ["HOME"]                          # KeyError, если нет — для обязательных
os.environ.get("LOG_LEVEL", "INFO")         # с дефолтом
os.getenv("SENTRY_DSN")                     # None, если нет

token = os.environ.get("GITLAB_TOKEN") or sys.exit("GITLAB_TOKEN не задан")
timeout = float(os.environ.get("TIMEOUT", "10"))              # ⚠️ в env всё — строки
dry_run = os.environ.get("DRY_RUN", "false").lower() in {"1", "true", "yes"}
```text
- Изменения `os.environ` видят дочерние процессы, но не родительский шелл.
- Для дочернего процесса окружение лучше собрать явно: `env={**os.environ, "PGPASSWORD": pw}`.
- ⚠️ Никогда не логируй `os.environ` целиком — там токены.

---

## 5. ⭐ subprocess.run — правильный запуск команд

```python
import subprocess

result = subprocess.run(
    ["pg_dump", "-h", host, "-U", user, "-Fc", "-f", str(out_file), dbname],
    check=True,              # ненулевой код → исключение CalledProcessError
    capture_output=True,     # собрать stdout и stderr
    text=True,               # str вместо bytes
    timeout=900,             # не висеть вечно → TimeoutExpired
    env={**os.environ, "PGPASSWORD": password},
)
log.info("дамп готов: %s", out_file)
```text
| Параметр | Зачем |
|----------|-------|
| список аргументов | Каждый аргумент отдельно — пробелы и спецсимволы не ломают команду |
| `check=True` | Аналог `set -e`: ошибка команды не пройдёт молча |
| `capture_output=True` | Вывод в `result.stdout` / `result.stderr` |
| `text=True` | Декодировать вывод в строки |
| `timeout=` | Секунды; по истечении процесс убивается, летит `TimeoutExpired` |
| `cwd=` | Рабочий каталог команды |
| `env=` | Окружение команды (заменяет целиком — поэтому `{**os.environ, ...}`) |
| `input=` | Передать данные на stdin |
| `stdout=subprocess.DEVNULL` | Выбросить вывод |

```python
try:
    r = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
except FileNotFoundError:
    log.error("команда не найдена: %s", cmd[0])
except subprocess.TimeoutExpired:
    log.error("таймаут: %s", " ".join(cmd))
except subprocess.CalledProcessError as e:
    log.error("%s завершилась с кодом %d: %s", cmd[0], e.returncode, e.stderr.strip())
```text
Иногда ненулевой код — это **ответ**, а не ошибка. Тогда `check` не ставят и смотрят `returncode`:

```python
r = subprocess.run(["systemctl", "is-active", "--quiet", "nginx"])
if r.returncode != 0:          # 3 = inactive — это информация
    log.warning("nginx не активен")

r = subprocess.run(["grep", "-q", "ERROR", "/var/log/app.log"])   # 0 — нашёл, 1 — нет, 2 — ошибка
```text
---

## 6. Почему не `shell=True`

```python
name = "logs; rm -rf ~"                             # пришло из аргумента/API/имени файла
subprocess.run(f"tar czf /backup/{name}.tgz /var/log", shell=True)   # ⚠️ выполнит rm -rf ~
subprocess.run(["tar", "czf", f"/backup/{name}.tgz", "/var/log"])   # ✅ имя — просто строка
```text
| `shell=True` | Список аргументов |
|--------------|-------------------|
| Инъекция команд через переменные | Невозможна: шелла нет |
| Ломается на пробелах и кавычках | Каждый аргумент — как есть |
| Таймаут убивает шелл, но не всегда его детей | Убивается сама команда |
| Код выхода — от шелла/последней команды пайпа | Код самой команды |

Если без шелла совсем никак (фиксированная строка с пайпами, которую не хочется переписывать) —
никаких переменных внутри или `shlex.quote()` на каждую. Но обычно пайп проще сделать в Python:

```python
# вместо: journalctl -u nginx --since '1 hour ago' | grep -ci error
r = subprocess.run(["journalctl", "-u", "nginx", "--since", "1 hour ago", "-o", "cat"],
                   check=True, capture_output=True, text=True, timeout=60)
errors = sum("error" in line.lower() for line in r.stdout.splitlines())

shlex.split("rsync -a '/my dir/' host:/dst")   # строку команды → список аргументов
```text
`os.system()` и `os.popen()` — наследие: нет таймаута, нет нормального кода выхода,
всегда шелл. В новом коде не используют.

---

## 7. Долгие команды и потоковый вывод

`run()` ждёт завершения и отдаёт вывод целиком. Если нужно видеть прогресс по строкам:

```python
with subprocess.Popen(
    ["rsync", "-a", "--info=progress2", "/data/", "backup:/data/"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
) as proc:
    for line in proc.stdout:
        log.info("rsync: %s", line.rstrip())
if proc.returncode != 0:
    raise RuntimeError(f"rsync завершился с кодом {proc.returncode}")
```text
⚠️ `stdout=PIPE` и `stderr=PIPE`, а читаешь только один поток — второй переполнит буфер,
и процесс зависнет (deadlock). Либо `stderr=subprocess.STDOUT`, либо `proc.communicate()`,
либо `run(capture_output=True)`.

---

## 8. Коды выхода и сигналы

| `returncode` | Значение |
|--------------|----------|
| `0` | Успех |
| `> 0` | Ошибка (смысл — по документации команды) |
| `< 0` | Убит сигналом: `-15` — SIGTERM, `-9` — SIGKILL (в bash это 143 и 137) |

⭐ **Аккуратное завершение по SIGTERM** — `docker stop`, `kubectl delete pod`, `systemctl stop`
сначала шлют SIGTERM и ждут:

```python
import signal, threading

stop = threading.Event()

def on_signal(signum, frame):
    log.info("получен %s, завершаюсь после текущей итерации", signal.Signals(signum).name)
    stop.set()

signal.signal(signal.SIGTERM, on_signal)
signal.signal(signal.SIGINT, on_signal)

while not stop.is_set():
    run_checks()
    stop.wait(30)          # ⭐ вместо time.sleep(30): проснётся сразу по сигналу
log.info("остановлен")
```text
```text
docker stop → SIGTERM ──► есть обработчик? ──да──► закончить итерацию, выйти за 1 с
                                  │
                                  нет, и процесс — PID 1 в контейнере
                                  ▼
                   ядро ИГНОРИРУЕТ сигнал → 10 с ожидания → SIGKILL (код 137)
```text
Процессу с PID 1 ядро не применяет действие по умолчанию, поэтому без обработчика
SIGTERM «теряется». Лечится обработчиком, `docker run --init` (tini) или `exec` в entrypoint
(см. [26_bash_devops_practice.md](/linux/26-bash-devops-practice)).

Отправить сигнал из скрипта: `proc.terminate()` (SIGTERM), `proc.kill()` (SIGKILL),
`os.kill(pid, signal.SIGHUP)` — например, чтобы сервис перечитал конфиг.

---

## 9. Архивы, сжатие, контрольные суммы

```python
import tarfile, gzip, hashlib, shutil

with tarfile.open("/backups/nginx.tar.gz", "w:gz") as tar:
    tar.add("/etc/nginx", arcname="nginx")          # arcname — без абсолютного пути в архиве

with tarfile.open("/backups/nginx.tar.gz") as tar:  # формат сжатия определится сам
    print(tar.getnames())
    tar.extractall("/tmp/restore", filter="data")   # ⭐ защита от ../ и абсолютных путей

archive = shutil.make_archive("/backups/app-2026-09-27", "gztar", root_dir="/srv/app")
shutil.unpack_archive(archive, "/tmp/app-restore")

with gzip.open("/var/log/nginx/access.log.2.gz", "rt", encoding="utf-8", errors="replace") as f:
    for line in f: ...                              # читать .gz как обычный текст

with open(src, "rb") as fin, gzip.open(f"{src}.gz", "wb") as fout:
    shutil.copyfileobj(fin, fout)                   # gzip файла потоково

with open(archive, "rb") as f:
    digest = hashlib.file_digest(f, "sha256").hexdigest()   # контрольная сумма (3.11+)
```text
⚠️ `extractall` без `filter` на чужом архиве — уязвимость: элемент `../../etc/cron.d/x`
запишется за пределы каталога. С 3.12 передавай `filter="data"` явно.

---

## 10. Типовой паттерн: очистка старых файлов + защита от параллельного запуска

```python
import fcntl, time

def acquire_lock(path: str):
    fd = open(path, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)   # как flock -n в bash
    except BlockingIOError:
        sys.exit("уже запущен другой экземпляр")
    return fd                                            # держать открытым до конца работы

def cleanup(directory: Path, pattern: str, days: int, dry_run: bool) -> int:
    if not directory.is_dir():
        raise ValueError(f"нет каталога {directory}")
    cutoff = time.time() - days * 86400
    count = 0
    for p in directory.glob(pattern):
        if p.is_file() and p.stat().st_mtime < cutoff:
            if dry_run:
                log.info("[dry-run] к удалению: %s", p)
            else:
                p.unlink(missing_ok=True)
                log.info("удалён: %s", p)
            count += 1
    return count

lock = acquire_lock("/run/lock/cleanup.lock")
n = cleanup(Path("/var/backups/pg"), "*.sql.gz", days=14, dry_run=True)
```text
---

## 11. Грабли

| Грабля | Что происходит | Правильно |
|--------|----------------|-----------|
| `shell=True` + переменная | Инъекция команд | Список аргументов |
| Нет `timeout` | Скрипт висит вечно на зависшем ssh/NFS | `timeout=` всегда |
| Нет `check=True` и не смотришь `returncode` | Ошибка команды проходит молча | `check=True` или явная проверка |
| `capture_output` без `text=True` | `bytes`, `"error" in r.stdout` → `TypeError` | `text=True` |
| `Path(os.environ.get("DIR", ""))` | Пустая переменная → `Path(".")` — текущий каталог | Проверять значение перед `rmtree`/`unlink` |
| Запись конфига «на месте» | Упал на середине — битый файл | `tempfile` в том же каталоге + `os.replace` |
| Временный файл в `/tmp`, цель на другом разделе | `os.replace` → `OSError: Invalid cross-device link` | Временный файл рядом с целевым |
| `extractall` без `filter` | Path traversal из архива | `filter="data"` |
| Нет обработчика SIGTERM в контейнере | `docker stop` ждёт 10 с и убивает | `signal.signal(SIGTERM, ...)` / `--init` |
| `PIPE` на оба потока, чтение одного | Зависание | `stderr=STDOUT` / `communicate()` |
| `Path.glob("*")` | В отличие от шелла, находит и скрытые файлы | Фильтровать `p.name.startswith(".")` при надобности |

---

## 💼 Как это в DevOps

- Скрипты бэкапа — это `subprocess.run(["pg_dump", ...], check=True, timeout=...)` + `tarfile`/`gzip`
  + `hashlib` + выгрузка в S3 (тема 07) + ротация через `pathlib`.
- Любой долгоживущий Python-процесс в контейнере или k8s обязан обрабатывать SIGTERM —
  иначе каждый деплой ждёт `terminationGracePeriodSeconds` и убивает процесс посреди работы.
- Атомарная запись — стандарт для файлов, которые читают другие: конфиги, `.prom`-файлы
  textfile collector'а, state-файлы.
- `shell=True` с переменными на ревью считают уязвимостью, как SQL-инъекцию.
- Lock-файл (`fcntl.flock`) спасает от ситуации «cron запустил второй бэкап, пока первый не закончился».

---

## 📌 Шпаргалка

| Хочу | Python |
|------|--------|
| Каталог скрипта | `Path(__file__).resolve().parent` |
| `mkdir -p` / `rm -f` | `p.mkdir(parents=True, exist_ok=True)` / `p.unlink(missing_ok=True)` |
| Найти файлы | `Path(d).glob("*.log")` / `.rglob(...)` |
| Возраст файла | `time.time() - p.stat().st_mtime` |
| Прочитать / записать | `p.read_text(encoding="utf-8")` / `p.write_text(...)` |
| Атомарно записать | `mkstemp(dir=p.parent)` → write → `fsync` → `os.replace` |
| Временный каталог | `with tempfile.TemporaryDirectory() as tmp:` |
| Свободное место | `shutil.disk_usage("/")` |
| Есть ли утилита | `shutil.which("pg_dump")` |
| Переменная обязательная / с дефолтом | `os.environ["X"]` / `os.environ.get("X", "d")` |
| Запустить команду | `subprocess.run([...], check=True, capture_output=True, text=True, timeout=N)` |
| Код как информация | `subprocess.run([...]).returncode` |
| Строку → аргументы | `shlex.split(s)` |
| Экранировать для шелла | `shlex.quote(s)` |
| Поток вывода | `Popen(..., stdout=PIPE, stderr=STDOUT, text=True)` + `for line in proc.stdout` |
| Обработать SIGTERM | `signal.signal(signal.SIGTERM, handler)` + `Event.wait()` |
| tar.gz | `tarfile.open(p, "w:gz")` / `extractall(dst, filter="data")` |
| Читать .gz | `gzip.open(p, "rt", encoding="utf-8")` |
| sha256 файла | `hashlib.file_digest(f, "sha256").hexdigest()` |
| Один экземпляр | `fcntl.flock(fd, LOCK_EX \| LOCK_NB)` |

---

## 🧠 Что запомнить

1. Пути — через `pathlib`, файлы — всегда с `encoding="utf-8"`.
2. Файлы, которые читают другие, пишутся атомарно: временный файл рядом + `os.replace`.
3. `subprocess.run` = список аргументов + `check=True` + `timeout` + `text=True`.
4. `shell=True` с переменными — инъекция; пайпы и глобы делаются средствами Python.
5. Ненулевой код бывает ответом (`grep`, `systemctl is-active`) — тогда смотри `returncode` без `check`.
6. Отрицательный `returncode` — процесс убит сигналом (`-9`, `-15`).
7. PID 1 в контейнере без обработчика SIGTERM не остановится по `docker stop` — нужен обработчик.
8. `Event.wait(timeout)` вместо `time.sleep` — цикл просыпается сразу по сигналу.
9. `extractall(..., filter="data")` — всегда, когда архив не твой.
10. Перед `rmtree`/массовым `unlink` — проверка пути, dry-run и lock от параллельного запуска.

➡️ Дальше: [04_cli_logging_config.md](/python/04-cli-logging-config) · Задачи: 03_files_os_subprocess_tasks.md


---

### Блок A. Теория


**A1.** Чем `pathlib` удобнее `os.path`? Как получить каталог, где лежит сам скрипт?

<details><summary>Ответ</summary>

Пути — объекты с методами (`.name`, `.parent`, `.glob`, `.read_text`), склейка через `/`,
меньше строковой возни. Каталог скрипта — `Path(__file__).resolve().parent`.

</details>

**A2.** Что вернёт `Path("/backups") / "/etc/passwd"` и почему это опасно?

<details><summary>Ответ</summary>

`/etc/passwd`: абсолютная правая часть отбрасывает левую. Если имя пришло извне,
скрипт может писать или удалять за пределами нужного каталога.

</details>

**A3.** Чем режим `"w"` отличается от `"x"`? Когда полезен `"x"`?

<details><summary>Ответ</summary>

`"w"` обнуляет существующий файл при открытии; `"x"` создаёт новый и падает с
`FileExistsError`, если файл есть. Полезен для «не затереть чужой результат».

</details>

**A4.** ⭐ Что такое атомарная запись файла и почему временный файл создают в том же каталоге?

<details><summary>Ответ</summary>

Данные пишутся во временный файл, который затем `os.replace` подменяет целевой одним
`rename`. Читатель видит либо старую, либо новую версию целиком. `rename` атомарен только в пределах
одной ФС — поэтому временный файл рядом с целевым.

</details>

**A5.** Почему нельзя писать временные данные в фиксированный `/tmp/myscript.tmp`?

<details><summary>Ответ</summary>

Параллельные запуски затрут друг друга; предсказуемое имя позволяет подложить симлинк
(запись в чужой файл). Нужен `tempfile` с уникальным именем.

</details>

**A6.** Чем `os.environ["X"]` отличается от `os.environ.get("X")`? Какой тип у значений?

<details><summary>Ответ</summary>

`["X"]` бросает `KeyError`, если переменной нет (для обязательных); `.get` возвращает
`None`/дефолт. Значения — всегда строки, числа и булевы нужно преобразовывать.

</details>

**A7.** Разбери по параметрам: `subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)`.

<details><summary>Ответ</summary>

Список аргументов без шелла; `check` — исключение при ненулевом коде; `capture_output` —
собрать stdout/stderr; `text` — строки вместо байтов; `timeout` — убить через 30 с и бросить
`TimeoutExpired`.

</details>

**A8.** Какие исключения может бросить `subprocess.run` и что каждое означает?

<details><summary>Ответ</summary>

`FileNotFoundError` — нет бинарника; `CalledProcessError` — ненулевой код при `check=True`;
`TimeoutExpired` — истёк `timeout`; `PermissionError` — файл не исполняемый.

</details>

**A9.** ⭐ Почему `shell=True` опасен? Назови три проблемы кроме инъекции.

<details><summary>Ответ</summary>

Инъекция; ломается на пробелах/кавычках/спецсимволах в аргументах; `timeout` убивает шелл,
а дочерние процессы могут остаться; код выхода и ошибки относятся к шеллу/пайпу, а не к команде;
зависимость от конкретного шелла (`sh` ≠ `bash`).

</details>

**A10.** Когда ненулевой код выхода — не ошибка? Приведи два примера команд.

<details><summary>Ответ</summary>

`grep` (1 — не нашёл), `systemctl is-active` (3 — не активен), `diff` (1 — есть различия),
`test`/`[`.

</details>

**A11.** Что означает отрицательный `returncode`? Какой код увидит bash в том же случае?

<details><summary>Ответ</summary>

Процесс убит сигналом с этим номером: `-9` — SIGKILL, `-15` — SIGTERM. bash показал бы
`128 + N`: 137 и 143.

</details>

**A12.** Почему процесс с PID 1 в контейнере не завершается по SIGTERM без обработчика?

<details><summary>Ответ</summary>

Для PID 1 ядро не выполняет действие по умолчанию для сигналов без обработчика.
Python не ставит обработчик на SIGTERM, поэтому сигнал игнорируется, пока не придёт SIGKILL.

</details>

**A13.** Зачем `Event.wait(30)` вместо `time.sleep(30)` в цикле демона?

<details><summary>Ответ</summary>

`Event.wait` прерывается сразу, как только обработчик сигнала вызывает `event.set()`;
`time.sleep` дожидается конца паузы — остановка задерживается.

</details>

**A14.** Что делает `filter="data"` в `tarfile.extractall` и от какой атаки защищает?

<details><summary>Ответ</summary>

Отбрасывает/запрещает абсолютные пути, `..`, опасные симлинки, спецфайлы и
setuid-биты. Защищает от path traversal — записи файлов за пределы каталога распаковки.

</details>

**A15.** Как защититься от одновременного запуска двух экземпляров скрипта из cron?

<details><summary>Ответ</summary>

`fcntl.flock(fd, LOCK_EX | LOCK_NB)` на lock-файле (аналог `flock -n`), держать дескриптор
открытым до конца; второй экземпляр получает `BlockingIOError` и выходит.

</details>

---

### Блок B. «Что выведет / что тут не так»


```text:no-line-numbers
# B1.
```text
```text:no-line-numbers
from pathlib import Path
```text
```text:no-line-numbers
print(Path("/var/backups") / "pg" / "db.sql.gz")
```text
```text:no-line-numbers
print(Path("db_2026.sql.gz").suffix, Path("db_2026.sql.gz").stem)
```text
```text:no-line-numbers
# B2.
```text
```text:no-line-numbers
subprocess.run(f"rm -rf /tmp/{job_name}", shell=True)      # job_name приходит из API
```text
```text:no-line-numbers
# B3.
```text
```text:no-line-numbers
r = subprocess.run(["ls", "/nope"], capture_output=True)
```text
```text:no-line-numbers
print(r.returncode, "No such" in r.stderr)
```text
```text:no-line-numbers
# B4.
```text
```text:no-line-numbers
r = subprocess.run(["curl", "-s", "http://10.0.0.99/health"])   # хост не отвечает
```text
```text:no-line-numbers
# B5.
```text
```text:no-line-numbers
backup_dir = Path(os.environ.get("BACKUP_DIR", ""))
```text
```text:no-line-numbers
shutil.rmtree(backup_dir / "old", ignore_errors=True)
```text
```text:no-line-numbers
for p in backup_dir.glob("*"):
```text
```text:no-line-numbers
    p.unlink()
```text
```text:no-line-numbers
# B6.
```text
```text:no-line-numbers
with open("/etc/nginx/nginx.conf", "w") as f:
```text
```text:no-line-numbers
    f.write(render_template())          # render_template() бросает исключение
```text
```text:no-line-numbers
# B7.
```text
```text:no-line-numbers
timeout = os.environ.get("TIMEOUT", 10)
```text
```text:no-line-numbers
time.sleep(timeout * 2)                 # TIMEOUT=5 задан в окружении
```text
```text:no-line-numbers
# B8.
```text
```text:no-line-numbers
r = subprocess.run([sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"])
```text
```text:no-line-numbers
print(r.returncode)
```text
```text:no-line-numbers
# B9.
```text
```text:no-line-numbers
p = subprocess.Popen(["some-tool"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
```text
```text:no-line-numbers
for line in p.stdout:
```text
```text:no-line-numbers
    print(line, end="")
```text
```text:no-line-numbers
# B10.
```text
```text:no-line-numbers
with tarfile.open(uploaded_archive) as tar:
```text
```text:no-line-numbers
    tar.extractall("/srv/app")
```text
```text:no-line-numbers
# B11.
```text
```text:no-line-numbers
tmp = Path("/tmp/metrics.prom.tmp")
```text
```text:no-line-numbers
tmp.write_text(data)
```text
```text:no-line-numbers
os.replace(tmp, "/var/lib/node_exporter/textfile/app.prom")   # /var — отдельный раздел
```text
```text:no-line-numbers
# B12.
```text
```text:no-line-numbers
r = subprocess.run(["systemctl", "is-active", "nginx"], check=True, capture_output=True, text=True)
```text
```text:no-line-numbers
print("nginx:", r.stdout.strip())       # nginx остановлен
```text
---

### Блок C. Практика


### C1. pathlib-разминка
**1.** Выведи 5 самых больших файлов в `/var/log` (рекурсивно) с размером в МБ.

<details><summary>Ответ</summary>

for p in Path("/proc").glob("[0-9]*/cmdline")
    if b"python" in p.read_bytes()
)
```text
(процессы могут исчезнуть между `glob` и `read_bytes` — оберни в `try/except OSError`).

</details>

**2.** Выведи файлы старше 7 дней в `~/Downloads` (или любом каталоге) с их возрастом в днях.
**3.** Посчитай суммарный размер `*.gz` в `/var/log`.
### C2. 🔑 Очистка с dry-run
Напиши `cleanup.py DIR --pattern '*.log' --days 14 [--apply]`:
- по умолчанию dry-run: только печатает, что удалит, и сколько места освободится;
- с `--apply` удаляет;
- отказывается работать, если `DIR` — `/`, пустой или не каталог;
- защищён lock-файлом от параллельного запуска.
Проверь на наборе файлов со старым mtime: `touch -d '20 days ago' old{1..3}.log`.

### C3. Атомарная запись
**1.** Реализуй `atomic_write(path, data)` из конспекта.

<details><summary>Ответ</summary>

for p in Path("/proc").glob("[0-9]*/cmdline")
    if b"python" in p.read_bytes()
)
```text
(процессы могут исчезнуть между `glob` и `read_bytes` — оберни в `try/except OSError`).

</details>

**2.** В другом терминале крути `while true; do cat target.txt; done`, а скриптом 1000 раз
   перезаписывай файл. Убедись, что ни разу не видно пустого или половинчатого содержимого.
**3.** Сравни с наивной записью `open(path, "w")`.
### C4. 🔑 Обёртка над командами
Напиши функцию `run(cmd: list[str], timeout: int = 60) -> str`, которая:
- возвращает stdout при успехе;
- при ненулевом коде бросает своё `CommandError` с кодом и stderr;
- при таймауте и отсутствии бинарника — тоже `CommandError` с понятным сообщением;
- логирует команду (без секретов!) и длительность.
Проверь на `["uname", "-a"]`, `["ls", "/nope"]`, `["sleep", "5"]` с таймаутом 1, `["nope"]`.

### C5. Код как ответ
Напиши `service_status(name) -> str`, которая возвращает `active`/`inactive`/`failed`/`unknown`
по `systemctl is-active` без исключений на ненулевой код.

### C6. Пайп без шелла
Перепиши на Python без `shell=True`: `ps aux | grep python | grep -v grep | wc -l`.
Вариант 1 — `ps` + фильтр в Python. Вариант 2 — вообще без внешних команд (подсказка: `/proc/*/cmdline`).

### C7. 🔑 SIGTERM и PID 1
**1.** Напиши демон: в цикле печатает «tick» раз в 5 секунд.

<details><summary>Ответ</summary>

for p in Path("/proc").glob("[0-9]*/cmdline")
    if b"python" in p.read_bytes()
)
```text
(процессы могут исчезнуть между `glob` и `read_bytes` — оберни в `try/except OSError`).

</details>

**2.** Собери образ (`FROM python:3.12-slim`, `CMD ["python", "-u", "daemon.py"]`),
   замерь `time docker stop &lt;id&gt;` — сколько секунд и какой код выхода (`docker inspect -f '&#123;&#123;.State.ExitCode&#125;&#125;'`)?
**3.** Добавь обработчик SIGTERM с `Event.wait()` — повтори замер.
**4.** Убери обработчик и запусти с `docker run --init` — что изменилось?

<details><summary>Ответ</summary>

```python
class CommandError(Exception): ...

def run(cmd: list[str], timeout: int = 60) -> str:
    start = time.monotonic()
    try:
        r = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise CommandError(f"не найдена команда {cmd[0]}") from None
    except subprocess.TimeoutExpired:
        raise CommandError(f"{cmd[0]}: таймаут {timeout}s") from None
    except subprocess.CalledProcessError as e:
        raise CommandError(f"{cmd[0]}: код {e.returncode}: {e.stderr.strip()}") from e
    finally:
        log.debug("%s: %.2fs", cmd[0], time.monotonic() - start)
    return r.stdout
```text
</details>

### C8. Архив с проверкой
Напиши `pack.py SRC DST_DIR`: собирает `SRC` в `name-YYYYmmdd-HHMMSS.tar.gz`, рядом кладёт
`.sha256`, затем проверяет архив: открывается, список файлов не пуст, сумма совпадает.

### C9. Безопасная распаковка
Создай «злой» архив с элементом `../evil.txt`:
`tarfile.open("evil.tgz", "w:gz").add("f.txt", arcname="../evil.txt")` (не забудь закрыть архив
или используй `with`). Распакуй в `./out` с `filter="data"` и без — где оказался файл
и какие сообщения выводит Python?

### C10. Потоковый вывод
Запусти `ping -c 5 1.1.1.1` через `Popen` и логируй каждую строку с отметкой времени по мере
появления. Верни код выхода `ping` как код выхода скрипта.

---

### Блок D. Инциденты


**D1.** Скрипт очистки удалил содержимое домашнего каталога пользователя, от которого запускался cron. В коде `Path(os.environ.get("CLEAN_DIR", ""))`. Что произошло и как защититься?

<details><summary>Ответ</summary>

Переменная не задана → `Path("")` → текущий каталог, а cron запускает из `$HOME`.
Защита: обязательная переменная (`os.environ["CLEAN_DIR"]`), проверка `is_dir()`, запрет `/`
и `$HOME`, `resolve()` и проверка, что путь внутри разрешённого корня; dry-run по умолчанию.

</details>

**D2.** Ночной бэкап «успешен» уже месяц, но файлы дампа по 0 байт. В коде `subprocess.run(["pg_dump", ...])`. Что не так?

<details><summary>Ответ</summary>

Нет `check=True` и проверки размера: `pg_dump` падает (пароль, сеть), а скрипт считает,
что всё хорошо. Нужны `check=True`, проверка размера/целостности дампа и метрика «время последнего
успешного бэкапа» с алертом.

</details>

**D3.** Скрипт в CI иногда висит до таймаута job'а (1 час) на шаге `subprocess.run(["ssh", host, ...])`. Что добавить?

<details><summary>Ответ</summary>

`timeout=` в `subprocess.run` и опции ssh `-o ConnectTimeout=10 -o BatchMode=yes`
(не ждать ввода пароля) и `ServerAliveInterval`.

</details>

**D4.** Nginx после деплоя не стартует: `nginx.conf` пустой. Деплой-скрипт упал на середине генерации конфига. Как переписать запись?

<details><summary>Ответ</summary>

Сгенерировать конфиг в строку, записать во временный файл рядом, проверить `nginx -t -c tmp`,
затем `os.replace` и `nginx -s reload`.

</details>

**D5.** Каждый деплой Python-воркера в k8s длится +30 секунд на под, а незаконченные задачи теряются. В чём причина?

<details><summary>Ответ</summary>

Воркер — PID 1 без обработчика SIGTERM: k8s ждёт `terminationGracePeriodSeconds` (30 с)
и убивает SIGKILL посреди задачи. Нужен обработчик: перестать брать новые задачи, закончить текущую, выйти.

</details>

**D6.** Скрипт выгрузки метрик пишет `.prom`-файл через `/tmp` и `os.replace` — в проде падает с `OSError: [Errno 18] Invalid cross-device link`. Почему?

<details><summary>Ответ</summary>

`/tmp` и каталог textfile на разных ФС, `rename` между ними невозможен. Временный файл —
в том же каталоге (или `write_to_textfile` из `prometheus_client`, он делает так сам).

</details>

**D7.** На сервере два экземпляра ночного бэкапа работают одновременно и мешают друг другу. Откуда второй и как не допустить?

<details><summary>Ответ</summary>

Первый ещё не закончился, а cron запустил следующий (или остался в `crontab` у двух
пользователей). Lock через `fcntl.flock`/`flock -n`, либо systemd-таймер (он не запустит сервис,
пока предыдущий запуск активен).

</details>

**D8.** Скрипт вызывает `subprocess.run("tar czf " + dst + " " + src, shell=True)`, на путях с пробелами создаются странные файлы и архив неполный. Объясни и исправь.

<details><summary>Ответ</summary>

Шелл режет строку по пробелам: `/data/my dir` превращается в два аргумента. Правильно:
`subprocess.run(["tar", "czf", dst, src], check=True)` или `tarfile` без внешних команд.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как запустить внешнюю команду из Python и получить её вывод?

<details><summary>Ответ</summary>

`subprocess.run([...], capture_output=True, text=True, check=True, timeout=N)`, вывод в `.stdout`.

</details>

**2.** Почему не стоит использовать `os.system` и `shell=True`?

<details><summary>Ответ</summary>

Нет таймаутов и нормального кода выхода, шелл открывает инъекции и ломается на пробелах.

</details>

**3.** Как сделать так, чтобы команда не висела вечно?

<details><summary>Ответ</summary>

`timeout=` в `subprocess.run` и таймауты самой утилиты (ssh `ConnectTimeout`, curl `--max-time`).

</details>

**4.** Как обработать SIGTERM в Python-приложении?

<details><summary>Ответ</summary>

`signal.signal(signal.SIGTERM, handler)`: обработчик ставит флаг/`Event`, главный цикл
   завершает текущую работу и выходит.

</details>

**5.** Почему контейнер с Python долго останавливается по `docker stop`?

<details><summary>Ответ</summary>

Python — PID 1 без обработчика SIGTERM: сигнал игнорируется, через 10 с приходит SIGKILL.

</details>

**6.** Как атомарно обновить файл?

<details><summary>Ответ</summary>

Временный файл в том же каталоге → `fsync` → `os.replace`.

</details>

**7.** Как безопасно работать с временными файлами?

<details><summary>Ответ</summary>

`tempfile.TemporaryDirectory`/`mkstemp` с уникальными именами, `with` для автоудаления.

</details>

**8.** Как прочитать сжатый `.gz` лог без распаковки на диск?

<details><summary>Ответ</summary>

`gzip.open(path, "rt", encoding="utf-8")` и чтение построчно.

</details>

**9.** Как в Python узнать свободное место на диске?

<details><summary>Ответ</summary>

`shutil.disk_usage(path)` → `total, used, free`.

</details>

**10.** Как не допустить параллельного запуска cron-скрипта?

<details><summary>Ответ</summary>

Lock-файл с `fcntl.flock` (или `flock -n` в crontab), либо systemd-таймер вместо cron.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Работаю с путями и файлами через `pathlib`, всегда указываю `encoding`
- [ ] Пишу важные файлы атомарно через временный файл и `os.replace`
- [ ] Пользуюсь `tempfile` вместо «вшитых» путей в `/tmp`
- [ ] Читаю окружение с проверкой обязательных переменных и приведением типов
- [ ] Запускаю команды списком с `check`, `capture_output`, `text`, `timeout`
- [ ] Отличаю «ненулевой код = ошибка» от «ненулевой код = ответ»
- [ ] Не использую `shell=True` с переменными и `os.system`
- [ ] Обрабатываю SIGTERM и понимаю проблему PID 1 в контейнере
- [ ] Собираю и безопасно распаковываю архивы (`filter="data"`), считаю sha256
- [ ] Защищаю cron-скрипты lock-файлом и dry-run по умолчанию
