---
title: "03. Трейсинг и OpenTelemetry"
description: "Блок → SRE и Observability → тема 03. Три сигнала введены в"
---

# 03. Трейсинг и OpenTelemetry

> Блок → SRE и Observability → тема 03. Три сигнала введены в
> [../Left/02_Monitoring/01_monitoring_concepts.md](/monitoring/01-monitoring-concepts),
> `trace_id` в логах — в [../Left/03_Logging/03_loki_grafana.md](/logging/03-loki-grafana).
> Здесь — откуда берётся `trace_id`, как устроен трейс и как собрать всё в одну картину.
>
> **После темы ты умеешь:** объяснить trace, span, атрибуты и события; прочитать `traceparent`;
> выбрать head или tail sampling; инструментировать Python-сервис (авто и вручную); написать
> конфиг OTel Collector; искать трейсы в Tempo через TraceQL и прыгать метрика ↔ трейс ↔ лог
> в Grafana, не взорвав кардинальность и бюджет.

---

## 🗺️ Карта темы

```text
 пользователь ─► shop-api ───────────────► payments ─────────► «БД»
                 span: GET /checkout        span: GET /pay       span: db.query
                    │  HTTP-заголовок traceparent: 00-&lt;trace_id&gt;-&lt;span_id&gt;-01
                    ▼
   OTel SDK в приложении ── OTLP ──► OTel Collector ──► Tempo       (трейсы)
   (авто + ручные спаны)             receivers →        Loki        (логи с trace_id)
                                     processors →       Prometheus  (метрики, exemplars)
                                     exporters
                                                   ▼
                          Grafana: метрика ⇄ трейс ⇄ лог — одним кликом
```text
---

## 1. Зачем трейсы, если есть метрики и логи

```text
Метрика:  p99 /checkout = 2 с (было 200 мс)              → ЧТО и КОГДА
Логи:     5 сервисов пишут вперемешку, 40 тысяч строк    → ПОЧЕМУ (если найдёшь нужные)
Трейс:    из 2 с — 1,8 с запрос ждал свободное           → ГДЕ именно
          соединение в пуле payments
```text
Трейсы окупаются, когда запрос проходит через несколько сервисов, очередей и баз:
без них «где тормозит» превращается в гадание по графикам соседних сервисов.
Они **не заменяют** метрики (для алертов и SLO) и логи (для деталей), а связывают их.

---

## 2. Анатомия трейса

```text
trace_id = 4bf92f3577b34da6a3ce929d0e0e4736              0 мс ──────────────────── 180 мс
GET /checkout        shop-api  SERVER    ████████████████████████████████████████  180 мс
 ├─ validate_cart    shop-api  INTERNAL  ██                                         12 мс
 └─ GET              shop-api  CLIENT      ██████████████████████████████████████  160 мс
     └─ GET /pay     payments  SERVER       ████████████████████████████████████   155 мс
         ├─ db.pool.acquire    INTERNAL     ███████████████████████████            120 мс ← ждём пул!
         └─ db.query           INTERNAL                                ████████     35 мс
```text
| Поле спана | Что это |
|------------|---------|
| `trace_id` | 16 байт (32 hex-символа), общий для всех спанов одного запроса |
| `span_id` | 8 байт (16 hex), уникален для спана |
| `parent_span_id` | Родитель; у корневого спана пусто |
| `name` | Операция: `GET /checkout`, `db.query` (без ID и параметров!) |
| `kind` | `SERVER`, `CLIENT`, `INTERNAL`, `PRODUCER`, `CONSUMER` |
| start / end | Время начала и конца → длительность |
| `status` | `UNSET`, `OK`, `ERROR` |
| **attributes** | Ключ-значение: `http.response.status_code=502`, `db.system.name=postgresql` |
| **events** | События с меткой времени внутри спана: `exception`, «retry #2», «deadlock detected» |
| links | Ссылки на другие трейсы (батч-обработка, fan-in из очереди) |
| **resource** | Кто породил: `service.name`, `service.version`, `deployment.environment.name` |

**Semantic conventions** — стандартные имена атрибутов, чтобы бэкенды и дашборды понимали
данные одинаково: `http.request.method`, `http.response.status_code`, `http.route`,
`url.path`, `server.address`, `db.system.name`.

> ⚠️ Python-инструментация по умолчанию пишет **старые** имена (`http.status_code`,
> `http.method`). Новые включаются переменной `OTEL_SEMCONV_STABILITY_OPT_IN=http`
> (так сделано на стенде). Разные имена в разных сервисах ломают запросы и дашборды.

---

## 3. Context propagation: как спаны находят друг друга

Сервисы передают контекст в заголовках по стандарту **W3C Trace Context**:

```text
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
             │  │                                │                │
          версия  trace_id (16 байт)             span_id вызывающего  флаги: 01 = sampled
tracestate:  vendor1=abc,vendor2=xyz     ← данные конкретных вендоров, необязательно
baggage:     tenant=acme,plan=pro        ← ключи-значения, которые едут ВО ВСЕ сервисы ниже
```text
- Пропагаторы задаются `OTEL_PROPAGATORS` (по умолчанию `tracecontext,baggage`);
  для старых систем на Zipkin — `b3`/`b3multi`.
- ⚠️ `baggage` уходит во все нижестоящие вызовы, включая внешние API: никаких секретов
  и персональных данных, и держи его маленьким.

Где контекст рвётся (и трейс распадается на куски):

| Место | Почему | Что делать |
|-------|--------|------------|
| Очереди (Kafka, RabbitMQ) | HTTP-заголовков нет | Класть `traceparent` в заголовки сообщения (`inject`/`extract`) |
| Фоновые задачи, пулы потоков | Контекст живёт в текущем потоке/корутине | Передавать контекст явно |
| Неинструментированный сервис посередине | Он не пробрасывает заголовки | Инструментировать или хотя бы пробрасывать заголовки |
| Шлюз/прокси режет заголовки | Фильтр «неизвестных» заголовков | Разрешить `traceparent`, `tracestate`, `baggage` |
| Cron, CLI | Нет входящего запроса | Это новый трейс — и это нормально |

```python
from opentelemetry import trace
from opentelemetry.propagate import inject, extract

tracer = trace.get_tracer("shop.demo")

# продюсер: положить контекст в заголовки сообщения
headers: dict[str, str] = {}
inject(headers)                      # → {'traceparent': '00-...-01'}
publish(topic="orders", body=order, headers=headers)

# консьюмер: продолжить тот же трейс
ctx = extract(message_headers)
with tracer.start_as_current_span("process order", context=ctx,
                                  kind=trace.SpanKind.CONSUMER):
    handle(order)
```text
---

## 4. Sampling: что сохранять

