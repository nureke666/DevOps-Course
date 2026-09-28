---
title: "02. Prometheus: архитектура и сбор метрик"
description: "Устройство Prometheus, prometheus.yml, service discovery, relabeling, хранение TSDB и retention"
---

# 02. Prometheus: архитектура и сбор метрик

> Роадмап → Мониторинг → Prometheus: *«`Pull` модель, как работает»*.
>
> **После темы ты умеешь:** объяснить устройство Prometheus, настроить `prometheus.yml`,
> подключить таргеты статически и через service discovery, понимать хранение и retention.

---

## 🗺️ Архитектура

```text:no-line-numbers
 ┌─────────────────────────────────────────────────────────────────────┐
 │                            PROMETHEUS                                │
 │                                                                      │
 │  ┌────────────────┐   ┌──────────────┐   ┌────────────────────────┐  │
 │  │ Service        │──►│  Retrieval   │──►│  TSDB (локальный диск) │  │
 │  │ Discovery      │   │  (scrape)    │   │  блоки по 2 часа       │  │
 │  │ static/file/   │   └──────┬───────┘   └───────────┬────────────┘  │
 │  │ docker/k8s/…   │          │                       │               │
 │  └────────────────┘          │                       ▼               │
 │                              │            ┌────────────────────┐     │
 │  ┌────────────────┐          │            │ PromQL engine      │     │
 │  │ Rules (правила)│◄─────────┴───────────►│ + HTTP API + Web UI│     │
 │  │ recording+alert│                       └─────────┬──────────┘     │
 │  └───────┬────────┘                                 │                │
 └──────────┼──────────────────────────────────────────┼────────────────┘
            │ алерты                                   │ запросы
            ▼                                          ▼
    ┌────────────────┐                          ┌────────────┐
    │  Alertmanager  │                          │  Grafana   │
    └────────────────┘                          └────────────┘
```

Ключевые свойства, из которых следует всё остальное:
1. **Pull:** Prometheus сам ходит по HTTP за `/metrics`.
2. **Локальное хранилище:** данные лежат на диске самого Prometheus (не кластеризуется
   «из коробки»).
3. **Многомерная модель:** метрика + лейблы.
4. **PromQL:** язык запросов, на нём же пишутся правила и алерты.
5. **Не для логов и не для событий с уникальными id** — только числовые ряды.

---

## 1. Формат экспозиции метрик

```bash
curl -s localhost:9100/metrics | head -20
```
```text:no-line-numbers
# HELP node_cpu_seconds_total Seconds the CPUs spent in each mode.
# TYPE node_cpu_seconds_total counter
node_cpu_seconds_total{cpu="0",mode="idle"} 84521.79
node_cpu_seconds_total{cpu="0",mode="system"} 1204.3
node_memory_MemAvailable_bytes 3.221225472e+09
```
Это обычный текст по HTTP. Любой сервис, который умеет отдавать такой ответ на `/metrics`,
уже совместим с Prometheus — библиотеки есть для всех популярных языков.

---

## 2. `prometheus.yml` — основной конфиг

```yaml
global:
  scrape_interval: 15s          # как часто ходить за метриками (по умолчанию 1m)
  scrape_timeout: 10s           # таймаут одного сбора (< scrape_interval)
  evaluation_interval: 15s      # как часто вычислять правила
  external_labels:              # добавляются к метрикам, уходящим наружу
    cluster: prod
    region: kz-1

rule_files:
  - /etc/prometheus/rules/*.yml

alerting:
  alertmanagers:
    - static_configs:
        - targets: ['alertmanager:9093']

scrape_configs:
  - job_name: prometheus                 # сам себя
    static_configs:
      - targets: ['localhost:9090']

  - job_name: node
    static_configs:
      - targets: ['10.0.1.5:9100', '10.0.1.6:9100']
        labels:
          env: prod

  - job_name: api
    metrics_path: /actuator/prometheus    # если путь нестандартный
    scheme: https
    basic_auth:
      username: prom
      password_file: /etc/prometheus/api_pass
    static_configs:
      - targets: ['api.internal:8443']
```

Проверка и применение:
```bash
promtool check config /etc/prometheus/prometheus.yml    # ⭐ всегда перед применением
promtool check rules /etc/prometheus/rules/*.yml

curl -X POST http://localhost:9090/-/reload             # требует --web.enable-lifecycle
kill -HUP $(pidof prometheus)                           # альтернатива
```

