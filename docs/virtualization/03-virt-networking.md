---
title: "03. Сеть для VM: libvirt-сети, bridge, macvtap, VLAN, bonding"
description: "Блок → Виртуализация on-prem → тема 03. Опирается на"
---

# 03. Сеть для VM: libvirt-сети, bridge, macvtap, VLAN, bonding

> Блок → Виртуализация on-prem → тема 03. Опирается на
> [../Network/02_l2_ethernet_arp.md](/network/02-l2-ethernet-arp) (MAC, свитч, VLAN, bridge),
> [../Linux/20_network_config.md](/linux/20-network-config) (`ip`, netplan, nmcli, как не
> потерять сервер) и [../Network/03_l3_ip_icmp.md](/network/03-l3-ip-icmp) (маршруты, NAT, MTU).
>
> **После темы ты умеешь:** выбирать режим сети libvirt (NAT, isolated, routed, bridge, macvtap),
> выводить VM в LAN через Linux bridge (ip, netplan, nmcli), объяснять ограничение macvtap,
> раскладывать VLAN на хосте (bridge на VLAN и VLAN-aware bridge), собирать bond
> (active-backup, LACP) и типовую схему «bond + VLAN + bridge», настраивать jumbo frames
> и разбирать «VM не видит сеть» по слоям.

> ⚠️ **Правило темы.** Любая правка сети хоста может отрезать тебя от него. Эксперименты —
> внутри VM или в изолированных сетях libvirt (лаба 2). На реальном сервере — только
> с консолью (IPMI/iLO/iDRAC) и через `netplan try`
> (см. «Как не потерять сервер» в [../Linux/20_network_config.md](/linux/20-network-config)).

---

## 🗺️ Карта темы

```text
                       ┌──────────────────────── ХОСТ-ГИПЕРВИЗОР ───────────────────────────┐
  VM1 eth0 ── vnet0 ──►│ virbr0 (NAT) ── dnsmasq ── MASQUERADE ──┐                          │
                       │                                         ├──► eno1 ─┐               │
  VM2 eth0 ── vnet1 ──►│ br-prod ◄── bond0.20 ◄── bond0 ◄────────┘          ├── LACP ──► свитч
  VM3 eth0 ── vnet2 ──►│ br-db   ◄── bond0.30 ◄──┘   (eno1+eno2)   eno2 ────┘   (trunk: VLAN 10,20,30)
                       │                                                                    │
  VM4 eth0 ── macvtap ►│ ───────────────────────► напрямую через eno3 (хост ↔ VM4 ✗)        │
                       └────────────────────────────────────────────────────────────────────┘
   vnetX / macvtapN — «кабель» VM в хост; bridge — программный свитч; bond — два кабеля как один;
   bond0.20 — тег VLAN 20; свитч должен быть настроен в пару (trunk, LACP)
```text
---

## 1. Как VM подключается к сети

Каждая сетевая карта VM на хосте — **tap-устройство** `vnetN`: с одной стороны его читает
процесс QEMU, с другой — он воткнут в **bridge** (программный свитч, как `docker0` —
[../Network/02_l2_ethernet_arp.md](/network/02-l2-ethernet-arp), раздел 6).

```bash
virsh domiflist vm1
#  Interface   Type      Source     Model    MAC
#  vnet3       network   virt-lab   virtio   52:54:00:6b:1a:02
ip -br link show master virbr-lab     # какие vnet воткнуты в бридж сети virt-lab
bridge link                           # все порты всех бриджей
virsh domif-getlink vm1 vnet3         # «кабель» воткнут? (up/down)
virsh domif-setlink vm1 vnet3 down    # выдернуть кабель у VM (удобно для тестов failover)
```text
---

## 2. Сети libvirt

| Режим | VM → интернет | Хост ↔ VM | LAN → VM | Адреса | Когда |
|-------|---------------|-----------|----------|--------|-------|
| **NAT** (`default`, `virt-lab`) | Да, через MASQUERADE | Да | Нет (только проброс портов) | dnsmasq libvirt | Стенд, ноутбук |
| **routed** | Да, если роутер знает маршрут назад | Да | Да | dnsmasq libvirt | Есть доступ к роутеру, NAT не нужен |
| **isolated** | Нет | Да, если у сети есть `&lt;ip&gt;` | Нет | dnsmasq или никто | Внутренние сети между VM, «трансляция» L2 |
| **bridge** (готовый `br0` хоста) | Как обычный хост в LAN | Да | Да | DHCP/статика сети LAN | Серверы: VM «как железные» |
| **macvtap** (direct) | Как хост в LAN | ❌ Нет | Да | DHCP/статика LAN | Быстро вывести VM в LAN без правки сети хоста |

```xml
<!-- NAT: сеть стенда virt-lab (полное определение — в 00_INDEX.md) -->
&lt;network&gt;
  &lt;name&gt;virt-lab</name>
  &lt;forward mode='nat'/&gt;
  &lt;bridge name='virbr-lab' stp='on' delay='0'/&gt;
  &lt;ip address='10.10.10.1' netmask='255.255.255.0'&gt;
    &lt;dhcp&gt;&lt;range start='10.10.10.100' end='10.10.10.199'/&gt;</dhcp>
  </ip>
</network>

<!-- isolated без IP на хосте: чистый L2-свитч между VM (лаба 2) -->
&lt;network&gt;
  &lt;name&gt;lab-trunk</name>
  &lt;bridge name='virbr-trunk' stp='off' delay='0'/&gt;
</network>

<!-- routed: без NAT; на роутере нужен маршрут 10.20.0.0/24 via &lt;IP хоста&gt; -->
&lt;network&gt;
  &lt;name&gt;routed-lab</name>
  &lt;forward mode='route' dev='enp3s0'/&gt;
  &lt;bridge name='virbr-rt' stp='on' delay='0'/&gt;
  &lt;ip address='10.20.0.1' netmask='255.255.255.0'&gt;
    &lt;dhcp&gt;&lt;range start='10.20.0.100' end='10.20.0.199'/&gt;</dhcp>
  </ip>
</network>

<!-- использовать готовый bridge хоста -->
&lt;network&gt;
  &lt;name&gt;host-bridge</name>
  &lt;forward mode='bridge'/&gt;
  &lt;bridge name='br0'/&gt;
</network>

<!-- macvtap поверх физического NIC -->
&lt;network&gt;
  &lt;name&gt;macvtap-lan</name>
  &lt;forward mode='bridge'&gt;
    &lt;interface dev='enp3s0'/&gt;
  </forward>
</network>
```text
```bash
virsh net-define lab-trunk.xml && virsh net-start lab-trunk && virsh net-autostart lab-trunk
virsh net-list --all
virsh net-dumpxml virt-lab
virsh net-edit virt-lab                    # изменения — после net-destroy/net-start
virsh net-dhcp-leases virt-lab             # кто какой IP получил
virsh net-update virt-lab add ip-dhcp-host \
  "&lt;host mac='52:54:00:6b:1a:02' name='vm1' ip='10.10.10.50'/&gt;" --live --config   # резерв IP
ps -ef | grep [d]nsmasq                    # на каждую сеть с &lt;ip&gt; — свой dnsmasq (DHCP + DNS)
sudo nft list ruleset | grep -i libvirt    # NAT и фильтры (libvirt ≥ 10.4 умеет nftables;
sudo iptables -t nat -S | grep -i libvirt  #  в 10.0 на Ubuntu 24.04 — правила iptables)
```text
> 💡 NAT-сеть = маленький домашний роутер: шлюз `10.10.10.1` на хосте, DHCP и DNS от dnsmasq,
> наружу — MASQUERADE (подробно про NAT — [../Network/03_l3_ip_icmp.md](/network/03-l3-ip-icmp),
> раздел 6). Снаружи в VM не попасть без проброса портов — ровно как в облаке без публичного IP.

---

## 3. Linux bridge: VM прямо в LAN

Нужно, чтобы VM получила адрес из сети офиса/ЦОДа и была доступна «как железный сервер».
Физический NIC превращается в порт бриджа, а IP хоста переезжает с NIC **на бридж**.

