---
title: "04. postgresql.conf — основные параметры"
description: "Память, соединения, WAL и checkpoint, autovacuum, таймауты, логирование и pg_stat_statements"
---

# 04. `postgresql.conf` — основные параметры

> Роадмап → Базы → PostgreSQL → *«`postgresql.conf` (основные параметры)»*.
>
> **После темы ты умеешь:** осознанно выставить память, соединения, WAL, autovacuum,
> таймауты и логирование; объяснить, почему выбрал именно такие значения.

---

## 🗺️ Карта параметров: на что они влияют

```text:no-line-numbers
 ┌──────────────┬────────────────────────────────────────────────────────┐
 │ ПАМЯТЬ       │ shared_buffers · work_mem · maintenance_work_mem        │
 │              │ effective_cache_size                    → скорость чтения│
 ├──────────────┼────────────────────────────────────────────────────────┤
 │ СОЕДИНЕНИЯ   │ max_connections · superuser_reserved_connections         │
 │              │                                → сколько клиентов влезет│
 ├──────────────┼────────────────────────────────────────────────────────┤
 │ WAL / ДИСК   │ wal_level · max_wal_size · checkpoint_timeout            │
 │              │ synchronous_commit · archive_mode → надёжность + реплика │
 ├──────────────┼────────────────────────────────────────────────────────┤
 │ AUTOVACUUM   │ autovacuum_* · vacuum_cost_*            → борьба с bloat │
 ├──────────────┼────────────────────────────────────────────────────────┤
 │ ТАЙМАУТЫ     │ statement_timeout · idle_in_transaction_session_timeout  │
 │              │ lock_timeout                        → защита от зависших │
 ├──────────────┼────────────────────────────────────────────────────────┤
 │ ЛОГИ         │ logging_collector · log_min_duration_statement · префикс │
 │              │                          → возможность разобрать инцидент│
 └──────────────┴────────────────────────────────────────────────────────┘
```

---

## 1. Как менять параметры (три способа)

```bash
# 1. Правка файла (классика, хорошо ложится в Ansible)
sudo -u postgres vim /etc/postgresql/16/main/postgresql.conf
sudo systemctl reload postgresql@16-main
```
```sql
-- 2. ALTER SYSTEM: пишет в postgresql.auto.conf, который читается ПОСЛЕ основного
ALTER SYSTEM SET work_mem = '32MB';
SELECT pg_reload_conf();
ALTER SYSTEM RESET work_mem;        -- отменить

-- 3. Точечно: на сессию, на роль, на базу
SET work_mem = '256MB';                          -- текущая сессия
ALTER ROLE analyst SET work_mem = '256MB';       -- для аналитика
ALTER DATABASE shop SET statement_timeout = '30s';
```

> ⚠️ Грабля: правишь `postgresql.conf`, а значение не меняется, потому что тот же параметр
> переопределён в `postgresql.auto.conf` (`ALTER SYSTEM`). Проверяй источник:

```sql
SELECT name, setting, unit, source, sourcefile, pending_restart
FROM pg_settings WHERE name IN ('shared_buffers','work_mem','max_connections');

SHOW config_file;        -- какой файл вообще читается
```

Поддерживаемая практика — каталог `conf.d`:
```ini
# postgresql.conf
include_dir = 'conf.d'
```
```text:no-line-numbers
/etc/postgresql/16/main/conf.d/
├── 10-memory.conf
├── 20-wal.conf
└── 30-logging.conf     ← раскладывается Ansible'ом, основной файл не трогаем
```

---

## 2. Память

| Параметр | Что это | Ориентир | Рестарт |
|----------|---------|----------|---------|
| `shared_buffers` | Общий кэш страниц базы в RAM | **~25% RAM** (редко >40%) | да |
| `effective_cache_size` | Подсказка планировщику, сколько всего кэша (БД+ОС) | **~50-75% RAM** | нет |
| `work_mem` | Память **на одну операцию** сортировки/хеша | 16-64 МБ (см. ниже) | нет |
| `maintenance_work_mem` | Память под VACUUM, CREATE INDEX | 256 МБ - 2 ГБ | нет |
| `temp_buffers` | Кэш временных таблиц на сессию | 8-64 МБ | нет |

### ⭐ Ловушка `work_mem`

```text:no-line-numbers
work_mem — это НЕ на сервер и НЕ на соединение, а на КАЖДУЮ операцию в запросе.

100 соединений × 3 сортировки в запросе × work_mem 64MB = до 19 ГБ 💥
```
Поэтому `work_mem` держат скромным глобально и поднимают точечно
(`SET work_mem` в сессии аналитика или `ALTER ROLE`).