---

## 3. Service discovery: откуда берутся таргеты

| Тип | Когда используют |
|-----|------------------|
| `static_configs` | Несколько фиксированных хостов, учебные стенды |
| `file_sd_configs` | ⭐ Список целей в JSON/YAML-файле, который генерирует Ansible/скрипт |
| `docker_sd_configs` | Контейнеры на хосте |
| `kubernetes_sd_configs` | ⭐ Поды, сервисы, ноды в k8s |
| `consul_sd_configs`, `dns_sd_configs` | Реестры сервисов, DNS SRV-записи |
| `ec2/gce/azure_sd_configs` | Облачные инстансы |

```yaml
  - job_name: node
    file_sd_configs:
      - files: ['/etc/prometheus/targets/*.yml']
        refresh_interval: 30s
```
```yaml
# /etc/prometheus/targets/nodes.yml — этот файл раскатывает Ansible
- targets: ['10.0.1.5:9100', '10.0.1.6:9100']
  labels: { env: prod, role: app }
- targets: ['10.0.2.5:9100']
  labels: { env: stage, role: db }
```

> 💡 `file_sd` — золотая середина для классической инфраструктуры: цели не зашиты
> в основной конфиг, обновляются без перезагрузки Prometheus, легко генерируются
> из inventory Ansible.

В Kubernetes стандарт — **kube-prometheus-stack** (Helm-чарт с Prometheus Operator):
таргеты описываются объектами `ServiceMonitor`/`PodMonitor`, а не правкой `prometheus.yml`.

---

## 4. Relabeling — как «чинят» лейблы

Два разных механизма, которые часто путают:

| | Когда применяется | Зачем |
|---|------------------|-------|
| `relabel_configs` | **До** сбора, к списку целей | Фильтровать цели, менять адрес, формировать лейблы из метаданных SD |
| `metric_relabel_configs` | **После** сбора, к метрикам | Выбросить лишние метрики, уменьшить кардинальность |

```yaml
  - job_name: node
    file_sd_configs: [{ files: ['/etc/prometheus/targets/*.yml'] }]
    relabel_configs:
      # красивое имя инстанса вместо ip:port
      - source_labels: [__address__]
        regex: '([^:]+):.*'
        target_label: instance
        replacement: '$1'
      # не собирать цели с меткой env=dev
      - source_labels: [env]
        regex: dev
        action: drop

    metric_relabel_configs:
      # выбросить шумную метрику с высокой кардинальностью
      - source_labels: [__name__]
        regex: 'go_gc_duration_seconds.*'
        action: drop
```

| `action` | Что делает |
|----------|-----------|
| `keep` / `drop` | Оставить / выбросить цели или метрики по regex |
| `replace` | Записать значение в лейбл (самый частый) |
| `labelmap` | Скопировать группу лейблов по шаблону (часто в k8s SD) |
| `labeldrop` / `labelkeep` | Удалить/оставить лейблы по regex |

---

## 5. Хранение данных (TSDB)

```text:no-line-numbers
data/
├── 01H8Z…/          блок за 2 часа: chunks + index + meta.json
├── 01H90…/          старые блоки объединяются (compaction) в более крупные
├── chunks_head/     свежие данные в памяти + на диске
└── wal/             журнал для восстановления после падения
```

| Параметр запуска | Смысл |
|------------------|-------|
| `--storage.tsdb.path=/prometheus` | Каталог данных |
| `--storage.tsdb.retention.time=15d` | Сколько хранить (по умолчанию 15 дней) |
| `--storage.tsdb.retention.size=50GB` | Лимит по размеру |
| `--web.enable-lifecycle` | Разрешить `/-/reload` |
| `--web.enable-admin-api` | Разрешить удаление рядов (осторожно) |

Оценка объёма:
```text:no-line-numbers
размер ≈ число_рядов × (1 / scrape_interval) × retention × ~1-2 байта на точку

пример: 500 000 рядов, 15 с, 15 дней ≈ 500000 × 4/мин × 60 × 24 × 15 × 1.5 Б ≈ 65 ГБ
```
Диагностика:
```text:no-line-numbers
prometheus_tsdb_head_series                 # активных рядов (главный показатель)
rate(prometheus_tsdb_head_samples_appended_total[5m])   # точек в секунду
prometheus_target_interval_length_seconds   # успевает ли scrape
scrape_duration_seconds                     # сколько занимает сбор с цели
up                                          # доступность целей
```

