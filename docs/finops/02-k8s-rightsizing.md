---
title: "02. Rightsizing в Kubernetes: requests, limits и реальное потребление"
description: "Блок → FinOps → тема 02. Опирается на"
---

# 02. Rightsizing в Kubernetes: requests, limits и реальное потребление

> Блок → FinOps → тема 02. Опирается на
> [../Kubernetes/09_probes_resources.md](/kubernetes/09-probes-resources) (requests/limits,
> QoS, LimitRange, ResourceQuota — базу не повторяем) и
> [../Left/02_Monitoring/03_promql.md](/monitoring/03-promql) (`rate`,
> `*_over_time`, subquery, recording rules).
>
> **После темы ты умеешь:** объяснить, почему requests — это деньги, измерить реальное
> потребление подов PromQL-ом за 7–14 дней (p95 CPU, пик памяти), посчитать эффективность
> requests по namespace, выбрать новые requests/limits с обоснованием, получить рекомендации
> VPA и Goldilocks, поставить guardrails и понимать, как bin packing превращает rightsizing
> в меньшее число нод.

---

## 🗺️ Карта темы

```text
 requests ──► scheduler раскладывает поды ──► ноды «заполнены» по requests
    │                                                │
    │ завышены в 3–5 раз (типично)                   ▼
    │                                     autoscaler докупает ноды ──► 💰 счёт
    ▼
 реальное потребление (PromQL): p95 CPU, max memory за 14 дней
    │
    ▼
 новые числа: CPU request ≈ p95 + запас · memory request = limit ≈ max + 20%
    │
    ├── VPA (updateMode: Off) / Goldilocks — вторая точка зрения
    ├── guardrails: LimitRange, ResourceQuota
    └── bin packing / consolidation ──► лишние ноды уходят ──► экономия становится реальной
```text
---

## 1. Почему requests — это деньги

```text
 нода 4 vCPU / 16 GiB (allocatable ≈ 3,8 vCPU / 14,5 GiB)
 ┌───────────────────────────────────────────────┐
 │ requested: 3,6 vCPU  ███████████████████████░ │ ← так ноду видит scheduler: «почти полна»
 │ used:      0,7 vCPU  ████░░░░░░░░░░░░░░░░░░░░ │ ← так её видит Linux
 └───────────────────────────────────────────────┘
 новый под с request 500m → не влезает → Pending → Cluster Autoscaler покупает ещё ноду
```text
Три числа, которые путают:

| Термин | Формула | Кто «виноват» | Чем лечится |
|--------|---------|---------------|-------------|
| **Request waste** (slack) | requests − usage | Команда, завысившая requests | Rightsizing (эта тема) |
| **Idle** | allocatable − requests | Платформа: ноды заполнены плохо | Autoscaler, consolidation, bin packing (тема 03) |
| **Эффективность requests** | usage / requests | — | Цель: CPU 50–70%, память 70–85% |

По отчёту CAST AI (данные за 2024 год, 2100+ организаций) средняя утилизация CPU
в кластерах — около **10%**, памяти — около **23%** от выделенного. Типичная картина: requests
«с запасом» скопированы из чужого чарта и не пересматривались.

Грубая оценка цены (иллюстративно): 1 vCPU request ≈ $30/мес, 1 GiB ≈ $4/мес.
```text
30 деплойментов × 3 реплики × лишние 500m CPU = 45 vCPU ≈ $1 350/мес — просто «на всякий случай»
```text
> ⚠️ Уменьшение requests само по себе денег не экономит. Экономия появляется, когда
> освободившееся место превращается в **меньшее число нод** — через Cluster Autoscaler
> или Karpenter consolidation (раздел 12 и тема 03).

---

## 2. Limits: throttling и OOM глубже

База — в [../Kubernetes/09_probes_resources.md](/kubernetes/09-probes-resources). Добавим механику.

**CPU limit = квота CFS.** В cgroup v2 это `cpu.max`: квота на период 100 мс.
```text
limits.cpu: 500m  → 50 мс CPU на каждые 100 мс
приложение с 4 активными потоками сжигает 50 мс за 12,5 мс реального времени
→ оставшиеся 87,5 мс периода потоки стоят («throttled»)
→ p99 латентности растёт, хотя средняя загрузка CPU «всего 30%»
```text
Поэтому throttling видно не по `rate(cpu_usage)`, а по отдельным метрикам (раздел 4).

**Memory limit = жёсткая граница.** Превысил — ядро убивает процесс (OOMKilled, код 137).
Считается `working set` — память без неактивного файлового кэша.

---

## 3. QoS и вытеснение: что меняется, когда режешь requests

| Механизм | Как выбирает жертву | FinOps-вывод |
|----------|--------------------|--------------|
| **Kubelet eviction** (нехватка памяти/диска на ноде) | 1) превышает ли под свои requests; 2) priority; 3) насколько превышает requests | Под, чьё потребление выше request, вылетает первым: requests ниже реального — риск |
| **OOM killer ядра** | `oom_score_adj`: Guaranteed −997, BestEffort 1000, Burstable — между, тем выше, чем меньше memory request | Маленький memory request при большом потреблении = первый кандидат на OOM |

```text
 правило rightsizing: CPU можно ставить «впритык» (сжимаемый ресурс — просто медленнее),
                      память — только с запасом над реальным пиком (несжимаемая — смерть пода)
```text
---

## 4. Измеряем реальное потребление PromQL-ом

Стенд: kube-prometheus-stack из [00_INDEX.md](/finops/) — он собирает cAdvisor (через kubelet)
и kube-state-metrics и уже содержит нужные recording rules.

### Метрики

| Метрика | Источник | Что это |
|---------|----------|---------|
| `container_cpu_usage_seconds_total` | cAdvisor | Counter секунд CPU; `rate()` = используемые ядра |
| `container_memory_working_set_bytes` | cAdvisor | Память, по которой считают OOM и eviction |
| `container_cpu_cfs_throttled_periods_total`, `container_cpu_cfs_periods_total` | cAdvisor | Доля периодов с throttling |
| `kube_pod_container_resource_requests{resource="cpu"\|"memory"}` | kube-state-metrics | Requests (ядра / байты), STABLE |
| `kube_pod_container_resource_limits` | kube-state-metrics | Limits |
| `kube_pod_owner`, `kube_replicaset_owner` | kube-state-metrics | Связь под → ReplicaSet → Deployment |
| `node_namespace_pod_container:container_cpu_usage_seconds_total:sum_rate5m` | recording rule kube-prometheus-stack | Готовый `rate` CPU по контейнерам |
| `namespace_cpu:kube_pod_container_resource_requests:sum`, `namespace_memory:…:sum` | recording rule kube-prometheus-stack | Requests **активных** (Pending/Running) подов по namespace |

Фильтры: `container!=""` — убрать агрегат уровня пода, `container!="POD"` — pause-контейнер.

### Готовые запросы

```promql
# Сейчас: ядра по контейнерам
sum by (namespace, pod, container) (
  rate(container_cpu_usage_seconds_total{namespace="shop", container!="", container!="POD"}[5m])
)

# p95 CPU за 14 дней по workload: имя Deployment вырезаем из имени пода,
# max by — берём самую загруженную реплику в каждый момент (консервативно для request пода)
quantile_over_time(0.95,
  max by (namespace, workload, container) (
    label_replace(
      rate(container_cpu_usage_seconds_total{namespace="shop", container!="", container!="POD"}[5m]),
      "workload", "$1", "pod", "(.+)-[a-z0-9]+-[a-z0-9]{5}"
    )
  )[14d:5m]
)

# Пик памяти за 14 дней (для памяти — max или p99, не p95: OOM не прощает)
max_over_time(
  max by (namespace, workload, container) (
    label_replace(
      container_memory_working_set_bytes{namespace="shop", container!="", container!="POD"},
      "workload", "$1", "pod", "(.+)-[a-z0-9]+-[a-z0-9]{5}"
    )
  )[14d:5m]
)

# Текущие requests для сравнения
max by (namespace, pod, container) (kube_pod_container_resource_requests{namespace="shop", resource="cpu"})
```text
Regex `(.+)-[a-z0-9]+-[a-z0-9]{5}` подходит для подов Deployment (`shop-api-7d9f8b6c5d-x2k4p` →
`shop-api`); для StatefulSet — `(.+)-[0-9]+`. Точнее — джойн с `kube_pod_owner`, но для
rightsizing regex хватает.

