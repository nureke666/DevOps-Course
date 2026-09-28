---
title: "07. TLS/SSL"
description: "Handshake, сертификаты, SNI, openssl s_client, Let's Encrypt, терминация TLS — конспект и задачи"
---

# 07. TLS/SSL — шифрование, сертификаты, handshake

> Роадмап → 2.5 Сети → протокол **TLS/SSL**. Вопрос с собеса: *«Как происходит TLS Handshake?»* —
> входит в шестёрку самых популярных.
> **После темы ты умеешь:** рассказать хендшейк по шагам, проверить сертификат из консоли,
> собрать цепочку, объяснить SNI и починить типовые TLS-ошибки.

---

## 🗺️ Схема: TLS 1.3 handshake (актуальная версия)

```text:no-line-numbers
   КЛИЕНТ                                                СЕРВЕР
      │                                                     │
      │─── ClientHello ────────────────────────────────────►│
      │    • версии TLS  • список шифров                    │
      │    • SNI (какой домен нужен) ⭐                      │
      │    • ALPN (h2 / http/1.1)                           │
      │    • key_share (уже начинает обмен ключами!)        │
      │                                                     │
      │◄── ServerHello ─────────────────────────────────────│
      │    • выбранный шифр  • key_share сервера            │
      │◄── {Certificate}    (уже зашифровано) ──────────────│
      │◄── {CertificateVerify} — подпись, доказывающая      │
      │      владение приватным ключом                      │
      │◄── {Finished} ──────────────────────────────────────│
      │                                                     │
      │  проверяет: подпись CA, срок, имя (SAN), отзыв      │
      │                                                     │
      │─── {Finished} ─────────────────────────────────────►│
      │                                                     │
      │═══ зашифрованный прикладной трафик (HTTP) ═════════►│
```

**TLS 1.3 — 1 RTT** (в TLS 1.2 было 2 RTT), а с session resumption — 0-RTT.
Отсюда главный практический вывод: обновление до TLS 1.3 реально уменьшает задержку.

⭐ **Ответ за 30 секунд:** «Клиент шлёт ClientHello со списком шифров, поддерживаемыми версиями
и SNI. Сервер отвечает ServerHello с выбранным шифром и своим сертификатом. Клиент проверяет
сертификат по цепочке до доверенного корневого CA, срок действия и совпадение имени.
Стороны по Диффи-Хеллману вырабатывают общий сеансовый ключ — асимметричная криптография
используется только для аутентификации и обмена ключами, дальше данные шифруются
симметрично (AES/ChaCha20), потому что это быстро».

---

## 1. Что решает TLS

| Свойство | Как достигается |
|----------|-----------------|
| **Конфиденциальность** | Симметричное шифрование сеансовым ключом (AES-GCM, ChaCha20) |
| **Аутентификация** | Сертификат сервера, подписанный доверенным CA |
| **Целостность** | AEAD/MAC — подмена байтов будет обнаружена |
| **Forward secrecy** | Эфемерный Диффи-Хеллман (ECDHE): украв ключ сервера, старый трафик не расшифруешь |

SSL — устаревшее название (SSLv2/v3 сломаны и запрещены). Сейчас корректно говорить TLS:
1.2 — минимум, 1.3 — актуальный.

---

## 2. Сертификат: что внутри и как проверяется

```text:no-line-numbers
Subject:      CN=example.com                ← кому выдан
SAN:          DNS:example.com, DNS:*.example.com   ⭐ реально проверяется ИМЕННО SAN
Issuer:       CN=R3, O=Let's Encrypt        ← кто выдал
Validity:     Not Before … Not After …      ← срок
Public Key:   RSA 2048 / EC P-256
Signature:    подпись издателя
```

```text:no-line-numbers
          ┌──────────────────────────┐
          │ Root CA (в доверенном    │  ← лежит в /etc/ssl/certs, в ОС и браузере
          │ хранилище системы)       │
          └────────────┬─────────────┘
                       │ подписал
          ┌────────────▼─────────────┐
          │ Intermediate CA          │  ⭐ сервер ОБЯЗАН отдать его вместе со своим
          └────────────┬─────────────┘
                       │ подписал
          ┌────────────▼─────────────┐
          │ Сертификат example.com   │
          └──────────────────────────┘
```

⭐ **Самая частая ошибка конфигурации:** не отдана промежуточная цепочка.
В браузере работает (он умеет дотягивать сам), а `curl`, Java-приложения и мобильные клиенты
падают с `unable to get local issuer certificate`. Правильный файл — `fullchain.pem`
(сертификат + промежуточные), а не `cert.pem`.

