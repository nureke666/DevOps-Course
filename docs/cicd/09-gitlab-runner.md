---
title: "09. GitLab Runner"
description: "Установка, регистрация, executors (shell/docker/kubernetes), config.toml, кэш, диагностика stuck-джоб"
---

# 09. GitLab Runner

> Роадмап → 4. CI/CD → Инструменты → GitLab CI → **Хорошо**:
> «GitLab Runner — установка, настройка, типы executor'ов (shell, docker, kubernetes)».
> **После темы ты умеешь:** поставить и зарегистрировать раннер, выбрать executor,
> разобраться в `config.toml`, настроить кэш и понять, почему джоба «stuck».

---

## 1. Что такое раннер и как он общается с GitLab

```text:no-line-numbers
┌──────────────┐   1. раннер САМ опрашивает GitLab (long polling, исходящее соединение)
│ GitLab       │ ◄──────────────────────────────────────────────┐
│ (сервер/SaaS)│   2. отдаёт джобу, если есть подходящая        │
└──────────────┘ ──────────────────────────────────────────────►│
                 3. раннер клонирует репо, выполняет script     │
                 4. стримит лог, загружает артефакты            │
                                                     ┌──────────┴─────────┐
                                                     │  GitLab Runner     │
                                                     │  (твоя VM / k8s)   │
                                                     └────────────────────┘
```

**Важно:** GitLab **не подключается** к раннеру — раннер сам ходит наружу.
Поэтому раннер можно поставить в закрытом контуре без белого IP и входящих правил firewall.

### Типы раннеров по области видимости

| Тип | Где настраивается | Кому доступен |
|-----|-------------------|---------------|
| **Instance (shared)** | Админка GitLab / gitlab.com | Всем проектам инстанса |
| **Group** | Настройки группы | Всем проектам группы |
| **Project (specific)** | Settings → CI/CD → Runners | Одному проекту |

---

## 2. Установка

```bash
# Debian/Ubuntu
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | sudo bash
sudo apt update && sudo apt install -y gitlab-runner

sudo systemctl status gitlab-runner
sudo gitlab-runner --version

# Вариант «в докере» (удобно для учебного стенда)
docker run -d --name gitlab-runner --restart always \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  -v /var/run/docker.sock:/var/run/docker.sock \
  gitlab/gitlab-runner:latest
```

При пакетной установке создаётся системный пользователь `gitlab-runner`,
сервис systemd и каталог конфигурации `/etc/gitlab-runner/`.

---

## 3. Регистрация

Современный способ (GitLab 16+): сначала создаём раннер в UI и получаем **authentication token**
(`glrt-...`), затем регистрируем:

```bash
sudo gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.com/" \
  --token "$RUNNER_AUTH_TOKEN" \
  --executor "docker" \
  --docker-image "alpine:3.20" \
  --description "vm-docker-runner"
```

Старый способ (registration token `glrt-`/`GR1348941...`, до 16.x) выглядел так же,
но с `--registration-token` и заданием `--tag-list`/`--run-untagged` прямо в команде;
в новых версиях теги и настройки задаются в UI при создании раннера.

```bash
sudo gitlab-runner list                 # что зарегистрировано
sudo gitlab-runner verify               # живы ли раннеры
sudo gitlab-runner unregister --all-runners
sudo gitlab-runner restart
```

**Теги** — механизм маршрутизации джоб:
```yaml
job:
  tags: [docker, linux]     # поедет на раннер с ТАКИМИ ЖЕ тегами
```
Если у раннера теги есть, а джоба без тегов — раннер её не возьмёт,
пока не включено «Run untagged jobs».

---

## 4. Executors — главное отличие раннеров

| Executor | Где выполняется джоба | Плюсы | Минусы |
|----------|-----------------------|-------|--------|
| **shell** | Прямо на хосте, от имени `gitlab-runner` | Простота, доступ к локальным инструментам | Грязное окружение, состояние между сборками, риск (сборка = доступ к хосту) |
| **docker** | В контейнере из `image:` | ⭐ Чистое окружение, изоляция, воспроизводимость | Нужен docker на хосте; dind требует privileged |
| **docker+machine** | Автоподнимаемые VM (autoscaling) | Масштабирование под нагрузку | Сложнее, стоит денег; legacy |
| **kubernetes** | Под в кластере на каждую джобу | ⭐ Эластичность, изоляция, k8s-нативно | Нужен кластер; сборка образов только без демона (rootless BuildKit/buildah) |
| **ssh** | На удалённой машине по SSH | Для экзотики/железа | Нет изоляции, медленно |
| **custom** | Свой драйвер | Любые сценарии (LXD, Podman) | Пишешь сам |

