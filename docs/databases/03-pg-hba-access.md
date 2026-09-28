---
title: "03. Доступ: pg_hba.conf, роли и права"
description: "Аутентификация vs авторизация, формат pg_hba.conf, роли и GRANT по уровням, TLS, разбор ошибок подключения"
---

# 03. Доступ: `pg_hba.conf`, роли и права

> Роадмап → Базы → PostgreSQL → *«`pg_hba.conf` (кто откуда может подключаться)»*.
>
> **После темы ты умеешь:** пустить в базу ровно тех, кого нужно, ровно оттуда, откуда нужно;
> завести роль приложения с минимальными правами; разобрать ошибки подключения.

---

## 🗺️ Идея: три двери, которые нужно пройти

```text:no-line-numbers
  приложение 10.0.1.7
        │
        │ 1. СЕТЬ: firewall/security group + listen_addresses
        ▼         ("до порта 5432 вообще достучались?")
  ┌───────────────────────────────────────────────┐
  │ 2. pg_hba.conf — «кто откуда каким способом»  │  ← host-based authentication
  │    сверху вниз, ДО ПЕРВОГО СОВПАДЕНИЯ ⭐      │
  └───────────────────┬───────────────────────────┘
                      │ аутентификация пройдена (ты тот, кем представился)
                      ▼
  ┌───────────────────────────────────────────────┐
  │ 3. GRANT/роли — «что тебе можно внутри»       │  ← авторизация
  └───────────────────────────────────────────────┘
```

Разница, которую спрашивают на собесе:
**аутентификация** (`pg_hba.conf`) — «пускать ли вообще»,
**авторизация** (`GRANT`) — «что можно делать после входа».

---

## 1. Формат `pg_hba.conf`

```text:no-line-numbers
# TYPE   DATABASE   USER        ADDRESS          METHOD        [OPTIONS]
local    all        postgres                     peer
host     shop       app         10.0.1.0/24      scram-sha-256
hostssl  shop       app         0.0.0.0/0        scram-sha-256
host     replication repl       10.0.1.5/32      scram-sha-256
host     all        all         0.0.0.0/0        reject
```

| Поле | Значения | Комментарий |
|------|----------|-------------|
| TYPE | `local` | Unix-сокет (без сети) |
| | `host` | TCP: и SSL, и без SSL |
| | `hostssl` | Только с TLS ⭐ |
| | `hostnossl` | Только без TLS |
| DATABASE | имя, `all`, `replication`, список | `replication` — отдельная «псевдобаза» для реплик |
| USER | имя роли, `all`, `+группа` | `+` = роль и все члены группы |
| ADDRESS | `10.0.1.0/24`, `::1/128`, `samenet` | Только для `host*` |
| METHOD | см. таблицу ниже | Как проверять |

### Методы аутентификации

| Метод | Что делает | Где применяют |
|-------|-----------|----------------|
| `trust` | Пускает **без пароля** | ⚠️ Только локальный тест-стенд. В проде — никогда |
| `peer` | Имя пользователя ОС = имя роли (только `local`) | `sudo -u postgres psql` |
| `ident` | То же, но по сети через ident-сервер | Практически не используется |
| `scram-sha-256` | Современная парольная аутентификация | ⭐ Стандарт (PG 10+) |
| `md5` | Устаревший хеш пароля | Только для старых клиентов |
| `cert` | Клиентский TLS-сертификат | Строгие требования безопасности |
| `ldap` / `gss` / `pam` | Внешние системы | Корпоративная интеграция |
| `reject` | Явно запретить | Последняя строка «всё остальное — нет» |

### ⭐ Главное правило: порядок строк

Файл читается **сверху вниз**, применяется **первая подходящая строка**, дальше поиск
не продолжается. Если она не подошла по методу — соединение отклоняется, а не «ищется дальше».

```text:no-line-numbers
# ПЛОХО: строка-заглушка сверху перекрывает всё
host  all  all  0.0.0.0/0   trust        ← сработает для всех, дальше никто не смотрит
host  shop app  10.0.1.0/24 scram-sha-256

# ХОРОШО: от частного к общему
host  shop app  10.0.1.0/24 scram-sha-256
host  all  all  0.0.0.0/0   reject
```

### Применение изменений

```bash
sudo -u postgres psql -c "SELECT pg_reload_conf();"   # reload, НЕ restart
sudo -u postgres psql -c "SELECT * FROM pg_hba_file_rules;"   # ⭐ проверка синтаксиса и порядка
```
`pg_hba_file_rules` показывает разобранные правила и колонку `error` — удобно проверить
файл до того, как его применили клиенты.

