---
title: "11. Jenkinsfile и декларативный пайплайн"
description: "pipeline/agent/stages/steps, credentials, parameters, post, stash/unstash — production-ready Jenkinsfile"
---

# 11. Jenkinsfile и декларативный пайплайн

> Роадмап → 4. CI/CD → Инструменты → Jenkins → **База**:
> `Jenkinsfile`; декларативный пайплайн (`pipeline`, `agent`, `stages`, `stage`, `steps`);
> `post`; `environment`; `Credentials`; `parameters`; интеграция с Git (webhook).
> **После темы ты умеешь:** написать production-ready `Jenkinsfile` с секретами,
> параметрами, post-обработкой и деплоем.

---

## 1. Скелет декларативного пайплайна

```groovy
pipeline {
    agent any                       // ГДЕ выполнять (обязательный блок)

    options {                       // поведение пайплайна
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
        disableConcurrentBuilds()
        timestamps()
    }

    parameters {                    // параметры запуска
        choice(name: 'ENVIRONMENT', choices: ['dev', 'staging', 'prod'], description: 'Куда деплоим')
        booleanParam(name: 'RUN_TESTS', defaultValue: true, description: 'Гонять тесты')
        string(name: 'IMAGE_TAG', defaultValue: '', description: 'Пусто = текущий коммит')
    }

    environment {                   // переменные окружения для всех стадий
        REGISTRY = 'registry.example.com'
        APP_NAME = 'myapp'
        IMAGE    = "${REGISTRY}/${APP_NAME}"
    }

    triggers {                      // чем запускается
        cron('H 2 * * *')
    }

    stages {
        stage('Checkout') {
            steps { checkout scm }
        }

        stage('Build') {
            steps {
                sh 'make build'
            }
        }

        stage('Test') {
            when { expression { params.RUN_TESTS } }
            steps {
                sh 'make test'
            }
            post {
                always { junit 'reports/**/*.xml' }
            }
        }

        stage('Deploy') {
            steps {
                sh "./deploy.sh ${params.ENVIRONMENT}"
            }
        }
    }

    post {                          // что делать по итогам
        always  { cleanWs() }
        success { echo "✅ ${env.JOB_NAME} #${env.BUILD_NUMBER} успешно" }
        failure { echo "❌ Сборка упала: ${env.BUILD_URL}" }
    }
}
```

| Блок | Обязателен | Смысл |
|------|-----------|-------|
| `pipeline { }` | ✅ | Корень декларативного пайплайна |
| `agent` | ✅ | Где выполнять (на уровне пайплайна и/или стадии) |
| `stages { stage { steps { } } }` | ✅ | Этапы и шаги |
| `options` | ❌ | Таймауты, хранение сборок, запрет параллельных запусков |
| `parameters` | ❌ | Параметризованная сборка |
| `environment` | ❌ | Переменные, в том числе из credentials |
| `triggers` | ❌ | cron, pollSCM, вебхуки |
| `tools` | ❌ | Автоустановка JDK/Maven/Node из настроек Jenkins |
| `post` | ❌ | Действия по результату |

---

## 2. `agent` — где выполняется

```groovy
agent any                              // любой свободный агент
agent none                             // не занимать агента на уровне пайплайна
agent { label 'linux && docker' }      // по метке
agent {                                 // ⭐ каждый билд в чистом контейнере
    docker {
        image 'python:3.12-slim'
        args  '-v $HOME/.cache/pip:/root/.cache/pip'
        label 'docker'
        reuseNode true
    }
}
agent {                                 // собрать образ агента из Dockerfile репозитория
    dockerfile { filename 'ci/Dockerfile.ci' }
}
agent { kubernetes { yaml podTemplateYaml } }   // под на сборку
```

`agent none` на уровне пайплайна + свой `agent` в каждой стадии — способ не держать
executor занятым во время ожидания `input`.

---

## 3. `environment` и Credentials — секреты

### Хранилище
Manage Jenkins → Credentials → System → Global credentials.
Типы: *Secret text* (токен), *Username with password*, *SSH Username with private key*,
*Secret file* (kubeconfig, keystore), *Certificate*.

### Способ 1: `environment { credentials(...) }`
```groovy
environment {
    REGISTRY_CREDS = credentials('registry-user')   // даёт 3 переменные:
    // REGISTRY_CREDS      = user:password
    // REGISTRY_CREDS_USR  = user
    // REGISTRY_CREDS_PSW  = password
    SONAR_TOKEN = credentials('sonar-token')        // secret text → одна переменная
}
steps {
    sh 'echo "$REGISTRY_CREDS_PSW" | docker login -u "$REGISTRY_CREDS_USR" --password-stdin "$REGISTRY"'
}
```

