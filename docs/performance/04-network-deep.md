---
title: "04. Сеть глубже: очереди, TIMEWAIT, conntrack и дропы"
description: "Блок → Deep Linux Troubleshooting & Performance → тема 04. Опирается на"
---

# 04. Сеть глубже: очереди, TIME_WAIT, conntrack и дропы

> Блок → Deep Linux Troubleshooting & Performance → тема 04. Опирается на
> [../Network/04_l4_tcp_udp.md](/network/04-l4-tcp-udp) (состояния TCP, TIME_WAIT vs CLOSE_WAIT, эфемерные порты),
> [../Network/09_net_tools.md](/network/09-net-tools) (ss, nc, curl),
> [../Network/10_tcpdump_wireshark.md](/network/10-tcpdump-wireshark) (фильтры, чтение вывода, ротация),
> [../Network/11_firewall_iptables.md](/network/11-firewall-iptables) (netfilter, conntrack),
> [../Linux/12_kernel.md](/linux/12-kernel) (sysctl, ulimit) и [01_methodology.md](/performance/01-methodology) (USE для сети).
>
> **После темы ты умеешь:** читать `ss -ti` по полям (rtt, cwnd, retrans), считать предел
> эфемерных портов, находить переполнение SYN- и accept-очереди по счётчикам ядра, ловить
> ретрансмиты, диагностировать переполненный conntrack и утечку дескрипторов, разбирать
> дамп через tshark, находить дропы на NIC и в ядре, подозревать DNS и понимать, какие
> sysctl трогать нельзя.

---

## 🗺️ Карта темы

```text
 провод ─► NIC ring buffer ─► softirq / backlog ─► netfilter + conntrack ─► TCP ─────────► приложение
           ip -s link          /proc/net/          conntrack -S            │
           ethtool -S          softnet_stat        dmesg «table full»      │ SYN ──► SYN queue (SYN-RECV)
           (rx_missed/drop)    (netdev_max_backlog)                        │           │ ACK
                                                                           │           ▼
                                                                           │    accept queue ──► accept()
                                                                           │    ss -lnt Recv-Q/Send-Q
                                                                           │    nstat ListenOverflows
                                                                           ▼
                                               сокет: rtt, cwnd, retrans (ss -ti), fd (ulimit -n)
 исходящие: эфемерный порт (ip_local_port_range) ─► TIME_WAIT 60 с на закрывшей стороне
 + DNS перед каждым «новым» соединением (resolv.conf, ndots, таймауты)
```text
Каждая ступень может молча выбросить пакет. Приложение увидит только таймаут или
«медленно». Задача темы — знать, какой счётчик на какой ступени растёт.

---

## 1. USE для сети и «дельта-режим» счётчиков

| | Метрика | Команда |
|---|---------|---------|
| **U** | Пропускная способность интерфейса, число соединений | `sar -n DEV 1`, `ss -s` |
| **S** | Очереди: accept queue, SYN backlog, softnet backlog, TIME_WAIT, conntrack заполнен | `ss -lnt`, `nstat`, `/proc/net/softnet_stat`, `conntrack -C` |
| **E** | Ретрансмиты, дропы, RST, ошибки интерфейса | `nstat`, `sar -n EDEV,ETCP 1`, `ip -s link`, `ethtool -S` |

Почти все сетевые счётчики ядра — **накопительные с момента загрузки**. «ListenOverflows 3412»
ничего не значит, пока не видно, растёт ли он сейчас. `nstat` умеет показывать приращения:

```bash
nstat -az 'TcpExtListen*'       # абсолютные значения (-a) включая нули (-z), по шаблону
nstat -n                        # запомнить текущие значения, ничего не печатать
sleep 10; nstat                 # приращения за эти 10 секунд (только ненулевые)
```text
---

## 2. `ss` глубже: что внутри соединения

Базовые флаги и состояния — в [../Network/04_l4_tcp_udp.md](/network/04-l4-tcp-udp). Здесь — поля
`-i` и приёмы для разбора.

```bash
ss -s                                    # сводка: сколько estab, timewait, orphaned
ss -tanp                                 # все TCP, с процессами
ss -tinp state established '( dport = :5432 )'    # внутренности соединений к PostgreSQL
ss -tino                                 # + таймеры: timer:(on,…) = идёт ретрансмит
ss -tm                                   # память сокетов: skmem:(…,d&lt;drops&gt;)
ss -tan | awk 'NR>1 {print $1}' | sort | uniq -c | sort -rn   # распределение по состояниям
```text
```text
# пример вывода ss -s
Total: 1369
TCP:   545 (estab 104, closed 397, orphaned 1, timewait 65)
```text
```text
# пример вывода ss -tin (одно соединение с потерями, разбито на строки для чтения)
ESTAB 0 0 10.0.2.15:44120 10.0.2.20:5432
   cubic wscale:7,7 rto:412 backoff:1 rtt:205.3/48.1 mss:1448 cwnd:4 ssthresh:7
   bytes_sent:1822030 bytes_retrans:94120 bytes_acked:1726410
   send 225645bps delivery_rate 181200bps busy:18204ms unacked:3 retrans:1/65 lost:1 minrtt:0.412
```text
| Поле | Что значит | Тревожный признак |
|------|-----------|-------------------|
| `rtt:205.3/48.1` | Сглаженный RTT / разброс, мс | RTT ≫ `minrtt` → очереди на пути (bufferbloat) или перегруз получателя |
| `minrtt` | Минимальный наблюдённый RTT | «Идеальная» задержка пути |
| `rto`, `backoff` | Таймаут ретрансмита, мс; сколько раз его удваивали | `backoff` > 0 — сейчас идут повторы по таймауту |
| `cwnd`, `ssthresh` | Окно перегрузки и порог slow start, в сегментах | Маленький `cwnd` на долгоживущем соединении — были потери |
| `retrans:1/65` | Сейчас не подтверждено повторов / всего повторов за жизнь | Растущий второй счётчик = потери на пути |
| `bytes_retrans` | Сколько байт отправлено повторно | Доля от `bytes_sent` > 1% — плохо |
| `unacked`, `lost` | Сегменты в полёте без ACK / помеченные потерянными | `lost` > 0 — прямо сейчас теряем |
| `send`, `delivery_rate` | Расчётная и фактическая скорость | — |
| `app_limited` | Скорость ограничило приложение (нечего слать) | Сеть ни при чём, медленно само приложение |
| `busy`, `rwnd_limited` | Время, когда слали; когда упирались в окно **получателя** | `rwnd_limited` велик → получатель не успевает читать |

⭐ Разделение ответственности: растут `retrans`/`lost` и `rtt` → проблема пути; `app_limited`
или большой `Recv-Q` у получателя → проблема приложения. Это ответ на вечный спор
«сеть или код».

---

## 3. TIME_WAIT и исчерпание эфемерных портов

Что такое TIME_WAIT и почему он нормален — в [../Network/04_l4_tcp_udp.md](/network/04-l4-tcp-udp).
Здесь — арифметика и лечение.

Соединение уникально по четвёрке `(src IP, src port, dst IP, dst port)`. Для исходящих
соединений **к одному и тому же** `dst IP:port` с одного `src IP` меняется только src port:

```text
 ip_local_port_range = 32768 60999  →  60999 − 32768 + 1 = 28 232 порта
 TIME_WAIT длится 60 с (константа ядра, sysctl не меняет)
 предел новых соединений к ОДНОМУ backend:  28 232 / 60 ≈ 470 в секунду
```text
Сервис делает 800 коротких HTTP-запросов/с к одному upstream без keep-alive — через
минуту `connect()` начнёт падать с `EADDRNOTAVAIL` («Cannot assign requested address»).
TIME_WAIT живёт на стороне, **которая закрыла соединение первой**: у клиента, если закрывает
клиент, — там и кончаются порты.

```bash
ss -tan state time-wait | wc -l                                  # сколько TIME_WAIT
ss -tan state time-wait | awk 'NR>1 {print $4}' | sort | uniq -c | sort -rn | head   # к кому
sysctl net.ipv4.ip_local_port_range net.ipv4.tcp_tw_reuse net.ipv4.tcp_max_tw_buckets
```text
| Лечение | Когда |
|---------|-------|
| ⭐ Keep-alive и пулы соединений в клиенте (HTTP, БД) | Всегда первое: нет новых соединений — нет TIME_WAIT |
| `net.ipv4.tcp_tw_reuse=1` | Разрешает переиспользовать TIME_WAIT для **исходящих** соединений, когда это безопасно (нужны TCP timestamps). По умолчанию `2` — только для loopback |
| Расширить `ip_local_port_range` (например, `10240 65535`) | Не забыть исключить порты своих сервисов: `net.ipv4.ip_local_reserved_ports` |
| Несколько src IP или dst IP/портов у upstream | Прокси, NAT-шлюзы: каждая пара даёт свои 28k |

> 🔴 `net.ipv4.tcp_tw_recycle` — **никогда**. Он ломал соединения клиентов за NAT и был
> удалён из ядра в 4.12. Если «гайд по тюнингу» его советует — гайд устарел лет на восемь.

> ⚠️ `net.ipv4.tcp_fin_timeout` **не** укорачивает TIME_WAIT. Он задаёт, сколько
> «осиротевшее» соединение живёт в FIN-WAIT-2. Путаница кочует из статьи в статью.

---

## 4. SYN queue и accept queue: соединения теряются до `accept()`

```text
 клиент                        ядро сервера                                 приложение
   SYN ───────────────► SYN queue (SYN-RECV)  предел: tcp_max_syn_backlog
                        переполнена → syncookies (tcp_syncookies=1) или drop
   ◄──────────── SYN-ACK
   ACK ───────────────► accept queue (готовые ESTAB)  предел: min(backlog из listen(), somaxconn)
                        переполнена → ACK выброшен, ListenOverflows++ ; SYN выброшены, ListenDrops++
                                              │ accept()
                                              ▼
                                         воркер приложения
```text
Для **LISTEN**-сокета колонки `ss` означают другое, чем для соединения:

