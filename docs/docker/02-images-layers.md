---
title: "02. Образы: слои, overlay2, теги"
description: "Из чего состоит docker-образ, copy-on-write, overlay2, тегирование и дайджесты, save/load vs export/import"
---

# 02. Образы: слои, overlay2, теги и дайджесты

> Роадмап → 3. Docker → Теория → Образы (слои и кэширование, тегирование)
> **После темы ты умеешь:** объяснить, из чего состоит образ, читать `docker history`,
> понимать copy-on-write, отличать тег от дайджеста и почему `latest` — зло.

---

## 🗺️ Схема: образ = стопка read-only слоёв

```text:no-line-numbers
   ОБРАЗ (immutable)                        КОНТЕЙНЕР
┌───────────────────────────┐        ┌───────────────────────────┐
│ Layer 4  CMD/метаданные   │        │  Writable layer (thin)    │ ← только тут пишется
├───────────────────────────┤        ├───────────────────────────┤
│ Layer 3  COPY app.jar     │  RO    │ Layer 4 (RO, из образа)   │
├───────────────────────────┤  ───►  ├───────────────────────────┤
│ Layer 2  RUN apt install  │        │ Layer 3 (RO, из образа)   │
├───────────────────────────┤        ├───────────────────────────┤
│ Layer 1  FROM ubuntu      │        │ Layer 2, Layer 1 (RO)     │
└───────────────────────────┘        └───────────────────────────┘
                                       ▲
   Один и тот же RO-слой                │  10 контейнеров из одного образа =
   переиспользуется всеми ────────────────  1 копия слоёв + 10 тонких writable-слоёв
   контейнерами и образами                  (поэтому контейнеры «ничего не весят»)
```

**Copy-on-Write (CoW):** пока файл только читают — он берётся из нижнего RO-слоя.
При первой записи файл **целиком копируется** в writable-слой контейнера и меняется уже там.
Отсюда два следствия:
- изменение 1 байта в файле на 2 ГБ = копирование 2 ГБ (поэтому БД в контейнерном слое — плохо, тема 07);
- удаление файла в верхнем слое **не уменьшает образ**: в нижнем слое он остаётся, сверху ставится
  «whiteout»-метка. Классическая ошибка `RUN rm -rf /var/lib/apt/lists/*` **отдельной строкой** (тема 04).

---

## 1. Анатомия образа

```text:no-line-numbers
Образ = манифест + конфиг + N слоёв (tar-архивы), всё адресуется по sha256
```

| Сущность | Что это |
|----------|---------|
| **Layer** | tar-архив с изменениями файловой системы относительно предыдущего слоя |
| **Config** | JSON: `Cmd`, `Entrypoint`, `Env`, `WorkingDir`, `User`, `ExposedPorts`, история, архитектура |
| **Manifest** | Список: какой конфиг + какие слои (по дайджестам) составляют образ |
| **Manifest list / Index** | Мульти-архитектурный образ: под amd64 — один манифест, под arm64 — другой |
| **Image ID** | sha256 от **конфига** образа (локальный идентификатор) |
| **Digest** | sha256 от **манифеста** — то, чем образ идентифицируется в registry. Неизменяем |
| **Tag** | Человеческая метка, **указатель** на дайджест. Может быть переназначена в любой момент |

```bash
docker pull nginx:1.27-alpine
docker images
docker image inspect nginx:1.27-alpine | jq '.[0].RootFS.Layers'   # слои
docker image inspect nginx:1.27-alpine --format '{{.Id}}'          # image ID (конфиг)
docker image inspect nginx:1.27-alpine --format '{{index .RepoDigests 0}}'  # digest
docker history nginx:1.27-alpine                                   # ⭐ как собирался
docker manifest inspect nginx:1.27-alpine | head -30                # манифест из registry
```

### `docker history` — важнейшая команда темы

```bash
docker history --no-trunc --format "table {{.Size}}\t{{.CreatedBy}}" myapp:1.0
```
Показывает, **какая инструкция Dockerfile сколько весит**. Отсюда начинается любая
оптимизация размера: находишь жирные слои → переписываешь именно их.

> Слои с размером `0B` — это метаданные (`ENV`, `CMD`, `WORKDIR`, `LABEL`, `EXPOSE`).
> Они не добавляют файлов и почти ничего не весят.

---

## 2. Storage driver: overlay2

```bash
docker info | grep -A5 "Storage Driver"      # ожидаем overlay2
ls /var/lib/docker/overlay2 | head           # каталоги слоёв (нужен root)
du -sh /var/lib/docker                       # где реально лежит место
```

OverlayFS объединяет каталоги в одну «слоёную» ФС:

```text:no-line-numbers
lowerdir  = слои образа (read-only, может быть несколько, через ':')
upperdir  = writable-слой контейнера
workdir   = служебный каталог для атомарных операций
merged    = то, что видит процесс внутри контейнера как /
```

| Драйвер | Когда встречается |
|---------|-------------------|
| `overlay2` | Дефолт и рекомендация для всех современных ядер |
| `fuse-overlayfs` | Rootless-докер |
| `btrfs`, `zfs` | Если ФС хоста соответствующая |
| `devicemapper`, `aufs`, `vfs` | Легаси. `vfs` — без CoW, копирует всё, дико жрёт диск |

