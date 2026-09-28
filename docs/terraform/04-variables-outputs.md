---
title: "04. Переменные, выражения и зависимости"
description: "variable/locals/data/output, count vs for_each, dynamic-блоки, templatefile и параметризация под AWS и Yandex Cloud"
---

# 04. Переменные, выражения и зависимости

> Роадмап → Terraform. Это «рабочий инструментарий»: без переменных, `for_each`
> и `data` код превращается в копипасту.
>
> **После темы ты умеешь:** параметризовать конфигурацию, создавать группы ресурсов,
> читать существующие объекты через `data` и отдавать значения через `output`.

---

## 🗺️ Из чего состоит конфигурация

```text:no-line-numbers
 variable  ──► входные параметры (что можно менять снаружи)
 locals    ──► вычисленные значения внутри модуля (DRY)
 data      ──► чтение существующих объектов (образы, зоны, чужие ресурсы)
 resource  ──► создаваемые объекты
 output    ──► что отдаём наружу (другим стейтам, людям, CI)
```

---

## 1. `variable` — входные параметры

```hcl
variable "env" {
  description = "Окружение: prod, stage, dev"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["prod", "stage", "dev"], var.env)
    error_message = "env должен быть prod, stage или dev."
  }
}

variable "instance_count" {
  type    = number
  default = 2
}

variable "enable_backup" {
  type    = bool
  default = true
}

variable "subnets" {
  type = list(string)
  default = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "tags" {
  type = map(string)
  default = { managed-by = "terraform" }
}

# структурированный тип — самый удобный для наборов ресурсов ⭐
variable "servers" {
  type = map(object({
    cores  = number
    memory = number
    zone   = string
  }))
  default = {
    web = { cores = 2, memory = 2, zone = "ru-central1-a" }
    db  = { cores = 4, memory = 8, zone = "ru-central1-b" }
  }
}

variable "db_password" {
  type      = string
  sensitive = true        # ⭐ не показывать в выводе plan/apply
  # без default → Terraform спросит или возьмёт из TF_VAR_db_password
}
```

Откуда берутся значения (по возрастанию приоритета):
```text:no-line-numbers
1. default в блоке variable
2. файл terraform.tfvars / *.auto.tfvars
3. переменные окружения TF_VAR_имя
4. -var-file=prod.tfvars
5. -var="env=prod"                       ← побеждает
```
```bash
terraform apply -var-file=environments/prod.tfvars
export TF_VAR_db_password='...'          # ⭐ секреты — так, а не в файле
```

---

## 2. `locals` — вычисленные значения

```hcl
locals {
  name_prefix = "${var.project}-${var.env}"

  common_tags = merge(var.tags, {
    env        = var.env
    managed_by = "terraform"
  })

  is_prod = var.env == "prod"
  # количество зависит от окружения
  instance_count = local.is_prod ? 3 : 1
}

resource "yandex_compute_instance" "web" {
  name   = "${local.name_prefix}-web"
  labels = local.common_tags
}
```
`locals` — это не переменные пользователя, а «вычисленные константы» внутри модуля:
их нельзя передать снаружи, и это правильно.

---

## 3. `data` — читать, а не создавать

```hcl
# актуальный образ ОС
data "yandex_compute_image" "ubuntu" {
  family = "ubuntu-2404-lts"
}

# уже существующая сеть (созданная другой командой)
data "yandex_vpc_network" "shared" {
  name = "shared-net"
}

# данные из другого стейта (для Yandex Object Storage добавь endpoints и skip_* — тема 03, §7)
data "terraform_remote_state" "network" {
  backend = "s3"
  config  = { bucket = "tfstate", key = "prod/network/terraform.tfstate", region = "ru-central1" }
}

# локальные данные и шаблоны
data "local_file" "ssh_key" { filename = "~/.ssh/id_ed25519.pub" }
```

⭐ Разница, которую спрашивают: `resource` — Terraform **создаёт и владеет** объектом,
`data` — только **читает** существующий и никогда его не меняет.

---

## 4. `count` и `for_each` ⭐

