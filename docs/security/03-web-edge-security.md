---
title: "03. Безопасность веба и периметра (edge)"
description: "Блок → Безопасность → тема 03. Опирается на"
---

# 03. Безопасность веба и периметра (edge)

> Блок → Безопасность → тема 03. Опирается на
> [../Network/12_nginx.md](/network/12-nginx) (nginx, базовые заголовки, `limit_req`) ·
> [../Network/07_tls.md](/network/07-tls) (TLS, сертификаты, `openssl s_client`) ·
> [../Network/06_http.md](/network/06-http) (HTTP, заголовки, CORS). Принципы — в
> [01_security_mindset.md](/security/01-security-mindset).
>
> **После темы ты умеешь:** разложить OWASP Top 10:2025 на «что может инфраструктура» и
> «что только код»; настроить в nginx HSTS, CSP и остальные заголовки без ловушки наследования;
> сделать rate limit, который отвечает `429` и не обходится подделкой IP; включить WAF
> (ModSecurity/Coraza + OWASP CRS) через DetectionOnly; отличить DDoS L3/4 от L7 и понять,
> кто что гасит; проверить свой периметр testssl.sh, nmap и curl.

---

## 🗺️ Карта темы

```text
 клиент / бот / атакующий
        │
        ▼  L3/4  провайдер, anycast, scrubbing      ← объёмный DDoS, SYN flood  (гасит не nginx)
        ▼  CDN / облачный WAF (опционально)          ← L7-флуд, боты, known exploits
 ┌──────┴────────────────────── EDGE: nginx ─────────────────────────────────────┐
 │ TLS 1.2/1.3 · HSTS · CSP и заголовки · server_tokens off · свои error pages     │
 │ rate limit (429) · limit_conn · таймауты от slowloris · реальный IP только от  │
 │ доверенных прокси · WAF (ModSecurity/Coraza + CRS): DetectionOnly → On          │
 └──────┬───────────────────────────────────────────────────────────────────────┘
        ▼
      app  ← authz, валидация ввода, параметризованные запросы — это уже код (OWASP A01, A05…)
        │
 проверка снаружи: testssl.sh · SSL Labs · curl -I · nmap (⚠️ только свои хосты)
```text
---

## 1. OWASP Top 10:2025 глазами девопса

OWASP Top 10 — рейтинг самых критичных классов рисков веб-приложений. Актуальная редакция —
**2025** (финальная версия опубликована в январе 2026, предыдущая — 2021). Большинство пунктов
закрывает код, но у инфраструктуры в каждом есть своя роль.

| # | Категория 2025 | Что может инфраструктура | Что только код |
|---|----------------|--------------------------|----------------|
| A01 | Broken Access Control (включая SSRF) | Не выставлять админки и `/metrics` наружу, сегментация сети; против SSRF — IMDSv2 с hop limit 1, egress-правила, запрет 169.254.169.254 из подов | Проверка прав на каждый объект (IDOR), валидация URL |
| A02 | Security Misconfiguration | Заголовки, `server_tokens off`, нет directory listing и дефолтных паролей, закрытые бакеты, харденинг ([02](/security/02-linux-hardening)) | Безопасные дефолты фреймворка, выключенный debug |
| A03 | Software Supply Chain Failures | Сканы образов и зависимостей, SBOM, пины по digest, подписи ([04](/security/04-vuln-management), [06](/security/06-k8s-security)) | Выбор и обновление библиотек |
| A04 | Cryptographic Failures | TLS 1.2+, HSTS, шифрование at rest, управление ключами | Хеширование паролей (argon2/bcrypt), без самописной криптографии |
| A05 | Injection | WAF + CRS как **компенсирующий** контроль, least privilege у учётки БД | Параметризованные запросы, экранирование — настоящий фикс |
| A06 | Insecure Design | Threat modeling ([01](/security/01-security-mindset)), лимиты на тяжёлые операции | Архитектура бизнес-логики |
| A07 | Authentication Failures | Rate limit на `/login`, MFA/SSO для админок, короткие сессии на прокси | Хранение паролей, управление сессиями |
| A08 | Software or Data Integrity Failures | Подпись артефактов, защищённый CI, проверка обновлений | Безопасная десериализация |
| A09 | Security Logging and Alerting Failures | Access-логи, аудит, вывоз логов, алерты на всплески 401/403/429 ([07](/security/07-security-incidents-compliance)) | Логирование событий безопасности в приложении |
| A10 | Mishandling of Exceptional Conditions | Свои error pages, `proxy_intercept_errors`, стек-трейсы не уходят клиенту, fail-closed лимиты | Обработка ошибок и крайних случаев |

Что изменилось с 2021 (коротко): **Security Misconfiguration** поднялась с 5-го на 2-е место;
«Vulnerable and Outdated Components» расширили до **Software Supply Chain Failures** (A03);
**SSRF** влили в Broken Access Control; появилась новая категория **Mishandling of Exceptional
Conditions** (A10); A07 и A09 переименованы.

> ⭐ WAF не исправляет SQL-инъекцию, а прикрывает её, пока разработчики чинят код.
> Правильная фраза на собесе: «инфраструктура уменьшает вероятность и ущерб, но причину
> уязвимости устраняет код».

---

## 2. Заголовки безопасности в nginx

Базовые заголовки есть в [../Network/12_nginx.md](/network/12-nginx) (раздел 7). Полный
набор и зачем каждый:

| Заголовок | Значение (пример) | От чего защищает |
|-----------|-------------------|------------------|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | Браузер ходит только по HTTPS: нет SSL stripping на первом HTTP-запросе после визита |
| `Content-Security-Policy` | `default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'` | XSS (откуда можно грузить скрипты), clickjacking (`frame-ancestors`) |
| `X-Content-Type-Options` | `nosniff` | Браузер не «угадывает» тип: загруженный `.txt` не исполнится как JS |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Утечка URL с токенами и путями на чужие сайты |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | Доступ страницы и iframe к API браузера |
| `X-Frame-Options` | `DENY` | Clickjacking в старых браузерах; современная замена — CSP `frame-ancestors` |
| `X-XSS-Protection` | не отправлять (или `0`) | Устарел: фильтр убран из браузеров и сам создавал уязвимости |

