---
title: "20. Network Config"
description: "Настройка сети: ip, netplan, NetworkManager, DNS, ARP — временные и постоянные изменения"
---

# 20. Network Config — настройка сети

> Источник: `20_network_config.txt` (Networking Nomad, 5 уроков)
> **После темы ты умеешь:** настраивать интерфейсы через `ip`, netplan и NetworkManager,
> задавать статический адрес и не потерять доступ к серверу при этом.

---

## 🗺️ Схема: временно vs постоянно

```text:no-line-numbers
        ┌──────────────────────────────────────────────────────────┐
        │  ВРЕМЕННО (до перезагрузки) — утилиты iproute2            │
        │  ip addr add / ip link set / ip route add                │
        │  ✅ мгновенно, удобно для диагностики                     │
        │  ❌ исчезнет после reboot                                 │
        └──────────────────────────────────────────────────────────┘
                                   │
                                   ▼
        ┌──────────────────────────────────────────────────────────┐
        │  ПОСТОЯННО — менеджер сети дистрибутива                   │
        │                                                          │
        │  Ubuntu server ──▶ netplan (YAML) ──▶ systemd-networkd    │
        │  Ubuntu desktop ─▶ netplan ──────────▶ NetworkManager      │
        │  RHEL/Rocky ─────▶ NetworkManager (nmcli / keyfiles)      │
        │  Debian ─────────▶ /etc/network/interfaces (ifupdown)     │
        │  Контейнеры ─────▶ настраивает рантайм (CNI, docker0)     │
        └──────────────────────────────────────────────────────────┘
```

🔑 Правило: **диагностируешь через `ip`, закрепляешь через менеджер сети.**
Настройка, сделанная только через `ip`, исчезнет при первой же перезагрузке.

---

## 1. Network Interfaces — интерфейсы

### Именование

```text:no-line-numbers
eth0, eth1              — классическое (сейчас редко)
ens3, enp0s3, eno1      — predictable naming (по расположению на шине PCI)
   en = ethernet, p0 = шина 0, s3 = слот 3, o1 = onboard 1
wlp2s0                  — беспроводной
lo                      — loopback (127.0.0.1) — есть всегда
docker0, br-xxx         — мосты Docker
veth...                 — виртуальные пары (контейнеры)
tun0 / wg0              — VPN-туннели
bond0 / team0           — агрегация каналов
vlan10 / eth0.10        — VLAN-интерфейс
```

Predictable naming нужен, чтобы имя не менялось при добавлении карт (в отличие от `eth0/eth1`,
порядок которых зависел от обнаружения). Отключается параметром ядра `net.ifnames=0`.

### Команды `ip` (iproute2) — современный стандарт

```bash
# ПРОСМОТР
ip addr                       # или ip a
ip -br addr                   # ⭐ краткий и читаемый вид
ip -c -br addr                # с цветом
ip link                       # состояние L2, MAC, MTU
ip -s link show eth0          # статистика: пакеты, ошибки, дропы
ip -br link

# АДРЕСА
sudo ip addr add 192.168.1.100/24 dev eth0
sudo ip addr del 192.168.1.100/24 dev eth0
sudo ip addr flush dev eth0             # снять все адреса

# СОСТОЯНИЕ ИНТЕРФЕЙСА
sudo ip link set eth0 up
sudo ip link set eth0 down
sudo ip link set eth0 mtu 1400
sudo ip link set eth0 address 52:54:00:aa:bb:cc    # сменить MAC

# МАРШРУТЫ (тема 19)
ip route
sudo ip route add default via 192.168.1.1

# СОСЕДИ (ARP)
ip neigh
```

Соответствие старых и новых команд (старые `net-tools` часто **не установлены**):

| Устарело (`net-tools`) | Современно (`iproute2`) |
|------------------------|-------------------------|
| `ifconfig` | `ip addr` / `ip link` |
| `ifconfig eth0 up` | `ip link set eth0 up` |
| `ifconfig eth0 192.168.1.5` | `ip addr add 192.168.1.5/24 dev eth0` |
| `route -n` | `ip route` |
| `route add default gw X` | `ip route add default via X` |
| `arp -n` | `ip neigh` |
| `netstat -tulpn` | `ss -tulpn` |
| `netstat -rn` | `ip route` |
| `iptunnel`, `iwconfig` | `ip tunnel`, `iw` |

### Диагностика интерфейса

```bash
ip -s link show eth0           # ошибки, дропы, коллизии
ethtool eth0                   # скорость, дуплекс, линк (нужен пакет ethtool)
ethtool -S eth0                # детальная статистика драйвера
ethtool -i eth0                # какой драйвер и версия прошивки
cat /sys/class/net/eth0/operstate
cat /sys/class/net/eth0/carrier      # 1 = кабель подключён
```

---

## 2. route — маршруты (кратко, подробно — тема 19)

```bash
ip route                                 # посмотреть
sudo ip route add default via 192.168.1.1
sudo ip route add 10.0.0.0/8 via 192.168.1.254 dev eth0
sudo ip route del 10.0.0.0/8
ip route get 8.8.8.8                     # как пойдёт пакет
```

