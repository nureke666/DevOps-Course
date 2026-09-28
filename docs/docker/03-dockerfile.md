---
title: "03. Dockerfile: директивы и контекст сборки"
description: "Все директивы Dockerfile, контекст сборки, CMD vs ENTRYPOINT, COPY vs ADD, ENV vs ARG, образцовый Dockerfile"
---

# 03. Dockerfile: все директивы + контекст сборки

> Роадмап → 3. Docker → Теория → Образы → Dockerfile, контекст сборки
> «Главный файл, который описывает сборку образа. Надо уметь написать Dockerfile
> + знать директивы и что они делают.»
> **После темы ты умеешь:** написать Dockerfile с нуля, объяснить каждую директиву,
> и не путаться в `CMD`/`ENTRYPOINT`, `COPY`/`ADD`, `ENV`/`ARG`.

---

## 🗺️ Схема: как происходит сборка

```text:no-line-numbers
   ТЫ: docker build -t myapp:1.0 .
                              │
                              └── «.» = КОНТЕКСТ СБОРКИ (не «текущая папка для докера»,
                                        а набор файлов, который целиком уедет демону)
                              │
   1. CLI архивирует контекст (минус .dockerignore) и шлёт его демону
      → "Sending build context to Docker daemon  148.4MB"   ← если тут много МБ — ты что-то делаешь не так
                              │
   2. Демон читает Dockerfile сверху вниз, на каждую инструкцию:
        ┌──────────────────────────────────────────────┐
        │ есть подходящий кэш? ──да──► взять слой      │
        │           │нет                               │
        │           ▼                                  │
        │ запустить временный контейнер из пред. слоя  │
        │ выполнить инструкцию                         │
        │ зафиксировать результат как НОВЫЙ СЛОЙ       │
        └──────────────────────────────────────────────┘
                              │
   3. Записать конфиг (CMD/ENV/USER/…) и поставить тег myapp:1.0
```

**Важно:** `FROM`, `RUN`, `COPY`, `ADD` создают слои с файлами.
`ENV`, `CMD`, `ENTRYPOINT`, `WORKDIR`, `USER`, `LABEL`, `EXPOSE`, `ARG`, `HEALTHCHECK`
меняют только **метаданные** (слой размером 0B).

---

## 1. Контекст сборки (роадмап: «что учитывается при сборке, какие файлы могут попасть»)

```bash
docker build -t myapp .                 # контекст = текущий каталог
docker build -t myapp ./backend         # контекст = ./backend
docker build -t myapp -f docker/Dockerfile .   # Dockerfile отдельно, контекст — корень
docker build -t myapp https://github.com/user/repo.git#main   # контекст = git-репозиторий
docker build -t myapp - < Dockerfile    # БЕЗ контекста (COPY работать не сможет)
```

Три правила, которые надо понимать:

1. **Весь контекст уезжает демону.** Даже если в Dockerfile нет ни одного `COPY`.
   Каталог с `.git` на 500 МБ и `node_modules` → каждая сборка медленная.
2. **Выйти за пределы контекста нельзя.** `COPY ../secret.key /` — ошибка
   *«forbidden path outside the build context»*. Это защита: сборка должна быть воспроизводимой.
3. **Что попало в контекст — может попасть в образ** (и в его слои навсегда):
   `.env`, `.git`, ключи, дампы БД. Даже если потом `rm` — см. тему 02.

### `.dockerignore` — обязателен в каждом проекте

```text:no-line-numbers
# .dockerignore
.git
.gitignore
.github
.env
.env.*
*.md
node_modules
__pycache__/
*.pyc
.venv
target/
dist/
build/
.idea
.vscode
Dockerfile*
docker-compose*.yml
*.log
*.sqlite
tmp/
```

> ⚠️ `.dockerignore` синтаксически похож на `.gitignore`, но **это разные файлы**.
> Docker не читает `.gitignore`. Нет `.dockerignore` → в образ уезжает всё.

```bash
# Проверить, что реально уходит в контекст
du -sh .
docker build --no-cache --progress=plain -t t . 2>&1 | grep -i "transferring context"
# Что в итоге попало в образ:
docker run --rm myapp ls -la /app
```

---

## 2. Директивы: справочник

### `FROM` — базовый образ

```dockerfile
FROM python:3.12-slim
FROM python:3.12-slim AS builder          # именованная стадия (multi-stage, тема 04)
FROM scratch                              # пустой образ
FROM --platform=linux/amd64 node:22-alpine
FROM python@sha256:abc123...              # пин по дайджесту — максимальная воспроизводимость
```
- Первая инструкция (до неё может быть только `ARG` и комментарии/директивы парсера).
- Тег указывать **обязательно** (не `FROM python` — это `latest` и лотерея).

### `RUN` — выполнить команду при сборке → новый слой

```dockerfile
# shell-форма: выполняется через /bin/sh -c → работают &&, |, $VAR
RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

# exec-форма: без shell, аргументы как есть
RUN ["/bin/bash", "-c", "echo hi"]

# BuildKit: кэш-маунт (кэш пакетов НЕ попадает в слой, но переживает сборки)
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt
# BuildKit: секрет только на время выполнения инструкции
RUN --mount=type=secret,id=npmrc npm ci
```
**Правило:** объединяй связанные команды в один `RUN` через `&&` — меньше слоёв и
мусор удаляется до фиксации слоя.

### `COPY` vs `ADD` ⭐ (вопрос с собеса)

```dockerfile
COPY requirements.txt .                 # файл → в WORKDIR
COPY src/ /app/src/                     # каталог (содержимое!)
COPY --chown=app:app . /app             # сразу нужный владелец
COPY --from=builder /app/bin /usr/local/bin/   # из другой стадии (multi-stage)
COPY --chmod=755 entrypoint.sh /entrypoint.sh

ADD https://example.com/file.tar.gz /tmp/      # умеет URL
ADD archive.tar.gz /opt/                       # ЛОКАЛЬНЫЙ tar АВТОМАТИЧЕСКИ распакуется
ADD --keep-git-dir=true https://github.com/u/r.git /src   # умеет git-репо (BuildKit)
```

| | `COPY` | `ADD` |
|---|---|---|
| Локальные файлы/каталоги | ✅ | ✅ |
| Автораспаковка локального tar | ❌ | ✅ (`.tar`, `.tar.gz`, `.tar.bz2`, `.tar.xz`) |
| Скачивание по URL | ❌ | ✅ (но без распаковки и без проверки) |
| Git-репозиторий | ❌ | ✅ (BuildKit) |
| Предсказуемость | высокая | низкая (магия) |

**Ответ на собесе:** используй **`COPY` всегда**, кроме случая «нужно распаковать локальный
tar-архив прямо в образ» — тогда `ADD`. Скачивать по URL через `ADD` — плохая практика:
слой нельзя докэшировать нормально, нет контроля хэша и нельзя удалить архив в том же слое;
вместо этого `RUN curl -fsSL … && tar xz … && rm …` в одной инструкции.

### `WORKDIR` — рабочий каталог

