---
title: "08. Сеть в Docker"
description: "bridge, host, none, overlay, macvlan; путь пакета от curl до процесса в контейнере, embedded DNS, публикация портов"
---

# 08. Сеть в Docker

> Роадмап → 3. Docker → Теория → Сеть: «Как работает сеть в докере?»
> Типы сетей: `bridge`, `host`, `none`, `overlay`, `macvlan`
> **После темы ты умеешь:** объяснить путь пакета от `curl localhost:8080` до процесса
> в контейнере, связать контейнеры по именам и починить «не резолвится / не достучаться».

---

## 🗺️ Схема: default bridge и что происходит при `-p 8080:80`

```text:no-line-numbers
                        ХОСТ
  ┌──────────────────────────────────────────────────────────────┐
  │  eth0 192.168.1.10                                           │
  │    │                                                         │
  │    │  iptables (таблица nat, цепочка DOCKER):                │
  │    │  DNAT tcp dpt:8080 → 172.17.0.2:80     ← это и есть -p  │
  │    ▼                                                         │
  │  ┌──────────────────────────────────────────────────────┐    │
  │  │ docker0  172.17.0.1/16   (виртуальный L2-коммутатор) │    │
  │  └───┬──────────────────┬──────────────────┬────────────┘    │
  │      │ veth pair        │ veth             │ veth            │
  └──────┼──────────────────┼──────────────────┼─────────────────┘
         │                  │                  │
   ┌─────▼──────┐    ┌──────▼─────┐     ┌──────▼─────┐
   │ eth0       │    │ eth0       │     │ eth0       │
   │ 172.17.0.2 │    │ 172.17.0.3 │     │ 172.17.0.4 │
   │  nginx:80  │    │  app:8000  │     │  db:5432   │
   └────────────┘    └────────────┘     └────────────┘
      контейнер A        контейнер B       контейнер C

  Исходящий трафик наружу: SNAT/MASQUERADE на адрес хоста.
```

**Что делает `-p 8080:80`:** добавляет правило DNAT в iptables и поднимает
`docker-proxy` (для некоторых случаев). Порт 8080 хоста → порт 80 контейнера.
`EXPOSE` в Dockerfile здесь ни при чём — он только документация.

---

## 1. Типы сетей (драйверы)

| Драйвер | Что делает | Когда |
|---------|-----------|-------|
| **bridge** | Виртуальный коммутатор + NAT. Дефолт для одиночного хоста | 95% случаев |
| **host** | Контейнер использует сетевой стек **хоста** напрямую, без изоляции и NAT | Максимальная производительность сети, приложения, слушающие много портов, сетевые утилиты |
| **none** | Только `lo`, никакой сети | Изолированные задачи: обработка данных, сборка |
| **overlay** | Общая L2-сеть между **несколькими хостами** (VXLAN) | Docker Swarm, мультихостовые кластеры |
| **macvlan** | Контейнер получает **собственный MAC и IP в физической сети** | Легаси-приложения, которым нужен «настоящий» адрес в LAN |
| **ipvlan** | Как macvlan, но один MAC на всех (для сетей с ограничением по MAC) | Специфические сетевые требования |

```bash
docker network ls
docker network inspect bridge
docker network create app-net                       # bridge по умолчанию
docker network create --driver bridge --subnet 172.28.0.0/16 --gateway 172.28.0.1 app-net
docker network create --internal db-net             # ⭐ БЕЗ доступа в интернет
docker network connect app-net web                  # подключить работающий контейнер
docker network disconnect app-net web
docker network rm app-net
docker network prune
```

### `host`

```bash
docker run -d --network host nginx      # nginx слушает порт 80 САМОГО ХОСТА
# -p здесь игнорируется (предупреждение), изоляции сети нет,
# конфликты портов с хостом реальны. На Docker Desktop (Mac/Win) работает иначе — через VM.
```

### `none`

```bash
docker run --rm --network none alpine ip a      # только lo
```

---

## 2. Default bridge vs пользовательская сеть ⭐

Это одно из главных практических отличий, которое спрашивают:

| | `bridge` (дефолтная `docker0`) | Пользовательская сеть (`docker network create`) |
|---|---|---|
| **DNS по имени контейнера** | ❌ нет (только устаревший `--link`) | ✅ **есть**: `ping db` работает |
| Изоляция | Все контейнеры в одной сети видят друг друга | Только участники этой сети |
| Подключение на лету | ❌ | ✅ `network connect/disconnect` |
| Настройка подсети | ограниченно | ✅ |
| Алиасы | ❌ | ✅ `--network-alias` |

```bash
# ❌ так контейнеры друг друга по имени НЕ найдут
docker run -d --name db postgres:16-alpine
docker run --rm alpine ping -c1 db          # bad address 'db'

# ✅ так — найдут
docker network create app-net
docker run -d --name db --network app-net -e POSTGRES_PASSWORD=pw postgres:16-alpine
docker run --rm --network app-net alpine ping -c1 db
```

**Embedded DNS:** внутри контейнера `/etc/resolv.conf` указывает на `127.0.0.11` —
это встроенный DNS-сервер докера. Он резолвит имена контейнеров, сетевые алиасы
и имена сервисов compose, остальное пересылает наверх (в DNS хоста).

```bash
docker exec app cat /etc/resolv.conf        # nameserver 127.0.0.11
docker exec app getent hosts db
docker exec app nslookup db 2>/dev/null || docker exec app ping -c1 db
```

---

## 3. Публикация портов

```bash
-p 8080:80                 # 0.0.0.0:8080 → контейнер:80  (доступно ИЗВНЕ!)
-p 127.0.0.1:8080:80       # только с самого хоста ⭐ безопасный дефолт
-p 8080:80/udp
-p 8080-8090:8080-8090     # диапазон
-P                         # все EXPOSE-порты → случайные порты хоста
--network host             # вообще без публикации, порты хоста напрямую

docker port web            # что куда проброшено
ss -tlnp | grep docker     # на хосте
```