### Эффективность и потери

```promql
# Эффективность CPU по namespace (usage / requests)
sum by (namespace) (node_namespace_pod_container:container_cpu_usage_seconds_total:sum_rate5m)
/
sum by (namespace) (namespace_cpu:kube_pod_container_resource_requests:sum)

# Эффективность памяти по namespace
sum by (namespace) (container_memory_working_set_bytes{container!="", container!="POD"})
/
sum by (namespace) (namespace_memory:kube_pod_container_resource_requests:sum)

# «Оплачено, но не используется»: ядра в кластере
sum(namespace_cpu:kube_pod_container_resource_requests:sum)
  - sum(node_namespace_pod_container:container_cpu_usage_seconds_total:sum_rate5m)

# Топ-10 подов по завышенным CPU requests (в ядрах)
topk(10,
  sum by (namespace, pod) (kube_pod_container_resource_requests{resource="cpu"})
  - sum by (namespace, pod) (rate(container_cpu_usage_seconds_total{container!="", container!="POD"}[5m]))
)

# Throttling: доля периодов, в которых контейнер упёрся в лимит (> 25% — плохо)
sum by (namespace, pod, container) (rate(container_cpu_cfs_throttled_periods_total{container!=""}[5m]))
/
sum by (namespace, pod, container) (rate(container_cpu_cfs_periods_total{container!=""}[5m]))
```text
### Длинные окна: recording rules и retention

Subquery `[14d:5m]` по сотням контейнеров тяжёлый. Вынеси «внутренность» в recording rule
(в kube-prometheus-stack — объект `PrometheusRule`):
```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: finops-rightsizing
  namespace: monitoring
spec:
  groups:
    - name: finops-rightsizing
      interval: 1m
      rules:
        - record: workload_container:cpu_usage_cores:max_rate5m
          expr: |
            max by (namespace, workload, container) (
              label_replace(
                rate(container_cpu_usage_seconds_total{container!="", container!="POD"}[5m]),
                "workload", "$1", "pod", "(.+)-[a-z0-9]+-[a-z0-9]{5}"))
        - record: workload_container:memory_working_set_bytes:max
          expr: |
            max by (namespace, workload, container) (
              label_replace(
                container_memory_working_set_bytes{container!="", container!="POD"},
                "workload", "$1", "pod", "(.+)-[a-z0-9]+-[a-z0-9]{5}"))
```text
```promql
quantile_over_time(0.95, workload_container:cpu_usage_cores:max_rate5m[14d])
max_over_time(workload_container:memory_working_set_bytes:max[14d])
```text
> ⚠️ У kube-prometheus-stack retention по умолчанию — **10 дней**. Окно 14 дней на таком
> Prometheus молча посчитается по 10. Ставь `prometheus.prometheusSpec.retention: 15d`
> (или больше) либо используй долговременное хранилище.

Почему 7–14 дней: захватить недельную сезонность (понедельник ≠ воскресенье), ночные батчи
и релизы. Меньше недели — риск пропустить пик; больше месяца — устаревшие данные после
изменений в коде.

---

## 5. Как выбрать новые числа

```text
CPU request     = p95 CPU за 14 дней × 1,1–1,2          (веб, API)
                  p90 и меньше запаса                     (батчи, воркеры очередей)
CPU limit       = нет, или 2–4× request                  (раздел 7)
memory request  = memory limit = max working set × 1,2   (или p99 × 1,25)
минимум         = 50m / 64Mi на контейнер                 (ниже — шум и риск)
пересмотр       = через 2 недели после изменения и после крупных релизов
```text
**Особый случай — сервисы под HPA.** HPA держит утилизацию `usage / request` около цели.
Уменьшишь request — HPA добавит реплик, и суммарно ядер будет столько же:
```text
стоимость ≈ суммарное потребление / целевая утилизация HPA
usage 6 ядер, target 50% → запрошено 12 ядер;  target 70% → ≈ 8,6 ядра (−28%)
```text
Для сервисов под HPA главный рычаг — **целевая утилизация и minReplicas** (тема 03),
а rightsizing важен для памяти (её HPA не скейлит) и для «пола» при minReplicas.

**Рантаймы:** JVM — согласуй `-XX:MaxRAMPercentage` с memory limit и учти CPU-пик на старте
(startupProbe + отсутствие CPU limit); Go — `GOMEMLIMIT` ≈ 90% memory limit; Node.js —
`--max-old-space-size` меньше лимита.

Пример «до/после» (иллюстративно):

| Deployment | Реплик | CPU req → p95 → новый | Mem req → max WS → новый (= limit) | Освобождено |
|------------|--------|-----------------------|-------------------------------------|-------------|
| shop-api | 3 | 1000m → 180m → **250m** | 1Gi → 310Mi → **384Mi** | 2,25 vCPU, 1,9 GiB |
| worker | 2 | 500m → 40m → **100m** | 512Mi → 160Mi → **192Mi** | 0,8 vCPU, 0,6 GiB |
| nginx | 2 | 500m → 5m → **50m** | 256Mi → 12Mi → **64Mi** | 0,9 vCPU, 0,4 GiB |
| **Итого** | | | | **3,95 vCPU, 2,9 GiB ≈ $130/мес** |

---

## 6. Дашборд эффективности

В kube-prometheus-stack уже есть дашборды «Kubernetes / Compute Resources / Namespace (Pods)»
с колонками *CPU Requests %* и *Memory Requests %* (usage / requests). Свой FinOps-дашборд
([../Left/02_Monitoring/06_grafana.md](/monitoring/06-grafana) — переменные и provisioning):

| Панель | Тип | Запрос |
|--------|-----|--------|
| Эффективность CPU/памяти по namespace | Bar gauge, пороги 30/60% | формулы из раздела 4 |
| Оплачено и не используется | Stat: ядра и `× 30` в $/мес | `requests − usage` |
| Allocatable vs requests vs usage | Time series, 3 линии | `sum(kube_node_status_allocatable{resource="cpu"})`, requests, usage |
| Топ-10 завышенных workload | Table | `topk(10, …)` |
| Throttling топ-10 | Table, порог 25% | доля throttled-периодов |
| p95 CPU / max памяти за 14 дней против requests | Table по `$namespace` | recording rules раздела 4 |

---

## 7. Спор про CPU limits

| | Без CPU limit | С CPU limit |
|---|---------------|-------------|
| Латентность | ✅ Нет throttling: свободные ядра ноды используются | ⚠️ Throttling даже при свободной ноде |
| Честность | ✅ При конкуренции CPU делится пропорционально **requests** (веса cgroup) | Жёсткий потолок |
| Соседи | ⚠️ Прожорливый под съест свободное CPU — остальные получат «только» свои requests | ✅ Предсказуемо |
| QoS Guaranteed | ❌ Невозможен | ✅ Возможен (limit = request и для памяти) |
| Рантаймы | ⚠️ Go ≥ 1.25 выставляет `GOMAXPROCS` по CPU **limit**; без него — по ядрам ноды | ✅ Рантайм видит лимит |

**Сбалансированная рекомендация:**
1. **CPU requests — всегда** и честные: именно они гарантируют долю при конкуренции.
2. **Latency-чувствительные сервисы** в кластере, где у всех честные requests: CPU limit не ставить
   или ставить с запасом (2–4× request).
3. **Мультиарендные кластеры, чужие/недоверенные нагрузки, батчи:** limits (или default из
   LimitRange) — защита от шумных соседей.
