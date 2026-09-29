---
title: "03. Автоскейлинг как инструмент экономии: HPA, KEDA, ноды, spot, расписания"
description: "Блок → FinOps → тема 03. Опирается на"
---

# 03. Автоскейлинг как инструмент экономии: HPA, KEDA, ноды, spot, расписания

> Блок → FinOps → тема 03. Опирается на
> [../Kubernetes/18_hpa_autoscaling.md](/kubernetes/18-hpa-autoscaling) (формула HPA,
> `behavior`, VPA, Cluster Autoscaler — базу не повторяем),
> [../Kubernetes/19_scheduling.md](/kubernetes/19-scheduling) (taints, topology spread, PDB)
> и тему [02_k8s_rightsizing.md](/finops/02-k8s-rightsizing) (requests).
>
> **После темы ты умеешь:** настраивать HPA с оглядкой на деньги (пол, цель, стабилизация),
> избегать конфликтов VPA и HPA, скейлить по очереди и до нуля через KEDA, объяснить
> разницу Cluster Autoscaler и Karpenter (NodePool, consolidation, disruption budgets),
> безопасно использовать spot, выключать non-prod по расписанию и выбирать размер нод.

---

## 🗺️ Карта темы

```text
 ЧТО СКЕЙЛИМ           ЧЕМ                              ГДЕ ДЕНЬГИ
 ─────────────────     ───────────────────────────      ─────────────────────────────────
 реплики подов         HPA (CPU/RPS), KEDA (очереди,    пол (minReplicas), цель утилизации,
                       cron, до нуля)                   скорость scale down
 ресурсы пода          VPA (тема 02)                    requests
 ноды                  Cluster Autoscaler / Karpenter   удаление пустых и недогруженных нод
 тип капасити          spot / on-demand                 −60…90% на отказоустойчивом
 время                 KEDA cron, kube-downscaler       non-prod ночью и в выходные: −60–70%

 ⭐ Цепочка экономии: поды уменьшились → ноды опустели → автоскейлер нод их удалил.
    Любое звено сломано — экономии нет.
```text
---

## 1. HPA как инструмент экономии

Формула и `behavior` — в [../Kubernetes/18_hpa_autoscaling.md](/kubernetes/18-hpa-autoscaling).
Здесь — три рычага стоимости.

**1) Пол (`minReplicas`).** Платишь за него 24/7, даже ночью без трафика.
```text
minReplicas: 3 × request 500m = 1,5 vCPU ≈ $45/мес на сервис
20 сервисов в stage с тем же полом ≈ $900/мес — за окружение, которое ночью никто не открывает
Правило: prod — ≥ 2 (отказоустойчивость, PDB), stage/dev — 1 или 0 через KEDA
```text
**2) Цель утилизации.** Для сервиса под HPA стоимость ≈ потребление / цель.
```text
потребление 6 ядер:  target 50% → 12 ядер requests;  70% → ~8,6;  80% → 7,5
выше цель — дешевле, но меньше запаса на всплеск, пока HPA и ноды догоняют
⭐ разумно 60–75% для веба; выше — если быстро скейлишься и есть запас по нодам
```text
**3) Скорость уменьшения.** Длинное окно стабилизации держит лишние поды после пика,
короткое — «пилит» (поды создаются и удаляются, ноды не успевают консолидироваться).
```yaml
behavior:
  scaleDown:
    stabilizationWindowSeconds: 300      # дефолт; для «пилящего» трафика — 600–900
    policies:
      - { type: Percent, value: 25, periodSeconds: 60 }   # плавно, по четверти в минуту
```text
> 💡 Главная статья экономии у HPA — не `behavior`, а пол и цель. Окно стабилизации —
> про стабильность, его цена обычно копеечная по сравнению с `minReplicas`.

---

## 2. VPA и HPA вместе: что можно, что нельзя

| Сочетание | Можно? | Почему |
|-----------|--------|--------|
| HPA по CPU + VPA меняет CPU (Recreate/InPlace) | ❌ | VPA меняет request, HPA скейлит по usage/request — петля |
| HPA по CPU + VPA только на память (`controlledResources: [memory]`) | ✅ | Разные ресурсы |
| HPA по прикладной метрике (RPS, очередь) + VPA на CPU и память | ✅ (осторожно) | HPA не смотрит на requests |
| HPA любой + VPA `Off` | ✅ | Только рекомендации |
| KEDA + VPA | Те же правила | KEDA сама создаёт HPA (`keda-hpa-&lt;имя&gt;`) |

---

## 3. KEDA: событийный скейлинг и масштабирование до нуля

KEDA (CNCF graduated) добавляет в кластер оператор и metrics adapter. Ты описываешь
`ScaledObject`, KEDA создаёт и ведёт HPA, а переходы **0 ↔ 1** делает сама — HPA этого не умеет.
Актуальная линия — **KEDA 2.21** (23.09.2026, закрывает критическую CVE; поддерживает k8s 1.34–1.36), 70+ скейлеров. Подробно — [../Kubernetes/25_ecosystem.md](/kubernetes/25-ecosystem).

```text
 источник (Prometheus, RabbitMQ, Kafka, SQS, cron, …) ──► KEDA operator
                                                             │ 0 ↔ 1: сама
                                                             │ 1 ↔ N: через HPA keda-hpa-&lt;имя&gt;
                                                             ▼
                                                        Deployment / StatefulSet / Job
```text
```bash
helm repo add kedacore https://kedacore.github.io/charts
helm install keda kedacore/keda -n keda --create-namespace
```text
### Скейлинг по метрике Prometheus

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata: { name: shop-api, namespace: shop }
spec:
  scaleTargetRef: { name: shop-api }          # по умолчанию Deployment
  minReplicaCount: 2
  maxReplicaCount: 20
  pollingInterval: 30                          # как часто опрашивать источник (с)
  advanced:
    horizontalPodAutoscalerConfig:             # behavior для созданного HPA
      behavior:
        scaleDown: { stabilizationWindowSeconds: 300 }
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus-kube-prometheus-prometheus.monitoring.svc:9090
        query: sum(rate(http_requests_total{namespace="shop", job="shop-api"}[2m]))
        threshold: "50"                        # ⭐ целевое значение НА ОДНУ реплику: 400 RPS → 8 реплик
```text
### Очередь и scale to zero

```yaml
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata: { name: rabbitmq-auth, namespace: orders }
spec:
  secretTargetRef:
    - { parameter: host, name: rabbitmq-conn, key: url }   # amqp://user:pass@rabbitmq.orders:5672/
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata: { name: order-worker, namespace: orders }
spec:
  scaleTargetRef: { name: order-worker }
  minReplicaCount: 0                          # ⭐ нет сообщений — нет подов
  maxReplicaCount: 30
  cooldownPeriod: 120                         # сколько ждать тишины перед переходом в 0
  triggers:
    - type: rabbitmq
      metadata:
        queueName: orders
        mode: QueueLength
        value: "20"                           # 20 сообщений в очереди на реплику
        activationValue: "0"                  # > 0 сообщений → просыпаемся с нуля
      authenticationRef: { name: rabbitmq-auth }