**Как выбирать:**
- учебный стенд/простой проект → **docker**;
- нужен доступ к железу, GPU, специфичному ПО → **shell** (с осознанием рисков);
- есть Kubernetes → **kubernetes**;
- много нагрузки и облако → автоскейлинг (docker+machine / k8s / GitLab Runner Autoscaler).

> ⚠️ **shell-executor** = джоба выполняется под пользователем `gitlab-runner` на хосте
> со всем его доступом. Любой, кто может править `.gitlab-ci.yml`, фактически получает
> shell на этой машине. Никогда не ставь shell-раннер на сервер с продом.

---

## 5. `config.toml` — где живёт вся настройка

`/etc/gitlab-runner/config.toml` (или `~/.gitlab-runner/config.toml` для пользовательской установки):

```toml
concurrent = 4              # сколько джоб ОДНОВРЕМЕННО на всём раннере
check_interval = 3          # как часто опрашивать GitLab (сек)
log_level = "info"

[session_server]
  session_timeout = 1800

[[runners]]
  name = "vm-docker-runner"
  url = "https://gitlab.com/"
  token = "glrt-xxxxxxxx"
  executor = "docker"
  limit = 2                 # лимит джоб для ЭТОГО раннера
  output_limit = 16384      # максимальный размер лога (КБ)
  environment = ["DOCKER_DRIVER=overlay2", "TZ=Europe/Astana"]

  [runners.docker]
    image = "alpine:3.20"          # образ по умолчанию, если в джобе нет image:
    privileged = false             # true — только если нужен dind!
    volumes = ["/cache"]           # кэш между джобами
    pull_policy = ["always"]       # always | if-not-present | never
    shm_size = 268435456
    network_mtu = 1450
    memory = "2g"
    cpus = "2"
    allowed_images = ["python:*", "node:*", "docker:*"]   # ограничение образов

  [runners.cache]
    Type = "s3"                    # распределённый кэш между раннерами
    Shared = true
    [runners.cache.s3]
      ServerAddress = "s3.example.com"
      BucketName = "gitlab-runner-cache"
      AccessKey = "..."
      SecretKey = "..."
      Insecure = false
```

После правки: `sudo gitlab-runner restart` (или `sudo systemctl restart gitlab-runner`).
Проверить синтаксис: `sudo gitlab-runner verify` / `gitlab-runner run --debug` (на время отладки).

### `concurrent` vs `limit`

```text:no-line-numbers
concurrent = 4        ← глобально: не больше 4 джоб одновременно на этой машине
[[runners]] limit = 2 ← этот конкретный раннер возьмёт не больше 2 из них
```

---

## 6. Настройка раннера под Docker-in-Docker

```toml
[[runners]]
  executor = "docker"
  [runners.docker]
    image = "docker:29"
    privileged = true                                   # ⚠️ обязательно для dind
    volumes = ["/certs/client", "/cache"]
```
Это включает возможность запускать `services: docker:dind` (тема 07).
Такой раннер — **только** для доверенных проектов.

Альтернатива без privileged: раннер обычный, а образы собираются **rootless BuildKit** или
**buildah** (kaniko архивирован в 2025 — см. [07. Docker в GitLab CI](/cicd/07-gitlab-ci-docker)).
Честная оговорка: rootless-сборке нужны user namespaces, и дефолтный seccomp/AppArmor их режет —
на таком раннере задают `security_opt` в `[runners.docker]` (лучше кастомным seccomp-профилем,
чем `["seccomp:unconfined", "apparmor:unconfined"]`). Это всё равно намного меньше, чем `privileged`.

---

## 7. Kubernetes executor (кратко)

```toml
[[runners]]
  executor = "kubernetes"
  [runners.kubernetes]
    namespace = "gitlab-runner"
    image = "alpine:3.20"
    cpu_request = "500m"
    memory_request = "1Gi"
    cpu_limit = "2"
    memory_limit = "4Gi"
    poll_timeout = 180
    service_account = "gitlab-runner"
```
Ставится обычно Helm-чартом `gitlab/gitlab-runner`. На каждую джобу создаётся под
с контейнерами: `build` (твой `image`), `helper` (git/артефакты) и по контейнеру
на каждый `services`. Масштабирование — нативно кластером.

---

## 8. Обслуживание раннера

