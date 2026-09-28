---
title: "03. Стейт и backend"
description: "Зачем нужен стейт, удалённый backend с блокировкой (S3/use_lockfile), импорт ресурсов, разделение стейтов"
---

# 03. Стейт и backend ⭐

> Роадмап → Terraform → *«Понимать концепции: Стейт, Backend»*.
>
> **После темы ты умеешь:** объяснить, зачем нужен стейт, настроить удалённый backend
> с блокировкой, импортировать существующие ресурсы и безопасно чинить состояние.

---

## 🗺️ Зачем вообще нужен стейт

```text:no-line-numbers
 Terraform должен ответить на вопрос:
 «Ресурс vm-web в коде — это тот самый инстанс fhm3k2..., который я создал вчера?»

                КОД                  СТЕЙТ                  РЕАЛЬНОСТЬ
      resource "vm" "web" {}  ←──►  vm.web = fhm3k2...  ←──►  инстанс fhm3k2...
                                      │
                            без стейта этой связи НЕТ:
                            Terraform не знает, что уже создано,
                            и попытается создать всё заново
```

| Что хранит стейт | Зачем |
|------------------|-------|
| Соответствие «адрес в коде → идентификатор в провайдере» | Главное назначение |
| Атрибуты ресурсов (IP, id, параметры) | Чтобы считать разницу и подставлять значения |
| Зависимости между ресурсами | Порядок создания и удаления |
| Версия Terraform и провайдеров | Совместимость |
| Метаданные (serial, lineage) | Контроль версий и блокировок |

⚠️ **Стейт содержит секреты в открытом виде**: пароли `random_password`, ключи,
креды managed-баз. Отсюда правила: не в git, шифровать в хранилище, ограничивать доступ.

---

## 1. Локальный стейт и почему его недостаточно

```text:no-line-numbers
terraform.tfstate          текущее состояние (JSON)
terraform.tfstate.backup   предыдущая версия
```

| Проблема локального стейта | Последствие |
|----------------------------|-------------|
| Лежит на одном ноутбуке | Коллеги не могут работать |
| Нет блокировки | Два `apply` одновременно портят состояние |
| Легко потерять/закоммитить | Потеря управления инфраструктурой или утечка секретов |
| Нет истории версий | Нельзя откатиться к прошлому состоянию |

⭐ Вывод: локальный стейт — только для одиночных экспериментов.
Всё командное — **удалённый backend**.

---

## 2. Удалённый backend

```hcl
# backend в объектном хранилище, совместимом с S3 (пример для Yandex Cloud)
terraform {
  backend "s3" {
    endpoints = { s3 = "https://storage.yandexcloud.net" }
    bucket    = "tfstate-mycompany"
    key       = "prod/network/terraform.tfstate"   # ⭐ путь = имя окружения/компонента
    region    = "ru-central1"

    skip_region_validation      = true
    skip_credentials_validation = true
    skip_requesting_account_id  = true
    skip_s3_checksum            = true

    # блокировка: в S3-совместимых хранилищах — через DynamoDB-подобный сервис
    # или (Terraform 1.10+/OpenTofu) через lockfile в самом бакете
    use_lockfile = true
  }
}
```

### 2.1 AWS / Yandex Cloud: backend рядом

> Проверь, сентябрь 2026: Terraform 1.16, OpenTofu 1.12. `use_lockfile` — Terraform 1.10+
> (OpenTofu 1.10+); блокировка через DynamoDB в S3 backend **deprecated с Terraform 1.11**
> и будет удалена в одной из будущих минорных версий.

**AWS: S3 + нативная блокировка** (стандарт для новых проектов):
```hcl
terraform {
  backend "s3" {
    bucket       = "tfstate-mycompany-111122223333"   # имя бакета глобально уникально
    key          = "prod/network/terraform.tfstate"
    region       = "eu-central-1"
    encrypt      = true                               # SSE (по умолчанию SSE-S3; KMS — kms_key_id)
    use_lockfile = true                               # ⭐ рядом со стейтом появится key.tflock
  }
}
```
Как это работает: Terraform кладёт `prod/network/terraform.tfstate.tflock` **условной
записью** (`If-None-Match`): если файл уже есть — блокировка занята. Роли нужны
`s3:GetObject`/`PutObject`/`DeleteObject` на `*.tflock` (плюс обычные права на сам стейт).

**AWS: было — DynamoDB (deprecated), переход без простоя:**
```hcl
terraform {
  backend "s3" {
    bucket         = "tfstate-mycompany-111122223333"
    key            = "prod/network/terraform.tfstate"
    region         = "eu-central-1"
    encrypt        = true
    dynamodb_table = "terraform-locks"   # ⚠️ устаревшее: предупреждение при init
    use_lockfile   = true                # шаг 1: включаем ОБА механизма, раскатываем на всех
  }
}
# шаг 2: когда все пайплайны и люди на Terraform 1.10+ — убираем dynamodb_table,
#        terraform init -reconfigure; таблицу удаляем отдельным изменением
```