### Способ 2: `withCredentials` — точечно и короче по времени жизни
```groovy
steps {
    withCredentials([
        usernamePassword(credentialsId: 'registry-user',
                         usernameVariable: 'REG_USER', passwordVariable: 'REG_PASS'),
        sshUserPrivateKey(credentialsId: 'prod-ssh', keyFileVariable: 'SSH_KEY'),
        string(credentialsId: 'slack-token', variable: 'SLACK_TOKEN'),
        file(credentialsId: 'kubeconfig', variable: 'KUBECONFIG')
    ]) {
        sh '''
            echo "$REG_PASS" | docker login -u "$REG_USER" --password-stdin "$REGISTRY"
            ssh -i "$SSH_KEY" deploy@prod "docker compose pull && docker compose up -d"
        '''
    }
}
```

**Правила работы с секретами в Jenkins:**
1. Jenkins маскирует значения кредов в логе (`****`) — но так же, как в GitLab,
   только точные совпадения: не выводи их сам и не делай `set -x` рядом.
2. `sh "команда ${SECRET}"` с **двойными** кавычками подставляет значение в текст команды
   средствами Groovy → секрет может утечь в лог и в список процессов.
   Используй **одинарные** кавычки и обращение как к переменной окружения: `sh 'echo "$SECRET" | ...'`.
3. Ограничивай область: креды на уровне папки (Folder) и роли, а не глобально всем.
4. Для прод-кредов — отдельная папка/агент и ограниченные права.

---

## 4. `parameters` — параметризованные сборки

```groovy
parameters {
    string(name: 'BRANCH', defaultValue: 'main', description: 'Ветка')
    choice(name: 'ENVIRONMENT', choices: ['dev', 'staging', 'prod'], description: '')
    booleanParam(name: 'SKIP_TESTS', defaultValue: false, description: '')
    password(name: 'ADMIN_PASS', defaultValue: '', description: 'Разовый пароль')
    text(name: 'RELEASE_NOTES', defaultValue: '', description: '')
}
```
Использование: `params.ENVIRONMENT`, `params.SKIP_TESTS`.

> ⚠️ Первая сборка после добавления `parameters` берёт значения по умолчанию и только
> потом появляется форма «Build with Parameters» — классическая путаница новичка.
> И помни: параметры задаёт человек — не доверяй им слепо (инъекции в `sh`).

---

## 5. `post` — действия по результату

```groovy
post {
    always {
        junit testResults: 'reports/**/*.xml', allowEmptyResults: true
        archiveArtifacts artifacts: 'dist/**', fingerprint: true, allowEmptyArchive: true
        cleanWs()
    }
    success  { echo 'Успех' }
    failure  {
        mail to: 'team@example.com',
             subject: "FAILED: ${env.JOB_NAME} #${env.BUILD_NUMBER}",
             body: "Лог: ${env.BUILD_URL}console"
    }
    unstable { echo 'Тесты упали, но сборка прошла' }
    changed  { echo 'Статус изменился по сравнению с прошлой сборкой' }
    aborted  { echo 'Отменено' }
    cleanup  { echo 'Выполняется самым последним' }
}
```

`post` можно объявлять и на уровне пайплайна, и внутри каждой `stage`.
Порядок: `always` → результат-специфичные → `cleanup`.

---

## 6. Полезные шаги (`steps`)

```groovy
sh 'make build'                                   // shell (Linux)
bat 'make.bat'                                    // Windows
powershell 'Get-Date'

checkout scm                                      // забрать репозиторий джобы
git branch: 'main', url: 'https://gitlab.com/g/p.git', credentialsId: 'git-creds'

script { /* произвольный Groovy внутри декларативного пайплайна */ }

echo "Сообщение"
error "Явно уронить сборку"
unstable "Пометить сборку нестабильной"

def out = sh(script: 'git rev-parse --short HEAD', returnStdout: true).trim()
def code = sh(script: './check.sh', returnStatus: true)     // не падать, получить код

stash name: 'app', includes: 'dist/**'            // передать файлы между стадиями/агентами
unstash 'app'

archiveArtifacts artifacts: 'dist/**', fingerprint: true
junit 'reports/**/*.xml'

timeout(time: 10, unit: 'MINUTES') { sh './long.sh' }
retry(3) { sh 'flaky-network-call' }
sleep time: 5, unit: 'SECONDS'
dir('subproject') { sh 'make' }                   // сменить каталог
withEnv(['FOO=bar']) { sh 'echo $FOO' }
lock(resource: 'prod-deploy') { sh './deploy.sh' } // взаимное исключение (Lockable Resources)
build job: 'other-pipeline', parameters: [string(name: 'TAG', value: env.GIT_COMMIT)], wait: true
```

**`stash`/`unstash` — аналог `artifacts` в GitLab** для передачи файлов между стадиями
(особенно когда стадии идут на разных агентах). Для больших файлов лучше registry/хранилище.

---

## 7. Полезные встроенные переменные

```groovy
env.BUILD_NUMBER      // 42
env.BUILD_URL         // http://jenkins/job/app/42/
env.JOB_NAME          // app/main
env.NODE_NAME         // агент
env.WORKSPACE         // путь к рабочему каталогу
env.GIT_COMMIT        // полный SHA
env.GIT_BRANCH        // origin/main
env.BRANCH_NAME       // в multibranch — имя ветки
env.CHANGE_ID         // номер MR/PR в multibranch
currentBuild.result           // SUCCESS / UNSTABLE / null
currentBuild.currentResult    // текущий результат
currentBuild.duration
```

