---
title: "02. Провайдер, ресурс, plan и apply"
description: "Жизненный цикл init/plan/apply/destroy, синтаксис HCL, зависимости ресурсов, настройка провайдеров AWS и Yandex Cloud"
---

# 02. Провайдер, ресурс, plan и apply ⭐

> Роадмап → Terraform → *«Понимать концепции: Провайдер, Ресурс, План, Apply»*.
>
> **После темы ты умеешь:** написать первую конфигурацию, объяснить каждый шаг
> `init → plan → apply → destroy`, читать вывод плана и понимать синтаксис HCL.

---

## 🗺️ Жизненный цикл

```text:no-line-numbers
  .tf файлы                 ┌──────────────────────────────────────────┐
  (желаемое состояние)      │             TERRAFORM                    │
        │                   │                                          │
        ├──► terraform init ─┤ скачать провайдеры, настроить backend    │
        │                   │                                          │
        ├──► terraform plan ─┤ сравнить: КОД ↔ СТЕЙТ ↔ РЕАЛЬНОСТЬ       │
        │                   │ вывести: + создать, ~ изменить, - удалить│
        │                   │                                          │
        ├──► terraform apply─┤ выполнить план через API провайдера     │
        │                   │ обновить стейт                           │
        │                   │                                          │
        └──► terraform destroy─ удалить всё, что описано               │
                            └──────────────────────────────────────────┘
```

---

## 1. Минимальная конфигурация

```hcl
# versions.tf — ⭐ всегда фиксируй версии
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"          # >= 3.0.0, < 4.0.0
    }
  }
}

# main.tf
provider "docker" {}              # настройка провайдера (адрес, креды, регион)

resource "docker_image" "nginx" {          # ТИП ресурса и ИМЯ в коде
  name         = "nginx:1.27-alpine"
  keep_locally = false
}

resource "docker_container" "web" {
  name  = "tf-web"
  image = docker_image.nginx.image_id      # ⭐ ссылка = неявная зависимость
  ports {
    internal = 80
    external = 8088
  }
}

# outputs.tf
output "url" {
  value = "http://localhost:${docker_container.web.ports[0].external}"
}
```

```text:no-line-numbers
resource "docker_container" "web" { ... }
          └──────┬──────┘  └─┬─┘
         тип ресурса       имя в коде
         (даёт провайдер)  (твоё; адрес — docker_container.web)
```

---

## 2. Основные команды

```bash
terraform init                 # скачать провайдеры и модули, настроить backend
terraform init -upgrade        # обновить версии в рамках ограничений
terraform fmt -recursive       # привести форматирование к канону
terraform validate             # проверить синтаксис и ссылки
terraform plan                 # ⭐ что изменится
terraform plan -out=tfplan     # сохранить план в файл
terraform apply                # применить (спросит подтверждение)
terraform apply tfplan         # применить ровно сохранённый план (в CI)
terraform apply -auto-approve  # ⚠️ без вопросов — только в CI после ревью
terraform destroy              # удалить всё описанное
terraform show                 # текущее состояние в читаемом виде
terraform output               # значения outputs
terraform output -raw url      # одно значение без кавычек (для скриптов)
terraform providers            # какие провайдеры используются
terraform console              # интерактивная проверка выражений ⭐ недооценённая команда
```

Точечные операции:
```bash
terraform plan  -target=docker_container.web     # ⚠️ только для отладки, не для рутины
terraform apply -replace=docker_container.web    # пересоздать конкретный ресурс
terraform refresh                                # обновить стейт из реальности (устаревшее)
```

---

## 3. ⭐ Как читать вывод plan

```text:no-line-numbers
Terraform will perform the following actions:

  # docker_container.web will be created
  + resource "docker_container" "web" {
      + image = "sha256:abc..."
      + name  = "tf-web"
    }

  # yandex_compute_instance.app will be updated in-place
  ~ resource "yandex_compute_instance" "app" {
      ~ description = "old" -> "new"
    }

  # yandex_compute_disk.data must be replaced
-/+ resource "yandex_compute_disk" "data" {
      ~ type = "network-hdd" -> "network-ssd" # forces replacement  ⚠️
    }

  # aws_s3_bucket.old will be destroyed
  - resource "aws_s3_bucket" "old" { ... }

Plan: 1 to add, 1 to change, 1 to destroy.
```

| Символ | Значение | Опасность |
|--------|----------|-----------|
| `+` | Создать | Обычно безопасно |
| `~` | Изменить на месте | Проверить, не вызовет ли простой |
| `-/+` | Пересоздать (destroy → create) | ⚠️ Потеря данных: диск, база, IP |
| `-` | Удалить | ⚠️ Читать внимательно |
| `<=` | Прочитать data source | Безопасно |

⭐ Правило дежурного: **любая строка с `destroy` или `forces replacement` на проде
требует осознанного ответа «да, я понимаю, что будет пересоздано»**.

---