```dockerfile
WORKDIR /app            # создастся, если нет; действует на RUN/CMD/ENTRYPOINT/COPY/ADD
WORKDIR src             # относительный путь → /app/src
```
> Никогда не пиши `RUN cd /app` — `cd` действует только внутри одного `RUN` и теряется дальше.

### `ENV` vs `ARG` ⭐

```dockerfile
ARG NODE_VERSION=22               # ТОЛЬКО на время сборки
FROM node:${NODE_VERSION}-alpine  # ARG до FROM виден во FROM

ARG APP_VERSION                   # значение придёт из --build-arg
ENV APP_VERSION=${APP_VERSION}    # переносим в рантайм, если нужно
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"
```

| | `ARG` | `ENV` |
|---|---|---|
| Доступна при сборке | ✅ | ✅ |
| Доступна в запущенном контейнере | ❌ | ✅ |
| Переопределяется | `--build-arg K=V` | `-e K=V` / `--env-file` / compose |
| Видна в `docker history` | ✅ | ✅ |

> 🔒 **Ни `ARG`, ни `ENV` не годятся для секретов**: оба видны в `docker history`
> и в `docker inspect`. Секреты при сборке — `RUN --mount=type=secret`;
> в рантайме — переменные окружения из внешнего хранилища/`--env-file`/docker secrets (тема 10).

**ARG до FROM** виден только во `FROM`. Чтобы использовать его дальше, объявляют повторно
внутри стадии:
```dockerfile
ARG VERSION=1.0
FROM alpine:3.20
ARG VERSION           # ← повторное объявление, иначе пусто
RUN echo $VERSION
```

### `EXPOSE` — документация, не публикация ⭐

```dockerfile
EXPOSE 8080
EXPOSE 8080/tcp 9090/udp
```
`EXPOSE` **ничего не открывает наружу**. Это метаданные: подсказка человеку и
входные данные для `docker run -P` (публикует все EXPOSE-порты на случайные порты хоста).
Реальная публикация — `-p 8080:8080` при запуске (тема 08).

### `CMD` vs `ENTRYPOINT` ⭐⭐ (главный вопрос с собеса)

```dockerfile
CMD ["nginx", "-g", "daemon off;"]     # exec-форма ← ПРАВИЛЬНО
CMD nginx -g "daemon off;"             # shell-форма → /bin/sh -c "..." ← сигналы не дойдут

ENTRYPOINT ["python", "app.py"]
ENTRYPOINT ["docker-entrypoint.sh"]
```

**Смысл:**
- `ENTRYPOINT` — **что это за контейнер** (неизменяемая часть команды).
- `CMD` — **аргументы по умолчанию**, которые легко заменить.

| Что в Dockerfile | `docker run img` | `docker run img echo hi` |
|---|---|---|
| `CMD ["nginx"]` | `nginx` | `echo hi` (CMD **заменён**) |
| `ENTRYPOINT ["nginx"]` | `nginx` | `nginx echo hi` (аргументы **добавлены**) |
| `ENTRYPOINT ["ping"]` + `CMD ["localhost"]` | `ping localhost` | `ping hi`… т.е. `ping echo hi` |

```text:no-line-numbers
ИТОГОВАЯ КОМАНДА = ENTRYPOINT + (аргументы из docker run ИЛИ CMD, если аргументов нет)
```

Переопределить сам ENTRYPOINT можно только флагом: `docker run --entrypoint sh -it img`.

**Shell-форма — источник бага «контейнер не останавливается»:**
```dockerfile
CMD python app.py          # PID 1 = /bin/sh, python — его ребёнок.
                           # docker stop шлёт SIGTERM в sh, sh его не пересылает →
                           # через 10 сек SIGKILL, graceful shutdown не отработал
CMD ["python", "app.py"]   # PID 1 = python, сигнал приходит приложению ✅
```

**Типовые сочетания:**
```dockerfile
# 1. Сервис: жёсткая команда
ENTRYPOINT ["/usr/local/bin/myapp"]
CMD ["--config", "/etc/myapp.yml"]      # дефолтные аргументы, заменяемые

# 2. CLI-утилита: контейнер как команда
ENTRYPOINT ["curl"]
CMD ["--help"]
# docker run myimg https://ya.ru  →  curl https://ya.ru

# 3. Скрипт-обёртка (подготовка + exec) — самый частый прод-вариант
ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "app:app", "-b", "0.0.0.0:8000"]
```
```bash
#!/bin/sh
set -e
# миграции, ожидание БД, генерация конфига...
exec "$@"          # ⭐ exec обязателен: заменяет shell приложением → оно станет PID 1
```

### `USER` — от кого работает процесс

```dockerfile
RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app   # Debian/Ubuntu
# RUN addgroup -S app && adduser -S -G app app                          # Alpine
RUN chown -R app:app /app
USER app                     # ← всё, что ниже (RUN/CMD/ENTRYPOINT), идёт от app
```
По умолчанию контейнер работает от **root** — это UID 0 и на хосте тоже (если не включён
user namespace). Непривилегированный пользователь — обязательный пункт best practices (тема 10).
Порты < 1024 непривилегированный процесс занять не сможет — слушай 8080, а не 80.

### Остальные директивы

```dockerfile
LABEL org.opencontainers.image.source="https://github.com/acme/api" \
      org.opencontainers.image.version="1.4.2" \
      maintainer="devops@acme.ru"
# Метаданные. Стандарт OCI-меток — то, что показывают registry и сканеры.

VOLUME ["/var/lib/postgresql/data"]
# Объявляет точку как том: при запуске БЕЗ -v докер создаст анонимный том.
# ⚠️ В своих приложениях лучше НЕ использовать: плодит анонимные тома-призраки,
#    и всё, что запишут СЛЕДУЮЩИЕ слои в этот путь, потеряется. Монтируй через -v/compose.

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1
# Статус контейнера: starting → healthy / unhealthy. Виден в docker ps.
# Используется compose (depends_on: condition: service_healthy) и балансировщиками.
HEALTHCHECK NONE          # отключить унаследованный из базового образа

STOPSIGNAL SIGQUIT        # какой сигнал слать при docker stop (по умолчанию SIGTERM)

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
# Меняет shell для shell-формы RUN. pipefail важен: без него `RUN a | b` не упадёт,
# если упала команда a.

ONBUILD COPY . /app       # сработает в ДОЧЕРНЕМ образе (FROM этот-образ). Редко, легаси.
```

---

## 3. Образцовый Dockerfile (Python)

```dockerfile
# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

FROM base AS builder
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .                     # ← сначала ТОЛЬКО зависимости (кэш! тема 04)
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install -r requirements.txt

FROM base AS runtime
ARG APP_VERSION=dev
LABEL org.opencontainers.image.version="${APP_VERSION}"
ENV PATH="/opt/venv/bin:$PATH" \
    APP_VERSION=${APP_VERSION}

RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . .                    # ← код копируется ПОСЛЕДНИМ

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
ENTRYPOINT ["/opt/venv/bin/gunicorn"]
CMD ["app:app", "-b", "0.0.0.0:8000", "-w", "4"]
```

