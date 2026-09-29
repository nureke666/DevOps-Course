---
title: "07. Практика: 6 лаб по распределённым системам"
description: "Блок → Распределённые системы → практика. Лабы делаются руками в ~/labs/distributed/"
---

# 07. Практика: 6 лаб по распределённым системам

> Блок → Распределённые системы → практика. Лабы делаются руками в `~/labs/distributed/`
> (стенд — в [00_INDEX.md](/distributed/)) и остаются в git. После них на собесе есть что показать:
> свои цифры failover'а etcd и Patroni, воспроизведённый split brain, посчитанные потери Kafka при
> `acks=1`, ключ идемпотентности и outbox, которые выдержали `kill -9`.
>
> Механика лаб 1, 2, 4 и мини-лабы темы 06 прогнана на стенде (сентябрь 2026): etcd 3.6.15,
> Patroni 4.1.5 из репозитория PGDG поверх `postgres:17`, HAProxy 3.2, Apache Kafka 4.3.1 (KRaft).
> Теги в compose — **проверь** свежие перед стартом. Цифры «ожидаемо» — ориентир с того прогона:
> у тебя будут свои, важны порядок и объяснение.

---

## 📋 Список лаб

| № | Лаба | Темы | Артефакт |
|---|------|------|----------|
| 1 | ⭐ etcd из 3 узлов: отказы, разделение 1 \| 2, задержка и латентность записи | 01, 04 | таблица замеров + объяснение каждой цифры |
| 2 | ⭐ Patroni ×3 + etcd + HAProxy: failover, отрезать primary от DCS, `failsafe_mode`, split brain без watchdog | 04, 06 | хронология failover'а, воспроизведённый split brain и его цена |
| 3 | Дрейф часов на `web`/`app`: chrony-топология, TTL-блокировка по часам клиента, fencing-токен | 05 | скрипты воркеров, «было/стало» |
| 4 | ⭐ Kafka ×3 (KRaft): `acks=1` против `acks=all` + `min.insync.replicas=2` при убийстве лидера | 02, 03, 06 | число потерянных подтверждённых сообщений |
| 5 | Ретраи без идемпотентности → дубли; ключ идемпотентности в копии linkd | 06 | патч + тест-скрипт, который его проверяет |
| 6 | Transactional outbox: PostgreSQL → relay → Kafka → консьюмер с дедупликацией | 06 | relay + консьюмер, пережившие `kill -9` |

Общее для всех лаб:
```bash
mkdir -p ~/labs/distributed && cd ~/labs/distributed && git init 2>/dev/null
docker compose version                       # v2
# задержки и разделения — из sidecar-контейнера netshoot в сетевом неймспейсе узла:
#   network_mode: "service:&lt;узел&gt;" + cap_add: [NET_ADMIN]
# ⚠️ перезапустил узел — пересоздай его sidecar: docker compose up -d --force-recreate chaosN
#    (иначе sidecar остаётся в старом неймспейсе: «Cannot find device eth0»)
```text
---

## 🧪 Лаба 1. ⭐ etcd из 3 узлов под отказами и разделением сети

### Цель
Расширить мини-лабу темы 04: разделить кластер 1 | 2 и увидеть, что пишет только большинство;
**померить** латентность записи, когда задержка на фолловере и когда на лидере; довести
задержку до выборов нового лидера.

### Темы
[04_consensus_quorum.md](/distributed/04-consensus-quorum) (Raft, кворум, выборы, таймауты etcd),
[01_fallacies_basics.md](/distributed/01-fallacies-basics) (задержка ≠ отказ, таймауты).

### Стенд
```bash
mkdir -p ~/labs/distributed/lab1 && cd ~/labs/distributed/lab1
IMG=quay.io/coreos/etcd:v3.6.15              # проверь тег (образ distroless: внутри нет sh)
{
echo "services:"
for i in 1 2 3; do cat <&lt;EOF
  etcd$i:
    image: $IMG
    command:&gt;-
      etcd --name etcd$i --data-dir /etcd-data
      --listen-peer-urls http://0.0.0.0:2380 --initial-advertise-peer-urls http://etcd$i:2380
      --listen-client-urls http://0.0.0.0:2379 --advertise-client-urls http://etcd$i:2379
      --initial-cluster etcd1=http://etcd1:2380,etcd2=http://etcd2:2380,etcd3=http://etcd3:2380
      --initial-cluster-token lab1 --initial-cluster-state new
  chaos$i:                                   # tc и iptables в неймспейсе etcd$i
    image: nicolaka/netshoot                 # проверь тег
    network_mode: "service:etcd$i"
    cap_add: [NET_ADMIN]
    command: sleep infinity
EOF
done
cat <<'EOF'
  client:                                    # отсюда меряем: curl к JSON-шлюзу etcd
    image: nicolaka/netshoot
    command: sleep infinity
EOF
} > compose.yaml
docker compose up -d && sleep 5
EP=etcd1:2379,etcd2:2379,etcd3:2379
st() { docker compose exec -T etcd1 etcdctl --endpoints=$EP endpoint status -w table; }
st                                           # IS LEADER, RAFT TERM
```text
Латентность записи меряем без накладных `docker exec` — curl к HTTP/JSON-шлюзу etcd
(`/v3/kv/put`, ключ и значение в base64: `eA==` = `x`):
```bash
cat > lat.sh <<'EOF'
# lat.sh &lt;endpoint&gt; [n] — p50/p99/max времени put в мс
ep=$1; n=${2:-50}
for i in $(seq $n); do
  curl -s -o /dev/null -w '%{time_total}\n' -X POST "http://$ep/v3/kv/put" -d '{"key":"bGF0","value":"eA=="}'
done | sort -n | awk '{a[NR]=$1*1000} END {printf "n=%d p50=%.1fms p99=%.1fms max=%.1fms\n", NR, a[int(NR*0.5)], a[int(NR*0.99)], a[NR]}'
EOF
docker compose cp lat.sh client:/lat.sh
lat() { docker compose exec -T client sh /lat.sh "$@"; }
```text
### Шаги
1. **База.** Найди лидера (`st`), затем `lat &lt;лидер&gt;:2379` и `lat &lt;фолловер&gt;:2379`.
   Ожидаемо: единицы миллисекунд (на прогоне p50 ≈ 1,2 мс) через любой узел.