Хранить всё — дорого:
```text
200 RPS × 20 спанов на запрос × ~700 байт ≈ 2,8 МБ/с ≈ 242 ГБ в сутки
с сэмплингом 10%                                        ≈  24 ГБ в сутки
```text
| | Head sampling | Tail sampling |
|---|---------------|---------------|
| Где решают | В SDK, при создании корневого спана | В Collector, когда трейс завершился |
| По чему решают | Только по `trace_id` (случайно) | По всему трейсу: ошибки, длительность, атрибуты |
| Стоимость | Почти бесплатно | Память: коллектор держит трейсы `decision_wait` секунд |
| Риск | Редкие ошибки теряются с той же вероятностью, что и успешные | Все спаны трейса должны попасть в **один** экземпляр коллектора |
| Настройка | `OTEL_TRACES_SAMPLER=parentbased_traceidratio`, `OTEL_TRACES_SAMPLER_ARG=0.1` | Процессор `tail_sampling` |

```text
parentbased_*: если родитель сэмплирован (флаг 01 в traceparent) — сэмплируем и мы.
               Иначе трейс рвётся: один сервис записал спан, другой — нет.
```text
Tail sampling в нескольких репликах коллектора — двухуровневая схема:
```text
SDK ──► коллекторы-агенты ──► load_balancing exporter ──► коллекторы с tail_sampling ──► Tempo
                              (routing_key: traceID —      (все спаны одного трейса
                               один трейс → один узел)      приходят в один узел)
```text
> ⭐ Метрики из спанов (RPS, ошибки, латентность) считают **до** сэмплинга — иначе RPS
> окажется в 10 раз меньше реального. И SLI никогда не считают по сэмплированным трейсам.

---

## 5. OpenTelemetry: из чего состоит

```text
OpenTracing + OpenCensus ──(2019)──► OpenTelemetry (CNCF): единый стандарт телеметрии
```text
| Часть | Роль |
|-------|------|
| **Specification** | Как должны работать API, SDK, протокол — одинаково для всех языков |
| **API** | То, что вызывает код: `tracer.start_as_current_span(...)`; без SDK — no-op |
| **SDK** | Реализация: сэмплинг, батчинг, экспорт, ресурсы |
| **Instrumentation libraries** | Готовая инструментация FastAPI, Flask, httpx, requests, psycopg, Kafka… |
| **Collector** | Отдельный процесс: принимает, обрабатывает и рассылает телеметрию |
| **OTLP** | Протокол: gRPC на `4317`, HTTP на `4318` |
| **Semantic conventions** | Стандартные имена атрибутов и метрик |

Сигналы: трейсы, метрики и логи — стабильны; профили — в разработке. Зрелость SDK
разная по языкам: смотри статус конкретного языка перед внедрением.
Старые клиенты Jaeger объявлены устаревшими — новые сервисы инструментируют через OTel SDK.

---

## 6. Инструментирование: авто и вручную

| | Автоматическое (zero-code) | Ручное |
|---|----------------------------|--------|
| Как | Агент/обёртка патчит библиотеки при старте | Код создаёт спаны, атрибуты, события |
| Что даёт | HTTP-сервер и клиенты, БД, очереди — «из коробки» | Бизнес-операции: «проверка корзины», «ожидание пула» |
| Усилия | Минуты, без изменения кода | Правка кода, ревью |
| Минус | Не знает бизнес-смысла; бывает шумным | Легко переусердствовать (спан на каждую итерацию цикла) |

Практика: начинают с авто, затем добавляют ручные спаны в узкие места.

**Авто в Python** (так запускается демо-сервис стенда):
```bash
pip install opentelemetry-distro opentelemetry-exporter-otlp
opentelemetry-bootstrap -a install     # доставит инструментации под найденные библиотеки

OTEL_SERVICE_NAME=shop-api \
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
opentelemetry-instrument uvicorn app:app --host 0.0.0.0 --port 8000
```text
⚠️ С `uvicorn --reload` авто-инструментация не работает — только для разработки без трейсов.

| Переменная | Зачем |
|------------|-------|
| `OTEL_SERVICE_NAME` | ⭐ Имя сервиса; без него — `unknown_service` |
| `OTEL_RESOURCE_ATTRIBUTES` | `deployment.environment.name=prod,service.version=1.4.2` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` / `_PROTOCOL` | Куда слать: `http://otel-collector:4317`, `grpc` или `http/protobuf` |
| `OTEL_TRACES_SAMPLER` / `_ARG` | Head sampling: `parentbased_traceidratio` и `0.1` |
| `OTEL_PROPAGATORS` | Формат заголовков: `tracecontext,baggage` |
| `OTEL_LOGS_EXPORTER` + `OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true` | Логи `logging` уходят по OTLP с `trace_id` |
| `OTEL_PYTHON_FASTAPI_EXCLUDED_URLS` | Не трейсить `/metrics`, `/healthz` |
| `OTEL_SEMCONV_STABILITY_OPT_IN=http` | Новые имена HTTP-атрибутов |

**Вручную** — ручные спаны поверх авто (фрагмент `app.py` со стенда):
```python
from opentelemetry import trace

tracer = trace.get_tracer("shop.demo")

@app.get("/pay")
async def pay():
    with tracer.start_as_current_span("db.pool.acquire"):      # видно время ожидания пула
        await POOL.acquire()
    try:
        with tracer.start_as_current_span("db.query") as span:
            span.set_attribute("db.system.name", "postgresql")
            await asyncio.sleep(delay)
            if random.random() < CHAOS["error_rate"]:
                span.add_event("deadlock detected")
                raise HTTPException(status_code=500, detail="db error")
    finally:
        POOL.release()
```text
Исключение, вылетевшее из `with start_as_current_span(...)`, SDK сам запишет событием
`exception` и поставит спану статус `ERROR`.

Достать `trace_id` (для логов, exemplars или заголовка ответа `X-Trace-Id`, по которому
поддержка найдёт трейс):
```python
ctx = trace.get_current_span().get_span_context()
trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None
```text
> 💡 В Kubernetes авто-инструментацию подключает OpenTelemetry Operator: ресурс
> `Instrumentation` плюс аннотация пода `instrumentation.opentelemetry.io/inject-python: "true"`.

---

## 7. OTel Collector

| Компонент | Что делает | Примеры |
|-----------|-----------|---------|
| **receivers** | Принимают данные | `otlp`, `prometheus`, `filelog`, `hostmetrics`, `kafka` |
| **processors** | Меняют, фильтруют, сэмплируют | `memory_limiter`, `batch`, `filter`, `attributes`, `resource`, `k8s_attributes`, `tail_sampling`, `transform` |
| **exporters** | Отправляют дальше | `otlp_grpc`, `otlp_http`, `prometheus`, `debug` |
| **connectors** | Выход одного пайплайна = вход другого | `span_metrics`, `forward`, `count` |
| **extensions** | Служебное | `health_check`, `zpages`, `pprof` |
| **pipelines** | Связывают всё по сигналам | `traces`, `metrics`, `logs` |

