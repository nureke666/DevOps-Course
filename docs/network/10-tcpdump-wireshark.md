---
title: "10. tcpdump и Wireshark"
description: "Захват трафика, фильтры BPF, чтение флагов TCP, Wireshark/tshark, дамп HTTPS — конспект и задачи"
---

# 10. tcpdump и Wireshark — увидеть пакет глазами

> Роадмап → 2.5 Сети → утилиты **tcpdump**, **wireshark**.
> **После темы ты умеешь:** снять дамп с фильтром, прочитать вывод tcpdump построчно,
> найти в Wireshark хендшейк, ретрансмиссии и сброс соединения.
> ⭐ Это последний аргумент в споре «у нас всё работает» — пакеты не врут.

---

## 🗺️ Схема: где снимать дамп

```text:no-line-numbers
   Клиент ──► [ФАЙРВОЛ] ──► Балансировщик ──► Бэкенд
      ①                          ②                ③

   ① на клиенте  : ушёл ли запрос вообще
   ② на прокси   : дошёл ли до нас, что мы отправили дальше
   ③ на бэкенде  : дошло ли до него, что он ответил

   ⭐ Сравнение двух точек отвечает на главный вопрос:
      «пакет не дошёл» или «дошёл, но ответа не было»
```

---

## 1. tcpdump: базовый синтаксис

```bash
sudo tcpdump -i eth0                      # смотреть интерфейс
sudo tcpdump -i any                       # ⭐ все интерфейсы (включая docker/lo)
sudo tcpdump -D                           # список интерфейсов
```

| Флаг | Что делает |
|------|------------|
| `-i any` | Все интерфейсы |
| `-n` | ⭐ Не резолвить IP в имена (быстрее и честнее) |
| `-nn` | Не резолвить и порты |
| `-c 100` | Остановиться после N пакетов |
| `-v` / `-vv` | Подробнее (TTL, ID, флаги) |
| `-e` | Показать MAC-адреса (L2) |
| `-A` | Пакет как ASCII (удобно для HTTP) |
| `-X` | Hex + ASCII |
| `-s 0` | Снимать пакет целиком (в новых версиях по умолчанию) |
| `-w file.pcap` | ⭐ Писать в файл (для Wireshark) |
| `-r file.pcap` | Читать файл |
| `-t`, `-tttt` | Формат времени (`-tttt` — с датой) |
| `-Q in\|out` | Только входящие/исходящие |

```bash
# Рабочая формула, которую стоит запомнить
sudo tcpdump -i any -nn -c 200 -w /tmp/dump.pcap 'host 10.0.0.5 and port 443'
```

---

## 2. Фильтры (BPF) — самое важное

```bash
# По хостам и сетям
host 10.0.0.5
src host 10.0.0.5
dst host 10.0.0.5
net 192.168.56.0/24

# По портам
port 443
src port 5432
portrange 8000-8100

# По протоколам
tcp / udp / icmp / arp
icmp6

# Комбинации
'host 10.0.0.5 and port 443'
'tcp port 80 and not host 10.0.0.9'
'(src 10.0.0.5 or src 10.0.0.6) and dst port 5432'

# По флагам TCP (⭐ очень полезно)
'tcp[tcpflags] & tcp-syn != 0'                       # SYN — кто инициирует
'tcp[tcpflags] & tcp-rst != 0'                       # ⭐ RST — кто рвёт соединения
'tcp[tcpflags] & (tcp-syn|tcp-fin) != 0'             # начало и конец соединений

# По содержимому
'tcp port 80 and tcp[((tcp[12:1] & 0xf0) >> 2):4] = 0x47455420'   # HTTP GET
'udp port 53'                                         # DNS
'port 53 and host 8.8.8.8'
```

⚠️ Фильтр — в кавычках, иначе shell съест скобки и `|`.

---

## 3. Читаем вывод построчно

```text:no-line-numbers
13:45:22.123456 IP 192.168.56.10.51234 > 192.168.56.11.80: Flags [S], seq 1234567, win 64240, options [mss 1460,sackOK,TS val ...], length 0
    │              │              │       │             │      │        │             │
  время        src IP + порт      │   dst IP + порт   флаги   seq      окно        опции
                                  └─ направление
```

**Флаги в квадратных скобках:**

