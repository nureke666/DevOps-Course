---
title: "06. Практика: 5 лаб по FinOps"
description: "Блок → FinOps и оптимизация ресурсов → практика."
---

# 06. Практика: 5 лаб по FinOps

> Блок → FinOps и оптимизация ресурсов → практика.
> Лабы 1–3 — на локальном кластере kind из [00_INDEX.md](/finops/) (раздел «Стенд»),
> лаба 4 — Terraform + Infracost + GitLab, лаба 5 — письменная. **Облачный аккаунт не нужен.**
> Всё складывай в репозиторий `finops-lab/` — после блока есть что показать на собесе:
> таблица rightsizing «до/после», showback по командам, dev, который спит ночью, Infracost
> в MR и cost review с оценкой экономии.
>
> Версии на сентябрь 2026 (пинь их вместо `latest`): KEDA 2.21, Infracost CLI v0.10.46 / v2.16,
> tflint-ruleset-aws 0.49, Kubernetes в kind ≥ 1.35 (для in-place resize).

---

## 📋 Список лаб

| № | Лаба | Что закрепляет | Артефакт |
|---|------|----------------|----------|
| 1 | ⭐ Rightsizing: раздутые requests → PromQL p95 → новые значения | тема 02 | манифесты до/после, `rightsizing.md` с таблицей эффективности |
| 2 | ⭐ OpenCost с custom pricing и showback по namespace | темы 01, 04 | `values-opencost.yaml`, расчёт цен, `showback.md`, дашборд, алерт |
| 3 | Dev спит ночью: KEDA cron и scale to zero | тема 03 | ScaledObject'ы, замеры, расчёт экономии |
| 4 | ⭐ Infracost на Terraform + CI-джоба с диффом в MR + политики | тема 05 | `infracost-lab/`, `.gitlab-ci.yml`, `policy/`, скриншот комментария |
| 5 | Cost review воображаемого счёта: 5 находок с оценкой экономии | темы 01–05 | `cost-review-2026-09.md` |

---

## 🧪 Лаба 1. ⭐ Rightsizing: от раздутых requests к честным

### Что делаем
Разворачиваем в namespace `demo` три сервиса с requests «как скопировали из интернета»,
даём нагрузку, меряем реальное потребление PromQL-ом, считаем новые значения по правилу
темы 02, применяем и сравниваем эффективность до и после.

