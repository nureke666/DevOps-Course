---
title: "08. GitLab CI: needs, extends, include, trigger"
description: "DAG через needs, YAML-якоря, extends, include, дочерние и межпроектные пайплайны, parallel/matrix — конспект и задачи"
---

# 08. GitLab CI: needs, extends, include, trigger

> Роадмап → 4. CI/CD → Инструменты → GitLab CI → **Хорошо**:
> `needs`, `extends` и YAML-якоря, `include`, `trigger`.
> **После темы ты умеешь:** ускорить пайплайн через DAG, убрать копипасту из конфига,
> вынести общие шаблоны в отдельный репозиторий и запускать пайплайны в других проектах.

---

## 1. `needs` — DAG вместо строгих стадий

По умолчанию джоба ждёт **всю** предыдущую стадию. `needs` позволяет ждать только конкретные джобы.

```text:no-line-numbers
БЕЗ needs (стадии)                     С needs (DAG)
build ████                             build:backend  ████
      ↓ (ждём всю стадию)              build:frontend ███
test  ████████                         test:backend    ████ (стартует сразу после build:backend)
      ↓                                test:frontend   ███
deploy    ███                          deploy          ███  (ждёт оба test)

общее: 15 мин                          общее: 9 мин
```

```yaml
build:backend:
  stage: build
  script: ["make backend"]
  artifacts: { paths: [bin/] }

build:frontend:
  stage: build
  script: ["npm ci && npm run build"]
  artifacts: { paths: [dist/] }

test:backend:
  stage: test
  needs: [build:backend]          # не ждём frontend
  script: ["make test-backend"]

test:frontend:
  stage: test
  needs: [build:frontend]
  script: ["npm test"]

deploy:
  stage: deploy
  needs: ["test:backend", "test:frontend"]
  script: ["./deploy.sh"]
```

### Тонкости

```yaml
needs:
  - job: build
    artifacts: true        # скачивать артефакты (по умолчанию true)
  - job: lint
    artifacts: false       # только дождаться, файлы не нужны
  - job: slow-scan
    optional: true         # если джобы нет в пайплайне — не ошибка

needs: []                  # ⭐ джоба стартует СРАЗУ, не дожидаясь ничего
```

| Правило | Смысл |
|---------|-------|
| Джоба в `needs` должна быть в **более ранней** стадии (или той же — с оговорками) | Иначе ошибка конфигурации |
| `needs: []` | Мгновенный старт (например, `lint` параллельно со сборкой) |
| `optional: true` | Нужен, когда джоба может быть исключена `rules` |
| Лимит | До 50 записей в `needs` (зависит от версии/настроек) |
| `needs` отменяет ожидание стадии | Но порядок `stages` всё равно должен быть корректным |

> ⭐ `needs` — самый дешёвый способ ускорить пайплайн: часто экономит 30-50% времени
> без изменения логики.

---

## 2. YAML-якоря и скрытые джобы

### Скрытые джобы (`.` в начале имени)

```yaml
.docker-login: &docker-login
  - echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"

.base-docker:
  image: docker:29
  services: [docker:29-dind]
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
```
Джобы, начинающиеся с точки, **не выполняются** — это шаблоны.

### Якоря (`&`), ссылки (`*`) и слияние (`<<`)

```yaml
.job-template: &job-template
  image: python:3.12-slim
  before_script: ["pip install -r requirements.txt"]
  cache:
    key: { files: [requirements.txt] }
    paths: [.cache/pip]

unit:
  <<: *job-template          # подставить весь блок
  stage: test
  script: ["pytest tests/unit"]

integration:
  <<: *job-template
  stage: test
  script: ["pytest tests/integration"]
```

Якоря — чистый YAML: работают только **внутри одного файла** и подставляются буквально.
Для переиспользования между файлами нужен `extends` + `include`.

---

## 3. `extends` — наследование джоб

```yaml
.deploy-template:
  stage: deploy
  image: alpine:3.20
  before_script:
    - apk add --no-cache openssh-client curl
  script:
    - ./deploy.sh "$DEPLOY_ENV"
    - curl -fsS "$HEALTH_URL"
  environment:
    name: $DEPLOY_ENV

deploy:staging:
  extends: .deploy-template
  variables:
    DEPLOY_ENV: staging
    HEALTH_URL: https://staging.example.com/health
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy:prod:
  extends: .deploy-template
  variables:
    DEPLOY_ENV: production
    HEALTH_URL: https://example.com/health
  resource_group: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false
```

| `extends` | YAML-якоря |
|-----------|------------|
| Работает **между файлами** (с `include`) | Только внутри одного файла |
| **Глубокое слияние** словарей (merge) | Буквальная подстановка |
| Можно наследовать цепочкой (до 11 уровней) | Вложенность вручную |
| Понятно читается | Требует знания YAML-синтаксиса |

