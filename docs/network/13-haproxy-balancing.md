---
title: "13. HAProxy и балансировка"
description: "L4 vs L7, алгоритмы балансировки, активные health-check, runtime API, VIP/keepalived — конспект и задачи"
---

# 13. HAProxy и балансировка нагрузки

> Роадмап → 2.5 Сети → Балансировщики: **HAProxy**.
> **После темы ты умеешь:** объяснить L4 vs L7, выбрать алгоритм балансировки, настроить
> HAProxy с health-check и stats, и понимать, как строится отказоустойчивость (VIP/keepalived).

---

## 🗺️ Схема: балансировка и отказоустойчивость

```text:no-line-numbers
                        ┌────────────── VIP 192.168.56.100 ──────────────┐
                        │        (keepalived / VRRP: переезжает)         │
                        ▼                                               ▼
                 ┌─────────────┐                               ┌─────────────┐
                 │ HAProxy #1  │  MASTER                       │ HAProxy #2  │ BACKUP
                 └──────┬──────┘                               └─────────────┘
                        │ health-check каждые 2 с
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
    app-1:8080      app-2:8080      app-3:8080
     (UP)            (UP)            (DOWN — выведен из ротации)
```

⭐ Балансировщик сам по себе — единая точка отказа. Отказоустойчивость даёт пара узлов
с плавающим адресом (VIP), который переезжает по VRRP.

---

## 1. L4 vs L7 — главный вопрос темы

| | L4 (транспортный) | L7 (прикладной) |
|---|---|---|
| Что видит | IP, порт, TCP-поток | HTTP-запрос: метод, URL, заголовки, куки |
| Маршрутизация по пути/домену | ❌ | ✅ |
| Терминация TLS | Обычно нет (passthrough) | ✅ |
| Ретраи, sticky по cookie | Ограниченно | ✅ |
| Производительность | Выше, задержка ниже | Ниже (парсинг запроса) |
| HAProxy | `mode tcp` | `mode http` |
| Примеры | AWS NLB, IPVS, `Service` в k8s | nginx, HAProxy http, ALB, Ingress |

Практика: L4 — для баз, очередей, gRPC-стримов и там, где нужен passthrough TLS;
L7 — для веба, где нужны маршрутизация, ретраи и наблюдаемость.

---

## 2. Алгоритмы балансировки

| Алгоритм | HAProxy | Когда применять |
|----------|---------|-----------------|
| Round-robin | `balance roundrobin` | Одинаковые бэкенды, короткие запросы |
| Weighted | `server ... weight 3` | Разная мощность узлов |
| Least connections | `balance leastconn` | ⭐ Долгие и разные по длительности запросы |
| Source hash | `balance source` | Липкость по IP |
| URI hash | `balance uri` | Кеширующие бэкенды (один URL — один узел) |
| Header hash | `balance hdr(Host)` | Мультитенантность |
| Random | `balance random` | Много бэкендов, равномерность без состояния |

**Sticky sessions (липкость):** нужны, когда состояние хранится локально на бэкенде.
Варианты: по IP (`balance source` — ломается за NAT), по cookie (`cookie SRV insert indirect
nocache` — надёжнее). ⭐ Правильное решение — вынести сессии в Redis/БД и не нуждаться
в липкости вовсе.

---

## 3. Health-check — то, ради чего часто берут HAProxy

```text:no-line-numbers
backend app
    option httpchk GET /health
    http-check expect status 200
    default-server inter 2s fall 3 rise 2
    server app1 10.0.0.11:8080 check
    server app2 10.0.0.12:8080 check
    server app3 10.0.0.13:8080 check backup
```

| Параметр | Смысл |
|----------|-------|
| `inter 2s` | Интервал проверок |
| `fall 3` | Сколько неудач подряд, чтобы признать мёртвым |
| `rise 2` | Сколько успехов, чтобы вернуть в ротацию |
| `check` | Включить проверки для сервера |
| `backup` | Использовать, только если все основные мертвы |

⭐ В отличие от open source nginx, здесь проверки **активные**: HAProxy сам опрашивает
бэкенды и знает их состояние до того, как туда попадёт реальный пользователь.

**Правильный `/health`:** быстрый (миллисекунды), без тяжёлых зависимостей,
отражающий готовность именно этого инстанса. Разделяют liveness («процесс жив»)
и readiness («готов принимать трафик») — как в Kubernetes (Kubernetes/09, probes).

---

## 4. Конфигурация HAProxy целиком

