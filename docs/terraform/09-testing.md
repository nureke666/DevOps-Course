---
title: "09. Тестирование инфраструктурного кода"
description: "Пирамида тестирования IaC: tflint, checkov/trivy, conftest на plan JSON, terraform test с моками, Terratest, ночной дрейф"
---

# 09. Тестирование инфраструктурного кода

> Роадмап → Terraform. В теме [«Рабочий процесс и CI/CD»](/terraform/06-workflow-cicd), §6 тестирование — обзорной
> таблицей; здесь — как его строить: от `fmt` за секунду до `apply` в песочнице и поиска дрейфа.
>
> **После темы ты умеешь:** разложить проверки IaC по пирамиде, настроить tflint, checkov
> и `trivy config`, написать политику conftest на plan JSON, покрыть модуль `terraform test`
> с моками **без облачных кредов**, понимать место Terratest и собрать всё в пайплайн.
>
> ⚠️ Версии — **проверь, сентябрь 2026**: Terraform 1.16.4, OpenTofu 1.12.6, tflint 0.64.0
> + `tflint-ruleset-aws` 0.49.0, checkov 3.3.19, trivy 0.74.0, conftest 0.70.1 (OPA 1.20),
> Terratest v2.0.0; `hashicorp/aws` 6.66, `yandex-cloud/yandex` 0.230 — на них прогнаны §3 и §4.

---

## 🗺️ Пирамида тестирования IaC

```text:no-line-numbers
                         ▲ дорого · минуты–часы · реальное облако · деньги
   7. Дрейф             │  plan -detailed-exitcode по расписанию на живом окружении
   6. Интеграция        │  Terratest / terraform test с настоящим провайдером в sandbox
   5. terraform test    │  ⭐ run-блоки + mock_provider: логика модуля без кредов
   4. Политики          │  conftest/OPA на plan JSON: теги, «нет SSH из мира»
   3. Безопасность      │  checkov / trivy config: сотни готовых правил
   2. Линтер            │  tflint + ruleset облака: опечатки в типах, неиспользуемое
   1. fmt / validate    │  синтаксис, ссылки, типы
                         ▼ дёшево · секунды · без облака · на каждый коммит
```

| Уровень | Что ловит | Время | Креды | Когда |
|---------|-----------|-------|-------|-------|
| 1. `fmt`, `validate` | Синтаксис, битые ссылки, типы | секунды | нет | pre-commit, MR |
| 2. `tflint` | `t3.mirco`, неиспользуемые переменные, нет тегов | секунды | нет | pre-commit, MR |
| 3. checkov / trivy | Публичный бакет, SG в мир, нет шифрования | секунды | нет | MR |
| 4. conftest на плане | Правила компании на **итоговых** значениях | секунды | read-only для plan | MR |
| 5. `terraform test` + моки | `for_each`, `cidrsubnet`, validation, outputs | секунды | нет ⭐ | MR в модуль |
| 6. Интеграция | Создаётся ли и работает (IAM, сеть, квоты) | 5–30 мин | sandbox | релиз модуля, ночью |
| 7. Дрейф | Ручные правки, изменения платформы | минуты | read-only | по расписанию |

⭐ Правило пирамиды: **чем ниже уровень, тем больше проверок и тем раньше они падают**.

---

## 1. Уровни 1–2: `fmt`, `validate`, tflint

```bash
terraform fmt -check -recursive -diff                                  # только проверить (CI)
terraform init -backend=false -input=false && terraform validate       # ⭐ без доступа к стейту
```
**tflint** видит то, чего не видит `validate`: несуществующий тип инстанса, устаревший
синтаксис, неиспользуемые переменные, отсутствие тегов.
```hcl
# .tflint.hcl  (+ config { call_module_type = "local" } — проверять и локальные модули)
plugin "terraform" {                         # встроенные правила языка
  enabled = true
  preset  = "recommended"
}
plugin "aws" {
  enabled = true
  version = "0.49.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}
rule "aws_resource_missing_tags" {           # учитывает default_tags провайдера
  enabled = true
  tags    = ["owner", "env"]
}
```
```bash
tflint --init && tflint --recursive --format compact    # CI: --format junit > tflint.xml
```
Для AWS есть ⭐ `tflint-ruleset-aws` (сотни правил); для Yandex и OpenStack-облаков официальных
наборов нет — только правила языка и свои политики (§3). До коммита уровни 1–3 запускает
pre-commit (`terraform_fmt`, `_validate`, `_tflint`, `_trivy` из `antonbabenko/pre-commit-terraform`).

---

## 2. Уровень 3: сканеры безопасности — checkov и `trivy config`

**tfsec → trivy.** tfsec «влился» в Trivy: репозиторий жив, но развитие и новые правила — в
`trivy config`; для новых пайплайнов бери trivy.
```bash
trivy config --severity HIGH,CRITICAL --exit-code 1 .    # ⭐ уронить джобу на серьёзном
trivy config --tf-vars environments/prod/terraform.tfvars .
checkov -d . --framework terraform --compact
checkov -f plan.json --framework terraform_plan          # ⭐ по плану: значения вычислены
checkov -d . --soft-fail -o junitxml > checkov.xml       # этап внедрения: отчёт без падения
```

SG с SSH из мира (§7.1 темы 02, если заменить `/32` на `0.0.0.0/0`):
```text:no-line-numbers
checkov:  CKV_AWS_24   "Ensure no security groups allow ingress from 0.0.0.0:0 to port 22"
trivy:    AVD-AWS-0107 (HIGH) "Security groups should not allow ingress from a public address"
```
Подавление — **только в коде и с причиной**, чтобы оно прошло ревью:
```hcl
resource "aws_vpc_security_group_ingress_rule" "http" {
  #checkov:skip=CKV_AWS_260:публичный веб за ALB, 80 редиректит на 443
  #trivy:ignore:AVD-AWS-0107
  cidr_ipv4 = "0.0.0.0/0"
  # ...
}
```

| | checkov | trivy config |
|---|---------|--------------|
| Что сканирует | Terraform, plan JSON, k8s, Helm, Dockerfile, CI-конфиги | То же + уязвимости образов в одном инструменте |
| Свои правила | Python или YAML | Rego |
| Готовые правила | AWS, Azure, GCP; для Yandex/OpenStack — практически нет | так же |

⭐ Вывод: для AWS сначала бери готовые правила сканера; для Yandex Cloud и казахстанских
облаков критичные запреты пишутся **своими политиками** на plan JSON.

---

## 3. Уровень 4: политики — conftest/OPA на plan JSON

