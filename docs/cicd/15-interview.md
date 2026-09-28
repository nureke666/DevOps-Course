---
title: "15. Вопросы с собеседований"
description: "Топ-вопросы про идеальный пайплайн, CI/CD/Deployment, extends/include, GitOps и 52 дополнительных вопроса"
---

# 15. Вопросы с собеседований

> Роадмап → 4. CI/CD → **3. Собесы**
> «Основная масса вопросов по самой концепции/методологии.
> Топ-1 вопрос, который задают буквально всегда: *«Как бы ты построил идеальный пайплайн?»*
> Топ-2 относится к методологии: *«В чем разница Continuous Integration, Continuous Delivery,
> Continuous Deployment?»* Любят спрашивать про `extends`/`include` в GitLab CI.
> Опять же, здесь пригодится всё из двух блоков левее (Linux и Docker).»

---

## 🎯 Часть 1. Главные вопросы роадмапа

### 1. Как бы ты построил идеальный пайплайн? ⭐ топ-1

<details><summary>Ответ</summary>

Отвечать структурой, а не перечислением ключей YAML. Каркас на 2-3 минуты речи:

**1) Уточню контекст** (это уже плюс в глазах собеседующего):
«Пайплайн зависит от того, что за приложение, какая модель ветвления, куда деплоим —
VM или Kubernetes, и какие требования по регламенту релизов. Расскажу типовой вариант
для веб-сервиса в контейнере, деплой на серверы, GitLab CI».

**2) Триггеры.** MR-пайплайн (быстрый, ≤ 10 минут), пайплайн основной ветки (полный),
релизный по тегу, ночной для тяжёлых проверок.

**3) Стадии и почему именно так:**
```text:no-line-numbers
lint (10-30 с)     форматтер, статанализ, детект секретов — дёшево, падаем первыми
test (2-5 мин)     unit + покрытие, quality gate
build (2-5 мин)    ОДНА сборка образа, тег = commit SHA, пуш в registry
scan (1-3 мин)     Trivy по образу и зависимостям, блокировка по Critical
integration        поднять сервис + БД (services), интеграционные тесты
deploy:dev         авто на каждый push в ветку
deploy:staging     авто по мержу в main + smoke
deploy:prod        manual, только из main, protected, + smoke + автооткат
```

**4) Ключевые принципы, которые я закладываю:**
- **build once, deploy many**: один артефакт проходит все окружения, различия — только
  в переменных;
- иммутабельные теги (SHA), никакого `latest` в деплое;
- секреты в CI/CD Variables (masked + protected) или Vault, в репозитории — ничего;
- быстрое раньше медленного; `needs` и кэш для скорости;
- откат = деплой предыдущего тега кнопкой, 2-3 минуты, без сборки;
- smoke-тесты после каждого деплоя — без них «деплой успешен» ничего не значит;
- окружения с `environment`, прод защищён `resource_group` и Protected environments.

**5) Как я пойму, что пайплайн хороший:** MR-пайплайн ≤ 10 минут, доля флаки-падений
около нуля, lead time от мержа до staging — минуты, откат отрепетирован,
и любой инженер команды может объяснить каждую стадию.

> Сильный финал: «И ещё я бы явно описал, чего в пайплайне **нет** и почему —
> например, e2e-тесты не на каждый коммит, а ночью, чтобы не разрушать обратную связь».

</details>

### 2. В чём разница Continuous Integration, Continuous Delivery и Continuous Deployment? ⭐ топ-2

<details><summary>Ответ</summary>

**Коротко:**
- **CI** — практика: разработчики часто (минимум раз в день) вливают изменения в общую
  ветку, и каждое вливание автоматически собирается и тестируется.
- **Continuous Delivery** — каждое прошедшее проверки изменение автоматически доводится
  до состояния «готово к релизу»; **выкат в прод запускает человек**.
- **Continuous Deployment** — то же самое, но **без кнопки**: зелёный пайплайн едет в прод сам.

