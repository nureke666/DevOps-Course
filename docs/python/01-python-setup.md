---
title: "01. Окружение и каркас скрипта"
description: "Блок → Python для DevOps → тема 1 из 8."
---

# 01. Окружение и каркас скрипта

> Блок → **Python для DevOps** → тема 1 из 8.
> Модуль bash закончился разделом «Когда bash пора бросать»
> ([26_bash_devops_practice.md](/linux/26-bash-devops-practice)) — здесь начинается то, что брать вместо.
>
> **После темы ты умеешь:** решать, где писать на bash, а где на Python; ставить библиотеки,
> не ломая системный Python; пользоваться venv, pip, pipx и uv; оформлять скрипт с `main()`
> и честными кодами выхода; запускать его из cron, systemd и контейнера.

---

## 🗺️ Карта темы

```text
                    задача автоматизации
                            │
            ┌───────────────┴────────────────┐
   склеить 2-3 утилиты,               JSON/API, структуры данных,
   до ~100 строк, «запустил и забыл»  ретраи, тесты, SDK, > 100 строк
            │                                │
          bash                            Python
                                             │
        ┌────────────────────┬───────────────┴──────┬─────────────────────┐
  откуда интерпретатор   куда ставить библиотеки   как оформить скрипт   где запускать
  системный python3      venv + requirements/lock  shebang, main(),      руками, cron,
  uv python / образ      pipx / uv tool — для CLI  sys.exit(код)         systemd, docker, CI
```text
---

## 1. Зачем девопсу Python

Python — второй язык девопса после bash. Не потому что он «лучше», а потому что на нём
написана половина инструментов и почти все SDK к инфраструктуре.

| Где встретится | Что там на Python |
|----------------|-------------------|
| Ansible | Сам Ansible, его модули, фильтры Jinja2, динамические инвентори |
| Облака и S3 | `boto3` (AWS и любые S3-совместимые: MinIO, Ceph, Yandex/VK Cloud) |
| Kubernetes | Официальный клиент `kubernetes`, операторы на `kopf`, скрипты-«уборщики» |
| Docker | Пакет `docker` — тот же API, что у CLI, но из кода |
| Мониторинг | `prometheus_client`: свой exporter или метрики из cron-задачи |
| CI/CD | Скрипты релизов, генерация changelog, вызовы API GitLab/Jira/Telegram |
| Логи и отчёты | Разбор access.log, выгрузки в CSV, «сколько 5xx было ночью» |
| Разовые задачи | Миграции данных, массовые правки через API, инвентаризация |

---

## 2. Python или bash

| Критерий | bash | Python |
|----------|------|--------|
| Склеить готовые утилиты (`tar`, `rsync`, `pg_dump`) | ⭐ Идеально | Можно, но многословно |
| Entrypoint контейнера, wait-for, короткие обёртки | ⭐ Стандарт | Избыточно |
| JSON/YAML глубже одного уровня | `jq`/`yq` — терпимо | ⭐ Родные dict/list |
| HTTP API с пагинацией, ретраями, авторизацией | Боль | ⭐ `requests`/`httpx` |
| Структуры данных, группировки, сортировки | Ассоциативные массивы — хрупко | ⭐ dict, Counter, dataclass |
| Обработка ошибок | `set -e` + `trap` — много нюансов | ⭐ Исключения, `try/finally` |
| Тесты | bats — редко кто пишет | ⭐ pytest, моки |
| SDK (AWS, k8s, Docker) | Только через CLI | ⭐ Официальные библиотеки |
| Доступность «из коробки» | Есть везде, включая alpine (`sh`) | Есть почти везде, но версия разная |
| Скорость написания 10 строк | ⭐ Быстрее | Чуть дольше |

**Правило большого пальца:** пока скрипт — это последовательность команд, пиши на bash.
Как только появляются `if` по содержимому JSON, циклы по вложенным структурам, ретраи
и желание написать тест — переходи на Python.

Одна задача двумя способами — «имена упавших пайплайнов»:

```bash
curl -sSf --max-time 10 -H "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  "$GITLAB_URL/api/v4/projects/42/pipelines?status=failed&per_page=20" \
  | jq -r '.[] | "\(.id) \(.ref)"'
```text
```python
import os
import requests

resp = requests.get(
    f"{os.environ['GITLAB_URL']}/api/v4/projects/42/pipelines",
    params={"status": "failed", "per_page": 20},
    headers={"PRIVATE-TOKEN": os.environ["GITLAB_TOKEN"]},
    timeout=10,
)
resp.raise_for_status()
for p in resp.json():
    print(p["id"], p["ref"])
```text
Пока задача такая — bash короче. Когда нужно пройти все страницы, отфильтровать по дате,
сгруппировать по веткам и отправить отчёт в Telegram — Python выигрывает с большим отрывом.

---

## 3. Какой Python: системный, свой, в контейнере