Почему именно так:
- `requirements.txt` копируется отдельно → слой с зависимостями кэшируется, пока не изменились зависимости;
- venv собирается в builder-стадии, в рантайм приезжает готовым (нет `build-essential` в финале);
- `USER app` — без root;
- `ENTRYPOINT` + `CMD` — можно переопределить параметры gunicorn, не ломая образ;
- exec-форма → корректный `docker stop`.

---

## 4. Частые ошибки

| Ошибка | Чем плохо | Как правильно |
|--------|-----------|---------------|
| `FROM ubuntu` без тега | Невоспроизводимо | `FROM ubuntu:24.04` |
| `COPY . .` в начале | Убивает весь кэш при любой правке кода | Сначала манифест зависимостей |
| Нет `.dockerignore` | Медленно + секреты в образе | Завести сразу |
| `RUN cd /app` | Не действует на следующие инструкции | `WORKDIR /app` |
| `RUN apt-get upgrade` | Невоспроизводимо, раздувает слой | Обновлять базовый образ |
| `CMD python app.py` | PID 1 = sh, ломается `docker stop` | exec-форма |
| Секрет в `ARG`/`ENV` | Виден в `docker history` | `--mount=type=secret`, рантайм-env |
| Контейнер от root | Дыра в безопасности | `USER app` |
| `EXPOSE 80` вместо `-p` | Порт не публикуется | `-p 8080:80` при запуске |
| `ADD https://…` | Магия, нет кэша и хэша | `RUN curl … && … && rm …` |
| Несколько процессов в одном контейнере | Нельзя масштабировать, логи мешаются | Один процесс = один контейнер |

---

## 💼 Как это в DevOps

- Dockerfile — это **код, который ревьюят**. Плохой Dockerfile = медленный CI (десятки минут),
  тяжёлые образы, уязвимости в проде.
- Линтер обязателен: `hadolint Dockerfile` в пайплайне ловит 80% ошибок из таблицы выше.
- `# syntax=docker/dockerfile:1` в первой строке включает свежий фронтенд BuildKit:
  кэш-маунты, секреты, heredoc — без обновления самого докера.
- `LABEL org.opencontainers.image.*` — то, по чему в registry находят, из какого коммита собран образ.

---

## 🧪 Мини-лаба: разбираем директивы руками

```bash
mkdir -p ~/docker-lab/03 && cd ~/docker-lab/03

# 1. CMD vs ENTRYPOINT — четыре образа
printf 'FROM alpine:3.20\nCMD ["echo","from CMD"]\n'                       > Dockerfile.cmd
printf 'FROM alpine:3.20\nENTRYPOINT ["echo","from ENTRYPOINT"]\n'         > Dockerfile.ep
printf 'FROM alpine:3.20\nENTRYPOINT ["echo"]\nCMD ["default-arg"]\n'      > Dockerfile.both
printf 'FROM alpine:3.20\nCMD sleep 300\n'                                 > Dockerfile.shell

for f in cmd ep both shell; do docker build -q -f Dockerfile.$f -t d3:$f . ; done

docker run --rm d3:cmd                 # from CMD
docker run --rm d3:cmd  echo REPLACED  # REPLACED       ← CMD заменён
docker run --rm d3:ep                  # from ENTRYPOINT
docker run --rm d3:ep   EXTRA          # from ENTRYPOINT EXTRA   ← аргумент добавлен
docker run --rm d3:both                # default-arg
docker run --rm d3:both hello          # hello
docker run --rm --entrypoint sh d3:ep -c 'echo overridden'

# 2. Shell-форма ломает docker stop — измерь время
docker run -d --name shellform d3:shell
time docker stop shellform             # ⏱ ~10 секунд (SIGTERM проигнорирован → SIGKILL)
docker inspect shellform --format '{{.State.ExitCode}}'   # 137
docker rm shellform

printf 'FROM alpine:3.20\nCMD ["sleep","300"]\n' > Dockerfile.exec
docker build -q -f Dockerfile.exec -t d3:exec .
docker run -d --name execform d3:exec
time docker stop execform              # ⏱ мгновенно
docker rm execform

# 3. ENV vs ARG
cat > Dockerfile.args <<'EOF'
FROM alpine:3.20
ARG BUILD_ARG=default-arg
ENV RUNTIME_ENV=default-env
RUN echo "во время сборки ARG=$BUILD_ARG ENV=$RUNTIME_ENV"
CMD sh -c 'echo "в рантайме ARG=[$BUILD_ARG] ENV=[$RUNTIME_ENV]"'
EOF
docker build -f Dockerfile.args --build-arg BUILD_ARG=from-cli -t d3:args .
docker run --rm d3:args                          # ARG пустой! ENV — есть
docker run --rm -e RUNTIME_ENV=overridden d3:args
docker history d3:args | grep -i build_arg       # ⚠️ значение ARG видно в истории!

# 4. Контекст сборки
dd if=/dev/zero of=bigfile bs=1M count=100
docker build --no-cache --progress=plain -f Dockerfile.cmd -t d3:ctx . 2>&1 | grep -i context
echo "bigfile" > .dockerignore
docker build --no-cache --progress=plain -f Dockerfile.cmd -t d3:ctx . 2>&1 | grep -i context
# Сравни размеры переданного контекста

# 5. COPY vs ADD
tar czf sample.tar.gz Dockerfile.cmd
cat > Dockerfile.copyadd <<'EOF'
FROM alpine:3.20
COPY sample.tar.gz /copy/
ADD  sample.tar.gz /add/
RUN ls -R /copy /add
EOF
docker build -f Dockerfile.copyadd -t d3:copyadd .   # /copy — архив, /add — распакован

# 6. WORKDIR vs RUN cd
cat > Dockerfile.wd <<'EOF'
FROM alpine:3.20
RUN cd /tmp && pwd
RUN pwd
WORKDIR /app
RUN pwd
EOF
docker build --no-cache --progress=plain -f Dockerfile.wd -t d3:wd . 2>&1 | grep -E "^#.*(/tmp|/app|^/)"

# 7. USER и права
cat > Dockerfile.user <<'EOF'
FROM alpine:3.20
RUN addgroup -S app && adduser -S -G app app
USER app
CMD ["id"]
EOF
docker build -q -f Dockerfile.user -t d3:user .
docker run --rm d3:user                 # uid=100(app)
docker run --rm --user root d3:user     # uid=0(root)  ← флаг перебивает USER

# 8. HEALTHCHECK
cat > Dockerfile.hc <<'EOF'
FROM nginx:alpine
HEALTHCHECK --interval=5s --timeout=2s --retries=2 CMD wget -qO- localhost/ >/dev/null || exit 1
EOF
docker build -q -f Dockerfile.hc -t d3:hc .
docker run -d --name hc d3:hc
sleep 8; docker ps --filter name=hc --format '{{.Status}}'     # (healthy)
docker inspect hc --format '{{json .State.Health}}' | head -c 300
docker rm -f hc

# 9. Уборка
cd ~ && rm -rf ~/docker-lab/03
docker rmi $(docker images "d3" -q) 2>/dev/null
```

---

## 📌 Шпаргалка директив

