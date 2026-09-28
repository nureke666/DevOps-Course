---
title: "17. Основы сетей"
description: "OSI и TCP/IP, инкапсуляция, MAC/IP/порты, TCP vs UDP, ARP, DHCP"
---

# 17. Network Basics — модели, уровни, протоколы

> Источник: `17_network_basics.txt` (Networking Nomad, 9 уроков)
> **После темы ты умеешь:** объяснить путь пакета по уровням, различать TCP и UDP,
> читать порты и понимать, как работает DHCP. База для всех сетевых тем.

---

## 🗺️ Схема: OSI и TCP/IP рядом

```text:no-line-numbers
   OSI (7 уровней, теория)          TCP/IP (4 уровня, практика)      ЧТО ЗДЕСЬ ЖИВЁТ
 ┌───────────────────────┐       ┌──────────────────────────┐
 │ 7. Application        │       │                          │  HTTP, DNS, SSH, SMTP
 │ 6. Presentation       │ ────▶ │  4. Application          │  TLS, JSON, сжатие
 │ 5. Session            │       │                          │  сессии, cookies
 ├───────────────────────┤       ├──────────────────────────┤
 │ 4. Transport          │ ────▶ │  3. Transport            │  TCP, UDP · ПОРТЫ
 ├───────────────────────┤       ├──────────────────────────┤
 │ 3. Network            │ ────▶ │  2. Internet             │  IP, ICMP · IP-АДРЕСА, маршруты
 ├───────────────────────┤       ├──────────────────────────┤
 │ 2. Data Link          │ ────▶ │  1. Link (Network Access)│  Ethernet, ARP · MAC-АДРЕСА
 │ 1. Physical           │       │                          │  кабель, Wi-Fi, оптика
 └───────────────────────┘       └──────────────────────────┘
```

Мнемоника OSI снизу вверх: **P**lease **D**o **N**ot **T**hrow **S**ausage **P**izza **A**way
(Physical, Data Link, Network, Transport, Session, Presentation, Application).

### Инкапсуляция — что реально происходит с данными

```text:no-line-numbers
Приложение:    [ GET /index.html ]
Transport:  [TCP hdr|            данные            ]   ← добавлен порт (80)
Internet: [IP hdr|TCP hdr|       данные            ]   ← добавлен IP (10.0.0.5 → 93.184.x.x)
Link:  [Eth hdr|IP hdr|TCP hdr|  данные  |Eth trailer] ← добавлен MAC (следующего узла)
                             ▼
                      биты в кабель
```
На приёмнике всё разворачивается в обратном порядке. Каждый уровень «разговаривает» только
со своим уровнем на другой стороне.

💼 **Зачем девопсу:** диагностика строится по уровням снизу вверх.
«Сайт не открывается» → есть ли линк (L1/L2) → есть ли IP и маршрут (L3) → открыт ли порт (L4)
→ отвечает ли приложение (L7). Это и есть методика темы [21. Troubleshooting](/linux/21-troubleshooting).

---

## 1-3. Модели и адресация

**Три вида адресов — не путать:**

| Адрес | Уровень | Пример | Область действия |
|-------|---------|--------|------------------|
| **MAC** | L2 | `52:54:00:12:34:56` | Один сегмент сети (не маршрутизируется) |
| **IP** | L3 | `192.168.1.10` | Весь интернет (маршрутизируется) |
| **Порт** | L4 | `443` | Конкретный процесс на хосте |

```text:no-line-numbers
Полный адрес сервиса = IP:порт     →   10.0.0.5:8080
Соединение (socket pair) = 5 элементов:
   протокол + src_IP + src_port + dst_IP + dst_port
```

MAC меняется на **каждом хопе** (маршрутизаторе), IP остаётся неизменным от источника до
получателя (кроме NAT). Это важная деталь, которую спрашивают на собеседованиях.

```bash
ip addr                     # IP-адреса и MAC
ip link                     # интерфейсы и их состояние
ip neigh                    # ARP-таблица (IP ↔ MAC)
ip route                    # маршруты
ss -tulpn                   # порты и процессы
```

---

## 4. Application Layer — прикладной уровень

| Протокол | Порт | Назначение |
|----------|------|-----------|
| HTTP | 80 | Веб |
| **HTTPS** | **443** | Веб + TLS |
| **SSH** | **22** | Удалённый доступ |
| **DNS** | **53** | Имена → IP (UDP, TCP для больших ответов и зон) |
| DHCP | 67/68 | Автоконфигурация (UDP) |
| SMTP / IMAP / POP3 | 25, 587 / 143, 993 / 110, 995 | Почта |
| FTP | 20/21 | Файлы (устарел) |
| NTP | 123 | Время (UDP) |
| SNMP | 161/162 | Мониторинг сетевого оборудования |
| LDAP / LDAPS | 389 / 636 | Каталоги |
| **PostgreSQL / MySQL / Redis / MongoDB** | 5432 / 3306 / 6379 / 27017 | БД |
| Kubernetes API | 6443 | k8s |
| Prometheus / Grafana | 9090 / 3000 | Мониторинг |

