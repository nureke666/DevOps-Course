---
title: "04. CLI, логирование и конфиги"
description: "Блок → Python для DevOps → тема 4 из 8."
---

# 04. CLI, логирование и конфиги

> Блок → **Python для DevOps** → тема 4 из 8.
> Аналог в bash: `getopts`, `>&2`, `source config.env` из [25_bash_robust.md](/linux/25-bash-robust).
>
> **После темы ты умеешь:** делать удобный CLI на `argparse` (флаги, подкоманды, `--dry-run`, `-v`),
> понимаешь, когда брать click/typer; логируешь через `logging` (уровни, формат, stderr, файл, JSON),
> а не `print`; безопасно читаешь YAML/JSON/TOML и собираешь настройки по приоритету
> «CLI > env > файл > дефолт».

---

## 🗺️ Карта темы

```text
   ./opsctl.py -v --config ops.yaml cleanup /var/backups --days 14 --apply
        │       │        │              │           │         │        │
        └───────┴────────┴──── argparse (или click / typer) ──┴────────┘
                                   │
        ┌──────────────────────────┼─────────────────────────────┐
    НАСТРОЙКИ                  ЛОГИРОВАНИЕ                    ПОВЕДЕНИЕ
    CLI > env > файл > дефолт  logging → stderr (journald,    dry-run по умолчанию,
    YAML: safe_load            docker, k8s соберут сами)      --apply / --yes,
    TOML: tomllib              уровни через -v / -q           коды выхода 0/1/2
    JSON: json                 JSON-формат для Loki/ELK
```text
---

## 1. argparse: основы

```python
import argparse, os

parser = argparse.ArgumentParser(
    prog="cleanup",
    description="Удаляет старые файлы бэкапов.",
    epilog="Пример: cleanup /var/backups --days 14 --apply",
    formatter_class=argparse.ArgumentDefaultsHelpFormatter,   # показывать дефолты в --help
)
parser.add_argument("path", help="каталог с бэкапами")                     # позиционный
parser.add_argument("--days", type=int, default=14, help="старше скольких дней")
parser.add_argument("--pattern", default="*.gz")
parser.add_argument("--level", choices=["debug", "info", "warning"], default="info")
parser.add_argument("--exclude", action="append", default=[], help="можно несколько раз")
parser.add_argument("--apply", action="store_true", help="реально удалить (иначе dry-run)")
parser.add_argument("-v", "--verbose", action="count", default=0)          # -v, -vv
parser.add_argument("--token", default=os.environ.get("API_TOKEN"), help="или env API_TOKEN")
parser.add_argument("--version", action="version", version="%(prog)s 1.2.0")

args = parser.parse_args()         # в тестах: parser.parse_args(["/tmp", "--days", "3"])
args.path, args.days, args.apply   # дефисы в именах → подчёркивания: --dry-run → args.dry_run
```text
| Что нужно | Как |
|-----------|-----|
| Флаг вкл/выкл | `action="store_true"` |
| Пара `--x / --no-x` | `action=argparse.BooleanOptionalAction` |
| Число | `type=int` / `type=float` |
| Путь | `type=Path` |
| Выбор из списка | `choices=[...]` |
| Несколько значений | `nargs="+"` (1+), `nargs="*"` (0+) |
| Повторяемая опция | `action="append"` |
| Обязательная опция | `required=True` (лучше позиционный аргумент) |
| Ошибка валидации | `parser.error("...")` — печатает usage и выходит с кодом 2 |

⚠️ `type=bool` не работает: `bool("false")` — это `True`. Для флагов только `store_true`
или `BooleanOptionalAction`.

---

## 2. ⭐ Подкоманды и каркас утилиты

```python
#!/usr/bin/env python3
"""opsctl — набор эксплуатационных команд."""
import argparse
import logging
import sys
from pathlib import Path

log = logging.getLogger("opsctl")


def cmd_cleanup(args: argparse.Namespace) -> int:
    mode = "удаляю" if args.apply else "[dry-run] к удалению"
    for p in sorted(args.path.glob(args.pattern)):
        log.info("%s: %s", mode, p)
        if args.apply:
            p.unlink(missing_ok=True)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    log.info("проверяю %s", ", ".join(args.hosts))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opsctl", description=__doc__)
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("-q", "--quiet", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("cleanup", help="удалить старые файлы")
    p.add_argument("path", type=Path)
    p.add_argument("--pattern", default="*.gz")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(func=cmd_cleanup)

    p = sub.add_parser("check", help="проверить хосты")
    p.add_argument("hosts", nargs="+")
    p.set_defaults(func=cmd_check)
    return parser


def setup_logging(verbose: int, quiet: bool) -> None:
    level = logging.WARNING if quiet else (logging.DEBUG if verbose else logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)      # приглушить болтливые библиотеки


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose, args.quiet)
    try:
        return args.func(args)
    except Exception:
        log.exception("команда %s упала", args.command)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```text
