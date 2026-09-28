---
title: "11. Долгое хранение и Prometheus Operator"
description: "remote_write, VictoriaMetrics/Thanos/Mimir, HA-пара и дедупликация, kube-prometheus-stack, ServiceMonitor/PrometheusRule, ловушка release, кардинальность"
---

# 11. Долгое хранение и Prometheus Operator

> Сверх роадмапа: роадмап заканчивается на «Prometheus + Grafana», а прод начинается там,
> где одного Prometheus перестаёт хватать. На собеседованиях middle+ почти всегда спрашивают
> «как хранить метрики год», «как сделать HA» и «как подключить сервис в kube-prometheus-stack».
>
> **После темы ты умеешь:** объяснить, почему одного Prometheus мало, настроить `remote_write`
> и следить за ним, поднять VictoriaMetrics как удалённое хранилище, сравнить Thanos, Mimir
> и VictoriaMetrics, собрать HA-пару с дедупликацией, поставить kube-prometheus-stack в kind,
> подключить сервис через `ServiceMonitor` и `PrometheusRule`, не попасть в ловушку лейбла
> `release` и держать кардинальность под контролем.

---

## 🗺️ Карта темы

```text:no-line-numbers
 ┌──────────── кластер A (Operator: ServiceMonitor, PrometheusRule) ─┐  ┌── ДЦ / VM ──┐
 │  Prometheus A-1 (replica=A)          Prometheus A-2 (replica=B)   │  │ vmagent или │
 └────────┬───────────────── remote_write ─────────┬─────────────────┘  │ agent mode  │
          │                                        ▼                    └──────┬──────┘
          │        ┌──────────────────────────────────────────────────────┐◄───┘
          │        │ ДОЛГОЕ ХРАНИЛИЩЕ: VictoriaMetrics / Thanos / Mimir    │
          │        │ месяцы и годы, дедупликация, все кластеры сразу       │
          │        └─────────────────────────┬────────────────────────────┘
          └─ оперативка 1–15 дней ─► Grafana ◄┘ история
```

> 📌 **Версии (проверь, сентябрь 2026):** Prometheus **3.15.0** (25.09.2026) ·
> VictoriaMetrics **v1.152.0** (14.09.2026, Apache 2.0 + enterprise-функции) ·
> Thanos **v0.42.4** (30.07.2026, Apache 2.0) · Grafana Mimir **3.2.1** (10.09.2026, AGPLv3) ·
> kube-prometheus-stack **91.7.1** (27.09.2026; внутри Operator v0.94.1, Prometheus v3.15.0,
> Grafana 13.2). Чарты и образы обновляются еженедельно — в проде версию всегда фиксируют.

---

## 1. Почему одного Prometheus мало

| Проблема | Почему у одиночного Prometheus | Что нужно |
|----------|-------------------------------|-----------|
| **Retention** | Локальный диск, по умолчанию 15 дней (см. [«02. Prometheus: базовые концепции»](/monitoring/02-prometheus-basics)); год на одной ноде — большой диск и риск потерять всё | Отдельное хранилище, downsampling |
| **HA** | Один инстанс = единая точка отказа; две реплики дают **две копии** данных | Дедупликация на чтении или записи |
| **Глобальный взгляд** | Три кластера — три Prometheus, запрос «ошибки по всем» не сделать | Единая точка запросов |
| **Масштаб** | Все активные ряды в памяти одной ноды, горизонтально не растёт | Шардирование + общее хранилище |
| **Тяжёлые запросы** | «p99 за 90 дней» читает сырые точки и роняет Prometheus | Downsampling, кэш запросов |

**Federation** (`/federate`) — старый способ собрать агрегаты; для долгого хранения и HA не решение.

---

## 2. `remote_write`: как метрики уходят наружу

```text:no-line-numbers
 scrape ──► TSDB head + WAL ──► чтение WAL ──► очередь (shards) ──► HTTP POST (snappy protobuf)
                                    │ при недоступности хранилища — повторы с backoff;
                                    └ данные ждут в WAL ~2 часа, дальше теряются
```

```yaml
# prometheus.yml
global:
  external_labels:            # ⭐ обязательно: откуда пришли ряды
    cluster: kz-prod-1
    replica: A                # для HA-пар (см. раздел 5)

remote_write:
  - url: http://victoriametrics:8428/api/v1/write
    queue_config:
      capacity: 10000             # буфер одного шарда (дефолт)
      max_samples_per_send: 2000  # размер пачки (дефолт)
      max_shards: 50              # потолок параллелизма
    write_relabel_configs:        # ⭐ в долгое хранилище — только то, что нужно
      - source_labels: [__name__]
        regex: 'go_.*|process_.*|prometheus_tsdb_.*'
        action: drop
```

| Метрика Prometheus | Что показывает |
|--------------------|----------------|
| `prometheus_remote_storage_samples_pending` | Сколько точек ждёт отправки — растёт = не успеваем |
| `rate(prometheus_remote_storage_samples_failed_total[5m])` | Ошибки отправки |
| `prometheus_remote_storage_shards` / `..._shards_desired` | Текущее и желаемое число шардов |
| `prometheus_remote_storage_highest_timestamp_in_seconds` − `prometheus_remote_storage_queue_highest_sent_timestamp_seconds` | ⭐ Отставание отправки в секундах |

Что важно знать:
- **Память:** по документации Prometheus, remote_write добавляет в среднем ~25% памяти
  (зависит от данных).
- **Agent mode** (`--agent`): Prometheus без локальных запросов и правил — только собрать
  и отправить. Удобно на краю (VM, филиалы, маленькие кластеры); аналог — vmagent.
- **Remote Write 2.0** — спецификация всё ещё *experimental*: метаданные, exemplars,
  native histograms, created timestamps. Включается `protobuf_message: io.prometheus.write.v2.Request`
  в `remote_write`, если получатель это поддерживает — проверь у своего хранилища.
- **Native histograms** — стабильны с Prometheus 3.8, но сбор включается явно
  (`scrape_native_histograms: true`); хранилище тоже должно их принимать.

---

## 3. VictoriaMetrics

Совместимое с Prometheus хранилище и набор компонентов. Принимает `remote_write`, отвечает
на Prometheus query API (Grafana подключает его как обычный источник Prometheus), хранит
данные на локальных дисках, а не в S3.

| | **Single-node** | **Cluster** |
|---|-----------------|-------------|
| Процессы | Один бинарник `victoria-metrics` | `vminsert` (8480) → `vmstorage` (8482) ← `vmselect` (8481) |
| Запись | `:8428/api/v1/write` | `vminsert:8480/insert/<accountID>/prometheus/api/v1/write` |
| Чтение | `:8428` (Prometheus API), UI `/vmui` | `vmselect:8481/select/<accountID>/prometheus` |
| Мультиаренда | Нет | ⭐ `accountID` в URL |
| Репликация | Нет (надёжность — диск/бэкап/две копии) | `-replicationFactor=N` |
| Когда | По документации VM — до ~1 млн точек/с single-node проще и предпочтительнее | Больше, мультиаренда, горизонтальный рост |