4. **Критичное с QoS Guaranteed** (БД, ingress): limit = request.
5. Без CPU limit у Go-сервисов задай `GOMAXPROCS` явно, например из requests через Downward API:
```yaml
env:
  - name: GOMAXPROCS
    valueFrom:
      resourceFieldRef: { resource: requests.cpu, divisor: "1" }   # округляется вверх до целого
```text
---

## 8. Память: limit = request

Память несжимаема, поэтому частая практика — **memory limit = memory request**:
- scheduler знает реальный объём и не переподписывает ноды по памяти;
- под умирает только от **своей** утечки (OOMKilled), а не вытесняется из-за соседей;
- нет сюрприза «на ноде кончилась память, и kubelet выселил половину подов».

Цена — чуть больше запрошенной памяти. Исключение — батчи с редкими пиками, где сознательно
идут на риск OOM ради плотности.

---

## 9. VPA в режиме рекомендаций

VPA (Vertical Pod Autoscaler) из репозитория `kubernetes/autoscaler` — три компонента:
**recommender** (считает), **updater** (выселяет/обновляет поды), **admission controller**
(подставляет значения при создании). Для рекомендаций достаточно recommender.

```bash
# официальный способ (ставит все три компонента)
git clone https://github.com/kubernetes/autoscaler.git
cd autoscaler/vertical-pod-autoscaler && ./hack/vpa-up.sh

# или только recommender — через чарт Fairwinds
helm repo add fairwinds-stable https://charts.fairwinds.com/stable
helm install vpa fairwinds-stable/vpa -n vpa --create-namespace \
  --set updater.enabled=false --set admissionController.enabled=false
```text
```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata: { name: shop-api, namespace: shop }
spec:
  targetRef: { apiVersion: apps/v1, kind: Deployment, name: shop-api }
  updatePolicy:
    updateMode: "Off"                  # ⭐ только рекомендации
  resourcePolicy:
    containerPolicies:
      - containerName: "*"
        controlledResources: ["cpu", "memory"]
        minAllowed: { cpu: 50m, memory: 64Mi }
        maxAllowed: { cpu: "2", memory: 2Gi }
```text
```bash
kubectl get vpa -n shop
kubectl describe vpa shop-api -n shop | grep -A12 "Container Recommendations"
#   Lower Bound / Target / Uncapped Target / Upper Bound  — по каждому контейнеру
```text
| Поле | Смысл |
|------|-------|
| `target` | Рекомендуемый request: p90 истории CPU (для памяти — p90 суточных пиков) + 15% запаса |
| `lowerBound` / `upperBound` | Границы: ниже — «слишком мало», выше — «слишком много» (p50 / p95 с поправкой на доверие) |
| `uncappedTarget` | Target без учёта `minAllowed`/`maxAllowed` |

Recommender использует затухающую гистограмму (свежие данные важнее) и по умолчанию
не рекомендует меньше 25m CPU и 250Mi памяти **на под** — для крошечных контейнеров
(nginx-сайдкар) VPA завышает. Первые дни рекомендации нестабильны: жди ~неделю.

### Режимы `updateMode` (VPA 1.6+)

| Режим | Что делает | Для FinOps |
|-------|-----------|------------|
| `Off` | Только считает рекомендации | ⭐ Старт: смотришь, сравниваешь с PromQL, правишь чарт руками |
| `Initial` | Ставит значения только при создании пода | Безопасно: применяется при следующем деплое/рестарте |
| `Recreate` | Выселяет поды, если рекомендация сильно отличается | Осторожно: рестарты; нужен PDB |
| `InPlaceOrRecreate` | Меняет ресурсы на лету, если не вышло — выселяет (GA в VPA 1.6) | Меньше рестартов; нужен k8s с in-place resize |
| `InPlace` | Только на лету, никогда не выселяет | Самый мягкий автоматический режим |
| `Auto` | ⚠️ Устарел (deprecated) — не используй в новых манифестах | — |

**In-place resize** в Kubernetes — **GA с 1.35** (декабрь 2025): CPU и память работающего
контейнера меняются без пересоздания пода через подресурс `resize`:
```bash
kubectl patch pod shop-api-7d9f8b6c5d-x2k4p -n shop --subresource resize --patch \
  '{"spec":{"containers":[{"name":"app","resources":{"requests":{"cpu":"300m"},"limits":{"cpu":"600m"&#125;&#125;}]&#125;&#125;'
```text
Ограничения: только CPU и память; QoS-класс пода при resize не меняется; `resizePolicy`
контейнера решает, нужен ли рестарт (`NotRequired` / `RestartContainer`); уменьшение memory
limit с 1.35 разрешено, но kubelet лишь «по возможности» проверяет, что текущее потребление
ниже нового лимита. Если на ноде нет места — resize откладывается (`PodResizePending`).

> ⚠️ Уменьшил requests «на лету» — под остался на той же ноде. Нода освободится,
> только если autoscaler/Karpenter переложит поды и удалит её (раздел 12).

---

## 10. Goldilocks — рекомендации VPA для всего namespace

Goldilocks (Fairwinds) создаёт VPA в режиме `Off` для каждого workload в помеченных namespace
и показывает рекомендации в веб-интерфейсе (для QoS Guaranteed и Burstable).
```bash
helm install goldilocks fairwinds-stable/goldilocks -n goldilocks --create-namespace
kubectl label namespace shop goldilocks.fairwinds.com/enabled=true
kubectl -n goldilocks port-forward svc/goldilocks-dashboard 8080:80
# http://localhost:8080 — рекомендации и готовые YAML-сниппеты resources
```text
Goldilocks не ставит сам VPA-компоненты: нужен установленный recommender (раздел 9).

---

## 11. Guardrails: LimitRange и ResourceQuota как инструмент FinOps

Объекты — в [../Kubernetes/09_probes_resources.md](/kubernetes/09-probes-resources). FinOps-применение:

```yaml
apiVersion: v1
kind: LimitRange
metadata: { name: finops-defaults, namespace: team-shop }
spec:
  limits:
    - type: Container
      defaultRequest: { cpu: 100m, memory: 128Mi }   # забыл requests — получишь скромные, а не 0
      default:        { memory: 128Mi }              # memory limit по умолчанию = request
                                                     # ⚠️ request > 128Mi без явного limit → под отклонят
      max:            { cpu: "2", memory: 4Gi }      # «один контейнер на всю ноду» не пройдёт
                                                     # ⚠️ max без default → default limit = max (CPU limit 2 у всех)
      maxLimitRequestRatio: { memory: "1" }          # ⭐ память: limit == request обязательно
---
apiVersion: v1
kind: ResourceQuota
metadata: { name: team-shop-budget, namespace: team-shop }
spec:
  hard:
    requests.cpu: "20"                    # бюджет команды в ядрах ≈ 20 × $30 = $600/мес
    requests.memory: 64Gi
    requests.storage: 500Gi
    persistentvolumeclaims: "20"
    services.loadbalancers: "1"           # ⭐ каждый Service type=LoadBalancer — отдельный платный LB
    count/deployments.apps: "40"
```text
Квота на requests — это **бюджет команды в ядрах**: её легко перевести в деньги и обсуждать
на cost review.

---

## 12. Overcommit и bin packing: как rightsizing превращается в деньги

```text
allocatable = capacity − kube-reserved − system-reserved − порог eviction
overcommit  = sum(limits) / allocatable > 1   → нормально для CPU, опасно для памяти
```text
По умолчанию scheduler **размазывает** поды (стратегия `LeastAllocated`): все ноды заполнены
наполовину, и autoscaler не может удалить ни одну. Способы упаковать плотнее:

| Способ | Где | Как |
|--------|-----|-----|
| Scoring `MostAllocated` | Свой control plane | `KubeSchedulerConfiguration` ниже |
| Профиль автоскейлера | GKE | `optimize-utilization` |
| Consolidation | Karpenter (тема 03) | `consolidationPolicy: WhenEmptyOrUnderutilized` |
| Descheduler | Любой кластер | Стратегия `HighNodeUtilization`: выселяет поды с недогруженных нод, чтобы autoscaler их удалил |

