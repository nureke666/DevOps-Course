---
title: "07. Практика: 5 лаб по виртуализации on-prem"
description: "Блок → Виртуализация on-prem → практика."
---

# 07. Практика: 5 лаб по виртуализации on-prem

> Блок → Виртуализация on-prem → практика.
> Лабы делаются на стенде из [00_INDEX.md](/virtualization/) (хост с libvirt/KVM, сеть `virt-lab`,
> облачный образ Ubuntu 24.04 в пуле `default`) и остаются в git: `~/labs/virt/`.
> После них есть что показать на собесе: скрипт VM из облачного образа, сеть «bond + VLAN +
> bridge» с доказанной изоляцией, свой Proxmox с шаблоном, отработанное восстановление из
> бэкапа и VM, созданные и настроенные кодом.
>
> ⚠️ Сеть **хоста** в лабах не меняется: bond, VLAN и bridge живут внутри VM и в
> изолированных сетях libvirt.

---

## 📋 Список лаб

| № | Лаба | Что закрепляет | Артефакт |
|---|------|----------------|----------|
| 1 | ⭐ VM из облачного образа: `virt-install` + cloud-init, управление через `virsh` | темы 01–02 | `create-vm.sh`, `destroy-vm.sh`, заметки |
| 2 | ⭐ bond (active-backup) + VLAN + bridge между двумя VM, изоляция и failover | тема 03 | netplan-файлы, вывод tcpdump, `/proc/net/bonding` |
| 3 | Proxmox вложенно: шаблон с cloud-init, 3 VM + 1 LXC | темы 04–05 | заметки установки, команды шаблона |
| 4 | ⭐ Учения: бэкап и восстановление в Proxmox, замер RTO | тема 04 | runbook восстановления + протокол учений |
| 5 | ⭐ Terraform + Ansible: VM и их настройка кодом | тема 06 | `terraform/`, `ansible/`, `Makefile` |

---

## 🧪 Лаба 1. VM из облачного образа и `virsh`

### Что делаем
Пишем скрипт, который за одну команду поднимает VM из облачного образа с пользователем и
ключом через cloud-init, и отрабатываем на этих VM весь жизненный цикл: консоль, снапшот и
откат, изменение ресурсов, увеличение диска, guest agent, удаление без мусора.

