---
title: "10. Zabbix: классический мониторинг инфраструктуры"
description: "Архитектура Zabbix, passive/active проверки, триггеры и гистерезис, discovery, proxy, API и Ansible, Zabbix vs Prometheus"
---

# 10. Zabbix: классический мониторинг инфраструктуры

> Сверх роадмапа: стандартом роадмап называет Prometheus, но в Казахстане в on-prem
> (банки, телеком, госсектор, крупные предприятия) очень часто встречается Zabbix.
> Это общее наблюдение по вакансиям и практике, а не статистика. Прийти в такую команду
> и не понимать Zabbix — значит неделю разбираться в том, что там все знают.
>
> **После темы ты умеешь:** объяснить устройство Zabbix (server, proxy, agent, БД, frontend),
> различать пассивные и активные проверки, собрать хост из шаблонов, написать триггер
> с гистерезисом, настроить уведомления в Telegram, включить LLD и автопоиск,
> поднять стенд в compose, работать с API и Ansible, и аргументированно выбрать между
> Zabbix и Prometheus.

---

## 🗺️ Архитектура

```text:no-line-numbers
 Филиал                          Центральный ДЦ
 agent2 ─┐                      ┌───────────────┐  SQL  ┌──────────────────────┐
 agent2 ─┼─► Zabbix proxy ─────►│ Zabbix server │◄─────►│ PostgreSQL / MySQL   │
 SNMP   ─┘   (буфер)    :10051  │ pollers,      │       │ конфиг + history +   │
                                │ trapper,      │       │ trends + события     │
 agent2 (active)  ── :10051 ───►│ триггеры,     │       └──────────▲───────────┘
 agent2 (passive) ◄─ :10050 ────│ действия      │                  │ SQL
 SNMP / IPMI / HTTP / ICMP ◄────│               │       ┌──────────┴───────────┐
                                └───────┬───────┘       │ Frontend (PHP) + API │◄── браузер
                                        ▼               └──────────────────────┘
                           Telegram · почта · webhook
```

| Компонент | Что делает |
|-----------|-----------|
| **Server** | Сердце: опрашивает (pollers), принимает данные (trapper), считает триггеры, запускает действия и эскалации |
| **БД** | ⭐ Хранит **всё**: конфигурацию, историю значений (history), агрегаты по часам (trends), события |
| **Frontend** | PHP-веб-интерфейс и JSON-RPC API; пишет конфигурацию в ту же БД |
| **Agent / Agent 2** | Ставится на хост, собирает метрики ОС и сервисов |
| **Proxy** | Собирает данные вместо сервера на удалённой площадке, буферизует, отправляет пачками |

Ключевое отличие от Prometheus (см. [«02. Prometheus: базовые концепции»](/monitoring/02-prometheus-basics)): у Zabbix
**всё в реляционной БД и в UI/API**, а не в файлах. Отсюда и сильные стороны (коробка,
эскалации, удобно админам), и слабые (БД растёт, конфиг сложнее держать в git).

> 📌 **Версии (проверь, сентябрь 2026):** LTS — **7.0** (7.0.31 от 22.09.2026, полная
> поддержка до 06.2027); стандартный релиз — **7.4** (7.4.15). **8.0 LTS** запланирован на
> Q3 2026, на 23.09.2026 опубликован только 8.0.0beta2 (9 июля). Для 8.0 поднимаются
> минимальные версии: PostgreSQL 15, PHP 8.2. В проде бери LTS; учить можно на 7.0 —
> концепции в 8.0 те же.

---

## 1. Модель данных: от хоста до уведомления

```text:no-line-numbers
 Host group ─► Host (интерфейсы agent/SNMP/JMX/IPMI) ── привязан ──► Template
                                                                        │ содержит
 history/trends ◄── значения ── Item (элемент данных) ◄─────────────────┤
                                  │                                     │
                                  ▼                                     │
 Problem (событие) ◄── OK→PROBLEM ── Trigger (выражение над item'ами) ◄─┘
      │
      └──► Action (условия) ──► Operation (сообщение, скрипт) ──► Media type (Telegram, email)
```

| Zabbix | Ближайший аналог в Prometheus | Разница |
|--------|------------------------------|---------|
| Host | `instance` | Хост — объект в БД с интерфейсами и инвентарём |
| Template | Экспортер + набор правил | Шаблон несёт и сбор, и триггеры, и графики |
| Item | Временной ряд | Один item = один ряд на хосте; лейблов нет, есть теги |
| Trigger | Alerting rule | Выражение + severity + зависимости |
| Action | Маршрут в Alertmanager | Условия + операции + эскалации |
| Maintenance | Silence | Плановые работы, данные собираются или нет — на выбор |
| Macro `{$X}` | Параметр правила | Порог/креды на уровне шаблона, хоста или глобально |

Макросы наследуются с приоритетом **хост > шаблон > глобальные**. Правильная практика:
пороги в шаблоне задаются макросами (`{$CPU.UTIL.CRIT}`), а для особого хоста
переопределяются на хосте — шаблон при этом не трогают.

---

## 2. Агент: пассивные и активные проверки

```text:no-line-numbers
 ПАССИВНАЯ (passive)                         АКТИВНАЯ (active)
 server ── "дай system.cpu.load" ──► agent   agent ── "что мне собирать?" ──► server
        :10050                               agent ◄── список item'ов ──────  :10051
 server ◄── значение ───────────────  agent  agent ── пачка значений ───────► server
 Сервер ходит к каждому агенту                Агент сам шлёт данные (буферизует)
```

| | Passive | Active |
|---|---------|--------|
| Кто инициирует | Server/proxy → agent:10050 | Agent → server/proxy:10051 |
| Параметр агента | `Server=` (кому можно спрашивать) | `ServerActive=` (куда слать) |
| Через NAT/firewall | Нужен доступ **к** хосту | Нужен доступ **от** хоста |
| Нагрузка на сервер | Pollers ждут ответа | Сервер только принимает |
| Когда брать | Мало хостов, простая сеть | ⭐ Много хостов, облака, NAT, автоперенос |

```ini
# /etc/zabbix/zabbix_agent2.conf — минимум
Server=10.0.0.10                    # passive: кто может опрашивать
ServerActive=10.0.0.10              # active: куда отправлять (можно proxy)
Hostname=web01                      # ⭐ должен совпадать с именем хоста в Zabbix
HostMetadata=linux web prod         # для авторегистрации (раздел 6)
```

**Agent vs Agent 2.** Agent 2 написан на Go, умеет плагины и держит соединения
с сервисами. Встроенные плагины: Docker, MySQL, Oracle, Redis, Memcached, Ceph, MQTT,
Modbus, SMART, Systemd и др.; загружаемые (пакеты `zabbix-agent2-plugin-*`): PostgreSQL,
MongoDB, MSSQL — в официальном Docker-образе agent2 они уже есть. Для новых установок
бери **agent2**.