### Каркас
```yaml
# demo.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: demo
  labels: { owner: team-shop, env: dev }
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: podinfo
  namespace: demo
  labels: { app: podinfo, owner: team-shop, env: dev, service: podinfo, team: shop }
spec:
  replicas: 3
  selector: { matchLabels: { app: podinfo } }
  template:
    metadata:
      labels: { app: podinfo, owner: team-shop, env: dev, service: podinfo, team: shop }
    spec:
      containers:
        - name: podinfo
          image: ghcr.io/stefanprodan/podinfo:latest   # ⚠️ latest — только для стенда
          ports: [{ containerPort: 9898 }]
          resources:
            requests: { cpu: "1", memory: 1Gi }        # «с запасом»
            limits:   { memory: 1Gi }
---
apiVersion: v1
kind: Service
metadata: { name: podinfo, namespace: demo, labels: { app: podinfo } }
spec:
  selector: { app: podinfo }
  ports: [{ name: http, port: 9898 }]
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: worker
  namespace: demo
  labels: { app: worker, owner: team-data, env: dev, service: worker, team: data }
spec:
  replicas: 2
  selector: { matchLabels: { app: worker } }
  template:
    metadata:
      labels: { app: worker, owner: team-data, env: dev, service: worker, team: data }
    spec:
      containers:
        - name: worker
          image: polinux/stress
          command: ["stress"]
          args: ["--vm", "1", "--vm-bytes", "150M", "--vm-hang", "1"]   # держит ~150 МБ
          resources:
            requests: { cpu: 500m, memory: 512Mi }
            limits:   { memory: 512Mi }
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx
  namespace: demo
  labels: { app: nginx, owner: team-shop, env: dev, service: nginx, team: shop }
spec:
  replicas: 2
  selector: { matchLabels: { app: nginx } }
  template:
    metadata:
      labels: { app: nginx, owner: team-shop, env: dev, service: nginx, team: shop }
    spec:
      containers:
        - name: nginx
          image: nginx:1.29
          resources:
            requests: { cpu: 500m, memory: 256Mi }
            limits:   { memory: 256Mi }
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: load
  namespace: demo
  labels: { app: load, owner: team-shop, env: dev, service: load, team: shop }
spec:
  replicas: 1
  selector: { matchLabels: { app: load } }
  template:
    metadata:
      labels: { app: load, owner: team-shop, env: dev, service: load, team: shop }
    spec:
      containers:
        - name: load
          image: busybox:1.36
          command: ["sh", "-c", "while true; do wget -q -O- http://podinfo:9898/ >/dev/null; sleep 0.05; done"]
          resources:
            requests: { cpu: 50m, memory: 16Mi }
            limits:   { memory: 32Mi }
```text
```bash
kubectl apply -f demo.yaml
kubectl -n demo get pods -o wide
kubectl -n monitoring port-forward svc/prometheus-kube-prometheus-prometheus 9090 &
# PrometheusRule с recording rules — из 02_k8s_rightsizing.md, раздел 4
kubectl apply -f finops-rightsizing-rules.yaml
```text
Дай стенду поработать **минимум 2 часа** (лучше ночь). В проде то же самое — за 7–14 дней.

### Требования
- [ ] Все поды `Running`, recording rules `workload_container:*` считаются на `/rules`
- [ ] Таблица «до»: requests, p95 CPU и max памяти за окно, эффективность по каждому workload
- [ ] Эффективность CPU и памяти namespace `demo` до изменений посчитана запросом из темы 02
- [ ] Новые значения посчитаны по правилу (CPU p95 × 1,15, память max × 1,2, минимум 50m/64Mi)
      с округлением — каждое число обосновано в `rightsizing.md`
- [ ] Для сравнения получены рекомендации VPA (`updateMode: "Off"`) или Goldilocks
- [ ] Новые манифесты применены (memory limit = request), через 1–2 часа — таблица «после»
- [ ] Посчитано: сколько vCPU и GiB освободилось и сколько это в $/мес (1 vCPU ≈ $30, 1 GiB ≈ $4)
- [ ] Проверено, что после rightsizing нет OOMKilled и throttling (запросы из темы 02)
- [ ] Бонус: в kind ≥ 1.35 одному поду request изменён на лету через `--subresource resize`

### Критерии приёмки
```bash
P='http://localhost:9090/api/v1/query'
q() { curl -s -G "$P" --data-urlencode "query=$1" | jq -r '.data.result[] | "\(.metric) \(.value[1])"'; }
q 'sum by (namespace) (node_namespace_pod_container:container_cpu_usage_seconds_total:sum_rate5m{namespace="demo"}) / sum by (namespace) (namespace_cpu:kube_pod_container_resource_requests:sum{namespace="demo"})'
q 'quantile_over_time(0.95, workload_container:cpu_usage_cores:max_rate5m{namespace="demo"}[2h])'
q 'max_over_time(workload_container:memory_working_set_bytes:max{namespace="demo"}[2h]) / 2^20'
kubectl -n demo get pods -o custom-columns=NAME:.metadata.name,RESTARTS:.status.containerStatuses[0].restartCount
kubectl get events -n demo --field-selector reason=OOMKilling   # пусто
```text
`rightsizing.md`:
```text
| workload | реплик | CPU req до → p95 → после | Mem req до → max → после | освобождено |
| эффективность CPU namespace: до X% → после Y% | памяти: до X% → после Y% |
| итог: −N vCPU, −M GiB ≈ −$K/мес; на kind это не деньги, в облаке — ноды (объясни почему) |
```text
### Вопросы себе
- Почему на kind rightsizing не уменьшил «счёт», а в облаке уменьшил бы? Что должно произойти с нодами?
- Почему VPA для `nginx` рекомендует больше памяти, чем ты насчитал?
- Как изменился бы расчёт, если бы `podinfo` был под HPA с target 50%?
- Что опаснее: занизить CPU request или memory request? Почему?