```text
  БЫЛО                                  СТАЛО
  enp3s0: 192.168.1.20/24               enp3s0: без IP, порт бриджа
                                        br0:    192.168.1.20/24  ← IP хоста здесь
                                          ├── enp3s0 ──► свитч LAN
                                          ├── vnet0 (VM1: 192.168.1.31)
                                          └── vnet1 (VM2: 192.168.1.32)
```text
> ⚠️ В момент переноса IP с `enp3s0` на `br0` SSH-сессия через `enp3s0` оборвётся.
> Делай это с консоли или через `netplan try`. Сначала потренируйся в VM с двумя NIC.

**Временно (до перезагрузки), руками:**
```bash
sudo ip link add br0 type bridge
sudo ip link set br0 type bridge stp_state 0 forward_delay 0
sudo ip link set enp3s0 master br0
sudo ip addr flush dev enp3s0          # ← здесь SSH через enp3s0 рвётся
sudo ip addr add 192.168.1.20/24 dev br0
sudo ip link set br0 up
sudo ip route add default via 192.168.1.1
```text
**Постоянно — netplan (Ubuntu):**
```yaml
# /etc/netplan/60-br0.yaml  (chmod 600; применять: sudo netplan try)
network:
  version: 2
  renderer: networkd
  ethernets:
    enp3s0:
      dhcp4: false
  bridges:
    br0:
      interfaces: [enp3s0]
      macaddress: 52:54:00:aa:bb:cc   # MAC физического enp3s0 — чтобы DHCP-резерв не «уехал»
      addresses: [192.168.1.20/24]
      routes:
        - to: default
          via: 192.168.1.1
      nameservers:
        addresses: [192.168.1.1]
      parameters:
        stp: false
        forward-delay: 0
```text
**Постоянно — NetworkManager (RHEL, Rocky, десктопы):**
```bash
sudo nmcli con add type bridge ifname br0 con-name br0 bridge.stp no \
     ipv4.method manual ipv4.addresses 192.168.1.20/24 ipv4.gateway 192.168.1.1 ipv4.dns 192.168.1.1
sudo nmcli con add type ethernet ifname enp3s0 con-name br0-port master br0
sudo nmcli con down "Wired connection 1"; sudo nmcli con up br0    # ← одной строкой: связь моргнёт
```text
**Подключить VM:** `virt-install ... --network bridge=br0,model=virtio` или через сеть
`host-bridge` из раздела 2 (`--network network=host-bridge`).

> ⚠️ **Docker на том же хосте.** Docker ставит политику `iptables FORWARD DROP` и включает
> `br_netfilter`, из-за чего кадры, идущие *через бридж*, проходят iptables и режутся —
> VM в `br0` «не видят сеть». Проверка: `sysctl net.bridge.bridge-nf-call-iptables` → `1` и
> `sudo iptables -S FORWARD` → `-P FORWARD DROP`. Лечение:
> `sudo iptables -I DOCKER-USER -i br0 -o br0 -j ACCEPT` (и сохранить правило).

> ⚠️ **Wi-Fi.** Через Wi-Fi-клиента бридж не работает: точка доступа не принимает кадры
> с чужими MAC-адресами VM. На ноутбуке по Wi-Fi — только NAT или routed.

---

## 4. macvtap: быстро в LAN, но хост не видит VM

macvtap создаёт у VM «виртуальный NIC-двойник» прямо на физической карте — без бриджа
и без правки сети хоста.

```bash
virt-install ... --network type=direct,source=enp3s0,source.mode=bridge,model=virtio
# или --network network=macvtap-lan
```text
| Режим | Что делает |
|-------|-----------|
| `vepa` | Весь трафик, даже между VM, уходит на внешний свитч (нужен свитч с hairpin/reflective relay) |
| `bridge` | VM на одном NIC видят друг друга напрямую; самый частый |
| `private` | VM не видят друг друга совсем |
| `passthrough` | Отдать NIC (или SR-IOV VF) одной VM целиком |

**Ограничение:** трафик VM уходит прямо в физический порт, минуя сетевой стек хоста.
Хост и VM на одном NIC **друг друга не видят**: ping с хоста на VM и обратно не проходит,
хотя из LAN VM доступна. Обходы — второй NIC хоста, отдельная isolated-сеть libvirt для
связи хост ↔ VM или обычный bridge вместо macvtap.

---

## 5. VLAN на гипервизоре

Что такое VLAN и тег 802.1Q — в [../Network/02_l2_ethernet_arp.md](/network/02-l2-ethernet-arp),
раздел 5. Здесь — как это раскладывается на хосте с VM.

```text
  Порт свитча в режиме ACCESS  — один VLAN, кадры БЕЗ тега (untagged) → обычный сервер/ПК
  Порт свитча в режиме TRUNK   — много VLAN, кадры С тегом (tagged)   → гипервизор
  Native VLAN (на транке)      — VLAN, кадры которого идут без тега   → частый источник путаницы
```text
Гипервизор почти всегда подключён **транком**, а внутри хоста VLAN раскладывают двумя
способами.

### Способ A. Бридж на каждый VLAN (классика)

```text
 bond0 (trunk) ──┬── bond0.10 ── br10 ── VM «управление»
                 ├── bond0.20 ── br20 ── VM прода
                 └── bond0.30 ── br30 ── VM БД
 Хост снимает тег на bond0.N, VM ничего не знают о VLAN (для них это access-порт)
```text
```bash
sudo ip link add link bond0 name bond0.20 type vlan id 20
sudo ip link add br20 type bridge
sudo ip link set bond0.20 master br20
sudo ip link set bond0.20 up && sudo ip link set br20 up
ip -d link show bond0.20 | grep vlan           # vlan protocol 802.1Q id 20
```text
Просто и наглядно, но 50 VLAN = 50 бриджей и 50 интерфейсов.

### Способ B. Один VLAN-aware bridge

Бридж сам понимает теги: у каждого порта свой список VLAN, как у настоящего свитча.
```bash
sudo ip link add br0 type bridge vlan_filtering 1
sudo ip link set bond0 master br0 && sudo ip link set br0 up
sudo bridge vlan add dev bond0 vid 10                  # транк: VLAN 10 и 20 тегированными
sudo bridge vlan add dev bond0 vid 20
sudo bridge vlan add dev vnet3 vid 20 pvid untagged    # порт VM = access в VLAN 20
sudo bridge vlan del dev vnet3 vid 1                   # убрать VLAN 1 по умолчанию
bridge vlan show
# port     vlan-id
# bond0    1 PVID Egress Untagged
#          10
#          20
# vnet3    20 PVID Egress Untagged
```text
IP хоста в VLAN 10 на таком бридже: `bridge vlan add dev br0 vid 10 self` и интерфейс
`ip link add link br0 name br0.10 type vlan id 10`.

**Кто ставит VLAN на порт VM:**
- **Proxmox** — сам: `qm set 101 --net0 virtio,bridge=vmbr0,tag=20` при `bridge-vlan-aware yes` (тема 04).
- **libvirt** — `&lt;vlan&gt;&lt;tag id='20'/&gt;</vlan>` в интерфейсе VM работает на обычных Linux-бриджах
  только с libvirt 11.0 (раньше — лишь с Open vSwitch и SR-IOV). В Ubuntu 24.04 libvirt 10.0,
  поэтому на ней — способ A, `bridge vlan` руками или hook-скрипт `/etc/libvirt/hooks/qemu`.
  Номер `vnetN` меняется при каждом старте VM, ручные `bridge vlan` не переживают перезапуск.

---

## 6. Bonding: два кабеля как один

Bond (в Cisco-мире — port-channel/EtherChannel, в Windows — NIC teaming) объединяет
несколько NIC в один логический интерфейс: **отказоустойчивость** и/или **полоса**.