### Каркас
```bash
mkdir -p ~/labs/virt/lab1 && cd ~/labs/virt/lab1
```text
```bash
#!/usr/bin/env bash
# create-vm.sh &lt;name&gt; [memory_mb] [vcpus] — VM из облачного образа в сети virt-lab
set -euo pipefail
NAME=${1:?usage: $0 &lt;name&gt; [memory_mb] [vcpus]}
MEM=${2:-2048}
CPUS=${3:-2}
BASE=/var/lib/libvirt/images/noble-base.qcow2
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

virsh dominfo "$NAME" &>/dev/null && { echo "VM $NAME уже есть" >&2; exit 1; }

virsh vol-create-as default "$NAME.qcow2" 20G --format qcow2 \
  --backing-vol "$BASE" --backing-vol-format qcow2 >/dev/null

cat > "$WORK/user-data" <&lt;EOF
#cloud-config
hostname: $NAME
users:
  - name: devops
    groups: [sudo]
    shell: /bin/bash
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    ssh_authorized_keys:
      - $(cat ~/.ssh/id_ed25519.pub)
packages: [qemu-guest-agent]
runcmd:
  - [systemctl, start, qemu-guest-agent]
EOF
printf 'instance-id: %s-%s\nlocal-hostname: %s\n' "$NAME" "$(date +%s)" "$NAME"&gt; "$WORK/meta-data"
cp "$WORK/user-data" "$(dirname "$0")/user-data.example"     # образец с твоим ключом для лаб 2–5

virt-install --name "$NAME" --memory "$MEM" --vcpus "$CPUS" --osinfo ubuntu24.04 \
  --disk "vol=default/$NAME.qcow2,bus=virtio" \
  --network network=virt-lab,model=virtio \
  --cloud-init "user-data=$WORK/user-data,meta-data=$WORK/meta-data" \
  --import --graphics none --noautoconsole

echo -n "Жду IP"
for _ in $(seq 60); do
  IP=$(virsh domifaddr "$NAME" 2>/dev/null | awk '/ipv4/ {sub(/\/.*/, "", $4); print $4; exit}')
  [ -n "${IP:-}" ] && break
  echo -n .; sleep 2
done
echo; echo "$NAME → ${IP:-нет IP, смотри: virsh console $NAME}"
```text
```bash
#!/usr/bin/env bash
# destroy-vm.sh &lt;name&gt; — удалить VM вместе с дисками (база остаётся)
set -euo pipefail
NAME=${1:?usage: $0 &lt;name&gt;}
virsh destroy "$NAME" 2>/dev/null || true
virsh undefine "$NAME" --remove-all-storage --snapshots-metadata
```text
```bash
chmod +x create-vm.sh destroy-vm.sh
./create-vm.sh lab1-a && ./create-vm.sh lab1-b 1024 1
```text
### Требования
- [ ] Скрипты написаны руками, каждая строка объяснима; повторный запуск с тем же именем — понятная ошибка
- [ ] VM готова (SSH по ключу, `cloud-init status: done`) быстрее, чем за 2 минуты
- [ ] Показано: `shutdown` против `destroy`, `autostart`, `console` (и выход из неё)
- [ ] Internal-снапшот → поломка (`apt remove openssh-server`) → откат → SSH снова работает
- [ ] External-снапшот с `--quiesce`, просмотр цепочки `qemu-img info -U --backing-chain`, удаление снапшота
- [ ] vCPU и RAM подняты на ходу (через максимум в конфиге), диск увеличен на ходу и растянут в госте
- [ ] Guest agent: `guest-ping`, `domifaddr --source agent`, `domfsfreeze`/`domfsthaw`
- [ ] IP `lab1-a` зарезервирован в DHCP сети `virt-lab` и переживает перезапуск VM
- [ ] После `destroy-vm.sh` в пуле нет томов этой VM, база `noble-base.qcow2` на месте
- [ ] Бонус: флаг `--seed-iso` в скрипте — тот же результат через `cloud-localds` вместо `--cloud-init`

### Критерии приёмки
```bash
ip_of() { virsh domifaddr "$1" | awk '/ipv4/ {sub(/\/.*/, "", $4); print $4; exit}'; }
virsh list --all | grep lab1-
ssh devops@"$(ip_of lab1-a)" 'hostname; cloud-init status; systemctl is-active qemu-guest-agent; df -h / | tail -1'
virsh qemu-agent-command lab1-a '{"execute":"guest-ping"}'          # {"return":{&#125;&#125;
virsh snapshot-list lab1-a
qemu-img info -U --backing-chain /var/lib/libvirt/images/lab1-a.qcow2 | grep -E '^image:|backing file:'
virsh net-dumpxml virt-lab | grep "name='lab1-a'"                   # резерв DHCP
./destroy-vm.sh lab1-b && virsh vol-list default | grep -c lab1-b   # 0
```text
### Вопросы себе
- Что произойдёт с `lab1-a`, если удалить или изменить `noble-base.qcow2`?
- Почему `instance-id` в скрипте содержит время, и что будет, если сделать его постоянным?
- Чем `virsh undefine --remove-all-storage` опаснее `destroy` и почему в скрипте он оправдан?
- Как тот же `user-data` использовать в Proxmox и в облаке?

---

## 🧪 Лаба 2. ⭐ bond + VLAN + bridge между двумя VM

### Что делаем
Две VM `hv1` и `hv2` играют роль хостов-гипервизоров: у каждой управляющий NIC в `virt-lab`
и два «транковых» NIC в изолированной сети `lab-trunk` (это наш «свитч»). Внутри собираем
типовую схему из темы 03: `bond0` (active-backup) → `bond0.10`, `bond0.20` → `br10`, `br20`.
Доказываем связность внутри VLAN, изоляцию между VLAN (ping + tcpdump с тегами) и failover бонда.

