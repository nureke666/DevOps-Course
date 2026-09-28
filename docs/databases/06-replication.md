---
title: "06. Репликация PostgreSQL"
description: "Потоковая и логическая репликация, слоты, синхронная/асинхронная, lag, promote/failover, Patroni"
---

# 06. Репликация PostgreSQL

> Роадмап → Базы → PostgreSQL → *«Репликация»*.
>
> **После темы ты умеешь:** поднять потоковую реплику, следить за лагом, сделать promote,
> объяснить разницу синхронной и асинхронной репликации и рассказать, как устроен
> автоматический failover.

---

## 🗺️ Идея

```text:no-line-numbers
          записи (INSERT/UPDATE/DELETE)
                  │
            ┌─────▼──────┐  WAL  ┌──────────────┐
            │  PRIMARY   │──────►│   STANDBY    │  режим восстановления,
            │ (чтение+   │ поток │ (только      │  постоянно доигрывает WAL
            │  запись)   │       │  чтение)     │
            └─────┬──────┘       └──────┬───────┘
                  │                     │
            приложение             отчёты / аналитика / резерв
```

Зачем это нужно:

| Задача | Как решает репликация |
|--------|------------------------|
| Отказ сервера | Standby можно promote'нуть в primary (минуты вместо часов) |
| Нагрузка на чтение | Тяжёлые SELECT уводят на реплику |
| Бэкап без нагрузки на прод | `pg_basebackup`/WAL-G снимают с реплики |
| Обновление версии | Логическая репликация → переключение почти без простоя |
| Географическое резервирование | Standby в другом дата-центре |

⚠️ Чего репликация **не** решает: ошибок людей и приложения.
`DROP TABLE` приедет на standby за секунду. Нужен бэкап — [тема 05](/databases/05-backup-restore).

---

## 1. Физическая (потоковая) vs логическая репликация

| | Физическая (streaming) | Логическая |
|---|------------------------|------------|
| Что передаётся | Байтовые записи WAL | Логические изменения строк |
| Объём копирования | Весь кластер целиком | Выбранные таблицы/базы |
| Версии | Только одинаковая мажорная | Можно между разными |
| Реплика доступна на запись | Нет (read-only) | Да (это отдельная база) |
| DDL реплицируется | Да | ⚠️ Нет (кроме PG16+ частично) |
| Типовое применение | HA, резерв, чтение | Апгрейд версии, CDC, интеграции, частичная выгрузка |
| `wal_level` | `replica` | `logical` |

---

## 2. Поднять потоковую реплику (руками, чтобы понимать)

### На primary

```sql
CREATE ROLE repl WITH REPLICATION LOGIN PASSWORD 'strong';
SELECT pg_create_physical_replication_slot('standby1');   -- слот (см. ниже)
```
```text:no-line-numbers
# postgresql.conf
wal_level = replica
max_wal_senders = 10
max_replication_slots = 10
wal_keep_size = 1GB          # запас WAL, если слот не используется
```
```text:no-line-numbers
# pg_hba.conf
host  replication  repl  10.0.1.6/32  scram-sha-256
```
```bash
sudo systemctl restart postgresql@16-main     # wal_level требует рестарта
```

### На standby

```bash
sudo systemctl stop postgresql@16-main
sudo -u postgres rm -rf /var/lib/postgresql/16/main/*

sudo -u postgres pg_basebackup \
  -h 10.0.1.5 -U repl -D /var/lib/postgresql/16/main \
  -Fp -Xs -P -R -S standby1
```
Флаг `-R` создаёт `standby.signal` и записывает `primary_conninfo` —
именно так контейнер превращается в реплику:
```text:no-line-numbers
# postgresql.auto.conf на standby
primary_conninfo = 'host=10.0.1.5 port=5432 user=repl password=… application_name=standby1'
primary_slot_name = 'standby1'
```
```text:no-line-numbers
# postgresql.conf на standby
hot_standby = on                 # разрешить читать со standby (по умолчанию on)
hot_standby_feedback = on        # ⚠️ защищает долгие запросы, но тормозит vacuum на primary
max_standby_streaming_delay = 30s
```
```bash
sudo systemctl start postgresql@16-main
```

### Проверка

```sql
-- на primary
SELECT client_addr, application_name, state, sync_state,
       pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS lag_bytes
FROM pg_stat_replication;

-- на standby
SELECT pg_is_in_recovery();                     -- t
SELECT now() - pg_last_xact_replay_timestamp() AS lag_time;
SELECT * FROM pg_stat_wal_receiver;
```

