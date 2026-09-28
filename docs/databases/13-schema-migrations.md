---
title: "13. Миграции схемы"
description: "Как менять схему базы без простоя: инструменты, expand/contract, блокировки, откаты, тесты в CI, Helm-хуки"
---

# 13. Миграции схемы: как менять базу без простоя

> Вне роадмапа → Базы + CI/CD → **миграции схемы**. В CI/CD-блоке идея expand/contract
> дана коротко ([CI/CD: проектирование пайплайна](/cicd/03-pipeline-design) §6) —
> здесь глубина: инструменты, где запускать, блокировки, откаты, тесты.
>
> **После темы ты умеешь:** выбрать инструмент миграций, встроить миграции в пайплайн
> и в Kubernetes так, чтобы они не гонялись друг с другом, переименовать колонку без
> простоя за три релиза, не повесить прод долгим `ALTER` и объяснить стратегию отката.
>
> 📅 Версии и лицензии инструментов — **проверь, сентябрь 2026**.

---

## 🗺️ Карта: миграция в жизни релиза

```text:no-line-numbers
 git push ──► CI: тест миграций на пустой базе и на копии схемы прода, линтер
                │
                ▼
         ┌──────────────────────────────────┐   одна за раз (блокировка/resource_group)
         │ migrate: V7 → V8 (роль-владелец)  │   lock_timeout, бэкап/точка восстановления
         └──────────────┬───────────────────┘
                        ▼
         rolling update:  старые поды (код N) ─┐
                          новые поды (код N+1) ─┴─► ОДНОВРЕМЕННО работают со схемой V8 ⭐
                        │
                        ▼
         через релиз-два: contract — удалить то, что больше никто не использует
```

**Главная мысль:** схема базы — это общий ресурс для **двух версий кода сразу**.
Любая миграция должна быть совместима и со старым кодом, и с новым.

---

## 1. Почему миграции — забота DevOps

| Разработчик | DevOps |
|-------------|--------|
| Пишет миграцию (SQL/ORM) | Решает, **где и когда** она запускается |
| Проверяет, что код работает с новой схемой | Гарантирует, что миграция запустится **один раз**, а не N раз из N подов |
| — | Доступ: роль-владелец для миграций, роль без DDL для приложения ([03. Доступ через pg_hba.conf](/databases/03-pg-hba-access)) |
| — | Таймауты и блокировки: миграция не должна повесить прод |
| — | Бэкап/точка восстановления до миграции, план отката |
| — | Наблюдаемость: логи миграции, алерт на упавший job, лаг реплик |

Большая доля «релиз уронил прод» — это не код, а миграция: `ALTER TABLE` встал в очередь
блокировок, `DROP COLUMN` выкатили раньше кода, индекс строился час на большой таблице.

---

## 2. Как устроен инструмент версионных миграций

```text:no-line-numbers
db/migrations/
  V1__init.sql
  V2__add_hits_index.sql
  V3__add_target_url.sql      ← новая, ещё не применена

  таблица истории в самой базе (flyway_schema_history / alembic_version /
  schema_migrations / DATABASECHANGELOG):
  ┌─────────┬──────────────────────┬────────────┬─────────┐
  │ version │ description          │ checksum   │ success │
  │ 1       │ init                 │ 1a2b…      │ true    │
  │ 2       │ add hits index       │ 9f8e…      │ true    │
  └─────────┴──────────────────────┴────────────┴─────────┘
```
1. Берёт **блокировку** (чтобы два запуска не применяли одно и то же одновременно).
2. Сравнивает файлы с таблицей истории, проверяет **контрольные суммы** уже применённых.
3. Применяет недостающие по порядку, каждую записывает в историю.

Правила, которые из этого следуют:
- **Применённую миграцию не редактируют** — меняется checksum, `validate` падает.
  Ошибся — пиши новую миграцию.
- Миграции — в том же репозитории и том же образе/артефакте, что и код версии.
- Порядок версий один на всех: две ветки с `V8__…` = конфликт, решается при merge.

---

## 3. Инструменты

| Инструмент | Язык / формат | Откат | Блокировка | Статус (сентябрь 2026) |
|------------|---------------|-------|-----------|------------------------|
| **Flyway** (Redgate) | SQL-файлы `V3__name.sql`, Java-миграции; CLI, Docker, Maven/Gradle | `undo` — только в платной Enterprise | advisory lock (PG), `GET_LOCK` (MySQL) | 13.x (13.8.0 от 24.09.2026); Community бесплатна; нужна Java 17+ |
| **Liquibase** | changelog: SQL, XML, YAML, JSON; changeset-ы | ✅ `rollback` встроен | таблица `DATABASECHANGELOGLOCK` | ⚠️ с 5.0 (09.2025) Community под **FSL**, не Apache 2.0; 5.0.4 (08.2026) |
| **Alembic** | Python, поверх SQLAlchemy; autogenerate из моделей | `downgrade` | ❌ своей нет | 1.20.0 (09.2026), Python ≥ 3.10, SQLAlchemy 2.x |
| **golang-migrate** | Пары `000003_x.up.sql` / `.down.sql`; CLI и Go-библиотека | `down` | advisory lock / `GET_LOCK` | v4.20.1 (09.2026) |
| **Atlas** (Ariga) | Декларативно (HCL/SQL/ORM-схема) **и** версионно; `migrate lint` | Через новую миграцию | Есть | v1.3.0 (08.2026); обычный бинарь под EULA, Community-сборка — Apache 2.0 |

Кратко по выбору:
- **Язык проекта решает**: Python — Alembic, Go — golang-migrate/goose/Atlas,
  Java/Spring — Flyway/Liquibase, Django/Rails/Prisma/EF Core — встроенные миграции ORM.
- **Flyway** — «просто SQL-файлы по порядку», самый понятный для DevOps; платные фичи
  (undo, drift, генерация скриптов) большинству не нужны.
- **Liquibase** — сильна в энтерпрайзе и мультибазовых продуктах. Про FSL: использовать
  у себя в проде можно, запрещено делать конкурирующий коммерческий продукт; через 2 года
  каждая версия переходит в Apache 2.0. Часть проектов (например, Keycloak, фонд Apache)
  из-за этого пересматривала зависимость. Community 5.x идёт **без драйверов и расширений** —
  их ставят отдельно.
- **Atlas** — если нравится подход «как Terraform» для схемы и нужен линтер опасных миграций.
  Бесплатный тариф урезан (`migrate lint` с v0.38 не входит в free-план, но есть
  в Community-сборке).

---

## 4. Версионный vs декларативный подход

```text:no-line-numbers
ВЕРСИОННЫЙ (Flyway, Alembic, golang-migrate)   ДЕКЛАРАТИВНЫЙ (Atlas schema apply, Skeema)
───────────────────────────────────────────    ─────────────────────────────────────────
«Вот шаги: V1, V2, V3»                          «Вот желаемая схема — посчитай разницу»
+ ревьюишь ровно тот SQL, что поедет в прод     + нет истории скриптов, схема читается целиком
+ контроль над порядком и батчами данных        + дрейф (ручные правки в проде) виден сразу
− дрейф прода от истории незаметен              − переименование = DROP + ADD → потеря данных ⚠️
− длинная история, медленный старт с нуля       − миграции данных (backfill) не выражаются
```
Практичный гибрид: схема описывается декларативно, а инструмент **генерирует версионный
файл** (`atlas migrate diff`, `alembic revision --autogenerate`), который проходит ревью
и едет как обычная версионная миграция. Автогенерацию **всегда читают глазами**: ORM
не отличает переименование от «удалить и создать».