```bash
./opsctl.py --help
./opsctl.py -v cleanup /var/backups --pattern '*.sql.gz'          # dry-run
./opsctl.py cleanup /var/backups --apply
./opsctl.py check web1 web2; echo $?
```text
---

## 3. click и typer — когда argparse мало

| | argparse | click | typer |
|---|----------|-------|-------|
| Зависимости | stdlib | пакет `click` | пакет `typer` (поверх click) |
| Стиль | Объект парсера | Декораторы | Сигнатура функции + type hints |
| Когда | Скрипт должен работать без `pip install` | Большая утилита с группами команд | Быстро сделать красивый CLI |

```python
# typer: аргументы и опции выводятся из сигнатуры
from typing import Annotated
import typer

app = typer.Typer(help="Инструменты эксплуатации")

@app.command()
def cleanup(path: str, days: int = 14, apply: bool = False):
    """Удалить старые файлы (по умолчанию только показать)."""
    ...                                     # --days 3, --apply / --no-apply

@app.command()
def backup(db: str, bucket: Annotated[str, typer.Option(envvar="BACKUP_BUCKET")] = "backups"):
    """Сделать бэкап базы."""
    ...

if __name__ == "__main__":
    app()
```text
```python
# click: то же на декораторах
import click

@click.group()
def cli():
    """Инструменты эксплуатации."""

@cli.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False))
@click.option("--days", default=14, show_default=True)
@click.option("--apply", is_flag=True, help="реально удалить")
def cleanup(path, days, apply):
    """Удалить старые файлы."""
    click.echo(f"{path} {days} {apply}")

if __name__ == "__main__":
    cli()
```text
---

## 4. ⭐ logging вместо print

| Уровень | Когда | Пример |
|---------|-------|--------|
| `DEBUG` | Детали для отладки, по `-v` | «запрос GET /api/v4/projects?page=3» |
| `INFO` | Нормальный ход работы | «загружено 42 файла, 1.3 ГБ» |
| `WARNING` | Необычное, но работа продолжается | «ретрай 2/5: 503 от API» |
| `ERROR` | Операция не удалась | «не удалось загрузить db.sql.gz» |
| `CRITICAL` | Скрипт не может продолжать | «нет доступа к хранилищу» |

```python
log = logging.getLogger(__name__)          # в каждом модуле свой логгер

log.info("удалено %d файлов из %s", n, path)   # ⭐ аргументы отдельно: форматируется лениво
try:
    upload(file)
except OSError:
    log.exception("не удалось загрузить %s", file)   # ERROR + traceback
```text
**Почему не `print`:**
- у лога есть уровень, время, источник — можно фильтровать и искать;
- `logging` пишет в **stderr**, а stdout остаётся для данных: `./report.py --json | jq .` работает;
- уровень меняется флагом `-v/-q`, без правки кода;
- в systemd/docker/k8s stderr сам уходит в journald / `docker logs` / Loki.

```text
stdout  →  результат (таблица, JSON, CSV)   ← то, что пойдёт в pipe
stderr  →  логи и диагностика               ← то, что увидит человек / соберёт journald
```text
**Файл с ротацией** — только если нет journald/docker (голый сервер, cron):

```python
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler("/var/log/opsctl.log", maxBytes=10_000_000, backupCount=5, encoding="utf-8")
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.getLogger().addHandler(handler)
```text
**JSON-логи** для Loki/ELK — один объект на строку, поля ищутся без regex:

```python
import json, logging

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **getattr(record, "ctx", {}),          # доп. поля: log.info("...", extra={"ctx": {...&#125;&#125;)
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)

handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
log.info("бэкап загружен", extra={"ctx": {"bucket": "backups", "size_mb": 512&#125;&#125;)
# {"ts": "...", "level": "INFO", "logger": "__main__", "msg": "бэкап загружен", "bucket": "backups", "size_mb": 512}
```text
⚠️ Никогда не логируй токены, пароли, заголовки `Authorization`, весь конфиг или `os.environ`.

---

## 5. Конфиги: JSON, YAML, TOML

| Формат | Чтение | Запись | Заметка |
|--------|--------|--------|---------|
| JSON | `json.load(f)` | `json.dump(obj, f, indent=2, ensure_ascii=False)` | Без комментариев; ответы API, `-o json` |
| YAML | `yaml.safe_load(f)` (PyYAML) | `yaml.safe_dump(obj, sort_keys=False, allow_unicode=True)` | k8s, Ansible, compose, CI |
| TOML | `tomllib.load(f)` (stdlib 3.11+) | пакет `tomli-w` | `pyproject.toml`, конфиги утилит; файл открывать `"rb"` |