Удобный приём — вынести заголовки в файл и подключать в каждый `server`/`location`:
```nginx
# /etc/nginx/snippets/security-headers.conf
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
add_header Content-Security-Policy "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
add_header X-Frame-Options "DENY" always;
```text
- `always` — заголовок добавляется и к ответам 4xx/5xx (по умолчанию только к 2xx/3xx).
- ⚠️ **Ловушка наследования:** если в `location` есть хотя бы один свой `add_header`, все
  `add_header` уровня `server` там **пропадают**. Лечится: `include` сниппета в каждом таком
  `location` или, начиная с nginx **1.29.3**, директивой `add_header_inherit merge;` на верхнем
  уровне — тогда заголовки родителя складываются с заголовками потомка.

**HSTS — осторожно, это «нельзя отменить быстро»:**
- Браузер запоминает политику на `max-age`. Начинай с `max-age=300`, проверь все поддомены,
  потом год.
- `includeSubDomains` сломает любой поддомен без HTTPS (старая админка на `http://`).
- `preload` + заявка в hstspreload.org вшивают домен в браузеры; удаление из списка занимает
  месяцы. Не включай на учебных и чужих доменах.
- HSTS имеет смысл только на HTTPS-ответе; HTTP-сервер делает `301` на HTTPS.

**CSP — внедряй через Report-Only.** Строгая политика сразу ломает фронтенд (инлайн-скрипты,
CDN, аналитика). Порядок: `Content-Security-Policy-Report-Only` с `report-uri`/`report-to` →
собрать нарушения за 1–2 недели → поправить фронт/политику → включить enforce.

```bash
curl -skI https://app.lab.local:8443/ | grep -iE 'strict-transport|content-security|x-content-type|referrer|permissions|x-frame|server:'
```text
---

## 3. TLS-конфигурация

Как работает TLS и как читать сертификат — в [../Network/07_tls.md](/network/07-tls).
Для nginx основа — генератор Mozilla (ssl-config.mozilla.org), профиль **intermediate**:

```nginx
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
ssl_prefer_server_ciphers off;      # все шифры в списке сильные — пусть клиент выберет быстрый для себя
ssl_session_cache shared:TLS:10m;
ssl_session_timeout 1d;
ssl_session_tickets off;            # тикеты с долгоживущим ключом ослабляют forward secrecy
```text
| Решение | Почему |
|---------|--------|
| Только TLS 1.2 и 1.3 | TLS 1.0/1.1 устарели (RFC 8996); в OpenSSL 3.x они работают только на security level 0 |
| Только ECDHE, AEAD-шифры | Forward secrecy; нет CBC и RC4 |
| `ssl_ciphers` не касается TLS 1.3 | У 1.3 свой короткий набор сильных шифров |
| Сертификат — полная цепочка | Иначе «в браузере работает, в curl/мобильном — нет» |
| OCSP stapling | Let's Encrypt **выключил OCSP 6 августа 2025** и перешёл на CRL — для его сертификатов `ssl_stapling` бесполезен; у коммерческих CA проверь, есть ли OCSP |

> 💡 Самая частая TLS-авария — не слабый шифр, а истёкший сертификат. Мониторинг срока —
> в [../Network/07_tls.md](/network/07-tls) («Как это в DevOps»).

---

## 4. Rate limiting, который работает

Синтаксис `limit_req` — в [../Network/12_nginx.md](/network/12-nginx). Там в комментарии
написано «429 при превышении» — это неточно: **по умолчанию nginx отвечает `503`**, и клиенты,
мониторинг и SLO-метрики примут это за падение сервера. Нужна директива `limit_req_status 429`.

```nginx
# http {}
limit_req_zone  $binary_remote_addr zone=perip:10m rate=10r/s;   # общий лимит на IP
limit_req_zone  $binary_remote_addr zone=login:10m rate=5r/m;    # подбор паролей
limit_conn_zone $binary_remote_addr zone=conn:10m;
limit_req_status  429;
limit_conn_status 429;

# server {}
location / {
    limit_req  zone=perip burst=20 nodelay;
    limit_conn conn 20;
    proxy_pass http://app:8080;
}
location = /login {
    limit_req zone=login burst=3 nodelay;
    proxy_pass http://app:8080;
}
```text
| Вариант | Поведение при всплеске |
|---------|------------------------|
| `burst=20` (без `nodelay`) | Лишние запросы встают в очередь и **задерживаются** до темпа `rate` — пользователь видит тормоза |
| `burst=20 nodelay` | До 20 лишних обслуживаются сразу, слоты освобождаются с темпом `rate`, сверх — `429` |
| `burst=20 delay=8` | Первые 8 лишних — сразу, следующие — с задержкой, сверх 20 — `429` (двухступенчатый режим) |
| `limit_req_dry_run on` | Ничего не режет, только пишет в error log — включать новый лимит так |

**Реальный IP — главная ловушка.** За балансировщиком `$remote_addr` — адрес балансировщика:
все клиенты делят один лимит. Лечится модулем realip, но **только для доверенных прокси**:
```nginx
set_real_ip_from 10.0.0.0/8;          # ✅ адреса ТВОИХ балансировщиков/CDN
real_ip_header   X-Forwarded-For;
real_ip_recursive on;
# ❌ set_real_ip_from 0.0.0.0/0;  → любой клиент пришлёт «X-Forwarded-For: 1.2.3.4»
#    и обойдёт rate limit, allowlist по IP и испортит логи
```text
Лимиты ставят не «на глаз»: смотри реальный профиль в access-логах (p99 запросов на IP в
секунду), бери запас в 2–3 раза, включай через `dry_run`, следи за долей `429`. От слабых
L7-атак вроде slowloris помогают короткие таймауты:
```nginx
client_header_timeout 10s;  client_body_timeout 10s;  send_timeout 10s;
keepalive_timeout 30s;      client_max_body_size 10m;
```text
---

## 5. WAF: ModSecurity / Coraza + OWASP CRS

**WAF** (web application firewall) проверяет содержимое HTTP-запросов по правилам и блокирует
известные атаки: SQLi, XSS, RCE, path traversal, сканеры.

| Компонент | Что это |
|-----------|---------|
| **OWASP CRS** (Core Rule Set, v4) | Открытый набор правил — «мозги» WAF |
| **ModSecurity v3** (libmodsecurity) | Движок; к nginx подключается через ModSecurity-nginx connector. Trustwave прекратил поддержку в июле 2024, проект перешёл в OWASP |
| **Coraza** | Движок OWASP на Go, совместим с правилами ModSecurity и CRS v4; есть для Caddy, HAProxy (coraza-spoa), Envoy (coraza-proxy-wasm) |
| Облачный WAF | AWS WAF, Cloudflare, Yandex Smart Web Security (WAF + ARL + защита от ботов) |

