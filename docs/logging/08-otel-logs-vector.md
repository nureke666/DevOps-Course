---
title: "08. Логи через OpenTelemetry и Vector"
description: "Модель LogRecord, логи по OTLP, file_log и оператор container, что Loki делает с OTLP, Alloy как дистрибутив OTel Collector, Vector и VRL"
---

# 08. Логи через OpenTelemetry и Vector

> Блок → Логи → тема 08. Опирается на [04. Сборщики логов](/logging/04-collectors) (сборщики, буферы)
> и тему SRE про трейсинг и OpenTelemetry (OTLP, устройство
> OTel Collector, `trace_id`). Основы коллектора здесь не повторяются — только то, что нужно логам.
>
> **После темы ты умеешь:** объяснить модель лог-записи OTel и зачем логи по OTLP; собрать логи
> контейнеров коллектором и отправить в Loki на `/otlp`, понимая, что станет лейблом; выбрать
> между Alloy, upstream-коллектором, Vector и Fluent Bit; написать VRL для разбора и маскирования.
>
> Проверено на стенде (сентябрь 2026): OTel Collector contrib **0.161.0**, Loki **3.7.8**,
> Alloy **v1.20.0**, Vector **0.58.0**, Python SDK **1.45.0**. Конфиги ниже прошли `validate`
> и живой прогон. Имена компонентов и версии меняются быстро — «проверь, сентябрь 2026».

---

## 🗺️ Карта темы

```text:no-line-numbers
 ПУТЬ 1: код знает про OTel                  ПУТЬ 2: код пишет в stdout (как обычно)
 logging / logback / zap                      {"level":"error","msg":"…","trace_id":"4bf9…"}
      │ log bridge (LoggingHandler)                │ container runtime
      ▼                                            ▼
 OTel SDK: resource + trace_id                /var/log/pods/<ns>_<pod>_<uid>/<c>/0.log (k8s)
 из активного спана                           /var/lib/docker/containers/<id>/<id>-json.log
      │ OTLP 4317/4318                             │ file_log + оператор container
      └──────────────►  OTel Collector / Alloy  ◄──┘
                        memory_limiter → k8s_attributes → batch
                                  │ otlp_http
                                  ▼
                        Loki /otlp → лейблы (resource) + structured metadata (остальное)
                                  ▲
 Альтернатива: Vector — docker_logs / kubernetes_logs → remap (VRL) → loki / elasticsearch
```

---

## 1. Логи как сигнал OpenTelemetry

OTel не придумывает новый логгер: код пишет в привычный `logging`/logback/zap, а **log bridge**
(handler/appender) превращает запись в `LogRecord`. Logs Bridge API — для авторов мостов,
а не для прикладного кода.

| Поле `LogRecord` | Что это | Пример со стенда |
|------------------|---------|------------------|
| `Timestamp` | Когда событие произошло (часы источника) | `2026-09-28T10:02:31.412Z` |
| `ObservedTimestamp` | Когда его увидел сборщик | момент чтения строки агентом |
| `SeverityText` / `SeverityNumber` | Уровень как в исходнике / нормализованный 1–24 | `ERROR` / `17` |
| `Body` | Тело: строка или структура | `"card declined"` |
| `Attributes` | Поля конкретного события | `order.id=A-1042`, `code.line.number=22` |
| `Resource` | Кто породил (общий для всех сигналов) | `service.name=billing`, `k8s.pod.name=…` |
| `InstrumentationScope` | Имя логгера/библиотеки | `billing` |
| `TraceId` / `SpanId` / `TraceFlags` | Связь со спаном (W3C Trace Context) | `42d9fc65…` / `413b9734…` |
| `EventName` | Класс события (для событий, не обычных логов) | `browser.page_view` |

`SeverityNumber`: TRACE 1–4, DEBUG 5–8, INFO 9–12, WARN 13–16, ERROR 17–20, FATAL 21–24 —
чтобы `warn`, `WARNING` и `W` из разных языков сравнивались как одно и то же.

**Статус (проверь, сентябрь 2026):** модель данных, Bridge API и OTLP для логов стабильны, зрелость
SDK — по языкам: C++, .NET, PHP — stable, Go — release candidate, Python — Development (модули
`opentelemetry.sdk._logs` с подчёркиванием, API может меняться). Смотри opentelemetry.io/status.

---

## 2. Зачем логи по OTLP

Один конвейер и один агент на три сигнала; `trace_id`/`span_id` SDK берёт из активного спана сам;
общий resource (`service.name`, `deployment.environment.name`) у метрик, трейсов и логов — переходы
в Grafana без регулярок; типизированные атрибуты без парсинга; смена бэкенда = смена exporter'а.

