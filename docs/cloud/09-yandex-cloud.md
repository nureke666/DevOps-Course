---
title: "09. Yandex Cloud глубже"
description: "Ресурсная модель и регионы, IAM и workload identity federation, VPC, instance group, Managed Kubernetes, Managed PostgreSQL, Object Storage и Lockbox в Yandex Cloud"
---

# 09. Yandex Cloud глубже: то, что трогает девопс

> Блок → Облака → тема 09. Понятия — в [01](/cloud/01-cloud-models)–[05](/cloud/05-managed-services),
> та же глубина для AWS — в [«08. AWS глубже»](/cloud/08-aws-deep) (в конце темы — таблица соответствия).
> IAM с точки зрения безопасности здесь не повторяем,
> провайдер [Terraform](/terraform/) и стейт в Object Storage — тема отдельная.
>
> **После темы ты умеешь:** разложить ресурсы по облакам и каталогам, выбрать регион (Россия
> или Казахстан) и понимать, что это меняет; выдать сервисному аккаунту роль на конкретный
> ресурс и выбрать тип ключа; пустить GitLab CI и поды без ключей (workload identity
> federation); собрать сеть с NAT и security groups, instance group за балансировщиком,
> Managed Kubernetes с Container Registry, Managed PostgreSQL; читать секреты Lockbox и
> работать с Object Storage через S3 API.
>
> ⚠️ Версии, набор сервисов по регионам и цены — **проверь, сентябрь 2026**. Цены в регионе
> Казахстан — в тенге на `yandex.cloud/ru-kz/prices`.

---

## 🗺️ Карта темы

```text:no-line-numbers
 Организация (Cloud Organization: пользователи, федерации SSO, группы)
 ├── облако linkd-prod          ← граница биллинга и прав (аналог аккаунта AWS)
 │   ├── каталог prod           ← здесь живут ресурсы (аналог «аккаунт + регион»)
 │   │   ├── VPC-сеть (глобальная) → подсети по зонам → security groups, NAT gateway
 │   │   ├── instance group → ALB/NLB          ├── Managed Kubernetes → Container Registry
 │   │   ├── Managed PostgreSQL (хосты по зонам)├── Object Storage (S3 API), Lockbox
 │   │   └── сервисные аккаунты + роли на ресурсы, Monitoring, Logging, Audit Trails
 │   └── каталог stage
 └── облако linkd-dev

 Регион Россия: ru-central1 (a, b, d, e)   │   Регион Казахстан: kz1 (одна зона kz1-a)
 console.yandex.cloud                       │   kz.console.yandex.cloud — отдельная консоль,
 storage.yandexcloud.net · cr.yandex        │   биллинг, API; storage.yandexcloud.kz · cr.yandexcloud.kz
```

---

## 1. Ресурсная модель и регионы

| Уровень | Что это | Практика |
|---------|---------|----------|
| **Организация** | Пользователи, группы, федерации SSO | Одна на компанию; вход людей — через SAML/OIDC-федерацию |
| **Облако** | Граница биллинга и прав | Отдельные облака под prod и non-prod |
| **Каталог (folder)** | Контейнер ресурсов | prod/stage/dev, по командам; роли выдаются на каталог |
| **Ресурс** | ВМ, сеть, бакет, секрет… | Роли можно выдать и на отдельный ресурс |

**Регионы.** Регион определяется консолью, в которой зарегистрирован аккаунт, и у каждого
своя инфраструктура, биллинг и API:

| | Россия | Казахстан |
|---|--------|-----------|
| Зоны | `ru-central1-a`, `-b`, `-d` (рекомендуется для новых), `-e`; `-m` — только BareMetal | ⭐ **только `kz1-a`** |
| Консоль / биллинг | `console.yandex.cloud` / `center.yandex.cloud` | `kz.console.yandex.cloud` / `kz.center.yandex.cloud` |
| API / Object Storage | `api.cloud.yandex.net` / `storage.yandexcloud.net` | `api.yandexcloud.kz` / `storage.yandexcloud.kz` |
| Registry | `cr.yandex` | `cr.yandexcloud.kz` |
| Оператор | — | ТОО «Облачные Сервисы Казахстан», ЦОД в Караганде, цены в тенге |

Данные **не пересекают** регионы: бакет из России не виден в Казахстане. Подключить второй
регион к той же организации можно (controlled organization, по запросу) — это может сделать
только владелец организации.

**Что есть в регионе Казахстан** (таблица сервисов в документации, сентябрь 2026):

| ✅ Есть | ❌ Нет |
|--------|--------|
| Compute, VPC, NLB, ALB, DNS, CDN, Interconnect, Cloud Backup | Cloud Functions, Serverless Containers, API Gateway |
| Managed Kubernetes, Container Registry, Cloud Registry | Managed GitLab, SourceCraft |
| Managed PostgreSQL, MySQL, ClickHouse, Kafka, Valkey, OpenSearch, Greenplum, YDB | DataLens, Data Proc, Managed Airflow |
| Object Storage, Lockbox, KMS, Certificate Manager, Audit Trails | DDoS Protection, Smart Web Security, SmartCaptcha |
| Monitoring, Cloud Logging, Message Queue, Organization, IAM | Cloud Postbox, Data Streams, IoT Core |

⭐ **Одна зона в Казахстане — главное архитектурное следствие.** Мультизонной
отказоустойчивости «как в AWS» внутри региона нет: HA-мастер k8s и хосты PostgreSQL
защищают от отказа хоста, но не от отказа ЦОД. DR — вторая площадка, а если в данных есть
ПДн граждан РК, то тоже в Казахстане ([10_kz_clouds.md](/cloud/10-kz-clouds),
Security/07, §7).

```bash
yc init                                   # профиль: вход, облако, каталог, зона
yc init --region=kz                       # профиль для региона Казахстан
yc config profile list && yc config list  # какой профиль и каталог активны
yc resource-manager folder list
```

---

## 2. IAM: роли, сервисные аккаунты, ключи

Права — это **роль, назначенная субъекту на ресурс** (организацию, облако, каталог или
конкретный бакет/секрет/SA). Роли наследуются вниз: роль на облако действует во всех каталогах.

| Тип роли | Примеры | Когда |
|----------|---------|-------|
| Примитивные | `auditor` (метаданные без данных), `viewer`, `editor`, `admin` | Людям на чтение; `editor`/`admin` — ⚠️ широко |
| Сервисные | `compute.editor`, `storage.uploader`, `lockbox.payloadViewer`, `k8s.clusters.agent`, `container-registry.images.puller` | ⭐ Сервисным аккаунтам — только они |

**Сервисный аккаунт (SA)** — identity программы. Живёт в каталоге, получает роли, может быть
привязан к ВМ (тогда ВМ получает IAM-токен из metadata без ключей).