```yaml
apiVersion: kubescheduler.config.k8s.io/v1
kind: KubeSchedulerConfiguration
profiles:
  - schedulerName: default-scheduler
    pluginConfig:
      - name: NodeResourcesFit
        args:
          scoringStrategy:
            type: MostAllocated              # складывать на уже занятые ноды
            resources:
              - { name: cpu, weight: 1 }
              - { name: memory, weight: 1 }
```text
> ⚠️ Плотная упаковка увеличивает blast radius: падение ноды уносит больше подов. Компенсируй
> topology spread и PDB ([../Kubernetes/19_scheduling.md](/kubernetes/19-scheduling)).

---

## 13. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| Rightsizing по среднему | Пики не влезают: throttling, OOM | p95 для CPU, max/p99 для памяти |
| Окно 1–2 дня | Пропущены недельные пики и батчи | 7–14 дней, retention ≥ окна |
| Retention 10d и окно 14d | Молча считается по 10 дням | Retention 15d+ |
| `sum by (pod)` за 14 дней | Имена подов меняются при каждом деплое — ряды рвутся | Агрегировать по workload/container |
| Урезать память по p95 | 5% времени выше request → OOM/eviction | Память — по пику с запасом |
| Снизить requests сервиса под HPA | HPA добавит реплик, экономии нет | Поднимать target утилизации, пересматривать minReplicas |
| CPU limit = request у latency-сервиса | Throttling и хвосты латентности | Без limit или с запасом; следить за throttling |
| `updateMode: Auto` в проде «сразу» | Рестарты подов в час пик, конфликт с HPA | Off → Initial → InPlaceOrRecreate, с PDB |
| Верить VPA для маленьких контейнеров | Минимум 250Mi на под — завышено | Сверять с PromQL |
| Requests снижены, счёт тот же | Ноды не удалены: поды размазаны | Autoscaler/consolidation, bin packing |

---

## 💼 Как это в DevOps

- Rightsizing — самая частая FinOps-задача девопса: раз в квартал выгружаешь таблицу
  «requests против p95/max» по namespace и приносишь командам MR с новыми values.
- Команды боятся уменьшать requests. Аргумент — данные за 14 дней, запас над пиком,
  мониторинг throttling/OOM после изменения и быстрый откат через GitOps.
- В шаблоны Helm-чартов закладывают разумные дефолты, а LimitRange в namespace ловит тех,
  кто забыл про resources.
- Результат меряют в двух единицах: эффективность requests (%) и число нод/$ до и после.
  «Сэкономили 12 vCPU, кластер уменьшился на 3 ноды, −$450/мес, SLO не пострадал» —
  готовая строка для резюме.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| CPU сейчас | `rate(container_cpu_usage_seconds_total{container!=""}[5m])` |
| p95 CPU за 14 дней | `quantile_over_time(0.95, (&lt;rate по workload&gt;)[14d:5m])` |
| Пик памяти | `max_over_time(container_memory_working_set_bytes[14d:5m])` (по workload) |
| Requests | `kube_pod_container_resource_requests{resource="cpu"}` |
| Эффективность namespace | usage / `namespace_cpu:kube_pod_container_resource_requests:sum` |
| Throttling | `throttled_periods / periods` > 25% — плохо |
| Новый CPU request | p95 × 1,1–1,2 |
| Новый memory request = limit | max × 1,2 |
| Рекомендации | VPA `updateMode: "Off"`, `kubectl describe vpa` |
| Для всего namespace | Goldilocks + лейбл `goldilocks.fairwinds.com/enabled=true` |
| Ресурсы без рестарта | `kubectl patch pod … --subresource resize` (GA в 1.35) |
| Защита от «забыл resources» | LimitRange `defaultRequest` |
| Бюджет команды | ResourceQuota `requests.cpu`, `services.loadbalancers` |
| Упаковать плотнее | `MostAllocated`, consolidation, descheduler |

---

## 🧠 Что запомнить

1. Платишь за ноды, ноды покупаются под requests — поэтому requests и есть деньги.
2. Request waste (requests − usage) и idle (allocatable − requests) — разные проблемы с разными лекарствами.
3. Средняя утилизация CPU в кластерах — около 10%: завышенные requests — норма, а не исключение.
4. Мерить за 7–14 дней: CPU — p95, память — пик; retention Prometheus должен покрывать окно.
5. Агрегируй по workload, а не по поду: имена подов меняются при каждом деплое.
6. ⭐ CPU request ≈ p95 × 1,1–1,2; memory request = limit ≈ max × 1,2.
7. Для сервисов под HPA рычаг экономии — target утилизации и minReplicas, а не requests.
8. CPU limit — компромисс: throttling против шумных соседей; requests обязательны всегда.
9. VPA в `Off` и Goldilocks — вторая точка зрения, а не истина; `Auto` устарел; in-place resize — GA в 1.35.
10. Экономия реальна, только когда освободившееся место превращается в меньшее число нод.

➡️ Дальше: [03_autoscaling_cost.md](/finops/03-autoscaling-cost) · Задачи: 02_k8s_rightsizing_tasks.md


---

### Блок A. Теория


**A1.** Почему уменьшение requests само по себе не уменьшает счёт? Что должно произойти ещё?

<details><summary>Ответ</summary>

Ноды оплачиваются целиком. Освободившиеся requests превращаются в деньги, только
когда поды переложены плотнее и лишние ноды удалены: Cluster Autoscaler scale-down,
Karpenter consolidation, descheduler.

</details>

**A2.** Чем request waste отличается от idle? Кто отвечает за каждое и чем лечится?

<details><summary>Ответ</summary>

Request waste = requests − usage: команда запросила больше, чем использует; лечится
rightsizing. Idle = allocatable − requests: ноды заполнены плохо; ответственность платформы,
лечится автоскейлингом нод, consolidation и bin packing.

</details>

**A3.** ⭐ Как возможен сильный CPU throttling при средней загрузке контейнера 30%?

<details><summary>Ответ</summary>

CPU limit — квота CFS на период 100 мс. Многопоточное приложение может сжечь всю квоту
в начале периода (4 потока × 12,5 мс = 50 мс при limit 500m) и стоять до конца периода.
Средняя загрузка по минуте низкая, а запросы, попавшие в «стоячие» 87 мс, тормозят.

</details>

**A4.** Как kubelet выбирает под для вытеснения при нехватке памяти? Что это значит для
rightsizing памяти?

<details><summary>Ответ</summary>

Сначала — поды, чьё потребление выше их requests; внутри — по priority; дальше — по тому,
насколько превышен request. Значит, memory request ниже реального потребления делает под
первым кандидатом на вытеснение: память урезают только с запасом над пиком.

</details>

**A5.** Почему память меряют по `container_memory_working_set_bytes`?

<details><summary>Ответ</summary>

Working set = использованная память минус неактивный файловый кэш — именно её
сравнивают с лимитом для OOM и с порогами eviction. `usage` включает кэш и завышает,
RSS не включает активный кэш и tmpfs и может занизить.

</details>

**A6.** Зачем в запросах фильтры `container!=""` и `container!="POD"`?

<details><summary>Ответ</summary>

cAdvisor отдаёт ряды и для контейнеров, и агрегат уровня пода (с `container=""`) —
без фильтра потребление считается дважды. `container="POD"` — pause-контейнер (в старых
рантаймах), его ресурсы не интересны.

</details>

**A7.** Почему за 14 дней агрегируют по workload, а не по имени пода?

<details><summary>Ответ</summary>

При каждом деплое поды получают новые имена: ряд старого пода обрывается, нового —
начинается. `quantile_over_time` по поду считает статистику по короткому куску жизни.
По workload + container ряд непрерывен весь период.

</details>

