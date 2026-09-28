---
title: "08. Базовый SQL для DevOps"
description: "SELECT/INSERT/GRANT/EXPLAIN, безопасный UPDATE на проде, батчевые удаления, типичные грабли SQL"
---

# 08. Базовый SQL для DevOps

> Роадмап → Базы → PostgreSQL → *«Базовый SQL (`SELECT`, `INSERT`, `CREATE TABLE`, `GRANT`)»*.
>
> **После темы ты умеешь:** зайти в базу и посмотреть данные, создать таблицу и роль,
> выдать права, прочитать план запроса и не сломать прод одной командой.

---

## 🗺️ Сколько SQL нужно девопсу

```text:no-line-numbers
     Разработчик                         DevOps
 ┌────────────────────┐        ┌──────────────────────────────┐
 │ сложные JOIN'ы     │        │ SELECT с WHERE и count(*)    │
 │ оконные функции    │        │ CREATE TABLE / CREATE ROLE   │
 │ CTE, рекурсия      │        │ GRANT / REVOKE               │
 │ оптимизация ORM    │        │ EXPLAIN (понять, есть индекс)│
 │ бизнес-логика      │        │ системные вьюхи pg_stat_*    │
 └────────────────────┘        │ BEGIN/COMMIT/ROLLBACK ⭐      │
                               └──────────────────────────────┘
```

Цель — не стать аналитиком, а **уметь проверить, посмотреть и не навредить**.

---

## 1. Четыре группы команд

| Группа | Команды | Что делает |
|--------|---------|------------|
| **DDL** (структура) | `CREATE`, `ALTER`, `DROP`, `TRUNCATE` | Меняет схему |
| **DML** (данные) | `SELECT`, `INSERT`, `UPDATE`, `DELETE` | Работает с данными |
| **DCL** (права) | `GRANT`, `REVOKE` | Выдаёт доступ |
| **TCL** (транзакции) | `BEGIN`, `COMMIT`, `ROLLBACK`, `SAVEPOINT` | Управляет транзакциями |

> ⭐ В PostgreSQL **DDL транзакционен**: `CREATE TABLE`/`ALTER TABLE` можно откатить
> внутри `BEGIN … ROLLBACK`. Это спасает при миграциях (в MySQL так нельзя).

---

## 2. `CREATE TABLE` и типы

```sql
CREATE TABLE users (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- современный serial
    email       text        NOT NULL UNIQUE,
    name        text        NOT NULL,
    age         int         CHECK (age >= 0),
    is_active   boolean     NOT NULL DEFAULT true,
    settings    jsonb       NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now()        -- ⭐ timestamptz, не timestamp
);

CREATE TABLE orders (
    id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id   bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount    numeric(12,2) NOT NULL,                     -- ⭐ деньги — numeric, не float
    status    text NOT NULL DEFAULT 'new',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_orders_user_id ON orders(user_id);
```

| Тип | Когда |
|-----|-------|
| `bigint` / `int` | Числа, идентификаторы |
| `numeric(p,s)` | Деньги и всё, где недопустима погрешность |
| `real`/`double precision` | Научные вычисления (не деньги!) |
| `text` | Строки (в PostgreSQL `varchar(n)` не быстрее) |
| `boolean` | Флаги |
| `timestamptz` | Время с зоной — почти всегда правильный выбор |
| `date`, `interval` | Даты и промежутки |
| `jsonb` | Слабоструктурированные данные, есть индексы GIN |
| `uuid` | Идентификаторы в распределённых системах |
| `inet`, `cidr` | IP-адреса и подсети (пригодится девопсу) |

Изменение структуры:
```sql
ALTER TABLE users ADD COLUMN phone text;
ALTER TABLE users ALTER COLUMN phone SET NOT NULL;     -- ⚠️ блокировка + проверка всех строк
ALTER TABLE users RENAME COLUMN name TO full_name;
ALTER TABLE users DROP COLUMN phone;
DROP TABLE orders;                                      -- ⚠️ без вопросов
TRUNCATE orders;                                        -- быстро очистить (с освобождением места)
TRUNCATE orders RESTART IDENTITY CASCADE;
```

---

## 3. `SELECT` — 90% того, что ты будешь писать