2. **Задержка 100 мс на фолловере** (`docker compose exec -T chaosN tc qdisc add dev eth0 root netem delay 100ms`).
   Повтори замеры через лидера и через этот фолловер. Ожидаемо: через лидера — **без изменений**
   (кворум — лидер + второй быстрый фолловер); через медленный фолловер ≈ +300 мс (задержка
   исходящих пакетов этого узла: ответ на рукопожатие TCP, пересылка запроса лидеру, ответ клиенту).
   Убери: `tc qdisc del dev eth0 root`.
3. **Задержка 100 мс на лидере.** Через лидера ≈ +300 мс, через фолловер ≈ +200 мс. Объясни, на каких
   шагах Raft появляется каждая сотня: лидер обязан разослать запись и дождаться большинства.
4. **Задержка 1500 мс на лидере** — больше `--election-timeout` (1000 мс). Через ~5–10 с `st`:
   лидер другой, `RAFT TERM` вырос. В логах фолловеров — `lost leader … elected leader`. Сними
   задержку: лидерство **не** возвращается старому узлу само.
5. ⭐ **Разделение 1 | 2 — отрезаем лидера** (от соседей, но не от клиента):
   ```bash
   N=&lt;номер лидера&gt;
   docker compose exec -T chaos$N sh -c 'for h in etcd1 etcd2 etcd3; do [ $h = etcd'$N' ] && continue
     ip=$(getent hosts $h | cut -d" " -f1); iptables -A INPUT -s $ip -j DROP; iptables -A OUTPUT -d $ip -j DROP; done'
   # запись через узел большинства — раз в 0,1 с, таймаут 1 с: сколько запросов не прошло?
   docker compose exec -T client sh -c 'for i in $(seq 30); do curl -s -m 1 -o /dev/null -w "%{http_code} " \
     -X POST http://&lt;узел большинства&gt;:2379/v3/kv/put -d "{\"key\":\"eA==\",\"value\":\"eQ==\"}"; sleep 0.1; done; echo'
   # запись и чтения через отрезанного старого лидера
   docker compose exec -T client curl -s -m 10 -w ' %{http_code}\n' -X POST http://etcd$N:2379/v3/kv/put -d '{"key":"eA==","value":"eg=="}'
   docker compose exec -T client curl -s -m 10 -w ' %{http_code}\n' -X POST http://etcd$N:2379/v3/kv/range -d '{"key":"eA=="}'
   docker compose exec -T client curl -s -m 10 -w ' %{http_code}\n' -X POST http://etcd$N:2379/v3/kv/range -d '{"key":"eA==","serializable":true}'
   ```
   Ожидаемо: через большинство — 1–2 неудачи (`000`) и дальше `200`: новый лидер за ~1–2 с.
   Старый лидер: запись — через ~7 с `504 context deadline exceeded`; линеаризуемое чтение —
   `503 etcdserver: request timed out`; **serializable-чтение — `200` со старыми данными** (в
   заголовке ответа старый `raft_term`).
6. **Разделение 1 | 2 — отрезаем фолловер.** Запись через большинство не замечает; через
   отрезанный фолловер — таймаут. Верни сеть (`iptables -F`), через несколько секунд `st`: термы
   у всех одинаковые, `RAFT INDEX` догнал.

### Сломай сам
- Отрежь **каждый** узел от каждого (три меньшинства): никто не пишет, `st` — `no leader`.
- Джиттер вместо задержки на лидере: `netem delay 700ms 400ms` — посчитай смены лидера за минуту
  (`curl -s etcdN:2379/metrics | grep leader_changes_seen_total` из `client`). Это «флапающий
  лидер» из инцидентов темы 04.
- `etcdctl check perf` при задержке 100 мс на лидере — какой пункт проверки провалится и почему?

### Критерии
- [ ] Таблица: база, задержка на фолловере (через лидера / через фолловер), задержка на лидере,
      время появления нового лидера при разделении, рост терма
- [ ] Для каждой цифры — объяснение в терминах Raft (кто кого ждёт)
- [ ] Показано, что отрезанный старый лидер **не подтвердил** ни одной записи, но отдал устаревшее
      serializable-чтение; объяснено, когда `--consistency=s` допустим

### Уборка
`docker compose down -v`

---

## 🧪 Лаба 2. ⭐ Patroni ×3 + etcd + HAProxy: failover и попытка split brain

### Цель
Увидеть failover Patroni своими глазами и **хронологию** решений; отрезать primary от DCS и
убедиться, что двух primary не бывает; понять `failsafe_mode`; воспроизвести split brain, от
которого защищает watchdog, и увидеть, какие данные он съедает.

### Темы
[04_consensus_quorum.md](/distributed/04-consensus-quorum) (Patroni + DCS), [06_failure_modes.md](/distributed/06-failure-modes) §1,
[../Storage/06_db_backup_replication.md](/storage/06-db-backup-replication) §9 (Patroni в эксплуатации).

