---
title: "08. Портал разработчика: Backstage"
description: "Блок → Platform Engineering → единая точка входа. Зачем портал и как мерить платформу —"
---

# 08. Портал разработчика: Backstage

> Блок → Platform Engineering → **единая точка входа**. Зачем портал и как мерить платформу —
> [01_platform_engineering.md](/platform/01-platform-engineering); GitOps и App of Apps —
> [../Left/07_ArgoCD/04_app_of_apps.md](/argocd/04-app-of-apps).
> Вопросы собеса: *«Как у вас узнают, кто владелец сервиса?»*, *«Как создаётся новый сервис?»*,
> *«Внедряли Backstage? Сколько стоит его поддерживать?»*
> **После темы ты умеешь:** описать linkd в каталоге (`catalog-info.yaml` с владельцем, системой,
> API, базой и аннотациями ArgoCD/Kubernetes/GitLab), написать шаблон «новый сервис по golden path»
> (репозиторий из скелета с Dockerfile, CI, LinkdApp и catalog-info → публикация → регистрация),
> подключить TechDocs и плагины Kubernetes/ArgoCD, запустить Backstage локально и объяснить,
> как внедрять портал и мерить его пользу — или почему вам хватит README.
> Версии — «проверь, сентябрь 2026».

---

## 🗺️ Карта темы

```text
                         Backstage (localhost:3000 UI, :7007 backend)
 ┌───────────────────────────────────────────────────────────────────────────────┐
 │ Каталог: Component linkd ─ owner ─► Group team-a ─ system ─► System shortener │
 │            │ providesApi linkd-api  │ dependsOn Resource linkd-db             │
 │ Вкладки сервиса: CI (GitLab) · Kubernetes (поды) · ArgoCD (sync) · Docs · API │
 │ Шаблоны (scaffolder): «Новый сервис linkd-стиля» → форма → шаги               │
 │ TechDocs: docs/ из репозитория сервиса → HTML в портале                       │
 └──────────┬───────────────────────┬──────────────────────────┬────────────────┘
            │ читает catalog-info   │ fetch:template →          │ API кластера,
            ▼                       ▼ publish:gitlab →          ▼ ArgoCD API
     GitLab / GitHub          новый репозиторий          kind: LinkdApp, Deployment,
     (discovery)              + catalog:register         Application в ArgoCD
```text
---

## 1. Что такое Backstage и сколько он стоит

**Backstage** — open source-фреймворк портала разработчика от Spotify (проект CNCF).
Это не готовый продукт, а **приложение на TypeScript/React**, которое ты собираешь из плагинов,
деплоишь и обновляешь сам. Три опоры: **каталог**, **шаблоны** (scaffolder), **TechDocs**.

| Факт (проверь, сентябрь 2026) | |
|-------------------------------|---|
| Версия | **v1.55.2** (25.09.2026), новая минорная примерно раз в месяц |
| Создание приложения | `npx @backstage/create-app@latest`; свежие версии генерируют **новую frontend-систему** (`@backstage/frontend-defaults`), старая — флаг `--legacy` |
| Backend | **Новая backend-система**: `createBackend()` + `backend.add(import('...'))` — плагины и модули подключаются одной строкой |
| Требования | Node.js 22 или 24, Yarn 4, Docker, ≥ 6 ГБ RAM и ~20 ГБ диска для локального запуска |
| v1.55 ломает | Удалены устаревшие API каталога, TechDocs режет MkDocs-плагины вне allowlist, Elasticsearch 8.19+ |

| Статья расходов | Реальность |
|-----------------|------------|
| Люди | 1–3 инженера, которые знают TypeScript/React; для команды на Python это новый стек |
| Обновления | Ежемесячные релизы, `yarn backstage-cli versions:bump`, ломающие изменения плагинов |
| Инфраструктура | PostgreSQL, деплой (контейнер в Kubernetes), SSO, секреты интеграций |
| Наполнение | Каталог без данных бесполезен: владельцы, системы, доки — это работа **всех** команд |

> 💡 Честный порог: Backstage окупается, когда сервисов десятки, команд несколько и вопрос
> «чей это сервис и где его доки» стоит дорого. Для 5 сервисов — README и репозиторий шаблонов (§10).

---

## 2. ⭐ Каталог: модель сущностей

| Kind | Что это | Пример для linkd |
|------|---------|------------------|
| **Component** | Единица софта: `type: service / website / library`, `lifecycle: experimental / production / deprecated` | `linkd` — сервис |
| **API** | Интерфейс: `type: openapi / grpc / asyncapi / graphql`, `definition` | `linkd-api` — OpenAPI |
| **System** | Набор компонентов и ресурсов, решающих одну задачу | `shortener` |
| **Domain** | Группа систем по бизнес-области | `growth` |
| **Resource** | Инфраструктура, от которой зависит компонент: база, бакет, очередь | `linkd-db` (LinkdDatabase) |
| **Group** | Команда (`type: team`), иерархия `parent`/`children` | `team-a` |
| **User** | Человек, `memberOf` группы | `nurdaulet` |
| **Location** | Ссылка на другие файлы с сущностями | `url: .../catalog-info.yaml` |
| **Template** | Шаблон scaffolder'а | `linkd-service` |