Спутники: **vmagent** (лёгкий сбор по `prometheus.yml` + отправка с дисковым буфером,
relabeling, лимиты кардинальности, шардирование), **vmalert** (recording/alerting rules
поверх VM → Alertmanager), **vmauth** (прокси с авторизацией и маршрутизацией), vmbackup.

Важные флаги: `-retentionPeriod` (по умолчанию 1 месяц; `12` = 12 месяцев, можно `90d`, `1y`),
`-dedup.minScrapeInterval` (дедупликация), `-storageDataPath`.

**Лицензия:** основной код — Apache 2.0. Downsampling, разные retention для разных
данных, автообнаружение vmstorage, часть функций безопасности и LTS-релизы — в Enterprise.

### MetricsQL ≠ PromQL на 100%

| | PromQL | MetricsQL |
|---|--------|-----------|
| `rate`/`increase` | Экстраполирует к краям окна, `increase` бывает дробным | Без экстраполяции, берёт последнюю точку **до** окна → целые `increase` |
| Окно `[5m]` | Обязательно | Можно опустить: `rate(http_requests_total)` — окно подберётся само |
| Шаблоны | Нет | `WITH (f = …) …` — переиспользуемые куски запроса |
| Имена после функций | Теряются | Модификатор `keep_metric_names` |
| NaN | Возвращает ряды с NaN | Удаляет NaN из результата |
| Функции | Стандарт | Плюс `range_median`, `topk_avg`, `histogram_quantiles` и др. |

⭐ Следствие: одни и те же дашборды и алерты на Prometheus и на VM могут давать
**немного разные числа** (особенно `increase` на коротких окнах). Это не баг — разные
определения. Алерты, перенесённые на vmalert, перепроверяют.

---

## 4. 🧰 Стенд: VictoriaMetrics как удалённое хранилище

Дополняем compose из настройки стенда блока Monitoring (`~/labs/monitoring`):

```yaml
# docker-compose.yml — добавить сервисы
  victoriametrics:
    image: victoriametrics/victoria-metrics:v1.152.0     # проверь, сентябрь 2026
    command:
      - -storageDataPath=/storage
      - -retentionPeriod=12                # месяцев
      - -dedup.minScrapeInterval=15s       # = scrape_interval пары реплик
    volumes: [vmdata:/storage]
    ports: ["8428:8428"]

  vmagent:                                 # альтернатива «Prometheus + remote_write»
    image: victoriametrics/vmagent:v1.152.0
    command:
      - -promscrape.config=/etc/prometheus/prometheus.yml
      - -remoteWrite.url=http://victoriametrics:8428/api/v1/write
      - -remoteWrite.tmpDataPath=/buffer   # дисковый буфер, если VM недоступна
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - vmagentbuf:/buffer
    ports: ["8429:8429"]

# и в секцию volumes: vmdata: {}, vmagentbuf: {}
```
```yaml
# prometheus.yml — добавить
remote_write:
  - url: http://victoriametrics:8428/api/v1/write
```
В Grafana — второй источник `type: prometheus`, `url: http://victoriametrics:8428`
(provisioning как в [«06. Grafana»](/monitoring/06-grafana); для MetricsQL есть отдельный плагин VM).

### Мини-лаба
1. `docker compose up -d`, проверь `curl -s 'localhost:8428/api/v1/query?query=up' | jq`
   и UI `http://localhost:8428/vmui`.
2. Сравни в Grafana один и тот же `increase(prometheus_http_requests_total[1m])` из
   Prometheus и VM — объясни разницу (раздел 3).
3. **Буфер WAL:** `docker compose stop victoriametrics` на 5 минут, смотри
   `prometheus_remote_storage_samples_pending` и отставание; запусти VM — пропуска на
   графике из VM нет, Prometheus дослал из WAL.
4. Поставь в Prometheus `--storage.tsdb.retention.time=2h`: через день «вчера» есть
   только в VM — так и живут в проде (Prometheus — оперативка, VM — история).
5. Со звёздочкой: убери `remote_write` из Prometheus и собирай через vmagent; сравни
   память `prometheus` и `vmagent` (`docker stats`) — цифры запиши, выводы только по своим данным.

---

## 5. HA-пара и дедупликация

```text:no-line-numbers
   Prometheus-A (replica="A") ─┐ одинаковый конфиг, одинаковые цели
   Prometheus-B (replica="B") ─┤ каждая точка приходит ДВАЖДЫ
                               ▼
   Хранилище/запрос ── дедупликация ──► один ряд без «двойных» значений
   Алерты: обе реплики → кластер Alertmanager (сам дедуплицирует уведомления)
```

| Система | Как дедуплицирует | Что настроить |
|---------|-------------------|---------------|
| **Thanos** | На чтении: Querier склеивает ряды, отличающиеся только лейблом реплики | `external_labels: {replica: A}` + `--query.replica-label=replica` |
| **VictoriaMetrics** | На записи/чтении: из одинаковых рядов оставляет одну точку за интервал | ⭐ Ряды реплик должны совпадать: одинаковые `external_labels` **или** срезать `replica` на входе (relabeling), плюс `-dedup.minScrapeInterval` = интервал сбора |
| **Mimir** | На записи: HA tracker в distributor принимает данные только от одной реплики | Лейблы `cluster` + `__replica__`, включить HA tracker |

⭐ Частая ошибка — перенести схему Thanos на VM: реплики пишут с разными `replica`,
в VM оказывается **два разных ряда**, дедупликация «не работает», `sum()` удваивается.

---

## 6. Thanos vs Mimir vs VictoriaMetrics

| | **Thanos** | **Grafana Mimir** | **VictoriaMetrics** |
|---|------------|-------------------|---------------------|
| Идея | Надстройка над Prometheus: блоки TSDB в объектное хранилище | Горизонтально масштабируемый TSDB-кластер (наследник Cortex) | Отдельная быстрая TSDB, совместимая с Prometheus |
| Приём данных | Sidecar (загружает 2-часовые блоки) **или** Receive (remote_write) | remote_write → distributor → ingester | remote_write, vmagent, много протоколов |
| Хранилище | ⭐ S3/GCS/MinIO | ⭐ S3/GCS/MinIO | Локальные диски (PVC) |
| Downsampling | Есть (compactor: 5m, 1h) | Нет | Только Enterprise |
| Мультиаренда | Через Receive (tenants) | ⭐ Родная, лимиты на тенанта | Cluster: `accountID` |
| Число компонентов | Среднее: sidecar, query, store, compactor, (receive, ruler, query-frontend) | Много: distributor, ingester, querier, query-frontend, store-gateway, compactor, ruler; в 3.x — ingest storage на Kafka | Мало: 1 процесс или 3 роли |
| Язык | PromQL | PromQL (свой движок MQE) | MetricsQL (≈ надмножество PromQL) |
| Лицензия | Apache 2.0 | AGPLv3 | Apache 2.0 + Enterprise |
| Когда выбирать | Уже есть Prometheus и S3, нужен долгий дешёвый архив и глобальный query | Большая платформа, много команд-тенантов, экосистема Grafana | ⭐ Нужно просто и дёшево по ресурсам, небольшая команда, on-prem без S3 |