```text
| Параметр | Что делает | Нюанс |
|----------|-----------|-------|
| `minReplicaCount: 0` | Разрешает ноль | Первый запрос/сообщение ждёт холодного старта |
| `activationThreshold` / `activationValue` | Порог «проснуться с нуля» | Отдельно от порога скейлинга 1 → N |
| `cooldownPeriod` (дефолт 300 с) | Задержка перед переходом **в 0** | ⚠️ На скейлинг N → 1 не влияет — это `behavior` HPA |
| `idleReplicaCount` | Число реплик «в простое» (обычно 0) при `min > 0` | Редко нужен |
| `fallback` | Сколько реплик держать, если источник недоступен | Без него при падении Prometheus скейлинг «замрёт» |

> ⚠️ Scale to zero подходит воркерам очередей, батчам и dev-окружениям. Для HTTP-сервиса
> без буфера первый запрос после нуля упадёт или будет ждать — нужен KEDA HTTP add-on
> (прокси, держащий запросы) или минимум 1 реплика. Долгие задачи — через `ScaledJob`
> (Job на пачку сообщений), чтобы scale down не убивал работу посередине.

> ⚠️ Не создавай свой HPA для того же Deployment: KEDA ведёт собственный, а два HPA
> на одну цель конфликтуют (admission-вебхук KEDA такое отклоняет).

---

## 4. Ноды: Cluster Autoscaler против Karpenter

### Cluster Autoscaler (CA)

Работает с **группами нод** заранее заданного типа (ASG, node pool облака):
`Pending`-поды → увеличить группу; нода недогружена → переложить поды и удалить.

| Настройка | Дефолт | Для экономии |
|-----------|--------|--------------|
| `--scale-down-utilization-threshold` | 0.5 | Нода-кандидат, если сумма requests < 50% allocatable |
| `--scale-down-unneeded-time` | 10m | Сколько нода должна быть лишней до удаления |
| `--scale-down-delay-after-add` | 10m | Пауза после добавления ноды |
| `--expander` | random | `least-waste` (меньше простоя), `priority` (сначала spot-группы), `price` |
| Pod `cluster-autoscaler.kubernetes.io/safe-to-evict: "false"` | — | ⚠️ Блокирует удаление ноды — используй точечно |

### Karpenter

Не группы, а **подбор инстанса под конкретные поды**: смотрит на `Pending`-поды, выбирает
самый дешёвый подходящий тип из разрешённых и создаёт ноду за секунды. Умеет
**consolidation** — постоянно ищет, как переложить поды на меньше/дешевле нод.

Доступность: **AWS** (EKS, основной провайдер) и **Azure** (AKS Node Auto Provisioning на
базе Karpenter). API — `karpenter.sh/v1` (документация — v1.14 на сентябрь 2026).

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata: { name: general }
spec:
  template:
    spec:
      nodeClassRef: { group: karpenter.k8s.aws, kind: EC2NodeClass, name: default }
      requirements:
        - { key: karpenter.sh/capacity-type, operator: In, values: ["spot", "on-demand"] }
        - { key: kubernetes.io/arch, operator: In, values: ["arm64", "amd64"] }
        - { key: karpenter.k8s.aws/instance-category, operator: In, values: ["c", "m", "r"] }
        - { key: karpenter.k8s.aws/instance-generation, operator: Gt, values: ["5"] }
      expireAfter: 720h                          # ноды живут не дольше 30 дней (свежие AMI)
  limits: { cpu: "200", memory: 800Gi }          # ⭐ потолок: защита от «скейлинга в бесконечность»
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized   # или WhenEmpty, Balanced
    consolidateAfter: 1m
    budgets:
      - nodes: "10%"                             # не больше 10% нод одновременно
      - nodes: "0"                               # в рабочие часы не консолидировать недогруженные
        schedule: "0 4 * * mon-fri"              # ⚠️ cron в UTC: 04:00 UTC = 09:00 Алматы
        duration: 11h
        reasons: [Underutilized]
---
apiVersion: karpenter.k8s.aws/v1
kind: EC2NodeClass
metadata: { name: default }
spec:
  role: "KarpenterNodeRole-${CLUSTER_NAME}"
  amiSelectorTerms: [{ alias: al2023@latest }]
  subnetSelectorTerms:        [{ tags: { karpenter.sh/discovery: "${CLUSTER_NAME}" } }]
  securityGroupSelectorTerms: [{ tags: { karpenter.sh/discovery: "${CLUSTER_NAME}" } }]
```text
| Понятие Karpenter | Смысл |
|-------------------|-------|
| **NodePool** | Какие ноды можно создавать (типы, зоны, spot/on-demand, taints), лимиты и правила disruption |
| **EC2NodeClass** / AKSNodeClass | Облачные детали: AMI, подсети, security groups, IAM-роль |
| **Consolidation** | `WhenEmpty` — только пустые ноды; `WhenEmptyOrUnderutilized` — ещё и заменить недогруженные дешевле; `Balanced` — только если экономия стоит вызванных рестартов подов |
| **Disruption budgets** | Сколько нод можно трогать одновременно, по расписанию и по причине (`Empty`, `Drifted`, `Underutilized`) |
| **Drift / expiration** | Замена нод при изменении NodePool/AMI и по `expireAfter` |
| `karpenter.sh/do-not-disrupt: "true"` | Аннотация пода: не трогать его ноду добровольно (не спасает от spot-прерывания) |

| | Cluster Autoscaler | Karpenter |
|---|--------------------|-----------|
| Единица | Группа нод одного типа | Отдельная нода под поды |
| Выбор типа | Заранее, при создании группы | На лету, самый дешёвый подходящий |
| Скорость | Минуты (через ASG) | Десятки секунд |
| Упаковка | Scale down недогруженных | Активная consolidation, замена на дешёвые |
| Spot | Отдельные группы + expander | Нативно, диверсификация типов |
| Где | Почти везде (AWS, GCP, Azure, Yandex, OpenStack…) | AWS, Azure |

> ⚠️ **Деньги при практике.** Karpenter требует EKS или AKS: control plane EKS ≈ $0,10/ч
> (~$73/мес), плюс ноды, NAT, балансировщики. Хочешь попробовать — бюджет с алертом
> (тема 05), `limits` в NodePool, spot-ноды маленьких типов и **удаление кластера в тот же день**
> (`eksctl delete cluster`). Для блока достаточно понимать манифесты — облачная практика не обязательна.

---

## 5. Spot / preemptible: скидка за риск