---

## 3. `openssl s_client` — главный инструмент

```bash
# Полная проверка
openssl s_client -connect example.com:443 -servername example.com </dev/null

# Только срок действия
echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null \
  | openssl x509 -noout -dates

# Кому выдан, кем, какие SAN
echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null \
  | openssl x509 -noout -subject -issuer -ext subjectAltName

# Цепочка целиком (проверяем, что промежуточные отдаются)
openssl s_client -connect example.com:443 -servername example.com -showcerts </dev/null

# Проверить конкретную версию TLS
openssl s_client -connect example.com:443 -tls1_2 </dev/null | grep Protocol
openssl s_client -connect example.com:443 -tls1_3 </dev/null | grep Protocol

# Локальные файлы
openssl x509 -in cert.pem -noout -text | head -20
openssl x509 -in cert.pem -noout -enddate
openssl rsa  -in key.pem -check -noout
openssl verify -CAfile chain.pem cert.pem

# ⭐ Совпадают ли ключ и сертификат (частая причина «nginx не стартует»)
openssl x509 -noout -modulus -in cert.pem | openssl md5
openssl rsa  -noout -modulus -in key.pem  | openssl md5   # хеши должны совпасть
```

```bash
# Дней до истечения — в скрипт мониторинга
end=$(echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null \
      | openssl x509 -noout -enddate | cut -d= -f2)
echo $(( ( $(date -d "$end" +%s) - $(date +%s) ) / 86400 )) дней
```

---

## 4. SNI — почему нужен `-servername`

SNI (Server Name Indication) — расширение ClientHello, в котором клиент **открытым текстом**
сообщает, какой домен ему нужен. Без SNI сервер не знает, какой из сотни сертификатов отдать,
и вернёт сертификат по умолчанию.

```bash
openssl s_client -connect 93.184.216.34:443                          # ← отдаст дефолтный серт
openssl s_client -connect 93.184.216.34:443 -servername example.com  # ← правильный
curl --resolve example.com:443:93.184.216.34 https://example.com/    # curl шлёт SNI сам
```

Практика: именно из-за SNI один IP обслуживает тысячи HTTPS-сайтов, и именно по SNI
провайдеры и корпоративные файрволы фильтруют HTTPS, не расшифровывая трафик.

---

## 5. Типовые ошибки и что они означают

| Ошибка | Причина | Лечение |
|--------|---------|---------|
| `certificate has expired` | Истёк срок | Продлить; автоматизировать (certbot + таймер) |
| `unable to get local issuer certificate` | ⭐ Не отдана промежуточная цепочка | Использовать `fullchain.pem` |
| `self signed certificate` | Самоподписанный серт | Добавить CA в доверенные или выпустить нормальный |
| `hostname mismatch` | Имя не совпадает с SAN | Выпустить серт с нужным SAN |
| `sslv3 alert handshake failure` | Нет общих шифров/версий | Обновить TLS-версии и ciphers |
| `certificate verify failed` в контейнере | Нет `ca-certificates` в образе | `apk add ca-certificates` / `update-ca-certificates` |
| Ошибка только на старых клиентах | Отключили TLS 1.0/1.1 или старые шифры | Оценить, кого ломаем; обычно оставить как есть |
| Неверное время на клиенте | Сертификат «ещё не действителен» | NTP |

---

## 6. Let's Encrypt и автоматизация

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d example.com -d www.example.com     # HTTP-01 challenge
sudo certbot certonly --manual --preferred-challenges dns -d '*.example.com'  # DNS-01 для wildcard
sudo certbot renew --dry-run
systemctl list-timers | grep certbot                        # автообновление
```

| Challenge | Как доказывается владение | Когда использовать |
|-----------|---------------------------|--------------------|
| HTTP-01 | Файл по `/.well-known/acme-challenge/` | Обычный сайт с открытым 80 портом |
| DNS-01 | TXT-запись `_acme-challenge` | ⭐ Wildcard-сертификаты, серверы без публичного 80 |
| TLS-ALPN-01 | Спец. сертификат в хендшейке | Когда занят только 443 |

Сертификаты LE живут 90 дней — ручное обновление гарантированно забудут.
Обновление всегда автоматизируют (systemd-таймер certbot, cert-manager в Kubernetes).

---

## 7. Терминация TLS в инфраструктуре

```text:no-line-numbers
   Клиент ──HTTPS──► [Балансировщик/Ingress] ──HTTP──► Бэкенд        edge termination
   Клиент ──HTTPS──► [Балансировщик] ──HTTPS──► Бэкенд               re-encrypt
   Клиент ──HTTPS──────────────(passthrough)──────────► Бэкенд       TLS passthrough (L4)
