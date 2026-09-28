---
title: "05. DNS"
description: "DNS как протокол: рекурсия, типы записей, TTL и кеширование, resolv.conf/ndots, DNS в Docker и Kubernetes"
---

# 05. DNS — как имя превращается в адрес

> Роадмап → 2.5 Сети → протокол **DNS**. Вопрос с собеса: *«Как работает DNS?»*
> Базовое было в [Linux/22](/linux/22-dns) — здесь DNS **как протокол**:
> рекурсия, кеши, TTL, UDP/TCP, и DNS внутри Docker и Kubernetes.

---

## 🗺️ Схема: полный путь резолва `www.example.com`

```text:no-line-numbers
  Приложение
      │ getaddrinfo()
      ▼
  ① /etc/nsswitch.conf → порядок источников (files → dns)
      │
      ├─► /etc/hosts            ← если есть запись, поиск закончен
      │
      ▼
  ② Локальный кеш резолвера (systemd-resolved / nscd / браузер)
      │ промах
      ▼
  ③ Рекурсивный резолвер (провайдер, 8.8.8.8, corp-DNS) — из /etc/resolv.conf
      │ промах
      ├──► ROOT (.)            : «за .com спроси у a.gtld-servers.net»
      ├──► TLD (.com)          : «за example.com спроси у ns1.example.com»
      ├──► Authoritative NS    : «www.example.com = 93.184.216.34, TTL 300»
      │
      ▼ кеширует ответ на TTL секунд
  ④ Ответ клиенту → соединение по IP
```

⭐ **Ответ на собесе за 30 секунд:** «Клиент спрашивает у рекурсивного резолвера, тот при
промахе кеша идёт по цепочке: корневые серверы → серверы зоны .com → авторитетный сервер домена,
получает запись, кеширует её на время TTL и отдаёт клиенту. Клиент делает один запрос,
всю рекурсию выполняет резолвер».

---

## 1. DNS как протокол

| Свойство | Значение |
|----------|----------|
| Порт | **53** — UDP и TCP |
| UDP | Обычные запросы (быстро, без установки соединения) |
| TCP | ⭐ Когда ответ > 512 байт (без EDNS0), зонные передачи (AXFR), DNSSEC |
| EDNS0 | Расширение: UDP-ответы до 4096 байт |
| DoT / DoH | DNS over TLS (853) / over HTTPS (443) — шифрование запросов |

⚠️ Если в файрволе открыт только UDP/53, крупные ответы (много записей, DNSSEC) будут
обрезаться: клиент получает флаг `TC` (truncated) и должен повторить по TCP — а он закрыт.
Симптом: «часть доменов резолвится, часть — нет».

---

## 2. Типы записей

| Тип | Что содержит | Пример использования |
|-----|--------------|----------------------|
| `A` | IPv4-адрес | `example.com → 93.184.216.34` |
| `AAAA` | IPv6-адрес | ⭐ Причина «медленных» соединений при кривом IPv6 |
| `CNAME` | Алиас на другое имя | `www → example.com`; **нельзя на вершине зоны** |
| `MX` | Почтовые серверы + приоритет | Доставка почты |
| `NS` | Авторитетные серверы зоны | Делегирование |
| `TXT` | Произвольный текст | SPF, DKIM, верификация домена, ACME-challenge |
| `SRV` | Сервис: порт + хост + приоритет | Kubernetes, Consul, Active Directory |
| `PTR` | Обратная зона: IP → имя | Репутация почты, логи |
| `SOA` | Параметры зоны: серийник, TTL, refresh | Проверка синхронизации зон |
| `CAA` | Кто может выпускать сертификаты | Защита от левых сертификатов |

```bash
dig example.com A +short
dig example.com MX
dig example.com TXT
dig +trace example.com          # ⭐ показать всю цепочку от корня — лучший инструмент отладки
dig @8.8.8.8 example.com        # спросить конкретный сервер
dig -x 93.184.216.34            # обратный запрос (PTR)
dig example.com SOA +short      # серийник зоны
```

---

## 3. Чтение вывода `dig`

```text:no-line-numbers
;; flags: qr rd ra; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 1
;; ANSWER SECTION:
example.com.    276    IN    A    93.184.216.34
                 ↑              ↑
              TTL (сек)      тип записи
;; Query time: 24 msec
;; SERVER: 127.0.0.53#53(127.0.0.53)
```