Признак, что `work_mem` мал: в `EXPLAIN (ANALYZE, BUFFERS)` видно
`Sort Method: external merge Disk: 120400kB` — сортировка ушла на диск.

```ini
# сервер 16 ГБ RAM, OLTP-нагрузка
shared_buffers = 4GB
effective_cache_size = 12GB
work_mem = 32MB
maintenance_work_mem = 1GB
```

> 💡 Для стартовой конфигурации удобен генератор pgtune (`https://pgtune.leopard.in.ua/`):
> задаёшь RAM/CPU/тип нагрузки и получаешь адекватный набор значений. Это старт, а не финал.

---

## 3. Соединения

```ini
max_connections = 200                  # рестарт
superuser_reserved_connections = 3     # чтобы админ смог зайти, когда всё занято
```

```text:no-line-numbers
Каждое соединение = процесс.
Память на соединение ≈ несколько МБ + work_mem на операцию.
1000 соединений ⇒ 1000 процессов ⇒ контекст-свитчи и OOM.
```

Правильное решение — **PgBouncer** (пул соединений):

```text:no-line-numbers
app (500 соединений) ──► PgBouncer ──► PostgreSQL (20 реальных соединений)
```
```ini
# pgbouncer.ini
[databases]
shop = host=10.0.1.5 port=5432 dbname=shop

[pgbouncer]
listen_port = 6432
pool_mode = transaction        # ⭐ обычный выбор для веб-приложений
max_client_conn = 1000
default_pool_size = 20
```
| `pool_mode` | Когда соединение возвращается в пул | Ограничения |
|-------------|-----------------------------------|-------------|
| `session` | После отключения клиента | Никаких, но и пользы мало |
| `transaction` | После каждой транзакции | ⭐ Нельзя prepared statements «в лоб», временные таблицы между транзакциями |
| `statement` | После каждого запроса | Запрещены многооператорные транзакции |

Мониторинг: `SELECT count(*), state FROM pg_stat_activity GROUP BY state;`

---

## 4. WAL, checkpoint и надёжность

```ini
wal_level = replica            # minimal | replica | logical  (рестарт)
max_wal_size = 4GB             # мягкий порог, после которого запускается checkpoint
min_wal_size = 1GB
checkpoint_timeout = 15min     # не реже чем раз в 15 минут
checkpoint_completion_target = 0.9   # размазать запись checkpoint по времени
synchronous_commit = on        # ⭐ подтверждать COMMIT только после fsync WAL
wal_compression = on
archive_mode = on              # для PITR (тема 05)
archive_command = 'test ! -f /arch/%f && cp %p /arch/%f'
```

| Параметр | Если сделать меньше/выключить | Если больше/включить |
|----------|-------------------------------|----------------------|
| `max_wal_size` | Частые checkpoint → всплески записи | Реже checkpoint, но дольше восстановление после сбоя и больше места под `pg_wal` |
| `synchronous_commit = off` | Быстрее запись, но при сбое теряются последние транзакции (данные в ОС-буфере) | Гарантия durability |
| `fsync = off` | ⚠️ Возможна полная порча кластера | — |
| `wal_level = logical` | Нужен для логической репликации/CDC | Чуть больше объём WAL |

> ⭐ `synchronous_commit = off` — единственный «безопасный» способ ускорить запись:
> он не портит базу, но теряет последние транзакции (обычно до 3×`wal_writer_delay`).
> Для аналитических/фоновых баз иногда приемлемо, для платежей — нет.

Контроль:
```sql
SELECT * FROM pg_stat_bgwriter;        -- checkpoints_timed vs checkpoints_req
```
Если `checkpoints_req` (внеплановые, по объёму WAL) заметно больше `checkpoints_timed` —
`max_wal_size` мал.

---

## 5. Autovacuum

```ini
autovacuum = on                            # ⚠️ НИКОГДА не выключать
autovacuum_max_workers = 5
autovacuum_naptime = 30s
autovacuum_vacuum_scale_factor = 0.1       # запуск при 10% мёртвых строк (дефолт 0.2)
autovacuum_analyze_scale_factor = 0.05
autovacuum_vacuum_cost_limit = 2000        # «разрешить работать быстрее» (дефолт 200)
```

```text:no-line-numbers
Таблица 100 млн строк, scale_factor = 0.2
⇒ autovacuum придёт только после 20 млн мёртвых строк. К этому моменту таблица распухла.
Для больших таблиц ставят настройки индивидуально:
```
```sql
ALTER TABLE events SET (autovacuum_vacuum_scale_factor = 0.01,
                        autovacuum_vacuum_threshold = 10000);
```