---

## 8. Интеграция с Git и webhook

### GitLab → Jenkins
1. Поставить плагин **GitLab** (и **GitLab Branch Source** для multibranch).
2. В джобе: Build Triggers → *Build when a change is pushed to GitLab*,
   скопировать URL вида `http://jenkins.example.com/project/<job-name>`, создать Secret token.
3. В GitLab: Settings → Webhooks → URL + токен + события (Push, Merge request).
4. Проверить кнопкой **Test → Push events** и посмотреть ответ (200 = принято).

### GitHub → Jenkins
Плагин GitHub → «GitHub hook trigger for GITScm polling»; в репозитории webhook на
`http://jenkins.example.com/github-webhook/`.

### В `Jenkinsfile`
```groovy
triggers {
    gitlab(triggerOnPush: true, triggerOnMergeRequest: true, branchFilterType: 'All')
    // или универсально:
    // pollSCM('H/5 * * * *')
}
```

> В закрытых контурах вебхук часто невозможен (Jenkins недоступен извне) — тогда
> остаётся `pollSCM`. Это нормальный компромисс, но нужно понимать его цену:
> задержка и постоянная нагрузка на Git.

---

## 9. Полный пример: сборка образа и деплой

```groovy
pipeline {
    agent { label 'docker' }

    options {
        timeout(time: 45, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '30'))
        disableConcurrentBuilds()
        timestamps()
        ansiColor('xterm')
    }

    parameters {
        choice(name: 'ENVIRONMENT', choices: ['staging', 'prod'], description: 'Куда деплоить')
    }

    environment {
        REGISTRY   = 'registry.example.com'
        IMAGE      = "${REGISTRY}/myapp"
        IMAGE_TAG  = "${env.GIT_COMMIT?.take(8) ?: 'dev'}"
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                script { env.IMAGE_TAG = sh(script: 'git rev-parse --short HEAD', returnStdout: true).trim() }
            }
        }

        stage('Lint & Test') {
            agent { docker { image 'python:3.12-slim'; reuseNode true } }
            steps {
                sh 'pip install -q -r requirements.txt -r requirements-dev.txt'
                sh 'flake8 app/'
                sh 'pytest -q --junitxml=reports/junit.xml'
            }
            post { always { junit 'reports/*.xml' } }
        }

        stage('Build & Push') {
            steps {
                withCredentials([usernamePassword(credentialsId: 'registry-creds',
                                                  usernameVariable: 'REG_USER',
                                                  passwordVariable: 'REG_PASS')]) {
                    sh '''
                        echo "$REG_PASS" | docker login -u "$REG_USER" --password-stdin "$REGISTRY"
                        docker build -t "$IMAGE:$IMAGE_TAG" .
                        docker push "$IMAGE:$IMAGE_TAG"
                    '''
                }
            }
        }

        stage('Scan') {
            steps {
                sh 'trivy image --exit-code 1 --severity CRITICAL "$IMAGE:$IMAGE_TAG"'
            }
        }

        stage('Approve prod') {
            when { expression { params.ENVIRONMENT == 'prod' } }
            options { timeout(time: 2, unit: 'HOURS') }
            steps {
                input message: "Деплоить ${IMAGE}:${IMAGE_TAG} в PROD?", ok: 'Деплой',
                      submitter: 'release-managers'
            }
        }

        stage('Deploy') {
            steps {
                lock(resource: "deploy-${params.ENVIRONMENT}") {
                    withCredentials([sshUserPrivateKey(credentialsId: "ssh-${params.ENVIRONMENT}",
                                                       keyFileVariable: 'SSH_KEY',
                                                       usernameVariable: 'SSH_USER')]) {
                        sh '''
                            ssh -i "$SSH_KEY" -o StrictHostKeyChecking=yes "$SSH_USER@$DEPLOY_HOST" \
                                "APP_IMAGE=$IMAGE:$IMAGE_TAG docker compose up -d --pull always"
                        '''
                    }
                    sh 'curl -fsS --retry 5 --retry-delay 3 "https://$DEPLOY_HOST/health"'
                }
            }
        }
    }

    post {
        always  { cleanWs() }
        failure { echo "❌ ${env.JOB_NAME} #${env.BUILD_NUMBER}: ${env.BUILD_URL}" }
    }
}
```

---

## 10. Частые ошибки

| Ошибка | Причина/решение |
|--------|-----------------|
| Секрет в логе | `sh "... ${SECRET}"` с двойными кавычками → используй одинарные и `$VAR` |
| «Файл из прошлой сборки» | Workspace переиспользуется → `cleanWs()` или docker-агент |
| `No such DSL method 'xxx'` | Не установлен плагин, дающий этот шаг |
| Сборка висит на `input` и держит агента | `agent none` + агент на уровне стадий, `options { timeout }` |
| Переменная пуста в `sh` | Groovy-переменные ≠ переменные окружения; используй `env.X` или `withEnv` |
| Параметры не появились | Первая сборка после добавления `parameters` их только регистрирует |
| Тесты упали, сборка зелёная | Нет `junit` шага / результат подавлен `|| true` |
| Конкурентные сборки портят стенд | `disableConcurrentBuilds()`, `lock(resource:)` |

