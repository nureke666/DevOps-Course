---
title: "08. Упаковка и качество: pyproject, ruff, pytest, Docker, CI"
description: "Блок → Python для DevOps → тема 8 из 8."
---

# 08. Упаковка и качество: pyproject, ruff, pytest, Docker, CI

> Блок → **Python для DevOps** → тема 8 из 8.
> Смежные блоки: [03_dockerfile.md](/docker/03-dockerfile), [04_build_cache_multistage.md](/docker/04-build-cache-multistage),
> [05_gitlab_ci_basics.md](/cicd/05-gitlab-ci-basics).
>
> **После темы ты умеешь:** раскладывать утилиту в структуру проекта с `pyproject.toml` и entry point,
> ставить её через uv/pip/pipx, держать код чистым через ruff (линт + формат), писать pytest-тесты
> для скриптов с моками subprocess и HTTP, собирать компактный Docker-образ (slim, non-root,
> multi-stage) и гонять линт и тесты в GitLab CI.

---

## 🗺️ Карта темы

```text
 скрипт.py ─────► проект-утилита ─────► качество ──────────────► доставка
 (один файл,      src/opsctl/           ruff check  — линт       Docker-образ: slim, non-root,
  «у меня         pyproject.toml        ruff format — формат     слой зависимостей отдельно
  работает»)      [project.scripts]     pytest + моки            uv tool / pipx install
                  uv.lock               subprocess, HTTP, env    GitLab CI: lint → test → build
```text
---

## 1. Когда скрипт становится проектом

Признаки: файлов больше одного, есть зависимости, утилиту запускают коллеги или CI, хочется тестов.

```text
opsctl/
├── pyproject.toml            ← метаданные, зависимости, entry point, настройки ruff/pytest
├── uv.lock                   ← lock-файл (или requirements.txt + requirements-dev.txt)
├── README.md
├── src/opsctl/
│   ├── __init__.py
│   ├── __main__.py           ← python -m opsctl
│   ├── cli.py                ← argparse + main(): только разбор аргументов и коды выхода
│   ├── backup.py             ← логика: функции без print/argparse, их и тестируют
│   └── notify.py             ← Telegram/HTTP
├── tests/
│   ├── test_backup.py
│   └── test_cli.py
├── Dockerfile
├── .dockerignore
└── .gitlab-ci.yml
```text
- **src-layout**: тесты импортируют установленный пакет, а не случайные файлы из текущего каталога —
  то, что прошло локально, пройдёт и в CI.
- **Логика отдельно от краёв**: функции принимают данные и возвращают результат; CLI, subprocess, HTTP —
  тонкие обёртки. Такую логику тестируют без моков.

```python
# src/opsctl/__main__.py
from opsctl.cli import main

raise SystemExit(main())
```text
---

## 2. pyproject.toml

```toml
[project]
name = "opsctl"
version = "0.1.0"
description = "Эксплуатационные команды: бэкапы, уборка, проверки"
requires-python = ">=3.12"
dependencies = [
    "requests>=2.31",
    "pyyaml>=6",
]

[project.scripts]
opsctl = "opsctl.cli:main"              # после установки появится команда opsctl

[dependency-groups]
dev = ["pytest>=8", "responses", "ruff"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM", "S", "G"]
ignore = ["S603", "S607"]               # «любой subprocess подозрителен» — в ops-коде шумно

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S101"]                    # assert в тестах — норма

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
```text
```bash
uv sync                          # venv + зависимости + dev-группа + сам проект (editable)
uv run opsctl --help             # entry point из [project.scripts]
uv run python -m opsctl --help
uv add boto3                     # добавить зависимость (обновит pyproject и uv.lock)
uv build                         # dist/opsctl-0.1.0-py3-none-any.whl

# без uv
python -m venv .venv && .venv/bin/pip install -e . pytest responses ruff

# поставить утилиту «как программу» себе или на сервер
uv tool install .                # или: pipx install .
pipx install dist/opsctl-0.1.0-py3-none-any.whl
```text
Версия в коде без дублирования: `importlib.metadata.version("opsctl")`.

---

## 3. ruff: линтер и форматтер в одном

```bash
ruff check .                     # линт
ruff check --fix .               # исправить то, что можно автоматически (импорты, pyupgrade)
ruff format .                    # отформатировать (как black)
ruff format --check .            # в CI: упасть, если код не отформатирован
ruff check --output-format=gitlab . > gl-code-quality-report.json   # отчёт для GitLab MR
```text
Что он ловит в ops-скриптах (правила из `select` выше):

| Код | Что | Тема |
|-----|-----|------|
| `F401`, `F821` | Неиспользуемый импорт, неопределённое имя | 02 |
| `B006` | Изменяемое значение по умолчанию | 02 |
| `E722`, `S110` | Голый `except`, `except: pass` | 02 |
| `S602` | `subprocess` с `shell=True` | 03 |
| `S108` | Жёстко прописанный путь в `/tmp` | 03 |
| `S202` | `tarfile.extractall` (проверь `filter`) | 03 |
| `S506` | `yaml.load` вместо `safe_load` | 04 |
| `G004` | f-строка в `log.info(...)` | 04 |
| `S113`, `S501` | `requests` без `timeout`, `verify=False` | 05 |
| `S105` | Пароль/токен строкой в коде | — |
| `UP045` | `Optional[X]` → `X \| None` | 02 |
| `I001` | Порядок импортов | — |