| Флаг | Значение |
|------|----------|
| `qr` | Это ответ (не запрос) |
| `rd` | Recursion Desired — клиент просит рекурсию |
| `ra` | Recursion Available — сервер умеет рекурсию |
| `aa` | ⭐ Authoritative Answer — ответ от авторитетного сервера, не из кеша |
| `tc` | Truncated — ответ обрезан, нужен TCP |

**Коды ответа (RCODE):**

| Код | Значение | Что делать |
|-----|----------|------------|
| `NOERROR` | Успех (может быть с пустым ANSWER — «имя есть, записи такого типа нет») |
| `NXDOMAIN` | ⭐ Имени не существует | Опечатка, не создана запись, не делегирована зона |
| `SERVFAIL` | ⭐ Сбой резолвера или зоны | Проблема у DNS-сервера, DNSSEC, недоступность авторитетных NS |
| `REFUSED` | Сервер отказал | Не обслуживает этот клиент/зону (ACL) |

⭐ Разница NXDOMAIN vs SERVFAIL — частый вопрос: первое означает «точно нет такого имени»,
второе — «не смог узнать»; лечатся они совершенно по-разному.

---

## 4. TTL и кеширование — источник «магии»

```text:no-line-numbers
TTL=300 → запись живёт в кешах 5 минут после получения.
Сменил IP, а трафик всё ещё идёт на старый адрес? Ждёшь TTL.
```

**Правило миграций:** за сутки до переключения уменьшить TTL до 60 секунд, переключить,
убедиться, что всё работает, вернуть TTL обратно. Иначе часть клиентов будет ходить
на старый адрес несколько часов.

**Отрицательное кеширование** (negative caching) — NXDOMAIN тоже кешируется, на время из
поля SOA `minimum`. Поэтому «создал запись, а она не появляется» — это чаще всего
закешированный NXDOMAIN.

```bash
# Где кеш на Linux
resolvectl statistics                 # статистика кеша systemd-resolved
sudo resolvectl flush-caches          # ⭐ сбросить кеш
resolvectl query example.com
systemd-resolve --status 2>/dev/null || resolvectl status
```

---

## 5. Клиентская часть: resolv.conf, nsswitch, search

```bash
cat /etc/resolv.conf
# nameserver 127.0.0.53   ← stub-резолвер systemd-resolved (не настоящий сервер!)
# search example.com internal
# options ndots:5 timeout:2 attempts:2

cat /etc/nsswitch.conf | grep hosts
# hosts: files dns   ← сначала /etc/hosts, потом DNS
```

| Параметр | Смысл |
|----------|-------|
| `nameserver` | Куда слать запросы (максимум 3, перебираются по порядку) |
| `search` | Домены, которые дописываются к коротким именам |
| `options ndots:N` | ⭐ Если в имени меньше N точек — сначала пробовать с `search`-суффиксами |
| `options timeout:2 attempts:2` | Таймаут и число попыток |

⭐ **`ndots:5` в Kubernetes** — знаменитая причина «тормозящего DNS»: запрос `api.github.com`
(2 точки) сначала перебирает `api.github.com.default.svc.cluster.local`, `...svc.cluster.local`,
`...cluster.local` и только потом идёт наружу — 3 лишних NXDOMAIN на каждый запрос.

```bash
getent hosts example.com        # ⭐ резолв ТАК ЖЕ, как это делает приложение (через nsswitch)
dig example.com +short          # dig идёт напрямую в DNS, мимо /etc/hosts!
```

⚠️ Классическая ловушка: `dig` показывает правильный адрес, а приложение ходит не туда —
потому что в `/etc/hosts` есть запись, которую `dig` не видит. Всегда сверяй `getent hosts`.

---

## 6. DNS в Docker и Kubernetes

**Docker:** у каждого контейнера в пользовательской сети есть встроенный DNS `127.0.0.11`,
который резолвит **имена контейнеров и сервисов compose**; неизвестные имена форвардятся
на DNS хоста.

```bash
docker run --rm --network labnet alpine cat /etc/resolv.conf   # nameserver 127.0.0.11
docker run --rm --network labnet alpine nslookup other-container
```

**Kubernetes:** CoreDNS резолвит сервисы по схеме

```text:no-line-numbers
<service>.<namespace>.svc.cluster.local
   web.prod.svc.cluster.local → ClusterIP
   headless-сервис → список IP подов (A-записи)
   SRV-записи для портов: _http._tcp.web.prod.svc.cluster.local
```