Диапазоны портов:
```text:no-line-numbers
0    - 1023    well-known    требуют root для прослушивания
1024 - 49151   registered    приложения
49152- 65535   ephemeral     исходящие соединения клиентов
```
```bash
cat /etc/services | head -30          # справочник соответствий
grep -w 443 /etc/services
sysctl net.ipv4.ip_local_port_range   # какой диапазон эфемерных портов на этой машине
```

---

## 5. Transport Layer — TCP vs UDP (ключевой вопрос собеседования)

| | **TCP** | **UDP** |
|---|---------|---------|
| Соединение | С установкой (handshake) | Без установки |
| Надёжность | Гарантия доставки, подтверждения, переотправка | Нет гарантий |
| Порядок | Гарантирован | Не гарантирован |
| Контроль потока/перегрузки | Есть | Нет |
| Накладные расходы | Заголовок 20+ байт, больше задержек | Заголовок 8 байт, быстро |
| Применение | HTTP(S), SSH, БД, почта | DNS, DHCP, NTP, VoIP, видео, QUIC-основа |

### TCP three-way handshake

```text:no-line-numbers
Клиент                                Сервер
  │                                     │
  │ ──────── SYN (seq=x) ─────────────▶ │   «хочу соединиться»
  │                                     │
  │ ◀─── SYN-ACK (seq=y, ack=x+1) ───── │   «готов, подтверждаю»
  │                                     │
  │ ──────── ACK (ack=y+1) ───────────▶ │   «подтверждаю, работаем»
  │                                     │
  │ ═══════ данные туда-обратно ══════  │
  │                                     │
  │ ──────── FIN ─────────────────────▶ │   закрытие (4 шага: FIN/ACK, FIN/ACK)
```

**Состояния TCP-соединения** (видны в `ss -tan`):

| Состояние | Значение |
|-----------|----------|
| `LISTEN` | Сервер слушает порт |
| `SYN-SENT` / `SYN-RECV` | Идёт установка |
| `ESTABLISHED` | Соединение активно |
| `FIN-WAIT`/`CLOSE-WAIT`/`LAST-ACK` | Закрытие |
| **`TIME-WAIT`** | Ожидание 2×MSL после закрытия (норма, но тысячи — уже симптом) |
| `CLOSED` | Закрыто |

```bash
ss -tan | awk '{print $1}' | sort | uniq -c | sort -rn   # распределение состояний
ss -s                                                    # сводка по сокетам
```

💼 Много `TIME_WAIT` на балансировщике — типичная картина; лечится
`net.ipv4.tcp_tw_reuse=1`, keep-alive и пулом соединений.
Много `CLOSE_WAIT` — **баг приложения**: оно не закрывает сокеты.

---

## 6. Network Layer — IP и ICMP

**IPv4:** 32 бита, 4 октета (`192.168.1.10`), около 4.3 млрд адресов — исчерпаны, отсюда NAT.
**IPv6:** 128 бит (`2001:db8::1`).

Частные диапазоны (RFC 1918) — **выучить наизусть**:
```text:no-line-numbers
10.0.0.0/8         10.0.0.0     – 10.255.255.255      (16.7 млн адресов)
172.16.0.0/12      172.16.0.0   – 172.31.255.255      (1 млн)
192.168.0.0/16     192.168.0.0  – 192.168.255.255     (65 тыс)

Особые:
127.0.0.0/8        loopback (localhost)
169.254.0.0/16     link-local (APIPA) — признак «DHCP не ответил»
0.0.0.0            «любой адрес» / маршрут по умолчанию
255.255.255.255    broadcast
```

**ICMP** — служебный протокол L3 (не TCP и не UDP!): `ping`, `traceroute`, сообщения об ошибках
(`Destination Unreachable`, `Time Exceeded`, `Fragmentation Needed`).

⚠️ Полная блокировка ICMP в firewall ломает **Path MTU Discovery** — соединения зависают на
больших пакетах. Частая причина «мелкие запросы работают, большие — нет».

**MTU** — максимальный размер кадра, обычно 1500 байт. В туннелях (VPN, VXLAN, overlay-сети
Kubernetes) он меньше — отсюда классические проблемы с «зависающими» соединениями.

---

## 7. Link Layer — Ethernet и ARP

**MAC-адрес**: 48 бит, `52:54:00:12:34:56` (первые 3 октета — производитель, OUI).

**ARP** — как по IP узнать MAC внутри локальной сети:
```text:no-line-numbers
Хост A хочет отправить пакет на 192.168.1.20
  1. Смотрит ARP-кэш: есть ли MAC для этого IP?
  2. Нет → широковещательный запрос: "Кто такой 192.168.1.20?"  (на FF:FF:FF:FF:FF:FF)
  3. Хост B отвечает: "Это я, мой MAC 52:54:00:aa:bb:cc"
  4. A кэширует и отправляет кадр на этот MAC
```
```bash
ip neigh                      # современный способ
ip neigh flush all            # очистить кэш
arp -n                        # устаревший
```

Если IP **не в локальной сети** — кадр отправляется на MAC **шлюза по умолчанию**,
а тот маршрутизирует дальше. Это ключ к пониманию маршрутизации (тема 19).

---

## 8. DHCP — автоматическая настройка

