---
title: "21. Troubleshooting"
description: "Диагностика сети снизу вверх: ICMP, ping, traceroute/mtr, ss, tcpdump, готовые алгоритмы"
---

# 21. Troubleshooting — диагностика сети

> Источник: `21_troubleshooting.txt` (Networking Nomad, 5 уроков)
> **После темы ты умеешь:** системно искать сетевую проблему, а не тыкать наугад.
> Это навык, который отличает инженера от «перезагрузи и посмотри».

---

## 🗺️ Методика: диагностика снизу вверх по уровням

```text:no-line-numbers
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ L1/L2  ЛИНК И СОСЕДИ                                                     │
 │   ip -br link            интерфейс UP? LOWER_UP?                         │
 │   cat /sys/class/net/X/carrier      кабель есть?                         │
 │   ip neigh               MAC шлюза резолвится?                           │
 │   ethtool X              скорость/дуплекс/линк                           │
 ├──────────────────────────────────────────────────────────────────────────┤
 │ L3    АДРЕС И МАРШРУТ                                                    │
 │   ip -br addr            есть ли IP, правильная ли маска?                │
 │   ip route               есть ли default gateway?                        │
 │   ping <шлюз>            шлюз доступен?                                  │
 │   ping 1.1.1.1           интернет по IP доступен?                        │
 │   traceroute / mtr       где теряется?                                   │
 ├──────────────────────────────────────────────────────────────────────────┤
 │ DNS   РАЗРЕШЕНИЕ ИМЁН                                                    │
 │   ping google.com        имена резолвятся?                               │
 │   dig @1.1.1.1 host      сам DNS работает?                               │
 ├──────────────────────────────────────────────────────────────────────────┤
 │ L4    ПОРТ И ТРАНСПОРТ                                                   │
 │   ss -tulpn              сервис слушает? на каком адресе?                │
 │   nc -zv host port       порт доступен снаружи?                          │
 │   iptables -L -n         firewall не режет?                              │
 ├──────────────────────────────────────────────────────────────────────────┤
 │ L7    ПРИЛОЖЕНИЕ                                                         │
 │   curl -v https://host   что отвечает сервис?                            │
 │   journalctl -u app      что в логах?                                    │
 │   openssl s_client       что с сертификатом?                             │
 └──────────────────────────────────────────────────────────────────────────┘
```

🔑 **Главное правило: не прыгай по уровням.** Идёшь снизу вверх и на каждом шаге получаешь
однозначный ответ «работает / не работает». Так проблема локализуется за минуты,
а не за часы гаданий.

---

## 1. ICMP — протокол диагностики

ICMP работает на L3 (не TCP и не UDP), передаёт служебные сообщения.

| Тип | Сообщение | Когда возникает |
|-----|-----------|-----------------|
| 0 | Echo Reply | Ответ на ping |
| 3 | Destination Unreachable | Хост/сеть/порт недостижимы |
| 3/4 | Fragmentation Needed | **Пакет больше MTU, DF установлен** ← критично для PMTUD |
| 5 | Redirect | «Используй другой шлюз» |
| 8 | Echo Request | Сам ping |
| 11 | Time Exceeded | **TTL исчерпан** ← основа traceroute |

Подтипы Destination Unreachable, которые надо уметь читать:
```text:no-line-numbers
Network unreachable        нет маршрута до сети
Host unreachable           сеть есть, хост не отвечает (нет ARP-ответа)
Port unreachable           хост есть, но порт закрыт (для UDP)
Communication administratively prohibited   → пакет отбросил FIREWALL
```

⚠️ Полная блокировка ICMP — распространённая, но вредная практика: ломается Path MTU Discovery
(зависают соединения с большими пакетами) и теряется вся диагностика.
Блокировать стоит максимум echo-request извне, оставляя типы 3 и 11.

---

## 2. ping — проверка L3

```bash
ping 8.8.8.8                # бесконечно (Ctrl+C)
ping -c4 8.8.8.8            # 4 пакета
ping -i 0.2 -c 20 host      # интервал 0.2 с
ping -W 1 -c 1 host         # таймаут 1 секунда ← для скриптов
ping -s 1472 -M do host     # размер пакета + запрет фрагментации (проверка MTU)
ping -I eth1 host           # с конкретного интерфейса
ping -t 5 host              # ограничить TTL
ping -f host                # flood (только root, аккуратно!)
ping -A host                # адаптивный интервал
```

Что смотреть в выводе:
```text:no-line-numbers
64 bytes from 8.8.8.8: icmp_seq=1 ttl=115 time=12.4 ms
                                    │           │
                                    │           └─ RTT: задержка туда-обратно
                                    └─ оставшийся TTL (≈ сколько хопов прошёл)

--- 8.8.8.8 ping statistics ---
4 packets transmitted, 4 received, 0% packet loss, time 3005ms
rtt min/avg/max/mdev = 12.1/12.5/13.0/0.3 ms
                                      └─ mdev: джиттер. Большой = нестабильный канал
```

Интерпретация:

| Симптом | Вероятная причина |
|---------|-------------------|
| `Destination Host Unreachable` | Нет ARP-ответа: хост выключен или не в этой сети |
| `Network is unreachable` | **Нет маршрута** (часто нет default gateway) |
| 100% потерь, но TCP работает | ICMP заблокирован firewall — нормально для многих хостов |
| Нестабильные потери 5-20% | Перегрузка канала, дуплекс-мисматч, плохой кабель/Wi-Fi |
| Растущий RTT | Перегрузка, буферизация (bufferbloat) |
| `Time to live exceeded` | Петля маршрутизации |

⚠️ **`ping` не проверяет сервис.** Хост может пинговаться, а приложение быть мёртвым, и наоборот.

---

## 3. traceroute — где теряется трафик

