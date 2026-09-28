---
title: "12. Jenkins: Groovy, Shared Libraries, Multibranch"
description: "Scripted pipeline, параллельные стадии, when/input, Shared Libraries, Multibranch Pipeline, docker/k8s-агенты"
---

# 12. Jenkins: Groovy, Shared Libraries, Multibranch

> Роадмап → 4. CI/CD → Инструменты → Jenkins → **Хорошо**:
> скриптовые пайплайны на Groovy, `Shared Libraries`, параллельные стейджи,
> `when`, `input`, `Multibranch` пайплайн, агент на Docker.
> **После темы ты умеешь:** убрать дублирование через общую библиотеку, ускорить сборку
> параллельными стадиями и автоматически заводить пайплайн на каждую ветку.

---

## 1. Scripted pipeline — когда декларативного мало

```groovy
// Скриптовый: чистый Groovy, максимум свободы
node('linux') {
    def image
    try {
        stage('Checkout') {
            checkout scm
        }
        stage('Build') {
            image = docker.build("myapp:${env.BUILD_NUMBER}")
        }
        stage('Test') {
            // произвольная логика: циклы, условия, работа с данными
            ['unit', 'integration', 'contract'].each { suite ->
                sh "pytest tests/${suite}"
            }
        }
        stage('Push') {
            docker.withRegistry('https://registry.example.com', 'registry-creds') {
                image.push()
                image.push('latest')
            }
        }
    } catch (err) {
        currentBuild.result = 'FAILURE'
        throw err
    } finally {
        cleanWs()
    }
}
```

| | Declarative | Scripted |
|---|---|---|
| Синтаксис | Структурированный DSL | Чистый Groovy (`node { }`) |
| Валидация | Есть (до запуска) | Почти нет |
| Читаемость | Высокая | Зависит от автора |
| Гибкость | Ограниченная (спасает `script { }`) | Максимальная |
| Рекомендация | ⭐ Дефолт | Только там, где действительно нужна логика |

**Практика:** пишем декларативный пайплайн, а сложные куски заворачиваем в `script { }`
или выносим в shared library. Полностью скриптовые пайплайны сегодня — редкость и легаси.

---

## 2. Параллельные стадии

```groovy
pipeline {
    agent none
    stages {
        stage('Quality') {
            parallel {
                stage('Unit') {
                    agent { docker { image 'python:3.12-slim' } }
                    steps { sh 'pytest tests/unit --junitxml=unit.xml' }
                    post { always { junit 'unit.xml' } }
                }
                stage('Lint') {
                    agent { docker { image 'python:3.12-slim' } }
                    steps { sh 'flake8 app/' }
                }
                stage('Security') {
                    agent { label 'docker' }
                    steps { sh 'trivy fs --severity CRITICAL --exit-code 1 .' }
                }
            }
        }
    }
}
```

```groovy
// динамическая параллель (скриптово — внутри script {})
script {
    def branches = [:]
    ['3.11', '3.12', '3.13'].each { ver ->
        branches["python-${ver}"] = {
            docker.image("python:${ver}-slim").inside {
                sh 'pip install -q -r requirements.txt && pytest -q'
            }
        }
    }
    branches.failFast = true      // упал один — останавливаем остальные
    parallel branches
}
```

| Ключ | Смысл |
|------|-------|
| `parallel { }` | Стадии выполняются одновременно (нужны свободные executors!) |
| `failFast true` | Падение одной ветки останавливает остальные |
| `agent` внутри | У каждой параллельной стадии может быть свой агент |

> Параллель ускоряет только при наличии свободных executors. Если агент один
> с одним слотом — стадии выстроятся в очередь.

---

## 3. `when` — условное выполнение стадий

```groovy
stage('Deploy prod') {
    when {
        allOf {
            branch 'main'
            expression { params.ENVIRONMENT == 'prod' }
            not { changeRequest() }
        }
        beforeAgent true            // ⭐ не занимать агента, если условие ложно
    }
    steps { sh './deploy.sh prod' }
}
```

| Условие | Смысл |
|---------|-------|
| `branch 'main'` | Имя ветки (multibranch); поддерживает шаблоны `'release/*'` |
| `buildingTag()` / `tag 'v*'` | Сборка по тегу |
| `changeRequest()` | Это PR/MR (можно уточнять `target: 'main'`) |
| `environment name: 'DEPLOY', value: 'true'` | По переменной окружения |
| `expression { ... }` | Произвольное Groovy-выражение |
| `changeset '**/backend/**'` | Изменились указанные пути (аналог `rules:changes`) |
| `equals expected: 2, actual: currentBuild.number` | Сравнение |
| `anyOf` / `allOf` / `not` | Комбинирование |
| `beforeAgent true` | Проверить условие **до** выделения агента |
| `beforeInput true`, `beforeOptions true` | Проверить до `input`/`options` |

---