---

## 💼 Как это в DevOps

- `Jenkinsfile` лежит **в репозитории приложения** — это тот же «pipeline as code»,
  что и `.gitlab-ci.yml`: ревью, история, откат.
- Стандартная задача: перенести старые freestyle-джобы в `Jenkinsfile` и вынести
  повторяющееся в shared library (тема 12).
- Работа с credentials — то, что спрашивают в банках первым делом: где лежат секреты,
  кто имеет доступ, как ограничивается область видимости.
- `lock` + `disableConcurrentBuilds` — jenkins-аналог `resource_group` в GitLab:
  обязательны для деплойных пайплайнов.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Скелет | `pipeline { agent any; stages { stage('X') { steps { sh '...' } } } }` |
| Контейнер на сборку | `agent { docker { image 'python:3.12-slim' } }` |
| Переменные | `environment { KEY = 'value' }` |
| Секрет (user/pass) | `credentials('id')` → `_USR` / `_PSW` |
| Секрет точечно | `withCredentials([...]) { }` |
| Параметры | `parameters { choice(...) }` → `params.NAME` |
| Условие | `when { branch 'main' }` / `when { expression { ... } }` |
| По результату | `post { always/success/failure/unstable/changed/cleanup }` |
| Отчёт о тестах | `junit 'reports/**/*.xml'` |
| Артефакты | `archiveArtifacts artifacts: 'dist/**'` |
| Передать файлы между стадиями | `stash` / `unstash` |
| Ручное подтверждение | `input message: '...', submitter: '...'` |
| Не выполнять параллельно | `options { disableConcurrentBuilds() }` + `lock()` |
| Таймаут | `options { timeout(time: 30, unit: 'MINUTES') }` |
| Чистый workspace | `post { always { cleanWs() } }` |
| Запуск другой джобы | `build job: 'name', parameters: [...]` |

---

## 🧠 Что запомнить

1. Декларативный пайплайн = `pipeline { agent + stages + steps }`, остальное — опционально.
2. `Jenkinsfile` живёт в репозитории: пайплайн как код, с ревью и историей.
3. `agent { docker { ... } }` — лучший способ получить чистое окружение на каждую сборку.
4. Секреты — только Credentials; `credentials()` для простых случаев, `withCredentials`
   для точечного доступа.
5. Двойные кавычки в `sh "... ${SECRET}"` подставляют секрет в текст команды — утечка.
6. `post` выполняется по результату: `always`, `success`, `failure`, `unstable`, `cleanup`.
7. `cleanWs()` обязателен там, где агенты статические: workspace переиспользуется.
8. `parameters` дают параметризованные сборки; первая сборка после их добавления —
   всегда с дефолтами.
9. `junit` и `archiveArtifacts` — отчёты и артефакты, аналог `artifacts:reports` в GitLab.
10. `stash`/`unstash` передают файлы между стадиями и агентами.
11. Webhook вместо `pollSCM`, где возможно; в закрытых контурах — осознанный компромисс.
12. Деплойные пайплайны защищай `disableConcurrentBuilds()` + `lock(resource:)` + `input`.

---

## Задачи

> Лаба: Jenkins из темы 10 + репозиторий приложения с `Jenkinsfile` в корне.
> Создай джобу типа Pipeline → Pipeline script from SCM → укажи свой репозиторий.

---

### Блок A. Теория

**A1.** Из каких обязательных блоков состоит декларативный пайплайн?

<details><summary>Ответ</summary>

`pipeline`, внутри него `agent` и `stages`, внутри `stages` — минимум один `stage`
с блоком `steps`.

</details>

**A2.** Какие необязательные блоки бывают и за что отвечает каждый?

<details><summary>Ответ</summary>

`options` (таймауты, хранение сборок, запрет параллельных запусков, timestamps),
`parameters` (параметры запуска), `environment` (переменные и креды), `triggers`
(cron/pollSCM/вебхуки), `tools` (автоустановка JDK/Maven/Node), `post` (действия
по результату), `when` (на уровне стадии — условия выполнения).

</details>

**A3.** Что делает `agent none` и зачем он нужен?

<details><summary>Ответ</summary>

Не выделять агента на уровне всего пайплайна: агент указывается в каждой стадии.
Нужно, чтобы длинные ожидания (`input`) не держали executor занятым.

</details>

**A4.** Как запустить стадию в контейнере? Что даёт `reuseNode true`?

<details><summary>Ответ</summary>

`agent { docker { image '...' } }`. `reuseNode true` заставляет запустить контейнер
на том же агенте и в том же workspace, что и остальной пайплайн, — иначе стадия может
уехать на другой узел, и файлы/workspace не совпадут.

</details>

**A5.** Что делает `options { disableConcurrentBuilds() }` и чем это отличается от `lock()`?