**A8.** Почему окно — 7–14 дней? Какая ловушка есть у kube-prometheus-stack по умолчанию?

<details><summary>Ответ</summary>

Нужно захватить недельную сезонность, батчи и релизы. У kube-prometheus-stack
retention по умолчанию 10 дней — окно 14 дней молча посчитается по 10.

</details>

**A9.** ⭐ Сформулируй правило выбора CPU request и memory request/limit. Почему для CPU
и памяти разные статистики?

<details><summary>Ответ</summary>

CPU request ≈ p95 × 1,1–1,2 (батчи — p90), memory request = limit ≈ max × 1,2 (или
p99 × 1,25). CPU сжимаем — превышение request даёт замедление, а не смерть, поэтому p95
допустим. Память несжимаема — превышение лимита = OOMKilled, поэтому берут пик.

</details>

**A10.** ⭐ Почему снижение requests у сервиса под HPA обычно не даёт экономии? Что даёт?

<details><summary>Ответ</summary>

HPA держит `usage / request` около цели: меньше request — больше реплик, суммарные
requests почти те же. Стоимость ≈ потребление / target. Экономят подъёмом target (50% → 70%),
снижением minReplicas там, где это безопасно, и rightsizing памяти.

</details>

**A11.** Аргументы за и против CPU limits. Твоя рекомендация.

<details><summary>Ответ</summary>

Без limit: нет throttling, CPU ноды используется полностью, при конкуренции доли
делятся по requests. С limit: предсказуемость и защита от шумных соседей, возможен Guaranteed.
Рекомендация: честные requests всегда; для latency-сервисов — без limit или с запасом 2–4×;
для мультиарендных кластеров и батчей — limits; для критичного — Guaranteed. Следить за
throttling. Go без limit — задать `GOMAXPROCS`.

</details>

**A12.** Зачем memory limit = request?

<details><summary>Ответ</summary>

Scheduler видит реальный объём памяти, ноды не переподписаны по памяти,
под умирает только от своей утечки, а не вытесняется из-за соседей.

</details>

**A13.** Назови режимы `updateMode` VPA. Какой устарел? Чем `InPlaceOrRecreate` отличается от `Recreate`?

<details><summary>Ответ</summary>

`Off`, `Initial`, `Recreate`, `InPlaceOrRecreate`, `InPlace`; `Auto` — deprecated.
`Recreate` выселяет под для применения; `InPlaceOrRecreate` сначала пробует изменить ресурсы
на лету через in-place resize и выселяет, только если это невозможно.

</details>

**A14.** Как VPA считает `target`? Почему для маленьких контейнеров он завышает?

<details><summary>Ответ</summary>

Затухающая гистограмма потребления: target CPU — p90 истории + 15% запаса,
память — p90 суточных пиков + 15%. Минимум по умолчанию — 25m CPU и 250Mi памяти на под,
поэтому для крошечных контейнеров рекомендация завышена.

</details>

**A15.** In-place resize: статус в Kubernetes, что можно менять, основные ограничения.

<details><summary>Ответ</summary>

GA с Kubernetes 1.35: CPU и память работающего контейнера меняются через подресурс
`resize` без пересоздания пода. Ограничения: только CPU/память; QoS-класс не меняется;
`resizePolicy` определяет необходимость рестарта контейнера; уменьшение memory limit
разрешено, но проверка «потребление ниже нового лимита» — best effort; нет места на ноде —
resize откладывается.

</details>

**A16.** Как LimitRange и ResourceQuota работают как FinOps-guardrails? Зачем квота
`services.loadbalancers`?

<details><summary>Ответ</summary>

LimitRange задаёт скромные дефолты для тех, кто забыл resources, и потолки
(`max`, `maxLimitRequestRatio`), ResourceQuota — суммарный бюджет namespace в ядрах/GiB/ГБ
дисков и числе объектов. `services.loadbalancers` ограничивает число платных облачных
балансировщиков (каждый Service `type: LoadBalancer` — отдельный LB с почасовой оплатой).

</details>

**A17.** Что такое bin packing и почему scheduler по умолчанию его не делает?

<details><summary>Ответ</summary>

Упаковка подов на минимум нод, чтобы остальные удалить. Scheduler по умолчанию
использует `LeastAllocated` — выбирает наименее занятые ноды ради отказоустойчивости
и равномерности; упаковывают стратегией `MostAllocated`, consolidation или descheduler.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  # новый CPU request выбираю по этому запросу
```text
<details><summary>Ответ</summary>

⚠️ Среднее прячет пики: request по среднему гарантирует конкуренцию за CPU половину
времени. Нужен `quantile_over_time(0.95, …)`.

</details>

```text:no-line-numbers
     avg_over_time(rate(container_cpu_usage_seconds_total{namespace="shop", container="app"}[5m])[14d:5m])
```text
```text:no-line-numbers
B2.  quantile_over_time(0.95,
```text
<details><summary>Ответ</summary>

⚠️ `sum by (pod)` — ряды рвутся при каждом деплое, а сумма по подам даёт потребление
всех реплик, а не одной. Нужно `max by (namespace, workload, container)`.

</details>

```text:no-line-numbers
       sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="shop", container!=""}[5m]))[14d:5m])
```text
```text:no-line-numbers
B3.  # memory request = p95 working set за 14 дней, limit не ставим
```text
<details><summary>Ответ</summary>

⚠️ 5% времени память выше request → eviction при нехватке на ноде; без limit под может
съесть ноду. Память — по пику × 1,2 и limit = request.

</details>

```text:no-line-numbers
B4.  # эффективность CPU кластера
```text
<details><summary>Ответ</summary>

⚠️ Нет `container!=""` — потребление посчитано дважды (агрегат пода + контейнеры).
Requests включают завершённые поды (Completed Jobs) — знаменатель завышен. Лучше recording
rules `node_namespace_pod_container:…:sum_rate5m` и `namespace_cpu:…:sum`.

</details>

```text:no-line-numbers
     sum(rate(container_cpu_usage_seconds_total[5m]))
```text
```text:no-line-numbers
       / sum(kube_pod_container_resource_requests{resource="cpu"})
```text
```text:no-line-numbers
B5.  # Java-сервис (Spring Boot), стартует 60 секунд
```text
<details><summary>Ответ</summary>

⚠️ Java на старте жжёт несколько ядер (JIT, загрузка классов), при limit 100m старт
растянется на минуты, liveness убьёт под до готовности — CrashLoopBackOff. Нужны startupProbe,
CPU request по реальному потреблению и без жёсткого CPU limit (или с большим).

</details>

```text:no-line-numbers
     resources: { requests: { cpu: 100m, memory: 1Gi }, limits: { cpu: 100m, memory: 1Gi } }
```text
```text:no-line-numbers
     livenessProbe: { httpGet: { path: /actuator/health, port: 8080 }, failureThreshold: 3 }
```text
```text:no-line-numbers
B6.  # один и тот же Deployment
```text
<details><summary>Ответ</summary>

⚠️ VPA меняет CPU request, HPA скейлит по `usage / request` — петля: VPA поднял request →
утилизация упала → HPA убрал реплики → нагрузка на под выросла → VPA снова поднял.
Рабочее сочетание: HPA по CPU + VPA только на память (`controlledResources: [memory]`).

</details>

```text:no-line-numbers
     VPA updateMode: Recreate, controlledResources: [cpu, memory]
```text
```text:no-line-numbers
     HPA по CPU averageUtilization: 70
```text
```text:no-line-numbers
B7.  # LimitRange в namespace: default.memory 128Mi, defaultRequest.memory 128Mi
```text
<details><summary>Ответ</summary>

⚠️ Default limit 128Mi подставится, а request 512Mi больше limit — admission отклонит
под. Указывать limit явно или поднять `default`.

</details>

```text:no-line-numbers
     # контейнер: requests.memory: 512Mi, limits не указаны