```bash
# Логи
sudo journalctl -u gitlab-runner -f
sudo gitlab-runner --debug run          # запустить в фореграунде с отладкой

# Место (главная эксплуатационная проблема!)
docker system df
docker system prune -a --volumes        # на docker-executor
du -sh /home/gitlab-runner/builds/*     # на shell-executor
du -sh /srv/gitlab-runner/*

# Кэш раннера
sudo rm -rf /var/lib/docker/volumes/runner-*-cache-*    # аккуратно!
# либо в UI: Settings → CI/CD → Clear runner caches
```

**Регулярные задачи:** чистка кэша и «повисших» контейнеров, обновление версии раннера
(должна быть не ниже версии GitLab), мониторинг диска и очереди джоб, ротация токенов.

**Метрики:** раннер отдаёт Prometheus-метрики (`listen_address = ":9252"`):
число выполняемых джоб, время ожидания, ошибки — полезно для алерта «очередь растёт».

---

## 9. Диагностика: «джоба stuck / pending»

```text:no-line-numbers
1. Есть ли онлайн-раннеры у проекта?      Settings → CI/CD → Runners (зелёная точка)
2. Совпадают ли теги?                     tags в джобе == теги раннера
3. Раннер берёт untagged-джобы?           галочка "Run untagged jobs"
4. Не занят ли он?                        concurrent / limit, очередь
5. Protected-ветка?                       раннер помечен "Protected" → берёт только защищённые
6. Живой ли сервис?                       systemctl status gitlab-runner; gitlab-runner verify
7. Место на диске?                        df -h — забитый диск = падения и зависания
8. Версия раннера?                        старее GitLab → несовместимость
9. CI-минуты (gitlab.com)               → квота исчерпана
```

| Ошибка | Причина |
|--------|---------|
| `This job is stuck because...` | Нет подходящего раннера (теги/статус/protected) |
| `ERROR: Preparation failed: Cannot connect to the Docker daemon` | На хосте нет/не запущен docker, либо пользователь `gitlab-runner` не в группе `docker` |
| `ERROR: Job failed (system failure): pod ... OOMKilled` | Лимиты памяти у k8s-executor |
| `no space left on device` | Забит диск раннера (кэш, образы, builds) |
| `WARNING: Failed to pull image` | Нет доступа к registry / rate limit / неверный `pull_policy` |
| Джоба берёт старый образ | `pull_policy = "if-not-present"` |

---

## 10. Безопасность раннеров

1. **shell-executor** — доступ к хосту у любого, кто правит `.gitlab-ci.yml`. Только
   для доверенных проектов, никогда на проде.
2. **privileged (dind)** — эквивалент root на хосте раннера; отдельный раннер
   под доверенные проекты, либо rootless BuildKit/buildah вместо него.
3. **Проброс `/var/run/docker.sock`** — то же самое, ещё и с доступом к соседним сборкам.
4. **Protected runners** — отдельные раннеры для защищённых веток и прод-деплоя.
5. `allowed_images` / `allowed_services` — ограничение, что вообще можно запускать.
6. Раннеры не должны иметь лишних прав в инфраструктуре: доступ к проду — через
   ограниченного пользователя и отдельные ключи, а не «раннер всё может».
7. Регулярно обновлять раннер и базовые образы; токены хранить как секреты.

---

## 💼 Как это в DevOps

- Свой раннер ставят, когда: нужен доступ во внутреннюю сеть, специфичное железо/софт,
  нет минут на shared, требования безопасности, дорогие сборки.
- Три самых частых инцидента с раннерами: **закончилось место**, **джоба stuck из-за тегов**,
  **раннер старее GitLab**.
- Хорошая практика: раннеры описаны в IaC (Ansible/Terraform), а не настроены руками;
  `config.toml` — в репозитории (без токенов).
- Разделение раннеров по назначению: `build` (мощные, privileged), `test` (много, дешёвые),
  `deploy` (protected, с доступом к окружениям).

---

## 📌 Шпаргалка

```bash
# установка и регистрация
curl -L https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh | sudo bash
sudo apt install -y gitlab-runner
sudo gitlab-runner register --non-interactive --url https://gitlab.com/ \
  --token "$TOKEN" --executor docker --docker-image alpine:3.20

# управление
sudo gitlab-runner list | verify | restart | unregister --all-runners
sudo journalctl -u gitlab-runner -f
sudo nano /etc/gitlab-runner/config.toml && sudo gitlab-runner restart
```

