---
title: "09. Docker Compose"
description: "Многоконтейнерные приложения в YAML: services, depends_on, volumes, networks, profiles, override для dev/prod"
---

# 09. Docker Compose

> Роадмап → 3. Docker → Теория → Контейнеры → Docker Compose
> «В реальности приложение — это не один контейнер. Это минимум приложение + база данных,
> а чаще приложение + база + кэш + nginx + мониторинг. Compose позволяет описать всю эту связку
> декларативно и поднимать/гасить одной командой.»
> **После темы ты умеешь:** описать многоконтейнерное приложение в YAML и управлять им
> одной командой, с зависимостями, healthcheck'ами, сетями и томами.

---

## 🗺️ Схема: что делает compose

```text:no-line-numbers
   docker-compose.yml (декларативное описание)          docker compose up -d
 ┌─────────────────────────────────────────┐        ┌──────────────────────────────┐
 │ services:                               │        │ 1. создаёт СЕТЬ проекта      │
 │   nginx:  image, ports, depends_on      │  ───►  │ 2. создаёт ТОМА              │
 │   app:    build, env, healthcheck       │        │ 3. собирает/тянет ОБРАЗЫ     │
 │   db:     image, volumes, healthcheck   │        │ 4. запускает контейнеры      │
 │   redis:  image                         │        │    в порядке зависимостей    │
 │ volumes:  pgdata                        │        │ 5. подключает всё в сеть,    │
 │ networks: front, back                   │        │    имена сервисов = DNS      │
 └─────────────────────────────────────────┘        └──────────────────────────────┘

  Одна команда вместо 4 длинных docker run + docker network create + docker volume create.
  Файл лежит в git → инфраструктура приложения описана как код.
```

> `docker-compose` (v1, python, с дефисом) устарел. Сейчас — **`docker compose`** (v2, плагин Go).
> Ключ `version:` в начале файла больше не нужен и игнорируется.

---

## 1. Базовый пример

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: app
      POSTGRES_USER: app
      POSTGRES_PASSWORD: ${DB_PASSWORD:?переменная DB_PASSWORD обязательна}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d app"]
      interval: 5s
      timeout: 3s
      retries: 5
      start_period: 10s
    networks: [backend]
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 5
    networks: [backend]
    restart: unless-stopped

  app:
    build:
      context: .
      dockerfile: Dockerfile
      target: prod
      args:
        APP_VERSION: ${APP_VERSION:-dev}
    image: myapp:${APP_VERSION:-dev}
    environment:
      DATABASE_URL: postgresql://app:${DB_PASSWORD}@db:5432/app   # ← имя сервиса как хост!
      REDIS_URL: redis://redis:6379/0
    depends_on:
      db:     { condition: service_healthy }     # ⭐ ждать РЕАЛЬНОЙ готовности
      redis:  { condition: service_healthy }
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"]
      interval: 10s
      timeout: 3s
      retries: 3
      start_period: 15s
    networks: [backend, frontend]
    restart: unless-stopped
    deploy:
      resources:
        limits: { cpus: "1.0", memory: 512M }

  nginx:
    image: nginx:alpine
    ports:
      - "8080:80"                                # ⭐ порты ТОЛЬКО у точки входа
    volumes:
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
      - ./static:/usr/share/nginx/html:ro
    depends_on:
      app: { condition: service_healthy }
    networks: [frontend]
    restart: unless-stopped

volumes:
  pgdata:
  redisdata:

networks:
  frontend:
  backend:
    internal: true        # БД и кэш без выхода в интернет
```

---

## 2. Команды

```bash
docker compose up -d                 # поднять всё в фоне
docker compose up -d --build         # пересобрать образы перед запуском
docker compose up -d app             # только сервис app (и его зависимости)
docker compose up --watch            # (v2.22+) пересинхронизация файлов/пересборка на лету

docker compose ps                    # статус сервисов
docker compose ps -a                 # включая остановленные
docker compose top                   # процессы
docker compose logs -f app           # логи одного сервиса
docker compose logs -f --tail=100    # всех сервисов
docker compose exec app sh           # войти в работающий сервис
docker compose run --rm app python manage.py migrate   # РАЗОВАЯ задача в новом контейнере

docker compose stop / start / restart [service]
docker compose down                  # остановить и удалить контейнеры + сеть (ТОМА ОСТАЮТСЯ)
docker compose down -v               # ⚠️ + УДАЛИТЬ тома (потеря данных!)
docker compose down --rmi all        # + удалить образы

docker compose build [--no-cache] [service]
docker compose pull                  # обновить образы
docker compose config                # ⭐ показать итоговый YAML со всеми подстановками
docker compose config --services     # список сервисов
docker compose kill -s HUP nginx
docker compose cp app:/app/log.txt .
docker compose events
```

| `exec` vs `run` | |
|---|---|
| `docker compose exec app sh` | Команда в **уже работающем** контейнере |
| `docker compose run --rm app cmd` | **Новый** контейнер из того же описания (для миграций, команд, тестов). Порты по умолчанию не публикуются |

---

## 3. Ключевые секции

### `depends_on` ⭐ главная ловушка

```yaml
# ❌ ЭТО НЕ ЖДЁТ ГОТОВНОСТИ — только порядок запуска контейнеров
depends_on:
  - db

# ✅ Ждёт healthcheck
depends_on:
  db:
    condition: service_healthy
  migrations:
    condition: service_completed_successfully    # дождаться успешного завершения задачи
