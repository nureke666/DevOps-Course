---
title: "18. Современные прокси"
description: "Traefik, Envoy, Caddy: автообнаружение, xDS, circuit breaking, automatic HTTPS — конспект и задачи"
---

# 18. Современные прокси: Traefik, Envoy, Caddy

> Вне роадмапа 2.5 — продолжение тем [12. Nginx](/network/12-nginx) и [13. HAProxy](/network/13-haproxy-balancing).
> В вакансиях: «Traefik в Docker Swarm/Compose», «Envoy / Istio / Gateway API», «Caddy для внутренних сервисов».
> **После темы ты умеешь:** объяснить, чем «облачные» прокси отличаются от nginx/HAProxy, настроить
> Traefik через Docker-лейблы, написать статический конфиг Envoy с ретраями, таймаутами и circuit
> breaking, читать admin-эндпоинт Envoy, поднять Caddy с автоматическим HTTPS и выбрать прокси под задачу.
> Версии — «проверь, сентябрь 2026».

---

## 🗺️ Схема: откуда прокси узнаёт конфигурацию

```text:no-line-numbers
КЛАССИКА (nginx, HAProxy)       TRAEFIK                                ENVOY
 человек/Ansible                 Docker API ─┐                          control plane (istiod,
      │ пишет файл               Kubernetes ─┼─► providers (watch)      Envoy Gateway, Contour)
      ▼                          файлы      ─┘        │                        │ xDS (gRPC-стрим):
 nginx.conf ─► nginx -t ─► reload                     ▼                        │ LDS RDS CDS EDS SDS
                                 Traefik пересобирает роутинг на лету          ▼
 новый бэкенд = правка + reload  новый контейнер = маршрут появился сам   Envoy × сотни (data plane)
```

⭐ Главное отличие не в скорости, а в том, **кто и как меняет конфиг**: файл + reload,
автообнаружение из оркестратора или API, через который управляют тысячами прокси сразу.

---

## 1. Зачем что-то кроме nginx и HAProxy

| Потребность | Классика | Что предлагают новые прокси |
|-------------|----------|-----------------------------|
| **Динамический конфиг** | Правка файла + `reload` на каждый бэкенд | Изменения применяются на лету, без reload |
| **Service discovery** | Адреса вписаны руками или шаблонизатором | Бэкенды берутся из Docker, Kubernetes, Consul, DNS |
| **API-driven** | Нет (у HAProxy — runtime API для части операций) | Envoy целиком управляется по API (xDS) |
| **Устойчивость** | Базовые ретраи и таймауты | Ретраи с бюджетом, circuit breaking, outlier detection |
| **Наблюдаемость** | access.log + `stub_status` / stats-страница | Метрики по каждому маршруту и бэкенду, трассировка, response flags |
| **Протоколы** | HTTP/2 к бэкенду — ограниченно | gRPC и HTTP/2 end-to-end, WebSocket, HTTP/3 |
| **TLS** | certbot рядом, cron на продление | Caddy/Traefik сами получают и продлевают сертификаты |

Когда nginx/HAProxy **всё ещё лучший выбор**: статичная инфраструктура на ВМ, статика и кеш
(nginx), высоконагруженный L4/L7-балансировщик с runtime API (HAProxy), команда, которая
уже умеет их эксплуатировать. «Новое» ≠ «лучше» — это другой способ управления.

---

## 2. Traefik

| Факт (проверь, сентябрь 2026) | |
|-------------------------------|---|
| Версия | **Traefik v3.7.13** (04.09.2026); поддерживается только последняя минорная ветка |
| Образ | `traefik:v3.7` |
| Kubernetes | Ingress, свои CRD (`traefik.io/v1alpha1`: IngressRoute, Middleware…) и Gateway API (v1.5.x) |

### 2.1 Модель: entrypoints → routers → middlewares → services

```text:no-line-numbers
запрос :443 ─► ENTRYPOINT websecure ─► ROUTER Host(`app.lab`) && PathPrefix(`/api`) ─► MIDDLEWARES ─► SERVICE [ip1, ip2]
```

| Сущность | Что это | Аналог в nginx |
|----------|---------|----------------|
| **EntryPoint** | Порт, на котором слушает Traefik | `listen` |
| **Router** | Правило (`Host`, `PathPrefix`, `Header`, `Method`…) → куда отправить | `server_name` + `location` |
| **Middleware** | Преобразование запроса/ответа по пути | `rewrite`, `auth_basic`, `limit_req`, `add_header` |
| **Service** | Балансировщик с набором серверов | `upstream` |
| **Provider** | Откуда брать routers/services: Docker, Kubernetes, файл, Consul… | — (нет такого понятия) |

### 2.2 Static vs dynamic конфигурация (частый вопрос)

| | Static (install) | Dynamic (routing) |
|---|------------------|-------------------|
| Что | EntryPoints, providers, API/дашборд, certResolvers, логи, метрики | Routers, services, middlewares, TLS-опции |
| Где | `traefik.yml`, CLI-флаги, env | Лейблы Docker, CRD/Ingress/Gateway API, файлы file-провайдера |
| Когда применяется | Только при старте | ⭐ На лету, без перезапуска |

⚠️ Классическая ошибка — router в `traefik.yml`: его молча не прочитают. Маршруты — только в dynamic.

### 2.3 Docker-лейблы: сервис сам объявляет свой маршрут

```yaml
# compose.yaml
services:
  traefik:
    image: traefik:v3.7
    command:
      - --entrypoints.web.address=:80
      - --entrypoints.websecure.address=:443
      - --entrypoints.web.http.redirections.entrypoint.to=websecure   # весь http → https
      - --providers.docker=true
      - --providers.docker.exposedbydefault=false                     # ⭐ только с traefik.enable=true
      - --certificatesresolvers.le.acme.email=ops@example.com
      - --certificatesresolvers.le.acme.storage=/letsencrypt/acme.json
      - --certificatesresolvers.le.acme.httpchallenge.entrypoint=web
      - --metrics.prometheus=true --accesslog=true
    ports: ["80:80", "443:443"]
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro                 # ⚠️ см. «Грабли»
      - ./letsencrypt:/letsencrypt

  api:
    image: example/api:1.4
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.api.rule=Host(`api.example.com`) && PathPrefix(`/v1`)"
      - "traefik.http.routers.api.entrypoints=websecure"
      - "traefik.http.routers.api.tls.certresolver=le"               # ⭐ сертификат Let's Encrypt сам
      - "traefik.http.routers.api.middlewares=api-rl,api-retry"
      - "traefik.http.middlewares.api-rl.ratelimit.average=50"
      - "traefik.http.middlewares.api-rl.ratelimit.burst=100"
      - "traefik.http.middlewares.api-retry.retry.attempts=3"
      - "traefik.http.services.api.loadbalancer.server.port=8080"
      - "traefik.http.services.api.loadbalancer.healthcheck.path=/health"
      - "traefik.http.services.api.loadbalancer.healthcheck.interval=5s"
```

- `docker compose up -d --scale api=3` — Traefik **сам** объединит три контейнера в один service;
  остановился контейнер — событие Docker убирает сервер мгновенно. Ни одной правки конфига прокси.
- Ссылка на объект другого провайдера — через суффикс: `auth@file`, `api@internal`.

### 2.4 Middlewares, которые нужны чаще всего

| Middleware | Зачем |
|------------|-------|
| `redirectScheme` | http → https (или на уровне entrypoint, как выше) |
| `stripPrefix` | Срезать `/api` перед бэкендом (аналог слеша в `proxy_pass`) |
| `basicAuth` / `forwardAuth` | Пароль или внешний сервис авторизации (oauth2-proxy, Authelia) |
| `rateLimit` / `inFlightReq` | Лимит частоты и числа одновременных запросов |
| `retry` | Повтор при сетевой ошибке до ответа бэкенда; в свежих v3 — ещё по кодам (`status`) и с `timeout` |
| `circuitBreaker` | Размыкание по выражению: `NetworkErrorRatio() > 0.30`, `LatencyAtQuantileMS(50.0) > 100` |
| `headers` / `ipAllowList` | Заголовки безопасности и CORS / доступ только с подсетей |