На **плане**, а не на `.tf`: переменные подставлены, модули развёрнуты, `for_each` раскрыт,
`default_tags` смёржены в `tags_all` — проверяется то, что **уйдёт в API**, одним языком для любого провайдера.
```bash
terraform plan -out=tfplan && terraform show -json tfplan > plan.json
conftest test plan.json -p policy/          # deny → exit 1, warn → только вывод
conftest verify -p policy/                  # тесты самих политик (*_test.rego)
```

Обязательные теги/метки и запрет SSH из интернета для AWS **и** Yandex Cloud (проверено
conftest 0.70.1 на реальном плане AWS и на плане с `yandex_vpc_security_group`):
```text:no-line-numbers
# policy/terraform.rego
package main

import rego.v1

required_tags := {"owner", "env"}
world := {"0.0.0.0/0", "::/0"}

changed contains rc if {
	some rc in input.resource_changes
	rc.mode == "managed"
	some action in rc.change.actions
	action in {"create", "update"}
}
tag_attr(rc) := "tags_all" if startswith(rc.type, "aws_")   # tags_all включает default_tags
tag_attr(rc) := "labels" if startswith(rc.type, "yandex_")

deny contains msg if {                              # 1. теги / метки
	some rc in changed
	attr := tag_attr(rc)
	attr in object.keys(rc.change.after)          # ресурс вообще поддерживает теги
	have := {k | some k, _ in object.get(rc.change.after, attr, {})}   # null → пусто
	missing := required_tags - have
	count(missing) > 0
	msg := sprintf("%s: нет обязательных %s %v", [rc.address, attr, missing])
}
covers_22(from, to) if { from <= 22; to >= 22 }

deny contains msg if {                              # 2a. AWS: правило SG
	some rc in changed
	rc.type == "aws_vpc_security_group_ingress_rule"
	a := rc.change.after
	object.get(a, "cidr_ipv4", "") in world
	any_ssh_aws(a)
	msg := sprintf("%s: SSH открыт в интернет (%s)", [rc.address, a.cidr_ipv4])
}
any_ssh_aws(a) if a.ip_protocol == "-1"            # «все протоколы» — тоже 22
any_ssh_aws(a) if covers_22(a.from_port, a.to_port)
# (inline ingress у aws_security_group — такое же правило по ingress[].cidr_blocks)

deny contains msg if {                              # 2b. Yandex Cloud
	some rc in changed
	rc.type == "yandex_vpc_security_group"
	some ing in object.get(rc.change.after, "ingress", [])
	some cidr in object.get(ing, "v4_cidr_blocks", [])
	cidr in world
	any_ssh_yc(ing)
	msg := sprintf("%s: ingress открывает 22 для %s", [rc.address, cidr])
}
any_ssh_yc(ing) if ing.port == 22
any_ssh_yc(ing) if covers_22(ing.from_port, ing.to_port)
```
```text:no-line-numbers
$ conftest test plan.json -p policy
FAIL - plan.json - main - aws_vpc_security_group_ingress_rule.bad: SSH открыт в интернет (0.0.0.0/0)
$ conftest test yc-plan.json -p policy
FAIL - yc-plan.json - main - yandex_vpc_network.this: нет обязательных labels {"env", "owner"}
FAIL - yc-plan.json - main - yandex_vpc_security_group.web: ingress открывает 22 для 0.0.0.0/0
FAIL - yc-plan.json - main - yandex_vpc_security_group.web: нет обязательных labels {"owner"}
```
Политики — тоже код: тесты в `policy/*_test.rego` (правило `test_...`, вход подменяется
`count(deny) > 0 with input as {...}`), запуск — `conftest verify` (задача C4 в задачах темы).

| Подводный камень | Что делать |
|------------------|-----------|
| `(known after apply)` | Значения нет в `after`, оно в `after_unknown` — «пусто» ≠ нарушение |
| Удаление | `actions = ["delete"]`, `after = null` — фильтруй по действиям (`changed` выше) |
| Деньги | Политики на JSON Infracost — см. раздел FinOps этого курса, §4 |

---

## 4. Уровень 5: `terraform test` ⭐

### 4.1 Как устроено

```text:no-line-numbers
modules/network/aws/                    terraform test
├── main.tf variables.tf outputs.tf       для каждого *.tftest.hcl (корень модуля и tests/):
└── tests/                                  run "a" ─► plan/apply модуля со своими variables
    └── network.tftest.hcl                  run "b" ─► видит стейт "a" и run.a.<output>
                                            teardown ─► destroy в обратном порядке run
```

| Блок файла / атрибут `run` | Смысл |
|----------------------------|-------|
| `variables { }` | Входы для всех `run` (у `run` — свои, приоритетнее) |
| `provider "aws" { }` | Настроенный провайдер для тестов (sandbox-регион/аккаунт) |
| `mock_provider "aws" { }` | ⭐ Провайдер-подделка: API не вызывается, креды не нужны (1.7+) |
| `override_resource/_data/_module` | Конкретные значения ресурсу, data, модулю |
| `command = plan \| apply` | ⚠️ По умолчанию **apply**: с настоящим провайдером — реальные ресурсы |
| `assert { condition, error_message }` | Проверки, сколько угодно |
| `expect_failures = [var.x]` | Кейс проходит, **если** валидация/условие упали |
| `module { source = "./tests/setup" }` | Выполнить другой модуль (подготовка, `examples/`) |
| `plan_options`, `providers`, `state_key`, `parallel` | Режим плана, выбор провайдера, общий стейт, параллельность |

```bash
terraform test -filter=tests/network.tftest.hcl -verbose   # или все файлы: terraform test
terraform test -junit-xml=test-report.xml                  # отчёт для GitLab/GitHub
```

### 4.2 🧪 Пример без облака: модуль `network` (AWS)