```text
   ПАТТЕРНЫ РАЗВЁРТЫВАНИЯ
   agent   — рядом с приложением (DaemonSet на ноде или sidecar): дешёвый сбор,
             k8s-метаданные, локальный буфер
   gateway — отдельный Deployment за балансировщиком: tail sampling, чистка PII,
             маршрутизация, ключи бэкендов в одном месте
   Типично: приложения → agent → gateway → Tempo/Loki/Prometheus
```text
Дистрибутивы: core (`otel/opentelemetry-collector`), contrib
(`otel/opentelemetry-collector-contrib` — почти все компоненты), k8s, свой через
OpenTelemetry Collector Builder (`ocb`). Grafana Alloy — дистрибутив коллектора со своим
языком конфигурации ([../Left/03_Logging/04_collectors.md](/logging/04-collectors)).

«Боевой» конфиг gateway: фильтрация шума, чистка PII, span metrics **до** сэмплинга, tail sampling
(проверен `otelcol-contrib validate`):
```yaml
# otelcol-gateway.yaml
receivers:
  otlp:
    protocols:
      grpc: { endpoint: 0.0.0.0:4317 }   # ⭐ по умолчанию localhost — в контейнере так нельзя
      http: { endpoint: 0.0.0.0:4318 }

processors:
  memory_limiter:                      # 1) всегда первым
    check_interval: 1s
    limit_mib: 1500
    spike_limit_mib: 300
  filter/health:                       # 2) выкинуть шум как можно раньше
    error_mode: ignore
    traces:
      span:
        - 'attributes["url.path"] == "/healthz"'
  attributes/scrub:                    # 3) чистка чувствительных данных
    actions:
      - key: http.request.header.authorization
        action: delete
      - key: user.email
        action: hash
  resource:
    attributes:
      - key: deployment.environment.name
        value: prod
        action: upsert
  tail_sampling:                       # 4) решение по целому трейсу
    decision_wait: 10s
    num_traces: 50000
    policies:
      - name: keep-errors
        type: status_code
        status_code: { status_codes: [ERROR] }
      - name: keep-slow
        type: latency
        latency: { threshold_ms: 500 }
      - name: baseline-10pct
        type: probabilistic
        probabilistic: { sampling_percentage: 10 }
  batch: {}                            # 5) последним

connectors:
  span_metrics:                        # RED-метрики из ВСЕХ спанов (до сэмплинга)
    histogram:
      explicit:
        buckets: [50ms, 100ms, 300ms, 500ms, 1s, 2s, 5s]
    dimensions:
      - name: http.request.method
      - name: http.response.status_code
  forward/sampling: {}                 # «мост» между пайплайнами

exporters:
  otlp_grpc/tempo:
    endpoint: tempo:4317
    tls: { insecure: true }
  prometheus:                          # Prometheus скрейпит span metrics отсюда
    endpoint: 0.0.0.0:8889

extensions:
  health_check: { endpoint: 0.0.0.0:13133 }

service:
  extensions: [health_check]
  pipelines:
    traces/in:                         # всё, что пришло
      receivers: [otlp]
      processors: [memory_limiter, filter/health, attributes/scrub, resource]
      exporters: [span_metrics, forward/sampling]
    traces/sampled:                    # только то, что уйдёт в хранилище
      receivers: [forward/sampling]
      processors: [tail_sampling, batch]
      exporters: [otlp_grpc/tempo]
    metrics/spanmetrics:
      receivers: [span_metrics]
      processors: [batch]
      exporters: [prometheus]
```text
> ⚠️ Имена компонентов переезжают на snake_case: `otlp` → `otlp_grpc`, `otlphttp` → `otlp_http`
> (с v0.144), `spanmetrics` → `span_metrics`, `k8sattributes` → `k8s_attributes`. Старые
> имена пока работают как устаревшие алиасы, но в статьях встретишь оба варианта.
> Экспортера `loki` больше нет — логи в Loki отправляют по OTLP (`http://loki:3100/otlp`).

Отладка коллектора:
| Инструмент | Что покажет |
|------------|-------------|
| `otelcol-contrib validate --config=...` | Ошибки конфига до запуска (неизвестные ключи, опечатки) |
| Экспортер `debug` | Что реально проходит через пайплайн (в логах коллектора) |
| `health_check` (`:13133`) | Жив ли коллектор (для probes) |
| Внутренние метрики (`:8888`, по умолчанию только localhost) | `otelcol_receiver_accepted_spans`, `otelcol_receiver_refused_spans`, `otelcol_exporter_sent_spans`, `otelcol_exporter_send_failed_spans`, `otelcol_exporter_queue_size` |

---

## 8. Бэкенды: Tempo, Jaeger и другие

| | Grafana Tempo | Jaeger | Коммерческие (Datadog, Honeycomb и др.) |
|---|---------------|--------|------------------------------------------|
| Хранение | Объектное хранилище (S3/GCS) или диск, минимальный индекс | Elasticsearch/OpenSearch, Cassandra, Badger, память | SaaS |
| Поиск | По trace_id + TraceQL | По сервису, операции, тегам | Мощный, с аналитикой |
| Стоимость | ⭐ Низкая | Зависит от хранилища | Высокая, за объём |
| Интерфейс | Grafana (связка с Prometheus и Loki) | Свой UI (или Grafana) | Свой |
| Особенности | metrics-generator: service graph и span metrics | Jaeger v2 построен на OTel Collector | Всё в одном |

**TraceQL** — язык запросов Tempo (все примеры проверены на стенде):
```text
{ resource.service.name = "payments" && name = "db.query" && duration > 100ms }
{ status = error }
{ span.http.response.status_code >= 500 }
{ name = "db.pool.acquire" && duration > 500ms }
{ resource.service.name = "shop-api" } >> { resource.service.name = "payments" && status = error }
{ status = error } | select(span.http.response.status_code)
```text
`resource.` — атрибуты сервиса, `span.` — атрибуты спана, `>>` — «потомок где-то ниже»,
`select(...)` — показать атрибут в результатах.

---

## 9. Связка метрики ↔ трейсы ↔ логи в Grafana

```text
   Prometheus                      Tempo                         Loki
 p99 /checkout подскочил ──(1)──► трейс 4bf92f… ──(2)──►  строки лога этого trace_id
        ▲                          │     ▲                           │
        └──────────(4)─────────────┘     └───────────(3)─────────────┘
```text
| # | Переход | Механизм | Что настроить |
|---|---------|----------|---------------|
| 1 | Метрика → трейс | **Exemplars**: к точке гистограммы приложение прикладывает `trace_id` | Приложение пишет exemplar, Prometheus с `--enable-feature=exemplar-storage`, в источнике `exemplarTraceIdDestinations` |
| 2 | Трейс → логи | «Logs for this span» | `tracesToLogsV2` в источнике Tempo |
| 3 | Лог → трейс | Ссылка по полю `trace_id` | `derivedFields` в источнике Loki: regex по телу или `matcherType: label` |
| 4 | Трейс → метрики | RED-метрики сервиса из спана, service graph | `tracesToMetrics`, `serviceMap` + metrics-generator Tempo |