**Как работает CRS — anomaly scoring.** Правило не блокирует само, а добавляет баллы
(critical = 5). Если сумма за запрос ≥ порога (`ANOMALY_INBOUND`, по умолчанию 5) — блок.
**Paranoia level** 1–4: чем выше, тем больше правил и ложных срабатываний. Начинают с PL1.

Внедрение — как любой gate ([../CICD/13_quality_security.md](/cicd/13-quality-security), раздел 8):
```text
1. DetectionOnly: только логируем, ничего не режем (1–2 недели на реальном трафике)
2. Разбор срабатываний: атаки → ок; ложные → исключения (rule exclusion) по конкретному
   правилу/параметру/пути, а не «выключить CRS»
3. On с высоким порогом (например, ANOMALY_INBOUND=10) → постепенно снижаем до 5
4. PL2 — для чувствительных частей (админка, платежи)
```text
На стенде WAF — отдельный контейнер `waf` (образ `owasp/modsecurity-crs:nginx`, профиль compose `waf`):
```bash
cd ~/labs/security/edge && docker compose --profile waf up -d waf
curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:8081/?id=1'%20OR%20'1'='1"   # DetectionOnly → 200
docker compose logs waf | grep -o '"ruleId":"[0-9]*"' | sort | uniq -c                   # какие правила сработали
# переключить на блокировку: MODSEC_RULE_ENGINE=On → docker compose --profile waf up -d waf
curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:8081/?id=1'%20OR%20'1'='1"   # → 403
```text
Аудит-лог образа по умолчанию пишется в stdout в JSON (`MODSEC_AUDIT_LOG=/dev/stdout`) —
его видно в `docker compose logs waf` и забирает любой сборщик логов.

> ⚠️ **WAF в Kubernetes:** проект `kubernetes/ingress-nginx` (в котором ModSecurity включался
> аннотацией) снят с поддержки в марте 2026 — без исправлений уязвимостей. Если WAF жил там,
> его переносят вместе с миграцией ингресса: на Gateway API-реализацию с WAF-фильтром
> (например, Coraza для Envoy) или в облачный WAF перед кластером.

---

## 6. DDoS: L3/4 против L7

| | L3/4 (сеть/транспорт) | L7 (приложение) |
|---|------------------------|-----------------|
| Примеры | UDP-флуд, amplification (DNS/NTP/memcached), SYN flood | HTTP-флуд на тяжёлые эндпоинты, slowloris, перебор `/search`, HTTP/2 Rapid Reset |
| Цель | Забить канал или таблицы соединений | Исчерпать CPU, пул БД, воркеры приложения |
| Как выглядит | Гигабиты/миллионы пакетов, канал до сервера забит | Трафик «похож на пользователей», но RPS и латентность растут |
| Кто гасит | **Провайдер/облако**: anycast, scrubbing-центры, CDN. Nginx тут бессилен — канал забит до него | Nginx (лимиты, таймауты, кэш), WAF/анти-бот, CDN, автоскейлинг, лимиты в приложении |
| Что можно на хосте | `net.ipv4.tcp_syncookies=1` ([02](/security/02-linux-hardening)), не светить origin IP | `limit_req`, `limit_conn`, кэш, таймауты, отдельные лимиты тяжёлым эндпоинтам |

**HTTP/2 Rapid Reset (CVE-2023-44487)** — клиент открывает поток и сразу сбрасывает, сервер
тратит ресурсы на обработку. Уязвимость в каталоге CISA KEV (эксплуатировалась массово); nginx
закрыл её обновлением — ещё один аргумент патчить edge первым ([04](/security/04-vuln-management)).

Практика защиты от DDoS: трафик идёт через CDN/облачную защиту, **origin IP не публичен**
(иначе атакуют мимо CDN), security group origin пропускает только адреса CDN, дешёвые ответы
кэшируются, у тяжёлых эндпоинтов — свои лимиты, есть runbook «нас DDoS'ят» с контактами провайдера.

---

## 7. Итоговый конфиг edge-стенда

«После» для стартового конфига из [00_INDEX.md](/security/) (лаба 4 ведёт от одного к другому):
```nginx
# ~/labs/security/edge/nginx/conf.d/app.conf — hardened
server_tokens off;
limit_req_zone  $binary_remote_addr zone=perip:10m rate=10r/s;
limit_req_zone  $binary_remote_addr zone=login:10m rate=5r/m;
limit_conn_zone $binary_remote_addr zone=conn:10m;
limit_req_status  429;
limit_conn_status 429;

server {                                           # HTTP → только редирект
    listen 80;
    server_name app.lab.local;
    return 301 https://$host:8443$request_uri;     # на стенде HTTPS-порт 8443
}

server {
    listen 443 ssl;
    http2 on;
    server_name app.lab.local;

    ssl_certificate     /etc/nginx/certs/app.crt;
    ssl_certificate_key /etc/nginx/certs/app.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:TLS:10m;
    ssl_session_tickets off;

    add_header Strict-Transport-Security "max-age=300; includeSubDomains" always;   # на стенде коротко
    add_header Content-Security-Policy "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;

    client_header_timeout 10s;
    client_body_timeout   10s;
    client_max_body_size  1m;

    proxy_intercept_errors on;                      # 5xx бэкенда → своя страница, без стек-трейсов
    error_page 500 502 503 504 /50x.html;
    location = /50x.html { root /usr/share/nginx/html; internal; }

    location / {
        limit_req  zone=perip burst=20 nodelay;
        limit_conn conn 20;
        proxy_pass http://app:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location = /login {
        limit_req zone=login burst=3 nodelay;
        proxy_pass http://app:8080;
    }
}
```text
```bash
docker compose exec nginx nginx -t && docker compose exec nginx nginx -s reload
```text
> ⚠️ `location = /login` задаёт `limit_req`, но не `add_header` — поэтому заголовки уровня
> `server` там сохраняются. Добавишь в него свой `add_header` — повтори весь набор (или
> `add_header_inherit merge;`).

---

## 8. Проверка периметра снаружи

> ⚠️ Сканировать можно **только свои** хосты и стенды. Скан чужой инфраструктуры без
> письменного разрешения — нарушение закона и правил облака/провайдера.