```bash
ss -lnt '( sport = :8080 )'
```text
```text
# пример вывода: приложение не успевает принимать соединения
State  Recv-Q Send-Q Local Address:Port Peer Address:Port
LISTEN 129    128          0.0.0.0:8080      0.0.0.0:*
```text
`Recv-Q` — сколько установленных соединений **сейчас** ждут `accept()`; `Send-Q` — размер
очереди (backlog). `Recv-Q` у потолка = очередь переполнена.

```bash
nstat -az 'TcpExtListen*'          # TcpExtListenOverflows, TcpExtListenDrops (накопительно)
nstat -n; sleep 10; nstat 'TcpExtListen*'   # растут ли прямо сейчас
dmesg -T | grep -i 'SYN flooding'  # «Possible SYN flooding on port 8080. Sending cookies.»
sysctl net.core.somaxconn net.ipv4.tcp_max_syn_backlog net.ipv4.tcp_syncookies net.ipv4.tcp_abort_on_overflow
sudo tcpsynbl-bpfcc                # гистограмма длины очереди у слушающих сокетов (тема 07)
```text
| Счётчик / сообщение | Что значит |
|---------------------|-----------|
| `TcpExtListenOverflows` растёт | Accept queue полна: приложение медленно вызывает `accept()` |
| `TcpExtListenDrops` растёт | Все отброшенные на слушающем сокете (включает overflows) |
| `Possible SYN flooding … Sending cookies` | SYN queue переполнена: реальный флуд **или** всплеск нагрузки при маленьком backlog |

Параметры (ядро 7.2, стенд):

| sysctl | Значение | Замечание |
|--------|----------|-----------|
| `net.core.somaxconn` | 4096 | С ядра 5.4; раньше было 128. Потолок для `listen(backlog)` |
| `net.ipv4.tcp_max_syn_backlog` | 2048 | Зависит от RAM — проверь у себя |
| `net.ipv4.tcp_syncookies` | 1 | Не выключать: защита от SYN-флуда |
| `net.ipv4.tcp_abort_on_overflow` | 0 | 1 — слать RST при переполнении вместо молчаливого дропа. Обычно оставляют 0 |

⭐ Главное: переполнение accept queue — почти всегда **симптом медленного приложения**
(заблокированный event loop, мало воркеров, долгий GC), а не «маленький somaxconn».
Поднимать очередь имеет смысл для коротких всплесков — и тогда нужно поднять **оба**:
backlog в приложении (например, `listen 80 backlog=4096;` в nginx) и `somaxconn`.
Приложение, которое вызывает `listen(fd, 128)`, получит 128, какой бы ни был sysctl.

Симптом у клиента: при `tcp_abort_on_overflow=0` сервер молча выбрасывает финальный ACK,
клиент считает соединение установленным, а сервер повторяет SYN-ACK. Отсюда задержки
на 1, 3, 7 секунд у части запросов без единой ошибки в логах сервера.

---

## 5. Ретрансмиты: сеть теряет или сервер не отвечает

```bash
nstat -az TcpOutSegs TcpRetransSegs TcpExtTCPSynRetrans TcpExtTCPTimeouts TcpExtTCPLostRetransmit
sar -n TCP,ETCP 1                  # retrans/s в динамике; история: sar -n ETCP -f /var/log/sysstat/saDD
sudo tcpretrans-bpfcc              # каждый ретрансмит: кто, куда, в каком состоянии (тема 07)
```text
```text
# пример вывода sudo tcpretrans-bpfcc
TIME     PID     IP LADDR:LPORT          T> RADDR:RPORT          STATE
14:02:11 0       4  10.0.2.15:44120      R> 10.0.2.20:5432       ESTABLISHED
14:02:12 0       4  10.0.2.15:51230      R> 10.0.2.30:443        SYN_SENT
```text
| Счётчик | Что показывает |
|---------|----------------|
| `TcpRetransSegs / TcpOutSegs` | Доля повторов. Долгосрочно > 1% — повод разбираться, > 5% — плохо |
| `TcpExtTCPSynRetrans` | Повторы SYN: сервер **не ответил** на попытку соединения |
| `TcpExtTCPTimeouts` | Повторы по RTO (самые дорогие: сотни мс–секунды ожидания) |
| `TcpExtTCPLostRetransmit` | Потерялся уже повторный сегмент |

Ретрансмит SYN в `SYN_SENT` (как во второй строке) — не потеря «в интернете», а чаще всего:
переполненная очередь на сервере, conntrack table full, файрвол с DROP, мёртвый backend
за балансировщиком. Характерный след — задержки подключения ровно 1 с, 3 с, 7 с (удвоение RTO
от 1 с).

---

## 6. conntrack: таблица полна — пакеты молча выбрасываются

Основы conntrack и stateful-правил — в [../Network/11_firewall_iptables.md](/network/11-firewall-iptables).
Таблица есть на любом хосте, где загружен `nf_conntrack`: NAT, Docker, Kubernetes
(kube-proxy в режиме iptables), ufw, правила с `-m conntrack`.

```bash
dmesg -T | grep -i conntrack            # nf_conntrack: nf_conntrack: table full, dropping packet
sudo conntrack -C                       # сколько записей сейчас
sysctl net.netfilter.nf_conntrack_count net.netfilter.nf_conntrack_max net.netfilter.nf_conntrack_buckets
sudo conntrack -S                       # статистика по CPU
sudo conntrack -L -o extended 2>/dev/null | awk '{print $3}' | sort | uniq -c | sort -rn   # по протоколам
sudo conntrack -L -p tcp 2>/dev/null | awk '{print $4}' | sort | uniq -c | sort -rn      # по состояниям TCP
```text
```text
# пример вывода sudo conntrack -S (таблица переполнена)
cpu=0   found=0 invalid=1204 insert=0 insert_failed=0 drop=18233 early_drop=5120 error=0 search_restart=41
cpu=1   found=0 invalid=988  insert=0 insert_failed=0 drop=17904 early_drop=4987 error=0 search_restart=37
```text
| Поле | Смысл |
|------|-------|
| `drop` | Новое соединение выброшено: места для записи нет |
| `early_drop` | Чтобы принять новое, ядро вытеснило запись без ответного трафика |
| `insert_failed` | Не удалось вставить запись (гонки, часто с UDP/DNS) |
| `invalid` | Пакет не подходит ни к одному соединению и не создаёт новое |
| `found`, `insert` | Всегда 0, оставлены для совместимости |

Симптомы: у части **новых** соединений таймауты (SYN не доходит), существующие работают,
в логах приложений пусто, CPU и память в норме. `nf_conntrack_count` упирается в `max`.

| sysctl | Значение (ядро 7.2) | Замечание |
|--------|---------------------|-----------|
| `nf_conntrack_max` | 262144 | По умолчанию = `nf_conntrack_buckets`, а тот считается от RAM. На VM стенда проверь своё |
| `nf_conntrack_buckets` | 262144 | Хеш-таблица; при большом `max` поднимают и её |
| `nf_conntrack_tcp_timeout_established` | 432000 (5 суток) | Мёртвые соединения без FIN висят сутками |
| `nf_conntrack_tcp_timeout_time_wait` | 120 | |
| `nf_conntrack_udp_timeout` / `_stream` | 30 / 120 | DNS-трафик быстро забивает таблицу |

Лечение по порядку:
1. Понять, **что** заполнило таблицу (протокол, состояния, адреса) — часто это один источник:
   DNS-флуд, сканер, клиент без keep-alive.
2. Поднять `nf_conntrack_max` (каждая запись — порядка 300+ байт ядра; 1 млн записей ≈ сотни МБ).
3. Сократить таймауты там, где это безопасно (например, `established` до часов, если нет
   долгоживущих соединений без keep-alive).
4. Не отслеживать то, что не нужно: `iptables -t raw -A PREROUTING -p udp --dport 53 -j CT --notrack`
   (и такое же правило в `OUTPUT`) — для высоконагруженного DNS-сервера.

> ⚠️ Флуд conntrack для воспроизведения — только на VM стенда: лаба 4 в
> [08_practice_labs.md](/softskills/08-practice-labs) уменьшает `nf_conntrack_max` до пары сотен и
> забивает его соединениями.

---

## 7. Файловые дескрипторы: «Too many open files»

Каждый сокет — это fd. Утечка сокетов = утечка fd = отказ `accept()`.

```bash
ls /proc/1234/fd | wc -l                          # сколько открыто сейчас
grep 'Max open files' /proc/1234/limits           # soft и hard лимит процесса
sudo ls -l /proc/1234/fd | awk '{print $NF}' | sed -E 's/:\[.*//' | sort | uniq -c | sort -rn
cat /proc/sys/fs/file-nr                          # выделено / 0 / fs.file-max (вся система)
systemctl show app -p LimitNOFILE -p LimitNOFILESoft
```text
```text
# пример: утечка сокетов
  4012 socket
    38 /opt/app/lib/…
     5 pipe
$ ss -tanp | grep 'pid=1234' | awk '{print $1}' | sort | uniq -c
   3980 CLOSE-WAIT
     24 ESTAB
```text
Тысячи сокетов в `CLOSE-WAIT` у процесса — приложение не закрывает соединения
(классика из [../Network/04_l4_tcp_udp.md](/network/04-l4-tcp-udp)). Число fd растёт, пока не
упрётся в лимит.

| Ошибка | errno | Что кончилось |
|--------|-------|---------------|
| `Too many open files` | `EMFILE` | Лимит **процесса** (`RLIMIT_NOFILE`, `ulimit -n`) |
| `Too many open files in system` | `ENFILE` | Лимит **системы** (`fs.file-max`) — редкость |