```bash
kubectl run -it --rm dnsutils --image=registry.k8s.io/e2e-test-images/jessie-dnsutils:1.3 -- bash
# внутри: nslookup kubernetes.default ; dig +search web.prod
kubectl -n kube-system logs -l k8s-app=kube-dns --tail=50
```

Типичные k8s-проблемы: `ndots:5` (лишние запросы), перегрузка CoreDNS, `NXDOMAIN` из-за
неверного namespace в имени, отсутствие `NodeLocal DNSCache` при высокой нагрузке.
Подробнее — в блоке Kubernetes (сетевая модель).

---

## 7. Алгоритм «не резолвится»

```text:no-line-numbers
1. getent hosts имя          → так видит приложение (учитывает /etc/hosts и nsswitch)
2. cat /etc/hosts            → нет ли «залипшей» записи
3. cat /etc/resolv.conf      → какой сервер, какой search, какой ndots
4. dig имя                   → что отвечает текущий резолвер (RCODE!)
5. dig @8.8.8.8 имя          → проблема в нашем резолвере или в самой зоне?
6. dig +trace имя            → на каком этапе цепочки рвётся
7. dig имя SOA / NS          → правильные ли NS, совпадает ли серийник на разных серверах
8. resolvectl flush-caches   → снять влияние кеша (и вспомнить про TTL)
9. ss -u / tcpdump port 53   → уходят ли запросы вообще (файрвол?)
```

---

## 💼 Как это в DevOps

- Половина инцидентов «всё сломалось после переезда» — это TTL и кеши.
- `dig +trace` и `dig @сервер` — инструменты, которыми отличают «наш резолвер сломан»
  от «зона сломана у владельца домена».
- DNS — самая частая причина медленного старта контейнеров и подов (`ndots`, таймауты).
- Сертификаты Let's Encrypt выпускаются через DNS-01 challenge (TXT-запись) — тема [07](/network/07-tls).
- Service discovery в k8s/Consul — это DNS: SRV и A-записи.
- Мониторить DNS обязательно: latency резолва и доля SERVFAIL — ранние индикаторы аварии.

---

## 🧪 Мини-лаба