**Правила слияния `extends`:**
- словари (`variables`, `artifacts`, `cache`) объединяются по ключам;
- **массивы заменяются целиком** (`script`, `rules`, `tags`) — частая ловушка;
- можно наследовать несколько шаблонов: `extends: [.base, .docker]` (последний важнее).

```yaml
# ⚠️ ловушка: script полностью заменится, а не дополнится
.base:
  script: ["echo A", "echo B"]
job:
  extends: .base
  script: ["echo C"]        # итог: только "echo C"
```

**Комбинация `extends` + `!reference`** (если нужно вставить кусок массива):

```yaml
.setup:
  script: ["apk add curl", "echo prepared"]

job:
  script:
    - !reference [.setup, script]     # подставит обе команды
    - ./run.sh
```

---

## 4. `include` — конфиг из других файлов и репозиториев

```yaml
include:
  # 1. локальный файл того же репозитория
  - local: '/ci/templates/build.yml'

  # 2. файл из другого проекта GitLab
  - project: 'devops/ci-templates'
    ref: 'v1.4.0'                       # ⭐ пин версии, не main!
    file:
      - '/templates/python.yml'
      - '/templates/deploy.yml'

  # 3. шаблон из поставки GitLab
  - template: 'Security/SAST.gitlab-ci.yml'

  # 4. внешний URL
  - remote: 'https://example.com/ci/common.yml'

  # 5. CI/CD-компонент (современный способ, GitLab 16.6+)
  - component: gitlab.com/devops/components/python-build@1.2.0
    inputs:
      python_version: "3.12"
```

**Правила:**
- `include` раскрывается **до** выполнения; итог смотри в Pipeline editor → Full configuration;
- локальные определения переопределяют включённые (при совпадении имён джоб);
- `ref` в `project` фиксирует версию шаблона — иначе один коммит в шаблонах может
  сломать пайплайны всех проектов сразу;
- в `include` можно добавлять `rules` (условное подключение).

### Централизованные шаблоны — как это выглядит на практике

```text:no-line-numbers
ci-templates (отдельный репозиторий)
├── templates/
│   ├── python.yml       # lint + test + build для Python-проектов
│   ├── nodejs.yml
│   ├── go.yml
│   └── deploy-ssh.yml   # общая джоба деплоя
└── README.md            # как подключать и какие переменные переопределять
```

```yaml
# .gitlab-ci.yml обычного проекта — всё, что нужно проекту
include:
  - project: 'devops/ci-templates'
    ref: 'v1.4.0'
    file: '/templates/python.yml'

variables:
  PYTHON_VERSION: "3.12"
  APP_NAME: "billing"

deploy:prod:
  extends: .deploy-ssh
  variables:
    DEPLOY_HOST: $PROD_HOST
```
Это ровно задание №2 из практики роадмапа (см. [тему 14](/cicd/14-practice-labs)).

---

## 5. `trigger` — дочерние и межпроектные пайплайны

### Child pipeline (внутри проекта)

```yaml
backend:
  stage: build
  trigger:
    include: backend/.gitlab-ci.yml
    strategy: depend            # ждать результата дочернего пайплайна
  rules:
    - changes: ["backend/**/*"]

frontend:
  stage: build
  trigger:
    include: frontend/.gitlab-ci.yml
    strategy: depend
  rules:
    - changes: ["frontend/**/*"]
```

Зачем: монорепозиторий, где у каждого компонента свой пайплайн; вынос сложной части
в отдельный файл; динамическая генерация конфига.

**Динамический child pipeline** — конфиг генерируется джобой:

```yaml
generate:
  stage: prepare
  script: ["./generate-ci.py > generated.yml"]
  artifacts: { paths: [generated.yml] }

run-generated:
  stage: build
  needs: [generate]
  trigger:
    include:
      - artifact: generated.yml
        job: generate
    strategy: depend
```

### Multi-project pipeline

```yaml
deploy:infra:
  stage: deploy
  trigger:
    project: devops/infrastructure
    branch: main
    strategy: depend
  variables:
    APP_IMAGE: "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
    UPSTREAM_PROJECT: "$CI_PROJECT_PATH"
```

В принимающем проекте пайплайн отличает такой запуск по `$CI_PIPELINE_SOURCE == "pipeline"`
и получает переданные переменные. Так, например, обновляют config-repo в GitOps-схеме
или запускают деплой из отдельного infra-проекта.