### Стенд
```dockerfile
# Dockerfile — PostgreSQL 17 + Patroni из репозитория PGDG (он уже подключён в образе postgres)
FROM postgres:17
RUN apt-get update \
 && apt-get install -y --no-install-recommends patroni python3-etcd iproute2 iptables curl \
 && rm -rf /var/lib/apt/lists/*
USER postgres
ENTRYPOINT ["patroni", "/etc/patroni.yml"]
```text
```yaml
# patroni.yml — общий для узлов; имя и адреса — через PATRONI_* в compose
scope: shop-pg
restapi: { listen: 0.0.0.0:8008 }
bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 1048576
    postgresql:
      use_pg_rewind: true
      parameters: { wal_log_hints: "on" }
  pg_hba:
    - local all all trust
    - host replication replicator 0.0.0.0/0 scram-sha-256
    - host all all 0.0.0.0/0 scram-sha-256
postgresql:
  listen: 0.0.0.0:5432
  data_dir: /var/lib/postgresql/data/pg
  bin_dir: /usr/lib/postgresql/17/bin
  authentication:
    superuser:   { username: postgres,   password: postgres }
    replication: { username: replicator, password: replicator }
    rewind:      { username: rewinder,   password: rewinder }
watchdog: { mode: off }        # в контейнере /dev/watchdog нет; на VM — modprobe softdog и mode: required
```text
```text
# haproxy.cfg — 5000 → только текущий primary (проверка /primary на REST API Patroni)
global
    maxconn 200
defaults
    mode tcp
    timeout connect 3s
    timeout client 30m
    timeout server 30m
listen stats
    mode http
    bind *:7000
    stats enable
    stats uri /
listen primary
    bind *:5000
    option httpchk GET /primary
    http-check expect status 200
    default-server inter 2s fall 2 rise 2 on-marked-down shutdown-sessions
    server pg1 pg1:5432 check port 8008
    server pg2 pg2:5432 check port 8008
    server pg3 pg3:5432 check port 8008
```text
```bash
mkdir -p ~/labs/distributed/lab2 && cd ~/labs/distributed/lab2   # сюда три файла выше
{
echo "services:"
for i in 1 2 3; do cat <&lt;EOF
  etcd$i:
    image: quay.io/coreos/etcd:v3.6.15       # проверь тег
    command:&gt;-
      etcd --name etcd$i --data-dir /etcd-data
      --listen-peer-urls http://0.0.0.0:2380 --initial-advertise-peer-urls http://etcd$i:2380
      --listen-client-urls http://0.0.0.0:2379 --advertise-client-urls http://etcd$i:2379
      --initial-cluster etcd1=http://etcd1:2380,etcd2=http://etcd2:2380,etcd3=http://etcd3:2380
      --initial-cluster-token lab2 --initial-cluster-state new
EOF
done
for i in 1 2 3; do cat <&lt;EOF
  pg$i:
    build: .
    image: lab-patroni:17
    hostname: pg$i
    cap_add: [NET_ADMIN]                     # для iptables внутри узла
    environment:
      PATRONI_NAME: pg$i
      PATRONI_ETCD3_HOSTS: etcd1:2379,etcd2:2379,etcd3:2379
      PATRONI_RESTAPI_CONNECT_ADDRESS: pg$i:8008
      PATRONI_POSTGRESQL_CONNECT_ADDRESS: pg$i:5432
    volumes: [ "./patroni.yml:/etc/patroni.yml:ro" ]
    depends_on: [etcd1, etcd2, etcd3]
EOF
done
cat <<'EOF'
  haproxy:
    image: haproxy:3.2-alpine                # проверь тег
    volumes: [ "./haproxy.cfg:/usr/local/etc/haproxy/haproxy.cfg:ro" ]
    ports: [ "127.0.0.1:15000:5000", "127.0.0.1:17000:7000" ]
    depends_on: [pg1, pg2, pg3]
EOF
}&gt; compose.yaml
docker compose up -d --build && sleep 25
pl() { docker compose exec -T "${1:-pg1}" patronictl -c /etc/patroni.yml list; }
pl                                            # Leader + 2 × streaming, TL 1
```text
«Писатель» — раз в 0,5 с вставляет строку через HAProxy и пишет в лог `ok &lt;адрес сервера&gt;` или `FAIL`
(живёт в контейнере реплики pg3; если pg3 станет лидером — это нормально):
```bash
docker compose exec -T -e PGPASSWORD=postgres pg3 psql -h haproxy -p 5000 -U postgres \
  -c "CREATE TABLE t (id bigserial PRIMARY KEY, src text, at timestamptz DEFAULT now())"
docker compose exec -d -T -e PGPASSWORD=postgres pg3 sh -c 'while true; do
  if psql -h haproxy -p 5000 -U postgres -tAq -c "insert into t(src) values (inet_server_addr()::text) returning src" >/tmp/w 2>&1
  then echo "$(date +%T) ok $(cat /tmp/w)"; else echo "$(date +%T) FAIL $(head -c 100 /tmp/w)"; fi; sleep 0.5; done >/tmp/writer.log'
wlog()  { docker compose exec -T pg3 sh -c "awk '{print \$1, \$2, \$3}' /tmp/writer.log | uniq -c -f1"; }  # сводка ok/FAIL
wreset(){ docker compose exec -T pg3 sh -c ': > /tmp/writer.log'; }
rec()   { for n in pg1 pg2 pg3; do printf "%s:%s " $n "$(docker compose exec -T $n psql -U postgres -tAc 'select pg_is_in_recovery()' 2>&1 | head -c 40)"; done; echo; }
```text
### Шаги
1. **Switchover** (плановый): `patronictl switchover shop-pg --leader &lt;лидер&gt; --candidate &lt;реплика&gt; --force`,
   `wlog`. Ожидаемо: несколько FAIL за пару секунд.