---

## 2. `listen_addresses` — про что часто забывают

```ini
# postgresql.conf
listen_addresses = 'localhost'      # по умолчанию: снаружи не подключиться вообще
listen_addresses = '10.0.1.5,localhost'   # конкретные интерфейсы (правильно)
listen_addresses = '*'              # все интерфейсы (только если снаружи есть firewall)
```
Требует **restart**. Симптом неверной настройки — `Connection refused`,
а вовсе не «no pg_hba.conf entry».

```text:no-line-numbers
Connection refused              → сеть/listen_addresses/порт/firewall
no pg_hba.conf entry for host   → дошли до базы, но нет правила ⇒ правим pg_hba
password authentication failed  → правило есть, пароль/метод не совпал
```

---

## 3. Роли: пользователи и группы — это одно и то же

В PostgreSQL нет отдельных «пользователей» и «групп»: есть **роли**.
Роль с атрибутом `LOGIN` — это пользователь; роль без него обычно используют как группу.

```sql
-- пользователь приложения
CREATE ROLE app WITH LOGIN PASSWORD 'strong' CONNECTION LIMIT 50;

-- роль-группа с правами только на чтение
CREATE ROLE readonly;                       -- без LOGIN
GRANT CONNECT ON DATABASE shop TO readonly;
GRANT USAGE ON SCHEMA public TO readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly;

-- аналитик — член группы
CREATE ROLE analyst WITH LOGIN PASSWORD 'xxx';
GRANT readonly TO analyst;                  -- членство в группе

-- срок действия пароля / временный доступ
ALTER ROLE analyst VALID UNTIL '2026-01-01';
```

| Атрибут | Смысл |
|---------|-------|
| `LOGIN` | Может подключаться |
| `SUPERUSER` | Всё можно, проверки прав игнорируются ⚠️ |
| `CREATEDB`, `CREATEROLE` | Создавать базы / роли |
| `REPLICATION` | Подключаться как реплика (тема 06) |
| `CONNECTION LIMIT n` | Максимум одновременных соединений роли |
| `VALID UNTIL` | Дата окончания действия пароля |
| `NOINHERIT` | Права группы нужно активировать `SET ROLE` |

Посмотреть: `\du`, `\drg` (членства), `SELECT * FROM pg_roles;`

---

## 4. Права: `GRANT` по уровням

```text:no-line-numbers
КЛАСТЕР ──► БАЗА ──► СХЕМА ──► ТАБЛИЦА/ПОСЛЕДОВАТЕЛЬНОСТЬ/ФУНКЦИЯ ──► КОЛОНКА
            CONNECT  USAGE      SELECT/INSERT/UPDATE/DELETE            SELECT(col)
```
Чтобы прочитать таблицу, роли нужны **все три** уровня: `CONNECT` на базу,
`USAGE` на схему, `SELECT` на таблицу. Это частая причина «дал SELECT, всё равно permission denied».

```sql
GRANT CONNECT ON DATABASE shop TO app;
GRANT USAGE ON SCHEMA public TO app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app;   -- для serial/identity

-- ⭐ права на БУДУЩИЕ таблицы (иначе после миграции всё сломается)
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO readonly;

REVOKE DELETE ON orders FROM app;          -- забрать
```

Проверить права:
```sql
\dp orders                                              -- права на таблицу
SELECT has_table_privilege('app','orders','SELECT');    -- точечная проверка
SELECT has_database_privilege('app','shop','CONNECT');
```

> ⭐ В PostgreSQL 15+ обычные пользователи больше **не могут** создавать объекты в схеме
> `public` по умолчанию — частая причина «раньше работало, после апгрейда нет».
> Решение: `GRANT CREATE ON SCHEMA public TO app;` или отдельная схема под приложение.

### Принцип минимальных прав для приложения

```sql
-- владелец схемы/таблиц: отдельная роль, под которой едут миграции
CREATE ROLE shop_owner LOGIN PASSWORD '...';
-- рабочая роль приложения: только DML, без DDL
CREATE ROLE shop_app LOGIN PASSWORD '...';
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO shop_app;
```
Так приложение физически не может выполнить `DROP TABLE`, даже если очень захочет
(а миграции едут отдельной ролью из CI).

---

## 5. TLS: шифрование соединения

