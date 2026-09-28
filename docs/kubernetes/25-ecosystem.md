---
title: "25. Экосистема вокруг кластера"
description: "external-dns, Helm-чарты в OCI, Helm 4, helmfile, KEDA (scale to zero), Karpenter, Reloader"
---

# 25. Экосистема вокруг кластера: external-dns, Helm OCI и Helm 4, helmfile, KEDA, Karpenter, Reloader

> Вне роадмапа — инструменты, которые встречаются почти в каждом рабочем кластере
> и в вакансиях рядом со словом Kubernetes. Вопросы собеса: *«Как у вас появляются
> DNS-записи?»*, *«Где вы храните чарты?»*, *«Как скейлить воркеры очереди до нуля?»*
> **После темы ты умеешь:** объяснить, какую задачу решает каждый инструмент, написать
> для него рабочий манифест, поднять KEDA в kind со scale to zero и перевести CI на Helm 4.
> Версии — «проверь, сентябрь 2026».

---

## 🗺️ Карта темы

```text:no-line-numbers
                          git: чарты, values, helmfile / ArgoCD Application
                                   │
              OCI-реестр (GHCR, Harbor, ECR) ◄── helm push     helm 4 / helmfile apply
                                   │                                  │
                                   ▼                                  ▼
  ┌─────────────────────────────────── КЛАСТЕР ───────────────────────────────────┐
  │  Gateway / Service ──► external-dns ──► DNS-провайдер (Route 53, Cloudflare)  │
  │  ConfigMap/Secret изменился ──► Reloader ──► rollout подов                    │
  │  очередь / Prometheus / cron ──► KEDA ──► HPA ──► реплики (в т.ч. 0 ↔ 1)      │
  │  поды Pending ──► Karpenter ──► новая нода нужного типа (или consolidation)   │
  └───────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Какую задачу решает что

| Задача | Инструмент | Альтернатива | Где |
|--------|------------|--------------|-----|
| DNS-записи для Service/Ingress/Gateway без ручных правок | **external-dns** | Terraform-ресурсы DNS, записи руками | §2 |
| Хранить и раздавать чарты с правами и подписью | **OCI-реестр** (GHCR, Harbor, ECR) | Классический репозиторий с `index.yaml` | §3 |
| Деплой чартов из CLI и CI | **Helm 4** (Helm 3 — до 10.02.2027) | Kustomize | §4, тема 15 |
| Описать десятки релизов по окружениям одним файлом | **helmfile** | Umbrella-чарт, ArgoCD ApplicationSet | §5 |
| Непрерывная сверка кластера с git | ArgoCD / Flux | helmfile в CI (push) | тема 21 |
| Скейлинг по очереди, метрике или расписанию, **до нуля** | **KEDA** | HPA + prometheus-adapter (без нуля) | §6, тема 18 |
| Быстро и дёшево добавлять ноды под поды | **Karpenter** | Cluster Autoscaler | §7 |
| Перекатить поды при смене ConfigMap/Secret | **Reloader** | checksum-аннотация в Helm, `configMapGenerator` | §8 |

---

## 2. external-dns — DNS из объектов кластера

**Проблема:** запись `shop.example.com` завели руками, адрес балансировщика сменился — сайт лежит.
**Решение:** external-dns (kubernetes-sigs; **v0.23.0 — 18.09.2026**) держит записи у DNS-провайдера
в соответствии с объектами кластера.

```text:no-line-numbers
 HTTPRoute (hostnames: shop.example.com) ──parentRefs──► Gateway (status.addresses: 203.0.113.10)
                          │
                          ▼ раз в --interval (1m)
                    external-dns ──► Route 53: shop.example.com A 203.0.113.10
                                              + TXT «владелец = cluster-blue»
```

### Источники (`--source`)

| Источник | Имя берётся из | Адрес берётся из |
|----------|----------------|------------------|
| `service` | Аннотация `external-dns.kubernetes.io/hostname` | IP/hostname LoadBalancer (ClusterIP — только с `--publish-internal-services`) |
| `ingress` | `spec.rules[].host` | `status.loadBalancer` Ingress |
| ⭐ `gateway-httproute`, `gateway-grpcroute`, `gateway-tlsroute` | `spec.hostnames` маршрута (или hostname listener'а) | `status.addresses` Gateway, к которому привязан маршрут |
| `gateway-tcproute`, `gateway-udproute` | Только аннотация `hostname` (своих hostnames у них нет) | `status.addresses` Gateway |
| `crd` | Объект `DNSEndpoint` — запись «как есть» | Задаёшь сам |

Фильтры для Gateway: `--gateway-name`, `--gateway-namespace`, `--gateway-label-filter`.
Для зон: `--domain-filter=example.com` — ⭐ всегда ограничивай, чтобы не трогать чужие зоны.

### Провайдеры

In-tree: `aws` (Route 53), `google`, `azure`, `cloudflare`, `rfc2136` (BIND), `coredns`,
`pdns`, `oci`, `ovh`, `scaleway` и др.; остальные — через **`webhook`** (отдельный контейнер-адаптер).
v0.22 убрала из дерева Akamai, Plural, Transip, v0.23 — Gandi. Для Yandex Cloud DNS in-tree
провайдера нет: webhook-провайдеры сообщества или записи через Terraform (проверь).

### ⭐ Владение записями: TXT registry и policy

external-dns не трогает записи, которые создал **не он**. Рядом с каждой записью он кладёт
TXT с меткой владельца `--txt-owner-id` (с v0.22 есть и registry `crd` — владение в объектах
кластера). Два кластера с одним owner-id перетирают записи друг друга — в blue/green они **разные**.

| `--policy` (⚠️ с v0.22 обязателен, дефолта нет) | Что разрешено |
|---------------------|---------------|
| `sync` | Создавать, обновлять и **удалять** свои записи |
| `upsert-only` | Создавать и обновлять, никогда не удалять — ⭐ безопасный старт |
| `create-only` | Только создавать |

> ⚠️ **v0.22 — ломающие изменения.** Префикс аннотаций по умолчанию сменился
> с `external-dns.alpha.kubernetes.io/` на `external-dns.kubernetes.io/` **без запасного
> варианта** — со старыми аннотациями и `policy: sync` можно **удалить все записи**.
> Перед обновлением: `--dry-run=true`, миграция аннотаций или флаг
> `--enable-legacy-annotation-prefix` (v0.23). В старых гайдах — старый префикс.

### Манифесты (AWS Route 53 + Gateway API)

```yaml
# values-external-dns.yaml — чарт external-dns/external-dns (1.22.0)
provider: { name: aws }
sources: [service, gateway-httproute, gateway-grpcroute]
domainFilters: [example.com]
policy: upsert-only               # после проверки — sync
registry: txt
txtOwnerId: prod-blue             # уникален для каждого кластера
serviceAccount:
  name: external-dns              # права на Route 53 — через EKS Pod Identity, без ключей