**Разница Delivery/Deployment — ровно одна ручная кнопка.**

**Что добавить, чтобы ответ был сильным:**
- «CI — это не наличие Jenkins/GitLab, а короткие ветки + частые мержи + автопроверки;
  можно иметь инструмент и не иметь CI».
- «Continuous Deployment требует зрелости: надёжные тесты, smoke после деплоя, canary
  или feature flags, автооткат и мониторинг. Без этого автоматический прод — не зрелость,
  а риск».
- «В GitLab разница выражается буквально одной строкой: `when: manual` на джобе прода».

</details>

### 3. Расскажи про `extends` и `include` в GitLab CI ⭐ спрашивают часто

<details><summary>Ответ</summary>

**`include`** подключает конфигурацию из других файлов:
```yaml
include:
  - local: '/ci/build.yml'                       # файл в этом же репозитории
  - project: 'devops/ci-templates'               # из другого проекта
    ref: 'v1.4.0'                                # ⭐ обязательно пинить версию
    file: '/templates/python.yml'
  - template: 'Jobs/SAST.gitlab-ci.yml'          # шаблон из поставки GitLab
  - remote: 'https://example.com/ci.yml'
  - component: gitlab.com/org/components/build@1.2.0
```

**`extends`** — наследование джоб:
```yaml
.deploy:
  stage: deploy
  script: ["./deploy.sh $ENV_NAME"]

deploy:prod:
  extends: .deploy
  variables: { ENV_NAME: production }
  rules: [{ if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH', when: manual }]
```

**Что обязательно сказать:**
1. `extends` работает **между файлами** (в связке с `include`), а YAML-якоря — только
   внутри одного файла.
2. При `extends` словари (`variables`, `artifacts`) **сливаются**, а массивы
   (`script`, `rules`, `tags`) **заменяются целиком** — это главная ловушка.
   Чтобы дополнить массив, есть `!reference [.job, script]`.
3. Джобы, начинающиеся с точки (`.template`), не выполняются — это шаблоны.
4. `include` без `ref` = чужой коммит может сломать твой пайплайн: всегда пиним версию.
5. Итоговый конфиг после раскрытия смотрится в Pipeline editor → **Full configuration**.

</details>

### 4. Что такое GitOps?

<details><summary>Ответ</summary>

Декларативное желаемое состояние в git + агент в кластере (Argo CD/Flux), который
непрерывно сверяет фактическое состояние с git и приводит к нему. Деплой = мерж,
откат = `git revert`, аудит = `git log`.
Главное отличие от классического CD — **pull вместо push**: креды кластера не хранятся
в CI, входящий доступ в кластер не нужен, дрейф конфигурации обнаруживается и лечится сам.
Секреты при этом — через External Secrets/Sealed Secrets/SOPS/Vault, а не base64 в git.

</details>

### 5. Какие стратегии ветвления знаешь и как выбрать?

<details><summary>Ответ</summary>

GitFlow (main+develop+release+hotfix — релизные циклы, поддержка версий, но долгоживущие
ветки), GitHub Flow (одна main + короткие ветки — под непрерывный выкат), GitLab Flow
(ветки окружений, код движется только вперёд), Trunk-Based (всё в main, ветки на часы,
обязательны feature flags).

Выбор — **от процесса релиза**: регламент и приёмка QA → GitFlow/release-ветки;
частые выкаты и владение продом → GitHub Flow/Trunk-Based. И сразу добавить, что модель
определяет `rules`, соответствие «ветка → окружение» и места ручных подтверждений.

</details>

### 6. Какие инструменты интегрируются в CI/CD и как?

<details><summary>Ответ</summary>

- **Docker** — три роли: среда выполнения джобы (`image:`), объект сборки
  (dind/buildx или без privileged — rootless BuildKit/buildah, + пуш в registry), способ доставки
  (на сервере запускается тот же образ).
- **Ansible** — provisioning серверов и деплой: джоба вызывает плейбук и передаёт
  `app_image=registry/app:<sha>`; даёт идемпотентность и inventory.