Точечное исключение — с объяснением: `subprocess.run(cmd, shell=True)  # noqa: S602 — фиксированная строка без переменных`.

---

## 4. ⭐ pytest для скриптов

```python
# tests/test_backup.py
import os
import time

import pytest

from opsctl.backup import find_old_files, parse_size


@pytest.mark.parametrize(("text", "expected"), [("10K", 10_240), ("1M", 1_048_576), ("512", 512)])
def test_parse_size(text, expected):
    assert parse_size(text) == expected


def test_parse_size_rejects_garbage():
    with pytest.raises(ValueError):
        parse_size("много")


def test_find_old_files(tmp_path):  # tmp_path — свой временный каталог на каждый тест
    old, new = tmp_path / "old.gz", tmp_path / "new.gz"
    old.write_text("x")
    new.write_text("x")
    week_ago = time.time() - 8 * 86400
    os.utime(old, (week_ago, week_ago))  # подделать mtime
    assert find_old_files(tmp_path, "*.gz", days=7) == [old]
```text
| Фикстура | Для чего |
|----------|----------|
| `tmp_path` | Временный каталог (`Path`) — файлы, конфиги, архивы |
| `monkeypatch` | Подменить env (`setenv`/`delenv`), атрибуты, текущий каталог |
| `capsys` | Перехватить stdout/stderr (`capsys.readouterr().out`) |
| `caplog` | Проверить логи (`caplog.text`, `caplog.records`) |

**CLI через `main(argv)`:**

```python
# tests/test_cli.py
from opsctl.cli import main


def test_cleanup_dry_run_keeps_files(tmp_path):
    f = tmp_path / "a.gz"
    f.write_text("x")
    assert main(["cleanup", str(tmp_path), "--pattern", "*.gz"]) == 0
    assert f.exists()  # dry-run ничего не удалил


def test_missing_token(monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    assert main(["pipelines", "devops"]) == 2
```text
**Мок subprocess** — тест не должен реально звать `pg_dump`:

```python
import subprocess
from unittest import mock

import pytest

from opsctl import backup


def test_dump_builds_right_command(tmp_path):
    ok = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with mock.patch("opsctl.backup.subprocess.run", return_value=ok) as run:
        backup.dump_db("app", tmp_path / "app.dump")
    cmd, kwargs = run.call_args.args[0], run.call_args.kwargs
    assert cmd[0] == "pg_dump"
    assert "app" in cmd
    assert kwargs["check"] is True
    assert kwargs["timeout"] > 0


def test_dump_error_is_wrapped(tmp_path):
    err = subprocess.CalledProcessError(1, ["pg_dump"], stderr="password authentication failed")
    with (
        mock.patch("opsctl.backup.subprocess.run", side_effect=err),
        pytest.raises(backup.BackupError, match="authentication failed"),
    ):
        backup.dump_db("app", tmp_path / "app.dump")
```text
⭐ Патчить **там, где имя ищется**: модуль делает `import subprocess` и зовёт `subprocess.run` —
патчим `opsctl.backup.subprocess.run`; если бы было `from subprocess import run` — `opsctl.backup.run`.

**Мок HTTP** — библиотека `responses` для requests (для httpx — `respx` или встроенный `httpx.MockTransport`):

```python
import json

import responses

from opsctl import notify


@responses.activate
def test_send_telegram(monkeypatch):
    monkeypatch.setenv("TG_BOT_TOKEN", "t0k")
    monkeypatch.setenv("TG_CHAT_ID", "42")
    responses.post("https://api.telegram.org/bott0k/sendMessage", json={"ok": True})

    notify.send_telegram("диск <b>90%</b>")

    body = json.loads(responses.calls[0].request.body)
    assert body["chat_id"] == "42"


@responses.activate
def test_retry_on_503():
    responses.get("https://api.example.com/items", status=503)  # сначала 503,
    responses.get("https://api.example.com/items", json=[1, 2])  # затем успех
    assert notify.get_items() == [1, 2]  # get_items() ходит через Session с Retry
    assert len(responses.calls) == 2
```text
Незарегистрированный URL в `@responses.activate` → `ConnectionError`: тест никогда не уйдёт в реальную сеть.

```bash
pytest -q                     # тихо
pytest -x --lf                # остановиться на первой ошибке / только упавшие в прошлый раз
pytest -k telegram -v         # по имени
```text
---

## 5. Dockerfile для Python-утилиты

**Базовый вариант** — хватает в большинстве случаев:

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
# ⭐ слой зависимостей кэшируется отдельно от кода
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY src/ ./src/
ENV PYTHONPATH=/app/src

# не root
RUN useradd --system --uid 10001 --no-create-home app
USER app
# exec-форма (JSON-массив): Python получает сигналы напрямую
ENTRYPOINT ["python", "-m", "opsctl"]
CMD ["--help"]
```text
**Multi-stage** — когда при сборке нужны компиляторы (пакеты с C-расширениями без готовых wheel'ов),
а в итоговом образе они лишние:

```dockerfile
FROM python:3.12-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps .

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:$PATH
# только готовое окружение, без компиляторов
COPY --from=build /opt/venv /opt/venv
RUN useradd --system --uid 10001 --no-create-home app
USER app
ENTRYPOINT ["opsctl"]
```text
С uv тот же приём: `uv sync --locked --no-dev --no-install-project` (слой зависимостей),
затем копирование `src/` и `uv sync --locked --no-dev --no-editable`.

```gitignore
# .dockerignore
.venv
.git
__pycache__
.pytest_cache
.ruff_cache
dist
tests
```text
```bash
docker build -t opsctl:dev .
docker run --rm opsctl:dev --help
docker run --rm --entrypoint id opsctl:dev          # uid=10001(app) — не root
docker image ls opsctl                              # slim-образ ~150 МБ против ~1 ГБ у python:3.12
```text
- Долгоживущий процесс в контейнере обрабатывает SIGTERM (тема 03) или запускается с `--init`.
- `alpine` для Python часто хуже `slim`: musl, часть пакетов собирается из исходников — медленно и больно.

---

## 6. GitLab CI: линт → тесты → образ

```yaml
# .gitlab-ci.yml
stages: [lint, test, build]

