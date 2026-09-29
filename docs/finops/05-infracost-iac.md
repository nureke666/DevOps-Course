---
title: "05. FinOps в инфраструктурном коде: Infracost, теги, бюджеты, чистка"
description: "Блок → FinOps → тема 05. Опирается на"
---

# 05. FinOps в инфраструктурном коде: Infracost, теги, бюджеты, чистка

> Блок → FinOps → тема 05. Опирается на
> [../Left/06_Terraform/00_INDEX.md](/terraform/),
> [../Left/06_Terraform/06_workflow_cicd.md](/terraform/06-workflow-cicd) (plan в MR,
> там Infracost упомянут одной строкой — здесь разбираем),
> [../CICD/06_gitlab_ci_core.md](/cicd/06-gitlab-ci-core) (`rules`, `artifacts`, variables),
> [../Left/04_Cloud/04_s3_storage.md](/cloud/04-s3-storage) (lifecycle) и тему
> [01](/finops/01-finops-intro) (теги, бюджеты).
>
> **После темы ты умеешь:** оценить стоимость Terraform-кода до `apply` Infracost'ом (обе
> версии CLI), показать дифф стоимости в GitLab MR, остановить дорогой MR политикой
> (conftest), навязать теги через `default_tags` и tflint, завести бюджеты и детектор аномалий,
> найти и убрать «сирот», настроить lifecycle и retention и провести ежемесячный cost review.

---

## 🗺️ Карта темы

```text
  ДО apply (shift-left)                  ПОСЛЕ apply (guardrails)            ПОСТОЯННО
 ─────────────────────────────         ──────────────────────────────     ─────────────────────
 MR с .tf                               бюджеты + алерты (факт/прогноз)    cost review раз в месяц
  ├─ terraform plan                     детектор аномалий                  чистка сирот
  ├─ infracost diff → коммент в MR      default_tags → allocation          lifecycle S3, retention логов
  ├─ conftest: лимит роста $, gp3,      tag policies / SCP                 очистка registry
  │  теги, типы инстансов
  └─ tflint: aws_resource_missing_tags
         │
         ▼
 «этот MR добавит +$412/мес» видят ДО мержа, а не в счёте через месяц
```text
---

## 1. Infracost: что это и какая версия

Infracost читает Terraform (HCL или plan JSON), Terragrunt, CloudFormation, CDK, находит
ресурсы, берёт цены из своего Cloud Pricing API и показывает месячную стоимость и дифф.
**Облачные креды не нужны**: код разбирается локально, в API уходят только параметры для
цены (тип инстанса, размер диска, регион), без секретов и без plan JSON.

Поддерживаемые облака — **AWS, Azure, Google Cloud**. Для Yandex Cloud и других провайдеров
Infracost ресурсы не оценит (покажет как unsupported) — там считаешь сам по прайсу или
тегами по факту.

В 2026 году есть **два поколения CLI** — важно не перепутать документацию:

| | Классический CLI **v0.10** | Новый CLI **v2** («Infracost 2.0») |
|---|---------------------------|-----------------------------------|
| Репозиторий | `infracost/infracost` (legacy, но обновляется: v0.10.46 — сентябрь 2026) | `infracost/cli` (v2.16 — сентябрь 2026) |
| Установка | `curl -fsSL https://raw.githubusercontent.com/infracost/infracost/master/scripts/install.sh \| sh` | `curl -fsSL https://raw.githubusercontent.com/infracost/cli/main/scripts/install.sh \| sh` |
| Вход | `infracost auth login` → API key; в CI — `INFRACOST_API_KEY` | `infracost auth login` (браузер или `--oauth-use-device-flow`); в CI — `INFRACOST_CLI_AUTHENTICATION_TOKEN` |
| Команды | `breakdown`, `diff`, `output`, `comment`, `upload`, `configure` | `scan`, `inspect`, `price`, `setup`, `policies`, `budgets`, `guardrails` |
| CI | Официальный шаблон GitLab CI на образе `infracost/infracost:ci-0.10` | Интеграция с GitLab/GitHub как приложение (`infracost ci setup`) |
| Когда брать | ⭐ Пайплайны `breakdown → diff → comment` (так устроено большинство существующих проектов) | Новые проекты, локальный анализ с политиками и тегами |

```bash
infracost --version     # 0.10.x → breakdown/diff;  2.x → scan/inspect
```text
**Регистрация (бесплатно, без облачного аккаунта):**
```bash
infracost auth login              # откроется браузер: вход через GitHub/Google/email
infracost configure get api_key   # v0.10: показать ключ — положить в CI как INFRACOST_API_KEY (masked)
```text
Бесплатный план (на сентябрь 2026) — оценки стоимости с лимитом в 1000 запусков в месяц.
FinOps- и tagging-политики, guardrails и дашборды — в платном Infracost Cloud.
Поэтому политики в этой теме — на бесплатном conftest (раздел 4).

---

## 2. Команды

### v0.10: breakdown и diff

```bash
cd infra/aws
infracost breakdown --path .                                   # таблица месячных расходов
infracost breakdown --path . --show-skipped                    # + какие ресурсы не оценены и почему
infracost breakdown --path . --format json --out-file /tmp/base.json   # снимок «до»

# … правишь .tf (новый инстанс, другой тип) …
infracost diff --path . --compare-to /tmp/base.json           # что изменится в $/мес

infracost breakdown --path . --terraform-var-file prod.tfvars # с переменными окружения
infracost output --path /tmp/base.json --format html --out-file report.html
```text
Пример вывода (цифры иллюстративные, порядок us-east-1):
```text
 Name                                                   Monthly Qty  Unit     Monthly Cost
 aws_instance.app
 ├─ Instance usage (Linux/UNIX, on-demand, m6i.large)           730  hours          $70.08
 └─ root_block_device
    └─ Storage (general purpose SSD, gp3)                        30  GB              $2.40
 aws_nat_gateway.main
 ├─ NAT gateway                                                 730  hours          $32.85
 └─ Data processed                            Monthly cost depends on usage: $0.045 per GB
```text
### Usage-файл: ресурсы, которые стоят «от потребления»

У NAT, Lambda, S3, логов цена зависит от трафика и запросов — из кода её не узнать.
Такие строки Infracost помечает *«depends on usage»*, а оценку даёт usage-файл:
```yaml
# infracost-usage.yml
version: 0.1
resource_type_default_usage:          # для всех ресурсов типа
  aws_nat_gateway:
    monthly_data_processed_gb: 500
resource_usage:                       # для конкретного ресурса
  aws_cloudwatch_log_group.app:
    storage_gb: 200
    monthly_data_ingested_gb: 100
  aws_lambda_function.thumbnailer:
    monthly_requests: 2000000
    request_duration_ms: 300
```text
```bash
infracost breakdown --path . --usage-file infracost-usage.yml
infracost breakdown --path . --usage-file infracost-usage.yml --sync-usage-file   # дописать шаблон для всех usage-ресурсов
```text
Цифры для usage-файла бери из реальности: CloudWatch/биллинг прошлого месяца, метрики
Prometheus.

### Несколько окружений: `infracost.yml`

