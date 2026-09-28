---
title: "03. Loki + Grafana"
description: "Модель лейблов Loki, Grafana Alloy, LogQL, алерты по логам, retention, миграция с Promtail, Loki vs ELK"
---

# 03. Loki + Grafana

> Роадмап → 7. Остальное → Логи → *«Loki + Grafana»*.
>
> **После темы ты умеешь:** поднять Loki с агентом Grafana Alloy, писать LogQL, понимать
> модель лейблов, объяснить, чем Loki принципиально отличается от Elasticsearch,
> и перевести легаси-конфиг Promtail на Alloy.

---

## 🗺️ Главная идея Loki

```text:no-line-numbers
 ELASTICSEARCH                          LOKI
 ─────────────                          ────
 индексирует СОДЕРЖИМОЕ каждой строки   индексирует только ЛЕЙБЛЫ
 (инвертированный индекс по словам)     {app="api", env="prod"}
        │                                       │
   мощный полнотекстовый поиск           сами строки лежат сжатыми чанками
   дорого: RAM, CPU, диск ×2-3           дёшево: объектное хранилище (S3)
        │                                       │
   «найди слово timeout везде»           «возьми поток по лейблам → grep внутри»
```

Девиз проекта: *«Like Prometheus, but for logs»* — та же модель лейблов, та же
философия, та же Grafana сверху. Если у тебя уже есть [Prometheus](/monitoring/),
Loki встроится почти бесплатно.

---

## 1. Архитектура

```text:no-line-numbers
 ┌──────────┐  push  ┌──────────────────────────────────────┐
 │ Alloy    │───────►│ LOKI                                 │
 │ (агент)  │  HTTP  │  distributor → ingester → чанки      │
 └──────────┘        │        │            │                │
 ┌──────────┐        │        │            ▼                │
 │ Docker   │        │        │      объектное хранилище    │
 │ driver   │───────►│        │      (S3/файлы) + индекс    │
 └──────────┘        │        ▼                             │
 ┌──────────┐        │    querier ◄──── query-frontend      │
 │ Fluent Bit│──────►│        ▲                             │
 └──────────┘        └────────┼─────────────────────────────┘
                              │ LogQL
                         ┌────┴─────┐
                         │ Grafana  │  (Explore + дашборды + алерты)
                         └──────────┘
```

| Компонент | Роль |
|-----------|------|
| **Grafana Alloy** (пришёл на смену Promtail) | Агент: читает файлы/journald/docker, ставит лейблы, шлёт в Loki |
| **distributor** | Принимает потоки, проверяет лимиты, распределяет |
| **ingester** | Собирает записи в чанки, пишет в хранилище |
| **querier / query-frontend** | Выполняют LogQL-запросы, разбивают их на части |
| **ruler** | Алерты и recording rules по логам |
| **хранилище** | Локальные файлы (стенд) или S3/GCS (прод) |

Режимы запуска: `monolithic` (всё в одном процессе — для стенда и небольших объёмов),
`simple scalable` (read/write/backend), `microservices` (каждый компонент отдельно).

---

## 2. Модель данных: потоки и лейблы

```text:no-line-numbers
Поток (stream) = уникальный набор лейблов
{job="docker", container="api", env="prod", level="error"}
    │
    └── упорядоченные по времени строки логов (внутри — сжатый чанк)
```

⭐ Правило, которое определяет всё: **лейблы должны иметь низкую кардинальность**,
ровно как в Prometheus.

| Хорошие лейблы | Плохие лейблы ⚠️ |
|----------------|------------------|
| `job`, `app`, `service` | `trace_id`, `request_id` |
| `env`, `cluster`, `namespace` | `user_id`, `order_id` |
| `container`, `pod`, `node` | `ip` клиента, полный URL |
| `level` (если значений мало) | `message`, время, любые уникальные значения |

Что делать с `trace_id`? Не в лейблы, а в **содержимое строки** — и искать фильтром
(`|= "7f3c9a1b"`) или парсером (`| json | trace_id="7f3c9a1b"`).

```text:no-line-numbers
Высокая кардинальность в Loki = миллионы мелких потоков =
медленные запросы, распухший индекс, падающие ingester'ы.
Это ошибка №1 при внедрении Loki.
```

---

## 3. Grafana Alloy: сбор логов

**Alloy** — единый агент Grafana: дистрибутив OpenTelemetry Collector плюс пайплайны
Prometheus и Loki (логи, метрики, трейсы, профили в одном процессе). Конфиг пишется
на синтаксисе Alloy (бывший River, похож на HCL): это набор **компонентов**, которые
передают данные друг другу через `forward_to` и `targets`.

```text:no-line-numbers
 что читать                    откуда читать              обработка           отправка
 local.file_match ──────────►  loki.source.file    ─┐
 discovery.docker ──────────►  loki.source.docker  ─┼──► loki.process ──► loki.write ──► Loki
 (+ discovery.relabel: лейблы) loki.source.journal ─┘    (stage.*)
```