---

## 3. Тегирование (роадмап: «надо понимать, как правильно именовать образы»)

Полное имя образа:

```text:no-line-numbers
          registry      /  namespace / repository : tag        @ digest
   ┌──────────────────┐   ┌────────┐  ┌────────┐  ┌──────┐    ┌──────────┐
   registry.company.ru / backend   /  payments : 1.4.2       @ sha256:ab12…

   nginx                       →  docker.io/library/nginx:latest   (дефолты подставляются!)
   ghcr.io/acme/api:2.1.0
   123456.dkr.ecr.eu-west-1.amazonaws.com/api:2.1.0
```

### Правила именования, которые спрашивают

1. **`latest` — не «последний»**, а просто тег по умолчанию. Он никак не связан с версией:
   на него указывает то, что последним запушили с этим тегом (или вообще ничего).
2. **Не деплой по `latest`**: невозможно понять, что именно работает в проде, и откатиться.
   `imagePullPolicy`/кэш могут подсунуть старый слой — источник «мистических» багов.
3. **Тег = версия артефакта.** Рабочая схема — сразу несколько тегов на один образ:
   ```text:no-line-numbers
   myapp:1.4.2           ← точная версия (semver) — по ней деплоят
   myapp:1.4             ← minor-указатель, двигается
   myapp:1               ← major-указатель, двигается
   myapp:a1b2c3d         ← git short SHA — 100% трассируемость коммит↔образ ⭐
   myapp:2026-09-13.17   ← дата+номер сборки
   myapp:latest          ← удобство для разработчика, НЕ для прода
   ```
4. **Иммутабельность тегов.** Хорошая практика: релизный тег ставится один раз и больше
   не переписывается (в ECR/Harbor/GitLab это включается настройкой «immutable tags»).
5. **Тег ≠ гарантия.** Гарантия — **дайджест**: `myapp@sha256:…`. В проде/k8s для критичных
   систем пинят именно дайджест.
6. Не используй `-` вместо версии (`myapp:prod`, `myapp:stable`) как единственный тег:
   такие «плавающие» имена скрывают, что внутри.

```bash
docker tag myapp:1.4.2 myapp:1.4
docker tag myapp:1.4.2 registry.company.ru/backend/myapp:1.4.2
docker images myapp                      # один IMAGE ID под несколькими тегами
docker rmi myapp:1.4                     # удалит ТЕГ, слои останутся (на них ссылается 1.4.2)
docker pull nginx@sha256:<digest>        # намертво зафиксированный образ
```

> `docker images` показывает один и тот же `IMAGE ID` у разных тегов — это один образ,
> место на диске занимает **один раз**.

---

## 4. Что происходит при pull/push

```text:no-line-numbers
docker pull nginx:1.27-alpine
  1. Резолв имени → docker.io/library/nginx:1.27-alpine
  2. Скачивается манифест (по тегу) → узнаём список дайджестов слоёв
  3. Скачиваются ТОЛЬКО отсутствующие локально слои (параллельно)
     "Already exists" ← слой уже есть от другого образа
  4. Слои распаковываются в /var/lib/docker/overlay2

docker push myapp:1.4.2
  Пушатся только слои, которых нет в registry ("Layer already exists")
```

Именно поэтому **порядок инструкций в Dockerfile** влияет не только на скорость сборки,
но и на скорость деплоя: если менялся только верхний слой с кодом (5 МБ), сервер
дотянет 5 МБ, а не весь образ (тема 04).

### Dangling-образы `<none>:<none>`

Появляются, когда тег переехал на новый образ, а старый остался без имени.

```bash
docker images -f "dangling=true"
docker image prune              # снести dangling
docker image prune -a           # снести все образы, на которые нет контейнеров ⚠️
```

---

## 5. Базовые образы: что выбирать

| База | Размер | Когда |
|------|--------|-------|
| `ubuntu:24.04` / `debian:bookworm` | ~30-80 МБ | Нужны привычные пакеты и glibc, отладка |
| `debian:bookworm-slim` | ~30 МБ | Дефолтный разумный выбор |
| `alpine:3.20` | ~7 МБ | Минимализм. ⚠️ musl вместо glibc: Python/Node-пакеты собираются медленно, бывают баги |
| `gcr.io/distroless/*` | ~2-20 МБ | Прод: только рантайм, **нет shell и пакетного менеджера** → меньше поверхность атаки |
| `scratch` | 0 | Для статических бинарников (Go, Rust) — идеал multi-stage |
| `*-alpine`/`*-slim` варианты официальных | — | `python:3.12-slim`, `node:22-alpine` — берут почти всегда |

> Alpine ≠ автоматически лучше. Для Python с нативными зависимостями `python:3.12-slim`
> часто **меньше по итогу и собирается в разы быстрее**, чем alpine (нет колёс под musl).

---

## 6. Сохранить/загрузить образ без registry

```bash
docker save myapp:1.4.2 -o myapp.tar          # образ (все слои) в tar
docker load -i myapp.tar                      # обратно, теги сохраняются

docker export <container> -o fs.tar           # ФС КОНТЕЙНЕРА, БЕЗ слоёв и истории
docker import fs.tar myflat:1.0               # получится ОДИН слой, без CMD/ENV
```