- **Terraform** — инфраструктура, обычно отдельным пайплайном (plan → ручное подтверждение → apply).
- **Helm/kubectl/Argo CD** — деплой в Kubernetes.
- **SonarQube, Trivy, Semgrep, Gitleaks** — качество и безопасность, quality gates.
- **Vault/External Secrets** — секреты.
- **Prometheus/Grafana** — проверка после деплоя и автооткат по метрикам.

</details>

---

## 📚 Часть 2. Дополнительные вопросы с ответами

### Методология

**1. Зачем вообще CI/CD?**

<details><summary>Ответ</summary>

Сокращает время от идеи до пользователя, уменьшает риск релиза (маленькие изменения),
делает процесс повторяемым и не зависящим от конкретного человека, даёт быструю обратную
связь о качестве.

</details>

**2. Что такое артефакт и чем он отличается от кэша?**

<details><summary>Ответ</summary>

Артефакт — результат, нужный дальше или для релиза (образ, бинарь, отчёт); хранится
и версионируется, его потеря ломает процесс. Кэш — ускоритель (зависимости), его потеря
только замедляет.

</details>

**3. Почему нельзя пересобирать образ перед продом?**

<details><summary>Ответ</summary>

Потому что в прод поедет не то, что тестировали: могли измениться зависимости, базовый
образ, порядок слоёв. Все проверки обесцениваются, расследование инцидента усложняется.

</details>

**4. Чем деплой отличается от релиза?**

<details><summary>Ответ</summary>

Деплой — техническое размещение кода в окружении; релиз — момент, когда функциональность
доступна пользователям. Feature flags разводят их во времени.

</details>

**5. Какие метрики у CI/CD?**

<details><summary>Ответ</summary>

DORA: частота деплоев, lead time, change failure rate, MTTR. Плюс операционные:
длительность пайплайна, доля падений, доля флаки-тестов.

</details>

**6. Что делать, если пайплайн идёт 45 минут?**

<details><summary>Ответ</summary>

Профилировать джобы; кэш зависимостей и слоёв; `needs`/DAG; параллель и шардирование;
`rules: changes`; разделить MR-пайплайн и полный; вынести e2e в nightly; добавить раннеров;
`interruptible` + авто-отмена.

</details>

**7. Как выкатывать без даунтайма?**

<details><summary>Ответ</summary>

Rolling/blue-green/canary + healthcheck и readiness; миграции по expand/contract;
совместимость версий API; smoke после выката.

</details>

**8. Как организовать откат?**

<details><summary>Ответ</summary>

Иммутабельные теги, предыдущий образ в registry, отдельная джоба/кнопка отката,
совместимая схема БД, регулярные учения. Цель — минуты и без пересборки.

</details>

**9. Что такое quality gate?**

<details><summary>Ответ</summary>

Автоматический порог, блокирующий продвижение: покрытие, уязвимости, линтер, smoke.

</details>

**10. Что такое feature flags и зачем они в CI/CD?**

<details><summary>Ответ</summary>

Переключатели функциональности в проде. Позволяют мержить незаконченное (нужно
для trunk-based), включать фичу постепенно, откатывать без деплоя.

</details>

### GitLab CI

**11. Pipeline, stage, job — что это?**

<details><summary>Ответ</summary>

Pipeline — весь запуск; stage — этап (последовательно); job — задача (параллельно
внутри стадии).

</details>

**12. Как передать файлы между джобами?**

<details><summary>Ответ</summary>

`artifacts: paths:` (+ `needs`); переменные — через `artifacts: reports: dotenv`.
Общей ФС у джоб нет.

</details>

**13. `artifacts` vs `cache`?**

<details><summary>Ответ</summary>

Артефакты в GitLab, гарантированы, для передачи результатов; кэш на раннере,
не гарантирован, только для ускорения.

</details>

**14. `rules` vs `only/except`?**

<details><summary>Ответ</summary>