```ini
# postgresql.conf
ssl = on
ssl_cert_file = '/etc/ssl/certs/server.crt'
ssl_key_file  = '/etc/ssl/private/server.key'   # права 600, владелец postgres
```
```text:no-line-numbers
# pg_hba.conf — требовать TLS для внешних подключений
hostssl  shop  app  10.0.0.0/8  scram-sha-256
hostnossl all  all  0.0.0.0/0   reject
```
Со стороны клиента:
```bash
psql "postgresql://app@db:5432/shop?sslmode=verify-full&sslrootcert=/etc/ssl/ca.crt"
```
| `sslmode` | Смысл |
|-----------|-------|
| `disable` | Без TLS |
| `require` | Шифрование есть, сертификат не проверяется |
| `verify-ca` | Проверяется, что сертификат выдан доверенным CA |
| `verify-full` | ⭐ Плюс проверка имени хоста (правильный выбор для прода) |

Проверить, что соединение зашифровано:
```sql
SELECT ssl, version, cipher, client_addr FROM pg_stat_ssl
  JOIN pg_stat_activity USING (pid);
```

---

## 6. Пароли и секреты

```sql
\password app                       -- безопасно: хеш не попадает в историю psql
ALTER ROLE app PASSWORD 'new';      -- ⚠️ попадёт в лог, если log_statement='all'
SHOW password_encryption;           -- должно быть scram-sha-256
```

Правила гигиены:
1. Пароли — в Vault / CI-переменных / ansible-vault, **не** в репозитории
   (см. раздел «Vault» и [раздел «Ansible»](/ansible/12-vault)).
2. Для приложений — отдельная роль на сервис, не общий `postgres`.
3. `~/.pgpass` с правами `600` вместо пароля в командной строке.
4. Ротация паролей — плановая процедура: сначала новый пароль, потом обновление
   конфигов приложений, потом отзыв старого.
5. Суперпользователь `postgres` по сети недоступен (`local ... peer` и только он).

---

## 7. Разбор ошибок подключения (рабочий алгоритм)

```text:no-line-numbers
psql -h db -U app -d shop
        │
        ├─ "Connection refused"      ──► сеть: ss -tlnp | grep 5432, firewall,
        │                                 listen_addresses (нужен RESTART)
        ├─ "no pg_hba.conf entry"    ──► нет правила: смотри pg_hba_file_rules,
        │                                 добавь строку, сделай RELOAD
        ├─ "password authentication  ──► пароль/метод: scram vs md5, \password,
        │   failed"                       password_encryption
        ├─ "database ... does not     ──► опечатка в -d или база не создана
        │   exist"
        ├─ "permission denied for     ──► аутентификация прошла, не хватает GRANT
        │   table/schema"                 (CONNECT → USAGE → SELECT)
        └─ "too many connections"     ──► max_connections / CONNECTION LIMIT
```

Логи базы отвечают на большинство вопросов:
```bash
sudo tail -f /var/log/postgresql/postgresql-16-main.log
docker logs -f pg
```
```ini
log_connections = on          # кто подключился
log_disconnections = on       # и когда отключился
```

---

## 💼 Как это в DevOps

- `pg_hba.conf` почти всегда генерируется шаблоном Ansible из списка «сервис → подсеть»:
  это даёт ревьюируемую историю доступов в git.
- Нормальный прод: `hostssl` + `scram-sha-256` + отдельная роль на каждый сервис +
  доступ только из подсетей приложений, `reject` в конце.
- Доступ людей к проду обычно даётся через bastion/VPN и read-only роль, а полноценный
  доступ — по заявке и на время (`VALID UNTIL`).
- Миграции едут под ролью-владельцем из CI/CD, приложение работает под ролью без DDL.
- Аудит: `log_connections`, `pg_stat_activity`, регулярный обзор `\du` и `\dp`
  («кто вообще имеет доступ к проду?»).

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Разрешить приложению из подсети | `host shop app 10.0.1.0/24 scram-sha-256` |
| Разрешить только по TLS | `hostssl …` + `hostnossl all all 0.0.0.0/0 reject` |
| Разрешить реплику | `host replication repl 10.0.1.5/32 scram-sha-256` |
| Применить `pg_hba.conf` | `SELECT pg_reload_conf();` |
| Проверить правила и ошибки | `SELECT * FROM pg_hba_file_rules;` |
| Слушать сеть | `listen_addresses` + **restart** |
| Создать роль приложения | `CREATE ROLE app LOGIN PASSWORD '…';` |
| Создать группу и добавить в неё | `CREATE ROLE readonly;` + `GRANT readonly TO analyst;` |
| Дать чтение всей схемы | `GRANT USAGE ON SCHEMA public …; GRANT SELECT ON ALL TABLES …;` |
| Права на будущие таблицы | `ALTER DEFAULT PRIVILEGES … GRANT …` |
| Ограничить число соединений роли | `ALTER ROLE app CONNECTION LIMIT 50;` |
| Временный доступ | `ALTER ROLE analyst VALID UNTIL '2026-01-01';` |
| Посмотреть права на таблицу | `\dp orders` |
| Посмотреть роли и членства | `\du`, `\drg` |
| Сменить пароль безопасно | `\password app` |
| Проверить шифрование соединения | `SELECT * FROM pg_stat_ssl;` |

