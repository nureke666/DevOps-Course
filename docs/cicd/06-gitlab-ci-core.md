---
title: "06. GitLab CI: rules, variables, artifacts, cache, environments"
description: "Правила запуска джоб, переменные и секреты, передача файлов, кэш, окружения — конспект и задачи"
---

# 06. GitLab CI: rules, variables, artifacts, cache, environments

> Роадмап → 4. CI/CD → Инструменты → GitLab CI → **База**:
> `only/rules`, `variables`, CI/CD Variables (секреты), `artifacts`, `cache`,
> `before_script`/`after_script`, окружения (environments), `when: manual`.
> **После темы ты умеешь:** управлять тем, когда джоба запускается, откуда берёт секреты,
> что передаёт дальше и во что деплоит.

---

## 🗺️ Карта темы

```text:no-line-numbers
 КОГДА запускать          ОТКУДА данные            ЧТО передаётся дальше
 ┌──────────────┐        ┌──────────────┐        ┌──────────────────────┐
 │ rules / only │        │ variables    │        │ artifacts (файлы →   │
 │ workflow     │        │ CI/CD Vars   │        │   следующие джобы,   │
 │ when: manual │        │ (masked,     │        │   скачивание, отчёты)│
 │ changes      │        │  protected,  │        │ cache (ускорение,    │
 └──────────────┘        │  file, env)  │        │   можно потерять)    │
                         └──────────────┘        └──────────────────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │ environment: куда    │
                         │ деплоим, история,    │
                         │ откат, on_stop       │
                         └──────────────────────┘
```

---

## 1. `rules` — когда джоба попадает в пайплайн

`rules` пришли на смену `only/except` и умеют существенно больше. Правила проверяются
**сверху вниз, до первого совпадения**; дальше применяется его `when`/`variables`/`allow_failure`.
Если ни одно правило не совпало — джоба в пайплайн не попадает.

```yaml
deploy:prod:
  stage: deploy
  script: ["./deploy.sh"]
  rules:
    # 1. на main — кнопкой
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
    # 2. по тегу vX.Y.Z — тоже кнопкой
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/
      when: manual
    # 3. во всех остальных случаях джобы нет
    - when: never
```

### Что можно писать в правиле

| Ключ | Смысл |
|------|-------|
| `if:` | Условие по переменным |
| `changes:` | Запускать, только если изменились указанные пути |
| `exists:` | Запускать, если в репозитории есть файл |
| `when:` | `on_success` (по умолчанию), `manual`, `always`, `never`, `delayed`, `on_failure` |
| `allow_failure:` | Не валить пайплайн |
| `variables:` | Переопределить переменные для этого случая |
| `needs:` | Разные зависимости для разных случаев |

### Операторы в `if`

```yaml
- if: $CI_COMMIT_BRANCH == "main"
- if: $CI_COMMIT_BRANCH != "main"
- if: $CI_COMMIT_TAG                        # переменная не пуста
- if: $CI_COMMIT_TAG == null                # переменной нет
- if: $CI_COMMIT_BRANCH =~ /^feature\/.+/   # регулярка
- if: $CI_COMMIT_BRANCH !~ /^wip-/
- if: $CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_TARGET_BRANCH_NAME == "main"
- if: $DEPLOY_ENABLED == "true" || $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### `changes` — не гонять лишнее

```yaml
build:frontend:
  script: ["npm ci && npm run build"]
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        paths: ["frontend/**/*", "package-lock.json"]
```
> ⚠️ `changes` осмысленно работает в MR-пайплайнах и при push с известной базой сравнения.
> В пайплайне ветки без базы (например, первый пуш) GitLab считает, что изменилось всё.

### `only/except` — легаси, но читать уметь надо

```yaml
# старый синтаксис (встретится в любом старом проекте)
job:
  only:
    refs: [main, tags]
    variables: ['$DEPLOY == "yes"']
  except:
    refs: [/^wip-.*/]
```
Ограничения `only/except`: нельзя комбинировать условия сложной логикой, нельзя менять
переменные, хуже работает с MR-пайплайнами. **Новый код пишем на `rules`, старый читаем.**
Смешивать `only` и `rules` в одной джобе нельзя.

### `workflow:rules` — правила для всего пайплайна

```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      variables:
        ENV_NAME: "review"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      variables:
        ENV_NAME: "staging"
    - if: $CI_COMMIT_TAG
      variables:
        ENV_NAME: "production"
    - when: never
```
Здесь же удобно задавать переменные, общие для типа пайплайна.

---

## 2. `variables` — переменные

### Уровни (от общего к частному)

```text:no-line-numbers
1. Instance / Group CI/CD Variables   (админ, вся группа проектов)
2. Project CI/CD Variables            (Settings → CI/CD → Variables)  ← секреты
3. variables: в .gitlab-ci.yml        (уровень пайплайна)
4. variables: внутри job              (уровень джобы)  ← самый приоритетный из YAML
5. Переменные, заданные при Run pipeline вручную / через trigger
6. Предопределённые (CI_*)            (их не переопределяем)
```
Побеждает более конкретный уровень; вручную заданные при запуске — самые приоритетные.

```yaml
variables:
  APP_NAME: "myapp"
  DOCKER_DRIVER: overlay2

build:
  variables:
    APP_NAME: "myapp-edge"      # переопределение для этой джобы
  script:
    - echo "$APP_NAME"