```bash
traceroute -n 8.8.8.8            # UDP-зонды (по умолчанию)
traceroute -I -n 8.8.8.8         # ICMP
sudo traceroute -T -p 443 host   # ⭐ TCP-зонды: проходят там, где UDP/ICMP режут
tracepath 8.8.8.8                # без root, показывает MTU
mtr -n 8.8.8.8                   # ⭐⭐ traceroute + ping в реальном времени
mtr -n --report --report-cycles 20 8.8.8.8    # отчёт для тикета
```

Как читать `mtr`:
```text:no-line-numbers
HOST                    Loss%   Snt   Last   Avg  Best  Wrst StDev
1. 10.0.2.2              0.0%    20    0.3   0.4   0.2   0.9   0.1
2. 172.16.0.1            0.0%    20    5.1   5.4   4.9   8.2   0.7
3. 10.10.10.1           40.0%    20   25.3  26.1  24.8  31.0   1.5   ← потери на хопе
4. 8.8.8.8               0.0%    20   12.2  12.4  12.1  13.0   0.2   ← но до цели дошло!
```

🔑 **Потери на промежуточном хопе ≠ проблема.** Маршрутизаторы ограничивают генерацию ICMP
(rate limit) и отвечают на зонды по остаточному принципу, продолжая нормально передавать
транзитный трафик. **Значение имеют только потери на последнем хопе** (и их устойчивый рост,
начинающийся с какого-то хопа и сохраняющийся до конца).

---

## 4. netstat/ss — соединения и порты

```bash
ss -tulpn            # ⭐ слушающие TCP/UDP + процессы (t=tcp u=udp l=listen p=process n=numeric)
ss -tan              # все TCP-соединения
ss -tanp state established
ss -tan state time-wait | wc -l
ss -s                # сводка
ss -tanp '( dport = :443 or sport = :443 )'
ss -tp dst 10.0.0.5
ss -tuni             # с детальной TCP-статистикой (rtt, cwnd, retrans)

netstat -tulpn       # устаревшее, часто не установлено
```

Чтение `ss -tulpn`:
```text:no-line-numbers
State   Recv-Q Send-Q Local Address:Port  Peer Address:Port  Process
LISTEN  0      511          0.0.0.0:80         0.0.0.0:*     users:(("nginx",pid=842,fd=6))
LISTEN  0      4096       127.0.0.1:5432       0.0.0.0:*     users:(("postgres",pid=901,fd=5))
        │      │              │
        │      │              └─ 0.0.0.0 = все интерфейсы, 127.0.0.1 = ТОЛЬКО локально
        │      └─ backlog: максимум ожидающих соединений
        └─ Recv-Q: непрочитанные данные. Постоянно растёт → приложение не успевает
```

🔑 **Самая частая ошибка новичка:** сервис слушает `127.0.0.1:8080`, а не `0.0.0.0:8080` —
снаружи он недоступен, хотя «сервис работает и порт открыт».

Проверка доступности порта:
```bash
nc -zv 10.0.0.5 5432                     # netcat
timeout 2 bash -c '</dev/tcp/10.0.0.5/5432' && echo OPEN     # без nc
curl -v telnet://10.0.0.5:5432
nmap -p 22,80,443 10.0.0.5               # сканирование (только на своих системах!)
```

---

## 5. Packet Analysis — tcpdump

Когда логи и `ss` не дают ответа — смотрим сами пакеты.

```bash
sudo tcpdump -i any -n                       # всё подряд (шумно)
sudo tcpdump -i eth0 -n port 443
sudo tcpdump -i any -n host 10.0.0.5
sudo tcpdump -i any -n 'tcp port 80 and host 10.0.0.5'
sudo tcpdump -i any -n 'icmp'
sudo tcpdump -i any -n 'tcp[tcpflags] & (tcp-syn) != 0'      # только SYN
sudo tcpdump -i any -n -c 100 -w capture.pcap                # ⭐ в файл для Wireshark
sudo tcpdump -r capture.pcap -n                              # прочитать файл
sudo tcpdump -i any -n -A port 80                            # показать содержимое (ASCII)
sudo tcpdump -i any -n -s0 -w /tmp/full.pcap 'port 5432'     # полные пакеты
```

Ключевые опции: `-i` интерфейс (`any` — все), `-n` не резолвить имена (быстрее),
`-c` число пакетов, `-w` писать в файл, `-A`/`-X` содержимое, `-s0` полный размер.

Чтение вывода:
```text:no-line-numbers
10:23:45.123 IP 10.0.0.5.54321 > 93.184.216.34.443: Flags [S], seq 12345, win 64240
                  │        │           │         │          │
                  src IP  src port    dst IP   dst port   флаги TCP
```
Флаги: `[S]` SYN, `[S.]` SYN-ACK, `[.]` ACK, `[P.]` PSH-ACK (данные),
`[F.]` FIN, `[R]` RST (сброс — частый признак «firewall/приложение отказало»).

💼 Типовые сценарии:
```bash
# Доходят ли вообще запросы до сервера?
sudo tcpdump -i any -n "port 8080 and host <клиент>"

# Кто шлёт RST (обрывает соединение)?
sudo tcpdump -i any -n 'tcp[tcpflags] & tcp-rst != 0'

# Проверить DNS-запросы приложения
sudo tcpdump -i any -n port 53

# Собрать дамп для сетевой команды/вендора
sudo tcpdump -i any -n -s0 -w /tmp/issue.pcap host 10.0.0.5 and port 443
```

---

## 🔧 Готовые алгоритмы

### «Сайт не открывается» — 8 шагов

```text:no-line-numbers
1. ip -br addr && ip route            есть адрес и default gateway?
2. ping <gateway>                     шлюз отвечает?
3. ping 1.1.1.1                       интернет по IP есть?
4. ping google.com                    DNS работает?    (нет → см. тему 22)
5. dig +short site.com                какой адрес отдаёт DNS? тот ли?
6. nc -zv site.com 443                порт доступен?
7. curl -v https://site.com           что отвечает сервер? (код, заголовки, TLS)
8. mtr -n <IP сайта>                  где теряется по пути
```