```
Без `condition: service_healthy` приложение стартует раньше, чем БД примет соединения,
и падает с `connection refused`. Второй уровень защиты — **retry в самом приложении**
(в оркестраторах типа k8s `depends_on` вообще нет, и приложение обязано уметь переподключаться).

### Переменные окружения и `.env`

```yaml
environment:
  - APP_ENV=production
  - DB_PASSWORD=${DB_PASSWORD}          # из .env или окружения shell
  - DEBUG=${DEBUG:-false}               # значение по умолчанию
  - API_KEY=${API_KEY:?обязательна}     # ошибка, если не задана
env_file:
  - .env
  - .env.local
```
```bash
# .env рядом с compose-файлом подхватывается автоматически
DB_PASSWORD=supersecret
APP_VERSION=1.4.2
COMPOSE_PROJECT_NAME=shop          # иначе имя = имя каталога
```
> `.env` **обязательно** в `.gitignore`. В репозитории держат `.env.example` с пустыми значениями.

### Volumes и конфиги

```yaml
volumes:
  - pgdata:/var/lib/postgresql/data        # named volume
  - ./nginx.conf:/etc/nginx/nginx.conf:ro  # bind mount (относительный путь — ОК в compose)
  - ./src:/app/src                         # dev: hot reload
  - /app/node_modules                      # анонимный том поверх (защита от перекрытия)
```

### Сети

```yaml
networks: [frontend, backend]    # сервис в двух сетях
# ...
networks:
  frontend:
  backend:
    internal: true
  external-net:
    external: true               # сеть создана вне этого проекта
```
Если ничего не указать — compose создаст сеть `<project>_default` и подключит туда всё.

### Healthcheck

```yaml
healthcheck:
  test: ["CMD-SHELL", "curl -fsS http://localhost:8000/health || exit 1"]
  interval: 10s
  timeout: 3s
  retries: 3
  start_period: 30s      # время на старт, неудачи в этот период не считаются
```

### Ресурсы и рестарт

```yaml
restart: unless-stopped        # no | always | on-failure | unless-stopped
stop_grace_period: 30s         # сколько ждать перед SIGKILL
deploy:
  resources:
    limits:       { cpus: "1.5", memory: 1G }
    reservations: { memory: 256M }
```

### Профили — разные наборы сервисов в одном файле

```yaml
services:
  app: { ... }
  debug-tools:
    image: nicolaka/netshoot
    profiles: [debug]
    command: sleep infinity
```
```bash
docker compose up -d                     # без debug-tools
docker compose --profile debug up -d     # с ними
```

### Наследование и переопределение

```yaml
# docker-compose.yml — база
# docker-compose.override.yml — подхватывается АВТОМАТИЧЕСКИ (обычно dev)
# docker-compose.prod.yml — явно
```
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose config      # посмотреть, что получилось после слияния
```

```yaml
# docker-compose.override.yml (dev)
services:
  app:
    build:
      target: dev
    volumes:
      - ./src:/app/src           # hot reload
    environment:
      DEBUG: "true"
    ports:
      - "8000:8000"              # прямой доступ в обход nginx
```

### Общие блоки через YAML-якоря

```yaml
x-common: &common
  restart: unless-stopped
  logging:
    driver: json-file
    options: { max-size: "10m", max-file: "3" }

services:
  app:
    <<: *common
    image: myapp:1.0
  worker:
    <<: *common
    image: myapp:1.0
    command: ["celery", "worker"]
```

---

## 4. Масштабирование и один процесс на контейнер

```bash
docker compose up -d --scale worker=3       # три экземпляра воркера
docker compose ps
```
> Сервис с фиксированным `ports:` масштабировать нельзя (конфликт портов на хосте).
> Масштабируют то, что стоит за балансировщиком/очередью.

---

## 💼 Как это в DevOps

- **Compose — это инфраструктура как код** для одного хоста: файл в git, ревью, воспроизводимый
  стенд у каждого разработчика и в CI одной командой.
- **Локальная разработка:** `docker compose up` поднимает весь стек зависимостей (БД, кэш,
  очередь, mock-сервисы) без установки чего-либо на ноутбук.
- **CI:** поднять зависимости для интеграционных тестов, прогнать тесты, погасить.
- **Небольшой прод** на одиночном сервере — вполне рабочая схема (compose + systemd-юнит
  + бэкапы + мониторинг). Дальше — Kubernetes, где те же понятия называются Deployment,
  Service, ConfigMap, PVC.
- **Compose ≠ оркестратор:** нет самолечения на нескольких нодах, rolling update, автоскейлинга.

---

## 🧪 Мини-лаба: приложение + БД + кэш + nginx