```bash
zabbix_agent2 -t system.cpu.util                   # проверить ключ локально
zabbix_get -s web01 -k agent.ping                   # спросить агента с сервера (passive)
zabbix_sender -z zbx -s web01 -k backup.ok -o 1     # отправить значение в trapper-item
```

---

## 3. Items: что и как собирать

| Тип item | Пример ключа / назначение |
|----------|---------------------------|
| Zabbix agent (passive/active) | `system.cpu.util`, `vfs.fs.size[/,pused]`, `net.if.in[eth0]`, `proc.num[nginx]` |
| SNMP agent | Коммутаторы, маршрутизаторы, ИБП, СХД — ⭐ главная сила Zabbix |
| HTTP agent | Запрос к API/странице; ответ разбирается preprocessing'ом |
| Simple check | `icmpping`, `net.tcp.service[https,,443]` — без агента |
| Zabbix trapper | Значение приходит снаружи (`zabbix_sender`, скрипты бэкапа) |
| Dependent item | Берёт значение из «мастер»-item'а (один запрос → много метрик) |
| Calculated | Формула над другими item'ами |
| IPMI / JMX / ODBC / Script | Железо, Java, SQL-запрос, JavaScript |

**Preprocessing** — цепочка обработки значения до записи: JSONPath, регулярка,
«Change per second» (аналог `rate`), множитель, «Discard unchanged with heartbeat»
(не писать одинаковые значения — экономит БД), **Prometheus pattern** (вытащить
метрику из `/metrics`).

```text:no-line-numbers
HTTP agent: GET http://linkd:8080/metrics   (мастер, history 0 — не хранить)
  └── dependent: linkd_errors_total   preprocessing: Prometheus pattern → Change per second
  └── dependent: linkd_db_up          preprocessing: Prometheus pattern
```

**History и trends.** History — сырые значения (типично 7–31 день), trends — часовые
min/avg/max (типично 365 дней). Именно эти два срока определяют размер БД.

---

## 4. Триггеры: выражения, severity, гистерезис

Синтаксис (с 5.4): `функция(/хост/ключ,параметры) оператор константа`.

```text:no-line-numbers
last(/web01/agent.ping)=0                                  агент не отвечает
avg(/web01/system.cpu.util,5m)>90                          средний CPU за 5 мин
min(/web01/vfs.fs.size[/,pfree],15m)<10                     свободно < 10% всё окно
nodata(/web01/backup.ok,26h)=1                              бэкап не отчитывался сутки
count(/web01/web.test.fail[linkd],10m,"ne",0)>=3            3 провала за 10 минут
change(/web01/system.sw.os)<>0                              сменилась ОС/ядро
last(/web01/vfs.fs.size[/,pused])>{$VFS.FS.PUSED.MAX.CRIT}  порог из макроса
```

В шаблоне вместо имени хоста пишется имя шаблона: `/Linux by Zabbix agent/…` — при
привязке к хосту подставится сам хост. Имя триггера с макросами:
`Высокая загрузка CPU на {HOST.NAME}: {ITEM.LASTVALUE}`.

**Severity** (по возрастанию): Not classified → Information → Warning → Average → High →
Disaster. Будить ночью — только High/Disaster. Критерии, какие алерты вообще нужны, те же,
что в [«05. Alertmanager»](/monitoring/05-alertmanager) и [«07. Что мониторить»](/monitoring/07-what-to-monitor):
симптом, а не «CPU 80%».

### ⭐ Гистерезис (recovery expression) — лекарство от дребезга

```text:no-line-numbers
 CPU %  95 ┤    ╭╮  ╭─╮        без гистерезиса: порог 90 — PROBLEM/OK каждые 30 с
        90 ┼────╯╰──╯ ╰╮ ╭╮──  с гистерезисом: PROBLEM при >90 5 мин,
        70 ┼ ─ ─ ─ ─ ─ ─╰─╯╰─   OK только когда <70 5 мин
```

```text:no-line-numbers
Problem expression:   min(/web01/system.cpu.util,5m)>90
Recovery expression:  max(/web01/system.cpu.util,5m)<70
OK event generation:  Recovery expression
```

Проблема закрывается, только когда выражение проблемы ложно **и** выражение
восстановления истинно. Окно в функциях (`min(...,5m)`) — аналог `for` в Prometheus.

**Зависимости триггеров.** «Коммутатор филиала недоступен» → зависимые «хост за ним
недоступен» не создают отдельных уведомлений. Аналог inhibit-правил Alertmanager.

---

## 5. Действия, эскалации и Telegram

```text:no-line-numbers
Action "Prod: High и выше"   условия: host group = Prod AND severity >= High AND не в maintenance
  шаг 1 (0 мин)  → группа "DevOps дежурные" в Telegram
  шаг 2 (15 мин) → не подтверждено (ack) → руководитель;  шаг 3 (30 мин) → скрипт/звонок
  recovery operations → "✅ решено" в тот же чат;  update operations → ack/комментарий
```

**Telegram** — встроенный media type (webhook), настраивается без кода:
1. Бот через @BotFather → токен; бот добавлен в чат.
2. *Alerts → Media types → Telegram*: параметр `api_token` = токен бота, включить.
3. *Users → пользователь → Media*: тип Telegram, **Send to** = chat id (для группы —
   отрицательный `-100…`).
4. Action с операцией «Send message» этой группе пользователей.
5. Проверка: кнопка **Test** у media type.

**Maintenance** (*Data collection → Maintenance*) — аналог silence: на время работ
проблемы не шлют уведомления; «With data collection» — данные при этом пишутся.

---

## 6. Discovery: чтобы не заводить всё руками

| Механизм | Что находит | Пример |
|----------|-------------|--------|
| **LLD** (low-level discovery) | Сущности **внутри** хоста | Файловые системы, интерфейсы, базы, диски, контейнеры |
| **Network discovery** | Хосты **в сети** по диапазону IP | Скан `10.10.0.0/24` по ICMP/SNMP/agent → action: добавить хост + шаблон |
| **Active agent autoregistration** | Хосты, которые **сами** пришли | ⭐ Агент с `HostMetadata=linux prod` → action: группа Prod + шаблон Linux |

LLD устроен так: discovery rule возвращает JSON с макросами, по нему создаются
**прототипы**:

```json
[{"{#FSNAME}": "/", "{#FSTYPE}": "ext4"}, {"{#FSNAME}": "/data", "{#FSTYPE}": "xfs"}]
```
```text:no-line-numbers
item prototype:    vfs.fs.size[{#FSNAME},pused]
trigger prototype: last(/Linux by Zabbix agent/vfs.fs.size[{#FSNAME},pused])>{$VFS.FS.PUSED.MAX.CRIT:"{#FSNAME}"}
фильтр:            {#FSTYPE} matches ^(ext4|xfs|btrfs)$     ← не мониторить tmpfs/overlay
```