```text:no-line-numbers
global
    log /dev/log local0
    maxconn 20000
    user haproxy
    group haproxy
    daemon
    stats socket /run/haproxy/admin.sock mode 660 level admin   # ⭐ runtime API

defaults
    log     global
    mode    http
    option  httplog
    option  dontlognull
    option  forwardfor                 # ⭐ добавляет X-Forwarded-For
    option  http-server-close
    timeout connect 5s
    timeout client  30s
    timeout server  30s                # ⭐ аналог proxy_read_timeout → источник 504
    retries 3

frontend web
    bind :80
    bind :443 ssl crt /etc/haproxy/certs/example.pem alpn h2,http/1.1
    http-request redirect scheme https unless { ssl_fc }

    acl is_api  path_beg /api
    acl is_static path_end .css .js .png .jpg
    use_backend api_servers    if is_api
    use_backend static_servers if is_static
    default_backend app_servers

backend app_servers
    balance leastconn
    option httpchk GET /health
    http-check expect status 200
    cookie SRV insert indirect nocache          # липкость по cookie
    default-server inter 2s fall 3 rise 2
    server app1 10.0.0.11:8080 check cookie a1
    server app2 10.0.0.12:8080 check cookie a2

backend api_servers
    balance roundrobin
    server api1 10.0.0.21:9000 check

listen stats                                     # ⭐ страница статистики
    bind :8404
    stats enable
    stats uri /stats
    stats refresh 5s
    stats admin if TRUE
```

```bash
sudo haproxy -c -f /etc/haproxy/haproxy.cfg      # ⭐ проверка конфига
sudo systemctl reload haproxy                     # без разрыва (seamless reload)
curl -s http://localhost:8404/stats               # HTML-страница статистики
echo "show stat" | sudo socat stdio /run/haproxy/admin.sock | cut -d, -f1,2,18,19
echo "disable server app_servers/app1" | sudo socat stdio /run/haproxy/admin.sock   # ⭐ вывести из ротации
echo "enable server app_servers/app1"  | sudo socat stdio /run/haproxy/admin.sock
```

⭐ Runtime API — то, чего нет у nginx: можно выводить бэкенд из ротации **без перезагрузки**,
что превращает деплой в управляемый процесс (drain → deploy → enable).

---

## 5. HAProxy vs Nginx — вопрос с собеседования

| | Nginx | HAProxy |
|---|-------|---------|
| Изначальная задача | Веб-сервер | Балансировщик |
| Статика | ✅ Отлично | ❌ Не умеет |
| Кеширование | ✅ | ❌ |
| Health-check в OSS | Пассивные | ⭐ Активные |
| L4-режим | `stream` (есть) | ⭐ Основной режим `tcp` |
| Статистика | Скудная (`stub_status`) | ⭐ Подробная страница + API |
| Runtime-управление | Нет (нужен reload) | ⭐ Есть (socket API) |
| TLS-терминация | ✅ | ✅ |
| Где встречается | Веб, Ingress | Балансировка БД/сервисов, перед кластерами |

Короткий ответ: «Nginx — веб-сервер, который умеет балансировать; HAProxy — балансировщик,
который не умеет отдавать статику. Для веба с кешем и статикой берут nginx, для честной
балансировки с активными проверками и L4 — HAProxy».

---

## 6. Отказоустойчивость: VIP и keepalived

```text:no-line-numbers
# /etc/keepalived/keepalived.conf на MASTER
vrrp_script chk_haproxy {
    script "/usr/bin/killall -0 haproxy"
    interval 2
    weight -20                 # упал HAProxy → приоритет падает → VIP уезжает
}
vrrp_instance VI_1 {
    state MASTER
    interface eth1
    virtual_router_id 51
    priority 110               # на BACKUP — 100
    advert_int 1
    authentication { auth_type PASS; auth_pass secret }
    virtual_ipaddress { 192.168.56.100/24 }
    track_script { chk_haproxy }
}
```

Как это работает: узлы обмениваются VRRP-объявлениями; узел с наибольшим приоритетом держит
VIP и рассылает **gratuitous ARP** (см. [02. L2, Ethernet, ARP](/network/02-l2-ethernet-arp)), чтобы соседи обновили
ARP-таблицы. При падении MASTER'а VIP переезжает за 1-3 секунды.

⚠️ В облаках VRRP обычно не работает (запрещён multicast и «чужие» адреса на порту) —
там используют облачный балансировщик или API-переназначение адреса.

---

## 7. Что ломается в балансировке

