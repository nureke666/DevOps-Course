---
title: "07. Практика: 4 лабы по SRE и observability"
description: "Блок → SRE и Observability → практика."
---

# 07. Практика: 4 лабы по SRE и observability

> Блок → SRE и Observability → практика.
> Лабы делаются руками на стенде из [00_INDEX.md](/sre/) и остаются в git.
> После них есть что показать на собесе: трейсинг, SLO с burn-rate алертами, отчёт
> о нагрузочном тесте и постмортем по учениям.
>
> Конфиги ниже проверены целиком (сентябрь 2026): OTel Collector 0.161, Tempo 3.0.0,
> Loki 3.7, Prometheus 3.15, Grafana 13.2, k6 2.3. Эти версии и стоит пинить вместо `latest`.

---

## 📋 Список лаб

| № | Лаба | Что закрепляет | Артефакт |
|---|------|----------------|----------|
| 1 | ⭐ Трейсинг: приложение + OTel Collector + Tempo + Loki + Grafana, найти медленный спан | тема 03 | стенд в git + TraceQL-шпаргалка |
| 2 | ⭐ SLO для сервиса: recording rules, burn-rate алерты, дашборд | тема 02 | `rules/`, `tests/`, дашборд JSON |
| 3 | Нагрузка k6 до срабатывания алерта | темы 02, 06 | `k6/load.js` + отчёт о ёмкости |
| 4 | Game day: сломать зависимость, провести инцидент по ролям, написать постмортем | темы 04, 05, 06 | таймлайн, апдейты, постмортем, runbook |

---

## 🧪 Лаба 1. Трейсинг: найти медленный спан

### Что делаем
Поднимаем стенд: два сервиса (shop-api → payments) с авто- и ручной инструментацией,
OTel Collector, Tempo, Loki, Prometheus, Grafana. Доводим до состояния «с графика p99
одним кликом попадаю в медленный трейс, из трейса — в его логи».

### Каркас
`docker-compose.yml` — в [00_INDEX.md](/sre/), раздел «Стенд». Остальные файлы:

```python
# app/app.py — демо-сервис: одинаковый код для shop-api и payments
import asyncio
import logging
import os
import random
import time

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from opentelemetry import trace
from prometheus_client import REGISTRY, Counter, Histogram
from prometheus_client.openmetrics.exposition import CONTENT_TYPE_LATEST, generate_latest

SERVICE = os.getenv("OTEL_SERVICE_NAME", "app")
PAYMENTS_URL = os.getenv("PAYMENTS_URL", "http://payments:8000")
POOL = asyncio.Semaphore(int(os.getenv("POOL_SIZE", "10")))  # «пул соединений к БД»
CHAOS = {"delay_ms": 0, "error_rate": 0.0}                   # меняется через POST /chaos

log = logging.getLogger(SERVICE)
log.setLevel(logging.INFO)
log.addHandler(logging.StreamHandler())  # stdout; в Loki логи уходят через OTel SDK

tracer = trace.get_tracer("shop.demo")
client = httpx.AsyncClient(timeout=2.0)  # ⭐ таймаут на вызов зависимости
app = FastAPI()

REQS = Counter("http_requests_total", "HTTP-запросы", ["handler", "status"])
LAT = Histogram("http_request_duration_seconds", "Время ответа", ["handler"],
                buckets=(0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1, 2, 5))
for code in ("200", "500", "502", "504"):  # ряды ошибок есть с нуля → нет «No data»
    REQS.labels("/checkout", code)


@app.middleware("http")
async def red_metrics(request: Request, call_next):
    path = request.url.path  # ⚠️ в проде — шаблон маршрута, иначе кардинальность
    if path == "/metrics":
        return await call_next(request)
    start = time.perf_counter()
    status = "500"
    try:
        response = await call_next(request)
        status = str(response.status_code)
        return response
    finally:
        ctx = trace.get_current_span().get_span_context()
        exemplar = {"trace_id": format(ctx.trace_id, "032x")} if ctx.is_valid else None
        LAT.labels(path).observe(time.perf_counter() - start, exemplar=exemplar)
        REQS.labels(path, status).inc()


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/checkout")
async def checkout():
    with tracer.start_as_current_span("validate_cart") as span:
        span.set_attribute("cart.items", random.randint(1, 5))
        await asyncio.sleep(random.uniform(0.005, 0.02))
    try:
        r = await client.get(f"{PAYMENTS_URL}/pay")
        r.raise_for_status()
    except httpx.TimeoutException:
        log.error("payments timeout")
        raise HTTPException(status_code=504, detail="payments timeout")
    except httpx.HTTPError as exc:
        log.error("payments error: %s", exc)
        raise HTTPException(status_code=502, detail="payments error")
    log.info("checkout ok")
    return {"status": "paid"}


@app.get("/pay")
async def pay():
    with tracer.start_as_current_span("db.pool.acquire"):   # ожидание «соединения»
        await POOL.acquire()
    try:
        with tracer.start_as_current_span("db.query") as span:
            span.set_attribute("db.system.name", "postgresql")
            delay = random.uniform(0.03, 0.12) + CHAOS["delay_ms"] / 1000
            if random.random() < 0.005:
                delay += 0.5                                  # редкий медленный запрос — «хвост»
            await asyncio.sleep(delay)
            if random.random() < CHAOS["error_rate"]:
                span.add_event("deadlock detected")
                log.error("db error: deadlock detected")
                raise HTTPException(status_code=500, detail="db error")
    finally:
        POOL.release()
    return {"status": "ok"}


@app.post("/chaos")
async def chaos(delay_ms: int = 0, error_rate: float = 0.0):
    CHAOS.update(delay_ms=delay_ms, error_rate=error_rate)
    log.warning("chaos set: %s", CHAOS)
    return CHAOS


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
```text
```dockerfile
# app/Dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn httpx prometheus-client \
        opentelemetry-distro opentelemetry-exporter-otlp \
 && opentelemetry-bootstrap -a install
COPY app.py .
CMD ["opentelemetry-instrument", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```text
```yaml
# otelcol.yaml — OTLP → Tempo (трейсы) и Loki (логи)
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317       # ⭐ по умолчанию localhost — из других контейнеров не достучаться
      http:
        endpoint: 0.0.0.0:4318

processors:
  memory_limiter:                    # первым: защищает коллектор от OOM
    check_interval: 1s
    limit_mib: 400
    spike_limit_mib: 100
  batch: {}                          # последним: отправка пачками

exporters:
  otlp_grpc/tempo:                   # до v0.144 этот экспортер назывался `otlp`
    endpoint: tempo:4317
    tls:
      insecure: true
  otlp_http/loki:                    # до v0.144 — `otlphttp`
    endpoint: http://loki:3100/otlp
  debug:
    verbosity: basic

extensions:
  health_check:
    endpoint: 0.0.0.0:13133

service:
  extensions: [health_check]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp_grpc/tempo]
    logs:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp_http/loki]
```text
```yaml
# tempo.yaml
stream_over_http_enabled: true
server:
  http_listen_port: 3200

distributor:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: "0.0.0.0:4317"
        http:
          endpoint: "0.0.0.0:4318"

storage:
  trace:
    backend: local
    wal:
      path: /var/tempo/wal
    local:
      path: /var/tempo/blocks

metrics_generator:                  # span metrics и service graph → Prometheus
  registry:
    external_labels:
      source: tempo
  storage:
    path: /var/tempo/generator/wal
    remote_write:
      - url: http://prometheus:9090/api/v1/write
        send_exemplars: true

overrides:
  defaults:
    metrics_generator:
      processors: [service-graphs, span-metrics]

usage_report:
  reporting_enabled: false
```text
```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - /etc/prometheus/rules/*.yml

scrape_configs:
  - job_name: shop-api
    static_configs: [{ targets: ["shop-api:8000"] }]
  - job_name: payments
    static_configs: [{ targets: ["payments:8000"] }]
  - job_name: tempo
    static_configs: [{ targets: ["tempo:3200"] }]
  - job_name: prometheus
    static_configs: [{ targets: ["localhost:9090"] }]
```text
```yaml
# grafana/provisioning/datasources/datasources.yml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    uid: prometheus
    url: http://prometheus:9090
    isDefault: true
    jsonData:
      exemplarTraceIdDestinations:          # exemplar trace_id → кнопка «открыть трейс»
        - name: trace_id
          datasourceUid: tempo

  - name: Tempo
    type: tempo
    uid: tempo
    url: http://tempo:3200
    jsonData:
      serviceMap:
        datasourceUid: prometheus           # service graph из metrics-generator
      nodeGraph:
        enabled: true
      tracesToLogsV2:                       # спан → логи этого трейса в Loki
        datasourceUid: loki
        spanStartTimeShift: "-5m"
        spanEndTimeShift: "5m"
        tags: [{ key: "service.name", value: "service_name" }]
        customQuery: true
        query: '{$${__tags&#125;&#125; | trace_id="$${__trace.traceId}"'

  - name: Loki
    type: loki
    uid: loki
    url: http://loki:3100
    jsonData:
      derivedFields:                        # строка лога → трейс в Tempo
        - name: TraceID
          matcherType: label                # trace_id лежит в structured metadata
          matcherRegex: trace_id
          datasourceUid: tempo
          url: "$${__value.raw}"
          urlDisplayLabel: "Открыть трейс"
```text
```bash
mkdir -p rules && docker compose up -d --build
for i in $(seq 50); do curl -s -o /dev/null localhost:8080/checkout; done
```text
### Требования
- [ ] Все сервисы в `docker compose ps` — `running`, конфиги написаны руками и каждая строка объяснима
- [ ] В Tempo виден трейс `GET /checkout` со спанами обоих сервисов (граница — CLIENT → SERVER)
- [ ] Найдены ручные спаны `validate_cart`, `db.pool.acquire`, `db.query`
- [ ] После `curl -X POST "localhost:8081/chaos?delay_ms=300"` медленный спан находится
      TraceQL-запросом и через exemplar на графике p99