```bash
mkdir -p ~/docker-lab/09/{app,nginx,static} && cd ~/docker-lab/09

cat > app/app.py <<'PY'
import os, json, psycopg2, redis
from http.server import HTTPServer, BaseHTTPRequestHandler

DB  = os.getenv("DATABASE_URL", "")
RDS = os.getenv("REDIS_URL", "redis://redis:6379/0")
r = redis.Redis.from_url(RDS)

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        hits = r.incr("hits")
        with psycopg2.connect(DB) as c, c.cursor() as cur:
            cur.execute("SELECT version()")
            v = cur.fetchone()[0][:40]
        self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
        self.wfile.write(json.dumps({"hits": hits, "db": v, "ver": os.getenv("APP_VERSION")}).encode())
    def log_message(self, *a): print("REQ", self.path, flush=True)

HTTPServer(("0.0.0.0", 8000), H).serve_forever()
PY

cat > app/requirements.txt <<'EOF'
psycopg2-binary==2.9.9
redis==5.0.8
EOF

cat > app/Dockerfile <<'EOF'
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd -r -u 10001 app
COPY --chown=app:app app.py .
USER app
EXPOSE 8000
CMD ["python", "app.py"]
EOF

cat > nginx/default.conf <<'EOF'
server {
  listen 80;
  location /static/ { alias /usr/share/nginx/html/; }
  location / {
    proxy_pass http://app:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
  }
}
EOF
echo "<h1>статика</h1>" > static/index.html

cat > .env <<'EOF'
DB_PASSWORD=devpassword
APP_VERSION=1.0.0
COMPOSE_PROJECT_NAME=shop
EOF
echo ".env" > .gitignore

cat > docker-compose.yml <<'YML'
x-common: &common
  restart: unless-stopped
  logging:
    driver: json-file
    options: { max-size: "10m", max-file: "3" }

services:
  db:
    <<: *common
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: app
      POSTGRES_USER: app
      POSTGRES_PASSWORD: ${DB_PASSWORD:?нужен DB_PASSWORD}
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d app"]
      interval: 5s
      timeout: 3s
      retries: 5
    networks: [backend]

  redis:
    <<: *common
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes"]
    volumes: [redisdata:/data]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 5
    networks: [backend]

  app:
    <<: *common
    build: ./app
    image: shop-app:${APP_VERSION}
    environment:
      DATABASE_URL: postgresql://app:${DB_PASSWORD}@db:5432/app
      REDIS_URL: redis://redis:6379/0
      APP_VERSION: ${APP_VERSION}
    depends_on:
      db:    { condition: service_healthy }
      redis: { condition: service_healthy }
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"]
      interval: 10s
      retries: 3
      start_period: 10s
    networks: [backend, frontend]
    deploy:
      resources:
        limits: { cpus: "1.0", memory: 512M }

  nginx:
    <<: *common
    image: nginx:alpine
    ports: ["8080:80"]
    volumes:
      - ./nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
      - ./static:/usr/share/nginx/html:ro
    depends_on:
      app: { condition: service_healthy }
    networks: [frontend]

volumes:
  pgdata:
  redisdata:

networks:
  frontend:
  backend:
    internal: true
YML

# --- Запуск
docker compose config >/dev/null && echo "YAML валиден"
docker compose up -d --build
docker compose ps                                   # смотри колонку STATUS: healthy

curl -s localhost:8080 | jq .                       # {"hits":1,...}
curl -s localhost:8080 | jq .hits                   # 2 — redis считает
curl -s localhost:8080/static/

docker compose logs --tail=20 app
docker compose exec db psql -U app -d app -c '\l'
docker compose exec app sh -c 'getent hosts db redis'        # DNS по именам сервисов
docker compose run --rm app python -c "print('разовая задача')"

# --- Данные переживают пересоздание
docker compose exec db psql -U app -d app -c "CREATE TABLE t(x int); INSERT INTO t VALUES (7);"
docker compose down                                  # тома остаются!
docker compose up -d
sleep 10
docker compose exec db psql -U app -d app -c "SELECT * FROM t;"   # 7 ✅

# --- Масштабирование
docker compose up -d --scale app=3 2>&1 | tail -2
docker compose ps

# --- Уборка
docker compose down -v --rmi local
cd ~ && rm -rf ~/docker-lab/09
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `docker compose up -d [--build]` | Поднять всё (с пересборкой) |
| `docker compose down [-v] [--rmi all]` | Снести (⚠️ `-v` удаляет тома) |
| `docker compose ps [-a]` | Статус сервисов |
| `docker compose logs -f [--tail=N] [svc]` | Логи |
| `docker compose exec svc sh` | В работающий контейнер |
| `docker compose run --rm svc cmd` | Разовая задача в новом контейнере |
| `docker compose restart/stop/start [svc]` | Управление |
| `docker compose build [--no-cache]` / `pull` | Сборка / обновление образов |
| `docker compose config [--services]` | Итоговый YAML после подстановок ⭐ |
| `docker compose up -d --scale worker=3` | Масштабирование |
| `docker compose -f a.yml -f b.yml up -d` | Слияние файлов (dev/prod) |
| `docker compose --profile debug up -d` | Профили |
| `docker compose top` / `events` / `cp` | Процессы / события / копирование |

### Мини-справочник YAML

| Ключ | Смысл |
|------|-------|
| `image` / `build` | Готовый образ / сборка (можно оба: собрать и назвать) |
| `ports` | Публикация (`"127.0.0.1:8080:80"`) |
| `expose` | Только документация |
| `environment` / `env_file` | Переменные |
| `volumes` | Тома и bind mount'ы |
| `depends_on` + `condition` | Порядок и ожидание готовности |
| `healthcheck` | Проверка живости |
| `networks` | Сети сервиса |
| `restart` | Политика перезапуска |
| `command` / `entrypoint` | Переопределение из образа |
| `deploy.resources.limits` | CPU/память |
| `profiles` | Опциональные сервисы |
| `logging` | Драйвер и ротация логов |
| `stop_grace_period` | Время на graceful shutdown |

---

## 🧠 Что запомнить

1. `docker compose` (v2) вместо `docker-compose`; ключ `version:` больше не нужен.
2. Compose создаёт **свою сеть**, поэтому сервисы видят друг друга **по именам сервисов**.
3. `depends_on` без `condition: service_healthy` **не ждёт готовности** — только порядок старта.
4. Приложение всё равно должно **уметь переподключаться**: в k8s `depends_on` нет вообще.
5. `down` сохраняет тома, **`down -v` их удаляет** — на проде это потеря данных.
6. `exec` — в работающий контейнер, `run --rm` — новый контейнер для разовой задачи.
7. `.env` рядом с compose-файлом подхватывается автоматически и **не должен попадать в git**.
8. `docker compose config` — первое средство отладки YAML и подстановок.
9. Порты публикуй только у точки входа; БД и кэш — во внутренней сети (`internal: true`).
10. Данные — в named volumes; конфиги — bind mount `:ro`.
11. Разделяй dev/prod через `override`-файлы или `-f a.yml -f b.yml`, а не копией всего файла.
12. Имя проекта (`COMPOSE_PROJECT_NAME` или имя каталога) — префикс контейнеров, сетей и томов;
    переименовал каталог → получил «новый» проект и «потерял» данные.

---

## Задачи

> Лаба: `mkdir -p ~/docker-lab/09 && cd ~/docker-lab/09`
> ⚠️ Помни: `docker compose down -v` удаляет тома вместе с данными.

---

### Блок A. Теория

**A1.** Зачем нужен Docker Compose? Какую проблему он решает?

<details><summary>Ответ</summary>

Описать многоконтейнерное приложение декларативно в одном YAML-файле и управлять всей
связкой одной командой. Заменяет десяток длинных `docker run` + создание сетей и томов,
хранится в git (инфраструктура как код), даёт одинаковый стенд у всех разработчиков и в CI.

</details>

**A2.** Чем `docker compose` (v2) отличается от `docker-compose` (v1)? Нужен ли ключ `version:`?

<details><summary>Ответ</summary>

v1 — отдельная утилита на Python (`docker-compose`, устарела и снята с поддержки);
v2 — плагин к докеру на Go (`docker compose`), быстрее, поддерживает профили, `--wait`,
`service_completed_successfully`, watch. Ключ `version:` в файле не нужен: он игнорируется
(в v2 при его наличии выводится предупреждение).

</details>

**A3.** Как сервисы в compose находят друг друга? Какое имя использовать как хост в конфиге
приложения?

<details><summary>Ответ</summary>

Compose создаёт сеть проекта и регистрирует **имена сервисов** в embedded DNS.
В конфиге приложения хостом указывается имя сервиса: `db`, `redis`, `app`
(например, `postgresql://app:pw@db:5432/app`), а не IP и не `localhost`.