> 💡 Для облака и автоскейлинга лучший вариант — **авторегистрация активных агентов**:
> Ansible/cloud-init ставит agent2 с нужным `HostMetadata`, хост сам появляется
> с правильными шаблонами. Network discovery хорош для «железного» зоопарка и SNMP.

---

## 7. Proxy: удалённые площадки

```text:no-line-numbers
  Центральный ДЦ                        Регион / филиал / другая сеть
 ┌──────────────┐  одно исходящее      ┌──────────────────────────────┐
 │ Zabbix server│◄═ соединение ════════│ Zabbix proxy (active)        │
 └──────────────┘  :10051, TLS/PSK     │ своя БД (SQLite/PG), буфер   │
                                       │ ► agent2 × 200, SNMP, ICMP   │
                                       └──────────────────────────────┘
```

Зачем proxy: **сеть** — одно соединение с площадки вместо сотни, агенты и SNMP не выходят
за её пределы; **буфер** — связь с центром пропала, proxy копит данные и досылает
(`ProxyOfflineBuffer`, в часах — проверь в своей версии); **нагрузка** — опросы делает proxy.
**Proxy groups (с 7.0)** — хосты распределяются между proxy группы и переезжают при падении одного.

```ini
# zabbix_proxy.conf
ProxyMode=0                 # 0 = active (proxy сам ходит к серверу), 1 = passive
Server=zbx.example.kz
Hostname=proxy-shymkent     # ⭐ имя proxy в UI должно совпадать
DBName=/var/lib/zabbix/proxy.db
TLSConnect=psk
TLSPSKIdentity=proxy-shymkent
TLSPSKFile=/etc/zabbix/proxy.psk
```

Сам сервер тоже можно сделать отказоустойчивым: **native HA-кластер** (с 6.0) —
несколько server-нод, активна одна, остальные в standby, общая БД.

---

## 8. 🧰 Стенд: Zabbix 7.0 + PostgreSQL + agent2 в compose

```bash
mkdir -p ~/labs/zabbix && cd ~/labs/zabbix
```
```yaml
# docker-compose.yml
x-db: &db                                     # общие переменные БД (учебный стенд; в проде — секреты)
  DB_SERVER_HOST: postgres-server
  POSTGRES_USER: zabbix
  POSTGRES_PASSWORD: zabbix_pwd
  POSTGRES_DB: zabbix

services:
  postgres-server:
    image: postgres:16-alpine                 # 8.0 потребует PostgreSQL 15+
    environment: *db
    volumes: [pgdata:/var/lib/postgresql/data]

  zabbix-server:
    image: zabbix/zabbix-server-pgsql:alpine-7.0-latest   # проверь тег, сентябрь 2026
    environment: *db
    ports: ["10051:10051"]
    depends_on: [postgres-server]

  zabbix-web:
    image: zabbix/zabbix-web-nginx-pgsql:alpine-7.0-latest
    environment:
      <<: *db
      ZBX_SERVER_HOST: zabbix-server
      PHP_TZ: Asia/Almaty
    ports: ["8080:8080"]                      # nginx в контейнере слушает 8080
    depends_on: [zabbix-server]

  zabbix-agent2:
    image: zabbix/zabbix-agent2:alpine-7.0-latest
    hostname: zabbix-agent2
    environment:
      ZBX_HOSTNAME: zabbix-agent2             # = имя хоста в UI
      ZBX_SERVER_HOST: zabbix-server          # кому разрешены пассивные проверки
      ZBX_ACTIVESERVERS: zabbix-server        # куда слать активные
    depends_on: [zabbix-server]

  web:                                        # цель HTTP-проверок (можно заменить на linkd)
    image: nginx:alpine

volumes: { pgdata: {} }
```
```bash
docker compose up -d
docker compose logs -f zabbix-server | grep -m1 'server #0 started'   # схема создана, сервер жив
# UI: http://localhost:8080   логин Admin / zabbix  → ⭐ сразу сменить пароль
```

### Мини-лаба: Linux + PostgreSQL + HTTP через шаблоны

1. **Linux.** *Data collection → Hosts → Create host*: имя `zabbix-agent2`, группа
   `Linux servers`, интерфейс **Agent**, DNS `zabbix-agent2`, «Connect to: DNS», порт 10050.
   Шаблон `Linux by Zabbix agent`. Через 1–2 минуты: *Monitoring → Latest data*.
   ⚠️ Агент в контейнере видит контейнер, а не хост; на реальной VM агент ставят пакетом.
2. **PostgreSQL** (мониторим базу самого Zabbix):
   ```bash
   docker compose exec postgres-server psql -U zabbix -d zabbix -c \
     "CREATE USER zbx_monitor WITH PASSWORD 'mon_pwd' INHERIT; GRANT pg_monitor TO zbx_monitor;"
   ```
   К тому же хосту добавь шаблон `PostgreSQL by Zabbix agent 2`, макросы хоста:
   `{$PG.CONNSTRING.AGENT2}` = `tcp://postgres-server:5432`, `{$PG.USER}` = `zbx_monitor`,
   `{$PG.PASSWORD}` = `mon_pwd` (тип Secret text). Запросы к базе делает **агент** своим плагином.
3. **HTTP.** На хосте → *Web* → web scenario `web health`: шаг `http://web/`, ожидаемый
   код 200. Zabbix сам создаст item'ы `web.test.fail[web health]`, `web.test.time[…]`,
   `web.test.rspcode[…]`. Триггер: `last(/zabbix-agent2/web.test.fail[web health])<>0`.
4. **Сломай.** `docker compose stop web` → проблема в *Monitoring → Problems*;
   `docker compose start web` → закрылась. Останови агент — сработает триггер
   недоступности агента из шаблона Linux.
5. **Уведомления.** Подключи Telegram по разделу 5, повтори шаг 4 и получи сообщение
   о проблеме и о восстановлении.
6. **Гистерезис.** Нагрузи CPU (`docker compose exec zabbix-agent2 sh -c 'yes >/dev/null'`)
   и сравни свой триггер нагрузки без recovery expression и с ним.

---

## 9. API: JSON-RPC и автоматизация

Всё, что делается в UI, есть в API: `https://zbx/api_jsonrpc.php`, метод POST,
`Content-Type: application/json-rpc`. Токен — через `user.login` или (лучше) API-токен
сервисного пользователя (*Users → API tokens*). С 7.0 токен передают заголовком
`Authorization: Bearer …`; поле `auth` в теле устарело.

