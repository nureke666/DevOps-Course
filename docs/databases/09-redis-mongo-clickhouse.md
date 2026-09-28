---
title: "09. Redis, MongoDB, ClickHouse — обзорно"
description: "Кэш и сессии в Redis, документы в MongoDB, аналитика в ClickHouse — обзорно: зачем, как поднять, бэкап и метрики"
---

# 09. Redis, MongoDB, ClickHouse — обзорно

> Роадмап → Базы → **Обзорно:** *«Redis — кэш, очень часто в стэке проектов;
> MongoDB — встречается в проектах; ClickHouse — для логов, аналитики, и др.»*
>
> **После темы ты умеешь:** объяснить, зачем каждая из них, поднять, подключиться,
> снять бэкап и назвать ключевые метрики. Глубина — сознательно обзорная.

---

## 🗺️ Кто за что отвечает

```text:no-line-numbers
            ┌──────────────────────────────────────────────────────┐
            │                  типовой стек                        │
            └──────────────────────────────────────────────────────┘
  PostgreSQL         Redis              MongoDB            ClickHouse
  ──────────         ─────              ───────            ──────────
  основные данные    кэш, сессии,       документы          аналитика, логи,
  транзакции         счётчики,          без жёсткой схемы  события, метрики
  «истина»           очереди, локи      «гибкость»         «посчитать по
                     «быстро и          (Mongo)             миллиардам строк»
                      временно»
```

---

## 1. Redis

**Что это:** in-memory key-value хранилище. Всё живёт в оперативной памяти,
поэтому скорость — десятки-сотни тысяч операций в секунду.

### Зачем в проекте
| Сценарий | Как используется |
|----------|------------------|
| Кэш | Результат тяжёлого запроса кладут на 60 секунд |
| Сессии | Сессии пользователей вместо «липких» сессий на серверах |
| Счётчики / rate limit | `INCR` + `EXPIRE` |
| Распределённые блокировки | `SET key val NX PX 30000` |
| Простые очереди | Списки (`LPUSH`/`BRPOP`), Streams |
| Pub/Sub | Простые уведомления между сервисами |

### Поднять и потрогать
```bash
docker run -d --name redis -p 6379:6379 redis:7 redis-server --requirepass secret
docker exec -it redis redis-cli -a secret
```
```text:no-line-numbers
SET user:1:name "Иван"      # положить
GET user:1:name             # взять
SET session:abc "data" EX 3600   # с TTL в секундах
TTL session:abc             # сколько осталось
INCR page:views             # счётчик
LPUSH queue:jobs "task1"    # очередь
KEYS *                      # ⚠️ НИКОГДА на проде: блокирует сервер
SCAN 0 COUNT 100            # ⭐ правильный способ перебора
INFO                        # всё состояние сервера
DBSIZE                      # сколько ключей
FLUSHALL                    # ⚠️ удалить ВСЁ
```

### Что важно девопсу

| Тема | Суть |
|------|------|
| **Персистентность** | `RDB` — снапшот по расписанию (быстро, теряет последние изменения); `AOF` — журнал операций (надёжнее, больше диска). Часто включают оба |
| **maxmemory** | Обязательно задать лимит + политику вытеснения `maxmemory-policy` (`allkeys-lru` для чистого кэша, `noeviction` для очередей) |
| **Однопоточность** | Команды выполняются последовательно: одна тяжёлая (`KEYS`, `FLUSHALL`, большой `LRANGE`) блокирует всех |
| **HA** | Redis Sentinel (автоматический failover) или Redis Cluster (шардирование) |
| **Бэкап** | Копия `dump.rdb`/AOF, `BGSAVE`; для чистого кэша бэкап часто не нужен вовсе |
| **Мониторинг** | `redis_exporter`: память, hit rate, `evicted_keys`, `connected_clients`, `blocked_clients`, репликация |

