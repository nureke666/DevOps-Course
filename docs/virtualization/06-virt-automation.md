---
title: "06. Автоматизация: шаблоны, cloud-init, Packer, Terraform, Ansible, VMware"
description: "Блок → Виртуализация on-prem → тема 06. Опирается на 02kvmqemulibvirt.md"
---

# 06. Автоматизация: шаблоны, cloud-init, Packer, Terraform, Ansible, VMware

> Блок → Виртуализация on-prem → тема 06. Опирается на [02_kvm_qemu_libvirt.md](/virtualization/02-kvm-qemu-libvirt)
> (cloud-init, overlay), [04_proxmox.md](/virtualization/04-proxmox) (шаблоны, API-токены), блок Terraform
> [../Left/06_Terraform/00_INDEX.md](/terraform/) (провайдер, ресурс, стейт)
> и [../Ansible/03_inventory.md](/ansible/03-inventory) (динамический inventory).
>
> **После темы ты умеешь:** собрать хороший шаблон VM, писать cloud-init (user-data, meta-data,
> network-config) и отлаживать его, собирать «золотой образ» Packer'ом (qemu и proxmox),
> создавать VM Terraform'ом в libvirt (провайдер dmacvicar/libvirt 0.9) и в Proxmox
> (bpg/proxmox), настраивать их Ansible'ом через динамический inventory, описать конвейер
> golden image и говорить на языке VMware vSphere (vCenter, datastore, vMotion, DRS, HA, govc).

---

## 🗺️ Карта темы

```text
  ОБРАЗ (редко)              ИНФРАСТРУКТУРА (часто)          КОНФИГУРАЦИЯ (всегда)
  ─────────────              ─────────────────────           ────────────────────
  облачный образ             Terraform                       Ansible
       │                     ├─ dmacvicar/libvirt  → KVM     ├─ inventory: community.libvirt
       ▼                     ├─ bpg/proxmox        → Proxmox ├─ inventory: community.proxmox
  Packer (qemu / proxmox)    └─ vmware/vsphere     → vSphere └─ роли: nginx, postgres, ...
  + обновления, агент,             │
    hardening, clean               │  VM из шаблона + cloud-init:
       │                           │  пользователь, ключ, IP, hostname
       ▼                           ▼
  golden image / шаблон ─────►  VM ───────────────────────────►  сервис
  noble-golden-2026.09.27     «скот, а не питомцы»: сломалась — пересоздаём кодом
```text
---

## 1. Что автоматизируем и почему в три слоя

| Слой | Инструмент | Как часто меняется | Что там |
|------|-----------|--------------------|---------|
| Образ | Packer | Раз в месяц + при критичных CVE | ОС, обновления, агент, базовый hardening, мониторинг-агент |
| Инфраструктура | Terraform | При изменении состава | Сколько VM, какие CPU/RAM/диски, сети, VLAN |
| Конфигурация | Ansible | При каждом релизе | Пакеты и конфиги сервисов, пользователи, сертификаты |
| Первый старт | cloud-init | — | Склейка: hostname, пользователь, ключ, IP, «позвони Ansible» |

Чем больше вшито в образ, тем быстрее и предсказуемее старт VM; чем больше в Ansible, тем
гибче. Правило: в образ — то, что нужно **всем** VM и меняется редко.

---

## 2. Хороший шаблон VM

- [ ] Облачный образ дистрибутива с проверенной контрольной суммой (не «ISO + ручная установка»)
- [ ] `cloud-init` включён, datasource подходит платформе (NoCloud, ConfigDrive, VMware)
- [ ] `qemu-guest-agent` (KVM/Proxmox) или `open-vm-tools` (VMware)
- [ ] Обновления на дату сборки, лишние пакеты удалены
- [ ] **Уникальность удалена:** `/etc/machine-id` пуст, `/etc/ssh/ssh_host_*` удалены,
      `cloud-init clean` выполнен, нет истории shell и логов
- [ ] Нет паролей и чужих ключей; вход — только по ключу из cloud-init
- [ ] Драйверы virtio, серийная консоль (`console=ttyS0`) для облачных образов
- [ ] Имя с версией: `noble-golden-2026.09.27`, а не `ubuntu-template-final-2`

> ⚠️ Забудешь про `machine-id` — все клоны получат один IP по DHCP (DHCP client ID строится
> из machine-id) и одинаковые SSH host keys. Классика, разобрана в задачах тем 02 и 04.

---

## 3. cloud-init подробнее

### Источники данных и стадии

```text
 datasource: NoCloud (ISO/диск «cidata», libvirt, Proxmox), ConfigDrive (OpenStack),
             VMware (guestinfo), EC2/GCE/Azure (сервис метаданных облака) ...
      │
      ▼
 local   → найти datasource, применить network-config (сеть ещё не поднята)
 network → поднять сеть, получить user-data; bootcmd, write_files, growpart, users, ssh-ключи
 config  → ntp, timezone, настройки apt, ...
 final   → packages, runcmd, scripts, final_message                  → cloud-init status: done
```text
Большинство модулей — **один раз на экземпляр** (по `instance-id`): `users`, `packages`,
`runcmd`. `bootcmd` — при **каждой** загрузке. Сменился `instance-id` — это «новая VM»,
модули отработают снова.

### user-data: что пишут чаще всего

```yaml
#cloud-config
hostname: app1
fqdn: app1.lab.local
timezone: Asia/Almaty
users:
  - name: devops
    groups: [sudo]
    shell: /bin/bash
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    lock_passwd: true
    ssh_authorized_keys:
      - ssh-ed25519 AAAA... devops@laptop
ssh_pwauth: false
package_update: true
package_upgrade: false            # полное обновление при старте = долгий старт; лучше в образе
packages: [qemu-guest-agent, chrony]
write_files:
  - path: /etc/motd
    content: "Managed by Terraform + Ansible. Руками не править.\n"
runcmd:
  - [systemctl, enable, --now, qemu-guest-agent]
final_message: "cloud-init done after $UPTIME s"
```text
- Формы user-data: `#cloud-config` (YAML), обычный скрипт (`#!/bin/bash`), MIME multipart (оба сразу).
- **vendor-data** — настройки «от платформы», которые **сливаются** с user-data, а не
  заменяют его. В Proxmox удобно: `--cicustom "vendor=local:snippets/vendor.yaml"` ставит
  пакеты, а пользователь и ключи по-прежнему идут из `ciuser`/`sshkeys`.
- ⚠️ user-data читает любой, у кого есть доступ к datasource (ISO, API, сервис метаданных).
  Секреты туда не кладут — только ключи доступа к системе, откуда секрет заберут (Vault).

### meta-data и network-config

```yaml
# meta-data
instance-id: app1-2026-09-27
local-hostname: app1
```text
```yaml
# network-config — версия 2, это синтаксис netplan
version: 2
ethernets:
  mgmt0:
    match:
      macaddress: "52:54:00:10:00:01"   # имена enp1s0/ens18 зависят от платформы — матчим по MAC
    set-name: mgmt0
    addresses: [10.10.10.60/24]
    routes:
      - to: default
        via: 10.10.10.1
    nameservers:
      addresses: [10.10.10.1]
```text
### Отладка

```bash
cloud-init status --wait --long             # done / error, detail: DataSourceNoCloud ...
sudo cat /var/log/cloud-init.log | grep -iE 'warn|error|traceback'
sudo cat /var/log/cloud-init-output.log     # вывод packages и runcmd
sudo cloud-init query --all | less          # что пришло от datasource
sudo cloud-init query userdata              # user-data как его увидел cloud-init
cloud-init schema -c user-data.yaml --annotate   # проверить YAML ДО запуска (где стоит cloud-init)
sudo cloud-init clean --logs --reboot       # прогнать заново (только на стенде!)
```text
---

## 4. Packer: золотой образ

**Packer** поднимает временную VM, прогоняет провижинеры (shell, Ansible) и сохраняет результат
как образ или шаблон. Плагины: `hashicorp/qemu` (builder `qemu`, актуальная ветка 1.1.x) и
`hashicorp/proxmox` (builders `proxmox-iso` и `proxmox-clone`, ветка 1.2.x).