variables:
  UV_CACHE_DIR: "$CI_PROJECT_DIR/.uv-cache"

.python:
  image: python:3.12-slim
  before_script:
    - pip install --quiet uv
    - uv sync --locked                 # ровно то, что в uv.lock; расхождение с pyproject → ошибка
  cache:
    key:
      files: [uv.lock]
    paths: [.uv-cache]

lint:
  stage: lint
  extends: .python
  script:
    - uv run ruff format --check .
    - uv run ruff check .

test:
  stage: test
  extends: .python
  script:
    - uv run pytest --junitxml=report.xml
  artifacts:
    when: always
    reports:
      junit: report.xml                # результаты тестов прямо в MR

build:
  stage: build
  image: docker:latest                 # в проде — зафиксированная версия
  services: [docker:dind]
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  script:
    - echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
    - docker build -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" .
    - docker push "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
```text
Варианты сборки образа в CI (dind, rootless BuildKit, buildah; kaniko — legacy) — в [07_gitlab_ci_docker.md](/cicd/07-gitlab-ci-docker).
Без uv: `pip install -r requirements-dev.txt` в `before_script` и кэш `~/.cache/pip` по файлу requirements.

Локально те же проверки до коммита — `pre-commit` с хуками `ruff-check` и `ruff-format`
из репозитория `astral-sh/ruff-pre-commit` (`pre-commit autoupdate` проставит актуальную версию).

---

## 7. Утилита готова к людям, если…

| Пункт | Проверка |
|-------|----------|
| Ставится одной командой | `uv tool install .` / `pipx install .` / `docker run` |
| `--help` понятен без README | Описание, примеры, дефолты |
| Разрушительное — dry-run по умолчанию | `--apply` / `--yes` |
| Коды выхода осмысленные | 0 / 1 / 2 |
| Логи в stderr, данные в stdout | `opsctl report --json \| jq .` |
| Секреты только из env/файлов | Нет токенов в аргументах, логах, git |
| Зависимости зафиксированы | `uv.lock` / `requirements.txt` с `==` |
| ruff и pytest зелёные в CI | Пайплайн на каждый MR |
| Образ slim и non-root | `docker run --entrypoint id` |
| README: что делает, как запустить, какие права нужны | 5 минут до первого запуска |

---

## 8. Грабли

| Грабля | Что происходит | Правильно |
|--------|----------------|-----------|
| Плоская структура, тесты импортируют файлы из cwd | Локально работает, в CI/после установки — `ModuleNotFoundError` | src-layout + установка пакета |
| `mock.patch("subprocess.run")` при `from subprocess import run` в модуле | Мок не срабатывает, зовётся настоящий `run` | Патчить имя в модуле, где оно ищется |
| Тесты ходят в реальную сеть/API | Флапающие тесты, токены в CI | `responses`/`respx`, фейки |
| Тест зависит от «сейчас» | Падает в полночь или 1-го числа | Передавать `now` параметром |
| `COPY . .` до `pip install` | Любая правка кода пересобирает зависимости | Сначала requirements, потом код |
| Нет `.dockerignore` | `.venv`, `.git`, кэши в образе | `.dockerignore` |
| Контейнер от root | Лишние права при компрометации | `USER app` |
| `ENTRYPOINT python -m opsctl` (shell-форма) | Python не PID 1 под `sh`, SIGTERM не доходит | exec-форма `["python", "-m", "opsctl"]` |
| Комментарий в конце строки Dockerfile (`USER app  # не root`) | Docker считает `#...` аргументами: ошибка или JSON-форма превращается в shell-форму | Комментарии — только отдельной строкой |
| `# noqa` на всё подряд | Линтер формально зелёный, проблемы на месте | Исключения точечно и с причиной |
| CI ставит зависимости без lock | Сборки отличаются от локальных | `uv sync --locked` / `pip install -r` с `==` |

---

## 💼 Как это в DevOps

- Утилиты команды эксплуатации живут в одном репозитории (`ops-tools`) с общим pyproject, ruff и тестами;
  на серверы попадают Docker-образом или через `uv tool`/`pipx`, в k8s — как CronJob/Job с этим образом.
- Тесты для скриптов — не «для галочки»: мок subprocess и HTTP проверяет самое опасное — какие команды
  и запросы уйдут в прод (правильный ли бакет, есть ли `--dry-run`, не потерялся ли таймаут).
- ruff в CI с правилами `S` (bandit) ловит `shell=True`, `yaml.load`, `verify=False`, запросы без таймаута
  ещё на MR — дешевле любого ревью.
- Образ для Python-утилиты — те же правила, что для любого сервиса: slim, non-root, слой зависимостей
  отдельно, никакого `latest` в проде ([10_security_best_practices.md](/docker/10-security-best-practices)).
