---
title: "04. OpenCost и Kubecost: сколько стоит каждый namespace"
description: "Блок → FinOps → тема 04. Опирается на"
---

# 04. OpenCost и Kubecost: сколько стоит каждый namespace

> Блок → FinOps → тема 04. Опирается на
> [../Left/02_Monitoring/03_promql.md](/monitoring/03-promql) (джойны `on`/`group_left`,
> recording rules), [../Left/02_Monitoring/06_grafana.md](/monitoring/06-grafana)
> (дашборды) и темы [01](/finops/01-finops-intro) (showback, общие расходы) и
> [02](/finops/02-k8s-rightsizing) (requests и эффективность).
>
> **После темы ты умеешь:** выбрать между OpenCost и Kubecost (с учётом статуса на 2026 год),
> поставить OpenCost рядом с kube-prometheus-stack, настроить свои цены для on-prem/kind,
> понимать модель allocation (CPU/RAM/GPU/PV/сеть, idle, общие расходы), доставать данные
> через API, UI и `kubectl cost`, выводить стоимость в Grafana, алертить на всплески
> и собирать showback-отчёт по командам.

---

## 🗺️ Карта темы

```text
 kube-state-metrics + cAdvisor ──► Prometheus ◄── scrape ── OpenCost (цены нод, PV, LB → метрики)
                                       │                        │
                                       └──── запросы ──────────►│ allocation-модель
                                                                │
          ┌───────────────────────┬─────────────────────────────┼───────────────────────┐
          ▼                       ▼                             ▼                       ▼
   UI :9090              API :9003 /allocation         kubectl cost            метрики *_hourly_cost
   (по namespace,        (namespace, label:team,       (из терминала)          → Grafana, алерты
    controller, pod)      controller, idle)                                    → showback-отчёт
```text
---

## 1. OpenCost или Kubecost: расклад на 2026 год

| | OpenCost | Kubecost (IBM) |
|---|----------|----------------|
| Что это | Открытый движок и спецификация allocation для k8s | Коммерческий продукт, построенный вокруг того же движка |
| Лицензия, владелец | Apache 2.0, проект CNCF (**Incubating** с октября 2024); мейнтейнеры — IBM Kubecost, Randoli и сообщество | IBM купила Kubecost в сентябре 2024; продукт в линейке IBM Apptio (Cloudability, Turbonomic) |
| Источник данных | Prometheus; с 2025 есть режим без Prometheus («Promless») | Kubecost 3.0 (сентябрь 2025): свой агент, ClickHouse, без зависимости от Prometheus |
| Цены | Публичные прайсы облаков или свои (custom pricing) | + сверка со счётом (скидки, резервы), cloud costs |
| Кластеры | Одна установка — один кластер | Федерация многих кластеров |
| Сверх allocation | UI, API, `/cloudCost`, плагины внешних расходов, MCP-сервер для AI-агентов | Рекомендации по requests и node groups, бюджеты, алерты, аномалии, прогноз, SSO/RBAC |
| Бесплатно | Всё | Free tier; в 3.0 ограничен объёмом расходов (порядка $100k за 30 дней), а не числом ядер, как раньше — проверяй условия на сайте |

```text
Выбор:
  учиться, один-два кластера, нужна прозрачность и API      → OpenCost
  десятки кластеров, нужна сверка со счётом, рекомендации,
  SSO и готовые отчёты для финансов, есть бюджет             → Kubecost / аналоги (CAST AI, Vantage и др.)
```text
> 💡 Концепции одинаковые: allocation по namespace/лейблам, idle, эффективность, общие расходы.
> Разобравшись с OpenCost, в Kubecost ты будешь как дома.

---

## 2. Модель allocation: как OpenCost считает деньги

```text
стоимость контейнера за интервал =
      max(CPU request, CPU usage)   × цена vCPU·час × часы
    + max(RAM request, RAM usage)   × цена GiB·час  × часы
    + GPU (по requests)             × цена GPU·час  × часы
    + PV (по PVC пода)              × цена GiB·час  × часы
    + сеть и LoadBalancer (если настроено)

цена ноды = прайс по типу инстанса (облако) или custom pricing; делится на CPU/RAM/GPU
idle      = стоимость нод − всё, что распределено по контейнерам
```text
- **`max(request, usage)`**: запросил 2 ядра, использовал 0,2 — платишь за 2 (ты их занял).
  Использовал 3 при request 2 (без лимита) — платишь за 3.
- **Idle** (`__idle__`) — оплаченная, но никем не запрошенная мощность нод. Её можно
  показывать отдельно или распределять (`shareIdle`) — раздел 5.
- **Эффективность** — `usage / request` в деньгах: `cpuEfficiency`, `ramEfficiency`, `totalEfficiency`.
- **Агрегации:** `cluster`, `node`, `namespace`, `controllerKind`, `controller`, `pod`, `container`,
  `service`, `label:&lt;ключ&gt;` (например, `label:team`), и их комбинации.

---

## 3. Установка OpenCost рядом с kube-prometheus-stack

Предполагается стенд из [00_INDEX.md](/finops/): релиз `prometheus` в namespace `monitoring`,
сервис `prometheus-kube-prometheus-prometheus:9090` (проверь: `kubectl -n monitoring get svc`).

```yaml
# values-opencost.yaml
opencost:
  exporter:
    defaultClusterId: kind-finops
  prometheus:
    internal:
      enabled: true
      namespaceName: monitoring
      serviceName: prometheus-kube-prometheus-prometheus
      port: 9090
  metrics:
    serviceMonitor:
      enabled: true                          # ⭐ Prometheus должен собирать метрики OpenCost
      additionalLabels: { release: prometheus }   # иначе kube-prometheus-stack не увидит ServiceMonitor
  ui:
    enabled: true
  customPricing:                             # раздел 4; для облака — не нужен
    enabled: true
    provider: custom
    costModel:
      description: "kind-стенд: цены своего железа"
      CPU: "0.0128"
      spotCPU: "0.0128"
      RAM: "0.0032"
      spotRAM: "0.0032"
      GPU: "0.95"
      storage: "0.0000685"
      zoneNetworkEgress: "0.0"
      regionNetworkEgress: "0.0"
      internetNetworkEgress: "0.0"
```text
```bash
helm repo add opencost-charts https://opencost.github.io/opencost-helm-chart
helm repo update
helm install opencost opencost-charts/opencost -n opencost --create-namespace -f values-opencost.yaml

kubectl -n opencost get pods                          # Running
kubectl -n opencost port-forward svc/opencost 9003:9003 9091:9090
# API: http://localhost:9003   UI: http://localhost:9091 (9090 локально занят Prometheus)

curl -s localhost:9003/metrics | grep -E '^node_(cpu|ram)_hourly_cost' | head
```text
Проверь в Prometheus, что таргет OpenCost `UP`, а `node_total_hourly_cost` возвращает ряды.
Через 10–20 минут появятся первые данные allocation.