| Провайдер | Название | Предупреждение | Особенности |
|-----------|----------|----------------|-------------|
| AWS | Spot Instances | **2 минуты** (+ ранний rebalance recommendation) | Цена плавает, диверсифицируй типы и зоны |
| GCP | Spot VMs | ~30 секунд | Без ограничения времени жизни |
| Azure | Spot VMs | ~30 секунд | Eviction по цене или ёмкости |
| Yandex Cloud | Прерываемые ВМ | Короткое | Живут не дольше 24 часов, могут быть остановлены раньше |

**Что подходит для spot:**

| ✅ Хорошо | ⚠️ С оговорками | ❌ Плохо |
|-----------|----------------|---------|
| Stateless-веб с 3+ репликами | Воркеры очередей (идемпотентность, ack после обработки) | БД и брокеры с одной репликой |
| CI-раннеры, сборки | Долгие батчи — только с чекпойнтами | Stateful с локальными дисками |
| Батчи, ETL, рендеринг | Kafka/Elasticsearch — при репликации и запасе | Всё, что не переживает остановку за 30 с – 2 мин |
| Dev/stage целиком | Ingress-контроллеры — часть реплик на on-demand | Control plane, единственные экземпляры |

**Как переживать прерывания:**
1. **Несколько реплик и PDB** ([../Kubernetes/19_scheduling.md](/kubernetes/19-scheduling)) —
   PDB защищает от добровольных выселений (consolidation, drain), от прерывания spot —
   только запас реплик.
2. **Разнести реплики по типу капасити и зонам.** С Karpenter — 50/50 spot/on-demand:
```yaml
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: karpenter.sh/capacity-type      # лейбл ставит Karpenter: spot / on-demand
    whenUnsatisfiable: DoNotSchedule
    labelSelector: { matchLabels: { app: shop-api } }
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway
    labelSelector: { matchLabels: { app: shop-api } }
```text
3. **Graceful shutdown короче предупреждения:** `terminationGracePeriodSeconds` ≤ 30–90 с,
   readiness падает сразу по SIGTERM, `preStop` даёт балансировщику убрать под.
4. **Обработка сигнала прерывания:** Karpenter — через SQS-очередь (`--interruption-queue`)
   сам cordon/drain; с CA — AWS Node Termination Handler.
5. **Диверсификация:** много типов инстансов (Karpenter выбирает spot по стратегии
   price-capacity-optimized) — меньше шанс одновременного прерывания.
6. **Spot — отдельный пул с taint** для CA-мира: только поды с toleration туда попадут.
```yaml
# нода spot-группы: taint spot=true:NoSchedule; под, которому можно на spot:
tolerations:
  - { key: spot, operator: Equal, value: "true", effect: NoSchedule }
affinity:
  nodeAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 80
        preference:
          matchExpressions: [{ key: node-pool, operator: In, values: [spot] }]
```text
---

## 6. Non-prod по расписанию: выключить на ночь и выходные

```text
неделя = 168 ч;  рабочее время пн–пт 09:00–20:00 = 55 ч  → 33% времени
dev/stage, выключенные вне рабочих часов, стоят ~1/3 от круглосуточных: экономия ~67% compute
⚠️ только если вместе с подами уходят НОДЫ (CA/Karpenter/node pool с min 0)
```text
**Способ 1 — KEDA cron** (на каждый Deployment):
```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata: { name: shop-api-office-hours, namespace: dev }
spec:
  scaleTargetRef: { name: shop-api }
  minReplicaCount: 0                  # вне окна — 0
  maxReplicaCount: 2
  triggers:
    - type: cron
      metadata:
        timezone: Asia/Almaty         # IANA: учитывает переход Казахстана на UTC+5
        start: 0 9 * * 1-5
        end: 0 20 * * 1-5
        desiredReplicas: "2"          # ⚠️ не ставь 0 — ноль даёт minReplicaCount
```text
Ноль наступает через `cooldownPeriod` (дефолт 5 минут) после `end`. Можно добавить второй
триггер (например, Prometheus по RPS), чтобы dev просыпался и вне окна при реальной работе.

**Способ 2 — kube-downscaler** для всего namespace одной аннотацией. Исходный проект
`hjacobs/kube-downscaler` заброшен; поддерживаемые форки — `caas-team/py-kube-downscaler`
и Go-версия **GoKubeDownscaler** (умеет Deployment, StatefulSet, CronJob, HPA, KEDA ScaledObject и др.):
```bash
helm repo add caas-team https://caas-team.github.io/helm-charts/
helm install go-kube-downscaler caas-team/go-kube-downscaler -n kube-downscaler --create-namespace
kubectl annotate namespace dev downscaler/uptime="Mon-Fri 09:00-20:00 Asia/Almaty"
kubectl annotate deploy postgres -n dev downscaler/exclude="true"        # не трогать
kubectl annotate namespace dev downscaler/exclude-until="2026-10-01T18:00:00Z"   # релиз, не гасить
```text
**Способ 3 — CronJob с `kubectl scale`**: работает, но хрупко (RBAC, забытые новые сервисы,
нет исключений). Годится для 2–3 объектов.

| Нюанс | Что делать |
|-------|-----------|
| Базы и брокеры в dev | Гасить последними, поднимать первыми; или оставить (маленькие) |
| PV остаются | Диски тарифицируются и при нуле реплик — это нормально |
| «Мне нужен dev в субботу» | `exclude-until`, ручной `force-uptime`, самообслуживание через чат-бот/CI-кнопку |
| Утренний подъём | Поднимать за 15–30 минут до начала дня: холодный старт нод и образов |
| Managed-БД и ВМ вне k8s | Отдельное расписание: остановка инстансов по тегу `env=dev` |

---

## 7. Размер нод: несколько больших или много маленьких

```text
DaemonSet'ы на каждой ноде (node-exporter, лог-агент, CNI, kube-proxy, CSI) ≈ 0,4 vCPU / 0,8 GiB
12 нод × 2 vCPU = 24 vCPU → накладные 12 × 0,4 = 4,8 vCPU = 20%
 3 ноды × 8 vCPU = 24 vCPU → накладные  3 × 0,4 = 1,2 vCPU =  5%
+ kube-reserved на больших нодах в процентах меньше
```text
| | Много маленьких | Несколько больших |
|---|-----------------|-------------------|
| Накладные DaemonSet/reserved | ⚠️ Высокие | ✅ Низкие |
| Упаковка крупных подов | ⚠️ Под на 3 vCPU не влезет в 2-vCPU ноду | ✅ |
| Шаг автоскейлинга | ✅ Мелкий, мало простоя | ⚠️ Крупный: +8 vCPU ради одного пода |
| Blast radius | ✅ Падение ноды — малая доля | ⚠️ Падение = треть кластера |
| Лимит подов на ноду | ⚠️ Упираешься в max pods / IP (EKS VPC CNI) | ✅ |
| Spot | ✅ Больше типов и шанс получить | ⚠️ Большие типы прерываются заметнее |

Практика: 3+ ноды в пуле ради отказоустойчивости; самый крупный под — не больше ¼–½ ноды;
типичный размер — 4–16 vCPU; с Karpenter размер выбирается автоматически под очередь подов.

