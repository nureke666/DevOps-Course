---
title: "12. MySQL и MariaDB"
description: "MySQL/MariaDB для того, кто уже знает PostgreSQL: установка, my.cnf, права, бэкапы, PITR по binlog, репликация, HA"
---

# 12. MySQL и MariaDB — для того, кто уже знает PostgreSQL

> Вне роадмапа → Базы → **MySQL/MariaDB**. Блок построен на PostgreSQL, но в вакансиях
> (особенно PHP/Bitrix и легаси) MySQL встречается не реже. Тема идёт через сравнение
> «в PG это …» — переносим знакомые навыки, а не учим всё заново.
>
> **После темы ты умеешь:** поднять MySQL/MariaDB, осознанно настроить `my.cnf`, выдать
> доступ через `'user'@'host'`, снять и восстановить бэкап (включая PITR по binlog),
> поднять реплику на GTID, починить сломанную репликацию и настроить мониторинг.
>
> 📅 Версии, теги образов и статусы утилит быстро меняются — **проверь, сентябрь 2026**.

---

## 🗺️ Карта: то же самое, но другими словами

```text:no-line-numbers
  PostgreSQL                          MySQL / MariaDB (InnoDB)
  ─────────────────────────────       ──────────────────────────────────────
  postgresql.conf, ALTER SYSTEM       my.cnf, SET PERSIST
  pg_hba.conf + роли                  'user'@'host' + GRANT (всё в SQL)
  один WAL: надёжность + репликация   ⭐ ДВА журнала: redo — надёжность,
                                         binlog — репликация и PITR
  мёртвые строки + VACUUM             undo log + purge (VACUUM нет)
  физическая реплика, только чтение   реплика применяет binlog, писать МОЖНО
  pg_dump / pg_basebackup + WAL       mysqldump, MySQL Shell / XtraBackup + binlog
  Patroni, PgBouncer, HAProxy         InnoDB Cluster, Galera, ProxySQL
  postgres_exporter :9187             mysqld_exporter :9104
```

---

## 1. Где ты встретишь MySQL

| Где | Почему MySQL |
|-----|--------------|
| PHP-мир: WordPress, 1С-Битрикс, Laravel, Magento, Moodle | Исторически LAMP-стек; Битрикс — частый гость в Казахстане и СНГ |
| Легаси-монолиты 2005–2015 годов | «Так сложилось», миграция на PG дорогая |
| Готовые продукты: Zabbix, Nextcloud, Jira/Confluence, Keycloak | MySQL — одна из поддерживаемых баз |
| Продуктовые команды на Go/Java | Опыт команды, простая репликация, Vitess |
| Облака | AWS RDS/Aurora, Yandex Managed Service for MySQL, managed MySQL у казахстанских провайдеров (блок Cloud) |

---

## 2. Версии и форки

### MySQL (Oracle): LTS и Innovation

```text:no-line-numbers
8.0 ────── EOL 30.04.2026 ⚠️ (всё ещё много в проде — планируй апгрейд)
8.4 LTS ── апрель 2024 · premier-поддержка до 2029, extended до 2032
9.0–9.6 ── Innovation, каждая жила ~квартал
9.7 LTS ── апрель 2026 · последняя «старая» нумерация, поддержка до 2031/2034
26.7 ───── июль 2026 · первая Innovation с календарной версией YY.M.P (9.8 не будет)
26.10 … ── следующие Innovation; будущие LTS тоже календарные (вида 28.4)
```
LTS — 5 лет premier + 3 года extended, выбор для прода; Innovation живёт до выхода следующей.

> ⚠️ `mysql:latest` в Docker Hub — это **Innovation** (сейчас 26.7). В проде и compose
> всегда явная LTS: `mysql:8.4` или `mysql:9.7`.

### MariaDB: форк, который ушёл своей дорогой

LTS-ветки: **10.11** (до 02.2028), **11.4** (до 05.2029), **11.8** (до 06.2028),
**12.3** (май 2026, до 06.2029). С 12.x LTS-релизом ветки становится версия `.3`,
поддержка — 3 года (раньше 5). 10.6 закончила жизнь в июле 2026.

MariaDB — **уже не «тот же MySQL»**: другой формат GTID, свои плагины аутентификации,
`JSON` = псевдоним `LONGTEXT`, встроенная Galera, свои утилиты (`mariadb`, `mariadb-dump`,
`mariadb-backup`) и старый синтаксис репликации. Переезд MySQL 8.4 ⇄ MariaDB 11.x —
миграция через логический дамп, а не «поменял пакет».

**Percona Server for MySQL** — drop-in замена MySQL (доп. диагностика, аудит), нумерация та же.

---

## 3. Установка

```bash
# Docker
docker run -d --name mysql -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=root -e MYSQL_DATABASE=shop \
  -v mysqldata:/var/lib/mysql -v ./conf.d:/etc/mysql/conf.d:ro \
  mysql:8.4
docker exec -it mysql mysql -uroot -p              # аналог psql
docker exec mysql mysqladmin -uroot -proot ping    # аналог pg_isready

# MariaDB: переменные MARIADB_*, теги lts/latest, встроенный healthcheck.sh
docker run -d --name maria -e MARIADB_ROOT_PASSWORD=root mariadb:11.8

# Ubuntu 26.04: в штатном репозитории mysql-server 8.4 и mariadb-server 11.8
# (конфликтуют — ставится одно); точная версия — repo.mysql.com / mariadb.org (как PGDG)
sudo apt install -y mysql-server
sudo mysql                        # root по auth_socket — аналог peer в pg_hba
sudo mysql_secure_installation    # убрать анонимов, тестовую базу, root по сети
```

| Что | PostgreSQL (Ubuntu) | MySQL (Ubuntu) |
|-----|---------------------|----------------|
| Конфиг | `/etc/postgresql/16/main/postgresql.conf` | `/etc/mysql/my.cnf` → `mysql.conf.d/mysqld.cnf` |
| Данные / лог | `/var/lib/postgresql/16/main`, `/var/log/postgresql/` | `/var/lib/mysql`, `/var/log/mysql/error.log` |
| Сервис / порт | `postgresql@16-main`, 5432 | `mysql` (MariaDB: `mariadb`), 3306 |
| «Слушать сеть» | `listen_addresses` | `bind-address` |

---

## 4. Конфигурация: `my.cnf`

Секции по программам: `[mysqld]` — сервер, `[client]` — все клиенты, `[mysqldump]` — дамп.
Порядок чтения: `mysqld --verbose --help | grep -A1 "Default options"`; итог — `SHOW VARIABLES LIKE '…';`.

```sql
SET GLOBAL max_connections = 300;     -- до рестарта (параметр динамический)
SET PERSIST max_connections = 300;    -- ⭐ переживёт рестарт: пишет mysqld-auto.cnf
                                      --    (аналог ALTER SYSTEM → postgresql.auto.conf)
SET PERSIST_ONLY back_log = 1000;     -- статический: применится после рестарта
```

### Ключевые параметры (сервер 16 ГБ, только база)

```ini
[mysqld]
innodb_buffer_pool_size = 11G      # ⭐ 60–75% RAM (в PG shared_buffers ~25%): InnoDB кэширует
                                   #    сам через O_DIRECT и на кэш ОС не рассчитывает
# или innodb_dedicated_server = ON — посчитает buffer pool и redo сам

innodb_flush_log_at_trx_commit = 1 # не терять коммиты (0/2 — быстрее, но с риском)
sync_binlog                    = 1 # binlog на диск на каждый коммит
innodb_redo_log_capacity       = 4G  # аналог max_wal_size (8.0.30+)

max_connections    = 300           # по умолчанию 151
wait_timeout       = 600           # закрывать брошенные соединения
max_connect_errors = 1000000       # иначе хост блокируется после сетевых сбоев

server_id                  = 1     # уникален в топологии!
log_bin                    = binlog  # в 8.0+ включён по умолчанию
binlog_format               = ROW   # только ROW; STATEMENT — легаси
binlog_expire_logs_seconds = 604800  # 7 дней (умолч. 30); expire_logs_days удалён в 8.4
gtid_mode                  = ON
enforce_gtid_consistency   = ON

slow_query_log  = ON
long_query_time = 0.5
character_set_server = utf8mb4     # utf8 = utf8mb3: эмодзи и часть символов не влезут
# sql_mode в 8.x по умолчанию строгий — не ослабляй его ради старого PHP-кода
```