```

```bash
helm repo add external-dns https://kubernetes-sigs.github.io/external-dns/
helm upgrade --install external-dns external-dns/external-dns \
  -n external-dns --create-namespace -f values-external-dns.yaml
kubectl -n external-dns logs deploy/external-dns | grep -i -E "change|desired"
```

```yaml
# Service: имя и TTL — аннотациями (новый префикс!)
metadata:
  annotations:
    external-dns.kubernetes.io/hostname: api.example.com
    external-dns.kubernetes.io/ttl: "60"
# HTTPRoute: имя берётся из spec.hostnames — аннотации не нужны
spec:
  parentRefs: [{ name: web, namespace: infra }]
  hostnames: ["shop.example.com"]
```

IAM для Route 53 и Pod Identity — в разделе про облака.

> ⚠️ **В kind полноценно не запустить:** нужен реальный DNS-провайдер и балансировщик,
> чтобы у Gateway появился `status.addresses`. Для знакомства — `--provider=inmemory
> --inmemory-zone=example.org --source=service --publish-internal-services --policy=sync
> --log-level=debug`: записи живут в памяти процесса, по логам видно план изменений,
> но резолвить их нельзя. Настоящая проверка — облачная зона с бюджетом и уборкой.

---

## 3. Helm-чарты в OCI-реестрах

Чарт — такой же артефакт, как образ: его кладут **в тот же реестр** (GHCR, Harbor, ECR,
Yandex Container Registry), с теми же правами, сканированием и подписью. Отдельный
сервер с `index.yaml` больше не нужен.

```bash
helm package ./chart                                  # → web-0.3.0.tgz (версия из Chart.yaml)

# GHCR: токен с правом write:packages
echo "$GHCR_TOKEN" | helm registry login ghcr.io -u "$GH_USER" --password-stdin
helm push web-0.3.0.tgz oci://ghcr.io/$GH_USER/charts   # → ghcr.io/<user>/charts/web:0.3.0
helm push web-0.3.0.tgz oci://harbor.example.com/platform   # Harbor: проект = путь

# потребление — без helm repo add
helm show values oci://ghcr.io/$GH_USER/charts/web --version 0.3.0
helm pull        oci://ghcr.io/$GH_USER/charts/web --version 0.3.0
helm upgrade --install web oci://ghcr.io/$GH_USER/charts/web --version 0.3.0 -n prod

# Helm 4: установка по digest — неизменяемая ссылка
helm install web oci://ghcr.io/$GH_USER/charts/web@sha256:<digest>

# учебно, без аккаунта: локальный реестр
docker run -d -p 5001:5000 --name registry registry:2
helm push web-0.3.0.tgz oci://localhost:5001/charts --plain-http
```

Зависимость из OCI в `Chart.yaml` — `repository: oci://ghcr.io/my-org/charts` (без `helm repo add`).

### OCI-чарт в ArgoCD

```yaml
# вариант 1 — Helm-репозиторий типа OCI: repoURL БЕЗ oci://, имя чарта в chart
spec:
  source:
    repoURL: ghcr.io/my-org/charts
    chart: web
    targetRevision: 0.3.0
    helm: { valueFiles: [values-prod.yaml] }
# креды: Secret с label argocd.argoproj.io/secret-type=repository, type: helm, enableOCI: "true"
---
# вариант 2 — нативный OCI-источник (ArgoCD 3.1+, проверь): repoURL С oci://
spec:
  source:
    repoURL: oci://ghcr.io/my-org/charts/web
    targetRevision: 0.3.0
    path: .
```

| Грабля | Суть |
|--------|------|
| `helm repo add oci://…` | Не работает: OCI-реестры не «добавляют», к ним обращаются по полному пути |
| Тег образа ≠ версия чарта | Тег артефакта = `version` из Chart.yaml (semver); `appVersion` — отдельно |
| Перезапись версии | Реестр может разрешать перезаливку тега — в проде включай иммутабельность тегов |

---

## 4. ⭐ Helm 4 против Helm 3

**Helm 4.0.0** вышел 12.11.2025, актуальная — **4.3.0** (09.09.2026). **Helm 3.22.0**
(10.09.2026) — последняя минорная Helm 3, security-фиксы до **10.02.2027** (проверь).
Чарты `apiVersion: v2` работают без изменений; чарты v3 — экспериментально (`HELM_EXPERIMENTAL_CHART_V3=1`).

| Что изменилось | Helm 3 | Helm 4 |
|----------------|--------|--------|
| Применение манифестов | Client-side 3-way merge | ⭐ **Server-side apply** для новых установок; релизы из Helm 3 остаются на client-side (переключение — `--server-side`) |
| Откат при неудаче | `--atomic` | **`--rollback-on-failure`** |
| Пересоздание ресурсов | `--force` | **`--force-replace`** |
| Ожидание готовности | Свой код `--wait` | На основе **kstatus** — точнее понимает статус ресурсов |
| Плагины | Бинарники/скрипты | Новая система, **WebAssembly**-плагины в песочнице с явными правами |
| Post-renderer | Путь к исполняемому файлу | Только **плагин** (kustomize-обёртку нужно переоформить) |
| OCI | `helm registry login https://…` допускался | Логин по **домену**; установка по `@sha256:` |
| Прочее | — | Кэш по содержимому, логи через slog, воспроизводимая сборка архивов |

**Чек-лист перевода CI на Helm 4:**
1. Зафиксировать версию Helm в образе CI (`get-helm-4` или пакет с pinned-версией).
2. Заменить `--atomic` → `--rollback-on-failure`, `--force` → `--force-replace`.
3. Найти `--post-renderer` и переделать в плагин.
4. На staging прогнать `upgrade` существующих релизов и **новую** установку: SSA может
   вскрыть конфликты владельцев полей (поле правили `kubectl edit`, HPA и т.п.).
5. Проверить helmfile (Helm 4 поддерживается с v1.2.0) и ArgoCD (у него свой встроенный Helm).

> 💡 Команды из темы 15 в Helm 4 те же — меняются флаги и механика применения.

---

## 5. helmfile — много релизов одним файлом

Когда в кластере 15 чартов (Envoy Gateway, cert-manager, KEDA, external-dns, мониторинг,
приложения) и 3 окружения, `helm upgrade` из bash-скрипта превращается в хаос.
**helmfile** описывает все релизы декларативно. Версии: **v1.8.0** (13.09.2026);
v1.0.0 — 30.04.2025 (заменена на v1.1.0 — с 0.x обновляться сразу на неё);
Helm 4 поддерживается с v1.2.0.

**Ломающие изменения v1:** шаблонизация — только в файлах `helmfile.yaml.gotmpl`;
`environments` и `releases` — в разных частях файла через `---`; удалены `--args`
и `charts.yaml`.

