---
title: "06. Практика: 5 лаб по логам"
description: "Loki + Alloy, ELK руками, парсинг и маскирование, алерты по логам, OTel-логи и Vector"
---

# 06. Практика: 5 лаб по логам

> Роадмап → Логи: *«желательно знать в целом про существование, и поднять ELK или Loki
> и потыкаться»*. Ниже — как «потыкаться» так, чтобы осталось понимание и артефакты.

---

## 📋 Список лаб

| № | Лаба | Что закрепляет | Артефакт |
|---|------|----------------|----------|
| 1 | ⭐ Loki + Grafana Alloy + Grafana с нуля | темы 03, 04, 05 | compose + `config.alloy` + LogQL-шпаргалка |
| 2 | ELK один раз руками | тема 02 | compose + скриншоты Kibana |
| 3 | Парсинг, multiline, маскирование | темы 01, 04 | конфиг сборщика |
| 4 | Алерты по логам и связка с метриками | темы 03, 05 + мониторинг | правила + дашборд |
| 5 | OTel-логи и Vector: один сервис — один путь | тема 08 | `otelcol-logs.yaml`, `vector.yaml`, `otlp_config`, сравнение |

---

## 🧪 Лаба 1. ⭐ Loki-стек с нуля

### Что делаем
Поднимаем полноценное централизованное логирование для своих контейнеров.

### Требования
- [ ] `docker-compose.yml`: loki, alloy (`grafana/alloy`, версия зафиксирована), grafana
      (+ приложение из лабы мониторинга)
- [ ] Alloy собирает: системные логи (`loki.source.file`), логи контейнеров
      (`discovery.docker` + `loki.source.docker`), journald (`loki.source.journal`)
- [ ] Позиции чтения вынесены на том (`--storage.path`)
- [ ] В UI Alloy (`:12345`) все компоненты здоровы, граф понятен
- [ ] Лейблы: `job`, `container`, `env`, `level` — и никаких уникальных значений
- [ ] Loki добавлен как источник в Grafana
- [ ] Написано и сохранено минимум 10 LogQL-запросов
- [ ] Настроен `retention_period`, объяснено, почему выбран именно такой

### Проверка
```bash
curl -s localhost:3100/ready
curl -s localhost:12345/metrics | grep loki_write_sent_entries_total   # агент реально отправляет
curl -s localhost:3100/loki/api/v1/labels | jq
curl -s 'localhost:3100/loki/api/v1/label/container/values' | jq
```
В Grafana Explore:
```text:no-line-numbers
{job="docker"} |= "error"
{container="api"} | json | level="error" | duration_ms > 1000
sum by (container) (rate({job="docker"} |= "error" [5m]))
```

### Вопросы себе
- Что случится, если я добавлю `trace_id` в лейблы? (Проверь и откати.)
- Сколько места занимают логи за сутки и сколько это будет за месяц?

### Со звёздочкой: легаси Promtail
Напиши (или возьми из [03. Loki + Grafana](/logging/03-loki-grafana), §3) `promtail.yml` для тех же
источников, сконвертируй `alloy convert --source-format=promtail --output=converted.alloy promtail.yml`
и сравни со своим `config.alloy`. Promtail — EOL с 02.03.2026, в стенде его не держим.

---

## 🧪 Лаба 2. ELK один раз руками

### Что делаем
Поднимаем Elastic Stack, чтобы своими руками увидеть разницу с Loki.
⚠️ Нужно 4+ ГБ RAM; после лабы стенд гасим.

### Требования
- [ ] Elasticsearch + Kibana + Filebeat в compose (9.5.x, одна версия у всех трёх)
- [ ] `vm.max_map_count` настроен, кластер отвечает и статус объяснён
- [ ] Filebeat собирает логи контейнеров (`filestream` + парсер `container`) с `add_docker_metadata`
- [ ] JSON-логи разбираются (`decode_json_fields`), поля видны в Discover
- [ ] Настроен multiline для стектрейсов
- [ ] Создан data view, сохранены 3 запроса KQL
- [ ] Собран дашборд: динамика ошибок, топ сервисов, таблица последних ERROR
- [ ] Настроена политика ILM с rollover и удалением
- [ ] Замерено потребление RAM/диска и сравнено с Loki-стендом

### Проверка
```bash
curl -s 'localhost:9200/_cluster/health?pretty'
curl -s 'localhost:9200/_cat/indices?v&s=store.size:desc'
curl -s 'localhost:9200/_ilm/explain/logs-*?pretty' | head -40
docker stats --no-stream
```

### Вопросы себе
- Что ELK даёт такого, чего нет в Loki? Нужно ли это моему проекту?
- Во сколько раз тяжелее стенд ELK по памяти?

---

## 🧪 Лаба 3. Парсинг, multiline и маскирование

### Что делаем
Учимся приводить «грязные» логи в пригодный для поиска вид.

### Подготовка: генератор «плохих» логов
```bash
#!/bin/bash
# messy-logs.sh — пишет разнородные логи в stdout
while true; do
  echo "$(date -Is) INFO  request completed path=/api/orders status=200 duration=32ms"
  echo '{"ts":"'"$(date -Is)"'","level":"error","msg":"db timeout","service":"billing","password":"secret123"}'
  printf 'Traceback (most recent call last):\n  File "app.py", line 42\n    do_work()\nValueError: boom\n'
  sleep 2
done
```

### Требования
- [ ] logfmt-строки разобраны в поля (`path`, `status`, `duration`)
- [ ] JSON-строки разобраны, `level` стал лейблом
- [ ] Стектрейс приходит **одной** записью
- [ ] Поле `password` замаскировано или удалено до отправки
- [ ] Время записи берётся из лога, а не из момента чтения
- [ ] Строки healthcheck отбрасываются (экономия)
- [ ] Проверено: поиск по полю `status >= 500` работает