---

## 5. Где запускать миграции ⭐

| Где | Плюсы | Минусы |
|-----|-------|--------|
| **Приложение на старте** (`auto-migrate`, Spring Boot + Flyway) | Ноль инфраструктуры | N подов гонятся за блокировку; приложению нужны права DDL; долгая миграция → liveness-проба убивает под посреди `ALTER` |
| **init container** в поде | Запускается «сам» с каждым деплоем | То же «N раз», rollout стоит, пока идёт миграция; при масштабировании снова запускается |
| **Отдельный job в CI** до деплоя | Явный шаг, логи, пайплайн останавливается при ошибке | Раннеру нужен сетевой доступ к базе и секреты владельца |
| **k8s Job** из пайплайна (`kubectl wait`) | Запускается рядом с базой, тем же образом | Нужна обвязка в пайплайне ([Kubernetes: Job и CronJob](/kubernetes/07-job-cronjob) §4) |
| **Helm pre-upgrade hook** | Миграция — часть релиза | Упал хук → упал релиз; секреты должны существовать до хука ([Kubernetes: Helm](/kubernetes/15-helm) §8) |
| **ArgoCD PreSync hook** | GitOps: миграция перед синхронизацией манифестов | Логи и повторы — через интерфейс ArgoCD |

Разумный выбор по умолчанию:
- **Есть k8s + Helm/ArgoCD** → Job-хук (`pre-upgrade` / `PreSync`), тот же образ, что у приложения,
  роль-владелец из отдельного секрета. ArgoCD сам превращает Helm-хуки `pre-install/pre-upgrade`
  в `PreSync`.
- **VM / docker compose** → отдельный job в CI (или шаг Ansible) перед выкаткой кода.
- **Приложение на старте** — только когда инстанс один и миграции гарантированно быстрые.

**Блокировка обязательна при любом варианте.** Flyway, golang-migrate, Liquibase, Atlas
берут её сами; у Alembic её нет — запускай ровно один раз (Job/CI) или оборачивай
в `pg_advisory_lock`. В GitLab два пайплайна подряд не запустят миграции одновременно,
если у job есть `resource_group`.

---

## 6. Совместимость с rolling update

Во время rolling update **старый и новый код одновременно** работают с одной схемой.
Если миграция идёт до деплоя, то схема N+1 должна быть совместима с кодом N;
а откат кода N+1 → N не должен требовать отката схемы.

| Изменение | Безопасно за один релиз? | Как правильно |
|-----------|--------------------------|---------------|
| Добавить таблицу / nullable-колонку | ✅ | Просто миграция |
| Добавить колонку `NOT NULL DEFAULT …` | ✅ PG 11+ и MySQL 8.0 INSTANT — мгновенно | Проверить версию базы |
| Добавить индекс | ✅, но… | PG — `CONCURRENTLY`, MySQL — online DDL (§8) |
| **Переименовать** колонку/таблицу | ❌ старый код сломается мгновенно | expand/contract (§7) |
| **Удалить** колонку/таблицу | ❌ если код N её читает | Сначала релиз кода без неё, потом `DROP` |
| Сменить тип колонки | ❌ часто переписывает таблицу | Новая колонка + backfill + переключение |
| Добавить `NOT NULL` к существующей | ⚠️ полный скан под блокировкой | `CHECK … NOT VALID` → `VALIDATE` → `SET NOT NULL` |
| Добавить FK / `UNIQUE` | ⚠️ скан и блокировки, падение на «грязных» данных | `NOT VALID` + `VALIDATE`; уникальный индекс `CONCURRENTLY` |

> 💡 Отдельная ловушка ORM: часть фреймворков кэширует список колонок или делает
> `SELECT *` / `INSERT` по всем полям модели. Код N, «не знающий» о новой `NOT NULL`
> колонке без default, упадёт на вставке.

---

## 7. Expand/contract на примере linkd: `url` → `target_url` за 3 релиза

У linkd 2.0 таблица `links (code, url, created_at, hits)`. Команда хочет переименовать
`url` в `target_url`. `ALTER TABLE links RENAME COLUMN url TO target_url` — мгновенная
операция, но **все поды со старым кодом начнут падать в ту же секунду**. Делаем в три релиза.

### Релиз A — expand (добавить новое, ничего не ломать)

```sql
-- V3__links_add_target_url.sql   (быстро: nullable-колонка без переписывания)
ALTER TABLE links ADD COLUMN target_url TEXT;

-- триггер: старые поды (2.0) во время rollout пишут только url
CREATE FUNCTION links_sync_target_url() RETURNS trigger AS $$
BEGIN
  IF NEW.target_url IS NULL THEN NEW.target_url := NEW.url; END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER links_sync BEFORE INSERT OR UPDATE ON links
  FOR EACH ROW EXECUTE FUNCTION links_sync_target_url();
```
Код A: **пишет в обе** колонки, читает `COALESCE(target_url, url)`.
После выката — **backfill пачками** (отдельный job, не в транзакции миграции):
```sql
UPDATE links SET target_url = url
WHERE code IN (SELECT code FROM links WHERE target_url IS NULL LIMIT 5000);
-- повторять, пока UPDATE 0; пауза между пачками — чтобы не душить реплики и autovacuum
```

### Релиз B — switch (переключить чтение и запись на новое)

```sql
-- V4__links_target_url_not_null.sql
ALTER TABLE links ALTER COLUMN url DROP NOT NULL;           -- код B в url не пишет
ALTER TABLE links ADD CONSTRAINT target_url_nn CHECK (target_url IS NOT NULL) NOT VALID;
ALTER TABLE links VALIDATE CONSTRAINT target_url_nn;        -- скан без блокировки записи
ALTER TABLE links ALTER COLUMN target_url SET NOT NULL;     -- PG 12+: по CHECK, без скана
ALTER TABLE links DROP CONSTRAINT target_url_nn;
```
Код B: читает и пишет **только** `target_url`; колонка `url` из кода и ORM-моделей убрана.
Если backfill не закончен, V4 упадёт на `VALIDATE` — это встроенная страховка.

### Релиз C — contract (убрать старое)

```sql
-- V5__links_drop_url.sql   (только когда B стабилен и откат на A больше не нужен)
DROP TRIGGER links_sync ON links;
DROP FUNCTION links_sync_target_url();
ALTER TABLE links DROP COLUMN url;
```

### Проверка совместимости: кто с какой схемой работает

| Момент | Схема | Работают поды | Всё ок? |
|--------|-------|---------------|---------|
| Rollout A | V3 | 2.0 (пишет `url`) + A (пишет оба) | ✅ триггер заполняет `target_url` за 2.0 |
| Откат A → 2.0 | V3 | 2.0 | ✅ новая колонка ему не мешает |
| Rollout B | V4 | A (оба) + B (только `target_url`) | ✅ `url` уже nullable, A читает `COALESCE` |
| Откат B → A | V4 | A | ✅ |
| Rollout C | V5 | B + C | ✅ оба не трогают `url` |
| Откат C → B | V5 | B | ✅ — а вот откат до **A** уже невозможен (осознанно) |

Цена — три релиза и немного кода «на два фронта». Плата за нулевой простой и за то,
что **любой шаг можно откатить кодом, не трогая схему**.

---

## 8. Долгие миграции и блокировки

### PostgreSQL: очередь блокировок