| Директива | Смысл | Слой |
|-----------|-------|------|
| `FROM img:tag [AS name]` | Базовый образ / начало стадии | ✅ |
| `RUN cmd` | Выполнить при сборке | ✅ |
| `COPY [--from=] [--chown=] src dst` | Копировать из контекста/стадии | ✅ |
| `ADD src dst` | COPY + распаковка tar + URL/git | ✅ |
| `WORKDIR /path` | Рабочий каталог для последующих инструкций | ⬜ |
| `ENV K=V` | Переменная **сборки и рантайма** | ⬜ |
| `ARG K=V` | Переменная **только сборки** (`--build-arg`) | ⬜ |
| `EXPOSE port` | Документация порта (НЕ публикация) | ⬜ |
| `CMD [...]` | Команда/аргументы по умолчанию (заменяется) | ⬜ |
| `ENTRYPOINT [...]` | Неизменяемая часть команды (дополняется) | ⬜ |
| `USER user[:group]` | От кого работать | ⬜ |
| `LABEL k=v` | Метаданные (OCI-метки) | ⬜ |
| `VOLUME ["/path"]` | Объявить точку томом (осторожно) | ⬜ |
| `HEALTHCHECK CMD …` | Проверка живости | ⬜ |
| `STOPSIGNAL SIG` | Сигнал для `docker stop` | ⬜ |
| `SHELL [...]` | Чем выполнять shell-форму RUN | ⬜ |
| `ONBUILD …` | Триггер для дочернего образа | ⬜ |

```bash
docker build -t name:tag .              # собрать
docker build -f path/Dockerfile .       # другой файл Dockerfile
docker build --build-arg K=V .          # передать ARG
docker build --no-cache .               # без кэша
docker build --target builder .         # собрать до конкретной стадии
docker build --progress=plain .         # полный вывод команд (отладка)
hadolint Dockerfile                     # линтер
```

---

## 🧠 Что запомнить

1. **Контекст сборки** целиком уезжает демону. `.dockerignore` обязателен.
   Выйти за пределы контекста (`COPY ../`) нельзя.
2. `FROM/RUN/COPY/ADD` создают слои; остальные директивы — только метаданные.
3. **`COPY` по умолчанию**; `ADD` — только для распаковки локального tar.
4. **`ENTRYPOINT` = что за контейнер, `CMD` = аргументы по умолчанию.**
   Аргументы из `docker run` заменяют `CMD`, но добавляются к `ENTRYPOINT`.
5. Всегда **exec-форма** (`["cmd","arg"]`): иначе PID 1 — это `sh`, и сигналы до приложения не доходят.
6. В скрипте-обёртке последняя строка — `exec "$@"`.
7. `ARG` — только сборка, `ENV` — сборка и рантайм. **Оба видны в `docker history`** → не для секретов.
8. `EXPOSE` ничего не открывает; публикует порт `-p` при запуске.
9. `WORKDIR`, а не `RUN cd`.
10. Один `RUN` на логическую операцию, с очисткой кэшей в той же инструкции.
11. `USER` — непривилегированный, порты ≥ 1024.
12. `HEALTHCHECK` даёт статус healthy/unhealthy, на него опирается compose и оркестраторы.

---

## Задачи

> Лаба: `mkdir -p ~/docker-lab/03 && cd ~/docker-lab/03`
> ⭐ Блок C1 и вопросы про `CMD`/`ENTRYPOINT` и `COPY`/`ADD` — прямо из списка роадмапа по собесам.

---

### Блок A. Теория

**A1.** Что такое контекст сборки? Что произойдёт, если собирать в каталоге с `.git` на 800 МБ?

<details><summary>Ответ</summary>

Контекст — набор файлов, который CLI упаковывает и **целиком передаёт демону** перед
сборкой; из него берутся источники для `COPY`/`ADD`. Каталог с `.git` на 800 МБ будет
пересылаться и хэшироваться при каждой сборке: медленный билд, забитый диск, риск утащить
в образ лишнее. Лечится `.dockerignore`.

</details>

**A2.** Почему `COPY ../config.yml /app/` не работает? Как правильно решить эту задачу?

<details><summary>Ответ</summary>

`COPY` может брать файлы только **изнутри контекста** — это гарантия воспроизводимости
сборки (иначе результат зависел бы от произвольных путей на машине сборщика). Решения:
перенести файл в контекст, собирать с контекстом уровнем выше (`docker build -f app/Dockerfile .`),
либо передавать значение через `--build-arg` / монтировать секрет.

</details>

**A3.** Зачем нужен `.dockerignore` и чем он отличается от `.gitignore`?

<details><summary>Ответ</summary>

Исключает файлы из контекста сборки: быстрее сборка, меньше образ, секреты не уезжают
демону. Docker **не читает** `.gitignore` — это отдельный файл со своим (похожим) синтаксисом;
в нём обычно исключают `.git`, `node_modules`, `.env`, тесты, документацию, сам Dockerfile.

</details>

**A4.** Какие директивы создают слои с файлами, а какие — только метаданные? Перечисли обе группы.

<details><summary>Ответ</summary>

Слои с файлами: `FROM`, `RUN`, `COPY`, `ADD`. Только метаданные (0B):
`ENV`, `ARG`, `CMD`, `ENTRYPOINT`, `WORKDIR`, `USER`, `LABEL`, `EXPOSE`, `VOLUME`,
`HEALTHCHECK`, `STOPSIGNAL`, `SHELL`, `ONBUILD`.

</details>

**A5.** Разница `COPY` и `ADD`. Когда `ADD` оправдан? *(вопрос из роадмапа)*

<details><summary>Ответ</summary>

`COPY` умеет только копировать локальные файлы из контекста — предсказуемо.
`ADD` дополнительно распаковывает **локальные** tar-архивы, умеет URL и git-репозитории.
Оправдан только для распаковки локального tar. URL через `ADD` — плохо: нет проверки хэша,
архив останется в слое, кэш ведёт себя неочевидно; вместо этого `RUN curl … && tar … && rm …`.

</details>

**A6.** Разница `CMD` и `ENTRYPOINT`. Что будет при `docker run img arg` в каждом случае?
*(вопрос из роадмапа)*

<details><summary>Ответ</summary>

`ENTRYPOINT` — неизменяемая часть команды (что это за контейнер), `CMD` — аргументы
по умолчанию. `docker run img arg`: при `CMD` — аргументы **заменяют** CMD целиком;
при `ENTRYPOINT` — **добавляются** к нему. Формула:
`итог = ENTRYPOINT + (args из run, иначе CMD)`. Сам ENTRYPOINT переопределяется только
флагом `--entrypoint`.

</details>

**A7.** Что такое shell-форма и exec-форма? Почему `CMD python app.py` — это баг?

<details><summary>Ответ</summary>

Shell-форма (`CMD python app.py`) оборачивается в `/bin/sh -c "…"`; exec-форма
(`CMD ["python","app.py"]`) запускает процесс напрямую. В shell-форме PID 1 — это `sh`,
он не пересылает SIGTERM ребёнку → `docker stop` ждёт 10 секунд и делает SIGKILL,
graceful shutdown не отрабатывает, код выхода 137. Плюс shell-форма подставляет переменные
окружения — иногда это нужно, тогда явно: `CMD ["sh","-c","exec app --port $PORT"]`.

</details>