### 2.5 Дашборд, API, метрики

```bash
# Лаба: --api.insecure=true → дашборд на :8080 (entrypoint «traefik»). В проде — router на api@internal + auth
curl -s localhost:8080/api/http/routers | jq '.[].name'
curl -s localhost:8080/api/http/services | jq '.[] | {name, serverStatus}'   # ⭐ UP/DOWN каждого сервера
curl -s localhost:8080/metrics | grep traefik_service_requests_total          # при --metrics.prometheus=true
```

### 2.6 Traefik в Kubernetes

```yaml
apiVersion: traefik.io/v1alpha1          # в v3 группа traefik.io (traefik.containo.us — удалена)
kind: IngressRoute
metadata: { name: api, namespace: shop }
spec:
  entryPoints: [websecure]
  routes:
  - match: Host(`api.example.com`) && PathPrefix(`/v1`)
    kind: Rule
    services: [{ name: api, port: 8080 }]
  tls: { certResolver: le }
```

- Три способа описать маршруты: стандартный `Ingress`, CRD `IngressRoute` (все возможности Traefik),
  **Gateway API** (`--providers.kubernetesgateway`; TCPRoute/TLSRoute — с `experimentalChannel=true`).
- Gateway API и его роли — в блоке Kubernetes; Traefik — одна из реализаций.

---

## 3. Envoy

Версия (проверь, сентябрь 2026): **Envoy 1.39.1** (27.08.2026), образ `envoyproxy/envoy:v1.39.1`; мажорный релиз
раз в квартал, поддержка — 12 месяцев. API конфигурации — ⭐ только **v3**.

### 3.1 Модель: listener → filter chain → route → cluster → endpoint

```text:no-line-numbers
запрос ─► LISTENER :10000 ─► filter_chains ─► HCM (http_connection_manager)            CLUSTER app (STRICT_DNS/EDS):
                                               ├ route_config: domains → routes ──────►  lb_policy, health_checks,
                                               └ http_filters: [jwt, ratelimit…, router]  circuit_breakers, outlier_detection
                                                                 router ВСЕГДА последний  └► ENDPOINTS 10.0.0.11:80, .12:80
```

| Термин Envoy | Аналог в nginx | Смысл |
|--------------|----------------|-------|
| Listener | `listen` | Адрес:порт, на который приходят соединения |
| Network / HTTP filter | модуль `stream`/`http`, фазы (`auth`, `limit_req`) | Поток байтов: HCM (HTTP), `tcp_proxy` (L4); над HTTP — цепочка, `router` шлёт в кластер |
| Route / virtual host | `server` + `location` | Домены и пути → кластер, ретраи, таймауты |
| Cluster | `upstream` | Группа бэкендов с балансировкой и защитой |
| Endpoint | `server` в upstream | Конкретный адрес бэкенда |

### 3.2 Минимальный статический конфиг: два бэкенда, ретраи, таймауты, circuit breaking

```yaml
# envoy.yaml
admin:
  address: { socket_address: { address: 0.0.0.0, port_value: 9901 } }   # ⚠️ в проде — только 127.0.0.1

static_resources:
  listeners:
  - name: http
    address: { socket_address: { address: 0.0.0.0, port_value: 10000 } }
    filter_chains:
    - filters:
      - name: envoy.filters.network.http_connection_manager
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
          stat_prefix: ingress_http
          access_log:
          - name: envoy.access_loggers.stdout
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.access_loggers.stream.v3.StdoutAccessLog
          route_config:
            virtual_hosts:
            - name: app
              domains: ["*"]
              routes:
              - match: { prefix: "/" }
                route:
                  cluster: app
                  timeout: 3s                          # весь запрос, включая все попытки
                  retry_policy:
                    retry_on: "connect-failure,reset,5xx"
                    num_retries: 2
                    per_try_timeout: 1s                # одна попытка
                    retry_host_predicate:              # повтор — на ДРУГОЙ хост
                    - name: envoy.retry_host_predicates.previous_hosts
                      typed_config:
                        "@type": type.googleapis.com/envoy.extensions.retry.host.previous_hosts.v3.PreviousHostsPredicate
          http_filters:
          - name: envoy.filters.http.router
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router

  clusters:
  - name: app
    type: STRICT_DNS                                   # резолвит имена и следит за изменениями
    dns_lookup_family: V4_ONLY
    connect_timeout: 0.5s
    lb_policy: ROUND_ROBIN
    load_assignment:
      cluster_name: app
      endpoints:
      - lb_endpoints:
        - endpoint: { address: { socket_address: { address: app1, port_value: 80 } } }
        - endpoint: { address: { socket_address: { address: app2, port_value: 80 } } }
    health_checks:                                     # активные проверки
    - timeout: 1s
      interval: 2s
      unhealthy_threshold: 2
      healthy_threshold: 1
      http_health_check: { path: "/" }
    circuit_breakers:                                  # ⭐ защита бэкенда от лавины
      thresholds:
      - max_connections: 100
        max_pending_requests: 50
        max_requests: 100
        max_retries: 3                                 # одновременных ретраев на кластер
    outlier_detection:                                 # пассивное выбрасывание «плохих» хостов
      consecutive_5xx: 3
      interval: 5s
      base_ejection_time: 15s
      max_ejection_percent: 50
```

```bash
docker run --rm -v "$PWD/envoy.yaml:/etc/envoy/envoy.yaml:ro" envoyproxy/envoy:v1.39.1 \
  envoy --mode validate -c /etc/envoy/envoy.yaml          # ⭐ аналог nginx -t
```

### 3.3 Устойчивость: четыре механизма, которые путают

| Механизм | Что делает | Когда срабатывает | Код клиенту |
|----------|-----------|-------------------|-------------|
| **Timeout** (`timeout`, `per_try_timeout`) | Ограничивает ожидание ответа | Бэкенд молчит | 504 (`UT`) |
| **Retry** (`retry_policy`) | Повтор на другой хост | Ошибка соединения, reset, 5xx, таймаут попытки | Успех или 5xx после `num_retries` (`URX`) |
| **Circuit breaker** (`circuit_breakers`) | Лимит одновременных соединений/запросов/ретраев на кластер | Кластер перегружен | Мгновенный 503 (`UO`) |
| **Outlier detection** | Временно выкидывает хост после серии ошибок | `consecutive_5xx` подряд | — (запросы идут на здоровые) |
| + **Health check** | Активная проверка, как `check` в HAProxy | `unhealthy_threshold` неудач | Нет живых → 503 (`UH`) |

⭐ Ретраи без бюджета — самоубийство при деградации: каждый запрос превращается в три, и умирающий
бэкенд добивают. Поэтому `max_retries` в circuit breakers и `per_try_timeout` меньше общего `timeout`.

### 3.4 Admin-эндпоинт и статистика

```bash
curl -s localhost:9901/ready                                   # LIVE
curl -s localhost:9901/clusters | grep -E 'health_flags|cx_active|rq_total'   # ⭐ состояние каждого хоста
curl -s localhost:9901/stats | grep -E '^cluster\.app\.(upstream_rq_(retry|timeout|pending_overflow)|membership_healthy|outlier_detection\.ejections_active)'
curl -s localhost:9901/stats/prometheus | head                 # готово для Prometheus
curl -s localhost:9901/config_dump | jq -r '.configs[]."@type"' # итоговый конфиг (static + xDS)
```

**Response flags** в access log (после кода ответа) — первое, что читают при разборе ошибок:
`UH` — нет здоровых хостов, `UF` — не подключился к бэкенду, `UO` — переполнен circuit breaker,
`URX` — исчерпаны ретраи, `UT` — таймаут, `UC` — бэкенд закрыл соединение, `NR` — нет маршрута.

### 3.5 xDS: Envoy как «тупой» data plane