- [ ] Из строки лога в Loki — переход в трейс; из трейса — «Logs for this span»
- [ ] Собрана TraceQL-шпаргалка из 5+ запросов, проверенных на стенде
- [ ] Коллектор проверен `validate` до запуска; объяснено, почему receiver слушает `0.0.0.0`
- [ ] Бонус: коллектор с tail sampling из темы 03 — ошибки сохраняются все, успешные ~10%

### Критерии приёмки
```bash
curl -s localhost:13133                         # {"status":"Server available",...}
curl -s localhost:3200/ready                    # ready
curl -s localhost:3100/loki/api/v1/labels       # есть service_name
# (у Loki 3.7 на этом стенде /ready может долго отвечать 503 — ориентируйся на ответ API)
curl -s -G localhost:3200/api/search \
  --data-urlencode 'q={ resource.service.name = "payments" && name = "db.query" }' \
  --data-urlencode limit=3 | jq '.traces[].traceID'
curl -s -G localhost:3100/loki/api/v1/query_range \
  --data-urlencode 'query={service_name="shop-api"} | trace_id!=""' \
  --data-urlencode limit=3 | jq '.data.result | length'
curl -s -H 'Accept: application/openmetrics-text' localhost:8080/metrics | grep -m2 trace_id
docker run --rm -v "$PWD/otelcol.yaml":/cfg.yaml:ro \
  otel/opentelemetry-collector-contrib:latest validate --config=/cfg.yaml
```text
### Вопросы себе
- Почему в трейсе есть служебные спаны `http send`, и где их отключить?
- Что сломается, если убрать `OTEL_SEMCONV_STABILITY_OPT_IN` в одном сервисе, но не в другом?
- Чем `docker compose pause payments` отличается от `stop` в трейсах и кодах ответа?
- Сколько места займут трейсы при 200 RPS за сутки и что сделает сэмплинг 10%?

---

## 🧪 Лаба 2. ⭐ SLO: recording rules, burn-rate алерты, дашборд

### Что делаем
Заводим SLO «99,9% запросов /checkout без 5xx за 30 дней» и латентный SLO «99% быстрее
300 мс» по всем правилам темы 02: правила в git, unit-тесты, дашборд через provisioning.

### Каркас
- `rules/slo-shop-api.yml` — recording rules и алерты из
  [02_sli_slo_error_budget.md](/sre/02-sli-slo-error-budget) (раздел 10), плюс свои правила
  `job:slo_slow_requests:ratio_rate*` для латентного SLO.
- `tests/slo-shop-api_test.yml` — unit-тест из того же раздела + тест «тишины».
- Provisioning дашборда:
```yaml
# grafana/provisioning/dashboards/dashboards.yml
apiVersion: 1
providers:
  - name: sre
    folder: SRE
    type: file
    allowUiUpdates: false
    options:
      path: /etc/grafana/provisioning/dashboards/json
```text
JSON дашборда (экспорт из UI: Share → Export) кладётся в `grafana/provisioning/dashboards/json/`.

### Требования
- [ ] 7 recording rules доступности + правила латентности, `promtool check rules` проходит
- [ ] Алерты `...BurnFast` (critical) и `...BurnSlow` (warning) с `runbook_url`
- [ ] Unit-тесты: 2% ошибок → страница; 0,05% → тишина; сломанный порог роняет тест
- [ ] Правила загружены без перезапуска (`/-/reload`), на `/rules` у всех `health: ok`
- [ ] Дашборд: SLI за 30 дней, остаток бюджета, burn rate 1h/6h с линиями 14,4 и 6,
      доля ошибок против цели, список алертов; лежит в git и раскатывается provisioning'ом
