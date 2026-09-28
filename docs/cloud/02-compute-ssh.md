---
title: "02. Виртуальные машины и подключение по SSH"
description: "Создание ВМ через консоль/CLI, SSH-ключи и bastion, cloud-init, диски, метаданные и сервисные аккаунты — конспект и задачи"
---

# 02. Виртуальные машины и подключение по SSH

> Роадмап → 7. Остальное → Облака: *«Создать вмку в облаке, подключиться по SSH»*.
>
> **После темы ты умеешь:** создать ВМ через консоль и CLI (`aws` и `yc`), зайти по ключу,
> подключить и разметить диск, автоматизировать первоначальную настройку через cloud-init
> и понимать, из чего складывается стоимость машины.
>
> 📅 Типы машин, образы и цены — **проверь, сентябрь 2026**.

---

## 🗺️ Из чего состоит ВМ в облаке

```text:no-line-numbers
 ┌──────────────────────────────────────────────────────────────┐
 │ ВИРТУАЛЬНАЯ МАШИНА                                            │
 │  ├── образ (Ubuntu 24.04, Debian, свой)   ← ОС и её версия    │
 │  ├── тип/размер (2 vCPU, 4 ГБ)            ← производительность│
 │  ├── загрузочный диск (SSD/HDD, 20 ГБ)    ← ⚠️ платный всегда │
 │  ├── дополнительные диски                 ← данные отдельно    │
 │  ├── сетевой интерфейс в подсети VPC      ← приватный IP       │
 │  ├── публичный IP (опционально)           ← платный            │
 │  ├── security group / firewall            ← кто может подключиться│
 │  ├── SSH-ключ (или доступ через агента)   ← ⭐ не пароль!      │
 │  ├── сервисный аккаунт / роль             ← права ВМ в облаке  │
 │  └── cloud-init / user-data               ← автонастройка при старте│
 └──────────────────────────────────────────────────────────────┘
```

### Одни и те же сущности у трёх семейств

| Понятие | AWS | Yandex Cloud | Облака РК (OpenStack: PS Cloud, Kazteleport) |
|---------|-----|--------------|-----------------------------------------------|
| ВМ | EC2 instance | Compute Cloud instance | server (Nova) |
| Образ | AMI (ID свой в каждом регионе) | image / `image-family` | image (Glance) |
| Размер | instance type (`t3.micro`, `m7i.large`) | платформа + ядра + RAM + `core-fraction` | flavor |
| Загрузочный/доп. диск | EBS volume (`gp3`, `io2`, `st1`) | disk (`network-hdd`, `network-ssd`, …) | volume (Cinder) |
| Локальный быстрый диск | instance store (теряется при stop) | нереплицируемые диски — без избыточности | зависит от провайдера |
| Публичный IP | public IPv4 / Elastic IP | публичный адрес (one-to-one NAT), статический — отдельно | floating IP |
| Дешёвая прерываемая ВМ | Spot | прерываемая (`--preemptible`) | обычно нет — проверь |
| «Доля ядра» | burstable `t3/t4g` (CPU credits) | `--core-fraction 5/20/50` | обычно нет |
| SSH-ключ | key pair | `--ssh-key` или cloud-init | keypair |
| Права ВМ в облаке | IAM role + instance profile | сервисный аккаунт на ВМ | обычно нет аналога — ключи на ВМ ⚠️ |
| Метаданные | IMDSv2 `169.254.169.254` (с токеном) | `169.254.169.254` (формат GCE) | `169.254.169.254/openstack/...` |
| Доступ без SSH-порта | SSM Session Manager, EC2 Instance Connect | OS Login (`yc compute ssh`) | веб-консоль VNC |
| Serial console | EC2 Serial Console | `yc compute connect-to-serial-port` | консоль в веб-интерфейсе |
| Снапшот диска | EBS snapshot | snapshot | volume snapshot |

---

## 1. Создание ВМ: консоль → CLI → код

**Шаг 1 (руками, один раз):** создать ВМ в веб-консоли и пройти по всем полям —
это лучший способ понять, из чего состоит инстанс.

**Шаг 2 (CLI):** то же самое командой.

**Yandex Cloud:**
```bash
yc compute instance create \
  --name web-1 \
  --zone ru-central1-a \
  --platform standard-v3 \
  --cores 2 --memory 4 --core-fraction 20 \
  --create-boot-disk image-family=ubuntu-2404-lts,type=network-ssd,size=20 \
  --network-interface subnet-name=public-a,nat-ip-version=ipv4 \
  --metadata-from-file user-data=cloud-init.yaml \
  --preemptible                                  # ⭐ дешёвая прерываемая ВМ для учёбы
# вариант без cloud-init: --ssh-key ~/.ssh/cloud_ed25519.pub (пользователь будет yc-user)

yc compute instance list
yc compute instance get web-1 --format json | jq '.network_interfaces[0].primary_v4_address'
yc compute instance stop web-1 && yc compute instance delete web-1

# регион Казахстан: профиль `yc init --region=kz`, зона --zone kz1-a
# (доступные платформы и образы в kz1 смотри в консоли kz.console.yandex.cloud)
```

**AWS:**
```bash
# 1. ключ: загружаем ПУБЛИЧНУЮ часть
aws ec2 import-key-pair --key-name nurik-laptop \
  --public-key-material fileb://~/.ssh/cloud_ed25519.pub

# 2. актуальный AMI Ubuntu 24.04 — Canonical публикует ID в SSM Parameter Store
AMI=$(aws ssm get-parameter \
  --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
  --query Parameter.Value --output text)

# 3. ВМ
aws ec2 run-instances \
  --image-id "$AMI" \
  --instance-type t3.micro \
  --key-name nurik-laptop \
  --subnet-id subnet-0123456789abcdef0 \
  --security-group-ids sg-0123456789abcdef0 \
  --associate-public-ip-address \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=20,VolumeType=gp3}' \
  --user-data file://cloud-init.yaml \
  --metadata-options HttpTokens=required \
  --instance-market-options MarketType=spot \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=web-1},{Key=env,Value=study}]'

aws ec2 describe-instances --filters Name=tag:Name,Values=web-1 \
  --query 'Reservations[].Instances[].[InstanceId,State.Name,PublicIpAddress]' --output table
aws ec2 terminate-instances --instance-ids i-0123456789abcdef0
```