```bash
ZBX=http://localhost:8080/api_jsonrpc.php
TOKEN=$(curl -s $ZBX -H 'Content-Type: application/json-rpc' -d '{
  "jsonrpc":"2.0","method":"user.login","id":1,
  "params":{"username":"Admin","password":"<пароль>"}}' | jq -r .result)
# хосты и их доступность
curl -s $ZBX -H 'Content-Type: application/json-rpc' -H "Authorization: Bearer $TOKEN" -d '{
  "jsonrpc":"2.0","method":"host.get","id":2,
  "params":{"output":["hostid","host","status"],"selectInterfaces":["ip","dns","available"]}}' | jq
# текущие проблемы High и выше
curl -s $ZBX -H 'Content-Type: application/json-rpc' -H "Authorization: Bearer $TOKEN" -d '{
  "jsonrpc":"2.0","method":"problem.get","id":3,
  "params":{"output":["eventid","name","severity","clock"],"severities":[4,5],"recent":true}}' | jq
```

```python
# zbx_maint.py — поставить maintenance на хост перед деплоем (вызывается из CI)
import os, time, requests

URL = os.environ["ZBX_URL"]                       # https://zbx/api_jsonrpc.php
HDR = {"Authorization": f"Bearer {os.environ['ZBX_TOKEN']}"}   # json= сам ставит Content-Type

def call(method, params):
    r = requests.post(URL, json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
                      headers=HDR, timeout=10)
    r.raise_for_status()
    body = r.json()
    if "error" in body:                           # ⭐ ошибки API приходят с HTTP 200
        raise RuntimeError(body["error"])
    return body["result"]

host = call("host.get", {"filter": {"host": ["web01"]}, "output": ["hostid"]})[0]
now = int(time.time())
call("maintenance.create", {
    "name": f"deploy web01 {now}", "active_since": now, "active_till": now + 1800,
    "hosts": [{"hostid": host["hostid"]}],
    "timeperiods": [{"period": 1800}],            # timeperiod_type по умолчанию — one time
})
```

Есть и официальная библиотека `zabbix_utils` (pip) — обёртка над тем же JSON-RPC.

### Ansible: `community.zabbix`

Коллекция (4.x, на момент написания 4.2.0 — проверь, сентябрь 2026) даёт **роли**
`zabbix_agent`, `zabbix_server`, `zabbix_proxy`, `zabbix_web`, `zabbix_javagateway`
и **модули** `zabbix_host`, `zabbix_template`, `zabbix_group`, `zabbix_action`,
`zabbix_mediatype`, `zabbix_maintenance`, `zabbix_discovery_rule` и др.

```yaml
# host_vars/zbx-api.yml — модули ходят в API через httpapi-соединение
ansible_network_os: community.zabbix.zabbix
ansible_connection: httpapi
ansible_httpapi_port: 443
ansible_httpapi_use_ssl: true
ansible_zabbix_auth_key: "{{ vault_zabbix_token }}"     # токен из vault, не в git
```
```yaml
# playbook: агент на хосты + регистрация в Zabbix (имена переменных роли сверь с её README)
- hosts: app
  become: true
  roles:
    - role: community.zabbix.zabbix_agent
      vars:
        zabbix_agent2: true
        zabbix_agent_server: zbx.example.kz
        zabbix_agent_serveractive: zbx.example.kz

- hosts: app
  gather_facts: false
  tasks:
    - name: Хост в Zabbix
      community.zabbix.zabbix_host:
        host_name: "{{ inventory_hostname }}"
        host_groups: [Linux servers, Prod]
        link_templates: [Linux by Zabbix agent]
        interfaces:
          - { type: agent, main: 1, useip: 1, ip: "{{ ansible_host }}", port: "10050" }
        macros:
          - { macro: "{$VFS.FS.PUSED.MAX.CRIT}", value: "95" }
      delegate_to: zbx-api                   # хост из inventory с переменными httpapi
```

> 💡 Шаблоны экспортируются в YAML (*Data collection → Templates → Export*) и ложатся в git.
> «Шаблоны в git → импорт через API/Ansible в CI» — тот же «мониторинг как код», что у Prometheus.

---

## 10. Zabbix vs Prometheus: когда что

| | Zabbix | Prometheus |
|---|--------|-----------|
| Сбор | Агент (passive/active), SNMP, IPMI, JMX, HTTP, ICMP | Pull HTTP `/metrics`, экспортеры |
| Хранение | Реляционная БД (PG/MySQL, опционально TimescaleDB) | Своя TSDB, долгое хранение — [«11. Долгое хранение и Operator»](/monitoring/11-long-term-and-operator) |
| Модель данных | Item на хосте + теги | Метрика + лейблы, многомерность |
| Язык запросов | Функции триггеров; ad-hoc аналитики нет | ⭐ PromQL |
| Алертинг | Встроен: триггеры, действия, эскалации, ack | Prometheus + Alertmanager |
| Конфигурация | UI/API, шаблоны (экспорт в YAML) | Файлы в git |
| Динамика | Поды живут минуты — плохо ложится на «хосты» | Kubernetes SD, ServiceMonitor — родная среда |
| Коробка | Сотни готовых шаблонов, карты сети, инвентарь | Экспортеры + дашборды из сообщества |
| Сильная сторона | ⭐ Железо, сеть (SNMP), Windows, VM, «один продукт на всё» | ⭐ Kubernetes, микросервисы, метрики приложений |

```text:no-line-numbers
            Типичное сосуществование (часто в КЗ-энтерпрайзе)
 ┌──────────────────────────────┐        ┌───────────────────────────────┐
 │ ZABBIX                       │        │ PROMETHEUS (kube-prometheus)   │
 │ коммутаторы, ИБП, СХД (SNMP) │        │ кластеры k8s, поды, ingress    │
 │ VM, Windows, железо (IPMI)   │        │ метрики приложений (/metrics)  │
 │ «старые» сервисы на VM       │        │ SLO, burn-rate алерты          │
 └──────────────┬───────────────┘        └───────────────┬───────────────┘
                └────────────► Grafana ◄─────────────────┘
                     (плагин Zabbix + источник Prometheus)
```

Как отвечать «что выбрать»: не «что лучше», а «что у нас мониторится». Железо, сеть, VM,
команда админов, эскалации из коробки → Zabbix. Kubernetes и сервисы с метриками →
Prometheus. Часто — оба, с общей Grafana; «всё на Prometheus» ради моды при живом SNMP-зоопарке — плохая идея.

---

## 11. Грабли

