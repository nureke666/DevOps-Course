---
title: "12. Nginx"
description: "Веб-сервер, reverse proxy, балансировщик: конфиг, location, 502/504/413, rate limiting — конспект и задачи"
---

# 12. Nginx — веб-сервер, reverse proxy, балансировщик

> Роадмап → 2.5 Сети → Балансировщики: **Nginx**.
> **После темы ты умеешь:** написать конфиг с нуля, проксировать на бэкенды, балансировать,
> терминировать TLS, читать логи и чинить 502/504.
> ⭐ Nginx ты встретишь и как веб-сервер, и как Ingress-контроллер в Kubernetes.

---

## 🗺️ Схема: место nginx в инфраструктуре

```text:no-line-numbers
                       ┌──────────────────────────────┐
   Интернет ──443──►   │            NGINX             │
                       │  • терминация TLS            │
                       │  • отдача статики            │
                       │  • маршрутизация по пути     │──► app-1:8080
                       │  • балансировка upstream     │──► app-2:8080
                       │  • кеш, gzip, rate limit     │──► app-3:8080
                       │  • X-Forwarded-* заголовки   │
                       └──────────────────────────────┘
                                     │
                              access.log / error.log
                          (главный источник правды об инцидентах)
```

---

## 1. Структура конфигурации

```text:no-line-numbers
/etc/nginx/
├── nginx.conf                 ← главный: worker'ы, http-блок, include
├── conf.d/*.conf              ← доп. конфиги (RHEL-стиль)
├── sites-available/           ← конфиги сайтов (Debian-стиль)
└── sites-enabled/             ← симлинки на активные
```

```nginx
user www-data;
worker_processes auto;              # ⭐ по числу ядер
events { worker_connections 1024; } # максимум соединений на воркер

http {
    include       /etc/nginx/mime.types;
    sendfile      on;
    keepalive_timeout 65;
    client_max_body_size 10m;       # ⭐ иначе 413 на загрузке файлов

    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" "$http_user_agent" '
                    'rt=$request_time uct=$upstream_connect_time urt=$upstream_response_time';
    #                                          ⭐ времена бэкенда — must have для разбора инцидентов
    access_log /var/log/nginx/access.log main;
    error_log  /var/log/nginx/error.log warn;

    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
```

**Иерархия контекстов:** `http` → `server` → `location`. Директивы наследуются вниз
и переопределяются на более глубоком уровне.

---

## 2. Минимальный рабочий конфиг с проксированием

```nginx
upstream backend {
    least_conn;                             # алгоритм балансировки
    server 10.0.0.11:8080 max_fails=3 fail_timeout=30s;
    server 10.0.0.12:8080 max_fails=3 fail_timeout=30s;
    server 10.0.0.13:8080 backup;           # резервный
    keepalive 32;                           # ⭐ пул соединений к бэкендам
}

server {
    listen 80;
    server_name example.com www.example.com;
    return 301 https://$host$request_uri;   # ⭐ весь http → https
}

server {
    listen 443 ssl http2;
    server_name example.com;

    ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;  # ⭐ fullchain!
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:SSL:10m;

    root /var/www/example;

    location /static/ {
        alias /var/www/example/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";                # ⭐ для keepalive к upstream
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;    # ⭐ иначе редирект-петля
        proxy_connect_timeout 5s;
        proxy_send_timeout   60s;
        proxy_read_timeout   60s;                      # ⭐ отсюда берутся 504
    }

    location /health { access_log off; return 200 "ok\n"; }
}
```

---

## 3. location — порядок выбора (частый вопрос)

```nginx
location = /exact      { }   # ① точное совпадение — наивысший приоритет
location ^~ /static/   { }   # ② префикс с запретом проверки regex
location ~ \.php$      { }   # ③ regex с учётом регистра (в порядке описания)
location ~* \.(jpg|png)$ { } # ③ regex без учёта регистра
location /prefix       { }   # ④ обычный префикс (самый длинный выигрывает)
location /             { }   # ⑤ fallback
```

⚠️ **`proxy_pass` со слешем и без — разное поведение:**

```nginx
location /api/ { proxy_pass http://backend;  }   # запрос /api/users → бэкенд получит /api/users
location /api/ { proxy_pass http://backend/; }   # запрос /api/users → бэкенд получит /users
```

Это причина половины «404 от бэкенда после настройки прокси».

---

## 4. Балансировка

| Алгоритм | Директива | Когда |
|----------|-----------|-------|
| Round-robin | (по умолчанию) | Одинаковые бэкенды |
| Взвешенный | `server ... weight=3;` | Разные по мощности |
| Least connections | `least_conn;` | Долгие запросы разной длительности |
| IP hash | `ip_hash;` | ⭐ Sticky-сессии по IP |
| Hash по ключу | `hash $request_uri consistent;` | Кеш-серверы, шардирование |