### 4.1. qemu: qcow2 из облачного образа (на хосте с KVM)

```hcl
# packer/noble.pkr.hcl
packer {
  required_plugins {
    qemu = {
      source  = "github.com/hashicorp/qemu"
      version = "~> 1.1"
    }
  }
}

variable "version" {
  type    = string
  default = "2026.09.27"
}

source "qemu" "noble" {
  iso_url          = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
  iso_checksum     = "file:https://cloud-images.ubuntu.com/noble/current/SHA256SUMS"
  disk_image       = true               # на входе готовый диск, а не установщик
  format           = "qcow2"
  disk_size        = "10G"
  disk_compression = true
  accelerator      = "kvm"
  headless         = true
  cpus             = 2
  memory           = 2048
  net_device       = "virtio-net"
  disk_interface   = "virtio"
  output_directory = "output/noble-golden-${var.version}"
  vm_name          = "noble-golden-${var.version}.qcow2"

  cd_label = "cidata"                   # NoCloud для первого старта сборочной VM
  cd_content = {
    "meta-data" = "instance-id: packer\nlocal-hostname: packer\n"
    "user-data" = <<-EOF
      #cloud-config
      password: packer
      chpasswd: { expire: false }
      ssh_pwauth: true
    EOF
  }

  ssh_username     = "ubuntu"           # временный пароль живёт только во время сборки
  ssh_password     = "packer"
  ssh_timeout      = "15m"
  shutdown_command = "sudo shutdown -P now"
}

build {
  sources = ["source.qemu.noble"]

  provisioner "shell" {
    inline = [
      "cloud-init status --wait",
      "sudo apt-get update",
      "sudo DEBIAN_FRONTEND=noninteractive apt-get -y full-upgrade",
      "sudo apt-get -y install qemu-guest-agent",
      "sudo passwd -l ubuntu",
      "sudo cloud-init clean --logs --machine-id --seed --configs all",
      "sudo rm -f /etc/ssh/ssh_host_*",
    ]
  }
}
```text
```bash
cd packer
packer init .              # скачать плагины
packer fmt -check .        # стиль (для CI)
packer validate .
packer build .             # → output/noble-golden-2026.09.27/noble-golden-2026.09.27.qcow2
```text
`--configs all` в `cloud-init clean` удаляет и сгенерированные файлы (sshd с паролями,
netplan) — в шаблоне не останется `PasswordAuthentication yes`. Нужен доступ к `/dev/kvm`
(группа `kvm`) и `xorriso` для `cd_content`.

### 4.2. proxmox-clone: новый шаблон из шаблона

```hcl
packer {
  required_plugins {
    proxmox = {
      source  = "github.com/hashicorp/proxmox"
      version = "~> 1.2"
    }
    ansible = {                        # для provisioner "ansible" ниже
      source  = "github.com/hashicorp/ansible"
      version = "~> 1.1"
    }
  }
}

variable "pve_token" {
  type      = string
  sensitive = true                     # PKR_VAR_pve_token из секрета CI
}

source "proxmox-clone" "golden" {
  proxmox_url              = "https://10.10.10.11:8006/api2/json"
  username                 = "packer@pve!packer"   # пользователь!идентификатор_токена
  token                    = var.pve_token
  insecure_skip_tls_verify = true
  node                     = "pve1"
  clone_vm_id              = 9000                  # базовый шаблон из темы 04
  vm_id                    = 9100
  template_name            = "noble-golden-2026-09"
  cores                    = 2
  memory                   = 2048
  network_adapters {
    bridge = "vmbr0"
    model  = "virtio"
  }
  cloud_init              = true
  cloud_init_storage_pool = "local-lvm"
  ssh_username            = "devops"
  ssh_private_key_file    = pathexpand("~/.ssh/id_ed25519")
}

build {
  sources = ["source.proxmox-clone.golden"]
  provisioner "ansible" {
    playbook_file = "../ansible/base.yml"   # hardening той же ролью, что и в проде
  }
}
```text
IP клона Packer узнаёт через **qemu-guest-agent** — в базовом шаблоне агент обязан быть.
`proxmox-iso` — то же, но с установкой с ISO (autoinstall/kickstart через `boot_command`).

---

## 5. Terraform + libvirt (dmacvicar/libvirt 0.9)

> ⚠️ В 2025 провайдер **переписан с нуля** (ветка 0.9.x на Terraform Plugin Framework): схема
> повторяет XML libvirt. Примеры из старых статей для 0.7/0.8 (`network_interface { network_name }`,
> `cloudinit = ...`, `source = "https://..."` у тома) на 0.9 **не работают**. Смотри
> документацию именно своей версии.

```hcl
# terraform/libvirt/main.tf
terraform {
  required_providers {
    libvirt = {
      source  = "dmacvicar/libvirt"
      version = "~> 0.9.9"
    }
  }
}

provider "libvirt" {
  uri = "qemu:///system"
}

locals {
  vms = toset(["web1", "web2"])
}

resource "libvirt_volume" "base" {
  name   = "noble-tf-base.qcow2"
  pool   = "default"
  target = { format = { type = "qcow2" } }
  create = {
    content = {
      url = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
    }
  }
}

resource "libvirt_volume" "disk" {
  for_each = local.vms
  name     = "${each.key}.qcow2"
  pool     = "default"
  capacity = 10737418240                      # 10 GiB в байтах
  target   = { format = { type = "qcow2" } }
  backing_store = {
    path   = libvirt_volume.base.path
    format = { type = "qcow2" }
  }
}

resource "libvirt_cloudinit_disk" "seed" {
  for_each = local.vms
  name     = "${each.key}-seed"
  user_data = templatefile("${path.module}/user-data.tftpl", {
    hostname = each.key
    ssh_key  = trimspace(file(pathexpand("~/.ssh/id_ed25519.pub")))
  })
  meta_data = yamlencode({ instance-id = each.key, local-hostname = each.key })
}

resource "libvirt_volume" "seed" {
  for_each = local.vms
  name     = "${each.key}-seed.iso"
  pool     = "default"
  create   = { content = { url = libvirt_cloudinit_disk.seed[each.key].path } }
}

resource "libvirt_domain" "vm" {
  for_each    = local.vms
  name        = each.key
  type        = "kvm"
  vcpu        = 1
  memory      = 1024
  memory_unit = "MiB"
  running     = true

  os  = { type = "hvm", type_arch = "x86_64", type_machine = "q35" }
  cpu = { mode = "host-passthrough" }

  devices = {
    disks = [
      {
        source = { volume = { pool = "default", volume = libvirt_volume.disk[each.key].name } }
        target = { dev = "vda", bus = "virtio" }
        driver = { type = "qcow2" }
      },
      {
        device = "cdrom"
        source = { volume = { pool = "default", volume = libvirt_volume.seed[each.key].name } }
        target = { dev = "sda", bus = "sata" }
      },
    ]
    interfaces = [
      {
        type        = "network"
        model       = { type = "virtio" }
        source      = { network = { network = "virt-lab" } }
        wait_for_ip = { timeout = 300, source = "lease" }   # ждать аренду DHCP
      },
    ]
  }
}

data "libvirt_domain_interface_addresses" "vm" {
  for_each = local.vms
  domain   = libvirt_domain.vm[each.key].name
  source   = "lease"
}

output "ips" {
  value = { for k, d in data.libvirt_domain_interface_addresses.vm : k => d.interfaces[0].addrs[0].addr }
}
```text
```yaml
# terraform/libvirt/user-data.tftpl
#cloud-config
hostname: ${hostname}
users:
  - name: devops
    groups: [sudo]
    shell: /bin/bash
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    ssh_authorized_keys:
      - ${ssh_key}
packages: [qemu-guest-agent]
runcmd:
  - [systemctl, start, qemu-guest-agent]
```text
```bash
terraform init && terraform plan && terraform apply
terraform output -json ips       # {"web1":"10.10.10.1xx","web2":"10.10.10.1yy"}
```text
Серийная консоль и канал агента описываются в `devices.consoles` / `devices.channels` — так же,
как в XML libvirt (схема повторяет его один в один).

---

## 6. Terraform + Proxmox: bpg/proxmox или Telmate