```hcl
# count — простое размножение по числу
resource "yandex_compute_instance" "web" {
  count = 3
  name  = "web-${count.index}"          # web-0, web-1, web-2
}
# адреса: yandex_compute_instance.web[0], [1], [2]

# for_each по множеству
resource "yandex_vpc_subnet" "this" {
  for_each       = toset(["ru-central1-a", "ru-central1-b"])
  name           = "subnet-${each.key}"
  zone           = each.key
}
# адреса: yandex_vpc_subnet.this["ru-central1-a"]

# for_each по map объектов — самый гибкий вариант
resource "yandex_compute_instance" "srv" {
  for_each    = var.servers
  name        = "${local.name_prefix}-${each.key}"
  zone        = each.value.zone
  resources {
    cores  = each.value.cores
    memory = each.value.memory
  }
}
```

```text:no-line-numbers
⚠️ ГЛАВНАЯ РАЗНИЦА:
 count адресует по ИНДЕКСУ  → удалил элемент из середины списка →
                              все последующие ресурсы ПЕРЕСОЗДАЮТСЯ
 for_each адресует по КЛЮЧУ → удалил элемент → удалится ровно он

⭐ Правило: count — только для «N одинаковых» и для условного создания;
   во всех остальных случаях — for_each.
```

Условное создание ресурса:
```hcl
resource "yandex_compute_instance" "bastion" {
  count = var.create_bastion ? 1 : 0
  # ...
}
# ссылка: yandex_compute_instance.bastion[0].id  (осторожно, когда count = 0)
```

---

## 5. `output` — отдать значения наружу

```hcl
output "web_ips" {
  description = "Публичные адреса веб-серверов"
  value       = [for i in yandex_compute_instance.web : i.network_interface[0].nat_ip_address]
}

output "subnet_ids" {
  value = { for k, s in yandex_vpc_subnet.this : k => s.id }
}

output "db_password" {
  value     = random_password.db.result
  sensitive = true          # ⭐ не печатать в логах
}
```
```bash
terraform output                 # все значения
terraform output -raw web_ips    # для скриптов
terraform output -json           # для передачи в Ansible/CI
```

Типовая связка с Ansible:
```bash
terraform output -json | jq -r '.web_ips.value[]' > ansible/inventory_hosts
```

---

## 6. Выражения, циклы и функции

```hcl
# for-выражения
locals {
  names     = [for s in var.servers_list : upper(s.name)]
  by_zone   = { for k, v in var.servers : k => v.zone }
  prod_only = { for k, v in var.servers : k => v if v.env == "prod" }
}

# динамические вложенные блоки
resource "yandex_vpc_security_group" "app" {
  dynamic "ingress" {
    for_each = var.allowed_ports
    content {
      protocol       = "TCP"
      port           = ingress.value
      v4_cidr_blocks = ["10.0.0.0/16"]
    }
  }
}

# шаблоны файлов
user_data = templatefile("${path.module}/cloud-init.tpl", {
  hostname = local.name_prefix
  ssh_key  = var.ssh_public_key
})

# безопасные выражения
value = try(var.optional_setting, "default")
ok    = can(regex("^10\\.", var.cidr))
```

Часто используемые функции:
```text:no-line-numbers
merge, lookup, coalesce, compact, distinct, flatten, concat, zipmap
cidrsubnet("10.0.0.0/16", 8, 1) → "10.0.1.0/24"     ⭐ для сетей
format("%s-%02d", "web", 3) → "web-03"
jsonencode / yamlencode / base64encode
file / templatefile / fileexists
```

---

## 7. AWS / Yandex Cloud: одни переменные — разные ресурсы

Приём: **входы описывают намерение** («маленький сервер в зоне a»), а `locals` переводят его
в термины конкретного облака. Тогда `tfvars` окружений почти одинаковы для обоих облаков.
Код проверен `terraform validate` (aws 6.66.0, yandex 0.230.0).