## 4. HCL: синтаксис за пять минут

```hcl
# комментарий (# или //), /* блочный */

# --- блоки ---
resource "тип" "имя" {
  строка   = "значение"
  число    = 42
  булево   = true
  список   = ["a", "b"]
  словарь  = { key = "value", env = "prod" }

  вложенный_блок {
    поле = "значение"
  }
}

# --- интерполяция и выражения ---
name    = "web-${var.env}-${count.index}"
enabled = var.env == "prod" ? true : false        # тернарный оператор
tags    = merge(var.common_tags, { role = "web" })
size    = max(var.min_size, 2)
list    = [for s in var.subnets : s.id]           # генератор списка
map     = { for k, v in var.nodes : k => v.ip }   # генератор словаря

# --- многострочная строка ---
user_data = <<-CLOUDINIT
  #cloud-config
  packages: [docker.io]
CLOUDINIT
```

Полезные функции (проверять удобно в `terraform console`):
```text:no-line-numbers
join, split, format, replace, lower, upper, trimspace
length, keys, values, lookup, merge, concat, flatten, distinct, toset
file, templatefile, jsonencode, jsondecode, yamlencode, base64encode
cidrsubnet, cidrhost, coalesce, try, can
```

---

## 5. Ссылки и зависимости

```hcl
resource "docker_network" "app" { name = "app-net" }

resource "docker_container" "web" {
  name  = "web"
  image = docker_image.nginx.image_id     # ⭐ неявная зависимость
  networks_advanced { name = docker_network.app.name }
}
```

```text:no-line-numbers
Terraform строит ГРАФ зависимостей по ссылкам:
  docker_image.nginx ──► docker_container.web ◄── docker_network.app
Ресурсы без связей создаются ПАРАЛЛЕЛЬНО (по умолчанию до 10 одновременно).

Если зависимость есть, но её не видно из кода:
  depends_on = [aws_iam_role_policy.example]      # явная зависимость
```

Мета-аргументы ресурса:
| Аргумент | Смысл |
|----------|-------|
| `depends_on` | Явная зависимость |
| `count` / `for_each` | Несколько экземпляров (тема 04) |
| `provider` | Использовать альтернативный провайдер (другой регион/аккаунт) |
| `lifecycle` | `create_before_destroy`, `prevent_destroy`, `ignore_changes` |

```hcl
lifecycle {
  prevent_destroy = true                       # ⭐ защита прод-базы от удаления
  ignore_changes  = [tags["LastModified"]]     # игнорировать внешние изменения поля
  create_before_destroy = true                 # сначала создать замену, потом удалить
}
```

---

## 6. Провайдеры: настройка и креды

```hcl
provider "yandex" {
  cloud_id  = var.cloud_id
  folder_id = var.folder_id
  zone      = "ru-central1-a"
  # token берётся из переменной окружения YC_TOKEN ⭐ (не хардкодим!)
}

# несколько конфигураций одного провайдера
provider "aws" {
  region = "eu-central-1"
}
provider "aws" {
  alias  = "backup"
  region = "eu-west-1"
}

resource "aws_s3_bucket" "backup" {
  provider = aws.backup       # ресурс в другом регионе
  bucket   = "my-backups"
}
```

```text:no-line-numbers
Как передавать секреты провайдеру:
  ✅ переменные окружения (YC_TOKEN, AWS_ACCESS_KEY_ID, TF_VAR_*)
  ✅ секреты CI/CD
  ✅ Vault / хранилище секретов облака
  ❌ значения в .tf и закоммиченных .tfvars
```

После `init` появляется `.terraform.lock.hcl` — файл с зафиксированными версиями
и контрольными суммами провайдеров. ⭐ Его **коммитят** в git: он гарантирует,
что у всех и в CI одинаковые версии.

### 6.1 AWS / Yandex Cloud: провайдер и вход

> Облачные примеры блока показываются парой «AWS / Yandex Cloud» (плюс казахстанские облака,
> где это важно). Версии — **проверь, сентябрь 2026**.

```hcl
# versions.tf — оба провайдера (в реальном проекте обычно один)
terraform {
  required_version = ">= 1.10.0"            # 1.10+ нужен для use_lockfile в S3 backend (тема 03)
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }            # сентябрь 2026: 6.66
    yandex = { source = "yandex-cloud/yandex", version = "~> 0.230" }    # сентябрь 2026: 0.230
  }
}
```

**AWS:**
```hcl
provider "aws" {
  region = "eu-central-1"                   # региона AWS в Казахстане нет — берут Франкфурт и соседей
  default_tags {                            # ⭐ теги на все ресурсы провайдера (учёт денег, владелец)
    tags = { project = "lab", env = "dev", owner = "nurik", managed-by = "terraform" }
  }
  # креды НЕ здесь: провайдер сам берёт AWS_PROFILE / AWS_ACCESS_KEY_ID / роль из окружения
}
```

