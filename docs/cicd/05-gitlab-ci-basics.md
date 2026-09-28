---
title: "05. GitLab CI: pipeline, stage, job"
description: "Pipeline, stage, job, .gitlab-ci.yml, предопределённые переменные, отладка пайплайна — конспект и задачи"
---

# 05. GitLab CI: pipeline, stage, job

> Роадмап → 4. CI/CD → Инструменты → GitLab CI → **Минимум**:
> «Понимать что такое `pipeline`, `stage`, `job`. Написать `.gitlab-ci.yml` с парой стейджей
> (build, test, deploy)».
> **После темы ты умеешь:** написать рабочий `.gitlab-ci.yml` с нуля, прочитать лог джобы
> и объяснить, кто, где и в каком порядке выполняет твои команды.

---

## 🗺️ Кто что делает

```text:no-line-numbers
   git push
      │
      ▼
┌──────────────────┐   1. видит .gitlab-ci.yml в корне репозитория
│   GitLab сервер  │   2. создаёт PIPELINE из описанных JOB'ов
└────────┬─────────┘   3. раздаёт джобы свободным раннерам
         │  job
         ▼
┌──────────────────┐   4. раннер клонирует репозиторий в чистое окружение
│  GitLab Runner   │   5. выполняет script построчно в shell
│  (твоя VM / SaaS)│   6. отдаёт лог, статус, артефакты обратно в GitLab
└──────────────────┘
```

**Ключевая мысль:** GitLab CI ничего не выполняет сам — он **оркестратор**.
Команды выполняет раннер, и он же определяет, в каком окружении это происходит
(контейнер с `image:` или shell на сервере). Тема 09 — целиком про раннеры.

---

## 1. Три главных слова

```text:no-line-numbers
PIPELINE (всё, что запускается на один коммит)
│
├── STAGE: build      ← стадии идут ПОСЛЕДОВАТЕЛЬНО
│     ├── JOB: build:backend   ┐
│     └── JOB: build:frontend  ┘ ← джобы одной стадии идут ПАРАЛЛЕЛЬНО
│
├── STAGE: test
│     ├── JOB: unit
│     ├── JOB: lint
│     └── JOB: integration
│
└── STAGE: deploy
      └── JOB: deploy:staging
```

| Термин | Что это | Правила |
|--------|---------|---------|
| **Pipeline** | Весь запуск на конкретный коммит/MR | Красный, если упала любая джоба (кроме `allow_failure`) |
| **Stage** | Группа джоб, этап | Следующая стадия стартует, только когда **вся** предыдущая успешна |
| **Job** | Единица работы: набор команд в `script` | Выполняется на раннере, в своём чистом окружении |

**Важно:** у каждой джобы **своё** окружение и своя файловая система. То, что одна джоба
собрала в `dist/`, вторая **не увидит**, пока ты явно не передашь это через `artifacts`
(тема 06). Общего диска между джобами нет.

---

## 2. Минимальный `.gitlab-ci.yml`

Файл лежит в **корне репозитория**, имя фиксированное.

```yaml
stages:
  - build
  - test
  - deploy

build:
  stage: build
  script:
    - echo "Собираем приложение"
    - mkdir -p dist && echo "artifact" > dist/app.txt

test:
  stage: test
  script:
    - echo "Тестируем"
    - test -n "$CI_COMMIT_SHA"

deploy:
  stage: deploy
  script:
    - echo "Деплоим $CI_COMMIT_SHORT_SHA"
```

Это уже рабочий пайплайн. Коммитим — и в **Build → Pipelines** видим три стадии.

---

## 3. Полноценный пример (Python-приложение)