**A8.** Зачем в entrypoint-скрипте писать `exec "$@"` в конце?

<details><summary>Ответ</summary>

`exec` **заменяет** процесс shell'а процессом приложения, сохраняя PID 1. Без него
shell остаётся PID 1, а приложение становится его ребёнком — сигналы от `docker stop`
до приложения не дойдут.

</details>

**A9.** Разница `ENV` и `ARG`. Можно ли класть в них пароль? Почему?

<details><summary>Ответ</summary>

`ARG` существует только во время сборки и задаётся `--build-arg`; `ENV` попадает
в конфиг образа и доступен в рантайме, задаётся/переопределяется `-e`. Пароль нельзя ни в том,
ни в другом: оба сохраняются в истории образа (`docker history`, `docker image inspect`)
и достаются любым, кто скачал образ. Для сборки — `RUN --mount=type=secret`,
для рантайма — переменные из секрет-хранилища / `--env-file` / docker secrets.

</details>

**A10.** Как использовать `ARG` до `FROM` и внутри стадии одновременно?

<details><summary>Ответ</summary>

Объявить дважды: `ARG VERSION=1.0` перед `FROM` (виден во `FROM`) и ещё раз
внутри стадии после `FROM` — тогда он получит то же значение и станет доступен в `RUN`.

</details>

**A11.** Что делает `EXPOSE`? Откроется ли порт наружу?

<details><summary>Ответ</summary>

Только документирует порт в метаданных образа и участвует в `docker run -P`
(публикация всех EXPOSE-портов на случайные порты хоста). Само по себе наружу ничего
не открывает — нужен `-p host:container`.

</details>

**A12.** Почему `RUN cd /app` не работает как ожидается?

<details><summary>Ответ</summary>

Каждая инструкция выполняется в **своём** временном контейнере; `cd` меняет каталог
только внутри этого одного `RUN` и не сохраняется в слое (сохраняется ФС, но не рабочий каталог).
Правильно — `WORKDIR`.

</details>

**A13.** Что делает `USER` и почему работать от root в контейнере плохо?
Какое ограничение появится у непривилегированного процесса?

<details><summary>Ответ</summary>

`USER` задаёт UID/GID для последующих `RUN`, `CMD`, `ENTRYPOINT`. Root в контейнере —
это UID 0 и на хосте: при побеге/уязвимости или небрежном bind mount это прямой путь к хосту,
плюс процесс может менять что угодно внутри. Ограничение: непривилегированный процесс
не может слушать порты < 1024 (нужна capability `NET_BIND_SERVICE`) — поэтому в контейнере
слушают 8080, а наружу публикуют 80.

</details>

**A14.** Для чего `HEALTHCHECK` и кто его использует?

<details><summary>Ответ</summary>

Периодическая проверка живости приложения внутри контейнера; статус
`starting/healthy/unhealthy` виден в `docker ps` и `docker inspect`. Используется
docker compose (`depends_on: condition: service_healthy`), Swarm, балансировщиками и мониторингом.
В Kubernetes вместо него — liveness/readiness probes.

</details>

**A15.** Почему директиву `VOLUME` в своих приложениях обычно не используют?

<details><summary>Ответ</summary>

`VOLUME` в Dockerfile принудительно создаёт **анонимный том** при каждом запуске без `-v`:
копятся безымянные тома, которые никто не чистит; данные, записанные в этот путь
**следующими слоями сборки**, теряются; путь нельзя «отменить» в дочернем образе. Монтирование
данных — решение уровня запуска (`-v`, compose), а не образа.

</details>

**A16.** Что делает `SHELL ["/bin/bash", "-o", "pipefail", "-c"]` и зачем `pipefail`?

<details><summary>Ответ</summary>

Меняет интерпретатор для shell-формы `RUN` на bash с `pipefail`. Без `pipefail`
код возврата конвейера — код **последней** команды: `RUN curl … | tar xz` не упадёт, даже если
`curl` вернул 404, и в образ уедет битый результат.

</details>

**A17.** Что даёт строка `# syntax=docker/dockerfile:1` в начале файла?

<details><summary>Ответ</summary>

Подключает указанный фронтенд BuildKit (свежий синтаксис Dockerfile) независимо от версии
докера: `RUN --mount=type=cache/secret/bind`, heredoc-синтаксис, `COPY --link` и т. д.

</details>

**A18.** Почему `RUN apt-get upgrade` в Dockerfile считается плохой практикой?

<details><summary>Ответ</summary>

Результат зависит от даты сборки (невоспроизводимо), обновление системных пакетов
раздувает слой и может сломать совместимость. Правильный путь — обновлять **базовый образ**
(его тег) и регулярно пересобирать.

</details>

---

### Блок B. «Что делает команда / что произойдёт»

```bash
B1.  docker build -t app:1.0 .
B2.  docker build -f docker/Dockerfile -t app:1.0 .
B3.  docker build --build-arg VERSION=2.1 -t app:2.1 .
B4.  docker build --target builder -t app:build .
B5.  docker build --no-cache --progress=plain .
B6.  docker build -t app - < Dockerfile
B7.  docker run --rm --entrypoint sh app:1.0 -c 'ls /'
B8.  docker run --rm --user 1000:1000 app:1.0 id
B9.  docker inspect app:1.0 --format '{{.Config.Entrypoint}} {{.Config.Cmd}}'
B10. docker history app:1.0 | grep -i arg
B11. hadolint Dockerfile
B12. docker build --platform linux/amd64 -t app:1.0 .
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Собрать образ app:1.0 из ./Dockerfile, контекст — текущий каталог.
B2.  Тот же контекст (.), но файл Dockerfile берётся из docker/.
B3.  Передать ARG VERSION=2.1 внутрь сборки.
B4.  Собрать только до стадии builder (multi-stage, удобно для отладки и запуска тестов).
B5.  Полная пересборка без кэша с подробным выводом каждой команды.
B6.  Сборка БЕЗ КОНТЕКСТА (Dockerfile из stdin): COPY из контекста работать не будет.
B7.  Запустить контейнер, подменив ENTRYPOINT на sh — способ залезть внутрь образа,
     который сразу что-то выполняет и выходит.
B8.  Запуск от UID/GID 1000 независимо от USER в образе.
B9.  Показать, что именно записано в конфиге как Entrypoint и Cmd — первое, что смотрят
     при разборе чужого образа.
B10. Найти в истории образа значения build-аргументов (так и находят утёкшие секреты).
B11. Линтер Dockerfile: пины версий, --no-install-recommends, USER, exec-форма и т. д.
B12. Сборка под конкретную платформу (полезно на Apple Silicon для amd64-серверов).
```

</details>

**B13.** Дан Dockerfile:
```dockerfile
FROM alpine:3.20
ENTRYPOINT ["echo", "hello"]
CMD ["world"]
```
Что выведут:
`docker run img` · `docker run img docker` · `docker run --entrypoint ls img -la`?

<details><summary>Ответ</summary>

`docker run img` → `hello world`; `docker run img docker` → `hello docker`
(аргумент заменил CMD, но добавился к ENTRYPOINT); `docker run --entrypoint ls img -la` →
листинг корня (ENTRYPOINT заменён, `-la` пришло как аргумент, CMD отброшен).