| Тип ключа | Что это | Где нужен | Риск |
|-----------|---------|-----------|------|
| **IAM-токен** | Короткоживущий (до 12 часов) | ⭐ Почти все API; ВМ с SA получает его сама | Минимальный |
| Авторизованный ключ | Пара ключей SA; из него подписывается JWT → IAM-токен | Terraform/софт вне облака, ESO для Lockbox | Живёт до отзыва |
| Статический ключ доступа | Пара `key_id`/`secret` в стиле AWS | S3 API Object Storage, YDB; из него можно выпустить временный ключ (STS) | Живёт до отзыва |
| API-ключ | Для сервисов без IAM-токенов; можно ограничить scope и срок | Отдельные API | Ограничивай scope и срок |

```bash
FOLDER_ID=$(yc config get folder-id)
yc iam service-account create --name backup-writer
SA_ID=$(yc iam service-account get backup-writer --format json | jq -r .id)

# роль на КАТАЛОГ (широко: все бакеты каталога)
yc resource-manager folder add-access-binding "$FOLDER_ID" --role storage.viewer --subject serviceAccount:"$SA_ID"
# права на КОНКРЕТНЫЙ бакет (узко; write — только вместе с read; --grants задаёт ACL целиком)
yc storage bucket update --name linkd-backups \
  --grants grant-type=grant-type-account,grantee-id="$SA_ID",permission=permission-read \
  --grants grant-type=grant-type-account,grantee-id="$SA_ID",permission=permission-write

yc iam access-key create --service-account-name backup-writer   # статический ключ для S3 API
yc iam key create --service-account-name tf-runner --output key.json   # авторизованный ключ
yc iam create-token                                             # IAM-токен текущего профиля
```
> ⚠️ Секрет статического ключа показывается **один раз** — сразу в Lockbox или Vault. Любой
> ключ SA — такой же долгоживущий секрет, как access key AWS: ротация и инвентарь
> (Security/05, §5).

---

## 3. Без ключей: workload identity federation для CI и подов

Аналог OIDC в AWS: внешний OIDC-провайдер выдаёт JWT, IAM Yandex Cloud меняет его на
IAM-токен сервисного аккаунта. Долгоживущих ключей нет.

```text:no-line-numbers
 GitLab job / под k8s ──JWT──► federation (issuer, audience, JWKS)
                                   └── federated credential: SA ↔ external subject
                         ◄── IAM-токен SA ── POST https://auth.yandex.cloud/oauth/token
```

**GitLab CI → Yandex Cloud:**
```bash
yc iam workload-identity oidc federation create --name gitlab \
  --issuer "https://gitlab.com" --audiences "https://gitlab.com" --jwks-url "https://gitlab.com/oauth/discovery/keys"
yc iam workload-identity federated-credential create \
  --service-account-id "$CI_SA_ID" --federation-id "$FED_ID" \
  --external-subject-id "project_path:acme/linkd:ref_type:branch:ref:main"   # ⭐ только main
```
```yaml
deploy:
  id_tokens:
    YC_JWT: { aud: https://gitlab.com }
  script:
    - >
      export YC_TOKEN=$(curl -s -X POST https://auth.yandex.cloud/oauth/token
      -H "Content-Type: application/x-www-form-urlencoded"
      -d "grant_type=urn:ietf:params:oauth:grant-type:token-exchange&requested_token_type=urn:ietf:params:oauth:token-type:access_token&audience=${CI_SA_ID}&subject_token=${YC_JWT}&subject_token_type=urn:ietf:params:oauth:token-type:id_token"
      | jq -r .access_token)
    - terraform apply -auto-approve      # провайдер yandex читает YC_TOKEN
```

**Под в Managed Kubernetes → API Yandex Cloud** (аналог IRSA): включить federation в кластере
и группе узлов, взять issuer кластера (`https://storage.yandexcloud.net/mk8s-oidc/v1/clusters/<id>`),
создать federation и federated credential с subject `system:serviceaccount:<ns>:<sa>`. Под
монтирует projected-токен SA с этим `audience` и сам меняет его на IAM-токен тем же POST.
```bash
yc managed-kubernetes cluster update --id "$CLUSTER_ID" --enable-workload-identity-federation
```
> 💡 В отличие от EKS Pod Identity, SDK не подменяет креды «сам»: обмен токена делает код
> или sidecar. Для синхронизации секретов в k8s проще External Secrets Operator с провайдером
> `yandexlockbox` — он пока работает через авторизованный ключ SA (§8).

---

## 4. VPC, NAT и security groups

| Деталь | Что знать |
|--------|-----------|
| Сеть | **Глобальная** в регионе; подсеть — в одной зоне |
| Выход в интернет | Публичный IP у ВМ или **NAT gateway** (`shared_egress_gateway`) + route table на подсети |
| Security group | Stateful, на интерфейсе; правила могут ссылаться на другую SG, на «себя» (`self_security_group`) и на диапазоны health check'ов балансировщиков (`loadbalancer_healthchecks`) |
| SG по умолчанию | Создаётся с сетью и применяется к интерфейсам без своей SG — назначай свои явно |
| Публичные IP | Динамический (меняется после stop) или статический (платный и в резерве) |

```hcl
resource "yandex_vpc_network" "main" { name = "lab" }

resource "yandex_vpc_gateway" "nat" {
  name = "lab-nat"
  shared_egress_gateway {}
}
resource "yandex_vpc_route_table" "private" {
  network_id = yandex_vpc_network.main.id
  static_route {
    destination_prefix = "0.0.0.0/0"
    gateway_id         = yandex_vpc_gateway.nat.id
  }
}
resource "yandex_vpc_subnet" "private" {
  for_each       = { a = "10.30.16.0/20", b = "10.30.32.0/20", d = "10.30.48.0/20" }
  name           = "private-${each.key}"
  zone           = "ru-central1-${each.key}"      # в Казахстане — только kz1-a
  network_id     = yandex_vpc_network.main.id
  v4_cidr_blocks = [each.value]
  route_table_id = yandex_vpc_route_table.private.id
}

resource "yandex_vpc_security_group" "web" {
  name       = "web"
  network_id = yandex_vpc_network.main.id
  ingress {
    protocol          = "TCP"
    port              = 80
    predefined_target = "loadbalancer_healthchecks"   # проверки балансировщика
  }
  ingress {
    protocol          = "TCP"
    port              = 80
    security_group_id = yandex_vpc_security_group.alb.id   # «от группы к группе»
  }
  egress {
    protocol       = "ANY"
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
}
```

---

## 5. Compute: instance group за балансировщиком

**Instance group** = Launch Template + ASG в одном ресурсе. Работает от имени своего SA:
`compute.editor` на каталог, плюс `load-balancer.editor` (интеграция с NLB) или `alb.editor`
(с ALB).