2. **Failover: чистая остановка против `kill -9`.** `wreset; docker compose stop &lt;лидер&gt;`, через
   25 с `wlog`, затем `start`. Потом `wreset; docker kill &lt;контейнер лидера&gt;`, через 45 с `wlog`.
   Ожидаемо: `stop` — ~5 с ошибок (Patroni при остановке **сам снимает** лидер-ключ); `kill` —
   ~30 с (ключ живёт до `ttl`). Объясни разницу и какое из двух — настоящая авария.
3. ⭐ **Отрезать primary от DCS** (но не от реплик и HAProxy):
   ```bash
   P=&lt;лидер&gt;; wreset
   docker compose exec -T -u root $P sh -c 'for h in etcd1 etcd2 etcd3; do ip=$(getent hosts $h | cut -d" " -f1)
     iptables -A OUTPUT -d $ip -j DROP; iptables -A INPUT -s $ip -j DROP; done'; date -u +%T
   for i in $(seq 10); do sleep 6; rec; done
   docker compose logs $P --since 90s | grep -i -E 'demot|lock|DCS'
   wlog; pl &lt;реплика&gt;
   ```
   Ожидаемо (прогон): ~T+20 с — `demoting self because DCS is not accessible and I was a leader`
   (следующий цикл + `retry_timeout`); ~T+28 с — новый лидер (ключ истёк: последнее продление + `ttl`);
   у писателя ~10 с FAIL (сначала `read-only transaction`, потом HAProxy без primary); **ни в
   один момент `rec` не показал двух `f`**. Верни сеть (`iptables -F`): старый primary
   возвращается репликой на новом timeline (при расхождении — `pg_rewind`).
4. **`failsafe_mode`.** `patronictl edit-config -s failsafe_mode=true --force`, повтори шаг 3.
   Ожидаемо: primary **остаётся** primary (`continue to run as a leader because failsafe mode is
   enabled and all members are accessible`), реплики принимают `POST /failsafe`, у писателя 0 FAIL.
   Теперь дополнительно отрежь primary от **одной** реплики: он demote'ится (кого-то не видно), а
   failover на прогоне занял ~40 с — дольше, чем без failsafe. Верни `failsafe_mode=false`.

### Сломай сам — ⭐ split brain без watchdog
Заморозь **Patroni** (не PostgreSQL) на лидере. Patroni, запущенный как PID 1, форкает рабочий
процесс — морозить нужно его:
```bash
P=&lt;лидер&gt;
docker compose exec -T $P sh -c 'ps -o pid,stat,args | grep [p]atroni'      # PID 1 и рабочий (не 1)
docker compose exec -T $P sh -c 'kill -STOP $(pgrep -f bin/patroni | grep -v "^1$" | head -1)'
for i in $(seq 9); do sleep 6; rec; done                                     # через ~ttl — ДВА «f»
docker compose exec -T -e PGPASSWORD=postgres pg3 psql -h $P -U postgres -tAc \
  "insert into t(src) values ('direct-to-old-primary') returning id"          # прямая запись: ПРОХОДИТ
docker compose exec -T -e PGPASSWORD=postgres pg3 psql -h haproxy -p 5000 -U postgres -tAc \
  "insert into t(src) values ('via-haproxy') returning id, inet_server_addr()" # уходит на НОВЫЙ primary
docker compose exec -T $P sh -c 'kill -CONT $(pgrep -f bin/patroni | grep -v "^1$" | head -1)'
sleep 40; docker compose logs $P --since 45s | grep -i -E 'demot|rewind'
docker compose exec -T -e PGPASSWORD=postgres pg3 psql -h haproxy -p 5000 -U postgres -tAc \
  "select id, src from t where src = 'direct-to-old-primary'"                 # ?
```text
Ожидаемо: через ~30 с реплика стала лидером, а старый PostgreSQL **всё ещё primary** и принимает
прямые записи — два primary. HAProxy защитил тех, кто ходит через него (REST API замороженного
Patroni не отвечает — узел выпал из пула). После `CONT` старый узел видит чужой ключ, делает
`Demoting self (immediate-nolock)` и `pg_rewind` — **строка `direct-to-old-primary` исчезает**.
Ответь: когда перезагрузил бы узел watchdog (`ttl − safety_margin` = 25 с после последнего
продления) и почему это **раньше**, чем истечёт ключ.

Ещё: DCS из двух узлов etcd (убери etcd3 из `PATRONI_ETCD3_HOSTS` и останови его, потом останови
etcd2) — что станет с primary, когда DCS потеряет кворум?

### Критерии
- [ ] Хронология шага 3 с временами: разрыв → demote → новый лидер → первая успешная запись
- [ ] Объяснено, почему окно без primary есть, а окна с двумя нет (`loop_wait + 2 × retry_timeout ≤ ttl`)
- [ ] Разница `stop` и `kill -9` объяснена через лидер-ключ
- [ ] `failsafe_mode`: когда спасает, чем платим
- [ ] Split brain воспроизведён, потерянная строка показана, роль watchdog объяснена; записан вывод
      «клиенты ходят к primary только через проверку роли (HAProxy `/primary`, `target_session_attrs`)»

### Уборка
`docker compose down -v` (образ `lab-patroni:17` пригодится для задач темы 04 и 06)

---

## 🧪 Лаба 3. Дрейф часов на `web`/`app`: chrony, TTL-блокировка, fencing-токен

### Цель
Выстроить правильную топологию времени, увидеть мониторинг под chrony, а главное — сломать
**корректность**: «блокировку», которая считает срок по часам клиента, и починить её временем базы
и fencing-токеном.

### Темы
[05_time_ordering.md](/distributed/05-time-ordering) (мини-лаба с TLS, JWT и логами — сделай её первой).