```text
   hv1                                         hv2
   mgmt0 ── virt-lab (SSH) ──────────────────── mgmt0
   trunk0 ─┐                               ┌── trunk0
           ├ bond0 ═══ lab-trunk (L2) ═══ bond0 ┤
   trunk1 ─┘   ├ bond0.10 ─ br10 10.0.10.1 ◄──► 10.0.10.2 br10 ─ bond0.10 ┤
               └ bond0.20 ─ br20 10.0.20.1 ◄──► 10.0.20.2 br20 ─ bond0.20 ┘  └── trunk1
```text
### Каркас
```bash
mkdir -p ~/labs/virt/lab2 && cd ~/labs/virt/lab2
cat > lab-trunk.xml <<'EOF'
&lt;network&gt;
  &lt;name&gt;lab-trunk</name>
  &lt;bridge name='virbr-trunk' stp='off' delay='0'/&gt;
</network>
EOF
virsh net-define lab-trunk.xml && virsh net-start lab-trunk && virsh net-autostart lab-trunk
```text
```bash
# на каждую VM: свой network-config (N=1 для hv1, N=2 для hv2)
for N in 1 2; do
cat > net-hv$N.yaml <&lt;EOF
version: 2
ethernets:
  mgmt0:
    match: { macaddress: "52:54:00:20:0$N:00" }
    set-name: mgmt0
    dhcp4: true
  trunk0:
    match: { macaddress: "52:54:00:20:0$N:01" }
    set-name: trunk0
    dhcp4: false
    optional: true
  trunk1:
    match: { macaddress: "52:54:00:20:0$N:02" }
    set-name: trunk1
    dhcp4: false
    optional: true
EOF
printf 'instance-id: hv%s-001\nlocal-hostname: hv%s\n' "$N" "$N"&gt; meta-hv$N.yaml
sed "s/^hostname: .*/hostname: hv$N/" ../lab1/user-data.example > user-hv$N.yaml   # или напиши user-data как в лабе 1

virsh vol-create-as default hv$N.qcow2 20G --format qcow2 \
  --backing-vol /var/lib/libvirt/images/noble-base.qcow2 --backing-vol-format qcow2
virt-install --name hv$N --memory 1024 --vcpus 1 --osinfo ubuntu24.04 \
  --disk vol=default/hv$N.qcow2,bus=virtio \
  --network network=virt-lab,model=virtio,mac=52:54:00:20:0$N:00 \
  --network network=lab-trunk,model=virtio,mac=52:54:00:20:0$N:01 \
  --network network=lab-trunk,model=virtio,mac=52:54:00:20:0$N:02 \
  --cloud-init user-data=user-hv$N.yaml,meta-data=meta-hv$N.yaml,network-config=net-hv$N.yaml \
  --import --graphics none --noautoconsole
done
```text
> `lab1/user-data.example` оставляет `create-vm.sh` из лабы 1 — это готовый user-data
> с твоим ключом; здесь в нём меняется только `hostname`.

**Шаг 1 — руками (`ip`), чтобы понять механику** — на `hv1` (на `hv2` то же с `.2`):
```bash
sudo ip link add bond0 type bond mode active-backup miimon 100
for s in trunk0 trunk1; do sudo ip link set $s down; sudo ip link set $s master bond0; done
sudo ip link set bond0 up
for v in 10 20; do
  sudo ip link add link bond0 name bond0.$v type vlan id $v
  sudo ip link add br$v type bridge
  sudo ip link set bond0.$v master br$v
  sudo ip link set bond0.$v up && sudo ip link set br$v up
  sudo ip addr add 10.0.$v.1/24 dev br$v
done
cat /proc/net/bonding/bond0
```text
**Шаг 2 — постоянно (netplan)**: перезагрузи VM (ручная конфигурация исчезнет) и положи файл:
```yaml
# /etc/netplan/60-lab.yaml на hv1 (на hv2 — адреса .2); chmod 600
network:
  version: 2
  renderer: networkd
  bonds:
    bond0:
      interfaces: [trunk0, trunk1]
      parameters:
        mode: active-backup
        mii-monitor-interval: 100
        primary: trunk0
  vlans:
    bond0.10: { id: 10, link: bond0 }
    bond0.20: { id: 20, link: bond0 }
  bridges:
    br10:
      interfaces: [bond0.10]
      addresses: [10.0.10.1/24]
      parameters: { stp: false, forward-delay: 0 }
    br20:
      interfaces: [bond0.20]
      addresses: [10.0.20.1/24]
      parameters: { stp: false, forward-delay: 0 }
```text
```bash
sudo netplan try          # автооткат через 120 с, если связь (mgmt0) пропадёт
```text
`trunk0`/`trunk1` уже описаны в `50-cloud-init.yaml` — netplan склеивает все файлы в одну
конфигурацию, поэтому в `60-lab.yaml` на них можно ссылаться.