---

## 🧪 Лаба 2. ⭐ OpenCost с custom pricing и showback по командам

### Что делаем
Ставим OpenCost рядом с kube-prometheus-stack, задаём цены «своего железа», делаем
showback по namespace и по лейблу `team`, распределяем общие расходы и idle, выводим
стоимость в Grafana и настраиваем алерт на всплеск.

### Каркас
1. Разнеси workload из лабы 1 по командам — добавь namespace:
```bash
kubectl create namespace team-data
kubectl label namespace team-data owner=team-data env=dev
# перенеси worker в team-data (поменяй namespace в манифесте и примени), podinfo/nginx оставь в demo
```text
2. Посчитай цены (запиши расчёт в `pricing.md`): «сервер 32 vCPU / 128 GiB, полная стоимость
   $600/мес, 50/50 CPU/RAM, storage $0,05/ГБ·мес» — по разделу 4 темы 04.
3. `values-opencost.yaml` — из темы 04 (раздел 3) со своими ценами. Установка:
```bash
helm repo add opencost-charts https://opencost.github.io/opencost-helm-chart && helm repo update
helm install opencost opencost-charts/opencost -n opencost --create-namespace -f values-opencost.yaml
kubectl -n opencost port-forward svc/opencost 9003:9003 9091:9090 &
```text
4. Showback-скрипт:
```bash
#!/usr/bin/env bash
# showback.sh — расходы по namespace за окно, с idle
set -euo pipefail
WINDOW="${1:-1d}"
curl -sG localhost:9003/allocation/compute \
  -d window="$WINDOW" -d aggregate=namespace -d accumulate=true -d includeIdle=true \
| jq -r '.data[0] | to_entries | sort_by(-.value.totalCost)[]
    | [.key, (.value.cpuCost*1000|round/1000), (.value.ramCost*1000|round/1000),
       (.value.pvCost*1000|round/1000), (.value.totalCost*1000|round/1000),
       ((.value.totalEfficiency // 0)*100|round)] | @tsv' \
| (printf 'namespace\tcpu$\tram$\tpv$\ttotal$\teff%%\n'; cat) | column -t -s$'\t'
```text
### Требования
- [ ] OpenCost `Running`, таргет в Prometheus `UP`, `node_total_hourly_cost` возвращает значения
- [ ] `pricing.md`: расчёт цен за vCPU·ч, GiB·ч, GiB·ч storage и обратная проверка до $600/мес
- [ ] Месячный прогноз кластера `sum(node_total_hourly_cost) * 730` совпадает с ручным расчётом
      (vCPU и GiB нод kind × цены × 730) с точностью до округлений
- [ ] `showback.sh` выводит таблицу по namespace, есть строка `__idle__`
- [ ] Showback по `label:team`: объяснено, что попало в `__unallocated__` и почему
- [ ] `showback.md`: общие расходы (kube-system, monitoring, opencost, …) и idle распределены
      пропорционально прямым расходам команд; итог сходится со стоимостью кластера
- [ ] Recording rule `namespace:opencost_hourly_cost:sum` и дашборд из 4 панелей (тема 04, раздел 8)
- [ ] Алерт `NamespaceCostSpike` (стендовая версия из задачи C6 темы 04) спровоцирован и погашен
- [ ] Бонус: `kubectl cost` — прогноз и `--historical`, объяснена разница

