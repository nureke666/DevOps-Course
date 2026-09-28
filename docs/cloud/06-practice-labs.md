---
title: "06. Практика: 5 лаб по облакам"
description: "Пять практических лаб: первая ВМ, сеть проекта, объектное хранилище, managed-база, полный стенд — с командами для AWS, Yandex Cloud и облаков РК"
---

# 06. Практика: 5 лаб по облакам

> Роадмап → Облака. Цель лаб — пройти путь «первая ВМ → рабочая архитектура»
> и научиться убирать за собой, не потратив лишнего.
>
> Каждая лаба выполнима **либо в AWS** (Free plan: до 200 $ кредитов, до 6 месяцев),
> **либо в Yandex Cloud** (стартовый грант на 60 дней; для резидентов РК — в тенге).
> Команды даны для обоих CLI. Вариант для **провайдера РК** (PS Cloud, Kazteleport и др.)
> делается так же через его консоль или OpenStack API — отличия указаны в конце каждой лабы.
>
> 📅 Условия бесплатного старта и цены — **проверь, сентябрь 2026**.

> ⚠️ **Перед началом:** настрой бюджет и уведомления (AWS Budgets / бюджет в Yandex Billing).
> Ставь метку `lab=cloud-N` на всё, что создаёшь. После каждой лабы — **блок «Уборка»**
> и проверка счёта на следующий день.

---

## 📋 Список лаб

| № | Лаба | Что закрепляет | Артефакт | Примерная стоимость* |
|---|------|----------------|----------|----------------------|
| 1 | Первая ВМ и SSH | тема 02 | заметка с командами CLI | копейки при удалении в тот же день |
| 2 | ⭐ Сеть проекта: bastion, приватные ВМ, NAT | тема 03 | схема сети + security groups | NAT — самая дорогая часть, делать за один присест |
| 3 | Бэкапы и статика в объектном хранилище | тема 04 | скрипт бэкапа + бакет с lifecycle | почти ноль на малых объёмах |
| 4 | Managed-база + приложение | тема 05 | рабочее приложение с БД | managed-БД тикает почасово — удалить в тот же день |
| 5 | Полный стенд: балансировщик, две зоны, мониторинг | всё вместе | README с архитектурой и стоимостью | самая дорогая: LB + NAT + БД HA; уложиться в 1 день |

\* Порядок, а не цена: считай в калькуляторе провайдера (calculator.aws, калькулятор Yandex Cloud,
прайс провайдера РК) перед стартом. На кредитах/гранте ты платишь ими, но они тоже кончаются.

### 🧹 Универсальная проверка «ничего не осталось»

```bash
# AWS — ресурсы РЕГИОНАЛЬНЫ: повтори для каждого региона, где работал
aws ec2 describe-instances --filters Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query 'Reservations[].Instances[].[InstanceId,State.Name]' --output table
aws ec2 describe-volumes --query 'Volumes[].[VolumeId,State,Size]' --output table
aws ec2 describe-snapshots --owner-ids self --query 'Snapshots[].SnapshotId'
aws ec2 describe-addresses --query 'Addresses[].[PublicIp,AllocationId]'
aws ec2 describe-nat-gateways --filter Name=state,Values=available --query 'NatGateways[].NatGatewayId'
aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName'
aws rds describe-db-instances --query 'DBInstances[].DBInstanceIdentifier'
aws eks list-clusters
aws s3 ls

# Yandex Cloud (для kz1 — то же с профилем kz: yc --profile kz ...)
yc compute instance list
yc compute disk list
yc compute snapshot list
yc vpc address list
yc vpc gateway list
yc load-balancer network-load-balancer list
yc application-load-balancer load-balancer list
yc managed-postgresql cluster list
yc managed-kubernetes cluster list
yc storage bucket list
```

---

## 🧪 Лаба 1. Первая ВМ и доступ

### Требования
- [ ] Аккаунт, бюджет и уведомления настроены
- [ ] ВМ создана в консоли (Ubuntu, минимальная, прерываемая/spot)
- [ ] Доступ по SSH-ключу, вход по паролю отключён
- [ ] Та же ВМ создана командой CLI (команда сохранена в файл)
- [ ] Подключён дополнительный диск, смонтирован через fstab по UUID
- [ ] cloud-init ставит docker и создаёт пользователя
- [ ] Снят снапшот диска и восстановлен в новый диск
- [ ] Всё удалено, счёт проверен