**Yandex Cloud** (регион Россия — пример выше в §6; регион Казахстан `kz1`):
```hcl
provider "yandex" {
  endpoint         = "api.yandexcloud.kz:443"    # ⭐ без этого провайдер пойдёт в API региона Россия
  storage_endpoint = "storage.yandexcloud.kz"    # для yandex_storage_* ресурсов
  cloud_id         = var.cloud_id
  folder_id        = var.folder_id
  zone             = "kz1-a"                     # в kz1 одна зона
}
```

| Вход | AWS | Yandex Cloud |
|------|-----|--------------|
| Человек на ноутбуке | `aws sso login --profile dev` → `export AWS_PROFILE=dev` | `yc init` → `export YC_TOKEN=$(yc iam create-token)` (живёт ≤ 12 ч) |
| CI без долгоживущих ключей ⭐ | OIDC → роль (`AssumeRoleWithWebIdentity`) | Workload identity federation → `YC_TOKEN` |
| Сервис вне облака (крайний случай) | Access keys IAM-пользователя | Авторизованный ключ SA: `service_account_key_file` |
| Другой аккаунт / каталог | `assume_role { role_arn = ... }` в провайдере | Другой `folder_id` / `cloud_id` |
| Проверить, кто я | `aws sts get-caller-identity` | `yc config list`, `yc iam service-account get ...` |

⭐ Общее правило одинаково для обоих облаков: **в `.tf` нет ни ключей, ни токенов** —
только регион/каталог; креды приходят из окружения, а в CI — временные, через федерацию.

---

## 7. Первый рабочий пример на облаке

**Yandex Cloud:**

```hcl
resource "yandex_vpc_network" "this" { name = "lab-net" }

resource "yandex_vpc_subnet" "a" {
  name           = "lab-subnet-a"
  zone           = "ru-central1-a"
  network_id     = yandex_vpc_network.this.id
  v4_cidr_blocks = ["10.10.1.0/24"]
}

resource "yandex_compute_instance" "web" {
  name        = "web-1"
  platform_id = "standard-v3"
  zone        = "ru-central1-a"

  resources {
    cores         = 2
    memory        = 2
    core_fraction = 20
  }

  boot_disk {
    initialize_params {
      image_id = data.yandex_compute_image.ubuntu.id
      size     = 20
    }
  }

  network_interface {
    subnet_id = yandex_vpc_subnet.a.id
    nat       = true
  }

  metadata = {
    ssh-keys  = "ubuntu:${file("~/.ssh/id_ed25519.pub")}"
    user-data = file("${path.module}/cloud-init.yaml")
  }
}

output "web_ip" {
  value = yandex_compute_instance.web.network_interface[0].nat_ip_address
}
```
```bash
terraform init && terraform plan && terraform apply
ssh ubuntu@$(terraform output -raw web_ip)
terraform destroy          # ⚠️ обязательно после лабы
```

### 7.1 Тот же стенд на AWS: ВМ + security group

Для первого раза — дефолтная VPC (эталонная сеть на 2 AZ).
Код проверен `terraform validate` на `hashicorp/aws` 6.66.0.

```hcl
data "aws_vpc" "default" { default = true }

data "aws_ssm_parameter" "ubuntu" {          # ⭐ свежий AMI без хардкода ami-id
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

resource "aws_security_group" "web" {
  name   = "lab-web"
  vpc_id = data.aws_vpc.default.id
}

# правила — отдельными ресурсами (современный стиль провайдера 5+/6)
resource "aws_vpc_security_group_ingress_rule" "ssh" {
  security_group_id = aws_security_group.web.id
  ip_protocol       = "tcp"
  from_port         = 22
  to_port           = 22
  cidr_ipv4         = "${var.my_ip}/32"      # ⭐ SSH только со своего IP, не 0.0.0.0/0
}
resource "aws_vpc_security_group_ingress_rule" "http" {
  security_group_id = aws_security_group.web.id
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}
resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.web.id
  ip_protocol       = "-1"                  # весь исходящий трафик
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_key_pair" "me" {
  key_name   = "lab-key"
  public_key = file("~/.ssh/id_ed25519.pub")
}

resource "aws_instance" "web" {
  ami                         = data.aws_ssm_parameter.ubuntu.value
  instance_type               = "t3.micro"
  key_name                    = aws_key_pair.me.key_name
  vpc_security_group_ids      = [aws_security_group.web.id]
  associate_public_ip_address = true
  user_data                   = file("${path.module}/cloud-init.yaml")
  metadata_options { http_tokens = "required" }             # IMDSv2
  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }
  tags = { Name = "web-1" }
}

output "web_ip" { value = aws_instance.web.public_ip }
```

### 7.2 Security group рядом: Yandex Cloud