Лимиты сервисов в systemd: по умолчанию soft **1024**, hard **524288**. Часть приложений
сами поднимают soft до hard при старте, часть — нет. Постоянно — drop-in:
```bash
sudo systemctl edit app          # [Service]
                                 # LimitNOFILE=65536
sudo systemctl restart app && grep 'open files' /proc/$(systemctl show -p MainPID --value app)/limits
```text
`/etc/security/limits.conf` на systemd-сервисы **не действует** — он для PAM-сессий
(логин по SSH), см. [../Linux/12_kernel.md](/linux/12-kernel).

> ⭐ Поднять лимит — лечение симптома. Если fd растут линейно со временем — это утечка,
> и лимит просто отложит падение. Покажи разработчикам график числа fd и `CLOSE-WAIT`.

---

## 8. tcpdump + tshark: доказательство на уровне пакетов

Базовые фильтры и ротация — в [../Network/10_tcpdump_wireshark.md](/network/10-tcpdump-wireshark).
Здесь — фильтры для инцидентов и анализ дампа без GUI.

```bash
# только «чистые» SYN (без ACK), устойчиво к ECN-флагам
sudo tcpdump -ni any 'tcp[tcpflags] & (tcp-syn|tcp-ack) == tcp-syn and dst port 8080'
# SYN-ACK — ответы сервера
sudo tcpdump -ni any 'tcp[tcpflags] & (tcp-syn|tcp-ack) == (tcp-syn|tcp-ack) and src port 8080'
# кто рвёт соединения
sudo tcpdump -ni any 'tcp[tcpflags] & tcp-rst != 0'
# в файл, только заголовки, ограниченно по числу пакетов
sudo tcpdump -ni any -s 128 -c 200000 -w /tmp/incident.pcap 'port 8080'
```text
Разбор дампа:
```bash
tshark -r /tmp/incident.pcap -q -z conv,tcp | head -20                       # соединения, байты, длительность
tshark -r /tmp/incident.pcap -Y 'tcp.analysis.retransmission' | wc -l        # ретрансмиты
tshark -r /tmp/incident.pcap -Y 'tcp.flags.syn==1 && tcp.flags.ack==0' | wc -l   # попытки соединений
tshark -r /tmp/incident.pcap -Y 'tcp.flags.syn==1 && tcp.flags.ack==1' | wc -l   # ответы на них
tshark -r /tmp/incident.pcap -Y 'tcp.flags.syn==1 && tcp.flags.ack==0 && tcp.analysis.retransmission' \
  -T fields -e ip.dst -e tcp.dstport | sort | uniq -c | sort -rn             # куда SYN уходят без ответа
tshark -r /tmp/incident.pcap -Y 'tcp.flags.reset==1' -T fields -e ip.src | sort | uniq -c   # кто шлёт RST
tshark -r /tmp/incident.pcap -Y 'tcp.analysis.zero_window'                   # получатель не читает
tshark -r /tmp/incident.pcap -Y 'tcp.analysis.initial_rtt' \
  -T fields -e tcp.stream -e tcp.analysis.initial_rtt | sort -u -k1,1n | head   # iRTT хендшейка по соединениям
```text
Как читать: SYN много, SYN-ACK заметно меньше, SYN-ретрансмиты к одному адресу — сервер
не отвечает (очередь, conntrack, файрвол, сервис мёртв). Снимай дамп **с обеих сторон**:
если SYN ушёл с клиента, но не пришёл на сервер — виноват путь (файрвол, SG, NAT); если
пришёл, но SYN-ACK нет — сам сервер.

---

## 9. Дропы на NIC и в ядре

```bash
ip -s link show eth0                        # RX: errors dropped missed; TX: errors dropped
sar -n EDEV 1                               # rxerr/s txerr/s rxdrop/s txdrop/s rxfifo/s …
sudo ethtool -S eth0 | grep -iE 'drop|miss|err|fifo'    # счётчики драйвера (имена зависят от драйвера)
sudo ethtool -g eth0                        # размеры ring buffer: текущие и максимум
cat /proc/net/softnet_stat                  # строка на CPU, hex
sudo tcpdrop-bpfcc                          # где в ядре выброшен TCP-пакет, со стеком (тема 07)
```text
```text
# пример вывода ip -s link show eth0
2: eth0: &lt;BROADCAST,MULTICAST,UP,LOWER_UP&gt; mtu 1500 qdisc fq_codel state UP mode DEFAULT group default qlen 1000
    RX:  bytes  packets errors dropped  missed   mcast
    9876543210 8123456      0   41230       0     120
    TX:  bytes  packets errors dropped carrier collsns
    1234567890 5432109      0       0       0       0
```text
`/proc/net/softnet_stat`: по строке на CPU, значения в hex. Колонка 1 — обработано пакетов,
**колонка 2 — выброшено**, потому что переполнилась очередь backlog
(`net.core.netdev_max_backlog`, по умолчанию 1000), **колонка 3 — time_squeeze**: softirq не
успел разобрать очередь за отведённый бюджет (`net.core.netdev_budget`).

| Где растёт | Что значит | Куда смотреть |
|------------|-----------|---------------|
| `missed` / `rx_missed_errors` / `rx_fifo_errors` | Ring buffer NIC переполнен до того, как ядро забрало пакеты | `ethtool -G eth0 rx &lt;больше&gt;`, распределение прерываний по CPU |
| softnet колонка 2 | Очередь backlog полна | `netdev_max_backlog`, RPS/RSS |
| softnet колонка 3 | Softirq не успевает | CPU `%soft` в `mpstat`, `netdev_budget` |
| `dropped` в `ip -s link` при нуле выше | Ядро выбросило пакет выше драйвера (нет протокола, фильтр, …) | `tcpdrop-bpfcc`, `nstat` |
| `skmem:(…,d&lt;N&gt;)` в `ss -tm` | Дропы на уровне конкретного сокета (буфер полон) | Приложение не читает, буферы сокета |

---

## 10. DNS — скрытый виновник latency

DNS резолвится **до** соединения и в метриках сервиса часто спрятан внутри «времени
запроса к upstream». Признаки:
- медленный **первый** запрос, остальные быстрые (кэш);
- задержки ровно 5 с, 10 с — таймаут резолвера (`options timeout:5` по умолчанию) и повтор;
- в Kubernetes `ndots:5`: имя `api.example.com` сначала ищется по всем search-доменам
  (`api.example.com.default.svc.cluster.local` и т.д.) — несколько лишних запросов на каждый вызов.

```bash
dig api.example.com | grep 'Query time'            # ;; Query time: 9 msec
curl -o /dev/null -s -w 'dns:%{time_namelookup} connect:%{time_connect} total:%{time_total}\n' https://api.example.com
sudo resolvectl statistics                         # попадания/промахи кэша systemd-resolved
sudo gethostlatency-bpfcc                          # задержка getaddrinfo()/gethostbyname() по процессам
sudo tcpdump -ni any port 53                       # сколько запросов реально уходит
```text
```text
# пример вывода sudo gethostlatency-bpfcc
TIME      PID     COMM                  LATms HOST
14:10:02  2210    java                5012.33 billing.internal
14:10:03  3117    curl                   2.41 api.example.com
```text
5 секунд на `billing.internal` — первый DNS-сервер не отвечает, резолвер ждёт таймаут и
идёт ко второму. `gethostlatency` видит только вызовы через libc; Go с собственным
резолвером так не поймать — смотри `tcpdump port 53`.

Лечение: кэширующий резолвер на хосте/ноде (systemd-resolved, NodeLocal DNSCache в k8s),
FQDN с точкой в конце (`billing.internal.`) или меньше `ndots`, рабочие DNS-серверы первыми
в списке, пулы соединений (меньше резолвов).

---

## 11. sysctl: когда трогать, а когда нет

| Параметр | Трогать, если… | Не трогать / осторожно |
|----------|---------------|------------------------|
| `net.core.somaxconn` + backlog приложения | `ListenOverflows` растут на коротких всплесках | Если приложение просто медленное — только отсрочит |
| `net.ipv4.ip_local_port_range` | Доказано исчерпание портов (`EADDRNOTAVAIL`) | Не залезть на порты своих сервисов |
| `net.ipv4.tcp_tw_reuse=1` | Много исходящих коротких соединений, пул внедрить нельзя | — |
| `net.netfilter.nf_conntrack_max` | `table full` в `dmesg`, count упирается в max | Сначала понять, кто заполняет |
| `net.core.netdev_max_backlog` | Растёт колонка 2 в softnet_stat | — |
| `net.ipv4.tcp_tw_recycle` | — | 🔴 Удалён в 4.12, ломал NAT |
| `net.ipv4.tcp_syncookies=0` | — | 🔴 Снимает защиту от SYN-флуда |
| `tcp_rmem`/`tcp_wmem` «побольше» | Доказанная нехватка на длинных толстых каналах (высокий BDP) | Автотюнинг буферов обычно справляется |
| `net.ipv4.tcp_fin_timeout` «чтобы убрать TIME_WAIT» | — | Не влияет на TIME_WAIT вообще |

Правила: сначала счётчик, который доказывает проблему; одно изменение за раз; замер до и
после; постоянные значения — в `/etc/sysctl.d/*.conf` с комментарием, **зачем**
([../Linux/12_kernel.md](/linux/12-kernel)). Копипаста «100 sysctl для highload» — источник
инцидентов, а не их лечение.

---