```python
import json, tomllib, yaml
from pathlib import Path

cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))

with open("config.yaml", encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}              # пустой файл → None, отсюда «or {}»

with open("pyproject.toml", "rb") as f:        # ⚠️ именно "rb"
    project = tomllib.load(f)["project"]

with open("manifests.yaml", encoding="utf-8") as f:
    docs = [d for d in yaml.safe_load_all(f) if d]    # несколько документов через ---
```text
⚠️ **YAML-сюрпризы** (PyYAML следует YAML 1.1):

```yaml
enabled: no          # → False (как и off, NO, false) — «норвежская проблема»: country: NO → False
version: 1.10        # → 1.1 (float!)
port_map: 22:22      # → 1342 (шестидесятеричное число)
mode: 010            # → 8 (восьмеричное)
safe: "1.10"         # → '1.10' — строки, похожие на числа/булевы, бери в кавычки
```text
⚠️ `yaml.load(f, Loader=yaml.Loader)` / `unsafe_load` на чужом файле может выполнить код
(`!!python/object/apply:os.system`). Всегда `safe_load`.

---

## 6. ⭐ Приоритет настроек: CLI > env > файл > дефолт

```text
дефолт в коде  ──►  конфиг-файл  ──►  переменные окружения  ──►  флаги CLI
 (разумно)          (общий для        (секреты, различия        (разовый
                    окружения)        dev/stage/prod, k8s)       запуск)
                                                     каждый следующий перекрывает предыдущий
```text
```python
import os
from dataclasses import dataclass, fields, replace

class ConfigError(Exception): ...

@dataclass
class Settings:
    endpoint: str = "http://localhost:9000"
    bucket: str = "backups"
    keep_days: int = 14
    dry_run: bool = True

def _convert(raw: str, typ: type):
    if typ is bool:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return typ(raw)

def load_settings(args) -> Settings:
    s = Settings()                                                  # 1. дефолты
    if args.config:                                                 # 2. файл
        data = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
        unknown = set(data) - {f.name for f in fields(Settings)}
        if unknown:
            raise ConfigError(f"неизвестные ключи в {args.config}: {sorted(unknown)}")
        s = replace(s, **data)
    for f in fields(Settings):                                      # 3. env: OPS_KEEP_DAYS=7
        raw = os.environ.get(f"OPS_{f.name.upper()}")
        if raw is not None:
            setattr(s, f.name, _convert(raw, f.type))
    for f in fields(Settings):                                      # 4. CLI, если задан явно
        value = getattr(args, f.name, None)
        if value is not None:
            setattr(s, f.name, value)
    if s.keep_days < 1:
        raise ConfigError("keep_days должен быть >= 1")
    return s
```text
Чтобы отличить «флаг не задан» от «задан дефолт», у CLI-опций `default=None`
(`--keep-days` с `type=int, default=None`, `--dry-run/--no-dry-run` через `BooleanOptionalAction`).

**Секреты:** из окружения или файла (`--token-file`, `/run/secrets/...` в Docker/k8s).
⚠️ Не аргументом CLI: он виден в `ps aux` всем пользователям хоста и остаётся в history.

---

## 7. dry-run и подтверждения

```python
def confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():          # cron/CI: спрашивать некого — считаем «нет»
        return False
    return input(f"{question} [y/N] ").strip().lower() in {"y", "yes"}

plan = [p for p in candidates if should_delete(p)]            # 1. план
for p in plan:
    log.info("%s %s", "удаляю" if args.apply else "[dry-run]", p)
if args.apply and plan and confirm(f"Удалить {len(plan)} файлов?", args.yes):   # 2. подтверждение
    for p in plan:
        p.unlink(missing_ok=True)                             # 3. выполнение
log.info("итого: %d файлов, режим %s", len(plan), "apply" if args.apply else "dry-run")
```text
Правила: разрушительное действие — dry-run по умолчанию; dry-run не меняет **ничего**
(ни каталогов, ни файлов состояния); в конце — сводка, сколько затронуто.

---

## 8. Грабли

| Грабля | Что происходит | Правильно |
|--------|----------------|-----------|
| `print` для логов | Смешано с данными в stdout, нет уровней и времени | `logging` → stderr |
| `logging.basicConfig` в модуле-библиотеке или после первого лога | Не срабатывает: у root уже есть обработчик | Один раз в `main()` (или `force=True`) |
| `log.info("x=%s y=%s", x)` | Ошибка форматирования в логе: «not enough arguments» | Число `%s` = числу аргументов |
| `type=bool` в argparse | `--flag false` → `True` | `store_true` / `BooleanOptionalAction` |
| У CLI-опций дефолты не `None` | Не понять, задал ли пользователь флаг — env/файл не работают | `default=None` и слияние по приоритету |
| `yaml.load` без SafeLoader | Выполнение кода из файла | `yaml.safe_load` |
| `enabled: no`, `version: 1.10` | `False`, `1.1` | Кавычки у строк |
| `open("x.toml")` для `tomllib` | `TypeError: File must be opened in binary mode` | `open(..., "rb")` |
| Токен в `--token` | Виден в `ps`, history, логах CI | env / файл-секрет |
| Неизвестные ключи конфига игнорируются | Опечатка `keep_day: 3` тихо не работает | Проверять лишние ключи |
| dry-run «почти ничего не меняет» | Создаёт каталоги, пишет state — сюрпризы | dry-run только читает |