---

## 🧠 Что запомнить

1. Путь клиента: сеть → `pg_hba.conf` (аутентификация) → `GRANT` (авторизация).
2. ⭐ `pg_hba.conf` читается сверху вниз до первого совпадения; «широкая» строка сверху
   перекрывает всё, что ниже.
3. `pg_hba.conf` применяется по **reload**, `listen_addresses` — только по **restart**.
4. `trust` в проде не существует; стандарт — `scram-sha-256`, снаружи — `hostssl`.
5. `Connection refused` — это сеть/listen, `no pg_hba.conf entry` — это правило,
   `permission denied` — это уже права.
6. Роль = пользователь и группа одновременно; `LOGIN` делает её пользователем.
7. Для чтения таблицы нужны три уровня: `CONNECT` → `USAGE` на схему → `SELECT` на таблицу.
8. `ALTER DEFAULT PRIVILEGES` — чтобы права работали и для таблиц, созданных завтра.
9. В PG 15+ `public` больше не даёт `CREATE` всем — частая причина поломки после апгрейда.
10. Приложение работает под ролью без DDL, миграции — под владельцем; суперпользователь
    по сети не ходит.

---

## Задачи

> Стенд: PostgreSQL на VM (или два контейнера в одной docker-сети — чтобы были «разные хосты»).

---

### Блок A. Теория

**A1.** Чем аутентификация отличается от авторизации? Где в PostgreSQL живёт каждая?

<details><summary>Ответ</summary>

Аутентификация — проверка «ты тот, за кого себя выдаёшь» (`pg_hba.conf`).
Авторизация — «что тебе разрешено внутри» (роли и `GRANT`).

</details>

**A2.** Разбери строку `hostssl shop app 10.0.1.0/24 scram-sha-256` по полям.

<details><summary>Ответ</summary>

`hostssl` — только TLS-соединения; база `shop`; роль `app`; клиент из
подсети `10.0.1.0/24`; метод `scram-sha-256` (пароль по современному протоколу).

</details>

**A3.** ⭐ В каком порядке просматриваются строки `pg_hba.conf` и что происходит,
если подошедшая строка не пропустила клиента?

<details><summary>Ответ</summary>

Сверху вниз, применяется первая строка, совпавшая по типу/базе/роли/адресу.
Если по ней аутентификация не прошла — соединение отклоняется, остальные строки
не просматриваются.

</details>

**A4.** Чем отличаются `local`, `host`, `hostssl`, `hostnossl`?

<details><summary>Ответ</summary>

`local` — Unix-сокет; `host` — TCP с TLS или без; `hostssl` — только с TLS;
`hostnossl` — только без TLS (обычно используется в паре с `reject`).

</details>

**A5.** Что делают методы `trust`, `peer`, `md5`, `scram-sha-256`, `reject`?
Какие из них допустимы в проде?

<details><summary>Ответ</summary>

`trust` — без пароля (только тестовый стенд); `peer` — сверка с именем
пользователя ОС по локальному сокету; `md5` — устаревший хеш; `scram-sha-256` — текущий
стандарт; `reject` — явный запрет. В проде допустимы `scram-sha-256`, `cert`, `peer`
(локально), `reject`.

</details>

**A6.** Что означает специальное значение `replication` в поле DATABASE?

<details><summary>Ответ</summary>

Это не база данных, а специальный вид подключения — физическая репликация
(и `pg_basebackup`). Без такой строки реплика не подключится.

</details>

**A7.** Какие изменения доступа требуют `reload`, а какие — `restart`?

<details><summary>Ответ</summary>