| Ключ | Смысл |
|------|-------|
| `strategy: depend` | Родительская джоба ждёт дочерний пайплайн и падает вместе с ним |
| без `strategy` | «Выстрелил и забыл»: джоба зелёная сразу после запуска |
| `forward:` | Что пробрасывать в дочерний пайплайн (переменные, yaml-переменные) |
| `$CI_PIPELINE_SOURCE` | `parent_pipeline` для child, `pipeline` для multi-project |

---

## 6. `parallel` и матрицы

```yaml
# 1. Просто N копий джобы (шардирование тестов)
test:
  parallel: 4
  script:
    - pytest --splits $CI_NODE_TOTAL --group $CI_NODE_INDEX

# 2. Матрица: джоба на каждую комбинацию
test:versions:
  parallel:
    matrix:
      - PYTHON: ["3.11", "3.12"]
        DJANGO: ["4.2", "5.0"]
  image: python:$PYTHON
  script: ["pip install django==$DJANGO", "pytest"]
# получится 4 джобы: 3.11/4.2, 3.11/5.0, 3.12/4.2, 3.12/5.0
```

Матрицы полезны и для деплоя в несколько регионов/кластеров:

```yaml
deploy:
  parallel:
    matrix:
      - REGION: [eu, us, ap]
  script: ["./deploy.sh $REGION"]
  environment:
    name: production/$REGION
```

---

## 7. Прочее из «хорошо бы знать»

```yaml
job:
  retry:
    max: 2
    when: [runner_system_failure, stuck_or_timeout_failure]   # не «любая ошибка»!
  timeout: 30m
  interruptible: true
  resource_group: production
  dependencies: []              # не качать артефакты
  allow_failure:
    exit_codes: [137]           # считать успехом конкретный код
```

**Правило про `retry`:** повторять можно **инфраструктурные** сбои (раннер умер, таймаут),
но не падающие тесты — иначе прячешь реальные проблемы (см. тему 01).

---

## 8. Рефакторинг конфига: до и после

```yaml
# ❌ ДО: 4 почти одинаковые джобы, 60 строк копипасты
deploy:dev:
  stage: deploy
  image: alpine:3.20
  before_script: ["apk add --no-cache openssh-client curl"]
  script: ["./deploy.sh dev", "curl -fsS https://dev.example.com/health"]
  rules: [{ if: '$CI_COMMIT_BRANCH != $CI_DEFAULT_BRANCH' }]
# ... ещё три такие же
```

```yaml
# ✅ ПОСЛЕ
include:
  - local: '/ci/deploy.yml'

.deploy:
  stage: deploy
  image: alpine:3.20
  before_script: ["apk add --no-cache openssh-client curl"]
  script:
    - ./deploy.sh "$ENV_NAME"
    - curl -fsS "$HEALTH_URL"
  environment:
    name: $ENV_NAME
    url: $BASE_URL

deploy:dev:
  extends: .deploy
  variables: { ENV_NAME: dev, BASE_URL: "https://dev.example.com", HEALTH_URL: "https://dev.example.com/health" }
  rules: [{ if: '$CI_COMMIT_BRANCH != $CI_DEFAULT_BRANCH' }]

deploy:staging:
  extends: .deploy
  variables: { ENV_NAME: staging, BASE_URL: "https://staging.example.com", HEALTH_URL: "https://staging.example.com/health" }
  rules: [{ if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH' }]

deploy:prod:
  extends: .deploy
  variables: { ENV_NAME: production, BASE_URL: "https://example.com", HEALTH_URL: "https://example.com/health" }
  resource_group: production
  rules: [{ if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH', when: manual, allow_failure: false }]
```

---

## 💼 Как это в DevOps

- Централизованные шаблоны (`include` из общего репозитория) — типовая задача платформенной
  команды: 40 проектов, один стандарт пайплайна, обновление в одном месте.
- Версионирование шаблонов (`ref: v1.4.0`) — обязательное требование: иначе один коммит
  ломает CI всей компании.
- `needs` — первое, что применяют при жалобе «пайплайн долгий», после кэша.
- Child pipelines спасают монорепозитории: не гонять весь пайплайн из-за правки в одном сервисе.
- `extends` + `!reference` — то, чем отличают «умею писать ямлы» от «умею поддерживать CI».

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Не ждать всю стадию | `needs: [job]` |
| Стартовать сразу | `needs: []` |
| Дождаться, но без файлов | `needs: [{job: x, artifacts: false}]` |
| Не падать, если джобы нет | `needs: [{job: x, optional: true}]` |
| Шаблон-джоба | Имя с точки: `.template:` |
| Подставить блок (один файл) | Якорь `&name` + `<<: *name` |
| Наследование между файлами | `extends: .template` |
| Вставить кусок массива | `!reference [.job, script]` |
| Подключить общий конфиг | `include: - project: ... ref: vX.Y.Z file: ...` |
| Готовые шаблоны GitLab | `include: - template: 'Security/SAST.gitlab-ci.yml'` |
| Дочерний пайплайн | `trigger: include: ... strategy: depend` |
| Пайплайн в другом проекте | `trigger: project: group/other` |
| N копий джобы | `parallel: 4` (+ `$CI_NODE_INDEX`) |
| Комбинации параметров | `parallel: matrix:` |
| Повтор только при сбое раннера | `retry: {max: 2, when: [runner_system_failure]}` |