</details>

**A4.** Что создаёт compose при `up`, кроме контейнеров?

<details><summary>Ответ</summary>

Сеть проекта (`<project>_default` или объявленные), named volumes, при необходимости
собирает образы; всем объектам даёт префикс имени проекта и служебные метки
(`com.docker.compose.*`).

</details>

**A5.** Главная ловушка `depends_on`. Как заставить сервис реально дождаться готовности БД?

<details><summary>Ответ</summary>

`depends_on: [db]` задаёт только **порядок запуска контейнеров**, но не ждёт, пока БД
начнёт принимать соединения. Нужно `depends_on: db: { condition: service_healthy }` плюс
корректный `healthcheck` у БД (`pg_isready`).

</details>

**A6.** Почему даже с `condition: service_healthy` приложение должно уметь переподключаться?

<details><summary>Ответ</summary>

Потому что БД может «упасть и подняться» во время работы, сеть — моргнуть, а в
Kubernetes аналога `depends_on` нет вообще: под стартует, когда стартует. Устойчивость к
недоступности зависимостей — свойство приложения (retry с backoff, пул соединений с проверкой).

</details>

**A7.** Разница `docker compose exec` и `docker compose run`. Когда что использовать?

<details><summary>Ответ</summary>

`exec` выполняет команду в **уже работающем** контейнере сервиса (отладка, psql,
shell). `run --rm` создаёт **новый** контейнер по описанию сервиса (миграции, management-команды,
тесты), по умолчанию не публикует порты и не зависит от того, запущен ли сервис.

</details>

**A8.** Что делают `stop`, `down`, `down -v`, `down --rmi all`? Что при этом теряется?

<details><summary>Ответ</summary>

`stop` — остановить контейнеры (всё остальное на месте); `down` — остановить и удалить
контейнеры и сеть проекта, **named volumes остаются**; `down -v` — дополнительно удалить тома
(**потеря данных**); `down --rmi all` — ещё и удалить образы.

</details>

**A9.** Как compose подставляет переменные? Откуда берётся `.env` и что означают
`${VAR:-default}` и `${VAR:?error}`?

<details><summary>Ответ</summary>

Подставляет переменные из окружения shell и из файла `.env`, лежащего рядом с
compose-файлом (или указанного `--env-file`). `${VAR:-default}` — значение по умолчанию, если
переменная пуста/не задана; `${VAR:?сообщение}` — прервать выполнение с ошибкой, если не задана.

</details>

**A10.** Что такое имя проекта в compose, на что оно влияет и как его задать?

<details><summary>Ответ</summary>

Имя проекта — префикс для контейнеров, сетей и томов (`shop_db_1`, `shop_pgdata`).
По умолчанию равно имени каталога; задаётся `COMPOSE_PROJECT_NAME` в `.env`, ключом
`name:` в файле или флагом `-p`. Смена имени проекта = «другой» набор томов и контейнеров.

</details>

**A11.** Как организовать разные конфигурации для dev и prod? Два способа.

<details><summary>Ответ</summary>

(1) `docker-compose.yml` + `docker-compose.override.yml` (подхватывается
автоматически, обычно dev) и явный `-f docker-compose.yml -f docker-compose.prod.yml` для прода.
(2) Профили + переменные окружения. Проверять результат — `docker compose config`.

</details>

**A12.** Что такое профили (`profiles`) и когда они полезны?

<details><summary>Ответ</summary>

Метки на сервисах, позволяющие держать в одном файле опциональные компоненты
(отладочные утилиты, мониторинг, сиды данных) и поднимать их только с `--profile`.
По умолчанию сервисы с профилем не запускаются.

</details>

**A13.** Зачем нужны YAML-якоря (`x-common: &common`)?