```text:no-line-numbers
# redis.conf — минимум для прода
maxmemory 2gb
maxmemory-policy allkeys-lru
requirepass <пароль>
appendonly yes
bind 10.0.1.5
```

> ⭐ Главный вопрос про Redis на собесе: *«Что будет, если Redis упадёт?»*
> Если это кэш — приложение должно пережить (деградация производительности).
> Если там сессии или очереди — падение Redis равно падению сервиса, и это надо знать заранее.

---

## 2. MongoDB

**Что это:** документная база. Вместо строк в таблицах — JSON-подобные документы (BSON)
в коллекциях. Схема гибкая: документы в одной коллекции могут различаться.

```text:no-line-numbers
PostgreSQL                     MongoDB
─────────                      ───────
database                       database
table                          collection
row                            document   { "_id": …, "name": "Иван", "tags": ["a","b"] }
column                         field
JOIN                           $lookup (есть, но не основной приём — данные вкладывают)
```

### Поднять и потрогать
```bash
docker run -d --name mongo -p 27017:27017 \
  -e MONGO_INITDB_ROOT_USERNAME=root -e MONGO_INITDB_ROOT_PASSWORD=secret mongo:7
docker exec -it mongo mongosh -u root -p secret
```
```javascript
use shop
db.users.insertOne({ name: "Иван", email: "a@b.c", tags: ["vip"] })
db.users.find({ name: "Иван" })
db.users.updateOne({ name: "Иван" }, { $set: { tags: ["vip","new"] } })
db.users.deleteOne({ name: "Иван" })
db.users.createIndex({ email: 1 }, { unique: true })
db.users.countDocuments()
db.stats()                       // размеры
db.currentOp()                   // что выполняется сейчас
```

### Что важно девопсу

| Тема | Суть |
|------|------|
| **Replica set** | Базовая единица прода: 3 узла (primary + 2 secondary), автоматические выборы |
| **Sharding** | Горизонтальное масштабирование (config servers + mongos + шарды) — сложно, нужен не всем |
| **Бэкап** | `mongodump`/`mongorestore` (логический), снапшот тома, Ops Manager/облачные средства |
| **Аутентификация** | ⚠️ Исторически Mongo часто запускали без пароля — отсюда массовые утечки. Всегда `--auth` и закрытая сеть |
| **Мониторинг** | `mongodb_exporter`: соединения, операции/сек, репликация (`replication lag`), кэш WiredTiger, блокировки |
| **Диск** | Как и у любой базы — алерт на место |

```bash
mongodump --uri="mongodb://user:pass@host:27017/shop" --out=/backup/$(date +%F)
mongorestore --uri="mongodb://user:pass@host:27017" /backup/2026-09-13
```

---

## 3. ClickHouse

**Что это:** колоночная СУБД для аналитики (OLAP). Считает агрегаты по миллиардам строк
за секунды. Часто используется как хранилище логов и событий.

### Чем отличается от PostgreSQL
| | PostgreSQL | ClickHouse |
|---|-----------|-----------|
| Нагрузка | OLTP: много мелких операций | OLAP: тяжёлые аналитические запросы |
| Хранение | По строкам | По колонкам + сжатие |
| `UPDATE`/`DELETE` | Обычная операция | ⚠️ «Мутации» — тяжёлые и асинхронные, не для частого использования |
| Транзакции | Полноценные | Практически нет |
| Вставка | По одной строке нормально | ⭐ Только пачками (батчи по 1000+ строк) |
| Индексы | B-tree | Разреженный первичный индекс + сортировка данных |

