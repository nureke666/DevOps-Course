---
title: "04. Proxmox VE: VM, LXC, шаблоны, хранилища, кластер, HA, бэкапы, API"
description: "Блок → Виртуализация on-prem → тема 04. Опирается на 02kvmqemulibvirt.md"
---

# 04. Proxmox VE: VM, LXC, шаблоны, хранилища, кластер, HA, бэкапы, API

> Блок → Виртуализация on-prem → тема 04. Опирается на [02_kvm_qemu_libvirt.md](/virtualization/02-kvm-qemu-libvirt)
> (KVM, QEMU, qcow2, cloud-init, снапшоты) и [03_virt_networking.md](/virtualization/03-virt-networking)
> (bridge, VLAN, bond). Хранилища (LVM-thin, ZFS, NFS, Ceph) подробно — в блоке [«Хранилища»](/storage/).
>
> **После темы ты умеешь:** поднять Proxmox VE вложенно в KVM, настроить репозиторий без подписки,
> работать в веб-интерфейсе и CLI (`qm`, `pct`, `pvesm`, `pvecm`, `pvesh`), делать шаблоны
> с cloud-init и клоны, выбирать хранилище, настраивать vmbr0 и VLAN, собирать кластер из трёх
> узлов и объяснять кворум, включать HA, делать бэкапы (vzdump, Proxmox Backup Server)
> и восстанавливать их, ходить в API по токену.

---

## 🗺️ Карта темы

```text
 ┌──────────────────── Proxmox VE 9.x = Debian 13 + ... ───────────────────────────┐
 │  веб-интерфейс :8006  ◄──►  REST API /api2/json  ◄──►  pvesh / Terraform / Ansible │
 │                                                                                  │
 │  VM: qm (KVM/QEMU)        LXC: pct              хранилища: pvesm                 │
 │  шаблоны + cloud-init     шаблоны pveam         local · local-lvm · ZFS · NFS · Ceph · PBS │
 │                                                                                  │
 │  сеть: /etc/network/interfaces (ifupdown2): vmbr0, bond, VLAN-aware, SDN         │
 │                                                                                  │
 │  кластер: corosync (кворум) + pmxcfs (/etc/pve — общий конфиг всех узлов)        │
 │  HA: ha-manager (CRM/LRM + watchdog-фенсинг)    бэкап: vzdump → local / PBS      │
 └──────────────────────────────────────────────────────────────────────────────────┘
          libvirt НЕ используется: у Proxmox свои конфиги /etc/pve/qemu-server/&lt;vmid&gt;.conf
```text
---

## 1. Что такое Proxmox VE

Дистрибутив на базе Debian, в котором уже собраны KVM/QEMU, LXC, веб-интерфейс, REST API,
кластер, HA, Ceph, ZFS и бэкапы. Лицензия AGPLv3: всё бесплатно, подписка даёт доступ
к enterprise-репозиторию (более обкатанные пакеты) и поддержку.

| Версия | Когда | База |
|--------|-------|------|
| 9.0 | август 2025 | Debian 13 «Trixie», ядро 6.14, QEMU 10.0; HA rules вместо HA groups, SDN fabrics, снапшоты на shared thick LVM (SAN) |
| 9.1 | ноябрь 2025 | ядро 6.17; LXC из OCI-образов (образы из registry как шаблоны контейнеров) |
| 9.2 | май 2026 | ядро 7.0, QEMU 11.0, LXC 7.0, ZFS 2.4, Ceph Squid/Tentacle; динамическая балансировка HA-гостей (CRS) |

Рядом живёт **Proxmox Backup Server** (PBS, ветка 4.x на Debian 13) — отдельный продукт
для бэкапов с дедупликацией.

---

## 2. Установка вложенно (nested) в KVM

| | Один узел (лабы 3–4) | Кластер из трёх (бонус) |
|---|---------------------|------------------------|
| vCPU | 4 | 2 на узел |
| RAM | 8 ГБ | 4 ГБ на узел |
| Диск | 64 ГБ | 40 ГБ на узел (+ общий NFS) |
| CPU mode | ⭐ `host-passthrough` — иначе внутри не будет KVM | то же |
| Адреса в `virt-lab` | `10.10.10.11` | `.11`, `.12`, `.13` |

```bash
# на хосте: ISO — туда, где его прочитает QEMU
cd /var/lib/libvirt/images
sudo wget http://download.proxmox.com/iso/proxmox-ve_9.2-1.iso    # сверь SHA256 со страницы загрузок

virt-install \
  --name pve1 \
  --memory 8192 --vcpus 4 \
  --cpu host-passthrough \
  --osinfo debian13 \
  --disk size=64,format=qcow2,bus=virtio \
  --cdrom /var/lib/libvirt/images/proxmox-ve_9.2-1.iso \
  --network network=virt-lab,model=virtio \
  --graphics vnc,listen=127.0.0.1 \
  --noautoconsole
virt-viewer pve1          # или virt-manager
```text
В установщике: графический или **Terminal UI** (есть и вариант для серийной консоли);
диск `vda`, ФС `ext4` (создаст `local` + `local-lvm`) или ZFS; FQDN `pve1.lab.local`;
IP `10.10.10.11/24`, шлюз и DNS `10.10.10.1`. После перезагрузки:

```bash
virsh change-media pve1 sda --eject     # вынуть ISO (имя устройства — из virsh domblklist pve1)
# веб-интерфейс: https://10.10.10.11:8006  → root, realm «Linux PAM»
ssh root@10.10.10.11
grep -cE 'vmx|svm' /proc/cpuinfo        # > 0 — nested работает, VM внутри будут на KVM
pveversion -v | head -3
```text
> 💡 Для десятков узлов есть автоматическая установка: `proxmox-auto-install-assistant`
> готовит ISO с файлом ответов `answer.toml` — Proxmox ставится без рук.

---

## 3. Репозиторий без подписки (Proxmox VE 9)

Установщик включает **enterprise**-репозитории (`pve-enterprise.sources`, `ceph.sources`),
без подписки `apt update` падает с 401. В PVE 9 репозитории описаны в формате **deb822**
(`.sources`), а не строками в `.list`.

```bash
# выключить enterprise — строкой Enabled: no в каждом таком файле
for f in pve-enterprise ceph; do
  [ -f /etc/apt/sources.list.d/$f.sources ] && sed -i '/^Types:/i Enabled: no' /etc/apt/sources.list.d/$f.sources
done

cat > /etc/apt/sources.list.d/proxmox.sources <<'EOF'
Types: deb
URIs: http://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-no-subscription
Signed-By: /usr/share/keyrings/proxmox-archive-keyring.gpg
EOF

apt update && apt full-upgrade -y     # ⭐ всегда full-upgrade (dist-upgrade), не apt upgrade
```text
То же в интерфейсе: узел → **Updates → Repositories** → Disable у enterprise, **Add →
No-Subscription**. Окно «You do not have a valid subscription» при входе — просто напоминание.

> ⚠️ `no-subscription` — для тестов и небольших установок: пакеты туда попадают раньше
> enterprise. В банке или госсекторе с SLA — подписка и enterprise-репозиторий.

---

## 4. Веб-интерфейс и CLI

| Инструмент | Что делает | Пример |
|------------|-----------|--------|
| `qm` | VM (KVM/QEMU) | `qm list`, `qm start 101`, `qm config 101`, `qm terminal 101` |
| `pct` | LXC-контейнеры | `pct list`, `pct enter 200`, `pct exec 200 -- df -h` |
| `pvesm` | Хранилища | `pvesm status`, `pvesm list local` |
| `pveam` | Шаблоны LXC | `pveam update`, `pveam available --section system` |
| `pvecm` | Кластер | `pvecm status`, `pvecm nodes` |
| `ha-manager` | HA | `ha-manager status` |
| `vzdump` / `qmrestore` / `pct restore` | Бэкап / восстановление | `vzdump 101 --storage local` |
| `pvesh` | API из консоли | `pvesh get /cluster/resources --type vm` |
| `pveum` | Пользователи, роли, токены | `pveum user token add ...` |
| `pveversion -v` | Версии всех компонентов | — |