Как отвечать на собесе: «Для одной-двух команд и on-prem без объектного хранилища —
VictoriaMetrics single или cluster: меньше компонентов. Если есть S3 и нужен архив на
годы с downsampling — Thanos. Если это платформа для десятков команд с изоляцией
и лимитами — Mimir. Дальше решают эксплуатационная экспертиза команды и стоимость».
Объектное хранилище on-prem обычно поднимают через MinIO, в облаке — через S3-совместимый сервис.

---

## 7. kube-prometheus-stack в kind

Helm-чарт = **Prometheus Operator** + Prometheus + Alertmanager + Grafana +
node-exporter (DaemonSet) + kube-state-metrics + готовые правила и дашборды
(kubernetes-mixin) + ServiceMonitor'ы для kubelet, apiserver, CoreDNS и компонентов.
Основы Helm — [«15. Helm»](/kubernetes/15-helm).

```bash
kind create cluster --name mon
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install prometheus prometheus-community/kube-prometheus-stack \
  --version 91.7.1 -n monitoring --create-namespace -f kps-values.yaml   # проверь версию
```
```yaml
# kps-values.yaml — учебный минимум
prometheus:
  prometheusSpec:
    retention: 7d                         # дефолт чарта — 10d
    scrapeInterval: 30s
    enforcedSampleLimit: 50000            # страховка от «взрыва» одной цели (раздел 10)
    # remoteWrite: [{ url: http://vm.example:8428/api/v1/write }]   # долгое хранение
grafana:
  adminPassword: admin                    # только для стенда
kubeEtcd: { enabled: false }              # в kind эти компоненты слушают localhost,
kubeControllerManager: { enabled: false } # их таргеты были бы DOWN
kubeScheduler: { enabled: false }
kubeProxy: { enabled: false }
```
```bash
kubectl -n monitoring get pods
kubectl get crd | grep monitoring.coreos.com                # какие CRD принёс оператор
kubectl -n monitoring get prometheus,alertmanager,servicemonitors,prometheusrules
kubectl -n monitoring port-forward svc/prometheus-kube-prometheus-prometheus 9090 &
kubectl -n monitoring port-forward svc/prometheus-grafana 3000:80 &
```

Как это работает: ServiceMonitor/PrometheusRule (CRD) → Operator следит за ними → генерирует
`prometheus.yml` и файлы правил (Secret/ConfigMap) → Prometheus перечитывает. Руками
`prometheus.yml` в Kubernetes не правят — его пишет оператор.

⚠️ **Обновление CRD.** `helm upgrade` не обновляет CRD из каталога `crds/`. При
мажорном обновлении чарта CRD применяют заранее:
`kubectl apply --server-side -f <crds из архива чарта>` (CRD большие — client-side apply
упирается в лимит аннотации).

---

## 8. CRD Prometheus Operator и манифесты для linkd

| CRD | API | Зачем |
|-----|-----|-------|
| `Prometheus` | v1 | Сам сервер: реплики, retention, селекторы, remoteWrite |
| `PrometheusAgent` | v1alpha1 | Prometheus в agent mode |
| `Alertmanager` / `AlertmanagerConfig` | v1 / v1alpha1 | Кластер AM и маршруты «по кусочкам» от команд |
| ⭐ `ServiceMonitor` | v1 | Собирать метрики с **Service** (по его лейблам и имени порта) |
| `PodMonitor` | v1 | Собирать с подов напрямую (без Service) |
| `Probe` | v1 | Blackbox-проверки URL/Ingress |
| ⭐ `PrometheusRule` | v1 | Recording и alerting rules |
| `ScrapeConfig` | v1alpha1 | Произвольный scrape (static, file, DNS, HTTP SD) — цели вне кластера |
| `ThanosRuler` | v1 | Правила поверх Thanos Query |

Цепочка, по которой ищут «почему нет таргета»:
```text:no-line-numbers
Prometheus ──serviceMonitorSelector──► ServiceMonitor ──selector──► Service ──port NAME──► Endpoints ──► Pod
 (лейбл release!)                        (namespaceSelector)          (лейблы)                (readiness)
```

linkd из проекта: порт назван, лейблы `app.kubernetes.io/*`, `/metrics` на 8080.
Подставь свой namespace и лейблы чарта.

```yaml
# servicemonitor-linkd.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: linkd
  namespace: linkd
  labels:
    release: prometheus              # ⭐ = имя helm-релиза kube-prometheus-stack (раздел 9)
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: linkd  # лейблы SERVICE, не пода
  endpoints:
    - port: http                     # ИМЯ порта в Service, не номер
      path: /metrics
      interval: 30s
      metricRelabelings:             # = metric_relabel_configs
        - sourceLabels: [__name__]
          regex: 'python_gc_.*'
          action: drop
  sampleLimit: 5000                  # цель отдала больше — scrape целиком отбрасывается
```
```yaml
# prometheusrule-linkd.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: linkd
  namespace: linkd
  labels:
    release: prometheus              # ⭐ тот же селектор, только для правил
spec:
  groups:
    - name: linkd
      rules:
        - record: linkd:http_requests:rate5m
          expr: sum by (namespace, code) (rate(linkd_http_requests_total[5m]))
        - alert: LinkdDown
          expr: max by (namespace) (linkd_db_up) == 0
          for: 2m
          labels: { severity: critical }
          annotations:
            summary: "linkd в {{ $labels.namespace }} не видит базу"
            runbook_url: "https://git.example/linkd-platform/-/blob/main/runbooks/linkd-db-down.md"
        - alert: LinkdHighErrorRate
          expr: |
            sum by (namespace) (rate(linkd_http_requests_total{code=~"5.."}[5m]))
              / sum by (namespace) (rate(linkd_http_requests_total[5m])) > 0.05
          for: 5m
          labels: { severity: warning }
          annotations:
            summary: "linkd: {{ $value | humanizePercentage }} ответов 5xx"
```
Правила по SLO и burn rate относятся к отдельной теме SRE; здесь важен только способ
доставки правил в кластер.

```bash
kubectl apply -f servicemonitor-linkd.yaml -f prometheusrule-linkd.yaml
# Prometheus UI → /targets: serviceMonitor/linkd/linkd/0 ; /rules: группа linkd
promtool check rules <(kubectl get prometheusrule linkd -n linkd -o jsonpath='{.spec}' | yq -P)
```

Цели вне кластера (например, node_exporter на VM) — `ScrapeConfig`:
```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: ScrapeConfig
metadata: { name: legacy-vms, namespace: monitoring, labels: { release: prometheus } }
spec:
  staticConfigs:
    - targets: ['10.0.1.5:9100', '10.0.1.6:9100']
      labels: { env: prod, role: legacy }
```

---