| Режим | Имя | Как работает | Что нужно от свитча |
|-------|-----|--------------|---------------------|
| 0 | `balance-rr` | Пакеты по очереди во все линки | Статический port-channel; возможен переупорядоченный трафик |
| 1 | ⭐ `active-backup` | Работает один линк, второй ждёт | **Ничего** — самый безопасный |
| 2 | `balance-xor` | Линк по хэшу адресов | Статический port-channel |
| 3 | `broadcast` | Всё во все линки | Спецслучаи |
| 4 | ⭐ `802.3ad` (LACP) | Динамическая агрегация, линк по хэшу | **LACP на порт-группе свитча** (оба порта — в одну группу) |
| 5 | `balance-tlb` | Исходящий трафик балансируется, входящий — на один линк | Ничего |
| 6 | `balance-alb` | tlb + балансировка входящего через подмену ARP | Ничего; плохо дружит с бриджами и VM |

```bash
# active-backup руками (в VM или на стенде!)
sudo ip link add bond0 type bond mode active-backup miimon 100
sudo ip link set trunk0 down && sudo ip link set trunk0 master bond0   # слейв должен быть down
sudo ip link set trunk1 down && sudo ip link set trunk1 master bond0
sudo ip link set bond0 up

cat /proc/net/bonding/bond0
# Bonding Mode: fault-tolerance (active-backup)
# Currently Active Slave: trunk0
# MII Status: up
# MII Polling Interval (ms): 100
# Slave Interface: trunk0
# MII Status: up
# Link Failure Count: 0
# Slave Interface: trunk1
# MII Status: up
# Link Failure Count: 0
```text
Что важно понимать:
- `miimon 100` — проверка линка каждые 100 мс по carrier. Не видит проблему «линк есть,
  а свитч дальше мёртв» — для этого `arp_ip_target` (ARP-мониторинг) или LACP.
- **LACP (802.3ad)** — обе стороны договариваются по протоколу; порт, который перестал
  отвечать LACPDU, выкидывается. Свитч настраивают **до** хоста, иначе хост в изоляции.
- Балансировка идёт **по потокам** (хэш: `layer2`, `layer2+3`, `layer3+4`): один TCP-поток
  никогда не быстрее одного линка. Два линка по 10G ≠ одна копия файла на 20G.
- Два разных свитча под один LACP-бонд работают, только если свитчи в стеке/MLAG.
- **Teaming** (`teamd`) — альтернатива bonding'у: в RHEL 9 объявлен устаревшим, в RHEL 10
  удалён. Используй bonding.

---

## 7. Типовой хост гипервизора: bond + VLAN + bridge

```text
                     свитч A ─┐  стек/MLAG, LACP port-channel, trunk: 10, 20, 30
                     свитч B ─┤
                              │
              eno1 ───────────┤
              eno2 ───────────┘
                │   bond0 (802.3ad, MTU 9000)
      ┌─────────┼──────────────────────────┐
  bond0.10   bond0.20                  bond0.30
  MTU 1500   MTU 1500                  MTU 9000
      │         │                          │
  br-mgmt    br-prod                   10.0.30.11/24  ← хранилище/миграция, без VM
  10.0.10.11    │
  (IP хоста,    ├── vnet0 ── VM app1
   SSH, API)    └── vnet1 ── VM app2
```text
```yaml
# /etc/netplan/60-hypervisor.yaml — ⚠️ только с консолью и через netplan try
network:
  version: 2
  renderer: networkd
  ethernets:
    eno1: {}
    eno2: {}
  bonds:
    bond0:
      interfaces: [eno1, eno2]
      mtu: 9000
      parameters:
        mode: 802.3ad
        lacp-rate: fast
        mii-monitor-interval: 100
        transmit-hash-policy: layer3+4
  vlans:
    bond0.10: { id: 10, link: bond0, mtu: 1500 }
    bond0.20: { id: 20, link: bond0, mtu: 1500 }
    bond0.30:
      id: 30
      link: bond0
      mtu: 9000
      addresses: [10.0.30.11/24]
  bridges:
    br-mgmt:
      interfaces: [bond0.10]
      addresses: [10.0.10.11/24]
      routes:
        - to: default
          via: 10.0.10.1
      nameservers: { addresses: [10.0.10.1] }
      parameters: { stp: false, forward-delay: 0 }
    br-prod:
      interfaces: [bond0.20]
      parameters: { stp: false, forward-delay: 0 }
```text
Зачем так: два кабеля на два свитча — переживаем смерть линка и свитча; управление, VM
и хранилище в разных VLAN — трафик бэкапа не душит SSH, а VM прода не видят сеть хранения;
хост без IP в VLAN прода — VM не могут «постучаться» в гипервизор. Та же схема в Proxmox —
в `/etc/network/interfaces` (тема 04).

---

## 8. MTU и jumbo frames

Сеть хранения (NFS, iSCSI, Ceph) и живой миграции часто переводят на **MTU 9000**: меньше
пакетов на гигабайт — меньше нагрузка на CPU. Что такое MTU и почему «большие пакеты
пропадают» — [../Network/03_l3_ip_icmp.md](/network/03-l3-ip-icmp), раздел 5.

Правило: **MTU одинаковый на всём L2-пути** — порты свитча (часто 9216), bond, VLAN,
bridge, tap, интерфейс VM. Один порт с 1500 в цепочке — и большие кадры тихо теряются.
Тег 802.1Q добавляет 4 байта в кадр, но это забота свитча, а не MTU интерфейса. Оверлеи
(VXLAN, Proxmox SDN) съедают ~50 байт: внутри получится 1450 при 1500 снаружи.

```bash
ip link show bond0.30 | grep -o 'mtu [0-9]*'
ping -M do -s 8972 -c 3 10.0.30.12     # 9000 − 20 (IP) − 8 (ICMP) = 8972; должно проходить
ping -M do -s 8973 -c 1 10.0.30.12     # на 1 байт больше — «message too long» локально
```text
---

## 9. Разбор «VM не видит сеть» по слоям

```text
 1. Линк       ethtool eno1 | grep -E 'Speed|Link detected'; ip -s link show eno1 (ошибки/дропы)
 2. Bond       cat /proc/net/bonding/bond0 — активный слейв, MII Status, LACP partner
 3. VLAN       ip -d link show bond0.20 — тот ли id; совпадает ли с транком на свитче
 4. Bridge     ip -br link show master br-prod — воткнуты ли bond0.20 и vnetX
               bridge fdb show br br-prod | grep -v permanent — выучен ли MAC VM и за каким портом
               bridge vlan show — у VLAN-aware: есть ли нужный vid на порту VM и аплинке
 5. Порт VM    virsh domiflist vm; virsh domif-getlink vm vnetX — «кабель» up?
 6. Кадры      sudo tcpdump -eni vnetX — уходят ли ARP/DHCP от VM; -e показывает MAC и теги
               sudo tcpdump -eni bond0 vlan 20 — выходят ли они на транк с тегом 20
 7. Фильтры    sysctl net.bridge.bridge-nf-call-iptables; sudo iptables -S FORWARD (Docker!)
 8. Гость      ip a, ip r, ping шлюза, arp/ip neigh (дальше — как с любым Linux-хостом)
```text
Главный инструмент — `tcpdump -e` на vnet-интерфейсе: видно, отправляет ли VM вообще
что-то, дошёл ли ответ до бриджа, и с каким VLAN-тегом кадр ушёл в физику.

---

## 10. Грабли

| Симптом | Причина | Что делать |
|---------|---------|-----------|
| После `netplan apply` хост пропал | IP переехал на бридж/бонд с ошибкой | Только консоль + `netplan try`; бэкап `/etc/netplan` |
| VM в `br0` не получают DHCP/не пингуются | Docker: `FORWARD DROP` + `br_netfilter` | Правило в `DOCKER-USER` для `br0` |
| После перевода на бридж у хоста новый IP | Бридж получил другой MAC — DHCP видит «новое устройство» | `macaddress:` у бриджа = MAC физического NIC |
| Хост не пингует VM на macvtap | Так устроен macvtap | Bridge, второй NIC или isolated-сеть для хоста |
| Бридж через Wi-Fi не работает | Точка доступа отбрасывает чужие MAC | NAT или routed |
| VM в VLAN не видит соседей | Тег не совпадает с транком свитча, native VLAN путают | `tcpdump -e`, сверить с сетевиками список VLAN на порту |
| LACP-бонд поднят, трафика нет | На свитче порты не в LACP port-channel | Сначала свитч, потом хост; `/proc/net/bonding/bond0` — partner MAC |
| «Бонд 2×10G, а копия идёт на 10G» | Один поток хэшируется в один линк | Это норма; несколько потоков → оба линка |
| Большие пакеты теряются, SSH работает | MTU 9000 не на всём пути | `ping -M do -s 8972`, выровнять MTU |
| `bridge vlan` для VM пропал после рестарта | vnetN создаётся заново при старте VM | Proxmox, libvirt ≥ 11 `&lt;vlan&gt;`, hook или способ A |
| `balance-alb` + бридж: VM теряют связь | alb подменяет MAC в ARP-ответах | Для хостов с VM — `active-backup` или LACP |