> 💡 В 8.4 умолчания InnoDB подогнаны под SSD (`innodb_io_capacity=10000`, `O_DIRECT`,
> adaptive hash index и change buffering выключены) — не тащи «оптимизации» из конфигов 5.7/8.0.

---

## 5. Пользователи и права: `'user'@'host'` вместо `pg_hba.conf`

В PostgreSQL «кто откуда» — в `pg_hba.conf`, «что можно» — в `GRANT`
([03. Доступ через pg_hba.conf](/databases/03-pg-hba-access)). В MySQL **обе двери в SQL**:
учётная запись — это пара **имя + хост**.

```sql
CREATE USER 'shop_app'@'10.0.1.%' IDENTIFIED BY 'strong' REQUIRE SSL;
GRANT SELECT, INSERT, UPDATE, DELETE ON shop.* TO 'shop_app'@'10.0.1.%';
CREATE USER 'shop_owner'@'10.0.5.%' IDENTIFIED BY '...';   -- для миграций из CI
GRANT ALL ON shop.* TO 'shop_owner'@'10.0.5.%';

SHOW GRANTS FOR 'shop_app'@'10.0.1.%';
SELECT user, host, plugin FROM mysql.user;                  -- аналог \du

-- роли (8.0+): без SET DEFAULT ROLE пользователь их «не видит»
CREATE ROLE 'readonly';
GRANT SELECT ON shop.* TO 'readonly';
CREATE USER 'analyst'@'10.0.9.%' IDENTIFIED BY '...' PASSWORD EXPIRE INTERVAL 90 DAY;
GRANT 'readonly' TO 'analyst'@'10.0.9.%';
SET DEFAULT ROLE ALL TO 'analyst'@'10.0.9.%';               -- ⭐ иначе Access denied
```

| | PostgreSQL | MySQL |
|--|-----------|-------|
| Кто откуда | `pg_hba.conf`, нужен **reload** | `'user'@'host'` в SQL, действует сразу |
| Выбор правила | Первая совпавшая строка сверху | Самый **конкретный** хост (`10.0.1.7` → `10.0.1.%` → `%`) |
| `app@localhost` и `app@%` | Одна роль | ⚠️ **Две разные** учётки с разными паролями и правами |
| Уровни | база → схема → таблица | база (= схема) → таблица → колонка |
| Требовать TLS | `hostssl` | `REQUIRE SSL` или `require_secure_transport=ON` |
| Хеш паролей | `scram-sha-256` | `caching_sha2_password` (по умолчанию с 8.0) |

### ⭐ `mysql_native_password` — главная боль апгрейдов

```text:no-line-numbers
8.0.34  объявлен устаревшим
8.4     ОТКЛЮЧЁН по умолчанию  (вернуть временно: mysql_native_password=ON в [mysqld])
9.0+    УДАЛЁН совсем
```
Симптом после апгрейда — `Plugin 'mysql_native_password' is not loaded`, старый PHP/драйвер
не входит. Лечение — перевести учётку и обновить драйвер, а не включать плагин навсегда:
`ALTER USER 'shop_app'@'10.0.1.%' IDENTIFIED WITH caching_sha2_password BY 'strong';`
Без TLS `caching_sha2_password` требует обмена RSA-ключом — у JDBC это ошибка
`Public Key Retrieval is not allowed`. Правильный ответ — включить TLS.

---

## 6. InnoDB: что нужно знать эксплуатационнику

| Тема | InnoDB | PostgreSQL |
|------|--------|-----------|
| Хранение | Таблица = B-дерево по **первичному ключу** | Heap + отдельные индексы |
| MVCC | Старые версии в **undo log**, чистит фоновый purge | Мёртвые строки в таблице, чистит VACUUM |
| Долгая транзакция | Растёт *history list length*, undo пухнет | Держит горизонт, растёт bloat |
| Изоляция по умолчанию | ⚠️ **REPEATABLE READ** (+ gap locks) | READ COMMITTED |
| DDL | ❌ каждый DDL — неявный COMMIT | ✅ транзакционный DDL |
| Место после `DELETE` | Само не вернётся: `OPTIMIZE TABLE` | `VACUUM FULL` / pg_repack |

- **Первичный ключ обязателен**: без него ROW-репликация медленная, Group Replication откажет.
- Долгие транзакции: `SELECT * FROM information_schema.innodb_trx ORDER BY trx_started;`
  и `SHOW ENGINE INNODB STATUS\G` (раздел TRANSACTIONS, `History list length`).
- Deadlock-и — норма, приложение повторяет транзакцию (в лог: `innodb_print_all_deadlocks=ON`).
  **MyISAM** — легаси без транзакций и crash recovery: встретил — план переезда на InnoDB.

---

## 7. Бэкапы

Логика та же, что в [05. Backup / Restore](/databases/05-backup-restore) (RPO/RTO, 3-2-1, проверка restore) — меняются инструменты:

| Задача | PostgreSQL | MySQL | MariaDB |
|--------|-----------|-------|---------|
| Логический дамп | `pg_dump` | `mysqldump`, **MySQL Shell** `util.dump*` | `mariadb-dump` |
| Физический «горячий» | `pg_basebackup`, pgBackRest | **Percona XtraBackup** | `mariadb-backup` |
| Журнал для PITR | архив WAL | **binlog** | binlog |
| Пользователи | `pg_dumpall --globals-only` | MySQL Shell `dumpInstance`, pt-show-grants | то же |

> ⚠️ `mysqlpump` **удалён в 8.4** — в старых скриптах заменить на `mysqldump` или MySQL Shell.

```bash
# mysqldump: логический, однопоточное восстановление
mysqldump -uroot -p --single-transaction \  # ⭐ консистентный снимок без блокировок (только InnoDB)
  --routines --triggers --events \          # иначе процедуры и события потеряются
  --source-data=2 --set-gtid-purged=ON \    # позиция binlog и GTID (было --master-data)
  --databases shop | zstd > shop_$(date +%F).sql.zst
zstd -dc shop_2026-09-27.sql.zst | mysql -uroot -p
```
```js
// MySQL Shell (mysqlsh --js): параллельно, чанками, умеет писать в S3-совместимое хранилище
util.dumpInstance("/backup/2026-09-27", {threads: 8})   // вся база + пользователи
util.loadDump("/backup/2026-09-27", {threads: 8})        // на целевом нужен local_infile=ON
```
```bash
# Percona XtraBackup: физический бэкап на ходу
xtrabackup --backup  --target-dir=/backup/full --user=bkp --password=...
xtrabackup --prepare --target-dir=/backup/full        # ⭐ применить redo, иначе копия «грязная»
systemctl stop mysql && rm -rf /var/lib/mysql/*       # ⚠️ трижды проверь путь
xtrabackup --copy-back --target-dir=/backup/full && chown -R mysql:mysql /var/lib/mysql
```
Версия XtraBackup **привязана к серии сервера**: 8.4.x (актуальная 8.4.0-7, сентябрь 2026)
работает только с MySQL/Percona Server 8.4, для 8.0 — ветка 8.0.35-x, поддержку 9.7
проверяй отдельно. Для MariaDB — `mariadb-backup`.

### PITR по binlog

```text:no-line-numbers
 полный бэкап 02:00     binlog.000041   binlog.000042   binlog.000043
 ──────●────────────────────────────────────────────────►  время
   позиция/GTID из бэкапа           14:37 DROP TABLE ⚠️
   восстановить бэкап В ОТДЕЛЬНЫЙ инстанс + доиграть binlog ДО 14:36:59
```
```bash
mysqlbinlog --base64-output=DECODE-ROWS -vv binlog.000042 | grep -n -B5 "DROP TABLE"
mysqlbinlog --start-position=157 --stop-datetime="2026-09-27 14:36:59" \
  binlog.000042 binlog.000043 | mysql -uroot -p
# с GTID вместо позиций: --include-gtids / --exclude-gtids
```
- `--stop-datetime` трактуется в **часовом поясе машины**, где запущен `mysqlbinlog`
  (Казахстан с 01.03.2024 — UTC+5; на сервере в UTC сдвиг на 5 часов).
- Binlog должен храниться **дольше интервала между полными бэкапами**, а в идеале —
  непрерывно уезжать с хоста: `mysqlbinlog --read-from-remote-server --raw --stop-never`
  (аналог архива WAL).

---

## 8. Репликация

```text:no-line-numbers
  SOURCE                                 REPLICA
  коммит → binlog  ── события ──►  receiver (IO) → relay log → applier (SQL, N потоков)
                   реплика тянет сама
```
В PG реплика получает физический WAL и **не может** принять запись. Реплика MySQL — обычный
сервер, применяющий чужие изменения: **писать в неё можно**, пока не включён `super_read_only`.