> ⚠️ OpenCost сам отдаёт часть метрик в стиле kube-state-metrics. Если в кластере уже есть
> KSM (как в kube-prometheus-stack), следи за дублями; в чарте есть флаги
> `opencost.metrics.kubeStateMetrics.*` (например, `emitKsmV1Metrics`), чтобы их отключить.

---

## 4. Свои цены: on-prem и kind

В облаке OpenCost сам берёт публичный прайс по типу инстанса. На своём железе цену задаёшь ты.
**Единицы — за час:** CPU — $ за vCPU·час, RAM — $ за GiB·час, storage — $ за GiB·час
(поэтому в дефолтном `default.json` storage = 0.00005479452 — это $0,04 за ГБ·мес / 730).

Расчёт от полной стоимости сервера (TCO из [01_finops_intro.md](/finops/01-finops-intro), раздел 8):
```text
Сервер 32 vCPU / 128 GiB, полная стоимость $600/мес (амортизация + электричество + колокация + люди).
Делим 50/50 между CPU и RAM (можно по рыночному соотношению цен):

CPU:     $300 / (32 vCPU × 730 ч)  = $0,0128 за vCPU·час
RAM:     $300 / (128 GiB × 730 ч)  = $0,0032 за GiB·час
Storage: $0,05 за GiB·мес (СХД)    = 0,05 / 730 = $0,0000685 за GiB·час

Проверка: 32 × 0,0128 × 730 + 128 × 0,0032 × 730 = 299 + 299 ≈ $598/мес ✅
```text
| Ошибка | Последствие |
|--------|-------------|
| Ввести месячную цену как часовую | Всё дороже в 730 раз |
| Storage «за месяц» вместо «за час» | PV дороже в 730 раз |
| Не учесть людей и электричество | On-prem кажется бесплатным, showback занижен |
| Забыть про запас на отказ (N+1) | Реальная стоимость ядра выше расчётной |

Для точного прайса по типам нод (разные серверы разной цены) есть CSV-прайс
(`EndpointID`, `InstanceType`, `MarketPriceHourly`, `CPU`, `RAM`, …) — для учёбы хватает `costModel`.

---

## 5. Allocation API

```bash
# расходы по namespace за 7 дней одной суммой, с idle
curl -sG localhost:9003/allocation/compute \
  -d window=7d -d aggregate=namespace -d accumulate=true -d includeIdle=true | jq '.data[0] | keys'

# таблица: namespace, CPU $, RAM $, PV $, итого $, эффективность %
curl -sG localhost:9003/allocation/compute \
  -d window=7d -d aggregate=namespace -d accumulate=true -d includeIdle=true \
| jq -r '.data[0] | to_entries[]
    | [.key, (.value.cpuCost*100|round/100), (.value.ramCost*100|round/100),
       (.value.pvCost*100|round/100), (.value.totalCost*100|round/100),
       ((.value.totalEfficiency // 0)*100|round)] | @tsv' \
| sort -t$'\t' -k5 -nr | column -t -s$'\t'

# по командам (лейбл team на подах), idle распределён по нодам
curl -sG localhost:9003/allocation \
  -d window=lastweek -d aggregate=label:team -d accumulate=true \
  -d shareIdle=true -d idleByNode=true | jq '.data[0] | map_values(.totalCost)'

# по контроллерам (Deployment/StatefulSet) внутри namespace
curl -sG localhost:9003/allocation/compute -d window=1d -d aggregate=controller \
  -d accumulate=true | jq '.data[0] | map_values({cpu: .cpuCost, ram: .ramCost, eff: .totalEfficiency})'
```text
| Параметр | Значения | Смысл |
|----------|----------|-------|
| `window` | `1d`, `7d`, `today`, `yesterday`, `lastweek`, `lastmonth`, пара RFC3339 | Период |
| `aggregate` | `namespace`, `controller`, `pod`, `label:team`, `namespace,label:app` | Группировка |
| `step` | `1d` | Разбить период на куски (тренд по дням) |
| `accumulate` | `true` | Одна сумма за весь период |
| `includeIdle` | `true` | Показать `__idle__` отдельной строкой |
| `shareIdle` | `true` | Распределить idle пропорционально между аллокациями |
| `idleByNode` | `true` | Считать idle по каждой ноде, а не по кластеру |

Служебные строки ответа: `__idle__` — idle; `__unallocated__` — поды **без** лейбла, по которому
агрегируешь (при `label:team`). Большой `__unallocated__` = плохое покрытие лейблами (тема 01).

---

## 6. Idle и общие расходы

```text
 стоимость нод кластера (100%)
 ├── распределено по namespace команд          60%   ← прямые расходы команд
 ├── инфраструктурные namespace               15%   ← kube-system, monitoring, ingress, opencost
 └── __idle__                                 25%   ← никем не запрошено
```text
| Что | Варианты | Рекомендация |
|-----|----------|--------------|
| **Idle** | Показать отдельно / `shareIdle` пропорционально / `idleByNode` | Для showback — отдельно (это задача платформы: consolidation), для chargeback — распределять |
| **Инфраструктурные namespace** | Отдельная строка «платформа» / пропорционально прямым / по драйверу | Пропорционально прямым или по драйверу (тема 01, раздел 6) |