```yaml
# catalog-info.yaml в корне репозитория linkd
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  name: linkd
  title: linkd — сокращатель ссылок
  description: HTTP-сервис коротких ссылок, PostgreSQL, метрики RED
  tags: [python, http, postgres]
  links:
    - { url: https://linkd.example.kz, title: Прод }
    - { url: https://grafana.example.kz/d/linkd, title: Дашборд, icon: dashboard }
    - { url: https://git.example.kz/team-a/linkd/-/blob/main/docs/runbook.md, title: Runbook }
  annotations:
    gitlab.com/project-slug: team-a/linkd              # вкладка CI (плагин GitLab)
    # github.com/project-slug: team-a/linkd            # то же для GitHub
    backstage.io/techdocs-ref: dir:.                   # mkdocs.yml рядом
    backstage.io/kubernetes-id: linkd                  # поды с меткой backstage.io/kubernetes-id=linkd
    backstage.io/kubernetes-namespace: team-a
    argocd/app-name: linkd-prod                        # вкладка ArgoCD
spec:
  type: service
  lifecycle: production
  owner: group:team-a                                  # ⭐ владелец — команда, не человек
  system: shortener
  providesApis: [linkd-api]
  dependsOn: [resource:linkd-db]
---
apiVersion: backstage.io/v1alpha1
kind: API
metadata: { name: linkd-api, description: REST API linkd }
spec:
  type: openapi
  lifecycle: production
  owner: group:team-a
  system: shortener
  definition:
    $text: ./openapi.yaml                              # файл из того же репозитория
---
apiVersion: backstage.io/v1alpha1
kind: Resource
metadata: { name: linkd-db, description: "PostgreSQL через LinkdDatabase (тема 07)" }
spec: { type: database, owner: group:team-a, system: shortener }
---
apiVersion: backstage.io/v1alpha1
kind: System
metadata: { name: shortener }
spec: { owner: group:team-a, domain: growth }
```text
```yaml
# org.yaml — в репозитории платформы (или синхронизация из GitLab/LDAP/Entra ID)
apiVersion: backstage.io/v1alpha1
kind: Group
metadata: { name: team-a, title: Команда ссылок }
spec:
  type: team
  children: []
  profile: { email: team-a@example.kz }
  # дежурства и чат — аннотациями: pagerduty.com/service-id, slack/телеграм-канал в links
---
apiVersion: backstage.io/v1alpha1
kind: User
metadata: { name: nurdaulet }
spec: { memberOf: [team-a], profile: { email: nurdaulet@example.kz } }
```text
Ссылки на сущности — `kind:namespace/name`, по умолчанию `component:default/linkd`.
Из `owner`, `system`, `dependsOn`, `providesApis` каталог строит **граф связей**: «что сломается,
если упадёт `linkd-db`», «все сервисы команды», «кто потребляет этот API».

---

## 3. Как каталог наполняется и не устаревает

| Способ | Как | Когда |
|--------|-----|-------|
| Статичные Location | `catalog.locations` в `app-config.yaml` | Стенд, org.yaml, шаблоны |
| Регистрация руками | UI → «Register existing component» → URL `catalog-info.yaml` | Первые сервисы |
| ⭐ Discovery | Провайдер `catalog.providers.gitlab` / `github`: сканирует группы и находит `catalog-info.yaml` | Прод: новые репозитории появляются сами |
| Орг-данные | Провайдеры GitLab/GitHub orgs, LDAP, Microsoft Entra ID | Group/User без ручной поддержки |
| Шаблон | `catalog:register` в конце scaffolder | Новые сервисы с первого дня |

```yaml
# app-config.yaml (фрагмент): discovery всех проектов группы в self-hosted GitLab
integrations:
  gitlab:
    - host: git.example.kz
      token: ${GITLAB_TOKEN}
catalog:
  rules:
    - allow: [Component, API, System, Domain, Resource, Group, User, Location, Template]
  providers:
    gitlab:
      company:
        host: git.example.kz
        group: platform-kz                      # сканировать группу и подгруппы
        entityFilename: catalog-info.yaml
        schedule: { frequency: { minutes: 30 }, timeout: { minutes: 3 } }
```text
Каталог устаревает, когда `catalog-info.yaml` живёт отдельно от кода. Правило: **файл в репозитории
сервиса**, меняется тем же MR, что и код; CI проверяет его схему (`owner` существует, `lifecycle`
из списка); discovery сам подхватывает изменения. Сущность, чей файл исчез, становится
**orphan** — её видно фильтром, и платформа чистит их регулярно.

---

## 4. ⭐ Шаблоны: «новый сервис по golden path»

Scaffolder — форма (JSON Schema) + шаги (actions). Шаблон — тоже сущность каталога,
`apiVersion: scaffolder.backstage.io/v1beta3`.

```text
templates/linkd-service/
├── template.yaml
└── skeleton/                          # файлы с подстановками $&#123;&#123; values.* &#125;&#125; (nunjucks)
    ├── app/main.py                    # «hello» на Python c /healthz, /readyz, /metrics
    ├── Dockerfile
    ├── .gitlab-ci.yml                 # сборка, тесты, trivy, push, bump тега в gitops
    ├── deploy/linkdapp.yaml           # LinkdApp (тема 03) — вместо 300 строк чарта
    ├── deploy/database.yaml           # LinkdDatabase (тема 07), {% if values.database %}
    ├── catalog-info.yaml              # owner, system, аннотации — из формы
    ├── mkdocs.yml
    └── docs/index.md                  # «как запустить локально», runbook-заготовка
```text
```yaml
# templates/linkd-service/template.yaml
apiVersion: scaffolder.backstage.io/v1beta3
kind: Template
metadata:
  name: linkd-service
  title: Новый HTTP-сервис (golden path)
  description: Python-сервис с CI, LinkdApp, метриками, доками и записью в каталоге
  tags: [python, recommended]
spec:
  owner: group:platform
  type: service
  parameters:
    - title: Сервис
      required: [name, owner, system]
      properties:
        name:
          title: Имя
          type: string
          pattern: '^[a-z][a-z0-9-]{2,30}$'        # ⭐ ограждение прямо в форме
          ui:autofocus: true
        owner:
          title: Команда-владелец
          type: string
          ui:field: OwnerPicker
          ui:options: { catalogFilter: { kind: Group } }
        system:
          title: Система
          type: string
          ui:field: EntityPicker
          ui:options: { catalogFilter: { kind: System } }
        database: { title: Нужна PostgreSQL, type: boolean, default: false }
    - title: Репозиторий
      required: [repoUrl]
      properties:
        repoUrl:
          title: Где создать
          type: string
          ui:field: RepoUrlPicker
          ui:options: { allowedHosts: [git.example.kz], allowedOwners: [platform-kz] }
  steps:
    - id: fetch
      name: Скелет
      action: fetch:template
      input:
        url: ./skeleton
        values:
          name: $&#123;&#123; parameters.name &#125;&#125;
          owner: $&#123;&#123; parameters.owner &#125;&#125;
          system: $&#123;&#123; parameters.system &#125;&#125;
          database: $&#123;&#123; parameters.database &#125;&#125;
          host: $&#123;&#123; parameters.name &#125;&#125;.apps.example.kz
    - id: publish
      name: Репозиторий
      action: publish:gitlab                      # publish:github / publish:gitea — модулями
      input:
        repoUrl: $&#123;&#123; parameters.repoUrl &#125;&#125;
        defaultBranch: main
        repoVisibility: internal
    - id: gitops
      name: Приложение в ArgoCD
      action: publish:gitlab:merge-request        # MR в gitops-репо: Application для сервиса
      input:
        repoUrl: git.example.kz?owner=platform-kz&repo=gitops
        branchName: add-$&#123;&#123; parameters.name &#125;&#125;
        title: "Добавить $&#123;&#123; parameters.name &#125;&#125;"
        description: Создано шаблоном linkd-service
        sourcePath: ./gitops                      # подготовлен вторым fetch:template (опущен)
        targetPath: apps/$&#123;&#123; parameters.name &#125;&#125;
    - id: register
      name: Каталог
      action: catalog:register
      input:
        repoContentsUrl: $&#123;&#123; steps.publish.output.repoContentsUrl &#125;&#125;
        catalogInfoPath: /catalog-info.yaml
  output:
    links:
      - { title: Репозиторий, url: "$&#123;&#123; steps.publish.output.remoteUrl &#125;&#125;" }
      - { title: Открыть в каталоге, icon: catalog, entityRef: "$&#123;&#123; steps.register.output.entityRef &#125;&#125;" }
```text
```yaml
# skeleton/catalog-info.yaml — подстановки из values
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  name: $&#123;&#123; values.name &#125;&#125;
  annotations:
    backstage.io/techdocs-ref: dir:.
    backstage.io/kubernetes-id: $&#123;&#123; values.name &#125;&#125;
    argocd/app-name: $&#123;&#123; values.name &#125;&#125;
spec:
  type: service
  lifecycle: experimental
  owner: $&#123;&#123; values.owner &#125;&#125;
  system: $&#123;&#123; values.system &#125;&#125;
```text
- Шаги выполняются **по порядку на backend**; у шага есть `if:` и `each:`, в новых версиях —
  `if: $&#123;&#123; failure() &#125;&#125;` для уборки (удалить репозиторий, если дальше упало).