`rules` поддерживают сложные условия, регулярки, `changes`, `exists`, переопределение
переменных и `when`; `only/except` — легаси и не смешиваются с `rules`.

</details>

**15. Как запустить джобу только на main / по тегу / в MR?**

<details><summary>Ответ</summary>

`$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH`; `$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/`;
`$CI_PIPELINE_SOURCE == "merge_request_event"`.

</details>

**16. Что такое `workflow:rules`?**

<details><summary>Ответ</summary>

Правила создания **всего** пайплайна; чаще всего решают проблему дублирующихся
branch- и MR-пайплайнов.

</details>

**17. Где хранить секреты?**

<details><summary>Ответ</summary>

CI/CD Variables с флагами masked и protected, тип File для ключей, environment scope;
зрелый вариант — Vault/OIDC. Маскирование не защищает от намеренного вывода.

</details>

**18. Что такое `needs`?**

<details><summary>Ответ</summary>

Явные зависимости между джобами (DAG): джоба стартует, не дожидаясь всей стадии.
`needs: []` — старт сразу.

</details>

**19. Что такое `environment` и что он даёт?**

<details><summary>Ответ</summary>

Учёт деплоев: история, url, кнопки re-deploy/rollback, scope переменных, защита
окружения, динамические review-стенды.

</details>

**20. Как запретить одновременные деплои?**

<details><summary>Ответ</summary>

`resource_group` (+ Protected environments, отмена устаревших пайплайнов).

</details>

**21. Как собрать Docker-образ в GitLab CI?**

<details><summary>Ответ</summary>

`image: docker` + `services: docker:dind` (нужен privileged-раннер), либо без демона
и privileged — rootless BuildKit (`buildctl-daemonless.sh`) или buildah, либо buildx с кэшем
в registry. Логин — предопределёнными `CI_REGISTRY_*`. Kaniko архивирован в 2025 — только legacy.

</details>

**22. Чем сборка без демона (rootless BuildKit, buildah) лучше dind?**

<details><summary>Ответ</summary>

Не требует privileged и докер-демона — безопаснее для общих раннеров и k8s;
кэш слоёв хранится в registry. Цена — нет `docker run` в джобе, а rootless-режиму нужны
послабленные seccomp/AppArmor (что всё равно несравнимо безопаснее privileged).

</details>

**23. Как сервер получает доступ к приватному registry?**

<details><summary>Ответ</summary>

Deploy Token со scope `read_registry` (или технический пользователь); `$CI_JOB_TOKEN`
живёт только во время джобы и для этого не годится.

</details>

**24. Что такое GitLab Runner и какие бывают executors?**

<details><summary>Ответ</summary>

Агент, забирающий джобы (исходящим соединением). Executors: shell, docker,
docker+machine, kubernetes, ssh, custom.

</details>

**25. Почему джоба «stuck»?**

<details><summary>Ответ</summary>

Нет онлайн-раннера, не совпали теги, раннер не берёт untagged, занят, protected-настройка,
закончились минуты, забит диск.

</details>

**26. Чем опасен shell-executor?**

<details><summary>Ответ</summary>

Кто пишет `.gitlab-ci.yml`, тот выполняет команды на хосте раннера с правами
пользователя `gitlab-runner`.

</details>

**27. Как ускорить установку зависимостей?**

<details><summary>Ответ</summary>

Кэш каталога пакетного менеджера с ключом по lock-файлу, `policy: pull` в тестовых
джобах, детерминированная установка (`npm ci`).

</details>

**28. Что такое child pipeline?**

<details><summary>Ответ</summary>

Отдельный пайплайн внутри проекта, запускаемый через `trigger: include:`;
типичное применение — монорепозиторий и динамически сгенерированные конфиги.

</details>

**29. Как запустить пайплайн в другом проекте?**

<details><summary>Ответ</summary>

`trigger: project: group/other` (+ `strategy: depend`, переменные); принимающий проект
видит `$CI_PIPELINE_SOURCE == "pipeline"`.

</details>