OpenCost API распределяет idle; общие namespace распределяешь сам в отчёте (или Kubecost:
параметры `shareNamespaces`, `shareSplit`). Пример на Python-подобном псевдокоде:
```text
shared  = cost[kube-system] + cost[monitoring] + cost[ingress-nginx] + cost[opencost]
direct  = {ns: cost[ns] for ns in team_namespaces}
итог[ns] = direct[ns] + shared × direct[ns] / sum(direct)
```text
---

## 7. UI и kubectl cost

**UI** (`localhost:9091`): расходы за период по namespace/controller/pod, графики по дням,
эффективность. Удобно для первого взгляда и демонстрации команде.

**`kubectl cost`** — плагин (изначально от Kubecost), умеет ходить в OpenCost:
```bash
kubectl krew install cost

OC="--service-port 9003 --service-name opencost --kubecost-namespace opencost --allocation-path /allocation/compute"
kubectl cost $OC namespace --window 7d --show-cpu --show-memory --show-pv --show-efficiency=true
kubectl cost $OC namespace --window 2h --show-efficiency=true    # ⭐ прогноз на месяц по последним 2 часам
kubectl cost $OC deployment --window 1d -n demo
kubectl cost $OC label --historical -l team --window 7d
```text
Без `--historical` плагин показывает **прогноз месячной стоимости** по выбранному окну,
с `--historical` — фактическую стоимость за окно.

---

## 8. Стоимость в Grafana

OpenCost отдаёт метрики, которые собирает Prometheus:

| Метрика | Смысл |
|---------|-------|
| `node_cpu_hourly_cost`, `node_ram_hourly_cost`, `node_gpu_hourly_cost` | Цена vCPU/GiB/GPU ноды в час |
| `node_total_hourly_cost` | Полная цена ноды в час |
| `pv_hourly_cost` | Цена PV за GiB в час |
| `container_cpu_allocation`, `container_memory_allocation_bytes`, `container_gpu_allocation` | Распределённые ресурсы: `max(request, usage)` |
| `pod_pvc_allocation` | Распределённые байты PVC |
| `kubecost_load_balancer_cost` | Цена балансировщиков |

```promql
# Прогноз месячной стоимости нод кластера
sum(node_total_hourly_cost) * 730

# Стоимость CPU + RAM по namespace, $ в час
sum by (namespace) (
    container_cpu_allocation * on (node) group_left() node_cpu_hourly_cost
  + container_memory_allocation_bytes / 1024^3 * on (node) group_left() node_ram_hourly_cost
)

# Стоимость PV по namespace, $ в час
sum by (namespace) (pod_pvc_allocation * on (persistentvolume) group_left() pv_hourly_cost / 1024^3)
```text
Recording rule, чтобы дашборды и алерты не джойнили сырые ряды каждый раз:
```yaml
# в PrometheusRule (как в теме 02)
- record: namespace:opencost_hourly_cost:sum
  expr: |
    sum by (namespace) (
        avg by (namespace, pod, container, node) (container_cpu_allocation)
          * on (node) group_left() avg by (node) (node_cpu_hourly_cost)
      + avg by (namespace, pod, container, node) (container_memory_allocation_bytes) / 1024^3
          * on (node) group_left() avg by (node) (node_ram_hourly_cost)
    )
```text
| Панель | Запрос |
|--------|--------|
| Месячный прогноз кластера | `sum(node_total_hourly_cost) * 730` (Stat, единицы `currencyUSD`) |
| Топ namespace, $/мес | `topk(10, namespace:opencost_hourly_cost:sum * 730)` (Bar gauge) |
| Доля idle | `1 - sum(namespace:opencost_hourly_cost:sum) / sum(node_total_hourly_cost)` |
| Тренд по дням | `sum by (namespace) (namespace:opencost_hourly_cost:sum)` (Time series, 30 дней) |
| Эффективность (из темы 02) | usage / requests по namespace |

---

## 9. Алерты на всплески стоимости

```yaml
- alert: NamespaceCostSpike
  expr: |
    namespace:opencost_hourly_cost:sum
      > 1.5 * avg_over_time(namespace:opencost_hourly_cost:sum[7d] offset 1d)
    and namespace:opencost_hourly_cost:sum > 0.5          # игнорировать копеечные namespace
  for: 2h
  labels: { severity: warning, team: finops }
  annotations:
    summary: "Расходы &#123;&#123; $labels.namespace &#125;&#125; выросли больше чем на 50% к средним за неделю"

- alert: ClusterIdleTooHigh
  expr: 1 - sum(namespace:opencost_hourly_cost:sum) / sum(node_total_hourly_cost) > 0.4
  for: 6h
  labels: { severity: warning, team: platform }
  annotations:
    summary: "Больше 40% стоимости нод никем не запрошено — проверь consolidation/autoscaler"

- alert: ClusterMonthlyForecastOverBudget
  expr: sum(node_total_hourly_cost) * 730 > 3000
  for: 1h
  labels: { severity: warning, team: finops }
```text
Маршрутизация — через Alertmanager по лейблу `team` в канал владельца
([../Left/02_Monitoring/05_alertmanager.md](/monitoring/05-alertmanager)).

---

## 10. Showback-отчёт по командам

Раз в месяц (часть cost review, тема 05):
```bash
curl -sG localhost:9003/allocation/compute -d window=lastmonth -d aggregate=label:team \
  -d accumulate=true -d shareIdle=true \
| jq -r '.data[0] | to_entries[] | [.key, .value.cpuCost, .value.ramCost, .value.pvCost,
         .value.totalCost, .value.totalEfficiency] | @csv' > showback-2026-09.csv
```text
```text
SHOWBACK — кластер prod-kz, сентябрь 2026 (цены — custom pricing, $)
┌───────────────┬───────┬───────┬──────┬──────────┬───────────┬────────┬─────────┬────────────────────┐
│ команда       │ CPU   │ RAM   │ PV   │ платформа│ итого     │ Δ к авг│ эффект. │ топ-действие       │
├───────────────┼───────┼───────┼──────┼──────────┼───────────┼────────┼─────────┼────────────────────┤
│ team-shop     │ 1 240 │ 410   │ 120  │ 350      │ 2 120     │ +8%    │ 34%     │ rightsizing api    │
│ team-data     │ 2 100 │ 980   │ 640  │ 740      │ 4 460     │ +31% ⚠️│ 22%     │ батчи на spot      │
│ __unallocated__│ 310  │ 90    │ 0    │ —        │ 400       │        │         │ повесить лейбл team│
└───────────────┴───────┴───────┴──────┴──────────┴───────────┴────────┴─────────┴────────────────────┘
```text
Хороший отчёт — это не таблица, а **действия**: у каждой строки владелец и следующий шаг.