---

## 3. Слоты репликации: польза и опасность

```text:no-line-numbers
БЕЗ слота:                          СО слотом:
primary удаляет старые сегменты     primary ХРАНИТ сегменты, пока standby их не заберёт
WAL после checkpoint                ⇒ реплика не «отвалится навсегда»
⇒ отставшая реплика ломается
  (requested WAL segment removed)   ⚠️ но если standby умер и слот остался активным,
                                       pg_wal растёт до заполнения диска
```

```sql
SELECT slot_name, active, restart_lsn,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) AS retained
FROM pg_replication_slots;

SELECT pg_drop_replication_slot('standby1');    -- удалить брошенный слот
```
Страховка от переполнения диска (PG 13+):
```text:no-line-numbers
max_slot_wal_keep_size = 50GB     # больше не хранить: слот станет lost, зато диск цел
```

> ⭐ «Неактивный слот репликации» — одна из трёх главных причин роста `pg_wal`
> и остановки autovacuum. Это обязательный пункт мониторинга.

---

## 4. Синхронная и асинхронная репликация

```text:no-line-numbers
АСИНХРОННАЯ (по умолчанию)         СИНХРОННАЯ
COMMIT ──► primary ответил OK      COMMIT ──► ждём подтверждения standby ──► OK
           WAL уедет потом                     потеря данных при падении primary ≈ 0
быстро, но при аварии primary      медленнее на величину RTT;
теряются последние транзакции      если standby недоступен — запись ВСТАЁТ ⚠️
```

```text:no-line-numbers
# на primary
synchronous_standby_names = 'standby1'                  # один синхронный
synchronous_standby_names = 'ANY 1 (s1, s2, s3)'        # любой из трёх подтвердил
synchronous_commit = on        # remote_write | on | remote_apply — уровень строгости
```

| `synchronous_commit` | Когда COMMIT считается завершённым |
|----------------------|------------------------------------|
| `off` | Даже локальный WAL ещё не на диске |
| `local` | Локальный WAL записан |
| `remote_write` | Реплика получила и записала в ОС |
| `on` | Реплика сбросила WAL на диск ⭐ обычный выбор |
| `remote_apply` | Реплика **применила** — чтение с реплики сразу видит данные |

> ⚠️ Синхронная репликация с одной репликой — ловушка: упала реплика — встал прод.
> Поэтому берут `ANY 1 (s1, s2)` минимум с двумя кандидатами.

---

## 5. Отставание (lag) и чтение с реплики

```sql
-- на primary: лаг в байтах по каждой реплике
SELECT application_name,
       pg_wal_lsn_diff(sent_lsn, replay_lsn) AS replay_lag_bytes,
       write_lag, flush_lag, replay_lag
FROM pg_stat_replication;

-- на standby: лаг во времени
SELECT CASE WHEN pg_is_in_recovery()
            THEN now() - pg_last_xact_replay_timestamp() END AS lag;
```

Причины лага: тяжёлая запись на primary, медленный диск/сеть на standby,
конфликты восстановления, долгие запросы на реплике.

**Конфликты восстановления** — специфика чтения со standby:
реплика применяет WAL, а на ней идёт долгий `SELECT`, которому нужны старые версии строк.

| Решение | Побочный эффект |
|---------|-----------------|
| `max_standby_streaming_delay = 30s` | Реплика тормозит применение WAL ради запроса, растёт лаг |
| `hot_standby_feedback = on` | Primary не чистит нужные версии → bloat и остановка vacuum на primary |
| Ничего | Запрос убивается: `ERROR: canceling statement due to conflict with recovery` |

> 💡 Приложение, читающее с реплики, должно быть готово к **eventual consistency**:
> «записал и сразу прочитал с реплики» может не увидеть свою же запись.

---

## 6. Переключение: promote и failover

### Ручной promote

```bash
sudo -u postgres pg_ctl promote -D /var/lib/postgresql/16/main
# или
sudo -u postgres psql -c "SELECT pg_promote();"
```
```sql
SELECT pg_is_in_recovery();     -- теперь f: это полноценный primary
```

После promote старый primary **нельзя** просто включить обратно — будет split-brain
(две базы принимают запись). Возврат в строй:
```bash
sudo -u postgres pg_rewind --target-pgdata=/var/lib/postgresql/16/main \
  --source-server='host=10.0.1.6 user=repl password=…'
# либо заново pg_basebackup с нового primary
```

### Автоматический failover: Patroni