Модуль — контракт из [«Модули»](/terraform/05-modules), §7 (`aws/`). Проверено на Terraform 1.16.4 +
aws 6.66.0 **без кредов**: нужен лишь `terraform init` (схему провайдера из registry/зеркала).
```hcl
# modules/network/aws/tests/network.tftest.hcl
mock_provider "aws" {}                          # ⭐ ни одного запроса к AWS

variables {
  name  = "lab"
  env   = "dev"
  zones = ["eu-central-1a", "eu-central-1b"]
}

run "subnets_are_carved_from_cidr" {
  command = plan
  assert {
    condition     = length(aws_subnet.this) == 2
    error_message = "Ожидали по подсети на зону"
  }
  assert {
    condition     = aws_subnet.this["eu-central-1b"].cidr_block == "10.20.1.0/24"
    error_message = "Вторая подсеть должна быть 10.20.1.0/24"
  }
}

run "ssh_from_world_is_rejected" {
  command = plan
  variables {
    ssh_allowed_cidrs = ["0.0.0.0/0"]
  }
  expect_failures = [var.ssh_allowed_cidrs]     # ⭐ валидация ОБЯЗАНА упасть
}

run "outputs_after_mocked_apply" {              # apply по умолчанию, но провайдер — мок
  override_resource {
    target = aws_vpc.this
    values = { id = "vpc-0test" }               # своё значение вместо случайной строки
  }
  assert {
    condition     = output.network_id == "vpc-0test"
    error_message = "network_id должен прийти из aws_vpc"
  }
  assert {
    condition     = length(output.subnet_ids) == 2
    error_message = "Ожидали 2 subnet_ids"
  }
}
```
```text:no-line-numbers
$ terraform init && terraform test
  run "subnets_are_carved_from_cidr"... pass
  run "ssh_from_world_is_rejected"... pass
  run "outputs_after_mocked_apply"... pass
Success! 3 passed, 0 failed.
```
Реализация `yandex/` — тот же файл с `mock_provider "yandex" {}` и зонами `ru-central1-*`
(проверено на `yandex-cloud/yandex` 0.230.0); отдельный кейс для Казахстана:
```hcl
run "kz1_single_zone" {
  command = plan
  variables { zones = ["kz1-a"] }
  assert {
    condition     = length(yandex_vpc_subnet.this) == 1
    error_message = "В kz1 одна зона — одна подсеть"
  }
}
```

### 4.3 Моки и переопределения

```hcl
mock_provider "aws" {
  mock_data "aws_availability_zones" {                       # data без API
    defaults = { names = ["eu-central-1a", "eu-central-1b"] }
  }
}
override_data {                                              # уровень файла — для всех run
  target = data.aws_ssm_parameter.ubuntu
  values = { value = "ami-0123456789abcdef0" }
}
run "app_uses_vpc_module" {
  override_module {                                          # вложенный модуль не выполняется
    target  = module.vpc
    outputs = { vpc_id = "vpc-0test", private_subnets = ["subnet-a", "subnet-b"] }
  }
}
```
- Не заданное мок генерирует: строки — случайные 8 символов, числа — `0`, bool — `false`,
  коллекции — пустые; `override_during = plan` подставляет значения уже на плане.
- ⚠️ Моки проверяют **логику кода**, а не облако: что AWS примет тип инстанса и что роль
  позволит запись в бакет, мок не скажет — это уровни 2 и 6.

### 4.4 Настоящий провайдер: `terraform test` как интеграция

Без моков и с `command = apply` тест **создаёт реальные ресурсы** и удаляет их на teardown —
простая альтернатива Terratest без Go. Только в sandbox:
```hcl
provider "aws" { region = "eu-central-1" }        # креды sandbox-роли из окружения
run "setup" {
  module { source = "./tests/setup" }             # random_pet → уникальный суффикс
}
run "creates_network" {
  variables { name = "it-${run.setup.suffix}" }
  assert {
    condition     = startswith(output.network_id, "vpc-")
    error_message = "Ожидали настоящий vpc-id"
  }
}
```
⚠️ Убитый посреди теста процесс teardown не выполнит — ресурсы останутся (уборка — §5).

**OpenTofu:** `tofu test` совместим: `run`, `assert`, `expect_failures`, `mock_provider`, `override_*`.
Отличия (проверь, сентябрь 2026): понимает ещё `*.tofutest.hcl` (при одинаковом имени он
приоритетнее `.tftest.hcl`), машинный вывод — `-json`/`-json-into` вместо `-junit-xml`.

---

## 5. Уровень 6: интеграция — Terratest и sandbox

**Terratest** — Go-библиотека: `init/apply` → проверки (outputs, HTTP, SSH, API облака) →
`destroy`. Отдельного блока Go в волте нет и не планируется: здесь достаточно уметь читать такой тест, писать с нуля его нужно редко — для sandbox-проверок хватает `terraform test` с настоящим провайдером (§4). С **v2.0.0** (сентябрь 2026) пути пакетов `.../modules/<имя>/v2`, API — с контекстом (`InitAndApplyContext`,
`OutputContext`, `DestroyContext`); в старом коде — v1: `terraform.InitAndApply(t, opts)`.
```go
// test/network_aws_test.go
package test

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/gruntwork-io/terratest/modules/terraform/v2"
	"github.com/stretchr/testify/assert"
)
func TestNetworkAWS(t *testing.T) {
	ctx := context.Background()
	opts := terraform.WithDefaultRetryableErrors(t, &terraform.Options{
		TerraformDir: "../examples/aws",
		Vars: map[string]interface{}{
			"name":  fmt.Sprintf("tt-%d", time.Now().Unix()), // уникальное имя
			"env":   "dev",
			"zones": []string{"eu-central-1a", "eu-central-1b"},
		},
		EnvVars: map[string]string{"AWS_REGION": "eu-central-1"},
	})
	defer terraform.DestroyContext(t, ctx, opts) // ⭐ убрать даже при падении
	terraform.InitAndApplyContext(t, ctx, opts)
	assert.Regexp(t, `^vpc-`, terraform.OutputContext(t, ctx, opts, "network_id"))
	assert.Len(t, terraform.OutputMapContext(t, ctx, opts, "subnet_ids"), 2)
}
```
```bash
cd test && go mod init example.com/network-test && go get github.com/gruntwork-io/terratest/modules/terraform/v2@v2.0.0
go test -v -timeout 30m        # ⚠️ дефолтный таймаут go test — 10 минут
```

| Terratest | `terraform test` с настоящим провайдером |
|-----------|------------------------------------------|
| Любые проверки на Go: HTTP, SSH, SDK облака, k8s | Только HCL-условия над ресурсами и outputs |
| Идемпотентность (`InitAndApplyAndIdempotentContext`), ретраи облачных ошибок | Вручную: повторный план вторым `run` |
| Нужен Go в команде | Ничего, кроме Terraform |

**Sandbox**: AWS-аккаунт в OU Sandbox или отдельное облако/каталог Yandex с бюджетом и алертом;
уникальные имена и метка `managed-by = terraform-test`;
ночная уборка «сирот» (aws-nuke/cloud-nuke; для Yandex — скрипт по метке через `yc ... list
--format json`); в CI — роль только на sandbox, вход через OIDC/WIF.

---

## 6. Уровень 7: дрейф

```yaml
drift:                                               # ночное расписание в GitLab
  rules: [{ if: $CI_PIPELINE_SOURCE == "schedule" }]
  script:
    - terraform init -input=false
    - set +e; terraform plan -detailed-exitcode -lock=false -input=false -out=d.plan; rc=$?; set -e
    - if [ "$rc" -eq 2 ]; then terraform show -no-color d.plan > drift.txt; exit 1; fi   # 2 = есть изменения
    - exit $rc                                                                          # 0 — чисто, 1 — ошибка
  artifacts: { when: on_failure, paths: [drift.txt], expire_in: 3 days }
```
`-lock=false` — ночной read-only plan не мешает apply; `plan -refresh-only` — только расхождение
реальности со стейтом. Реакция — [«Стейт и backend»](/terraform/03-state-backend), §6.