| Грабля | Симптом | Решение |
|--------|---------|---------|
| ⭐ БД растёт без контроля | Диск кончается, housekeeper крутится часами, UI тормозит | Осознанные сроки history/trends, «Discard unchanged», TimescaleDB-партиционирование, мониторинг размера БД |
| Слишком много item'ов и частые интервалы | Растёт *Queue* (задержанные проверки), pollers заняты на 100% | Интервалы 1–5 мин вместо 10 с, dependent items, active-агенты, proxy |
| Не хватает кэшей | Лог: `cache is full`, дыры в данных | `CacheSize`, `HistoryCacheSize`, `ValueCacheSize`; шаблон `Zabbix server health` |
| Дребезг триггеров | PROBLEM/OK каждые пару минут, чат в спаме | Recovery expression (гистерезис), окна `min/max(...,5m)` |
| `Hostname` агента ≠ имени хоста | Active-проверки молчат, в логе агента `host not found` | Совпадающие имена, `HostMetadata` + авторегистрация |
| Агент в контейнере | «Мониторим хост», а видим контейнер | Агент на хосте пакетом (или privileged + mounts, осознанно) |
| `Admin/zabbix` не сменён | Любой в сети — администратор | Сменить сразу, SSO/LDAP, отдельные сервисные пользователи для API |
| Трафик агента без шифрования | Данные и команды в открытом виде | PSK или сертификаты (`TLSConnect`/`TLSAccept`) |
| Правки только в UI | «Кто поменял порог?», шаблоны разъехались между средами | Шаблоны в git, импорт через API/Ansible, аудит-лог |
| Нет мониторинга самого Zabbix | Сервер завис — тишина = «всё хорошо» | Шаблон `Zabbix server health`, внешняя проверка UI/порта, watchdog из другой системы |

---

## 💼 Как это в DevOps

- Приходишь в банк/телеком/госпроект — Zabbix там почти наверняка уже есть. Задача
  девопса — не выбросить его, а встроиться: агенты и хосты через Ansible, шаблоны
  в git, maintenance из CI на время деплоя, общая Grafana.
- Новый сервер появляется в мониторинге **сам**: роль `zabbix_agent` ставит agent2
  с `HostMetadata`, авторегистрация вешает шаблоны. Ручное «создать хост в UI» — незрелость.
- Удалённые площадки (филиалы, регионы, отдельные сегменты сети) — через active proxy
  с PSK; наружу выходит одно соединение.
- Kubernetes и сервисы с `/metrics` мониторятся Prometheus'ом, Zabbix
  остаётся на железе, сети и VM. Дежурство одно: одинаковые severity и один канал.
- Размер БД Zabbix — первая эксплуатационная метрика, которую надо держать на дашборде.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Проверить ключ на агенте | `zabbix_agent2 -t vfs.fs.size[/,pused]` |
| Триггер «нет данных» | `nodata(/host/key,10m)=1` |
| Убрать дребезг | Recovery expression: `max(/host/key,5m)<70` |
| Порог для одного хоста | Переопределить макрос `{$…}` на хосте |
| Хосты появляются сами | Active agent autoregistration + `HostMetadata` |
| Удалённая площадка | Active proxy + PSK |
| Заглушить на время работ | Maintenance (UI или `maintenance.create` через API) |
| Уведомить в Telegram | Media type Telegram + media пользователя + action |
| Список проблем из скрипта | API `problem.get` с `Authorization: Bearer` |
| Агенты и хосты кодом | Роль `community.zabbix.zabbix_agent` + модуль `zabbix_host` |
| Здоровье самого Zabbix | Шаблон `Zabbix server health`, *Administration → Queue* |

---

## 🧠 Что запомнить

1. Zabbix = server + БД + frontend + agent/agent2 + proxy; **всё** (конфиг и данные)
   лежит в реляционной БД.
2. Passive: сервер спрашивает агента на 10050; active: агент сам шлёт на 10051 —
   для масштаба, NAT и облаков бери active.
3. Цепочка: хост → шаблон → item → триггер → проблема → action → media type.
4. Пороги — макросами в шаблоне, исключения — переопределением на хосте.
5. ⭐ Recovery expression (гистерезис) лечит дребезг; окно в функции — аналог `for`.
6. LLD — сущности внутри хоста, network discovery — хосты в сети, авторегистрация — сами пришли.
7. Proxy — для удалённых площадок: одно соединение, буфер при обрыве, разгрузка сервера.
8. API — JSON-RPC на `api_jsonrpc.php`, токен в `Authorization: Bearer`; ошибки приходят
   с HTTP 200 в поле `error`.
9. Главная эксплуатационная боль — рост БД: сроки history/trends, housekeeping, TimescaleDB.
10. Zabbix — железо, сеть, VM; Prometheus — Kubernetes и приложения; часто они живут
    вместе под общей Grafana.

---

## Задачи

> Стенд: compose из раздела 8 конспекта (`~/labs/zabbix`: PostgreSQL + server + web + agent2 + nginx).
> Для блока C5 нужен телеграм-бот (@BotFather) и тестовый чат — тот же, что в
> [«05. Alertmanager»](/monitoring/05-alertmanager).

---

### Блок A. Теория

**A1.** Из каких компонентов состоит Zabbix? Что из них обязательно, а что опционально?

<details><summary>Ответ</summary>

Server, БД, frontend — обязательный минимум; agent/agent2 — почти всегда;
proxy — для удалённых площадок и разгрузки; Java gateway, web service (отчёты) — опционально.

</details>

**A2.** ⭐ Что хранится в БД Zabbix? Почему именно БД — главный объект эксплуатации?

<details><summary>Ответ</summary>

Всё: конфигурация (хосты, шаблоны, триггеры, пользователи), history, trends,
события и проблемы, аудит. Поэтому размер БД, её производительность и бэкап определяют
здоровье всего мониторинга; сервер без БД не работает.

</details>

**A3.** Чем пассивная проверка отличается от активной? Какие порты и параметры агента
за что отвечают?

<details><summary>Ответ</summary>

Passive: сервер/proxy подключается к агенту на 10050, агент отвечает на один
запрос; параметр `Server=` — кому разрешено спрашивать. Active: агент сам подключается
к серверу/proxy на 10051, получает список item'ов и шлёт значения пачками;
параметр `ServerActive=`. В обоих случаях `Hostname` должен совпадать с именем хоста.

</details>

**A4.** Когда выбирать active-агентов, а когда достаточно passive?

<details><summary>Ответ</summary>

Active — много хостов, NAT и облака (нужен только исходящий доступ с хоста),
автоскейлинг и авторегистрация, меньше нагрузки на pollers. Passive — небольшая
инфраструктура с простой сетью или когда хост не должен сам выходить наружу.

</details>

**A5.** Чем Agent 2 отличается от классического агента? Что такое загружаемые плагины?

<details><summary>Ответ</summary>

Agent 2 на Go: плагины, постоянные соединения с сервисами (PostgreSQL, Redis,
Docker), параллельный сбор. Загружаемые плагины — отдельные бинарники/пакеты
(`zabbix-agent2-plugin-*`, например PostgreSQL, MongoDB, MSSQL), подключаются без
пересборки агента.

</details>

**A6.** Опиши цепочку «хост → … → сообщение в Telegram». Какой объект за что отвечает?

<details><summary>Ответ</summary>

Хост (объект с интерфейсами) связан с шаблоном → шаблон даёт item'ы (сбор)
и триггеры (условия) → триггер переходит OK → PROBLEM, создаётся проблема → action
проверяет условия (группа, severity, maintenance) → операция отправляет сообщение группе
пользователей → media type (Telegram) доставляет по media пользователя (chat id).