```hcl
variable "servers" {
  type = map(object({
    size = string              # small | large — не "t3.small" и не "cores = 2"
    zone = string
  }))
  validation {
    condition     = alltrue([for s in values(var.servers) : contains(["small", "large"], s.size)])
    error_message = "size: small или large."
  }
}

locals {
  sizes = {
    aws    = { small = "t3.small", large = "m7i.large" }
    yandex = { small = { cores = 2, memory = 2 }, large = { cores = 4, memory = 16 } }
  }
}
```

**AWS:**
```hcl
data "aws_ssm_parameter" "ubuntu" {                   # образ — аналог yandex_compute_image
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}
data "aws_availability_zones" "available" { state = "available" }   # зоны без хардкода

resource "aws_instance" "srv" {
  for_each          = var.servers
  ami               = data.aws_ssm_parameter.ubuntu.value
  instance_type     = local.sizes.aws[each.value.size]
  availability_zone = each.value.zone                  # "eu-central-1a"
  tags              = { Name = "lab-${each.key}", role = each.key }
}

# правила SG: в AWS вместо dynamic — отдельный ресурс на правило через for_each
resource "aws_vpc_security_group_ingress_rule" "app" {
  for_each          = var.allowed_ports                # set(number): [80, 443]
  security_group_id = aws_security_group.app.id
  ip_protocol       = "tcp"
  from_port         = each.value
  to_port           = each.value
  cidr_ipv4         = "10.0.0.0/16"
}

output "servers" {
  value = { for k, i in aws_instance.srv : k => { id = i.id, private_ip = i.private_ip, public_ip = i.public_ip } }
}
```

**Yandex Cloud:**
```hcl
resource "yandex_compute_instance" "srv" {
  for_each    = var.servers
  name        = "lab-${each.key}"
  zone        = each.value.zone                        # "ru-central1-a" или "kz1-a"
  platform_id = "standard-v3"
  labels      = { role = each.key }
  resources {
    cores  = local.sizes.yandex[each.value.size].cores
    memory = local.sizes.yandex[each.value.size].memory
  }
  boot_disk {
    initialize_params { image_id = data.yandex_compute_image.ubuntu.id }
  }
  network_interface {
    subnet_id = yandex_vpc_subnet.this[each.value.zone].id
    nat       = true
  }
}

output "servers" {                                     # ⭐ та же форма, что у AWS
  value = { for k, i in yandex_compute_instance.srv : k => {
    id         = i.id
    private_ip = i.network_interface[0].ip_address
    public_ip  = i.network_interface[0].nat_ip_address
  } }
}
```

| Что | AWS | Yandex Cloud |
|-----|-----|--------------|
| Размер ВМ | один атрибут `instance_type` | `platform_id` + `resources { cores, memory, core_fraction }` |
| Зоны | `eu-central-1a/b/c` (`data "aws_availability_zones"`) | `ru-central1-a/b/d/e`; в `kz1` — только `kz1-a` |
| Правила SG | ресурс на правило (`for_each`) | `dynamic "ingress"` внутри группы (§6) |
| Метки | `tags` + `default_tags` провайдера; ключи с `:` и `/` можно | `labels`: ключи строчными, ограниченный набор символов |
| Публичный IP в output | `public_ip` | `network_interface[0].nat_ip_address` |
| Образ | SSM-параметр Canonical / `data "aws_ami"` с `most_recent` | `data "yandex_compute_image"` по `family` |

⭐ Одинаковая **форма outputs** (`servers = { name => {id, private_ip, public_ip} }`) важнее
одинаковых ресурсов: Ansible-инвентарь, соседний стейт и CI читают outputs и не должны знать,
какое облако внизу. Валидация зоны для `kz1`:
`condition = alltrue([for s in values(var.servers) : s.zone == "kz1-a"])`.

---

## 8. Грабли