---

## 7. Всё вместе в CI

```text:no-line-numbers
 MR:     fmt/validate ─► tflint ─► trivy/checkov ─► plan ─► conftest ─► infracost
                              └──► terraform test (модули, моки) ──┘
 main:   ... ─► apply (manual)          ночью: дрейф · интеграция модулей · уборка sandbox
```
```yaml
# .gitlab-ci.yml (фрагмент; образы и теги — проверь, сентябрь 2026)
stages: [lint, test, plan, policy, apply]
variables: { TF_ROOT: environments/dev-aws, TF_IN_AUTOMATION: "true" }
.tf: { image: { name: hashicorp/terraform:1.16.4, entrypoint: [""] } }

# fmt/validate — как в теме 06, §2
tflint:
  stage: lint
  image: { name: ghcr.io/terraform-linters/tflint:v0.64.0, entrypoint: [""] }
  script: [tflint --init, tflint --recursive --format junit > tflint.xml]
  artifacts: { when: always, reports: { junit: tflint.xml } }
trivy: { stage: lint, image: { name: aquasec/trivy:0.74.0, entrypoint: [""] }, script: [trivy config --severity HIGH,CRITICAL --exit-code 1 .] }
module-tests:
  extends: .tf
  stage: test
  parallel: { matrix: [{ MODULE: [modules/network/aws, modules/network/yandex] }] }
  script: [cd "$MODULE", terraform init -input=false, terraform test -junit-xml=report.xml]   # креды не нужны ⭐
  artifacts: { when: always, reports: { junit: "$MODULE/report.xml" } }
plan:
  extends: .tf
  stage: plan
  id_tokens: { AWS_OIDC: { aud: sts.amazonaws.com } }     # read-only роль через OIDC
  script:
    - echo "$AWS_OIDC" > /tmp/web-identity
    - export AWS_WEB_IDENTITY_TOKEN_FILE=/tmp/web-identity AWS_ROLE_ARN="$PLAN_ROLE_ARN"
    - cd "$TF_ROOT" && terraform init -input=false && terraform plan -input=false -out=tfplan
    - terraform show -json tfplan > plan.json
  artifacts: { paths: ["$TF_ROOT/tfplan", "$TF_ROOT/plan.json"], expire_in: 3 days }
conftest:
  stage: policy
  needs: [plan]
  image: { name: openpolicyagent/conftest:v0.70.1, entrypoint: [""] }
  script: [conftest verify -p policy/, conftest test "$TF_ROOT/plan.json" -p policy/]
```
Джоба `infracost` и версии CLI — см. раздел FinOps этого курса, §3; `apply` —
[«Рабочий процесс и CI/CD»](/terraform/06-workflow-cicd), §2; OIDC в AWS — см. раздел Security этого курса,
в Yandex — workload identity federation.

**GitHub Actions** — те же шаги, что и в GitLab CI (см. раздел CI/CD этого курса):
`hashicorp/setup-terraform@v3` (`terraform_version: 1.16.4`) → `fmt -check` → `terraform test`
по матрице модулей; для AWS — `aws-actions/configure-aws-credentials` с OIDC (`id-token: write`).

---

## 🧪 Мини-лаба: пирамида на ноутбуке без облака (~40 минут)

```bash
mkdir -p ~/labs/tf-testing/modules/network/aws/tests && cd ~/labs/tf-testing/modules/network/aws
# 1. модуль (контракт из темы 05, §7) + тест из §4.2
terraform init && terraform test                         # 3 passed
# 2. сломай логику: cidrsubnet(var.cidr, 8, each.value + 1) → тест обязан упасть
# 3. уровни 1–3
terraform fmt -check && tflint --init && tflint && trivy config .
# 4. план без облака: корневая конфигурация, провайдер aws с access_key/secret_key = "mock"
#    и skip_credentials_validation, skip_requesting_account_id, skip_metadata_api_check = true
terraform plan -out=tfplan && terraform show -json tfplan > plan.json
conftest test plan.json -p ~/labs/tf-testing/policy       # политика из §3
```
Трюк (только для лабы!) работает без `data`-источников, которым нужен API: план ресурсов на
создание в AWS не ходит. Провайдер Yandex получает IAM-токен уже при настройке — его план
строится с read-only сервисным аккаунтом.

Критерии: тест зелёный, поломка логики ловится, SG с `0.0.0.0/0` на 22 ловят trivy и conftest.

---

## 8. Грабли и антипаттерны

| Антипаттерн | Последствие | Как правильно |
|-------------|-------------|---------------|
| «Тест» = `apply` на stage и посмотреть | Ошибки через 20 минут и за деньги | Пирамида: всё, что можно, — линтером и моками |
| `run` без моков и без `command = plan` | Реальные ресурсы там, куда смотрят креды | Моки или явный sandbox-провайдер в файле теста |
| Тест повторяет код (`name == "${var.name}-${var.env}"`) | Ломается при рефакторинге, ничего не ловит | Проверять поведение: CIDR, число подсетей, отказы, контракт outputs |
| Нет тестов на `validation` | Запрет ослабили — никто не заметил | `expect_failures` на каждый запрет |
| `--soft-fail` навсегда, `skip` без причины | Сканер выключен по факту | Soft-fail на внедрение, затем `--exit-code 1`; skip — в коде с причиной |
| Политики на `.tf`, а не на плане; политики без тестов | Не видят tfvars и `default_tags`; молча перестают срабатывать | Plan JSON + `conftest verify` в CI |
| Terratest без `defer Destroy` и `-timeout` | «Сироты»; тест убит через 10 минут | `defer DestroyContext`, `-timeout 30m` |
| Для Yandex-кода только AWS-сканеры | Иллюзия безопасности: правил под `yandex_*` нет | Свои политики на plan JSON |

---

## 💼 Как это в DevOps

- «Как вы тестируете Terraform?» — хороший ответ звучит как пирамида: fmt/validate/tflint
  и сканер на каждый MR, conftest на плане, `terraform test` с моками для модулей,
  интеграция в песочнице перед релизом модуля, ночной дрейф.
- `terraform test` с моками — самые дешёвые настоящие тесты модулей: секунды, без кредов.
- Политики на plan JSON — общий язык для всех облаков: одно правило «нет SSH из мира»
  проверяет AWS, Yandex Cloud и OpenStack-облака Казахстана.