```text:no-line-numbers
// config.alloy

// 1) системные логи: какие файлы читать
local.file_match "system" {
  path_targets = [{"__path__" = "/var/log/*.log", "job" = "varlogs"}]   // ⭐ __path__ — как в Promtail
}

loki.source.file "system" {
  targets    = local.file_match.system.targets
  forward_to = [loki.write.local.receiver]
}

// 2) логи docker-контейнеров через service discovery
discovery.docker "linux" {
  host = "unix:///var/run/docker.sock"
}

discovery.relabel "docker" {
  targets = []
  rule {
    source_labels = ["__meta_docker_container_name"]
    regex         = "/(.*)"
    target_label  = "container"
  }
  rule {
    source_labels = ["__meta_docker_container_log_stream"]
    target_label  = "stream"
  }
}

loki.source.docker "default" {
  host          = "unix:///var/run/docker.sock"
  targets       = discovery.docker.linux.targets
  labels        = {"job" = "docker"}
  relabel_rules = discovery.relabel.docker.rules
  forward_to    = [loki.process.app.receiver]      // сначала — в разбор
}

loki.process "app" {
  stage.json {
    expressions = {level = "level", msg = "msg", service = "service", ts = "ts"}
  }
  stage.labels {
    values = {level = "", service = ""}           // level становится лейблом (значений мало — ок)
  }
  stage.timestamp {
    source = "ts"
    format = "RFC3339"
  }
  stage.output {
    source = "msg"
  }
  forward_to = [loki.write.local.receiver]
}

// 3) systemd journal
discovery.relabel "journal" {
  targets = []
  rule {
    source_labels = ["__journal__systemd_unit"]
    target_label  = "unit"
  }
}

loki.source.journal "read" {
  max_age       = "12h"
  labels        = {"job" = "systemd-journal"}
  relabel_rules = discovery.relabel.journal.rules
  forward_to    = [loki.write.local.receiver]
}

// отправка в Loki
loki.write "local" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
```

```bash
alloy fmt config.alloy                         # проверить синтаксис (и отформатировать)
alloy run --server.http.listen-addr=0.0.0.0:12345 \
  --storage.path=/var/lib/alloy/data /etc/alloy/config.alloy
# http://localhost:12345 — UI: граф компонентов, их здоровье, текущие аргументы и экспорт
```

⭐ Позиции чтения (аналог `positions.yaml`) Alloy хранит сам — в каталоге `--storage.path`.
Этот каталог выносят на том, иначе после пересоздания контейнера будут дубли или потери.

Основные стадии `loki.process`:
| Стадия Alloy | В Promtail | Что делает |
|--------------|-----------|-----------|
| `stage.json` / `stage.logfmt` / `stage.regex` | `json` / `logfmt` / `regex` | Разбор строки в поля |
| `stage.labels` | `labels` | Превратить поле в лейбл (осторожно с кардинальностью!) |
| `stage.timestamp` | `timestamp` | Взять время из самого лога |
| `stage.multiline` | `multiline` | Склеить стектрейс |
| `stage.drop` | `drop` | Выбросить ненужные строки (экономия) |
| `stage.metrics` | `metrics` | ⭐ Сделать метрику Prometheus прямо из логов (видна на `:12345/metrics`) |
| `stage.output` | `output` | Что останется телом записи |

### Легаси: Promtail и миграция на Alloy

> ⚠️ **Promtail — EOL с 02.03.2026**: ни новых версий, ни исправлений безопасности.
> В новых проектах его не ставят, но в легаси он встречается часто — узнаётся
> по `promtail.yml` со `scrape_configs`/`pipeline_stages` и метрикам на `:9080`.

Так выглядел тот же сбор в Promtail — полезно уметь читать:
```yaml
# promtail.yml
server:
  http_listen_port: 9080

positions:
  filename: /tmp/positions.yaml        # где остановились при чтении файлов

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  # 1) системные логи
  - job_name: system
    static_configs:
      - targets: [localhost]
        labels:
          job: varlogs
          host: ${HOSTNAME}
          __path__: /var/log/*.log      # ⭐ спец-лейбл: какие файлы читать

  # 2) логи docker-контейнеров через service discovery
  - job_name: docker
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        refresh_interval: 15s
    relabel_configs:
      - source_labels: ['__meta_docker_container_name']
        regex: '/(.*)'
        target_label: container
      - source_labels: ['__meta_docker_container_log_stream']
        target_label: stream
    pipeline_stages:
      - json:
          expressions: { level: level, msg: msg, service: service }
      - labels:
          level:                        # level становится лейблом (значений мало — ок)
          service:
      - timestamp:
          source: ts
          format: RFC3339
      - output:
          source: msg

  # 3) systemd journal
  - job_name: journal
    journal:
      max_age: 12h
      labels: { job: systemd-journal }
    relabel_configs:
      - source_labels: ['__journal__systemd_unit']
        target_label: unit
```

Миграция — встроенным конвертером:
```bash
alloy convert --source-format=promtail --output=config.alloy promtail.yml
alloy convert --source-format=promtail --report=report.txt --output=config.alloy promtail.yml
#   --report — что сконвертировалось с оговорками; --bypass-errors — сконвертировать то, что можно
```

