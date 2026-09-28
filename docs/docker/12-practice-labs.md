---
title: "12. Практика: лабы"
description: "Контейнеризация своего приложения, docker compose, мониторинг-стек Prometheus+Grafana, nginx со своим конфигом, свободные эксперименты"
---

# 12. Практика: 5 лаб из роадмапа

> Роадмап → 3. Docker → **2. Практика**
> «Тут самое главное — **КАЖДУЮ непонятную вещь разбирать**.»
>
> Это не задачник с ответами, а список работ, которые надо **сделать руками** и оставить
> в git. После них у тебя есть готовые артефакты для резюме и материал для собеса.

---

## 📋 Список лаб

| № | Лаба | Что закрепляет | Артефакт |
|---|------|----------------|----------|
| 1 | Приложение из Linux-практики → в контейнеры | темы 03, 04, 06, 10 | `Dockerfile` + образ в registry |
| 2 | То же приложение → в docker compose | темы 07, 08, 09 | `docker-compose.yml` |
| 3 | Мониторинг-стек Prometheus + Grafana + Node Exporter (+ cAdvisor) | тема 09 + знакомство с мониторингом | compose + дашборд |
| 4 | nginx со своим конфигом, статикой и пробросом портов | темы 07, 08 | `nginx.conf` + compose |
| 5 | Свободные эксперименты | всё сразу | список «что я сломал и починил» |

**Правило всех лаб:** каждую строчку, которую ты не понимаешь, — разбирать до конца.
Не «работает — и ладно», а «работает, и я могу объяснить почему».

---

## 🧪 Лаба 1. Завернуть приложение в контейнер

> Роадмап: «Взять приложение, которое осталось после практики в линуксе → обернуть его
> в контейнеры → поднять и проверить, что приложение работает корректно.»

### Что делаем
Берём приложение из Linux-блока (systemd-сервис, скрипт, простой веб-сервер — что осталось)
и превращаем в контейнеризованное.

Если ничего не осталось — подойдёт любое минимальное HTTP-приложение (пример ниже).

### Требования
- [ ] Свой `Dockerfile` (не скопированный), каждая строка объяснима
- [ ] Базовый образ с явным тегом, не `latest`
- [ ] Multi-stage (если язык компилируемый или есть сборочные зависимости)
- [ ] `.dockerignore`
- [ ] Зависимости копируются до кода (кэш работает)
- [ ] `USER` — не root
- [ ] `HEALTHCHECK`
- [ ] exec-форма `ENTRYPOINT`/`CMD`, `docker stop` за < 3 секунд с кодом 0
- [ ] Лимиты при запуске (`--memory`, `--cpus`)
- [ ] Логи идут в stdout и видны в `docker logs`
- [ ] Конфигурация — через переменные окружения, не зашита в образ
- [ ] Образ запушен в registry (Docker Hub / GHCR / локальный `registry:2`) с нормальными тегами

### Каркас приложения (если своего нет)

```bash
mkdir -p ~/docker-practice/lab1 && cd ~/docker-practice/lab1
cat > app.py <<'PY'
import os, json, signal, sys, time
from http.server import HTTPServer, BaseHTTPRequestHandler

VERSION = os.getenv("APP_VERSION", "dev")
GREETING = os.getenv("GREETING", "hello")
START = time.time()

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok"); return
        body = json.dumps({
            "greeting": GREETING, "version": VERSION,
            "host": os.uname().nodename, "uptime": round(time.time()-START, 1),
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(body)
    def log_message(self, fmt, *a): print("REQ", self.path, flush=True)

def shutdown(sig, frm):
    print("graceful shutdown", flush=True); sys.exit(0)

signal.signal(signal.SIGTERM, shutdown)
print(f"start version={VERSION}", flush=True)
HTTPServer(("0.0.0.0", 8000), H).serve_forever()
PY
```

### Проверка (критерии приёмки)