---

## 💼 Как это в DevOps

- Любая утилита, которую запускают коллеги, должна иметь `--help`, dry-run и понятные коды
  выхода — иначе её боятся запускать и продолжают делать руками.
- В контейнерах и k8s логи идут в stderr, а сбор — задача платформы (journald, Docker, Promtail/Fluent Bit).
  JSON-формат экономит часы на парсинге в Loki/Kibana.
- Конфиг утилиты — YAML в git, секреты — из переменных окружения/Vault/k8s Secret, различия
  окружений — env. Это та же модель, что у Helm values и 12-factor приложений.
- `--dry-run` по умолчанию для всего, что удаляет, — стандартная практика: «уборщики» подов,
  ротация бэкапов, массовые правки через API (как `terraform plan` перед `apply`).
- На ревью смотрят: нет ли секретов в аргументах и логах, `safe_load` ли YAML, есть ли `-v`.

---

## 📌 Шпаргалка

| Хочу | Python |
|------|--------|
| Позиционный аргумент | `p.add_argument("path", type=Path)` |
| Флаг | `p.add_argument("--apply", action="store_true")` |
| `--x/--no-x` | `action=argparse.BooleanOptionalAction` |
| Уровень болтливости | `p.add_argument("-v", action="count", default=0)` |
| Подкоманды | `sub = p.add_subparsers(dest="cmd", required=True)` + `set_defaults(func=...)` |
| Дефолт из env | `default=os.environ.get("X")` |
| Ошибка аргументов (код 2) | `parser.error("...")` |
| Настроить логи | `logging.basicConfig(level=..., format="%(asctime)s %(levelname)s %(name)s: %(message)s")` |
| Логгер модуля | `log = logging.getLogger(__name__)` |
| Ошибка с traceback | `log.exception("...")` |
| Приглушить библиотеку | `logging.getLogger("urllib3").setLevel(logging.WARNING)` |
| Ротация файла | `RotatingFileHandler(path, maxBytes=..., backupCount=...)` |
| YAML | `yaml.safe_load(f)` / `yaml.safe_load_all(f)` |
| TOML | `tomllib.load(open(p, "rb"))` |
| JSON | `json.load(f)` / `json.dump(obj, f, indent=2, ensure_ascii=False)` |
| Приоритет | дефолт → файл → env → CLI |
| Спросить подтверждение | `input()` только если `sys.stdin.isatty()` |

---

## 🧠 Что запомнить

1. CLI — `argparse` (stdlib); click/typer — когда утилита большая и зависимость допустима.
2. `main(argv)` + `parse_args(argv)` — CLI легко тестировать.
3. Логи — `logging` в stderr, данные — в stdout. `print` для логов не используют.
4. Уровень логов меняется флагами `-v/-q`, болтливые библиотеки приглушают отдельно.
5. `log.info("... %s", x)` — ленивое форматирование; `log.exception` в `except` — с traceback.
6. В контейнерах и systemd пишут в stderr, файлы с ротацией — только на «голых» серверах.
7. YAML — только `safe_load`; строки, похожие на числа и `no/yes`, — в кавычках.
8. `tomllib` в stdlib, файл открывают в `"rb"`.
9. Приоритет: CLI > env > файл > дефолт; у CLI-опций `default=None`, лишние ключи конфига — ошибка.
10. Разрушительные действия — dry-run по умолчанию, `--apply`/`--yes` явно; секреты — не в аргументах.

➡️ Дальше: [05_http_api.md](/python/05-http-api) · Задачи: 04_cli_logging_config_tasks.md


---

### Блок A. Теория


**A1.** Чем позиционный аргумент отличается от опции? Когда что выбирать?

<details><summary>Ответ</summary>

Позиционный — обязательный «предмет» команды (`path`, `hosts`), опция — необязательная
настройка с дефолтом (`--days`). Обязательные значения лучше делать позиционными.

</details>

**A2.** Почему `type=bool` в argparse — ошибка? Как правильно сделать флаг и пару `--x/--no-x`?

<details><summary>Ответ</summary>

argparse передаёт в `bool()` строку, а любая непустая строка истинна. Флаг —
`action="store_true"`, пара — `action=argparse.BooleanOptionalAction`.

</details>

**A3.** Как устроены подкоманды в argparse и зачем `set_defaults(func=...)`?