**Yandex Cloud** — пример в начале раздела (регион Россия). Регион Казахстан `kz1`:
```hcl
terraform {
  backend "s3" {
    endpoints = { s3 = "https://storage.yandexcloud.kz" }   # ⭐ бакеты kz1 не видны через .net
    bucket    = "tfstate-mycompany-kz"
    key       = "prod/network/terraform.tfstate"
    region    = "kz1"                        # регион подписи — проверь в документации
    skip_region_validation      = true
    skip_credentials_validation = true
    skip_requesting_account_id  = true
    skip_s3_checksum            = true
    use_lockfile                = true
  }
}
```
- Ключи — **статический ключ сервисного аккаунта** (`yc iam access-key create`) в
  `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`: backend говорит на S3 API, `YC_TOKEN` он не читает.
- `use_lockfile` опирается на условную запись; Object Storage поддерживает `If-None-Match`
  (документация Yandex, проверь, сентябрь 2026). Официальный туториал Yandex всё ещё показывает
  блокировку через **YDB Document API** (`endpoints.dynamodb` + `dynamodb_table`) — это тот же
  deprecated-механизм DynamoDB, для новых проектов бери `use_lockfile`.

| | AWS S3 | Yandex Object Storage |
|---|--------|-----------------------|
| Endpoint | по умолчанию | `storage.yandexcloud.net` / `storage.yandexcloud.kz` |
| `skip_*` флаги | не нужны | нужны: backend не должен ходить в STS/IAM AWS |
| Креды backend | те же, что у провайдера (профиль, роль) | статический ключ SA (S3 API) |
| Блокировка | `use_lockfile = true` | `use_lockfile = true` (устаревшее: YDB как DynamoDB) |
| Шифрование | `encrypt = true` / `kms_key_id` | SSE-KMS на бакете (`server_side_encryption_configuration`) |
| Версионирование | `aws_s3_bucket_versioning` | `versioning { enabled = true }` у `yandex_storage_bucket` |

### 2.2 Бакет для стейта: «курица и яйцо»

Бакет со стейтом создают **отдельной маленькой конфигурацией** (`bootstrap/`) с локальным
стейтом (его потом можно мигрировать в этот же бакет) или руками по регламенту:
```hcl
# bootstrap/aws.tf
resource "aws_s3_bucket" "tfstate" {
  bucket = "tfstate-mycompany-111122223333"
  lifecycle { prevent_destroy = true }
}
resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration { status = "Enabled" }       # ⭐ откат испорченного стейта
}
resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
```
```hcl
# bootstrap/yandex.tf
resource "yandex_storage_bucket" "tfstate" {
  bucket = "tfstate-mycompany"
  versioning { enabled = true }
  server_side_encryption_configuration {
    rule {
      apply_server_side_encryption_by_default {
        kms_master_key_id = yandex_kms_symmetric_key.tfstate.id
        sse_algorithm     = "aws:kms"
      }
    }
  }
  lifecycle { prevent_destroy = true }
}
```

| Тип backend | Комментарий |
|-------------|-------------|
| `s3` (и S3-совместимые) | ⭐ Самый распространённый; версионирование + шифрование бакета обязательны |
| `gcs`, `azurerm` | Аналоги в других облаках |
| `http` | Встроенный backend GitLab — удобно, если инфраструктура в GitLab |
| `kubernetes` | Стейт в Secret кластера |
| `consul`, `postgres` | Реже |
| `remote` (Terraform Cloud) | Managed-вариант с UI и политиками |
| `local` | Только эксперименты |

```bash
# инициализация и миграция состояния между backend'ами
terraform init
terraform init -migrate-state       # перенести локальный стейт в удалённый
terraform init -reconfigure         # сменить настройки без переноса
```

> ⭐ Требования к бакету со стейтом: **версионирование включено** (откат при порче),
> **шифрование**, доступ только для тех, кому положено, и отдельный бакет от бэкапов
> и статики.

---

## 3. Блокировки

```text:no-line-numbers
 инженер A: terraform apply ──► взял блокировку (lock) ──► работает
 инженер B: terraform apply ──► Error: Error acquiring the state lock
                                Lock Info: ID, Who, Created, Operation ⭐
```

```bash
# если процесс убили и блокировка «зависла» — снять ПОСЛЕ проверки, что никто не работает
terraform force-unlock <LOCK_ID>
```

⚠️ `force-unlock` — операция для аккуратных: если снять блокировку, пока идёт чужой
apply, можно получить повреждённый стейт.

---

## 4. Работа со стейтом: команды