> ⚠️ **Docker и UFW/firewalld.** Докер пишет свои правила в iptables в цепочку `DOCKER`,
> которая обрабатывается **раньше** правил UFW. Поэтому `-p 5432:5432` для базы данных
> открывает её всему интернету, даже если UFW «всё закрыл». Решения:
> публиковать на `127.0.0.1`, использовать `DOCKER-USER` цепочку для своих правил,
> или `"iptables": false` + ручное управление (сложно).

```bash
# Правило в DOCKER-USER (обрабатывается до правил докера)
sudo iptables -I DOCKER-USER -i eth0 ! -s 10.0.0.0/8 -j DROP
```

### Как контейнеру достучаться до хоста

```bash
host.docker.internal                       # Docker Desktop (Mac/Win) — из коробки
docker run --add-host=host.docker.internal:host-gateway ...    # Linux: так же работает
ip route show default | awk '{print $3}'   # или напрямую IP шлюза (172.17.0.1)
```

---

## 4. Типовая архитектура приложения

```text:no-line-numbers
                       ┌──────────── frontend-net (публичная) ────────────┐
   Интернет ──:443──►  │  nginx  ──────────────────────────► app         │
                       └──────────────────────────────────────┬──────────┘
                                                              │
                       ┌──────────── backend-net (--internal) ┴──────────┐
                       │            app ──► postgres    app ──► redis    │
                       └─────────────────────────────────────────────────┘

   Только у nginx опубликованы порты наружу.
   БД и кэш ВООБЩЕ не имеют портов на хосте и недоступны из интернета.
   backend-net с --internal — даже исходящего доступа в интернет у БД нет.
```

```bash
docker network create frontend-net
docker network create --internal backend-net

docker run -d --name db    --network backend-net  -e POSTGRES_PASSWORD=pw postgres:16-alpine
docker run -d --name app   --network backend-net  myapp:1.0
docker network connect frontend-net app                    # app в ОБЕИХ сетях
docker run -d --name nginx --network frontend-net -p 80:80 nginx:alpine

# app обращается к базе как postgres://db:5432 — по имени контейнера
# nginx проксирует на http://app:8000
```

**Правило:** порт публикуется наружу только у того, к кому реально ходят из интернета.
Всё остальное общается внутри пользовательской сети по именам.

---

## 5. Диагностика сети

```bash
# Что где
docker network ls
docker network inspect app-net --format '{{json .Containers}}' | jq .
docker inspect web --format '{{range $n,$c := .NetworkSettings.Networks}}{{$n}}={{$c.IPAddress}} {{end}}'
docker port web

# Изнутри контейнера
docker exec app ip a
docker exec app ip route
docker exec app cat /etc/resolv.conf
docker exec app getent hosts db
docker exec app sh -c 'ss -tlnp || netstat -tlnp'      # что слушает приложение
docker exec app wget -qO- http://db:5432 2>&1 | head -1

# Контейнер без сетевых утилит — берём их из другого контейнера
docker run --rm --network container:app nicolaka/netshoot ss -tlnp
docker run --rm --network app-net nicolaka/netshoot dig db
docker run --rm --network app-net nicolaka/netshoot curl -s http://app:8000/health

# С хоста
sudo iptables -t nat -L DOCKER -n | head
ss -tlnp | grep -E '8080|docker'
sudo nsenter -t $(docker inspect -f '{{.State.Pid}}' app) -n ss -tlnp
```

### Алгоритм «контейнер не отвечает»

```text:no-line-numbers
1. Контейнер вообще работает?          docker ps / docker logs
2. Приложение слушает?                 docker exec c ss -tlnp
3. Слушает 0.0.0.0 или 127.0.0.1?      ⭐ 127.0.0.1 внутри = снаружи НЕДОСТУПНО
4. Порт опубликован?                   docker port c   / docker ps (колонка PORTS)
5. Достучаться изнутри сети:           docker run --rm --network net alpine wget -qO- http://c:port
6. Достучаться с хоста:                curl 127.0.0.1:8080
7. Правильная сеть?                    docker inspect / обе стороны в одной сети?
8. DNS резолвится?                     docker exec c getent hosts other
9. Файрвол/iptables                    sudo iptables -t nat -L DOCKER -n
```

> **Ошибка №1 у новичков:** приложение слушает `127.0.0.1:8000` внутри контейнера.
> Внутри контейнера `localhost` — это сам контейнер, снаружи туда не попасть даже с `-p`.
> Приложение должно слушать **`0.0.0.0`**.
>
> **Ошибка №2:** в конфиге приложения `DB_HOST=localhost`. Внутри контейнера `localhost` —
> это он сам, а не база в соседнем контейнере. Нужно имя сервиса: `DB_HOST=db`.

---

## 6. overlay и macvlan (обзорно)

```bash
# overlay — несколько хостов, нужен Swarm или внешний KV-store
docker swarm init
docker network create -d overlay --attachable app-overlay
docker service create --name web --network app-overlay -p 80:80 nginx
# В Kubernetes эту роль играет CNI-плагин (Calico, Cilium, Flannel)

# macvlan — контейнер получает IP в физической сети
docker network create -d macvlan \
  --subnet=192.168.1.0/24 --gateway=192.168.1.1 \
  -o parent=eth0 lan-net
docker run -d --name legacy --network lan-net --ip 192.168.1.50 nginx
# ⚠️ Хост НЕ сможет достучаться до такого контейнера напрямую (особенность macvlan),
#    и многие облака/Wi-Fi не пропускают чужие MAC-адреса.
```

---

## 💼 Как это в DevOps

- В compose (тема 09) всё это делается декларативно, а сеть создаётся автоматически,
  и **сервисы резолвятся по именам** — понимание этой темы объясняет, почему оно работает.