| Promtail | Alloy |
|----------|-------|
| `clients` | `loki.write` |
| `static_configs` + `__path__` | `local.file_match` + `loki.source.file` |
| `docker_sd_configs` | `discovery.docker` + `loki.source.docker` |
| `journal` | `loki.source.journal` |
| `relabel_configs` | `discovery.relabel` с блоками `rule {}` |
| `pipeline_stages` | `loki.process` со стадиями `stage.*` |
| `positions.yaml` | каталог `--storage.path` |
| `:9080/metrics` | `:12345/metrics` + веб-UI |

> 💡 После конвертации конфиг всё равно читают глазами: переменные окружения
> (`${HOSTNAME}` переносится как есть), нестандартные стадии и лейблы проверяют в UI
> Alloy, прежде чем выключать старый агент. Позиции файлов конвертер подхватывает
> из старого `positions.yaml` (аргумент `legacy_positions_file`), а в отчёте прямо
> предупреждает: метрики у Alloy другие — алерты и дашборды на `promtail_*` переписывают
> (например, на `loki_write_dropped_entries_total`).

---

## 4. LogQL — язык запросов

```text:no-line-numbers
# 1. Селектор потока (обязателен!)
{job="docker", container="api"}

# 2. Фильтры по содержимому
{container="api"} |= "error"                 # содержит
{container="api"} != "healthcheck"           # не содержит
{container="api"} |~ "timeout|refused"       # regex
{container="api"} !~ "DEBUG"

# 3. Парсеры и фильтры по полям
{container="api"} | json | level="error" | duration_ms > 1000
{container="nginx"} | logfmt | status >= 500
{container="api"} | pattern `<ip> - <_> [<ts>] "<method> <path>"` | method="POST"
{container="api"} | json | line_format "{{.service}} {{.msg}}"     # переформатировать вывод

# 4. Метрики из логов (можно строить графики и алерты!)
rate({container="api"} |= "error" [5m])                       # ошибок в секунду
sum by (container) (count_over_time({job="docker"}[5m]))      # строк за 5 минут
sum(rate({container="api"} | json | level="error" [5m]))
quantile_over_time(0.95,
  {container="api"} | json | unwrap duration_ms [5m]) by (path)   # p95 из поля лога
```

```text:no-line-numbers
Порядок всегда один:
  {селектор потока}  →  фильтры строки (|= != |~)  →  парсер (| json)  →
  фильтры полей  →  (опционально) агрегация во времени
Селектор обязателен: LogQL не умеет искать «по всем логам сразу» — и это by design.
```

---

## 5. Алерты по логам

```yaml
# loki/rules/app.yml — их выполняет ruler
groups:
  - name: app-logs
    rules:
      - alert: TooManyErrors
        expr: |
          sum by (container) (rate({job="docker"} | json | level="error" [5m])) > 1
        for: 5m
        labels: { severity: warning }
        annotations:
          summary: "{{ $labels.container }}: больше 1 ошибки в секунду"

      - alert: PanicInLogs
        expr: sum(count_over_time({job="docker"} |= "panic:" [5m])) > 0
        labels: { severity: critical }
        annotations:
          summary: "В логах обнаружен panic"
```
Алерты уходят в тот же [Alertmanager](/monitoring/05-alertmanager), что и метрики.

> 💡 Лучший приём: то, что нужно **считать**, превращать в метрику
> (`stage.metrics` в Alloy или `rate()` в LogQL), а логи оставлять для деталей.

---

## 6. Retention и хранение

```yaml
# loki-config.yaml (фрагменты, актуальные для прода)
limits_config:
  retention_period: 720h            # 30 дней
  ingestion_rate_mb: 10
  ingestion_burst_size_mb: 20
  max_streams_per_user: 10000       # ⭐ защита от взрыва кардинальности
  reject_old_samples: true
  reject_old_samples_max_age: 168h

compactor:
  retention_enabled: true
  delete_request_store: s3

schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: s3
      schema: v13
      index: { prefix: index_, period: 24h }

storage_config:
  aws:
    s3: s3://key:secret@region/loki-bucket
```

| Вопрос | Loki |
|--------|------|
| Где лежат логи | Объектное хранилище (S3/GCS/MinIO) или файлы |
| Индекс | Только по лейблам (TSDB) — маленький |
| Retention | `retention_period` + compactor |
| Стоимость | Заметно дешевле Elasticsearch при том же объёме |
| Мультиарендность | По заголовку `X-Scope-OrgID` (tenant) |

---

## 7. Loki vs ELK — как выбирать

| Критерий | Loki | Elasticsearch |
|----------|------|---------------|
| Ресурсы | Низкие | Высокие (RAM, CPU, диск ×2-3) |
| Полнотекстовый поиск «везде» | Нет (нужен селектор потока) | Да |
| Сложная аналитика по логам | Ограниченно | Да (агрегации, ML) |
| Интеграция с Prometheus/Grafana | Родная, те же лейблы | Через плагины |
| Порог входа | Низкий | Высокий |
| Стоимость хранения | S3, дёшево | Дорого |
| Когда выбирать | ⭐ Kubernetes/контейнеры, ограниченный бюджет, уже есть Grafana | Нужен мощный поиск/аналитика, безопасность, SIEM |

