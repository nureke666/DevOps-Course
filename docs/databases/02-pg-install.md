---
title: "02. PostgreSQL: установка и устройство"
description: "Установка из PGDG/RHEL/Docker, где что лежит, управление сервисом, psql, reload vs restart, версии и обновления"
---

# 02. PostgreSQL: установка и устройство

> Роадмап → Базы → PostgreSQL → *«Установка и базовая настройка»*.
>
> **После темы ты умеешь:** поставить PostgreSQL нужной версии из официального репозитория,
> найти конфиги и данные, управлять сервисом, зайти через `psql` и понимать, что такое
> «кластер PostgreSQL».

---

## 🗺️ Идея: что такое «кластер PostgreSQL»

⚠️ В PostgreSQL слово **кластер** означает **не** «несколько серверов».
Кластер = один экземпляр (инстанс) СУБД + его каталог данных + все базы внутри него.

```text:no-line-numbers
СЕРВЕР (один хост)
└── КЛАСТЕР PostgreSQL (один процесс postmaster, один порт 5432, один PGDATA)
    ├── база postgres      ← служебная, «домашняя» для суперпользователя
    ├── база template0/1   ← шаблоны для CREATE DATABASE
    ├── база shop          ← твоё приложение
    │   ├── схема public
    │   │   ├── таблица users
    │   │   └── таблица orders
    │   └── схема billing
    └── РОЛИ (пользователи) — общие на весь кластер ⭐
```

Отсюда два практических следствия:
- **Роли и пароли общие для всего кластера**, а права выдаются внутри баз (тема 03).
- На одном сервере можно поднять **несколько кластеров** — каждый со своим портом
  и каталогом данных (в Debian/Ubuntu это штатная возможность).

---

## 1. Установка

### Вариант A. Ubuntu/Debian, официальный репозиторий PGDG (так делают в проде)

```bash
sudo apt install -y curl ca-certificates
sudo install -d /usr/share/postgresql-common/pgdg
sudo curl -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
  --fail https://www.postgresql.org/media/keys/ACCC4CF8.asc

. /etc/os-release
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
https://apt.postgresql.org/pub/repos/apt $VERSION_CODENAME-pgdg main" \
  | sudo tee /etc/apt/sources.list.d/pgdg.list

sudo apt update
sudo apt install -y postgresql-16 postgresql-client-16
```

> 💡 Почему не просто `apt install postgresql`? В репозитории дистрибутива лежит
> та версия, которая была на момент релиза ОС. PGDG даёт актуальные мажорные версии
> и одинаковую версию на всех серверах — это важно для репликации.

Проверка:
```bash
systemctl status postgresql          # обёртка над кластерами
pg_lsclusters                        # ⭐ Debian/Ubuntu: список кластеров
sudo -u postgres psql -c "SELECT version();"
```

```text:no-line-numbers
Ver Cluster Port Status Owner    Data directory              Log file
16  main    5432 online postgres /var/lib/postgresql/16/main /var/log/postgresql/postgresql-16-main.log
```

### Вариант B. RHEL/CentOS/Rocky

```bash
sudo dnf install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-9-x86_64/pgdg-redhat-repo-latest.noarch.rpm
sudo dnf -qy module disable postgresql
sudo dnf install -y postgresql16-server
sudo /usr/pgsql-16/bin/postgresql-16-setup initdb   # ⭐ здесь initdb руками
sudo systemctl enable --now postgresql-16
```

### Вариант C. Docker (учёба, dev)

```bash
docker run -d --name pg \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_DB=shop \
  -p 5432:5432 \
  -v pgdata:/var/lib/postgresql/data \
  postgres:16

docker exec -it pg psql -U postgres -d shop
```

| Переменная образа | Что делает |
|-------------------|------------|
| `POSTGRES_PASSWORD` | Пароль суперпользователя (обязательна) |
| `POSTGRES_USER` | Имя суперпользователя (по умолчанию `postgres`) |
| `POSTGRES_DB` | Создать базу при первом запуске |
| `PGDATA` | Где данные внутри контейнера |
| `POSTGRES_INITDB_ARGS` | Аргументы `initdb`, например `--data-checksums` |

Скрипты из `/docker-entrypoint-initdb.d/*.sql|*.sh` выполняются **только при первой**
инициализации пустого тома. Добавил файл позже — он не выполнится, пока не удалишь том.

> ⚠️ Без `-v` данные живут внутри контейнера и исчезают вместе с ним.
> Это самая частая ошибка в учебных стендах.