### Требования
- [ ] Схема собрана сначала руками (`ip`), потом в netplan; после перезагрузки поднимается сама
- [ ] `hv1 ↔ hv2` пингуются в VLAN 10 и в VLAN 20
- [ ] Изоляция доказана: адрес `10.0.10.99/24` на `br20` у `hv1` → `ping -I br20 10.0.10.2` — 100% потерь
- [ ] На хосте `tcpdump -e` на vnet-интерфейсе транка показывает теги `vlan 10` и `vlan 20`
- [ ] Failover: `virsh domif-setlink hv1 &lt;vnet активного слейва&gt; down` при идущем `ping -i 0.2` —
      потеряно не больше нескольких пакетов; в `/proc/net/bonding/bond0` сменился активный слейв
- [ ] Показано, что будет, если на `hv2` перепутать VLAN (20 → 30): связи нет, в tcpdump видно `vlan 30`
- [ ] Бонус: вместо двух бриджей — один VLAN-aware `br0` с network namespace-«VM» в VLAN 10 и 20
- [ ] Бонус: MTU 9000 на всём пути (`&lt;mtu size='9000'/&gt;` в `lab-trunk` и во всех интерфейсах VM),
      проверка `ping -M do -s 8972`

### Критерии приёмки
```bash
ip_of() { virsh domifaddr "$1" | awk '/ipv4/ {sub(/\/.*/, "", $4); print $4; exit}'; }
H1=$(ip_of hv1)
ssh devops@$H1 'grep -E "Bonding Mode|Currently Active" /proc/net/bonding/bond0'
ssh devops@$H1 'ping -c3 -W1 10.0.10.2 && ping -c3 -W1 10.0.20.2'
ssh devops@$H1 'ping -c3 -W1 -I br20 10.0.10.2; echo "exit=$?"'     # exit=1 — изоляция
virsh domiflist hv1                                                  # найди vnet для MAC ...:01:01
sudo tcpdump -eni &lt;vnetX&gt; -c 20 vlan 2>/dev/null | grep -oE 'vlan (10|20)' | sort -u
```text
### Вопросы себе
- Почему бридж `virbr-trunk` на хосте пропускает кадры с тегами, хотя VLAN на нём не настроены?
- Что изменится, если вместо active-backup поставить `802.3ad`? Заработает ли на `lab-trunk`?
- Где в реальном ЦОДе физически «живут» `lab-trunk`, `trunk0` и `trunk1`?
- Почему у хоста-гипервизора не должно быть IP в VLAN, где живут VM?

---

## 🧪 Лаба 3. Proxmox вложенно: шаблон, 3 VM и 1 LXC

### Что делаем
Поднимаем Proxmox VE 9.2 внутри KVM, настраиваем репозитории, делаем шаблон Ubuntu 24.04
с cloud-init и агентом, клонируем три VM со статическими адресами и создаём unprivileged
LXC-контейнер. Всё — по командам тем 04 и 05, но руками от начала до конца.

### Каркас
```text
~/labs/virt/lab3/
├── install.md          # параметры virt-install, ответы установщику, проверка nested
├── bootstrap.sh        # запускается на pve1: репозитории, full-upgrade, шаблон 9000
├── clones.sh           # запускается на pve1: app1..app3 + ct1
└── notes.md            # что пошло не так и как починил
```text
1. **Установка** — [04_proxmox.md](/virtualization/04-proxmox), раздел 2 (`pve1`: 4 vCPU, 8 ГБ, 64 ГБ,
   `host-passthrough`, `10.10.10.11`).
2. **Репозитории** — раздел 3 (deb822, `pve-no-subscription`, `apt full-upgrade`).
3. **Шаблон** — раздел 6 (`import-from`, `ide2 ...:cloudinit`, serial, агент через `virt-customize`).
4. **Клоны** — раздел 6 (цикл `qm clone` + `ipconfig0` `10.10.10.21–23`).
5. **LXC** — [05_lxc_containers.md](/virtualization/05-lxc-containers), раздел 6 (`pveam`, `pct create`, unprivileged, `nesting=1`).