<details><summary>Ответ</summary>

`add_subparsers(dest=..., required=True)` → для каждой подкоманды свой парсер со своими
аргументами. `set_defaults(func=handler)` кладёт обработчик в `args`, и `main` просто зовёт `args.func(args)`.

</details>

**A4.** С каким кодом выходит скрипт при неверных аргументах argparse? Как вызвать такую ошибку из своего кода?

<details><summary>Ответ</summary>

Код 2 и usage в stderr. Из своего кода — `parser.error("сообщение")`.

</details>

**A5.** Когда брать click или typer вместо argparse, а когда нет?

<details><summary>Ответ</summary>

click/typer — для больших утилит с группами команд, автодополнением, красивым help,
когда зависимость допустима. argparse — когда скрипт должен работать на голом python3 без `pip install`.

</details>

**A6.** ⭐ Назови четыре причины, почему в скриптах логируют через `logging`, а не `print`.

<details><summary>Ответ</summary>

Уровни и фильтрация; время и источник в каждой строке; вывод в stderr (stdout свободен для данных);
управление уровнем и форматом без правки кода; traceback через `log.exception`; сбор журналами платформы.

</details>

**A7.** Что пишут в stdout, а что в stderr? Почему это важно для пайпов?

<details><summary>Ответ</summary>

stdout — результат (данные, отчёт, JSON), stderr — логи и ошибки. Иначе `script | jq`
или `script > report.csv` получат мусор.

</details>

**A8.** Чем `log.info("n=%s", n)` лучше `log.info(f"n={n}")`? Когда разница реально заметна?

<details><summary>Ответ</summary>

Форматирование выполняется, только если сообщение пройдёт по уровню; плюс в логах-агрегаторах
шаблон сообщения одинаковый. Заметно, когда `debug` вызывается в горячем цикле или форматирование дорогое.

</details>

**A9.** Что делает `log.exception` и где его вызывать?

<details><summary>Ответ</summary>

Пишет сообщение уровня ERROR и traceback текущего исключения. Вызывают внутри `except`.

</details>

**A10.** Когда логировать в файл с ротацией, а когда просто в stderr?

<details><summary>Ответ</summary>

Файл с ротацией — когда нет системного сборщика (голый сервер, cron без journald).
В systemd, Docker, k8s — только stderr, сбор и ротация — задача платформы.

</details>

**A11.** Зачем JSON-логи и как их сделать на stdlib?

<details><summary>Ответ</summary>

Поля (уровень, сервис, хост, trace_id) доступны для поиска и фильтрации без regex,
многострочные traceback не разваливаются на события. Свой `logging.Formatter`, возвращающий `json.dumps(...)`.

</details>

**A12.** ⭐ Почему `yaml.load` опасен? Какие значения YAML 1.1 превращаются не в то, что ожидаешь?

<details><summary>Ответ</summary>

С полным `Loader` YAML может создавать произвольные Python-объекты и выполнять код.
Сюрпризы YAML 1.1 в PyYAML: `no/off/NO` → `False`, `yes/on/YES` → `True`, `1.10` → `1.1`, `22:22` → `1342`,
`010` → `8`, `~` → `None`, `2026-09-27` → `date`.

</details>

**A13.** Как прочитать TOML в Python 3.12 без внешних пакетов? Какая типичная ошибка?

<details><summary>Ответ</summary>

`tomllib.load(f)` с файлом, открытым в `"rb"`. Ошибка — открыть в текстовом режиме.

</details>

**A14.** ⭐ В каком порядке объединяются дефолты, конфиг-файл, env и CLI? Зачем CLI-опциям `default=None`?

<details><summary>Ответ</summary>

Дефолт → файл → env → CLI, каждый следующий перекрывает. `default=None` позволяет отличить
«не задано» от «задано значение по умолчанию», иначе CLI-дефолт перебьёт env и файл.

</details>

**A15.** Почему секреты не передают аргументами командной строки? Откуда их брать?

<details><summary>Ответ</summary>

Аргументы видны в `ps aux` всем пользователям хоста, попадают в history шелла и логи CI.
Секреты — из env, файла (`/run/secrets/...`, k8s Secret как файл), Vault.

</details>

---

### Блок B. «Что выведет / что тут не так»