---

## 2. Где что лежит

| Что | Ubuntu/Debian | RHEL | Docker (офиц. образ) |
|-----|---------------|------|----------------------|
| Данные (PGDATA) | `/var/lib/postgresql/16/main` | `/var/lib/pgsql/16/data` | `/var/lib/postgresql/data` |
| `postgresql.conf` | `/etc/postgresql/16/main/` | внутри PGDATA | внутри PGDATA |
| `pg_hba.conf` | `/etc/postgresql/16/main/` | внутри PGDATA | внутри PGDATA |
| Логи | `/var/log/postgresql/` | внутри PGDATA `log/` | stdout (`docker logs`) |
| Бинарники | `/usr/lib/postgresql/16/bin` | `/usr/pgsql-16/bin` | `/usr/lib/postgresql/16/bin` |

Спросить у самой базы — надёжнее, чем помнить таблицу:
```sql
SHOW data_directory;
SHOW config_file;
SHOW hba_file;
SELECT name, setting, source, sourcefile FROM pg_settings WHERE name='shared_buffers';
```

### Внутри PGDATA

```text:no-line-numbers
PGDATA/
├── base/            данные баз (подкаталог на каждую базу, файл на каждую таблицу)
├── global/          общекластерные объекты (в т.ч. роли)
├── pg_wal/          ⭐ журнал предзаписи (WAL). Руками НИЧЕГО не удалять!
├── pg_xact/         статусы транзакций
├── log/             логи (если logging_collector = on)
├── postgresql.conf  основной конфиг (в Debian — симлинк на /etc)
├── pg_hba.conf      правила подключения
├── postmaster.pid   pid работающего инстанса
└── PG_VERSION       мажорная версия — по ней бинарь понимает совместимость
```

> ⚠️ Правило дежурного: **никогда не удаляй файлы из `pg_wal/` вручную**, даже когда
> кончается место. Это прямой путь к неподнимающейся базе. Разбираться надо с причиной
> роста (тема 05).

---

## 3. Управление сервисом

```bash
# Debian/Ubuntu — «обёртки» над кластерами
sudo systemctl status postgresql@16-main
sudo systemctl restart postgresql@16-main
sudo pg_ctlcluster 16 main start|stop|restart|reload
sudo pg_lsclusters

# создать второй кластер на другом порту
sudo pg_createcluster 16 test --port 5433 --start
sudo pg_dropcluster 16 test --stop        # удалить вместе с данными (осторожно)

# универсально (через bin PostgreSQL)
sudo -u postgres /usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/16/main status
```

**reload vs restart** — вопрос, который любят на собесе:

| Действие | Что делает | Когда хватает |
|----------|------------|---------------|
| `reload` (`SELECT pg_reload_conf();`) | Перечитать конфиги без разрыва соединений | `pg_hba.conf`, большинство параметров `postgresql.conf` |
| `restart` | Полный перезапуск, все соединения рвутся | `shared_buffers`, `max_connections`, `port`, `wal_level` |

Как понять, нужен ли рестарт:
```sql
SELECT name, setting, pending_restart FROM pg_settings WHERE pending_restart;
SELECT name, context FROM pg_settings WHERE name='shared_buffers';  -- context=postmaster ⇒ рестарт
```

---

## 4. `psql` — рабочий инструмент девопса

```bash
sudo -u postgres psql                       # локально, peer-аутентификация
psql -h 10.0.0.5 -p 5432 -U app -d shop     # по сети
psql "postgresql://app:pass@10.0.0.5:5432/shop?sslmode=require"   # URI
PGPASSWORD=secret psql -h host -U app -d shop -c "SELECT 1;"      # разово (лучше ~/.pgpass)
```

`~/.pgpass` (права строго `600`):
```text:no-line-numbers
# host:port:database:user:password
10.0.0.5:5432:shop:app:SuperSecret
```

### Мета-команды, которые реально нужны

| Команда | Что показывает |
|---------|----------------|
| `\l` | Список баз (и их размер с `\l+`) |
| `\c shop` | Переключиться на базу |
| `\dt` | Таблицы текущей схемы |
| `\d users` | Структура таблицы, индексы, ограничения |
| `\du` | Роли и их атрибуты |
| `\dn` | Схемы |
| `\dp` / `\z` | Права на таблицы |
| `\x` | Вертикальный вывод (спасение для широких строк) |
| `\timing` | Показывать время выполнения |
| `\conninfo` | Как и куда ты подключён |
| `\e` | Открыть редактор для запроса |
| `\i file.sql` | Выполнить файл |
| `\watch 2` | Повторять последний запрос каждые 2 сек (мониторинг вживую) |
| `\q` | Выход |