Руками failover в проде не делают — берут менеджер кластера:

```text:no-line-numbers
        ┌──────────────────────────────────────────────┐
        │  DCS (etcd / Consul) — хранит, кто сейчас     │
        │  primary; обеспечивает единственность лидера  │
        └──────┬─────────────────────┬─────────────────┘
               │                     │
        ┌──────▼──────┐       ┌──────▼──────┐
        │ Patroni     │       │ Patroni     │     Patroni управляет
        │  + Postgres │       │  + Postgres │     запуском/промоушеном,
        │  (leader)   │       │  (replica)  │     держит лидер-ключ с TTL
        └──────┬──────┘       └──────┬──────┘
               └──────────┬──────────┘
                   HAProxy / PgBouncer
                   (маршрутизация: 5432 → leader, 5433 → replicas)
                          ▲
                     приложение
```

| Компонент | Роль |
|-----------|------|
| **Patroni** | Следит за Postgres, участвует в выборах, делает promote/rewind автоматически |
| **etcd/Consul** | Распределённое хранилище и кворум (отсюда требование нечётного числа узлов) |
| **HAProxy** | Единая точка входа; определяет лидера через HTTP API Patroni (`/leader`, `/replica`) |
| **PgBouncer** | Пул соединений перед всем этим |

Альтернативы: repmgr, pg_auto_failover, операторы в Kubernetes (CloudNativePG, Zalando).

---

## 7. Логическая репликация (кратко, но по делу)

```text:no-line-numbers
wal_level = logical      # на источнике, требует рестарта
```
```sql
-- на источнике (publisher)
CREATE PUBLICATION pub_orders FOR TABLE orders, order_items;
-- или FOR ALL TABLES;

-- на приёмнике (subscriber) — таблицы должны существовать заранее!
CREATE SUBSCRIPTION sub_orders
  CONNECTION 'host=10.0.1.5 dbname=shop user=repl password=…'
  PUBLICATION pub_orders;

-- контроль
SELECT * FROM pg_stat_subscription;
SELECT * FROM pg_publication;
```

Где применяют: мажорный апгрейд без простоя, перенос части данных в другую базу,
CDC в аналитику/Kafka (`pgoutput`, Debezium), объединение данных из нескольких баз.

Ограничения: DDL не реплицируется, нужны первичные ключи (или `REPLICA IDENTITY`),
последовательности не синхронизируются, на большом объёме первичная синхронизация тяжёлая.

---

## 8. Грабли

| Грабля | Последствие | Правильно |
|--------|-------------|-----------|
| Слот остался после смерти реплики | `pg_wal` растёт, кончается диск | Мониторить `pg_replication_slots.active`, `max_slot_wal_keep_size` |
| Синхронная репликация с одной репликой | Упала реплика — встал прод | `ANY 1 (s1, s2)` |
| `hot_standby_feedback = on` без контроля | Bloat и остановка vacuum на primary | Осознанно, с мониторингом |
| Старый primary включили после promote | Split-brain, расходящиеся данные | `pg_rewind` или пересоздание |
| Разные мажорные версии | Реплика не запустится | Одинаковые версии |
| Считают реплику бэкапом | Ошибочные изменения реплицируются | Бэкап отдельно |
| Приложение читает с реплики без учёта лага | «Мои данные пропали» | Критичное чтение — с primary |
| Failover руками в 3 ночи | Долгий простой, ошибки | Patroni + HAProxy |

---

## 💼 Как это в DevOps

- Типовой прод: primary + 1-2 асинхронных standby, Patroni + etcd, HAProxy/PgBouncer
  перед ними, бэкапы (WAL-G) снимаются с реплики.
- Приложение знает два адреса: «на запись» (leader) и «на чтение» (replicas) —
  либо через HAProxy-порты, либо через `target_session_attrs=read-write` в строке подключения.
- Метрики репликации обязательны в мониторинге: лаг в секундах и байтах, состояние слотов,
  число `wal_senders`, статус кластера Patroni.
- Учебные тревоги: раз в квартал в проекте делают **плановое переключение** (switchover),
  чтобы убедиться, что failover работает и приложение переживает смену лидера.