```hcl
resource "yandex_compute_instance_group" "web" {
  name               = "web"
  service_account_id = yandex_iam_service_account.ig.id
  instance_template {
    platform_id = "standard-v3"
    resources {
      cores         = 2
      memory        = 2
      core_fraction = 20                   # дешёвые ВМ с долей vCPU — для учёбы
    }
    boot_disk {
      initialize_params { image_id = data.yandex_compute_image.ubuntu.id }
    }
    network_interface {
      subnet_ids         = [for s in yandex_vpc_subnet.private : s.id]
      security_group_ids = [yandex_vpc_security_group.web.id]
    }
    scheduling_policy { preemptible = true }          # прерываемые — в разы дешевле
    metadata = { user-data = file("cloud-init.yaml") }
  }
  scale_policy {
    fixed_scale { size = 2 }               # или auto_scale { min_zone_size, max_size, cpu_utilization_target }
  }
  allocation_policy { zones = ["ru-central1-a", "ru-central1-b"] }
  deploy_policy {
    max_unavailable = 1                    # раскатка по одной ВМ
    max_expansion   = 0
  }
  health_check {
    http_options {
      port = 80
      path = "/healthz"
    }
  }
  application_load_balancer { target_group_name = "web-tg" }   # для NLB — load_balancer {}
}
```

| Балансировщик | Yandex Cloud | Аналог AWS |
|---------------|--------------|------------|
| L4 | Network Load Balancer: listener → target group, health check, внешний или внутренний | NLB |
| L7 | Application Load Balancer: HTTP-роутеры, virtual hosts, backend groups, TLS из Certificate Manager | ALB |
| k8s Ingress / Gateway API | ALB Ingress Controller / Gateway API для ALB | AWS Load Balancer Controller |

`yc compute instance-group list-instances --name web` — статусы и зоны ВМ; `yc compute ssh --name <vm>` —
вход по OS Login. ⚠️ `preemptible = true` — ВМ останавливается не позже чем через 24 часа и в любой
момент при нехватке ресурсов: для учёбы и stateless, не для прода с состоянием.

---

## 6. Managed Kubernetes + Container Registry

| Что | Факт |
|-----|------|
| Мастер | Базовый (один хост, недоступен при обновлении) или высокодоступный — 3 хоста в одной зоне или в трёх зонах |
| Каналы | `RAPID` (автообновления нельзя выключить), `REGULAR`, `STABLE`; канал выбирается при создании и не меняется |
| Версии (сентябрь 2026) | 1.34 — только в `RAPID`, 1.33 — во всех каналах; 1.32 заканчивает поддержку. Yandex заметно отстаёт от upstream и EKS |
| Обновления | Минорные — вручную по одной версии; группа узлов может отставать от мастера на 2 минорные |
| Два SA | **Кластера** — `k8s.clusters.agent` (+ `vpc.publicAdmin` при публичном доступе); **узлов** — `container-registry.images.puller` |

```hcl
resource "yandex_kubernetes_cluster" "main" {
  name       = "lab"
  network_id = yandex_vpc_network.main.id
  master {
    version   = "1.33"
    public_ip = true                                   # лаба; прод — без публичного API или с SG по CIDR
    zonal {
      zone      = yandex_vpc_subnet.private["a"].zone
      subnet_id = yandex_vpc_subnet.private["a"].id
    }
    security_group_ids = [yandex_vpc_security_group.k8s_master.id]
    maintenance_policy { auto_upgrade = true }
  }
  service_account_id      = yandex_iam_service_account.k8s_cluster.id
  node_service_account_id = yandex_iam_service_account.k8s_nodes.id
  release_channel         = "STABLE"
  workload_identity_federation { enabled = true }
  # ⚠️ depends_on на ресурсы с ролями SA — иначе destroy снимет роли раньше кластера
  depends_on = [yandex_resourcemanager_folder_iam_member.k8s_agent,
                yandex_resourcemanager_folder_iam_member.nodes_puller]
}

# yandex_kubernetes_node_group: cluster_id, version = "1.33",
#   instance_template { platform_id, resources { cores = 2, memory = 4 }, network_interface
#   { subnet_ids, security_group_ids }, scheduling_policy { preemptible = true } },
#   scale_policy { auto_scale { min = 1, max = 3, initial = 2 } }, allocation_policy { location { zone } }
```
```bash
yc managed-kubernetes cluster get-credentials lab --external   # kubeconfig; --internal из VPC
kubectl get nodes -o wide

# Container Registry
yc container registry create --name linkd
yc container registry configure-docker                        # credential helper для docker
docker tag linkd:1.4.2 cr.yandex/<registry-id>/linkd:1.4.2    # в Казахстане — cr.yandexcloud.kz
docker push cr.yandex/<registry-id>/linkd:1.4.2
yc container image list --registry-name linkd
```
В CI пуш — SA с `container-registry.images.pusher` через workload identity federation (§3);
узлы тянут образы по роли `images.puller` своего SA — `imagePullSecrets` не нужны. В реестре есть
сканер уязвимостей и lifecycle-политики удаления старых тегов.

---

## 7. Managed PostgreSQL

| Что | Как устроено |
|-----|--------------|
| HA | Несколько хостов в разных зонах, автоматический failover; в Казахстане все хосты в `kz1-a` |
| Подключение | Порт **6432** (встроенный пулер), TLS обязателен |
| Особые FQDN | `c-<cluster_id>.rw.mdb.yandexcloud.net` — всегда текущий мастер; `c-<id>.ro…` — самая свежая реплика |
| Версии (сентябрь 2026) | 15, 16, 17 поддерживаются, 18 — новая, 14 — устаревшая |
| Бэкапы | WAL-G: полные + WAL; хранятся 7 дней по умолчанию (настраивается 7–60), по политикам — до 3 лет; ⭐ PITR включён и восстанавливает в **новый** кластер |
| После удаления кластера | Бэкапы хранятся ещё 7 дней |

```hcl
resource "yandex_mdb_postgresql_cluster" "pg" {
  name                = "linkd-pg"
  environment         = "PRODUCTION"
  network_id          = yandex_vpc_network.main.id
  security_group_ids  = [yandex_vpc_security_group.db.id]    # 6432 только от web/k8s
  deletion_protection = true
  config {
    version = "17"
    resources {
      resource_preset_id = "s3-c2-m8"
      disk_type_id       = "network-ssd"
      disk_size          = 20
    }
    backup_retain_period_days = 14
  }
  host {
    zone      = "ru-central1-a"
    subnet_id = yandex_vpc_subnet.private["a"].id
  }
  host {
    zone      = "ru-central1-b"
    subnet_id = yandex_vpc_subnet.private["b"].id
  }
}
```
```bash
mkdir -p ~/.postgresql && curl -so ~/.postgresql/root.crt https://storage.yandexcloud.net/cloud-certs/CA.pem
psql "host=c-<cluster_id>.rw.mdb.yandexcloud.net port=6432 dbname=linkd user=linkd sslmode=verify-full"
yc managed-postgresql cluster list-hosts linkd-pg      # роли MASTER/REPLICA и зоны
yc managed-postgresql cluster list-backups linkd-pg
```
Пользователи и базы — отдельными ресурсами (`yandex_mdb_postgresql_user`,
`yandex_mdb_postgresql_database`); пароль — из Lockbox, не в `.tfvars`.

