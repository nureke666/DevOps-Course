---
title: "07. Docker в GitLab CI и GitLab Registry"
description: "dind, rootless BuildKit, buildah, kaniko (legacy), тегирование, кэш слоёв, сканирование и деплой образа — конспект и задачи"
---

# 07. Docker в GitLab CI и GitLab Registry

> Роадмап → 4. CI/CD → Инструменты → GitLab CI → **База**:
> «Сборка и пуш Docker-образа в GitLab Registry».
> Опирается на блок [Docker, тема 05](/docker/05-registry-tags).
> **После темы ты умеешь:** собрать образ в пайплайне с privileged (dind/buildx) и без него
> (rootless BuildKit, buildah), объяснить, почему kaniko стал legacy, запушить образ
> в GitLab Registry с правильными тегами, ускорить сборку кэшем и задеплоить этот образ.

---

## 🗺️ Схема

```text:no-line-numbers
 .gitlab-ci.yml
      │
      ▼
┌──────────────┐   docker login $CI_REGISTRY  (логин/пароль = CI_REGISTRY_USER / CI_JOB_TOKEN)
│  job: build  │   docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
└──────┬───────┘   docker push  $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
       │
       ▼
┌───────────────────────────┐      registry.gitlab.com/<group>/<project>[/<image>]:<tag>
│  GitLab Container Registry│  ◄── встроен в проект, вкладка Deploy → Container Registry
└──────┬────────────────────┘
       │ docker pull (с сервера/из кластера)
       ▼
┌──────────────┐
│  dev/stg/prod│  тот же самый образ, без пересборки
└──────────────┘
```

---

## 1. Переменные registry, которые GitLab даёт бесплатно

```bash
$CI_REGISTRY            # registry.gitlab.com
$CI_REGISTRY_IMAGE      # registry.gitlab.com/group/project — адрес образа проекта
$CI_REGISTRY_USER       # технический пользователь для логина
$CI_REGISTRY_PASSWORD   # = $CI_JOB_TOKEN, живёт только пока идёт джоба
$CI_JOB_TOKEN           # токен джобы: доступ к registry и API проекта
$CI_DEPENDENCY_PROXY_SERVER  # прокси для образов Docker Hub (обход rate limit)
```

```yaml
before_script:
  - echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
```
> Никаких личных токенов для своего же registry не нужно. Для **чужого** registry
> (Docker Hub, ECR) заводим отдельные переменные (masked+protected) или Deploy Token.

---

## 2. Способ 1: Docker-in-Docker (dind)

```yaml
build:
  stage: build
  image: docker:29
  services:
    - name: docker:29-dind
      alias: docker
  variables:
    DOCKER_HOST: tcp://docker:2376
    DOCKER_TLS_CERTDIR: "/certs"
    DOCKER_TLS_VERIFY: 1
    DOCKER_CERT_PATH: "/certs/client"
  before_script:
    - echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
  script:
    - docker build
        --build-arg APP_VERSION="$CI_COMMIT_SHORT_SHA"
        -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" .
    - docker push "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
```

**Как это работает:** рядом с контейнером джобы поднимается **второй контейнер** с докер-демоном
(`docker:dind`), а клиент из джобы ходит к нему по сети (`DOCKER_HOST=tcp://docker:2376`).

| Плюсы | Минусы |
|-------|--------|
| Полноценный docker, всё работает как локально | Раннеру нужен `privileged = true` — это доступ к ядру хоста |
| Изоляция между джобами | Холодный демон: нет кэша слоёв между запусками (нужен `--cache-from`) |
| Можно поднимать контейнеры для тестов | Медленнее, требует ресурсов |

Регистрация раннера под dind (тема 09): в `config.toml` → `[runners.docker] privileged = true`.

> ⚠️ `privileged` = фактически root на хосте раннера. Такой раннер нельзя давать
> недоверенным проектам. Для shared-инфраструктуры и Kubernetes — сборка без демона:
> rootless BuildKit (§3) или buildah (§4).

---

## 3. Способ 2: rootless BuildKit (без докер-демона и без privileged) ⭐

```yaml
build:
  stage: build
  image:
    name: moby/buildkit:v0.33.0-rootless        # = moby/buildkit:rootless, но с пином версии
    entrypoint: [""]                            # ⚠️ обязательно, иначе вместо script стартует buildkitd
  variables:
    BUILDKITD_FLAGS: --oci-worker-no-process-sandbox   # rootless в непривилегированном контейнере/поде
  before_script:
    - mkdir -p ~/.docker
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > ~/.docker/config.json
  script:
    - buildctl-daemonless.sh build
        --frontend dockerfile.v0
        --local context=.
        --local dockerfile=.
        --opt build-arg:APP_VERSION="$CI_COMMIT_SHORT_SHA"
        --import-cache "type=registry,ref=$CI_REGISTRY_IMAGE:buildcache"
        --export-cache "type=registry,ref=$CI_REGISTRY_IMAGE:buildcache,mode=max"
        --output "type=image,name=$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA,push=true"
```

**Как это работает:** `buildctl-daemonless.sh` прямо внутри контейнера джобы поднимает `buildkitd`
под `rootlesskit` (user namespace: root внутри, обычный uid 1000 снаружи), отдаёт ему сборку
через `buildctl` и гасит демон в конце. Докер-демона нет вовсе, образ пушится прямо из BuildKit
(`push=true`), логин — через обычный `~/.docker/config.json`. Движок тот же, что внутри
`docker build`/`buildx`: параллельные стадии, `RUN --mount=type=cache`/`type=secret`, мультиарх
(`--opt platform=linux/amd64,linux/arm64`), кэш в registry.

| Флаг `buildctl` | Что значит | Аналог в `docker build` |
|-----------------|-----------|-------------------------|
| `--frontend dockerfile.v0` | Собирать по Dockerfile | — (по умолчанию) |
| `--local context=.` | Каталог контекста сборки | `.` в конце команды |
| `--local dockerfile=.` | **Каталог**, где лежит `Dockerfile` (не путь к файлу!) | — |
| `--opt filename=Dockerfile.prod` | Другое имя Dockerfile | `-f Dockerfile.prod` |
| `--opt build-arg:K=V` | Аргумент сборки | `--build-arg K=V` |
| `--opt target=prod` | Стадия multi-stage | `--target prod` |
| `--output type=image,name=…,push=true` | Имя образа + пуш сразу | `-t …` + `docker push` |
| `type=image,\"name=img:sha,img:main\",push=true` | Несколько тегов за один прогон (кавычки должен увидеть buildctl, а не шелл — экранируй) | несколько `-t` |
| `--export-cache` / `--import-cache type=registry,ref=…` | Кэш слоёв в registry; `mode=max` — и промежуточные стадии | `--cache-to` / `--cache-from` |

> ⚠️ **Честно про «rootless»:** privileged не нужен, но «совсем без прав», как когда-то kaniko,
> это не работает. `rootlesskit` создаёт user namespace и делает mount'ы, а дефолтные
> seccomp/AppArmor это режут:
> - **gitlab.com (hosted runners)** — работает из коробки (они и так privileged);
> - **свой docker-раннер без privileged** — ошибка
>   `[rootlesskit:parent] error: failed to start the child: fork/exec /proc/self/exe: operation not permitted`;
>   лечится `security_opt` в `[runners.docker]` (тема 09) — лучше кастомным seccomp-профилем,
>   разрешающим только нужные syscalls, чем `seccomp:unconfined` + `apparmor:unconfined`;
> - **Kubernetes-раннер** — `--oci-worker-no-process-sandbox` (RUN-шаги делят PID namespace
>   с `buildkitd`; в одноразовом поде это приемлемо) плюс `seccompProfile` и AppArmor `Unconfined`
>   для контейнера сборки.
>
> Это послабление изоляции, но несравнимо меньшее, чем `privileged`: нет доступа к устройствам
> и ядру хоста, root в контейнере — не root на хосте.