### «Сервис недоступен снаружи» — 6 шагов

```text:no-line-numbers
1. systemctl status app               сервис вообще запущен?
2. ss -tulpn | grep <порт>            слушает? на 0.0.0.0 или на 127.0.0.1?
3. curl localhost:<порт>              работает локально?
4. sudo iptables -L -n -v             firewall на сервере
5. облачные Security Group / firewall провайдера
6. sudo tcpdump -i any port <порт>    доходят ли пакеты от клиента вообще?
```

### «Медленно работает»

```text:no-line-numbers
1. mtr -n <сервер>                    потери и задержки по пути
2. ping -c 100 <сервер>               стабильность RTT, mdev (джиттер)
3. ss -tuni                           retransmits, rtt, cwnd для соединений
4. iperf3 -c <сервер>                 реальная пропускная способность
5. top / iostat                       не сервер ли тормозит, а не сеть (тема 14)
6. curl -w '@format' -o /dev/null -s  разбить время запроса по фазам
```

Файл формата для `curl -w`:
```text:no-line-numbers
dns: %{time_namelookup}s  connect: %{time_connect}s  tls: %{time_appconnect}s
ttfb: %{time_starttransfer}s  total: %{time_total}s\n
```

---

## 🧪 Мини-лаба

```bash
vagrant ssh web
sudo apt install -y tcpdump mtr-tiny traceroute netcat-openbsd curl dnsutils

# 1. Полная диагностика снизу вверх
ip -br link; cat /sys/class/net/eth0/carrier
ip -br addr; ip route
ping -c2 $(ip route | awk '/default/{print $3}')
ping -c2 1.1.1.1
ping -c2 google.com
dig +short google.com
nc -zv google.com 443
curl -sI https://google.com | head -3

# 2. ping — разные сценарии
ping -c4 192.168.56.11
ping -c2 -W1 192.168.56.99 || echo "хост недоступен (ожидаемо)"
ping -c2 10.99.99.99 || echo "нет маршрута"
ping -c2 -M do -s 1472 192.168.56.11
ping -c2 -M do -s 2000 192.168.56.11 || echo "больше MTU — не проходит"

# 3. traceroute/mtr
traceroute -n 1.1.1.1
sudo traceroute -T -p 443 -n 1.1.1.1
mtr -n --report --report-cycles 5 1.1.1.1

# 4. Порты и соединения
ss -tulpn
ss -s
ss -tan state established
python3 -m http.server 8080 --bind 127.0.0.1 &
ss -tulpn | grep 8080                       # видно 127.0.0.1:8080
curl -s localhost:8080 >/dev/null && echo "локально работает"
# с app: curl http://192.168.56.10:8080  → НЕ РАБОТАЕТ (слушает только localhost)
kill %1
python3 -m http.server 8080 &               # теперь на 0.0.0.0
ss -tulpn | grep 8080
# с app: curl http://192.168.56.10:8080 → работает
kill %1

# 5. tcpdump
sudo tcpdump -i any -n -c 10 icmp &
ping -c3 192.168.56.11
wait

sudo tcpdump -i any -n -c 20 'host 192.168.56.11 and tcp port 22' &
ssh -o StrictHostKeyChecking=no vagrant@192.168.56.11 exit
wait

# Записать в файл и прочитать
sudo tcpdump -i any -n -c 20 -w /tmp/cap.pcap port 53 &
dig @1.1.1.1 example.com >/dev/null
wait
sudo tcpdump -r /tmp/cap.pcap -n | head

# 6. Симуляция проблемы: firewall режет порт
sudo iptables -A INPUT -p tcp --dport 8080 -j DROP
python3 -m http.server 8080 &
# с app: curl --max-time 3 http://192.168.56.10:8080 → таймаут (не connection refused!)
sudo tcpdump -i any -n -c5 'tcp port 8080'    # видно SYN без ответа
sudo iptables -D INPUT -p tcp --dport 8080 -j DROP
kill %1

# 7. DROP vs REJECT — важное отличие
sudo iptables -A INPUT -p tcp --dport 9999 -j REJECT
timeout 3 bash -c '</dev/tcp/127.0.0.1/9999' || echo "REJECT → отказ сразу"
sudo iptables -D INPUT -p tcp --dport 9999 -j REJECT
sudo iptables -A INPUT -p tcp --dport 9999 -j DROP
timeout 3 bash -c '</dev/tcp/127.0.0.1/9999' || echo "DROP → ждали до таймаута"
sudo iptables -D INPUT -p tcp --dport 9999 -j DROP

# 8. Разбор времени HTTP-запроса по фазам
cat > /tmp/curl-format.txt <<'EOS'
dns:     %{time_namelookup}s
connect: %{time_connect}s
tls:     %{time_appconnect}s
ttfb:    %{time_starttransfer}s
total:   %{time_total}s
EOS
curl -w "@/tmp/curl-format.txt" -o /dev/null -s https://google.com
```

---

## 📌 Шпаргалка

| Уровень | Команда |
|---------|---------|
| Линк | `ip -br link`, `cat /sys/class/net/X/carrier`, `ethtool X` |
| Соседи | `ip neigh`, `arping -I eth0 <ip>` |
| Адрес/маршрут | `ip -br addr`, `ip route`, `ip route get <ip>` |
| Доступность | `ping -c4 -W1 <ip>` |
| Путь | `traceroute -n`, `traceroute -T -p 443`, `tracepath`, **`mtr -n`** |
| DNS | `dig +short host`, `dig @1.1.1.1 host`, `resolvectl query host` |
| Порты локально | `ss -tulpn` |
| Порт удалённо | `nc -zv host port`, `timeout 2 bash -c '</dev/tcp/h/p'` |
| Firewall | `sudo iptables -L -n -v`, `sudo nft list ruleset`, `ufw status` |
| Пакеты | `sudo tcpdump -i any -n 'host X and port Y'`, `-w file.pcap` |
| HTTP | `curl -v`, `curl -w '@fmt'`, `curl -sI` |
| TLS | `openssl s_client -connect host:443 -servername host` |
| Пропускная способность | `iperf3 -s` / `iperf3 -c host` |