```yaml
# ключевые строки datasources.yml (файл целиком — в лабе 1)
# Prometheus → jsonData:
exemplarTraceIdDestinations:
  - { name: trace_id, datasourceUid: tempo }          # name = имя лейбла exemplar'а
# Tempo → jsonData:
tracesToLogsV2:
  datasourceUid: loki
  tags: [{ key: "service.name", value: "service_name" }]
  customQuery: true
  query: '{$${__tags&#125;&#125; | trace_id="$${__trace.traceId}"'   # $$ — экранирование в provisioning
# Loki → jsonData (trace_id лежит в structured metadata, поэтому matcherType: label):
derivedFields:
  - { name: TraceID, matcherType: label, matcherRegex: trace_id, datasourceUid: tempo, url: "$${__value.raw}" }
```text
Откуда `trace_id` в логах:
- Логи уходят через OTel SDK → Collector → Loki (OTLP): `trace_id` и `span_id` попадают
  в **structured metadata** автоматически, `service.name` → лейбл `service_name`.
  Поиск: `{service_name="shop-api"} | trace_id="4bf92f…"`.
- Логи в stdout (JSON) собирает агент: добавь поле `trace_id` в форматтер логов и
  **не делай его лейблом** — причина в
  [../Left/03_Logging/03_loki_grafana.md](/logging/03-loki-grafana).

---

## 10. Стоимость и кардинальность

| Где | Высокая кардинальность | Правило |
|-----|------------------------|---------|
| Атрибуты спана в Tempo | ✅ Допустима: `order_id`, `user_id` можно (если не PII) | Трейсы для того и нужны — детали конкретного запроса |
| Имя спана | ❌ | `GET /orders/{id}`, а не `GET /orders/83721` |
| Измерения span metrics | ❌ | Только `http.route`, метод, код; никаких `url.path` с ID |
| Лейблы Loki и Prometheus | ❌ | `trace_id` — в тело или structured metadata, не в лейблы |

Рычаги стоимости:
1. **Сэмплинг** (tail: ошибки и медленные — 100%, остальное — 1–10%).
2. **Retention** трейсов короче, чем у метрик: обычно 7–14 дней.
3. **Меньше спанов**: не создавать спан на каждую итерацию цикла; отключить шумные инструментации.
4. **Фильтр** health checks и служебных эндпоинтов в SDK или коллекторе.
5. **Объектное хранилище** (Tempo) вместо индексирующих баз.

Накладные расходы SDK на приложение обычно малы (батчинг, асинхронный экспорт),
но при переполнении очереди SDK **молча выбрасывает спаны** — это видно по метрикам
коллектора (`refused`/`send_failed`) и по «дырявым» трейсам.

---

## 11. Грабли

| Грабля | Симптом | Решение |
|--------|---------|---------|
| Нет `OTEL_SERVICE_NAME` | Сервис `unknown_service:python` | Задать имя в env/манифесте |
| Receiver слушает `localhost` | Коллектор не принимает данные из других контейнеров | `endpoint: 0.0.0.0:4317` |
| Контекст не пробрасывается | Трейс обрывается на очереди/прокси | `inject`/`extract`, разрешить заголовки |
| Head sampling без `parentbased` | Спаны одного трейса сэмплируются вразнобой | `parentbased_traceidratio` |
| Tail sampling в нескольких репликах без балансировки по trace_id | Решения по неполным трейсам | `load_balancing` exporter с `routing_key: traceID` |
| Span metrics после сэмплинга | RPS занижен в 10 раз | Connector до `tail_sampling` |
| ID в имени спана | Взрыв кардинальности в span metrics и UI | Шаблон маршрута в имени |
| `trace_id` лейблом в Loki | Миллионы потоков | Structured metadata или тело строки |
| Разные semconv в сервисах | Запросы и дашборды «видят» половину данных | Единая версия, `OTEL_SEMCONV_STABILITY_OPT_IN` |
| `memory_limiter` не первым / нет вообще | Коллектор падает по OOM на всплеске | `memory_limiter` первым в каждом пайплайне |
| Секреты в атрибутах/baggage | Утечка токенов в хранилище трейсов | `attributes` processor: `delete`/`hash` |

---

## 💼 Как это в DevOps

- Девопс чаще всего отвечает за **коллектор и бэкенд**: Helm-чарт коллектора (agent + gateway),
  Tempo на S3, источники в Grafana, сэмплинг и retention. Разработчики — за SDK и ручные спаны.
- Стандарт на уровне платформы: env-переменные `OTEL_*` в шаблоне деплоя, единое
  `service.name` = имя Deployment, `deployment.environment.name` из окружения.
- Первым делом на инциденте с латентностью открывают exemplar с графика p99
  и смотрят самый длинный спан — это быстрее, чем гадать по графикам соседних сервисов.
- Tail sampling и чистку PII держат в gateway-коллекторе: одно место для правил
  и ключей доступа к бэкендам.
- На собесе спрашивают: «что такое span и trace», «как передаётся контекст», «head vs tail
  sampling», «зачем OTel Collector», «как связать логи и трейсы».

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Авто-инструментация Python | `opentelemetry-bootstrap -a install` + `opentelemetry-instrument &lt;cmd&gt;` |
| Имя сервиса | `OTEL_SERVICE_NAME=shop-api` |
| Куда слать | `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317` |
| Head sampling 10% | `OTEL_TRACES_SAMPLER=parentbased_traceidratio`, `OTEL_TRACES_SAMPLER_ARG=0.1` |
| Ручной спан | `with tracer.start_as_current_span("name") as span:` |
| Атрибут / событие | `span.set_attribute("k", v)` / `span.add_event("retry")` |
| Текущий trace_id | `format(trace.get_current_span().get_span_context().trace_id, "032x")` |
| Передать контекст в очередь | `inject(headers)` → `extract(headers)` |
| Порты OTLP | gRPC `4317`, HTTP `4318` |
| Проверить конфиг коллектора | `otelcol-contrib validate --config=config.yaml` |
| Порядок процессоров | `memory_limiter` → фильтры/атрибуты → `tail_sampling` → `batch` |
| Логи в Loki из коллектора | экспортер `otlp_http`, `endpoint: http://loki:3100/otlp` |
| Медленные спаны в Tempo | `{ name = "db.query" && duration > 100ms }` |
| Ошибки в Tempo | `{ status = error }` |
| Логи по трейсу в Loki | `{service_name="shop-api"} \| trace_id="…"` |