| Плюсы | Минусы |
|-------|--------|
| Не нужен privileged и докер-демон | На своих раннерах нужны послабления seccomp/AppArmor |
| Тот же движок, что `docker build`: кэш-маунты, секреты, мультиарх | Нет `docker run`/compose внутри джобы |
| Самый быстрый из daemonless-вариантов, кэш в registry | Непривычный синтаксис `buildctl` (таблица выше) |
| Активно развивается (moby/buildkit) — прямая замена kaniko | Демон стартует в каждой джобе с холодным локальным кэшем (спасает registry-кэш) |

> 💡 Вариант для большого кластера — не поднимать демон в каждой джобе, а держать **отдельный
> сервис `buildkitd`** с тёплым кэшем на диске и ходить к нему `buildctl --addr tcp://buildkitd:1234 build …`
> или `docker buildx create --driver remote tcp://buildkitd:1234`. Быстрее, но это ещё один
> сервис, который надо защищать (mTLS, доступ только от раннеров).

---

## 4. Способ 3: Buildah (daemonless, Dockerfile как есть)

```yaml
build:
  stage: build
  image: quay.io/buildah/stable:v1.43.4
  variables:
    STORAGE_DRIVER: vfs          # = --storage-driver=vfs для всех команд: без overlay-маунтов и привилегий
    BUILDAH_FORMAT: docker       # манифест docker, а не OCI: иначе HEALTHCHECK/SHELL будут проигнорированы
    BUILDAH_ISOLATION: chroot    # RUN-шаги через chroot, без вложенного рантайма (в образе stable уже так)
  before_script:
    - echo "$CI_REGISTRY_PASSWORD" | buildah login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
  script:
    - buildah build
        --layers
        --cache-from "$CI_REGISTRY_IMAGE/buildah-cache"
        --cache-to   "$CI_REGISTRY_IMAGE/buildah-cache"
        --build-arg APP_VERSION="$CI_COMMIT_SHORT_SHA"
        -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" .
    - buildah push "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
```

**Как это работает:** buildah — утилита из семейства podman/skopeo (Red Hat), демона у неё нет:
она сама читает Dockerfile, сама выполняет RUN-шаги (в chroot) и сама пушит в registry.
`buildah build` (он же старый `buildah bud`) принимает почти те же флаги, что `docker build`
(`-t`, `-f`, `--build-arg`, `--target`), поэтому переезд с dind — это замена пары слов.
Кэш в registry: `--layers` + `--cache-from/--cache-to` (указывается **репозиторий**, без тега).

`vfs` — самый простой драйвер хранения: не нужны overlay-маунты (а значит, и привилегии),
но каждый слой копируется целиком — на больших образах медленно и много места на диске.

> ⚠️ GitLab предлагает buildah как запасной вариант, когда настройки безопасности раннера
> менять нельзя. Но и он в rootless-режиме на закрученном раннере может упасть с
> `Error during unshare(CLONE_NEWUSER): Operation not permitted` — лечится тем же
> послаблением seccomp/AppArmor, что и у BuildKit (§3).

| Плюсы | Минусы |
|-------|--------|
| Нет демона, не нужен privileged | `vfs` медленный и прожорлив по диску — обычно медленнее BuildKit |
| CLI почти как у docker, Dockerfile без изменений | Нет `docker run`/compose внутри джобы |
| Активно поддерживается (containers/buildah), стандарт в OpenShift | На закрученных раннерах тоже нужны послабления seccomp/AppArmor |
| Умеет собирать и без Dockerfile — скриптом (`buildah from/run/commit`) | |

---

## 5. Способ 4: `docker buildx` поверх dind (+ кэш в registry)

```yaml
build:
  stage: build
  image: docker:29
  services: [docker:29-dind]
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
    BUILDKIT_PROGRESS: plain
  before_script:
    - echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
    - docker buildx create --use --name ci
  script:
    - docker buildx build
        --cache-from "type=registry,ref=$CI_REGISTRY_IMAGE:buildcache"
        --cache-to   "type=registry,ref=$CI_REGISTRY_IMAGE:buildcache,mode=max"
        --tag "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
        --push .
```

Самый привычный быстрый вариант при частых сборках: кэш слоёв лежит в registry и переиспользуется
любым раннером. `--push` пушит сразу из билдера (без промежуточного `docker push`).
Так же собираются мультиархитектурные образы: `--platform linux/amd64,linux/arm64`.
Это тот же BuildKit, что в §3, но **через dind** — значит, снова `privileged`.

---

## 6. Legacy: Kaniko (архивирован в 2025)

> 🪦 **Статус:** Google заархивировал `GoogleContainerTools/kaniko` **3 июня 2025** (репозиторий
> read-only), образ `gcr.io/kaniko-project/executor` больше не обновляется — ни фич, ни CVE-фиксов.
> Chainguard поддерживает форк `chainguard-forks/kaniko` — **только security-фиксы**, без новых
> возможностей. Готовые образы форка собирает сообщество:
> `registry.gitlab.com/gitlab-ci-utils/container-images/kaniko` (только `debug`-вариант с шеллом).

```yaml
build:kaniko:                                   # legacy — для новых пайплайнов бери §3/§4
  stage: build
  image:
    name: registry.gitlab.com/gitlab-ci-utils/container-images/kaniko:v1.25.19-debug  # форк Chainguard, не gcr.io
    entrypoint: [""]
  script:
    - mkdir -p /kaniko/.docker
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"username\":\"$CI_REGISTRY_USER\",\"password\":\"$CI_REGISTRY_PASSWORD\"}}}" > /kaniko/.docker/config.json
    - /kaniko/executor
        --context "$CI_PROJECT_DIR"
        --dockerfile "$CI_PROJECT_DIR/Dockerfile"
        --destination "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
        --cache=true
        --cache-repo "$CI_REGISTRY_IMAGE/cache"
```

Kaniko выполнял инструкции Dockerfile **в юзерспейсе** своего контейнера (снапшот ФС после
каждого шага), без демона и **вообще без привилегий и послаблений seccomp** — поэтому много лет
был дефолтом для k8s-раннеров. Ровно поэтому его не заменить «один в один»: у rootless BuildKit
и buildah цена чуть выше (см. оговорки в §3–4).

**Встретил kaniko в проекте — что делать:**
1. Сразу — заменить `gcr.io/kaniko-project/executor` на образ форка (пример выше): хотя бы security-фиксы.
2. Планово — мигрировать на rootless BuildKit или buildah. Соответствие флагов:

| kaniko | rootless BuildKit (`buildctl`) | buildah |
|--------|-------------------------------|---------|
| `--context DIR` | `--local context=DIR` | `buildah build … DIR` |
| `--dockerfile F` | `--local dockerfile=<каталог>` + `--opt filename=F` | `-f F` |
| `--destination IMG` | `--output type=image,name=IMG,push=true` | `-t IMG` + `buildah push IMG` |
| `--build-arg K=V` | `--opt build-arg:K=V` | `--build-arg K=V` |
| `--target T` | `--opt target=T` | `--target T` |
| `--cache=true --cache-repo R` | `--export-cache`/`--import-cache type=registry,ref=R` | `--layers --cache-to R --cache-from R` |
| `/kaniko/.docker/config.json` | `~/.docker/config.json` | `buildah login` |

