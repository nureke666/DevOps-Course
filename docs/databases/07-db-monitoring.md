---
title: "07. Мониторинг баз данных"
description: "pg_stat_*, pg_stat_statements, postgres_exporter/Prometheus/Grafana, алерты, алгоритм разбора «база тормозит»"
---

# 07. Мониторинг баз данных

> Роадмап → Базы → PostgreSQL → *«Мониторинг баз»*.
>
> **После темы ты умеешь:** снять метрики PostgreSQL через postgres_exporter, собрать
> дашборд, настроить осмысленные алерты и быстро понять по метрикам, что именно болит.

---

## 🗺️ Что вообще смотрят у базы

```text:no-line-numbers
 ┌──────────────────┬──────────────────────────────────────────────────┐
 │ ДОСТУПНОСТЬ      │ база жива? принимает соединения? это primary?     │
 ├──────────────────┼──────────────────────────────────────────────────┤
 │ РЕСУРСЫ ХОСТА    │ диск (⭐ №1), CPU, RAM, IO — node_exporter        │
 ├──────────────────┼──────────────────────────────────────────────────┤
 │ СОЕДИНЕНИЯ       │ сколько, в каких состояниях, близко ли к лимиту    │
 ├──────────────────┼──────────────────────────────────────────────────┤
 │ ЗАПРОСЫ          │ долгие, tps, ошибки, блокировки, deadlocks       │
 ├──────────────────┼──────────────────────────────────────────────────┤
 │ ВНУТРЕННЕЕ       │ cache hit, autovacuum, bloat, temp files, WAL      │
 ├──────────────────┼──────────────────────────────────────────────────┤
 │ РЕПЛИКАЦИЯ       │ лаг, состояние слотов, число wal_senders           │
 ├──────────────────┼──────────────────────────────────────────────────┤
 │ БЭКАПЫ           │ возраст последнего, ошибки архивации WAL           │
 └──────────────────┴──────────────────────────────────────────────────┘
```

Логика та же, что в общем мониторинге:
**симптомы** (пользователю плохо: медленно, ошибки) алертят, **причины**
(cache hit, bloat) смотрят на дашборде при разборе.

---

## 1. Встроенная статистика: `pg_stat_*`

PostgreSQL сам собирает статистику — экспортер просто вытаскивает её наружу.

| Представление | Что показывает | Когда открываешь |
|---------------|----------------|------------------|
| `pg_stat_activity` | Все соединения: состояние, запрос, время старта, ожидания | ⭐ «База тормозит» — сюда первым делом |
| `pg_stat_database` | Коммиты, откаты, попадания в кэш, deadlocks, temp files | Общее здоровье базы |
| `pg_stat_user_tables` | Живые/мёртвые строки, seq/idx сканы, последний autovacuum | Bloat, отсутствие индексов |
| `pg_stat_user_indexes` | Использование индексов | Поиск бесполезных индексов |
| `pg_stat_replication` | Реплики и их лаг (на primary) | Репликация |
| `pg_replication_slots` | Слоты и удержанный WAL | Рост `pg_wal` |
| `pg_stat_archiver` | Архивация WAL | Бэкапы/PITR |
| `pg_stat_bgwriter` | Checkpoint'ы: плановые/внеплановые | Настройка WAL |
| `pg_locks` | Блокировки | «Всё висит» |
| `pg_stat_statements` | Топ запросов по времени (расширение) | Оптимизация |

### Рабочие запросы дежурного