### Стенд
`net-lab` (`~/Projects/devops/stands/net-lab/Vagrantfile`): `web` 192.168.56.10,
`app` 192.168.56.11; `vagrant snapshot save before_clock`. На `web` — PostgreSQL из apt (Ubuntu
22.04 даст 14-ю версию — для лабы годится), слушает `192.168.56.10`, в `pg_hba.conf` —
`host lab lab 192.168.56.0/24 scram-sha-256`; на `app` — `postgresql-client`.

```sql
-- на web: sudo -u postgres psql
CREATE ROLE lab LOGIN PASSWORD 'lab'; CREATE DATABASE lab OWNER lab;
\c lab lab
CREATE TABLE locks    (name text PRIMARY KEY, owner text, expires_at bigint NOT NULL DEFAULT 0, fence bigint NOT NULL DEFAULT 0);
CREATE TABLE work_log (id bigserial, owner text, token bigint, at timestamptz DEFAULT now());   -- время БД — одна точка
CREATE TABLE report   (id int PRIMARY KEY, content text, fence bigint NOT NULL DEFAULT 0);
INSERT INTO locks (name) VALUES ('report'); INSERT INTO report VALUES (1, '', 0);
```text
### Шаги
1. **Топология времени.** `web` — NTP-сервер для `app` (задача C2 темы 05): на `app` один
   источник `^* 192.168.56.10`. На обеих — `prometheus-node-exporter` из apt; проверь
   `node_timex_sync_status` и `node_timex_offset_seconds` (под chrony offset, скорее всего, 0 —
   запиши, какой метрикой ты бы на самом деле алертил).
2. **Неправильная блокировка.** Напиши `lock-worker.sh &lt;имя&gt;` (bash + psql), который в цикле раз
   в 2 с пытается взять/продлить блокировку `report` **по своим часам**: `expires_at` = `date +%s`
   + 20, условие захвата — «`expires_at` меньше моего `now` или владелец — я». Держатель пишет
   строку в `work_log` раз в цикл. Запусти воркер на `web` и на `app`.
   Проверка: `SELECT owner, count(*) FROM work_log WHERE at > now() - interval '1 minute' GROUP BY owner`
   — при синхронных часах пишет **один** владелец.
3. **Сдвинь часы `app` на +60 с** (`systemctl stop chrony; date -s '+60 seconds'`). Ожидаемо: оба
   воркера пишут в `work_log` в одну и ту же минуту — `app` «видит» чужую блокировку истёкшей
   каждый раз. Взаимного исключения нет, и ни одной ошибки в логах.
4. **Починка 1 — время одной точки.** Перепиши захват так, чтобы срок считала база (`now()` в SQL,
   `expires_at` — `timestamptz`). Повтори шаг 3: сдвиг часов клиента больше ни на что не влияет.
5. **Починка 2 — fencing-токен.** Смена владельца увеличивает `fence` (`RETURNING fence` — это
   токен); запись в `report` проходит только с токеном не меньше записанного:
   `UPDATE report SET content = …, fence = $token WHERE id = 1 AND fence <= $token`.
   Смоделируй паузу держателя: `kill -STOP` воркера на `web` на 40 с (больше TTL) → `app` берёт
   блокировку с токеном +1 и пишет → `kill -CONT` на `web` → его запись со старым токеном даёт
   `UPDATE 0`, воркер это видит и прекращает работу.
6. Верни время: `chronyd -q` / `systemctl start chrony`, `chronyc tracking`.

### Сломай сам
- «Синхронны, но неверны»: на `web` отключи внешние источники, оставь `local stratum 8` и сдвинь
  его часы на 5 минут. `app` послушно синхронизируется, `sync_status` = 1 на обеих, а TLS с
  внешним миром ломается. Какой мониторинг поймал бы это? (Подсказка: сравнение с независимым
  источником, `chronyc sources` с 2–3 внешними серверами и `^x`.)
- `maxdistance 0.0001` на `app` — chrony откажется синхронизироваться; как это выглядит в
  `chronyc tracking` и в метриках?

### Критерии
- [ ] Воспроизведено нарушение взаимного исключения из-за сдвига часов — без единой ошибки в логах
- [ ] Починка 1 и 2 работают; объяснено, почему починка 1 не спасает от паузы процесса, а 2 — спасает
- [ ] Для fencing показано: проверку делает **хранилище** (`report`), а не воркер
- [ ] Записан алерт, который реально сработает под chrony

### Уборка
`vagrant snapshot restore before_clock` (или остановить воркеры, `systemctl start chrony` на обеих)

---

## 🧪 Лаба 4. ⭐ Kafka ×3 (KRaft): `acks=1` против `acks=all` при убийстве лидера

### Цель
Посчитать, сколько **подтверждённых** сообщений теряется при `acks=1`, когда умирает лидер
партиции, и убедиться, что с `acks=all` + `min.insync.replicas=2` + RF 3 — ноль. Попутно увидеть,
что «ошибка у продюсера» не значит «не записано».

### Темы
[03_replication_partitioning.md](/distributed/03-replication-partitioning) (ISR, лаг), [02_consistency_cap.md](/distributed/02-consistency-cap),
[06_failure_modes.md](/distributed/06-failure-modes) §8 и §12, [../Left/05_Queues/02_kafka_basics.md](/queues/02-kafka-basics) §6.