| Параметр | Где | Зачем |
|----------|-----|-------|
| `concurrent` | верх `config.toml` | Джоб одновременно на машине |
| `limit` | `[[runners]]` | Джоб у конкретного раннера |
| `executor` | `[[runners]]` | shell / docker / kubernetes |
| `privileged` | `[runners.docker]` | Нужен для dind (риск!) |
| `pull_policy` | `[runners.docker]` | always — всегда свежий образ |
| `volumes = ["/cache"]` | `[runners.docker]` | Кэш между джобами |
| `[runners.cache] Type="s3"` | `[[runners]]` | Общий кэш для нескольких раннеров |
| `allowed_images` | `[runners.docker]` | Ограничить образы |
| Теги | UI раннера | Маршрутизация джоб |
| Protected | UI раннера | Только защищённые ветки |

---

## 🧠 Что запомнить

1. Раннер сам опрашивает GitLab — входящий доступ к нему не нужен (важно для закрытых контуров).
2. Раннеры бывают instance/group/project; джобы маршрутизируются **тегами**.
3. Executor определяет, где выполняется джоба: shell (на хосте), docker (в контейнере),
   kubernetes (под на джобу).
4. docker-executor — дефолт: чистое окружение на каждую джобу.
5. shell-executor даёт доступ к хосту тому, кто пишет `.gitlab-ci.yml`.
6. `privileged = true` нужен для dind и равносилен root на хосте раннера.
7. Вся настройка — в `config.toml`; после правки раннер надо перезапустить.
8. `concurrent` — глобальный лимит параллельных джоб, `limit` — на конкретный раннер.
9. Кэш между раннерами работает только через distributed cache (S3/совместимое хранилище).
10. «Stuck» — почти всегда теги, отсутствие онлайн-раннера или protected-настройка.
11. Забитый диск — самая частая эксплуатационная авария раннера; нужна регулярная чистка.
12. Разделяй раннеры по назначению и правам: build / test / protected deploy.

---

## Задачи

> Лаба: учебная VM (та же, что в блоке Linux) + проект на gitlab.com.
> ⚠️ Не регистрируй учебный раннер на рабочем сервере и не давай ему прод-доступов.

---

### Блок A. Теория

**A1.** Кто к кому подключается: GitLab к раннеру или раннер к GitLab? Почему это важно
для закрытых контуров?

<details><summary>Ответ</summary>

Раннер сам подключается к GitLab (исходящее соединение, long polling) и запрашивает
джобы. Это позволяет ставить раннеры за NAT и в закрытых контурах: не нужен белый IP
и входящие правила firewall.

</details>

**A2.** Какие бывают раннеры по области видимости? Где каждый настраивается?

<details><summary>Ответ</summary>

Instance/shared (админка инстанса, доступен всем проектам), group (настройки группы,
доступен проектам группы), project/specific (Settings → CI/CD → Runners конкретного проекта).

</details>

**A3.** Что такое теги раннера и как они влияют на выбор джобы?

<details><summary>Ответ</summary>

Теги — метки раннера; джоба с `tags:` попадёт только на раннер, у которого есть все
указанные теги. Это механизм маршрутизации: «эта джоба — на мощный раннер, эта — на
раннер с доступом к проду».

</details>

**A4.** Что произойдёт с джобой без `tags`, если у всех раннеров теги заданы?

<details><summary>Ответ</summary>

Джоба останется в pending и в итоге станет stuck, если ни у одного раннера
не включена опция «Run untagged jobs».

</details>

**A5.** Перечисли executors и скажи, где выполняется джоба в каждом случае.

<details><summary>Ответ</summary>

shell — на самом хосте от имени пользователя `gitlab-runner`; docker — в контейнере
из `image`; docker+machine — на автоматически поднимаемых VM; kubernetes — в поде кластера;
ssh — на удалённой машине; custom — как опишет драйвер.

</details>

**A6.** Почему shell-executor опасен? Сформулируй риск одним предложением.

<details><summary>Ответ</summary>

Любой, кто может изменить `.gitlab-ci.yml`, выполняет произвольные команды
на машине раннера с правами пользователя `gitlab-runner` — то есть фактически получает
доступ к хосту.

</details>

**A7.** Чем docker-executor лучше shell для типового проекта? Три аргумента.

<details><summary>Ответ</summary>

(1) Чистое окружение на каждую джобу — нет наследования состояния;
(2) воспроизводимость: окружение задаётся образом и версионируется;
(3) изоляция между джобами и проектами; (4) легко менять версии рантайма без правки хоста.

</details>

**A8.** Когда выбирают kubernetes-executor и как там собирают образы?

<details><summary>Ответ</summary>

Когда есть кластер и нужна эластичность: под на каждую джобу, лимиты ресурсов,
автоматическое масштабирование. Образы там собирают без демона — rootless BuildKit/buildah
(kaniko архивирован в 2025), поскольку privileged-подов обычно избегают.

</details>