**Где лежат конфиги.** `/etc/pve` — это **pmxcfs**: база в SQLite, смонтированная как ФС
и одинаковая на всех узлах кластера.

```text
/etc/pve/
├── qemu-server/101.conf     → симлинк на nodes/&lt;этот узел&gt;/qemu-server/
├── lxc/200.conf
├── nodes/pve1/…             конфиги VM/CT конкретного узла
├── storage.cfg              хранилища (общие для кластера)
├── corosync.conf            кластер
├── jobs.cfg                 расписания бэкапов и репликации
└── user.cfg, priv/          пользователи, токены, ключи
/var/lib/vz/                 хранилище local: template/iso, template/cache (LXC), dump (бэкапы)
/etc/network/interfaces      сеть узла (ifupdown2; применить: ifreload -a)
```text
```ini
# /etc/pve/qemu-server/101.conf — конфиг VM: читается проще XML libvirt
agent: enabled=1
boot: order=scsi0
cores: 2
cpu: host
ide2: local-lvm:vm-101-cloudinit,media=cdrom
ipconfig0: ip=10.10.10.21/24,gw=10.10.10.1
memory: 2048
name: app1
net0: virtio=BC:24:11:5E:0A:01,bridge=vmbr0
scsi0: local-lvm:base-9000-disk-0/vm-101-disk-0,discard=on,iothread=1,size=11776M
scsihw: virtio-scsi-single
serial0: socket
vga: serial0
```text
---

## 5. VM на Proxmox: на что смотреть

- **VMID** — числовой ID (100+), уникален в кластере. Договорись о диапазонах: 100–899 — VM,
  9000+ — шаблоны.
- **CPU type.** В интерфейсе по умолчанию `x86-64-v2-AES` — совместим с любым современным
  хостом, живая миграция в разнородном кластере работает. `host` — максимум скорости и все
  инструкции, но миграция только между одинаковыми CPU (как `host-passthrough`, тема 02).
  Через `qm create` без `--cpu` получишь старый `kvm64` — задавай явно.
- **Диск:** контроллер `VirtIO SCSI single` + `iothread=1` + `discard=on` (TRIM возвращает
  место тонкому хранилищу). В CLI дефолт контроллера — `lsi`, задавай `--scsihw` явно.
- **Guest agent:** `--agent enabled=1` + пакет `qemu-guest-agent` в госте — без него Proxmox
  не покажет IP, а бэкап не сделает fsfreeze.
- **Клоны:** из шаблона по умолчанию **linked clone** (overlay поверх диска шаблона — быстро,
  но шаблон нельзя удалить, пока есть клоны); `--full 1` — полная независимая копия.

---

## 6. Шаблон с cloud-init и клоны

```bash
# на хосте: свой публичный ключ — на узел (для VM и CT)
scp ~/.ssh/id_ed25519.pub root@10.10.10.11:/root/devops.pub
# дальше — на узле pve1
cd /root
wget https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
# (желательно) вшить агент в образ: в облачных образах Ubuntu его нет
apt install -y libguestfs-tools
virt-customize -a noble-server-cloudimg-amd64.img --install qemu-guest-agent

qm create 9000 --name noble-tpl --ostype l26 --memory 2048 --cores 2 --cpu host \
  --scsihw virtio-scsi-single --net0 virtio,bridge=vmbr0 --agent enabled=1
qm set 9000 --scsi0 local-lvm:0,import-from=/root/noble-server-cloudimg-amd64.img,discard=on,iothread=1
qm set 9000 --ide2 local-lvm:cloudinit          # диск cloud-init (Proxmox сам соберёт NoCloud-ISO)
qm set 9000 --boot order=scsi0
qm set 9000 --serial0 socket --vga serial0      # облачные образы ждут серийную консоль
qm set 9000 --ciuser devops --sshkeys /root/devops.pub --ipconfig0 ip=dhcp
qm disk resize 9000 scsi0 +8G                   # 3.5G образа мало
qm template 9000                                # теперь это шаблон: запускать нельзя, клонировать — да
```text
```bash
# три VM со статическими адресами
for i in 1 2 3; do
  qm clone 9000 10$i --name app$i                       # linked clone
  qm set 10$i --ipconfig0 ip=10.10.10.2$i/24,gw=10.10.10.1 --nameserver 10.10.10.1
  qm start 10$i
done
qm list
qm cloudinit dump 101 user          # какой user-data Proxmox сгенерировал
qm guest cmd 101 network-get-interfaces   # IP от агента
ssh devops@10.10.10.21
```text
- Параметры cloud-init Proxmox: `ciuser`, `cipassword`, `sshkeys`, `ipconfigN`, `nameserver`,
  `searchdomain`, `ciupgrade` (по умолчанию 1 — полное обновление пакетов при первом старте,
  это долго). Меняются в любой момент — применяются при следующем старте.
- Нужно больше (пакеты, runcmd, файлы) — **свой user-data**: включи тип контента `snippets`
  у хранилища (`pvesm set local --content iso,vztmpl,backup,snippets`), положи файл в
  `/var/lib/vz/snippets/` и `qm set 9000 --cicustom "user=local:snippets/user.yaml"`.
  Он заменяет сгенерированный user-data целиком — ключи и пользователя пиши сам.

---

## 7. LXC в Proxmox коротко

```bash
pveam update
pveam available --section system | grep -E 'debian-13|ubuntu-24'
pveam download local debian-13-standard_13.6-1_amd64.tar.zst   # имя — из списка выше

pct create 200 local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst \
  --hostname ct1 --cores 1 --memory 512 --swap 512 \
  --rootfs local-lvm:8 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 --features nesting=1 \
  --ssh-public-keys /root/devops.pub --start 1
pct enter 200
```text
Unprivileged, nesting, bind mounts, idmap и «когда LXC, а когда VM» — тема
[05_lxc_containers.md](/virtualization/05-lxc-containers).

---

## 8. Хранилища

| Тип (`pvesm`) | Что это | Общее для кластера | Снапшоты | Когда |
|---------------|---------|--------------------|----------|-------|
| `dir` (`local`) | Каталог `/var/lib/vz` | Нет | Только с qcow2 | ISO, шаблоны LXC, бэкапы, сниппеты |
| `lvmthin` (`local-lvm`) | Тонкий пул LVM | Нет | Да | Диски VM/CT на одиночном узле — дефолт установщика |
| `zfspool` | ZFS | Нет (но есть **репликация** между узлами) | Да | Надёжность (checksums, RAID-Z), сжатие; ест RAM под кэш ARC |
| `nfs` / `cifs` | Сетевой каталог | Да | С qcow2 | Простое общее хранилище для миграции и HA |
| `lvm` на iSCSI/FC | «Толстый» LVM на LUN СХД | Да | С 9.0 — появились (раньше не было) | Энтерпрайз с SAN |
| `rbd` (Ceph) | Распределённое блочное хранилище | Да | Да | Гиперконвергенция: 3+ узла, быстрая сеть (10G+) |
| `pbs` | Proxmox Backup Server | Да | — | Только бэкапы |

```bash
pvesm status                                    # все хранилища, место
pvesm list local-lvm
pvesm add nfs nfs-lab --server 10.10.10.30 --export /srv/pve --content images,rootdir,backup
pvesm set local --content iso,vztmpl,backup,snippets
cat /etc/pve/storage.cfg
```text
> 💡 «Общее» (shared) хранилище = диски доступны со всех узлов: живая миграция без
> копирования дисков и HA. С локальными дисками миграция идёт с копированием
> (`--with-local-disks`), а HA — только через ZFS-репликацию с потерей данных с последней
> синхронизации (по умолчанию каждые 15 минут).

---

## 9. Сеть

По умолчанию установщик делает `vmbr0` — бридж на физическом NIC, IP узла на бридже
(ровно схема из темы 03). Файл — `/etc/network/interfaces`, применяется без перезагрузки
через `ifreload -a` (или кнопкой **Apply Configuration** в интерфейсе).