```bash
terraform state list                          # список ресурсов в стейте
terraform state show yandex_compute_instance.web   # атрибуты конкретного ресурса
terraform state pull > state.json             # выгрузить (например, для анализа)
terraform state push state.json               # ⚠️ загрузить обратно — крайне осторожно

terraform state mv ADDR NEW_ADDR              # переименовать/перенести (в модуль)
terraform state mv docker_container.web module.web.docker_container.this

terraform state rm ADDR                       # ⭐ убрать из стейта, НЕ удаляя ресурс
terraform state replace-provider OLD NEW      # смена провайдера (например, на OpenTofu)
```

| Команда | Когда нужна |
|---------|-------------|
| `state list` / `show` | Разобраться, что вообще под управлением |
| `state mv` | Рефакторинг: переименовали ресурс или вынесли в модуль |
| `state rm` | Ресурс больше не должен управляться Terraform (передали другой команде) |
| `import` | Наоборот: взять существующий ресурс под управление |
| `force-unlock` | Снять зависшую блокировку |

---

## 5. `import` — взять существующее под управление ⭐

```bash
# 1) описать ресурс в коде (можно с минимумом полей)
# 2) импортировать
terraform import yandex_compute_instance.web fhm3k2abcdef
terraform plan     # ⭐ покажет разницу между кодом и реальностью — дописать поля
```

С Terraform 1.5+ есть декларативный импорт (удобнее для массового переноса):
```hcl
import {
  to = yandex_compute_instance.web
  id = "fhm3k2abcdef"
}
```
```bash
terraform plan -generate-config-out=generated.tf    # ⭐ сгенерировать заготовку кода
```

Что такое `id` при импорте — зависит от ресурса и облака (смотри раздел *Import*
в документации ресурса):

| Ресурс | AWS | Yandex Cloud |
|--------|-----|--------------|
| ВМ | `aws_instance` → `i-0abc1234def567890` | `yandex_compute_instance` → `fhm3k2abcdef` |
| Сеть | `aws_vpc` → `vpc-0a1b2c...` | `yandex_vpc_network` → `enp1...` |
| Бакет | `aws_s3_bucket` → имя бакета | `yandex_storage_bucket` → имя бакета |
| Правило SG | `aws_vpc_security_group_ingress_rule` → `sgr-...` | правила — часть `yandex_vpc_security_group`, импортируется группа целиком |

```bash
# найти id без консоли
aws ec2 describe-instances --filters Name=tag:Name,Values=web-1 --query 'Reservations[].Instances[].InstanceId'
yc compute instance list --format json | jq -r '.[] | select(.name=="web-1") | .id'
```

Типовой сценарий «у нас всё создано руками»:
```text:no-line-numbers
1. Описать ресурс в коде (или сгенерировать)
2. terraform import / блок import
3. terraform plan → довести код до состояния "No changes"
4. Повторить для следующего ресурса
5. Зафиксировать правило: руками больше не создаём
```

---

## 6. Дрейф: когда реальность разошлась с кодом

```text:no-line-numbers
Причины дрейфа:
 • правки руками в консоли облака
 • автоматика провайдера (обновление версий, теги, автоскейлинг)
 • другой инструмент менял те же ресурсы

Как обнаружить:
 terraform plan            ⭐ регулярно, в том числе по расписанию в CI
 (план не пустой без изменений кода = дрейф)

Как реагировать:
 1. Понять, кто и зачем изменил
 2. Либо вернуть к коду (apply), либо внести изменение в код
 3. Для полей, которые меняет сама платформа → lifecycle { ignore_changes = [...] }
```

---

## 7. Разделение стейтов ⭐

```text:no-line-numbers
 ОДИН БОЛЬШОЙ СТЕЙТ                     НЕСКОЛЬКО СТЕЙТОВ
 ──────────────────                     ──────────────────
 всё в одном: сеть, ВМ, базы, k8s       prod/network, prod/data, prod/apps
 plan идёт минуты                        быстрый plan
 любая ошибка затрагивает всё            радиус поражения ограничен
 конфликты в команде                     команды работают параллельно
 удобно только на старте                 ⭐ стандарт для реальных проектов
```

Обмен данными между стейтами:
```hcl
# читаем outputs другого стейта
data "terraform_remote_state" "network" {
  backend = "s3"
  config = {
    bucket = "tfstate-mycompany"
    key    = "prod/network/terraform.tfstate"
    region = "ru-central1"
  }
}

resource "yandex_compute_instance" "app" {
  network_interface {
    subnet_id = data.terraform_remote_state.network.outputs.subnet_id
  }
}
```
⚠️ В `config` должны быть **те же параметры доступа, что в backend** соседа. Пример выше
годится для AWS (нужен лишь `region = "eu-central-1"`); для Yandex Object Storage без
`endpoints` и `skip_*` Terraform пойдёт в настоящий AWS и не найдёт бакет:
```hcl
data "terraform_remote_state" "network" {           # Yandex Cloud
  backend = "s3"
  config = {
    endpoints                   = { s3 = "https://storage.yandexcloud.net" }   # kz1: .kz
    bucket                      = "tfstate-mycompany"
    key                         = "prod/network/terraform.tfstate"
    region                      = "ru-central1"
    skip_region_validation      = true
    skip_credentials_validation = true
    skip_requesting_account_id  = true
    skip_s3_checksum            = true
  }
}
```
Альтернатива — искать ресурсы через `data`-источники по имени/тегу
(`data "aws_vpc" { tags = {...} }`, `data "yandex_vpc_network" { name = ... }`): меньше
связности между стейтами, но нужен стабильный способ поиска.

