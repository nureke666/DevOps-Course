---
title: "05. Registry и тегирование"
description: "Registry — точка встречи CI и CD: тегирование, версионирование, дайджесты, безопасность образов"
---

# 05. Registry: связующее звено между сборкой и деплоем

> Роадмап → 3. Docker → Теория → Образы → Registry
> «**Очень важно** для CI/CD: пайплайн собрал образ, положил в registry, а дальше условный
> Kubernetes его оттуда забирает. Понимание registry + тегирование + версионирование образов —
> это то, что превращает просто разрозненные знания о технологии в DevOps-видение.»
> **После темы ты умеешь:** выстроить путь «коммит → образ → registry → деплой» и объяснить
> его на собесе целиком.

---

## 🗺️ Схема: место registry в DevOps-цикле

```text:no-line-numbers
 разработчик          CI (GitLab CI / GitHub Actions / Jenkins)              прод
 ┌────────┐      ┌───────────────────────────────────────────┐      ┌──────────────────┐
 │ git    │push  │ 1. checkout                               │      │ Kubernetes /     │
 │ commit ├─────►│ 2. tests, lint                            │      │ docker compose   │
 │ a1b2c3 │      │ 3. docker build -t app:a1b2c3             │      │                  │
 └────────┘      │ 4. docker login                           │      │  kubectl set     │
                 │ 5. docker push reg/app:a1b2c3  ───────────┼──┐   │  image app=      │
                 │ 6. scan (trivy) / sign (cosign)           │  │   │  reg/app:a1b2c3  │
                 └───────────────────────────────────────────┘  │   └────────┬─────────┘
                                                                 ▼            │ pull
                                       ┌──────────────────────────────────┐   │
                                       │      REGISTRY (Harbor/ECR/       │◄──┘
                                       │      GHCR/Nexus/Docker Hub)      │
                                       │   app:a1b2c3, app:1.4.2, ...     │
                                       └──────────────────────────────────┘

  ⭐ Registry — ЕДИНСТВЕННАЯ точка, где встречаются сборка и деплой.
     Без него CI/CD не существует: собранный образ должен где-то жить.
```

---

## 1. Что такое registry

| Термин | Смысл |
|--------|-------|
| **Registry** | Сервис хранения образов (Docker Hub, GHCR, ECR, GCR, Harbor, Nexus, GitLab Registry) |
| **Repository** | Набор версий одного образа: `acme/payments` со всеми тегами |
| **Tag** | Метка версии внутри репозитория |
| **Namespace / project** | Группировка репозиториев (`library/`, `acme/`, `team-backend/`) |

```text:no-line-numbers
registry.company.ru  /  team-backend  /  payments   :  1.4.2
└── registry ───────┘   └ namespace ┘   └ repo ───┘    └ tag ┘
```

### Типы

| Тип | Примеры | Когда |
|-----|---------|-------|
| Публичный | Docker Hub, GHCR, Quay | Open source, базовые образы |
| Managed приватный | AWS ECR, GCP Artifact Registry, Yandex CR | Облако, IAM-интеграция |
| Self-hosted | Harbor, Nexus, GitLab Registry, `registry:2` | On-prem, полный контроль, air-gapped |
| Прокси/кэш | Harbor proxy cache, Nexus proxy, pull-through cache | Экономия трафика, работа при недоступности Hub |

> ⚠️ **Rate limits Docker Hub** — боль реальной жизни: анонимно ~100 pull/6ч на IP.
> В CI это выливается в `toomanyrequests: You have reached your pull rate limit`.
> Лечится авторизацией, зеркалом/pull-through cache или переездом базовых образов в свой registry.

---

## 2. Работа с registry: команды

```bash
# Аутентификация
docker login                                   # Docker Hub
docker login ghcr.io -u USER --password-stdin <<< "$GITHUB_TOKEN"
docker login registry.company.ru -u ci-bot
cat ~/.docker/config.json                      # ⚠️ credentials лежат ЗДЕСЬ (base64, не шифр!)
docker logout registry.company.ru

# Тегирование под registry — ОБЯЗАТЕЛЬНО перед push
docker tag myapp:1.4.2 registry.company.ru/team-backend/payments:1.4.2

# Публикация и получение
docker push registry.company.ru/team-backend/payments:1.4.2
docker pull registry.company.ru/team-backend/payments:1.4.2
docker pull registry.company.ru/team-backend/payments@sha256:abc…   # по дайджесту

# Инспекция БЕЗ скачивания
docker manifest inspect registry.company.ru/team-backend/payments:1.4.2
skopeo inspect docker://registry.company.ru/team-backend/payments:1.4.2
skopeo copy docker://src/img:1.0 docker://dst/img:1.0   # перелить между registry
```

> `docker push` без указания registry уйдёт на Docker Hub. Имя образа **содержит** адрес registry —
> это и есть «куда пушить». Нет отдельного флага `--registry`.

### Что реально передаётся при push/pull

```text:no-line-numbers
push: манифест + конфиг + слои, которых ещё нет в registry ("Layer already exists")
pull: манифест → список слоёв → скачиваются только отсутствующие локально ("Already exists")
```
Отсюда прямая связь с темой 04 про кэш сборки: аккуратные слои = быстрый деплой.

---

## 3. Версионирование образов ⭐

### Схема, которая работает в реальных командах