```

| Вариант | Плюсы | Минусы |
|---------|-------|--------|
| Терминация на краю | Один сертификат, кеш и L7-логика доступны, разгрузка бэкендов | Трафик внутри сети открыт |
| Re-encrypt | Шифрование до самого приложения | Двойной расход CPU, нужны внутренние сертификаты |
| Passthrough | Бэкенд сам владеет сертификатом, end-to-end | Балансировщик не видит HTTP → только L4-логика |

**mTLS (взаимный TLS)** — клиент тоже предъявляет сертификат. Используется для service-to-service
(service mesh, Vault, Kubernetes API) и там, где нужна сильная аутентификация без паролей.

```bash
curl --cert client.crt --key client.key https://api.internal/    # клиент с сертификатом
```

---

## 💼 Как это в DevOps

- Истёкший сертификат — классическая авария «всё легло в 3 часа ночи в субботу».
  Мониторинг срока действия обязателен (blackbox_exporter умеет из коробки).
- `openssl s_client` — стандартный способ проверить, что реально отдаёт сервер
  (в отличие от «а в браузере зелёный замочек»).
- Неполная цепочка — причина «работает в браузере, не работает в мобильном приложении и curl».
- В Kubernetes сертификатами управляет cert-manager: Issuer/ClusterIssuer + Certificate,
  секрет типа `tls` и ссылка на него в Ingress.
- Терминация TLS на Ingress/балансировщике — стандартная схема; не забывать `X-Forwarded-Proto`.

---

## 🧪 Мини-лаба

```bash
vagrant ssh web
sudo apt install -y openssl nginx

# 1. Хендшейк и параметры
openssl s_client -connect example.com:443 -servername example.com </dev/null 2>/dev/null \
  | grep -E 'Protocol|Cipher|Verify return code'

# 2. Срок действия и SAN
echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates -ext subjectAltName

# 3. Дней до истечения
end=$(echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null \
      | openssl x509 -noout -enddate | cut -d= -f2)
echo "осталось $(( ( $(date -d "$end" +%s) - $(date +%s) ) / 86400 )) дней"

# 4. SNI: с ним и без него
ip=$(dig +short example.com | head -1)
echo | openssl s_client -connect "$ip:443" 2>/dev/null | openssl x509 -noout -subject
echo | openssl s_client -connect "$ip:443" -servername example.com 2>/dev/null | openssl x509 -noout -subject

# 5. Свой CA и сертификат (мини-PKI)
mkdir -p ~/tlslab && cd ~/tlslab
openssl req -x509 -newkey rsa:2048 -nodes -keyout ca.key -out ca.crt -days 365 \
  -subj "/CN=Lab Root CA"
openssl req -newkey rsa:2048 -nodes -keyout web.key -out web.csr \
  -subj "/CN=web.lab.local" \
  -addext "subjectAltName=DNS:web.lab.local,IP:192.168.56.10"
openssl x509 -req -in web.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out web.crt -days 90 \
  -copy_extensions copyall
openssl x509 -in web.crt -noout -subject -issuer -dates -ext subjectAltName

# 6. Ключ и сертификат — от одной пары?
openssl x509 -noout -modulus -in web.crt | openssl md5
openssl rsa  -noout -modulus -in web.key | openssl md5      # хеши совпадают

# 7. Подключаем к nginx
sudo cp web.crt web.key /etc/nginx/
sudo tee /etc/nginx/sites-available/tls >/dev/null <<'EOS'
server {
  listen 8443 ssl;
  server_name web.lab.local;
  ssl_certificate     /etc/nginx/web.crt;
  ssl_certificate_key /etc/nginx/web.key;
  ssl_protocols TLSv1.2 TLSv1.3;
  location / { return 200 "TLS ok\n"; }
}
EOS
sudo ln -sf /etc/nginx/sites-available/tls /etc/nginx/sites-enabled/tls
sudo nginx -t && sudo systemctl reload nginx

# 8. Проверяем: сначала ошибка доверия, потом с нашим CA
curl -sv https://127.0.0.1:8443/ --resolve web.lab.local:8443:127.0.0.1 2>&1 | grep -E 'SSL certificate problem|unable'
curl -s --cacert ca.crt --resolve web.lab.local:8443:127.0.0.1 https://web.lab.local:8443/