- **Безопасность:** не публикуй БД наружу. `-p 5432:5432` на сервере с публичным IP —
  это инцидент, а не конфигурация. Помни про обход UFW.
- В **Kubernetes** модель другая (под = свой IP, Service, CoreDNS, CNI), но базовая логика
  «имя сервиса вместо IP» — та же.
- `nicolaka/netshoot` — обязательный инструмент: контейнер со всеми сетевыми утилитами,
  который подключается в namespace проблемного контейнера.

---

## 🧪 Мини-лаба: сети руками

```bash
# 1. Дефолтная сеть: DNS по имени НЕ работает
docker run -d --name a1 alpine sleep 600
docker run -d --name a2 alpine sleep 600
docker exec a2 ping -c1 a1 2>&1 | head -1          # bad address
docker exec a2 ping -c1 $(docker inspect -f '{{.NetworkSettings.IPAddress}}' a1)  # по IP работает
docker rm -f a1 a2

# 2. Пользовательская сеть: DNS работает
docker network create app-net
docker run -d --name a1 --network app-net alpine sleep 600
docker run -d --name a2 --network app-net alpine sleep 600
docker exec a2 ping -c1 a1                          # ✅ по имени
docker exec a2 cat /etc/resolv.conf                 # nameserver 127.0.0.11
docker exec a2 getent hosts a1

# 3. Изоляция сетей
docker network create other-net
docker run -d --name b1 --network other-net alpine sleep 600
docker exec a2 ping -c1 -W1 b1 2>&1 | head -1       # не видит
docker network connect other-net a2                  # подключили вторую сеть
docker exec a2 ping -c1 b1                           # ✅ теперь видит
docker exec a2 ip a | grep inet                      # два интерфейса

# 4. Публикация портов и прослушивание 0.0.0.0
docker run -d --name web -p 8080:80 nginx:alpine
curl -sI localhost:8080 | head -1
docker port web
sudo iptables -t nat -L DOCKER -n | grep 8080
docker exec web sh -c 'netstat -tlnp 2>/dev/null | head -3'

# приложение на 127.0.0.1 внутри контейнера — недоступно снаружи
docker run -d --name loop -p 8081:8000 python:3.12-alpine \
  python -m http.server 8000 --bind 127.0.0.1
sleep 2; curl -s --max-time 3 localhost:8081 || echo "❌ недоступно — слушает 127.0.0.1"
docker rm -f loop
docker run -d --name ok -p 8081:8000 python:3.12-alpine python -m http.server 8000 --bind 0.0.0.0
sleep 2; curl -s --max-time 3 localhost:8081 >/dev/null && echo "✅ доступно — слушает 0.0.0.0"
docker rm -f ok

# 5. Только localhost хоста
docker run -d --name safe -p 127.0.0.1:8082:80 nginx:alpine
curl -sI localhost:8082 | head -1
ss -tlnp | grep 8082                                # слушает только 127.0.0.1 ✅
docker rm -f safe

# 6. host и none
docker run -d --name h --network host nginx:alpine
ss -tlnp | grep ':80 '                              # nginx на порту 80 ХОСТА
docker exec h ip a | grep -c inet                   # интерфейсы = хостовые
docker rm -f h
docker run --rm --network none alpine ip a          # только lo
docker run --rm --network none alpine ping -c1 -W1 8.8.8.8 2>&1 | head -1

# 7. Трёхзвенка: nginx → app → db с изолированной сетью БД
docker network create frontend-net
docker network create --internal backend-net
docker run -d --name db --network backend-net -e POSTGRES_PASSWORD=pw postgres:16-alpine
docker run -d --name app --network backend-net python:3.12-alpine \
  sh -c 'python -m http.server 8000 --bind 0.0.0.0'
docker network connect frontend-net app
cat > /tmp/proxy.conf <<'EOF'
server {
  listen 80;
  location / { proxy_pass http://app:8000; }
}
EOF
docker run -d --name nginx --network frontend-net -p 8080:80 \
  -v /tmp/proxy.conf:/etc/nginx/conf.d/default.conf:ro nginx:alpine
sleep 2
curl -s localhost:8080 | head -3                    # ✅ через прокси в app
docker exec app ping -c1 db                         # ✅ app видит db
docker exec nginx ping -c1 -W1 db 2>&1 | head -1    # ❌ nginx НЕ видит db
docker exec db ping -c1 -W1 8.8.8.8 2>&1 | head -1  # ❌ internal-сеть без интернета
docker ps --format 'table {{.Names}}\t{{.Ports}}'   # порты только у nginx

# 8. netshoot — диагностика без утилит в образе
docker run --rm --network backend-net nicolaka/netshoot dig +short db
docker run --rm --network container:app nicolaka/netshoot ss -tlnp

# 9. Уборка
docker rm -f nginx app db web a1 a2 b1 2>/dev/null
docker network rm app-net other-net frontend-net backend-net 2>/dev/null
rm -f /tmp/proxy.conf
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `docker network ls` | Список сетей |
| `docker network create NET` | Создать пользовательскую bridge-сеть |
| `docker network create --internal NET` | Сеть без выхода в интернет |
| `docker network inspect NET` | Подсеть, шлюз, участники |
| `docker network connect/disconnect NET C` | Подключить/отключить контейнер |
| `docker network prune` | Удалить неиспользуемые сети |
| `--network NET` | Подключить при запуске |
| `--network host / none / container:NAME` | Стек хоста / без сети / стек другого контейнера |
| `-p 127.0.0.1:8080:80` | Публикация только на localhost ⭐ |
| `-P` | Опубликовать все EXPOSE-порты |
| `--add-host=host.docker.internal:host-gateway` | Доступ к хосту по имени |
| `--network-alias NAME` | Дополнительное DNS-имя в сети |
| `docker port C` | Проброшенные порты |
| `docker exec C ss -tlnp` | Что слушает приложение |
| `docker run --rm --network container:C nicolaka/netshoot …` | Полный сетевой тулкит |
| `sudo iptables -t nat -L DOCKER -n` | Правила DNAT докера |

---

## 🧠 Что запомнить

1. Дефолтная сеть — **bridge (`docker0`)** + NAT. `-p` создаёт правило **DNAT** в iptables.
2. В **дефолтной** bridge-сети DNS по именам контейнеров **не работает**;
   в **пользовательской** — работает. Всегда создавай свою сеть.
3. Внутри контейнера DNS — `127.0.0.11` (embedded DNS докера).
4. `localhost` внутри контейнера — это **сам контейнер**, а не хост и не соседний контейнер.
5. Приложение должно слушать **`0.0.0.0`**, иначе `-p` не поможет.
6. `EXPOSE` ничего не публикует — публикует `-p` при запуске.
7. `-p 8080:80` открывает порт **всему миру** и **обходит UFW**. Для локального —
   `-p 127.0.0.1:8080:80`.
8. БД и внутренние сервисы **не публикуют** наружу: общение по именам во внутренней сети.
9. `--internal` — сеть без доступа в интернет, хороший вариант для БД.
10. `host` — без изоляции и NAT (быстро, но конфликты портов); `none` — без сети.
11. `overlay` — мультихост (Swarm); `macvlan` — контейнер с собственным IP в физической LAN.
12. Диагностика: `ss -tlnp` внутри → `docker port` → пинг по имени → `iptables -t nat`,
    и `nicolaka/netshoot`, когда в образе нет утилит.

---

## Задачи

> Полезный инструмент: `docker run --rm --network <net> nicolaka/netshoot <команда>`
> Уборка: `docker rm -f $(docker ps -aq); docker network prune -f`

---

### Блок A. Теория

**A1.** Что происходит при `docker run -p 8080:80 nginx` на уровне сети хоста? Опиши путь пакета.

<details><summary>Ответ</summary>

Докер создаёт для контейнера сетевой namespace, veth-пару (один конец в контейнере как
`eth0`, другой — в bridge `docker0`), выдаёт IP из подсети bridge. `-p 8080:80` добавляет в
iptables (таблица nat, цепочка DOCKER) правило DNAT: пакет на порт 8080 хоста переписывается
в `172.17.0.2:80` и уходит через bridge в контейнер. Ответ уходит обратно с обратной трансляцией.
Исходящий трафик контейнера наружу маскарадится под адрес хоста.

</details>

**A2.** Назови 5 типов сетей докера и когда какой применять. *(типы из роадмапа)*

<details><summary>Ответ</summary>

`bridge` — виртуальный коммутатор с NAT, дефолт для одного хоста;
`host` — стек хоста напрямую (нет изоляции и NAT);
`none` — только loopback;
`overlay` — L2-сеть поверх нескольких хостов (VXLAN), Swarm;
`macvlan` — собственный MAC/IP в физической сети;
(+ `ipvlan` — то же с общим MAC).

</details>

**A3.** Главное отличие дефолтной сети `bridge` от пользовательской. Почему это критично?

<details><summary>Ответ</summary>

В дефолтной `bridge` нет автоматического DNS по именам контейнеров — общаться можно
только по IP (или устаревшим `--link`). В пользовательской сети работает embedded DNS: имена
контейнеров резолвятся автоматически. Критично, потому что IP контейнера меняется при
пересоздании, а имя — нет.

</details>

**A4.** Что такое embedded DNS и какой у него адрес? Что он резолвит?

<details><summary>Ответ</summary>

Встроенный DNS-сервер докера на `127.0.0.11` внутри контейнера. Резолвит имена
контейнеров, сетевые алиасы (`--network-alias`), имена сервисов compose; остальные запросы
пересылает во внешние резолверы хоста.

</details>

**A5.** Почему приложение должно слушать `0.0.0.0`, а не `127.0.0.1`?

<details><summary>Ответ</summary>

`127.0.0.1` внутри контейнера — это loopback **самого контейнера**; пакет, пришедший
через veth/DNAT, приходит на `eth0` контейнера и до сокета, привязанного к loopback, не доходит.
Слушать надо `0.0.0.0` (все интерфейсы).

</details>

**A6.** Что означает `localhost` внутри контейнера? Как контейнеру обратиться к соседнему
контейнеру и к хосту?

<details><summary>Ответ</summary>

`localhost` — сам контейнер. К соседнему контейнеру — по его имени/алиасу в общей
пользовательской сети (`http://app:8000`). К хосту — `host.docker.internal`
(с `--add-host=host.docker.internal:host-gateway` на Linux) или IP шлюза сети
(обычно `172.17.0.1`).