| Тег | Кто ставит | Назначение |
|-----|-----------|------------|
| `1.4.2` | CI на git-теге | Релиз. **Иммутабельный**, по нему деплоят и откатываются |
| `1.4`, `1` | CI | Подвижные указатели на последний patch/minor |
| `a1b2c3d` (git SHA) | CI на каждый коммит | ⭐ Трассируемость: по любому поду видно коммит |
| `main`, `develop` | CI на пуш в ветку | Автодеплой на dev/stage окружения |
| `pr-142` | CI на pull request | Временные превью-окружения |
| `2026-09-13.17` | CI | Когда semver неприменим (инфраструктурные образы) |
| `latest` | CI (опц.) | Удобство разработчика. **Не для прода** |

```bash
# Типовой фрагмент CI
IMAGE=registry.company.ru/team-backend/payments
SHA=$(git rev-parse --short HEAD)
VER=$(git describe --tags --abbrev=0 2>/dev/null || echo "0.0.0")

docker build -t $IMAGE:$SHA --build-arg APP_VERSION=$VER .
docker tag $IMAGE:$SHA $IMAGE:$VER
docker tag $IMAGE:$SHA $IMAGE:latest
docker push --all-tags $IMAGE          # или push по одному тегу
```

### Semantic Versioning (semver) на пальцах

```text:no-line-numbers
MAJOR . MINOR . PATCH        1.4.2
  │       │        └── багфикс, обратно совместимо
  │       └── новая функциональность, обратно совместимо
  └── ломающие изменения
```
Предрелизы: `1.5.0-rc.1`, `1.5.0-beta.2`. Сборки: `1.4.2+build.17`.

### Правила, за нарушение которых бьют

1. **Релизный тег не переписывают.** Включи immutable tags в registry (ECR, Harbor, GitLab).
2. **В прод-манифестах — точная версия или дайджест**, никогда не `latest`/`main`.
3. **Каждый образ трассируется до коммита** — через тег с SHA и/или OCI-метки:
   ```dockerfile
   LABEL org.opencontainers.image.revision="$GIT_SHA" \
         org.opencontainers.image.source="https://git.company.ru/team/payments" \
         org.opencontainers.image.version="1.4.2" \
         org.opencontainers.image.created="2026-09-13T10:00:00Z"
   ```
4. **Один образ — все окружения.** Dev/stage/prod получают **тот же артефакт**, различия —
   в переменных окружения и конфигах, а не в пересборке. Пересобрал под прод → тестировал не то.
5. **Retention policy**: автоудаление старых тегов (кроме релизных), иначе registry растёт бесконечно.

---

## 4. Свой registry за 30 секунд

```bash
# Простейший (без auth и TLS — только для лабы!)
docker run -d -p 5000:5000 --name registry \
  -v registry-data:/var/lib/registry \
  registry:2

docker tag alpine:3.20 localhost:5000/alpine:3.20
docker push localhost:5000/alpine:3.20
curl -s http://localhost:5000/v2/_catalog | jq .
curl -s http://localhost:5000/v2/alpine/tags/list | jq .
docker pull localhost:5000/alpine:3.20
```

> Для пуша на **`localhost:5000`** докер делает исключение и разрешает HTTP.
> Для любого другого адреса без TLS получишь `http: server gave HTTP response to HTTPS client`
> — нужно добавить `{"insecure-registries": ["reg.lab:5000"]}` в `/etc/docker/daemon.json`
> и перезапустить демон (только для лаб! в проде — TLS).

Для взрослого self-hosted — **Harbor**: UI, проекты, RBAC, сканирование (Trivy),
подпись, репликация между registry, retention, proxy cache.

### Distribution API (полезно для скриптов и отладки)

```bash
REG=localhost:5000
curl -s $REG/v2/_catalog | jq .                          # список репозиториев
curl -s $REG/v2/alpine/tags/list | jq .                  # теги
curl -sI -H "Accept: application/vnd.oci.image.manifest.v1+json" \
     $REG/v2/alpine/manifests/3.20 | grep -i docker-content-digest   # дайджест тега
```

---

## 5. Безопасность registry

| Практика | Зачем |
|----------|-------|
| Приватный registry для своих образов | Код и конфиги не утекают |
| Robot-аккаунты для CI (не личные логины) | Ротация, ограничение прав, аудит |
| Права: CI — push, прод-кластер — **только pull** | Скомпрометированная нода не отравит registry |
| **Сканирование** (Trivy, Grype, Docker Scout, Harbor) | CVE находят до прода |
| **Подпись** образов (cosign) + верификация на деплое | Защита от подмены образа |
| Immutable tags + retention | Воспроизводимость + место |
| `imagePullSecrets` / IAM-роли вместо паролей в манифестах | Секреты не в git |
| Pull-through cache для Docker Hub | Rate limits и доступность |

```bash
# Сканирование
trivy image --severity HIGH,CRITICAL registry.company.ru/team/payments:1.4.2
docker scout cves payments:1.4.2

# Подпись (cosign, keyless через OIDC в CI)
cosign sign registry.company.ru/team/payments@sha256:abc…
cosign verify registry.company.ru/team/payments@sha256:abc…
```

> `~/.docker/config.json` хранит логин/пароль в **base64**, а не зашифрованным.
> На CI-раннерах используй `docker login --password-stdin` из секрета и
> `docker logout` в конце джобы; лучше — credential helper или IAM-роль.

---

## 💼 Как это в DevOps

- **Registry — граница ответственности.** До него — «сборка» (CI), после — «доставка» (CD).
  Артефакт (образ) один и тот же во всех окружениях.
- **Инцидент «что в проде?»** решается за 10 секунд, если теги правильные:
  `kubectl get pods -o jsonpath='{..image}'` → `payments:1.4.2` → git-тег → коммит → changelog.
  С `latest` этот путь невозможен.
- **Откат** — это `kubectl set image ... payments:1.4.1`, работает только если старый образ
  ещё в registry и тег иммутабельный (отсюда retention policy с исключением релизов).