Диагностика:
```sql
SELECT relname, n_live_tup, n_dead_tup, last_autovacuum, last_autoanalyze
FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 10;

SELECT pid, query, now()-xact_start AS dur FROM pg_stat_activity
WHERE query LIKE 'autovacuum%';
```

Что мешает autovacuum работать (и вызывает bloat даже при включённом autovacuum):
- долгие открытые транзакции и `idle in transaction`;
- неактивные слоты репликации (`pg_replication_slots.active = false`);
- отставшая реплика с `hot_standby_feedback = on`;
- `prepared transactions`, забытые в статусе `prepared`.

---

## 6. Таймауты — дешёвая защита от инцидентов

```ini
statement_timeout = 0                        # глобально обычно 0 (не рубить всё подряд)
idle_in_transaction_session_timeout = 5min   # ⭐ убивает забытые транзакции
lock_timeout = 5s                            # не ждать блокировку вечно
```
Точечно — там, где это безопасно:
```sql
ALTER DATABASE shop SET statement_timeout = '30s';
ALTER ROLE analyst SET statement_timeout = '5min';
ALTER ROLE migrator SET lock_timeout = '3s';   -- миграция не встанет в очередь надолго
```

> 💡 `idle_in_transaction_session_timeout` — одна строка конфига, которая закрывает
> самый частый класс инцидентов «база встала из-за забытой транзакции».

---

## 7. Логирование

```ini
logging_collector = on
log_directory = 'log'
log_filename = 'postgresql-%Y-%m-%d.log'
log_rotation_age = 1d
log_rotation_size = 100MB

log_line_prefix = '%m [%p] %u@%d %a %h '   # время, pid, роль@база, приложение, хост
log_min_duration_statement = 1000          # ⭐ логировать запросы дольше 1 сек
log_checkpoints = on
log_connections = on
log_disconnections = on
log_lock_waits = on                        # ⭐ кто кого блокировал
log_temp_files = 0                         # все временные файлы (признак малого work_mem)
log_autovacuum_min_duration = 0
```

| Параметр | Зачем |
|----------|-------|
| `log_min_duration_statement` | Найти медленные запросы без сторонних инструментов |
| `log_lock_waits` | Понять, кто держал блокировку в момент инцидента |
| `log_temp_files` | Увидеть, что сортировки уходят на диск (мал `work_mem`) |
| `log_checkpoints` | Понять, не упирается ли база в запись |
| `log_statement = 'ddl'` | Аудит структурных изменений (`all` — только при разборе, шумно и опасно для секретов) |

Расширение `pg_stat_statements` — стандарт для поиска тяжёлых запросов:
```ini
shared_preload_libraries = 'pg_stat_statements'   # рестарт
```
```sql
CREATE EXTENSION pg_stat_statements;
SELECT calls, round(mean_exec_time::numeric,2) AS avg_ms, query
FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10;
```

---

## 8. Базовый конфиг «сервер 16 ГБ, OLTP» (шпаргалка целиком)

```ini
# --- память ---
shared_buffers = 4GB
effective_cache_size = 12GB
work_mem = 32MB
maintenance_work_mem = 1GB

# --- соединения ---
max_connections = 200
superuser_reserved_connections = 3

# --- WAL ---
wal_level = replica
max_wal_size = 4GB
min_wal_size = 1GB
checkpoint_timeout = 15min
checkpoint_completion_target = 0.9
synchronous_commit = on
wal_compression = on

# --- планировщик (для SSD/NVMe) ---
random_page_cost = 1.1
effective_io_concurrency = 200

# --- autovacuum ---
autovacuum_vacuum_scale_factor = 0.1
autovacuum_analyze_scale_factor = 0.05
autovacuum_vacuum_cost_limit = 2000

# --- таймауты ---
idle_in_transaction_session_timeout = 5min
lock_timeout = 5s

# --- логи ---
logging_collector = on
log_line_prefix = '%m [%p] %u@%d %a %h '
log_min_duration_statement = 1000
log_checkpoints = on
log_lock_waits = on
log_temp_files = 0
log_autovacuum_min_duration = 0
shared_preload_libraries = 'pg_stat_statements'
```

> ⚠️ `random_page_cost = 4` (дефолт) — наследие HDD. На SSD это заставляет планировщик
> недооценивать индексы и выбирать `Seq Scan`. На SSD ставят `1.1`.

---

## 💼 Как это в DevOps

- Конфиг базы живёт в git (роль Ansible + шаблон), а не «правился руками год назад».
- На новый сервер конфиг генерируют от размера RAM/CPU (pgtune как отправная точка),
  потом корректируют по метрикам — см. [тему 07](/databases/07-db-monitoring).