- На собеседовании «как оформить и доставить свой скрипт» — хороший повод показать весь путь:
  структура → lock → тесты → CI → образ → запуск по расписанию.

---

## 📌 Шпаргалка

| Хочу | Команда / код |
|------|---------------|
| Новый проект | `uv init --package opsctl` |
| Entry point | `[project.scripts] opsctl = "opsctl.cli:main"` |
| Зависимость / dev-зависимость | `uv add requests` / `uv add --dev pytest` |
| Окружение по lock | `uv sync --locked` |
| Запустить в окружении | `uv run opsctl ...` / `uv run pytest` |
| Собрать wheel | `uv build` |
| Поставить как программу | `uv tool install .` / `pipx install .` |
| Линт / автофикс | `ruff check .` / `ruff check --fix .` |
| Формат / проверка формата | `ruff format .` / `ruff format --check .` |
| Временный каталог в тесте | фикстура `tmp_path` |
| Подменить env | `monkeypatch.setenv("X", "1")` / `delenv` |
| Проверить вывод | `capsys.readouterr().out` |
| Мок subprocess | `mock.patch("pkg.mod.subprocess.run", return_value=CompletedProcess(...))` |
| Ошибка из мока | `side_effect=subprocess.CalledProcessError(...)` |
| Мок HTTP | `@responses.activate` + `responses.get(url, json=...)` |
| Ожидаемое исключение | `with pytest.raises(Err, match="..."):` |
| Образ | `python:3.12-slim`, requirements → код, `USER app`, exec-форма ENTRYPOINT |
| CI | `lint` (ruff) → `test` (pytest + junit) → `build` (образ) |

---

## 🧠 Что запомнить

1. Скрипт становится проектом, когда у него есть пользователи, зависимости и тесты: src-layout + pyproject.
2. Логика — в чистых функциях, CLI/subprocess/HTTP — тонкие обёртки; так тестируется почти всё без моков.
3. `[project.scripts]` даёт команду после установки; доставка — `uv tool`/`pipx` или Docker-образ.
4. ruff заменяет flake8+isort+black+bandit-минимум; `ruff format --check` и `ruff check` — в CI.
5. pytest: `tmp_path`, `monkeypatch`, `capsys`, `caplog`, `parametrize` покрывают 90% нужд скриптов.
6. Мокать subprocess и HTTP обязательно — тест не должен звать `pg_dump` и ходить в API.
7. Патчить имя там, где оно ищется.
8. Образ: slim, non-root, зависимости отдельным слоем, `.dockerignore`, exec-форма `ENTRYPOINT`.
9. CI: `uv sync --locked` → ruff → pytest с junit-отчётом → сборка образа на основной ветке.
10. Готовность утилиты: `--help`, dry-run, коды выхода, stderr для логов, секреты из env, lock, CI.

➡️ Дальше: [09_practice_labs.md](/python/09-practice-labs) · Задачи: 08_packaging_quality_tasks.md


---

### Блок A. Теория


**A1.** По каким признакам скрипт пора превращать в проект с pyproject?

<details><summary>Ответ</summary>

Больше одного файла, внешние зависимости, пользователи кроме автора (коллеги, CI, cron на серверах),
нужны тесты и версии.

</details>

**A2.** Что такое src-layout и какую проблему он решает?

<details><summary>Ответ</summary>

Код лежит в `src/&lt;пакет&gt;/` и недоступен для импорта «из текущего каталога»: тесты работают
с установленным пакетом, как у пользователя. Ловит забытые файлы, неправильные импорты и зависимости.

</details>

**A3.** Зачем разделять «логику» и «края» (CLI, subprocess, HTTP)? Как это влияет на тесты?

<details><summary>Ответ</summary>

Логика без I/O тестируется простыми вызовами с данными; края тонкие — их проверяют немногими
тестами с моками. Итог: больше тестов, меньше моков, проще рефакторинг.

</details>

**A4.** Что делает секция `[project.scripts]`? Как после установки появляется команда?

<details><summary>Ответ</summary>

Описывает консольные команды: при установке создаётся исполняемый файл `opsctl`,
который импортирует `opsctl.cli` и вызывает `main()`, передавая её результат в `sys.exit`.

</details>

**A5.** Чем `[project.dependencies]` отличается от `[dependency-groups] dev`?

<details><summary>Ответ</summary>

`dependencies` — нужны для работы утилиты и ставятся пользователю; `dependency-groups.dev` —
только для разработки (pytest, ruff), в продовый образ не попадают.

</details>

**A6.** Что делают `uv sync`, `uv sync --locked`, `uv run`, `uv build`, `uv tool install .`?

<details><summary>Ответ</summary>

`sync` — привести venv в соответствие с pyproject/lock (обновив lock при надобности);
`--locked` — упасть, если lock устарел; `run` — выполнить команду в окружении проекта;
`build` — собрать wheel/sdist; `tool install .` — поставить утилиту в отдельное окружение с командой в `PATH`.

</details>

**A7.** Чем ruff заменяет набор flake8 + isort + black + bandit? Назови пять правил, полезных именно в ops-скриптах.

<details><summary>Ответ</summary>

Один быстрый инструмент: линт (pyflakes/pycodestyle), сортировка импортов, форматирование,
часть правил bandit. Полезно: `S602` (shell=True), `S113` (requests без timeout), `S506` (yaml.load),
`S501` (verify=False), `B006` (mutable default), `E722`/`S110` (голый except, except-pass), `G004`.

</details>