`pg_hba.conf`, `pg_ident.conf` — reload. `listen_addresses`, `port`,
`max_connections`, `ssl` (включение) — restart.

</details>

**A8.** Как проверить синтаксис и порядок правил, не дожидаясь жалоб клиентов?

<details><summary>Ответ</summary>

`SELECT * FROM pg_hba_file_rules;` — показывает разобранные строки и ошибки
разбора, включая порядок.

</details>

**A9.** Три ошибки подключения: `Connection refused`, `no pg_hba.conf entry`,
`password authentication failed`. Что означает каждая?

<details><summary>Ответ</summary>

Refused — не дошли до базы (сервис не слушает нужный адрес/порт, firewall).
No entry — дошли, но нет подходящего правила. Password failed — правило есть,
не совпал пароль или метод (например, клиент со старым md5).

</details>

**A10.** Чем роль-пользователь отличается от роли-группы?

<details><summary>Ответ</summary>

Технически ничем: это одна сущность. Роль с `LOGIN` используется как
пользователь, роль без `LOGIN` — как группа, в которую включают пользователей
через `GRANT группа TO пользователь`.

</details>

**A11.** Какие три уровня прав нужны, чтобы роль смогла прочитать таблицу?

<details><summary>Ответ</summary>

`CONNECT` на базу → `USAGE` на схему → `SELECT` на таблицу.

</details>

**A12.** Зачем нужен `ALTER DEFAULT PRIVILEGES`?

<details><summary>Ответ</summary>

Чтобы права автоматически распространялись на объекты, созданные **в будущем**
указанной ролью. Иначе после каждой миграции придётся раздавать `GRANT` заново.

</details>

**A13.** ⭐ Что поменялось со схемой `public` в PostgreSQL 15 и как это ломает приложения?

<details><summary>Ответ</summary>

С PG 15 схема `public` больше не даёт `CREATE` роли `PUBLIC`: право создавать
объекты есть только у владельца базы. Приложения, создававшие таблицы «на лету»,
получают `permission denied for schema public`. Решение — `GRANT CREATE ON SCHEMA public`
нужной роли или выделенная схема.

</details>

**A14.** Зачем разделять роль-владельца (для миграций) и роль приложения?

<details><summary>Ответ</summary>

Приложение не должно иметь возможности выполнять DDL: это защищает от случайного
`DROP`/`ALTER` из кода и сужает ущерб при SQL-инъекции. Миграции выполняются отдельной
ролью из CI/CD, где это осознанное действие.

</details>

**A15.** Что означают `sslmode=require`, `verify-ca`, `verify-full`? Какой нужен в проде?

<details><summary>Ответ</summary>

`require` — шифрование без проверки подлинности сервера (защищает от пассивного
прослушивания, но не от MITM); `verify-ca` — проверяется цепочка до доверенного CA;
`verify-full` — плюс проверка имени хоста. В проде — `verify-full`.

</details>

---

### Блок B. «Что тут не так»

Разбери каждый фрагмент `pg_hba.conf`:

```text:no-line-numbers
B1.  host  all  all  0.0.0.0/0  trust
B2.  host  all  all  0.0.0.0/0  md5
     host  shop app  10.0.1.0/24 scram-sha-256
B3.  local all  postgres        peer
B4.  host  replication all 0.0.0.0/0 scram-sha-256
B5.  hostnossl shop app 10.0.1.0/24 scram-sha-256
B6.  host  shop app  10.0.1.7  scram-sha-256        # без маски
```

<details><summary>Ответ</summary>

**B1.** Пускает всех отовсюду без пароля — критическая дыра.

**B2.** Первая строка перекрывает вторую: все подключаются по устаревшему `md5`,
специальное правило для `app` не сработает никогда. Порядок должен быть от частного к общему.

**B3.** Нормально и правильно: локальный `postgres` через `sudo -u postgres psql`.

**B4.** Репликация разрешена откуда угодно любой роли — так реплику может поднять кто угодно,
получив полную копию данных. Нужны конкретные адреса реплик и отдельная роль.

**B5.** Запрещает TLS для приложения — трафик с паролями и данными идёт открытым. Нужен `hostssl`.

**B6.** Адрес без маски — ошибка формата (нужно `10.0.1.7/32`); строка не применится,
правило появится в `pg_hba_file_rules.error`.

</details>