## 4. `input` — ручное подтверждение

```groovy
stage('Approve') {
    options { timeout(time: 4, unit: 'HOURS') }
    input {
        message "Выкатываем ${env.IMAGE_TAG} в PROD?"
        ok "Деплой"
        submitter "release-managers,team-lead"        // кто может подтвердить
        parameters {
            choice(name: 'STRATEGY', choices: ['rolling', 'canary'], description: '')
        }
    }
    steps {
        echo "Стратегия: ${STRATEGY}"
        sh "./deploy.sh prod ${STRATEGY}"
    }
}
```

Особенности:
- `input` **блокирует** пайплайн до решения — держи стадию под `agent none`/отдельным агентом;
- всегда ставь таймаут: иначе сборка висит неделями и занимает ресурсы;
- `submitter` ограничивает круг подтверждающих (аналог Protected environments в GitLab);
- результат (`submitter`, выбранные параметры) можно сохранить: `def approval = input(...)`.

---

## 5. Shared Libraries — главный инструмент против копипасты

Аналог `include` + шаблонов в GitLab CI: общий код пайплайнов в отдельном git-репозитории.

### Структура репозитория библиотеки

```text:no-line-numbers
jenkins-shared-library/
├── vars/                       # глобальные функции: имя файла = имя шага
│   ├── buildDockerImage.groovy
│   ├── deployToEnv.groovy
│   └── standardPipeline.groovy # целый пайплайн одной строкой
├── src/                        # классы Groovy (org/example/...)
│   └── org/example/Notifier.groovy
└── resources/                  # статические файлы (шаблоны, конфиги)
    └── org/example/slack.json
```

### Подключение
Manage Jenkins → System → Global Pipeline Libraries: имя, репозиторий, версия по умолчанию
(ветка/тег), «Load implicitly» при необходимости.

```groovy
@Library('devops-lib@v1.4.0') _        // ⭐ пин версии, как ref в include
// или несколько: @Library(['devops-lib@v1.4.0', 'security-lib@main']) _
```

### Простой шаг в `vars/`
```groovy
// vars/buildDockerImage.groovy
def call(Map config = [:]) {
    def registry = config.registry ?: 'registry.example.com'
    def name     = config.name     ?: error('name обязателен')
    def tag      = config.tag      ?: env.GIT_COMMIT.take(8)

    withCredentials([usernamePassword(credentialsId: config.creds ?: 'registry-creds',
                                      usernameVariable: 'REG_USER',
                                      passwordVariable: 'REG_PASS')]) {
        sh """
            echo "\$REG_PASS" | docker login -u "\$REG_USER" --password-stdin ${registry}
            docker build -t ${registry}/${name}:${tag} .
            docker push ${registry}/${name}:${tag}
        """
    }
    return "${registry}/${name}:${tag}"
}
```

```groovy
// использование в Jenkinsfile
@Library('devops-lib@v1.4.0') _
pipeline {
    agent { label 'docker' }
    stages {
        stage('Build') {
            steps {
                script { env.IMAGE = buildDockerImage(name: 'myapp') }
            }
        }
    }
}
```

### Целый пайплайн в библиотеке
```groovy
// vars/standardPipeline.groovy
def call(Map cfg) {
    pipeline {
        agent { label cfg.agentLabel ?: 'docker' }
        options { timeout(time: 40, unit: 'MINUTES'); buildDiscarder(logRotator(numToKeepStr: '20')) }
        stages {
            stage('Test')   { steps { sh cfg.testCmd ?: 'make test' } }
            stage('Build')  { steps { script { env.IMAGE = buildDockerImage(name: cfg.appName) } } }
            stage('Deploy') {
                when { branch 'main' }
                steps { deployToEnv(env: 'staging', image: env.IMAGE) }
            }
        }
        post { always { cleanWs() } }
    }
}
```
```groovy
// Jenkinsfile проекта — три строки
@Library('devops-lib@v1.4.0') _
standardPipeline(appName: 'billing', testCmd: 'pytest -q')
```

### Класс в `src/`
```groovy
// src/org/example/Notifier.groovy
package org.example

class Notifier implements Serializable {
    def steps
    Notifier(steps) { this.steps = steps }

    void failure(String job, String url) {
        steps.echo "❌ ${job} упал: ${url}"
        // steps.sh "curl -X POST ..."
    }
}
```

**Правила эксплуатации библиотек:**
1. Всегда **пинить версию** (`@v1.4.0`): иначе коммит в библиотеку ломает все пайплайны.
2. Версионировать по SemVer, вести changelog, тестировать на канареечном проекте.
3. `vars/` — шаги (camelCase, имя файла = имя шага), `src/` — классы, `resources/` — файлы.
4. Классы должны быть `Serializable` (пайплайн сериализуется между шагами).
5. Не злоупотреблять: библиотека, которую никто не понимает, хуже копипасты.