| Символ | Флаг |
|--------|------|
| `[S]` | SYN |
| `[S.]` | SYN+ACK (точка = ACK) |
| `[.]` | ACK |
| `[P.]` | PSH+ACK — данные |
| `[F.]` | FIN+ACK — закрытие |
| `[R]` / `[R.]` | ⭐ RST — сброс |

**Типовой здоровый обмен:**

```text:no-line-numbers
IP A.51234 > B.80: Flags [S],  seq 100          ← запрос соединения
IP B.80 > A.51234: Flags [S.], seq 900, ack 101 ← согласие
IP A.51234 > B.80: Flags [.],  ack 901          ← установлено
IP A.51234 > B.80: Flags [P.], length 78        ← HTTP-запрос
IP B.80 > A.51234: Flags [P.], length 1200      ← ответ
IP A.51234 > B.80: Flags [F.]                   ← закрытие
```

**Что видно при типовых проблемах:**

| Картина в дампе | Диагноз |
|-----------------|---------|
| Только `[S]`, ответа нет, повторы через 1, 2, 4 с | Пакеты дропаются (файрвол/маршрут) — клиент увидит таймаут |
| `[S]` → `[R.]` | Порт закрыт → `Connection refused` |
| Много одинаковых `seq` подряд | ⭐ Ретрансмиссии — потери в сети |
| `[R]` посреди сессии | Соединение сброшено (приложение, NAT, idle timeout) |
| `[F.]` сразу после установки | Приложение закрывает соединение (health-check или отказ) |
| Пакеты есть только на одной стороне | Проблема между точками: маршрут, NAT, файрвол |

---

## 4. Боевые однострочники

```bash
# Кто ломится на порт
sudo tcpdump -i any -nn 'tcp port 8080 and tcp[tcpflags] & tcp-syn != 0'

# Кто рвёт соединения (RST) — топ-аргумент в спорах с разработчиками
sudo tcpdump -i any -nn 'tcp[tcpflags] & tcp-rst != 0' -c 50

# HTTP-запросы в читаемом виде
sudo tcpdump -i any -nn -A -s0 'tcp port 80 and (((ip[2:2] - ((ip[0]&0xf)<<2)) - ((tcp[12]&0xf0)>>2)) != 0)'

# DNS-запросы и ответы
sudo tcpdump -i any -nn -s0 'udp port 53'

# ARP (см. тему 02)
sudo tcpdump -i eth1 -nn -e arp

# Трафик конкретного контейнера (через его veth или на bridge)
sudo tcpdump -i br-1a2b3c4d -nn

# Пишем с ротацией: 10 файлов по 100 МБ — чтобы не забить диск
sudo tcpdump -i any -nn -s0 -W 10 -C 100 -w /var/tmp/cap.pcap 'port 443'

# Только заголовки, но много: -s 96 экономит место
sudo tcpdump -i any -nn -s 96 -w /tmp/head.pcap
```

⚠️ **Дисциплина на проде:** всегда ограничивай дамп (`-c`, `-W/-C`, фильтр),
никогда не пиши в `/var/log` и не оставляй tcpdump «на ночь» без ротации.
Дамп содержит реальные данные пользователей — обращайся с ним как с персональными данными.

---

## 5. Wireshark и tshark

`tcpdump` — снять, `Wireshark` — разобрать. На сервере GUI нет:
снимаем `-w dump.pcap`, скачиваем `scp`, открываем локально.

```bash
sudo tcpdump -i any -nn -s0 -c 2000 -w /tmp/dump.pcap 'host 10.0.0.5'
# на своей машине:
scp server:/tmp/dump.pcap . && wireshark dump.pcap
```

**Фильтры отображения Wireshark (это НЕ синтаксис BPF!):**

| Задача | Фильтр |
|--------|--------|
| Только HTTP | `http` |
| Запросы | `http.request` |
| Коды 5xx | `http.response.code >= 500` |
| Конкретный хост | `ip.addr == 10.0.0.5` |
| Порт | `tcp.port == 443` |
| ⭐ Ретрансмиссии | `tcp.analysis.retransmission` |
| ⭐ Проблемы TCP | `tcp.analysis.flags` |
| Сбросы | `tcp.flags.reset == 1` |
| Медленные ответы | `http.time > 1` |
| TLS-хендшейк | `tls.handshake.type == 1` (ClientHello) |
| DNS-ответы с ошибкой | `dns.flags.rcode != 0` |