---

## 💼 Как это в DevOps

- **Разговор с сетевиками** — это «прошу транк на порты `Gi1/0/1-2` с VLAN 10, 20, 30,
  native — никакой, LACP port-channel, MTU 9216». Без понимания trunk/access/LACP такую
  заявку не написать и ответ не проверить.
- **Хост гипервизора = bond + VLAN + bridge** почти везде: Proxmox, голый KVM, OpenStack
  compute-ноды. В VMware то же самое называется vSwitch/vDS + port groups с VLAN ID.
- **Сегментация** — базовое требование ИБ банков и госсектора: прод, тест, управление
  и хранилище в разных VLAN, между ними — файрвол.
- **Облачные аналоги:** VLAN ≈ подсеть/VPC, NAT-сеть libvirt ≈ приватная подсеть с NAT
  gateway, bridge ≈ публичный IP.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Сети libvirt / аренды | `virsh net-list --all`, `virsh net-dhcp-leases &lt;сеть&gt;` |
| Создать сеть из XML | `virsh net-define f.xml && virsh net-start N && virsh net-autostart N` |
| Резерв IP в DHCP libvirt | `virsh net-update N add ip-dhcp-host "&lt;host mac=.. ip=../&gt;" --live --config` |
| Порты VM | `virsh domiflist vm`, `virsh domif-setlink vm vnetX down/up` |
| Бридж руками | `ip link add br0 type bridge; ip link set eth1 master br0` |
| VM в бридж | `--network bridge=br0,model=virtio` |
| VM на macvtap | `--network type=direct,source=enp3s0,source.mode=bridge` |
| VLAN-интерфейс | `ip link add link bond0 name bond0.20 type vlan id 20` |
| VLAN-aware bridge | `ip link add br0 type bridge vlan_filtering 1`; `bridge vlan add dev vnet3 vid 20 pvid untagged` |
| Бонд | `ip link add bond0 type bond mode active-backup miimon 100` |
| Состояние бонда | `cat /proc/net/bonding/bond0` |
| MAC-таблица бриджа | `bridge fdb show br br0` |
| VLAN на портах | `bridge vlan show` |
| Трафик VM с MAC и тегами | `sudo tcpdump -eni vnetX` |
| Проверить jumbo | `ping -M do -s 8972 &lt;IP&gt;` |
| Docker режет бридж? | `sysctl net.bridge.bridge-nf-call-iptables`, `iptables -S FORWARD` |

---

## 🧠 Что запомнить

1. NIC VM на хосте — tap `vnetN`, воткнутый в бридж; бридж — программный свитч.
2. NAT — для стенда, bridge — чтобы VM жили в LAN, isolated — внутренние сети, routed — без NAT, если роутер знает маршрут.
3. При переводе на бридж IP переезжает с NIC на бридж — это рвёт SSH: консоль и `netplan try`.
4. macvtap прост, но хост и VM на одном NIC не видят друг друга; через Wi-Fi не работают ни бридж, ни macvtap.
5. Гипервизор подключают транком; VLAN раскладывают бриджем на каждый VLAN или одним VLAN-aware бриджем.
6. active-backup не требует ничего от свитча; LACP (802.3ad) требует port-channel на свитче.
7. Бонд балансирует по потокам: один поток не быстрее одного линка.
8. Типовой хост: bond → VLAN (управление, VM, хранилище) → bridge; у хоста нет IP в сетях VM.
9. Jumbo frames работают, только если MTU 9000 на всём L2-пути; проверка — `ping -M do -s 8972`.
10. Разбор идёт по слоям: линк → bond → VLAN → bridge/fdb → порт VM → tcpdump → фильтры → гость.

➡️ Дальше: [04_proxmox.md](/virtualization/04-proxmox) · задачи: 03_virt_networking_tasks.md


---

### Блок A. Теория


**A1.** Что такое `vnetN` на хосте и как он связан с бриджем и процессом QEMU?

<details><summary>Ответ</summary>

`vnetN` — tap-устройство: «кабель» между процессом QEMU (он читает и пишет кадры VM)
и сетевым стеком хоста. Этот конец воткнут в бридж, как патч-корд в порт свитча.

</details>

**A2.** ⭐ Сравни режимы сетей libvirt: NAT, routed, isolated, bridge, macvtap — кто кого видит
и кто раздаёт адреса.

<details><summary>Ответ</summary>

NAT: VM выходит наружу через MASQUERADE, хост видит VM, LAN — нет; адреса от dnsmasq.
Routed: без NAT, LAN видит VM, если роутер знает маршрут в подсеть VM; адреса от dnsmasq.
Isolated: только VM между собой (и хост, если у сети есть `&lt;ip&gt;`). Bridge: VM — полноправные
узлы LAN, адреса от DHCP LAN или статика. macvtap: как bridge для LAN, но хост и VM на одном
NIC не видят друг друга.

</details>

**A3.** Почему из LAN нельзя зайти в VM из NAT-сети? Что нужно, чтобы работал routed-режим?

<details><summary>Ответ</summary>

VM за NAT имеют приватные адреса, известные только хосту; снаружи в них можно попасть
лишь пробросом портов. Для routed на роутере LAN нужен маршрут «подсеть VM via IP хоста»,
иначе ответы из интернета/LAN не найдут дорогу назад.

</details>

**A4.** Что происходит с IP хоста, когда физический NIC становится портом бриджа? Почему
в этот момент рвётся SSH?

<details><summary>Ответ</summary>

Порт бриджа работает на L2 и адреса не держит — IP переезжает на сам бридж. Пока IP
снят с NIC и не поднят на бридже (или меняется MAC/маршрут по умолчанию), TCP-сессия через
этот интерфейс рвётся.

</details>

**A5.** Почему нельзя сделать бридж для VM поверх Wi-Fi?

<details><summary>Ответ</summary>

Wi-Fi-клиент подключён к точке доступа от своего MAC; кадры с чужими MAC (VM) точка
доступа отбрасывает (без режима 4addr/WDS). Поэтому ядро и не даёт добавить Wi-Fi в бридж.

</details>

**A6.** Какие режимы есть у macvtap? В чём его главное ограничение и как его обойти?

<details><summary>Ответ</summary>

`vepa`, `bridge`, `private`, `passthrough`. Ограничение: трафик VM уходит прямо в
физический порт мимо стека хоста — хост и VM на одном NIC не видят друг друга. Обход: второй NIC,
отдельная isolated-сеть для связи хоста с VM или обычный бридж.

</details>

**A7.** Чем access-порт отличается от trunk-порта? Что такое native VLAN?

<details><summary>Ответ</summary>

Access — один VLAN, кадры без тега (для обычных серверов). Trunk — несколько VLAN,
кадры с тегом 802.1Q (для гипервизоров и свитчей). Native VLAN — VLAN транка, чьи кадры
идут без тега; несогласованный native VLAN на двух концах — источник «утечек» между VLAN.

</details>

**A8.** ⭐ Два способа разложить VLAN на гипервизоре. Плюсы и минусы каждого.

<details><summary>Ответ</summary>