| | **bpg/proxmox** ⭐ | Telmate/proxmox |
|---|--------------------|-----------------|
| Статус в 2026 | Частые стабильные релизы (0.11x), самый скачиваемый | Ветка 3.0.2 годами в release candidate |
| Что умеет | VM, LXC, файлы/сниппеты, скачивание образов, пользователи, пулы, SDN, HA, firewall | VM (`proxmox_vm_qemu`), LXC |
| Аутентификация | API-токен, пароль, SSH для части операций (загрузка файлов) | Токен, пароль |
| Целевая версия PVE | 9.x | 8.x/9.x |

Для новых проектов берут **bpg/proxmox**. В нём живут два поколения ресурсов:
`proxmox_virtual_environment_*` (зрелые) и новые с коротким префиксом `proxmox_*`.

```hcl
# terraform/proxmox/main.tf
terraform {
  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.114"
    }
  }
}

provider "proxmox" {
  endpoint = "https://10.10.10.11:8006/"
  insecure = true                  # самоподписанный сертификат стенда
  # токен — из окружения: export PROXMOX_VE_API_TOKEN='terraform@pve!tf=&lt;secret&gt;'
}

resource "proxmox_virtual_environment_vm" "app" {
  for_each  = toset(["app11", "app12"])
  name      = each.key
  node_name = "pve1"

  clone {
    vm_id = 9000                   # шаблон из темы 04
    full  = false                  # linked clone
  }
  cpu {
    cores = 2
    type  = "host"
  }
  memory {
    dedicated = 2048
  }
  agent {
    enabled = true                 # ⚠️ агент должен быть в шаблоне, иначе apply ждёт таймаут
  }
  network_device {
    bridge = "vmbr0"
  }
  initialization {
    ip_config {
      ipv4 {
        address = "dhcp"
      }
    }
    user_account {
      username = "devops"
      keys     = [trimspace(file(pathexpand("~/.ssh/id_ed25519.pub")))]
    }
  }
  stop_on_destroy = true
}

output "ips" {
  # адреса от агента по интерфейсам: [0] — lo, [1] — первый NIC
  value = { for k, vm in proxmox_virtual_environment_vm.app : k => vm.ipv4_addresses[1][0] }
}
```text
LXC — ресурс `proxmox_virtual_environment_container`, загрузка облачного образа на узел —
`proxmox_virtual_environment_download_file`.

---

## 7. Ansible: динамический inventory

Зачем и как устроены inventory-плагины — [../Ansible/03_inventory.md](/ansible/03-inventory),
раздел 6. Здесь — два плагина для on-prem.

**Вариант 0 — из outputs Terraform** (просто и надёжно для маленьких стендов):
```bash
{ echo "[web]"; terraform output -json ips \
  | jq -r 'to_entries[] | "\(.key) ansible_host=\(.value) ansible_user=devops"'; } > inventory.ini
```text
**community.libvirt** (коллекция 2.x): VM с хоста libvirt.
```yaml
# inventory/kvm.libvirt.yml
plugin: community.libvirt.libvirt
uri: qemu:///system
filter: '^web'                      # опция из 2.3.0: только VM с именами web*
compose:
  ansible_connection: "'ssh'"       # ⚠️ по умолчанию плагин ходит через guest agent (libvirt_qemu)
  ansible_user: "'devops'"
  ansible_host: >-
    interface_addresses | dict2items
    | rejectattr('key', 'equalto', 'lo')
    | map(attribute='value.addrs') | flatten
    | selectattr('type', 'equalto', 0)
    | map(attribute='addr') | first
```text
Адреса плагин берёт у **qemu-guest-agent**, а Python-модуль `libvirt` должен стоять в том же
окружении, где Ansible (`python3-libvirt` из apt или `pip install libvirt-python`).

**community.proxmox** (Proxmox-модули и плагин переехали сюда из `community.general`; старое
имя `community.general.proxmox` — только перенаправление, помечено устаревшим):
```yaml
# inventory/lab.proxmox.yml   ← имя файла ОБЯЗАНО кончаться на proxmox.yml
plugin: community.proxmox.proxmox
url: https://10.10.10.11:8006
user: ansible@pve
token_id: inv                        # секрет — в переменной окружения PROXMOX_TOKEN_SECRET
validate_certs: false
want_facts: true
exclude_nodes: true
keyed_groups:
  - key: proxmox_tags_parsed         # теги VM в Proxmox → группы tag_web, tag_db
    separator: ""
    prefix: tag_
compose:
  ansible_host: (proxmox_agent_interfaces | rejectattr('name', 'equalto', 'lo') | first)['ip-addresses'][0].split('/')[0]
  ansible_user: "'devops'"
```text
```bash
ansible-galaxy collection install community.libvirt community.proxmox
ansible-inventory -i inventory/lab.proxmox.yml --graph
ansible -i inventory/lab.proxmox.yml tag_web -m ping
```text
Связка: Terraform ставит VM **теги** (`tags = ["web"]` в bpg) → плагин строит группы по тегам →
плейбук целится в `tag_web`. Никаких списков IP руками.

---

## 8. Конвейер golden image

```text
 git push (packer/, ansible/roles/base)         + по расписанию (1-е число) и при критичных CVE
        │
        ▼
 CI: packer fmt -check → packer validate → packer build
        │   облачный образ (SHA256) + обновления + агент + роль base (hardening, мониторинг) + clean
        ▼
 артефакт: noble-golden-2026.09.27.qcow2  →  шаблон Proxmox 9100 / пул libvirt / vSphere Content Library
        │
        ▼
 тест: Terraform поднимает VM из нового образа → SSH по ключу, агент отвечает,
       cloud-init status: done, проверки hardening (например, goss/InSpec) → destroy
        │ ok
        ▼
 публикация: версия + указатель «latest»; хранить N последних, старые удалять
        │
        ▼
 окружения: Terraform ссылается на версию шаблона → новые VM из свежего образа,
            старые пересоздаются по графику (rolling), а не «apt upgrade руками»
```text
Что это даёт: одинаковые VM во всех окружениях, быстрый старт (обновления уже внутри),
аудит («из какого образа эта VM»), откат на прошлую версию образа.

---

## 9. VMware vSphere — обзор для вакансий

VMware ты, скорее всего, увидишь на работе раньше, чем в лабе. Минимум — понимать термины
и знать, чем его автоматизируют.

| Термин | Что это | Аналог в Proxmox/KVM |
|--------|---------|----------------------|
| **ESXi** | Гипервизор type-1 на хосте | Узел Proxmox / KVM-хост |
| **vCenter Server** (VCSA) | Центральное управление: кластеры, права, API | Кластер Proxmox, oVirt engine |
| Datacenter / Cluster | Группа хостов с общими ресурсами | Datacenter / кластер |
| **Datastore** (VMFS, NFS, vSAN) | Хранилище дисков VM (`.vmdk`) | Storage: LVM, NFS, Ceph |
| vSwitch / **vDS**, port group | Виртуальный свитч; группа портов с VLAN ID | Linux bridge, `vmbr0` + `tag` |
| **vMotion** / Storage vMotion | Живая миграция VM / её дисков | `qm migrate --online` / `qm disk move` |
| **DRS** | Автобалансировка VM по хостам кластера | CRS (в PVE 9.2 — динамический) |
| **vSphere HA** | Перезапуск VM на других хостах при отказе | `ha-manager` |
| FT (Fault Tolerance) | Теневая копия VM на другом хосте, без простоя | Прямого аналога нет |
| Templates, Content Library | Шаблоны и образы | Шаблоны Proxmox |
| VMware Tools / `open-vm-tools` | Агент в госте | `qemu-guest-agent` |

