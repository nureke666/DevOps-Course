---
title: "22. DNS"
description: "Путь резолвинга, типы записей, dig, /etc/hosts vs DNS, алгоритм «DNS не работает»"
---

# 22. DNS — система доменных имён

> Источник: `22_dns.txt` (Networking Nomad, 6 уроков)
> **После темы ты умеешь:** объяснить путь резолвинга, читать DNS-записи, дебажить через `dig`
> и понимать, почему «это всегда DNS». Финальная тема курса.

---

## 🗺️ Схема: путь резолвинга `www.example.com`

```text:no-line-numbers
   Приложение                                  ┌──────────────────────┐
        │  getaddrinfo("www.example.com")      │  КОРНЕВЫЕ (.)        │
        ▼                                      │  13 наборов a-m      │
 ┌──────────────────┐                     ┌───▶│  «спроси .com»       │
 │ Кэш процесса     │                     │    └──────────┬───────────┘
 └────────┬─────────┘                     │               │
          ▼                               │    ┌──────────▼───────────┐
 ┌──────────────────┐                     │    │  TLD-серверы (.com)  │
 │ /etc/hosts       │  найдено → ответ    ├───▶│  «спроси ns1.example │
 └────────┬─────────┘                     │    │   .com»              │
          ▼                               │    └──────────┬───────────┘
 ┌──────────────────┐                     │               │
 │ systemd-resolved │                     │    ┌──────────▼───────────┐
 │ (локальный кэш)  │                     └───▶│ АВТОРИТАТИВНЫЙ сервер│
 └────────┬─────────┘                          │ «www.example.com =   │
          ▼                                    │  93.184.216.34»      │
 ┌──────────────────┐   рекурсивный запрос     └──────────────────────┘
 │ РЕКУРСИВНЫЙ      │──────────────────────────────────┘
 │ резолвер         │◀── ответ + TTL, кладёт в кэш
 │ (1.1.1.1, ISP)   │
 └────────┬─────────┘
          ▼
      IP-адрес → приложение открывает TCP-соединение
```

Порядок «кто отвечает первым» на Linux задаётся в `/etc/nsswitch.conf`:
```text:no-line-numbers
hosts: files dns    →  сначала /etc/hosts, потом DNS
```
(в Ubuntu обычно `files mdns4_minimal [NOTFOUND=return] dns`)

---

## 1. What is DNS

DNS переводит имена в адреса. Кроме удобства это даёт:
- **гибкость** — можно сменить IP-адрес сервиса, не меняя имя;
- **балансировку** — одно имя → несколько адресов;
- **географию** — разным клиентам разные ответы (GeoDNS, Anycast);
- **service discovery** — SRV-записи, внутренний DNS Kubernetes.

Иерархия имени читается **справа налево**:
```text:no-line-numbers
        www   .   example   .   com   .
         │         │            │     └─ корень (точка, обычно не пишут)
         │         │            └─ TLD (top-level domain)
         │         └─ домен второго уровня (то, что регистрируют)
         └─ поддомен (host)

FQDN (полное имя): www.example.com.   ← с точкой в конце
```

---

## 2. DNS Components — кто есть кто

| Компонент | Роль |
|-----------|------|
| **Stub resolver** | Клиентская библиотека в ОС (`getaddrinfo`), спрашивает у резолвера |
| **Рекурсивный резолвер** | Ходит по иерархии за тебя и кэширует (1.1.1.1, 8.8.8.8, DNS провайдера) |
| **Корневые серверы** | 13 логических наборов (a–m.root-servers.net), знают, где TLD |
| **TLD-серверы** | `.com`, `.org`, `.kz` — знают, где авторитативные серверы домена |
| **Авторитативный сервер** | Хранит зону и даёт **окончательный** ответ |
| **Зона** | Файл/база с записями домена |
| **Регистратор** | Где покупается домен и задаются NS-серверы |

### Типы записей — must-know

| Тип | Что делает | Пример |
|-----|-----------|--------|
| **A** | Имя → IPv4 | `example.com. 300 IN A 93.184.216.34` |
| **AAAA** | Имя → IPv6 | `example.com. IN AAAA 2606:2800:220:1::` |
| **CNAME** | Псевдоним (имя → имя) | `www IN CNAME example.com.` |
| **MX** | Почтовые серверы (с приоритетом) | `example.com. IN MX 10 mail.example.com.` |
| **NS** | Авторитативные серверы зоны | `example.com. IN NS ns1.example.com.` |
| **TXT** | Произвольный текст: SPF, DKIM, верификация | `IN TXT "v=spf1 include:_spf.google.com ~all"` |
| **SOA** | Параметры зоны: серийник, таймеры | — |
| **PTR** | IP → имя (обратная зона) | для почтовых серверов обязательна |
| **SRV** | Сервис, порт и приоритет | `_sip._tcp.example.com. IN SRV 10 5 5060 sip.example.com.` |
| **CAA** | Кто может выпускать TLS-сертификаты | `IN CAA 0 issue "letsencrypt.org"` |

⚠️ **CNAME нельзя ставить на корень домена** (`example.com`), только на поддомены —
он не может сосуществовать с другими записями (SOA/NS обязаны быть на корне).
Провайдеры обходят это нестандартными `ALIAS`/`ANAME`/`CNAME flattening`.

**TTL** — сколько секунд ответ можно кэшировать. Практическое правило: **за сутки до миграции
понижай TTL** до 60-300 секунд, после переезда — верни обратно (3600+).

---

## 3. DNS Process — как это работает

**Рекурсивный запрос** — «найди мне ответ полностью» (клиент → резолверу).
**Итеративный запрос** — «скажи, что знаешь» (резолвер → корень → TLD → авторитативный).

Транспорт: **UDP/53** для обычных запросов, **TCP/53** для больших ответов (>512 байт без EDNS)
и для передачи зон (AXFR). Современные варианты: **DoT** (DNS over TLS, 853),
**DoH** (DNS over HTTPS, 443).