---

## 11. Границы точности

| Что OpenCost не знает сам | Следствие | Как закрыть |
|---------------------------|-----------|-------------|
| Скидки: RI, savings plans, spot, договорные | Стоимость выше счёта | Сверка со счётом (Kubecost, свои отчёты); OpenCost `/cloudCost` с выгрузкой счёта |
| Расходы вне кластера (RDS, S3, managed-сервисы) | Картина неполная | `/cloudCost` по billing export облака, теги (тема 05) |
| Сетевой трафик по подам | `networkCost = 0` | Отдельная настройка сбора сетевых метрик |
| On-prem цены | Только твоя модель | Честный TCO (раздел 4) |
| Историю до установки | Данных нет | Ставить заранее; retention Prometheus ≥ периода отчёта |

> ⚠️ OpenCost — инструмент распределения, а не бухгалтерия. Для showback ±10% — нормально;
> для chargeback итог сверяют со счётом и распределяют разницу пропорционально.

---

## 12. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| ServiceMonitor без лейбла `release` | Prometheus не собирает OpenCost — в UI нули | `additionalLabels: {release: prometheus}` или открытые селекторы |
| Неверное имя сервиса Prometheus | OpenCost не стартует/пустые данные | `kubectl -n monitoring get svc`, поправить `serviceName`/`port` |
| Цены «в месяц» в `costModel` | Всё дороже в 730 раз | Цены за час |
| Сравнивать OpenCost со счётом «в лоб» | Не совпадает на размер скидок | Сверка и распределение разницы |
| Не показывать idle | Сумма команд < стоимости кластера, «куда делись деньги?» | `includeIdle=true`, решить, как распределять |
| Лейбл team только на namespace | `label:team` → всё в `__unallocated__` | Лейблы на шаблоне подов (или агрегировать по namespace) |
| Retention 10 дней | Месячный отчёт не собрать | Retention ≥ 35 дней или выгрузка отчёта ежедневно/еженедельно |
| Алерт на абсолютный порог по каждому namespace | Шум | Относительно недели + минимальная сумма |
| Отчёт без действий | «Посмотрели и забыли» | У каждой строки — владелец и следующий шаг |

---

## 💼 Как это в DevOps

- OpenCost — дешёвый способ перейти от «кластер стоит $X» к «team-data — 45% кластера,
  эффективность 22%». Именно такая таблица запускает разговор о rightsizing.
- Девопс настраивает сбор, цены и дашборд; FinOps/финансы задают правила распределения;
  команды получают showback и сами решают, что оптимизировать.
- В on-prem и небольших облаках (российские, казахстанские провайдеры) custom pricing —
  единственный способ показать стоимость: считаешь цену ядра и гигабайта из TCO.
- Метрики стоимости живут рядом с остальными в Prometheus: те же алерты, те же дашборды,
  та же маршрутизация по командам.
- Kubecost/аналоги появляются, когда кластеров много и нужна сверка со счётом и отчёты
  для финансов без ручной работы.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Поставить OpenCost | `helm install opencost opencost-charts/opencost -n opencost -f values.yaml` |
| Указать Prometheus | `opencost.prometheus.internal.{namespaceName,serviceName,port}` |
| Чтобы Prometheus собирал OpenCost | `opencost.metrics.serviceMonitor.enabled: true` (+ лейбл `release`) |
| Свои цены | `opencost.customPricing.enabled: true`, `costModel` — $ за vCPU·ч, GiB·ч |
| API / UI | порт 9003 / порт 9090 сервиса `opencost` |
| По namespace за неделю | `/allocation/compute?window=7d&aggregate=namespace&accumulate=true` |
| По командам | `aggregate=label:team` |
| Показать idle | `includeIdle=true` |
| Распределить idle | `shareIdle=true` (+ `idleByNode=true`) |
| Из терминала | `kubectl cost … namespace --window 7d` |
| Месячный прогноз кластера | `sum(node_total_hourly_cost) * 730` |
| Стоимость namespace | `container_*_allocation × node_*_hourly_cost` через `on (node) group_left()` |
| Алерт на всплеск | recording rule + сравнение с `avg_over_time(...[7d] offset 1d)` |

---

## 🧠 Что запомнить

1. OpenCost — открытый CNCF-проект (Incubating), Kubecost — коммерческий продукт IBM на той же модели.
2. Allocation = `max(request, usage)` × цена ресурса × время; платишь за то, что занял.
3. Idle — оплаченная и никем не запрошенная мощность; её показывают или распределяют осознанно.
4. Prometheus обязан собирать метрики самого OpenCost — без ServiceMonitor данных не будет.
5. Custom pricing — цены **за час**: vCPU·ч, GiB·ч, GiB·ч для storage; считаются из TCO.
6. API: `window`, `aggregate`, `accumulate`, `includeIdle`, `shareIdle`; `__unallocated__` = нет лейбла.
7. Метрики `*_hourly_cost` и `*_allocation` → recording rule → дашборды и алерты в Grafana.
8. Алерт на стоимость — относительный (к средней за неделю) с минимальным порогом.
9. OpenCost не знает скидок и внешних расходов — для chargeback нужна сверка со счётом.
10. ⭐ Showback ценен действиями: у каждой строки — владелец и следующий шаг.

➡️ Дальше: [05_infracost_iac.md](/finops/05-infracost-iac) · Задачи: 04_kubecost_opencost_tasks.md


---

### Блок A. Теория


**A1.** Каков статус OpenCost и Kubecost в 2026 году? Что бесплатно, что платно?

<details><summary>Ответ</summary>