# 9. Версии протокола
openssl s_client -connect 127.0.0.1:8443 -tls1_3 </dev/null 2>/dev/null | grep Protocol
openssl s_client -connect 127.0.0.1:8443 -tls1_1 </dev/null 2>&1 | grep -iE 'alert|error|no protocols'

# 10. Истёкший сертификат — увидеть ошибку
# openssl 3.x умеет задавать даты напрямую:
openssl req -x509 -newkey rsa:2048 -nodes -keyout old.key -out old.crt \
  -subj "/CN=old.lab.local" -not_before 20200101000000Z -not_after 20200102000000Z 2>/dev/null \
  && openssl x509 -in old.crt -noout -dates \
  || echo "старая версия openssl: тот же эффект даёт faketime '2020-01-01' openssl req -x509 ... -days 1"
# подключи old.crt к nginx и посмотри:
#   curl -v https://web.lab.local:8443/  → SSL certificate problem: certificate has expired
#   openssl s_client ...                 → Verify return code: 10 (certificate has expired)

# 11. Уборка
sudo rm -f /etc/nginx/sites-enabled/tls && sudo systemctl reload nginx
cd ~ && rm -rf ~/tlslab
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `openssl s_client -connect host:443 -servername host` | ⭐ Проверить TLS-соединение |
| `... -showcerts` | Вся цепочка, которую отдаёт сервер |
| `... \| openssl x509 -noout -dates` | Срок действия |
| `... -noout -subject -issuer -ext subjectAltName` | Кому, кем, какие имена |
| `openssl s_client -tls1_2 / -tls1_3` | Проверить поддержку версии |
| `openssl verify -CAfile chain.pem cert.pem` | Проверить цепочку |
| `openssl x509 -noout -modulus \| openssl md5` | ⭐ Ключ и серт от одной пары? |
| `openssl req -x509 -newkey rsa:2048 -nodes …` | Самоподписанный сертификат |
| `curl --cacert ca.crt https://…` | Доверять своему CA |
| `curl --cert c.crt --key c.key https://…` | mTLS-клиент |
| `certbot --nginx -d домен` / `certbot renew` | Let's Encrypt |

---

## 🧠 Что запомнить

1. TLS даёт конфиденциальность, аутентификацию, целостность и forward secrecy.
2. Handshake: ClientHello (шифры, SNI, ALPN) → ServerHello + сертификат → проверка → общий
   сеансовый ключ. Асимметрика — только для аутентификации и обмена ключами, данные — симметрично.
3. TLS 1.3 — 1 RTT, меньше шифров, все слабые выброшены. TLS 1.0/1.1 — устарели.
4. Имя проверяется по **SAN**, а не по CN.
5. Цепочку промежуточных сертификатов обязан отдавать сервер → используй `fullchain.pem`.
6. SNI передаётся открытым текстом и позволяет держать тысячи сайтов на одном IP.
7. `openssl s_client -servername` — главный инструмент проверки; `-showcerts` показывает цепочку.
8. Ключ и сертификат должны быть от одной пары — сверяется по modulus.
9. Let's Encrypt выдаёт на 90 дней: обновление обязательно автоматизировать.
10. Терминация TLS на балансировщике — норма; не забудь `X-Forwarded-Proto`, иначе будет
    редирект-петля (см. [06. HTTP](/network/06-http)).
11. Мониторинг срока действия сертификатов — обязательный алерт, а не «хорошо бы».

---

## Задачи

> ⭐ «Как происходит TLS Handshake?» — вопрос из топ-6 роадмапа. Ответ должен быть заучен.

---

### Блок A. Теория

**A1.** Опиши TLS-handshake по шагам (версия 1.3). Что передаётся в ClientHello?

<details><summary>Ответ</summary>

ClientHello: поддерживаемые версии TLS, список шифров, SNI (нужный домен), ALPN
(http/1.1 или h2), случайное число и `key_share` для ECDHE. Сервер отвечает ServerHello
(выбранный шифр, свой `key_share`), затем в уже зашифрованном виде — сертификат,
CertificateVerify (подпись, доказывающая владение ключом) и Finished. Клиент проверяет
сертификат (цепочка, срок, имя) и отправляет своё Finished. Далее идёт симметрично
зашифрованный прикладной трафик.

</details>

**A2.** Какие четыре задачи решает TLS?

<details><summary>Ответ</summary>

Конфиденциальность (шифрование), аутентификация сервера (сертификат), целостность
(AEAD/MAC) и forward secrecy (эфемерные ключи).