---

## 🧠 Что запомнить

1. `needs` превращает стадии в DAG и обычно даёт самый быстрый выигрыш по времени.
2. `needs: []` — мгновенный старт джобы; `optional: true` — для джоб под `rules`.
3. Джобы с точки в начале имени — шаблоны, они не выполняются.
4. Якоря YAML работают только внутри файла; между файлами — `extends`.
5. При `extends` словари сливаются, **массивы заменяются целиком** (`script`, `rules`).
6. `!reference` позволяет вставлять куски массивов из других джоб.
7. `include` умеет: local, project, template, remote, component.
8. Всегда пинуй версию шаблонов (`ref: v1.4.0`) — иначе чужой коммит ломает твой CI.
9. Итоговую конфигурацию после раскрытия смотри в Pipeline editor → Full configuration.
10. `trigger` + `strategy: depend` — дочерний/межпроектный пайплайн с ожиданием результата.
11. Child pipelines + `rules: changes` — стандартное решение для монорепозиториев.
12. `retry` — только для инфраструктурных сбоев, не для флакающих тестов.

---

## Задачи

> Лаба: проект из тем 05-07 + **второй** проект `ci-templates` для заданий про `include`.

---

### Блок A. Теория

**A1.** Что делает `needs` и чем DAG отличается от обычного порядка стадий?

<details><summary>Ответ</summary>

`needs` задаёт явные зависимости между джобами: джоба стартует, как только
завершились указанные джобы, не дожидаясь окончания всей предыдущей стадии.
Пайплайн превращается из последовательности стадий в направленный ациклический граф (DAG),
что сокращает общее время.

</details>

**A2.** Что означает `needs: []`? Когда это применяют?

<details><summary>Ответ</summary>

Пустой список зависимостей: джоба стартует сразу при запуске пайплайна,
независимо от стадии. Применяют для быстрых проверок (линтер, валидация конфигов),
чтобы обратная связь пришла максимально рано.

</details>

**A3.** Зачем нужны `artifacts: false` и `optional: true` внутри `needs`?

<details><summary>Ответ</summary>

`artifacts: false` — дождаться джобу, но не скачивать её артефакты (экономия
времени и трафика). `optional: true` — не считать ошибкой отсутствие джобы в пайплайне
(она могла быть исключена `rules`), иначе конфигурация станет невалидной.

</details>

**A4.** Может ли джоба в `needs` находиться в более поздней стадии? Что будет?

<details><summary>Ответ</summary>

Нет: джоба может зависеть только от джоб более ранних стадий (или, с ограничениями,
той же стадии). Иначе GitLab вернёт ошибку конфигурации ещё до запуска пайплайна.

</details>

**A5.** Что такое скрытая джоба и как её объявить?

<details><summary>Ответ</summary>

Джоба, имя которой начинается с точки (`.template:`). Она не попадает в пайплайн
и служит шаблоном для `extends`/якорей.

</details>

**A6.** Как работают YAML-якоря (`&`, `*`, `<<`)? В чём их главное ограничение?

<details><summary>Ответ</summary>

`&name` объявляет якорь, `*name` подставляет его значение, `<<: *name` сливает
словарь в текущий. Ограничение: это механизм самого YAML, поэтому работает **только
внутри одного файла** и не переживает `include`.

</details>

**A7.** Чем `extends` лучше якорей? Назови четыре отличия.

<details><summary>Ответ</summary>

`extends` работает между файлами (в том числе с `include`), выполняет глубокое
слияние словарей, поддерживает цепочки и множественное наследование, и гораздо
читаемее для тех, кто не знает тонкостей YAML.

</details>

**A8.** Что произойдёт с ключом `script`, если он есть и в шаблоне, и в наследнике?
А что будет с `variables`?

<details><summary>Ответ</summary>

`script` — массив, он **заменяется целиком** значением наследника.
`variables` — словарь, он сливается по ключам: общие ключи берутся из наследника,
остальные наследуются.

</details>

**A9.** Что делает `!reference` и какую проблему решает?

<details><summary>Ответ</summary>

`!reference [.job, script]` подставляет значение конкретного ключа другой (в том
числе скрытой) джобы — включая элементы массивов. Решает проблему «нужно дополнить,
а не заменить» массивы вроде `script` и `before_script`.