**govc** — CLI к vSphere API (проект `govmomi`):
```bash
export GOVC_URL=vcenter.corp.local GOVC_USERNAME='devops@vsphere.local' GOVC_PASSWORD='...' GOVC_INSECURE=1
govc about
govc ls /DC1/vm
govc vm.info -r app01
govc vm.power -on app01
govc snapshot.create -vm app01 before-upgrade
govc vm.clone -vm tpl-ubuntu-2404 -on=false -folder /DC1/vm/apps app02
govc datastore.ls -ds datastore1
govc find / -type m -runtime.powerState poweredOn
```text
**Terraform:** провайдер переехал в `vmware/vsphere` (ветка 2.x; `hashicorp/vsphere` больше не
обновляется). Схема клона из шаблона:
```hcl
# провайдер vmware/vsphere ~> 2.17; data-источники vsphere_datacenter, vsphere_compute_cluster,
# vsphere_datastore, vsphere_network, vsphere_virtual_machine (шаблон) ищут объекты по имени
resource "vsphere_virtual_machine" "app" {
  name             = "app01"
  resource_pool_id = data.vsphere_compute_cluster.cl.resource_pool_id
  datastore_id     = data.vsphere_datastore.ds.id
  num_cpus         = 2
  memory           = 4096
  guest_id         = data.vsphere_virtual_machine.tpl.guest_id
  network_interface {
    network_id = data.vsphere_network.vlan20.id      # port group с VLAN 20
  }
  disk {
    label = "disk0"
    size  = data.vsphere_virtual_machine.tpl.disks[0].size
  }
  clone {
    template_uuid = data.vsphere_virtual_machine.tpl.id
  }
}
```text
Образы для vSphere собирают Packer'ом (builders `vsphere-iso`, `vsphere-clone`; плагин теперь
развивает VMware в `vmware/packer-plugin-vsphere`), инвентарь — `community.vmware` в Ansible.

---

## 10. Грабли

| Симптом | Причина | Что делать |
|---------|---------|-----------|
| Пример из статьи для libvirt-провайдера падает на `terraform validate` | Статья для 0.8, у тебя 0.9 (другая схема) | Документация своей версии, `version = "~> 0.9.9"` |
| `terraform apply` в Proxmox висит минутами на создании VM | `agent.enabled = true`, а агента в шаблоне нет | Вшить агент в шаблон или `enabled = false` |
| Клоны с одним IP / одинаковыми host keys | Шаблон не «обезличен» | `cloud-init clean --machine-id --seed`, удалить `ssh_host_*` |
| Packer ждёт SSH вечно | cloud-init не получил `cidata`, пароль/ключ не применились | Смотреть консоль сборочной VM (`headless = false`), `cd_label = "cidata"` |
| Packer proxmox-clone: не находит IP | Нет guest agent в шаблоне | Агент в базовом шаблоне, `vm_interface` при нескольких NIC |
| Inventory community.proxmox пустой | Файл не кончается на `proxmox.yml` | Переименовать |
| Libvirt-inventory: Ansible «ходит» странно и медленно | Подключение через guest agent по умолчанию | `compose: ansible_connection: "'ssh'"` |
| `community.general.proxmox` — предупреждение | Плагин переехал | `community.proxmox.proxmox` |
| Секрет в user-data виден всем | user-data не секретен | Vault/переменные CI, в user-data — только ключ доступа |
| Шаблон «ubuntu-final» полгода без обновлений | Нет конвейера | Packer по расписанию + версия в имени |
| Токен Proxmox лежит в `terraform.tfvars` в git | Секрет в коде | `PROXMOX_VE_API_TOKEN` из секретов CI |

---

## 💼 Как это в DevOps

- **«VM как код»:** запрос «нужно 3 VM под сервис» закрывается merge request'ом в репозиторий
  Terraform, а не заявкой админам. Ревью плана — как ревью кода.
- **Golden image** — ответ на аудит ИБ («все VM с актуальными патчами и CIS-базой») и на
  скорость («VM готова за минуту»).
- **Один и тот же user-data** работает на libvirt, Proxmox, VMware и в облаке — cloud-init
  стоит выучить один раз.
- **Смена платформы** (VMware → Proxmox) при таком подходе — замена провайдера Terraform и
  builder'а Packer; роли Ansible и cloud-init остаются.
- В вакансиях on-prem чаще всего пишут «VMware + Terraform + Ansible» или «Proxmox/KVM +
  Terraform + Ansible» — это ровно эта тема.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Проверить user-data | `cloud-init schema -c user-data.yaml --annotate` |
| Статус cloud-init | `cloud-init status --wait --long` |
| Что получил cloud-init | `sudo cloud-init query --all` |
| Обезличить образ | `sudo cloud-init clean --logs --machine-id --seed --configs all; rm /etc/ssh/ssh_host_*` |
| Packer | `packer init . && packer validate . && packer build .` |
| Packer из облачного образа | `source "qemu"`: `disk_image = true`, `cd_label = "cidata"`, `cd_content` |
| Packer в Proxmox | `source "proxmox-clone"` / `"proxmox-iso"`, токен `user@pve!id` |
| Terraform libvirt | `dmacvicar/libvirt ~> 0.9.9`: `libvirt_volume` + `libvirt_cloudinit_disk` + `libvirt_domain` |
| Terraform Proxmox | `bpg/proxmox`: `proxmox_virtual_environment_vm` с `clone` и `initialization` |
| Токен в окружении | `PROXMOX_VE_API_TOKEN` (bpg), `PROXMOX_TOKEN_SECRET` (inventory), `PKR_VAR_*` (Packer) |
| Inventory libvirt | `plugin: community.libvirt.libvirt` + `compose: ansible_host / ansible_connection` |
| Inventory Proxmox | `plugin: community.proxmox.proxmox`, файл `*.proxmox.yml` |
| Проверить inventory | `ansible-inventory -i &lt;src&gt; --graph` |
| vSphere CLI | `govc ls`, `govc vm.info`, `govc vm.power -on`, `govc vm.clone` |
| Terraform vSphere | `vmware/vsphere`: `vsphere_virtual_machine` + `clone { template_uuid }` |

---

## 🧠 Что запомнить

1. Три слоя: образ (Packer, редко) → инфраструктура (Terraform) → конфигурация (Ansible); cloud-init склеивает первый старт.
2. Хороший шаблон: облачный образ, cloud-init, агент, обновления, **без** machine-id и host keys, версия в имени.
3. cloud-init: `user-data` — что сделать, `meta-data` — кто ты (`instance-id`), `network-config` — сеть (синтаксис netplan).
4. Большинство модулей cloud-init — один раз на экземпляр; `bootcmd` — каждую загрузку; сменился `instance-id` — «новая VM».
5. Отладка cloud-init: `status --long`, `/var/log/cloud-init*.log`, `query`, `schema --annotate`.
6. Packer: `qemu` с `disk_image = true` для облачных образов; `proxmox-clone`/`proxmox-iso` для Proxmox; IP клона — через агент.
7. dmacvicar/libvirt 0.9 — переписан, схема как XML libvirt; старые примеры не работают.
8. Для Proxmox — bpg/proxmox с API-токеном; агент в шаблоне обязателен, если `agent.enabled = true`.
9. Динамический inventory: `community.libvirt.libvirt` (адреса через агент, переопредели `ansible_connection`) и `community.proxmox.proxmox` (файл `*.proxmox.yml`, группы по тегам).
10. VMware: ESXi + vCenter, datastore, vDS/port group, vMotion, DRS, HA; автоматизация — govc, `vmware/vsphere`, Packer vsphere-*.

➡️ Дальше: [07_practice_labs.md](/mlops/07-practice-labs) · задачи: 06_virt_automation_tasks.md


---

### Блок A. Теория


**A1.** Какие три слоя автоматизации VM и что в какой слой класть? Где место cloud-init?

<details><summary>Ответ</summary>

Образ (Packer): ОС, обновления, агент, базовый hardening — всё общее и редко меняющееся.
Инфраструктура (Terraform): количество и размеры VM, сети, диски. Конфигурация (Ansible):
сервисы и их настройки. cloud-init — первый старт: hostname, пользователь, ключ, IP; мост
между шаблоном и Terraform/Ansible.

</details>

**A2.** ⭐ Что должно быть в хорошем шаблоне VM и чего в нём быть не должно? Почему `machine-id`
так важен?

<details><summary>Ответ</summary>