---

## 7. Что выбрать: сравнение

| | dind (+ buildx) | rootless BuildKit | buildah | kaniko (legacy) |
|---|---|---|---|---|
| **Привилегии раннера** | `privileged = true` ≈ root на хосте | Без privileged, но нужны user namespaces: послабленные seccomp/AppArmor (в k8s — `Unconfined` + `--oci-worker-no-process-sandbox`) | Без privileged (`vfs` + `chroot`); на закрученных раннерах — те же послабления | Без privileged и без послаблений |
| **Демон** | `dockerd` в сервисе | `buildkitd` живёт внутри джобы | Нет | Нет |
| **Кэш слоёв** | `--cache-from`; buildx — `--cache-to/--cache-from type=registry` | `--export-cache/--import-cache type=registry`, `mode=max` | `--layers --cache-to/--cache-from` (репозиторий) | `--cache=true --cache-repo` |
| **Скорость** | С buildx и registry-кэшем — быстро; холодный демон без кэша — медленно | ⭐ Быстро: движок BuildKit, параллельные стадии | Средне; `vfs` тормозит на больших образах | Медленнее BuildKit (снапшот ФС на каждый шаг) |
| **`docker run` в джобе** | Да | Нет | Нет | Нет |
| **Статус** | Активно (Docker Engine 29.x) | Активно (moby/buildkit) | Активно (containers/buildah) | Upstream архивирован 03.06.2025; форк Chainguard — только security-фиксы |

**Короткое правило:**
- В джобе нужен полноценный docker (`docker run`, compose в тестах) и есть свой доверенный раннер →
  **dind** (+ buildx ради кэша).
- Kubernetes-раннер или shared-инфраструктура, privileged запрещён → **rootless BuildKit**;
  если он не взлетает на ограничениях вашего раннера или вы живёте в экосистеме Red Hat/OpenShift →
  **buildah**.
- Увидел kaniko → это задача на миграцию, а не образец для нового пайплайна.

---

## 8. Тегирование: что и когда

```yaml
.tags-script: &tags-script
  - IMAGE="$CI_REGISTRY_IMAGE"
  - SHA_TAG="$IMAGE:$CI_COMMIT_SHORT_SHA"          # всегда
  - BRANCH_TAG="$IMAGE:$CI_COMMIT_REF_SLUG"        # main, feature-x
  - |
    if [ -n "$CI_COMMIT_TAG" ]; then
      VERSION_TAG="$IMAGE:${CI_COMMIT_TAG#v}"      # 1.4.2 из тега v1.4.2
    fi
```

| Тег | Когда ставим | Зачем |
|-----|--------------|-------|
| `:<short-sha>` | **Всегда** | Иммутабельный идентификатор для деплоя и отката |
| `:<branch-slug>` | На каждой сборке ветки | Удобно для dev-стендов |
| `:<semver>` | На пуш git-тега | Релизы, changelog, внешние потребители |
| `:latest` | Опционально на main | Только для людей; **в деплое не использовать** |

**Правило деплоя:** окружения получают образ по SHA. Плавающие теги — навигация,
а не источник правды.

---

## 9. Сборка образа для тестов + прогон тестов в контейнере

```yaml
build:test-image:
  stage: build
  image: docker:29
  services: [docker:29-dind]
  variables: { DOCKER_TLS_CERTDIR: "/certs" }
  script:
    - echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
    - docker build --target test -t "$CI_REGISTRY_IMAGE:test-$CI_COMMIT_SHORT_SHA" .
    - docker run --rm "$CI_REGISTRY_IMAGE:test-$CI_COMMIT_SHORT_SHA" pytest -q
    - docker build --target prod -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" .
    - docker push "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
```
Multi-stage `--target` (см. [Docker, тема 04](/docker/04-build-cache-multistage))
позволяет собрать «тестовый» слой и прод-образ из одного Dockerfile — без второго файла.
Этот приём держится на `docker run`, то есть на dind. С rootless BuildKit/buildah собери
`--target test` и запушь его, а тесты гоняй **отдельной джобой** с `image: "$CI_REGISTRY_IMAGE:test-$CI_COMMIT_SHORT_SHA"`.

---

## 10. Тесты с зависимостями через `services`

```yaml
integration:
  stage: test
  image: python:3.12-slim
  services:
    - name: postgres:16-alpine
      alias: db
    - name: redis:7-alpine
      alias: cache
  variables:
    POSTGRES_DB: app
    POSTGRES_USER: app
    POSTGRES_PASSWORD: app
    DATABASE_URL: "postgresql://app:app@db:5432/app"
    REDIS_URL: "redis://cache:6379/0"
  before_script:
    - pip install -r requirements.txt -r requirements-dev.txt
    - until pg_isready -h db -U app; do sleep 1; done      # дождаться готовности!
  script:
    - alembic upgrade head
    - pytest tests/integration -q
```
Сервисы доступны по alias как по DNS-имени. Готовность нужно **ждать явно** —
контейнер запущен ≠ БД принимает соединения (та же логика, что `depends_on` в compose).

---

## 11. Сканирование образа перед пушем в прод

```yaml
scan:image:
  stage: scan
  image:
    name: aquasec/trivy:0.74.0
    entrypoint: [""]
  variables:
    TRIVY_NO_PROGRESS: "true"
    TRIVY_CACHE_DIR: ".trivycache/"
  script:
    - trivy image --exit-code 0 --severity HIGH "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
    - trivy image --exit-code 1 --severity CRITICAL "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
  cache:
    paths: [".trivycache/"]
```
HIGH — предупреждение, CRITICAL — блокирует пайплайн. Подробнее — тема 13.

---

## 12. Деплой образа на сервер

### Через SSH + docker compose
```yaml
deploy:staging:
  stage: deploy
  image: alpine:3.20
  before_script:
    - apk add --no-cache openssh-client curl
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - ssh-keyscan -H "$DEPLOY_HOST" >> ~/.ssh/known_hosts
  script:
    - ssh -i "$SSH_KEY" "$DEPLOY_USER@$DEPLOY_HOST" "
        echo '$CI_REGISTRY_PASSWORD' | docker login -u '$CI_REGISTRY_USER' --password-stdin $CI_REGISTRY &&
        cd /opt/app &&
        APP_IMAGE=$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA docker compose up -d --pull always &&
        docker image prune -f"
    - curl -fsS --retry 5 --retry-delay 3 "https://staging.example.com/health"
  environment:
    name: staging
    url: https://staging.example.com
```

> ⚠️ `$CI_JOB_TOKEN` живёт только во время джобы — на сервере он протухнет.
> Для постоянного доступа сервера к registry заведи **Deploy Token**
> (Settings → Repository → Deploy tokens, scope `read_registry`) и логинься им.

### Через Ansible
См. [03_pipeline_design.md](/cicd/03-pipeline-design) §5 — плейбук получает `app_image`
параметром и не знает ничего про CI.

---

## 13. Политика очистки registry

Settings → Packages and registries → Cleanup policies:

```text:no-line-numbers
Keep the most recent: 10 tags per image
Keep tags matching:   ^v\d+\.\d+\.\d+$    (релизы не удаляем)
Remove tags older than: 30 days
Remove tags matching:   .*                 (всё остальное)
```

> ⚠️ Помни: **откат возможен, только пока предыдущий образ жив**. Не удаляй теги,
> на которые ссылаются активные окружения.

---

## 14. Частые проблемы

| Ошибка | Причина и решение |
|--------|-------------------|
| `Cannot connect to the Docker daemon` | Нет `services: docker:dind` или неверный `DOCKER_HOST`; на shell-раннере — нет доступа к сокету |
| `docker: not found` | `image:` джобы без докер-клиента — нужен `image: docker:29` |
| `denied: requested access to the resource is denied` | Не выполнен `docker login`, либо имя образа не равно `$CI_REGISTRY_IMAGE`, либо нет прав |
| `error during connect: ... x509` | Рассогласование TLS: задай `DOCKER_TLS_CERTDIR: "/certs"` и cert-переменные (или отключи TLS осознанно) |
| `toomanyrequests` от Docker Hub | Лимит анонимных пуллов: используй Dependency Proxy или свой зеркальный registry |
| Каждая сборка с нуля | Нет кэша: `--cache-from`, buildx `--cache-to`, buildctl `--export-cache/--import-cache`, buildah `--layers --cache-to` |
| Образ 1.5 ГБ | Нет multi-stage/`.dockerignore` (см. блок Docker, тема 04) |
| Джоба падает только в CI | Разные архитектуры (arm64 локально, amd64 в CI) — собирай с `--platform` |
| `fork/exec /proc/self/exe: operation not permitted` / `unshare(CLONE_NEWUSER): Operation not permitted` | Rootless BuildKit/buildah упёрлись в seccomp/AppArmor раннера: `security_opt` (лучше кастомный профиль) на docker-раннере, `Unconfined` + `--oci-worker-no-process-sandbox` в k8s (§3) |
| BuildKit-джоба молчит и висит до таймаута | Не задан `entrypoint: [""]` — вместо `script` запустился долгоживущий `buildkitd` |
| `invalid local: stat .../Dockerfile: not a directory` | В `--local dockerfile=` указан файл, а нужен каталог; имя файла — через `--opt filename=` |
| `HEALTHCHECK is not supported for OCI image format` (buildah) | Задай `BUILDAH_FORMAT: docker` |

---

## 💼 Как это в DevOps

- Джоба сборки образа — самая «горячая» часть пайплайна: её оптимизируют первой
  (кэш слоёв, `.dockerignore`, multi-stage).
- Выбор dind/buildx vs rootless BuildKit/buildah — это в первую очередь вопрос **безопасности
  раннера**, а не вкуса. На собесе так и отвечай — и назови цену rootless (seccomp/AppArmor).
- Kaniko заархивирован в 2025 — типовая задача 2025–2026: перевести kaniko-джобы на форк,
  а затем на rootless BuildKit/buildah. Знать это — признак, что ты следишь за экосистемой.
- Спросят: «как передаёте образ на прод?» — правильный ответ про иммутабельный тег,
  registry и pull на целевой стороне, а не про `docker save | scp`.
- Политика очистки registry — реальная эксплуатационная задача: хранилище конечно.

---

## 📌 Шпаргалка

```yaml
# минимальная рабочая сборка и пуш
build:
  image: docker:29
  services: [docker:29-dind]
  variables: { DOCKER_TLS_CERTDIR: "/certs" }
  before_script:
    - echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
  script:
    - docker build -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" .
    - docker push "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
```

| Хочу | Как |
|------|-----|
| Собрать без privileged | rootless BuildKit: `moby/buildkit:rootless` + `buildctl-daemonless.sh build … --output type=image,name=…,push=true` |
| Без privileged, CLI как у docker | buildah: `STORAGE_DRIVER=vfs`, `buildah build -t …` + `buildah push` |
| Быстрая сборка с кэшем | buildx: `--cache-to/--cache-from type=registry`; buildctl: `--export-cache/--import-cache type=registry` |
| Остался kaniko-пайплайн | Образ форка Chainguard как временная мера → миграция по таблице из §6 |
| Тег для деплоя | `$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA` |
| Тег релиза | `${CI_COMMIT_TAG#v}` по git-тегу |
| БД для тестов | `services:` + ожидание готовности |
| Скан образа | Trivy с `--exit-code 1 --severity CRITICAL` |
| Доступ сервера к registry | Deploy Token со scope `read_registry` |
| Не забить хранилище | Cleanup policy + защита релизных тегов |
| Обойти лимиты Docker Hub | Dependency Proxy (`$CI_DEPENDENCY_PROXY_SERVER`) |

---

## 🧠 Что запомнить

1. Для своего registry всё уже есть в переменных: `CI_REGISTRY*` + `CI_JOB_TOKEN`.
2. dind требует `privileged` на раннере — мощно, но небезопасно для общих раннеров.
3. Без privileged сегодня собирают **rootless BuildKit** или **buildah**; kaniko архивирован
   в 2025 (жив лишь форк Chainguard с security-фиксами) — только legacy и миграция.
4. BuildKit (buildx через dind или rootless `buildctl`) + кэш в registry — самый быстрый вариант
   при частых сборках.
5. Тег по SHA — всегда; ветка и SemVer — как дополнительные алиасы; `latest` не для деплоя.
6. Собирай образ **один раз** и продвигай по окружениям (принцип из темы 01).
7. `services:` дают БД и кэш для интеграционных тестов, но готовность надо дожидаться.
8. Сканируй образ до прода: CRITICAL — блокирует, HIGH — предупреждает.
9. `$CI_JOB_TOKEN` короткоживущий: серверу нужен Deploy Token, а не токен джобы.
10. Без registry-кэша (`--cache-from/--cache-to`, `--export-cache/--import-cache`) каждая сборка
    начинается с нуля.
11. Политика очистки registry обязана щадить релизные теги и то, что задеплоено.
12. Ошибку `denied: ...` в 90% случаев объясняет забытый `docker login` или неверное имя образа.
13. Rootless ≠ без ограничений: BuildKit и buildah нужны user namespaces, поэтому seccomp/AppArmor
    раннера под них настраивают (лучше кастомным профилем, чем `Unconfined`) — и это всё равно
    намного безопаснее `privileged`.

---

## Задачи

> Лаба: проект с Dockerfile из блока Docker. На gitlab.com shared runners поддерживают dind —
> если используешь свой раннер, включи `privileged = true` (тема 09) или собирай без демона —
> rootless BuildKit/buildah (§3–4 конспекта).

---

### Блок A. Теория

**A1.** Какие переменные GitLab даёт для работы со своим registry? Что означает каждая?

<details><summary>Ответ</summary>

`$CI_REGISTRY` — адрес registry; `$CI_REGISTRY_IMAGE` — полный путь образа проекта;
`$CI_REGISTRY_USER` и `$CI_REGISTRY_PASSWORD` — учётные данные для `docker login`
(пароль равен токену джобы); `$CI_JOB_TOKEN` — токен для API и registry;
`$CI_DEPENDENCY_PROXY_SERVER` — адрес прокси образов.

</details>

**A2.** Что такое `$CI_JOB_TOKEN`, сколько он живёт и где его нельзя использовать?

<details><summary>Ответ</summary>