У Yandex правила — вложенные блоки одного ресурса; SG вешается на интерфейс ВМ
(`network_interface { security_group_ids = [...] }`):
```hcl
resource "yandex_vpc_security_group" "web" {
  name       = "lab-web"
  network_id = yandex_vpc_network.this.id
  ingress {
    protocol       = "TCP"
    port           = 22
    v4_cidr_blocks = ["${var.my_ip}/32"]
  }
  ingress {
    protocol       = "TCP"
    port           = 80
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    protocol       = "ANY"
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
}
```

| Понятие | AWS | Yandex Cloud |
|---------|-----|--------------|
| Сеть / подсеть | `aws_vpc` / `aws_subnet` (в AZ) | `yandex_vpc_network` / `yandex_vpc_subnet` (в зоне) |
| ВМ | `aws_instance` | `yandex_compute_instance` |
| Образ | `data "aws_ssm_parameter"` / `data "aws_ami"` | `data "yandex_compute_image"` (`family`) |
| Размер | `instance_type = "t3.micro"` | `platform_id` + `resources { cores, memory, core_fraction }` |
| SSH-ключ | `aws_key_pair` + `key_name` | `metadata = { ssh-keys = "..." }` |
| Публичный IP | `associate_public_ip_address` → `public_ip` | `nat = true` → `nat_ip_address` |
| Firewall | `aws_security_group` + `aws_vpc_security_group_*_rule` | `yandex_vpc_security_group` с блоками `ingress`/`egress` |
| Метки | `tags` (+ `default_tags` в провайдере) | `labels` (ключи строчными) |

Полное соответствие сервисов — в материалах по Yandex Cloud.
Казахстанские облака на OpenStack (PS Cloud и др.) — провайдер `openstack`
(материалы по облакам Казахстана): те же `init/plan/apply`, другие типы ресурсов.

---

## 8. Грабли

| Грабля | Симптом | Решение |
|--------|---------|---------|
| Не зафиксированы версии | «Вчера работало» | `required_version`, `version`, lock-файл в git |
| `apply -auto-approve` локально | Случайные изменения на проде | Только в CI после ревью плана |
| Не заметили `forces replacement` | Пересоздали диск/базу | Читать план целиком |
| Секреты в `.tf` | Утечка + они же в стейте | Переменные окружения, Vault |
| `-target` в рутине | Стейт и реальность расходятся | Использовать только для отладки |
| Правка ресурсов руками | Дрейф | Всё через код |
| Нет `prevent_destroy` на критичном | Одна опечатка = потеря данных | `lifecycle` на базах, дисках, бакетах |
| `.terraform/` и стейт в git | Мусор и утечки | `.gitignore` |
| Игнорирование `terraform fmt` | Шумные диффы в MR | `fmt` в pre-commit и CI |
| Yandex `kz1` без `endpoint` в провайдере | Ошибки авторизации/«не найдено»: запросы ушли в API региона Россия | `endpoint = "api.yandexcloud.kz:443"`, `storage_endpoint` |
| AWS: истёкшая SSO-сессия или не тот `AWS_PROFILE` | `ExpiredToken`, ресурсы «не в том аккаунте» | `aws sts get-caller-identity` перед `plan` |
| SSH в SG из `0.0.0.0/0` | Боты перебирают пароли через минуты | Свой `/32`, bastion или SSM/OS Login |

---

## 💼 Как это в DevOps

- `plan` — центральный артефакт ревью: его вывод прикладывают к MR, и коллеги смотрят
  именно diff инфраструктуры, а не «какой-то код».
- `apply` в зрелых командах запускается **только из CI** с ручным подтверждением:
  так исключаются «применил со своего ноутбука со старым кодом».
- `lifecycle { prevent_destroy = true }` ставят на всё, чья потеря критична:
  прод-базы, диски с данными, бакеты бэкапов.
- `.terraform.lock.hcl` в репозитории — обязательное требование воспроизводимости.
- Автодополнение, `terraform console` и `terraform show` — рабочие инструменты
  повседневной отладки, а не экзотика.

---

## 📌 Шпаргалка

| Хочу | Команда/код |
|------|-------------|
| Инициализировать проект | `terraform init` |
| Обновить провайдеры | `terraform init -upgrade` |
| Проверить формат/синтаксис | `terraform fmt -recursive`, `terraform validate` |
| Посмотреть изменения | `terraform plan` |
| Сохранить план | `terraform plan -out=tfplan` |
| Применить | `terraform apply` / `terraform apply tfplan` |
| Удалить всё | `terraform destroy` |
| Показать состояние | `terraform show` |
| Значение output | `terraform output -raw name` |
| Пересоздать ресурс | `terraform apply -replace=ADDR` |
| Проверить выражение | `terraform console` |
| Зафиксировать версию TF | `required_version = ">= 1.6.0"` |
| Зафиксировать провайдер | `version = "~> 3.0"` |
| Защитить от удаления | `lifecycle { prevent_destroy = true }` |
| Игнорировать поле | `lifecycle { ignore_changes = [...] }` |
| Явная зависимость | `depends_on = [...]` |
| Второй регион/аккаунт | `provider` с `alias` |
| Теги на все ресурсы AWS | `provider "aws" { default_tags { tags = {...} } }` |
| Yandex регион Казахстан | `endpoint = "api.yandexcloud.kz:443"`, `zone = "kz1-a"` |
| Кто я в AWS / Yandex | `aws sts get-caller-identity` / `yc config list` |