```yaml
# helmfile.yaml.gotmpl
environments:
  dev:  { values: [env/dev.yaml] }
  prod: { values: [env/prod.yaml] }
---
repositories:
  - name: kedacore
    url: https://kedacore.github.io/charts
  - name: external-dns
    url: https://kubernetes-sigs.github.io/external-dns/

releases:
  - name: keda
    namespace: keda
    chart: kedacore/keda
    version: 2.21.0
  - name: external-dns
    namespace: external-dns
    chart: external-dns/external-dns
    version: 1.22.0
    installed: {{ .Values.dns.enabled }}           # в dev можно выключить
    values: [values/external-dns.yaml.gotmpl]
  - name: web
    namespace: shop
    chart: oci://ghcr.io/my-org/charts/web
    version: 0.3.0
    needs: [keda/keda]                             # ⭐ порядок: сначала KEDA (CRD ScaledObject)
    values: [values/web-{{ .Environment.Name }}.yaml]
```

```bash
helm plugin install https://github.com/databus23/helm-diff   # нужен для diff/apply
helmfile -e dev  diff            # что изменится (как terraform plan)
helmfile -e dev  apply           # diff + применить только изменившиеся релизы
helmfile -e prod template > rendered.yaml    # финальные манифесты для ревью; sync — всё без diff
```

| | helmfile | ArgoCD |
|---|----------|--------|
| Модель | Push: CLI/CI применяет | Pull: агент в кластере сверяет с git |
| Дрейф | Виден только при `diff` | Виден всегда, `selfHeal` исправляет |
| Доступ | CI нужны креды кластера | Кластер сам ходит в git |
| Порядок релизов | `needs` | sync waves, App of Apps |
| Где хорош | Бутстрап аддонов, локальная разработка, «без GitOps» | Постоянная доставка в прод |

> 💬 Частая схема: helmfile поднимает «фундамент» нового кластера (CNI, ArgoCD),
> дальше всё ведёт ArgoCD. ArgoCD helmfile нативно не читает — только через CMP-плагин.

---

## 6. KEDA — событийный скейлинг

KEDA ставит оператор и адаптер External Metrics API; по `ScaledObject` создаёт HPA `keda-hpa-<имя>`
для 1 ↔ N и **сама** делает 0 ↔ 1. Формула HPA — тема 18.

| Факт (проверь, сентябрь 2026) | |
|-------------------------------|---|
| Версия | **KEDA 2.21.0** (23.09.2026), следующая — ~январь 2027 |
| Поддержка Kubernetes | 1.34–1.36 (N-2) — ⭐ для kind бери `kindest/node:v1.36.4` |
| Важно при обновлении с 2.20 | Критичная CVE-2026-77524 для `boundServiceAccountToken` (Vault, Prometheus с токеном SA) + ещё два ломающих изменения — читать migration guide |
| Ограничение | В кластере может быть только **один** адаптер `external.metrics.k8s.io` — и это должен быть KEDA |

---

## 🧪 Мини-лаба: KEDA scale to zero в kind

Эмулируем очередь: nginx отдаёт JSON `{"queue": N}`, воркер скейлится по N скейлером `metrics-api`.

```bash
kind create cluster --name keda --image kindest/node:v1.36.4
helm repo add kedacore https://kedacore.github.io/charts && helm repo update
helm install keda kedacore/keda --version 2.21.0 -n keda --create-namespace
kubectl -n keda wait --for=condition=Available deploy --all --timeout=180s
kubectl get apiservice v1beta1.external.metrics.k8s.io        # AVAILABLE True
```

```yaml
# keda-lab.yaml
apiVersion: v1
kind: Namespace
metadata: { name: demo }
---
apiVersion: apps/v1
kind: Deployment
metadata: { name: queue-api, namespace: demo }
spec:
  selector: { matchLabels: { app: queue-api } }
  template:
    metadata: { labels: { app: queue-api } }
    spec:
      containers:
        - name: nginx
          image: nginx
          command: ["sh", "-c", "echo '{\"queue\": 0}' > /usr/share/nginx/html/stats.json && exec nginx -g 'daemon off;'"]
---
apiVersion: v1
kind: Service
metadata: { name: queue-api, namespace: demo }
spec:
  selector: { app: queue-api }
  ports: [{ port: 80 }]
---
apiVersion: apps/v1
kind: Deployment
metadata: { name: worker, namespace: demo }
spec:
  replicas: 0                                   # с нуля — дальше решает KEDA
  selector: { matchLabels: { app: worker } }
  template:
    metadata: { labels: { app: worker } }
    spec:
      containers:
        - name: worker
          image: busybox:1.36
          command: ["sh", "-c", "while true; do echo working; sleep 5; done"]
          resources: { requests: { cpu: 10m, memory: 16Mi } }
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata: { name: worker, namespace: demo }
spec:
  scaleTargetRef: { name: worker }
  minReplicaCount: 0
  maxReplicaCount: 10
  pollingInterval: 10                           # опрос источника раз в 10 с
  cooldownPeriod: 30                            # 30 с «тишины» → в ноль
  triggers:
    - type: metrics-api
      metadata:
        url: "http://queue-api.demo.svc.cluster.local/stats.json"
        valueLocation: "queue"
        targetValue: "5"                        # 5 сообщений на реплику
        activationTargetValue: "0"              # больше 0 → просыпаемся
```

```bash
kubectl apply -f keda-lab.yaml
kubectl -n demo get scaledobject worker        # READY True, ACTIVE False
kubectl -n demo get hpa                        # keda-hpa-worker создан KEDA
kubectl -n demo get deploy worker -w           # держи в отдельном окне

# «пришло 23 сообщения»: 0 → 1 (KEDA), затем 1 → 5 (HPA: ceil(23 / 5) = 5)
kubectl -n demo exec deploy/queue-api -- sh -c 'echo "{\"queue\": 23}" > /usr/share/nginx/html/stats.json'

# «очередь разобрана»: через cooldownPeriod + опрос → 0 подов
kubectl -n demo exec deploy/queue-api -- sh -c 'echo "{\"queue\": 0}" > /usr/share/nginx/html/stats.json'
kubectl -n demo describe scaledobject worker | tail -10   # события активации/деактивации
```

**Шаг 2 — расписание.** Добавь в `triggers` второй триггер и примени:
```yaml
    - type: cron
      metadata:
        timezone: Asia/Almaty
        start: "0,10,20,30,40,50 * * * *"       # окно открывается каждые 10 минут…
        end:   "5,15,25,35,45,55 * * * *"       # …и закрывается через 5
        desiredReplicas: "2"
```
В окне воркеров минимум 2 (берётся максимум из триггеров), вне окна при пустой
очереди — 0. В проде так гасят dev-окружения ночью (`start: 0 9 * * 1-5`, `end: 0 19 * * 1-5`).