| Грабля | Последствие | Решение |
|--------|-------------|---------|
| `count` для именованных сущностей | Пересоздание «соседей» при удалении одного | `for_each` |
| Секреты в `terraform.tfvars` в git | Утечка | `TF_VAR_*`, Vault, секреты CI |
| `output` без `sensitive` | Пароли в логах CI | `sensitive = true` |
| Переменные без `type` и `description` | Непонятный модуль, ошибки типов | Всегда описывать |
| Нет `validation` | Опечатка в `env` доезжает до apply | Валидация значений |
| Хардкод зон, образов, CIDR | Копипаста между окружениями | Переменные и `data` |
| Огромные `locals` с логикой | Нечитаемо | Разбивать, выносить в модули |
| `data` на ресурс, который создаёт этот же код | Ошибка «не найдено» при первом apply | Ссылаться напрямую на ресурс |
| Ссылка на `resource[0]` при `count = 0` | Ошибка плана | `try()` или `one()` |
| Облачные термины во входах (`instance_type`, `cores`) | Переезд/второе облако = переписать все `tfvars` | Входы — намерение (`size`), перевод — в `locals` |
| Теги AWS «как есть» в `labels` Yandex | Ошибка API: заглавные буквы, `:` в ключах | Нормализовать ключи (`lower`, `replace`) в `locals` |
| AMI из `data` с `most_recent` без контроля | Новый образ → план пересоздаёт все ВМ | Фиксировать `ami` в переменной или `ignore_changes = [ami]` |

---

## 💼 Как это в DevOps

- Переменные — то, чем окружения отличаются друг от друга: размер машин, число реплик,
  зоны, включённость бэкапов. Остальной код один и тот же.
- `for_each` по map объектов — стандартный способ описывать «наши серверы/подсети/базы»
  одной структурой, которую удобно ревьюить.
- `data` избавляет от хардкода: актуальный образ ОС, существующая сеть,
  outputs соседнего стейта.
- `output` — интерфейс инфраструктуры наружу: адреса для Ansible, идентификаторы
  для другого стейта, строки подключения для CI.
- Валидация переменных экономит время: ошибка ловится до создания ресурсов,
  а не в середине apply.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Параметр снаружи | `variable` с `type`, `description`, `default` |
| Секретная переменная | `sensitive = true` + `TF_VAR_*` |
| Проверить значение | блок `validation` |
| Вычисленное значение | `locals` |
| Прочитать существующее | `data "..." "..."` |
| N одинаковых ресурсов | `count = N`, `count.index` |
| Набор именованных ресурсов | `for_each` + `each.key` / `each.value` |
| Условный ресурс | `count = var.flag ? 1 : 0` |
| Повторяющиеся вложенные блоки | `dynamic "block" { for_each = ... }` |
| Отдать значение | `output` (+ `sensitive`) |
| Значения для скрипта | `terraform output -raw` / `-json` |
| Подставить шаблон | `templatefile(path, vars)` |
| Посчитать подсеть | `cidrsubnet("10.0.0.0/16", 8, 1)` |
| Безопасное значение | `try(...)`, `coalesce(...)` |
| Значения из файла | `-var-file=prod.tfvars` |
| Образ ОС: AWS / Yandex | `data "aws_ssm_parameter"` / `data "yandex_compute_image"` |
| Правила SG: AWS / Yandex | `for_each` по `aws_vpc_security_group_ingress_rule` / `dynamic "ingress"` |

---

## 🧠 Что запомнить

1. `variable` — вход, `locals` — вычисленные значения, `data` — чтение, `output` — выход.
2. Приоритет значений: default → tfvars → `TF_VAR_*` → `-var-file` → `-var`.
3. Секреты передают через переменные окружения и хранилища, помечают `sensitive`.
4. ⭐ `for_each` адресует по ключу и не пересоздаёт соседей; `count` — только для
   «N одинаковых» и условного создания.
5. `data` читает существующие объекты и никогда их не меняет.
6. `dynamic` избавляет от копипасты вложенных блоков (правила SG, диски).
7. `templatefile` — правильный способ подставлять значения в cloud-init и конфиги.
8. `validation` ловит ошибки до создания ресурсов.
9. `output -json` — стандартный мост к Ansible и CI.
10. Всё, чем отличаются окружения, выносят в переменные; код остаётся общим.
11. Для AWS и Yandex Cloud входы описывают намерение (`size`, `zone`), перевод в термины
    облака — в `locals`, а outputs одинаковой формы скрывают, какое облако внизу.

---

## Задачи