```

### CI/CD Variables в UI (место для секретов)

Settings → CI/CD → Variables. У переменной есть флаги:

| Флаг | Что даёт |
|------|----------|
| **Masked** | Значение заменяется на `[MASKED]` в логах (требования: без переносов, длина ≥ 8, ограниченный набор символов) |
| **Protected** | Доступна только джобам из **защищённых** веток и тегов ← так защищают прод-секреты |
| **Type: File** | Значение кладётся во временный файл, в переменную попадает **путь** (идеально для ключей и kubeconfig) |
| **Environment scope** | Переменная только для конкретного окружения (`production`, `staging`) |
| **Expanded/Raw** | Раскрывать ли `$`-подстановки внутри значения (для паролей с `$` нужен Raw) |

```yaml
# File-переменная SSH_KEY (тип File)
script:
  - chmod 600 "$SSH_KEY"
  - ssh -i "$SSH_KEY" deploy@$HOST "docker compose pull && docker compose up -d"
```

> ⚠️ Masked ≠ безопасно. Маскирование прячет **точное совпадение** в логе. Если вывести
> ключ через `base64`, склеить или вывести по частям — маскирование не сработает.
> Не печатай секреты вообще: никакого `env`, `set -x` рядом с подстановкой, `cat` конфигов.

### Проверка обязательных переменных

```yaml
.check-vars: &check-vars
  - |
    for v in DEPLOY_HOST DEPLOY_USER; do
      if [ -z "$(eval echo \$$v)" ]; then echo "❌ $v не задана"; exit 1; fi
    done
```

---

## 3. `artifacts` — передача файлов и отчёты

```yaml
build:
  stage: build
  script: ["npm ci", "npm run build"]
  artifacts:
    name: "$CI_JOB_NAME-$CI_COMMIT_SHORT_SHA"
    paths:
      - dist/
      - build-info.json
    exclude:
      - dist/**/*.map            # не тащить sourcemaps
    expire_in: 1 week            # ⭐ иначе забьёшь хранилище
    when: on_success             # on_success | on_failure | always
```

**Что важно понимать:**
1. Артефакты **загружаются в GitLab** после джобы и **скачиваются** во все джобы
   последующих стадий (или в те, что указаны в `needs`).
2. Это не общий диск — это upload/download. Большие артефакты замедляют пайплайн.
3. `expire_in` обязателен для всего, кроме релизных артефактов.
4. Артефакты можно скачать из UI и через API — удобно для отчётов.
5. Игнорируемые в `.gitignore` файлы по умолчанию **не** попадают в артефакты
   (лечится `artifacts: untracked: true` или изменением `.gitignore`).

### Отчёты (`artifacts:reports`)

```yaml
test:
  script: ["pytest --junitxml=report.xml --cov=app --cov-report=xml"]
  coverage: '/TOTAL.+?(\d+\.\d+\%)/'
  artifacts:
    when: always
    reports:
      junit: report.xml                      # вкладка Tests в MR
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml
```
Другие типы отчётов: `dotenv` (передать переменные в следующие джобы!), `sast`,
`dependency_scanning`, `container_scanning`, `codequality`, `terraform`.

```yaml
# ⭐ dotenv — самый практичный: передать вычисленное значение дальше
build:
  script:
    - echo "IMAGE_TAG=$CI_COMMIT_SHORT_SHA" >> build.env
  artifacts:
    reports:
      dotenv: build.env

deploy:
  needs: [build]
  script:
    - echo "Деплою $IMAGE_TAG"     # переменная приехала из build
```

### Управление скачиванием

```yaml
deploy:
  dependencies: []          # НЕ скачивать артефакты вообще (ускоряет)
  # или
  dependencies: [build]     # только из конкретной джобы
```

---

## 4. `cache` — ускорение, а не передача данных

```yaml
variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"

.python-cache: &python-cache
  key:
    files: [requirements.txt]        # ⭐ ключ меняется при изменении зависимостей
  paths:
    - .cache/pip
    - .venv/
  policy: pull-push                  # pull-push | pull | push

test:
  cache: *python-cache
  script: ["pip install -r requirements.txt", "pytest"]
```

| Ключ | Смысл |
|------|-------|
| `key` | Идентификатор кэша: строка, `$CI_COMMIT_REF_SLUG`, `files: [...]`, `prefix` |
| `paths` | Что кэшируем (**внутри** `$CI_PROJECT_DIR`) |
| `policy` | `pull` — только читать (для тестовых джоб), `push` — только писать, `pull-push` — по умолчанию |
| `when` | Когда сохранять: `on_success`/`always`/`on_failure` |
| `untracked` | Кэшировать неотслеживаемые git-файлы |
| `fallback_keys` | Использовать другой кэш, если по ключу ничего нет |

### Cache vs Artifacts — главный вопрос темы

| | `cache` | `artifacts` |
|---|---|---|
| Назначение | Ускорить (зависимости) | Передать результат / сохранить |
| Хранится | На раннере (или в S3) | В GitLab |
| Гарантия наличия | ❌ нет, может пропасть | ✅ есть (до `expire_in`) |
| Между пайплайнами | ✅ да | ❌ нет (только внутри пайплайна) |
| Между раннерами | Только если distributed cache (S3) | ✅ да, всегда |
| Потеря = | Медленнее | Сломанный пайплайн |

**Правило:** то, без чего следующая джоба не может работать — `artifacts`.
То, что просто ускоряет — `cache`. Никогда не кэшируй сборочный результат, от которого
зависит корректность.

---

## 5. `before_script` / `after_script`

```yaml
default:
  before_script:
    - echo "Джоба $CI_JOB_NAME на раннере $CI_RUNNER_DESCRIPTION"