```text
# /etc/network/interfaces — bond + VLAN-aware bridge (пример из документации Proxmox)
auto lo
iface lo inet loopback

iface eno1 inet manual
iface eno2 inet manual

auto bond0
iface bond0 inet manual
        bond-slaves eno1 eno2
        bond-miimon 100
        bond-mode 802.3ad
        bond-xmit-hash-policy layer2+3

auto vmbr0
iface vmbr0 inet manual
        bridge-ports bond0
        bridge-stp off
        bridge-fd 0
        bridge-vlan-aware yes
        bridge-vids 2-4094

auto vmbr0.10                      # IP узла в VLAN управления
iface vmbr0.10 inet static
        address 10.0.10.11/24
        gateway 10.0.10.1
```text
```bash
qm set 101 --net0 virtio,bridge=vmbr0,tag=20      # VM в VLAN 20 — Proxmox сам настроит порт
pct set 200 --net0 name=eth0,bridge=vmbr0,tag=20,ip=dhcp
```text
- **SDN** (Datacenter → SDN): зоны Simple, VLAN, QinQ, VXLAN, EVPN — сети VM описываются
  на уровне кластера, а не руками на каждом узле.
- **Firewall** — на уровнях Datacenter, узел, VM (правила и security groups), выключен по
  умолчанию. Включаешь — сначала разреши себе 8006 и 22, иначе отрежешь интерфейс.

---

## 10. Кластер: corosync и кворум

```bash
# на pve1
pvecm create lab-cluster
# на pve2 и pve3 (узлы без VM!)
pvecm add 10.10.10.11
pvecm status
pvecm nodes
```text
**Кворум** — большинство голосов: `floor(N/2) + 1`. Только узлы в кворуме могут менять
`/etc/pve` (запускать, создавать, мигрировать VM). Без кворума `/etc/pve` — только чтение,
уже работающие VM продолжают работать (если нет HA).

```text
 3 узла, 3 голоса, кворум = 2          2 узла, 2 голоса, кворум = 2
 ┌────┐ ┌────┐ ┌────┐                  ┌────┐     ┌────┐
 │pve1│ │pve2│ │pve3│                  │pve1│  ✗  │pve2│   упал один — у второго 1 голос из 2:
 └────┘ └────┘ └─✗──┘                  └────┘     └────┘   кворума нет, кластер «встал»
 упал один — 2 из 3 ✅                  → нужен третий голос: QDevice
 разрыв сети 2|1 — работает сторона с 2, одиночка знает, что она в меньшинстве (нет split-brain)
```text
- **Почему 3 узла:** это минимум, когда падение одного не останавливает кластер и HA.
- **QDevice** — внешний «арбитр» с одним голосом для кластеров из **чётного** числа узлов
  (прежде всего 2): на отдельной машине `apt install corosync-qnetd`, на узлах —
  `apt install corosync-qdevice`, затем `pvecm qdevice setup &lt;IP&gt;`. Для нечётных кластеров
  Proxmox QDevice не рекомендует.
- **Требования:** UDP 5405–5412 между узлами, задержка < 5 мс (LAN, не WAN), синхронное время,
  одинаковые версии, лучше отдельная сеть для corosync и второй линк на резерв. Corosync'у
  нужна не полоса, а стабильно низкая задержка — бэкапы по той же сети рушат кластер.
- Имя и IP узла выбирай до создания кластера: переименовать узел потом — боль.

---

## 11. HA

Требования: **3+ узла**, **общее хранилище** (или ZFS-репликация), фенсинг. Фенсинг
в Proxmox — watchdog: узел, потерявший кворум, с активными HA-ресурсами сам перезагружается
через 60 секунд, чтобы его VM гарантированно не работали в двух местах одновременно.
Типичное время обнаружения отказа и восстановления — около 2 минут.

```bash
ha-manager add vm:101 --state started --max_restart 1 --max_relocate 1
ha-manager status
ha-manager rules add node-affinity app1-on-pve1 --resources vm:101 --nodes pve1   # предпочитать pve1
ha-manager rules add resource-affinity apps-apart --affinity negative --resources vm:101,vm:102
qm migrate 102 pve2 --online          # живая миграция (с общим хранилищем)
```text
- С 9.0 **HA rules** (node-affinity, resource-affinity) заменили HA groups — старые команды
  групп помечены устаревшими.
- HA ≠ живая миграция: HA **перезапускает** VM на другом узле после смерти хоста (простой
  на время перезагрузки гостя), миграция — плановый переезд без простоя.

---

## 12. Бэкапы: vzdump и Proxmox Backup Server

| Режим vzdump | Как | Простой | Консистентность |
|--------------|-----|---------|-----------------|
| `snapshot` (по умолчанию) | Бэкап работающей VM (с fsfreeze через агент) | Нет | Хорошая при агенте |
| `suspend` | Пауза на время копирования | Заметный | Не лучше snapshot — не рекомендуют |
| `stop` | Выключить, бэкап, включить | Короткий | Максимальная |

```bash
vzdump 101 --storage local --mode snapshot --compress zstd --notes-template '&#123;&#123;guestname&#125;&#125; manual'
ls -lh /var/lib/vz/dump/                       # vzdump-qemu-101-&lt;дата&gt;.vma.zst + .log
vzdump 200 --storage local --mode snapshot     # LXC → .tar.zst

qmrestore /var/lib/vz/dump/vzdump-qemu-101-&lt;дата&gt;.vma.zst 201 --storage local-lvm   # в НОВЫЙ VMID
pct restore 300 /var/lib/vz/dump/vzdump-lxc-200-&lt;дата&gt;.tar.zst --storage local-lvm
```text
Расписание: Datacenter → Backup (хранится в `/etc/pve/jobs.cfg`), хранение —
`--prune-backups keep-daily=7,keep-weekly=4,keep-monthly=3`.

**Proxmox Backup Server:**
- **Инкрементально и с дедупликацией:** данные режутся на чанки, одинаковые чанки хранятся
  один раз; у работающих VM dirty bitmap помнит изменённые блоки — ежедневный бэкап
  копирует только их.
- Шифрование на клиенте, **verify**-задания (проверка целостности), синхронизация на
  удалённый PBS, в 4.2 — S3-совместимое хранилище как бэкенд.
- **File restore** — достать отдельный файл из бэкапа VM, не восстанавливая её целиком.

```bash
pvesm add pbs pbs01 --server 10.10.10.20 --datastore store1 \
  --username root@pam --fingerprint &lt;SHA256 из дашборда PBS&gt; --password
vzdump 101 --storage pbs01
```text
> ⭐ Бэкап, из которого ни разу не восстанавливали, — это надежда, а не бэкап. Правило
> 3-2-1: три копии, на двух типах носителей, одна вне площадки. И регулярный тест
> восстановления (лаба 4).

---

## 13. API и токены

Всё, что делает веб-интерфейс, — вызовы REST API `https://&lt;узел&gt;:8006/api2/json/...`.
Для автоматизации (Terraform, Ansible, Packer, скрипты) — **API-токены**, а не пароль root.

```bash
pveum user add terraform@pve --comment "IaC"
pveum acl modify / --users terraform@pve --roles PVEAdmin   # на стенде; в проде — своя роль с минимумом прав
pveum user token add terraform@pve tf --privsep 0           # секрет показывается ОДИН раз
#  ┌──────────────┬──────────────────────────────────────┐
#  │ full-tokenid │ terraform@pve!tf                     │
#  │ value        │ 3f0c9a4e-....                        │
#  └──────────────┴──────────────────────────────────────┘

curl -sk -H 'Authorization: PVEAPIToken=terraform@pve!tf=3f0c9a4e-....' \
  https://10.10.10.11:8006/api2/json/cluster/resources?type=vm | jq '.data[] | {vmid, name, status}'

pvesh get /cluster/resources --type vm --output-format json-pretty    # то же с узла
pvesh get /nodes/pve1/qemu/101/status/current
```text
- `--privsep 1` (по умолчанию) — у токена свои права, которые надо выдать отдельно
  (`pveum acl modify / --tokens 'terraform@pve!tf' --roles ...`), и они не шире прав
  пользователя. `--privsep 0` — токен получает все права пользователя.