<details><summary>Ответ</summary>

Чтобы не дублировать одинаковые блоки (restart, logging, переменные, лимиты) в каждом
сервисе: объявляется якорь `x-common: &common` и подмешивается через `<<: *common`.
Ключи с префиксом `x-` игнорируются compose как расширения.

</details>

**A14.** Как ограничить ресурсы сервиса в compose?

<details><summary>Ответ</summary>

`deploy.resources.limits.cpus/memory` (в v2 работает и вне Swarm) либо
`cpus:`/`mem_limit:` (legacy-ключи). Плюс `pids_limit`, `ulimits`.

</details>

**A15.** Почему сервис с `ports:` нельзя отмасштабировать через `--scale`?

<details><summary>Ответ</summary>

Потому что каждый экземпляр пытался бы занять **тот же порт хоста** — конфликт.
Масштабируют сервисы без публикации портов, стоящие за reverse proxy или читающие из очереди;
либо публикуют диапазон портов.

</details>

**A16.** Compose — это оркестратор? Чего в нём нет по сравнению с Kubernetes?

<details><summary>Ответ</summary>

Нет. Compose — инструмент для **одного хоста**: нет распределения по нодам,
самолечения при падении ноды, rolling update с контролем готовности, автоскейлинга,
декларативной сверки состояния, секретов и RBAC уровня кластера. Это его назначение —
разработка, CI и небольшой одиночный прод.

</details>

**A17.** Где в compose объявлять сети и как сделать сеть без выхода в интернет?

<details><summary>Ответ</summary>

В верхнеуровневой секции `networks:`; сервис подключается через `networks: [name]`.
Сеть без интернета — `internal: true`. Внешнюю (созданную вне проекта) подключают через
`external: true`.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  docker compose up -d --build
B2.  docker compose up -d app
B3.  docker compose down -v
B4.  docker compose logs -f --tail=100 app
B5.  docker compose exec app sh
B6.  docker compose run --rm app python manage.py migrate
B7.  docker compose config
B8.  docker compose config --services
B9.  docker compose ps -a
B10. docker compose up -d --scale worker=3
B11. docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
B12. docker compose --profile debug up -d
B13. docker compose kill -s HUP nginx
B14. docker compose pull && docker compose up -d
B15. docker compose restart app
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Пересобрать образы и поднять весь стек в фоне.
B2.  Поднять только сервис app и то, от чего он зависит.
B3.  Снести контейнеры, сеть и тома (данные будут потеряны).
B4.  Следить за логами сервиса app, начиная с последних 100 строк.
B5.  Открыть shell в работающем контейнере app.
B6.  Запустить миграции в новом одноразовом контейнере того же сервиса.
B7.  Показать итоговую конфигурацию после слияния файлов и подстановки переменных.
B8.  Вывести список имён сервисов (удобно для скриптов).
B9.  Статус всех сервисов, включая остановленные.
B10. Поднять три экземпляра сервиса worker.
B11. Слить базовый и прод-файл и поднять стек по итоговой конфигурации.
B12. Поднять стек вместе с сервисами профиля debug.
B13. Послать SIGHUP сервису nginx (перечитать конфиг без остановки).
B14. Обновить образы из registry и перезапустить изменившиеся сервисы.
B15. Перезапустить один сервис (без пересоздания контейнера).
```

</details>

**B16.** Что произойдёт с данными при `docker compose down`, а что при `docker compose down -v`?

<details><summary>Ответ</summary>

`down` — контейнеры и сеть удаляются, **named volumes сохраняются**, поэтому после
`up` данные на месте. `down -v` — тома проекта удаляются вместе с данными БД, восстановление
возможно только из бэкапа.

</details>

---

### Блок C. Практика

#### C1. 🔑 Приложение + БД + кэш + nginx (главное задание из роадмапа)

Собери стек из четырёх сервисов:

- **db** — PostgreSQL с named volume, healthcheck (`pg_isready`), пароль из `.env`;
- **redis** — с персистентностью (`appendonly`) и healthcheck;
- **app** — твоё приложение (собирается из Dockerfile), ходит в БД и Redis
  по именам сервисов, имеет `/health`, ждёт готовности db и redis;
- **nginx** — проксирует на app, отдаёт статику, **единственный** с опубликованным портом.

Требования:
1. Две сети: `frontend` и `backend` (`internal: true`), db и redis — только в backend.
2. У app лимиты CPU/памяти и ротация логов.
3. `restart: unless-stopped` у всех.
4. `.env` с паролем и версией, `.env.example` в git, `.env` — в `.gitignore`.
5. Все сервисы должны быть `healthy` в `docker compose ps`.

**Критерии приёмки:**
- `docker compose up -d --build` поднимает всё одной командой;
- `curl localhost:8080` отдаёт ответ приложения с данными из БД и счётчиком из Redis;
- `docker compose down && docker compose up -d` — данные в БД сохранились;
- `docker compose exec nginx ping db` — **не** работает (изоляция сетей);
- в `docker compose ps` у db, redis и app статус `(healthy)`.

<details><summary>Ответ</summary>

Полностью рабочий пример — см. мини-лабу выше в этом же конспекте. Ключевые проверки приёмки:

```bash
docker compose up -d --build
docker compose ps                       # у db/redis/app — (healthy)
curl -s localhost:8080 | jq .
docker compose exec nginx ping -c1 -W1 db 2>&1 | head -1     # bad address → изоляция ✅
docker compose exec db psql -U app -d app -c "CREATE TABLE t(x int); INSERT INTO t VALUES (7);"
docker compose down && docker compose up -d && sleep 10
docker compose exec db psql -U app -d app -c "SELECT * FROM t;"   # 7 ✅
```

</details>

#### C2. depends_on и гонка при старте

1. Сделай compose, где app подключается к БД **без** healthcheck и с `depends_on: [db]`.
   Поймай падение app с `connection refused` (подсказка: замедли старт БД или уменьши
   таймаут подключения).
2. Добавь healthcheck и `condition: service_healthy` — покажи, что гонка исчезла.
3. Добавь в приложение retry-логику и покажи, что оно выживает даже без healthcheck.
4. Объясни, зачем нужны оба уровня защиты.

<details><summary>Ответ</summary>

```bash
mkdir -p ~/docker-lab/09c2 && cd ~/docker-lab/09c2
cat > wait.py <<'PY'
import os, sys, time, socket
host, port = "db", 5432
deadline = time.time() + float(os.getenv("RETRY_SECONDS", "0"))
while True:
    try:
        socket.create_connection((host, port), timeout=1); print("подключились к БД"); sys.exit(0)
    except OSError as e:
        if time.time() > deadline:
            print("connection refused:", e); sys.exit(1)
        print("жду БД..."); time.sleep(1)