```bash
vagrant ssh web
sudo apt install -y dnsutils

# 1. Как резолвит система и чем это отличается от dig
getent hosts example.com
dig +short example.com
echo "1.2.3.4 example.com" | sudo tee -a /etc/hosts
getent hosts example.com          # 1.2.3.4 ← приложение пойдёт СЮДА
dig +short example.com            # реальный IP ← dig не смотрит /etc/hosts
sudo sed -i '/1.2.3.4 example.com/d' /etc/hosts

# 2. Типы записей
dig example.com A +short
dig example.com MX +short
dig example.com TXT +short
dig example.com NS +short
dig example.com SOA +short
dig -x 8.8.8.8 +short

# 3. Полная цепочка от корня
dig +trace example.com | grep -E '^\S+\s+[0-9]+\s+IN\s+(NS|A)' | head -12

# 4. Флаги и коды ответа
dig example.com | grep -E 'flags|status'
dig несуществующее-имя-12345.com | grep status      # NXDOMAIN
dig @192.168.56.11 example.com | grep -E 'status|timed'  # SERVFAIL/таймаут

# 5. TTL в действии
dig example.com | awk '/ANSWER SECTION/{getline; print "TTL:", $2}'
sleep 5; dig example.com | awk '/ANSWER SECTION/{getline; print "TTL:", $2}'   # уменьшился — ответ из кеша
sudo resolvectl flush-caches
dig example.com | awk '/ANSWER SECTION/{getline; print "TTL после сброса:", $2}'

# 6. Кто наш резолвер
cat /etc/resolv.conf
resolvectl status | head -20
resolvectl statistics

# 7. UDP и TCP
dig example.com +short                 # по UDP
dig example.com +tcp +short            # принудительно TCP
sudo tcpdump -i any -n -c 4 port 53 &
dig +short example.com >/dev/null; wait

# 8. search и ndots
grep -E 'search|ndots' /etc/resolv.conf
dig +search app | head -3 2>/dev/null || echo "короткое имя резолвится через search-суффиксы"

# 9. Замер скорости резолва
for i in 1 2 3; do dig example.com | awk '/Query time/{print $4" ms"}'; done
sudo resolvectl flush-caches; dig example.com | awk '/Query time/{print "холодный кеш:", $4" ms"}'

# 10. Docker DNS (если есть docker)
docker network create dnslab >/dev/null 2>&1
docker run -d --name svc --network dnslab nginx:alpine >/dev/null 2>&1
docker run --rm --network dnslab alpine sh -c 'cat /etc/resolv.conf; nslookup svc' 2>/dev/null
docker rm -f svc >/dev/null 2>&1; docker network rm dnslab >/dev/null 2>&1
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `getent hosts имя` | ⭐ Резолв так, как это делает приложение |
| `dig имя +short` | Быстрый ответ |
| `dig имя ТИП` | Запись конкретного типа (A, MX, TXT, NS, SOA) |
| `dig @сервер имя` | Спросить конкретный DNS-сервер |
| `dig +trace имя` | ⭐ Вся цепочка от корня |
| `dig -x IP` | Обратный запрос (PTR) |
| `dig имя +tcp` | Принудительно по TCP |
| `dig имя \| grep status` | Код ответа (NOERROR/NXDOMAIN/SERVFAIL) |
| `resolvectl status` / `statistics` | Настройки и статистика резолвера |
| `resolvectl flush-caches` | Сбросить кеш |
| `cat /etc/resolv.conf` | Серверы, search, ndots |
| `tcpdump -n port 53` | Видеть DNS-трафик |

---

## 🧠 Что запомнить

1. Резолвинг: hosts → кеш → рекурсивный резолвер → корень → TLD → авторитетный сервер.
2. DNS работает по UDP **и** TCP на порту 53; TCP нужен для больших ответов и AXFR.
3. `NXDOMAIN` — имени нет; `SERVFAIL` — не смог узнать. Это разные поломки.
4. TTL определяет, сколько ответ живёт в кешах: перед миграцией TTL понижают заранее.
5. Отрицательные ответы тоже кешируются — «запись создал, а её не видно».
6. `dig` не смотрит `/etc/hosts`, а приложение смотрит: сверяй через `getent hosts`.
7. `dig +trace` показывает, на каком звене цепочки ломается резолв.
8. `search` + `ndots:5` в Kubernetes порождают лишние запросы и «тормоза» DNS.
9. Docker даёт контейнерам встроенный DNS `127.0.0.11`, k8s — CoreDNS с именами
   `svc.namespace.svc.cluster.local`.
10. CNAME нельзя ставить в вершине зоны; для этого есть ALIAS/ANAME у провайдеров.

---

## Задачи

> Базовое — [Linux/22](/linux/22-dns).
> ⭐ «Как работает DNS?» — вопрос, который задают почти всегда.

---

### Блок A. Теория

**A1.** Опиши полный путь резолва `www.example.com` от вызова приложения до IP.

<details><summary>Ответ</summary>

Приложение вызывает `getaddrinfo()` → `nsswitch.conf` задаёт порядок источников →
`/etc/hosts` → локальный кеш (systemd-resolved) → рекурсивный резолвер из `resolv.conf` →
при промахе он идёт к корневым серверам, затем к серверам TLD, затем к авторитетным NS зоны →
ответ кешируется на TTL и возвращается клиенту.

</details>

**A2.** Чем рекурсивный резолвер отличается от авторитетного сервера?

<details><summary>Ответ</summary>

Рекурсивный принимает запрос клиента и сам проходит всю цепочку, кешируя результат.
Авторитетный хранит саму зону и отвечает только за неё (флаг `aa`).

</details>

**A3.** По каким протоколам и портам работает DNS? Когда используется TCP?

<details><summary>Ответ</summary>

Порт 53, UDP и TCP. TCP — когда ответ не помещается в UDP-датаграмму (флаг `tc`),
для зонных передач AXFR/IXFR и часто для DNSSEC.

</details>

**A4.** Что такое EDNS0 и зачем он нужен?

<details><summary>Ответ</summary>

Расширение протокола, позволяющее UDP-ответам быть больше 512 байт (обычно до 4096)
и передавать доп. флаги (в т.ч. для DNSSEC), уменьшая число переходов на TCP.

</details>

**A5.** Назови 8 типов записей и для чего каждая.

<details><summary>Ответ</summary>

A — IPv4; AAAA — IPv6; CNAME — алиас; MX — почтовые серверы; NS — авторитетные серверы;
TXT — текст (SPF/DKIM/верификация/ACME); SRV — сервис с портом; PTR — обратная запись;
SOA — параметры зоны; CAA — кому можно выпускать сертификаты.

</details>

**A6.** Почему CNAME нельзя разместить на вершине зоны (`example.com`)?

<details><summary>Ответ</summary>

По стандарту CNAME не может сосуществовать с другими записями того же имени,
а на вершине зоны обязаны быть SOA и NS. Провайдеры предлагают нестандартные ALIAS/ANAME/
CNAME-flattening.

</details>

**A7.** Что означают флаги `aa`, `rd`, `ra`, `tc` в ответе dig?

<details><summary>Ответ</summary>

`aa` — ответ авторитетный (не из кеша); `rd` — клиент просил рекурсию; `ra` — сервер
её поддерживает; `tc` — ответ обрезан, нужен повтор по TCP.

</details>

**A8.** Разница NXDOMAIN, SERVFAIL, REFUSED и NOERROR с пустым ANSWER?

<details><summary>Ответ</summary>

NXDOMAIN — такого имени нет; SERVFAIL — резолвер не смог получить ответ (сбой зоны,
недоступность NS, DNSSEC); REFUSED — сервер отказался обслуживать запрос (ACL);
NOERROR с пустым ANSWER — имя существует, но записей запрошенного типа нет
(например, есть A, а спрашивали AAAA).

</details>

**A9.** Что такое TTL и как его используют при миграции сервиса?

<details><summary>Ответ</summary>

Время жизни записи в кешах. Перед миграцией TTL снижают (например, до 60 с) заранее —
минимум за время старого TTL, переключают, проверяют, затем возвращают обратно.

</details>

**A10.** Что такое отрицательное кеширование и где хранится его длительность?

<details><summary>Ответ</summary>

Кеширование отрицательных ответов (NXDOMAIN). Длительность берётся из поля
`minimum` записи SOA зоны (и ограничивается TTL SOA).

</details>

**A11.** Чем `getent hosts` отличается от `dig`? Почему это важно?

<details><summary>Ответ</summary>

`getent hosts` идёт через NSS — учитывает `/etc/hosts`, mDNS и прочие источники,
то есть повторяет путь приложения. `dig` общается напрямую с DNS-сервером и `/etc/hosts`
игнорирует. Поэтому расхождение между ними мгновенно указывает на локальную запись.

</details>

**A12.** Что делает `options ndots:5` и почему это проблема в Kubernetes?

<details><summary>Ответ</summary>

Если в имени меньше `ndots` точек, резолвер сначала перебирает `search`-суффиксы.
В k8s `ndots:5` означает, что `api.github.com` (2 точки) сперва пробуется как
`api.github.com.<ns>.svc.cluster.local` и т. д. — лишние NXDOMAIN-запросы, нагрузка на CoreDNS
и задержки. Лечится `dnsConfig` с меньшим ndots или точкой в конце имени (`api.github.com.`).

</details>

**A13.** Как устроен DNS в Docker? Какой адрес у встроенного резолвера?

<details><summary>Ответ</summary>

В пользовательских сетях контейнер получает `nameserver 127.0.0.11` — встроенный DNS
Docker, который резолвит имена контейнеров/сервисов в этой сети, остальное форвардит
на резолверы хоста.

</details>

**A14.** По какой схеме именуются сервисы в Kubernetes?

<details><summary>Ответ</summary>

`<service>.<namespace>.svc.cluster.local`; для headless-сервисов — A-записи подов,
плюс SRV-записи вида `_port._proto.service.namespace.svc.cluster.local`.

</details>

**A15.** Что такое DoT и DoH?

<details><summary>Ответ</summary>

DNS over TLS (порт 853) и DNS over HTTPS (443) — шифрование DNS-запросов,
чтобы провайдер/посредник не видел и не подменял их.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  dig example.com +short
B2.  dig @1.1.1.1 example.com
B3.  dig +trace example.com
B4.  dig example.com MX +short
B5.  dig -x 8.8.8.8
B6.  dig example.com SOA +short
B7.  dig example.com +tcp
B8.  getent hosts example.com
B9.  resolvectl flush-caches
B10. resolvectl statistics
B11. tcpdump -n port 53
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Только значение A-записи.
B2.  Запрос к конкретному резолверу (Cloudflare) — проверка «у нас или у всех».
B3.  Полная цепочка делегирования от корня.
B4.  Почтовые серверы с приоритетами.
B5.  Обратный PTR-запрос.
B6.  Параметры зоны, включая серийник.
B7.  Запрос по TCP (проверка, не режется ли UDP).
B8.  Резолв средствами NSS, как это делает приложение.
B9.  Очистка кеша systemd-resolved.
B10. Статистика кеша: попадания/промахи.
B11. Просмотр DNS-трафика в реальном времени.
```