| LDS | RDS | CDS | EDS | SDS | ADS |
|-----|-----|-----|-----|-----|-----|
| Listeners | Маршруты (`route_config`) | Clusters | Endpoints (адреса подов) | Сертификаты и ключи | Всё одним стримом в правильном порядке |

Control plane (Istio `istiod`, Envoy Gateway, Contour, Gloo/kgateway или свой на
`go-control-plane`) следит за Kubernetes и шлёт Envoy изменения по gRPC-стриму. Под переехал —
EDS за доли секунды обновил endpoints, без reload и без DNS-кеша.

### 3.6 Где ты встретишь Envoy, даже не настраивая его руками

- **Envoy Gateway** — реализация Gateway API: пишешь `Gateway`/`HTTPRoute`, контроллер
  превращает их в xDS для Envoy-подов.
- **Istio** — sidecar-Envoy в каждом поде (или в ambient-режиме: ztunnel на ноде + waypoint-Envoy),
  mTLS между сервисами, ретраи и трассировка без изменения кода.
- **Облака**: GCP Cloud Service Mesh (бывший Traffic Director), AWS App Mesh (поддержка заканчивается 30.09.2026) — Envoy внутри.
- Даже в Istio ошибки читаются через те же response flags, `/clusters` и `/config_dump` (`istioctl proxy-config`).

---

## 4. Caddy

Версия (проверь, сентябрь 2026): **Caddy 2.11.4** (03.06.2026), образ `caddy:2.11`. Главная фишка — ⭐ **automatic HTTPS** по умолчанию.

```text:no-line-numbers
# /etc/caddy/Caddyfile — это ВЕСЬ конфиг HTTPS-сайта с балансировкой
app.example.com {
    encode zstd gzip
    reverse_proxy app1:8080 app2:8080 {
        lb_policy       least_conn
        lb_retries      2
        health_uri      /health
        health_interval 5s
        fail_duration   30s             # пассивная проверка: помнить ошибку 30 с
    }
    handle_path /static/* {
        root * /srv/static
        file_server
    }
    log
}

internal.lab {
    tls internal                        # свой локальный CA Caddy — для внутренних имён
    reverse_proxy 10.0.0.21:3000
}
```

**Что делает automatic HTTPS**, если в адресе сайта домен: получает сертификат по ACME (Let's Encrypt или ZeroSSL;
HTTP-01 или TLS-ALPN-01 — нужны 80/443 снаружи), продлевает заранее, редиректит http → https. Для `localhost`
и внутренних IP — сертификат от собственного CA Caddy (`caddy trust` ставит его в систему).

```bash
caddy validate --config /etc/caddy/Caddyfile     # проверка
caddy fmt --overwrite /etc/caddy/Caddyfile       # форматирование
caddy reload --config /etc/caddy/Caddyfile       # применить без простоя (через admin API :2019)
caddy reverse-proxy --from :8080 --to app1:80 --to app2:80   # прокси одной командой
curl -s localhost:2019/config/ | jq              # итоговый JSON-конфиг (Caddyfile → JSON)
```

**Когда брать Caddy:** быстро и правильно отдать HTTPS небольшому сервису, внутренние инструменты, pet-проекты,
статика + прокси без certbot. **Когда нет:** тонкая балансировка/L4 на больших нагрузках (HAProxy), mesh и xDS
(Envoy), автообнаружение в Docker/K8s (Traefik; у Caddy — только сторонние плагины).

---

## 5. Сравнение: nginx vs HAProxy vs Traefik vs Envoy vs Caddy

| | nginx | HAProxy | Traefik | Envoy | Caddy |
|---|-------|---------|---------|-------|-------|
| Язык | C | C | Go | C++ | Go |
| Конфиг | Файл + `reload` | Файл + `reload`, runtime API | Providers (Docker/K8s/file) — на лету | Static YAML или ⭐ xDS API | Caddyfile/JSON + admin API |
| Service discovery | DNS-перерезолв `server … resolve` (с 1.27.3) | DNS/SRV-резолверы, `server-template` | ⭐ Из коробки | Через control plane (EDS), DNS | DNS/SRV, плагины |
| Активный health-check | Только Plus | ✅ | ✅ | ✅ | ✅ |
| Ретраи / circuit breaking | `proxy_next_upstream` | `retries`, `redispatch` | Middleware `retry`, `circuitBreaker` | ⭐ Богаче всех + outlier detection | `lb_retries`, `fail_duration` |
| Автоматический TLS | certbot или новый модуль `nginx-acme` | certbot или встроенный ACME (3.2+, эксперим.) | ✅ ACME | Через SDS / cert-manager | ⭐ По умолчанию |
| Метрики | `stub_status` (скудно) | Stats + Prometheus | Prometheus, OTel, дашборд | ⭐ Тысячи метрик, трассировка | Prometheus |
| Статика, кеш | ⭐ Лучший | ❌ | ❌ | ❌ | ✅ статика |
| L4 (TCP/UDP) | `stream` | ⭐ Основной режим | TCP/UDP routers | `tcp_proxy`, `udp_proxy` | Плагин `layer4` |
| Где типично | Веб-сервер, ingress-nginx | Балансировка БД/сервисов | Docker/Compose/Swarm, небольшой K8s | Mesh, Gateway API, edge больших компаний | Небольшие сервисы, внутренние инструменты |

**Ответ на собесе за 30 секунд:** «nginx — веб-сервер и прокси со статикой и кешем, HAProxy — балансировщик
с активными проверками. Traefik сам находит сервисы в Docker/Kubernetes и получает сертификаты. Envoy —
data plane, которым управляют по API (xDS): на нём Istio и Envoy Gateway, у него лучшие ретраи,
circuit breaking и метрики. Caddy — самый простой способ получить HTTPS».

---

## 6. Грабли

| Грабля | Симптом | Лечение |
|--------|---------|---------|
| Traefik: docker.sock в контейнере | Взлом Traefik = root на хосте | `:ro` не спасает — нужен socket-proxy (только чтение `containers`/`events`) или file-провайдер |
| Traefik: нет `exposedbydefault=false` | Наружу торчат все контейнеры, включая БД-админки | Всегда `false` + явный `traefik.enable=true` |
| Traefik: нет таймаута к бэкенду | Зависший бэкенд держит запросы бесконечно | `serversTransport.forwardingTimeouts.responseHeaderTimeout` (по умолчанию 0 = без лимита) |
| Envoy: забыли `router` в `http_filters` | Все запросы 404 / ошибка валидации | `envoy.filters.http.router` — последним |
| Envoy: `per_try_timeout` ≥ `timeout` | Ретраи «не работают» — общий таймаут кончился на первой попытке | `per_try_timeout × (num_retries+1) ≤ timeout` |
| Envoy: ретраи POST | Двойные платежи/заказы | Ретраить только идемпотентное или `retriable-status-codes` + ключи идемпотентности |
| Envoy: admin на 0.0.0.0 | Любой может `POST /quitquitquit` или менять логирование | Admin только на 127.0.0.1 / отдельная сеть |
| Caddy: 80/443 закрыты снаружи | Сертификат не выпускается, в логе ACME challenge failed | Открыть порты или DNS-01 (плагин провайдера) |

---

## 💼 Как это в DevOps

- **Compose/Swarm** — Traefik: сервис при деплое сам приносит маршрут лейблами, сертификаты выпускаются сами.
- **Kubernetes** — ingress-nginx уходит в прошлое, на его место — реализации Gateway API: Envoy Gateway,
  Traefik, Cilium и др.
- **Service mesh** — Envoy как sidecar/waypoint: ретраи, mTLS и метрики без изменения кода;
  от DevOps ждут умения читать `/clusters`, `config_dump` и response flags.
- **Наблюдаемость** — RPS, ошибки и латентность по каждому маршруту из коробки в Prometheus — основа
  SLO. **Внутренние сервисы** — Caddy: HTTPS одним файлом.

---

## 🧪 Мини-лаба