```bash
docker build --build-arg APP_VERSION=1.0.0 -t myapp:1.0.0 .
docker run -d --name app -p 8080:8000 --memory=256m --cpus=0.5 \
  -e GREETING="привет" -e APP_VERSION=1.0.0 myapp:1.0.0

curl -s localhost:8080 | jq .                     # ответ с версией
docker exec app id                                # НЕ root
docker ps --filter name=app --format '{{.Status}}' # (healthy)
time docker stop app                              # < 3 сек
docker inspect app --format '{{.State.ExitCode}}' # 0
docker logs app | tail -3                         # graceful shutdown
docker images myapp:1.0.0 --format '{{.Size}}'    # запиши размер
docker history myapp:1.0.0                        # объясни каждый слой
```

### Вопросы себе после лабы
1. Почему у меня именно такой порядок инструкций?
2. Что произойдёт, если поменять одну строчку кода — что пересоберётся?
3. Где в образе хранится конфигурация и почему не в файле?
4. Что будет, если убрать `USER app`?
5. Куда денутся данные, если приложение начнёт что-то писать на диск?

---

## 🧪 Лаба 2. То же приложение в docker compose

> Роадмап: «Всё то же приложение засунуть в docker compose. Проверить, что контейнеры
> работают, всё работает корректно.»

### Что делаем
Добавляем к приложению реальное окружение: БД, кэш, reverse proxy — и описываем всё в compose.

### Требования
- [ ] 3-4 сервиса: `app`, `db` (PostgreSQL), `redis`, `nginx`
- [ ] Приложение реально ходит в БД и Redis (хотя бы счётчик посещений + запрос версии БД)
- [ ] Две сети: `frontend` и `backend` (`internal: true`)
- [ ] Порт наружу **только** у nginx
- [ ] Named volumes для данных БД и Redis
- [ ] Healthcheck у всех сервисов, `depends_on` с `condition: service_healthy`
- [ ] `.env` с секретами (в `.gitignore`), `.env.example` в репозитории
- [ ] Лимиты ресурсов и ротация логов
- [ ] `restart: unless-stopped`

### Критерии приёмки

```bash
docker compose up -d --build
docker compose ps                      # все сервисы healthy
curl -s localhost:8080 | jq .          # ответ с данными из БД и счётчиком из Redis

# данные переживают пересоздание
docker compose exec db psql -U app -d app -c "CREATE TABLE t(x int); INSERT INTO t VALUES(1);"
docker compose down && docker compose up -d && sleep 10
docker compose exec db psql -U app -d app -c "SELECT * FROM t;"     # ✅

# изоляция
docker compose exec nginx ping -c1 -W1 db      # ❌ не должен видеть
docker compose exec db ping -c1 -W1 8.8.8.8    # ❌ internal-сеть

# порты
docker compose ps --format 'table {{.Name}}\t{{.Ports}}'   # только nginx наружу
```

Готовый рабочий пример — в [09. Docker Compose](/docker/09-compose), раздел «Мини-лаба».
**Не копируй бездумно**: собери свой и объясни каждую секцию.

### Вопросы себе
1. Что произойдёт, если убрать `condition: service_healthy`?
2. Чем `docker compose down` отличается от `down -v` — и что случится с данными?
3. Как приложение находит БД? Что будет, если написать `localhost`?
4. Почему БД в сети с `internal: true`?
5. Как обновить только один сервис, не трогая остальные?

---

## 🧪 Лаба 3. Мониторинг-стек: Prometheus + Grafana + Node Exporter + cAdvisor

> Роадмап: «Три сервиса в compose, Prometheus собирает метрики с Node Exporter, Grafana рисует
> дашборды. Одновременно учит Docker Compose и знакомит с мониторингом.
> Можно добавить cAdvisor для метрик самих контейнеров.»

### Схема