- [ ] Error budget policy на одну страницу (тема 01, C4) лежит рядом с правилами
- [ ] Проверено: `error_rate=0.3` → `BurnFast` firing; замерены время срабатывания и затухания
- [ ] Бонус: те же SLO сгенерированы Sloth, отличия от ручных правил объяснены

### Критерии приёмки
```bash
PT='docker run --rm -v '"$PWD"':/w -w /w --entrypoint promtool prom/prometheus:latest'
$PT check rules rules/slo-shop-api.yml
$PT test rules tests/slo-shop-api_test.yml
curl -s -X POST localhost:9090/-/reload
curl -s localhost:9090/api/v1/rules | jq '.data.groups[].rules[] | {name, health}'
curl -s localhost:9090/api/v1/alerts | jq '.data.alerts[] | {a: .labels.alertname, s: .state}'
curl -s -u admin:admin 'localhost:3000/api/search?query=shop-api' | jq '.[].title'
```text
### Вопросы себе
- Почему на стенде `BurnSlow` загорается почти одновременно с `BurnFast`, а в проде — нет?
- Что покажет панель SLI, если 5xx ещё ни разу не было, и почему в коде есть цикл
  `for code in (...)`?
- Какой SLO предложить продукту для `/checkout` и какими цифрами его обосновать?

---

## 🧪 Лаба 3. Нагрузка k6 до срабатывания алерта

### Что делаем
Находим «колено» производительности стенда, доводим сервис до burn-rate алерта,
по трейсам находим узкое место, применяем одно улучшение и сравниваем.

### Каркас
```javascript
// k6/load.js
import http from 'k6/http';
import { check } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';

export const options = {
  scenarios: {
    ramp: {
      executor: 'ramping-arrival-rate',   // открытая модель: задаём RPS, а не число юзеров
      startRate: 10,
      timeUnit: '1s',
      preAllocatedVUs: 50,
      maxVUs: 500,
      stages: [
        { target: 50, duration: '2m' },   // разогрев
        { target: 100, duration: '3m' },  // около расчётной ёмкости payments
        { target: 200, duration: '5m' },  // за пределом — ищем «колено» и алерт
        { target: 0, duration: '1m' },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate&lt;0.01'],                 // ≤ 1% ошибок
    http_req_duration: ['p(95)<300', 'p(99)<1000'], // латентность в мс
    checks: ['rate&gt;0.99'],
  },
};

export default function () {
  const res = http.get(`${BASE_URL}/checkout`, { tags: { name: 'checkout' } });
  check(res, { 'status 200': (r) => r.status === 200 });
}
```text
```bash
# фоновый трафик (в отдельном терминале), чтобы у SLI была база
while true; do curl -s -o /dev/null localhost:8080/checkout; sleep 0.2; done

# нагрузка с метриками k6_* в Prometheus
docker compose run --rm -e K6_PROMETHEUS_RW_TREND_STATS='p(95),p(99),max' \
  k6 run -o experimental-prometheus-rw /scripts/load.js; echo "exit=$?"
```text
### Требования
- [ ] Перед прогоном записана гипотеза: ёмкость по закону Литтла (пул 10, ~75 мс → ~133 RPS)
- [ ] Во время прогона открыт дашборд: RPS, p95/p99, доля ошибок по кодам, burn rate
- [ ] Найдено «колено» (RPS, при котором p95 резко растёт) и сравнено с гипотезой
- [ ] Зафиксировано, когда стали pending/firing `BurnFast` и `BurnSlow`
- [ ] По трейсам определено узкое место (какой спан растёт), по логам — какие ошибки
- [ ] Применено одно улучшение (bulkhead с быстрым 503, `POOL_SIZE=20` или ретраи с jitter),
      прогон повторён, результаты сравнены в таблице
- [ ] Отчёт на одну страницу: предел, узкое место, что поменяли, какой запас по ёмкости

### Критерии приёмки
```bash
# 99 — thresholds провалены (ожидаемо при нагрузке выше колена), 0 — все пройдены
docker compose run --rm k6 run /scripts/load.js; echo "exit=$?"
curl -s -G localhost:9090/api/v1/query \
  --data-urlencode 'query=sum by (status) (increase(http_requests_total{job="shop-api",handler="/checkout"}[15m]))' | jq
curl -s -G localhost:9090/api/v1/query --data-urlencode 'query=k6_http_req_duration_p95' | jq '.data.result | length'
```text
### Вопросы себе
- Почему после колена успешных ответов в секунду становится **меньше**, чем до него?
- Что означает `dropped_iterations` и почему closed-модель (VU + `sleep`) это спрятала бы?
- Почему p95 на графике упирается ровно в 5 секунд? (Подсказка: корзины гистограммы.)
- Что будет с базой, если «улучшением» станет HPA на 20 подов с пулом по 10 соединений?