OpenCost — открытый проект CNCF (Incubating с октября 2024), Apache 2.0, бесплатен
полностью; мейнтейнеры — IBM Kubecost, Randoli, сообщество; в 2025 появились режим без
Prometheus, плагины и MCP-сервер. Kubecost куплен IBM в сентябре 2024; Kubecost 3.0
(сентябрь 2025) — свой агент и ClickHouse; есть free tier (в 3.0 ограничен объёмом расходов),
платно — федерация, сверка со счётом в полном объёме, SSO, поддержка, расширенные функции.

</details>

**A2.** ⭐ По какой формуле OpenCost распределяет стоимость на контейнер? Почему
`max(request, usage)`, а не просто usage?

<details><summary>Ответ</summary>

`max(request, usage)` по CPU и RAM × цена за единицу·час × время + GPU + PV + сеть/LB.
Request — это занятая мощность: её никто другой не может использовать, и под неё куплены ноды.
Если usage выше request (без лимита), под реально потребил больше — считается фактическое.

</details>

**A3.** Что такое idle? Какие есть способы с ним обращаться?

<details><summary>Ответ</summary>

Оплаченная мощность нод, которую никто не запросил. Варианты: показывать отдельной
строкой (задача платформы — consolidation), распределять пропорционально (`shareIdle`),
распределять по нодам (`idleByNode`).

</details>

**A4.** Почему OpenCost без ServiceMonitor (или scrape-конфига) показывает нули?

<details><summary>Ответ</summary>

OpenCost вычисляет allocation запросами к Prometheus, в том числе по своим метрикам
цен (`node_*_hourly_cost`, `pv_hourly_cost`). Если Prometheus их не собирает — цен нет,
стоимость нулевая.

</details>

**A5.** В каких единицах задаются custom-цены? Почему storage в `default.json` — такое маленькое число?

<details><summary>Ответ</summary>

За час: CPU — $ за vCPU·час, RAM — $ за GiB·час, storage — $ за GiB·час.

</details>

**A6.** Что делают параметры API `window`, `aggregate`, `accumulate`, `includeIdle`, `shareIdle`, `idleByNode`?

<details><summary>Ответ</summary>

`window` — период; `aggregate` — группировка (namespace, controller, label:…);
`accumulate=true` — одна сумма за период; `includeIdle` — показать `__idle__`; `shareIdle` —
распределить idle между аллокациями; `idleByNode` — считать idle по каждой ноде.

</details>

**A7.** Что означают строки `__idle__` и `__unallocated__`?

<details><summary>Ответ</summary>

`__idle__` — idle-стоимость (никем не запрошенная мощность). `__unallocated__` —
аллокации без лейбла, по которому агрегируешь (например, поды без `team`).

</details>

**A8.** Как распределить расходы инфраструктурных namespace (kube-system, monitoring, ingress)?

<details><summary>Ответ</summary>

Отдельной строкой «платформа», пропорционально прямым расходам, поровну, фиксированно
или по драйверу (time series, запросы). В OpenCost — расчётом в отчёте; в Kubecost есть
`shareNamespaces`.

</details>

**A9.** Чем вывод `kubectl cost` без `--historical` отличается от вывода с ним?

<details><summary>Ответ</summary>

Без `--historical` — прогноз месячной стоимости по скорости расходов в окне
(окно 2 часа экстраполируется на месяц); с `--historical` — фактическая стоимость за окно.

</details>

**A10.** Какие метрики экспортирует OpenCost? Как посчитать стоимость namespace PromQL-ом?

<details><summary>Ответ</summary>

`node_cpu_hourly_cost`, `node_ram_hourly_cost`, `node_gpu_hourly_cost`,
`node_total_hourly_cost`, `pv_hourly_cost`, `container_cpu_allocation`,
`container_memory_allocation_bytes`, `container_gpu_allocation`, `pod_pvc_allocation`,
`kubecost_load_balancer_cost`. Стоимость namespace:
`sum by (namespace) (container_cpu_allocation * on (node) group_left() node_cpu_hourly_cost
+ container_memory_allocation_bytes / 1024^3 * on (node) group_left() node_ram_hourly_cost)`.

</details>

**A11.** Почему алерт на стоимость лучше делать относительным?

<details><summary>Ответ</summary>

У namespace разный масштаб: $1/ч для одного — норма, для другого — всплеск в 10 раз.
Сравнение со своей средней за неделю ловит изменения поведения; минимальный порог отсекает
копеечный шум.

</details>

**A12.** Чего OpenCost не знает и где его данные расходятся со счётом?

<details><summary>Ответ</summary>

Скидки (RI, SP, spot, договорные), расходы вне кластера (RDS, S3, NAT, трафик,
плата за control plane), сетевой трафик по подам без доп. настройки, историю до установки.
On-prem — только твоя модель цен.

</details>

**A13.** Когда стоит брать Kubecost или аналог вместо OpenCost?

<details><summary>Ответ</summary>

Много кластеров и нужна единая картина; финансам нужна сверка со счётом и chargeback
с учётом скидок; нужны готовые рекомендации, бюджеты, SSO и поддержка; нет времени
собирать это вокруг OpenCost.

</details>

**A14.** Что делает showback-отчёт полезным, кроме самой таблицы?

<details><summary>Ответ</summary>

Действия: у каждой строки владелец, тренд к прошлому месяцу, эффективность
и конкретный следующий шаг; отдельная строка `__unallocated__` как задача на лейблы.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  # values-opencost.yaml
```text
<details><summary>Ответ</summary>

⚠️ Prometheus не собирает метрики OpenCost — нет цен, стоимость 0. Включить
ServiceMonitor (с лейблом `release: prometheus`, если селекторы kube-prometheus-stack закрыты).

</details>

```text:no-line-numbers
     opencost:
```text
```text:no-line-numbers
       metrics: { serviceMonitor: { enabled: false } }
```text
```text:no-line-numbers
     # «UI через час показывает $0 по всем namespace»
```text
```text:no-line-numbers
B2.  customPricing:
```text
<details><summary>Ответ</summary>

⚠️ Цены должны быть за час: $23,36 за vCPU·мес = 23,36 / 730 ≈ $0,032 за vCPU·час.
Сейчас всё дороже в 730 раз (storage тоже).

</details>

```text:no-line-numbers
       costModel: { CPU: "23.36", RAM: "3.10", storage: "0.08" }   # «цены из прайса за месяц»