Должно: облачный образ с проверенной суммой, cloud-init, агент гипервизора, свежие
обновления, virtio и серийная консоль, версия в имени. Не должно: `/etc/machine-id`,
SSH host keys, состояния cloud-init, паролей, чужих ключей, истории и логов. `machine-id`
используется systemd для DHCP client ID, journald и прочего — одинаковый id у клонов даёт
одинаковые IP от DHCP и путаницу в логах и мониторинге.

</details>

**A3.** Что такое datasource cloud-init? Назови четыре.

<details><summary>Ответ</summary>

Источник, откуда cloud-init берёт данные экземпляра. NoCloud (ISO/диск `cidata`,
libvirt, Proxmox), ConfigDrive (OpenStack), VMware (guestinfo), EC2/GCE/Azure (сервисы
метаданных облаков), LXD/Incus.

</details>

**A4.** Какие стадии у cloud-init? Когда выполняются `bootcmd`, `runcmd`, `packages`?

<details><summary>Ответ</summary>

local (найти datasource, применить сеть) → network (сеть, user-data; `bootcmd`,
`write_files`, `growpart`, пользователи, ключи) → config (ntp, timezone, apt) → final
(`packages`, скрипты `runcmd`, final_message). `bootcmd` — на каждой загрузке; `runcmd` и
`packages` — один раз на экземпляр, в стадии final.

</details>

**A5.** Чем отличаются `user-data`, `vendor-data`, `meta-data` и `network-config`?

<details><summary>Ответ</summary>

user-data — что сделать (от пользователя); vendor-data — настройки платформы,
сливаются с user-data; meta-data — данные экземпляра (`instance-id`, hostname);
network-config — сеть (v2, синтаксис netplan), применяется в самой ранней стадии.

</details>

**A6.** Почему в user-data нельзя класть секреты? Как тогда передать VM пароль к БД?

<details><summary>Ответ</summary>

user-data хранится в datasource (ISO, API гипервизора, сервис метаданных) и в VM
в `/var/lib/cloud/instance/`; его видит любой, у кого есть доступ к этим местам, и он
попадает в стейт Terraform. Пароль к БД VM получает из Vault/секрет-хранилища (через
AppRole/токен с коротким сроком) или его раскатывает Ansible из Vault/ansible-vault.

</details>

**A7.** Как отлаживать cloud-init? Пять команд или файлов.

<details><summary>Ответ</summary>

`cloud-init status --wait --long`, `/var/log/cloud-init.log`,
`/var/log/cloud-init-output.log`, `cloud-init query --all`/`query userdata`,
`cloud-init schema -c file --annotate`; повторный прогон — `cloud-init clean --logs --reboot`.

</details>

**A8.** Что делает Packer? Что значат `disk_image = true`, `cd_label` и `cd_content` у builder'а `qemu`?

<details><summary>Ответ</summary>

Packer поднимает временную VM, выполняет провижинеры и сохраняет результат как
образ/шаблон. `disk_image = true` — на входе готовый диск (облачный образ), а не установщик;
`cd_content` — файлы, из которых Packer соберёт ISO, `cd_label = "cidata"` — метка тома,
по которой cloud-init узнаёт NoCloud-источник.

</details>

**A9.** ⭐ Зачем в конце сборки образа `cloud-init clean --logs --machine-id --seed --configs all`
и удаление `ssh_host_*`?

<details><summary>Ответ</summary>

Чтобы каждая VM из образа стала уникальной: пустой `machine-id` сгенерируется заново,
сброшенное состояние cloud-init заставит его отработать как на новом экземпляре, `--seed`
уберёт данные сборки, `--configs all` удалит сгенерированные конфиги (sshd с паролями,
netplan), а удалённые host keys будут созданы заново — иначе у всех VM один отпечаток SSH.

</details>

**A10.** Что изменилось в провайдере dmacvicar/libvirt в ветке 0.9? Чем это грозит при
копировании примеров из интернета?

<details><summary>Ответ</summary>

Провайдер переписан на Terraform Plugin Framework, схема повторяет XML libvirt
(`os`, `devices.disks`, `devices.interfaces` как вложенные объекты), тома из URL — через
`create.content.url`, формат задаётся явно. Примеры для 0.7/0.8 не проходят `validate`,
а ограничение версии `>= 0.7` молча притянет 0.9 и сломает старый код.

</details>

**A11.** bpg/proxmox или Telmate/proxmox — что выбрать в 2026 и почему?

<details><summary>Ответ</summary>

bpg/proxmox: частые стабильные релизы, широкое покрытие API (VM, LXC, файлы, SDN,
пользователи, HA), токены, целится в PVE 9. Telmate годами в release candidate 3.0.2.
Для новых проектов — bpg.

</details>

**A12.** Как Terraform (bpg) передаёт VM пользователя, ключ и IP?

<details><summary>Ответ</summary>

Через блок `initialization`: `user_account` (имя, ключи, пароль), `ip_config`
(DHCP или статика со шлюзом), `dns`; при необходимости — свой `user_data_file_id` (сниппет).
Provider пишет это в cloud-init-диск VM в Proxmox, а cloud-init в госте применяет.

</details>

**A13.** ⭐ Сравни inventory-плагины `community.libvirt.libvirt` и `community.proxmox.proxmox`:
откуда берут адреса, какие ловушки?

<details><summary>Ответ</summary>

libvirt-плагин опрашивает libvirt по URI, IP берёт у qemu-guest-agent, по умолчанию
ставит подключение через агента (`community.libvirt.libvirt_qemu`) — для SSH нужно
переопределить `ansible_connection` и `ansible_host` через `compose`; нужен Python-модуль
`libvirt`. Proxmox-плагин ходит в API по токену, файл обязан кончаться на `proxmox.yml`,
IP даёт `proxmox_agent_interfaces` (тоже агент, `want_facts: true`), группы — по тегам.

</details>

**A14.** Опиши этапы конвейера golden image.

<details><summary>Ответ</summary>

Изменение в git или расписание → lint/validate → Packer build (облачный образ +
обновления + агент + hardening + clean) → тест (поднять VM, проверить SSH, агента,
cloud-init, hardening, уничтожить) → публикация с версией и указателем latest, чистка старых
версий → окружения переходят на новую версию, VM пересоздаются по графику.

</details>

**A15.** ⭐ Чем отличаются vMotion, vSphere HA, DRS и FT?

<details><summary>Ответ</summary>

vMotion — плановая живая миграция работающей VM между хостами без простоя. HA —
автоматический перезапуск VM на других хостах после отказа хоста (простой = загрузка гостя).
DRS — автоматическая балансировка VM по хостам кластера (через vMotion) и правила affinity.
FT — теневая копия VM, идущая синхронно на другом хосте: отказ хоста без простоя вообще.

</details>

**A16.** Чем автоматизируют vSphere? Что поменялось с провайдером Terraform?

<details><summary>Ответ</summary>

govc (govmomi), PowerCLI, Terraform, Packer (vsphere-iso, vsphere-clone),
Ansible (`community.vmware`). Провайдер Terraform переехал в `vmware/vsphere`, старый
`hashicorp/vsphere` больше не обновляется; плагин Packer тоже развивает VMware.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  #cloud-config
```text
<details><summary>Ответ</summary>

⚠️ Список `users` без `default` отменяет создание стандартного пользователя, а
`ssh_authorized_keys` верхнего уровня предназначен именно ему — ключ уйдёт в никуда. Ключ
надо положить внутрь записи `devops` (или добавить `default` в список). У `devops` ещё и
нет `shell` и `groups`.

</details>

```text:no-line-numbers
     users:
```text
```text:no-line-numbers
       - name: devops
```text
```text:no-line-numbers
         sudo: "ALL=(ALL) NOPASSWD:ALL"
```text
```text:no-line-numbers
     ssh_authorized_keys:
```text
```text:no-line-numbers
       - ssh-ed25519 AAAA... me@laptop
```text
```text:no-line-numbers
     # «зашёл бы как devops по ключу»
```text
```text:no-line-numbers
B2.  terraform {
```text
<details><summary>Ответ</summary>

⚠️ Синтаксис 0.8 (`cloudinit`, `network_interface`, `disk.volume_id`), а `>= 0.7`
притянет 0.9 с новой схемой — `validate` упадёт. Переписать под 0.9 (`devices = { disks,
interfaces }`) и закрепить `~> 0.9.9` — или осознанно `~> 0.8.0` для старого кода.

</details>

```text:no-line-numbers
       required_providers {
```text
```text:no-line-numbers
         libvirt = { source = "dmacvicar/libvirt", version = ">= 0.7" }
```text
```text:no-line-numbers
       }
```text
```text:no-line-numbers
     }