### Стенд
```bash
mkdir -p ~/labs/distributed/lab4 && cd ~/labs/distributed/lab4
{
echo "x-kafka: &kafka"; echo "  image: apache/kafka:4.3.1          # проверь тег"; echo "services:"
for i in 1 2 3; do cat <&lt;EOF
  kafka$i:
    <<: *kafka
    hostname: kafka$i
    environment:
      CLUSTER_ID: 5L6g3nShT-eMCtK--X86sw           # один на кластер (kafka-storage.sh random-uuid)
      KAFKA_NODE_ID: $i
      KAFKA_PROCESS_ROLES: broker,controller       # каждый узел — и брокер, и контроллер KRaft
      KAFKA_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka$i:9092
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
      KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka1:9093,2@kafka2:9093,3@kafka3:9093
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 3
      KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 3
      KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 2
      KAFKA_UNCLEAN_LEADER_ELECTION_ENABLE: "false"
      KAFKA_LOG_DIRS: /var/lib/kafka/data
  chaos$i:                                         # в образе Kafka нет tc — задержки отсюда
    image: nicolaka/netshoot
    network_mode: "service:kafka$i"
    cap_add: [NET_ADMIN]
    command: sleep infinity
EOF
done
cat <<'EOF'
  tools:                                           # клиенты живут отдельно: лидера убиваем, а не их
    image: apache/kafka:4.3.1
    entrypoint: ["sleep", "infinity"]
EOF
}&gt; compose.yaml
docker compose up -d && sleep 20
K=/opt/kafka/bin; BS=kafka1:9092,kafka2:9092,kafka3:9092
docker compose exec -T tools $K/kafka-metadata-quorum.sh --bootstrap-server $BS describe --status   # LeaderId, CurrentVoters: 3
```text
### Шаги
Эксперимент одной функцией: свежий топик (1 партиция, RF 3, `min.insync.replicas=2`), задержка
200 мс на фолловерах (чтобы они отставали), `kafka-verifiable-producer.sh` пишет 60 000 сообщений
со скоростью 5000/с и логирует **каждое подтверждение**, на 6-й секунде `docker kill` лидера,
потом брокер возвращается, консьюмер вычитывает всё, `comm` сравнивает множества.
```bash
run() {  # run &lt;топик&gt; &lt;acks: 1 | -1&gt;   (verifiable-producer принимает только число; -1 = all)
  docker compose exec -T tools $K/kafka-topics.sh --bootstrap-server $BS --create --topic $1 \
    --partitions 1 --replication-factor 3 --config min.insync.replicas=2 >/dev/null
  L=$(docker compose exec -T tools $K/kafka-topics.sh --bootstrap-server $BS --describe --topic $1 |
      awk '/Leader:/{for(i=1;i<=NF;i++) if($i=="Leader:") print $(i+1)}'); echo "topic=$1 acks=$2 leader=$L"
  for f in 1 2 3; do [ $f != $L ] && docker compose exec -T chaos$f tc qdisc add dev eth0 root netem delay 200ms; done
  docker compose exec -T tools sh -c "$K/kafka-verifiable-producer.sh --bootstrap-server $BS --topic $1 \
    --max-messages 60000 --throughput 5000 --acks $2 > /tmp/$1.log 2>/tmp/$1.err" &
  sleep 6; docker kill "$(docker compose ps -q kafka$L)" >/dev/null; echo "killed kafka$L"; wait
  for f in 1 2 3; do docker compose exec -T chaos$f tc qdisc del dev eth0 root 2>/dev/null; done
  docker compose start kafka$L >/dev/null; sleep 15; docker compose up -d --force-recreate chaos$L >/dev/null 2>&1
  docker compose exec -T tools sh -c "grep tool_data /tmp/$1.log
    $K/kafka-console-consumer.sh --bootstrap-server $BS --topic $1 --from-beginning --timeout-ms 15000 2>/dev/null > /tmp/$1.raw
    sort -u /tmp/$1.raw > /tmp/$1.read
    grep producer_send_success /tmp/$1.log | sed 's/.*\"value\":\"\([0-9]*\)\".*/\1/' | sort -u > /tmp/$1.acked
    echo read=\$(wc -l < /tmp/$1.raw) unique=\$(wc -l < /tmp/$1.read) \
         lost_acked=\$(comm -23 /tmp/$1.acked /tmp/$1.read | wc -l) \
         failed_but_present=\$(comm -13 /tmp/$1.acked /tmp/$1.read | wc -l)"
}
run t-acks1 1
run t-acksall -1
```text
1. Выполни `run` для `acks=1` два-три раза (каждый раз новый топик). Ожидаемо: `lost_acked` > 0 —
   на прогоне 30 и 579: лидер подтвердил, фолловеры не успели скопировать, новый лидер из ISR
   их не знает, вернувшийся старый **обрезает** свой лог по новому лидеру.
2. `run` для `acks=-1`. Ожидаемо: `lost_acked=0`. Зато у продюсера тысячи ошибок
   (`producer_send_error`, на прогоне ~5000), и `failed_but_present` > 0 (~1000): продюсер
   считал запись неудачной, а она в логе. Это «таймаут не говорит, выполнилось ли» из темы 01 —
   отсюда идемпотентный продюсер и дедупликация.
3. `read` против `unique`: есть ли дубли? Почему их нет, хотя были ошибки? (Подсказка:
   verifiable-producer ставит `retries=0` — в исходниках «No producer retries», — и
   идемпотентность из-за конфликта настроек выключается сама.) Что изменилось бы с ретраями без
   идемпотентности?
4. **`min.insync.replicas` в деле.** Создай топик и останови **два** брокера из трёх. Продюсер
   `--acks -1` получает `NOT_ENOUGH_REPLICAS`, `--acks 1` продолжает писать — и что с этими
   записями будет при потере оставшегося брокера?
5. Посмотри `--describe`: колонки `Isr`, `Elr` (eligible leader replicas, KIP-966 — поведение в 4.x
   **проверь** по документации своей версии).