**A9.** Что делает `concurrent` и чем отличается от `limit`?

<details><summary>Ответ</summary>

`concurrent` — глобальный лимит одновременно выполняемых джоб на всей машине
(на всех `[[runners]]`); `limit` — лимит для конкретного раннера внутри этого общего лимита.

</details>

**A10.** Что делает `privileged = true` и когда он действительно нужен?

<details><summary>Ответ</summary>

Снимает ограничения контейнера (устройства, capabilities, монтирование) —
требуется для запуска докер-демона внутри джобы (dind). Нужен только для сборки образов
через dind; для rootless BuildKit/buildah не требуется (хотя им нужны user namespaces —
послабленный seccomp/AppArmor).

</details>

**A11.** Что задаёт `pull_policy` и к каким проблемам приводит `if-not-present`?

<details><summary>Ответ</summary>

Политику загрузки образов: `always` — всегда тянуть свежий, `if-not-present` —
использовать локальный, если есть, `never` — только локальные. `if-not-present` приводит
к тому, что джобы бесконечно используют устаревший локальный образ (в том числе
устаревший `latest`) и «загадочно» ведут себя иначе, чем ожидается.

</details>

**A12.** Зачем `volumes = ["/cache"]` в конфиге docker-executor?

<details><summary>Ответ</summary>

Это volume, который раннер переиспользует между джобами для хранения кэша
(`cache:` из `.gitlab-ci.yml`). Без него кэш будет теряться при каждом запуске.

</details>

**A13.** Как сделать так, чтобы кэш работал между несколькими раннерами?

<details><summary>Ответ</summary>

Настроить distributed cache: `[runners.cache] Type = "s3"` (MinIO/S3-совместимое
хранилище) с `Shared = true`. Тогда кэш не привязан к конкретной машине.

</details>

**A14.** Что такое protected runner и зачем он нужен?

<details><summary>Ответ</summary>

Раннер, который берёт джобы только из защищённых веток и тегов. Используется
для деплой-раннеров с доступом к проду: код из произвольной фича-ветки на него не попадёт.

</details>

**A15.** Как ограничить, какие образы можно использовать в джобах?

<details><summary>Ответ</summary>

`allowed_images` и `allowed_services` в `[runners.docker]` — списки шаблонов
разрешённых образов. Позволяет запретить запуск произвольных образов на своих раннерах.

</details>

**A16.** Почему версия раннера должна быть не ниже версии GitLab?

<details><summary>Ответ</summary>

Раннер старее сервера может не понимать новые возможности API и конфигурации
(новые ключи, форматы токенов) — джобы начинают падать или не забираться. Рекомендация
GitLab — держать раннер не ниже версии инстанса.

</details>

**A17.** Назови девять шагов диагностики «джоба висит в pending».

<details><summary>Ответ</summary>

См. §9 конспекта: наличие онлайн-раннеров, совпадение тегов, untagged-настройка,
загрузка (`concurrent`/`limit`), protected-настройка, статус сервиса, место на диске,
версия раннера, квота CI-минут.

</details>

**A18.** Какие метрики раннера полезно мониторить?

<details><summary>Ответ</summary>

Число выполняемых и ожидающих джоб, время ожидания в очереди, длительность джоб,
ошибки системы (system failures), использование диска/CPU/памяти хоста, статус сервиса.

</details>

**A19.** Что делает `gitlab-runner verify` и `gitlab-runner unregister`?

<details><summary>Ответ</summary>

`verify` проверяет, что зарегистрированные раннеры ещё существуют на стороне
GitLab (с `--delete` удаляет из конфига «мёртвые»); `unregister` снимает регистрацию
раннера (по имени, токену или `--all-runners`).

</details>

---

### Блок B. «Что делает команда/конфиг»

```bash
B1.  sudo gitlab-runner register --non-interactive --url https://gitlab.com/ --token glrt-xxx --executor docker --docker-image alpine:3.20
B2.  sudo gitlab-runner list
B3.  sudo gitlab-runner verify --delete
B4.  sudo journalctl -u gitlab-runner -f
B5.  sudo gitlab-runner unregister --all-runners
B6.  docker system prune -a --volumes
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1. Зарегистрировать раннер с docker-executor и образом по умолчанию alpine
B2. Показать зарегистрированные на этой машине раннеры
B3. Проверить раннеры и удалить из конфига те, которых уже нет в GitLab
B4. Смотреть логи сервиса раннера в реальном времени
B5. Снять регистрацию всех раннеров этой машины
B6. Удалить все неиспользуемые образы, контейнеры, сети и тома (освободить место)
```

</details>

