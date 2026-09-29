---
title: "01. Приложение: linkd 2.0 и контракт с платформой"
description: "Цель этапа: положить в linkd-platform сервис linkd 2.0 и собственные утилиты вокруг"
---

# 01. Приложение: linkd 2.0 и контракт с платформой

> **Цель этапа:** положить в `linkd-platform` сервис linkd 2.0 и собственные утилиты вокруг
> него, а контракт «что сервис обещает платформе» записать так, чтобы на него опирались
> все следующие этапы.
>
> **После этапа у тебя есть:** репозиторий `linkd-platform` с `app/` (linkd 2.0 + CHANGELOG),
> `tools/` (свой код на Python с тестами), `docs/app-contract.md`, заведённый
> `docs/journal.md` и разделы «Что это» и «Сервис» в README.
>
> **~время:** 2–4 часа (после проектов).

---

## 🧪 Откуда берём

| Проект | Что забираешь | Когда готово |
|--------|---------------|--------------|
| 🛠️ **09-ledger** — эксплуатация PostgreSQL · `README` · `~/Projects/devops/09-ledger` | `app/` — linkd 2.0 и `app/CHANGELOG.md` | приложение можно брать сразу; сам проект понадобится к этапу 09 |
| 🛠️ **10-toolsmith** — автоматизация на Python · `README` · `~/Projects/devops/10-toolsmith` | CLI к API linkd, анализатор логов, exporter, утилиту бэкапа, тесты → `tools/` | `./check.sh` зелёный |
| 🛠️ **02-nightshift** — ночной регламент · `README` · `~/Projects/devops/02-nightshift` | `deploy/POSTMORTEM.md` → `docs/postmortems/`; идеи hardening юнита (пригодятся в роли Ansible, этап 04) | `./check.sh` зелёный; для портфолио — по желанию |

> 💡 Главный источник правды о приложении —
> `CHANGELOG` ·
> `~/Projects/devops/09-ledger/app/CHANGELOG.md`. Он сам себя называет контрактом
> приложения. Если имена переменных, эндпоинтов или метрик в этой заметке разошлись
> с ним — прав CHANGELOG.

---

## 🎯 Цель

Девопсу не нужно писать бизнес-код, но нужно понимать, **что платформа ожидает от
приложения**, и уметь это сформулировать. linkd 2.0 уже умеет всё нужное: PostgreSQL
(по `LINKD_DATABASE_URL`), отдельные liveness/readiness, RED-метрики с гистограммой,
JSON-логи, трейсы и учебные «фолты». Задача этапа — выписать из CHANGELOG то, что важно
**платформе**, в свой `docs/app-contract.md`, на который ссылаются Dockerfile, чарт,
алерты и runbook'и.

И сразу о честности: **linkd написан не тобой.** Это учебный сервис из практики,
и так и пишется в README. Твоя работа — всё вокруг него, а твой собственный код —
`tools/` из 10-toolsmith. Такая формулировка выдерживает любой уточняющий вопрос;
«сервис — мой» — нет.

### 📜 Контракт linkd 2.0 с платформой

| Требование | Как у linkd 2.0 | Кто этим пользуется |
|-----------|-----------------|---------------------|
| Конфиг только из env (12-factor) | `LINKD_PORT`, `LINKD_LOG_FORMAT`, `LINKD_DATABASE_URL`; пустой URL = SQLite по умолчанию | compose, Helm values + Secret, шаблоны Ansible |
| «Процесс жив» | `GET /healthz` — в базу не ходит | Docker `HEALTHCHECK`, livenessProbe |
| «Готов принимать трафик» | `GET /readyz` — база доступна и таблица есть, иначе 503 | readinessProbe, Service, балансировщик |
| Совместимость с 1.x | `GET /health` — как в 1.x + `version`, `storage`; 500 при недоступной базе | healthcheck из 02-nightshift, старые проверки |
| Метрики | все метрики 1.x + `linkd_http_requests_total{method,path,code}`, гистограмма `linkd_request_duration_seconds{path}`, `linkd_errors_total`, `linkd_db_up`, `linkd_build_info{version,storage}` | Prometheus, SLI/SLO, алерты |
| Логи | stdout; `LINKD_LOG_FORMAT=json` — одна строка = один JSON, пароль из URL замаскирован | journald, Loki |
| Трейсы | `OTEL_EXPORTER_OTLP_ENDPOINT` (OTLP/HTTP) **и** пакеты из `requirements-otel.txt`; `trace_id` попадает в JSON-лог | Tempo |
| Учебные фолты | `LINKD_FAULT_LATENCY_MS`, `LINKD_FAULT_ERROR_RATE` — только на `/r/*` | демо, учения, проверка алертов |
| Схема БД | таблицу linkd создаёт сам, если её нет, с повтором раз в 2 с; для готовой таблицы роли хватает `SELECT, INSERT, UPDATE` | 09-ledger, compose, чарт |
| Подключения | новое подключение на каждый запрос, пула нет | планирование нагрузки, PgBouncer |
| Состояние | только в базе | несколько реплик, rolling update |
| Остановка | корректно по SIGTERM/SIGINT, за полсекунды | `systemctl stop`, `docker stop`, kubelet |