---

## 6. Multibranch Pipeline

Тип джобы, который **сам сканирует репозиторий** и создаёт пайплайн для каждой ветки
и каждого PR/MR, где есть `Jenkinsfile`.

```text:no-line-numbers
Multibranch job "myapp"
├── main          ← Jenkinsfile из main
├── develop
├── feature/login
└── PR-42         ← пайплайн для merge request
```

Настройка: New Item → Multibranch Pipeline → Branch Sources (Git/GitLab/GitHub) →
Behaviours (какие ветки/PR обнаруживать) → Scan triggers (по вебхуку или периодически) →
Orphaned Item Strategy (удалять пайплайны удалённых веток).

В `Jenkinsfile` появляются переменные:
```groovy
env.BRANCH_NAME      // feature/login или PR-42
env.CHANGE_ID        // номер PR/MR (только для PR)
env.CHANGE_TARGET    // целевая ветка PR
env.CHANGE_BRANCH    // исходная ветка PR
env.CHANGE_AUTHOR
```

```groovy
stage('Deploy dev') {
    when { not { anyOf { branch 'main'; changeRequest() } } }
    steps { sh "./deploy.sh dev-${env.BRANCH_NAME.replaceAll('[^a-zA-Z0-9]', '-')}" }
}
```

**Organization Folder** идёт дальше: сканирует все репозитории группы/организации
и заводит multibranch-джобу каждому проекту, где есть `Jenkinsfile`.

---

## 7. Docker-агенты: каждая сборка в чистом контейнере

```groovy
pipeline {
    agent none
    stages {
        stage('Test') {
            agent {
                docker {
                    image 'python:3.12-slim'
                    args '-v $HOME/.cache/pip:/root/.cache/pip -u root:root'
                    label 'docker'
                    reuseNode true
                }
            }
            steps { sh 'pip install -r requirements.txt && pytest -q' }
        }
        stage('Build image') {
            agent { label 'docker' }
            steps {
                script {
                    def img = docker.build("registry.example.com/myapp:${env.GIT_COMMIT.take(8)}")
                    docker.withRegistry('https://registry.example.com', 'registry-creds') {
                        img.push()
                    }
                }
            }
        }
    }
}
```

```groovy
// Kubernetes-агент: под на сборку (плагин kubernetes)
agent {
    kubernetes {
        yaml '''
            apiVersion: v1
            kind: Pod
            spec:
              containers:
              - name: python
                image: python:3.12-slim
                command: ["sleep"]
                args: ["infinity"]
              - name: buildah
                image: quay.io/buildah/stable:v1.43.4
                command: ["sleep"]
                args: ["infinity"]
                env:
                - name: STORAGE_DRIVER        # без overlay-маунтов → без privileged
                  value: vfs
                - name: BUILDAH_FORMAT
                  value: docker
        '''
    }
}
steps {
    container('python') { sh 'pytest -q' }
    container('buildah') {
        withCredentials([usernamePassword(credentialsId: 'registry-creds',
                                          usernameVariable: 'REG_USER', passwordVariable: 'REG_PASS')]) {
            sh '''
                echo "$REG_PASS" | buildah login -u "$REG_USER" --password-stdin registry.example.com
                buildah build -t registry.example.com/app:$GIT_COMMIT .
                buildah push registry.example.com/app:$GIT_COMMIT
            '''
        }
    }
}
```

> Раньше в такой под ставили kaniko (`gcr.io/kaniko-project/executor`), но upstream заархивирован
> в 2025 и больше не обновляется. Для новых агентов — buildah (как выше) или rootless BuildKit
> (`moby/buildkit:rootless` + `buildctl-daemonless.sh`); в закрученном кластере им может понадобиться
> seccomp/AppArmor `Unconfined`. Подробности и сравнение — [09. Docker в GitLab CI](/cicd/07-gitlab-ci-docker).

Docker/k8s-агенты решают три классические проблемы Jenkins: грязный workspace,
«на агенте нет нужной версии Python» и конфликты версий инструментов между проектами.

---

## 8. Чем это соответствует GitLab CI

| Jenkins | GitLab CI |
|---------|-----------|
| Shared Library (`@Library`) | `include:` + `extends` |
| `vars/step.groovy` | шаблон-джоба `.template` |
| `parallel { }` | джобы одной стадии / `parallel` |
| `when { branch 'main' }` | `rules: - if: $CI_COMMIT_BRANCH == "main"` |
| `when { changeset '...' }` | `rules: changes:` |
| `input` | `when: manual` |
| `submitter` | Protected environments |
| Multibranch Pipeline | пайплайны веток и MR из коробки |
| `agent { docker { } }` | docker-executor + `image:` |
| `lock(resource:)` | `resource_group:` |

---

## 💼 Как это в DevOps

- Shared Library — то, ради чего в энтерпрайзе держат платформенную команду: 200 проектов,
  один стандарт пайплайна, изменения в одном месте.