Окружения:
| Способ | Комментарий |
|--------|-------------|
| Разные каталоги + разные `key` в backend | ⭐ Прозрачно, стандарт для prod/stage |
| `terraform workspace` | Один код, несколько стейтов; удобно для временных сред, но легко перепутать текущий workspace |
| Terragrunt | Убирает дублирование конфигурации между окружениями |

---

## 8. Грабли

| Грабля | Последствие | Решение |
|--------|-------------|---------|
| Стейт в git | Утечка секретов, конфликты | `.gitignore`, удалённый backend |
| Нет версионирования бакета | Испорченный стейт не откатить | Включить версионирование |
| Нет блокировок | Параллельные apply портят состояние | Backend с блокировкой |
| `force-unlock` наугад | Повреждение стейта | Сначала убедиться, что apply не идёт |
| Ручное редактирование JSON стейта | Трудноуловимые поломки | `state mv/rm/import`, а не текстовый редактор |
| Один стейт на всю компанию | Медленно, рискованно, конфликты | Разделение по компонентам и окружениям |
| `state rm` вместо `destroy` | Ресурс остался, но им никто не управляет («сирота») | Понимать разницу |
| Секреты в outputs без `sensitive` | Пароли в логах CI | `sensitive = true` + хранилище секретов |
| Игнорирование дрейфа | «Не понимаю, почему план не пустой» | Регулярный plan и расследование |
| `dynamodb_table` в новом проекте | Лишняя таблица, предупреждение deprecated, миграция потом | `use_lockfile = true` с первого дня |
| Бакет `kz1` через `storage.yandexcloud.net` | `NoSuchBucket` / `AccessDenied` | Endpoint `storage.yandexcloud.kz` в backend и remote state |
| `terraform_remote_state` для Yandex без `endpoints` и `skip_*` | Запрос ушёл в AWS, «бакет не найден» | Копировать параметры доступа из backend соседа |

---

## 💼 Как это в DevOps

- Первое, что делают на новом проекте, — выносят стейт в удалённый backend
  с версионированием, шифрованием и блокировкой. Без этого команда работать не может.
- Ключ стейта отражает структуру: `env/component/terraform.tfstate`
  (`prod/network`, `prod/k8s`, `stage/apps`).
- Доступ к бакету со стейтом ограничен: там лежат пароли managed-баз и ключи.
- Регулярный `plan` по расписанию в CI ловит дрейф раньше, чем он станет инцидентом.
- Импорт существующей инфраструктуры — типовая задача при внедрении Terraform
  в живой проект; делается постепенно, компонент за компонентом.
- Стейт живёт рядом с тем, чем управляет: инфраструктура AWS — в S3 своего аккаунта,
  Yandex `kz1` — в Object Storage Казахстана. В стейте лежат адреса, пароли и строки
  подключения — для проектов с требованиями локализации это тоже аргумент.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Понять, что под управлением | `terraform state list` |
| Посмотреть атрибуты ресурса | `terraform state show ADDR` |
| Перенести стейт в облако | backend + `terraform init -migrate-state` |
| Сменить настройки backend | `terraform init -reconfigure` |
| Снять зависшую блокировку | `terraform force-unlock ID` (осторожно) |
| Переименовать ресурс без пересоздания | `terraform state mv OLD NEW` |
| Перестать управлять ресурсом | `terraform state rm ADDR` |
| Взять ресурс под управление | `terraform import ADDR ID` или блок `import` |
| Сгенерировать код по существующему | `terraform plan -generate-config-out=gen.tf` |
| Прочитать outputs другого стейта | `data "terraform_remote_state"` |
| Игнорировать изменения поля | `lifecycle { ignore_changes = [...] }` |
| Скрыть секрет в выводе | `output { sensitive = true }` |
| Найти дрейф | Регулярный `terraform plan` в CI |
| Блокировка в S3 без DynamoDB | `use_lockfile = true` (Terraform/OpenTofu 1.10+) |
| Уйти с DynamoDB-lock | Оба механизма → все на 1.10+ → убрать `dynamodb_table`, `init -reconfigure` |
| Backend Yandex Object Storage | `endpoints = { s3 = "https://storage.yandexcloud.net" }` (+ `skip_*`); kz1 — `.kz` |

---

## 🧠 Что запомнить

1. ⭐ Стейт связывает код с реальными ресурсами; без него Terraform «не видит»
   инфраструктуру.