## 9. ⭐ Ловушка лейбла `release`

По умолчанию в чарте `serviceMonitorSelectorNilUsesHelmValues: true` (и такие же флаги
для PodMonitor, Probe, PrometheusRule, ScrapeConfig). Тогда объект `Prometheus` получает:

```yaml
serviceMonitorSelector:
  matchLabels:
    release: prometheus        # имя helm-релиза
```

Симптом: ServiceMonitor создан, `kubectl get` его показывает, ошибок нигде нет, а таргета
на `/targets` **нет**. Prometheus его просто не выбирает.

```bash
# что реально выбирает Prometheus
kubectl -n monitoring get prometheus -o jsonpath='{.items[0].spec.serviceMonitorSelector}{"\n"}'
kubectl -n monitoring get prometheus -o jsonpath='{.items[0].spec.ruleSelector}{"\n"}'
# есть ли нужный лейбл у объекта
kubectl -n linkd get servicemonitor linkd --show-labels
```

| Решение | Плюсы | Минусы |
|---------|-------|--------|
| Ставить `release: <имя релиза>` на каждый объект | Работает с дефолтами | Имя релиза «зашито» в чарты приложений |
| `serviceMonitorSelectorNilUsesHelmValues: false` (и для rule/pod/probe/scrapeConfig) | Берёт **все** объекты во всех namespace | Любой ServiceMonitor в кластере попадёт в этот Prometheus |
| Свой селектор: `serviceMonitorSelector: {matchLabels: {monitoring: platform}}` | Явный контракт «что собирает этот Prometheus» | Надо договориться о лейбле со всеми командами |

Другие причины «нет таргета» по цепочке из раздела 8: селектор ServiceMonitor не совпал
с лейблами **Service** (а не пода), `port` указан номером или не тем именем, Service в
другом namespace без `namespaceSelector`, у Endpoints нет адресов (поды не Ready),
RBAC оператора не видит namespace. Смотреть: `/service-discovery`, логи оператора
(`kubectl -n monitoring logs deploy/prometheus-kube-prometheus-operator`).

---

## 10. Кардинальность под контролем

Основы — в [«02. Prometheus: базовые концепции»](/monitoring/02-prometheus-basics) (relabeling)
и [«09. Вопросы с собеседований»](/monitoring/09-interview) (вопрос 5); здесь — найти и ограничить.

```text:no-line-numbers
topk(10, count by (__name__) ({__name__=~".+"}))            # метрики-лидеры по рядам (тяжёлый запрос!)
topk(10, count by (job) ({__name__=~".+"}))                  # job'ы-лидеры
count(count by (path) (linkd_http_requests_total))           # сколько значений у лейбла
scrape_series_added                                           # сколько рядов добавил последний scrape
```
```bash
curl -s localhost:9090/api/v1/status/tsdb | jq '.data.seriesCountByMetricName[:10]'
promtool tsdb analyze /prometheus                           # внутри контейнера/пода
# VictoriaMetrics: vmui → Cardinality explorer
```

Инструменты ограничения — от «лечим» к «страхуемся»:

| Уровень | Как |
|---------|-----|
| Код | Не класть в лейблы `user_id`, полный URL, `request_id`; шаблон пути (`/r/:code`, как в linkd) |
| Сбор | `metric_relabel_configs` / `metricRelabelings`: `drop` метрик, `labeldrop` лейблов |
| Отправка | `write_relabel_configs`: в долгое хранилище — только нужное (раздел 2) |
| Лимит на цель | `sample_limit`, `label_limit`, `label_name_length_limit`, `label_value_length_limit`; в Operator — `sampleLimit` в ServiceMonitor и `enforcedSampleLimit` / `enforcedLabelLimit` в `Prometheus` |
| Лимит на job | `target_limit` / `enforcedTargetLimit` |
| Хранилище | vmagent `-remoteWrite.maxHourlySeries`/`-remoteWrite.maxDailySeries`; лимиты на тенанта в Mimir; `-search.maxUniqueTimeseries` в VM |

⚠️ При превышении `sample_limit` отбрасывается **весь scrape** цели, а `up` становится 0 —
лимит превращает «взрыв кардинальности» в понятный алерт, а не в OOM всего Prometheus.
Метрика `prometheus_target_scrapes_exceeded_sample_limit_total` показывает, что лимит сработал.

---

## 11. Сколько нужно ресурсов: правило большого пальца

> ⚠️ Это **грубые ориентиры** для первой прикидки, а не гарантии. Реальные цифры зависят
> от churn рядов, длины лейблов, запросов и версии. Меряй на своих данных.

```text:no-line-numbers
активные ряды (prometheus_tsdb_head_series)   = N
точек в секунду                               = N / scrape_interval
RAM Prometheus  ≈ N × 3–4 КБ  (+ запросы, + ~25% при remote_write)
диск Prometheus ≈ точек/с × 86400 × дни × 1–2 байта

пример: N = 1 000 000, интервал 30 с
  точек/с ≈ 33 000
  RAM     ≈ 3–4 ГБ + запас → нода 8 ГБ
  диск    ≈ 33 000 × 86400 × 1.5 Б ≈ 4.3 ГБ/сутки → 15 дней ≈ 65 ГБ
```
Долгие хранилища обычно заметно экономнее на точку (сжатие, downsampling у Thanos),
но «во сколько раз» — только по своему бенчмарку. Первый шаг экономии всегда один:
**не собирать и не отправлять лишнее**.

---

## 12. Грабли

| Грабля | Симптом | Решение |
|--------|---------|---------|
| ⭐ Нет лейбла `release` | ServiceMonitor/PrometheusRule есть, таргета/правила нет | Лейбл или свой селектор (раздел 9) |
| `port: 8080` вместо имени | Таргета нет | Именованный порт в Service, `port: http` |
| Селектор по лейблам пода | Таргета нет | ServiceMonitor выбирает **Service** |
| Нет `external_labels` | В общем хранилище ряды кластеров смешались | `cluster`, `env`, `replica` |
| Схема Thanos на VM | Дедупликация «не работает», суммы удвоены | Одинаковые ряды реплик + `-dedup.minScrapeInterval` |
| Хранилище лежит > 2 ч | Дыра в долгом хранилище | Алерт на отставание remote_write, vmagent с дисковым буфером |
| Отправляют всё подряд | Хранилище дорожает, запросы медленнее | `write_relabel_configs` |
| `helm upgrade` без CRD | Новые поля «не работают», оператор ругается | Обновлять CRD `--server-side` перед чартом |
| Дашборды с Prometheus на VM «врут» | `increase` отличается | Разные определения, перепроверить алерты |
| Нет лимитов | Один релиз с `user_id` в лейбле — OOM Prometheus | `sampleLimit`, `enforcedSampleLimit`, ревью метрик |
| Год данных в одном Prometheus | Огромный диск, минуты на запрос, риск потерять всё | Prometheus — оперативка, история — во внешнем хранилище |

---

## 💼 Как это в DevOps