---

## 3. dhclient — получение адреса по DHCP

```bash
sudo dhclient -v eth0           # запросить адрес
sudo dhclient -r eth0           # освободить (release)
sudo dhclient -x                # остановить все процессы dhclient
cat /var/lib/dhcp/dhclient.leases
ip -br addr                     # проверить результат
```

В современной Ubuntu DHCP-клиент встроен в `systemd-networkd`:
```bash
sudo netplan apply
networkctl status
networkctl status eth0
journalctl -u systemd-networkd -n 50
```

---

## 4. Network Manager и netplan

### Netplan (Ubuntu 18.04+) — декларативный YAML

Файлы: `/etc/netplan/*.yaml`. Netplan — «фасад»: он **генерирует** конфигурацию для
бэкенда (`systemd-networkd` на серверах, `NetworkManager` на десктопах).

```yaml
# /etc/netplan/01-netcfg.yaml
network:
  version: 2
  renderer: networkd          # или NetworkManager
  ethernets:
    eth0:
      dhcp4: true
    eth1:
      dhcp4: false
      addresses:
        - 192.168.56.10/24
      routes:
        - to: default
          via: 192.168.56.1
        - to: 10.10.0.0/16
          via: 192.168.56.254
      nameservers:
        addresses: [1.1.1.1, 8.8.8.8]
        search: [internal.local]
      mtu: 1500
```

```bash
sudo netplan generate          # сгенерировать конфиг бэкенда
sudo netplan --debug generate  # с подробностями (покажет ошибки YAML)
sudo netplan try               # ⭐ применить с АВТООТКАТОМ через 120 секунд
sudo netplan apply             # применить окончательно
netplan get                    # текущая конфигурация
netplan status                 # состояние (в новых версиях)
```

🔴 **`netplan try` — золотое правило удалённой настройки.** Если ты ошибся и потерял SSH,
через 120 секунд конфигурация откатится сама, и сервер вернётся. `netplan apply` такой
страховки не даёт.

⚠️ YAML чувствителен к отступам: **только пробелы, никаких табов**. Права на файл — `600`
(иначе netplan предупредит о потенциальной утечке паролей Wi-Fi).

### NetworkManager (`nmcli`) — RHEL/Fedora и десктопы

```bash
nmcli device status                       # интерфейсы и их состояние
nmcli connection show                     # профили соединений
nmcli connection show "Wired connection 1"

# Создать статическое соединение
sudo nmcli connection add type ethernet con-name static-eth1 ifname eth1 \
     ipv4.method manual ipv4.addresses 192.168.56.10/24 \
     ipv4.gateway 192.168.56.1 ipv4.dns "1.1.1.1,8.8.8.8"

sudo nmcli connection up static-eth1
sudo nmcli connection modify static-eth1 +ipv4.routes "10.10.0.0/16 192.168.56.254"
sudo nmcli connection down static-eth1
sudo nmcli connection delete static-eth1
nmcli -t -f IP4.ADDRESS,IP4.GATEWAY device show eth1
```

### Debian — `/etc/network/interfaces`

```text:no-line-numbers
auto eth0
iface eth0 inet static
    address 192.168.1.100/24
    gateway 192.168.1.1
    dns-nameservers 1.1.1.1
```
```bash
sudo systemctl restart networking
sudo ifup eth0 / sudo ifdown eth0
```

### DNS-настройки

```bash
cat /etc/resolv.conf                 # ⚠️ часто это СИМЛИНК, править напрямую бесполезно
ls -l /etc/resolv.conf
resolvectl status                    # реальные DNS в systemd-resolved
resolvectl query example.com
sudo resolvectl flush-caches
```
На Ubuntu DNS задаются в netplan (`nameservers:`) или через NetworkManager — правка
`/etc/resolv.conf` будет перезаписана. Подробнее — тема [22](/linux/22-dns).

---

## 5. arp — таблица соседей

```bash
ip neigh                              # современный вариант
ip neigh show dev eth0
sudo ip neigh flush all               # очистить кэш (полезно при смене оборудования)
sudo ip neigh add 192.168.1.50 lladdr 52:54:00:aa:bb:cc dev eth0 nud permanent   # статическая запись
sudo ip neigh del 192.168.1.50 dev eth0

arp -n                                # устаревшее
arping -I eth0 192.168.1.1            # проверить доступность на L2 (пакет iputils-arping)
```

Состояния в `ip neigh`:

| Состояние | Значение |
|-----------|----------|
| `REACHABLE` | Проверено недавно, запись актуальна |
| `STALE` | Устарела, но используется; проверится при следующем обращении |
| `DELAY` / `PROBE` | Идёт проверка |
| `FAILED` | Не удалось разрешить (хост недоступен на L2) |
| `PERMANENT` | Статическая запись |

💼 Где пригождается: конфликт IP (два хоста с одним адресом → MAC «прыгает»), подмена шлюза
(ARP spoofing), «сервер недоступен после замены сетевой карты» (устаревшая запись у соседа/коммутатора).

