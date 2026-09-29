---
title: "02. Контейнеризация: образ и локальный стенд"
description: "Цель этапа: перенести образ из 04-shipyard в портфолио, довести его до linkd 2.0"
---

# 02. Контейнеризация: образ и локальный стенд

> **Цель этапа:** перенести образ из 04-shipyard в портфолио, довести его до linkd 2.0
> и собрать стенд «nginx + linkd ×2 + PostgreSQL», который поднимается одной командой.
>
> **После этапа у тебя есть:** `docker/Dockerfile`, `.dockerignore`, `compose/` со
> стендом, `Makefile` с целями `up`/`down`/`smoke`, таблица «было → стало» по размеру
> и времени сборки в README.
>
> **~время:** 2–3 часа (после проекта).

---

## 🧪 Откуда берём

| Проект | Что забираешь | Когда готово |
|--------|---------------|--------------|
| 🛠️ **04-shipyard** — упаковка и доставка · `README` · `~/Projects/devops/04-shipyard` | `docker/Dockerfile`, `.dockerignore`, `compose/docker-compose.yml` и конфиг nginx | `./check.sh` зелёный |
| 🛠️ **09-ledger** — эксплуатация PostgreSQL · `README` · `~/Projects/devops/09-ledger` | как linkd 2.0 подключается к PostgreSQL и как создаётся схема | достаточно запуска приложения из проекта |
| 🛠️ **03-gatekeeper** — точка входа · `README` · `~/Projects/devops/03-gatekeeper` | по желанию: TLS и upstream-настройки nginx для стенда | `./check.sh` зелёный |

Инциденты про Docker из `99-incidents`
(`~/Projects/devops/99-incidents`) — источник историй для `docs/journal.md`.

---

## 🎯 Цель

Образ — артефакт, который дальше **без изменений** поедет в CI, registry, dev и prod.
Всё, что отработано в 04-shipyard (non-root, размер, кэш слоёв, сигналы, healthcheck),
наследуют все следующие этапы.

Что меняется по сравнению с проектом:

- приложение — linkd 2.0, а значит, проверка здоровья смотрит на `/healthz`;
- данные — в PostgreSQL, поэтому две реплики linkd больше не делят один файл SQLite:
  вывод из compose-задачи 04-shipyard становится решением, записанным в ADR;
- образ должен сообщать, из какого коммита он собран, — этим воспользуется CI (этап 03).

---

## 🗺️ Что получится

```text
 linkd-platform/
 ├── docker/Dockerfile         ← из 04-shipyard + метки OCI и /healthz
 ├── .dockerignore             ← в корне: контекст сборки — корень репо
 ├── compose/
 │   ├── docker-compose.yml    ← 04-shipyard + сервис PostgreSQL
 │   ├── nginx.conf            ← 04-shipyard / 03-gatekeeper
 │   └── .env.example          ← только имена переменных, без значений
 └── Makefile                  ← up · down · smoke · build

                :8080
   curl ──► nginx ──► linkd-1 ─┐
                 └──► linkd-2 ─┴──► postgres ── volume pgdata
   порядок старта: postgres healthy ─► (схема) ─► linkd healthy ─► nginx
```text
---

## 🪜 Шаги

### 1. Проект зелёный

```bash
cd ~/Projects/devops/04-shipyard && ./check.sh
```text
### 2. Перенос в раскладку портфолио

Файлы — в каталоги из схемы выше. Пути внутри (`COPY`, `context`, `dockerfile`)
поправь под новую раскладку: в проекте контекстом был корень проекта, здесь — корень
`linkd-platform`, и в нём лежат ещё `tools/`, `infra/`, `docs/`. Значит, `.dockerignore`
теперь отсекает гораздо больше, чем в проекте.

### 3. Что добавить поверх проекта