- Изменение параметров прода — это MR с обоснованием и указанием, нужен ли рестарт
  (то есть окно обслуживания).
- Таймауты и логирование — то, что настраивают **сразу**, ещё до появления нагрузки:
  без них разбор первого же инцидента превращается в гадание.
- PgBouncer появляется не «когда упрёмся», а сразу, если приложение в нескольких репликах
  или в Kubernetes (каждый под держит свой пул).

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Посмотреть значение и его источник | `SELECT name,setting,source,sourcefile FROM pg_settings WHERE name='…';` |
| Изменить без правки файла | `ALTER SYSTEM SET x = 'y'; SELECT pg_reload_conf();` |
| Отменить `ALTER SYSTEM` | `ALTER SYSTEM RESET x;` |
| Узнать, что ждёт рестарта | `SELECT name FROM pg_settings WHERE pending_restart;` |
| Память под кэш | `shared_buffers` ≈ 25% RAM (рестарт) |
| Память под сортировку | `work_mem` — **на операцию**, не на сервер |
| Много клиентов | PgBouncer `pool_mode = transaction` |
| Реже checkpoint | Больше `max_wal_size` |
| Надёжность записи | `synchronous_commit = on`, `fsync = on` |
| Меньше bloat на большой таблице | `ALTER TABLE … SET (autovacuum_vacuum_scale_factor=0.01)` |
| Убивать забытые транзакции | `idle_in_transaction_session_timeout = 5min` |
| Ловить медленные запросы | `log_min_duration_statement = 1000` |
| Ловить блокировки | `log_lock_waits = on` |
| Топ тяжёлых запросов | `pg_stat_statements` |
| Быстрые диски | `random_page_cost = 1.1` |

---

## 🧠 Что запомнить

1. Три способа менять параметры: файл, `ALTER SYSTEM` (`postgresql.auto.conf`),
   точечно на сессию/роль/базу. Источник значения показывает `pg_settings.source`.
2. `shared_buffers` ≈ 25% RAM и требует рестарта; `effective_cache_size` — только подсказка планировщику.
3. ⭐ `work_mem` выделяется на **каждую операцию**, поэтому глобально его держат небольшим.
4. Соединение = процесс: вместо роста `max_connections` ставят PgBouncer в режиме `transaction`.
5. `synchronous_commit = off` ускоряет запись ценой потери последних транзакций;
   `fsync = off` — путь к порче кластера.
6. Мало `max_wal_size` → частые внеплановые checkpoint (видно в `pg_stat_bgwriter`).
7. Autovacuum не выключают; для больших таблиц задают персональные `scale_factor`.
8. Autovacuum блокируют долгие транзакции, неактивные слоты репликации и отставшие реплики.
9. `idle_in_transaction_session_timeout` и `lock_timeout` — самая дешёвая страховка от инцидентов.
10. Логи (`log_min_duration_statement`, `log_lock_waits`, `log_temp_files`) и
    `pg_stat_statements` настраивают заранее — иначе разбирать инцидент будет нечем.

---

## Задачи

> Стенд: PostgreSQL, где не жалко перезапускать сервис и менять параметры.

---

### Блок A. Теория

**A1.** Назови три способа изменить параметр PostgreSQL. Чем они отличаются по области действия?

<details><summary>Ответ</summary>

Правка `postgresql.conf` (весь кластер, версионируется в git);
`ALTER SYSTEM` (весь кластер, пишет в `postgresql.auto.conf`);
`SET` / `ALTER ROLE` / `ALTER DATABASE` — сессия, роль, база.

</details>

**A2.** Что такое `postgresql.auto.conf` и почему из-за него «правка конфига не помогает»?

<details><summary>Ответ</summary>

Файл, куда пишет `ALTER SYSTEM`; читается **после** основного конфига и
переопределяет его. Отсюда эффект «поправил файл — ничего не изменилось».
Смотреть `pg_settings.sourcefile`, отменять `ALTER SYSTEM RESET`.

</details>

**A3.** Как узнать текущее значение параметра, его источник и нужен ли рестарт?

<details><summary>Ответ</summary>

`SELECT name, setting, unit, source, sourcefile, pending_restart FROM pg_settings
WHERE name = '…';`

</details>

**A4.** Сколько ставить `shared_buffers` и почему не «всю память»?

<details><summary>Ответ</summary>

Около 25% RAM. Больше — плохо, потому что данные кэшируются ещё и page cache ОС
(двойное кэширование), а остальная память нужна под соединения, `work_mem`,
`maintenance_work_mem` и саму ОС.

</details>

**A5.** Чем `effective_cache_size` отличается от `shared_buffers`?

<details><summary>Ответ</summary>