- Встроенные действия: `fetch:template`, `fetch:plain`, `publish:github`, `publish:gitlab`,
  `catalog:register`, `debug:log`; модули — `publish:gitea`, `publish:bitbucket`, `gitlab:*`, `github:*`.
  Список на своём инстансе — `/create/actions`.
- **Template Editor** (`/create/edit`) — прогон формы и шагов в режиме dry-run до публикации шаблона.
- Шаблон — **начало** golden path, а не он сам: платформа поддерживает скелет (обновления
  Dockerfile, CI), иначе через год 40 сервисов живут на 40 версиях скелета.

---

## 5. TechDocs: документация как код

Документация лежит **в репозитории сервиса** (`mkdocs.yml` + `docs/`), ревьюится в том же MR,
а Backstage рендерит её во вкладке Docs. Аннотация — `backstage.io/techdocs-ref: dir:.`.

```yaml
# mkdocs.yml
site_name: linkd
nav:
  - Обзор: index.md
  - Runbook: runbook.md
  - API: api.md
plugins: [techdocs-core]
```text
| Режим | Как | Где |
|-------|-----|-----|
| `techdocs.builder: local` | Backstage сам собирает при открытии (генератор в Docker или локально) | Стенд, маленькие инсталляции |
| `techdocs.builder: external` | CI собирает `npx @techdocs/cli generate` и публикует `techdocs-cli publish` в S3/MinIO/GCS; Backstage только читает | ⭐ Прод: сборка не нагружает портал |

> ⚠️ С v1.55 TechDocs удаляет MkDocs-плагины вне allowlist (с предупреждением в логе);
> нужные разрешают в `techdocs.generator.mkdocs.dangerouslyAllowAdditionalPlugins`.

---

## 6. Плагины: портал показывает то, что уже есть

| Плагин | Что даёт во вкладке сервиса | Что нужно |
|--------|-----------------------------|-----------|
| ⭐ Kubernetes (`@backstage/plugin-kubernetes`; backend уже в create-app, frontend — проверь) | Поды, деплойменты, ошибки, рестарты по всем кластерам | `kubernetes.clusterLocatorMethods` + токен SA с `get/list/watch`; метка `backstage.io/kubernetes-id` на объектах |
| ⭐ ArgoCD (Roadie `@roadiehq/backstage-plugin-argo-cd` или `@backstage-community/plugin-redhat-argocd`) | Sync/Health, история выкаток | Прокси/backend к API ArgoCD, токен read-only; аннотация `argocd/app-name` |
| GitLab / GitHub Actions | Пайплайны, MR | Интеграция + `gitlab.com/project-slug` / `github.com/project-slug` |
| Grafana, Prometheus | Дашборды и алерты сервиса | Аннотации селекторов дашбордов |
| PagerDuty / Opsgenie | Кто дежурит, инциденты | `pagerduty.com/service-id` |
| SonarQube, Trivy/Snyk | Качество и уязвимости | Аннотации проектов |
| Tech Radar, Scorecards (Tech Insights) | Стандарты: «есть ли runbook, SLO, владелец» | Правила проверок |

```yaml
# app-config.yaml: кластер kind для плагина Kubernetes (стенд)
kubernetes:
  serviceLocatorMethod: { type: multiTenant }
  clusterLocatorMethods:
    - type: config
      clusters:
        - name: kind-platform
          url: https://127.0.0.1:&lt;порт из kubectl config view&gt;
          authProvider: serviceAccount
          serviceAccountToken: ${K8S_SA_TOKEN}   # kubectl create token backstage -n backstage --duration=24h
          skipTLSVerify: true                    # только стенд
```text
```ts
// packages/backend/src/index.ts — новая backend-система: плагин = одна строка
backend.add(import('@backstage/plugin-kubernetes-backend'));             // уже есть в create-app
backend.add(import('@backstage/plugin-scaffolder-backend-module-gitlab')); // publish:gitlab
backend.add(import('@backstage/plugin-catalog-backend-module-gitlab'));    // discovery
```text
---

## 7. Auth и права — коротко

- **Вход:** провайдеры GitLab, GitHub, OIDC (Keycloak, Entra ID); локально — `guest`.
  **Sign-in resolver** связывает логин с сущностью `User` в каталоге (по email или имени) —
  без User в каталоге человек не войдёт или будет «без команды».
- **Права:** permission framework — политика (код на TypeScript или готовые модули):
  «удалять сущности может только владелец», «шаблон `prod-db` — только группе platform».
  Дефолт create-app — `allow-all-policy`, в проде его заменяют.