```text:no-line-numbers
# B1.
```text
```text:no-line-numbers
p = argparse.ArgumentParser()
```text
```text:no-line-numbers
p.add_argument("--verbose", type=bool, default=False)
```text
```text:no-line-numbers
print(p.parse_args(["--verbose", "false"]).verbose)
```text
```text:no-line-numbers
# B2.
```text
```text:no-line-numbers
p = argparse.ArgumentParser()
```text
```text:no-line-numbers
p.add_argument("--dry-run", action="store_true")
```text
```text:no-line-numbers
args = p.parse_args(["--dry-run"])
```text
```text:no-line-numbers
print(args.dry-run)
```text
```text:no-line-numbers
# B3.
```text
```text:no-line-numbers
import logging
```text
```text:no-line-numbers
log = logging.getLogger("app")
```text
```text:no-line-numbers
log.info("старт")
```text
```text:no-line-numbers
logging.basicConfig(level=logging.INFO)
```text
```text:no-line-numbers
log.info("работаю")
```text
```text:no-line-numbers
log.debug("детали")
```text
```text:no-line-numbers
# B4.
```text
```text:no-line-numbers
log.info("загружено %s файлов в %s", count)
```text
```text:no-line-numbers
# B5.
```text
```text:no-line-numbers
import yaml
```text
```text:no-line-numbers
print(yaml.safe_load("""
```text
```text:no-line-numbers
country: NO
```text
```text:no-line-numbers
version: 1.10
```text
```text:no-line-numbers
enabled: off
```text
```text:no-line-numbers
ports: 22:22
```text
```text:no-line-numbers
name: "1.10"
```text
```text:no-line-numbers
"""))
```text
```text:no-line-numbers
# B6.
```text
```text:no-line-numbers
import tomllib
```text
```text:no-line-numbers
with open("pyproject.toml") as f:
```text
```text:no-line-numbers
    data = tomllib.load(f)
```text
```text:no-line-numbers
# B7.
```text
```text:no-line-numbers
cfg = yaml.load(open("user_upload.yaml"), Loader=yaml.Loader)
```text
```text:no-line-numbers
# B8.
```text
```text:no-line-numbers
print(f"Обработано {n} файлов")          # скрипт вызывают так: ./report.py --json | jq .
```text
```text:no-line-numbers
print(json.dumps(result))
```text
```text:no-line-numbers
# B9.
```text
```text:no-line-numbers
p.add_argument("--days", type=int, default=14)
```text
```text:no-line-numbers
days = args.days or int(os.environ.get("KEEP_DAYS", 14))   # KEEP_DAYS=3 задан
```text
```text:no-line-numbers
B10.  $ ./deploy.py --token glpat-xxxxxxxx --env prod
```text
<details><summary>Ответ</summary>

⚠️ Токен виден в `ps`, history, логах CI. Из env или файла.

</details>

```text:no-line-numbers
# B11.
```text
```text:no-line-numbers
try:
```text
```text:no-line-numbers
    upload(f)
```text
```text:no-line-numbers
except Exception as e:
```text
```text:no-line-numbers
    log.error("ошибка: " + str(e))
```text
```text:no-line-numbers
# B12.
```text
```text:no-line-numbers
cfg = yaml.safe_load(open("empty.yaml"))      # файл пустой
```text
```text:no-line-numbers
print(cfg.get("bucket", "backups"))
```text
---

### Блок C. Практика


### C1. argparse с нуля
Сделай `ping_hosts.py HOST [HOST ...] --count N --timeout SEC --format {text,json}`:
- `--count` по умолчанию 3, `--timeout` — 2.0, `--format` — text;
- `--help` показывает дефолты;
- если `--count` < 1 — ошибка через `parser.error` (код 2).
Пока без реального ping — печатай разобранные аргументы.

### C2. 🔑 Утилита с подкомандами
Собери `opsctl.py` из конспекта с подкомандами `cleanup` и `check`, добавь третью —
`disk` (печатает занятость разделов из списка, код 1 при превышении порога).
Проверь `opsctl.py --help`, `opsctl.py disk --help`, запуск без подкоманды (код?).

### C3. 🔑 Логирование
**1.** Добавь в `opsctl.py` уровни: по умолчанию INFO, `-v` — DEBUG, `-q` — WARNING.

<details><summary>Ответ</summary>

```python
p = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
p.add_argument("hosts", nargs="+")
p.add_argument("--count", type=int, default=3)
p.add_argument("--timeout", type=float, default=2.0)
p.add_argument("--format", choices=["text", "json"], default="text")
args = p.parse_args()
if args.count < 1:
    p.error("--count должен быть >= 1")
```text
</details>

**2.** Приглуши логгер `urllib3`.

<details><summary>Ответ</summary>

Без подкоманды: `error: the following arguments are required: command`, код 2.

</details>

**3.** Проверь, что `./opsctl.py disk / 2>/dev/null` не печатает логов, а `2>&1 | grep WARNING` их находит.

<details><summary>Ответ</summary>

Проверка: `./opsctl.py disk / 2>/dev/null; echo $?` — логов нет, код есть.

</details>

**4.** Сделай так, чтобы исключение в подкоманде логировалось с traceback и давало код 1.

<details><summary>Ответ</summary>

Выбор форматтера:
```python
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter() if args.log_format == "json"
                     else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.basicConfig(level=level, handlers=[handler])
log.warning("мало места", extra={"ctx": {"host": socket.gethostname(), "mount": "/"&#125;&#125;)
```text
</details>