PY
cat > docker-compose.yml <<'YML'
services:
  db:
    image: postgres:16-alpine
    environment: { POSTGRES_PASSWORD: pw }
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 3s
      retries: 10
  app:
    image: python:3.12-alpine
    volumes: [./wait.py:/wait.py:ro]
    command: ["python", "/wait.py"]
    depends_on: [db]          # ← без condition: гонка
YML
docker compose up --abort-on-container-exit 2>&1 | grep -E "refused|подключились"
# app падает раньше, чем БД успевает подняться

sed -i 's/depends_on: \[db\]/depends_on:\n      db: { condition: service_healthy }/' docker-compose.yml
docker compose up --abort-on-container-exit 2>&1 | grep -E "refused|подключились"   # ✅

# retry в приложении (работает даже без healthcheck):
docker compose run --rm -e RETRY_SECONDS=30 app
# Оба уровня нужны: healthcheck решает проблему ХОЛОДНОГО старта,
# retry — проблему падений и сетевых сбоев В РАБОТЕ (и в k8s, где depends_on нет).
```

</details>

#### C3. Миграции как отдельный шаг

Добавь сервис `migrate`, который:
- использует тот же образ, что и `app`;
- выполняет «миграцию» (создание таблицы) и завершается с кодом 0;
- запускается **после** healthy-БД;
- а `app` стартует только после **успешного завершения** миграции
  (`condition: service_completed_successfully`).

<details><summary>Ответ</summary>

```bash
cat > docker-compose.migrate.yml <<'YML'
services:
  db:
    image: postgres:16-alpine
    environment: { POSTGRES_PASSWORD: pw, POSTGRES_DB: app, POSTGRES_USER: app }
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d app"]
      interval: 3s
      retries: 10
  migrate:
    image: postgres:16-alpine
    environment: { PGPASSWORD: pw }
    command: ["psql","-h","db","-U","app","-d","app","-c","CREATE TABLE IF NOT EXISTS users(id serial);"]
    depends_on:
      db: { condition: service_healthy }
  app:
    image: postgres:16-alpine
    environment: { PGPASSWORD: pw }
    command: ["psql","-h","db","-U","app","-d","app","-c","\\dt"]
    depends_on:
      migrate: { condition: service_completed_successfully }
YML
docker compose -f docker-compose.migrate.yml up --abort-on-container-exit
docker compose -f docker-compose.migrate.yml down -v
```

</details>

#### C4. dev и prod конфигурации

1. Базовый `docker-compose.yml` (общее).
2. `docker-compose.override.yml` — dev: bind mount исходников, `DEBUG=true`,
   проброс порта app напрямую, target `dev`.
3. `docker-compose.prod.yml` — prod: без bind mount, лимиты ресурсов, `restart: always`.
4. Покажи разницу через `docker compose config` для обоих вариантов.

<details><summary>Ответ</summary>

```bash
cat > docker-compose.yml <<'YML'
services:
  app:
    image: nginx:alpine
    networks: [net]
networks: { net: {} }
YML
cat > docker-compose.override.yml <<'YML'
services:
  app:
    environment: { DEBUG: "true" }
    ports: ["8000:80"]
    volumes: ["./static:/usr/share/nginx/html:ro"]
YML
cat > docker-compose.prod.yml <<'YML'
services:
  app:
    restart: always
    deploy:
      resources:
        limits: { cpus: "1.0", memory: 256M }
YML
mkdir -p static && echo hi > static/index.html
docker compose config | head -30                                        # dev (override авто)
docker compose -f docker-compose.yml -f docker-compose.prod.yml config   # prod
```

</details>

#### C5. Профили

Добавь профиль `debug` с контейнером `netshoot` и профиль `monitoring` с чем-нибудь ещё.
Покажи, что по умолчанию они не поднимаются, а с `--profile` — поднимаются.

<details><summary>Ответ</summary>

```bash
cat >> docker-compose.yml <<'YML'
  netshoot:
    image: nicolaka/netshoot
    command: sleep infinity
    profiles: [debug]
    networks: [net]
YML
docker compose up -d && docker compose ps            # netshoot нет
docker compose --profile debug up -d && docker compose ps   # есть
docker compose --profile debug down
```

</details>

#### C6. Масштабирование

1. Добавь сервис `worker` (например, бесконечный цикл, пишущий в Redis).
2. Подними 3 экземпляра.
3. Покажи имена контейнеров и что все они видят Redis по имени.
4. Попробуй отмасштабировать сервис с `ports:` — объясни ошибку.

<details><summary>Ответ</summary>

```bash
cat > docker-compose.scale.yml <<'YML'
services:
  redis:
    image: redis:7-alpine
  worker:
    image: redis:7-alpine
    command: ["sh","-c","while :; do redis-cli -h redis incr jobs >/dev/null; sleep 2; done"]
    depends_on: [redis]
  web:
    image: nginx:alpine
    ports: ["8080:80"]