</details>

**A7.** `EXPOSE 8080` в Dockerfile и `-p 8080:8080` при запуске — в чём разница?

<details><summary>Ответ</summary>

`EXPOSE` — только метаданные образа (документация + список для `-P`). `-p` реально
создаёт правило DNAT и публикует порт на хосте. Без `-p`/`-P` наружу ничего не доступно.

</details>

**A8.** Почему `-p 5432:5432` на сервере с публичным IP — это инцидент безопасности?
Причём тут UFW?

<details><summary>Ответ</summary>

Порт становится доступен всему интернету. Правила докера попадают в цепочки
`DOCKER`/`nat PREROUTING`, которые обрабатываются **раньше** правил UFW (`ufw-input`),
поэтому «UFW всё закрыл» не защищает. Решение: публиковать на `127.0.0.1`, не публиковать
БД вовсе, писать правила в `DOCKER-USER`.

</details>

**A9.** Что делает `--network host`? Какие плюсы и какие риски?

<details><summary>Ответ</summary>

Контейнер использует сетевой стек хоста: его интерфейсы, порты, iptables. Плюсы:
нет NAT и veth — минимальная задержка и максимальная пропускная способность, удобно для
приложений с множеством портов и сетевых утилит. Риски: нет сетевой изоляции, конфликты портов
с хостом и другими контейнерами, приложение видит все интерфейсы хоста; `-p` игнорируется.