| Симптом | Причина |
|---------|---------|
| Пользователей «разлогинивает» | Сессии локальные, нет липкости/общего хранилища |
| Все бэкенды в DOWN, хотя работают | `/health` требует БД, которая недоступна; неверный путь/код проверки |
| 503 от балансировщика | Нет живых бэкендов (`no server available`) |
| 504 | Бэкенд не ответил за `timeout server` |
| Реальный IP клиента потерян | Нет `option forwardfor` / не настроен `real_ip` на бэкенде |
| Неравномерная нагрузка | `balance source` за NAT (все клиенты с одного IP) |
| Долгие соединения рвутся | `timeout client/server` меньше, чем длительность запроса |
| При деплое 502 | Бэкенд остановлен до вывода из ротации — нужен drain |

---

## 💼 Как это в DevOps

- Балансировщик — место, где выполняется rolling deploy: drain → обновить → вернуть в ротацию.
- Stats-страница HAProxy — первое, что открывают при инциденте: сразу видно, какие бэкенды живы.
- Активные health-check спасают от «раскатили битую версию и только пользователи заметили».
- `Service` в Kubernetes — это L4-балансировка (iptables/IPVS), `Ingress` — L7;
  под капотом идеи те же.
- Для БД (PostgreSQL, RabbitMQ) HAProxy в `mode tcp` — стандартная схема с patroni/кластером.

---

## 🧪 Мини-лаба

```bash
vagrant ssh web
sudo apt install -y haproxy socat curl

# 1. Два «бэкенда» с разными ответами
for p in 9101 9102; do
  (while true; do printf "HTTP/1.1 200 OK\r\nContent-Length: 9\r\n\r\nbackend$p" | nc -l -p $p -q0 >/dev/null 2>&1; done) &
done

# 2. Конфиг HAProxy
sudo cp /etc/haproxy/haproxy.cfg /etc/haproxy/haproxy.cfg.bak
sudo tee -a /etc/haproxy/haproxy.cfg >/dev/null <<'EOS'

frontend lab_front
    bind :8100
    mode http
    default_backend lab_back

backend lab_back
    mode http
    balance roundrobin
    option forwardfor
    default-server inter 2s fall 2 rise 1
    server b1 127.0.0.1:9101 check
    server b2 127.0.0.1:9102 check

listen lab_stats
    bind :8404
    mode http
    stats enable
    stats uri /stats
    stats refresh 5s
EOS
sudo haproxy -c -f /etc/haproxy/haproxy.cfg && sudo systemctl reload haproxy

# 3. Балансировка в действии
for i in $(seq 1 6); do curl -s http://localhost:8100/; echo; done

# 4. Статистика
curl -s "http://localhost:8404/stats;csv" | cut -d, -f1,2,18 | head -8

# 5. Падение бэкенда и health-check
pkill -f 'nc -l -p 9102'; sleep 5
for i in $(seq 1 4); do curl -s http://localhost:8100/; echo; done    # весь трафик на b1
curl -s "http://localhost:8404/stats;csv" | grep b2 | cut -d, -f1,2,18

# 6. Все бэкенды мертвы → 503
pkill -f 'nc -l -p 910'; sleep 5
curl -s -o /dev/null -w 'нет бэкендов: %{http_code}\n' http://localhost:8100/

# 7. Runtime API: вывести сервер из ротации без reload
for p in 9101 9102; do
  (while true; do printf "HTTP/1.1 200 OK\r\nContent-Length: 9\r\n\r\nbackend$p" | nc -l -p $p -q0 >/dev/null 2>&1; done) &
done; sleep 3
echo "show stat" | sudo socat stdio /run/haproxy/admin.sock 2>/dev/null | cut -d, -f1,2,18 | head -6
echo "disable server lab_back/b1" | sudo socat stdio /run/haproxy/admin.sock 2>/dev/null
for i in $(seq 1 4); do curl -s http://localhost:8100/; echo; done    # только b2
echo "enable server lab_back/b1" | sudo socat stdio /run/haproxy/admin.sock 2>/dev/null

# 8. Алгоритмы: source вместо roundrobin
sudo sed -i 's/balance roundrobin/balance source/' /etc/haproxy/haproxy.cfg
sudo haproxy -c -f /etc/haproxy/haproxy.cfg && sudo systemctl reload haproxy
for i in $(seq 1 6); do curl -s http://localhost:8100/; echo; done    # всегда один и тот же

# 9. Таймауты и 504
sudo sed -i 's/^    timeout server.*/    timeout server 2s/' /etc/haproxy/haproxy.cfg
sudo haproxy -c -f /etc/haproxy/haproxy.cfg && sudo systemctl reload haproxy
pkill -f 'nc -l -p 9101'
(while true; do sleep 10 | nc -l -p 9101 -q0 >/dev/null 2>&1; done) &
curl -s -o /dev/null -w 'медленный бэкенд: %{http_code} за %{time_total}s\n' --max-time 15 http://localhost:8100/

# 10. Сравнение с nginx: тот же сценарий (см. тему 12) — обрати внимание,
#     что HAProxy пометил бэкенд DOWN ДО того, как туда попал пользователь.

# 11. Уборка
pkill -f 'nc -l -p 910'
sudo cp /etc/haproxy/haproxy.cfg.bak /etc/haproxy/haproxy.cfg
sudo haproxy -c -f /etc/haproxy/haproxy.cfg && sudo systemctl reload haproxy
```