</details>

**A10.** Перечисли все типы `include` и приведи пример каждого.

<details><summary>Ответ</summary>

`local` (файл в том же репо), `project` (+`ref`+`file` — из другого проекта),
`template` (встроенные шаблоны GitLab), `remote` (URL), `component` (CI/CD-компоненты
с `inputs`). Примеры — в конспекте §4.

</details>

**A11.** Почему обязательно указывать `ref` при `include: project:`?

<details><summary>Ответ</summary>

Без `ref` подключается ветка по умолчанию шаблонного репозитория: любой коммит
туда моментально меняет пайплайны всех потребителей — в том числе ломает их.
`ref: vX.Y.Z` фиксирует версию и делает обновление осознанным действием.

</details>

**A12.** Что произойдёт, если джоба с тем же именем есть и в include-файле, и в локальном конфиге?

<details><summary>Ответ</summary>

Локальное определение переопределяет включённое: при совпадении имён джоба
из `.gitlab-ci.yml` побеждает (можно также точечно переопределять отдельные ключи).

</details>

**A13.** Чем child pipeline отличается от multi-project pipeline?

<details><summary>Ответ</summary>

Child pipeline — отдельный пайплайн **внутри того же проекта**, описанный другим
файлом (или сгенерированный). Multi-project — запуск пайплайна **в другом проекте**,
со своими переменными, правами и репозиторием.

</details>

**A14.** Что делает `strategy: depend`? Что будет без него?

<details><summary>Ответ</summary>

`strategy: depend` заставляет родительскую джобу ждать завершения дочернего
пайплайна и наследовать его статус. Без него джоба-триггер завершается успешно сразу
после запуска, и падение дочернего пайплайна не отразится на родительском.

</details>

**A15.** Как сгенерировать конфиг пайплайна динамически?

<details><summary>Ответ</summary>

Джоба генерирует YAML (скриптом), сохраняет его артефактом, а следующая джоба
подключает его через `trigger: include: - artifact: generated.yml, job: generate`.

</details>

**A16.** Как отличить в дочернем проекте, что пайплайн запущен через `trigger`?

<details><summary>Ответ</summary>

По `$CI_PIPELINE_SOURCE`: `pipeline` для multi-project trigger,
`parent_pipeline` для child. Дополнительно приходят переменные, переданные в `trigger`,
и `$CI_PIPELINE_TRIGGERED`/upstream-переменные.

</details>

**A17.** Чем `parallel: 4` отличается от `parallel: matrix`? Какие переменные доступны
в шардированной джобе?

<details><summary>Ответ</summary>

`parallel: N` создаёт N одинаковых копий джобы (для шардирования), внутри доступны
`$CI_NODE_INDEX` (1..N) и `$CI_NODE_TOTAL`. `parallel: matrix` создаёт джобу на каждую
комбинацию значений переменных — для тестирования на разных версиях/платформах.

</details>

**A18.** В каких случаях допустим `retry` и почему нельзя ставить его «на всякий случай»?

<details><summary>Ответ</summary>

Допустим для инфраструктурных сбоев: `runner_system_failure`,
`stuck_or_timeout_failure`, иногда `api_failure`, `scheduler_failure`. «На всякий случай»
нельзя, потому что он маскирует флакающие тесты и недетерминированные баги, увеличивает
время пайплайна и может привести к повторному выполнению небезопасных операций (деплой).

</details>

**A19.** Где посмотреть итоговый конфиг после раскрытия `include`, `extends` и якорей?

<details><summary>Ответ</summary>

Build → Pipeline editor → вкладка **Full configuration** (или API `ci/lint`).

</details>

---

### Блок B. «Что сделает этот конфиг»

```yaml
# B1
stages: [build, test, deploy]
a: { stage: build, script: ["sleep 60"] }
b: { stage: build, script: ["sleep 10"] }
c: { stage: test, needs: [b], script: ["echo c"] }
d: { stage: deploy, needs: [c], script: ["echo d"] }
```
Вопрос: через сколько секунд примерно стартует `d` и почему?

<details><summary>Ответ</summary>

`d` стартует примерно через 10 секунд + время `c`: `c` зависит только от `b`
(10 c), а не от всей стадии `build`, поэтому долгая джоба `a` не блокирует цепочку
(хотя сам пайплайн завершится не раньше, чем закончится `a`).

</details>

```yaml
# B2
.base:
  script: ["echo base1", "echo base2"]
  variables: { A: "1", B: "2" }
job:
  extends: .base
  script: ["echo job"]
  variables: { B: "3", C: "4" }
```
Вопрос: что выполнится и какие переменные будут заданы?

<details><summary>Ответ</summary>