</details>

**A10.** Зачем нужна сеть `--internal`?

<details><summary>Ответ</summary>

Чтобы контейнеры в ней не имели доступа в интернет и не были доступны извне —
только внутренняя коммуникация. Типично для БД и внутренних сервисов: даже при компрометации
приложение не сможет выгрузить данные наружу напрямую.

</details>

**A11.** Что такое `veth pair` и `docker0`?

<details><summary>Ответ</summary>

`veth pair` — пара связанных виртуальных интерфейсов: один конец внутри сетевого
namespace контейнера (`eth0`), другой на хосте, воткнут в мост. `docker0` — программный
L2-мост (коммутатор), объединяющий эти интерфейсы и выступающий шлюзом для контейнеров.

</details>

**A12.** Как контейнер выходит в интернет? Что такое MASQUERADE в этом контексте?

<details><summary>Ответ</summary>

Через шлюз `docker0` и правило **MASQUERADE** (SNAT) в iptables: исходный адрес
контейнера подменяется адресом хоста, ответы транслируются обратно. Поэтому снаружи
трафик контейнера выглядит как трафик хоста.

</details>

**A13.** Что такое overlay-сеть и где она применяется?

<details><summary>Ответ</summary>

Сеть поверх нескольких хостов (VXLAN-туннели): контейнеры на разных машинах
оказываются в одной L2-сети и общаются по именам. Применяется в Docker Swarm;
в Kubernetes аналогичную задачу решает CNI (Calico, Cilium, Flannel).

</details>

**A14.** Что такое macvlan и какое у него известное ограничение?

<details><summary>Ответ</summary>

Контейнер получает собственный MAC и IP прямо в физической сети — выглядит как
отдельная машина в LAN. Ограничение: **хост не может обратиться к своему macvlan-контейнеру**
напрямую (нужен дополнительный macvlan-интерфейс на хосте); многие Wi-Fi-сети и облачные
провайдеры блокируют «чужие» MAC.

</details>

**A15.** Что делает `--network container:NAME`? Где это используют?

<details><summary>Ответ</summary>

Контейнер использует **сетевой namespace другого контейнера**: общий IP, порты,
интерфейсы. Используется для sidecar-паттернов и диагностики
(`--network container:app` + netshoot). Так же устроены поды в Kubernetes.

</details>

**A16.** Как дать одному контейнеру несколько сетей и зачем это нужно?

<details><summary>Ответ</summary>

`docker network connect <net> <container>` (или несколько сетей в compose).
Нужно для сегментации: например, `app` одновременно во frontend-сети (общается с nginx)
и в backend-сети (общается с БД), при этом nginx и БД друг друга не видят.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  docker network create --driver bridge --subnet 172.28.0.0/16 app-net
B2.  docker network create --internal db-net
B3.  docker run -d --network app-net --name db postgres:16
B4.  docker network connect frontend-net app
B5.  docker run -d -p 127.0.0.1:8080:80 nginx
B6.  docker run -d -P nginx
B7.  docker run --rm --network none alpine ip a
B8.  docker run -d --network host nginx
B9.  docker run --rm --network container:web nicolaka/netshoot ss -tlnp
B10. docker exec app cat /etc/resolv.conf
B11. docker port web
B12. docker network inspect app-net --format '{{json .Containers}}'
B13. docker run --add-host=host.docker.internal:host-gateway alpine ping -c1 host.docker.internal
B14. sudo iptables -t nat -L DOCKER -n
B15. docker run -d --network app-net --network-alias api myapp
```

**B1.** Создать bridge-сеть с явно заданной подсетью.
**B2.** Создать сеть без доступа в интернет и извне.
**B3.** Запустить postgres в пользовательской сети — его смогут звать по имени `db`.
**B4.** Подключить работающий контейнер `app` ко второй сети.
**B5.** Опубликовать порт только на loopback хоста (недоступно извне).
**B6.** Опубликовать все `EXPOSE`-порты на случайные свободные порты хоста.
**B7.** Контейнер без сети: виден только `lo`.
**B8.** nginx занимает порт 80 самого хоста, без NAT и изоляции.
**B9.** Запустить тулкит в сетевом namespace контейнера `web` и посмотреть, что он слушает.
**B10.** Показать DNS-настройки контейнера (`nameserver 127.0.0.11`).
**B11.** Показать соответствие опубликованных портов.
**B12.** Список контейнеров в сети с их IP.
**B13.** Проверить доступность хоста по имени `host.docker.internal` (Linux — через host-gateway).
**B14.** Показать правила DNAT, созданные докером при публикации портов.
**B15.** Дать контейнеру дополнительное DNS-имя `api` внутри сети.

**B17.** Чем `docker exec c ping db` отличается от `docker run --rm --network app-net alpine ping db`
с точки зрения диагностики?

<details><summary>Ответ</summary>

`docker exec` проверяет связность **из самого контейнера** (его DNS, маршруты,
сетевые namespace, а также наличие утилит в образе). Запуск отдельного контейнера в той же
сети проверяет **саму сеть**, независимо от состояния проблемного контейнера, и работает,
даже если в его образе нет ping/curl. Оба нужны: первый локализует проблему в контейнере,
второй — в сети.

</details>

---

### Блок C. Практика

#### C1. 🔑 Трёхзвенка с изоляцией (главное задание)

Подними схему: `nginx (reverse proxy) → app → postgres`, где:
- `nginx` в сети `frontend-net`, опубликован порт 8080 → 80;
- `app` в **обеих** сетях (`frontend-net` и `backend-net`);
- `postgres` **только** в `backend-net`, которая создана с `--internal`;
- nginx проксирует `/` на `http://app:8000`;
- ни у `app`, ни у `db` нет опубликованных портов.