- **Стоимость**: registry — это диск и трафик. Политики очистки и общие базовые слои экономят
  реальные деньги в облаке.

---

## 🧪 Мини-лаба: полный путь коммит → registry → запуск

```bash
mkdir -p ~/docker-lab/05 && cd ~/docker-lab/05 && git init -q 2>/dev/null

# --- 1. Поднять локальный registry
docker run -d -p 5000:5000 --name lab-registry -v lab-reg:/var/lib/registry registry:2
curl -s localhost:5000/v2/_catalog | jq .

# --- 2. Приложение и образ
cat > app.py <<'EOF'
import os
print(f"payments version={os.getenv('APP_VERSION','dev')} commit={os.getenv('GIT_SHA','none')}")
EOF
cat > Dockerfile <<'EOF'
FROM python:3.12-slim
ARG APP_VERSION=dev
ARG GIT_SHA=none
LABEL org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.source="https://git.local/team/payments"
ENV APP_VERSION=${APP_VERSION} GIT_SHA=${GIT_SHA}
WORKDIR /app
COPY app.py .
CMD ["python","app.py"]
EOF

# --- 3. Симуляция CI: собрать и протегировать
git add -A && git commit -qm "v1.4.2" 2>/dev/null
REG=localhost:5000
IMG=$REG/team-backend/payments
SHA=$(git rev-parse --short HEAD 2>/dev/null || echo a1b2c3d)
VER=1.4.2

docker build -t $IMG:$SHA --build-arg APP_VERSION=$VER --build-arg GIT_SHA=$SHA .
for t in $VER 1.4 1 latest; do docker tag $IMG:$SHA $IMG:$t; done
docker images | grep payments

# --- 4. Push
docker push --all-tags $IMG
curl -s $REG/v2/_catalog | jq .
curl -s $REG/v2/team-backend/payments/tags/list | jq .

# --- 5. Получить дайджест и проверить трассируемость
DIGEST=$(docker image inspect $IMG:$VER --format '{{index .RepoDigests 0}}')
echo "digest: $DIGEST"
docker image inspect $IMG:$VER --format '{{json .Config.Labels}}' | jq .

# --- 6. «Деплой»: удалить локальные образы и притянуть заново по дайджесту
docker rmi $IMG:$SHA $IMG:$VER $IMG:1.4 $IMG:1 $IMG:latest
docker run --rm $DIGEST                     # ← деплой по неизменяемому дайджесту
docker run --rm $IMG:$VER                   # ← деплой по версии

# --- 7. Новый релиз: показать, что подвижные теги двигаются, а релизные — нет
sed -i 's/version=/v=/' app.py 2>/dev/null || true
git add -A && git commit -qm "v1.4.3" 2>/dev/null
SHA2=$(git rev-parse --short HEAD); VER2=1.4.3
docker build -t $IMG:$SHA2 --build-arg APP_VERSION=$VER2 --build-arg GIT_SHA=$SHA2 .
for t in $VER2 1.4 1 latest; do docker tag $IMG:$SHA2 $IMG:$t; done
docker push --all-tags $IMG
curl -s $REG/v2/team-backend/payments/tags/list | jq .
docker run --rm $IMG:1.4.2      # старая версия НА МЕСТЕ → откат возможен
docker run --rm $IMG:1.4        # уже новая → плавающий тег

# --- 8. Что лежит в credentials
cat ~/.docker/config.json 2>/dev/null | jq . | head

# --- 9. Уборка
docker rm -f lab-registry; docker volume rm lab-reg
docker rmi $(docker images "$REG/*" -q) 2>/dev/null
cd ~ && rm -rf ~/docker-lab/05
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `docker login REG -u USER --password-stdin` | Авторизация (пароль из stdin, не в истории shell) |
| `docker logout REG` | Выйти |
| `docker tag SRC REG/NS/REPO:TAG` | Подготовить имя под registry |
| `docker push REG/NS/REPO:TAG` | Загрузить |
| `docker push --all-tags REG/NS/REPO` | Загрузить все теги репозитория |
| `docker pull REG/NS/REPO:TAG` / `@sha256:…` | Скачать по тегу / по дайджесту |
| `docker manifest inspect IMG` | Манифест из registry без скачивания |
| <code v-pre>docker image inspect IMG --format '{{index .RepoDigests 0}}'</code> | Дайджест образа |
| `curl REG/v2/_catalog` | Список репозиториев (Distribution API) |
| `curl REG/v2/REPO/tags/list` | Список тегов |
| `skopeo copy docker://a docker://b` | Перелить образ между registry без docker |
| `trivy image IMG` / `docker scout cves IMG` | Сканирование уязвимостей |
| `cosign sign/verify IMG@sha256:…` | Подпись и проверка |
| `docker run -d -p 5000:5000 registry:2` | Локальный registry |

---

## 🧠 Что запомнить

1. **Registry — точка встречи CI и CD.** Пайплайн собрал и запушил, оркестратор забрал.
   Без него автоматизация доставки не существует.
2. Имя образа **содержит адрес registry**: `push` определяется тегом, а не флагом.
3. Push/pull передают **только недостающие слои** — правильная нарезка слоёв ускоряет деплой.
4. Тег — подвижная метка. Релизные теги делай **иммутабельными**, деплой — по версии
   или **дайджесту**.
5. Обязательные теги в CI: **точная версия** + **git SHA**. Плавающие (`1.4`, `latest`) — для удобства.
6. **Один артефакт на все окружения**; различия — через конфиги и переменные окружения.
7. OCI-метки (`revision`, `source`, `version`) дают трассировку «под → коммит».
8. Docker Hub имеет **rate limit** — в CI логинься или используй зеркало/кэш.
9. Права: CI пушит, прод только тянет; для CI — robot-аккаунты, не личные.
10. Сканирование (trivy/scout) и подпись (cosign) — часть пайплайна, а не «потом».
11. `~/.docker/config.json` хранит креды в base64 — это не шифрование.
12. Retention policy обязательна, но релизные теги из неё исключают (иначе не откатишься).