- Токен отзывается отдельно от пользователя — утёк из CI? Удаляешь токен, пароль не меняешь.

---

## 14. Грабли

| Симптом | Причина | Что делать |
|---------|---------|-----------|
| `apt update`: 401 Unauthorized от enterprise.proxmox.com | Enterprise-репо без подписки | `Enabled: no` в `pve-enterprise.sources` и `ceph.sources`, добавить no-subscription |
| `KVM virtualisation configured, but not available` | Nested: у VM-гипервизора нет `vmx`/`svm` | `nested=1` на хосте, `host-passthrough` у pve1 |
| Клон стартует, но не получает IP/ключ | Нет диска cloudinit или пустые `ipconfig0`/`sshkeys` | `qm cloudinit dump &lt;id&gt; user`, проверить `ide2 ...cloudinit` |
| Консоль VM из облачного образа пустая | Образ пишет в серийную консоль | `--serial0 socket --vga serial0` |
| IP в интерфейсе не показывается | Нет/не запущен qemu-guest-agent или `agent` выключен | Вшить агент в шаблон, `--agent enabled=1` |
| `apt upgrade` сломал узел | Для Proxmox нужен `full-upgrade` | Только `apt full-upgrade` |
| Не удаляется шаблон | От него есть linked clones | Сначала клоны или делай `--full` клоны |
| Узел не добавляется в кластер | На узле есть VM или конфликт VMID/имени | Добавлять пустой узел; имя и IP — до кластера |
| Кластер «встал» после падения одного из двух узлов | Нет кворума | 3 узла или QDevice; `pvecm expected 1` — только в аварии и осознанно |
| HA не спасла VM при отказе узла | Диск VM на local-lvm упавшего узла | Общее хранилище или ZFS-репликация |
| Бэкапы по сети corosync — кластер разваливается | Задержки corosync | Отдельная сеть/линк для corosync |
| Включил firewall Datacenter — пропал веб-интерфейс | Нет разрешающих правил | Правила на 8006/22 до включения; с консоли — `pve-firewall stop` |

---

## 💼 Как это в DevOps

- **Замена VMware:** Proxmox — самый частый кандидат. Девопс переносит шаблоны (Packer),
  провижининг (Terraform bpg/proxmox), инвентарь (Ansible), бэкапы (PBS) и мониторинг
  (экспортер метрик Proxmox → Prometheus). В 8.2+ есть мастер импорта VM прямо с ESXi.