```text:no-line-numbers
 долгий SELECT (отчёт, 10 мин) ── держит ACCESS SHARE на links
 ALTER TABLE links ...          ── ждёт ACCESS EXCLUSIVE        ⏳
 все новые SELECT/INSERT        ── встают в очередь ЗА ALTER    ⏳⏳⏳  → сайт лежит
```
Даже мгновенный `ALTER` (добавить nullable-колонку) вешает прод, если ждёт блокировку.

```sql
SET lock_timeout = '5s';          -- ⭐ не дождался блокировки — упади, а не вешай всех
SET statement_timeout = '15min';  -- страховка от бесконечной миграции
```
Миграцию, упавшую по `lock_timeout`, **повторяют** (инструмент/пайплайн с ретраями) —
это нормально. Передать таймауты всем миграциям: `PGOPTIONS='-c lock_timeout=5s'`
для libpq-клиентов (Alembic/psycopg) или `initSql` во Flyway.

| Операция | Проблема | Безопасный вариант |
|----------|----------|--------------------|
| `CREATE INDEX` | Блокирует запись на всё время построения | `CREATE INDEX CONCURRENTLY` — **вне транзакции**; упал → остаётся `INVALID`-индекс, удалить и повторить |
| `ADD COLUMN … DEFAULT` | До PG 11 переписывал таблицу | PG 11+ мгновенно (нестабильный default вроде `random()` — всё ещё переписывает) |
| `SET NOT NULL` | Полный скан под `ACCESS EXCLUSIVE` | `CHECK … NOT VALID` → `VALIDATE` → `SET NOT NULL` (§7) |
| `ADD FOREIGN KEY` | Скан обеих таблиц с блокировками | `… NOT VALID`, затем `VALIDATE CONSTRAINT` |
| `ALTER COLUMN TYPE` | Переписывание таблицы | Новая колонка + backfill + переключение |
| Большой `UPDATE` | Раздувание, лаг реплик, долгие блокировки строк | Пачками по тысячи строк, отдельным job-ом |

`CONCURRENTLY` и транзакции: Flyway сам выполняет такой скрипт вне транзакции (не смешивай
в одном файле с другими командами), в Alembic — `op.get_context().autocommit_block()`
и `postgresql_concurrently=True`, в golang-migrate — отдельный файл с одной командой.

### MySQL: online DDL и внешние инструменты

DDL в MySQL **не транзакционный** ([12. MySQL и MariaDB](/databases/12-mysql)): упавшая посередине миграция
оставляет базу в промежуточном состоянии — Flyway пометит её failed (`flyway repair`
после ручной уборки), golang-migrate — `dirty` (`migrate force <версия>`).

```sql
ALTER TABLE links ADD COLUMN target_url TEXT, ALGORITHM=INSTANT;       -- 8.0.29+: и DROP COLUMN
ALTER TABLE links ADD INDEX ix_created (created_at), ALGORITHM=INPLACE, LOCK=NONE;
SET SESSION lock_wait_timeout = 5;   -- аналог lock_timeout: metadata lock ждём не вечно
```
Указывай `ALGORITHM`/`LOCK` явно: если так нельзя, MySQL **вернёт ошибку**, а не молча
скопирует таблицу с блокировкой. Та же очередь блокировок существует и здесь
(`Waiting for table metadata lock`). И ещё одна ловушка: DDL на реплике выполняется
**после** primary и столько же времени — час `ALTER` = час лага реплики.

| Инструмент | Как работает | Особенности |
|------------|--------------|-------------|
| **gh-ost** (GitHub) | Теневая копия таблицы, изменения догоняет **по binlog**, без триггеров; атомарная подмена | Троттлинг по лагу реплик, пауза/отмена на ходу; v1.1.11 (08.2026), поддерживает MySQL 8.4 |
| **pt-online-schema-change** (Percona Toolkit) | Теневая копия + **триггеры** на исходной таблице | Проще, но триггеры добавляют нагрузку на запись |

---

## 9. Откаты: forward-fix или down-миграции

```text:no-line-numbers
 Сломалось после релиза с миграцией
        │
        ├─ код откатываем ВСЕГДА можно ── потому что схема совместима (expand/contract)
        │
        └─ схему: ⭐ forward-fix — новая миграция V9, исправляющая V8
                  down-миграция    — только если она реально протестирована и
                                     не теряет данные
                  восстановление   — крайний случай: PITR / restore point (тема 05)
```

Почему «down» часто обман: `DROP COLUMN` в down-миграции для `ADD COLUMN` удаляет
данные, записанные за время работы нового кода; down для `DROP COLUMN` не вернёт данные
вообще. У Flyway `undo` есть только в платной редакции — и это нормально: в проде
принято чинить **вперёд**.

Перед рискованной миграцией:
- свежий проверенный бэкап и точка восстановления: `SELECT pg_create_restore_point('before_V8');`
  ([05. Backup / Restore](/databases/05-backup-restore));
- замер длительности на копии прода;
- план «что делаем, если упала посередине» — особенно для MySQL.

---

## 10. Тестирование миграций в CI

| Проверка | Что ловит |
|----------|-----------|
| Применить все миграции на **пустую** базу (service-контейнер `postgres:17`) | Синтаксис, порядок, зависимости |
| `flyway validate` / `alembic check` / `atlas migrate validate` | Изменённые применённые файлы, дрейф моделей от миграций |
| Применить новые миграции на **копии схемы прода** (обезличенный дамп) | Падения на реальных данных: дубликаты под `UNIQUE`, NULL под `NOT NULL` |
| `up → down → up` (где есть down) | Нерабочие down-миграции |
| Линтер: squawk (PG), `atlas migrate lint` | `CREATE INDEX` без `CONCURRENTLY`, `SET NOT NULL`, rename/drop |
| Замер времени на данных размера прода | «Миграция на 40 минут» до того, как она попала в прод |
| Прогон тестов **старой** версии кода на **новой** схеме | Нарушение совместимости с rolling update ⭐ |

---

## 11. Пример: GitLab CI + Flyway

```yaml
stages: [test, migrate, deploy]

.flyway:
  image: { name: redgate/flyway:13.8.0, entrypoint: [""] }   # закрепи версию; проверь теги
  variables:
    FLYWAY_LOCATIONS: filesystem:db/migrations
    FLYWAY_CONNECT_RETRIES: "10"

migrations:test:
  extends: .flyway
  stage: test
  services: [{ name: postgres:17, alias: db }]
  variables:
    POSTGRES_DB: linkd
    POSTGRES_USER: linkd
    POSTGRES_PASSWORD: test
    FLYWAY_URL: jdbc:postgresql://db:5432/linkd
    FLYWAY_USER: linkd
    FLYWAY_PASSWORD: test
  script:
    - flyway migrate
    - flyway validate
    - flyway info
  rules:
    - changes: [db/migrations/**/*]

migrate:prod:
  extends: .flyway
  stage: migrate
  tags: [prod-network]                 # раннер, которому доступна прод-база
  environment: { name: production }
  resource_group: prod-db              # ⭐ никогда два запуска одновременно
  variables:
    FLYWAY_URL: $PROD_DB_JDBC_URL      # protected + masked переменные
    FLYWAY_USER: $PROD_DB_OWNER_USER   # роль-владелец, не роль приложения
    FLYWAY_PASSWORD: $PROD_DB_OWNER_PASSWORD
    FLYWAY_INIT_SQL: "SET lock_timeout = '5s'; SET statement_timeout = '15min'"
  script:
    - flyway info
    - flyway migrate
  rules:
    - if: $CI_COMMIT_TAG
      when: manual                     # человек нажал «катить» — осознанно

deploy:prod:
  stage: deploy
  needs: [migrate:prod]
  script: [./deploy.sh "$CI_COMMIT_TAG"]
  rules:
    - if: $CI_COMMIT_TAG
```
`cleanDisabled` у Flyway по умолчанию `true` — и пусть так и остаётся: `flyway clean`
удаляет **всё** в схеме. Для существующей базы без истории — `flyway baseline`.