---

## Задачи

> Лаба: `mkdir -p ~/docker-lab/05 && cd ~/docker-lab/05`
> ⭐ Роадмап: «Понимание registry + тегирование + версионирование образов — это то, что
> превращает разрозненные знания в DevOps-видение». Блок C1 — именно про это.

---

### Блок A. Теория

**A1.** Что такое registry и какое место он занимает в CI/CD? Нарисуй путь от коммита до пода.

<details><summary>Ответ</summary>

Registry — хранилище образов, единственная точка встречи сборки и доставки.
Путь: коммит → CI (тесты, `docker build`, тег) → `docker login` + `docker push` в registry →
(скан, подпись) → CD меняет образ в манифесте/compose → кластер делает `pull` из registry →
запускает контейнер. Без registry артефакт негде хранить и оркестратору неоткуда его брать.

</details>

**A2.** Чем registry отличается от repository? Разбери на примере
`registry.company.ru/team-backend/payments:1.4.2`.

<details><summary>Ответ</summary>

Registry — сервис (`registry.company.ru`). Repository — набор версий одного образа
внутри него (`team-backend/payments`), где `team-backend` — namespace/проект.
`1.4.2` — тег (метка конкретного манифеста).

</details>

**A3.** Куда уйдёт `docker push myapp:1.0`, если не указывать адрес registry? Как это исправить?

<details><summary>Ответ</summary>

На Docker Hub, в репозиторий `docker.io/<твой_логин>/myapp` (а без логина — с ошибкой
доступа). Исправить: `docker tag myapp:1.0 registry.company.ru/team/myapp:1.0` и пушить уже
полное имя — адрес registry является частью имени образа.

</details>

**A4.** Что реально передаётся при `docker push`? Почему повторный push быстрый?

<details><summary>Ответ</summary>

Манифест, конфиг и **только те слои, которых в registry ещё нет** (проверка по дайджестам,
в выводе — `Layer already exists`). Повторный push быстрый, потому что общие слои уже лежат там.

</details>

**A5.** Назови 4 типа registry (публичный, managed, self-hosted, кэширующий) с примерами
и когда какой применять.

<details><summary>Ответ</summary>

Публичный (Docker Hub, GHCR, Quay) — open source и базовые образы;
managed (ECR, Artifact Registry, Yandex CR) — облако с IAM;
self-hosted (Harbor, Nexus, GitLab Registry, `registry:2`) — on-prem, приватность, air-gap;
кэширующий прокси (Harbor proxy cache, Nexus proxy, registry mirror) — экономия трафика,
обход rate limits, доступность при недоступном Hub.

</details>

**A6.** Что такое Docker Hub rate limit и как с ним бороться в CI? Три способа.

<details><summary>Ответ</summary>

Ограничение числа pull с одного IP/аккаунта за окно времени (для анонимов заметно
жёстче). Решения: (1) `docker login` техническим аккаунтом в CI; (2) pull-through cache /
registry mirror; (3) держать копии базовых образов в своём registry (skopeo copy) и собирать от них.

</details>

**A7.** Опиши схему тегирования для CI: какие теги ставить, какие двигать, какие замораживать.

<details><summary>Ответ</summary>

Ставить на каждый образ: git SHA (всегда), точную версию на релизах, плавающие
`major`/`major.minor`, `latest` (опционально), ветку/PR для превью-окружений. Замораживать —
релизные теги и SHA; двигать — плавающие.

</details>

**A8.** Что такое semver? Что меняется в каждой позиции `MAJOR.MINOR.PATCH`?

<details><summary>Ответ</summary>

`MAJOR.MINOR.PATCH`: MAJOR — несовместимые изменения API; MINOR — новая
функциональность с обратной совместимостью; PATCH — исправления. Предрелизы через
`-rc.1`/`-beta.2`.

</details>

**A9.** Почему релизные теги должны быть иммутабельными? Что случится, если это не так?

<details><summary>Ответ</summary>

Иначе один и тот же тег в разное время означает разные образы: невозможно
воспроизвести сборку, откат может привести не туда, аудит бесполезен, а перезапуск пода
внезапно меняет версию приложения (см. D4).

</details>

**A10.** Почему в проде деплоят по дайджесту, а не по тегу? В чём минус такого подхода?

<details><summary>Ответ</summary>

Дайджест — криптографический идентификатор содержимого: гарантирует, что запустится
ровно тот образ, который тестировали, и защищает от подмены тега. Минус — нечитаемо
(`@sha256:9f2c…`), ручные операции неудобны, поэтому дайджест обычно подставляет
автоматика (CD, рендер манифестов, Renovate).

</details>

**A11.** Почему «один образ — все окружения», а не отдельная сборка под прод?

<details><summary>Ответ</summary>

Потому что тестировали конкретный артефакт. Пересборка «под прод» даёт другой образ
(другие версии зависимостей, другое время сборки) — все тесты обесцениваются. Различия
окружений выносятся в переменные окружения, конфиги и секреты.

</details>

**A12.** Какие OCI-метки стоит проставлять и что они дают на практике?

<details><summary>Ответ</summary>

`org.opencontainers.image.source` (репозиторий), `.revision` (коммит), `.version`,
`.created`, `.title`, `.licenses`. Дают трассировку «работающий контейнер → коммит»,
удобны в registry UI и сканерах, используются инструментами SBOM/supply chain.