**Системный `python3`** принадлежит ОС: на нём работают `apt`, `cloud-init`, `netplan`,
ansible-модули на хостах. Ломать его нельзя, поэтому современные Debian/Ubuntu
запрещают `pip install` в систему (PEP 668):

```text
$ pip install requests
error: externally-managed-environment
× This environment is externally managed
```text
⚠️ `--break-system-packages` и `sudo pip install` «чинят» ошибку, ломая систему. Не надо.

| Способ получить Python | Когда |
|------------------------|-------|
| Системный `python3` + venv | Скрипт живёт на сервере, версии ОС хватает |
| `uv python install 3.12` | Нужна другая версия без root и без сборки |
| pyenv / deadsnakes PPA | Старый способ получить новую версию на машине разработчика |
| Образ `python:3.12-slim` | Скрипт запускается в контейнере, в CI, в k8s CronJob |

```bash
python3 --version          # какая версия
which -a python3           # какие интерпретаторы есть в PATH
python3 -c 'import sys; print(sys.executable, sys.prefix)'   # какой реально запущен
```text
---

## 4. venv — отдельная коробка для зависимостей

```bash
sudo apt install python3-venv        # на Debian/Ubuntu venv — отдельный пакет
python3 -m venv .venv                # создать окружение в каталоге проекта
source .venv/bin/activate            # «активировать» = поставить .venv/bin первым в PATH
python -m pip install requests       # ставится в .venv, а не в систему
deactivate                           # вернуть PATH как было

.venv/bin/python script.py           # ⭐ без активации — так запускают из cron/systemd
```text
```text
.venv/
├── bin/python  → /usr/bin/python3     (симлинк на базовый интерпретатор)
├── bin/pip, bin/activate
├── lib/python3.12/site-packages/      ← сюда ставятся библиотеки
└── pyvenv.cfg                         ← откуда взят интерпретатор
```text
- Активация — это только правка `PATH` в текущем шелле. Никакой магии.
- venv **нельзя переносить** в другой каталог: пути прописаны внутри. Удали и создай заново.
- `.venv/` — в `.gitignore`. В git живёт список зависимостей, а не окружение.

---

## 5. pip, requirements и фиксация версий

```bash
python -m pip install 'requests>=2.31,&lt;3'   # ⭐ python -m pip — тот pip, что у этого python
python -m pip install -r requirements.txt
python -m pip freeze&gt; requirements.txt     # снимок ВСЕГО окружения с точными версиями
python -m pip list --outdated
python -m pip show requests                 # версия, зависимости, где лежит
```text
| Спецификатор | Смысл |
|--------------|-------|
| `requests==2.32.3` | Ровно эта версия (lock) |
| `requests>=2.31,&lt;3` | Диапазон — для библиотек и «верхнеуровневых» зависимостей |
| `requests~=2.32` | Совместимая: `&gt;=2.32, &lt;3` |
| без версии | Что угодно — «вчера работало» ⚠️ |

Две схемы, которые встречаются на практике:

```text
requirements.in      ← что нужно напрямую:   requests, pyyaml
      │  pip-compile (pip-tools) или  uv pip compile
      ▼
requirements.txt     ← все зависимости с точными версиями (lock)

pyproject.toml       ← зависимости проекта (тема 08)
      │  uv lock
      ▼
uv.lock              ← lock-файл uv
```text
---

## 6. pipx и uv

**pipx** ставит Python-утилиты (не библиотеки!) каждую в свой venv и кладёт команду в `~/.local/bin`:

```bash
pipx install ruff              # линтер как отдельная команда
pipx install --include-deps ansible
pipx run pycowsay moo          # запустить один раз без установки
pipx list
```text
**uv** — быстрый менеджер от Astral, заменяет pip, venv, pip-tools, pipx и pyenv разом:

| Задача | uv |
|--------|----|
| Создать venv | `uv venv` |
| Поставить из requirements | `uv pip install -r requirements.txt` |
| Собрать lock из `.in` | `uv pip compile requirements.in -o requirements.txt` |
| Новый проект | `uv init --package opsctl` |
| Добавить зависимость | `uv add requests` · `uv add --dev pytest` |
| Поставить всё по lock | `uv sync --locked` |
| Запустить в окружении проекта | `uv run pytest` · `uv run opsctl --help` |
| CLI-утилита глобально (как pipx) | `uv tool install ruff` · разово: `uvx ruff check .` |
| Поставить интерпретатор | `uv python install 3.12` |

⭐ **Скрипт одним файлом с зависимостями** (PEP 723) — удобно для утилит, которые не хочется
превращать в проект:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = "&gt;=3.12"
# dependencies = ["requests", "pyyaml"]
# ///
import requests, yaml
print(requests.__version__, yaml.__version__)
```text
```bash
chmod +x check.py && ./check.py     # uv сам создаст окружение и поставит зависимости
```text
---

## 7. ⭐ Каркас скрипта

```python
#!/usr/bin/env python3
"""disk_check — предупреждает, если на разделах мало места.

Пример: ./disk_check.py / /var --threshold 85
"""
import argparse
import logging
import shutil
import sys