```sql
SELECT * FROM users LIMIT 10;                         -- ⭐ LIMIT на незнакомой таблице
SELECT id, email FROM users WHERE is_active = true ORDER BY created_at DESC LIMIT 20;

SELECT count(*) FROM orders;                          -- сколько всего
SELECT status, count(*) FROM orders GROUP BY status;  -- разбивка
SELECT status, count(*) FROM orders GROUP BY status HAVING count(*) > 100;

-- условия
WHERE created_at >= now() - interval '1 day'
WHERE email LIKE '%@example.com'
WHERE email ILIKE '%@EXAMPLE.com'      -- регистронезависимо
WHERE status IN ('new','paid')
WHERE amount BETWEEN 100 AND 500
WHERE phone IS NULL                    -- ⭐ NULL сравнивают только через IS
WHERE settings->>'theme' = 'dark'      -- jsonb

-- агрегаты
SELECT sum(amount), avg(amount), min(amount), max(amount) FROM orders;
SELECT date_trunc('hour', created_at) AS h, count(*)
FROM orders WHERE created_at > now() - interval '24 hours'
GROUP BY h ORDER BY h;
```

### JOIN — на пальцах

```text:no-line-numbers
users                orders
 id  name            id  user_id  amount
 1   Иван            10  1        500
 2   Пётр            11  1        300
 3   Анна            12  2        700

INNER JOIN  → только те, у кого есть заказы          (Иван, Иван, Пётр)
LEFT  JOIN  → все пользователи, заказы если есть      (+ Анна с NULL)
```
```sql
SELECT u.name, o.amount
FROM users u
JOIN orders o ON o.user_id = u.id
WHERE o.created_at > now() - interval '7 days';

-- пользователи без заказов
SELECT u.name FROM users u
LEFT JOIN orders o ON o.user_id = u.id
WHERE o.id IS NULL;
```

---

## 4. `INSERT` / `UPDATE` / `DELETE` — и как не сломать прод

```sql
INSERT INTO users (email, name) VALUES ('a@b.c', 'Иван');
INSERT INTO users (email, name) VALUES ('a@b.c','Иван'), ('d@e.f','Пётр');   -- пачкой
INSERT INTO users (email, name) VALUES ('a@b.c','Иван')
  ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name;                     -- upsert
INSERT INTO users (email, name) VALUES (...) RETURNING id;                    -- вернуть id

UPDATE orders SET status = 'paid' WHERE id = 42;
DELETE FROM orders WHERE created_at < now() - interval '1 year';
```

### ⭐ Правила безопасной работы на проде

```sql
-- 1. Сначала посмотри, что затронешь
SELECT count(*) FROM orders WHERE created_at < now() - interval '1 year';

-- 2. Выполняй в транзакции и проверяй число строк
BEGIN;
UPDATE orders SET status='cancelled' WHERE created_at < '2024-01-01';
-- UPDATE 15234   ← ожидал 15 тысяч? хорошо. Ожидал 100? ROLLBACK!
ROLLBACK;   -- или COMMIT
```
```text:no-line-numbers
Правила, которые экономят карьеру:
1. UPDATE/DELETE без WHERE не пишут никогда.
2. Перед UPDATE — тот же запрос с SELECT count(*).
3. На проде — только BEGIN … проверил … COMMIT.
4. Массовые удаления — батчами (DELETE … WHERE id IN (SELECT id … LIMIT 10000)).
5. Перед любой ручной правкой данных — свежий бэкап (тема 05).
6. Ручные правки данных на проде вообще нежелательны: правильный путь — миграция в CI.
```

Массовое удаление батчами (не раздувает WAL и не держит блокировки часами):
```sql
DO $$
DECLARE deleted int;
BEGIN
  LOOP
    DELETE FROM events WHERE id IN (
      SELECT id FROM events WHERE created_at < now() - interval '1 year' LIMIT 10000
    );
    GET DIAGNOSTICS deleted = ROW_COUNT;
    EXIT WHEN deleted = 0;
    COMMIT;
  END LOOP;
END $$;
```

---

## 5. `GRANT` — права (повтор из темы 03, но с примерами)

```sql
CREATE ROLE app LOGIN PASSWORD 'secret';
GRANT CONNECT ON DATABASE shop TO app;
GRANT USAGE ON SCHEMA public TO app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO readonly;

REVOKE DELETE ON orders FROM app;
\dp orders                                    -- проверить
```

---

## 6. `EXPLAIN` — минимум, который нужен

```sql
EXPLAIN SELECT * FROM orders WHERE user_id = 42;              -- план без выполнения
EXPLAIN ANALYZE SELECT * FROM orders WHERE user_id = 42;      -- ⚠️ реально выполняет!
EXPLAIN (ANALYZE, BUFFERS) SELECT …;                          -- + работа с кэшем
```