Докажи:
1. `curl localhost:8080` работает и отдаёт ответ приложения.
2. `app` резолвит и пингует `db` по имени.
3. `nginx` **не видит** `db`.
4. `db` **не имеет** выхода в интернет.
5. `db` недоступен с хоста напрямую (`curl localhost:5432` — ничего).
6. Покажи IP-адреса всех контейнеров и их сети одной командой.

<details><summary>Ответ</summary>

```bash
docker network create frontend-net
docker network create --internal backend-net

docker run -d --name db --network backend-net -e POSTGRES_PASSWORD=pw postgres:16-alpine
docker run -d --name app --network backend-net python:3.12-alpine \
  sh -c 'echo "<h1>app ok</h1>" > index.html; python -m http.server 8000 --bind 0.0.0.0'
docker network connect frontend-net app

cat > /tmp/proxy.conf <<'EOF'
server { listen 80; location / { proxy_pass http://app:8000; } }
EOF
docker run -d --name nginx --network frontend-net -p 8080:80 \
  -v /tmp/proxy.conf:/etc/nginx/conf.d/default.conf:ro nginx:alpine
sleep 2

curl -s localhost:8080                                    # 1) ответ приложения
docker exec app ping -c1 db                               # 2) ✅
docker exec nginx ping -c1 -W1 db 2>&1 | head -1          # 3) ❌ bad address
docker exec db ping -c1 -W1 8.8.8.8 2>&1 | head -1        # 4) ❌ нет интернета
curl -s --max-time 2 localhost:5432 || echo "5) db с хоста недоступен ✅"
docker ps --format '{{.Names}}' | while read c; do
  printf "%-8s %s\n" "$c" "$(docker inspect $c --format '{{range $n,$cfg := .NetworkSettings.Networks}}{{$n}}={{$cfg.IPAddress}} {{end}}')"
done                                                       # 6)
```

</details>

#### C2. DNS: дефолтная сеть vs своя

1. Запусти два контейнера в дефолтной сети — покажи, что по имени они друг друга не находят,
   а по IP — находят.
2. Повтори в пользовательской сети — покажи, что имя резолвится.
3. Посмотри `/etc/resolv.conf` внутри обоих случаев.
4. Добавь контейнеру сетевой алиас и проверь, что он резолвится тоже.

<details><summary>Ответ</summary>

```bash
docker run -d --name d1 alpine sleep 600
docker run -d --name d2 alpine sleep 600
docker exec d2 ping -c1 -W1 d1 2>&1 | head -1              # bad address
docker exec d2 ping -c1 $(docker inspect -f '{{.NetworkSettings.IPAddress}}' d1) | head -1
docker exec d2 cat /etc/resolv.conf
docker rm -f d1 d2

docker network create n1
docker run -d --name u1 --network n1 alpine sleep 600
docker run -d --name u2 --network n1 --network-alias api alpine sleep 600
docker exec u1 ping -c1 u2 | head -1                        # ✅
docker exec u1 ping -c1 api | head -1                       # ✅ алиас
docker exec u1 cat /etc/resolv.conf                         # 127.0.0.11
docker rm -f u1 u2; docker network rm n1
```

</details>

#### C3. 0.0.0.0 vs 127.0.0.1

1. Запусти `python -m http.server` с `--bind 127.0.0.1` и пробросом порта — покажи, что снаружи
   недоступно, а `docker exec ... wget localhost` изнутри работает.
2. Перезапусти с `--bind 0.0.0.0` — покажи, что заработало.
3. Объясни, где именно рвётся цепочка в первом случае.

<details><summary>Ответ</summary>

```bash
docker run -d --name bad -p 8081:8000 python:3.12-alpine python -m http.server 8000 --bind 127.0.0.1
sleep 2
curl -s --max-time 3 localhost:8081 || echo "снаружи недоступно"
docker exec bad wget -qO- http://localhost:8000 | head -1   # изнутри работает
docker rm -f bad
docker run -d --name good -p 8081:8000 python:3.12-alpine python -m http.server 8000 --bind 0.0.0.0
sleep 2; curl -s --max-time 3 localhost:8081 >/dev/null && echo "работает ✅"; docker rm -f good
# Цепочка рвётся на последнем шаге: DNAT доставил пакет на eth0 контейнера (172.17.x.x),
# но сокет привязан к 127.0.0.1 и такие пакеты не принимает.
```

</details>

#### C4. Публикация портов и безопасность

1. Запусти nginx с `-p 8080:80` и с `-p 127.0.0.1:8081:80`.
2. Через `ss -tlnp` покажи разницу в адресах прослушивания.
3. Найди правила DNAT в iptables для обоих.
4. (Если есть вторая машина/VM) проверь доступность обоих портов извне.
5. Сформулируй правило, которое будешь применять на серверах.

<details><summary>Ответ</summary>

```bash
docker run -d --name p1 -p 8080:80 nginx:alpine
docker run -d --name p2 -p 127.0.0.1:8081:80 nginx:alpine
ss -tlnp | grep -E '8080|8081'          # 0.0.0.0:8080 vs 127.0.0.1:8081
sudo iptables -t nat -L DOCKER -n | grep -E '8080|8081'
docker rm -f p1 p2
# Правило: наружу публикуем только реальные точки входа (reverse proxy),
# всё остальное — на 127.0.0.1 или вообще без публикации.
```

</details>

#### C5. host и none

1. Запусти nginx в `--network host`, найди его порт на хосте, объясни, почему `-p` не нужен.
2. Попробуй запустить второй такой же — что произойдёт?
3. Запусти контейнер в `--network none` и покажи, что интернета нет.
4. Назови по одному реальному применению для каждого режима.