**A8.** Для чего фикстуры `tmp_path`, `monkeypatch`, `capsys`, `caplog`?

<details><summary>Ответ</summary>

`tmp_path` — временный каталог; `monkeypatch` — подмена env и атрибутов с откатом;
`capsys` — перехват stdout/stderr; `caplog` — перехват записей logging.

</details>

**A9.** ⭐ Как замокать `subprocess.run` и что значит «патчить там, где имя ищется»?

<details><summary>Ответ</summary>

`mock.patch("pkg.mod.subprocess.run", return_value=CompletedProcess(...))` или `side_effect=...`.
Патчится имя в том пространстве имён, где код его ищет во время вызова: при `import subprocess` —
атрибут модуля `subprocess`; при `from subprocess import run` — имя `run` в модуле `pkg.mod`.

</details>

**A10.** Как тестировать код, который ходит в HTTP API, без реальной сети?

<details><summary>Ответ</summary>

Библиотеки-перехватчики: `responses` (requests), `respx` или `httpx.MockTransport` (httpx);
регистрируешь ответы по URL и проверяешь отправленные запросы (`responses.calls`).

</details>

**A11.** Как тестировать CLI? Почему удобно, что `main()` принимает `argv` и возвращает код?

<details><summary>Ответ</summary>

Вызывать `main([...])` из теста как функцию: не нужен subprocess, легко проверить код выхода,
вывод (`capsys`) и эффекты (`tmp_path`).

</details>

**A12.** ⭐ Назови пять правил хорошего Dockerfile для Python-утилиты.

<details><summary>Ответ</summary>

Slim-база; зависимости отдельным слоем до копирования кода; `.dockerignore`; non-root `USER`;
exec-форма `ENTRYPOINT`; `PYTHONUNBUFFERED=1`; без кэшей pip; зафиксированные версии.

</details>

**A13.** Когда нужен multi-stage для Python-образа, а когда хватит одного этапа?

<details><summary>Ответ</summary>

Multi-stage — когда для сборки нужны компиляторы/заголовки (C-расширения без wheel) или
build-инструменты, которые не нужны в рантайме. Если все зависимости ставятся готовыми wheel'ами — одного этапа хватает.

</details>

**A14.** Почему `python:3.12-slim` обычно лучше `python:3.12-alpine` для Python?

<details><summary>Ответ</summary>

Большинство wheel'ов рассчитаны на glibc; на musl (alpine) часть пакетов собирается из исходников —
нужны компиляторы, сборка медленная, итоговый размер часто не меньше, плюс редкие отличия в поведении.

</details>

**A15.** Из каких job'ов состоит минимальный CI для Python-утилиты и что каждый проверяет?

<details><summary>Ответ</summary>

`lint` (ruff format --check, ruff check), `test` (pytest с junit-отчётом), `build` (образ/пакет,
обычно только на основной ветке или тегах). Иногда ещё проверка безопасности зависимостей и образа.

</details>

---

### Блок B. «Что выведет / что тут не так»


```text:no-line-numbers
# B1. src/opsctl/backup.py
```text
```text:no-line-numbers
from subprocess import run
```text
```text:no-line-numbers
def dump(db): run(["pg_dump", db], check=True, timeout=60)
```text
```text:no-line-numbers
# tests/test_backup.py
```text
```text:no-line-numbers
with mock.patch("subprocess.run") as m:
```text
```text:no-line-numbers
    backup.dump("app")
```text
```text:no-line-numbers
# B2.
```text
```text:no-line-numbers
[project]
```text
```text:no-line-numbers
name = "opsctl"
```text
```text:no-line-numbers
dependencies = ["requests", "pyyaml", "pytest", "ruff"]
```text
```text:no-line-numbers
# B3.
```text
```text:no-line-numbers
def test_report():
```text
```text:no-line-numbers
    data = requests.get("https://gitlab.example.com/api/v4/projects", timeout=10).json()
```text
```text:no-line-numbers
    assert len(report(data)) > 0
```text
```text:no-line-numbers
# B4.
```text
```text:no-line-numbers
def test_old_files():
```text
```text:no-line-numbers
    assert find_old_files(Path("/var/backups"), "*.gz", days=7) == []
```text
```text:no-line-numbers
# B5.
```text
```text:no-line-numbers
def test_rotation():
```text
```text:no-line-numbers
    assert is_expired("db_2026-09-20.sql.gz", days=7)      # «сегодня» внутри функции — datetime.now()
```text
```text:no-line-numbers
# B6.
```text
```text:no-line-numbers
FROM python:3.12
```text
```text:no-line-numbers
COPY . /app
```text
```text:no-line-numbers
WORKDIR /app
```text
```text:no-line-numbers
RUN pip install -r requirements.txt
```text
```text:no-line-numbers
CMD python -m opsctl
```text
```text:no-line-numbers
# B7.
```text
```text:no-line-numbers
FROM python:3.12-slim
```text
```text:no-line-numbers
RUN pip install -r requirements.txt
```text
```text:no-line-numbers
COPY requirements.txt .
```text
```text:no-line-numbers
B8.  .dockerignore отсутствует, в каталоге: .venv/ (400 МБ), .git/ (120 МБ), tests/, src/
```text
<details><summary>Ответ</summary>

⚠️ В контекст сборки уходят сотни мегабайт, `COPY . .` тащит `.venv` и `.git` в образ. Нужен `.dockerignore`.

</details>