Два бэкенда за Traefik (лейблы) и Envoy (статический YAML) — сравниваем поведение при трёх видах «смерти» бэкенда.
Удобнее на хосте с Docker; на `web` из `~/Projects/devops/stands/net-lab` — `sudo apt install -y docker.io docker-compose-v2`.

```bash
mkdir -p ~/lab18 && cd ~/lab18
# envoy.yaml — конфиг из §3.2 целиком (кластер app → app1:80, app2:80)

cat > compose.yaml <<'EOF'
x-backend: &backend
  image: python:3.12-alpine
  # бэкенд отвечает своим hostname; /tmp/down = «процесс умер, контейнер жив»
  command: >-
    sh -c 'mkdir -p /srv && hostname > /srv/index.html &&
    while true; do [ -f /tmp/down ] || python3 -m http.server 80 -d /srv; sleep 1; done'
  labels:
    - "traefik.enable=true"
    - "traefik.http.routers.app.rule=PathPrefix(`/`)"
    - "traefik.http.routers.app.entrypoints=web"
    - "traefik.http.services.app.loadbalancer.server.port=80"
    - "traefik.http.services.app.loadbalancer.healthcheck.path=/"
    - "traefik.http.services.app.loadbalancer.healthcheck.interval=2s"
    - "traefik.http.services.app.loadbalancer.healthcheck.timeout=1s"
services:
  app1: *backend
  app2: *backend
  traefik:
    image: traefik:v3.7
    command: [--entrypoints.web.address=:80, --providers.docker=true,
              --providers.docker.exposedbydefault=false, --api.insecure=true, --accesslog=true]
    ports: ["8000:80", "8088:8080"]
    volumes: ["/var/run/docker.sock:/var/run/docker.sock:ro"]
  envoy:
    image: envoyproxy/envoy:v1.39.1
    volumes: ["./envoy.yaml:/etc/envoy/envoy.yaml:ro"]
    ports: ["8001:10000", "9901:9901"]
EOF

# 1. Старт и базовая проверка: оба прокси чередуют бэкенды
docker compose up -d && docker compose ps
for i in 1 2 3 4; do curl -s localhost:8000/; done      # Traefik
for i in 1 2 3 4; do curl -s localhost:8001/; done      # Envoy

# 2. Что прокси знают о бэкендах
curl -s localhost:8088/api/http/services/app@docker | jq .serverStatus    # Traefik: UP/UP (дашборд — :8088/dashboard/)
curl -s localhost:9901/clusters | grep health_flags                        # Envoy: healthy

# 3. Генератор нагрузки: 40 запросов по 0.1 с на оба прокси параллельно
hit() { for i in $(seq 40); do curl -s -o /dev/null -m 3 -w '%{http_code}\n' "localhost:$1/"; sleep 0.1; done | sort | uniq -c | sed "s/^/$2 /"; }
both() { hit 8000 traefik & hit 8001 envoy & wait; }

# 4. Сценарий A: процесс умер, контейнер жив (connection refused)
docker compose exec app2 sh -c 'touch /tmp/down; pkill python3'; both
#   Traefik: несколько 502, пока health-check не выведет app2; Envoy: только 200 — ретрай на app1
curl -s localhost:8088/api/http/services/app@docker | jq .serverStatus    # app2 DOWN
curl -s localhost:9901/clusters | grep health_flags                        # /failed_active_hc
curl -s localhost:9901/stats | grep -E 'cluster.app.upstream_rq_retry:'    # сколько раз Envoy повторил
docker compose exec app2 rm /tmp/down; sleep 4                              # бэкенд ожил → снова UP

# 5. Traefik тоже умеет ретраи: меняем ЛЕЙБЛЫ, а не Traefik
sed -i 's|    - "traefik.http.routers.app.entrypoints=web"|&\n    - "traefik.http.routers.app.middlewares=rt"\n    - "traefik.http.middlewares.rt.retry.attempts=2"|' compose.yaml
docker compose up -d                              # пересоздаются только app1/app2, Traefik подхватывает сам
docker compose exec app2 sh -c 'touch /tmp/down; pkill python3'; both   # теперь 200 у обоих
docker compose exec app2 rm /tmp/down; sleep 4

# 6. Сценарий B: бэкенд завис (SIGSTOP) — соединение принимается ядром, ответа нет
docker compose exec app2 pkill -STOP python3; both
#   Traefik: 000 (curl -m 3 не дождался) — таймаута к бэкенду по умолчанию нет,
#   пока health-check (timeout 1s) не выведет app2; Envoy: 200 с задержкой ~1 с (per_try_timeout → ретрай)
curl -s localhost:9901/stats | grep -E 'cluster.app.upstream_rq_(per_try_timeout|retry):'   # таймауты попыток и ретраи
docker compose exec app2 pkill -CONT python3; sleep 4
#   починка Traefik: --serverstransport.forwardingtimeouts.responseheadertimeout=2s в command → 504 вместо вечного ожидания

# 7. Сценарий C: контейнер остановлен
docker compose stop -t 1 app2; both     # -t 1: sh как PID 1 игнорирует SIGTERM, иначе ждать 10 с до SIGKILL
#   Traefik: событие Docker убрало сервер сразу; Envoy: DNS-перерезолв (5 с) + health-check, ретраи прикрывают
curl -s localhost:8088/api/http/services/app@docker | jq .serverStatus    # app2 исчез из списка
docker compose start app2

# 8. Автообнаружение: масштабируем
docker compose up -d --scale app2=3 && sleep 6          # Envoy перерезолвит DNS раз в 5 с
curl -s localhost:8088/api/http/services/app@docker | jq '.serverStatus | length'   # 4 сервера
curl -s localhost:9901/clusters | grep -c '::health_flags::'                         # тоже 4: STRICT_DNS нашёл все A-записи app2
for i in $(seq 8); do curl -s localhost:8000/; done | sort | uniq -c

# 9. Circuit breaker Envoy: сжимаем лимиты до 1
sed -i 's/max_connections: 100/max_connections: 1/; s/max_pending_requests: 50/max_pending_requests: 1/' envoy.yaml
docker compose up -d --force-recreate envoy       # sed -i меняет inode файла — bind mount надо пересоздать
seq 200 | xargs -P 50 -I{} curl -s -o /dev/null -w '%{http_code}\n' localhost:8001/ | sort | uniq -c   # часть — 503
curl -s localhost:9901/stats | grep upstream_rq_pending_overflow            # > 0; в access log флаг UO

# 10. Бонус — Caddy одной командой (без HTTPS: адрес :80)
docker run --rm -d --name caddy --network lab18_default -p 8002:80 caddy:2.11 \
  caddy reverse-proxy --from :80 --to app1:80 --to app2:80
for i in 1 2 3 4; do curl -s localhost:8002/; done; docker rm -f caddy

# 11. Уборка
docker compose down
```

**Что зафиксировать:** таблицу «сценарий × прокси → ошибок у клиента, через сколько секунд бэкенд выведен». Типичный
вывод: Traefik выигрывает в обнаружении (контейнер пропал — маршрут пропал), Envoy — в устойчивости к «полуживым» бэкендам.

---

## 📌 Шпаргалка

| Команда / понятие | Смысл |
|-------------------|-------|
| EntryPoint → Router → Middleware → Service | ⭐ Модель Traefik |
| Static vs dynamic | Установка (при старте) vs маршруты (на лету) |
| `traefik.enable=true` + `exposedbydefault=false` | Публиковать только явно отмеченное |
| `curl :8080/api/http/services` | Состояние серверов в Traefik |
| Listener → HCM → route → cluster → endpoint | ⭐ Модель Envoy |
| `envoy --mode validate -c envoy.yaml` | Проверка конфига |
| `retry_policy` + `per_try_timeout` + `timeout` | Ретраи и таймауты Envoy |
| `circuit_breakers` / `outlier_detection` | Лимиты на кластер / выбрасывание плохих хостов |
| `:9901/clusters`, `/stats`, `/config_dump`; xDS: LDS RDS CDS EDS SDS | ⭐ Admin Envoy; API control plane |
| `UH UF UO URX UT NR` | Response flags Envoy |
| `reverse_proxy a b { health_uri … }` | Caddy: балансировка |
| `caddy reload`, `:2019/config/`, `tls internal` | Caddy: применить, посмотреть конфиг, свой CA |