<details><summary>Ответ</summary>

`disableConcurrentBuilds()` запрещает параллельные сборки **этой джобы**;
`lock(resource: 'x')` (Lockable Resources) сериализует доступ к **общему ресурсу**
между любыми джобами — например, к стенду прода, который деплоят несколько пайплайнов.

</details>

**A6.** Где в Jenkins хранятся секреты и какие типы credentials бывают?

<details><summary>Ответ</summary>

В Credentials (Manage Jenkins → Credentials), с областью видимости System/Global
или на уровне папки. Типы: Secret text, Username with password, SSH Username with private
key, Secret file, Certificate.

</details>

**A7.** Что произойдёт при `environment { CREDS = credentials('my-userpass') }`?
Какие переменные появятся?

<details><summary>Ответ</summary>

Появятся три переменные: `CREDS` (в формате `user:password`), `CREDS_USR`
и `CREDS_PSW`. Для Secret text — одна переменная со значением.

</details>

**A8.** Чем `withCredentials` лучше объявления кредов в `environment`?

<details><summary>Ответ</summary>

`withCredentials` ограничивает область и время жизни секрета конкретным блоком
шагов, а не всем пайплайном; удобнее для нескольких разных кредов и разных стадий,
меньше шансов случайно «протащить» секрет в посторонние шаги.

</details>

**A9.** Почему `sh "deploy --token ${TOKEN}"` опасно, а `sh 'deploy --token "$TOKEN"'` — нет?

<details><summary>Ответ</summary>

В двойных кавычках Groovy подставляет значение **в текст команды** ещё до запуска:
секрет попадает в лог (если включён вывод команды), в список процессов и в историю.
В одинарных кавычках строка уходит в shell как есть, а `$TOKEN` раскрывается уже внутри
shell из переменной окружения, которую Jenkins маскирует.

</details>

**A10.** Какие типы параметров бывают? Как к ним обращаться?

<details><summary>Ответ</summary>

`string`, `text`, `booleanParam`, `choice`, `password`, `file` (и расширения
плагинами). Обращение — `params.NAME`.

</details>

**A11.** Почему после добавления `parameters` первая сборка идёт без формы параметров?

<details><summary>Ответ</summary>

Параметры регистрируются в конфигурации джобы в момент выполнения пайплайна:
первая сборка ещё «не знает» о них и идёт со значениями по умолчанию; форма появляется
для последующих запусков.

</details>

**A12.** Перечисли секции `post` и порядок их выполнения.

<details><summary>Ответ</summary>

`always`, `success`, `failure`, `unstable`, `changed`, `fixed`, `regression`,
`aborted`, `cleanup`. Порядок: сначала `always`, затем подходящие по результату,
в самом конце `cleanup`.

</details>

**A13.** Чем `junit` отличается от `archiveArtifacts`?

<details><summary>Ответ</summary>

`junit` парсит XML-отчёты тестов и показывает их в UI (влияя на статус UNSTABLE);
`archiveArtifacts` сохраняет файлы как артефакты сборки для скачивания.

</details>

**A14.** Что делают `stash`/`unstash` и когда они нужны?

<details><summary>Ответ</summary>

Сохраняют и восстанавливают набор файлов между стадиями (в том числе на разных
агентах) в рамках одной сборки. Нужны, когда стадии выполняются в разных окружениях,
а результат сборки надо передать дальше. Для больших объёмов лучше внешнее хранилище.

</details>

**A15.** Как получить вывод команды в переменную? Как получить код возврата, не роняя сборку?

<details><summary>Ответ</summary>

`def out = sh(script: 'cmd', returnStdout: true).trim()` — вывод;
`def code = sh(script: 'cmd', returnStatus: true)` — код возврата без падения сборки.

</details>

**A16.** Зачем нужен блок `script { }` внутри декларативного пайплайна?

<details><summary>Ответ</summary>

Декларативный синтаксис ограничен; `script { }` позволяет выполнить произвольный
Groovy (циклы, условия, вычисления, работа с объектами) внутри стадии.

</details>

**A17.** Как настроить запуск по вебхуку от GitLab? Опиши шаги с обеих сторон.

<details><summary>Ответ</summary>

В Jenkins: установить плагин GitLab, в джобе включить триггер «Build when a change
is pushed to GitLab», получить URL и сгенерировать secret token. В GitLab: Settings →
Webhooks → добавить URL и токен, выбрать события (Push, Merge request), проверить
кнопкой Test. Jenkins должен быть сетево доступен для GitLab.

</details>

**A18.** Когда оправдан `pollSCM` вместо вебхука?

<details><summary>Ответ</summary>

Когда Jenkins недоступен извне (закрытый контур, нет публичного адреса)
или нет прав настраивать вебхуки в репозитории. Цена — задержка и постоянная нагрузка
опросами; частоту подбирают через `H/5`-подобные выражения.

</details>

**A19.** Назови восемь встроенных переменных `env` и что они содержат.

<details><summary>Ответ</summary>