</details>

**A7.** Что такое макрос `{$…}` и в каком порядке применяются значения с разных уровней?

<details><summary>Ответ</summary>

Переменная для порогов, кредов, адресов. Приоритет: хост → привязанные шаблоны
→ глобальные макросы. Контекстные макросы (`{$X:"/data"}`) позволяют разный порог
для конкретной сущности LLD.

</details>

**A8.** Что такое dependent item и зачем он нужен? Приведи пример.

<details><summary>Ответ</summary>

Item, который берёт значение не сам, а из мастер-item'а и вытаскивает часть через
preprocessing. Пример: один HTTP-запрос к `/metrics` или JSON-API, из которого десяток
dependent item'ов достают отдельные значения — один запрос вместо десяти.

</details>

**A9.** Чем history отличается от trends? Как их сроки влияют на размер БД?

<details><summary>Ответ</summary>

History — сырые значения, trends — часовые min/avg/max/count. Размер БД примерно
пропорционален числу item'ов × частоте × сроку history, плюс trends по числовым item'ам.
Короткая history + длинные trends — стандартный компромисс.

</details>

**A10.** ⭐ Что такое recovery expression и какую проблему он решает?

<details><summary>Ответ</summary>

Отдельное условие закрытия проблемы. Проблема открывается по problem expression
и закрывается, только когда оно ложно и recovery expression истинно. Это гистерезис:
разные пороги входа и выхода убирают дребезг около порога.

</details>

**A11.** Что такое зависимости триггеров? Какой аналог есть в Alertmanager?

<details><summary>Ответ</summary>

Если триггер-родитель в состоянии PROBLEM, зависимые не создают своих
уведомлений: «коммутатор недоступен» подавляет «хосты за ним недоступны». Аналог —
inhibit rules в Alertmanager.

</details>

**A12.** Чем LLD отличается от network discovery и от авторегистрации активных агентов?

<details><summary>Ответ</summary>

LLD находит сущности внутри уже известного хоста (ФС, интерфейсы, базы) и
создаёт item'ы/триггеры по прототипам. Network discovery сканирует диапазоны IP и через
action добавляет найденные хосты. Авторегистрация — агент сам приходит с `HostMetadata`,
и action заводит хост с группами и шаблонами; лучший вариант для облака.

</details>

**A13.** Зачем нужен Zabbix proxy? Что происходит с данными при обрыве связи с сервером?

<details><summary>Ответ</summary>

Сбор данных на удалённой площадке: одно соединение с центром, опросы идут
локально, сервер разгружается. При обрыве proxy хранит данные в своей БД
(`ProxyOfflineBuffer`) и досылает после восстановления связи; если обрыв дольше буфера —
старые данные теряются.

</details>

**A14.** Как работает API Zabbix? Как передаётся токен в 7.0 и как выглядит ошибка?

<details><summary>Ответ</summary>

JSON-RPC 2.0 по HTTP POST на `api_jsonrpc.php`: `method`, `params`, `id`.
Токен из `user.login` или API-токен, передаётся заголовком
`Authorization: Bearer`; поле `auth` в теле устарело. Ошибка приходит с HTTP 200 и объектом `error` (code, message,
data) — проверять надо тело, а не только код ответа.

</details>

**A15.** ⭐ В каких случаях ты выберешь Zabbix, в каких Prometheus, а в каких — оба?

<details><summary>Ответ</summary>

Zabbix — железо, сеть по SNMP, Windows, VM, «коробочный» мониторинг
с эскалациями для команды админов. Prometheus — Kubernetes, микросервисы, метрики
приложений, PromQL и SLO. Оба — типичная гибридная инфраструктура: Zabbix на железе
и VM, Prometheus на кластерах, общая Grafana и единые правила дежурства.

</details>

---

### Блок B. «Что делает / что тут не так»

Триггеры:
```text:no-line-numbers
B1.  last(/web01/agent.ping)=0
B2.  avg(/web01/system.cpu.util,5m)>90
B3.  last(/web01/system.cpu.util)>90                    # severity Disaster
B4.  nodata(/backup01/backup.ok,26h)=1
B5.  count(/web01/web.test.fail[shop],10m,"ne",0)>=3
B6.  Problem:  min(/db01/vfs.fs.size[/data,pused],10m)>90
     Recovery: max(/db01/vfs.fs.size[/data,pused],10m)<80
B7.  last(/web01/vfs.fs.size[/,pused])>{$VFS.FS.PUSED.MAX.CRIT}
B8.  change(/web01/system.sw.os)<>0
```

<details><summary>Ответ (триггеры)</summary>

**B1.** Агент не отвечает на `agent.ping` — базовый триггер доступности; лучше использовать
встроенный из шаблона (он учитывает active/passive).
**B2.** Средний CPU за 5 минут выше 90% — окно гасит одиночные всплески, норма.
**B3.** Одно последнее значение + Disaster: дребезг и ложные ночные подъёмы. Нужны окно
(`min/avg(...,5m)`), честная severity и лучше — алерт на симптом сервиса.
**B4.** Бэкап не отчитывался 26 часов (сутки + запас) — хороший триггер на регламент.
**B5.** Три и более провала web-сценария за 10 минут — устойчиво к единичным сбоям.
**B6.** Гистерезис: проблема при заполнении > 90% всё окно, закрытие только при < 80%.
**B7.** Порог из макроса — правильно: можно переопределить на хосте, не трогая шаблон.
**B8.** Срабатывает при смене версии ОС/ядра — информационный триггер (обычно Information).

</details>

Конфиги и команды:
```ini
B9.  # zabbix_agent2.conf
     Server=10.0.0.10
     ServerActive=10.0.0.10
     Hostname=web01.prod.local        # в UI хост называется web01
B10. # zabbix_agent2.conf на VM в облаке за NAT
     Server=10.0.0.10
     # ServerActive не задан
B11. # zabbix_proxy.conf
     ProxyMode=0
     Server=zbx.example.kz
     Hostname=proxy-branch1
```
```bash
B12. zabbix_get -s 10.0.1.5 -k 'vfs.fs.size[/,pused]'
B13. zabbix_sender -z zbx -s db01 -k backup.ok -o 1
B14. curl -s $ZBX -H 'Content-Type: application/json-rpc' \
       -d '{"jsonrpc":"2.0","method":"host.get","params":{},"id":1}'
```

<details><summary>Ответ (конфиги и команды)</summary>

**B9.** `Hostname` не совпадает с именем в UI — active-проверки не заработают (`host not found`),
passive будут работать. Исправить имя в одном из мест.
**B10.** За NAT сервер не достучится до агента, а активных проверок нет — данных не будет.
Нужен `ServerActive` и шаблон с active-проверками.
**B11.** Active proxy: сам подключается к серверу; в UI должен быть proxy с именем
`proxy-branch1` в активном режиме. Не хватает PSK/TLS.
**B12.** Passive-запрос ключа у агента с сервера/proxy — быстрая проверка доступности и прав.
**B13.** Отправка значения в trapper-item `backup.ok` хоста `db01` — так скрипт бэкапа
отчитывается об успехе.
**B14.** Нет токена (`Authorization: Bearer`) — вернётся ошибка авторизации в поле `error`
при HTTP 200.