**OpenStack-облака РК** (PS Cloud и Kazteleport дают OpenStack API/CLI):
```bash
openstack keypair create --public-key ~/.ssh/cloud_ed25519.pub nurik-laptop
openstack server create --flavor <flavor> --image <ubuntu-24.04> \
  --network app-net --key-name nurik-laptop --security-group sg-web \
  --user-data cloud-init.yaml web-1
openstack floating ip create <external-net>             # публичный адрес
openstack server add floating ip web-1 <ip>
```
Имена flavor, образов и внешней сети у каждого провайдера свои — смотри
`openstack flavor list`, `openstack image list`, `openstack network list --external`.

**Шаг 3 (Terraform):** описать ВМ кодом — блок [«Terraform»](/terraform/).

---

## 2. SSH: ключи, а не пароли

```bash
# 1. создать ключ (на своей машине)
ssh-keygen -t ed25519 -C "nurik@laptop" -f ~/.ssh/cloud_ed25519

# 2. отдать ПУБЛИЧНУЮ часть облаку (в метаданных ВМ или в аккаунте)
cat ~/.ssh/cloud_ed25519.pub

# 3. подключиться
ssh -i ~/.ssh/cloud_ed25519 ubuntu@203.0.113.10
```
```text:no-line-numbers
Имя пользователя по умолчанию зависит от образа и способа передачи ключа:
  Ubuntu → ubuntu   Debian → debian   Rocky → rocky   Amazon Linux → ec2-user
  Yandex Cloud с --ssh-key → yc-user (или тот, кого создал в cloud-init)
```

`~/.ssh/config` — то, что экономит часы:
```text:no-line-numbers
Host bastion
    HostName 203.0.113.10
    User ubuntu
    IdentityFile ~/.ssh/cloud_ed25519

Host app-1
    HostName 10.0.1.15                  # приватный адрес
    User ubuntu
    IdentityFile ~/.ssh/cloud_ed25519
    ProxyJump bastion                   # ⭐ ходим внутрь через bastion
```
```bash
ssh app-1                 # и всё
scp file.tar.gz app-1:/tmp/
ssh -L 5432:10.0.2.10:5432 bastion      # локальный проброс порта к базе
```

Доступ **без открытого порта 22** — зрелый вариант:
```bash
# AWS: SSM Session Manager (на ВМ агент SSM + роль с AmazonSSMManagedInstanceCore)
aws ssm start-session --target i-0123456789abcdef0
# Yandex Cloud: OS Login — ключи и доступ управляются через IAM организации
yc compute ssh --name web-1
```

Гигиена доступа:
| Правило | Почему |
|---------|--------|
| Только ключи, `PasswordAuthentication no` | Пароли перебирают ботами через минуты после создания ВМ |
| Отдельный ключ на окружение/человека | Отзывать проще |
| SSH не открыт на `0.0.0.0/0` | Ограничение по IP или доступ только через bastion/VPN/SSM |
| Не пускать root напрямую | `PermitRootLogin no`, работать через `sudo` |
| Ключи людей — в облачном IAM (OS Login / SSM) | Централизованный отзыв при увольнении |
| Приватный ключ нигде не передаётся | Он остаётся только у владельца |

> ⚠️ Потерял SSH-доступ? Пути: serial console провайдера (EC2 Serial Console,
> `yc compute connect-to-serial-port`, VNC-консоль OpenStack), SSM Session Manager (AWS),
> временное добавление ключа через метаданные, монтирование диска к другой ВМ.
> Именно поэтому у ВМ должен быть способ восстановления доступа, известный заранее.

---

## 3. cloud-init: настройка при первом запуске

Один и тот же файл работает во всех трёх семействах: в AWS он передаётся как `--user-data`,
в Yandex Cloud — `--metadata-from-file user-data=...`, в OpenStack — `--user-data`.

```yaml
#cloud-config
users:
  - name: deploy
    groups: [sudo]
    shell: /bin/bash
    sudo: ['ALL=(ALL) NOPASSWD:ALL']
    ssh_authorized_keys:
      - ssh-ed25519 AAAAC3Nz... nurik@laptop

package_update: true
packages:
  - docker.io
  - docker-compose-plugin
  - htop

write_files:
  - path: /etc/ssh/sshd_config.d/99-hardening.conf
    content: |
      PasswordAuthentication no
      PermitRootLogin no

runcmd:
  - systemctl enable --now docker
  - usermod -aG docker deploy
  - systemctl restart ssh
```
```bash
# проверка на самой ВМ
cloud-init status --wait
sudo cat /var/log/cloud-init-output.log      # ⭐ сюда смотреть, если «ничего не применилось»
```

> 💡 cloud-init хорош для базовой подготовки («чтобы Ansible смог подключиться»).
> Всю конфигурацию в него не переносят — для этого есть [Ansible](/ansible/)
> и образы.
> ⚠️ user-data видна всем, кто может читать метаданные ВМ, — секреты туда не кладут.

---

## 4. Диски

```bash
lsblk                               # увидеть новый диск: vdb (Yandex, OpenStack) или nvme1n1 (AWS Nitro)
sudo mkfs.ext4 /dev/vdb             # ⚠️ проверь имя устройства трижды
sudo mkdir -p /data
sudo mount /dev/vdb /data

# постоянное монтирование по UUID (а не по имени устройства!)
sudo blkid /dev/vdb
echo 'UUID=xxxx-xxxx /data ext4 defaults,noatime,nofail 0 2' | sudo tee -a /etc/fstab
sudo mount -a && df -h /data
```

Создать и подключить диск:
```bash
# Yandex Cloud
yc compute disk create --name data-1 --size 10 --type network-hdd --zone ru-central1-a
yc compute instance attach-disk web-1 --disk-name data-1
yc compute snapshot create --name data-1-snap --disk-name data-1

# AWS (диск и ВМ должны быть в ОДНОЙ зоне)
aws ec2 create-volume --availability-zone eu-central-1a --size 10 --volume-type gp3 \
  --tag-specifications 'ResourceType=volume,Tags=[{Key=Name,Value=data-1}]'
aws ec2 attach-volume --volume-id vol-0123456789abcdef0 \
  --instance-id i-0123456789abcdef0 --device /dev/sdf     # внутри ВМ будет /dev/nvme1n1
aws ec2 create-snapshot --volume-id vol-0123456789abcdef0 --description "data-1 before upgrade"

# OpenStack
openstack volume create --size 10 data-1
openstack server add volume web-1 data-1
```