```text
```text:no-line-numbers
     resource "libvirt_domain" "vm" {
```text
```text:no-line-numbers
       name      = "web1"
```text
```text:no-line-numbers
       memory    = 1024
```text
```text:no-line-numbers
       cloudinit = libvirt_cloudinit_disk.seed.id
```text
```text:no-line-numbers
       network_interface { network_name = "default" }
```text
```text:no-line-numbers
       disk { volume_id = libvirt_volume.disk.id }
```text
```text:no-line-numbers
     }
```text
```text:no-line-numbers
B3.  source "qemu" "noble" {
```text
<details><summary>Ответ</summary>

⚠️ Без NoCloud-источника cloud-init не задаст пароль `ubuntu` — у облачного образа
входа нет, Packer вечно ждёт SSH. Нужны `cd_label = "cidata"` и `cd_content` с user-data
(или `http_directory` + параметры ядра — для ISO-сборок).

</details>

```text:no-line-numbers
       iso_url      = ".../noble-server-cloudimg-amd64.img"
```text
```text:no-line-numbers
       disk_image   = true
```text
```text:no-line-numbers
       ssh_username = "ubuntu"
```text
```text:no-line-numbers
       ssh_password = "packer"
```text
```text:no-line-numbers
       # cd_content и cd_label не указаны
```text
```text:no-line-numbers
     }
```text
```text:no-line-numbers
B4.  # bpg/proxmox, шаблон 9000 без qemu-guest-agent в образе
```text
<details><summary>Ответ</summary>

⚠️ Провайдер ждёт ответа агента (таймаут по умолчанию — минуты), чтобы получить IP.
Вшить `qemu-guest-agent` в шаблон или `agent { enabled = false }` и статические адреса.

</details>

```text:no-line-numbers
     agent { enabled = true }
```text
```text:no-line-numbers
     # terraform apply: «Still creating... [10m0s elapsed]»
```text
```text:no-line-numbers
B5.  provisioner "shell" {
```text
<details><summary>Ответ</summary>

⚠️ Провижинер стартовал, пока cloud-init/unattended-upgrades ещё держат apt. Первой
командой `cloud-init status --wait` (и дождаться блокировки/выключить apt-daily на время сборки).

</details>

```text:no-line-numbers
       inline = ["sudo apt-get update", "sudo apt-get -y install nginx"]
```text
```text:no-line-numbers
     }
```text
```text:no-line-numbers
     # E: Could not get lock /var/lib/dpkg/lock-frontend. It is held by process 912 (apt-get)
```text
```text:no-line-numbers
B6.  $ ls inventory/
```text
<details><summary>Ответ</summary>

⚠️ Файл должен кончаться на `proxmox.yml`/`proxmox.yaml`, иначе плагин его пропускает
(видно в `-vvv`). Переименовать в `pve.proxmox.yml`.

</details>

```text:no-line-numbers
     pve.yml          # plugin: community.proxmox.proxmox
```text
```text:no-line-numbers
     $ ansible-inventory -i inventory/pve.yml --graph
```text
```text:no-line-numbers
     @all:
```text
```text:no-line-numbers
       |--@ungrouped:
```text
```text:no-line-numbers
B7.  # inventory/kvm.yml
```text
<details><summary>Ответ</summary>

⚠️ Плагин по умолчанию ставит `ansible_connection` через guest agent — медленно и не
работает без агента. Переопределить `ansible_connection: "'ssh'"`, `ansible_host`,
`ansible_user` в `compose`.

</details>

```text:no-line-numbers
     plugin: community.libvirt.libvirt
```text
```text:no-line-numbers
     uri: qemu:///system
```text
```text:no-line-numbers
     # ansible web1 -m ping → медленно / «guest agent is not connected»
```text
```text:no-line-numbers
B8.  runcmd:
```text
<details><summary>Ответ</summary>

⚠️ Пароль в user-data виден в datasource, в `/var/lib/cloud/instance/` и в стейте
Terraform. Секрет — из Vault/ansible-vault на этапе конфигурации.

</details>

```text:no-line-numbers
       - [sh, -c, "echo 'DB_PASSWORD=S3cr3t!' >> /etc/app.env"]