Короткоживущий токен, выданный конкретной джобе и действующий только пока она
выполняется (и отзываемый после). Его нельзя «положить» на сервер для постоянного доступа
к registry и нельзя передавать во внешние системы — для этого Deploy Token или отдельные креды.

</details>

**A3.** Как устроен Docker-in-Docker в GitLab CI? Какие два контейнера участвуют
и как они связаны?

<details><summary>Ответ</summary>

Контейнер джобы (`image: docker:29`) — это только **клиент**; рядом сервисом
поднимается контейнер `docker:dind` — полноценный **демон**. Клиент обращается к демону
по TCP (`DOCKER_HOST=tcp://docker:2376`) с TLS.

</details>

**A4.** Зачем нужны переменные `DOCKER_HOST` и `DOCKER_TLS_CERTDIR`?

<details><summary>Ответ</summary>

`DOCKER_HOST` указывает клиенту, где демон (иначе он ищет локальный сокет).
`DOCKER_TLS_CERTDIR` задаёт каталог сертификатов: dind генерирует их и разделяет с джобой
через общий volume, обеспечивая защищённое соединение (порт 2376). Без согласованных
значений будут ошибки соединения или x509.

</details>

**A5.** Почему `privileged = true` — это риск? Что именно получает джоба?

<details><summary>Ответ</summary>

`privileged` снимает большинство ограничений контейнера: доступ к устройствам,
возможность монтировать ФС, управлять ядром хоста. Практически это равно root на машине
раннера, поэтому такой раннер нельзя предоставлять недоверенным проектам —
злонамеренный `.gitlab-ci.yml` сможет получить доступ к хосту и чужим сборкам.

</details>

**A6.** Как работал kaniko, чем принципиально отличается от dind и почему в 2025 он стал legacy?

<details><summary>Ответ</summary>

Kaniko выполнял инструкции Dockerfile в юзерспейсе внутри своего контейнера
(снапшот ФС после каждого шага), формируя слои и отправляя их прямо в registry. Демон не нужен,
privileged не нужен, послабления seccomp — тоже; кэш — в registry (`--cache-repo`). В отличие
от dind, внутри джобы нет докера, поэтому `docker run`/`docker compose` там не работают.
Legacy он потому, что 3 июня 2025 Google заархивировал upstream, а `gcr.io/kaniko-project/executor`
больше не получает даже CVE-фиксов; живёт только форк Chainguard (security-фиксы, без новых фич).
Существующие джобы переводят на образ форка, а затем — на rootless BuildKit/buildah.

</details>

**A7.** Когда выбрать dind, когда rootless BuildKit, когда buildah, когда buildx? Где в этой схеме
kaniko? Дай короткое правило.

<details><summary>Ответ</summary>

Нужен полный докер (запуск контейнеров в тестах, compose) и есть свой доверенный раннер —
dind (с buildx ради кэша в registry). Раннер в Kubernetes/общая инфраструктура, privileged
запрещён — rootless BuildKit (тот же движок, что `docker build`, самый быстрый без демона);
buildah — если BuildKit не взлетает на ограничениях раннера или вы в экосистеме Red Hat/OpenShift.
Kaniko — только legacy: не выбирать для нового, существующее мигрировать.

</details>

**A8.** Как организовать кэш слоёв: в dind, в buildx, в rootless BuildKit, в buildah
(и как это делал kaniko)?

<details><summary>Ответ</summary>

dind: `docker build --cache-from <образ из registry>` (образ нужно предварительно
`docker pull`), либо buildx. buildx: `--cache-to type=registry,mode=max` и `--cache-from type=registry`.
Rootless BuildKit: `--export-cache type=registry,ref=<img>:buildcache,mode=max`
и `--import-cache type=registry,ref=<img>:buildcache`. buildah: `--layers --cache-to <repo>
--cache-from <repo>` (репозиторий без тега). kaniko (legacy): `--cache=true --cache-repo <registry>/cache`.

</details>

**A9.** Какие теги ставить образу и какой из них использовать в деплое? Почему не `latest`?

<details><summary>Ответ</summary>

Всегда `:$CI_COMMIT_SHORT_SHA`; дополнительно `:$CI_COMMIT_REF_SLUG` для ветки
и `:X.Y.Z` для релизного git-тега. В деплое — только SHA (или digest): `latest` плавающий,
из-за чего перезапуск может поднять другую версию, а откат теряет смысл.

</details>

**A10.** Как получить `1.4.2` из git-тега `v1.4.2` в шелле?

<details><summary>Ответ</summary>

`VERSION="${CI_COMMIT_TAG#v}"` — удаляет ведущий `v`.

</details>

**A11.** Что делает `services:` в джобе? Как обратиться к сервису из тестов?

<details><summary>Ответ</summary>

Поднимает дополнительные контейнеры в сети джобы. Обращение — по имени сервиса
или `alias` (`db`, `cache`) как к DNS-имени: `postgresql://app:app@db:5432/app`.

</details>

**A12.** Почему сервисам нужно явное ожидание готовности? Приведи пример для PostgreSQL.

<details><summary>Ответ</summary>

Контейнер запущен ≠ сервис принимает соединения: инициализация БД занимает секунды,
и тесты падают с `connection refused`. Пример:
`until pg_isready -h db -U app; do sleep 1; done` (с ограничением по числу попыток).

</details>

**A13.** Как прогнать тесты внутри собираемого образа, не создавая второй Dockerfile?

<details><summary>Ответ</summary>

Multi-stage Dockerfile с таргетами: `docker build --target test` собирает слой
с dev-зависимостями и тестами, `docker run --rm <test-образ> pytest` их прогоняет,
затем `--target prod` собирает финальный образ из того же файла.

</details>

**A14.** Как устроена политика очистки registry и какое правило обязательно нужно добавить?

<details><summary>Ответ</summary>

Cleanup policy в Settings → Packages and registries: сколько тегов хранить,
какие теги оставлять по регулярке, что удалять и старше какого возраста. Обязательно —
правило, защищающее релизные теги (`^v\d+\.\d+\.\d+$`) и образы, задеплоенные в окружения,
иначе пропадёт возможность отката.

</details>

**A15.** Что такое Deploy Token и зачем он нужен, если есть `$CI_JOB_TOKEN`?

<details><summary>Ответ</summary>

Deploy Token — постоянные учётные данные с ограниченным скоупом (`read_registry`,
`read_repository`), пригодные для серверов и внешних систем. `$CI_JOB_TOKEN` живёт только
в течение джобы, поэтому для сервера, который будет пуллить образы и завтра, не годится.

</details>

**A16.** Что такое Dependency Proxy и какую проблему он решает?

<details><summary>Ответ</summary>

Dependency Proxy кэширует образы Docker Hub внутри GitLab: решает проблему
rate limit для анонимных/бесплатных пуллов и ускоряет старт джоб, а также снижает
зависимость от доступности внешнего registry.

</details>

**A17.** Почему образ, собранный локально на Apple Silicon, может не запуститься на сервере,
и как это решается в CI?

<details><summary>Ответ</summary>

Локальная сборка на arm64 даёт образ под arm64, а сервер обычно amd64 —
получаем `exec format error`. Решение: собирать в CI (там amd64) или использовать
`docker buildx build --platform linux/amd64,linux/arm64` и публиковать мультиарх-манифест.

</details>

**A18.** Как работает rootless BuildKit в джобе (`buildctl-daemonless.sh`)? Зачем нужны
`entrypoint: [""]` и `--oci-worker-no-process-sandbox`? Почему «без privileged» ≠ «без прав вообще»?