---

## 📌 Шпаргалка

| Команда / директива | Смысл |
|---------------------|-------|
| `haproxy -c -f файл` | ⭐ Проверить конфиг |
| `systemctl reload haproxy` | Применить без разрыва |
| `mode http` / `mode tcp` | L7 / L4 |
| `balance roundrobin\|leastconn\|source\|uri` | Алгоритм |
| `option httpchk GET /health` | ⭐ Активная проверка |
| `default-server inter 2s fall 3 rise 2` | Параметры проверок |
| `server x ip:port check backup` | Бэкенд, резервный |
| `option forwardfor` | X-Forwarded-For |
| `timeout connect/client/server` | Таймауты (504 — из server) |
| `cookie SRV insert indirect nocache` | Липкость по cookie |
| `stats uri /stats` | Страница статистики |
| `echo "show stat" \| socat stdio /run/haproxy/admin.sock` | Статистика в CSV |
| `disable/enable server backend/srv` | ⭐ Ротация без reload |
| keepalived + VIP | Отказоустойчивость самого балансировщика |

---

## 🧠 Что запомнить

1. L4 балансирует TCP-поток (быстро, «слепо»), L7 разбирает HTTP (маршрутизация, ретраи, TLS).
2. Алгоритмы: roundrobin, weight, leastconn, source/uri hash. `leastconn` — универсальный выбор
   при разной длительности запросов.
3. Липкость — костыль для локальных сессий; правильнее вынести сессии во внешнее хранилище.
4. ⭐ HAProxy делает **активные** health-check, open source nginx — только пассивные.
5. `/health` должен быть быстрым и не зависеть от тяжёлых внешних систем, иначе
   балансировщик выведет из ротации живые бэкенды.
6. Runtime API (`disable server`) позволяет делать rolling deploy без перезагрузки конфига.
7. `timeout server` — источник 504; `no server available` — источник 503.
8. `option forwardfor` обязателен, иначе бэкенд видит IP балансировщика.
9. Сам балансировщик — точка отказа: нужна пара узлов с VIP (keepalived/VRRP)
   или облачный LB.
10. Переезд VIP работает через gratuitous ARP; в облаках VRRP обычно недоступен.
11. Stats-страница HAProxy — первое, что смотрят при инциденте с балансировкой.

---

## Задачи

> Сравнивай с темой [12. Nginx](/network/12-nginx): одни и те же сценарии на двух инструментах.

---

### Блок A. Теория

**A1.** Чем L4-балансировка отличается от L7? Приведи по три примера реализаций.

<details><summary>Ответ</summary>

L4 работает с TCP/UDP-потоком (IP и порт), не разбирая содержимое: HAProxy `mode tcp`,
IPVS/kube-proxy, AWS NLB. L7 разбирает HTTP и маршрутизирует по URL/заголовкам:
nginx, HAProxy `mode http`, AWS ALB / Ingress-контроллеры.

</details>

**A2.** Когда нужен `mode tcp`, а когда `mode http`?

<details><summary>Ответ</summary>

`mode tcp` — для не-HTTP протоколов (PostgreSQL, Redis, SMTP, gRPC-стримы),
для TLS passthrough и там, где важна минимальная задержка. `mode http` — когда нужны
маршрутизация по пути/домену, cookie-липкость, ретраи, вставка заголовков, логирование запросов.

</details>

**A3.** Назови алгоритмы балансировки и по одному сценарию для каждого.

<details><summary>Ответ</summary>