> Частый практический выбор: **Loki для инженерных логов приложений**, а Elasticsearch —
> там, где логи нужны бизнесу/безопасности для глубокого анализа.

---

## 8. Грабли

| Грабля | Симптом | Решение |
|--------|---------|---------|
| Высокая кардинальность лейблов | Loki тормозит, ingester'ы падают | Только низкокардинальные лейблы; `trace_id` — в тело строки |
| Запрос без селектора | Ошибка/таймаут | Всегда `{job="..."}` |
| Слишком широкий диапазон | Запрос на 30 дней «висит» | Сузить время, добавить фильтры, `query-frontend` |
| Нет `timestamp`-стадии | Время = момент приёма, а не события | `stage.timestamp` в `loki.process` |
| `reject_old_samples` | Старые логи молча отбрасываются | Понимать лимиты и `max_age` |
| Агент читает не те файлы | Логов нет | Проверить `__path__` в `local.file_match`, граф в UI Alloy (`:12345`), каталог позиций |
| Promtail в новом проекте | EOL с 02.03.2026, без исправлений безопасности | Alloy; легаси — `alloy convert` |
| Loki без retention | Бакет растёт вечно | `retention_period` + compactor |
| Используют Loki как полнотекстовый поиск | Разочарование | Понимать модель: поток → grep |

---

## 💼 Как это в DevOps

- Loki — дефолтный выбор для команды, у которой уже есть Prometheus и Grafana:
  единые лейблы, один интерфейс, переход «метрика → лог» в один клик в Explore.
- В Kubernetes ставят Helm-чарт `grafana/loki`, агент — чарт `grafana/alloy` DaemonSet'ом
  (старый `loki-stack` с Promtail устарел); логи берутся из stdout подов, лейблы — из метаданных.
- Promtail в легаси — не повод паниковать: `alloy convert` переводит конфиг,
  дальше агенты меняют по нодам и сверяют, что потоки и лейблы в Loki не изменились.
- Хранение в S3/MinIO делает стоимость предсказуемой: индекс маленький, чанки сжаты.
- Алерты по логам (`panic`, `OOM`, всплеск ошибок) — хорошее дополнение к метрикам,
  но всё, что можно посчитать, лучше превращать в метрику.
- На собесе типичный вопрос: «Loki или ELK?» — правильный ответ не «Loki лучше»,
  а объяснение через модель индексации, ресурсы и задачи.

---

## 📌 Шпаргалка

| Хочу | LogQL / команда |
|------|-----------------|
| Логи контейнера | `{container="api"}` |
| Только ошибки | `{container="api"} \|= "error"` |
| Исключить шум | `{container="api"} != "healthcheck"` |
| Regex-фильтр | `{container="api"} \|~ "timeout\|refused"` |
| Разобрать JSON | `{container="api"} \| json` |
| Фильтр по полю | `... \| json \| level="error" \| duration_ms > 1000` |
| Переформатировать вывод | <code v-pre>... \| line_format "{{.service}} {{.msg}}"</code> |
| Ошибок в секунду | `rate({container="api"} \|= "error" [5m])` |
| Строк за период | `count_over_time({job="docker"}[5m])` |
| Перцентиль из поля | `quantile_over_time(0.95, {..} \| json \| unwrap duration_ms [5m])` |
| Найти по trace_id | `{app="api"} \|= "7f3c9a1b"` |
| Проверить агент | UI `http://localhost:12345`, `curl localhost:12345/metrics` (Alloy) |
| Мигрировать с Promtail | `alloy convert --source-format=promtail --output=config.alloy promtail.yml` |
| Проверить Loki | `curl localhost:3100/ready`, `/metrics` |
| Список лейблов | `curl -s localhost:3100/loki/api/v1/labels` |
| Значения лейбла | `curl -s localhost:3100/loki/api/v1/label/container/values` |

---

## 🧠 Что запомнить

1. Loki индексирует только лейблы, а сами строки хранит сжатыми чанками — отсюда
   низкая стоимость.
2. Модель та же, что у Prometheus: поток = уникальный набор лейблов.
3. ⭐ Высокая кардинальность лейблов — главная ошибка внедрения Loki;
   `trace_id` и `user_id` живут в теле строки, а не в лейблах.
4. LogQL всегда начинается с селектора потока, затем фильтры, парсер, фильтры полей.
5. Из логов можно строить метрики (`rate`, `count_over_time`, `unwrap`) и алерты.
6. Grafana Alloy читает файлы, journald и docker, ставит лейблы и парсит строки
   в `loki.process`; Promtail — EOL с 02.03.2026, легаси переводят `alloy convert`.
7. Стадия `stage.timestamp` нужна, чтобы временем записи было время события, а не приёма.
8. Retention задаётся в `limits_config` и обслуживается compactor'ом; хранилище — S3.
9. Loki дешевле и проще ELK, но не даёт полнотекстового поиска «по всему сразу».
10. Loki + Grafana + Prometheus — один интерфейс и одни лейблы для метрик и логов.