```text:no-line-numbers
Клиент                                     DHCP-сервер
  │ ── DISCOVER (broadcast) ─────────────▶ │  «есть кто-нибудь?»
  │ ◀── OFFER (предлагаю 192.168.1.50) ─── │
  │ ── REQUEST (беру его) ───────────────▶ │
  │ ◀── ACK (подтверждаю, lease 24ч) ───── │
```
Мнемоника: **DORA** (Discover, Offer, Request, Acknowledge).

Клиент получает: IP, маску, шлюз по умолчанию, DNS-серверы, домен поиска, NTP, время аренды.

```bash
sudo dhclient -v eth0          # запросить адрес вручную
sudo dhclient -r eth0          # освободить аренду
cat /var/lib/dhcp/dhclient.leases
journalctl -u systemd-networkd | grep -i dhcp
```

⚠️ Адрес вида `169.254.x.x` означает, что **DHCP не ответил** — ищи проблему в сети,
на DHCP-сервере или в конфигурации интерфейса.

💼 В облаках DHCP работает всегда: адрес назначает платформа, а метаданные инстанса доступны
на `169.254.169.254` (magic IP) — оттуда cloud-init берёт настройки и ключи.

---

## 🧪 Мини-лаба: стенд из двух ВМ

Это отдельный стенд — `~/Projects/devops/stands/net-lab/Vagrantfile` (учебную VM `learn-linux` не трогай):

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "generic/ubuntu2204"

  config.vm.define "web" do |web|
    web.vm.hostname = "web"
    web.vm.network :private_network, ip: "192.168.56.10"
    web.vm.provider :libvirt do |v| v.memory = 1024; v.cpus = 1 end
  end

  config.vm.define "app" do |app|
    app.vm.hostname = "app"
    app.vm.network :private_network, ip: "192.168.56.11"
    app.vm.provider :libvirt do |v| v.memory = 1024; v.cpus = 1 end
  end
end
```

```bash
vagrant up                 # поднимет обе
vagrant status
vagrant ssh web            # зайти на web
vagrant ssh app            # зайти на app
vagrant snapshot save --all clean_net
```

Упражнения:

```bash
# === на web ===
ip addr; ip -br addr        # -br = краткий вид, очень удобно
ip link; ip route; ip neigh
hostname -I

# Проверка связи с app
ping -c3 192.168.56.11
ip neigh                    # появился MAC соседа — это ARP в действии

# Уровни в действии: L3 (ping) → L4 (порт) → L7 (данные)
ping -c2 192.168.56.11                                   # L3 работает?
timeout 2 bash -c '</dev/tcp/192.168.56.11/22' && echo "L4: порт 22 открыт"
ssh -o StrictHostKeyChecking=no vagrant@192.168.56.11 hostname   # L7

# Порты и сокеты
ss -tulpn
ss -tan | awk 'NR>1{print $1}' | sort | uniq -c | sort -rn
ss -s

# TCP handshake своими глазами
sudo apt install -y tcpdump
sudo tcpdump -i any -n 'tcp port 22 and host 192.168.56.11' &   # запусти в одном окне
ssh vagrant@192.168.56.11 exit                                   # в другом
#  увидишь: [S], [S.], [.]  — это SYN, SYN-ACK, ACK

# Разница TCP и UDP
sudo tcpdump -i any -n -c5 'udp port 53' &
dig @8.8.8.8 example.com +short
wait