### Команды

**Yandex Cloud:**
```bash
yc compute instance create --name lab1 --zone ru-central1-a \
  --cores 2 --memory 2 --core-fraction 20 --preemptible \
  --create-boot-disk image-family=ubuntu-2404-lts,size=20 \
  --network-interface subnet-name=default-ru-central1-a,nat-ip-version=ipv4 \
  --metadata-from-file user-data=cloud-init.yaml --labels lab=cloud-1
yc compute disk create --name lab1-data --size 10 --type network-hdd --zone ru-central1-a
yc compute instance attach-disk lab1 --disk-name lab1-data
yc compute snapshot create --name lab1-snap --disk-name lab1-data
yc compute disk create --name lab1-restored --source-snapshot-name lab1-snap --zone ru-central1-a
```

**AWS:**
```bash
aws ec2 import-key-pair --key-name lab --public-key-material fileb://~/.ssh/cloud_ed25519.pub
AMI=$(aws ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
  --query Parameter.Value --output text)
aws ec2 run-instances --image-id "$AMI" --instance-type t3.micro --key-name lab \
  --security-group-ids "$SG_SSH" --user-data file://cloud-init.yaml \
  --metadata-options HttpTokens=required \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=lab,Value=cloud-1}]'
aws ec2 create-volume --availability-zone <зона ВМ> --size 10 --volume-type gp3
aws ec2 attach-volume --volume-id vol-... --instance-id i-... --device /dev/sdf   # в ВМ: /dev/nvme1n1
aws ec2 create-snapshot --volume-id vol-... --description lab1
aws ec2 create-volume --availability-zone <зона ВМ> --snapshot-id snap-...
```
Тип инстанса бери из помеченных «Free tier eligible» в консоли; `$SG_SSH` — группа
с 22/tcp только с твоего IP.

### Проверка
```bash
ssh app ' lsblk; df -h /data; docker ps; cloud-init status'
```

### 🧹 Уборка
```bash
# Yandex
yc compute instance delete lab1
yc compute disk delete lab1-data lab1-restored
yc compute snapshot delete lab1-snap
# AWS
aws ec2 terminate-instances --instance-ids i-...
aws ec2 delete-volume --volume-id vol-...          # оба диска (после detach/terminate)
aws ec2 delete-snapshot --snapshot-id snap-...
aws ec2 delete-key-pair --key-name lab
```

### 🇰🇿 Вариант в облаке РК
`openstack server create` / `volume create` / `volume snapshot create` или то же в консоли;
публичный адрес — floating IP (удали его отдельно!). Прерываемых ВМ обычно нет — удаляй сразу.

### Вопросы себе
- Сколько стоит эта ВМ в месяц при работе 24/7? А прерываемая?
- Что останется платным, если я её просто остановлю?

---

## 🧪 Лаба 2. ⭐ Сеть проекта

### Что делаем
Строим «взрослую» схему: наружу смотрит только то, что должно.

### Требования
- [ ] VPC с продуманным CIDR, схема записана в README
- [ ] Публичные подсети в двух зонах, приватные в двух зонах
- [ ] Bastion в публичной подсети, SSH ограничен твоим IP
- [ ] Две ВМ приложения в приватных подсетях (разные зоны), без публичных IP
- [ ] NAT-шлюз, приватные ВМ ходят в интернет
- [ ] Security groups: `bastion`, `app`, `db`, правила «от группы к группе»
- [ ] `~/.ssh/config` с `ProxyJump`, вход одной командой
- [ ] Проверено: прямой доступ к приватной ВМ невозможен

### Команды
Готовые последовательности — в [«03. Сети и VPC в облаке»](/cloud/03-network-vpc), разделы 1 и 2:
- **Yandex:** `yc vpc network create` → `yc vpc subnet create` ×4 → `yc vpc gateway create` →
  `yc vpc route-table create` → `yc vpc subnet update --route-table-name` →
  `yc vpc security-group create` ×3; bastion — ВМ с `nat-ip-version=ipv4`, остальные — без.