---

## 12. Пример: Helm-хук с Alembic для linkd

Общая схема Job-миграции и её иммутабельность — в [Kubernetes: Job и CronJob](/kubernetes/07-job-cronjob) §4,
хуки — в [Kubernetes: Helm](/kubernetes/15-helm) §8. Здесь — то, что добавляет практика:

```yaml
# templates/migrate-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "linkd.fullname" . }}-migrate
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade          # ArgoCD прочитает как PreSync
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": before-hook-creation   # упавший Job остаётся для логов
spec:
  backoffLimit: 0                  # повтор решает человек: в MySQL миграция могла пройти наполовину
  activeDeadlineSeconds: 900
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"   # тот же образ, что у приложения
          command: ["alembic", "upgrade", "head"]
          env:
            - name: DATABASE_URL
              valueFrom: { secretKeyRef: { name: linkd-db-owner, key: url } }   # роль-владелец
            - name: PGOPTIONS
              value: "-c lock_timeout=5s -c statement_timeout=15min"
```
- Секрет `linkd-db-owner` должен существовать **до** хука: при `pre-install` ресурсы
  чарта ещё не созданы. Решение — ExternalSecret/Vault вне чарта или секрет-хук с меньшим весом.
- У Alembic нет блокировки — здесь это не страшно, потому что хук запускается один раз на релиз.
- Проверить до выката, какой SQL поедет: `alembic upgrade head --sql` (offline-режим) — удобно
  приложить к merge request для ревью.

---

## 13. Грабли

| Грабля | Последствие | Правильно |
|--------|-------------|-----------|
| `RENAME`/`DROP COLUMN` в том же релизе, что и код | Старые поды падают во время rollout | expand/contract |
| Миграции на старте приложения при 10 репликах | Гонка, долгий старт, под убит пробой посреди `ALTER` | Job/хук/CI, один запуск |
| `ALTER TABLE` без `lock_timeout` | Очередь блокировок — сайт лежит | `lock_timeout` + ретраи |
| `CREATE INDEX` без `CONCURRENTLY` на большой таблице | Запись заблокирована на минуты | `CONCURRENTLY` вне транзакции |
| Исправили уже применённую миграцию | `validate` падает, окружения расходятся | Только новая миграция |
| Backfill одним `UPDATE` на 50 млн строк | Лаг реплик, bloat, блокировки | Пачками в отдельном job |
| Приложение с правами DDL «для миграций» | Нарушен принцип минимальных прав | Отдельная роль-владелец для миграций |
| Down-миграция, которую ни разу не запускали | Откат не работает в момент аварии | Forward-fix; down — только протестированный |
| Автогенерация ORM без ревью | Переименование превратилось в DROP + ADD | Читать сгенерированный SQL |
| Долгий `ALTER` в MySQL без учёта реплик | Час лага на всех репликах | gh-ost / pt-osc с троттлингом |

---

## 💼 Как это в DevOps

- Миграции — **отдельный шаг** релиза с понятным владельцем: в пайплайне он виден,
  логируется и может остановить выкатку.
- Стандарт команды фиксируют в README/CONTRIBUTING: инструмент, именование файлов,
  «только аддитивные изменения за релиз», обязательный `CONCURRENTLY`, линтер в CI.
- Опасные миграции (часы на большой таблице) выносятся из пайплайна в отдельную
  процедуру с окном, рунбуком и дежурным — как в [CI/CD: проектирование пайплайна](/cicd/03-pipeline-design).
- Метрики и алерты: упавший migrate-job, длительность миграций, лаг реплик во время
  backfill ([07. Мониторинг БД](/databases/07-db-monitoring)).
- На собесе хорошо звучит история: «переименовали колонку за три релиза, откат был
  возможен на каждом шаге».

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Применить миграции | `flyway migrate` / `alembic upgrade head` / `migrate -path db -database "$URL" up` / `liquibase update` |
| Посмотреть состояние | `flyway info` / `alembic current` / `migrate version` |
| Проверить целостность | `flyway validate` / `alembic check` / `atlas migrate validate` |
| SQL без применения | `alembic upgrade head --sql` / `liquibase update-sql` |
| Починить после сбоя | `flyway repair` / `migrate force <v>` / `liquibase release-locks` |
| Существующая база без истории | `flyway baseline` / `alembic stamp head` |
| Не вешать прод блокировкой | `SET lock_timeout = '5s';` (MySQL: `lock_wait_timeout`) |
| Индекс без блокировки записи | PG: `CREATE INDEX CONCURRENTLY`; MySQL: `ALGORITHM=INPLACE, LOCK=NONE` |
| `NOT NULL` без долгой блокировки | `CHECK … NOT VALID` → `VALIDATE` → `SET NOT NULL` |
| Одна миграция за раз в GitLab | `resource_group: prod-db` |
| Миграция в k8s | Job-хук `pre-upgrade` / ArgoCD `PreSync` |
| Точка отката | `SELECT pg_create_restore_point('before_V8');` |

---

## 🧠 Что запомнить

1. ⭐ Во время rolling update схема обслуживает **две версии кода** — миграция совместима с обеими.
2. Переименование и удаление — только через expand/contract (минимум три релиза).
3. Миграция запускается **один раз** и под блокировкой: Job/хук/CI, а не каждый под на старте.
4. Где запускать: k8s — Helm `pre-upgrade`/ArgoCD `PreSync`; VM — шаг CI/Ansible до кода.
5. Миграции едут под ролью-владельцем, приложение работает без прав DDL.
6. `lock_timeout` + ретраи: даже мгновенный `ALTER` вешает прод, если ждёт блокировку.
7. Индексы в PG — `CONCURRENTLY`, ограничения — `NOT VALID` + `VALIDATE`, backfill — пачками.
8. В MySQL DDL не транзакционный: явный `ALGORITHM`, `lock_wait_timeout`, gh-ost/pt-osc
   для больших таблиц, помнить про лаг реплик.
9. Откат — forward-fix; код откатывается всегда, схема — почти никогда.
10. Инструменты: Flyway (13.x), Liquibase (5.x, **FSL** с 2025), Alembic, golang-migrate,
    Atlas (EULA/Community); выбор диктует язык проекта.

---

## Задачи

> Стенд: `postgres:17` в Docker + `pgbench` для нагрузки; для MySQL-задач — стенд из
> [12. MySQL и MariaDB](/databases/12-mysql); для Helm-задач — kind-кластер из блока Kubernetes.

---

### Блок A. Теория

**A1.** Почему миграции схемы — забота DevOps, а не только разработчика? Назови минимум
четыре зоны ответственности.

<details><summary>Ответ</summary>

Место и порядок запуска в пайплайне; единственный запуск и блокировки; доступы
(роль-владелец, секреты); таймауты и защита прода от долгих блокировок; бэкап/точка
восстановления и план отката; наблюдаемость (логи, алерты, лаг реплик).

</details>

**A2.** Как инструмент понимает, какие миграции уже применены? Что такое checksum
и почему нельзя редактировать применённую миграцию?

<details><summary>Ответ</summary>