---

## 🧠 Что запомнить

1. **Диагностируй снизу вверх:** линк → адрес → маршрут → шлюз → DNS → порт → приложение.
2. `ping` проверяет L3, а не сервис. Отсутствие ответа может означать просто блокировку ICMP.
3. В `mtr` важны потери **на последнем хопе**; на промежуточных они обычно артефакт rate limit.
4. `ss -tulpn`: `127.0.0.1:порт` — снаружи недоступен, `0.0.0.0:порт` — доступен.
5. **DROP** → клиент ждёт таймаута; **REJECT** → мгновенный `Connection refused`.
   По этому признаку отличают firewall от «сервис не запущен».
6. `traceroute -T -p 443` проходит там, где ICMP и UDP фильтруются.
7. `tcpdump` отвечает на вопрос «доходят ли пакеты вообще» — когда логи молчат.
8. Полная блокировка ICMP ломает Path MTU Discovery.
9. `curl -w` разбивает запрос на фазы (DNS / connect / TLS / TTFB) — сразу видно, что тормозит.
10. Проверяй с **обеих** сторон: клиент и сервер видят разную картину.

Дальше — [22. DNS](/linux/22-dns) — финальная тема курса.

---

## Задачи

> Стенд из двух ВМ, `vagrant snapshot save --all before_21`
> Установи: `sudo apt install -y tcpdump mtr-tiny traceroute netcat-openbsd dnsutils curl`

### Блок A. Теория

**A1.** Опиши методику диагностики «снизу вверх». Почему нельзя начинать с уровня приложения?

<details><summary>Ответ</summary>

Проверяем последовательно: линк и соседей (L1/L2) → адрес и маршрут (L3) → DNS →
порт и транспорт (L4) → приложение (L7). Каждый шаг даёт однозначный ответ и отсекает половину
пространства причин. Начинать сверху бессмысленно: ошибка приложения может быть следствием
отсутствия маршрута, и ты будешь часами читать логи сервиса вместо одной команды `ip route`.

</details>

**A2.** Что такое ICMP? Назови 4 типа сообщений и когда они возникают.

<details><summary>Ответ</summary>

ICMP — служебный протокол сетевого уровня. Echo Request/Reply (тип 8/0) — ping;
Destination Unreachable (3) — нет маршрута/хоста/порта или запрещено firewall;
Fragmentation Needed (3/4) — пакет больше MTU при установленном DF;
Time Exceeded (11) — TTL обнулился, основа traceroute.

</details>

**A3.** Почему нельзя полностью блокировать ICMP на firewall?

<details><summary>Ответ</summary>

Блокировка типа 3 код 4 ломает Path MTU Discovery — соединения с большими пакетами
зависают. Блокировка типа 11 убивает traceroute, типа 3 — быстрые отказы. Теряется вся
диагностика, а проблемы становятся «плавающими». Разумно ограничивать только echo-request
извне, не трогая служебные типы.

</details>

**A4.** Чем `Destination Host Unreachable` отличается от `Network is unreachable`?

<details><summary>Ответ</summary>

`Network is unreachable` — у **отправителя** нет маршрута до сети назначения
(обычно нет default gateway). `Destination Host Unreachable` — маршрут есть, но ближайший
маршрутизатор (или сам хост) не смог доставить пакет конечному узлу: чаще всего нет ARP-ответа,
то есть хост выключен или отсутствует в сегменте.

</details>

**A5.** Хост не отвечает на `ping`, но сайт на нём открывается. Как такое возможно?

<details><summary>Ответ</summary>

На хосте (или на firewall по пути) заблокированы ICMP echo-запросы, а TCP-трафик
на 80/443 разрешён. Это очень распространённая конфигурация — поэтому `ping` не является
доказательством недоступности сервиса.

</details>

**A6.** В `mtr` на 3-м хопе 40% потерь, на последнем 0%. Есть ли проблема? Объясни.

<details><summary>Ответ</summary>

Нет. Потери на промежуточном хопе означают, что этот маршрутизатор ограничивает
генерацию ICMP-ответов на зонды (rate limit) или деприоритизирует их. Транзитный трафик
при этом идёт нормально — что и подтверждают 0% потерь на последнем хопе. Реальная проблема —
это потери на **конечном** хопе (или потери, начинающиеся с какого-то хопа и сохраняющиеся до конца).

</details>

**A7.** Что означает `Recv-Q`, который постоянно растёт в выводе `ss`?

<details><summary>Ответ</summary>

В приёмном буфере сокета накапливаются данные, которые приложение не успевает читать:
для слушающего сокета — очередь непринятых соединений (приложение не вызывает `accept()`),
для установленного — не читает данные. Признак того, что приложение перегружено, зависло
или заблокировано (например, ждёт БД).

</details>

**A8.** 🔑 В чём разница между `127.0.0.1:8080` и `0.0.0.0:8080` в выводе `ss -tulpn`?

<details><summary>Ответ</summary>

`127.0.0.1:8080` — сокет привязан только к loopback: доступен исключительно с самого
хоста. `0.0.0.0:8080` — слушает на всех интерфейсах, доступен по сети. Это причина №1
ситуации «локально работает, снаружи нет».

</details>

**A9.** 🔑 Чем поведение firewall с правилом `DROP` отличается от `REJECT` с точки зрения клиента?
Как это использовать в диагностике?

<details><summary>Ответ</summary>