```yaml
stages: [lint, test, build, deploy]

default:
  image: python:3.12-slim          # окружение по умолчанию для всех джоб
  interruptible: true              # новый пуш отменяет устаревший пайплайн

variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"

lint:
  stage: lint
  before_script:
    - pip install --quiet flake8
  script:
    - flake8 app/ --max-line-length=100

unit:
  stage: test
  before_script:
    - pip install --quiet -r requirements.txt -r requirements-dev.txt
  script:
    - pytest -q --junitxml=report.xml
  artifacts:
    when: always
    reports:
      junit: report.xml            # GitLab покажет тесты во вкладке MR

build:
  stage: build
  image: docker:29
  services:
    - docker:29-dind
  script:
    - docker build -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" .
    - echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
    - docker push "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"

deploy:staging:
  stage: deploy
  image: alpine:3.20
  script:
    - echo "Деплой образа $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA на staging"
  environment:
    name: staging
    url: https://staging.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

> Подробный разбор Docker-джобы — тема 07, `rules` и `artifacts` — тема 06.
> Здесь важно увидеть **скелет**: стадии, джобы, окружение, порядок.

---

## 4. Ключевые слова, которые нужны сразу

| Ключ | Смысл |
|------|-------|
| `stages` | Список стадий и их порядок (глобально) |
| `stage:` | К какой стадии относится джоба (по умолчанию `test`) |
| `script:` | Команды джобы — **обязательный** ключ |
| `before_script` / `after_script` | Выполняется до/после `script` (подготовка/уборка) |
| `image:` | Docker-образ, в котором выполняется джоба (для docker-executor) |
| `services:` | Дополнительные контейнеры рядом (БД, dind) |
| `variables:` | Переменные пайплайна или джобы |
| `tags:` | На каком раннере выполнять (по тегам раннера) |
| `rules:` / `only`/`except` | Когда джоба попадает в пайплайн |
| `artifacts:` | Файлы, передаваемые дальше и доступные для скачивания |
| `cache:` | Кэш зависимостей между запусками |
| `needs:` | Явные зависимости между джобами (DAG) |
| `when:` | `on_success` (по умолчанию), `manual`, `always`, `on_failure`, `delayed` |
| `allow_failure:` | Падение джобы не валит пайплайн |
| `environment:` | Привязка к окружению (dev/staging/prod) |
| `timeout:` | Лимит времени на джобу |
| `retry:` | Число повторов при падении |
| `default:` | Значения по умолчанию для всех джоб |
| `workflow:` | Правила создания пайплайна целиком |

---

## 5. Как выполняется `script`

```yaml
job:
  script:
    - echo "шаг 1"
    - false            # ← ненулевой код возврата
    - echo "шаг 3"     # ← НЕ выполнится, джоба уже упала
```

Правила:
1. Команды выполняются **по одной**, в shell раннера.
2. Ненулевой код возврата любой команды → джоба падает и останавливается.
3. `before_script` + `script` = одна логическая последовательность (падение в
   `before_script` валит джобу). `after_script` выполняется **всегда**, даже после падения,
   в отдельном shell (переменные из `script` там не видны).
4. Каждая джоба стартует с **чистой копии репозитория** (если не отключён `GIT_STRATEGY`).

**Многострочные команды и YAML:**

```yaml
script:
  - |
    if [ -z "$DEPLOY_HOST" ]; then
      echo "DEPLOY_HOST не задан"; exit 1
    fi
  - >
    curl -fsS --retry 3 --max-time 10
    "https://$DEPLOY_HOST/health"
```
`|` сохраняет переводы строк (скрипт), `>` склеивает в одну строку (длинная команда).

> ⚠️ Двоеточие и специальные символы в YAML: `script: - echo "a: b"` без кавычек сломает
> парсер. Правило простое — строки с `:`/`{`/`}`/`#` брать в кавычки.

---

## 6. Статусы джоб и пайплайна

| Статус | Значит |
|--------|--------|
| `created` / `pending` | Ждёт свободного раннера (или зависимостей) |
| `running` | Выполняется |
| `passed` | Успех |
| `failed` | Ненулевой код возврата |
| `canceled` | Отменена (вручную или `interruptible`) |
| `skipped` | Не попала в пайплайн / предыдущая стадия упала |
| `manual` | Ждёт нажатия кнопки |
| `warning` | Упала, но с `allow_failure: true` |

**Пайплайн красный**, если упала хотя бы одна джоба без `allow_failure: true`.

---

## 7. Типы пайплайнов (какие бывают триггеры)

| Тип | Когда | Признак |
|-----|-------|---------|
| **Branch pipeline** | Push в ветку | `$CI_PIPELINE_SOURCE == "push"` |
| **Merge request pipeline** | Создан/обновлён MR | `merge_request_event` |
| **Tag pipeline** | Пуш тега | `$CI_COMMIT_TAG` не пустой |
| **Scheduled** | По расписанию (CI/CD → Schedules) | `schedule` |
| **Manual (web)** | Кнопка Run pipeline | `web` |
| **API / trigger** | Внешний вызов, `trigger` из другого проекта | `pipeline` / `trigger` |
| **Parent/child** | `trigger:` внутри проекта | `parent_pipeline` |

**Двойные пайплайны** — классическая боль новичка: на MR из ветки того же проекта создаётся
и branch-, и MR-пайплайн. Лечится `workflow:rules`:

```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - if: $CI_COMMIT_TAG
    - when: never        # всё остальное — пайплайн не создаётся
```

---

## 8. Предопределённые переменные (топ-15)