deploy:
  before_script:
    - apk add --no-cache openssh-client
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - ssh-keyscan -H "$DEPLOY_HOST" >> ~/.ssh/known_hosts
  script:
    - ssh -i "$SSH_KEY" "$DEPLOY_USER@$DEPLOY_HOST" "docker compose pull && docker compose up -d"
  after_script:
    - rm -f ~/.ssh/id_* || true          # уборка, выполнится даже при падении
```

Особенности:
- `before_script` джобы **полностью заменяет** глобальный (не дополняет!);
- `after_script` работает в **отдельном shell**: переменные и `cd` из `script` не сохраняются,
  а падение `after_script` не меняет статус джобы (но пишется в лог);
- `after_script` выполняется и при отмене/таймауте — поэтому там место уборке и уведомлениям.

---

## 6. `environment` — окружения

```yaml
deploy:staging:
  stage: deploy
  script: ["./deploy.sh staging"]
  environment:
    name: staging
    url: https://staging.example.com
    deployment_tier: staging
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy:prod:
  stage: deploy
  script: ["./deploy.sh production"]
  environment:
    name: production
    url: https://example.com
    deployment_tier: production
  resource_group: production          # ⭐ два деплоя прода не пойдут одновременно
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
```

Что даёт `environment`:
- раздел **Deployments → Environments**: что, когда и кем задеплоено, ссылка на сервис;
- кнопка **Re-deploy** и **Rollback** (повторный запуск джобы предыдущего успешного деплоя);
- привязку переменных с `environment scope`;
- защиту окружения (Settings → CI/CD → Protected environments): кто имеет право деплоить.

### Динамические окружения (review apps)

```yaml
review:
  stage: deploy
  script: ["./deploy.sh review-$CI_COMMIT_REF_SLUG"]
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.review.example.com
    on_stop: stop_review
    auto_stop_in: 2 days
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

stop_review:
  stage: deploy
  script: ["./destroy.sh review-$CI_COMMIT_REF_SLUG"]
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    action: stop
  when: manual
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

---

## 7. `when: manual` и ручное подтверждение

```yaml
deploy:prod:
  script: ["./deploy.sh"]
  when: manual            # кнопка ▶ в UI
  allow_failure: false    # ⭐ делает джобу БЛОКИРУЮЩЕЙ: пайплайн ждёт решения
```

| Вариант | Поведение |
|---------|-----------|
| `when: manual` (по умолчанию `allow_failure: true` для manual) | Кнопка есть, пайплайн считается успешным без нажатия |
| `when: manual` + `allow_failure: false` | Пайплайн в статусе «ожидает ручного действия» (blocked) |
| `when: delayed` + `start_in: 30 minutes` | Отложенный запуск (например, «подождать и добить canary») |
| `when: on_failure` | Запустить, только если предыдущие джобы упали (например, уведомление/откат) |
| `when: always` | Запускать независимо от результата (отчёты, уборка) |

Кто может нажать кнопку — определяется правами на ветку и **Protected environments**.

---

## 8. Практичный пример: всё вместе

```yaml
stages: [test, build, deploy]

default:
  image: python:3.12-slim
  interruptible: true

variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"
  IMAGE: "$CI_REGISTRY_IMAGE"

workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_COMMIT_TAG
    - when: never

test:
  stage: test
  cache:
    key:
      files: [requirements.txt]
    paths: [.cache/pip]
    policy: pull-push
  before_script:
    - pip install -r requirements.txt -r requirements-dev.txt
  script:
    - pytest -q --junitxml=report.xml
  artifacts:
    when: always
    expire_in: 1 week
    reports:
      junit: report.xml

build:
  stage: build
  image: docker:29
  services: [docker:29-dind]
  script:
    - echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
    - docker build -t "$IMAGE:$CI_COMMIT_SHORT_SHA" .
    - docker push "$IMAGE:$CI_COMMIT_SHORT_SHA"
    - echo "IMAGE_TAG=$CI_COMMIT_SHORT_SHA" >> build.env
  artifacts:
    reports:
      dotenv: build.env
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

deploy:staging:
  stage: deploy
  image: alpine:3.20
  needs: [build]
  before_script:
    - apk add --no-cache openssh-client curl
    - ssh-keyscan -H "$STAGING_HOST" >> /etc/ssh/ssh_known_hosts
  script:
    - ssh -i "$SSH_KEY" "$DEPLOY_USER@$STAGING_HOST"
        "docker pull $IMAGE:$IMAGE_TAG && APP_IMAGE=$IMAGE:$IMAGE_TAG docker compose up -d"
    - curl -fsS --retry 5 --retry-delay 3 "https://staging.example.com/health"
  environment:
    name: staging
    url: https://staging.example.com
  resource_group: staging
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy:prod:
  extends: deploy:staging
  script:
    - ssh -i "$SSH_KEY" "$DEPLOY_USER@$PROD_HOST"
        "docker pull $IMAGE:$IMAGE_TAG && APP_IMAGE=$IMAGE:$IMAGE_TAG docker compose up -d"
    - curl -fsS --retry 5 --retry-delay 3 "https://example.com/health"
  environment:
    name: production
    url: https://example.com
  resource_group: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
```

---

## 💼 Как это в DevOps

- 90% вопросов «почему джоба не запустилась / запустилась дважды» — это `rules`.
  Учись читать их сверху вниз и проверять в Pipeline editor.
- Секреты в CI/CD Variables (masked + protected) — минимальный стандарт;
  дальше по зрелости — Vault/OIDC вместо долгоживущих токенов.
- Кэш — первое, что настраивают при жалобе «пайплайн медленный»;
  артефакты — первое, что проверяют при «джоба не видит файл».