### Поднять и потрогать
```bash
docker run -d --name ch -p 8123:8123 -p 9000:9000 \
  --ulimit nofile=262144:262144 clickhouse/clickhouse-server:latest
docker exec -it ch clickhouse-client
```
```sql
CREATE TABLE events (
    ts        DateTime,
    user_id   UInt64,
    event     String,
    duration  Float32
) ENGINE = MergeTree()
ORDER BY (ts, user_id)               -- ⭐ порядок сортировки = основной "индекс"
PARTITION BY toYYYYMM(ts)            -- партиции по месяцам: удобно удалять старое
TTL ts + INTERVAL 90 DAY;            -- ⭐ автоудаление старых данных

INSERT INTO events VALUES (now(), 1, 'login', 0.5);

SELECT event, count(), avg(duration)
FROM events WHERE ts > now() - INTERVAL 1 DAY
GROUP BY event ORDER BY count() DESC;

SELECT table, formatReadableSize(sum(bytes)) FROM system.parts
WHERE active GROUP BY table;
```

### Что важно девопсу

| Тема | Суть |
|------|------|
| **Движки таблиц** | `MergeTree` — основа; `ReplicatedMergeTree` — с репликацией через ZooKeeper/ClickHouse Keeper; `Distributed` — шардирование |
| **Партиции и TTL** | Данные удаляют партициями (`DROP PARTITION`) и по TTL, а не `DELETE` |
| **Вставка батчами** | Частые мелкие вставки убивают кластер (много мелких партов) — буферизуют на стороне приложения или через Kafka |
| **Кластер** | Шарды + реплики, координация через ClickHouse Keeper |
| **Бэкап** | `clickhouse-backup`, `FREEZE PARTITION`, копия в S3 |
| **Мониторинг** | Встроенные таблицы `system.*` + `clickhouse_exporter`: запросы, слияния, место, задержки репликации |

> 💡 Типичная роль ClickHouse у девопса: хранилище логов и метрик приложения,
> витрина для аналитики, приёмник событий из Kafka
> (см. темы «Очереди» и «Логирование»).

---

## 4. Сводная таблица «что мониторить и как бэкапить»

| | PostgreSQL | Redis | MongoDB | ClickHouse |
|---|-----------|-------|---------|------------|
| Порт | 5432 | 6379 | 27017 | 8123 / 9000 |
| CLI | `psql` | `redis-cli` | `mongosh` | `clickhouse-client` |
| Бэкап | `pg_dump`, WAL-G | `dump.rdb`/AOF, `BGSAVE` | `mongodump` | `clickhouse-backup`, FREEZE |
| Репликация | streaming/логическая | Sentinel / Cluster | Replica set | ReplicatedMergeTree |
| Экспортер | postgres_exporter | redis_exporter | mongodb_exporter | встроенные `system.*` |
| Топ-метрики | соединения, лаг, диск | память, evictions, hit rate | соединения, лаг, кэш | запросы, слияния, диск |
| Главная грабля | bloat, `pg_wal`, забытые транзакции | `KEYS` и отсутствие `maxmemory` | запуск без auth | мелкие вставки, мутации |

---

## 💼 Как это в DevOps

- Redis встречается почти в каждом проекте. Минимум, который спрашивают: зачем он тут,
  что будет при падении, задан ли `maxmemory` и политика вытеснения, есть ли персистентность.
- MongoDB чаще достаётся «по наследству». Задача девопса — replica set, аутентификация,
  бэкапы `mongodump` и мониторинг лага.
- ClickHouse обычно появляется под логи/аналитику. Девопс отвечает за партиции, TTL
  (иначе диск кончится), батчевую вставку и репликацию.
- Общее для всех: диск, бэкап с проверкой восстановления, экспортер метрик, алерты,
  ограниченный сетевой доступ и пароли в Vault.
- Учить их вглубь заранее не нужно — нужно уметь поднять, подключиться, снять бэкап
  и снять метрики. Остальное добирается на конкретном проекте.

---

## 📌 Шпаргалка