`BUILD_NUMBER`, `BUILD_URL`, `JOB_NAME`, `NODE_NAME`, `WORKSPACE`, `GIT_COMMIT`,
`GIT_BRANCH`, `BRANCH_NAME` (multibranch), `CHANGE_ID` (PR/MR), `BUILD_TAG`.

</details>

**A20.** Как в Jenkins сделать аналог `when: manual` из GitLab CI?

<details><summary>Ответ</summary>

Шаг `input` (с `submitter`, `ok`, таймаутом через `options { timeout }`) —
пайплайн останавливается и ждёт подтверждения человека.

</details>

---

### Блок B. «Что сделает этот Jenkinsfile»

```groovy
// B1
pipeline {
    agent any
    stages {
        stage('A') { steps { sh 'echo A > f.txt' } }
        stage('B') { steps { sh 'cat f.txt' } }
    }
}
```
Вопрос: сработает ли `cat`? А если стадии выполнятся на разных агентах?

<details><summary>Ответ</summary>

На одном агенте `cat` сработает: стадии используют один workspace.
На разных агентах файла не будет — нужны `stash`/`unstash` или общее хранилище.

</details>

```groovy
// B2
pipeline {
    agent any
    environment { TOKEN = credentials('api-token') }
    stages {
        stage('Deploy') { steps { sh "curl -H 'Auth: ${TOKEN}' https://api" } }
    }
}
```

<details><summary>Ответ</summary>

Утечка: значение подставляется в текст команды средствами Groovy, попадает
в лог и в список процессов. Правильно — одинарные кавычки и `"$TOKEN"` внутри shell.

</details>

```groovy
// B3
pipeline {
    agent any
    stages {
        stage('Test') { steps { sh 'pytest || true' } }
    }
    post { always { junit 'reports/*.xml' } }
}
```

<details><summary>Ответ</summary>

Тесты никогда не уронят стадию из-за `|| true`; статус сборки может стать
UNSTABLE только благодаря шагу `junit` (если отчёт содержит падения). Лучше убрать
`|| true` и оставить `junit` в `post { always }`.

</details>

```groovy
// B4
pipeline {
    agent none
    stages {
        stage('Approve') { steps { input 'Деплоить?' } }
        stage('Deploy')  { agent { label 'linux' }; steps { sh './deploy.sh' } }
    }
}
```
Вопрос: почему `agent none` здесь важен?

<details><summary>Ответ</summary>

Без `agent none` executor был бы занят всё время ожидания `input` —
а это может быть часы. С `agent none` агент выделяется только стадии деплоя.

</details>

```groovy
// B5
pipeline {
    agent any
    stages {
        stage('X') {
            steps {
                script { def v = sh(script: 'date +%s', returnStdout: true) }
            }
        }
        stage('Y') { steps { echo "${v}" } }
    }
}
```

<details><summary>Ответ</summary>

Ошибка: `def v` — локальная переменная внутри `script`, в следующей стадии
её нет. Нужно `env.V = ...` (строка) или объявить переменную на уровне пайплайна.

</details>

```groovy
// B6
pipeline {
    agent any
    options { timeout(time: 5, unit: 'MINUTES') }
    stages { stage('Long') { steps { sh 'sleep 600' } } }
}
```

<details><summary>Ответ</summary>

Через 5 минут сборка будет прервана по таймауту со статусом ABORTED.

</details>

---

### Блок C. Практика

#### C1. 🔑 Jenkinsfile для своего приложения (главное задание темы)

Напиши `Jenkinsfile` со стадиями:
1. **Checkout** — `checkout scm`, вычислить короткий SHA в `env.IMAGE_TAG`.
2. **Lint** — в контейнере с нужным рантаймом.
3. **Test** — тесты + `junit` отчёт в `post`.
4. **Build** — сборка Docker-образа с тегом по SHA.
5. **Push** — пуш в registry с кредами из Credentials.
6. **Deploy** — SSH-деплой, с `lock` и проверкой `/health`.
Плюс `options` (timeout, buildDiscarder, disableConcurrentBuilds) и `post` с `cleanWs()`.

<details><summary>Ответ</summary>

Критерии приёмки: пайплайн зелёный; в логе не видно секретов; образ с тегом
по SHA в registry; отчёт о тестах виден в UI; `/health` проверяется после деплоя;
workspace очищается.

</details>

#### C2. Credentials двумя способами
Заведи креды `registry-creds` (username/password) и используй их сначала через
`environment { ... credentials(...) }`, затем через `withCredentials`.
Проверь, как значение выглядит в логе. Попробуй «случайно» вывести его двойными кавычками
(с тестовым значением!) и зафиксируй результат.

<details><summary>Ответ</summary>

Ожидаемо: в логе `****` вместо значения при корректном использовании,
и видимое значение при подстановке через Groovy-интерполяцию — наглядная иллюстрация,
почему двойные кавычки опасны.

</details>

#### C3. Параметры
Сделай сборку параметризованной: `ENVIRONMENT` (choice), `RUN_TESTS` (boolean),
`IMAGE_TAG` (string). Пусть стадия Test пропускается при `RUN_TESTS = false`,
а Deploy использует выбранное окружение.