</details>

**B14.** Что выведет `docker run --rm img` для
```dockerfile
FROM alpine
ARG GREET=hi
CMD ["sh","-c","echo [$GREET]"]
```
и почему?

<details><summary>Ответ</summary>

Выведет `[]` — пусто. `ARG` существует только во время сборки; в рантайме
переменной `GREET` нет. Чтобы было видно — `ENV GREET=${GREET}`.

</details>

---

### Блок C. Практика

#### C1. 🔑 Написать Dockerfile с нуля (главное задание)

Есть простое приложение (возьми своё из Linux-практики или создай):

```python
# app.py
from http.server import HTTPServer, BaseHTTPRequestHandler
import os, signal, sys, json

VERSION = os.getenv("APP_VERSION", "dev")

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
        self.wfile.write(json.dumps({"version": VERSION, "host": os.uname().nodename}).encode())
    def log_message(self, *a): print("REQ", self.path, flush=True)

def bye(signum, frame):
    print("graceful shutdown", flush=True); sys.exit(0)

signal.signal(signal.SIGTERM, bye)
HTTPServer(("0.0.0.0", 8000), H).serve_forever()
```

Напиши Dockerfile, удовлетворяющий требованиям:

- базовый образ с явным тегом, не `latest`;
- версия приложения приходит через `--build-arg APP_VERSION=…` и доступна **в рантайме**;
- есть `.dockerignore`, контекст сборки < 100 КБ;
- рабочий каталог `/app`;
- процесс работает от непривилегированного пользователя `app`;
- порт 8000 задокументирован;
- `HEALTHCHECK` дёргает `/health` каждые 10 секунд;
- `ENTRYPOINT` + `CMD` так, чтобы можно было переопределить порт аргументом;
- вывод приложения не буферизуется (логи видны сразу в `docker logs`);
- `docker stop` укладывается в 1 секунду и в логах видно `graceful shutdown`;
- проставлены OCI-метки `source` и `version`.

**Критерии приёмки:**
1. `docker build --build-arg APP_VERSION=1.2.3 -t myapp:1.2.3 .` проходит.
2. `curl localhost:8080/` возвращает `{"version":"1.2.3", ...}`.
3. `docker exec myapp id` → не root.
4. `docker ps` показывает `(healthy)`.
5. `time docker stop myapp` < 2 сек, в `docker logs` есть `graceful shutdown`,
   код выхода 0 (не 137).
6. `docker history` не содержит секретов, контекст сборки маленький.

<details><summary>Ответ (эталонное решение)</summary>

```bash
mkdir -p ~/docker-lab/03 && cd ~/docker-lab/03
# (app.py — из условия задачи)

cat > .dockerignore <<'EOF'
.git
.gitignore
.env
*.md
__pycache__/
*.pyc
.venv
Dockerfile*
docker-compose*.yml
EOF

cat > Dockerfile <<'EOF'
# syntax=docker/dockerfile:1
FROM python:3.12-slim

ARG APP_VERSION=dev
LABEL org.opencontainers.image.source="https://github.com/me/myapp" \
      org.opencontainers.image.version="${APP_VERSION}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_VERSION=${APP_VERSION}

RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app
WORKDIR /app
COPY --chown=app:app app.py .

USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

ENTRYPOINT ["python"]
CMD ["app.py"]
EOF

docker build --build-arg APP_VERSION=1.2.3 -t myapp:1.2.3 .
docker run -d --name myapp -p 8080:8000 myapp:1.2.3

curl -s localhost:8080/ ; echo                 # {"version":"1.2.3",...}
docker exec myapp id                           # uid=999(app) — не root
sleep 12; docker ps --filter name=myapp --format '{{.Status}}'   # (healthy)
time docker stop myapp                         # < 2 сек
docker logs myapp | tail -2                    # graceful shutdown
docker inspect myapp --format '{{.State.ExitCode}}'              # 0
docker history myapp:1.2.3 | head
docker rm myapp
```

</details>

#### C2. CMD vs ENTRYPOINT — таблица истинности

Собери 4 образа и **заранее запиши в тетрадь ожидаемый вывод**, потом проверь:

| Dockerfile | `docker run img` | `docker run img echo BYE` |
|---|---|---|
| `CMD ["echo","A"]` | ? | ? |
| `ENTRYPOINT ["echo","B"]` | ? | ? |
| `ENTRYPOINT ["echo"]` + `CMD ["C"]` | ? | ? |
| `ENTRYPOINT echo D` (shell-форма) | ? | ? |

<details><summary>Ответ</summary>

```bash
printf 'FROM alpine:3.20\nCMD ["echo","A"]\n'                   > D1
printf 'FROM alpine:3.20\nENTRYPOINT ["echo","B"]\n'            > D2
printf 'FROM alpine:3.20\nENTRYPOINT ["echo"]\nCMD ["C"]\n'     > D3
printf 'FROM alpine:3.20\nENTRYPOINT echo D\n'                  > D4
for i in 1 2 3 4; do docker build -q -f D$i -t t:$i . ; done
for i in 1 2 3 4; do
  echo "--- t:$i"; docker run --rm t:$i; docker run --rm t:$i echo BYE
done
```

| Dockerfile | `docker run img` | `docker run img echo BYE` |
|---|---|---|
| `CMD ["echo","A"]` | `A` | `BYE` (CMD заменён) |
| `ENTRYPOINT ["echo","B"]` | `B` | `B echo BYE` |
| `ENTRYPOINT ["echo"]`+`CMD ["C"]` | `C` | `echo BYE` |
| `ENTRYPOINT echo D` (shell) | `D` | `D` — ⚠️ аргументы **игнорируются**: команда стала `/bin/sh -c "echo D"`, а `echo BYE` попало в `$0` |

</details>

#### C3. Сигналы и PID 1

1. Собери образ с `CMD sleep 300` (shell-форма) и с `CMD ["sleep","300"]` (exec).
2. Для каждого: замерь `time docker stop`, посмотри код выхода и `docker exec ps`.
3. Напиши entrypoint-скрипт **без** `exec "$@"` и **с** ним, покажи разницу в PID 1 и в реакции
   на `docker stop`.
4. Как получить корректную обработку сигналов, если запускать надо именно через shell?
   (Подсказка: `--init` или `tini`.)

<details><summary>Ответ</summary>