- **AWS:** `create-vpc` → `create-subnet` ×4 → IGW + публичная route table → EIP +
  `create-nat-gateway` + приватная route table → `create-security-group` ×3 +
  `authorize-security-group-ingress --source-group`; bastion — с `--associate-public-ip-address`.
- Сохрани команды в `network.sh` — это черновик будущего Terraform-кода.

### Проверка
```bash
ssh app-1 'curl -s ifconfig.me; echo; sudo apt-get update -qq && echo apt-ok'
nc -zv <private-ip> 22        # снаружи — таймаут
```

### 💰 Стоимость
NAT Gateway в AWS тарифицируется почасово и за каждый гигабайт (порядок — десятки $ в месяц
за один шлюз, проверь), плюс каждый публичный IPv4. NAT-шлюз Yandex и публичные адреса тоже
платные. Делай лабу за один присест и сноси NAT сразу.

### 🧹 Уборка (обратный порядок)
```bash
# Yandex
yc compute instance delete bastion app-1 app-2
yc vpc subnet delete public-a public-b app-a app-b      # подсети держат route table
yc vpc route-table delete via-nat && yc vpc gateway delete nat-gw
yc vpc security-group delete sg-bastion sg-app sg-db
yc vpc network delete study
# AWS
aws ec2 terminate-instances --instance-ids i-... i-... i-...
aws ec2 delete-nat-gateway --nat-gateway-id "$NAT" && aws ec2 wait nat-gateway-deleted --nat-gateway-ids "$NAT"
aws ec2 release-address --allocation-id "$EIP"
aws ec2 detach-internet-gateway --internet-gateway-id "$IGW" --vpc-id "$VPC"
aws ec2 delete-internet-gateway --internet-gateway-id "$IGW"
# затем: delete-security-group, delete-subnet ×4, delete-route-table ×2, delete-vpc
```

### 🇰🇿 Вариант в облаке РК
Модель Neutron: `network` + `subnet` + `router --external-gateway` (он и есть NAT) +
floating IP для bastion + security groups с `--remote-group`. В Yandex `kz1` — те же `yc`,
но все подсети в `kz1-a`: «две зоны» не получится, отметь это в README.

### Вопросы себе
- Что произойдёт, если удалить NAT-шлюз?
- Какие правила SG придётся менять при добавлении третьей ВМ приложения? (Правильный
  ответ — никакие.)

---

## 🧪 Лаба 3. Объектное хранилище: бэкапы и статика

### Требования
- [ ] Бакет `*-backups` (приватный) и `*-static`
- [ ] Сервисный аккаунт (Yandex) / IAM-роль или пользователь (AWS) с доступом только к нужным бакетам
- [ ] Скрипт бэкапа PostgreSQL прямо в бакет, ключ с датой
- [ ] Проверено восстановление из бэкапа в отдельную базу
- [ ] Включено версионирование на бакете бэкапов
- [ ] Учётка бэкапа не имеет права `DeleteObject`
- [ ] Lifecycle: холодный класс через 30 дней, удаление через 180,
      старые версии через 30, незавершённые загрузки через 7
- [ ] Статика выгружается `aws s3 sync --delete`, публично доступна только `static/`
- [ ] presigned URL для приватного файла проверен

### Команды
```bash
# Yandex: ключ сервисного аккаунта + endpoint
yc iam service-account create --name sa-backup
yc resource-manager folder add-access-binding <folder-id> --role storage.uploader \
  --subject serviceAccount:<sa-id>
yc iam access-key create --service-account-name sa-backup
E="--endpoint-url=https://storage.yandexcloud.net"      # kz1: https://storage.yandexcloud.kz
# AWS: E="" (endpoint не нужен), права — IAM-политика «PutObject/GetObject в db/*»

aws s3 $E mb s3://<prefix>-backups
aws s3api $E put-bucket-versioning --bucket <prefix>-backups --versioning-configuration Status=Enabled
aws s3api $E put-bucket-lifecycle-configuration --bucket <prefix>-backups \
  --lifecycle-configuration file://lifecycle.json    # Yandex: COLD/ICE, AWS: STANDARD_IA/GLACIER
```