</details>

Оцени решения:
```text:no-line-numbers
B15. "Всем item'ам интервал 10 секунд, history 365 дней — вдруг пригодится"
B16. "Мониторим поды Kubernetes в Zabbix: каждый под — отдельный хост, заводим руками"
B17. "Новые VM добавляем в Zabbix вручную через UI после каждого деплоя"
B18. "Меняем Zabbix на Prometheus целиком, включая 400 коммутаторов и ИБП по SNMP"
```

<details><summary>Ответ (оцени решения)</summary>

**B15.** Нагрузка на pollers и очередь, взрывной рост БД и housekeeping. Интервал —
по смыслу метрики (1–5 мин), history — дни, для истории — trends.
**B16.** Поды живут минуты, ручное ведение невозможно, модель «хост» не подходит.
Kubernetes — Prometheus/kube-prometheus-stack.
**B17.** Ручной шаг, который забывают. Авторегистрация активных агентов или
`community.zabbix.zabbix_host` в пайплайне.
**B18.** SNMP-зоопарк, эскалации и привычки команды никуда не денутся; миграция дорогая
и рискованная. Разумнее гибрид: Prometheus для k8s и сервисов, Zabbix для железа и сети.

</details>

---

### Блок C. Практика

#### C1. 🔑 Стенд
1. Подними compose из раздела 8 конспекта, дождись в логе сервера `server #0 started`.
2. Войди в UI, смени пароль `Admin`.
3. Найди в *Administration → Queue* очередь проверок, объясни, что она показывает.

#### C2. Хост из шаблона
1. Заведи хост `zabbix-agent2` с agent-интерфейсом по DNS и шаблоном `Linux by Zabbix agent`.
2. Найди в *Latest data* CPU, память, файловые системы.
3. Проверь ключ руками: `docker compose exec zabbix-agent2 zabbix_agent2 -t system.cpu.util`
   и `zabbix_get` из контейнера сервера (если утилиты нет — объясни, как проверить иначе).
4. Посмотри, какие item'ы и триггеры пришли из шаблона, а какие созданы LLD.

<details><summary>Ответ</summary>

Item'ы с `{#…}` в прототипах созданы LLD (файловые системы, интерфейсы) — у них
в UI есть пометка discovery rule. Если `zabbix_get` в образе сервера нет, проверяют
через *Execute now* у item'а или с отдельного контейнера с `zabbix-get`.

</details>

#### C3. PostgreSQL через agent 2
1. Создай пользователя `zbx_monitor` с ролью `pg_monitor`.
2. Привяжи шаблон `PostgreSQL by Zabbix agent 2`, задай макросы на хосте, пароль — Secret text.
3. Найди метрики подключений и размера базы `zabbix`.
4. Сломай пароль в макросе — что покажет Zabbix и где искать ошибку?

<details><summary>Ответ</summary>

С неверным паролем item'ы плагина становятся *Not supported* с текстом ошибки
подключения; видно в *Latest data* и в конфигурации item'а. Логи агента тоже покажут ошибку.

</details>

#### C4. HTTP-проверка
1. Сделай web scenario `web health` на `http://web/` с ожидаемым кодом 200.
2. Добавь триггер на провал сценария и второй — на время ответа > 2 с.
3. Останови `web` — дождись проблемы, запусти — дождись восстановления.
4. Со звёздочкой: подними linkd из `~/Projects/devops/09-ledger` в той же сети и проверь
   `/readyz`; сделай HTTP agent item на `/metrics` и dependent item с preprocessing
   **Prometheus pattern** для `linkd_db_up`.

#### C5. Telegram
1. Настрой media type Telegram, media у пользователя, action «severity ≥ Warning».
2. Получи сообщение о проблеме и о восстановлении (повтори C4.3).
3. Добавь второй шаг эскалации через 5 минут, если проблема не подтверждена.
4. Подтверди (ack) проблему и убедись, что второй шаг не сработал.

#### C6. ⭐ Гистерезис
1. Создай на хосте триггер `avg(/zabbix-agent2/system.cpu.util,1m)>70` без recovery.
2. Нагружай CPU рывками (`yes >/dev/null` на 40 с, пауза 20 с) — посчитай число событий.
3. Добавь recovery expression `max(...,2m)<40` — повтори и сравни.

<details><summary>Ответ</summary>

Без recovery событий столько же, сколько пересечений порога; с гистерезисом —
одно событие на весь эпизод нагрузки.

</details>

#### C7. LLD и макросы
1. Посмотри discovery rule файловых систем в шаблоне Linux: фильтр, прототипы.
2. Переопредели на хосте `{$VFS.FS.PUSED.MAX.CRIT}` для одной ФС через контекстный макрос
   `{$VFS.FS.PUSED.MAX.CRIT:"/"}`.
3. Объясни, почему правильно менять макрос на хосте, а не порог в шаблоне.

<details><summary>Ответ</summary>

Шаблон общий для всех хостов: правка в нём меняет пороги везде и ломается при
обновлении шаблона. Макрос на хосте — точечное и явное исключение.

</details>

#### C8. Авторегистрация
1. Добавь в compose второго агента `agent-b` с `ZBX_HOSTNAME=agent-b` и
   `ZBX_METADATA=linux lab` (проверь имя переменной в README образа).
2. Создай action *Autoregistration*: metadata содержит `linux` → добавить хост, группа
   `Lab`, шаблон `Linux by Zabbix agent active`.
3. Запусти агента — хост должен появиться без ручного создания.

<details><summary>Ответ</summary>

Если хост не появился — не совпадают metadata и условие action, агент не может
достучаться до `ServerActive`, или action выключен.

</details>

#### C9. API
1. Получи токен (`user.login` или API-токен), выведи хосты и их доступность `host.get`.
2. Выведи текущие проблемы `problem.get` с severity ≥ Warning.
3. Напиши скрипт, который ставит maintenance на хост на 30 минут, и скрипт, который его
   снимает (`maintenance.delete`). Проверь, что уведомления во время работ не приходят.

#### C10. Ansible (со звёздочкой)
1. Поставь коллекцию `community.zabbix`, опиши inventory с хостом API.
2. Модулем `zabbix_host` зарегистрируй хост с группой, шаблоном и макросом.
3. Запусти плейбук дважды — второй прогон должен быть `changed=0`.

<details><summary>Ответ</summary>

Модуль идемпотентен: сравнивает желаемое состояние с тем, что вернул API,
и ничего не меняет, если совпадает.

</details>

---

### Блок D. Инциденты