| Вид | Суть | Аналог в PG |
|-----|------|-------------|
| Асинхронная (умолч.) | Коммит не ждёт реплику | async streaming |
| Semi-sync | Коммит ждёт, что хоть одна реплика **получила** событие | `synchronous_commit=remote_write` |
| Group Replication | Консенсус группы (§9) | Прямого нет |

Semi-sync в 8.4 — плагины `rpl_semi_sync_source` / `rpl_semi_sync_replica` (старые
`…_master/_slave` вместе с новыми не ставятся). ⚠️ По истечении
`rpl_semi_sync_source_timeout` (10 с) source **молча уходит в async** —
алерт на `Rpl_semi_sync_source_status = OFF`.

**GTID** (`server_uuid:номер`) — глобальный номер транзакции: реплика сообщает, что применила,
source досылает остальное (`SOURCE_AUTO_POSITION=1`) — без «файл + позиция», смена source одной командой.

### ⭐ Синтаксис 8.4: MASTER/SLAVE удалены

| Было (удалено в 8.4) | Стало |
|----------------------|-------|
| `CHANGE MASTER TO MASTER_HOST=…` | `CHANGE REPLICATION SOURCE TO SOURCE_HOST=…` |
| `START SLAVE` / `STOP SLAVE` / `RESET SLAVE` | `START REPLICA` / `STOP REPLICA` / `RESET REPLICA` |
| `SHOW SLAVE STATUS` / `SHOW SLAVE HOSTS` | `SHOW REPLICA STATUS` / `SHOW REPLICAS` |
| `SHOW MASTER STATUS` | `SHOW BINARY LOG STATUS` |
| `RESET MASTER` | `RESET BINARY LOGS AND GTIDS` |

Скрипты, Ansible-роли и проверки на `SHOW SLAVE STATUS` на 8.4 **ломаются**; MariaDB `CHANGE MASTER` сохраняет.

### Поднять реплику (GTID)

```sql
-- на source
CREATE USER 'repl'@'10.0.1.%' IDENTIFIED BY '...' REQUIRE SSL;
GRANT REPLICATION SLAVE ON *.* TO 'repl'@'10.0.1.%';   -- имя привилегии осталось старым
-- данные на реплику: mysqldump --set-gtid-purged=ON / MySQL Shell / XtraBackup / Clone plugin

-- на реплике (другой server_id, gtid_mode=ON)
RESET BINARY LOGS AND GTIDS;              -- перед загрузкой дампа с GTID_PURGED
-- … загрузить дамп …
CHANGE REPLICATION SOURCE TO SOURCE_HOST='10.0.1.5', SOURCE_USER='repl',
  SOURCE_PASSWORD='...', SOURCE_AUTO_POSITION=1, SOURCE_SSL=1;
START REPLICA;
SET PERSIST super_read_only = ON;         -- ⭐ никто, даже root, не пишет в реплику
SHOW REPLICA STATUS\G
```

| Поле `SHOW REPLICA STATUS` | Норма | Если нет |
|----------------------------|-------|----------|
| `Replica_IO_Running` | `Yes` | Сеть, пароль, TLS, нужный binlog уже удалён → `Last_IO_Error` |
| `Replica_SQL_Running` | `Yes` | Конфликт данных (1062 duplicate, 1032 not found) → `Last_SQL_Error` |
| `Seconds_Behind_Source` | ≈ 0 | Лаг; `NULL` — применение стоит |
| `Retrieved_` vs `Executed_Gtid_Set` | почти равны | Разница = получено, но не применено |

⚠️ `Seconds_Behind_Source` врёт: не видит, что отстал сам receiver. Надёжнее —
`pt-heartbeat` (таблица-пульс) или `performance_schema.replication_applier_status_by_worker`.
Ускорить применение — многопоточный applier (`replica_parallel_workers`, умолч. 4).

### Сломалась репликация: как чинят

```text:no-line-numbers
Last_SQL_Error: … Duplicate entry '100' for key 'orders.PRIMARY' (1062)
```
1. Понять, **почему** разошлись данные (писали в реплику? не было `super_read_only`?).
2. Устранить конфликт на реплике (удалить мешающую строку) → `START REPLICA;` —
   упавшая транзакция применится заново.
3. Если событие действительно надо пропустить — с GTID `sql_replica_skip_counter`
   не работает, вставляют **пустую транзакцию** с этим GTID:
   `STOP REPLICA; SET GTID_NEXT='<uuid>:1234'; BEGIN; COMMIT; SET GTID_NEXT='AUTOMATIC'; START REPLICA;`
4. Проверить консистентность (`pt-table-checksum`), при сомнениях — **переналить реплику**.
   Пропускать ошибки «пока не заработает» = тихо разъехавшиеся данные.

Отложенная реплика против `DROP TABLE` (аналог `recovery_min_apply_delay`): `SOURCE_DELAY = 3600`.

---

## 9. HA и маршрутизация трафика

| Решение | Как устроено | Когда |
|---------|--------------|-------|
| **InnoDB Cluster** | Group Replication (консенсус, ≥3 узла, обычно single-primary) + MySQL Shell AdminAPI + MySQL Router | Официальный путь; ClusterSet — несколько кластеров для DR |
| **InnoDB ReplicaSet** | Async-репликация под AdminAPI, переключение вручную | Проще, без консенсуса |
| **Orchestrator** | Следит за async-топологией, автоматический failover | ⚠️ Оригинал openark заархивирован; жив форк Percona (в их операторе) |
| **Galera** (MariaDB Galera, Percona XtraDB Cluster) | Синхронный multi-master с сертификацией, ≥3 узла | MariaDB-мир; конфликт записи на разных узлах = deadlock у клиента |
| **Managed** | RDS/Aurora, Yandex Managed MySQL | Нет людей дежурить |

```text:no-line-numbers
  приложение ──3306──► ProxySQL / MySQL Router ──запись──► primary, чтение ──► реплики
```
- **ProxySQL** — «PgBouncer + HAProxy в одном»: пул и мультиплексирование соединений,
  разделение чтения/записи по правилам запросов, admin-интерфейс на 6032.
  Сейчас три ветки (3.0.11 / 3.1.11 / 4.0.11, август 2026): 3.0.x — stable, 3.1.x — innovative, 4.0.x.
- **MySQL Router** — маршрутизатор под InnoDB Cluster, сам знает топологию; порты 6446 (RW) / 6447 (RO).
- В Kubernetes: MySQL Operator (Oracle), Percona Operator, mariadb-operator; шардирование — Vitess
  (идея как у Patroni/CloudNativePG, [06. Репликация](/databases/06-replication)).

---

## 10. Мониторинг

```sql
CREATE USER 'exporter'@'10.0.1.%' IDENTIFIED BY '...' WITH MAX_USER_CONNECTIONS 3;
GRANT PROCESS, REPLICATION CLIENT, SELECT ON *.* TO 'exporter'@'10.0.1.%';
```
```bash
# /etc/mysqld_exporter/.my.cnf (права 600): [client] host=… user=exporter password=…
mysqld_exporter --config.my-cnf=/etc/mysqld_exporter/.my.cnf        # порт 9104
# DATA_SOURCE_NAME в актуальных версиях не используется; пароль — MYSQLD_EXPORTER_PASSWORD
# один экспортер на много баз: /probe?target=db2:3306&auth_module=client.db2
```
Дашборды — «MySQL Overview» для Grafana или Percona PMM.

| Что алертить (сравни с [07. Мониторинг БД](/databases/07-db-monitoring)) | Метрика |
|---------------------------------------------------|---------|
| База недоступна | `mysql_up == 0` |
| Соединения к пределу | `mysql_global_status_threads_connected / mysql_global_variables_max_connections > 0.8` |
| Перегруз | `mysql_global_status_threads_running` высоко и растёт |
| Репликация стоит / лаг | `mysql_slave_status_*` (IO/SQL running, seconds behind) — имена зависят от версии, проверь `curl :9104/metrics` |
| Buffer pool мал | растёт доля `innodb_buffer_pool_reads` к `…_read_requests` (чтения мимо кэша) |
| Блокировки и медленные | rate `…innodb_row_lock_waits`, `…slow_queries` |
| Диск | место под `/var/lib/mysql` и под binlog ⭐ |

