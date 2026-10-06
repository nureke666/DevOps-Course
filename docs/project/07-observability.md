---
title: "07. Наблюдаемость: метрики, логи, трейсы и алерты по SLO"
description: "SLO, алерты с тестами, логи, трейсы"
---

# 07. Наблюдаемость: метрики, логи, трейсы и алерты по SLO

> **Цель этапа:** собрать в портфолио результаты 08-observatory и 14-pulse так, чтобы
> linkd 2.0 наблюдался в том окружении, где он реально работает: SLO записан, алерты
> по burn rate покрыты тестами и доходят до Telegram, от алерта можно дойти до логов
> и трейса.
>
> **После этапа у тебя есть:** каталог `observability/` (правила + promtool-тесты,
> дашборды, Alertmanager, сценарии k6), `docs/slo.md`, `runbooks/`, постмортем из 14-pulse,
> job проверки правил в CI, раздел «Наблюдаемость» в README со скриншотами.
>
> **~время:** 4–8 часов (после проектов).

---

## 🧪 Откуда берём

| Проект | Что забираешь | Когда готово |
|--------|---------------|--------------|
| 🛠️ **08-observatory** — наблюдаемость · `README` · `~/Projects/devops/08-observatory` | `stack/` (конфиги Prometheus, Loki, сборщика, Alertmanager), `rules/`, дашборды, `queries.md`, runbook'и | `./check.sh` зелёный |
| 🛠️ **14-pulse** — SRE: SLO, алерты, трейсинг · `README` · `~/Projects/devops/14-pulse` | SLI/SLO, recording rules, burn-rate алерты и их promtool-тесты, сценарии k6, настройка трейсинга в Tempo, постмортем | `./check.sh` зелёный |
| 🛠️ **10-toolsmith** · `README` · `~/Projects/devops/10-toolsmith` | свой exporter — ещё одна цель для Prometheus | уже в `tools/` (этап 01) |

---

## 🎯 Цель

Поднимать стек уже научили проекты. Здесь задача другая: **наблюдать свой сервис
осмысленно и доказуемо**. Разница между «Grafana установлена» и «эксплуатация понятна» —
в ответах на вопросы:

- какой SLO у linkd, откуда цифра и сколько бюджета ошибок осталось;
- почему алертов именно столько и на что каждый;
- как от сообщения в Telegram дойти до строки лога и медленного спана.

Что меняется по сравнению с проектами:

- 08-observatory работал с метриками linkd 1.x. В 2.0 они сохранены под теми же
  именами, так что правила и дашборды проекта продолжают работать, а сверху добавились
  счётчик запросов с `code`, гистограмма задержек, `linkd_errors_total`, `linkd_db_up`,
  `linkd_build_info`. Список «чего не хватает» из `queries.md` 08-observatory против
  того, что принёс 2.0, — хороший абзац для README;
- правила и дашборды — **один набор файлов** для любого окружения, и CI проверяет его
  так же, как код.

---

## 🗺️ Что получится

```text:no-line-numbers
 linkd-platform/observability/
 ├── rules/          recording + alerting (08 + 14) — единственный источник правил
 ├── tests/          promtool test rules (14-pulse) — гоняет CI
 ├── dashboards/     JSON: RED/USE сервиса, SLO-дашборд
 ├── alertmanager/   маршрутизация и группировка (08) + получатель Telegram
 ├── load/           сценарии k6 (14-pulse) — для демо и проверки SLO под нагрузкой
 └── README.md       где что запускается
 docs/slo.md · runbooks/*.md · docs/postmortems/

 🥉 минимум: стек из 08/14 в compose рядом со стендом этапа 02
 🥇 полная:  в кластере через Argo (linkd-gitops/apps/platform/)
     linkd /metrics ◄── ServiceMonitor ── Prometheus ── правила из observability/rules
     stdout (JSON) ──► Alloy ──► Loki ──┐
     OTel ──────────────────► Tempo ────┼──► Grafana (дашборды из observability/)
     Alertmanager ──► Telegram          │
```

---

## 🪜 Шаги

### 1. Проекты зелёные

```bash
cd ~/Projects/devops/08-observatory && ./check.sh
cd ~/Projects/devops/14-pulse && ./check.sh
```

### 2. Перенос

Правила, тесты, дашборды, конфиг Alertmanager и сценарии k6 → `observability/`.
Runbook'и из 08-observatory → `runbooks/` в корне (на них ссылаются `runbook_url`).
Постмортем из 14-pulse → `docs/postmortems/`.

### 3. Привести к linkd 2.0

Метрики 1.x в 2.0 на месте, поэтому правила и панели 08-observatory не ломаются. Реши,
что из них остаётся, а что честнее считать по `linkd_http_requests_total` и
`linkd_request_duration_seconds` (например, ошибки — по `code`, а не по одному счётчику).
Правила 14-pulse — главные для SLO. После правки — `promtool test rules` зелёный на
**тех же** файлах, что будут загружены в Prometheus.