- Интеграция — в sandbox с бюджетом и автоуборкой; результат — JUnit-отчёт в MR.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Линтер с правилами AWS | `.tflint.hcl` с `plugin "aws"`, затем `tflint --init && tflint --recursive` |
| Сканер (код / план) | `trivy config --severity HIGH,CRITICAL --exit-code 1 .` / `checkov -f plan.json --framework terraform_plan` |
| Политики и их тесты | `terraform show -json tfplan > plan.json` → `conftest test plan.json -p policy/` · `conftest verify` |
| Тесты модуля | `terraform test` (`tests/*.tftest.hcl`), отчёт `-junit-xml=report.xml` |
| Без облака | `mock_provider "aws" {}` / `mock_provider "yandex" {}` |
| Проверить отказ валидации | `expect_failures = [var.x]` + `command = plan` |
| Подменить значение | `override_resource` / `override_data` / `override_module` |
| Интеграция на Go | Terratest v2: `InitAndApplyContext` + `defer DestroyContext` |
| Дрейф | `terraform plan -detailed-exitcode` (exit 2 = изменения) |
| Стоимость | Infracost — см. раздел FinOps этого курса |

---

## 🧠 Что запомнить

1. Пирамида IaC: fmt/validate → tflint → сканер → политики на плане → `terraform test`
   с моками → интеграция в sandbox → дрейф; чем ниже, тем чаще и дешевле.
2. ⭐ `terraform test`: `*.tftest.hcl`, `run`-блоки по порядку, `command` по умолчанию —
   **apply**; для логики модуля — `command = plan` и/или `mock_provider`.
3. `mock_provider` (1.7+) подменяет провайдер: креды не нужны, API не вызывается.
4. `override_*` задают значения; `expect_failures` доказывает, что валидация запрещает плохой ввод.
5. Моки проверяют код, а не облако: значения и права — tflint, сканеры, интеграция.
6. tfsec влился в trivy — `trivy config`; checkov сканирует и plan JSON.
7. Политики conftest — на plan JSON (итоговые значения, `tags_all`) и с тестами (`conftest verify`).
8. Для Yandex Cloud и KZ-облаков готовых правил сканеров почти нет — нужны свои политики.
9. Terratest v2 — пути `modules/<имя>/v2` и API с контекстом; всегда `defer DestroyContext`
   и увеличенный `-timeout`.
10. Дрейф ловится `plan -detailed-exitcode` по расписанию с read-only правами.

---

## Задачи

> Стенд: Terraform 1.10+ (или OpenTofu), tflint, trivy и/или checkov, conftest; для блока C
> облако **не нужно** до задачи C10 (там — sandbox-аккаунт AWS или каталог Yandex Cloud).
> Модуль для опытов — контракт `network` из [«Модули»](/terraform/05-modules), §7.

---

### Блок A. Теория

**A1.** ⭐ Нарисуй пирамиду тестирования IaC. Почему её нижние уровни запускают чаще верхних?

<details><summary>Ответ</summary>

Снизу вверх: fmt/validate → tflint → сканер безопасности → политики на плане →
`terraform test` с моками → интеграция в sandbox → дрейф. Нижние уровни стоят секунды,
не требуют облака и денег, поэтому их гоняют на каждый коммит; верхние медленные и платные —
их запускают реже (релиз модуля, ночью).

</details>

**A2.** Что проверяет `terraform validate` и чего он **не** проверяет? Зачем ему
`init -backend=false`?

<details><summary>Ответ</summary>

Синтаксис, ссылки между объектами, типы и обязательные аргументы по схеме
провайдера. Не проверяет допустимость значений (`t3.mirco`), права, существование
объектов в облаке, логику `for_each`. `init -backend=false` скачивает провайдеры и модули,
не трогая стейт — validate можно запускать в CI без кредов к backend.

</details>

**A3.** Что добавляет tflint к `validate`? Приведи три примера ошибок, которые ловит только он.

<details><summary>Ответ</summary>

Несуществующий тип инстанса/класс БД, неиспользуемые переменные и data,
отсутствие `required_version`/версий провайдеров, отсутствие обязательных тегов
(`aws_resource_missing_tags`), устаревший синтаксис интерполяции.

</details>

**A4.** Что случилось с tfsec и что использовать вместо него?

<details><summary>Ответ</summary>

tfsec влился в Trivy: репозиторий не архивирован, но развитие и новые правила идут
в `trivy config`. В новых пайплайнах используют trivy (или checkov).

</details>

**A5.** Чем сканирование `.tf` отличается от сканирования plan JSON? Когда что выбрать?

<details><summary>Ответ</summary>

`.tf` — быстро, без кредов, но значения переменных, модулей и `default_tags` могут
быть не вычислены. План — итоговые значения, развёрнутые модули, но нужен `plan`
(read-only креды). На MR обычно оба: сканер по коду рано, политики — по плану.

</details>

**A6.** ⭐ Почему политики conftest удобнее писать на plan JSON, а не на исходных `.tf`?

<details><summary>Ответ</summary>

В плане подставлены переменные и tfvars, раскрыты `for_each` и модули, смёржены
`default_tags` в `tags_all`: проверяется то, что уйдёт в API. Формат плана одинаков для любого
провайдера — один язык политик для AWS, Yandex и OpenStack.

</details>

**A7.** Как устроен файл `*.tftest.hcl`: какие блоки бывают и в каком порядке выполняются `run`?

<details><summary>Ответ</summary>

Блоки: `test` (настройки), `variables`, `provider`/`mock_provider`, `override_*`,
`run`. `run` выполняются последовательно в порядке файла (параллельно — только явно
разрешённые и независимые), видят стейт предыдущих и их outputs через `run.<имя>`;
в конце — destroy в обратном порядке.

</details>

**A8.** ⭐ Какое значение `command` у `run` по умолчанию и чем это опасно?

<details><summary>Ответ</summary>

`apply`. С настоящим провайдером и кредами окружения тест **создаст реальные
ресурсы** там, куда смотрят креды (включая прод, если CI с прод-ролью). Для логики модуля —
`command = plan` и/или `mock_provider`, для интеграции — явный sandbox.

</details>

**A9.** Что делает `mock_provider` и почему с ним тесты идут без облачных кредов?
Нужен ли при этом `terraform init`?

<details><summary>Ответ</summary>

Подменяет провайдер: вызовы API не делаются, вычисляемые атрибуты генерируются
(строки — случайные, числа — 0 и т.д.). Провайдер не конфигурируется, поэтому креды не нужны.
`terraform init` нужен: Terraform берёт схему ресурсов из скачанного провайдера
(из registry, зеркала или кэша плагинов).

</details>

**A10.** Чем `override_resource` отличается от `mock_resource` в `mock_provider`?

<details><summary>Ответ</summary>

`mock_resource` внутри `mock_provider` задаёт `defaults` для **всех** ресурсов
этого типа от мок-провайдера. `override_resource` задаёт значения **конкретному** ресурсу
по адресу (`target`) и работает на уровне файла или `run`, в том числе поверх настоящего
провайдера.