**testssl.sh** — полный аудит TLS локально, в том числе для внутренних хостов:
```bash
docker run --rm -t --network host -v ~/labs/security/edge/certs:/certs:ro \
  ghcr.io/testssl/testssl.sh:3.2 --ip 127.0.0.1 --add-ca /certs/ca.crt -p -S -h -U \
  https://app.lab.local:8443
#   -p протоколы · -S данные сертификата · -h HTTP-заголовки (HSTS и др.) · -U уязвимости
#   --ip — куда реально подключаться (в контейнере нет твоего /etc/hosts)
#   --jsonfile out.json / --htmlfile out.html — отчёт; --severity HIGH — фильтр для файлов
```text
**SSL Labs** (ssllabs.com/ssltest) — оценка A…F для **публичных** хостов; для стенда не подходит.

**curl** — заголовки, редиректы, коды:
```bash
curl -sI http://app.lab.local:8080/ | grep -i location              # 301 на https
curl -skI https://app.lab.local:8443/ | grep -iE 'server|strict|content-security'
for i in $(seq 40); do curl -sk -o /dev/null -w '%{http_code}\n' https://app.lab.local:8443/; done | sort | uniq -c
curl -sk -H 'X-Forwarded-For: 1.2.3.4' https://app.lab.local:8443/ | grep -i x-real-ip   # IP не подменяется
```text
**nmap** — что вообще открыто и какие шифры:
```bash
nmap -sV -p- 127.0.0.1                                    # все порты и версии сервисов
nmap -p 8443 --script ssl-enum-ciphers 127.0.0.1          # протоколы и шифры с оценкой
nmap -sV -p 22 192.168.56.30                              # как sec01 видно из админской сети
```text
| Находка | Исправление |
|---------|-------------|
| TLS 1.0/1.1 или CBC-шифры | `ssl_protocols TLSv1.2 TLSv1.3`, ECDHE+AEAD |
| Нет HSTS / CSP | Сниппет заголовков с `always` |
| `Server: nginx/1.30.5` | `server_tokens off` |
| HTTP не редиректит | `return 301 https://…` |
| Неполная цепочка | `fullchain.pem` вместо `cert.pem` |
| Лишний открытый порт | Закрыть/слушать 127.0.0.1 ([01](/security/01-security-mindset), раздел 5) |

---

## 9. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| `limit_req` без `limit_req_status` | Клиенты получают `503`, мониторинг видит «сервер упал» | `limit_req_status 429;` |
| `set_real_ip_from 0.0.0.0/0` | Любой обходит лимиты и allowlist подделкой `X-Forwarded-For` | Только адреса своих прокси/CDN |
| Свой `add_header` в `location` | Все заголовки безопасности `server` там пропали | Сниппет в каждый location или `add_header_inherit merge` |
| Заголовки без `always` | На страницах ошибок заголовков нет | `always` |
| HSTS `preload` на пробу | Домен вшит в браузеры на месяцы | Сначала короткий `max-age`, preload — осознанно |
| CSP сразу в enforce | Сломан фронтенд, политику «временно» убирают навсегда | Report-Only → разбор → enforce |
| WAF сразу в блокирующем режиме | Ложные срабатывания режут пользователей, WAF выключают | DetectionOnly → исключения → On |
| «WAF закрыл SQLi» | Обход правил — вопрос времени | WAF компенсирует, чинит код |
| Origin IP публичен | DDoS идёт мимо CDN | SG пропускает только CDN, IP не светить |
| `ssl_stapling on` с Let's Encrypt | С августа 2025 у LE нет OCSP — только warnings | Для LE не нужно |
| Лимит «на глаз» 1r/s | Режет реальных пользователей за NAT | По access-логам, запас 2–3×, `dry_run` |
| Скан чужого хоста «для практики» | Нарушение закона и ToS | Только свои стенды |

---

## 💼 Как это в DevOps

- Edge-конфиг — общий шаблон (сниппеты заголовков, TLS, лимитов) в git, а не копипаста
  в каждом сервисе. Изменения — через MR и `nginx -t` в CI.
- WAF и лимиты — совместная работа с командой сервиса: исключения CRS обсуждают по
  конкретным правилам и параметрам, а не «отключите WAF, он мешает».
- Проверка TLS и заголовков — в расписании (testssl.sh по списку хостов, алерт на
  регресс) и в мониторинге (срок сертификата, доля 429/403, всплеск 5xx на edge).
- На собесе про OWASP спрашивают не «перечисли десять», а «что ты как девопс можешь сделать
  против injection/SSRF/misconfig» — отвечай таблицей «инфра vs код».
- DDoS L3/4 решается договором и настройкой у провайдера до инцидента; runbook с контактами —
  часть подготовки ([07](/security/07-security-incidents-compliance)).

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Проверить заголовки | `curl -skI https://host/ \| grep -iE 'strict\|content-security\|nosniff'` |
| Заголовки и на ошибках | `add_header … always;` |
| Не терять заголовки в location | сниппет `include` или `add_header_inherit merge;` (1.29.3+) |
| Спрятать версию nginx | `server_tokens off;` |
| Rate limit с 429 | `limit_req zone=… burst=N nodelay;` + `limit_req_status 429;` |
| Проверить новый лимит без вреда | `limit_req_dry_run on;` |
| Реальный IP за LB | `set_real_ip_from &lt;свои прокси&gt;; real_ip_header X-Forwarded-For; real_ip_recursive on;` |
| Против slowloris | `client_header_timeout 10s; client_body_timeout 10s;` |
| Современный TLS | `ssl_protocols TLSv1.2 TLSv1.3;` + ECDHE/AEAD, генератор Mozilla |
| WAF без риска | CRS в `DetectionOnly`, разбор логов, исключения, потом `On` |
| Аудит TLS | `testssl.sh --ip 127.0.0.1 --add-ca ca.crt -p -S -h -U https://host:port` |
| Шифры через nmap | `nmap -p 443 --script ssl-enum-ciphers host` |
| Открытые порты | `nmap -sV -p- host` (только свои!) |

---

## 🧠 Что запомнить