```bash
# Redis
redis-cli -h host -a pass INFO memory
redis-cli --scan --pattern 'session:*' | head       # вместо KEYS
redis-cli -a pass CONFIG GET maxmemory
redis-cli -a pass BGSAVE

# MongoDB
mongosh "mongodb://user:pass@host:27017/db" --eval 'db.stats()'
mongosh --eval 'rs.status()'                        # состояние replica set
mongodump --uri="…" --out=/backup/$(date +%F)

# ClickHouse
clickhouse-client -q "SELECT count() FROM events"
clickhouse-client -q "SELECT * FROM system.parts WHERE active LIMIT 5"
clickhouse-client -q "SELECT query, elapsed FROM system.processes"
clickhouse-client -q "ALTER TABLE events DROP PARTITION '202401'"
```

---

## 🧠 Что запомнить

1. Redis — память: быстро, но при падении теряется всё, что не сохранено (RDB/AOF).
2. ⭐ В Redis всегда задают `maxmemory` и `maxmemory-policy`; `KEYS *` на проде запрещён.
3. Redis однопоточен: одна тяжёлая команда блокирует всех клиентов.
4. Вопрос «что будет, если Redis упадёт» надо знать заранее: кэш переживём, сессии — нет.
5. MongoDB — документы вместо строк; прод-минимум — replica set из трёх узлов.
6. MongoDB без аутентификации в открытой сети — классический источник утечек.
7. ClickHouse — колоночная OLAP-база: агрегаты по миллиардам строк, но не для транзакций.
8. В ClickHouse вставляют батчами, старое удаляют партициями и TTL, а не `DELETE`.
9. У каждой базы свой экспортер и свой список метрик, но принцип один: диск, соединения,
   задержки, репликация, бэкапы.
10. Глубина по этим трём — обзорная; главное уметь поднять, подключиться, забэкапить
    и снять метрики.

---

## Задачи

> Стенд: три контейнера. Поднимай по одному — вместе они съедят память ноутбука.

---

### Блок A. Теория

**A1.** Для чего в проекте берут Redis? Назови пять сценариев.

<details><summary>Ответ</summary>

Кэш тяжёлых запросов, сессии, счётчики и rate limit, распределённые блокировки,
простые очереди и pub/sub.

</details>

**A2.** Чем `RDB` отличается от `AOF`? Когда какой выбирают?

<details><summary>Ответ</summary>

RDB — периодический снапшот всей базы (быстрое восстановление, компактно, но
теряются изменения с момента последнего снапшота). AOF — журнал всех записывающих команд
(меньше потерь, больше диска и дольше восстановление). Часто включают оба.

</details>

**A3.** ⭐ Что произойдёт, если не задать `maxmemory` в Redis?

<details><summary>Ответ</summary>

Redis будет расти, пока не съест память сервера: дальше своп, OOM killer
и падение либо Redis, либо соседних сервисов.

</details>

**A4.** Что делают политики `allkeys-lru` и `noeviction`? Для чего каждая?

<details><summary>Ответ</summary>

`allkeys-lru` вытесняет давно не используемые ключи — подходит для чистого кэша.
`noeviction` отвечает клиенту ошибкой при заполнении — нужен там, где терять данные нельзя
(очереди, сессии), но тогда за памятью надо следить отдельно.

</details>

**A5.** Почему `KEYS *` на проде — запрещённая команда и чем её заменить?

<details><summary>Ответ</summary>

`KEYS` сканирует всё пространство ключей и, поскольку Redis однопоточен,
блокирует сервер на всё время выполнения. Заменяют на `SCAN` (курсорный обход)
или `redis-cli --scan --pattern`.

</details>

**A6.** Чем Redis Sentinel отличается от Redis Cluster?

<details><summary>Ответ</summary>

Sentinel следит за одним мастером и его репликами и делает автоматический failover
(данные целиком на каждом узле). Cluster шардирует данные по слотам между несколькими
мастерами — это про объём и масштабирование.

</details>

**A7.** Что будет с приложением, если Redis упадёт? От чего зависит ответ?

<details><summary>Ответ</summary>