### Проверка
```bash
aws s3 $E ls s3://<backups> --recursive --summarize | tail -3
aws s3 $E presign s3://<backups>/db/last.dump --expires-in 300
curl -I https://<static-endpoint>/static/index.html    # 200
curl -I https://<static-endpoint>/private/secret.txt   # 403
```

### 🧹 Уборка
⚠️ `aws s3 rb --force` удаляет только текущие объекты: в бакете с версионированием остаются
старые версии и delete marker'ы, и бакет не удалится. Очисти версии (в консоли AWS — кнопка
«Empty», в Yandex — удаление версий в консоли или скриптом по `list-object-versions`), затем:
```bash
aws s3 $E rb s3://<prefix>-backups --force
aws s3 $E rb s3://<prefix>-static --force
yc iam access-key list --service-account-name sa-backup   # удали ключи и SA
yc iam service-account delete sa-backup
```

### 🇰🇿 Вариант в облаке РК
Те же `aws s3`/`rclone` с endpoint'ом S3 провайдера и ключами из его консоли. Сначала проверь
в документации, поддерживаются ли версии, lifecycle и presigned URL. ⭐ Для реальных ПДн —
бэкапы только в хранилище в РК.

### Вопросы себе
- Что произойдёт с моими бэкапами, если прод-сервер взломают?
- Сколько будет стоить хранение через год при текущем темпе?

---

## 🧪 Лаба 4. Managed-база и приложение

### Требования
- [ ] Managed PostgreSQL в приватной подсети, доступ только от `sg-app`
- [ ] Подключение по TLS (`sslmode=verify-full`)
- [ ] Отдельные роли: владелец (миграции) и приложение (только DML)
- [ ] Приложение из лабы 2 работает с этой базой
- [ ] Настроены бэкапы; выполнено пробное восстановление в новый кластер
- [ ] Подключён `postgres_exporter`, есть 3 алерта
- [ ] Проверено поведение приложения при разрыве соединения
- [ ] Записаны ограничения: чего в managed нельзя

### Команды
Полные команды — в [«05. Managed-сервисы»](/cloud/05-managed-services), раздел 2:
- **Yandex:** `yc managed-postgresql cluster create` с одним хостом `s2.micro`;
  второй хост в другой зоне добавь на этапе проверки HA (консоль или `yc managed-postgresql --help`).
- **AWS:** `aws rds create-db-subnet-group` + `aws rds create-db-instance --db-instance-class db.t4g.micro
  --no-publicly-accessible --manage-master-user-password`; `--multi-az` — только на время проверки
  failover (удваивает цену).

### 💰 Стоимость
Managed-БД тарифицируется почасово, пока существует (даже без нагрузки), плюс диск и бэкапы.
Проверь, что покрывают кредиты AWS Free plan / грант Yandex для выбранного класса.

### 🧹 Уборка
```bash
# Yandex (если включена защита от удаления — сначала сними её)
yc managed-postgresql cluster delete shop-pg
# AWS (на учебном стенде — без финального снапшота, в проде так НЕ делают)
aws rds delete-db-instance --db-instance-identifier shop-pg --skip-final-snapshot
aws rds wait db-instance-deleted --db-instance-identifier shop-pg
aws rds delete-db-subnet-group --db-subnet-group-name shop-db
aws rds describe-db-snapshots --snapshot-type manual     # удали ручные снапшоты
```

### 🇰🇿 Вариант в облаке РК
Если у провайдера есть managed PostgreSQL — то же через его консоль. Если нет — PostgreSQL
на ВМ в приватной подсети (это нормальная учебная альтернатива: сравни, сколько работы ушло).
В Yandex `kz1` — те же `yc managed-postgresql`, хосты только в `kz1-a`.

### Вопросы себе
- Сколько стоит HA-конфигурация против одного хоста?
- Что сломается в приложении при failover?

---

## 🧪 Лаба 5. Полный стенд

### Что делаем
Собираем минимальную «боевую» архитектуру и документируем её.