```yaml
version: 0.1
projects:                     # запускай из каталога с infracost.yml; tfvars — относительно path
  - { path: aws/dev,  name: dev,  usage_file: infracost-usage.yml, terraform_var_files: [dev.tfvars] }
  - { path: aws/prod, name: prod, usage_file: infracost-usage.yml, terraform_var_files: [prod.tfvars] }
```text
`infracost breakdown --config-file infracost.yml` — оценка всех проектов разом.

### v2: scan и inspect

```bash
infracost scan ./infra/aws                       # цены + FinOps- и tagging-проверки, результат кэшируется
infracost inspect --summary                      # итоги и число нарушений
infracost inspect --top 5                        # 5 самых дорогих ресурсов
infracost inspect --top-savings 5                # 5 находок с наибольшей экономией
infracost inspect --missing-tag owner            # ресурсы без тега owner

terraform plan -out tfplan.binary && terraform show -json tfplan.binary > plan.json
infracost scan plan.json                         # с v2.4.2 — оценка по plan JSON (значения plan-time)
```text
---

## 3. Infracost в GitLab MR

Процесс Terraform в CI — в [../Left/06_Terraform/06_workflow_cicd.md](/terraform/06-workflow-cicd),
`rules` и артефакты — в [../CICD/06_gitlab_ci_core.md](/cicd/06-gitlab-ci-core). Джоба по
официальному шаблону (v0.10):

```yaml
# .gitlab-ci.yml (фрагмент)
stages: [validate, plan, cost]

variables:
  TF_ROOT: infra/aws/dev
  # INFRACOST_API_KEY и GITLAB_TOKEN — в Settings → CI/CD → Variables (masked)

infracost:
  stage: cost
  image:
    name: infracost/infracost:ci-0.10
    entrypoint: [""]
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes: ["infra/**/*"]
  script:
    # 1. стоимость целевой ветки (baseline)
    - git clone $CI_REPOSITORY_URL --branch=$CI_MERGE_REQUEST_TARGET_BRANCH_NAME --single-branch /tmp/base
    - infracost breakdown --path=/tmp/base/${TF_ROOT} --format=json --out-file=infracost-base.json
    # 2. дифф ветки MR против baseline
    - infracost diff --path=${TF_ROOT} --compare-to=infracost-base.json --format=json --out-file=infracost.json
    # 3. комментарий в MR (обновляет один и тот же комментарий)
    - infracost comment gitlab --path=infracost.json --repo=$CI_PROJECT_PATH
        --merge-request=$CI_MERGE_REQUEST_IID --gitlab-server-url=$CI_SERVER_URL
        --gitlab-token=$GITLAB_TOKEN --behavior=update
  artifacts:
    paths: [infracost.json]
    expire_in: 7 days
```text
| Деталь | Почему так |
|--------|-----------|
| Baseline из целевой ветки | Дифф честный: сравнивается ровно то, во что мержим |
| `--behavior=update` | Один комментарий обновляется при каждом пуше (есть `new`, `hide-and-new`, `delete-and-new`) |
| `GITLAB_TOKEN` со scope `api` | Писать комментарии в MR; на self-managed подойдёт project access token |
| `INFRACOST_API_KEY` masked | Ключ не светится в логах |
| `rules: changes` | Не гонять джобу, если инфраструктура не менялась |
| `artifacts: infracost.json` | Следующая джоба (политики) читает результат |

В MR появляется комментарий вида «Monthly cost will increase by $412 (+18%)» с таблицей
изменений по ресурсам — ревьюер видит цену до мержа.

---

## 4. Политики стоимости: conftest

Два вида проверок — на **деньги** (JSON Infracost) и на **конфигурацию** (plan JSON Terraform).

```rego
# policy/cost/cost.rego — вход: infracost.json
package main

import rego.v1

deny contains msg if {
	diff := to_number(input.diffTotalMonthlyCost)
	diff > 200
	msg := sprintf("MR увеличивает расходы на $%.2f/мес (лимит $200) — нужен апрув FinOps", [diff])
}

warn contains msg if {
	some project in input.projects
	some r in project.breakdown.resources
	to_number(r.monthlyCost) > 500
	msg := sprintf("%s стоит $%s/мес — проверь размер", [r.name, r.monthlyCost])
}
```text
```rego
# policy/plan/plan.rego — вход: terraform show -json tfplan > plan.json
package main

import rego.v1

required_tags := {"owner", "env", "service", "cost-center"}

deny contains msg if {
	some rc in input.resource_changes
	some action in rc.change.actions
	action in {"create", "update"}
	tags := rc.change.after.tags_all            # tags_all включает default_tags провайдера
	missing := required_tags - object.keys(tags)
	count(missing) > 0
	msg := sprintf("%s: нет тегов %v", [rc.address, missing])
}

deny contains msg if {
	some rc in input.resource_changes
	rc.type == "aws_ebs_volume"
	rc.change.after.type == "gp2"
	msg := sprintf("%s: используй gp3 — дешевле gp2 примерно на 20%%", [rc.address])
}

deny contains msg if {
	input.variables.env.value == "dev"
	some rc in input.resource_changes
	rc.type == "aws_instance"
	not regex.match(`\.(nano|micro|small|medium|large)$`, rc.change.after.instance_type)
	msg := sprintf("%s: в dev разрешены типы до *.large, а не %s", [rc.address, rc.change.after.instance_type])
}
```text
```yaml
cost-policy:
  stage: cost
  needs: [infracost, plan]                  # plan-джоба кладёт plan.json в artifacts
  image: { name: openpolicyagent/conftest:latest, entrypoint: [""] }
  rules: [{ if: $CI_PIPELINE_SOURCE == "merge_request_event" }]
  script:
    - conftest test infracost.json -p policy/cost
    - conftest test ${TF_ROOT}/plan.json -p policy/plan
```text
`deny` роняет джобу, `warn` — только предупреждает. Для исключений — лейбл MR
«finops-approved» и `rules`, пропускающие `deny` при нём, либо ручная джоба-апрув.

> 💡 Числа в JSON Infracost — строки (`"123.45"`), отсюда `to_number`. `diffTotalMonthlyCost`
> есть только в выводе `diff`. В Infracost Cloud есть готовые FinOps-политики и guardrails
> («заблокировать MR дороже $X») — это платная замена conftest.

---

## 5. Обязательные теги в Terraform