`shared_buffers` — реально выделенная память под кэш базы. `effective_cache_size`
память не выделяет вообще: это подсказка планировщику, сколько данных суммарно
может лежать в кэше (база + ОС), влияет на выбор индексных планов.

</details>

**A6.** ⭐ На что именно выделяется `work_mem`? Посчитай худший случай для
`max_connections=200`, `work_mem=64MB`, 3 сортировки на запрос.

<details><summary>Ответ</summary>

На каждую операцию сортировки/хеш-соединения/хеш-агрегации в каждом запросе.
Худший случай: 200 × 3 × 64 МБ ≈ 38 ГБ — в разы больше памяти сервера.

</details>

**A7.** По какому признаку в `EXPLAIN` видно, что `work_mem` мал?

<details><summary>Ответ</summary>

`Sort Method: external merge  Disk: …kB` (или `external sort`) вместо
`quicksort Memory`. Также `log_temp_files` начнёт писать временные файлы в лог.

</details>

**A8.** Почему нельзя решать проблему нехватки соединений увеличением `max_connections`?

<details><summary>Ответ</summary>

Каждое соединение — отдельный процесс с собственной памятью; рост числа процессов
даёт переключения контекста, давление на память и риск OOM, а не производительность.
Нужен пул соединений.

</details>

**A9.** Что такое PgBouncer и чем отличаются режимы `session`, `transaction`, `statement`?

<details><summary>Ответ</summary>

Пул соединений перед базой: держит много клиентских соединений и мало серверных.
`session` — серверное соединение занято на всё время клиентской сессии;
`transaction` — освобождается после каждой транзакции (стандарт для веба);
`statement` — после каждого запроса (запрещает многооператорные транзакции).

</details>

**A10.** Что делает `synchronous_commit = off` и чем это отличается от `fsync = off`?

<details><summary>Ответ</summary>

`synchronous_commit = off` — `COMMIT` подтверждается до сброса WAL на диск:
при аварии теряются последние транзакции, но кластер остаётся консистентным.
`fsync = off` отключает гарантии записи вообще — при сбое возможна порча кластера
и полная потеря базы.

</details>

**A11.** Что произойдёт, если `max_wal_size` слишком мал? Как это увидеть в статистике?

<details><summary>Ответ</summary>

Checkpoint будет запускаться по объёму WAL (внеплановые), давая всплески записи
и просадки производительности. Видно как рост `checkpoints_req` относительно
`checkpoints_timed` в `pg_stat_bgwriter` и сообщения `checkpoint starting: wal` в логе.

</details>

**A12.** Почему autovacuum нельзя выключать? Что происходит при transaction ID wraparound?

<details><summary>Ответ</summary>

Autovacuum убирает мёртвые версии строк и обновляет статистику. Без него —
bloat, деградация планов и, в пределе, приближение к пределу счётчика транзакций
(wraparound), при котором база принудительно останавливается для аварийного vacuum.

</details>

**A13.** Назови четыре причины, по которым autovacuum «работает, но bloat растёт».

<details><summary>Ответ</summary>

Долгие транзакции и `idle in transaction`; неактивные слоты репликации;
отставшие реплики с `hot_standby_feedback = on`; зависшие prepared transactions;
плюс слишком «вежливые» настройки (`autovacuum_vacuum_cost_limit`) на больших таблицах.

</details>

**A14.** Какие три таймаута стоит настроить и что каждый из них предотвращает?

<details><summary>Ответ</summary>

`statement_timeout` (не даёт одному запросу висеть вечно),
`idle_in_transaction_session_timeout` (убивает забытые транзакции),
`lock_timeout` (не позволяет встать в очередь за блокировкой на долго —
особенно важно для миграций).

</details>

**A15.** Почему `random_page_cost = 4` плохо подходит для SSD?

<details><summary>Ответ</summary>

`random_page_cost` — стоимость случайного чтения относительно последовательного.
На HDD она реально была в 4 раза выше, на SSD/NVMe разница почти отсутствует.
Дефолт 4 заставляет планировщик избегать индексов и выбирать `Seq Scan`.

</details>

---

### Блок B. «Что произойдёт»

Сервер: 16 ГБ RAM, 4 CPU, SSD, OLTP-приложение.

```ini
B1.  shared_buffers = 14GB
B2.  work_mem = 512MB
B3.  max_connections = 1500
B4.  fsync = off
B5.  synchronous_commit = off
B6.  autovacuum = off
B7.  max_wal_size = 256MB
B8.  checkpoint_timeout = 60min
B9.  log_statement = 'all'          # на нагруженном проде
B10. log_min_duration_statement = -1
B11. random_page_cost = 4           # на NVMe
B12. idle_in_transaction_session_timeout = 0
```