```text:no-line-numbers
   ┌──────────────┐  scrape :9100   ┌──────────────┐
   │ node-exporter├────────────────►│              │
   └──────────────┘                 │  Prometheus  │  :9090
   ┌──────────────┐  scrape :8080   │  (TSDB +     │
   │   cAdvisor   ├────────────────►│   scraper)   │
   └──────────────┘                 └──────┬───────┘
   ┌──────────────┐  scrape /metrics       │ PromQL
   │  твоё app    ├────────────────────────┤
   └──────────────┘                        ▼
                                   ┌──────────────┐
                                   │   Grafana    │  :3000  ← дашборды
                                   └──────────────┘
```

| Компонент | Роль |
|-----------|------|
| **Prometheus** | Опрашивает (scrape) цели по HTTP, хранит временные ряды, даёт язык запросов PromQL |
| **Node Exporter** | Отдаёт метрики **хоста**: CPU, память, диск, сеть, файловые системы |
| **cAdvisor** | Отдаёт метрики **контейнеров**: CPU/RAM/сеть/IO по каждому |
| **Grafana** | Рисует дашборды поверх Prometheus |

### Файлы

```bash
mkdir -p ~/docker-practice/lab3/prometheus && cd ~/docker-practice/lab3

cat > prometheus/prometheus.yml <<'YML'
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: prometheus
    static_configs:
      - targets: ['localhost:9090']

  - job_name: node
    static_configs:
      - targets: ['node-exporter:9100']

  - job_name: cadvisor
    static_configs:
      - targets: ['cadvisor:8080']
YML

cat > docker-compose.yml <<'YML'
services:
  prometheus:
    image: prom/prometheus:v2.54.1
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=7d'
      - '--web.enable-lifecycle'                # POST /-/reload без рестарта
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - promdata:/prometheus
    ports: ["9090:9090"]
    networks: [monitoring]
    restart: unless-stopped

  node-exporter:
    image: prom/node-exporter:v1.8.2
    command:
      - '--path.rootfs=/host'
    pid: host                                   # видеть процессы хоста
    volumes:
      - /:/host:ro,rslave                       # только чтение
    networks: [monitoring]
    restart: unless-stopped

  cadvisor:
    image: gcr.io/cadvisor/cadvisor:v0.49.1
    privileged: true                            # ⚠️ требование cAdvisor, см. разбор ниже
    devices: ["/dev/kmsg"]
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    networks: [monitoring]
    restart: unless-stopped

  grafana:
    image: grafana/grafana:11.2.0
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD:-admin}
      GF_USERS_ALLOW_SIGN_UP: "false"
    volumes:
      - grafanadata:/var/lib/grafana
    ports: ["3000:3000"]
    depends_on: [prometheus]
    networks: [monitoring]
    restart: unless-stopped

volumes:
  promdata:
  grafanadata:

networks:
  monitoring:
YML

echo "GRAFANA_PASSWORD=admin123" > .env
echo ".env" > .gitignore
docker compose up -d
```

### Что сделать

1. Открой **Prometheus** `http://localhost:9090` → *Status → Targets*: все цели должны быть `UP`.
   Если нет — это отличная тренировка темы 11 (сеть, имена сервисов, порты).
2. Выполни запросы в Prometheus (вкладка Graph):
   ```text:no-line-numbers
   up                                                   # какие цели живы
   node_memory_MemAvailable_bytes / 1024/1024/1024       # свободная память хоста, ГБ
   100 - (avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)   # CPU %
   node_filesystem_avail_bytes{mountpoint="/"} / 1e9     # свободно на /
   rate(container_cpu_usage_seconds_total{name!=""}[5m]) # CPU по контейнерам
   container_memory_usage_bytes{name!=""} / 1024/1024    # память контейнеров, МБ
   ```
3. Открой **Grafana** `http://localhost:3000` (admin / пароль из `.env`):
   - добавь Data source → Prometheus → URL `http://prometheus:9090`
     (⭐ именно имя сервиса, не localhost — разбери, почему);
   - импортируй готовые дашборды по ID: **1860** (Node Exporter Full),
     **193** или **14282** (Docker/cAdvisor);
   - собери **свой** дашборд минимум с 4 панелями: CPU хоста, память хоста,
     память по контейнерам, свободное место на диске.