- **Токены интеграций** (GitLab, ArgoCD, Kubernetes) — от сервисных аккаунтов с минимальными
  правами; шаблоны пишут в репозитории от имени бота или от имени пользователя
  (`requestUserCredentials` у RepoUrlPicker).

---

## 🧪 Мини-лаба: Backstage локально, linkd в каталоге и свой шаблон

**Шаг 1. Приложение** (Node 22/24, `corepack enable`, Docker, ~6 ГБ RAM):

```bash
npx @backstage/create-app@latest         # имя: platform-portal
cd platform-portal
yarn start                               # UI http://localhost:3000, backend :7007, вход guest
```text
**Шаг 2. linkd в каталоге.** Положи `catalog-info.yaml` из §2 и `org.yaml` в каталог
`catalog/` рядом и подключи их статично (файлы — относительно `packages/backend`):

```yaml
# app-config.local.yaml (не коммитится)
catalog:
  locations:
    - { type: file, target: ../../catalog/org.yaml, rules: [{ allow: [Group, User] }] }
    - { type: file, target: ../../catalog/linkd/catalog-info.yaml,
        rules: [{ allow: [Component, API, System, Resource] }] }
    - { type: file, target: ../../templates/linkd-service/template.yaml, rules: [{ allow: [Template] }] }
```text
Перезапусти `yarn start`. Проверь: страница `linkd`, вкладка Dependencies (граф с `linkd-db`,
`linkd-api`, `shortener`), «My Groups» у команды `team-a`, вкладка API с OpenAPI.

**Шаг 3. TechDocs.** Добавь `mkdocs.yml` и `docs/index.md` рядом с `catalog-info.yaml` linkd.
Открой вкладку Docs (первый раз генерация идёт в Docker — подожди).

**Шаг 4. Шаблон.** Сделай `templates/linkd-service/` из §4 с публикацией в свой GitHub
(`publish:github` уже есть в create-app; токен — `integrations.github[0].token: ${GITHUB_TOKEN}`,
в `allowedHosts` — `github.com`) или в GitLab (модуль из §6). Прогони в Template Editor,
затем по-настоящему: появился репозиторий, в нём скелет, сервис в каталоге с `lifecycle: experimental`.

**Шаг 5. Kubernetes-вкладка.** Создай в kind ServiceAccount `backstage` с ClusterRole на чтение
подов/деплойментов, токен — в `K8S_SA_TOKEN`, кластер — в конфиг из §6. Поставь на Deployment
linkd метку `backstage.io/kubernetes-id: linkd` — поды появятся во вкладке Kubernetes.

**Проверь себя:** что будет, если в `owner` указать несуществующую группу? Где в UI видно
ошибки обработки сущностей? Почему `catalog-info.yaml` должен лежать в репозитории сервиса, а не
в общем «реестре»?

Уборка: `Ctrl+C`, удалить тестовые репозитории, созданные шаблоном.

---

## 8. Внедрение: сначала польза, потом портал

**Порядок, который работает:**
1. **Каталог реальных сервисов** — импорт discovery из GitLab, владельцы у 100% сервисов прода.
   Уже это отвечает на «чей сервис и где доки» на инцидентах.
2. **Один шаблон** golden path для самого частого случая (HTTP-сервис на Python) — с командой-пилотом.
3. **TechDocs и runbook'и** — ссылка из алерта ведёт в портал.
4. **Плагины** по запросам команд (Kubernetes, ArgoCD, CI) — портал становится местом,
   где смотрят статус, а не только ищут владельца.
5. **Scorecards** — «у сервиса есть SLO, runbook, дежурство» — уже как стандарт, а не как наказание.

| Метрика | Как считать | Цель-ориентир |
|---------|-------------|---------------|
| ⭐ Покрытие каталога | Сервисов в кластерах с сущностью и владельцем / всех сервисов | 90%+ |
| ⭐ Time to first deploy | От запуска шаблона до первого ответа сервиса в dev | Минуты–часы, а не дни |
| Использование шаблонов | Запусков в месяц, доля новых сервисов «через шаблон» | Большинство новых |
| Активные пользователи | WAU портала среди разработчиков | Растёт после каждого плагина |
| Свежесть | Доля сущностей с orphan/ошибками, доков старше года | Снижается |
| Удовлетворённость | Опрос DevEx раз в квартал ([01_platform_engineering.md](/platform/01-platform-engineering)) | Растёт |

**Антипаттерны:** «портал ради портала» без данных; обязательное заполнение 30 полей;
Backstage как единственный способ создать сервис (golden path должен быть удобным, а не
единственным); один энтузиаст, который уволился — и портал заморожен на версии годовой давности.

---

## 9. Альтернативы

| Вариант | Что это | Когда |
|---------|---------|-------|
| **Port** | SaaS-портал: свои «blueprints» сущностей, self-service actions, scorecards; настраивается без кода | Нет людей на TypeScript, нужен результат за недели; платно, данные у вендора |
| **Cortex** | SaaS с упором на каталог и scorecards/инициативы | Главная боль — стандарты и зрелость сервисов |
| OpsLevel и др. | Похожие SaaS-каталоги | Сравнивать по интеграциям и цене |
| Roadie, Red Hat Developer Hub | Backstage «как сервис» / дистрибутив с поддержкой и динамическими плагинами | Хочется Backstage, но не собирать его самим |
| ⭐ «Портал = README + репозиторий шаблонов» | `services.yaml` с владельцами в git, шаблоны проектов GitLab или copier/cookiecutter, доки в репозиториях, дашборд в Grafana | До ~15 сервисов и 2–3 команд: 80% пользы за 5% стоимости |

> 💡 Хорошая стратегия — начать с «README + шаблоны», но **сразу** писать `catalog-info.yaml`
> в репозитории: формат Backstage станет стандартом метаданных, и переход на портал потом —
> это просто discovery.

---

## 10. Грабли