---

## 🧠 Что запомнить

1. Новые прокси отличаются способом управления: автообнаружение (Traefik) и API (Envoy/xDS) вместо «файл + reload».
2. Traefik: entrypoints → routers → middlewares → services; static-конфиг — при старте,
   dynamic (лейблы, CRD, Gateway API) — на лету.
3. В Docker всегда `exposedbydefault=false`, доступ к docker.sock — это root на хосте;
   сертификаты Traefik выпускает сам через `certResolver`, `acme.json` — на volume.
4. Envoy: listener → filter chain (HCM + http_filters, `router` последний) → route → cluster → endpoint.
5. Envoy-устойчивость: timeout, retry (с `per_try_timeout` и бюджетом), circuit breaker (503 `UO`),
   outlier detection, активные health-check.
6. Admin Envoy (`/clusters`, `/stats`, `/config_dump`) и response flags — главный инструмент отладки,
   в том числе в Istio и Envoy Gateway.
7. xDS: LDS, RDS, CDS, EDS, SDS; control plane управляет, Envoy только проксирует.
8. Caddy — automatic HTTPS по умолчанию: ACME, продление, редирект; `tls internal` для внутренних имён.
9. Выбор: статика и кеш — nginx; L4 и активные проверки — HAProxy; Docker/Compose — Traefik;
    mesh и Gateway API — Envoy; «просто HTTPS» — Caddy.

---

## Задачи

> Стенд: `~/lab18` из мини-лабы (Docker на хосте или на `web`), бэкенды `app1`/`app2`.
> Сравнивай с темами [12. Nginx](/network/12-nginx) и [13. HAProxy](/network/13-haproxy-balancing): те же сценарии, другие инструменты.

---

### Блок A. Теория

**A1.** Какие задачи решают Traefik и Envoy, которые плохо решаются схемой «файл + reload»?
Когда nginx или HAProxy всё равно лучше?

<details><summary>Ответ</summary>

Динамическая инфраструктура: бэкенды появляются и исчезают (контейнеры, поды), адреса
меняются, а каждый reload — это ручная работа или шаблонизатор. Новые прокси берут конфиг
из оркестратора (Traefik) или по API (Envoy/xDS), дают ретраи, circuit breaking, метрики по
маршрутам и автоматический TLS. nginx лучше для статики и кеша, HAProxy — для высоконагруженного
L4/L7 на статичных ВМ с runtime API; обоих проще эксплуатировать, если команда их знает.

</details>

**A2.** ⭐ Опиши модель Traefik: entrypoint, router, middleware, service, provider.
Что из этого соответствует `listen`, `location`, `upstream` в nginx?

<details><summary>Ответ</summary>

EntryPoint — порт (`listen`); Router — правило сопоставления (`server_name` + `location`);
Middleware — преобразования (rewrite, auth, лимиты, заголовки); Service — балансировщик с серверами
(`upstream`); Provider — источник dynamic-конфигурации (Docker, Kubernetes, файл), аналога в nginx нет.

</details>

**A3.** Чем static-конфигурация Traefik отличается от dynamic? Что будет, если описать router
в `traefik.yml`?

<details><summary>Ответ</summary>

Static — то, что нужно при старте: entrypoints, providers, API, certResolvers, логи, метрики
(`traefik.yml`, флаги, env). Dynamic — маршруты, сервисы, middlewares, TLS-сертификаты (лейблы,
CRD, file-провайдер), применяется на лету. Router в `traefik.yml` просто игнорируется.

</details>

**A4.** Как Traefik узнаёт о новом контейнере и что происходит при `docker compose up --scale api=3`?

<details><summary>Ответ</summary>

Docker-провайдер подписан на события Docker API: старт/остановка контейнера пересобирает
конфигурацию. При `--scale` у всех реплик одинаковые лейблы → один service с несколькими серверами.

</details>

**A5.** Как Traefik получает сертификат Let's Encrypt? Что такое `certResolver`, какие бывают
challenge и где хранится результат?

<details><summary>Ответ</summary>

`certResolver` — именованная ACME-конфигурация (email, storage, challenge) в static-конфиге;
router ссылается на него `tls.certresolver=le`. Challenge: HTTP-01 (порт 80), TLS-ALPN-01 (порт 443),
DNS-01 (TXT-запись через API DNS-провайдера — нужен для wildcard и закрытых сетей).
Сертификаты и ключ аккаунта — в `acme.json` (volume, права 600).

</details>

**A6.** Зачем `exposedbydefault=false`? Почему монтирование `docker.sock` опасно даже с `:ro`
и что делают вместо этого?

<details><summary>Ответ</summary>

Без него наружу публикуется каждый контейнер с открытым портом. Доступ к Docker API =
root на хосте (можно запустить привилегированный контейнер); `:ro` на сокете не ограничивает API.
Вместо — docker-socket-proxy с разрешёнными только `containers` и `events` (GET), либо file-провайдер.

</details>

**A7.** Назови три способа описать маршруты Traefik в Kubernetes. Когда какой?

<details><summary>Ответ</summary>

`Ingress` — стандарт, минимум возможностей, остальное — аннотации; CRD `IngressRoute` +
`Middleware` — все возможности Traefik, но привязка к нему; Gateway API — стандарт нового поколения
с ролями, переносимый между реализациями. Для новых проектов — Gateway API.

</details>

**A8.** ⭐ Опиши модель Envoy: listener, filter chain, HCM, http filters, route, cluster, endpoint.
Почему `router` должен быть последним HTTP-фильтром?

<details><summary>Ответ</summary>

Listener принимает соединения; filter chain — набор сетевых фильтров; HCM
(`http_connection_manager`) превращает поток в HTTP-запросы, содержит route_config (домены,
пути → кластер, ретраи, таймауты) и цепочку HTTP-фильтров; cluster — группа бэкендов с политикой
балансировки и защитой; endpoint — адрес. `router` — терминальный фильтр: он отправляет запрос
в кластер, фильтры после него не выполнятся.

</details>

**A9.** Чем отличаются timeout, per-try timeout, retry, circuit breaker, outlier detection
и active health check в Envoy? Какой код получит клиент в каждом случае?

<details><summary>Ответ</summary>

Timeout — сколько ждать ответа (весь запрос; per-try — одна попытка) → 504 `UT`.
Retry — повтор при ошибках соединения/5xx/таймауте попытки → успех или ошибка `URX`.
Circuit breaker — лимит одновременных соединений/запросов/ретраев на кластер → мгновенный 503 `UO`.
Outlier detection — временное исключение хоста после серии ошибок → клиент ошибок не видит.
Health check — активная проверка; нет здоровых хостов → 503 `UH`.

</details>

**A10.** Почему ретраи без ограничений опасны? Какими настройками Envoy их ограничивают?

<details><summary>Ответ</summary>

При деградации бэкенда ретраи умножают нагрузку (каждый запрос → N), добивая его
(retry storm). Ограничения: `num_retries`, `per_try_timeout` меньше общего `timeout`,
`max_retries` в circuit breakers (или `retry_budget`), ретраи только идемпотентных запросов.

</details>

**A11.** Что такое xDS? Перечисли основные API и назови три control plane.

<details><summary>Ответ</summary>

xDS — набор gRPC API, по которым control plane раздаёт Envoy конфигурацию: LDS (listeners),
RDS (routes), CDS (clusters), EDS (endpoints), SDS (секреты), ADS (всё одним стримом).
Control plane: Istio `istiod`, Envoy Gateway, Contour, kgateway (Gloo), свой на `go-control-plane`.

</details>

**A12.** Как Envoy используется в Envoy Gateway и Istio? Чем sidecar отличается от ambient-режима?

<details><summary>Ответ</summary>