---

## Задачи

> Стенд: Loki + Grafana Alloy + Grafana (см. описание compose-стенда в индексе раздела).
> Promtail (EOL с 02.03.2026) — только в задачах про легаси и миграцию.

---

### Блок A. Теория

**A1.** ⭐ Чем принципиально отличается модель индексации Loki от Elasticsearch?

<details><summary>Ответ</summary>

Elasticsearch строит инвертированный индекс по содержимому каждой строки —
отсюда мощный полнотекстовый поиск и высокая стоимость. Loki индексирует только набор
лейблов потока, а строки хранит сжатыми чанками: дёшево, но поиск сначала сужает поток,
а затем «грепает» его содержимое.

</details>

**A2.** Почему говорят «Loki — это Prometheus для логов»?

<details><summary>Ответ</summary>

Та же модель лейблов, тот же подход к мультитенантности и конфигурации,
общая экосистема (Grafana, Alertmanager), похожий язык запросов (LogQL ≈ PromQL для логов).

</details>

**A3.** Что такое поток (stream) в Loki?

<details><summary>Ответ</summary>

Уникальная комбинация лейблов и связанная с ней упорядоченная по времени
последовательность строк.

</details>

**A4.** Какие лейблы считаются хорошими, а какие — недопустимыми? Почему?

<details><summary>Ответ</summary>

Хорошие — с малым числом значений: `job`, `app`, `env`, `namespace`, `container`,
`level`. Плохие — уникальные: `trace_id`, `user_id`, `ip`, полный URL: каждый новый
вариант создаёт новый поток и раздувает индекс.

</details>

**A5.** Куда девать `trace_id`, если его нельзя класть в лейблы?

<details><summary>Ответ</summary>

Оставлять в теле строки (в JSON) и искать фильтром `|= "..."` или
`| json | trace_id="..."`.

</details>

**A6.** Из каких компонентов состоит Loki и за что отвечает каждый?

<details><summary>Ответ</summary>

distributor (приём и распределение), ingester (сборка чанков и запись),
querier/query-frontend (выполнение запросов), ruler (алерты), compactor
(компакция и retention), объектное хранилище.

</details>

**A7.** Какие режимы развёртывания Loki бывают?

<details><summary>Ответ</summary>

Monolithic (всё в одном процессе), simple scalable (read/write/backend),
microservices (каждый компонент отдельно).

</details>

**A8.** Что делает Grafana Alloy как агент логов и какие у него бывают источники?

<details><summary>Ответ</summary>

Агент сбора: читает файлы (`local.file_match` + `loki.source.file`), systemd journal
(`loki.source.journal`), логи docker через discovery (`loki.source.docker`), ставит лейблы
(`discovery.relabel`), разбирает строки в `loki.process` и отправляет в Loki по HTTP
(`loki.write`). Раньше эту роль играл Promtail.

</details>

**A9.** Что такое `loki.process` и какие стадии `stage.*` ты знаешь?

<details><summary>Ответ</summary>

Компонент, который прогоняет строку через стадии: `stage.json`, `stage.logfmt`,
`stage.regex`, `stage.labels`, `stage.timestamp`, `stage.multiline`, `stage.drop`,
`stage.metrics`, `stage.output`, `stage.template`. В Promtail то же самое называлось
`pipeline_stages`.

</details>

**A10.** Зачем нужна стадия `timestamp`?

<details><summary>Ответ</summary>

Чтобы временем записи стало время события из самого лога, а не момент чтения
агентом: иначе при задержках и досылке порядок и графики искажаются.

</details>

**A11.** Из каких частей состоит запрос LogQL? Почему селектор обязателен?

<details><summary>Ответ</summary>

Селектор потока `{...}` → фильтры строки (`|=`, `!=`, `|~`, `!~`) → парсер
(`json`, `logfmt`, `pattern`, `regexp`) → фильтры по полям → опционально агрегация
(`rate`, `count_over_time`, `unwrap`). Селектор обязателен: без него пришлось бы читать
все данные, что противоречит модели хранения.

</details>

**A12.** Как из логов сделать метрику? Приведи два примера.

<details><summary>Ответ</summary>

`rate({app="api"} |= "error" [5m])` — ошибок в секунду;
`quantile_over_time(0.95, {app="api"} | json | unwrap duration_ms [5m])` — перцентиль
по числовому полю; плюс `stage.metrics` в Alloy создаёт метрику Prometheus.

</details>

**A13.** Как настраивается retention в Loki и где хранятся данные в проде?

<details><summary>Ответ</summary>

`limits_config.retention_period` + включённый `compactor` с `retention_enabled`;
данные — в объектном хранилище (S3/GCS/MinIO), индекс — TSDB.

</details>

**A14.** Что делает `max_streams_per_user` и от чего защищает?

<details><summary>Ответ</summary>

Ограничивает число активных потоков на арендатора; защищает от взрыва
кардинальности лейблов, который кладёт кластер.

</details>

**A15.** Когда выберешь Loki, а когда ELK?

<details><summary>Ответ</summary>