```text:no-line-numbers
Seq Scan on orders  (cost=0.00..18584.00 rows=1 width=45) (actual time=0.3..85 rows=3 loops=1)
 │                        │           │       │                    │
 │                        │           │       │                    └ реально строк
 │                        │           │       └ оценка строк планировщиком
 │                        │           └ оценка полной стоимости
 │                        └ стоимость первой строки
 └ ⚠️ полный перебор таблицы — если строк много, нужен индекс
```

| Узел плана | Смысл |
|------------|-------|
| `Seq Scan` | Полный перебор. Для маленьких таблиц нормально, для больших — тревога |
| `Index Scan` | Поиск по индексу ✅ |
| `Index Only Scan` | Данные взяты прямо из индекса — самый быстрый вариант |
| `Bitmap Heap Scan` | Много строк по индексу — тоже нормально |
| `Nested Loop` | Соединение перебором (хорошо на малых объёмах) |
| `Hash Join` / `Merge Join` | Соединение больших наборов |
| `Sort` + `external merge Disk` | ⚠️ Сортировка ушла на диск — мал `work_mem` |

Что смотреть девопсу: есть ли `Seq Scan` по большой таблице, сильно ли расходятся
`rows` оценочные и фактические (устарела статистика → `ANALYZE table;`),
не ушла ли сортировка на диск.

---

## 7. Системные запросы, которые нужны каждый день

```sql
-- размеры
SELECT pg_size_pretty(pg_database_size(current_database()));
SELECT relname, pg_size_pretty(pg_total_relation_size(relid)) AS total
FROM pg_catalog.pg_statio_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 10;

-- версия, время, текущий пользователь и база
SELECT version(), now(), current_user, current_database();

-- список таблиц и их владельцы
SELECT schemaname, tablename, tableowner FROM pg_tables WHERE schemaname='public';

-- активность и блокировки — см. тему 07
SELECT * FROM pg_stat_activity WHERE state <> 'idle';

-- обновить статистику планировщика
ANALYZE orders;
VACUUM (ANALYZE) orders;
```

`psql` для скриптов:
```bash
psql -At -c "SELECT count(*) FROM orders;"                 # голое значение
psql -X -f script.sql -v ON_ERROR_STOP=1                   # без .psqlrc, стоп на ошибке
psql -c "\copy orders TO 'orders.csv' CSV HEADER"          # выгрузка в CSV
psql -c "\copy orders FROM 'orders.csv' CSV HEADER"        # загрузка
```

---

## 8. Грабли

| Грабля | Что происходит | Как правильно |
|--------|----------------|---------------|
| `UPDATE`/`DELETE` без `WHERE` | Изменены все строки | Сначала `SELECT count(*)`, потом транзакция |
| `SELECT *` на большой таблице | Ждёшь минуту, грузишь сеть | Всегда `LIMIT` |
| `= NULL` вместо `IS NULL` | Условие никогда не истинно | `IS NULL` / `IS NOT NULL` |
| `float` для денег | Копейки «теряются» | `numeric` |
| `timestamp` без зоны | Путаница со временем между серверами | `timestamptz` |
| `EXPLAIN ANALYZE` на `UPDATE` | Запрос реально выполняется! | Оборачивай в `BEGIN … ROLLBACK` |
| `DROP TABLE` вместо `TRUNCATE` | Потеряна структура и права | Понимать разницу |
| Ручная правка данных на проде | Нет следа, нет отката | Миграция через CI/CD |
| Забыл `COMMIT` | Блокировки, `idle in transaction` | Проверяй `\conninfo` и состояние |

---

## 💼 Как это в DevOps

- SQL нужен, чтобы **проверить** результат деплоя («миграция прошла? строки появились?»),
  **посмотреть** состояние («сколько записей в очереди?») и **выдать доступ**.
- Любая правка данных на проде оформляется как миграция в репозитории и едет через CI/CD:
  это даёт ревью, историю и повторяемость. Ручной `UPDATE` — исключение с обоснованием.
- Миграции в CI запускают с `ON_ERROR_STOP=1` и внутри транзакции, а перед выкаткой
  проверяют, не блокирует ли миграция таблицу (`ALTER TABLE … SET NOT NULL`,
  `CREATE INDEX` без `CONCURRENTLY`).
- `\copy` — рабочий инструмент для выгрузки данных аналитикам и загрузки тестовых наборов.
- Знание `EXPLAIN` на базовом уровне позволяет говорить с разработчиками предметно:
  «у вас Seq Scan по таблице на 40 млн строк» — это уже разговор по делу.

---

## 📌 Шпаргалка