# DHCP и адресация
ip -br addr
cat /etc/netplan/*.yaml
journalctl -u systemd-networkd --no-pager | grep -i -m5 dhcp

# Порты приложений
grep -wE "22|80|443|3306|5432|6379" /etc/services
sysctl net.ipv4.ip_local_port_range

# === на app: поднять «сервис» и подключиться с web ===
python3 -m http.server 8080 &
# === снова на web ===
curl -s http://192.168.56.11:8080/ | head -3
ss -tan | grep 192.168.56.11
```

---

## 📌 Шпаргалка

| Задача | Команда |
|--------|---------|
| IP-адреса кратко | `ip -br addr` |
| Интерфейсы | `ip link`, `ip -br link` |
| ARP-таблица | `ip neigh` |
| Маршруты | `ip route` |
| Открытые порты + процессы | `ss -tulpn` |
| Все соединения | `ss -tan`, сводка — `ss -s` |
| Состояния TCP | `ss -tan \| awk '{print $1}' \| sort \| uniq -c` |
| Проверить порт без nc | `timeout 2 bash -c '</dev/tcp/HOST/PORT'` |
| Захват трафика | `sudo tcpdump -i any -n 'port 443'` |
| DHCP вручную | `sudo dhclient -v eth0` |
| Справочник портов | `/etc/services` |

**Порты наизусть:** 22 SSH · 53 DNS · 80 HTTP · 443 HTTPS · 3306 MySQL · 5432 PostgreSQL ·
6379 Redis · 27017 MongoDB · 6443 k8s API · 9090 Prometheus · 3000 Grafana.

---

## 🧠 Что запомнить

1. Уровни: **L2 MAC (локально) → L3 IP (маршрутизация) → L4 порт (процесс) → L7 приложение**.
   Диагностируй снизу вверх.
2. MAC меняется на каждом хопе, IP — нет (кроме NAT).
3. TCP — с установкой соединения и гарантией доставки; UDP — быстро и без гарантий.
4. Three-way handshake: **SYN → SYN-ACK → ACK**.
5. `TIME_WAIT` — норма; много `CLOSE_WAIT` — баг приложения (не закрывает сокеты).
6. Частные сети: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`. `169.254.x.x` = DHCP не ответил.
7. ICMP — не TCP/UDP; блокировать полностью нельзя (ломается Path MTU Discovery).
8. ARP связывает IP с MAC внутри сегмента; для внешних адресов кадр идёт на MAC шлюза.
9. DHCP = **DORA**. В облаке метаданные инстанса — `169.254.169.254`.
10. Порты 0-1023 требуют root; исходящие берутся из эфемерного диапазона.

Дальше — [18. Subnetting](/linux/18-subnetting).

---

## Задачи

> Для сетевых тем удобнее стенд из **двух ВМ** — `Vagrantfile` в конспекте, раздел «Мини-лаба».
> `vagrant snapshot save --all before_17`

---

### Блок A. Теория

**A1.** Перечисли уровни модели OSI снизу вверх. Какие из них «схлопнуты» в модели TCP/IP?

<details><summary>Ответ</summary>

Снизу вверх: Physical, Data Link, Network, Transport, Session, Presentation, Application.
В TCP/IP: Physical+Data Link → Link (Network Access); Network → Internet; Transport → Transport;
Session+Presentation+Application → Application.

</details>

**A2.** Что такое инкапсуляция? Опиши, что добавляется к данным на каждом уровне.

<details><summary>Ответ</summary>

Каждый уровень добавляет свой заголовок к данным вышестоящего:
Transport добавляет TCP/UDP-заголовок (порты, seq/ack), Internet — IP-заголовок (src/dst IP, TTL),
Link — Ethernet-заголовок (src/dst MAC, тип) и контрольную сумму в конце. На приёмнике заголовки
снимаются в обратном порядке (декапсуляция).

</details>

**A3.** Три вида адресов (MAC, IP, порт) — на каком уровне каждый и какова область действия?

<details><summary>Ответ</summary>

MAC — L2, действует в пределах одного сегмента (широковещательного домена), не
маршрутизируется. IP — L3, глобально маршрутизируемый адрес хоста. Порт — L4, идентифицирует
конкретный процесс/сервис на хосте.

</details>

**A4.** Меняется ли MAC-адрес при прохождении пакета через маршрутизатор? А IP-адрес?

<details><summary>Ответ</summary>

MAC меняется на **каждом** маршрутизаторе: кадр всегда адресуется следующему устройству
в текущем сегменте. IP-адреса источника и назначения остаются неизменными от начала до конца
(исключение — NAT, который подменяет адрес/порт).

</details>

**A5.** Что однозначно идентифицирует TCP-соединение? (Сколько параметров и какие?)

<details><summary>Ответ</summary>

Пятёрка (5-tuple): протокол + IP источника + порт источника + IP назначения + порт
назначения. Именно поэтому один сервер может держать тысячи соединений на одном порту 443.

</details>

**A6.** TCP vs UDP: 5 отличий. Приведи по 3 протокола, использующих каждый.

<details><summary>Ответ</summary>

TCP: с установкой соединения, гарантией доставки, порядком, контролем потока и перегрузки,
большим заголовком. UDP: без соединения, без гарантий и порядка, без контроля потока,
минимальный заголовок, меньшая задержка. TCP: HTTP(S), SSH, PostgreSQL. UDP: DNS, DHCP, NTP
(а также VoIP, видео, QUIC).

</details>

**A7.** Опиши three-way handshake. Зачем нужен третий пакет?

<details><summary>Ответ</summary>

Клиент шлёт `SYN` со своим начальным номером последовательности; сервер отвечает
`SYN-ACK` (подтверждает клиентский и шлёт свой); клиент отвечает `ACK`. Третий пакет нужен,
чтобы **сервер** убедился, что клиент получил его номер последовательности и канал двусторонний
(а также защищает от подделки соединений со спуфингом адреса).

</details>

**A8.** Что означают состояния `LISTEN`, `ESTABLISHED`, `TIME_WAIT`, `CLOSE_WAIT`?
Какое из них сигнализирует о баге в приложении?

<details><summary>Ответ</summary>

`LISTEN` — сокет ждёт входящих соединений. `ESTABLISHED` — соединение установлено,
идёт обмен. `TIME_WAIT` — сторона, закрывшая соединение первой, выжидает 2×MSL, чтобы
«догоняющие» пакеты не попали в новое соединение; это нормально. `CLOSE_WAIT` — удалённая
сторона закрыла соединение, а **локальное приложение не вызвало close()** — признак бага.

</details>

**A9.** Назови частные диапазоны IPv4. Что означает адрес `169.254.10.5`?

<details><summary>Ответ</summary>

`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`. Адрес `169.254.x.x` — link-local (APIPA):
хост не получил ответа от DHCP-сервера и назначил адрес сам; сеть фактически не настроена.

</details>

**A10.** Что такое ICMP? Почему его нельзя полностью блокировать в firewall?

<details><summary>Ответ</summary>

ICMP — служебный протокол сетевого уровня для диагностики и сообщений об ошибках
(`echo request/reply`, `Destination Unreachable`, `Time Exceeded`, `Fragmentation Needed`).
Полная блокировка ломает Path MTU Discovery (сообщение «нужна фрагментация» не доходит),
и соединения с большими пакетами зависают; также теряется диагностика.

</details>

**A11.** Как работает ARP? Что произойдёт, если целевой IP находится в другой сети?

<details><summary>Ответ</summary>

Хост проверяет ARP-кэш; если MAC для нужного IP неизвестен, рассылает широковещательный
ARP-запрос, владелец адреса отвечает своим MAC, ответ кэшируется. Если целевой IP **не** в
локальной сети, ARP выполняется для IP **шлюза по умолчанию**, и кадр отправляется на MAC шлюза.

</details>

**A12.** Опиши процесс DHCP по шагам. Что клиент получает, кроме IP-адреса?

<details><summary>Ответ</summary>

DORA: DISCOVER (широковещательно ищем сервер) → OFFER (сервер предлагает адрес) →
REQUEST (клиент запрашивает именно его) → ACK (сервер подтверждает и фиксирует аренду).
Кроме IP клиент получает маску, шлюз по умолчанию, DNS-серверы, домен поиска, время аренды,
часто NTP-серверы, MTU и статические маршруты.

</details>

**A13.** Что такое MTU и почему в туннелях и overlay-сетях (VPN, Kubernetes) с ним бывают проблемы?

<details><summary>Ответ</summary>

MTU — максимальный размер полезной нагрузки кадра (обычно 1500 байт для Ethernet).
Туннели (VPN, VXLAN, IPIP, GRE) добавляют свои заголовки, уменьшая эффективный MTU; если пакеты
не фрагментируются, а ICMP-сообщения о необходимости фрагментации блокируются, соединение
«подвисает» на больших пакетах. Лечится настройкой MTU/MSS clamping.

</details>

**A14.** Почему порты ниже 1024 требуют root? Как запустить приложение на 80 порту без root?

<details><summary>Ответ</summary>

Порты < 1024 считаются привилегированными: исторически только root мог запускать
на них сервисы, чтобы клиент мог доверять, что на 22 порту действительно SSH.
Варианты без root: capability `CAP_NET_BIND_SERVICE` (`setcap` или `AmbientCapabilities=`
в systemd), запуск за реверс-прокси, проброс через iptables/nftables REDIRECT,
или `sysctl net.ipv4.ip_unprivileged_port_start=80`.

</details>

---

### Блок B. «Что делает / что покажет»

```bash
B1.  ip -br addr
B2.  ip link show
B3.  ip neigh
B4.  ss -tulpn
B5.  ss -tan | awk 'NR>1{print $1}' | sort | uniq -c | sort -rn
B6.  ss -s
B7.  ss -tanp state established
B8.  timeout 2 bash -c '</dev/tcp/1.1.1.1/443'; echo $?
B9.  sudo tcpdump -i any -n -c 10 'tcp port 22'
B10. grep -w 5432 /etc/services
B11. sysctl net.ipv4.ip_local_port_range
B12. sudo dhclient -v eth0
B13. cat /var/lib/dhcp/dhclient.leases
B14. ping -c3 -s 1472 -M do 8.8.8.8
```

- **B1.** Краткая таблица интерфейсов с состоянием и адресами.
- **B2.** Интерфейсы канального уровня: состояние, MTU, MAC.
- **B3.** ARP/NDP-кэш: соответствие IP ↔ MAC.
- **B4.** Слушающие TCP/UDP-сокеты с номерами портов и процессами.
- **B5.** Распределение TCP-соединений по состояниям.
- **B6.** Сводная статистика сокетов по типам и состояниям.
- **B7.** Установленные соединения с указанием процессов.
- **B8.** Проверка доступности TCP-порта 443 у 1.1.1.1; `0` — открыт, иначе — нет.
- **B9.** Захват 10 пакетов SSH-трафика без резолва имён.
- **B10.** Строка из справочника сервисов для порта 5432 (postgresql).
- **B11.** Диапазон эфемерных портов для исходящих соединений.
- **B12.** Запрос IP-адреса по DHCP в подробном режиме.
- **B13.** Текущие DHCP-аренды клиента.
- **B14.** Ping пакетом 1472 байта с запретом фрагментации — проверка MTU 1500 (1472+28 = 1500).

**B15.** Чем `ss -tulpn` отличается от `netstat -tulpn`? Почему сейчас рекомендуют `ss`?

<details><summary>Ответ</summary>

`netstat` из устаревшего пакета `net-tools`, читает `/proc/net/*` построчно и медленно
работает на тысячах соединений; во многих дистрибутивах не установлен. `ss` — из `iproute2`,
работает через netlink, быстрее, поддерживает фильтры состояний (`state established`),
показывает больше информации о сокетах. Рекомендуется `ss`.

</details>

---

### Блок C. Практика

**C1. Стенд.** Подними двухнодовый стенд (web `192.168.56.10`, app `192.168.56.11`).
Убедись, что обе машины видят друг друга. Сделай снапшоты обеих.

**C2. Паспорт сети.** На web собери:
- список интерфейсов с их состоянием и MAC-адресами;
- все IP-адреса;
- шлюз по умолчанию;
- DNS-серверы;
- ARP-таблицу;
- список слушающих портов с процессами.

<details><summary>Ответ</summary>

```bash
ip -br link; ip -br addr
ip route | grep default
resolvectl status 2>/dev/null | grep -A2 'DNS Servers' || cat /etc/resolv.conf
ip neigh
ss -tulpn
```

</details>

**C3. Диагностика по уровням.** Проверь доступность app последовательно по уровням
и запиши команду для каждого:
- L2: есть ли MAC соседа;
- L3: доходит ли ICMP;
- L4: открыт ли порт 22;
- L7: отвечает ли SSH-сервис (получить hostname удалённой машины).

<details><summary>Ответ</summary>

```bash
ip neigh | grep 192.168.56.11                                   # L2
ping -c3 192.168.56.11                                          # L3
timeout 2 bash -c '</dev/tcp/192.168.56.11/22' && echo "L4 OK"  # L4
ssh -o StrictHostKeyChecking=no vagrant@192.168.56.11 hostname  # L7
```

</details>

**C4. TCP handshake своими глазами.** На web запусти `tcpdump`, фильтруя трафик к app
по порту 22, установи SSH-соединение и найди в выводе пакеты `[S]`, `[S.]`, `[.]`.
Затем найди пакеты закрытия соединения (`[F]`).

<details><summary>Ответ</summary>

```bash
sudo tcpdump -i any -n -c 20 "host 192.168.56.11 and tcp port 22" &
ssh -o StrictHostKeyChecking=no vagrant@192.168.56.11 exit
wait
#  Flags [S] → [S.] → [.]  ... в конце [F.] и [.]
```

</details>

**C5. TCP vs UDP в захвате.** Сравни:
- захвати DNS-запрос (UDP 53) — сколько пакетов на один запрос?
- захвати установку TCP-соединения — сколько пакетов до передачи данных?
Сделай вывод о накладных расходах.

<details><summary>Ответ</summary>

```bash
sudo tcpdump -i any -n -c 4 'udp port 53' & dig @8.8.8.8 example.com +short; wait
#  DNS: обычно 2 пакета (запрос + ответ)
sudo tcpdump -i any -n -c 6 'tcp port 80 and host 1.1.1.1' & curl -s -o /dev/null http://1.1.1.1; wait
#  TCP: 3 пакета только на установку, плюс данные, плюс 3-4 на закрытие
```

</details>

**C6. Состояния соединений.** На app запусти `python3 -m http.server 8080`.
С web сделай 20 запросов через `curl`. Сразу после этого посмотри распределение
состояний TCP на обеих машинах. Объясни, откуда берутся `TIME_WAIT` и на какой стороне их больше.

<details><summary>Ответ</summary>

```bash
# на app:
python3 -m http.server 8080 &
# на web:
for i in $(seq 1 20); do curl -s -o /dev/null http://192.168.56.11:8080/; done
ss -tan | awk 'NR>1{print $1}' | sort | uniq -c | sort -rn
```
`TIME_WAIT` образуется у той стороны, которая **закрыла соединение первой** — при обычных
curl-запросах это клиент (web). На сервере при `Connection: close` от клиента их меньше.

</details>

**C7. Порты и процессы.**
1. Запусти три «сервиса» на разных портах (например, `http.server` на 8001, 8002, 8003).
2. Найди, какой процесс слушает каждый порт, тремя способами.
3. Определи, какие порты слушаются только на localhost, а какие на всех интерфейсах.
4. Заверши один из сервисов, используя найденный PID.

<details><summary>Ответ</summary>

```bash
for p in 8001 8002 8003; do (cd /tmp && python3 -m http.server $p >/dev/null 2>&1 &) ; done
ss -tulpn | grep -E ':800[123]'
sudo lsof -i :8001
sudo fuser -n tcp 8002
ss -tulpn | awk '/:800/ {print $5}'      # 0.0.0.0:PORT = все интерфейсы, 127.0.0.1:PORT = только локально
kill "$(ss -tulpnH 'sport = :8003' | grep -oP 'pid=\K[0-9]+' | head -1)"
```

</details>

**C8. Эфемерные порты.** Посмотри текущий диапазон эфемерных портов.
Установи несколько исходящих соединений и покажи, что исходные порты берутся из этого диапазона.
Измени диапазон временно и постоянно.

<details><summary>Ответ</summary>

```bash
sysctl net.ipv4.ip_local_port_range
curl -s -o /dev/null http://192.168.56.11:8080/ &
ss -tan | grep 192.168.56.11             # исходный порт из эфемерного диапазона
sudo sysctl -w net.ipv4.ip_local_port_range="20000 30000"
echo 'net.ipv4.ip_local_port_range=20000 30000' | sudo tee /etc/sysctl.d/99-ports.conf
sudo sysctl --system
```

</details>

**C9. MTU-эксперимент.** Определи MTU интерфейса. Отправь ping с размером пакета,
который точно поместится, и с размером, который превысит MTU (с запретом фрагментации).
Объясни результат. Найди максимальный размер, который проходит.

<details><summary>Ответ</summary>

```bash
ip link show eth0 | grep -o 'mtu [0-9]*'
ping -c2 -M do -s 1472 8.8.8.8      # 1472 + 8 (ICMP) + 20 (IP) = 1500 → проходит
ping -c2 -M do -s 1500 8.8.8.8      # "Frag needed and DF set" → не проходит
for s in 1500 1480 1472 1400; do ping -c1 -M do -s $s -W1 8.8.8.8 >/dev/null 2>&1 && { echo "max payload: $s"; break; }; done
```

</details>

**C10. Скрипт сетевой диагностики.** Напиши `/vagrant/net_report.sh`:
```text:no-line-numbers
=== NETWORK REPORT ===
Hostname: web
Interfaces:
  lo     UP    127.0.0.1/8
  eth0   UP    10.0.2.15/24    52:54:00:12:34:56
  eth1   UP    192.168.56.10/24
Default gateway: 10.0.2.2 (dev eth0)
DNS servers: 10.0.2.3
Listening ports: 5 (22/tcp, 8080/tcp, ...)
Established connections: 3
TIME_WAIT: 12   CLOSE_WAIT: 0
ARP neighbours: 2
Internet: OK (1.1.1.1 reachable, DNS resolves)
```

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
echo "=== NETWORK REPORT ==="
echo "Hostname: $(hostname)"
echo "Interfaces:"
ip -br addr | awk '{printf "  %-8s %-5s %s\n", $1, $2, $3}'
gw=$(ip route | awk '/^default/ {print $3, "(dev "$5")"}')
echo "Default gateway: ${gw:-none}"
dns=$(resolvectl status 2>/dev/null | awk '/DNS Servers/{print $3; exit}')
[ -z "$dns" ] && dns=$(awk '/^nameserver/{print $2}' /etc/resolv.conf | paste -sd, )
echo "DNS servers: $dns"
echo "Listening ports: $(ss -tulnH | wc -l) ($(ss -tulnH | awk '{print $5}' | grep -oE '[0-9]+$' | sort -un | paste -sd,))"
echo "Established connections: $(ss -tanH state established | wc -l)"
echo "TIME_WAIT: $(ss -tanH state time-wait | wc -l)   CLOSE_WAIT: $(ss -tanH state close-wait | wc -l)"
echo "ARP neighbours: $(ip neigh | grep -c REACHABLE)"
if ping -c1 -W2 1.1.1.1 >/dev/null 2>&1 && getent hosts example.com >/dev/null 2>&1; then
  echo "Internet: OK (1.1.1.1 reachable, DNS resolves)"
else
  echo "Internet: PROBLEM"
fi
```

</details>

---

### Блок D. Инциденты

**D1.** Сервер получил адрес `169.254.12.34`. Что это значит и что проверять?

<details><summary>Ответ</summary>

DHCP-сервер не ответил, и ОС назначила link-local адрес (APIPA). Проверять:
физическую/виртуальную связность (`ip link` — состояние UP, есть ли carrier), доступность
DHCP-сервера в этом сегменте, настройки интерфейса (`/etc/netplan/*.yaml`), логи
(`journalctl -u systemd-networkd`, `dhclient -v`), не исчерпан ли пул адресов,
не блокирует ли firewall UDP 67/68, не отвалился ли VLAN/бридж на гипервизоре.

</details>

**D2.** `ss -tan | grep CLOSE_WAIT | wc -l` показывает 5000. Что это означает,
чья это проблема и что делать?

<details><summary>Ответ</summary>

Удалённая сторона закрыла соединения, а приложение не вызвало `close()` на своих сокетах —
дескрипторы утекают, скоро будет `Too many open files`. Это **проблема приложения**
(незакрытые соединения, отсутствие таймаутов, утечка в пуле). Временно: рестарт сервиса и
повышение `LimitNOFILE`. По-настоящему: исправить код, добавить таймауты и корректное
закрытие, проверить пул соединений к БД/внешним сервисам.

</details>

**D3.** На балансировщике десятки тысяч `TIME_WAIT`, новые соединения устанавливаются с ошибками.
Что происходит и какие есть решения?

<details><summary>Ответ</summary>

Каждое закрытое соединение держит пятёрку (5-tuple) занятой 2×MSL (обычно 60 с), и при
высоком темпе соединений исчерпывается диапазон эфемерных портов к одному назначению.
Решения: keep-alive и пул постоянных соединений вместо новых на каждый запрос,
`net.ipv4.tcp_tw_reuse=1`, расширение `ip_local_port_range`, несколько исходящих IP,
увеличение `somaxconn`/backlog. `tcp_tw_recycle` использовать нельзя (удалён, ломает NAT).

</details>

**D4.** Приложение работает по HTTP, но «большие ответы зависают», а мелкие проходят.
При этом `ping` работает. Какая гипотеза первая?

<details><summary>Ответ</summary>

Проблема MTU/фрагментации: мелкие пакеты проходят, большие отбрасываются, а ICMP
«Fragmentation Needed» заблокирован — Path MTU Discovery не работает. Проверка:
`ping -M do -s <размер>` подбором, `tracepath`. Решения: снизить MTU интерфейса/туннеля,
включить MSS clamping на шлюзе, разрешить ICMP type 3 code 4.

</details>

**D5.** Приложение не может слушать порт 80: `Permission denied`, хотя файл исполняемый
и пользователь корректный. Три способа решить.

<details><summary>Ответ</summary>

(1) Выдать capability: `sudo setcap 'cap_net_bind_service=+ep' /path/bin` или в юните
`AmbientCapabilities=CAP_NET_BIND_SERVICE`. (2) Поставить перед приложением reverse-proxy
(nginx) на 80 порту, приложение слушает 8080. (3) Пробросить порт средствами firewall:
`iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8080`
(или `sysctl net.ipv4.ip_unprivileged_port_start=80`, но это ослабляет модель безопасности).

</details>

**D6.** Два сервера в одной подсети не «пингуются». `ip addr` показывает корректные адреса.
Что проверить по уровням?

<details><summary>Ответ</summary>

Снизу вверх: `ip -br link` (интерфейсы UP? есть ли carrier), `ip -br addr`
(в одной ли подсети адреса и одинаковая ли маска), `ip neigh` (резолвится ли MAC — если нет,
проблема на L2: VLAN, бридж, разные сегменты), `ip route` (есть ли маршрут),
firewall (`iptables -L -n`, `nft list ruleset`, `ufw status`) — часто блокируется ICMP,
настройки гипервизора/Security Group, `sysctl net.ipv4.icmp_echo_ignore_all`.

</details>

**D7.** После рестарта сервиса порт остался занят: `Address already in use`.
Что происходит и как правильно?

<details><summary>Ответ</summary>

Сокет в состоянии `TIME_WAIT` (или остался «осиротевший» процесс, держащий порт).
Правильно: приложение должно устанавливать `SO_REUSEADDR` на слушающем сокете — тогда
рестарт проходит мгновенно. Проверить, не остался ли старый процесс:
`ss -tulpn | grep :PORT`, `pgrep -af app`. Не следует «лечить» это через `tcp_tw_recycle`.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что происходит, когда ты вводишь `https://example.com` в браузере? (Классика!)

<details><summary>Ответ</summary>

Резолвинг имени (кэш браузера/ОС → `/etc/hosts` → DNS-рекурсор → корневые → TLD →
авторитативный), установка TCP-соединения (three-way handshake) к IP:443, TLS-рукопожатие
(обмен сертификатом и ключами), отправка HTTP-запроса, ответ сервера, рендеринг.
По пути — ARP для шлюза, маршрутизация, возможно NAT и CDN.

</details>

**2.** Чем TCP отличается от UDP?

<details><summary>Ответ</summary>

TCP — с установкой соединения, гарантией доставки и порядка, контролем перегрузки;
UDP — без соединения и гарантий, но с минимальной задержкой и накладными расходами.

</details>

**3.** Опиши three-way handshake.

<details><summary>Ответ</summary>

`SYN` → `SYN-ACK` → `ACK`: стороны обмениваются начальными номерами последовательности
и подтверждают двусторонний канал.

</details>

**4.** Какие порты у HTTP, HTTPS, SSH, DNS, PostgreSQL?

<details><summary>Ответ</summary>

SSH 22, DNS 53, HTTP 80, HTTPS 443, PostgreSQL 5432 (MySQL 3306, Redis 6379).

</details>

**5.** Что такое ARP?

<details><summary>Ответ</summary>

Протокол разрешения IP-адреса в MAC-адрес внутри локального сегмента через широковещательный
запрос; результат кэшируется (`ip neigh`).

</details>

**6.** Что такое DHCP и как он работает?

<details><summary>Ответ</summary>

Протокол автоматической выдачи сетевых настроек; работает по схеме DISCOVER → OFFER →
REQUEST → ACK, выдаёт IP, маску, шлюз, DNS и время аренды.

</details>

**7.** Как проверить, открыт ли порт на удалённом сервере?

<details><summary>Ответ</summary>

`timeout 2 bash -c '</dev/tcp/host/port'`, `nc -zv host port`, `ss`/`lsof` локально,
`nmap -p PORT host`, `curl -v telnet://host:port`.

</details>

**8.** Что такое MTU и когда он вызывает проблемы?

<details><summary>Ответ</summary>

Максимальный размер кадра. Проблемы возникают в туннелях и overlay-сетях, где заголовки
уменьшают полезный размер, а блокировка ICMP ломает Path MTU Discovery.

</details>

**9.** Что такое TIME_WAIT и почему их много?

<details><summary>Ответ</summary>

Состояние после закрытия соединения инициатором, длится 2×MSL для защиты от «опоздавших»
пакетов. Много их бывает при большом потоке коротких соединений; лечится keep-alive,
пулом соединений и `tcp_tw_reuse`.

</details>

---

### 🎯 Чек-лист

- [ ] Рисую по памяти уровни OSI/TCP-IP и что на каждом живёт
- [ ] Диагностирую по уровням: L2 (`ip neigh`) → L3 (`ping`) → L4 (`ss`, `/dev/tcp`) → L7 (`curl`)
- [ ] Знаю отличия TCP/UDP и three-way handshake
- [ ] Понимаю `TIME_WAIT` и `CLOSE_WAIT`
- [ ] Помню частные диапазоны и что значит `169.254.x.x`
- [ ] Порты (22/53/80/443/3306/5432/6379/6443) — наизусть
- [ ] Поднял стенд из двух ВМ и проверил связность
- [ ] Видел handshake в tcpdump своими глазами