```hcl
provider "aws" {
  region = "eu-central-1"
  default_tags {                       # ⭐ ставятся на все поддерживающие теги ресурсы провайдера
    tags = {
      "owner"       = var.owner
      "env"         = var.env
      "service"     = var.service
      "cost-center" = var.cost_center
      "managed-by"  = "terraform"
    }
  }
}

variable "env" {
  type = string
  validation {
    condition     = contains(["prod", "stage", "dev", "sandbox"], var.env)
    error_message = "env: prod, stage, dev или sandbox."
  }
}
# так же для owner: can(regex("^team-[a-z0-9-]+$", var.owner)) — команда, а не человек
```text
Проверка в CI — tflint с AWS-плагином (правило учитывает `default_tags` провайдера):
```hcl
# .tflint.hcl
plugin "aws" {
  enabled = true
  version = "0.49.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}

rule "aws_resource_missing_tags" {
  enabled = true
  tags    = ["owner", "env", "service", "cost-center"]
}
```text
```bash
tflint --init && tflint --recursive
```text
| Где теги «теряются» | Что делать |
|---------------------|-----------|
| Ресурсы, созданные не Terraform'ом (ноды Karpenter, диски PVC, LB от Service) | Karpenter — `spec.tags` в EC2NodeClass; CSI-драйвер и LB-контроллер — свои параметры тегов |
| Инстансы ASG, диски из launch template | `tag_specifications` в launch template, `propagate_at_launch` |
| Ресурсы, созданные руками в консоли | SCP/Tag Policies в AWS Organizations: запрет создания без тегов; отчёт «без owner» |
| Cost Explorer не видит теги | Активировать ключи как cost allocation tags |
| Yandex Cloud | `labels` на ресурсах (ключи строчными); общий набор держи в `locals` и мёржи `merge(local.labels, {...})` |

---

## 6. Бюджеты и детектор аномалий

**AWS Budgets в Terraform:**
```hcl
resource "aws_budgets_budget" "monthly_total" {
  name         = "monthly-total"
  budget_type  = "COST"
  limit_amount = "3000"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"        # по факту
    subscriber_email_addresses = ["platform@example.kz"]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"    # ⭐ по прогнозу — узнаёшь в середине месяца
    subscriber_email_addresses = ["platform@example.kz"]
  }
}

resource "aws_budgets_budget" "dev" {
  # … те же name, budget_type, limit_*, time_unit и notification (получатель — команда), плюс:
  cost_filter {
    name   = "TagKeyValue"
    values = ["user:env$dev"]                     # формат: user:&lt;ключ&gt;$&lt;значение&gt;
  }
}
```text
Детектор аномалий AWS — Cost Anomaly Detection (`aws_ce_anomaly_monitor` +
`aws_ce_anomaly_subscription`): мониторит расходы по сервисам/тегам и шлёт ежедневные
или мгновенные уведомления. Budget Actions умеют применить IAM/SCP-политику или остановить
инстансы — для песочниц полезно, для прода опасно.

**Yandex Cloud:** бюджеты создаются в Billing (консоль/API): «на потребление» — по стоимости
потребления без скидок или «к оплате» со скидками — и «на остаток средств». Пороги в процентах
или суммах, уведомления выбранным пользователям. ⚠️ Достижение порога **не останавливает**
ресурсы; для автоматики — триггер «Бюджет» для Cloud Functions/Serverless Containers
(например, функция, останавливающая ВМ с `env=dev`).

---

## 7. «Сироты»: найти и убрать

**AWS CLI:**
```bash
# диски, не подключённые ни к одной ВМ
aws ec2 describe-volumes --filters Name=status,Values=available \
  --query 'Volumes[].{ID:VolumeId,GiB:Size,Type:VolumeType,Created:CreateTime}' --output table

# свои снапшоты старше даты
aws ec2 describe-snapshots --owner-ids self \
  --query "Snapshots[?StartTime<='2026-03-01'].{ID:SnapshotId,GiB:VolumeSize,Start:StartTime}" --output table

# Elastic IP без привязки (платные: $0,005/ч)
aws ec2 describe-addresses --query 'Addresses[?AssociationId==null].[PublicIp,AllocationId]' --output table

# «пустой» балансировщик: запросов за 7 дней
aws cloudwatch get-metric-statistics --namespace AWS/ApplicationELB --metric-name RequestCount \
  --dimensions Name=LoadBalancer,Value=app/my-alb/0123456789abcdef \
  --start-time "$(date -u -d '-7 days' +%FT%TZ)" --end-time "$(date -u +%FT%TZ)" \
  --period 604800 --statistics Sum

# лог-группы без retention (хранятся вечно)
aws logs describe-log-groups --query 'logGroups[?!retentionInDays].[logGroupName,storedBytes]' --output table
```text
**Yandex Cloud (`yc`):**
```bash
yc compute disk list --format json \
  | jq -r '.[] | select((.instance_ids // []) | length == 0) | [.id, .name, (.size|tonumber/1073741824)] | @tsv'
yc vpc address list --format json | jq -r '.[] | select(.used != true) | [.id, .external_ipv4_address.address] | @tsv'
yc compute snapshot list
```text
**Kubernetes:** PV в статусе `Released` (`kubectl get pv | grep Released`) — диск в облаке всё
ещё оплачивается при `reclaimPolicy: Retain`; Service `type: LoadBalancer`, про которые забыли;
PVC удалённых стендов.

**Registry:** старые образы — это деньги за хранение (и шум).
```json
{
  "rules": [{
    "rulePriority": 1,
    "description": "Хранить последние 20 образов",
    "selection": { "tagStatus": "any", "countType": "imageCountMoreThan", "countNumber": 20 },
    "action": { "type": "expire" }
  }]
}
```text
```bash
aws ecr put-lifecycle-policy --repository-name shop-api --lifecycle-policy-text file://ecr-lifecycle.json
```text
В GitLab Container Registry — cleanup policy проекта (Settings → Packages and registries):
держать N последних тегов по regex, удалять старше X дней.

**cloud-nuke — только для песочниц ⚠️:**
```bash
cloud-nuke inspect-aws --region eu-central-1 --older-than 24h          # только посмотреть
cloud-nuke aws --list-resource-types                                    # какие типы умеет
cloud-nuke aws --region eu-central-1 --resource-type ec2 --resource-type ami --older-than 24h --dry-run
```text
> ⚠️ cloud-nuke удаляет **всё** подходящее в аккаунте. Запускать только в отдельном
> sandbox-аккаунте, никогда — в аккаунте с продом или общими ресурсами; сначала `inspect-aws`
> и `--dry-run`, исключения — через `--config`. Для прода чистка — только кодом (Terraform)
> и по согласованию с владельцем.

Правило чистки: **найти → найти владельца (теги, CloudTrail) → предупредить → снапшот при
сомнениях → удалить**. Автоматика: TTL-тег (`expires=2026-10-15`) на песочницах и джоба, удаляющая просроченное.

---

## 8. Хранение: lifecycle и retention

Основы lifecycle — в [../Left/04_Cloud/04_s3_storage.md](/cloud/04-s3-storage). В Terraform:
```hcl
resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    id     = "logs-tiering"
    status = "Enabled"
    filter {
      prefix = "logs/"
    }
    transition {
      days          = 30
      storage_class = "STANDARD_IA"      # ~$0,0125 за ГБ·мес против ~$0,023 у Standard
    }
    transition {
      days          = 90
      storage_class = "GLACIER_IR"       # ~$0,004 за ГБ·мес, мгновенное чтение, но платное извлечение
    }
    expiration {
      days = 365
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}
```text
Нюансы: у STANDARD_IA минимальный срок хранения 30 дней и минимальный оплачиваемый размер
объекта 128 КБ — миллионы мелких файлов в IA станут дороже; переходы между классами платные
(за запрос); при неизвестном профиле доступа — Intelligent-Tiering. В Yandex Object Storage
классы — STANDARD, COLD, ICE.