---

## 8. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| Поды скейлятся, ноды — нет | Нет CA/Karpenter или scale down заблокирован | Проверять всю цепочку до нод |
| `minReplicas: 3` в dev | Пол 24/7 без трафика | 1 или 0 через KEDA cron |
| target 40% «для надёжности» | Платишь за 2,5× потребления | 60–75% + быстрый скейлинг нод |
| HPA по CPU + VPA на CPU | Петля скейлинга | VPA только на память или Off |
| Свой HPA рядом со ScaledObject | Два HPA на одну цель | Только ScaledObject |
| `desiredReplicas: "0"` в cron | Ошибка конфигурации | Ноль — через `minReplicaCount: 0` |
| Надеяться, что `cooldownPeriod` тормозит N → 1 | Он только про переход в 0 | `advanced.horizontalPodAutoscalerConfig.behavior` |
| Karpenter без `limits` | Баг/атака — сотни нод за ночь | `limits.cpu/memory` + бюджет |
| Consolidation без budgets в час пик | Перетасовка подов днём | Budgets по расписанию (cron в UTC!) |
| Spot для единственной реплики БД | Прерывание = простой и failover | On-demand для stateful |
| PDB «спасёт от spot» | PDB — только добровольные выселения | Запас реплик и spread по капасити |
| Scale to zero для HTTP без буфера | Первые запросы падают | HTTP add-on или min 1 |

---

## 💼 Как это в DevOps

- Первая быстрая победа почти в любой компании — **выключение non-prod ночью**: −60–70%
  compute этих окружений за день работы, почти без риска.
- Karpenter на EKS стал стандартом: consolidation и spot дают десятки процентов экономии,
  а девопс отвечает за NodePool, limits и disruption budgets.
- Spot вводят постепенно: CI-раннеры → dev → батчи → часть реплик stateless-прода.
  Каждый шаг — с проверкой, что сервис переживает прерывание (chaos-тест: удалить ноду).
- KEDA — ответ на «воркер жжёт 10 подов, когда очередь пуста»: scale to zero
  и скейлинг по длине очереди вместо CPU.
- На собесе ценят понимание цепочки: HPA добавил поды → `Pending` → Karpenter создал ноду →
  трафик упал → поды ушли → consolidation удалила ноду.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Дешевле под HPA | Поднять target до 60–75%, снизить `minReplicas` в non-prod |
| Плавный scale down | `behavior.scaleDown.policies` + `stabilizationWindowSeconds` |
| HPA и VPA вместе | HPA по CPU + VPA `controlledResources: [memory]` |
| Скейлить по очереди | KEDA `ScaledObject` + trigger `rabbitmq`/`kafka`/`aws-sqs-queue` |
| До нуля | KEDA `minReplicaCount: 0` + `activationThreshold` |
| Порог Prometheus-триггера | `threshold` — значение на одну реплику |
| Задержка перед нулём | `cooldownPeriod` (дефолт 300 с) |
| Dev по расписанию | KEDA `cron` или `downscaler/uptime` на namespace |
| Удалять лишние ноды | CA `--scale-down-*` или Karpenter consolidation |
| Потолок нод | Karpenter `spec.limits` |
| Не трогать в рабочее время | Karpenter `budgets` с `schedule` (UTC) и `reasons` |
| Смесь spot/on-demand | `topologySpreadConstraints` по `karpenter.sh/capacity-type` |
| Не выселять под | `karpenter.sh/do-not-disrupt` / `safe-to-evict: "false"` (точечно) |

---

## 🧠 Что запомнить

1. Экономия от автоскейлинга реальна, только если после подов уходят ноды.
2. У HPA главные деньги — пол (`minReplicas`) и цель утилизации: стоимость ≈ потребление / цель.
3. HPA по CPU и VPA на CPU вместе нельзя; HPA по CPU + VPA на память — можно.
4. KEDA умеет 0 ↔ 1 и событийные метрики; 1 ↔ N делает созданный ею HPA.
5. `cooldownPeriod` — только про переход в ноль; `threshold` Prometheus-триггера — на одну реплику.
6. CA скейлит группы нод, Karpenter подбирает инстанс под поды и активно консолидирует.
7. У Karpenter обязательно `limits` и disruption budgets; cron в budgets — в UTC.
8. Spot — для отказоустойчивого: несколько реплик, spread по капасити и зонам, graceful shutdown короче предупреждения.
9. PDB защищает от consolidation и drain, но не от прерывания spot.
10. ⭐ Non-prod по расписанию — самая быстрая победа: ~67% экономии compute окружения.

➡️ Дальше: [04_kubecost_opencost.md](/finops/04-kubecost-opencost) · Задачи: 03_autoscaling_cost_tasks.md


---

### Блок A. Теория


**A1.** Опиши цепочку, через которую автоскейлинг экономит деньги. Где она обычно рвётся?

<details><summary>Ответ</summary>

Нагрузка упала → HPA/KEDA уменьшили реплики → ноды опустели → CA/Karpenter переложили
поды и удалили ноды → счёт уменьшился. Рвётся на нодах: нет автоскейлера нод, минимум группы,
блокировки scale down (PDB без запаса, `safe-to-evict: "false"`, локальные тома), поды
размазаны по нодам.

</details>

**A2.** ⭐ Почему стоимость сервиса под HPA ≈ потребление / целевая утилизация? Посчитай
requests для потребления 6 ядер при цели 50% и 75%.

<details><summary>Ответ</summary>

HPA держит `потребление / requests ≈ цель`, значит requests ≈ потребление / цель,
а платишь за ноды под requests. 6 / 0,5 = 12 ядер; 6 / 0,75 = 8 ядер (−33%).

</details>

**A3.** Как `minReplicas` влияет на счёт? Какие значения разумны для prod и non-prod?

<details><summary>Ответ</summary>

Пол оплачивается 24/7 при любом трафике. Prod — не меньше 2 (отказоустойчивость, PDB),
для критичных — 3 по зонам; stage/dev — 1, а вне рабочих часов — 0 через KEDA/downscaler.

</details>

**A4.** Какие сочетания VPA и HPA допустимы, а какие нет?

<details><summary>Ответ</summary>

Нельзя: HPA по CPU + VPA, меняющий CPU. Можно: HPA по CPU + VPA только на память;
HPA по прикладной метрике + VPA на CPU/память; любой HPA + VPA `Off`.

</details>

**A5.** Что KEDA делает сама, а что — через HPA?

<details><summary>Ответ</summary>

Сама: активация 0 → 1 и деактивация 1 → 0, опрос источников, адаптер метрик.
Скейлинг 1 ↔ N — через созданный ею HPA `keda-hpa-&lt;имя&gt;`.

</details>

**A6.** Что такое `activationThreshold` и `cooldownPeriod`? На что `cooldownPeriod` не влияет?

<details><summary>Ответ</summary>