Кэширование происходит на каждом уровне: приложение → ОС/systemd-resolved → рекурсивный резолвер.
Отсюда классика: «я поменял запись, а у меня старый адрес» — виноват кэш и TTL.

Негативное кэширование (NXDOMAIN) тоже существует и управляется параметром SOA `minimum`.

---

## 4. /etc/hosts — статическое сопоставление

```bash
cat /etc/hosts
```
```text:no-line-numbers
127.0.0.1       localhost
127.0.1.1       learn-linux
192.168.56.10   web web.lab.local
192.168.56.11   app  app.lab.local
::1             localhost ip6-localhost ip6-loopback
```

Проверяется **до** DNS (согласно `/etc/nsswitch.conf`). Применение:
- локальная разработка (`127.0.0.1 myapp.local`);
- тестирование до переключения DNS;
- аварийный обход неработающего DNS;
- небольшие стенды без своего DNS-сервера.

⚠️ Минусы: не масштабируется, легко забыть и потом долго искать «почему на этом сервере
имя резолвится не туда». В проде — только временно и осознанно.

Родственные файлы:
```text:no-line-numbers
/etc/resolv.conf      какие DNS использовать (обычно СИМЛИНК на systemd-resolved!)
/etc/nsswitch.conf    порядок источников: files → dns
/etc/hosts            статические записи
```

`/etc/resolv.conf`:
```text:no-line-numbers
nameserver 127.0.0.53      # заглушка systemd-resolved
options edns0 trust-ad
search lab.local           # суффиксы: "app" будет искаться как "app.lab.local"
```

⚠️ `search`-домены — источник загадочных задержек: каждое неудачное имя порождает
дополнительные запросы с суффиксами. В Kubernetes из-за `ndots:5` это классическая проблема
производительности DNS.

---

## 5. DNS Setup — настройка клиента и сервера

### Клиент (Ubuntu, systemd-resolved)

```bash
resolvectl status                       # какие DNS используются, по интерфейсам
resolvectl query example.com
resolvectl statistics                   # попадания в кэш
sudo resolvectl flush-caches            # сбросить кэш
systemd-resolve --status                # старое имя команды
```
Задать DNS постоянно — через netplan:
```yaml
      nameservers:
        addresses: [1.1.1.1, 8.8.8.8]
        search: [lab.local]
```
или в `/etc/systemd/resolved.conf` (`DNS=`, `FallbackDNS=`, `Domains=`), затем
`systemctl restart systemd-resolved`.

### Свой DNS-сервер (кратко)

| Сервер | Применение |
|--------|-----------|
| **dnsmasq** | Простой кэширующий + DHCP, для небольших сетей и стендов |
| **BIND9** | Классика, полнофункциональный авторитативный |
| **CoreDNS** | Модульный, **DNS внутри Kubernetes** |
| **Unbound** | Быстрый валидирующий рекурсивный резолвер |
| **PowerDNS** | С базой данных и API |

Пример зоны BIND:
```text:no-line-numbers
$TTL 3600
@   IN  SOA ns1.lab.local. admin.lab.local. (
        2026091301  ; Serial ← увеличивать при каждом изменении!
        3600        ; Refresh
        1800        ; Retry
        604800      ; Expire
        86400 )     ; Minimum TTL (негативное кэширование)
@       IN  NS   ns1.lab.local.
ns1     IN  A    192.168.56.10
web   IN  A    192.168.56.10
app    IN  A    192.168.56.11
www     IN  CNAME web
```

💼 В Kubernetes DNS — это CoreDNS, и имена формируются как
`<service>.<namespace>.svc.cluster.local`. Большинство «сетевых» проблем в кластере
на самом деле проблемы CoreDNS.

---

## 6. DNS Tools — инструменты

### dig — основной инструмент

```bash
dig example.com                       # полный ответ
dig +short example.com                # ⭐ только адрес
dig example.com A
dig example.com MX
dig example.com NS
dig example.com TXT
dig example.com ANY
dig @1.1.1.1 example.com              # ⭐ спросить КОНКРЕТНЫЙ сервер (обход кэша)
dig @8.8.8.8 example.com +short
dig +trace example.com                # ⭐⭐ ВЕСЬ путь: корень → TLD → авторитативный
dig -x 93.184.216.34                  # обратный запрос (PTR)
dig +noall +answer example.com        # только секция ответа
dig +nocmd +noall +answer +ttlid example.com
dig example.com +stats                # время ответа и статистика
dig soa example.com                   # серийник зоны
```

Читаем вывод:
```text:no-line-numbers
;; QUESTION SECTION:
;example.com.            IN  A

;; ANSWER SECTION:
example.com.     300     IN  A     93.184.216.34
                  │                       │
                  └─ оставшийся TTL       └─ ответ

;; Query time: 24 msec
;; SERVER: 127.0.0.53#53(127.0.0.53)     ← кто ответил
```
Статусы: `NOERROR` (ок), **`NXDOMAIN`** (имени не существует),
`SERVFAIL` (сервер не смог ответить — часто DNSSEC или недоступность авторитативного),
`REFUSED` (сервер отказался обслуживать запрос).

### Прочие инструменты

```bash
nslookup example.com                  # проще, но менее информативен
nslookup example.com 8.8.8.8
host example.com                      # самый короткий вывод
host -t MX example.com

getent hosts example.com              # ⭐ резолв так, как это делает СИСТЕМА (через nsswitch)
ping -c1 example.com                  # проверка «как приложение»

whois example.com | head -20          # владелец домена, NS, даты
```

🔑 **Важное различие:** `dig` идёт напрямую в DNS, а `getent hosts` / `ping` используют
**системный** резолвинг, включая `/etc/hosts` и nsswitch. Если `dig` работает, а приложение
нет — сравни их вывод: часто ответ найдётся в `/etc/hosts`.

---

## 🔧 Алгоритм «DNS не работает»