2. Стейт содержит секреты открытым текстом — его нельзя коммитить и нужно шифровать.
3. Локальный стейт годится только для экспериментов; команда работает с удалённым backend.
4. У бакета со стейтом обязательно включают версионирование и ограничивают доступ.
5. Блокировка предотвращает одновременные apply; `force-unlock` — только после проверки.
   ⭐ В S3 и S3-совместимых хранилищах (AWS, Yandex Object Storage) — `use_lockfile = true`;
   DynamoDB-lock deprecated.
6. `state mv`/`state rm` — инструменты рефакторинга; `state rm` не удаляет сам ресурс.
7. `import` берёт существующий ресурс под управление; с 1.5+ есть декларативный
   блок `import` и генерация кода.
8. Дрейф ловится регулярным `plan`; поля, которые меняет платформа, гасят
   через `ignore_changes`.
9. Один гигантский стейт — антипаттерн: разделяют по окружениям и компонентам.
10. Данные между стейтами передают через `terraform_remote_state` или data-источники.

---

## Задачи

> Для удалённого backend подойдёт бакет облака или локальный **MinIO**
> (`docker run -p 9000:9000 -p 9001:9001 pgsty/silo:RELEASE.2026-09-16T00-00-00Z server /data --console-address ":9001"` —
> форк MinIO: официальный образ с сентября 2026 не скачивается, см. материалы по NFS/MinIO
> в блоке про хранилища).

---

### Блок A. Теория

**A1.** ⭐ Зачем нужен стейт? Что произойдёт без него?

<details><summary>Ответ</summary>

Стейт связывает адреса ресурсов в коде с их реальными идентификаторами
у провайдера и хранит их атрибуты. Без него Terraform не знает, что уже создано,
и попытается создать всё заново (или не сможет ничего изменить и удалить).

</details>

**A2.** Что именно хранится в стейте?

<details><summary>Ответ</summary>

Соответствие «адрес → id», атрибуты ресурсов (включая чувствительные),
зависимости, версии Terraform и провайдеров, служебные метаданные (serial, lineage),
outputs.

</details>

**A3.** Почему стейт нельзя коммитить в git?

<details><summary>Ответ</summary>

Он содержит секреты открытым текстом (пароли, токены, ключи), а также
конфликтует при параллельной работе; попадание в git = утечка и конфликты слияния.

</details>

**A4.** Какие проблемы у локального стейта в команде?

<details><summary>Ответ</summary>

Нет общего доступа и блокировок, легко потерять, нет версий и истории,
невозможно применять из CI.

</details>

**A5.** Что такое backend и какие типы бывают?

<details><summary>Ответ</summary>

Backend — место хранения стейта и механизм блокировок: `s3` (и S3-совместимые),
`gcs`, `azurerm`, `http` (GitLab), `kubernetes`, `consul`, `pg`, `remote`
(Terraform Cloud), `local`.

</details>

**A6.** Какие требования предъявляются к бакету со стейтом?

<details><summary>Ответ</summary>

Включённое версионирование, шифрование, ограниченный доступ, отдельный бакет
от прочих данных, механизм блокировок.

</details>

**A7.** Что такое блокировка стейта и когда используют `force-unlock`?

<details><summary>Ответ</summary>

Механизм, не позволяющий двум процессам одновременно изменять стейт.
`force-unlock` применяют, когда процесс аварийно завершился и блокировка «зависла», —
и только убедившись, что никто не выполняет apply.

</details>

**A8.** Чем `terraform state rm` отличается от `terraform destroy`?

<details><summary>Ответ</summary>

`destroy` удаляет реальный ресурс; `state rm` лишь перестаёт им управлять —
ресурс остаётся в облаке (и может стать «сиротой»).

</details>

**A9.** Зачем нужен `terraform state mv`? Приведи два сценария.

<details><summary>Ответ</summary>

Переименование ресурса без пересоздания и перенос ресурса в модуль/из модуля
при рефакторинге.

</details>

**A10.** Как взять под управление существующий ресурс? Опиши два способа.

<details><summary>Ответ</summary>

`terraform import ADDR ID` после описания ресурса в коде, либо декларативный
блок `import` (Terraform 1.5+), в том числе с генерацией кода
`-generate-config-out`.

</details>

**A11.** Что такое дрейф и как его регулярно обнаруживать?

<details><summary>Ответ</summary>

Расхождение кода и реальности из-за изменений вне Terraform. Обнаруживается
регулярным `terraform plan` (в том числе по расписанию в CI).

</details>

**A12.** Когда уместен `ignore_changes`, а когда это маскировка проблемы?

<details><summary>Ответ</summary>

Уместен для полей, которыми управляет сама платформа (служебные теги,
автоматически меняющиеся значения). Маскировка — когда им «затыкают» реальные
расхождения конфигурации, чтобы план был чистым.

</details>

**A13.** ⭐ Почему один большой стейт — плохая идея?