```bash
# на хосте перед началом и после каждого успешного шага
virsh snapshot-create-as pve1 --name step-N-ok
```text
### Требования
- [ ] `pve1` установлен, внутри `grep -cE 'vmx|svm' /proc/cpuinfo` > 0, VM в Proxmox работают на KVM
- [ ] `apt update` без ошибок 401, узел обновлён через `full-upgrade`, enterprise-репозитории выключены через `Enabled: no`
- [ ] Шаблон 9000: VirtIO SCSI single, `discard`, `iothread`, агент в образе и `agent: 1`, serial-консоль, cloud-init диск
- [ ] `app1..app3` — linked clones со статическими IP, SSH по ключу, IP виден через агента
- [ ] `ct1` — unprivileged, `nesting=1`, в VLAN (тег) или `vmbr0`, SSH по ключу, nginx внутри
- [ ] Скрипты `bootstrap.sh` и `clones.sh` воспроизводят шаги на чистом узле (проверь откатом снапшота `pve1`)
- [ ] Показана разница в месте linked и full clone (`lvs`)
- [ ] Бонус: 3-узловой кластер (`pve2`, `pve3` по 2 vCPU/4 ГБ), NFS-хранилище, живая миграция `app1`
- [ ] Бонус: HA для `app1` и замер времени восстановления после `virsh destroy` его узла

### Критерии приёмки
```bash
ssh root@10.10.10.11 'pveversion; grep -cE "vmx|svm" /proc/cpuinfo; grep -h "^Enabled" /etc/apt/sources.list.d/*.sources'
ssh root@10.10.10.11 'qm list; pct list; qm config 9000 | grep -E "template|agent|scsihw|serial0|ide2"'
ssh root@10.10.10.11 "pvesh get /cluster/resources --type vm --output-format json" \
  | jq -r '.[] | "\(.vmid) \(.name) \(.status) \(.type)"'
for i in 1 2 3; do ssh -o ConnectTimeout=5 devops@10.10.10.2$i hostname; done
ssh root@10.10.10.11 'qm guest cmd 101 network-get-interfaces' | jq -r '.[].["ip-addresses"][]?."ip-address"'
```text
### Вопросы себе
- Что сломается у клонов, если удалить шаблон 9000? А если его склонировать `--full`?
- Почему для облачного образа обязательно `--serial0 socket --vga serial0`?
- Какой `--cpu` ты поставил и что будет с живой миграцией в кластере из разных процессоров?
- Чем «VM в Proxmox внутри VM в KVM» отличается по производительности от настоящего железа и почему?

---

## 🧪 Лаба 4. ⭐ Учения: бэкап и восстановление

### Что делаем
Проводим учения «потеряли VM»: заранее записываем цели (RTO — за сколько восстановимся,
RPO — сколько данных можем потерять), делаем бэкапы VM и контейнера, «теряем» их, восстанавливаем
по runbook'у, замеряем время и проверяем данные. Бонус — то же через Proxmox Backup Server
с восстановлением одного файла.

### Каркас
```text
~/labs/virt/lab4/
├── plan.md               # цели RTO/RPO, что бэкапим, сценарии, критерий успеха
├── runbooks/restore-vm.md
└── drill-2026-10-xx.md   # протокол: время каждого шага, что пошло не так
```text
```bash
# 1. данные-маркеры (на app1 и ct1)
ssh devops@10.10.10.21 'date -Is | sudo tee /var/tmp/marker; sudo apt-get -y install nginx'
ssh root@10.10.10.11 'pct exec 200 -- sh -c "date -Is > /root/marker"'

# 2. бэкапы
ssh root@10.10.10.11 'vzdump 101 --storage local --mode snapshot --compress zstd --notes-template "&#123;&#123;guestname&#125;&#125; drill"'
ssh root@10.10.10.11 'vzdump 200 --storage local --mode snapshot --compress zstd'
ssh root@10.10.10.11 'ls -lh /var/lib/vz/dump/'

# 3. «авария» — засекай время с этого момента
ssh root@10.10.10.11 'qm stop 101 && qm destroy 101 --purge'
ssh root@10.10.10.11 'pct stop 200 && pct destroy 200 --purge'

# 4. восстановление — строго по своему runbook'у (qmrestore / pct restore, раздел 12 темы 04)
```text
**Бонус — PBS:** VM `pbs01` на хосте из `proxmox-backup-server_4.2-1.iso` (2 vCPU, 4 ГБ,
диск 32 ГБ + второй диск 64 ГБ под datastore, адрес `10.10.10.20`). В веб-интерфейсе PBS
(`https://10.10.10.20:8007`): Administration → Storage/Disks → Directory → Create на втором
диске с «Add as Datastore». Отпечаток сертификата — `proxmox-backup-manager cert info`.
Подключение к `pve1` — `pvesm add pbs ...` из раздела 12 темы 04.