---

## 🛡️ Как не потерять сервер при настройке сети

```text:no-line-numbers
1. Всегда имей ВТОРОЙ канал доступа: консоль гипервизора, IPMI, serial, второй интерфейс.
2. Используй netplan try (автооткат) вместо netplan apply.
3. Бэкапь конфиг: sudo cp -a /etc/netplan /etc/netplan.bak.$(date +%F)
4. Страховка через at:  echo "netplan apply" | sudo at now + 10 minutes
   (или заранее подготовленный скрипт отката)
5. Проверяй конфиг до применения: netplan --debug generate
6. Меняй по одному параметру, проверяя связь после каждого шага.
7. Никогда не выполняй ip link set <интерфейс с SSH> down удалённо.
```

---

## 🧪 Мини-лаба

```bash
vagrant ssh web

# 1. Инвентаризация
ip -br addr
ip -br link
ip -s link show eth0
ip route
ip neigh
resolvectl status 2>/dev/null | head -20

# 2. Временный адрес (исчезнет после reboot)
sudo ip addr add 192.168.56.200/24 dev eth1
ip -br addr show eth1
ping -c2 -I 192.168.56.200 192.168.56.11
sudo ip addr del 192.168.56.200/24 dev eth1

# 3. Поднять/опустить интерфейс (НЕ на том, через который SSH!)
ip link show eth1
sudo ip link set eth1 down; ip -br link show eth1
sudo ip link set eth1 up;   ip -br link show eth1

# 4. MTU
ip link show eth1 | grep -o 'mtu [0-9]*'
sudo ip link set eth1 mtu 1400
ip link show eth1 | grep -o 'mtu [0-9]*'
sudo ip link set eth1 mtu 1500

# 5. Netplan: безопасная правка
sudo cp -a /etc/netplan /root/netplan.bak.$(date +%F)
ls /etc/netplan/
sudo cat /etc/netplan/*.yaml
sudo netplan --debug generate      # проверка синтаксиса
sudo netplan try                   # ⭐ с автооткатом; Enter — подтвердить

# 6. Свой конфиг (статический адрес на eth1)
sudo tee /etc/netplan/99-lab.yaml >/dev/null <<'EOS'
network:
  version: 2
  ethernets:
    eth1:
      dhcp4: false
      addresses: [192.168.56.10/24]
      nameservers:
        addresses: [1.1.1.1, 8.8.8.8]
EOS
sudo chmod 600 /etc/netplan/99-lab.yaml
sudo netplan --debug generate
sudo netplan try
ip -br addr show eth1

# 7. ARP
ip neigh
ping -c1 192.168.56.11 >/dev/null; ip neigh show 192.168.56.11
sudo ip neigh flush all; ip neigh
ping -c1 192.168.56.11 >/dev/null; ip neigh show 192.168.56.11
sudo apt install -y iputils-arping
sudo arping -c2 -I eth1 192.168.56.11

# 8. Статистика и ошибки интерфейса
ip -s link show eth1
sudo apt install -y ethtool
sudo ethtool eth1 2>/dev/null | head
sudo ethtool -i eth1

# 9. Уборка
sudo rm -f /etc/netplan/99-lab.yaml
sudo netplan apply
ip -br addr
```

---

## 📌 Шпаргалка

| Задача | Команда |
|--------|---------|
| Адреса кратко | `ip -br addr` |
| Интерфейсы и MAC | `ip -br link`, `ip link` |
| Статистика/ошибки | `ip -s link show eth0`, `ethtool -S eth0` |
| Добавить/снять адрес | `ip addr add 192.168.1.5/24 dev eth0` / `del` |
| Поднять/опустить | `ip link set eth0 up` / `down` |
| MTU | `ip link set eth0 mtu 1400` |
| DHCP вручную | `dhclient -v eth0`, `dhclient -r eth0` |
| ARP-таблица | `ip neigh`, `ip neigh flush all` |
| Проверка L2 | `arping -I eth0 192.168.1.1` |
| Netplan: проверить | `netplan --debug generate` |
| **Netplan: применить с откатом** | `sudo netplan try` |
| Netplan: применить | `sudo netplan apply` |
| systemd-networkd | `networkctl status`, `journalctl -u systemd-networkd` |
| NetworkManager | `nmcli device status`, `nmcli connection show/add/modify/up` |
| DNS | `resolvectl status`, `resolvectl query host`, `resolvectl flush-caches` |

---

## 🧠 Что запомнить

1. `ip` — временно (до перезагрузки), netplan/NetworkManager — постоянно. Не путать.
2. **`sudo netplan try`** вместо `apply` при удалённой настройке: автооткат через 120 с спасает сервер.
3. `net-tools` (`ifconfig`, `route`, `netstat`, `arp`) устарел и часто не установлен —
   учи `ip`, `ss`.