| Тип диска | AWS | Yandex Cloud | Когда |
|-----------|-----|--------------|-------|
| Сетевой HDD | `st1`/`sc1` | `network-hdd` | Архивы, логи, учебные стенды — дёшево и медленно |
| Сетевой SSD | `gp3` ⭐ | `network-ssd` | Базы, приложения — дефолт |
| Высокие IOPS | `io2` | `network-ssd-io-m3`, нереплицируемые | Нагруженные базы |
| Локальный NVMe | instance store | — | Максимальная скорость, но данные теряются при остановке ВМ ⚠️ |

Практика:
- Данные (база, загруженные файлы) — на **отдельном диске**, а не на загрузочном:
  ВМ можно пересоздать, диск переподключить.
- Диск живёт в **одной зоне**: подключить его к ВМ в другой зоне нельзя — только через снапшот.
- Расширение диска: увеличить в облаке → `growpart` + `resize2fs` внутри.
- Снапшот диска — быстрый способ бэкапа, но не замена полноценному бэкапу
  (см. [«05. Backup и restore»](/databases/05-backup-restore)).

---

## 5. Метаданные и сервисный аккаунт ВМ

```bash
# Yandex Cloud (формат Google Compute Engine)
curl -H "Metadata-Flavor: Google" \
  http://169.254.169.254/computeMetadata/v1/instance/id
curl -H "Metadata-Flavor: Google" \
  http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token   # ⭐ IAM-токен

# AWS: IMDSv2 — сначала токен сессии, потом запрос
TOKEN=$(curl -sX PUT http://169.254.169.254/latest/api/token \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
curl -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id
curl -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/iam/security-credentials/     # имя роли → временные ключи

# OpenStack
curl http://169.254.169.254/openstack/latest/meta_data.json
```
Зачем это девопсу:
- получить имя/зону/идентификатор ВМ для тегирования логов и метрик;
- получить **временный токен** сервисного аккаунта (роли), чтобы ВМ ходила в API облака
  без хранения статических ключей ⭐;
- прочитать `user-data`, который передавался при создании.

Как выдать ВМ права:
```bash
# Yandex Cloud: сервисный аккаунт на ВМ
yc iam service-account create --name sa-backup
yc resource-manager folder add-access-binding <folder-id> \
  --role storage.uploader --subject serviceAccount:<sa-id>
yc compute instance create ... --service-account-name sa-backup

# AWS: роль → instance profile → ВМ
aws iam create-role --role-name backup-writer \
  --assume-role-policy-document file://trust-ec2.json     # Principal: ec2.amazonaws.com
aws iam attach-role-policy --role-name backup-writer --policy-arn <arn своей политики>
aws iam create-instance-profile --instance-profile-name backup-writer
aws iam add-role-to-instance-profile --instance-profile-name backup-writer --role-name backup-writer
aws ec2 associate-iam-instance-profile --instance-id i-0123456789abcdef0 \
  --iam-instance-profile Name=backup-writer
```

```text:no-line-numbers
ВМ с сервисным аккаунтом / ролью может, например:
  • складывать бэкапы в объектное хранилище
  • читать секреты из облачного хранилища секретов (Lockbox / Secrets Manager)
  • регистрировать себя в service discovery
— и всё это без ключей в файлах на диске.
```

> ⚠️ Метаданные — цель SSRF-атак: уязвимое приложение делает запрос на `169.254.169.254`
> и отдаёт злоумышленнику токен. В AWS поэтому требуют IMDSv2 (`HttpTokens=required`).

---

## 6. Жизненный цикл и стоимость

```text:no-line-numbers
 создать ──► запустить ──► остановить ──► запустить ──► удалить
                │              │                          │
                │              └─ vCPU/RAM не тарифицируются,
                │                 но ДИСК и IP — да ⚠️
                └─ снапшот/образ можно снять в любой момент
```

| Приём экономии | AWS | Yandex Cloud | Суть |
|----------------|-----|--------------|------|
| Прерываемые ВМ | Spot | `--preemptible` | В разы дешевле, но провайдер может остановить (Yandex — и принудительно раз в сутки) |
| Маленькая доля CPU | burstable `t3/t4g` | `--core-fraction 5/20/50` | Для стендов и мелких сервисов |
| Расписание выключения | Instance Scheduler / Lambda / CI | Cloud Functions / CI | dev/stage не работают ночью и в выходные |
| Right-sizing | Compute Optimizer | метрики Monitoring | Смотреть метрики и уменьшать размер |
| Свой образ (golden image) | AMI через Packer | образ через Packer | Быстрый запуск без долгой установки пакетов |
| Скидка за обязательство | Savings Plans / RI | резервирование (committed use) | Для стабильной нагрузки |

⭐ Фундаментальный принцип облака: **инстансы одноразовые** (cattle, not pets).
Если ВМ нельзя удалить и пересоздать за 10 минут скриптом — что-то настроено вручную,
и это техдолг.

---

## 7. В облаках РК

- PS Cloud и Kazteleport дают **OpenStack API и CLI**, веб-консоль (у PS Cloud — ещё VNC),
  заявлена интеграция с Terraform и Ansible; команды выше (`openstack server create`,
  `floating ip`, `volume`) — это их «диалект» (проверь, сентябрь 2026).
- У PS Cloud зоны доступности — Алматы и Астана; у Kazteleport — три ЦОД в Алматы.
  Как они представлены в API (как AZ или как отдельные регионы) — смотри в документации провайдера.
- Прерываемых ВМ, «доли ядра» и аналога роли ВМ (instance profile) у OpenStack-облаков
  обычно нет: считай стоимость по полной цене, а ключи на ВМ выдавай с минимальными
  правами и ротацией.
- Yandex Cloud `kz1` — это тот же `yc`, только профиль `--region=kz` и зона `kz1-a`.
- Цены у облаков РК — в тенге; сравнивай конфигурации в калькуляторах, а не «на глаз».
  Подробнее: [10_kz_clouds.md](/cloud/10-kz-clouds).