- Типовая схема: в каждом кластере kube-prometheus-stack (HA-пара, retention 1–7 дней),
  `remote_write` в общее хранилище, Grafana смотрит в хранилище, алерты считаются локально
  (переживают потерю связи с центром).
- Сервисы подключаются к мониторингу из **своих** чартов: ServiceMonitor и PrometheusRule
  лежат рядом с Deployment, правила проверяются `promtool` в CI. Командам нужен один
  понятный контракт — лейбл, который выбирает Prometheus.
- Выбор хранилища объясняют ресурсами и экспертизой, а не модой: VictoriaMetrics — просто
  и дёшево, Thanos — архив в S3, Mimir — платформа для многих команд.
- Кардинальность — на ревью метрик так же, как SQL-запросы на ревью кода; лимиты стоят
  заранее, а не после первого OOM.
- VM и серверы вне Kubernetes — node_exporter + `ScrapeConfig`/vmagent, или Zabbix
  (см. [«10. Zabbix»](/monitoring/10-zabbix)), если он уже живёт в компании.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Отправить метрики наружу | `remote_write: [{url: …/api/v1/write}]` |
| Не отправлять лишнее | `write_relabel_configs` с `action: drop` |
| Понять, успевает ли remote_write | `prometheus_remote_storage_samples_pending`, отставание timestamp'ов |
| Prometheus только для сбора | `--agent` или vmagent |
| VM single | `victoria-metrics -retentionPeriod=12 -dedup.minScrapeInterval=15s` |
| Дедупликация в Thanos | `external_labels.replica` + `--query.replica-label=replica` |
| Поставить стек в k8s | `helm install prometheus prometheus-community/kube-prometheus-stack -n monitoring` |
| Подключить сервис | `ServiceMonitor` (+ `release: prometheus`, `port: <имя>`) |
| Правила / цели вне кластера | `PrometheusRule` с тем же лейблом / `ScrapeConfig` (v1alpha1) |
| Что выбирает Prometheus | `kubectl get prometheus -o jsonpath='{..serviceMonitorSelector}'` |
| Метрики-лидеры по рядам | `/api/v1/status/tsdb`, `topk(10, count by (__name__)(…))` |
| Ограничить цель | `sampleLimit` / `enforcedSampleLimit` |
| Обновить CRD | `kubectl apply --server-side -f crds/` |

---

## 🧠 Что запомнить

1. Одного Prometheus мало из-за retention, HA, глобального взгляда и масштаба; federation
   это не решает.
2. `remote_write` читает WAL и шлёт пачками; при недоступности хранилища данные ждут
   ~2 часа, дальше теряются — отставание нужно мониторить.
3. `external_labels` обязательны: `cluster`, `env`, для HA — `replica`.
4. VictoriaMetrics: single до ~1 млн точек/с, cluster — `vminsert/vmselect/vmstorage`
   и `accountID`; vmagent — лёгкий сбор с дисковым буфером.
5. MetricsQL близок к PromQL, но `rate/increase` считает иначе — цифры могут отличаться.
6. ⭐ Дедупликация: Thanos склеивает по лейблу реплики на чтении; VM требует одинаковых
   рядов и `-dedup.minScrapeInterval`; Mimir — HA tracker на записи.
7. Thanos — S3 и downsampling; Mimir — мультиаренда и масштаб; VM — простота и ресурсы.
8. kube-prometheus-stack = Operator + Prometheus + Alertmanager + Grafana + экспортеры +
   готовые правила; `prometheus.yml` пишет оператор из CRD.
9. ⭐ ServiceMonitor и PrometheusRule без лейбла `release: <релиз>` при дефолтных values
   молча игнорируются; ServiceMonitor ищет Service по лейблам и порт по имени.
10. Кардинальность: найти (`/api/v1/status/tsdb`), срезать (relabeling), ограничить
    (`sample_limit`), а ресурсы прикидывать правилом большого пальца и проверять замером.

---

## Задачи

> Стенды: compose с VictoriaMetrics из раздела 4 конспекта; kind + kube-prometheus-stack
> из раздела 7. Для C6–C8 нужен linkd в кластере или любой сервис с `/metrics`
> и именованным портом.

---

### Блок A. Теория

**A1.** Назови четыре причины, по которым одного Prometheus в проде недостаточно.

<details><summary>Ответ</summary>

Ограниченный локальный retention и риск потерять всё с диском; нет HA без
дублирования данных; нет глобального взгляда на несколько кластеров; память и диск
одной ноды ограничивают число рядов; тяжёлые запросы за длинный период.

</details>

**A2.** Как устроен `remote_write`? Что происходит, если хранилище недоступно 30 минут?
А 3 часа?

<details><summary>Ответ</summary>

Prometheus читает WAL и отправляет пачками через шарды очереди. 30 минут —
повторы с backoff, данные ждут в WAL и досылаются. Больше ~2 часов — WAL компактится,
неотправленное теряется, в долгом хранилище остаётся дыра.

</details>

**A3.** ⭐ Зачем нужны `external_labels` и какие лейблы ты туда поставишь?

<details><summary>Ответ</summary>

Чтобы в общем хранилище и в Alertmanager различать источники: `cluster`, `env`,
`region`; для HA-пары — `replica` (с учётом того, как дедуплицирует хранилище).

</details>

**A4.** Что такое agent mode Prometheus и чем он похож на vmagent?

<details><summary>Ответ</summary>

Режим `--agent`: только сбор и `remote_write`, без локальных запросов, правил и
долгого хранения. Как и vmagent — «сборщик на краю»: VM вне кластера, филиал, маленький
кластер без своей оперативки.

</details>

**A5.** Чем VictoriaMetrics single-node отличается от cluster? Когда нужен cluster?

<details><summary>Ответ</summary>

Single — один процесс, запись и чтение на 8428, проще в эксплуатации; по документации
VM предпочтителен до ~1 млн точек/с. Cluster — vminsert/vmselect/vmstorage, горизонтальный
рост, репликация `-replicationFactor`, мультиаренда через `accountID`.

</details>

**A6.** Какие компоненты есть у VictoriaMetrics кроме самого хранилища и зачем каждый?

<details><summary>Ответ</summary>

vmagent — сбор и отправка с дисковым буфером, relabeling, лимиты; vmalert —
правила поверх VM и отправка в Alertmanager; vmauth — прокси с авторизацией и
маршрутизацией; vmbackup/vmrestore — бэкапы; vmui — веб-интерфейс запросов.

</details>

**A7.** Назови три отличия MetricsQL от PromQL. Почему дашборд может показать разные
числа на Prometheus и на VM?

<details><summary>Ответ</summary>

`rate/increase` без экстраполяции и с учётом точки до окна; окно `[…]` можно
опустить; `WITH`-шаблоны; `keep_metric_names`; NaN удаляются. Из-за другого определения
`increase` и краёв окна числа на коротких окнах отличаются.

</details>

**A8.** ⭐ Как устроена дедупликация HA-пары в Thanos, VictoriaMetrics и Mimir?