**Проверь себя:** `kubectl get hpa` показывает `minReplicas 1` — почему поды всё же уходят в 0?
Что будет, если создать ещё один HPA на `worker`? Уборка: `kind delete cluster --name keda`.

---

## 7. Karpenter — ноды под поды (концепция)

Cluster Autoscaler увеличивает **заранее заданные группы** нод. Karpenter смотрит
на `Pending`-поды и **сам выбирает тип инстанса** — самый дешёвый из разрешённых,
создаёт ноду за десятки секунд и постоянно ищет, как переложить поды на меньше/дешевле нод.
Версия **v1.14.1** (21.08.2026, LTS до 07.2027); работает в AWS (EKS, в т.ч. Auto Mode)
и Azure (AKS Node Auto Provisioning).

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool                                   # ЧТО можно создавать
metadata: { name: general }
spec:
  template:
    spec:
      nodeClassRef: { group: karpenter.k8s.aws, kind: EC2NodeClass, name: default }
      requirements:
        - { key: karpenter.sh/capacity-type, operator: In, values: ["spot", "on-demand"] }
        - { key: karpenter.k8s.aws/instance-category, operator: In, values: ["c", "m"] }
      expireAfter: 720h                          # ноды не старше 30 дней — свежие AMI
  limits: { cpu: "100" }                         # потолок
  disruption: { consolidationPolicy: WhenEmptyOrUnderutilized, consolidateAfter: 1m }
# EC2NodeClass (karpenter.k8s.aws/v1) — КАК создавать: AMI, подсети, security groups, IAM-роль
```

| | Cluster Autoscaler | Karpenter |
|---|--------------------|-----------|
| Единица | Группа нод одного типа (ASG, node pool) | Отдельная нода под конкретные поды |
| Тип инстанса | Выбран заранее | На лету, самый дешёвый подходящий |
| Скорость | Минуты | Десятки секунд |
| Упаковка | Удаляет недогруженные | Активная consolidation, замена на дешёвые |
| Обновление нод | Отдельная процедура | **Drift**: сменилась AMI/версия — ноды заменяются сами (surge из темы 24 §4) |
| Где | Почти везде, включая Yandex | AWS, Azure |

---

## 8. Перекат при изменении конфигурации: Reloader и альтернативы

Из темы 08: переменные окружения из ConfigMap/Secret **не обновляются** в живом поде,
а файлы из тома обновляются с задержкой, но приложение их обычно не перечитывает.
Нужен rollout — вопрос, кто его запустит.

| Способ | Как | Когда |
|--------|-----|-------|
| checksum-аннотация | <code v-pre>checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . \| sha256sum }}</code> в шаблоне пода | ⭐ Конфиг в том же чарте (тема 15) |
| Kustomize `configMapGenerator` | Имя с хешем содержимого → новый ConfigMap → новый шаблон пода | Kustomize-репозитории |
| `kubectl rollout restart` | Руками или из CI | Разово |
| **Reloader** (stakater, v1.4.22; v2 — в бете) | Контроллер следит за ConfigMap/Secret и перекатывает связанные нагрузки | Конфиг меняется **вне** чарта: External Secrets, cert-manager, ротация паролей |

```bash
helm repo add stakater https://stakater.github.io/stakater-charts
helm install reloader stakater/reloader -n reloader --create-namespace
```

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  annotations:
    reloader.stakater.com/auto: "true"                    # любой используемый ConfigMap/Secret
    # или точечно:
    # secret.reloader.stakater.com/reload: "db-credentials"
    # configmap.reloader.stakater.com/reload: "api-config"
    # deployment.reloader.stakater.com/pause-period: "5m" # не чаще раза в 5 минут
```

> ⚠️ В GitOps стратегия по умолчанию (`env-vars`) меняет шаблон пода, и ArgoCD видит дрейф —
> для ArgoCD включают `reloadStrategy: annotations`. И помни: ротация одного общего Secret
> с Reloader = одновременный rollout всех использующих его сервисов; нужны PDB и `maxUnavailable`.

---

## 9. Грабли

| Грабля | Что происходит | Как избежать |
|--------|----------------|--------------|
| external-dns с `policy: sync` и без `domainFilters` | Удаляет «лишние» записи в зоне | `upsert-only` на старте, фильтр доменов |
| Одинаковый `txtOwnerId` у двух кластеров | Кластеры перетирают записи друг друга | Уникальный owner-id на кластер |
| Обновили external-dns до 0.22+ со старыми аннотациями | Записи удаляются | `--dry-run`, миграция на `external-dns.kubernetes.io/` |
| CI на Helm 4 с `--atomic` | Скрипт падает на неизвестном флаге | `--rollback-on-failure` |
| Свой HPA + ScaledObject на один Deployment | Два контроллера спорят о репликах | Только ScaledObject (вебхук KEDA отклонит) |
| Scale to zero для HTTP без буфера | Первый запрос после нуля ждёт или падает | min 1 или KEDA HTTP add-on |
| KEDA 2.21 на кластере 1.37 | Вне матрицы поддержки (1.34–1.36) | Ждать версию KEDA с 1.37 |
| Reloader + общий Secret | Одновременный rollout десятка сервисов | Точечные аннотации, `pause-period`, PDB |

---

## 💼 Как это в DevOps

- external-dns + cert-manager + Gateway — стандартная тройка входа: объект в git →
  запись DNS → сертификат → трафик. Руками в DNS-консоль в зрелой команде не ходят.
- Чарты — в том же OCI-реестре, что и образы: одна модель прав, сканирование, подпись
  (cosign). Публичный Helm-репозиторий на GitHub Pages — наследие.
- Helm 3 доживает до 10.02.2027: перевод пайплайнов на Helm 4 — задача ближайших месяцев,
  главное — флаги и server-side apply.
- KEDA — стандарт для воркеров очередей и «ночного нуля» в non-prod;
  Karpenter — стандарт де-факто для нод в EKS. Любой аддон отсюда — ещё строка
  в матрице совместимости при обновлении кластера (тема 24 §3.3).

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| DNS-запись для Gateway | external-dns `--source=gateway-httproute`, имя — `spec.hostnames` |
| Не удалить чужое | `--domain-filter`, `--policy=upsert-only`, уникальный `--txt-owner-id` |
| Положить чарт в реестр | `helm package` → `helm registry login` → `helm push x.tgz oci://…` |
| Поставить чарт из OCI | `helm upgrade --install web oci://ghcr.io/org/charts/web --version 0.3.0` |
| OCI-чарт в ArgoCD | `repoURL: ghcr.io/org/charts` + `chart: web` (или `oci://…` в 3.1+) |
| Откат при неудаче в Helm 4 | `--rollback-on-failure` (было `--atomic`) |
| Применить изменившиеся релизы | `helmfile -e prod apply` |
| Скейлинг до нуля | KEDA `ScaledObject` с `minReplicaCount: 0` |
| Ноды под поды | Karpenter `NodePool` + `EC2NodeClass` |
| Перекат при смене Secret | Reloader `reloader.stakater.com/auto: "true"` |