```toml
# B7
concurrent = 1
[[runners]]
  executor = "docker"
  [runners.docker]
    image = "alpine:3.20"
    pull_policy = ["if-not-present"]
```
Вопрос: какие две проблемы создаёт такой конфиг?

<details><summary>Ответ</summary>

(1) `concurrent = 1` — джобы выполняются строго по одной, очередь растёт;
(2) `pull_policy = if-not-present` — образы не обновляются, джобы могут месяцами
использовать устаревший локальный образ.

</details>

```toml
# B8
[[runners]]
  executor = "shell"
```
Вопрос: какие риски и что нужно проверить перед использованием?

<details><summary>Ответ</summary>

Джобы выполняются на хосте от имени `gitlab-runner`: остаётся состояние между
сборками, возможен доступ к файлам и сервисам хоста, конфликты параллельных джоб.
Проверить: какие права у пользователя, есть ли он в группе `docker` (это = root),
какие секреты и ключи лежат на машине, какие проекты допущены к раннеру.

</details>

```toml
# B9
[[runners]]
  executor = "docker"
  [runners.docker]
    privileged = true
    volumes = ["/var/run/docker.sock:/var/run/docker.sock", "/cache"]
```
Вопрос: что здесь избыточно и опасно одновременно?

<details><summary>Ответ</summary>

Одновременно включены и privileged (dind), и проброс сокета хоста. Достаточно
одного механизма, а проброс сокета вдобавок даёт джобе полный контроль над докером хоста
и всеми соседними контейнерами — это худший вариант с точки зрения безопасности.

</details>

---

### Блок C. Практика

#### C1. 🔑 Свой раннер с docker-executor (главное задание)

1. Поставь `gitlab-runner` на учебную VM.
2. Создай раннер в UI проекта, получи токен, зарегистрируй с `--executor docker`.
3. Дай ему тег `my-vm`.
4. Добавь в пайплайн джобу с `tags: [my-vm]` и убедись, что она выполнилась именно там
   (выведи `hostname`, `$CI_RUNNER_DESCRIPTION`).
5. Останови сервис раннера и посмотри, что произойдёт с новой джобой.

<details><summary>Ответ</summary>

Ожидаемо: после остановки сервиса раннер уходит в offline, джоба висит в pending
и превращается в stuck по таймауту.

</details>

#### C2. Сравни executors
Зарегистрируй на той же машине **второй** раннер с `--executor shell` и тегом `my-shell`.
Запусти одну и ту же джобу (`whoami`, `pwd`, `ls -la`, `env | head`) на обоих.
Выпиши пять отличий в выводе и объясни, откуда они берутся.
После эксперимента shell-раннер удали.

<details><summary>Ответ</summary>

Типичные отличия: пользователь (`root` в контейнере против `gitlab-runner` на хосте),
рабочий каталог (`/builds/...` против `/home/gitlab-runner/builds/...`), набор установленных
пакетов, переменные окружения, наличие файлов от предыдущих сборок на shell-раннере.

</details>

#### C3. Конфигурация
Открой `/etc/gitlab-runner/config.toml` и:
1. поставь `concurrent = 2`;
2. добавь лимиты памяти и CPU для docker-executor;
3. добавь `pull_policy = ["always"]`;
4. перезапусти сервис и убедись, что раннер жив (`verify`).
Запусти два пайплайна одновременно и проверь, что выполняются обе джобы.

<details><summary>Ответ</summary>

Проверка: при `concurrent = 2` две джобы выполняются одновременно; при лимитах
ресурсов тяжёлая джоба не «съедает» всю машину; `pull_policy = always` гарантирует свежие
образы (ценой трафика).

</details>

#### C4. Раннер для dind
Включи `privileged = true` и прогони джобу сборки образа из темы 07.
Затем выключи и убедись, что сборка перестала работать. Опиши, что именно ломается.

<details><summary>Ответ</summary>

Без `privileged` dind-сервис не может запустить демон: джоба падает на
`Cannot connect to the Docker daemon` (или dind не стартует). Это ровно та причина,
по которой в общих инфраструктурах выбирают сборку без демона — rootless BuildKit или buildah.

</details>

#### C5. Кэш
Проверь, где физически лежит кэш docker-executor (`docker volume ls | grep cache`).
Запусти джобу с `cache:` дважды и убедись, что второй раз он подхватился.
Затем очисти кэш через UI (Clear runner caches) и проверь снова.

<details><summary>Ответ</summary>

Кэш лежит в docker volume вида `runner-<id>-project-<id>-concurrent-<n>-cache-<hash>`;
после Clear runner caches ключ кэша меняется и джоба снова ставит зависимости заново.