## 12. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| Смотреть абсолютные счётчики `netstat -s`/`nstat -a` | Накоплено с загрузки, неясно, растёт ли | `nstat -n; sleep 10; nstat` — дельта |
| Поднять `somaxconn` и считать задачу решённой | `listen(fd, 128)` в приложении всё равно даст 128 | Поднять backlog в приложении и sysctl вместе |
| Лечить `ListenOverflows` очередью | Приложение медленно принимает | Воркеры, event loop, профилирование (темы 02, 05) |
| `tcp_tw_recycle=1` из старой статьи | Параметра нет с 4.12, раньше ломал NAT | Keep-alive, `tcp_tw_reuse` |
| `tcp_fin_timeout` против TIME_WAIT | Это FIN-WAIT-2 | TIME_WAIT = 60 с всегда |
| Лимит fd в `/etc/security/limits.conf` для сервиса | systemd его не читает | `LimitNOFILE=` в юните |
| Поднять `LimitNOFILE` при утечке | Отложили падение | Найти утечку: `CLOSE-WAIT`, рост fd |
| `conntrack_max ×10` без анализа | Кто-то всё равно забьёт таблицу, плюс память | Найти источник, таймауты, NOTRACK |
| Дамп только на одной стороне | Не понять, где пропал пакет | Две точки съёма |
| `tcpdump` без фильтра и `-c` на проде | Диск и CPU | Фильтр, `-s 128`, `-c`, ротация |
| Не подозревать DNS | 5 секунд «где-то в upstream» | `time_namelookup`, `gethostlatency` |

---

## 💼 Как это в DevOps

- Алерты на сеть — по счётчикам ядра из node_exporter: `node_netstat_TcpExt_ListenOverflows`,
  `node_netstat_Tcp_RetransSegs`, `node_nf_conntrack_entries / node_nf_conntrack_entries_limit`,
  `node_sockstat_TCP_tw`, `node_filefd_allocated` — и всегда через `rate()`.
- На нодах Kubernetes conntrack заполняется DNS-трафиком и kube-proxy: `table full` на ноде
  выглядит как «случайные таймауты между подами». NodeLocal DNSCache и `nf_conntrack_max`
  — стандартные меры.
- Исчерпание эфемерных портов — типичная авария прокси, NAT-шлюзов и CI-раннеров, которые
  дёргают API без keep-alive.
- `CLOSE-WAIT` + растущие fd — готовый баг-репорт разработчикам с графиком и `ss -tanp`.
- Спор «это сеть» vs «это приложение» решают `ss -ti` (`retrans`, `app_limited`,
  `rwnd_limited`) и дамп с двух сторон.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Сводка по сокетам | `ss -s` |
| Внутренности соединений | `ss -tinp state established '( dport = :5432 )'` |
| Распределение по состояниям | `ss -tan \| awk 'NR>1{print $1}' \| sort \| uniq -c` |
| TIME_WAIT к кому | `ss -tan state time-wait \| awk 'NR>1{print $4}' \| sort \| uniq -c` |
| Очередь слушающего сокета | `ss -lnt` → `Recv-Q` (сейчас) / `Send-Q` (предел) |
| Дельта счётчиков | `nstat -n; sleep 10; nstat` |
| Переполнение accept queue | `nstat -az 'TcpExtListen*'` |
| Ретрансмиты | `nstat -az TcpRetransSegs TcpExtTCPSynRetrans`, `sar -n ETCP 1`, `tcpretrans-bpfcc` |
| conntrack | `conntrack -C`, `conntrack -S`, `dmesg \| grep conntrack` |
| fd процесса | `ls /proc/PID/fd \| wc -l`, `grep 'open files' /proc/PID/limits` |
| Лимит сервиса | `systemctl edit app` → `LimitNOFILE=65536` |
| Анализ дампа | `tshark -r f.pcap -q -z conv,tcp`, `-Y 'tcp.analysis.retransmission'` |
| Дропы NIC | `ip -s link`, `ethtool -S`, `/proc/net/softnet_stat`, `sar -n EDEV 1` |
| Задержка DNS | `curl -w '%{time_namelookup}'`, `sudo gethostlatency-bpfcc` |

---

## 🧠 Что запомнить

1. Сетевые счётчики накопительные — смотри дельту (`nstat` без `-a`) и `rate()` в мониторинге.
2. `ss -ti`: `retrans`/`lost`/`rtt` — проблема пути; `app_limited`/`rwnd_limited` — проблема приложения.
3. Порты к одному backend: ~28 тыс. / 60 с ≈ 470 новых соединений в секунду. Лечит keep-alive.
4. `tcp_tw_recycle` удалён в 4.12 и ломал NAT; `tcp_fin_timeout` не трогает TIME_WAIT.
5. Для LISTEN `Recv-Q` — текущая accept queue, `Send-Q` — её предел; очередь = min(backlog, somaxconn).
6. `ListenOverflows` растёт → приложение медленно делает `accept()`; очередь — лишь буфер на всплеск.
7. SYN-ретрансмиты и задержки 1/3/7 с — сервер не отвечает на SYN: очередь, conntrack, файрвол.
8. `table full, dropping packet` — новые соединения молча теряются; ищи источник, потом тюнь.
9. `EMFILE` — лимит процесса; для systemd — `LimitNOFILE`, не `limits.conf`. Рост fd = утечка.
10. DNS проверяй всегда: 5-секундные задержки — таймаут резолвера, в k8s — ещё и `ndots:5`.

➡️ Дальше: [05_strace_hung_processes.md](/performance/05-strace-hung-processes) · задачи: 04_network_deep_tasks.md


---

### Блок A. Теория


**A1.** Почему «`TcpExtListenOverflows 3412`» само по себе ничего не значит? Как смотреть правильно?

<details><summary>Ответ</summary>

Сетевые счётчики накопительные с момента загрузки: 3412 могли набежать за месяц
в одном давнем всплеске. Важна скорость роста: `nstat -n; sleep 10; nstat` (дельта) или
`rate()` в мониторинге (`node_netstat_TcpExt_ListenOverflows`).

</details>

**A2.** ⭐ Назови пять полей `ss -ti` и что каждое говорит. Как по ним отличить проблему
сети от проблемы приложения?

<details><summary>Ответ</summary>

`rtt`/`minrtt` — задержка сейчас и идеальная; большой разрыв — очереди на пути.
`retrans:X/Y` и `bytes_retrans` — повторы, растущий Y — потери. `cwnd`/`ssthresh` — окно
перегрузки: маленькое на долгом соединении — были потери. `lost`/`unacked` — теряем прямо сейчас.
`app_limited` — скорость ограничило приложение; `rwnd_limited` — окно получателя (он не читает).
Растут `retrans`/`lost`/`rtt` — путь; `app_limited`/`rwnd_limited`/большой `Recv-Q` — приложение.

</details>

**A3.** ⭐ Посчитай предел новых соединений в секунду к одному backend при настройках по
умолчанию. Откуда эти числа и на какой стороне живёт TIME_WAIT?

<details><summary>Ответ</summary>

`ip_local_port_range` 32768–60999 = 28 232 порта; TIME_WAIT держит четвёрку 60 с (константа
ядра). К одному `dst IP:port` с одного src IP: 28 232 / 60 ≈ 470 новых соединений в секунду.
TIME_WAIT остаётся на стороне, которая закрыла соединение первой; если это клиент — у него
и кончаются порты.

</details>

**A4.** Что делают `tcp_tw_reuse` (значения 0/1/2), `tcp_tw_recycle` и `tcp_fin_timeout`?

<details><summary>Ответ</summary>

`tcp_tw_reuse`: 0 — выключено, 1 — можно переиспользовать TIME_WAIT для новых исходящих
соединений, когда это безопасно по TCP timestamps, 2 (по умолчанию) — только для loopback.
`tcp_tw_recycle` — ускоренная утилизация TIME_WAIT, ломала клиентов за NAT, удалена в ядре 4.12.
`tcp_fin_timeout` — сколько осиротевшее соединение живёт в FIN-WAIT-2; к TIME_WAIT отношения не имеет.

</details>

**A5.** ⭐ Опиши путь нового соединения через SYN queue и accept queue. Какие параметры
задают размер каждой очереди?

<details><summary>Ответ</summary>

SYN → запись в SYN queue (SYN-RECV), сервер шлёт SYN-ACK; предел —
`tcp_max_syn_backlog`, при переполнении — syncookies (если `tcp_syncookies=1`) или дроп.
Финальный ACK → соединение переходит в accept queue (готовые ESTAB); предел —
`min(backlog из listen(), net.core.somaxconn)`. Приложение забирает их через `accept()`.
Переполнение accept queue → ACK/SYN выбрасываются, растут `ListenOverflows`/`ListenDrops`.

</details>

**A6.** Что означают `Recv-Q` и `Send-Q` у LISTEN-сокета и у ESTAB-сокета?

<details><summary>Ответ</summary>

LISTEN: `Recv-Q` — сколько установленных соединений сейчас ждут `accept()`, `Send-Q` —
размер accept queue. ESTAB: `Recv-Q` — байты, полученные ядром, но не прочитанные приложением;
`Send-Q` — отправленные байты, ещё не подтверждённые пиром (или ещё не отправленные).

</details>

**A7.** Почему «поднять `somaxconn`» часто не помогает? Что нужно поднять вместе с ним
и когда это вообще имеет смысл?

<details><summary>Ответ</summary>

Очередь = `min(backlog, somaxconn)`: если приложение вызывает `listen(fd, 128)`, sysctl
ничего не даст. Поднимать надо и backlog в приложении (nginx `listen … backlog=`, gunicorn
`--backlog`), и `somaxconn`. Имеет смысл только для коротких всплесков; если приложение медленно
принимает постоянно, большая очередь лишь удлинит ожидание — лечить воркеры/event loop.

</details>

**A8.** Что видит клиент при переполненной accept queue с `tcp_abort_on_overflow=0` и с `=1`?

<details><summary>Ответ</summary>

`=0`: сервер молча выбрасывает финальный ACK (и новые SYN); клиент думает, что соединение
установлено, сервер повторяет SYN-ACK, новые клиенты повторяют SYN — задержки 1, 3, 7 с без
ошибок. `=1`: сервер отвечает RST — клиент сразу получает `Connection reset by peer`; быстрее
видно, но это ошибки вместо задержек. Обычно оставляют 0.

</details>

**A9.** Какие счётчики ретрансмитов есть в `nstat` и что каждый означает? О чём говорит
ретрансмит SYN?

<details><summary>Ответ</summary>