---

## 🧠 Что запомнить

1. Рабочий цикл: `init` → `fmt`/`validate` → `plan` → `apply`, при необходимости `destroy`.
2. Ресурс адресуется как `тип.имя`; ссылки между ресурсами создают граф зависимостей.
3. ⭐ План читают целиком: `+` создать, `~` изменить, `-/+` пересоздать, `-` удалить.
4. `forces replacement` означает пересоздание — на данных это потеря.
5. Версии Terraform и провайдеров фиксируют, `.terraform.lock.hcl` коммитят.
6. Секреты передают через переменные окружения и хранилища, а не в `.tf`.
7. `lifecycle` защищает критичные ресурсы (`prevent_destroy`) и гасит шум
   (`ignore_changes`).
8. `depends_on` нужен только там, где зависимость не видна из ссылок.
9. `-target` — инструмент отладки, а не повседневной работы.
10. `apply` на проде запускают из CI после ревью плана, а не с ноутбука.
11. Цикл и HCL одинаковы для AWS и Yandex Cloud — отличаются провайдер, типы ресурсов
    и способ входа; в CI у обоих — временные креды через федерацию (OIDC / WIF).

---

## Задачи

> Стенд: Terraform/OpenTofu + docker (для заданий без облака) и/или облачный аккаунт
> (AWS или Yandex Cloud — облачные задания даны в обоих вариантах, C7 и C11).

---

### Блок A. Теория

**A1.** Что делает `terraform init`?

<details><summary>Ответ</summary>

Скачивает провайдеры и модули, инициализирует backend, создаёт каталог
`.terraform/` и файл блокировки версий `.terraform.lock.hcl`.

</details>

**A2.** Что именно сравнивает `terraform plan` (три источника)?

<details><summary>Ответ</summary>

Код (.tf), стейт (что Terraform считает созданным) и реальность
(запрашивается у провайдера). Разница между ними и есть план.

</details>

**A3.** ⭐ Что означают символы `+`, `~`, `-/+`, `-` в плане?

<details><summary>Ответ</summary>

`+` — создать, `~` — изменить на месте, `-/+` — пересоздать (удалить и создать),
`-` — удалить; `<=` — чтение data source.

</details>

**A4.** Что такое `forces replacement` и почему это опасно?

<details><summary>Ответ</summary>

Изменение атрибута, который нельзя поменять на месте: ресурс будет удалён
и создан заново. Для дисков, баз и адресов это означает потерю данных или простой.

</details>

**A5.** Как адресуется ресурс в коде и в командах?

<details><summary>Ответ</summary>

`тип.имя` (например, `docker_container.web`); внутри модуля —
`module.network.subnet_id`; в командах адрес используется в `-target`, `-replace`,
`state` и `import`.

</details>

**A6.** Как Terraform понимает порядок создания ресурсов?

<details><summary>Ответ</summary>

По графу зависимостей, построенному из ссылок между ресурсами
(и явных `depends_on`). Независимые ресурсы создаются параллельно.

</details>

**A7.** Когда нужен `depends_on`?

<details><summary>Ответ</summary>

Когда зависимость реальна, но не выражена ссылкой: например, политика IAM
должна существовать до создания ресурса, который ею пользуется неявно.

</details>

**A8.** Что делают `prevent_destroy`, `ignore_changes`, `create_before_destroy`?

<details><summary>Ответ</summary>

`prevent_destroy` запрещает удаление ресурса; `ignore_changes` заставляет
игнорировать изменения указанных полей; `create_before_destroy` сначала создаёт замену,
потом удаляет старый ресурс (уменьшает простой).

</details>

**A9.** Зачем нужен `.terraform.lock.hcl` и коммитят ли его?

<details><summary>Ответ</summary>

Фиксирует версии и контрольные суммы провайдеров; коммитится в git,
чтобы у всех разработчиков и в CI были одинаковые версии.

</details>

**A10.** Как фиксируются версии Terraform и провайдеров? Что означает `~> 3.0`?

<details><summary>Ответ</summary>

`required_version` для Terraform и `version` в `required_providers`.
`~> 3.0` означает «>= 3.0.0 и < 4.0.0» (разрешены минорные обновления).

</details>

**A11.** Как правильно передавать креды провайдеру?

<details><summary>Ответ</summary>

Через переменные окружения (`YC_TOKEN`, `AWS_ACCESS_KEY_ID`, `TF_VAR_*`),
секреты CI/CD или хранилище секретов; никогда — в коде и в закоммиченных `.tfvars`.

</details>