</details>

**B12.** Что значит каждая строка ответа:
```text:no-line-numbers
;; flags: qr rd ra; QUERY: 1, ANSWER: 2, AUTHORITY: 0
example.com.  76  IN  A  93.184.216.34
;; Query time: 0 msec
```

<details><summary>Ответ</summary>

Флаги: ответ (qr), запрашивалась и доступна рекурсия (rd/ra), авторитетности нет —
ответ из кеша; две записи в ANSWER; TTL 76 секунд (уже «подтаял» в кеше);
`Query time: 0 msec` — ответ пришёл из локального кеша.

</details>

---

### Блок C. Практика

**C1. Цепочка резолва.** Прогони `dig +trace` для любого домена и выпиши: какие корневые
серверы отвечали, кто отвечал за TLD, кто оказался авторитетным сервером зоны.

<details><summary>Ответ</summary>

В выводе `+trace` последовательно видно: NS корня (`.`), NS зоны `com.`,
NS домена и, наконец, строка с A-записью от авторитетного сервера (с флагом отсутствия
рекурсии). Полезно: на каждом шаге видно, кто делегирует дальше.

</details>

**C2. hosts vs DNS.** Добавь в `/etc/hosts` неверную запись для существующего домена.
Покажи разницу между `dig` и `getent hosts`, затем — что `curl` пойдёт по записи из hosts.
Опиши, как этот эффект выглядит в реальном инциденте.