**Что искать в первую очередь:**
- `Statistics → Conversations` — кто с кем и сколько передал;
- `Statistics → Protocol Hierarchy` — из чего состоит трафик;
- правый клик → `Follow → TCP Stream` — ⭐ увидеть диалог целиком как текст;
- `Expert Information` — автоматически найденные проблемы (retransmissions, resets, dup ACK).

```bash
# tshark — Wireshark в консоли, когда GUI недоступен
tshark -r dump.pcap -q -z conv,tcp                 # сводка по соединениям
tshark -r dump.pcap -Y 'http.response.code >= 500' # фильтр отображения
tshark -r dump.pcap -Y tcp.analysis.retransmission | wc -l
tshark -r dump.pcap -T fields -e ip.src -e ip.dst -e tcp.dstport | sort | uniq -c | sort -rn | head
```

---

## 6. Дамп шифрованного трафика

HTTPS в дампе не читается — виден только TLS-хендшейк. Что с этим делать:

| Подход | Как |
|--------|-----|
| Смотреть метаданные | SNI в ClientHello виден открытым текстом: `tls.handshake.extensions_server_name` |
| Снимать до/после терминации | Дамп между nginx и бэкендом, где уже HTTP |
| Логи приложения | Часто быстрее и законнее, чем расшифровка |
| `SSLKEYLOGFILE` | Для отладки **своего** клиента: браузер/curl пишет сеансовые ключи, Wireshark расшифровывает |

```bash
SSLKEYLOGFILE=/tmp/keys.log curl https://example.com >/dev/null
# в Wireshark: Preferences → Protocols → TLS → (Pre)-Master-Secret log filename
```

---

## 💼 Как это в DevOps

- Дамп — финальный аргумент: «SYN уходит, SYN-ACK не приходит» закрывает спор
  между командами за минуту.
- Снятие дампа с двух сторон одновременно — стандартный приём при «пакеты теряются».
- В Kubernetes дамп снимают в сетевом namespace пода (`nsenter`/`netshoot`-контейнер) —
  иначе не видно ничего, кроме туннеля.
- Ретрансмиссии и `RST` из дампа — объективные метрики для разговора с сетевиками.
- Осторожно с персональными данными: дампы прода хранят как чувствительные файлы.

---

## 🧪 Мини-лаба