Loki — когда уже есть Prometheus/Grafana, логи контейнерные, бюджет ограничен,
нужен инженерный просмотр. ELK — когда нужен полнотекстовый поиск по всему массиву,
сложная аналитика, SIEM-сценарии и есть ресурсы.

</details>

**A16.** Почему Promtail не ставят в новый проект и как перевести легаси-конфиг на Alloy?

<details><summary>Ответ</summary>

Promtail — EOL с 02.03.2026: нет ни новых версий, ни исправлений безопасности,
преемник — Grafana Alloy. Легаси-конфиг переводят
`alloy convert --source-format=promtail --output=config.alloy promtail.yml`
(с `--report`, чтобы увидеть оговорки), затем проверяют
результат в UI Alloy и сравнивают потоки в Loki до и после замены.

</details>

---

### Блок B. «Что вернёт запрос / что тут не так»

```text:no-line-numbers
B1.  {container="api"}
B2.  {container="api"} |= "error"
B3.  {container="api"} | json | level="error" | duration_ms > 1000
B4.  |= "error"
B5.  {trace_id="7f3c9a1b"}
B6.  rate({container="api"} |= "error" [5m])
B7.  sum by (container) (count_over_time({job="docker"}[5m]))
B8.  quantile_over_time(0.95, {app="api"} | json | unwrap duration_ms [5m]) by (path)
B9.  {job="docker"} |~ ".*"
B10. {app="api"} | json | line_format "{{.msg}}"
```

<details><summary>Ответ (запросы)</summary>

**B1.** Все строки потока по лейблу `container`.
**B2.** Строки, содержащие «error».
**B3.** Ошибки с длительностью больше секунды (после разбора JSON).
**B4.** ⚠️ Нет селектора потока — запрос недопустим.
**B5.** ⚠️ `trace_id` как лейбл — взрыв кардинальности (и такого лейбла, скорее всего,
просто нет).
**B6.** Скорость появления ошибок в секунду — можно строить график и алерт.
**B7.** Количество строк за 5 минут по контейнерам.
**B8.** p95 значения `duration_ms` из логов с группировкой по пути.
**B9.** Бессмысленный regex `.*` — просто нагрузка; фильтр лучше убрать.
**B10.** Показать только поле `msg` — удобно для чтения.

</details>

Оцени конфигурации агента (Alloy) и Loki:

```text:no-line-numbers
B11. loki.process "app" {
       stage.json {
         expressions = {user_id = "user_id"}
       }
       stage.labels {
         values = {user_id = ""}
       }
       forward_to = [loki.write.local.receiver]
     }
B12. loki.process "app" {
       stage.json {
         expressions = {level = "level"}
       }
       stage.labels {
         values = {level = ""}
       }
       forward_to = [loki.write.local.receiver]
     }
B13. local.file_match "app" {
       path_targets = [{"__path__" = "/var/log/app/*.log", "job" = "app"}]
     }
B14. alloy run /etc/alloy/config.alloy     # в контейнере, --storage.path не на томе
```

<details><summary>Ответ (Alloy)</summary>

**B11.** ⚠️ `user_id` в лейблах — категорически нельзя.
**B12.** Нормально: у `level` мало значений.
**B13.** Корректное описание файлов для чтения (дальше нужен `loki.source.file`).
**B14.** Каталог позиций живёт внутри контейнера: после пересоздания агент начнёт читать
файлы заново — дубли или потери. `--storage.path` выносят на том.

</details>

```yaml
B15. limits_config: { retention_period: 8760h }                # логи приложений на год
B16. promtail:                                                 # новый проект, 2026 год
       image: grafana/promtail:latest
```

<details><summary>Ответ (Loki и Promtail)</summary>

**B15.** Год хранения прикладных логов — почти всегда лишние расходы; нужен разный
retention по типам.
**B16.** ⚠️ Promtail в новом проекте — EOL-компонент без исправлений безопасности,
да ещё и `latest`. Нужен Alloy с зафиксированной версией.

</details>

---

### Блок C. Практика

#### C1. 🔑 Поднять стек
1. Подними Loki + Alloy + Grafana (compose и `config.alloy` по описанию в индексе раздела).
2. Открой UI Alloy на `:12345`: найди граф компонентов и убедись, что все они здоровы.
3. Добавь Loki как источник данных в Grafana.
4. В Explore выполни `{job="varlogs"}` и увидь системные логи.

#### C2. Логи контейнеров
1. Настрой `discovery.docker` + `loki.source.docker` в Alloy.
2. Запусти nginx и приложение, посмотри их логи по лейблу `container`.
3. Разбери relabeling (`discovery.relabel`): откуда берутся лейблы `container` и `stream`.

#### C3. Фильтры
Потренируйся: `|=`, `!=`, `|~`, `!~`. Найди все ошибки, исключи healthcheck,
найди по regex два разных слова.

#### C4. 🔑 Парсинг JSON
1. Запусти приложение с JSON-логами.
2. Примени `| json`, отфильтруй по `level` и числовому полю.
3. Используй `line_format` для компактного вывода.