</details>

**A3.** Где в TLS используется асимметричное шифрование, а где симметричное и почему?

<details><summary>Ответ</summary>

Асимметричное — для аутентификации сервера и согласования ключа (подпись + ECDHE);
симметричное — для самих данных, потому что оно на порядки быстрее.

</details>

**A4.** Что такое forward secrecy и что даёт ECDHE?

<details><summary>Ответ</summary>

Свойство, при котором компрометация долговременного ключа сервера не позволяет
расшифровать ранее записанный трафик. Обеспечивается эфемерным Диффи-Хеллманом (ECDHE):
сеансовые ключи генерируются заново для каждого соединения и нигде не хранятся.

</details>

**A5.** Чем TLS 1.3 лучше 1.2? Сколько RTT занимает хендшейк в каждой версии?

<details><summary>Ответ</summary>

TLS 1.3: хендшейк за 1 RTT (и 0-RTT при возобновлении), убраны слабые алгоритмы
(RSA key exchange, CBC, RC4, SHA-1), forward secrecy обязателен, часть хендшейка зашифрована.
В TLS 1.2 хендшейк занимает 2 RTT.

</details>

**A6.** Что содержится в сертификате? По какому полю проверяется имя хоста?

<details><summary>Ответ</summary>

Subject (CN), SAN (список имён и IP), издатель, срок действия, публичный ключ,
назначение ключа, подпись CA. Имя хоста проверяется по **SAN**; CN современные клиенты
игнорируют.

</details>

**A7.** Что такое цепочка сертификатов и зачем нужен промежуточный CA?

<details><summary>Ответ</summary>

Цепочка доверия: корневой CA (в хранилище ОС) → промежуточный → сертификат сервера.
Промежуточный нужен, чтобы корневой ключ хранился офлайн и не подписывал сертификаты напрямую.

</details>

**A8.** Почему сайт «работает в браузере, но не работает в curl/Java»?

<details><summary>Ответ</summary>

Браузеры умеют докачивать промежуточные сертификаты (AIA fetching) и имеют свои
хранилища, а `curl`/Java строго строят цепочку из того, что отдал сервер. Если промежуточный
не отдан — ошибка `unable to get local issuer certificate`.

</details>

**A9.** Что такое SNI? Почему он нужен и что он раскрывает наблюдателю?

<details><summary>Ответ</summary>

Расширение ClientHello с именем запрашиваемого домена. Нужен, чтобы сервер выбрал
правильный сертификат при множестве сайтов на одном IP. Передаётся в открытом виде,
поэтому наблюдатель видит, к какому домену идёт подключение (частично решается ECH).

</details>

**A10.** Что такое mTLS и где применяется?

<details><summary>Ответ</summary>

Взаимный TLS: не только сервер, но и клиент предъявляет сертификат.
Применяется для service-to-service (service mesh, Vault, Kubernetes API, внутренние API),
где нужна сильная аутентификация без паролей.

</details>

**A11.** Назови три способа подтверждения владения доменом в ACME.

<details><summary>Ответ</summary>

HTTP-01 (файл по `/.well-known/acme-challenge/`), DNS-01 (TXT-запись `_acme-challenge`,
единственный для wildcard), TLS-ALPN-01 (специальный сертификат в хендшейке на 443).

</details>

**A12.** Чем отличаются edge termination, re-encrypt и passthrough?

<details><summary>Ответ</summary>

Edge termination — TLS расшифровывается на балансировщике, дальше HTTP;
re-encrypt — балансировщик расшифровывает и снова шифрует до бэкенда;
passthrough — трафик не расшифровывается вовсе, бэкенд сам терминирует TLS (балансировка только L4).

</details>

**A13.** Как проверить, что приватный ключ соответствует сертификату?

<details><summary>Ответ</summary>

Сравнить modulus: `openssl x509 -noout -modulus -in cert.pem | openssl md5`
и `openssl rsa -noout -modulus -in key.pem | openssl md5` — хеши должны совпадать.
Для EC-ключей — сравнить публичные ключи (`openssl pkey -pubout`).

</details>

**A14.** Почему сертификаты Let's Encrypt живут 90 дней и что из этого следует?

<details><summary>Ответ</summary>