1. OWASP Top 10:2025 — актуальная редакция; для каждой категории отвечай «что может инфра, что только код».
2. WAF — компенсирующий контроль: уменьшает вероятность, причину устраняет код.
3. Заголовки — с `always`; свой `add_header` в location отменяет родительские (или `add_header_inherit merge`).
4. HSTS нельзя быстро отменить: короткий `max-age` → проверка поддоменов → год; preload — осознанно.
5. CSP внедряют через Report-Only, иначе его отключат после первой поломки фронта.
6. TLS: только 1.2/1.3, ECDHE + AEAD; частая авария — не шифр, а истёкший сертификат.
7. `limit_req` по умолчанию отвечает `503`: нужен `limit_req_status 429`; включай через `dry_run`.
8. Реальный IP доверяем только своим прокси, иначе лимиты и allowlist обходятся одним заголовком.
9. DDoS L3/4 гасит провайдер/CDN, L7 — edge, WAF, кэш и лимиты; origin IP не светить.
10. Периметр проверяют снаружи (testssl.sh, curl, nmap) — и только свои хосты.

➡️ Дальше: [04_vuln_management.md](/security/04-vuln-management) · задачи: 03_web_edge_security_tasks.md


---

### Блок A. Теория


**A1.** Что такое OWASP Top 10 и какая редакция актуальна? Что изменилось по сравнению с 2021?

<details><summary>Ответ</summary>

Рейтинг самых критичных классов рисков веб-приложений от OWASP. Актуальна редакция 2025
(финал — январь 2026). Изменения: Security Misconfiguration поднялась на 2-е место; «Vulnerable
and Outdated Components» расширили до Software Supply Chain Failures (A03); SSRF влили в Broken
Access Control; новая A10 Mishandling of Exceptional Conditions; A07 и A09 переименованы.

</details>

**A2.** ⭐ Для A05 Injection, A01 Broken Access Control (SSRF) и A02 Security Misconfiguration
назови, что может инфраструктура, а что может только код.

<details><summary>Ответ</summary>

Injection: инфра — WAF+CRS как компенсация, least privilege учётки БД; код —
параметризованные запросы. SSRF (в A01): инфра — IMDSv2 с hop limit 1, egress-правила/
NetworkPolicy, запрет 169.254.169.254; код — валидация и allowlist URL. Misconfig: инфра —
заголовки, `server_tokens off`, нет листинга каталогов и дефолтных паролей, закрытые бакеты;
код — выключенный debug, безопасные дефолты фреймворка.

</details>

**A3.** Почему WAF называют компенсирующим контролем?

<details><summary>Ответ</summary>

Он не устраняет уязвимость в коде, а снижает вероятность её эксплуатации известными
способами; правила можно обойти. Держат его, пока чинят код, и как дополнительный слой.

</details>

**A4.** Что защищает каждый заголовок: HSTS, CSP, X-Content-Type-Options, Referrer-Policy,
Permissions-Policy? Почему X-XSS-Protection не нужен?

<details><summary>Ответ</summary>

HSTS — только HTTPS, нет SSL stripping; CSP — откуда грузить ресурсы (XSS) и кто может
встраивать страницу (`frame-ancestors`, clickjacking); nosniff — браузер не угадывает тип
файла; Referrer-Policy — не утекают полные URL на чужие сайты; Permissions-Policy — доступ к
камере, геолокации и т.п. X-XSS-Protection устарел, фильтр убран из браузеров и сам создавал уязвимости.

</details>

**A5.** ⭐ Что делает параметр `always` у `add_header`? Опиши ловушку наследования `add_header`
и два способа её обойти.

<details><summary>Ответ</summary>