- Multibranch + вебхук = поведение, к которому все привыкли в GitLab: пайплайн на ветку
  и на MR без ручного создания джоб.
- Перевод статических агентов на docker/k8s-агенты — типовой проект по снижению
  «загадочных» падений сборок.
- На собесе в банк любят спрашивать именно про Shared Libraries и multibranch:
  это признак того, что человек работал с Jenkins не на уровне «нажал Build Now».

---

## 📌 Шпаргалка

```groovy
@Library('devops-lib@v1.4.0') _          // подключить библиотеку (с пином версии!)

parallel {                                // параллельные стадии
  stage('A') { steps { sh 'a' } }
  stage('B') { steps { sh 'b' } }
}

when { allOf { branch 'main'; expression { params.GO } }; beforeAgent true }

input { message 'Деплой?'; ok 'Да'; submitter 'leads' }

agent { docker { image 'python:3.12-slim'; reuseNode true } }
agent { kubernetes { yaml '...' } }

lock(resource: 'prod') { sh './deploy.sh' }
```

| Хочу | Как |
|------|-----|
| Убрать копипасту между проектами | Shared Library + `@Library('lib@vX.Y.Z')` |
| Общий шаг | `vars/myStep.groovy` c `def call(...)` |
| Класс с логикой | `src/org/example/Class.groovy` (Serializable) |
| Пайплайн на каждую ветку | Multibranch Pipeline |
| Пайплайн на PR/MR | Multibranch + `changeRequest()` |
| Ускорить | `parallel` + `failFast true` |
| Условие без занятия агента | `when { ... ; beforeAgent true }` |
| Подтверждение с параметрами | `input { parameters { ... } }` |
| Чистое окружение | docker/k8s-агент |
| Не деплоить одновременно | `lock()` + `disableConcurrentBuilds()` |

---

## 🧠 Что запомнить

1. Декларативный пайплайн — дефолт; скриптовый — только там, где нужна настоящая логика.
2. `parallel` ускоряет только при наличии свободных executors; `failFast` экономит время.
3. `when { ... beforeAgent true }` не занимает агента при ложном условии.
4. `input` блокирует пайплайн: ставь таймаут, ограничивай `submitter`, не держи агента.
5. Shared Library — аналог `include`+`extends` из GitLab; `vars/` = шаги, `src/` = классы.
6. Библиотеку **обязательно** пинить по версии: `@Library('lib@v1.4.0')`.
7. Целый типовой пайплайн можно свести к трём строкам в `Jenkinsfile`.
8. Multibranch сам заводит пайплайны на ветки и PR/MR и удаляет их для исчезнувших веток.
9. В multibranch появляются `BRANCH_NAME`, `CHANGE_ID`, `CHANGE_TARGET`.
10. Docker/k8s-агенты решают проблему грязного workspace и разнобоя версий инструментов.
11. Классы в `src/` должны быть `Serializable` — пайплайн сериализуется между шагами.
12. Сложность нужно держать в узде: непонятная библиотека хуже честной копипасты.

---

## Задачи

> Лаба: Jenkins из тем 10-11 + **второй** репозиторий под shared library.

---

### Блок A. Теория

**A1.** Чем скриптовый пайплайн отличается от декларативного? Когда оправдан скриптовый?

<details><summary>Ответ</summary>

Декларативный — структурированный DSL с валидацией и предсказуемой структурой;
скриптовый — произвольный Groovy в `node { }` с полной свободой (циклы, классы,
обработка исключений) и почти без проверок. Скриптовый оправдан при действительно
сложной динамической логике, которую не выразить декларативно.

</details>

**A2.** Как выполнить произвольный Groovy внутри декларативного пайплайна?

<details><summary>Ответ</summary>

Блоком `script { }` внутри `steps`.

</details>

**A3.** Как объявить параллельные стадии? Что даёт `failFast`?

<details><summary>Ответ</summary>

Блоком `parallel { }` внутри стадии (или `parallel map` в скриптовом стиле).
`failFast true` останавливает остальные ветки при падении одной — экономит время и ресурсы.

</details>

**A4.** Почему параллельные стадии иногда не ускоряют сборку?

<details><summary>Ответ</summary>

Потому что параллелизм упирается в executors: если свободных слотов нет,
стадии встают в очередь. Также мешают общий ресурс (`lock`), медленная подготовка
окружения в каждой ветке и отсутствие кэша.

</details>

**A5.** Перечисли восемь условий, доступных в `when`.

<details><summary>Ответ</summary>

`branch`, `tag`/`buildingTag()`, `changeRequest()`, `environment name/value`,
`expression { }`, `changeset`, `equals`, `anyOf`, `allOf`, `not`, `triggeredBy`.

</details>

**A6.** Что делает `beforeAgent true` и зачем это нужно?