### Сломай сам
- `unclean.leader.election.enable=true` на топике, RF 3, `min.insync.replicas=1`: останови оба
  фолловера, попиши в лидера, останови лидера, подними **сначала** фолловеры. Кто станет лидером
  и что будет с записями, которые лидер успел подтвердить? Это сценарий Jepsen 2013
  ([06_failure_modes.md](/distributed/06-failure-modes) §12). (С ELR в 4.x выбор лидера мог измениться — проверь.)
- Повтори `run t-x 1` без задержки на фолловерах: потерь меньше или ноль — почему «на стенде не
  теряется» ничего не доказывает?

### Критерии
- [ ] Таблица: `acks`, `acked`, `lost_acked`, `failed_but_present` по каждому прогону
- [ ] Объяснено, откуда потери при `acks=1` (подтверждение до репликации + обрезка лога) и почему
      их нет при `acks=all` + `min.insync.replicas=2`
- [ ] Объяснено, почему `failed_but_present` > 0 и что из этого следует для консьюмеров
- [ ] Записана «надёжная» конфигурация с ценой каждого параметра (задержка, доступность записи)

### Уборка
`docker compose down -v`

---

## 🧪 Лаба 5. Ретраи без идемпотентности → дубли; ключ идемпотентности в linkd

### Цель
Под нагрузкой получить дубли от ретраев неидемпотентного `POST /api/links`, затем **самому**
добавить ключ идемпотентности в копию linkd и доказать тестом, что дублей больше нет — ни при
ретраях, ни при параллельных повторах, ни после рестарта сервиса.

### Темы
[06_failure_modes.md](/distributed/06-failure-modes) §7 и мини-лаба, [../SRE/06_reliability_patterns.md](/sre/06-reliability-patterns) §2–3.

### Стенд
Как в мини-лабе темы 06, но код — **копия** (репозиторий `~/Projects/devops` не трогаем):
```bash
mkdir -p ~/labs/distributed/lab5/app && cd ~/labs/distributed/lab5
cp ~/Projects/devops/09-ledger/app/linkd.py app/ && git -C .. add lab5 2>/dev/null
# compose.yaml — из мини-лабы темы 06, но volume: ./app:/app:ro; порт 127.0.0.1:18480
```text
### Шаги
1. **Дубли под нагрузкой.** Напиши `dupes.sh`: 20 параллельных клиентов, каждый создаёт ссылку на
   свой URL (`https://example.kz/n-$i`) с `curl --max-time 1 --retry 3`; одновременно в фоне
   держится `LOCK TABLE links IN SHARE MODE` на 4 с. Проверка:
   `SELECT url, count(*) FROM links WHERE url LIKE '%/n-%' GROUP BY url HAVING count(*) > 1` —
   дубли есть; сравни с тем, сколько 201 увидели клиенты.
2. **Реализуй ключ идемпотентности** в `app/linkd.py`. Требования:
   - заголовок `Idempotency-Key` необязателен; без него — старое поведение;
   - таблица ключей создаётся при старте рядом с `links` (схема — из темы 06 §7), ключ уникален
     в рамках клиента (заголовок `X-Client-Id`, по умолчанию `anonymous`);
   - отпечаток запроса — хеш нормализованного тела;
   - запись ключа, создание ссылки и сохранение ответа — **одна транзакция** (в linkd это один
     `with DB() as d:`);
   - повтор с тем же ключом и телом → тот же статус и тело (тот же `code`) + заголовок
     `Idempotent-Replayed: true`; тот же ключ, другое тело → `422`;
   - метрика `linkd_idempotent_replays_total` в `/metrics`;
   - чистка ключей старше 24 часов (отдельной командой или при старте — реши и обоснуй).
3. **Тест `idem-test.sh`** (он и есть критерий приёмки):
   ```
   a) 20 параллельных POST с одним ключом          → в БД 1 строка, у всех 20 ответов один code
   b) шаг 1, но у каждого клиента свой ключ         → ни одного URL с count > 1
   c) тот же ключ, другой URL                       → 422
   d) POST без ключа дважды                         → 2 разных code (старое поведение)
   e) ключ K → docker compose restart linkd → K     → тот же code (состояние в БД, не в памяти)
   ```
4. Посмотри логи linkd в тесте a): сколько раз реально выполнился `INSERT INTO links`?

### Сломай сам
- Храни ключи в словаре Python в памяти процесса и подними **две** реплики linkd за nginx — тест
  a) снова даёт дубли. Почему?
- Сделай «проверить → вставить» без уникального ограничения (`SELECT` ключа, потом `INSERT`) —
  тест a) при параллельных запросах иногда падает. Найди гонку.
- Раздели транзакции: ключ — в одной, ссылка — в другой. Убей linkd (`docker kill`) между ними
  (вставь `time.sleep(5)` для окна) — что стало с ключом и что получит повтор?

### Критерии
- [ ] Дубли без ключа воспроизведены и посчитаны
- [ ] `idem-test.sh` проходит все пять пунктов; код ревьюится построчно («почему здесь одна транзакция»)
- [ ] В README лабы: почему ключ хранится в той же БД, что и ссылки, и сколько его хранить
- [ ] Для «сломай сам» — объяснение каждого провала

### Уборка
`docker compose down -v`

---

## 🧪 Лаба 6. Transactional outbox: PostgreSQL → relay → Kafka → консьюмер с дедупликацией

### Цель
Построить outbox для событий `LinkCreated`: запись данных и события — одной транзакцией, relay
публикует в Kafka, консьюмер считает статистику **ровно один раз по эффекту**, даже когда relay и
консьюмер убивают `kill -9` в худший момент.

### Темы
[06_failure_modes.md](/distributed/06-failure-modes) §8–9, [../Left/05_Queues/01_queues_concepts.md](/queues/01-queues-concepts) §3–4,
[../Left/05_Queues/03_kafka_ops.md](/queues/03-kafka-ops) (CLI).