```nginx
upstream backend {
    server app1:8080 weight=3;
    server app2:8080;
    server app3:8080 max_fails=2 fail_timeout=20s;   # пассивный health-check
    server app4:8080 down;                            # выведен из ротации
}
```

⚠️ В открытой версии nginx **пассивные** health-check: бэкенд помечается «плохим»
после `max_fails` ошибок за `fail_timeout`. Активные проверки (`health_check`) —
только в NGINX Plus; в open source их заменяют HAProxy или внешний мониторинг.

---

## 5. Эксплуатация: команды, которые нужны каждый день

```bash
sudo nginx -t                    # ⭐ ВСЕГДА перед перезагрузкой
sudo nginx -T                    # полный итоговый конфиг (со всеми include)
sudo systemctl reload nginx      # ⭐ без разрыва соединений
sudo systemctl restart nginx     # с разрывом — только когда reload не хватает
nginx -V 2>&1 | tr ' ' '\n' | grep -- --with    # какие модули собраны

tail -f /var/log/nginx/error.log
tail -f /var/log/nginx/access.log
```

**Анализ access.log** (связка с Linux/03, Text-Fu):

```bash
awk '{print $9}' access.log | sort | uniq -c | sort -rn          # коды ответа
awk '$9 ~ /^5/ {print $7}' access.log | sort | uniq -c | sort -rn | head   # какие URL дают 5xx
awk '{print $1}' access.log | sort | uniq -c | sort -rn | head            # топ IP
awk '{print $NF}' access.log | sort -rn | head                            # самые долгие (при rt= в конце)
```

---

## 6. Разбор 502 / 504 / 403 / 413

| Код | В error.log | Причина и что делать |
|-----|-------------|----------------------|
| **502** | `connect() failed (111: Connection refused) while connecting to upstream` | Бэкенд не слушает: проверь `ss -tlnp` на бэкенде, адрес в `proxy_pass` |
| **502** | `upstream prematurely closed connection` | Бэкенд упал/перезапустился в процессе ответа |
| **502** | `no live upstreams while connecting to upstream` | Все бэкенды помечены «плохими» из-за `max_fails` |
| **504** | `upstream timed out (110) while reading response header` | Бэкенд медленный — увеличивать `proxy_read_timeout` лишь как временную меру |
| **403** | `directory index of ... is forbidden` / `Permission denied` | Права на файлы/каталоги, отсутствие `index`, SELinux |
| **413** | `client intended to send too large body` | `client_max_body_size` |
| **400** | `client sent too long header line` | `large_client_header_buffers` |
| **499** | — | ⭐ Клиент сам закрыл соединение, не дождавшись ответа (почти всегда — медленный бэкенд) |

```bash
# Проверить бэкенд напрямую, минуя nginx
curl -s -o /dev/null -w '%{http_code} %{time_total}\n' http://10.0.0.11:8080/health
```

---

## 7. Полезные возможности, о которых спрашивают

```nginx
# Сжатие
gzip on;
gzip_types text/plain text/css application/json application/javascript;
gzip_min_length 1024;

# Ограничение частоты запросов
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
location /api/ {
    limit_req zone=api burst=20 nodelay;
    limit_req_status 429;                  # по умолчанию nginx отдаёт 503 — клиенты примут это за падение
    proxy_pass http://backend;
}

# Ограничение числа соединений
limit_conn_zone $binary_remote_addr zone=perip:10m;
limit_conn perip 20;

# Кеширование ответов бэкенда
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=app:100m max_size=1g inactive=60m;
location / {
    proxy_cache app;
    proxy_cache_valid 200 10m;
    proxy_cache_use_stale error timeout updating;   # ⭐ отдавать устаревшее, если бэкенд лёг
    add_header X-Cache-Status $upstream_cache_status;
    proxy_pass http://backend;
}

# Реальный IP за внешним балансировщиком/CDN
set_real_ip_from 10.0.0.0/8;
real_ip_header X-Forwarded-For;
real_ip_recursive on;

# WebSocket
location /ws/ {
    proxy_pass http://backend;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;
}

# Базовые заголовки безопасности
add_header X-Content-Type-Options nosniff always;
add_header X-Frame-Options SAMEORIGIN always;
add_header Strict-Transport-Security "max-age=31536000" always;
server_tokens off;                                  # не светить версию
```

⚠️ `add_header` **не наследуется**, если в дочернем контексте есть свой `add_header` —
частая причина «заголовок пропал в одном location».

---

## 8. Nginx в Kubernetes

ingress-nginx — это тот же nginx, конфиг которого генерируется из Ingress-ресурсов.
Что стоит знать: аннотации (`nginx.ingress.kubernetes.io/proxy-body-size`,
`proxy-read-timeout`, `rewrite-target`, `ssl-redirect`) превращаются ровно в те директивы,
что выше, а логи контроллера читаются так же (см. Kubernetes/12, Ingress).