```text:no-line-numbers
# B9.
```text
```text:no-line-numbers
lint:
```text
```text:no-line-numbers
  image: python:3.12-slim
```text
```text:no-line-numbers
  script:
```text
```text:no-line-numbers
    - pip install ruff
```text
```text:no-line-numbers
    - ruff check . || true
```text
```text:no-line-numbers
# B10.
```text
```text:no-line-numbers
test:
```text
```text:no-line-numbers
  image: python:3.12-slim
```text
```text:no-line-numbers
  script:
```text
```text:no-line-numbers
    - pip install pytest requests pyyaml
```text
```text:no-line-numbers
    - pytest
```text
```text:no-line-numbers
# B11.
```text
```text:no-line-numbers
@responses.activate
```text
```text:no-line-numbers
def test_notify():
```text
```text:no-line-numbers
    notify.send_telegram("hi")         # URL Telegram в responses не зарегистрирован
```text
```text:no-line-numbers
# B12.
```text
```text:no-line-numbers
def test_cli(capsys):
```text
```text:no-line-numbers
    main(["report", "--json"])
```text
```text:no-line-numbers
    out = capsys.readouterr().out
```text
```text:no-line-numbers
    assert json.loads(out)["total"] == 3      # в main() логи настроены на stdout
```text
---

### Блок C. Практика


### C1. 🔑 Скрипт → проект
**1.** `uv init --package opsctl`, разложи `cleanup` и `healthcheck` из прошлых тем по модулям `src/opsctl/`.
**2.** `cli.py` с подкомандами, `[project.scripts] opsctl = "opsctl.cli:main"`, `__main__.py`.

<details><summary>Ответ</summary>

Чаще всего у скриптов срабатывают `I001` (импорты), `F401`, `UP` (устаревший синтаксис), `S113`, `E501`.

</details>

**3.** Проверь: `uv run opsctl --help`, `uv run python -m opsctl --help`.

<details><summary>Ответ</summary>

Пример параметризации с мусором:
```python
@pytest.mark.parametrize("line", ["", "garbage", '1.2.3.4 - - [x] "\\x16\\x03" 400 0 "-" "-"'])
def test_parse_line_garbage(line):
    assert parse_line(line) is None
```text
</details>

**4.** `uv build` и установи wheel через `uv tool install dist/*.whl` — команда `opsctl` доступна вне проекта.

<details><summary>Ответ</summary>

```python
def test_cleanup_apply_removes_only_old(tmp_path):
    old, new = tmp_path / "old.gz", tmp_path / "new.gz"
    for f in (old, new):
        f.write_text("x")
    t = time.time() - 30 * 86400
    os.utime(old, (t, t))
    assert main(["cleanup", str(tmp_path), "--days", "14", "--apply"]) == 0
    assert not old.exists()
    assert new.exists()
```text
</details>

### C2. ruff
**1.** Добавь настройки ruff из конспекта, прогони `ruff check --statistics .` по своим скриптам тем 01-07.
**2.** Исправь всё, что нашлось; автоисправимое — `ruff check --fix`.

<details><summary>Ответ</summary>

Чаще всего у скриптов срабатывают `I001` (импорты), `F401`, `UP` (устаревший синтаксис), `S113`, `E501`.

</details>

**3.** `ruff format .` и посмотри diff. Какие правила сработали чаще всего?

<details><summary>Ответ</summary>

Пример параметризации с мусором:
```python
@pytest.mark.parametrize("line", ["", "garbage", '1.2.3.4 - - [x] "\\x16\\x03" 400 0 "-" "-"'])
def test_parse_line_garbage(line):
    assert parse_line(line) is None
```text
</details>

### C3. 🔑 Тесты чистых функций
Напиши `parametrize`-тесты для: `parse_line` (тема 06, включая мусорные строки), `parse_size`,
функции ротации «старше N дней» (тема 02, `now` передаётся параметром). Минимум 12 случаев.

### C4. 🔑 Файловые тесты
Для `cleanup`: создай файлы в `tmp_path`, подделай `mtime` через `os.utime`, проверь, что
dry-run ничего не удаляет, `--apply` удаляет только старые, отказ на несуществующем каталоге даёт код 2.

### C5. 🔑 Мок subprocess
Для `dump_db(db, out)`:
**1.** Проверь, какая команда и с какими `check`/`timeout` уходит в `subprocess.run`.
**2.** `CalledProcessError` превращается в `BackupError` с текстом stderr.

<details><summary>Ответ</summary>

Чаще всего у скриптов срабатывают `I001` (импорты), `F401`, `UP` (устаревший синтаксис), `S113`, `E501`.

</details>

**3.** `FileNotFoundError` (нет `pg_dump`) → понятная ошибка.

<details><summary>Ответ</summary>

Пример параметризации с мусором:
```python
@pytest.mark.parametrize("line", ["", "garbage", '1.2.3.4 - - [x] "\\x16\\x03" 400 0 "-" "-"'])
def test_parse_line_garbage(line):
    assert parse_line(line) is None
```text
</details>

**4.** Переделай модуль на `from subprocess import run` и почини тесты (цель патча).

<details><summary>Ответ</summary>

```python
def test_cleanup_apply_removes_only_old(tmp_path):
    old, new = tmp_path / "old.gz", tmp_path / "new.gz"
    for f in (old, new):
        f.write_text("x")
    t = time.time() - 30 * 86400
    os.utime(old, (t, t))
    assert main(["cleanup", str(tmp_path), "--days", "14", "--apply"]) == 0
    assert not old.exists()
    assert new.exists()
```text
</details>