</details>

**A13.** Где docker хранит креды после `docker login` и насколько это безопасно?

<details><summary>Ответ</summary>

В `~/.docker/config.json` — логин и пароль в **base64** (не шифрование, декодируется
одной командой). Безопаснее: credential helper (`docker-credential-*`), IAM-роли (ECR),
короткоживущие токены, `docker login --password-stdin` из секрета CI и `docker logout` по
завершении джобы.

</details>

**A14.** Зачем нужен pull-through cache (proxy cache)?

<details><summary>Ответ</summary>

Кэширует образы из внешнего registry у себя: экономит трафик, ускоряет pull,
снимает rate limits, позволяет работать, когда внешний registry недоступен, и даёт
контроль/аудит используемых образов.

</details>

**A15.** Какие права должны быть у CI и у прод-кластера в registry и почему разные?

<details><summary>Ответ</summary>

CI — push (и pull) в свои репозитории, прод-кластер — **только pull**.
Если нода скомпрометирована, атакующий не сможет перезаписать образы в registry.
Учётки — робот-аккаунты с ограниченной областью действия и ротацией.

</details>

**A16.** Что такое retention policy для registry и какие теги нельзя в неё включать?

<details><summary>Ответ</summary>

Правила автоудаления старых артефактов (по возрасту/количеству/шаблону тега).
Нельзя включать релизные теги и образы, задеплоенные в прод — иначе откат станет невозможным
(см. D5). Обычно чистят: `pr-*`, `<branch>-*`, dangling, SHA-теги старше N дней.

</details>

**A17.** Зачем подписывать образы (cosign) и где проверяется подпись?

<details><summary>Ответ</summary>

Чтобы гарантировать происхождение образа и отсутствие подмены в registry.
Подпись ставит CI (cosign, часто keyless через OIDC), проверка — на этапе деплоя:
admission-контроллер в k8s (Kyverno/Gatekeeper/Connaisseur) или шаг в пайплайне.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  docker login ghcr.io -u user --password-stdin < token.txt
B2.  docker tag app:1.0 registry.company.ru/team/app:1.0
B3.  docker push --all-tags registry.company.ru/team/app
B4.  docker pull app@sha256:9f2c...
B5.  docker manifest inspect nginx:alpine
B6.  docker image inspect app:1.0 --format '{{index .RepoDigests 0}}'
B7.  curl -s localhost:5000/v2/_catalog | jq .
B8.  curl -s localhost:5000/v2/app/tags/list | jq .
B9.  skopeo copy docker://docker.io/library/alpine:3.20 docker://localhost:5000/alpine:3.20
B10. trivy image --severity CRITICAL app:1.0
B11. cosign verify --key cosign.pub registry/app@sha256:...
B12. docker run -d -p 5000:5000 -v reg:/var/lib/registry registry:2
B13. docker logout registry.company.ru
```

**B1.** Логин в GHCR с передачей токена через stdin (не попадает в историю shell и в `ps`).
**B2.** Дать образу имя, содержащее адрес registry и namespace — подготовка к push.
**B3.** Запушить все локальные теги этого репозитория.
**B4.** Скачать образ, жёстко зафиксированный по дайджесту.
**B5.** Показать манифест (или manifest list с платформами) прямо из registry.
**B6.** Показать `RepoDigest` — имя@дайджест, которым образ адресуется в registry.
**B7.** Список репозиториев локального registry через Distribution API.
**B8.** Список тегов репозитория `app`.
**B9.** Скопировать образ между registry **без docker-демона** (skopeo).
**B10.** Просканировать образ и показать только критические уязвимости.
**B11.** Проверить подпись образа по публичному ключу.
**B12.** Поднять локальный registry с постоянным томом.
**B13.** Удалить сохранённые креды для указанного registry.

**B14.** Почему `docker push localhost:5000/app:1.0` работает без TLS,
а `docker push reg.lab:5000/app:1.0` — нет?

<details><summary>Ответ</summary>

Докер по умолчанию требует HTTPS, но делает исключение для `localhost`/`127.0.0.1`
(трафик не уходит в сеть). Для других хостов нужен валидный TLS; временный обход —
`"insecure-registries": ["reg.lab:5000"]` в `/etc/docker/daemon.json` + рестарт демона
(только для лабораторий).

</details>

---

### Блок C. Практика

#### C1. 🔑 Полный путь «коммит → registry → запуск» (главное задание)

Собери мини-CI руками, без CI-системы:

1. Подними локальный registry (`registry:2`) с постоянным томом.
2. Создай git-репозиторий с приложением, которое печатает свою версию и коммит.
3. Напиши скрипт `ci.sh`, который:
   - берёт короткий git SHA и версию из git-тега;
   - собирает образ с `--build-arg APP_VERSION` и `--build-arg GIT_SHA`;
   - ставит теги: `<sha>`, `<version>`, `<major.minor>`, `<major>`, `latest`;
   - пушит все теги в локальный registry;
   - выводит итоговый дайджест.
4. Сделай два «релиза» (1.4.2 и 1.4.3), запусти скрипт для каждого.
5. Докажи, что:
   - `payments:1.4.2` по-прежнему запускает **старую** версию (откат возможен);
   - `payments:1.4` и `latest` указывают на новую;
   - по метке `org.opencontainers.image.revision` можно найти коммит.
6. Задеплой «в прод» по дайджесту и объясни, почему это надёжнее тега.

**Критерии приёмки:**
- `curl localhost:5000/v2/_catalog` показывает репозиторий;
- в списке тегов есть все 6+ тегов;
- `docker run` по тегу `1.4.2` печатает версию 1.4.2 после того, как вышла 1.4.3;
- `docker image inspect` показывает корректные OCI-метки.

<details><summary>Ответ</summary>

```bash
mkdir -p ~/docker-lab/05 && cd ~/docker-lab/05 && git init -q
docker run -d -p 5000:5000 --name lab-registry -v lab-reg:/var/lib/registry registry:2