```text
```text:no-line-numbers
B8.  # kube-prometheus-stack с values по умолчанию
```text
<details><summary>Ответ</summary>

⚠️ Retention по умолчанию 10 дней — «максимум за 14 дней» на деле за 10.

</details>

```text:no-line-numbers
     max_over_time(container_memory_working_set_bytes{namespace="shop"}[14d])
```text
```text:no-line-numbers
B9.  # requests в кластере снижены на 60%, прошла неделя — нод столько же, счёт тот же
```text
<details><summary>Ответ</summary>

⚠️ Поды размазаны по нодам (`LeastAllocated`), autoscaler не может освободить ни одну,
или scale-down блокируют PDB/`safe-to-evict`/локальные тома/минимум группы. Нужны
consolidation/descheduler и разбор блокировок.

</details>

```text:no-line-numbers
B10.  # 40 подов на нодах по 16 GiB
```text
<details><summary>Ответ</summary>

⚠️ Scheduler считает 40 × 256Mi = 10 GiB, а поды вправе взять до 80 GiB — переподписка
по памяти в 8 раз. При одновременном росте — OOM и массовые eviction. Limit = request.

</details>

```text:no-line-numbers
     resources: { requests: { memory: 256Mi }, limits: { memory: 2Gi } }
```text
```text:no-line-numbers
B11.  # Go 1.24-сервис на ноде с 64 ядрами, requests.cpu: 500m, CPU limit не задан, GOMAXPROCS не задан
```text
<details><summary>Ответ</summary>

⚠️ Go до 1.25 выставит `GOMAXPROCS=64`: 64 потока конкурируют за долю в 0,5 ядра
при конкуренции — переключения контекста, лишняя латентность GC. Задать `GOMAXPROCS`
(из requests через Downward API) или обновиться до Go ≥ 1.25 и поставить limit.

</details>

```text:no-line-numbers
B12.  # «чтобы сэкономить побольше, ставим CPU request = p50 за неделю»
```text
<details><summary>Ответ</summary>

⚠️ Половину времени под потребляет больше request — при конкуренции он получает меньше,
чем нужно, латентность в пиках растёт; для HPA утилизация будет постоянно > 100%.
Экономия мнимая, SLO пострадает.

</details>


---

### Блок C. Практика


### C1. 🔑 Найти завышенные requests
На стенде в namespace `demo`:
**1.** Выведи текущее потребление CPU и памяти по контейнерам и их requests.

<details><summary>Ответ</summary>

```promql
sum by (pod, container) (rate(container_cpu_usage_seconds_total{namespace="demo", container!="", container!="POD"}[5m]))
sum by (pod, container) (container_memory_working_set_bytes{namespace="demo", container!="", container!="POD"})
sum by (pod, container) (kube_pod_container_resource_requests{namespace="demo"}) # resource="cpu"/"memory"

sum by (namespace) (node_namespace_pod_container:container_cpu_usage_seconds_total:sum_rate5m{namespace="demo"})
  / sum by (namespace) (namespace_cpu:kube_pod_container_resource_requests:sum{namespace="demo"})

topk(5, sum by (pod, container) (kube_pod_container_resource_requests{namespace="demo", resource="cpu"})
      - sum by (pod, container) (rate(container_cpu_usage_seconds_total{namespace="demo", container!=""}[5m])))
topk(5, sum by (pod, container) (kube_pod_container_resource_requests{namespace="demo", resource="memory"})
      - sum by (pod, container) (container_memory_working_set_bytes{namespace="demo", container!=""})) / 2^30
```text
</details>

**2.** Посчитай эффективность CPU и памяти по namespace (через recording rules kube-prometheus-stack).

<details><summary>Ответ</summary>

Если правил нет на `/rules` — у Prometheus из kube-prometheus-stack селектор правил
по лейблу `release`: либо добавить `metadata.labels.release: prometheus`, либо (как на стенде)
`ruleSelectorNilUsesHelmValues: false`. Запросы:
`quantile_over_time(0.95, workload_container:cpu_usage_cores:max_rate5m{namespace="demo"}[1h])`
и `max_over_time(workload_container:memory_working_set_bytes:max{namespace="demo"}[1h])`.

</details>

**3.** Найди топ-5 контейнеров по «оплачено, но не используется» в ядрах и в GiB.

<details><summary>Ответ</summary>

```text
api:      CPU 220 × 1,15 = 253 → 250m;   память 420 × 1,2 = 504 → 512Mi
consumer: CPU 350 × 1,15 = 402 → 400m;   память 1,1 × 1,2 = 1,32 GiB → 1,5Gi (1536Mi)
report:   CPU 1400 × 1,15 = 1610 → 1600m; память 3,2 × 1,2 = 3,84 → 4Gi (без изменений)

Освобождено (постоянно работающие):
api:      CPU (800 − 250) × 4 = 2200m;  память (1024 − 512) × 4 = 2048Mi = 2 GiB
consumer: CPU (1000 − 400) × 3 = 1800m; память (2048 − 1536) × 3 = 1536Mi = 1,5 GiB
Итого: 4 vCPU и 3,5 GiB → 4 × $30 + 3,5 × $4 = $120 + $14 = $134/мес
report:   0,4 vCPU, но только 2 ч в сутки: 0,4 × $30 × 2/24 ≈ $1/мес
```text
По `report` экономия пропорциональна времени работы: запросы CronJob занимают ноду только
пока Job идёт (если под него не держат отдельную ноду 24/7).

</details>

### C2. 🔑 Recording rules для длинных окон
**1.** Примени `PrometheusRule` из конспекта (раздел 4). Проверь, что правила появились на `/rules`.

<details><summary>Ответ</summary>

```promql
sum by (pod, container) (rate(container_cpu_usage_seconds_total{namespace="demo", container!="", container!="POD"}[5m]))
sum by (pod, container) (container_memory_working_set_bytes{namespace="demo", container!="", container!="POD"})
sum by (pod, container) (kube_pod_container_resource_requests{namespace="demo"}) # resource="cpu"/"memory"

sum by (namespace) (node_namespace_pod_container:container_cpu_usage_seconds_total:sum_rate5m{namespace="demo"})
  / sum by (namespace) (namespace_cpu:kube_pod_container_resource_requests:sum{namespace="demo"})

topk(5, sum by (pod, container) (kube_pod_container_resource_requests{namespace="demo", resource="cpu"})
      - sum by (pod, container) (rate(container_cpu_usage_seconds_total{namespace="demo", container!=""}[5m])))
topk(5, sum by (pod, container) (kube_pod_container_resource_requests{namespace="demo", resource="memory"})
      - sum by (pod, container) (container_memory_working_set_bytes{namespace="demo", container!=""})) / 2^30
```text
</details>

**2.** Через 30–60 минут посчитай p95 CPU и максимум памяти по workload за `[1h]`
   (в проде — `[14d]`).

<details><summary>Ответ</summary>

Если правил нет на `/rules` — у Prometheus из kube-prometheus-stack селектор правил
по лейблу `release`: либо добавить `metadata.labels.release: prometheus`, либо (как на стенде)
`ruleSelectorNilUsesHelmValues: false`. Запросы:
`quantile_over_time(0.95, workload_container:cpu_usage_cores:max_rate5m{namespace="demo"}[1h])`
и `max_over_time(workload_container:memory_working_set_bytes:max{namespace="demo"}[1h])`.

</details>

**3.** Убедись, что Prometheus хранит данные дольше окна: `kubectl -n monitoring get prometheus -o yaml | grep retention`.

<details><summary>Ответ</summary>

```text
api:      CPU 220 × 1,15 = 253 → 250m;   память 420 × 1,2 = 504 → 512Mi
consumer: CPU 350 × 1,15 = 402 → 400m;   память 1,1 × 1,2 = 1,32 GiB → 1,5Gi (1536Mi)
report:   CPU 1400 × 1,15 = 1610 → 1600m; память 3,2 × 1,2 = 3,84 → 4Gi (без изменений)