- Environments — то, что делает деплой прозрачным для команды: видно, что и когда в проде.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Запускать только на main | `rules: - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH` |
| Запускать в MR | `- if: $CI_PIPELINE_SOURCE == "merge_request_event"` |
| Только по релизному тегу | `- if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/` |
| Только при изменении каталога | `changes: paths: ["backend/**/*"]` |
| Никогда в остальных случаях | `- when: never` (последним правилом) |
| Кнопка | `when: manual` (+ `allow_failure: false` — блокирующая) |
| Секрет | CI/CD Variables: masked + protected (+ тип File для ключей) |
| Передать файл дальше | `artifacts: paths: [...]` + `expire_in` |
| Передать переменную дальше | `artifacts: reports: dotenv: build.env` |
| Ускорить установку пакетов | `cache: key: files: [...] , paths: [...]` |
| Не качать артефакты | `dependencies: []` |
| Видеть, что в проде | `environment: name/url` |
| Не деплоить одновременно | `resource_group: production` |
| Временный стенд на MR | `environment: name: review/$CI_COMMIT_REF_SLUG` + `on_stop` |
| Уборка после падения | `after_script` |

---

## 🧠 Что запомнить

1. `rules` читаются сверху вниз **до первого совпадения**; нет совпадения — джобы нет.
2. `only/except` — легаси: читать умей, новое пиши на `rules`; смешивать нельзя.
3. `workflow:rules` управляет созданием **всего** пайплайна и убирает дубли на MR.
4. Секреты живут в CI/CD Variables: **masked** (лог) + **protected** (только защищённые ветки).
5. Masked прячет только точное совпадение — не печатай секреты вообще.
6. Тип **File** — правильный способ отдать в джобу SSH-ключ или kubeconfig.
7. `artifacts` — надёжная передача файлов между джобами; всегда ставь `expire_in`.
8. `artifacts:reports:dotenv` — способ передать **переменные** из джобы в джобу.
9. `cache` — только ускорение: он может пропасть, и пайплайн обязан это переживать.
10. Ключ кэша по `files:` — кэш обновляется при изменении зависимостей, а не «когда-нибудь».
11. `environment` даёт историю деплоев, ссылку, кнопку отката и защиту прода.
12. `when: manual` + `allow_failure: false` = блокирующая кнопка; `resource_group` защищает
    от одновременных деплоев.

---

## Задачи

> Лаба: тот же проект, что в теме 05. Многие задания проверяются только реальным пушем —
> заведи ветку `ci-lab` и коммить в неё маленькими шагами.

---

### Блок A. Теория

**A1.** Как обрабатываются `rules`? Что произойдёт, если не совпало ни одно правило?

<details><summary>Ответ</summary>

Правила проверяются сверху вниз до первого совпадения; применяются `when`,
`variables`, `allow_failure` этого правила. Если не совпало ни одно — джоба не добавляется
в пайплайн (её просто нет).

</details>

**A2.** Назови все ключи, которые можно использовать внутри правила `rules`.

<details><summary>Ответ</summary>

`if`, `changes`, `exists`, `when`, `allow_failure`, `variables`, `needs`
(а также `interruptible` в новых версиях).

</details>

**A3.** Чем `rules` лучше `only/except`? Можно ли использовать их в одной джобе вместе?

<details><summary>Ответ</summary>

`rules` поддерживают сложную логику (`&&`, `||`, регулярки), переопределение
переменных, `changes`/`exists`, задание `when`/`allow_failure` для конкретного случая
и корректно работают с MR-пайплайнами. Смешивать `only/except` и `rules` в одной джобе
нельзя — будет ошибка конфигурации.

</details>

**A4.** Как в `rules` проверить: ветку по умолчанию, любой тег, релизный тег `vX.Y.Z`,
merge request, ветку по маске `feature/*`?

<details><summary>Ответ</summary>

```yaml
- if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
- if: $CI_COMMIT_TAG
- if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/
- if: $CI_PIPELINE_SOURCE == "merge_request_event"
- if: $CI_COMMIT_BRANCH =~ /^feature\/.+/
```

</details>

**A5.** Что делает `changes:` и в каких пайплайнах его результат непредсказуем?

<details><summary>Ответ</summary>

`changes` запускает джобу, только если изменились указанные пути. Предсказуемо
работает в MR-пайплайнах (есть база сравнения) и при обычных пушах с известным предыдущим
коммитом; в пайплайнах без базы (новая ветка, ручной/scheduled запуск) GitLab считает
изменённым всё, и джоба выполнится.

</details>

**A6.** Что настраивается через `workflow:rules` и какую частую проблему это решает?

<details><summary>Ответ</summary>

`workflow:rules` определяют, создавать ли пайплайн вообще и с какими переменными.
Решают проблему дублирующихся пайплайнов (branch + MR) и позволяют централизованно
задать переменные для типа запуска.

</details>

**A7.** Перечисли уровни переменных по приоритету.

<details><summary>Ответ</summary>

От низшего к высшему: предопределённые CI_* → instance/group переменные →
project переменные → `variables` в `.gitlab-ci.yml` (пайплайн) → `variables` в джобе →
переменные, переданные вручную при Run pipeline или через trigger/API.

</details>

**A8.** Что дают флаги Masked и Protected? Почему masked не является полной защитой?

<details><summary>Ответ</summary>

Masked скрывает значение в логах, Protected делает переменную доступной только
джобам из защищённых веток/тегов. Masked прячет точное совпадение строки, поэтому любое
преобразование (base64, вывод по частям, склейка) обходит маскирование — это защита
от случайной печати, а не от злоумышленника.

</details>