<details><summary>Ответ</summary>

**B1.** ~88% RAM под shared_buffers: почти ничего не остаётся ОС, соединениям и work_mem →
своп, OOM. Нужно ~4 ГБ.

**B2.** Глобальный `work_mem` 512 МБ при сотнях соединений — прямой путь к OOM.

**B3.** 1500 процессов: память и контекст-свитчи; нужен PgBouncer.

**B4.** Отключены гарантии записи: при сбое питания кластер может стать нерабочим. Недопустимо.

**B5.** Ускоряет запись, теряет последние транзакции при аварии; осознанный компромисс,
для финансовых данных не подходит.

**B6.** Bloat, деградация, риск wraparound-остановки. Нельзя.

**B7.** Слишком маленький `max_wal_size` → постоянные внеплановые checkpoint → всплески IO.

**B8.** Очень редкие checkpoint: дольше восстановление после сбоя и большой `pg_wal`.

**B9.** Логирование всех запросов на нагруженном проде: гигабайты логов, просадка
производительности, риск попадания чувствительных данных в лог.

**B10.** Медленные запросы вообще не логируются — разбирать инциденты будет нечем.

**B11.** На NVMe заставляет планировщик недооценивать индексы; ставят ~1.1.

**B12.** Забытые транзакции живут вечно: блокировки и остановка очистки мёртвых строк.

</details>

```sql
B13. ALTER SYSTEM SET work_mem = '16MB';       -- а в postgresql.conf стоит 64MB
B14. ALTER TABLE events SET (autovacuum_vacuum_scale_factor = 0.01);
B15. ALTER DATABASE shop SET statement_timeout = '30s';
```

<details><summary>Ответ</summary>

**B13.** Победит `ALTER SYSTEM` (16MB), так как `postgresql.auto.conf` читается последним.

**B14.** Индивидуальная настройка автовакуума для большой таблицы — правильный приём.

**B15.** Ограничение времени запроса на уровне базы — хорошая практика, но значение
надо согласовать с долгими отчётами (для них — отдельная роль с бОльшим таймаутом).

</details>

---

### Блок C. Практика

#### C1. 🔑 Источник истины
1. Поставь `work_mem = 64MB` в `postgresql.conf`, сделай reload.
2. Выполни `ALTER SYSTEM SET work_mem = '16MB';` и reload.
3. Посмотри `SELECT name, setting, source, sourcefile FROM pg_settings WHERE name='work_mem';`
4. Объясни, какое значение победило и почему. Отмени `ALTER SYSTEM`.

<details><summary>Ответ</summary>

`source = configuration file` против `source = configuration file` с другим
`sourcefile` (`postgresql.auto.conf`). Побеждает `auto.conf`; отмена — `ALTER SYSTEM RESET work_mem;`.

</details>

#### C2. `conf.d`
Включи `include_dir = 'conf.d'`, вынеси память в `10-memory.conf`, логи в `30-logging.conf`.
Проверь, что параметры применились и `sourcefile` указывает на новые файлы.

#### C3. Цена `work_mem`
```sql
SET work_mem = '64kB';
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM t ORDER BY val;   -- смотри Sort Method
SET work_mem = '256MB';
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM t ORDER BY val;
```
Сравни `external merge Disk` и `quicksort Memory`, замерь разницу во времени.

<details><summary>Ответ</summary>

При `work_mem = 64kB` — `Sort Method: external merge Disk: …`, время в разы больше;
при 256MB — `quicksort Memory`.

</details>

#### C4. Соединения и память
1. Открой 50 соединений скриптом.
2. Посмотри число процессов postgres и их RSS (`ps -o pid,rss,cmd -C postgres`).
3. Прикинь, во что превратится 1000 соединений.

<details><summary>Ответ</summary>

Типичный RSS процесса — десятки МБ (много общей памяти), но накладные расходы
и work_mem реальны; 1000 соединений превращают сервер в машину для переключения контекста.

</details>

#### C5. PgBouncer (со звёздочкой)
Подними PgBouncer в докере перед своей базой, настрой `pool_mode = transaction`,
подключи приложение/скрипт к 6432 и посмотри, сколько реальных соединений в
`pg_stat_activity` при 100 клиентах.

#### C6. Checkpoint
1. Поставь `max_wal_size = 128MB`, сделай массовую вставку на несколько минут.
2. Смотри `SELECT checkpoints_timed, checkpoints_req FROM pg_stat_bgwriter;` до и после.
3. Увеличь `max_wal_size` до 4GB и повтори. Сравни числа и график записи.

<details><summary>Ответ</summary>