### Критерии приёмки
```bash
curl -s localhost:9003/metrics | grep -c '^node_total_hourly_cost'
./showback.sh 1d
curl -sG localhost:9003/allocation/compute -d window=1d -d aggregate=label:team -d accumulate=true \
  | jq '.data[0] | map_values(.totalCost)'
curl -s -G localhost:9090/api/v1/query --data-urlencode 'query=sum(node_total_hourly_cost) * 730' | jq '.data.result[0].value[1]'
curl -s localhost:9090/api/v1/rules | jq -r '.data.groups[].rules[] | select(.name|test("opencost|Cost")) | "\(.name) \(.health)"'
```text
### Вопросы себе
- Почему сумма расходов команд меньше стоимости кластера и куда деть разницу в chargeback?
- Idle на kind огромный — почему, и что сделало бы с ним облако с Karpenter?
- Как изменится showback, если перейти с 50/50 на реальное соотношение цен CPU и RAM?
- Что бы ты показал команде `team-shop` на cost review, кроме суммы?

---

## 🧪 Лаба 3. Dev спит ночью: KEDA cron и scale to zero

### Что делаем
Выключаем «dev-окружение» вне рабочих часов и включаем по расписанию: сначала KEDA cron
на каждом Deployment, потом — kube-downscaler на весь namespace. Добавляем «пробуждение
по трафику». Считаем экономию.

### Каркас
```bash
helm repo add kedacore https://kedacore.github.io/charts && helm repo update
helm install keda kedacore/keda -n keda --create-namespace
kubectl create namespace dev
kubectl -n dev create deployment api --image=nginx:1.29 --replicas=2
kubectl -n dev create deployment web --image=nginx:1.29 --replicas=2
kubectl -n dev set resources deployment/api deployment/web --requests=cpu=100m,memory=64Mi --limits=memory=64Mi
```text
```yaml
# dev-office-hours.yaml — окно поставь на ближайшие 10 минут, чтобы увидеть оба перехода
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata: { name: api-office-hours, namespace: dev }
spec:
  scaleTargetRef: { name: api }
  minReplicaCount: 0
  maxReplicaCount: 2
  cooldownPeriod: 60                 # для стенда: ноль через минуту после конца окна
  triggers:
    - type: cron
      metadata:
        timezone: Asia/Almaty
        start: 30 14 * * *           # ← подставь «сейчас + 2 мин»
        end: 40 14 * * *             # ← «сейчас + 12 мин»
        desiredReplicas: "2"
```text
Второй ScaledObject — для `web` (тот же шаблон). Затем:
```bash
kubectl apply -f dev-office-hours.yaml
kubectl -n dev get so,hpa,deploy -w
```text
### Требования
- [ ] ScaledObject'ы в статусе `READY=True`; найдены HPA `keda-hpa-*`, созданные KEDA
- [ ] Замерено: когда реплики поднялись после `start` и когда стало 0 после `end`; сравнено
      с `pollingInterval` и `cooldownPeriod`
- [ ] Добавлен второй триггер (prometheus: есть запросы к `web` за 5 минут → 1 реплика) —
      dev «просыпается» вне окна при трафике; проверено нагрузкой
- [ ] GoKubeDownscaler: аннотация `downscaler/uptime` на namespace `dev2` с короткими
      окнами, один Deployment исключён `downscaler/exclude`
- [ ] Таблица сравнения KEDA cron и downscaler: удобство для 30 сервисов, исключения, пробуждение
- [ ] Расчёт экономии для «настоящего» dev: 12 нод по $146, пн–пт 09:00–20:00, 2 ноды баз 24/7
      (ответ сверь с задачей C9 темы 03)
- [ ] Объяснено, почему на kind экономии нет, а в облаке нужен ещё автоскейлер нод