По таблице истории в самой базе (`flyway_schema_history`, `alembic_version`,
`schema_migrations`, `DATABASECHANGELOG`). Checksum — хеш содержимого файла на момент
применения; если файл изменить, `validate` увидит расхождение: окружения, где применялась
старая версия, и новые окружения получили бы разную схему.

</details>

**A3.** Сравни Flyway, Liquibase, Alembic, golang-migrate и Atlas: формат миграций,
поддержка отката, есть ли блокировка.

<details><summary>Ответ</summary>

Flyway — SQL-файлы по номерам, undo только в платной редакции, блокировка есть.
Liquibase — changelog (SQL/XML/YAML), встроенный rollback, блокировка через таблицу.
Alembic — Python-ревизии поверх SQLAlchemy, `downgrade`, своей блокировки нет.
golang-migrate — пары up/down SQL, блокировка есть. Atlas — декларативно и версионно,
линтер, блокировка есть.

</details>

**A4.** ⭐ Что изменилось с лицензией Liquibase в 2025 году? Что это значит для компании,
которая просто катит им миграции своего продукта?

<details><summary>Ответ</summary>

С версии 5.0 (сентябрь 2025) Liquibase Community распространяется под Functional
Source License вместо Apache 2.0. Использовать у себя в проде, менять и контрибьютить можно;
запрещено строить конкурирующий коммерческий продукт; каждая версия через два года
переходит в Apache 2.0. Для обычной компании изменений почти нет, но юристам стоит знать:
это не OSI-лицензия. Плюс 5.x поставляется без драйверов — их надо добавить самим.

</details>

**A5.** Чем версионный подход отличается от декларативного? Почему переименование колонки
особенно опасно в декларативном?

<details><summary>Ответ</summary>

Версионный — последовательность шагов, ревьюится ровно тот SQL, что поедет;
декларативный — желаемое состояние, инструмент считает diff (как Terraform). В декларативном
diff не знает о намерении «переименовать»: он видит «колонки `url` нет, есть `target_url`»
и генерирует `DROP` + `ADD` — данные теряются.

</details>

**A6.** Перечисли места, где можно запускать миграции, и по одному плюсу и минусу каждого.

<details><summary>Ответ</summary>

Приложение на старте (просто / гонки и права DDL у приложения); init container
(автоматически / N запусков и стоящий rollout); job в CI (явно и с логами / нужен доступ
к базе из раннера); k8s Job из пайплайна (рядом с базой / нужна обвязка); Helm-хук (часть
релиза / упал хук — упал релиз, секреты до хука); ArgoCD PreSync (GitOps / отладка через ArgoCD).

</details>

**A7.** ⭐ Почему «миграции на старте приложения» плохи при нескольких репликах? Три причины.

<details><summary>Ответ</summary>

N подов одновременно пытаются мигрировать (гонка, ожидание блокировки);
приложению нужны права DDL (нарушение минимальных прав); долгая миграция не даёт поду
стать ready — liveness-проба убивает его посреди `ALTER` (в MySQL это ещё и полупримененная
миграция).

</details>

**A8.** Зачем нужна блокировка миграций? У какого инструмента из темы её нет и как быть?

<details><summary>Ответ</summary>

Чтобы два параллельных запуска не применили одно и то же и не записали
противоречивую историю. У Alembic блокировки нет — запускать один раз (Job/CI с
`resource_group`) или оборачивать в `pg_advisory_lock`.

</details>

**A9.** Что значит «схема должна быть совместима с двумя версиями кода»? Откуда берутся
именно две версии?

<details><summary>Ответ</summary>

Во время rolling update часть подов ещё на коде N, часть уже на N+1, и все они
работают с одной схемой. Миграция идёт до деплоя — значит, её результат увидит и старый код.
Плюс откат N+1 → N должен работать без отката схемы.

</details>

**A10.** Какие изменения схемы безопасны за один релиз, а какие — нет? Приведи по три примера.

<details><summary>Ответ</summary>

Безопасно: новая таблица, nullable-колонка, колонка с константным default (PG 11+),
индекс `CONCURRENTLY`. Небезопасно: переименование, удаление колонки, которую читает
текущий код, смена типа, `SET NOT NULL` напрямую на большой таблице.

</details>

**A11.** ⭐ Опиши expand/contract для переименования колонки: что происходит в схеме
и в коде в каждом из трёх релизов и в какой момент теряется возможность отката.

<details><summary>Ответ</summary>

Релиз A (expand): добавить новую колонку (+ триггер синхронизации для старого кода),
код пишет в обе и читает с fallback, фоновый backfill. Релиз B (switch): новая колонка
`NOT NULL`, старая nullable, код работает только с новой. Релиз C (contract): удалить
старую колонку и триггер. После C откат на A невозможен — поэтому C катят, когда B стабилен.

</details>

**A12.** Что такое очередь блокировок в PostgreSQL и почему даже мгновенный `ALTER TABLE`
может положить сайт?

<details><summary>Ответ</summary>

`ALTER TABLE` просит `ACCESS EXCLUSIVE`; пока его держит хоть один долгий запрос,
`ALTER` ждёт, а все последующие запросы к таблице встают в очередь **за ним**, даже
простые `SELECT`. Сам `ALTER` быстрый, но ожидание блокировки = простой. Лечится
`lock_timeout` и ретраями.

</details>

**A13.** Что делает `CREATE INDEX CONCURRENTLY`, какие у него ограничения и что остаётся
после неудачного построения?

<details><summary>Ответ</summary>

Строит индекс без блокировки записи (два прохода по таблице). Нельзя внутри
транзакции, дольше обычного, при отмене или ошибке остаётся `INVALID`-индекс, который
не используется, но обновляется — его нужно удалить и построить заново.

</details>

**A14.** Как добавить `NOT NULL` к существующей колонке большой таблицы без долгой блокировки?

<details><summary>Ответ</summary>

`ADD CONSTRAINT … CHECK (col IS NOT NULL) NOT VALID` (мгновенно) →
`VALIDATE CONSTRAINT` (скан, но запись не блокируется) → `SET NOT NULL` (в PG 12+ без скана,
по проверенному CHECK) → удалить CHECK.

</details>

**A15.** Чем миграции в MySQL опаснее, чем в PostgreSQL? Что означают `ALGORITHM=INSTANT` и `INPLACE`? Чем gh-ost отличается от pt-online-schema-change?

<details><summary>Ответ</summary>

DDL в MySQL не транзакционный — упавшая миграция остаётся наполовину применённой;
DDL на репликах выполняется после primary и столько же времени (лаг). `INSTANT` — меняются
только метаданные, `INPLACE` — перестройка без копии таблицы, часто с `LOCK=NONE`.
gh-ost догоняет изменения по binlog без триггеров и умеет троттлинг по лагу; pt-osc
использует триггеры на исходной таблице.

</details>

**A16.** Forward-fix или down-миграция: что выбирают в проде и почему?

<details><summary>Ответ</summary>

Forward-fix — новая миграция, исправляющая проблему. Down-миграции часто теряют
данные (удаляют колонку с новыми данными) или вовсе невозможны (вернуть удалённое),
и их редко тестируют. Код откатывают свободно благодаря совместимости схемы, а схему — чинят вперёд.

</details>

**A17.** Что стоит проверять в CI для миграций? Назови минимум пять проверок.

<details><summary>Ответ</summary>

Применение на пустую базу; `validate`/`check` (checksum и дрейф моделей);
применение на копии схемы прода с данными-образцом; up→down→up; линтер опасных операций;
замер длительности на данных размера прода; тесты старой версии кода на новой схеме.

</details>

---

### Блок B. «Что тут не так»