| Хочу | SQL |
|------|-----|
| Посмотреть данные | `SELECT * FROM t LIMIT 10;` |
| Посчитать | `SELECT count(*) FROM t WHERE …;` |
| Разбивка по группам | `SELECT col, count(*) FROM t GROUP BY col;` |
| За последние сутки | `WHERE created_at > now() - interval '1 day'` |
| Соединить таблицы | `JOIN b ON b.a_id = a.id` |
| Найти без пары | `LEFT JOIN … WHERE b.id IS NULL` |
| Вставить | `INSERT INTO t (a,b) VALUES (1,2);` |
| Вставить или обновить | `INSERT … ON CONFLICT (col) DO UPDATE SET …` |
| Обновить безопасно | `BEGIN; UPDATE …; -- проверил; COMMIT;` |
| Создать таблицу | `CREATE TABLE t (id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, …);` |
| Добавить колонку | `ALTER TABLE t ADD COLUMN c text;` |
| Очистить таблицу | `TRUNCATE t;` |
| Создать индекс в проде | `CREATE INDEX CONCURRENTLY …;` |
| Выдать права | `GRANT SELECT ON ALL TABLES IN SCHEMA public TO role;` |
| Посмотреть план | `EXPLAIN (ANALYZE, BUFFERS) SELECT …;` |
| Обновить статистику | `ANALYZE t;` |
| Размер базы/таблиц | `pg_database_size()`, `pg_total_relation_size()` |
| Выгрузить в CSV | `\copy t TO 'f.csv' CSV HEADER` |
| Значение для скрипта | `psql -At -c "…"` |

---

## 🧠 Что запомнить

1. Девопсу нужен не «сложный SQL», а уверенный `SELECT`, `CREATE`, `GRANT`, `EXPLAIN`
   и умение не навредить.
2. DDL в PostgreSQL транзакционен — миграции можно откатить.
3. ⭐ `UPDATE`/`DELETE` на проде: сначала `SELECT count(*)`, потом `BEGIN … COMMIT`.
4. `NULL` сравнивают через `IS NULL`; деньги хранят в `numeric`; время — в `timestamptz`.
5. Массовые удаления делают батчами, иначе блокировки и раздувание WAL.
6. `EXPLAIN ANALYZE` **выполняет** запрос — для изменяющих команд оборачивай в `ROLLBACK`.
7. `Seq Scan` по большой таблице и расхождение оценки со фактом — главные сигналы в плане.
8. Индексы в проде создают с `CONCURRENTLY`.
9. Права выдаются по трём уровням и не забываются `ALTER DEFAULT PRIVILEGES`.
10. Правки данных на проде — через миграции в CI/CD, а не руками в psql.

---

## Задачи

> Стенд: любая база PostgreSQL. Данные удобно налить `pgbench -i -s 10` или скриптом ниже.

```sql
-- учебные таблицы для блока C
CREATE TABLE users (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email text NOT NULL UNIQUE, name text NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE orders (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  amount numeric(12,2) NOT NULL, status text NOT NULL DEFAULT 'new',
  created_at timestamptz NOT NULL DEFAULT now());
INSERT INTO users (email, name)
SELECT 'user'||g||'@test.local', 'User '||g FROM generate_series(1,1000) g;
INSERT INTO orders (user_id, amount, status, created_at)
SELECT (random()*999)::int+1, (random()*1000)::numeric(12,2),
       (ARRAY['new','paid','cancelled'])[(random()*2)::int+1],
       now() - (random()*60||' days')::interval
FROM generate_series(1,200000);
```

---

### Блок A. Теория

**A1.** Назови четыре группы SQL-команд и по две команды в каждой.

<details><summary>Ответ</summary>

DDL (`CREATE`, `ALTER`), DML (`SELECT`, `INSERT`), DCL (`GRANT`, `REVOKE`),
TCL (`BEGIN`, `COMMIT`).

</details>

**A2.** Что значит «DDL в PostgreSQL транзакционен» и чем это полезно при миграциях?

<details><summary>Ответ</summary>

`CREATE`/`ALTER`/`DROP` можно выполнить внутри транзакции и откатить.
Миграция из нескольких DDL-шагов либо применяется целиком, либо не применяется вовсе —
не остаётся «наполовину применённой» схемы.

</details>

**A3.** Почему деньги хранят в `numeric`, а не в `float`?

<details><summary>Ответ</summary>

`float` — двоичное приближение: 0.1 + 0.2 ≠ 0.3, при суммировании копейки
расходятся. `numeric` хранит десятичные значения точно.

</details>

**A4.** Чем `timestamptz` лучше `timestamp` для распределённой системы?