log = logging.getLogger("disk_check")

DEFAULT_THRESHOLD = 90


def used_percent(path: str) -> float:
    usage = shutil.disk_usage(path)
    return usage.used / usage.total * 100


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проверка свободного места")
    parser.add_argument("paths", nargs="+", help="точки монтирования")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    exit_code = 0
    for path in args.paths:
        try:
            pct = used_percent(path)
        except OSError as e:
            log.error("%s: не удалось проверить: %s", path, e)
            exit_code = 2
            continue
        if pct >= args.threshold:
            log.warning("%s: занято %.1f%% (порог %d%%)", path, pct, args.threshold)
            exit_code = max(exit_code, 1)
        else:
            log.info("%s: занято %.1f%%", path, pct)
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
```text
| Часть | Зачем |
|-------|-------|
| `#!/usr/bin/env python3` | Берёт `python3` из `PATH` — в активированном venv это python из venv |
| Докстринг | Первое, что прочитает коллега: что делает и как запускать |
| Константы наверху | Пороги и пути не размазаны по коду |
| Логика в функциях | Их можно импортировать и тестировать |
| `main(argv) -> int` | Возвращает код выхода; `argv` можно подать из теста |
| `if __name__ == "__main__"` | Код выполняется только при запуске, а не при `import disk_check` |
| `sys.exit(main())` | Код выхода доходит до шелла, cron, CI |

**Коды выхода** — тот же контракт, что в bash:

| Код | Когда |
|-----|-------|
| `0` | Всё хорошо |
| `1` | Проверка не прошла / общая ошибка (так же завершается необработанное исключение) |
| `2` | Неверные аргументы (так делает `argparse`) или ошибка окружения |
| `130` | Прервано Ctrl+C (128 + SIGINT) |
| `sys.exit("текст")` | Печатает текст в stderr и выходит с кодом 1 |

---

## 8. Где запускать

```bash
# руками
chmod +x disk_check.py && ./disk_check.py / /var

# cron: окружение минимальное — только абсолютные пути и явный python из venv
*/10 * * * * /opt/disk-check/.venv/bin/python /opt/disk-check/disk_check.py / >> /var/log/disk_check.log 2>&1
```text
```ini
# /etc/systemd/system/disk-check.service  (+ disk-check.timer для расписания)
[Service]
Type=oneshot
ExecStart=/opt/disk-check/.venv/bin/python /opt/disk-check/disk_check.py / /var
Environment=PYTHONUNBUFFERED=1
User=monitor
```text
⚠️ **Буферизация stdout.** Когда stdout не терминал (docker, journald, pipe), `print()`
копит вывод блоками, и логи приходят с задержкой или теряются при падении. Лечится
`PYTHONUNBUFFERED=1`, `python -u` или логированием через `logging` (он пишет в stderr,
а stderr построчно буферизуется).

---

## 9. Полезные `python3 -m` на каждый день

```bash
python3 -m http.server 8000 --bind 127.0.0.1   # раздать текущий каталог по HTTP
python3 -m json.tool response.json             # проверить и красиво вывести JSON
python3 -m venv .venv                          # окружение
python3 -m pip ...                             # pip «того самого» интерпретатора
python3 -m tarfile -l backup.tar.gz            # содержимое архива без tar
python3 -m zipfile -l artifact.zip
python3 -m timeit '"-".join(map(str, range(100)))'   # замерить скорость кусочка кода
python3 -c 'import ssl; print(ssl.OPENSSL_VERSION)'
```text
---

## 10. Грабли окружения

| Грабля | Что происходит | Как правильно |
|--------|----------------|---------------|
| `sudo pip install ...` | Ломает пакеты ОС (или ловит PEP 668) | venv / pipx / uv |
| `pip` и `python3` — от разных интерпретаторов | Пакет стоит, а `import` падает | `python -m pip` |
| Скрипт назван `requests.py`, `yaml.py`, `logging.py` | Импортирует сам себя вместо библиотеки | Не называй файлы как модули |
| `.venv` скопирован на другой сервер/каталог | Ломаные шебанги и пути | Пересоздать venv из requirements |
| `.venv` в git | Сотни мегабайт мусора, чужие бинарники | `.gitignore`, в git — lock-файл |
| Нет версий в requirements | Новый релиз библиотеки ломает прод | Lock-файл с точными версиями |
| cron запускает `python3 script.py` | Не тот Python, нет библиотек, другой `PATH` | Абсолютный путь к `.venv/bin/python` |
| Файл с CRLF (правился в Windows) | `env: 'python3\r': No such file or directory` | `dos2unix`, `.gitattributes` |
| `print` в контейнере | Логи с задержкой | `PYTHONUNBUFFERED=1` / `logging` |

---

## 💼 Как это в DevOps