<details><summary>Ответ</summary>

Долгий plan, широкий радиус поражения при ошибке, конфликты и блокировки
между командами, сложность прав доступа. Разделяют по окружениям и компонентам.

</details>

**A14.** Как передать данные из одного стейта в другой?

<details><summary>Ответ</summary>

Через `data "terraform_remote_state"` (читая outputs) или через data-источники,
находящие ресурсы по имени/тегу.

</details>

**A15.** Чем workspaces отличаются от разделения по каталогам и когда что выбирать?

<details><summary>Ответ</summary>

Workspaces дают несколько стейтов для одного кода: удобно для временных
и однотипных окружений, но легко перепутать текущий workspace и сложно держать
различия конфигураций. Разные каталоги/ключи — явное разделение, стандарт для prod/stage.

</details>

---

### Блок B. «Оцени решение»

```text:no-line-numbers
B1.  terraform.tfstate закоммичен в репозиторий
B2.  backend "s3" с версионированием и шифрованием бакета
B3.  backend "local" на проекте из пяти инженеров
B4.  Один стейт на всю компанию: сети, k8s, базы, приложения, DNS
B5.  key = "prod/network/terraform.tfstate", отдельные ключи по компонентам
B6.  force-unlock выполняется скриптом автоматически при любой ошибке блокировки
B7.  Стейт лежит в том же бакете, что и бэкапы, доступ у всей команды
B8.  output "db_password" { value = ..., sensitive = true }
B9.  Ресурсы создаются руками, Terraform используется только для новых
B10. terraform state rm применили, чтобы "убрать ресурс", ресурс остался в облаке
B11. lifecycle { ignore_changes = [tags] } на ресурсах, где теги ставит облако
B12. lifecycle { ignore_changes = [instance_type, image_id] } "чтобы план был чистый"
B13. terraform plan запускается только вручную раз в квартал
B14. JSON стейта отредактировали вручную, чтобы "поправить id"
```

<details><summary>Ответ</summary>

**B1.** Утечка секретов и конфликты — недопустимо.
**B2.** Правильная конфигурация — при условии, что включена и блокировка (`use_lockfile = true`).
**B3.** Локальный стейт в команде — блокирует совместную работу.
**B4.** Единый стейт: медленно и опасно.
**B5.** Правильное разделение.
**B6.** Автоматический `force-unlock` может повредить стейт при реально идущем apply.
**B7.** Смешение стейта с другими данными и широкий доступ — риск утечки.
**B8.** Правильно: `sensitive` скрывает значение в выводе (но не в стейте).
**B9.** Половина инфраструктуры вне управления: дрейф и «сироты»; нужен постепенный импорт.
**B10.** Классическая ошибка: ресурс остался и продолжает тарифицироваться,
но им никто не управляет.
**B11.** Уместное использование `ignore_changes`.
**B12.** Игнорирование ключевых полей превращает код в фикцию.
**B13.** Редкий plan = поздно обнаруженный дрейф.
**B14.** Ручное редактирование стейта — источник трудноуловимых поломок;
есть `state mv/rm/import`.

</details>

---

### Блок C. Практика

#### C1. 🔑 Изучить локальный стейт
1. Создай пару ресурсов (docker/local провайдер), выполни `apply`.
2. Открой `terraform.tfstate`: найди адрес ресурса, id, атрибуты, зависимости.
3. Найди `random_password` (создай его) и убедись, что пароль виден в стейте открытым
   текстом.

<details><summary>Ответ</summary>

В стейте у `random_password` виден атрибут `result` — это и есть демонстрация
того, почему стейт секретен.

</details>

#### C2. Удалённый backend
1. Подними MinIO (или используй облачный бакет), создай бакет `tfstate`.
2. Настрой `backend "s3"` с нужными флагами.
3. Выполни `terraform init -migrate-state`, проверь, что стейт уехал в бакет.
4. Удали локальный файл и убедись, что `plan` по-прежнему работает.

<details><summary>Ответ</summary>

После миграции локальный файл можно удалить: источник истины — бакет.

</details>

#### C3. Версионирование и восстановление
1. Включи версионирование на бакете.
2. Сделай несколько `apply`, посмотри версии объекта стейта.
3. «Испорти» стейт (загрузи пустой файл) и восстанови предыдущую версию.

<details><summary>Ответ</summary>

Восстановление версии объекта в бакете — штатный способ «откатить» испорченный стейт.

</details>

#### C4. Блокировки
1. Запусти `terraform apply` и не подтверждай.
2. Из второго терминала запусти `plan`/`apply` — прочитай сообщение о блокировке.
3. Прерви первый процесс и сними блокировку `force-unlock`.

<details><summary>Ответ</summary>

Сообщение о блокировке содержит ID, пользователя, время и операцию — по ним
и принимают решение.

</details>

#### C5. `state list` и `state show`
Изучи все ресурсы в стейте, найди у одного из них id, попробуй сопоставить
с тем, что видно в консоли облака/`docker ps`.