`always` добавляет заголовок к любым ответам, включая 4xx/5xx (без него — только к

</details>

**A6.** Почему HSTS включают поэтапно? Чем опасны `includeSubDomains` и `preload`?

<details><summary>Ответ</summary>

Браузер запоминает политику на `max-age` — ошибку не откатить быстро. `includeSubDomains`
ломает поддомены без HTTPS; `preload` вшивает домен в браузеры, удаление занимает месяцы.
Поэтому: короткий `max-age` → проверка поддоменов → год → preload осознанно.

</details>

**A7.** Как внедрять CSP, чтобы не сломать фронтенд?

<details><summary>Ответ</summary>

Сначала `Content-Security-Policy-Report-Only` с `report-uri`/`report-to`, собрать
нарушения 1–2 недели, поправить фронт/политику, потом enforce.

</details>

**A8.** Какие версии TLS и какие шифры оставить? Почему `ssl_ciphers` не влияет на TLS 1.3?

<details><summary>Ответ</summary>

TLS 1.2 и 1.3; для 1.2 — ECDHE с AEAD (AES-GCM, ChaCha20-Poly1305), без CBC/RC4;
`ssl_prefer_server_ciphers off`, когда все шифры сильные. У TLS 1.3 свой фиксированный набор
сильных шифров, `ssl_ciphers` задаёт список только для TLS ≤ 1.2.

</details>

**A9.** Нужен ли `ssl_stapling on` для сертификатов Let's Encrypt в 2026 году? Почему?

<details><summary>Ответ</summary>

Нет: Let's Encrypt выключил OCSP-респондеры 6 августа 2025 и перешёл на CRL. В его
сертификатах нет OCSP URL — stapling ничего не даст, будут только предупреждения.

</details>

**A10.** ⭐ Какой код ответа у `limit_req` по умолчанию и чем это плохо? Как исправить?

<details><summary>Ответ</summary>

`503`. Клиенты ретраят, мониторинг и SLO считают это отказом сервера, дежурный ищет
несуществующую аварию. Исправление — `limit_req_status 429;` (и `limit_conn_status 429;`).

</details>

**A11.** Чем отличаются `burst=20`, `burst=20 nodelay` и `burst=20 delay=8`?

<details><summary>Ответ</summary>

`burst=20` — лишние запросы ставятся в очередь и задерживаются до темпа `rate`;
`nodelay` — до 20 лишних обслуживаются сразу, сверх — 429; `delay=8` — первые 8 лишних сразу,
остальные до 20 с задержкой, сверх — 429.

</details>

**A12.** ⭐ Как правильно получить реальный IP клиента за балансировщиком и в чём ловушка?

<details><summary>Ответ</summary>

Модуль realip: `set_real_ip_from &lt;адреса своих LB/CDN&gt;`, `real_ip_header X-Forwarded-For`,
`real_ip_recursive on`. Ловушка — доверять всем (`0.0.0.0/0`): любой клиент подделает заголовок,
обойдёт лимиты и allowlist, испортит логи.

</details>

**A13.** Как работает anomaly scoring в OWASP CRS? Что такое paranoia level?

<details><summary>Ответ</summary>

Правила CRS добавляют баллы (critical = 5), блок — если сумма за запрос достигла порога
(`ANOMALY_INBOUND`, по умолчанию 5). Paranoia level 1–4 определяет, сколько правил включено:
выше уровень — больше защиты и больше ложных срабатываний.

</details>

**A14.** Как безопасно внедрить WAF на работающий сервис?

<details><summary>Ответ</summary>

DetectionOnly на реальном трафике → разбор срабатываний → точечные исключения →
`On` с высоким порогом → снижение порога → PL2 для чувствительных путей. Всё в git, как gate в CI.

</details>

**A15.** ⭐ Чем DDoS L3/4 отличается от L7? Кто гасит каждый вид?

<details><summary>Ответ</summary>

L3/4 забивает канал или таблицы соединений (UDP-флуд, amplification, SYN flood) — гасят
провайдер, anycast, scrubbing, CDN; на хосте помогает немногое (`tcp_syncookies`). L7 исчерпывает
ресурсы приложения запросами, похожими на легитимные (HTTP-флуд, slowloris, Rapid Reset) — гасят
edge (лимиты, таймауты, кэш), WAF/анти-бот, CDN, автоскейлинг.

</details>

**A16.** Какими инструментами проверить периметр снаружи и чем SSL Labs отличается от testssl.sh?

<details><summary>Ответ</summary>

testssl.sh (TLS локально, в т.ч. внутренние хосты), SSL Labs (только публичные хосты,
оценка A–F), curl (заголовки, редиректы, коды), nmap (порты, версии, `ssl-enum-ciphers`).
SSL Labs — внешний сервис для публичных адресов, testssl.sh — локальный инструмент, работает везде.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  server {
```text
<details><summary>Ответ</summary>

⚠️ В `/api/` свой `add_header` — HSTS и nosniff там пропали. Повторить сниппет в
location или `add_header_inherit merge;`.

</details>

```text:no-line-numbers
         add_header Strict-Transport-Security "max-age=31536000" always;
```text
```text:no-line-numbers
         add_header X-Content-Type-Options nosniff always;
```text
```text:no-line-numbers
         location /api/ {
```text
```text:no-line-numbers
             add_header Cache-Control "no-store";
```text
```text:no-line-numbers
             proxy_pass http://app:8080;
```text
```text:no-line-numbers
         }
```text
```text:no-line-numbers
     }
```text
```text:no-line-numbers
B2.  limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
```text
<details><summary>Ответ</summary>

⚠️ Лимит отвечает `503`: графики «5xx выросли» — на самом деле это отказы лимита.
Добавить `limit_req_status 429;`, разделить метрики 429 и 5xx.

</details>

```text:no-line-numbers
     location /api/ { limit_req zone=api burst=20 nodelay; proxy_pass http://app:8080; }
```text
```text:no-line-numbers
     # Grafana: «доля 5xx на edge выросла в 5 раз»
```text
```text:no-line-numbers
B3.  set_real_ip_from 0.0.0.0/0;
```text
<details><summary>Ответ</summary>

⚠️ Доверие всем прокси: атакующий шлёт `X-Forwarded-For: 10.10.0.5` и проходит
allowlist `/admin/`. Указать только адреса своих балансировщиков.

</details>

```text:no-line-numbers
     real_ip_header X-Forwarded-For;
```text
```text:no-line-numbers
     location /admin/ { allow 10.10.0.0/16; deny all; proxy_pass http://app:8080; }
```text
```text:no-line-numbers
B4.  add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
```text
<details><summary>Ответ</summary>

⚠️ `includeSubDomains` сломает HTTP-вики, а `preload` вшьёт это в браузеры на месяцы.
Сначала перевести все поддомены на HTTPS, короткий `max-age`, preload — только осознанно.

</details>

```text:no-line-numbers
     # домен компании; на old.company.kz — внутренняя вики только по HTTP
```text
```text:no-line-numbers
B5.  add_header Content-Security-Policy "default-src 'self'" always;
```text
<details><summary>Ответ</summary>

⚠️ Инлайн-скрипты и внешний CDN заблокированы — фронт сломан в пятницу. Report-Only,
разбор, политика с нужными источниками (nonce/hash для инлайна), потом enforce.

</details>

```text:no-line-numbers
     # фронтенд использует инлайн-скрипты и аналитику с внешнего CDN; включили в пятницу
```text
```text:no-line-numbers
B6.  ssl_protocols TLSv1 TLSv1.1 TLSv1.2 TLSv1.3;
```text
<details><summary>Ответ</summary>

⚠️ TLS 1.0/1.1 устарели (RFC 8996); `HIGH` включает CBC-шифры и шифры без forward
secrecy. `ssl_protocols TLSv1.2 TLSv1.3` и явный список ECDHE+AEAD.

</details>

```text:no-line-numbers
     ssl_ciphers HIGH:!aNULL:!MD5;
```text
```text:no-line-numbers
B7.  add_header Strict-Transport-Security "max-age=31536000";      # в server на порту 80
```text
<details><summary>Ответ</summary>

⚠️ HSTS по HTTP браузер игнорирует. На 80 — `return 301 https://…`, HSTS — на HTTPS-ответе.

</details>

```text:no-line-numbers
B8.  # WAF на проде включён сразу так:
```text
<details><summary>Ответ</summary>

⚠️ Сразу блокировка и максимальная паранойя: лавина ложных срабатываний, WAF выключат.
DetectionOnly, PL1, исключения, потом On.

</details>

```text:no-line-numbers
     MODSEC_RULE_ENGINE=On  BLOCKING_PARANOIA=4
```text
```text:no-line-numbers
B9.  limit_req_zone $binary_remote_addr zone=all:10m rate=1r/s;
```text
<details><summary>Ответ</summary>

⚠️ 300 человек за одним IP делят 1 запрос в секунду — сервис недоступен. Лимиты по
реальному профилю (access-логи), по API-ключу/аккаунту вместо IP, запас 2–3×, `dry_run`.

</details>

```text:no-line-numbers
     # B2B-сервис, клиенты — офисы по 300 человек за одним NAT
```text
```text:no-line-numbers
B10.  # Сайт за CDN с защитой от DDoS. DNS старого поддомена direct.company.kz указывает
```text
<details><summary>Ответ</summary>

⚠️ Origin доступен напрямую — DDoS пойдёт мимо CDN. Убрать DNS-запись, пропускать
на origin только адреса CDN, при необходимости сменить IP origin.

</details>

```text:no-line-numbers
     # прямо на origin, security group origin открыта 0.0.0.0/0 на 443.
```text
```text:no-line-numbers
B11.  error_page 500 502 503 504 /50x.html;
```text
<details><summary>Ответ</summary>

⚠️ Без `proxy_intercept_errors on` `error_page` не перехватывает ошибки бэкенда —
клиент видит стек-трейс (A10, утечка информации). Включить и отдавать свою страницу.

</details>

```text:no-line-numbers
     # proxy_intercept_errors не включён; приложение на ошибке отдаёт HTML со стек-трейсом
```text
```text:no-line-numbers
B12.  ssl_stapling on;
```text
<details><summary>Ответ</summary>

⚠️ У Let's Encrypt с августа 2025 нет OCSP — stapling бесполезен и засоряет лог.
Убрать для LE-сертификатов.

</details>

```text:no-line-numbers
     ssl_stapling_verify on;
```text
```text:no-line-numbers
     # сертификат от Let's Encrypt, в error.log: "no OCSP responder URL in the certificate"
```text
---

### Блок C. Практика


### C1. 🔑 Заголовки безопасности
Создай сниппет `security-headers.conf` (смонтируй в контейнер nginx), подключи в `server`
на 443. Проверь `curl -skI`. Добавь в `location /` свой `add_header X-Test 1` — убедись, что
заголовки безопасности пропали, и почини двумя способами: `include` в location и
`add_header_inherit merge;` (nginx 1.30 это умеет).

### C2. 🔑 Rate limit с 429 и dry run
Включи `limit_req` на `location /` сначала с `limit_req_dry_run on` и посмотри записи в
error log при нагрузке, потом по-настоящему. Проверь распределение кодов циклом из 40 запросов
до и после `limit_req_status 429`. Добавь отдельный лимит `5r/m` на `/login`.

### C3. Ловушка реального IP
Поставь `set_real_ip_from 0.0.0.0/0; real_ip_header X-Forwarded-For;` и докажи, что лимит
обходится: запросы с разными `X-Forwarded-For` не получают 429. Исправь на подсеть docker-сети
(или вообще убери realip, т.к. перед nginx на стенде прокси нет) и повтори.

### C4. 🔑 testssl.sh до и после
Прогони testssl.sh по стартовому конфигу, сохрани `--jsonfile` и список предупреждений.
Примени TLS-часть итогового конфига (раздел 7), прогони снова и сравни: протоколы, шифры,
HSTS, `Server`, серверные предпочтения.

### C5. 🔑 WAF: DetectionOnly → On
Подними `waf`. Отправь 3 атаки: SQLi (`?id=1' OR '1'='1`), path traversal (`?file=../../etc/passwd`),
RCE-подобную (`?cmd=;cat /etc/passwd`). В DetectionOnly — какие коды и какие `ruleId` в логе?
Переключи на `On`, повтори. Потом отправь легитимный запрос, который выглядит подозрительно
(например, поиск текста `select * from` в параметре `q`), и напиши rule exclusion для него.

### C6. CSP Report-Only
Добавь `Content-Security-Policy-Report-Only` со строгой политикой и `report-uri /csp-report`.
Открой страницу в браузере с DevTools — какие нарушения видно в консоли? Чем Report-Only
отличается от enforce при реальной атаке?

### C7. Редирект, версия и страницы ошибок
Сделай `301` с 80 на 443, `server_tokens off`, свои error pages с `proxy_intercept_errors on`.
Останови `app` (`docker compose stop app`) и проверь, что клиент видит твою страницу 502,
а не дефолтную с версией.

### C8. nmap своего стенда
`nmap -sV -p- 127.0.0.1` и `nmap -p 8443 --script ssl-enum-ciphers 127.0.0.1`. Что видно из
того, что не должно быть видно? Сравни с тем, что `ss -tulpn` показывает на хосте. Проверь с
`sec01` (`nmap -sV &lt;IP хоста в 192.168.56.0/24&gt;`), видны ли порты edge.

### C9. Матрица OWASP для своего сервиса
Для своего проекта (linkd или любого) заполни таблицу 10 категорий 2025: что уже закрыто
инфраструктурой, что закрывает код, что не закрыто никем, кто владелец.

---

### Блок D. Инциденты


**D1.** После выката нового конфига nginx мобильное приложение массово получает ошибки,
а в Grafana растёт доля 503. Бэкенды здоровы, CPU низкий.

<details><summary>Ответ</summary>

Новый `limit_req` без `limit_req_status` режет мобильные клиенты (много запросов с одного
NAT/IP оператора) и отвечает 503. Проверить error log (`limiting requests`), откатить или
перевести в `dry_run`, поставить `429`, пересчитать лимит по access-логам.

</details>

**D2.** Логин-страницу перебирают паролями с тысяч разных IP по 2–3 попытки с каждого.
`limit_req` по IP не срабатывает.

<details><summary>Ответ</summary>

Распределённый перебор (credential stuffing): лимит по IP бессилен. Лимит по логину/
аккаунту в приложении, CAPTCHA/анти-бот (Smart Web Security, Cloudflare), MFA, блок-листы
известных прокси, алерт на долю неуспешных входов.

</details>

**D3.** Включили WAF в режиме `On`, через час поддержка завалена жалобами: не сохраняются
статьи в CMS, где пользователи пишут про SQL.

<details><summary>Ответ</summary>

Ложные срабатывания SQLi-правил на тексте статей. Вернуть DetectionOnly (или поднять
порог) для этого пути, написать исключение по конкретному правилу и параметру (`body`/`content`
редактора), вернуть `On`. Урок — сразу `On` без периода наблюдения.

</details>

**D4.** Сайт за CDN лежит под DDoS, хотя CDN показывает нормальный трафик.

<details><summary>Ответ</summary>

Атакуют origin напрямую, мимо CDN: IP origin известен (старая DNS-запись, история DNS,
заголовки в письмах). Закрыть origin для всех, кроме адресов CDN (SG/firewall), сменить IP,
убрать прямые DNS-записи.

</details>

**D5.** После включения HSTS с `includeSubDomains` перестала открываться внутренняя система
`jira.company.kz`, которая работает по HTTP.

<details><summary>Ответ</summary>

HSTS с `includeSubDomains` заставляет браузер ходить на все поддомены только по HTTPS.
Срочно: выпустить сертификат и включить HTTPS на `jira`; снижение `max-age` не поможет браузерам,
которые политику уже запомнили. На будущее — инвентаризация поддоменов до `includeSubDomains`.

</details>

**D6.** Пентестер нашёл, что приложение по параметру `url=` ходит на `http://169.254.169.254/`
и возвращает содержимое. Что делаешь как девопс сегодня, пока разработчики чинят код?

<details><summary>Ответ</summary>

Компенсирующие меры: IMDSv2 обязательный с hop limit 1 (`aws ec2 modify-instance-metadata-options
--http-tokens required --http-put-response-hop-limit 1`), egress-правила/NetworkPolicy без доступа
к 169.254.169.254 и внутренним сетям, WAF-правило на параметр `url`, минимальные права роли ВМ,
проверить в аудите облака, не использовались ли креды роли вне ВМ, при сомнении — ротировать.

</details>

**D7.** Сканер безопасности у клиента выдал «сервер раскрывает версию и поддерживает TLS 1.0».
У тебя TLS 1.0 выключен в nginx, но отчёт настаивает.

<details><summary>Ответ</summary>

Сканер мог проверять другой адрес (origin мимо балансировщика, старый IP, другой порт)
или TLS терминируется на балансировщике/CDN со своими настройками. Проверить `testssl.sh` по
тому же адресу, что и сканер, и конфиг TLS на балансировщике. Версию — `server_tokens off` и на LB.

</details>

**D8.** Мониторинг показывает всплеск 404 с одного диапазона IP на пути вроде `/.env`,
`/wp-admin`, `/.git/config`.

<details><summary>Ответ</summary>

Автоматическое сканирование уязвимостей (фоновый шум интернета). Убедиться, что
`/.env`, `/.git` не отдаются (правило `location ~ /\.(?!well-known) { deny all; }`), WAF/лимиты
режут сканеры, при массовости — блок диапазона на edge/CDN. Проверить по логам, не было ли 200 на эти пути.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Что такое OWASP Top 10? Что девопс может сделать против injection и SSRF?

<details><summary>Ответ</summary>

Рейтинг рисков веб-приложений, актуальный — 2025. Против injection: WAF+CRS как компенсация,
   least privilege учётки БД, но фикс — параметризованные запросы. Против SSRF: IMDSv2, egress-
   политики, запрет metadata, минимальные права роли; фикс — allowlist URL в коде.

</details>

**2.** Какие заголовки безопасности ты настраиваешь в nginx и зачем?

<details><summary>Ответ</summary>

HSTS, CSP (с `frame-ancestors`), X-Content-Type-Options, Referrer-Policy, Permissions-Policy,
   иногда X-Frame-Options; `server_tokens off`; всё с `always` и с учётом наследования `add_header`.

</details>

**3.** Что такое HSTS и в чём его опасность?

<details><summary>Ответ</summary>

Заставляет браузер ходить только по HTTPS на `max-age`. Опасен тем, что ошибку не откатить:
   `includeSubDomains` ломает HTTP-поддомены, `preload` вшивает домен в браузеры надолго.

</details>

**4.** Как настроить TLS правильно и как это проверить?

<details><summary>Ответ</summary>

TLS 1.2/1.3, ECDHE+AEAD, полная цепочка, профиль Mozilla intermediate, автообновление
   сертификатов и мониторинг срока; проверка — testssl.sh, SSL Labs, `openssl s_client`.

</details>

**5.** Как сделать rate limiting в nginx? Какие подводные камни?

<details><summary>Ответ</summary>

`limit_req_zone` + `limit_req` с `burst`/`nodelay`, `limit_conn`; камни: 503 по умолчанию
   (нужен `limit_req_status 429`), реальный IP за LB и подделка XFF, NAT, лимиты на глаз —
   включать через `dry_run`.

</details>

**6.** Что такое WAF? Как его внедрять?

<details><summary>Ответ</summary>

Фильтр HTTP по правилам (ModSecurity/Coraza + OWASP CRS или облачный). Внедрение: DetectionOnly →
   разбор → исключения → On с высоким порогом → снижение; WAF — компенсирующий контроль.

</details>

**7.** Чем DDoS L3/4 отличается от L7 и как защищаться?

<details><summary>Ответ</summary>

L3/4 забивает канал — защита у провайдера/CDN, скрытый origin; L7 — лимиты, таймауты, кэш,
   WAF/анти-бот, автоскейлинг; runbook и контакты провайдера заранее.

</details>

**8.** Как получить реальный IP клиента за балансировщиком?

<details><summary>Ответ</summary>

realip: `set_real_ip_from` только адреса своих прокси, `real_ip_header X-Forwarded-For`,
   `real_ip_recursive on`; никогда `0.0.0.0/0`.

</details>

**9.** Как ты проверяешь безопасность периметра?

<details><summary>Ответ</summary>

Снаружи: nmap (порты, версии), testssl.sh/SSL Labs (TLS), curl (заголовки, редиректы), регулярно
   и по расписанию; внутри — ревью конфигов в git и мониторинг 4xx/5xx/429. Только свои хосты.

</details>

**10.** Что такое CSP и почему его внедряют через Report-Only?

<details><summary>Ответ</summary>

Политика источников контента: защищает от XSS и clickjacking. Строгая CSP ломает фронтенд,
    поэтому сначала Report-Only собирает нарушения, после правок — enforce.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Для каждой категории OWASP Top 10:2025 называю вклад инфраструктуры и кода
- [ ] ⭐ Заголовки безопасности с `always` и без ловушки наследования `add_header`
- [ ] Включаю HSTS поэтапно и CSP через Report-Only
- [ ] TLS только 1.2/1.3 с ECDHE+AEAD, проверено testssl.sh до/после
- [ ] ⭐ Rate limit отвечает `429`, новый лимит включаю через `dry_run`
- [ ] Реальный IP беру только от доверенных прокси, ловушку XFF воспроизвёл
- [ ] WAF + CRS прошёл путь DetectionOnly → исключение → On
- [ ] Объясняю DDoS L3/4 vs L7 и кто что гасит
- [ ] Сканирую только свои хосты: nmap, testssl.sh, curl