Envoy Gateway переводит Gateway API (`Gateway`, `HTTPRoute`) в xDS для Envoy-подов на входе
в кластер. Istio ставит Envoy рядом с приложениями: sidecar — контейнер в каждом поде (mTLS, ретраи,
метрики), ambient — без sidecar: ztunnel на ноде делает L4 и mTLS, а L7-функции — waypoint-Envoy
по необходимости.

</details>

**A13.** Что даёт admin-эндпоинт Envoy? Назови пять путей и объясни, почему admin нельзя
вешать на `0.0.0.0`.

<details><summary>Ответ</summary>

Состояние и отладка: `/clusters` (хосты и health flags), `/stats` и `/stats/prometheus`,
`/config_dump` (итоговый конфиг), `/listeners`, `/ready`, `/server_info`, `/logging` (уровни логов).
Admin умеет и менять состояние (`POST /quitquitquit`, `/healthcheck/fail`, `/logging`) — доступ снаружи
позволяет уронить или вывести из балансировки прокси.

</details>

**A14.** Расшифруй response flags `UH`, `UF`, `UO`, `URX`, `UT`, `NR`.

<details><summary>Ответ</summary>

`UH` — нет здоровых хостов; `UF` — ошибка подключения к бэкенду; `UO` — переполнение
circuit breaker; `URX` — исчерпаны ретраи/попытки соединения; `UT` — таймаут запроса к бэкенду;
`NR` — нет маршрута для домена/пути.

</details>

**A15.** Что делает automatic HTTPS в Caddy? В каких условиях сертификат не будет выпущен
и что тогда делать?

<details><summary>Ответ</summary>