`TcpRetransSegs` (с `TcpOutSegs` — доля повторов), `TcpExtTCPSynRetrans` — повторы SYN,
`TcpExtTCPTimeouts` — повторы по RTO (самые дорогие), `TcpExtTCPLostRetransmit` — потерялся уже
повторный сегмент. Ретрансмит SYN означает, что сервер не ответил на попытку соединения: очередь
переполнена, conntrack полон, DROP в файрволе или backend мёртв.

</details>

**A10.** ⭐ Как проявляется переполненный conntrack и как это доказать? Что значат `drop`,
`early_drop`, `insert_failed` в `conntrack -S`?

<details><summary>Ответ</summary>

У части новых соединений таймауты, существующие работают, в приложениях пусто, CPU/RAM
в норме. Доказательство: `dmesg` — `nf_conntrack: table full, dropping packet`; `conntrack -C`
≈ `nf_conntrack_max`; растёт `drop` в `conntrack -S`. `drop` — новая запись не создана, пакет
выброшен; `early_drop` — ядро вытеснило запись без ответного трафика, чтобы вставить новую;
`insert_failed` — вставка не удалась (гонки, часто UDP/DNS).

</details>

**A11.** В каком порядке лечить «conntrack table full»? Что такое NOTRACK и когда он уместен?

<details><summary>Ответ</summary>

1) Понять, что заполнило таблицу (протокол, состояние, адреса: DNS-флуд, сканер, клиент
без keep-alive). 2) Поднять `nf_conntrack_max` (и `nf_conntrack_buckets`), учитывая память.

</details>

**A12.** Чем `EMFILE` отличается от `ENFILE`? Где задаётся лимит fd для systemd-сервиса
и почему `/etc/security/limits.conf` не работает?

<details><summary>Ответ</summary>

`EMFILE` — упёрлись в лимит процесса (`RLIMIT_NOFILE`), `ENFILE` — в системный
`fs.file-max`. Для сервиса лимит задаётся `LimitNOFILE=` в юните (drop-in через `systemctl edit`);
по умолчанию soft 1024 / hard 524288. `limits.conf` применяет `pam_limits` при входе в сессию
(SSH, login), а systemd запускает сервисы без PAM-сессии.

</details>

**A13.** На каких уровнях пакет может быть выброшен до приложения? Чем проверить каждый?

<details><summary>Ответ</summary>

Ring buffer NIC — `missed`/`rx_missed_errors`/`rx_fifo_errors` (`ip -s link`,
`ethtool -S`). Backlog softirq — колонка 2 в `/proc/net/softnet_stat`, недобор бюджета — колонка 3.
Netfilter/conntrack — `conntrack -S`, `dmesg`, счётчики правил `iptables -L -n -v`. TCP-очереди —
`ListenOverflows`/`ListenDrops` в `nstat`. Буфер сокета — `d` в `skmem` (`ss -tm`). Где именно
выброшен TCP-пакет со стеком — `tcpdrop-bpfcc`.

</details>

**A14.** Как DNS прячется в latency? Назови три признака и объясни `ndots:5`.

<details><summary>Ответ</summary>

Резолв идёт до соединения, и его время прячется внутри «запроса к upstream». Признаки:
медленный только первый запрос (кэш), задержки ровно 5/10 с (таймаут резолвера и повтор),
лишние запросы в `tcpdump port 53`. В k8s `ndots:5`: имя, в котором меньше пяти точек, сначала
пробуется со всеми search-доменами (`…default.svc.cluster.local` и т.д.), — несколько лишних
запросов на каждый вызов.

</details>

**A15.** Какие сетевые sysctl трогать нельзя и почему? Сформулируй правила тюнинга.

<details><summary>Ответ</summary>

Нельзя: `tcp_tw_recycle` (удалён, ломал NAT), `tcp_syncookies=0` (снимает защиту от
SYN-флуда), `tcp_fin_timeout` «от TIME_WAIT» (не работает), буферы `tcp_rmem`/`tcp_wmem`
«побольше» без доказанной нужды (автотюнинг справляется). Правила: сначала счётчик-доказательство,
одно изменение, замер до/после, постоянные значения в `/etc/sysctl.d/*.conf` с комментарием «зачем».

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  $ ss -lnt '( sport = :8080 )'
```text
<details><summary>Ответ</summary>

Accept queue переполнена: `Recv-Q` 4097 при пределе 4096 (ядро допускает backlog+1),
за 10 секунд выброшено 812 попыток. Приложение не успевает вызывать `accept()`. Клиенты видят
задержки подключения 1/3/7 с. Смотреть воркеров приложения, блокировки event loop, профиль
(темы 02, 05); очередь поднимать, только если это короткие всплески.

</details>

```text:no-line-numbers
     State  Recv-Q Send-Q Local Address:Port Peer Address:Port
```text
```text:no-line-numbers
     LISTEN 4097   4096         0.0.0.0:8080      0.0.0.0:*
```text
```text:no-line-numbers
     $ nstat -n; sleep 10; nstat 'TcpExtListen*'
```text
```text:no-line-numbers
     TcpExtListenOverflows           812                0.0
```text
```text:no-line-numbers
     TcpExtListenDrops               812                0.0
```text
```text:no-line-numbers
B2.  # пользователь: «скачивание отчёта медленное, сеть плохая»
```text
<details><summary>Ответ</summary>

Сеть ни при чём: `rtt` ≈ `minrtt` (2 мс), ретрансмитов нет, `cwnd` нормальный, а
`app_limited` и `delivery_rate` 1,2 Мбит/с при расчётных 55 — приложение медленно отдаёт данные
(генерирует отчёт, пишет маленькими порциями). Профилировать приложение.

</details>

```text:no-line-numbers
     ESTAB 0 0 10.0.2.15:8000 10.0.2.40:51022
```text
```text:no-line-numbers
        cubic rtt:2.1/0.4 minrtt:1.9 cwnd:10 bytes_sent:81920 retrans:0/0
```text
```text:no-line-numbers
        send 55Mbps delivery_rate 1.2Mbps app_limited busy:9120ms
```text
```text:no-line-numbers
B3.  ESTAB 0 180224 10.0.2.15:44120 10.0.2.20:5432
```text
<details><summary>Ответ</summary>

Проблема пути: `rtt` 180 мс при `minrtt` 0,4 мс (очереди/перегрузка), 412 повторов за
жизнь, ~5% байт повторно (468004 / 9120330), `lost` 3 и `backoff` 2 — прямо сейчас повторы по
таймауту, `cwnd` упал до 3. Плюс `Send-Q` 180 КБ — данные копятся на отправке. Дальше:
`ip -s link` и `ethtool -S` на обеих сторонах, `mtr`, дамп с двух сторон.

</details>

```text:no-line-numbers
        cubic rto:612 backoff:2 rtt:180.4/61.2 minrtt:0.4 cwnd:3 ssthresh:5
```text
```text:no-line-numbers
        bytes_sent:9120330 bytes_retrans:468004 unacked:12 retrans:3/412 lost:3
```text
```text:no-line-numbers
B4.  # прокси, в логе: connect() failed (99: Cannot assign requested address)
```text
<details><summary>Ответ</summary>

Исчерпаны эфемерные порты: 28 104 TIME_WAIT при диапазоне 28 232 порта; `tcp_tw_reuse=2`
разрешает переиспользование только на loopback. Прокси открывает новое соединение на каждый
запрос. Лечение: keep-alive к upstream (`keepalive` в nginx upstream + HTTP/1.1), затем
`tcp_tw_reuse=1`, шире `ip_local_port_range`, несколько адресов upstream/источника.

</details>

```text:no-line-numbers
     $ ss -s
```text
```text:no-line-numbers
     TCP:   29412 (estab 1180, closed 28120, orphaned 0, timewait 28104)
```text
```text:no-line-numbers
     $ sysctl net.ipv4.ip_local_port_range net.ipv4.tcp_tw_reuse
```text
```text:no-line-numbers
     net.ipv4.ip_local_port_range = 32768	60999
```text
```text:no-line-numbers
     net.ipv4.tcp_tw_reuse = 2
```text
```text:no-line-numbers
B5.  $ sudo dmesg -T | tail -3
```text
<details><summary>Ответ</summary>

Таблица conntrack забита UDP-записями DNS (180 тыс. из ~190 тыс.): хост шлёт или
принимает огромный поток DNS-запросов, каждый живёт `nf_conntrack_udp_timeout`. Лечение:
найти источник (кто шлёт — `conntrack -L` по `src`), кэширующий резолвер, NOTRACK для
порта 53 в `raw`, затем при необходимости поднять `nf_conntrack_max`.

</details>

```text:no-line-numbers
     [Sat Sep 26 03:12:40 2026] nf_conntrack: nf_conntrack: table full, dropping packet
```text
```text:no-line-numbers
     [Sat Sep 26 03:12:45 2026] nf_conntrack: nf_conntrack: table full, dropping packet
```text
```text:no-line-numbers
     $ sudo conntrack -L 2>/dev/null | awk '{print $1}' | sort | uniq -c
```text
```text:no-line-numbers
      181204 udp
```text
```text:no-line-numbers
        9310 tcp
```text
```text:no-line-numbers
     $ sudo conntrack -L -p udp 2>/dev/null | grep -c 'dport=53'
```text
```text:no-line-numbers
     179880
```text
```text:no-line-numbers
B6.  $ grep 'open files' /proc/2210/limits
```text
<details><summary>Ответ</summary>

Утечка сокетов: 990 в CLOSE-WAIT — пиры закрыли соединения, а приложение нет; fd 1021
из 1024 — следующее `accept()`/`open()` упадёт с `EMFILE`. Лимит поднимать можно как временную
меру, но это баг кода: соединения не закрываются (нет `close()`/`with`, потерянные ответы в пуле).

</details>

```text:no-line-numbers
     Max open files            1024                 1024                 files
```text
```text:no-line-numbers
     $ ls /proc/2210/fd | wc -l
```text
```text:no-line-numbers
     1021