При маленьком `max_wal_size` быстро растёт `checkpoints_req`; после увеличения
преобладают `checkpoints_timed` — так и должно быть.

</details>

#### C7. Autovacuum вживую
1. `UPDATE` всех строк большой таблицы → смотри `n_dead_tup`.
2. Дождись autovacuum (`last_autovacuum`) либо запусти `VACUUM` вручную.
3. Открой долгую транзакцию в другом сеансе и повтори — объясни, почему мёртвые строки
   перестали убираться.

<details><summary>Ответ</summary>

Открытая транзакция удерживает «горизонт» — vacuum не может удалить версии строк,
которые теоретически ещё видны этой транзакции.

</details>

#### C8. Таймауты
1. Поставь `idle_in_transaction_session_timeout = 30s`.
2. Открой транзакцию и подожди — посмотри, что произойдёт с сессией и что в логе.
3. Поставь `lock_timeout = 3s` и спровоцируй ожидание блокировки.

<details><summary>Ответ</summary>

Сессия будет завершена с сообщением `FATAL: terminating connection due to idle-in-transaction timeout`.

</details>

#### C9. Логи, которые спасают
Включи `log_min_duration_statement = 200`, `log_lock_waits`, `log_temp_files = 0`,
`log_checkpoints`. Создай по одному событию каждого типа и найди их в логе.

#### C10. `pg_stat_statements`
1. Добавь в `shared_preload_libraries`, перезапусти, создай расширение.
2. Погоняй нагрузку (`pgbench -i && pgbench -c 10 -T 60`).
3. Выведи топ-10 запросов по `total_exec_time` и объясни, что с ними делать дальше.

<details><summary>Ответ</summary>

Дальше: смотреть на `mean_exec_time` и `calls` — частый и умеренно медленный
запрос обычно важнее одного редкого тяжёлого; затем `EXPLAIN (ANALYZE, BUFFERS)`
и работа с индексами вместе с разработчиками.

</details>

---

### Блок D. Инциденты

**D1.** После увеличения `work_mem` до 512 МБ база начала уходить в OOM. Объясни механизм.

<details><summary>Ответ</summary>

`work_mem` выделяется на каждую операцию каждого запроса; при десятках параллельных
запросов суммарная память превышает физическую → OOM killer убивает backend
(иногда postmaster). Лечение — вернуть небольшое глобальное значение и поднимать точечно.

</details>

**D2.** «База тормозит по вечерам, в логе много `checkpoint starting: wal`». Что настраивать?

<details><summary>Ответ</summary>

`max_wal_size` мал (внеплановые checkpoint по объёму WAL). Увеличить `max_wal_size`,
поднять `checkpoint_timeout` до 15 минут, `checkpoint_completion_target = 0.9`,
включить `log_checkpoints` для контроля.

</details>

**D3.** Таблица растёт, `n_dead_tup` огромный, autovacuum включён и «работает». Причины?

<details><summary>Ответ</summary>

Долгая транзакция/`idle in transaction`, неактивный слот репликации, отставшая
реплика с `hot_standby_feedback`, prepared transaction, либо autovacuum не успевает
(увеличить `autovacuum_max_workers`, `cost_limit`, задать индивидуальный `scale_factor`).

</details>

**D4.** После включения `synchronous_commit = off` бизнес жалуется на потерю
нескольких заказов после аварии. Объясни, что произошло и что предложить.

<details><summary>Ответ</summary>

Последние транзакции подтверждались до записи WAL на диск и были потеряны при
аварийном выключении. Вернуть `synchronous_commit = on` для критичных операций
(его можно включать даже на уровне отдельной транзакции) и объяснить компромисс бизнесу.

</details>

**D5.** Приложение периодически висит на 20 минут, в `pg_stat_activity` — `idle in transaction`.
Какое одно изменение конфига закрывает большинство таких случаев?

<details><summary>Ответ</summary>

`idle_in_transaction_session_timeout` (плюс исправление кода приложения,
который не закрывает транзакции).

</details>

**D6.** Диск под `pg_wal` растёт и не очищается. Какие три причины проверишь?

<details><summary>Ответ</summary>

Неактивный слот репликации (`pg_replication_slots`), неработающий `archive_command`
(WAL не архивируется и не удаляется), очень большой `max_wal_size`/`wal_keep_size`.

</details>

**D7.** Правка `postgresql.conf` не применяется даже после рестарта. Алгоритм проверки.

<details><summary>Ответ</summary>

`SHOW config_file` (тот ли файл), `pg_settings.sourcefile` (не перебивает ли
`postgresql.auto.conf`), синтаксис (база могла не стартовать с новым конфигом),
`pending_restart`, реально ли перезапущен нужный кластер.

