---
title: "04. Кэш сборки, multi-stage и best practices"
description: "Как работает кэш слоёв, multi-stage build, 13 best practice'ов написания Dockerfile — 800 МБ → 30 МБ"
---

# 04. Слои, кэширование, multi-stage и 13 best practice'ов

> Роадмап → 3. Docker → Теория → Образы → «Слои и кэширование», «Multi-stage build», «Best practice'ы»
> «Как правильно писать Dockerfile, чтобы на выходе образ был легковесный.»
> **После темы ты умеешь:** ускорить сборку в 10 раз и уменьшить образ в 20 раз,
> и объяснить на собесе, зачем нужен multi-stage.

---

## 🗺️ Схема: как работает кэш сборки

```text:no-line-numbers
Dockerfile                     Кэш проверяется сверху вниз:
──────────────────────────     ┌──────────────────────────────────────────────┐
FROM node:22-alpine        ✅  │ базовый слой тот же → HIT                    │
WORKDIR /app               ✅  │ инструкция не изменилась → HIT               │
COPY package*.json ./      ✅  │ файлы не изменились (по чексумме) → HIT      │
RUN npm ci                 ✅  │ пред. слой из кэша + строка та же → HIT      │  ← 3 минуты сэкономлено
COPY . .                   ❌  │ изменился хоть один файл → MISS              │
RUN npm run build          ❌  │ пред. слой пересобран → ВЫНУЖДЕННЫЙ MISS     │
CMD ["node","dist/main"]   ❌  │ ...и всё ниже тоже                           │
                               └──────────────────────────────────────────────┘

 ⚠️ ГЛАВНОЕ ПРАВИЛО: один промах — и ВСЁ, что ниже, пересобирается заново.
 Отсюда порядок: РЕДКО меняется — наверх, ЧАСТО меняется (код) — вниз.
```

### Как докер решает, HIT или MISS

| Инструкция | Критерий кэша |
|------------|---------------|
| `RUN` | Совпадает **текстовая строка** команды (докер НЕ знает, что `apt-get update` вернёт другое) |
| `COPY` / `ADD` | Совпадает **контрольная сумма содержимого** файлов + метаданные (права, размер) |
| Остальные | Совпадает текст инструкции |
| Любая | + предыдущий слой должен быть из кэша |

Отсюда классическая проблема **stale cache**: `RUN apt-get update` берётся из кэша недельной
давности, и `apt-get install` ставит старые версии или падает с 404. Лечение:
`update` и `install` — **в одном `RUN`**, плюс периодический `--no-cache`.

---

## 1. Правила кэширования на практике

```dockerfile
# ❌ ПЛОХО — любая правка кода переустанавливает все зависимости (3-10 минут)
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
CMD ["python", "app.py"]

# ✅ ХОРОШО — зависимости кэшируются, пока не менялся requirements.txt (5 секунд)
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .          # ← только манифест зависимостей
RUN pip install --no-cache-dir -r requirements.txt
COPY . .                         # ← код в самом конце
CMD ["python", "app.py"]
```

Тот же приём для всех экосистем:

| Стек | Копировать первым |
|------|-------------------|
| Node | `package.json package-lock.json` → `npm ci` |
| Python | `requirements.txt` / `pyproject.toml poetry.lock` |
| Go | `go.mod go.sum` → `go mod download` |
| Java/Maven | `pom.xml` → `mvn dependency:go-offline` |
| Rust | `Cargo.toml Cargo.lock` |
| PHP | `composer.json composer.lock` |

### Управление кэшем

```bash
docker build --no-cache .                       # игнорировать кэш целиком
docker build --pull .                           # заново проверить базовый образ
docker build --cache-from myapp:latest .        # взять кэш из готового образа (CI!)
docker builder prune                            # почистить кэш сборок
docker builder prune --filter until=168h -f     # старше недели
docker buildx build --cache-to type=registry,ref=myapp:cache --cache-from type=registry,ref=myapp:cache .
```

> В CI кэша между запусками обычно нет (раннер чистый). Поэтому используют
> `--cache-from` с предыдущим образом из registry или BuildKit-кэш в registry/GitHub Actions cache.