roundrobin — равные бэкенды; weight — разная мощность; leastconn — долгие запросы
разной длительности; source — липкость по IP; uri — кеширующие бэкенды;
hdr(Host) — мультитенантность; random — много одинаковых узлов.

</details>

**A4.** Что такое sticky sessions? Два способа реализации и минусы каждого.
Почему это считается костылём?

<details><summary>Ответ</summary>

Привязка клиента к одному бэкенду. По IP (`balance source`) — просто, но ломается
за NAT/CGNAT и при смене сети; по cookie — точнее, но требует HTTP (не работает в L4)
и добавляет состояние в балансировщик. Костыль, потому что маскирует настоящую проблему —
локальное хранение сессий; правильное решение — общее хранилище (Redis/БД/JWT).

</details>

**A5.** ⭐ Чем активные health-check лучше пассивных? Что делает `inter`, `fall`, `rise`?

<details><summary>Ответ</summary>

Активные проверки выявляют мёртвый бэкенд **до** того, как туда попадёт пользователь;
пассивные узнают о проблеме, только «испортив» чей-то запрос. `inter` — интервал проверок,
`fall` — сколько неудач подряд для перевода в DOWN, `rise` — сколько успехов для возврата.

</details>

**A6.** Каким должен быть эндпоинт `/health` и чем он отличается от `/ready`?

<details><summary>Ответ</summary>

`/health` — быстрый, без внешних зависимостей, отражает работоспособность процесса.
`/ready` — готовность принимать трафик (прогрет кеш, есть соединение с БД, миграции
завершены). Смешивать опасно: если `/health` ходит в БД, кратковременная недоступность БД
выведет из ротации **все** бэкенды сразу.

</details>

**A7.** Откуда в HAProxy берутся коды 503 и 504?

<details><summary>Ответ</summary>

503 — нет доступных серверов в backend (все DOWN или превышен `maxconn`);
504 — бэкенд не ответил за `timeout server` (аналог `proxy_read_timeout` в nginx).

</details>

**A8.** Что делает `option forwardfor`?

<details><summary>Ответ</summary>

Добавляет заголовок `X-Forwarded-For` с адресом клиента к запросам, идущим на бэкенд.

</details>

**A9.** Что даёт runtime API (socket) и почему это важно при деплое?

<details><summary>Ответ</summary>

Позволяет менять состояние (включать/выключать серверы, менять веса, смотреть
статистику) **без перезагрузки** конфига и разрыва соединений. Это основа управляемого
rolling deploy: сначала drain, потом обновление, потом возврат в ротацию.

</details>

**A10.** Сравни nginx и HAProxy: 5 отличий.

<details><summary>Ответ</summary>

(1) Nginx умеет статику и кеш, HAProxy — нет; (2) HAProxy имеет активные health-check
в open source; (3) у HAProxy подробная статистика и runtime API; (4) HAProxy сильнее
в L4-режиме; (5) nginx чаще встречается как веб-сервер/Ingress, HAProxy — как выделенный
балансировщик перед БД и кластерами.

</details>

**A11.** Что такое VIP и как работает keepalived/VRRP?

<details><summary>Ответ</summary>

VIP — виртуальный IP, который держит активный узел. keepalived реализует VRRP:
узлы обмениваются объявлениями, узел с наибольшим приоритетом владеет адресом; при его
падении адрес забирает следующий и рассылает gratuitous ARP.

</details>

**A12.** Почему VRRP обычно не работает в облаках и что делают вместо него?

<details><summary>Ответ</summary>

Облачные сети фильтруют multicast и запрещают отправку трафика с «чужих» адресов
(anti-spoofing). Вместо VRRP используют облачный балансировщик, переназначение
floating/elastic IP через API или DNS-переключение.

</details>

**A13.** Как балансировщик участвует в rolling deploy?

<details><summary>Ответ</summary>

Балансировщик выводит инстанс из ротации (drain), даёт завершить текущие
соединения, после обновления проверяет health и возвращает в ротацию — пользователи
не видят ошибок.

</details>

**A14.** Как эти идеи отражены в Kubernetes (Service, Ingress, probes, endpoints)?

<details><summary>Ответ</summary>

Service = L4-балансировка (iptables/IPVS правила kube-proxy), Ingress = L7,
readiness-проба = health-check (под исключается из Endpoints), rolling update Deployment =
тот же drain → обновление → возврат.

</details>

---

### Блок B. «Что делает конфиг»