</details>

**A11.** Как проверить, что валидация переменной действительно запрещает плохое значение?

<details><summary>Ответ</summary>

`run` с `command = plan`, плохим значением в `variables` и
`expect_failures = [var.имя]`: кейс проходит, только если валидация упала.

</details>

**A12.** Чего моки принципиально **не** могут проверить? Какие уровни это закрывают?

<details><summary>Ответ</summary>

Что облако примет значения (тип инстанса, квоты, регион), что IAM/SG реально
пропустят трафик и запросы, поведение API и eventual consistency. Закрывают tflint (часть
значений), сканеры и интеграционные тесты в sandbox.

</details>

**A13.** Чем Terratest отличается от `terraform test` с настоящим провайдером?
Что изменилось в Terratest v2?

<details><summary>Ответ</summary>

Terratest — Go: произвольные проверки (HTTP, SSH, SDK облака, k8s), ретраи облачных
ошибок, идемпотентность; нужен Go. `terraform test` — только HCL-условия, зато без
дополнительных языков. В v2 (сентябрь 2026) пакеты переехали на пути
`github.com/gruntwork-io/terratest/modules/<имя>/v2`, API — с `context`
(`InitAndApplyContext`, `DestroyContext`), устаревшие функции удалены.

</details>

**A14.** Как ловить дрейф автоматически? Что означают коды выхода `plan -detailed-exitcode`?

<details><summary>Ответ</summary>

Джоба по расписанию: `terraform plan -detailed-exitcode` с read-only правами и
`-lock=false`. Коды: 0 — изменений нет, 1 — ошибка, 2 — план не пустой (дрейф или
неприменённые изменения кода) → алерт с выводом плана.

</details>

**A15.** Почему для Yandex Cloud и казахстанских OpenStack-облаков своих политик нужно больше,
чем для AWS?

<details><summary>Ответ</summary>

Готовые сканеры (checkov, trivy) и tflint-ruleset покрывают AWS/Azure/GCP; правил
под `yandex_*` и `openstack_*` практически нет. Значит, «SSH из мира», «бакет без
шифрования», «нет меток» для них проверяют только свои политики на plan JSON.

</details>

---

### Блок B. «Оцени решение»

```text:no-line-numbers
B1.  В CI только terraform plan, «остальное проверим на stage»
B2.  pre-commit: terraform fmt, validate, tflint; в MR — trivy и checkov с --exit-code 1 по HIGH
B3.  run "creates_bucket" { assert { ... } }  — без command и без mock_provider, CI с prod-кредами
B4.  assert { condition = aws_vpc.this.tags["Name"] == "${var.name}-${var.env}" }
B5.  run "bad_env" { command = plan, variables { env = "production" }, expect_failures = [var.env] }
B6.  checkov --soft-fail в пайплайне уже полтора года
B7.  #checkov:skip=CKV_AWS_24 — без причины, в 40 местах репозитория
B8.  Политика conftest: deny, если after.tags пусто (tags, а не tags_all), провайдер с default_tags
B9.  Для кода на провайдере yandex в CI только trivy config и checkov
B10. Terratest без defer Destroy, go test без -timeout
B11. Интеграционные тесты модулей гоняются ночью в отдельном sandbox-аккаунте с бюджетом
B12. Ночной plan с -detailed-exitcode и алертом при коде 2
B13. Политики conftest есть, тестов политик (conftest verify) нет
B14. terraform test с mock_provider на каждый MR в репозиторий модулей, JUnit-отчёт в MR
```

<details><summary>Ответ</summary>

**B1.** Слабо: ошибки находятся поздно и дорого; нет статики, политик и тестов модулей.
**B2.** Хорошая база нижних уровней пирамиды.
**B3.** Опасно: `command = apply` по умолчанию + настоящий провайдер + прод-креды = реальные
ресурсы в проде. Нужны моки или sandbox-креды и `command = plan`.
**B4.** Тест повторяет реализацию: ломается при рефакторинге и ничего не ловит.
**B5.** Правильный тест валидации (в файле — каждый атрибут на своей строке).
**B6.** Сканер выключен по факту: отчёты никто не читает; переход на `--exit-code 1` по HIGH.
**B7.** Массовые подавления без причины = выключенная проверка; причина обязательна.
**B8.** Ошибка: теги из `default_tags` лежат в `tags_all`, политика даст ложные срабатывания
(или пропустит, если проверять не то поле).
**B9.** Иллюзия защиты: правил под `yandex_*` почти нет — нужны свои политики.
**B10.** «Сироты» в облаке и тест, убитый через 10 минут дефолтного таймаута.
**B11.** Правильно: отдельный аккаунт, бюджет, ночь.
**B12.** Правильный детектор дрейфа.
**B13.** Политики могут молча перестать срабатывать после рефакторинга; `conftest verify` в CI.
**B14.** Эталон для репозитория модулей.

</details>

---

### Блок C. Практика

#### C1. 🔑 Пирамида одной командой
Сделай в корне репозитория `Makefile` (или `scripts/test.sh`) с целями `fmt`, `validate`,
`lint`, `sec`, `policy`, `test` и общей `check`, которая запускает их по порядку и падает
на первой ошибке. Засеки время каждого уровня.

#### C2. tflint и его пределы
1. Настрой `.tflint.hcl` с `preset = "recommended"` и плагином `aws` 0.49.0.
2. Напиши `instance_type = "t3.mirco"` прямо в ресурсе — поймал ли tflint?
3. Теперь задай тип через `locals.sizes.aws[each.value.size]` (тема 04, §7) с опечаткой
   в значении map — поймал ли? Почему? Как закрыть дыру?

<details><summary>Ответ</summary>

Литерал `t3.mirco` tflint ловит (`aws_instance_invalid_type`). Значение, пришедшее
через `local.sizes.aws[each.value.size]`, — нет (на 0.64.0 такая опечатка прошла): tflint
не всегда может вычислить выражение. Закрывают `validation` на входе (`contains(["small",
"large"], ...)`) плюс тест карты размеров или политика на плане (там тип уже вычислен).

</details>

#### C3. Сканеры на одном и том же баге
1. Открой SSH `0.0.0.0/0` в `aws_vpc_security_group_ingress_rule`.
2. Прогони `trivy config .` и `checkov -d .` — запиши ID находок.
3. Подави одну находку **правильно** (в коде, с причиной) и объясни, почему это лучше
   `--skip-check` в CI.
4. Повтори шаг 1 для `yandex_vpc_security_group` — что нашли сканеры?

<details><summary>Ответ</summary>