---

## 💼 Как это в DevOps

- Nginx — точка, где сходятся TLS, маршрутизация, лимиты и логи: он первым видит инцидент.
- `nginx -t && systemctl reload nginx` — деплой конфига без единой ошибки 5xx.
- `$upstream_response_time` в логах отвечает на вопрос «тормозит nginx или приложение».
- Кеш и `proxy_cache_use_stale` позволяют пережить падение бэкенда без ошибок у пользователей.
- Ingress в Kubernetes — это nginx, и все навыки отсюда переносятся туда напрямую.

---

## 🧪 Мини-лаба

```bash
vagrant ssh web
sudo apt install -y nginx curl

# 1. Базовые проверки
nginx -v; sudo nginx -t; systemctl status nginx --no-pager | head -3
curl -sI http://localhost | head -3

# 2. Статика и виртуальные хосты
sudo mkdir -p /var/www/site-a /var/www/site-b
echo "<h1>SITE A</h1>" | sudo tee /var/www/site-a/index.html >/dev/null
echo "<h1>SITE B</h1>" | sudo tee /var/www/site-b/index.html >/dev/null
sudo tee /etc/nginx/sites-available/lab >/dev/null <<'EOS'
server { listen 8080; server_name a.lab; root /var/www/site-a; }
server { listen 8080; server_name b.lab; root /var/www/site-b; }
EOS
sudo ln -sf /etc/nginx/sites-available/lab /etc/nginx/sites-enabled/lab
sudo nginx -t && sudo systemctl reload nginx
curl -s -H 'Host: a.lab' http://localhost:8080/
curl -s -H 'Host: b.lab' http://localhost:8080/
curl -s http://localhost:8080/                # без Host → default_server

# 3. Два бэкенда и балансировка
for p in 9001 9002; do
  (while true; do printf "HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nport$p\n" | nc -l -p $p -q0 >/dev/null 2>&1; done) &
done
sudo tee /etc/nginx/sites-available/lb >/dev/null <<'EOS'
upstream lab_backend {
    server 127.0.0.1:9001;
    server 127.0.0.1:9002;
}
server {
    listen 8090;
    location / {
        proxy_pass http://lab_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 2s;
        proxy_read_timeout 3s;
    }
    location /health { access_log off; return 200 "ok\n"; }
}
EOS
sudo ln -sf /etc/nginx/sites-available/lb /etc/nginx/sites-enabled/lb
sudo nginx -t && sudo systemctl reload nginx
for i in $(seq 1 6); do curl -s http://localhost:8090/; done     # round-robin по очереди

# 4. 502: убиваем бэкенды
pkill -f 'nc -l -p 900'; sleep 1
curl -s -o /dev/null -w '502? %{http_code}\n' http://localhost:8090/
sudo tail -3 /var/log/nginx/error.log

# 5. 504: медленный бэкенд
(while true; do sleep 10 | nc -l -p 9001 -q0 >/dev/null 2>&1; done) &
curl -s -o /dev/null -w '504? %{http_code} за %{time_total}s\n' --max-time 15 http://localhost:8090/
sudo tail -2 /var/log/nginx/error.log
pkill -f 'nc -l -p 9001'

# 6. 413 и client_max_body_size
head -c 3M /dev/zero > /tmp/big.bin
curl -s -o /dev/null -w '%{http_code}\n' -F "file=@/tmp/big.bin" http://localhost:8090/
sudo sed -i '/^http {/a \    client_max_body_size 1m;' /etc/nginx/nginx.conf
sudo nginx -t && sudo systemctl reload nginx
curl -s -o /dev/null -w 'после лимита: %{http_code}\n' -F "file=@/tmp/big.bin" http://localhost:8090/

# 7. 403 — права на файлы
sudo chmod 000 /var/www/site-a/index.html
curl -s -o /dev/null -w '403? %{http_code}\n' -H 'Host: a.lab' http://localhost:8080/
sudo chmod 644 /var/www/site-a/index.html

# 8. Логи: времена бэкенда
sudo sed -i "s|access_log /var/log/nginx/access.log.*|access_log /var/log/nginx/access.log combined;|" /etc/nginx/nginx.conf
sudo nginx -t && sudo systemctl reload nginx
curl -s http://localhost:8090/health >/dev/null
sudo tail -2 /var/log/nginx/access.log
awk '{print $9}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head

# 9. Rate limiting
sudo tee /etc/nginx/conf.d/rl.conf >/dev/null <<'EOS'
limit_req_zone $binary_remote_addr zone=lab:10m rate=2r/s;
EOS
# ⚠️ не `return 200` — return срабатывает на фазе rewrite, раньше limit_req, и лимит не применится
sudo sed -i 's|location /health|location /limited { limit_req zone=lab burst=2 nodelay; limit_req_status 429; empty_gif; }\n    location /health|' /etc/nginx/sites-available/lb
sudo nginx -t && sudo systemctl reload nginx
for i in $(seq 1 10); do curl -s -o /dev/null -w '%{http_code} ' http://localhost:8090/limited; done; echo
# ожидаем примерно: 200 200 200 429 429 … (1 запрос + burst=2 проходят, остальные — 429)

# 10. reload без потерь
(while true; do curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8090/health; sleep 0.2; done) > /tmp/codes.txt &
sudo systemctl reload nginx; sleep 2; kill %1 2>/dev/null
sort /tmp/codes.txt | uniq -c        # только 200 — reload не рвёт соединения

# 11. Уборка
pkill -f 'nc -l -p 900'
sudo rm -f /etc/nginx/sites-enabled/{lab,lb} /etc/nginx/conf.d/rl.conf /tmp/big.bin /tmp/codes.txt
sudo nginx -t && sudo systemctl reload nginx
```