`DROP` молча отбрасывает пакет: клиент повторяет SYN и ждёт до таймаута (десятки секунд),
ошибка — `Connection timed out`. `REJECT` отправляет ICMP unreachable или TCP RST: клиент
получает мгновенный `Connection refused`. Диагностический вывод: **долгий таймаут** обычно
означает фильтрацию на пути (firewall/Security Group), **мгновенный отказ** — что до хоста
дошли, но порт никто не слушает (или стоит REJECT).

</details>

**A10.** Почему `traceroute -T -p 443` иногда работает там, где обычный `traceroute` показывает звёздочки?

<details><summary>Ответ</summary>

Многие маршрутизаторы и firewall фильтруют UDP-зонды traceroute и ICMP, но пропускают
TCP-трафик на 443/80, поскольку это «нормальный» пользовательский трафик. TCP-зонды
имитируют его и проходят дальше.

</details>

**A11.** Что означает флаг `[R]` (RST) в выводе tcpdump?

<details><summary>Ответ</summary>

RST — принудительный сброс соединения: порт закрыт, приложение завершилось/отказалось
обрабатывать соединение, сработал firewall с REJECT, произошёл таймаут у балансировщика или
промежуточного устройства, либо разошлись состояния TCP (например, после NAT-таймаута).

</details>

**A12.** Какие фазы HTTP-запроса можно измерить через `curl -w` и что означает каждая?

<details><summary>Ответ</summary>

`time_namelookup` — разрешение имени (DNS); `time_connect` — установка TCP-соединения;
`time_appconnect` — завершение TLS-рукопожатия; `time_starttransfer` (TTFB) — момент прихода
первого байта ответа (включает обработку на сервере); `time_total` — полное время запроса.
Разность между фазами показывает, какой этап тормозит.

</details>

**A13.** Что такое джиттер (`mdev` в выводе ping) и почему он важен?

<details><summary>Ответ</summary>

`mdev` — среднее отклонение RTT, то есть разброс задержек. Большой джиттер критичен
для голоса, видео, игр и синхронных протоколов; он указывает на перегрузку, буферизацию
или нестабильный канал даже при отсутствии потерь.

</details>

---

### Блок B. «Что делает / что покажет»

```bash
B1.  ping -c4 -W1 8.8.8.8
B2.  ping -c2 -M do -s 1472 8.8.8.8
B3.  traceroute -n 8.8.8.8
B4.  sudo traceroute -T -p 443 -n example.com
B5.  mtr -n --report --report-cycles 10 1.1.1.1
B6.  ss -tulpn
B7.  ss -tan state established
B8.  ss -tuni
B9.  nc -zv 10.0.0.5 5432
B10. timeout 2 bash -c '</dev/tcp/10.0.0.5/5432'; echo $?
B11. sudo tcpdump -i any -n -c 20 'host 10.0.0.5 and port 443'
B12. sudo tcpdump -i any -n 'tcp[tcpflags] & tcp-rst != 0'
B13. sudo tcpdump -i any -n -s0 -w /tmp/cap.pcap port 53
B14. curl -v https://example.com 2>&1 | head -20
B15. openssl s_client -connect example.com:443 -servername example.com </dev/null
```

<details><summary>Ответ</summary>

- **B1.** Четыре ICMP-запроса с таймаутом 1 секунда на ответ.
- **B2.** Пакет размером 1472 байта без фрагментации — проверка прохождения MTU 1500.
- **B3.** Путь до 8.8.8.8 без резолва имён (UDP-зонды).
- **B4.** Трассировка TCP-зондами на порт 443 — проходит через фильтрующие узлы.
- **B5.** Отчёт mtr за 10 циклов: потери и задержки по каждому хопу.
- **B6.** Слушающие TCP/UDP-сокеты с адресами, портами и процессами.
- **B7.** Только установленные TCP-соединения.
- **B8.** Детальная TCP-статистика по соединениям: rtt, cwnd, retransmits.
- **B9.** Проверка доступности порта 5432 без передачи данных.
- **B10.** То же средствами bash; `0` — порт открыт, ненулевой код — нет.
- **B11.** Захват 20 пакетов трафика к конкретному хосту по порту 443.
- **B12.** Захват только пакетов с флагом RST — поиск того, кто обрывает соединения.
- **B13.** Полный дамп DNS-трафика в файл для анализа в Wireshark.
- **B14.** Подробности HTTP-запроса: DNS, соединение, TLS, заголовки запроса и ответа.
- **B15.** TLS-рукопожатие: цепочка сертификатов, срок действия, версия TLS, шифр.

</details>

**B16.** Чем `ss -tulpn` отличается от `nc -zv`? Какой инструмент для чего?

<details><summary>Ответ</summary>

`ss` показывает состояние сокетов **на локальной машине**: кто слушает, какие есть
соединения. `nc -zv` проверяет доступность порта **с точки зрения клиента** (по сети, через
firewall). Для полной картины нужны оба: `ss` на сервере и `nc`/`curl` с клиента.

</details>

---

### Блок C. Практика

**C1. Полная диагностика.** Пройди все 8 шагов алгоритма «сайт не открывается»
для `https://example.com`, записывая результат каждого шага. Оформи как чек-лист с отметками.

**C2. ping в разных сценариях.** Получи и зафиксируй вывод для:
- доступного хоста;
- несуществующего хоста в своей подсети;
- адреса в сети, к которой нет маршрута;
- хоста, блокирующего ICMP (например, многие публичные сайты);
- пакета больше MTU с запретом фрагментации.

Для каждого — объясни, чем отличается сообщение и что оно говорит о проблеме.

<details><summary>Ответ (C1–C2)</summary>

```bash
# C1
ip -br addr && ip route
ping -c2 -W1 "$(ip route | awk '/default/{print $3}')"
ping -c2 -W1 1.1.1.1
ping -c2 -W1 example.com
dig +short example.com
nc -zv example.com 443
curl -sSI --max-time 5 https://example.com | head -3
mtr -n --report --report-cycles 5 example.com

# C2
ping -c2 -W1 192.168.56.11                    # 0% loss
ping -c2 -W1 192.168.56.99                    # Destination Host Unreachable
ping -c2 -W1 10.99.99.99                      # Network is unreachable (нет маршрута)
ping -c2 -W1 example.com                      # 100% loss (ICMP фильтруется), но curl работает
ping -c2 -M do -s 2000 192.168.56.11          # Frag needed / message too long
```