#### C6. 🔑 Рефакторинг через `state mv`
1. Переименуй ресурс в коде (`docker_container.web` → `docker_container.app`).
2. Выполни `plan` — Terraform предложит удалить и создать заново.
3. Отмени, сделай `terraform state mv` и снова `plan` — изменений быть не должно.

<details><summary>Ответ</summary>

После `state mv` план должен быть пустым: ресурс просто «переехал» по адресу.

</details>

#### C7. ⭐ Импорт существующего ресурса
1. Создай контейнер/ВМ **вручную** (не Terraform'ом).
2. Опиши его в коде.
3. Импортируй (`terraform import` или блок `import`).
4. Доводи код до состояния «No changes».

<details><summary>Ответ</summary>

Признак успешного импорта — `No changes` после доведения кода.

</details>

#### C8. Генерация кода
Попробуй `terraform plan -generate-config-out=generated.tf` с блоком `import`
и посмотри, какой код получился.

#### C9. Дрейф
1. Измени ресурс вручную (переименуй контейнер, поменяй тег в облаке).
2. Выполни `plan` и прочитай, что Terraform хочет сделать.
3. Реши: вернуть к коду или внести изменение в код. Сделай оба варианта по очереди.

<details><summary>Ответ</summary>

Terraform либо вернёт ресурс к описанному состоянию, либо (если изменение
внесено в код) покажет отсутствие изменений.

</details>

#### C10. Разделение стейтов
Разнеси инфраструктуру на два стейта (`network` и `app`), передай `subnet_id`
через `terraform_remote_state`. Сравни время `plan` до и после.

#### C11. 🔑 AWS-вариант C2 + C4: S3 backend с `use_lockfile`
1. Отдельной конфигурацией `bootstrap/` создай бакет: версионирование, public access block,
   `prevent_destroy` (конспект, §2.2).
2. Настрой `backend "s3"` с `encrypt = true` и `use_lockfile = true`, выполни
   `terraform init -migrate-state`.
3. Запусти `apply` и не подтверждай; в другом терминале — `aws s3 ls s3://<бакет>/<key-dir>/`:
   найди `*.tflock`. Второй `plan` должен упасть на блокировке.
4. Сделай то же для Yandex Object Storage (регион Россия или `kz1`) — какие параметры backend
   пришлось добавить?

<details><summary>Ответ</summary>

Пока держится блокировка, рядом со стейтом лежит `<key>.tflock` с Lock Info;
после завершения он удаляется. Для Yandex добавились `endpoints.s3`
(`storage.yandexcloud.net` или `.kz`), флаги `skip_region_validation`,
`skip_credentials_validation`, `skip_requesting_account_id`, `skip_s3_checksum`
и статический ключ SA в `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`.

</details>

#### C12. Миграция с DynamoDB-lock
1. Смоделируй «старый» проект: backend с `dynamodb_table` (таблица с ключом `LockID`).
2. Посмотри предупреждение при `init`.
3. Включи `use_lockfile = true` рядом с `dynamodb_table`, проверь, что блокируются оба.
4. Убери `dynamodb_table`, `terraform init -reconfigure`, удали таблицу. Запиши регламент:
   в каком порядке это делать в команде из пяти человек и CI.

<details><summary>Ответ</summary>

Порядок: 1) все (люди, образ CI) на Terraform/OpenTofu 1.10+; 2) MR с обоими
механизмами — старые клиенты берут DynamoDB-lock, новые оба; 3) когда старых клиентов нет —
MR без `dynamodb_table` + `init -reconfigure` у всех; 4) отдельным изменением удалить таблицу.
Если убрать DynamoDB раньше, старый клиент будет работать **без блокировки**.

</details>

---

### Блок D. Инциденты

**D1.** Стейт потерян (удалён бакет/файл). Что делать?

<details><summary>Ответ</summary>

Если включено версионирование — восстановить предыдущую версию. Если нет —
воссоздать стейт импортом существующих ресурсов (долго, но возможно). Профилактика:
версионирование, резервные копии, ограниченный доступ.

</details>

**D2.** Два инженера применили изменения одновременно, стейт «сломался». Как чинить?

<details><summary>Ответ</summary>

Восстановить стейт из версии в бакете, убедиться, что реальное состояние
соответствует, при расхождениях — импортировать/удалить лишнее. Внедрить блокировки.

</details>

**D3.** `Error acquiring the state lock` держится уже час. Порядок действий.

<details><summary>Ответ</summary>

Проверить, не идёт ли реально apply (CI, коллеги), посмотреть Lock Info
(кто и когда взял), связаться с владельцем; только затем `force-unlock`.

</details>

**D4.** Terraform хочет пересоздать все ресурсы, хотя код не менялся. Гипотезы?

<details><summary>Ответ</summary>