Короткий срок снижает ущерб от компрометации и делает ручное обновление
непрактичным, вынуждая автоматизировать (certbot-таймер, cert-manager). Следствие:
любая ручная схема рано или поздно приведёт к падению — автообновление обязательно.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  openssl s_client -connect example.com:443 -servername example.com </dev/null
B2.  openssl s_client -connect example.com:443 -showcerts </dev/null
B3.  echo | openssl s_client -connect example.com:443 2>/dev/null | openssl x509 -noout -dates
B4.  openssl x509 -in cert.pem -noout -text
B5.  openssl verify -CAfile chain.pem cert.pem
B6.  openssl x509 -noout -modulus -in cert.pem | openssl md5
B7.  openssl req -x509 -newkey rsa:2048 -nodes -keyout k.pem -out c.pem -days 365 -subj "/CN=test"
B8.  curl --cacert ca.crt https://internal.local/
B9.  curl -k https://self-signed.local/
B10. certbot renew --dry-run
B11. openssl s_client -connect host:443 -tls1_1 </dev/null
```

- **B1.** Устанавливает TLS-соединение с указанием SNI, печатает цепочку, шифр и код проверки.
- **B2.** То же плюс полные PEM всех сертификатов, которые отдал сервер.
- **B3.** Печатает даты начала и окончания действия сертификата.
- **B4.** Полная расшифровка локального сертификата.
- **B5.** Проверяет сертификат против указанного CA-файла.
- **B6.** Хеш modulus — для сверки с ключом.
- **B7.** Создаёт самоподписанный сертификат и ключ без пароля.
- **B8.** Обращение к сайту с доверием к своему CA.
- **B9.** Игнорирует проверку сертификата — только для отладки, никогда в проде.
- **B10.** Тестовый прогон обновления Let's Encrypt без реального выпуска.
- **B11.** Проверяет, поддерживается ли TLS 1.1 (на современном сервере — ошибка).

**B12.** Что означает каждая ошибка:
`certificate has expired`, `unable to get local issuer certificate`,
`self signed certificate in certificate chain`, `hostname mismatch`,
`sslv3 alert handshake failure`?

<details><summary>Ответ</summary>

`expired` — истёк срок; `unable to get local issuer certificate` — не отдана
промежуточная цепочка (или нет CA в хранилище клиента); `self signed certificate in chain` —
в цепочке самоподписанный корень, которому клиент не доверяет; `hostname mismatch` —
запрошенное имя отсутствует в SAN; `handshake failure` — нет общих версий TLS или шифров.

</details>

---

### Блок C. Практика

**C1. Разбор чужого сертификата.** Для трёх сайтов собери: издателя, срок действия, SAN,
версию TLS, выбранный шифр, полную цепочку. Оформи как таблицу.

<details><summary>Ответ</summary>

Собирается командами из шпаргалки; в таблице полезно фиксировать `Protocol`, `Cipher`,
`Verify return code: 0 (ok)` и число сертификатов в цепочке.

</details>

**C2. Дни до истечения.** Напиши `certcheck.sh <host[:port]>…`, который печатает домен,
издателя и количество оставшихся дней, и возвращает код 2, если меньше 14 дней
(связь с bash-темой про боевые паттерны).

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
set -uo pipefail
rc=0
for target in "$@"; do
  host="${target%%:*}"; port="${target#*:}"; [[ "$port" == "$host" ]] && port=443
  end=$(echo | openssl s_client -connect "$host:$port" -servername "$host" 2>/dev/null \
        | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2) || { echo "$host: ошибка"; rc=2; continue; }
  days=$(( ( $(date -d "$end" +%s) - $(date +%s) ) / 86400 ))
  printf '%-30s %5s дней\n' "$host" "$days"
  (( days < 14 )) && rc=2
done
exit "$rc"
```

</details>

**C3. Свой CA и сертификат.** Создай корневой CA, выпусти сертификат для `web.lab.local`
с SAN (DNS + IP), подключи к nginx на 8443. Покажи ошибку доверия в curl без `--cacert`
и успех с ним. Добавь CA в системное хранилище и покажи, что curl работает уже без флага.

<details><summary>Ответ</summary>

Ключевые шаги — в мини-лабе конспекта. Добавление CA в систему:
`sudo cp ca.crt /usr/local/share/ca-certificates/lab-ca.crt && sudo update-ca-certificates`,
после чего `curl https://web.lab.local:8443/` работает без `--cacert`.

</details>

**C4. Неполная цепочка.** Настрой nginx так, чтобы он отдавал **только** серверный сертификат
без промежуточного. Покажи, что ошибка воспроизводится в curl, и почини через fullchain.

<details><summary>Ответ</summary>

Если в `ssl_certificate` указать только серверный сертификат, `s_client -showcerts`
покажет одну запись, а curl вернёт `unable to get local issuer certificate`.
Починка: `cat server.crt intermediate.crt > fullchain.pem` и указать его в `ssl_certificate`.