</details>

**C3. Локализация потерь.** Запусти `mtr` до нескольких целей (`1.1.1.1`, `8.8.8.8`,
своего провайдера) на 20 циклов. Определи:
- есть ли реальные потери;
- на каком хопе начинается устойчивый рост задержки;
- является ли проблема «твоей» или вне зоны ответственности.

**C4. 🔑 Ловушка localhost.** Воспроизведи классическую ошибку:
1. На web запусти сервис, слушающий только `127.0.0.1:8080`.
2. С app попробуй подключиться — зафиксируй ошибку.
3. Докажи через `ss -tulpn`, в чём причина.
4. Перезапусти сервис на `0.0.0.0:8080` и проверь снова.
5. Через `tcpdump` покажи разницу в поведении на обоих этапах.

<details><summary>Ответ</summary>

```bash
# C4  (на web)
python3 -m http.server 8080 --bind 127.0.0.1 &
ss -tulpn | grep 8080                          # 127.0.0.1:8080
#    (на app)
curl --max-time 3 http://192.168.56.10:8080 || echo "недоступно"
#    (на web) — видно, что SYN приходит, но ядро отвечает RST
sudo tcpdump -i any -n -c5 'tcp port 8080'
kill %1
python3 -m http.server 8080 &                  # 0.0.0.0:8080
ss -tulpn | grep 8080
#    (на app)
curl -s http://192.168.56.10:8080 | head -3    # работает
kill %1
```

</details>

**C5. 🔑 DROP vs REJECT.** Поставь на порт 9999 правило `DROP`, затем `REJECT`,
и в каждом случае измерь, как ведёт себя клиент (время до ошибки, текст ошибки).
Сделай вывод: как по поведению клиента отличить «firewall режет» от «сервис не запущен».

<details><summary>Ответ</summary>

```bash
sudo iptables -A INPUT -p tcp --dport 9999 -j REJECT
time timeout 5 bash -c '</dev/tcp/127.0.0.1/9999' ; echo "---"
sudo iptables -D INPUT -p tcp --dport 9999 -j REJECT
sudo iptables -A INPUT -p tcp --dport 9999 -j DROP
time timeout 5 bash -c '</dev/tcp/127.0.0.1/9999' ; echo "---"
sudo iptables -D INPUT -p tcp --dport 9999 -j DROP
```
REJECT — ошибка мгновенно (`Connection refused`); DROP — ожидание до таймаута.
Значит: мгновенный отказ → до хоста дошли, порт не слушается; долгий таймаут → фильтрация.

</details>

**C6. tcpdump-практика.**
1. Захвати ICMP-трафик при пинге соседа.
2. Захвати полный TCP-handshake при SSH-подключении и найди `[S]`, `[S.]`, `[.]`.
3. Захвати DNS-запрос и найди в нём имя, которое резолвится.
4. Запиши дамп в файл и прочитай его обратно.
5. Найди в трафике пакеты RST.

**C7. Время HTTP-запроса.** Через `curl -w` разбей запрос к нескольким сайтам на фазы
(DNS / TCP / TLS / TTFB / total). Определи, какая фаза занимает больше всего времени
и что это значит.

<details><summary>Ответ (C6–C7)</summary>

```bash
# C6
sudo tcpdump -i any -n -c6 icmp & ping -c3 192.168.56.11 >/dev/null; wait
sudo tcpdump -i any -n -c10 'host 192.168.56.11 and tcp port 22' & ssh -o StrictHostKeyChecking=no vagrant@192.168.56.11 exit; wait
sudo tcpdump -i any -n -c4 -A port 53 & dig @1.1.1.1 example.com >/dev/null; wait
sudo tcpdump -i any -n -c10 -w /tmp/cap.pcap port 53 & dig @1.1.1.1 github.com >/dev/null; wait
sudo tcpdump -r /tmp/cap.pcap -n
sudo tcpdump -i any -n 'tcp[tcpflags] & tcp-rst != 0' -c5 &

# C7
cat > /tmp/fmt.txt <<'EOS'
dns:     %{time_namelookup}s
connect: %{time_connect}s
tls:     %{time_appconnect}s
ttfb:    %{time_starttransfer}s
total:   %{time_total}s
EOS
for u in https://google.com https://github.com https://example.com; do
  echo "== $u"; curl -w "@/tmp/fmt.txt" -o /dev/null -s "$u"
done
```

</details>

**C8. Скрипт диагностики.** Напиши `/vagrant/net_diag.sh <host> [port]`, который последовательно
проверяет и выводит с отметками `[OK]`/`[FAIL]`:
```text:no-line-numbers
=== NETWORK DIAGNOSTIC: example.com:443 ===
[OK]   Interface eth0 is UP (carrier present)
[OK]   IP address: 10.0.2.15/24
[OK]   Default gateway: 10.0.2.2
[OK]   Gateway reachable (0.4 ms)
[OK]   Internet reachable (1.1.1.1)
[OK]   DNS resolves: example.com -> 93.184.216.34
[OK]   Port 443 is open
[OK]   HTTP response: 200 (0.234s)
[WARN] TLS certificate expires in 25 days
=== RESULT: OK ===
```
Скрипт должен останавливаться на первой критической ошибке и подсказывать, что проверять дальше.

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
HOST="${1:?usage: net_diag.sh <host> [port]}"; PORT="${2:-443}"
ok(){ echo "[OK]   $*"; }; warn(){ echo "[WARN] $*"; }
fail(){ echo "[FAIL] $*"; echo "=== RESULT: FAILED ==="; exit 1; }