```text
```text:no-line-numbers
     $ ss -tanp | grep 'pid=2210' | awk '{print $1}' | sort | uniq -c
```text
```text:no-line-numbers
         990 CLOSE-WAIT
```text
```text:no-line-numbers
          28 ESTAB
```text
```text:no-line-numbers
B7.  # /etc/sysctl.d/99-highload.conf из «гайда по тюнингу»
```text
<details><summary>Ответ</summary>

`tcp_tw_recycle` не существует с 4.12 (sysctl выдаст ошибку, а на старых ядрах ломал NAT);
`tcp_fin_timeout` не влияет на TIME_WAIT (это FIN-WAIT-2); `tcp_syncookies=0` снимает защиту
от SYN-флуда; `somaxconn=65535` без backlog в приложении ничего не даст, а с ним — лишь удлинит
очередь медленному приложению. Файл надо выбросить и тюнить по счётчикам.

</details>

```text:no-line-numbers
     net.ipv4.tcp_tw_recycle = 1
```text
```text:no-line-numbers
     net.ipv4.tcp_fin_timeout = 5        # «чтобы TIME_WAIT держался 5 секунд»
```text
```text:no-line-numbers
     net.ipv4.tcp_syncookies = 0
```text
```text:no-line-numbers
     net.core.somaxconn = 65535
```text
```text:no-line-numbers
B8.  $ cat /proc/net/softnet_stat      # первые три колонки, 2 CPU
```text
<details><summary>Ответ</summary>

CPU0: колонка 2 = 0x12f4e = 77 646 выброшенных пакетов (переполнение backlog,
`netdev_max_backlog`), колонка 3 = 0x3a91 = 14 993 раза softirq не уложился в бюджет. CPU1
почти ничего не обрабатывает — весь приём на одном ядре. Лечение: несколько очередей NIC (RSS)
и распределение прерываний, RPS, умеренно поднять `netdev_max_backlog`/`netdev_budget`.

</details>

```text:no-line-numbers
     0a3b41c2 00012f4e 00003a91 …
```text
```text:no-line-numbers
     00f10a33 00000000 00000012 …
```text
```text:no-line-numbers
B9.  $ curl -o /dev/null -s -w 'dns:%{time_namelookup} connect:%{time_connect} total:%{time_total}\n' https://billing.internal/health
```text
<details><summary>Ответ</summary>

5 секунд уходят на DNS (`time_namelookup` 5,012), соединение и ответ быстрые. Типично:
первый DNS-сервер в списке не отвечает, резолвер ждёт таймаут 5 с и идёт ко второму.
Проверить `resolvectl status`, `dig @&lt;каждый сервер&gt;`, убрать мёртвый сервер, кэш на хосте.

</details>

```text:no-line-numbers
     dns:5.012 connect:5.014 total:5.120
```text
```text:no-line-numbers
B10.  # дамп за 5 минут на клиенте
```text
<details><summary>Ответ</summary>

5000 SYN остались без ответа, и почти все ретрансмиты — к одному адресу 10.0.3.7:5432:
база (или путь до неё) не отвечает на SYN — переполнена accept queue у PostgreSQL, conntrack
или DROP в файрволе на пути, хост перегружен. Лимит `max_connections` выглядит иначе: соединение
устанавливается, и PostgreSQL отвечает ошибкой `too many clients`. Снять дамп на стороне базы
(дошли ли SYN), там же дельта `ListenOverflows` в `nstat` и `dmesg`.

</details>

```text:no-line-numbers
     SYN (без ACK):                         12000
```text
```text:no-line-numbers
     SYN-ACK:                                7000
```text
```text:no-line-numbers
     SYN-ретрансмиты к 10.0.3.7:5432:        4800
```text
```text:no-line-numbers
B11.  $ ip -s link show eth0 | sed -n 3,4p
```text
<details><summary>Ответ</summary>

NIC и драйвер ничего не теряют (`missed`, `rx_missed_errors`, `rx_fifo_errors` = 0), а
`dropped` растёт — пакеты выбрасывает ядро выше драйвера: backlog (softnet_stat колонка 2),
неизвестный протокол/VLAN, фильтры. Проверить softnet_stat, `nstat`, `sudo tcpdrop-bpfcc`
(для TCP) и мультикаст/неподдерживаемые протоколы.

</details>

```text:no-line-numbers
         RX:  bytes  packets errors dropped  missed   mcast
```text
```text:no-line-numbers
         9876543210 8123456      0   41230       0     120
```text
```text:no-line-numbers
     $ sudo ethtool -S eth0 | grep -iE 'miss|fifo'
```text
```text:no-line-numbers
          rx_missed_errors: 0
```text
```text:no-line-numbers
          rx_fifo_errors: 0
```text
```text:no-line-numbers
B12.  # коллега добавил в /etc/security/limits.conf строку «* soft nofile 65536»,
```text
<details><summary>Ответ</summary>

systemd запускает сервис без PAM-сессии, `limits.conf` на него не действует. Soft 1024 —
дефолт systemd. Нужен drop-in `systemctl edit app` → `[Service]` `LimitNOFILE=65536`, затем
restart и проверка `/proc/PID/limits`.

</details>

```text:no-line-numbers
     # сделал systemctl restart app, а лимит не изменился
```text
```text:no-line-numbers
     $ grep 'open files' /proc/$(systemctl show -p MainPID --value app)/limits
```text
```text:no-line-numbers
     Max open files            1024                 524288               files
```text
---

### Блок C. Практика


### C1. 🔑 Дельта-режим счётчиков
**1.** `nstat -n`, затем минуту обычной жизни VM, затем `nstat` — что изменилось?

<details><summary>Ответ</summary>

В спокойной VM за минуту растут единицы счётчиков (`TcpInSegs`, `TcpOutSegs`, ARP/ICMP).
После 2000 запросов: `TcpActiveOpens` и `TcpPassiveOpens` +2000 каждый (клиент и сервер на одной
машине), в `ss -s` — ~2000 в `timewait`; `TcpExtTW` вырастет на ~2000 примерно через минуту,
когда эти TIME_WAIT истекут (счётчик считает завершённые TIME_WAIT).

</details>

**2.** Запусти `python3 -m http.server 8000 &` и 2000 запросов:
   `for i in $(seq 2000); do curl -s -o /dev/null localhost:8000/; done`.

<details><summary>Ответ</summary>

`ss -lnt` показывает `Recv-Q` 9 при `Send-Q` 8 — очередь полна; `ListenOverflows` и
`ListenDrops` растут на десятки в секунду. Новый клиент подключается мгновенно, если попал в
момент освобождения места, или через ~1 с / ~3 с: его SYN выброшен, и он повторяет SYN по
RTO (1 с, затем +2 с).

</details>

**3.** Снова `nstat` и `ss -s`: какие счётчики выросли, сколько стало TIME_WAIT?

<details><summary>Ответ</summary>

С 3% потерь в `ss -tin` растёт второй счётчик `retrans`, `cwnd` скачет и остаётся
небольшим, появляются `lost`, в выводе iperf3 — колонка `Retr` с сотнями, скорость заметно
ниже. `tcpretrans-bpfcc` печатает ретрансмиты с адресами, `nstat TcpRetransSegs` растёт.
Без netem `retrans` 0/0 и скорость — гигабиты.

</details>

### C2. 🔑 Переполнить accept queue
```text:no-line-numbers
# ~/perf/t04/slow_accept.py — «медленное приложение»: один accept() в секунду, backlog 8
```text
```text:no-line-numbers
import socket
```text
```text:no-line-numbers
import time
```text
```text:no-line-numbers
s = socket.socket()
```text
```text:no-line-numbers
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
```text
```text:no-line-numbers
s.bind(("127.0.0.1", 8080))
```text
```text:no-line-numbers
s.listen(8)
```text
```text:no-line-numbers
while True:
```text
```text:no-line-numbers
    time.sleep(1)
```text
```text:no-line-numbers
    c, _ = s.accept()
```text
```text:no-line-numbers
    c.close()