```sql
SHOW PROCESSLIST;                                -- аналог pg_stat_activity; KILL <id>
SELECT * FROM sys.statement_analysis LIMIT 10;   -- топ запросов (аналог pg_stat_statements)
SELECT * FROM sys.innodb_lock_waits\G            -- кто кого блокирует
SHOW ENGINE INNODB STATUS\G                      -- транзакции, deadlock, history list
```
`performance_schema` включена по умолчанию, `sys` — представления поверх неё; slow log — `pt-query-digest`.

---

## 11. MySQL vs PostgreSQL — таблица эксплуатационника

| Вопрос | PostgreSQL | MySQL (InnoDB) |
|--------|-----------|----------------|
| Соединения | Процесс на соединение, PgBouncer обязателен | Поток на соединение, дешевле; пул — ProxySQL |
| Доступ | `pg_hba.conf` + роли | `'user'@'host'` + `GRANT` |
| Настройки | `ALTER SYSTEM`, reload/restart | `SET PERSIST`, большинство динамические |
| Журналы | Один WAL | redo log + binlog |
| Уборка | autovacuum ⭐ | purge сам; место — `OPTIMIZE TABLE` |
| Реплика | Физическая, только чтение | По binlog, писать можно без `super_read_only` |
| Автофейловер | Patroni, CloudNativePG | InnoDB Cluster, Orchestrator, Galera, операторы |
| Физический бэкап | pgBackRest, WAL-G | XtraBackup, `mariadb-backup` |
| Онлайн-DDL | `CONCURRENTLY`, `lock_timeout` | `ALGORITHM=INSTANT/INPLACE`, gh-ost, pt-osc ([13. Миграции схемы](/databases/13-schema-migrations)) |
| Мажорный апгрейд | `pg_upgrade` или дамп | in-place между LTS (8.0 → 8.4 → 9.7), откат — только из бэкапа |

---

## 12. Мини-лаба: primary + replica, дамп, поломка и починка

```yaml
# ~/sandbox/mysql-lab/compose.yaml
x-mysql: &mysql
  image: mysql:8.4
  environment: { MYSQL_ROOT_PASSWORD: root }
  healthcheck: { test: ["CMD", "mysqladmin", "ping", "-h127.0.0.1", "-proot"], interval: 5s }
services:
  src:
    <<: *mysql
    command: --server-id=1 --gtid-mode=ON --enforce-gtid-consistency=ON
  replica:
    <<: *mysql
    command: --server-id=2 --gtid-mode=ON --enforce-gtid-consistency=ON
```
```bash
docker compose up -d --wait
S="docker compose exec -T src mysql -uroot -proot"
R="docker compose exec -T replica mysql -uroot -proot"

# 1. пользователь репликации и данные на source
$S -e "CREATE USER 'repl'@'%' IDENTIFIED BY 'replpass'; GRANT REPLICATION SLAVE ON *.* TO 'repl'@'%';
       CREATE DATABASE shop; CREATE TABLE shop.orders (id INT PRIMARY KEY, sum INT);
       INSERT INTO shop.orders VALUES (1,100),(2,200);"
# 2. дамп с GTID → на реплику
docker compose exec -T src mysqldump -uroot -proot --single-transaction \
  --set-gtid-purged=ON --routines --triggers --events --databases shop > shop.sql
$R -e "RESET BINARY LOGS AND GTIDS;" && $R < shop.sql
# 3. включить репликацию и проверить
$R -e "CHANGE REPLICATION SOURCE TO SOURCE_HOST='src', SOURCE_USER='repl',
       SOURCE_PASSWORD='replpass', SOURCE_AUTO_POSITION=1, SOURCE_SSL=1; START REPLICA;"
$R -e "SHOW REPLICA STATUS\G" | grep -E "Running:|Behind|Error:"
$S -e "INSERT INTO shop.orders VALUES (3,300);"; $R -e "SELECT * FROM shop.orders;"
# 4. сломать: запись в реплику, потом та же строка на source → 1062
$R -e "INSERT INTO shop.orders VALUES (100,1);"
$S -e "INSERT INTO shop.orders VALUES (100,999);"
$R -e "SHOW REPLICA STATUS\G" | grep -E "SQL_Running:|Last_SQL_Error"
# 5. починить: убрать конфликт, перезапустить, запретить запись
$R -e "DELETE FROM shop.orders WHERE id=100; START REPLICA;"
$R -e "SET PERSIST super_read_only=ON; SELECT * FROM shop.orders WHERE id=100;"  # 999
$R -e "INSERT INTO shop.orders VALUES (101,1);"     # ERROR 1290 … --super-read-only
```
Подумай: `@@gtid_executed` реплики теперь содержит GTID с её **собственным** `server_uuid`
(шаг 4) — errant-транзакция. Чем она опасна при failover и как её найти (`GTID_SUBTRACT`)?

---

## 13. Грабли

| Грабля | Последствие | Правильно |
|--------|-------------|-----------|
| `mysql:latest` в compose | Внезапный переезд на Innovation (26.x) | Явная LTS: `mysql:8.4` / `9.7` |
| `app@%` и `app@localhost` с разными паролями | «Отсюда пускает, оттуда нет» | Одна учётка на источник, `SHOW GRANTS` |
| Роль выдана, `SET DEFAULT ROLE` нет | `Access denied` при «правильных» правах | `SET DEFAULT ROLE ALL TO …` |
| Апгрейд на 8.4/9.x со старыми клиентами | `mysql_native_password is not loaded` | Заранее перевести на `caching_sha2_password` |
| Скрипты на `SHOW SLAVE STATUS` | Мониторинг и Ansible ломаются на 8.4 | Синтаксис `REPLICA`/`SOURCE` |
| Реплика без `super_read_only` | Запись в реплику → 1062, errant GTID | `SET PERSIST super_read_only=ON` |
| Пропускать ошибки «пока не заработает» | Тихо разъехавшиеся данные | Причина → pt-table-checksum → переналивка |
| Binlog хранится меньше интервала бэкапов | PITR невозможен | Хранить дольше, выгружать с хоста |

---

## 💼 Как это в DevOps

- MySQL ставят как PG: роль Ansible + шаблон `my.cnf` + учётки из переменных
  (`community.mysql.mysql_user`), пароли — из Vault.
- Типовой self-hosted прод: MySQL 8.4 LTS, GTID, primary + 2 реплики, ProxySQL,
  XtraBackup ночью + непрерывная выгрузка binlog в S3, mysqld_exporter + алерты.
- Главная плановая работа 2026 года — **уход с 8.0**: клиенты на `caching_sha2_password`,
  новый синтаксис репликации в скриптах, свежие XtraBackup и экспортер, апгрейд на копии.
- Битрикс/WordPress часто живут как «одна MariaDB на VM и дамп раз в сутки» — первые
  улучшения: проверка restore, binlog для PITR, мониторинг, реплика.
- DDL в MySQL не транзакционный — миграции схемы здесь опаснее, см.
  [13. Миграции схемы](/databases/13-schema-migrations).

---

## 📌 Шпаргалка

| Хочу | Команда |
|------|---------|
| Параметр до / после рестарта | `SET GLOBAL …` / `SET PERSIST …` |
| Создать учётку и выдать права | `CREATE USER 'app'@'10.0.1.%' … REQUIRE SSL;` + `GRANT … ON shop.* TO …` |
| Права учётки / активировать роли | `SHOW GRANTS FOR …` / `SET DEFAULT ROLE ALL TO …` |
| Логический дамп | `mysqldump --single-transaction --routines --triggers --events --databases shop` |
| Параллельный дамп | `util.dumpInstance("/backup/x", {threads: 8})` в `mysqlsh` |
| Физический бэкап | `xtrabackup --backup` → `--prepare` → `--copy-back` |
| Позиция binlog | `SHOW BINARY LOG STATUS;` |
| PITR | `mysqlbinlog --start-position … --stop-datetime … \| mysql` |
| Включить реплику | `CHANGE REPLICATION SOURCE TO … SOURCE_AUTO_POSITION=1; START REPLICA;` |
| Статус реплики | `SHOW REPLICA STATUS\G` |
| Запретить запись в реплику | `SET PERSIST super_read_only=ON;` |
| Кто что делает / топ запросов | `SHOW PROCESSLIST;` / `sys.statement_analysis` |

---

## 🧠 Что запомнить

1. MySQL живёт в PHP/Bitrix/WordPress, легаси и части продуктовых команд — эксплуатировать
   его надо уметь так же, как PG.