- Кандидатом на promote должна быть реплика с наименьшим лагом — Patroni учитывает это сам.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Роль для репликации | `CREATE ROLE repl WITH REPLICATION LOGIN PASSWORD '…';` |
| Разрешить реплику | `host replication repl 10.0.1.6/32 scram-sha-256` |
| Создать слот | `SELECT pg_create_physical_replication_slot('standby1');` |
| Склонировать базу в реплику | `pg_basebackup -h primary -U repl -D PGDATA -Fp -Xs -P -R -S standby1` |
| Файл-признак реплики | `standby.signal` в PGDATA |
| Адрес primary | `primary_conninfo` в `postgresql.auto.conf` |
| Состояние реплик (на primary) | `SELECT * FROM pg_stat_replication;` |
| Лаг во времени (на standby) | `SELECT now() - pg_last_xact_replay_timestamp();` |
| Это реплика? | `SELECT pg_is_in_recovery();` |
| Слоты и удержанный WAL | `SELECT * FROM pg_replication_slots;` |
| Удалить брошенный слот | `SELECT pg_drop_replication_slot('standby1');` |
| Сделать репликой primary | `SELECT pg_promote();` |
| Вернуть старый primary | `pg_rewind` |
| Синхронная репликация | `synchronous_standby_names = 'ANY 1 (s1, s2)'` |
| Логическая публикация | `CREATE PUBLICATION … FOR TABLE …;` |
| Подписка | `CREATE SUBSCRIPTION … PUBLICATION …;` |

---

## 🧠 Что запомнить

1. Физическая репликация копирует WAL байт в байт: тот же кластер, та же версия, read-only.
2. Логическая передаёт изменения строк: выборочно, между версиями, но без DDL.
3. Реплика создаётся `pg_basebackup -R`; признак реплики — файл `standby.signal`.
4. ⭐ Слот репликации гарантирует, что WAL не удалят раньше времени — и он же способен
   заполнить диск, если реплика умерла. Мониторить обязательно.
5. Асинхронная репликация быстрее, но теряет последние транзакции при аварии primary.
6. Синхронная с единственной репликой останавливает запись при её падении — нужен `ANY 1 (…)`.
7. Чтение с реплики означает eventual consistency и конфликты восстановления
   (`max_standby_streaming_delay`, `hot_standby_feedback`).
8. После promote старый primary нельзя включать «как был» — split-brain; нужен `pg_rewind`.
9. Автоматический failover в проде делает Patroni + etcd + HAProxy, а не человек в 3 ночи.
10. Реплика — про доступность, бэкап — про ошибки. Нужны оба.

---

## Задачи

> Стенд: два кластера PostgreSQL одной мажорной версии — две VM либо два контейнера
> в одной docker-сети (`docker network create pgnet`).

---

### Блок A. Теория

**A1.** Какие задачи решает репликация и какую — принципиально не решает?

<details><summary>Ответ</summary>

Решает: отказоустойчивость (promote вместо восстановления), масштабирование чтения,
снятие бэкапов без нагрузки на primary, миграции версий, географический резерв.
Не решает: ошибки людей и приложения — они реплицируются мгновенно.

</details>

**A2.** Сравни физическую и логическую репликацию по шести признакам.

<details><summary>Ответ</summary>

Физическая: байты WAL, весь кластер, одна мажорная версия, реплика read-only,
DDL реплицируется, применение — HA. Логическая: изменения строк, выбранные таблицы,
разные версии, приёмник доступен на запись, DDL не реплицируется, применение — апгрейды,
CDC, интеграции.

</details>

**A3.** Что нужно настроить на primary, чтобы к нему смогла подключиться реплика?

<details><summary>Ответ</summary>

Роль с `REPLICATION`, `wal_level = replica`, `max_wal_senders`, строку
`host replication …` в `pg_hba.conf`, при необходимости слот и `max_replication_slots`.

</details>

**A4.** Что делает флаг `-R` у `pg_basebackup`?

<details><summary>Ответ</summary>

Создаёт `standby.signal` и записывает `primary_conninfo` (и `primary_slot_name`
при `-S`) — то есть сразу делает из копии готовую реплику.

</details>

**A5.** Какой файл делает кластер репликой и чем он отличается от `recovery.signal`?

<details><summary>Ответ</summary>

`standby.signal` — постоянная реплика (режим ожидания, следует за primary).
`recovery.signal` — одноразовое восстановление (PITR): дойти до цели и открыть базу.

</details>

**A6.** Зачем нужен слот репликации? ⭐ Чем он опасен?

<details><summary>Ответ</summary>

Слот заставляет primary хранить сегменты WAL, пока реплика их не получит, —
реплика не «отвалится навсегда». Опасность: если реплика мертва, а слот остался,
WAL копится и заполняет диск primary.

</details>