**Образ:**
- `HEALTHCHECK` смотрит на `/healthz` — он не ходит в базу;
- у linkd 2.0 появились настоящие зависимости: `requirements.txt` (psycopg 3) и
  необязательный `requirements-otel.txt`. Слой зависимостей по-прежнему выше слоя
  с кодом, кэш работает как в 04-shipyard;
- пакеты трейсов в образе или нет — решение с ценой: без них трейсы выключены (linkd
  пишет одно предупреждение `tracing disabled`), с ними образ больше. Размер обоих
  вариантов — в таблицу замеров, выбор — в ADR;
- метки OCI (`org.opencontainers.image.revision`, `.version`, `.source`) через
  build-аргументы — CI передаст SHA коммита, и по любому образу найдётся его код;
- версия linkd зашита в код (`VERSION`) и видна в `/healthz` и `linkd_build_info`;
  тег образа — отдельная сущность, и как они соотносятся, написано в README.

**Стенд compose:**
- сервис PostgreSQL с именованным томом и healthcheck;
- `LINKD_DATABASE_URL` и пароль БД — из `.env`, который в `.gitignore`;
  в репозитории — `.env.example` с именами переменных;
- схема БД: таблицу linkd создаёт сам и повторяет попытку, пока база не поднимется.
  Если в 09-ledger у приложения роль без DDL-прав (ей хватает `SELECT, INSERT, UPDATE`),
  таблица создаётся заранее — в compose это одноразовый сервис перед linkd;
- `LINKD_LOG_FORMAT=json` — логи сразу в формате, который потом заберёт Loki;
- nginx стартует только после того, как linkd стал `healthy`.

**Точка входа** — `Makefile` (или `scripts/`), чтобы README не превращался в простыню команд:

| Цель | Что делает |
|------|-----------|
| `make build` | собрать образ с версией и SHA |
| `make up` / `make down` | поднять / остановить стенд |
| `make smoke` | сценарий проверки из шага 5 |

### 4. Замеры для README

| Что | Было (04-shipyard, исходный образ) | Стало |
|-----|-----------------------------------|-------|
| Размер образа | … МБ | … МБ |
| Пересборка после правки кода | … с | … с |
| `docker stop` | … с | … с |
| Пользователь в контейнере | root | UID … |

Цифры — только замеренные. Это готовая строка для резюме и ответ на «что конкретно
улучшено».

### 5. Smoke-сценарий

Что проверяет `make smoke` (скрипт пишется своими руками, это пара десятков строк на bash):

1. создать ссылку через nginx (`POST /api/links`) и пройти по редиректу `/r/<code>`;
2. остановить одну реплику linkd — редиректы продолжают работать;
3. остановить PostgreSQL — `/readyz` через nginx отвечает 503, `/healthz` жив;
   запустить обратно — linkd снова готов без рестарта;
4. `down` → `up` — созданная ссылка на месте;
5. каждая строка логов linkd проходит через `jq .`.

### 6. README и ADR

- Раздел «Локальный запуск»: `cp compose/.env.example compose/.env`, `make up`, `make smoke`.
- Таблица замеров из шага 4.
- ADR «Почему linkd 2.0 хранит данные в PostgreSQL» — своими словами, с опорой на то,
  что выяснилось в compose-задаче 04-shipyard про две реплики и один файл SQLite.

### 7. Коммит

```bash
git add docker compose .dockerignore Makefile README.md docs/adr
git commit -m "build: container image and local compose stand for linkd 2.0"
```text
---

## ✅ Критерии приёмки

- [ ] Образ меньше 100 МБ, работает не от root, внутри нет `.git`, `tests/`, `tools/`, `infra/`, `.env`
- [ ] `docker inspect` показывает `healthy`, проверка идёт на `/healthz`
- [ ] Метки OCI содержат SHA коммита и версию
- [ ] Пересборка после правки `app/` не переустанавливает зависимости
- [ ] `docker stop` занимает секунды, а не 10
- [ ] `make up` с нуля поднимает стенд без ручных шагов; `make smoke` зелёный
- [ ] Данные PostgreSQL переживают `down`/`up`
- [ ] `.env` не в git, в `docker history --no-trunc` нет паролей
- [ ] Таблица замеров и ADR лежат в репо