### Критерии приёмки
```bash
kubectl -n dev get scaledobject          # колонки READY / ACTIVE / FALLBACK
kubectl -n dev get hpa
kubectl -n dev get deploy               # вне окна: 0/0
kubectl -n keda logs deploy/keda-operator --tail=50 | grep -i -E 'scal|cron'
```text
### Вопросы себе
- Почему `desiredReplicas: "0"` — ошибка, а ноль даёт `minReplicaCount`?
- Что будет с базой данных в dev, если гасить её вместе с приложением, и в каком порядке поднимать?
- Как дать разработчику «поработать в субботу» без правки манифестов?
- Почему в Казахстане важно, чтобы в образе KEDA была свежая tzdata?

---

## 🧪 Лаба 4. ⭐ Infracost на Terraform + дифф в MR + политики

### Что делаем
Оцениваем стоимость Terraform-кода без облачного аккаунта, настраиваем в GitLab CI джобу,
которая пишет дифф стоимости в MR, добавляем conftest-политики и tflint на теги.

### Каркас
```text
finops-lab/infra/
├── aws/dev/main.tf             # код из шапки 05_infracost_iac_tasks.md + default_tags и variables
├── aws/dev/dev.tfvars
├── infracost-usage.yml         # NAT 500 ГБ, лог-группа 100 ГБ приёма / 200 ГБ хранения
├── infracost.yml               # проект dev с usage-файлом и tfvars
├── .tflint.hcl                 # aws_resource_missing_tags
└── policy/
    ├── cost/cost.rego          # лимит роста $200/мес
    └── plan/plan.rego          # теги, gp2, типы инстансов в dev
```text
Отдельно попробуй Infracost на проекте из практики Terraform —
`11-blueprint`
(`~/Projects/devops/11-blueprint/environments/dev`): там провайдер `docker`, и Infracost
честно скажет, что оценивать нечего. Это нормальный результат — объясни его.

```bash
cd finops-lab/infra
infracost auth login
infracost breakdown --config-file infracost.yml
infracost breakdown --config-file infracost.yml --format json --out-file /tmp/base.json
# правка: m6i.large → m6i.xlarge, второй NAT
infracost diff --config-file infracost.yml --compare-to /tmp/base.json

infracost breakdown --path ~/Projects/devops/11-blueprint/environments/dev --show-skipped
```text
`.gitlab-ci.yml` — джобы `infracost` и `cost-policy` из темы 05 (раздел 3–4) плюс `tflint`:
```yaml
tflint:
  stage: validate
  image: { name: ghcr.io/terraform-linters/tflint:latest, entrypoint: [""] }
  rules: [{ if: $CI_PIPELINE_SOURCE == "merge_request_event" }]
  script:
    - cd infra && tflint --init && tflint --recursive
```text
### Требования
- [ ] `breakdown` работает без AWS-кредов; в отчёте объяснено, какие строки — почасовые,
      какие — «depends on usage»
- [ ] Дифф `m6i.large → m6i.xlarge` + второй NAT посчитан руками и сверен с `infracost diff`
- [ ] Usage-файл заполнен и объяснено, откуда в реальности брать эти числа
- [ ] Для 11-blueprint объяснено, почему Infracost ничего не оценил (провайдер `docker`)
- [ ] В GitLab MR появляется комментарий Infracost и **обновляется** при следующем пуше
- [ ] `cost-policy` падает на MR с ростом > $200/мес и проходит на маленьком изменении
- [ ] `plan.rego` проверен на plan JSON из задачи C5 темы 05 (3 `deny`)
- [ ] tflint ловит ресурс без `cost-center` при удалении тега из `default_tags`
- [ ] Бонус: тот же код через CLI v2 — `infracost scan` и `infracost inspect --top 5`

### Критерии приёмки
```bash
infracost --version
infracost breakdown --config-file infracost.yml --format json | jq -r '.totalMonthlyCost'
conftest test /tmp/infracost.json -p policy/cost; echo "exit=$?"
conftest test plan-sample.json -p policy/plan; echo "exit=$?"     # exit=1, три deny
tflint --recursive; echo "exit=$?"
```text
+ ссылка на MR (или скриншот) с комментарием Infracost и упавшей/прошедшей `cost-policy`.