| Грабля | Что происходит | Как избежать |
|--------|----------------|--------------|
| Каталог заполнили руками разово | Через полгода половина владельцев неверна | Файл в репозитории, discovery, проверка в CI |
| `owner` — человек | Уволился — сервис «ничей» | Владелец — Group; люди — через membership |
| Нет org-данных | Группы и люди не совпадают с реальностью, вход не работает | Провайдер org из GitLab/LDAP/Entra ID |
| Шаблон без поддержки скелета | 40 сервисов на 40 версиях Dockerfile и CI | Общие CI-компоненты и базовые образы, скелет тонкий |
| TechDocs `local` в проде | Портал тормозит на сборке доков | `external`: сборка в CI, хранение в S3/MinIO |
| Токены интеграций с правами админа | Шаблон или плагин может всё | Отдельные SA/боты, минимальные права, `requestUserCredentials` |
| Обновления раз в год | Прыжок через 12 версий с ломающими изменениями | Ежемесячный `versions:bump` в расписании команды |
| Команда портала — один человек | Портал умирает с его уходом | Минимум двое, портал — продукт с roadmap |
| `allow-all-policy` в проде | Любой удаляет сущности и запускает любые шаблоны | Своя permission-политика |

---

## 💼 Как это в DevOps

- Первый вопрос на инциденте — «чей сервис и где runbook». Каталог с владельцами и ссылкой из
  алерта экономит минуты MTTR — это самая быстрая польза портала.
- Шаблон golden path = стандарты платформы в одном месте: Dockerfile без root, CI со сканированием,
  LinkdApp вместо чарта, метрики и пробы. Новые сервисы «рождаются правильными».
- Backstage — продукт с пользователями: roadmap, опросы, метрики использования. Портал, который
  никто не открывает, — дорогая витрина.
- В резюме: «внедрил каталог (95% сервисов с владельцами), шаблон нового сервиса — time to first
  deploy с 3 дней до 40 минут, TechDocs для 30 сервисов».

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Создать приложение | `npx @backstage/create-app@latest` → `yarn start` |
| Описать сервис | `catalog-info.yaml`: Component + `owner`, `system`, `lifecycle`, `providesApis`, `dependsOn` |
| Владелец | `owner: group:team-a` |
| Вкладка Kubernetes | Аннотация `backstage.io/kubernetes-id` + метка на объектах + `kubernetes.clusterLocatorMethods` |
| Вкладка ArgoCD | Плагин + `argocd/app-name` |
| Вкладка CI | `gitlab.com/project-slug` / `github.com/project-slug` |
| Документация | `mkdocs.yml` + `docs/` + `backstage.io/techdocs-ref: dir:.` |
| Автонаполнение | `catalog.providers.gitlab` / `github` (discovery) |
| Шаблон | `scaffolder.backstage.io/v1beta3`: `parameters` + `steps` (`fetch:template` → `publish:*` → `catalog:register`) |
| Подстановки в скелете | `$&#123;&#123; values.name &#125;&#125;`, условия `{% if values.database %}` |
| Проверить шаблон | Template Editor `/create/edit`, список действий `/create/actions` |
| Плагин на backend | `backend.add(import('@backstage/plugin-...'))` |
| Обновить Backstage | `yarn backstage-cli versions:bump` |

---

## 🧠 Что запомнить

1. ⭐ Backstage — фреймворк, а не продукт: TypeScript/React-приложение, которое собирают, деплоят
   и обновляют каждый месяц; нужны люди.
2. Три опоры: каталог, шаблоны (scaffolder), TechDocs; остальное — плагины.
3. ⭐ Сущности: Component, API, System, Domain, Resource, Group, User, Location, Template; владелец — Group.
4. `catalog-info.yaml` живёт в репозитории сервиса; discovery из GitLab/GitHub держит каталог свежим.
5. Аннотации связывают сущность с внешним миром: `backstage.io/kubernetes-id`, `argocd/app-name`,
   `gitlab.com/project-slug`, `backstage.io/techdocs-ref`.
6. ⭐ Шаблон: `parameters` (форма) + `steps` (`fetch:template` → `publish:gitlab/github` →
   `catalog:register`), в скелете — Dockerfile, CI, LinkdApp, catalog-info, docs.
7. Шаблон — начало golden path: скелет нужно поддерживать, общее — выносить в CI-компоненты и базовые образы.
8. TechDocs — docs-like-code на MkDocs; в проде сборка в CI (`external`).
9. Новая backend-система: `createBackend()` и `backend.add(...)`; create-app генерирует новую frontend-систему.
10. ⭐ Внедрение: каталог → один шаблон → доки → плагины → scorecards; мерить покрытие каталога,
    time to first deploy, использование шаблонов.
11. Альтернативы: Port, Cortex (SaaS), Roadie/RHDH (Backstage как сервис), «README + шаблоны» для малых команд.

➡️ Дальше: [09_practice_labs.md](/python/09-practice-labs) · Задачи: 08_backstage_tasks.md


---

### Блок A. Теория


**A1.** ⭐ Что такое Backstage? Почему его называют фреймворком, а не продуктом?

<details><summary>Ответ</summary>

Open source-фреймворк портала разработчика (Spotify, CNCF). Это TypeScript/React-приложение,
которое ты генерируешь, собираешь из плагинов, деплоишь и обновляешь сам; «из коробки» он пустой.

</details>

**A2.** Какие три опоры у Backstage? Что делает каждая?

<details><summary>Ответ</summary>

Каталог — сущности, владельцы и связи; шаблоны (scaffolder) — создание сервисов и ресурсов
по golden path; TechDocs — документация из репозиториев в портале.

</details>

**A3.** ⭐ Сколько стоит держать Backstage: люди, обновления, инфраструктура, наполнение?

<details><summary>Ответ</summary>

1–3 инженера с TypeScript/React; ежемесячные релизы и `versions:bump` с ломающими изменениями;
PostgreSQL, деплой, SSO, токены интеграций; наполнение каталога и доки — работа всех команд.

</details>

**A4.** ⭐ Назови kinds каталога и для чего каждый. Какой kind у базы данных linkd?

<details><summary>Ответ</summary>

Component (сервис, сайт, библиотека), API (контракт), System (набор компонентов), Domain
(бизнес-область), Resource (инфраструктура), Group (команда), User (человек), Location (ссылки на файлы),
Template (шаблон). База linkd — `Resource` с `type: database`.

</details>

**A5.** Почему `owner` должен быть группой, а не человеком?

<details><summary>Ответ</summary>

Люди уходят и меняют команды; группа живёт дольше, а членство поддерживается org-данными.
Иначе после увольнения сервис становится «ничьим».

</details>

**A6.** Что такое `lifecycle` и какие значения используют?

<details><summary>Ответ</summary>

Стадия жизни: `experimental`, `production`, `deprecated`. Помогает фильтровать и решать,
какие требования (SLO, дежурство) обязательны.