```bash
printf 'FROM alpine:3.20\nCMD sleep 300\n'        > Ds
printf 'FROM alpine:3.20\nCMD ["sleep","300"]\n'  > De
docker build -q -f Ds -t sig:shell . ; docker build -q -f De -t sig:exec .

docker run -d --name s sig:shell; docker exec s ps -o pid,args   # PID 1 = /bin/sh
time docker stop s                                               # ~10s
docker inspect s --format '{{.State.ExitCode}}'                  # 137
docker rm s

docker run -d --name e sig:exec; docker exec e ps -o pid,args    # PID 1 = sleep
time docker stop e                                               # мгновенно
docker rm e

cat > entry-bad.sh <<'EOF'
#!/bin/sh
echo "prepare..."
"$@"          # БЕЗ exec: sh остаётся PID 1
EOF
cat > entry-good.sh <<'EOF'
#!/bin/sh
echo "prepare..."
exec "$@"     # ← правильно
EOF
chmod +x entry-*.sh
printf 'FROM alpine:3.20\nCOPY entry-bad.sh /e.sh\nENTRYPOINT ["/e.sh"]\nCMD ["sleep","300"]\n'  > Db
printf 'FROM alpine:3.20\nCOPY entry-good.sh /e.sh\nENTRYPOINT ["/e.sh"]\nCMD ["sleep","300"]\n' > Dg
docker build -q -f Db -t ent:bad . ; docker build -q -f Dg -t ent:good .
docker run -d --name eb ent:bad ; docker exec eb ps -o pid,args ; time docker stop eb
docker run -d --name eg ent:good; docker exec eg ps -o pid,args ; time docker stop eg
docker rm eb eg
# 4) Если нужен именно shell — добавить init-процесс:
docker run -d --init --name ei ent:bad; docker exec ei ps -o pid,args  # PID 1 = docker-init (tini)
time docker stop ei; docker rm ei
```

</details>

#### C4. Контекст сборки и секреты

1. Положи в каталог файл `.env` с «паролем» и 50-мегабайтный файл.
2. Собери образ с `COPY . /app` без `.dockerignore`. Найди `.env` внутри образа.
3. Покажи размер переданного контекста.
4. Добавь `.dockerignore`, пересобери, сравни контекст и содержимое `/app`.
5. Докажи, что даже `RUN rm /app/.env` **не** удаляет секрет из образа
   (подсказка: `docker save` + поиск по слоям).

<details><summary>Ответ</summary>

```bash
echo "DB_PASSWORD=SuperSecret123" > .env
dd if=/dev/zero of=bigfile bs=1M count=50
printf 'FROM alpine:3.20\nCOPY . /app\n' > Dctx
rm -f .dockerignore
docker build --no-cache --progress=plain -f Dctx -t ctx:bad . 2>&1 | grep -i "transferring context"
docker run --rm ctx:bad cat /app/.env          # секрет внутри образа!
printf '.env\nbigfile\n' > .dockerignore
docker build --no-cache --progress=plain -f Dctx -t ctx:good . 2>&1 | grep -i "transferring context"
docker run --rm ctx:good ls -a /app            # .env отсутствует

# доказательство, что rm не помогает:
printf 'FROM alpine:3.20\nCOPY .env /app/.env\nRUN rm /app/.env\n' > Drm
rm -f .dockerignore && docker build --no-cache -f Drm -t ctx:rm .
docker run --rm ctx:rm ls -a /app              # файла нет...
docker save ctx:rm -o /tmp/img.tar && mkdir -p /tmp/x && tar xf /tmp/img.tar -C /tmp/x
grep -r "SuperSecret" /tmp/x 2>/dev/null | head -1   # ...а в слое он есть!
rm -rf /tmp/x /tmp/img.tar
```

</details>

#### C5. ARG и ENV

1. Сделай Dockerfile с `ARG` до `FROM` (версия базового образа) и `ARG` внутри стадии.
2. Покажи, что `ARG` до `FROM` не виден внутри стадии без повторного объявления.
3. Передай «секрет» через `--build-arg` и найди его в `docker history` — докажи, что так нельзя.
4. Сделай то же правильно через `RUN --mount=type=secret`.

<details><summary>Ответ</summary>

```bash
cat > Darg <<'EOF'
ARG PY=3.12
FROM python:${PY}-slim
RUN echo "внутри стадии PY=[$PY]"        # ПУСТО — нужно повторное объявление
ARG PY
RUN echo "после повторного ARG PY=[$PY]"
ARG SECRET
RUN echo "secret=$SECRET"
EOF
docker build --no-cache --progress=plain -f Darg --build-arg SECRET=hunter2 -t argdemo . 2>&1 | grep -E "PY=|secret="
docker history --no-trunc argdemo | grep -i hunter2     # ⚠️ секрет в истории

# правильно (BuildKit):
cat > Dsec <<'EOF'
# syntax=docker/dockerfile:1
FROM alpine:3.20
RUN --mount=type=secret,id=mysecret \
    sh -c 'echo "длина секрета: $(wc -c < /run/secrets/mysecret)"'
EOF
echo -n "hunter2" > secret.txt
docker build -f Dsec --secret id=mysecret,src=secret.txt --no-cache --progress=plain -t secdemo . 2>&1 | grep длина
docker history --no-trunc secdemo | grep -i hunter2     # пусто ✅
rm -f secret.txt
```

</details>

#### C6. COPY vs ADD

1. Положи рядом `archive.tar.gz`.
2. Сделай образ, где `COPY` кладёт архив, а `ADD` — распаковывает. Покажи разницу.
3. Скачай файл по URL двумя способами: через `ADD` и через `RUN curl … && rm …`.
   Сравни размеры образов и объясни разницу.

<details><summary>Ответ</summary>

```bash
tar czf archive.tar.gz app.py
printf 'FROM alpine:3.20\nCOPY archive.tar.gz /copy/\nADD archive.tar.gz /add/\nRUN ls -R /copy /add\n' > Dca
docker build --no-cache --progress=plain -f Dca -t ca . 2>&1 | grep -A6 "ls -R"
# /copy/archive.tar.gz  (архив как есть) | /add/app.py (распакован)

printf 'FROM alpine:3.20\nADD https://raw.githubusercontent.com/docker-library/hello-world/master/README.md /tmp/\n' > Dadd
printf 'FROM alpine:3.20\nRUN apk add --no-cache curl && curl -fsSL https://raw.githubusercontent.com/docker-library/hello-world/master/README.md -o /tmp/r.md && apk del curl\n' > Drun
# ADD не требует curl в образе, но и не даёт удалить источник/проверить хэш;
# RUN-вариант позволяет проверить контрольную сумму и убрать за собой в том же слое.
```

</details>

#### C7. Линтер

Прогони `hadolint` по своему Dockerfile из C1, исправь все предупреждения
(или обоснуй игнор через `# hadolint ignore=DL3008`).

```bash
docker run --rm -i hadolint/hadolint < Dockerfile
```

---

### Блок D. Инциденты

**D1.** `docker stop myapp` всегда занимает ровно 10 секунд, приложение не успевает
закрыть соединения с БД. Три возможные причины и как чинить.

<details><summary>Ответ</summary>

(1) `CMD`/`ENTRYPOINT` в shell-форме → PID 1 это `sh`, сигнал не доходит;
(2) приложение не обрабатывает SIGTERM (нет обработчика) — типично для Node/Python без
явного хендлера; (3) приложение запускается через обёртку без `exec "$@"`, или PID 1 —
это `npm`/`yarn`/`bash`, которые не пересылают сигналы. Лечение: exec-форма, `exec "$@"`,
обработчик SIGTERM в коде, `--init`/tini, при необходимости `STOPSIGNAL` и
`docker stop -t 30` (`stop_grace_period` в compose).

</details>

**D2.** CI-сборка приложения занимает 12 минут, хотя менялся только один `.py` файл.
Смотришь Dockerfile: `COPY . /app` стоит второй строкой. Объясни и почини.