| | `save/load` | `export/import` |
|---|---|---|
| Работает с | образом | контейнером |
| Слои | сохраняются | схлопываются в один |
| Метаданные (CMD/ENV) | сохраняются | теряются |
| Зачем | перенести образ на машину без registry | «сплющить» образ, забрать ФС |

---

## 💼 Как это в DevOps

- **Слои = деньги и время.** Трафик registry, скорость деплоя, место на нодах k8s — всё зависит
  от того, насколько аккуратно нарезаны слои и переиспользуются базовые образы.
- **Один базовый образ на компанию.** Если все сервисы идут от общего `company/base:python-3.12`,
  этот слой на ноде хранится один раз и тянется один раз.
- **Тег — это контракт между CI и деплоем.** CI собрал `myapp:$GIT_SHA` → положил в registry →
  манифест k8s ссылается на `$GIT_SHA`. Так по любому поду можно за секунду понять,
  какой коммит там работает.
- **Дайджест — для аудита и безопасности.** Подписанные образы (cosign) и пины по дайджесту —
  защита от подмены тега в registry.

---

## 🧪 Мини-лаба: слои, CoW и теги

```bash
# 1. Слои и переиспользование
docker pull python:3.12-slim
docker pull python:3.12-alpine
docker images
docker image inspect python:3.12-slim  | jq '.[0].RootFS.Layers | length'
docker history python:3.12-slim

# 2. Собрать образ и посмотреть, что весит
mkdir -p ~/lab02 && cd ~/lab02
cat > Dockerfile <<'EOF'
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y curl
RUN curl -sL https://example.com -o /tmp/page.html
RUN rm -f /tmp/page.html
COPY . /app
CMD ["sleep", "infinity"]
EOF
docker build -t lab02:v1 .
docker history lab02:v1                       # ⭐ найди слой с apt — он самый жирный
docker images lab02:v1

# 3. Докажи, что rm отдельным слоем НЕ уменьшает образ
docker run --rm lab02:v1 ls /tmp              # файла нет
docker history lab02:v1 | grep -i curl        # но слой с ним остался и весит

# 4. Copy-on-write в действии
docker run -d --name cow lab02:v1
docker exec cow sh -c 'dd if=/dev/zero of=/big bs=1M count=100'
docker ps -s                                  # колонка SIZE: ~100MB (writable-слой)
docker diff cow | head                        # A/C/D — что изменилось относительно образа
docker rm -f cow                              # ← и эти 100 МБ исчезли вместе с контейнером

# 5. Теги — это указатели
docker tag lab02:v1 lab02:1.0
docker tag lab02:v1 lab02:latest
docker images lab02                           # ОДИН IMAGE ID, три тега
docker rmi lab02:latest                       # "Untagged" — слои целы
docker images lab02

# 6. Dangling
docker build -t lab02:v1 --build-arg X=1 --no-cache .   # пересобрали под тем же тегом
docker images -f "dangling=true"              # появился <none> — старый образ без тега
docker image prune -f

# 7. Перенос без registry
docker save lab02:v1 -o /tmp/lab02.tar && ls -lh /tmp/lab02.tar
docker rmi lab02:v1 lab02:1.0
docker load -i /tmp/lab02.tar && docker images lab02

# 8. Уборка
cd ~ && rm -rf ~/lab02 /tmp/lab02.tar
docker rmi lab02:v1 2>/dev/null
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `docker images` / `docker image ls` | Список образов |
| `docker images -f dangling=true` | Образы без тегов (`<none>`) |
| `docker pull IMG[:tag\|@digest]` | Скачать образ |
| `docker push REG/NS/IMG:tag` | Загрузить в registry |
| `docker tag SRC DST` | Поставить ещё одно имя тому же образу |
| `docker history IMG` | ⭐ Слои и их размер (чем собран каждый) |
| `docker image inspect IMG` | Полный JSON: конфиг, слои, env, cmd |
| `docker manifest inspect IMG` | Манифест из registry (в т.ч. мультиарх) |
| `docker rmi IMG` | Удалить тег/образ |
| `docker image prune [-a]` | Снести dangling / все неиспользуемые |
| `docker system df [-v]` | Занятое место, с детализацией |
| `docker save/load` | Образ ↔ tar (со слоями) |
| `docker export/import` | ФС контейнера ↔ tar (одним слоем) |
| `docker diff CONT` | Что изменилось в контейнере относительно образа |
| `docker ps -s` | Размер writable-слоя контейнеров |

---

## 🧠 Что запомнить

1. Образ = **стопка read-only слоёв** + конфиг + манифест; всё адресуется по sha256.
2. Контейнер = образ + **тонкий writable-слой** сверху. Удалил контейнер — потерял этот слой.
3. **Copy-on-Write**: запись в файл копирует его целиком наверх. Много записи → пиши в volume.
4. Удаление файла в следующем слое **не уменьшает образ** — чистить надо в той же инструкции `RUN`.
5. Слои **переиспользуются** между образами и контейнерами: одинаковый слой на диске один раз.
6. `Image ID` — sha256 конфига (локально), `Digest` — sha256 манифеста (в registry, неизменяем).
7. **Тег — это подвижный указатель**, а не версия. `latest` ничего не гарантирует.
8. Деплой — по конкретной версии/`git SHA`, а для критичного — **по дайджесту**.
9. `docker history` — первая команда при оптимизации размера.
10. `docker rmi` тега не удаляет слои, если на них ссылается другой тег/образ.
11. Базу выбирают осознанно: `slim` — дефолт, `alpine` — минимализм с оговорками (musl),
    `distroless`/`scratch` — прод и multi-stage.
12. `save/load` сохраняет слои и метаданные, `export/import` — нет.

---

## Задачи

> Рабочий каталог для лаб: `mkdir -p ~/docker-lab/02 && cd ~/docker-lab/02`
> Уборка: `docker system prune -a` (⚠️ снесёт все неиспользуемые образы)

---

### Блок A. Теория

**A1.** Из чего состоит docker-образ? Назови 4 сущности.

<details><summary>Ответ</summary>

Слои (tar-архивы с изменениями ФС), конфиг (JSON с `Cmd`, `Env`, `Entrypoint`, `User`,
историей), манифест (список конфига и слоёв по дайджестам) и — для мультиарх-образов —
manifest list/index.

</details>

**A2.** Чем контейнер отличается от образа в терминах слоёв?

<details><summary>Ответ</summary>

Образ — только read-only слои, он неизменяем. Контейнер = те же RO-слои + **тонкий
writable-слой** сверху, куда пишутся все изменения. Удаление контейнера уничтожает только этот слой.

</details>

**A3.** Что такое Copy-on-Write и какие два практических следствия из него вытекают?

<details><summary>Ответ</summary>

CoW: файл читается из нижнего RO-слоя, но при первой записи **копируется целиком** наверх.
Следствия: (1) запись в большие файлы дорогая — нагруженные данные (БД, логи) выносят в volume;
(2) удалённый в верхнем слое файл остаётся в нижнем — образ не худеет.

</details>

**A4.** Почему `RUN rm -rf /var/lib/apt/lists/*` отдельной строкой не уменьшает образ?

<details><summary>Ответ</summary>

Потому что `apt-get update`/`install` создали свой слой с этими файлами, а `rm` создаёт
**новый** слой, где ставится whiteout-метка. Данные из нижнего слоя никуда не деваются и качаются
при pull. Чистить нужно в той же инструкции: `RUN apt-get update && apt-get install -y … && rm -rf /var/lib/apt/lists/*`.

</details>

**A5.** Чем `Image ID` отличается от `Digest`? Какой из них меняется при перетегировании?

<details><summary>Ответ</summary>

`Image ID` = sha256 конфига образа, локальный идентификатор. `Digest` = sha256 манифеста,
идентификатор в registry. Перетегирование не меняет ни того, ни другого — тег это просто указатель;
меняется только набор `RepoTags`.

</details>

**A6.** Тег — это версия? Объясни, чем на самом деле является тег.

<details><summary>Ответ</summary>

Нет. Тег — **человекочитаемый подвижный указатель** на конкретный манифест (дайджест)
в репозитории. Его можно переназначить на другой образ в любой момент, если в registry
не включена иммутабельность тегов.

</details>

**A7.** Что означает тег `latest` и почему деплоить по нему нельзя?

<details><summary>Ответ</summary>

`latest` — просто тег по умолчанию, который подставляется, если тег не указан. Он не
означает «самый новый» и может вообще отсутствовать. Деплоить нельзя: неизвестно, что в проде,
невозможен воспроизводимый откат, кэш образов на нодах может подсунуть старую версию.

</details>

**A8.** Какое полное каноническое имя у образа `nginx`? Разложи по частям.

<details><summary>Ответ</summary>

`docker.io/library/nginx:latest` — registry `docker.io`, namespace `library`
(для официальных образов), repository `nginx`, tag `latest`. Плюс необязательный `@sha256:…`.

</details>

**A9.** Предложи схему тегирования для CI: какие теги ставить на один и тот же образ и зачем.

<details><summary>Ответ</summary>

На один образ: `1.4.2` (точная версия — по ней деплой), `1.4` и `1` (подвижные указатели),
`<git-sha>` (трассируемость коммит↔образ), опционально дата/номер сборки и `latest` для удобства
разработки. В прод-манифестах — точная версия или дайджест.

</details>

**A10.** Что такое overlay2? Что означают `lowerdir`, `upperdir`, `merged`?

<details><summary>Ответ</summary>

Файловая система, объединяющая каталоги. `lowerdir` — слои образа (RO, могут быть
несколько), `upperdir` — writable-слой контейнера, `workdir` — служебный, `merged` — итоговое
представление, которое видит процесс как `/`.

</details>

**A11.** Почему при `docker pull` часть слоёв пишет `Already exists`?

<details><summary>Ответ</summary>

Слой с таким дайджестом уже есть локально (он общий с другим образом или предыдущей
версией). Скачиваются только недостающие слои — это и экономит трафик при частых деплоях.

</details>

**A12.** Откуда берутся образы `<none>:<none>` и опасны ли они?

<details><summary>Ответ</summary>

Когда тег переезжает на новый образ (пересборка под тем же именем), старый образ остаётся
без тега. Не опасны, но занимают место; чистятся `docker image prune`. Если на такой образ
ссылается работающий контейнер — он продолжит работать.

</details>

**A13.** Чем `docker save/load` отличается от `docker export/import`? Когда что использовать.

<details><summary>Ответ</summary>

`save/load` работает с **образом**: сохраняет все слои, историю и метаданные (CMD/ENV),
теги восстанавливаются. `export/import` работает с **контейнером**: выгружает плоскую ФС,
слои схлопываются в один, метаданные теряются (нужно задавать `CMD` заново через `--change`).
save/load — перенести образ на машину без registry; export/import — «сплющить» образ или забрать
файловую систему на анализ.

</details>

**A14.** Что такое manifest list и зачем он нужен?

<details><summary>Ответ</summary>

Индекс, который для одного тега хранит несколько манифестов — по одному на
архитектуру/ОС (amd64, arm64…). Клиент сам выбирает подходящий. Благодаря ему `docker pull nginx`
работает и на Mac M-series, и на серверах x86.

</details>

**A15.** Alpine всегда лучше, потому что меньше? Приведи контраргумент.

<details><summary>Ответ</summary>

Alpine использует **musl** вместо glibc. Для Python/Node с нативными зависимостями
готовые бинарные колёса под musl часто отсутствуют → всё собирается из исходников: сборка в разы
дольше, итоговый образ может оказаться **больше**, плюс бывают трудноуловимые баги
(DNS-резолвинг, локали, производительность malloc). Для Go/Rust-статики alpine (или scratch) — отлично.

</details>

**A16.** Десять контейнеров запущены из одного образа на 500 МБ. Сколько места на диске
займут сами контейнеры сразу после запуска и почему?

<details><summary>Ответ</summary>

Практически нисколько: слои образа переиспользуются всеми контейнерами, каждый получает
только свой пустой writable-слой (килобайты). 500 МБ на диске лежат один раз.
Расти контейнеры начнут по мере записи внутрь.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  docker history --no-trunc myapp:1.0
B2.  docker image inspect nginx --format '{{.Id}}'
B3.  docker image inspect nginx --format '{{index .RepoDigests 0}}'
B4.  docker images -f dangling=true -q
B5.  docker tag myapp:1.4.2 myapp:1.4
B6.  docker rmi myapp:1.4
B7.  docker pull nginx@sha256:abc123...
B8.  docker system df -v
B9.  docker ps -s
B10. docker diff web
B11. docker image prune -a
B12. docker save alpine | gzip > alpine.tar.gz
B13. docker manifest inspect nginx:alpine
B14. docker image inspect nginx | jq '.[0].RootFS.Layers | length'
B15. docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}'
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Полная история слоёв без обрезки команд — видно, какая инструкция Dockerfile сколько весит.
B2.  Image ID (sha256 конфига).
B3.  RepoDigest — имя с дайджестом, которым образ адресуется в registry.
B4.  ID всех dangling-образов (удобно для docker rmi $(...)).
B5.  Добавляет второй тег тому же образу (копирования не происходит).
B6.  Удаляет ТЕГ. Если это был последний тег и нет зависимых контейнеров — удалится и образ.
B7.  Скачивает образ, жёстко зафиксированный по дайджесту — тег не участвует, подмена невозможна.
B8.  Детальная раскладка занятого места по каждому образу/контейнеру/тому/кэшу.
B9.  Список контейнеров с колонками SIZE (writable-слой) и virtual (слой + образ).
B10. Изменения ФС контейнера относительно образа: A — добавлен, C — изменён, D — удалён.
B11. Удаляет все образы, на которые не ссылается ни один контейнер (не только dangling).
B12. Сохраняет образ в поток и жмёт — типовой способ перенести образ по scp.
B13. Показывает манифест (или manifest list с архитектурами) прямо из registry без скачивания.
B14. Число слоёв в образе.
B15. Компактный список «репозиторий:тег размер».
```

</details>

**B16.** Чем отличается результат `docker rmi myapp:1.4`, если у образа два тега,
от того же действия при одном теге?

<details><summary>Ответ</summary>

При двух тегах будет только `Untagged: myapp:1.4` — слои остаются, т.к. на них ссылается
второй тег. При единственном теге дополнительно пойдут строки `Deleted: sha256:…` — реально
удаляются слои (те, что не используются другими образами).

</details>

---

### Блок C. Практика

#### C1. 🔑 Анатомия образа (главное задание)

Для образа `python:3.12-slim`:
1. Сколько в нём слоёв?
2. Какая инструкция создала самый тяжёлый слой?
3. Какой у него Image ID, какой RepoDigest, чем они отличаются?
4. Какие `ENV`, `CMD` и `WorkingDir` записаны в конфиге?
5. Скачай `python:3.12-alpine` и сравни: размер, число слоёв, базовый дистрибутив.

<details><summary>Ответ</summary>

```bash
docker pull python:3.12-slim python:3.12-alpine 2>/dev/null || {
  docker pull python:3.12-slim; docker pull python:3.12-alpine; }

docker image inspect python:3.12-slim | jq '.[0].RootFS.Layers | length'
docker history python:3.12-slim --format "table {{.Size}}\t{{.CreatedBy}}" | head
docker image inspect python:3.12-slim --format '{{.Id}}'
docker image inspect python:3.12-slim --format '{{index .RepoDigests 0}}'
docker image inspect python:3.12-slim \
  --format 'ENV={{.Config.Env}}{{"\n"}}CMD={{.Config.Cmd}}{{"\n"}}WD={{.Config.WorkingDir}}'
docker images python
docker run --rm python:3.12-slim   cat /etc/os-release | head -2   # Debian
docker run --rm python:3.12-alpine cat /etc/os-release | head -2   # Alpine
# Id — sha256 конфига (локальный), RepoDigest — sha256 манифеста в registry.
```

</details>

#### C2. Слои своими руками

Собери образ по этому Dockerfile, затем ответь на вопросы:

```dockerfile
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y curl ca-certificates
RUN dd if=/dev/urandom of=/tmp/blob bs=1M count=50
RUN rm -f /tmp/blob
COPY . /app
ENV APP_ENV=prod
CMD ["sleep", "infinity"]
```

1. Сколько весит итоговый образ?
2. Есть ли файл `/tmp/blob` в контейнере?
3. Сколько весит слой, где он создавался? Почему он всё ещё в образе?
4. Перепиши Dockerfile так, чтобы blob не попал в образ. Сравни размеры.
5. Сколько весят слои `ENV` и `CMD` и почему?

<details><summary>Ответ</summary>

```bash
mkdir -p ~/docker-lab/02 && cd ~/docker-lab/02
cat > Dockerfile <<'EOF'
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y curl ca-certificates
RUN dd if=/dev/urandom of=/tmp/blob bs=1M count=50
RUN rm -f /tmp/blob
COPY . /app
ENV APP_ENV=prod
CMD ["sleep", "infinity"]
EOF
docker build -t lab02:bad .
docker images lab02:bad                      # ~50 МБ лишних
docker run --rm lab02:bad ls /tmp            # blob отсутствует...
docker history lab02:bad | grep dd           # ...но слой на 50 МБ есть

cat > Dockerfile.good <<'EOF'
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN dd if=/dev/urandom of=/tmp/blob bs=1M count=50 && rm -f /tmp/blob
COPY . /app
ENV APP_ENV=prod
CMD ["sleep", "infinity"]
EOF
docker build -f Dockerfile.good -t lab02:good .
docker images lab02                          # good заметно меньше
docker history lab02:good | head
# ENV и CMD весят 0B — они меняют только конфиг образа, файлов не добавляют.
```

</details>

#### C3. Copy-on-Write

1. Запусти контейнер из любого образа.
2. Создай внутри файл на 200 МБ.
3. Покажи размер writable-слоя контейнера (два разных способа).
4. Покажи список изменений контейнера относительно образа, объясни буквы `A`, `C`, `D`.
5. Удали контейнер и покажи, что место освободилось.

<details><summary>Ответ</summary>

```bash
docker run -d --name cow lab02:good sleep infinity
docker exec cow dd if=/dev/zero of=/big bs=1M count=200
docker ps -s --filter name=cow                       # способ 1: колонка SIZE
docker inspect cow --format '{{.GraphDriver.Data.UpperDir}}'
sudo du -sh $(docker inspect cow --format '{{.GraphDriver.Data.UpperDir}}')  # способ 2
docker diff cow | head                               # A /big
docker system df
docker rm -f cow
docker system df                                     # место вернулось
```

</details>

#### C4. Теги — это указатели

1. Поставь одному образу три разных тега, включая тег с другим репозиторием.
2. Докажи, что это один образ и место занято один раз.
3. Удали один тег — покажи, что слои целы.
4. Пересобери образ под тем же тегом — найди появившийся dangling-образ и объясни, откуда он.
5. Почисти dangling.

<details><summary>Ответ</summary>

```bash
docker tag lab02:good shop-api:1.4.2
docker tag lab02:good registry.local/team/shop-api:1.4.2
docker images | grep -E "lab02|shop-api"             # один IMAGE ID
docker system df                                     # место не выросло
docker rmi registry.local/team/shop-api:1.4.2        # только Untagged
docker build --no-cache -f Dockerfile.good -t lab02:good .
docker images -f dangling=true                       # прежний образ остался без тега
docker image prune -f
```

</details>

#### C5. Схема тегирования как в CI

Симулируй CI: собери образ `shop-api` и повесь на него теги
`1.4.2`, `1.4`, `1`, `<git-sha>` (возьми любые 7 hex-символов), `latest`.
Затем «выпусти версию 1.4.3» (пересобери) и переставь подвижные теги.
Покажи `docker images shop-api` до и после. Какие теги двинулись, какие остались?

<details><summary>Ответ</summary>

```bash
docker build -f Dockerfile.good -t shop-api:1.4.2 .
for t in 1.4 1 a1b2c3d latest; do docker tag shop-api:1.4.2 shop-api:$t; done
docker images shop-api
# «релиз 1.4.3»
docker build --no-cache -f Dockerfile.good -t shop-api:1.4.3 .
for t in 1.4 1 latest; do docker tag shop-api:1.4.3 shop-api:$t; done
docker tag shop-api:1.4.3 shop-api:e4f5a6b
docker images shop-api
```

Двинулись: `1.4`, `1`, `latest`. Остались на месте: `1.4.2` и его git-sha `a1b2c3d` —
именно поэтому по ним можно откатиться и понять, что работает в проде.

</details>

#### C6. Перенос образа без registry

1. Сохрани образ в tar, сожми gzip, посмотри размер.
2. Удали образ локально (все теги).
3. Восстанови из архива, убедись, что теги вернулись.
4. Сделай то же через `export/import` из контейнера и сравни `docker history` двух результатов.

<details><summary>Ответ</summary>

```bash
docker save shop-api:1.4.2 | gzip > /tmp/shop.tar.gz && ls -lh /tmp/shop.tar.gz
docker rmi shop-api:1.4.2 shop-api:a1b2c3d
docker load -i /tmp/shop.tar.gz && docker images shop-api

docker run -d --name exp shop-api:1.4.3 sleep infinity
docker export exp -o /tmp/flat.tar
docker import /tmp/flat.tar flat:1.0
docker history shop-api:1.4.3 | wc -l     # много слоёв
docker history flat:1.0                   # ОДИН слой, CMD пустой
docker run --rm flat:1.0 2>&1 | head -1   # ошибка: нет команды по умолчанию
docker rm -f exp; docker rmi flat:1.0; rm -f /tmp/flat.tar /tmp/shop.tar.gz
```

</details>

#### C7. Где лежит место

1. Покажи, сколько всего занято образами, контейнерами, томами, build cache.
2. Найди `Docker Root Dir` и посмотри размер каталога.
3. Найди три самых больших образа на машине.

<details><summary>Ответ</summary>

```bash
docker system df -v | head -30
docker info --format '{{.DockerRootDir}}'
sudo du -sh $(docker info --format '{{.DockerRootDir}}')
docker images --format '{{.Size}}\t{{.Repository}}:{{.Tag}}' | sort -h -r | head -3
```

</details>

---

### Блок D. Инциденты

**D1.** На проде задеплоили `myapp:latest`. Приложение работает по-старому, хотя CI собрал новую
версию 20 минут назад. Назови три возможные причины и как больше в это не попадать.

<details><summary>Ответ</summary>

(1) На ноде/раннере уже лежит старый образ с тем же тегом и его не перекачали
(`docker pull` не сделали, в k8s `imagePullPolicy: IfNotPresent`); (2) CI запушил в другой
registry/репозиторий, а прод тянет из старого; (3) деплой вообще не перезапустил контейнер
(тег тот же — оркестратор не видит изменений). Решение: тег с версией или `git SHA`,
`imagePullPolicy: Always` для плавающих тегов, а лучше — деплой по дайджесту.

</details>

**D2.** Диск на CI-раннере забит под 100%. `du -sh /var/lib/docker` = 180 ГБ.
Разложи, из чего это состоит, и напиши безопасный план очистки (что можно удалять, что нельзя).

<details><summary>Ответ</summary>

Состав: образы (в т.ч. dangling), остановленные контейнеры с writable-слоями, тома,
**build cache** (часто самое жирное), логи контейнеров (`/var/lib/docker/containers/*/*-json.log`).

План:
```bash
docker system df -v                      # понять раскладку
docker container prune                   # остановленные контейнеры
docker image prune                       # dangling
docker builder prune --filter until=168h # кэш сборок старше недели
docker image prune -a --filter until=336h  # образы, не используемые > 2 недель
docker volume ls -f dangling=true        # ⚠️ ПОСМОТРЕТЬ ГЛАЗАМИ перед удалением
```
Нельзя бездумно: `docker volume prune` (может снести данные БД) и `docker system prune -a --volumes`
на сервере с прод-данными. Плюс настроить ротацию логов драйвера (`max-size`/`max-file` в `daemon.json`).

</details>

**D3.** Образ приложения весит 2.8 ГБ, хотя jar-файл — 40 МБ. С чего начнёшь расследование
и какие три типовые причины проверишь?

<details><summary>Ответ</summary>

Начать с `docker history --no-trunc <img>` и найти самые тяжёлые слои. Типовые причины:
(1) в образ тянется весь build-контекст (`COPY . .` без `.dockerignore`: `.git`, `node_modules`,
дампы); (2) в рантайм-образе остались сборочные зависимости (jdk вместо jre, `build-essential`,
кэш maven/npm) — лечится multi-stage; (3) кэши пакетных менеджеров и мусор удалены отдельным
`RUN`, а не в той же инструкции. Инструмент: `dive` для послойного анализа.

</details>

**D4.** Контейнер с PostgreSQL хранит данные внутри контейнера (без volume). Через месяц
диск кончился, а `docker ps -s` показывает у него SIZE 60GB. Объясни, что произошло
с точки зрения слоёв, и как правильно.

<details><summary>Ответ</summary>

Все записи БД шли в writable-слой контейнера через CoW: каждая правка страницы данных
копировала файл наверх, слой распух до 60 ГБ, производительность деградировала, а при удалении
контейнера данные были бы потеряны безвозвратно. Правильно: `-v pgdata:/var/lib/postgresql/data`
(named volume) — данные вне слоёв, на обычной ФС хоста, переживают пересоздание контейнера
и бэкапятся отдельно (тема 07).

</details>

**D5.** После переезда на новый сервер `docker pull` каждого образа тянет все слои заново,
хотя образы похожи. Какие причины? (Минимум две.)

<details><summary>Ответ</summary>

(1) Слои действительно новые: другая архитектура/база, пересборка `--no-cache`,
поменялся базовый образ; (2) на новом сервере пустой кэш — первый pull всегда полный, общими
станут только последующие; (3) в Dockerfile нарушен порядок слоёв: код копируется до установки
зависимостей, поэтому каждый билд инвалидирует все верхние слои и дайджесты меняются целиком;
(4) образы собираются с `--squash`/`export-import` — слои схлопнуты в один, переиспользовать нечего.

</details>

**D6.** Разработчик перезаписал тег `1.2.0` в registry новым образом. Через неделю прод
«внезапно» стал другой версией после перезапуска пода. Как такое предотвратить?

<details><summary>Ответ</summary>

Включить **immutable tags** в registry (ECR tag immutability, Harbor/GitLab настройка),
запретить переписывание релизных тегов в CI, деплоить по **дайджесту**
(`myapp@sha256:…`), подписывать образы (cosign) и проверять подпись на деплое.

</details>

**D7.** На arm-ноутбуке собрали образ и запушили; на серверах amd64 он падает с
`exec format error`. Причина и решение?

<details><summary>Ответ</summary>

Образ собран под arm64, серверы amd64 — платформы несовместимы. Решение: собирать
мультиарх через buildx (`docker buildx build --platform linux/amd64,linux/arm64 --push`),
либо строго `--platform linux/amd64` при сборке, либо собирать в CI на нужной архитектуре.
Проверить: <code v-pre>docker image inspect &lt;img&gt; --format '{{.Os}}/{{.Architecture}}'</code>.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое docker-образ и из чего он состоит?

<details><summary>Ответ</summary>

Неизменяемый артефакт: набор read-only слоёв + конфиг (CMD/ENV/USER…) + манифест,
всё адресуется по sha256.

</details>

**2.** Что такое слои и зачем они нужны?

<details><summary>Ответ</summary>

Слой — diff файловой системы от предыдущего шага. Нужны для переиспользования (общие слои
хранятся и качаются один раз) и кэширования сборки.

</details>

**3.** Чем образ отличается от контейнера?

<details><summary>Ответ</summary>

Образ — шаблон, только RO-слои. Контейнер — запущенный экземпляр: те же слои + writable-слой
+ namespaces/cgroups.

</details>

**4.** Что такое Copy-on-Write в докере?

<details><summary>Ответ</summary>

Механизм overlay-ФС: чтение идёт из нижних слоёв, при записи файл копируется в writable-слой
контейнера и изменяется там.

</details>

**5.** Почему удаление файлов в Dockerfile не всегда уменьшает образ?

<details><summary>Ответ</summary>

Потому что удаление создаёт новый слой с whiteout-меткой, а данные остаются в нижнем слое
и по-прежнему качаются. Удалять надо в той же инструкции `RUN`, где создавали.

</details>

**6.** Чем тег отличается от дайджеста?

<details><summary>Ответ</summary>

Тег — подвижная метка, дайджест — неизменяемый sha256 манифеста. Тег можно переназначить,
дайджест — нет.

</details>

**7.** Почему нельзя использовать `latest` в проде?

<details><summary>Ответ</summary>

Он ничего не гарантирует: непонятно, что в проде, нет воспроизводимого отката, кэш может
подсунуть старый образ.

</details>

**8.** Как правильно тегировать образы в CI?

<details><summary>Ответ</summary>

Точная версия (semver) + git SHA обязательно, плюс подвижные `major`/`minor` и `latest`
для удобства; релизные теги — иммутабельные; для критичного — пин по дайджесту.

</details>

**9.** Как посмотреть, из-за чего образ такой большой?

<details><summary>Ответ</summary>

`docker history --no-trunc`, `docker image inspect`, `docker system df -v`, утилита `dive`;
дальше — multi-stage, `.dockerignore`, чистка кэшей в том же `RUN`.

</details>

**10.** Что такое overlay2?

<details><summary>Ответ</summary>

Storage driver по умолчанию: объединяет каталоги слоёв (lowerdir) и writable-слой (upperdir)
в единую `merged` ФС с copy-on-write.

</details>

---

### 🎯 Чек-лист

- [ ] Читаю `docker history` и нахожу, из-за чего образ распух
- [ ] Объясняю CoW и почему БД не живёт в writable-слое
- [ ] Знаю, почему `rm` отдельным слоем не уменьшает образ
- [ ] Различаю Image ID, Digest и тег
- [ ] Имею готовую схему тегирования для CI и могу её защитить
- [ ] Умею переносить образы через save/load и знаю разницу с export/import
- [ ] Могу безопасно почистить диск на сервере (prune без потери данных)
- [ ] Проверяю архитектуру образа перед деплоем