2. Для прода — только LTS (8.4 или 9.7); 8.0 умер в апреле 2026; `mysql:latest` — Innovation.
3. MariaDB — самостоятельный форк: свои LTS (10.11/11.4/11.8/12.3), GTID, утилиты, синтаксис.
4. ⭐ Два журнала: redo — надёжность, binlog — репликация и PITR.
5. Доступ — `'user'@'host'` в SQL, выигрывает самый конкретный хост; `app@%` и
   `app@localhost` — разные учётки.
6. `mysql_native_password` выключен в 8.4 и удалён в 9.0 — главная причина поломок апгрейда.
7. `innodb_buffer_pool_size` 60–75% RAM; `flush_log_at_trx_commit=1` + `sync_binlog=1` —
   не терять коммиты.
8. Бэкап: `mysqldump --single-transaction` / MySQL Shell, XtraBackup для физического,
   binlog для PITR; `mysqlpump` удалён.
9. В 8.4 `MASTER/SLAVE`-синтаксис удалён: `CHANGE REPLICATION SOURCE TO`, `START REPLICA`,
   `SHOW REPLICA STATUS`, `SHOW BINARY LOG STATUS`.
10. Реплика MySQL принимает запись — `super_read_only=ON` обязателен; сломанную репликацию
    чинят устранением причины, а не пропуском ошибок.

---

## Задачи

> Стенд: Docker (`mysql:8.4`, для сравнения — `mariadb:11.8`); для репликации — compose
> из мини-лабы конспекта (`~/sandbox/mysql-lab`). Всё — на учебном стенде, не на проде.

---

### Блок A. Теория

**A1.** Где DevOps чаще всего встречает MySQL/MariaDB? Почему нельзя ответить
«у нас PostgreSQL, MySQL мне не нужен»?

<details><summary>Ответ</summary>

PHP-проекты (WordPress, 1С-Битрикс, Laravel, Magento, Moodle), легаси-монолиты,
готовые продукты (Zabbix, Nextcloud, Jira, Keycloak), часть продуктовых команд, managed-базы
в облаках. В большой компании почти всегда есть «ещё и MySQL», а дежурный отвечает за все базы.

</details>

**A2.** Чем LTS отличается от Innovation? Что случилось с MySQL 8.0 в 2026 году,
что такое версия 26.7 и какой тег образа писать в compose?

<details><summary>Ответ</summary>

LTS — долгоживущая ветка (5 лет premier + 3 extended), только исправления;
Innovation — новые фичи, поддержка до выхода следующей. 8.0 получила EOL 30.04.2026.
После 9.7 LTS MySQL перешла на календарные версии: 26.7 — Innovation июля 2026.
В compose — явная LTS (`mysql:8.4` или `mysql:9.7`), не `latest`.

</details>

**A3.** Почему MariaDB 11.x — это уже не «тот же MySQL»? Назови 3–4 отличия,
важные для эксплуатации.

<details><summary>Ответ</summary>

Другой формат GTID (несовместим с MySQL), свои плагины аутентификации, `JSON` —
псевдоним `LONGTEXT`, встроенная Galera, свои утилиты (`mariadb-dump`, `mariadb-backup`),
старый синтаксис `CHANGE MASTER`, собственный цикл LTS. Переезд — через логический дамп.

</details>

**A4.** ⭐ Какие два журнала есть у MySQL и за что отвечает каждый? Как это устроено в PostgreSQL?

<details><summary>Ответ</summary>

Redo log (InnoDB) — физический журнал для восстановления после сбоя;
binlog (уровень сервера) — логический журнал изменений для репликации и PITR.
В PG одну роль играет WAL: и crash recovery, и репликация, и PITR.

</details>

**A5.** Почему `innodb_buffer_pool_size` ставят в 60–75% RAM, а `shared_buffers` в PG — около 25%?

<details><summary>Ответ</summary>

InnoDB читает данные с `O_DIRECT` мимо кэша ОС и рассчитывает только на свой
buffer pool. PostgreSQL использует двойное кэширование — `shared_buffers` + page cache ОС,
поэтому своему кэшу отдаёт меньше.

</details>

**A6.** Что означают `innodb_flush_log_at_trx_commit = 1/2/0` и `sync_binlog = 1/0`?
Какая комбинация нужна базе с деньгами?

<details><summary>Ответ</summary>

`flush_log_at_trx_commit=1` — redo сбрасывается на диск на каждый коммит (надёжно);
`2` — пишется в ОС, fsync раз в секунду (теряем до секунды при падении ОС); `0` — теряем
до секунды даже при падении mysqld. `sync_binlog=1` — binlog на диск на каждый коммит,
`0` — на усмотрение ОС. Для денег — `1` и `1`.

</details>

**A7.** Чем отличаются `SET GLOBAL`, `SET PERSIST` и `SET PERSIST_ONLY`? Какой механизм
в PostgreSQL аналогичен `SET PERSIST`?

<details><summary>Ответ</summary>

`SET GLOBAL` — до рестарта; `SET PERSIST` — сразу и после рестарта (пишет
`mysqld-auto.cnf`); `SET PERSIST_ONLY` — только в файл, для статических параметров,
применится после рестарта. Аналог — `ALTER SYSTEM` → `postgresql.auto.conf`.

</details>

**A8.** Как MySQL выбирает учётку для входящего соединения? Чем это отличается от правила
первого совпадения в `pg_hba.conf`?

<details><summary>Ответ</summary>

MySQL сортирует учётки по конкретности хоста (точный IP → маска → `%`)
и выбирает самую конкретную подходящую; порядок создания не важен.
В `pg_hba.conf` решает порядок строк в файле.

</details>

**A9.** Пользователю выдали роль с нужными правами, а он получает `Access denied`. Почему?

<details><summary>Ответ</summary>

Роли в MySQL по умолчанию не активны в сессии. Нужен `SET DEFAULT ROLE ALL TO …`
(или `SET ROLE` в сессии, или `activate_all_roles_on_login=ON`).

</details>

**A10.** ⭐ Опиши судьбу `mysql_native_password` по версиям 8.0 → 8.4 → 9.x. Что сломается
при апгрейде и как готовиться?

<details><summary>Ответ</summary>

8.0.34 — deprecated; 8.4 — отключён по умолчанию (включается `mysql_native_password=ON`);
9.0 — удалён. Сломаются учётки с этим плагином и старые драйверы. Подготовка:
`SELECT user, host FROM mysql.user WHERE plugin='mysql_native_password';`, перевод на
`caching_sha2_password`, обновление драйверов, TLS для клиентов.

</details>

**A11.** Как устроен MVCC в InnoDB и почему в MySQL нет VACUUM? Что в MySQL играет роль
«раздувания от долгих транзакций»?

<details><summary>Ответ</summary>

Старые версии строк хранятся в undo log, таблица содержит только актуальную версию;
фоновый purge удаляет ненужные записи undo. Долгая транзакция не даёт purge работать:
растёт history list length, undo-табличные пространства пухнут, чтения идут по длинным цепочкам версий.

</details>

**A12.** Какой уровень изоляции по умолчанию в MySQL и в PostgreSQL? Чем это может
удивить разработчика, переходящего с PG?

<details><summary>Ответ</summary>

MySQL — REPEATABLE READ, PostgreSQL — READ COMMITTED. В MySQL внутри транзакции
повторное чтение видит старый снимок, появляются gap locks и больше deadlock-ов
при конкурентных вставках.

</details>

**A13.** Перечисли способы бэкапа MySQL (логический, физический, PITR). Что случилось с `mysqlpump`?

<details><summary>Ответ</summary>

Логический — `mysqldump`, MySQL Shell (`util.dumpInstance/dumpSchemas`), mydumper;
физический — Percona XtraBackup (для MariaDB — `mariadb-backup`); PITR — полный бэкап +
binlog через `mysqlbinlog`. `mysqlpump` удалён в 8.4.

</details>

**A14.** Зачем нужен GTID? Что без него приходится знать при настройке реплики?

<details><summary>Ответ</summary>

GTID — уникальный номер каждой транзакции. Реплика сама сообщает, что применила
(`SOURCE_AUTO_POSITION=1`), переключение на другой source не требует вычислять позиции.
Без GTID нужно знать имя binlog-файла и позицию (`SOURCE_LOG_FILE`, `SOURCE_LOG_POS`).

</details>

**A15.** ⭐ Какие команды репликации удалены в 8.4 и на что их заменили? Назови минимум пять пар.

<details><summary>Ответ</summary>