<details><summary>Ответ</summary>

После записи в `/etc/hosts`: `getent hosts` и `curl` идут на подставленный адрес,
`dig` показывает реальный. В инцидентах это выглядит как «в тестах всё правильно
(dig), а приложение упорно ходит не туда» — обычно наследие отладки или Ansible-шаблона.

</details>

**C3. Все типы записей.** Для реального домена (например, `github.com`) собери A, AAAA, MX,
NS, TXT, SOA, CAA. Объясни, что означает каждая найденная TXT-запись.

<details><summary>Ответ</summary>

`dig github.com A/AAAA/MX/NS/TXT/SOA/CAA +short`. TXT обычно содержит SPF
(`v=spf1 …`), подтверждения владения доменом для сервисов и ключи DKIM.

</details>

**C4. Кеш и TTL.** Сделай запрос, зафиксируй TTL, повтори через 10 секунд, покажи уменьшение.
Сбрось кеш и покажи, что TTL снова стал максимальным. Объясни, где именно был кеш.

<details><summary>Ответ</summary>

TTL уменьшается с каждой секундой, пока запись лежит в кеше; после
`resolvectl flush-caches` возвращается исходное значение от авторитетного сервера.
Кеш был в systemd-resolved (`127.0.0.53`).

</details>

**C5. Диагностика чужой зоны.** Найди авторитетные NS домена и спроси **каждый** из них
напрямую. Сравни ответы и серийники SOA. Что означает расхождение серийников?

<details><summary>Ответ</summary>

`dig example.com NS +short`, затем `dig @<каждый NS> example.com SOA +short`.
Расхождение серийников означает, что зона не синхронизирована между мастером и слейвами:
часть клиентов получает старые данные.

</details>

**C6. Свой DNS-сервер.** Подними `dnsmasq` (или CoreDNS в докере) на ВМ `web`,
заведи зону `lab.local` с записями `app.lab.local → 192.168.56.11` и wildcard.
Настрой ВМ `app` использовать его и проверь резолв.

<details><summary>Ответ</summary>

```bash
sudo apt install -y dnsmasq
echo -e "address=/app.lab.local/192.168.56.11\naddress=/.lab.local/192.168.56.10" \
  | sudo tee /etc/dnsmasq.d/lab.conf
sudo systemctl restart dnsmasq
dig @192.168.56.10 app.lab.local +short
# на app: sudo resolvectl dns eth1 192.168.56.10 && resolvectl query app.lab.local
```

</details>