<details><summary>Ответ</summary>

```bash
docker run -d --name h1 --network host nginx:alpine
ss -tlnp | grep ':80 '                 # процесс nginx на порту 80 ХОСТА
docker run -d --name h2 --network host nginx:alpine; sleep 2
docker logs h2 | tail -2               # address already in use → контейнер падает
docker rm -f h1 h2
docker run --rm --network none alpine ping -c1 -W1 8.8.8.8 2>&1 | head -1
# host: высоконагруженные сетевые сервисы, мониторинг-агенты (node_exporter), сетевые утилиты.
# none: обработка данных/сборка, где сеть не нужна и её лучше запретить.
```

</details>

#### C6. Подключение и отключение сетей на лету

1. Создай две сети и контейнер в первой.
2. Покажи, что он не видит контейнер во второй.
3. Подключи его ко второй сети без перезапуска, покажи два интерфейса и успешный пинг.
4. Отключи обратно.

<details><summary>Ответ</summary>

```bash
docker network create net-a; docker network create net-b
docker run -d --name ca --network net-a alpine sleep 600
docker run -d --name cb --network net-b alpine sleep 600
docker exec ca ping -c1 -W1 cb 2>&1 | head -1       # bad address
docker network connect net-b ca
docker exec ca ip -o a | grep -c inet               # два интерфейса (+lo)
docker exec ca ping -c1 cb | head -1                # ✅
docker network disconnect net-b ca
docker rm -f ca cb; docker network rm net-a net-b
```

</details>

#### C7. Диагностика без утилит в образе

Возьми образ без сетевых утилит (например, `gcr.io/distroless/static` или обычный `nginx:alpine`
без `curl`) и выясни:
1. Что он слушает (через netshoot в его network namespace).
2. Как резолвится имя другого контейнера (через `dig` из netshoot).
3. Сделай то же самое через `nsenter` с хоста.

<details><summary>Ответ</summary>

```bash
docker network create diag
docker run -d --name web --network diag nginx:alpine
docker run -d --name svc --network diag alpine sleep 600
docker run --rm --network container:web nicolaka/netshoot ss -tlnp
docker run --rm --network diag nicolaka/netshoot dig +short web
PID=$(docker inspect -f '{{.State.Pid}}' web)
sudo nsenter -t $PID -n ss -tlnp
docker rm -f web svc; docker network rm diag
```

</details>

#### C8. Доступ к хосту из контейнера

1. Запусти на хосте простой HTTP-сервер на порту 9000.
2. Достучись до него из контейнера тремя способами: через `host.docker.internal`,
   через IP шлюза docker0, через `--network host`.

<details><summary>Ответ</summary>

```bash
python3 -m http.server 9000 --bind 0.0.0.0 >/dev/null 2>&1 &
HPID=$!
docker run --rm --add-host=host.docker.internal:host-gateway alpine \
  sh -c 'wget -qO- http://host.docker.internal:9000 | head -2'
GW=$(docker run --rm alpine ip route | awk '/default/{print $3}')
docker run --rm alpine sh -c "wget -qO- http://$GW:9000 | head -2"
docker run --rm --network host alpine sh -c 'wget -qO- http://127.0.0.1:9000 | head -2'
kill $HPID
```

</details>

---

### Блок D. Инциденты

**D1.** Приложение в контейнере не может подключиться к БД: `could not connect to server: Connection
refused`, хотя контейнер с БД работает. В конфиге `DB_HOST=localhost`. Диагноз?

<details><summary>Ответ</summary>

`localhost` внутри контейнера приложения — это сам контейнер, там БД нет.
Нужно обращаться по **имени контейнера/сервиса** (`DB_HOST=db`) и убедиться, что оба
контейнера в одной пользовательской сети. Проверка: `docker exec app getent hosts db`.

</details>

**D2.** Веб-приложение отвечает на `docker exec app curl localhost:8000`, но `curl localhost:8080`
с хоста висит. Порт проброшен. Три причины.

<details><summary>Ответ</summary>

(1) Приложение слушает `127.0.0.1` внутри контейнера вместо `0.0.0.0`;
(2) порт проброшен на другой порт/интерфейс (`docker port` покажет реальную привязку);
(3) приложение слушает не тот порт, который указан в `-p` (например, слушает 3000, а пробросили
на 8000); (4) файрвол хоста/облачная security group; (5) контейнер в `--network none`
или в host-режиме с другим портом.

</details>

**D3.** На сервере с UFW «всё закрыто», но снаружи открыт порт Redis из контейнера,
и его зашифровали вымогатели. Как это возможно и что делать?

<details><summary>Ответ</summary>

Контейнер запустили с `-p 6379:6379`, докер добавил правило DNAT в `nat PREROUTING`,
которое отрабатывает **до** правил UFW (фильтрация в `INPUT`), поэтому UFW ничего не блокирует.
Действия: немедленно убрать публикацию (`-p 127.0.0.1:6379:6379` или без публикации),
поднять пароль/ACL Redis, проверить компрометацию данных, добавить правило в `DOCKER-USER`
(`iptables -I DOCKER-USER -i eth0 ! -s <доверенная сеть> -j DROP`), пересмотреть все
публикации на сервере (<code v-pre>docker ps --format '{{.Names}} {{.Ports}}'</code>).

</details>

**D4.** Два контейнера в одной пользовательской сети, но `ping` по имени выдаёт
«bad address». Что проверить? (Четыре варианта.)

<details><summary>Ответ</summary>

(1) Контейнеры на самом деле в разных сетях (`docker inspect`) — частая причина:
один в дефолтной bridge; (2) опечатка в имени/контейнер переименован; (3) целевой контейнер
остановлен (имя перестаёт резолвиться); (4) в compose обращаются к имени контейнера, а не к
имени сервиса; (5) в образе нет ping/getent, и «bad address» — вводящая в заблуждение ошибка
busybox; проверить через netshoot.