#### C5. Лейблы из логов
1. Сделай `level` лейблом через `stage.labels` в `loki.process`.
2. Проверь `curl -s localhost:3100/loki/api/v1/label/level/values`.
3. Попробуй сделать лейблом `trace_id` и посмотри, что произойдёт с числом потоков
   (`loki_ingester_memory_streams`). Верни обратно.

<details><summary>Ответ</summary>

Число потоков видно в метрике `loki_ingester_memory_streams`;
после добавления `trace_id` в лейблы оно растёт взрывообразно.

</details>

#### C6. Время события
Настрой `stage.timestamp` и убедись, что логи ложатся по времени события,
а не по времени приёма (сгенерируй строку с прошлым временем).

<details><summary>Ответ</summary>

Без стадии `timestamp` записи с прошлым временем лягут «сейчас».

</details>

#### C7. Multiline
Настрой склейку стектрейсов (`stage.multiline`), проверь, что трейс приходит одной записью.

#### C8. Метрики из логов
1. `rate({container="api"} |= "error" [5m])` — построй график.
2. Сделай панель в Grafana рядом с метриками Prometheus.
3. Через `stage.metrics` в Alloy создай counter, найди его на `:12345/metrics` и в Prometheus.

<details><summary>Ответ</summary>

Метрики из логов удобны, но для постоянного счёта лучше полноценная метрика
приложения.

</details>

#### C9. Алерты по логам
Настрой ruler и правило `PanicInLogs`; вызови panic в приложении и проверь,
что алерт дошёл до Alertmanager.

#### C10. Дашборд «сервис»
Собери дашборд, где сверху метрики (RPS, ошибки, p99), а снизу панель Logs
с фильтром по тем же лейблам. Проверь переход «увидел всплеск → посмотрел логи».

<details><summary>Ответ</summary>

В Grafana панель Logs с теми же лейблами, что у метрик, — это и есть
переход «метрика → лог» в один клик.

</details>

#### C11. Легаси: Promtail + `alloy convert` (по желанию)
1. Возьми `promtail.yml` из легаси-раздела конспекта (§3).
2. Сконвертируй: `alloy convert --source-format=promtail --report=report.txt --output=converted.alloy promtail.yml`.
3. Прочитай `report.txt` и сравни `converted.alloy` со своим рукописным `config.alloy`.
4. Со звёздочкой: подними рядом последний образ Promtail (зафиксированной версией),
   сравни потоки и лейблы в Loki от двух агентов, затем выключи Promtail.

<details><summary>Ответ</summary>

Для типового `promtail.yml` конвертер даёт рабочий конфиг и добавляет
`legacy_positions_file`, чтобы подхватить старые позиции. Внимания требуют переменные
окружения (`${HOSTNAME}` переносится как есть), редкие стадии и метрики: отчёт
предупреждает, что алерты и дашборды на `promtail_*` придётся переписать.

</details>

---

### Блок D. Инциденты

**D1.** Запросы в Loki стали очень медленными, ingester'ы перезапускаются. Первая гипотеза?

<details><summary>Ответ</summary>

Взрыв кардинальности лейблов (кто-то добавил уникальный лейбл). Смотреть
число потоков, лимиты, последние изменения конфига агента.

</details>

**D2.** Логи в Grafana не появляются, Alloy запущен. Алгоритм проверки.

<details><summary>Ответ</summary>

Логи самого Alloy и его UI на `:12345` (здоровы ли компоненты, какие targets нашлись),
`/metrics` (`loki_write_sent_entries_total`, `loki_write_dropped_entries_total`),
корректность `__path__`/discovery, права на файлы и `docker.sock`, каталог позиций,
доступность Loki (`/ready`), правильность селектора и временного диапазона в Grafana.

</details>

**D3.** В Loki попадают логи, но со временем приёма, из-за чего сортировка «плывёт». Причина?

<details><summary>Ответ</summary>

Не настроена стадия `timestamp`: используется время приёма.

</details>

**D4.** Агент пишет `entry out of order` / логи отбрасываются. Что происходит?

<details><summary>Ответ</summary>

Записи приходят не по порядку для одного потока (или старше допустимого возраста):
раньше Loki строго требовал порядок, сейчас лимиты гибче, но `reject_old_samples`
и настройки всё ещё отбрасывают слишком старые записи. Причины — часовые пояса,
досылка старых файлов, несколько агентов на один поток.

</details>

**D5.** Диск/бакет Loki растёт без ограничений. Что настроить?

<details><summary>Ответ</summary>

`retention_period`, включить compactor с retention, лимиты приёма,
фильтрацию лишних логов (`drop`), sampling.

</details>

**D6.** Нужно найти все записи по одному `trace_id` за сутки, а запрос падает по таймауту.
Как правильно?

<details><summary>Ответ</summary>

Сузить запрос: селектор потока (сервис, окружение), узкий диапазон времени,
затем `|= "trace_id"`. Поиск «по всему за сутки» в Loki делать не нужно — это
не его модель.

</details>

**D7.** После пересоздания контейнера Alloy часть логов пришла повторно. Почему?

<details><summary>Ответ</summary>