---

## 🧠 Что запомнить

1. Каждый инструмент решает одну задачу — и каждый добавляет строку в матрицу обновлений.
2. ⭐ external-dns берёт имена из Service/Ingress/HTTPRoute, адреса — из статусов
   (у Gateway — `status.addresses`) и синхронизирует их с DNS-провайдером.
3. Владение — TXT с `--txt-owner-id` (свой на кластер); `--policy` с v0.22 обязателен,
   старт — `upsert-only` + `--domain-filter`; в kind без DNS-провайдера — только `inmemory`.
4. ⚠️ v0.22 сменила префикс аннотаций на `external-dns.kubernetes.io/` — старые
   аннотации + `sync` могут удалить записи.
5. OCI-чарты: `helm push/pull/install oci://…`, без `helm repo add`; тег = версия чарта.
6. ArgoCD: Helm-OCI — `repoURL` без `oci://` + `chart`; нативный OCI (3.1+) — с `oci://`.
7. ⭐ Helm 4 (с 12.11.2025): server-side apply для новых релизов, `--rollback-on-failure`
   вместо `--atomic`, `--force-replace`, kstatus, WASM-плагины; чарты v2 работают.
8. Helm 3: последняя минорная 3.22.0, security-фиксы до 10.02.2027.
9. helmfile v1: `.gotmpl` для шаблонов, `environments` и `releases` через `---`,
    `diff` → `apply`; push-модель против pull-модели ArgoCD.
10. ⭐ KEDA делает 0 ↔ 1 сама, 1 ↔ N — через свой HPA; `cooldownPeriod` — задержка
    перехода в 0; второй HPA на ту же цель — ошибка.
11. KEDA 2.21 поддерживает Kubernetes 1.34–1.36 и закрывает критичную CVE — обновляться.
12. Karpenter подбирает инстанс под поды, умеет consolidation и drift; CA масштабирует группы.
13. Reloader перекатывает поды при смене ConfigMap/Secret, которые меняются вне чарта;
    для конфигов внутри чарта хватает checksum-аннотации.

---

## Задачи

> ⭐ Вопросы собеса: *«Как у вас появляются DNS-записи?»*, *«Где храните чарты?»*,
> *«Как скейлить воркеры до нуля?»* — важно назвать инструмент **и** его ограничения.

---

### Блок A. Теория

**A1.** ⭐ Какую задачу решает external-dns? Что он делает раз в `--interval`?

<details><summary>Ответ</summary>

Синхронизирует DNS-записи у провайдера с объектами кластера: собирает имена
и адреса из источников, сравнивает с зоной и применяет изменения в рамках `--policy`.

</details>

**A2.** Какие источники (`--source`) умеет external-dns? Откуда он берёт имя и адрес
для HTTPRoute?

<details><summary>Ответ</summary>