**A9.** Зачем нужен тип переменной **File**? Приведи два примера использования.

<details><summary>Ответ</summary>

Значение записывается во временный файл, а в переменную попадает путь к нему.
Примеры: SSH-приватный ключ (`ssh -i "$SSH_KEY"`), kubeconfig (`KUBECONFIG=$KUBE_CONFIG`),
сервис-аккаунт GCP, TLS-сертификат. Это избавляет от возни с переносами строк
в многострочных секретах.

</details>

**A10.** Что такое environment scope у переменной?

<details><summary>Ответ</summary>

Ограничение области действия переменной конкретным окружением (`production`,
`staging`, `review/*`): джоба получит значение, только если её `environment:name`
совпадает со scope. Позволяет иметь одно имя переменной с разными значениями.

</details>

**A11.** Чем `artifacts` отличается от `cache`? Дай таблицу из пяти различий.

<details><summary>Ответ</summary>

Назначение (передача vs ускорение), место хранения (GitLab vs раннер/S3), гарантия
наличия (есть vs нет), область (внутри пайплайна vs между пайплайнами), последствия
потери (сломанный пайплайн vs замедление) — см. таблицу «Cache vs Artifacts» выше в конспекте.

</details>

**A12.** Что делает `artifacts: reports: dotenv` и зачем это нужно?

<details><summary>Ответ</summary>

Джоба пишет `KEY=VALUE` в файл, GitLab считывает его и превращает в переменные,
доступные последующим джобам. Так передают вычисленные значения: версию, тег образа,
адрес поднятого стенда.

</details>

**A13.** Зачем нужен `expire_in` и что будет без него?

<details><summary>Ответ</summary>

`expire_in` задаёт срок жизни артефактов. Без него артефакты хранятся согласно
настройкам проекта/инстанса и легко забивают хранилище — а переполнение хранилища
блокирует CI и пуш.

</details>

**A14.** Что делает `dependencies: []` и когда это полезно?

<details><summary>Ответ</summary>

Запрещает скачивать артефакты предыдущих стадий. Полезно для джоб, которым файлы
не нужны (деплой по образу из registry, уведомления): экономит время и трафик.

</details>

**A15.** Что задаёт `policy: pull` у кэша? Где это применяют?

<details><summary>Ответ</summary>

`policy: pull` — только читать кэш, не сохранять. Применяют в джобах, которые
не меняют зависимости (тесты, линтеры), чтобы не тратить время на архивирование и
не плодить версии кэша; сохраняет кэш одна «подготовительная» джоба с `pull-push`/`push`.

</details>

**A16.** Почему ключ кэша по `files: [package-lock.json]` лучше, чем фиксированная строка?

<details><summary>Ответ</summary>

Ключ по содержимому файла зависимостей меняется ровно тогда, когда меняются
зависимости: кэш автоматически инвалидируется при обновлении и переиспользуется, пока
зависимости те же. Фиксированная строка накапливает мусор и устаревает.

</details>

**A17.** Правда ли, что `before_script` джобы дополняет глобальный? Что происходит на самом деле?

<details><summary>Ответ</summary>

Нет, не дополняет: `before_script` в джобе **заменяет** глобальный/`default`
целиком. Если нужно и то, и другое — выносите общую часть в якорь/`extends` и явно
объединяйте.

</details>

**A18.** Какие особенности у `after_script` (три штуки)?

<details><summary>Ответ</summary>

(1) Выполняется всегда — при успехе, падении, отмене и таймауте;
(2) работает в отдельном shell: изменения каталога и переменные из `script` не сохраняются;
(3) его падение не меняет статус джобы (но видно в логе); плюс у него отдельный таймаут.

</details>

**A19.** Что даёт блок `environment`? Перечисли пять возможностей.

<details><summary>Ответ</summary>

История деплоев в Deployments → Environments; ссылка на приложение (`url`);
кнопки Re-deploy и Rollback; привязка переменных по environment scope; защита окружения
(кто может деплоить); поддержка динамических окружений с `on_stop`/`auto_stop_in`;
отображение «что сейчас задеплоено» в MR.

</details>

**A20.** Что такое `resource_group` и какую проблему он решает?

<details><summary>Ответ</summary>

`resource_group` сериализует джобы: одновременно выполняется только одна джоба
из группы. Решает проблему параллельных деплоев на одно окружение, которые перетирают
друг друга и оставляют непредсказуемое состояние.

</details>

**A21.** Как сделать динамическое окружение на каждый MR и как оно удаляется?

<details><summary>Ответ</summary>

`environment: name: review/$CI_COMMIT_REF_SLUG` + `on_stop: stop_job`
(+ `auto_stop_in`). Джоба остановки описывается с `environment: action: stop` и обычно
`when: manual`; GitLab запускает её при закрытии/мерже MR или по истечении `auto_stop_in`.

</details>

**A22.** В чём разница между `when: manual` и `when: manual` + `allow_failure: false`?

<details><summary>Ответ</summary>

У ручной джобы по умолчанию `allow_failure: true`, поэтому пайплайн считается
успешным, даже если кнопку не нажали. С `allow_failure: false` джоба становится
блокирующей: пайплайн переходит в состояние ожидания ручного действия и не завершается
успехом до нажатия.

</details>

---

### Блок B. «Что сделает этот конфиг»

```yaml
# B1
job:
  script: ["echo hi"]
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      when: manual
    - if: $CI_COMMIT_BRANCH =~ /^feature\/.*/
    - when: never
```
Вопрос: что произойдёт на ветке `main`, на `feature/x`, на `hotfix/y`?

<details><summary>Ответ</summary>