- **Шаблон с cloud-init + клоны** — стандарт выдачи VM: руками в интерфейсе делаешь только
  шаблон (а лучше и его — Packer'ом), остальное — Terraform.
- **Кластер и HA** требуют дисциплины: отдельная сеть corosync, общее хранилище, тесты
  отказа узла. HA — не бесплатное «само починится».
- **Бэкап = PBS + проверенное восстановление + копия вне площадки.** На собесе ценится
  фраза «мы раз в месяц восстанавливаем случайную VM и засекаем время».
- **API-токены на каждую систему** (Terraform, Ansible, мониторинг) с минимальными правами —
  отзываются по одному.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Репо без подписки (PVE 9) | `Enabled: no` в `pve-enterprise.sources`/`ceph.sources` + `proxmox.sources` с `pve-no-subscription` |
| Обновить узел | `apt update && apt full-upgrade` |
| VM и CT | `qm list`, `pct list`, `pvesh get /cluster/resources --type vm` |
| Конфиг VM | `qm config 101`, `/etc/pve/qemu-server/101.conf` |
| Импорт облачного образа | `qm set 9000 --scsi0 local-lvm:0,import-from=/path/img` |
| Диск cloud-init | `qm set 9000 --ide2 local-lvm:cloudinit` |
| Шаблон / клон | `qm template 9000`, `qm clone 9000 101 --name app1 [--full 1]` |
| Cloud-init параметры | `qm set 101 --ciuser u --sshkeys f --ipconfig0 ip=dhcp` |
| Что сгенерировал cloud-init | `qm cloudinit dump 101 user` |
| Увеличить диск | `qm disk resize 101 scsi0 +10G` |
| VM в VLAN | `qm set 101 --net0 virtio,bridge=vmbr0,tag=20` |
| Шаблоны LXC | `pveam update; pveam available --section system; pveam download local &lt;tpl&gt;` |
| Хранилища | `pvesm status`, `/etc/pve/storage.cfg` |
| Кластер | `pvecm create N`, `pvecm add &lt;IP&gt;`, `pvecm status` |
| QDevice | `pvecm qdevice setup &lt;IP&gt;` |
| HA | `ha-manager add vm:101`, `ha-manager status`, `ha-manager rules add ...` |
| Миграция | `qm migrate 101 pve2 --online` |
| Бэкап / восстановление | `vzdump 101 --storage S --mode snapshot --compress zstd`; `qmrestore &lt;файл&gt; 201` |
| Токен | `pveum user token add user@pve id --privsep 0` |
| API | `curl -H 'Authorization: PVEAPIToken=user@pve!id=SECRET' https://host:8006/api2/json/...` |

---

## 🧠 Что запомнить

1. Proxmox VE = Debian + KVM/QEMU + LXC + веб/API + кластер + бэкапы; libvirt не используется.
2. Nested-стенд: у VM-гипервизора `host-passthrough`, внутри `grep vmx|svm` > 0.
3. В PVE 9 репозитории — deb822 `.sources`; без подписки выключи enterprise и включи `pve-no-subscription`; обновление — только `full-upgrade`.
4. `/etc/pve` — общая для кластера pmxcfs; конфиг VM — `/etc/pve/qemu-server/&lt;vmid&gt;.conf`.
5. Шаблон = облачный образ + `import-from` + диск `cloudinit` + serial + агент → `qm template`; клоны — linked или full.
6. Хранилище определяет возможности: снапшоты, миграция без копирования, HA — только с общим хранилищем или ZFS-репликацией.
7. VLAN в Proxmox — `bridge-vlan-aware yes` на vmbr0 и `tag=N` у NIC VM.
8. Кворум = большинство голосов; 3 узла — минимум для HA, для 2 узлов — QDevice.
9. HA перезапускает VM после отказа узла (фенсинг watchdog'ом, ~2 минуты), живая миграция — плановый переезд без простоя.
10. vzdump/PBS + регулярная проверка восстановления; автоматизация — через API-токены с минимальными правами.

➡️ Дальше: [05_lxc_containers.md](/virtualization/05-lxc-containers) · задачи: 04_proxmox_tasks.md


---

### Блок A. Теория


**A1.** Из чего состоит Proxmox VE? Чем его стек отличается от «libvirt + virsh»?

<details><summary>Ответ</summary>

Debian + ядро с KVM + QEMU (`qm`) + LXC (`pct`) + веб-интерфейс и REST API + кластер
(corosync, pmxcfs `/etc/pve`) + HA (`ha-manager`) + плагины хранилищ (LVM-thin, ZFS, NFS, Ceph,
PBS) + бэкапы (vzdump). libvirt не используется: свой формат конфигов VM и свои инструменты,
всё управляется через API, а кластер и HA встроены.

</details>

**A2.** Что нужно, чтобы Proxmox внутри KVM-VM мог запускать VM с KVM? Как проверить?

<details><summary>Ответ</summary>

На хосте `nested=1` у `kvm_intel`/`kvm_amd`, у VM-гипервизора `host-passthrough`.
Проверка внутри pve1: `grep -cE 'vmx|svm' /proc/cpuinfo` > 0 и VM в Proxmox стартуют с KVM
(нет ошибки «KVM virtualisation configured, but not available»).

</details>

**A3.** Чем enterprise-репозиторий отличается от no-subscription? Как репозитории описаны
в Proxmox VE 9? Почему обновляют через `apt full-upgrade`?

<details><summary>Ответ</summary>

Enterprise — более обкатанные пакеты, доступ по подписке; no-subscription — бесплатно,
пакеты приходят раньше, для тестов и небольших установок. В PVE 9 репозитории — файлы deb822
`*.sources` (`pve-enterprise.sources`, `ceph.sources`, `proxmox.sources`), выключаются строкой
`Enabled: no`. `full-upgrade` нужен, потому что обновления Proxmox меняют зависимости
(новые пакеты, замены), а `apt upgrade` их не ставит и может оставить систему в
несогласованном состоянии.

</details>

**A4.** Что такое `/etc/pve` и почему там нельзя хранить большие файлы?

<details><summary>Ответ</summary>

pmxcfs — кластерная ФС на базе SQLite, смонтированная в `/etc/pve` и реплицируемая
на все узлы через corosync. Там конфиги VM, хранилищ, кластера, пользователей и токенов.
Она маленькая (рассчитана на конфиги, ограничена по размеру) и синхронна между узлами —
большие файлы туда класть нельзя.

</details>

**A5.** ⭐ Перечисли шаги создания шаблона VM с cloud-init из облачного образа.

<details><summary>Ответ</summary>

Скачать облачный образ (и проверить контрольную сумму) → при желании вшить
`qemu-guest-agent` (`virt-customize`) → `qm create` с `--scsihw virtio-scsi-single`, NIC на
`vmbr0`, `--agent enabled=1`, `--cpu`, `--ostype l26` → импорт диска
`--scsi0 local-lvm:0,import-from=&lt;img&gt;` → диск cloud-init `--ide2 local-lvm:cloudinit` →
`--boot order=scsi0` → `--serial0 socket --vga serial0` → `ciuser`, `sshkeys`, `ipconfig0` →
увеличить диск → `qm template`.

</details>

**A6.** Чем linked clone отличается от full clone?

<details><summary>Ответ</summary>

Linked clone — overlay поверх диска шаблона: создаётся мгновенно и занимает мало,
но зависит от шаблона (его нельзя удалить) и живёт на том же хранилище. Full clone — полная
независимая копия: дольше и больше места, зато не зависит от шаблона и может лежать
на другом хранилище.

</details>

**A7.** Какой тип CPU выбрать для VM: `x86-64-v2-AES` или `host`? От чего зависит?

<details><summary>Ответ</summary>

`x86-64-v2-AES` — общая модель, работает на любом современном хосте и позволяет живую
миграцию в разнородном кластере. `host` — все инструкции CPU хоста и максимум скорости, но
миграция только между одинаковыми CPU. Одинаковые узлы и нужна скорость — `host`; разные
поколения CPU — общая модель.

</details>

**A8.** ⭐ Какие хранилища Proxmox общие для кластера, какие поддерживают снапшоты? Когда ZFS,
когда Ceph?

<details><summary>Ответ</summary>

Общие: NFS, CIFS, LVM на iSCSI/FC, Ceph RBD, PBS (для бэкапов). Локальные: `dir`,
`lvmthin`, `zfspool`. Снапшоты: LVM-thin, ZFS, Ceph, qcow2 на файловых хранилищах
(dir/NFS), толстый LVM — с 9.0. ZFS — надёжность данных, сжатие, репликация между узлами без
общего хранилища, на 1–3 узлах. Ceph — гиперконвергентный кластер от трёх узлов с быстрой
сетью, общий и отказоустойчивый.

</details>

**A9.** Как в Proxmox VM попадает в нужный VLAN?

<details><summary>Ответ</summary>

`vmbr0` делают VLAN-aware (`bridge-vlan-aware yes`, `bridge-vids`), физический порт —
транк; у NIC VM указывают `tag=20` — Proxmox сам настроит порт как access в VLAN 20.
Альтернатива — отдельный бридж на VLAN-интерфейсе (`vmbr0v20` на `bond0.20`).

</details>

**A10.** ⭐ Что такое кворум? Формула. Почему для кластера минимум три узла? Что такое QDevice
и когда он нужен?

<details><summary>Ответ</summary>

Кворум — большинство голосов кластера: `floor(N/2) + 1`. Только часть кластера с
кворумом может менять конфигурацию и запускать VM, это защищает от split-brain. При двух узлах
кворум = 2: падение любого останавливает кластер. При трёх кворум = 2: переживаем отказ одного.
QDevice — внешний арбитр (corosync-qnetd) с дополнительным голосом, нужен кластерам с чётным
числом узлов, прежде всего из двух.

</details>

**A11.** Какие требования у corosync к сети?

<details><summary>Ответ</summary>

UDP 5405–5412 между всеми узлами, стабильная задержка ниже 5 мс (LAN), синхронное
время, SSH между узлами; желательно отдельная сеть и резервный линк (corosync поддерживает
до 8 линков). Полоса не важна — важна задержка, поэтому нельзя делить линк с бэкапами.

</details>

**A12.** Что нужно для HA в Proxmox? Как работает фенсинг?

<details><summary>Ответ</summary>

Минимум три узла, общее хранилище (или ZFS-репликация), надёжное железо. Фенсинг —
watchdog: если узел с активными HA-ресурсами теряет кворум, через 60 с он перезагружается сам,
а кластер после этого безопасно запускает его VM на других узлах. Типичное время
восстановления — около двух минут.

</details>

**A13.** Чем HA отличается от живой миграции?

<details><summary>Ответ</summary>

HA реагирует на отказ: VM перезапускается на другом узле, простой — время
обнаружения + загрузки гостя. Живая миграция — плановая операция на исправных узлах, VM
переезжает работающей, без простоя.

</details>

**A14.** Какие режимы есть у vzdump и какой выбирать?

<details><summary>Ответ</summary>

`snapshot` — бэкап работающей VM без простоя (с fsfreeze через агент) — выбор по
умолчанию; `suspend` — пауза на время копирования, выгоды почти нет; `stop` — выключение
на время старта бэкапа, максимальная консистентность ценой короткого простоя.

</details>

**A15.** Чем Proxmox Backup Server лучше, чем vzdump-файлы на NFS?

<details><summary>Ответ</summary>

Инкрементальные бэкапы (dirty bitmap), дедупликация чанков (десятки копий занимают
мало), шифрование на клиенте, verify-задания, prune/GC, синхронизация на удалённый PBS и S3,
восстановление отдельных файлов, быстрый live-restore. vzdump на NFS — полные архивы каждый
раз без дедупликации и проверки.

</details>

**A16.** Зачем API-токены, если есть пароль root? Что значит `--privsep`?

<details><summary>Ответ</summary>

Токен выдаётся на систему (Terraform, CI, мониторинг), имеет свои права, отзывается
отдельно и не раскрывает пароль. `--privsep 1` (по умолчанию) — права токена задаются
отдельными ACL и не шире прав пользователя; `--privsep 0` — токен наследует все права
пользователя.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  $ apt update
```text
<details><summary>Ответ</summary>

⚠️ Включён enterprise-репозиторий без подписки. `Enabled: no` в
`pve-enterprise.sources` (и `ceph.sources`), добавить `proxmox.sources` с `pve-no-subscription`.

</details>

```text:no-line-numbers
     Err:4 https://enterprise.proxmox.com/debian/pve trixie InRelease
```text
```text:no-line-numbers
       401  Unauthorized [IP: ...]
```text
```text:no-line-numbers
B2.  root@pve1:~# apt upgrade -y        # «обычный Debian же»
```text
<details><summary>Ответ</summary>

⚠️ `apt upgrade` не ставит новые зависимости и не убирает заменённые пакеты — узел
может остаться полуобновлённым. Нужен `apt full-upgrade`.

</details>

```text:no-line-numbers
B3.  # кластер из 2 узлов, pve2 выключили на обслуживание
```text
<details><summary>Ответ</summary>

⚠️ В кластере из двух узлов после выключения одного нет кворума — конфигурация
только для чтения, VM не стартуют. Вернуть pve2, добавить QDevice или третий узел;
временно `pvecm expected 1` — осознанно и только пока второй узел гарантированно выключен.

</details>

```text:no-line-numbers
     root@pve1:~# qm start 101
```text
```text:no-line-numbers
     cluster not ready - no quorum? (500)
```text
```text:no-line-numbers
B4.  root@pve2:~# qm list      # на pve2 уже есть VM 100
```text
<details><summary>Ответ</summary>

⚠️ Узел с гостями добавлять нельзя (конфликт VMID и конфигов) — `pvecm add` откажет.
Перенести/забэкапить VM, удалить их, добавить пустой узел, восстановить.

</details>

```text:no-line-numbers
     root@pve2:~# pvecm add 10.10.10.11
```text
```text:no-line-numbers
B5.  # HA-ресурс vm:101, диск VM на local-lvm узла pve1; pve1 сгорел
```text
<details><summary>Ответ</summary>

⚠️ HA не поднимет VM: её диск был на локальном хранилище погибшего узла. Нужно общее
хранилище или ZFS-репликация (с потерей данных с последней синхронизации).

</details>

```text:no-line-numbers
B6.  root@pve1:~# qm template 9000
```text
<details><summary>Ответ</summary>

⚠️ Шаблон нельзя запустить — ошибка «you can't start a vm if it's a template».
Клонировать и запускать клон.

</details>

```text:no-line-numbers
     root@pve1:~# qm start 9000
```text
```text:no-line-numbers
B7.  # в шаблоне: --cicustom "user=local:snippets/pkgs.yaml"
```text
<details><summary>Ответ</summary>

⚠️ `cicustom user=` полностью заменяет сгенерированный user-data: `ciuser`/`sshkeys`
больше не применяются. Добавить пользователя и `ssh_authorized_keys` в свой файл.

</details>

```text:no-line-numbers
     # pkgs.yaml: #cloud-config + packages: [nginx]
```text
```text:no-line-numbers
     # клоны: nginx есть, а зайти по SSH ключом нельзя
```text
```text:no-line-numbers
B8.  # Datacenter → Firewall → Options → Firewall: Yes   (правил нет)
```text
<details><summary>Ответ</summary>

⚠️ Политика по умолчанию для входящего — DROP: можно отрезать себе веб-интерфейс и SSH
(Proxmox оставляет доступ из локальной сети кластера, но полагаться не стоит). Сначала
правила на 8006/22, потом включение.

</details>

```text:no-line-numbers
B9.  # corosync и ночные бэкапы по одному линку 1G; каждую ночь узлы «выпадают» из кластера
```text
<details><summary>Ответ</summary>

⚠️ Бэкапы забивают линк, задержки corosync растут — узлы теряют членство, а с HA ещё и
фенсятся. Отдельная сеть/линк для corosync, второй линк, ограничение полосы бэкапов (`bwlimit`).

</details>

```text:no-line-numbers
B10.  root@pve1:~# qm create 9001 --name tpl2 --memory 2048 --net0 virtio,bridge=vmbr0
```text
<details><summary>Ответ</summary>

⚠️ Через CLI без явных параметров — `cpu: kvm64`-дефолт (в конфиге пусто) и
`scsihw: lsi`: старая модель CPU и медленный эмулируемый контроллер. Задавать `--cpu` и
`--scsihw virtio-scsi-single`.

</details>

```text:no-line-numbers
     root@pve1:~# qm config 9001 | grep -E 'cpu|scsihw'
```text
```text:no-line-numbers
B11.  «Бэкапы у нас есть: vzdump каждую ночь в local на том же узле»
```text
<details><summary>Ответ</summary>

⚠️ Бэкап на том же узле погибнет вместе с ним. Нужны PBS/отдельное хранилище, копия
вне площадки (3-2-1) и проверка восстановления.

</details>

```text:no-line-numbers
B12.  root@pve1:~# pveum user token add terraform@pve tf     # без --privsep 0
```text
<details><summary>Ответ</summary>

⚠️ С `privsep=1` у токена нет прав, пока их не выдать отдельно:
`pveum acl modify / --tokens 'terraform@pve!tf' --roles &lt;роль&gt;`, или пересоздать токен с
`--privsep 0`.

</details>

```text:no-line-numbers
     # terraform: 403 Permission check failed
```text
---

### Блок C. Практика


### C1. 🔑 Поднять pve1
**1.** Установи Proxmox VE 9.2 вложенно по разделу 2 конспекта.

<details><summary>Ответ</summary>

Проверка: `grep -cE 'vmx|svm' /proc/cpuinfo` в pve1 > 0, `pveversion` показывает
`pve-manager/9.2...`, `apt update` без ошибок.

</details>

**2.** Настрой no-subscription, обнови узел, перезагрузи.

<details><summary>Ответ</summary>

`lvs` на узле: у linked clone тонкий том с небольшим `Data%` поверх `base-9000-disk-0`,
у full clone — независимый том с копией данных шаблона. `qm guest cmd 101 network-get-interfaces`
возвращает JSON с адресами — значит, агент работает.

</details>

**3.** Докажи, что внутри pve1 доступен KVM. Сделай на хосте `virsh snapshot-create-as pve1 --name clean`.

<details><summary>Ответ</summary>

`pct create 200 local:vztmpl/debian-13-standard_...tar.zst --hostname ct1 --memory 512
--rootfs local-lvm:8 --net0 name=eth0,bridge=vmbr0,ip=dhcp --unprivileged 1 --features nesting=1`,
`pct start 200`, `pct enter 200`; `pct snapshot 200 base`, `pct rollback 200 base`
(снапшоты работают, потому что rootfs на LVM-thin).

</details>

### C2. 🔑 Шаблон и три клона
**1.** Сделай шаблон 9000 из облачного образа Ubuntu 24.04 с cloud-init и вшитым агентом.

<details><summary>Ответ</summary>

Проверка: `grep -cE 'vmx|svm' /proc/cpuinfo` в pve1 > 0, `pveversion` показывает
`pve-manager/9.2...`, `apt update` без ошибок.

</details>

**2.** Склонируй `app1..app3` (linked) со статическими адресами `10.10.10.21–23`.

<details><summary>Ответ</summary>

`lvs` на узле: у linked clone тонкий том с небольшим `Data%` поверх `base-9000-disk-0`,
у full clone — независимый том с копией данных шаблона. `qm guest cmd 101 network-get-interfaces`
возвращает JSON с адресами — значит, агент работает.

</details>

**3.** Зайди по SSH, проверь IP через агента (`qm guest cmd`), посмотри `qm cloudinit dump 101 user`.

<details><summary>Ответ</summary>

`pct create 200 local:vztmpl/debian-13-standard_...tar.zst --hostname ct1 --memory 512
--rootfs local-lvm:8 --net0 name=eth0,bridge=vmbr0,ip=dhcp --unprivileged 1 --features nesting=1`,
`pct start 200`, `pct enter 200`; `pct snapshot 200 base`, `pct rollback 200 base`
(снапшоты работают, потому что rootfs на LVM-thin).

</details>

**4.** Сделай один full clone. Сравни, сколько места заняли linked и full (`lvs` на узле).

<details><summary>Ответ</summary>

`pvesm add nfs nfs-lab --server &lt;IP&gt; --export &lt;путь&gt; --content images,rootdir,backup`.
`qm disk move 101 scsi0 nfs-lab` работает на ходу (у linked clone диск станет самостоятельным).
С диском на общем хранилище VM можно мигрировать между узлами без копирования дисков и
добавить в HA.

</details>

### C3. LXC
Создай unprivileged-контейнер `ct1` (Debian 13, 512 МБ, `nesting=1`), зайди через `pct enter`,
поставь `nginx`. Сделай снапшот `pct snapshot 200 base`, сломай nginx, откатись `pct rollback`.

### C4. Хранилища
**1.** Добавь NFS-хранилище (экспорт с `nfs01` или хоста, сеть `virt-lab`).

<details><summary>Ответ</summary>

Проверка: `grep -cE 'vmx|svm' /proc/cpuinfo` в pve1 > 0, `pveversion` показывает
`pve-manager/9.2...`, `apt update` без ошибок.

</details>

**2.** Перенеси диск `app1` на NFS на ходу: `qm disk move 101 scsi0 nfs-lab`.

<details><summary>Ответ</summary>

`lvs` на узле: у linked clone тонкий том с небольшим `Data%` поверх `base-9000-disk-0`,
у full clone — независимый том с копией данных шаблона. `qm guest cmd 101 network-get-interfaces`
возвращает JSON с адресами — значит, агент работает.

</details>

**3.** Сравни в `pvesm status` и объясни, какие функции появились у `app1` (подсказка: миграция).

<details><summary>Ответ</summary>

`pct create 200 local:vztmpl/debian-13-standard_...tar.zst --hostname ct1 --memory 512
--rootfs local-lvm:8 --net0 name=eth0,bridge=vmbr0,ip=dhcp --unprivileged 1 --features nesting=1`,
`pct start 200`, `pct enter 200`; `pct snapshot 200 base`, `pct rollback 200 base`
(снапшоты работают, потому что rootfs на LVM-thin).

</details>

### C5. VLAN внутри Proxmox
**1.** Сделай `vmbr0` VLAN-aware (`bridge-vlan-aware yes`, `bridge-vids 2-4094`), примени `ifreload -a`
   (с консоли pve1, не по SSH!).

<details><summary>Ответ</summary>

Проверка: `grep -cE 'vmx|svm' /proc/cpuinfo` в pve1 > 0, `pveversion` показывает
`pve-manager/9.2...`, `apt update` без ошибок.

</details>

**2.** `app2` и `app3` положи в VLAN 20 (`tag=20`), им — адреса `10.0.20.2/.3` на втором
   интерфейсе или вместо основного.

<details><summary>Ответ</summary>

`lvs` на узле: у linked clone тонкий том с небольшим `Data%` поверх `base-9000-disk-0`,
у full clone — независимый том с копией данных шаблона. `qm guest cmd 101 network-get-interfaces`
возвращает JSON с адресами — значит, агент работает.

</details>

**3.** Докажи: `app2 ↔ app3` видят друг друга, `app1` (без тега) их не видит.

<details><summary>Ответ</summary>

`pct create 200 local:vztmpl/debian-13-standard_...tar.zst --hostname ct1 --memory 512
--rootfs local-lvm:8 --net0 name=eth0,bridge=vmbr0,ip=dhcp --unprivileged 1 --features nesting=1`,
`pct start 200`, `pct enter 200`; `pct snapshot 200 base`, `pct rollback 200 base`
(снапшоты работают, потому что rootfs на LVM-thin).

</details>

### C6. 🔑 Бэкап и восстановление
**1.** На `app1` создай файл-маркер с датой. Сделай `vzdump 101 --mode snapshot --compress zstd`.

<details><summary>Ответ</summary>

Проверка: `grep -cE 'vmx|svm' /proc/cpuinfo` в pve1 > 0, `pveversion` показывает
`pve-manager/9.2...`, `apt update` без ошибок.

</details>

**2.** Удали маркер, «сломай» VM.

<details><summary>Ответ</summary>

`lvs` на узле: у linked clone тонкий том с небольшим `Data%` поверх `base-9000-disk-0`,
у full clone — независимый том с копией данных шаблона. `qm guest cmd 101 network-get-interfaces`
возвращает JSON с адресами — значит, агент работает.

</details>

**3.** Восстанови бэкап в VMID 201, запусти (не забудь, что у копии тот же IP — поменяй
   `ipconfig0` до старта или выключи `app1`), найди маркер. Засеки время восстановления.

<details><summary>Ответ</summary>

`pct create 200 local:vztmpl/debian-13-standard_...tar.zst --hostname ct1 --memory 512
--rootfs local-lvm:8 --net0 name=eth0,bridge=vmbr0,ip=dhcp --unprivileged 1 --features nesting=1`,
`pct start 200`, `pct enter 200`; `pct snapshot 200 base`, `pct rollback 200 base`
(снапшоты работают, потому что rootfs на LVM-thin).

</details>

### C7. API
**1.** Создай пользователя `terraform@pve`, выдай роль, создай токен.

<details><summary>Ответ</summary>

Проверка: `grep -cE 'vmx|svm' /proc/cpuinfo` в pve1 > 0, `pveversion` показывает
`pve-manager/9.2...`, `apt update` без ошибок.

</details>

**2.** `curl` — список VM; `curl -X POST` — запусти VM 102.

<details><summary>Ответ</summary>

`lvs` на узле: у linked clone тонкий том с небольшим `Data%` поверх `base-9000-disk-0`,
у full clone — независимый том с копией данных шаблона. `qm guest cmd 101 network-get-interfaces`
возвращает JSON с адресами — значит, агент работает.

</details>

**3.** То же через `pvesh`. Какие пути API у операций «клонировать» и «изменить конфиг»?

<details><summary>Ответ</summary>

`pct create 200 local:vztmpl/debian-13-standard_...tar.zst --hostname ct1 --memory 512
--rootfs local-lvm:8 --net0 name=eth0,bridge=vmbr0,ip=dhcp --unprivileged 1 --features nesting=1`,
`pct start 200`, `pct enter 200`; `pct snapshot 200 base`, `pct rollback 200 base`
(снапшоты работают, потому что rootfs на LVM-thin).

</details>

### C8. Кластер и HA (бонус, нужно ~16 ГБ RAM под стенд)
**1.** Три узла, `pvecm create` / `pvecm add`, NFS как общее хранилище.

<details><summary>Ответ</summary>

Проверка: `grep -cE 'vmx|svm' /proc/cpuinfo` в pve1 > 0, `pveversion` показывает
`pve-manager/9.2...`, `apt update` без ошибок.

</details>

**2.** `app1` на NFS, `ha-manager add vm:101`.

<details><summary>Ответ</summary>

`lvs` на узле: у linked clone тонкий том с небольшим `Data%` поверх `base-9000-disk-0`,
у full clone — независимый том с копией данных шаблона. `qm guest cmd 101 network-get-interfaces`
возвращает JSON с адресами — значит, агент работает.

</details>

**3.** На хосте `virsh destroy pve1` (где работает app1). Засеки, через сколько app1 поднимется
   на другом узле. Что в `ha-manager status` в процессе?

<details><summary>Ответ</summary>

`pct create 200 local:vztmpl/debian-13-standard_...tar.zst --hostname ct1 --memory 512
--rootfs local-lvm:8 --net0 name=eth0,bridge=vmbr0,ip=dhcp --unprivileged 1 --features nesting=1`,
`pct start 200`, `pct enter 200`; `pct snapshot 200 base`, `pct rollback 200 base`
(снапшоты работают, потому что rootfs на LVM-thin).

</details>

**4.** Верни pve1. Что с кворумом при двух выключенных узлах?

<details><summary>Ответ</summary>

`pvesm add nfs nfs-lab --server &lt;IP&gt; --export &lt;путь&gt; --content images,rootdir,backup`.
`qm disk move 101 scsi0 nfs-lab` работает на ходу (у linked clone диск станет самостоятельным).
С диском на общем хранилище VM можно мигрировать между узлами без копирования дисков и
добавить в HA.

</details>

---

### Блок D. Инциденты


**D1.** Был один узел, добавили второй «на будущее». Выключили второй на обслуживание —
на первом VM не стартуют, в интерфейсе нельзя ничего поменять. Что случилось, что делать
сейчас и как правильно?

<details><summary>Ответ</summary>

Два узла — кворум 2, выключение одного лишает первый кворума: `/etc/pve` только
для чтения. Сейчас: включить второй или `pvecm expected 1` на первом (только если второй
точно выключен). Правильно: сразу три узла или QDevice для двух; для «на будущее» не
собирать кластер заранее.

</details>

**D2.** HA-VM перезапустилась на другом узле, хотя исходный узел был жив. В логах узла —
перезагрузка по watchdog. Ночью шли бэкапы. Объясни цепочку событий и лечение.

<details><summary>Ответ</summary>

Бэкапы забили сеть, задержки corosync выросли, узел потерял кворум; у него были
активные HA-ресурсы — watchdog перезагрузил узел через 60 с, HA подняла VM на другом узле.
Лечение: отдельная сеть corosync + второй линк, `bwlimit` для бэкапов, мониторинг задержек
corosync.

</details>

**D3.** VM на `local-lvm` начали уходить в I/O error и паузу. `lvs` показывает у `data`
`Data%` 100. Как так при «тонком» хранилище и что делать?

<details><summary>Ответ</summary>

Тонкий пул переподписан: суммарный размер дисков больше пула, и данные действительно
заполнили его. Освободить место (удалить снапшоты/ненужные тома, `fstrim` в гостях при
`discard=on`), расширить пул (`lvextend` на свободное место VG или новый диск), вернуть VM
из паузы. Потом — алерт на `Data%` и `Meta%` (например, от 80%).

</details>

**D4.** После `apt full-upgrade` и перезагрузки узел не видит сеть: новый драйвер NIC в новом
ядре. Ты в консоли IPMI. Действия?

<details><summary>Ответ</summary>

Загрузиться со старого ядра из меню загрузчика, закрепить его:
`proxmox-boot-tool kernel pin &lt;версия&gt;`, вернуть сеть, сообщить о проблеме, ждать фикса/обновить
прошивку NIC; после — `proxmox-boot-tool kernel unpin`. Обновлять узлы по одному, начиная
с тестового.

</details>

**D5.** Восстановили LXC-контейнер из бэкапа — система на месте, а данных приложения
в `/data` нет. Почему?

<details><summary>Ответ</summary>

`/data` был bind mount с хоста: содержимое bind mount'ов vzdump не бэкапит. Данные
нужно бэкапить отдельно (на хосте) или держать их на volume mount point (`mp0: local-lvm:...`
с `backup=1`), который входит в бэкап.

</details>

**D6.** Все клоны шаблона получают один и тот же IP по DHCP. Шаблон делали из VM, которую
перед конвертацией один раз запускали, «чтобы проверить». Что пошло не так?

<details><summary>Ответ</summary>

При первом запуске в VM сгенерировались `/etc/machine-id`, SSH host keys и cloud-init
записал состояние экземпляра — всё это ушло в шаблон. DHCP client ID строится из machine-id
→ одинаковые IP. Перед `qm template`: `cloud-init clean --logs --machine-id --seed`, удалить
`/etc/ssh/ssh_host_*`, выключить — или не запускать исходную VM вовсе.

</details>

**D7.** Токен Terraform с правами PVEAdmin попал в публичный репозиторий. Действия по шагам.

<details><summary>Ответ</summary>

1) Сразу удалить токен: `pveum user token remove terraform@pve tf`. 2) Посмотреть, что
им делали: журнал задач (Datacenter → Tasks), `/var/log/pveproxy/access.log` на узлах.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Что такое Proxmox VE и чем он отличается от VMware vSphere?

<details><summary>Ответ</summary>

Open source платформа на Debian: KVM-VM и LXC-контейнеры, веб-интерфейс и API, кластер,
   HA, Ceph/ZFS, бэкапы (PBS). В отличие от vSphere — без отдельного vCenter (управлять можно
   с любого узла), бесплатна с опциональной подпиской, есть системные контейнеры; у vSphere —
   более зрелая экосистема, DRS/vMotion и сторонние интеграции.

</details>

**2.** Как устроен кластер Proxmox? Что такое кворум и почему нужно три узла?

<details><summary>Ответ</summary>

Corosync обеспечивает членство и кворум, pmxcfs реплицирует `/etc/pve` на все узлы. Кворум —
   большинство голосов (`floor(N/2)+1`), без него узел не меняет конфигурацию — защита от
   split-brain. Три узла — минимум, чтобы пережить отказ одного; для двух — QDevice.

</details>

**3.** Как работает HA в Proxmox и что для неё нужно?

<details><summary>Ответ</summary>

`ha-manager` следит за ресурсами (VM/CT); при отказе узла тот самофенсится watchdog'ом
   после потери кворума, а кластер запускает его HA-ресурсы на других узлах (~2 минуты).
   Нужны 3+ узла, общее хранилище или ZFS-репликация, правила размещения — HA rules.

</details>

**4.** Какие хранилища поддерживает Proxmox? Что нужно для живой миграции?

<details><summary>Ответ</summary>

Локальные: dir, LVM-thin, ZFS; общие: NFS/CIFS, LVM на iSCSI/FC, Ceph RBD; PBS для бэкапов.
   Живая миграция: общее хранилище (иначе копирование дисков `--with-local-disks`), совместимый
   CPU-тип, одинаковые сети (бриджи/VLAN) на узлах.

</details>

**5.** Как ты делаешь шаблоны VM?

<details><summary>Ответ</summary>

Облачный образ + cloud-init: импорт диска, диск cloudinit, серийная консоль, агент,
   `qm template`; клоны получают пользователя, ключ и IP через cloud-init. В идеале шаблон
   собирается Packer'ом (proxmox-iso/proxmox-clone) по расписанию.

</details>

**6.** Когда в Proxmox выбрать LXC, а когда VM?

<details><summary>Ответ</summary>

LXC — лёгкие Linux-сервисы без своего ядра (DNS, прокси, мониторинг), быстрый старт,
   высокая плотность. VM — другая ОС, своё ядро/модули, сильная изоляция, живая миграция,
   Docker/Kubernetes (Proxmox рекомендует Docker запускать в VM).

</details>

**7.** Как устроены бэкапы? Что такое Proxmox Backup Server?

<details><summary>Ответ</summary>

vzdump по расписанию (snapshot-режим) в PBS: инкрементально, дедупликация, шифрование,
   verify, хранение по политике, синхронизация на удалённый PBS; регулярная проверка
   восстановления и копия вне площадки.

</details>

**8.** Как автоматизировать Proxmox?

<details><summary>Ответ</summary>

REST API с токенами: Terraform (провайдер bpg/proxmox), Ansible (коллекция community.proxmox
   с inventory-плагином), Packer для шаблонов, `pvesh`/`curl` в скриптах.

</details>

**9.** Как настроить VLAN для VM в Proxmox?

<details><summary>Ответ</summary>

`vmbr0` с `bridge-vlan-aware yes` поверх транка (часто bond), у NIC VM — `tag=N`; либо
   отдельные бриджи на VLAN-интерфейсах; в больших кластерах — SDN-зоны VLAN/VXLAN.

</details>

**10.** Как обновить кластер Proxmox без простоя сервисов?

<details><summary>Ответ</summary>

По одному узлу: мигрировать VM с узла (или maintenance-режим HA), `apt full-upgrade`,
    перезагрузка, проверка `pvecm status`/`ha-manager status`, вернуть VM, следующий узел.
    Сначала тестовый узел/кластер, перед этим — бэкапы.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Поднимаю Proxmox вложенно и проверяю KVM внутри
- [ ] Настраиваю no-subscription в формате deb822 и обновляю через `full-upgrade`
- [ ] ⭐ Делаю шаблон с cloud-init и агентом, клонирую VM со статикой
- [ ] Создаю LXC через `pct`, делаю снапшот и откат
- [ ] Выбираю хранилище под задачу и объясняю, что даёт общее хранилище
- [ ] Кладу VM в VLAN через VLAN-aware `vmbr0` и `tag`
- [ ] ⭐ Объясняю кворум, три узла и QDevice; знаю требования corosync
- [ ] Объясняю HA, фенсинг и разницу с миграцией
- [ ] ⭐ Делаю бэкап и восстанавливаю в новый VMID, знаю, зачем PBS
- [ ] Хожу в API по токену (`curl`, `pvesh`)