4. `ip -br addr` / `ip -br link` — самый быстрый способ увидеть картину.
5. `/etc/resolv.conf` обычно симлинк на systemd-resolved: правь netplan, а не файл.
6. YAML netplan — только пробелы, права `600`, проверка `netplan --debug generate`.
7. `ip neigh` — состояние соседей; `FAILED` означает недоступность на канальном уровне.
8. Перед изменением сети: бэкап конфига + второй канал доступа (консоль/IPMI).
9. `ip -s link` и `ethtool` — первое место, где видно ошибки и дропы на интерфейсе.

Дальше — [21. Troubleshooting](/linux/21-troubleshooting).

---

## Задачи

> 🔴 Тема меняет настройки сети — **обязательно** `vagrant snapshot save --all before_20`.
> Помни: если потеряешь сеть, доступ остаётся через `virsh console` или `vagrant halt && vagrant up`.

### Блок A. Теория

**A1.** В чём разница между настройкой через `ip` и через netplan/NetworkManager?

<details><summary>Ответ</summary>

Команды `ip` меняют состояние **работающего ядра**: эффект мгновенный, но исчезает
после перезагрузки или перезапуска сетевой службы. netplan/NetworkManager описывают желаемое
состояние в конфигурации, которая применяется при каждой загрузке — это постоянная настройка.

</details>

**A2.** Что такое predictable network interface names (`ens3`, `enp0s3`) и зачем их ввели?

<details><summary>Ответ</summary>

Имена, генерируемые systemd/udev на основе физического расположения устройства
(шина, слот, onboard-индекс) или MAC. Введены потому, что классические `eth0/eth1`
назначались в порядке обнаружения и могли **меняться местами** при перезагрузке или
добавлении карты, ломая конфигурацию и firewall-правила.

</details>

**A3.** Соотнеси устаревшие и современные команды: `ifconfig`, `route -n`, `arp -n`, `netstat -tulpn`.
Почему старые лучше не использовать?

<details><summary>Ответ</summary>

`ifconfig` → `ip addr`/`ip link`; `route -n` → `ip route`; `arp -n` → `ip neigh`;
`netstat -tulpn` → `ss -tulpn`. Пакет `net-tools` не развивается, во многих дистрибутивах и
контейнерах отсутствует, не показывает современные возможности (несколько адресов, политики
маршрутизации, namespaces) и медленнее работает на больших объёмах.

</details>

**A4.** Что такое netplan? Он сам настраивает сеть или нет?

<details><summary>Ответ</summary>

Netplan — это «фасад»: он читает YAML из `/etc/netplan/` и **генерирует** конфигурацию
для бэкенда (`systemd-networkd` на серверах, `NetworkManager` на десктопах). Сам сеть
не настраивает — это делает бэкенд.

</details>

**A5.** 🔑 Чем `netplan try` отличается от `netplan apply`? Почему первый обязателен при удалённой работе?

<details><summary>Ответ</summary>

`netplan try` применяет конфигурацию и ждёт подтверждения; если в течение 120 секунд
не нажать Enter (например, потому что связь потеряна), настройки **автоматически откатываются**.
`netplan apply` применяет немедленно и безвозвратно — ошибка означает потерю доступа к серверу.

</details>

**A6.** Почему правка `/etc/resolv.conf` часто «не срабатывает»? Как правильно задать DNS в Ubuntu?

<details><summary>Ответ</summary>

В Ubuntu `/etc/resolv.conf` — симлинк на файл, генерируемый `systemd-resolved`;
он перезаписывается при каждом применении сетевой конфигурации. Правильно задавать DNS
в netplan (`nameservers:`), через NetworkManager или в `/etc/systemd/resolved.conf`.

</details>

**A7.** Что означают состояния в `ip neigh`: `REACHABLE`, `STALE`, `FAILED`, `PERMANENT`?

<details><summary>Ответ</summary>

`REACHABLE` — соответствие IP↔MAC подтверждено недавно; `STALE` — запись устарела,
будет проверена при следующем использовании; `FAILED` — разрешить адрес не удалось
(хост недоступен на канальном уровне); `PERMANENT` — статическая запись, добавленная вручную.

</details>

**A8.** Зачем может понадобиться `ip neigh flush all`?

<details><summary>Ответ</summary>

При смене оборудования (новая сетевая карта = новый MAC при том же IP), при
подозрении на ARP spoofing, при конфликте адресов или после изменения топологии,
когда в кэше остались устаревшие соответствия.

</details>

**A9.** Как проверить, есть ли физический линк на интерфейсе (кабель подключён)?

<details><summary>Ответ</summary>

`cat /sys/class/net/<if>/carrier` (1 — линк есть), `ip link` (флаг `LOWER_UP`),
`ethtool <if>` (поле `Link detected: yes`).

</details>

**A10.** Где смотреть ошибки и потери пакетов на интерфейсе?

<details><summary>Ответ</summary>

`ip -s link show <if>` (RX/TX errors, dropped, overruns), `ethtool -S <if>`
(детальная статистика драйвера), `/sys/class/net/<if>/statistics/*`, плюс `dmesg`/`journalctl -k`
на предмет сообщений драйвера.

</details>