```sql
B7.  GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly;
     -- но роль всё равно получает "permission denied for schema public"
B8.  CREATE ROLE app WITH LOGIN SUPERUSER PASSWORD 'app';
B9.  ALTER ROLE app PASSWORD 'newpassword';          -- при log_statement='all'
B10. GRANT ALL PRIVILEGES ON DATABASE shop TO app;   -- "чтобы точно работало"
```

<details><summary>Ответ</summary>

**B7.** Не хватает `GRANT USAGE ON SCHEMA public TO readonly;` — права на таблицы
не работают без права на схему.

**B8.** Приложению выдан суперпользователь: обходятся все проверки прав,
любая инъекция или ошибка кода = полный контроль над кластером.

**B9.** Пароль попадёт в лог открытым текстом. Использовать `\password` (клиент считает
пароль и отправит уже хеш) или `SET log_statement='none'` на сессию.

**B10.** `ALL PRIVILEGES ON DATABASE` даёт `CREATE`/`TEMP`/`CONNECT` на базу, но **не** права
на таблицы — обычно люди ждут не того. При этом приложение получает право создавать схемы.

</details>

```ini
B11. listen_addresses = '*'        # и firewall не настроен
B12. password_encryption = md5
```

<details><summary>Ответ</summary>

**B11.** База слушает все интерфейсы без firewall — потенциально доступна из интернета.

**B12.** Пароли хранятся устаревшим хешем; нужно `scram-sha-256` и смена паролей ролей.

</details>

---

### Блок C. Практика

#### C1. 🔑 Открыть базу «правильно»
1. Поставь `listen_addresses` на конкретный IP, сделай restart.
2. Добавь правило для подсети приложения со `scram-sha-256`, сделай reload.
3. Последней строкой добавь `host all all 0.0.0.0/0 reject`.
4. Подключись с разрешённого хоста и с запрещённого — сравни ошибки.

<details><summary>Ответ</summary>

С разрешённого хоста — успешное подключение; с запрещённого —
`no pg_hba.conf entry for host` (если дошли до базы) или таймаут/refused (если мешает firewall).

</details>

#### C2. Порядок строк решает
1. Добавь в начало файла `host all all 0.0.0.0/0 reject` и сделай reload.
2. Попробуй подключиться — что произошло, хотя ниже есть разрешающая строка?
3. Верни правильный порядок и объясни правило первого совпадения.

<details><summary>Ответ</summary>

Подключения перестанут работать полностью: сработает первая строка `reject`.
Правило первого совпадения — самое частое «ой» в этом файле.

</details>

#### C3. `pg_hba_file_rules`
```sql
SELECT line_number, type, database, user_name, address, auth_method, error
FROM pg_hba_file_rules ORDER BY line_number;
```
Внеси намеренную опечатку в файл, сделай reload и найди её через этот запрос.

<details><summary>Ответ</summary>

Ошибочная строка появится с заполненной колонкой `error`, остальные правила
продолжат работать.

</details>

#### C4. Роль приложения с минимальными правами
1. Создай `shop_owner` (владелец) и `shop_app` (только DML).
2. Под `shop_owner` создай таблицу, под `shop_app` попробуй `DROP TABLE` — должно быть отказано.
3. Проверь `\dp` и `has_table_privilege`.

<details><summary>Ответ</summary>

`shop_app` получит `ERROR: must be owner of table` при попытке `DROP`.

</details>

#### C5. Группа readonly
1. Создай группу `readonly` с `CONNECT`/`USAGE`/`SELECT`.
2. Создай пользователя `analyst`, включи в группу.
3. Убедись, что `INSERT` ему запрещён.
4. Создай новую таблицу и проверь: видит ли её `analyst`? Почини через `ALTER DEFAULT PRIVILEGES`.

<details><summary>Ответ</summary>

Новая таблица не будет видна аналитику, пока не выполнен
`ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO readonly;`
(или повторный `GRANT SELECT ON ALL TABLES`).

</details>

#### C6. Три уровня прав
Сними у роли по очереди `SELECT`, потом `USAGE` на схему, потом `CONNECT` на базу.
Записывай текст ошибки на каждом шаге — это поможет на дежурстве.

<details><summary>Ответ</summary>

Тексты ошибок: `permission denied for table X` → `permission denied for schema public`
→ `FATAL: permission denied for database "shop"`.

</details>

#### C7. Лимиты и срок действия
1. `ALTER ROLE app CONNECTION LIMIT 2;` — открой три соединения, посмотри ошибку.
2. `ALTER ROLE analyst VALID UNTIL '2020-01-01';` — попробуй подключиться.