echo "=== NETWORK DIAGNOSTIC: $HOST:$PORT ==="
IF=$(ip route | awk '/^default/{print $5; exit}')
[ -n "$IF" ] || fail "нет интерфейса с маршрутом по умолчанию (проверь: ip route)"
[ "$(cat /sys/class/net/$IF/carrier 2>/dev/null)" = 1 ] \
  && ok "Interface $IF is UP (carrier present)" || fail "нет линка на $IF (проверь: ip link, ethtool $IF)"

ADDR=$(ip -br addr show "$IF" | awk '{print $3}')
[ -n "$ADDR" ] && ok "IP address: $ADDR" || fail "нет IP-адреса (проверь DHCP/netplan)"

GW=$(ip route | awk '/^default/{print $3; exit}')
[ -n "$GW" ] && ok "Default gateway: $GW" || fail "нет default gateway (проверь: ip route)"

RTT=$(ping -c1 -W2 "$GW" 2>/dev/null | awk -F'time=' '/time=/{print $2}')
[ -n "$RTT" ] && ok "Gateway reachable ($RTT)" || fail "шлюз недоступен (проверь: ip neigh, arping)"

ping -c1 -W2 1.1.1.1 >/dev/null 2>&1 && ok "Internet reachable (1.1.1.1)" \
  || fail "нет интернета (проверь NAT/firewall/провайдера)"

IP=$(getent hosts "$HOST" | awk '{print $1; exit}')
[ -n "$IP" ] && ok "DNS resolves: $HOST -> $IP" || fail "DNS не резолвит (проверь: resolvectl status, dig @1.1.1.1 $HOST)"

timeout 3 bash -c "</dev/tcp/$IP/$PORT" 2>/dev/null && ok "Port $PORT is open" \
  || fail "порт $PORT закрыт/фильтруется (проверь firewall, Security Group, ss -tulpn на сервере)"

CODE=$(curl -sS -o /dev/null -w '%{http_code} %{time_total}' --max-time 10 "https://$HOST" 2>/dev/null)
[ -n "$CODE" ] && ok "HTTP response: $CODE" || warn "HTTP-запрос не выполнен"