<details><summary>Ответ</summary>

Проверка: при `RUN_TESTS = false` стадия Test отображается как пропущенная
(`when` не выполнен), деплой идёт в выбранное окружение.

</details>

#### C4. `post` во всех вариантах
Сделай джобу, которая по параметру завершается успехом, падением или UNSTABLE,
и покажи, какие блоки `post` срабатывают в каждом случае. Зафиксируй в таблице.

<details><summary>Ответ</summary>

Ожидаемо: `always` — всегда; `success`/`failure`/`unstable` — по результату;
`changed` — когда результат отличается от предыдущей сборки; `cleanup` — последним.

</details>

#### C5. Чистый workspace
Сравни поведение пайплайна с `cleanWs()` и без него (создавай файл с именем по номеру
сборки). Затем переведи стадию на `agent { docker { ... } }` и проверь ещё раз.

<details><summary>Ответ</summary>

Без `cleanWs()` файлы копятся; с ним workspace чист; в docker-агенте окружение
изолировано, но сам workspace может сохраняться на хосте — поэтому `cleanWs()` полезен
в обоих случаях.

</details>

#### C6. stash/unstash
Собери артефакт в одной стадии, передай его в другую через `stash`/`unstash`.
Затем заархивируй его через `archiveArtifacts` и скачай из UI.

<details><summary>Ответ</summary>

`stash name: 'dist', includes: 'dist/**'` → `unstash 'dist'`;
`archiveArtifacts artifacts: 'dist/**', fingerprint: true` даёт ссылку на скачивание.

</details>

#### C7. Webhook
Настрой запуск пайплайна по пушу из GitLab/GitHub. Проверь Test-кнопкой вебхука.
Если Jenkins недоступен извне — опиши схему, которую применил бы (reverse proxy,
туннель, self-hosted runner для доставки события) и включи `pollSCM`.

<details><summary>Ответ</summary>

Критерий: пуш в репозиторий автоматически запускает сборку, в логе видно
«Started by GitLab push». При недоступности Jenkins описанная схема — обратный прокси
с публичным адресом, ограниченный по IP/токену, либо опрос SCM.

</details>

#### C8. Ручное подтверждение
Добавь стадию `input` с `submitter` и таймаутом. Проверь, что происходит при истечении
таймаута, и убедись, что агент не занят во время ожидания (`agent none`).

<details><summary>Ответ</summary>

Ожидаемо: по истечении таймаута сборка становится ABORTED; с `agent none`
во время ожидания executor не занят.

</details>

#### C9. Сравнение с GitLab CI
Возьми свой `.gitlab-ci.yml` из темы 06 и перепиши его в `Jenkinsfile` один в один.
Выпиши, что оказалось проще, а что сложнее.

<details><summary>Ответ</summary>

Типичные выводы: в Jenkins гибче логика (Groovy) и удобнее `input`,
но многословнее и требует плагинов; в GitLab CI проще правила запуска, артефакты
и переменные, и нет обслуживания сервера.

</details>

---

### Блок D. Инциденты

**D1.** Токен из credentials оказался в консольном выводе. Как именно это могло произойти
(три способа) и что сделать?

<details><summary>Ответ</summary>

(1) Интерполяция Groovy в двойных кавычках; (2) `set -x`/`sh -x` вместе
с подстановкой; (3) вывод окружения (`env`, `printenv`) или конфигов, содержащих секрет;
(4) секрет преобразован (base64) и маскирование не сработало. Действия: ротация секрета,
удаление лога сборки, аудит доступов, исправление пайплайна.

</details>

**D2.** Пайплайн падает на `No such DSL method 'junit'`. Причина?

<details><summary>Ответ</summary>

Не установлен плагин, предоставляющий шаг (JUnit plugin). В Jenkins шаги приходят
из плагинов — отсюда и класс ошибок `No such DSL method`.

</details>

**D3.** Пайплайн висит сутки на стадии `input`, executor занят, очередь растёт. Решение.

<details><summary>Ответ</summary>

Вынести ожидание из-под агента (`agent none` + агент на стадиях), поставить
таймаут (`options { timeout(...) }` на стадию), ограничить `submitter`, а для долгих
согласований использовать отдельную джобу/внешнюю систему аппрувов.

</details>

**D4.** Сборка проходит, хотя тесты падают. Что проверить в `Jenkinsfile`?

<details><summary>Ответ</summary>

Наличие `|| true`, подавление кода возврата, отсутствие шага `junit`,
`catchError`/`allowEmptyResults` в неверном месте, тесты не запускаются вообще
(неверный путь/паттерн).

</details>

**D5.** Две параллельные сборки одной джобы деплоят на один стенд и мешают друг другу.
Что добавить?

<details><summary>Ответ</summary>

`options { disableConcurrentBuilds() }` и/или `lock(resource: 'deploy-prod')`,
плюс отдельные стенды на ветку, если нужно параллельно.

</details>

**D6.** Переменная, вычисленная в `script { def x = ... }`, недоступна в следующей стадии.
Как правильно?