**A11.** Какие меры предосторожности нужно принять перед изменением сети на удалённом сервере?
Назови пять.

<details><summary>Ответ</summary>

(1) Обеспечить второй канал доступа (консоль гипервизора, IPMI, serial).
(2) Сделать бэкап конфигурации. (3) Проверить синтаксис до применения
(`netplan --debug generate`). (4) Применять через `netplan try` (автооткат) или заранее
запланировать откат через `at`/cron. (5) Менять по одному параметру с проверкой связи после
каждого шага и не трогать интерфейс, через который открыта сессия.

</details>

**A12.** Что такое MTU и когда его меняют вручную?

<details><summary>Ответ</summary>

Maximum Transmission Unit — максимальный размер полезной нагрузки кадра.
Меняют вручную при использовании туннелей и overlay-сетей (VPN, VXLAN, GRE — нужен меньший MTU)
и при включении jumbo frames в дата-центре (9000) для повышения пропускной способности.

</details>

---

### Блок B. «Что делает / что покажет»

```bash
B1.  ip -br addr
B2.  ip -br link
B3.  ip -s link show eth0
B4.  sudo ip addr add 192.168.56.200/24 dev eth1
B5.  sudo ip link set eth1 down
B6.  sudo ip link set eth1 mtu 1400
B7.  sudo dhclient -v eth0
B8.  sudo dhclient -r eth0
B9.  ip neigh
B10. sudo ip neigh flush all
B11. sudo arping -c2 -I eth1 192.168.56.11
B12. sudo netplan --debug generate
B13. sudo netplan try
B14. networkctl status eth0
B15. nmcli device status
B16. resolvectl status
B17. sudo ethtool -i eth0
B18. cat /sys/class/net/eth0/carrier
```

<details><summary>Ответ</summary>

- **B1.** Компактная таблица: интерфейс, состояние, адреса.
- **B2.** Компактно: интерфейс, состояние, MAC.
- **B3.** Статистика интерфейса: принятые/переданные байты и пакеты, ошибки, дропы.
- **B4.** Добавляет дополнительный IP-адрес на интерфейс (временно).
- **B5.** Выключает интерфейс — все соединения через него рвутся (не делать по SSH через него!).
- **B6.** Меняет MTU на 1400 байт.
- **B7.** Запрашивает адрес по DHCP в подробном режиме.
- **B8.** Освобождает аренду DHCP (release).
- **B9.** Таблица соседей (IP ↔ MAC) с состояниями.
- **B10.** Полная очистка ARP-кэша.
- **B11.** Проверка доступности хоста на канальном уровне (ARP-запросы), минуя IP-маршрутизацию.
- **B12.** Генерация конфигурации бэкенда с диагностикой — проверка синтаксиса YAML.
- **B13.** Применение с автоматическим откатом через 120 секунд без подтверждения.
- **B14.** Статус интерфейса глазами systemd-networkd: адреса, маршруты, DNS, состояние.
- **B15.** Состояние устройств с точки зрения NetworkManager.
- **B16.** Текущие DNS-серверы, домены поиска, режим DNSSEC для каждого интерфейса.
- **B17.** Драйвер интерфейса, версия прошивки, шина.
- **B18.** `1` — физический линк есть, `0` — кабель не подключён/нет сигнала.

</details>

**B19.** Чем `ip -br addr` удобнее `ip addr`? В каких случаях нужен полный вывод?

<details><summary>Ответ</summary>

`-br` (brief) даёт по одной строке на интерфейс — быстро увидеть состояние и адреса
всех интерфейсов. Полный вывод нужен, когда важны детали: несколько адресов с флагами,
время жизни (`valid_lft`), scope, secondary-адреса, VRF/namespace-привязки.

</details>

---

### Блок C. Практика

**C1. Полная инвентаризация сети.** Собери на ВМ:
- список интерфейсов, их состояние, MAC, MTU;
- все IP-адреса с масками;
- маршрут по умолчанию и все маршруты;
- DNS-серверы и домен поиска;
- ARP-таблицу;
- статистику по ошибкам на каждом интерфейсе;
- какой бэкенд управляет сетью (networkd или NetworkManager).

**C2. Временная настройка.**
1. Добавь второй IP-адрес на `eth1`.
2. Убедись, что он работает (пинг с явным указанием source-адреса).
3. Посмотри, появился ли маршрут для него.
4. Удали адрес.
5. Объясни, что будет с этой настройкой после перезагрузки.

<details><summary>Ответ (C1–C2)</summary>

```bash
# C1
ip -br link; ip -br addr; ip link | grep -o 'mtu [0-9]*'
ip route
resolvectl status | grep -E 'DNS Servers|DNS Domain' || cat /etc/resolv.conf
ip neigh
for i in $(ls /sys/class/net); do echo "== $i"; ip -s link show "$i" | tail -4; done
systemctl is-active systemd-networkd NetworkManager 2>/dev/null
ls -l /etc/netplan/ && grep -h renderer /etc/netplan/*.yaml 2>/dev/null

# C2
sudo ip addr add 192.168.56.200/24 dev eth1
ip -br addr show eth1
ping -c2 -I 192.168.56.200 192.168.56.11
ip route | grep 192.168.56
sudo ip addr del 192.168.56.200/24 dev eth1
```
После перезагрузки адрес исчезнет: `ip addr add` меняет только состояние работающего ядра.