```text:no-line-numbers
1. getent hosts example.com        резолвится системой?
2. dig +short example.com          резолвится через DNS?
3. dig @1.1.1.1 example.com        а через публичный резолвер?  (если да → проблема в твоём DNS)
4. resolvectl status               какие DNS реально настроены?
5. cat /etc/resolv.conf ; ls -l    не перезаписан ли файл, симлинк ли он?
6. grep example.com /etc/hosts     нет ли статической записи, которая всё ломает
7. dig +trace example.com          где обрывается цепочка делегирования
8. dig soa example.com             актуальный ли серийник зоны
9. ss -tulpn | grep :53 ; ping <dns>   доступен ли сам DNS-сервер
10. sudo resolvectl flush-caches   не старый ли кэш
```

---

## 💼 Как это в DevOps

- «Это всегда DNS» — известная шутка, потому что очень часто так и есть: TTL, кэш, `search`-домены,
  забытая запись, упавший CoreDNS.
- **Миграция сервиса:** снизить TTL заранее → переключить запись → дождаться истечения TTL → вернуть TTL.
- **Let's Encrypt DNS-01 challenge** — TXT-записи для выпуска wildcard-сертификатов.
- **Почта:** MX + SPF/DKIM/DMARC (TXT) + PTR — без них письма уходят в спам.
- **Kubernetes:** CoreDNS, `ndots:5`, `dnsPolicy`, `dnsConfig` — типичный источник задержек.
- **Service discovery:** Consul, внутренние зоны, SRV-записи.
- **Мониторинг:** проверять срок регистрации домена, корректность NS, время ответа резолвера.

---

## 🧪 Мини-лаба

```bash
vagrant ssh web
sudo apt install -y dnsutils

# 1. Базовый резолвинг
dig +short example.com
dig example.com | head -20
host example.com
getent hosts example.com
resolvectl query example.com

# 2. Разные типы записей
dig +short google.com A
dig +short google.com AAAA
dig +short google.com MX
dig +short google.com NS
dig +short google.com TXT | head -3
dig +short www.github.com CNAME

# 3. Полный путь делегирования (важное упражнение!)
dig +trace example.com | head -40

# 4. Конкретные серверы и кэш
dig @1.1.1.1 example.com +short
dig @8.8.8.8 example.com +short
dig example.com | grep -E 'SERVER|Query time'
dig example.com | grep -E 'SERVER|Query time'     # второй раз быстрее — кэш
sudo resolvectl flush-caches
dig example.com | grep 'Query time'               # снова медленно

# 5. TTL в динамике
dig +noall +answer example.com; sleep 5; dig +noall +answer example.com   # TTL уменьшился

# 6. Обратный запрос
dig -x 8.8.8.8 +short
dig -x 1.1.1.1 +short

# 7. Ошибки
dig +short this-domain-definitely-does-not-exist-12345.com    # пусто
dig this-domain-definitely-does-not-exist-12345.com | grep status   # NXDOMAIN

# 8. /etc/hosts и приоритет над DNS
cat /etc/nsswitch.conf | grep hosts
echo "1.2.3.4 example.com" | sudo tee -a /etc/hosts
getent hosts example.com          # 1.2.3.4 — hosts победил
ping -c1 example.com              # идёт на 1.2.3.4!
dig +short example.com            # а dig по-прежнему даёт реальный адрес
sudo sed -i '/1.2.3.4 example.com/d' /etc/hosts
getent hosts example.com

# 9. Локальные имена для стенда
echo "192.168.56.11 app app.lab.local" | sudo tee -a /etc/hosts
ping -c2 app
ssh -o StrictHostKeyChecking=no vagrant@app hostname

# 10. Свой кэширующий DNS (dnsmasq) — по желанию
sudo apt install -y dnsmasq
sudo tee /etc/dnsmasq.d/lab.conf >/dev/null <<'EOS'
address=/web.lab.local/192.168.56.10
address=/app.lab.local/192.168.56.11
cache-size=1000
EOS
sudo systemctl restart dnsmasq 2>/dev/null || echo "порт 53 занят systemd-resolved — это нормально"
dig @127.0.0.1 web.lab.local +short 2>/dev/null
sudo systemctl disable --now dnsmasq

# 11. Диагностика времени резолва
curl -w 'dns: %{time_namelookup}s total: %{time_total}s\n' -o /dev/null -s https://example.com

# 12. Статистика резолвера
resolvectl statistics
```

---

## 📌 Шпаргалка

| Задача | Команда |
|--------|---------|
| Быстро узнать IP | `dig +short example.com` |
| Полный ответ | `dig example.com` |
| Конкретный тип записи | `dig example.com MX\|NS\|TXT\|AAAA` |
| **Обойти кэш** | `dig @1.1.1.1 example.com` |
| **Весь путь делегирования** | `dig +trace example.com` |
| Обратный запрос | `dig -x 8.8.8.8` |
| Только ответ | `dig +noall +answer example.com` |
| Системный резолв (как у приложения) | `getent hosts example.com` |
| Текущие DNS | `resolvectl status` |
| Сбросить кэш | `sudo resolvectl flush-caches` |
| Статистика кэша | `resolvectl statistics` |
| Владелец домена | `whois example.com` |
| Статические записи | `/etc/hosts` |
| Порядок источников | `/etc/nsswitch.conf` |

**Записи:** A (IPv4) · AAAA (IPv6) · CNAME (псевдоним) · MX (почта) · NS (серверы зоны) ·
TXT (SPF/DKIM/верификация) · PTR (обратная) · SRV (сервис) · SOA (параметры зоны) · CAA (сертификаты).

---

## 🧠 Что запомнить

1. Порядок резолва: **кэш приложения → `/etc/hosts` → systemd-resolved → рекурсивный резолвер →
   корень → TLD → авторитативный**. Управляется `/etc/nsswitch.conf`.
2. `dig` ходит в DNS напрямую; `getent hosts`/`ping` используют системный резолв с `/etc/hosts`.
   Расхождение между ними — готовый диагноз.