`CHANGE MASTER TO` → `CHANGE REPLICATION SOURCE TO`; `START/STOP SLAVE` →
`START/STOP REPLICA`; `SHOW SLAVE STATUS` → `SHOW REPLICA STATUS`; `RESET SLAVE` →
`RESET REPLICA`; `SHOW MASTER STATUS` → `SHOW BINARY LOG STATUS`; `RESET MASTER` →
`RESET BINARY LOGS AND GTIDS`; `SHOW SLAVE HOSTS` → `SHOW REPLICAS`.

</details>

**A16.** Почему в реплику MySQL можно писать, а в реплику PostgreSQL — нет? Чем это опасно
и как защищаются?

<details><summary>Ответ</summary>

Реплика PG применяет физический WAL и находится в режиме восстановления —
запись невозможна в принципе. Реплика MySQL — обычный сервер, который применяет события
binlog, поэтому принимает запись. Опасно: конфликты (1062/1032), errant GTID, расхождение
данных. Защита — `super_read_only=ON` на всех репликах.

</details>

**A17.** Что такое semi-sync репликация и в каком случае она **молча** перестаёт быть semi-sync?

<details><summary>Ответ</summary>

Source ждёт подтверждения, что хоть одна реплика получила событие. Если подтверждения
нет дольше `rpl_semi_sync_source_timeout`, source переходит в асинхронный режим без ошибок
для клиентов — нужно алертить на `Rpl_semi_sync_source_status`.

</details>

**A18.** Сравни InnoDB Cluster, Galera и Orchestrator: принцип и когда что выбирают.

<details><summary>Ответ</summary>

InnoDB Cluster — Group Replication (консенсус, ≥3 узла) + MySQL Router + AdminAPI,
официальное решение Oracle. Galera — синхронный multi-master с сертификацией транзакций,
стандарт в мире MariaDB/Percona XtraDB Cluster. Orchestrator — внешний менеджер
async-топологии с автоматическим failover (оригинал заархивирован, жив форк Percona).

</details>

---

### Блок B. «Что тут не так»

```yaml
B1.  services:
       db:
         image: mysql:latest
```

<details><summary>Ответ</summary>

`latest` — Innovation-ветка (26.x): при пересоздании контейнера база внезапно
переедет на новую версию без возможности откатиться. Нужен явный LTS-тег.

</details>

```bash
B2.  mysqldump -uroot -pS3cret shop > /var/lib/mysql/shop.sql      # в cron, каждую ночь
```

<details><summary>Ответ</summary>

Нет `--single-transaction` (блокировки/неконсистентность), нет `--routines --triggers
--events`, пароль в командной строке (виден в `ps`), дамп в datadir на том же диске, одно
имя файла каждую ночь. Правильно: `~/.my.cnf`/`--defaults-extra-file`, файл с датой,
вынос на другой хост, проверка восстановления.

</details>

```sql
B3.  CREATE USER 'app'@'%' IDENTIFIED BY 'app';
     GRANT ALL ON *.* TO 'app'@'%' WITH GRANT OPTION;
```

<details><summary>Ответ</summary>

Приложение может подключиться откуда угодно, со слабым паролем, с правами на все базы
и правом раздавать права — фактически суперпользователь. Нужен конкретный хост/подсеть,
только DML на свою базу, `REQUIRE SSL`.

</details>

```ini
B4.  # база платёжного сервиса, «для скорости»
     innodb_flush_log_at_trx_commit = 0
     sync_binlog = 0
```

<details><summary>Ответ</summary>

При падении сервера теряются последние коммиты (до секунды и больше), binlog может
разойтись с данными — реплики и PITR получат другую историю. Для платежей — `1` и `1`.

</details>

```ini
B5.  # my.cnf, одинаковый на primary и на реплике (скопировали)
     server_id = 1
```

<details><summary>Ответ</summary>

Одинаковый `server_id` ломает репликацию: реплика игнорирует события со «своим»
id или падает с ошибкой. `server_id` уникален на каждом узле.

</details>

```ini
B6.  # полный бэкап раз в неделю, PITR «по binlog»
     binlog_expire_logs_seconds = 86400
```

<details><summary>Ответ</summary>

Binlog живёт сутки, а полный бэкап — раз в неделю: восстановиться на момент
«3 дня назад» невозможно. Хранить binlog дольше интервала полных бэкапов и выгружать с хоста.

</details>

```ini
B7.  character_set_server = utf8
```

<details><summary>Ответ</summary>

`utf8` в MySQL — это `utf8mb3`, не хранит 4-байтовые символы (эмодзи). Нужен `utf8mb4`.

</details>

```ini
B8.  # сервер 32 ГБ RAM, на нём только MySQL
     innodb_buffer_pool_size = 128M
```

<details><summary>Ответ</summary>

128 МБ — значение по умолчанию, почти все чтения пойдут на диск. На выделенном
сервере 32 ГБ — порядка 20–24 ГБ (или `innodb_dedicated_server=ON`).

</details>

```ini
B9.  # MySQL 8.4, в плане на квартал — апгрейд на 9.7
     mysql_native_password = ON        # «чтобы всё работало»
```

<details><summary>Ответ</summary>

Это откладывание проблемы: в 9.0+ плагина нет, и апгрейд сломает всех клиентов
в день переключения. Нужно заранее перевести учётки и драйверы на `caching_sha2_password`.

</details>

```bash
B10. # cron каждые 5 минут на реплике (GTID включён)
     mysql -e "STOP REPLICA; SET GLOBAL sql_replica_skip_counter=1; START REPLICA;"
```

<details><summary>Ответ</summary>

С GTID `sql_replica_skip_counter` не работает (ошибка), а сама идея «автоматически
пропускать ошибки» ведёт к тихому расхождению данных. Нужно разбирать причину каждой ошибки.

</details>

```bash
B11. # проверка мониторинга после апгрейда на 8.4
     mysql -e "SHOW SLAVE STATUS\G" | grep Seconds_Behind_Master
```

<details><summary>Ответ</summary>

В 8.4 `SHOW SLAVE STATUS` удалён — команда вернёт синтаксическую ошибку, и мониторинг
«молчит». Нужно `SHOW REPLICA STATUS` и поле `Seconds_Behind_Source`.

</details>

```bash
B12. # сервер обновили до MySQL 8.4, бэкапилка осталась из пакета percona-xtrabackup-80
     xtrabackup --backup --target-dir=/backup/full       # «у нас всегда был этот пакет»
```

<details><summary>Ответ</summary>

XtraBackup 8.0 не поддерживает MySQL 8.4 — нужна ветка 8.4 (серия бэкапилки
совпадает с серией сервера).

</details>

```bash
B13. xtrabackup --backup --target-dir=/backup/full && xtrabackup --copy-back --target-dir=/backup/full
```

<details><summary>Ответ</summary>

Пропущен `--prepare`: копия содержит незавершённые изменения, redo не применён —
восстановленная база будет неконсистентной или не запустится.

</details>

```sql
B14. -- реплика
     SET GLOBAL read_only = ON;     -- приложение-отчётник ходит под пользователем с CONNECTION_ADMIN
```

<details><summary>Ответ</summary>

`read_only` не действует на пользователей с `CONNECTION_ADMIN`/`SUPER` — отчётник
может писать в реплику. Нужен `super_read_only=ON` и пользователь без админских привилегий.

</details>

---

### Блок C. Практика

#### C1. Поднять и настроить
1. Запусти `mysql:8.4` с каталогом `conf.d/` (свой `my.cnf`: buffer pool, `max_connections`,
   slow log, `utf8mb4`).
2. Проверь `SHOW VARIABLES`, что значения применились.
3. Сделай `SET PERSIST max_connections = 250;`, перезапусти контейнер, найди файл
   `mysqld-auto.cnf` в datadir и посмотри, что в нём.

<details><summary>Ответ</summary>

`mysqld-auto.cnf` — JSON с параметрами, их значениями, временем и пользователем,
который их установил. Удалить параметр из него — `RESET PERSIST max_connections;`.

</details>

#### C2. `'user'@'host'` — две разные учётки
1. Создай `'app'@'localhost'` с паролем `one` и `'app'@'%'` с паролем `two`.
2. Подключись изнутри контейнера через сокет и снаружи по TCP — какой пароль подходит где?
3. Посмотри `SELECT user, host FROM mysql.user;` и `SELECT CURRENT_USER();` в обоих случаях.

<details><summary>Ответ</summary>

Через сокет (`localhost`) сработает `'app'@'localhost'` и пароль `one`, по TCP снаружи —
`'app'@'%'` и пароль `two`. `CURRENT_USER()` покажет, под какой учёткой ты на самом деле.