**D1.** Хост в UI красный: «Zabbix agent is not available», но агент запущен. Что проверишь?

<details><summary>Ответ</summary>

Порт 10050 и firewall между сервером и агентом, `Server=` в конфиге агента
(разрешён ли IP сервера/proxy), правильный IP/DNS интерфейса хоста, через какой proxy
опрашивается хост, PSK-настройки с обеих сторон, лог агента.

</details>

**D2.** Passive-проверки работают, active — нет, в логе агента `host [web01] not found`.

<details><summary>Ответ</summary>

`Hostname` в конфиге агента не совпадает с именем хоста в Zabbix (или хост
отслеживается другим proxy). Выровнять имена; для масштаба — авторегистрация.

</details>

**D3.** Диск под PostgreSQL Zabbix заполнился на 90%, housekeeper работает часами.
Быстрые и правильные решения?

<details><summary>Ответ</summary>

Быстро — расширить диск, временно сократить history для самых «тяжёлых» item'ов,
найти item'ы-лидеры по объёму. Правильно — пересмотреть сроки history/trends,
«Discard unchanged», убрать лишние item'ы и частые интервалы, TimescaleDB для
партиционирования (удаление старых чанков вместо медленного DELETE), алерт на размер БД.

</details>

**D4.** *Administration → Queue* показывает тысячи проверок с задержкой > 10 минут.

<details><summary>Ответ</summary>

Недоступные хосты тормозят passive-опрос (таймауты), не хватает pollers, слишком
частые интервалы, перегруженный proxy. Смотреть загрузку процессов (`zabbix[process,…]`
в шаблоне Zabbix server health), перевести агентов в active, разнести по proxy.

</details>

**D5.** В лог сервера сыплется `cache is full`, на графиках дыры.

<details><summary>Ответ</summary>

Не хватает кэшей (`CacheSize`, `HistoryCacheSize`, `ValueCacheSize`) или БД не
успевает записывать. Увеличить кэши по метрикам шаблона Zabbix server health и
разобраться с производительностью БД.

</details>

**D6.** Триггер «Высокая загрузка CPU» отправил 60 сообщений за ночь.

<details><summary>Ответ</summary>

Дребезг у порога: нет окна и гистерезиса. Окно в функции, recovery expression,
пересмотр severity и получателей; возможно, это вообще не должно будить.

</details>

**D7.** Коммутатор филиала упал — пришло 150 сообщений «хост недоступен».

<details><summary>Ответ</summary>

Нет зависимостей триггеров. Сделать триггеры хостов филиала зависимыми от
доступности коммутатора/proxy — придёт одно сообщение о причине.

</details>

**D8.** Связь с филиалом пропадала на 40 минут. Данные за это время есть или нет?

<details><summary>Ответ</summary>

Если хосты филиала опрашиваются через proxy и обрыв короче `ProxyOfflineBuffer` —
данные сохранены и досланы. Без proxy (прямой опрос из центра) — данных за этот период нет.

</details>

**D9.** Скрипт автоматизации работал, после обновления Zabbix стал получать ошибку
авторизации, хотя токен верный.

<details><summary>Ответ</summary>

Проверить, как передаётся токен: в новых версиях ожидается
`Authorization: Bearer`, поле `auth` в теле устарело; также изменения методов API в
release notes. Обработка ошибок должна читать поле `error`.

</details>

**D10.** Zabbix server завис на ночь, никто не узнал. Как не допустить повторения?

<details><summary>Ответ</summary>

Шаблон Zabbix server health с алертами, внешняя проверка UI и порта 10051 из
другой системы (blackbox в Prometheus, uptime-сервис), watchdog: регулярное тестовое
уведомление, отсутствие которого — тревога; native HA-кластер сервера.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как устроен Zabbix и что в нём хранится в БД?

<details><summary>Ответ</summary>

Server, БД, frontend, агенты, proxy; в БД — конфигурация, history, trends, события.

</details>

**2.** Чем пассивные проверки отличаются от активных?

<details><summary>Ответ</summary>

Passive — сервер спрашивает агента на 10050; active — агент сам шлёт на 10051,
масштабируется и работает через NAT.

</details>

**3.** Что такое шаблоны и макросы, зачем они?

<details><summary>Ответ</summary>

Шаблон — переиспользуемый набор item'ов, триггеров, графиков и LLD; макросы — параметры
порогов и кредов с переопределением на хосте.

</details>

**4.** Как написать триггер и как бороться с его дребезгом?

<details><summary>Ответ</summary>

`функция(/хост/ключ,окно) оператор порог`; дребезг — окна, recovery expression,
зависимости и честная severity.

</details>

**5.** Что такое LLD и как новые хосты попадают в мониторинг автоматически?

<details><summary>Ответ</summary>

LLD создаёт метрики для найденных внутри хоста сущностей; хосты — авторегистрация
активных агентов с `HostMetadata` или network discovery.

</details>

**6.** Зачем нужен Zabbix proxy?

<details><summary>Ответ</summary>

Удалённые площадки: одно соединение, буфер при обрыве, разгрузка сервера, proxy groups
для отказоустойчивости.

</details>

**7.** Как настроить уведомления и эскалации?

<details><summary>Ответ</summary>

Media type (Telegram/почта), media у пользователей, action с условиями и шагами
эскалации, recovery-операции, maintenance на время работ.

</details>

**8.** Как автоматизировать Zabbix (API, Ansible)?

<details><summary>Ответ</summary>

JSON-RPC API с токеном в заголовке; `community.zabbix`: роль агента и модули
`zabbix_host`/`zabbix_template`; шаблоны в git.

</details>

**9.** Какие главные проблемы эксплуатации Zabbix?

<details><summary>Ответ</summary>

Рост БД и housekeeping, перегрузка очереди, кэши, дребезг триггеров, ручная
конфигурация в UI, мониторинг самого Zabbix.

</details>

**10.** Zabbix или Prometheus — что и когда?

<details><summary>Ответ</summary>

Железо, сеть, VM — Zabbix; Kubernetes и приложения — Prometheus; в гибриде — оба
с общей Grafana.

</details>

---

### 🎯 Чек-лист

- [ ] Объясняю архитектуру Zabbix и роль БД
- [ ] ⭐ Различаю passive и active проверки, знаю порты и параметры агента
- [ ] Поднял стенд в compose и сменил пароль Admin
- [ ] Собрал хост из шаблонов Linux и PostgreSQL by Zabbix agent 2
- [ ] Сделал web scenario и триггеры на него
- [ ] Пишу выражения триггеров и умею делать гистерезис
- [ ] Настроил Telegram, action и эскалацию
- [ ] Понимаю LLD, network discovery и авторегистрацию
- [ ] Знаю, зачем proxy и что будет при обрыве связи
- [ ] Работал с API через curl и Python, пробовал `community.zabbix`
- [ ] Аргументированно выбираю между Zabbix и Prometheus