---

## 8. Object Storage через S3 API и Lockbox

**Object Storage** говорит на S3 API ([04_s3_storage.md](/cloud/04-s3-storage)): те же `aws s3`,
`boto3`, `rclone`, `restic`, но со своим endpoint и статическим ключом SA.
```bash
aws configure --profile yc          # key_id / secret из `yc iam access-key create`, region ru-central1
aws --profile yc --endpoint-url https://storage.yandexcloud.net s3 mb s3://linkd-backups
aws --profile yc --endpoint-url https://storage.yandexcloud.net s3 cp dump.sql.gz s3://linkd-backups/pg/
# регион Казахстан: --endpoint-url https://storage.yandexcloud.kz (регион подписи — проверь в документации)
```
Бакеты — **глобальный ресурс** региона (не зональный), доступ по ACL/bucket policy и ролям.
Стейт Terraform в Object Storage — см. [«03. State и backend»](/terraform/03-state-backend).

**Lockbox** — секреты с версиями (аналог Secrets Manager). Доступ к содержимому — роль
`lockbox.payloadViewer` **на конкретный секрет**; шифрование ключом KMS — опционально.
```bash
yc lockbox secret create --name linkd-db \
  --payload '[{"key":"password","text_value":"'"$(openssl rand -base64 24)"'"}]'
yc lockbox secret add-access-binding --name linkd-db \
  --service-account-name eso --role lockbox.payloadViewer
yc lockbox payload get --name linkd-db --key password
```
В k8s — External Secrets Operator: `SecretStore` с провайдером `yandexlockbox`, а
`ExternalSecret` ссылается на ID секрета и ключ (`remoteRef: { key: <secret-id>, property: password }`):
```yaml
apiVersion: external-secrets.io/v1
kind: SecretStore
metadata: { name: lockbox, namespace: linkd }
spec:
  provider:
    yandexlockbox:
      auth:
        authorizedKeySecretRef: { name: yc-auth, key: authorized-key }   # авторизованный ключ SA `eso`
```
Lockbox или [Vault](/vault/) — сравнение: Lockbox проще и
не требует эксплуатации, Vault даёт динамические секреты и работает в любом облаке.

---

## 9. Monitoring, Logging, Audit Trails

| Сервис | Что делает | Практика |
|--------|-----------|----------|
| Monitoring | Метрики сервисов облака, дашборды, алерты; есть приём метрик в формате Prometheus | Метрики managed-сервисов берут отсюда, основное — свой Prometheus/Grafana ([/monitoring/](/monitoring/)) |
| Cloud Logging | Лог-группы с retention; логи мастера k8s, ALB, своих приложений | Задать retention; ПДн в логах — это ПДн |
| Audit Trails | Кто что сделал в API облака (аналог CloudTrail) | Трейл на организацию в бакет/лог-группу в отдельном каталоге |

---

## 10. Деньги

- Тарифицируется то же, что везде ([01](/cloud/01-cloud-models), §3): vCPU/RAM (с `core_fraction`
  и прерываемые — дешевле), диски, **публичные IP** (и зарезервированные неиспользуемые),
  исходящий трафик, NAT, балансировщики, мастер k8s, хосты managed-баз.
- Бюджеты только уведомляют, ресурсы не останавливают; автоматика — триггер «Бюджет» для
  Cloud Functions (FinOps/05, §6), но в регионе Казахстан
  функций нет — там автоматику делают иначе (скрипт по расписанию в CI).