```sql
B1.  -- V8__rename_url.sql, едет в одном релизе с кодом, который читает target_url
     ALTER TABLE links RENAME COLUMN url TO target_url;
```

<details><summary>Ответ</summary>

Переименование ломает старые поды мгновенно: весь rollout — ошибки `column "url"
does not exist` (или наоборот). Нужен expand/contract.

</details>

```sql
B2.  -- таблица links: 200 млн строк, прод
     CREATE INDEX ix_links_created ON links (created_at);
```

<details><summary>Ответ</summary>

Обычный `CREATE INDEX` блокирует запись в таблицу на всё время построения —
на 200 млн строк это минуты или часы простоя. Нужен `CONCURRENTLY` (и вне транзакции).

</details>

```sql
B3.  -- одна миграция
     ALTER TABLE links ADD COLUMN target_url TEXT;
     UPDATE links SET target_url = url;            -- 80 млн строк
```

<details><summary>Ответ</summary>

Backfill одной транзакцией: долгие блокировки строк, лаг реплик, раздувание таблицы,
откат всего при ошибке в конце. Колонку — миграцией, заполнение — пачками отдельным джобом.

</details>

```sql
B4.  -- Alembic-миграция на существующей таблице с данными
     op.add_column('links', sa.Column('owner_id', sa.Integer(), nullable=False))
```

<details><summary>Ответ</summary>

На таблице с данными `NOT NULL` без default не добавится (ошибка: существующие строки
получили бы NULL), а код N, не знающий о колонке, не сможет вставлять. Сначала nullable/default,
backfill, потом `NOT NULL`.

</details>

```sql
B5.  -- «план отката» для релиза A из expand/contract
     ALTER TABLE links DROP COLUMN target_url;
```

<details><summary>Ответ</summary>

«Откат» удаляет данные, записанные в `target_url` за время работы релиза A, и ломает
код A, если он уже работает. Отката схемы в этой схеме не требуется — откатывается только код.

</details>

```sql
B6.  -- MySQL 8.4, таблица 300 ГБ, три реплики, запуск из пайплайна
     ALTER TABLE orders MODIFY amount DECIMAL(12,2);
```

<details><summary>Ответ</summary>

Смена типа колонки обычно требует копирования таблицы (`ALGORITHM=COPY`) с блокировкой
записи на часы, затем столько же лага на каждой реплике. Для такой таблицы — gh-ost/pt-osc
с троттлингом, вне пайплайна, в окно.

</details>

```sql
B7.  -- в одном файле Flyway / одной Alembic-ревизии без autocommit_block
     ALTER TABLE links ADD COLUMN owner_id INT;
     CREATE INDEX CONCURRENTLY ix_links_owner ON links (owner_id);
```

<details><summary>Ответ</summary>

`CREATE INDEX CONCURRENTLY cannot run inside a transaction block` — миграция упадёт
(или Flyway откажется смешивать). `CONCURRENTLY` — отдельным файлом/ревизией, в Alembic —
через `autocommit_block()`.

</details>

```dockerfile
B8.  # deployment: replicas: 6
     CMD ["sh", "-c", "alembic upgrade head && exec gunicorn linkd:app"]
```

<details><summary>Ответ</summary>

Шесть подов одновременно запускают миграцию при каждом старте и каждом перезапуске;
у Alembic нет блокировки — гонки; долгая миграция сорвёт пробы; приложению нужны права DDL.

</details>

```bash
B9.  # «в V3 опечатка в комментарии, поправил» — V3 уже применён на стейдже и проде
     git commit -am "fix typo in V3__links_add_target_url.sql"
```

<details><summary>Ответ</summary>

Изменён checksum применённой миграции: `flyway validate` на всех окружениях упадёт,
деплой остановится. Применённые файлы не трогают; если уже случилось — вернуть файл
или осознанно `flyway repair` (обновит checksum в истории).

</details>

```yaml
B10. migrate:prod:
       stage: migrate
       script: [flyway migrate]
       rules: [{ if: '$CI_COMMIT_BRANCH == "main"' }]   # пайплайн на каждый merge
       # resource_group не задан
```

<details><summary>Ответ</summary>

Два пайплайна подряд могут запустить миграции одновременно; к тому же любой merge
катит в прод без контроля. Нужны `resource_group`, запуск по тегу/вручную.

</details>

```yaml
B11. variables:
       FLYWAY_CLEAN_DISABLED: "false"          # в прод-джобе, «на всякий случай»
```

<details><summary>Ответ</summary>

`flyway clean` удаляет все объекты в схеме — одна случайная команда или ошибка
в скрипте уничтожит прод. `cleanDisabled` должен оставаться `true` везде, кроме эфемерных баз.

</details>

```yaml
B12. annotations:
       "helm.sh/hook": pre-upgrade
       "helm.sh/hook-delete-policy": hook-succeeded,hook-failed
```

<details><summary>Ответ</summary>

Упавший Job удаляется сразу — логов, почему упала миграция, не будет. Лучше
`before-hook-creation` (удалять перед следующим запуском), при желании плюс `hook-succeeded`.

</details>

```yaml
B13. env:
       - name: DATABASE_URL
         valueFrom: { secretKeyRef: { name: linkd-db-app, key: url } }   # роль приложения с GRANT ALL
```

<details><summary>Ответ</summary>

Миграции должны ехать под ролью-владельцем, а приложение — работать под ролью
без DDL. Роль приложения с `GRANT ALL` превращает любую SQL-инъекцию в `DROP TABLE`.

</details>

---

### Блок C. Практика

#### C1. Flyway руками
1. Подними `postgres:17` и запусти Flyway в контейнере с каталогом `db/migrations`.
2. Создай `V1__init.sql` (таблица `links` как у linkd) и `V2__hits_index.sql`, выполни `migrate`, `info`.
3. Посмотри таблицу `flyway_schema_history`.
4. Измени `V1` и запусти `validate` — зафиксируй ошибку. Верни файл обратно.
5. Сделай `V3` с синтаксической ошибкой, примени, посмотри `info`, исправь и примени снова.
   Объясни, почему в PostgreSQL `repair` не понадобился, а в MySQL понадобился бы.

<details><summary>Ответ</summary>

`validate` пишет о несовпадении checksum для версии 1. Неудачная `V3` в PG выполнялась
в транзакции: DDL откатился целиком, записи о сбое в истории нет — исправляешь файл (он ещё
нигде не применён) и повторяешь. В MySQL DDL не транзакционный: остаётся запись
`success = false` и полупримененные изменения — сначала ручная уборка, потом `flyway repair`.

</details>

#### C2. Alembic
1. `alembic init`, настрой `sqlalchemy.url` из переменной окружения.
2. Создай ревизию с новой колонкой, `upgrade head`, `downgrade -1`, снова `upgrade head`.
3. Выведи SQL без применения: `alembic upgrade head --sql`.
4. Опиши модель SQLAlchemy, расходящуюся с базой, и проверь `alembic check`.

<details><summary>Ответ</summary>

`--sql` печатает DDL для ревью/DBA без подключения к базе; `alembic check` сообщает
о расхождении моделей и миграций и завершается с ошибкой — удобно для CI.

</details>

#### C3. golang-migrate и «грязное» состояние
1. Создай пару `000001_init.up.sql` / `.down.sql`, примени `up`.
2. Напиши `000002` с ошибкой во втором statement'е, примени.
3. Посмотри `migrate version` (dirty), таблицу `schema_migrations`; почини базу руками,
   затем `migrate force 1` и повтори с исправленной миграцией.