</details>

**C3. Управление интерфейсом.** На интерфейсе, **не** используемом для SSH:
опусти его, проверь состояние и что стало с адресами/маршрутами, подними обратно,
убедись, что связь восстановилась.

**C4. MTU-эксперимент.** Измени MTU на `eth1` до 1400. Проверь через ping с запретом
фрагментации, какой максимальный размер пакета теперь проходит до соседней ВМ. Верни 1500.
Объясни расчёт (сколько байт занимают заголовки).

<details><summary>Ответ (C3–C4)</summary>

```bash
# C3
ip -br addr show eth1
sudo ip link set eth1 down
ip -br addr show eth1; ip route | grep eth1     # адрес остаётся, маршруты пропадают
sudo ip link set eth1 up
sleep 2; ip -br addr show eth1; ping -c2 192.168.56.11

# C4
sudo ip link set eth1 mtu 1400
ping -c2 -M do -s 1372 192.168.56.11     # 1372 + 8 (ICMP) + 20 (IP) = 1400 → проходит
ping -c2 -M do -s 1400 192.168.56.11     # не проходит
sudo ip link set eth1 mtu 1500
```

</details>

**C5. 🔑 Статический адрес через netplan (главное задание).**
Настрой на `eth1` статическую конфигурацию:
- адрес `192.168.56.10/24`;
- DNS `1.1.1.1` и `8.8.8.8`;
- домен поиска `lab.local`;
- статический маршрут к `10.99.0.0/16` через `192.168.56.11`.

Требования: сделать бэкап, проверить синтаксис **до** применения, применить через `netplan try`,
затем перезагрузить ВМ и убедиться, что настройки сохранились. В конце — откатить.

**C6. Сломай и почини.** Внеси в netplan-файл синтаксическую ошибку (таб вместо пробелов),
запусти `netplan --debug generate` и прочитай сообщение. Затем исправь.
*Вывод:* почему проверка до применения важнее, чем «применю и посмотрю».

**C7. DNS.** Определи текущие DNS-серверы тремя способами. Задай новые через netplan,
проверь, что `resolvectl status` их видит, а `/etc/resolv.conf` — симлинк.
Сделай тестовый запрос и сбрось кэш резолвера.

**C8. ARP-эксперимент.**
1. Очисти ARP-кэш, покажи, что он пуст.
2. Пропингуй соседнюю ВМ, покажи появившуюся запись и её состояние.
3. Подожди и посмотри, как состояние меняется на `STALE`.
4. Добавь статическую (`PERMANENT`) запись, проверь, удали.
5. Проверь доступность соседа на уровне L2 через `arping`.

<details><summary>Ответ (C5–C8)</summary>

```bash
sudo cp -a /etc/netplan /root/netplan.bak.$(date +%F_%H%M)
sudo tee /etc/netplan/99-lab.yaml >/dev/null <<'EOS'
network:
  version: 2
  renderer: networkd
  ethernets:
    eth1:
      dhcp4: false
      addresses: [192.168.56.10/24]
      nameservers:
        addresses: [1.1.1.1, 8.8.8.8]
        search: [lab.local]
      routes:
        - to: 10.99.0.0/16
          via: 192.168.56.11
EOS
sudo chmod 600 /etc/netplan/99-lab.yaml
sudo netplan --debug generate        # проверка ДО применения
sudo netplan try                     # автооткат через 120 с
ip -br addr show eth1; ip route | grep 10.99; resolvectl status | grep -A2 eth1
sudo reboot
# после перезагрузки повторить проверки, затем откат:
sudo rm /etc/netplan/99-lab.yaml && sudo netplan apply

# C6
printf 'network:\n  version: 2\n  ethernets:\n\teth1:\n      dhcp4: true\n' | sudo tee /etc/netplan/98-bad.yaml >/dev/null
sudo netplan --debug generate        # ошибка: tab character / invalid YAML
sudo rm /etc/netplan/98-bad.yaml

# C7
resolvectl status | grep 'DNS Servers'
cat /etc/resolv.conf
ls -l /etc/resolv.conf               # симлинк на ../run/systemd/resolve/stub-resolv.conf
resolvectl query example.com
sudo resolvectl flush-caches

# C8
sudo ip neigh flush all; ip neigh
ping -c1 192.168.56.11 >/dev/null; ip neigh show 192.168.56.11    # REACHABLE
sleep 40; ip neigh show 192.168.56.11                              # STALE
sudo ip neigh add 192.168.56.99 lladdr 52:54:00:11:22:33 dev eth1 nud permanent
ip neigh show 192.168.56.99
sudo ip neigh del 192.168.56.99 dev eth1
sudo arping -c2 -I eth1 192.168.56.11
```

</details>