```bash
# однострочники для скриптов и мониторинга
psql -At -c "SELECT count(*) FROM pg_stat_activity;"    # -A без рамки, -t без заголовка
psql -f migration.sql -v ON_ERROR_STOP=1                 # ⭐ в CI обязательно
```

---

## 5. Первая базовая настройка после установки

```bash
sudo -u postgres psql
```
```sql
\password postgres                                    -- задать пароль суперпользователю
CREATE ROLE app LOGIN PASSWORD 'strong-password';     -- роль приложения (не суперюзер!)
CREATE DATABASE shop OWNER app;                       -- база под приложение
\c shop
REVOKE ALL ON SCHEMA public FROM PUBLIC;              -- гигиена прав (PG15+ уже строже)
GRANT ALL ON SCHEMA public TO app;
```

Минимальные правки конфигов (подробности — темы 03 и 04):
```ini
# postgresql.conf
listen_addresses = '10.0.0.5,localhost'   # по умолчанию только localhost
port = 5432
shared_buffers = 2GB                      # ~25% RAM
logging_collector = on
log_line_prefix = '%m [%p] %u@%d '        # время, pid, пользователь, база
log_min_duration_statement = 1000         # логировать запросы дольше 1 сек
```
```ini
# pg_hba.conf
host    shop    app    10.0.0.0/24    scram-sha-256
```
```bash
sudo systemctl restart postgresql@16-main     # listen_addresses требует рестарта
```

Проверка снаружи:
```bash
pg_isready -h 10.0.0.5 -p 5432          # ⭐ готова ли база принимать соединения
psql -h 10.0.0.5 -U app -d shop -c '\conninfo'
ss -tlnp | grep 5432
```

---

## 6. Версии и обновления

```text:no-line-numbers
16.2
│  └── минорная: багфиксы и безопасность. Обновление = apt upgrade + restart.
│                Формат данных не меняется, откат простой.
└──── мажорная: 15 → 16. Формат данных меняется ⇒ нужен pg_upgrade или dump/restore.
```

| Способ мажорного апгрейда | Простой | Особенности |
|---------------------------|---------|-------------|
| `pg_dumpall` + restore | Долгий | Самый простой, годится для небольших баз |
| `pg_upgrade` | Короткий | Стандарт; с `--link` — минуты даже на больших базах |
| Логическая репликация | Почти нулевой | Сложнее, зато переключение почти без простоя |

```bash
# Debian/Ubuntu: типовой pg_upgrade между кластерами
sudo pg_dropcluster 16 main --stop            # новый пустой кластер 16 создаётся при установке
sudo pg_upgradecluster 15 main                # перенос 15 → 16
sudo pg_lsclusters                            # проверить, что новый online
```

Правила апгрейда, которые спасают:
1. Сначала **бэкап** и проверка восстановления.
2. Прогнать на копии прода, замерить время.
3. Читать release notes на несовместимости.
4. Старый кластер не удалять сразу — оставить как быстрый откат.

---

## 7. Типовые грабли установки

| Симптом | Причина | Решение |
|---------|---------|---------|
| `could not connect to server: No such file or directory` | Сервис не запущен / другой сокет | `pg_lsclusters`, `systemctl status` |
| Подключение с другого хоста: `Connection refused` | `listen_addresses = localhost` | Поправить + **restart** |
| `no pg_hba.conf entry for host` | Нет правила в `pg_hba.conf` | Добавить строку + `reload` (тема 03) |
| `FATAL: password authentication failed` | Пароль/метод не совпадают | `\password`, `scram-sha-256` |
| Данные пропали после пересоздания контейнера | Нет volume | `-v pgdata:/var/lib/postgresql/data` |
| `initdb: could not create directory` | Права на каталог | Владелец `postgres`, `chmod 700` |
| База не стартует: `PG_VERSION mismatch` | Данные от другой мажорной версии | Поставить нужную версию бинарей / `pg_upgrade` |
| Кончилось место, база в read-only/остановилась | Рост `pg_wal` или данных | Разбираться с причиной, **не** чистить `pg_wal` |

---

## 💼 Как это в DevOps

- Установка почти всегда **автоматизирована**: роль Ansible (`geerlingguy.postgresql`
  или своя) ставит пакет из PGDG, кладёт конфиги шаблонами, заводит роли и базы.
  См. [раздел «Ansible»](/ansible/).