> ⭐ Prometheus **не создан** для долгого хранения и не масштабируется горизонтально сам.
> Для длительного хранения и глобального обзора берут **VictoriaMetrics**, **Thanos**
> или **Mimir** (через `remote_write` или sidecar).

```yaml
remote_write:
  - url: http://victoriametrics:8428/api/v1/write
```

---

## 6. Prometheus в бою: что важно на практике

| Вопрос | Практика |
|--------|----------|
| Интервал сбора | 15-30 с для инфраструктуры; чаще — только если реально нужно |
| Надёжность | Два независимых Prometheus, собирающих одно и то же (HA-пара), Alertmanager в кластере |
| Мониторинг мониторинга | `up`, `prometheus_tsdb_*`, dead man's switch — алерт, который всегда должен «гореть» |
| Безопасность | `/metrics` и UI не торчат в интернет; доступ через VPN/reverse proxy с авторизацией |
| Конфиг | В git, раскатывается Ansible/Helm, проверяется `promtool` в CI |
| Метки окружения | `external_labels` (cluster, env) — чтобы различать источники в общем хранилище |

Полезные служебные эндпоинты:
```text:no-line-numbers
/targets      состояние целей и ошибки сбора        ⭐ первое место при «метрик нет»
/config       текущий конфиг, как его видит Prometheus
/rules        загруженные правила
/alerts       активные алерты
/service-discovery  что нашёл SD и какие лейблы получились
/-/healthy  /-/ready   для healthcheck
```

---

## 7. Грабли

| Грабля | Симптом | Решение |
|--------|---------|---------|
| `scrape_timeout` ≥ `scrape_interval` | Пропуски данных | Таймаут меньше интервала |
| Метрики приложения с уникальными id | Рост памяти, тормоза | `metric_relabel_configs` + исправление кода |
| Retention по умолчанию 15 дней | «Данных за прошлый месяц нет» | Настроить retention/долгое хранилище |
| Конфиг правился в контейнере | Пропал при пересоздании | Конфиг в git + том/ConfigMap |
| Нет `--web.enable-lifecycle` | `/-/reload` возвращает 403 | Добавить флаг |
| Один Prometheus на всё | Он же единая точка отказа | HA-пара, мониторинг самого Prometheus |
| Собирают всё подряд «на всякий случай» | Диск и память кончаются | Фильтровать метрики relabeling'ом |
| `up == 1`, а метрик нет | Смотрят не туда | `/targets`, `scrape_duration`, путь `metrics_path` |

---

## 💼 Как это в DevOps

- На классической инфраструктуре: Prometheus в докере/systemd, конфиг из Ansible,
  цели через `file_sd` из inventory, правила и дашборды в том же репозитории.
- В Kubernetes: `kube-prometheus-stack` (Helm) — Prometheus Operator, `ServiceMonitor`,
  готовые дашборды и правила; руками `prometheus.yml` уже не правят.
- Долгое хранение: `remote_write` в VictoriaMetrics/Thanos; Prometheus держит 15-30 дней
  «оперативки».
- В CI обязателен `promtool check config` и `promtool check rules` — сломанный конфиг
  не должен доезжать до прода.
- При «нет метрик» порядок один: `/targets` → ошибка сбора → `curl` до `/metrics` руками →
  сеть/firewall → путь и порт.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Проверить конфиг | `promtool check config prometheus.yml` |
| Проверить правила | `promtool check rules rules/*.yml` |
| Перечитать конфиг | `curl -X POST localhost:9090/-/reload` |
| Посмотреть цели и ошибки | UI → `/targets` |
| Посмотреть, что нашёл SD | UI → `/service-discovery` |
| Изменить интервал сбора | `global.scrape_interval` или на уровне job |
| Добавить хосты без правки конфига | `file_sd_configs` + файл целей |
| Убрать шумную метрику | `metric_relabel_configs` с `action: drop` |
| Переименовать лейбл цели | `relabel_configs` с `action: replace` |
| Задать срок хранения | `--storage.tsdb.retention.time=30d` |
| Отдать метрики наружу | `remote_write` в VictoriaMetrics/Thanos |
| Проверить, жива ли цель | `up{job="node"}` |
| Сколько рядов в базе | `prometheus_tsdb_head_series` |
| Сколько длится сбор | `scrape_duration_seconds` |

---

## 🧠 Что запомнить