<details><summary>Ответ</summary>

В `schema_migrations` `dirty = true`: инструмент не знает, что успело примениться.
Сначала вручную привести базу к состоянию версии 1, затем `migrate force 1`, затем снова `up`.
`force` без уборки — ложь в истории.

</details>

#### C4. ⭐ Очередь блокировок своими глазами
1. Сессия 1: `BEGIN; SELECT count(*) FROM links;` — не завершай.
2. Сессия 2: `ALTER TABLE links ADD COLUMN note TEXT;` — висит.
3. Сессия 3: `SELECT * FROM links LIMIT 1;` — тоже висит. Посмотри `pg_stat_activity`
   и `pg_blocking_pids()`.
4. Повтори с `SET lock_timeout = '3s';` в сессии 2 и объясни разницу для сайта.

<details><summary>Ответ</summary>

Без `lock_timeout` третья сессия ждёт вместе со второй — так выглядит «лёг сайт».
С `lock_timeout` `ALTER` падает через 3 секунды с `canceling statement due to lock timeout`,
очередь рассасывается, миграцию повторяют позже.

</details>

#### C5. `CONCURRENTLY` под нагрузкой
1. Нагенерируй 5–10 млн строк, запусти `pgbench` с записью в эту таблицу.
2. Построй индекс обычным `CREATE INDEX` и посмотри, что происходит с TPS.
3. Удали индекс, построй `CONCURRENTLY`, сравни.
4. Прерви `CREATE INDEX CONCURRENTLY` (Ctrl+C), найди `INVALID`-индекс:
   `SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;`, удали и повтори.

<details><summary>Ответ</summary>

Обычный `CREATE INDEX` роняет TPS записи почти до нуля на время построения,
`CONCURRENTLY` дольше, но запись идёт. После прерывания остаётся `INVALID`-индекс.

</details>

#### C6. ⭐ Expand/contract для linkd
Пройди три релиза из конспекта (`url` → `target_url`) на стенде:
1. Эмулируй «старый код» и «новый код» двумя SQL-скриптами (вставка/чтение так, как делает
   каждая версия) и запускай их **одновременно** в цикле во время каждой миграции.
2. После каждого релиза проверь строку матрицы совместимости: какие версии кода работают.
3. Сделай «откат» кода на каждом шаге и убедись, что он не требует отката схемы.
4. Попробуй сделать V4 до окончания backfill — что остановит миграцию?

<details><summary>Ответ</summary>

Матрица из конспекта подтверждается; V4 остановит `VALIDATE CONSTRAINT`, если
остались строки с `target_url IS NULL`.

</details>

#### C7. `NOT NULL` без долгой блокировки
На таблице в 10+ млн строк сравни `ALTER TABLE … SET NOT NULL` напрямую и вариант
`CHECK … NOT VALID` → `VALIDATE` → `SET NOT NULL`. Во время каждого варианта из другой
сессии делай `INSERT` и замеряй, сколько он ждёт.

<details><summary>Ответ</summary>

Прямой `SET NOT NULL` держит `ACCESS EXCLUSIVE` на весь скан — `INSERT` ждут;
при варианте с `CHECK` блокировка короткая, а `VALIDATE` не мешает записи.

</details>

#### C8. Тест миграций в GitLab CI
1. Добавь в проект job `migrations:test` из конспекта (service `postgres:17`).
2. Сделай миграцию, добавляющую `UNIQUE` на колонку, где в реальных данных есть дубликаты.
3. На пустой базе она пройдёт — добавь шаг, который сначала загружает обезличенный дамп
   схемы и данных-образца, и убедись, что CI ловит проблему.
4. Добавь линтер (squawk или `atlas migrate lint`) и посмотри, что он скажет про `CREATE INDEX`
   без `CONCURRENTLY`.

<details><summary>Ответ</summary>

На пустой базе `UNIQUE` создаётся, на данных-образце — `could not create unique index …
Key (…) is duplicated`. Линтер отметит `CREATE INDEX` без `CONCURRENTLY` как блокирующую операцию.

</details>

#### C9. Helm-хук с миграцией
1. В kind разверни чарт с Job-хуком `pre-install,pre-upgrade` (Alembic или Flyway).
2. Сломай миграцию и сделай `helm upgrade --wait` — посмотри статус релиза, `helm history`,
   логи Job, что стало с подами приложения.
3. Почини и повтори. Объясни, зачем `before-hook-creation` и `backoffLimit: 0`.
4. (Со звёздочкой) то же самое через ArgoCD: убедись, что хук выполнился как `PreSync`.

<details><summary>Ответ</summary>

Релиз в статусе `failed`, поды приложения не тронуты (хук `pre-upgrade` отработал
до изменения манифестов) — это хорошо. `before-hook-creation` сохраняет упавший Job
до следующей попытки, `backoffLimit: 0` не даёт повторять миграцию без человека.

</details>

#### C10. MySQL online DDL (со звёздочкой — gh-ost)
1. На `mysql:8.4` выполни `ADD COLUMN … ALGORITHM=INSTANT`, `ADD INDEX … ALGORITHM=INPLACE, LOCK=NONE`.
2. Попробуй `MODIFY` типа колонки с `ALGORITHM=INSTANT` — зафиксируй ошибку и объясни её пользу.
3. Повтори сценарий C4 в MySQL и найди `Waiting for table metadata lock` в `SHOW PROCESSLIST`.
4. На стенде primary + replica из темы 12 прогони то же изменение через gh-ost
   и понаблюдай лаг реплики.

<details><summary>Ответ</summary>

MySQL вернёт `ALGORITHM=INSTANT is not supported for this operation. Try ALGORITHM=COPY/INPLACE`
— польза в том, что тяжёлая операция не выполнится молча. gh-ost держит лаг реплики в пределах
`--max-lag-millis`, притормаживая копирование.

</details>

---

### Блок D. Инциденты

**D1.** Во время релиза сайт лежал 4 минуты. В `pg_stat_activity` — сотни запросов
с `wait_event_type = Lock`, первый в цепочке — `ALTER TABLE orders ADD COLUMN …`,
а перед ним — отчёт, работающий 20 минут. Что произошло, как вытащить сейчас,
как не допустить?

<details><summary>Ответ</summary>

`ALTER` ждал `ACCESS EXCLUSIVE` за долгим отчётом, все запросы встали за `ALTER`.
Сейчас: отменить `ALTER` (`pg_cancel_backend`) или отчёт — очередь сразу рассосётся.
Профилактика: `lock_timeout` + ретраи в миграциях, `statement_timeout`/отдельная реплика
для отчётов, не катить миграции в часы тяжёлых отчётов.

</details>

**D2.** В течение rollout 30% запросов отдают 500: `column "url" does not exist`.
Через 3 минуты, когда rollout закончился, ошибки пропали. Что сделали не так?

<details><summary>Ответ</summary>

Миграция переименовала (или удалила) колонку до того, как старый код перестал
её использовать; старые поды падали, пока их не заменили. Нужен expand/contract,
а не rename в одном релизе.

</details>

**D3.** Миграция на MySQL упала посередине: первые два `ALTER` прошли, третий — нет.
Flyway пишет `Detected failed migration to version 8`. Порядок действий.

<details><summary>Ответ</summary>

Остановить деплой. Посмотреть, какие части V8 применились (`SHOW CREATE TABLE`),
вручную довести до «до V8» или «после V8», исправить скрипт (новой версией, если V8 уже
применялась где-то ещё), `flyway repair` для удаления записи о сбое, повторить.
Вывод: одна DDL-операция на миграцию в MySQL.