### Требования
- [ ] В `plan.md` до учений записаны RTO/RPO, критерий успеха и условие остановки
- [ ] Бэкапы VM и CT сделаны в режиме `snapshot`, проверено, что для VM сработал fsfreeze (лог задачи)
- [ ] VM и CT восстановлены **в те же VMID** после полного удаления; маркеры на месте, nginx работает
- [ ] Отдельно: восстановление в **новый** VMID рядом с живой VM без конфликта IP/MAC
- [ ] Замерено фактическое RTO по шагам; сравнено с целью
- [ ] Runbook написан так, что по нему восстановит коллега, не видевший стенд
- [ ] Настроено расписание бэкапов (Datacenter → Backup) с `prune-backups`, показан `/etc/pve/jobs.cfg`
- [ ] Бонус: PBS — два бэкапа подряд, второй заметно быстрее (инкремент); verify-задание; восстановление
      одного файла из бэкапа VM через File Restore
- [ ] Бонус: сценарий «потерян весь узел» — новый `pve1` из чистой установки, подключение PBS, восстановление

### Критерии приёмки
```bash
ssh root@10.10.10.11 'ls -lh /var/lib/vz/dump/ | grep -E "qemu-101|lxc-200"'
ssh root@10.10.10.11 'qm list | grep " 101 "; pct list | grep "^200"'
ssh devops@10.10.10.21 'cat /var/tmp/marker; systemctl is-active nginx'
ssh root@10.10.10.11 'pct exec 200 -- cat /root/marker'
ssh root@10.10.10.11 'cat /etc/pve/jobs.cfg'
# бонус PBS
ssh root@10.10.10.11 'pvesm status | grep pbs; pvesm list pbs01 | tail -3'
```text
### Вопросы себе
- Какое RPO у ежедневного бэкапа в 02:00 и что делать, если бизнесу нужно 15 минут?
- Почему бэкап на `local` того же узла не защищает от отказа узла? Как выглядит 3-2-1 для этого стенда?
- Что в бэкап не попало бы, если бы данные `ct1` жили в bind mount?
- Сколько времени займёт восстановление 2 ТБ по сети 1 Гбит/с? А 10 Гбит/с?

---

## 🧪 Лаба 5. ⭐ Terraform + Ansible: VM и их настройка кодом

### Что делаем
Одной командой `make all` из пустоты получаем две VM `web1`, `web2` в libvirt (Terraform,
провайдер dmacvicar/libvirt 0.9), настроенные Ansible'ом через динамический inventory:
nginx со страницей «hello from &lt;имя&gt;». `make down` убирает всё. Бонус — то же в Proxmox
(bpg/proxmox + inventory community.proxmox по тегам) и базовый образ из Packer.