**30. Что делает `interruptible`?**

<details><summary>Ответ</summary>

Позволяет отменять устаревшие пайплайны при новом пуше — экономит ресурсы раннеров.

</details>

### Jenkins

**31. Архитектура Jenkins?**

<details><summary>Ответ</summary>

Controller (UI, конфигурация, планирование, история, креды) + агенты (выполнение сборок);
связь по SSH или JNLP; распределение по labels; на контроллере сборки не запускают.

</details>

**32. Где Jenkins хранит состояние?**

<details><summary>Ответ</summary>

В `JENKINS_HOME`: джобы, плагины, креды, история. Бэкап Jenkins = бэкап этого каталога
(плюс JCasC и `Jenkinsfile` в git).

</details>

**33. Декларативный или скриптовый пайплайн?**

<details><summary>Ответ</summary>

Декларативный — дефолт (структура, валидация, читаемость); скриптовый — когда нужна
сложная динамическая логика; сложные куски можно оборачивать в `script { }`.

</details>

**34. Как хранить секреты в Jenkins?**

<details><summary>Ответ</summary>

Credentials (Secret text, Username/Password, SSH key, Secret file) + `withCredentials`
или `environment { credentials('id') }`; не подставлять секрет через двойные кавычки
в `sh`, ограничивать область папками и правами.

</details>

**35. Что такое Shared Libraries?**

<details><summary>Ответ</summary>

Общий код пайплайнов в отдельном репозитории: `vars/` — шаги, `src/` — классы,
`resources/` — файлы. Подключается `@Library('lib@v1.4.0') _`; версию обязательно пинить.
Аналог `include` + `extends` в GitLab.

</details>

**36. Что такое Multibranch Pipeline?**

<details><summary>Ответ</summary>

Тип джобы, автоматически создающий пайплайны для веток и PR/MR, где есть `Jenkinsfile`,
и удаляющий джобы исчезнувших веток.

</details>

**37. Как сделать ручное подтверждение?**

<details><summary>Ответ</summary>

Шаг `input` с `submitter` и таймаутом; ожидание не должно занимать агента (`agent none`).

</details>

**38. Почему workspace в Jenkins — источник проблем?**

<details><summary>Ответ</summary>

Он переиспользуется между сборками: остаются файлы от прошлых запусков.
Лечится `cleanWs()` и docker/k8s-агентами.

</details>

**39. Что такое UNSTABLE?**

<details><summary>Ответ</summary>

Сборка выполнилась, но с проблемами (обычно упавшие тесты или предупреждения анализаторов).

</details>

**40. Jenkins или GitLab CI — что выбрать?**

<details><summary>Ответ</summary>

Для нового проекта на GitLab — GitLab CI (проще, конфиг в репо, нет обслуживания).
Jenkins — когда он уже внедрён, нужна независимость от VCS, закрытый контур,
нестандартные интеграции и железо.

</details>

### Безопасность и эксплуатация

**41. Как не пустить уязвимость в прод?**

<details><summary>Ответ</summary>

Скан зависимостей и образа (Trivy/SCA), блокировка по Critical, обновление базовых
образов, периодический пересканер уже задеплоенного, деплой только образов, прошедших скан.

</details>

**42. Что делать, если секрет утёк в лог?**

<details><summary>Ответ</summary>

Считать скомпрометированным: ротация, удаление логов/истории, аудит использования,
исправление причины, автоматическая проверка (gitleaks) в pre-commit и CI.

</details>

**43. Что такое supply chain security?**

<details><summary>Ответ</summary>

Защита цепочки сборки: пин базовых образов (digest), lock-файлы, контролируемые
обновления, SBOM, подпись образов (cosign) и проверка при деплое, минимальные образы,
non-root, защита раннеров и registry.

</details>

**44. Как понять, что сейчас в проде?**

<details><summary>Ответ</summary>

Тег образа = SHA коммита, запись в Environments/Deployments, эндпоинт `/version`
в приложении. Не «Петя помнит».