```text
**1.** Запусти сервер, затем 100 параллельных подключений:
   `for i in $(seq 100); do (timeout 10 bash -c 'exec 3<>/dev/tcp/127.0.0.1/8080; sleep 2') & done`.

<details><summary>Ответ</summary>

В спокойной VM за минуту растут единицы счётчиков (`TcpInSegs`, `TcpOutSegs`, ARP/ICMP).
После 2000 запросов: `TcpActiveOpens` и `TcpPassiveOpens` +2000 каждый (клиент и сервер на одной
машине), в `ss -s` — ~2000 в `timewait`; `TcpExtTW` вырастет на ~2000 примерно через минуту,
когда эти TIME_WAIT истекут (счётчик считает завершённые TIME_WAIT).

</details>

**2.** Одновременно: `ss -lnt '( sport = :8080 )'`, `nstat -n; sleep 5; nstat 'TcpExtListen*'`.

<details><summary>Ответ</summary>

`ss -lnt` показывает `Recv-Q` 9 при `Send-Q` 8 — очередь полна; `ListenOverflows` и
`ListenDrops` растут на десятки в секунду. Новый клиент подключается мгновенно, если попал в
момент освобождения места, или через ~1 с / ~3 с: его SYN выброшен, и он повторяет SYN по
RTO (1 с, затем +2 с).

</details>

**3.** Замерь время подключения нового клиента: `time bash -c 'exec 3<>/dev/tcp/127.0.0.1/8080'`.
   Почему иногда ~1 с или ~3 с?

<details><summary>Ответ</summary>

С 3% потерь в `ss -tin` растёт второй счётчик `retrans`, `cwnd` скачет и остаётся
небольшим, появляются `lost`, в выводе iperf3 — колонка `Retr` с сотнями, скорость заметно
ниже. `tcpretrans-bpfcc` печатает ретрансмиты с адресами, `nstat TcpRetransSegs` растёт.
Без netem `retrans` 0/0 и скорость — гигабиты.

</details>

### C3. 🔑 `ss -ti` под потерями
**1.** `iperf3 -s -D`, затем добавь 3% потерь на loopback: `sudo tc qdisc add dev lo root netem loss 3%`
   (если `Specified qdisc kind is unknown` — `sudo apt install linux-modules-extra-$(uname -r)`).

<details><summary>Ответ</summary>

В спокойной VM за минуту растут единицы счётчиков (`TcpInSegs`, `TcpOutSegs`, ARP/ICMP).
После 2000 запросов: `TcpActiveOpens` и `TcpPassiveOpens` +2000 каждый (клиент и сервер на одной
машине), в `ss -s` — ~2000 в `timewait`; `TcpExtTW` вырастет на ~2000 примерно через минуту,
когда эти TIME_WAIT истекут (счётчик считает завершённые TIME_WAIT).

</details>

**2.** `iperf3 -c 127.0.0.1 -t 20 &` и во время теста `ss -tin '( dport = :5201 )'` раз в пару секунд.

<details><summary>Ответ</summary>

`ss -lnt` показывает `Recv-Q` 9 при `Send-Q` 8 — очередь полна; `ListenOverflows` и
`ListenDrops` растут на десятки в секунду. Новый клиент подключается мгновенно, если попал в
момент освобождения места, или через ~1 с / ~3 с: его SYN выброшен, и он повторяет SYN по
RTO (1 с, затем +2 с).

</details>

**3.** Сравни `retrans`, `cwnd`, `rtt` с прогоном без потерь; посмотри `sudo tcpretrans-bpfcc`
   и `nstat TcpRetransSegs`. Уборка: `sudo tc qdisc del dev lo root`.

<details><summary>Ответ</summary>

С 3% потерь в `ss -tin` растёт второй счётчик `retrans`, `cwnd` скачет и остаётся
небольшим, появляются `lost`, в выводе iperf3 — колонка `Retr` с сотнями, скорость заметно
ниже. `tcpretrans-bpfcc` печатает ретрансмиты с адресами, `nstat TcpRetransSegs` растёт.
Без netem `retrans` 0/0 и скорость — гигабиты.

</details>

### C4. Кто держит TIME_WAIT
После C1 выполни `ss -tan state time-wait | head`. На какой стороне (порт 8000 или эфемерный)
TIME_WAIT? Кто закрыл соединение первым и почему (HTTP/1.0 в `http.server`)?
Посчитай, сколько таких запросов в секунду выдержит связка при 28 232 портах.

### C5. conntrack: что лежит в таблице
**1.** `sudo conntrack -C`, `sudo conntrack -S | head -2`.

<details><summary>Ответ</summary>

В спокойной VM за минуту растут единицы счётчиков (`TcpInSegs`, `TcpOutSegs`, ARP/ICMP).
После 2000 запросов: `TcpActiveOpens` и `TcpPassiveOpens` +2000 каждый (клиент и сервер на одной
машине), в `ss -s` — ~2000 в `timewait`; `TcpExtTW` вырастет на ~2000 примерно через минуту,
когда эти TIME_WAIT истекут (счётчик считает завершённые TIME_WAIT).

</details>

**2.** 300 DNS-запросов: `for i in $(seq 300); do dig +short @1.1.1.1 test$i.example.com >/dev/null; done`.

<details><summary>Ответ</summary>

`ss -lnt` показывает `Recv-Q` 9 при `Send-Q` 8 — очередь полна; `ListenOverflows` и
`ListenDrops` растут на десятки в секунду. Новый клиент подключается мгновенно, если попал в
момент освобождения места, или через ~1 с / ~3 с: его SYN выброшен, и он повторяет SYN по
RTO (1 с, затем +2 с).

</details>

**3.** Снова `conntrack -C`; разбивка по протоколам и по `dport=53`. Через сколько записи UDP исчезнут
   и какой sysctl это задаёт?

<details><summary>Ответ</summary>

С 3% потерь в `ss -tin` растёт второй счётчик `retrans`, `cwnd` скачет и остаётся
небольшим, появляются `lost`, в выводе iperf3 — колонка `Retr` с сотнями, скорость заметно
ниже. `tcpretrans-bpfcc` печатает ретрансмиты с адресами, `nstat TcpRetransSegs` растёт.
Без netem `retrans` 0/0 и скорость — гигабиты.

</details>

### C6. 🔑 Утечка fd и CLOSE-WAIT
```text:no-line-numbers
# ~/perf/t04/leaky_server.py — принимает соединения и «забывает» их закрыть
```text
```text:no-line-numbers
import socket
```text
```text:no-line-numbers
srv = socket.socket()
```text
```text:no-line-numbers
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
```text
```text:no-line-numbers
srv.bind(("127.0.0.1", 7000))
```text
```text:no-line-numbers
srv.listen(128)
```text
```text:no-line-numbers
conns = []
```text
```text:no-line-numbers
while True:
```text
```text:no-line-numbers
    c, _ = srv.accept()
```text
```text:no-line-numbers
    conns.append(c)             # ни recv, ни close — классическая утечка
```text
**1.** `systemd-run --user --unit=leaky-srv -p LimitNOFILE=200 python3 ~/perf/t04/leaky_server.py`.

<details><summary>Ответ</summary>

В спокойной VM за минуту растут единицы счётчиков (`TcpInSegs`, `TcpOutSegs`, ARP/ICMP).
После 2000 запросов: `TcpActiveOpens` и `TcpPassiveOpens` +2000 каждый (клиент и сервер на одной
машине), в `ss -s` — ~2000 в `timewait`; `TcpExtTW` вырастет на ~2000 примерно через минуту,
когда эти TIME_WAIT истекут (счётчик считает завершённые TIME_WAIT).

</details>

**2.** 300 коротких клиентов: `for i in $(seq 300); do timeout 1 bash -c 'exec 3<>/dev/tcp/127.0.0.1/7000'; done`.

<details><summary>Ответ</summary>

`ss -lnt` показывает `Recv-Q` 9 при `Send-Q` 8 — очередь полна; `ListenOverflows` и
`ListenDrops` растут на десятки в секунду. Новый клиент подключается мгновенно, если попал в
момент освобождения места, или через ~1 с / ~3 с: его SYN выброшен, и он повторяет SYN по
RTO (1 с, затем +2 с).

</details>

**3.** Смотри: число fd (`ls /proc/PID/fd | wc -l`), состояния сокетов сервера, лимит
   в `/proc/PID/limits`, `journalctl --user -u leaky-srv`. Что упало и с какой ошибкой?

<details><summary>Ответ</summary>

С 3% потерь в `ss -tin` растёт второй счётчик `retrans`, `cwnd` скачет и остаётся
небольшим, появляются `lost`, в выводе iperf3 — колонка `Retr` с сотнями, скорость заметно
ниже. `tcpretrans-bpfcc` печатает ретрансмиты с адресами, `nstat TcpRetransSegs` растёт.
Без netem `retrans` 0/0 и скорость — гигабиты.

</details>

### C7. tcpdump + tshark по переполненной очереди
Повтори C2, записывая дамп: `sudo tcpdump -ni lo -w ~/perf/t04/q.pcap 'port 8080' &`.
Посчитай в tshark SYN, SYN-ACK, SYN-ретрансмиты и RST. Совпадает ли картина с `nstat`?

### C8. DNS как часть latency
**1.** `resolvectl flush-caches`, затем дважды
   `curl -o /dev/null -s -w 'dns:%{time_namelookup} total:%{time_total}\n' https://example.com`.

<details><summary>Ответ</summary>

В спокойной VM за минуту растут единицы счётчиков (`TcpInSegs`, `TcpOutSegs`, ARP/ICMP).
После 2000 запросов: `TcpActiveOpens` и `TcpPassiveOpens` +2000 каждый (клиент и сервер на одной
машине), в `ss -s` — ~2000 в `timewait`; `TcpExtTW` вырастет на ~2000 примерно через минуту,
когда эти TIME_WAIT истекут (счётчик считает завершённые TIME_WAIT).

</details>

**2.** В соседнем окне `sudo gethostlatency-bpfcc`, в первом — `getent ahosts example.org`.

<details><summary>Ответ</summary>

`ss -lnt` показывает `Recv-Q` 9 при `Send-Q` 8 — очередь полна; `ListenOverflows` и
`ListenDrops` растут на десятки в секунду. Новый клиент подключается мгновенно, если попал в
момент освобождения места, или через ~1 с / ~3 с: его SYN выброшен, и он повторяет SYN по
RTO (1 с, затем +2 с).

</details>

**3.** Как выглядит «мёртвый» DNS-сервер: `dig @192.0.2.1 example.com +timeout=2 +tries=1`.

<details><summary>Ответ</summary>

С 3% потерь в `ss -tin` растёт второй счётчик `retrans`, `cwnd` скачет и остаётся
небольшим, появляются `lost`, в выводе iperf3 — колонка `Retr` с сотнями, скорость заметно
ниже. `tcpretrans-bpfcc` печатает ретрансмиты с адресами, `nstat TcpRetransSegs` растёт.
Без netem `retrans` 0/0 и скорость — гигабиты.

</details>

### C9. Декодер softnet_stat
Напиши однострочник, который печатает по каждому CPU обработанные, выброшенные пакеты
и time_squeeze в десятичном виде (в Ubuntu `awk` — это mawk, без `strtonum`).

---

### Блок D. Инциденты


**D1.** После релиза ~1% запросов к API стали дольше ровно на 1 или 3 секунды. В логах
сервера чисто, CPU 20%. Как искать?

<details><summary>Ответ</summary>

Ровные 1 и 3 с — SYN-ретрансмиты: сервер иногда не отвечает на SYN. Проверить
`nstat` дельты `ListenOverflows`/`ListenDrops` и `TcpExtTCPSynRetrans`, `ss -lnt` (`Recv-Q` у
потолка?), `dmesg` (conntrack, SYN flooding), дамп SYN/SYN-ACK. Если очередь — релиз замедлил
приём соединений (меньше воркеров, блокировка event loop), лечить приложение; backlog —
буфер на всплеск.