### BuildKit cache mounts — кэш, который не попадает в слой

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```
Кэш pip/npm/apt/go живёт **между сборками**, но **не увеличивает образ**. Для apt:
```dockerfile
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends curl
```

---

## 2. Слои: меньше — лучше (но без фанатизма)

```dockerfile
# ❌ 4 слоя, кэш apt внутри образа, мусор остался навсегда
RUN apt-get update
RUN apt-get install -y curl git
RUN rm -rf /var/lib/apt/lists/*

# ✅ 1 слой, чистка ДО фиксации слоя
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl git \
 && rm -rf /var/lib/apt/lists/*
```

Что чистить в том же `RUN`:

| Стек | Чистка |
|------|--------|
| apt | `rm -rf /var/lib/apt/lists/*`, `--no-install-recommends` |
| apk | `apk add --no-cache pkg` (или `--virtual .build && apk del .build`) |
| yum/dnf | `yum clean all && rm -rf /var/cache/yum` |
| pip | `--no-cache-dir` |
| npm | `npm ci --omit=dev && npm cache clean --force` |
| Сборочные зависимости | ставить в отдельной стадии multi-stage |

> Не доводи до абсурда: склеивать в один `RUN` **несвязанные** операции вредно —
> теряется кэш (правка одной строки пересобирает всё) и читаемость.
> Логика: одна инструкция = одна логическая операция.

---

## 3. Multi-stage build ⭐ (вопрос с собеса)

**Проблема:** чтобы собрать приложение, нужны компилятор, SDK, dev-зависимости, исходники.
Чтобы **запустить** — нужен только артефакт. Но всё сборочное остаётся в слоях.

**Решение:** несколько `FROM` в одном Dockerfile. Финальный образ — последняя стадия;
из предыдущих копируется только результат.

```text:no-line-numbers
┌── Stage "builder" ──────────────┐      ┌── Stage "runtime" (финальный) ──┐
│ FROM golang:1.23                │      │ FROM alpine:3.20                │
│ go mod download                 │  ──► │ COPY --from=builder /app/server │
│ go build -o /app/server         │      │ CMD ["/server"]                 │
│ размер: ~900 МБ                 │      │ размер: ~12 МБ                  │
└─────────────────────────────────┘      └─────────────────────────────────┘
      ↑ в итоговый образ НЕ попадает            ↑ только это уедет в registry
```

### Go → 900 МБ превращается в 8 МБ

```dockerfile
# syntax=docker/dockerfile:1
FROM golang:1.23-alpine AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /out/server ./cmd/server

FROM scratch                       # ПУСТОЙ образ
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /out/server /server
USER 65534:65534                   # nobody
EXPOSE 8080
ENTRYPOINT ["/server"]
```

### Node: сборка фронта + рантайм

```dockerfile
FROM node:22-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --from=build /app/dist ./dist
USER node
EXPOSE 3000
CMD ["node", "dist/main.js"]
```

### Приёмы multi-stage

```dockerfile
# 1. Стадия для тестов/линта — CI останавливается на ней
FROM base AS test
RUN pytest -q && ruff check .
# docker build --target test .

# 2. Копировать можно из ЛЮБОГО образа, не только из своей стадии
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY --from=nginx:alpine /etc/nginx/nginx.conf /etc/nginx/nginx.conf

# 3. Общая база для всех стадий — экономит и слои, и время
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1
FROM base AS builder
...
FROM base AS runtime
...
```

**Ответ на собесе «зачем multi-stage»:**
> Чтобы в финальном образе остался только рантайм и артефакт. Это даёт:
> (1) размер меньше в разы или десятки раз → быстрее push/pull и деплой;
> (2) безопасность: нет компиляторов, исходников, dev-зависимостей, `.git`, токенов пакетных
> менеджеров → меньше поверхность атаки и меньше CVE;
> (3) сборочный кэш и инструменты не засоряют прод-образ;
> (4) можно собрать несколько вариантов (test/dev/prod) из одного Dockerfile через `--target`.

---

## 4. Итог: 800 МБ → 30 МБ (типовой Python)

| Шаг | Размер |
|-----|--------|
| `FROM python:3.12` + `COPY . .` + `pip install` | ~1.1 ГБ |
| → база `python:3.12-slim` | ~380 МБ |
| → `.dockerignore` (без `.git`, `.venv`, тестов) | ~310 МБ |
| → `--no-install-recommends` + чистка apt в том же RUN | ~250 МБ |
| → multi-stage: venv собирается в builder | ~150 МБ |
| → только нужные системные библиотеки в runtime | ~120 МБ |
| (для Go/Rust) → `scratch`/`distroless` | ~10-25 МБ |

---

## 5. 📋 13 best practice'ов написания Dockerfile

Тот самый список из роадмапа — учи как мантру, спрашивают почти дословно.

| # | Практика | Почему |
|---|----------|--------|
| **1** | **Официальные/проверенные базовые образы** (`python`, `node`, Docker Official / Verified Publisher) | Обновляются, патчатся, без закладок. Случайный образ с Docker Hub — это чужой код, запущенный у тебя в проде |
| **2** | **Фиксируй версию тега**, не `latest` (а для критичного — дайджест) | Воспроизводимость: сборка месяц спустя даёт тот же результат |
| **3** | **Маленький базовый образ** (`-slim`, `-alpine`, distroless, scratch) | Меньше вес, меньше CVE, быстрее деплой |
| **4** | **Порядок инструкций по частоте изменений** (редкое — наверх, код — вниз) | Кэш: сборка секунды вместо минут |
| **5** | **`.dockerignore` обязателен** | Быстрый контекст, нет секретов и мусора в образе |
| **6** | **Multi-stage build** | Сборочные инструменты не уезжают в прод |
| **7** | **Минимум слоёв: связанные команды в один `RUN`, чистка в той же инструкции** | Мусор не фиксируется в слое |
| **8** | **Только нужные пакеты** (`--no-install-recommends`, без `vim`/`curl` «на всякий») | Размер и поверхность атаки |
| **9** | **Непривилегированный пользователь** (`USER`) | Root в контейнере = риск для хоста |
| **10** | **Никаких секретов в образе** (ни `ENV`, ни `ARG`, ни `COPY`) — `--mount=type=secret` / рантайм | Всё в образе достаётся любым, кто его скачал |
| **11** | **Один процесс на контейнер** | Масштабирование, логи, рестарты, health-check |
| **12** | **Корректные `CMD`/`ENTRYPOINT` в exec-форме + `HEALTHCHECK`** | Сигналы доходят, graceful shutdown, оркестратор видит состояние |
| **13** | **Сканируй образы и добавляй метаданные** (`docker scout` / trivy + OCI `LABEL`) | Уязвимости находят до прода, по меткам понятно, из какого коммита образ |

Дополнительно (почти всегда идут в том же списке): используй **линтер** (`hadolint`),
логи — **в stdout/stderr**, а не в файл, данные — **в volume**, а не в контейнерный слой.

---

## 💼 Как это в DevOps

- **Скорость CI — это деньги и нервы.** Пайплайн 15 минут → команда перестаёт часто деплоить.
  Правильный порядок слоёв + `--cache-from` часто сокращают сборку в 5-10 раз.
- **Размер образа влияет на деплой**: pull 1.5 ГБ на 50 нод k8s против pull 40 МБ — это разница
  между «раскатили за 20 секунд» и «ждём 10 минут», плюс трафик и место на нодах.
- **Безопасность:** каждый лишний пакет = потенциальная CVE. Distroless-образы регулярно
  показывают 0 уязвимостей там, где `ubuntu:latest` даёт сотни.
- **Один Dockerfile — несколько целей** (`--target test`, `--target dev`, `--target prod`)
  избавляет от зоопарка `Dockerfile.dev`, `Dockerfile.ci`, `Dockerfile.prod`.

---

## 🧪 Мини-лаба: 900 МБ → 10 МБ

```bash
mkdir -p ~/docker-lab/04 && cd ~/docker-lab/04

# --- Go-приложение
cat > main.go <<'EOF'
package main
import ("fmt"; "net/http"; "os")
func main() {
    http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
        h, _ := os.Hostname(); fmt.Fprintf(w, "hello from %s\n", h)
    })
    http.ListenAndServe(":8080", nil)
}
EOF
cat > go.mod <<'EOF'
module demo

go 1.21
EOF

# 1. НАИВНО: всё в одном образе
cat > Dockerfile.naive <<'EOF'
FROM golang:1.23
WORKDIR /src
COPY . .
RUN go build -o /server .
CMD ["/server"]
EOF
docker build -q -f Dockerfile.naive -t demo:naive .

# 2. MULTI-STAGE на alpine
cat > Dockerfile.multi <<'EOF'
FROM golang:1.23-alpine AS builder
WORKDIR /src
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /server .

FROM alpine:3.20
RUN adduser -S -u 10001 app
COPY --from=builder /server /server
USER app
EXPOSE 8080
ENTRYPOINT ["/server"]
EOF
docker build -q -f Dockerfile.multi -t demo:multi .

# 3. SCRATCH — предел
cat > Dockerfile.scratch <<'EOF'
FROM golang:1.23-alpine AS builder
WORKDIR /src
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /server .

FROM scratch
COPY --from=builder /server /server
USER 65534:65534
EXPOSE 8080
ENTRYPOINT ["/server"]
EOF
docker build -q -f Dockerfile.scratch -t demo:scratch .

docker images demo          # ⭐ сравни: ~900MB / ~14MB / ~7MB
docker run -d --name m -p 8081:8080 demo:scratch && curl -s localhost:8081 && docker rm -f m

# --- Кэш: измеряем выигрыш от порядка инструкций
mkdir -p ~/docker-lab/04py && cd ~/docker-lab/04py
printf 'requests==2.32.3\nflask==3.0.3\n' > requirements.txt
printf 'print("app v1")\n' > app.py

cat > Dockerfile.bad <<'EOF'
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python","app.py"]
EOF
cat > Dockerfile.good <<'EOF'
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python","app.py"]
EOF

docker build -q -f Dockerfile.bad  -t py:bad  .    # первая сборка — прогрев
docker build -q -f Dockerfile.good -t py:good .

printf 'print("app v2")\n' > app.py                # ИЗМЕНИЛИ ТОЛЬКО КОД
echo "--- bad:";  time docker build -q -f Dockerfile.bad  -t py:bad  .
echo "--- good:"; time docker build -q -f Dockerfile.good -t py:good .
# bad: заново ставит зависимости; good: ~1 секунда, CACHED

# Посмотреть CACHED-строки
docker build --progress=plain -f Dockerfile.good -t py:good . 2>&1 | grep -i cached

# --- Stale cache на apt
cat > Dockerfile.stale <<'EOF'
FROM debian:bookworm-slim
RUN apt-get update
RUN apt-get install -y curl
EOF
# Через неделю первый RUN возьмётся из кэша, а install может не найти пакеты.
# Правильно — одной инструкцией:
cat > Dockerfile.fresh <<'EOF'
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*
EOF
docker build -q -f Dockerfile.fresh -t deb:fresh .
docker history deb:fresh

# --- Стадия для тестов
cat > Dockerfile.target <<'EOF'
FROM python:3.12-slim AS base
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS test
COPY . .
RUN python -c "print('тесты прошли')"

FROM base AS prod
COPY app.py .
CMD ["python","app.py"]
EOF
docker build --target test -q -f Dockerfile.target -t py:test .
docker build --target prod -q -f Dockerfile.target -t py:prod .

# --- Уборка
cd ~ && rm -rf ~/docker-lab/04 ~/docker-lab/04py
docker rmi demo:naive demo:multi demo:scratch py:bad py:good py:test py:prod deb:fresh 2>/dev/null
docker builder prune -f
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `docker build --no-cache .` | Полная пересборка |
| `docker build --pull .` | Обновить базовый образ |
| `docker build --target NAME .` | Собрать до конкретной стадии |
| `docker build --cache-from img .` | Взять кэш из готового образа (CI) |
| `docker build --progress=plain .` | Видеть `CACHED` и вывод команд |
| `docker builder prune [-a]` | Почистить кэш сборок |
| `docker history --no-trunc img` | Что сколько весит |
| `docker system df -v` | Сколько занимает build cache |
| `docker buildx build --platform …` | Мультиарх-сборка |
| `dive img` | Интерактивный анализ слоёв (сторонняя утилита) |
| `hadolint Dockerfile` | Линтер |
| `docker scout cves img` / `trivy image img` | Сканер уязвимостей |

---

## 🧠 Что запомнить

1. Кэш проверяется **сверху вниз**; один MISS пересобирает всё, что ниже.
2. `RUN` кэшируется по **тексту команды**, `COPY`/`ADD` — по **содержимому файлов**.
3. Порядок: база → системные пакеты → зависимости приложения → **код в самом конце**.
4. `apt-get update` и `install` — **всегда в одном `RUN`** (иначе stale cache).
5. Чистка мусора работает только **в той же инструкции**, где мусор создан.
6. **Multi-stage** = сборочные инструменты в builder, в финал — только артефакт:
   меньше размер, меньше CVE, нет исходников и токенов.
7. `COPY --from=` умеет брать файлы из любой стадии **и из любого чужого образа**.
8. `--target` позволяет из одного Dockerfile собирать test/dev/prod.
9. BuildKit `--mount=type=cache` даёт кэш зависимостей, не раздувая образ.
10. В CI кэш приходит через `--cache-from` / registry-кэш, локального кэша там нет.
11. 13 best practice'ов: официальная база → пин версии → маленькая база → порядок слоёв →
    `.dockerignore` → multi-stage → мало слоёв и чистка → минимум пакетов → non-root →
    без секретов → один процесс → exec-форма + healthcheck → сканирование и метки.
12. Размер образа — это скорость деплоя и площадь атаки, а не эстетика.

---

## Задачи

> Лаба: `mkdir -p ~/docker-lab/04 && cd ~/docker-lab/04`
> ⭐ «Зачем нужен multi-stage build?» и «Какие best practice'ы?» — вопросы прямо из роадмапа.

---

### Блок A. Теория

**A1.** Как докер решает, брать слой из кэша или пересобирать? Опиши критерий для `RUN`
и для `COPY` отдельно.

<details><summary>Ответ</summary>

Для `RUN` сравнивается **текстовая строка** инструкции (плюс идентичность родительского
слоя): докер не выполняет команду, чтобы узнать, изменился ли результат. Для `COPY`/`ADD`
считается контрольная сумма **содержимого** копируемых файлов и их метаданных. Любое расхождение —
MISS.

</details>

**A2.** Что произойдёт с кэшем нижележащих слоёв, если изменился один слой в середине?

<details><summary>Ответ</summary>

Все нижележащие слои тоже пересобираются, даже если их инструкции не менялись:
кэш валиден только если валиден родитель.

</details>

**A3.** Почему `COPY . .` перед установкой зависимостей — главная ошибка новичка?

<details><summary>Ответ</summary>

Потому что любой изменённый файл проекта (даже README) инвалидирует слой `COPY`,
а вместе с ним — установку зависимостей, которая идёт следом. Каждая сборка заново качает
и ставит все библиотеки: минуты вместо секунд.

</details>

**A4.** Что такое stale cache на `apt-get update` и как его избежать?

<details><summary>Ответ</summary>

`RUN apt-get update` отдельной инструкцией кэшируется надолго; при следующей сборке
индекс пакетов берётся из старого слоя, а `apt-get install` пытается скачать версии, которых
в репозитории уже нет → 404 или старые уязвимые версии. Лечение: `update && install` в одном
`RUN`, периодическая сборка с `--no-cache`/`--pull`.

</details>

**A5.** Почему чистка мусора (`rm -rf /var/lib/apt/lists/*`) работает только в том же `RUN`?

<details><summary>Ответ</summary>

Каждый `RUN` фиксируется как отдельный слой. Мусор, созданный в слое N, остаётся
в слое N навсегда; `rm` в слое N+1 лишь помечает файлы удалёнными (whiteout), но байты
по-прежнему в образе и качаются при pull.

</details>

**A6.** Что такое multi-stage build и зачем он нужен? Назови 4 выгоды. *(вопрос из роадмапа)*

<details><summary>Ответ</summary>

Несколько `FROM` в одном Dockerfile: промежуточные стадии собирают артефакт,
финальная берёт из них только результат (`COPY --from=`). Выгоды: (1) размер — в разы/десятки
раз меньше; (2) безопасность — нет компиляторов, исходников, dev-зависимостей, токенов;
(3) чистый прод-образ без сборочного кэша; (4) один Dockerfile на несколько целей (`--target`).

</details>

**A7.** Как скопировать файл из предыдущей стадии? А из чужого образа, который вообще
не участвует в сборке?

<details><summary>Ответ</summary>

Из стадии: `COPY --from=builder /app/bin /usr/local/bin/`.
Из чужого образа: `COPY --from=nginx:alpine /etc/nginx/nginx.conf /etc/nginx/nginx.conf` —
докер сам скачает образ и возьмёт файл, не запуская его.

</details>

**A8.** Что делает `--target` и зачем это в CI?

<details><summary>Ответ</summary>

Останавливает сборку на указанной стадии. В CI: `--target test` для прогона тестов
в том же окружении, `--target prod` для артефакта; локально — отладка промежуточной стадии.

</details>

**A9.** Что такое `--mount=type=cache` и чем это лучше обычного кэша слоёв?

<details><summary>Ответ</summary>

BuildKit-маунт, который подключает постоянный каталог кэша (pip/npm/go/apt) только
на время выполнения инструкции. Кэш сохраняется **между сборками**, но **не становится слоем** —
образ не растёт. Обычный кэш слоёв инвалидируется при смене манифеста зависимостей, а cache mount
переживает и это (перекачивается только новое).

</details>

**A10.** Почему в CI кэш обычно не работает и как это чинят?

<details><summary>Ответ</summary>

Раннер обычно чистый (новый контейнер/VM) — локального кэша слоёв нет. Решения:
`--cache-from` с образом из registry (+ `BUILDKIT_INLINE_CACHE=1` при сборке),
BuildKit registry-кэш (`--cache-to type=registry,ref=...`), кэш раннера (GitLab cache,
GitHub Actions `type=gha`), собственный persistent builder (`docker buildx create`).

</details>

**A11.** Перечисли 13 best practice'ов написания Dockerfile. *(вопрос из роадмапа)*

<details><summary>Ответ</summary>

(1) официальные/проверенные базовые образы; (2) фиксированный тег/дайджест, не `latest`;
(3) маленькая база (slim/alpine/distroless/scratch); (4) порядок инструкций по частоте изменений;
(5) `.dockerignore`; (6) multi-stage; (7) объединять связанные `RUN` и чистить в той же инструкции;
(8) ставить только нужные пакеты (`--no-install-recommends`); (9) non-root `USER`;
(10) никаких секретов в образе; (11) один процесс на контейнер; (12) exec-форма
`CMD`/`ENTRYPOINT` + `HEALTHCHECK`; (13) сканирование уязвимостей и OCI-метки.

</details>

**A12.** Всегда ли «меньше слоёв — лучше»? Приведи контрпример.

<details><summary>Ответ</summary>

Нет. Если склеить в один `RUN` независимые операции (установка системных пакетов +
установка зависимостей приложения), то изменение одной строки зависимостей заставит заново
ставить и системные пакеты. Кроме того, страдает читаемость. Правило: одна инструкция =
одна логическая операция, чистка — внутри неё.

</details>

**A13.** Чем `FROM scratch` отличается от `FROM alpine`? Для каких языков подходит scratch?

<details><summary>Ответ</summary>

`scratch` — абсолютно пустой образ: нет shell, libc, пакетного менеджера, даже
`/etc/passwd` и корневых сертификатов. Подходит для **статически слинкованных** бинарников:
Go (`CGO_ENABLED=0`), Rust (musl-таргет), C со статической линковкой. `alpine` — минимальный
дистрибутив (~7 МБ) с busybox, apk и musl: можно зайти внутрь и отладить.

</details>

**A14.** Что такое distroless и в чём его плюс и минус?

<details><summary>Ответ</summary>

Distroless (`gcr.io/distroless/*`) — образы с рантаймом языка (Java, Python, Node,
статический C), но **без shell и пакетного менеджера**. Плюс: очень маленькая поверхность атаки,
часто ноль CVE, работает с non-root по умолчанию. Минус: невозможно `docker exec … sh` для
отладки (нужны debug-варианты образов или `nsenter`/эфемерные контейнеры в k8s).

</details>

**A15.** Почему `--no-install-recommends` важен?

<details><summary>Ответ</summary>

apt по умолчанию ставит «рекомендуемые» пакеты — десятки мегабайт того, что приложению
не нужно (документация, шрифты, лишние библиотеки). Это и размер, и лишние CVE.

</details>

**A16.** У тебя образ 1.2 ГБ. Опиши пошаговый план его уменьшения (минимум 5 шагов).

<details><summary>Ответ</summary>

(1) Сменить базу на `-slim`/`-alpine`/distroless; (2) добавить `.dockerignore`;
(3) объединить `RUN` и чистить кэши пакетных менеджеров в той же инструкции;
(4) `--no-install-recommends` и убрать «на всякий случай» пакеты (vim, curl, git);
(5) multi-stage: сборочные зависимости и исходники — в builder; (6) не копировать в образ тесты,
документацию, фикстуры; (7) проверить через `docker history`/`dive`, что осталось,
и вынести данные в volume.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  docker build --no-cache -t app .
B2.  docker build --pull -t app .
B3.  docker build --target builder -t app:build .
B4.  docker build --cache-from myapp:latest -t myapp:new .
B5.  docker build --progress=plain -t app . 2>&1 | grep CACHED
B6.  docker builder prune --filter until=168h -f
B7.  docker system df -v | grep -i "build cache"
B8.  docker history --no-trunc app | sort -k2 -h
B9.  docker buildx build --platform linux/amd64,linux/arm64 --push -t reg/app:1.0 .
B10. docker run --rm -i hadolint/hadolint < Dockerfile
B11. docker scout cves app:1.0
B12. docker build --build-arg BUILDKIT_INLINE_CACHE=1 -t app .
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Пересобрать всё с нуля, игнорируя кэш слоёв.
B2.  Принудительно проверить и скачать свежую версию базового образа (тег мог переехать).
B3.  Собрать только до стадии builder.
B4.  Использовать слои указанного образа как источник кэша — типовой приём в CI.
B5.  Показать подробный лог и выбрать строки, взятые из кэша (диагностика кэша).
B6.  Удалить записи build cache старше 7 дней.
B7.  Посмотреть, сколько места занимает именно кэш сборок.
B8.  История слоёв, отсортированная по размеру — быстро найти «жир».
B9.  Собрать мультиарх-образ под amd64 и arm64 и сразу запушить (манифест-лист).
B10. Прогнать линтер Dockerfile.
B11. Показать известные уязвимости образа (Docker Scout).
B12. Встроить метаданные кэша в образ, чтобы другой раннер мог использовать --cache-from.
```

</details>

**B13.** Чем отличаются по результату `docker build --no-cache` и `docker builder prune -a`?

<details><summary>Ответ</summary>

`--no-cache` — разовая полная пересборка конкретного образа (кэш на диске остаётся
и пополняется). `docker builder prune -a` — **удаляет** сам кэш сборок с диска, влияя на все
последующие сборки.

</details>

---

### Блок C. Практика

#### C1. 🔑 Уменьшить образ в 20 раз (главное задание)

Дан заведомо плохой Dockerfile для Python-приложения:

```dockerfile
FROM python:3.12
RUN apt-get update
RUN apt-get install -y build-essential curl git vim
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
RUN rm -rf /var/lib/apt/lists/*
CMD python app.py
```

Задача: переписать так, чтобы выполнялись **все 13 best practice'ов**, и:
1. Зафиксировать размер «до» и «после».
2. Показать, что при изменении только `app.py` пересборка занимает < 3 секунд.
3. Финальный образ работает не от root.
4. `hadolint` не выдаёт ошибок.
5. Объяснить письменно каждое своё изменение (по пунктам).

<details><summary>Ответ (эталон)</summary>

```bash
mkdir -p ~/docker-lab/04c1 && cd ~/docker-lab/04c1
printf 'flask==3.0.3\nrequests==2.32.3\n' > requirements.txt
printf 'print("app v1")\n' > app.py

cat > Dockerfile.bad <<'EOF'
FROM python:3.12
RUN apt-get update
RUN apt-get install -y build-essential curl git vim
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
RUN rm -rf /var/lib/apt/lists/*
CMD python app.py
EOF
docker build -q -f Dockerfile.bad -t c1:bad . && docker images c1:bad     # ~1.2 GB

cat > .dockerignore <<'EOF'
.git
.venv
__pycache__/
*.pyc
tests/
*.md
Dockerfile*
EOF

cat > Dockerfile <<'EOF'
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

FROM base AS builder
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

FROM base AS runtime
LABEL org.opencontainers.image.source="https://github.com/me/app"
ENV PATH="/opt/venv/bin:$PATH"
RUN groupadd -r app && useradd -r -g app app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app.py .
USER app
CMD ["python", "app.py"]
EOF
docker build -q -t c1:good . && docker images "c1"

printf 'print("app v2")\n' > app.py
time docker build -q -t c1:good .          # < 3 сек, всё выше COPY — CACHED
docker run --rm c1:good
docker run --rm --entrypoint id c1:good    # non-root
docker run --rm -i hadolint/hadolint < Dockerfile
```

Что изменено и почему:
1. `python:3.12` → `python:3.12-slim` — база меньше (~1 ГБ → ~130 МБ) *(bp 3)*.
2. Тег зафиксирован, не `latest` *(bp 2)*, образ официальный *(bp 1)*.
3. `apt-get update && install && rm -rf` в одном `RUN` — нет stale cache, мусор не фиксируется *(bp 7)*.
4. `--no-install-recommends`, убраны `curl/git/vim` *(bp 8)*.
5. `COPY requirements.txt` до `pip install`, код — в конце *(bp 4)*.
6. Добавлен `.dockerignore` *(bp 5)*.
7. Multi-stage: `build-essential` остался в builder *(bp 6)*.
8. `USER app` *(bp 9)*, секретов нет *(bp 10)*, один процесс *(bp 11)*.
9. `CMD` в exec-форме *(bp 12)*, добавлена OCI-метка и прогон сканера *(bp 13)*.

</details>

#### C2. Измерить эффект порядка слоёв

1. Собери два образа: с `COPY . .` до установки зависимостей и после.
2. Прогрей кэш обоих.
3. Измени только код, замерь `time docker build` для обоих.
4. Запиши цифры. Во сколько раз разница?
5. Покажи, какие строки в выводе помечены `CACHED`.

<details><summary>Ответ</summary>

```bash
cd ~/docker-lab/04c1
cat > Dockerfile.order-bad <<'EOF'
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python","app.py"]
EOF
cat > Dockerfile.order-good <<'EOF'
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python","app.py"]
EOF
docker build -q -f Dockerfile.order-bad  -t o:bad  .
docker build -q -f Dockerfile.order-good -t o:good .
printf 'print("changed")\n' > app.py
echo BAD:;  time docker build -q -f Dockerfile.order-bad  -t o:bad  .
echo GOOD:; time docker build -q -f Dockerfile.order-good -t o:good .
docker build --progress=plain -f Dockerfile.order-good -t o:good . 2>&1 | grep -i cached
```

</details>

#### C3. Multi-stage для компилируемого языка

Сделай Go (или Rust/Java) приложение и три версии образа:
наивная (`FROM golang`), multi-stage на alpine, multi-stage на scratch.
Сравни размеры и убедись, что все три работают. Объясни, почему в scratch-версию
нужно копировать `ca-certificates.crt`, если приложение ходит по HTTPS.

<details><summary>Ответ</summary>

См. мини-лабу конспекта (naive ~900MB / alpine ~14MB / scratch ~7MB).

`ca-certificates` нужны, т.к. в `scratch` нет `/etc/ssl/certs` — TLS-валидация упадёт:
```bash
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
```

</details>

#### C4. Multi-stage для интерпретируемого языка

Python не компилируется — зачем ему multi-stage? Сделай образ, где:
- стадия `builder` ставит `build-essential` и собирает зависимости в venv;
- стадия `runtime` берёт только готовый venv;
- покажи разницу в размере и объясни, что именно осталось за бортом.

<details><summary>Ответ</summary>

За бортом остаются `build-essential` (~200 МБ), заголовочные файлы, кэш pip и исходники
пакетов; в runtime едет только готовый venv (см. Dockerfile из C1).

</details>

#### C5. Стадии под разные цели

Один Dockerfile, три цели:
- `--target dev` — с dev-зависимостями и hot reload;
- `--target test` — запускает линтер и тесты при сборке (падает сборка → падает CI);
- `--target prod` — минимальный, non-root.

Проверь, что `docker build --target test .` действительно падает, если тест сломан.

<details><summary>Ответ</summary>

```bash
cat > Dockerfile.multi <<'EOF'
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS dev
RUN pip install --no-cache-dir watchdog ruff pytest
COPY . .
CMD ["python","app.py"]

FROM dev AS test
RUN ruff check . || true
RUN python -c "assert 1 == 1, 'тест провален'"

FROM base AS prod
RUN groupadd -r app && useradd -r -g app app
COPY --chown=app:app app.py .
USER app
CMD ["python","app.py"]
EOF
docker build --target test -q -f Dockerfile.multi -t m:test . && echo "тесты ок"
docker build --target prod -q -f Dockerfile.multi -t m:prod .
# сломать тест → сборка --target test падает → CI красный
```

</details>

#### C6. Cache mounts (BuildKit)

1. Собери образ с `pip install` обычным способом, замерь время второй сборки
   после изменения `requirements.txt` (добавь одну библиотеку).
2. Переделай на `RUN --mount=type=cache,target=/root/.cache/pip`, повтори замер.
3. Покажи, что кэш pip **не** попал в слои образа.

<details><summary>Ответ</summary>

```bash
cat > Dockerfile.cache <<'EOF'
# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt
COPY . .
CMD ["python","app.py"]
EOF
docker build -q -f Dockerfile.cache -t cm:1 .
printf 'flask==3.0.3\nrequests==2.32.3\nrich==13.7.1\n' > requirements.txt
time docker build -q -f Dockerfile.cache -t cm:2 .    # flask/requests берутся из кэша pip
docker run --rm cm:2 sh -c 'du -sh /root/.cache 2>/dev/null || echo "кэша pip в образе нет"'
```

</details>

#### C7. Кэш в CI

Симулируй CI без локального кэша:
```bash
docker builder prune -af          # «чистый раннер»
```
1. Собери образ и запушь его (или сохрани локально) с `BUILDKIT_INLINE_CACHE=1`.
2. Снова очисти кэш и собери с `--cache-from`.
3. Покажи, что слои переиспользовались.

<details><summary>Ответ</summary>

```bash
docker builder prune -af
docker build --build-arg BUILDKIT_INLINE_CACHE=1 -t c1:cache .
docker builder prune -af
docker build --cache-from c1:cache --progress=plain -t c1:new . 2>&1 | grep -ci cached
```

</details>

#### C8. Анализ чужого образа

Возьми любой публичный тяжёлый образ (например `node:22`) и:
1. Найди 3 самых больших слоя и что их создало.
2. Посчитай, сколько слоёв.
3. Сравни с `node:22-alpine` и `node:22-slim`.
4. Установи `dive` и пройдись по слоям интерактивно (опционально).

<details><summary>Ответ</summary>

```bash
docker pull node:22 node:22-slim node:22-alpine 2>/dev/null || \
  { docker pull node:22; docker pull node:22-slim; docker pull node:22-alpine; }
docker images node
docker history node:22 --format '{{.Size}}\t{{.CreatedBy}}' | sort -h -r | head -3
docker image inspect node:22 | jq '.[0].RootFS.Layers | length'
```

</details>

---

### Блок D. Инциденты

**D1.** Сборка в CI идёт 18 минут. Локально — 40 секунд. Обе используют один Dockerfile.
Перечисли причины и решения.

<details><summary>Ответ</summary>

В CI нет локального кэша слоёв (чистый раннер), плюс возможны: отсутствие
`.dockerignore` (весь `.git` в контексте), сборка `--no-cache`, медленная сеть до registry,
слабый раннер, отсутствие `--cache-from`. Решения: registry-кэш/inline cache,
persistent builder, `.dockerignore`, правильный порядок слоёв, cache mounts для зависимостей.

</details>

**D2.** После добавления одной строчки комментария в середину Dockerfile пересобралась
половина образа. Почему?

<details><summary>Ответ</summary>

Кэш `RUN`/любой инструкции считается по **тексту**; добавленный комментарий меняет
содержимое Dockerfile, и если он попал внутрь инструкции (например, внутрь многострочного `RUN`)
— это другая строка → MISS, и всё ниже пересобирается. Отдельная строка-комментарий между
инструкциями кэш не ломает, но смена **порядка** инструкций ломает.

</details>

**D3.** Образ приложения на Go весит 1.1 ГБ. Разработчик говорит «так надо, там компилятор».
Что предложишь и какой размер обещаешь?

<details><summary>Ответ</summary>

Multi-stage: собирать в `golang:1.23-alpine`, а в финал класть только бинарник
в `alpine` (~10-15 МБ) или `scratch` (~5-8 МБ, если `CGO_ENABLED=0`).
Плюс `-ldflags="-s -w"` уберёт отладочные символы. Обещаемый размер — единицы-десятки мегабайт.

</details>

**D4.** В multi-stage образ на `scratch` приложение падает с
`x509: certificate signed by unknown authority` при обращении к внешнему API. Причина и фикс.

<details><summary>Ответ</summary>

В `scratch` нет корневых сертификатов — TLS не проверяется. Фикс:
`COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/`
(или база `gcr.io/distroless/static:nonroot`, где они есть). Заодно часто нужны
`/etc/passwd` для non-root и tzdata для часовых поясов.

</details>

**D5.** Сборка внезапно падает: `E: Unable to locate package libfoo` — хотя вчера работала,
Dockerfile не менялся. Диагноз?

<details><summary>Ответ</summary>

Stale cache: `apt-get update` взят из старого кэшированного слоя, индекс устарел,
версия пакета в репозитории сменилась. Или изменился сам upstream-репозиторий / пакет
переименован. Лечение: объединить `update` и `install` в один `RUN`, пересобрать
с `--no-cache`/`--pull`, при необходимости пинить версии пакетов.

</details>

**D6.** В образ через `--build-arg GITHUB_TOKEN=...` передали токен для приватного репо.
Токен нашли в публичном образе. Как надо было?

<details><summary>Ответ</summary>

`--build-arg` сохраняется в истории образа. Надо было: BuildKit-секрет
(`RUN --mount=type=secret,id=gh` + `--secret id=gh,src=token.txt`), либо SSH-агент
(`--mount=type=ssh`), либо скачивать зависимости в отдельной стадии, которая не попадает
в финальный образ. Токен, попавший в публичный образ, считается скомпрометированным —
отозвать и перевыпустить.

</details>

**D7.** `docker build` на Apple Silicon даёт образ, который не стартует на amd64-сервере.
Как собирать правильно?

<details><summary>Ответ</summary>

Собирать под целевую платформу: `docker buildx build --platform linux/amd64 …`
или мультиарх `--platform linux/amd64,linux/arm64 --push`. Проверять
<code v-pre>docker image inspect --format '{{.Architecture}}'</code>. В CI — собирать на нужной архитектуре
или через QEMU-эмуляцию (`docker/setup-qemu-action`).

</details>

**D8.** Диск CI-раннера забит: `docker system df` показывает Build Cache = 120 ГБ.
Что делать сейчас и что настроить, чтобы не повторялось?

<details><summary>Ответ</summary>

Сейчас: `docker builder prune -af --filter until=48h` (или `-af` целиком).
Настроить: периодический prune по cron/в пайплайне, ограничение размера кэша
(`docker buildx create --driver-opt` / `/etc/docker/daemon.json` с настройками GC BuildKit),
`--filter until=…` в регулярной задаче, отдельный том под `/var/lib/docker` с мониторингом места.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как работает кэширование слоёв в докере?

<details><summary>Ответ</summary>

Сверху вниз: слой берётся из кэша, если совпала инструкция (для `COPY`/`ADD` —
контрольная сумма файлов) и родительский слой тоже из кэша. Первый MISS инвалидирует всё ниже.

</details>

**2.** Как ускорить сборку образа?

<details><summary>Ответ</summary>

Правильный порядок слоёв (зависимости раньше кода), `.dockerignore`, cache mounts,
`--cache-from` в CI, multi-stage с параллельными стадиями (BuildKit), маленькая база.

</details>

**3.** Зачем нужен multi-stage build? *(роадмап)*

<details><summary>Ответ</summary>

См. A6.

</details>

**4.** Какие best practice'ы написания Dockerfile ты знаешь? *(роадмап)*

<details><summary>Ответ</summary>

См. A11.

</details>

**5.** Как уменьшить размер образа?

<details><summary>Ответ</summary>

Маленькая база, multi-stage, чистка кэшей в том же `RUN`, `--no-install-recommends`,
`.dockerignore`, не копировать лишнее, distroless/scratch для компилируемых языков.

</details>

**6.** Почему нельзя чистить кэш пакетов отдельной инструкцией?

<details><summary>Ответ</summary>

Потому что удалённые файлы остаются в предыдущем слое — образ не худеет, только добавляется
ещё один слой с whiteout-метками.

</details>

**7.** Что такое BuildKit и что он даёт?

<details><summary>Ответ</summary>

Современный движок сборки: параллельные стадии, кэш-маунты, секреты, SSH-проброс,
мультиарх, экспорт кэша в registry, более умная инвалидация. Включается
`DOCKER_BUILDKIT=1`/`docker buildx` (по умолчанию в свежих версиях).

</details>

**8.** Как передать секрет в сборку, чтобы он не остался в образе?

<details><summary>Ответ</summary>

`RUN --mount=type=secret,id=x` + `docker build --secret id=x,src=file` — секрет доступен
только во время выполнения инструкции и не попадает в слои и историю.

</details>

**9.** Чем `scratch` отличается от `alpine` и от distroless?

<details><summary>Ответ</summary>

`scratch` — пусто (только статические бинарники); `alpine` — минимальный дистрибутив
с shell и apk на musl; distroless — рантайм языка без shell и пакетного менеджера.

</details>

**10.** Как организовать кэш сборки в CI?

<details><summary>Ответ</summary>

Inline cache (`BUILDKIT_INLINE_CACHE=1` + `--cache-from`), registry-кэш
(`--cache-to/--cache-from type=registry`), кэш раннера (`type=gha`, GitLab cache)
или постоянный buildx-билдер.

</details>

---

### 🎯 Чек-лист

- [ ] Объясняю правило кэша и порядок инструкций без подсказки
- [ ] Всегда копирую манифест зависимостей до кода
- [ ] Никогда не разношу `apt-get update` и `install` по разным `RUN`
- [ ] Написал multi-stage для компилируемого и для интерпретируемого языка
- [ ] Уменьшил реальный образ минимум в 5 раз и знаю, за счёт чего
- [ ] Помню все 13 best practice'ов и могу защитить каждый
- [ ] Умею настроить кэш сборки в CI
- [ ] Не передаю секреты через `--build-arg`
- [ ] Проверяю образ линтером и сканером