`service`, `ingress`, `gateway-httproute/grpcroute/tlsroute/tcproute/udproute`,
`crd` (DNSEndpoint), `node`, источники Istio, Contour, Traefik и др. Для HTTPRoute имя —
`spec.hostnames` (или hostname listener'а), адрес — `status.addresses` Gateway из `parentRefs`.

</details>

**A3.** Почему для `gateway-tcproute` имя задаётся только аннотацией?

<details><summary>Ответ</summary>

У TCPRoute/UDPRoute нет поля `hostnames` — это L4-маршруты без понятия имени хоста.

</details>

**A4.** ⭐ Как external-dns понимает, что запись «его»? Что такое `--txt-owner-id`?

<details><summary>Ответ</summary>

Рядом с каждой записью создаётся TXT с меткой `heritage=external-dns` и владельцем
`--txt-owner-id`. Записи без своего TXT external-dns не трогает.

</details>

**A5.** Чем отличаются `--policy=sync`, `upsert-only`, `create-only`? Что изменилось
с этим флагом в v0.22?

<details><summary>Ответ</summary>

`sync` — создаёт, обновляет и удаляет свои записи; `upsert-only` — без удаления;
`create-only` — только создание. С v0.22 флаг обязателен, дефолта нет.

</details>

**A6.** ⭐ Какое ломающее изменение аннотаций было в external-dns v0.22 и чем оно опасно?

<details><summary>Ответ</summary>

Префикс аннотаций по умолчанию стал `external-dns.kubernetes.io/` без fallback
на `external-dns.alpha.kubernetes.io/`. Старые аннотации перестают читаться, и при `sync`
external-dns удалит «ненужные» записи. Защита — `--dry-run`, миграция аннотаций,
`--enable-legacy-annotation-prefix` (v0.23) или явный `--annotation-prefix`.

</details>

**A7.** Что такое webhook-провайдер external-dns и зачем он нужен?

<details><summary>Ответ</summary>

Провайдер как отдельный процесс-адаптер (обычно sidecar), с которым external-dns
общается по HTTP. Так поддерживают DNS-сервисы без in-tree кода, в том числе удалённые из дерева.

</details>

**A8.** Почему external-dns нельзя полноценно проверить в kind?

<details><summary>Ответ</summary>

Нужен реальный DNS-провайдер с зоной и адрес у Gateway/LoadBalancer. `inmemory`
показывает план изменений в логах, но записи нельзя зарезолвить.

</details>

**A9.** Зачем хранить Helm-чарты в OCI-реестре, а не в классическом Helm-репозитории?

<details><summary>Ответ</summary>

Один реестр для образов и чартов: общие права, аутентификация, сканирование,
подпись, иммутабельные теги и digest; не нужен отдельный сервер с `index.yaml`.

</details>

**A10.** Какими командами опубликовать чарт в GHCR и поставить его оттуда?

<details><summary>Ответ</summary>

`helm package ./chart` → `helm registry login ghcr.io` → `helm push web-0.3.0.tgz
oci://ghcr.io/<user>/charts` → `helm upgrade --install web oci://ghcr.io/<user>/charts/web --version 0.3.0`.

</details>

**A11.** Чем отличаются два способа подключить OCI-чарт в ArgoCD?

<details><summary>Ответ</summary>

Helm-репозиторий типа OCI: `repoURL` без `oci://` (`ghcr.io/org/charts`) + `chart: web`,
креды с `type: helm` и `enableOCI: "true"`. Нативный OCI-источник (ArgoCD 3.1+): `repoURL:
oci://ghcr.io/org/charts/web`, `path: .`, креды типа `oci`.

</details>

**A12.** ⭐ Назови главные изменения Helm 4 по сравнению с Helm 3.

<details><summary>Ответ</summary>

Server-side apply для новых установок, `--atomic` → `--rollback-on-failure`,
`--force` → `--force-replace`, ожидание на основе kstatus, новая система плагинов
с WebAssembly, post-renderer только как плагин, установка OCI по digest, логин в реестр
по домену; чарты v2 работают как раньше.

</details>

**A13.** Как Helm 4 применяет манифесты для новых и для существующих релизов?

<details><summary>Ответ</summary>

Новые релизы — server-side apply; релизы, созданные Helm 3, продолжают
обновляться client-side, пока не переключить `--server-side`.

</details>

**A14.** До какой даты Helm 3 получает исправления безопасности? Какая версия — последняя минорная?

<details><summary>Ответ</summary>

Security-фиксы — до 10.02.2027; последняя минорная — 3.22.0 (10.09.2026).

</details>

**A15.** Что такое helmfile и чем он отличается от «bash-скрипта с `helm upgrade`»?

<details><summary>Ответ</summary>

Декларативное описание всех релизов, репозиториев и окружений в одном файле:
`diff` показывает изменения до применения, `apply` применяет только изменившиеся релизы,
`needs` задаёт порядок. Скрипт этого не умеет и не показывает план.

</details>

**A16.** Какие ломающие изменения принёс helmfile v1?

<details><summary>Ответ</summary>

Шаблонизация — только в `.gotmpl`; `environments` и `releases` — в разных частях
через `---`; удалены `--args` и `charts.yaml`; `HELMFILE_SKIP_INSECURE_TEMPLATE_FUNCTIONS`
заменён на `HELMFILE_DISABLE_INSECURE_FEATURES`.

</details>

**A17.** ⭐ Чем helmfile отличается от ArgoCD? Когда что брать?

<details><summary>Ответ</summary>

helmfile — push: CI или человек применяет, дрейф виден только при `diff`,
CI нужны креды кластера. ArgoCD — pull: агент в кластере постоянно сверяет с git
и исправляет дрейф. helmfile — для бутстрапа и окружений без GitOps, ArgoCD — для постоянной
доставки в прод.

</details>

**A18.** Зачем в helmfile `needs`?

<details><summary>Ответ</summary>

Чтобы релиз ставился после зависимостей: например, приложение с ScaledObject —
после KEDA, которая приносит CRD.

</details>

**A19.** ⭐ Как KEDA масштабирует до нуля, если HPA этого не умеет?

<details><summary>Ответ</summary>

KEDA сама переводит нагрузку между 0 и 1 репликой по активности триггеров,
а диапазон 1…N отдаёт своему HPA `keda-hpa-<имя>`.

</details>

**A20.** Что делают `cooldownPeriod`, `pollingInterval` и `activationTargetValue`?

<details><summary>Ответ</summary>

`pollingInterval` — как часто опрашивать источник; `cooldownPeriod` — сколько
ждать после последней активности перед переходом в 0; `activationTargetValue` — порог
«проснуться с нуля», отдельный от порога масштабирования.

</details>

**A21.** Как работает cron-триггер KEDA вместе с другими триггерами?

<details><summary>Ответ</summary>

В окне `start`–`end` триггер требует `desiredReplicas`; HPA берёт максимум
по всем триггерам, поэтому cron работает как «динамический минимум».

</details>

**A22.** Почему нельзя создавать свой HPA для Deployment, у которого есть ScaledObject?

<details><summary>Ответ</summary>

Два HPA на одну цель спорят о числе реплик; KEDA ведёт свой HPA, а её
admission-вебхук отклоняет конфликтующие объекты.

</details>

**A23.** ⭐ Чем Karpenter отличается от Cluster Autoscaler? Что такое NodePool и EC2NodeClass?

<details><summary>Ответ</summary>

CA увеличивает заранее заданные группы нод; Karpenter создаёт отдельные ноды,
выбирая тип под ожидающие поды, быстрее и дешевле. NodePool — какие ноды можно создавать
(типы, spot/on-demand, лимиты, правила disruption); EC2NodeClass — как (AMI, подсети,
security groups, IAM-роль).

</details>

**A24.** Что такое consolidation и drift в Karpenter?

<details><summary>Ответ</summary>

Consolidation — перекладывание подов, чтобы удалить пустые или заменить
недогруженные ноды дешёвыми. Drift — замена нод, которые перестали соответствовать
NodePool/EC2NodeClass (например, сменилась AMI или версия).

</details>

**A25.** Какие есть способы перекатить поды при изменении ConfigMap/Secret? Когда нужен Reloader?

<details><summary>Ответ</summary>

checksum-аннотация в чарте, `configMapGenerator` с хешем, `kubectl rollout restart`,
Reloader. Reloader нужен, когда ConfigMap/Secret меняется вне чарта: External Secrets,
cert-manager, ротация паролей.

</details>

---

### Блок B. «Что произойдёт»

```yaml
# B1 — external-dns
policy: sync
# domainFilters не задан; в зоне example.com есть ручные записи mail, vpn
```
Вопрос: тронет ли external-dns ручные записи? А что может пойти не так?

<details><summary>Ответ</summary>

Ручные записи без TXT-владельца он не тронет. Но без `domainFilters` он будет
работать со всеми зонами, к которым есть доступ, и при ошибке в объектах может создать
или удалить свои записи не там. Ограничить домены и начинать с `upsert-only`.

</details>

```yaml
# B2 — два кластера, blue и green
txtOwnerId: prod        # одинаковый в обоих
```
Вопрос: что будет с записью `shop.example.com`?

<details><summary>Ответ</summary>

Оба кластера считают запись своей и переписывают её на свой адрес при каждом
цикле — запись «прыгает». Owner-id должен быть уникальным.

</details>

```yaml
# B3 — обновили external-dns с 0.21 до 0.23, policy: sync
metadata:
  annotations:
    external-dns.alpha.kubernetes.io/hostname: api.example.com
```
Вопрос: что случится с записью `api.example.com`?

<details><summary>Ответ</summary>

v0.22+ не читает старый префикс: источник больше не требует `api.example.com`,
и при `policy: sync` запись будет удалена. Нужна миграция аннотаций до обновления.

</details>

```bash
# B4
helm repo add myrepo oci://ghcr.io/me/charts
```
Вопрос: что ответит Helm и как правильно?

<details><summary>Ответ</summary>

Ошибка: OCI-реестры не добавляются через `helm repo add`. Правильно — сразу
`helm install/pull/show … oci://ghcr.io/me/charts/<chart> --version X`.

</details>

```bash
# B5 — CI после перехода на Helm 4
helm upgrade --install web ./chart --atomic --timeout 5m
```
Вопрос: что будет?

<details><summary>Ответ</summary>

Команда упадёт или поведёт себя иначе: в Helm 4 флаг называется `--rollback-on-failure`.

</details>

```yaml
# B6 — helmfile v1
# файл helmfile.yaml (без .gotmpl)
releases:
  - name: web
    values: [values/web-{{ .Environment.Name }}.yaml]
```
Вопрос: что пойдёт не так?

<details><summary>Ответ</summary>

Файл без `.gotmpl` не рендерится как шаблон — выражение <code v-pre>{{ .Environment.Name }}</code>
останется буквальным, путь к values будет неверным. Переименовать в `helmfile.yaml.gotmpl`.

</details>

```yaml
# B7 — KEDA
minReplicaCount: 0
cooldownPeriod: 300
triggers:
  - type: metrics-api
    metadata: { targetValue: "10", activationTargetValue: "0", ... }
# в «очереди» 37 сообщений, сейчас 0 реплик
```
Вопрос: сколько реплик будет и в каком порядке?

<details><summary>Ответ</summary>

Сначала KEDA активирует нагрузку: 0 → 1. Затем HPA посчитает `ceil(37 / 10) = 4`
и поднимет до 4 (в пределах `maxReplicaCount`).

</details>

```yaml
# B8
triggers:
  - type: cron
    metadata: { timezone: Asia/Almaty, start: "0 9 * * 1-5", end: "0 19 * * 1-5", desiredReplicas: "3" }
  - type: prometheus
    metadata: { threshold: "50", query: "sum(rate(http_requests_total[2m]))" }   # сейчас 400 RPS
# вторник, 11:00
```
Вопрос: сколько реплик? А в субботу при тех же 400 RPS?

<details><summary>Ответ</summary>

Во вторник в 11:00: `max(3, ceil(400 / 50) = 8)` = 8. В субботу cron неактивен,
остаётся Prometheus: тоже 8. Cron влияет только когда нагрузка ниже его минимума.

</details>

```yaml
# B9 — Karpenter
spec:
  limits: { cpu: "100" }
# в NodePool уже ноды на 98 CPU, в Pending поды на 8 CPU
```
Вопрос: что сделает Karpenter?

<details><summary>Ответ</summary>

Создаст ноды не больше чем на 2 CPU до лимита; если подходящей ноды в пределах
лимита нет, часть подов останется `Pending`. Лимит — защита, а не ошибка.

</details>

```yaml
# B10 — Reloader
metadata:
  annotations:
    reloader.stakater.com/auto: "true"
# 12 Deployment используют общий Secret db-credentials; ESO его ротировал
```
Вопрос: что произойдёт?

<details><summary>Ответ</summary>

Reloader перекатит все 12 Deployment почти одновременно; без PDB
и аккуратной стратегии rollout возможен короткий простой и нагрузка на БД при переподключении.

</details>

---

### Блок C. Практика

#### C1. 🔑 KEDA scale to zero
Пройди мини-лабу из конспекта: KEDA 2.21 в kind на `kindest/node:v1.36.4`,
воркер по `metrics-api`. Запиши, через сколько секунд после изменения «очереди»
появился первый под и через сколько воркеры ушли в 0.

<details><summary>Ответ</summary>

Типично: первый под через 10–20 секунд (опрос + старт), до 5 реплик — ещё
через 15–30 секунд; уход в 0 — примерно через `cooldownPeriod` плюс интервал опроса.

</details>

#### C2. 🔑 Проверка формулы на KEDA
Поставь в «очередь» 7, 23, 51 при `targetValue: "5"`. Посчитай ожидаемое число реплик
(`ceil(N / 5)`, но не больше `maxReplicaCount`) и сравни с фактом.

<details><summary>Ответ</summary>

7 → 2, 23 → 5, 51 → 10 при `maxReplicaCount: 10` (иначе 11).

</details>

#### C3. cron-триггер
Добавь cron-окно из конспекта. Убедись, что в окне реплик минимум 2 даже при пустой
очереди, а вне окна — 0. Посмотри, как это отражается в `kubectl get hpa`.

#### C4. Конфликт двух HPA
Попробуй создать `kubectl autoscale deploy worker -n demo --min=1 --max=3`.
Что ответил кластер? Найди, какой компонент отклонил запрос.

#### C5. 🔑 Helm OCI локально
1. Подними локальный реестр `registry:2` на порту 5001.
2. `helm package` свой чарт из лабы 5, `helm push … --plain-http`.
3. Поставь чарт в kind из `oci://localhost:5001/charts/<имя>` (для kind подумай,
   откуда кластер будет качать образ приложения — чарт ставит Helm на твоей машине).
4. Подними версию, опубликуй снова и сделай `helm upgrade` на новую версию.

#### C6. Helm 4
Поставь Helm 4 во временный каталог (`get-helm-4` с `HELM_INSTALL_DIR`),
выполни `helm version`, создай новый релиз и посмотри `metadata.managedFields`
у Deployment: кто менеджер полей? Сравни с релизом, установленным Helm 3.

<details><summary>Ответ</summary>

У релиза Helm 4 менеджер полей — Helm с операцией Apply (server-side);
у релиза Helm 3 — операция Update от клиента Helm.

</details>

#### C7. 🔑 helmfile
Опиши стенд в `helmfile.yaml.gotmpl`: окружения dev и prod, релизы Envoy Gateway,
KEDA и твоё приложение из OCI, `needs` для порядка. Выполни `helmfile -e dev diff`
и `apply`, затем поменяй значение в values и снова посмотри `diff`.

#### C8. external-dns учебно
Запусти external-dns в kind с `--provider=inmemory --inmemory-zone=example.org
--source=service --publish-internal-services --policy=sync --log-level=debug`.
Создай ClusterIP-Service с аннотацией `external-dns.kubernetes.io/hostname: web.example.org`
и найди в логах план изменений. Запиши, что в этом запуске **не** проверяется.

<details><summary>Ответ</summary>

Не проверяется реальная запись в DNS, права на зону, адреса Gateway/LoadBalancer
и поведение TXT в настоящем провайдере.

</details>

#### C9. Reloader
Поставь Reloader, повесь `reloader.stakater.com/auto: "true"` на Deployment,
который читает переменную из ConfigMap. Измени ConfigMap и посмотри,
перекатились ли поды и появилась ли новая ревизия в `rollout history`.

#### C10. Таблица «какую задачу решает что»
Без подсказок заполни таблицу из 8 строк: задача → инструмент → альтернатива →
одно ограничение. Сверь с §1 конспекта.

#### C11. Karpenter на бумаге (со звёздочкой)
Напиши NodePool для воркеров очередей: только spot, arm64 и amd64, лимит 40 CPU,
consolidation только пустых нод. Объясни, как он будет сочетаться с KEDA `minReplicaCount: 0`.

---

### Блок D. Инциденты

**D1.** После обновления external-dns пропали DNS-записи половины сервисов.
Что проверить и как восстановить?

<details><summary>Ответ</summary>

Логи external-dns и версия; не было ли перехода на v0.22+ со старым префиксом
аннотаций, изменения `--policy`, `txtOwnerId` или `domainFilters`. Восстановить аннотации
(или включить `--enable-legacy-annotation-prefix`), записи вернутся при следующем цикле;
на будущее — `--dry-run` перед обновлением.

</details>

**D2.** external-dns в логах пишет, что не может изменить запись, «owned by another owner».
Что это значит и что делать?

<details><summary>Ответ</summary>

TXT-запись принадлежит другому owner-id — её создал другой кластер или экземпляр.
Разобраться, кто должен владеть записью; не «отбирать» её сменой owner-id вслепую.

</details>

**D3.** DNS-запись для HTTPRoute не создаётся, хотя маршрут `Accepted`. Где искать?

<details><summary>Ответ</summary>

Включён ли источник `gateway-httproute`, есть ли у Gateway `status.addresses`,
совпадает ли hostname с `domainFilters`, есть ли RBAC на gateways/httproutes/namespaces,
не отфильтрован ли Gateway `--gateway-name/--gateway-label-filter`.

</details>

**D4.** После перехода CI на Helm 4 часть релизов при `upgrade` падает с конфликтами полей,
а новые установки проходят. Объясни и предложи план.

<details><summary>Ответ</summary>

Новые релизы идут через server-side apply, старые при переключении на SSA
сталкиваются с полями, которыми владеют другие менеджеры (kubectl, HPA, контроллеры).
План: оставить старые релизы на client-side, разобрать конфликты на staging,
убрать из чартов поля, которыми управляют другие (например, `replicas` при HPA).

</details>

**D5.** Кто-то перезалил чарт `web:0.3.0` в реестр, и в проде «та же версия» ведёт себя иначе.
Как не допустить такого?

<details><summary>Ответ</summary>

Иммутабельные теги в реестре, установка по digest (`@sha256:` в Helm 4),
подпись чартов (cosign) и повышение версии чарта при любом изменении.

</details>

**D6.** Воркеры KEDA не уходят в 0 ночью. Гипотезы?

<details><summary>Ответ</summary>

`minReplicaCount` больше 0; источник метрики не опускается ниже порога активации;
активен cron-триггер; `idleReplicaCount`; фоновая активность в очереди.

</details>

**D7.** После падения Prometheus воркеры KEDA «замерли» на одном числе реплик
и не реагируют на очередь. Что настроить?

<details><summary>Ответ</summary>

Источник недоступен — KEDA не может принять решение. Настроить `fallback`
(число реплик при ошибках источника) и алерт на ошибки скейлера.

</details>

**D8.** HTTP-сервис со scale to zero: первый запрос утром падает с таймаутом. Что делать?

<details><summary>Ответ</summary>

Холодный старт после нуля. Держать минимум 1 реплику для HTTP, либо KEDA
HTTP add-on, который буферизует запросы, пока поднимается под.

</details>

**D9.** Karpenter создал в 3 раза больше нод, чем ожидалось, счёт вырос. Причины?

<details><summary>Ответ</summary>

Завышенные `requests`, нет `limits` в NodePool, consolidation выключена или
заблокирована (`do-not-disrupt`, PDB), слишком узкие требования к типам, поды с
anti-affinity «по одному на ноду».

</details>

**D10.** После ротации пароля БД одновременно перезапустились 12 сервисов,
был короткий простой. Что улучшить?

<details><summary>Ответ</summary>

Точечные аннотации Reloader вместо общего `auto`, `pause-period`,
PDB и `maxUnavailable`, разные Secret для разных сервисов, пул соединений в приложении.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Как у вас появляются DNS-записи для сервисов в Kubernetes?

<details><summary>Ответ</summary>

external-dns: имена из HTTPRoute/Ingress/Service, адреса из статусов, провайдер —
Route 53 или Cloudflare, `upsert-only`/`sync`, свой owner-id на кластер.

</details>

**2.** Как external-dns не ломает чужие записи?

<details><summary>Ответ</summary>

TXT-владение, `--domain-filter`, аккуратная `--policy`, `--dry-run` при обновлениях.

</details>

**3.** Где вы храните Helm-чарты и почему?

<details><summary>Ответ</summary>

В OCI-реестре рядом с образами: права, сканирование, подпись, иммутабельные теги.

</details>

**4.** ⭐ Что изменилось в Helm 4 и что нужно поправить в пайплайнах?

<details><summary>Ответ</summary>

SSA для новых релизов, `--rollback-on-failure`, `--force-replace`, post-renderer как плагин,
kstatus; поправить флаги, проверить upgrade старых релизов; Helm 3 — до 10.02.2027.

</details>

**5.** helmfile или ArgoCD — что и когда?

<details><summary>Ответ</summary>

helmfile — push-модель, бутстрап и окружения без GitOps; ArgoCD — pull-модель
и постоянная сверка для прода.

</details>

**6.** ⭐ Как масштабировать воркеры очереди, включая ноль?

<details><summary>Ответ</summary>

KEDA ScaledObject по длине очереди с `minReplicaCount: 0`, порог активации,
`cooldownPeriod`, `fallback`; долгие задачи — ScaledJob.

</details>

**7.** Чем KEDA отличается от HPA с prometheus-adapter?

<details><summary>Ответ</summary>

KEDA приносит десятки источников, сама ведёт HPA и умеет 0 ↔ 1; HPA с адаптером
требует настройки метрик и до нуля не скейлит.

</details>

**8.** Karpenter или Cluster Autoscaler?

<details><summary>Ответ</summary>

Karpenter — в EKS/AKS, разнородные нагрузки и spot; CA — везде и с фиксированными группами.

</details>

**9.** Как сделать, чтобы поды перечитали изменившийся Secret?

<details><summary>Ответ</summary>

checksum-аннотация в чарте или Reloader для конфигов, меняющихся вне чарта.

</details>

**10.** Какие аддоны вы бы поставили в новый кластер первыми и почему?

<details><summary>Ответ</summary>

CNI, CSI, вход (Gateway + cert-manager + external-dns), metrics-server, мониторинг,
GitOps-агент; дальше — автоскейлинг (KEDA, Karpenter/CA) и Reloader по потребности.

</details>

---

## 🎯 Чек-лист

- [ ] Могу заполнить таблицу «какую задачу решает что» без подсказок
- [ ] ⭐ Объясняю, как external-dns берёт имена и адреса и как владеет записями
- [ ] Знаю ломающие изменения external-dns v0.22 (префикс аннотаций, обязательный `--policy`)
- [ ] Публиковал чарт в OCI-реестр и ставил его оттуда
- [ ] Знаю два способа подключить OCI-чарт в ArgoCD
- [ ] ⭐ Назову изменения Helm 4 и знаю, что поправить в CI
- [ ] Описал стенд в helmfile и пользовался `diff`/`apply`
- [ ] ⭐ Поднимал KEDA в kind и видел scale to zero
- [ ] Понимаю cron-триггер и `cooldownPeriod`
- [ ] Объясняю разницу Karpenter и Cluster Autoscaler
- [ ] Знаю, когда нужен Reloader, а когда хватает checksum-аннотации