1. Prometheus сам ходит за метриками по HTTP; формат — обычный текст с именем, лейблами
   и значением.
2. `prometheus.yml` состоит из `global`, `scrape_configs`, `rule_files`, `alerting`.
3. ⭐ `/targets` — первое место, куда смотрят, когда «метрик нет».
4. Цели задают статически, но в реальной инфраструктуре — через `file_sd` или k8s SD.
5. `relabel_configs` работает с целями до сбора, `metric_relabel_configs` — с метриками после.
6. Данные лежат локально блоками по 2 часа; retention по умолчанию 15 дней.
7. Объём диска определяется числом активных рядов и интервалом сбора.
8. Prometheus не масштабируется сам: долгое хранение — VictoriaMetrics/Thanos/Mimir.
9. HA достигается двумя одинаковыми инстансами, а не кластером Prometheus.
10. Конфиг и правила — в git, с обязательной проверкой `promtool` в CI.

---

## Задачи

> Стенд: compose из индекса темы.

---

### Блок A. Теория

**A1.** Из каких компонентов состоит Prometheus? Нарисуй схему по памяти.

<details><summary>Ответ</summary>

Service discovery → retrieval (scrape) → TSDB; поверх — PromQL-движок с HTTP API
и Web UI; отдельно — вычисление правил и отправка алертов в Alertmanager;
Grafana читает данные через API.

</details>

**A2.** Как выглядит формат метрик, который отдаёт экспортер? Что означают `# HELP` и `# TYPE`?

<details><summary>Ответ</summary>

Текст по HTTP: `имя{лейблы} значение`. `# HELP` — человекочитаемое описание,
`# TYPE` — тип метрики (counter/gauge/histogram/summary).

</details>

**A3.** Какие разделы есть в `prometheus.yml` и за что отвечает каждый?

<details><summary>Ответ</summary>

`global` — общие параметры сбора и вычислений; `scrape_configs` — что и откуда
собирать; `rule_files` — файлы правил; `alerting` — куда отправлять алерты;
опционально `remote_write`/`remote_read`.

</details>

**A4.** Чем `scrape_interval` отличается от `evaluation_interval`?

<details><summary>Ответ</summary>

Первый — как часто собирать метрики с целей, второй — как часто пересчитывать
правила (recording и alerting).

</details>

**A5.** Почему `scrape_timeout` должен быть меньше `scrape_interval`?

<details><summary>Ответ</summary>

Иначе сбор может не завершиться до начала следующего — появляются пропуски
и наложение запросов.

</details>

**A6.** Зачем нужны `external_labels`?

<details><summary>Ответ</summary>

Чтобы пометить, откуда пришли данные (кластер, регион, окружение) — это нужно при
отправке в общее хранилище и в Alertmanager, чтобы различать одинаковые алерты
из разных инсталляций.

</details>

**A7.** Какие способы service discovery знаешь? Какой выберешь для 200 VM и почему?

<details><summary>Ответ</summary>

`static`, `file_sd`, `docker_sd`, `kubernetes_sd`, `consul_sd`, `dns_sd`, облачные.
Для 200 VM — `file_sd`: файл генерируется из inventory Ansible, обновляется без перезагрузки.

</details>

**A8.** ⭐ Чем `relabel_configs` отличается от `metric_relabel_configs`?

<details><summary>Ответ</summary>

`relabel_configs` применяется к **целям** до сбора (фильтрация целей, формирование
лейблов, изменение адреса). `metric_relabel_configs` — к **метрикам** после сбора
(выбросить метрики, срезать лейблы, снизить кардинальность).

</details>

**A9.** Как убрать шумную метрику, не трогая приложение?

<details><summary>Ответ</summary>

`metric_relabel_configs` с `action: drop` по `__name__` (или `labeldrop`
для отдельного лейбла).

</details>

**A10.** Как устроено хранилище Prometheus? Что такое блоки и WAL?

<details><summary>Ответ</summary>

Данные пишутся в WAL и в память, каждые 2 часа формируется блок на диске;
блоки затем объединяются (compaction). WAL нужен для восстановления после падения.

</details>

**A11.** Сколько по умолчанию хранятся данные и как это изменить?

<details><summary>Ответ</summary>

15 дней; меняется флагами `--storage.tsdb.retention.time` и/или `.size`.

</details>

**A12.** Как оценить, сколько диска займёт Prometheus?

<details><summary>Ответ</summary>