На `main` — джоба есть, но ручная (кнопка). На `feature/x` — джоба есть и
запускается автоматически. На `hotfix/y` — джобы нет (`when: never`).

</details>

```yaml
# B2
job:
  rules:
    - when: never
    - if: $CI_COMMIT_BRANCH == "main"
  script: ["echo deploy"]
```

<details><summary>Ответ</summary>

Джоба не появится никогда: первое правило `when: never` совпадает всегда и
останавливает проверку. Порядок правил критичен.

</details>

```yaml
# B3
build:
  script: ["npm ci", "npm run build"]
  cache:
    key: "$CI_COMMIT_SHA"
    paths: [node_modules/]
```
Вопрос: будет ли такой кэш работать? Почему?

<details><summary>Ответ</summary>

Кэш практически бесполезен: ключ `$CI_COMMIT_SHA` уникален для каждого коммита,
поэтому на каждом запуске кэш пустой, а старые копии копятся. Нужен ключ по файлу
зависимостей или по ветке.

</details>

```yaml
# B4
test:
  script: ["pytest"]
  artifacts:
    paths: [coverage/]
```
Вопрос: чего не хватает и чем это грозит через полгода?

<details><summary>Ответ</summary>

Нет `expire_in` — артефакты будут храниться по умолчанию и займут хранилище;
через полгода это выльется в переполнение квоты и блокировку CI. Также стоит добавить
`when: always`, если отчёт нужен и при падении тестов.

</details>

```yaml
# B5
deploy:
  script: ["echo $SECRET_TOKEN | base64"]
```

<details><summary>Ответ</summary>

Секрет попадёт в лог в base64: маскирование не сработает, потому что в логе
нет точного совпадения со значением. Это утечка — секрет нужно считать скомпрометированным.

</details>

```yaml
# B6
job:
  variables:
    URL: "https://example.com"
  script:
    - echo "$URL"
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      variables:
        URL: "https://prod.example.com"
```
Вопрос: что выведется на `main`, а что на другой ветке?

<details><summary>Ответ</summary>

На `main` — `https://prod.example.com` (переменная из сработавшего правила
переопределяет `variables` джобы). На других ветках правило не совпадает, джобы не будет
вовсе (нет других правил), так что вывода не будет — если добавить fallback-правило,
вывелось бы `https://example.com`.

</details>

```yaml
# B7
deploy:prod:
  script: ["./deploy.sh"]
  when: manual
```
Вопрос: будет ли пайплайн зелёным, если кнопку не нажали?

<details><summary>Ответ</summary>

Да, пайплайн будет зелёным: у ручной джобы по умолчанию `allow_failure: true`.
Чтобы пайплайн ждал решения — `allow_failure: false`.

</details>

```yaml
# B8
job_a:
  stage: build
  script: ["echo A > a.txt"]
  artifacts:
    paths: [a.txt]
job_b:
  stage: test
  dependencies: []
  script: ["cat a.txt"]
```

<details><summary>Ответ</summary>

`job_b` упадёт: `dependencies: []` отключает скачивание артефактов, файла `a.txt`
в рабочем каталоге не будет.

</details>

---

### Блок C. Практика

#### C1. 🔑 Правила запуска (главное задание)

Настрой пайплайн так, чтобы:
- `lint` и `unit` выполнялись **всегда** (MR, main, теги);
- `build` — только в MR и на `main`;
- `deploy:dev` — автоматически на любой ветке, кроме main;
- `deploy:staging` — автоматически на `main`;
- `deploy:prod` — только на `main`, кнопкой, блокирующей;
- пайплайн не создавался при пуше в ветку, если по ней открыт MR (без дублей).

Проверь все пять сценариев реальными пушами и зафиксируй результат в таблице.

<details><summary>Ответ</summary>

Рабочий каркас:
```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_COMMIT_TAG
    - if: $CI_OPEN_MERGE_REQUESTS
      when: never          # не создавать branch-пайплайн, если по ветке открыт MR
    - if: $CI_COMMIT_BRANCH

deploy:dev:
  rules:
    - if: $CI_COMMIT_BRANCH != $CI_DEFAULT_BRANCH && $CI_PIPELINE_SOURCE == "push"
deploy:staging:
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
deploy:prod:
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
```

</details>

#### C2. Секреты
1. Заведи переменную `DEPLOY_TOKEN` (masked, protected).
2. Убедись, что в джобе из непривилегированной ветки она пустая, а из `main` — доступна.
3. Заведи переменную типа **File** `SSH_KEY` и используй `chmod 600 "$SSH_KEY"`.
4. Попробуй вывести masked-переменную в лог напрямую и через `base64`.
   Зафиксируй, в каком случае маскирование сработало.
   ⚠️ Делай это только с тестовым значением, не с настоящим секретом.

<details><summary>Ответ</summary>

Ожидаемый результат: protected-переменная пуста в ветке, не являющейся защищённой;
прямой `echo` маскируется, `base64` — нет. Вывод: маскирование — страховка от случайности,
а не механизм защиты.

</details>

#### C3. Artifacts между джобами
Сделай цепочку: `build` создаёт `dist/` → `test` проверяет наличие файлов →
`package` кладёт архив с `expire_in: 1 week` и именем `$CI_JOB_NAME-$CI_COMMIT_SHORT_SHA`.
Скачай артефакт из UI.

<details><summary>Ответ</summary>

Проверка: артефакт скачивается из UI, файл присутствует в следующей джобе,
имя артефакта содержит SHA — по нему легко найти сборку.

</details>