checkov — `CKV_AWS_24`, trivy — `AVD-AWS-0107`. Подавление в коде видно в diff,
проходит ревью и привязано к конкретному ресурсу; `--skip-check` в CI выключает правило для
всего репозитория. Для `yandex_vpc_security_group` сканеры, скорее всего, ничего не найдут.

</details>

#### C4. 🔑 conftest: политика и её тесты
1. Возьми политику из конспекта (§3) и прогони на плане из C8 и на своём плане Yandex.
2. Допиши правило для **inline** `ingress` у `aws_security_group` (`cidr_blocks`).
3. Напиши `policy/terraform_test.rego`: один тест «SSH из мира запрещён», один «HTTPS
   из мира разрешён», один «ресурс без тегов отклонён». `conftest verify` — зелёный.
4. Добавь `warn` (а не `deny`) на `instance_type` крупнее `*.large` в dev.

<details><summary>Ответ</summary>

Inline-правило: `some ing in object.get(rc.change.after, "ingress", [])`,
`some cidr in ing.cidr_blocks`, `cidr in world`, `covers_22(ing.from_port, ing.to_port)`.
`warn` не роняет `conftest test`, но печатается в выводе.

</details>

#### C5. 🔑 `terraform test` с моками (AWS)
1. Для `modules/network/aws` напиши `tests/network.tftest.hcl` из конспекта (§4.2).
2. `terraform test` без AWS-кредов (`env -u AWS_PROFILE -u AWS_ACCESS_KEY_ID`) — зелёный.
3. Сломай логику (`cidrsubnet(var.cidr, 8, each.value + 1)`) — какой `run` упал и с каким
   сообщением? Верни.
4. Запусти с `-verbose` и с `-junit-xml=report.xml`, открой отчёт.

<details><summary>Ответ</summary>

Упадёт `run "subnets_are_carved_from_cidr"` с сообщением «Вторая подсеть должна быть
10.20.1.0/24» (получится `10.20.2.0/24`). Отчёт JUnit содержит по testcase на каждый `run`.

</details>

#### C6. Все запреты — под тестом
Для каждой `validation` модуля (`env`, `cidr`, `ssh_allowed_cidrs`) сделай `run`
с `command = plan` и `expect_failures`. Затем ослабь одну валидацию и убедись,
что соответствующий тест упал.

#### C7. Моки и переопределения
1. Добавь в модуль `data "aws_availability_zones"` и выбирай зоны из него, если `zones` пуст.
2. В тесте задай `mock_data "aws_availability_zones"` с `defaults = { names = [...] }`.
3. В отдельном `run` переопредели `aws_vpc` через `override_resource` и проверь `output.network_id`.
4. Что будет, если не задать `defaults` для `names`? Проверь и объясни.

<details><summary>Ответ</summary>

Без `defaults` мок вернёт для `names` пустой список: модуль не создаст подсетей
(или упадёт на индексе) — поэтому для data, от которых зависит логика, `defaults` задают явно.

</details>

#### C8. План без облака (AWS)
1. Сделай корневую конфигурацию, вызывающую модуль, с провайдером `aws`:
   `access_key = "mock"`, `secret_key = "mock"`, `skip_credentials_validation`,
   `skip_requesting_account_id`, `skip_metadata_api_check` = `true`.
2. `terraform plan -out=tfplan && terraform show -json tfplan > plan.json`.
3. Найди в `plan.json` `tags_all` одного ресурса — откуда там теги провайдера?
4. Добавь `data "aws_vpc" "default"` — что случилось с планом и почему?

<details><summary>Ответ</summary>

`tags_all` = `tags` ресурса + `default_tags` провайдера, смёрженные Terraform'ом.
С `data "aws_vpc" "default"` план падает: data читается через API, фиктивные креды не проходят.
Для Yandex трюк не работает вовсе — провайдер получает IAM-токен при настройке.

</details>

#### C9. Yandex-реализация и `kz1`
1. Для `modules/network/yandex` напиши тот же набор `run`-проверок с `mock_provider "yandex"`.
2. Добавь `run "kz1_single_zone"` (`zones = ["kz1-a"]`).
3. Добавь валидацию: если в `zones` есть `kz1-a`, других зон быть не должно;
   покрой её `expect_failures`.
4. Сравни два тест-файла: что получилось вынести в общий «тест контракта»?

<details><summary>Ответ</summary>

`condition = !contains(var.zones, "kz1-a") || length(var.zones) == 1`. В общий тест
контракта выносятся проверки, не зависящие от типов ресурсов: outputs, отказы валидаций;
проверки конкретных ресурсов (`aws_subnet` / `yandex_vpc_subnet`) остаются свои.

</details>

#### C10. Интеграция в песочнице
Выбери вариант:
- **A (без Go):** `tests/integration.tftest.hcl` с настоящим провайдером AWS или Yandex,
  `run "setup"` с `random_pet` и проверкой `startswith(output.network_id, "vpc-")`
  (для Yandex — непустой id).
- **B (Terratest v2):** тест из конспекта (§5) на `examples/aws`.

Запусти в sandbox, засеки время, убедись, что после теста ресурсов не осталось. Затем прерви
тест `Ctrl+C` посреди `apply` — что осталось и как это найти по метке?

<details><summary>Ответ</summary>

После прерывания teardown не выполнился: ресурсы остались. Найти —
`aws resourcegroupstaggingapi get-resources --tag-filters Key=managed-by,Values=terraform-test`
или `yc vpc network list --format json | jq '.[] | select(.labels["managed-by"]=="terraform-test")'`.

</details>

#### C11. Пайплайн
Собери GitLab CI (или GitHub Actions): `tflint` и `trivy` в `lint`, `terraform test`
матрицей по двум реализациям модуля с JUnit-отчётами, `plan` → `plan.json`, `conftest`.
Намеренно сломай по одной проверке на каждом уровне и убедись, что MR блокируется
на **нужной** джобе.

#### C12. Дрейф
Сделай джобу по расписанию с `plan -detailed-exitcode -lock=false`, которая падает только на
коде 2 и прикладывает `drift.txt`. Поменяй тег ресурса руками в консоли — сработало?

<details><summary>Ответ</summary>

Ручная правка тега даёт `~` в плане → код 2 → джоба падает и прикладывает
`drift.txt`.

</details>

---

### Блок D. Инциденты

**D1.** `terraform test` в CI создал в проде бакет `test-bucket-xyz` и удалил его через
минуту. Как это произошло и как предотвратить?

<details><summary>Ответ</summary>

`run` без `command = plan` и без моков выполнил `apply` настоящим провайдером
с прод-кредами CI. Профилактика: `mock_provider` в тестах модулей, отдельная sandbox-роль
для интеграции, прод-креды только в джобе `apply` на защищённой ветке.

</details>