<details><summary>Ответ</summary>

`timestamptz` хранит момент времени в UTC и приводит его к зоне клиента.
`timestamp` без зоны означает разное время на серверах в разных зонах — источник
трудноуловимых багов.

</details>

**A5.** Почему `WHERE col = NULL` не работает?

<details><summary>Ответ</summary>

`NULL` — не значение, а «неизвестно»; любое сравнение с ним даёт `NULL`,
то есть условие не истинно. Нужны `IS NULL` / `IS NOT NULL`.

</details>

**A6.** Чем `TRUNCATE` отличается от `DELETE` и от `DROP TABLE`?

<details><summary>Ответ</summary>

`DELETE` удаляет строки по условию, создаёт мёртвые версии, пишет много WAL,
место не освобождает. `TRUNCATE` мгновенно очищает таблицу целиком и освобождает файлы
(берёт эксклюзивную блокировку). `DROP TABLE` удаляет саму таблицу вместе со структурой,
индексами и правами.

</details>

**A7.** Что такое upsert и как он пишется в PostgreSQL?

<details><summary>Ответ</summary>

«Вставить или обновить»: `INSERT … ON CONFLICT (col) DO UPDATE SET … `
(или `DO NOTHING`).

</details>

**A8.** ⭐ Опиши порядок безопасного выполнения `UPDATE` на проде.

<details><summary>Ответ</summary>

Посмотреть `SELECT count(*)` по тому же условию → убедиться, что есть свежий
бэкап → `BEGIN` → выполнить `UPDATE` → сверить число затронутых строк с ожиданием →
`COMMIT` (или `ROLLBACK`). В идеале — оформить миграцией и прогнать через CI.

</details>

**A9.** Почему массовые `DELETE` делают батчами?

<details><summary>Ответ</summary>

Один большой `DELETE` держит блокировки, раздувает WAL, создаёт миллионы мёртвых
версий и может не завершиться за разумное время; батчи с коммитами дают предсказуемую
нагрузку и возможность прервать процесс.

</details>

**A10.** Чем `EXPLAIN` отличается от `EXPLAIN ANALYZE` и в чём опасность второго?

<details><summary>Ответ</summary>

`EXPLAIN` только показывает план. `EXPLAIN ANALYZE` реально выполняет запрос —
для `UPDATE`/`DELETE` это означает изменение данных, поэтому его оборачивают
в `BEGIN … ROLLBACK`.

</details>

**A11.** Что означают узлы `Seq Scan`, `Index Scan`, `Index Only Scan`?

<details><summary>Ответ</summary>

`Seq Scan` — последовательный просмотр всей таблицы; `Index Scan` — поиск по
индексу с обращением к таблице; `Index Only Scan` — все нужные колонки взяты из индекса,
обращения к таблице почти нет (самый быстрый вариант).

</details>

**A12.** Что значит большое расхождение между оценочным и фактическим числом строк в плане?

<details><summary>Ответ</summary>

Статистика устарела или условие сложное для оценки. Планировщик выбирает плохой
план. Лечится `ANALYZE`, увеличением `default_statistics_target`, переписыванием запроса.

</details>

**A13.** Чем `INNER JOIN` отличается от `LEFT JOIN`? Как найти записи без пары?

<details><summary>Ответ</summary>

`INNER JOIN` оставляет только совпавшие пары; `LEFT JOIN` сохраняет все строки
левой таблицы, подставляя `NULL`. Записи без пары ищут через
`LEFT JOIN … WHERE right.id IS NULL`.

</details>

**A14.** Какие три уровня прав нужно выдать роли, чтобы она читала таблицы?

<details><summary>Ответ</summary>

`CONNECT` на базу, `USAGE` на схему, `SELECT` на таблицы (плюс
`ALTER DEFAULT PRIVILEGES` для будущих).

</details>

**A15.** Зачем девопсу `\copy` и чем он отличается от `COPY`?

<details><summary>Ответ</summary>

`\copy` — клиентская команда psql: файл читается/пишется **на машине клиента**
и не требует прав суперпользователя. `COPY` — серверная: файл на сервере базы,
нужны особые права. Девопсу `\copy` удобен для выгрузок и загрузок с рабочей машины.

</details>

---

### Блок B. «Что делает / что тут не так»