#### C4. dotenv
Пусть джоба `version` вычисляет версию (`date +%Y.%m.%d-$CI_COMMIT_SHORT_SHA`)
и передаёт её через `artifacts: reports: dotenv`. Джоба `deploy` должна вывести эту версию.
Проверь, что без `needs`/зависимости переменная не приезжает.

<details><summary>Ответ</summary>

Без `needs`/зависимости по стадиям dotenv-переменные не подхватываются; это
частая причина «переменная пустая в следующей джобе».

</details>

#### C5. Кэш
1. Замерь время джобы `test` без кэша.
2. Добавь кэш зависимостей с ключом по файлу зависимостей.
3. Замерь время на втором запуске.
4. Измени файл зависимостей и убедись, что ключ (и кэш) сменился.
5. Поставь `policy: pull` в тестовой джобе и объясни, почему так лучше.

<details><summary>Ответ</summary>

Ожидаемо: вторая сборка заметно быстрее; при изменении файла зависимостей ключ
меняется и кэш пересоздаётся; `policy: pull` в тестовой джобе экономит время на упаковке
и исключает гонку за перезапись кэша.

</details>

#### C6. Окружения
1. Добавь `environment` в джобы staging и prod с `url`.
2. Задеплой дважды и посмотри Deployments → Environments: история, текущая версия.
3. Нажми Rollback и опиши, что именно происходит.
4. Сделай окружение `production` защищённым (Protected environments) и проверь права.

<details><summary>Ответ</summary>

Rollback запускает заново джобу деплоя предыдущего успешного деплоймента —
то есть повторно выполняет её скрипт (важно, чтобы он деплоил конкретную версию,
а не «последнюю»).

</details>

#### C7. Review app
Сделай динамическое окружение на MR: `review/$CI_COMMIT_REF_SLUG` c `on_stop` и
`auto_stop_in: 1 day`. Закрой MR и убедись, что джоба остановки отработала.
(Если деплоить некуда — пусть «деплой» просто пишет файл/лог, важна механика.)

<details><summary>Ответ</summary>

Критерий: после закрытия MR окружение исчезает из списка активных, а джоба
остановки отработала. Если этого не произошло — чаще всего джоба `stop` не попала
в пайплайн по `rules` или у неё другой `environment: name`.

</details>

#### C8. `resource_group`
Запусти два пайплайна подряд на `main` и убедись, что джобы деплоя не выполняются
одновременно. Опиши, что происходит со вторым пайплайном.

<details><summary>Ответ</summary>

Второй пайплайн ждёт освобождения ресурса: джоба деплоя переходит в состояние
ожидания и стартует только после завершения первой.

</details>

#### C9. Оптимизация `changes`
Раздели репозиторий на `backend/` и `frontend/`. Настрой, чтобы тесты бэкенда не гонялись
при изменении только фронтенда. Проверь на MR.

<details><summary>Ответ</summary>

Проверка: в MR, где изменён только `frontend/`, джобы бэкенда должны быть `skipped`.

</details>

---

### Блок D. Инциденты

**D1.** Джоба деплоя запускается на каждой фича-ветке и выкатывает на staging.
Как чинить и как проверить исправление, не ломая main?

<details><summary>Ответ</summary>

В `rules` джобы указать ветку по умолчанию (`$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH`)
и убрать автозапуск на произвольных ветках. Проверять безопасно: временно заменить
деплой-команду на `echo`, прогнать на тестовой ветке, посмотреть, в каких случаях джоба
появляется, и только потом вернуть реальный деплой.

</details>

**D2.** Переменная `$PROD_TOKEN` пустая в джобе, хотя в Settings она есть. Три причины.

<details><summary>Ответ</summary>

(1) Переменная protected, а ветка/тег не защищены; (2) у переменной задан
environment scope, не совпадающий с `environment` джобы; (3) переменная определена
в другом проекте/группе или переопределена пустым значением на уровне пайплайна/джобы;
(4) опечатка в имени.

</details>

**D3.** Секрет попал в лог, потому что джоба падала и выводила конфиг целиком.
Немедленные действия и системные меры.

<details><summary>Ответ</summary>

Немедленно: ротация секрета, удаление лога джобы, проверка, куда ещё он мог попасть
(артефакты, кэш, внешние системы). Системно: masked+protected, тип File, запрет `set -x`
рядом с секретами, вывод конфигов только с маскированием, сканер секретов в пайплайне
и в pre-commit.

</details>

**D4.** Джоба `deploy` не видит артефакты из `build`, хотя они есть в UI. Четыре причины.

<details><summary>Ответ</summary>

(1) `dependencies: []` или `dependencies` без нужной джобы; (2) `needs` без
`artifacts: true`/без этой джобы; (3) джоба-источник в той же или более поздней стадии;
(4) артефакты истекли (`expire_in`) или джоба-источник упала и не загрузила их;
(5) пути в `.gitignore` (не попадают в артефакты).

</details>

**D5.** Хранилище проекта переполнено, CI отказывается стартовать. Что проверить первым делом?

<details><summary>Ответ</summary>

Storage проекта: размер артефактов (Settings → Usage Quotas), наличие `expire_in`,
размер Container Registry и политики очистки, старые job logs. Быстрое решение —
удалить просроченные артефакты и настроить политику хранения.

</details>

**D6.** Тесты стали падать «через раз» после добавления кэша `node_modules`. Почему такое
бывает и как правильно?

<details><summary>Ответ</summary>

Кэш `node_modules` переносит состояние между запусками: смена версии Node,
частично установленные зависимости, платформозависимые бинарники (`node-gyp`) дают
«иногда работает». Правильнее кэшировать каталог менеджера пакетов (`.npm`, `~/.cache/pip`)
и ставить зависимости детерминированно (`npm ci`), а ключ привязывать к lock-файлу.