A) Бридж на каждый VLAN (`bond0.20` → `br20`): просто, VM ничего не знают о тегах,
но много интерфейсов при десятках VLAN. B) Один VLAN-aware бридж (`vlan_filtering 1`):
один бридж, VLAN задаются на портах; компактно и гибко, но нужно, чтобы кто-то ставил VLAN
на порт VM (Proxmox делает сам, в libvirt — с 11.0 или hook).

</details>

**A9.** ⭐ Какие режимы bonding не требуют настройки свитча? Что нужно от свитча для 802.3ad?

<details><summary>Ответ</summary>

Без свитча: `active-backup`, `balance-tlb`, `balance-alb`. Для 802.3ad на свитче
нужна LACP port-channel группа из этих же портов (на одном свитче или на стеке/MLAG).
`balance-rr` и `balance-xor` требуют статический port-channel.

</details>

**A10.** Почему у бонда 2×10G одна копия файла идёт на 10G? Что такое `transmit-hash-policy`?

<details><summary>Ответ</summary>

Бонд выбирает линк для кадра по хэшу полей (`layer2` — MAC, `layer2+3` — MAC+IP,
`layer3+4` — IP+порты). Все пакеты одного потока попадают в один линк, чтобы не было
переупорядочивания. Больше потоков — лучше распределение.

</details>

**A11.** Чем MII-мониторинг отличается от ARP-мониторинга в бонде? Чего не видит `miimon`?

<details><summary>Ответ</summary>

MII проверяет carrier (есть ли «свет» на порту). ARP-мониторинг шлёт ARP на
заданные адреса и проверяет ответы. `miimon` не видит отказ дальше порта: линк до свитча
жив, а свитч или его аплинк мёртвы.

</details>

**A12.** Нарисуй типовую сеть хоста гипервизора. Зачем управление, VM и хранилище в разных VLAN?

<details><summary>Ответ</summary>

Бонд из двух NIC на два свитча → VLAN-интерфейсы (управление, VM, хранилище/миграция)
→ бриджи для VLAN с VM; у хоста IP только в управлении и хранилище. Разделение: трафик бэкапа
и миграции не душит управление, VM не видят сеть хранения и сам гипервизор, требования ИБ
к сегментации выполнены.

</details>

**A13.** Где используют MTU 9000 и что обязательно для его работы? Как проверить?

<details><summary>Ответ</summary>

В сетях хранения (NFS, iSCSI, Ceph) и живой миграции — меньше пакетов, меньше
нагрузка на CPU. Обязательно одинаковый MTU на всём L2-пути: порты свитча, bond, VLAN,
бридж, tap, интерфейс VM. Проверка: `ping -M do -s 8972 &lt;IP&gt;`.

</details>

**A14.** Как Docker на гипервизоре ломает сеть VM в бридже?

<details><summary>Ответ</summary>

Docker ставит политику `FORWARD DROP` в iptables и загружает `br_netfilter` с
`bridge-nf-call-iptables=1` — кадры, идущие через бриджи, проходят цепочку FORWARD и
отбрасываются. Лечение — правило `ACCEPT` в `DOCKER-USER` для бриджа VM.

</details>

**A15.** Чем помогает `tcpdump -e` при разборе сети VM?

<details><summary>Ответ</summary>

`-e` печатает MAC-адреса и VLAN-теги. На `vnetN` видно, шлёт ли VM ARP/DHCP вообще
и приходят ли ответы; на транке — уходит ли кадр с правильным тегом. Сразу понятно, на каком
слое пропадает трафик.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  # по SSH на удалённый сервер через enp3s0
```text
<details><summary>Ответ</summary>

⚠️ IP переедет на `br0`, SSH через `enp3s0` оборвётся; ошибка в YAML — и доступа нет
совсем. Только с консолью/IPMI и через `netplan try` (автооткат через 120 с).

</details>

```text:no-line-numbers
     $ sudo vim /etc/netplan/60-br0.yaml     # enp3s0 → порт br0, IP на br0
```text
```text:no-line-numbers
     $ sudo netplan apply
```text
```text:no-line-numbers
B2.  # хост: bond0 mode 802.3ad (eno1 + eno2)
```text
<details><summary>Ответ</summary>

⚠️ Хост шлёт LACPDU, свитч их не понимает — слейвы не агрегируются, трафик теряется
или идёт по одному линку с петлями MAC. Сначала на свитче LACP port-channel с транком, потом хост.

</details>

```text:no-line-numbers
     # свитч: оба порта — обычные access в VLAN 10, без port-channel
```text
```text:no-line-numbers
B3.  $ bridge vlan show
```text
<details><summary>Ответ</summary>

⚠️ На аплинке `bond0` нет VLAN 20 — кадры VM из VLAN 20 не выходят за пределы бриджа.
`bridge vlan add dev bond0 vid 20` (и VLAN 20 на транке свитча).

</details>

```text:no-line-numbers
     port      vlan-id
```text
```text:no-line-numbers
     bond0     1 PVID Egress Untagged
```text
```text:no-line-numbers
               10
```text
```text:no-line-numbers
     vnet3     20 PVID Egress Untagged
```text
```text:no-line-numbers
     # VM на vnet3 «не видит сеть»
```text
```text:no-line-numbers
B4.  # VM подключена macvtap к enp3s0, из офиса по SSH заходится
```text
<details><summary>Ответ</summary>

✅ Сеть VM в порядке: это ограничение macvtap — хост не видит свою VM на том же NIC.
Проверять с другого узла LAN.

</details>

```text:no-line-numbers
     $ ping 192.168.1.31      # с самого хоста
```text
```text:no-line-numbers
     # 100% packet loss → «у VM сломана сеть»
```text
```text:no-line-numbers
B5.  # гипервизор: bond0 mode balance-alb, поверх — бридж br0 с десятью VM
```text
<details><summary>Ответ</summary>

⚠️ `balance-alb` подменяет MAC в ARP-ответах для балансировки входящего трафика и плохо
работает с бриджами и VM — теряется связность. Для гипервизора — `active-backup` или LACP.

</details>

```text:no-line-numbers
B6.  # в госте: ip link set enp1s0 mtu 9000
```text
<details><summary>Ответ</summary>

⚠️ MTU 9000 только в госте: большие кадры отбрасываются на бридже/свитче, мелкие
(SSH, handshake) проходят. Выровнять MTU на всём пути или вернуть 1500 в госте.

</details>

```text:no-line-numbers
     # бридж на хосте и порты свитча — 1500
```text
```text:no-line-numbers
     $ scp big.iso storage:/data/    # висит; ssh работает
```text
```text:no-line-numbers
B7.  # ноутбук, интернет по Wi-Fi
```text
<details><summary>Ответ</summary>

⚠️ Wi-Fi в режиме клиента нельзя добавить в бридж. Для VM на ноутбуке с Wi-Fi —
NAT или routed.

</details>

```text:no-line-numbers
     $ sudo ip link set wlp2s0 master br0
```text
```text:no-line-numbers
     Error: Device does not allow enslaving to a bridge.
```text
```text:no-line-numbers
B8.  # хост Ubuntu 24.04 (libvirt 10.0), обычный Linux-бридж br0 без Open vSwitch
```text
<details><summary>Ответ</summary>

⚠️ На libvirt 10.0 VLAN-тег на интерфейсе поддерживается только для Open vSwitch и
SR-IOV — конфигурацию отклонят как неподдерживаемую. Нужен libvirt ≥ 11.0, способ A
(бридж на VLAN) или OVS.

</details>

```text:no-line-numbers
     # в XML интерфейса VM добавили: &lt;vlan&gt;&lt;tag id='20'/&gt;</vlan>
```text
```text:no-line-numbers
B9.  # бонд 802.3ad: eno1 → свитч A, eno2 → свитч B
```text
<details><summary>Ответ</summary>

⚠️ LACP между двумя независимыми свитчами не соберётся: у них разные system ID.
Нужен стек/MLAG, либо active-backup (он с независимыми свитчами работает).

</details>

```text:no-line-numbers
     # свитчи независимые: не стек и не MLAG