**Логи** ([../Left/03_Logging/00_INDEX.md](/logging/)):

| Где | Как ограничить |
|-----|----------------|
| Loki | `limits_config.retention_period` + compactor с `retention_enabled` ([../Left/03_Logging/03_loki_grafana.md](/logging/03-loki-grafana)); разный retention по tenant/стримам |
| Elasticsearch | ILM-политика: rollover в hot, удаление через N дней |
| CloudWatch Logs | `retention_in_days` в `aws_cloudwatch_log_group` (по умолчанию — **никогда не удалять**) |
| Приложение | Уровень INFO в проде, sampling повторяющихся сообщений, не логировать тела запросов |

**Метрики:** retention Prometheus по потребности (2–4 недели локально), долгосрочное — с
downsampling (Thanos/Mimir/VictoriaMetrics); главная статья — кардинальность, а не срок.

---

## 9. Привычка: ежемесячный cost review

```text
COST REVIEW — первый вторник месяца, 60 минут
участники: платформа (ведёт), тимлиды команд, FinOps/финансы

1. Итог месяца и тренд, юнит-метрики ($ за 1000 запросов, $ на клиента)    10 мин
2. Топ-10 строк счёта и всё, что выросло > 10% месяц к месяцу               15 мин
3. Аномалии месяца: что было, сколько стоило, что сделали                     10 мин
4. Статус прошлых action items                                               10 мин
5. Новые action items: что, владелец, срок, ожидаемая экономия $/мес          10 мин
6. Обязательства: coverage и utilization, истекающие резервы/savings plans     5 мин
```text
| KPI практики | Цель (ориентир) |
|--------------|-----------------|
| Доля расходов с тегами `owner`/`env` | ≥ 90–95% |
| Эффективность CPU requests (тема 02) | ≥ 50% |
| Доля idle в кластерах (тема 04) | ≤ 20–25% |
| Utilization обязательств | ≥ 95% |
| Тренд стоимости юнита | Не растёт |
| Сироты (диски, IP, снапшоты) | Ноль старше 30 дней |

Результат ревью — короткая заметка в вики/репозитории: цифры, решения, action items.
Через полгода это история, которую приятно рассказать на собесе.

---

## 10. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| Доки v2, а в CI образ `ci-0.10` | Команды `scan`/`breakdown` не находятся | Проверь `infracost --version`, держи одну версию |
| Считать Infracost «счётом» | Usage-ресурсы = $0 без usage-файла, скидки не учтены | Usage-файл по реальным данным; это оценка изменений |
| Дифф против `main`, а мержим в `release` | Сравнение не с тем | Baseline из `$CI_MERGE_REQUEST_TARGET_BRANCH_NAME` |
| Политика «запретить любой рост» | Блокирует нормальную работу | Порог + процесс апрува |
| Теги только через `tags` в каждом ресурсе | Забывают, опечатки | `default_tags` + validation + tflint |
| Бюджет без прогнозного порога | Узнаёшь в конце месяца | `FORECASTED` 100% |
| cloud-nuke «чтобы почистить» в общем аккаунте | Удалены чужие и продовые ресурсы | Только sandbox-аккаунт, `inspect`/`--dry-run` |
| Удалить «сироту» без владельца | Это был бэкап/DR-диск | Владелец → предупреждение → снапшот → удаление |
| IA-класс для мелких объектов | Минимум 128 КБ и 30 дней — дороже Standard | Считать до перехода, Intelligent-Tiering |

---

## 💼 Как это в DevOps

- Infracost в MR превращает спор «дорого/недорого» в цифру до мержа — и это одна из самых
  заметных вещей, которые девопс может внедрить за день.
- Теги задаются в провайдере и модулях один раз, проверяются tflint и политиками — после
  этого allocation «сам» становится точным.
- Бюджеты и аномалии заводятся Terraform'ом вместе с аккаунтом/проектом: новый проект без
  бюджета не создаётся.
- Чистка сирот, lifecycle и retention — регулярная гигиена: раз в месяц отчёт, раз в квартал —
  разбор с командами.
- Cost review ведёт платформа, но решения принимают владельцы сервисов: девопс приносит
  данные и варианты, а не «режет» чужое сам.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Узнать версию CLI | `infracost --version` (0.10 или 2.x) |
| Получить ключ | `infracost auth login`; v0.10: `infracost configure get api_key` |
| Стоимость кода (v0.10) | `infracost breakdown --path .` |
| Дифф (v0.10) | `breakdown --format json --out-file base.json` → `diff --compare-to base.json` |
| Стоимость кода (v2) | `infracost scan ./infra`, `infracost inspect --top 5` |
| Usage-ресурсы | `--usage-file infracost-usage.yml` (`--sync-usage-file` — шаблон) |
| Коммент в MR | `infracost comment gitlab --path=infracost.json --repo=… --merge-request=… --gitlab-token=… --behavior=update` |
| Лимит роста $ | conftest: `to_number(input.diffTotalMonthlyCost) > 200` |
| Теги везде | `default_tags` в провайдере AWS + validation |
| Проверить теги | tflint `aws_resource_missing_tags` |
| Бюджет | `aws_budgets_budget` с `ACTUAL` и `FORECASTED` |
| Непривязанные диски | `aws ec2 describe-volumes --filters Name=status,Values=available` |
| Свободные EIP | `aws ec2 describe-addresses --query 'Addresses[?AssociationId==null]'` |
| Retention логов | `aws logs put-retention-policy`, Loki `retention_period`, ES ILM |
| Чистка песочницы | `cloud-nuke inspect-aws` → `cloud-nuke aws … --dry-run` (только sandbox!) |

---

## 🧠 Что запомнить

1. Infracost оценивает стоимость кода **до** apply, без облачных кредов; только AWS, Azure, GCP.
2. В 2026 два CLI: v0.10 (`breakdown/diff/comment`, шаблоны CI) и v2 (`scan/inspect`); проверяй версию.
3. Usage-ресурсы (NAT, логи, Lambda, S3) без usage-файла выглядят бесплатными.
4. MR-пайплайн: baseline из целевой ветки → `diff` → комментарий → политики.
5. Политики: деньги — на JSON Infracost, конфигурация и теги — на plan JSON; conftest бесплатен.
6. ⭐ Теги: `default_tags` + validation + tflint + политики облака; активируй cost allocation tags.
7. Бюджет обязательно с прогнозным порогом; бюджет сам ресурсы не останавливает.
8. Сироты: найти → владелец → предупредить → снапшот → удалить; cloud-nuke — только sandbox.
9. Lifecycle и retention — «бесплатная» экономия, но с нюансами классов хранения.
10. Ежемесячный cost review с action items превращает FinOps из разовой акции в привычку.

➡️ Дальше: [06_practice_labs.md](/english/06-practice-labs) · Задачи: 05_infracost_iac_tasks.md


---

### Блок A. Теория


**A1.** Что делает Infracost? Нужны ли облачные креды и что уходит в его API?

<details><summary>Ответ</summary>

Разбирает Terraform/Terragrunt/CloudFormation/CDK, находит ресурсы, берёт цены из Cloud
Pricing API и показывает месячную стоимость и дифф. Креды облака не нужны; в API уходят только
параметры для цены (тип, размер, регион, ОС), без секретов и без plan JSON.