</details>

**45. Что делать с флакающими тестами?**

<details><summary>Ответ</summary>

Карантин + тикет + починка причины. `retry` допустим только для инфраструктурных сбоев.

</details>

**46. Как внедрить блокирующую проверку в команде?**

<details><summary>Ответ</summary>

Поэтапно: сначала отчёт (`allow_failure: true`), затем baseline и согласование порогов,
потом блокировка; пороги ужесточать постепенно.

</details>

**47. Как организовать CI для 50 микросервисов?**

<details><summary>Ответ</summary>

Общие шаблоны (`include` с пином версии / Shared Library), единый стандарт стадий,
монорепо → child pipelines с `rules: changes`, автоскейлинг раннеров, централизованные
секреты, дашборд по длительности и падениям пайплайнов.

</details>

**48. Kaniko заархивирован — чем собирать образы в k8s-раннере?**

<details><summary>Ответ</summary>

Google заархивировал kaniko 3 июня 2025, `gcr.io/kaniko-project/executor` больше не обновляется;
форк Chainguard даёт только security-фиксы. По умолчанию — **rootless BuildKit**
(`moby/buildkit:rootless` + `buildctl-daemonless.sh`, `--oci-worker-no-process-sandbox`,
кэш `--export-cache/--import-cache type=registry`): тот же движок, что `docker build`, без privileged.
Честно назвать цену: kaniko работал вообще без послаблений, а rootless BuildKit нужны
seccomp/AppArmor `Unconfined` (или кастомный профиль) для контейнера сборки. Альтернатива —
**buildah** (`STORAGE_DRIVER=vfs`, `buildah build/push`), особенно в OpenShift; для большого
кластера — отдельный сервис `buildkitd` с тёплым кэшем. Существующие kaniko-джобы — временно
на образ форка, затем миграция. dind/privileged в k8s — нет.

</details>

### GitHub Actions

**49. Чем GitHub Actions отличается от GitLab CI и как бы ты перенёс пайплайн?**

<details><summary>Ответ</summary>

Принципы те же, модель исполнения другая: стадий нет — порядок только через `needs`; каждая
джоба — чистая VM, файлы передаются артефактами, значения — через `outputs`; шаги — экшены
(чужой код); права токена задаются `permissions`. Перенос по словарю: `rules` → `on` + `if`,
`dotenv` → `$GITHUB_OUTPUT`, `resource_group` → `concurrency`, `include` → reusable workflow,
`extends` → composite action, `when: manual` → environment с required reviewers, registry → GHCR.
Какое-то время гоняю оба CI параллельно и сверяю результат и время (см. [16. GitHub Actions](/cicd/16-github-actions)).

</details>

**50. Как дать workflow доступ в AWS без ключей и что при этом чаще всего ломается?**

<details><summary>Ответ</summary>

OIDC: IAM provider `token.actions.githubusercontent.com` с audience `sts.amazonaws.com`, роль с trust
policy по `aud` и `sub`, в джобе `permissions: id-token: write` и `aws-actions/configure-aws-credentials`.
Секретов в CI нет, креды живут час. Ломается `sub`: у джобы с `environment:` он равен
`repo:org/repo:environment:prod` (ref пропадает), а репо, созданные после 15.07.2026, получают
immutable `sub` с числовыми ID. Без условия по `sub` роль примет любой репозиторий на GitHub.

</details>

**51. Какие дыры в безопасности типичны для GitHub Actions?**

<details><summary>Ответ</summary>

(1) **Pwn request** — `pull_request_target` работает с секретами и write-токеном, а в нём делают
checkout кода PR и запускают его; с 2025–2026 GitHub закрывает это по умолчанию (workflow из default
branch, checkout `v7` отказывает), но правило одно: код PR — только в `pull_request`. (2) **Script
injection** — вставка события (заголовок/тело PR и т.п.) прямо в текст `run:`; недоверенное передают
через `env:`. (3) **Сторонние экшены по тегу** — кейс `tj-actions/changed-files` (март 2025): пин по
полному SHA, Dependabot, allowlist. (4) Лишние права `GITHUB_TOKEN` — `permissions: contents: read`
по умолчанию. Проверяю всё это `zizmor` в CI.