API: `POST /api/links`, `GET /api/links`, `GET /r/<code>` — редирект 302.

---

## 🗺️ Что получится

```text
linkd-platform/
├── app/                     ← копия 09-ledger/app: linkd 2.0
│   ├── linkd.py, requirements.txt, requirements-otel.txt
│   └── CHANGELOG.md         ← контракт от авторов сервиса
├── tools/                   ← твой код из 10-toolsmith
│   ├── …                    CLI, анализатор логов, exporter, бэкап
│   └── tests/
├── docs/
│   ├── app-contract.md      ← таблица выше + что из неё использует каждый этап
│   ├── journal.md           ← истории поломок со всех проектов
│   └── postmortems/         ← POSTMORTEM.md из 02-nightshift
├── .gitignore
└── README.md                ← пока: «Что это» и «Сервис»
```text
---

## 🪜 Шаги

### 1. Проекты зелёные

```bash
cd ~/Projects/devops && ./progress.sh
cd ~/Projects/devops/10-toolsmith && ./check.sh
```text
Приложение из 09-ledger брать можно и до окончания проекта — это просто код сервиса.

### 2. Заводишь репозитории

На gitlab.com — два пустых **публичных** проекта: `linkd-platform` и `linkd-gitops`
(почему GitLab — этап 03: там живёт CI из 05-conveyor). Локально — рядом с практикой,
а не внутри неё:

```bash
mkdir -p ~/Projects/linkd-platform && cd ~/Projects/linkd-platform && git init -b main
```text
### 3. Переносишь приложение

Копия `09-ledger/app/` → `app/`: `linkd.py`, `requirements.txt` (драйвер PostgreSQL),
`requirements-otel.txt` (трейсы, необязательно), `CHANGELOG.md`. Не переносятся: файлы
баз, дампы, `__pycache__`, `.env`, всё из обвязки проекта (`TASKS.md`, `check.sh`,
`.state/`). В `.gitignore` — `__pycache__/`, `.venv/`, `.env`, `*.db`, локальные дампы.

### 4. Проверяешь контракт руками

Запусти linkd 2.0 с PostgreSQL так, как это делается в 09-ledger, и пройди по таблице
контракта. Минимальный набор проверок:

- `/health` показывает `storage` — это PostgreSQL, а не SQLite по умолчанию;
- `/healthz` и `/readyz` отвечают 200;
- PostgreSQL остановлен → `/readyz` отвечает 503, а `/healthz` по-прежнему 200;
  PostgreSQL вернулся → linkd сам снова готов, без рестарта;
- после пары запросов в `/metrics` есть `linkd_http_requests_total` и
  `linkd_request_duration_seconds_bucket`, а `path` для редиректов — `/r/:code`;
- с `LINKD_LOG_FORMAT=json` каждая строка лога проходит через `jq .`;
- с `LINKD_FAULT_ERROR_RATE` часть ответов на `/r/*` — 500: растут `linkd_errors_total`
  и ряд с `code="500"`;
- SIGTERM — процесс выходит сразу, код возврата 0.

Результат — в `docs/app-contract.md`: что проверено и какой командой.

### 5. Переносишь свои утилиты

Утилиты из 10-toolsmith → `tools/` вместе с тестами. Что добавить сверху:

- адрес linkd, креды MinIO и прочее — из аргументов/переменных, без захардкоженных
  значений из учебного стенда;
- тесты запускаются одной командой из корня репо — её потом вызовет CI (этап 03);
- `tools/README.md`: что делает каждая утилита, пример запуска, какие переменные нужны.

Утилита бэкапа понадобится на этапе 09, exporter — на этапе 07.

### 6. История сервиса

`POSTMORTEM.md` из 02-nightshift → `docs/postmortems/` с датой в имени.
Это готовая «история про сложную проблему» для собеса: legacy-скрипт, битые бэкапы,
разбор причин. Юнит из 02 в портфолио отдельно не кладётся — его идеи (non-root,
рестарт, ограничения) переедут в шаблон роли Ansible на этапе 04.

### 7. Журнал

`docs/journal.md` заводится сейчас, а наполняется весь блок. Формат строки:

```markdown
## 2026-10-02 — docker stop ждал 10 секунд
- Симптом: …
- Как искалась причина: …   ← главное — шаги диагностики, а не только ответ
- Причина: …
- Решение и что вынесено: …
```text
Сразу перенеси туда 2–3 истории из уже пройденных проектов и 99-incidents.

### 8. README: первые разделы