---

## 🧪 Лаба 4. Game day: инцидент по ролям и постмортем

### Что делаем
Проводим учения: ведущий тайно ломает зависимость, команда проводит инцидент по всем
правилам темы 04, затем пишет постмортем по шаблону темы 05.

### Подготовка (за день)
- [ ] Роли: **ведущий** (ломает и следит за безопасностью), **IC**, **Ops**, **Comms**, **Scribe**.
      Соло-вариант: ведущий — таймер со случайной задержкой, остальные роли — на одном
      человеке, но с раздельными записями
- [ ] Steady state записан: SLI доступности и латентности, текущие значения
- [ ] Для каждого сценария — гипотеза: какой алерт придёт, через сколько, что сделаем
- [ ] Runbook для `ShopApiErrorBudgetBurnFast` (тема 04) готов, таблица SEV под рукой
- [ ] Условия остановки: учения прекращаются, если стенд нужен для другого или
      ведущий видит, что сценарий вышел из-под контроля; ограничение — 60–90 минут

### Карточки сценариев (ведущий выбирает 1–2, не раскрывая)
| Сценарий | Как сломать | Что проверяем |
|----------|-------------|---------------|
| Зависание payments | `docker compose pause payments` | Таймауты, 504, скорость обнаружения |
| Ошибки payments | `curl -X POST "localhost:8081/chaos?error_rate=0.3"` | Burn-rate алерт, трейсы с ошибками, логи |
| Насыщение пула | `/chaos?delay_ms=150` + фоновая нагрузка k6 | Латентный SLO, `db.pool.acquire` в трейсах |
| Коллектор упал | `docker compose stop otel-collector` | Замечаем ли, что пропали трейсы и логи? |

### Проведение
```text
T+0     ведущий ломает, фиксирует время
        команда: detect → triage (SEV, канал/файл инцидента, IC) → mitigate → resolve
        Comms: апдейты по шаблону каждые 10 минут (на учениях ритм чаще)
        Scribe: таймлайн в UTC
T+end   ведущий раскрывает сценарий; 15 минут горячего разбора: гипотеза против факта
```text
### Требования
- [ ] Таймлайн в UTC с событиями, решениями и командами
- [ ] Минимум три статус-апдейта по шаблону и один «внешний»
- [ ] Посчитаны MTTD, MTTA, MTTM; сравнены с гипотезами
- [ ] Постмортем по шаблону темы 05: влияние через SLO, факторы, хорошо/плохо/повезло
- [ ] 3–5 action items с типами, владельцами и сроками; хотя бы один — на обнаружение
- [ ] Runbook обновлён по итогам (что в нём не сработало)
- [ ] Для сценария «коллектор упал» — предложен алерт, который бы это поймал

### Критерии приёмки
```text
sre-lab/gameday/2026-10-xx/
├── plan.md            # steady state, гипотезы, условия остановки
├── timeline.md        # UTC, события и решения
├── updates.md         # статус-апдейты
└── postmortem.md      # по шаблону, с action items
```text
### Вопросы себе
- Что заметили бы раньше пользователи, чем алерт? Как это исправить?
- Какой шаг runbook оказался бесполезным или неверным?
- Что изменилось бы, будь это SEV1 ночью с незнакомым дежурным?

---

## 🏁 Что должно остаться после блока

```text
sre-lab/                          # репозиторий стенда
├── docker-compose.yml, app/, otelcol.yaml, tempo.yaml, prometheus.yml
├── rules/slo-shop-api.yml        # recording rules + burn-rate алерты
├── tests/slo-shop-api_test.yml   # unit-тесты алертов
├── grafana/provisioning/         # источники с корреляцией + SLO-дашборд
├── k6/load.js + reports/         # нагрузочный тест и отчёт о ёмкости
├── runbooks/shop-api-slo.md
├── policy/error-budget.md
└── gameday/…/postmortem.md
```text
Это артефакт, который превращает ответ «знаю, что такое SLO и трейсинг» в «вот мои SLO
с тестами алертов, вот трейс, где видно узкое место, вот постмортем по учениям».

➡️ Дальше: [08_interview.md](/mlops/08-interview)