- Версия PostgreSQL фиксируется и **одинакова на всех окружениях** — иначе «на стейдже
  работает, на проде нет» и невозможна репликация между ними.
- Для базы почти всегда выделяют **отдельный диск/раздел** под PGDATA и часто отдельный —
  под `pg_wal` (разные диски = меньше конкуренции за IO и защита от «место кончилось»).
- `pg_isready` — стандартная проверка в healthcheck'ах Docker/k8s и в CI перед прогоном тестов.
- В Kubernetes базу ставят оператором (CloudNativePG, Zalando postgres-operator),
  который сам делает initdb, реплики, бэкапы и failover.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Список кластеров (Deb/Ubuntu) | `pg_lsclusters` |
| Старт/стоп/reload кластера | `pg_ctlcluster 16 main start\|stop\|reload` |
| Перечитать конфиг без разрыва | `SELECT pg_reload_conf();` |
| Узнать каталог данных | `SHOW data_directory;` |
| Узнать путь к конфигам | `SHOW config_file;` / `SHOW hba_file;` |
| Проверить, готова ли база | `pg_isready -h host -p 5432` |
| Зайти локально суперюзером | `sudo -u postgres psql` |
| Зайти по сети | `psql -h host -U user -d db` |
| Список баз / таблиц / ролей | `\l` / `\dt` / `\du` |
| Структура таблицы | `\d table` |
| Время выполнения запросов | `\timing` |
| Выполнить файл с остановкой на ошибке | `psql -f f.sql -v ON_ERROR_STOP=1` |
| Повторять запрос каждые N сек | `\watch N` |
| Создать второй кластер | `pg_createcluster 16 test --port 5433 --start` |
| Мажорный апгрейд (Deb/Ubuntu) | `pg_upgradecluster 15 main` |
| Пароль без ввода | `~/.pgpass` с правами `600` |

---

## 🧠 Что запомнить

1. «Кластер» в PostgreSQL — это один инстанс с одним PGDATA, а не несколько серверов.
2. Роли общие на кластер, базы и права — внутри кластера.
3. В проде ставят из PGDG и фиксируют одинаковую версию на всех окружениях.
4. Пути различаются по дистрибутивам — спрашивай у базы: `SHOW data_directory / config_file / hba_file`.
5. ⭐ Из `pg_wal/` ничего не удаляют руками, даже когда кончилось место.
6. `pg_hba.conf` и большинство параметров подхватываются по `reload`; `shared_buffers`,
   `max_connections`, `listen_addresses`, `port` — только `restart`.
7. `pg_settings.pending_restart` покажет, что ждёт перезапуска.
8. `psql` — рабочий инструмент: `\d`, `\du`, `\l`, `\timing`, `\watch`, `-At` для скриптов.
9. В докере база без `-v` теряет данные; init-скрипты выполняются только на пустом томе.
10. Минорное обновление — просто рестарт; мажорное — `pg_upgrade` после бэкапа и репетиции.

---

## Задачи

> Для блока C нужна VM (Ubuntu) **и** docker — часть заданий про пакетную установку.

---

### Блок A. Теория

**A1.** Что в PostgreSQL называют «кластером»? Чем это отличается от бытового значения слова?

<details><summary>Ответ</summary>

Кластер PostgreSQL — один инстанс СУБД: один каталог данных (PGDATA), один порт,
один набор процессов и все базы внутри. Это не «несколько серверов», как в обиходе.

</details>

**A2.** Роли в PostgreSQL общие для кластера или для базы? А права?

<details><summary>Ответ</summary>

Роли (пользователи) — общекластерные, хранятся в `global/`. Права выдаются на
объекты внутри конкретных баз и схем.

</details>

**A3.** Почему в проде ставят PostgreSQL из репозитория PGDG, а не из репозитория дистрибутива?

<details><summary>Ответ</summary>

В репозитории дистрибутива версия зафиксирована на момент релиза ОС и часто
устаревшая. PGDG даёт актуальные мажорные версии, свежие минорные патчи и одинаковые
версии на разных дистрибутивах — критично для репликации и предсказуемости.

</details>

**A4.** Где лежат `postgresql.conf` и `pg_hba.conf` в Ubuntu, в RHEL и в официальном
docker-образе? Как узнать это, не заглядывая в документацию?

<details><summary>Ответ</summary>