```text:no-line-numbers
B1.  balance leastconn
B2.  balance source
B3.  server app1 10.0.0.11:8080 check inter 2s fall 3 rise 2
B4.  server app3 10.0.0.13:8080 check backup
B5.  option httpchk GET /health
B6.  http-check expect status 200
B7.  cookie SRV insert indirect nocache
B8.  timeout server 30s
B9.  http-request redirect scheme https unless { ssl_fc }
B10. use_backend api_servers if { path_beg /api }
B11. bind :443 ssl crt /etc/haproxy/certs/site.pem alpn h2,http/1.1
B12. echo "disable server app/app1" | socat stdio /run/haproxy/admin.sock
```

<details><summary>Ответ</summary>

- **B1.** Отправлять запрос на бэкенд с наименьшим числом активных соединений.
- **B2.** Привязка клиента к бэкенду по хешу его IP.
- **B3.** Проверки каждые 2 с, DOWN после 3 неудач, UP после 2 успехов.
- **B4.** Резервный сервер: получает трафик, только когда все основные мертвы.
- **B5.** HTTP-проверка методом GET на `/health`.
- **B6.** Считать проверку успешной только при коде 200.
- **B7.** Липкость по cookie `SRV`, вставляемому балансировщиком и не кешируемому.
- **B8.** Ждать ответа бэкенда не более 30 с, иначе 504.
- **B9.** Редирект на HTTPS для всех незашифрованных запросов.
- **B10.** Запросы с путём, начинающимся на `/api`, идут в отдельный backend.
- **B11.** Терминация TLS с указанным PEM и поддержкой HTTP/2 через ALPN.
- **B12.** Выводит сервер из ротации через runtime API без перезагрузки.

</details>

**B13.** Что произойдёт, если `option httpchk` указывает на `/` , а приложение отвечает
на `/` редиректом 302?

<details><summary>Ответ</summary>

Проверка будет считаться неуспешной (ожидается 200, приходит 302), и все бэкенды
уйдут в DOWN — классическая ошибка. Нужно либо `http-check expect status 200,302`,
либо отдельный эндпоинт `/health`.

</details>

---

### Блок C. Практика

**C1. 🔑 Базовый HAProxy.** Настрой frontend на 8100 и backend с двумя серверами,
roundrobin, активными health-check и stats-страницей. Проверь распределение запросов
и содержимое статистики.

<details><summary>Ответ</summary>

Конфиг — в мини-лабе конспекта. В статистике смотри колонки `status`, `check_status`,
`lastchg`, `scur`, `qcur`.

</details>

**C2. Падение и восстановление.** Останови один бэкенд, зафиксируй: через сколько секунд
он помечен DOWN (посчитай по `inter`/`fall`), куда пошёл трафик, что показывает stats.
Подними обратно и замерь возврат в ротацию (`rise`).

<details><summary>Ответ</summary>

При `inter 2s fall 3` бэкенд помечается DOWN примерно через 6 секунд.
Трафик полностью уходит на живой. При `rise 2` возврат занимает ~4 секунды после
восстановления.

</details>

**C3. Все бэкенды мертвы.** Останови оба и покажи код ответа. Добавь `backup`-сервер
с заглушкой «идут работы» и покажи, что пользователь видит её вместо 503.

<details><summary>Ответ</summary>

Без бэкендов — 503. С `server maint 127.0.0.1:9999 backup` и заглушкой
пользователь получает 200 со страницей обслуживания.

</details>

**C4. Алгоритмы.** Сравни поведение `roundrobin`, `leastconn` и `source` на одинаковой
нагрузке. Для `leastconn` сделай один бэкенд медленным и покажи, что на него уходит
меньше запросов.

<details><summary>Ответ</summary>

`roundrobin` распределяет поровну независимо от занятости; `leastconn` отправляет
меньше запросов на медленный бэкенд (у него больше активных соединений);
`source` с одного клиента всегда попадает в один и тот же бэкенд.

</details>

**C5. Липкость.** Настрой липкость по cookie, покажи, что один клиент всегда попадает
на один бэкенд, а другой — на другой. Затем удали cookie и покажи перераспределение.

<details><summary>Ответ</summary>

С `cookie SRV insert indirect nocache` в ответе появляется `Set-Cookie: SRV=a1`,
и последующие запросы с этим cookie идут на тот же сервер. `curl -b/-c` для эмуляции;
без cookie — снова балансировка.

</details>

**C6. Реальный IP.** Убедись, что без `option forwardfor` бэкенд видит адрес балансировщика,
а с ним — адрес клиента.

<details><summary>Ответ</summary>