<details><summary>Ответ</summary>

Thanos: реплики пишут с разным лейблом реплики, Querier склеивает на чтении
(`--query.replica-label`). VM: из одинаковых рядов оставляет одну точку за
`-dedup.minScrapeInterval` — ряды реплик должны совпадать (одинаковые `external_labels`
или срез лейбла реплики на входе). Mimir: HA tracker в distributor принимает данные
только от одной реплики по лейблам `cluster`/`__replica__`.

</details>

**A9.** Сравни Thanos, Mimir и VictoriaMetrics: хранилище, downsampling, мультиаренда,
число компонентов, лицензия.

<details><summary>Ответ</summary>

Thanos — S3, downsampling есть, мультиаренда через Receive, среднее число компонентов,
Apache 2.0. Mimir — S3, без downsampling, родная мультиаренда с лимитами, много компонентов,
AGPLv3. VM — локальные диски, downsampling только Enterprise, `accountID` в cluster,
мало компонентов, Apache 2.0 + Enterprise.

</details>

**A10.** Что входит в kube-prometheus-stack?

<details><summary>Ответ</summary>

Prometheus Operator, Prometheus, Alertmanager, Grafana с дашбордами,
node-exporter, kube-state-metrics, правила kubernetes-mixin, ServiceMonitor'ы для
компонентов кластера, CRD оператора.

</details>

**A11.** Какие CRD приносит Prometheus Operator? Чем ServiceMonitor отличается от PodMonitor
и от ScrapeConfig?

<details><summary>Ответ</summary>

Prometheus, PrometheusAgent, Alertmanager, AlertmanagerConfig, ServiceMonitor,
PodMonitor, Probe, PrometheusRule, ScrapeConfig, ThanosRuler. ServiceMonitor выбирает
Service и его Endpoints, PodMonitor — поды напрямую (когда Service нет или не нужен),
ScrapeConfig — произвольный scrape, в том числе цели вне кластера.

</details>

**A12.** ⭐ Почему ServiceMonitor может быть создан без ошибок, а таргета нет? Назови
минимум пять причин.

<details><summary>Ответ</summary>

Нет лейбла, который ждёт `serviceMonitorSelector` (`release`); селектор
ServiceMonitor не совпал с лейблами Service; `port` указан номером или чужим именем;
Service в другом namespace без `namespaceSelector`; у Endpoints нет адресов (поды не Ready);
Prometheus не выбирает namespace (`serviceMonitorNamespaceSelector`); RBAC; неверный `path`
(тогда таргет есть, но DOWN).

</details>

**A13.** Что делает `serviceMonitorSelectorNilUsesHelmValues` и какие есть варианты его
настройки?

<details><summary>Ответ</summary>

При `true` и пустом селекторе чарт подставляет `matchLabels: {release: <релиз>}`.
Варианты: ставить лейбл на объекты; `false` — брать все объекты; задать свой явный
селектор (например `monitoring: platform`).

</details>

**A14.** Какие инструменты ограничения кардинальности есть в Prometheus, Operator и VM?

<details><summary>Ответ</summary>

Prometheus: `metric_relabel_configs`, `write_relabel_configs`, `sample_limit`,
`label_limit`, длины лейблов, `target_limit`. Operator: `metricRelabelings`, `sampleLimit`
в ServiceMonitor, `enforcedSampleLimit`/`enforcedLabelLimit`/`enforcedTargetLimit`
в `Prometheus`. VM: vmagent `-remoteWrite.maxHourlySeries`/`maxDailySeries`,
`-search.maxUniqueTimeseries`, cardinality explorer.

</details>

**A15.** Как грубо прикинуть RAM и диск Prometheus для N активных рядов? Почему это
только ориентир?

<details><summary>Ответ</summary>

RAM ≈ N × 3–4 КБ плюс запросы и ~25% на remote_write; диск ≈ N / интервал ×
86400 × дни × 1–2 байта. Ориентир, потому что влияют churn, длина лейблов, запросы,
версия; проверяется замером.

</details>

---

### Блок B. «Что делает / что тут не так»

```yaml
B1.  remote_write:
       - url: http://vm:8428/api/v1/write
     # external_labels не заданы, три кластера пишут в одну VM

B2.  remote_write:
       - url: http://vm:8428/api/v1/write
         write_relabel_configs:
           - source_labels: [__name__]
             regex: 'go_.*|process_.*'
             action: drop

B3.  # два Prometheus HA-пары пишут в одну VM single-node
     global: { external_labels: { cluster: prod, replica: A } }   # у второго replica: B
     # VM запущена с -dedup.minScrapeInterval=15s

B4.  victoria-metrics -retentionPeriod=12 -dedup.minScrapeInterval=30s   # scrape_interval 30s

B5.  thanos query --query.replica-label=replica --endpoint=sidecar-a:10901 --endpoint=sidecar-b:10901

B6.  apiVersion: monitoring.coreos.com/v1
     kind: ServiceMonitor
     metadata: { name: api, namespace: shop }
     spec:
       selector: { matchLabels: { app: api } }
       endpoints: [{ port: "8080", path: /metrics }]

B7.  apiVersion: monitoring.coreos.com/v1
     kind: ServiceMonitor
     metadata: { name: api, namespace: shop, labels: { release: prometheus } }
     spec:
       selector: { matchLabels: { app.kubernetes.io/name: api } }
       endpoints: [{ port: http, interval: 5s }]
       sampleLimit: 200

B8.  # kps-values.yaml
     prometheus:
       prometheusSpec:
         serviceMonitorSelectorNilUsesHelmValues: false
         ruleSelectorNilUsesHelmValues: false

B9.  prometheus:
       prometheusSpec:
         retention: 365d
         storageSpec: {}     # без PVC
```

<details><summary>Ответ (B1–B9)</summary>

**B1.** Ряды разных кластеров неразличимы и сливаются; обязательно `external_labels.cluster`.
**B2.** В долгое хранилище не уходят метрики рантайма — экономия, в оперативке они остаются.
**B3.** Разные `replica` → в VM два разных ряда, дедупликация не сработает, суммы удвоятся.
Для VM ряды реплик должны совпадать.
**B4.** Хранить 12 месяцев, дедуп по интервалу сбора — корректно.
**B5.** Thanos Querier над двумя sidecar'ами с дедупликацией по лейблу `replica` — HA-пара.
**B6.** Нет `release`-лейбла (при дефолтах чарта не выберут), `port` — номер вместо имени,
селектор по «голому» `app` — проверить, что такой лейбл есть у Service.
**B7.** Корректно, но интервал 5 с — дорого без причины, а `sampleLimit: 200` мал для
большинства сервисов: при превышении весь scrape отбросится, `up` = 0.
**B8.** Prometheus берёт все ServiceMonitor и PrometheusRule кластера без лейбла — удобно
на стенде, в общем кластере — без контроля.
**B9.** Год в Prometheus без PVC — данные исчезнут при пересоздании пода; год — задача
долгого хранилища.

</details>