</details>

#### C3. Роли
1. Создай роль `readonly` с `SELECT ON shop.*`, выдай её пользователю `analyst`.
2. Подключись под `analyst` и попробуй `SELECT` — зафиксируй ошибку.
3. Почини через `SET DEFAULT ROLE`; проверь `SELECT CURRENT_ROLE();`.

<details><summary>Ответ</summary>

До `SET DEFAULT ROLE` — `SELECT command denied`, `CURRENT_ROLE()` = `NONE`; после —
роль активна, `SELECT` работает.

</details>

#### C4. Прощание с `mysql_native_password`
1. На 8.4 попробуй `CREATE USER 'legacy'@'%' IDENTIFIED WITH mysql_native_password BY 'x';`.
2. Включи `mysql_native_password=ON`, повтори, подключись.
3. Переведи учётку на `caching_sha2_password`, выключи плагин, проверь `SELECT user, plugin FROM mysql.user;`.
4. Запиши, какой запрос найдёт все учётки, которые сломаются при апгрейде на 9.7.

<details><summary>Ответ</summary>

Без плагина `CREATE USER … WITH mysql_native_password` вернёт ошибку
`Plugin 'mysql_native_password' is not loaded`. Поиск кандидатов на поломку:
`SELECT user, host FROM mysql.user WHERE plugin = 'mysql_native_password';`.

</details>

#### C5. Логический дамп и проверка восстановления
1. Наполни базу (свой скрипт или `sysbench oltp_read_write prepare`).
2. `mysqldump --single-transaction --routines --triggers --events` → сжатый файл с датой.
3. Восстанови в **другой** контейнер, сравни `CHECKSUM TABLE` и `COUNT(*)` ключевых таблиц.
4. Замерь время снятия и восстановления.

<details><summary>Ответ</summary>

`CHECKSUM TABLE` должен совпасть; время восстановления обычно в разы больше времени
дампа (индексы строятся при загрузке) — это и есть твой RTO для логического бэкапа.

</details>

#### C6. MySQL Shell против mysqldump
1. На той же базе сделай `util.dumpSchemas(["shop"], "/backup/shell", {threads: 4})`.
2. Загрузи в чистый инстанс через `util.loadDump` (не забудь `local_infile`).
3. Сравни время и размер с C5, запиши вывод.

<details><summary>Ответ</summary>

MySQL Shell быстрее за счёт многопоточности и чанков, особенно на загрузке.
`loadDump` без `local_infile=ON` на целевом сервере откажется работать.

</details>

#### C7. ⭐ PITR по binlog
1. Сделай полный дамп с `--source-data=2`, запомни позицию из комментария в дампе.
2. Вставь ещё строк, запомни время; затем `DROP TABLE shop.orders;`.
3. Найди событие `DROP` через `mysqlbinlog --base64-output=DECODE-ROWS -vv`.
4. В **отдельный** контейнер восстанови дамп и доиграй binlog до момента перед `DROP`.
5. Проверь: таблица есть, строки после дампа есть, `DROP` не применился.
6. Отдельно проверь, как `--stop-datetime` зависит от часового пояса машины.

<details><summary>Ответ</summary>

Позиция берётся из строки `-- CHANGE REPLICATION SOURCE TO SOURCE_LOG_FILE='…',
SOURCE_LOG_POS=…` в начале дампа. Доигрывают с `--start-position` до `--stop-position`
(позиция перед `DROP`) или `--stop-datetime`. `--stop-datetime` интерпретируется в часовом
поясе машины с `mysqlbinlog`, поэтому точнее останавливаться по позиции или GTID.

</details>

#### C8. ⭐ Реплика: поднять, сломать, починить
Пройди мини-лабу конспекта целиком. Дополнительно:
1. Под нагрузкой (`sysbench`) понаблюдай `Seconds_Behind_Source`.
2. Останови реплику на 5 минут, запусти снова — сколько времени она догоняла?
3. Сломай репликацию вторым способом: удали на реплике строку, которую source потом обновит
   (ошибка 1032). Почини без пропуска событий.

<details><summary>Ответ</summary>

Ошибка 1032 (`Can't find record`) лечится возвратом на реплику недостающей строки
в том виде, что был на source (взять с source), затем `START REPLICA`. Лаг после простоя
убывает со скоростью, зависящей от `replica_parallel_workers` и нагрузки.

</details>

#### C9. Errant GTID
1. После C8 найди на реплике транзакции, которых нет на source:
   `SELECT GTID_SUBTRACT(@@GLOBAL.gtid_executed, '<gtid_executed с source>');`
2. Объясни, что будет, если эту реплику сделать новым source.
3. Исправь: вставь на source пустые транзакции с этими GTID (или переналей реплику).

<details><summary>Ответ</summary>

Errant GTID при failover: остальные реплики запросят у нового source транзакции
с его uuid — если binlog с ними уже удалён, репликация сломается, если нет — «чужие»
изменения разъедутся по кластеру. Лечение — пустые транзакции с этими GTID на source
(`SET GTID_NEXT=…; BEGIN; COMMIT;`) либо переналивка реплики.

</details>

#### C10. Мониторинг
1. Подними `mysqld_exporter` рядом со стендом (отдельный пользователь с `MAX_USER_CONNECTIONS 3`).
2. Найди в `/metrics` метрики соединений, buffer pool и статуса репликации
   (запиши точные имена для своей версии).
3. Напиши два правила Prometheus: «репликация остановилась» и «лаг больше 60 с».
4. Останови SQL-поток на реплике и убедись, что алерт срабатывает.

<details><summary>Ответ</summary>

Правила вида `mysql_slave_status_replica_sql_running == 0` (`for: 1m`)
и `mysql_slave_status_seconds_behind_source > 60` (`for: 5m`); точные имена зависят
от версии сервера и экспортера — берутся из собственного `/metrics`.

</details>

#### C11. XtraBackup (со звёздочкой)
Контейнер с XtraBackup ветки 8.4 (образ `percona/percona-xtrabackup`, проверь тег) с общим томом данных: `--backup` → `--prepare` →
восстановление в новый том → запуск `mysql:8.4` на нём. Сравни время с C5.

<details><summary>Ответ</summary>

Восстановление физической копии обычно заметно быстрее логического: копируются
файлы, индексы не перестраиваются.

</details>

#### C12. InnoDB Cluster в песочнице (со звёздочкой)
В `mysqlsh`: `dba.deploySandboxInstance(3310)` (и 3320, 3330), `dba.createCluster('lab')`,
`cluster.addInstance(...)`, `cluster.status()`. Убей primary и посмотри, кто стал новым.
Подними MySQL Router и проверь, что порт 6446 ведёт на нового primary.

<details><summary>Ответ</summary>

Group Replication выберет нового primary за секунды; MySQL Router сам переключит
порт 6446 на него, приложение увидит лишь переподключение.

</details>

---

### Блок D. Инциденты

**D1.** После апгрейда MySQL на 8.4 старый PHP-сайт не открывается, в логе приложения
`Plugin 'mysql_native_password' is not loaded`. Твои действия сейчас и «правильно».

<details><summary>Ответ</summary>

Сейчас: временно `mysql_native_password=ON` в `[mysqld]` и рестарт (восстановить сервис).
Правильно: перевести учётку на `caching_sha2_password`, обновить PHP/драйвер, включить TLS,
затем выключить плагин. Урок: такие вещи проверяются на стейдже до апгрейда.

</details>

**D2.** Алерт: `Replica_SQL_Running: No`, `Last_SQL_Error: … Duplicate entry '4521' for key
'orders.PRIMARY'`. Порядок действий.

<details><summary>Ответ</summary>

Не пропускать сразу. Выяснить, откуда строка на реплике (писали ли в неё, был ли
`super_read_only`), сравнить строку с source. Удалить мешающую строку на реплике →
`START REPLICA`. Включить `super_read_only`, проверить консистентность `pt-table-checksum`,
при масштабных расхождениях — переналить реплику.

</details>

**D3.** Реплика была выключена неделю. После старта: `Replica_IO_Running: No`,
`Got fatal error 1236 … Cannot replicate because the source purged required binary logs`.
Что произошло и как восстановить?

<details><summary>Ответ</summary>

Пока реплика стояла, binlog на source удалили по `binlog_expire_logs_seconds`, нужных
транзакций больше нет. Догнать невозможно — реплику переналивают (XtraBackup/Clone/MySQL Shell)
и заново подключают. Вывод: алерт на остановленную реплику и retention binlog под максимальный
допустимый простой реплики.