### 4. Где работает стек

- **Минимум:** compose-стек из проектов рядом со стендом этапа 02, правила и дашборды
  монтируются из `observability/`.
- **Полная:** kube-prometheus-stack, Loki + Alloy, Tempo — Argo-приложения в
  `linkd-gitops/apps/platform/`, их values — в `linkd-gitops/platform/`. linkd
  подключается ServiceMonitor'ом из чарта. Правила и дашборды попадают в кластер из тех
  же файлов `observability/` — через шаблон чарта или генератор ConfigMap; выбери способ
  и опиши его в `observability/README.md`.

Главное требование к обоим вариантам: **нет второй копии правил**, которая тихо
разъезжается с проверенной.

### 5. SLO — `docs/slo.md`

Цифры берутся из 14-pulse, формулировки — свои:

```markdown
# SLO linkd

| | |
|---|---|
| SLI доступности | доля запросов … среди … (что считается «плохим» ответом, какие пути входят и почему) |
| SLI задержки | доля запросов быстрее … мс |
| Цель | …% за … дней |
| Бюджет ошибок | …% запросов ≈ … минут полного простоя |
| Алерты | быстрое и медленное сгорание: окна, пороги, severity |
| Что не входит | служебные эндпоинты, 4xx по вине клиента, … |
```

### 6. Алерты и доставка

Состав — на уровне смысла, выражения уже есть в проектах:

| Алерт | Про что | Откуда |
|-------|---------|--------|
| Быстрое сгорание бюджета | пользователи массово получают ошибки | 14-pulse |
| Медленное сгорание бюджета | тихая деградация | 14-pulse |
| Высокая задержка | сервис медленный | 08 / 14 |
| Нет целей для скрейпа | «мы ослепли» | добавить |
| Бэкап устарел / restore-test упал | данные не защищены | этап 09 |

У каждого — `runbook_url` на файл в `runbooks/` публичного репо. Получатель — Telegram:
токен бота и chat_id не в git (пока — Secret руками, на этапе 08 — Vault).

### 7. Логи и трейсы

- JSON-логи linkd → Loki; лейблы — то, по чему выбирают поток (namespace, app, level),
  всё остальное — в теле строки;
- переход «всплеск на графике → логи за то же время» из 08-observatory работает и в
  новом окружении;
- трейсы включаются values чарта (`OTEL_EXPORTER_OTLP_ENDPOINT`, OTLP/HTTP) → Tempo
  или коллектор перед ним; в образе должны быть пакеты из `requirements-otel.txt`;
- при включённых трейсах linkd пишет `trace_id` в JSON-лог — настрой переход из строки
  лога в трейс (derived field в datasource Loki) и обратно.

### 8. CI

Job из этапа 03: `promtool check rules` и `promtool test rules` по `observability/`,
проверка, что JSON дашбордов валиден. Запускается при изменениях в `observability/`.

### 9. Проверка вживую — через фолты linkd

- `LINKD_FAULT_ERROR_RATE` в values dev → через несколько минут быстрый burn-rate алерт
  в Telegram → фолт выключен → `RESOLVED`. Засеки время и объясни его (окна, `for`,
  `group_wait`).
- `LINKD_FAULT_LATENCY_MS` → алерт задержки + медленный спан в Tempo.
- Нагрузка — сценарием k6 из `observability/load/`, чтобы графики были живыми.
  Фолты действуют **только на `/r/*`** — сценарий должен ходить по редиректам,
  иначе «инцидента» не будет.

В GitOps фолт включается **коммитом** в values: ручной `kubectl set env` self-heal
откатит — и это тоже можно показать.

### 10. README, скриншоты, ADR

- Раздел «Наблюдаемость»: SLO одной таблицей, список алертов, схема сбора.
- Скриншоты: дашборд во время учебного инцидента, FIRING и RESOLVED в Telegram,
  трейс с медленным спаном.
- ADR «SLO …% и multiwindow burn rate»: почему алерты на симптом, а не на CPU.

### 11. Коммит

```bash
git add observability runbooks docs README.md .gitlab-ci.yml
git commit -m "observability: SLO, tested burn-rate alerts, dashboards, tracing"
```

---

## ✅ Критерии приёмки