```text:no-line-numbers
B10. topk(10, count by (__name__) ({__name__=~".+"}))
B11. prometheus_remote_storage_highest_timestamp_in_seconds
       - ignoring(remote_name, url) group_right
         prometheus_remote_storage_queue_highest_sent_timestamp_seconds > 120
B12. increase(http_requests_total[1m])        # в Prometheus 7.5, в VM 7
```

<details><summary>Ответ (B10–B12)</summary>

**B10.** Топ метрик по числу рядов — тяжёлый запрос, только разово.
**B11.** Отставание `remote_write` больше 2 минут — основа алерта.
**B12.** Разные определения `increase`: Prometheus экстраполирует, VM — нет.

</details>

```bash
B13. helm upgrade prometheus prometheus-community/kube-prometheus-stack -n monitoring --version <новая мажорная>
B14. kubectl -n monitoring get prometheus -o jsonpath='{.items[0].spec.serviceMonitorSelector}'
```

<details><summary>Ответ (B13–B14)</summary>

**B13.** CRD чартом не обновятся — сначала `kubectl apply --server-side` CRD новой версии.
**B14.** Узнать, по какому лейблу Prometheus выбирает ServiceMonitor'ы.

</details>

Оцени решения:
```text:no-line-numbers
B15. "Храним метрики 2 года в Prometheus на PVC 4 ТБ — зачем лишние системы"
B16. "Ставим Mimir для одного кластера и одной команды, потому что это модно"
B17. "Каждая команда сама ставит kube-prometheus-stack в свой namespace"
B18. "Лимиты на сбор не ставим — если что, увеличим память"
```

<details><summary>Ответ (B15–B18)</summary>

**B15.** Нет downsampling, запросы за годы тяжёлые, потеря PVC = потеря истории, нет
глобального взгляда. Prometheus — оперативка, история — во внешнем хранилище.
**B16.** Mimir оправдан для платформы с многими тенантами; для одного кластера это много
компонентов без выгоды — VM single или Thanos проще.
**B17.** Дубли node-exporter и kube-state-metrics, конфликт CRD, N копий одного и того же.
Один стек на кластер, команды приносят ServiceMonitor/PrometheusRule.
**B18.** Один релиз с `user_id` в лейбле — OOM всего Prometheus. Лимиты превращают
взрыв в понятный `up == 0` на одной цели.

</details>

---

### Блок C. Практика

#### C1. 🔑 VictoriaMetrics как удалённое хранилище
1. Добавь в compose VictoriaMetrics из раздела 4, настрой `remote_write` в Prometheus.
2. Проверь запрос `up` через API VM и в `/vmui`.
3. Подключи VM вторым источником в Grafana, построй одну панель из обоих источников.

#### C2. Буфер и отставание
1. Выведи на дашборд `prometheus_remote_storage_samples_pending` и отставание из B11.
2. Останови VM на 5 минут, наблюдай метрики, запусти обратно.
3. Убедись, что на графике из VM дыры нет. Объясни, что было бы при простое 3 часа.
4. Добавь алерт «remote_write отстаёт больше 5 минут».

<details><summary>Ответ</summary>

При простое дольше ~2 часов неотправленные данные потеряются. Алерт — выражение
из B11 с порогом 300 и `for`.

</details>

#### C3. Что отправлять
1. Посчитай число рядов в Prometheus и в VM.
2. Добавь `write_relabel_configs`, отбрасывающий `go_.*` и `prometheus_.*`.
3. Сравни, как изменилось число рядов в VM, а в Prometheus — нет. Почему?

<details><summary>Ответ</summary>

`write_relabel_configs` влияет только на отправку; локально Prometheus продолжает
хранить всё.

</details>

#### C4. MetricsQL
1. Выполни в VM `rate(node_network_receive_bytes_total)` без окна — объясни результат.
2. Сравни `increase(...[1m])` в Prometheus и VM на одном и том же ряду.
3. Напиши запрос с `WITH` для доли ошибок приложения из практической лабы.

#### C5. HA-пара (со звёздочкой)
1. Подними второй Prometheus с тем же конфигом, оба пишут в VM.
2. Вариант 1: разные `replica` → посчитай `count(up)` в VM и объясни результат.
3. Вариант 2: одинаковые `external_labels` (или срез `replica` на входе VM) + dedup →
   повтори подсчёт. Какой вариант правильный для VM и почему для Thanos наоборот?

<details><summary>Ответ</summary>

С разными `replica` `count(up)` в VM удваивается. Для VM правильно одинаковые
ряды + dedup; Thanos, наоборот, требует разный лейбл реплики, чтобы склеивать на чтении.

</details>

#### C6. 🔑 kube-prometheus-stack в kind
1. Поставь чарт с `kps-values.yaml` из раздела 7.
2. Перечисли поды и CRD `monitoring.coreos.com`, объясни, кто за что отвечает.
3. Открой Prometheus → `/targets` и Grafana: найди готовые дашборды по нодам и подам.
4. Найди, откуда взялись правила (`kubectl -n monitoring get prometheusrules`).

#### C7. ⭐ ServiceMonitor для linkd и ловушка `release`
1. Задеплой linkd (или свой сервис) с именованным портом `http`.
2. Создай ServiceMonitor **без** лейбла `release` — убедись, что таргета нет.
3. Найди причину через `serviceMonitorSelector` объекта Prometheus.
4. Добавь лейбл — таргет появился. Затем укажи `port: "8080"` вместо имени — что сломалось?
5. Со звёздочкой: переключи чарт на свой селектор `monitoring: platform` и опиши
   контракт для команд в трёх строках.

<details><summary>Ответ</summary>

С `port: "8080"` таргет пропадает: `port` в ServiceMonitor — **имя** порта Service.
Порт контейнера (имя или номер) задают отдельным полем `targetPort`.

</details>

#### C8. PrometheusRule
1. Примени `PrometheusRule` для linkd из раздела 8.
2. Найди группу на `/rules`, recording rule — в Explore Grafana.
3. Включи учебный фолт `LINKD_FAULT_ERROR_RATE` и дождись `LinkdHighErrorRate`
   в Alertmanager.
4. Проверь правила `promtool check rules` до применения (из файла в git).

#### C9. Кардинальность
1. Найди топ-10 метрик по числу рядов через `/api/v1/status/tsdb`.
2. Добавь в ServiceMonitor `metricRelabelings`, отбрасывающий одну из них.
3. Поставь `sampleLimit: 50` и посмотри, что станет с `up` и
   `prometheus_target_scrapes_exceeded_sample_limit_total`. Верни нормальный лимит.

<details><summary>Ответ</summary>

При превышении `sampleLimit` весь scrape цели отбрасывается, `up` = 0, растёт
`prometheus_target_scrapes_exceeded_sample_limit_total`.

</details>

#### C10. Прикидка ресурсов
Для своего кластера kind: возьми `prometheus_tsdb_head_series`, интервал сбора и посчитай
RAM и диск на 15 дней по правилу из раздела 11. Сравни с фактическими `container_memory_working_set_bytes`
пода Prometheus и размером PVC/каталога. Запиши, во сколько раз ошибся.