```text
```text:no-line-numbers
B9.  resource "libvirt_volume" "base" {
```text
<details><summary>Ответ</summary>

⚠️ `current` — плавающая ссылка: каждое создание берёт свежий образ, окружения
расходятся. Закрепить датированный релиз (`/noble/&lt;дата&gt;/`) или свой версионный golden image.

</details>

```text:no-line-numbers
       ...
```text
```text:no-line-numbers
       create = { content = { url = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img" } }
```text
```text:no-line-numbers
     }
```text
```text:no-line-numbers
     # stage собрали в марте, prod — в сентябре: «почему пакеты разные?»
```text
```text:no-line-numbers
B10.  # golden image: user-data сборки с password: packer + ssh_pwauth: true,
```text
<details><summary>Ответ</summary>

⚠️ У `ubuntu` остался пароль `packer`, а в sshd — `PasswordAuthentication yes` от
cloud-init: любой клон пускает по паролю. Нужно `passwd -l ubuntu`, `cloud-init clean
... --configs all` (или удалить `/etc/ssh/sshd_config.d/50-cloud-init.conf`) и проверка
в тесте образа.

</details>

```text:no-line-numbers
     # в конце только «sudo cloud-init clean --logs»
```text
```text:no-line-numbers
B11.  #!/bin/bash
```text
<details><summary>Ответ</summary>

⚠️ Пароль администратора в репозитории и cron, проверка сертификата выключена,
учётка admin для одной операции. Сервисная учётка с минимальными правами, секрет из
хранилища, `GOVC_INSECURE` не использовать (доверить CA vCenter), `-force` — только осознанно.

</details>

```text:no-line-numbers
     export GOVC_URL=vcenter.corp.local GOVC_USERNAME=admin GOVC_PASSWORD='P@ssw0rd' GOVC_INSECURE=1
```text
```text:no-line-numbers
     govc vm.power -off -force app01
```text
```text:no-line-numbers
     # скрипт лежит в репозитории, запускается из cron
```text
```text:no-line-numbers
B12.  «Включим vMotion — и отказ хоста нам не страшен»
```text
<details><summary>Ответ</summary>

⚠️ vMotion — плановая миграция исправной VM; от отказа хоста защищает vSphere HA
(перезапуск VM), от простоя при отказе — FT.

</details>


---

### Блок C. Практика


### C1. 🔑 cloud-init до мелочей
**1.** Подними VM `ci1` через `virt-install` с user-data из конспекта (раздел 3) и network-config со
   статикой `10.10.10.60` по MAC (MAC задай в `--network ...,mac=52:54:00:10:00:01`).

<details><summary>Ответ</summary>

`virt-install ... --network network=virt-lab,model=virtio,mac=52:54:00:10:00:01
--cloud-init user-data=user-data.yaml,meta-data=meta-data.yaml,network-config=network-config.yaml`.
В госте интерфейс называется `mgmt0`, адрес статический. Ошибка отступа видна в
`cloud-init status --long` (`status: error` или `degraded` с `recoverable_errors`) и в
`/var/log/cloud-init.log` (сообщение о невалидном YAML / schema).

</details>

**2.** Проверь: имя, пользователь, `timezone`, `/etc/motd`, статический IP, `cloud-init status --long`.

<details><summary>Ответ</summary>

`cat /etc/machine-id` и `ssh-keyscan &lt;IP&gt;` различаются у двух VM; `ssh -o
PubkeyAuthentication=no ubuntu@IP` → `Permission denied (publickey)`; `systemctl status
qemu-guest-agent` — активен; `apt list --upgradable` — пусто или почти пусто на дату сборки.

</details>

**3.** Проверь user-data командой `cloud-init schema -c ... --annotate` внутри VM.

<details><summary>Ответ</summary>

Изменение `vcpu` — update in-place (провайдер переопределит домен, применится после
перезапуска VM, в зависимости от версии — с автоматическим рестартом); удаление элемента из
`for_each` — destroy только этой VM и её томов. После `destroy` в пуле нет томов `web*`
и базового (если он тоже в коде).

</details>

**4.** Специально сломай отступ в user-data, пересоздай VM и найди ошибку в логах cloud-init.

<details><summary>Ответ</summary>

Плейбук: `ansible.builtin.apt: name=nginx`, `ansible.builtin.copy` с `content: "hello from &#123;&#123; inventory_hostname &#125;&#125;"`
в `/var/www/html/index.html`. Для плагина libvirt в госте должен работать `qemu-guest-agent`
(адреса из `interface_addresses`), на контроллере — Python-модуль `libvirt`.

</details>

### C2. 🔑 Golden image Packer'ом
**1.** Собери образ по разделу 4.1 конспекта.

<details><summary>Ответ</summary>

`virt-install ... --network network=virt-lab,model=virtio,mac=52:54:00:10:00:01
--cloud-init user-data=user-data.yaml,meta-data=meta-data.yaml,network-config=network-config.yaml`.
В госте интерфейс называется `mgmt0`, адрес статический. Ошибка отступа видна в
`cloud-init status --long` (`status: error` или `degraded` с `recoverable_errors`) и в
`/var/log/cloud-init.log` (сообщение о невалидном YAML / schema).

</details>

**2.** Подними из него две VM (`virt-install --import` с `--cloud-init`, overlay поверх образа).

<details><summary>Ответ</summary>

`cat /etc/machine-id` и `ssh-keyscan &lt;IP&gt;` различаются у двух VM; `ssh -o
PubkeyAuthentication=no ubuntu@IP` → `Permission denied (publickey)`; `systemctl status
qemu-guest-agent` — активен; `apt list --upgradable` — пусто или почти пусто на дату сборки.

</details>

**3.** Докажи «обезличенность»: разные `/etc/machine-id` и SSH host keys, по паролю `packer` не
   пускает (`ssh -o PubkeyAuthentication=no ubuntu@IP`), агент стоит, обновления на месте.

<details><summary>Ответ</summary>

Изменение `vcpu` — update in-place (провайдер переопределит домен, применится после
перезапуска VM, в зависимости от версии — с автоматическим рестартом); удаление элемента из
`for_each` — destroy только этой VM и её томов. После `destroy` в пуле нет томов `web*`
и базового (если он тоже в коде).

</details>

### C3. 🔑 Terraform + libvirt
**1.** Опиши две VM `web1`, `web2` по разделу 5 конспекта, но с базой из своего golden image
   (`url = "/путь/к/noble-golden-....qcow2"`).

<details><summary>Ответ</summary>

`virt-install ... --network network=virt-lab,model=virtio,mac=52:54:00:10:00:01
--cloud-init user-data=user-data.yaml,meta-data=meta-data.yaml,network-config=network-config.yaml`.
В госте интерфейс называется `mgmt0`, адрес статический. Ошибка отступа видна в
`cloud-init status --long` (`status: error` или `degraded` с `recoverable_errors`) и в
`/var/log/cloud-init.log` (сообщение о невалидном YAML / schema).

</details>

**2.** `terraform apply`, `terraform output -json ips`, SSH на обе.

<details><summary>Ответ</summary>

`cat /etc/machine-id` и `ssh-keyscan &lt;IP&gt;` различаются у двух VM; `ssh -o
PubkeyAuthentication=no ubuntu@IP` → `Permission denied (publickey)`; `systemctl status
qemu-guest-agent` — активен; `apt list --upgradable` — пусто или почти пусто на дату сборки.

</details>

**3.** Поменяй `vcpu` у одной — что покажет `plan`? Удали одну из `locals.vms` — что будет?

<details><summary>Ответ</summary>

Изменение `vcpu` — update in-place (провайдер переопределит домен, применится после
перезапуска VM, в зависимости от версии — с автоматическим рестартом); удаление элемента из
`for_each` — destroy только этой VM и её томов. После `destroy` в пуле нет томов `web*`
и базового (если он тоже в коде).

</details>

**4.** `terraform destroy` — проверь, что в пуле не осталось мусора (`virsh vol-list default`).

<details><summary>Ответ</summary>

Плейбук: `ansible.builtin.apt: name=nginx`, `ansible.builtin.copy` с `content: "hello from &#123;&#123; inventory_hostname &#125;&#125;"`
в `/var/www/html/index.html`. Для плагина libvirt в госте должен работать `qemu-guest-agent`
(адреса из `interface_addresses`), на контроллере — Python-модуль `libvirt`.

</details>

### C4. 🔑 Ansible поверх Terraform
**1.** Сгенерируй `inventory.ini` из outputs и прогони плейбук: nginx + страница «hello from &#123;&#123; inventory_hostname &#125;&#125;».

<details><summary>Ответ</summary>

`virt-install ... --network network=virt-lab,model=virtio,mac=52:54:00:10:00:01
--cloud-init user-data=user-data.yaml,meta-data=meta-data.yaml,network-config=network-config.yaml`.
В госте интерфейс называется `mgmt0`, адрес статический. Ошибка отступа видна в
`cloud-init status --long` (`status: error` или `degraded` с `recoverable_errors`) и в
`/var/log/cloud-init.log` (сообщение о невалидном YAML / schema).

</details>

**2.** Настрой `community.libvirt.libvirt` с `compose` из конспекта, проверь `ansible-inventory --graph`
   и тот же плейбук. Что нужно в госте, чтобы плагин узнал IP?

<details><summary>Ответ</summary>

`cat /etc/machine-id` и `ssh-keyscan &lt;IP&gt;` различаются у двух VM; `ssh -o
PubkeyAuthentication=no ubuntu@IP` → `Permission denied (publickey)`; `systemctl status
qemu-guest-agent` — активен; `apt list --upgradable` — пусто или почти пусто на дату сборки.

</details>

### C5. Terraform bpg + inventory по тегам
**1.** На `pve1` через bpg создай `app11`, `app12` из шаблона 9000 с тегом `web`.

<details><summary>Ответ</summary>

`virt-install ... --network network=virt-lab,model=virtio,mac=52:54:00:10:00:01
--cloud-init user-data=user-data.yaml,meta-data=meta-data.yaml,network-config=network-config.yaml`.
В госте интерфейс называется `mgmt0`, адрес статический. Ошибка отступа видна в
`cloud-init status --long` (`status: error` или `degraded` с `recoverable_errors`) и в
`/var/log/cloud-init.log` (сообщение о невалидном YAML / schema).

</details>

**2.** Настрой `lab.proxmox.yml`, проверь группу `tag_web`, пингани её.

<details><summary>Ответ</summary>

`cat /etc/machine-id` и `ssh-keyscan &lt;IP&gt;` различаются у двух VM; `ssh -o
PubkeyAuthentication=no ubuntu@IP` → `Permission denied (publickey)`; `systemctl status
qemu-guest-agent` — активен; `apt list --upgradable` — пусто или почти пусто на дату сборки.

</details>

**3.** Поменяй `memory.dedicated` — применится ли на ходу или VM перезагрузится? Посмотри `plan`.

<details><summary>Ответ</summary>

Изменение `vcpu` — update in-place (провайдер переопределит домен, применится после
перезапуска VM, в зависимости от версии — с автоматическим рестартом); удаление элемента из
`for_each` — destroy только этой VM и её томов. После `destroy` в пуле нет томов `web*`
и базового (если он тоже в коде).

</details>

### C6. Packer proxmox-clone
Собери шаблон 9100 `noble-golden-2026-09` из 9000 с шагом `apt full-upgrade` и установкой
`chrony`. Склонируй из него VM и сравни версии пакетов с клоном 9000.

### C7. Конвейер на бумаге
Напиши `.gitlab-ci.yml` (или GitHub Actions) для golden image: стадии `lint` (packer fmt/validate,
ansible-lint), `build`, `test` (поднять VM Terraform'ом, проверить SSH/агент/cloud-init,
уничтожить), `publish` (версия и указатель latest). Где хранятся токены? Когда запускается?

### C8. VMware по вакансии
Возьми вакансию с VMware и переведи каждое требование в термины темы: «администрирование
vSphere 7/8», «шаблоны VM», «vMotion/DRS/HA», «автоматизация через PowerCLI/Terraform»,
«распределённые коммутаторы и VLAN». Для каждого — аналог в Proxmox и чем ты его делал на стенде.

---

### Блок D. Инциденты


**D1.** Сделали `terraform destroy` учебного окружения — сломались ещё три VM, созданные руками
«на той же базе». Почему?

<details><summary>Ответ</summary>

Базовый том был ресурсом Terraform: `destroy` удалил его, а ручные VM использовали его
как backing file — их overlay потеряли базу. Базовые образы, от которых зависит что-то вне
Terraform, не держать в том же стейте (или `prevent_destroy`), а ручные VM — не строить
на чужих ресурсах.

</details>

**D2.** VM из шаблона становятся доступны только через 10 минут после создания. В user-data
`package_upgrade: true`, в Proxmox — `ciupgrade` по умолчанию. Что улучшить?

<details><summary>Ответ</summary>

Полное обновление пакетов при каждом старте. Перенести обновления в golden image
(Packer раз в месяц), `package_upgrade: false`, в Proxmox `ciupgrade: 0`; тяжёлые пакеты —
тоже в образ.

</details>

**D3.** `ansible-inventory` по Proxmox показывает хосты, но без `ansible_host`, и Ansible
пытается резолвить имена VM через DNS. Причины?

<details><summary>Ответ</summary>

Агент не установлен/не запущен или выключен `agent` у VM → нет
`proxmox_agent_interfaces`; `want_facts: false` → фактов нет; `compose` с ошибкой при
`strict: false` молча не применился. Проверить `ansible-inventory --host &lt;vm&gt;` и `-vvv`.

</details>

**D4.** Новый golden image выкатили — все новые VM недоступны по SSH: роль hardening сменила
порт sshd. Старые VM работают. Что пошло не так в процессе?

<details><summary>Ответ</summary>

В конвейере не было стадии теста (поднять VM и проверить SSH) и постепенной раскатки:
образ ушёл сразу во все окружения. Добавить smoke-тест, раскатывать сначала в dev/stage,
держать прошлую версию образа для отката.

</details>

**D5.** Terraform-стейт для VM в Proxmox лежал на ноутбуке уволившегося коллеги. VM работают,
стейта нет. Как вернуть управление?

<details><summary>Ответ</summary>

Импортировать VM в новый стейт: описать ресурсы в коде и
`terraform import 'proxmox_virtual_environment_vm.app["app11"]' pve1/111` (формат ID bpg —
`узел/vmid`; в Terraform 1.5+ — блоки `import`), затем `plan` должен показать отсутствие
изменений. На будущее — удалённый backend с блокировками (S3/MinIO, GitLab), не на ноутбуке.

</details>

**D6.** VM, перенесённая с VMware на Proxmox, игнорирует cloud-init диск Proxmox: hostname
и ключи не меняются. В госте cloud-init есть. Где искать?

<details><summary>Ответ</summary>

В образе ограничен список datasource (например, `datasource_list: [ VMware, None ]`
в `/etc/cloud/cloud.cfg.d/`), NoCloud/ConfigDrive не опрашивается. Исправить список (добавить
`NoCloud`), `cloud-init clean`, перезагрузить; `cloud-init status --long` покажет
`DataSourceNoCloud`. Заодно — поставить `qemu-guest-agent` вместо VMware Tools.

</details>

**D7.** Аудитор нашёл в Terraform-стейте пароли пользователей VM открытым текстом. Откуда они
там и что делать?

<details><summary>Ответ</summary>

Стейт хранит все атрибуты ресурсов, включая `initialization.user_account.password`
и user-data. Не передавать пароли VM через Terraform (только ключи), хранить стейт в
зашифрованном backend'е с ограниченным доступом, сменить утёкшие пароли. Подробнее о стейте —
[../Left/06_Terraform/00_INDEX.md](/terraform/) (тема 03).

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как ты автоматически создаёшь VM on-prem?

<details><summary>Ответ</summary>

Golden image Packer'ом → Terraform (bpg/proxmox, libvirt или vSphere) создаёт VM из шаблона
   и передаёт cloud-init (пользователь, ключ, IP, теги) → динамический inventory → Ansible
   настраивает сервисы. Всё в git, через CI.

</details>

**2.** Что такое cloud-init и откуда он берёт данные?

<details><summary>Ответ</summary>

Агент первичной настройки: при первом старте находит datasource (NoCloud-ISO, ConfigDrive,
   сервис метаданных облака, guestinfo VMware), применяет network-config, meta-data и user-data:
   пользователи, ключи, пакеты, файлы, команды.

</details>

**3.** Что такое golden image и зачем он нужен?

<details><summary>Ответ</summary>

Эталонный образ с ОС, обновлениями, агентами и hardening, собранный автоматически и
   версионированный. Все VM одинаковые, быстро стартуют, их можно аудировать и откатить.

</details>

**4.** Зачем Packer, если есть Ansible?

<details><summary>Ответ</summary>

Packer делает образ заранее — старт VM быстрый и предсказуемый, нет зависимостей от
   репозиториев в момент создания; Ansible внутри Packer как раз и используется для
   наполнения образа. Ansible на живых VM — для того, что отличается между сервисами.

</details>

**5.** Какие провайдеры Terraform для Proxmox, libvirt и vSphere знаешь?

<details><summary>Ответ</summary>

Proxmox — bpg/proxmox (или Telmate); libvirt — dmacvicar/libvirt (0.9 — новая схема);
   vSphere — vmware/vsphere (бывший hashicorp/vsphere).

</details>

**6.** Как Ansible узнаёт о новых VM?

<details><summary>Ответ</summary>

Динамический inventory: `community.proxmox.proxmox`, `community.libvirt.libvirt`,
   `community.vmware.vmware_vm_inventory`, группы по тегам; либо inventory из outputs Terraform.

</details>

**7.** Как обновляешь парк VM: патчишь на месте или пересоздаёшь?

<details><summary>Ответ</summary>

Предпочтительно пересоздаю (immutable): новый образ → новые VM → переключение → удаление
   старых. Для «питомцев» (БД, легаси) — патчи на месте через Ansible по графику с окнами.

</details>

**8.** Что нужно убрать из VM, прежде чем делать из неё шаблон?

<details><summary>Ответ</summary>

`machine-id`, SSH host keys, состояние cloud-init (`cloud-init clean`), логи, историю,
   временных пользователей и пароли, привязки к MAC (udev/netplan с конкретным MAC), DHCP-аренды.

</details>

**9.** Чем отличаются vMotion, DRS, HA и FT в VMware?

<details><summary>Ответ</summary>

vMotion — плановая живая миграция; DRS — автобалансировка через vMotion; HA — перезапуск
   VM после отказа хоста; FT — синхронная теневая копия без простоя.

</details>

**10.** Где хранишь секреты в цепочке Packer → Terraform → Ansible?

<details><summary>Ответ</summary>

В Vault или защищённых переменных CI: токены гипервизоров (`PKR_VAR_*`,
    `PROXMOX_VE_API_TOKEN`), секреты приложений — ansible-vault/Vault; в user-data и стейт
    секреты не кладу; стейт — в зашифрованном backend'е.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Раскладываю автоматизацию на образ / инфраструктуру / конфигурацию
- [ ] ⭐ Пишу user-data, meta-data и network-config и отлаживаю cloud-init по логам
- [ ] ⭐ Собираю golden image Packer'ом и доказываю, что клоны уникальны и без паролей
- [ ] Создаю VM Terraform'ом через dmacvicar/libvirt 0.9 и знаю, чем он отличается от 0.8
- [ ] Создаю VM в Proxmox через bpg/proxmox с токеном и тегами
- [ ] ⭐ Настраиваю динамический inventory (libvirt и Proxmox) и прогоняю плейбук
- [ ] Описываю конвейер golden image со стадией теста
- [ ] Объясняю термины vSphere и чем его автоматизируют