Другой стейт/рабочая директория (пустой стейт), смена провайдера или его версии
с изменением идентификаторов, изменение полей, вызывающих replacement,
переименование модуля/ресурсов.

</details>

**D5.** В стейте есть ресурс, которого нет в облаке. Что произошло и что делать?

<details><summary>Ответ</summary>

Ресурс удалили вне Terraform. План покажет его создание; варианты — дать создать
заново или убрать из кода и из стейта (`state rm`).

</details>

**D6.** В облаке есть ресурс, которого нет в стейте. Варианты действий.

<details><summary>Ответ</summary>

Ресурс создан вне Terraform: импортировать, оставить неуправляемым (плохо)
или удалить вручную, если он не нужен.

</details>

**D7.** Пароль от прод-базы утёк: обнаружен в стейте, доступ к бакету был у всей компании.
Действия.

<details><summary>Ответ</summary>

Считать секрет скомпрометированным: ротировать пароль, ограничить доступ
к бакету, включить шифрование и аудит, вынести секреты в Vault, проверить логи доступа.

</details>

**D8.** `plan` идёт 12 минут и блокирует работу команды. Что менять?

<details><summary>Ответ</summary>

Разделить стейт на компоненты, уменьшить число ресурсов в одном стейте,
использовать `-refresh=false` осознанно, вынести редкоменяющиеся части отдельно.

</details>

**D9.** После переименования модуля Terraform предлагает удалить и создать 40 ресурсов.
Как избежать?

<details><summary>Ответ</summary>

Использовать `terraform state mv` для всех адресов (или блоки `moved`),
чтобы Terraform понял, что ресурсы просто переехали.

</details>

**D10.** Нужно передать управление частью ресурсов другой команде. Как это сделать
без пересоздания?

<details><summary>Ответ</summary>

Разделить стейты: перенести ресурсы через `state mv` в новый стейт
(или `state rm` + `import` в новом), передать права на бакет и код.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое стейт и зачем он нужен?

<details><summary>Ответ</summary>

Файл состояния, связывающий код с реальными ресурсами и хранящий их атрибуты.

</details>

**2.** Что хранится в стейте и почему его нельзя коммитить?

<details><summary>Ответ</summary>

Идентификаторы, атрибуты (включая секреты), зависимости, метаданные; в git нельзя
из-за утечек и конфликтов.

</details>

**3.** Что такое backend и какие бывают?

<details><summary>Ответ</summary>

Место хранения стейта и блокировок: s3/gcs/azurerm/http/kubernetes/remote/local.

</details>

**4.** Как организуются блокировки?

<details><summary>Ответ</summary>

Через backend с поддержкой блокировок: в S3 и S3-совместимых хранилищах (AWS,
Yandex Object Storage) — `use_lockfile = true` (файл `.tflock` условной записью,
Terraform 1.10+); DynamoDB (у Yandex — YDB Document API) — устаревший путь, deprecated
с 1.11; у `http` (GitLab), `gcs`, `azurerm`, `kubernetes` — встроенные механизмы.
Снимать вручную — только осознанно.

</details>

**5.** Чем `state rm` отличается от `destroy`?

<details><summary>Ответ</summary>

`state rm` перестаёт управлять ресурсом, `destroy` его удаляет.

</details>

**6.** Как импортировать существующую инфраструктуру?

<details><summary>Ответ</summary>

`terraform import` или блок `import` с последующим доведением кода до «No changes».

</details>

**7.** Что такое дрейф и как его находить?

<details><summary>Ответ</summary>

Расхождение кода и реальности; ищется регулярным `plan`, в том числе по расписанию.

</details>

**8.** Как разделяют стейты и зачем?

<details><summary>Ответ</summary>

По окружениям и компонентам, чтобы ускорить plan и ограничить радиус поражения.

</details>

**9.** Как передать значения между стейтами?

<details><summary>Ответ</summary>

`terraform_remote_state` или data-источники.

</details>

**10.** Что делать, если стейт повреждён или потерян?

<details><summary>Ответ</summary>

Восстановить из версии бакета; при отсутствии версий — пересобрать импортом.

</details>

---

### 🎯 Чек-лист

- [ ] ⭐ Объясняю, зачем нужен стейт и что в нём лежит
- [ ] Настроил удалённый backend и выполнил миграцию стейта
- [ ] Включил версионирование и восстанавливал стейт из версии
- [ ] Видел сообщение о блокировке и снимал её осознанно
- [ ] Пользуюсь `state list/show/mv/rm`
- [ ] Импортировал существующий ресурс и довёл код до «No changes»
- [ ] Ловил дрейф через `plan` и понимаю, как реагировать
- [ ] Разделил инфраструктуру на несколько стейтов
- [ ] Передаю значения между стейтами через remote state
- [ ] Знаю, что делать при потере или порче стейта
- [ ] Настроил S3 backend с `use_lockfile` в AWS и/или Yandex Object Storage (знаю endpoint `kz1`)