3. `dig @1.1.1.1 …` — обход локального кэша; `dig +trace …` — где обрывается делегирование.
4. **TTL решает всё при миграциях:** снизить заранее, переключить, вернуть обратно.
5. `NXDOMAIN` — имени нет; `SERVFAIL` — сервер не смог ответить (DNSSEC, недоступность);
   `REFUSED` — отказ обслуживать.
6. CNAME нельзя на корень домена.
7. `/etc/resolv.conf` — обычно симлинк на systemd-resolved; править надо netplan/resolved.conf.
8. `search`-домены и `ndots` — частая причина медленного резолва (особенно в Kubernetes).
9. `/etc/hosts` перебивает DNS — первое, что стоит проверять при «загадочном» резолве.
10. Если что-то работает «странно и через раз» — проверь DNS. Это правда всегда DNS.

---

## 🎓 Linux Journey пройден!

Ты прошёл все 22 темы Linux Journey: от истории Linux до DNS. Блок Linux на этом ещё не закончен:

1. **Bash-скриптинг** — темы [23](/linux/23-bash-basics)-[26](/linux/26-bash-devops-practice) этого же блока:
   от кавычек до `set -euo pipefail`, `trap` и скриптов для Docker и CI.
2. **Закрепить практикой:** [27. Практика: лабы](/linux/27-practice-labs) — сквозные лабы по всему блоку
   и итоговый стенд (web + app, systemd-юниты, пользователи, логирование, бэкапы, сеть).
3. **Проверить себя:** [28. Собеседование](/linux/28-interview) — вопросы с собеседований и live-траблшутинг.
4. **Следующий блок роадмапа — Сети:** протоколы, TLS, HTTP, SSH, tcpdump, iptables, nginx.
   Дальше по общей карте: Docker → CI/CD → Ansible → Kubernetes → Остальное; Git — параллельно со всем.

💡 Совет: перед следующим этапом **перечитай свои конспекты и решите задачи заново**.
Linux — фундамент; всё вышеперечисленное работает поверх того, что ты уже знаешь.

Дальше — [23. Bash-скриптинг](/linux/23-bash-basics) (часть 4 блока).

---

## Задачи

> `vagrant snapshot save --all before_22`
> Установи: `sudo apt install -y dnsutils`

### Блок A. Теория

**A1.** Опиши полный путь резолвинга `www.example.com` с нуля (кэш пуст). Кто кого спрашивает?

<details><summary>Ответ</summary>

Приложение вызывает `getaddrinfo()` → библиотека проверяет порядок из `/etc/nsswitch.conf`
→ `/etc/hosts` → локальный кэш (systemd-resolved) → рекурсивный резолвер (например, 1.1.1.1).
Резолвер при пустом кэше идёт итеративно: корневой сервер («спроси серверы .com») → TLD-сервер
.com («спроси ns1.example.com») → авторитативный сервер зоны, который отдаёт A-запись.
Ответ с TTL кэшируется на всех уровнях и возвращается приложению.

</details>

**A2.** Чем рекурсивный запрос отличается от итеративного?

<details><summary>Ответ</summary>

Рекурсивный: клиент просит «дай окончательный ответ», и резолвер сам проходит всю цепочку.
Итеративный: сервер отвечает «сам не знаю, спроси вот этих» — так резолвер общается с корневыми
и TLD-серверами.

</details>

**A3.** Что такое авторитативный сервер и чем он отличается от рекурсивного резолвера?

<details><summary>Ответ</summary>

Авторитативный сервер хранит саму зону и даёт окончательные ответы для своих доменов.
Рекурсивный резолвер ничего не хранит постоянно: он выполняет поиск по иерархии от имени клиента
и кэширует результаты на время TTL.

</details>

**A4.** Какой транспорт использует DNS и почему нужен и UDP, и TCP?

<details><summary>Ответ</summary>

UDP/53 — для обычных запросов: быстро, без установки соединения.
TCP/53 — когда ответ не помещается в один UDP-датаграм (флаг TC, ответы >512 байт без EDNS,
DNSSEC), а также для передачи зон (AXFR/IXFR). Дополнительно существуют DoT (853) и DoH (443).

</details>

**A5.** Назови 8 типов DNS-записей и для чего каждая.

<details><summary>Ответ</summary>

A (IPv4), AAAA (IPv6), CNAME (псевдоним на другое имя), MX (почтовые серверы с приоритетом),
NS (авторитативные серверы зоны), TXT (произвольный текст: SPF, DKIM, верификация),
SOA (параметры зоны и серийник), PTR (обратное соответствие IP→имя), SRV (сервис/порт),
CAA (какие CA могут выпускать сертификаты).

</details>

**A6.** Почему CNAME нельзя поставить на корень домена (`example.com`)? Как это обходят?

<details><summary>Ответ</summary>

По стандарту CNAME не может сосуществовать с другими записями для того же имени,
а на корне зоны обязательно присутствуют SOA и NS. Обходят нестандартными типами
(`ALIAS`, `ANAME`) или CNAME flattening на стороне DNS-провайдера (Cloudflare, Route53 Alias).

</details>

**A7.** Что такое TTL? Как правильно мигрировать сервис на новый IP с точки зрения TTL?

<details><summary>Ответ</summary>

TTL — время, в течение которого ответ можно кэшировать. При миграции: за 24-48 часов
снизить TTL до 60-300 секунд, дождаться, пока старое значение истечёт у всех кэшей,
переключить запись, убедиться в корректности, затем вернуть высокий TTL (3600+).

</details>

**A8.** Что означают статусы `NOERROR`, `NXDOMAIN`, `SERVFAIL`, `REFUSED`?

<details><summary>Ответ</summary>

`NOERROR` — запрос выполнен успешно (ответ может быть и пустым, если нет записей
такого типа). `NXDOMAIN` — имени не существует. `SERVFAIL` — сервер не смог обработать запрос
(ошибка DNSSEC, недоступен авторитативный сервер, внутренняя ошибка). `REFUSED` — сервер
отказался обслуживать запрос (политика, ACL, не его зона).