### Стенд
PostgreSQL (`postgres:17-alpine`, для бонуса с CDC — `command: postgres -c wal_level=logical`),
Kafka — одноузловой из [../Left/05_Queues/00_INDEX.md](/queues/) или три брокера из лабы 4
(тогда топик с RF 3 и `min.insync.replicas=2`), два своих сервиса на `python:3.12-slim` с
`psycopg[binary]` и `confluent-kafka` (**проверь** версии пакетов).
```sql
CREATE TABLE links  (code text PRIMARY KEY, url text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE outbox (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  aggregatetype text NOT NULL,              -- имена колонок как у Debezium Outbox Event Router
  aggregateid   text NOT NULL,              -- → ключ сообщения → порядок по ссылке
  type          text NOT NULL,
  payload       jsonb NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  published_at  timestamptz
);
CREATE INDEX outbox_unpublished ON outbox (created_at) WHERE published_at IS NULL;
-- у консьюмера (можно та же база, другая схема):
CREATE TABLE processed  (msg_id uuid PRIMARY KEY, processed_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE link_stats (day date PRIMARY KEY, created bigint NOT NULL DEFAULT 0);
```text
### Шаги (требования)
1. **Писатель** (скрипт или `psql`): каждая ссылка — `INSERT links` + `INSERT outbox` в одной
   транзакции (`type = 'LinkCreated'`, в `payload` — code и url).
2. **Relay** (`relay.py`): в цикле `BEGIN` → `SELECT … WHERE published_at IS NULL ORDER BY created_at
   LIMIT 100 FOR UPDATE SKIP LOCKED` → отправить в топик `outbox.event.link` с ключом `aggregateid`
   и заголовком `id` (продюсер: `acks=all`, идемпотентность включена) → дождаться подтверждений
   (`flush`) → `UPDATE … SET published_at = now()` → `COMMIT`. Переменная `CRASH_AFTER_SEND=1` —
   упасть (`os._exit(1)`) после `flush`, до `COMMIT`.
3. **Консьюмер** (`stats.py`): группа `link-stats`, `enable.auto.commit=false`; на сообщение —
   одна транзакция: `INSERT INTO processed … ON CONFLICT DO NOTHING RETURNING` → если вставилось,
   `link_stats.created + 1` за день → `COMMIT`; **потом** коммит оффсета. Переменная
   `CRASH_BEFORE_OFFSET=1` — упасть между `COMMIT` в базе и коммитом оффсета.
4. **Проверки:**
   ```
   a) Kafka остановлена → писатель работает, outbox растёт; Kafka вернулась → relay всё дослал
      (метрики relay: число неопубликованных и возраст самого старого — это и есть «лаг outbox»)
   b) CRASH_AFTER_SEND=1 → в топике дубли (посчитай по заголовку id: kafka-console-consumer
      --property print.headers=true), а sum(link_stats.created) = count(links) — эффект один раз
   c) CRASH_BEFORE_OFFSET=1 → повторная доставка после рестарта, счётчик не удвоился
   d) два relay одновременно → партии не пересекаются (SKIP LOCKED), доставка всё равно at-least-once
   e) порядок: события одного aggregateid в топике идут в порядке created_at (одна партиция)
   ```
5. Инвариант приёмки после любых падений: `SELECT count(*) FROM links` =
   `SELECT sum(created) FROM link_stats` = `SELECT count(*) FROM processed`.

### Сломай сам
- Dual write вместо outbox: писатель коммитит ссылку, потом шлёт в Kafka напрямую; убей его между
  шагами — инвариант ломается. Во сколько строк?
- Консьюмер коммитит оффсет **до** транзакции в базе — повтори c) с падением «после оффсета, до
  COMMIT». Что потеряли?
- Бонус CDC: Debezium (Kafka Connect) с Outbox Event Router вместо `relay.py` (версии — **проверь**).
  Останови коннектор на полчаса под нагрузкой: `SELECT slot_name, active, wal_status,
  pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) FROM pg_replication_slots` — что
  растёт и чем это грозит primary?

### Критерии
- [ ] Инвариант держится после a)–e) и после «сломай сам» для правильного варианта
- [ ] Объяснено, почему relay даёт at-least-once и где в цепочке «ровно один раз» — только эффект
- [ ] Дубли в топике посчитаны и показано, что консьюмер их поглотил
- [ ] Для CDC-бонуса — алерт на неактивный слот и размер удерживаемого WAL

### Уборка
`docker compose down -v`

---

## 🏁 Что должно остаться после блока

```text
~/labs/distributed/
├── lab1/  compose.yaml, lat.sh, RESULTS.md       # латентность, failover, разделение 1 | 2
├── lab2/  Dockerfile, patroni.yml, haproxy.cfg,  # хронология failover, split brain и
│          compose.yaml, RESULTS.md                #   потерянная строка
├── lab3/  lock-worker.sh (+ fixed), RESULTS.md   # сдвиг часов → два держателя → fencing
├── lab4/  compose.yaml, run.sh, RESULTS.md       # lost_acked по acks
├── lab5/  app/linkd.py (патч), idem-test.sh      # ключ идемпотентности с тестом
└── lab6/  relay.py, stats.py, compose.yaml       # outbox + dedup, инвариант после kill -9
```text
Это превращает «знаю CAP и Raft» в «вот мои цифры: etcd выбирает нового лидера за ~2 с, Patroni
переключается за ~30 с при `kill -9` и никогда не даёт двух primary — кроме случая без watchdog,
который я воспроизвёл; Kafka с `acks=1` потеряла у меня 579 подтверждённых сообщений из 60 000».

➡️ Дальше: [08_interview.md](/mlops/08-interview)