---

## 📌 Шпаргалка

| Команда / директива | Смысл |
|---------------------|-------|
| `nginx -t` | ⭐ Проверить конфиг |
| `nginx -T` | Итоговый конфиг целиком |
| `systemctl reload nginx` | Применить без разрыва соединений |
| `server_name` + `Host` | Выбор виртуального хоста |
| `location = / ^~ ~ ~* /` | Порядок приоритета |
| `proxy_pass http://up;` vs `up/;` | С путём / с заменой пути |
| `proxy_set_header X-Forwarded-*` | ⭐ Реальный IP и схема |
| `proxy_read_timeout` | Откуда берётся 504 |
| `client_max_body_size` | Откуда берётся 413 |
| `upstream` + `least_conn`/`ip_hash` | Балансировка |
| `max_fails` / `fail_timeout` | Пассивный health-check |
| `limit_req_zone` / `limit_req` | Rate limiting (по умолчанию 503; `limit_req_status 429`) |
| `proxy_cache` + `use_stale` | Кеш и выживание при падении бэкенда |
| `$upstream_response_time` | ⭐ Время бэкенда в логе |
| Код 499 | Клиент ушёл, не дождавшись |

---

## 🧠 Что запомнить

1. Контексты `http` → `server` → `location`, директивы наследуются вниз.
2. Виртуальный хост выбирается по `Host`; при отсутствии совпадения — `default_server`.
3. Порядок location: точное `=`, затем `^~`, затем regex, затем самый длинный префикс.
4. Слеш в конце `proxy_pass` меняет путь, который увидит бэкенд, — источник массовых 404.
5. `X-Forwarded-For`/`X-Forwarded-Proto` обязательны, иначе бэкенд видит IP прокси
   и уходит в редирект-петлю.
6. 502 — не достучался, 504 — не дождался, 499 — клиент ушёл сам.
7. `nginx -t` перед каждым `reload`; reload не рвёт существующие соединения.
8. В open source nginx health-check пассивный (`max_fails`), активного нет.
9. `$upstream_response_time` в логах разделяет «тормозит nginx» и «тормозит приложение».
10. `client_max_body_size`, `proxy_read_timeout`, `limit_req` — три настройки,
    о которых вспоминают уже во время инцидента.
11. ingress-nginx в Kubernetes — это тот же nginx, только конфиг генерируется автоматически.

---

## Задачи

> Стенд: nginx на `web`, бэкенды — простые HTTP-серверы на `web` и `app`.

---

### Блок A. Теория

**A1.** Опиши структуру конфига: какие контексты есть и как наследуются директивы.

<details><summary>Ответ</summary>

Главный контекст (`user`, `worker_processes`), `events`, `http` (общие настройки,
логи, include), внутри — `server` (виртуальные хосты), внутри — `location` (маршруты).
Директивы наследуются сверху вниз и переопределяются в более глубоком контексте.

</details>

**A2.** Как nginx выбирает `server`-блок для запроса? Что такое `default_server`?

<details><summary>Ответ</summary>

По паре «адрес:порт» из `listen`, затем по `Host` и `server_name` (точное совпадение,
затем маска `*.example.com`, затем regex). Если ничего не совпало — берётся `default_server`
для этого `listen` (или первый объявленный).

</details>

**A3.** Назови порядок приоритета `location` (все пять форм).

<details><summary>Ответ</summary>

① `location = /path` (точное), ② `location ^~ /prefix` (префикс без проверки regex),
③ regex `~` и `~*` в порядке объявления, ④ самый длинный обычный префикс, ⑤ `location /`.

</details>

**A4.** ⭐ Чем отличается `proxy_pass http://backend;` от `proxy_pass http://backend/;`?

<details><summary>Ответ</summary>

Без слеша путь запроса добавляется к URI бэкенда целиком (`/api/users` → `/api/users`).
Со слешем часть, совпавшая с `location`, заменяется (`/api/users` → `/users`).

</details>

**A5.** Зачем нужны `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`?