### C4. JSON-логи
Добавь флаг `--log-format {text,json}`. В JSON-режиме каждая строка — валидный JSON
(`./opsctl.py --log-format json disk / 2>&1 >/dev/null | jq .level`). Добавь поле `host` через `extra`.

### C5. typer или click
Перепиши `cleanup` на typer (или click): аргумент `path`, опции `--days`, `--apply`,
`--bucket` с чтением из env `BACKUP_BUCKET`. Сравни объём кода и `--help` с argparse-версией.

### C6. 🔑 Конфиг по приоритетам
Реализуй `load_settings` из конспекта для настроек `endpoint`, `bucket`, `keep_days`, `dry_run`:
**1.** Конфиг `ops.yaml` задаёт `keep_days: 30`.

<details><summary>Ответ</summary>

```python
p = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
p.add_argument("hosts", nargs="+")
p.add_argument("--count", type=int, default=3)
p.add_argument("--timeout", type=float, default=2.0)
p.add_argument("--format", choices=["text", "json"], default="text")
args = p.parse_args()
if args.count < 1:
    p.error("--count должен быть >= 1")
```text
</details>

**2.** `OPS_KEEP_DAYS=7` перекрывает файл.

<details><summary>Ответ</summary>

Без подкоманды: `error: the following arguments are required: command`, код 2.

</details>

**3.** `--keep-days 3` перекрывает всё.

<details><summary>Ответ</summary>

Проверка: `./opsctl.py disk / 2>/dev/null; echo $?` — логов нет, код есть.

</details>

**4.** Опечатка в конфиге (`keep_day: 3`) → понятная ошибка и код 2.
Покажи все четыре сценария.

<details><summary>Ответ</summary>

Выбор форматтера:
```python
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter() if args.log_format == "json"
                     else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.basicConfig(level=level, handlers=[handler])
log.warning("мало места", extra={"ctx": {"host": socket.gethostname(), "mount": "/"&#125;&#125;)
```text
</details>

### C7. YAML-ловушки
Составь YAML с `no`, `on`, `1.10`, `22:22`, `010`, `0x1F`, `~`, `2026-09-27` и посмотри,
во что превращает их `safe_load`. Исправь файл так, чтобы всё было строками.

### C8. TOML
Создай `tool.toml` с секциями `[storage]` и `[[targets]]` (массив таблиц) и прочитай через `tomllib`.
Выведи список целей.

### C9. dry-run и подтверждение
Добавь в `cleanup` флаги `--apply` и `--yes`. Без `--apply` — только план; с `--apply` без `--yes` —
вопрос `[y/N]`, но если stdin не терминал (`echo | ./opsctl.py ...`) — отказ без вопроса.
В конце — сводка «N файлов, X МБ, режим».

### C10. Секрет из файла
Добавь `--token-file PATH` (по умолчанию из env `API_TOKEN_FILE`). Если не задан — берёт env
`API_TOKEN`. Убедись, что токен нигде не попадает в логи даже на `-v`.

---

### Блок D. Инциденты


**D1.** В лог-файле утилиты нет ни одной строки INFO, хотя `main()` вызывает
`logging.basicConfig(level=logging.INFO, filename="/var/log/tool.log")`. Перед этим импортируется
модуль, который при импорте выполняет `logging.warning("устаревшая опция")`. Что случилось?

<details><summary>Ответ</summary>

Функции уровня модуля (`logging.warning()`, `logging.info()`...) при отсутствии обработчиков
у корневого логгера сами вызывают `basicConfig()` с настройками по умолчанию (stderr, WARNING).
Следующий `basicConfig` в `main()` уже ничего не делает — у root есть обработчик, поэтому файл
и уровень INFO не применились. Настраивать логирование первым делом в `main()` (или `force=True`),
в модулях — только `log = logging.getLogger(__name__)`.

</details>

**D2.** CI-пайплайн парсит вывод скрипта через `jq` и падает с `parse error`. Скрипт печатает JSON. В чём проблема?

<details><summary>Ответ</summary>

В stdout, кроме JSON, попадают `print`-сообщения или логи (логгер настроен на stdout).
Логи — в stderr, в stdout — только JSON.

</details>

**D3.** В конфиге утилиты `log_mode: off` — ожидалась строка режима `"off"`, а код получил `False`
и включил режим по умолчанию. Что произошло и как избежать?

<details><summary>Ответ</summary>

YAML 1.1 превратил `off` в `False`. Строки, похожие на булевы/числа, берут в кавычки
(`log_mode: "off"`); в CI полезен `yamllint` (правило `truthy`), а в коде — проверка типа значения.

</details>