---

## 🧠 Что запомнить

1. Трейс — дерево спанов с общим `trace_id`; спан — операция с временем, статусом,
   атрибутами и событиями.
2. Контекст едет в заголовке `traceparent` (W3C): версия, trace_id, span_id родителя, флаг sampled.
3. Трейсы рвутся на очередях и неинструментированных узлах — контекст передают явно.
4. Head sampling дёшев, но слеп; tail sampling видит весь трейс, но требует памяти
   и маршрутизации по trace_id.
5. ⭐ Метрики из спанов считают до сэмплинга; SLI по сэмплированным трейсам не считают.
6. OpenTelemetry = спецификация + API + SDK + инструментации + Collector + OTLP + semconv.
7. Начинают с авто-инструментации, ручные спаны добавляют в узкие места.
8. В коллекторе `memory_limiter` — первым, `batch` — последним; receivers слушают `0.0.0.0`.
9. Связка в Grafana: exemplars (метрика → трейс), tracesToLogs (трейс → логи),
   derived fields (лог → трейс).
10. Высокая кардинальность допустима в атрибутах спанов, но не в именах спанов,
    span metrics и лейблах Loki/Prometheus.

➡️ Дальше: [04_incident_management.md](/sre/04-incident-management) · задачи: 03_tracing_opentelemetry_tasks.md


---

### Блок A. Теория


**A1.** Чем трейс отличается от спана? Что общего у всех спанов одного трейса?

<details><summary>Ответ</summary>

Спан — одна операция (с началом, концом, статусом, атрибутами); трейс — дерево спанов
одного запроса через все сервисы. Общее у спанов трейса — `trace_id`.

</details>

**A2.** Назови основные поля спана и пять видов `kind`.

<details><summary>Ответ</summary>

`trace_id`, `span_id`, `parent_span_id`, `name`, `kind`, время начала и конца,
`status`, attributes, events, links, resource. Kinds: `SERVER`, `CLIENT`, `INTERNAL`,
`PRODUCER`, `CONSUMER`.

</details>

**A3.** Чем атрибут спана отличается от события спана и от строки лога?

<details><summary>Ответ</summary>