---

### Блок D. Инциденты

**D1.** В общей VM графики «ошибки по кластерам» показывают один кластер вместо трёх.

<details><summary>Ответ</summary>

Нет `external_labels.cluster` (или одинаковый у всех) — ряды слились. Задать
уникальный `cluster` каждому Prometheus.

</details>

**D2.** После добавления второй реплики Prometheus RPS на дашборде из VM вырос ровно вдвое.

<details><summary>Ответ</summary>

Реплики пишут разные ряды (`replica` A/B) в VM без среза этого лейбла —
дедупликация не срабатывает. Выровнять ряды или срезать лейбл на входе, dedup-интервал.

</details>

**D3.** Ночью хранилище было недоступно 4 часа; в истории дыра, хотя Prometheus работал.

<details><summary>Ответ</summary>

Простой больше ~2 часов — WAL компактится, неотправленное потеряно. Алерт на
доступность хранилища и отставание, vmagent с дисковым буфером, HA хранилища.

</details>

**D4.** `prometheus_remote_storage_samples_pending` растёт весь день, отставание — 40 минут.

<details><summary>Ответ</summary>

Не хватает шардов/пропускной способности, хранилище медленно отвечает, сеть,
слишком много рядов. Смотреть `shards_desired` vs `max_shards`, ошибки, латентность
записи; поднять `max_shards`, срезать лишнее `write_relabel_configs`, масштабировать приём.

</details>

**D5.** Команда создала ServiceMonitor, `kubectl get servicemonitor` его показывает,
таргета нет, ошибок в событиях нет.

<details><summary>Ответ</summary>

Цепочка из раздела 8: лейбл `release` (селектор Prometheus), лейблы Service,
имя порта, namespace, Ready-эндпоинты, логи оператора и `/service-discovery`.

</details>

**D6.** После `helm upgrade` kube-prometheus-stack оператор пишет в лог ошибки про
неизвестные поля, часть настроек не применилась.

<details><summary>Ответ</summary>

CRD не обновились вместе с чартом. Применить CRD новой версии `--server-side`,
затем `helm upgrade`.

</details>

**D7.** Prometheus в кластере перезапускается по OOMKilled после релиза одного сервиса.

<details><summary>Ответ</summary>

Взрыв кардинальности в новом релизе. Найти метрику (`/api/v1/status/tsdb`,
`scrape_series_added`), срезать `metricRelabelings`, поставить `sampleLimit`, исправить код.

</details>

**D8.** Алерты, перенесённые с Prometheus на vmalert, стали срабатывать «чуть по-другому».

<details><summary>Ответ</summary>

Разная семантика `rate/increase` в MetricsQL; пересмотреть окна и пороги,
проверить алерты на исторических данных.

</details>

**D9.** Запрос «p99 за 90 дней» в Grafana висит минутами и роняет querier.

<details><summary>Ответ</summary>

Сырые точки за 90 дней: нужны recording rules, downsampling (Thanos) или
агрегированные ряды, query-frontend с кэшем и лимиты на запросы.

</details>

**D10.** Правило есть в `PrometheusRule`, на `/rules` его нет.

<details><summary>Ответ</summary>

У `PrometheusRule` нет лейбла из `ruleSelector`, или правило с синтаксической
ошибкой отвергнуто (смотреть логи оператора, `promtool check rules`).

</details>

---

### Блок E. Вопросы с собеседования

**1.** Почему одного Prometheus недостаточно и что делают вместо этого?

<details><summary>Ответ</summary>

Retention, HA, глобальный взгляд, масштаб; `remote_write` в VictoriaMetrics/Thanos/Mimir,
Prometheus — оперативка.

</details>

**2.** Как работает `remote_write` и как понять, что он не успевает?

<details><summary>Ответ</summary>

Читает WAL, шлёт пачками по шардам; смотрю pending, ошибки и отставание timestamp'ов,
помню про ~2 часа WAL.

</details>

**3.** Сравни Thanos, Mimir и VictoriaMetrics. Что выберешь и почему?

<details><summary>Ответ</summary>

VM — просто и экономно; Thanos — S3 и downsampling; Mimir — мультиаренда и масштаб.
Выбор — по объёму, S3, числу команд и экспертизе.

</details>

**4.** Как сделать Prometheus отказоустойчивым и не получить двойные данные?

<details><summary>Ответ</summary>

Две одинаковые реплики + дедупликация в хранилище (под его модель) + кластер Alertmanager.

</details>

**5.** Что такое Prometheus Operator и kube-prometheus-stack?

<details><summary>Ответ</summary>

Оператор превращает CRD в конфиг Prometheus; kube-prometheus-stack — чарт с оператором,
Prometheus, Alertmanager, Grafana, экспортерами и готовыми правилами.

</details>

**6.** Чем ServiceMonitor отличается от PodMonitor?

<details><summary>Ответ</summary>

ServiceMonitor — через Service и его Endpoints; PodMonitor — напрямую по подам.

</details>

**7.** ServiceMonitor есть, таргета нет — твои действия?

<details><summary>Ответ</summary>

Селектор Prometheus и лейбл `release`, лейблы Service, имя порта, namespace,
Endpoints, `/service-discovery`, логи оператора.

</details>

**8.** Как бороться с кардинальностью в Kubernetes?

<details><summary>Ответ</summary>

Правила именования и ревью метрик, `metricRelabelings`, `sampleLimit`/`enforcedSampleLimit`,
`write_relabel_configs`, мониторинг `head_series`.

</details>

**9.** Как прикинуть ресурсы под Prometheus?

<details><summary>Ответ</summary>

Правило большого пальца (RAM ≈ ряды × 3–4 КБ, диск ≈ точки × 1–2 байта), затем замер.

</details>

**10.** Что такое agent mode и когда он нужен?

<details><summary>Ответ</summary>

Prometheus только собирает и отправляет — на краю, в филиалах, маленьких кластерах.

</details>

---

### 🎯 Чек-лист

- [ ] Объясняю, почему одного Prometheus мало и что делают вместо federation
- [ ] Настроил `remote_write` в VictoriaMetrics и мониторю отставание
- [ ] Знаю про ~2 часа WAL и проверил поведение при простое хранилища
- [ ] Отличаю VM single от cluster и знаю, зачем vmagent и vmalert
- [ ] Знаю отличия MetricsQL от PromQL и их последствия для алертов
- [ ] ⭐ Объясняю дедупликацию HA-пары в Thanos, VM и Mimir
- [ ] Сравниваю Thanos, Mimir и VM с аргументами, а не по моде
- [ ] Поставил kube-prometheus-stack в kind и знаю, что внутри
- [ ] ⭐ Подключил сервис через ServiceMonitor и знаю ловушку `release`
- [ ] Доставляю правила через PrometheusRule и проверяю их `promtool`
- [ ] Нахожу и ограничиваю кардинальность, прикидываю ресурсы и проверяю замером