```text:no-line-numbers
        интернет
           │
     ┌─────▼─────┐  TLS, health-check /healthz
     │    LB     │
     └──┬─────┬──┘
   zone-a│     │zone-b
   ┌─────▼─┐ ┌─▼─────┐      ┌──────────────┐
   │ app-1 │ │ app-2 │─────►│ managed PG   │ (primary + реплика в другой зоне)
   └───┬───┘ └───┬───┘      └──────┬───────┘
       └────┬────┘                 │ бэкапы
            ▼                       ▼
      объектное хранилище (статика, бэкапы)
            ▲
      мониторинг: Prometheus + Grafana (из блока 02)
```

| Компонент | AWS | Yandex Cloud |
|-----------|-----|--------------|
| Балансировщик | ALB (подсети в 2 AZ) + ACM-сертификат | Application Load Balancer (или NLB) + Certificate Manager |
| Приложение | 2 × EC2 в разных AZ (или ASG) | 2 × ВМ в разных зонах (или Instance Group) |
| База | RDS PostgreSQL `--multi-az` | Managed PostgreSQL, 2 хоста в разных зонах |
| Хранилище | S3 | Object Storage |
| Доступ инженеров | SSM Session Manager или bastion | bastion или OS Login |

### Требования
- [ ] Балансировщик с health-check на реальный эндпоинт, TLS
- [ ] Приложение в двух зонах, автоматически переживает отключение одной ВМ
- [ ] База managed с репликой в другой зоне
- [ ] Статика и бэкапы в объектном хранилище
- [ ] Мониторинг: node_exporter, postgres_exporter, blackbox на внешний URL
- [ ] Алерты приходят в телеграм
- [ ] README: схема, адресация, security groups, стоимость в месяц, как поднять заново
- [ ] Проведено учение: погасили зону — сервис жив

### Критерии приёмки
```bash
curl -sI https://<домен>/healthz          # 200
# гасим app-1 → трафик идёт на app-2, алерт пришёл
# гасим зону a → сервис отвечает, база переключилась
```

### 💰 Стоимость
Самая дорогая лаба: балансировщик + NAT + HA-база + несколько ВМ тикают одновременно.
Посчитай в калькуляторе заранее, собери и разбери стенд в один день; лучше — сразу
через Terraform (тогда уборка — это `terraform destroy`).

### 🧹 Уборка
`terraform destroy` (если стенд в коде) → затем «Универсальная проверка» в начале файла.
Вручную — в порядке: балансировщик и target group → ВМ → база → NAT и адреса → бакеты
(с версиями) → подсети и сеть → сертификаты, DNS-записи, ключи и сервисные аккаунты.

### 🇰🇿 Вариант в облаке РК
Та же схема через консоль/OpenStack API провайдера: две площадки (у PS Cloud — Алматы
и Астана; у Kazteleport — несколько ЦОД в Алматы), балансировщик провайдера, managed-БД
или Patroni на ВМ. В Yandex `kz1` зона одна: учение «погасили зону» заменяется на
«погасили ВМ и хост базы» + восстановление из бэкапа на другой площадке в РК — запиши RTO.

### Вопросы себе
- Сколько времени займёт развернуть это с нуля в другом регионе?
- Что из этого я уже могу описать Terraform'ом? (Это ровно задача блока 06.)
- Какие данные этого стенда были бы ПДн, и где им разрешено лежать?

---

## 🏁 Что должно остаться после блока

```text:no-line-numbers
cloud/
├── cli-commands.md          # как создать ВМ, сеть, бакет командой — в yc И в aws
├── network-design.md        # CIDR, подсети, зоны, security groups
├── backup/
│   ├── db_backup.sh
│   └── restore-runbook.md
├── monitoring/              # экспортеры и алерты для облачных ресурсов
├── cleanup.md               # ⭐ как проверить, что ничего не осталось (оба облака)
├── cost.md                  # сколько стоит стенд и из чего складывается
└── README.md                # схема архитектуры + как поднять заново
```

⭐ И главный артефакт — привычка: **после каждой лабы удалять ресурсы и смотреть счёт**.
Это то, что отличает инженера, которому можно доверить прод-аккаунт.