### C6. Мок HTTP
Для `check(url)` из health-checker'а с `responses`: 200 → ok, 500 → не ok, `ConnectionError`
(`responses.get(url, body=requests.ConnectionError("boom"))`) → не ok с именем ошибки.
Для функции с ретраями — 503, 503, 200 → успех и ровно 3 вызова.

### C7. Вывод и логи
Проверь через `capsys`, что `opsctl report --json` пишет в stdout валидный JSON, а логи — в stderr;
через `caplog` — что на ошибке пишется сообщение уровня ERROR.

### C8. 🔑 Образ
**1.** Dockerfile по базовому шаблону: slim, зависимости отдельным слоем, non-root, exec-форма ENTRYPOINT.
**2.** `.dockerignore`. Сравни размер с образом на `python:3.12` (`docker image ls`).

<details><summary>Ответ</summary>

Чаще всего у скриптов срабатывают `I001` (импорты), `F401`, `UP` (устаревший синтаксис), `S113`, `E501`.

</details>

**3.** Поменяй строку в коде и пересобери — слой `pip install` должен взяться из кэша.

<details><summary>Ответ</summary>

Пример параметризации с мусором:
```python
@pytest.mark.parametrize("line", ["", "garbage", '1.2.3.4 - - [x] "\\x16\\x03" 400 0 "-" "-"'])
def test_parse_line_garbage(line):
    assert parse_line(line) is None
```text
</details>

**4.** `docker run --rm --entrypoint id opsctl:dev` → не root.

<details><summary>Ответ</summary>

```python
def test_cleanup_apply_removes_only_old(tmp_path):
    old, new = tmp_path / "old.gz", tmp_path / "new.gz"
    for f in (old, new):
        f.write_text("x")
    t = time.time() - 30 * 86400
    os.utime(old, (t, t))
    assert main(["cleanup", str(tmp_path), "--days", "14", "--apply"]) == 0
    assert not old.exists()
    assert new.exists()
```text
</details>

**5.** Сделай multi-stage-вариант и сравни размер.

<details><summary>Ответ</summary>

п.3:
```python
def test_dump_without_pg_dump(tmp_path):
    with (mock.patch("opsctl.backup.subprocess.run", side_effect=FileNotFoundError("pg_dump")),
          pytest.raises(backup.BackupError, match="pg_dump")):
        backup.dump_db("app", tmp_path / "x")
```text
(в `dump_db` нужно ловить `FileNotFoundError` и превращать в `BackupError`).

</details>

### C9. 🔑 GitLab CI
**1.** `.gitlab-ci.yml` с job'ами `lint`, `test` (junit-отчёт), `build` (только на основной ветке).
**2.** Сделай MR с неотформатированным кодом — `lint` должен упасть.

<details><summary>Ответ</summary>

Чаще всего у скриптов срабатывают `I001` (импорты), `F401`, `UP` (устаревший синтаксис), `S113`, `E501`.

</details>

**3.** Сделай MR с падающим тестом — убедись, что отчёт виден во вкладке тестов MR.

<details><summary>Ответ</summary>

Пример параметризации с мусором:
```python
@pytest.mark.parametrize("line", ["", "garbage", '1.2.3.4 - - [x] "\\x16\\x03" 400 0 "-" "-"'])
def test_parse_line_garbage(line):
    assert parse_line(line) is None
```text
</details>

**4.** Добавь кэш uv по `uv.lock` и сравни время второго прогона.

<details><summary>Ответ</summary>

```python
def test_cleanup_apply_removes_only_old(tmp_path):
    old, new = tmp_path / "old.gz", tmp_path / "new.gz"
    for f in (old, new):
        f.write_text("x")
    t = time.time() - 30 * 86400
    os.utime(old, (t, t))
    assert main(["cleanup", str(tmp_path), "--days", "14", "--apply"]) == 0
    assert not old.exists()
    assert new.exists()
```text
</details>

### C10. pre-commit
Настрой `pre-commit` с хуками `ruff-check` (`args: [--fix]`) и `ruff-format`
(репозиторий `https://github.com/astral-sh/ruff-pre-commit`, версия через `pre-commit autoupdate`).
Попробуй закоммитить файл с неиспользуемым импортом — что произойдёт?

---

### Блок D. Инциденты


**D1.** Локально `pytest` зелёный, в CI — `ModuleNotFoundError: No module named 'opsctl'`. Три возможные причины.

<details><summary>Ответ</summary>

Пакет не установлен в окружение CI (нет `pip install -e .`/`uv sync`); плоская структура и
локально работало за счёт текущего каталога; в CI тесты запускаются из другого каталога или без `src` в пути.

</details>

**D2.** Тест «с моком» в CI падает с `FileNotFoundError: [Errno 2] No such file or directory: 'pg_dump'`. Что не так с моком?

<details><summary>Ответ</summary>

Патч не туда: например, `mock.patch("subprocess.run")`, а модуль сделал `from subprocess import run`,
или патч в другом модуле, чем тот, где вызывается. Патчить имя в модуле-потребителе.

</details>

**D3.** Тест ротации бэкапов падает раз в месяц — 1-го числа. Почему и как переписать?

<details><summary>Ответ</summary>

Логика берёт `datetime.now()` внутри, а тест строит ожидания от «сегодня минус N дней» с ошибкой
на границе месяца (или дни месяца захардкожены). Передавать `now` параметром и фиксировать его в тесте.

</details>