Освобождено (постоянно работающие):
api:      CPU (800 − 250) × 4 = 2200m;  память (1024 − 512) × 4 = 2048Mi = 2 GiB
consumer: CPU (1000 − 400) × 3 = 1800m; память (2048 − 1536) × 3 = 1536Mi = 1,5 GiB
Итого: 4 vCPU и 3,5 GiB → 4 × $30 + 3,5 × $4 = $120 + $14 = $134/мес
report:   0,4 vCPU, но только 2 ч в сутки: 0,4 × $30 × 2/24 ≈ $1/мес
```text
По `report` экономия пропорциональна времени работы: запросы CronJob занимают ноду только
пока Job идёт (если под него не держат отдельную ноду 24/7).

</details>

### C3. 🔑 Таблица «до/после» (расчёт)
| Workload | Реплик | CPU req | p95 CPU | Mem req | Max WS |
|----------|--------|---------|---------|---------|--------|
| api | 4 | 800m | 220m | 1Gi | 420Mi |
| consumer | 3 | 1000m | 350m | 2Gi | 1,1Gi |
| report (CronJob, 2 ч в сутки) | 1 | 2000m | 1400m | 4Gi | 3,2Gi |

По правилу конспекта (CPU × 1,15, память × 1,2, округлить до «красивых» значений) посчитай
новые requests, сколько освободится и сколько это в $/мес (1 vCPU ≈ $30, 1 GiB ≈ $4).
Почему экономия по `report` считается иначе?

### C4. VPA против PromQL
**1.** Поставь VPA recommender (конспект, раздел 9) и создай VPA `updateMode: "Off"` для двух
   Deployment из `demo`.

<details><summary>Ответ</summary>

```promql
sum by (pod, container) (rate(container_cpu_usage_seconds_total{namespace="demo", container!="", container!="POD"}[5m]))
sum by (pod, container) (container_memory_working_set_bytes{namespace="demo", container!="", container!="POD"})
sum by (pod, container) (kube_pod_container_resource_requests{namespace="demo"}) # resource="cpu"/"memory"

sum by (namespace) (node_namespace_pod_container:container_cpu_usage_seconds_total:sum_rate5m{namespace="demo"})
  / sum by (namespace) (namespace_cpu:kube_pod_container_resource_requests:sum{namespace="demo"})

topk(5, sum by (pod, container) (kube_pod_container_resource_requests{namespace="demo", resource="cpu"})
      - sum by (pod, container) (rate(container_cpu_usage_seconds_total{namespace="demo", container!=""}[5m])))
topk(5, sum by (pod, container) (kube_pod_container_resource_requests{namespace="demo", resource="memory"})
      - sum by (pod, container) (container_memory_working_set_bytes{namespace="demo", container!=""})) / 2^30
```text
</details>

**2.** Через час сравни `target` VPA с твоими p95/max из C2. Объясни расхождения.

<details><summary>Ответ</summary>

Если правил нет на `/rules` — у Prometheus из kube-prometheus-stack селектор правил
по лейблу `release`: либо добавить `metadata.labels.release: prometheus`, либо (как на стенде)
`ruleSelectorNilUsesHelmValues: false`. Запросы:
`quantile_over_time(0.95, workload_container:cpu_usage_cores:max_rate5m{namespace="demo"}[1h])`
и `max_over_time(workload_container:memory_working_set_bytes:max{namespace="demo"}[1h])`.

</details>

### C5. Goldilocks
Поставь Goldilocks, пометь namespace `demo`, открой дашборд. Сравни рекомендации для
Guaranteed и Burstable. Для какого контейнера рекомендация явно завышена и почему?

### C6. 🔑 Throttling своими глазами
**1.** Разверни `registry.k8s.io/hpa-example` (каждый запрос жжёт CPU) с `requests.cpu: 100m`,
   `limits.cpu: 100m` и Service на 80 порту.

<details><summary>Ответ</summary>

```promql
sum by (pod, container) (rate(container_cpu_usage_seconds_total{namespace="demo", container!="", container!="POD"}[5m]))
sum by (pod, container) (container_memory_working_set_bytes{namespace="demo", container!="", container!="POD"})
sum by (pod, container) (kube_pod_container_resource_requests{namespace="demo"}) # resource="cpu"/"memory"

sum by (namespace) (node_namespace_pod_container:container_cpu_usage_seconds_total:sum_rate5m{namespace="demo"})
  / sum by (namespace) (namespace_cpu:kube_pod_container_resource_requests:sum{namespace="demo"})

topk(5, sum by (pod, container) (kube_pod_container_resource_requests{namespace="demo", resource="cpu"})
      - sum by (pod, container) (rate(container_cpu_usage_seconds_total{namespace="demo", container!=""}[5m])))
topk(5, sum by (pod, container) (kube_pod_container_resource_requests{namespace="demo", resource="memory"})
      - sum by (pod, container) (container_memory_working_set_bytes{namespace="demo", container!=""})) / 2^30
```text
</details>

**2.** Дай нагрузку: `kubectl run load --image=busybox:1.36 --restart=Never -- sh -c 'while true; do wget -q -O- http://php-apache; done'`.

<details><summary>Ответ</summary>

Если правил нет на `/rules` — у Prometheus из kube-prometheus-stack селектор правил
по лейблу `release`: либо добавить `metadata.labels.release: prometheus`, либо (как на стенде)
`ruleSelectorNilUsesHelmValues: false`. Запросы:
`quantile_over_time(0.95, workload_container:cpu_usage_cores:max_rate5m{namespace="demo"}[1h])`
и `max_over_time(workload_container:memory_working_set_bytes:max{namespace="demo"}[1h])`.

</details>

**3.** Построй долю throttled-периодов и время ответа (`time wget …` из другого пода).

<details><summary>Ответ</summary>

```text
api:      CPU 220 × 1,15 = 253 → 250m;   память 420 × 1,2 = 504 → 512Mi
consumer: CPU 350 × 1,15 = 402 → 400m;   память 1,1 × 1,2 = 1,32 GiB → 1,5Gi (1536Mi)
report:   CPU 1400 × 1,15 = 1610 → 1600m; память 3,2 × 1,2 = 3,84 → 4Gi (без изменений)