```bash
$CI_PROJECT_DIR         # каталог с исходниками на раннере
$CI_PROJECT_NAME        # имя проекта
$CI_COMMIT_SHA          # полный SHA коммита
$CI_COMMIT_SHORT_SHA    # первые 8 символов ← лучший тег для образа
$CI_COMMIT_BRANCH       # имя ветки (пусто для тегов и MR-пайплайнов)
$CI_COMMIT_REF_NAME     # имя ветки ИЛИ тега
$CI_COMMIT_TAG          # имя тега (пусто, если не тег)
$CI_DEFAULT_BRANCH      # ветка по умолчанию (обычно main)
$CI_PIPELINE_ID         # глобальный id пайплайна
$CI_PIPELINE_IID        # номер пайплайна внутри проекта
$CI_PIPELINE_SOURCE     # push / merge_request_event / schedule / web / trigger
$CI_JOB_NAME            # имя джобы
$CI_JOB_TOKEN           # токен для доступа к API/registry этого проекта
$CI_REGISTRY            # адрес GitLab Registry
$CI_REGISTRY_IMAGE      # registry.gitlab.com/group/project
$CI_MERGE_REQUEST_IID   # номер MR (в MR-пайплайне)
$GITLAB_USER_LOGIN      # кто запустил пайплайн
```

Посмотреть все: в джобе выполнить `env | grep ^CI_ | sort`
(⚠️ только на учебном проекте — в лог может попасть лишнее).

---

## 9. Отладка пайплайна

```bash
# 1. Проверить синтаксис ДО коммита:
#    Build → Pipeline editor → вкладка Validate → Simulate pipeline
#    или CLI:
glab ci lint

# 2. Посмотреть, как GitLab «развернул» твой YAML (include, extends, якоря):
#    Pipeline editor → Full configuration

# 3. Локально прогнать джобу (старые версии раннера):
gitlab-runner exec docker build     # ⚠️ устарело/ограничено, но иногда выручает

# 4. Диагностика внутри джобы
script:
  - set -x                      # показывать выполняемые команды
  - pwd && ls -la               # где я и что вокруг
  - env | grep ^CI_ | sort      # переменные (осторожно с секретами!)
  - cat /etc/os-release         # что за образ
  - whoami && id                # под кем работаем
```

**Порядок чтения лога упавшей джобы:**
1. Секция `Preparing environment` — какой раннер, какой образ.
2. `Getting source from Git repository` — клонирование (тут видны проблемы с submodule/LFS).
3. Последние 20 строк перед `ERROR: Job failed` — там причина.
4. Строка `ERROR: Job failed: exit code N` — код возврата.

> Типичная ошибка новичка — читать только последнюю строку `Job failed` и не смотреть,
> какая команда реально вернула ошибку.

---

## 10. Частые ошибки старта

| Симптом | Причина |
|---------|---------|
| `This job is stuck...` | Нет раннера с нужными `tags` или раннер выключен |
| Пайплайн не создался | Нет `.gitlab-ci.yml` в корне / `workflow:rules` отсекли / CI выключен в настройках |
| `yaml invalid` | Ошибка синтаксиса: табы вместо пробелов, двоеточие без кавычек |
| Джоба падает на `docker: not found` | В образе джобы нет докера (нужен `image: docker` + dind) |
| Файл из соседней джобы не найден | Нет `artifacts`/`needs`: у каждой джобы своя ФС |
| `permission denied` на скрипт | Забыли `chmod +x` (и `git update-index --chmod=+x`) |
| Переменная пустая | Protected-переменная, а ветка не защищена |
| Джоба зелёная, хотя тесты упали | В команде есть `|| true` или упавшая команда не последняя в пайпе |

---

## 💼 Как это в DevOps

- `.gitlab-ci.yml` — такой же код, как приложение: его ревьюят, версионируют, рефакторят
  (тема 08: `extends`, `include`).
- 80% вопросов разработчиков: «почему джоба не запустилась» (→ `rules`),
  «почему не видно файл» (→ `artifacts`), «почему медленно» (→ `cache`, `needs`).
- Начинай новый проект не с копипасты чужого ямла, а со скелета: стадии → джобы →
  переменные → правила. Тогда каждый ключ в файле будет объясним.

---

## 📌 Шпаргалка

```yaml
stages: [lint, test, build, deploy]        # порядок стадий

default:                                    # применяется ко всем джобам
  image: python:3.12-slim
  interruptible: true

variables:                                  # переменные пайплайна
  APP_NAME: myapp

job_name:
  stage: test                               # в какую стадию
  image: node:20-alpine                     # переопределение образа
  tags: [docker]                            # на каком раннере
  before_script: [ "npm ci" ]
  script: [ "npm test" ]                    # ОБЯЗАТЕЛЬНО
  after_script: [ "echo done" ]             # выполнится даже при падении
  artifacts:
    paths: [ dist/ ]
    expire_in: 1 week
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
  allow_failure: false
  retry: 1
  timeout: 20m
```

| Хочу | Ключ |
|------|------|
| Задать порядок стадий | `stages` |
| Выполнить команды | `script` |
| Общий образ для всех джоб | `default: image:` |
| Подготовка перед командами | `before_script` |
| Передать файлы дальше | `artifacts: paths:` |
| Ускорить установку зависимостей | `cache` |
| Запускать джобу только на main | `rules: - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH` |
| Кнопка вместо автозапуска | `when: manual` |
| Не валить пайплайн | `allow_failure: true` |
| Не ждать всю стадию | `needs: [job]` |
| Отменять устаревшие пайплайны | `interruptible: true` |