> Стенд: docker/local провайдеры (быстро и бесплатно) либо облако.

---

### Блок A. Теория

**A1.** Чем `variable` отличается от `locals`?

<details><summary>Ответ</summary>

`variable` — вход модуля, значение задаётся снаружи. `locals` — вычисленные
внутри значения, снаружи их задать нельзя.

</details>

**A2.** Каков приоритет источников значений переменных?

<details><summary>Ответ</summary>

default → `terraform.tfvars`/`*.auto.tfvars` → `TF_VAR_*` → `-var-file` →
`-var` (последнее побеждает).

</details>

**A3.** Как правильно передавать секретные значения?

<details><summary>Ответ</summary>

Через `TF_VAR_*`, секреты CI/CD или хранилище секретов; в коде и закоммиченных
`.tfvars` — нельзя.

</details>

**A4.** Что делает `sensitive = true` и чего он **не** делает?

<details><summary>Ответ</summary>

Скрывает значение в выводе `plan`/`apply`/`output`. Не шифрует и не скрывает
его в стейте — там значение остаётся открытым.

</details>

**A5.** Зачем нужен блок `validation`?

<details><summary>Ответ</summary>

Чтобы проверять значения на этапе плана (допустимое окружение, формат CIDR,
диапазон чисел) и не доводить ошибку до создания ресурсов.

</details>

**A6.** ⭐ Чем `data` отличается от `resource`?

<details><summary>Ответ</summary>

`resource` создаёт и управляет объектом (он попадает в стейт как управляемый),
`data` только читает существующий объект и никогда его не изменяет.

</details>

**A7.** Когда `data` может привести к ошибке при первом `apply`?

<details><summary>Ответ</summary>

Если `data` ищет объект, который создаётся в этом же конфиге: на момент плана
его ещё нет. Нужно ссылаться напрямую на ресурс.

</details>

**A8.** ⭐ В чём принципиальная разница между `count` и `for_each`?

<details><summary>Ответ</summary>

`count` адресует экземпляры по индексу, `for_each` — по ключу. При изменении
середины списка `count` пересоздаёт все последующие ресурсы, `for_each` затрагивает
только изменённый ключ.

</details>

**A9.** Что произойдёт при удалении среднего элемента списка при использовании `count`?

<details><summary>Ответ</summary>

Все элементы после удалённого сдвинутся по индексам, и Terraform пересоздаст их.

</details>

**A10.** Как сделать ресурс условным?

<details><summary>Ответ</summary>

`count = var.flag ? 1 : 0` (или `for_each = var.flag ? toset(["x"]) : toset([])`).

</details>

**A11.** Что такое `dynamic` и какую проблему он решает?

<details><summary>Ответ</summary>

Генерация повторяющихся вложенных блоков (правила SG, диски, порты)
по списку/множеству вместо копипасты.

</details>

**A12.** Зачем нужен `templatefile` и чем он лучше конкатенации строк?

<details><summary>Ответ</summary>

Подставляет переменные в файл-шаблон: удобно для cloud-init, конфигов, скриптов;
шаблон хранится отдельным читаемым файлом и его можно проверить.

</details>

**A13.** Как передать значения из Terraform в Ansible?

<details><summary>Ответ</summary>

Через `terraform output -json` и генерацию inventory (или динамический inventory,
читающий стейт/облако).

</details>

**A14.** Что делают `try()` и `coalesce()`?

<details><summary>Ответ</summary>

`try()` возвращает первое выражение, которое не дало ошибку;
`coalesce()` — первое не-null/не-пустое значение.

</details>

**A15.** Что делает `cidrsubnet("10.0.0.0/16", 8, 3)`?

<details><summary>Ответ</summary>

Возвращает `10.0.3.0/24` — подсеть с дополнительными 8 битами маски и индексом 3.

</details>

---

### Блок B. «Что не так / что получится»