<details><summary>Ответ</summary>

Проверяет условие **до** выделения агента: если условие ложно, агент не занимается
и время на подготовку окружения не тратится. Аналогично `beforeInput`/`beforeOptions`.

</details>

**A7.** Как в `when` проверить, что сборка запущена из PR/MR? А что по тегу?

<details><summary>Ответ</summary>

PR/MR — `when { changeRequest() }` (можно `changeRequest target: 'main'`);
тег — `when { buildingTag() }` или `when { tag 'v*' }`.

</details>

**A8.** Что делает `input` и какие три вещи обязательно нужно с ним настроить?

<details><summary>Ответ</summary>

Останавливает пайплайн и ждёт подтверждения человека. Обязательно: таймаут
(`options { timeout }`), ограничение `submitter`, и вынос ожидания из-под занятого агента
(`agent none` на уровне пайплайна).

</details>

**A9.** Как ограничить круг людей, которые могут подтвердить деплой?

<details><summary>Ответ</summary>

Параметром `submitter` в `input` (список пользователей/групп); дополнительно —
правами на джобу и папку в матрице авторизации.

</details>

**A10.** Что такое Shared Library? Какая структура каталогов и что означает каждый?

<details><summary>Ответ</summary>

Репозиторий с общим кодом пайплайнов: `vars/` — глобальные шаги (имя файла =
имя шага, внутри `def call(...)`), `src/` — Groovy-классы в пакетах, `resources/` —
статические файлы, доступные через `libraryResource`.

</details>

**A11.** Как называется шаг, определённый в `vars/deployToEnv.groovy`?

<details><summary>Ответ</summary>

`deployToEnv` — имя файла без расширения, вызывается как обычный шаг.

</details>

**A12.** Как подключить библиотеку и почему обязательно указывать версию?

<details><summary>Ответ</summary>

`@Library('devops-lib@v1.4.0') _` в начале `Jenkinsfile` (или «Load implicitly»
в настройках). Версия обязательна, потому что иначе используется ветка по умолчанию:
любой коммит в библиотеку мгновенно меняет поведение всех пайплайнов и может их сломать.

</details>

**A13.** Почему классы в `src/` должны реализовывать `Serializable`?

<details><summary>Ответ</summary>

Состояние пайплайна сериализуется на диск между шагами (для продолжения после
перезапуска контроллера). Несериализуемые объекты в переменных приводят к
`NotSerializableException`.

</details>

**A14.** Что такое Multibranch Pipeline и какую проблему он решает?

<details><summary>Ответ</summary>

Тип джобы, который сканирует репозиторий и автоматически создаёт пайплайн
для каждой ветки и PR/MR с `Jenkinsfile`, а также удаляет джобы исчезнувших веток.
Решает проблему ручного создания и поддержки джоб на каждую ветку.

</details>

**A15.** Какие переменные появляются в multibranch-сборке?

<details><summary>Ответ</summary>

`BRANCH_NAME`, `CHANGE_ID`, `CHANGE_TARGET`, `CHANGE_BRANCH`, `CHANGE_AUTHOR`,
`CHANGE_TITLE`, `CHANGE_URL`.

</details>

**A16.** Что такое Organization Folder?

<details><summary>Ответ</summary>

Тип папки, сканирующей все репозитории организации/группы и автоматически
создающей multibranch-джобы для каждого проекта, где найден `Jenkinsfile`.

</details>

**A17.** Что даёт docker-агент и какие три проблемы Jenkins он решает?

<details><summary>Ответ</summary>

Каждая сборка получает чистое изолированное окружение из образа. Решает:
грязный workspace, отсутствие/разнобой версий инструментов на агентах, конфликты
зависимостей между проектами на одном агенте.

</details>

**A18.** Что делает `reuseNode true` у docker-агента?

<details><summary>Ответ</summary>

Запускает контейнер на том же узле и в том же workspace, что и остальной
пайплайн, вместо выделения нового узла — важно, чтобы файлы предыдущих стадий были
доступны.

</details>

**A19.** Сопоставь с GitLab CI: Shared Library, `when`, `input`, multibranch, `lock`.

<details><summary>Ответ</summary>

Shared Library ↔ `include` + `extends`; `when` ↔ `rules`; `input` ↔ `when: manual`
(+ Protected environments для `submitter`); multibranch ↔ встроенные пайплайны веток и MR;
`lock` ↔ `resource_group`.

</details>

---

### Блок B. «Что сделает этот код»

```groovy
// B1
stage('Deploy') {
    when { branch 'main'; beforeAgent true }
    agent { docker { image 'alpine' } }
    steps { sh './deploy.sh' }
}
```
Вопрос: что произойдёт на ветке `feature/x`?

<details><summary>Ответ</summary>

На `feature/x` условие ложно, и благодаря `beforeAgent true` контейнер-агент
даже не поднимется; стадия будет пропущена.