<details><summary>Ответ</summary>

При проксировании бэкенд видит адрес nginx. `X-Real-IP` и `X-Forwarded-For`
передают адрес клиента, `X-Forwarded-Proto` — исходную схему (https), чтобы приложение
строило верные ссылки и не редиректило по кругу.

</details>

**A6.** Как работает `set_real_ip_from` + `real_ip_header` и почему нельзя доверять
`X-Forwarded-For` от кого угодно?

<details><summary>Ответ</summary>

`set_real_ip_from` задаёт доверенные прокси, `real_ip_header` — заголовок,
из которого брать адрес. Без ограничения доверия любой клиент подделает `X-Forwarded-For`
и подменит свой IP в логах, обойдёт ограничения по адресу и rate limit.

</details>

**A7.** Назови алгоритмы балансировки в upstream и когда какой применять.

<details><summary>Ответ</summary>

round-robin (по умолчанию, одинаковые бэкенды), `weight` (разная мощность),
`least_conn` (запросы разной длительности), `ip_hash` (липкие сессии по IP),
`hash $ключ consistent` (шардирование, кеш-серверы).

</details>

**A8.** Как в open source nginx работает проверка живости бэкендов? Чего не хватает?

<details><summary>Ответ</summary>

Только пассивно: если запрос к бэкенду завершился ошибкой `max_fails` раз
за `fail_timeout`, бэкенд временно исключается. Активных проверок (`health_check`) в open
source нет — их дают NGINX Plus, HAProxy или внешние механизмы (например, Kubernetes probes).

</details>

**A9.** Откуда берутся коды 502, 504, 499, 413, 403? Что смотреть в каждом случае?

<details><summary>Ответ</summary>

502 — nginx не смог получить корректный ответ (бэкенд не слушает, упал, вернул мусор);
504 — истёк `proxy_read_timeout`; 499 — клиент закрыл соединение до ответа;
413 — тело больше `client_max_body_size`; 403 — нет прав на файл/каталог или явный `deny`.
Смотреть `error.log` nginx и логи/метрики бэкенда.

</details>

**A10.** Чем `reload` отличается от `restart`? Почему reload безопасен?

<details><summary>Ответ</summary>

`reload` запускает новые рабочие процессы с новым конфигом, старые дорабатывают
текущие запросы и завершаются — простоя нет. `restart` останавливает процесс целиком:
все соединения рвутся, возможны ошибки у пользователей.

</details>

**A11.** Что делает `proxy_cache_use_stale` и зачем это в проде?

<details><summary>Ответ</summary>

Позволяет отдавать устаревший кешированный ответ, если бэкенд недоступен, вернул
ошибку или обновляется. Пользователь видит контент вместо 502 — дешёвая отказоустойчивость.

</details>

**A12.** Как настроить rate limiting и какой код вернёт nginx при превышении?

<details><summary>Ответ</summary>

`limit_req_zone` в `http` (ключ, зона, rate) и `limit_req` в `location`
(`burst`, `nodelay`). При превышении — 503 по умолчанию, обычно переопределяют на 429
через `limit_req_status 429`.

</details>

**A13.** Почему `add_header` может «пропасть» в некоторых location?

<details><summary>Ответ</summary>

`add_header` не наследуется, если в дочернем контексте есть **свой** `add_header`:
тогда родительские заголовки не применяются. Решение — `always` и дублирование директив
в нужных location.

</details>

**A14.** Что нужно добавить в location для работы WebSocket?

<details><summary>Ответ</summary>

`proxy_http_version 1.1;`, `proxy_set_header Upgrade $http_upgrade;`,
`proxy_set_header Connection "upgrade";` и увеличенный `proxy_read_timeout`.

</details>

**A15.** Как ingress-nginx в Kubernetes связан с обычным nginx?

<details><summary>Ответ</summary>

ingress-nginx — контроллер, который следит за Ingress-ресурсами и генерирует из них
конфиг того же nginx, перезагружая его. Аннотации соответствуют знакомым директивам.

</details>

---

### Блок B. «Что сделает конфиг»

```nginx
B1.  location /api/ { proxy_pass http://backend; }        # запрос /api/users → ?
B2.  location /api/ { proxy_pass http://backend/; }       # запрос /api/users → ?
B3.  location = /health { return 200 "ok\n"; }
B4.  server { listen 80; return 301 https://$host$request_uri; }
B5.  upstream b { ip_hash; server a:80; server c:80; }
B6.  upstream b { server a:80 weight=3; server c:80; }
B7.  server a:80 max_fails=2 fail_timeout=10s;
B8.  proxy_read_timeout 5s;
B9.  client_max_body_size 0;
B10. limit_req zone=api burst=20 nodelay;
B11. proxy_set_header Host $host;
B12. add_header X-Cache-Status $upstream_cache_status;
```

<details><summary>Ответ</summary>