**A12.** Зачем нужен `alias` у провайдера?

<details><summary>Ответ</summary>

Чтобы использовать несколько конфигураций одного провайдера — другой регион,
аккаунт или кластер; ресурсы явно выбирают нужный через `provider = aws.backup`.

</details>

**A13.** Чем `terraform apply tfplan` лучше `terraform apply` в CI?

<details><summary>Ответ</summary>

Применяется ровно тот план, который был построен и просмотрен: между plan
и apply никто не мог изменить код или состояние.

</details>

**A14.** Когда допустим `-target` и почему им не пользуются постоянно?

<details><summary>Ответ</summary>

Для отладки и аварийных ситуаций. Постоянное использование приводит к тому,
что стейт обновляется частично, а реальное состояние расходится с кодом.

</details>

**A15.** Что делает `terraform apply -replace=ADDR`?

<details><summary>Ответ</summary>

Помечает ресурс на пересоздание (замена `taint`): он будет удалён и создан
заново при следующем apply.

</details>

---

### Блок B. «Что сделает Terraform»

```hcl
B1.  resource "docker_container" "web" { name = "web", image = docker_image.nginx.image_id }
     # ресурса ещё нет
B2.  # изменили description у существующего ресурса
B3.  # изменили тип диска с network-hdd на network-ssd
B4.  # удалили ресурс из кода
B5.  # ничего не меняли, запускаем apply второй раз
```

<details><summary>Ответ</summary>

**B1.** Создаст образ и контейнер (2 to add), сначала образ — из-за ссылки.
**B2.** Изменение на месте (`~`).
**B3.** Скорее всего, пересоздание диска (`-/+`, `forces replacement`) — опасно для данных.
**B4.** Удаление ресурса (`-`).
**B5.** Ничего: «No changes».

</details>

Оцени код:
```hcl
B6.   terraform { required_providers { docker = { source = "kreuzwerker/docker" } } }
B7.   provider "yandex" { token = "y0_AgAAAA..." }
B8.   resource "yandex_mdb_postgresql_cluster" "prod" { ... }   # без lifecycle
B9.   lifecycle { prevent_destroy = true }                       # на прод-базе
B10.  lifecycle { ignore_changes = all }
B11.  terraform apply -auto-approve                              # в скрипте на ноутбуке
B12.  terraform apply -target=module.network -auto-approve       # регулярно, в рутине
B13.  output "db_password" { value = random_password.db.result }  # без sensitive
B14.  .gitignore: пусто
```

<details><summary>Ответ</summary>

**B6.** Не указана версия провайдера — непредсказуемые обновления.
**B7.** Токен в коде — утечка; должен приходить из переменной окружения.
**B8.** Прод-кластер без `prevent_destroy` — одна ошибка в плане может его удалить.
**B9.** Правильная защита.
**B10.** `ignore_changes = all` фактически отключает управление ресурсом — почти всегда
неверно.
**B11.** Автоприменение без ревью с локальной машины — прямой риск для прода.
**B12.** Регулярный `-target` разрушает целостность подхода; допустим только как отладка.
**B13.** Пароль попадёт в вывод и логи CI — нужен `sensitive = true` (и лучше хранить
в Vault).
**B14.** Без `.gitignore` в репозиторий уедут стейт и `.terraform/`.

</details>

---

### Блок C. Практика

#### C1. 🔑 Полный цикл на docker-провайдере
1. Напиши конфигурацию: образ nginx + контейнер с портом.
2. `init`, `fmt`, `validate`, `plan`, `apply`.
3. Проверь `curl localhost:8088`, посмотри `terraform show` и `output`.
4. `destroy`.

#### C2. Чтение плана
1. Измени внешний порт контейнера → `plan`: изменение или пересоздание?
2. Измени тег образа → `plan`: что произойдёт с контейнером?
3. Добавь новый контейнер → `plan`: сколько ресурсов будет создано?
4. Запиши вывод `Plan: X to add, Y to change, Z to destroy` для каждого случая.

<details><summary>Ответ</summary>

Смена внешнего порта и тега образа обычно приводит к пересозданию контейнера
(`-/+`), потому что эти поля неизменяемы.

</details>

#### C3. Зависимости
1. Добавь `docker_network` и подключи к нему контейнеры.
2. Посмотри порядок создания в выводе apply.
3. Попробуй `terraform graph` (или проанализируй ссылки) и нарисуй граф на бумаге.

#### C4. `lifecycle`
1. Поставь `prevent_destroy = true` на контейнер, попробуй `destroy` — что произойдёт?
2. Убери защиту, добавь `ignore_changes` на одно поле, измени его вне Terraform
   и посмотри план.
3. Попробуй `create_before_destroy` и объясни, когда это нужно.

<details><summary>Ответ</summary>

При `prevent_destroy` команда `destroy` завершится ошибкой с указанием ресурса —
именно так это и должно работать.

</details>