<details><summary>Ответ</summary>

`buildctl-daemonless.sh` прямо в контейнере джобы запускает `buildkitd` под `rootlesskit`
(user namespace: root внутри, uid 1000 снаружи), отдаёт ему сборку через `buildctl` и гасит демон
в конце; образ пушится из BuildKit (`--output ...,push=true`). `entrypoint: [""]` нужен, потому что
ENTRYPOINT образа `moby/buildkit:rootless` запускает долгоживущий `buildkitd` — без переопределения
`script` не выполнится и джоба повиснет. `--oci-worker-no-process-sandbox` отключает отдельный PID
namespace для RUN-шагов: в непривилегированном контейнере новый `/proc` смонтировать не дадут.
«Без privileged» — да, «без прав вообще» — нет: rootlesskit нужны user namespaces и mount, поэтому
на своих раннерах ослабляют seccomp/AppArmor (кастомный профиль через `security_opt`, в k8s —
`Unconfined`). Kaniko в этом смысле был «чище» — но он заархивирован.

</details>

**A19.** Чем buildah отличается от rootless BuildKit? Зачем в CI ему задают `STORAGE_DRIVER=vfs`
и `BUILDAH_FORMAT=docker`?

<details><summary>Ответ</summary>

buildah — отдельная daemonless-утилита (семейство podman/skopeo): сама выполняет Dockerfile
(RUN — через chroot) и сама пушит; CLI близок к docker (`buildah build -t`, `-f`, `--build-arg`,
`buildah push`). BuildKit — движок самого `docker build`: быстрее, богаче кэш (`mode=max`),
кэш-маунты и секреты. `STORAGE_DRIVER=vfs` — хранилище без overlay-маунтов, работающее без
привилегий (цена — медленнее и больше места на диске). `BUILDAH_FORMAT=docker` — манифест
docker-формата: в OCI-формате buildah игнорирует `HEALTHCHECK` и `SHELL` из Dockerfile.

</details>

---

### Блок B. «Найди ошибку»

```yaml
# B1
build:
  image: docker:29
  script:
    - docker build -t myapp .
    - docker push myapp
```

<details><summary>Ответ</summary>

Нет сервиса dind (демона), нет `docker login`, имя образа не содержит адрес registry
(`myapp` попытается уйти в Docker Hub), нет иммутабельного тега. Исправление — см. шпаргалку
конспекта.

</details>

```yaml
# B2
build:
  image: docker:29
  services: [docker:29-dind]
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_REGISTRY_PASSWORD" "$CI_REGISTRY"
    - docker build -t "$CI_REGISTRY_IMAGE:latest" .
    - docker push "$CI_REGISTRY_IMAGE:latest"
```

<details><summary>Ответ</summary>

Пароль передан через `-p` — попадёт в лог/историю процессов; нужно
`--password-stdin`. Тег `latest` не годится для деплоя. Не задан `DOCKER_TLS_CERTDIR`,
что часто приводит к ошибкам TLS.

</details>

```yaml
# B3
integration:
  image: python:3.12
  services: [postgres:16]
  script:
    - pytest tests/integration
```

<details><summary>Ответ</summary>

Не заданы переменные для postgres (`POSTGRES_*`) и `DATABASE_URL`, нет alias,
нет ожидания готовности БД: тесты упадут либо на подключении, либо на аутентификации.

</details>

```yaml
# B4
deploy:
  script:
    - ssh $DEPLOY_HOST "docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY && docker pull $CI_REGISTRY_IMAGE:latest && docker restart app"
```

<details><summary>Ответ</summary>

`$CI_JOB_TOKEN` на сервере станет недействительным после завершения джобы;
пароль передан через `-p` (утечка в лог); деплой по `latest`; `docker restart` не подтянет
новый образ — нужно пересоздание контейнера (`up -d --pull always`); плюс нет проверки
здоровья после деплоя.

</details>

```yaml
# B5
build:
  image: docker:29
  services: [docker:29-dind]
  script:
    - docker build -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" .
    - docker push "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
  rules:
    - if: $CI_COMMIT_BRANCH
deploy:prod:
  script:
    - ssh prod "docker build -t app . && docker run -d app"
```

<details><summary>Ответ</summary>

Нарушен принцип build once: образ собирается в `build`, а на проде **пересобирается**
заново из исходников. В прод должен уезжать тот же образ по SHA, который прошёл тесты
и сканы.

</details>

---

### Блок C. Практика

#### C1. 🔑 Сборка и пуш в GitLab Registry (задание «База» из роадмапа)

1. Собери образ приложения в джобе `build` через dind.
2. Залогинься в `$CI_REGISTRY` предопределёнными переменными.
3. Пушни два тега: `$CI_COMMIT_SHORT_SHA` и `$CI_COMMIT_REF_SLUG`.
4. Убедись, что образ появился в Deploy → Container Registry.
5. Скачай его локально: `docker pull registry.gitlab.com/<group>/<project>:<sha>` и запусти.

<details><summary>Ответ</summary>

Критерий: образ виден в Container Registry, `docker pull` по SHA работает локально,
контейнер запускается. Если `denied` — проверь, что имя образа начинается с
`$CI_REGISTRY_IMAGE`.

</details>

#### C2. Релизный тег
Настрой правило: при пуше git-тега `vX.Y.Z` дополнительно публикуется образ с тегом `X.Y.Z`.
Проверь пушем `v0.1.0`.

<details><summary>Ответ</summary>

Правило:
```yaml
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/
```
и в скрипте `docker tag ... "$CI_REGISTRY_IMAGE:${CI_COMMIT_TAG#v}"`.

</details>

#### C3. Kaniko (legacy) — чтобы узнавать и мигрировать
Upstream kaniko архивирован в 2025, поэтому бери образ форка Chainguard
(`registry.gitlab.com/gitlab-ci-utils/container-images/kaniko:vX.Y.Z-debug`), а не `gcr.io/kaniko-project/executor`.
Собери им образ без privileged, сравни время сборки с dind, включи `--cache=true --cache-repo`
и сравни повторную сборку. Это знакомство с легаси: на работе такую джобу ты будешь не писать,
а переносить на rootless BuildKit/buildah (C11, C12).

#### C4. Buildx с кэшем в registry
Сделай третий вариант джобы — `docker buildx` с `--cache-to/--cache-from type=registry`.
Замерь: первая сборка, вторая без изменений, третья с изменением кода приложения
(но не зависимостей). Объясни разницу по времени.

<details><summary>Ответ (C3–C4)</summary>

Ожидаемо: первая сборка везде примерно одинакова; повторная с кэшем в registry
(buildx/kaniko) существенно быстрее; изменение кода без изменения зависимостей должно
переиспользовать слой установки зависимостей — если этого не происходит, проблема
в порядке инструкций Dockerfile.

</details>

#### C5. Оптимизация Dockerfile под CI
Проверь, что зависимости ставятся в отдельном слое до копирования кода, и что есть
`.dockerignore`. Замерь размер образа `docker images` до и после multi-stage.
Цель — уложиться в разумный размер (для Python-приложения обычно < 200 МБ).

<details><summary>Ответ</summary>

Типичные находки: `COPY . .` до установки зависимостей (убивает кэш),
отсутствие `.dockerignore` (в контекст улетает `.git`, `node_modules`, артефакты),
один stage вместо multi-stage.

</details>