**A7.** Что такое `max_slot_wal_keep_size` и от чего он защищает?

<details><summary>Ответ</summary>

Лимит на объём WAL, удерживаемого слотом (PG 13+). При превышении слот
инвалидируется (`lost`), реплику придётся пересоздавать, зато primary не умрёт от
переполнения диска.

</details>

**A8.** Чем асинхронная репликация отличается от синхронной? Что теряем в каждом случае?

<details><summary>Ответ</summary>

Асинхронная: COMMIT подтверждается сразу, при аварии primary теряются последние
транзакции. Синхронная: COMMIT ждёт подтверждения реплики — потери ≈ 0, но растёт задержка,
а при недоступности синхронной реплики запись останавливается.

</details>

**A9.** Разбери значения `synchronous_commit`: `local`, `remote_write`, `on`, `remote_apply`.

<details><summary>Ответ</summary>

`local` — локальный WAL на диске; `remote_write` — реплика записала в ОС;
`on` — реплика сбросила WAL на диск; `remote_apply` — реплика применила изменения
(чтение с неё сразу актуально, но самая высокая задержка).

</details>

**A10.** Почему синхронная репликация с одной репликой — плохая идея?

<details><summary>Ответ</summary>

Единственная синхронная реплика становится единой точкой отказа для записи:
её падение/обслуживание останавливает прод. Нужен `ANY 1 (s1, s2)`.

</details>

**A11.** Что такое конфликт восстановления на standby и три способа с ним бороться?

<details><summary>Ответ</summary>

Реплика применяет WAL, удаляющий версии строк, нужные долгому запросу на реплике.
Решения: `max_standby_streaming_delay` (реплика ждёт, растёт лаг), `hot_standby_feedback`
(primary не чистит, растёт bloat), смириться с отменой запросов.

</details>

**A12.** Что делает `hot_standby_feedback = on` и какой ценой?

<details><summary>Ответ</summary>

Реплика сообщает primary, какие версии строк ей ещё нужны, и primary их не
вакуумирует. Цена — bloat и «зависший» autovacuum на primary, особенно при долгих
аналитических запросах.

</details>

**A13.** Как измерить лаг репликации в байтах и в секундах?

<details><summary>Ответ</summary>

В байтах на primary:
`pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)` из `pg_stat_replication`.
Во времени на standby: `now() - pg_last_xact_replay_timestamp()`.

</details>

**A14.** Что такое split-brain и почему он возникает после promote? Как его избежать?

<details><summary>Ответ</summary>

Ситуация, когда две ноды считают себя primary и обе принимают запись —
данные расходятся необратимо. Избегается кворумом в DCS (etcd), фенсингом старого
лидера, обязательным `pg_rewind`/пересозданием перед возвратом в кластер.

</details>

**A15.** Из каких компонентов состоит кластер с автоматическим failover и за что отвечает каждый?

<details><summary>Ответ</summary>