**C7. Сломай резолвинг.** По очереди воспроизведи и почини: (1) неверный nameserver;
(2) DNS-сервер недоступен (DROP на 53 порту); (3) закешированный NXDOMAIN;
(4) неверная запись в `/etc/hosts`. Для каждого случая укажи характерный симптом и время реакции.

<details><summary>Ответ</summary>

(1) Неверный nameserver — таймаут `timeout:2 attempts:2`, затем SERVFAIL;
(2) DROP на 53 — запросы уходят, ответов нет, всё «висит» несколько секунд;
(3) закешированный NXDOMAIN — мгновенный ответ «нет такого имени», лечится ожиданием
или сбросом кеша; (4) hosts-запись — мгновенный неверный адрес, dig при этом корректен.

</details>

**C8. search и ndots.** Добавь `search lab.local` и `options ndots:5`, сделай запрос
короткого имени и имени с двумя точками, посмотри в tcpdump, сколько реальных запросов ушло.
Объясни, почему в k8s это создаёт нагрузку.

<details><summary>Ответ</summary>

В tcpdump видно несколько запросов подряд с суффиксами search перед «настоящим».
Для имени с 5+ точками или с точкой в конце — один запрос. Это и есть причина
трёхкратной нагрузки на CoreDNS в кластерах.

</details>