<details><summary>Ответ</summary>

`COPY . /app` вторым слоем инвалидирует кэш всех последующих слоёв при **любом**
изменении любого файла → зависимости переустанавливаются каждый раз. Чинится порядком:
сначала `COPY requirements.txt` / `package*.json`, потом установка зависимостей, и **только
потом** `COPY . .`. Плюс `.dockerignore` и кэш-маунты (тема 04).

</details>

**D3.** `docker build` падает с `COPY failed: file not found in build context`,
хотя файл точно лежит рядом. Три причины.

<details><summary>Ответ</summary>

(1) Файл исключён в `.dockerignore`; (2) путь указан относительно Dockerfile, а не
контекста (или контекст задан другим каталогом: `docker build -f app/Dockerfile .`);
(3) файл вне контекста (`../file`) либо это симлинк наружу; реже — опечатка в регистре имени
или файл создаётся только локально (в `.gitignore` и не попал в CI-чекаут).

</details>

**D4.** В образ попал файл `id_rsa`. Разработчик добавил `RUN rm /root/.ssh/id_rsa`
и говорит, что проблема решена. Прав ли он? Что делать на самом деле?

<details><summary>Ответ</summary>

Не прав. `rm` создаёт новый слой с whiteout-меткой, а сам ключ остаётся в нижнем слое
и извлекается через `docker save` + распаковку (см. C4). Правильно: считать ключ
**скомпрометированным и отозвать/перевыпустить**, убрать его из контекста (`.dockerignore`),
пересобрать образ с нуля, использовать `RUN --mount=type=secret` или multi-stage, удалить
старый образ из registry.

</details>

**D5.** Приложение в контейнере не пишет логи в `docker logs`, хотя в консоли локально всё видно.
Причина и решение (для Python и вообще).

<details><summary>Ответ</summary>

Вывод буферизуется, потому что stdout не в tty. Для Python — `ENV PYTHONUNBUFFERED=1`
(или `python -u`). В общем случае: писать логи в stdout/stderr, а не в файл; отключить
буферизацию в рантайме (`stdbuf -oL`, настройки логгера); убедиться, что приложение не пишет
в файл внутри контейнера. Проверка: `docker logs -f`, <code v-pre>docker inspect --format '{{.LogPath}}'</code>.

</details>

**D6.** Контейнер запускается, но приложение отвечает `Permission denied` при записи
в `/app/uploads`. При этом локально всё работает. Что произошло после добавления `USER app`?

<details><summary>Ответ</summary>

`/app/uploads` принадлежит root (создан на этапе сборки до `USER`) или это
смонтированный с хоста каталог с чужим владельцем. Решения: `RUN mkdir -p /app/uploads &&
chown -R app:app /app` **до** `USER app`, копировать с `COPY --chown=app:app`,
для bind mount — согласовать UID (`--user $(id -u):$(id -g)`) или использовать named volume
(докер инициализирует его правами из образа).

</details>

**D7.** `EXPOSE 8080` прописан, но `curl localhost:8080` с хоста не отвечает.
Контейнер работает. Объясни.

<details><summary>Ответ</summary>

`EXPOSE` ничего не публикует. Нужен `docker run -p 8080:8080`. Дополнительно проверить,
что приложение слушает `0.0.0.0`, а не `127.0.0.1` внутри контейнера (иначе снаружи не достучаться
даже с `-p`) — `docker exec c ss -tlnp`.

</details>

**D8.** После добавления `HEALTHCHECK` контейнер вечно в статусе `starting`, потом `unhealthy`,
хотя приложение отвечает. Что проверить? (Три варианта.)

<details><summary>Ответ</summary>

(1) В образе нет команды из healthcheck (`curl`/`wget` отсутствуют в slim/alpine) —
проверить <code v-pre>docker inspect --format '{{json .State.Health}}'</code>, там будет вывод и код;
(2) проверка ходит на неправильный адрес: внутри контейнера нужно `localhost:<внутренний порт>`,
а не порт хоста; (3) слишком маленький `--start-period`/`--timeout` — приложение не успевает
подняться; (4) healthcheck запускается от `USER` без прав.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Какие основные директивы Dockerfile ты знаешь и что они делают?

<details><summary>Ответ</summary>

`FROM` (база), `RUN` (команда при сборке), `COPY`/`ADD` (файлы), `WORKDIR` (каталог),
`ENV`/`ARG` (переменные рантайма/сборки), `EXPOSE` (документация порта),
`CMD`/`ENTRYPOINT` (что запускать), `USER` (от кого), плюс `LABEL`, `HEALTHCHECK`,
`VOLUME`, `STOPSIGNAL`, `SHELL`.

</details>

**2.** Разница `CMD` и `ENTRYPOINT`? *(роадмап)*

<details><summary>Ответ</summary>

См. A6.

</details>

**3.** Разница `COPY` и `ADD`? *(роадмап)*

<details><summary>Ответ</summary>

См. A5.

</details>

**4.** Разница `ENV` и `ARG`?

<details><summary>Ответ</summary>

См. A9.

</details>

**5.** Что такое контекст сборки и зачем `.dockerignore`?

<details><summary>Ответ</summary>

См. A1 и A3.

</details>

**6.** Что делает `EXPOSE`?

<details><summary>Ответ</summary>

См. A11.

</details>

**7.** Почему важна exec-форма команд?

<details><summary>Ответ</summary>

См. A7: PID 1, доставка сигналов, корректный graceful shutdown.

</details>

**8.** Как передать секрет в сборку?

<details><summary>Ответ</summary>

BuildKit: `RUN --mount=type=secret,id=x` + `docker build --secret id=x,src=file`;
либо multi-stage, где секрет используется только в промежуточной стадии; никогда —
`ARG`/`ENV`/`COPY` секрета в финальный образ.

</details>

**9.** Зачем `USER` и как создать непривилегированного пользователя?

<details><summary>Ответ</summary>

`USER` переключает пользователя для последующих инструкций и рантайма.
`RUN groupadd -r app && useradd -r -g app app` (Debian) или
`RUN addgroup -S app && adduser -S -G app app` (Alpine), затем `chown` нужных каталогов и `USER app`.

</details>

**10.** Что такое HEALTHCHECK?

<details><summary>Ответ</summary>

Встроенная проверка живости приложения; статус healthy/unhealthy в `docker ps`,
используется compose'ом (`depends_on: service_healthy`) и оркестраторами.

</details>

---

### 🎯 Чек-лист

- [ ] Написал Dockerfile с нуля без подглядывания в чужие примеры
- [ ] Объясняю `CMD` vs `ENTRYPOINT` через формулу и таблицу
- [ ] Всегда пишу exec-форму и `exec "$@"` в entrypoint-скриптах
- [ ] Знаю, почему `ADD` не нужен в 95% случаев
- [ ] Не кладу секреты в `ARG`/`ENV`, умею `--mount=type=secret`
- [ ] В каждом проекте есть `.dockerignore`
- [ ] Контейнер запускается не от root
- [ ] Умею добавить рабочий `HEALTHCHECK` и отладить его
- [ ] Проверяю Dockerfile линтером hadolint