- **B1.** Бэкенд получит `/api/users`.
- **B2.** Бэкенд получит `/users`.
- **B3.** Точное совпадение `/health` — быстрый ответ без обращения к бэкенду.
- **B4.** Весь HTTP-трафик перенаправляется на HTTPS с сохранением пути.
- **B5.** Липкая привязка клиента к бэкенду по хешу IP.
- **B6.** Первый бэкенд получает втрое больше запросов.
- **B7.** После 2 ошибок за 10 секунд бэкенд исключается на 10 секунд.
- **B8.** Ответ бэкенда дольше 5 секунд → 504.
- **B9.** Снимает ограничение на размер тела запроса (осторожно: риск исчерпания диска/памяти).
- **B10.** До 20 запросов сверх лимита пропускаются без задержки, дальше — отказ.
- **B11.** Передаёт бэкенду исходный Host (иначе там будет имя upstream).
- **B12.** Добавляет заголовок со статусом кеша (HIT/MISS/STALE).

</details>

**B13.** Что произойдёт, если в двух `server`-блоках указан один и тот же `listen` и
`server_name`?

<details><summary>Ответ</summary>

Nginx выдаст предупреждение `conflicting server name` и будет использовать
первый блок; второй — проигнорирует.

</details>

**B14.** Почему запрос приходит не в тот location, если написано
`location /images { }` и `location ~ \.png$ { }`, а запрошен `/images/logo.png`?

<details><summary>Ответ</summary>

Regex-локации имеют приоритет над обычным префиксом: `/images/logo.png` попадёт
в `location ~ \.png$`. Чтобы этого не произошло, префиксную локацию объявляют как
`location ^~ /images`.

</details>

---

### Блок C. Практика

**C1. Виртуальные хосты.** Настрой три сайта на одном порту с разными `server_name`
(включая `default_server`). Проверь все варианты через `curl -H 'Host: …'`.

<details><summary>Ответ</summary>

Три `server`-блока с одним `listen 8080` и разными `server_name`,
один — с `default_server`. Проверка через `curl -H 'Host: …'` и запрос без Host.

</details>

**C2. 🔑 Reverse proxy с балансировкой.** Подними два бэкенда (на `web` и `app`),
настрой upstream с `least_conn`, `max_fails`, keepalive и полным набором `X-Forwarded-*`.
Проверь: (1) распределение запросов; (2) поведение при остановке одного бэкенда;
(3) что бэкенд видит реальный IP клиента.

<details><summary>Ответ</summary>

Конфиг — из конспекта (раздел 2). Проверка: серия запросов показывает чередование
бэкендов; после остановки одного из них запросы идут на живой (а в логе появляются ошибки
и пометка upstream); бэкенд, логирующий `X-Forwarded-For`, показывает адрес клиента,
а не nginx.

</details>

**C3. Коллекция ошибок.** Воспроизведи и зафиксируй запись в `error.log` для каждого:
502 (бэкенд выключен), 502 (все бэкенды помечены плохими), 504 (медленный бэкенд),
413 (большое тело), 403 (права на файл), 499 (клиент прервал запрос — `curl --max-time 1`).

<details><summary>Ответ</summary>

Ключевые строки error.log приведены в конспекте (раздел 6).
499 воспроизводится `curl --max-time 1` к медленному эндпоинту: в access.log код 499,
в error.log — ничего.

</details>

**C4. proxy_pass со слешем.** На одном бэкенде, логирующем путь, покажи разницу между
`proxy_pass http://b;` и `proxy_pass http://b/;` для запроса `/api/v1/users`.

<details><summary>Ответ</summary>

Достаточно бэкенда `nc -l` или `python3 -m http.server`, печатающего путь:
в первом случае придёт `/api/v1/users`, во втором — `/v1/users`.

</details>

**C5. TLS.** Подключи самоподписанный сертификат из [темы 07 (TLS)](/network/07-tls), настрой
редирект http→https, `ssl_protocols TLSv1.2 TLSv1.3` и проверь через `openssl s_client`.

<details><summary>Ответ</summary>

`listen 443 ssl;` + `ssl_certificate`/`ssl_certificate_key`, отдельный `server`
на 80 с `return 301 https://$host$request_uri;`. Проверка:
`openssl s_client -connect localhost:443 -servername web.lab.local </dev/null | grep Protocol`.

</details>

**C6. Статика и кеш.** Настрой отдачу статики с `expires` и `Cache-Control`,
покажи 200 → 304 и разницу во времени ответа. Сравни отдачу статики напрямую nginx
и через проксирование на бэкенд.

<details><summary>Ответ</summary>

`expires 30d; add_header Cache-Control "public";` — повторный запрос с ETag
даёт 304. Статика напрямую отдаётся заметно быстрее (нет обращения к бэкенду и сериализации).

</details>