</details>

**A2.** Какие облака поддерживает Infracost? Что делать с ресурсами Yandex Cloud?

<details><summary>Ответ</summary>

AWS, Azure, Google Cloud. Ресурсы Yandex Cloud будут unsupported — считать по прайсу
провайдера (свой скрипт/таблица), фактические расходы — отчётами биллинга по меткам.

</details>

**A3.** ⭐ Какие два поколения CLI существуют в 2026? Как понять, какое установлено,
и какие у каждого основные команды?

<details><summary>Ответ</summary>

v0.10 (`infracost/infracost`): `breakdown`, `diff`, `output`, `comment`, `upload`, `configure`;
v2 (`infracost/cli`, Infracost 2.0): `scan`, `inspect`, `price`, `setup`, `policies`, `budgets`,
`guardrails`. Версию показывает `infracost --version` (0.10.x или 2.x).

</details>

**A4.** Как получить API-ключ и безопасно передать его в GitLab CI?

<details><summary>Ответ</summary>

`infracost auth login` (регистрация бесплатная, без облачного аккаунта), для v0.10 —
`infracost configure get api_key`; ключ — в Settings → CI/CD → Variables как `INFRACOST_API_KEY`,
masked (для v2 — `INFRACOST_CLI_AUTHENTICATION_TOKEN`).

</details>

**A5.** Почему NAT gateway, логи и Lambda в `breakdown` выглядят почти бесплатными? Что с этим делать?

<details><summary>Ответ</summary>

Их цена зависит от потребления (ГБ, запросы), которого нет в коде: Infracost показывает
«depends on usage» и $0 за эту часть. Задать usage-файл по реальным данным (биллинг, метрики).

</details>

**A6.** Опиши шаги MR-пайплайна Infracost. Почему baseline берут из целевой ветки MR?

<details><summary>Ответ</summary>

Клонировать целевую ветку → `breakdown` baseline в JSON → `diff` ветки MR против baseline →
`comment gitlab` → политики (conftest). Baseline из целевой ветки, потому что мержим именно туда:
сравнение с другой веткой покажет чужие изменения.

</details>

**A7.** Какие значения бывают у `--behavior` в `infracost comment gitlab`?

<details><summary>Ответ</summary>

`update` (один комментарий, обновляется), `new` (новый каждый раз), `hide-and-new`
(старые скрыть, новый добавить), `delete-and-new` (удалить старые, добавить новый).

</details>

**A8.** Почему политики «по деньгам» пишут на JSON Infracost, а «по конфигурации и тегам» —
на plan JSON Terraform?

<details><summary>Ответ</summary>

Деньги (итог, дифф, стоимость ресурса) есть только у Infracost. Конфигурация (типы, классы
дисков, теги с учётом `default_tags`) — в plan JSON в структурированном виде; в JSON Infracost
она спрятана в текстовых названиях компонент цены.

</details>

**A9.** ⭐ Назови уровни, на которых навязывают теги в Terraform-инфраструктуре.

<details><summary>Ответ</summary>

`default_tags` в провайдере и validation переменных; линтер (tflint
`aws_resource_missing_tags`) и политики на plan в CI; политики облака (AWS Tag Policies + SCP,
оргполитики); отчёт «без owner» постфактум; в Kubernetes — admission-политики на лейблы.

</details>

**A10.** Чем `tags` отличается от `tags_all`? Почему политика проверяет `tags_all`?

<details><summary>Ответ</summary>

`tags` — теги, заданные в самом ресурсе; `tags_all` — итог с `default_tags` провайдера.
Политика смотрит `tags_all`, иначе ресурсы, тегированные только через `default_tags`, будут
ложно помечены как нарушители.

</details>

**A11.** Где теги теряются, несмотря на `default_tags`?

<details><summary>Ответ</summary>

Ресурсы, созданные не Terraform'ом: ноды Karpenter, диски PVC (CSI), балансировщики
от Service, ресурсы, созданные руками; инстансы ASG и диски из launch template без
`tag_specifications`/`propagate_at_launch`.

</details>

**A12.** Чем `ACTUAL` отличается от `FORECASTED` в AWS Budgets? Остановит ли бюджет ресурсы?
Как с этим в Yandex Cloud?

<details><summary>Ответ</summary>

`ACTUAL` — порог по фактическим расходам, `FORECASTED` — по прогнозу на конец периода
(узнаёшь в середине месяца). Бюджет сам не останавливает; в AWS можно настроить Budget Actions
(IAM/SCP, остановка инстансов). В Yandex Cloud порог не влияет на потребление; остановку делают
триггером «Бюджет» + Cloud Functions.

</details>

**A13.** Назови 6 видов «сирот» и как их найти.

<details><summary>Ответ</summary>

Непривязанные диски (`describe-volumes status=available`), старые снапшоты
(`describe-snapshots --owner-ids self` по дате), свободные EIP (`AssociationId==null`), свои AMI,
пустые балансировщики (CloudWatch `RequestCount`), лог-группы без retention, PV `Released`,
забытые Service `LoadBalancer`, старые образы в registry.

</details>

**A14.** Почему cloud-nuke опасен и как им пользоваться безопасно?

<details><summary>Ответ</summary>

Удаляет всё подходящее в аккаунте/регионе, включая чужие и продовые ресурсы. Безопасно:
только отдельный sandbox-аккаунт, сначала `inspect-aws` и `--dry-run`, фильтры `--resource-type`,
`--older-than`, исключения через `--config`.

</details>

**A15.** Какие нюансы у перехода объектов в STANDARD_IA и Glacier?

<details><summary>Ответ</summary>

STANDARD_IA: минимум 30 дней хранения и минимальный оплачиваемый размер 128 КБ —
мелкие объекты дорожают; переходы платные за каждый запрос; Glacier: платное и/или медленное
извлечение, минимальный срок хранения (досрочное удаление оплачивается). Для неизвестного
профиля — Intelligent-Tiering.

</details>

**A16.** Что такое ежемесячный cost review, из каких пунктов состоит и какие KPI на нём смотрят?

<details><summary>Ответ</summary>

Ежемесячная встреча платформы, команд и финансов: итог и юнит-метрики, топ-10 строк
и рост > 10%, аномалии, статус и новые action items, обязательства. KPI: покрытие тегами,
эффективность requests, доля idle, utilization обязательств, тренд стоимости юнита, число сирот.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  image: { name: infracost/infracost:ci-0.10, entrypoint: [""] }
```text
<details><summary>Ответ</summary>

⚠️ `scan` — команда CLI v2, в образе `ci-0.10` её нет. Либо `breakdown/diff/comment`,
либо образ/установка v2.

</details>

```text:no-line-numbers
     script: [ "infracost scan ." ]
```text
```text:no-line-numbers
B2.  # MR из feature в release/2026-10
```text
<details><summary>Ответ</summary>

⚠️ Baseline — `main`, а мержим в `release/…`: в диффе окажутся чужие изменения.
Клонировать `$CI_MERGE_REQUEST_TARGET_BRANCH_NAME`.

</details>

```text:no-line-numbers
     - infracost breakdown --path=/tmp/main/${TF_ROOT} --format=json --out-file=base.json   # склонирован main