`activationThreshold` — порог, выше которого KEDA «будит» workload с нуля (отдельно от
`threshold` для 1 → N). `cooldownPeriod` — сколько ждать после последней активности перед
переходом в 0 (дефолт 300 с). На уменьшение N → 1 он не влияет — это `behavior` HPA.

</details>

**A7.** Prometheus-триггер KEDA с `threshold: "50"`, запрос вернул 430. Сколько реплик захочет KEDA?

<details><summary>Ответ</summary>

По умолчанию метрика AverageValue: ⌈430 / 50⌉ = ⌈8,6⌉ = 9 реплик (в пределах min/max).

</details>

**A8.** Почему scale to zero плохо подходит HTTP-сервису? Что с этим делать?

<details><summary>Ответ</summary>

Первый запрос после нуля попадает в холодный старт (нода, pull образа, старт приложения)
и либо ждёт десятки секунд, либо падает, потому что подов нет. Варианты: `minReplicaCount: 1`,
KEDA HTTP add-on (прокси буферизует запросы и будит сервис), scale to zero только в dev.

</details>

**A9.** ⭐ Чем Cluster Autoscaler отличается от Karpenter?

<details><summary>Ответ</summary>

CA увеличивает/уменьшает группы нод заранее выбранного типа; Karpenter подбирает
тип инстанса под конкретные Pending-поды за секунды, нативно работает со spot и активно
консолидирует (заменяет недогруженные ноды дешевле). CA — почти у всех провайдеров,
Karpenter — AWS и Azure.

</details>

**A10.** Что описывают NodePool и EC2NodeClass? Какие у них `apiVersion`?

<details><summary>Ответ</summary>

NodePool (`karpenter.sh/v1`) — какие ноды можно создавать: requirements (типы, архитектуры,
зоны, spot/on-demand), taints, `expireAfter`, limits, disruption. EC2NodeClass
(`karpenter.k8s.aws/v1`) — облачные детали: AMI, подсети, security groups, IAM-роль.

</details>

**A11.** Назови три политики consolidation Karpenter и чем они отличаются.

<details><summary>Ответ</summary>

`WhenEmpty` — удаляет только пустые ноды; `WhenEmptyOrUnderutilized` — ещё и
перекладывает поды с недогруженных нод и заменяет ноды дешёвыми (максимум экономии,
больше рестартов); `Balanced` — выполняет действие, только если экономия достаточно велика
относительно вызванных выселений.

</details>

**A12.** Зачем в NodePool `limits` и disruption budgets? В какой таймзоне их `schedule`?

<details><summary>Ответ</summary>

`limits` — потолок суммарных CPU/памяти нод пула: защита от «скейлинга в бесконечность»
из-за бага или атаки. Budgets ограничивают, сколько нод можно одновременно выселять
добровольно, в том числе по расписанию и по причине. `schedule` — cron в UTC.

</details>

**A13.** Сколько длится предупреждение о прерывании spot у AWS, GCP, Azure? Что особенного
у прерываемых ВМ Yandex Cloud?

<details><summary>Ответ</summary>

AWS — 2 минуты (плюс более ранний rebalance recommendation), GCP и Azure — около

</details>

**A14.** Какие нагрузки подходят для spot, а какие — нет?

<details><summary>Ответ</summary>

Подходят: stateless с несколькими репликами, CI-раннеры, батчи, ETL, dev/stage.
С оговорками: воркеры очередей (идемпотентность), долгие батчи с чекпойнтами. Не подходят:
БД и брокеры с одной репликой, stateful с локальными дисками, единственные экземпляры.

</details>

**A15.** Защищает ли PodDisruptionBudget от прерывания spot?

<details><summary>Ответ</summary>

Нет. PDB ограничивает только добровольные выселения (drain, consolidation). Прерывание
spot — недобровольное; от него защищают запас реплик, распределение по капасити и зонам,
быстрый graceful shutdown.

</details>

**A16.** ⭐ Сколько экономит выключение dev вне рабочих часов (пн–пт 09:00–20:00)? При каком условии?

<details><summary>Ответ</summary>

55 из 168 часов — 33% времени, экономия ~67% compute окружения. Условие: вместе
с подами должны уйти ноды (автоскейлер нод, минимум группы 0 или маленький).

</details>

**A17.** Много маленьких нод или несколько больших — плюсы и минусы для денег и надёжности.

<details><summary>Ответ</summary>

Маленькие: мелкий шаг скейлинга, малый blast radius, больше вариантов spot, но
большие накладные DaemonSet/reserved, лимит подов/IP, крупные поды не влезают. Большие:
меньше накладных, лучше упаковка, но крупный шаг скейлинга и большой blast radius.
Практика — 4–16 vCPU, 3+ ноды в пуле.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  # для Deployment shop-api в namespace shop есть:
```text
<details><summary>Ответ</summary>

⚠️ KEDA создаёт свой HPA — на Deployment два HPA, они перетягивают `replicas`
(вебхук KEDA такой ScaledObject отклонит). Удалить ручной HPA, CPU добавить вторым
триггером (`type: cpu`) в ScaledObject.

</details>

```text:no-line-numbers
     kind: HorizontalPodAutoscaler   (CPU 70%)
```text
```text:no-line-numbers
     kind: ScaledObject              (prometheus, RPS)
```text
```text:no-line-numbers
B2.  # хотим ноль реплик ночью
```text
<details><summary>Ответ</summary>

⚠️ `desiredReplicas: "0"` — «почти всегда ошибка» по документации KEDA, а окно
«через полночь» с `start > end` запутывает логику. Правильно: окно рабочего времени
`start: 0 9 * * 1-5`, `end: 0 20 * * 1-5`, `desiredReplicas: "2"`, `minReplicaCount: 0`.

</details>

```text:no-line-numbers
     triggers:
```text
```text:no-line-numbers
       - type: cron
```text
```text:no-line-numbers
         metadata: { timezone: Asia/Almaty, start: 0 20 * * *, end: 0 9 * * *, desiredReplicas: "0" }
```text
```text:no-line-numbers
B3.  # Karpenter NodePool
```text
<details><summary>Ответ</summary>

⚠️ `schedule` в UTC: `0 9` — это 14:00 по Алматы (UTC+5), защита сработает не в те часы;
нужно `0 4 * * mon-fri`. Без `limits` любой баг (зацикленный HPA, огромный request) закажет
сотни нод. Budget без `reasons` блокирует и удаление пустых нод — лучше `reasons: [Underutilized]`.

</details>

```text:no-line-numbers
     disruption:
```text
```text:no-line-numbers
       consolidationPolicy: WhenEmptyOrUnderutilized
```text
```text:no-line-numbers
       budgets: [{ nodes: "0", schedule: "0 9 * * mon-fri", duration: 11h }]   # «рабочие часы Алматы»
```text
```text:no-line-numbers
     # limits не заданы