- Старт: для резидентов РК есть стартовый грант на 60 дней — не меньше 38 400 ₸ для личного
  аккаунта и для бизнеса с оплатой картой (без GPU, Postbox, платной поддержки и Marketplace),
  80 000 ₸ для бизнеса с оплатой банковским переводом. Отдельно от гранта есть «пробный период» —
  только для юрлиц с оплатой переводом, его условия видны в консоли
  ([грант](https://yandex.cloud/ru-kz/docs/getting-started/usage-grant),
  [пробный период](https://yandex.cloud/ru-kz/docs/billing/concepts/trial-period); проверь на момент регистрации).
- Счёт в регионе Казахстан — в тенге: валютного риска и конвертации меньше, чем с AWS.

---

## 11. Соответствие AWS ↔ Yandex Cloud

| AWS | Yandex Cloud | Отличие, о котором помнить |
|-----|--------------|----------------------------|
| Organizations / аккаунт | Организация / облако / каталог | Роли назначаются на ресурс и наследуются вниз |
| IAM role + policy JSON | SA + роль на ресурс | Нет JSON-политик с условиями — гранулярность через «на какой ресурс» |
| Identity Center | Федерации удостоверений в организации | SAML/OIDC от своего IdP |
| OIDC provider + `AssumeRoleWithWebIdentity` | Workload identity federation | Обмен через `auth.yandex.cloud/oauth/token` |
| Instance profile | SA, привязанный к ВМ | Токен из metadata |
| EKS Pod Identity / IRSA | WLIF для Managed Kubernetes | Обмен токена — в коде или sidecar |
| VPC + NAT Gateway | Сеть (глобальная в регионе) + NAT gateway через route table | Подсеть — в зоне в обоих случаях |
| Launch Template + ASG; ALB / NLB | Instance group; ALB / NLB | Instance group — один ресурс со своим SA |
| EKS | Managed Service for Kubernetes | Каналы обновлений, версии позже |
| ECR | Container Registry (`cr.yandex`, `cr.yandexcloud.kz`) | Pull по роли SA узлов |
| RDS PostgreSQL | Managed PostgreSQL | Порт 6432, особые FQDN `c-<id>.rw` |
| S3 | Object Storage | S3 API, свой endpoint и статический ключ |
| Secrets Manager | Lockbox | ESO через авторизованный ключ |
| CloudWatch / CloudTrail | Monitoring + Cloud Logging / Audit Trails | — |
| Регион в КЗ | ❌ нет | ✅ `kz1`, одна зона |

---

## 🧪 Мини-лаба: instance group за ALB, бакет и секрет, уборка

> Прерываемые ВМ с `core_fraction = 20` и маленькие диски — копейки в час; ALB и NAT тарифицируются
> почасово. Сначала бюджет в Billing (консоль), потом ресурсы.

```bash
# 0. Профиль и каталог для лабы
yc resource-manager folder create --name lab && yc config set folder-name lab

# 1. Сеть, NAT, SG, SA группы с ролями compute.editor + alb.editor, instance group (§4–5)
#    + ALB (backend group на target group web-tg, HTTP-роутер, listener :80) → ~/labs/yc-ig/main.tf
cd ~/labs/yc-ig && terraform init && terraform apply

# 2. Балансировка и самоизлечение
ALB_IP=$(yc application-load-balancer load-balancer get web-alb --format json \
  | jq -r '.listeners[0].endpoints[0].addresses[0].external_ipv4_address.address')
for i in $(seq 1 6); do curl -s "http://$ALB_IP/healthz"; done
yc compute instance-group list-instances --name web          # остановим одну ВМ
yc compute instance stop <instance-id> && sleep 60 && yc compute instance-group list-instances --name web

# 3. Object Storage через S3 API
yc iam service-account create --name lab-s3
yc iam access-key create --service-account-name lab-s3        # key_id + secret → aws configure --profile yc
aws --profile yc --endpoint-url https://storage.yandexcloud.net s3 mb s3://lab-<уникальное-имя>
# ⚠️ роль/грант SA на бакет выдай сам (§2) и проверь, что без него — AccessDenied

# 4. Lockbox
yc lockbox secret create --name lab-secret --payload '[{"key":"token","text_value":"s3cr3t"}]'
yc lockbox payload get --name lab-secret

# 5. ⭐ Уборка
terraform destroy
aws --profile yc --endpoint-url https://storage.yandexcloud.net s3 rb s3://lab-<имя> --force
yc lockbox secret delete --name lab-secret
yc iam service-account delete --name lab-s3
yc vpc address list; yc compute disk list; yc compute instance list   # должно быть пусто
```
Расширение: Managed Kubernetes (§6) + push образа в Container Registry + под, читающий
Lockbox через workload identity federation (§3), — и сразу `terraform destroy`.

---

## 12. Грабли

| Грабля | Последствие | Правильно |
|--------|-------------|-----------|
| `editor` сервисному аккаунту на всё облако | Утечка ключа = всё облако | Сервисная роль на каталог или ресурс |
| Статический ключ в `.env` и в CI | Вечный ключ утекает | WLIF для CI; ключ — в Lockbox/Vault с ротацией |
| Все ресурсы в одной зоне «пока» | Отказ зоны кладёт сервис | Зоны `a`/`b`/`d`; в Казахстане — DR на второй площадке |
| Думать, что регион KZ = те же сервисы | Нет Functions, Managed GitLab, DDoS Protection | Сверить таблицу сервисов **до** архитектуры |
| Прерываемые ВМ в проде с состоянием | Остановка раз в сутки или раньше | Только stateless/учёба; прод — обычные |
| Нет `depends_on` на роли SA кластера | `destroy` зависает: роли снялись раньше кластера | `depends_on` на IAM-ресурсы |
| Подключение к PG по FQDN хоста | После failover пишешь в реплику | `c-<id>.rw.…` |
| Бэкап PG только встроенный | Удалили кластер — через 7 дней бэкапов нет | Дамп/WAL-G в отдельный бакет, проверка восстановления |
| `cr.yandex` в манифестах для региона KZ | Образы не тянутся | `cr.yandexcloud.kz` |

---

## 💼 Как это в DevOps

- Структура «облако на prod, облако на non-prod, каталоги по окружениям/командам» — то же,
  что аккаунты в AWS: граница прав и денег.
- Всё — в Terraform провайдером `yandex-cloud/yandex` (сентябрь 2026 — v0.230); в CI — через
  workload identity federation, а не через ключ в переменной.
- Для казахстанских проектов первый вопрос: регион `kz1` и его ограничения (одна зона, урезанный
  набор сервисов) против требований проекта — это решение архитектора, а не «куда проще».
- В собесах в СНГ часто спрашивают про Yandex Cloud: каталоги и роли, SA и ключи, instance
  groups, Managed Kubernetes, особые FQDN PostgreSQL, S3 API с endpoint.

---

## 📌 Шпаргалка

| Хочу | Команда |
|------|---------|
| Профиль, регион KZ | `yc init`, `yc init --region=kz`, `yc config list` |
| SA и роль на каталог | `yc iam service-account create --name …` · `yc resource-manager folder add-access-binding <id> --role … --subject serviceAccount:<sa-id>` |
| Ключи SA | `yc iam access-key create` (S3) · `yc iam key create --output key.json` (авторизованный) |
| IAM-токен | `yc iam create-token` |
| Федерация для CI | `yc iam workload-identity oidc federation create …` + `federated-credential create …` |
| Вход на ВМ | `yc compute ssh --name <vm>` |
| Kubeconfig | `yc managed-kubernetes cluster get-credentials <c> --external` |
| Docker → registry | `yc container registry configure-docker` |
| Хосты PG | `yc managed-postgresql cluster list-hosts <c>` |
| S3 API | `aws --endpoint-url https://storage.yandexcloud.net s3 …` (KZ: `storage.yandexcloud.kz`) |
| Секрет | `yc lockbox payload get --name <s> --key <k>` |

---

## 🧠 Что запомнить

1. Иерархия: организация → облако → каталог → ресурс; роли назначаются на ресурс и наследуются вниз.
2. Регион выбирается консолью: Россия (`ru-central1`, несколько зон) и Казахстан (`kz1`, одна
   зона `kz1-a`, свой биллинг в тенге, свои endpoint'ы `*.yandexcloud.kz`).
3. В регионе Казахстан нет части сервисов (Functions, Serverless Containers, Managed GitLab,
   DDoS Protection) — сверяй до архитектуры.
4. Одна зона в KZ: HA внутри региона — только от отказа хоста; DR — вторая площадка в Казахстане.
5. Сервисным аккаунтам — сервисные роли на конкретный ресурс, не `editor` на облако.
6. Лучший ключ — IAM-токен из metadata ВМ или через workload identity federation; статический
   ключ — только для S3 API и под ротацию.
7. Instance group = шаблон + автоскейлинг + health check + интеграция с NLB/ALB, от имени своего SA.
8. Managed Kubernetes: два SA (кластера и узлов), каналы обновлений, версии позже upstream.
9. Managed PostgreSQL: порт 6432, `c-<id>.rw` для записи, PITR в новый кластер, бэкапы после
   удаления живут 7 дней.
10. Object Storage — S3 API со своим endpoint; Lockbox — секреты с доступом на уровне секрета.

---

## Задачи

> ⚠️ Бюджет с уведомлением — до ресурсов. NAT, ALB, мастер k8s, хосты PostgreSQL и публичные
> IP тарифицируются почасово. Для учёбы — прерываемые ВМ с `core_fraction = 20`.

---

### Блок A. Теория

**A1.** Организация, облако, каталог — что из этого граница биллинга, а что — просто
группировка ресурсов?

<details><summary>Ответ</summary>

Облако — граница биллинга (привязка к платёжному аккаунту) и прав верхнего уровня;
каталог — группировка ресурсов и прав внутри облака; организация — пользователи, федерации,
группы, объединяет облака.

</details>

**A2.** Как наследуются роли в Yandex Cloud и чем это опасно?

<details><summary>Ответ</summary>

Роль, назначенная на организацию/облако/каталог, действует на всё, что ниже. `editor`
на облако — это `editor` во всех его каталогах и на все ресурсы, включая будущие.

</details>

**A3.** Чем примитивные роли (`viewer`, `editor`, `admin`, `auditor`) отличаются от сервисных?
Кому что выдавать?

<details><summary>Ответ</summary>

Примитивные дают права сразу на все сервисы (`auditor` — метаданные без данных,
`viewer` — чтение, `editor` — изменение, `admin` — плюс управление доступом). Сервисные — на
один сервис и узкое действие. Людям — `viewer`/`auditor`, изменения через пайплайн; SA —
только сервисные роли на нужный ресурс.

</details>

**A4.** ⭐ Перечисли типы учётных данных сервисного аккаунта и где каждый нужен.

<details><summary>Ответ</summary>

IAM-токен (до 12 часов, почти все API); авторизованный ключ (из него подписывают JWT
и получают IAM-токен — Terraform/софт вне облака, ESO); статический ключ доступа (S3 API
Object Storage, YDB; можно выпускать временные ключи); API-ключ (сервисы без IAM-токенов,
с ограничением scope и срока).

</details>

**A5.** Как ВМ получает права без ключей? Откуда берётся токен?

<details><summary>Ответ</summary>

К ВМ привязывается SA; сервис метаданных внутри ВМ отдаёт короткоживущий IAM-токен
этого SA. Ключи на диске не нужны.

</details>

**A6.** Как устроена workload identity federation и что в ней играет роль «условия по `sub`»
из AWS?

<details><summary>Ответ</summary>

Федерация хранит issuer, audience и JWKS внешнего OIDC-провайдера; federated credential
связывает SA с конкретным external subject (значение `sub` из JWT). Именно external subject
(`project_path:…:ref:main`, `system:serviceaccount:ns:sa`) ограничивает, кто получит токен SA.

</details>

**A7.** Чем регион Казахстан отличается от региона Россия (минимум пять пунктов)?

<details><summary>Ответ</summary>

Отдельная консоль, биллинг и оплата в тенге; свои endpoint'ы (`*.yandexcloud.kz`,
`cr.yandexcloud.kz`); одна зона `kz1-a`; урезанный набор сервисов (нет Functions, Serverless
Containers, Managed GitLab, DDoS Protection и др.); данные не пересекают регионы; оператор —
казахстанское юрлицо, ЦОД в Караганде.

</details>

**A8.** ⭐ Почему одна зона `kz1-a` — архитектурное ограничение? Что можно и нельзя сделать
с HA внутри региона?

<details><summary>Ответ</summary>

Всё физически в одном ЦОД: HA-мастер k8s (3 хоста) и несколько хостов PostgreSQL
защищают от отказа хоста или стойки, но не площадки. Мультизонный failover внутри региона
невозможен; для DR нужна вторая площадка — для ПДн граждан РК тоже в Казахстане.

</details>

**A9.** Как в Yandex Cloud приватная подсеть получает выход в интернет?

<details><summary>Ответ</summary>

NAT gateway (`shared_egress_gateway`) + route table с маршрутом `0.0.0.0/0` на шлюз,
привязанная к подсети. Альтернатива — NAT-инстанс или публичный IP у ВМ.

</details>

**A10.** Что такое `predefined_target = "loadbalancer_healthchecks"` и `self_security_group`?

<details><summary>Ответ</summary>

Специальные источники в правилах SG: диапазоны, с которых приходят health check'и
балансировщиков (без этого правила цели будут `UNHEALTHY`), и «эта же группа» — трафик между
участниками одной SG.

</details>

**A11.** Instance group: какие роли нужны её сервисному аккаунту и зачем?

<details><summary>Ответ</summary>

`compute.editor` на каталог — создавать, менять и удалять ВМ; `load-balancer.editor` —
для интеграции с NLB; `alb.editor` — с ALB. Если ВМ группы получают свой SA, нужно право
его использовать.

</details>

**A12.** Что означают `max_unavailable` и `max_expansion` в `deploy_policy`?

<details><summary>Ответ</summary>

`max_unavailable` — сколько ВМ можно одновременно вывести при обновлении;
`max_expansion` — на сколько ВМ можно временно превысить размер группы.
`max_unavailable = 1, max_expansion = 0` — «убрать одну старую, создать новую» (дешевле, но на
время ВМ меньше); `max_unavailable = 0, max_expansion = 1` — «сначала новая, потом удалить старую»
(ёмкость не проседает).

</details>

**A13.** Прерываемые ВМ: что это, сколько живут, где уместны?

<details><summary>Ответ</summary>

ВМ, которую облако может остановить в любой момент и гарантированно не позже чем
через 24 часа; в разы дешевле. Учёба, CI-раннеры, batch, stateless-ноды с запасом.

</details>

**A14.** Каналы обновлений Managed Kubernetes: чем отличаются, можно ли сменить канал?

<details><summary>Ответ</summary>

`RAPID` — первым получает обновления, автообновления не выключить; `REGULAR` — позже;
`STABLE` — ещё позже. Канал задаётся при создании и не меняется — только пересоздание кластера.

</details>

**A15.** Зачем кластеру Managed Kubernetes два сервисных аккаунта и какие у них роли?

<details><summary>Ответ</summary>

SA кластера — от его имени сервис управляет узлами, подсетями, дисками,
балансировщиками (`k8s.clusters.agent`, плюс `vpc.publicAdmin` для публичного доступа).
SA узлов — чтобы узлы тянули образы из Container Registry (`container-registry.images.puller`).

</details>

**A16.** Managed PostgreSQL: как подключаться, чтобы после failover писать в мастер?

<details><summary>Ответ</summary>

По особому FQDN `c-<cluster_id>.rw.mdb.yandexcloud.net:6432` — он всегда указывает
на текущий мастер; `c-<id>.ro…` — на самую свежую реплику. TLS с `verify-full` и корневым
сертификатом Yandex Cloud.

</details>

**A17.** Что происходит с бэкапами Managed PostgreSQL после удаления кластера?

<details><summary>Ответ</summary>

Все бэкапы (включая ручные) хранятся ещё 7 дней бесплатно, потом удаляются. Для
долгого хранения нужна своя копия.

</details>

**A18.** Как работать с Object Storage из `aws` CLI и чем это отличается от AWS S3?

<details><summary>Ответ</summary>

`aws --endpoint-url https://storage.yandexcloud.net s3 …` (в KZ — `storage.yandexcloud.kz`)
со статическим ключом SA и регионом `ru-central1`. Команды те же; права — через роли
IAM/ACL/bucket policy Yandex Cloud, а не IAM AWS.

</details>

---

### Блок B. «Оцени конфигурацию»

```text:no-line-numbers
B1.  SA ci-deployer: роль editor на облако linkd-prod
B2.  SA backup-writer: storage.uploader на каталог prod, в котором 12 бакетов
B3.  Статический ключ SA лежит в .gitlab-ci.yml переменной без Protected/Masked
B4.  Федерация GitLab: external subject "project_path:acme/linkd:ref_type:branch:ref:*"
B5.  Прод-ВМ с динамическим публичным IP, адрес прописан в DNS
B6.  Подсети только в ru-central1-a, "потом добавим"
B7.  Instance group: scheduling_policy { preemptible = true }, в группе — PostgreSQL на ВМ
B8.  deploy_policy { max_unavailable = 2, max_expansion = 0 } при fixed_scale size = 2
B9.  Кластер k8s: release_channel = "RAPID" для прода, auto_upgrade без окна
B10. yandex_kubernetes_cluster без depends_on на IAM-роли своих SA
B11. Приложение подключается к rc1a-xxxx.mdb.yandexcloud.net:6432
B12. Проект для казахстанского банка: регион kz1, Cloud Functions для обработки событий
B13. Деплой в регион KZ: image: cr.yandex/crp123/linkd:1.4.2
B14. Lockbox: lockbox.payloadViewer для SA eso на каталог prod
B15. Managed PostgreSQL: backup_retain_period_days = 7, других копий нет
```

<details><summary>Ответ</summary>

**B1.** Слишком широко: утечка = всё облако. Сервисные роли на нужный каталог, CI — через WLIF.
**B2.** Пишет во все 12 бакетов. Права на конкретный бакет (ACL/bucket policy) или отдельный каталог.
**B3.** Ключ увидит любой, кто видит проект, и попадёт в логи. Убрать, отозвать, перейти на WLIF.
**B4.** Звёздочка — токен получит любая ветка, включая фичевые из MR. Только `ref:main`
(и protected).
**B5.** Динамический IP сменится после остановки ВМ — DNS укажет в никуда. Статический IP
на балансировщике, у ВМ — без публичного адреса.
**B6.** Одна зона — единая точка отказа; зоны `a`, `b`, `d`.
**B7.** База на прерываемой ВМ — остановка минимум раз в сутки. Для БД — обычные ВМ или managed.
**B8.** Обновление может вывести обе ВМ сразу — простой. `max_unavailable = 1` или
`max_expansion = 1`.
**B9.** Прод на самых свежих изменениях и обновления в любое время. `STABLE`/`REGULAR` и окно
обслуживания.
**B10.** При `destroy` роли SA могут сняться раньше кластера — удаление повиснет. Нужен `depends_on`.
**B11.** FQDN конкретного хоста: после failover это может быть реплика. `c-<id>.rw…`.
**B12.** Cloud Functions в регионе Казахстан нет. Обработку событий — в k8s (KEDA, очередь
Message Queue/Kafka) или на ВМ.
**B13.** Для KZ-региона реестр — `cr.yandexcloud.kz`; `cr.yandex` — российский регион, данные
там другие.
**B14.** Доступ ко всем секретам каталога. Роль на конкретный секрет.
**B15.** Встроенные бэкапы живут 7 дней и исчезают вместе с кластером через неделю после
удаления. Нужны независимые копии (дамп/WAL-G в отдельный бакет, для ПДн — в КЗ) и проверка
восстановления.

</details>

---

### Блок C. Практика

#### C1. 🔑 Структура
Создай каталоги `lab-prod` и `lab-dev` (или хотя бы один `lab`), профиль `yc` на каталог.
Выдай своему SA роль `viewer` на каталог и проверь `yc resource-manager folder list-access-bindings`.

#### C2. Ключи
Для SA `lab-s3` выпусти статический ключ, для `lab-tf` — авторизованный. Запиши, где и сколько
живёт каждый. Удали оба ключа и убедись, что доступ пропал.

#### C3. ВМ с SA без ключей
Создай ВМ с привязанным SA (роль `storage.viewer`). Изнутри ВМ получи IAM-токен из metadata
(`curl -H Metadata-Flavor:Google http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token`)
и сделай им запрос к API.

<details><summary>Ответ</summary>

Ответ metadata содержит `access_token` и `expires_in` — токен короткоживущий,
обновляется сам.

</details>

#### C4. 🔑 Сеть
Terraform: сеть, три private-подсети в `a`/`b`/`d`, NAT gateway через route table, SG «от группы
к группе». На ВМ без публичного IP проверь `curl ifconfig.me` — чей адрес виден?

<details><summary>Ответ</summary>

Виден адрес NAT gateway, а не ВМ (у неё публичного адреса нет).

</details>

#### C5. Instance group за ALB
Instance group на 2 ВМ в двух зонах с health check `/healthz`, ALB перед ней. Останови одну
ВМ — посмотри, как группа её восстановит. Поменяй cloud-init — посмотри раскатку по
`deploy_policy`.

<details><summary>Ответ</summary>

Остановленная ВМ будет перезапущена или пересоздана группой; при изменении шаблона
ВМ обновляются по одной согласно `deploy_policy`.

</details>

#### C6. 🔑 Managed Kubernetes + registry
Кластер (зональный мастер, `STABLE`), группа узлов из прерываемых ВМ, Container Registry.
Собери образ, запушь в `cr.yandex/<id>/…`, задеплой без `imagePullSecrets`.

<details><summary>Ответ</summary>

Pull проходит без `imagePullSecrets`, потому что SA узлов имеет
`container-registry.images.puller`.

</details>

#### C7. WLIF для GitLab CI
Создай федерацию `gitlab` и federated credential для своего проекта и ветки `main`. В джобе
обменяй `id_tokens` на IAM-токен и выполни `yc resource-manager folder list` (через `YC_TOKEN`).
Проверь, что из другой ветки обмен не проходит.

<details><summary>Ответ</summary>

Из другой ветки `sub` в JWT другой — federated credential не совпадает, обмен
возвращает ошибку.

</details>

#### C8. Managed PostgreSQL (платно)
Кластер из двух хостов в разных зонах. Подключись по `c-<id>.rw…:6432` с `verify-full`,
вручную переключи мастер (`yc managed-postgresql cluster start-failover`), проверь, что
подключение по `rw` снова пишет.

<details><summary>Ответ</summary>

После переключения `list-hosts` показывает новый MASTER; подключение по `rw`
после переподключения снова пишет, по FQDN старого хоста — уже нет.

</details>

#### C9. S3 API и Lockbox
Через `aws --endpoint-url` создай бакет, положи файл, включи версионирование. Положи пароль
в Lockbox и вытащи его через ESO в Secret k8s.

#### C10. Регион Казахстан (если есть доступ)
Создай профиль `yc init --region=kz`, выпиши endpoint'ы (API, storage, registry) и сверь
по таблице сервисов, чего нет из того, что ты использовал в C1–C9.

<details><summary>Ответ</summary>

Типичный вывод: нет Cloud Functions/Serverless Containers (триггеры бюджета,
обработчики событий), нет Managed GitLab, одна зона — мультизонные схемы не переносятся.

</details>

---

### Блок D. Инциденты

**D1.** Утёк статический ключ SA `backup-writer` (нашли в публичном репо). Порядок действий.

<details><summary>Ответ</summary>

Сразу удалить ключ (`yc iam access-key delete`), выпустить новый только если без него
никак, проверить Audit Trails и логи бакета на использование ключа, оценить, что было доступно
(данные с ПДн → процедура уведомления, Security/07),
убрать ключ из истории репо, перейти на WLIF.

</details>

**D2.** `terraform destroy` кластера Managed Kubernetes висит, а потом падает с ошибкой прав.

<details><summary>Ответ</summary>

Роли SA кластера сняты раньше кластера (нет `depends_on`) — сервис не может удалить
узлы и балансировщики. Вернуть роли, удалить кластер, добавить `depends_on`.

</details>

**D3.** Поды в Managed Kubernetes в `ImagePullBackOff` на образах из Container Registry.
Что проверить?

<details><summary>Ответ</summary>

Роль `container-registry.images.puller` у SA **узлов** (не кластера); правильный
адрес реестра (`cr.yandex` vs `cr.yandexcloud.kz`); существует ли тег; выход узлов в интернет
или доступ к реестру; политики доступа на реестре.

</details>

**D4.** После failover PostgreSQL приложение пишет с ошибкой `read-only transaction`.

<details><summary>Ответ</summary>

Приложение держит соединение (или DNS-кэш) к старому мастеру, ставшему репликой, или
подключается по FQDN хоста. Особый FQDN `rw`, переподключение при ошибке, короткий DNS-кэш.

</details>

**D5.** Все ВМ в приватных подсетях потеряли доступ в интернет после «чистки» ресурсов.

<details><summary>Ответ</summary>

Удалили NAT gateway или route table / отвязали её от подсетей. Восстановить Terraform'ом,
закрыть ручные удаления.

</details>

**D6.** Балансировщик показывает все цели `UNHEALTHY`, хотя nginx отвечает с ВМ локально.

<details><summary>Ответ</summary>

SG целей не пускает health check'и: нет правила с `loadbalancer_healthchecks`; либо
неверный порт/путь проверки, либо nginx слушает `127.0.0.1`.

</details>

**D7.** Прерываемые ноды k8s ночью разом ушли, сервис лёг на 10 минут.

<details><summary>Ответ</summary>

Прерываемые ВМ останавливаются массово при нехватке ресурсов и раз в сутки.
Смешанные группы узлов (часть обычных), PodDisruptionBudget, запас реплик, критичное — на
непрерываемых узлах.

</details>

**D8.** В регионе Казахстан отказал ЦОД, сервис и база недоступны. Что было не так в
архитектуре и как проектировать?

<details><summary>Ответ</summary>

Всё в одной зоне — отказ площадки = отказ сервиса. Для KZ-региона: вторая площадка
(другой провайдер или свой ЦОД в Казахстане) с репликой базы и бэкапами, IaC для быстрого
подъёма, DNS-переключение; RTO/RPO согласовать заранее ([10_kz_clouds.md](/cloud/10-kz-clouds)).

</details>

**D9.** Счёт вырос: «публичные IP-адреса» — 40 штук, половина не привязана.

<details><summary>Ответ</summary>

Неиспользуемые зарезервированные IP платные. `yc vpc address list`, удалить лишние;
для ВМ за балансировщиком публичные IP не нужны.

</details>

**D10.** Разработчик в `lab-dev` смог удалить бакет в `lab-prod`. Как такое возможно?

<details><summary>Ответ</summary>

Роль выдана на облако (наследуется во все каталоги) или на организацию. Роли — на
каталог, prod и dev — в разных облаках.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как устроена иерархия ресурсов и права в Yandex Cloud?

<details><summary>Ответ</summary>

Организация → облако → каталог → ресурс; роли назначаются субъекту на ресурс и наследуются
вниз; SA — identity программ.

</details>

**2.** Какие бывают ключи сервисного аккаунта и как обойтись без них?

<details><summary>Ответ</summary>

IAM-токен, авторизованный, статический, API-ключ; без них — SA на ВМ (токен из metadata)
и workload identity federation для CI и подов.

</details>

**3.** Как дать GitLab CI доступ в Yandex Cloud без секретов?

<details><summary>Ответ</summary>

Федерация с issuer GitLab, federated credential на SA с `sub` конкретного проекта и ветки,
в джобе `id_tokens` → обмен на IAM-токен в `auth.yandex.cloud/oauth/token`.

</details>

**4.** Как устроить сеть с приватными подсетями и выходом в интернет?

<details><summary>Ответ</summary>

Сеть глобальная, подсети по зонам; приватные подсети — NAT gateway через route table;
SG «от группы к группе» и правило для health check'ов.

</details>

**5.** Что такое instance group и чем она похожа на ASG?

<details><summary>Ответ</summary>

Шаблон ВМ + масштабирование + health check + политика раскатки + интеграция с NLB/ALB,
работает от своего SA — это Launch Template и ASG в одном ресурсе.

</details>

**6.** Как устроен Managed Kubernetes: мастер, узлы, SA, каналы?

<details><summary>Ответ</summary>

Мастер (базовый или HA из 3 хостов), группы узлов, SA кластера и узлов, каналы
RAPID/REGULAR/STABLE, минорные обновления вручную по одной.

</details>

**7.** Как подключаться к Managed PostgreSQL, чтобы переживать failover?

<details><summary>Ответ</summary>

Через `c-<id>.rw.mdb.yandexcloud.net:6432` с TLS, с переподключением в приложении.

</details>

**8.** Как работать с Object Storage инструментами AWS?

<details><summary>Ответ</summary>

`aws`/`boto3`/`rclone` со своим endpoint и статическим ключом SA; права — средствами
Yandex Cloud.

</details>

**9.** Чем регион Казахстан отличается от российского и как это влияет на архитектуру?

<details><summary>Ответ</summary>

Своя консоль, биллинг в тенге, endpoint'ы `.kz`, одна зона, меньше сервисов, данные
в Казахстане — HA внутри только от отказа хоста, DR — на другой казахстанской площадке.

</details>

**10.** Как перенести проект из AWS в Yandex Cloud: что соответствует чему?

<details><summary>Ответ</summary>

Account → облако/каталог, IAM role → SA + роль, OIDC → WLIF, ASG → instance group,
EKS → Managed Kubernetes, RDS → Managed PostgreSQL, S3 → Object Storage, Secrets Manager
→ Lockbox; Terraform-код переписывается, архитектура сохраняется.

</details>

---

### 🎯 Чек-лист

- [ ] Объясняю иерархию организация → облако → каталог и наследование ролей
- [ ] ⭐ Выдаю SA сервисные роли на конкретный ресурс, а не `editor` на облако
- [ ] Знаю типы ключей SA и когда без них можно обойтись
- [ ] Настроил workload identity federation для GitLab CI
- [ ] Собрал сеть с NAT gateway и security groups в Terraform
- [ ] Поднимал instance group за балансировщиком и видел самоизлечение
- [ ] ⭐ Поднимал Managed Kubernetes с Container Registry без `imagePullSecrets`
- [ ] Подключаюсь к Managed PostgreSQL через `c-<id>.rw` с TLS
- [ ] Работаю с Object Storage через `aws --endpoint-url` и с Lockbox
- [ ] Знаю отличия региона Казахстан: одна зона, endpoint'ы `.kz`, набор сервисов