### Вопросы себе
- Что проще: заставить разработчиков писать JSON или парсить текст регулярками?
- Где я маскирую секрет и почему этого недостаточно?

---

## 🧪 Лаба 4. Алерты по логам и связка с метриками

### Что делаем
Замыкаем наблюдаемость: метрика показывает всплеск — логи объясняют причину,
алерт приходит сам.

### Требования
- [ ] Настроен ruler в Loki (или Grafana Alerting) с двумя правилами:
      всплеск ошибок и появление `panic`/`OOM` в логах
- [ ] Алерты уходят в тот же Alertmanager, что и метрики
- [ ] Дашборд: сверху метрики (RPS, ошибки, p99), снизу панель Logs с теми же лейблами
- [ ] Проверено: искусственный всплеск ошибок → алерт → переход на логи в один клик
- [ ] Из логов сделана метрика (`rate` в LogQL или `stage.metrics` в Alloy)
- [ ] Написан рунбук: «пришёл алерт TooManyErrors — что делать»

### Проверка сценария
```text:no-line-numbers
1. Запускаем приложение с ошибками (увеличили долю 500)
2. Метрика http_requests_total{status="5.."} растёт  → алерт из Prometheus
3. Алерт из Loki по строкам "error" → тот же чат
4. В Grafana: график ошибок → клик → логи за то же время с теми же лейблами
5. Находим причину в тексте лога
```

### Вопросы себе
- Что лучше алертить: метрику ошибок или строки в логах? Почему?
- Какие ещё «маркерные» строки стоит отслеживать в моём стеке?

---

## 🧪 Лаба 5. OTel-логи и Vector: один сервис — один путь

### Что делаем
Переводим сбор логов приложения на OpenTelemetry: логи идут в Loki по OTLP с `trace_id`
в structured metadata, лейблы под контролем, дублей нет. Затем тот же поток — через Vector
с маскированием PII и маршрутизацией ошибок во второй приёмник. Каркас — мини-лаба
[08. Логи через OpenTelemetry и Vector](/logging/08-otel-logs-vector), §9; версии запиннены, как там.

### Требования
- [ ] Стенд лабы 1 + `app`, `otelcol` (contrib, версия зафиксирована), `vector` в одном compose
- [ ] Коллектор читает файлы docker через `file_log` + `container`; время, severity и
      `trace_id`/`span_id` разобраны из JSON; позиции — в `file_storage` на томе
- [ ] Второй сервис шлёт логи прямо из SDK (`LoggingHandler` или авто-инструментация) в тот же коллектор
- [ ] В Loki `otlp_config` с `ignore_defaults: true`: лейблы — только сервис, окружение и
      namespace/контейнер; `service_instance_id` не лейбл
- [ ] Найдены и устранены дубли: для каждого сервиса ровно один путь (Alloy / коллектор / Vector / SDK)
- [ ] Vector: VRL разбирает JSON, маскирует e-mail, `route` отправляет ошибки во второй sink
      (Elasticsearch из лабы 2 или `console`), у важного sink'а — disk-буфер
- [ ] Проверено: Loki остановлен на 2 минуты → после старта дыры нет ни у коллектора, ни у Vector
- [ ] Проверено: второй sink Vector недоступен → объяснено, что происходит с Loki при `block`
      и при `drop_newest`
- [ ] Метрики агентов в Prometheus: отправлено, очередь, ошибки/дропы у обоих

### Проверка
```bash
docker run --rm -v "$PWD/otelcol-logs.yaml":/c.yaml:ro otel/opentelemetry-collector-contrib:0.161.0 validate --config=/c.yaml
docker run --rm -v "$PWD/vector.yaml":/etc/vector/vector.yaml:ro timberio/vector:0.58.0-debian validate --no-environment
curl -s localhost:3100/loki/api/v1/labels | jq -c        # нет service_instance_id, log_file_path, trace_id
curl -s -G localhost:3100/loki/api/v1/query \
  --data-urlencode 'query=sum by (job, service_name) (count_over_time({service_name=~"orders|logging-app-1"} |= "order" [1m]))' | jq -c '.data.result[].metric'
```
```text:no-line-numbers
{service_name="orders"} | trace_id="<из строки>"
sum by (severity_text) (count_over_time({service_name="orders"}[5m]))
```

### Вопросы себе
- Что проще поддерживать команде: OTLP из SDK или JSON в stdout + агент? Почему?
- Где в моём конвейере маскируется PII и что будет, если этот шаг пропустить?
- Когда бы я поставил Vector агрегатором перед Loki и Elasticsearch, а когда хватит коллектора?

---

## 🏁 Что должно остаться после блока

```text:no-line-numbers
logging/
├── loki/                       # compose, конфиги loki и alloy
│   ├── docker-compose.yml
│   ├── config.alloy
│   └── loki-config.yaml
├── elk/                        # компоуз ELK (для истории и сравнения)
├── otel/                       # otelcol-logs.yaml, vector.yaml, otlp_config для Loki
├── rules/                      # алерты по логам
├── dashboards/                 # дашборд «метрики + логи»
├── logql-cheatsheet.md         # свои запросы
├── logging-guidelines.md       # памятка разработчикам: формат, поля, что нельзя
└── README.md                   # что где лежит и как поднять
```

Этого достаточно, чтобы на собесе отвечать конкретно: «поднимал и Loki, и ELK,
вот разница по ресурсам, вот почему выбрал бы Loki на проекте с Grafana».