**C9. Скрипт проверки DNS.** `dnscheck.sh <домен>`: сравнивает ответы локального резолвера,
8.8.8.8 и авторитетного NS; печатает TTL, RCODE и время ответа; возвращает ненулевой код,
если ответы расходятся.

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
set -uo pipefail
d="${1:?нужен домен}"
local_ip=$(dig +short "$d" | tail -1)
pub_ip=$(dig @8.8.8.8 +short "$d" | tail -1)
ns=$(dig +short NS "$d" | head -1)
auth_ip=$(dig @"${ns:-8.8.8.8}" +short "$d" | tail -1)
printf 'локальный: %s\nпубличный: %s\nавторитет: %s (%s)\n' "$local_ip" "$pub_ip" "$auth_ip" "$ns"
[[ "$local_ip" == "$pub_ip" && "$pub_ip" == "$auth_ip" ]] || { echo "РАСХОЖДЕНИЕ"; exit 1; }
```

</details>

**C10. Мониторинг DNS.** Сделай скрипт, который раз в 10 секунд измеряет время резолва
и пишет метрику в формате Prometheus textfile (связь с темой [bash 26](/linux/26-bash-devops-practice)).

<details><summary>Ответ</summary>

```bash
t=$( { /usr/bin/time -f %e dig +short example.com >/dev/null; } 2>&1 )
printf 'dns_resolve_seconds{domain="example.com"} %s\n' "$t" > /tmp/dns.prom.tmp
mv /tmp/dns.prom.tmp /var/lib/node_exporter/textfile/dns.prom
```

</details>

---

### Блок D. Инциденты

**D1.** Сменили IP сервиса в DNS, половина пользователей ходит на старый адрес третий час.
Что произошло и как надо было делать?

<details><summary>Ответ</summary>

Старый TTL (например, 3600 с) ещё жив в кешах провайдеров и клиентов. Правильный
порядок: заранее снизить TTL, дождаться истечения старого значения, переключить,
проверить, вернуть TTL.

</details>

**D2.** Создали новую запись `api.example.com`, но она не резолвится, хотя у коллеги работает.
Диагноз?

<details><summary>Ответ</summary>

Скорее всего закешированный отрицательный ответ (NXDOMAIN) у нашего резолвера:
проверить `dig @авторитетный-NS`, `dig @8.8.8.8`, сбросить локальный кеш и дождаться
истечения negative TTL из SOA. Второй вариант — запись создана в другой зоне/типе.

</details>

**D3.** `dig` показывает правильный IP, приложение ходит на другой. Где искать?

<details><summary>Ответ</summary>

В `/etc/hosts` (или в NSS/локальном hosts-файле контейнера) есть переопределение.
Проверять `getent hosts`, `/etc/hosts`, `/etc/nsswitch.conf`, а в контейнере — ещё и
`--add-host`/`extra_hosts` в compose.

</details>

**D4.** Часть доменов резолвится, часть даёт таймаут. На файрволе открыт только UDP/53. Связь?

<details><summary>Ответ</summary>

Крупные ответы (много записей, DNSSEC) не помещаются в UDP: сервер ставит флаг `tc`,
клиент должен повторить по TCP/53 — а он закрыт. Симптом: «часть доменов не резолвится».
Лечение: открыть TCP/53 (и разрешить EDNS0).

</details>

**D5.** В Kubernetes поды тратят по 2-5 секунд на резолв внешних адресов. Причина и решения.

<details><summary>Ответ</summary>

`ndots:5` + search-суффиксы → на каждый внешний домен 3-4 лишних запроса;
плюс возможная перегрузка CoreDNS и потери UDP. Решения: `dnsConfig` с `ndots:2`,
FQDN с точкой в конце, NodeLocal DNSCache, увеличение реплик CoreDNS и его ресурсов.

</details>

**D6.** Внезапно все сервисы начали отвечать 500. В логах приложения — `SERVFAIL` при обращении
к БД по имени. Куда смотреть?

<details><summary>Ответ</summary>

SERVFAIL — резолвер не смог ответить: проверить доступность DNS-серверов
(`dig @каждый`), их нагрузку, `tcpdump port 53`, состояние CoreDNS/внутреннего DNS,
не истёк ли срок делегирования/DNSSEC-подписи зоны.

</details>

**D7.** После включения VPN перестали резолвиться внутренние имена, внешние работают.
Что настроено неверно?

<details><summary>Ответ</summary>

VPN не отдал свои DNS-серверы или не настроен split-DNS: внутренние зоны должны
резолвиться через корпоративный DNS, остальное — через публичный. Настраивается
`resolvectl domain <iface> ~internal.corp` (split-DNS) или конфигом VPN-клиента.

</details>

**D8.** Мониторинг DNS показывает рост latency резолва с 5 до 300 мс. Чем это грозит
и что проверить?

<details><summary>Ответ</summary>

Медленный резолв замедляет каждое новое соединение (включая health-check'и и
обращения к БД) и способен выглядеть как «тормозит всё». Проверить: нагрузку и очередь
DNS-сервера, потери UDP, ndots/search, доступность апстримов, включить кеш ближе к клиенту.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как работает DNS? Опиши путь запроса.

<details><summary>Ответ</summary>

Клиент → hosts/кеш → рекурсивный резолвер → корень → TLD → авторитетный NS → ответ
кешируется на TTL.

</details>

**2.** Чем рекурсивный резолвер отличается от авторитетного?

<details><summary>Ответ</summary>

Рекурсивный сам проходит цепочку и кеширует, авторитетный хранит зону и отвечает за неё.

</details>

**3.** Какие типы записей ты знаешь?

<details><summary>Ответ</summary>

A, AAAA, CNAME, MX, NS, TXT, SRV, PTR, SOA, CAA.

</details>

**4.** Что такое TTL и зачем он нужен?

<details><summary>Ответ</summary>

Время жизни записи в кешах; управляет скоростью распространения изменений.

</details>

**5.** Что такое NXDOMAIN и SERVFAIL?

<details><summary>Ответ</summary>

NXDOMAIN — имени не существует; SERVFAIL — сбой при получении ответа.

</details>

**6.** По какому протоколу работает DNS?

<details><summary>Ответ</summary>

UDP и TCP, порт 53 (TCP — для больших ответов и зонных передач).

</details>

**7.** Как проверить, что именно ломается при резолве?

<details><summary>Ответ</summary>

`getent hosts` → `/etc/hosts` → `resolv.conf` → `dig` с кодом ответа → `dig @другой сервер`
→ `dig +trace` → проверка кеша и tcpdump на 53 порту.

</details>

**8.** Как работает DNS в Kubernetes?

<details><summary>Ответ</summary>

CoreDNS резолвит `service.namespace.svc.cluster.local`; в подах прописан search-список
и `ndots:5`.

</details>

---

### 🎯 Чек-лист

- [ ] Объясню полный путь резолва без подсказки
- [ ] Знаю типы записей и что лежит в TXT
- [ ] Различаю NXDOMAIN, SERVFAIL, REFUSED, NOERROR-пустой
- [ ] Понимаю TTL и правило понижения перед миграцией
- [ ] Всегда сверяю `getent hosts` и `dig`
- [ ] Умею `dig +trace` и `dig @сервер`
- [ ] Знаю про ndots:5 в Kubernetes и его последствия
- [ ] Поднял свой DNS (dnsmasq) и переключил на него клиента