Потерян каталог позиций (`--storage.path` у Alloy, `positions.yaml` у Promtail) —
например, он лежал в контейнере без тома, и агент начал читать файлы сначала.

</details>

**D8.** Разработчики жалуются: «в Loki нельзя нормально искать». Что объяснишь?

<details><summary>Ответ</summary>

Что Loki не полнотекстовый движок: сначала выбираем поток по лейблам, потом
фильтруем. Для их сценариев нужно правильно проставлять лейблы и писать JSON-логи;
если реально нужен глубокий поиск — это аргумент за Elasticsearch.

</details>

**D9.** Логи одного сервиса занимают 80% объёма. Что сделаешь?

<details><summary>Ответ</summary>

Разобраться, что там: DEBUG, дубли, «логи в цикле». Уменьшить уровень,
включить `drop` для мусора, sampling, обсудить с разработчиками; при необходимости —
отдельный tenant и лимиты.

</details>

**D10.** Нужно хранить логи безопасности 1 год, а прикладные — 14 дней. Как реализовать?

<details><summary>Ответ</summary>

Разные арендаторы (tenant) или отдельные инсталляции/бакеты с разным
`retention_period`; в Loki retention также можно задавать через `retention_stream`
правила по селекторам.

</details>

**D11.** В легаси-кластере на нодах стоит Promtail, безопасники требуют убрать
EOL-компоненты. Твой план?

<details><summary>Ответ</summary>

Инвентаризация: где стоит Promtail и с какими конфигами. Конвертация
`alloy convert` (+ `--report`), ревью результата, Alloy DaemonSet'ом сначала на части нод
(или рядом, с другим лейблом-маркером), сверка потоков и лейблов в Loki, затем замена
на всех нодах и удаление Promtail. Позиции файлов можно подхватить из старого
`positions.yaml` (аргумент `legacy_positions_file` у `loki.source.file`); для остального
на момент переключения закладывают небольшие дубли или короткое окно без логов.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое Loki и чем он отличается от Elasticsearch?

<details><summary>Ответ</summary>

Хранилище логов с индексацией только по лейблам: дешевле и проще ELK,
но без полнотекстового поиска по всему массиву.

</details>

**2.** Что такое поток и лейблы в Loki?

<details><summary>Ответ</summary>

Поток — уникальный набор лейблов и его строки; лейблы должны быть низкокардинальными.

</details>

**3.** Почему нельзя класть `trace_id` в лейблы?

<details><summary>Ответ</summary>

Каждый уникальный `trace_id` создаёт отдельный поток: индекс и память растут
неограниченно.

</details>

**4.** Как устроен LogQL?

<details><summary>Ответ</summary>

Селектор потока → фильтры строки → парсер → фильтры полей → агрегации.

</details>

**5.** Как из логов получить метрику?

<details><summary>Ответ</summary>

`rate`, `count_over_time`, `unwrap` в LogQL или `stage.metrics` в Alloy.

</details>

**6.** Чем Alloy отличается от Fluent Bit и что стало с Promtail?

<details><summary>Ответ</summary>

Alloy — «родной» агент стека Grafana: логи, метрики и трейсы, те же лейблы,
что у Prometheus. Fluent Bit универсальнее по выходам, легче по ресурсам и чаще
используется как общий сборщик. Promtail — прежний агент только для Loki,
EOL с 02.03.2026, мигрируется `alloy convert`.

</details>

**7.** Где Loki хранит данные и как настраивается retention?

<details><summary>Ответ</summary>

В объектном хранилище (S3/MinIO) чанками, индекс TSDB; retention —
`limits_config` + compactor.

</details>

**8.** Как настроить алерт по логам?

<details><summary>Ответ</summary>

Через ruler: правило на LogQL-выражении, алерты уходят в Alertmanager.

</details>

**9.** Как связать метрики и логи в одном интерфейсе?

<details><summary>Ответ</summary>

Grafana: один интерфейс, одинаковые лейблы у Prometheus и Loki, переход
из панели метрик в панель логов.

</details>

**10.** Когда выбрать Loki, а когда ELK?

<details><summary>Ответ</summary>

Loki — контейнеры, ограниченный бюджет, уже есть Grafana; ELK — мощный поиск,
аналитика, безопасность.

</details>

---

### 🎯 Чек-лист

- [ ] Поднял Loki + Alloy + Grafana и вижу логи контейнеров
- [ ] ⭐ Понимаю модель лейблов и не кладу в них уникальные значения
- [ ] Пишу LogQL: селектор → фильтры → парсер → поля
- [ ] Разбираю JSON-логи и фильтрую по числовым полям
- [ ] Настроил `stage.timestamp` и `stage.multiline` в Alloy
- [ ] Строю метрики из логов (`rate`, `count_over_time`, `unwrap`)
- [ ] Настроил алерт по логам через ruler
- [ ] Знаю, где Loki хранит данные и как работает retention
- [ ] Собрал дашборд «метрики сверху, логи снизу»
- [ ] Могу аргументированно выбрать между Loki и ELK
- [ ] Умею перевести легаси-конфиг Promtail на Alloy (`alloy convert`)