Для доменного имени сайта Caddy сам получает сертификат по ACME (Let's Encrypt/ZeroSSL),
продлевает его и включает редирект на https; для `localhost`/IP — выпускает от своего CA.
Не сработает, если имя не резолвится публично или 80/443 недоступны снаружи (HTTP-01/TLS-ALPN-01).
Тогда — DNS-01 через плагин DNS-провайдера или `tls internal` с раздачей корневого сертификата.

</details>

**A16.** Для каждого из nginx, HAProxy, Traefik, Envoy, Caddy — один сценарий, где он лучший выбор.

<details><summary>Ответ</summary>

nginx — статика, кеш, классический веб-сервер и reverse proxy на ВМ; HAProxy — балансировка
БД и TCP-сервисов с активными проверками и runtime API; Traefik — Docker/Compose/Swarm и небольшие
кластеры с автообнаружением и Let's Encrypt; Envoy — mesh, Gateway API, сложная устойчивость
и наблюдаемость; Caddy — внутренний сервис или pet-проект, где нужен HTTPS «без головной боли».

</details>

---

### Блок B. «Что делает конфиг / что значит вывод»

```text:no-line-numbers
B1.  traefik.http.routers.api.rule=Host(`api.lab`) && PathPrefix(`/v1`)
B2.  traefik.http.routers.api.tls.certresolver=le
B3.  traefik.http.middlewares.strip.stripprefix.prefixes=/api
B4.  traefik.http.services.api.loadbalancer.healthcheck.path=/health
B5.  --entrypoints.web.http.redirections.entrypoint.to=websecure
B6.  --providers.docker.exposedbydefault=false
B7.  traefik.http.middlewares.cb.circuitbreaker.expression=NetworkErrorRatio() > 0.30
B8.  retry_policy: { retry_on: "connect-failure,reset,5xx", num_retries: 2, per_try_timeout: 1s }
B9.  circuit_breakers: { thresholds: [ { max_connections: 1, max_pending_requests: 1 } ] }
B10. outlier_detection: { consecutive_5xx: 3, base_ejection_time: 15s, max_ejection_percent: 50 }
B11. type: STRICT_DNS
B12. reverse_proxy a:80 b:80 { lb_policy least_conn; health_uri /health }     # Caddy
B13. tls internal                                                             # Caddy
```

- **B1.** Router срабатывает на хост `api.lab` и пути, начинающиеся с `/v1`.
- **B2.** Сертификат для хоста из правила выпускается резолвером `le` (Let's Encrypt).
- **B3.** Middleware срезает `/api` в начале пути перед отправкой бэкенду.
- **B4.** Активная проверка: Traefik опрашивает `/health` каждого сервера и выводит неответивших.
- **B5.** Всё, что пришло на entrypoint `web` (80), редиректится на `websecure` (https).
- **B6.** Контейнеры публикуются только с лейблом `traefik.enable=true`.
- **B7.** Цепь размыкается (сразу 503 без обращения к бэкенду), если доля сетевых ошибок > 30%.
- **B8.** До 2 повторов на другой хост при ошибке соединения, reset или 5xx; каждая попытка — не дольше 1 с.
- **B9.** Одно соединение и один ожидающий запрос на весь кластер — всё сверх получает 503 `UO`.
- **B10.** После 3 подряд 5xx хост исключается на 15 с (дольше при повторах), но не более половины хостов.
- **B11.** Кластер резолвит имена endpoint'ов по DNS периодически и использует все A-записи.
- **B12.** Caddy балансирует на `a` и `b` по наименьшему числу соединений с активной проверкой `/health`.
- **B13.** Сертификат для сайта выпускает локальный CA Caddy, а не Let's Encrypt.

**B14.** Разбери строку access log Envoy:

```text:no-line-numbers
[2026-09-28T10:00:01.123Z] "GET /api/orders HTTP/1.1" 503 UO 0 81 0 - "-" "curl/8.5.0" "5b1c…" "api.lab" "-"
```

<details><summary>Ответ</summary>

GET на `/api/orders` к хосту `api.lab` получил 503 с флагом `UO`: сработал circuit breaker,
запрос до бэкенда не дошёл (`UPSTREAM_HOST` = `-`, 0 байт получено, длительность 0 мс).
Смотреть `upstream_rq_pending_overflow` / `upstream_cx_overflow` и лимиты `circuit_breakers`.

</details>

**B15.** Фрагмент `curl localhost:9901/clusters`. Что с хостами?

```text:no-line-numbers
app::172.18.0.3:80::health_flags::/failed_active_hc
app::172.18.0.4:80::health_flags::/failed_outlier_check
app::172.18.0.5:80::health_flags::healthy
```

<details><summary>Ответ</summary>

`.3` провалил активный health-check; `.4` отвечает на health-check, но выброшен outlier
detection за серию 5xx на реальном трафике; `.5` — здоров, весь трафик идёт на него.

</details>

---

### Блок C. Практика

**C1. 🔑 Сравнительная таблица.** Пройди мини-лабу конспекта целиком и заполни таблицу:
сценарий (процесс умер / завис / контейнер остановлен) × прокси (Traefik без retry,
Traefik с retry, Envoy) → сколько ошибок увидел клиент, какие коды, через сколько секунд
бэкенд выведен из ротации.

<details><summary>Ответ</summary>

Типичный результат: «процесс умер» — Traefik без retry даёт несколько 502 до health-check,
с retry и Envoy — 0 ошибок; «завис» — у Traefik без таймаута запросы висят (000/таймаут клиента)
до вывода по health-check, у Envoy — 200 с задержкой ~1 с (per-try timeout → ретрай);
«контейнер остановлен» — Traefik убирает сервер по событию Docker, Envoy — по DNS/health-check,
ретраи прикрывают клиента.

</details>

**C2. Traefik + HTTPS со своим CA.** Возьми CA и сертификат из темы [07. TLS](/network/07-tls), подключи
их через file-провайдер (`tls.certificates`), включи редирект http → https на уровне entrypoint.
Проверь `openssl s_client -servername` и объясни, когда Traefik отдаёт `TRAEFIK DEFAULT CERT`.

<details><summary>Ответ</summary>

```yaml
# dynamic/tls.yml (file-провайдер)
tls:
  certificates:
  - certFile: /certs/shop.lab.local.crt
    keyFile: /certs/shop.lab.local.key
```
Router: `tls=true`, entrypoint `websecure`, в static — редирект `web → websecure`.
`TRAEFIK DEFAULT CERT` отдаётся, когда для SNI нет подходящего сертификата (имя не совпало,
файл не прочитан, у router нет `tls`, certResolver не выпустил).

</details>

**C3. Middlewares.** Навесь на router цепочку `stripPrefix` (/api), `basicAuth` и `rateLimit`
(average 2, burst 2). Проверь каждую curl'ом: путь на бэкенде, 401 без пароля, 429 при превышении.

<details><summary>Ответ</summary>

`stripprefix.prefixes=/api`; `basicauth.users=lab:$$apr1$$…` (в compose `$` удваивается,
хеш — `htpasswd -nb lab pass`); `ratelimit.average=2`, `burst=2`. Проверки: бэкенд видит путь
без `/api`; без `-u` — 401; серия из 10 быстрых запросов — часть 429.

</details>

**C4. File-провайдер и бэкенд вне Docker.** Подними HTTP-сервер на ВМ `app` (192.168.56.11:8080)
и опиши его в dynamic-файле Traefik (`--providers.file.directory`, `watch=true`). Поменяй порт
в файле и докажи, что Traefik применил изменение без перезапуска.

<details><summary>Ответ</summary>

```yaml
# /etc/traefik/dynamic/legacy.yml
http:
  routers:
    legacy: { rule: "Host(`legacy.lab`)", entryPoints: [web], service: legacy }
  services:
    legacy:
      loadBalancer:
        servers: [{ url: "http://192.168.56.11:8080" }]
```
С `--providers.file.directory=/etc/traefik/dynamic --providers.file.watch=true` правка файла
применяется в течение секунды; в логе Traefik — перезагрузка конфигурации провайдера `file`.

</details>

**C5. Таймауты Traefik.** Повтори сценарий «завис» (SIGSTOP) с
`--serverstransport.forwardingtimeouts.responseheadertimeout=2s`. Что теперь получает клиент?
Добавь в retry-middleware повтор по статусу (`status=504`, если твоя версия поддерживает) и сравни.

<details><summary>Ответ</summary>

С `responseHeaderTimeout=2s` клиент через 2 с получает 504 вместо бесконечного ожидания;
после вывода бэкенда health-check'ом ошибки прекращаются. Повтор по статусу 504 (в версиях,
где есть `retry.status`) превращает часть 504 в 200 ценой +2 с к задержке.

</details>

**C6. Envoy: маршрутизация по пути.** Добавь второй кластер `api` и маршрут `/api/` → `api`
с `prefix_rewrite: "/"`, всё остальное → `app`. Проверь, какой путь видит бэкенд.

<details><summary>Ответ</summary>

```yaml
routes:
- match: { prefix: "/api/" }
  route: { cluster: api, prefix_rewrite: "/" }       # /api/users → /users
- match: { prefix: "/" }
  route: { cluster: app }
```
Порядок важен: маршруты проверяются сверху вниз, более специфичный — первым.

</details>

**C7. Outlier detection.** Добавь в кластер третий бэкенд, который всегда отвечает 500.
Покажи: (1) клиенту всё равно 200 (почему?); (2) в `/clusters` хост с `/failed_outlier_check`;
(3) `outlier_detection.ejections_active` в `/stats`; (4) возврат хоста через `base_ejection_time`.

<details><summary>Ответ</summary>

«Плохой» бэкенд: `python3 -c "import http.server as h
class H(h.BaseHTTPRequestHandler):
    def do_GET(s): s.send_response(500); s.end_headers()
h.ThreadingHTTPServer(('',80),H).serve_forever()"`. (1) 200 — `retry_on: 5xx` повторяет запрос на
другой хост; (2) `/failed_outlier_check` после 3 подряд 5xx; (3) `ejections_active 1`; (4) через
~15 с хост возвращается и после новых ошибок выбрасывается снова, уже дольше. Health-check на `/`
у этого бэкенда тоже провалится (500) — для чистоты опыта проверяй его на другом пути или убери.

</details>

**C8. Канарейка на Envoy.** Раздели трафик 90/10 между кластерами `v1` и `v2`
(`weighted_clusters`), прогони 200 запросов и посчитай распределение.

<details><summary>Ответ</summary>

```yaml
route:
  weighted_clusters:
    clusters:
    - { name: v1, weight: 90 }
    - { name: v2, weight: 10 }
```
На 200 запросах — примерно 180/20 (случайное распределение, ±несколько).

</details>

**C9. Метрики.** Сними `/stats/prometheus` Envoy и `/metrics` Traefik (включи
`--metrics.prometheus=true`). Найди в каждом: общее число запросов, число 5xx, число ретраев.
Напиши по одному PromQL-запросу на долю 5xx.

<details><summary>Ответ</summary>

Envoy: `envoy_cluster_upstream_rq_total`, `envoy_cluster_upstream_rq_xx{envoy_response_code_class="5"}`,
`envoy_cluster_upstream_rq_retry`. Traefik: `traefik_service_requests_total{code=~"5.."}`,
`traefik_service_retries_total`. PromQL:
`sum(rate(traefik_service_requests_total{code=~"5.."}[5m])) / sum(rate(traefik_service_requests_total[5m]))`.

</details>

**C10. Caddy.** Опиши в Caddyfile сайт `app.lab` с `tls internal` и балансировкой на `app1`/`app2`
с health-check. Достань корневой сертификат Caddy из контейнера и сделай
`curl --cacert … --resolve app.lab:443:127.0.0.1 https://app.lab/`. Сравни объём конфига с nginx+certbot.

<details><summary>Ответ</summary>

```text:no-line-numbers
app.lab {
    tls internal
    reverse_proxy app1:80 app2:80 {
        health_uri /
        health_interval 2s
    }
}
```
Корень: `docker cp caddy:/data/caddy/pki/authorities/local/root.crt .`, затем
`curl --cacert root.crt --resolve app.lab:443:127.0.0.1 https://app.lab/`. Восемь строк против
server-блоков nginx + certbot + cron.

</details>

**C11. Пять прокси — один сценарий.** Сценарий «процесс бэкенда умер» (из C1) повтори на nginx
(тема 12) и HAProxy (тема 13). Итог — таблица из пяти столбцов в стиле §5 конспекта, но с твоими цифрами.

<details><summary>Ответ</summary>

Ожидаемо: nginx (пассивные проверки) — ошибки до `max_fails`, но `proxy_next_upstream`
по умолчанию повторяет на другой бэкенд при `error`/`timeout`; HAProxy — ошибки только до вывода
по `inter × fall` (или 0 с `option redispatch` + `retries`); Traefik/Envoy — как в C1.

</details>

**C12 (по желанию). Envoy под капотом Envoy Gateway.** В kind с Envoy Gateway
пробрось admin-порт Envoy-пода (`kubectl port-forward … 19000`) и найди в `/config_dump` свой HTTPRoute в виде route и cluster.

<details><summary>Ответ</summary>

`kubectl -n envoy-gateway-system port-forward pod/<envoy-pod> 19000` →
`curl -s localhost:19000/config_dump | jq` — маршрут ищется по имени HTTPRoute (вида `httproute/<ns>/<name>/rule/0`),
кластер — по Service. Это тот же Envoy, что в мини-лабе, только конфиг пришёл по xDS.

</details>

---

### Блок D. Инциденты

**D1.** Новый сервис добавили в `compose.yaml` с лейблами, Traefik отвечает на его домен 404.
Назови пять причин и как проверить каждую.

<details><summary>Ответ</summary>

(1) Нет `traefik.enable=true` при `exposedbydefault=false`; (2) контейнер в другой
docker-сети, чем Traefik (нужен общий network или `traefik.docker.network`); (3) ошибка в `rule`
(обратные кавычки, `Host` вместо `Host(...)`); (4) не тот entrypoint; (5) контейнер unhealthy —
Traefik не публикует контейнеры с failing Docker healthcheck. Проверка: дашборд/API
`/api/http/routers`, логи Traefik (`--log.level=DEBUG`).

</details>

**D2.** Сайт за Traefik открывается с ошибкой сертификата: браузер показывает `TRAEFIK DEFAULT CERT`.

<details><summary>Ответ</summary>

Для SNI нет сертификата: certResolver не выпустил (ошибка ACME в логах, закрыт порт 80
для HTTP-01), у router нет `tls`, домен в `rule` не совпадает с запрошенным, или сертификат
из file-провайдера не загружен.

</details>

**D3.** После нескольких перезапусков контейнера Traefik Let's Encrypt перестал выдавать
сертификат: `too many certificates already issued`.

<details><summary>Ответ</summary>

`acme.json` не на volume: при каждом старте Traefik заказывает сертификаты заново и упирается
в лимит дубликатов Let's Encrypt (5 в неделю на один набор имён). Вынести `acme.json` на volume,
для экспериментов использовать staging (`caServer`).

</details>

**D4.** Envoy при росте нагрузки отдаёт 503 с флагом `UO`, а бэкенды загружены на 20%.

<details><summary>Ответ</summary>

Сработал circuit breaker: лимиты `max_connections`/`max_pending_requests`/`max_requests`
малы для текущего параллелизма (по умолчанию 1024 — в mesh их часто занижают). Проверить
`upstream_cx_overflow`, `upstream_rq_pending_overflow`, поднять лимиты под реальную нагрузку.

</details>

**D5.** После деплоя Envoy отдаёт 503 `UH`, хотя поды приложения Running и отвечают на curl изнутри.

<details><summary>Ответ</summary>

Все хосты кластера «нездоровы» с точки зрения Envoy: health-check идёт на неверный путь/порт,
EDS ещё не получил новые endpoints (control plane не видит поды — readiness, селектор Service),
или все хосты выброшены outlier detection. Смотреть `/clusters` (health_flags), `/config_dump`, логи control plane.

</details>

**D6.** В mesh включили ретраи на 5xx для всех сервисов. Через день — жалобы на двойные списания
в сервисе оплаты.

<details><summary>Ответ</summary>

Ретраи на 5xx повторили неидемпотентные POST: первый запрос успел списать деньги,
но ответ потерялся/вернулся 5xx. Ретраи — только для идемпотентных методов или с ключом
идемпотентности на стороне сервиса; для оплаты — отключить ретраи на 5xx.

</details>

**D7.** Выгрузка отчёта через Envoy стабильно обрывается с 504 ровно через 15 секунд, хотя
в конфиге маршрута `timeout` не указан.

<details><summary>Ответ</summary>

У маршрута Envoy по умолчанию `timeout: 15s`. Для отчётов — отдельный route с большим
`timeout` (или 0 — без лимита) и, возможно, `idle_timeout`; лучше — асинхронная генерация.

</details>

**D8.** Один бэкенд за Traefik завис (процесс жив, не отвечает). У части пользователей запросы
висят минутами, у других всё нормально.

<details><summary>Ответ</summary>

У Traefik по умолчанию нет таймаута ожидания ответа бэкенда (`responseHeaderTimeout: 0`),
а health-check либо не настроен, либо ещё не сработал. Запросы, попавшие на зависший бэкенд,
висят. Решение: `forwardingTimeouts.responseHeaderTimeout`, активный health-check, retry.

</details>

**D9.** Caddy для `grafana.corp.internal` в закрытой сети не может получить сертификат, в логе
ошибки ACME challenge.

<details><summary>Ответ</summary>

Let's Encrypt не может проверить закрытое имя: ни HTTP-01, ни TLS-ALPN-01 до сервера
не доходят. Варианты: DNS-01 через плагин провайдера (если домен публичный, а сервер закрыт),
`tls internal` + раздача корня Caddy, или внутренний ACME-CA (step-ca, Vault PKI).

</details>

**D10.** Через Traefik из интернета открывается Adminer к базе, хотя его никто не публиковал.

<details><summary>Ответ</summary>

Traefik запущен без `exposedbydefault=false`, и контейнер Adminer опубликован автоматически
(правило по умолчанию строится из имени контейнера, а с `defaultRule` — по шаблону, например `*.example.com`).
Выключить автопубликацию, закрыть админки middleware `ipAllowList`/`basicAuth` или не пускать их в сеть Traefik.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Чем Traefik отличается от nginx?

<details><summary>Ответ</summary>

nginx — веб-сервер и прокси, конфиг — файл + reload; Traefik сам находит сервисы
в Docker/Kubernetes, меняет маршруты на лету и выпускает сертификаты. Зато nginx лучше
в статике, кеше и тонкой настройке HTTP.

</details>

**2.** Что такое Envoy и почему он в основе service mesh?

<details><summary>Ответ</summary>

Высокопроизводительный L4/L7-прокси на C++, управляемый по API (xDS), с ретраями, circuit
breaking, outlier detection и богатой телеметрией — идеальный data plane, которым control
plane (Istio, Envoy Gateway) управляет централизованно.

</details>

**3.** Что такое xDS?

<details><summary>Ответ</summary>

Набор gRPC API (LDS, RDS, CDS, EDS, SDS, ADS), по которым control plane стримит Envoy
listeners, маршруты, кластеры, endpoints и секреты без reload.

</details>

**4.** Что такое circuit breaker и чем он отличается от retry?

<details><summary>Ответ</summary>

Circuit breaker ограничивает одновременную нагрузку на кластер и сразу отказывает сверх лимита
(защищает бэкенд); retry повторяет неудачный запрос (защищает клиента). Вместе — с бюджетом ретраев.

</details>

**5.** Что такое outlier detection?

<details><summary>Ответ</summary>

Пассивное исключение хоста из балансировки после серии ошибок (5xx, таймауты) на реальном трафике,
на время `base_ejection_time`, растущее с каждым повтором.

</details>

**6.** Как Traefik получает и продлевает сертификаты?

<details><summary>Ответ</summary>

Через `certResolver` (ACME): HTTP-01, TLS-ALPN-01 или DNS-01; хранит в `acme.json`, продлевает сам.

</details>

**7.** Static vs dynamic конфигурация Traefik?

<details><summary>Ответ</summary>

Static — при старте (entrypoints, providers, ACME); dynamic — маршруты, сервисы, middlewares,
меняются на лету из провайдеров.

</details>

**8.** Как отлаживать Envoy, когда «всё 503»?

<details><summary>Ответ</summary>

Access log и response flags → `/clusters` (health flags) → `/stats` (overflow, retry, timeout,
ejections) → `/config_dump` (что реально загружено) → логи control plane.

</details>

**9.** Когда взять Caddy, а когда nginx?

<details><summary>Ответ</summary>

Caddy — когда нужен HTTPS быстро и без обслуживания (небольшой сервис, внутренний инструмент);
nginx — статика, кеш, высокая нагрузка, привычная команде эксплуатация.

</details>

**10.** Что поставишь входной точкой в Kubernetes сегодня и почему?

<details><summary>Ответ</summary>

Реализацию Gateway API (Envoy Gateway, Traefik, Cilium, NGINX Gateway Fabric) —
ingress-nginx уходит в прошлое, а Gateway API стандартен и разделяет роли платформы и команд.

</details>

---

### 🎯 Чек-лист

- [ ] Объясняю модель Traefik и разницу static/dynamic
- [ ] Публикую сервис в Traefik лейблами с health-check, retry и сертификатом
- [ ] Пишу статический конфиг Envoy с ретраями, таймаутами, circuit breaking и outlier detection
- [ ] Читаю `/clusters`, `/stats`, `/config_dump` и response flags Envoy
- [ ] Знаю, что такое xDS и где Envoy работает data plane (Envoy Gateway, Istio)
- [ ] Поднял Caddy с `tls internal` и понимаю automatic HTTPS
- [ ] Заполнил таблицу сравнения прокси на сценарии «бэкенд умер»
- [ ] Могу за 30 секунд объяснить, какой прокси и когда выбрать