END=$(echo | openssl s_client -connect "$HOST:$PORT" -servername "$HOST" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
if [ -n "$END" ]; then
  DAYS=$(( ( $(date -d "$END" +%s) - $(date +%s) ) / 86400 ))
  (( DAYS < 30 )) && warn "TLS certificate expires in $DAYS days" || ok "TLS certificate valid ($DAYS days)"
fi
echo "=== RESULT: OK ==="
```

</details>

**C9. Сломанная система (работа в паре с самим собой).**
Создай список из 5 «поломок», внеси их по одной и каждый раз пройди диагностику как будто
не знаешь причину. Примеры поломок:
1. удалить default gateway;
2. указать несуществующий DNS-сервер;
3. заблокировать порт сервиса через iptables (DROP);
4. запустить сервис на localhost вместо 0.0.0.0;
5. опустить интерфейс `eth1`.

Для каждой запиши: **симптом → команда, которая локализовала → причина → фикс**.

<details><summary>Ответ</summary>

| Поломка | Симптом | Что локализует | Фикс |
|---------|---------|----------------|------|
| Нет default gateway | `Network is unreachable` | `ip route` | `ip route add default via …` / netplan |
| Неверный DNS | `ping 1.1.1.1` ок, `ping google.com` — «Name or service not known» | `dig @1.1.1.1 google.com`, `resolvectl status` | исправить `nameservers` в netplan |
| iptables DROP на порт | `curl` висит до таймаута | `ss -tulpn` (слушает), `tcpdump` (SYN без ответа), `iptables -L -n -v` | удалить правило |
| Сервис на 127.0.0.1 | Локально работает, снаружи — refused/timeout | `ss -tulpn` | привязать к `0.0.0.0` |
| Интерфейс down | Пропали маршруты и связь с подсетью | `ip -br link`, `ip route` | `ip link set eth1 up` |

</details>

**C10. Отчёт об инциденте.** По итогам C9 оформи короткий post-mortem по одной из поломок:
что наблюдалось, как искали, что нашли, как починили, как предотвратить.

---

### Блок D. Инциденты

**D1.** Пользователи жалуются: «сайт не открывается». С твоего сервера `curl` работает.
С чего начнёшь и какие вопросы задашь?

<details><summary>Ответ</summary>

Уточнить: у всех или у части пользователей, из какой сети/устройства, какой именно URL,
какая ошибка на экране, когда началось, что менялось. Затем: проверить внешний мониторинг,
резолв DNS с публичных резолверов (`dig @1.1.1.1`), доступность с внешней точки
(другой VPS, мобильный интернет), логи балансировщика и приложения, CDN/WAF, сертификат,
недавние деплои. Разделить «проблема на стороне сервиса» и «проблема на стороне клиента/провайдера».

</details>

**D2.** `curl` к API возвращает `Connection timed out`, а `ping` до хоста работает. Гипотезы?

<details><summary>Ответ</summary>

Пакеты до порта не доходят или ответы отбрасываются: firewall/Security Group с DROP,
сервис слушает не тот интерфейс, неверный порт, маршрут возврата отсутствует (асимметрия),
переполнена таблица conntrack, или проблема MTU на этапе передачи данных. Проверка:
`ss -tulpn` на сервере, `tcpdump` на обеих сторонах (видно ли SYN и уходит ли SYN-ACK),
правила firewall, облачные группы безопасности.

</details>

**D3.** `curl` возвращает `Connection refused` мгновенно. Что это означает и что проверять?

<details><summary>Ответ</summary>

До хоста дошли, но на этом порту никто не слушает (или firewall отвечает REJECT/RST).
Проверять: запущен ли сервис (`systemctl status`), `ss -tulpn` (слушает ли и на каком адресе),
правильный ли порт, нет ли правила REJECT, не упал ли процесс после старта (`journalctl -u`).

</details>

**D4.** Приложение периодически теряет соединения с БД, в tcpdump видны пакеты `[R]` со стороны
БД-сервера. Что это может быть?

<details><summary>Ответ</summary>

Возможные причины: сервер БД разрывает простаивающие соединения по таймауту
(`idle_in_transaction_session_timeout`, `wait_timeout`), исчерпан лимит соединений
(`max_connections`) — БД шлёт RST, NAT/файрвол по пути «забывает» сессию (conntrack timeout)
и отвечает RST, балансировщик рвёт соединения. Лечится keep-alive/пулом соединений,
настройкой таймаутов с обеих сторон, увеличением лимитов, проверкой conntrack.

</details>

**D5.** После деплоя приложение доступно локально (`curl localhost:8080` работает),
но недоступно с другого сервера. Три возможные причины в порядке проверки.

<details><summary>Ответ</summary>

(1) Сервис привязан к `127.0.0.1` вместо `0.0.0.0` — `ss -tulpn`.
(2) Локальный firewall блокирует порт — `iptables -L -n -v` / `ufw status`.
(3) Внешний firewall/Security Group провайдера или маршрутизация между подсетями.
Проверять именно в таком порядке — от самого частого к самому редкому.

</details>

**D6.** Соединения устанавливаются, но передача больших файлов зависает; мелкие запросы проходят.
Диагноз и как проверить?

<details><summary>Ответ</summary>

Классическая проблема MTU/фрагментации (особенно за VPN, в overlay-сетях, туннелях):
handshake и мелкие пакеты проходят, а передача данных с полноразмерными сегментами зависает,
потому что ICMP «Fragmentation Needed» блокируется. Проверка: `ping -M do -s <размер>` подбором,
`tracepath`, `tcpdump` (видно повторные передачи одного и того же сегмента).
Решение: уменьшить MTU, включить MSS clamping, разрешить ICMP type 3 code 4.

</details>

**D7.** `mtr` показывает 100% потерь на всех хопах, кроме последнего, где 0%.
Есть ли проблема в сети?

<details><summary>Ответ</summary>

Нет. Если конечный хоп отвечает без потерь, транзит работает. 100% «потерь» на
промежуточных хопах означает, что они просто не отвечают на зонды (политика/фильтрация),
что типично для магистральных маршрутизаторов.

</details>

**D8.** Сервис работает медленно. `curl -w` показывает `time_namelookup: 5.0s`,
остальные фазы быстрые. Где проблема?

<details><summary>Ответ</summary>

Проблема в DNS: разрешение имени занимает 5 секунд. Проверять: доступность и время
ответа настроенных резолверов (`dig @<dns> <host>` с замером), нет ли недоступного первого
сервера в списке (таймаут и переход ко второму), корректность `search`-доменов (лишние суффиксы
дают несколько неудачных запросов), работу `systemd-resolved`, IPv6-резолв (AAAA) при
неработающем IPv6. Быстрый обход — `curl -4`, правильное решение — исправить конфигурацию DNS.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Сайт не открывается. Твои действия по шагам?

<details><summary>Ответ</summary>

Снизу вверх: интерфейс и адрес → маршрут и шлюз → интернет по IP → DNS → порт → HTTP/TLS →
логи приложения; на каждом шаге фиксировать результат.

</details>

**2.** Как проверить, доступен ли порт на удалённом сервере?

<details><summary>Ответ</summary>

`nc -zv host port`, `timeout 2 bash -c '</dev/tcp/host/port'`, `curl -v telnet://host:port`,
`nmap -p port host`.

</details>

**3.** Чем DROP отличается от REJECT?

<details><summary>Ответ</summary>

DROP молча отбрасывает пакет (клиент ждёт таймаута), REJECT отправляет отказ
(ICMP unreachable или TCP RST) — клиент получает ошибку мгновенно.

</details>

**4.** Что такое ICMP и зачем он нужен?

<details><summary>Ответ</summary>

Служебный протокол L3 для диагностики и сообщений об ошибках: ping, traceroute,
уведомления о недостижимости и необходимости фрагментации (Path MTU Discovery).

</details>

**5.** Как понять, где именно теряются пакеты?

<details><summary>Ответ</summary>

`mtr` длительным прогоном: смотреть потери на последнем хопе и хоп, с которого начинается
устойчивый рост задержек/потерь; дополнительно — проверка с другой точки и в обратную сторону.

</details>

**6.** Сервис слушает порт, но недоступен снаружи. Что проверишь?

<details><summary>Ответ</summary>

Слушает ли на `0.0.0.0` (`ss -tulpn`), локальный firewall, внешний firewall/Security Group,
доходят ли пакеты (`tcpdump`), правильный ли порт и протокол.

</details>

**7.** Как посмотреть, доходят ли пакеты до сервера?

<details><summary>Ответ</summary>

`sudo tcpdump -i any -n 'host <клиент> and port <порт>'` на сервере — видно, приходят ли SYN
и уходят ли ответы.

</details>

**8.** Как измерить, какая часть HTTP-запроса тормозит?

<details><summary>Ответ</summary>

`curl -w` с форматом, выводящим `time_namelookup`, `time_connect`, `time_appconnect`,
`time_starttransfer`, `time_total`.

</details>

---

## 🎯 Чек-лист

- [ ] Знаю алгоритм «снизу вверх» наизусть и не прыгаю по уровням
- [ ] Различаю `Network unreachable` / `Host unreachable` / таймаут / refused
- [ ] Понимаю, что потери на промежуточных хопах mtr — не диагноз
- [ ] Проверяю `ss -tulpn` на предмет `127.0.0.1` vs `0.0.0.0`
- [ ] Отличаю DROP от REJECT по поведению клиента
- [ ] Умею снять и прочитать дамп tcpdump
- [ ] Разбиваю HTTP-запрос на фазы через `curl -w`
- [ ] Написал и проверил `net_diag.sh`