- Типичный путь утилиты: скрипт в git-репозитории `ops-scripts` → venv в `/opt/&lt;tool&gt;`
  или образ `python:3.12-slim` → запуск из systemd-таймера, CI или k8s CronJob.
- На ревью первым делом смотрят: есть ли `main()` и код выхода, зафиксированы ли версии,
  не лезет ли скрипт в системный Python.
- `uv` быстро стал стандартом в новых проектах: одна утилита вместо pip + venv + pip-tools
  + pipx, а lock-файл даёт воспроизводимые сборки в CI.
- Однофайловые скрипты с PEP 723 удобны для runbook'ов: зависимости описаны в самом файле.
- Решение «bash или Python» — частый вопрос на собесе. Ответ через критерии (JSON, ретраи,
  тесты, объём), а не через вкусовщину.

---

## 📌 Шпаргалка

| Хочу | Команда |
|------|---------|
| Какая версия и где | `python3 --version` · `which -a python3` |
| Создать venv | `python3 -m venv .venv` · `uv venv` |
| Войти / выйти | `source .venv/bin/activate` · `deactivate` |
| Запуск без активации | `.venv/bin/python script.py` |
| Поставить пакет | `python -m pip install pkg` · `uv pip install pkg` |
| Поставить из файла | `python -m pip install -r requirements.txt` |
| Снимок версий | `python -m pip freeze > requirements.txt` |
| Lock из `.in` | `uv pip compile requirements.in -o requirements.txt` |
| CLI-утилита изолированно | `pipx install ruff` · `uv tool install ruff` |
| Разово запустить утилиту | `pipx run x` · `uvx x` |
| Другая версия Python | `uv python install 3.12` |
| Скрипт с зависимостями в одном файле | блок `# /// script` + `uv run --script` |
| Каркас | shebang → докстринг → импорты → функции → `main() -> int` → `sys.exit(main())` |
| Логи сразу, без буфера | `PYTHONUNBUFFERED=1` или `python -u` |

---

## 🧠 Что запомнить

1. Bash — склеивать утилиты; Python — когда есть JSON, API, ретраи, структуры данных и тесты.
2. Системный Python принадлежит ОС: никаких `sudo pip install`, только venv/pipx/uv.
3. venv — это каталог с интерпретатором и библиотеками; активация лишь меняет `PATH`.
4. `python -m pip` вместо `pip` — гарантирует, что пакет поставится туда, откуда будет импорт.
5. В git — список зависимостей с точными версиями (requirements/lock), а не `.venv`.
6. Каркас: `main() -> int` и `if __name__ == "__main__": sys.exit(main())`.
7. Коды выхода: 0 — ок, 1 — проблема, 2 — неверный запуск, 130 — Ctrl+C.
8. Из cron и systemd запускают абсолютным путём к `.venv/bin/python`.
9. В контейнерах и journald — `PYTHONUNBUFFERED=1`, иначе логи опаздывают.
10. uv закрывает всё: версии Python, venv, зависимости, lock, CLI-утилиты, однофайловые скрипты.

➡️ Дальше: [02_basics_for_scripts.md](/python/02-basics-for-scripts) · Задачи: 01_python_setup_tasks.md


---

### Блок A. Теория


**A1.** Назови пять мест в DevOps, где ты встретишь Python, и что там на нём написано.

<details><summary>Ответ</summary>