**D4.** Сборка образа утилиты занимает 6 минут на каждый коммит, даже когда менялся только README. В чём дело?

<details><summary>Ответ</summary>

`COPY . .` стоит до установки зависимостей: любое изменение файла ломает кэш слоя `pip install`.
Сначала `COPY requirements.txt` (или `pyproject.toml` + lock) и установка, потом код; плюс `.dockerignore`.

</details>

**D5.** Образ утилиты весит 1,3 ГБ. Назови четыре вероятные причины.

<details><summary>Ответ</summary>

База `python:3.12` вместо slim; компиляторы оставлены в итоговом образе (нет multi-stage);
в образ скопированы `.git`, `.venv`, тесты; кэш pip не отключён; лишние системные пакеты.

</details>

**D6.** `docker stop` контейнера с утилитой-демоном всегда ждёт 10 секунд. Dockerfile: `ENTRYPOINT python -m opsctl watch`. Что поправить?

<details><summary>Ответ</summary>

Shell-форма: PID 1 — `/bin/sh -c`, он не пересылает SIGTERM Python'у. Exec-форма
`ENTRYPOINT ["python", "-m", "opsctl", "watch"]` и обработчик SIGTERM в коде (или `--init`).

</details>

**D7.** `ruff check` у разработчика зелёный, а в CI красный на том же коммите. Почему?

<details><summary>Ответ</summary>

Разные версии ruff (локально глобальный, в CI — `pip install ruff` последней версии) или разные
настройки (CI не видит `pyproject.toml`, запуск из другого каталога). Фиксировать ruff в dev-зависимостях lock-файла.

</details>

**D8.** Сканер безопасности помечает образ: «контейнер работает от root». Что поменять и что проверить после?

<details><summary>Ответ</summary>

Добавить пользователя (`useradd --uid 10001`) и `USER app`; проверить, что утилита не пишет в каталоги,
доступные только root (кэш, `/app`), что порт > 1024 и что права на примонтированные тома подходят.

</details>

**D9.** После `uv add boto3` у разработчика CI падает на `uv sync --locked`. Что забыто?

<details><summary>Ответ</summary>

Закоммитить обновлённый `uv.lock` (`uv add` его меняет); `--locked` в CI как раз ловит забытый lock.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как оформить Python-утилиту, которой будет пользоваться команда?

<details><summary>Ответ</summary>

src-layout, pyproject с entry point, lock-файл, ruff + pytest, CI (lint/test/build), README, Docker-образ
   или `uv tool`/`pipx`, `--help`, dry-run, коды выхода, логи в stderr.

</details>

**2.** Что такое pyproject.toml и что в нём описывают?

<details><summary>Ответ</summary>

Стандартный файл метаданных проекта: имя, версия, зависимости, entry points, система сборки и настройки
   инструментов (ruff, pytest).

</details>

**3.** Как зафиксировать зависимости и почему это важно для CI?

<details><summary>Ответ</summary>

Lock-файл (`uv.lock` или requirements с `==`), в CI ставить строго из него (`uv sync --locked`) —
   воспроизводимые сборки, «вчера работало» не повторится.

</details>

**4.** Как протестировать скрипт, который вызывает внешние команды?

<details><summary>Ответ</summary>

Логику вынести в функции, внешние команды вызывать через тонкую обёртку и мокать `subprocess.run`
   (`mock.patch` в модуле-потребителе), проверяя аргументы и обработку ошибок.

</details>

**5.** Как протестировать код, работающий с API?

<details><summary>Ответ</summary>

`responses`/`respx`: регистрировать ответы (включая 5xx и сетевые ошибки), проверять запросы и ретраи.

</details>

**6.** Какие линтеры/форматтеры ты используешь для Python?

<details><summary>Ответ</summary>

ruff (линт + формат), по желанию mypy/pyright для типов; всё — в CI и pre-commit.

</details>

**7.** Как написать хороший Dockerfile для Python-приложения?

<details><summary>Ответ</summary>

slim, зависимости до кода, `.dockerignore`, non-root, exec-форма, `PYTHONUNBUFFERED`, multi-stage при компиляции.

</details>

**8.** Как организовать CI для Python-проекта?

<details><summary>Ответ</summary>

Job'ы lint → test → build, зависимости из lock, кэш, junit-отчёт, сборка образа на основной ветке.

</details>

**9.** Как доставить утилиту на серверы?

<details><summary>Ответ</summary>

Docker-образ (запуск из systemd/cron/k8s CronJob), `uv tool install`/`pipx install` wheel'а из registry,
   Ansible-роль с venv.

</details>

**10.** Что такое src-layout?

<details><summary>Ответ</summary>

Размещение пакета в `src/&lt;имя&gt;/`: тесты работают с установленным пакетом, а не с файлами из cwd.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Превращаю скрипт в проект: src-layout, pyproject, entry point, `__main__.py`
- [ ] Управляю зависимостями через uv и lock-файл (или requirements с `==`)
- [ ] Держу код чистым через `ruff check` и `ruff format`
- [ ] Пишу параметризованные тесты для чистых функций
- [ ] Тестирую файловые операции через `tmp_path` и `os.utime`
- [ ] Мокаю subprocess и знаю, куда ставить патч
- [ ] Мокаю HTTP через `responses`, проверяю ретраи
- [ ] Тестирую CLI через `main(argv)`, `capsys`, `caplog`
- [ ] Собираю slim, non-root образ с отдельным слоем зависимостей
- [ ] Настраиваю GitLab CI: lint → test (junit) → build