### Вопросы себе
- Почему дифф в MR — это оценка, а не будущий счёт? Назови три причины расхождения.
- Как быть с ресурсами Yandex Cloud, которых Infracost не знает?
- Что делать, если рост стоимости оправдан (новый сервис), а политика красная?
- Как не выжечь бесплатный лимит запусков в монорепо с 40 проектами?

---

## 🧪 Лаба 5. Cost review воображаемого счёта

### Что делаем
Ты — девопс SaaS-проекта linkd (AWS, регион eu-central-1). Тебе дали счёт за сентябрь и метрики.
Нужно подготовить cost review: 5 находок, для каждой — доказательство, действие, расчёт
экономии, риск и владелец. Цены иллюстративные.

### Каркас — исходные данные

| # | Строка счёта | Детали | $ / мес |
|---|--------------|--------|---------|
| 1 | EC2: EKS prod | 30 × m6i.xlarge on-demand 24/7 ($0,192/ч) | 4 205 |
| 2 | EC2: EKS stage + dev | 12 × m6i.xlarge on-demand 24/7 | 1 682 |
| 3 | EKS control plane | 3 кластера | 219 |
| 4 | RDS PostgreSQL prod | db.r6g.2xlarge Multi-AZ | 1 500 |
| 5 | RDS PostgreSQL stage | db.r6g.xlarge Single-AZ, 24/7 | 380 |
| 6 | EBS volumes | 25 ТБ gp2 ($0,10/ГБ), из них 6 ТБ — unattached | 2 500 |
| 7 | EBS snapshots | 40 ТБ, ежедневные с 2023 года, без удаления | 2 000 |
| 8 | NAT gateway | 3 шлюза + 8 ТБ обработки (в основном S3 и ECR) | 459 |
| 9 | Data transfer inter-AZ | 40 ТБ | 800 |
| 10 | Data transfer out | 15 ТБ (картинки отдаются напрямую из S3, без CDN) | 1 350 |
| 11 | CloudWatch Logs | приём 3 ТБ ($0,50/ГБ) + хранение 60 ТБ ($0,03/ГБ), retention «never» | 3 300 |
| 12 | S3 | 50 ТБ Standard (архив логов и бэкапы, читаются редко) | 1 150 |
| 13 | Public IPv4 | 60 адресов, из них 25 EIP не привязаны | 219 |
| 14 | ALB | 14 балансировщиков (по одному на сервис) | 308 |
| | **Итого** | | **20 072** |

Метрики: эффективность CPU requests в prod — 18%, памяти — 35%; idle — 30%; stage/dev
используются пн–пт 09:00–19:00; RDS prod — CPU 12% в среднем, p95 — 20%; 60 млн запросов в месяц;
savings plans и резервов нет.

Шаблон отчёта:
```markdown
# Cost review — linkd, сентябрь 2026
## Итог
Счёт $20 072; $ за 1000 запросов: …; потенциал экономии: $… (…%)
## Находки
### 1. &lt;название&gt;
- Доказательство: строки счёта / метрики
- Действие: что именно сделать (с командами/манифестами, если уместно)
- Экономия: расчёт по шагам → $…/мес
- Риск и как его закрыть:
- Владелец и срок:
### 2. … ### 5. …
## Что НЕ трогаем и почему
## Action items (таблица: что, кто, когда, $)
```text
### Требования
- [ ] Посчитана юнит-метрика «$ за 1000 запросов» до и после предложенных мер
- [ ] 5 находок, у каждой — доказательство, действие, **расчёт** экономии по шагам, риск, владелец
- [ ] Находки отсортированы по экономии; порядок действий учитывает «сначала rightsizing, потом резервы»
- [ ] Хотя бы одна находка — про сеть (NAT, cross-AZ или egress), одна — про хранение/логи
- [ ] Раздел «что не трогаем»: например, Multi-AZ у prod-RDS — почему это цена надёжности (SLO)
- [ ] Суммарная экономия и новый счёт; проверка, что не посчитал одно и то же дважды
- [ ] Action items с владельцами-командами и сроками