---

## 🪤 Грабли

- **`.dockerignore` не там.** Docker читает его из корня контекста сборки, а не из
  каталога с Dockerfile. Dockerfile переехал в `docker/` — проверь, что игнор всё ещё действует.
- **Healthcheck остался на `/health`.** Контейнер `healthy`, а БД лежит — ровно та
  ситуация, от которой спасает разделение `/healthz` и `/readyz`.
- **Пароль БД прямо в compose-файле.** Остаётся в истории git навсегда. Только `.env`
  вне git и `.env.example` с пустыми значениями.
- **Порт PostgreSQL `5432:5432` без `127.0.0.1`.** На машине с публичным IP БД открыта
  миру, причём Docker обходит правила `ufw`.
- **`depends_on` без `condition`** ждёт только запуска контейнера, а не готовности БД.
- **Забыт `LINKD_DATABASE_URL`.** linkd молча работает на SQLite внутри контейнера:
  у каждой реплики своя база, ссылка, созданная через одну, «не находится» через другую.
  Проверка — поле `storage` в `/health`.
- **Пароль в `LINKD_DATABASE_URL` со спецсимволами** (`@`, `/`, `:`) ломает разбор URI —
  такие символы кодируются, а пароль для стенда проще генерировать без них.
- **Мажорная версия PostgreSQL в образе.** Начиная с 18-й официальный образ хранит данные
  по другому пути, и старый том «пропадает». Версию пинь и сверяйся с описанием образа.
- **`docker compose down -v`** удаляет именованные тома вместе с данными.
- **Секреты в `ARG`/`ENV`** остаются в `docker history`, даже если следующей строкой
  их «удалить».

---

## 🤔 Вопросы себе

1. Чем multi-stage сборка лучше, чем `rm -rf` кэша в том же слое?
2. Что пересоберётся, если поменять одну строку в `app/`? А в файле зависимостей?
3. Почему процесс в контейнере не должен работать от root, если есть namespaces?
4. Чем `HEALTHCHECK` в Dockerfile отличается от probes в Kubernetes и учитывает ли его k8s?
5. Что будет с данными PostgreSQL при `down`, `down -v`, удалении контейнера?
6. Почему две реплики linkd 1.x на общем файле SQLite — плохая идея, а с PostgreSQL — нормальная?
7. Как по образу, работающему в проде, найти коммит, из которого он собран?
8. Как уменьшить образ ещё сильнее и чем за это придётся заплатить (distroless, alpine)?

---

## 📚 Теория в волте

- Dockerfile и директивы: [../Docker/03_dockerfile.md](/docker/03-dockerfile)
- Кэш и multi-stage: [../Docker/04_build_cache_multistage.md](/docker/04-build-cache-multistage)
- Registry, теги, метки: [../Docker/05_registry_tags.md](/docker/05-registry-tags)
- Жизненный цикл, сигналы, PID 1: [../Docker/06_containers_lifecycle.md](/docker/06-containers-lifecycle)
- Тома: [../Docker/07_volumes_storage.md](/docker/07-volumes-storage)
- Compose: [../Docker/09_compose.md](/docker/09-compose)
- Безопасность образов: [../Docker/10_security_best_practices.md](/docker/10-security-best-practices)
- Когда что-то не стартует: [../Docker/11_troubleshooting.md](/docker/11-troubleshooting)
- Docker и файрвол: [../Network/11_firewall_iptables.md](/network/11-firewall-iptables)
- nginx как reverse proxy и балансировка: [../Network/12_nginx.md](/network/12-nginx),
  [../Network/13_haproxy_balancing.md](/network/13-haproxy-balancing)

➡️ Следующий этап: [03_ci.md](/project/03-ci)