```text
```text:no-line-numbers
     - infracost diff --path=${TF_ROOT} --compare-to=base.json ...
```text
```text:no-line-numbers
B3.  deny contains msg if { input.diffTotalMonthlyCost > 200; msg := "дорого" }
```text
<details><summary>Ответ</summary>

⚠️ В JSON Infracost числа — строки: сравнение строки с числом в Rego не сработает
(правило никогда не выполнится). `to_number(input.diffTotalMonthlyCost) > 200`.

</details>

```text:no-line-numbers
B4.  # conftest-политика по diffTotalMonthlyCost, а на вход подаётся вывод
```text
<details><summary>Ответ</summary>

⚠️ У вывода `breakdown` нет `diffTotalMonthlyCost` — правило молча не срабатывает. На вход
политики нужен JSON от `infracost diff` (или сравнивать `totalMonthlyCost` с `pastTotalMonthlyCost`).

</details>

```text:no-line-numbers
     infracost breakdown --path . --format json --out-file infracost.json
```text
```text:no-line-numbers
B5.  default_tags { tags = { owner = "ivan", env = "Production" } }
```text
<details><summary>Ответ</summary>

⚠️ Owner — человек (уйдёт — ресурсы «ничьи»), env — не из справочника (`Production`
вместо `prod`). Плюс нет `service`/`cost-center`. Команда + справочник + validation.

</details>

```text:no-line-numbers
B6.  resource "aws_budgets_budget" "all" {
```text
<details><summary>Ответ</summary>

⚠️ Только факт 100% — узнаёшь, когда деньги потрачены; получатель — один человек
(отпуск, увольнение). Нужны пороги по прогнозу и факту, групповой адрес/канал команды.

</details>

```text:no-line-numbers
       ... notification { threshold = 100, notification_type = "ACTUAL",
```text
```text:no-line-numbers
                          subscriber_email_addresses = ["ivan@example.kz"] } }
```text
```text:no-line-numbers
B7.  # в основном аккаунте компании, «чтобы убрать мусор»
```text
<details><summary>Ответ</summary>

⚠️ Удалит всё поддерживаемое в регионе, включая прод. cloud-nuke — только
в sandbox-аккаунте, с `inspect-aws`/`--dry-run` и фильтрами.

</details>

```text:no-line-numbers
     cloud-nuke aws --region eu-central-1
```text
```text:no-line-numbers
B8.  # бакет с миллионами превью по 10 КБ
```text
<details><summary>Ответ</summary>

⚠️ Объекты 10 КБ в IA оплачиваются как 128 КБ (в 12,8 раза больше), плюс плата за переход
каждого объекта и минимум 30 дней. Для мелких объектов — Standard или Intelligent-Tiering
(мелкие объекты он не мониторит и не переводит), либо упаковка в архивы.

</details>

```text:no-line-numbers
     transition { days = 1  storage_class = "STANDARD_IA" }
```text
```text:no-line-numbers
B9.  resource "aws_cloudwatch_log_group" "app" { name = "/app/shop" }
```text
<details><summary>Ответ</summary>

⚠️ Нет `retention_in_days` — логи хранятся вечно и растут в счёте. Задать, например, 30.

</details>

```text:no-line-numbers
B10.  transition { days = 30 storage_class = "STANDARD_IA" }     # одной строкой
```text
<details><summary>Ответ</summary>

⚠️ Синтаксическая ошибка HCL: однострочный блок может содержать только один аргумент.
Писать блок в несколько строк.

</details>

```text:no-line-numbers
B11.  # StorageClass reclaimPolicy: Retain; фич-стенды с PVC создаются и удаляются каждую неделю
```text
<details><summary>Ответ</summary>

⚠️ При удалении PVC том переходит в `Released`, а диск в облаке остаётся и оплачивается —
каждую неделю копятся новые. Для стендов — StorageClass с `reclaimPolicy: Delete`, для Retain —
регулярная чистка `Released` PV.

</details>

```text:no-line-numbers
B12.  script:
```text
<details><summary>Ответ</summary>

⚠️ Ключ утёк в лог джобы (логи видят все с доступом к проекту). Отметить переменную
masked, ротировать ключ, отладку делать без вывода секретов.

</details>

```text:no-line-numbers
       - echo "key=$INFRACOST_API_KEY"   # отладка; переменная не masked