Атрибут описывает весь спан (`http.route=/checkout`). Событие — момент внутри спана
со своим временем (`exception`, «retry #2»). Лог — отдельный сигнал со своим хранилищем;
связь с трейсом — через `trace_id`/`span_id` в записи.

</details>

**A4.** Что такое resource attributes? Какой из них обязателен на практике?

<details><summary>Ответ</summary>

Атрибуты источника телеметрии: `service.name`, `service.version`,
`deployment.environment.name`, k8s-метаданные. Обязателен на практике `service.name`.

</details>

**A5.** ⭐ Разбери заголовок `traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01`.

<details><summary>Ответ</summary>

`00` — версия формата; `4bf92f…4736` — trace_id (16 байт); `00f067aa0ba902b7` —
span_id вызывающего спана (станет parent); `01` — флаг sampled.

</details>

**A6.** Что такое `baggage` и чем он опасен?

<details><summary>Ответ</summary>

Набор ключ-значение, который пропагируется во все нижестоящие вызовы. Опасен тем,
что уходит в том числе во внешние API и логи: секреты и PII там утекают, большой baggage
раздувает каждый запрос.

</details>

**A7.** Назови три места, где рвётся контекст, и как это чинят.

<details><summary>Ответ</summary>

Очереди (класть `traceparent` в заголовки сообщения), фоновые задачи/пулы потоков
(передавать контекст явно), неинструментированный сервис или прокси, режущий заголовки
(инструментировать, разрешить заголовки).

</details>

**A8.** ⭐ Чем head sampling отличается от tail sampling? Плюсы и минусы.

<details><summary>Ответ</summary>

Head: решение в SDK при создании корневого спана, по trace_id — дёшево, но редкие
ошибки теряются. Tail: решение в коллекторе по целому трейсу (ошибки, латентность) —
точнее, но требует памяти и доставки всех спанов трейса в один экземпляр.

</details>

**A9.** Зачем сэмплер `parentbased_*`?

<details><summary>Ответ</summary>

Чтобы решение принималось один раз в корне и уважалось всеми сервисами ниже
по флагу в `traceparent`. Без этого каждый сервис бросает свою монетку — трейсы дырявые.

</details>

**A10.** Почему span metrics считают до сэмплинга?

<details><summary>Ответ</summary>

После сэмплинга остаётся доля трейсов: RPS и ошибки из span metrics окажутся
заниженными (при 10% — в 10 раз), а соотношения — искажены политиками (ошибки хранятся все).

</details>

**A11.** Из каких частей состоит OpenTelemetry? Что такое OTLP и на каких портах он работает?

<details><summary>Ответ</summary>

Спецификация, API, SDK, библиотеки инструментации, Collector, протокол OTLP,
semantic conventions. OTLP: gRPC — `4317`, HTTP — `4318`.

</details>

**A12.** Когда хватает авто-инструментации, а когда нужны ручные спаны?

<details><summary>Ответ</summary>

Авто хватает, чтобы увидеть HTTP, БД, очереди и границы сервисов. Ручные спаны —
для бизнес-операций и узких мест, которых инструментация не видит (ожидание пула,
вычисления, внешние вызовы через свои клиенты).

</details>

**A13.** Из каких компонентов состоит конфиг OTel Collector? Чем agent отличается от gateway?

<details><summary>Ответ</summary>

receivers, processors, exporters, connectors, extensions, service/pipelines.
Agent — рядом с приложением (DaemonSet/sidecar): сбор, метаданные, буфер. Gateway —
отдельный сервис: tail sampling, чистка PII, маршрутизация, ключи бэкендов.

</details>

**A14.** В каком порядке ставят процессоры и почему?

<details><summary>Ответ</summary>

`memory_limiter` первым (защита от OOM до любой работы), затем фильтры и атрибуты
(выкинуть шум и чувствительное как можно раньше), `tail_sampling` перед `batch`,
`batch` последним (отправка пачками).

</details>

**A15.** Что такое exemplars и что нужно, чтобы они заработали?

<details><summary>Ответ</summary>

Пример конкретного измерения (с `trace_id`), прикреплённый к точке метрики.
Нужно: приложение пишет exemplar (OpenMetrics), Prometheus хранит их
(`--enable-feature=exemplar-storage`), в источнике Grafana настроен
`exemplarTraceIdDestinations`.

</details>

**A16.** Чем Tempo отличается от Jaeger?

<details><summary>Ответ</summary>

Tempo хранит трейсы в объектном хранилище почти без индекса и ищет через TraceQL —
дёшево, живёт в Grafana рядом с Prometheus и Loki. Jaeger — отдельный UI и индексирующие
хранилища (Elasticsearch, Cassandra); Jaeger v2 построен на OTel Collector.

</details>

**A17.** Где высокая кардинальность допустима, а где — нет?

<details><summary>Ответ</summary>

Допустима в атрибутах спанов (детали конкретного запроса). Недопустима в именах
спанов, измерениях span metrics, лейблах Prometheus и Loki.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  # коллектор в Docker
```text
<details><summary>Ответ</summary>

⚠️ Receiver слушает только loopback контейнера — приложения из других контейнеров
не достучатся. Нужно `0.0.0.0:4317`.

</details>

```text:no-line-numbers
     receivers:
```text
```text:no-line-numbers
       otlp:
```text
```text:no-line-numbers
         protocols:
```text
```text:no-line-numbers
           grpc: { endpoint: localhost:4317 }
```text
```text:no-line-numbers
B2.  service:
```text
<details><summary>Ответ</summary>

⚠️ `memory_limiter` должен быть первым: иначе батчи копятся в памяти до проверки лимита.

</details>

```text:no-line-numbers
       pipelines:
```text
```text:no-line-numbers
         traces:
```text
```text:no-line-numbers
           receivers: [otlp]
```text
```text:no-line-numbers
           processors: [batch, memory_limiter]
```text
```text:no-line-numbers
           exporters: [otlp_grpc/tempo]
```text
```text:no-line-numbers
B3.  # во всех сервисах
```text
<details><summary>Ответ</summary>

⚠️ Без `parentbased` каждый сервис решает сам: трейсы получаются дырявыми.
Нужно `parentbased_traceidratio`.

</details>

```text:no-line-numbers
     OTEL_TRACES_SAMPLER=traceidratio
```text
```text:no-line-numbers
     OTEL_TRACES_SAMPLER_ARG=0.1
```text
```text:no-line-numbers
B4.  with tracer.start_as_current_span(f"GET /orders/{order_id}"): ...
```text
<details><summary>Ответ</summary>

⚠️ ID в имени спана — неограниченное число имён: взрыв кардинальности span metrics
и мусор в UI. Имя — `GET /orders/{id}`, ID — в атрибут.

</details>

```text:no-line-numbers
B5.  traces:
```text
<details><summary>Ответ</summary>

⚠️ Процессоры пайплайна применяются до всех его экспортеров: span metrics считаются
по сэмплированным данным. Нужен отдельный пайплайн до `tail_sampling` (через `forward`).

</details>

```text:no-line-numbers
       processors: [memory_limiter, tail_sampling, batch]
```text
```text:no-line-numbers
       exporters: [span_metrics, otlp_grpc/tempo]
```text
```text:no-line-numbers
B6.  # агент логов
```text
<details><summary>Ответ</summary>

⚠️ `trace_id` лейблом — миллионы потоков в Loki. Держать в теле строки или
structured metadata.

</details>

```text:no-line-numbers
     labels: { app: shop-api, trace_id: "${TRACE_ID}" }
```text
```text:no-line-numbers
B7.  baggage: user_token=eyJhbGciOiJIUzI1NiJ9...
```text
<details><summary>Ответ</summary>

⚠️ Токен в baggage уедет во все сервисы, логи и внешние API. Никогда не класть
секреты в baggage.

</details>

```text:no-line-numbers
B8.  # две реплики коллектора с tail_sampling за обычным round-robin балансировщиком
```text
<details><summary>Ответ</summary>

⚠️ Спаны одного трейса разъедутся по разным репликам — решения по неполным трейсам.
Нужен уровень с `load_balancing` exporter и `routing_key: traceID`.

</details>

```text:no-line-numbers
B9.  opentelemetry-instrument uvicorn app:app --reload
```text
<details><summary>Ответ</summary>

⚠️ С `--reload` авто-инструментация не работает — трейсов не будет.

</details>

```text:no-line-numbers
B10.  exporters:
```text
<details><summary>Ответ</summary>

⚠️ Экспортера `loki` в contrib больше нет — коллектор не стартует. Логи — через
`otlp_http` на `http://loki:3100/otlp`.

</details>

```text:no-line-numbers
       loki:
```text
```text:no-line-numbers
         endpoint: http://loki:3100/loki/api/v1/push
```text
```text:no-line-numbers
B11.  connectors:
```text
<details><summary>Ответ</summary>

⚠️ `url.path` с ID и `user.id` — неограниченная кардинальность метрик.
Измерения — только `http.route`, метод, код.

</details>

```text:no-line-numbers
       span_metrics:
```text
```text:no-line-numbers
         dimensions: [{ name: url.path }, { name: user.id }]
```text
```text:no-line-numbers
B12.  for item in items:                       # 10 000 элементов
```text
<details><summary>Ответ</summary>

⚠️ 10 000 спанов в одном трейсе с уникальными именами: тяжёлый трейс, переполнение
очереди SDK, кардинальность. Один спан на пачку, счётчик — атрибутом или событием.

</details>

```text:no-line-numbers
         with tracer.start_as_current_span(f"process item {item.id}"): ...
```text
```text:no-line-numbers
B13.  # TraceQL
```text
<details><summary>Ответ</summary>

⚠️ Синтаксическая ошибка: атрибуту нужен скоуп — `span.`, `resource.` или `.`
в начале. Плюс проверь semconv: при `OTEL_SEMCONV_STABILITY_OPT_IN=http` атрибут называется
`http.response.status_code`.

</details>

```text:no-line-numbers
     { http.status_code = 500 }
```text
---

### Блок C. Практика


### C1. 🔑 Первый трейс
**1.** Подними стенд, сделай 20 запросов: `for i in $(seq 20); do curl -s localhost:8080/checkout; done`.

<details><summary>Ответ</summary>

Авто: `GET /checkout` (SERVER), `GET` (CLIENT, httpx), `GET /pay` (SERVER), служебные
`http send`. Ручные: `validate_cart`, `db.pool.acquire`, `db.query`. Граница сервисов —
между CLIENT-спаном shop-api и SERVER-спаном payments.

</details>

**2.** Найди трейс в Grafana (Explore → Tempo → Search).

<details><summary>Ответ</summary>

Трейс сохранится с твоим trace_id, родителем `GET /checkout` станет span_id
`b7ad6b7169203331` из заголовка. С флагом `00` сэмплер `parentbased_*` уважает решение
вызывающего «не сэмплировать» — трейс не запишется.

</details>

**3.** Разбери waterfall: какие спаны создала авто-инструментация, какие — ручные
   (`validate_cart`, `db.pool.acquire`, `db.query`)? Где граница сервисов?

<details><summary>Ответ</summary>

```text
{ resource.service.name = "payments" && name = "db.query" && duration > 100ms }
{ status = error }
{ span.http.response.status_code >= 500 }
{ resource.service.name = "shop-api" } >> { resource.service.name = "payments" && status = error }
{ status = error } | select(span.http.response.status_code)
```text
</details>

### C2. 🔑 traceparent руками
**1.** Придумай trace_id из 32 hex-символов и отправь:
   `curl -H "traceparent: 00-&lt;trace_id&gt;-b7ad6b7169203331-01" localhost:8080/checkout`.

<details><summary>Ответ</summary>

Авто: `GET /checkout` (SERVER), `GET` (CLIENT, httpx), `GET /pay` (SERVER), служебные
`http send`. Ручные: `validate_cart`, `db.pool.acquire`, `db.query`. Граница сервисов —
между CLIENT-спаном shop-api и SERVER-спаном payments.

</details>

**2.** Найди в Tempo трейс с этим ID. Кто родитель спана `GET /checkout`?

<details><summary>Ответ</summary>

Трейс сохранится с твоим trace_id, родителем `GET /checkout` станет span_id
`b7ad6b7169203331` из заголовка. С флагом `00` сэмплер `parentbased_*` уважает решение
вызывающего «не сэмплировать» — трейс не запишется.

</details>

**3.** Повтори с флагом `00` вместо `01`. Что изменилось и почему?

<details><summary>Ответ</summary>

```text
{ resource.service.name = "payments" && name = "db.query" && duration > 100ms }
{ status = error }
{ span.http.response.status_code >= 500 }
{ resource.service.name = "shop-api" } >> { resource.service.name = "payments" && status = error }
{ status = error } | select(span.http.response.status_code)
```text
</details>

### C3. TraceQL
Напиши и проверь пять запросов: медленный `db.query` (> 100 мс), все ошибки, ответы 5xx,
«shop-api вызвал payments, и в payments ошибка», ошибки с выводом кода ответа (`select`).

### C4. 🔑 Найти медленный спан
**1.** `curl -X POST "localhost:8081/chaos?delay_ms=300"`, дай фоновый трафик.

<details><summary>Ответ</summary>

Авто: `GET /checkout` (SERVER), `GET` (CLIENT, httpx), `GET /pay` (SERVER), служебные
`http send`. Ручные: `validate_cart`, `db.pool.acquire`, `db.query`. Граница сервисов —
между CLIENT-спаном shop-api и SERVER-спаном payments.

</details>

**2.** Найди медленные трейсы TraceQL-запросом, определи спан-виновник.

<details><summary>Ответ</summary>

Трейс сохранится с твоим trace_id, родителем `GET /checkout` станет span_id
`b7ad6b7169203331` из заголовка. С флагом `00` сэмплер `parentbased_*` уважает решение
вызывающего «не сэмплировать» — трейс не запишется.

</details>

**3.** Сравни с графиком p99 `/checkout` в Prometheus. Верни `delay_ms=0`.

<details><summary>Ответ</summary>

```text
{ resource.service.name = "payments" && name = "db.query" && duration > 100ms }
{ status = error }
{ span.http.response.status_code >= 500 }
{ resource.service.name = "shop-api" } >> { resource.service.name = "payments" && status = error }
{ status = error } | select(span.http.response.status_code)
```text
</details>

### C5. Exemplars
Построй в Grafana `histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{job="shop-api"}[1m])))`,
включи переключатель Exemplars, кликни по точке и перейди в трейс.

### C6. Логи ↔ трейсы
**1.** Включи ошибки (`error_rate=0.3`), найди в Loki `{service_name="shop-api"} |= "payments error"`.

<details><summary>Ответ</summary>

Авто: `GET /checkout` (SERVER), `GET` (CLIENT, httpx), `GET /pay` (SERVER), служебные
`http send`. Ручные: `validate_cart`, `db.pool.acquire`, `db.query`. Граница сервисов —
между CLIENT-спаном shop-api и SERVER-спаном payments.

</details>

**2.** Из строки лога перейди в трейс (ссылка «Открыть трейс»).

<details><summary>Ответ</summary>

Трейс сохранится с твоим trace_id, родителем `GET /checkout` станет span_id
`b7ad6b7169203331` из заголовка. С флагом `00` сэмплер `parentbased_*` уважает решение
вызывающего «не сэмплировать» — трейс не запишется.

</details>

**3.** Из трейса открой «Logs for this span». Какой LogQL-запрос сгенерировала Grafana?

<details><summary>Ответ</summary>

```text
{ resource.service.name = "payments" && name = "db.query" && duration > 100ms }
{ status = error }
{ span.http.response.status_code >= 500 }
{ resource.service.name = "shop-api" } >> { resource.service.name = "payments" && status = error }
{ status = error } | select(span.http.response.status_code)
```text
</details>

### C7. Ручной спан
Добавь в `/checkout` спан `reserve_stock` с атрибутом `stock.warehouse` и событием
`"stock reserved"`. Пересобери (`docker compose up -d --build shop-api`) и найди его в Tempo.

### C8. Head sampling
Выставь в `x-otel-env` `OTEL_TRACES_SAMPLER=parentbased_traceidratio` и `OTEL_TRACES_SAMPLER_ARG=0.1`.
Сделай 200 запросов, посчитай трейсы в Tempo. Почему не бывает трейсов, где есть спаны
shop-api, но нет спанов payments?

### C9. Заглянуть внутрь коллектора
**1.** Добавь экспортер `debug` c `verbosity: detailed` в пайплайн traces, посмотри
   `docker compose logs otel-collector`.

<details><summary>Ответ</summary>

Авто: `GET /checkout` (SERVER), `GET` (CLIENT, httpx), `GET /pay` (SERVER), служебные
`http send`. Ручные: `validate_cart`, `db.pool.acquire`, `db.query`. Граница сервисов —
между CLIENT-спаном shop-api и SERVER-спаном payments.

</details>

**2.** Посмотри внутренние метрики коллектора: они слушают `localhost:8888` внутри контейнера
   (`docker run --rm --network container:&lt;id коллектора&gt; curlimages/curl -s localhost:8888/metrics`).
   Найди `otelcol_receiver_accepted_spans` и `otelcol_exporter_sent_spans`.

<details><summary>Ответ</summary>

Трейс сохранится с твоим trace_id, родителем `GET /checkout` станет span_id
`b7ad6b7169203331` из заголовка. С флагом `00` сэмплер `parentbased_*` уважает решение
вызывающего «не сэмплировать» — трейс не запишется.

</details>

### C10. Tail sampling
Замени `otelcol.yaml` на вариант с `tail_sampling` из конспекта (пайплайн `traces/in` →
`traces/sampled`). Включи `error_rate=0.1`, дай трафик. Проверь: сохраняются все ошибочные
трейсы и примерно 10% успешных. Проверь конфиг до запуска через `validate`.

### C11. Service graph
Открой в Grafana источник Tempo → вкладку Service Graph. Какие метрики metrics-generator
записал в Prometheus (`traces_service_graph_*`, `traces_spanmetrics_*`)?

---

### Блок D. Инциденты


**D1.** В Tempo спаны shop-api и payments лежат в **разных** трейсах.

<details><summary>Ответ</summary>

Контекст не пробрасывается: HTTP-клиент не инструментирован (например, клиент создан
до инструментации или используется неподдерживаемая библиотека), прокси режет `traceparent`,
разные пропагаторы (`b3` против `tracecontext`), вызов идёт через очередь без заголовков.

</details>

**D2.** Приложение работает, а в Tempo пусто.

<details><summary>Ответ</summary>

Проверить по цепочке: env `OTEL_*` в контейнере (endpoint, exporter), логи приложения
об ошибках экспорта, `otelcol_receiver_accepted_spans` (доходит ли до коллектора),
`otelcol_exporter_send_failed_spans` (уходит ли дальше), логи Tempo, receiver на `0.0.0.0`,
сэмплер (не `always_off`/0%).

</details>

**D3.** Коллектор перезапускается по OOM на каждом всплеске трафика.

<details><summary>Ответ</summary>

Нет `memory_limiter` или он не первым; маленький лимит памяти контейнера;
tail sampling с большим `num_traces`/`decision_wait`. Добавить `memory_limiter`, выставить
лимиты под контейнер, масштабировать gateway горизонтально.

</details>

**D4.** В строке лога есть `trace_id`, но кнопка «Открыть трейс» ведёт на «trace not found».

<details><summary>Ответ</summary>

Трейс не сохранился: сэмплирование (head/tail отбросил), retention трейсов короче,
чем логов, лог старше трейса, в ссылке другой источник или неверный `datasourceUid`.

</details>

**D5.** После включения tail sampling RPS на дашборде из span metrics упал в 10 раз.

<details><summary>Ответ</summary>

Span metrics считаются после сэмплинга. Вынести connector в пайплайн до
`tail_sampling`.

</details>

**D6.** Счёт за хранилище трейсов вырос в 5 раз за месяц.

<details><summary>Ответ</summary>

Проверить объём спанов по сервисам (метрики коллектора, Tempo), новые шумные
инструментации, спаны в циклах, отсутствие сэмплинга, retention. Рычаги: tail sampling,
фильтры, retention 7–14 дней, объектное хранилище.

</details>

**D7.** В медленных трейсах 1,8 с из 2 с занимает спан `db.pool.acquire`. Что это значит?

<details><summary>Ответ</summary>

Запрос почти всё время ждёт свободное соединение: пул исчерпан (saturation).
Смотреть конкурентность (закон Литтла: RPS × время обработки), медленные запросы, которые
держат соединения, размер пула; лечить ускорением запросов, увеличением пула (если БД
выдержит), ограничением входящей нагрузки.

</details>

**D8.** В хранилище трейсов нашли заголовки `Authorization` с токенами.

<details><summary>Ответ</summary>

Удалить атрибуты в коллекторе (`attributes` processor: `delete`), проверить
инструментации, которые пишут заголовки, ротировать утёкшие токены, почистить данные
в хранилище, завести постмортем.

</details>

**D9.** Все трейсы одного сервиса подписаны как `unknown_service:python`.

<details><summary>Ответ</summary>

Не задан `OTEL_SERVICE_NAME` (или `service.name` в `OTEL_RESOURCE_ATTRIBUTES`).

</details>

---

### Блок E. Вопросы с собеседования


**1.** Что такое distributed tracing и зачем он нужен?

<details><summary>Ответ</summary>

Отслеживание пути одного запроса через все сервисы в виде дерева спанов с таймингами —
   чтобы понять, где именно время и ошибки.

</details>

**2.** Чем trace отличается от span?

<details><summary>Ответ</summary>

Span — одна операция; trace — все спаны одного запроса с общим `trace_id`.

</details>

**3.** Как контекст трейса передаётся между сервисами?

<details><summary>Ответ</summary>

Через заголовки (W3C `traceparent`, `tracestate`, `baggage`); в очередях — через заголовки
   сообщений. Инструментация делает inject на клиенте и extract на сервере.

</details>

**4.** Head sampling или tail sampling — в чём разница?

<details><summary>Ответ</summary>

Head — решение в начале, по trace_id, дёшево и слепо; tail — в коллекторе по целому
   трейсу, дороже, но сохраняет все ошибки и медленные запросы.

</details>

**5.** Что такое OpenTelemetry?

<details><summary>Ответ</summary>

Открытый стандарт и набор инструментов (API, SDK, инструментации, Collector, OTLP,
   semconv) для трейсов, метрик и логов, не привязанный к вендору.

</details>

**6.** Зачем OTel Collector, если SDK может слать прямо в бэкенд?

<details><summary>Ответ</summary>

Отвязывает приложения от бэкенда: батчинг и ретраи, tail sampling, чистка PII, обогащение
   метаданными, смена бэкенда без передеплоя приложений, одно место для ключей доступа.

</details>

**7.** Как связать логи, метрики и трейсы?

<details><summary>Ответ</summary>

Единые `service.name`/лейблы, `trace_id` в логах, exemplars в метриках, настройки
   корреляции в Grafana (tracesToLogs, derived fields, exemplar destinations).

</details>

**8.** Что такое exemplars?

<details><summary>Ответ</summary>

Примеры конкретных измерений с `trace_id`, прикреплённые к точкам метрики, — переход
   с графика p99 в конкретный медленный трейс.

</details>

**9.** Tempo или Jaeger — как выбрать?

<details><summary>Ответ</summary>

Tempo — дешёвое хранение в S3 и родная связка с Grafana; Jaeger — свой UI и индексирующие
   хранилища. При стеке Grafana обычно выбирают Tempo.

</details>

**10.** Как контролировать стоимость трейсинга?

<details><summary>Ответ</summary>

Сэмплинг (tail: ошибки и медленные — всё, остальное — процент), короткий retention,
    фильтры шума, разумное число спанов, контроль кардинальности span metrics.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Объясняю trace, span, атрибуты, события и resource
- [ ] ⭐ Разбираю `traceparent` по частям и знаю, где рвётся контекст
- [ ] Объясняю head и tail sampling и зачем `parentbased`
- [ ] Знаю, почему span metrics считают до сэмплинга
- [ ] Стенд поднят, трейс shop-api → payments виден в Tempo
- [ ] ⭐ Нахожу медленный спан через TraceQL и через exemplar на графике
- [ ] Прыгаю лог → трейс → логи спана в Grafana
- [ ] Пишу конфиг OTel Collector и проверяю его `validate`
- [ ] Знаю порядок процессоров и переименования компонентов
- [ ] Контролирую кардинальность и стоимость трейсинга