Выполнится только `echo job` (массив `script` заменён). Переменные:
`A=1` (унаследована), `B=3` (переопределена), `C=4` (добавлена).

</details>

```yaml
# B3
.t: &t
  image: alpine
  before_script: ["echo prep"]
job1:
  <<: *t
  script: ["echo 1"]
job2:
  <<: *t
  before_script: ["echo custom"]
  script: ["echo 2"]
```

<details><summary>Ответ</summary>

`job1` использует `before_script: echo prep`; `job2` переопределяет его
на `echo custom` (подстановка якоря произошла, но собственный ключ джобы выиграл).

</details>

```yaml
# B4
include:
  - project: 'devops/ci-templates'
    file: '/templates/python.yml'
```
Вопрос: какой риск в этой записи?

<details><summary>Ответ</summary>

Нет `ref`: подключается ветка по умолчанию репозитория шаблонов, любое изменение
там немедленно влияет на этот проект. Нужно пинить тег/коммит.

</details>

```yaml
# B5
child:
  trigger:
    include: sub/.gitlab-ci.yml
```
Вопрос: упадёт ли родительский пайплайн, если дочерний красный?

<details><summary>Ответ</summary>

Нет: без `strategy: depend` родительская джоба завершится успешно сразу после
запуска дочернего пайплайна.

</details>

```yaml
# B6
test:
  parallel:
    matrix:
      - OS: ["alpine", "debian"]
        VER: ["3.11", "3.12", "3.13"]
  script: ["echo $OS $VER"]
```
Вопрос: сколько джоб создастся?

<details><summary>Ответ</summary>

6 джоб (2 × 3).

</details>

```yaml
# B7
job:
  retry: 2
  script: ["pytest"]
```

<details><summary>Ответ</summary>

`retry: 2` повторит джобу при **любом** типе падения, в том числе при падении
тестов — это маскирует нестабильность. Нужно ограничить `when:` инфраструктурными причинами.

</details>

---

### Блок C. Практика

#### C1. 🔑 Ускорь пайплайн через `needs`

1. Замерь текущее время пайплайна (из UI).
2. Построй DAG: `lint` с `needs: []`, тесты после сборки нужной части,
   деплой после всех тестов.
3. Замерь время снова и запиши выигрыш в процентах.
4. Нарисуй получившийся граф в заметке.

<details><summary>Ответ</summary>

Ориентир: на типовом пайплайне из 6-10 джоб DAG даёт 20-50% экономии. Если выигрыша
нет — скорее всего, узкое место в одной длинной джобе (её надо оптимизировать отдельно)
или не хватает раннеров.

</details>

#### C2. Рефакторинг копипасты
Возьми свой `.gitlab-ci.yml` и сократи его: вынеси общее в `.templates`, примени `extends`,
убери дублирующиеся `before_script`. Цель — минус 30% строк без потери функциональности.
Проверь эквивалентность через Full configuration.

<details><summary>Ответ</summary>

Проверка эквивалентности: сравнить Full configuration до и после рефакторинга —
набор джоб и ключей должен совпасть.

</details>

#### C3. Ловушка с массивами
Создай шаблон со `script` из двух команд и наследника со своим `script`.
Убедись, что команды шаблона **не** выполняются. Затем добейся, чтобы выполнялись и те,
и другие, через `!reference`.

<details><summary>Ответ</summary>

Ожидаемо: в первом варианте команды шаблона теряются; с `!reference [.tpl, script]`
выполняются и шаблонные, и собственные команды.

</details>

#### C4. 🔑 Свой репозиторий шаблонов (задание №2 из практики роадмапа)

1. Создай проект `ci-templates` со структурой:
   ```text:no-line-numbers
   templates/python.yml    # lint, test, build для Python
   templates/nodejs.yml
   templates/deploy-ssh.yml
   README.md
   ```
2. В шаблонах используй переменные с дефолтами (`PYTHON_VERSION`, `APP_NAME`, `DEPLOY_HOST`).
3. Поставь git-тег `v1.0.0`.
4. Подключи шаблон в двух разных проектах через `include: project: ... ref: v1.0.0`.
5. Проекты должны переопределять **только переменные**.
6. Выпусти `v1.1.0` с изменением и покажи, что проекты на `v1.0.0` не затронуты.

<details><summary>Ответ</summary>

Критерии приёмки: в проектах-потребителях `.gitlab-ci.yml` занимает 10-20 строк
и содержит только `include` и переменные; выпуск `v1.1.0` не меняет поведение проектов,
закреплённых на `v1.0.0`; в README шаблонов описаны входные переменные и их дефолты.

</details>

#### C5. Условный include
Подключай шаблон security-сканов только на `main` (подсказка: `rules` внутри `include`).

