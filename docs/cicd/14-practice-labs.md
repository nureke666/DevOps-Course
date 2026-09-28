---
title: "14. Практика: лабы из роадмапа"
description: "Шесть сквозных лаб: пайплайн build-test-deploy, три окружения, шаблоны CI, Jenkins, откат, GitHub Actions"
---

# 14. Практика: лабы из роадмапа

> Роадмап → 4. CI/CD → **2. Практика**
> «Лучше всего знакомиться с CI/CD на основе GitLab CI — вся практика рекомендована к нему.
> Написать простой пайплайн для приложения, которое было в линуксе, а затем в докере.»
> Здесь — те же задания, разложенные по шагам, с критериями приёмки и разбором.

---

## 📋 Список лаб

| № | Лаба | Что получишь | Темы |
|---|------|--------------|------|
| 1 | 🔑 Пайплайн build → test → deploy | Первый рабочий CI/CD для своего приложения | 05, 06, 07 |
| 2 | 🔑 Три окружения: dev / staging / prod | Реальный процесс доставки с кнопкой на прод | 06, 07, 13 |
| 3 | 🔑 Репозиторий шаблонов CI | Один стандарт на несколько проектов | 08 |
| 4 | Тот же пайплайн на Jenkins | Умение работать с обоими инструментами | 10, 11, 12 |
| 5 | Учения по откату | Проверенная процедура возврата версии | 03 |
| 6 | Тот же пайплайн на GitHub Actions | Второй CI в портфолио + OIDC и GitOps | 04, 13, 16 |

**Что нужно до начала:**
- приложение из блока Docker (с Dockerfile, `/health`, тестами);
- аккаунт на gitlab.com (бесплатный) + проект;
- одна VM для деплоя (та же, что в блоке Linux) с установленным docker и docker compose;
- SSH-ключ для деплоя (отдельный, не твой личный!).

```bash
# на VM: отдельный пользователь для деплоя
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG docker deploy
sudo mkdir -p /home/deploy/.ssh && sudo chmod 700 /home/deploy/.ssh

# на своей машине: ключ ТОЛЬКО для CI
ssh-keygen -t ed25519 -f ~/.ssh/ci_deploy -C "gitlab-ci-deploy" -N ""
# публичную часть — на сервер, приватную — в CI/CD Variables (тип File)
```

---

## 🧪 Лаба 1. Пайплайн из трёх стадий 🔑

> Задание роадмапа: **Build** — собрать Docker-образ из Dockerfile;
> **Test** — линтер (flake8/eslint и т.д.); **Deploy** — SSH на сервер, обновить контейнер.

### Что делаем
Полный путь коммита: проверка → сборка образа → публикация в GitLab Registry →
деплой на VM → проверка здоровья.

### Требования
1. Стадии: `lint` → `test` → `build` → `deploy`.
2. Образ тегируется `$CI_COMMIT_SHORT_SHA`, публикуется в GitLab Registry.
3. Деплой по SSH с ключом из CI/CD Variables (тип **File**).
4. После деплоя — проверка `/health` с ретраями (джоба падает, если сервис не поднялся).
5. Секретов в репозитории нет вообще.
6. Деплой выполняется только с ветки по умолчанию.

### Каркас `.gitlab-ci.yml`