```hcl
B1.  variable "env" {}                      # без type и description
B2.  variable "env" { type = string, validation { condition = contains(["prod","dev"], var.env) ... } }
B3.  variable "db_password" { default = "P@ssw0rd" }
B4.  output "db_password" { value = var.db_password }
B5.  resource "yandex_compute_instance" "web" { count = length(var.servers) ... }
     # servers — список имён, из середины удалили одно
B6.  resource "yandex_compute_instance" "web" { for_each = var.servers ... }
B7.  data "yandex_vpc_subnet" "this" { name = yandex_vpc_subnet.created.name }
B8.  locals { name = "${var.project}-${var.env}" }
B9.  resource "x" "y" { count = var.enabled ? 1 : 0 }  ... затем x.y.id
B10. dynamic "ingress" { for_each = var.ports, content { port = ingress.value } }
B11. user_data = "hostname: ${var.name}\nssh: ${var.key}"      # многострочный конфиг строкой
B12. terraform.tfvars с паролями закоммичен в git
```

<details><summary>Ответ</summary>

**B1.** Без типа и описания модуль непонятен и не защищён от ошибок типа.
**B2.** Правильная переменная с валидацией.
**B3.** Пароль по умолчанию в коде — утечка и небезопасное значение.
**B4.** Пароль попадёт в вывод и логи — нужен `sensitive = true` (и лучше не выводить вовсе).
**B5.** Пересоздание ресурсов после удалённого элемента — типичная ошибка `count`.
**B6.** Корректный вариант: изменения затронут только соответствующий ключ.
**B7.** `data`, ссылающийся на создаваемый в этом же коде ресурс, — ошибка;
надо использовать прямую ссылку.
**B8.** Нормальное использование `locals`.
**B9.** При `count` ссылка должна быть `x.y[0].id`; при `count = 0` нужна защита
(`try`, `one`).
**B10.** Корректный `dynamic`.
**B11.** Многострочный конфиг строкой — источник ошибок; нужен `templatefile`.
**B12.** Секреты в git — утечка.

</details>

---

### Блок C. Практика

#### C1. Переменные и валидация
1. Опиши переменные: `env` (с валидацией), `instance_count` (number),
   `tags` (map), `servers` (map объектов).
2. Передай значения тремя способами (`tfvars`, `TF_VAR_`, `-var`) и проверь приоритет.

#### C2. 🔑 `locals`
Сделай `name_prefix`, `common_tags` и условное значение (`is_prod`).
Примени их ко всем ресурсам и убедись, что имена и теги единообразны.

#### C3. `data`
1. Найди актуальный образ ОС (или существующую docker-сеть) через `data`.
2. Используй его в ресурсе.
3. Попробуй сослаться через `data` на ресурс, создаваемый в этом же коде, — получи ошибку
   и объясни её.

<details><summary>Ответ</summary>

Ошибка будет вида «не найдено» или циклическая зависимость — это ожидаемо.

</details>

#### C4. 🔑 `count` vs `for_each` — эксперимент
1. Создай три контейнера через `count` по списку имён.
2. Удали **средний** элемент списка и посмотри `plan`. Сколько ресурсов пересоздаётся?
3. Переделай на `for_each` (по map/set) и повтори эксперимент.
4. Запиши разницу — это любимый вопрос на собеседовании.

<details><summary>Ответ</summary>

С `count` план покажет пересоздание нескольких ресурсов; с `for_each` —
только удаление одного.

</details>

#### C5. Условное создание
Добавь переменную `create_bastion` и ресурс с `count = var.create_bastion ? 1 : 0`.
Проверь оба значения. Обработай ссылку на него через `try()`/`one()`.

<details><summary>Ответ</summary>

При `count = 0` обращение к `x.y[0]` даёт ошибку индекса; безопасные варианты —
`one(x.y[*].id)` или `try(x.y[0].id, null)`.

</details>

#### C6. `dynamic`
Опиши security group (или набор портов контейнера) через `dynamic` по списку портов.
Сравни с вариантом «руками».

#### C7. `templatefile`
Сделай `cloud-init.tpl` с подстановкой имени хоста и SSH-ключа. Проверь результат
(в облаке — на ВМ, локально — выведи через `output`).

#### C8. Outputs
1. Сделай `output` со списком адресов и map идентификаторов.
2. Получи их через `terraform output -json`.
3. Сгенерируй из них inventory для Ansible.