**C9. Скрипт настройки.** Напиши `/vagrant/set_static_ip.sh`, который:
- принимает интерфейс, адрес/префикс, шлюз и DNS;
- делает бэкап текущей конфигурации netplan с датой;
- генерирует YAML-файл с правами 600;
- проверяет конфиг (`netplan generate`), и **только при успехе** применяет через `netplan try`;
- при ошибке восстанавливает бэкап и завершается с кодом 1.

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
set -euo pipefail
IFACE="${1:?usage: set_static_ip.sh <iface> <addr/prefix> <gateway> <dns1,dns2>}"
ADDR="${2:?}"; GW="${3:?}"; DNS="${4:-1.1.1.1,8.8.8.8}"

BACKUP="/root/netplan.bak.$(date +%F_%H%M%S)"
cp -a /etc/netplan "$BACKUP"
echo "backup: $BACKUP"

CFG=/etc/netplan/99-static.yaml
cat > "$CFG" <<EOF
network:
  version: 2
  renderer: networkd
  ethernets:
    $IFACE:
      dhcp4: false
      addresses: [$ADDR]
      routes:
        - to: default
          via: $GW
      nameservers:
        addresses: [${DNS//,/, }]
EOF
chmod 600 "$CFG"

if ! netplan --debug generate; then
  echo "ОШИБКА конфигурации, откатываюсь" >&2
  rm -f "$CFG"; rm -rf /etc/netplan; cp -a "$BACKUP" /etc/netplan
  netplan apply; exit 1
fi
netplan try || { echo "применение отменено, откат" >&2; rm -f "$CFG"; netplan apply; exit 1; }
ip -br addr show "$IFACE"
```

</details>

**C10. Аварийное восстановление.** Сымитируй потерю сети: примени заведомо неверный netplan
(адрес из другой подсети, без шлюза), потеряй SSH, восстанови доступ через консоль
(`virsh console` или `vagrant`), откати конфигурацию. Опиши последовательность действий.

<details><summary>Ответ</summary>

Последовательность восстановления: (1) зайти на консоль ВМ
(`virsh list --all`, `virsh console <домен>`, выход `Ctrl+]`); (2) войти под пользователем;
(3) `sudo rm /etc/netplan/99-bad.yaml` или восстановить бэкап
(`sudo rm -rf /etc/netplan && sudo cp -a /root/netplan.bak.* /etc/netplan`);
(4) `sudo netplan generate && sudo netplan apply`; (5) проверить `ip -br addr`, `ip route`,
`ping`; (6) убедиться, что SSH вернулся. Вывод: без консольного доступа ошибка в сети
означает поездку в дата-центр.

</details>

---

### Блок D. Инциденты

**D1.** После `netplan apply` пропал SSH-доступ к серверу. Что делать сейчас
и что надо было сделать заранее?

<details><summary>Ответ</summary>

Сейчас: зайти через консоль гипервизора/IPMI/serial, восстановить конфигурацию из
бэкапа или удалить ошибочный файл, `netplan generate && netplan apply`. Если консоли нет —
подключать диск к другой ВМ или пересоздавать инстанс.
Заранее: `netplan try` вместо `apply`, бэкап конфигурации, проверка `netplan --debug generate`,
запланированный откат (`echo 'cp -a /root/netplan.bak/* /etc/netplan/ && netplan apply' | at now + 5 minutes`),
второй канал доступа.

</details>

**D2.** Сервер получил IP по DHCP, но интернета нет. `ip addr` показывает адрес,
`ip route` — пусто. Диагноз?

<details><summary>Ответ</summary>

Нет маршрута по умолчанию: DHCP выдал адрес, но не шлюз (или netplan настроен с
`dhcp4-overrides: use-routes: false`, либо это изолированная сеть без маршрутизатора).
Проверить: `journalctl -u systemd-networkd`, `networkctl status`, содержимое аренды DHCP,
конфигурацию DHCP-сервера. Временно — `ip route add default via <gw>`; постоянно — исправить
netplan/DHCP.

</details>

**D3.** У сервера два интерфейса, и после перезагрузки трафик стал уходить не в тот.
Что произошло и как зафиксировать поведение?

<details><summary>Ответ</summary>

Оба интерфейса получили маршрут по умолчанию (обычно по DHCP), и выбран тот, у которого
меньше метрика; порядок получения адресов может меняться от загрузки к загрузке.
Фиксация: задать разные метрики (`dhcp4-overrides: route-metric: 100/200`), либо отключить
получение маршрута на втором интерфейсе (`use-routes: false`, `default-route: false`),
либо перейти на статическую конфигурацию.

</details>

**D4.** Изменения в `/etc/resolv.conf` пропадают после перезагрузки. Почему и как правильно?

<details><summary>Ответ</summary>

`/etc/resolv.conf` управляется `systemd-resolved` (это симлинк) и перезаписывается.
Правильно: задать DNS в netplan (`nameservers:`) и применить, либо настроить
`/etc/systemd/resolved.conf` (`DNS=`, `FallbackDNS=`) и перезапустить `systemd-resolved`.

</details>

**D5.** После замены сетевой карты сервер недоступен с соседних хостов ещё несколько минут,
хотя сам «видит» сеть. В чём причина?

<details><summary>Ответ</summary>

У соседних хостов и коммутаторов в ARP-кэше осталась запись со **старым MAC**
для этого IP. Пока запись не устареет (или не будет обновлена gratuitous ARP), трафик
отправляется на несуществующий адрес. Ускорить: `ip neigh flush all` на соседях,
`arping -U` (unsolicited/gratuitous ARP) с нового интерфейса.

</details>

**D6.** `ip -s link` показывает растущее число `RX errors` и `dropped`. Что это значит
и что проверять?

<details><summary>Ответ</summary>

Пакеты повреждаются или отбрасываются: проблемы с кабелем/портом/SFP, несогласованный
дуплекс или скорость, переполнение буферов при перегрузке, ошибки MTU, проблемы драйвера,
перегрузка CPU (дропы в софтовой очереди). Проверять: `ethtool eth0` (скорость/дуплекс/линк),
`ethtool -S eth0` (детальные счётчики), `dmesg`/`journalctl -k`, загрузку интерфейса,
состояние порта на коммутаторе, `netstat -s`/`ss -s` для картины по стеку.

</details>

**D7.** Интерфейс в состоянии `UP`, но `carrier` = 0. Что это значит?

<details><summary>Ответ</summary>

Интерфейс административно включён, но **физического линка нет**: не подключён кабель,
выключен порт коммутатора, неисправен SFP/трансивер или сама карта; в виртуальной среде —
сетевой адаптер не подключён к сети гипервизора.

</details>

**D8.** В облаке после смены netplan-конфигурации инстанс не поднялся.
Как безопасно менять сеть в облаке вообще?

<details><summary>Ответ</summary>

Использовать механизмы провайдера: менять сеть через API/консоль облака, а не
вручную внутри гостя; иметь serial console и пароль для входа; применять `netplan try`;
делать снапшот диска перед изменением; в облаке адресация обычно управляется cloud-init и
DHCP — ручная статика часто ломает интеграцию (при пересоздании интерфейса настройки
не совпадут). Безопасный путь — задавать сеть в cloud-init/user-data и в самой платформе.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как задать статический IP-адрес в Ubuntu?

<details><summary>Ответ</summary>

Через netplan: файл в `/etc/netplan/*.yaml` с `addresses`, `routes`, `nameservers`,
проверка `netplan --debug generate`, применение `netplan try`/`apply`.

</details>

**2.** Чем `ip` лучше `ifconfig`?

<details><summary>Ответ</summary>

`ip` из актуального пакета `iproute2`: поддерживает несколько адресов на интерфейсе,
policy routing, namespaces, VRF, работает быстрее и есть в современных системах;
`net-tools` не развивается и часто отсутствует.

</details>

**3.** Как посмотреть, какие DNS-серверы использует система?

<details><summary>Ответ</summary>

`resolvectl status`, `cat /etc/resolv.conf` (с учётом симлинка), `nmcli dev show | grep DNS`.

</details>

**4.** Как применить сетевые настройки без потери доступа?

<details><summary>Ответ</summary>

`sudo netplan try` — автооткат через 120 секунд; плюс бэкап конфигурации, проверка синтаксиса,
второй канал доступа и отложенный откат через `at`.

</details>

**5.** Что такое ARP-таблица и как её посмотреть?

<details><summary>Ответ</summary>

Соответствие IP-адресов MAC-адресам в локальном сегменте; смотреть `ip neigh` (устар. `arp -n`).

</details>

**6.** Как узнать, есть ли ошибки на сетевом интерфейсе?

<details><summary>Ответ</summary>

`ip -s link show <if>`, `ethtool -S <if>`, счётчики в `/sys/class/net/<if>/statistics/`.

</details>

**7.** Где хранятся настройки сети в Ubuntu / RHEL / Debian?

<details><summary>Ответ</summary>

Ubuntu — `/etc/netplan/*.yaml`; RHEL/Rocky — NetworkManager
(`/etc/NetworkManager/system-connections/`, ранее `/etc/sysconfig/network-scripts/`);
Debian — `/etc/network/interfaces` (или тоже netplan/NM в новых версиях).

</details>

**8.** Как временно добавить IP-адрес?

<details><summary>Ответ</summary>

`sudo ip addr add 192.168.1.50/24 dev eth0` — действует до перезагрузки.

</details>

---

## 🎯 Чек-лист

- [ ] Различаю временную (`ip`) и постоянную (netplan/NM) настройку
- [ ] Всегда применяю netplan через `try`, а не `apply`
- [ ] Проверяю конфиг `netplan --debug generate` до применения
- [ ] Знаю, что `/etc/resolv.conf` — симлинк, и задаю DNS правильно
- [ ] Умею читать `ip -s link` и `ethtool` при проблемах на интерфейсе
- [ ] Понимаю состояния `ip neigh` и умею чистить ARP-кэш
- [ ] Восстановил сеть через консоль после намеренной поломки