</details>

**C5. SNI.** На одном IP и порту настрой два TLS-сайта с разными сертификатами.
Покажи, что выбор зависит от `-servername` / `--resolve`, и что без SNI отдаётся дефолтный.

<details><summary>Ответ</summary>

Два server-блока с `listen 443 ssl` и разными `server_name`/сертификатами.
`openssl s_client -connect IP:443` без `-servername` отдаст сертификат default_server;
с `-servername b.lab.local` — второй сертификат.

</details>

**C6. Версии и шифры.** Проверь, какие версии TLS поддерживает твой nginx.
Отключи TLS 1.2, оставь только 1.3 и покажи, какие клиенты перестали подключаться.
Верни обратно.

<details><summary>Ответ</summary>

`ssl_protocols TLSv1.3;` — клиенты без поддержки 1.3 (старые openssl, Java 8 ранних
сборок, старые Android) получают `handshake failure`. Проверка: `openssl s_client -tls1_2`.

</details>

**C7. mTLS.** Выпусти клиентский сертификат своим CA, включи `ssl_verify_client on` в nginx.
Покажи: без сертификата — 400/403, с сертификатом — 200.

<details><summary>Ответ</summary>

```nginx
ssl_client_certificate /etc/nginx/ca.crt;
ssl_verify_client on;
```
Без клиентского сертификата nginx вернёт `400 No required SSL certificate was sent`,
с `curl --cert client.crt --key client.key` — 200.

</details>

**C8. Истёкший сертификат.** Выпусти сертификат со сроком в прошлом (или используй `faketime`),
подключи и покажи поведение curl, openssl и браузера. Что именно пишут в логах?

<details><summary>Ответ</summary>

curl: `certificate has expired`; openssl: `Verify return code: 10 (certificate has expired)`;
браузер показывает страницу предупреждения. В `error.log` nginx при этом чисто —
ошибка на стороне клиента, что и путает.

</details>

**C9. Мониторинг.** Настрой проверку срока сертификата, выводящую метрику Prometheus
(`tls_cert_expiry_days`), и алерт-правило «меньше 14 дней».

<details><summary>Ответ</summary>

```bash
days=$(...)  # как в C2
printf 'tls_cert_expiry_days{host="%s"} %s\n' "$host" "$days" > /tmp/tls.prom.tmp
mv /tmp/tls.prom.tmp /var/lib/node_exporter/textfile/tls.prom
```
Правило: `tls_cert_expiry_days < 14` → warning, `< 3` → critical.
В проде эту метрику обычно даёт blackbox_exporter (`probe_ssl_earliest_cert_expiry`).

</details>

**C10. TLS в Docker.** Собери образ, где `curl` падает с `certificate verify failed`,
и почини добавлением `ca-certificates`. Объясни, почему в slim/alpine-образах это частая проблема.

<details><summary>Ответ</summary>

В `alpine`/`*-slim` образах нет корневых сертификатов, поэтому любой HTTPS-запрос
падает с `certificate verify failed`. Лечение: `apk add --no-cache ca-certificates`
или `apt-get install -y ca-certificates && update-ca-certificates`.

</details>

---

### Блок D. Инциденты

**D1.** Ночью сайт перестал открываться у всех, в браузере — предупреждение безопасности.
Что случилось и как не допустить повторения?

<details><summary>Ответ</summary>

Истёк сертификат и не сработало автообновление. Профилактика: certbot-таймер
с алертом на ошибку, мониторинг `probe_ssl_earliest_cert_expiry` с порогом 14 дней,
проверка после каждого обновления, документированный ручной сценарий.

</details>

**D2.** Мобильное приложение перестало подключаться к API, в браузере всё хорошо.
Самая вероятная причина?

<details><summary>Ответ</summary>

Неполная цепочка: браузер дотягивает промежуточный сертификат сам, а мобильный
HTTP-клиент — нет. Проверить `s_client -showcerts`, перейти на `fullchain.pem`.

</details>

**D3.** После переезда на новый балансировщик часть пользователей получает сертификат
другого сайта. Диагноз?

<details><summary>Ответ</summary>

Не настроен или не работает SNI-выбор: запросы попадают в `default_server`
с чужим сертификатом. Проверить `server_name`, наличие сертификата для нужного домена
и порядок server-блоков.

</details>

**D4.** Java-приложение в контейнере не может достучаться до внутреннего API:
`PKIX path building failed`. Что делать?