---

## 8. Грабли

| Грабля | Последствие | Решение |
|--------|-------------|---------|
| SSH открыт всему интернету с паролем | Взлом за часы | Только ключи, ограничение по IP, bastion/SSM |
| Данные на загрузочном диске | Пересоздание ВМ = потеря данных | Отдельный диск под данные |
| Диск не в `/etc/fstab` | После ребута данные «пропали» | UUID в fstab и проверка `mount -a` |
| ВМ остановлена, «денег не тратим» | Диск и IP тарифицируются | Удалять ненужное |
| Настройка руками, без cloud-init/Ansible | Невоспроизводимая ВМ | Всё в код |
| Ключ сервисного аккаунта в файле на ВМ | Утечка при компрометации | Метаданные и временные токены (роль ВМ) |
| Local SSD / instance store под данные | Потеря данных при остановке | Сетевые диски для данных |
| Нет плана восстановления SSH-доступа | Заблокировал сам себя | Serial console, SSM, запасной ключ |
| AMI ID скопирован из чужого региона | `InvalidAMIID.NotFound` | AMI региональны: брать через SSM-параметр |
| `terminate` в AWS вместо `stop` | Корневой EBS удалён (DeleteOnTermination) | Termination protection на важных ВМ |
| Диск создан в другой зоне | Не подключается к ВМ | Диск и ВМ — в одной зоне |
| IMDSv1 оставлен включённым | SSRF уносит ключи роли | `HttpTokens=required` |
| Секреты в user-data | Видны через метаданные и консоль | Секреты — из хранилища секретов |

---

## 💼 Как это в DevOps

- Первая ВМ создаётся руками, все остальные — Terraform'ом; настройка — cloud-init
  (минимум) + Ansible (всё остальное).
- Прод-машины не имеют публичных IP: доступ через bastion/VPN/SSM, наружу смотрит только
  балансировщик (см. [«03. Сеть и VPC»](/cloud/03-network-vpc)).
- У каждой ВМ есть сервисный аккаунт (роль) с минимальными правами; статические ключи
  на дисках — антипаттерн.