```text
```text:no-line-numbers
B3.  # лейбл team висит только на объектах Namespace
```text
<details><summary>Ответ</summary>

⚠️ OpenCost агрегирует по лейблам подов — всё уйдёт в `__unallocated__`. Нужны лейблы
в шаблонах подов (или агрегировать по namespace и мапить namespace → команда в отчёте).

</details>

```text:no-line-numbers
     curl -sG localhost:9003/allocation/compute -d window=7d -d aggregate=label:team -d accumulate=true
```text
```text:no-line-numbers
B4.  # «OpenCost насчитал за месяц $8 400, а счёт AWS за ноды — $6 100. OpenCost сломан»
```text
<details><summary>Ответ</summary>

⚠️ OpenCost считает по публичным ценам on-demand, а счёт уже со скидками (savings plans,
spot). Расхождение ожидаемо; для chargeback сверяют и распределяют разницу пропорционально.

</details>

```text:no-line-numbers
B5.  - alert: NamespaceExpensive
```text
<details><summary>Ответ</summary>

⚠️ Абсолютный порог одинаков для всех namespace — дорогие горят всегда, дешёвые никогда
не сработают даже при росте в 10 раз. Нужно сравнение со своей нормой и минимальная сумма.

</details>

```text:no-line-numbers
       expr: namespace:opencost_hourly_cost:sum > 1
```text
```text:no-line-numbers
B6.  # showback по командам без idle: сумма команд = 60% стоимости кластера
```text
<details><summary>Ответ</summary>

⚠️ Не показан idle (и, возможно, инфраструктурные namespace). `includeIdle=true`
и решение, как распределять; idle — отдельная задача платформы.

</details>

```text:no-line-numbers
     # финансы: «а где остальные 40%?»
```text
```text:no-line-numbers
B7.  # Prometheus retention 10d; 3-го числа строим отчёт window=lastmonth
```text
<details><summary>Ответ</summary>

⚠️ Данных за первые ~20 дней месяца уже нет — отчёт неполный. Retention ≥ 35 дней или
ежедневная/еженедельная выгрузка отчётов (CSV в S3), либо долговременное хранилище.

</details>

```text:no-line-numbers
B8.  sum by (namespace) (container_cpu_allocation * node_cpu_hourly_cost)
```text
<details><summary>Ответ</summary>

⚠️ У рядов разные наборы лейблов — без `on (node) group_left()` сопоставление не найдёт
пар, результат пустой. Нужно `container_cpu_allocation * on (node) group_left() node_cpu_hourly_cost`.

</details>

```text:no-line-numbers
B9.  # showback для всех команд с shareIdle=true; idle в кластере — 45%, никто об этом не знает
```text
<details><summary>Ответ</summary>

⚠️ Idle «растворился» в расходах команд: команды видят рост, а 45% простоя — проблема
платформы (consolidation, размер нод), которую никто не чинит. Показывать idle отдельно
хотя бы во внутреннем отчёте платформы.

</details>

```text:no-line-numbers
B10.  kubectl -n monitoring port-forward svc/prometheus-kube-prometheus-prometheus 9090 &
```text
<details><summary>Ответ</summary>

⚠️ Локальный порт 9090 уже занят port-forward Prometheus — второй не поднимется.
Проброс UI на другой локальный порт: `9091:9090`.

</details>

```text:no-line-numbers
     kubectl -n opencost port-forward svc/opencost 9003 9090
```text
---

### Блок C. Практика


### C1. 🔑 OpenCost на стенде
**1.** Установи OpenCost с `values-opencost.yaml` из конспекта.

<details><summary>Ответ</summary>

В kind custom pricing применяется ко всем нодам; прогноз = `sum(node_total_hourly_cost) * 730`.
Ручная проверка: (vCPU всех нод × 0,0128 + GiB × 0,0032) × 730. Небольшое расхождение —
из-за округлений и того, что RAM ноды в метриках — фактическая ёмкость.

</details>

**2.** Проверь: под `Running`, таргет OpenCost `UP` в Prometheus, `node_total_hourly_cost` есть.

<details><summary>Ответ</summary>

```text
CPU:     0,6 × $1 400 = $840;  $840 / (96 vCPU × 730 ч) = 840 / 70 080 ≈ $0,0120 за vCPU·ч
RAM:     0,4 × $1 400 = $560;  $560 / (384 GiB × 730 ч) = 560 / 280 320 ≈ $0,0020 за GiB·ч
Storage: $0,08 / 730 ≈ $0,00011 за GiB·ч
Проверка: 96 × 0,012 × 730 = $840,96; 384 × 0,002 × 730 = $560,64; итого ≈ $1 401,6 ✅
```text
</details>

**3.** Посчитай в Prometheus месячный прогноз стоимости кластера и сверь с ручным расчётом:
   число vCPU и GiB нод kind × твои цены × 730.

<details><summary>Ответ</summary>

```text
Кластер: 120 + 300 + 60 + 40 + 70 + 20 + 10 + 180 = $800
Общие (инфраструктура): 40 + 70 + 20 + 10 = $140;  idle: $180;  прямые: 120 + 300 + 60 = $480
Доли прямых: shop 25%, data 62,5%, dev 12,5%