```text
```text:no-line-numbers
B4.  # stage
```text
<details><summary>Ответ</summary>

⚠️ Пол 5 реплик в stage 24/7 и потолок 6 — HPA почти ничего не решает, а платишь за 5
круглосуточно. Stage: `minReplicas: 1`, ночью — 0.

</details>

```text:no-line-numbers
     HPA: minReplicas: 5, maxReplicas: 6, target CPU 50%
```text
```text:no-line-numbers
B5.  # prod, Karpenter consolidation включена
```text
<details><summary>Ответ</summary>

⚠️ `minAvailable` = числу реплик → `ALLOWED DISRUPTIONS: 0`: consolidation и drain
никогда не смогут выселить эти поды — ноды не консолидируются, обновления нод зависнут.
`maxUnavailable: 1`.

</details>

```text:no-line-numbers
     PodDisruptionBudget: minAvailable: 3   # у Deployment ровно 3 реплики
```text
```text:no-line-numbers
B6.  # воркер обрабатывает задачу 10 минут; KEDA ScaledObject minReplicaCount: 0, cooldownPeriod: 60
```text
<details><summary>Ответ</summary>

⚠️ Когда очередь опустеет, KEDA через 60 с уберёт поды посреди 10-минутных задач
(scale down в HPA тоже не знает о задачах). Нужен `ScaledJob` (Job на сообщение/пачку) или
длинный graceful shutdown с завершением задачи, ack после обработки и идемпотентность.

</details>

```text:no-line-numbers
B7.  # spot-ноды с taint spot=true:NoSchedule; Deployment с toleration на spot,
```text
<details><summary>Ответ</summary>

⚠️ Toleration только разрешает попасть на ноду с taint, но не притягивает. Нужна
nodeAffinity (preferred/required) к spot-пулу.

</details>

```text:no-line-numbers
     # но без nodeAffinity. «Почему поды всё равно на on-demand?»
```text
```text:no-line-numbers
B8.  # поды на AWS spot
```text
<details><summary>Ответ</summary>

⚠️ Предупреждение AWS — 2 минуты: через 120 с инстанс выключат, и 300 с grace никто
не дождётся — процесс убьют посреди работы. Grace ≤ 60–90 с, быстрый выход по SIGTERM.

</details>

```text:no-line-numbers
     terminationGracePeriodSeconds: 300
```text
```text:no-line-numbers
B9.  # в общем Helm-шаблоне компании у всех подов
```text
<details><summary>Ответ</summary>

⚠️ Autoscaler не может удалить ни одну ноду с такими подами — scale down фактически
выключен для всего кластера. Аннотацию ставят точечно (например, долгий Job).

</details>

```text:no-line-numbers
     annotations: { cluster-autoscaler.kubernetes.io/safe-to-evict: "false" }
```text
```text:no-line-numbers
B10.  # KEDA prometheus-триггер без fallback; Prometheus лёг на 40 минут
```text
<details><summary>Ответ</summary>

⚠️ Без `fallback` при ошибке источника скейлинг замирает на текущем числе реплик
(или — у скейлеров при нуле — не будет активации). Задать `fallback: {failureThreshold: 3,
replicas: N}` и алерт на доступность Prometheus.

</details>

```text:no-line-numbers
B11.  # dev-namespace погашен kube-downscaler'ом в 20:00, но нод в группе всё ещё 3 — min size = 3
```text
<details><summary>Ответ</summary>

⚠️ Поды ушли, но min size группы держит 3 ноды — экономии почти нет. Min size 0–1
для dev-группы (или Karpenter), базы — в отдельной маленькой группе.

</details>

```text:no-line-numbers
B12.  # «для надёжности» HPA target CPU 30%
```text
<details><summary>Ответ</summary>

⚠️ Платишь за 3,3× потребления. Надёжность дают быстрый скейлинг, запас по нодам
и корректные probes, а не низкая цель. 60–75%.

</details>


---

### Блок C. Практика


### C1. 🔑 Цена цели HPA (расчёт)
Сервис: 16 ч в сутки потребляет 4 ядра, 8 ч (пик) — 10 ядер. Request одного пода — 500m,
HPA держит цель точно, ноды следуют за подами. 1 vCPU·час = $0,04, месяц = 30 дней.
Посчитай месячную стоимость requests при цели 50% и 70% и экономию.

### C2. 🔑 KEDA по метрике Prometheus
**1.** Поставь KEDA. Для `podinfo` из `demo` создай ServiceMonitor (порт 9898, путь `/metrics`)
   и найди в метриках counter запросов (`curl …:9898/metrics | grep _count`).

<details><summary>Ответ</summary>

```text
Цель 50%: база 4 / 0,5 = 8 ядер (16 подов) × 16 ч = 128 vCPU·ч
          пик 10 / 0,5 = 20 ядер (40 подов) × 8 ч = 160 vCPU·ч      → 288 vCPU·ч/сутки
Цель 70%: база 4 / 0,7 = 5,71 → ⌈11,4⌉ = 12 подов = 6 ядер × 16 ч = 96
          пик 10 / 0,7 = 14,29 → ⌈28,6⌉ = 29 подов = 14,5 ядра × 8 ч = 116  → 212 vCPU·ч/сутки
Месяц: 288 × 30 × $0,04 = $345,6;  212 × 30 × $0,04 = $254,4
Экономия ≈ $91/мес (−26%) на одном сервисе — без изменения кода.
```text
</details>

**2.** Создай ScaledObject с prometheus-триггером: 1 реплика на 5 RPS, `minReplicaCount: 1`,
   `maxReplicaCount: 6`.

<details><summary>Ответ</summary>

-vCPU: полезно 1,9 − 0,4 = 1,5 → под на 3 vCPU не влезает вообще ❌ (нужен второй пул).

</details>

**3.** Дай нагрузку циклом `wget`, смотри `kubectl get hpa,pods -n demo -w`. Найди HPA,
   который создала KEDA, и объясни его `TARGETS`.

<details><summary>Ответ</summary>

Реплики поднимаются в пределах `pollingInterval` (30 с) после `start`. После `end`
до нуля — ~`cooldownPeriod` (300 с) + интервал опроса. Если нужно быстрее — уменьшить
`cooldownPeriod`.

</details>

### C3. 🔑 Dev спит ночью (KEDA cron)
**1.** Создай namespace `dev` с двумя Deployment.

<details><summary>Ответ</summary>

```text
Цель 50%: база 4 / 0,5 = 8 ядер (16 подов) × 16 ч = 128 vCPU·ч
          пик 10 / 0,5 = 20 ядер (40 подов) × 8 ч = 160 vCPU·ч      → 288 vCPU·ч/сутки
Цель 70%: база 4 / 0,7 = 5,71 → ⌈11,4⌉ = 12 подов = 6 ядер × 16 ч = 96
          пик 10 / 0,7 = 14,29 → ⌈28,6⌉ = 29 подов = 14,5 ядра × 8 ч = 116  → 212 vCPU·ч/сутки