Примерно: число активных рядов × частота точек × срок хранения × 1-2 байта
на точку. Ряды смотрят в `prometheus_tsdb_head_series`.

</details>

**A13.** Почему Prometheus не годится для долгого хранения и что берут вместо него?

<details><summary>Ответ</summary>

Локальное хранилище, нет горизонтального масштабирования и дедупликации между
инстансами, ограниченный retention. Берут VictoriaMetrics, Thanos или Mimir.

</details>

**A14.** Как сделать Prometheus отказоустойчивым?

<details><summary>Ответ</summary>

Два независимых Prometheus с одинаковым конфигом, оба шлют алерты в кластер
Alertmanager (он дедуплицирует); плюс мониторинг самого Prometheus и dead man's switch.

</details>

**A15.** Куда смотришь первым делом, если «метрики не собираются»?

<details><summary>Ответ</summary>

Страница `/targets`: состояние цели и текст ошибки сбора; затем `curl` до
`/metrics` руками, сеть/firewall, путь и порт.

</details>

---

### Блок B. «Что делает / что тут не так»

```yaml
B1.  global: { scrape_interval: 15s, scrape_timeout: 30s }
B2.  global: { scrape_interval: 1s }          # 500 таргетов
B3.  scrape_configs:
       - job_name: node
         static_configs: [{ targets: ['10.0.1.5:9100'] }]
B4.  rule_files: ['/etc/prometheus/rules/*.yml']
B5.  remote_write: [{ url: 'http://victoriametrics:8428/api/v1/write' }]
B6.  metric_relabel_configs:
       - source_labels: [__name__]
         regex: 'go_.*'
         action: drop
B7.  relabel_configs:
       - source_labels: [env]
         regex: dev
         action: drop
```

```bash
B8.  promtool check config /etc/prometheus/prometheus.yml
B9.  curl -X POST http://localhost:9090/-/reload
B10. curl -s localhost:9090/api/v1/targets | jq '.data.activeTargets[].health'
```

```text:no-line-numbers
B11. up
B12. prometheus_tsdb_head_series
B13. scrape_duration_seconds > 5
B14. count by (job) (up)
```

Оцени решения:
```text:no-line-numbers
B15. "Храним метрики 1 год в Prometheus, диск 2 ТБ"
B16. "Список из 300 таргетов ведём прямо в prometheus.yml, правим руками"
B17. "Prometheus торчит в интернет, чтобы смотреть с телефона"
B18. "Конфиг правим внутри контейнера через docker exec"
```

<details><summary>Ответ</summary>

**B1.** Таймаут больше интервала — ошибка конфигурации, пропуски данных.
**B2.** Интервал 1 с на 500 таргетов: огромная нагрузка и объём данных без пользы.
**B3.** Корректный простой job со статическими целями.
**B4.** Подключение файлов правил по маске — норма.
**B5.** Отправка копии метрик во внешнее долговременное хранилище.
**B6.** Отбрасывает все метрики рантайма Go — типичный приём снижения объёма.
**B7.** Исключает из сбора цели с `env=dev`.
**B8.** Проверка синтаксиса конфига (обязательна в CI).
**B9.** Горячая перезагрузка конфига.
**B10.** Быстрый способ увидеть состояние всех целей из скрипта.
**B11.** Доступность целей.
**B12.** Число активных рядов — главный показатель здоровья TSDB.
**B13.** Цели, сбор с которых длится дольше 5 секунд.
**B14.** Количество целей по job'ам.
**B15.** Год в Prometheus — плохая идея: нет downsampling, риск потери всего при отказе
узла. Нужно внешнее хранилище.
**B16.** 300 целей руками — источник ошибок; нужен `file_sd`/SD.
**B17.** UI и метрики раскрывают внутреннее устройство; доступ только через VPN/прокси
с авторизацией.
**B18.** Правки в контейнере теряются при пересоздании; конфиг должен быть в git и монтироваться.

</details>

---

### Блок C. Практика

#### C1. 🔑 Разобрать свой конфиг
1. Открой `prometheus.yml` из стенда и объясни каждую строку.
2. Проверь `promtool check config`.
3. Открой UI → `/config` и сравни с файлом.

#### C2. Таргеты
1. Добавь второй node_exporter (второй контейнер/машину).
2. Посмотри `/targets`: состояние, последний сбор, ошибки.
3. Останови один — найди его в `up == 0` и на странице targets.