</details>

#### C6. Диск
Заполни раннер сборками (несколько запусков с большим образом), посмотри `docker system df`
и `df -h`. Настрой регулярную очистку (cron/systemd timer) и проверь, что она работает.

<details><summary>Ответ</summary>

Порядок очистки: остановленные контейнеры → неиспользуемые образы → build-каталоги
старых сборок → тома кэша. На будущее — периодический `docker system prune` по таймеру
и мониторинг свободного места.

</details>

#### C7. Теги и маршрутизация
Создай две джобы: одну с `tags: [my-vm]`, другую без тегов. Проверь поведение,
включив и выключив «Run untagged jobs» у раннера. Зафиксируй результаты в таблице.

<details><summary>Ответ</summary>

Ожидаемо: с выключенной опцией untagged-джоба не попадает на раннер;
с включённой — попадает. Джоба с тегом попадает всегда, если тег совпал.

</details>

#### C8. Protected runner
Сделай раннер protected и убедись, что джоба из незащищённой ветки его не получает.
Объясни, как это сочетается с protected-переменными из темы 06.

<details><summary>Ответ</summary>

Protected runner + protected variables дают связку: секреты прода видны только
джобам защищённых веток, и выполняются такие джобы только на выделенных раннерах —
даже при утечке конфигурации фича-ветка не сможет ни получить секрет, ни попасть на
прод-раннер.

</details>

#### C9. Ansible-роль (со звёздочкой)
Опиши установку и регистрацию раннера в виде Ansible-плейбука: пакет, сервис,
`config.toml` из шаблона, токен из переменной. Прогони с `--check`.

<details><summary>Ответ</summary>

Ключевые задачи плейбука: подключить репозиторий пакетов, установить пакет,
положить `config.toml` из шаблона (токен — из vault/переменной), включить и перезапустить
сервис. Идемпотентность проверяется повторным прогоном (`changed=0`).

</details>

---

### Блок D. Инциденты

**D1.** Джоба висит `stuck`, раннер в UI зелёный. Что проверять по шагам?

<details><summary>Ответ</summary>

Совпадение тегов, включена ли «Run untagged jobs», не занят ли раннер
(`concurrent`/`limit`), не protected ли он при незащищённой ветке, назначен ли он
этому проекту, версия раннера, свободное место, наличие квоты минут.

</details>

**D2.** Раннер выполняет джобы, но все падают: `Cannot connect to the Docker daemon`.
Причины для shell- и для docker-executor.

<details><summary>Ответ</summary>

shell-executor: на хосте не установлен/не запущен docker либо пользователь
`gitlab-runner` не состоит в группе `docker`. docker-executor: не подключён сервис
`docker:dind`, неверные `DOCKER_HOST`/TLS-переменные или раннер без `privileged`.

</details>

**D3.** На раннере закончилось место, пайплайны падают с `no space left on device`.
Что удалять и в каком порядке, что настроить на будущее?

<details><summary>Ответ</summary>

Сначала `docker system prune -a --volumes` (или очистка каталогов `builds/`
на shell-раннере), затем удаление старых кэш-томов и логов. На будущее — таймер очистки,
лимит размера кэша, мониторинг диска с алертом, отдельный диск под `/var/lib/docker`.

</details>

**D4.** После обновления GitLab до новой версии раннеры перестали брать джобы. Причина?

<details><summary>Ответ</summary>

Раннеры старее инстанса GitLab — несовместимость API/формата токенов;
нужно обновить пакет раннера (и перерегистрировать, если сменился формат токена).

</details>

**D5.** Джобы берут старую версию образа, хотя в registry уже новая. Что в конфиге не так?

<details><summary>Ответ</summary>

`pull_policy = ["if-not-present"]` (или `never`): раннер использует локальную копию.
Нужно `always` для плавающих тегов, а лучше — пинить образы по digest/версии.

</details>

**D6.** Две джобы одного проекта одновременно портят друг другу файлы на shell-раннере.
Почему так происходит и что делать?

<details><summary>Ответ</summary>

На shell-executor у джоб общая файловая система и общий пользователь. Параллельные
джобы одного проекта работают в разных каталогах builds, но общие ресурсы (порты, временные
файлы, глобальные кэши) конфликтуют. Решение: перейти на docker-executor или ограничить
параллелизм и использовать `resource_group`.

</details>

**D7.** Разработчик добавил в `.gitlab-ci.yml` команду, которая прочитала `/etc/shadow`
на машине раннера. Как такое возможно и как предотвратить?

<details><summary>Ответ</summary>