</details>

**A9.** 🔑 В чём разница между `dig example.com` и `getent hosts example.com`?
Почему это важнейший диагностический приём?

<details><summary>Ответ</summary>

`dig` обращается напрямую к DNS-серверу и **игнорирует** `/etc/hosts` и nsswitch.
`getent hosts` использует **системный** механизм разрешения имён — ровно тот, которым
пользуются приложения. Если они дают разные ответы, значит вмешивается `/etc/hosts`,
mDNS, NSS-модуль или кэш — это мгновенно локализует проблему.

</details>

**A10.** Что задаёт `/etc/nsswitch.conf` и как он влияет на резолвинг?

<details><summary>Ответ</summary>

Порядок источников для разных баз данных ОС. Для строки `hosts:` он определяет,
где искать имена: `files` (`/etc/hosts`), `dns`, `mdns4_minimal`, `myhostname` и т.д.
Именно поэтому `/etc/hosts` побеждает DNS.

</details>

**A11.** Что такое `search`-домены и как они могут замедлить работу приложения?

<details><summary>Ответ</summary>

Суффиксы, которые автоматически дописываются к коротким именам (`app` →
`app.lab.local`). Если доменов поиска несколько, а имя не резолвится, система делает
запрос **на каждый** суффикс — это лишние round-trip'ы. В Kubernetes с `ndots:5`
даже полные внешние имена сначала пробуются с суффиксами кластера, что даёт заметные задержки.

</details>

**A12.** Почему правка `/etc/resolv.conf` в Ubuntu часто не даёт эффекта?

<details><summary>Ответ</summary>

Файл является симлинком на `/run/systemd/resolve/stub-resolv.conf` и перегенерируется
`systemd-resolved` при каждом применении сетевой конфигурации — ручные правки затираются.
Настраивать нужно netplan (`nameservers:`) или `/etc/systemd/resolved.conf`.

</details>

**A13.** Зачем нужны записи SPF, DKIM, DMARC и PTR для почтового сервера?

<details><summary>Ответ</summary>

SPF (TXT) — список серверов, которым разрешено отправлять почту от имени домена;
DKIM (TXT) — публичный ключ для проверки криптографической подписи писем;
DMARC (TXT) — политика, что делать с письмами, не прошедшими SPF/DKIM, и куда слать отчёты;
PTR — обратная запись для IP почтового сервера, её отсутствие почти гарантирует попадание в спам.

</details>

**A14.** Что такое CoreDNS и как формируются имена сервисов в Kubernetes?

<details><summary>Ответ</summary>