#### C3. `file_sd`
1. Переведи job `node` со `static_configs` на `file_sd_configs`.
2. Добавь цель, ничего не перезагружая, — убедись, что она появилась сама.
3. Добавь лейблы `env`, `role` в файл целей и проверь, что они видны в метриках.

<details><summary>Ответ</summary>

Новая цель появляется без reload, потому что `file_sd` перечитывает файлы
по `refresh_interval`.

</details>

#### C4. Relabeling
1. Сделай `instance` красивым (без порта) через `relabel_configs`.
2. Отфильтруй цели с `env=dev` (`action: drop`).
3. Выброси метрики `go_*` через `metric_relabel_configs`.
4. Сравни `count({__name__=~"go_.*"})` до и после.

<details><summary>Ответ</summary>

После drop `go_*` число рядов заметно падает — это самый дешёвый способ
уменьшить нагрузку.

</details>

#### C5. Интервалы
1. Поставь `scrape_interval: 5s` для одного job и `60s` для другого.
2. Посмотри на графике разную частоту точек.
3. Проверь `scrape_duration_seconds` и `prometheus_target_interval_length_seconds`.

#### C6. Хранилище
1. Посмотри размер каталога данных (`du -sh`), число рядов `prometheus_tsdb_head_series`.
2. Посчитай прогноз объёма на 30 дней по формуле из конспекта.
3. Поставь `--storage.tsdb.retention.time=2h`, подожди и убедись, что старые блоки удаляются.

<details><summary>Ответ</summary>

После уменьшения retention старые блоки удаляются при следующей компакции
(не мгновенно).

</details>

#### C7. Reload без рестарта
1. Включи `--web.enable-lifecycle`.
2. Измени конфиг и примени через `POST /-/reload`.
3. Сломай конфиг намеренно, сделай reload — что произойдёт со старым конфигом?

<details><summary>Ответ</summary>

При сломанном конфиге reload завершится ошибкой, Prometheus продолжит работать
со **старым** конфигом — это защита от «поломали прод перезагрузкой».

</details>

#### C8. Метрики самого Prometheus
Найди и объясни: `prometheus_tsdb_head_series`, `prometheus_target_scrapes_exceeded_sample_limit_total`,
`prometheus_rule_evaluation_failures_total`, `prometheus_notifications_dropped_total`.

<details><summary>Ответ</summary>

`head_series` — активные ряды; `exceeded_sample_limit` — цель отдала больше
метрик, чем разрешено `sample_limit`; `rule_evaluation_failures` — ошибки в правилах;
`notifications_dropped` — алерты не доставлены в Alertmanager.

</details>

#### C9. remote_write (со звёздочкой)
Подними VictoriaMetrics в compose, настрой `remote_write`, убедись, что метрики
пишутся туда, и подключи VM как источник данных в Grafana.

#### C10. Мониторинг для своего проекта
Опиши `prometheus.yml` для воображаемого проекта: 3 сервера приложений, 1 база,
2 сервиса с собственными метриками, внешняя проверка сайта. Со всеми job'ами и лейблами.

---

### Блок D. Инциденты

**D1.** На `/targets` цель в состоянии `DOWN` с ошибкой `context deadline exceeded`. Причины?

<details><summary>Ответ</summary>

Экспортер не отвечает вовремя: перегружен, слишком много метрик, сетевые задержки,
firewall, слишком маленький `scrape_timeout`.

</details>

**D2.** `up == 1`, но нужных метрик нет. Что проверишь?

<details><summary>Ответ</summary>

Правильный ли `metrics_path` и порт, действительно ли приложение регистрирует
метрики, не отфильтрованы ли они `metric_relabel_configs`, не переименованы ли метрики
в новой версии, смотришь ли ты в правильный job/instance.

</details>

**D3.** Prometheus занял всю память и был убит OOM. Разбор и лечение.

<details><summary>Ответ</summary>

Рост числа рядов (кардинальность). Смотреть `prometheus_tsdb_head_series`, топ
метрик по числу рядов, новые экспортеры и релизы; лечить relabeling'ом, исправлением
метрик приложения, лимитами (`sample_limit`), увеличением памяти.

</details>

**D4.** После добавления нового экспортера число рядов выросло в 10 раз. Что делать?

<details><summary>Ответ</summary>

Найти метрики-нарушители, отбросить их `metric_relabel_configs`, поговорить
с владельцем экспортера, при необходимости ограничить `sample_limit` для job.

</details>