Без `option forwardfor` бэкенд видит адрес HAProxy; с ним — в `X-Forwarded-For`
приходит адрес клиента (бэкенд должен доверять заголовку).

</details>

**C7. Таймауты.** Выставь `timeout server 2s`, сделай медленный бэкенд и покажи 504.
Сравни поведение с nginx из темы 12.

<details><summary>Ответ</summary>

`timeout server 2s` + медленный бэкенд → 504 ровно через 2 секунды.
В nginx аналогичное поведение даёт `proxy_read_timeout`.

</details>

**C8. Runtime-деплой.** Реализуй сценарий rolling deploy: `disable server` → дождаться
завершения соединений → «обновить» бэкенд → `enable server`. Покажи через непрерывный
`curl`-цикл, что пользователи не получили ни одной ошибки.

<details><summary>Ответ</summary>

```bash
# терминал 1: непрерывная проверка
while true; do curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8100/; sleep 0.2; done | sort | uniq -c
# терминал 2: деплой
echo "disable server lab_back/b1" | sudo socat stdio /run/haproxy/admin.sock
sleep 2                                  # дать завершиться текущим соединениям
# ... обновление бэкенда ...
echo "enable server lab_back/b1"  | sudo socat stdio /run/haproxy/admin.sock
```
Ожидаемый результат — только коды 200.

</details>

**C9. L4-режим.** Настрой `mode tcp` для проксирования PostgreSQL (или любого TCP-сервиса)
и покажи, что балансировка работает, но HAProxy не видит содержимое запросов.

<details><summary>Ответ</summary>

`mode tcp` + `server db1 10.0.0.11:5432 check`: балансировка работает,
но в логах видно только соединения (`option tcplog`), без SQL-запросов; маршрутизация
по содержимому невозможна.

</details>

**C10. TLS.** Собери PEM (сертификат + ключ), включи `bind :443 ssl crt`,
настрой редирект http→https. Проверь `openssl s_client`.

<details><summary>Ответ</summary>

`cat site.crt site.key > /etc/haproxy/certs/site.pem`, затем
`bind :443 ssl crt /etc/haproxy/certs/site.pem` и `http-request redirect scheme https unless { ssl_fc }`.

</details>

**C11. Сравнение с nginx.** Разверни один и тот же сценарий (2 бэкенда, один падает)
на nginx и HAProxy. Заполни таблицу: как быстро обнаружено падение, что видно в статистике,
сколько запросов получили ошибку.

<details><summary>Ответ</summary>

Ожидаемый итог: HAProxy обнаруживает падение за `inter*fall` секунд **без** ошибок
у пользователей; nginx (пассивные проверки) отдаст несколько 502, пока не наберёт `max_fails`.
Статистика: у HAProxy — подробная страница, у nginx — только логи.

</details>

**C12. VIP (по возможности).** На двух ВМ настрой keepalived с общим VIP, проверь переезд
адреса при остановке HAProxy на MASTER. Посмотри gratuitous ARP в tcpdump.

<details><summary>Ответ</summary>

Конфиг keepalived — в конспекте. Проверка: `ip addr show eth1` на MASTER содержит VIP;
после `systemctl stop haproxy` (при настроенном `track_script`) VIP появляется на BACKUP,
а в `tcpdump -i eth1 arp` видно gratuitous ARP.

</details>

---

### Блок D. Инциденты

**D1.** HAProxy показывает все бэкенды в DOWN, при этом `curl` к ним напрямую работает.
Три причины.

<details><summary>Ответ</summary>

(1) Проверка идёт на неверный путь/порт или ожидает не тот код (например, приложение
отвечает 302); (2) `/health` зависит от внешней системы, которая недоступна;
(3) сетевой доступ от балансировщика к бэкендам закрыт (файрвол/security group),
хотя с твоей машины они доступны.

</details>

**D2.** После деплоя пользователи получили сотни 502/503, хотя приложение поднялось за 20 секунд.
Как надо было деплоить?

<details><summary>Ответ</summary>

Инстансы останавливались до вывода из ротации. Правильно: drain через runtime API
(или readiness-пробу в k8s), ожидание завершения соединений, обновление, health-check,
возврат в ротацию — по одному инстансу за раз.

</details>

**D3.** Нагрузка распределяется неравномерно: один бэкенд загружен вдвое сильнее.
Две причины и как проверить.

<details><summary>Ответ</summary>

(1) `balance source` и клиенты за общим NAT — хеш даёт один бэкенд;
(2) разные веса/мощность, долгие соединения (keep-alive, WebSocket) закрепились на одном узле.
Проверка — колонки `scur`/`stot` в статистике и распределение по времени.