**D4.** Утилита игнорирует `KEEP_DAYS=3` из окружения и всегда удаляет бэкапы старше 14 дней. В коде `default=14` у argparse и `args.keep_days or env`. Почему?

<details><summary>Ответ</summary>

Дефолт argparse `14` всегда «истинный», `or` до env не доходит. `default=None` и слияние
по приоритету дефолт → файл → env → CLI.

</details>

**D5.** Токен GitLab утёк: его нашли в логах CI. Утилита вызывалась как `tool.py --token $GITLAB_TOKEN -v`. Назови два места утечки.

<details><summary>Ответ</summary>

Аргумент командной строки (виден в `ps`, в логе CI как часть команды) и `-v`: утилита логирует
аргументы/заголовки на DEBUG. Токен — только из env/файла, в логах — маскировать.

</details>

**D6.** Логи Python-сервиса в Kibana приходят «лесенкой»: traceback разбит на 20 отдельных событий. Как исправить?

<details><summary>Ответ</summary>

Логи текстовые, и сборщик считает каждую строку traceback отдельным событием. JSON-форматтер
(traceback в поле `exc`) или multiline-правило в сборщике.

</details>

**D7.** Скрипт «уборки» в dry-run-режиме создал на проде пустые каталоги и файл состояния, и следующий реальный запуск решил, что уборка уже была. Что нарушено?

<details><summary>Ответ</summary>

Dry-run должен только читать и показывать план. Любые изменения — каталоги, state, метки —
только в режиме `--apply`.

</details>

**D8.** В конфиге опечатка `bukcet: prod-backups`, скрипт неделю грузил бэкапы в дефолтный бакет `backups`. Как такое ловить?

<details><summary>Ответ</summary>

Проверять неизвестные ключи конфига (как в `load_settings`) или схему (dataclass/pydantic):
опечатка → ошибка при старте, а не тихий дефолт.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как сделать CLI для Python-скрипта?

<details><summary>Ответ</summary>

`argparse` (stdlib) с подкомандами, `--help`, дефолтами; для больших утилит — click/typer.

</details>

**2.** Чем logging лучше print?

<details><summary>Ответ</summary>

Уровни, время, источник, вывод в stderr, настройка без правки кода, traceback, интеграция со сборщиками.

</details>

**3.** Какие уровни логирования есть и когда какой?

<details><summary>Ответ</summary>

DEBUG — отладка, INFO — ход работы, WARNING — необычное без остановки, ERROR — операция не удалась,
   CRITICAL — продолжать нельзя.

</details>

**4.** Куда писать логи приложения в контейнере?

<details><summary>Ответ</summary>

В stdout/stderr — Docker/k8s собирают сами; без файлов внутри контейнера.

</details>

**5.** Как безопасно прочитать YAML?

<details><summary>Ответ</summary>

`yaml.safe_load`, строковые значения в кавычках, проверка схемы.

</details>

**6.** Как организовать конфигурацию утилиты для разных окружений?

<details><summary>Ответ</summary>

Дефолты в коде, общий конфиг в git, различия окружений и секреты — через env; CLI — для разовых
   переопределений. Приоритет CLI > env > файл > дефолт.

</details>

**7.** Что такое dry-run и зачем он?

<details><summary>Ответ</summary>

Режим, в котором утилита показывает план действий, ничего не меняя. Защищает от ошибок
   в фильтрах и путях при разрушительных операциях.

</details>

**8.** Как передавать секреты в скрипт?

<details><summary>Ответ</summary>

Через переменные окружения, файлы-секреты (Docker/k8s), Vault; не аргументами и не в git.

</details>

**9.** Как сделать логи удобными для Loki/ELK?

<details><summary>Ответ</summary>

Писать структурированные JSON-логи в stderr, по одному событию на строку, с полями уровня, сервиса, контекста.

</details>

**10.** Как протестировать CLI?

<details><summary>Ответ</summary>

`main(argv)` + `parse_args(argv)` → вызывать из pytest с разными argv, проверять код выхода
    и вывод через `capsys`/`caplog` (тема 08).

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Пишу CLI на argparse с подкомандами, типами, `choices`, `--version`
- [ ] Делаю флаги через `store_true`/`BooleanOptionalAction`, а не `type=bool`
- [ ] Логирую через `logging`: логгер на модуль, уровни, `-v/-q`, `log.exception`
- [ ] Разделяю stdout (данные) и stderr (логи)
- [ ] Умею JSON-формат логов и ротацию файла, знаю, когда что нужно
- [ ] Читаю YAML только через `safe_load` и знаю его ловушки
- [ ] Читаю TOML через `tomllib` (`"rb"`)
- [ ] Собираю настройки по приоритету CLI > env > файл > дефолт, ловлю лишние ключи
- [ ] Делаю dry-run по умолчанию и подтверждение для разрушительных действий
- [ ] Не передаю секреты аргументами и не пишу их в логи