**D5.** Диск под Prometheus кончился. Какие есть быстрые и правильные решения?

<details><summary>Ответ</summary>

Быстро — уменьшить retention, удалить старые блоки, расширить диск.
Правильно — снизить кардинальность, вынести долгое хранение во внешнюю систему,
следить за размером заранее (алерт).

</details>

**D6.** `/-/reload` возвращает 403. Почему?

<details><summary>Ответ</summary>

Не запущен с `--web.enable-lifecycle`.

</details>

**D7.** Метрики есть, но с «дырками» на графике. Гипотезы?

<details><summary>Ответ</summary>

Сбор не успевает (`scrape_duration` ≈ `scrape_interval`), таргет периодически
недоступен, рестарты экспортера, перегрузка Prometheus, сетевые потери.

</details>

**D8.** После рестарта контейнера пропали все данные. Что было не так?

<details><summary>Ответ</summary>

Данные лежали внутри контейнера без тома; нужен volume на `/prometheus`.

</details>

**D9.** Prometheus упал ночью, алертов не было вообще. Как это предотвратить?

<details><summary>Ответ</summary>

Мониторить сам Prometheus вторым инстансом или внешней проверкой, настроить
dead man's switch (постоянно срабатывающий алерт, отсутствие которого = проблема),
HA-пара, healthcheck и автоперезапуск.

</details>

**D10.** Нужно отдать метрики нескольких дата-центров в одно место. Варианты решения.

<details><summary>Ответ</summary>

Локальный Prometheus в каждом ДЦ + `remote_write` в общее хранилище
(VictoriaMetrics/Thanos/Mimir); federation — устаревший вариант для небольших объёмов.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как работает Prometheus и что такое pull-модель?

<details><summary>Ответ</summary>

Сервер сам опрашивает цели по HTTP `/metrics`, хранит ряды локально, считает PromQL
и отправляет алерты в Alertmanager.

</details>

**2.** Из чего состоит `prometheus.yml`?

<details><summary>Ответ</summary>

`global`, `scrape_configs`, `rule_files`, `alerting`, при необходимости `remote_write`.

</details>

**3.** Что такое service discovery и какие типы знаешь?

<details><summary>Ответ</summary>

Механизм автоматического получения списка целей: static, file_sd, docker, kubernetes,
consul, dns, облачные.

</details>

**4.** Что такое relabeling и зачем он нужен?

<details><summary>Ответ</summary>

Преобразование лейблов целей и метрик: фильтрация целей, приведение имён, снижение
кардинальности.

</details>

**5.** Как Prometheus хранит данные?

<details><summary>Ответ</summary>

Локальная TSDB: WAL + блоки по 2 часа с последующей компакцией.

</details>

**6.** Сколько хранятся метрики по умолчанию и как это изменить?

<details><summary>Ответ</summary>

15 дней; меняется флагами retention по времени и размеру.

</details>

**7.** Как оценить требуемый объём диска?

<details><summary>Ответ</summary>

По числу активных рядов, частоте сбора и сроку хранения.

</details>

**8.** Что делать, если нужно хранить метрики год?

<details><summary>Ответ</summary>

Внешнее долговременное хранилище: VictoriaMetrics, Thanos, Mimir через `remote_write`.

</details>

**9.** Как обеспечить отказоустойчивость Prometheus?

<details><summary>Ответ</summary>

Две одинаковые инсталляции + кластер Alertmanager для дедупликации, плюс мониторинг
самого мониторинга.

</details>

**10.** Что делаешь, если метрики перестали собираться?

<details><summary>Ответ</summary>

Смотрю `/targets` и ошибку сбора, проверяю `curl` до экспортера, сеть, путь, порт,
затем конфиг и relabeling.

</details>

---

### 🎯 Чек-лист

- [ ] Объясняю архитектуру Prometheus по памяти
- [ ] Понимаю каждую строку своего `prometheus.yml`
- [ ] Проверяю конфиг `promtool` перед применением
- [ ] Перевёл таргеты на `file_sd` и умею добавлять цели без reload
- [ ] ⭐ Различаю `relabel_configs` и `metric_relabel_configs`
- [ ] Умею выбросить шумные метрики и посчитать эффект
- [ ] Знаю, как устроено хранилище и как считать объём диска
- [ ] Настроил retention осознанно
- [ ] Знаю, чем решают долгое хранение и HA
- [ ] При «нет метрик» иду по алгоритму, а не наугад