<details><summary>Ответ</summary>

Третье соединение получит `FATAL: too many connections for role "app"`;
после `VALID UNTIL` в прошлом — `password authentication failed` (пароль считается истёкшим).

</details>

#### C8. Логи подключений
Включи `log_connections` и `log_disconnections`, сделай несколько удачных и неудачных
подключений, найди их в логе и опиши, какие поля полезны для разбора.

<details><summary>Ответ</summary>

В логе видно `connection received: host=… port=…` и
`connection authorized: user=… database=… SSL=…` — по ним разбирают «кто и откуда ходил».

</details>

#### C9. TLS (со звёздочкой)
1. Сгенерируй самоподписанный сертификат, включи `ssl = on`.
2. Переведи внешний доступ на `hostssl`, запрети `hostnossl`.
3. Подключись с `sslmode=require` и `sslmode=disable` — сравни.
4. Проверь `pg_stat_ssl`.

<details><summary>Ответ</summary>

С `sslmode=disable` подключение будет отклонено правилом `hostnossl … reject`;
`pg_stat_ssl` покажет `ssl = t`, версию TLS и шифр.

</details>

#### C10. Аудит доступов
Напиши набор запросов «кто имеет доступ к этой базе»: роли с LOGIN, суперпользователи,
членства в группах, права на таблицы. Оформи как чек-лист для ежеквартального ревью.

<details><summary>Ответ</summary>

Полезный минимум запросов: `SELECT rolname, rolsuper, rolcanlogin FROM pg_roles;`,
`\drg`, `\dp`, плюс список правил `pg_hba_file_rules`.

</details>

---

### Блок D. Инциденты

**D1.** Приложение из нового кластера k8s не может подключиться: `no pg_hba.conf entry
for host "10.42.3.9"`. Твои действия по шагам.

<details><summary>Ответ</summary>

Узнать реальную подсеть подов, добавить правило `host shop app <подсеть> scram-sha-256`
выше общего `reject`, `SELECT pg_reload_conf();`, проверить `pg_hba_file_rules`,
проверить подключение и firewall/security group.

</details>

**D2.** После правки `pg_hba.conf` ничего не изменилось. Что забыли?

<details><summary>Ответ</summary>

Не сделан reload (`SELECT pg_reload_conf();`), либо правился не тот файл
(проверить `SHOW hba_file;`), либо новая строка ниже более общей.

</details>

**D3.** После рестарта базы отвалились все приложения: `password authentication failed`.
Накануне меняли `password_encryption`. Что произошло?

<details><summary>Ответ</summary>

Пароли ролей хранились как md5; после перевода на `scram-sha-256` старые хеши
не подходят под новый метод — нужно **пересоздать пароли** ролей (`\password`)
после смены `password_encryption`.

</details>

**D4.** Разработчик просит «просто дай суперюзера, чтобы не мучиться». Твой ответ и альтернатива.

<details><summary>Ответ</summary>

Отказать: суперюзер обходит все проверки и не оставляет границ. Альтернатива —
роль с нужными правами (`CREATE`/DML в конкретной схеме), отдельная база для экспериментов,
доступ на стейдже, временная роль с `VALID UNTIL`.

</details>

**D5.** После апгрейда на PG 15 приложение не может создавать таблицы: `permission denied
for schema public`. Причина и два решения.

<details><summary>Ответ</summary>

С PG 15 `public` не даёт `CREATE`. Решения: `GRANT CREATE ON SCHEMA public TO app;`
или выделить приложению собственную схему и прописать `search_path`.

</details>

**D6.** Аналитик получил `SELECT` на все таблицы, но новая таблица ему не видна. Почему?

<details><summary>Ответ</summary>

`GRANT` действует только на существовавшие на тот момент таблицы.
Нужен `ALTER DEFAULT PRIVILEGES` (и повторный `GRANT` для уже созданных).

</details>

**D7.** В логе видно сотни попыток подключения с неизвестного IP под ролью `postgres`.
Что делаешь?

<details><summary>Ответ</summary>

Проверить, снаружи ли доступна база (firewall/secgroup/listen_addresses),
закрыть доступ до подсетей приложений, убедиться, что `postgres` по сети запрещён,
проверить успешные попытки в логе, при подозрении на компрометацию — ротация паролей
и разбор инцидента.

</details>

**D8.** `FATAL: too many connections for role "app"`. Где смотреть и что менять?

<details><summary>Ответ</summary>