```sql
-- 1) Кто что делает прямо сейчас (самое главное)
SELECT pid, usename, state, wait_event_type, wait_event,
       now() - xact_start AS xact_age,
       now() - query_start AS query_age,
       left(query, 80) AS query
FROM pg_stat_activity
WHERE state <> 'idle'
ORDER BY xact_age DESC NULLS LAST;

-- 2) Соединения по состояниям
SELECT state, count(*) FROM pg_stat_activity GROUP BY state;

-- 3) Долгие транзакции (кандидаты на убийство)
SELECT pid, now() - xact_start AS age, state, left(query,60)
FROM pg_stat_activity
WHERE state = 'idle in transaction' AND now() - xact_start > interval '5 min';

-- 4) Кто кого блокирует
SELECT blocked.pid AS blocked_pid, blocked.query AS blocked_query,
       blocking.pid AS blocking_pid, blocking.query AS blocking_query
FROM pg_stat_activity blocked
JOIN pg_stat_activity blocking ON blocking.pid = ANY(pg_blocking_pids(blocked.pid))
WHERE cardinality(pg_blocking_pids(blocked.pid)) > 0;

-- 5) Попадание в кэш (норма для OLTP > 0.99)
SELECT datname,
       round(blks_hit::numeric / nullif(blks_hit + blks_read, 0), 4) AS cache_hit_ratio
FROM pg_stat_database WHERE datname = current_database();

-- 6) Мёртвые строки
SELECT relname, n_live_tup, n_dead_tup,
       round(n_dead_tup::numeric / nullif(n_live_tup,0), 3) AS dead_ratio,
       last_autovacuum
FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 10;

-- 7) Таблицы, которые читаются полным перебором
SELECT relname, seq_scan, seq_tup_read, idx_scan
FROM pg_stat_user_tables WHERE seq_scan > idx_scan ORDER BY seq_tup_read DESC LIMIT 10;

-- 8) Неиспользуемые индексы (кандидаты на удаление)
SELECT relname, indexrelname, idx_scan, pg_size_pretty(pg_relation_size(indexrelid))
FROM pg_stat_user_indexes WHERE idx_scan = 0 ORDER BY pg_relation_size(indexrelid) DESC;
```

Аккуратное снятие зависшего:
```sql
SELECT pg_cancel_backend(pid);      -- мягко: отменить запрос
SELECT pg_terminate_backend(pid);   -- жёстко: убить соединение
```

---

## 2. `pg_stat_statements` — топ тяжёлых запросов

```text:no-line-numbers
shared_preload_libraries = 'pg_stat_statements'   # рестарт
pg_stat_statements.max = 10000
pg_stat_statements.track = top
```
```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

SELECT round(total_exec_time::numeric) AS total_ms,
       calls,
       round(mean_exec_time::numeric, 2) AS mean_ms,
       round(100 * total_exec_time / sum(total_exec_time) OVER (), 1) AS pct,
       left(query, 90) AS query
FROM pg_stat_statements
ORDER BY total_exec_time DESC LIMIT 10;

SELECT pg_stat_statements_reset();   -- обнулить перед экспериментом
```

> 💡 Правильный порядок оптимизации: сначала запрос с максимальным **суммарным** временем
> (`calls × mean`), а не самый медленный единичный. Запрос на 20 мс, вызываемый 50 000 раз
> в минуту, вреднее отчёта на 8 секунд раз в час.

---

## 3. postgres_exporter → Prometheus

```yaml
# docker-compose.yml (фрагмент)
services:
  postgres-exporter:
    image: quay.io/prometheuscommunity/postgres-exporter:latest
    environment:
      DATA_SOURCE_NAME: "postgresql://pgmon:pass@db:5432/postgres?sslmode=disable"
    ports: ["9187:9187"]
```
```sql
-- отдельная роль для мониторинга: минимум прав
CREATE ROLE pgmon LOGIN PASSWORD 'pass';
GRANT pg_monitor TO pgmon;          -- ⭐ встроенная роль (PG10+): читать всю статистику
```
```yaml
# prometheus.yml
scrape_configs:
  - job_name: postgres
    static_configs:
      - targets: ['postgres-exporter:9187']
```

### Метрики, которые реально используешь

| Метрика | Смысл |
|---------|-------|
| `pg_up` | Экспортер достучался до базы |
| `pg_settings_max_connections` | Лимит соединений |
| `pg_stat_activity_count{state=...}` | Соединения по состояниям |
| `pg_stat_database_xact_commit/rollback` | TPS и доля откатов |
| `pg_stat_database_blks_hit/blks_read` | Cache hit ratio |
| `pg_stat_database_deadlocks` | Взаимные блокировки |
| `pg_stat_database_temp_bytes` | Временные файлы (мал `work_mem`) |
| `pg_database_size_bytes` | Размер базы |
| `pg_stat_replication_*_lag` | Лаг репликации |
| `pg_replication_slots_*` | Состояние слотов |
| `pg_stat_bgwriter_checkpoints_req/timed` | Внеплановые checkpoint |
| `pg_stat_user_tables_n_dead_tup` | Мёртвые строки |
| `node_filesystem_avail_bytes` | ⭐ Место на диске (из node_exporter) |