</details>

**A7.** Как в каталоге описываются связи? Что дают `system`, `dependsOn`, `providesApis`?

<details><summary>Ответ</summary>

Через поля spec: `owner`, `system`, `dependsOn`, `providesApis`/`consumesApis`, `partOf`.
Каталог строит граф: что зависит от ресурса, какие сервисы у команды, кто потребляет API.

</details>

**A8.** Зачем аннотации в `catalog-info.yaml`? Назови четыре и что они подключают.

<details><summary>Ответ</summary>

Связывают сущность с внешними системами: `backstage.io/kubernetes-id` — поды во вкладке
Kubernetes; `argocd/app-name` — статус ArgoCD; `gitlab.com/project-slug` — пайплайны;
`backstage.io/techdocs-ref` — документация.

</details>

**A9.** ⭐ Какими способами наполняется каталог? Как сделать, чтобы он не устаревал?

<details><summary>Ответ</summary>

Статичные Location, ручная регистрация, discovery-провайдеры GitLab/GitHub, org-провайдеры
(GitLab, LDAP, Entra ID), `catalog:register` в шаблоне. Чтобы не устаревал: файл в репозитории
сервиса и меняется вместе с кодом, discovery, проверка схемы в CI, регулярная чистка orphan.

</details>

**A10.** Что такое orphan-сущность и откуда она берётся?

<details><summary>Ответ</summary>

Сущность, чей источник (файл или Location) больше её не содержит: репозиторий удалили,
файл переименовали. Остаётся в каталоге с пометкой orphan.

</details>

**A11.** Откуда берутся Group и User и что будет, если их нет?

<details><summary>Ответ</summary>

Из org-файлов или провайдеров org-данных. Без них `owner` указывает в никуда,
sign-in resolver не находит пользователя, «My Groups» пусты.

</details>

**A12.** ⭐ Из чего состоит шаблон scaffolder'а? Какой `apiVersion` у него?

<details><summary>Ответ</summary>

`apiVersion: scaffolder.backstage.io/v1beta3`, `kind: Template`: `metadata`, `spec.owner`,
`spec.type`, `parameters` (форма в JSON Schema с `ui:*`), `steps` (действия), `output` (ссылки).

</details>

**A13.** Чем `parameters` отличаются от `steps`? Как значения попадают в скелет?

<details><summary>Ответ</summary>

`parameters` — что спросить у пользователя; `steps` — что сделать на backend по порядку.
В `fetch:template` значения передаются в `values`, в скелете — `$&#123;&#123; values.name &#125;&#125;` и условия nunjucks.

</details>

**A14.** Назови встроенные действия scaffolder'а и как добавить `publish:gitlab` или `publish:gitea`.

<details><summary>Ответ</summary>

`fetch:template`, `fetch:plain`, `publish:github`, `publish:gitlab`, `catalog:register`,
`debug:log`. `publish:gitlab`/`publish:gitea` — модули `@backstage/plugin-scaffolder-backend-module-gitlab`
/ `-gitea`: `yarn add` в `packages/backend` и `backend.add(import(...))`, плюс интеграция в `app-config`.

</details>

**A15.** Как проверить шаблон, не создавая настоящий репозиторий?

<details><summary>Ответ</summary>

Template Editor (`/create/edit`) — dry-run формы и шагов; список доступных действий —
`/create/actions`.

</details>

**A16.** ⭐ Почему шаблон — это только начало golden path? Что происходит со скелетом через год?

<details><summary>Ответ</summary>

Шаблон создаёт сервис один раз; дальше скелет эволюционирует (Dockerfile, CI, версии),
а созданные репозитории — нет. Через год десятки сервисов на разных версиях скелета. Решение —
тонкий скелет и общие части вне репозитория: CI-компоненты, базовые образы, оператор LinkdApp.

</details>

**A17.** Что такое TechDocs? Чем `builder: local` отличается от `external`?

<details><summary>Ответ</summary>

Docs-like-code: MkDocs-доки в репозитории сервиса рендерятся в портале. `local` —
Backstage сам собирает при открытии; `external` — CI собирает `@techdocs/cli generate`
и публикует в S3/MinIO, портал только читает.

</details>

**A18.** Что изменилось в TechDocs в v1.55 и чем это может сломать документацию?

<details><summary>Ответ</summary>

TechDocs удаляет MkDocs-плагины вне встроенного allowlist (с предупреждением) —
доки, завязанные на эти плагины, соберутся без них или криво. Нужные плагины явно разрешить.

</details>

**A19.** Что нужно, чтобы во вкладке сервиса появились поды из Kubernetes?

<details><summary>Ответ</summary>

Backend-плагин Kubernetes с настроенным кластером (`clusterLocatorMethods`) и токеном SA
с правами на чтение; аннотация `backstage.io/kubernetes-id` на сущности и такая же метка на объектах
(или `kubernetes-label-selector`); frontend-плагин на странице сервиса.

</details>

**A20.** Как подключить ArgoCD к Backstage и какие права дать токену?

<details><summary>Ответ</summary>

Frontend-плагин (Roadie или community), backend/прокси к API ArgoCD, токен read-only
(локальный аккаунт ArgoCD с правами на чтение проекта), аннотация `argocd/app-name`.

</details>

**A21.** Как устроена новая backend-система? Как добавить плагин?

<details><summary>Ответ</summary>

`createBackend()` в `packages/backend/src/index.ts`, плагины и модули подключаются
`backend.add(import('@backstage/plugin-...'))`; сервисы (логгер, БД, конфиг) внедряются системой.

</details>

**A22.** Что такое sign-in resolver и permission framework? Чем опасен `allow-all-policy`?

<details><summary>Ответ</summary>

Sign-in resolver связывает аккаунт провайдера входа с сущностью User. Permission framework —
политика, кто что может (удалять сущности, запускать шаблоны). `allow-all-policy` разрешает всё всем:
любой запустит опасный шаблон или удалит сущности.

</details>

**A23.** ⭐ В каком порядке внедрять портал? Какие метрики собирать?

<details><summary>Ответ</summary>

Каталог реальных сервисов с владельцами → один шаблон для частого случая с пилотной командой →
TechDocs и runbook'и → плагины по запросам → scorecards. Метрики: покрытие каталога, time to first deploy,
использование шаблонов, активные пользователи, свежесть данных, удовлетворённость.

</details>