На shell-executor `script` выполняется на хосте с правами `gitlab-runner`, а права
на чтение системных файлов зависят от настройки. Предотвращение: не использовать shell
для недоверенных проектов, перейти на docker/kubernetes executor, ограничить права
пользователя раннера, не хранить секреты на машине раннера.

</details>

**D8.** Пайплайны стоят в очереди по 20 минут, раннер один и загружен. Варианты решения
(минимум четыре).

<details><summary>Ответ</summary>

Увеличить `concurrent`/`limit` (если ресурсы позволяют), добавить раннеров,
включить автоскейлинг, ускорить сами джобы (кэш, `needs`, `interruptible`), вынести
тяжёлое в nightly, разделить раннеры по типам джоб.

</details>

**D9.** Кэш не переиспользуется: джобы одного пайплайна выполняются на разных раннерах.
Что настроить?

<details><summary>Ответ</summary>

Distributed cache (S3/MinIO, `Shared = true`) — локальный кэш привязан к машине.
Альтернатива — привязать джобы одного пайплайна к одному раннеру тегами (хуже
масштабируется).

</details>

**D10.** Раннер зарегистрирован, но в UI он «offline». Что проверить на машине?

<details><summary>Ответ</summary>

Статус сервиса (`systemctl status gitlab-runner`), логи (`journalctl -u`),
сетевую доступность GitLab с машины (`curl -I https://gitlab.com`), корректность токена
в `config.toml`, прокси/DNS, синхронизацию времени, не удалён ли раннер в UI.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое GitLab Runner и как он взаимодействует с GitLab?

<details><summary>Ответ</summary>

Агент, который забирает джобы у GitLab (исходящим соединением), выполняет их
в заданном executor'ом окружении и возвращает логи, статусы и артефакты.

</details>

**2.** Какие executors знаешь и чем отличаются?

<details><summary>Ответ</summary>

shell, docker, docker+machine, kubernetes, ssh, custom — отличаются местом выполнения
джобы, изоляцией и сложностью.

</details>

**3.** Чем docker-executor лучше shell?

<details><summary>Ответ</summary>

Чистое воспроизводимое окружение на каждую джобу, изоляция, управление версиями
рантайма образом, безопасность.

</details>

**4.** Зачем нужен privileged и чем он опасен?

<details><summary>Ответ</summary>

Нужен для docker-in-docker; даёт контейнеру почти полный доступ к хосту, поэтому
такой раннер держат отдельно и только для доверенных проектов.

</details>

**5.** Что такое теги раннера?

<details><summary>Ответ</summary>

Метки раннера, по которым джобы с `tags:` маршрутизируются на нужные раннеры.

</details>

**6.** Как ограничить, какие джобы попадают на раннер с доступом к проду?

<details><summary>Ответ</summary>

Protected runner + protected branches/variables + отдельные ключи доступа
с минимальными правами.

</details>

**7.** Где настраивается параллелизм?

<details><summary>Ответ</summary>

`concurrent` (на машину) и `limit` (на раннер) в `config.toml`; в k8s — ресурсы
и лимиты подов.

</details>

**8.** Как организовать общий кэш между раннерами?

<details><summary>Ответ</summary>

Distributed cache в S3-совместимом хранилище (`[runners.cache]`, `Shared = true`).

</details>

**9.** Джоба висит в pending — что проверишь?

<details><summary>Ответ</summary>

Теги, онлайн-статус раннера, untagged-настройку, загрузку, protected, место на диске,
версию, квоту минут.

</details>

**10.** Как бы ты организовал парк раннеров в компании?

<details><summary>Ответ</summary>

Разделить по назначению (build/test/deploy), деплойные — protected и с минимальными
правами, описать всё в IaC, мониторить очередь и диск, настроить автоскейлинг
и регулярную очистку, обновлять версии.

</details>

---

### 🎯 Чек-лист

- [ ] Поставил и зарегистрировал свой раннер с docker-executor
- [ ] Маршрутизирую джобы тегами и понимаю поведение untagged
- [ ] Сравнил shell и docker executors на практике
- [ ] Понимаю риск shell-executor и privileged
- [ ] Правил `config.toml`: concurrent, лимиты, pull_policy — и знаю, что перезапуск обязателен
- [ ] Настроил и проверил кэш; знаю, зачем нужен distributed cache
- [ ] Настроил очистку диска на раннере
- [ ] Могу пройти диагностику «джоба stuck» по шагам
- [ ] Знаю, что такое protected runner и как он сочетается с protected-переменными
- [ ] Понимаю, как организовать парк раннеров в компании