Полезные PromQL:
```text:no-line-numbers
# доля использованных соединений
sum(pg_stat_activity_count) / max(pg_settings_max_connections)

# cache hit ratio за 5 минут
rate(pg_stat_database_blks_hit[5m])
  / (rate(pg_stat_database_blks_hit[5m]) + rate(pg_stat_database_blks_read[5m]))

# tps
rate(pg_stat_database_xact_commit[5m]) + rate(pg_stat_database_xact_rollback[5m])

# прогноз заполнения диска за 4 часа
predict_linear(node_filesystem_avail_bytes{mountpoint="/var/lib/postgresql"}[6h], 4*3600) < 0
```

Готовый дашборд Grafana: **9628** (PostgreSQL Database) — импортируется по ID.

---

## 4. Алерты, которые имеют смысл

| Алерт | Условие | Severity | Почему |
|-------|---------|----------|--------|
| База недоступна | `pg_up == 0` 1 мин | critical | Очевидно |
| Мало места | `< 15%` или прогноз на 4 часа | critical | ⭐ Самый частый «убийца» базы |
| Соединения у лимита | `> 85%` от `max_connections` | warning | Скоро откажет в подключении |
| Долгие транзакции | `idle in transaction > 10 мин` | warning | Блокировки и остановка vacuum |
| Лаг репликации | `> 60 с` или `> 1 ГБ` | warning | Реплика бесполезна для failover |
| Неактивный слот | `pg_replication_slots active == 0` | warning | `pg_wal` растёт |
| Архивация WAL | рост `archiver failed_count` | critical | PITR сломан |
| Возраст бэкапа | `> 25 ч` | critical | Бэкапов фактически нет |
| Deadlocks | рост `deadlocks` | warning | Проблема в коде приложения |
| Cache hit | `< 0.95` длительно | info | Мало памяти / плохие запросы |
| Мёртвые строки | `dead_ratio > 0.2` на больших таблицах | info | Autovacuum не справляется |

Пример правила Prometheus:
```yaml
groups:
  - name: postgres
    rules:
      - alert: PostgresDown
        expr: pg_up == 0
        for: 1m
        labels: { severity: critical }
        annotations:
          summary: "PostgreSQL {{ $labels.instance }} недоступен"

      - alert: PostgresTooManyConnections
        expr: sum by (instance) (pg_stat_activity_count)
              / max by (instance) (pg_settings_max_connections) > 0.85
        for: 5m
        labels: { severity: warning }

      - alert: PostgresReplicationLag
        expr: pg_replication_lag_seconds > 60
        for: 5m
        labels: { severity: warning }
```

> ⭐ Алерт должен быть **actionable**: у дежурного должен быть ответ «что делать».
> Алерт «cache hit 94%» в 3 ночи не имеет действия — ему место на дашборде, а не в пейджере.

---

## 5. Логи как источник метрик