YML
docker compose -f docker-compose.scale.yml up -d --scale worker=3
docker compose -f docker-compose.scale.yml ps
docker compose -f docker-compose.scale.yml exec redis redis-cli get jobs
docker compose -f docker-compose.scale.yml up -d --scale web=2 2>&1 | tail -2   # ошибка порта
docker compose -f docker-compose.scale.yml down
```

</details>

#### C7. Данные и бэкап в compose-проекте

1. Залей в БД тестовые данные.
2. Сделай `docker compose down` — проверь, что данные на месте после `up`.
3. Сделай бэкап тома проекта в архив (не удаляя стек).
4. Сделай `docker compose down -v`, восстанови данные из бэкапа и подними стек заново.

<details><summary>Ответ</summary>

```bash
# (в проекте из C1)
docker compose exec db psql -U app -d app -c "INSERT INTO t VALUES (99);"
docker compose down && docker compose up -d && sleep 10
docker compose exec db psql -U app -d app -c "SELECT * FROM t;"
VOL=$(docker volume ls -q | grep pgdata | head -1)
docker run --rm -v "$VOL":/data:ro -v "$PWD":/b alpine tar czf /b/pgdata.tgz -C /data .
docker compose down -v
docker compose up -d --no-start
VOL=$(docker volume ls -q | grep pgdata | head -1)
docker run --rm -v "$VOL":/data -v "$PWD":/b alpine tar xzf /b/pgdata.tgz -C /data
docker compose up -d && sleep 10
docker compose exec db psql -U app -d app -c "SELECT * FROM t;"    # данные вернулись
```

</details>

#### C8. Отладка YAML

Специально сломай файл тремя способами (неверный отступ, несуществующая переменная
с `:?`, ссылка на несуществующую сеть) и покажи, как `docker compose config` помогает
найти каждую ошибку.

<details><summary>Ответ</summary>

```bash
printf 'services:\n  app:\n  image: nginx\n' > broken1.yml
docker compose -f broken1.yml config 2>&1 | head -3      # ошибка структуры/отступа
printf 'services:\n  app:\n    image: nginx\n    environment:\n      K: ${MUST_BE_SET:?не задана}\n' > broken2.yml
docker compose -f broken2.yml config 2>&1 | head -3      # required variable is missing
printf 'services:\n  app:\n    image: nginx\n    networks: [nope]\n' > broken3.yml
docker compose -f broken3.yml config 2>&1 | head -3      # undefined network
cd ~ && rm -rf ~/docker-lab/09c2
```

</details>

---

### Блок D. Инциденты

**D1.** `docker compose up` — app падает с `could not translate host name "db"`.
Что проверить? (Четыре варианта.)

<details><summary>Ответ</summary>

(1) Сервис называется иначе, чем указано в конфиге (обращение к имени контейнера
вместо имени сервиса); (2) сервисы в разных сетях (у db только `backend`, у app только
`frontend`); (3) сервис db не запустился (`docker compose ps`, логи) — имя не резолвится;
(4) в конфиге приложения `localhost` вместо `db`; (5) опечатка/переменная окружения не
подставилась — проверить `docker compose config`.

</details>

**D2.** После переименования каталога проекта `docker compose up -d` поднял пустую базу,
хотя данные были. Что произошло?

<details><summary>Ответ</summary>

Имя проекта по умолчанию = имя каталога; при переименовании compose считает это
**новым проектом** и создаёт новые тома (`newdir_pgdata` вместо `olddir_pgdata`).
Данные не пропали — они в старом томе. Решение: задать `COMPOSE_PROJECT_NAME` в `.env`
(или `name:` в файле) и не зависеть от имени каталога; данные перенести из старого тома.

</details>

**D3.** Коллега выполнил `docker compose down -v` на проде «чтобы перезапустить».
Что случилось и что делать? Как не допустить повторения?

<details><summary>Ответ</summary>

Удалены тома проекта: база и всё её содержимое. Действия: остановить запись,
восстановить из последнего бэкапа (`pg_dump`/снапшот), проверить целостность, оформить
инцидент. Профилактика: запретить `-v` в рантбуках и алиасах, ограничить доступ к прод-серверу,
регулярные проверенные бэкапы, вынести БД из compose в managed-сервис или отдельный
сервер, `external: true` для прод-томов (тогда `down -v` их не тронет).

</details>

**D4.** В compose прописан `image: myapp:latest`. После `docker compose up -d`
изменения кода не появились. Три причины.

<details><summary>Ответ</summary>

(1) Образ не пересобран: нужен `--build` или отдельный `docker compose build`;
(2) тег `latest` уже есть локально и не перекачивается — compose не тянет новый образ
(нужен `docker compose pull` или уникальный тег); (3) контейнер не был пересоздан
(`up -d` без изменений конфигурации ничего не делает — помогает
`up -d --force-recreate`); (4) код подключён bind mount'ом, а приложение не перезапущено.

</details>

**D5.** `docker compose up` работает локально, но в CI падает: `.env: no such file`.
Как правильно организовать переменные?

<details><summary>Ответ</summary>

`.env` в git не хранят. В CI переменные приходят из секретов CI как переменные
окружения (compose подхватит их автоматически), либо файл генерируется на лету из секрета,
либо используется `--env-file` с путём к сгенерированному файлу. В репозитории —
`.env.example` со списком ключей без значений.

</details>

**D6.** Приложение стартует раньше БД, падает, но `restart: unless-stopped` его поднимает,
и в итоге «всё работает». Почему это плохое решение?

<details><summary>Ответ</summary>

Работает «по счастливой случайности»: стек стартует дольше, в логах постоянные
падения, при медленной БД цикл может не сойтись, а `restart` маскирует реальные проблемы
(в том числе ошибки конфигурации). Правильно — healthcheck + `condition: service_healthy`
и retry-логика в приложении; рестарт остаётся как защита от редких сбоев, а не как механизм старта.

</details>

**D7.** `docker compose ps` показывает сервис `app` как `unhealthy`, но `curl` изнутри
контейнера работает. Что проверить?

<details><summary>Ответ</summary>

Проверить сам healthcheck: (1) команда использует утилиту, которой нет в образе
(`curl` в slim/alpine); (2) проверка ходит на неверный порт/адрес (должен быть
`127.0.0.1:<внутренний порт>`); (3) слишком маленький `start_period`/`timeout`;
(4) healthcheck выполняется от `USER` без прав. Смотреть:
<code v-pre>docker inspect &lt;c&gt; --format '{{json .State.Health}}' | jq .</code> — там вывод последних проверок.

</details>

**D8.** Два compose-проекта на одном сервере конфликтуют: второй не поднимается
(`port is already allocated`). Варианты решения.

<details><summary>Ответ</summary>

Один и тот же порт хоста занят двумя проектами. Решения: сменить порт во втором
проекте (лучше — через переменную в `.env`: `ports: ["${HTTP_PORT:-8080}:80"]`),
публиковать на разных адресах (`127.0.0.1:8081:80`), поставить общий reverse proxy
(Traefik/nginx) и не публиковать порты каждого проекта, разнести проекты по разным хостам.

</details>

**D9.** В проде на compose при деплое приложение недоступно 30 секунд. Как уменьшить простой
средствами compose (и где предел этого подхода)?

<details><summary>Ответ</summary>

Уменьшить: healthcheck + `depends_on`, `stop_grace_period` и graceful shutdown,
предварительный `docker compose pull` (чтобы образ уже был на месте), запуск новой
версии рядом и переключение nginx (blue/green вручную), `--no-deps` для точечного
обновления сервиса. Предел: compose пересоздаёт контейнер «на месте» и не умеет
rolling update с контролем готовности — для нулевого простоя нужен Swarm/Kubernetes
или внешний балансировщик с двумя стеками.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое Docker Compose и зачем он нужен?

<details><summary>Ответ</summary>

Инструмент декларативного описания многоконтейнерного приложения в YAML и управления им
одной командой; заменяет набор `docker run`, хранится в git.

</details>

**2.** Как сервисы в compose общаются между собой?

<details><summary>Ответ</summary>

По именам сервисов через встроенный DNS в общей сети проекта.

</details>

**3.** Что делает `depends_on` и что он НЕ делает?

<details><summary>Ответ</summary>

Задаёт порядок запуска и (с `condition: service_healthy`) ожидание готовности;
сам по себе он **не** ждёт, пока сервис начнёт принимать соединения.

</details>

**4.** Чем `down` отличается от `down -v` и от `stop`?

<details><summary>Ответ</summary>

`stop` — остановить; `down` — удалить контейнеры и сеть, тома оставить;
`down -v` — удалить и тома (данные).

</details>

**5.** Как передавать секреты в compose?

<details><summary>Ответ</summary>

Через переменные окружения из секрет-хранилища CI/окружения, `env_file`,
docker secrets (в Swarm). Секреты не коммитят: `.env` в `.gitignore`, в репо — `.env.example`.

</details>

**6.** Как разделить конфигурации dev и prod?

<details><summary>Ответ</summary>

Базовый файл + `override` (dev, автоматически) и отдельный prod-файл через `-f … -f …`;
проверка результата через `docker compose config`.

</details>

**7.** Чем `exec` отличается от `run`?

<details><summary>Ответ</summary>

`exec` — в работающем контейнере; `run --rm` — новый одноразовый контейнер по описанию сервиса.

</details>

**8.** Можно ли использовать compose в проде? Какие ограничения?

<details><summary>Ответ</summary>

Можно на одиночном сервере (плюс systemd-юнит, бэкапы, мониторинг). Ограничения:
один хост, нет rolling update и самолечения на уровне кластера, нет автоскейлинга.

</details>

**9.** Как масштабировать сервис в compose?

<details><summary>Ответ</summary>

`docker compose up -d --scale svc=N`; масштабируемый сервис не должен публиковать
фиксированный порт.

</details>

**10.** Чем compose отличается от Kubernetes?

<details><summary>Ответ</summary>

Compose — один хост и простое описание стека; Kubernetes — распределённый кластер,
декларативная сверка состояния, самолечение, rolling update, автоскейлинг, сервисы,
ingress, RBAC, секреты и storage-абстракции.

</details>

---

### 🎯 Чек-лист

- [ ] Поднял стек из 4 сервисов одной командой
- [ ] Использую `condition: service_healthy`, а не голый `depends_on`
- [ ] Публикую порт только у точки входа, БД — во внутренней сети
- [ ] Данные в named volumes и я проверил, что они переживают `down`/`up`
- [ ] Знаю разницу `down` и `down -v` и никогда не путаю их на проде
- [ ] `.env` в `.gitignore`, в репозитории — `.env.example`
- [ ] Развёл dev и prod конфигурации через override-файлы
- [ ] Отлаживаю YAML через `docker compose config`
- [ ] Понимаю границы compose и что дальше — Kubernetes