- Golden image (собранный Packer'ом) ускоряет масштабирование: новая нода поднимается
  за минуты, а не за полчаса установки пакетов. Группы автомасштабирования (AWS ASG,
  Yandex Instance Groups) — следующий шаг: [08_aws_deep.md](/cloud/08-aws-deep),
  [09_yandex_cloud.md](/cloud/09-yandex-cloud).
- Проверка зрелости: можно ли удалить любую ВМ и восстановить сервис автоматически?
  Если нет — это «домашний питомец», а не облачная инфраструктура.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Создать ключ | `ssh-keygen -t ed25519 -C "comment" -f ~/.ssh/cloud` |
| Создать ВМ (Yandex) | `yc compute instance create --name ... --zone ... --create-boot-disk ... --ssh-key ...` |
| Создать ВМ (AWS) | `aws ec2 run-instances --image-id ... --instance-type ... --key-name ... --subnet-id ...` |
| Создать ВМ (OpenStack/РК) | `openstack server create --flavor ... --image ... --network ... --key-name ...` |
| Свежий AMI Ubuntu | `aws ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id` |
| Подключиться | `ssh -i ~/.ssh/cloud ubuntu@IP` |
| Ходить через bastion | `ProxyJump bastion` в `~/.ssh/config` |
| Без SSH-порта | `aws ssm start-session --target i-...` · `yc compute ssh --name ...` |
| Пробросить порт к базе | `ssh -L 5432:db-private-ip:5432 bastion` |
| Скопировать файл | `scp file app-1:/tmp/` |
| Автонастройка при старте | cloud-init (`#cloud-config`, `user-data`) |
| Проверить cloud-init | `cloud-init status --wait`, `/var/log/cloud-init-output.log` |
| Увидеть диски | `lsblk`, `df -h`, `blkid` |
| Смонтировать навсегда | UUID в `/etc/fstab` + `mount -a` |
| Расширить ФС после увеличения диска | `growpart` + `resize2fs` |
| Узнать метаданные ВМ | Yandex: `curl -H Metadata-Flavor:Google ...`; AWS: IMDSv2 с токеном |
| Дешёвая ВМ для учёбы | Spot / прерываемая + малая доля CPU (t3/t4g, core-fraction) |
| Снять бэкап диска | `aws ec2 create-snapshot` · `yc compute snapshot create` (не заменяет дамп базы!) |
| Отключить вход по паролю | `PasswordAuthentication no` + перезапуск sshd |

---

## 🧠 Что запомнить

1. ВМ = образ + размер + диски + сеть + security group + ключ + сервисный аккаунт (роль).
2. Порядок обучения: консоль → CLI → Terraform; в AWS и Yandex CLI разные, сущности одни.
3. ⭐ Доступ только по SSH-ключам; пароли и открытый наружу SSH — гарантированный взлом.
4. Прод-ВМ живут в приватной подсети, доступ — через bastion, VPN или SSM/OS Login.
5. cloud-init делает базовую подготовку, остальное — Ansible; логи в
   `/var/log/cloud-init-output.log`; один и тот же файл работает во всех облаках.
6. Данные — на отдельном диске, монтирование по UUID через `/etc/fstab`; диск живёт в одной зоне.
7. Остановленная ВМ всё равно стоит денег за диск и публичный IP.
8. Роль ВМ (AWS) / сервисный аккаунт (Yandex) и метаданные позволяют не хранить ключи
   на диске; в OpenStack-облаках РК аналога обычно нет — минимальные права и ротация.
9. Local SSD / instance store быстрый, но данные исчезают при остановке инстанса.
10. Инстансы одноразовые: если ВМ нельзя пересоздать скриптом — это техдолг.

---

## Задачи

> ⚠️ Все лабы делай на минимальных/прерываемых ВМ и удаляй ресурсы после работы.
> Практику можно делать в **AWS** (Free plan) или **Yandex Cloud** (грант); задачи 🟧 — про AWS,
> 🟦 — про Yandex Cloud, 🇰🇿 — про OpenStack-облака РК. Команды обоих CLI — в конспекте.

---

### Блок A. Теория

**A1.** Из каких компонентов состоит виртуальная машина в облаке?

<details><summary>Ответ</summary>

Образ ОС, тип (vCPU/RAM), загрузочный и дополнительные диски, сетевой интерфейс
в подсети, публичный IP (опционально), security group, SSH-ключ, сервисный аккаунт,
метаданные/cloud-init.

</details>

**A2.** Почему стоит один раз создать ВМ руками в консоли, прежде чем писать Terraform?

<details><summary>Ответ</summary>

Чтобы увидеть все составные части и зависимости (сеть, подсеть, ключи, группы
безопасности). Terraform-код без этого понимания превращается в копипасту.

</details>

**A3.** Как называется пользователь по умолчанию в образах Ubuntu, Debian, Rocky?

<details><summary>Ответ</summary>

`ubuntu`, `debian`, `rocky`/`centos`; в Amazon Linux — `ec2-user`; в Yandex Cloud
при передаче ключа через `--ssh-key` — `yc-user` (или пользователь из cloud-init).

</details>

**A4.** ⭐ Почему доступ по паролю в облаке недопустим?

<details><summary>Ответ</summary>

Публичный адрес ВМ начинают перебирать боты в течение минут после создания;
слабый пароль означает компрометацию. Ключи не подбираются практически.

</details>

**A5.** Что делает `ProxyJump` и зачем нужен bastion?

<details><summary>Ответ</summary>

Позволяет подключаться к машине во внутренней сети «через» bastion одной командой.
Bastion — единственная точка входа снаружи, которую защищают и логируют.

</details>

**A6.** Как безопасно подключиться к базе в приватной подсети со своего ноутбука?

<details><summary>Ответ</summary>

Пробросом порта через bastion: `ssh -L 5432:db-private:5432 bastion`,
затем подключаться к `localhost:5432`; либо через VPN.

</details>

**A7.** Что такое cloud-init и какие задачи он решает? Что в него не стоит класть?

<details><summary>Ответ</summary>

Механизм первоначальной настройки ВМ при первом запуске: пользователи, ключи,
пакеты, файлы, команды. Не стоит класть всю конфигурацию приложения — это работа
Ansible и образов.

</details>

**A8.** Где смотреть, почему cloud-init «не сработал»?

<details><summary>Ответ</summary>

`cloud-init status --wait`, `/var/log/cloud-init-output.log`,
`/var/log/cloud-init.log`; типичные причины — синтаксис YAML и отсутствие `#cloud-config`
в первой строке.

</details>

**A9.** Почему данные держат на отдельном диске, а не на загрузочном?

<details><summary>Ответ</summary>

Чтобы ВМ можно было пересоздать, не потеряв данные: диск отключается
и подключается к новой машине; проще снапшотить и масштабировать.

</details>

**A10.** Почему монтировать надо по UUID, а не по `/dev/vdb`?

<details><summary>Ответ</summary>

Имена устройств (`/dev/vdb`) могут меняться при добавлении/удалении дисков
и перезагрузке; UUID привязан к файловой системе.

</details>

**A11.** Чем Local SSD отличается от network-диска и когда он опасен?

<details><summary>Ответ</summary>

Local SSD физически находится на хосте: очень быстрый, но данные теряются
при остановке/миграции инстанса. Под данные, которые нельзя потерять, он не годится.

</details>

**A12.** Что тарифицируется у остановленной ВМ?

<details><summary>Ответ</summary>

Диски (загрузочный и дополнительные), снапшоты и образы, зарезервированный
публичный IP; сама vCPU/RAM обычно нет.

</details>

**A13.** Что такое прерываемая (spot/preemptible) ВМ и где её уместно применять?

<details><summary>Ответ</summary>

ВМ, которую провайдер может остановить в любой момент, зато она в разы дешевле.
Подходит для учебных стендов, батчей, CI-раннеров, stateless-нагрузок с автозапуском.

</details>

**A14.** Зачем ВМ сервисный аккаунт и чем это лучше ключа в файле?

<details><summary>Ответ</summary>

ВМ получает временный токен из сервиса метаданных и ходит в API облака
без хранения долгоживущих ключей на диске; компрометация диска не даёт постоянных прав.
В AWS это IAM-роль через instance profile, в Yandex Cloud — сервисный аккаунт на ВМ.

</details>

**A15.** Что значит «инстансы одноразовые» и как проверить, выполняется ли это у тебя?

<details><summary>Ответ</summary>

Любую ВМ можно удалить и автоматически воссоздать (Terraform + cloud-init/Ansible
или образ) без ручных шагов. Проверяется буквально: удалить и пересоздать за минуты.

</details>

**A16.** 🟧 Почему AMI ID нельзя «просто скопировать из статьи» и как получить актуальный
образ Ubuntu в своём регионе?

<details><summary>Ответ</summary>

AMI региональны и обновляются: ID из статьи относится к другому региону или устарел
(получишь `InvalidAMIID.NotFound` или старую ОС). Актуальный ID Ubuntu берут из SSM Parameter
Store: `aws ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id`
(или `--image-id resolve:ssm:<параметр>` прямо в `run-instances`).

</details>

**A17.** 🟧🟦 Как ВМ получает права в облаке в AWS и в Yandex Cloud? Как называются сущности?

<details><summary>Ответ</summary>

AWS: IAM-роль с trust policy на `ec2.amazonaws.com`, упакованная в instance profile
и привязанная к ВМ; временные ключи отдаёт IMDS. Yandex Cloud: сервисный аккаунт
с ролями на каталог/ресурс, назначенный ВМ (`--service-account-name`); IAM-токен отдаёт
сервис метаданных. Идея одна — никаких постоянных ключей на диске.

</details>

**A18.** 🟧 Что такое IMDSv2 и от какой атаки он защищает?

<details><summary>Ответ</summary>

Вторая версия сервиса метаданных EC2: сначала `PUT` за токеном сессии, потом
запросы с заголовком токена. Защищает от SSRF — когда уязвимое приложение по просьбе
злоумышленника делает <code v-pre>GET http://169.254.169.254/...</code> и отдаёт ему ключи роли.
Включается `--metadata-options HttpTokens=required`.

</details>

**A19.** 🇰🇿 Чем работа с ВМ в OpenStack-облаке РК отличается от AWS/Yandex
(названия сущностей, публичный IP, права ВМ)?

<details><summary>Ответ</summary>

Сущности называются по-другому: server, flavor, image, volume, keypair, floating IP.
Публичный адрес — floating IP, который привязывают к порту ВМ. Выход наружу — через роутер
с внешним шлюзом. Аналога роли ВМ обычно нет: ключи к S3/API хранят на ВМ, поэтому нужны
минимальные права, отдельный ключ на ВМ и ротация. Прерываемых ВМ и «доли ядра» обычно нет.

</details>

---

### Блок B. «Что делает команда / что тут не так»

```bash
B1.  ssh-keygen -t ed25519 -C "nurik@laptop" -f ~/.ssh/cloud_ed25519
B2.  ssh -i ~/.ssh/cloud_ed25519 ubuntu@203.0.113.10
B3.  ssh -L 5432:10.0.2.10:5432 bastion
B4.  scp -r ./app app-1:/opt/
B5.  cloud-init status --wait
B6.  lsblk && sudo blkid /dev/vdb
B7.  sudo growpart /dev/vda 1 && sudo resize2fs /dev/vda1
B8.  curl http://169.254.169.254/latest/meta-data/
```

<details><summary>Ответ</summary>

**B1.** Создаёт пару ключей ed25519 с комментарием в отдельный файл.
**B2.** Подключение по конкретному ключу.
**B3.** Локальный порт 5432 пробрасывается на базу через bastion.
**B4.** Копирование каталога на удалённую машину.
**B5.** Ожидание завершения cloud-init и вывод статуса.
**B6.** Список блочных устройств и UUID диска.
**B7.** Расширение раздела и файловой системы после увеличения диска.
**B8.** Запрос к сервису метаданных инстанса (в AWS без токена сработает только при IMDSv1).

</details>

Оцени решения:

```text:no-line-numbers
B9.  Security group: SSH 22/tcp открыт для 0.0.0.0/0
B10. PasswordAuthentication yes, root-логин разрешён
B11. Приватный SSH-ключ скопирован на bastion "чтобы было удобнее"
B12. База данных развёрнута на загрузочном диске ВМ
B13. Диск примонтирован командой mount, в fstab записи нет
B14. Local SSD используется под данные PostgreSQL
B15. Ключ сервисного аккаунта лежит в /root/key.json на ВМ
B16. Все ВМ настраивались вручную по SSH, документации нет
B17. Прод-ВМ имеет публичный IP и смотрит в интернет
B18. 🟧 В AWS важную ВМ "выключили" командой terminate-instances
B19. 🟧 На EC2 разрешён IMDSv1, приложение умеет ходить по произвольным URL (превью ссылок)
B20. 🟦 Ключ сервисного аккаунта Yandex выпущен и положен на ВМ, хотя ВМ можно назначить SA
B21. 🇰🇿 В OpenStack-облаке на ВМ лежат EC2-ключи от S3 с правами на весь проект
```

<details><summary>Ответ</summary>

**B9.** SSH всему интернету — зона риска; ограничить IP или использовать bastion/VPN.
**B10.** Пароли и root-логин — комбинация, которую взламывают в первую очередь.
**B11.** Приватный ключ не должен покидать машину владельца; для этого есть ProxyJump
и agent forwarding (и тот с оговорками).
**B12.** База на загрузочном диске мешает пересоздавать ВМ и увеличивает риск потери.
**B13.** После перезагрузки диск не примонтируется, приложение «потеряет» данные.
**B14.** Данные PostgreSQL на Local SSD исчезнут при остановке ВМ.
**B15.** Статический ключ на диске — постоянные права при компрометации; нужен
сервисный аккаунт через метаданные.
**B16.** Невоспроизводимая инфраструктура: восстановление после аварии займёт дни.
**B17.** Прод не должен светить публичным IP: снаружи — только балансировщик.
**B18.** `terminate` — это удаление; корневой EBS с `DeleteOnTermination=true` удаляется вместе
с ВМ. Для «выключить» есть `stop-instances`, для важных ВМ — termination protection.
**B19.** Классический путь SSRF → ключи роли. Нужен IMDSv2 (`HttpTokens=required`)
и фильтрация исходящих запросов приложения.
**B20.** Лишний долгоживущий ключ на диске; назначь SA на ВМ и бери токен из метаданных.
**B21.** Ключи на ВМ неизбежны, но права должны быть минимальными (один бакет),
ключ — отдельный на ВМ, с ротацией и хранением в Vault/секретах.

</details>

Что делают команды:

```bash
B22. yc compute instance create --name web-1 --zone kz1-a --ssh-key ~/.ssh/id.pub ...
B23. aws ec2 run-instances --image-id "$AMI" --instance-type t3.micro --metadata-options HttpTokens=required ...
B24. openstack server add floating ip web-1 203.0.113.50
```

<details><summary>Ответ</summary>

**B22.** Создание ВМ в регионе Казахстан Yandex Cloud (профиль `--region=kz`, зона `kz1-a`);
пользователь для входа — `yc-user`.
**B23.** ВМ в AWS с обязательным IMDSv2 — правильная настройка.
**B24.** Привязка публичного адреса (floating IP) к ВМ в OpenStack-облаке.

</details>

---

### Блок C. Практика

#### C1. 🔑 Первая ВМ руками
1. Создай ВМ через веб-консоль: минимальная конфигурация, Ubuntu, публичный IP.
2. Добавь свой публичный SSH-ключ.
3. Подключись, посмотри `lsblk`, `df -h`, `free -m`, `ip a`.
4. Запиши, какие поля пришлось заполнить при создании.

#### C2. То же самое через CLI
Повтори создание ВМ командой CLI своего провайдера. Сравни время и воспроизводимость.
Сохрани команду в файл.

#### C3. SSH-конфиг и bastion
1. Создай вторую ВМ **без** публичного IP.
2. Настрой `~/.ssh/config` с `ProxyJump` через первую.
3. Подключись к внутренней ВМ одной командой `ssh app-1`.

#### C4. Харденинг SSH
1. Отключи вход по паролю и root-логин.
2. Ограничь доступ по SSH в security group своим IP.
3. Проверь, что подключение по-прежнему работает, а с чужого адреса — нет.

<details><summary>Ответ</summary>

Проверить можно с другого адреса (например, с телефона в мобильной сети) —
соединение должно отваливаться по таймауту.

</details>

#### C5. 🔑 cloud-init
Создай ВМ с cloud-init, который: создаёт пользователя `deploy` с твоим ключом,
ставит docker, отключает вход по паролю и запускает контейнер nginx.
Проверь результат и `/var/log/cloud-init-output.log`.

<details><summary>Ответ</summary>

Проверка: `id deploy`, `docker ps`, попытка входа по паролю (должна отклоняться).

</details>

#### C6. Диски
1. Подключи дополнительный диск 10 ГБ.
2. Создай ФС, смонтируй в `/data`, пропиши в fstab по UUID.
3. Перезагрузи ВМ и проверь, что диск на месте.
4. Увеличь диск в консоли и расширь ФС (`growpart`, `resize2fs`).

<details><summary>Ответ</summary>

После перезагрузки `df -h /data` должен показывать примонтированный диск;
если нет — ошибка в fstab (проверять `mount -a` до перезагрузки!).

</details>

#### C7. Снапшот и восстановление
1. Положи файл в `/data`, сними снапшот диска.
2. Удали файл, восстанови диск из снапшота (или создай новый диск из снапшота).
3. Запиши, сколько времени это заняло.

#### C8. Метаданные и сервисный аккаунт
1. Привяжи к ВМ сервисный аккаунт с правами на объектное хранилище.
2. С самой ВМ получи токен из метаданных.
3. Загрузи файл в бакет **без** статических ключей.

<details><summary>Ответ</summary>

Успех — файл в бакете появился, при этом на ВМ нет файла с ключами.

</details>

#### C9. Одноразовость
Удали ВМ и пересоздай её одной командой/скриптом так, чтобы сервис снова работал.
Замерь время. Если не получается — запиши, что мешает.

<details><summary>Ответ</summary>

Типичные помехи: ручные настройки, которых нет в коде; данные на загрузочном
диске; жёстко прописанные IP.

</details>

#### C10. Экономия
Сравни стоимость: обычная ВМ vs прерываемая vs с уменьшенной долей CPU.
Посчитай месячную стоимость своего стенда и запиши в README.

<details><summary>Ответ</summary>

Прерываемая ВМ обычно в 2-3 раза дешевле; доля CPU 20% ещё сильнее снижает цену.

</details>

#### C11. 🟧 Та же ВМ в AWS
1. Импортируй ключ (`aws ec2 import-key-pair`), получи AMI через SSM-параметр.
2. Создай ВМ `t3.micro` (или то, что входит в Free plan) с cloud-init из C5 и IMDSv2.
3. Подключись по SSH; затем закрой 22 порт и подключись через `aws ssm start-session`
   (нужна роль с `AmazonSSMManagedInstanceCore`).
4. Удали ВМ и проверь, что не осталось EBS-дисков и Elastic IP.

<details><summary>Ответ</summary>

Для Session Manager на Ubuntu нужен SSM Agent (в официальных AMI Ubuntu он обычно
предустановлен как snap — проверь) и выход к endpoint'ам SSM (через интернет/NAT или VPC endpoint).
После удаления ВМ проверь `aws ec2 describe-volumes` и `aws ec2 describe-addresses`.

</details>

#### C12. 🟧🟦 Две команды — одна ВМ
Запиши рядом команды создания одинаковой ВМ в `yc` и `aws` (образ, размер, диск, сеть,
ключ, cloud-init, прерываемость, метки). Подпиши, какой флаг чему соответствует.

<details><summary>Ответ</summary>

Соответствия: `image-family` ↔ `--image-id`; `--cores/--memory/--core-fraction` ↔
`--instance-type`; `--create-boot-disk size,type` ↔ `--block-device-mappings`;
`--network-interface subnet-name,nat-ip-version` ↔ `--subnet-id --associate-public-ip-address`;
`--metadata-from-file user-data` ↔ `--user-data`; `--preemptible` ↔
`--instance-market-options MarketType=spot`; `--labels` ↔ `--tag-specifications`.

</details>

#### C13. 🟧 Роль вместо ключей
Создай IAM-роль с доступом к одному бакету, instance profile, привяжи к ВМ.
С ВМ выполни `aws sts get-caller-identity` и `aws s3 cp` без `aws configure`.

<details><summary>Ответ</summary>

`aws sts get-caller-identity` на ВМ покажет `assumed-role/<роль>/i-...` —
это и есть подтверждение, что работают временные ключи роли.

</details>

---

### Блок D. Инциденты

**D1.** Потерял SSH-ключ и не можешь зайти на ВМ. Какие есть пути?

<details><summary>Ответ</summary>

Serial/веб-консоль провайдера, добавление нового ключа через метаданные ВМ
(многие облака применяют изменения на лету), подключение диска к другой ВМ
и правка `authorized_keys`, пересоздание ВМ из снапшота.

</details>

**D2.** После перезагрузки ВМ каталог `/data` пуст. Что случилось?

<details><summary>Ответ</summary>

Диск не примонтирован после перезагрузки: нет записи в `/etc/fstab`
(или она неверна и система загрузилась без него).

</details>

**D3.** ВМ недоступна по SSH сразу после создания. Что проверишь по порядку?

<details><summary>Ответ</summary>

Статус ВМ и сервиса, публичный IP, security group и firewall, правильный
пользователь и ключ, готовность cloud-init, логи через serial console.

</details>

**D4.** На ВМ в логах тысячи попыток подбора пароля по SSH. Что делать?

<details><summary>Ответ</summary>

Убедиться, что вход по паролю отключён; ограничить SSH по IP/через bastion;
поставить fail2ban; перенести SSH за VPN; проверить, не было ли успешных входов.

</details>

**D5.** Прерываемая ВМ с базой была остановлена провайдером ночью. Что было
сделано неправильно?

<details><summary>Ответ</summary>

На прерываемых ВМ нельзя размещать stateful-сервисы без репликации и бэкапов;
база должна жить на обычной ВМ или в managed-сервисе.

</details>

**D6.** Диск заполнен на 100%, ВМ не отвечает нормально. Как разбирать?

<details><summary>Ответ</summary>

`df -h`, `du -sh /* | sort -h`, логи (`/var/log`, docker), временные файлы,
переполненные диски снапшотов; далее — ротация и увеличение диска.

</details>

**D7.** cloud-init не создал пользователя. Где искать причину?

<details><summary>Ответ</summary>

Логи cloud-init, синтаксис YAML, наличие строки `#cloud-config`, правильно ли
передан `user-data`, поддерживает ли образ cloud-init, не выполнялся ли он раньше
(при клонировании диска состояние может считаться «уже настроено»).

</details>

**D8.** Расширили диск в консоли, но `df -h` показывает старый размер. Что сделать?

<details><summary>Ответ</summary>

Расширить раздел и ФС внутри: `growpart /dev/vda 1` и `resize2fs /dev/vda1`
(или `xfs_growfs`).

</details>

**D9.** Приложение на ВМ не может писать в бакет: «access denied». Что проверишь?

<details><summary>Ответ</summary>

Привязан ли сервисный аккаунт к ВМ, какие у него роли, правильный ли бакет,
не используются ли просроченные статические ключи, политика доступа бакета, сеть.

</details>

**D10.** Уволился инженер, у которого был SSH-доступ ко всем ВМ. Порядок действий.

<details><summary>Ответ</summary>

Отозвать его ключи в IAM/OS Login и `authorized_keys`, сменить общие секреты,
проверить журналы доступа, убедиться, что доступ был персональным, а не общим ключом;
перейти на централизованное управление доступом (OS Login, SSM Session Manager), если этого не было.

</details>

**D11.** 🟧 После `terminate` важной ВМ в AWS пропали и данные. Почему и что спасёт
в следующий раз?

<details><summary>Ответ</summary>

Корневой EBS по умолчанию удаляется при terminate; данные на нём были единственной
копией. Спасёт снапшот (если был). На будущее: данные на отдельном томе с
`DeleteOnTermination=false`, регулярные снапшоты (AWS Backup/Data Lifecycle Manager),
termination protection, права на `TerminateInstances` только у тех, кому нужно.

</details>

**D12.** 🟧 В CloudTrail видно, что ключи роли ВМ используются с чужого IP. Как они
могли утечь и что делать?

<details><summary>Ответ</summary>

Типично — SSRF при IMDSv1 или RCE на ВМ. Действия: отозвать сессии роли
(в консоли IAM «Revoke active sessions» — политика запрета для токенов, выданных раньше
текущего момента), изолировать ВМ, снять диск для расследования, пересоздать ВМ из образа,
включить IMDSv2, сузить права роли, проверить CloudTrail на действия злоумышленника.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как создать ВМ в облаке и что нужно указать?

<details><summary>Ответ</summary>

Указать образ, размер, зону, диски, сеть и подсеть, security group, SSH-ключ,
при необходимости сервисный аккаунт и cloud-init.

</details>

**2.** Как настраивается доступ по SSH и почему не паролем?

<details><summary>Ответ</summary>

Публичный ключ передаётся в метаданные ВМ или через IAM; вход по паролю отключают,
так как его перебирают боты.

</details>

**3.** Что такое bastion и зачем он нужен?

<details><summary>Ответ</summary>

Единственная точка входа снаружи во внутреннюю сеть: через неё ходят по SSH
к машинам без публичных адресов.

</details>

**4.** Что такое cloud-init?

<details><summary>Ответ</summary>

Стандартный механизм первичной настройки ВМ при первом запуске (пользователи, ключи,
пакеты, команды).

</details>

**5.** Как подключить и смонтировать дополнительный диск?

<details><summary>Ответ</summary>

`lsblk` → `mkfs` → `mount` → запись в `/etc/fstab` по UUID → `mount -a`.

</details>

**6.** Почему монтируют по UUID?

<details><summary>Ответ</summary>

Имена устройств нестабильны, UUID привязан к файловой системе.

</details>

**7.** Что происходит с данными на Local SSD при остановке ВМ?

<details><summary>Ответ</summary>

Данные теряются: Local SSD не переживает остановку/миграцию инстанса.

</details>

**8.** Что тарифицируется у выключенной ВМ?

<details><summary>Ответ</summary>

Диски, снапшоты и зарезервированные публичные IP.

</details>

**9.** Как ВМ может ходить в API облака без статических ключей?

<details><summary>Ответ</summary>

Через сервисный аккаунт и сервис метаданных, который выдаёт временные токены.

</details>

**10.** Что значит «серверы должны быть одноразовыми»?

<details><summary>Ответ</summary>

Любую ВМ можно удалить и автоматически воссоздать; всё состояние вынесено
в диски, хранилища и код.

</details>

**11.** Как в AWS зайти на ВМ без открытого SSH-порта?

<details><summary>Ответ</summary>

SSM Session Manager (`aws ssm start-session`) — агент на ВМ, права через IAM, аудит
сессий; или EC2 Instance Connect Endpoint. Порт 22 наружу не нужен.

</details>

**12.** Чем instance profile в AWS похож на сервисный аккаунт ВМ в Yandex Cloud?

<details><summary>Ответ</summary>

Оба дают ВМ временные права без ключей на диске: в AWS роль в instance profile,
ключи отдаёт IMDS; в Yandex Cloud — сервисный аккаунт на ВМ, IAM-токен из метаданных.

</details>

---

### 🎯 Чек-лист

- [ ] Создал ВМ в консоли и той же командой в CLI
- [ ] Подключаюсь только по ключу, пароли отключены
- [ ] ⭐ Настроил bastion и `ProxyJump`
- [ ] Умею пробрасывать порт к приватной базе
- [ ] Применял cloud-init и умею читать его логи
- [ ] Подключил отдельный диск и прописал его по UUID в fstab
- [ ] Снял снапшот и восстановился из него
- [ ] Использую сервисный аккаунт вместо ключей на диске
- [ ] Могу удалить и пересоздать ВМ скриптом
- [ ] Знаю, сколько стоит мой стенд в месяц
- [ ] Создавал одинаковую ВМ через `yc` и `aws` и понимаю соответствие флагов
- [ ] Использую IMDSv2 в AWS и роль/сервисный аккаунт вместо ключей