<details><summary>Ответ</summary>

`terraform output -json | jq` — стандартный способ построить inventory.

</details>

#### C9. Функции в консоли
В `terraform console` проверь: `merge`, `lookup`, `cidrsubnet`, `format`, `for`-выражение,
`try`. Запиши четыре, которые пригодятся тебе чаще всего.

#### C10. Рефакторинг
Возьми свой код из предыдущих лаб и убери из него все хардкоды: имена, зоны, размеры,
образы — вынеси в переменные и `locals`. Сравни объём diff при смене окружения до и после.

<details><summary>Ответ</summary>

После выноса в переменные смена окружения обычно сводится к другому `tfvars`.

</details>

#### C11. 🔑 AWS-вариант C1 + C4: `servers` по намерению
1. Опиши `servers = map(object({ size, zone }))` с валидацией `size` и `locals.sizes`
   (конспект, §7).
2. Создай `aws_instance` через `for_each`, AMI — через `data "aws_ssm_parameter"`.
3. Сделай output `servers = { name => {id, private_ip, public_ip} }`.
4. Удали один сервер из map и посмотри `plan`: сколько ресурсов затронуто?
5. Если есть доступ к Yandex Cloud — тот же `tfvars` (поменяй только зоны) на
   `yandex_compute_instance`; сравни outputs.

<details><summary>Ответ</summary>

С `for_each` по map удаление одного сервера даёт `1 to destroy`, соседей не трогает.
Для Yandex меняются только зоны (`ru-central1-*`/`kz1-a` вместо `eu-central-1*`); размеры
переводятся `locals.sizes`, форма outputs та же — потребители не замечают смены облака.

</details>

#### C12. AWS-вариант C6: правила SG без `dynamic`
1. Опиши `allowed_ports = set(number)` и правила через `for_each` по
   `aws_vpc_security_group_ingress_rule`.
2. Сравни с Yandex-вариантом через `dynamic "ingress"`: что будет в плане при удалении
   одного порта в каждом случае?
3. Добавь валидацию: порт 22 можно открывать только с CIDR из переменной `admin_cidrs`,
   а `0.0.0.0/0` в `admin_cidrs` запрещён.

<details><summary>Ответ</summary>

В AWS каждое правило — отдельный ресурс с ключом-портом: удаление порта = удаление
одного `aws_vpc_security_group_ingress_rule`. В Yandex правила — блоки одной группы:
план покажет `~` изменение `yandex_vpc_security_group` на месте. Валидация:
`condition = !contains(var.admin_cidrs, "0.0.0.0/0")`.

</details>

---

### Блок D. Инциденты

**D1.** После добавления одного сервера в список Terraform пересоздаёт три существующих.
Причина и решение.

<details><summary>Ответ</summary>

Используется `count` по списку: индексы сместились. Перейти на `for_each`
по множеству/map с устойчивыми ключами.

</details>

**D2.** В логах CI виден пароль от базы. Что настроить?

<details><summary>Ответ</summary>

Пометить переменные и outputs `sensitive`, не выводить секреты вовсе,
хранить их в секретах CI/Vault, маскировать переменные в настройках CI.

</details>

**D3.** `apply` падает: `Error: Invalid index` при `count = 0`. Что происходит?

<details><summary>Ответ</summary>

Обращение к элементу ресурса, которого нет (count = 0). Использовать
`one()`/`try()` или условные выражения.

</details>

**D4.** Коллега передал `-var="env=prod"`, но применились значения dev. Почему это
невозможно и что проверить?

<details><summary>Ответ</summary>

Такое невозможно при корректном вызове: `-var` имеет наивысший приоритет.
Проверить: тот ли каталог/workspace, не переопределяется ли значение в модуле,
не используется ли другой `-var-file`, не кэширован ли план.

</details>

**D5.** Образ ОС «уехал»: после обновления family Terraform хочет пересоздать все ВМ.
Что делать?

<details><summary>Ответ</summary>