#### C6. Тесты в контейнере
Сделай multi-stage Dockerfile с таргетами `test` и `prod`. В джобе:
собери `--target test`, прогони тесты внутри контейнера, затем собери и запушь `--target prod`.

<details><summary>Ответ</summary>

Критерий: в registry попадает **только** прод-образ; тестовый слой в registry
не публикуется (или публикуется во временный тег с коротким сроком жизни).

</details>

#### C7. Интеграционные тесты с сервисами
Добавь джобу с `services: postgres` и `redis`, дождись готовности БД, прогони миграции
и интеграционные тесты. Убедись, что джоба падает, если БД недоступна
(например, специально укажи неверный `DATABASE_URL`).

<details><summary>Ответ</summary>

При неверном `DATABASE_URL` джоба обязана падать — если она зелёная, значит тесты
не выполняют реальных запросов к БД (или ошибки подавляются).

</details>

#### C8. Скан образа
Добавь джобу Trivy: HIGH — предупреждение (`--exit-code 0`), CRITICAL — блокировка
(`--exit-code 1`). Найди образ с известной уязвимостью (например, старый `python:3.8`)
и убедись, что пайплайн краснеет.

<details><summary>Ответ</summary>

На старом базовом образе Trivy найдёт критические уязвимости, джоба станет красной.
Это хороший момент проверить, что обновление базового образа их убирает.

</details>

#### C9. Деплой образа
Задеплой собранный образ на свою VM через SSH + `docker compose`, используя переменную
`APP_IMAGE=$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA`. Заведи Deploy Token для доступа
сервера к registry. Добавь проверку `/health` после деплоя.

<details><summary>Ответ</summary>

Критерий: на сервере логин выполняется Deploy Token'ом, контейнер запущен из образа
с тем же SHA, что в пайплайне, `/health` отвечает 200 из джобы.

</details>

#### C10. Очистка registry
Настрой cleanup policy: хранить 10 последних тегов, не трогать `^v\d+\.\d+\.\d+$`,
удалять остальное старше 30 дней. Посмотри размер registry до и после.

<details><summary>Ответ</summary>

После применения политики размер registry должен уменьшиться; релизные теги
и текущие задеплоенные версии должны остаться на месте.

</details>

#### C11. Rootless BuildKit
Перепиши сборку на `moby/buildkit:rootless` + `buildctl-daemonless.sh` (без privileged):
логин через `~/.docker/config.json`, пуш `--output type=image,name=...,push=true`, кэш
`--export-cache/--import-cache type=registry`. Замерь холодную и повторную сборку, сравни с buildx (C4).
Если свой раннер без privileged — поймай ошибку rootlesskit, почини её **без** возврата
privileged и запиши, что именно пришлось ослабить. Бонус: перенеси сюда kaniko-джобу из C3
по таблице соответствия флагов (§6 конспекта).

<details><summary>Ответ</summary>

Критерий: джоба зелёная без privileged, образ в registry, повторная сборка
с `--import-cache` заметно быстрее (в логе шаги помечены `CACHED`), по скорости — примерно
как buildx из C4 (движок тот же). На своём docker-раннере без privileged ожидаемо падение
`fork/exec /proc/self/exe: operation not permitted` → `security_opt` в `[runners.docker]`
с кастомным seccomp-профилем (крайний вариант — `seccomp:unconfined` + `apparmor:unconfined`
на отдельном раннере, записанный как осознанный риск). Миграция из C3: `--destination` →
`--output type=image,name=...,push=true`, `--cache-repo` → `--export-cache/--import-cache`.

</details>

#### C12. Buildah
Сделай вариант на `quay.io/buildah/stable`: `STORAGE_DRIVER=vfs`, `BUILDAH_FORMAT=docker`,
`buildah build` + `buildah push`, два тега (SHA и ветка — через `buildah tag`), кэш
`--layers --cache-from/--cache-to`. Сравни время сборки и занятое место на диске с BuildKit (C11).

<details><summary>Ответ</summary>

Критерий: в registry образ с двумя тегами (`buildah tag "$IMG:$SHA" "$IMG:$SLUG"`
и два `buildah push`), джоба без privileged. На больших образах buildah с `vfs` ожидаемо
медленнее BuildKit и занимает больше места (`du -sh /var/lib/containers`): `vfs` копирует
слои целиком вместо overlay.

</details>

---

### Блок D. Инциденты

**D1.** `Cannot connect to the Docker daemon at tcp://docker:2375`. Перечисли причины
и порядок проверки.

<details><summary>Ответ</summary>

(1) Нет `services: docker:dind`; (2) неверный `DOCKER_HOST` (2375 без TLS против
2376 с TLS) или несогласованный `DOCKER_TLS_CERTDIR`; (3) раннер без `privileged`;
(4) сеть между контейнером джобы и сервисом (alias `docker`); (5) на shell-раннере нет
доступа к сокету/пользователь не в группе docker.

</details>

**D2.** `denied: requested access to the resource is denied` при пуше. Четыре причины.

<details><summary>Ответ</summary>

(1) Не выполнен `docker login`; (2) имя образа не совпадает с `$CI_REGISTRY_IMAGE`
(пуш в чужой namespace); (3) registry отключён в настройках проекта; (4) недостаточно прав
у токена/пользователя (например, пуш из форка); (5) попытка пуша в защищённый тег/пакет.

</details>

**D3.** Сборка образа занимает 9 минут при любом изменении, даже в README. Что чинить?

<details><summary>Ответ</summary>

Кэш слоёв: `--cache-from`/buildx или buildctl registry cache/buildah `--cache-to`; порядок слоёв
в Dockerfile (зависимости до кода); `.dockerignore`, чтобы контекст не тащил лишнее;
multi-stage; при необходимости — сборка только при изменении нужных путей (`rules: changes`).

</details>

**D4.** Джоба падает с `toomanyrequests: You have reached your pull rate limit`. Решения.

<details><summary>Ответ</summary>

Использовать Dependency Proxy или зеркало, логиниться в Docker Hub своими
учётными данными (masked-переменные), кэшировать базовые образы в своём registry,
пинить базовые образы по digest.

</details>

**D5.** Образ собрался и запушился, но на сервере `docker pull` возвращает
`unauthorized: authentication required`. В чём дело?

<details><summary>Ответ</summary>

Сервер использует `$CI_JOB_TOKEN`, который уже недействителен, либо вообще
не логинился. Нужен Deploy Token со scope `read_registry`, сохранённый на сервере
(или логин в момент деплоя корректными кредами).

</details>

**D6.** Локально контейнер работает, в CI падает `exec format error`. Что произошло?

<details><summary>Ответ</summary>

Несовпадение архитектур: образ собран под другую платформу (arm64 vs amd64).
Решение — собирать в CI под нужную платформу или использовать buildx с `--platform`.

</details>

**D7.** Registry разросся до 80 ГБ, место кончилось. План действий (и чего нельзя удалять).

<details><summary>Ответ</summary>

Посмотреть крупнейшие репозитории образов, включить cleanup policy, удалить
служебные и старые ветковые теги, промежуточные кэш-репозитории. **Нельзя** удалять теги,
задеплоенные в активные окружения, и релизные версии — иначе пропадёт откат.
Долгосрочно — политика хранения и мониторинг размера.

</details>

**D8.** После перехода с dind на сборку без демона (kaniko/rootless BuildKit/buildah) перестал
работать `docker run` внутри джобы тестов. Почему и как перестроить пайплайн?