CoreDNS — DNS-сервер, работающий внутри кластера Kubernetes и обслуживающий
service discovery. Имена формируются как `<service>.<namespace>.svc.cluster.local`
(для подов — `<pod-ip-с-дефисами>.<namespace>.pod.cluster.local`).

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  dig +short example.com
B2.  dig example.com MX
B3.  dig @1.1.1.1 example.com +short
B4.  dig +trace example.com
B5.  dig -x 8.8.8.8
B6.  dig +noall +answer example.com
B7.  dig soa example.com
B8.  host -t NS example.com
B9.  getent hosts example.com
B10. resolvectl status
B11. resolvectl query example.com
B12. sudo resolvectl flush-caches
B13. resolvectl statistics
B14. whois example.com | head -20
B15. curl -w 'dns: %{time_namelookup}s\n' -o /dev/null -s https://example.com
```

<details><summary>Ответ</summary>

- **B1.** Только IP-адрес — удобно для скриптов.
- **B2.** Почтовые серверы домена с приоритетами.
- **B3.** Запрос напрямую к 1.1.1.1 в обход локального кэша и настроенных резолверов.
- **B4.** Полная цепочка делегирования: корень → TLD → авторитативный сервер.
- **B5.** Обратный запрос: какое имя соответствует адресу 8.8.8.8.
- **B6.** Только секция ANSWER без служебного вывода.
- **B7.** SOA-запись: первичный NS, почта администратора, серийник, таймеры.
- **B8.** Авторитативные серверы домена (краткий вывод).
- **B9.** Разрешение имени **системным** механизмом (учитывает `/etc/hosts` и nsswitch).
- **B10.** Какие DNS-серверы и домены поиска используются, по интерфейсам.
- **B11.** Запрос через systemd-resolved с подробностями (источник, кэш, DNSSEC).
- **B12.** Сброс кэша локального резолвера.
- **B13.** Статистика: число запросов, попаданий в кэш, промахов.
- **B14.** Регистрационные данные домена: регистратор, даты, NS-серверы.
- **B15.** Время, затраченное именно на DNS-резолвинг при HTTP-запросе.

</details>

**B16.** Чем `dig` лучше `nslookup` для диагностики?

<details><summary>Ответ</summary>

`dig` даёт полный, машиночитаемый вывод со всеми секциями (QUESTION/ANSWER/AUTHORITY/
ADDITIONAL), флагами, TTL, временем запроса и сервером-ответчиком; поддерживает `+trace`,
`+short`, точный выбор сервера и типа записи. `nslookup` проще, но скрывает детали
и считается устаревшим для диагностики.

</details>

---

### Блок C. Практика

**C1. Разведка.** Для домена `github.com` выясни:
- IPv4 и IPv6 адреса;
- почтовые серверы с приоритетами;
- авторитативные NS-серверы;
- TXT-записи (найди SPF);
- серийник зоны (SOA);
- TTL записи A.

<details><summary>Ответ</summary>

```bash
dig +short github.com A
dig +short github.com AAAA
dig +short github.com MX
dig +short github.com NS
dig +short github.com TXT | grep spf
dig +noall +answer github.com SOA
dig +noall +answer github.com | awk '{print $1, $2, $4, $5}'
```

</details>

**C2. Путь делегирования.** Выполни `dig +trace` для любого домена и распиши по шагам:
какой сервер на каком этапе отвечал и что именно он сообщил.

<details><summary>Ответ</summary>

```bash
dig +trace example.com | head -40
```
Шаги: сначала ответ от корневых серверов со списком NS для `.com` (записи NS + glue A),
затем ответ TLD-сервера `.com` с NS-серверами зоны `example.com`, затем ответ авторитативного
сервера с самой записью A. Каждый блок помечен `;; Received ... from <IP>`.

</details>

**C3. Кэш в действии.**
1. Сбрось кэш резолвера.
2. Сделай запрос, зафиксируй `Query time`.
3. Повтори тот же запрос — сравни время.
4. Покажи, как обойти локальный кэш и спросить напрямую у `1.1.1.1`.
5. Посмотри статистику попаданий в кэш.

<details><summary>Ответ</summary>

```bash
sudo resolvectl flush-caches
dig example.com | grep 'Query time'        # например 40 ms
dig example.com | grep 'Query time'        # 0-1 ms — из кэша
dig @1.1.1.1 example.com +short            # мимо локального кэша
resolvectl statistics
```

</details>

**C4. TTL.** Сделай запрос к домену, запиши TTL. Подожди 10 секунд, повтори — TTL должен
уменьшиться. Объясни, почему через какое-то время он «сбросится» обратно к исходному значению.

<details><summary>Ответ</summary>

```bash
dig +noall +answer example.com     # TTL, например, 300
sleep 10
dig +noall +answer example.com     # TTL 290
```
Когда TTL истекает, кэш сбрасывает запись, следующий запрос уходит к авторитативному серверу
и возвращает полный (исходный) TTL.

</details>

**C5. 🔑 hosts vs DNS (обязательное упражнение).**
1. Добавь в `/etc/hosts` запись `1.2.3.4 example.com`.
2. Сравни вывод `dig +short example.com` и `getent hosts example.com`.
3. Проверь, куда пойдёт `ping example.com` и `curl example.com`.
4. Объясни, почему `dig` показывает «правильный» ответ, а приложение идёт не туда.
5. Убери запись.

*Вывод запиши своими словами — это самая частая ловушка в реальной работе.*

<details><summary>Ответ</summary>

```bash
echo "1.2.3.4 example.com" | sudo tee -a /etc/hosts
dig +short example.com          # 93.184.216.34 — dig не смотрит в /etc/hosts
getent hosts example.com        # 1.2.3.4 — системный резолв
ping -c1 example.com            # идёт на 1.2.3.4
curl -sI --max-time 3 http://example.com || echo "не отвечает — это наш фейковый адрес"
sudo sed -i '/^1\.2\.3\.4 example\.com$/d' /etc/hosts
getent hosts example.com
```

</details>

**C6. Обратные записи.** Сделай PTR-запросы для `8.8.8.8`, `1.1.1.1` и IP своего сервера.
Объясни, почему для своего адреса PTR может отсутствовать и кому он нужен.

<details><summary>Ответ</summary>

```bash
dig -x 8.8.8.8 +short          # dns.google
dig -x 1.1.1.1 +short          # one.one.one.one
dig -x "$(curl -s ifconfig.me)" +short || echo "PTR отсутствует"
```
PTR настраивается **владельцем блока адресов** (провайдером/облаком), а не владельцем домена.
Он обязателен для почтовых серверов, полезен для логов и некоторых проверок безопасности.

</details>

**C7. Локальные имена стенда.** Настрой на обеих ВМ так, чтобы они обращались друг к другу
по именам `web.lab.local` и `app.lab.local`:
- через `/etc/hosts`;
- проверь `ping`, `ssh`, `getent hosts`;
- объясни минусы такого подхода для 50 серверов.

<details><summary>Ответ</summary>

```bash
# на обеих ВМ
sudo tee -a /etc/hosts >/dev/null <<'EOS'
192.168.56.10 web web.lab.local
192.168.56.11 app  app.lab.local
EOS
ping -c2 app.lab.local
getent hosts web.lab.local
ssh -o StrictHostKeyChecking=no vagrant@app hostname
```
Минусы для 50 серверов: файл надо синхронизировать вручную на каждом хосте, любое изменение
адреса требует правки везде, легко получить рассинхронизацию и «загадочные» различия
между серверами, нет TTL и централизованного управления. Решение — собственный DNS
(dnsmasq/CoreDNS/BIND) или сервис-дискавери.

</details>

**C8. Свой DNS-сервер.** Подними `dnsmasq` (или CoreDNS) на web так, чтобы:
- он резолвил `*.lab.local` в адреса стенда;
- остальные запросы форвардил на `1.1.1.1`;
- app использовал его как DNS-сервер.

Проверь: `dig @192.168.56.10 app.lab.local`, `dig @192.168.56.10 example.com`.
*Подсказка:* systemd-resolved уже занимает порт 53 — отключи его заглушку или используй другой порт.

<details><summary>Ответ</summary>

```bash
# на web
sudo apt install -y dnsmasq
sudo sed -i 's/^#\?DNSStubListener=.*/DNSStubListener=no/' /etc/systemd/resolved.conf
sudo systemctl restart systemd-resolved
sudo tee /etc/dnsmasq.d/lab.conf >/dev/null <<'EOS'
domain-needed
bogus-priv
no-resolv
server=1.1.1.1
address=/web.lab.local/192.168.56.10
address=/app.lab.local/192.168.56.11
cache-size=1000
listen-address=127.0.0.1,192.168.56.10
EOS
sudo systemctl restart dnsmasq && sudo systemctl status dnsmasq --no-pager | head -5
dig @192.168.56.10 app.lab.local +short
dig @192.168.56.10 example.com +short
# на app: указать 192.168.56.10 в netplan nameservers, применить и проверить
# уборка: sudo systemctl disable --now dnsmasq; вернуть DNSStubListener
```

</details>

**C9. Диагностика времени.** Измерь через `curl -w`, сколько занимает DNS-резолвинг
для нескольких доменов. Затем добавь в `/etc/resolv.conf` **несуществующий** DNS-сервер
первым и измерь снова. Объясни разницу и почему порядок серверов важен.

<details><summary>Ответ</summary>

```bash
curl -w 'dns: %{time_namelookup}s total: %{time_total}s\n' -o /dev/null -s https://example.com
# добавить нерабочий резолвер первым (через resolved.conf или netplan) и повторить
```
Если первый сервер не отвечает, резолвер ждёт таймаут (обычно 5 секунд) и только потом
переходит ко второму — отсюда стабильная пятисекундная задержка. Порядок и доступность
серверов критичны; мёртвый резолвер в списке хуже, чем его отсутствие.

</details>

**C10. Скрипт DNS-проверки.** Напиши `/vagrant/dns_check.sh <domain>`:
```text:no-line-numbers
=== DNS CHECK: example.com ===
System resolve (getent): 93.184.216.34
DNS resolve (dig):       93.184.216.34
Match: YES
A records:    93.184.216.34 (TTL 300)
AAAA records: 2606:2800:220:1:248:1893:25c8:1946
NS records:   a.iana-servers.net, b.iana-servers.net
MX records:   none
SPF:          v=spf1 -all
SOA serial:   2024081401
Resolvers in use: 127.0.0.53 -> 1.1.1.1
Query time:   24 ms
/etc/hosts override: none
=== RESULT: OK ===
```

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
D="${1:?usage: dns_check.sh <domain>}"
echo "=== DNS CHECK: $D ==="
SYS=$(getent hosts "$D" | awk '{print $1; exit}')
DNS=$(dig +short "$D" A | tail -1)
echo "System resolve (getent): ${SYS:-FAIL}"
echo "DNS resolve (dig):       ${DNS:-FAIL}"
[ "$SYS" = "$DNS" ] && echo "Match: YES" || echo "Match: NO  <-- проверь /etc/hosts!"
echo "A records:    $(dig +noall +answer "$D" A | awk '{print $5" (TTL "$2")"}' | paste -sd', ')"
echo "AAAA records: $(dig +short "$D" AAAA | paste -sd', ' || echo none)"
echo "NS records:   $(dig +short "$D" NS | paste -sd', ')"
echo "MX records:   $(dig +short "$D" MX | paste -sd', ' || echo none)"
echo "SPF:          $(dig +short "$D" TXT | grep -i spf1 || echo none)"
echo "SOA serial:   $(dig +short "$D" SOA | awk '{print $3}')"
echo "Resolvers in use: $(resolvectl status 2>/dev/null | awk '/DNS Servers/{print $3; exit}')"
echo "Query time:   $(dig "$D" | awk '/Query time/{print $4, $5}')"
echo "/etc/hosts override: $(grep -w "$D" /etc/hosts || echo none)"
[ -n "$DNS" ] && echo "=== RESULT: OK ===" || echo "=== RESULT: FAILED ==="
```