```yaml
stages: [lint, test, build, deploy]

default:
  interruptible: true

variables:
  IMAGE: "$CI_REGISTRY_IMAGE"
  DOCKER_TLS_CERTDIR: "/certs"

workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_COMMIT_TAG
    - when: never

lint:
  stage: lint
  image: python:3.12-slim
  needs: []
  before_script: ["pip install -q flake8"]
  script: ["flake8 app/ --max-line-length=100"]

test:
  stage: test
  image: python:3.12-slim
  cache:
    key: { files: [requirements.txt] }
    paths: [.cache/pip]
  variables:
    PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"
  before_script: ["pip install -q -r requirements.txt -r requirements-dev.txt"]
  script: ["pytest -q --junitxml=report.xml"]
  artifacts:
    when: always
    expire_in: 1 week
    reports: { junit: report.xml }

build:
  stage: build
  image: docker:29
  services: [docker:29-dind]
  before_script:
    - echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
  script:
    - docker build -t "$IMAGE:$CI_COMMIT_SHORT_SHA" .
    - docker push "$IMAGE:$CI_COMMIT_SHORT_SHA"
    - echo "IMAGE_TAG=$CI_COMMIT_SHORT_SHA" >> build.env
  artifacts:
    reports: { dotenv: build.env }

deploy:
  stage: deploy
  image: alpine:3.20
  needs: [build]
  before_script:
    - apk add --no-cache openssh-client curl
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - chmod 600 "$SSH_KEY"
    - ssh-keyscan -H "$DEPLOY_HOST" >> ~/.ssh/known_hosts
  script:
    - |
      ssh -i "$SSH_KEY" "$DEPLOY_USER@$DEPLOY_HOST" "
        echo '$CI_REGISTRY_PASSWORD' | docker login -u '$CI_REGISTRY_USER' --password-stdin $CI_REGISTRY &&
        cd /opt/app &&
        APP_IMAGE=$IMAGE:$IMAGE_TAG docker compose up -d --pull always &&
        docker image prune -f"
    - curl -fsS --retry 10 --retry-delay 3 "http://$DEPLOY_HOST:8000/health"
  environment:
    name: production
    url: http://$DEPLOY_HOST:8000
  resource_group: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

### На сервере `/opt/app/docker-compose.yml`
```yaml
services:
  app:
    image: ${APP_IMAGE}
    restart: unless-stopped
    ports: ["8000:8000"]
    env_file: [/opt/app/.env]
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/health"]
      interval: 10s
      retries: 5