Ubuntu/Debian — `/etc/postgresql/16/main/`; RHEL и docker — внутри PGDATA
(`/var/lib/pgsql/16/data`, `/var/lib/postgresql/data`). Узнать правильнее через SQL:
`SHOW config_file;`, `SHOW hba_file;`, `SHOW data_directory;`.

</details>

**A5.** Что лежит в `pg_wal/` и почему оттуда нельзя ничего удалять руками?

<details><summary>Ответ</summary>

Журнал предзаписи (WAL): сегменты по 16 МБ с записями всех изменений. На них
держатся восстановление после сбоя, репликация и PITR. Удаление файлов вручную ломает
консистентность — база может не подняться и данные будут потеряны.

</details>

**A6.** Чем `reload` отличается от `restart`? Приведи по три параметра на каждый случай.

<details><summary>Ответ</summary>

`reload` перечитывает конфиги без разрыва соединений: `pg_hba.conf`,
`log_min_duration_statement`, `work_mem`, `autovacuum_*`. `restart` нужен для параметров
с `context = postmaster`: `shared_buffers`, `max_connections`, `listen_addresses`, `port`,
`wal_level`.

</details>

**A7.** Как узнать, какие параметры ждут перезапуска?

<details><summary>Ответ</summary>

`SELECT name, setting, pending_restart FROM pg_settings WHERE pending_restart;`

</details>

**A8.** Что делает `pg_lsclusters` и что означает каждая колонка вывода?

<details><summary>Ответ</summary>

Список кластеров в Debian/Ubuntu: версия, имя кластера, порт, статус
(online/down), владелец, каталог данных, файл лога.

</details>

**A9.** Зачем на одном сервере может понадобиться два кластера PostgreSQL?

<details><summary>Ответ</summary>

Разные версии PostgreSQL рядом (для апгрейда), изоляция окружений (dev/test),
разные настройки под разные нагрузки на одном хосте (в проде так делают редко).

</details>

**A10.** Что произойдёт с данными, если запустить официальный образ postgres без `-v`?

<details><summary>Ответ</summary>

Данные окажутся в слое контейнера и исчезнут вместе с ним (`docker rm`).
Плюс производительность записи хуже.

</details>

**A11.** Когда выполняются скрипты из `/docker-entrypoint-initdb.d/`? Почему добавленный
позже скрипт «не работает»?

<details><summary>Ответ</summary>

Только при первой инициализации **пустого** PGDATA. Если том уже содержит базу,
entrypoint пропускает init-скрипты. Чтобы применить новый скрипт — пересоздать том
(в dev) или выполнить SQL вручную/миграцией.

</details>

**A12.** Чем минорное обновление отличается от мажорного? Какие есть способы мажорного?

<details><summary>Ответ</summary>

Минорное (16.2 → 16.3) — те же форматы данных, обновил пакет и перезапустил.
Мажорное (15 → 16) — меняется формат: `pg_dumpall`+restore, `pg_upgrade`
(в Debian — `pg_upgradecluster`) или логическая репликация с переключением.

</details>

**A13.** Что такое `pg_isready` и где его применяют?

<details><summary>Ответ</summary>

Утилита, проверяющая, принимает ли база соединения (коды возврата 0/1/2).
Применяют в healthcheck докера и k8s, в CI перед прогоном тестов, в скриптах ожидания.

</details>

**A14.** Что такое `~/.pgpass`, какие у него должны быть права и зачем он нужен?

<details><summary>Ответ</summary>

Файл с паролями в формате `host:port:db:user:password`, права строго `600`
(иначе игнорируется). Позволяет не хранить пароль в командной строке и переменных.

</details>

**A15.** ⭐ Зачем базе отдельный диск под PGDATA и иногда отдельный под `pg_wal`?

<details><summary>Ответ</summary>