</details>

---

### Блок D. Инциденты

**D1.** `ping 8.8.8.8` работает, `ping google.com` — «Name or service not known».
Алгоритм диагностики по шагам.

<details><summary>Ответ</summary>

(1) `getent hosts google.com` — резолвится ли системой. (2) `dig +short google.com` —
работает ли DNS вообще. (3) `dig @1.1.1.1 google.com` — если работает, проблема в настроенном
резолвере. (4) `resolvectl status` и `cat /etc/resolv.conf` — какие серверы настроены,
не пуст ли список. (5) `ping <dns-сервер>` — доступен ли он. (6) `grep google /etc/hosts`.
(7) `sudo resolvectl flush-caches`. Чаще всего: не указан DNS (DHCP не выдал) или резолвер недоступен.

</details>

**D2.** Вчера переключили домен на новый сервер, но часть пользователей до сих пор попадает
на старый. Что произошло, что делать сейчас и как надо было готовиться?

<details><summary>Ответ</summary>

Старая запись ещё живёт в кэшах резолверов и клиентов — TTL не истёк.
Сейчас: убедиться, что авторитативные серверы отдают новый адрес (`dig @ns1... +short`),
подождать истечения старого TTL, временно поддерживать старый сервер (или сделать на нём
редирект/проксирование на новый). Готовиться надо было заранее: за сутки-двое снизить TTL
до 60-300 секунд, а после успешного переключения вернуть обратно.

</details>

**D3.** На одном сервере `curl api.internal` идёт на правильный адрес, на другом — на старый.
`dig` на обоих даёт одинаковый правильный ответ. Где искать?

<details><summary>Ответ</summary>

`dig` одинаков, значит DNS отдаёт верный ответ на обоих — различие в **системном**
резолвинге. Проверять: `getent hosts api.internal` на обоих серверах, `/etc/hosts`
(скорее всего там осталась старая запись), `/etc/nsswitch.conf`, локальный кэш
(`resolvectl flush-caches`), а также кэш самого приложения (JVM кэширует DNS по умолчанию).

</details>

**D4.** В Kubernetes приложение делает запрос к `api.example.com` и получает ответ за 5 секунд
вместо 20 мс. Что проверишь в первую очередь?

<details><summary>Ответ</summary>

Смотрю CoreDNS: `kubectl -n kube-system get pods -l k8s-app=kube-dns`, его логи и
метрики, ресурсы/лимиты (частая причина — троттлинг CPU), количество реплик.
Затем `ndots:5` и `dnsPolicy`/`dnsConfig` пода: для внешних имён каждое разрешение сначала
проходит через суффиксы кластера — лечится точкой в конце (`api.example.com.`) или
`dnsConfig.options ndots:1`. Также проверяю `conntrack` и сетевую политику, доступность
upstream-резолверов.

</details>

**D5.** `dig example.com` возвращает `SERVFAIL`, а `dig @1.1.1.1 example.com` работает.
Где проблема?

<details><summary>Ответ</summary>