---

## 🧠 Что запомнить

1. GitLab — оркестратор, команды выполняет **раннер**; окружение задаёт `image`/executor.
2. Pipeline → stages (последовательно) → jobs (параллельно внутри стадии).
3. У каждой джобы **своя чистая ФС**: передача файлов только через `artifacts`.
4. `script` — обязательный ключ; ненулевой код любой команды валит джобу.
5. `after_script` выполняется всегда и в отдельном shell.
6. Файл всегда называется `.gitlab-ci.yml` и лежит в корне (путь можно переопределить в настройках).
7. `default:` и `variables:` убирают копипасту уже на старте.
8. `workflow:rules` — лекарство от дублирующихся пайплайнов на MR.
9. Предопределённые переменные (`$CI_COMMIT_SHORT_SHA`, `$CI_REGISTRY_IMAGE`) — основа
   тегирования и деплоя.
10. Проверяй YAML в Pipeline editor (Validate + Full configuration) до коммита.
11. `This job is stuck` — почти всегда несовпадение `tags` джобы и раннера.
12. Лог джобы читается сверху вниз по секциям, а не с последней строки.

---

## Задачи

> Лаба: проект на gitlab.com (можно приватный). Всё проверяется в **Build → Pipelines**.
> Синтаксис проверяй в **Build → Pipeline editor → Validate** до коммита.

---

### Блок A. Теория

**A1.** Что такое pipeline, stage и job? Что выполняется последовательно, а что параллельно?

<details><summary>Ответ</summary>

Pipeline — весь набор джоб, запускаемый на событие (push, MR, тег, расписание).
Stage — этап; стадии выполняются последовательно, следующая начинается только после успеха
всей предыдущей. Job — конкретная задача со своим `script`; джобы одной стадии выполняются
параллельно (в пределах доступных раннеров).

</details>

**A2.** Кто фактически выполняет команды из `script` — GitLab или раннер? Что определяет
окружение выполнения?

<details><summary>Ответ</summary>

Команды выполняет **раннер**. Окружение определяется executor'ом раннера: для
docker-executor — образ из `image:`, для shell-executor — окружение самой машины,
для kubernetes-executor — под с контейнерами.

</details>

**A3.** Джоба `build` создала каталог `dist/`. Увидит ли его джоба `test` из следующей стадии?
Почему?

<details><summary>Ответ</summary>

Нет. У каждой джобы своё чистое рабочее пространство (и, как правило, другой
контейнер). Передача файлов возможна только через `artifacts` (или внешнее хранилище/registry).

</details>

**A4.** Что произойдёт с джобой, если третья команда в `script` вернёт код 1,
а после неё есть ещё две команды?

<details><summary>Ответ</summary>

Джоба немедленно падает на третьей команде; четвёртая и пятая не выполняются;
статус `failed`, exit code попадает в лог.

</details>

**A5.** Чем `before_script` отличается от `after_script`? Когда выполняется каждый
и что происходит при падении?

<details><summary>Ответ</summary>

`before_script` выполняется перед `script` в том же shell — фактически это его
начало, и падение здесь валит джобу, `script` не выполняется. `after_script` выполняется
**всегда** (успех, падение, отмена по таймауту), в отдельном shell: переменные и рабочие
каталоги из `script` там не сохраняются.

</details>

**A6.** Где должен лежать `.gitlab-ci.yml` и можно ли это изменить?

<details><summary>Ответ</summary>

В корне репозитория, имя `.gitlab-ci.yml`. Путь можно изменить: Settings → CI/CD →
General pipelines → CI/CD configuration file (в том числе указать файл в другом репозитории).

</details>

**A7.** Что делает блок `default:`? Приведи три ключа, которые туда обычно кладут.

<details><summary>Ответ</summary>

Значения по умолчанию для всех джоб: чаще всего `image`, `before_script`, `tags`,
`retry`, `timeout`, `interruptible`, `artifacts`, `cache`. Джоба может их переопределить.

</details>

**A8.** Какая стадия у джобы, если `stage:` не указан?

<details><summary>Ответ</summary>

`test` — стадия по умолчанию.

</details>

**A9.** Перечисли статусы джобы и объясни `skipped`, `manual` и `warning`.

<details><summary>Ответ</summary>

`created`, `pending` (ждёт раннера), `running`, `passed`, `failed`, `canceled`,
`skipped`, `manual`. `skipped` — джоба не выполнялась (не прошла по `rules` или предыдущая
стадия упала); `manual` — ждёт нажатия кнопки; `warning` (жёлтый) — джоба упала,
но с `allow_failure: true`, пайплайн при этом не красный.

</details>

**A10.** Когда пайплайн считается красным? Как сделать так, чтобы падение конкретной
джобы не валило пайплайн?

<details><summary>Ответ</summary>