</details>

**D5.** После `docker compose down` и `up` приложение перестало находить БД,
хотя ничего не меняли. Где могла сломаться связность?

<details><summary>Ответ</summary>

При `down` сеть удаляется и создаётся заново; контейнеры получают новые IP.
Если приложение кэширует IP (или в конфиге прописан старый IP, а не имя сервиса) — связь рвётся.
Также могло измениться имя сети/проекта (каталог переименован) или сервис теперь в другой сети.
Решение: обращаться по именам сервисов, не хардкодить IP.

</details>

**D6.** Контейнер не может разрешить внешние имена (`google.com`), хотя по IP пингует.
Причины и решение.

<details><summary>Ответ</summary>

Проблема DNS: неверный `/etc/resolv.conf` (унаследован от хоста с недоступным
резолвером, например `127.0.0.53` systemd-resolved), блокировка порта 53, некорректный
`dns` в `daemon.json`. Решения: задать DNS явно (`--dns 1.1.1.1` или `"dns"` в
`/etc/docker/daemon.json`), проверить резолвер хоста, `docker exec c cat /etc/resolv.conf`.

</details>

**D7.** У контейнера в `--network host` не стартует приложение: `bind: address already in use`.
Объясни.

<details><summary>Ответ</summary>

В host-режиме контейнер занимает порт **самого хоста**: либо этот порт уже занят
процессом хоста/другим контейнером в host-режиме, либо запущено два таких контейнера.
Изоляции портов нет — это ожидаемое поведение host-сети.

</details>

**D8.** После создания нескольких сетей `docker network create` падает с
`could not find an available, non-overlapping IPv4 address pool`. Что произошло?

<details><summary>Ответ</summary>

Исчерпан пул адресов для bridge-сетей (по умолчанию докер нарезает подсети из
`172.17.0.0/12` и т.п.) — накопилось слишком много неудалённых сетей. Решение:
`docker network prune`, удалить неиспользуемые сети, при необходимости расширить пул
в `/etc/docker/daemon.json` (`default-address-pools`).

</details>

**D9.** Приложение периодически теряет соединения с БД, в логах — таймауты через 5 минут
простоя. Соединение внутри docker-сети. Что может быть причиной?

<details><summary>Ответ</summary>

Простаивающие соединения рвёт conntrack/NAT: записи в таблице отслеживания соединений
истекают (по умолчанию `nf_conntrack_tcp_timeout_established` большой, но у промежуточных
узлов/облака бывает 5 минут), и пакеты после простоя не доходят. Лечение: включить TCP keepalive
в приложении/драйвере БД (`tcp_keepalives_idle`), настроить пул соединений с проверкой живости
и `max_lifetime`, при необходимости — параметры conntrack на хосте.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Какие типы сетей есть в докере?

<details><summary>Ответ</summary>

bridge, host, none, overlay, macvlan (+ipvlan).

</details>

**2.** Как работает сеть в докере по умолчанию?

<details><summary>Ответ</summary>

Контейнер получает veth в мост `docker0`, IP из его подсети, выход в интернет через
MASQUERADE; публикация портов — правилами DNAT в iptables.

</details>

**3.** Чем пользовательская сеть отличается от дефолтной bridge?

<details><summary>Ответ</summary>

В пользовательской сети работает DNS по именам контейнеров и есть изоляция от других сетей;
в дефолтной bridge — нет DNS, все контейнеры в общей сети.

</details>

**4.** Как контейнеры общаются между собой?

<details><summary>Ответ</summary>

По именам контейнеров/сервисов внутри общей пользовательской сети (embedded DNS 127.0.0.11).

</details>

**5.** Что делает `-p 8080:80`?

<details><summary>Ответ</summary>

Создаёт DNAT-правило: порт 8080 хоста перенаправляется на порт 80 контейнера.

</details>

**6.** В чём разница `EXPOSE` и `-p`?

<details><summary>Ответ</summary>

`EXPOSE` — документация в метаданных образа; `-p` — фактическая публикация порта.

</details>

**7.** Как контейнеру обратиться к хосту?

<details><summary>Ответ</summary>

`host.docker.internal` (на Linux — с `--add-host=host.docker.internal:host-gateway`)
или по IP шлюза сети докера.

</details>

**8.** Что такое overlay-сеть?

<details><summary>Ответ</summary>

Сеть поверх нескольких хостов на базе VXLAN, используется в Swarm; позволяет контейнерам
на разных машинах быть в одной L2-сети.

</details>

**9.** Почему нельзя публиковать порт БД наружу?

<details><summary>Ответ</summary>

Порт становится доступен всему интернету, при этом правила докера обходят UFW;
БД должна быть доступна только внутренней сети контейнеров.

</details>

**10.** Как диагностировать сетевую проблему в контейнере?

<details><summary>Ответ</summary>

`docker ps/logs` → `docker exec ss -tlnp` (слушает ли и на каком адресе) → `docker port` →
проверка резолва имени → пробный запрос из контейнера в той же сети (netshoot) →
`iptables -t nat -L DOCKER` → файрвол хоста/облака.

</details>

---

### 🎯 Чек-лист

- [ ] Объясняю, что делает `-p` на уровне iptables
- [ ] Всегда создаю пользовательскую сеть вместо дефолтной
- [ ] Помню про `0.0.0.0` и про то, что `localhost` — это сам контейнер
- [ ] Не публикую порты БД наружу и знаю про обход UFW
- [ ] Собрал трёхзвенку с `--internal` сетью для БД
- [ ] Умею подключать контейнер к нескольким сетям
- [ ] Диагностирую сеть через netshoot и nsenter
- [ ] Знаю, что такое overlay и macvlan и когда они нужны