```text
---

### Блок C. Практика


### C1. 🔑 Первая оценка без облачного аккаунта
**1.** Установи Infracost v0.10, выполни `infracost auth login`.

<details><summary>Ответ</summary>

Оценены `aws_instance` (инстанс + gp3 30 ГБ), `aws_nat_gateway` (часы), `aws_db_instance`
(инстанс + хранилище), `aws_eip` (публичный IPv4, если прайс это учитывает); «depends on usage» —
данные NAT, лог-группа (приём/хранение), S3 (хранение/запросы). Без usage-файла месяц ≈ сумма
почасовых компонент — ориентир, а не счёт.

</details>

**2.** Для `main.tf` из шапки: `infracost breakdown --path .` и `--show-skipped`.

<details><summary>Ответ</summary>

```text
m6i.large → m6i.xlarge: (0,192 − 0,096) × 730 = +$70,08
второй NAT:              0,045 × 730           = +$32,85
второй EIP (IPv4):       0,005 × 730           = +$3,65
Ожидаемый дифф ≈ +$106,6/мес (плюс usage-часть NAT, если задан usage-файл)
```text
Расхождения — актуальные цены в Pricing API отличаются от округлённых в задаче; EIP может
не учитываться отдельно, если ресурс не поддержан в этой версии.

</details>

**3.** Какие ресурсы оценены, какие «depends on usage», какие бесплатны? Сколько стоит месяц?

<details><summary>Ответ</summary>

500 × $0,045 = $22,50/мес за обработку данных NAT (итого NAT ≈ $32,85 + $22,50 = $55,35).
Лог-группа: приём 100 ГБ (~$0,50/ГБ → ~$50) + хранение 200 ГБ (~$0,03/ГБ → ~$6) — она может
оказаться дороже NAT: usage-ресурсы часто и есть «невидимые» статьи счёта.

</details>

### C2. 🔑 Дифф руками и Infracost'ом
**1.** Сохрани baseline в JSON. Поменяй `m6i.large` → `m6i.xlarge` и добавь второй `aws_eip`
   + `aws_nat_gateway` (вторая AZ).

<details><summary>Ответ</summary>

Оценены `aws_instance` (инстанс + gp3 30 ГБ), `aws_nat_gateway` (часы), `aws_db_instance`
(инстанс + хранилище), `aws_eip` (публичный IPv4, если прайс это учитывает); «depends on usage» —
данные NAT, лог-группа (приём/хранение), S3 (хранение/запросы). Без usage-файла месяц ≈ сумма
почасовых компонент — ориентир, а не счёт.

</details>

**2.** Посчитай ожидаемый дифф руками: m6i.large — $0,096/ч, m6i.xlarge — $0,192/ч,
   NAT — $0,045/ч, публичный IPv4 — $0,005/ч, 730 ч.

<details><summary>Ответ</summary>

```text
m6i.large → m6i.xlarge: (0,192 − 0,096) × 730 = +$70,08
второй NAT:              0,045 × 730           = +$32,85
второй EIP (IPv4):       0,005 × 730           = +$3,65
Ожидаемый дифф ≈ +$106,6/мес (плюс usage-часть NAT, если задан usage-файл)
```text
Расхождения — актуальные цены в Pricing API отличаются от округлённых в задаче; EIP может
не учитываться отдельно, если ресурс не поддержан в этой версии.

</details>

**3.** Сравни с `infracost diff`. Объясни расхождения, если есть.

<details><summary>Ответ</summary>

500 × $0,045 = $22,50/мес за обработку данных NAT (итого NAT ≈ $32,85 + $22,50 = $55,35).
Лог-группа: приём 100 ГБ (~$0,50/ГБ → ~$50) + хранение 200 ГБ (~$0,03/ГБ → ~$6) — она может
оказаться дороже NAT: usage-ресурсы часто и есть «невидимые» статьи счёта.

</details>

### C3. 🔑 Usage-файл
Добавь usage: NAT обрабатывает 500 ГБ/мес, лог-группа принимает 100 ГБ/мес и хранит 200 ГБ.
Посчитай руками стоимость обработки NAT ($0,045/ГБ) и сверь с выводом. Как меняется картина
«самых дорогих ресурсов»?

### C4. 🔑 Комментарий в GitLab MR
**1.** Создай проект на gitlab.com, положи `main.tf` в `infra/aws/dev/`.

<details><summary>Ответ</summary>

Оценены `aws_instance` (инстанс + gp3 30 ГБ), `aws_nat_gateway` (часы), `aws_db_instance`
(инстанс + хранилище), `aws_eip` (публичный IPv4, если прайс это учитывает); «depends on usage» —
данные NAT, лог-группа (приём/хранение), S3 (хранение/запросы). Без usage-файла месяц ≈ сумма
почасовых компонент — ориентир, а не счёт.

</details>

**2.** Добавь masked-переменные `INFRACOST_API_KEY` и `GITLAB_TOKEN` (scope `api`).

<details><summary>Ответ</summary>

```text
m6i.large → m6i.xlarge: (0,192 − 0,096) × 730 = +$70,08
второй NAT:              0,045 × 730           = +$32,85
второй EIP (IPv4):       0,005 × 730           = +$3,65
Ожидаемый дифф ≈ +$106,6/мес (плюс usage-часть NAT, если задан usage-файл)
```text
Расхождения — актуальные цены в Pricing API отличаются от округлённых в задаче; EIP может
не учитываться отдельно, если ресурс не поддержан в этой версии.

</details>

**3.** Добавь джобу `infracost` из конспекта. Открой MR с `m6i.xlarge` — появился комментарий?

<details><summary>Ответ</summary>

500 × $0,045 = $22,50/мес за обработку данных NAT (итого NAT ≈ $32,85 + $22,50 = $55,35).
Лог-группа: приём 100 ГБ (~$0,50/ГБ → ~$50) + хранение 200 ГБ (~$0,03/ГБ → ~$6) — она может
оказаться дороже NAT: usage-ресурсы часто и есть «невидимые» статьи счёта.

</details>

**4.** Запушь ещё одну правку — комментарий обновился, а не продублировался?

<details><summary>Ответ</summary>

Если комментарий не появился: джоба не запустилась (нужен `merge_request_event`), токен
без `api`/прав на проект (403), `--repo`/`--merge-request` неверны. При `--behavior=update`
второй пуш обновляет тот же комментарий.

</details>

### C5. Политики conftest
**1.** Напиши `policy/cost/cost.rego` (лимит роста $200) и прогони на `infracost.json` из C4/C2
   (формат `diff`).

<details><summary>Ответ</summary>

Оценены `aws_instance` (инстанс + gp3 30 ГБ), `aws_nat_gateway` (часы), `aws_db_instance`
(инстанс + хранилище), `aws_eip` (публичный IPv4, если прайс это учитывает); «depends on usage» —
данные NAT, лог-группа (приём/хранение), S3 (хранение/запросы). Без usage-файла месяц ≈ сумма
почасовых компонент — ориентир, а не счёт.

</details>

**2.** Напиши `policy/plan/plan.rego` (теги, gp2, типы в dev) и прогони на этом plan JSON:

<details><summary>Ответ</summary>

```text
m6i.large → m6i.xlarge: (0,192 − 0,096) × 730 = +$70,08
второй NAT:              0,045 × 730           = +$32,85
второй EIP (IPv4):       0,005 × 730           = +$3,65
Ожидаемый дифф ≈ +$106,6/мес (плюс usage-часть NAT, если задан usage-файл)
```text
Расхождения — актуальные цены в Pricing API отличаются от округлённых в задаче; EIP может
не учитываться отдельно, если ресурс не поддержан в этой версии.

</details>

```text:no-line-numbers
{
```text
```text:no-line-numbers
  "variables": { "env": { "value": "dev" } },
```text
```text:no-line-numbers
  "resource_changes": [
```text
```text:no-line-numbers
    { "address": "aws_instance.app", "type": "aws_instance",
```text
```text:no-line-numbers
      "change": { "actions": ["create"],
```text
```text:no-line-numbers
        "after": { "instance_type": "m6i.2xlarge",
```text
```text:no-line-numbers
                   "tags_all": { "owner": "team-shop", "env": "dev", "service": "shop" } } } },
```text
```text:no-line-numbers
    { "address": "aws_ebs_volume.data", "type": "aws_ebs_volume",
```text
```text:no-line-numbers
      "change": { "actions": ["create"],
```text
```text:no-line-numbers
        "after": { "type": "gp2", "size": 100,
```text
```text:no-line-numbers
                   "tags_all": { "owner": "team-shop", "env": "dev", "service": "shop", "cost-center": "cc-1" } } } }
```text
```text:no-line-numbers
  ]
```text
```text:no-line-numbers
}
```text
Сколько `deny` ты ожидаешь и каких?

### C6. Теги кодом
Добавь в `main.tf` `default_tags` с переменными и validation из конспекта, `.tflint.hcl`
с `aws_resource_missing_tags`. Запусти `tflint --init && tflint`. Убери `cost-center`
из `default_tags` — что покажет tflint?

### C7. Скрипт поиска сирот
Напиши `orphans.sh`: непривязанные диски, свободные EIP, свои снапшоты старше 90 дней,
лог-группы без retention — и оценка стоимости в месяц (диск $0,08/ГБ, снапшот $0,05/ГБ,
EIP $3,65). `set -euo pipefail`, чистый shellcheck. Нет аккаунта — проверь логику на
выводе `aws … --generate-cli-skeleton output` или своём JSON.

### C8. Lifecycle: сколько сэкономит (расчёт)
В бакет логов приходит 1 ТБ (1000 ГБ) в месяц, логи хранятся 365 дней. Сейчас всё в Standard
($0,023/ГБ·мес). Политика: 30 дней Standard → до 90 дней STANDARD_IA ($0,0125) → до 365 дней
GLACIER_IR ($0,004) → удаление. Посчитай стоимость хранения в установившемся режиме до и после.

### C9. 🔑 Cost review своего стенда
Заполни шаблон cost review (конспект, раздел 9) по своему стенду/pet-проекту: итог
(OpenCost или счёт облака), топ-5 статей, эффективность, 3 action items с владельцем,
сроком и ожидаемой экономией.

---

### Блок D. Инциденты


**D1.** Комментарий Infracost в MR показал «+$0/мес», а после мержа счёт вырос на $800/мес.

<details><summary>Ответ</summary>

Рост не виден Infracost'у: usage-ресурсы без usage-файла (трафик NAT, логи), ресурсы
вне Terraform (балансировщики от k8s Service, ноды Karpenter), unsupported ресурсы
(`--show-skipped`), скидки/цены региона. Добавить usage-файл по реальным данным, проверять
skipped, мониторить фактические расходы (бюджеты, аномалии, OpenCost).

</details>

**D2.** Джоба Infracost падает на шаге комментария с HTTP 403.

<details><summary>Ответ</summary>

У `GITLAB_TOKEN` нет scope `api` или прав писать в проект (роль ниже Developer/Maintainer),
токен истёк, переменная protected, а MR из незащищённой ветки (переменная не пришла). Проверить
токен и настройки переменной.

</details>

**D3.** В середине месяца джоба Infracost начала падать с ошибкой лимита/ключа: монорепо,

<details><summary>Ответ</summary>

Бесплатный лимит запусков в месяц (на сентябрь 2026 — 1000) израсходован: 40 проектов ×
десятки пушей. Запускать только на изменения (`rules: changes` по путям проектов), считать только
затронутые проекты, не гонять на каждый пуш в ветку без MR; при необходимости — платный план.

</details>

**40.** проектов, пайплайн на каждый пуш.
**D4.** Бюджет dev превышен две недели назад, уведомление было, реакции — ноль.

<details><summary>Ответ</summary>

Бюджет без процесса: неясно, кто владелец и что делать. Получатель — канал команды,
а не общий ящик; в runbook — действия при превышении; разбор на cost review; для песочниц —
Budget Actions/триггер, останавливающий ресурсы.

</details>

**D5.** Удалили «сироту» — непривязанный диск на 2 ТБ. Через неделю выяснилось, что это была
DR-копия базы.

<details><summary>Ответ</summary>

Удаление без поиска владельца и страховки. Порядок: теги/CloudTrail → владелец →
предупреждение с дедлайном → снапшот перед удалением → удаление. DR-ресурсы — с явным тегом
(`purpose=dr`) и исключением из чистки.

</details>

**D6.** Ресурсы помечены тегом `env` полгода, а в Cost Explorer разбивка по `env` есть только
за последние две недели.

<details><summary>Ответ</summary>

Ключ `env` активировали как cost allocation tag недавно — разбивка работает с момента
активации (исторически по умолчанию не пересчитывается). Активировать ключи сразу при введении
стратегии тегов.

</details>

**D7.** После lifecycle-политики «всё в Glacier через 30 дней» счёт за S3 вырос.

<details><summary>Ответ</summary>

Миллионы мелких объектов: плата за переход каждого объекта; минимальный оплачиваемый
размер и срок хранения; частые чтения — платное извлечение из Glacier. Считать до внедрения:
число объектов × цена перехода, профиль чтения; мелкое — не переводить или паковать.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как оценить стоимость инфраструктуры до `terraform apply`?

<details><summary>Ответ</summary>

Infracost по коду в MR (`breakdown`/`diff` или `scan`), usage-файл для usage-ресурсов,
   для неподдерживаемых облаков — свой расчёт по прайсу.

</details>

**2.** Как встроить контроль стоимости в CI/CD?

<details><summary>Ответ</summary>

Джоба в MR: baseline целевой ветки → `infracost diff` → комментарий → conftest-политики
   (лимит роста $, типы, классы дисков, теги) → апрув при превышении. Плюс tflint.

</details>

**3.** Как заставить всех ставить теги?

<details><summary>Ответ</summary>

`default_tags` и validation в Terraform, модули с тегами, tflint и политики на plan в CI,
   SCP/Tag Policies в облаке, admission-политики в k8s, отчёт «без owner» и showback.

</details>

**4.** Как настроить бюджеты и алерты по расходам?

<details><summary>Ответ</summary>

Бюджеты кодом (`aws_budgets_budget`) на аккаунт, окружения и команды с порогами по факту
   и прогнозу; детектор аномалий; получатель — команда; runbook реакции.

</details>

**5.** Как найти неиспользуемые ресурсы в облаке?

<details><summary>Ответ</summary>

Скрипты/отчёты: непривязанные диски, старые снапшоты, свободные IP, пустые LB, лог-группы
   без retention, PV `Released`, старые образы; инструменты провайдера (Trusted Advisor и т.п.).

</details>

**6.** Что такое lifecycle-политики и когда они экономят, а когда нет?

<details><summary>Ответ</summary>

Автоматический перевод в дешёвые классы и удаление. Экономят на крупных редко читаемых
   объектах; не экономят на миллионах мелких и часто читаемых (переходы, минимумы, извлечение).

</details>

**7.** Как ограничить расходы на логи?

<details><summary>Ответ</summary>

Уровни логов и sampling, retention по классам логов (Loki, ILM, CloudWatch), дешёвое хранилище
   (Loki на S3), не логировать лишнее, следить за объёмом приёма.

</details>

**8.** Что такое cost review и как его проводить?

<details><summary>Ответ</summary>

Ежемесячный разбор: тренд и юнит-метрики, топ строк, аномалии, action items с владельцами
   и экономией, обязательства. Результат — записанные решения.

</details>

**9.** Чем опасна автоматическая чистка ресурсов?

<details><summary>Ответ</summary>

Можно удалить нужное (DR, бэкапы, чужое), особенно в общем аккаунте. Только с владельцем,
   предупреждением, снапшотом; инструменты массового удаления — только в песочницах.

</details>

**10.** Какие ограничения у Infracost?

<details><summary>Ответ</summary>

Только AWS/Azure/GCP; usage-ресурсы требуют usage-файла; публичные цены без скидок; не видит
    ресурсы вне кода; бесплатный лимит запусков; две версии CLI с разными командами.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Различаю CLI v0.10 и v2 и знаю их команды
- [ ] Получил ключ и оценил Terraform-код без облачного аккаунта
- [ ] Считаю дифф руками и сверяю с `infracost diff`, пользуюсь usage-файлом
- [ ] Infracost комментирует MR в GitLab и обновляет комментарий
- [ ] Написал conftest-политики на деньги (JSON Infracost) и на конфигурацию (plan JSON)
- [ ] Теги навязаны через `default_tags`, validation и tflint
- [ ] Завожу бюджеты с порогами факта и прогноза; знаю, что бюджет сам не останавливает ресурсы
- [ ] Есть скрипт поиска сирот с оценкой в $, знаю безопасный порядок удаления
- [ ] Считаю экономию от lifecycle и знаю подводные камни классов хранения
- [ ] Провёл cost review с action items