```text
```text:no-line-numbers
B10.  # сеть libvirt routed-lab (10.20.0.0/24), на роутере офиса ничего не меняли
```text
<details><summary>Ответ</summary>

⚠️ Routed без NAT: пакеты уходят с адресом 10.20.0.x, а роутер не знает, куда
возвращать ответы. Добавить на роутере маршрут `10.20.0.0/24 via &lt;IP хоста&gt;` (и NAT на
выходе в интернет на самом роутере) или использовать NAT-сеть.

</details>

```text:no-line-numbers
     # из VM: ping 1.1.1.1 — тишина
```text
```text:no-line-numbers
B11.  # netplan: br0 с dhcp4: true поверх enp3s0, без macaddress
```text
<details><summary>Ответ</summary>

⚠️ Бридж получил свой MAC, DHCP видит новое устройство. Указать `macaddress:` бриджа
равным MAC физического NIC или перенести резерв на новый MAC.

</details>

```text:no-line-numbers
     # после перезагрузки у сервера другой IP, DHCP-резерв «не сработал»
```text
```text:no-line-numbers
B12.  # схема хоста: bond0 → bond0.20 → br-prod, и у хоста IP 10.0.20.5 на br-prod
```text
<details><summary>Ответ</summary>

⚠️ Хост становится доступен из сети VM: скомпрометированная VM атакует гипервизор
напрямую. У хоста не должно быть IP в VLAN с VM — только в управлении.

</details>

```text:no-line-numbers
     # «чтобы было удобно ходить на хост из сети прода»