**A24.** Какие есть альтернативы Backstage? Когда хватит «README + шаблоны»?

<details><summary>Ответ</summary>

Port, Cortex, OpsLevel (SaaS), Roadie и Red Hat Developer Hub (Backstage как сервис
или дистрибутив). «README + шаблоны» — до ~15 сервисов и 2–3 команд.

</details>

**A25.** Почему стоит писать `catalog-info.yaml`, даже если Backstage пока нет?

<details><summary>Ответ</summary>

Формат метаданных становится стандартом: владельцы и ссылки уже в репозиториях,
и переход на портал — это просто включить discovery.

</details>

---

### Блок B. «Что произойдёт»


```text:no-line-numbers
# B1
```text
```text:no-line-numbers
spec:
```text
```text:no-line-numbers
  type: service
```text
```text:no-line-numbers
  owner: vasya
```text
Вопрос: что покажет каталог и что будет, когда Вася уйдёт?

```text:no-line-numbers
# B2 — catalog-info.yaml в общем репозитории «service-registry», не рядом с кодом
```text
Вопрос: что станет с каталогом через полгода?

```text:no-line-numbers
# B3
```text
```text:no-line-numbers
spec:
```text
```text:no-line-numbers
  owner: group:team-z      # такой Group нет в каталоге
```text
Вопрос: примет ли каталог сущность? Где искать ошибку?

```text:no-line-numbers
# B4 — catalog.rules
```text
```text:no-line-numbers
- allow: [Component, API, Group, User, Location]
```text
```text:no-line-numbers
# в репозитории сервиса есть kind: Resource linkd-db
```text
Вопрос: появится ли `linkd-db` в каталоге?

```text:no-line-numbers
# B5 — шаблон
```text
```text:no-line-numbers
name:
```text
```text:no-line-numbers
  type: string
```text
```text:no-line-numbers
  pattern: '^[a-z][a-z0-9-]{2,30}$'
```text
```text:no-line-numbers
# пользователь вводит "Linkd_Service"
```text
Вопрос: что произойдёт?

```text:no-line-numbers
# B6 — шаги шаблона
```text
```text:no-line-numbers
- id: publish
```text
```text:no-line-numbers
  action: publish:gitlab
```text
```text:no-line-numbers
- id: register
```text
```text:no-line-numbers
  action: catalog:register
```text
```text:no-line-numbers
# publish прошёл, register упал: в catalog-info.yaml опечатка
```text
Вопрос: в каком состоянии останутся репозиторий и каталог? Как улучшить шаблон?

```text:no-line-numbers
# B7 — app-config
```text
```text:no-line-numbers
techdocs:
```text
```text:no-line-numbers
  builder: local
```text
```text:no-line-numbers
# 300 сервисов, у каждого большие доки
```text
Вопрос: что заметят пользователи портала?

```text:no-line-numbers
# B8 — Deployment linkd без метки backstage.io/kubernetes-id, в catalog-info аннотация есть
```text
Вопрос: что покажет вкладка Kubernetes?

```text:no-line-numbers
# B9 — permission: allow-all-policy в проде; шаблон «удалить репозиторий» доступен всем
```text
Вопрос: что может пойти не так?

```text:no-line-numbers
# B10 — Backstage 1.43, решили обновиться сразу на 1.55
```text
```text:no-line-numbers
yarn backstage-cli versions:bump
```text
Вопрос: чего ждать?

---

### Блок C. Практика


### C1. 🔑 Локальный Backstage
Создай приложение `npx @backstage/create-app@latest`, запусти `yarn start`, войди как guest.
Определи по коду `packages/app`, на какой frontend-системе создано приложение, и найди
в `packages/backend/src/index.ts` плагины каталога, scaffolder'а, TechDocs и Kubernetes.

### C2. 🔑 linkd в каталоге
Опиши linkd как в конспекте: Component, API (реальный OpenAPI на эндпоинты linkd 2.0 из CHANGELOG),
Resource `linkd-db`, System `shortener`, Group и User. Подключи файлы статично. Проверь граф
зависимостей и страницу API.

### C3. Ошибки каталога
Сломай сущности: несуществующий owner, неизвестный kind, невалидный YAML. Найди, где Backstage
показывает ошибки обработки (логи backend и UI), и запиши, как это увидел бы владелец сервиса.

### C4. 🔑 Шаблон golden path
Напиши шаблон `linkd-service` со скелетом: `app/main.py`, Dockerfile, CI, `deploy/linkdapp.yaml`,
`deploy/database.yaml` по условию, `catalog-info.yaml`, `mkdocs.yml`, `docs/`. Публикация —
в GitHub или GitLab. Прогони в Template Editor, затем по-настоящему.

### C5. Шаг «приложение в ArgoCD»
Добавь в шаблон шаг, который создаёт MR (или PR) в gitops-репозиторий с ArgoCD Application
для нового сервиса. После мержа проверь, что ArgoCD подхватил приложение.

### C6. Уборка при ошибке
Добавь в шаблон шаг с `if: $&#123;&#123; failure() &#125;&#125;`, который удаляет созданный репозиторий, если
регистрация в каталоге упала. Проверь на намеренно сломанном `catalog-info.yaml`.

### C7. TechDocs
Подключи доки linkd: `mkdocs.yml`, три страницы (обзор, runbook, API). Затем собери их
в «внешнем» режиме: `npx @techdocs/cli generate` локально и посмотри, что получилось.

### C8. 🔑 Вкладка Kubernetes
Создай в kind ServiceAccount с правами только на чтение, выдай токен, подключи кластер к плагину
Kubernetes. Поставь метку на Deployment linkd и убедись, что поды видны; сломай под (неверный образ)
и посмотри, как это отображается.

### C9. Метрики внедрения
Придумай, как считать «покрытие каталога» для кластера: сравни список Deployment с меткой
`backstage.io/kubernetes-id` со списком всех Deployment в namespace команд (скрипт на Python
или kubectl + jq). Запиши процент.

### C10. «Портал без портала» (со звёздочкой)
Опиши минимальную альтернативу для 8 сервисов: `services.yaml` в git (владелец, дежурство,
ссылки), репозиторий шаблонов (copier/cookiecutter или шаблоны проектов GitLab), доки в репозиториях,
дашборд Grafana. Что потеряешь по сравнению с Backstage и когда станет пора переходить?

---

### Блок D. Инциденты