</details>

**52. Когда нужны self-hosted раннеры и как их не превратить в дыру?**

<details><summary>Ответ</summary>

Когда нужен доступ во внутреннюю сеть, спецжелезо (GPU, arm) или на большом объёме своё дешевле.
В k8s — ARC (runner scale sets, Helm-чарты `gha-runner-scale-set-controller` + `gha-runner-scale-set`,
аутентификация GitHub App): эфемерный под на каждую джобу, автоскейл от нуля. Правила: никогда
на публичных репо (PR из форка = чужой код в твоей сети), только эфемерные раннеры, runner groups
с ограничением репо, изоляция сети, в облако — по OIDC, а не ключами на хосте.

</details>

---

## 🧠 Как отвечать: практические приёмы

1. **Сначала структура, потом детали.** «Расскажу по слоям: триггеры → стадии → артефакт
   → окружения → откат» звучит сильнее, чем поток ключей YAML.
2. **Уточняющий вопрос — это плюс.** «Деплой на VM или в Kubernetes?» показывает,
   что ты понимаешь зависимость решения от контекста.
3. **Привязывай к опыту.** «В своём проекте я сделал так: …, и это дало …» —
   даже учебный проект работает, если ты честно говоришь, что он учебный.
4. **Называй компромиссы.** Идеальных решений нет: dind быстрый, но privileged;
   canary безопасный, но требует мониторинга. Умение назвать цену — признак инженера.
5. **Не говори «всегда» и «никогда» без основания.** Исключение — `latest` в деплое
   и секреты в git: тут «никогда» уместно.
6. **Если не знаешь — скажи, как выяснишь.** «Не работал с Tekton, но по опыту
   с GitLab CI и Argo CD ожидал бы, что…»
7. **Держи наготове три истории:** как ускорил пайплайн, как чинил инцидент,
   как внедрял проверку/стандарт.

---

## ✅ Финальный самоконтроль

Отвечай вслух, без подглядывания. Если запнулся — возвращайся к теме в скобках.

- [ ] Разница CI / Delivery / Deployment (01)
- [ ] «Идеальный пайплайн» за 2-3 минуты (03)
- [ ] Почему build once, deploy many (01, 03)
- [ ] Чем отличаются окружения, если артефакт один (03)
- [ ] Стратегии ветвления и выбор под процесс (02)
- [ ] Что такое GitOps и pull vs push (04)
- [ ] pipeline/stage/job, artifacts vs cache (05, 06)
- [ ] `rules` и как запустить джобу в нужный момент (06)
- [ ] Где хранить секреты и как их не утечь (06, 13)
- [ ] `extends` vs якоря, `include` с `ref` (08)
- [ ] `needs` и как ускорить пайплайн (08)
- [ ] Сборка образа: dind/buildx, rootless BuildKit, buildah и их цена; почему kaniko — legacy (07)
- [ ] Executors раннера и почему джоба stuck (09)
- [ ] Архитектура Jenkins, credentials, Shared Libraries (10-12)
- [ ] Скан образов и quality gates (13)
- [ ] Процедура отката и время (03, 14)
- [ ] Как понять, что сейчас в проде (02, 13)
- [ ] GitHub Actions: перенос с GitLab, OIDC и формат `sub`, pwn request, SHA-пиннинг, ARC (16)

---

## 🗺️ Что дальше после этого блока

Следующий шаг роадмапа — **Kubernetes**: там CI/CD превращается в GitOps-процесс
(тема 04), деплой становится `helm upgrade`/Argo CD, а раннеры переезжают в кластер
(kubernetes executor, тема 09). Всё, что ты собрал здесь — артефакт по SHA, окружения,
quality gates, откат — переносится туда почти без изменений; меняется только способ
доставки.