Отдельный диск изолирует базу от «кто-то залил логи и место кончилось»,
даёт предсказуемый IO и возможность отдельно снимать снапшоты. Отдельный диск под `pg_wal`
разводит последовательную запись журнала и случайный ввод-вывод данных — это заметно
повышает производительность записи.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  sudo -u postgres psql -c "SELECT version();"
B2.  pg_lsclusters
B3.  sudo pg_ctlcluster 16 main reload
B4.  sudo systemctl restart postgresql@16-main
B5.  pg_isready -h 10.0.0.5 -p 5432
B6.  psql -At -c "SELECT count(*) FROM pg_stat_activity;"
B7.  psql -f migration.sql -v ON_ERROR_STOP=1
B8.  sudo pg_createcluster 16 test --port 5433 --start
B9.  sudo pg_upgradecluster 15 main
B10. docker run -d -e POSTGRES_PASSWORD=x -v pgdata:/var/lib/postgresql/data postgres:16
```

```sql
B11. SHOW data_directory;
B12. SELECT name, setting, pending_restart FROM pg_settings WHERE pending_restart;
B13. SELECT pg_reload_conf();
B14. \watch 2
```

<details><summary>Ответ</summary>

**B1.** Подключается локально суперпользователем через peer и печатает версию сервера.
**B2.** Показывает все кластеры Debian/Ubuntu: версию, порт, статус, PGDATA, лог.
**B3.** Перечитывает конфиги кластера 16/main без разрыва соединений.
**B4.** Полный перезапуск инстанса, все соединения рвутся.
**B5.** Проверяет доступность базы по сети (для healthcheck/скриптов).
**B6.** Возвращает «голое» число соединений без рамок и заголовка — удобно для мониторинга.
**B7.** Выполняет SQL-файл и **останавливается на первой ошибке** — обязательный флаг в CI,
иначе миграция «успешно» проедет мимо ошибок.
**B8.** Создаёт второй кластер PostgreSQL 16 с именем test на порту 5433 и запускает его.
**B9.** Переносит кластер с версии 15 на установленную 16 (мажорный апгрейд).
**B10.** Поднимает postgres с именованным томом — данные переживут пересоздание контейнера.
**B11.** Показывает каталог данных.
**B12.** Показывает параметры, изменённые в конфиге, но требующие рестарта.
**B13.** То же, что `reload`, но из SQL.
**B14.** Повторяет последний запрос каждые 2 секунды — живой мониторинг из psql.

</details>

---

### Блок C. Практика

#### C1. 🔑 Установка из PGDG
1. Подключи репозиторий PGDG на Ubuntu-VM и поставь `postgresql-16`.
2. Проверь: `pg_lsclusters`, `systemctl status postgresql@16-main`, `SELECT version();`
3. Выясни через SQL: где данные, где `postgresql.conf`, где `pg_hba.conf`.

<details><summary>Ответ</summary>

Ожидаемый вывод `pg_lsclusters`: `16 main 5432 online postgres /var/lib/postgresql/16/main …`

</details>

#### C2. Осмотр PGDATA
```bash
sudo du -sh /var/lib/postgresql/16/main/*
sudo ls /var/lib/postgresql/16/main/
```
Опиши назначение `base/`, `global/`, `pg_wal/`, `PG_VERSION`, `postmaster.pid`.

<details><summary>Ответ</summary>

`base/` — файлы данных по базам; `global/` — общекластерные каталоги, в т.ч. роли;
`pg_wal/` — журнал; `PG_VERSION` — мажорная версия; `postmaster.pid` — pid и параметры
работающего инстанса (по нему база понимает, что уже запущена).

</details>

#### C3. reload vs restart
1. Поменяй `log_min_duration_statement = 500` → примени `reload`, проверь `SHOW`.
2. Поменяй `shared_buffers` → сделай `reload`, посмотри `pending_restart`.
3. Сделай `restart` и убедись, что значение применилось.

<details><summary>Ответ</summary>

`log_min_duration_statement` применяется по reload сразу; `shared_buffers`
после reload появится в `pending_restart = t` и применится только после restart.

</details>

#### C4. Логи базы
1. Включи `logging_collector`, задай `log_line_prefix = '%m [%p] %u@%d '`.
2. Найди файл лога, сделай заведомо ошибочный запрос, найди его в логе.
3. В docker-варианте — то же самое через `docker logs`.

<details><summary>Ответ</summary>

В Ubuntu лог — `/var/log/postgresql/postgresql-16-main.log`. Префикс `%m [%p] %u@%d`
даёт время, pid, пользователя и базу — без этого разбор инцидента почти невозможен.

</details>

#### C5. Первая настройка «под приложение»
Создай роль `app`, базу `shop` с владельцем `app`, зайди под `app`, создай таблицу.
Проверь через `\du` и `\l`, что всё как задумано.

<details><summary>Ответ</summary>

`\du` покажет роль `app` с атрибутом Login, `\l` — базу `shop` с владельцем `app`.

</details>

#### C6. Второй кластер
1. `pg_createcluster 16 test --port 5433 --start`
2. Подключись к нему, создай базу, убедись, что кластеры независимы.
3. Удали: `pg_dropcluster 16 test --stop`. Что происходит с данными?

<details><summary>Ответ</summary>

`pg_dropcluster --stop` удаляет и каталог данных — данные теряются безвозвратно.

</details>

#### C7. Docker: данные и init-скрипты
1. Подними postgres **без** volume, создай таблицу, удали контейнер, подними заново — проверь.
2. Повтори с именованным volume.
3. Положи `init.sql` в `/docker-entrypoint-initdb.d/` и проверь, что он отработал
   только на пустом томе.

<details><summary>Ответ</summary>

Без volume таблица исчезнет; с volume — сохранится. Init-скрипт отработает только
на пустом томе (в логах видно `running /docker-entrypoint-initdb.d/init.sql`).

</details>

#### C8. `psql` как инструмент
Освой на своей базе: `\l+`, `\dt+`, `\d table`, `\du`, `\x`, `\timing`, `\conninfo`,
`\i file.sql`, `\watch 2`. Запиши пять самых полезных лично тебе.

<details><summary>Ответ</summary>

Чаще всего в работе нужны `\d`, `\du`, `\l+`, `\x`, `\timing`, `\watch`.

</details>

#### C9. `.pgpass` и подключение по сети
1. Открой базу наружу (`listen_addresses`, `pg_hba.conf` — забегая в тему 03).
2. С другой машины подключись с паролем, потом настрой `~/.pgpass` и подключись без ввода.
3. Проверь права файла и что будет, если поставить `644`.

<details><summary>Ответ</summary>

С правами `644` psql выведет предупреждение и проигнорирует `.pgpass` —
пароль будет спрошен.

</details>

#### C10. Мажорный апгрейд (со звёздочкой)
На тестовой VM: поставь PG 15, налей данные, затем поставь 16 и сделай
`pg_upgradecluster 15 main`. Замерь время, проверь данные, опиши план отката.

<details><summary>Ответ</summary>

План отката: старый кластер 15 остаётся на месте (`pg_upgradecluster` его не
удаляет) — при проблемах поднимаешь его обратно на нужном порту.

</details>

---

### Блок D. Инциденты

**D1.** `psql: could not connect to server: No such file or directory`. Причины и проверки.

<details><summary>Ответ</summary>

Сервис не запущен, другой сокет/порт, не тот `-h`, нет прав на сокет.
Проверить `pg_lsclusters`, `systemctl status`, `ss -tlnp | grep 5432`, логи.

</details>

**D2.** С сервера приложения: `Connection refused` на 5432, локально всё работает. Что не так?

<details><summary>Ответ</summary>

`listen_addresses = 'localhost'` (нужен restart после правки), либо firewall/secgroup,
либо нет строки в `pg_hba.conf` — но тогда ошибка была бы другая (`no pg_hba.conf entry`).

</details>

**D3.** `FATAL: the database system is starting up` — база долго стартует после сбоя питания.
Что происходит и можно ли ускорить?

<details><summary>Ответ</summary>

Идёт восстановление по WAL после некорректной остановки. Процесс прерывать нельзя.
Ускорить постфактум нельзя; на будущее — уменьшают объём восстановления
(`checkpoint_timeout`, `max_wal_size`) и следят за корректной остановкой.

</details>

**D4.** База не стартует, в логе `PG_VERSION` mismatch / `incompatible data directory`. Причина?

<details><summary>Ответ</summary>

Каталог данных создан другой мажорной версией. Нужно поставить бинарники той версии
и сделать `pg_upgrade`, а не «подсунуть» данные новой версии.

</details>

**D5.** На диске с базой осталось 2% места. Твои действия по шагам (и чего делать нельзя).

<details><summary>Ответ</summary>

Посмотреть, что растёт (`du -sh` по PGDATA, `pg_wal`, логам), проверить неактивные
слоты репликации и `archive_command`, вынести логи и старые бэкапы, при необходимости
расширить диск. **Нельзя** удалять файлы из `pg_wal/` руками.

</details>

**D6.** Коллега «почистил» `pg_wal`, база не поднимается. Что произошло и что теперь делать?

<details><summary>Ответ</summary>

Удалены сегменты журнала, нужные для восстановления. База не может доиграть WAL.
Решение — восстановление из бэкапа (и это тот случай, когда бэкап спасает работу).

</details>

**D7.** После правки `postgresql.conf` изменения не применились. Что проверишь?

<details><summary>Ответ</summary>

Правился не тот файл (в Debian конфиг в `/etc`), не сделан reload/restart,
параметр требует рестарта, либо значение переопределено в `ALTER SYSTEM`
(`postgresql.auto.conf`) — проверить `SELECT name, setting, source, sourcefile FROM pg_settings`.

</details>

**D8.** В docker-compose разработчики добавили новый init-скрипт, но он «не выполняется».
Объясни причину и дай рабочее решение.

<details><summary>Ответ</summary>

Том уже инициализирован — init-скрипты пропускаются. В dev: `docker compose down -v`.
В общем случае — применять изменения миграциями, а не init-скриптами.

</details>

**D9.** На стейдже PG 14, на проде PG 16. Какие проблемы это создаёт?

<details><summary>Ответ</summary>

Разное поведение планировщика и синтаксиса, «на стейдже работает — на проде нет»,
невозможность физической репликации и переноса PGDATA, разные баги. Версии должны совпадать.

</details>

**D10.** После установки база слушает только localhost, а приложение в другом сегменте.
Опиши полный путь решения: что поменять и что перезапустить.

<details><summary>Ответ</summary>

`listen_addresses` в `postgresql.conf` → **restart**; правило в `pg_hba.conf`
для подсети приложения → **reload**; открыть порт в firewall/secgroup; проверить
`pg_isready` и `psql` с хоста приложения.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое кластер в PostgreSQL?

<details><summary>Ответ</summary>

Один инстанс СУБД: PGDATA, порт, процессы и все базы внутри; роли общие на кластер.

</details>

**2.** Как поставить PostgreSQL нужной версии на Ubuntu?

<details><summary>Ответ</summary>

Подключить репозиторий PGDG и `apt install postgresql-16`; в проде — Ansible-ролью.

</details>

**3.** Где лежат конфиги и данные PostgreSQL?

<details><summary>Ответ</summary>

Данные — PGDATA; конфиги в Ubuntu — `/etc/postgresql/<ver>/<cluster>/`, в RHEL/docker —
внутри PGDATA; точный ответ даёт `SHOW config_file;`.

</details>

**4.** Чем reload отличается от restart и какие параметры требуют рестарта?

<details><summary>Ответ</summary>

reload — без разрыва соединений (`pg_hba.conf`, логирование, autovacuum);
restart — для `shared_buffers`, `max_connections`, `listen_addresses`, `port`, `wal_level`.

</details>

**5.** Что такое `pg_wal` и почему его нельзя чистить руками?

<details><summary>Ответ</summary>

Журнал предзаписи; на нём держатся восстановление, репликация и PITR — ручное удаление
ломает базу.

</details>

**6.** Как проверить, что база доступна, из скрипта?

<details><summary>Ответ</summary>

`pg_isready -h host -p port` (или `psql -c 'SELECT 1'` с `-At`).

</details>

**7.** Как обновить PostgreSQL с 15 до 16?

<details><summary>Ответ</summary>

`pg_upgrade`/`pg_upgradecluster` после бэкапа и репетиции на копии; для минимального
простоя — логическая репликация.

</details>

**8.** Как запустить две базы на одном сервере?

<details><summary>Ответ</summary>

Создать второй кластер на другом порту (`pg_createcluster`) или запустить второй
контейнер с другим томом и портом.

</details>

**9.** Что происходит с данными контейнера postgres без volume?

<details><summary>Ответ</summary>

Данные живут в слое контейнера и удаляются вместе с ним.

</details>

**10.** Какие первые пять вещей ты настроишь после установки PostgreSQL?

<details><summary>Ответ</summary>

Пароль суперпользователя, роль и база под приложение, `listen_addresses`,
`pg_hba.conf`, память (`shared_buffers`), логирование, бэкапы и мониторинг.

</details>

---

### 🎯 Чек-лист

- [ ] Поставил PostgreSQL из PGDG и из докера, вижу разницу в путях
- [ ] Объясняю, что такое кластер PostgreSQL
- [ ] Нахожу PGDATA и конфиги через SQL, а не по памяти
- [ ] Знаю, что reload хватает для `pg_hba.conf`, а `shared_buffers` требует restart
- [ ] Умею смотреть `pending_restart`
- [ ] ⭐ Понимаю, почему `pg_wal` нельзя чистить руками
- [ ] Свободно пользуюсь `psql`: `\d`, `\du`, `\l`, `\timing`, `\watch`, `-At`
- [ ] Знаю разницу минорного и мажорного обновления и сделал `pg_upgradecluster` на стенде
- [ ] Настроил `.pgpass` с правами 600