cat > app.py <<'EOF'
import os
print(f"payments version={os.getenv('APP_VERSION','dev')} commit={os.getenv('GIT_SHA','none')}")
EOF
cat > Dockerfile <<'EOF'
FROM python:3.12-slim
ARG APP_VERSION=dev
ARG GIT_SHA=none
LABEL org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.source="https://git.local/team/payments"
ENV APP_VERSION=${APP_VERSION} GIT_SHA=${GIT_SHA}
WORKDIR /app
COPY app.py .
CMD ["python","app.py"]
EOF

cat > ci.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
REG=${REG:-localhost:5000}
IMG=$REG/team-backend/payments
SHA=$(git rev-parse --short HEAD)
VER=$(git describe --tags --abbrev=0 2>/dev/null || echo 0.0.0)
MINOR=${VER%.*}; MAJOR=${VER%%.*}

docker build -t "$IMG:$SHA" --build-arg APP_VERSION="$VER" --build-arg GIT_SHA="$SHA" .
for t in "$VER" "$MINOR" "$MAJOR" latest; do docker tag "$IMG:$SHA" "$IMG:$t"; done
docker push --all-tags "$IMG" >/dev/null
echo "pushed $IMG tags: $SHA $VER $MINOR $MAJOR latest"
docker image inspect "$IMG:$VER" --format 'digest: {{index .RepoDigests 0}}'
EOF
chmod +x ci.sh

git add -A && git commit -qm "release 1.4.2" && git tag -f 1.4.2 -m x >/dev/null
./ci.sh

echo 'print("новая фича")' >> app.py
git add -A && git commit -qm "release 1.4.3" && git tag -f 1.4.3 -m x >/dev/null
./ci.sh

curl -s localhost:5000/v2/team-backend/payments/tags/list | jq .
IMG=localhost:5000/team-backend/payments
docker rmi $(docker images "$IMG" -q) -f 2>/dev/null
docker run --rm $IMG:1.4.2       # СТАРАЯ версия — откат возможен
docker run --rm $IMG:1.4         # новая — плавающий тег
docker image inspect $IMG:1.4.2 --format '{{json .Config.Labels}}' | jq .
DIG=$(docker image inspect $IMG:1.4.3 --format '{{index .RepoDigests 0}}')
docker run --rm "$DIG"           # «деплой» по дайджесту
```

</details>

#### C2. Дайджест vs тег

1. Запушь образ под тегом `demo:1.0`, запиши дайджест.
2. Пересобери **другой** образ и запушь под тем же тегом `demo:1.0`.
3. Покажи, что дайджест изменился, а тег — нет.
4. Скачай образ по старому дайджесту — какой получишь?
5. Сделай вывод, что даёт пин по дайджесту.

<details><summary>Ответ</summary>

```bash
IMG=localhost:5000/team-backend/payments
docker tag alpine:3.20 $IMG:demo && docker push $IMG:demo
D1=$(docker image inspect $IMG:demo --format '{{index .RepoDigests 0}}'); echo $D1
docker tag busybox:latest $IMG:demo && docker push $IMG:demo
D2=$(docker image inspect $IMG:demo --format '{{index .RepoDigests 0}}'); echo $D2
# тег тот же, дайджесты разные
docker run --rm "$D1" cat /etc/os-release | head -1     # по старому дайджесту — СТАРЫЙ образ
```

</details>

#### C3. Что передаётся по сети

1. Собери образ на базе `python:3.12-slim`, запушь — засеки, сколько слоёв реально ушло.
2. Измени только код, пересобери, запушь снова — посмотри вывод (`Layer already exists`).
3. Сломай кэш: перенеси `COPY . .` в начало Dockerfile, пересобери, запушь.
4. Сравни, сколько слоёв ушло во втором и третьем случае. Сделай вывод для CI.

<details><summary>Ответ</summary>

```bash
IMG=localhost:5000/team-backend/payments
docker build -q -t $IMG:c3 . && docker push $IMG:c3 | tail -5
echo "# comment" >> app.py
docker build -q -t $IMG:c3b . && docker push $IMG:c3b | tail -5    # почти все "already exists"
# третий случай — COPY . . первым: меняется больше слоёв, пушится больше данных
```

</details>

#### C4. Registry API руками

Через `curl` (без docker CLI):
1. Получи список репозиториев.
2. Получи список тегов репозитория.
3. Получи дайджест конкретного тега (заголовок `Docker-Content-Digest`).
4. Скачай манифест и посмотри список слоёв.
5. (Бонус) Удали тег через API и проверь, что он пропал из списка.

<details><summary>Ответ</summary>

```bash
REG=localhost:5000; REPO=team-backend/payments
curl -s $REG/v2/_catalog | jq .
curl -s $REG/v2/$REPO/tags/list | jq .
D=$(curl -sI -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
     $REG/v2/$REPO/manifests/1.4.2 | tr -d '\r' | awk '/Docker-Content-Digest/{print $2}')
echo "digest: $D"
curl -s -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
     $REG/v2/$REPO/manifests/1.4.2 | jq '.layers[].size'