**D2.** После рефакторинга модуля все тесты зелёные, но на stage план пересоздаёт подсети.
Почему тесты не поймали?

<details><summary>Ответ</summary>

Тесты проверяли outputs и валидации, но не адреса ресурсов: изменился ключ
`for_each` (или адрес), что даёт пересоздание. Лечится блоком `moved`; ловится планом
на реальном окружении в MR и тестом, фиксирующим ключи (`keys(aws_subnet.this)`).

</details>

**D3.** `terraform test` падает локально с `Reference to undeclared output value`, хотя
модуль «не меняли». Что проверить?

<details><summary>Ответ</summary>

Переименован/удалён output в модуле, тест ссылается на старое имя; другой модуль
подставлен через `run.module`; устаревший `.terraform` (нужно `terraform init`).

</details>

**D4.** Сканер блокирует MR из-за открытого 443 на публичном ALB. Команда хочет выключить
сканер. Что предложишь?

<details><summary>Ответ</summary>

Не выключать сканер: подавить конкретную находку в коде с причиной («публичный ALB,
443 — это продукт»), либо исключение по ресурсу; порог `--severity HIGH,CRITICAL`.

</details>

**D5.** Политика «нет SSH из мира» зелёная, а в облаке SSH открыт в `0.0.0.0/0`. Гипотезы?

<details><summary>Ответ</summary>

Правило открыто иначе, чем проверяет политика: inline `ingress` в
`aws_security_group`, `aws_security_group_rule`, `ip_protocol = "-1"`, `::/0`, диапазон портов
вокруг 22; ресурс создан вне Terraform (дрейф); политика не запускалась на этом плане.

</details>

**D6.** Интеграционные тесты за месяц «наели» $300 в sandbox. Что пошло не так?

<details><summary>Ответ</summary>

Тесты не удаляли ресурсы (упавшие прогоны, нет `defer Destroy`), нет уборки
по метке и бюджета с алертом, тяжёлые ресурсы (NAT, кластеры) в каждом тесте.

</details>

**D7.** Terratest-тест падает через ровно 10 минут с `panic: test timed out`, в облаке
остаются ресурсы. Что делать?

<details><summary>Ответ</summary>

Увеличить `go test -timeout` (30m+), всегда `defer DestroyContext`, уборка sandbox
по метке после падений; оставшиеся ресурсы удалить вручную/скриптом.

</details>

**D8.** `conftest test` проходит, хотя в плане есть ресурс без обязательных тегов.
Что может быть в политике не так?

<details><summary>Ответ</summary>

Проверяется `tags` вместо `tags_all`; фильтр действий пропускает ресурс;
`after` пуст из-за `(known after apply)`; ресурс не поддерживает теги и отфильтрован;
политика в другом `package`, а conftest ищет `main` (нужен `--namespace`).

</details>

**D9.** Ночная джоба дрейфа падает каждую ночь, хотя руками никто ничего не менял. Причины?

<details><summary>Ответ</summary>

Поля, которые меняет платформа (теги автоскейлинга, версии), неприменённые
изменения из `main`, недетерминированный код (`timestamp()`), обновление провайдера
в CI без lock-файла. Разобрать план, исправить код или `ignore_changes` для платформенных полей.

</details>

**D10.** Модуль под AWS и Yandex: тесты AWS-реализации проходят, потребители Yandex-реализации
сломались после релиза. Как это не пропустить в будущем?

<details><summary>Ответ</summary>

Тест контракта (одинаковые `run`-проверки outputs и валидаций) в **обеих**
реализациях, матрица в CI и релиз только при зелёных тестах обеих.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как вы тестируете Terraform-код?

<details><summary>Ответ</summary>

Пирамидой: fmt/validate и tflint в pre-commit и MR, сканер (trivy/checkov), политики
conftest на плане, `terraform test` с моками для модулей, интеграция в sandbox
для релиза модулей, ночной дрейф.

</details>

**2.** Что такое `terraform test` и чем он отличается от Terratest?

<details><summary>Ответ</summary>

Встроенный фреймворк (1.6+): `*.tftest.hcl`, `run`, `assert`, моки (1.7+). Terratest —
Go-библиотека с произвольными проверками реальных ресурсов.

</details>

**3.** Как протестировать модуль без доступа к облаку?

<details><summary>Ответ</summary>

`terraform test` с `mock_provider` и `command = plan`; нужен только `terraform init`.

</details>

**4.** Какие инструменты статического анализа IaC знаешь и чем они отличаются?

<details><summary>Ответ</summary>

tflint (ошибки и best practices, правила облака), checkov и trivy (безопасность, сотни
правил), conftest/OPA (свои политики).

</details>

**5.** Что такое policy as code и где её применяют в Terraform?

<details><summary>Ответ</summary>

Правила в виде кода (Rego), которые проверяют план в CI: теги, запреты, лимиты стоимости.

</details>

**6.** Почему политики проверяют на plan JSON?

<details><summary>Ответ</summary>

Там итоговые значения, развёрнутые модули и `tags_all`, формат одинаков для всех провайдеров.

</details>

**7.** Как проверить, что валидации переменных работают?

<details><summary>Ответ</summary>

`run` с `command = plan` и `expect_failures = [var.x]` на каждый запрет.

</details>

**8.** Как устроить интеграционные тесты, чтобы они не разоряли и не мусорили?

<details><summary>Ответ</summary>

Отдельный sandbox-аккаунт/каталог с бюджетом, уникальные имена и метки, `defer Destroy`,
ночная уборка по метке, OIDC/WIF-роль только на sandbox.

</details>

**9.** Как обнаруживают дрейф?

<details><summary>Ответ</summary>

`plan -detailed-exitcode` по расписанию, алерт на код 2.

</details>

**10.** Как выглядит пайплайн проверок инфраструктурного MR у вас?

<details><summary>Ответ</summary>

lint → security → plan → policy → тесты модулей → стоимость → ручной apply на main.

</details>

---

### 🎯 Чек-лист

- [ ] ⭐ Объясняю пирамиду тестирования IaC и что ловит каждый уровень
- [ ] Настроил tflint с `tflint-ruleset-aws` и знаю его ограничения
- [ ] Запускаю trivy/checkov и подавляю находки только в коде с причиной
- [ ] Написал политику conftest на plan JSON для AWS и Yandex и тесты к ней
- [ ] ⭐ Покрыл модуль `terraform test` с `mock_provider` — без облачных кредов
- [ ] Каждая `validation` модуля покрыта `expect_failures`
- [ ] Пользовался `override_resource` / `mock_data`
- [ ] Прогнал интеграционный тест в sandbox и убедился, что уборка работает
- [ ] Собрал пайплайн с JUnit-отчётами тестов в MR
- [ ] Настроил ночной поиск дрейфа