```sql
B1.  SELECT count(*) FROM orders WHERE created_at > now() - interval '1 day';
B2.  SELECT status, count(*) FROM orders GROUP BY status;
B3.  UPDATE orders SET status = 'paid';
B4.  DELETE FROM users WHERE email LIKE '%test%';
B5.  SELECT * FROM orders;
B6.  SELECT * FROM users WHERE phone = NULL;
B7.  CREATE INDEX idx_orders_created ON orders(created_at);      -- на проде в 19:00
B8.  ALTER TABLE orders ALTER COLUMN status SET NOT NULL;        -- таблица 200 млн строк
B9.  EXPLAIN ANALYZE DELETE FROM orders WHERE id < 100;
B10. BEGIN; UPDATE users SET is_active=false WHERE id=5;          -- и окно psql закрыли
B11. INSERT INTO users (email,name) VALUES ('a@b.c','Иван')
     ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name;
B12. TRUNCATE orders RESTART IDENTITY CASCADE;
B13. GRANT ALL PRIVILEGES ON DATABASE shop TO app;
B14. psql -f migration.sql                                        -- без ON_ERROR_STOP
```

<details><summary>Ответ</summary>

**B1.** Число заказов за сутки — корректный запрос.
**B2.** Разбивка по статусам — корректно.
**B3.** `UPDATE` без `WHERE`: изменит все строки таблицы. Катастрофа.
**B4.** `DELETE` по `LIKE '%test%'` может зацепить лишнее (например, `contest@…`);
плюс каскад удалит связанные заказы. Сначала `SELECT`.
**B5.** Без `LIMIT` по большой таблице — долгий запрос и лишний трафик.
**B6.** Всегда пусто: нужно `IS NULL`.
**B7.** Блокирует запись в таблицу на время построения; в прайм-тайм — инцидент.
Нужно `CONCURRENTLY` и окно.
**B8.** Полная проверка всех строк с блокировкой; на 200 млн строк это долгий простой.
Правильный путь — добавить `CHECK … NOT VALID`, затем `VALIDATE CONSTRAINT`.
**B9.** Реально удалит строки: `EXPLAIN ANALYZE` выполняет запрос. Оборачивать
в `BEGIN … ROLLBACK`.
**B10.** Транзакция осталась открытой (пока сессия жива) — блокировки и `idle in
transaction`; при обрыве сессии транзакция откатится.
**B11.** Корректный upsert.
**B12.** Мгновенно очищает `orders`, сбрасывает счётчик идентификаторов и каскадно
очищает зависимые таблицы — мощная и опасная команда.
**B13.** Даёт права на базу (`CONNECT`, `CREATE`, `TEMP`), но не на таблицы;
при этом разрешает приложению создавать схемы. Обычно не то, что нужно.
**B14.** Без `ON_ERROR_STOP=1` psql продолжит после ошибки и выйдет с кодом 0 —
CI сочтёт сломанную миграцию успешной.

</details>

---

### Блок C. Практика

#### C1. Осмотреться в незнакомой базе
Не зная схемы, выясни: список таблиц и их размеры, число строк в каждой,
владельцев, индексы на самой большой таблице, топ-5 таблиц по размеру.

<details><summary>Ответ</summary>

Полезный набор: `\dt+`, `pg_total_relation_size`, `pg_tables`, `\d таблица`,
`SELECT count(*)`.

</details>

#### C2. `SELECT` на каждый день
Напиши запросы:
1. Заказы за последние 24 часа — количество и сумма.
2. Разбивка заказов по статусам.
3. Топ-10 пользователей по сумме заказов.
4. Пользователи без заказов.
5. Почасовая динамика заказов за сутки (`date_trunc`).

#### C3. 🔑 Безопасный `UPDATE`
1. Посчитай `SELECT count(*)` для будущего условия.
2. Выполни `BEGIN; UPDATE …;` — сравни число затронутых строк с ожиданием.
3. Сделай `ROLLBACK`, проверь, что данные не изменились.
4. Повтори с `COMMIT`.

<details><summary>Ответ</summary>

Число строк в ответе `UPDATE 15234` — главный индикатор: не совпало с ожиданием →
`ROLLBACK`.

</details>

#### C4. Батчевое удаление
Удали заказы старше 30 дней батчами по 10 000 строк. Замерь общее время
и сравни с одним большим `DELETE` (на копии таблицы).

<details><summary>Ответ</summary>

Батчи обычно немного медленнее суммарно, но не блокируют таблицу надолго,
дают ровную нагрузку и возможность остановиться.

</details>

#### C5. `CREATE TABLE` и ограничения
Создай таблицу с `PRIMARY KEY`, `UNIQUE`, `CHECK`, `REFERENCES … ON DELETE CASCADE`,
`DEFAULT now()`. Проверь каждое ограничение, попробовав его нарушить.