**C7. Кеш ответов бэкенда.** Включи `proxy_cache`, добавь `X-Cache-Status`,
покажи MISS → HIT. Затем выключи бэкенд и покажи, что `proxy_cache_use_stale`
продолжает отдавать контент.

<details><summary>Ответ</summary>

Первый запрос — `X-Cache-Status: MISS`, повторный — `HIT`. После остановки бэкенда
с `proxy_cache_use_stale error timeout updating` статус станет `STALE`, а пользователь
получит 200 вместо 502.

</details>

**C8. Rate limiting.** Настрой лимит 2 r/s с burst, прогони 20 запросов и посчитай,
сколько вернулось 200, а сколько 429/503.

<details><summary>Ответ</summary>

При `rate=2r/s burst=2 nodelay` из 20 быстрых запросов примерно 4 получат 200,
остальные — 503 (или 429 при `limit_req_status 429`).

</details>

**C9. Логи и разбор инцидента.** Настрой `log_format` с `$request_time` и
`$upstream_response_time`. Сгенерируй смешанную нагрузку (быстрые и медленные запросы,
ошибки) и напиши скрипт-отчёт: доля 5xx, p50/p95 времени ответа, топ медленных URL.

<details><summary>Ответ</summary>

```bash
LOG=/var/log/nginx/access.log
awk '{print $9}' $LOG | sort | uniq -c | sort -rn
awk '$9 ~ /^5/' $LOG | wc -l
awk '{print $(NF-2)}' $LOG | sed 's/rt=//' | sort -n | awk '{a[NR]=$1} END{print "p50="a[int(NR*0.5)], "p95="a[int(NR*0.95)]}'
awk '{print $(NF-2), $7}' $LOG | sort -rn | head
```

</details>

**C10. Zero-downtime reload.** В цикле шли запросы и одновременно делай `reload`
с изменением конфига. Докажи, что ни один запрос не потерян.

<details><summary>Ответ</summary>

В `/tmp/codes.txt` должны быть только 200: `reload` не разрывает существующие
соединения, старые воркеры дорабатывают запросы.

</details>

**C11. WebSocket.** Подними простой ws-сервер и настрой проксирование с `Upgrade`.
Покажи, что без этих заголовков соединение не устанавливается.

<details><summary>Ответ</summary>

Без `Upgrade`/`Connection` сервер вернёт 400 или соединение закроется сразу после
ответа 200 (апгрейда не произойдёт), и клиент увидит ошибку установления WebSocket.

</details>

**C12. Безопасность.** Отключи `server_tokens`, добавь заголовки безопасности,
закрой доступ к `/admin` по IP и настрой basic-auth. Проверь каждый пункт.

<details><summary>Ответ</summary>

`server_tokens off;` убирает версию из заголовка `Server` и страниц ошибок;
`allow`/`deny` ограничивают доступ по IP; `auth_basic` + `htpasswd` дают basic-auth
(проверка: без пароля 401, с паролем 200).

</details>

---

### Блок D. Инциденты

**D1.** После деплоя все запросы к `/api` возвращают 404 от бэкенда, хотя раньше работали.
В конфиг добавили слеш в `proxy_pass`. Объясни.

<details><summary>Ответ</summary>

Слеш в `proxy_pass` заменил префикс: бэкенд стал получать `/users` вместо `/api/users`,
а его маршруты рассчитаны на `/api/...`. Убрать слеш (или скорректировать маршруты/`rewrite`).

</details>

**D2.** Пользователи получают 502, `systemctl status app` — active (running).
Что проверить по порядку?

<details><summary>Ответ</summary>

`ss -tlnp` на бэкенде (слушает ли и на каком адресе), `curl` напрямую к бэкенду
в обход nginx, адрес/порт в `proxy_pass`, `error.log` nginx (refused/timeout/prematurely
closed), лимиты воркеров и файловых дескрипторов, сеть между nginx и бэкендом.

</details>

**D3.** В логах много 499. Пользователи жалуются на «долгую загрузку». Связь?

<details><summary>Ответ</summary>

499 означает, что клиент закрыл соединение, не дождавшись ответа. Это следствие
медленного бэкенда (или слишком маленьких таймаутов у клиента): пользователи устают ждать
и обновляют страницу. Лечить надо скорость бэкенда, а не nginx.

</details>

**D4.** После включения второго бэкенда часть пользователей «разлогинивается» при каждом
запросе. Причина и два решения.

<details><summary>Ответ</summary>

Сессии хранятся локально на бэкенде, а балансировка round-robin отправляет
запросы на разные узлы. Решения: общее хранилище сессий (Redis/БД) — правильное;
липкие сессии (`ip_hash` или cookie-based sticky) — временное.

</details>

**D5.** `nginx -t` проходит, `reload` выполнен, но сайт отдаёт старый конфиг. Варианты?

<details><summary>Ответ</summary>