Месяц: 288 × 30 × $0,04 = $345,6;  212 × 30 × $0,04 = $254,4
Экономия ≈ $91/мес (−26%) на одном сервисе — без изменения кода.
```text
</details>

**2.** Повесь на каждый ScaledObject с cron-триггером, где окно — ближайшие 10 минут
   (`timezone: Asia/Almaty`), `minReplicaCount: 0`.

<details><summary>Ответ</summary>

-vCPU: полезно 1,9 − 0,4 = 1,5 → под на 3 vCPU не влезает вообще ❌ (нужен второй пул).

</details>

**3.** Зафиксируй: когда поднялись реплики, через сколько после `end` стало 0. Сравни с `cooldownPeriod`.

<details><summary>Ответ</summary>

Реплики поднимаются в пределах `pollingInterval` (30 с) после `start`. После `end`
до нуля — ~`cooldownPeriod` (300 с) + интервал опроса. Если нужно быстрее — уменьшить
`cooldownPeriod`.

</details>

### C4. kube-downscaler для всего namespace
Поставь GoKubeDownscaler, повесь `downscaler/uptime` на namespace `dev2` с окном, которое
закончится через 5 минут. Исключи один Deployment аннотацией `downscaler/exclude`.
Сравни с KEDA cron: что удобнее для 30 сервисов и почему?

### C5. Очередь и scale to zero (по желанию)
**1.** Разверни `rabbitmq:4-management` (Deployment + Service, `RABBITMQ_DEFAULT_USER/PASS=keda/keda`),
   Secret с `url: amqp://keda:keda@rabbitmq.orders:5672/`.

<details><summary>Ответ</summary>

```text
Цель 50%: база 4 / 0,5 = 8 ядер (16 подов) × 16 ч = 128 vCPU·ч
          пик 10 / 0,5 = 20 ядер (40 подов) × 8 ч = 160 vCPU·ч      → 288 vCPU·ч/сутки
Цель 70%: база 4 / 0,7 = 5,71 → ⌈11,4⌉ = 12 подов = 6 ядер × 16 ч = 96
          пик 10 / 0,7 = 14,29 → ⌈28,6⌉ = 29 подов = 14,5 ядра × 8 ч = 116  → 212 vCPU·ч/сутки
Месяц: 288 × 30 × $0,04 = $345,6;  212 × 30 × $0,04 = $254,4
Экономия ≈ $91/мес (−26%) на одном сервисе — без изменения кода.
```text
</details>

**2.** Создай очередь и сообщения через HTTP API (port-forward 15672):
   `curl -u keda:keda -XPUT localhost:15672/api/queues/%2F/orders -H 'content-type: application/json' -d '{"durable":true}'`,
   публикация — `POST /api/exchanges/%2F/amq.default/publish` с `routing_key: orders`.

<details><summary>Ответ</summary>

-vCPU: полезно 1,9 − 0,4 = 1,5 → под на 3 vCPU не влезает вообще ❌ (нужен второй пул).

</details>

**3.** Воркер — любой Deployment (`busybox sleep infinity`): скейлинг зависит только от длины очереди.
   ScaledObject из конспекта с `value: "20"`. Опубликуй 100 сообщений, потом очисти очередь
   (`DELETE /api/queues/%2F/orders/contents`). Наблюдай 0 → 5 → 0.

<details><summary>Ответ</summary>

Реплики поднимаются в пределах `pollingInterval` (30 с) после `start`. После `end`
до нуля — ~`cooldownPeriod` (300 с) + интервал опроса. Если нужно быстрее — уменьшить
`cooldownPeriod`.

</details>

### C6. Karpenter на бумаге
Напиши два NodePool: `general` (spot + on-demand, arm64/amd64, c/m/r, поколение > 5,
лимит 100 vCPU, consolidation без трогания недогруженных нод в рабочие часы Алматы 10:00–19:00
пн–пт) и `batch` (только spot, taint `workload=batch:NoSchedule`, `WhenEmpty`, лимит 50 vCPU).
Проверь cron budgets в UTC.

### C7. Готов ли сервис к spot
Найди проблемы и исправь:
```text:no-line-numbers
spec:
```text
```text:no-line-numbers
  replicas: 1
```text
```text:no-line-numbers
  template:
```text
```text:no-line-numbers
    spec:
```text
```text:no-line-numbers
      terminationGracePeriodSeconds: 300
```text
```text:no-line-numbers
      containers:
```text
```text:no-line-numbers
        - name: api
```text
```text:no-line-numbers
          image: shop-api:2.3
```text
```text:no-line-numbers
          volumeMounts: [{ name: cache, mountPath: /cache }]    # тёплый кэш 20 ГБ, греется 15 минут
```text
```text:no-line-numbers
      volumes: [{ name: cache, emptyDir: {} }]
```text
```text:no-line-numbers
# PDB нет, readinessProbe нет, все поды на spot одного типа в одной зоне
```text
### C8. Размер нод (расчёт)
Поды: 30 × 0,5 vCPU и 2 × 3 vCPU. DaemonSet'ы — 0,4 vCPU на ноду. Allocatable: 2-vCPU нода —
**1.** ,9; 4-vCPU — 3,8; 8-vCPU — 7,8. Сколько нод каждого размера нужно и сколько vCPU оплачивается?
Какой вариант выгоднее?

<details><summary>Ответ</summary>

```text
Цель 50%: база 4 / 0,5 = 8 ядер (16 подов) × 16 ч = 128 vCPU·ч
          пик 10 / 0,5 = 20 ядер (40 подов) × 8 ч = 160 vCPU·ч      → 288 vCPU·ч/сутки
Цель 70%: база 4 / 0,7 = 5,71 → ⌈11,4⌉ = 12 подов = 6 ядер × 16 ч = 96
          пик 10 / 0,7 = 14,29 → ⌈28,6⌉ = 29 подов = 14,5 ядра × 8 ч = 116  → 212 vCPU·ч/сутки
Месяц: 288 × 30 × $0,04 = $345,6;  212 × 30 × $0,04 = $254,4
Экономия ≈ $91/мес (−26%) на одном сервисе — без изменения кода.
```text
</details>

### C9. 🔑 Экономия от расписания (расчёт)
Dev-кластер: 12 нод по $146/мес, из них 2 ноды — базы, которые работают 24/7.
Окно: пн–пт 08:30–20:00. Посчитай стоимость до и после и экономию в месяц.

---

### Блок D. Инциденты


**D1.** За ночь Karpenter создал 80 нод, утром — алерт бюджета. Как разбираешься
и что добавить, чтобы не повторилось?

<details><summary>Ответ</summary>