#### C6. 🔑 `EXPLAIN`
1. `EXPLAIN ANALYZE SELECT * FROM orders WHERE user_id = 42;` — запиши план и время.
2. Создай индекс `CONCURRENTLY`, повтори. Сравни.
3. Найди запрос, где план показывает `Sort … external merge Disk`, и почини его `work_mem`.
4. Удали статистику актуальности (`ALTER TABLE … SET (autovacuum_enabled=off)` + много
   вставок), посмотри расхождение оценки и факта, почини `ANALYZE`.

<details><summary>Ответ</summary>

После индекса план сменится с `Seq Scan` на `Index Scan`/`Bitmap Heap Scan`;
`external merge Disk` исчезнет после увеличения `work_mem`.

</details>

#### C7. Права
Создай роли `shop_owner`, `shop_app`, `readonly`; выдай права по уровням; проверь
`has_table_privilege` и `\dp`. Убедись, что `readonly` не может `INSERT`,
а `shop_app` не может `DROP`.

#### C8. Транзакции и блокировки
1. В сеансе 1 открой транзакцию с `UPDATE` без коммита.
2. В сеансе 2 попробуй `ALTER TABLE` — посмотри, что происходит.
3. Найди блокировку через `pg_blocking_pids`, сними её.

<details><summary>Ответ</summary>

`ALTER TABLE` ждёт эксклюзивную блокировку и блокирует всех, кто придёт после
него, — классическая «очередь за блокировкой».

</details>

#### C9. `\copy`
Выгрузи заказы за последний месяц в CSV, удали их, загрузи обратно из файла.
Сверь количество строк и суммы.

#### C10. Мини-миграция как в CI
Напиши `migration.sql`, который добавляет колонку, заполняет её и создаёт индекс
`CONCURRENTLY`. Запусти через `psql -X -v ON_ERROR_STOP=1`. Объясни, почему
`CREATE INDEX CONCURRENTLY` нельзя выполнять внутри транзакции.

<details><summary>Ответ</summary>

`CREATE INDEX CONCURRENTLY` не может выполняться внутри транзакционного блока:
он делает несколько проходов и коммитит между ними. В миграциях его выносят отдельным
шагом вне транзакции.

</details>

---

### Блок D. Инциденты

**D1.** Выполнили `UPDATE orders SET status='paid';` без `WHERE`. Что делать по шагам?

<details><summary>Ответ</summary>

Не паниковать и не делать новых изменений. Если транзакция ещё открыта —
`ROLLBACK`. Если закоммичено: зафиксировать время, поднять копию через PITR на момент
до операции, выгрузить корректные значения, обновить прод, сверить. Затем постмортем:
почему был прямой доступ на запись.

</details>

**D2.** Миграция выполняется 40 минут, приложение висит. Как понять, что она блокирует?

<details><summary>Ответ</summary>

`pg_stat_activity` (что выполняется, `wait_event_type = Lock`), `pg_blocking_pids`,
`pg_locks`. Видно, какая команда держит блокировку и кто в очереди.

</details>

**D3.** `psql` показывает `ERROR: current transaction is aborted, commands ignored until
end of transaction block`. Что это значит?

<details><summary>Ответ</summary>

В транзакции произошла ошибка; до `ROLLBACK`/`COMMIT` остальные команды
игнорируются. Нужно завершить транзакцию.

</details>

**D4.** Разработчик жалуется: «запрос был быстрый, стал медленный, код не менялся». Гипотезы?

<details><summary>Ответ</summary>

Вырос объём данных, устарела статистика (`ANALYZE`), пропал/распух индекс,
изменились параметры (`work_mem`, `random_page_cost`), другой план из-за bloat,
конкуренция за ресурсы, чтение переехало на отставшую реплику.

</details>

**D5.** Приложение получает `permission denied for table orders` после ночного релиза. Почему?

<details><summary>Ответ</summary>

Миграция создала новые таблицы под другой ролью, а прав приложению не выдали
(нет `ALTER DEFAULT PRIVILEGES`), либо изменился владелец объектов.

</details>

**D6.** Таблица выросла вдвое после массового `UPDATE`, хотя строк столько же. Причина?

<details><summary>Ответ</summary>

MVCC: `UPDATE` создал новую версию каждой строки, старые ещё не убраны
autovacuum'ом (или удерживаются долгой транзакцией) — это bloat.

</details>

**D7.** `DELETE` по 20 млн строк «висит» два часа и растёт `pg_wal`. Что делать?

<details><summary>Ответ</summary>