### Каркас
```text
~/labs/virt/lab5/
├── Makefile
├── terraform/
│   ├── main.tf              # из темы 06, раздел 5
│   └── user-data.tftpl
└── ansible/
    ├── ansible.cfg
    ├── inventory/kvm.libvirt.yml   # из темы 06, раздел 7
    └── site.yml
```text
```makefile
# Makefile (отступы в рецептах — табами)
.PHONY: all up config check down
all: up config check

up:
	cd terraform && terraform init -input=false && terraform apply -auto-approve

config:
	cd ansible && ansible-playbook site.yml

check:
	for ip in $$(cd terraform && terraform output -json ips | jq -r '.[]'); do curl -s "http://$$ip/"; done

down:
	cd terraform && terraform destroy -auto-approve
```text
```ini
# ansible/ansible.cfg
[defaults]
inventory = inventory/kvm.libvirt.yml
remote_user = devops
# только для стенда: VM пересоздаются с новыми host keys
host_key_checking = False
```text
```yaml
# ansible/site.yml
- name: Веб-серверы
  hosts: all
  become: true
  gather_facts: false
  tasks:
    - name: Дождаться SSH
      ansible.builtin.wait_for_connection:
        timeout: 300

    - name: Дождаться окончания cloud-init (иначе apt занят)
      ansible.builtin.command: cloud-init status --wait
      changed_when: false

    - name: Собрать факты
      ansible.builtin.setup:

    - name: Установить nginx
      ansible.builtin.apt:
        name: nginx
        state: present
        update_cache: true

    - name: Страница
      ansible.builtin.copy:
        dest: /var/www/html/index.html
        content: "hello from &#123;&#123; inventory_hostname &#125;&#125; (&#123;&#123; ansible_default_ipv4.address &#125;&#125;)\n"
        mode: "0644"
```text
```bash
ansible-galaxy collection install community.libvirt     # ≥ 2.3.0 для опции filter
python3 -c 'import libvirt' || sudo apt install -y python3-libvirt   # модуль — в Python Ansible'а
```text
### Требования
- [ ] `make all` на чистом стенде создаёт 2 VM и выводит две строки `hello from web1/web2`
- [ ] Inventory динамический: `ansible-inventory --graph` показывает `web1`, `web2` без ручных IP
- [ ] Повторный `make config` — `changed=0` (идемпотентность)
- [ ] `make down` удаляет VM и тома; `virsh vol-list default` без мусора
- [ ] В репозитории нет секретов и стейта (`.gitignore`: `*.tfstate*`, `.terraform/`)
- [ ] Версии провайдера и коллекций закреплены (`~> 0.9.9`, `requirements.yml`)
- [ ] Добавление `web3` — одна строка в `locals`, `make all` доводит до нужного состояния
- [ ] Бонус: Proxmox — `app11`, `app12` через bpg/proxmox с тегом `web`, inventory `lab.proxmox.yml`,
      токен только из окружения (`PROXMOX_VE_API_TOKEN`, `PROXMOX_TOKEN_SECRET`)
- [ ] Бонус: база VM — golden image из Packer (тема 06, раздел 4.1) вместо облачного образа

### Критерии приёмки
```bash
cd ~/labs/virt/lab5
make all
(cd ansible && ansible-inventory --graph)
(cd ansible && ansible-playbook site.yml) | grep -E 'changed=0.*failed=0' | wc -l   # 2
make check                        # hello from web1 (...) / hello from web2 (...)
make down && virsh list --all | grep -c web                                       # 0
git status --short | grep -c tfstate                                              # 0
```text
### Вопросы себе
- Что произойдёт, если запустить `make config` до окончания cloud-init без задачи `cloud-init status --wait`?
- Почему плагин libvirt без `compose: ansible_connection` пытается ходить через guest agent?
- Где будет храниться стейт, если этим репозиторием начнёт пользоваться команда?
- Что поменяется в коде при переезде с libvirt на Proxmox, а что останется прежним?

---

## 🏁 Что должно остаться после блока

```text
~/labs/virt/                       # репозиторий блока
├── lab1/create-vm.sh, destroy-vm.sh, user-data.example
├── lab2/lab-trunk.xml, net-hv*.yaml, 60-lab.yaml, tcpdump-vlan.txt
├── lab3/install.md, bootstrap.sh, clones.sh
├── lab4/plan.md, runbooks/restore-vm.md, drill-*.md
├── lab5/Makefile, terraform/, ansible/
└── automation/packer/noble.pkr.hcl    # golden image (тема 06)
```text
Это превращает «знаю, что такое KVM и Proxmox» в «вот скрипт VM из облачного образа, вот сеть
с bond и VLAN, где изоляция доказана tcpdump'ом, вот протокол учений восстановления с RTO
и вот VM, которые создаются и настраиваются одной командой».

➡️ Дальше: [08_interview.md](/mlops/08-interview)