Красный — если упала хотя бы одна джоба без `allow_failure: true`. Чтобы падение
не валило пайплайн — `allow_failure: true` (джоба будет жёлтой).

</details>

**A11.** Какие типы пайплайнов бывают? Как отличить их в `rules` (переменная и значения)?

<details><summary>Ответ</summary>

Branch (`push`), merge request (`merge_request_event`), tag (push тега,
`$CI_COMMIT_TAG` не пуст), scheduled (`schedule`), web (`web`), API/trigger (`trigger`,
`pipeline`), parent-child (`parent_pipeline`). Определяются через `$CI_PIPELINE_SOURCE`.

</details>

**A12.** Почему на MR иногда создаётся два пайплайна и как это чинится?

<details><summary>Ответ</summary>

Потому что для ветки создаётся branch-пайплайн, а для открытого MR — ещё и
MR-пайплайн. Лечится `workflow:rules` (разрешить MR-пайплайны, ветку `main`, теги,
остальное — `when: never`) либо правилами вида «не создавать branch-пайплайн, если открыт MR».

</details>

**A13.** Назови 10 предопределённых переменных и скажи, для чего каждая нужна.

<details><summary>Ответ</summary>

`$CI_COMMIT_SHA`/`$CI_COMMIT_SHORT_SHA` — идентификация коммита и тег образа;
`$CI_COMMIT_BRANCH` — ветка для правил; `$CI_DEFAULT_BRANCH` — не хардкодить `main`;
`$CI_COMMIT_TAG` — релизные пайплайны; `$CI_PIPELINE_SOURCE` — тип запуска;
`$CI_PROJECT_DIR` — путь к исходникам; `$CI_REGISTRY`, `$CI_REGISTRY_IMAGE`,
`$CI_REGISTRY_USER`, `$CI_REGISTRY_PASSWORD` — работа с registry; `$CI_JOB_TOKEN` — доступ
к API/зависимым проектам; `$CI_PIPELINE_IID`/`$CI_JOB_ID` — нумерация и ссылки;
`$GITLAB_USER_LOGIN` — кто запустил (полезно в логах деплоя).

</details>

**A14.** Чем `$CI_COMMIT_BRANCH` отличается от `$CI_COMMIT_REF_NAME`?

<details><summary>Ответ</summary>

`$CI_COMMIT_BRANCH` заполнена только в branch-пайплайне (пуста для тегов и
MR-пайплайнов); `$CI_COMMIT_REF_NAME` содержит имя ветки **или** тега — она заполнена почти
всегда, поэтому подходит для тегирования артефактов, но плохо подходит для точных правил.

</details>

**A15.** Что означает `This job is stuck because the project doesn't have any runners online`?

<details><summary>Ответ</summary>

Нет доступного раннера, который может взять эту джобу: раннер не подключён,
выключен, занят, либо `tags` джобы не совпадают с тегами раннера (а раннер не принимает
джобы без тегов).

</details>

**A16.** Что делает `interruptible: true`?

<details><summary>Ответ</summary>

Помечает джобу как прерываемую: при появлении нового пайплайна на той же ветке
(при включённой авто-отмене избыточных пайплайнов) старый пайплайн отменяется — экономит
минуты раннеров.

</details>

**A17.** Как посмотреть итоговую конфигурацию пайплайна после раскрытия `include`/`extends`?

<details><summary>Ответ</summary>

Build → Pipeline editor → вкладка **Full configuration** (раскрытые `include`,
`extends`, якоря). Также доступно через API `ci/lint`/`ci/config`.

</details>

**A18.** Почему `script: - echo "status: ok"` может сломать YAML, а `- echo 'status ok'` — нет?

<details><summary>Ответ</summary>

В YAML `:` + пробел — разделитель ключа и значения, поэтому неэкранированная строка
`echo "status: ok"` может трактоваться как отображение (map) и вызвать ошибку парсинга.
Решение — кавычки вокруг всей команды или использование блочных скаляров `|`/`>`.

</details>

---

### Блок B. «Что сделает этот конфиг»

```yaml
# B1
stages: [test, build]
build:
  stage: build
  script: ["echo build"]
test:
  stage: test
  script: ["echo test"]
```
Вопрос: в каком порядке выполнятся джобы и почему?

<details><summary>Ответ</summary>

Сначала `test`, потом `build`: порядок задаёт список `stages` (test указан первым),
а не порядок описания джоб в файле.

</details>

```yaml
# B2
job:
  script:
    - cd /tmp
    - echo "hi" > file.txt
  after_script:
    - cat file.txt
```
Вопрос: что выведет `after_script`?

<details><summary>Ответ</summary>

Скорее всего ошибка `cat: file.txt: No such file or directory`: `after_script`
выполняется в отдельном shell и стартует из рабочего каталога проекта, а не из `/tmp`.

</details>