команда  прямые  + общие (140)   + idle (180)   = итого
shop     120     + 35            + 45           = 200
data     300     + 87,5          + 112,5        = 500
dev       60     + 17,5          + 22,5         = 100
сумма    480     + 140           + 180          = 800 ✅
```text
```bash
curl -sG localhost:9003/allocation/compute -d window=30d -d aggregate=namespace -d accumulate=true \
| jq -r '.data[0] | to_entries | sort_by(-.value.totalCost)[] | "\(.key)\t\(.value.totalCost)"'
```text
</details>

### C2. 🔑 Свои цены (расчёт)
Два сервера по 48 vCPU / 192 GiB, полная стоимость обоих — $1 400/мес. Раздели 60% на CPU
и 40% на RAM. Хранилище — $0,08 за ГБ·мес. Посчитай значения `CPU`, `RAM`, `storage`
для `costModel` и проверь обратным расчётом.

### C3. 🔑 Showback с общими расходами
API за месяц вернул (`$`): `shop` 120, `data` 300, `dev` 60, `kube-system` 40, `monitoring` 70,
`ingress-nginx` 20, `opencost` 10, `__idle__` 180.
**1.** Посчитай стоимость кластера, общие расходы и прямые расходы команд.

<details><summary>Ответ</summary>

В kind custom pricing применяется ко всем нодам; прогноз = `sum(node_total_hourly_cost) * 730`.
Ручная проверка: (vCPU всех нод × 0,0128 + GiB × 0,0032) × 730. Небольшое расхождение —
из-за округлений и того, что RAM ноды в метриках — фактическая ёмкость.

</details>

**2.** Распредели общие расходы и idle пропорционально прямым. Сделай итоговую таблицу.

<details><summary>Ответ</summary>

```text
CPU:     0,6 × $1 400 = $840;  $840 / (96 vCPU × 730 ч) = 840 / 70 080 ≈ $0,0120 за vCPU·ч
RAM:     0,4 × $1 400 = $560;  $560 / (384 GiB × 730 ч) = 560 / 280 320 ≈ $0,0020 за GiB·ч
Storage: $0,08 / 730 ≈ $0,00011 за GiB·ч
Проверка: 96 × 0,012 × 730 = $840,96; 384 × 0,002 × 730 = $560,64; итого ≈ $1 401,6 ✅
```text
</details>

**3.** Напиши `jq`, который из ответа `/allocation/compute` печатает `namespace, totalCost`,
   отсортированные по убыванию.

<details><summary>Ответ</summary>

```text
Кластер: 120 + 300 + 60 + 40 + 70 + 20 + 10 + 180 = $800
Общие (инфраструктура): 40 + 70 + 20 + 10 = $140;  idle: $180;  прямые: 120 + 300 + 60 = $480
Доли прямых: shop 25%, data 62,5%, dev 12,5%

команда  прямые  + общие (140)   + idle (180)   = итого
shop     120     + 35            + 45           = 200
data     300     + 87,5          + 112,5        = 500
dev       60     + 17,5          + 22,5         = 100
сумма    480     + 140           + 180          = 800 ✅
```text
```bash
curl -sG localhost:9003/allocation/compute -d window=30d -d aggregate=namespace -d accumulate=true \
| jq -r '.data[0] | to_entries | sort_by(-.value.totalCost)[] | "\(.key)\t\(.value.totalCost)"'
```text
</details>

### C4. kubectl cost
Поставь плагин через krew, выведи стоимость namespace за 1 час с эффективностью —
в режиме прогноза и в режиме `--historical`. Объясни, почему цифры отличаются в сотни раз.

### C5. Дашборд стоимости
Добавь recording rule `namespace:opencost_hourly_cost:sum` и собери 4 панели: месячный
прогноз кластера, топ namespace в $/мес, доля idle, тренд по namespace. Экспортируй JSON.

### C6. 🔑 Алерт на всплеск
**1.** Создай `PrometheusRule` с `NamespaceCostSpike`, но для стенда: окно `[1h] offset 10m`, `for: 5m`,
   минимальная сумма `> 0.001`.

<details><summary>Ответ</summary>

В kind custom pricing применяется ко всем нодам; прогноз = `sum(node_total_hourly_cost) * 730`.
Ручная проверка: (vCPU всех нод × 0,0128 + GiB × 0,0032) × 730. Небольшое расхождение —
из-за округлений и того, что RAM ноды в метриках — фактическая ёмкость.

</details>

**2.** Увеличь реплики одного Deployment в `demo` в 5 раз.

<details><summary>Ответ</summary>

```text
CPU:     0,6 × $1 400 = $840;  $840 / (96 vCPU × 730 ч) = 840 / 70 080 ≈ $0,0120 за vCPU·ч
RAM:     0,4 × $1 400 = $560;  $560 / (384 GiB × 730 ч) = 560 / 280 320 ≈ $0,0020 за GiB·ч
Storage: $0,08 / 730 ≈ $0,00011 за GiB·ч
Проверка: 96 × 0,012 × 730 = $840,96; 384 × 0,002 × 730 = $560,64; итого ≈ $1 401,6 ✅
```text
</details>

**3.** Дождись `pending` → `firing` на `/alerts`. Верни реплики и проверь, что алерт погас.

<details><summary>Ответ</summary>

```text
Кластер: 120 + 300 + 60 + 40 + 70 + 20 + 10 + 180 = $800
Общие (инфраструктура): 40 + 70 + 20 + 10 = $140;  idle: $180;  прямые: 120 + 300 + 60 = $480
Доли прямых: shop 25%, data 62,5%, dev 12,5%