</details>

**D4.** Кончается диск на primary. `du` показывает: 400 ГБ в `/var/lib/mysql/binlog.*`.
Что делаешь и чего делать нельзя?

<details><summary>Ответ</summary>

Проверить, почему копятся: большой `binlog_expire_logs_seconds`, стоящая реплика,
которой они нужны, сломанная выгрузка. Удалять **только** через `PURGE BINARY LOGS BEFORE '…'`
(или `TO 'binlog.000xxx'`), убедившись, что реплики и PITR их не требуют (`SHOW REPLICA STATUS`
на репликах). Нельзя `rm binlog.*` руками — ломается индекс binlog и репликация.

</details>

**D5.** Каждую ночь лаг реплики вырастает до 2 часов и к обеду рассасывается.
В 01:00 запускается пакетный `UPDATE` на 30 млн строк. Причина и решения.

<details><summary>Ответ</summary>

Один огромный `UPDATE` — одна транзакция: на реплике она применяется целиком и
долго, остальное стоит за ней. Решения: дробить пакетно (по 1–10 тыс. строк с паузами),
планировать в окно, многопоточный applier помогает только между независимыми транзакциями.

</details>

**D6.** Приложение сыплет `ERROR 1040 (08004): Too many connections`. Как зайти на сервер
и что проверить?

<details><summary>Ответ</summary>

MySQL держит одно дополнительное соединение для пользователя с `CONNECTION_ADMIN`/`SUPER`
(или отдельный `admin_port`) — войти под админом. Проверить `SHOW PROCESSLIST` (кто держит,
`Sleep` с большим `Time`?), `Threads_connected`, пулы приложения. Лечение — пулы, `wait_timeout`,
ProxySQL, а не бесконечный рост `max_connections`.

</details>

**D7.** Сайт встал: `SHOW PROCESSLIST` показывает сотни запросов в состоянии
`Waiting for table metadata lock`, а в начале списка — `ALTER TABLE orders ADD COLUMN …`.
Что происходит и как разблокировать?

<details><summary>Ответ</summary>

`ALTER TABLE` ждёт метаданную блокировку, которую держит долгая транзакция
(часто «спящая» с открытым `BEGIN`); все новые запросы к таблице встают в очередь **за ALTER**.
Найти блокирующего (`sys.schema_table_lock_waits`, `information_schema.innodb_trx`), снять
его или сам `ALTER` (`KILL`). Профилактика — `lock_wait_timeout` для DDL и онлайн-миграции
(тема [13. Миграции схемы](/databases/13-schema-migrations)).

</details>

**D8.** В 11:20 кто-то выполнил `DELETE FROM customers;` без `WHERE`. Есть ночной
XtraBackup и binlog. Опиши восстановление, не останавливая прод.

<details><summary>Ответ</summary>

Развернуть ночной XtraBackup в **отдельный** инстанс, доиграть binlog до позиции
перед `DELETE` (найти через `mysqlbinlog -vv`), выгрузить `customers` дампом и загрузить
в прод (или точечно вставить недостающие строки). Прод не останавливается, улики не уничтожаются.

</details>

**D9.** Приложение не подключается: `Host '10.0.1.7' is blocked because of many connection errors`.
Причина и как разблокировать.

<details><summary>Ответ</summary>

Хост накопил больше `max_connect_errors` неудачных рукопожатий (обрывы сети,
health-check по TCP без протокола). Разблокировать: `TRUNCATE TABLE performance_schema.host_cache;`
(старый `FLUSH HOSTS` устарел), поднять `max_connect_errors`, починить источник ошибок.

</details>

**D10.** База медленная, `SHOW ENGINE INNODB STATUS` показывает `History list length 5000000`.
Что это значит и где искать виновника?

<details><summary>Ответ</summary>

Purge не успевает — есть транзакция, которая давно открыта и держит старые версии
строк. Искать в `information_schema.innodb_trx ORDER BY trx_started` (и `SHOW PROCESSLIST`),
часто это забытая сессия или долгий отчёт/дамп без `--single-transaction`-логики. Завершить её.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Чем MySQL отличается от PostgreSQL с точки зрения эксплуатации?

<details><summary>Ответ</summary>

Поток на соединение вместо процесса, доступ через `'user'@'host'` вместо `pg_hba.conf`,
два журнала (redo + binlog), нет VACUUM (undo + purge), реплика принимает запись,
DDL не транзакционный, свои инструменты бэкапа и HA.

</details>

**2.** Что такое binlog и чем он отличается от redo log?

<details><summary>Ответ</summary>

Binlog — логический журнал изменений сервера для репликации и PITR; redo — физический
журнал InnoDB для восстановления после сбоя.

</details>

**3.** Как вы бэкапите MySQL и как делаете PITR?

<details><summary>Ответ</summary>

XtraBackup (или MySQL Shell дамп) по расписанию + непрерывная выгрузка binlog с хоста;
PITR — восстановить полный бэкап в отдельный инстанс и доиграть binlog через `mysqlbinlog`
до нужной позиции/GTID; регулярная проверка восстановления.

</details>

**4.** Как устроена репликация MySQL и что такое GTID?

<details><summary>Ответ</summary>

Source пишет binlog, реплика забирает его в relay log и применяет; GTID — глобальный
номер транзакции, позволяющий реплике автоматически находить позицию.

</details>

**5.** Как поднять реплику без остановки primary?

<details><summary>Ответ</summary>

`mysqldump --single-transaction --set-gtid-purged=ON`, MySQL Shell, XtraBackup или Clone
plugin — всё без остановки; затем `CHANGE REPLICATION SOURCE TO … SOURCE_AUTO_POSITION=1`.

</details>

**6.** Реплика остановилась с ошибкой 1062. Что делаешь?

<details><summary>Ответ</summary>

Разобраться в причине, устранить конфликт, `START REPLICA`, включить `super_read_only`,
проверить консистентность; пропуск события — только осознанно пустой транзакцией.

</details>

**7.** Как измерить лаг реплики и почему `Seconds_Behind_Source` недостаточно?

<details><summary>Ответ</summary>

`Seconds_Behind_Source` считает по событиям в relay log и не видит отставания receiver;
надёжнее pt-heartbeat или метрики `performance_schema`.

</details>

**8.** Что изменилось в MySQL 8.4 такого, что ломает скрипты и клиентов?

<details><summary>Ответ</summary>

Удалён `MASTER/SLAVE`-синтаксис, `mysql_native_password` отключён, `mysqlpump` удалён,
новые умолчания InnoDB; 8.0 закончил поддержку.

</details>

**9.** Какие HA-решения для MySQL знаешь?

<details><summary>Ответ</summary>

InnoDB Cluster (Group Replication + Router), InnoDB ReplicaSet, Galera
(MariaDB/PXC), Orchestrator для async, операторы в Kubernetes, managed-сервисы.

</details>

**10.** Зачем ProxySQL?

<details><summary>Ответ</summary>

Пул и мультиплексирование соединений, разделение чтения/записи, маскировка failover
от приложения, правила маршрутизации запросов.

</details>

**11.** Что мониторишь у MySQL?

<details><summary>Ответ</summary>

Доступность, соединения и `Threads_running`, лаг и статус репликации, buffer pool,
блокировки и deadlock-и, медленные запросы, history list length, место под данные и binlog,
возраст последнего бэкапа.

</details>

---

### 🎯 Чек-лист

- [ ] Знаю, где встречается MySQL, и отличаю LTS (8.4, 9.7) от Innovation (26.x)
- [ ] Понимаю, чем MariaDB отличается от MySQL для эксплуатации
- [ ] ⭐ Объясню разницу redo log и binlog и сравню с WAL
- [ ] Настроил `my.cnf`: buffer pool, надёжность коммитов, binlog, GTID, slow log
- [ ] Выдаю доступ через `'user'@'host'` и помню про `SET DEFAULT ROLE`
- [ ] Знаю судьбу `mysql_native_password` и как подготовить апгрейд
- [ ] Снял и восстановил `mysqldump` и MySQL Shell дамп, замерил время
- [ ] ⭐ Сделал PITR по binlog в отдельный инстанс
- [ ] Поднял реплику на GTID с новым синтаксисом 8.4, сломал и починил её
- [ ] Включаю `super_read_only` на репликах и умею найти errant GTID
- [ ] Могу сравнить InnoDB Cluster, Galera и Orchestrator и объяснить роль ProxySQL
- [ ] Настроил mysqld_exporter и алерты на остановку и лаг репликации