`kubectl get nodeclaims`, события Karpenter (`kubectl -n kube-system logs deploy/karpenter`
или namespace установки): какие поды вызвали создание. Типичные причины: HPA упёрся в огромный
`maxReplicas` из-за сломанной метрики, под с гигантскими requests, поды не планируются
(affinity/volume в другой зоне) и Karpenter снова и снова создаёт ноды, DaemonSet с большими
requests. Остановить: уменьшить реплики/удалить виновника, consolidation удалит пустые ноды.
Профилактика: `limits` в NodePool, разумные `maxReplicas`, ResourceQuota, бюджет и алерт
на число нод (`count(kube_node_info)`).

</details>

**D2.** После включения `WhenEmptyOrUnderutilized` каждые ~15 минут — всплески 5xx.

<details><summary>Ответ</summary>

Consolidation перекладывает поды, а сервис плохо переносит выселение: одна реплика
или PDB отсутствует, медленная readiness, нет graceful shutdown. Исправить: PDB
`maxUnavailable: 1`, несколько реплик, корректные readiness/preStop, budgets на рабочие часы,
политику `Balanced` или `consolidateAfter` подлиннее, `do-not-disrupt` для хрупких задач.

</details>

**D3.** Сервис полностью лёг на 3 минуты: одновременно прервались все его spot-ноды.

<details><summary>Ответ</summary>

Все реплики на одном типе инстанса/зоне — прерывание пришло всем сразу. Разнести
по капасити (часть on-demand), зонам и нескольким типам (Karpenter с широкими requirements),
держать запас реплик, быстрый graceful shutdown, обработку уведомлений о прерывании.

</details>

**D4.** Dev-окружение «просыпается» в 08:00 вместо 09:00 по Алматы, хотя в ScaledObject
`timezone: Asia/Almaty`, `start: 0 9 * * 1-5`.

<details><summary>Ответ</summary>

Устаревшая база часовых поясов: с 1 марта 2024 Казахстан перешёл на единое время UTC+5
(tzdata 2024a), а в образе KEDA/ноды старая tzdata считает Asia/Almaty = UTC+6 — окно сдвинулось
на час. Обновить KEDA (образ со свежей tzdata) или временно указать `timezone: Asia/Aqtobe`
(всегда UTC+5)/UTC-выражение.

</details>

**D5.** Воркер на KEDA с нулём реплик: сообщения копятся по 5 минут, прежде чем появляется первый под.

<details><summary>Ответ</summary>

Долгий `pollingInterval` (например, 300 с) — KEDA редко проверяет очередь; или
`activationValue` слишком высокий; плюс холодный старт ноды. Уменьшить `pollingInterval`
до 10–30 с, `activationValue: "0"`, держать небольшой тёплый запас нод или `minReplicaCount: 1`
в часы активности (второй триггер cron).

</details>

**D6.** Ночью трафика нет, а HPA держит 6 реплик.

<details><summary>Ответ</summary>

`minReplicas: 6`; метрика — память, которая не освобождается; окно стабилизации
огромное; метрика не падает (фоновые задачи жгут CPU); у KEDA сработал `fallback` из-за
недоступного источника. Проверить `kubectl describe hpa` (условия и текущие значения).

</details>

**D7.** Cluster Autoscaler для обычного веб-пода поднял ноду из дорогой GPU-группы.

<details><summary>Ответ</summary>

Expander `random` выбрал GPU-группу, на её нодах нет taint — поды туда проходят.
Повесить taint `nvidia.com/gpu=true:NoSchedule` на GPU-ноды (toleration только у GPU-подов),
expander `priority` или `least-waste`, min size GPU-группы 0.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как автоскейлинг помогает экономить и почему иногда не помогает?

<details><summary>Ответ</summary>

Автоскейлинг подгоняет мощности под нагрузку: реплики (HPA/KEDA), ноды (CA/Karpenter),
   время (расписания). Не помогает, если ноды не уходят за подами, пол и цель заданы
   «с запасом», или узкое место — в БД.

</details>

**2.** Какую цель утилизации ставишь в HPA и почему?

<details><summary>Ответ</summary>

60–75% для веба: стоимость ≈ потребление / цель; выше — дешевле, но нужен быстрый скейлинг
   и запас нод; ниже — платишь за воздух.

</details>

**3.** Что такое KEDA и чем она отличается от HPA?

<details><summary>Ответ</summary>

Оператор, который скейлит по событиям (очереди, Prometheus, cron, 70+ источников) и умеет

</details>

**4.** Cluster Autoscaler или Karpenter?

<details><summary>Ответ</summary>

На AWS/Azure — Karpenter: быстрее, подбирает дешёвый тип, consolidation, нативный spot.
   В других облаках и on-prem — Cluster Autoscaler / автоскейлинг node pool провайдера.

</details>

**5.** Что такое consolidation в Karpenter и как не сломать ею прод?

<details><summary>Ответ</summary>

Постоянный поиск, как переложить поды на меньше/дешевле нод. Не сломать: PDB и несколько
   реплик, disruption budgets по расписанию (UTC), `Balanced` для чувствительных пулов,
   `do-not-disrupt` для хрупких задач, корректный graceful shutdown.

</details>

**6.** Как безопасно использовать spot в Kubernetes?

<details><summary>Ответ</summary>

Только отказоустойчивое: 3+ реплики, spread по капасити и зонам, часть на on-demand,
   grace короче предупреждения, обработка уведомлений, диверсификация типов, stateful — не на spot.

</details>

**7.** Как выключать dev-окружения на ночь?

<details><summary>Ответ</summary>

KEDA cron на workload или kube-downscaler аннотацией на namespace, вместе с автоскейлером
   нод; исключения для «нужен в субботу»; базы — отдельно; утренний подъём заранее.

</details>

**8.** VPA и HPA вместе — можно?

<details><summary>Ответ</summary>

Нельзя по одному ресурсу (CPU): петля. Можно HPA по CPU + VPA на память или VPA `Off`.

</details>

**9.** Почему поды удалились, а ноды остались?

<details><summary>Ответ</summary>

Scale down нод заблокирован (PDB, `safe-to-evict`, локальные тома, min size),
   поды размазаны по нодам, нет consolidation.

</details>

**10.** Большие ноды или маленькие?

<details><summary>Ответ</summary>

Компромисс: большие — меньше накладных и лучше упаковка, маленькие — мелкий шаг и меньший
    blast radius. Обычно 4–16 vCPU, 3+ ноды; Karpenter выбирает сам.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Объясняю цепочку «поды → ноды → деньги» и где она рвётся
- [ ] ⭐ Считаю стоимость сервиса под HPA от цели утилизации
- [ ] Знаю допустимые сочетания VPA и HPA
- [ ] Настроил KEDA: prometheus-триггер и scale to zero; понимаю `threshold`, `activationThreshold`, `cooldownPeriod`
- [ ] Dev-namespace гаснет и поднимается по расписанию (KEDA cron или downscaler)
- [ ] Объясняю CA против Karpenter, пишу NodePool с limits, consolidation и budgets (UTC)
- [ ] Знаю, какие нагрузки можно на spot и как переживать прерывания
- [ ] Считаю экономию от расписания и выбираю размер нод с учётом DaemonSet