curl -sX DELETE $REG/v2/$REPO/manifests/$D -o /dev/null -w "%{http_code}\n"
# 405 = удаление отключено; включается REGISTRY_STORAGE_DELETE_ENABLED=true
```

</details>

#### C5. Приватный registry с аутентификацией

Подними `registry:2` с basic-auth (htpasswd) и проверь:
1. `docker pull` без логина → отказ.
2. `docker login` → pull работает.
3. Посмотри, что записалось в `~/.docker/config.json`, раскодируй base64.
4. Сделай `docker logout` и убедись, что доступ снова закрыт.

<details><summary>Ответ</summary>

```bash
mkdir -p auth
docker run --rm --entrypoint htpasswd httpd:2 -Bbn ci-bot secret123 > auth/htpasswd
docker rm -f lab-registry
docker run -d -p 5000:5000 --name lab-registry \
  -v lab-reg:/var/lib/registry -v "$PWD/auth:/auth" \
  -e REGISTRY_AUTH=htpasswd -e REGISTRY_AUTH_HTPASSWD_REALM=Realm \
  -e REGISTRY_AUTH_HTPASSWD_PATH=/auth/htpasswd registry:2
docker logout localhost:5000 2>/dev/null
docker pull localhost:5000/team-backend/payments:1.4.2      # unauthorized
echo secret123 | docker login localhost:5000 -u ci-bot --password-stdin
docker pull localhost:5000/team-backend/payments:1.4.2      # ок
jq -r '.auths."localhost:5000".auth' ~/.docker/config.json | base64 -d; echo
docker logout localhost:5000
```

</details>

#### C6. Сканирование и метки

1. Собери образ на базе `python:3.12` (не slim) и просканируй `trivy`/`docker scout`.
2. Пересобери на `python:3.12-slim`, просканируй снова. Сравни число CRITICAL/HIGH.
3. Добавь полный набор OCI-меток и покажи их через `docker image inspect`.

<details><summary>Ответ</summary>

```bash
IMG=localhost:5000/team-backend/payments
docker pull python:3.12 >/dev/null
trivy image --severity HIGH,CRITICAL python:3.12      2>/dev/null | tail -5 || docker scout cves python:3.12
trivy image --severity HIGH,CRITICAL python:3.12-slim 2>/dev/null | tail -5 || docker scout cves python:3.12-slim
docker image inspect $IMG:1.4.3 --format '{{json .Config.Labels}}' | jq .
```

</details>

#### C7. Кэширующий прокси (опционально)

Подними `registry:2` в режиме pull-through cache для Docker Hub,
настрой демон на использование `registry-mirror`, убедись, что образы тянутся через него
(проверь логи registry).

<details><summary>Ответ</summary>

```bash
docker run -d -p 5001:5000 --name hub-cache \
  -e REGISTRY_PROXY_REMOTEURL=https://registry-1.docker.io registry:2
# /etc/docker/daemon.json: {"registry-mirrors": ["http://localhost:5001"]}
# sudo systemctl restart docker && docker pull alpine:3.20 && docker logs hub-cache | tail