<details><summary>Ответ</summary>

```yaml
include:
  - template: 'Security/SAST.gitlab-ci.yml'
    rules:
      - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

</details>

#### C6. Child pipeline для монорепозитория
Сделай репозиторий с `backend/` и `frontend/`, у каждого свой `.gitlab-ci.yml`.
Родительский конфиг запускает дочерние пайплайны только при изменении соответствующего
каталога, с `strategy: depend`. Проверь тремя MR: правка бэка, правка фронта, правка обоих.

<details><summary>Ответ</summary>

Ожидаемо: правка только `backend/` запускает один дочерний пайплайн;
правка обоих каталогов — два; правка README — ни одного (или только общий job).

</details>

#### C7. Динамическая генерация
Напиши скрипт, который по списку каталогов `services/*` генерирует джобы сборки,
и запусти его результат как child pipeline через `trigger: include: artifact:`.

<details><summary>Ответ</summary>

Типичная ошибка — генерировать YAML с отступами «на глаз»: проверяй результат
локально (`yq`/`python -c 'import yaml,sys;yaml.safe_load(sys.stdin)'`) прямо в джобе
до передачи в `trigger`.

</details>

#### C8. Multi-project trigger
Из проекта приложения запусти пайплайн в проекте `infrastructure`, передав
`APP_IMAGE=$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA`. В принимающем проекте выведи
эту переменную и `$CI_PIPELINE_SOURCE`.

<details><summary>Ответ</summary>

В принимающем проекте `$CI_PIPELINE_SOURCE` будет `pipeline`, а `APP_IMAGE`
придёт как обычная переменная. Не забудь, что у принимающего проекта должны быть права
на запуск (и токен/разрешения на trigger).

</details>

#### C9. Матрица
Настрой прогон тестов на двух версиях Python через `parallel: matrix`.
Сделай так, чтобы падение на экспериментальной версии не валило пайплайн
(подсказка: отдельная джоба с `allow_failure: true`).

<details><summary>Ответ</summary>

Вариант: основная матрица без `allow_failure`, отдельная джоба для
экспериментальной версии с `allow_failure: true` — тогда её падение даёт жёлтый статус.

</details>

#### C10. Шардирование тестов
Раздели тесты на 4 параллельные джобы через `parallel: 4` и `$CI_NODE_INDEX`/`$CI_NODE_TOTAL`.
Сравни время стадии тестов до и после.

<details><summary>Ответ</summary>

Ориентир: 4 шарда дают ускорение стадии тестов примерно в 2.5-3.5 раза
(не в 4 — есть накладные расходы на старт джоб и установку зависимостей).

</details>

---

### Блок D. Инциденты

**D1.** После добавления `needs` джоба `deploy` стала падать с «нет файла из build».
Причина?

<details><summary>Ответ</summary>

Явные `needs` заменяют неявное скачивание артефактов всех предыдущих стадий:
теперь скачиваются артефакты только перечисленных джоб. Нужно добавить джобу-источник
в `needs` (с `artifacts: true`).

</details>

**D2.** Конфиг перестал валидироваться: «job `test` needs job `build` in a later stage».
Что случилось?

<details><summary>Ответ</summary>

Кто-то поменял порядок `stages` или стадию джобы: `build` оказался после `test`.
`needs` требует, чтобы зависимость была в более ранней стадии.

</details>

**D3.** Один коммит в репозиторий шаблонов сломал пайплайны в 30 проектах.
Что было настроено неправильно и как это исправить навсегда?

<details><summary>Ответ</summary>

Проекты подключали шаблон без `ref` (с ветки по умолчанию). Исправление: пинить
теги версий, вести шаблоны как продукт (SemVer, changelog, тестовый проект-канарейка,
объявление о breaking changes).

</details>

**D4.** В проекте подключили шаблон, но джоба из него не появилась в пайплайне. Четыре причины.

<details><summary>Ответ</summary>

(1) Не совпал `rules` у джобы; (2) джоба переопределена локально или её имя
совпало с локальной; (3) неверный путь/`ref`/`file` в `include` (проверь Full configuration);
(4) нет прав на чтение шаблонного проекта у этого проекта/токена; (5) шаблон описывает
скрытую джобу, которую никто не расширил.

</details>

**D5.** Наследник через `extends` потерял часть `before_script` из шаблона. Почему?

<details><summary>Ответ</summary>

`before_script` — массив: он заменяется целиком значением наследника, а не
дополняется. Нужно `!reference` или перенос общей части в отдельный ключ.

</details>

**D6.** Child pipeline запускается, но родительский пайплайн всегда зелёный,
даже когда дочерний красный. Что забыли?

<details><summary>Ответ</summary>

`strategy: depend`.

</details>

**D7.** После перехода на матрицу тестов пайплайн стал медленнее, а не быстрее. Как так?

<details><summary>Ответ</summary>

Матрица размножила джобы, а раннеров столько же: джобы встали в очередь.
Плюс каждая джоба заново ставит зависимости (нет кэша) и тратит время на старт контейнера.
Решение: ограничить размер матрицы, добавить кэш и раннеров, выносить редкие комбинации
в nightly.

</details>

**D8.** `retry: 2` поставили на джобу деплоя. Через месяц обнаружили, что деплой
иногда выполняется дважды. Чем это опасно и что делать?

<details><summary>Ответ</summary>

Повторный запуск деплоя может привести к двойному применению неидемпотентных
операций (миграции, отправка уведомлений, платежи). Деплой должен быть идемпотентным,
а `retry` для него — либо отсутствовать, либо ограничиваться `runner_system_failure`.

</details>

**D9.** Динамический child pipeline падает с «config should be an object».
Что проверить в сгенерированном файле?

<details><summary>Ответ</summary>

Сгенерированный файл пустой или содержит невалидный YAML (сообщение об ошибке
скрипта попало в файл); отступы сломаны; артефакт не сохранён/не указан `job:`;
в файле нет ни одной джобы.

</details>

**D10.** В монорепозитории при правке одного сервиса запускаются пайплайны всех.
Что настроить?

<details><summary>Ответ</summary>

Child pipelines с `rules: changes` по каталогам сервисов (или `rules: changes`
на самих джобах), чтобы запускалось только то, что затронуто изменением.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое `needs` и зачем он нужен?

<details><summary>Ответ</summary>

Механизм явных зависимостей между джобами; превращает пайплайн в DAG и ускоряет его,
позволяя джобам стартовать раньше окончания стадии.

</details>

**2.** Чем `extends` отличается от YAML-якорей? (частый вопрос из роадмапа)

<details><summary>Ответ</summary>

`extends` — механизм GitLab: работает между файлами, делает глубокое слияние словарей,
поддерживает цепочки; якоря — механизм YAML: только внутри файла, буквальная подстановка.

</details>

**3.** Что происходит с `script` и `variables` при `extends`?

<details><summary>Ответ</summary>

`script` (массив) заменяется целиком, `variables` (словарь) сливается по ключам.

</details>

**4.** Как переиспользовать конфигурацию между проектами?

<details><summary>Ответ</summary>

Отдельный репозиторий шаблонов + `include: project: ... ref: ... file: ...`
(или CI/CD-компоненты), проекты переопределяют только переменные.

</details>

**5.** Зачем указывать `ref` при подключении шаблонов?

<details><summary>Ответ</summary>

Чтобы изменения в шаблонах не влияли на потребителей мгновенно; обновление версии —
осознанное действие с возможностью отката.

</details>

**6.** Что такое child pipeline и когда он нужен?

<details><summary>Ответ</summary>

Отдельный пайплайн внутри проекта, описанный другим файлом или сгенерированный;
нужен для монорепозиториев, разделения сложных конфигов и динамической генерации.

</details>

**7.** Как запустить пайплайн в другом проекте?

<details><summary>Ответ</summary>

`trigger: project: group/project` (+ `branch`, `strategy: depend`, переменные).

</details>

**8.** Как ускорить пайплайн из 20 джоб?

<details><summary>Ответ</summary>

Кэш, `needs`, параллелизм и шардирование, `rules: changes`, разделение на child
pipelines, вынос медленного в nightly, больше раннеров.

</details>

**9.** Как организовать CI для монорепозитория?

<details><summary>Ответ</summary>

Child pipelines по каталогам + `rules: changes` + общие шаблоны через `include`.

</details>

**10.** Когда уместен `retry`?

<details><summary>Ответ</summary>

Только для инфраструктурных сбоев (`runner_system_failure`, таймауты),
и только для идемпотентных операций.

</details>

---

### 🎯 Чек-лист

- [ ] Построил DAG через `needs` и замерил ускорение
- [ ] Знаю, что `script` при `extends` заменяется, и умею обойти через `!reference`
- [ ] Убрал копипасту: шаблоны `.job` + `extends`
- [ ] Создал репозиторий шаблонов и подключил его в двух проектах с пином версии
- [ ] Понимаю риск `include` без `ref`
- [ ] Настроил child pipeline для монорепозитория с `rules: changes`
- [ ] Использовал `strategy: depend` и знаю, что будет без него
- [ ] Запускал пайплайн в другом проекте и принимал переменные
- [ ] Применял `parallel`/`matrix` и понимаю, когда это не помогает
- [ ] Ставлю `retry` только для инфраструктурных сбоев