```text
---

### Блок C. Практика


### C1. 🔑 Сети libvirt
**1.** Создай `lab-trunk` (isolated, без `&lt;ip&gt;`) и `lab-iso` (isolated, с `&lt;ip&gt;` 10.30.0.1/24 и DHCP).

<details><summary>Ответ</summary>

У `lab-trunk` dnsmasq нет — нет `&lt;ip&gt;`, раздавать нечего и хост в сети без адреса;
у `lab-iso` есть. Резерв: `virsh net-update virt-lab add ip-dhcp-host "&lt;host mac='...' name='vm1' ip='10.10.10.50'/&gt;" --live --config`,
затем VM перезапустить (или обновить аренду в госте). NAT: `sudo nft list ruleset | grep -A3 10.10.10`
или `sudo iptables -t nat -S | grep 10.10.10` — правило MASQUERADE для 10.10.10.0/24.

</details>

**2.** Сравни `virsh net-dumpxml` и процессы dnsmasq: у какой сети он есть и почему?

<details><summary>Ответ</summary>

```bash
sudo ip link add br0 type bridge && sudo ip link set trunk0 master br0
sudo ip link set trunk0 up && sudo ip link set br0 up && sudo ip addr add 10.40.0.1/24 dev br0
sudo ip netns add vmA
sudo ip link add veth-a type veth peer name veth-a-br
sudo ip link set veth-a netns vmA && sudo ip link set veth-a-br master br0 && sudo ip link set veth-a-br up
sudo ip -n vmA addr add 10.40.0.11/24 dev veth-a && sudo ip -n vmA link set veth-a up
```text
В `bridge fdb` MAC `hv2` выучен за `trunk0`, MAC namespace — за `veth-a-br`: бридж ведёт
себя как свитч.

</details>

**3.** Зарезервируй `vm1` адрес `10.10.10.50` в `virt-lab`, перезапусти VM и проверь.

<details><summary>Ответ</summary>

Обычно теряется 0–несколько пакетов при `ping -i 0.2`: `miimon 100` замечает падение
за ~100 мс, бонд переключается и шлёт gratuitous ARP. В `/proc/net/bonding/bond0` меняется
`Currently Active Slave`, у упавшего слейва `MII Status: down` и растёт `Link Failure Count`.
Без `primary` бонд после возврата линка остаётся на текущем слейве; с `primary trunk0` и
`primary_reselect always` (по умолчанию) — вернётся на primary.

</details>

**4.** Найди правила NAT сети `virt-lab` в iptables или nftables.

<details><summary>Ответ</summary>

```bash
sudo ip link add link bond0 name bond0.10 type vlan id 10
sudo ip link add br10 type bridge && sudo ip link set bond0.10 master br10
sudo ip link set bond0.10 up && sudo ip link set br10 up && sudo ip addr add 10.0.10.1/24 dev br10
# то же для 20
```text
Адрес из 10.0.10.0/24 на `br20` — пакеты уходят с тегом 20, а `hv2` слушает 10.0.10.2 только
в VLAN 10: ARP не получает ответа — изоляция на L2. В tcpdump на хосте:
`ethertype 802.1Q (0x8100), length ...: vlan 10, p 0, ethertype IPv4 ...`. Бридж `lab-trunk`
на хосте теги не снимает — он не VLAN-aware и пропускает кадры как есть.

</details>

### C2. 🔑 Бридж внутри VM и «VM» из network namespace
Внутри `hv1` (сеть хоста не трогаем):
**1.** Создай `br0` поверх `trunk0` с адресом `10.40.0.1/24`.

<details><summary>Ответ</summary>

У `lab-trunk` dnsmasq нет — нет `&lt;ip&gt;`, раздавать нечего и хост в сети без адреса;
у `lab-iso` есть. Резерв: `virsh net-update virt-lab add ip-dhcp-host "&lt;host mac='...' name='vm1' ip='10.10.10.50'/&gt;" --live --config`,
затем VM перезапустить (или обновить аренду в госте). NAT: `sudo nft list ruleset | grep -A3 10.10.10`
или `sudo iptables -t nat -S | grep 10.10.10` — правило MASQUERADE для 10.10.10.0/24.

</details>

**2.** Сделай «виртуалку» из namespace: `ip netns add vmA`, veth-пара, один конец в `vmA`
   с адресом `10.40.0.11/24`, второй — в `br0`.

<details><summary>Ответ</summary>

```bash
sudo ip link add br0 type bridge && sudo ip link set trunk0 master br0
sudo ip link set trunk0 up && sudo ip link set br0 up && sudo ip addr add 10.40.0.1/24 dev br0
sudo ip netns add vmA
sudo ip link add veth-a type veth peer name veth-a-br
sudo ip link set veth-a netns vmA && sudo ip link set veth-a-br master br0 && sudo ip link set veth-a-br up
sudo ip -n vmA addr add 10.40.0.11/24 dev veth-a && sudo ip -n vmA link set veth-a up
```text
В `bridge fdb` MAC `hv2` выучен за `trunk0`, MAC namespace — за `veth-a-br`: бридж ведёт
себя как свитч.

</details>

**3.** С `hv2` (адрес `10.40.0.2/24` на `trunk0`) пропингуй `10.40.0.11`. Посмотри `bridge fdb show br br0`
   в `hv1` — за какими портами выучены MAC?

<details><summary>Ответ</summary>

Обычно теряется 0–несколько пакетов при `ping -i 0.2`: `miimon 100` замечает падение
за ~100 мс, бонд переключается и шлёт gratuitous ARP. В `/proc/net/bonding/bond0` меняется
`Currently Active Slave`, у упавшего слейва `MII Status: down` и растёт `Link Failure Count`.
Без `primary` бонд после возврата линка остаётся на текущем слейве; с `primary trunk0` и
`primary_reselect always` (по умолчанию) — вернётся на primary.

</details>

### C3. 🔑 active-backup и failover
**1.** В `hv1` и `hv2` собери `bond0` (active-backup, `miimon 100`) из `trunk0` + `trunk1`, адреса
   `10.50.0.1/24` и `10.50.0.2/24`.

<details><summary>Ответ</summary>

У `lab-trunk` dnsmasq нет — нет `&lt;ip&gt;`, раздавать нечего и хост в сети без адреса;
у `lab-iso` есть. Резерв: `virsh net-update virt-lab add ip-dhcp-host "&lt;host mac='...' name='vm1' ip='10.10.10.50'/&gt;" --live --config`,
затем VM перезапустить (или обновить аренду в госте). NAT: `sudo nft list ruleset | grep -A3 10.10.10`
или `sudo iptables -t nat -S | grep 10.10.10` — правило MASQUERADE для 10.10.10.0/24.

</details>

**2.** Запусти `ping -i 0.2 10.50.0.2` и на хосте выдерни «кабель» активного слейва:
   `virsh domif-setlink hv1 &lt;vnet активного&gt; down`.

<details><summary>Ответ</summary>

```bash
sudo ip link add br0 type bridge && sudo ip link set trunk0 master br0
sudo ip link set trunk0 up && sudo ip link set br0 up && sudo ip addr add 10.40.0.1/24 dev br0
sudo ip netns add vmA
sudo ip link add veth-a type veth peer name veth-a-br
sudo ip link set veth-a netns vmA && sudo ip link set veth-a-br master br0 && sudo ip link set veth-a-br up
sudo ip -n vmA addr add 10.40.0.11/24 dev veth-a && sudo ip -n vmA link set veth-a up
```text
В `bridge fdb` MAC `hv2` выучен за `trunk0`, MAC namespace — за `veth-a-br`: бридж ведёт
себя как свитч.

</details>

**3.** Сколько пакетов потерялось? Что показывает `/proc/net/bonding/bond0`?

<details><summary>Ответ</summary>

Обычно теряется 0–несколько пакетов при `ping -i 0.2`: `miimon 100` замечает падение
за ~100 мс, бонд переключается и шлёт gratuitous ARP. В `/proc/net/bonding/bond0` меняется
`Currently Active Slave`, у упавшего слейва `MII Status: down` и растёт `Link Failure Count`.
Без `primary` бонд после возврата линка остаётся на текущем слейве; с `primary trunk0` и
`primary_reselect always` (по умолчанию) — вернётся на primary.

</details>

**4.** Верни линк. Переключился ли бонд обратно? От чего это зависит?

<details><summary>Ответ</summary>

```bash
sudo ip link add link bond0 name bond0.10 type vlan id 10
sudo ip link add br10 type bridge && sudo ip link set bond0.10 master br10
sudo ip link set bond0.10 up && sudo ip link set br10 up && sudo ip addr add 10.0.10.1/24 dev br10
# то же для 20
```text
Адрес из 10.0.10.0/24 на `br20` — пакеты уходят с тегом 20, а `hv2` слушает 10.0.10.2 только
в VLAN 10: ARP не получает ответа — изоляция на L2. В tcpdump на хосте:
`ethertype 802.1Q (0x8100), length ...: vlan 10, p 0, ethertype IPv4 ...`. Бридж `lab-trunk`
на хосте теги не снимает — он не VLAN-aware и пропускает кадры как есть.

</details>

### C4. 🔑 VLAN поверх бонда: изоляция
**1.** Поверх `bond0` в обеих VM: `bond0.10` → `br10` (`10.0.10.1` / `.2`) и `bond0.20` → `br20`
   (`10.0.20.1` / `.2`).

<details><summary>Ответ</summary>

У `lab-trunk` dnsmasq нет — нет `&lt;ip&gt;`, раздавать нечего и хост в сети без адреса;
у `lab-iso` есть. Резерв: `virsh net-update virt-lab add ip-dhcp-host "&lt;host mac='...' name='vm1' ip='10.10.10.50'/&gt;" --live --config`,
затем VM перезапустить (или обновить аренду в госте). NAT: `sudo nft list ruleset | grep -A3 10.10.10`
или `sudo iptables -t nat -S | grep 10.10.10` — правило MASQUERADE для 10.10.10.0/24.

</details>

**2.** Докажи: `10.0.10.1 → 10.0.10.2` работает, из VLAN 20 в VLAN 10 — нет (добавь в `hv1`
   на `br20` адрес `10.0.10.99/24` и попробуй пропинговать `10.0.10.2`).

<details><summary>Ответ</summary>

```bash
sudo ip link add br0 type bridge && sudo ip link set trunk0 master br0
sudo ip link set trunk0 up && sudo ip link set br0 up && sudo ip addr add 10.40.0.1/24 dev br0
sudo ip netns add vmA
sudo ip link add veth-a type veth peer name veth-a-br
sudo ip link set veth-a netns vmA && sudo ip link set veth-a-br master br0 && sudo ip link set veth-a-br up
sudo ip -n vmA addr add 10.40.0.11/24 dev veth-a && sudo ip -n vmA link set veth-a up
```text
В `bridge fdb` MAC `hv2` выучен за `trunk0`, MAC namespace — за `veth-a-br`: бридж ведёт
себя как свитч.

</details>

**3.** На хосте: `sudo tcpdump -eni &lt;vnet trunk hv1&gt; vlan` — найди теги `vlan 10` и `vlan 20`.

<details><summary>Ответ</summary>

Обычно теряется 0–несколько пакетов при `ping -i 0.2`: `miimon 100` замечает падение
за ~100 мс, бонд переключается и шлёт gratuitous ARP. В `/proc/net/bonding/bond0` меняется
`Currently Active Slave`, у упавшего слейва `MII Status: down` и растёт `Link Failure Count`.
Без `primary` бонд после возврата линка остаётся на текущем слейве; с `primary trunk0` и
`primary_reselect always` (по умолчанию) — вернётся на primary.

</details>

### C5. VLAN-aware bridge
В `hv1` вместо `br10/br20` собери один `br0 vlan_filtering 1` поверх `bond0`: два namespace-«VM»
в VLAN 10 и 20 через `bridge vlan ... pvid untagged`, аплинк `bond0` — с тегами 10 и 20.
Проверь связность с `hv2` и вывод `bridge vlan show`.

### C6. Постоянная конфигурация
Перенеси схему из C3–C4 в netplan в `hv1` (файл в `/etc/netplan/`), примени через `netplan try`,
перезагрузи VM и проверь, что всё поднялось само.

### C7. Jumbo frames
**1.** Выключи обе VM, добавь в сеть `lab-trunk` `&lt;mtu size='9000'/&gt;` (`virsh net-edit`,
   затем `net-destroy`/`net-start`).

<details><summary>Ответ</summary>

У `lab-trunk` dnsmasq нет — нет `&lt;ip&gt;`, раздавать нечего и хост в сети без адреса;
у `lab-iso` есть. Резерв: `virsh net-update virt-lab add ip-dhcp-host "&lt;host mac='...' name='vm1' ip='10.10.10.50'/&gt;" --live --config`,
затем VM перезапустить (или обновить аренду в госте). NAT: `sudo nft list ruleset | grep -A3 10.10.10`
или `sudo iptables -t nat -S | grep 10.10.10` — правило MASQUERADE для 10.10.10.0/24.

</details>

**2.** Подними MTU 9000 на `trunk0/trunk1/bond0/bond0.10/br10` в обеих VM.

<details><summary>Ответ</summary>

```bash
sudo ip link add br0 type bridge && sudo ip link set trunk0 master br0
sudo ip link set trunk0 up && sudo ip link set br0 up && sudo ip addr add 10.40.0.1/24 dev br0
sudo ip netns add vmA
sudo ip link add veth-a type veth peer name veth-a-br
sudo ip link set veth-a netns vmA && sudo ip link set veth-a-br master br0 && sudo ip link set veth-a-br up
sudo ip -n vmA addr add 10.40.0.11/24 dev veth-a && sudo ip -n vmA link set veth-a up
```text
В `bridge fdb` MAC `hv2` выучен за `trunk0`, MAC namespace — за `veth-a-br`: бридж ведёт
себя как свитч.

</details>

**3.** `ping -M do -s 8972 10.0.10.2` — проходит? Верни 1500 на одном звене и повтори.

<details><summary>Ответ</summary>

Обычно теряется 0–несколько пакетов при `ping -i 0.2`: `miimon 100` замечает падение
за ~100 мс, бонд переключается и шлёт gratuitous ARP. В `/proc/net/bonding/bond0` меняется
`Currently Active Slave`, у упавшего слейва `MII Status: down` и растёт `Link Failure Count`.
Без `primary` бонд после возврата линка остаётся на текущем слейве; с `primary trunk0` и
`primary_reselect always` (по умолчанию) — вернётся на primary.

</details>

### C8. macvtap (только если у хоста есть проводной Ethernet)
Подними VM с `--network type=direct,source=&lt;проводной NIC&gt;,source.mode=bridge`. Проверь
доступ к ней с другого устройства в LAN и с самого хоста. Объясни результат.

---

### Блок D. Инциденты


**D1.** Сетевики добавили VLAN 30, на хосте сделали `bond0.30` → `br30`. VM в `br30` не видят шлюз.
`tcpdump -eni bond0 vlan 30` показывает исходящие ARP-запросы с тегом 30, ответов нет. Где проблема?

<details><summary>Ответ</summary>

VLAN 30 не добавлен в разрешённые на транке свитча (или на порт-группе LACP только
на одном порту). Кадры уходят с тегом, свитч их отбрасывает. Попросить сетевиков добавить
VLAN 30 на транк обоих портов и показать `show interfaces trunk`.

</details>

**D2.** Бонд active-backup, eno1 — primary. Свитч перезагрузили: сначала всё переключилось на eno2
без потерь, а после загрузки свитча VM на 30 секунд пропали из сети. Почему?

<details><summary>Ответ</summary>

После загрузки свитча линк eno1 поднялся раньше, чем порт начал передавать (STP
listening/learning ~30 с), и бонд сразу вернулся на primary — в «чёрную дыру». Лечение:
`updelay` (например 30000 мс) в бонде, `primary_reselect failure` (или better), на свитче —
portfast/edge для портов хостов; либо LACP, где порт включается только после согласования.

</details>

**D3.** На гипервизор поставили Docker для «пары утилит» — все VM в `br0` потеряли сеть,
у хоста сеть работает.

<details><summary>Ответ</summary>

Docker поставил `FORWARD DROP` и `br_netfilter`, трафик VM через бридж режется.
Проверка: `sysctl net.bridge.bridge-nf-call-iptables`, `sudo iptables -S FORWARD`. Лечение —
`iptables -I DOCKER-USER -i br0 -o br0 -j ACCEPT` с сохранением; лучше не ставить Docker на
гипервизор, а запускать его в VM.

</details>

**D4.** LACP-бонд периодически «моргает». В `/proc/net/bonding/bond0` у слейвов
`Partner Mac Address: 00:00:00:00:00:00`. Что это значит?

<details><summary>Ответ</summary>

Нулевой partner MAC — хост не получает LACPDU от свитча: порты не в LACP-группе,
LACP выключен или порт-группа в режиме `on` (статическая). Сверить конфиг свитча
(`channel-group N mode active`), скорость и дуплекс портов, `lacp-rate` на обеих сторонах.

</details>

**D5.** NFS-хранилище на отдельном VLAN с MTU 9000: мелкие файлы читаются, большие зависают,
`ls` в каталоге работает.

<details><summary>Ответ</summary>

MTU 9000 не на всём пути: где-то (свитч, бонд, VLAN, бридж, NFS-сервер) осталось

</details>

**D6.** Коллега на удалённом сервере (ЦОД в 500 км) сделал `netplan apply` с бриджем и
потерял доступ. Что делать прямо сейчас и как такое предотвращать?

<details><summary>Ответ</summary>

Сейчас: консоль через IPMI/iLO/iDRAC, откат `/etc/netplan` из бэкапа, `netplan apply`
с консоли; нет IPMI — «remote hands» ЦОДа. Предотвращение: всегда второй канал доступа,
`netplan try` вместо `apply`, бэкап конфига, отложенный откат (`at now + 10 minutes`),
проверка на стенде, изменения — по одному, в согласованное окно.

</details>

**D7.** На свитче в логах `MAC address flapping between Gi1/0/1 and Gi1/0/2`, VM на хосте
периодически недоступны. Что может быть на стороне хоста?

<details><summary>Ответ</summary>

Бонд в `balance-rr`/`balance-xor` без port-channel на свитче — один MAC приходит с двух
портов; либо петля: два NIC в одном бридже без бонда и без STP; либо `balance-alb`. Сделать
LACP с port-channel на свитче или active-backup; проверить `bridge link` и `/proc/net/bonding/*`.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Какие режимы сети есть у KVM/libvirt?

<details><summary>Ответ</summary>

NAT (по умолчанию, `virbr0` + dnsmasq), routed, isolated, bridge к бриджу хоста, macvtap
   (direct); плюс OVS и SR-IOV для особых случаев.

</details>

**2.** Как сделать, чтобы VM получила адрес в физической сети?

<details><summary>Ответ</summary>

Бридж на хосте: физический NIC — порт бриджа, IP хоста — на бридже, VM подключены к
   бриджу (`--network bridge=br0`). Быстрый вариант без правки хоста — macvtap, но хост не
   увидит VM.

</details>

**3.** Что такое bridge и tap-интерфейс?

<details><summary>Ответ</summary>

Bridge — программный L2-свитч в ядре: учит MAC, пересылает кадры между портами. Tap —
   виртуальный NIC, у которого с одной стороны процесс (QEMU), с другой — стек хоста; это «кабель»
   VM в бридж.

</details>

**4.** Что такое VLAN, trunk и access? Как VM попадает в нужный VLAN?

<details><summary>Ответ</summary>

VLAN — логическое разделение L2 по тегу 802.1Q. Access — один VLAN без тега, trunk — много
   VLAN с тегами. Хост подключают транком, дальше — `bond0.20` → `br20` для VM или VLAN-aware
   бридж, где порту VM назначают VLAN (в Proxmox — `tag=20`).

</details>

**5.** Какие режимы bonding знаешь? Что такое LACP?

<details><summary>Ответ</summary>

active-backup, balance-rr, balance-xor, broadcast, 802.3ad, balance-tlb, balance-alb.
   LACP (802.3ad) — протокол динамической агрегации: стороны договариваются, неисправный
   порт выкидывается, трафик делится по хэшу потоков; на свитче нужна port-channel группа.

</details>

**6.** Чем macvtap отличается от bridge?

<details><summary>Ответ</summary>

macvtap — NIC VM напрямую на физическом интерфейсе, без бриджа и правки хоста, но хост
   и VM не видят друг друга; bridge гибче (VLAN, несколько NIC, видимость хоста).

</details>

**7.** Как выглядит типовая сеть хоста гипервизора?

<details><summary>Ответ</summary>

Два NIC в бонде (LACP на стек свитчей) → VLAN: управление, VM, хранилище/миграция (MTU 9000)
   → бриджи для VM; IP хоста — только в управлении и хранилище.

</details>

**8.** Что такое jumbo frames и где их применяют?

<details><summary>Ответ</summary>

Кадры до 9000 байт вместо 1500 — меньше пакетов и нагрузки на CPU при больших потоках:
   хранилище, миграция, бэкап. MTU должен совпадать на всём L2-пути.

</details>

**9.** У VM нет сети. Как будешь искать проблему?

<details><summary>Ответ</summary>

По слоям: линк и ошибки NIC → бонд → VLAN-тег и транк → бридж и fdb → порт VM
   (`domif-getlink`) → `tcpdump -e` на vnet и аплинке → фильтры (br_netfilter, Docker) → IP и
   маршруты в госте.

</details>

**10.** Как безопасно менять сеть на удалённом сервере?

<details><summary>Ответ</summary>

Второй канал (IPMI/консоль), `netplan try` с автооткатом, бэкап конфигов, отложенный
    откат через `at`, проверка на стенде, изменения по одному в согласованное окно.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Объясняю режимы сетей libvirt и выбираю нужный под задачу
- [ ] Создаю сети libvirt из XML, резервирую IP, нахожу NAT-правила
- [ ] Вывожу VM в LAN через бридж (ip, netplan, nmcli) и знаю, почему это рвёт SSH
- [ ] Объясняю ограничения macvtap и Wi-Fi
- [ ] ⭐ Раскладываю VLAN двумя способами и доказываю изоляцию через tcpdump
- [ ] ⭐ Собираю бонд active-backup, проверяю failover; знаю требования LACP к свитчу
- [ ] Рисую типовую схему «bond + VLAN + bridge» и пишу для неё netplan
- [ ] Настраиваю и проверяю jumbo frames
- [ ] Разбираю «VM без сети» по слоям