</details>

**D8.** На SSD планировщик упорно выбирает `Seq Scan` вместо индекса. Что проверишь?

<details><summary>Ответ</summary>

`random_page_cost`, актуальность статистики (`ANALYZE`), селективность условия,
наличие подходящего индекса, `effective_cache_size`, размер таблицы (для маленьких
`Seq Scan` действительно дешевле).

</details>

**D9.** В логе `temporary file: size 2GB` десятки раз в час. Что это значит и что менять?

<details><summary>Ответ</summary>

Сортировки/хеши не помещаются в `work_mem` и уходят на диск. Поднять `work_mem`
(точечно для роли/запроса), оптимизировать запрос, добавить индексы для сортировки.

</details>

**D10.** Коллега предлагает `fsync = off`, «потому что тесты показывают +40% записи».
Твой ответ.

<details><summary>Ответ</summary>

Отказать: выигрыш в записи не стоит риска полной потери кластера при сбое питания.
Если нужна скорость — `synchronous_commit = off` (контролируемая потеря последних
транзакций), быстрые диски, отдельный диск под WAL, батчинг на стороне приложения.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Какие основные параметры памяти в PostgreSQL и как их подбирают?

<details><summary>Ответ</summary>

`shared_buffers` (~25% RAM), `effective_cache_size` (подсказка планировщику),
`work_mem` (на операцию), `maintenance_work_mem`; стартовые значения — от pgtune,
дальше по метрикам.

</details>

**2.** Что такое `work_mem` и в чём его опасность?

<details><summary>Ответ</summary>

Память на одну операцию сортировки/хеша; при большом значении и многих соединениях
суммарный расход многократно превышает ожидаемый.

</details>

**3.** Как правильно решать проблему большого числа соединений?

<details><summary>Ответ</summary>

Пул соединений (PgBouncer, `transaction`), разумный `max_connections`,
исправление пулов на стороне приложения.

</details>

**4.** Что такое WAL-checkpoint и как на него влияют настройки?

<details><summary>Ответ</summary>

Сброс грязных страниц на диск; регулируется `max_wal_size`, `checkpoint_timeout`,
`checkpoint_completion_target`; частые внеплановые checkpoint — признак малого `max_wal_size`.

</details>

**5.** Чем `synchronous_commit = off` отличается от `fsync = off`?

<details><summary>Ответ</summary>

Первое — контролируемая потеря последних транзакций, кластер цел; второе — отсутствие
гарантий записи и риск порчи кластера.

</details>

**6.** Зачем нужен autovacuum и почему его нельзя выключать?

<details><summary>Ответ</summary>

Убирает мёртвые версии строк и обновляет статистику; без него bloat, деградация планов
и угроза остановки из-за wraparound.

</details>

**7.** Что мешает autovacuum убирать мёртвые строки?

<details><summary>Ответ</summary>

Долгие транзакции, неактивные слоты репликации, отставшие реплики с `hot_standby_feedback`,
prepared transactions.

</details>

**8.** Какие таймауты ты настраиваешь в проде?

<details><summary>Ответ</summary>

`statement_timeout` (на уровне базы/роли), `idle_in_transaction_session_timeout`, `lock_timeout`.

</details>

**9.** Что включаешь в логировании базы и зачем?

<details><summary>Ответ</summary>

`log_min_duration_statement`, `log_lock_waits`, `log_temp_files`, `log_checkpoints`,
`log_connections/disconnections`, информативный `log_line_prefix`.

</details>

**10.** Как понять, какие запросы грузят базу?

<details><summary>Ответ</summary>

`pg_stat_statements` (топ по общему времени), медленные запросы из лога,
дальше `EXPLAIN (ANALYZE, BUFFERS)`.

</details>

---

### 🎯 Чек-лист

- [ ] Знаю три способа менять параметры и умею найти источник значения
- [ ] Могу обосновать значения `shared_buffers`, `effective_cache_size`, `work_mem`
- [ ] ⭐ Понимаю, что `work_mem` — на операцию, и умею считать худший случай
- [ ] Знаю, зачем PgBouncer и что такое `pool_mode = transaction`
- [ ] Различаю `synchronous_commit = off` и `fsync = off`
- [ ] Понимаю checkpoint и умею читать `pg_stat_bgwriter`
- [ ] Настраиваю autovacuum, знаю, что ему мешает
- [ ] В моём конфиге есть таймауты (`idle_in_transaction`, `lock_timeout`)
- [ ] Логирование настроено так, что инцидент можно разобрать
- [ ] Пользуюсь `pg_stat_statements` для поиска тяжёлых запросов