</details>

**D4.** Пользователи периодически «теряют корзину» в интернет-магазине. Диагноз и два решения.

<details><summary>Ответ</summary>

Сессии хранятся локально, липкости нет. Решения: общее хранилище сессий (Redis)
или липкость по cookie как временная мера.

</details>

**D5.** Долгие отчёты (5 минут) обрываются на середине. Что настроить?

<details><summary>Ответ</summary>

Увеличить `timeout server` (и `timeout client`) для соответствующего backend,
либо вынести отчёты в асинхронную задачу с опросом статуса — правильнее, чем держать
HTTP-соединение пять минут.

</details>

**D6.** В логах бэкенда все запросы приходят с одного адреса. Что забыли и где это чинится?

<details><summary>Ответ</summary>

Не включён `option forwardfor` (или бэкенд не доверяет `X-Forwarded-For`).
Чинится на балансировщике + настройкой trusted proxies в приложении/веб-сервере.

</details>

**D7.** VIP не переехал при падении MASTER, сервис недоступен. Что проверить?

<details><summary>Ответ</summary>

Приоритеты и `state` в keepalived, работу `track_script` (падение HAProxy должно
снижать приоритет), совпадение `virtual_router_id`, прохождение VRRP (multicast 224.0.0.18,
протокол 112) через файрвол и коммутатор, а в облаке — что VRRP вообще разрешён.

</details>

**D8.** Балансировщик начал отдавать 503 при росте трафика, хотя бэкенды не перегружены.
Куда смотреть?

<details><summary>Ответ</summary>

Лимиты самого балансировщика: `maxconn` (global и на backend), очередь (`qcur`),
исчерпание эфемерных портов при большом числе исходящих соединений к бэкендам,
лимиты файловых дескрипторов. Смотреть статистику и `dmesg`.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое балансировка нагрузки и зачем она нужна?

<details><summary>Ответ</summary>

Распределение запросов между несколькими серверами: масштабирование, отказоустойчивость,
возможность обновлять узлы без простоя.

</details>

**2.** Чем L4-балансировка отличается от L7?

<details><summary>Ответ</summary>

L4 — по IP и портам, без разбора содержимого; L7 — с разбором HTTP и маршрутизацией
по URL/заголовкам.

</details>

**3.** Какие алгоритмы балансировки ты знаешь?

<details><summary>Ответ</summary>

roundrobin, weighted, leastconn, source/uri hash, random.

</details>

**4.** Что такое health-check и чем активный отличается от пассивного?

<details><summary>Ответ</summary>

Проверка живости бэкенда. Активная — балансировщик сам опрашивает; пассивная — выводы
делаются по ошибкам реальных запросов.

</details>

**5.** Что такое sticky sessions и как без них обойтись?

<details><summary>Ответ</summary>

Привязка клиента к одному бэкенду; не нужна, если сессии хранятся во внешнем хранилище
или используются stateless-токены.

</details>

**6.** Чем HAProxy отличается от nginx?

<details><summary>Ответ</summary>

Nginx — веб-сервер со статикой и кешем, умеющий балансировать; HAProxy — специализированный
балансировщик с активными проверками, runtime API и сильным L4.

</details>

**7.** Как обеспечить отказоустойчивость самого балансировщика?

<details><summary>Ответ</summary>

Пара балансировщиков с VIP (keepalived/VRRP), облачный LB или DNS/anycast.

</details>

**8.** Как сделать деплой без ошибок у пользователей?

<details><summary>Ответ</summary>

Drain из ротации → обновление → health-check → возврат, по одному инстансу.

</details>

**9.** Как это устроено в Kubernetes?

<details><summary>Ответ</summary>

Service (L4) и Ingress (L7), readiness-пробы управляют Endpoints, rolling update
обновляет поды по одному.

</details>

---

### 🎯 Чек-лист

- [ ] Объясню L4 vs L7 и приведу примеры
- [ ] Знаю алгоритмы балансировки и когда какой брать
- [ ] Настроил HAProxy с активными health-check и stats
- [ ] Понимаю, почему плохой `/health` выводит из ротации живые бэкенды
- [ ] Сделал rolling deploy через runtime API без единой ошибки
- [ ] Сравнил поведение nginx и HAProxy при падении бэкенда
- [ ] Понимаю VIP/keepalived и почему в облаке иначе
- [ ] Связал всё это с Service/Ingress/probes в Kubernetes