Прервать (`pg_cancel_backend`), переписать на батчи, проверить место на диске,
убедиться, что autovacuum справится, при полной очистке рассмотреть
`TRUNCATE`/партиционирование.

</details>

**D8.** Отчёт аналитика положил прод: один `SELECT` съел всю память. Какие меры примешь?

<details><summary>Ответ</summary>

Отдельная роль с `statement_timeout` и ограниченным `work_mem`, чтение только
с реплики, лимиты на соединения, а в идеале — витрина/ClickHouse для аналитики.

</details>

**D9.** После `ALTER TABLE ADD COLUMN … NOT NULL DEFAULT …` на большой таблице сервис лёг.
Почему и как надо было?

<details><summary>Ответ</summary>

В старых версиях PostgreSQL такая операция переписывала всю таблицу под
блокировкой (в современных версиях константный DEFAULT добавляется мгновенно,
но `NOT NULL` на существующие строки всё равно требует проверки). Правильно — добавить
колонку nullable, заполнить батчами, затем поставить ограничение
(`CHECK … NOT VALID` + `VALIDATE`).

</details>

**D10.** Нужно срочно посмотреть данные на проде, но доступа нет. Как правильно
организовать доступ, чтобы это не повторялось?

<details><summary>Ответ</summary>

Read-only роль, доступ через bastion/VPN, временные креды (`VALID UNTIL`),
логирование, а для регулярных задач — витрина или дашборд вместо доступа к проду.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Какие группы SQL-команд ты знаешь?

<details><summary>Ответ</summary>

DDL, DML, DCL, TCL.

</details>

**2.** Чем `DELETE` отличается от `TRUNCATE` и `DROP`?

<details><summary>Ответ</summary>

`DELETE` — по условию, оставляет мёртвые версии; `TRUNCATE` — быстрая полная очистка
с освобождением места; `DROP` — удаление самой таблицы.

</details>

**3.** Как безопасно выполнить `UPDATE` на проде?

<details><summary>Ответ</summary>

Посчитать затрагиваемые строки, убедиться в наличии бэкапа, выполнить в транзакции,
сверить число строк, только потом `COMMIT`; лучше — миграцией через CI.

</details>

**4.** Что такое транзакция и как её откатить?

<details><summary>Ответ</summary>

Набор операций «всё или ничего»; откат — `ROLLBACK` (частичный — `SAVEPOINT`).

</details>

**5.** Как посмотреть план запроса и что в нём важно?

<details><summary>Ответ</summary>

`EXPLAIN (ANALYZE, BUFFERS)`; смотреть тип сканирования, расхождение оценки и факта,
сортировки на диске, самые дорогие узлы.

</details>

**6.** Что такое `Seq Scan` и всегда ли это плохо?

<details><summary>Ответ</summary>

Последовательный просмотр таблицы; для маленьких таблиц это нормально и даже быстрее
индекса, для больших — сигнал о недостающем индексе.

</details>

**7.** Как создать индекс на нагруженной таблице?

<details><summary>Ответ</summary>

`CREATE INDEX CONCURRENTLY`, вне транзакции, в окно с меньшей нагрузкой.

</details>

**8.** Как выдать пользователю доступ только на чтение?

<details><summary>Ответ</summary>

Роль + `CONNECT` + `USAGE` на схему + `SELECT ON ALL TABLES` + `ALTER DEFAULT PRIVILEGES`.

</details>

**9.** Почему деньги нельзя хранить во `float`?

<details><summary>Ответ</summary>

Двоичное представление даёт погрешность округления; используется `numeric`.

</details>

**10.** Как выгрузить данные из таблицы в CSV?

<details><summary>Ответ</summary>

`\copy таблица TO 'file.csv' CSV HEADER` из psql.

</details>

---

### 🎯 Чек-лист

- [ ] Могу осмотреться в незнакомой базе без документации
- [ ] Пишу `SELECT` с `WHERE`, `GROUP BY`, `JOIN` и интервалами времени без гугла
- [ ] ⭐ Делаю `UPDATE`/`DELETE` на проде только через `SELECT count(*)` + транзакцию
- [ ] Умею удалять большие объёмы батчами
- [ ] Создаю таблицы с правильными типами (`numeric`, `timestamptz`, `text`)
- [ ] Читаю `EXPLAIN` и отличаю `Seq Scan` от `Index Scan`
- [ ] Знаю, что `EXPLAIN ANALYZE` выполняет запрос
- [ ] Создаю индексы в проде через `CONCURRENTLY`
- [ ] Выдаю права по трём уровням и не забываю про будущие таблицы
- [ ] Пользуюсь `\copy` и `psql -At` в скриптах