</details>

```groovy
// B2
parallel {
    stage('A') { steps { sh 'sleep 30' } }
    stage('B') { steps { sh 'exit 1' } }
    stage('C') { steps { sh 'sleep 30' } }
}
```
Вопрос: что будет с A и C? А если добавить `failFast true`?

<details><summary>Ответ</summary>

Без `failFast` A и C доработают до конца, стадия упадёт после их завершения.
С `failFast true` остальные ветки будут прерваны сразу после падения B.

</details>

```groovy
// B3
@Library('devops-lib') _
```

<details><summary>Ответ</summary>

Библиотека подключена без версии: будет использована ветка по умолчанию,
то есть поведение пайплайна может измениться в любой момент.

</details>

```groovy
// B4
stage('Approve') {
    steps { input 'Деплоим?' }
}
```
Вопрос: какие две проблемы у этой стадии?

<details><summary>Ответ</summary>

Нет таймаута (сборка может висеть бесконечно) и нет `submitter` (подтвердить
может кто угодно с доступом); плюс если пайплайн под `agent any`, ожидание держит executor.

</details>

```groovy
// B5
when { changeset '**/backend/**' }
```

<details><summary>Ответ</summary>

Стадия выполнится, только если в изменениях есть файлы по пути `**/backend/**`
(аналог `rules: changes` в GitLab).

</details>

```groovy
// B6
script {
    def jobs = [:]
    for (v in ['1', '2', '3']) {
        jobs["job-${v}"] = { sh "echo ${v}" }
    }
    parallel jobs
}
```
Вопрос: какая классическая Groovy-ловушка может здесь сработать?

<details><summary>Ответ</summary>

Классическая ловушка замыканий в Groovy/Java-циклах: переменная цикла
захватывается по ссылке, и все замыкания видят последнее значение. Решение —
завести локальную копию внутри итерации (`def vv = v`) или использовать `.each { v -> }`.

</details>

---

### Блок C. Практика

#### C1. 🔑 Shared Library (главное задание темы)

1. Создай репозиторий `jenkins-shared-library` со структурой `vars/`, `src/`, `resources/`.
2. Напиши шаг `vars/buildDockerImage.groovy` (параметры: `name`, `tag`, `registry`, `creds`),
   возвращающий полное имя образа.
3. Напиши шаг `vars/deployToEnv.groovy` (параметры: `env`, `image`, `host`), выполняющий
   деплой по SSH и проверку `/health`.
4. Напиши класс `src/org/example/Notifier.groovy` с методами `success`/`failure`.
5. Подключи библиотеку в Jenkins (Global Pipeline Libraries), поставь тег `v1.0.0`.
6. Перепиши свой `Jenkinsfile` из темы 11 с использованием библиотеки: он должен стать
   минимум вдвое короче.
7. Выпусти `v1.1.0` с изменением поведения и покажи, что проект на `v1.0.0` не затронут.

<details><summary>Ответ</summary>

Критерии: `Jenkinsfile` проекта сократился минимум вдвое; при переключении
проекта на новую версию библиотеки поведение меняется, а закреплённые на старой —
нет; шаги имеют понятные параметры и валидацию обязательных.

</details>

#### C2. Пайплайн одной строкой
Сделай `vars/standardPipeline.groovy`, описывающий весь типовой пайплайн.
`Jenkinsfile` проекта должен стать таким:
```groovy
@Library('devops-lib@v1.1.0') _
standardPipeline(appName: 'myapp', testCmd: 'pytest -q')
```
Проверь на двух разных проектах.

<details><summary>Ответ</summary>

Проверка: два разных проекта используют один и тот же вызов, различаясь
только параметрами.

</details>

#### C3. Параллельные стадии
Разнеси lint, unit и security-скан по параллельным стадиям. Замерь время до и после.
Затем ограничь агента одним executor'ом и замерь снова — объясни результат.

<details><summary>Ответ</summary>

Ожидаемо: с несколькими executors время стадии ≈ времени самой долгой ветки;
с одним executor'ом параллель вырождается в последовательность.

</details>

#### C4. `when` во всех вариантах
Сделай пайплайн, в котором:
- стадия dev-деплоя выполняется на любой ветке, кроме main и PR;
- staging — только на main;
- prod — только по тегу `v*`;
- «тяжёлые» тесты — только при изменении `backend/**`.
Используй `beforeAgent true` и проверь, что агент не занимается зря.

<details><summary>Ответ</summary>

Критерий: в логе видно, что пропущенные стадии не поднимали агента (нет строк
подготовки окружения).

</details>

#### C5. `input` с параметрами
Сделай стадию подтверждения с выбором стратегии деплоя (`rolling`/`canary`),
ограничением `submitter` и таймаутом 1 час. Проверь поведение при истечении таймаута
и при отказе (Abort).

<details><summary>Ответ</summary>