</details>

**D2.** CI-раннеры на пике падают с `cannot assign requested address` при загрузке
артефактов в один внутренний API.

<details><summary>Ответ</summary>

Исчерпание эфемерных портов на раннерах: много коротких соединений к одному
`dst IP:port`, TIME_WAIT у клиента. Доказать: `ss -tan state time-wait | wc -l` ≈ диапазону,
`EADDRNOTAVAIL`. Лечение: keep-alive/пул в клиенте загрузки, `tcp_tw_reuse=1`, шире
`ip_local_port_range`, несколько адресов API за балансировщиком.

</details>

**D3.** Ноды Kubernetes: случайные таймауты между подами, иногда DNS-запросы по 5 секунд.
На ноде в `dmesg` — `table full, dropping packet`.

<details><summary>Ответ</summary>

Conntrack на нодах переполнен (DNS по UDP, kube-proxy/NAT). Доказать: `conntrack -C`
против max, `drop` в `conntrack -S`, разбивка по `dport=53`. Меры: NodeLocal DNSCache
(меньше UDP-записей и нет гонок `insert_failed`), `nf_conntrack_max` выше с учётом памяти,
меньше `ndots` или FQDN с точкой, проверить, кто генерирует флуд.

</details>

**D4.** Сервис падает раз в ~3 дня с `Too many open files`; рестарт помогает.

<details><summary>Ответ</summary>

Утечка fd, скорее всего сокетов. Собрать: график `ls /proc/PID/fd | wc -l` во времени,
типы fd (`socket`/файлы), `ss -tanp` по PID — CLOSE-WAIT? куда соединения? Отдать разработчикам
с доказательствами. Временно — поднять `LimitNOFILE` и перезапускать по расписанию/алерту на
рост fd (`process_open_fds / process_max_fds`), но починить код.

</details>

**D5.** «Сеть тормозит»: клиент скачивает с сервера 20 МБ/с вместо 100. У серверного сокета
в `ss -ti` большой `rwnd_limited`, у клиента в `ss -tn` растёт `Recv-Q`.

<details><summary>Ответ</summary>

Сервер упирается в окно получателя: клиент медленно читает данные из сокета (`Recv-Q`
растёт — ядро приняло, приложение не забрало). Сеть не виновата. Смотреть клиентское
приложение: пишет на медленный диск, однопоточная обработка, маленький буфер чтения.

</details>

**D6.** Nginx отдаёт 502 на пиках трафика. Upstream — gunicorn с `--backlog 64` и 4 воркерами.

<details><summary>Ответ</summary>

Backlog 64 у gunicorn: на пике accept queue переполняется, nginx получает таймауты
подключения/сброс → 502. Доказать: `ss -lnt` на порту gunicorn (`Recv-Q` у 64/65), дельта
`ListenOverflows`, `upstream timed out`/`connect() failed` в error.log nginx. Лечение: больше
воркеров или async-воркеры, короче обработка; для всплесков — `--backlog` больше и `somaxconn`
не меньше; keep-alive между nginx и upstream.

</details>

**D7.** Коллега применил «sysctl для highload» из старой статьи (там было `tcp_syncookies=0`).
Через неделю небольшой SYN-флуд положил сайт.

<details><summary>Ответ</summary>

С выключенными syncookies переполнение SYN queue при флуде означает отказ новым
легитимным клиентам. Вернуть `tcp_syncookies=1`, выкинуть «гайд», проверить остальные параметры
по одному со счётчиками; защита от флуда — ещё и на уровне провайдера/балансировщика.

</details>

**D8.** UDP-нагруженный хост теряет пакеты: в `ip -s link` растёт `dropped`, в softnet_stat —
колонка 2 только у CPU0, `mpstat` показывает `%soft` ~100% на CPU0.

<details><summary>Ответ</summary>

Весь приём на CPU0: одна очередь NIC или все прерывания на одном ядре, softirq не успевает,
backlog переполняется. Проверить `/proc/interrupts` (очереди `eth0-rx-N`), `ethtool -l eth0`
(число каналов), irqbalance. Лечение: включить несколько каналов (`ethtool -L`), распределить
IRQ, RPS (`/sys/class/net/eth0/queues/rx-0/rps_cpus`), затем умеренно поднять
`netdev_max_backlog`; для UDP-сервиса — несколько сокетов с `SO_REUSEPORT`.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как понять, что сервер не успевает принимать новые соединения?

<details><summary>Ответ</summary>

/3/7 с и SYN-ретрансмиты; в `dmesg` возможно `Possible SYN flooding`. Причина обычно —
   медленный `accept()` в приложении.

</details>

**2.** Чем TIME_WAIT отличается от CLOSE_WAIT и что с ними делать?

<details><summary>Ответ</summary>

TIME_WAIT — нормальное состояние ядра на стороне, закрывшей соединение первой, 60 с; много
   их — много коротких соединений, опасно исчерпанием портов; лечится keep-alive и
   `tcp_tw_reuse`. CLOSE_WAIT — пир закрыл, а приложение не вызвало `close()`: баг и утечка fd,
   лечится в коде.

</details>

**3.** Что такое `tcp_tw_reuse` и `tcp_tw_recycle`?

<details><summary>Ответ</summary>

`tcp_tw_reuse=1` разрешает безопасно переиспользовать TIME_WAIT для исходящих соединений
   (по timestamps), дефолт 2 — только loopback. `tcp_tw_recycle` ломал клиентов за NAT и удалён
   в 4.12 — ответ «никогда».

</details>

**4.** Сколько исходящих соединений в секунду можно открыть к одному адресу:порту? Почему?

<details><summary>Ответ</summary>

С одного src IP к одному dst IP:port меняется только src port: 28 232 порта / 60 с TIME_WAIT
   ≈ 470 новых соединений в секунду. Больше — keep-alive, `tcp_tw_reuse`, шире диапазон,
   больше адресов.

</details>

**5.** Что такое conntrack и чем опасно переполнение его таблицы?

<details><summary>Ответ</summary>

Таблица отслеживания соединений netfilter для stateful-фильтрации и NAT (Docker, k8s,
   файрволы). При переполнении новые соединения молча выбрасываются: случайные таймауты при
   нормальных CPU и памяти; в `dmesg` — `table full, dropping packet`.

</details>

**6.** «Too many open files» — твои действия?

<details><summary>Ответ</summary>

Понять, чей лимит: `EMFILE` (процесс) или `ENFILE` (система); сравнить
   `ls /proc/PID/fd | wc -l` с `/proc/PID/limits`; посмотреть, что за fd и растут ли (CLOSE-WAIT —
   утечка). Временно поднять `LimitNOFILE` в юните, постоянно — чинить утечку и алертить на
   долю использованных fd.

</details>

**7.** Как отличить проблему сети от проблемы приложения?

<details><summary>Ответ</summary>

`ss -ti`: ретрансмиты, `lost`, RTT ≫ minRTT — путь; `app_limited`, `rwnd_limited`, большой
   `Recv-Q` у получателя — приложение. Плюс `curl -w` по фазам и дамп с двух сторон:
   где пропадают пакеты или время.

</details>

**8.** Где на хосте могут теряться пакеты до приложения?

<details><summary>Ответ</summary>

Ring buffer NIC (`missed`, `rx_fifo_errors`), backlog softirq (softnet_stat), netfilter/conntrack,
   очереди TCP (SYN/accept), буфер сокета (`skmem` drops). Инструменты: `ip -s link`,
   `ethtool -S`, `/proc/net/softnet_stat`, `conntrack -S`, `nstat`, `tcpdrop-bpfcc`.

</details>

**9.** Почему DNS называют скрытым виновником latency?

<details><summary>Ответ</summary>

Резолв выполняется до соединения и в метриках прячется внутри времени запроса; мёртвый
   первый сервер даёт ровно 5 с, в k8s `ndots:5` множит запросы. Ловится `time_namelookup`,
   `gethostlatency-bpfcc`, `tcpdump port 53`.

</details>

**10.** Какие sysctl ты бы менял на нагруженном сервере и как принимаешь решение?

<details><summary>Ответ</summary>

Только по доказательству: `somaxconn` + backlog приложения — при растущих `ListenOverflows`
    на всплесках; `ip_local_port_range`/`tcp_tw_reuse=1` — при `EADDRNOTAVAIL`;
    `nf_conntrack_max` — при `table full`; `netdev_max_backlog` — при дропах в softnet_stat.
    По одному, с замером до/после, в `/etc/sysctl.d` с комментарием. Никогда — `tcp_tw_recycle`
    и `tcp_syncookies=0`.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Смотрю сетевые счётчики только дельтой (`nstat -n; sleep; nstat`)
- [ ] ⭐ Читаю `ss -ti` и по полям отличаю проблему пути от проблемы приложения
- [ ] ⭐ Считаю предел эфемерных портов и знаю, на какой стороне TIME_WAIT
- [ ] Объясняю `tcp_tw_reuse` 0/1/2, почему нет `tcp_tw_recycle` и что делает `tcp_fin_timeout`
- [ ] ⭐ Переполнил accept queue на стенде и доказал это `ss -lnt` и `ListenOverflows`
- [ ] Вижу ретрансмиты в `ss -ti`, `nstat`, `tcpretrans-bpfcc`, объясняю задержки 1/3/7 с
- [ ] Доказываю переполненный conntrack и знаю порядок лечения, включая NOTRACK
- [ ] Воспроизвёл утечку fd с CLOSE-WAIT и `EMFILE`; ставлю `LimitNOFILE` через drop-in
- [ ] Разбираю дамп в tshark: SYN против SYN-ACK, ретрансмиты, RST, zero window
- [ ] Нахожу дропы на NIC, в softnet_stat и в сокете
- [ ] Подозреваю DNS и меряю `time_namelookup`
- [ ] Знаю, какие sysctl не трогать никогда