```markdown
# linkd-platform

> Платформа доставки и эксплуатации для учебного сервиса коротких ссылок linkd:
> CI → registry → GitOps → Kubernetes, мониторинг по SLO, секреты в Vault,
> проверенное восстановление из бэкапа.

## Сервис
linkd 2.0 — учебный сервис (Python, PostgreSQL). Не мой код: мой — всё вокруг
и утилиты в tools/. Контракт с платформой — docs/app-contract.md.
```text
### 9. Коммит

```bash
git add . && git commit -m "feat: linkd 2.0 app, own tools and service contract"
```text
---

## ✅ Критерии приёмки

- [ ] `app/` совпадает с linkd 2.0 из 09-ledger, `CHANGELOG.md` на месте
- [ ] В репо нет файлов обвязки практики, локальных баз, `.env`
- [ ] Каждая строка контракта проверена руками, команды записаны в `docs/app-contract.md`
- [ ] `tools/` запускается без правок кода под чужую машину, тесты зелёные одной командой
- [ ] В README честно сказано, чей код сервис и чей — всё остальное
- [ ] `docs/journal.md` содержит минимум 2 реальные истории
- [ ] Код в git, в `git status` чисто

---

## 🪤 Грабли

- **«Этот сервис — мой».** Первый же вопрос про устройство кода — и неловкая пауза.
  Формулировка «учебный сервис, моя — платформа и утилиты» сильнее и честнее.
- **Контракт расходится с CHANGELOG.** Таблица переписана по памяти — и в чарте проба
  на несуществующий путь. Сверяйся с CHANGELOG, а не с этой заметкой.
- **Пробы на `/health` из 1.x.** Работает, но не отличает «жив» от «готов» — ради
  этого и появились `/healthz` и `/readyz`.
- **Утилиты привязаны к учебному стенду:** адреса и имена бакетов зашиты в код.
  В портфолио их запускают на другой машине — всё через аргументы и переменные.
- **Копирование всего каталога проекта** вместе с `check.sh`, `TASKS.md` и подсказками —
  портфолио превращается в выложенные ответы к чужому курсу.
- **Фолты включены по умолчанию.** Учебные ошибки и задержки — только явным включением,
  иначе «сервис глючит» уже на первом скриншоте.
- **Забыт `LINKD_DATABASE_URL`.** linkd молча стартует на SQLite — это режим по
  умолчанию. В контейнере данные пропадают при пересоздании, а две реплики живут
  каждая со своей базой. Выдаёт это поле `storage` в `/health` и метка `storage`
  у `linkd_build_info`.
- **Кардинальность своих метрик.** linkd нормализует метку `path` (`/r/:code`, `other`),
  чтобы число рядов не росло. У метрик exporter'а из `tools/` — та же дисциплина.

---

## 🤔 Вопросы себе

1. Чем liveness отличается от readiness и что будет, если перепутать их ручки?
2. Почему `/readyz` проверяет PostgreSQL, а `/healthz` — нет?
3. Какие факторы 12-factor app видны в linkd 2.0, а каких не хватает?
4. Зачем сервису учебные фолты и почему их нельзя включать в проде «на всякий случай»?
5. Что происходит с запросами «в полёте», когда процесс получает SIGTERM?
6. Почему у метрик мало лейблов, а у логов — много полей?
7. Что именно в `tools/` — твой код, как он тестируется и что будет, если linkd недоступен?
8. linkd открывает новое подключение к PostgreSQL на каждый запрос. Чем это грозит
   под нагрузкой и что с этим делают?
9. Как изменился бы контракт, если бы в linkd появился кэш (Redis)?

---

## 📚 Теория в волте

- Сигналы и корректное завершение: [../Linux/07_processes.md](/linux/07-processes),
  [../Docker/06_containers_lifecycle.md](/docker/06-containers-lifecycle)
- Probes: [../Kubernetes/09_probes_resources.md](/kubernetes/09-probes-resources)
- Метрики и их типы: [../Left/02_Monitoring/03_promql.md](/monitoring/03-promql),
  свои метрики — [../Left/02_Monitoring/04_exporters.md](/monitoring/04-exporters)
- RED/USE: [../Left/02_Monitoring/07_what_to_monitor.md](/monitoring/07-what-to-monitor)
- Структурные логи: [../Left/03_Logging/01_logging_concepts.md](/logging/01-logging-concepts)
- PostgreSQL глазами девопса: [../Left/01_Databases/01_db_for_devops.md](/databases/01-db-for-devops)
- Утилиты на Python: [../Python/04_cli_logging_config.md](/python/04-cli-logging-config),
  [../Python/05_http_api.md](/python/05-http-api),
  [../Python/08_packaging_quality.md](/python/08-packaging-quality)
- Постмортемы: [../SRE/05_postmortems.md](/sre/05-postmortems)
- HTTP-коды и редиректы: [../Network/06_http.md](/network/06-http)
- Коммиты и ветки: [../../IT/Git/02_basics_workflow.md](/git/02-basics-workflow)

➡️ Следующий этап: [02_docker.md](/project/02-docker)