Правится не тот файл (не подключён `include`/нет симлинка в `sites-enabled`),
`reload` выполнен для другого экземпляра/в контейнере, ответ отдаётся из кеша
(`proxy_cache` или кеш браузера/CDN), либо запрос попадает в другой `server`/`location`.
Проверка — `nginx -T | grep -n …` и `curl -H 'Cache-Control: no-cache' -I`.

</details>

**D6.** После настройки HTTPS приложение уходит в бесконечный редирект.

<details><summary>Ответ</summary>

Приложение видит `X-Forwarded-Proto: http` (или заголовок не передан) и редиректит
на https, а nginx снова ходит на бэкенд по http. Добавить `proxy_set_header
X-Forwarded-Proto $scheme;` и настроить доверие в приложении.

</details>

**D7.** Загрузка файлов больше 1 МБ падает с 413, хотя `client_max_body_size 50m`
прописан в `server`-блоке. Где может быть ошибка?

<details><summary>Ответ</summary>

Директива задана в другом `server`-блоке, чем тот, что обрабатывает запрос;
либо есть более специфичный `location` со своим значением; либо ограничение на стороне
приложения/upstream. Проверить `nginx -T` и в каком server/location реально идёт обработка.

</details>

**D8.** Nginx отдаёт 500 при обращении к статике, в error.log — `Permission denied`.
Что проверить (три места)?

<details><summary>Ответ</summary>

(1) Права на сам файл (`chmod 644`); (2) права `x` на все каталоги пути
(`/var/www/...`); (3) пользователь nginx (`user www-data`) и владелец файлов,
а на RHEL — ещё SELinux-контексты (`ls -Z`, `restorecon`).

</details>

**D9.** После рестарта все бэкенды помечены как недоступные, хотя они работают.
Что могло случиться и как проверить?

<details><summary>Ответ</summary>

После рестарта бэкенды могли не успеть подняться, и `max_fails` их «выключил»;
либо неверное DNS-имя в upstream (nginx резолвит имена при старте и кеширует),
либо изменились адреса контейнеров. Проверить `error.log` (`no live upstreams`),
`curl` напрямую, использовать `resolver` с `zone`/переменными в `proxy_pass` для
динамического резолва.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое reverse proxy и зачем он нужен?

<details><summary>Ответ</summary>

Сервер-посредник между клиентами и бэкендами: терминация TLS, маршрутизация,
балансировка, кеш, лимиты, единая точка логирования и защиты.

</details>

**2.** Как nginx выбирает server и location?

<details><summary>Ответ</summary>

По `listen` и `Host`/`server_name` выбирается `server`, затем по приоритету —
`location` (точное → `^~` → regex → длинный префикс).

</details>

**3.** Как настроить балансировку и какие алгоритмы бывают?

<details><summary>Ответ</summary>

Через `upstream` с серверами и алгоритмом: round-robin, weight, least_conn, ip_hash, hash.

</details>

**4.** Что означают 502 и 504 в nginx?

<details><summary>Ответ</summary>

502 — не смог получить ответ от бэкенда; 504 — бэкенд не ответил за `proxy_read_timeout`.

</details>

**5.** Чем reload отличается от restart?

<details><summary>Ответ</summary>

`reload` применяет конфиг без разрыва соединений; `restart` перезапускает процесс.

</details>

**6.** Как передать реальный IP клиента на бэкенд?

<details><summary>Ответ</summary>

Заголовками `X-Real-IP`/`X-Forwarded-For` + доверие к прокси на бэкенде.

</details>

**7.** Как ограничить размер загружаемого файла?

<details><summary>Ответ</summary>

`client_max_body_size`.

</details>

**8.** Как настроить rate limiting?

<details><summary>Ответ</summary>

`limit_req_zone` + `limit_req` (и `limit_conn` для числа соединений).

</details>

**9.** Как nginx проверяет живость бэкендов?

<details><summary>Ответ</summary>

Пассивно: `max_fails` и `fail_timeout`; активных проверок в open source нет.

</details>

**10.** Чем nginx отличается от HAProxy?

<details><summary>Ответ</summary>

Nginx — веб-сервер + L7-прокси со статикой, кешем и гибкой маршрутизацией;
HAProxy — специализированный балансировщик с активными health-check, богатой
статистикой и сильным L4-режимом.

</details>

---

### 🎯 Чек-лист

- [ ] Пишу рабочий конфиг reverse proxy с нуля
- [ ] Помню приоритет location и эффект слеша в `proxy_pass`
- [ ] Всегда ставлю `X-Forwarded-*`
- [ ] Воспроизвёл 502, 504, 499, 413, 403 и знаю, что в логах
- [ ] Настроил балансировку и проверил поведение при падении бэкенда
- [ ] Включил кеш с `use_stale` и rate limiting
- [ ] Делаю `nginx -t` перед каждым reload
- [ ] Анализирую access.log с `$upstream_response_time`