```bash
vagrant ssh web
sudo apt install -y tcpdump tshark

# 1. Три рукопожатия
sudo tcpdump -i any -nn -c 6 'host 192.168.56.11 and port 22' &
ssh -o StrictHostKeyChecking=no 192.168.56.11 true 2>/dev/null; wait

# 2. Закрытый порт: SYN → RST
sudo tcpdump -i any -nn -c 4 'host 192.168.56.11 and port 9999' &
nc -z -w2 192.168.56.11 9999; wait

# 3. Отфильтрованный порт: только SYN с повторами
# на app: sudo iptables -A INPUT -p tcp --dport 8088 -j DROP
sudo tcpdump -i any -nn -c 5 'host 192.168.56.11 and port 8088' &
nc -z -w6 192.168.56.11 8088; wait
# на app: sudo iptables -D INPUT -p tcp --dport 8088 -j DROP

# 4. Кто рвёт соединения
sudo tcpdump -i any -nn -c 10 'tcp[tcpflags] & tcp-rst != 0' &
for p in 9990 9991 9992; do nc -z -w1 192.168.56.11 $p; done; wait

# 5. HTTP в открытом виде
sudo tcpdump -i any -nn -A -s0 -c 12 'tcp port 80 and host 93.184.216.34' &
curl -s http://example.com >/dev/null; wait

# 6. DNS
sudo tcpdump -i any -nn -s0 -c 4 'udp port 53' &
dig +short example.com >/dev/null; wait

# 7. ARP и MAC (L2)
sudo ip neigh flush all
sudo tcpdump -i eth1 -nn -e -c 4 arp &
ping -c1 192.168.56.11 >/dev/null; wait

# 8. TLS: виден только хендшейк и SNI
sudo tcpdump -i any -nn -c 10 -w /tmp/tls.pcap 'port 443' &
curl -s https://example.com >/dev/null; wait
tshark -r /tmp/tls.pcap -Y 'tls.handshake.type == 1' \
  -T fields -e tls.handshake.extensions_server_name 2>/dev/null

# 9. Запись в файл и анализ через tshark
sudo tcpdump -i any -nn -s0 -c 200 -w /tmp/lab.pcap 'host 192.168.56.11' &
for i in $(seq 1 10); do ssh -o BatchMode=yes 192.168.56.11 true 2>/dev/null; done; wait
tshark -r /tmp/lab.pcap -q -z conv,tcp | head -12
tshark -r /tmp/lab.pcap -T fields -e ip.src -e ip.dst -e tcp.dstport | sort | uniq -c | sort -rn | head

# 10. Ретрансмиссии (искусственно)
sudo tc qdisc add dev eth1 root netem loss 20%
sudo tcpdump -i eth1 -nn -s0 -c 100 -w /tmp/loss.pcap 'host 192.168.56.11' &
scp -o BatchMode=yes /usr/lib/firmware/* 192.168.56.11:/tmp/ >/dev/null 2>&1 || \
  dd if=/dev/zero bs=1M count=5 2>/dev/null | ssh 192.168.56.11 'cat > /dev/null'
wait; sudo tc qdisc del dev eth1 root
tshark -r /tmp/loss.pcap -Y tcp.analysis.retransmission 2>/dev/null | wc -l

# 11. Ротация (как делать на проде)
sudo timeout 10 tcpdump -i any -nn -s 96 -W 3 -C 1 -w /var/tmp/rot.pcap 'port 22'
ls -lh /var/tmp/rot.pcap*

# 12. Уборка
sudo rm -f /tmp/*.pcap /var/tmp/rot.pcap*
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `tcpdump -i any -nn` | ⭐ Базовый захват без резолва |
| `-c N` | Остановиться после N пакетов |
| `-w file.pcap` / `-r file.pcap` | Записать / прочитать |
| `-A` / `-X` | ASCII / hex+ASCII |
| `-e` | Показать MAC (L2) |
| `-s 96` | Только заголовки (экономия места) |
| `-W 10 -C 100` | Ротация: 10 файлов по 100 МБ |
| `'host X and port Y'` | Базовый фильтр |
| `'tcp[tcpflags] & tcp-syn != 0'` | Только SYN |
| `'tcp[tcpflags] & tcp-rst != 0'` | ⭐ Только RST |
| `'udp port 53'` | DNS |
| `tshark -r f.pcap -q -z conv,tcp` | Сводка по соединениям |
| `tshark -r f.pcap -Y 'фильтр'` | Фильтр отображения |
| `tcp.analysis.retransmission` | Ретрансмиссии в Wireshark |
| `Follow → TCP Stream` | ⭐ Диалог целиком |

---

## 🧠 Что запомнить

1. `tcpdump -i any -nn` + фильтр — рабочая основа; `-n` обязателен, иначе DNS-резолв мешает.
2. Флаги: `[S]`, `[S.]`, `[.]`, `[P.]`, `[F.]`, `[R]` — по ним читается вся жизнь соединения.
3. Только SYN без ответа = пакеты дропаются; SYN → RST = порт закрыт.
4. Повторы с одинаковым seq — ретрансмиссии, объективный признак потерь.
5. Снимай дамп **с двух сторон**: это отвечает на вопрос «дошёл ли пакет».
6. На проде всегда ограничивай захват: фильтр, `-c`, ротация `-W/-C`, не в `/var/log`.
7. `-w` + Wireshark локально — нормальный рабочий процесс; на сервере — `tshark`.
8. Фильтры захвата (BPF) и фильтры отображения (Wireshark) — разный синтаксис.
9. HTTPS не читается, но SNI в ClientHello виден; для отладки своего клиента — `SSLKEYLOGFILE`.
10. Дамп содержит пользовательские данные — храни и передавай его как чувствительный файл.

---

## Задачи

> ⚠️ Снимать трафик можно только там, где ты имеешь на это право. Дамп прода = персональные данные.

---

### Блок A. Теория

**A1.** Зачем нужен флаг `-n` и что происходит без него?

<details><summary>Ответ</summary>

`-n` отключает обратный DNS-резолв адресов. Без него tcpdump на каждый адрес делает
PTR-запрос: вывод тормозит, добавляется собственный DNS-трафик (который тоже попадает в дамп),
а имена могут вводить в заблуждение.

</details>

**A2.** Чем `-i any` отличается от `-i eth0`? Когда это принципиально?

<details><summary>Ответ</summary>

`-i any` захватывает на всех интерфейсах, включая `lo` и docker-бриджи (в linux-cooked
формате, без полноценных MAC). `-i eth0` — только физический интерфейс. Принципиально,
когда трафик идёт через loopback или контейнерные интерфейсы — на `eth0` его не будет.

</details>

**A3.** Что означают `[S]`, `[S.]`, `[.]`, `[P.]`, `[F.]`, `[R]` в выводе?

<details><summary>Ответ</summary>

`[S]` — SYN, `[S.]` — SYN+ACK, `[.]` — чистый ACK, `[P.]` — PSH+ACK (есть данные),
`[F.]` — FIN+ACK (закрытие), `[R]`/`[R.]` — RST (сброс).

</details>

**A4.** Как в дампе выглядит: закрытый порт, отфильтрованный порт, ретрансмиссия, сброс сессии?

<details><summary>Ответ</summary>

Закрытый порт: `[S]` → `[R.]`. Отфильтрованный: только `[S]` с повторами через
1, 2, 4, 8 с и без ответа. Ретрансмиссия: повтор пакета с тем же `seq`.
Сброс сессии: `[R]` посреди установленного обмена.

</details>

**A5.** Чем фильтр захвата (BPF) отличается от фильтра отображения Wireshark?

<details><summary>Ответ</summary>

BPF применяется в ядре при захвате — уменьшает объём и нагрузку, синтаксис
`host/port/tcp[…]`. Фильтр отображения Wireshark применяется к уже снятому дампу,
синтаксис другой (`ip.addr == …`, `http.response.code >= 500`) и умеет анализ более высоких
уровней.

</details>

**A6.** Зачем `-s 96` и когда нужен полный размер пакета?

<details><summary>Ответ</summary>

`-s 96` сохраняет только заголовки — меньше объём и никакого содержимого пользователей.
Полный размер нужен, когда анализируешь содержимое (HTTP-тела, TLS-хендшейк целиком,
прикладные протоколы).

</details>

**A7.** Как настроить ротацию дампа и почему это обязательно на проде?

<details><summary>Ответ</summary>

`-W N -C размер_МБ -w файл` — циклическая запись N файлов. Без этого долгий захват
переполнит диск, а переполнение `/` на проде — самостоятельная авария.

</details>

**A8.** Почему дамп снимают с двух сторон и какой вопрос это решает?

<details><summary>Ответ</summary>

Чтобы понять, теряются пакеты по пути или сервер не отвечает: если на отправителе
SYN есть, а на получателе его нет — проблема в сети между ними (файрвол, маршрут, NAT).

</details>

**A9.** Что можно узнать из дампа HTTPS-трафика, а что нельзя?

<details><summary>Ответ</summary>

Видны: адреса, порты, объём и тайминги, факт и параметры TLS-хендшейка, SNI и
(до TLS 1.3) сертификат сервера. Не видно: URL, заголовки, тело, куки.

</details>

**A10.** Что такое `SSLKEYLOGFILE` и когда его применение допустимо?

<details><summary>Ответ</summary>

Переменная, в которую браузер/curl пишет сеансовые ключи TLS; Wireshark может
расшифровать трафик. Допустимо только для **своего** клиента и своей отладки,
никогда — для перехвата чужого трафика.

</details>

**A11.** Как снять дамп трафика конкретного контейнера или пода?

<details><summary>Ответ</summary>

Найти veth-интерфейс контейнера на хосте и снимать на нём, либо войти в сетевой
namespace: `sudo nsenter -t <pid> -n tcpdump -nn -i eth0`; в Kubernetes — sidecar/ephemeral
контейнер `netshoot` с `-n` namespace пода.

</details>

**A12.** Какие три вещи ты посмотришь в Wireshark первыми при разборе проблемы?

<details><summary>Ответ</summary>

`Statistics → Conversations` (кто с кем и сколько), `Expert Information`
(автоматически найденные проблемы), `Follow → TCP Stream` (диалог целиком).

</details>

---

### Блок B. «Что захватит фильтр»

```bash
B1.  tcpdump -i any -nn 'host 10.0.0.5'
B2.  tcpdump -i any -nn 'src 10.0.0.5 and dst port 443'
B3.  tcpdump -i any -nn 'tcp port 80 or tcp port 443'
B4.  tcpdump -i any -nn 'not port 22'
B5.  tcpdump -i any -nn 'tcp[tcpflags] & tcp-syn != 0'
B6.  tcpdump -i any -nn 'tcp[tcpflags] & tcp-rst != 0'
B7.  tcpdump -i eth1 -nn -e arp
B8.  tcpdump -i any -nn 'udp port 53 and host 8.8.8.8'
B9.  tcpdump -i any -nn -A 'tcp port 80'
B10. tcpdump -i any -nn -s0 -W 5 -C 50 -w /var/tmp/cap.pcap
```

- **B1.** Весь трафик с адресом 10.0.0.5 в любом направлении.
- **B2.** Пакеты от 10.0.0.5 на порт 443 (одно направление).
- **B3.** HTTP и HTTPS.
- **B4.** Весь трафик, кроме SSH (чтобы собственная сессия не мусорила).
- **B5.** Только SYN — кто инициирует соединения.
- **B6.** Только RST — кто рвёт соединения.
- **B7.** ARP на eth1 с MAC-адресами.
- **B8.** DNS-обмен с 8.8.8.8.
- **B9.** HTTP с содержимым в ASCII.
- **B10.** Захват с ротацией: 5 файлов по 50 МБ.

**B11.** Что означает такая последовательность?
```text:no-line-numbers
10:00:00.100 IP A.51234 > B.443: Flags [S], seq 1
10:00:01.100 IP A.51234 > B.443: Flags [S], seq 1
10:00:03.100 IP A.51234 > B.443: Flags [S], seq 1
```

<details><summary>Ответ</summary>

Клиент трижды повторяет SYN с экспоненциальной задержкой и не получает ответа:
пакеты отбрасываются (DROP на файрволе, неверный маршрут, хост выключен).
Клиент увидит `Connection timed out`.

</details>

**B12.** А такая?
```text:no-line-numbers
10:00:00.100 IP A.51234 > B.5432: Flags [S], seq 1
10:00:00.101 IP B.5432 > A.51234: Flags [R.], seq 1, ack 2
```

<details><summary>Ответ</summary>

Сервер немедленно ответил RST: хост доступен, но на порту 5432 никто не слушает
(или правило REJECT). Клиент увидит `Connection refused`.

</details>

---

### Блок C. Практика

**C1. Полный жизненный цикл соединения.** Сними дамп HTTP-запроса к соседней ВМ и выпиши
все пакеты с пояснением каждого: установка, запрос, ответ, закрытие.

<details><summary>Ответ</summary>

Ожидаемая последовательность: `[S]` → `[S.]` → `[.]` → `[P.]` (запрос) → `[.]` →
`[P.]` (ответ) → `[F.]` → `[.]` → `[F.]` → `[.]`. Каждый `[P.]` содержит `length > 0`.

</details>

**C2. Три сценария отказа.** Сними дампы для: закрытого порта, порта под `DROP`,
порта под `REJECT`. Опиши различия в дампе и в ошибке клиента.

<details><summary>Ответ</summary>

Закрытый — RST мгновенно (`Connection refused`); DROP — тишина и повторы SYN
(`Connection timed out`); REJECT — ICMP `administratively prohibited` или RST в зависимости
от `--reject-with` (клиент видит refused/unreachable).

</details>

**C3. HTTP в открытом виде.** Захвати HTTP-запрос и ответ через `-A`, найди заголовки
`Host`, `User-Agent`, код ответа. Затем повтори с HTTPS и покажи, что видно только хендшейк.

<details><summary>Ответ</summary>

В `-A` видны строки `GET / HTTP/1.1`, `Host: example.com`, `HTTP/1.1 200 OK`.
Для HTTPS — только `Client Hello`, `Server Hello`, `Application Data` без содержимого.

</details>

**C4. SNI в TLS.** Через `tshark` вытащи из дампа имя домена из ClientHello.
Объясни, почему это работает даже для зашифрованного трафика.

<details><summary>Ответ</summary>

`tshark -r dump.pcap -Y 'tls.handshake.type == 1' -T fields -e
tls.handshake.extensions_server_name`. SNI передаётся в открытом виде, потому что сервер
должен выбрать сертификат **до** установления шифрования.

</details>

**C5. Ретрансмиссии.** Добавь потери через `tc netem`, сними дамп при копировании файла,
посчитай ретрансмиссии через `tshark -Y tcp.analysis.retransmission`. Сравни с чистым каналом.

<details><summary>Ответ</summary>

На чистом канале ретрансмиссий 0-единицы; при `netem loss 20%` их десятки-сотни,
а скорость передачи падает многократно — видно работу контроля перегрузки.

</details>

**C6. Дамп с двух сторон.** Одновременно сними дампы на `web` и `app` при обращении
к закрытому файрволом порту. Покажи, что на `web` пакеты уходят, а на `app` их нет
(или наоборот). Сделай вывод, где именно теряется трафик.

<details><summary>Ответ</summary>

Если на `web` видны только исходящие SYN, а на `app` в дампе пусто — трафик режется
между ними (файрвол на пути, маршрут, security group). Если на `app` SYN видны, а ответа нет —
проблема на самом `app` (правило INPUT, сервис не слушает).

</details>

**C7. DNS.** Захвати DNS-запрос и ответ, найди: тип запроса, имя, TTL, все A-записи в ответе.
Затем сделай запрос к несуществующему домену и найди NXDOMAIN в дампе.

<details><summary>Ответ</summary>

В дампе видно `A? example.com` (запрос) и `A 93.184.216.34` (ответ) с TTL.
Для несуществующего имени в ответе будет `NXDomain`; в tshark — `dns.flags.rcode == 3`.

</details>

**C8. ARP.** Очисти ARP-кеш, сними дамп с `-e` и покажи broadcast-запрос и unicast-ответ
с MAC-адресами.

<details><summary>Ответ</summary>

`Request who-has 192.168.56.11 tell 192.168.56.10` с dst MAC `ff:ff:ff:ff:ff:ff`
и `Reply 192.168.56.11 is-at bb:bb:…` уже unicast'ом.

</details>

**C9. Анализ pcap.** Собери дамп на 500+ пакетов со смешанным трафиком и через `tshark`
посчитай: топ пар «источник → назначение», распределение по портам, число TCP-соединений,
количество RST.

<details><summary>Ответ</summary>

```bash
tshark -r lab.pcap -q -z conv,tcp
tshark -r lab.pcap -T fields -e tcp.dstport | sort | uniq -c | sort -rn | head
tshark -r lab.pcap -Y 'tcp.flags.syn==1 && tcp.flags.ack==0' | wc -l   # число попыток соединений
tshark -r lab.pcap -Y 'tcp.flags.reset==1' | wc -l
```

</details>

**C10. Ротация на проде.** Настрой захват с ротацией по 3 файла × 1 МБ, запусти на 30 секунд,
покажи получившиеся файлы и объясни, как это защищает от переполнения диска.

<details><summary>Ответ</summary>

`sudo timeout 30 tcpdump -i any -nn -s96 -W 3 -C 1 -w /var/tmp/rot.pcap`
создаст `rot.pcap0..2`, перезаписывая по кругу: объём на диске ограничен заранее и не зависит
от того, сколько трафика пришло и когда ты вспомнишь выключить захват.

</details>

**C11. Трафик контейнера.** Подними контейнер, найди его veth-интерфейс на хосте
и сними дамп именно его трафика. Альтернативно — зайди в его netns через `nsenter`.

<details><summary>Ответ</summary>

```bash
pid=$(docker inspect -f '{{.State.Pid}}' myctr)
sudo nsenter -t "$pid" -n tcpdump -i eth0 -nn -c 20
# либо найти veth: ip link | grep -A1 veth ; и снимать на нём/на бридже
```

</details>

---

### Блок D. Инциденты

**D1.** Разработчик утверждает, что его сервис не получает запросы, а фронтенд — что
отправляет их. Как закрыть спор за 5 минут?

<details><summary>Ответ</summary>

Снять дамп на бэкенде с фильтром по порту и IP фронтенда: если SYN и HTTP-запросы
видны — сервис их получает (проблема в приложении); если нет — снять дамп на фронтенде:
уходят ли пакеты. Дальше — поиск точки, где они пропадают.

</details>

**D2.** Соединения к БД рвутся раз в несколько минут. В дампе видно `[R]` со стороны,
которая не является ни клиентом, ни сервером. Кто это может быть?

<details><summary>Ответ</summary>

Промежуточное устройство: NAT/conntrack с истёкшим таймаутом, файрвол, облачный
балансировщик или IDS. Признак — RST с TTL, не соответствующим ни одной из сторон,
и отсутствие такого пакета в дампе на второй стороне.

</details>

**D3.** В дампе много `[F.]` сразу после установки соединения, каждые 10 секунд, с одного IP.
Что это, скорее всего?

<details><summary>Ответ</summary>

Health-check балансировщика или мониторинга: подключился, проверил, закрыл.
Подтверждается периодичностью, коротким обменом и адресом источника.

</details>

**D4.** Копирование файла идёт медленно; в дампе — регулярные ретрансмиссии и dup ACK.
Что это означает и куда эскалировать?

<details><summary>Ответ</summary>

Потери в сети: TCP повторяет сегменты и снижает окно. Эскалировать сетевикам
или провайдеру, приложив `mtr -r -c 200` и счётчики `ip -s link`; проверить дуплекс,
ошибки интерфейсов и MTU.

</details>

**D5.** В Kubernetes tcpdump на ноде показывает только VXLAN-трафик. Как посмотреть
реальные пакеты пода?

<details><summary>Ответ</summary>

Снимать внутри сетевого namespace пода: ephemeral-контейнер `kubectl debug`
с образом `netshoot`, либо `nsenter -t <pid пода> -n tcpdump` на ноде, либо фильтровать
по внутреннему IP пода после декапсуляции (`-i vxlan0`/cni-интерфейс).

</details>

**D6.** Тебя просят «снять дамп на проде на сутки». Какие условия ты поставишь?

<details><summary>Ответ</summary>

Чёткий фильтр (хост/порт), ограничение по объёму (`-W/-C`), `-s 96`, запись
на отдельный раздел, согласование с безопасностью, автоматическое завершение (`timeout`),
план удаления файлов и правила обращения с данными.

</details>

**D7.** В дампе видно, что клиент отправляет `ClientHello`, а сервер сразу отвечает `[R]`.
Что это значит?

<details><summary>Ответ</summary>

Сервер (или устройство на пути) отверг TLS-соединение сразу: нет сертификата
для запрошенного SNI, нет общих версий/шифров, сработал firewall/DPI по SNI,
или на порту не TLS-сервис.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как снять дамп трафика между двумя хостами?

<details><summary>Ответ</summary>

`sudo tcpdump -i any -nn 'host A and host B'` (+ `-w file.pcap` для анализа).

</details>

**2.** Что означают флаги в выводе tcpdump?

<details><summary>Ответ</summary>

`[S]` SYN, `[S.]` SYN-ACK, `[.]` ACK, `[P.]` данные, `[F.]` закрытие, `[R]` сброс.

</details>

**3.** Как отличить «пакет не дошёл» от «ответа не было»?

<details><summary>Ответ</summary>

Снять дамп с обеих сторон: есть ли пакет на принимающей стороне.

</details>

**4.** Как найти ретрансмиссии?

<details><summary>Ответ</summary>

`tshark -Y tcp.analysis.retransmission` или повторяющиеся `seq` в tcpdump.

</details>

**5.** Что можно узнать из дампа HTTPS?

<details><summary>Ответ</summary>

Адреса, порты, объёмы, тайминги, факт хендшейка и SNI; содержимое — нет.

</details>

**6.** Как ограничить размер дампа на проде?

<details><summary>Ответ</summary>

Фильтр + `-c` + `-s 96` + ротация `-W/-C` + `timeout`.

</details>

**7.** Как посмотреть трафик контейнера?

<details><summary>Ответ</summary>

Через veth-интерфейс на хосте или `nsenter -t <pid> -n tcpdump` в namespace контейнера.

</details>

---

### 🎯 Чек-лист

- [ ] Снимаю дамп с фильтром и читаю флаги без подсказки
- [ ] Отличаю DROP от REJECT по картине в дампе
- [ ] Умею снимать с двух сторон и делать вывод, где теряется трафик
- [ ] Нахожу ретрансмиссии и RST
- [ ] Использую `-w` + Wireshark/`tshark` для анализа
- [ ] Знаю, что видно и что не видно в HTTPS-дампе
- [ ] Настраиваю ротацию и не забиваю диск на проде
- [ ] Снял дамп трафика контейнера