Зависит от роли: если Redis — только кэш, приложение должно пережить падение
с деградацией (нагрузка уедет на базу). Если там сессии, очереди или блокировки —
падение равносильно недоступности сервиса.

</details>

**A8.** Как соотносятся понятия PostgreSQL и MongoDB: база, таблица, строка, колонка?

<details><summary>Ответ</summary>

database → database, table → collection, row → document, column → field.

</details>

**A9.** Что такое replica set и сколько узлов нужно минимум? Почему нечётное число?

<details><summary>Ответ</summary>

Replica set — группа узлов с одним primary и несколькими secondary, с
автоматическими выборами. Минимум для прода — 3 узла; нечётное число нужно для кворума
при выборах.

</details>

**A10.** Чем `mongodump` отличается от снапшота тома?

<details><summary>Ответ</summary>

`mongodump` — логический бэкап (BSON-дамп коллекций): переносим, выборочен,
медленнее на больших объёмах. Снапшот тома — физическая копия: быстро, но требует
согласованности файлов и того же окружения.

</details>

**A11.** Почему MongoDB исторически «светилась» в новостях об утечках?

<details><summary>Ответ</summary>

Ранние версии по умолчанию слушали все интерфейсы без аутентификации;
базы находили сканированием и выкачивали. Отсюда правило: `--auth` и закрытая сеть всегда.

</details>

**A12.** Чем колоночное хранение ClickHouse отличается от строчного и почему это быстрее
для аналитики?

<details><summary>Ответ</summary>

Данные хранятся по колонкам: для агрегата читается только нужная колонка,
а не все поля каждой строки; колонки однородны и хорошо сжимаются, что резко уменьшает
объём чтения с диска.

</details>

**A13.** Почему в ClickHouse нельзя вставлять по одной строке?

<details><summary>Ответ</summary>

Каждая вставка создаёт новый парт на диске; тысячи мелких партов приводят к
постоянным слияниям и ошибке `Too many parts`. Вставляют пачками (1000+ строк) или
через буфер/Kafka.

</details>

**A14.** Как в ClickHouse удаляют старые данные и почему не через `DELETE`?

<details><summary>Ответ</summary>

Партициями (`ALTER TABLE … DROP PARTITION`) и через `TTL`. `DELETE` в ClickHouse —
тяжёлая асинхронная мутация, переписывающая парты.

</details>

**A15.** Составь таблицу «порт / CLI / бэкап / экспортер» для всех трёх систем.

<details><summary>Ответ</summary>