4. Подключи к мониторингу **своё приложение** из лабы 1-2: добавь эндпоинт `/metrics`
   (например, через `prometheus_client` для Python) и job в `prometheus.yml`.
5. Перезагрузи конфиг Prometheus без рестарта:
   `curl -X POST http://localhost:9090/-/reload`.
6. Нагрузи систему (`docker run --rm -it progrium/stress --cpu 2 --timeout 60s`)
   и посмотри, как это отражается на графиках.

### ⚠️ Обязательно разобрать (то самое «разбирать каждую непонятную вещь»)

- Почему у `node-exporter` монтируется `/:/host:ro` и стоит `pid: host`?
  Что он из этого читает?
- Почему cAdvisor требует `privileged` и доступ к `/var/lib/docker`?
  Как это соотносится с темой 10 и что можно ограничить?
- Почему Grafana подключается к `http://prometheus:9090`, а не к `localhost:9090`?
- Что произойдёт с данными Prometheus при `docker compose down`? А при `down -v`?
- Зачем `--storage.tsdb.retention.time` и что будет без него через месяц?
- Почему порты 9090 и 3000 в реальном проде **не** публикуют наружу?

### Критерии приёмки
- [ ] Все targets `UP`
- [ ] Свой дашборд с 4+ панелями сохранён (экспортируй JSON в репозиторий)
- [ ] Данные Prometheus и Grafana переживают `docker compose down && up`
- [ ] Метрики своего приложения видны в Prometheus
- [ ] Можешь объяснить каждую строку compose-файла

---

## 🧪 Лаба 4. nginx: свой конфиг, статика, порты

> Роадмап: «Но не просто `docker run nginx`, а примонтировать свой `nginx.conf` через
> bind mount, отдавать свою статику, настроить проброс портов.»

### Что делаем

```bash
mkdir -p ~/docker-practice/lab4/{conf,html} && cd ~/docker-practice/lab4

cat > html/index.html <<'EOF'
<!doctype html><meta charset="utf-8"><title>Моя статика</title>
<h1>Статика из bind mount</h1><p>Правь этот файл на хосте — обновление мгновенное.</p>
EOF

cat > conf/default.conf <<'EOF'
server {
    listen 80;
    server_name _;

    access_log /dev/stdout;
    error_log  /dev/stderr warn;

    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }

    location /health {
        access_log off;
        return 200 "ok\n";
        add_header Content-Type text/plain;
    }

    # проксирование на приложение из лабы 1
    location /api/ {
        proxy_pass http://app:8000/;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # кэширование статики
    location ~* \.(css|js|png|jpg|svg|woff2)$ {
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    gzip on;
    gzip_types text/plain text/css application/json application/javascript;
}
EOF

docker network create lab4-net
docker run -d --name app --network lab4-net myapp:1.0.0 2>/dev/null || \
  docker run -d --name app --network lab4-net python:3.12-alpine \
    sh -c 'echo "{\"api\":\"ok\"}" > index.html; python -m http.server 8000 --bind 0.0.0.0'

docker run -d --name web --network lab4-net -p 8080:80 \
  -v "$PWD/conf/default.conf:/etc/nginx/conf.d/default.conf:ro" \
  -v "$PWD/html:/usr/share/nginx/html:ro" \
  nginx:alpine
```

### Что проверить и разобрать

```bash
curl -s localhost:8080/          # своя статика
curl -s localhost:8080/health    # ok
curl -s localhost:8080/api/      # ответ приложения через прокси
curl -sI localhost:8080/         # заголовки (gzip, кэш)

# правка статики на хосте видна СРАЗУ
echo "<h1>обновлено</h1>" > html/index.html && curl -s localhost:8080/

# правка КОНФИГА требует reload — разбери, почему
sed -i 's|"ok\\n"|"OK-v2\\n"|' conf/default.conf
curl -s localhost:8080/health           # старый ответ
docker exec web nginx -t                # проверить синтаксис ПЕРЕД релоадом
docker exec web nginx -s reload
curl -s localhost:8080/health           # новый

# только чтение
docker exec web sh -c 'echo x > /usr/share/nginx/html/hack.html' 2>&1 | head -1

# логи в stdout
docker logs --tail 5 web
```