<details><summary>Ответ</summary>

`def` создаёт локальную переменную внутри блока. Нужно писать в `env`
(`env.IMAGE_TAG = ...`) или объявлять переменную вне `script` на уровне пайплайна
(в `environment` или как поле через `script` в первой стадии).

</details>

**D7.** Деплойная стадия падает на `Host key verification failed`. Как решить правильно
(и почему не `StrictHostKeyChecking=no`)?

<details><summary>Ответ</summary>

Правильно — заранее положить ключ хоста в `known_hosts` (через `ssh-keyscan`
при подготовке агента или из Credentials/файла). `StrictHostKeyChecking=no` отключает
защиту от MITM, а через эту сессию передаются секреты и команды деплоя.

</details>

**D8.** Сборка идёт 40 минут, потому что каждый раз ставит зависимости заново.
Что сделать в Jenkins (три варианта)?

<details><summary>Ответ</summary>

(1) Кэш каталога пакетов через volume в docker-агенте (`args '-v ...'`);
(2) собственный образ агента с предустановленными зависимостями;
(3) `stash`/внешний кэш артефактов; (4) не переустанавливать, если lock-файл не менялся.

</details>

**D9.** После обновления пайплайна параметры «не применяются»: сборка идёт со старыми
значениями. Почему?

<details><summary>Ответ</summary>

Изменения `parameters` применяются после того, как пайплайн с ними выполнится:
первая сборка регистрирует новые параметры и идёт с дефолтами.

</details>

**D10.** `Jenkinsfile` разросся до 400 строк, в нём 6 почти одинаковых стадий деплоя.
Что с этим делать (предвосхищая тему 12)?

<details><summary>Ответ</summary>

Вынести повторяющееся в **Shared Library** (тема 12), параметризовать стадии,
использовать циклы/`parallel` и функции вместо копипасты; общие шаги — в `vars/*.groovy`.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое `Jenkinsfile` и чем декларативный пайплайн отличается от скриптового?

<details><summary>Ответ</summary>

Файл с описанием пайплайна в репозитории. Декларативный — структурированный синтаксис
(`pipeline { agent/stages/steps }`), проще и валидируется; скриптовый — чистый Groovy
(`node { ... }`), максимально гибкий, но сложнее в поддержке.

</details>

**2.** Назови обязательные блоки декларативного пайплайна.

<details><summary>Ответ</summary>

`pipeline`, `agent`, `stages` (с хотя бы одной `stage` и блоком `steps`).

</details>

**3.** Как хранить и использовать секреты в Jenkins?

<details><summary>Ответ</summary>

В Credentials; в пайплайне — через `environment { credentials('id') }` или
`withCredentials`; область видимости ограничивается папками и правами; в логах
значения маскируются, но выводить их нельзя.

</details>

**4.** Как сделать так, чтобы сборка шла в контейнере?

<details><summary>Ответ</summary>

`agent { docker { image '...' } }` (или Kubernetes-агент), на уровне пайплайна
или отдельной стадии.

</details>

**5.** Что такое `post` и какие блоки в нём бывают?

<details><summary>Ответ</summary>

Блок действий по результату сборки: `always`, `success`, `failure`, `unstable`,
`changed`, `aborted`, `cleanup`.

</details>

**6.** Как передать файлы между стадиями?

<details><summary>Ответ</summary>

`stash`/`unstash` внутри одной сборки; `archiveArtifacts` — для сохранения и
скачивания; большие файлы — во внешнее хранилище/registry.

</details>

**7.** Как сделать параметризованную сборку?

<details><summary>Ответ</summary>

Блок `parameters` с типами string/choice/boolean/password; обращение `params.NAME`.

</details>

**8.** Как реализовать ручное подтверждение деплоя?

<details><summary>Ответ</summary>

Шаг `input` с `submitter` и таймаутом, вынесенный из-под занятого агента.

</details>

**9.** Как не дать двум сборкам деплоить одновременно?

<details><summary>Ответ</summary>

`disableConcurrentBuilds()` и `lock(resource: ...)`.

</details>

**10.** Как настроить запуск по пушу в Git?

<details><summary>Ответ</summary>

Вебхук от GitLab/GitHub с токеном и соответствующим триггером в джобе;
при недоступности Jenkins — `pollSCM` как компромисс.

</details>

---

### 🎯 Чек-лист

- [ ] Написал `Jenkinsfile` со стадиями build/test/push/deploy
- [ ] Секреты беру из Credentials и не подставляю через двойные кавычки
- [ ] Использую `withCredentials` для точечного доступа
- [ ] Сделал параметризованную сборку и условия через `when`
- [ ] Настроил `post` с отчётами и `cleanWs()`
- [ ] Передал файлы между стадиями через `stash`/`unstash`
- [ ] Знаю, почему `agent none` важен при `input`
- [ ] Деплой защищён `disableConcurrentBuilds()` + `lock()`
- [ ] Настроил вебхук (или осознанно применил `pollSCM`)
- [ ] Понимаю разницу подходов Jenkins и GitLab CI на практике