Освобождено (постоянно работающие):
api:      CPU (800 − 250) × 4 = 2200m;  память (1024 − 512) × 4 = 2048Mi = 2 GiB
consumer: CPU (1000 − 400) × 3 = 1800m; память (2048 − 1536) × 3 = 1536Mi = 1,5 GiB
Итого: 4 vCPU и 3,5 GiB → 4 × $30 + 3,5 × $4 = $120 + $14 = $134/мес
report:   0,4 vCPU, но только 2 ч в сутки: 0,4 × $30 × 2/24 ≈ $1/мес
```text
По `report` экономия пропорциональна времени работы: запросы CronJob занимают ноду только
пока Job идёт (если под него не держат отдельную ноду 24/7).

</details>

**4.** Убери CPU limit, повтори. Сравни в таблице.

<details><summary>Ответ</summary>

Типичные расхождения: VPA берёт p90 + 15% — CPU target бывает ниже p95 × 1,15;
по памяти VPA смотрит суточные пики и минимум 250Mi на под — для маленьких контейнеров
выше твоего max × 1,2; первые часы VPA ещё мало знает (низкое доверие → широкие bounds).

</details>

### C7. Guardrails
В namespace `team-a` создай LimitRange и ResourceQuota из конспекта (раздел 11). Проверь:
под без resources; контейнер с `requests.memory: 512Mi` без limit; второй Service
`type: LoadBalancer`. Объясни каждую ошибку.

### C8. In-place resize
Создай kind-кластер с нодой Kubernetes ≥ 1.35 (`kind create cluster --image kindest/node:v1.35.x`
— тег возьми из релизов kind). Измени CPU request работающего пода через
`kubectl patch … --subresource resize`. Проверь, что `RESTARTS` не вырос, и найди новые
значения в `.status.containerStatuses[0].resources`.

### C9. Bin packing на бумаге
**6.** нод по 4 vCPU (allocatable 3,8). После rightsizing: 20 подов по 250m и 6 подов по 1000m.
Сколько нод нужно при идеальной упаковке? Что будет при стратегии `LeastAllocated` без
consolidation? Сколько это в деньгах (нода ≈ $146/мес)?

<details><summary>Ответ</summary>

С limit 100m доля throttled-периодов — десятки процентов, время ответа — сотни мс и
выше; без limit throttling = 0, время ответа падает в разы (под берёт свободное CPU ноды).
Вывод: CPU limit у latency-сервиса — осознанное решение, а не дефолт.

</details>

---

### Блок D. Инциденты


**D1.** После rightsizing (CPU limits не ставили) в час пик p99 вырос в 3 раза. Throttling
по метрикам — ноль. Что происходит и что проверить?

<details><summary>Ответ</summary>

Без limits под при конкуренции получает CPU пропорционально requests. Requests
снизили — в пик на переподписанной ноде сервису достаётся меньше. Проверить: загрузку нод
(`node_cpu_seconds_total` idle), PSI CPU (`container_pressure_cpu_waiting_seconds_total`,
если собирается), соседей на тех же нодах, окно для p95 (не пропущен ли пик), HPA target.
Лечение: поднять request до p95 пика, распределить по нодам, HPA раньше добавляет реплики.

</details>

**D2.** После снижения memory requests поды `api` каждую ночь получают `Evicted`,
когда стартует батч-отчёт на тех же нодах.

<details><summary>Ответ</summary>

Батч ест больше своих requests, на ноде кончается память, kubelet выселяет поды,
превысившие свои requests, — после урезания это `api`. Лечение: memory request = limit
у `api` по пику; честные requests у батча; разнести батчи на отдельный пул (taint/toleration);
PriorityClass для `api`.

</details>

**D3.** Включили VPA `InPlaceOrRecreate`, через сутки — серия `OOMKilled` у сервиса с кэшем.

<details><summary>Ответ</summary>

VPA снизил memory limit по истории, а кэш растёт до лимита (или был пик вне истории) —
OOM. Сделать: `minAllowed` по памяти, `controlledValues: RequestsOnly` или режим `Initial`,
лимит кэша в приложении, для stateful-кэшей — ручной rightsizing.

</details>

**D4.** Дашборд показывает эффективность CPU namespace `batch` — 240%. Ошибка?

<details><summary>Ответ</summary>

Не обязательно ошибка: без CPU limit поды могут потреблять больше requests (burst),
если на нодах свободно. Но это риск: при конкуренции они получат только requests и затормозят.
Также проверить двойной счёт (нет фильтра `container!=""`). Действие — поднять requests
до реального потребления.

</details>

**D5.** Применили рекомендации Goldilocks «как есть» — namespace упёрся в ResourceQuota
по `requests.memory`, хотя поды почти ничего не потребляют.

<details><summary>Ответ</summary>

VPA/Goldilocks не опускается ниже 250Mi на под — для десятков маленьких подов это
сотни GiB «на бумаге». Сверять с PromQL, задавать `minAllowed`/ручные значения, для
маленьких контейнеров ставить свой минимум (например, 64Mi).

</details>

**D6.** Ввели ResourceQuota с `limits.memory` — у команды перестали создаваться поды:
`must specify limits.memory`.

<details><summary>Ответ</summary>

При квоте на `limits.memory` каждый контейнер обязан иметь memory limit. Добавить
LimitRange с `default.memory` или прописать limits в чартах; внедрять квоты вместе с дефолтами.

</details>

**D7.** Нода загружена по requests на 15%, но Cluster Autoscaler её не удаляет уже сутки.

<details><summary>Ответ</summary>

Блокировки scale-down: поды с PDB без запаса (`ALLOWED DISRUPTIONS 0`), поды без
контроллера, `cluster-autoscaler.kubernetes.io/safe-to-evict: "false"`, поды с локальным
хранилищем, системные поды kube-system без PDB, группа нод на минимуме (`min size`),
поды не помещаются на оставшиеся ноды из-за affinity/taints. Смотри `kubectl -n kube-system
logs deploy/cluster-autoscaler` и события ноды.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как ты подбираешь requests и limits для сервиса?

<details><summary>Ответ</summary>

Меряю за 7–14 дней: CPU — p95, память — пик working set. CPU request ≈ p95 × 1,1–1,2,
   memory request = limit ≈ max × 1,2. CPU limit — по ситуации. Применяю через GitOps,
   слежу за throttling/OOM/SLO и пересматриваю через 2 недели.

</details>

**2.** Чем requests отличаются от limits с точки зрения денег?

<details><summary>Ответ</summary>

Requests определяют число нод, то есть счёт. Limits на деньги напрямую не влияют —
   они про throttling и OOM, но их переподписка влияет на стабильность.

</details>

**3.** Ставишь ли ты CPU limits? Почему?

<details><summary>Ответ</summary>

Для latency-сервисов обычно нет (или с запасом): throttling хуже; requests честные
   обязательно. В мультиарендных кластерах и для батчей — да, через LimitRange.

</details>

**4.** Как найти в кластере поды с завышенными requests?

<details><summary>Ответ</summary>

Эффективность usage/requests по namespace и workload, топ по `requests − usage`,
   p95 за 14 дней против requests; дашборды Compute Resources; Goldilocks/VPA; OpenCost
   показывает эффективность и в деньгах.

</details>

**5.** Что такое VPA и почему его редко включают в режиме Auto?

<details><summary>Ответ</summary>

Подбирает requests по истории. Auto (теперь Recreate/InPlaceOrRecreate) выселяет или
   меняет поды без контроля, конфликтует с HPA, для маленьких контейнеров завышает;
   на практике — Off для рекомендаций или Initial.

</details>

**6.** Почему нельзя использовать VPA и HPA по CPU на одном Deployment?

<details><summary>Ответ</summary>

HPA скейлит по отношению usage/request, VPA меняет request — они сбивают друг друга.
   Можно: HPA по CPU + VPA на память, или HPA по прикладной метрике.

</details>

**7.** Что такое QoS-классы и как они связаны с экономией?

<details><summary>Ответ</summary>

Guaranteed, Burstable, BestEffort — порядок вытеснения и OOM. Урезая requests, двигаешь
   поды к вытеснению; память режут осторожно, критичному даёшь Guaranteed.

</details>

**8.** Снизили requests — почему счёт не уменьшился?

<details><summary>Ответ</summary>

Ноды не удалились: поды размазаны, scale-down блокирован, или сервис под HPA добавил реплик.

</details>

**9.** Что такое in-place pod resize?

<details><summary>Ответ</summary>

Изменение CPU/памяти работающего контейнера без пересоздания пода; GA в Kubernetes 1.35;
   VPA использует его в `InPlaceOrRecreate`.

</details>

**10.** Как защитить кластер от команды, которая не ставит resources?

<details><summary>Ответ</summary>

LimitRange с дефолтами и потолками, ResourceQuota, admission-политика (Kyverno)
    «resources обязательны», шаблоны чартов с разумными дефолтами.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Объясняю, почему requests — деньги и когда экономия становится реальной
- [ ] Пишу PromQL: потребление, requests, эффективность, throttling
- [ ] ⭐ Считаю p95 CPU и пик памяти по workload за 7–14 дней (recording rules, retention)
- [ ] Выбираю новые requests/limits по правилу и считаю экономию в $
- [ ] Знаю, почему для сервисов под HPA рычаг — target утилизации
- [ ] Объясняю спор про CPU limits и даю сбалансированную рекомендацию
- [ ] Получил рекомендации VPA (Off) и Goldilocks и сравнил их с PromQL
- [ ] Увидел throttling своими глазами и сравнил с/без limit
- [ ] Поставил LimitRange + ResourceQuota и понимаю каждую ошибку admission
- [ ] Знаю про in-place resize (GA 1.35) и режимы VPA, включая устаревший Auto