```yaml
# B3
job:
  before_script: ["exit 1"]
  script: ["echo main"]
  after_script: ["echo cleanup"]
```

<details><summary>Ответ</summary>

Джоба упадёт сразу (падение в `before_script` = падение джобы), `echo main`
не выполнится, а `echo cleanup` выполнится — `after_script` отрабатывает всегда.

</details>

```yaml
# B4
lint:
  stage: test
  script: ["flake8 ."]
  allow_failure: true
unit:
  stage: test
  script: ["pytest"]
deploy:
  stage: deploy
  script: ["echo deploy"]
```
Вопрос: если `flake8` упал, а `pytest` прошёл — задеплоится ли?

<details><summary>Ответ</summary>

Да, задеплоится: `lint` с `allow_failure: true` даёт жёлтый статус, но не блокирует
переход к следующей стадии. Это и есть смысл «предупреждающих» джоб.

</details>

```yaml
# B5
job:
  script:
    - pytest || true
```

<details><summary>Ответ</summary>

Джоба всегда зелёная независимо от результата тестов: `|| true` подменяет код возврата.
Тесты превращаются в декорацию.

</details>

```yaml
# B6
job:
  script: ["make build"]
  tags: [heavy-runner]
```
Вопрос: что будет, если раннера с таким тегом нет?

<details><summary>Ответ</summary>

Джоба будет висеть в `pending`, а затем упадёт по таймауту с сообщением о том,
что нет подходящего раннера (`stuck`).

</details>

```yaml
# B7
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
    - when: never
```
Вопрос: запустится ли пайплайн на push в ветку `feature/x`?

<details><summary>Ответ</summary>

Нет: push в `feature/x` без открытого MR не подпадает ни под одно правило,
последнее `when: never` запрещает создание пайплайна.

</details>

```yaml
# B8
variables:
  GREETING: "hello"
job:
  variables:
    GREETING: "hi"
  script: ["echo $GREETING"]
```

<details><summary>Ответ</summary>

Выведет `hi`: переменная уровня джобы переопределяет одноимённую переменную
уровня пайплайна.

</details>

---

### Блок C. Практика

#### C1. 🔑 Первый пайплайн (задание «Минимум» из роадмапа)

1. Создай проект на gitlab.com и положи в него приложение из блока Docker.
2. Напиши `.gitlab-ci.yml` с тремя стадиями:
   - `build` — выводит сообщение и создаёт файл `dist/build-info.txt` с датой и `$CI_COMMIT_SHORT_SHA`;
   - `test` — проверяет, что файл существует (и падает, если нет);
   - `deploy` — выводит «деплой версии `$CI_COMMIT_SHORT_SHA`».
3. Убедись, что `test` **не видит** файл без `artifacts`. Затем добавь `artifacts` и убедись,
   что увидел.
4. Приложи в конспект вывод: сколько шла каждая джоба.

<details><summary>Ответ</summary>

Без `artifacts` джоба `test` падает — это и есть главный вывод задания.
Минимальное исправление:
```yaml
build:
  stage: build
  script:
    - mkdir -p dist
    - echo "$(date -Iseconds) $CI_COMMIT_SHORT_SHA" > dist/build-info.txt
  artifacts:
    paths: [dist/]
    expire_in: 1 day
test:
  stage: test
  script:
    - test -s dist/build-info.txt
    - cat dist/build-info.txt
```

</details>

#### C2. Параллельность стадий
Добавь в стадию `test` три джобы (`lint`, `unit`, `integration`) и посмотри в UI,
что они выполняются одновременно. Замерь общее время стадии и сравни с суммой времён джоб.

<details><summary>Ответ</summary>

Время стадии ≈ время самой длинной джобы (если раннеров хватает), а не сумма.
Если раннер один и `concurrent = 1`, джобы выстроятся в очередь — это хороший повод
заглянуть в тему 09.

</details>

#### C3. Свой образ джобы
Сделай так, чтобы `lint` выполнялся в `python:3.12-slim`, а `unit` — в `python:3.11-slim`.
Проверь версию в каждой джобе командой `python --version`.
Вынеси общий образ в `default:` и оставь переопределение только там, где нужно.

<details><summary>Ответ</summary>

Проверка — разные версии в выводе `python --version`. После выноса в `default:`
файл становится короче, а переопределение остаётся только в исключениях.

</details>

#### C4. Падение и диагностика
Намеренно сломай джобу тремя способами и зафиксируй сообщение об ошибке:
1. опечатка в имени команды;
2. ошибка синтаксиса YAML (таб вместо пробелов);
3. `tags: [no-such-runner]`.

<details><summary>Ответ</summary>

Ожидаемые сообщения: `bash: line N: flake9: command not found` (код 127);
ошибка валидации YAML в UI (пайплайн не создаётся); `stuck` из-за несуществующего тега раннера.

</details>