# Уборка после всех упражнений блока C
docker rm -f lab-registry hub-cache 2>/dev/null; docker volume rm lab-reg 2>/dev/null
cd ~ && rm -rf ~/docker-lab/05
```

</details>

---

### Блок D. Инциденты

**D1.** CI падает с `toomanyrequests: You have reached your pull rate limit`.
Что произошло и три варианта решения.

<details><summary>Ответ</summary>

Превышен лимит анонимных pull с IP раннера (общий NAT — лимит съедают соседи).
Решения: логиниться в Hub техническим аккаунтом; поднять pull-through cache/registry mirror;
скопировать нужные базовые образы в свой registry (`skopeo copy`) и собирать от них.

</details>

**D2.** `docker push` падает: `denied: requested access to the resource is denied`.
Перечисли 4 причины.

<details><summary>Ответ</summary>

(1) Не выполнен `docker login` / протух токен; (2) нет прав на push в этот
namespace/проект; (3) неверное имя образа (чужой namespace, опечатка в проекте);
(4) включены immutable tags и такой тег уже существует; (5) репозиторий не создан,
а автосоздание выключено; (6) закончилась квота.

</details>

**D3.** `docker push reg.internal:5000/app:1.0` →
`http: server gave HTTP response to HTTPS client`. Что это и как правильно решить
(и как — неправильно, но быстро)?

<details><summary>Ответ</summary>

Докер требует HTTPS для всех registry, кроме localhost. Правильно — выдать registry
валидный TLS-сертификат (корпоративный CA/Let's Encrypt) и раздать CA на хосты
(`/etc/docker/certs.d/reg.internal:5000/ca.crt`). Быстро и неправильно —
`"insecure-registries": ["reg.internal:5000"]` в `/etc/docker/daemon.json` + рестарт демона
(годится только для лаб).

</details>

**D4.** В проде под перезапустился и «сам собой» обновился до другой версии приложения.
Деплой никто не делал. Как такое возможно и как предотвратить?

<details><summary>Ответ</summary>

Деплой был по плавающему тегу (`latest`/`main`/`1.4`), кто-то перезаписал его новым
образом; при пересоздании пода образ подтянулся заново. Предотвращение: деплой по точной
версии или дайджесту, immutable tags в registry, запрет `latest` в прод-манифестах,
`imagePullPolicy: IfNotPresent` с иммутабельными тегами.

</details>

**D5.** Нужно откатиться на версию, которая работала месяц назад. В registry её нет —
retention policy удалила. Что делать сейчас и что исправить в процессе?

<details><summary>Ответ</summary>

Сейчас: поискать образ на нодах (`docker images`/`crictl images`) и запушить обратно,
восстановить из бэкапа registry, либо пересобрать из git-тега (воспроизводимость может
пострадать — зависимости обновились). Исправить процесс: retention с исключением релизных тегов
и всего, что задеплоено; политика «релизы хранятся N лет»; бэкап registry; пин зависимостей
для воспроизводимой сборки.

</details>

**D6.** Registry занял 2 ТБ. Разбери, из чего это состоит и какой план очистки безопасен.

<details><summary>Ответ</summary>

Состав: старые теги веток и PR, SHA-теги каждого коммита, dangling-манифесты,
неудалённые слои (после удаления манифестов нужен garbage collection), кэш-образы сборок.
План: включить и настроить retention (ветки/PR — 7-14 дней, SHA — 30-90 дней, релизы — вечно),
удалить манифесты, затем запустить **garbage collection** registry (без него место не вернётся),
включить дедупликацию/общие базовые образы, мониторинг роста.

</details>

**D7.** Разработчик запушил образ с токеном внутри в **публичный** registry.
Порядок действий?

<details><summary>Ответ</summary>

Считать токен скомпрометированным: немедленно **отозвать и перевыпустить**;
удалить образ и все теги из registry (и его кэши/зеркала); проверить логи доступа —
кто мог скачать; пересобрать образ без секрета (`--mount=type=secret`);
добавить в CI сканер секретов (gitleaks/trivy secret) и `.dockerignore`.

</details>

**D8.** Приложение в k8s не стартует: `ImagePullBackOff`. Перечисли 6 возможных причин.

<details><summary>Ответ</summary>

(1) Неверное имя/тег образа (опечатка, тега нет в registry); (2) нет
`imagePullSecrets`/прав у service account; (3) registry недоступен по сети/DNS с нод;
(4) rate limit Docker Hub; (5) несовместимая архитектура образа; (6) самоподписанный TLS,
которому не доверяет containerd на нодах; (7) образ удалён retention-политикой.
Диагностика: `kubectl describe pod` (событие с текстом ошибки).

</details>

**D9.** Образ собрался и запушился, но на сервере `docker pull` тянет старую версию,
хотя тег тот же. Почему и как проверить?

<details><summary>Ответ</summary>

Локально уже есть образ с этим тегом, а тег в registry переехал: `docker pull` по тегу
обновит образ, но если деплой использует `imagePullPolicy: IfNotPresent`/старый кэш или
приложение перезапущено без pull — останется старое. Проверить: сравнить
<code v-pre>docker image inspect --format '{{index .RepoDigests 0}}'</code> локально и
`docker manifest inspect` в registry. Лечение: уникальные теги на каждый билд.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое Docker Registry и зачем он нужен?

<details><summary>Ответ</summary>

Хранилище и раздача образов; точка стыковки CI (push) и CD (pull). Без него нельзя
доставить артефакт на серверы/в кластер.

</details>

**2.** Как устроен путь образа от CI до прода?

<details><summary>Ответ</summary>

Коммит → CI (тесты, build, теги) → push в registry → скан/подпись → CD обновляет манифест →
кластер делает pull → контейнер запущен.

</details>

**3.** Как вы тегируете образы? Почему именно так?

<details><summary>Ответ</summary>

Git SHA на каждый коммит + semver-версия на релиз + плавающие major/minor + branch/PR-теги
для превью. Причина: трассируемость до коммита, возможность отката, понятность в проде.

</details>

**4.** Чем тег отличается от дайджеста и что использовать в проде?

<details><summary>Ответ</summary>

Тег — подвижная метка, дайджест — неизменяемый sha256 манифеста. В проде — точная версия,
а для критичных систем — дайджест.

</details>

**5.** Как откатить релиз на предыдущую версию?

<details><summary>Ответ</summary>

Передеплоить предыдущий иммутабельный тег/дайджест (`kubectl set image`, `helm rollback`,
изменение compose + `up -d`). Работает, только если образ ещё в registry.

</details>

**6.** Как понять, какая версия кода сейчас работает в проде?

<details><summary>Ответ</summary>

По тегу образа в манифесте/`docker ps` и по OCI-метке `revision` → коммит.
Поэтому `latest` в проде недопустим.

</details>

**7.** Как хранить креды для registry в CI?

<details><summary>Ответ</summary>

В секретах CI, передавать через `--password-stdin`; лучше — короткоживущие токены,
OIDC/IAM-роли, credential helper; `docker logout` в конце джобы; не коммитить
`~/.docker/config.json`.

</details>

**8.** Что такое immutable tags и зачем?

<details><summary>Ответ</summary>

Запрет перезаписи существующего тега в registry. Гарантирует, что версия всегда означает
один и тот же образ: воспроизводимость, безопасные откаты, честный аудит.

</details>

**9.** Как бороться с rate limit Docker Hub?

<details><summary>Ответ</summary>

Логин техническим аккаунтом, pull-through cache/mirror, зеркалирование базовых образов
в свой registry.

</details>

**10.** Как обеспечить безопасность образов в registry?

<details><summary>Ответ</summary>

Приватность, robot-аккаунты с минимальными правами (CI push, прод pull), immutable tags,
сканирование на CVE, подпись (cosign) с проверкой на деплое, retention и бэкапы,
TLS и аудит доступа.

</details>

---

### 🎯 Чек-лист

- [ ] Объясняю путь коммит → образ → registry → под без запинки
- [ ] Поднял свой registry и запушил в него образ
- [ ] Имею схему тегирования и могу обосновать каждый тег
- [ ] Различаю тег и дайджест, знаю, что использовать в проде
- [ ] Умею смотреть registry через Distribution API и skopeo
- [ ] Знаю, где лежат креды и как их правильно хранить в CI
- [ ] Помню про rate limit Docker Hub и способы обхода
- [ ] Понимаю retention policy и почему релизы из неё исключают
- [ ] Сканирую образы и знаю, зачем их подписывают