<details><summary>Ответ</summary>

Daemonless-сборщики (kaniko, rootless BuildKit, buildah) не дают докер-демона внутри
джобы, поэтому `docker run` недоступен. Перестроить: тесты запускать отдельной джобой в нужном
образе (`image: <собранный образ>` или обычный language-образ), а сборщик оставить только
для сборки/пуша.

</details>

**D9.** Деплой на прод пошёл со старым образом, хотя пайплайн собрал новый.
Три возможные причины.

<details><summary>Ответ</summary>

(1) Деплой использует плавающий тег (`latest`/ветка), который указывает на старое;
(2) на сервере не выполнен `pull` (или `docker compose up` без `--pull always`);
(3) джоба деплоя взяла переменную с тегом из другого пайплайна/через кэш;
(4) деплой пошёл раньше завершения пуша (нет зависимости `needs`).

</details>

**D10.** В логе джобы деплоя видно значение `$CI_REGISTRY_PASSWORD`. Как это вышло
(команда `docker login -p ...`) и как правильно?

<details><summary>Ответ</summary>

`docker login -p "$VAR"` печатает предупреждение и часто саму команду в лог
(особенно при `set -x`); маскирование может не сработать при преобразованиях.
Правильно — `echo "$CI_REGISTRY_PASSWORD" | docker login --password-stdin`.

</details>

**D11.** Сборку перенесли с dind на rootless BuildKit на своём docker-раннере без privileged —
джоба падает с `[rootlesskit:parent] error: failed to start the child: fork/exec /proc/self/exe:
operation not permitted`. Что происходит и как чинить, не возвращая privileged?

<details><summary>Ответ</summary>

`rootlesskit` не может создать user namespace: дефолтный seccomp-профиль Docker режет
нужные syscalls (`unshare`/`clone` с `CLONE_NEWUSER`), AppArmor — mount'ы. Privileged не возвращаем.
Чиним: проверить `BUILDKITD_FLAGS: --oci-worker-no-process-sandbox`; в `[runners.docker]` задать
`security_opt` с кастомным seccomp-профилем, разрешающим только нужное (крайний вариант —
`seccomp:unconfined` + `apparmor:unconfined`, осознанно и на отдельном раннере); если политику
раннера менять нельзя — попробовать buildah. В k8s-раннере то же самое делается через
`seccompProfile`/AppArmor `Unconfined` у контейнера сборки.

</details>

**D12.** Новая BuildKit-джоба ничего не пишет в лог после старта и висит до таймаута.
Что забыто в конфиге?

<details><summary>Ответ</summary>

Не переопределён `entrypoint: [""]`: ENTRYPOINT образа `moby/buildkit:rootless` запускает
`rootlesskit buildkitd` — долгоживущий демон, и `script` джобы так и не выполняется.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как собрать и запушить Docker-образ в GitLab CI?

<details><summary>Ответ</summary>

Джоба с `image: docker` + `services: docker:dind`, `docker login` предопределёнными
переменными, `docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .`, `docker push`.

</details>

**2.** Что такое dind и почему для него нужен privileged?

<details><summary>Ответ</summary>

Второй контейнер с докер-демоном рядом с джобой; privileged нужен, потому что демону
требуется доступ к возможностям ядра (namespaces, cgroups, монтирование, overlayfs).

</details>

**3.** Чем сборка без демона (rootless BuildKit, buildah) лучше dind? Когда всё-таки выберешь dind?

<details><summary>Ответ</summary>

Не требует privileged и докер-демона — меньше поверхность атаки на общих раннерах и в k8s;
кэш слоёв живёт в registry и переживает любой раннер. Цена — послабленные seccomp/AppArmor
для rootless и нет `docker run` в джобе. dind выберу, когда в джобе нужен полноценный docker
(`docker run`, compose в тестах) и есть отдельный доверенный раннер.

</details>

**4.** Как организовать кэш слоёв в CI?

<details><summary>Ответ</summary>

Кэш зависимостей — `cache:`; кэш слоёв — `--cache-from`/`--cache-to type=registry` (buildx),
`--export-cache/--import-cache` (buildctl), `--layers --cache-to` (buildah); плюс правильный
порядок слоёв в Dockerfile.

</details>

**5.** Как тегировать образы и какой тег использовать в деплое?

<details><summary>Ответ</summary>

SHA — всегда и для деплоя; ветка и SemVer — алиасы; `latest` — не для деплоя.

</details>

**6.** Как прогнать интеграционные тесты с базой данных в пайплайне?

<details><summary>Ответ</summary>

Через `services:` с переменными подключения и явным ожиданием готовности, миграции
перед тестами.

</details>

**7.** Как сервер получает доступ к приватному registry?

<details><summary>Ответ</summary>

Через Deploy Token со scope `read_registry` (или отдельного технического пользователя),
`docker login` на сервере; токен джобы для этого не подходит.

</details>

**8.** Как не дать уязвимому образу попасть в прод?

<details><summary>Ответ</summary>

Скан образа (Trivy/GitLab Container Scanning) с блокировкой по CRITICAL, обновление
базовых образов, запрет деплоя без прохождения скана.

</details>

**9.** Как чистить registry и что нельзя удалять?

<details><summary>Ответ</summary>

Cleanup policy: хранить N последних, защищать релизные теги и задеплоенные версии,
удалять ветковые и временные теги по возрасту.

</details>

**10.** Что бы ты сделал, если сборка образа стала узким местом пайплайна?

<details><summary>Ответ</summary>

Профилировать шаги сборки, включить кэш слоёв, переупорядочить Dockerfile, добавить
`.dockerignore`, multi-stage, при необходимости — более мощный раннер и сборка
только при изменении релевантных путей.

</details>

**11.** Kaniko заархивирован — чем собирать образы в k8s-раннере?

<details><summary>Ответ</summary>

По умолчанию — rootless BuildKit (`moby/buildkit:rootless` + `buildctl-daemonless.sh`,
`--oci-worker-no-process-sandbox`, кэш `type=registry`): тот же движок, что `docker build`,
без privileged. Честно назову цену — контейнеру сборки нужны seccomp/AppArmor `Unconfined`
(или кастомный профиль). Альтернатива — buildah (`vfs`, `buildah build/push`), особенно
в OpenShift; для большого кластера — отдельный сервис `buildkitd` с тёплым кэшем. Существующие
kaniko-джобы — временно на форк Chainguard (только security-фиксы), затем миграция.
dind/privileged в k8s — нет.

</details>

---

### 🎯 Чек-лист

- [ ] Образ собирается в CI и лежит в GitLab Registry с тегом по SHA
- [ ] Логин в registry — через `--password-stdin`, без `-p`
- [ ] Умею собрать образ с privileged (dind/buildx) и без него (rootless BuildKit, buildah) и объяснить выбор
- [ ] Знаю, почему kaniko — legacy, и умею перенести kaniko-джобу на BuildKit/buildah
- [ ] Настроен кэш слоёв, повторная сборка заметно быстрее (замерил)
- [ ] Есть релизный тег из git-тега `vX.Y.Z`
- [ ] Интеграционные тесты идут с `services` и ждут готовности БД
- [ ] Образ сканируется, CRITICAL блокирует пайплайн
- [ ] Деплой тянет образ по SHA, сервер логинится Deploy Token'ом
- [ ] Настроена cleanup policy, релизные теги защищены
- [ ] Нигде не пересобираю образ перед продом