#### C5. Исследование окружения
Добавь временную джобу `debug`, которая выводит: `pwd`, `ls -la`, `whoami`, `id`,
`cat /etc/os-release`, `df -h`, `env | grep ^CI_ | sort | head -30`.
Разбери вывод: под каким пользователем работаешь, что за ОС, где лежит код.
⚠️ После разбора джобу удали (не оставляй дамп переменных в логах).

<details><summary>Ответ</summary>

В docker-executor чаще всего `root` внутри контейнера, рабочий каталог —
`/builds/<group>/<project>`. Полезно заметить, что «root в контейнере» ≠ «root на хосте».

</details>

#### C6. Типы пайплайнов
Добавь джобу `whoami:pipeline`, которая печатает `$CI_PIPELINE_SOURCE`, `$CI_COMMIT_BRANCH`,
`$CI_COMMIT_TAG`, `$CI_MERGE_REQUEST_IID`. Запусти её:
- пушем в ветку;
- созданием MR;
- пушем тега `v0.1.0`;
- кнопкой Run pipeline;
- по расписанию (CI/CD → Schedules, раз в час).
Заполни таблицу: какой источник и какие переменные заполнены в каждом случае.

<details><summary>Ответ</summary>

Ожидаемое: push → `push`, заполнены `CI_COMMIT_BRANCH`; MR → `merge_request_event`,
заполнен `CI_MERGE_REQUEST_IID`, `CI_COMMIT_BRANCH` пуста; тег → `push` с заполненным
`CI_COMMIT_TAG`; кнопка → `web`; расписание → `schedule`.

</details>

#### C7. Убери двойные пайплайны
Настрой `workflow:rules` так, чтобы пайплайн создавался только для MR, для `main` и для тегов.
Проверь, что при пуше в фича-ветку без MR пайплайн не создаётся.

<details><summary>Ответ</summary>

Проверяется просто: пуш в фича-ветку не создаёт пайплайн, открытие MR — создаёт один.

</details>

#### C8. Ручная джоба
Добавь `deploy:prod` с `when: manual` и убедись, что пайплайн остаётся зелёным,
пока кнопка не нажата. Затем добавь `allow_failure: false` и объясни, что изменилось
в статусе пайплайна (подсказка: блокирующая ручная джоба).

<details><summary>Ответ</summary>

По умолчанию ручная джоба **не блокирует** пайплайн: он получает статус
`passed` (или `blocked`/`manual` в зависимости от настроек). С `allow_failure: false`
ручная джоба становится блокирующей: пайплайн ждёт решения и не считается успешным,
пока кнопка не нажата.

</details>

---

### Блок D. Инциденты

**D1.** Пайплайн вообще не запускается после пуша. Перечисли шесть причин по порядку проверки.

<details><summary>Ответ</summary>

(1) Нет `.gitlab-ci.yml` в корне или изменён путь в настройках; (2) ошибка
синтаксиса — смотри Pipeline editor; (3) `workflow:rules`/`rules` отсекли все джобы;
(4) CI/CD отключён в Settings → General → Visibility; (5) пуш прошёл не в тот репозиторий/
ветку; (6) закончились CI-минуты или проект заблокирован; (7) пайплайн создался, но все
джобы `skipped`.

</details>

**D2.** Джоба висит в `pending` полчаса. Что смотреть?

<details><summary>Ответ</summary>

Есть ли активные раннеры у проекта (Settings → CI/CD → Runners), совпадают ли `tags`,
принимает ли раннер untagged-джобы, не занят ли он (`concurrent`), не закончились ли
общие CI-минуты, не ждёт ли джоба `needs`/ручного шага, не выключен ли раннер по расписанию.

</details>

**D3.** Джоба падает с `bash: line 42: ./deploy.sh: Permission denied`. Как чинить,
чтобы это не повторялось у всех?

<details><summary>Ответ</summary>

Дать файлу флаг исполнения **в git**: `chmod +x deploy.sh && git update-index
--chmod=+x deploy.sh` — тогда флаг сохранится в репозитории. Альтернатива: вызывать
`bash deploy.sh` в `script`.

</details>

**D4.** Джоба `test` падает с `no such file or directory: dist/app.js`, хотя джоба `build`
зелёная. Причина и решение.

<details><summary>Ответ</summary>

Файл не передан между джобами: нужно `artifacts: paths: [dist/]` в `build`
(и `needs`/зависимость по стадиям в `test`). Также проверь, что путь относительный и
не попал в `.gitignore` (игнорируемые файлы не попадают в артефакты по умолчанию).

</details>

**D5.** Разработчик говорит: «у меня локально тесты проходят, в CI падают». Три класса причин
и как локализовать.

<details><summary>Ответ</summary>

(1) Разница окружения: версии рантайма и системных пакетов, локаль, таймзона;
(2) состояние: локально остались файлы/БД/кэш, в CI чистая ФС; (3) переменные и секреты:
локально в `.env`, в CI не заданы. Локализация — запустить локально тот же образ
(`docker run --rm -it python:3.12-slim bash`) и повторить шаги джобы.