Ожидаемо: по таймауту сборка становится ABORTED; при Abort вручную — тоже,
и `post { aborted { ... } }` срабатывает.

</details>

#### C6. Multibranch
1. Создай Multibranch Pipeline на свой репозиторий.
2. Создай ветки `feature/a`, `develop` — убедись, что джобы появились автоматически.
3. Открой MR/PR и проверь появление джобы `PR-N` и переменных `CHANGE_*`.
4. Удали ветку и убедись, что джоба исчезла (Orphaned Item Strategy).
5. Настрой сканирование по вебхуку, а не по расписанию.

<details><summary>Ответ</summary>

Критерий: джобы веток появляются и исчезают автоматически, а PR-джоба содержит
`CHANGE_ID`; сканирование по вебхуку происходит мгновенно после пуша.

</details>

#### C7. Docker-агент
Переведи стадии тестов на `agent { docker { image ... } }`. Проверь:
- версия рантайма внутри контейнера;
- отсутствие «мусора» от прошлых сборок;
- кэш зависимостей через `args '-v ...'`.

<details><summary>Ответ</summary>

Проверка: внутри контейнера ожидаемая версия рантайма, workspace без файлов
прошлых сборок, повторная сборка быстрее за счёт кэша, смонтированного через `args`.

</details>

#### C8. Скриптовый пайплайн
Перепиши одну стадию в скриптовом стиле (`node { }`) с `try/catch/finally`.
Опиши, что стало удобнее, а что хуже.

<details><summary>Ответ</summary>

Типичный вывод: скриптовый удобнее для сложной логики и обработки ошибок,
но теряются валидация, читаемость и единообразие.

</details>

#### C9. Динамическая параллель
Сгенерируй параллельные стадии по списку сервисов (`services/*`) и запусти их
через `parallel`. Добавь `failFast`.

<details><summary>Ответ</summary>

Не забудь про ловушку замыканий (см. B6) и `failFast`.

</details>

#### C10. Миграция
Возьми свой `.gitlab-ci.yml` и `Jenkinsfile` для одного приложения и составь таблицу
соответствий по каждому ключу. Отметь, где в Jenkins нужен плагин.

<details><summary>Ответ</summary>

Ориентир: `agent`↔`image/tags`, `environment`↔`variables`, `credentials`↔
`CI/CD Variables`, `post`↔`after_script`/`rules`, `junit`↔`artifacts:reports:junit`,
`stash`↔`artifacts`, `input`↔`when: manual`, `when`↔`rules`, `lock`↔`resource_group`,
Shared Library↔`include`.

</details>

---

### Блок D. Инциденты

**D1.** Коммит в shared library сломал пайплайны 20 проектов. Что было не так
и как исправить навсегда?

<details><summary>Ответ</summary>

Проекты подключали библиотеку без пина версии. Исправить: везде `@Library('lib@vX.Y.Z')`,
SemVer и changelog для библиотеки, тестовый проект-канарейка, запрет прямых пушей
в ветку библиотеки, ревью изменений.

</details>

**D2.** Шаг из библиотеки не находится: `No such DSL method 'buildDockerImage'`.
Пять причин.

<details><summary>Ответ</summary>

(1) Библиотека не зарегистрирована в Manage Jenkins; (2) не подключена в
`Jenkinsfile` (`@Library(...) _`, включая символ подчёркивания); (3) файл лежит не в `vars/`
или назван иначе; (4) в файле нет `def call(...)`; (5) указана несуществующая версия/ветка;
(6) ошибка компиляции внутри библиотеки.

</details>

**D3.** Пайплайн падает с `java.io.NotSerializableException`. Что это значит?

<details><summary>Ответ</summary>

В переменной пайплайна оказался несериализуемый объект (например, результат
парсинга JSON или matcher регулярки), а состояние пайплайна должно сериализоваться.
Лечение: обернуть работу с такими объектами в метод с `@NonCPS` или не хранить их
в переменных между шагами.

</details>

**D4.** Параллельные стадии выполняются последовательно. Почему?

<details><summary>Ответ</summary>

Не хватает свободных executors (один агент/один слот), либо ветки конкурируют
за один `lock`/ресурс, либо они выполняются на одном узле с ограничением.

</details>

**D5.** Multibranch не видит новую ветку. Что проверить?

<details><summary>Ответ</summary>

Ветка без `Jenkinsfile`, фильтры Branch Sources/Behaviours исключают её,
сканирование не запускалось (нет вебхука и не наступил интервал), нет прав у креда
на чтение репозитория, неверная конфигурация источника.

</details>

**D6.** После настройки multibranch сборки запускаются на каждую ветку и забивают агентов.
Как ограничить?

<details><summary>Ответ</summary>

Ограничить обнаружение ветками по шаблону, отключить сборку всех PR (или собирать
только PR в основную ветку), использовать `when`/`rules` внутри `Jenkinsfile`, ограничить
число одновременных сборок (`throttle`, `disableConcurrentBuilds`), добавить агентов.