### Критерии приёмки
Файл `cost-review-2026-09.md` в репозитории; каждое число можно пересчитать по данным
из таблицы; нет действий, которые ломают SLO без оговорки.

<details>
<summary>Ориентиры для самопроверки (не подглядывай до своей версии)</summary>

```text
Юнит-метрика: $20 072 / 60 000 = $0,335 за 1000 запросов.

1. Rightsizing prod + savings plan (строка 1)
   эффективность 18% → цель ~50%: нужно ~0,18/0,5 = 36% текущих requests → ~11 нод + запас → 14 нод
   −16 нод × $140 = −$2 240; savings plan 1 год (−30%) на 14 нод: 14 × 140 × 0,3 = −$588
   итого ≈ −$2 830 (сначала rightsizing и consolidation, потом SP!)
2. Логи CloudWatch (строка 11)
   retention 30 дней: хранение 60 ТБ → ~3 ТБ: (60 000 − 3 000) × $0,03 ≈ −$1 710
   + уровни/сэмплинг −50% приёма: 1 500 × 0,5 = −$750 → итого ≈ −$2 460
3. Снапшоты (строка 7)
   хранить 30 дней ежедневных + 12 месячных: 40 ТБ → ~5 ТБ (оценка) → 35 000 × $0,05 ≈ −$1 750
4. Stage/dev по расписанию (строки 2, 5)
   50 ч из 168 = 30%: 1 682 × 0,7 ≈ −$1 180; RDS stage стоп вне часов: 380 × 0,7 ≈ −$265
   итого ≈ −$1 440
5. EBS (строка 6)
   удалить 6 ТБ unattached (после владельца и снапшота): −$600;
   gp2 → gp3 на остальных 19 ТБ: 19 000 × ($0,10 − $0,08) = −$380 → итого ≈ −$980
Ещё: S3 gateway endpoint (NAT, ~−$300), 25 EIP (−$91), lifecycle S3 (−$600+), CDN для картинок,
общий ALB через Ingress (−$200+), RDS prod — меньший класс после наблюдения (осторожно).

Топ-5 ≈ $9 460 → новый счёт ≈ $10 600 (−47%), ≈ $0,18 за 1000 запросов.
```text
</details>

### Вопросы себе
- Какие из находок можно сделать за один день, а какие требуют недель и согласований?
- Где риск для SLO самый высокий и как ты его закроешь (канарейка, наблюдение, откат)?
- Почему savings plan нельзя покупать до rightsizing и на какую сумму его покупать после?
- Как ты объяснишь финансам, почему после оптимизации счёт снова начнёт расти?

---

## 🏁 Что должно остаться после блока

```text
finops-lab/
├── README.md                     # что сделано и главные цифры «до/после»
├── k8s/
│   ├── demo.yaml, demo-rightsized.yaml
│   ├── finops-rightsizing-rules.yaml, opencost-cost-rules.yaml
│   ├── values-opencost.yaml
│   └── keda/dev-office-hours.yaml
├── reports/
│   ├── rightsizing.md            # таблица эффективности до/после
│   ├── pricing.md                # расчёт custom-цен из TCO
│   ├── showback.md               # расходы команд с общими расходами и idle
│   └── cost-review-2026-09.md    # 5 находок с экономией
├── grafana/finops-dashboard.json
├── infra/                        # Terraform + infracost.yml + usage + .tflint.hcl + policy/
└── .gitlab-ci.yml                # tflint → infracost → cost-policy
```text
Это превращает «знаю, что такое FinOps» в «вот как я нашёл 47% экономии в счёте, вот
Infracost в MR, вот showback по командам и dev, который спит ночью».

➡️ Дальше: [07_interview.md](/english/07-interview)