</details>

**D6.** Джоба зелёная, но по логам видно, что тесты упали. Где искать проблему в конфиге?

<details><summary>Ответ</summary>

Ищи `|| true`, `set +e`, `exit 0` в конце, тестовый раннер с `allow_failure: true`,
а также конвейеры вида `pytest | tee log` — код возврата берётся от последней команды пайпа
(лечится `set -o pipefail`).

</details>

**D7.** После добавления `image: docker` джоба падает на `Cannot connect to the Docker daemon`.
Что забыли?

<details><summary>Ответ</summary>

Не подключён сервис Docker-in-Docker (`services: [docker:29-dind]`) и переменные
`DOCKER_HOST`/`DOCKER_TLS_CERTDIR`, либо раннер не поддерживает privileged.
Подробности — тема 07.

</details>

**D8.** В логе джобы видно содержимое приватного ключа. Что произошло и как предотвратить?

<details><summary>Ответ</summary>

Ключ был выведен в лог (например, `echo "$SSH_PRIVATE_KEY"` или `set -x` рядом
с подстановкой переменной). Немедленно: ротация ключа, удаление лога джобы.
Предотвращение: masked-переменные, тип File, не использовать `set -x` рядом с секретами,
перенаправлять вывод чувствительных команд в `/dev/null`.

</details>

**D9.** Пайплайн на main зелёный, а тот же коммит в MR — красный. Как такое возможно?

<details><summary>Ответ</summary>

Различаются наборы джоб и переменные: в MR-пайплайне выполняются джобы с правилами
на `merge_request_event`, доступны другие переменные, protected-переменные из фича-ветки
недоступны; плюс в MR-пайплайне может собираться merged-результат (слияние с `main`),
то есть тестируется другой код.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое pipeline, stage, job в GitLab CI?

<details><summary>Ответ</summary>

Pipeline — весь запуск на событие; stage — этап; job — задача со скриптом.

</details>

**2.** Что выполняется параллельно, а что последовательно?

<details><summary>Ответ</summary>

Стадии — последовательно, джобы внутри стадии — параллельно (можно изменить через `needs`).

</details>

**3.** Как передать файлы между джобами?

<details><summary>Ответ</summary>

Через `artifacts` (и `needs` для явной зависимости); общей ФС между джобами нет.

</details>

**4.** Где выполняется `script` и как задать окружение?

<details><summary>Ответ</summary>

На раннере; окружение задаётся executor'ом и `image`/`services`.

</details>

**5.** Чем `before_script` отличается от `after_script`?

<details><summary>Ответ</summary>

`before_script` — часть `script` (падение валит джобу), `after_script` — всегда,
в отдельном shell.

</details>

**6.** Как сделать так, чтобы джоба не валила пайплайн?

<details><summary>Ответ</summary>

`allow_failure: true` (джоба станет жёлтой, пайплайн — нет).

</details>

**7.** Какие типы пайплайнов бывают?

<details><summary>Ответ</summary>

Branch, merge request, tag, scheduled, web, API/trigger, parent-child.

</details>

**8.** Как избавиться от дублирующихся пайплайнов на MR?

<details><summary>Ответ</summary>

`workflow:rules`: разрешить MR-пайплайны, ветку по умолчанию и теги, остальное — `never`.

</details>

**9.** Назови предопределённые переменные, которыми пользуешься чаще всего.

<details><summary>Ответ</summary>

`CI_COMMIT_SHORT_SHA`, `CI_COMMIT_BRANCH`, `CI_DEFAULT_BRANCH`, `CI_PIPELINE_SOURCE`,
`CI_REGISTRY_IMAGE`, `CI_JOB_TOKEN`, `CI_COMMIT_TAG`, `CI_PROJECT_DIR`.

</details>

**10.** Джоба стоит в pending — что проверишь?

<details><summary>Ответ</summary>

Наличие и статус раннеров, совпадение тегов, untagged-настройку, загрузку раннера,
лимиты минут, зависимости `needs`.

</details>

---

### 🎯 Чек-лист

- [ ] Написал рабочий `.gitlab-ci.yml` с тремя стадиями с нуля
- [ ] Понимаю, что стадии последовательны, а джобы внутри стадии параллельны
- [ ] Убедился на практике, что файлы между джобами не передаются без `artifacts`
- [ ] Знаю разницу `before_script` / `script` / `after_script`
- [ ] Умею читать лог упавшей джобы по секциям
- [ ] Различаю типы пайплайнов и знаю `$CI_PIPELINE_SOURCE`
- [ ] Убрал дублирующиеся пайплайны через `workflow:rules`
- [ ] Помню 10+ предопределённых переменных
- [ ] Знаю, почему джоба висит в pending, и что проверять
- [ ] Проверяю конфиг в Pipeline editor до коммита