</details>

**D7.** Стадия с `input` заняла единственный executor на 6 часов. Как надо было?

<details><summary>Ответ</summary>

Использовать `agent none` на уровне пайплайна и выделять агента только стадиям,
где реально выполняются шаги; на `input` поставить таймаут и `submitter`.

</details>

**D8.** Docker-агент падает с `permission denied` при записи в workspace. Причина и решение.

<details><summary>Ответ</summary>

Пользователь внутри контейнера (обычно не root или другой UID) не имеет прав
на каталог workspace, созданный на хосте. Решения: `args '-u root:root'` (просто, но менее
безопасно), сопоставление UID агента, права на каталог, либо отдельный workspace
в контейнере.

</details>

**D9.** В библиотеке используется `for (v in list) { jobs[v] = { sh "echo ${v}" } }`,
и все параллельные ветки печатают одно и то же значение. Почему?

<details><summary>Ответ</summary>

Ловушка захвата переменной цикла: все замыкания ссылаются на одну и ту же
переменную, которая после цикла хранит последнее значение. Нужно копировать значение
внутри итерации (`def vv = v`) или использовать `.each`.

</details>

**D10.** Библиотека разрослась: 40 шагов, никто не знает, что делает половина.
Что с этим делать организационно?

<details><summary>Ответ</summary>

Ввести владельца библиотеки и ревью, документацию на каждый шаг (README +
примеры), SemVer и changelog, депрекейт-политику, тесты библиотеки, регулярную чистку
неиспользуемых шагов, ограничение «библиотека решает частые задачи, а не всё подряд».

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое Shared Libraries и зачем они нужны?

<details><summary>Ответ</summary>

Общий код пайплайнов в отдельном git-репозитории, подключаемый в `Jenkinsfile`:
убирает копипасту, даёт единый стандарт и точку изменения для всех проектов.

</details>

**2.** Как устроен репозиторий библиотеки?

<details><summary>Ответ</summary>

`vars/` — шаги (`def call`), `src/` — классы в пакетах, `resources/` — статические
файлы; версии — ветками и тегами репозитория.

</details>

**3.** Как подключить библиотеку и зафиксировать её версию?

<details><summary>Ответ</summary>

`@Library('name@v1.4.0') _`; пин версии защищает проекты от неожиданных изменений.

</details>

**4.** Как сделать параллельные стадии?

<details><summary>Ответ</summary>

`parallel { stage(...) stage(...) }` (+ `failFast true`), либо `parallel map`
в скриптовом стиле.

</details>

**5.** Как условно выполнять стадию?

<details><summary>Ответ</summary>

Блоком `when` со всеми условиями (`branch`, `changeRequest`, `expression`, `changeset`),
желательно с `beforeAgent true`.

</details>

**6.** Как реализовать ручное подтверждение с ограничением по людям?

<details><summary>Ответ</summary>

Шаг `input` с `submitter`, `ok`, параметрами и таймаутом; агент при этом не должен
быть занят.

</details>

**7.** Что такое Multibranch Pipeline?

<details><summary>Ответ</summary>

Тип джобы, автоматически создающий пайплайны для веток и PR/MR с `Jenkinsfile`
и удаляющий их при исчезновении веток.

</details>

**8.** Как запускать сборки в чистом окружении?

<details><summary>Ответ</summary>

Docker- или Kubernetes-агенты: каждая сборка в свежем контейнере/поде.

</details>

**9.** Чем скриптовый пайплайн отличается от декларативного?

<details><summary>Ответ</summary>

Декларативный — структура и валидация; скриптовый — произвольный Groovy и максимум
гибкости при худшей читаемости.

</details>

**10.** Как бы ты организовал CI для 50 микросервисов на Jenkins?

<details><summary>Ответ</summary>

Multibranch (или Organization Folder) + Shared Library со стандартным пайплайном,
docker/k8s-агенты, вебхуки, единые креды по папкам, JCasC для конфигурации,
мониторинг очереди и автоскейлинг агентов.

</details>

---

### 🎯 Чек-лист

- [ ] Создал shared library и вынес в неё сборку и деплой
- [ ] `Jenkinsfile` проекта сократился минимум вдвое
- [ ] Пиню версию библиотеки и понимаю, почему это критично
- [ ] Использую параллельные стадии и понимаю ограничение по executors
- [ ] Применяю `when` с `beforeAgent true`
- [ ] `input` у меня всегда с таймаутом и `submitter`
- [ ] Настроил Multibranch со сканированием по вебхуку
- [ ] Сборки идут в docker-агентах, workspace чистый
- [ ] Знаю ловушку замыканий в циклах Groovy
- [ ] Могу сопоставить каждую конструкцию Jenkins с аналогом в GitLab CI