#### C5. Версии и lock-файл
1. Посмотри `.terraform.lock.hcl`.
2. Измени ограничение версии провайдера, выполни `init -upgrade`, сравни lock-файл.
3. Объясни, зачем его коммитить.

<details><summary>Ответ</summary>

После `init -upgrade` в lock-файле меняются версии и хеши; без коммита
lock-файла коллеги получат другие версии.

</details>

#### C6. Провайдер с alias
Создай два контейнера «в разных окружениях» через два `provider` с alias
(или два региона, если работаешь с облаком).

#### C7. 🔑 Облачная лаба
Создай сеть, подсеть и ВМ, выведи публичный IP в `output`, зайди по SSH.
Затем `destroy` и убедись, что ресурсов не осталось.

#### C8. `terraform console`
Проверь в консоли выражения: `join`, `merge`, `length`, `cidrsubnet`, тернарный оператор.
Запиши три полезных для себя.

#### C9. План в файл
Сделай `plan -out=tfplan`, посмотри `terraform show tfplan`, примени сохранённый план.
Объясни, зачем так делают в CI.

<details><summary>Ответ</summary>

В CI план строят на одном шаге, а применяют на другом — сохранённый файл плана
гарантирует, что применяется именно проверенное изменение.

</details>

#### C10. Защита от беды
Составь список ресурсов своего проекта, для которых обязательно нужен `prevent_destroy`,
и добавь его в код.

#### C11. 🔑 AWS-вариант облачной лабы (C7)
1. Войди через SSO (`aws sso login --profile dev`), проверь `aws sts get-caller-identity`.
2. Опиши провайдер `aws` с `region` и `default_tags`, ВМ `aws_instance` в дефолтной VPC,
   AMI — через `data "aws_ssm_parameter"`, SG с SSH только со своего `/32` (конспект, §7.1).
3. `plan` → найди в выводе, какие атрибуты `(known after apply)`; `apply`, зайди по SSH.
4. Сравни с Yandex-вариантом (C7): какие ресурсы соответствуют друг другу, что есть
   только в одном облаке? `destroy` и проверка консоли EC2 (регион!).

<details><summary>Ответ</summary>

Соответствие: `aws_instance` ↔ `yandex_compute_instance`, `aws_security_group` +
`aws_vpc_security_group_*_rule` ↔ `yandex_vpc_security_group` с блоками, `aws_key_pair` ↔
`metadata.ssh-keys`, `public_ip` ↔ `nat_ip_address`. `(known after apply)` — id, IP, ARN.
Только в AWS в этом примере — IMDSv2 и `default_tags`; частая ошибка — искать ВМ
в консоли не того региона.

</details>

#### C12. Один код — два провайдера
1. В одном `versions.tf` объяви `aws` и `yandex` (с фиксированными версиями).
2. Создай бакет в AWS (`aws_s3_bucket`) и бакет в Yandex Object Storage региона `kz1`
   (провайдер с `endpoint`/`storage_endpoint` для Казахстана).
3. Выведи оба имени в `output`, посмотри `terraform providers` и `.terraform.lock.hcl`.
4. Ответь: почему в проде так обычно не делают, а разносят облака по разным стейтам?

<details><summary>Ответ</summary>

Lock-файл фиксирует оба провайдера. В проде облака разносят по стейтам и пайплайнам:
разные креды и права, сбой API одного облака не блокирует `plan` другого, меньше радиус
поражения; связь между ними — через outputs и `terraform_remote_state` (тема 03).

</details>

---

### Блок D. Инциденты

**D1.** `terraform plan` показывает пересоздание ВМ, хотя менялось только описание. Почему?

<details><summary>Ответ</summary>

Изменённое поле неизменяемо для этого провайдера (Yandex: зона, платформа,
образ; AWS: `ami`, `availability_zone`, `subnet_id`, `user_data` при
`user_data_replace_on_change`) — оно помечено как `forces replacement`. Частый случай —
AMI из `data`, который «сам» обновился.

</details>

**D2.** `apply` завершился с ошибкой на середине. В каком состоянии инфраструктура?
Что делать?

<details><summary>Ответ</summary>

Часть ресурсов создана и записана в стейт, часть — нет. Нужно исправить причину
ошибки и повторить `apply`: Terraform доведёт состояние до целевого. Если ресурс создан,
но не попал в стейт — возможен `import` или ручная очистка.

</details>

**D3.** После `apply` пропал публичный IP, приложение недоступно. Как это могло произойти?

<details><summary>Ответ</summary>

Ресурс с IP был пересоздан (смена типа адреса, изменение поля, вызывающего
replacement) или удалён из кода; в плане это было видно как `-/+` или `-`.

</details>

**D4.** Коллега применил старую версию кода и «откатил» изменения. Как предотвратить?

<details><summary>Ответ</summary>

Стейт в удалённом backend с блокировкой, запрет локального apply, применение
только из CI с актуальной веткой, обязательный `plan` в MR.