PostgreSQL 5432 / `psql` / `pg_dump`+WAL-G / postgres_exporter;
Redis 6379 / `redis-cli` / RDB+AOF / redis_exporter;
MongoDB 27017 / `mongosh` / `mongodump` / mongodb_exporter;
ClickHouse 8123 и 9000 / `clickhouse-client` / `clickhouse-backup` / `system.*` + exporter.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  redis-cli -a pass INFO memory
B2.  redis-cli -a pass CONFIG GET maxmemory-policy
B3.  redis-cli --scan --pattern 'session:*'
B4.  redis-cli -a pass BGSAVE
B5.  redis-cli -a pass FLUSHALL
B6.  mongosh --eval 'rs.status()'
B7.  mongodump --uri="mongodb://…/shop" --out=/backup/2026-09-13
B8.  clickhouse-client -q "SELECT table, formatReadableSize(sum(bytes)) FROM system.parts WHERE active GROUP BY table"
B9.  clickhouse-client -q "ALTER TABLE events DROP PARTITION '202401'"
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1. Показывает раздел статистики по памяти (used_memory, фрагментация, maxmemory).
B2. Текущая политика вытеснения.
B3. Безопасный (курсорный) перебор ключей по шаблону.
B4. Асинхронно создаёт RDB-снапшот.
B5. Удаляет все ключи во всех базах — крайне опасная команда.
B6. Состояние replica set: кто primary, лаг, здоровье узлов.
B7. Логический бэкап базы в каталог.
B8. Размер таблиц ClickHouse по активным партам.
B9. Мгновенно удаляет партицию за январь 2024 — штатный способ чистки.
```

</details>

Оцени фрагменты:

**B10.** `redis.conf`: `maxmemory` не задан, `maxmemory-policy noeviction`

<details><summary>Ответ</summary>

Без `maxmemory` и с `noeviction` Redis будет расти до отказа памяти сервера.

</details>

**B11.** `redis-cli KEYS 'user:*'` — на проде с 20 млн ключей

<details><summary>Ответ</summary>

Блокировка однопоточного сервера на секунды-минуты: все клиенты встанут.

</details>

**B12.** MongoDB запущен без `--auth`, порт 27017 открыт наружу

<details><summary>Ответ</summary>

Открытая база без аутентификации — утечка данных вопрос времени.

</details>

**B13.** ClickHouse: `INSERT` одной строкой на каждое событие приложения

<details><summary>Ответ</summary>

Мелкие вставки → множество партов → `Too many parts`.

</details>

**B14.** ClickHouse: таблица без `PARTITION BY` и без `TTL`, пишем логи год

<details><summary>Ответ</summary>

Без партиций и TTL старые данные не удалить дёшево; диск закончится.

</details>

**B15.** Redis используется как основная очередь задач, persistence выключен

<details><summary>Ответ</summary>

Очередь без персистентности: перезапуск Redis = потеря задач.

</details>

---

### Блок C. Практика

#### C1. Redis: основы
1. Подними Redis с паролем, зайди `redis-cli`.
2. Поработай с `SET/GET/EXPIRE/TTL/INCR/LPUSH/BRPOP`.
3. Посмотри `INFO`, `DBSIZE`, `CONFIG GET maxmemory`.

#### C2. 🔑 Redis: вытеснение
1. Задай `maxmemory 10mb` и `maxmemory-policy allkeys-lru`.
2. Залей данные до упора (`redis-cli DEBUG POPULATE 1000000` или циклом).
3. Посмотри `INFO stats | grep evicted_keys` и объясни, что произошло.
4. Поменяй политику на `noeviction` и повтори — какая ошибка у клиента?

<details><summary>Ответ</summary>

С `allkeys-lru` растёт `evicted_keys`, память держится у лимита.
С `noeviction` клиент получает `OOM command not allowed when used memory > 'maxmemory'`.

</details>

#### C3. Redis: персистентность
1. Включи `appendonly yes`, положи данные, перезапусти контейнер — данные на месте?
2. Отключи персистентность, повтори — сделай вывод.
3. Найди `dump.rdb` и `appendonly.aof` внутри контейнера.

<details><summary>Ответ</summary>

С `appendonly yes` данные переживают рестарт; без персистентности — теряются.

</details>

#### C4. Redis: мониторинг
Подними `redis_exporter`, добавь таргет в Prometheus, найди метрики:
использованная память, hit rate, `evicted_keys`, `connected_clients`.
Придумай три алерта.

<details><summary>Ответ</summary>

Хорошие алерты: использование памяти > 85% от `maxmemory`, рост `evicted_keys`
там, где вытеснение недопустимо, `redis_up == 0`, низкий hit rate для кэша.

</details>

#### C5. MongoDB: основы
1. Подними Mongo с root-паролем, зайди `mongosh`.
2. Сделай `insertOne`, `find`, `updateOne`, `createIndex`, `countDocuments`.
3. Посмотри `db.stats()` и `db.currentOp()`.

#### C6. MongoDB: бэкап и восстановление
Сделай `mongodump`, удали коллекцию, восстанови `mongorestore`, сверь число документов.

#### C7. MongoDB: replica set (со звёздочкой)
Подними три узла в docker-compose, инициализируй replica set (`rs.initiate()`),
посмотри `rs.status()`, останови primary и понаблюдай выборы нового.

<details><summary>Ответ</summary>

После остановки primary secondary проводят выборы; новый primary появляется
за несколько секунд — видно в `rs.status()`.

</details>

#### C8. ClickHouse: основы
1. Подними ClickHouse, создай таблицу `events` с `MergeTree`, `ORDER BY`, `PARTITION BY`, `TTL`.
2. Вставь 1 млн строк одним батчем (`INSERT … SELECT … FROM numbers(1000000)`).
3. Сделай агрегирующий запрос и замерь время.
4. Сравни: тот же объём и тот же запрос в PostgreSQL.

<details><summary>Ответ</summary>

Агрегат по 1 млн строк в ClickHouse обычно выполняется за десятки миллисекунд;
в PostgreSQL тот же запрос заметно дольше (зависит от индексов и памяти).

</details>

#### C9. ClickHouse: партиции и место
1. Посмотри `system.parts`, размер таблицы и сжатие (сравни `bytes` и `data_uncompressed_bytes`).
2. Удали одну партицию `ALTER TABLE … DROP PARTITION`.
3. Проверь, как работает TTL.

<details><summary>Ответ</summary>

Сжатие в ClickHouse часто в 5-10 раз; после `DROP PARTITION` размер падает мгновенно,
в отличие от `DELETE` в PostgreSQL.

</details>

#### C10. Сравнительная записка
Напиши одностраничный документ: какие из четырёх баз есть (или были бы) на твоём проекте,
зачем каждая, кто её бэкапит, что мониторится, что будет при падении.

---

### Блок D. Инциденты

**D1.** Redis съел всю память сервера, ОС начала убивать процессы. Что было не настроено?

<details><summary>Ответ</summary>

Не задан `maxmemory` (и политика вытеснения), нет лимита памяти у контейнера,
нет алерта на использование памяти.

</details>

**D2.** После перезапуска Redis сессии пользователей пропали. Причина и решения.

<details><summary>Ответ</summary>

Персистентность выключена (или был только RDB и снапшот устарел). Решения:
включить AOF, хранить сессии в базе/с репликацией, принять потерю сессий как допустимую.

</details>

**D3.** Приложение «тормозит», в Redis `blocked_clients` растёт. Гипотезы?

<details><summary>Ответ</summary>

Блокирующие команды (`BRPOP`/`BLPOP`) — это нормально для очередей; но также
тяжёлая команда, блокирующая однопоточный сервер, нехватка памяти, медленный диск при
`BGSAVE`/AOF-rewrite, сетевые проблемы.

</details>

**D4.** Кто-то выполнил `KEYS *` на проде с 30 млн ключей. Что произошло со всеми клиентами?

<details><summary>Ответ</summary>

Сервер был заблокирован на время перебора всех ключей: все клиенты получили
таймауты, выросли очереди на стороне приложения, возможен каскадный отказ.

</details>

**D5.** Redis используется как очередь, включён `allkeys-lru`. Что может пойти не так?

<details><summary>Ответ</summary>

LRU может вытеснить сообщения очереди — задачи потеряются. Для очередей нужна
политика `noeviction` (и отдельный инстанс Redis, а не общий с кэшем).

</details>

**D6.** MongoDB: реплика отстала на час, primary под нагрузкой. Что смотреть?

<details><summary>Ответ</summary>

Нагрузку записи на primary, oplog window (хватает ли размера oplog),
диск и IO на secondary, сеть, долгие операции (`db.currentOp()`), индексы.

</details>

**D7.** Обнаружено, что Mongo доступна из интернета без пароля. Порядок действий.

<details><summary>Ответ</summary>

Немедленно закрыть доступ (firewall/security group), включить `--auth`, завести
роли и пароли, проверить логи на предмет чужих подключений, считать данные
скомпрометированными, уведомить ответственных, сменить все секреты, разобрать инцидент.

</details>

**D8.** ClickHouse: `Too many parts` в логах, вставки начали падать. Причина и лечение.

<details><summary>Ответ</summary>

Слишком частые мелкие вставки. Лечение: батчить на стороне приложения,
использовать буферную таблицу/Kafka, увеличить интервал вставки; временно — дождаться слияний.

</details>

**D9.** ClickHouse: диск заполнился логами за год. Что нужно было настроить заранее?

<details><summary>Ответ</summary>

`PARTITION BY` и `TTL` (плюс мониторинг места и retention по партициям).

</details>

**D10.** Разработчики просят выполнять частые `UPDATE` в ClickHouse. Что объяснишь
и что предложишь вместо этого?

<details><summary>Ответ</summary>

ClickHouse не предназначен для частых точечных обновлений: мутации переписывают
парты целиком. Альтернативы: `ReplacingMergeTree`/`CollapsingMergeTree` с версионностью,
хранение изменяемых данных в PostgreSQL, пересчёт витрин.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Зачем в проекте Redis и что будет, если он упадёт?

<details><summary>Ответ</summary>

Кэш, сессии, счётчики, блокировки, очереди; последствия падения зависят от роли:
кэш — деградация, сессии/очереди — отказ сервиса.

</details>

**2.** Как настроить ограничение памяти в Redis и что такое политики вытеснения?

<details><summary>Ответ</summary>

`maxmemory` + `maxmemory-policy`; `allkeys-lru` для кэша, `noeviction` там, где
терять данные нельзя.

</details>

**3.** Чем RDB отличается от AOF?

<details><summary>Ответ</summary>

RDB — снапшоты (быстро, возможны потери), AOF — журнал команд (надёжнее, объёмнее).

</details>

**4.** Почему `KEYS` нельзя использовать на проде?

<details><summary>Ответ</summary>

Однопоточность: полный перебор ключей блокирует сервер; нужен `SCAN`.

</details>

**5.** Как обеспечить отказоустойчивость Redis?

<details><summary>Ответ</summary>

Sentinel (failover) или Cluster (шардирование), плюс персистентность и мониторинг.

</details>

**6.** Что такое replica set в MongoDB?

<details><summary>Ответ</summary>

Группа узлов с primary и secondary, автоматическими выборами; минимум 3 узла.

</details>

**7.** Как делать бэкап MongoDB?

<details><summary>Ответ</summary>

`mongodump`/`mongorestore`, снапшоты томов, облачные средства; обязательна проверка
восстановления.

</details>

**8.** Чем ClickHouse отличается от PostgreSQL и когда его берут?

<details><summary>Ответ</summary>

Колоночная OLAP-база: быстрые агрегаты по огромным объёмам, но без нормальных
транзакций и точечных обновлений; берут под аналитику, логи, события.

</details>

**9.** Почему в ClickHouse вставляют батчами?

<details><summary>Ответ</summary>

Каждая вставка создаёт парт; мелкие вставки порождают лавину слияний и ошибку `Too many parts`.

</details>

**10.** Как удалять старые данные в ClickHouse?

<details><summary>Ответ</summary>

`TTL` и `DROP PARTITION`, а не `DELETE`.

</details>

---

### 🎯 Чек-лист

- [ ] Поднял Redis, поработал с ключами, TTL и счётчиками
- [ ] ⭐ Знаю про `maxmemory`, политики вытеснения и запрет `KEYS` на проде
- [ ] Понимаю разницу RDB/AOF и что будет при падении Redis
- [ ] Поднял MongoDB, сделал `mongodump`/`mongorestore`
- [ ] Знаю, что такое replica set и почему нужен `--auth`
- [ ] Поднял ClickHouse, создал `MergeTree` с партициями и TTL
- [ ] Понимаю, почему вставляют батчами и удаляют партициями
- [ ] Могу сравнить все четыре базы по назначению, бэкапу и метрикам
- [ ] Знаю, какой экспортер ставить для каждой