### Задания сверх минимума
1. Добавь второй `server{}` с другим `server_name` и проверь через `curl -H "Host: ..."`.
2. Настрой отдачу статики с кэшированием и проверь заголовки.
3. Сделай upstream с двумя экземплярами приложения и посмотри балансировку
   (`docker run` второго app + `upstream` в конфиге).
4. Переведи nginx в `--read-only` (найди, какие tmpfs ему нужны).
5. Собери свой образ `FROM nginx:alpine` с конфигом внутри — сравни подходы:
   когда bind mount, когда свой образ?

### Вопросы себе
1. Почему статика обновляется сразу, а конфиг — нет?
2. Что делает `proxy_set_header X-Forwarded-For` и зачем это приложению?
3. Почему в конфиге `proxy_pass http://app:8000`, а не IP?
4. Что будет, если `nginx -t` не проходит, а ты сделал `reload`? А если `restart`?
5. Почему монтируем `:ro`?

---

## 🧪 Лаба 5. Свободные эксперименты

> Роадмап: «Докер открывает дверь в мир экспериментов. Можно очень много всего быстро
> поднимать — ломать — тестировать. Здесь насколько хватит фантазии.
> Опять же нейронки в помощь для генерации заданий.»

### Идеи, которые дают максимум пользы

| Эксперимент | Что поймёшь |
|-------------|-------------|
| Поднять **свой registry** (`registry:2`) с auth и запушить туда образ | тема 05 целиком |
| **Traefik** или nginx как reverse proxy с автоматическим роутингом по доменам | реальная схема прода |
| **ELK/Loki + Promtail** — сбор логов контейнеров | что делать с логами дальше |
| **Одна БД, две версии приложения** (blue/green через nginx upstream) | как деплоят без простоя |
| **GitLab CE или Gitea + runner** в контейнерах, собрать образ пайплайном | связка CI + registry |
| **Wordpress + MySQL / Nextcloud / Vaultwarden** из compose | типовые стеки «как в жизни» |
| Собрать **один и тот же сервис** на alpine, slim, distroless, scratch | реальная разница размеров и CVE |
| Прогнать `trivy` по 5 популярным образам и сравнить | тема 10 |
| Уронить сервер: **fork-бомба, лог-бомба, OOM** — и защититься лимитами | тема 06 и 11 |
| Собрать **мультиарх-образ** через `buildx` | тема 05 |
| Поднять **Kubernetes локально** (kind/k3d) и задеплоить свой образ | мост в следующий блок роадмапа |

### Формат ведения (важно!)

Заведи файл `experiments.md` и на каждый эксперимент записывай:

```markdown
## 2026-09-15 — cAdvisor без privileged

**Гипотеза:** cAdvisor можно запустить без `--privileged`, выдав точечные права.
**Что делал:** заменил privileged на `--device=/dev/kmsg` + `cap-add=SYS_PTRACE`, ...
**Результат:** часть метрик пропала (X), остальные работают.
**Вывод:** ...
**Не понял / вернуться:** почему нужен доступ к /sys/fs/cgroup именно на чтение.
```

Через месяц этот файл — твой личный справочник и отличный материал для собеседования:
конкретные истории всегда сильнее общих слов.

---

## 🏁 Что должно остаться после блока «Практика»

- [ ] Git-репозиторий с приложением, `Dockerfile`, `.dockerignore` и осмысленным README
- [ ] `docker-compose.yml` на 4 сервиса с сетями, томами и healthcheck
- [ ] Мониторинг-стек в compose + экспортированный JSON своего дашборда
- [ ] Конфиг nginx с проксированием, статикой и health-эндпоинтом
- [ ] Образ в registry с нормальной схемой тегов
- [ ] `experiments.md` со списком «поднял — сломал — починил»
- [ ] Ответы на все вопросы из блока «Вопросы себе» — своими словами