Ansible (сам инструмент и модули), boto3 (облака/S3), клиент kubernetes и операторы,
`prometheus_client` (exporter'ы), скрипты в CI (релизы, уведомления), разбор логов и отчёты.

</details>

**A2.** По каким признакам понять, что скрипт пора переписать с bash на Python? Назови минимум четыре.

<details><summary>Ответ</summary>

Появился разбор JSON/YAML глубже одного уровня; нужны ретраи, пагинация, авторизация
к API; нужны структуры данных (группировки, словари); скрипт перевалил за 100-200 строк;
хочется тестов; нужен SDK (boto3, k8s).

</details>

**A3.** В каких задачах bash остаётся лучшим выбором даже для того, кто хорошо знает Python?

<details><summary>Ответ</summary>

Entrypoint контейнера, wait-for, короткие обёртки над утилитами (`tar`, `rsync`,
`pg_dump`), однострочники в CI, alpine-образы без Python.

</details>

**A4.** Почему нельзя делать `sudo pip install` на сервере? Что такое ошибка `externally-managed-environment`?

<details><summary>Ответ</summary>

Системный Python обслуживает пакеты ОС. `pip` может перезаписать их зависимости
другими версиями — ломаются `apt`-утилиты, cloud-init, netplan. PEP 668 заставляет pip
отказываться ставить пакеты в «управляемое ОС» окружение: ошибка `externally-managed-environment`.

</details>

**A5.** Что физически происходит при `source .venv/bin/activate`?

<details><summary>Ответ</summary>

Скрипт `activate` добавляет `.venv/bin` в начало `PATH`, выставляет `VIRTUAL_ENV`
и меняет приглашение. Больше ничего — поэтому можно не активировать, а звать `.venv/bin/python`.

</details>

**A6.** Почему venv нельзя скопировать в другой каталог или на другой сервер?

<details><summary>Ответ</summary>

Внутри прописаны абсолютные пути: в шебангах `.venv/bin/*`, в `pyvenv.cfg`. Плюс
`bin/python` — симлинк на конкретный базовый интерпретатор, которого на другом сервере может не быть.

</details>

**A7.** Чем `python -m pip install x` лучше, чем `pip install x`?

<details><summary>Ответ</summary>

`python -m pip` гарантирует, что пакет поставится в окружение именно этого интерпретатора.
Голый `pip` может оказаться от другой версии Python или из другого venv.

</details>

**A8.** Чем отличаются `pip freeze > requirements.txt` и схема `requirements.in` → `pip-compile`?

<details><summary>Ответ</summary>

`freeze` снимает всё, что сейчас стоит (включая мусор, поставленный руками),
без разделения на прямые и транзитивные зависимости. Схема `.in` → `pip-compile` хранит
отдельно «что нужно» и «что получилось», lock пересобирается воспроизводимо.

</details>

**A9.** Для чего pipx и чем он отличается от pip? Что из этого умеет uv?

<details><summary>Ответ</summary>

pipx ставит CLI-утилиты (ruff, ansible, httpie) каждую в свой venv и выносит команду
в `PATH`. pip ставит библиотеки в текущее окружение. uv умеет и то и другое:
`uv pip install` и `uv tool install` / `uvx`.

</details>

**A10.** Что такое PEP 723 (блок `# /// script`) и когда он удобен?

<details><summary>Ответ</summary>

Метаданные прямо в файле скрипта: версия Python и зависимости. `uv run` (или pipx)
создаёт для него временное окружение. Удобно для однофайловых утилит и runbook-скриптов.

</details>

**A11.** ⭐ Зачем `if __name__ == "__main__":` и почему `main()` возвращает число?

<details><summary>Ответ</summary>

Код под `if __name__ == "__main__"` выполняется только при запуске файла, но не при
импорте — функции можно импортировать в тесты и другие скрипты. `main()` возвращает код выхода,
который `sys.exit()` передаёт шеллу/cron/CI.

</details>

**A12.** Какие коды выхода ты вернёшь в каких ситуациях? Какой код даёт необработанное исключение?

<details><summary>Ответ</summary>

0 — успех, 1 — проверка не прошла/ошибка, 2 — неверные аргументы или окружение,

</details>

**A13.** Почему в cron и systemd пишут абсолютный путь к `.venv/bin/python`?

<details><summary>Ответ</summary>

У cron и systemd минимальный `PATH` и нет активированного venv: `python3` окажется
системным без нужных библиотек. Абсолютный путь к интерпретатору venv однозначен.

</details>

**A14.** Зачем `PYTHONUNBUFFERED=1` в контейнерах?

<details><summary>Ответ</summary>

Без терминала stdout буферизуется блоками: `print` копится, логи появляются поздно
или теряются при падении. Переменная отключает буферизацию.

</details>

**A15.** Чем `#!/usr/bin/env python3` отличается от `#!/usr/bin/python3`?

<details><summary>Ответ</summary>

`env` ищет `python3` в `PATH` — работает с venv и нестандартными путями.
`/usr/bin/python3` всегда берёт системный Python, игнорируя venv.

</details>

---

### Блок B. «Что выведет / что тут не так»


```text:no-line-numbers
B1.  $ pip install requests && python3 -c 'import requests'
```text
<details><summary>Ответ</summary>

`pip` и `python3` принадлежат разным интерпретаторам (или pip поставил в `--user`
другой версии). Лечение — `python3 -m pip install requests`, а лучше venv.

</details>

```text:no-line-numbers
     ModuleNotFoundError: No module named 'requests'
```text
```text:no-line-numbers
# B2. файл называется yaml.py
```text
```text:no-line-numbers
import yaml
```text
```text:no-line-numbers
print(yaml.safe_load("a: 1"))
```text
```text:no-line-numbers
# B3.
```text
```text:no-line-numbers
import sys
```text
```text:no-line-numbers
def main():
```text
```text:no-line-numbers
    print("готово")
```text
```text:no-line-numbers
    return 3
```text
```text:no-line-numbers
main()
```text
```text:no-line-numbers
# B4.
```text
```text:no-line-numbers
import sys
```text
```text:no-line-numbers
sys.exit("конфиг не найден")          # какой код выхода и куда уйдёт текст?
```text
```text:no-line-numbers
B5.  */5 * * * * python3 ~/scripts/report.py
```text
<details><summary>Ответ</summary>

⚠️ Запустится системный `python3` без библиотек venv, `PATH` у cron урезан, текущий
каталог — `$HOME`, а вывод никуда не сохраняется (в лучшем случае уходит в локальную почту).
Нужны абсолютные пути к venv-python и скрипту и `>> log 2>&1`.

</details>

```text:no-line-numbers
# B6. app.py печатает print() в цикле, а docker logs пустые минутами
```text
```text:no-line-numbers
FROM python:3.12-slim
```text
```text:no-line-numbers
COPY app.py .
```text
```text:no-line-numbers
CMD ["python", "app.py"]
```text
```text:no-line-numbers
B7.  requirements.txt:
```text
<details><summary>Ответ</summary>

⚠️ Версии не зафиксированы — сборка невоспроизводима. Нужен lock с `==` для всех пакетов.

</details>

```text:no-line-numbers
     requests
```text
```text:no-line-numbers
     pyyaml
```text
```text:no-line-numbers
B8.  $ ./deploy.py
```text
<details><summary>Ответ</summary>

Файл с Windows-переводами строк (CRLF): `\r` попал в шебанг. `dos2unix deploy.py`.

</details>

```text:no-line-numbers
     /usr/bin/env: 'python3\r': No such file or directory
```text
```text:no-line-numbers
# B9.
```text
```text:no-line-numbers
def main() -> int:
```text
```text:no-line-numbers
    ...
```text
```text:no-line-numbers
if __name__ == "__main__":
```text
```text:no-line-numbers
    main()                            # скрипт упал на проверке — какой код увидит CI?
```text
```text:no-line-numbers
B10.  $ rsync -a ~/tools/.venv/ server:/opt/tools/.venv/ && ssh server /opt/tools/.venv/bin/python -V
```text
<details><summary>Ответ</summary>

⚠️ venv перенесён — пути и симлинк `bin/python` указывают в никуда или на другой
интерпретатор. Переносят requirements/lock и создают venv на месте.

</details>

```text:no-line-numbers
B11.  $ python3 -m venv .venv
```text
<details><summary>Ответ</summary>

На Debian/Ubuntu нет пакета `python3-venv` (`apt install python3-venv` или `python3.12-venv`).

</details>

```text:no-line-numbers
     The virtual environment was not created successfully because ensurepip is not available.
```text
```text:no-line-numbers
B12.  $ pip install --break-system-packages ansible
```text
<details><summary>Ответ</summary>

⚠️ Ставит пакеты в системный Python в обход PEP 668 — риск сломать ОС. Правильно:
`pipx install --include-deps ansible` или venv.

</details>


---

### Блок C. Практика


### C1. Разведка интерпретаторов
**1.** Выведи все `python3` в `PATH` и их версии.
**2.** Узнай `sys.executable` и `sys.prefix` для системного Python и для venv.

<details><summary>Ответ</summary>

Проверка: `ls .venv/lib/python3.*/site-packages | grep -i requests`,
`.venv/bin/python -c 'import requests, yaml; print("ok")'`.

</details>

**3.** Найди, где лежит `site-packages` системного Python (`python3 -m site`).

<details><summary>Ответ</summary>

В lock попадут транзитивные зависимости `requests`: `urllib3`, `idna`, `certifi`,
`charset-normalizer`. После ограничения `&lt;2.32` версия requests (и, возможно, urllib3) сменится.

</details&gt;

### C2. 🔑 venv руками
**1.** Создай проект `~/labs/py/01`, в нём venv `.venv`.
**2.** Поставь `requests` и `pyyaml`, сними `pip freeze` в `requirements.txt`.

<details><summary>Ответ</summary>

Проверка: `ls .venv/lib/python3.*/site-packages | grep -i requests`,
`.venv/bin/python -c 'import requests, yaml; print("ok")'`.

</details>

**3.** Удали `.venv`, создай заново и восстанови зависимости из файла.

<details><summary>Ответ</summary>

В lock попадут транзитивные зависимости `requests`: `urllib3`, `idna`, `certifi`,
`charset-normalizer`. После ограничения `&lt;2.32` версия requests (и, возможно, urllib3) сменится.

</details&gt;

**4.** Запусти `python -c 'import requests'` без активации — через `.venv/bin/python`.
**5.** Добавь `.gitignore` с `.venv/` и `__pycache__/`.

<details><summary>Ответ</summary>

Импорт без выполнения `main()`:
```bash
python3 -c 'import disk_check; print(disk_check.used_percent("/"))'
```text
</details>

### C3. Lock-файл
**1.** Создай `requirements.in` с `requests` и `pyyaml`.
**2.** Собери `requirements.txt` через `uv pip compile`. Сколько там пакетов и откуда лишние?

<details><summary>Ответ</summary>

Проверка: `ls .venv/lib/python3.*/site-packages | grep -i requests`,
`.venv/bin/python -c 'import requests, yaml; print("ok")'`.

</details>

**3.** Поменяй в `.in` на `requests&lt;2.32` и пересобери. Что изменилось?

<details&gt;<summary>Ответ</summary>

В lock попадут транзитивные зависимости `requests`: `urllib3`, `idna`, `certifi`,
`charset-normalizer`. После ограничения `&lt;2.32` версия requests (и, возможно, urllib3) сменится.

</details&gt;

### C4. pipx / uv tool
**1.** Поставь `ruff` через `uv tool install` (или `pipx install`).
**2.** Убедись, что `ruff` — отдельная команда и не виден в venv проекта.

<details><summary>Ответ</summary>

Проверка: `ls .venv/lib/python3.*/site-packages | grep -i requests`,
`.venv/bin/python -c 'import requests, yaml; print("ok")'`.

</details>

**3.** Запусти разово `uvx pycowsay moo`.

<details><summary>Ответ</summary>

В lock попадут транзитивные зависимости `requests`: `urllib3`, `idna`, `certifi`,
`charset-normalizer`. После ограничения `&lt;2.32` версия requests (и, возможно, urllib3) сменится.

</details&gt;

### C5. 🔑 Каркас скрипта
Напиши `disk_check.py` по каркасу из конспекта:
**1.** Аргументы: список путей и `--threshold`.
**2.** Код выхода 0 — всё ок, 1 — превышен порог, 2 — путь не существует.

<details><summary>Ответ</summary>

Проверка: `ls .venv/lib/python3.*/site-packages | grep -i requests`,
`.venv/bin/python -c 'import requests, yaml; print("ok")'`.

</details>

**3.** Проверь коды: `./disk_check.py /; echo $?`, `./disk_check.py / --threshold 1; echo $?`,
   `./disk_check.py /nope; echo $?`.

<details><summary>Ответ</summary>

В lock попадут транзитивные зависимости `requests`: `urllib3`, `idna`, `certifi`,
`charset-normalizer`. После ограничения `&lt;2.32` версия requests (и, возможно, urllib3) сменится.

</details&gt;

**4.** Импортируй функцию `used_percent` в `python3 -c` и убедись, что `main()` при импорте не выполнился.
### C6. Однофайловый скрипт с зависимостями
Сделай `ip_info.py` с блоком `# /// script`, зависимостью `requests` и выводом ответа
`https://httpbin.org/ip` (или любого доступного JSON-эндпоинта). Запусти через `./ip_info.py`.

### C7. Запуск по расписанию
**1.** Разложи `disk_check.py` в `/opt/disk-check/` со своим venv.
**2.** Сделай systemd-юнит `disk-check.service` (`Type=oneshot`) и таймер раз в 10 минут.

<details><summary>Ответ</summary>

Проверка: `ls .venv/lib/python3.*/site-packages | grep -i requests`,
`.venv/bin/python -c 'import requests, yaml; print("ok")'`.

</details>

**3.** Проверь вывод в `journalctl -u disk-check`.

<details><summary>Ответ</summary>

В lock попадут транзитивные зависимости `requests`: `urllib3`, `idna`, `certifi`,
`charset-normalizer`. После ограничения `&lt;2.32` версия requests (и, возможно, urllib3) сменится.

</details&gt;

**4.** Альтернатива: строка в crontab с абсолютными путями и перенаправлением вывода.
### C8. Буферизация
**1.** Скрипт: `for i in range(5): print(i); time.sleep(1)`.
**2.** Запусти `python3 s.py | cat` и `python3 -u s.py | cat` — сравни, когда появляется вывод.

<details><summary>Ответ</summary>

Проверка: `ls .venv/lib/python3.*/site-packages | grep -i requests`,
`.venv/bin/python -c 'import requests, yaml; print("ok")'`.

</details>

**3.** Повтори с `logging` вместо `print`.

<details><summary>Ответ</summary>

В lock попадут транзитивные зависимости `requests`: `urllib3`, `idna`, `certifi`,
`charset-normalizer`. После ограничения `&lt;2.32` версия requests (и, возможно, urllib3) сменится.

</details&gt;

### C9. Ctrl+C
Добавь в скрипт `time.sleep(60)`, нажми Ctrl+C. Какой код выхода без обработки
`KeyboardInterrupt` и какой с ней? Что печатается в каждом случае?

---

### Блок D. Инциденты


**D1.** Скрипт отлично работает руками, а из cron падает с `ModuleNotFoundError`. Три причины.

<details><summary>Ответ</summary>

Cron запускает системный `python3`, а не venv; другой `PATH`/`HOME`; относительные пути
(скрипт ищет файлы относительно текущего каталога, а cron стартует из `$HOME`).

</details>

**D2.** После `apt upgrade` на сервере venv перестал запускаться: `No such file or directory`
на `.venv/bin/python`. Что случилось и как чинить?

<details><summary>Ответ</summary>

Обновился или удалился базовый интерпретатор, на который указывает симлинк `bin/python`
(например, python3.11 → 3.12). Пересоздать venv и поставить зависимости из lock.

</details>

**D3.** В CI вчера всё проходило, сегодня тот же коммит падает на импорте библиотеки. Что проверить?

<details><summary>Ответ</summary>

Незафиксированные версии: вышел новый релиз библиотеки или её зависимости.
Сравнить `pip freeze` вчерашнего и сегодняшнего job'а, зафиксировать lock, собирать из него.

</details>

**D4.** На сервере кто-то поставил пакет через `sudo pip install --break-system-packages`, и теперь
`apt` ругается/сломался `netplan`. Как разбираться и как не допустить?

<details><summary>Ответ</summary>

Посмотреть `pip list --path /usr/lib/python3/dist-packages` и `/usr/local/lib/python3*/dist-packages`,
удалить поставленное pip'ом (`sudo pip uninstall --break-system-packages ...`), переустановить
пакеты ОС (`apt install --reinstall ...`). Профилактика: запрет в регламенте, pipx/venv, образы.

</details>

**D5.** CI-job «проверка конфигов» всегда зелёный, хотя в логе видна ошибка валидации. Что не так в скрипте?

<details><summary>Ответ</summary>

Скрипт не возвращает ненулевой код: нет `sys.exit(main())`, исключение перехвачено
и только залогировано, или ошибка печатается через `print` без выхода.

</details>

**D6.** В `docker logs` у Python-сервиса пусто, хотя он точно работает и печатает. Почему?

<details><summary>Ответ</summary>

Буферизация stdout без TTY. `PYTHONUNBUFFERED=1`, `python -u` или `logging` в stderr.

</details>

**D7.** Скрипт на Python 3.12 использует `match`/`X | None`, а на сервере системный 3.8 —
всё падает с `SyntaxError`. Варианты решения.

<details><summary>Ответ</summary>

Поставить нужную версию рядом (`uv python install 3.12`, venv на ней), запускать
в контейнере `python:3.12-slim`, либо понизить синтаксис скрипта до 3.8.

</details>

**D8.** На сервере два проекта требуют разные версии `requests`. Как их развести?

<details><summary>Ответ</summary>

У каждого проекта свой venv (или свой контейнер). Глобальных библиотек быть не должно.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Когда ты выберешь bash, а когда Python?

<details><summary>Ответ</summary>

Bash — склеить утилиты, entrypoint, короткие обёртки. Python — JSON/API, ретраи,
   структуры данных, тесты, SDK, скрипт больше ~100-200 строк.

</details>

**2.** Что такое виртуальное окружение и зачем оно?

<details><summary>Ответ</summary>

Изолированный каталог с интерпретатором и библиотеками проекта; зависимости не конфликтуют
   между проектами и не ломают систему.

</details>

**3.** Как зафиксировать зависимости проекта?

<details><summary>Ответ</summary>

Lock-файл с точными версиями: `pip-compile`/`uv pip compile` → `requirements.txt`
   или `uv lock`; в CI ставить строго из него.

</details>

**4.** Чем pip отличается от pipx?

<details><summary>Ответ</summary>

pip ставит библиотеки в текущее окружение; pipx ставит CLI-приложения каждое в свой venv.

</details>

**5.** Что такое uv и чем он удобен?

<details><summary>Ответ</summary>

Быстрый менеджер пакетов, venv, lock-файлов, версий Python и CLI-утилит в одном бинарнике.

</details>

**6.** Зачем `if __name__ == "__main__"`?

<details><summary>Ответ</summary>

Чтобы код запуска не выполнялся при импорте модуля (тесты, переиспользование).

</details>

**7.** Как передать код выхода из Python-скрипта в шелл?

<details><summary>Ответ</summary>

`sys.exit(код)`; `main()` возвращает int, `sys.exit(main())`.

</details>

**8.** Как запустить Python-скрипт по расписанию на сервере?

<details><summary>Ответ</summary>

systemd-таймер (или cron) с абсолютным путём к python из venv; логи — в journald.

</details>

**9.** Почему нельзя ставить пакеты в системный Python?

<details><summary>Ответ</summary>

Пакеты ОС зависят от своих версий библиотек; pip их перезапишет и сломает системные утилиты.

</details>

**10.** Как доставить Python-утилиту на 50 серверов? (варианты)

<details><summary>Ответ</summary>

Ansible (создать venv + `pip install -r` из lock), deb-пакет, контейнерный образ,
    или один бинарник через zipapp/shiv. Проще всего — Docker-образ или Ansible-роль с venv.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Объясняю, когда bash, а когда Python, через критерии, а не «нравится»
- [ ] Не трогаю системный Python: venv / pipx / uv
- [ ] Создаю и пересоздаю venv, запускаю через `.venv/bin/python`
- [ ] Держу зависимости в lock-файле с точными версиями
- [ ] Ставлю CLI-утилиты через `pipx` / `uv tool`
- [ ] Пишу каркас: shebang, докстринг, `main() -> int`, `sys.exit(main())`
- [ ] Возвращаю осмысленные коды выхода 0/1/2/130
- [ ] Запускаю скрипт из systemd-таймера и cron с абсолютными путями
- [ ] Знаю про буферизацию stdout и `PYTHONUNBUFFERED=1`
- [ ] Умею однофайловый скрипт с зависимостями (PEP 723)