</details>

**D7.** Кэш не подхватывается: каждый запуск ставит зависимости заново. Пять причин.

<details><summary>Ответ</summary>

(1) Ключ меняется каждый запуск (`$CI_COMMIT_SHA`); (2) кэшируемый путь вне
`$CI_PROJECT_DIR`; (3) джобы идут на разных раннерах, а distributed cache (S3) не настроен;
(4) `policy: push`/`pull` выставлен не там; (5) кэш очищен (Clear runner caches) или истёк;
(6) в образе зависимости ставятся в другой каталог, чем кэшируется.

</details>

**D8.** Два человека нажали кнопку прод-деплоя одновременно, версии перемешались. Что настроить?

<details><summary>Ответ</summary>

`resource_group` на окружении прода (сериализация), плюс Protected environments
с ограниченным списком тех, кто может нажимать кнопку, и `interruptible`/отмена устаревших
пайплайнов.

</details>

**D9.** После мержа MR джоба `review:stop` не отработала, и стенды копятся. Что проверить?

<details><summary>Ответ</summary>

(1) Джоба `stop` не попала в пайплайн (её `rules` не совпали); (2) у джоб разные
`environment: name`; (3) нет `action: stop`; (4) нет прав/раннера для её запуска;
(5) окружение остановлено, но ресурсы удаляются самим скриптом, который упал.

</details>

**D10.** `rules` написаны так, что джоба не запускается нигде, но пайплайн зелёный.
Как такое отлаживать?

<details><summary>Ответ</summary>

Открыть Pipeline editor → Full configuration и проверить итоговые правила;
временно добавить джобу-диагностику, печатающую значения `$CI_PIPELINE_SOURCE`,
`$CI_COMMIT_BRANCH`, `$CI_COMMIT_TAG`; проверять по одному правилу, начиная с самого
широкого; помнить, что `when: never` в начале списка отключает всё.

</details>

**D11.** В MR-пайплайне не работает `changes` — джобы запускаются всегда.
Что может быть не так?

<details><summary>Ответ</summary>

Пайплайн не MR-типа (нет базы сравнения), сравнение идёт не с тем коммитом
(force-push, squash), пути указаны неверно (нужны glob'ы вроде `backend/**/*`),
либо изменения пришли из мержа веток. Диагностика — вывести список изменённых файлов
в отладочной джобе.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Чем `rules` лучше `only/except`?

<details><summary>Ответ</summary>

Сложная логика и регулярки, переопределение переменных, `changes`/`exists`,
собственный `when`/`allow_failure`, корректная работа с MR-пайплайнами.

</details>

**2.** Как запустить джобу только на main? Только по тегу? Только в MR?

<details><summary>Ответ</summary>

`- if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH`; `- if: $CI_COMMIT_TAG`;
`- if: $CI_PIPELINE_SOURCE == "merge_request_event"`.

</details>

**3.** Где хранить секреты в GitLab CI и какие флаги переменных знаешь?

<details><summary>Ответ</summary>

В Settings → CI/CD → Variables; флаги Masked, Protected, тип File, environment scope,
Raw; для зрелых сценариев — Vault/OIDC.

</details>

**4.** Чем `artifacts` отличается от `cache`?

<details><summary>Ответ</summary>

Артефакты — надёжная передача результатов и отчётов (хранятся в GitLab, живут до
`expire_in`); кэш — ускорение, хранится на раннере, может пропасть.

</details>

**5.** Как передать переменную из одной джобы в другую?

<details><summary>Ответ</summary>

Через `artifacts: reports: dotenv` (+ `needs`).

</details>

**6.** Как ускорить установку зависимостей?

<details><summary>Ответ</summary>

Кэш каталога пакетного менеджера с ключом по lock-файлу, `policy: pull` в тестовых
джобах, детерминированная установка (`npm ci`, `pip install -r` с хэшами).

</details>

**7.** Что такое environment и зачем он нужен?

<details><summary>Ответ</summary>

Механизм учёта деплоев: история, ссылка, откат, защита, scope переменных,
динамические стенды.

</details>

**8.** Как сделать ручное подтверждение деплоя?

<details><summary>Ответ</summary>

`when: manual` (+ `allow_failure: false` для блокирующей кнопки) и Protected environments
для ограничения круга тех, кто может нажать.

</details>

**9.** Как запретить одновременные деплои на одно окружение?

<details><summary>Ответ</summary>

`resource_group` (+ Protected environments и отмена устаревших пайплайнов).

</details>

**10.** Как сделать временный стенд на каждый MR?

<details><summary>Ответ</summary>

Динамическое окружение `review/$CI_COMMIT_REF_SLUG` с `on_stop` и `auto_stop_in`,
джоба остановки с `action: stop`.

</details>

---

### 🎯 Чек-лист

- [ ] Пишу `rules` и понимаю порядок «сверху вниз до первого совпадения»
- [ ] Убрал дубли пайплайнов и умею объяснить `workflow:rules`
- [ ] Секреты только в CI/CD Variables: masked + protected, ключи — типом File
- [ ] Ни одна моя джоба не печатает секреты в лог
- [ ] Различаю artifacts и cache и не путаю их назначение
- [ ] Использую `expire_in` во всех артефактах
- [ ] Передаю переменные между джобами через dotenv
- [ ] Кэш с ключом по lock-файлу реально ускорил пайплайн (замерил)
- [ ] У деплой-джоб есть `environment` с url и виден список деплоев
- [ ] Прод защищён: manual + protected branch + protected environment + `resource_group`