Зафиксировать конкретный образ в переменной (Yandex — `image_id`, AWS — `ami`;
в AWS то же случается с `data "aws_ami"` при `most_recent = true` и SSM-параметром `current`)
или использовать `ignore_changes` на образе, и обновлять его осознанно, отдельным изменением
(в AWS для групп — через launch template и instance refresh).

</details>

**D6.** Один и тот же код даёт разные результаты у двух инженеров. Гипотезы?

<details><summary>Ответ</summary>

Разные значения переменных (`TF_VAR_*`, локальные `tfvars`), разные версии
Terraform/провайдеров (нет lock-файла), разные workspace/стейты.

</details>

**D7.** Опечатка в значении переменной привела к созданию ресурсов в неправильной зоне.
Как предотвратить?

<details><summary>Ответ</summary>

`validation` в переменных, единый источник значений в репозитории,
ревью `plan` в MR, ограничение допустимых зон списком.

</details>

**D8.** Нужно временно отключить создание группы ресурсов, не удаляя код. Как?

<details><summary>Ответ</summary>

Флаг в переменной и `count = var.enabled ? 1 : 0` (либо пустой `for_each`);
код остаётся, ресурсы не создаются.

</details>

**D9.** Ansible не видит новые серверы после `apply`. Как связать Terraform и inventory?

<details><summary>Ответ</summary>

Генерировать inventory из `terraform output -json` в CI или использовать
динамический inventory (плагин облака/`terraform_remote_state`).

</details>

**D10.** В модуле 40 переменных, никто не понимает, какие обязательны. Что сделать?

<details><summary>Ответ</summary>

Задать `default` для необязательных, описать `description` и типы, сгруппировать
переменные, вынести структуру в `object`, написать README модуля с примером вызова.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Чем `variable` отличается от `locals`?

<details><summary>Ответ</summary>

`variable` — вход снаружи; `locals` — внутренние вычисленные значения.

</details>

**2.** Как передать секрет в Terraform?

<details><summary>Ответ</summary>

Через `TF_VAR_*`, секреты CI или Vault; в коде — нельзя.

</details>

**3.** Что такое `data source`?

<details><summary>Ответ</summary>

Источник данных: читает существующие объекты (образы, сети, outputs другого стейта).

</details>

**4.** Чем `count` отличается от `for_each`?

<details><summary>Ответ</summary>

`count` — по индексу (уязвим к смещению), `for_each` — по ключу (устойчив).

</details>

**5.** Как сделать ресурс необязательным?

<details><summary>Ответ</summary>

`count = условие ? 1 : 0` или пустой `for_each`.

</details>

**6.** Что такое `dynamic` блок?

<details><summary>Ответ</summary>

Генератор повторяющихся вложенных блоков.

</details>

**7.** Как вывести значения и передать их дальше?

<details><summary>Ответ</summary>

`output`, затем `terraform output -json/-raw` для CI и Ansible.

</details>

**8.** Как связать Terraform и Ansible?

<details><summary>Ответ</summary>

Через outputs и генерацию inventory (или динамический inventory).

</details>

**9.** Что делает `templatefile`?

<details><summary>Ответ</summary>

Рендерит файл-шаблон с подстановкой переменных.

</details>

**10.** Как валидировать входные значения?

<details><summary>Ответ</summary>

Блоком `validation` в описании переменной.

</details>

---

### 🎯 Чек-лист

- [ ] Все параметры вынесены в `variable` с типами и описаниями
- [ ] Есть валидация ключевых переменных
- [ ] Секреты идут через `TF_VAR_*`/CI и помечены `sensitive`
- [ ] Использую `locals` для префиксов и общих тегов
- [ ] Читаю существующие объекты через `data`
- [ ] ⭐ Понимаю разницу `count` и `for_each` и проверял её экспериментом
- [ ] Умею делать условные ресурсы
- [ ] Применяю `dynamic` вместо копипасты блоков
- [ ] Использую `templatefile` для cloud-init и конфигов
- [ ] Отдаю значения через `output` и связываю с Ansible/CI
- [ ] Описываю входы намерением (`size`, `zone`) и перевожу их в ресурсы AWS / Yandex в `locals`