- [ ] Правила и дашборды — один набор файлов в `observability/`, CI гоняет `promtool test rules`
- [ ] Цели linkd в Prometheus `up` в каждом окружении; ложных алертов нет
- [ ] `docs/slo.md` заполнен: SLI, цель, бюджет, окна burn rate
- [ ] Быстрый burn-rate алерт, вызванный фолтом, пришёл в Telegram, пришёл и `RESOLVED`; время записано
- [ ] У каждого алерта есть `runbook_url`, runbook'и лежат в `runbooks/`
- [ ] Логи ищутся по namespace/app/level; от графика можно перейти к логам за то же время
- [ ] (полная) трейс с задержкой из `LINKD_FAULT_LATENCY_MS` виден в Tempo
- [ ] Токен бота и пароль Grafana не лежат в git
- [ ] Фолты после проверки выключены

---

## 🪤 Грабли

- **<code v-pre>{{ $value }}</code> в правилах внутри Helm-шаблона** — Helm пытается отрендерить это сам
  и падает. Такие строки экранируются.
- **ServiceMonitor есть, цели нет.** Частые причины: селектор не совпадает с лейблами
  Service; порт указан номером, а не именем; Prometheus выбирает ServiceMonitor'ы только
  с определённым лейблом; NetworkPolicy режет доступ из namespace мониторинга (этап 08).
- **Большие CRD kube-prometheus-stack** не влезают в client-side apply — нужен server-side.
- **Кардинальность в Loki.** `path`, `trace_id`, `duration_ms` из JSON-лога в лейблы
  нельзя — только в тело строки, фильтровать их можно парсером в запросе.
- **Панель «пропала» во время инцидента.** `linkd_links_total` и `linkd_redirects_total`
  не выводятся, пока база недоступна, — это поведение linkd, а не поломка стека.
  Для «база жива?» есть `linkd_db_up`.
- **Трейсов нет, хотя endpoint задан.** В образе не установлены пакеты из
  `requirements-otel.txt` — в логе linkd одно предупреждение `tracing disabled`.
- **Тесты проверяют не тот файл.** `promtool` зелёный на копии, а в Prometheus загружена
  другая версия правил.
- **Отношение при нулевом трафике** даёт `NaN`, и алерт молчит — для «сервис не
  отвечает вообще» нужен отдельный алерт на отсутствие целей.
- **Одинаковый дашборд из двух namespace** — Grafana видит два дашборда с одним `uid`.
- **Фолт включён, а алерт молчит** — нагрузка ходит только в `/api/links`, а фолты
  действуют на `/r/*`.
- **Фолт забыт включённым** — на следующий день «сервис сломался» и горит бюджет.

---

## 🤔 Вопросы себе

1. Что такое SLI, SLO, SLA и бюджет ошибок? Какие у linkd цифры и откуда они взялись?
2. Что такое burn rate и зачем два окна в одном алерте?
3. Чем RED отличается от USE и к чему в портфолио применяется каждый?
4. Почему алертим на симптомы (ошибки, задержка), а не на «CPU > 80%»?
5. Как Prometheus находит поды linkd? Что делает Prometheus Operator?
6. Почему p95 считается через `histogram_quantile`, а не средним? Почему нельзя усреднять перцентили?
7. Как от алерта в Telegram дойти до причины: дашборд → логи → трейс?
8. Что добавил linkd 2.0 для четырёх золотых сигналов по сравнению с 1.x?
9. Что будет, если упадёт сам Prometheus? Как об этом узнать?

---

## 📚 Теория в волте

- Основы, SLI/SLO: [Мониторинг: 01. Основы мониторинга](/monitoring/01-monitoring-concepts),
  [SRE: 02. SLI, SLO и error budget](/sre/02-sli-slo-error-budget)
- Prometheus и service discovery: [Мониторинг: 02. Prometheus: архитектура и сбор](/monitoring/02-prometheus-basics)
- PromQL, histogram_quantile: [Мониторинг: 03. Типы метрик и PromQL](/monitoring/03-promql)
- Alertmanager, маршрутизация, inhibit: [Мониторинг: 05. Алерты и Alertmanager](/monitoring/05-alertmanager)
- Grafana, provisioning: [Мониторинг: 06. Grafana](/monitoring/06-grafana)
- RED, USE, золотые сигналы: [Мониторинг: 07. Что мониторить: 4 сигнала, USE, RED, SLO](/monitoring/07-what-to-monitor)
- Loki и сборщики: [Логирование: 03. Loki + Grafana](/logging/03-loki-grafana),
  [Логирование: 04. Сборщики логов](/logging/04-collectors),
  [Логирование: 05. Источники логов](/logging/05-log-sources)
- Трейсинг: [SRE: 03. Трейсинг и OpenTelemetry](/sre/03-tracing-opentelemetry)
- Инциденты и постмортемы: [SRE: 04. Инцидент-менеджмент и on-call](/sre/04-incident-management),
  [SRE: 05. Постмортемы](/sre/05-postmortems)
- Мониторинг PostgreSQL: [Базы данных: 07. Мониторинг баз данных](/databases/07-db-monitoring)

➡️ Следующий этап: [08. Секреты и безопасность](/project/08-secrets-security)