Patroni (управляет Postgres и участвует в выборах), etcd/Consul (кворум и
хранение состояния лидера), HAProxy (маршрутизация на текущего лидера через API Patroni),
PgBouncer (пул соединений), мониторинг.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  pg_basebackup -h 10.0.1.5 -U repl -D /var/lib/postgresql/16/main -Fp -Xs -P -R -S standby1
B2.  pg_ctl promote -D /var/lib/postgresql/16/main
B3.  pg_rewind --target-pgdata=/var/lib/postgresql/16/main --source-server='host=10.0.1.6 user=repl'
```

```sql
B4.  SELECT pg_create_physical_replication_slot('standby1');
B5.  SELECT * FROM pg_stat_replication;
B6.  SELECT pg_is_in_recovery();
B7.  SELECT now() - pg_last_xact_replay_timestamp();
B8.  SELECT slot_name, active FROM pg_replication_slots;
B9.  SELECT pg_drop_replication_slot('standby1');
B10. SELECT pg_promote();
B11. CREATE PUBLICATION pub_orders FOR TABLE orders;
B12. CREATE SUBSCRIPTION sub_orders CONNECTION '…' PUBLICATION pub_orders;
```

<details><summary>Ответ</summary>

**B1.** Клонирует primary в каталог реплики со стримингом WAL, настраивает `standby.signal`,
`primary_conninfo` и слот `standby1`.
**B2.** Промоутит standby в primary.
**B3.** Приводит старый primary в состояние, из которого он может стать репликой нового
лидера, без полного повторного копирования.
**B4.** Создаёт физический слот репликации.
**B5.** Показывает подключённые реплики, их состояние, sync_state и лаги.
**B6.** `t` — кластер в режиме восстановления (реплика/PITR), `f` — обычный primary.
**B7.** Лаг применения на реплике во времени.
**B8.** Список слотов и признак, подключён ли к ним кто-то сейчас.
**B9.** Удаляет слот — обязательный шаг после вывода реплики из эксплуатации.
**B10.** Промоут из SQL.
**B11.** Публикация изменений таблицы для логической репликации.
**B12.** Подписка на публикацию: создаёт слот на источнике и начинает копирование.

</details>

Оцени конфигурации:

```text:no-line-numbers
B13. synchronous_standby_names = 'standby1'     # одна реплика, синхронная
B14. hot_standby_feedback = on                  # на аналитической реплике с часовыми запросами
B15. wal_keep_size = 0                          # и слотов тоже нет
```

<details><summary>Ответ</summary>

**B13.** Одна синхронная реплика — единая точка отказа записи. Нужно `ANY 1 (s1, s2)`.
**B14.** На аналитической реплике с часовыми запросами это гарантированный bloat на primary.
Лучше `max_standby_streaming_delay` побольше или отдельная реплика/ETL.
**B15.** Ни `wal_keep_size`, ни слотов: при любой заминке реплика отвалится навсегда
и потребует пересоздания.

</details>

---

### Блок C. Практика

#### C1. 🔑 Поднять реплику руками
1. На primary: роль `repl`, `wal_level=replica`, `max_wal_senders`, строка `replication`
   в `pg_hba.conf`, слот.
2. На standby: `pg_basebackup … -R -S standby1`, запуск.
3. Проверь `pg_stat_replication` на primary и `pg_is_in_recovery()` на standby.
4. Вставь строку на primary — убедись, что она появилась на standby.

#### C2. Реплика только на чтение
Попробуй выполнить `INSERT` на standby. Запиши точный текст ошибки.

<details><summary>Ответ</summary>

`ERROR: cannot execute INSERT in a read-only transaction`.

</details>

#### C3. Измеряем лаг
1. Запусти на primary цикл вставок (`pgbench -c 4 -T 120`).
2. Смотри лаг в байтах (primary) и в секундах (standby) каждые 2 секунды (`\watch 2`).
3. Приостанови применение WAL: `SELECT pg_wal_replay_pause();` — посмотри, как растёт лаг.
4. Возобнови: `SELECT pg_wal_replay_resume();`

<details><summary>Ответ</summary>

При `pg_wal_replay_pause()` лаг растёт линейно, `pg_stat_replication` показывает
рост `replay_lag`, при этом `sent_lsn` продолжает двигаться — данные доезжают, но не применяются.

</details>

#### C4. Слот и переполнение диска
1. Останови standby, но слот не удаляй.
2. Погоняй запись на primary и смотри размер `pg_wal` и `pg_replication_slots`.
3. Поставь `max_slot_wal_keep_size = 64MB`, повтори — что произойдёт со слотом?
4. Верни реплику в строй.

<details><summary>Ответ</summary>

Со слотом `pg_wal` растёт неограниченно; с `max_slot_wal_keep_size` слот переходит
в состояние `lost` (в `pg_replication_slots` видно `wal_status = lost`), реплику
придётся пересоздать, но primary остаётся жив.

</details>

#### C5. Реплика без слота
Подними вторую реплику **без** слота, останови её на время, сгенерируй много WAL
на primary, затем запусти. Добейся ошибки
`requested WAL segment has already been removed` и объясни её.

<details><summary>Ответ</summary>

Без слота primary удалил сегменты после checkpoint; реплика требует уже
отсутствующий сегмент. Лечение — пересоздать реплику (или восстановить сегмент из архива
WAL, если он настроен).

</details>

#### C6. Синхронная репликация
1. Включи `synchronous_standby_names = 'standby1'`, reload.
2. Проверь `sync_state` в `pg_stat_replication`.
3. Останови standby и попробуй сделать `INSERT` на primary — что происходит?
4. Верни реплику. Затем настрой `ANY 1 (standby1, standby2)` и повтори эксперимент.

<details><summary>Ответ</summary>

При остановленной синхронной реплике `INSERT` на primary «зависает» в ожидании
подтверждения. С `ANY 1 (s1, s2)` достаточно любой из двух — запись продолжается.

</details>

#### C7. Конфликт восстановления
1. На standby запусти долгий `SELECT` по большой таблице.
2. На primary сделай массовый `UPDATE` + `VACUUM`.
3. Поймай `ERROR: canceling statement due to conflict with recovery`.
4. Подбери `max_standby_streaming_delay` и/или `hot_standby_feedback`, сравни эффекты.

<details><summary>Ответ</summary>

`hot_standby_feedback = on` убирает конфликты, но создаёт bloat;
`max_standby_streaming_delay` даёт запросу время ценой лага. Компромисс выбирается
по характеру нагрузки.

</details>

#### C8. 🔑 Promote и возврат
1. Сделай `pg_promote()` на standby, убедись, что он принимает запись.
2. Останови старый primary, верни его в строй как реплику через `pg_rewind`
   (или `pg_basebackup`).
3. Запиши последовательность как рунбук переключения.

<details><summary>Ответ</summary>

Рунбук должен включать: проверку лага перед переключением, остановку записи,
promote, переключение приложения (HAProxy/DNS/строка подключения), проверку,
возврат старого узла через `pg_rewind`, удаление лишних слотов.

</details>

#### C9. Логическая репликация
1. Переведи источник в `wal_level = logical`.
2. Создай публикацию на таблицу, на втором кластере создай такую же таблицу и подписку.
3. Проверь перенос данных, затем сделай `ALTER TABLE` на источнике — что произошло с подпиской?

<details><summary>Ответ</summary>

`ALTER TABLE` на источнике не приедет на подписчика: схему нужно менять на обеих
сторонах, иначе подписка начнёт падать при несовпадении структуры.

</details>

#### C10. Patroni (со звёздочкой)
Подними docker-compose с etcd + 2-3 Patroni-узлами + HAProxy.
Сделай `patronictl list`, `patronictl switchover`, убей лидера
и посмотри, за сколько произойдёт автоматический failover.

<details><summary>Ответ</summary>

`patronictl switchover` выполняет плановое переключение с минимальным простоем;
при убийстве лидера failover обычно занимает несколько секунд — зависит от TTL и
интервалов проверки.

</details>

---

### Блок D. Инциденты

**D1.** `pg_wal` на primary вырос на 300 ГБ за ночь. Первая гипотеза и как проверить?

<details><summary>Ответ</summary>

Первая гипотеза — неактивный слот репликации (мертвая реплика).
Проверить `pg_replication_slots` (`active=false`, `wal_status`), затем
`pg_stat_archiver.failed_count` (сломанная архивация) и `wal_keep_size`.

</details>

**D2.** Реплика отстала на 4 часа. Как найти причину? Перечисли 5 проверок.

<details><summary>Ответ</summary>

Лаг в байтах/секундах, нагрузка записи на primary, дисковый IO и CPU на реплике,
конфликты восстановления и паузы применения (`pg_is_wal_replay_paused`), сеть между
узлами, наличие долгих запросов на реплике.

</details>

**D3.** После падения сети реплика не может догнать primary:
`requested WAL segment has already been removed`. Что делать сейчас и как предотвратить?

<details><summary>Ответ</summary>

Сейчас: пересоздать реплику (`pg_basebackup`) либо восстановить недостающие
сегменты из архива WAL через `restore_command`. Предотвращение: слот репликации
(+ `max_slot_wal_keep_size`), архивация WAL, мониторинг лага.

</details>

**D4.** На аналитической реплике запросы падают с `canceling statement due to conflict
with recovery`. Варианты решения и их цена.

<details><summary>Ответ</summary>

Увеличить `max_standby_streaming_delay` (растёт лаг), включить
`hot_standby_feedback` (растёт bloat на primary), вынести тяжёлую аналитику на отдельную
реплику или в ClickHouse/ETL — самое здоровое решение.

</details>

**D5.** После включения `hot_standby_feedback = on` на primary вырос bloat и autovacuum
«не работает». Объясни связь.

<details><summary>Ответ</summary>

Реплика сообщает, какие старые версии строк ей нужны; primary их не удаляет.
Пока идёт долгий запрос на реплике, vacuum на primary не может очистить мёртвые строки —
растёт bloat.

</details>

**D6.** Primary упал, сделали promote реплики. Через час подняли старый сервер,
и он тоже принимает запись. Что произошло и что делать?

<details><summary>Ответ</summary>

Split-brain: две базы принимают запись. Нужно немедленно вывести старый сервер
из-под трафика, определить, какие данные разошлись, старый сервер вернуть только через
`pg_rewind`/пересоздание. Предотвращение — фенсинг и автоматика (Patroni).

</details>

**D7.** Приложение после записи сразу читает с реплики и «не видит» свои данные. Причина и решения.

<details><summary>Ответ</summary>

Асинхронная репликация: реплика отстаёт. Решения — критичное чтение направлять
на primary (`target_session_attrs=read-write`), read-your-writes на уровне приложения,
`synchronous_commit = remote_apply` для критичных транзакций (ценой задержки).

</details>

**D8.** Синхронная репликация настроена на одну реплику; реплика ушла на обслуживание —
прод встал. Как правильно было настроить?

<details><summary>Ответ</summary>

`synchronous_standby_names = 'ANY 1 (s1, s2)'` с двумя и более кандидатами,
чтобы обслуживание одной реплики не останавливало запись.

</details>

**D9.** Реплика на другой мажорной версии не стартует. Почему и какие есть варианты?

<details><summary>Ответ</summary>

Физическая репликация требует идентичной мажорной версии (формат данных).
Варианты: одинаковые версии, либо логическая репликация для переезда между версиями.

</details>

**D10.** Нужно обновить PostgreSQL с 14 до 16 с простоем не больше 5 минут. Предложи схему.

<details><summary>Ответ</summary>

Логическая репликация: поднять PG 16, создать подписку на PG 14, дождаться
синхронизации, в короткое окно остановить запись, дождаться нулевого лага, перенести
последовательности, переключить приложение. Простой — минуты.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Какие виды репликации есть в PostgreSQL?

<details><summary>Ответ</summary>

Физическая потоковая (streaming) и логическая; плюс каскадная, отложенная (`recovery_min_apply_delay`).

</details>

**2.** Как поднять потоковую реплику?

<details><summary>Ответ</summary>

Роль с REPLICATION, правило в `pg_hba.conf`, `wal_level=replica`, `pg_basebackup -R -S`,
запуск реплики, проверка `pg_stat_replication`.

</details>

**3.** Что такое слот репликации и чем он опасен?

<details><summary>Ответ</summary>

Слот удерживает WAL, пока реплика его не заберёт; опасен неограниченным ростом `pg_wal`
при мёртвой реплике — лечится мониторингом и `max_slot_wal_keep_size`.

</details>

**4.** Чем синхронная репликация отличается от асинхронной?

<details><summary>Ответ</summary>

Синхронная ждёт подтверждения реплики (нет потерь, выше задержка, риск остановки
записи), асинхронная — нет.

</details>

**5.** Как измерить отставание реплики?

<details><summary>Ответ</summary>

`pg_stat_replication` (байты, `replay_lag`) на primary; `now() - pg_last_xact_replay_timestamp()` на standby.

</details>

**6.** Что такое split-brain и как его избежать?

<details><summary>Ответ</summary>

Две ноды пишут одновременно; избегается кворумом, фенсингом и обязательным `pg_rewind`.

</details>

**7.** Как сделать автоматический failover?

<details><summary>Ответ</summary>

Patroni + etcd + HAProxy (или оператор в k8s); вручную в проде не делают.

</details>

**8.** Можно ли читать с реплики и какие есть подводные камни?

<details><summary>Ответ</summary>

Можно, но есть лаг (eventual consistency) и конфликты восстановления;
критичное чтение оставляют на primary.

</details>

**9.** Чем логическая репликация отличается от физической и где применяется?

<details><summary>Ответ</summary>

Логическая передаёт изменения строк выборочно и между версиями, не реплицирует DDL;
применяется для апгрейдов, CDC и интеграций.

</details>

**10.** Реплика заменяет бэкап?

<details><summary>Ответ</summary>

Нет: ошибочные операции реплицируются. Нужны и реплика, и бэкап.

</details>

---

### 🎯 Чек-лист

- [ ] Поднял потоковую реплику руками и проверил `pg_stat_replication`
- [ ] Знаю, что реплика read-only, и видел текст ошибки при записи
- [ ] Умею измерять лаг в байтах и секундах
- [ ] ⭐ Понимаю пользу и опасность слотов, знаю про `max_slot_wal_keep_size`
- [ ] Пробовал синхронную репликацию и видел, что бывает при падении реплики
- [ ] Ловил конфликт восстановления и знаю три способа с ним работать
- [ ] Делал promote и возвращал старый primary через `pg_rewind`
- [ ] Понимаю split-brain и как его предотвращают
- [ ] Пробовал логическую репликацию и знаю её ограничения
- [ ] Видел, как работает Patroni + etcd + HAProxy