команда  прямые  + общие (140)   + idle (180)   = итого
shop     120     + 35            + 45           = 200
data     300     + 87,5          + 112,5        = 500
dev       60     + 17,5          + 22,5         = 100
сумма    480     + 140           + 180          = 800 ✅
```text
```bash
curl -sG localhost:9003/allocation/compute -d window=30d -d aggregate=namespace -d accumulate=true \
| jq -r '.data[0] | to_entries | sort_by(-.value.totalCost)[] | "\(.key)\t\(.value.totalCost)"'
```text
</details>

### C7. Эффективность в деньгах (расчёт)
Namespace стоит $400/мес при `totalEfficiency` = 0,2. Сколько он будет стоить, если после
rightsizing эффективность станет 0,6 (потребление то же)? Сколько сэкономится?

### C8. Выбор инструмента
Компания: 3 кластера EKS, облако $40 000/мес, финансы хотят chargeback с учётом savings plans,
одна платформенная команда из двух человек. Напиши короткое обоснование: OpenCost или Kubecost/
коммерческий аналог — и что понадобится в каждом случае.

---

### Блок D. Инциденты


**D1.** OpenCost работает неделю, а UI показывает данные только за последние 2 дня.

<details><summary>Ответ</summary>

Prometheus хранит данные на `emptyDir` и перезапускался (или retention короткий) —
история потеряна. Включить PVC для Prometheus (`storageSpec`) и нужный retention; для OpenCost
тоже включить персистентность, если используются его локальные данные.

</details>

**D2.** Расходы namespace `data` за ночь выросли в 4 раза, деплоев не было.

<details><summary>Ответ</summary>

Запросить API с `step=1h` и `aggregate=controller`/`pod` в namespace: что выросло —
CPU/RAM (HPA ушёл в максимум из-за метрики, CronJob зациклился), PV (кто-то расширил PVC),
LB (новый Service type=LoadBalancer), цена нод (поды переехали на дорогие или on-demand ноды).
Сверить с событиями и HPA.

</details>

**D3.** В отчёте по `label:team` строка `__unallocated__` — 35% стоимости.

<details><summary>Ответ</summary>

Поды без лейбла `team`. Найти крупнейшие: `aggregate=namespace,label:team` (где team пуст),
добавить лейблы в чарты, включить Kyverno-политику на лейблы (тема 01), временно маппить
namespace → команда в отчёте.

</details>

**D4.** После обновления kube-prometheus-stack OpenCost в логах пишет ошибки запросов
к Prometheus, данные перестали обновляться.

<details><summary>Ответ</summary>

Изменилось имя/порт сервиса Prometheus (или namespace) — OpenCost ходит по старому адресу.
Поправить `opencost.prometheus.internal.*` и сделать `helm upgrade`; проверить `kubectl -n opencost logs`.

</details>

**D5.** Команда возмущена: «нам насчитали 8 ядер, а мы используем одно».

<details><summary>Ответ</summary>

Модель `max(request, usage)`: команда заняла 8 ядер requests, под них куплены ноды —
никто другой их использовать не может. Решение — rightsizing (тема 02): request по p95 → стоимость
упадёт; показать эффективность 12% и сколько сэкономит правка.

</details>

**D6.** После «оптимизации» `metricRelabelings` в Prometheus пропали все панели стоимости.

<details><summary>Ответ</summary>

Relabeling выкинул метрики OpenCost (`node_*_hourly_cost`, `container_*_allocation`)
или лейблы `node`/`namespace`, по которым идёт джойн. Вернуть их в keep-список и проверить
`count by (__name__) ({job=~".*opencost.*"})`.

</details>

**D7.** Стоимость prod-кластера по OpenCost на 30% **ниже**, чем строки счёта AWS, относящиеся к кластеру.

<details><summary>Ответ</summary>

OpenCost видит только ноды и PV внутри кластера. Не видит: плату за control plane EKS,
NAT gateway, трафик между AZ и наружу (без настройки), балансировщики вне k8s, EBS-снапшоты,
CloudWatch, RDS/S3. Дополнить `/cloudCost` по billing export или теговыми отчётами облака.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как узнать, сколько стоит каждый namespace или команда в Kubernetes?

<details><summary>Ответ</summary>

Поставить OpenCost (или Kubecost): allocation по namespace, контроллерам и лейблам
   `team`/`service`; цены — облачные или custom; результат — API/UI/Grafana и showback.

</details>

**2.** Что такое OpenCost и чем он отличается от Kubecost?

<details><summary>Ответ</summary>

OpenCost — открытый движок и спецификация (CNCF Incubating); Kubecost — коммерческий
   продукт IBM на его основе: федерация, сверка со счётом, рекомендации, SSO, free tier.

</details>

**3.** Как OpenCost считает стоимость пода?

<details><summary>Ответ</summary>

`max(request, usage)` по CPU и RAM × цена за единицу·час (из прайса ноды или custom) × время,
   плюс GPU, PV по PVC, сеть и LB.

</details>

**4.** Что такое idle cost и что с ним делать?

<details><summary>Ответ</summary>

Мощность нод, которую никто не запросил. Показываю отдельно как задачу платформы
   (consolidation, размер нод) и решаю, распределять ли её в chargeback.

</details>

**5.** Как распределить расходы на мониторинг и ingress между командами?

<details><summary>Ответ</summary>

Пропорционально прямым расходам или по драйверу потребления (серии метрик, объём логов,
   запросы через ingress); правило согласовать и зафиксировать.

</details>

**6.** Как посчитать стоимость в on-prem кластере?

<details><summary>Ответ</summary>

TCO сервера (амортизация, электричество, колокация, люди, резерв) → цена vCPU·часа
   и GiB·часа → custom pricing в OpenCost.

</details>

**7.** Почему данные OpenCost не совпадают со счётом облака?

<details><summary>Ответ</summary>

OpenCost — публичные цены без скидок и только ресурсы кластера; счёт — со скидками
   и внешними расходами. Для chargeback — сверка.

</details>

**8.** Как настроить алерт на рост расходов?

<details><summary>Ответ</summary>

Recording rule стоимости namespace и алерт «выше средней за неделю на 50% и больше
   минимальной суммы», `for: 2h`, маршрут по `team`; плюс алерт на долю idle и прогноз против бюджета.

</details>

**9.** Что такое showback-отчёт и что в нём должно быть?

<details><summary>Ответ</summary>

Таблица расходов команд за месяц с трендом, эффективностью, долей общих расходов,
   `__unallocated__` и главное — владельцами и следующими шагами.

</details>

**10.** Как вывести стоимость в Grafana?

<details><summary>Ответ</summary>

Prometheus собирает метрики OpenCost; recording rule `namespace:opencost_hourly_cost:sum`;
    панели: прогноз кластера `sum(node_total_hourly_cost) * 730`, топ namespace, idle, тренд.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Объясняю статус OpenCost и Kubecost в 2026 и когда что выбирать
- [ ] ⭐ Объясняю модель `max(request, usage)` × цена × время и idle
- [ ] Поставил OpenCost рядом с kube-prometheus-stack, Prometheus собирает его метрики
- [ ] Считаю custom-цены из TCO в правильных единицах (за час)
- [ ] Достаю allocation через API по namespace, контроллерам и `label:team`
- [ ] Распределяю общие расходы и idle и собираю showback-таблицу
- [ ] Пользуюсь `kubectl cost` и понимаю разницу прогноза и `--historical`
- [ ] Вывел стоимость в Grafana через recording rule
- [ ] Настроил и спровоцировал алерт на всплеск стоимости
- [ ] Знаю границы точности OpenCost и зачем сверка со счётом