<details><summary>Ответ</summary>

В образ не добавлен корневой сертификат внутреннего CA (или используется собственный
truststore Java). Решение: `keytool -import` в cacerts образа, монтирование корпоративного CA,
`update-ca-certificates` + `-Djavax.net.ssl.trustStore`.

</details>

**D5.** Приложение за Ingress уходит в бесконечный редирект после включения HTTPS.
Как это связано с терминацией TLS?

<details><summary>Ответ</summary>

Ingress терминирует TLS и ходит на приложение по HTTP; приложение видит схему `http`
и редиректит на `https` — цикл. Лечение: передавать `X-Forwarded-Proto` и научить приложение
ему доверять (или отключить принудительный редирект в приложении).

</details>

**D6.** `nginx -t` говорит `SSL_CTX_use_PrivateKey_file failed (key values mismatch)`.
Что произошло?

<details><summary>Ответ</summary>

Указанные `ssl_certificate` и `ssl_certificate_key` — из разных пар (перепутали файлы
при обновлении). Проверка по modulus, затем положить правильную пару.

</details>

**D7.** Клиент из другой страны жалуется на ошибку сертификата, у остальных всё в порядке.
Две гипотезы.

<details><summary>Ответ</summary>

(1) Промежуточный сертификат не отдаётся, а у клиента его нет в кеше;
(2) клиент попадает на другой сервер/CDN-узел с устаревшей конфигурацией, либо у него
неверное системное время, либо TLS-инспекция корпоративного прокси подменяет сертификат.

</details>

**D8.** certbot не смог обновить сертификат: `Timeout during connect (likely firewall problem)`.
Что проверить?

<details><summary>Ответ</summary>

HTTP-01 требует доступности 80 порта снаружи: проверить файрвол/security group,
что nginx слушает 80 и отдаёт `/.well-known/acme-challenge/`, что DNS указывает на этот сервер.
Альтернатива — перейти на DNS-01.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как происходит TLS handshake?

<details><summary>Ответ</summary>

ClientHello (версии, шифры, SNI, key_share) → ServerHello + сертификат + подпись →
проверка сертификата клиентом → согласование сеансового ключа → шифрованный обмен.

</details>

**2.** Зачем нужен сертификат и кто его подписывает?

<details><summary>Ответ</summary>

Сертификат доказывает, что публичный ключ принадлежит этому домену; подписывает CA,
которому доверяет ОС/браузер.

</details>

**3.** Где в TLS симметричное шифрование, а где асимметричное?

<details><summary>Ответ</summary>

Асимметричное — аутентификация и обмен ключами; симметричное — сами данные (быстрее).

</details>

**4.** Что такое SNI?

<details><summary>Ответ</summary>

Расширение с именем домена в ClientHello: позволяет выбрать нужный сертификат на общем IP.

</details>

**5.** Что такое forward secrecy?

<details><summary>Ответ</summary>

Свойство, при котором утечка ключа сервера не раскрывает ранее записанный трафик (ECDHE).

</details>

**6.** Чем отличается TLS 1.3 от 1.2?

<details><summary>Ответ</summary>

1 RTT вместо 2, обязательный forward secrecy, удалены слабые шифры, часть хендшейка шифруется.

</details>

**7.** Почему сертификат может быть валиден в браузере, но не в curl?

<details><summary>Ответ</summary>

Браузер умеет достраивать цепочку и имеет своё хранилище; curl — нет.

</details>

**8.** Что такое mTLS?

<details><summary>Ответ</summary>

Взаимная аутентификация по сертификатам с обеих сторон.

</details>

**9.** Как проверить сертификат из командной строки?

<details><summary>Ответ</summary>

`openssl s_client -connect host:443 -servername host` (+ `x509 -noout -dates/-ext subjectAltName`).

</details>

**10.** Как автоматизируют выпуск сертификатов?

<details><summary>Ответ</summary>

ACME-клиентами (certbot, cert-manager, traefik) с автоматическим продлением по таймеру.

</details>

---

### 🎯 Чек-лист

- [ ] Рассказываю handshake по памяти
- [ ] Знаю, что имя проверяется по SAN
- [ ] Проверяю сертификат через `openssl s_client`
- [ ] Понимаю проблему неполной цепочки и знаю про fullchain
- [ ] Объясню SNI и зачем `-servername`
- [ ] Выпустил свой CA и сертификат, настроил nginx
- [ ] Настроил mTLS хотя бы один раз
- [ ] Сделал скрипт проверки срока действия и знаю про алерт