| | stdout (JSON) + агент | OTLP прямо из SDK |
|---|------------------------|-------------------|
| `trace_id` в записи | Кладёшь в форматтер сам | Автоматически |
| `kubectl logs` / `docker logs` | Работают | ❌ Не видят (если нет второго handler'а в stdout) |
| Коллектор недоступен | Строка лежит в файле, агент дочитает | Очередь SDK в памяти переполнится — записи выброшены |
| Логи nginx, рантайма, системы | ✅ | ❌ Только то, что код пишет через SDK |

> 💡 Частая практика: stdout остаётся всегда (дёшево, переживает падение коллектора), `trace_id` —
> в JSON-форматтер; OTLP из SDK включают там, где команда уже на OTel. Два пути для одного
> сервиса без исключения одного из них — это дубли (§10).

---

## 3. Путь 1: из приложения через SDK

Без кода: `opentelemetry-instrument` + `OTEL_LOGS_EXPORTER=otlp` +
`OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true` — так на стенде из практики SRE
(лаба 1). Руками (проверено, SDK 1.45.0):

```python
# sdk_demo.py — pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
import logging
from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

resource = Resource.create({"service.name": "billing", "deployment.environment.name": "lab"})
trace.set_tracer_provider(TracerProvider(resource=resource))
provider = LoggerProvider(resource=resource)                # тот же resource, что у трейсов
provider.add_log_record_processor(
    BatchLogRecordProcessor(OTLPLogExporter(endpoint="http://otelcol:4318/v1/logs")))
set_logger_provider(provider)

log = logging.getLogger("billing")                           # → InstrumentationScope
log.setLevel(logging.INFO)                                   # иначе INFO отсечёт root (WARNING)
log.addHandler(LoggingHandler(level=logging.INFO, logger_provider=provider))  # мост logging → OTel

with trace.get_tracer("billing").start_as_current_span("charge"):
    log.error("card declined", extra={"order.id": "A-1042", "amount": 990})   # extra → attributes
provider.shutdown()                                          # ⭐ дослать батч перед выходом
```

- `trace_id`/`span_id` появились сами — запись сделана внутри спана; `extra` стали атрибутами
  (в Loki `order.id` → `order_id`). Без `shutdown()` короткий скрипт выйдет раньше, чем уйдёт батч.
- ⚠️ SDK сам добавил `service.instance.id` (UUID на каждый запуск). Loki по умолчанию делает его
  **лейблом** — каждый рестарт даёт новый поток. Лечение — в §5.

---

## 4. Путь 2: файлы → `file_log` (агент DaemonSet'ом)

Ресивер `file_log` (до v0.149 — `filelog`) читает файлы и прогоняет строки через цепочку
**операторов** (движок stanza): `container`, `json_parser`, `regex_parser`, `move`, `remove`,
`filter`, `recombine` (multiline после `container`).

Ключевое: `start_at` по умолчанию `end` (старое не читается), `include_file_path` по умолчанию
`false` (а он нужен `container`), `storage` — позиции в `file_storage`, `retry_on_failure` —
пауза чтения вместо потери, `multiline` (`line_start_pattern`) — склейка стектрейсов.

**Оператор `container`** снимает обёртку рантайма: форматы `docker` (`{"log","stream","time"}`),
`crio`, `containerd` (CRI: `<time> stdout F <строка>`), без `format` определяет сам; склеивает
строки, порезанные рантаймом (флаги `P`/`F`, `max_log_size` 1 MiB); при
`add_metadata_from_filepath: true` (по умолчанию) достаёт из пути `/var/log/pods/...` resource
`k8s.namespace.name`, `k8s.pod.name`, `k8s.pod.uid`, `k8s.container.name`,
`k8s.container.restart_count`, а поток `stdout`/`stderr` — в `log.iostream`.

```yaml
# otel-agent.yaml — DaemonSet; env K8S_NODE_NAME из spec.nodeName (без неё validate падает)
extensions:
  file_storage: { directory: /var/lib/otelcol/storage, create_directory: true }  # hostPath
receivers:
  file_log:
    include: [/var/log/pods/*/*/*.log]
    exclude: [/var/log/pods/observability_otel-agent-*/*/*.log]   # не читать самого себя
    start_at: end                                          # ⚠️ по умолчанию; на стенде — beginning
    include_file_path: true                                # ⭐ без него container не найдёт k8s.*
    include_file_name: false
    storage: file_storage                                  # позиции — как --storage.path у Alloy
    retry_on_failure: { enabled: true }
    operators:
      - { type: container, id: container-parser }         # CRI/docker → body + k8s.* из пути
      - type: json_parser                                  # JSON приложения → attributes
        on_error: send_quiet                               # не JSON — дальше как есть, без шума
        severity: { parse_from: attributes.level }
processors:
  memory_limiter: { check_interval: 1s, limit_percentage: 80, spike_limit_percentage: 20 }
  k8s_attributes:                                          # до переименования — k8sattributes
    auth_type: serviceAccount
    filter: { node_from_env_var: K8S_NODE_NAME }           # ⭐ только поды своей ноды
    pod_association:
      - sources: [{ from: resource_attribute, name: k8s.pod.uid }]   # uid уже дал container
      - sources: [{ from: connection }]                    # OTLP из SDK — по IP соединения
    extract:
      metadata: [k8s.namespace.name, k8s.pod.name, k8s.deployment.name, k8s.node.name]
      labels: [{ tag_name: service.name, key: app.kubernetes.io/name, from: pod }]
  resource:
    attributes: [{ key: k8s.cluster.name, value: prod-kz, action: upsert }]
  batch: {}
exporters:
  otlp_http/loki:                                          # до v0.144 — otlphttp
    endpoint: http://loki-gateway.observability.svc/otlp   # сам допишет /v1/logs
    sending_queue: { enabled: true, storage: file_storage }   # ⭐ очередь на диске
    retry_on_failure: { enabled: true, max_elapsed_time: 0s } # 0 — ретраить без ограничения
service:
  extensions: [file_storage]
  pipelines:
    logs:
      receivers: [file_log]
      processors: [memory_limiter, k8s_attributes, resource, batch]
      exporters: [otlp_http/loki]
```

- `k8s_attributes` ходит в API: ClusterRole с `get`/`list`/`watch` на `pods`, `namespaces`,
  `nodes`, `replicasets` (из ReplicaSet выводится имя Deployment). Для OTLP из SDK
  (`from: connection`) под узнаётся по IP соединения — поэтому агент на ноде, а не за балансировщиком.
- Готовое: Helm-чарт `opentelemetry-collector` с пресетами `logsCollection` и `kubernetesAttributes`.
- ⚠️ Переименования в snake_case: `filelog` → `file_log`, `k8sattributes` → `k8s_attributes`,
  `otlphttp` → `otlp_http`. Старые имена проходят `validate` молча — в статьях встретишь оба.

---

## 5. Loki и OTLP: что станет лейблом

Loki 3.x принимает OTLP сам (`http://loki:3100/otlp`); экспортера `loki` в коллекторе больше нет.
Нужны `allow_structured_metadata: true` (по умолчанию в 3.x) и схема `v13`.

| Что в OTLP | Куда в Loki |
|------------|-------------|
| Resource-атрибуты из списка по умолчанию | ⭐ **Лейблы**, точки → `_`: `service.name` → `service_name` |
| Остальные resource-атрибуты, scope, атрибуты записи | **Structured metadata** — хранится при строке, не индексируется |
| `TraceId` / `SpanId` / `Flags` | Structured metadata `trace_id`, `span_id`, `flags` |
| `SeverityText` / `SeverityNumber` | `severity_text`, `severity_number`; Loki добавляет `detected_level` |
| `Body` | Сама строка лога (не строку — сериализует) |
| `Timestamp` | Время записи; нет — `ObservedTimestamp`; нет обоих — время приёма |

Лейблы по умолчанию (17): `service.name`, `service.namespace`, `service.instance.id`,
`deployment.environment.name`, `cloud.region`, `cloud.availability_zone`, `k8s.cluster.name`,
`k8s.namespace.name`, `k8s.pod.name`, `k8s.container.name`, `container.name`, `k8s.deployment.name`,
`k8s.replicaset.name`, `k8s.statefulset.name`, `k8s.daemonset.name`, `k8s.job.name`, `k8s.cronjob.name`.

> ⚠️ `service.instance.id` и `k8s.pod.name` меняются на каждый рестарт/деплой. Проверено на стенде:
> правило `action: structured_metadata` для атрибута из списка по умолчанию его **не** понижает —
> помогает только `ignore_defaults: true` + свой список.

```yaml
# loki-config.yaml — фрагмент (проверен на 3.7.8)
limits_config:
  otlp_config:
    resource_attributes:
      ignore_defaults: true                 # ⭐ список лейблов задаём сами
      attributes_config:
        - action: index_label               # index_label — только для resource-атрибутов
          attributes: [service.name, deployment.environment.name, k8s.namespace.name, k8s.container.name]
    log_attributes:
      - action: drop                        # structured_metadata | drop
        attributes: [log.file.path, log.file.name]
```

Structured metadata фильтруется после `|` без парсера:
```text:no-line-numbers
{service_name="orders"} | trace_id="d98b820ac44d794f3d1719dfd84ff277"
{service_name="orders", deployment_environment_name="lab"} | severity_text="error"
sum by (severity_text) (count_over_time({service_name="orders"}[5m]))
```

---

## 6. Alloy как дистрибутив OTel

Внутри Alloy — компоненты коллектора под именами `otelcol.*`, связанные через `output {}` вместо
секции `pipelines` (проверено на v1.20.0):

```text:no-line-numbers
otelcol.receiver.filelog "app" {         // ⚠️ public-preview: alloy run --stability.level=public-preview
  include           = ["/var/lib/docker/containers/*/*-json.log"]
  start_at          = "end"
  include_file_path = true
  operators = [
    {type = "container", format = "docker", add_metadata_from_filepath = false},
    {type = "json_parser", on_error = "send_quiet"},
  ]
  output { logs = [otelcol.processor.batch.default.input] }   // + memory_limiter — как в §4
}

otelcol.processor.batch "default" {
  output { logs = [otelcol.exporter.otlphttp.loki.input] }
}

otelcol.exporter.otlphttp "loki" {
  client { endpoint = "http://loki:3100/otlp" }
}
```

| Upstream (YAML) | Alloy |
|-----------------|-------|
| `otlp`, `file_log` | `otelcol.receiver.otlp`, `otelcol.receiver.filelog` (public-preview) |
| `memory_limiter`, `batch`, `transform` | `otelcol.processor.memory_limiter` / `.batch` / `.transform` |
| `k8s_attributes`, `otlp_http`, `file_storage` | `otelcol.processor.k8sattributes`, `otelcol.exporter.otlphttp`, `otelcol.storage.file` |
| — | Мосты: `otelcol.receiver.loki` (записи `loki.*` → OTLP), `otelcol.exporter.loki` (OTLP → push API) |

Перевод: `alloy convert --source-format=otelcol --output=config.alloy otelcol.yaml` — в v1.20.0
перевёл `file_log`, `k8s_attributes`, `file_storage`, но отказался от `resource` и `health_check`.

**Когда что:** Alloy — стек Grafana, `loki.*` и OTLP в одном агенте, легаси Promtail; upstream —
вендор-нейтральный стандарт, Helm-чарт/Operator от OTel, gateway с tail sampling. Бывает и вместе:
Alloy на нодах, upstream-коллектор gateway'ем — они говорят по OTLP.

---

## 7. Vector

### 7.1 Архитектура

Vector (Rust) — граф **sources → transforms → sinks**, связанный полем `inputs`. Агент
(DaemonSet, `kubernetes_logs`) или агрегатор (принимает от агентов, парсит, маршрутизирует).
Принадлежит **Datadog** (купил автора, Timber, в 2021), лицензия MPL-2.0, версии всё ещё `0.x`:
0.58.0 от 26.08.2026. С 0.55 API — gRPC вместо GraphQL (порт `8686`, на нём `vector top`/`tap`).
Sources: `docker_logs`, `kubernetes_logs`, `file`, `journald`, `opentelemetry`, `vector`.
Transforms: `remap` (VRL), `route`, `filter`, `sample`, `dedupe`, `reduce`.
Sinks: `loki`, `elasticsearch`, `aws_s3`, `kafka`, `opentelemetry`, `console`.

### 7.2 VRL — язык преобразований

VRL компилируется при старте: неверный тип — ошибка **до** запуска. Функции, которые могут упасть
(`parse_json`, `parse_timestamp`…), требуют обработки: `x, err = f(...)` — разбираешь сам;
`f!(...)` — при ошибке событие уходит дальше **без изменений**, ошибка — в лог Vector;
`f(...) ?? default` — значение по умолчанию.

```coffee
# JSON приложения + маскирование PII (remap из vector.yaml ниже, проверено на стенде)
parsed, err = parse_json(.message)
if err != null || !is_object(parsed) {
  .parse_error = true                                    # не JSON — пометить, но не терять
} else {
  . = merge(., object!(parsed))                          # поля JSON — в корень события
  .message = del(.msg)
  ts, err = parse_timestamp(.ts, "%+")                   # время события, а не чтения
  if err == null { .timestamp = ts }
  del(.ts)
}
if is_string(.user_email) {
  .user_email = replace(string!(.user_email), r'^[^@]+', "***")   # ***@example.com
}
.message = redact(string(.message) ?? "", filters: [r'[\w.+-]+@[\w-]+\.[\w.-]+'])  # e-mail в тексте → [REDACTED]
del(.label)                                              # docker-лейблы контейнера — шум
del(.container_id)
del(.container_created_at)
```

```coffee
# access-лог nginx (формат combined) → поля
. = parse_nginx_log!(.message, "combined")   # client, user, timestamp, request, status, size, referer, agent
parts = split(string!(.request), " ")
.method = parts[0]
.path = split(string!(parts[1]), "?")[0]     # ⭐ без query string — иначе кардинальность
.level = if .status >= 500 { "error" } else if .status >= 400 { "warn" } else { "info" }
del(.agent)
```

Отладка без стенда: `vector vrl --input event.json --program nginx.vrl --print-object` (строка
`"POST /api/orders?id=42 HTTP/1.1" 502` → `method=POST`, `path=/api/orders`, `level=error`).
Неразобранное отсеивают: у `remap` `drop_on_error: true` + `reroute_dropped: true`, выход `<id>.dropped`.

### 7.3 Маршрутизация в Loki и Elasticsearch

```yaml
# vector.yaml (проверен: vector validate + прогон с Loki 3.7.8)
data_dir: /var/lib/vector                    # ⭐ дисковые буферы и чекпоинты — на том
api: { enabled: true, address: 0.0.0.0:8686 }
sources:
  app_logs:
    type: docker_logs
    include_labels: ["com.docker.compose.service=app"]   # только наш сервис
transforms:
  app_parse:
    type: remap
    inputs: [app_logs]
    source: |
      # ← сюда программа «JSON + PII» из §7.2 (с таким же отступом)
  split:
    type: route
    inputs: [app_parse]
    route: { errors: '.level == "error"' }   # остальное — split._unmatched
sinks:
  loki:
    type: loki
    inputs: [app_parse]                      # в Loki — всё
    endpoint: http://loki:3100               # /loki/api/v1/push допишет сам
    encoding: { codec: json }                # строка = событие целиком в JSON
    labels: { job: vector, service: "{{ service }}", level: "{{ level }}" }   # только низкая кардинальность
    structured_metadata: { trace_id: "{{ trace_id }}" }  # ⭐ не лейбл, но фильтруется без парсера
    buffer: { type: disk, max_size: 268435488, when_full: block }   # минимум ~256 МиБ
  es_errors:                                 # в Elasticsearch/OpenSearch — только ошибки
    type: elasticsearch
    inputs: [split.errors]
    endpoints: ["http://elasticsearch:9200"]
    mode: bulk                               # или data_stream
    bulk: { index: "app-errors-%Y.%m.%d" }
    healthcheck: { enabled: false }
```

OpenSearch обычно пишут тем же sink'ом `elasticsearch` (совместимый bulk API) — проверь свою
версию. Лейбл `service_name` Loki вывел сам из лейбла `service`.

### 7.4 Буферы и backpressure

Буфер — у каждого sink'а: **memory** (по умолчанию, `max_events: 500`, теряется при падении) или
**disk** (`max_size` от ~256 МиБ, WAL в `data_dir`, переживает рестарт). `when_full: block`
(по умолчанию) — давление идёт вверх по графу: transforms ждут, source перестаёт читать (файлы
дочитает позже, TCP/HTTP-клиенты тормозят или получают отказ); `drop_newest` — сбросить новое.
⚠️ При fan-out один недоступный sink с `block` останавливает и соседей: `route` ждёт, пока все
выходы примут событие. Второстепенным — `drop_newest`, важным — disk. `acknowledgements.enabled:
true` у sink'а заставляет source ждать подтверждения записи.

---

## 8. Сравнение: Alloy, OTel Collector, Vector, Fluent Bit

Fluent Bit подробно — в [04. Сборщики логов](/logging/04-collectors), §2.

| | **Grafana Alloy** | **OTel Collector (contrib)** | **Vector** | **Fluent Bit** |
|---|-------------------|------------------------------|------------|----------------|
| Кто стоит | Grafana Labs | CNCF (OpenTelemetry) | Datadog | CNCF (Fluent) |
| Язык | Go | Go | Rust | C |
| Конфиг | Синтаксис Alloy, `forward_to`/`output` | YAML: receivers → processors → exporters | YAML/TOML: sources → transforms → sinks | INI/YAML: input → filter → output |
| Сигналы | Логи, метрики, трейсы, профили | Логи, метрики, трейсы | Логи, метрики (трейсы — ограниченно) | Логи, метрики, трейсы (OTLP) |
| Преобразования | `loki.process`, OTTL | OTTL, операторы stanza | ⭐ VRL | Фильтры, Lua |
| Буфер на диске | `otelcol.storage.file`; у `loki.write` WAL — experimental | `sending_queue` + `file_storage` | disk-буфер на sink | `storage.type filesystem` |
| Память (порядок) | ~100 МБ+ | ~50–200 МБ | ~50 МБ | ~10–40 МБ |
| Когда | Стек Grafana, один агент на всё | Стандарт OTel, gateway | Сложный разбор, агрегатор | Самый лёгкий агент |

---

## 9. Мини-лаба: один лог — три агента

Стенд блока (вариант A: loki, alloy, grafana) в `~/labs/logging`
плюс приложение, коллектор и Vector. Loki 3.x (проверено на `grafana/loki:3.7.8`), Linux: на Docker
Desktop каталог `/var/lib/docker/containers` живёт внутри VM.

**Шаг 1. Приложение** — `app/gen.py`, JSON с `trace_id` в stdout:
```python
import json, os, random, secrets, time
from datetime import datetime, timezone

SERVICE = os.getenv("SERVICE", "orders")
while True:
    status = random.choice([200] * 8 + [404, 500])
    print(json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "level": "error" if status >= 500 else "info",
        "service": SERVICE, "path": "/api/orders", "status": status,
        "msg": "order failed" if status >= 500 else "order created",
        "duration_ms": random.randint(5, 900),
        "trace_id": secrets.token_hex(16), "span_id": secrets.token_hex(8),
        "user_email": f"user{random.randint(1, 99)}@example.com",   # ⚠️ PII — замаскируем
    }), flush=True)
    time.sleep(0.5)
```

**Шаг 2. Дописать в `docker-compose.yml`:**
```yaml
  app:
    image: python:3.12-slim
    command: ["python", "-u", "/app/gen.py"]
    environment: { SERVICE: orders }
    volumes: ["./app:/app:ro"]

  otelcol:
    image: otel/opentelemetry-collector-contrib:0.161.0
    user: "0"                                    # ⚠️ файлы docker читает только root
    command: ["--config=/etc/otelcol/config.yaml"]
    volumes:
      - ./otelcol-logs.yaml:/etc/otelcol/config.yaml:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - otelcol-data:/var/lib/otelcol            # ⭐ позиции чтения (file_storage)
    ports: ["4318:4318", "13133:13133"]

  vector:
    image: timberio/vector:0.58.0-debian
    volumes:
      - ./vector.yaml:/etc/vector/vector.yaml:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - vector-data:/var/lib/vector              # ⭐ disk-буфер и чекпоинты
    ports: ["8686:8686"]

volumes: { alloy-data: {}, otelcol-data: {}, vector-data: {} }   # вместо строки volumes стенда
```

**Шаг 3. `otelcol-logs.yaml`** — docker-вариант агента из §4 (плюс OTLP-вход для `sdk_demo.py`):
```yaml
extensions:
  file_storage: { directory: /var/lib/otelcol/storage, create_directory: true }
  health_check: { endpoint: 0.0.0.0:13133 }
receivers:
  otlp:
    protocols: { http: { endpoint: 0.0.0.0:4318 } }
  file_log:
    include: [/var/lib/docker/containers/*/*-json.log]
    start_at: end
    include_file_path: true
    storage: file_storage
    operators:
      - { type: container, format: docker, add_metadata_from_filepath: false }   # путь не k8s-овый
      - type: json_parser
        on_error: send_quiet
        timestamp: { parse_from: attributes.ts, layout_type: gotime, layout: '2006-01-02T15:04:05.000Z07:00' }
        severity: { parse_from: attributes.level }
        trace: { trace_id: { parse_from: attributes.trace_id }, span_id: { parse_from: attributes.span_id } }
      - { type: filter, expr: 'attributes.service == nil' }   # выбросить не наш JSON (Loki, сам коллектор)
      - { type: move, from: attributes.service, to: 'resource["service.name"]' }
      - { type: move, from: attributes.msg, to: body }
      - { type: remove, field: attributes.user_email }   # PII — не отправлять вовсе
      - { type: remove, field: attributes.ts }
processors:
  memory_limiter: { check_interval: 1s, limit_mib: 200, spike_limit_mib: 50 }
  resource:
    attributes: [{ key: deployment.environment.name, value: lab, action: upsert }]
  batch: {}
exporters:
  otlp_http/loki: { endpoint: http://loki:3100/otlp }
service:
  extensions: [file_storage, health_check]
  pipelines:
    logs:
      receivers: [otlp, file_log]
      processors: [memory_limiter, resource, batch]
      exporters: [otlp_http/loki]
```
`vector.yaml` — из §7.3; sink `es_errors` закомментируй, пока не поднят ELK (вариант B), иначе его
буфер заполнится и `block` остановит поток в Loki. После этого `split.errors has no consumers` —
нормально; `Healthcheck failed … 503` на старте — Loki ещё не ready, Vector всё равно начнёт слать.

**Шаг 4. Проверка:**
```bash
docker run --rm -v "$PWD/otelcol-logs.yaml":/c.yaml:ro otel/opentelemetry-collector-contrib:0.161.0 validate --config=/c.yaml
docker run --rm -v "$PWD/vector.yaml":/etc/vector/vector.yaml:ro timberio/vector:0.58.0-debian validate --no-environment
docker compose up -d && curl -s localhost:13133                 # коллектор жив
curl -s localhost:3100/loki/api/v1/labels | jq -c              # service_name, deployment_environment_name, job…
```
```text:no-line-numbers
{service_name="orders"} | trace_id="<скопируй из любой строки>"
sum by (job, service_name) (count_over_time({service_name=~"orders|logging-app-1"} |= "order created" [1m]))
```
Второй запрос покажет **три копии** каждой строки: Alloy стенда (`job="docker"`,
`service_name="logging-app-1"`, сырой JSON), коллектор (`service_name="orders"`, тело
`order created`, поля в structured metadata) и Vector (`job="vector"`, JSON с `***@example.com`).

**Шаг 5. Убрать дубли** — один агент на сервис. В `config.alloy` стенда, в `discovery.relabel "docker"`:
```text:no-line-numbers
  rule {
    source_labels = ["__meta_docker_container_label_com_docker_compose_service"]
    regex         = "app"
    action        = "drop"
  }
```
и выбери, кто остаётся для `app`: коллектор или Vector (второго — `docker compose stop`).

**Вопросы себе:** чем отличается строка у трёх агентов? Что будет без тома `otelcol-data`?

---

## 10. Грабли

| Грабля | Симптом | Решение |
|--------|---------|---------|
| Два агента читают одни логи (Alloy + коллектор, SDK + stdout) | Каждая строка в Loki 2–3 раза | Один путь на сервис: `exclude`/`drop` во втором |
| `start_at: end` на первом запуске | «Логов нет», хотя файлы есть | `beginning` для стенда; в проде — `end` + `storage` |
| Нет `storage` / `data_dir` на томе | Рестарт — дубли или дыра | `file_storage` / `data_dir` на hostPath или томе |
| Время не разобрано или неверный layout | Время = момент чтения, сортировка «прыгает» | `timestamp` в `json_parser` (проверь layout), `parse_timestamp` в VRL |
| Multiline не настроен | Стектрейс — 30 записей | `multiline` у `file_log` или `recombine` после `container` |
| Высококардинальный атрибут стал лейблом | Тысячи потоков, `service_instance_id` с UUID | `otlp_config`: `ignore_defaults` + свой список |
| ID в `labels` Vector | Взрыв потоков | В `labels` — `service`/`level`; `trace_id` — в `structured_metadata` |
| Коллектор читает свои логи + `debug` exporter | Лавина записей | `exclude` пути агента, `debug` — `basic` и временно |
| Коллектор не root | `permission denied` на файлах docker | `user: "0"` на стенде, `runAsUser: 0` + read-only hostPath |
| `otelcol.receiver.filelog` в Alloy | `stability level "public-preview"` при старте | `alloy run --stability.level=public-preview` |
| Один sink недоступен, `when_full: block` | Vector перестал слать везде | `drop_newest` второстепенным, disk важным, алерт |

---

## 💼 Как это в DevOps

- В новых кластерах всё чаще **один агент на три сигнала** (OTel Collector или Alloy DaemonSet'ом),
  gateway — отдельно; Loki 3.x первым делом получает `otlp_config` со своим списком лейблов.
- Приложения по-прежнему пишут JSON в stdout; OTLP из SDK включают по сервису, выключая сбор его файлов.
- Vector ставят там, где нужен тяжёлый разбор и маршрутизация: агрегатор перед Elasticsearch/S3/Kafka,
  замена Logstash, маскирование PII на границе.
- Метрики агента — в Prometheus: коллектор (`:8888`) — `otelcol_exporter_sent_log_records`,
  `otelcol_exporter_send_failed_log_records`, `otelcol_exporter_queue_size`; Vector (`internal_metrics`
  → `prometheus_exporter`) — `vector_buffer_size_events`, `vector_component_discarded_events_total`,
  `vector_component_errors_total`.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Логи Python по OTLP без кода | `OTEL_LOGS_EXPORTER=otlp` + `OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true` |
| Читать логи подов | `file_log`, `include: [/var/log/pods/*/*/*.log]`, оператор `container` |
| Позиции на диске | `file_storage` (+ `create_directory: true`) и `storage:` у ресивера |
| Метаданные k8s | `k8s_attributes` + `filter.node_from_env_var` + RBAC |
| Отправить в Loki | `otlp_http`, `endpoint: http://loki:3100/otlp` |
| Свой список лейблов Loki | `otlp_config.resource_attributes.ignore_defaults: true` + `index_label` |
| Найти по trace_id | `{service_name="orders"} \| trace_id="…"` |
| YAML коллектора → Alloy | `alloy convert --source-format=otelcol --output=config.alloy otelcol.yaml` |
| Разобрать / замаскировать в Vector | `parse_json(.message)`, `redact(..., filters: [r'…'])`, `replace(...)` |
| Проверить конфиги | `otelcol-contrib validate --config=…`, `vector validate --no-environment`, `vector vrl` |
| Посмотреть поток Vector | `vector top`, `vector tap` (API на `:8686`) |

---

## 🧠 Что запомнить

1. Лог-запись OTel = время (+ observed), severity (текст и номер 1–24), body, attributes, resource,
   scope и `trace_id`/`span_id`.
2. Код не переписывают: log bridge превращает записи `logging`/logback в OTel-записи.
3. OTLP для логов — один конвейер и автоматическая корреляция; stdout остаётся надёжным путём,
   а два пути для одного сервиса — это дубли.
4. Файлы подов: `file_log` + `container` (формат, склейка `P`/`F`, `k8s.*` из пути) +
   `k8s_attributes`; `memory_limiter` первым, `batch` последним.
5. ⭐ Позиции (`file_storage`) и очередь экспортера на диске — иначе рестарт даёт дубли или потери.
6. Loki `/otlp`: resource из списка по умолчанию — лейблы, остальное (`trace_id`, `severity_text`) —
   structured metadata; `service.instance.id` и `k8s.pod.name` убирают через `ignore_defaults`.
7. Alloy — дистрибутив OTel с `otelcol.*`; Alloy vs upstream — стек Grafana против стандарта.
8. Vector — sources → transforms → sinks, сила в VRL; буфер memory/disk, `when_full: block`
   передаёт давление назад по графу и соседним sink'ам.
9. В лейблы — сервис, окружение, namespace, уровень; ID — только в structured metadata или теле.

---

## Задачи

> Стенд: Loki-стек блока + app, otelcol и Vector из мини-лабы (§9).
> Трейсы и базовый коллектор — тема SRE про трейсинг и OpenTelemetry.

---

### Блок A. Теория

**A1.** Перечисли поля `LogRecord` в OTel. Чем `Timestamp` отличается от `ObservedTimestamp`?

<details><summary>Ответ</summary>

`Timestamp`, `ObservedTimestamp`, `SeverityText`, `SeverityNumber`, `Body`, `Attributes`,
`Resource`, `InstrumentationScope`, `TraceId`, `SpanId`, `TraceFlags`, `EventName`.
`Timestamp` — когда событие произошло по часам источника, `ObservedTimestamp` — когда запись
увидел сборщик; если время из строки не разобрано, есть только второе.

</details>

**A2.** Зачем нужен `SeverityNumber`, если есть `SeverityText`? Какие диапазоны у INFO и ERROR?

<details><summary>Ответ</summary>

Тексты уровней в языках разные (`warn`, `WARNING`, `W`), номер нормализует их для
сравнения и фильтрации. INFO — 9–12, ERROR — 17–20.

</details>

**A3.** Что такое log bridge и почему прикладной код не вызывает Logs Bridge API напрямую?

<details><summary>Ответ</summary>

Мост (handler/appender) между привычной библиотекой логирования и OTel: код пишет
в `logging`/logback, мост превращает запись в `LogRecord`. Bridge API — для авторов мостов,
чтобы не переписывать миллионы строк прикладного кода.

</details>

**A4.** Чем resource отличается от attributes? Приведи по два примера того и другого.

<details><summary>Ответ</summary>

Resource — кто породил, общий для всех сигналов процесса: `service.name`,
`k8s.pod.name`. Attributes — поля конкретного события: `order.id`, `http.response.status_code`.

</details>

**A5.** ⭐ Назови три причины отправлять логи по OTLP и три случая, когда stdout + агент лучше.

<details><summary>Ответ</summary>

За OTLP: один конвейер на три сигнала, автоматический `trace_id`/`span_id`, общий resource
без парсинга. За stdout: работают `kubectl logs`/`docker logs`; падение коллектора не теряет
логи — они в файле; собираются логи nginx, рантайма и всего, что не пишет через SDK.

</details>

**A6.** Что даёт оператор `container` у `file_log`? Какие форматы он понимает и что достаёт из пути?

<details><summary>Ответ</summary>

Снимает обёртку рантайма (`docker` json-file, `crio`, `containerd`, формат определяет сам),
склеивает строки, порезанные рантаймом (флаги `P`/`F`), и из пути `/var/log/pods/...` достаёт
`k8s.namespace.name`, `k8s.pod.name`, `k8s.pod.uid`, `k8s.container.name`,
`k8s.container.restart_count`; поток — в `log.iostream`.

</details>

**A7.** Зачем `include_file_path: true` и что будет без него?

<details><summary>Ответ</summary>

Кладёт путь файла в `log.file.path`. Без него оператору `container` не из чего доставать
метаданные пода (`add_metadata_from_filepath`) — разбор падает или метаданных нет.

</details>

**A8.** Почему `start_at: end` по умолчанию может выглядеть как «логи не собираются»?

<details><summary>Ответ</summary>

Коллектор читает только новые строки: если файлы уже записаны и в них ничего не
добавляется (стенд, тест), в бэкенд ничего не приходит. Для первого запуска — `beginning`,
в проде — `end` + сохранённые позиции.

</details>

**A9.** Как коллектор хранит позиции чтения и очередь отправки на диске?

<details><summary>Ответ</summary>

Расширение `file_storage` (каталог на hostPath/томе, `create_directory: true`):
ресивер `file_log` хранит в нём позиции (`storage:`), экспортер — очередь
(`sending_queue.storage`).

</details>

**A10.** Что делает `k8s_attributes`, как он находит под для записи из файла и для записи из SDK?

<details><summary>Ответ</summary>

Добавляет метаданные из API Kubernetes: владельца (Deployment, StatefulSet), labels,
annotations, ноду. Для записей из файлов — по `k8s.pod.uid`, который дал `container`
(`pod_association: from: resource_attribute`); для SDK — по IP входящего соединения
(`from: connection`), поэтому агент должен стоять на той же ноде, а не за балансировщиком.

</details>

**A11.** ⭐ Что Loki делает с OTLP-записью: что становится лейблом, что — structured metadata,
что — строкой?

<details><summary>Ответ</summary>

Resource-атрибуты из списка по умолчанию → лейблы (точки → `_`); прочие resource,
scope и все атрибуты записи, а также `trace_id`, `span_id`, `severity_text`, `severity_number`
→ structured metadata; `Body` → строка; время — `Timestamp`, иначе `ObservedTimestamp`,
иначе время приёма.

</details>

**A12.** Почему `service.instance.id` и `k8s.pod.name` в списке лейблов по умолчанию — проблема?
Как её решить?

<details><summary>Ответ</summary>

Они меняются на каждый рестарт или деплой — каждый раз новый поток, индекс пухнет,
запросы замедляются. Решение — `otlp_config.resource_attributes.ignore_defaults: true` и свой
список `index_label`; правило `structured_metadata` для атрибута из дефолтного списка не помогает.

</details>

**A13.** Как устроен Alloy относительно OTel Collector? Когда выберешь Alloy, а когда upstream?

<details><summary>Ответ</summary>

Alloy — дистрибутив OTel Collector: компоненты `otelcol.*` плюс пайплайны `loki.*`
и `prometheus.*`, свой синтаксис вместо YAML. Alloy — стек Grafana, один агент на всё, легаси
Promtail; upstream — вендор-нейтральный стандарт, Helm-чарт/Operator OTel, gateway.

</details>

**A14.** Из чего состоит конфиг Vector? Кто владеет проектом и что это значит для команды?

<details><summary>Ответ</summary>

`sources` → `transforms` → `sinks`, связанные полем `inputs`; плюс `data_dir`, `api`.
Владелец — Datadog (с 2021), лицензия MPL-2.0, версии 0.x: развитие определяет вендор,
breaking changes между минорами — changelog читать обязательно.

</details>

**A15.** Что такое fallible-функция в VRL? Чем отличаются `f!()`, `x, err = f()` и `f() ?? v`?

<details><summary>Ответ</summary>

Функция, которая может вернуть ошибку; VRL требует обработать её до запуска.
`f!()` — при ошибке событие уходит без изменений (ошибка в лог); `x, err = f()` — обрабатываешь
сам; `f() ?? v` — подставляешь значение по умолчанию.

</details>

**A16.** Как устроены буферы Vector и что такое backpressure? Чем опасен fan-out?

<details><summary>Ответ</summary>

У каждого sink'а буфер memory (500 событий, теряется при падении) или disk (от ~256 МиБ,
переживает рестарт). При заполнении `when_full: block` (по умолчанию) давление идёт вверх: transforms
ждут, source перестаёт читать. При fan-out один заблокированный sink останавливает и соседей;
`drop_newest` — сбросить новое, не тормозя граф.

</details>

**A17.** Какие переименования компонентов коллектора встречаются в статьях и конфигах?

<details><summary>Ответ</summary>

`filelog` → `file_log`, `k8sattributes` → `k8s_attributes`, `otlphttp` → `otlp_http`,
`otlp` → `otlp_grpc`; старые имена работают как устаревшие алиасы. В Alloy — свои имена:
`otelcol.receiver.filelog`, `otelcol.processor.k8sattributes`, `otelcol.exporter.otlphttp`.

</details>

---

### Блок B. «Что делает / что тут не так»

```yaml
B1.  receivers:
       file_log:
         include: [/var/log/pods/*/*/*.log]
         operators:
           - type: container

B2.  receivers:
       file_log:
         include: [/var/log/pods/*/*/*.log]
         include_file_path: true
         start_at: beginning
         operators: [{ type: container }]
     # под DaemonSet без тома, storage не задан

B3.  processors:
       batch: {}
       memory_limiter: { check_interval: 1s, limit_mib: 400 }
     service:
       pipelines:
         logs: { receivers: [file_log], processors: [batch, memory_limiter], exporters: [otlp_http/loki] }

B4.  exporters:
       otlp_http/loki:
         endpoint: http://loki:3100/loki/api/v1/push

B5.  extensions:
       file_storage:
         directory: /var/lib/otelcol/storage
     # коллектор не стартует: «directory must exist»

B6.  processors:
       k8s_attributes:
         filter: { node_from_env_var: K8S_NODE_NAME }
     # в манифесте DaemonSet переменной K8S_NODE_NAME нет

B7.  # Loki limits_config
     otlp_config:
       resource_attributes:
         attributes_config:
           - action: structured_metadata
             attributes: [service.instance.id]
     # после этого service_instance_id всё ещё лейбл

B8.  # Loki limits_config
     otlp_config:
       log_attributes:
         - action: index_label
           attributes: [http.route]
```

<details><summary>Ответ</summary>

**B1.** Нет `include_file_path: true` — `container` не достанет метаданные из пути; нет `storage`;
`start_at` по умолчанию `end`.
**B2.** Позиции только в памяти, а `start_at: beginning` — после каждого рестарта пода агент
перечитает все файлы: массовые дубли. Нужны `file_storage` на hostPath и `storage:`.
**B3.** ⚠️ `memory_limiter` должен быть первым, `batch` — последним.
**B4.** ⚠️ Это push API Loki, а не OTLP. Для `otlp_http` — `endpoint: http://loki:3100/otlp`
(экспортер сам допишет `/v1/logs`).
**B5.** Каталог не существует — нужен `create_directory: true` (и том/hostPath).
**B6.** `validate` и старт упадут: `node_from_env_var` требует переменную
(`valueFrom.fieldRef.fieldPath: spec.nodeName`).
**B7.** Атрибут из списка по умолчанию так не понижается; нужен `ignore_defaults: true` + свой список.
**B8.** ⚠️ `index_label` разрешён только для resource-атрибутов; для атрибутов записи —
`structured_metadata` или `drop`. Да и `http.route` в лейблах — рост потоков.

</details>

```yaml
B9.  # Vector, sink loki
     labels:
       service: "{{ service }}"
       trace_id: "{{ trace_id }}"

B10. # Vector, remap
     source: |
       . = parse_json!(.message)
     # часть строк — не JSON

B11. # Vector: route → loki (важное) и elasticsearch (ES выключен на обслуживание)
     es_errors:
       type: elasticsearch
       inputs: [split.errors]
       endpoints: ["http://elasticsearch:9200"]
     # buffer не задан

B12. # Alloy
     otelcol.receiver.filelog "app" { ... }
     # alloy run /etc/alloy/config.alloy → ошибка при старте
```

<details><summary>Ответ</summary>

**B9.** ⚠️ `trace_id` в лейблах — взрыв кардинальности; его место — `structured_metadata`.
**B10.** На не-JSON строках `parse_json!` даст ошибку, событие пройдёт без изменений. Лучше
`parsed, err = parse_json(.message)` с веткой для ошибки или `drop_on_error` + `reroute_dropped`.
**B11.** Буфер по умолчанию — memory на 500 событий с `block`: заполнится, и `route` перестанет
отдавать события — Loki тоже встанет. Нужен `drop_newest` или disk-буфер.
**B12.** `otelcol.receiver.filelog` в v1.20.0 — public-preview: нужен `--stability.level=public-preview`.

</details>

```python
B13. # логи из SDK, короткая cron-задача
     log.error("export failed")
     # конец скрипта, provider.shutdown() не вызывается
```

<details><summary>Ответ</summary>

**B13.** Батч в памяти не успеет уйти — запись потеряна. Нужен `provider.shutdown()` (или flush).

</details>

---

### Блок C. Практика

#### C1. 🔑 Мини-лаба конспекта
Подними стенд из §9: app → otelcol → Loki. Найди в Grafana Explore строку по `trace_id`
и объясни, откуда в ней `severity_text`, `detected_level`, `log_iostream`.

<details><summary>Ответ</summary>

`severity_text` — из `severity.parse_from: attributes.level`, `detected_level` добавил Loki,
`log_iostream` — оператор `container` из поля `stream` docker.

</details>

#### C2. Лейблы против structured metadata
Выведи `curl -s localhost:3100/loki/api/v1/labels` и `/loki/api/v1/series` для
`{service_name="orders"}`. Какие поля — лейблы, какие — structured metadata? Добавь в
`resource` атрибут `host.name` — стал ли он лейблом и почему?

<details><summary>Ответ</summary>

Лейблы — `service_name`, `deployment_environment_name`; остальное (`trace_id`, `status`,
`path`, `severity_*`) — structured metadata. `host.name` не в списке по умолчанию — останется
structured metadata.

</details>

#### C3. 🔑 SDK и `service.instance.id`
Запусти `sdk_demo.py` из §3 три раза. Сколько потоков появилось у `service_name="billing"`?
Настрой `otlp_config` с `ignore_defaults: true` и повтори.

<details><summary>Ответ</summary>

Без настройки — три потока (по `service_instance_id` на запуск); с `ignore_defaults` и
своим списком — один, `service_instance_id` остаётся в structured metadata.

</details>

#### C4. Время события
Убери из `json_parser` блок `timestamp`. Сравни время записи в Loki с полем `ts` строки.
Затем поставь неверный `layout` — что пишет коллектор и какое время у записи?

<details><summary>Ответ</summary>

Без `timestamp` время записи — время из docker-обёртки (момент записи в stdout, близко
к `ts`); при неверном `layout` — ошибка разбора времени в логах коллектора, запись со временем обёртки/приёма.

</details>

#### C5. Позиции чтения
Останови otelcol на минуту (app продолжает писать), запусти снова — есть ли дыра? Удали том
`otelcol-data` и повтори с `start_at: beginning` — что видишь в Loki?

<details><summary>Ответ</summary>

С томом дыры нет — коллектор дочитает с сохранённой позиции. Без тома и с `beginning` —
повторная отправка всего файла, дубли в Loki.

</details>

#### C6. Дубли
Воспроизведи три копии строки (Alloy + otelcol + Vector) запросом из §9, затем убери лишние
правилом `drop` в Alloy и остановкой одного из агентов.

#### C7. VRL
1. Прогони программу nginx из §7.2 через `vector vrl --input … --program … --print-object`.
2. Добавь маскирование IP-адреса клиента (последний октет → `0`).
3. Сломай входную строку — что вернёт `parse_nginx_log!` и что вернёт вариант с `err`?

#### C8. 🔑 Маршрутизация и backpressure в Vector
Включи sink `es_errors` без поднятого Elasticsearch. Понаблюдай (`vector top`, метрики
`vector_buffer_size_events`), что происходит с потоком в Loki. Поставь `es_errors` буфер
`when_full: drop_newest` и сравни.

<details><summary>Ответ</summary>

ES недоступен → буфер `es_errors` заполняется → `route` блокируется → в Loki
перестаёт приходить всё. С `drop_newest` теряются только события для ES, поток в Loki идёт.

</details>

#### C9. Alloy как OTel
Замени otelcol на Alloy с конфигом из §6 (не забудь `--stability.level=public-preview`).
Сравни потоки в Loki. Попробуй `alloy convert --source-format=otelcol` на своём `otelcol-logs.yaml`
и найди, что не сконвертировалось.

<details><summary>Ответ</summary>

Потоки те же (`service_name` и т. д.), если конвейер эквивалентен. В v1.20.0
`alloy convert` не перевёл процессор `resource` и расширение `health_check`.

</details>

#### C10. Метрики агентов
Включи внутренние метрики коллектора на `0.0.0.0:8888` (`service.telemetry.metrics.readers`)
и Vector (`internal_metrics` → `prometheus_exporter`). Найди отправленные записи, очередь и ошибки.

---

### Блок D. Инциденты

**D1.** После перехода на OTLP в Loki стало в 40 раз больше потоков, запросы тормозят.
Приложения не менялись, только SDK обновили. Разбор.

<details><summary>Ответ</summary>

Новый SDK стал проставлять `service.instance.id` (или деплои меняют `k8s.pod.name`),
а Loki делает это лейблом по умолчанию. Задать `ignore_defaults: true` и свой список лейблов,
проверить `/loki/api/v1/labels`.

</details>

**D2.** Логи из коллектора есть, но все записи имеют время «сейчас», а не время события.
Что проверить?

<details><summary>Ответ</summary>

Нет или неверный `timestamp` в операторе-парсере (`parse_from`, `layout_type`, `layout`),
поле времени называется иначе; в VRL — `parse_timestamp` с неверным форматом.

</details>

**D3.** После раскатки агента DaemonSet'ом логов подов в Loki нет, в логах агента тишина.
Что первым делом проверишь?

<details><summary>Ответ</summary>

`start_at: end` на старых файлах, `include` не совпадает с путями, права на `/var/log/pods`
(runAsUser, hostPath), `exclude` не съел ли всё; экспортер: адрес Loki и метрики
`otelcol_exporter_send_failed_log_records`.

</details>

**D4.** У записей из файлов нет `k8s.deployment.name`, а `k8s.pod.name` есть. Где проблема?

<details><summary>Ответ</summary>

`k8s.pod.name` дал `container` из пути, а владельца добавляет `k8s_attributes`:
не настроен процессор, нет RBAC на `replicasets`/`deployments`, не совпадает `pod_association`
или фильтр ноды.

</details>

**D5.** После обновления коллектора в логах предупреждения о deprecated alias `filelog`.
Что делать и срочно ли это?

<details><summary>Ответ</summary>

Переименовать в `file_log` (и прочие в snake_case) при ближайшем обновлении конфига —
алиас пока работает, но будет удалён; проверить через `validate` новой версии.

</details>

**D6.** Loki лежал 20 минут. После восстановления логи с нод за этот период частично пропали.
Что было не настроено в коллекторе?

<details><summary>Ответ</summary>

Очередь экспортера только в памяти и ограниченные ретраи: `sending_queue` без `storage`,
`retry_on_failure.max_elapsed_time` по умолчанию. Нужны очередь в `file_storage`,
`max_elapsed_time: 0s` и `retry_on_failure` у `file_log`, чтобы чтение ставилось на паузу.

</details>

**D7.** Vector перестал отправлять логи в Loki, хотя Loki доступен. В логах — ошибки
соединения с Elasticsearch. Почему страдает Loki и как чинить?

<details><summary>Ответ</summary>

Fan-out: буфер sink'а ES заполнился с `when_full: block`, `route` ждёт — поток в Loki
тоже встал. Второстепенному sink'у — `drop_newest` или disk-буфер, алерт на `vector_buffer_size_events`.

</details>

**D8.** Строки nginx в Loki приходят неразобранными, а в логах Vector — ошибки
`parse_nginx_log`. Почему события не выброшены и как их изолировать?

<details><summary>Ответ</summary>

`parse_nginx_log!` при ошибке пропускает событие без изменений (по умолчанию
`drop_on_error: false`). Изолировать — `drop_on_error: true` + `reroute_dropped: true` и отдельный
sink для `<id>.dropped`.

</details>

**D9.** Разработчики включили OTLP-логи в SDK, и в Loki каждая строка теперь дважды. Почему
и как договориться о едином пути?

<details><summary>Ответ</summary>

Работают оба пути: OTLP из SDK и сбор stdout агентом. Договориться: либо SDK + исключение
контейнера из сбора файлов, либо stdout + `trace_id` в JSON; зафиксировать в платформенном стандарте.

</details>

**D10.** Коллектор-агент съел лимит памяти и перезапускается при всплеске логов. Что проверить
в конфиге?

<details><summary>Ответ</summary>

Есть ли `memory_limiter` и стоит ли он первым, лимиты относительно `resources.limits`
пода (`limit_percentage`), размер `batch` и очереди, `max_log_size` у `container`.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как устроена лог-запись в OpenTelemetry?

<details><summary>Ответ</summary>

Время события и наблюдения, severity (текст и номер), body, attributes, resource, scope,
`trace_id`/`span_id`; код пишет через обычный логгер, мост превращает запись в OTel.

</details>

**2.** Зачем отправлять логи по OTLP, если есть Fluent Bit?

<details><summary>Ответ</summary>

Один конвейер и агент на три сигнала, автоматическая корреляция с трейсами, общий resource,
вендор-нейтральность; Fluent Bit при этом может остаться лёгким агентом — он умеет OTLP.

</details>

**3.** Как связать логи и трейсы?

<details><summary>Ответ</summary>

Один `trace_id` в спане и записи лога: SDK кладёт его сам, либо форматтер пишет в JSON;
в Loki — structured metadata, в Grafana — derived fields и tracesToLogs.

</details>

**4.** Как коллектор собирает логи подов в Kubernetes?

<details><summary>Ответ</summary>

DaemonSet: `file_log` читает `/var/log/pods`, `container` разбирает CRI и достаёт метаданные
из пути, `k8s_attributes` добавляет владельца и labels, позиции — в `file_storage`.

</details>

**5.** Что делает Loki с OTLP-логами и почему это важно для кардинальности?

<details><summary>Ответ</summary>

Resource из списка по умолчанию — лейблы, остальное — structured metadata; следить за
`service.instance.id` и `k8s.pod.name`, настраивать `otlp_config`.

</details>

**6.** Чем Alloy отличается от OpenTelemetry Collector?

<details><summary>Ответ</summary>

Alloy — дистрибутив коллектора от Grafana с `otelcol.*` и пайплайнами Loki/Prometheus в одном
агенте, свой синтаксис; upstream — стандарт OTel на YAML.

</details>

**7.** Что такое Vector и VRL? Когда выберешь Vector?

<details><summary>Ответ</summary>

Vector — конвейер на Rust (Datadog), VRL — язык преобразований с проверкой при компиляции.
Для тяжёлого разбора, маршрутизации в несколько приёмников, агрегатора, замены Logstash.

</details>

**8.** Как не потерять логи при недоступном приёмнике в коллекторе и в Vector?

<details><summary>Ответ</summary>

Коллектор: позиции и `sending_queue` в `file_storage`, ретраи без лимита, `retry_on_failure`
у ресивера. Vector: disk-буфер, `block` для важного, `drop_newest` для второстепенного,
acknowledgements; и там и там — метрики очереди и дропов с алертами.

</details>

**9.** Как избежать дублей логов при нескольких агентах?

<details><summary>Ответ</summary>

Один путь на сервис: исключать контейнеры из сбора (`exclude`, `drop`-правила, labels
контейнера), договориться о стандарте SDK или stdout.

</details>

**10.** Сравни Alloy, OTel Collector, Vector и Fluent Bit.

<details><summary>Ответ</summary>

Alloy — стек Grafana, всё в одном; OTel Collector — стандарт и gateway; Vector — самый мощный
разбор (VRL); Fluent Bit — самый лёгкий агент.

</details>

---

## 🎯 Чек-лист

- [ ] Объясняю поля `LogRecord` и разницу resource / attributes
- [ ] Отправил логи из Python через `LoggingHandler` и увидел `trace_id` в Loki
- [ ] Собрал логи контейнеров `file_log` + `container`, позиции — в `file_storage` на томе
- [ ] Понимаю, что Loki делает лейблом при OTLP, и настроил `otlp_config` со своим списком
- [ ] ⭐ Нашёл и убрал дубли от двух агентов
- [ ] Написал VRL: разбор JSON и nginx, маскирование PII
- [ ] Разделил поток Vector на Loki и Elasticsearch через `route`
- [ ] Воспроизвёл backpressure в Vector и объяснил `block` против `drop_newest`
- [ ] Повторил конвейер в Alloy (`otelcol.*`) и сравнил с upstream-коллектором
- [ ] Могу сравнить Alloy, OTel Collector, Vector и Fluent Bit на собесе