Локальный (настроенный) резолвер не смог получить ответ: он недоступен, перегружен,
имеет проблемы с DNSSEC-валидацией, ограничен ACL или не может достучаться до авторитативных
серверов. Проверить: `resolvectl status`, доступность резолвера, логи (`journalctl -u
systemd-resolved`, логи собственного DNS), `dig +trace` для проверки цепочки. Временное
решение — сменить резолвер; постоянное — починить свой.

</details>

**D6.** Письма с твоего сервера уходят в спам. Какие DNS-записи проверишь и зачем каждая?

<details><summary>Ответ</summary>

`dig +short domain MX` — есть ли почтовые серверы и верные ли;
`dig +short domain TXT | grep spf1` — SPF со списком разрешённых отправителей;
`dig +short selector._domainkey.domain TXT` — DKIM-ключ;
`dig +short _dmarc.domain TXT` — политика DMARC;
`dig -x <IP почтового сервера>` — PTR (обратная запись), её отсутствие критично.
Дополнительно — проверить, не в чёрных списках ли IP (RBL) и совпадает ли HELO с PTR.

</details>

**D7.** После смены хостинга сайт открывается, но почта не работает. Что забыли перенести?

<details><summary>Ответ</summary>

Перенесли только A-запись, а **MX-записи** остались указывать на старый хостинг
(или были удалены вместе со старой зоной). Нужно перенести MX, SPF/DKIM/DMARC (TXT),
а также autodiscover/autoconfig-записи и убедиться, что почтовый сервис действительно
работает на новом месте. Ещё вариант — почта хостилась у старого провайдера как услуга.

</details>

**D8.** Мониторинг сообщает, что сайт недоступен, но в браузере он открывается.
Может ли это быть DNS и как проверить?

<details><summary>Ответ</summary>

Да, вполне: мониторинг может использовать другой резолвер и получать другой (старый
или неверный) адрес, либо у него кэширован NXDOMAIN. Проверка: сравнить
`dig @<резолвер мониторинга> site.com` и `dig @1.1.1.1 site.com`, `dig +trace`,
проверить все A-записи (если их несколько — одна может вести на мёртвый сервер),
резолв с разных географических точек и наличие `/etc/hosts`-переопределений на хосте мониторинга.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что происходит, когда ты вводишь доменное имя в браузере? (DNS-часть подробно)

<details><summary>Ответ</summary>

Проверяется кэш приложения → `/etc/hosts` (по nsswitch) → локальный кэш резолвера →
рекурсивный резолвер, который при пустом кэше идёт к корневым серверам, затем к TLD,
затем к авторитативным серверам зоны; ответ с TTL кэшируется на всех уровнях. Затем уже
идёт TCP-соединение и TLS.

</details>

**2.** Чем A отличается от CNAME? Когда что использовать?

<details><summary>Ответ</summary>

A указывает имя на **IP-адрес**, CNAME — на **другое имя** (алиас). CNAME удобен, когда
целевой адрес меняется (CDN, балансировщик), но его нельзя ставить на корень домена
и он добавляет дополнительный запрос.

</details>

**3.** Что такое TTL и как он влияет на миграции?

<details><summary>Ответ</summary>

Время кэширования записи. При миграции TTL снижают заранее, переключают запись,
после подтверждения возвращают прежнее значение.

</details>

**4.** Как проверить DNS-запись, минуя кэш?

<details><summary>Ответ</summary>

`dig @<конкретный сервер> domain` (например, `@1.1.1.1` или авторитативный NS);
локально — `resolvectl flush-caches`.

</details>

**5.** Что такое NXDOMAIN и SERVFAIL?

<details><summary>Ответ</summary>

`NXDOMAIN` — домена не существует; `SERVFAIL` — резолвер не смог получить/проверить ответ
(недоступность авторитативных серверов, ошибка DNSSEC, внутренний сбой).

</details>

**6.** Какие записи нужны для работы почты?

<details><summary>Ответ</summary>

MX (куда доставлять), A для почтового хоста, SPF/DKIM/DMARC (TXT) для аутентификации
отправителя, PTR для IP сервера.

</details>

**7.** Как узнать, какие DNS-серверы использует система?

<details><summary>Ответ</summary>

`resolvectl status`, `cat /etc/resolv.conf` (с учётом симлинка), `nmcli dev show | grep DNS`.

</details>

**8.** Почему «это всегда DNS»?

<details><summary>Ответ</summary>

Потому что DNS участвует в **каждом** обращении по имени, имеет несколько уровней кэширования
с отложенным эффектом (TTL), настраивается в нескольких местах (`/etc/hosts`, resolved,
netplan, CoreDNS), и его сбои проявляются странно: «работает через раз», «на одном сервере
да, на другом нет», «стало медленно». Поэтому DNS проверяют первым.

</details>

---

## 🎯 Чек-лист

- [ ] Рассказываю путь резолвинга от приложения до авторитативного сервера
- [ ] Знаю типы записей: A, AAAA, CNAME, MX, NS, TXT, PTR, SOA, SRV, CAA
- [ ] Свободно пользуюсь `dig +short`, `dig @server`, `dig +trace`, `dig -x`
- [ ] Понимаю разницу `dig` и `getent hosts` и применяю её в диагностике
- [ ] Помню правило TTL при миграциях
- [ ] Проверяю `/etc/hosts` при «загадочном» резолве
- [ ] Различаю NXDOMAIN / SERVFAIL / REFUSED
- [ ] Написал `dns_check.sh`

---

## 🏁 Linux Journey пройден

Прошёл все 22 темы — поздравляю. Осталась **часть 4 блока Linux**: bash-скриптинг
([23](/linux/23-bash-basics) → [24](/linux/24-bash-control-flow) → [25](/linux/25-bash-robust) →
[26](/linux/26-bash-devops-practice)). Затем закрыть блок: [27. Практика: лабы](/linux/27-practice-labs)
(лабы и итоговый стенд) и [28. Собеседование](/linux/28-interview) (собес). Следующий блок роадмапа —
Сети.