</details>

**D5.** В плане `Plan: 0 to add, 0 to change, 0 to destroy`, но в консоли облака ресурса нет.
Что происходит?

<details><summary>Ответ</summary>

Стейт «думает», что ресурс существует, а фактически его нет (удалили руками).
Terraform обнаружит это при обновлении состояния во время plan — если не обнаружил,
проверь, тот ли стейт/окружение используется.

</details>

**D6.** Провайдер обновился, и план показывает изменения во всех ресурсах. Что делать?

<details><summary>Ответ</summary>

Прочитать changelog провайдера, проверить план на непроизводственном окружении,
при необходимости зафиксировать старую версию и планировать обновление отдельно.

</details>

**D7.** `terraform apply` падает с ошибкой авторизации. Что проверить?

<details><summary>Ответ</summary>

Наличие и срок действия кредов (переменные окружения, профиль), права
сервисного аккаунта или роли, правильность региона и контекста: в AWS — `AWS_PROFILE`,
истёкшая SSO-сессия, аккаунт (`aws sts get-caller-identity`); в Yandex — `YC_TOKEN`
(IAM-токен живёт до 12 ч), `cloud_id`/`folder_id`, для `kz1` — `endpoint` Казахстана;
системное время, сеть.

</details>

**D8.** Нужно срочно изменить один ресурс, а plan показывает 30 изменений от чужих правок.
Как поступить?

<details><summary>Ответ</summary>

Не применять чужие изменения вслепую: выяснить их происхождение, при
необходимости согласовать; `-target` использовать только как временную меру
с последующим приведением состояния в порядок.

</details>

**D9.** Кто-то выполнил `destroy` на стейдже, и там потерялись данные. Как защититься?

<details><summary>Ответ</summary>

`prevent_destroy` на критичных ресурсах, отдельные стейты и права для окружений,
запрет `destroy` в CI, бэкапы данных, ревью планов.

</details>

**D10.** В MR видно только изменение кода, план никто не смотрел. Как выстроить процесс?

<details><summary>Ответ</summary>

Публиковать вывод `plan` в MR автоматически (комментарий бота/artifact),
делать ревью обязательным, применять только после одобрения и только из CI.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Опиши рабочий цикл Terraform.

<details><summary>Ответ</summary>

Написать код → `init` → `fmt`/`validate` → `plan` → ревью → `apply` (→ `destroy`
для временных окружений).

</details>

**2.** Что делает `terraform init`?

<details><summary>Ответ</summary>

Скачивает провайдеры и модули, настраивает backend, создаёт lock-файл.

</details>

**3.** Что показывает `terraform plan`?

<details><summary>Ответ</summary>

Разницу между кодом, стейтом и реальностью: что будет создано, изменено, пересоздано
и удалено.

</details>

**4.** Как понять, что ресурс будет пересоздан?

<details><summary>Ответ</summary>

По строке `-/+` и пометке `# forces replacement` у конкретного атрибута.

</details>

**5.** Как Terraform определяет порядок создания ресурсов?

<details><summary>Ответ</summary>

По графу зависимостей из ссылок между ресурсами и `depends_on`.

</details>

**6.** Зачем нужен `depends_on`?

<details><summary>Ответ</summary>

Для зависимостей, не выраженных ссылками.

</details>

**7.** Что такое `lifecycle` и какие у него опции?

<details><summary>Ответ</summary>

Блок управления жизненным циклом: `prevent_destroy`, `ignore_changes`,
`create_before_destroy`, `replace_triggered_by`.

</details>

**8.** Как фиксируются версии провайдеров?

<details><summary>Ответ</summary>

`required_version`, `version` в `required_providers` и коммит `.terraform.lock.hcl`.

</details>

**9.** Как передаются креды в провайдер?

<details><summary>Ответ</summary>

Переменными окружения, секретами CI, хранилищами секретов — не в коде.

</details>

**10.** Как защитить критичные ресурсы от удаления?

<details><summary>Ответ</summary>

`lifecycle { prevent_destroy = true }`, отдельные стейты и права, ревью планов,
бэкапы.

</details>

---

### 🎯 Чек-лист

- [ ] Прошёл полный цикл `init/fmt/validate/plan/apply/destroy`
- [ ] ⭐ Читаю план и понимаю каждый символ изменения
- [ ] Отличаю изменение на месте от пересоздания
- [ ] Понимаю, как строится граф зависимостей
- [ ] Использую `lifecycle` для защиты критичных ресурсов
- [ ] Фиксирую версии и коммичу lock-файл
- [ ] Передаю креды через переменные окружения
- [ ] Пробовал `provider` с alias
- [ ] Пользуюсь `terraform console` и `terraform show`
- [ ] Знаю, зачем `plan -out` и `apply tfplan` в CI
- [ ] Поднял ВМ + SG в AWS и в Yandex Cloud и сопоставил ресурсы двух провайдеров