**D1.** Пользователи жалуются: половина сервисов в каталоге с неверными владельцами. Как исправить
сейчас и навсегда?

<details><summary>Ответ</summary>

Сейчас — выгрузить список сервисов и владельцев, подтвердить с командами, исправить файлы
MR-ами. Навсегда — файл в репозитории сервиса, org-данные из источника правды, проверка в CI,
scorecard «есть владелец» и регулярный отчёт orphan.

</details>

**D2.** После обновления Backstage вкладка Docs у части сервисов пустая, в логах предупреждения
про MkDocs-плагины. Что случилось?

<details><summary>Ответ</summary>

В v1.55 TechDocs удаляет MkDocs-плагины вне allowlist. Разрешить нужные в
`techdocs.generator.mkdocs.dangerouslyAllowAdditionalPlugins` или отказаться от них.

</details>

**D3.** Шаблон создаёт репозитории, но через раз падает на `catalog:register` с таймаутом. Гипотезы?

<details><summary>Ответ</summary>

Каталог обрабатывает сущность асинхронно, регистрация ждёт; медленная БД каталога, лимиты API
GitLab, большие репозитории. Проверить логи, увеличить таймауты, мониторинг БД и rate limits.

</details>

**D4.** Вкладка ArgoCD у всех сервисов показывает ошибку 401. Что проверить?

<details><summary>Ответ</summary>

Токен ArgoCD истёк или отозван, неправильный адрес/прокси, у токена нет прав на проекты.
Проверить токен запросом к API ArgoCD напрямую.

</details>

**D5.** Портал открывается 20 секунд, backend потребляет 3 ГБ памяти. Куда смотреть?

<details><summary>Ответ</summary>

БД каталога (индексы, размер), частота discovery-провайдеров, TechDocs `local`, поиск
(индексация), тяжёлые плагины; метрики и профилирование backend, разнести на несколько инстансов.

</details>

**D6.** Команды перестали пользоваться шаблоном и копируют старый сервис. Как выяснить почему?

<details><summary>Ответ</summary>

Интервью с командами и метрики воронки шаблона (где бросают форму); часто шаблон отстал
от практики, долгий или делает не то. Шаблон — продукт: обновить, упростить, сделать удобнее копирования.

</details>

**D7.** После ухода единственного инженера портала Backstage не обновлялся 10 месяцев. План?

<details><summary>Ответ</summary>

Оценить разрыв версий, обновляться поэтапно с тестами, назначить минимум двух владельцев,
ежемесячное обновление в плане команды, по возможности уменьшить число самописных плагинов.

</details>

**D8.** На инциденте дежурный нашёл сервис в каталоге, но runbook по ссылке — 404. Что улучшить
системно?

<details><summary>Ответ</summary>

Ссылки на runbook — в TechDocs того же репозитория (живут вместе с кодом), проверка битых
ссылок в CI, scorecard «runbook есть и открывается», ссылка из алерта ведёт на страницу в портале.

</details>

---

### Блок E. Вопросы с собеседования


**1.** ⭐ Что такое Backstage и из чего он состоит?

<details><summary>Ответ</summary>

Фреймворк портала: каталог, шаблоны, TechDocs, плагины; TypeScript/React, свой деплой и обновления.

</details>

**2.** Как вы описываете сервис в каталоге и как держите каталог в актуальном состоянии?

<details><summary>Ответ</summary>

`catalog-info.yaml` в репозитории сервиса (Component + API + Resource + System, owner — Group,
   аннотации), discovery из GitLab, org-данные из источника правды, проверка в CI.

</details>

**3.** ⭐ Расскажите про шаблон нового сервиса: что в скелете, какие шаги?

<details><summary>Ответ</summary>

Скелет: код с пробами и метриками, Dockerfile, CI, LinkdApp (и LinkdDatabase по галочке),
   catalog-info, доки; шаги: `fetch:template` → `publish:gitlab` → MR в gitops → `catalog:register`.

</details>

**4.** Что такое TechDocs и как его разворачивать в проде?

<details><summary>Ответ</summary>

MkDocs-доки в репозитории; в проде `external`: сборка в CI и хранение в S3/MinIO.

</details>

**5.** Какие плагины вы бы подключили первыми и почему?

<details><summary>Ответ</summary>

Kubernetes и ArgoCD (статус без kubectl), CI, дежурства и дашборды — то, что нужно на инциденте.

</details>

**6.** ⭐ Сколько стоит поддерживать Backstage? Когда он не нужен?

<details><summary>Ответ</summary>

1–3 инженера, ежемесячные обновления, БД, SSO, наполнение; не нужен при малом числе сервисов и команд.

</details>

**7.** ⭐ Как вы бы внедряли портал и как мерили бы успех?

<details><summary>Ответ</summary>

Каталог → шаблон с пилотом → доки → плагины → scorecards; покрытие каталога, time to first deploy,
   использование шаблонов, WAU, опросы DevEx.

</details>

**8.** Backstage, Port или «README + шаблоны» — как выбрать?

<details><summary>Ответ</summary>

По людям и масштабу: есть TypeScript-экспертиза и десятки сервисов — Backstage; нужен быстрый
   результат без разработки — Port/Cortex; мало сервисов — «README + шаблоны».

</details>

**9.** Как в портале управлять доступом?

<details><summary>Ответ</summary>

SSO, sign-in resolver на User, permission-политика, минимальные токены интеграций.

</details>

**10.** Как связать портал с GitOps и оператором платформы?

<details><summary>Ответ</summary>

Шаблон создаёт LinkdApp и Application (MR в gitops), ArgoCD доставляет, оператор разворачивает,
    портал показывает статус через плагины Kubernetes и ArgoCD.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Объясняю, что такое Backstage и сколько стоит его поддержка
- [ ] ⭐ Описываю сервис в каталоге: kinds, владелец-группа, связи, аннотации
- [ ] Знаю, как наполнять каталог и держать его свежим (discovery, файл в репозитории, CI)
- [ ] ⭐ Написал шаблон golden path со скелетом, публикацией и регистрацией
- [ ] Подключил TechDocs и понимаю `local` vs `external`
- [ ] Подключил вкладку Kubernetes к kind; знаю, как подключается ArgoCD
- [ ] Знаю новую backend-систему и как добавить плагин
- [ ] ⭐ Могу предложить план внедрения портала и метрики успеха
- [ ] Сравниваю Backstage с Port/Cortex и «README + шаблоны»