```

### Переменные проекта (Settings → CI/CD → Variables)
| Переменная | Тип | Флаги |
|------------|-----|-------|
| `SSH_KEY` | File | masked не нужен (File), **protected** |
| `DEPLOY_HOST` | Variable | protected |
| `DEPLOY_USER` | Variable | protected |

### Критерии приёмки
```bash
# 1. Пайплайн зелёный, 4 стадии
# 2. В Deploy → Container Registry лежит образ с тегом = короткому SHA
# 3. На сервере запущен именно этот тег:
ssh deploy@$HOST "docker ps --format '{{.Image}}'"     # должен совпасть с SHA
# 4. /health отвечает 200
curl -i http://$HOST:8000/health
# 5. В логе джоб НЕТ секретов (проверь глазами весь лог deploy)
# 6. Ломаем линтер → пайплайн краснеет и НЕ деплоит
# 7. Ломаем тест → то же самое
```

### Вопросы себе после лабы
1. Почему образ собирается один раз и не пересобирается при деплое?
2. Что произойдёт, если два пайплайна дойдут до `deploy` одновременно? (подсказка: `resource_group`)
3. Почему `ssh-keyscan`, а не `StrictHostKeyChecking=no`?
4. Как узнать, какая версия сейчас на сервере, не заходя на него?
5. Что нужно сделать, чтобы откатиться на предыдущую версию? Сколько это займёт?

---

## 🧪 Лаба 2. Три окружения 🔑

> Задание роадмапа (вариант 1): «Пайплайн с тестами и окружениями, три окружения:
> `dev` (деплоится автоматически по пушу в ветку), `staging` (автоматически по мержу в main),
> `prod` (только manual). Между стейджами передавать артефакты, использовать переменные
> окружения из CI/CD Settings для секретов. Добавить кэширование зависимостей.»

### Что делаем
Разворачиваем полноценный процесс доставки с тремя окружениями на одной VM
(три compose-проекта на разных портах) или на трёх VM, если есть ресурсы.

```text:no-line-numbers
 feature/*  ──push──►  dev      (авто)          :8001
 main       ──merge─►  staging  (авто) + smoke   :8002
 main       ──🔘─────►  prod     (manual)         :8003
```

### Требования
1. Один артефакт (образ по SHA) проходит все три окружения — **без пересборки**.
2. Кэш зависимостей с ключом по lock-файлу (замерить выигрыш).
3. Артефакты между стадиями: отчёт о тестах + `dotenv` с тегом образа.
4. Секреты — только в CI/CD Variables; прод-переменные **protected**.
5. У каждой джобы деплоя есть `environment` с url; в Environments видна история.
6. Прод — `when: manual`, `allow_failure: false`, `resource_group: production`.
7. Есть джоба `rollback:prod` (manual), деплоящая произвольный тег из переменной.
8. Smoke-проверка после каждого деплоя.

### Каркас (фрагмент)

```yaml
.deploy-template:
  image: alpine:3.20
  needs: [build]
  before_script:
    - apk add --no-cache openssh-client curl
    - chmod 600 "$SSH_KEY"
    - ssh-keyscan -H "$DEPLOY_HOST" >> /etc/ssh/ssh_known_hosts
  script:
    - |
      ssh -i "$SSH_KEY" "$DEPLOY_USER@$DEPLOY_HOST" "
        cd /opt/$ENV_NAME &&
        APP_IMAGE=$IMAGE:$IMAGE_TAG docker compose up -d --pull always"
    - curl -fsS --retry 10 --retry-delay 3 "http://$DEPLOY_HOST:$APP_PORT/health"
  environment:
    name: $ENV_NAME
    url: http://$DEPLOY_HOST:$APP_PORT

deploy:dev:
  extends: .deploy-template
  stage: deploy
  variables: { ENV_NAME: dev, APP_PORT: "8001" }
  rules:
    - if: $CI_COMMIT_BRANCH != $CI_DEFAULT_BRANCH && $CI_PIPELINE_SOURCE == "push"

deploy:staging:
  extends: .deploy-template
  stage: deploy
  variables: { ENV_NAME: staging, APP_PORT: "8002" }
  resource_group: staging
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy:prod:
  extends: .deploy-template
  stage: deploy
  variables: { ENV_NAME: prod, APP_PORT: "8003" }
  resource_group: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false

rollback:prod:
  extends: .deploy-template
  stage: deploy
  variables: { ENV_NAME: prod, APP_PORT: "8003", IMAGE_TAG: "$ROLLBACK_TAG" }
  resource_group: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Критерии приёмки
```bash
# 1. Пуш в feature-ветку → задеплоился ТОЛЬКО dev
# 2. Мерж в main → задеплоился staging, prod ждёт кнопки
# 3. Нажали кнопку → prod обновился, smoke прошёл
# 4. Один и тот же SHA на всех трёх:
for p in 8001 8002 8003; do curl -s http://$HOST:$p/version; echo; done
# 5. В Deployments → Environments видно три окружения и историю
# 6. Второй запуск пайплайна заметно быстрее за счёт кэша (записать цифры)
# 7. Откат: запустить rollback:prod с ROLLBACK_TAG=<предыдущий SHA>, замерить время
```

### Усложнения (по желанию)
- Динамические review-окружения на каждый MR (`environment: name: review/$CI_COMMIT_REF_SLUG`
  + `on_stop` + `auto_stop_in`).
- Protected environment `production`: право деплоя — только у Maintainer.
- Уведомление в Telegram/Slack из `after_script` при падении.
- Миграции БД отдельной джобой перед деплоем (expand/contract из темы 03).

---

## 🧪 Лаба 3. Репозиторий шаблонов CI 🔑

> Задание роадмапа (вариант 2): «Создать отдельный репозиторий с общими шаблонами,
> подключать через `include`. Один шаблон для Python-проектов, другой для Node.js,
> третий для Go. Каждый проект подключает нужный шаблон и переопределяет только переменные.»

### Что делаем
Платформенный подход: один источник правды для пайплайнов нескольких проектов.

```text:no-line-numbers
ci-templates/
├── templates/
│   ├── base.yml          # общие стадии, workflow, правила
│   ├── python.yml        # flake8/pytest/сборка образа
│   ├── nodejs.yml        # eslint/jest/сборка образа
│   ├── golang.yml        # golangci-lint/go test/сборка образа
│   └── deploy-ssh.yml    # универсальный деплой
└── README.md             # какие переменные принимает каждый шаблон
```

### Требования
1. Шаблоны версионируются git-тегами (`v1.0.0`), проекты подключаются с `ref`.
2. Проект-потребитель содержит **только** `include` + переменные (10-20 строк).
3. Три демо-проекта: Python, Node.js, Go — все работают на своих шаблонах.
4. У шаблонов есть дефолты и понятные имена переменных.
5. Выпуск `v1.1.0` не ломает проекты, закреплённые на `v1.0.0`.

### Пример `templates/python.yml`
```yaml
variables:
  PYTHON_VERSION: "3.12"
  LINT_PATHS: "app/"
  TEST_CMD: "pytest -q --junitxml=report.xml"

.python-base:
  image: python:${PYTHON_VERSION}-slim
  cache:
    key: { files: [requirements.txt] }
    paths: [.cache/pip]
  variables:
    PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"

lint:
  extends: .python-base
  stage: lint
  needs: []
  before_script: ["pip install -q flake8"]
  script: ["flake8 ${LINT_PATHS}"]

test:
  extends: .python-base
  stage: test
  before_script: ["pip install -q -r requirements.txt -r requirements-dev.txt"]
  script: ["${TEST_CMD}"]
  artifacts:
    when: always
    reports: { junit: report.xml }

build:
  stage: build
  image: docker:29
  services: [docker:29-dind]
  variables: { DOCKER_TLS_CERTDIR: "/certs" }
  before_script:
    - echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
  script:
    - docker build -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" .
    - docker push "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
```

### `.gitlab-ci.yml` проекта-потребителя
```yaml
include:
  - project: 'my-group/ci-templates'
    ref: 'v1.0.0'
    file:
      - '/templates/base.yml'
      - '/templates/python.yml'
      - '/templates/deploy-ssh.yml'

variables:
  PYTHON_VERSION: "3.11"
  LINT_PATHS: "src/ tests/"
  APP_PORT: "8000"

deploy:prod:
  extends: .deploy-ssh
  variables: { ENV_NAME: prod }
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### Критерии приёмки
1. Три проекта работают, их конфиги короткие и однотипные.
2. Изменение в шаблоне + новый тег → обновляется только тот проект, который сменил `ref`.
3. В README шаблонов перечислены все входные переменные и их дефолты.
4. Full configuration в Pipeline editor показывает раскрытый конфиг без сюрпризов.
5. Попробуй убрать `ref` в одном проекте и объясни в заметке, почему так делать нельзя.

---

## 🧪 Лаба 4. То же самое на Jenkins

### Что делаем
Повторяем лабу 1 на Jenkins — чтобы на собесе говорить про оба инструмента предметно.

### Требования
1. Jenkins в докере, агент — тоже в докере (или docker-агент в пайплайне).
2. `Jenkinsfile` в репозитории приложения, джоба типа **Multibranch Pipeline**.
3. Credentials: SSH-ключ и доступ к registry — из Jenkins Credentials.
4. Стадии: Checkout → Lint → Test (+`junit`) → Build&Push → Approve (`input`) → Deploy.
5. `post { always { cleanWs() } }`, `disableConcurrentBuilds()`, `lock('prod')`.
6. Запуск по вебхуку (или `pollSCM`, если Jenkins недоступен извне).

### Критерии приёмки
```text:no-line-numbers
1. Пуш в ветку → Multibranch автоматически создал джобу и запустил сборку
2. Отчёт о тестах виден в UI
3. Образ в registry с тегом = короткий SHA
4. Стадия Approve ждёт нажатия и не держит executor
5. В консоли нет секретов
6. Сравнил: сколько строк в .gitlab-ci.yml и сколько в Jenkinsfile
```

### Вопрос себе
Что в Jenkins оказалось удобнее, а что сложнее, чем в GitLab CI? Запиши — это готовый
ответ на собеседовании.

---

## 🧪 Лаба 5. Учения по откату

### Что делаем
Проверяем на практике, что откат — процедура, а не импровизация.

### Сценарий
1. Задеплой на прод заведомо «сломанную» версию (например, приложение падает на старте
   или `/health` возвращает 500).
2. Засеки время с момента «обнаружили проблему».
3. Откатись **без пересборки**: `rollback:prod` с предыдущим SHA.
4. Проверь `/health` и запиши общее время.

### Критерии приёмки
- Откат занял **меньше 5 минут** и не потребовал ни одной команды сборки.
- В Environments видно, что прод вернулся на предыдущую версию.
- Предыдущий образ был доступен в registry (политика очистки его не удалила).

### Разбор (запиши ответы)
1. Что именно откатывалось: код, конфиг, схема БД?
2. Что делать, если бы миграция уже применилась?
3. Кто в команде имеет право нажимать откат и как он узнает предыдущий тег?
4. Как сделать так, чтобы откат запускался автоматически при провале smoke-теста?

---

## 🧪 Лаба 6. Тот же пайплайн на GitHub Actions

### Что делаем
Повторяем лабы 1–2 на GitHub Actions для linkd — чтобы в резюме было «GitLab CI **и** GitHub
Actions», а на собесе — предметный ответ «чем они отличаются». Конспект: [16. GitHub Actions](/cicd/16-github-actions).

### Требования
1. **Публичный** репо `linkd` на GitHub (на Free environments с reviewers есть только в публичных)
   и репо `linkd-gitops` с `apps/linkd/{staging,production}/values.yaml`.
2. `.github/workflows/ci.yml`: `lint` → `test` (матрица Python, PostgreSQL в `services:` с
   health-check) → `build` (buildx, GHCR, тег `sha-<short>`, кэш в registry, в PR — без пуша).
3. `permissions: contents: read` на workflow; `packages: write` — только у `build`.
4. Деплой — reusable workflow `deploy-gitops.yml`: коммит тега в `linkd-gitops` токеном GitHub App
   (не `GITHUB_TOKEN`, не личный PAT); staging — автоматически с `main`, production — через
   environment с required reviewers и deployment branches `main`.
5. `concurrency`: отмена устаревших PR-запусков, очередь без отмены для деплоев.
6. Джоба `aws-smoke` с OIDC: `aws sts get-caller-identity` без единого AWS-ключа в секретах,
   trust policy с `sub` на `environment:production`.
7. Все экшены — по полному SHA, `.github/dependabot.yml` для `github-actions`,
   ruleset на `main` с required checks.

### Критерии приёмки
```text:no-line-numbers
1. PR → lint и test зелёные, образ собран, но НЕ запушен; повторный пуш в PR отменил старый запуск
2. Мерж в main → образ sha-xxxxxxx в GHCR, коммит в linkd-gitops от <app>[bot] для staging
3. production ждёт аппрува; после аппрува в linkd-gitops тот же тег, что на staging
4. Второй запуск быстрее: cache hit в setup-python и CACHED-слои в buildx (записать цифры)
5. aws-smoke показывает assumed-role; в Settings → Secrets нет AWS-ключей
6. actionlint и zizmor без ошибок; PR с заголовком `x"; echo pwned; echo "` ничего не выполнил
7. Сравнил: строки в .gitlab-ci.yml vs .github/workflows/*.yml и время пайплайна
```

### Вопрос себе
Что в Actions оказалось удобнее GitLab CI (Marketplace, матрицы, environments), а что хуже
(нет стадий, экшены как зависимость, секреты в форках)? Запиши — это ответ на вопрос 49 из
[15. Вопросы с собеседований](/cicd/15-interview).

---

## 🏁 Финальный чек-лист блока практики

- [ ] Лаба 1: пайплайн build→test→deploy работает, секретов в репо нет
- [ ] Лаба 2: три окружения, прод по кнопке, один артефакт на всех
- [ ] Лаба 2: кэш даёт измеримое ускорение (записал цифры)
- [ ] Лаба 2: есть работающая джоба отката
- [ ] Лаба 3: три проекта на общих шаблонах с пином версии
- [ ] Лаба 3: README шаблонов описывает все переменные
- [ ] Лаба 4: тот же процесс воспроизведён на Jenkins
- [ ] Лаба 5: откат отрепетирован и укладывается в 5 минут
- [ ] Лаба 6: тот же процесс на GitHub Actions — GHCR, GitOps через GitHub App, OIDC, экшены по SHA
- [ ] Все репозитории — в портфолио, конфиги объясняю построчно