</details>

**D4.** golang-migrate: `Dirty database version 12. Fix and force version.` Что это
и как чинить безопасно?

<details><summary>Ответ</summary>

Миграция 12 упала посередине, инструмент пометил базу `dirty` и отказывается работать.
Посмотреть, что успело примениться, вручную привести к версии 11 (или 12), затем
`migrate force 11` (или 12) и повторить. Не делать `force` «вслепую».

</details>

**D5.** Деплой висит: Liquibase пишет `Waiting for changelog lock…` уже 20 минут.
Прошлый деплой убили по таймауту. Что делать?

<details><summary>Ответ</summary>

Прошлый процесс взял блокировку в `DATABASECHANGELOGLOCK` и умер, не сняв её.
Убедиться, что никакой Liquibase сейчас действительно не работает, затем `liquibase release-locks`
(или `UPDATE DATABASECHANGELOGLOCK SET LOCKED = FALSE`), выяснить, что успело примениться.

</details>

**D6.** `helm upgrade` упал: `pre-upgrade hooks failed: job failed: DeadlineExceeded`.
Поды приложения не обновились. Хорошо это или плохо и что проверяешь?

<details><summary>Ответ</summary>

Скорее хорошо: хук упал до изменения манифестов, прод работает на старой версии
со старой схемой. Проверить логи Job (почему `DeadlineExceeded`: ждала блокировку?
огромный backfill?), состояние схемы, не осталась ли миграция наполовину (MySQL), затем
исправить и повторить.

</details>

**D7.** После backfill-джоба лаг реплик вырос до 40 минут, диск базы +30%,
autovacuum не вылезает из таблицы. Что пошло не так и как делать в следующий раз?

<details><summary>Ответ</summary>

Backfill шёл большими пачками без пауз: массив WAL/binlog, реплики не успевают,
мёртвые строки копятся быстрее, чем autovacuum их чистит. Правильно: маленькие пачки
с паузами, троттлинг по лагу реплик, запуск в спокойные часы, мониторинг лага и места.

</details>

**D8.** Разработчик просит «откатите релиз», а в релизе была миграция `DROP COLUMN legacy_status`.
Что ответишь и что можно сделать?

<details><summary>Ответ</summary>

Код можно откатить, только если старый код не использует удалённую колонку.
Если использует — откат кода сломает сервис; данные колонки вернуть можно только из
бэкапа/PITR в отдельный инстанс. Урок: `DROP` — только в contract-релизе, когда код, её
читающий, давно не работает.

</details>

**D9.** Индекс создали `CONCURRENTLY`, миграция «прошла», но запросы не ускорились.
В `\d orders` индекс помечен `INVALID`. Почему и как починить?

<details><summary>Ответ</summary>

Построение `CONCURRENTLY` упало (дедлок, нарушение уникальности, отмена), а инструмент
этого не заметил или ошибку проигнорировали. Индекс `INVALID` не используется планировщиком.
`DROP INDEX CONCURRENTLY`, устранить причину и построить заново; в CI — проверка
`pg_index.indisvalid` после миграций.

</details>

**D10.** Юристы спрашивают: можно ли дальше использовать Liquibase 5 после смены лицензии?
А отдельная команда хочет сделать платный SaaS «миграции баз для клиентов» поверх Liquibase.

<details><summary>Ответ</summary>

Использовать Liquibase 5 внутри компании для своих продуктов можно — FSL это разрешает.
Коммерческий сервис, конкурирующий с Liquibase, на версиях под FSL строить нельзя (пока версия
не перешла в Apache 2.0 через два года) — варианты: остаться на 4.x (Apache 2.0, но без поддержки),
купить лицензию или взять другой инструмент.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как у вас устроены миграции базы в пайплайне?

<details><summary>Ответ</summary>

Миграции лежат в репозитории рядом с кодом, в CI проверяются на пустой базе и на копии
схемы, в прод едут отдельным шагом (Job-хук или job в CI) под ролью-владельцем,
с `lock_timeout` и блокировкой от параллельных запусков.

</details>

**2.** Где запускать миграции в Kubernetes и почему не в приложении на старте?

<details><summary>Ответ</summary>

Helm `pre-upgrade`-хук или ArgoCD `PreSync` Job тем же образом; на старте приложения —
гонки N подов, права DDL у приложения, пробы убивают долгую миграцию.

</details>

**3.** Как переименовать колонку без простоя?

<details><summary>Ответ</summary>

Expand/contract: добавить новую колонку и синхронизацию, код пишет в обе, backfill;
переключить код на новую; удалить старую в третьем релизе.

</details>

**4.** Как сделать миграцию совместимой с rolling update?

<details><summary>Ответ</summary>

Только аддитивные изменения в релизе; удаления и переименования — отложенным contract;
новые колонки nullable или с default; откат кода не требует отката схемы.

</details>

**5.** Что будет, если две миграции запустятся одновременно?

<details><summary>Ответ</summary>

Инструменты берут блокировку и второй ждёт; без блокировки (Alembic) — гонка и ошибки.
Плюс `resource_group` в CI.

</details>

**6.** Как не заблокировать прод долгим `ALTER TABLE`?

<details><summary>Ответ</summary>

`lock_timeout` + ретраи, `CONCURRENTLY`, `NOT VALID` + `VALIDATE`, backfill пачками;
в MySQL — `ALGORITHM=INSTANT/INPLACE`, `lock_wait_timeout`, gh-ost для больших таблиц.

</details>

**7.** Как добавить индекс на большую таблицу в PostgreSQL и в MySQL?

<details><summary>Ответ</summary>

PG — `CREATE INDEX CONCURRENTLY` вне транзакции, проверить `indisvalid`; MySQL — `ADD INDEX`
с `ALGORITHM=INPLACE, LOCK=NONE` или gh-ost, следить за лагом реплик.

</details>

**8.** Как откатывать релиз с миграцией?

<details><summary>Ответ</summary>

Откатываем код — схема совместима; схему чиним forward-fix; восстановление из бэкапа —
крайний случай; перед рискованной миграцией — точка восстановления.

</details>

**9.** Как тестируете миграции?

<details><summary>Ответ</summary>

Пустая база, копия схемы прода с данными, validate/check, линтер, замер времени,
старый код против новой схемы.

</details>

**10.** Какими инструментами миграций пользовался и чем они отличаются?

<details><summary>Ответ</summary>

Flyway, Alembic, golang-migrate, Liquibase, Atlas: SQL-файлы vs changelog vs ORM,
откаты, блокировки, лицензии (Liquibase FSL, Atlas EULA/Community).

</details>

---

### 🎯 Чек-лист

- [ ] Объясню, почему миграции — зона ответственности DevOps
- [ ] Знаю, как работают таблица истории, checksum и блокировка
- [ ] Сравню Flyway, Liquibase, Alembic, golang-migrate, Atlas (и лицензии)
- [ ] ⭐ Выбираю место запуска миграций осознанно и не запускаю их из каждого пода
- [ ] ⭐ Прошёл expand/contract `url` → `target_url` и проверил матрицу совместимости
- [ ] Видел очередь блокировок и использую `lock_timeout`
- [ ] Строю индексы `CONCURRENTLY` и добавляю `NOT NULL` через `NOT VALID`
- [ ] Знаю online DDL в MySQL и когда брать gh-ost/pt-osc
- [ ] Отвечаю про откат через forward-fix
- [ ] Настроил тест миграций в GitLab CI и миграцию Helm-хуком