`SELECT count(*) FROM pg_stat_activity WHERE usename='app';`,
`SELECT rolconnlimit FROM pg_roles WHERE rolname='app';`, `SHOW max_connections;`.
Лечение — PgBouncer и разумный пул на стороне приложения, а не бесконечное повышение лимита.

</details>

**D9.** Кто-то добавил строку `host all all 0.0.0.0/0 trust` «на время отладки»
и ушёл в отпуск. Опиши риск и порядок исправления без простоя.

<details><summary>Ответ</summary>

Любой, кто дотянется до порта, зайдёт без пароля под любой ролью, включая `postgres`.
Исправление: убедиться, что легальные клиенты имеют свои правила выше, удалить строку
`trust`, `reload` (соединения не рвутся), проверить `pg_hba_file_rules` и логи на предмет
подключений, которые опирались на эту строку.

</details>

**D10.** Нужно дать доступ подрядчику к проду на две недели, только на чтение.
Как оформишь технически?

<details><summary>Ответ</summary>

Создать роль с `LOGIN`, `VALID UNTIL` на две недели, включить в группу `readonly`,
разрешить подключение только с bastion/VPN-адреса в `pg_hba.conf`, выдать пароль через
безопасный канал, после срока — `DROP ROLE` и проверка, что доступ закрыт.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое `pg_hba.conf` и как он устроен?

<details><summary>Ответ</summary>

Файл правил аутентификации: тип подключения, база, роль, адрес, метод.

</details>

**2.** В каком порядке применяются правила?

<details><summary>Ответ</summary>

Сверху вниз до первого совпадения; несработавшая аутентификация не «проваливается» дальше.

</details>

**3.** Какие методы аутентификации знаешь и какой стандарт сейчас?

<details><summary>Ответ</summary>

`trust`, `peer`, `md5`, `scram-sha-256`, `cert`, `ldap`, `reject`; стандарт — `scram-sha-256`.

</details>

**4.** Чем `reload` отличается от `restart` применительно к доступам?

<details><summary>Ответ</summary>

`pg_hba.conf` — reload; `listen_addresses`, `port`, `max_connections` — restart.

</details>

**5.** Чем отличаются ошибки `Connection refused` и `no pg_hba.conf entry`?

<details><summary>Ответ</summary>

Первое — не дошли до базы (сеть/listen/firewall), второе — дошли, но нет правила.

</details>

**6.** Как дать роли доступ только на чтение ко всей базе?

<details><summary>Ответ</summary>

Группа `readonly`: `CONNECT` на базу, `USAGE` на схему, `SELECT ON ALL TABLES`,
плюс `ALTER DEFAULT PRIVILEGES` на будущие таблицы.

</details>

**7.** Что такое `ALTER DEFAULT PRIVILEGES`?

<details><summary>Ответ</summary>

Правила прав по умолчанию для объектов, которые будут созданы в будущем.

</details>

**8.** Как разграничить права приложения и миграций?

<details><summary>Ответ</summary>

Владелец схемы/таблиц — отдельная роль для миграций из CI; приложение — роль только с DML.

</details>

**9.** Как включить TLS и заставить клиентов его использовать?

<details><summary>Ответ</summary>

`ssl = on` + сертификаты, `hostssl` в `pg_hba.conf`, `hostnossl … reject`,
клиенты с `sslmode=verify-full`.

</details>

**10.** Как выдать временный доступ человеку и как его потом отозвать?

<details><summary>Ответ</summary>

Отдельная роль с `VALID UNTIL` и ограничением по адресу, членство в read-only группе;
отзыв — `DROP ROLE` и проверка правил доступа.

</details>

---

### 🎯 Чек-лист

- [ ] Понимаю разницу аутентификации и авторизации в PostgreSQL
- [ ] ⭐ Помню правило первого совпадения в `pg_hba.conf`
- [ ] Знаю, что доступы применяются по reload, а `listen_addresses` — по restart
- [ ] Читаю `pg_hba_file_rules` для проверки правил
- [ ] Различаю три типовые ошибки подключения и знаю, куда смотреть по каждой
- [ ] Умею завести роль приложения без прав DDL и отдельную роль для миграций
- [ ] Умею сделать группу readonly и не забыть `ALTER DEFAULT PRIVILEGES`
- [ ] Знаю про изменение схемы `public` в PG 15
- [ ] Настроил TLS и проверил `pg_stat_ssl`
- [ ] Есть чек-лист аудита «кто имеет доступ к базе»