```text:no-line-numbers
log_min_duration_statement = 1000     # медленные запросы
log_lock_waits = on                   # кто кого блокировал
log_temp_files = 0                    # сортировки на диск
log_checkpoints = on                  # всплески записи
log_autovacuum_min_duration = 0       # работа autovacuum
```
Разбор логов — `pgBadger` (HTML-отчёт по логам: топ запросов, ошибки, checkpoint'ы)
или отправка логов в Loki/ELK — см. раздел логирования.

---

## 6. Алгоритм разбора «база тормозит»

```text:no-line-numbers
1. Доступна ли база и есть ли место на диске?           df -h / pg_up
        │ нет → чиним место/сервис
        ▼
2. Сколько соединений и в каких состояниях?              pg_stat_activity
        │ упёрлись в лимит → пул, закрыть зависшие
        ▼
3. Есть ли долгие транзакции / idle in transaction?      xact_age
        │ да → pg_cancel_backend / pg_terminate_backend, таймауты
        ▼
4. Есть ли блокировки?                                   pg_blocking_pids
        │ да → найти корневого блокирующего
        ▼
5. Что грузит базу?                                      pg_stat_statements
        │ тяжёлый запрос → EXPLAIN, индексы, вместе с разработчиком
        ▼
6. Ресурсы хоста: CPU/IO/RAM, своп?                      node_exporter
        │ IO в потолке → диски, checkpoint, work_mem
        ▼
7. Внутреннее: cache hit, temp files, autovacuum, bloat, лаг репликации
```

---

## 💼 Как это в DevOps

- Стандартный стек: **postgres_exporter + node_exporter → Prometheus → Grafana
  + Alertmanager**, дашборд 9628 как база, свои панели сверху.
- Роль для мониторинга — отдельная, с `pg_monitor`, без доступа к данным.
- На каждый прод-кластер: дашборд + набор алертов + рунбук на каждый алерт
  («что делать, если сработал»).
- Мониторинг ставят **до** того, как появится нагрузка. Иначе первый же инцидент
  разбирают вслепую и по рассказам пользователей.
- Метрики базы смотрят вместе с метриками приложения: рост времени ответа приложения
  и рост соединений к базе — обычно одна и та же история.
- Managed-базы в облаке дают метрики сами, но список того, на что смотреть, тот же.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Кто что делает сейчас | `SELECT * FROM pg_stat_activity WHERE state<>'idle';` |
| Соединения по состояниям | `SELECT state, count(*) FROM pg_stat_activity GROUP BY state;` |
| Долгие транзакции | `now() - xact_start > interval '5 min'` |
| Кто кого блокирует | `pg_blocking_pids(pid)` |
| Отменить запрос / убить сессию | `pg_cancel_backend(pid)` / `pg_terminate_backend(pid)` |
| Попадание в кэш | `blks_hit / (blks_hit + blks_read)` из `pg_stat_database` |
| Мёртвые строки | `pg_stat_user_tables.n_dead_tup` |
| Неиспользуемые индексы | `pg_stat_user_indexes` где `idx_scan = 0` |
| Топ тяжёлых запросов | `pg_stat_statements` по `total_exec_time` |
| Лаг репликации | `pg_stat_replication` / `pg_last_xact_replay_timestamp()` |
| Состояние слотов | `pg_replication_slots` |
| Архивация WAL | `pg_stat_archiver` |
| Checkpoint'ы | `pg_stat_bgwriter` |
| Размер базы/таблиц | `pg_database_size()`, `pg_total_relation_size()` |
| Экспортер метрик | postgres_exporter, роль с `pg_monitor` |
| Дашборд | Grafana ID **9628** |
| Отчёт по логам | `pgbadger postgresql.log -o report.html` |

---

## 🧠 Что запомнить

1. PostgreSQL сам собирает статистику в `pg_stat_*`; экспортер только отдаёт её наружу.
2. ⭐ `pg_stat_activity` — первое место, куда смотрят при «база тормозит».
3. Алерт №1 по базе — свободное место на диске (и прогноз заполнения).
4. `pg_stat_statements` показывает, кто съедает время суммарно, — оптимизируют по нему.
5. Для мониторинга заводят отдельную роль с `pg_monitor`, а не суперпользователя.
6. Алертить нужно симптомы и то, по чему есть действие; остальное — на дашборд.
7. Долгие транзакции, неактивные слоты и сломанная архивация WAL — три вещи,
   которые тихо ломают базу; они должны быть в алертах.
8. Лаг репликации мониторят и в секундах, и в байтах.
9. Логи (`log_min_duration_statement`, `log_lock_waits`, `log_temp_files`) —
   вторая половина мониторинга; pgBadger превращает их в отчёт.
10. Мониторинг настраивается заранее и сопровождается рунбуками на каждый алерт.

---

## Задачи

> Стенд: PostgreSQL + postgres_exporter + Prometheus + Grafana (docker compose).
> Нагрузку удобно делать `pgbench`.

---

### Блок A. Теория

**A1.** Какие семь групп показателей смотрят у базы данных?

<details><summary>Ответ</summary>

Доступность, ресурсы хоста (диск/CPU/RAM/IO), соединения, запросы (долгие, tps,
ошибки, блокировки), внутреннее состояние (cache hit, autovacuum, bloat, temp, WAL),
репликация, бэкапы.

</details>

**A2.** ⭐ Какое представление открываешь первым при жалобе «база тормозит» и почему?

<details><summary>Ответ</summary>

`pg_stat_activity`: показывает, кто подключён, что выполняет, сколько длится
транзакция и чего ждёт. Большая часть инцидентов видна именно здесь.

</details>

**A3.** Что показывают `pg_stat_database`, `pg_stat_user_tables`, `pg_stat_bgwriter`?

<details><summary>Ответ</summary>

`pg_stat_database` — коммиты/откаты, попадания в кэш, deadlocks, temp-файлы по базам.
`pg_stat_user_tables` — живые/мёртвые строки, seq/idx-сканы, время последнего autovacuum.
`pg_stat_bgwriter` — статистика checkpoint'ов (плановых и по объёму WAL).

</details>

**A4.** Чем `pg_cancel_backend` отличается от `pg_terminate_backend`?

<details><summary>Ответ</summary>

`pg_cancel_backend` отменяет текущий запрос, соединение остаётся живым.
`pg_terminate_backend` разрывает соединение целиком (откатывает транзакцию).
Начинают всегда с мягкого.

</details>

**A5.** Как найти, кто кого блокирует?

<details><summary>Ответ</summary>

`pg_blocking_pids(pid)` возвращает список блокирующих процессов; соединяют
`pg_stat_activity` сам с собой, чтобы увидеть пары «жертва — виновник».

</details>

**A6.** Что такое cache hit ratio, как считается и какое значение считается нормальным?

<details><summary>Ответ</summary>

Доля страниц, прочитанных из общего кэша, а не с диска:
`blks_hit / (blks_hit + blks_read)`. Для OLTP нормой считают > 0.99 (но это индикатор,
а не цель сама по себе).

</details>

**A7.** Зачем нужен `pg_stat_statements` и по какому полю в нём сортируют в первую очередь?

<details><summary>Ответ</summary>

Расширение накапливает статистику по нормализованным запросам: число вызовов,
общее и среднее время. Сортируют в первую очередь по `total_exec_time` — суммарному
вкладу в нагрузку.

</details>

**A8.** Почему запрос на 20 мс может быть важнее запроса на 8 секунд?

<details><summary>Ответ</summary>

Потому что вклад в нагрузку = `calls × mean_time`. Частый лёгкий запрос может
съедать больше ресурсов, чем редкий тяжёлый, и его оптимизация даёт больший эффект.

</details>

**A9.** Что такое роль `pg_monitor` и почему экспортер не должен ходить суперпользователем?

<details><summary>Ответ</summary>

`pg_monitor` — встроенная роль, дающая доступ ко всей статистике и системным
функциям мониторинга без прав на данные. Экспортер с суперпользователем — лишний риск
(утечка кредов = полный доступ к кластеру).

</details>

**A10.** Назови 8 метрик, которые точно должны быть на дашборде PostgreSQL.

<details><summary>Ответ</summary>

Доступность, соединения по состояниям и доля от лимита, TPS и доля откатов,
cache hit, размер базы и свободное место, лаг репликации, мёртвые строки/autovacuum,
temp files, checkpoint'ы, возраст бэкапа.

</details>

**A11.** Какой алерт по базе самый важный и почему?

<details><summary>Ответ</summary>

Свободное место на диске (и прогноз заполнения): переполнение диска
останавливает базу, а иногда мешает ей подняться.

</details>

**A12.** Что значит «алерт должен быть actionable»? Приведи пример плохого алерта.

<details><summary>Ответ</summary>

У дежурного должен быть чёткий следующий шаг. Плохой алерт — «cache hit 94%»
в 3 ночи: непонятно, что делать, и это не симптом для пользователя.

</details>

**A13.** Какие три «тихих» проблемы должны быть в алертах (иначе узнаешь о них поздно)?

<details><summary>Ответ</summary>

Долгие транзакции (`idle in transaction`), неактивные слоты репликации,
сломанная архивация WAL / устаревший бэкап.

</details>

**A14.** Какие параметры логирования дают материал для разбора инцидентов?

<details><summary>Ответ</summary>

`log_min_duration_statement`, `log_lock_waits`, `log_temp_files`,
`log_checkpoints`, `log_autovacuum_min_duration`, `log_connections/disconnections`
и информативный `log_line_prefix`.

</details>

**A15.** Опиши алгоритм разбора «база тормозит» по шагам.

<details><summary>Ответ</summary>

Доступность и диск → соединения → долгие транзакции → блокировки →
топ запросов (`pg_stat_statements`) → ресурсы хоста → внутреннее состояние
(cache hit, temp, autovacuum, лаг репликации).

</details>

---

### Блок B. «Что показывает запрос / метрика»

```sql
B1.  SELECT state, count(*) FROM pg_stat_activity GROUP BY state;
B2.  SELECT pid, now()-xact_start AS age FROM pg_stat_activity
     WHERE state='idle in transaction' ORDER BY age DESC;
B3.  SELECT blks_hit::float/(blks_hit+blks_read) FROM pg_stat_database WHERE datname='shop';
B4.  SELECT relname, n_dead_tup FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 5;
B5.  SELECT relname, indexrelname, idx_scan FROM pg_stat_user_indexes WHERE idx_scan=0;
B6.  SELECT * FROM pg_stat_archiver;
B7.  SELECT slot_name, active FROM pg_replication_slots;
B8.  SELECT checkpoints_timed, checkpoints_req FROM pg_stat_bgwriter;
```

```text:no-line-numbers
B9.  sum(pg_stat_activity_count) / max(pg_settings_max_connections)
B10. rate(pg_stat_database_xact_rollback[5m]) / rate(pg_stat_database_xact_commit[5m])
B11. predict_linear(node_filesystem_avail_bytes{mountpoint="/var/lib/postgresql"}[6h], 4*3600) < 0
B12. rate(pg_stat_database_deadlocks[5m]) > 0
B13. pg_stat_database_temp_bytes
```

<details><summary>Ответ</summary>

**B1.** Распределение соединений по состояниям (`active`, `idle`, `idle in transaction`).
**B2.** Забытые транзакции, отсортированные от самых старых.
**B3.** Cache hit ratio базы `shop`.
**B4.** Топ-5 таблиц по мёртвым строкам — кандидаты на проблемы с autovacuum/bloat.
**B5.** Индексы, которые ни разу не использовались, — кандидаты на удаление.
**B6.** Статистика архивации WAL: успешные/неуспешные, время последнего архивирования.
**B7.** Слоты и признак активности: неактивный слот = риск роста `pg_wal`.
**B8.** Соотношение плановых и внеплановых checkpoint'ов: перевес `req` — мал `max_wal_size`.
**B9.** Доля использованных соединений (для алерта на 85%).
**B10.** Доля откатов к коммитам — рост означает ошибки в приложении.
**B11.** Прогноз: закончится ли место на разделе базы в ближайшие 4 часа.
**B12.** Появление взаимных блокировок.
**B13.** Объём временных файлов — сортировки не помещаются в `work_mem`.

</details>

Оцени алерты — хороший или плохой и почему:
```yaml
B14. alert: CacheHitLow      expr: cache_hit < 0.99            for: 1m    severity: critical
B15. alert: PostgresDown     expr: pg_up == 0                  for: 1m    severity: critical
B16. alert: DiskWillBeFull   expr: predict_linear(...)  < 0    for: 10m   severity: critical
B17. alert: HighCPU          expr: cpu > 80%                   for: 1m    severity: critical
```

<details><summary>Ответ</summary>

**B14.** Плохой: не симптом, нет действия, `critical` и короткий `for` дадут шум ночью.
**B15.** Хороший: чёткий симптом, есть действие, разумный `for`.
**B16.** Хороший: предсказывает проблему заранее, действие очевидно (расширить/почистить).
**B17.** Плохой в таком виде: CPU 80% сам по себе не проблема; нужен симптом
(время ответа, насыщение) и больший `for`.

</details>

---

### Блок C. Практика

#### C1. 🔑 Запросы дежурного
Собери себе файл `dba_checks.sql` с запросами: активность, состояния соединений,
долгие транзакции, блокировки, cache hit, мёртвые строки, размеры, лаг репликации.
Проверь каждый на своей базе.

#### C2. Поймать блокировку
1. Сеанс 1: `BEGIN; UPDATE t SET val=val WHERE id=1;` (не коммитить).
2. Сеанс 2: тот же `UPDATE`.
3. Найди пару «блокирующий — заблокированный» через `pg_blocking_pids`.
4. Сними мягко (`pg_cancel_backend`) и жёстко (`pg_terminate_backend`), сравни поведение.

<details><summary>Ответ</summary>

`pg_cancel_backend` вернёт сеансу 1 ошибку отмены запроса, транзакция останется
открытой; `pg_terminate_backend` закроет соединение и откатит транзакцию.

</details>

#### C3. `pg_stat_statements`
1. Включи расширение, сбрось статистику.
2. `pgbench -i -s 20 shop && pgbench -c 10 -T 60 shop`
3. Выведи топ-5 по `total_exec_time` и топ-5 по `mean_exec_time` — сравни списки
   и объясни разницу.

<details><summary>Ответ</summary>

Списки будут разными: в топе по `total_exec_time` окажутся частые короткие
запросы, в топе по `mean_exec_time` — редкие тяжёлые. Оптимизировать начинают с первого.

</details>

#### C4. Стек мониторинга
Подними docker-compose: postgres + postgres_exporter + prometheus + grafana.
Проверь метрики на `:9187/metrics`, таргет в Prometheus, импортируй дашборд 9628.

#### C5. Роль для мониторинга
Создай `pgmon` с `pg_monitor`, переведи экспортер на неё.
Убедись, что она не может читать данные из таблиц приложения.

<details><summary>Ответ</summary>

`pgmon` увидит статистику, но `SELECT` из таблиц приложения выдаст
`permission denied` — это и требуется.

</details>

#### C6. Свои панели
Добавь в Grafana панели: соединения по состояниям, TPS, cache hit ratio,
размер базы, лаг репликации, мёртвые строки топ-5 таблиц.

#### C7. Алерты
Опиши в `rules.yml` пять алертов: `PostgresDown`, `TooManyConnections`,
`DiskSpaceLow`, `ReplicationLag`, `LongIdleTransaction`. Проверь, что они появились
в Prometheus, и спровоцируй хотя бы два из них.

<details><summary>Ответ</summary>

Проверять правила удобно через `promtool check rules rules.yml` и вкладку
Alerts в Prometheus (состояния pending → firing).

</details>

#### C8. Диск и прогноз
1. Заполни диск стенда до 85% (генерация данных).
2. Посмотри `predict_linear` в Prometheus.
3. Настрой алерт «диск закончится через 4 часа» и убедись, что он сработал.

#### C9. Логи и pgBadger
Включи `log_min_duration_statement=200`, `log_lock_waits`, `log_temp_files=0`.
Погоняй нагрузку, собери отчёт `pgbadger` и найди в нём топ медленных запросов.

<details><summary>Ответ</summary>

В отчёте pgBadger есть разделы Top slowest queries, Most frequent queries,
Locks, Temporary files, Checkpoints — это готовый материал для разговора с разработчиками.

</details>

#### C10. Мини-рунбук
Для каждого из пяти своих алертов напиши рунбук: что проверить, какие команды выполнить,
когда эскалировать. Один алерт = одна страница.

---

### Блок D. Инциденты

**D1.** Алерт: соединения 95% от лимита. Действия сейчас и что делать, чтобы не повторилось.

<details><summary>Ответ</summary>

Сейчас: посмотреть распределение состояний, найти и закрыть зависшие
`idle in transaction`, при необходимости временно расширить лимит.
Дальше: PgBouncer, таймауты, настройка пула в приложении.

</details>

**D2.** Приложение отвечает 5 секунд вместо 200 мс. База «по графикам спокойна».
Как проверишь, что дело всё-таки в базе?

<details><summary>Ответ</summary>

Сопоставить время ответа приложения с временем запросов: `pg_stat_statements`
за период, логи медленных запросов, `pg_stat_activity` во время всплеска, лаг репликации
(если читают с реплики), время подключения (проблема может быть в пуле/сети, а не в базе).

</details>

**D3.** `n_dead_tup` растёт, `last_autovacuum` — три дня назад. Что смотришь?

<details><summary>Ответ</summary>

Долгие транзакции и `idle in transaction`, неактивные слоты репликации,
`hot_standby_feedback` на реплике, prepared transactions, настройки autovacuum
для этой таблицы, загрузку autovacuum-воркеров.

</details>

**D4.** Cache hit ratio упал с 0.99 до 0.80. Возможные причины?

<details><summary>Ответ</summary>

Выросший объём данных (не помещаются в `shared_buffers`), новый тяжёлый запрос
с полным сканом, рестарт базы (кэш холодный), уменьшение `shared_buffers`,
массовая загрузка данных.

</details>

**D5.** Растёт `pg_stat_database_temp_bytes`. Что это значит и что менять?

<details><summary>Ответ</summary>

Сортировки/хеши уходят на диск: мал `work_mem` или запросы обрабатывают слишком
много строк. Поднять `work_mem` точечно и оптимизировать запросы/индексы.

</details>

**D6.** `deadlocks` растут каждый час по расписанию. Кто виноват и что делать девопсу?

<details><summary>Ответ</summary>

Взаимные блокировки — почти всегда логика приложения (разный порядок захвата
строк). Девопс приносит факты: время, участвующие запросы из лога (`log_lock_waits`,
сообщения о deadlock), и работает с разработчиками; со своей стороны — таймауты.

</details>

**D7.** Лаг репликации 0 секунд, но приложение читает старые данные. Что проверишь?

<details><summary>Ответ</summary>

Читает ли приложение вообще с той реплики, кэш на стороне приложения,
`pg_is_wal_replay_paused`, реально ли метрика лага снимается с нужного инстанса,
транзакция с длинным снимком на стороне приложения.

</details>

**D8.** Алерт «мало места» сработал ночью; выяснилось, что растёт `pg_wal`.
Какие три причины проверяешь по порядку?

<details><summary>Ответ</summary>

Неактивный слот репликации → сломанная архивация (`pg_stat_archiver.failed_count`)
→ большие `max_wal_size`/`wal_keep_size` или очень длинная транзакция.
Файлы из `pg_wal` руками не удалять.

</details>

**D9.** Мониторинг показывает `pg_up == 1`, но приложение не может подключиться.
Как такое возможно?

<details><summary>Ответ</summary>

Экспортер ходит локально/по сокету, а приложение — по сети (firewall, `pg_hba.conf`,
`listen_addresses`); либо упёрлись в `max_connections` (экспортер уже подключён);
либо база в recovery и отвергает запись.

</details>

**D10.** Дежурные жалуются, что алертов по базе слишком много и их игнорируют.
Как чинить?

<details><summary>Ответ</summary>

Аудит алертов: убрать неактуальные и не-actionable, повысить пороги и `for`,
сгруппировать в Alertmanager, разделить severity (пейджер только для critical),
к каждому алерту написать рунбук. Шум лечится удалением алертов, а не привыканием.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как ты мониторишь PostgreSQL?

<details><summary>Ответ</summary>

postgres_exporter + node_exporter → Prometheus → Grafana + Alertmanager, дашборд 9628,
логи в Loki/ELK, pgBadger для разбора.

</details>

**2.** Какие метрики базы считаешь ключевыми?

<details><summary>Ответ</summary>

Доступность, место на диске, соединения, TPS и откаты, долгие транзакции и блокировки,
лаг репликации, cache hit, мёртвые строки, состояние бэкапов.

</details>

**3.** Что показывает `pg_stat_activity`?

<details><summary>Ответ</summary>

Текущие соединения: пользователь, база, состояние, время транзакции и запроса,
что ждёт, сам текст запроса.

</details>

**4.** Как найти медленные запросы?

<details><summary>Ответ</summary>

`pg_stat_statements` по `total_exec_time` и `log_min_duration_statement` в логах,
дальше `EXPLAIN (ANALYZE, BUFFERS)`.

</details>

**5.** Как найти, кто заблокировал таблицу?

<details><summary>Ответ</summary>

`pg_blocking_pids` + `pg_stat_activity` (или `pg_locks`); снять `pg_cancel_backend`,
при необходимости `pg_terminate_backend`.

</details>

**6.** Что такое cache hit ratio?

<details><summary>Ответ</summary>

Доля чтений из кэша против чтений с диска; для OLTP ожидают > 0.99.

</details>

**7.** Какие алерты по базе ты бы настроил?

<details><summary>Ответ</summary>

`pg_up`, место на диске и прогноз, соединения у лимита, лаг репликации,
долгие `idle in transaction`, неактивные слоты, ошибки архивации WAL, возраст бэкапа.

</details>

**8.** Как мониторить репликацию и бэкапы?

<details><summary>Ответ</summary>

Репликацию — `pg_stat_replication`/`pg_replication_slots` через экспортер;
бэкапы — метрики инструмента (WAL-G/pgBackRest) плюс `pg_stat_archiver` и алерт
на возраст последнего успешного бэкапа.

</details>

**9.** Что смотришь в первую очередь при «база тормозит»?

<details><summary>Ответ</summary>

Диск и доступность, затем `pg_stat_activity`: соединения, долгие транзакции, блокировки.

</details>

**10.** Какие права нужны пользователю мониторинга?

<details><summary>Ответ</summary>

Отдельная роль с `GRANT pg_monitor` — доступ к статистике без доступа к данным.

</details>

---

### 🎯 Чек-лист

- [ ] Есть свой файл запросов дежурного по базе
- [ ] ⭐ Первым делом смотрю `pg_stat_activity` и умею читать его поля
- [ ] Умею найти, кто кого блокирует, и аккуратно снять сессию
- [ ] Пользуюсь `pg_stat_statements` и понимаю, почему сортирую по суммарному времени
- [ ] Поднял postgres_exporter + Prometheus + Grafana и импортировал дашборд
- [ ] Экспортер ходит под ролью с `pg_monitor`, а не суперпользователем
- [ ] Настроил как минимум 5 осмысленных алертов
- [ ] Есть алерт на место на диске с прогнозом
- [ ] Мониторю лаг репликации, слоты и возраст бэкапа
- [ ] К каждому алерту написан рунбук
