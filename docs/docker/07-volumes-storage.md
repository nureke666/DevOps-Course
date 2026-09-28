---
title: "07. Данные: volumes, bind mounts, tmpfs"
description: "Named volumes, bind mounts, tmpfs — как не терять данные при пересоздании контейнера, права доступа, бэкапы"
---

# 07. Данные: volumes, bind mounts, tmpfs

> Роадмап → практика: «примонтировать свой nginx.conf через bind mount», данные БД в compose.
> **После темы ты умеешь:** не терять данные при пересоздании контейнера, выбирать между
> volume и bind mount, чинить «permission denied» на монтировании и делать бэкап тома.

---

## 🗺️ Схема: три способа дать контейнеру данные

```text:no-line-numbers
                        ХОСТ                                  КОНТЕЙНЕР
 ┌────────────────────────────────────────────┐        ┌──────────────────────┐
 │ /var/lib/docker/volumes/pgdata/_data       │◄──────►│ /var/lib/postgresql  │  1. VOLUME
 │   управляется докером, переносимо,         │        │                      │     (named)
 │   бэкапится, драйверы (nfs, cloud)         │        │                      │
 ├────────────────────────────────────────────┤        ├──────────────────────┤
 │ /home/user/project/nginx.conf              │◄──────►│ /etc/nginx/nginx.conf│  2. BIND MOUNT
 │   ЛЮБОЙ путь хоста, зависит от машины      │        │                      │     (свой путь)
 ├────────────────────────────────────────────┤        ├──────────────────────┤
 │ (RAM, ничего на диске)                     │◄──────►│ /tmp                 │  3. TMPFS
 └────────────────────────────────────────────┘        └──────────────────────┘
                                                        ┌──────────────────────┐
                                                        │ writable-слой        │  ← НЕ хранилище:
                                                        │ (всё остальное)      │    умрёт с контейнером
                                                        └──────────────────────┘
```

| | Named volume | Bind mount | tmpfs |
|---|---|---|---|
| Где лежит | `/var/lib/docker/volumes/…` | любой путь хоста | RAM |
| Кто управляет | докер | ты | ядро |
| Переносимо между машинами | ✅ (через драйверы/бэкап) | ❌ зависит от путей хоста | — |
| Права/владелец | докер инициализирует из образа | как на хосте → частый конфликт UID | — |
| Производительность на Mac/Win | быстрее | медленно (виртуализация ФС) | быстро |
| Бэкап | `docker run --rm -v vol:/d …` | обычными средствами ОС | нет смысла |
| Типичное применение | **данные БД, стейт приложения** | **конфиги, исходники в dev, сокеты** | секреты, кэш, `/tmp` |

---

## 1. Named volumes

```bash
docker volume create pgdata
docker volume ls
docker volume inspect pgdata          # Mountpoint на хосте
docker volume rm pgdata
docker volume prune                   # ⚠️ удалит ВСЕ неиспользуемые тома
docker volume ls -f dangling=true     # тома, которые ни к чему не подключены

# Использование
docker run -d --name db \
  -e POSTGRES_PASSWORD=secret \
  -v pgdata:/var/lib/postgresql/data \
  postgres:16

# Современный синтаксис --mount (более явный, рекомендуется)
docker run -d --name db \
  --mount type=volume,source=pgdata,target=/var/lib/postgresql/data \
  postgres:16
```

**Важное поведение:** если named volume **пустой**, докер при первом монтировании
**копирует в него содержимое** каталога из образа (вместе с правами и владельцем).
Это и есть причина, по которой у named volume обычно не бывает проблем с правами,
в отличие от bind mount. У bind mount копирования **не происходит** — содержимое каталога
образа просто скрывается под смонтированным.

---

## 2. Bind mounts

```bash
# -v ПУТЬ_ХОСТА:ПУТЬ_КОНТЕЙНЕРА[:опции]  — путь хоста ДОЛЖЕН быть абсолютным
docker run -d --name web -p 8080:80 \
  -v "$PWD/nginx.conf:/etc/nginx/nginx.conf:ro" \
  -v "$PWD/html:/usr/share/nginx/html:ro" \
  nginx:alpine

docker run -d --name web \
  --mount type=bind,source="$PWD/html",target=/usr/share/nginx/html,readonly \
  nginx:alpine
```

| Опция | Смысл |
|-------|-------|
| `:ro` | Только чтение ⭐ для конфигов — всегда |
| `:rw` | Чтение/запись (по умолчанию) |
| `:z` / `:Z` | Перемаркировка SELinux (RHEL/Fedora): общий / приватный |
| `:delegated`, `:cached` | Оптимизации для Docker Desktop на macOS |

**Грабли bind mount:**

1. **Относительный путь в `-v`** создаёт **named volume** с этим именем, а не bind mount:
   `-v ./conf:/etc/conf` в `docker run` — ошибка (в compose — работает и означает bind mount).
   Используй `$(pwd)/conf` или `--mount type=bind`.
2. **Файла нет на хосте** → докер создаст **каталог** (старое поведение) или упадёт с ошибкой.
   Перед монтированием файла убедись, что он существует.
3. **UID/GID.** Внутри контейнера процесс может быть `app` (UID 999), а файл на хосте
   принадлежит тебе (UID 1000) → `Permission denied`. Решения: `--user $(id -u):$(id -g)`,
   `chown` на хосте, named volume вместо bind, ACL.
4. **Монтирование поверх каталога полностью его перекрывает**:
   `-v $PWD:/app` спрячет `/app/node_modules` из образа. Лечится «пустым» томом поверх:
   `-v $PWD:/app -v /app/node_modules`.
5. **`:ro` не защищает от всего** — если процесс в контейнере root, он может испортить
   то, на что имеет права; `:ro` защищает именно от записи в смонтированное.

---

## 3. tmpfs

```bash
docker run -d --tmpfs /tmp:rw,noexec,nosuid,size=64m nginx
docker run -d --mount type=tmpfs,destination=/app/cache,tmpfs-size=100m myapp
```
Данные в RAM: быстро, исчезают при остановке, не попадают на диск.
Для секретов, временных файлов и связки с `--read-only`:

```bash
docker run -d --read-only --tmpfs /tmp --tmpfs /run nginx:alpine
```

---

## 4. Правильная работа с данными

```text:no-line-numbers
Правило: КОНТЕЙНЕР ОДНОРАЗОВЫЙ. Всё, что должно пережить пересоздание, — в volume.
```

| Что | Куда |
|-----|------|
| Данные БД | named volume (или внешняя managed-БД) |
| Загруженные пользователями файлы | named volume / S3-совместимое хранилище ⭐ |
| Конфиги | bind mount `:ro` / configs в compose / образ |
| Секреты | не в образ: env из секрет-хранилища, docker secrets, tmpfs |
| Логи | stdout → сборщик логов, а не файл в контейнере |
| Кэш сборки | volume или BuildKit cache mount |
| Временные файлы | tmpfs или writable-слой (не жалко) |

### Бэкап и восстановление тома

```bash
# Бэкап
docker run --rm -v pgdata:/data:ro -v "$PWD":/backup alpine \
  tar czf /backup/pgdata-$(date +%F).tar.gz -C /data .

# Восстановление
docker volume create pgdata-new
docker run --rm -v pgdata-new:/data -v "$PWD":/backup alpine \
  tar xzf /backup/pgdata-2026-09-13.tar.gz -C /data

# Копия тома
docker run --rm -v pgdata:/from -v pgdata-copy:/to alpine sh -c 'cp -a /from/. /to/'
```

> ⚠️ Для БД холодная копия файлов данных **на работающей базе** может оказаться нецелостной.
> Правильный бэкап БД — её родными средствами (`pg_dump`/`pgBackRest`, `mysqldump`/xtrabackup),
> запущенными в контейнере.

```bash
docker exec db pg_dump -U postgres app > dump.sql
docker exec -i db psql -U postgres app < dump.sql
```

### Где место кончилось

```bash
docker system df -v                     # разделы: images / containers / volumes / build cache
docker volume ls -f dangling=true       # осиротевшие тома (часто гигабайты)
sudo du -sh /var/lib/docker/volumes/* | sort -h | tail
docker ps -s                            # writable-слои контейнеров
```

> `docker volume prune` удаляет **все** неиспользуемые тома. Перед запуском — посмотреть глазами,
> что в списке: анонимный том с продовой базой выглядит так же, как мусор.

---

## 💼 Как это в DevOps

- **Stateless-приложения** — цель: контейнер можно убить в любой момент. Состояние — в БД,
  объектном хранилище, кэше. Это то, что делает возможными автоскейлинг и rolling update.
- **Stateful в контейнерах** (БД) на одиночном сервере — нормально с named volume и бэкапами;
  в k8s — PersistentVolume/StatefulSet, и это отдельная большая тема.
- **Bind mount — инструмент разработки** (hot reload исходников) и доставки конфигов на
  одиночном сервере. В кластере вместо него — ConfigMap/Secret.
- `-v /var/run/docker.sock:/var/run/docker.sock` — самый частый **опасный** bind mount:
  это выдача root на хосте (тема 10).

---

## 🧪 Мини-лаба: данные переживают контейнер

```bash
mkdir -p ~/docker-lab/07 && cd ~/docker-lab/07

# 1. БЕЗ тома — данные умирают вместе с контейнером
docker run -d --name db-bad -e POSTGRES_PASSWORD=pw postgres:16-alpine
sleep 8
docker exec db-bad psql -U postgres -c "CREATE TABLE t(id int); INSERT INTO t VALUES (42);"
docker exec db-bad psql -U postgres -c "SELECT * FROM t;"
docker rm -f db-bad
docker run -d --name db-bad -e POSTGRES_PASSWORD=pw postgres:16-alpine
sleep 8
docker exec db-bad psql -U postgres -c "SELECT * FROM t;"    # ❌ relation "t" does not exist
docker rm -f db-bad

# 2. С томом — данные живут
docker volume create pgdata
docker run -d --name db -e POSTGRES_PASSWORD=pw -v pgdata:/var/lib/postgresql/data postgres:16-alpine
sleep 8
docker exec db psql -U postgres -c "CREATE TABLE t(id int); INSERT INTO t VALUES (42);"
docker rm -f db
docker run -d --name db -e POSTGRES_PASSWORD=pw -v pgdata:/var/lib/postgresql/data postgres:16-alpine
sleep 8
docker exec db psql -U postgres -c "SELECT * FROM t;"        # ✅ 42
docker volume inspect pgdata --format '{{.Mountpoint}}'
sudo ls $(docker volume inspect pgdata --format '{{.Mountpoint}}') | head

# 3. Бэкап и восстановление
docker run --rm -v pgdata:/data:ro -v "$PWD":/backup alpine \
  tar czf /backup/pgdata.tar.gz -C /data . && ls -lh pgdata.tar.gz
docker exec db pg_dump -U postgres postgres > dump.sql && head -5 dump.sql

# «катастрофа» и восстановление из дампа
docker rm -f db; docker volume rm pgdata
docker volume create pgdata
docker run -d --name db -e POSTGRES_PASSWORD=pw -v pgdata:/var/lib/postgresql/data postgres:16-alpine
sleep 8
docker exec -i db psql -U postgres < dump.sql >/dev/null
docker exec db psql -U postgres -c "SELECT * FROM t;"        # ✅ 42 восстановлено

# 4. Bind mount: свой конфиг nginx (задание из роадмапа)
mkdir -p html
echo '<h1>Моя статика</h1>' > html/index.html
cat > nginx.conf <<'EOF'
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    location / { try_files $uri $uri/ =404; }
    location /health { return 200 "ok\n"; add_header Content-Type text/plain; }
}
EOF
docker run -d --name web -p 8080:80 \
  -v "$PWD/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
  -v "$PWD/html:/usr/share/nginx/html:ro" \
  nginx:alpine
curl -s localhost:8080; curl -s localhost:8080/health
echo '<h1>Изменено на хосте</h1>' > html/index.html
curl -s localhost:8080                       # ⭐ изменения видны СРАЗУ, без пересборки
docker exec web sh -c 'echo x > /usr/share/nginx/html/hack.html' 2>&1 | head -1   # ro → отказ

# 5. Монтирование перекрывает содержимое образа
docker run --rm alpine ls /etc | head -3
docker run --rm -v "$PWD/html:/etc" alpine ls /etc          # видно только index.html

# 6. Права: UID-конфликт
mkdir -p data && echo "hello" > data/file.txt
docker run --rm -v "$PWD/data:/data" --user 1001:1001 alpine sh -c 'echo test >> /data/file.txt' \
  2>&1 | head -1                                            # Permission denied
docker run --rm -v "$PWD/data:/data" --user "$(id -u):$(id -g)" alpine sh -c 'echo ok >> /data/file.txt' && \
  tail -1 data/file.txt                                     # ✅

# 7. tmpfs и read-only
docker run -d --name ro --read-only --tmpfs /tmp --tmpfs /var/cache/nginx --tmpfs /run nginx:alpine
docker exec ro sh -c 'echo x > /tmp/ok && echo "в /tmp пишется"'
docker exec ro sh -c 'echo x > /etc/test' 2>&1 | head -1    # Read-only file system
docker rm -f ro

# 8. Анонимные тома — откуда берётся мусор
docker run -d --name anon -v /var/lib/postgresql/data -e POSTGRES_PASSWORD=pw postgres:16-alpine
docker volume ls | tail -3                                  # появился том со случайным именем
docker rm -f anon
docker volume ls -f dangling=true                           # он остался висеть
docker volume prune -f

# 9. Уборка
docker rm -f web db 2>/dev/null; docker volume rm pgdata 2>/dev/null
cd ~ && rm -rf ~/docker-lab/07
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `docker volume create NAME` | Создать том |
| `docker volume ls [-f dangling=true]` | Список / осиротевшие |
| `docker volume inspect NAME` | Где лежит на хосте, драйвер, метки |
| `docker volume rm NAME` / `prune` | Удалить / снести неиспользуемые ⚠️ |
| `-v vol:/path` | Named volume |
| `-v /abs/path:/path:ro` | Bind mount только для чтения |
| `--mount type=volume,source=v,target=/p` | То же явным синтаксисом |
| `--mount type=bind,source=/p,target=/p,readonly` | Bind mount |
| `--tmpfs /tmp:size=64m,noexec` | tmpfs |
| `--read-only` | ФС контейнера только для чтения |
| `docker run --rm -v vol:/d -v $PWD:/b alpine tar czf /b/v.tgz -C /d .` | Бэкап тома |
| `docker cp c:/path ./` | Разовое копирование файла |
| `docker ps -s`, `docker system df -v` | Размер writable-слоёв и томов |

---

## 🧠 Что запомнить

1. Всё, что не в volume, **умирает вместе с контейнером** (writable-слой).
2. **Named volume** — для данных (БД, стейт): управляется докером, переносим, бэкапится.
3. **Bind mount** — для конфигов и разработки: конкретный путь хоста, зависит от машины.
4. **tmpfs** — временное и секретное, живёт в RAM.
5. Пустой named volume **наследует содержимое и права** из образа; bind mount — **перекрывает**.
6. В `docker run` путь хоста в `-v` должен быть **абсолютным**, иначе получишь named volume
   со странным именем.
7. Конфиги монтируй с `:ro`.
8. Конфликт UID/GID — главный источник `Permission denied`: `--user`, `chown`, named volume.
9. Анонимные тома (`-v /path` и `VOLUME` в Dockerfile) копятся мусором — чисти
   `docker rm -v` / `docker volume prune` (осознанно!).
10. Холодный бэкап файлов работающей БД ненадёжен — используй `pg_dump`/`mysqldump`.
11. `docker volume prune` не спрашивает, что за данные внутри — смотри глазами до запуска.
12. Монтирование `/var/run/docker.sock` = выдача root на хосте.

---

## Задачи

> Лаба: `mkdir -p ~/docker-lab/07 && cd ~/docker-lab/07`
> ⚠️ В этой теме особенно осторожно с `docker volume prune` — сначала смотри, что удаляешь.

---

### Блок A. Теория

**A1.** Три способа дать контейнеру данные. Для каждого — где физически лежит и когда применять.

<details><summary>Ответ</summary>

(1) **Named volume** — `/var/lib/docker/volumes/<name>/_data`, управляется докером;
для данных приложения и БД. (2) **Bind mount** — произвольный путь хоста; для конфигов,
исходников в разработке, сокетов. (3) **tmpfs** — в оперативной памяти; для временных файлов
и секретов, ничего не попадает на диск.

</details>

**A2.** Что произойдёт с данными, записанными в контейнер без тома, при `docker rm` + `docker run`?

<details><summary>Ответ</summary>

Потеряются: они жили в writable-слое контейнера, который уничтожается вместе с ним.
Новый контейнер стартует из чистого образа.

</details>

**A3.** Чем named volume лучше bind mount для базы данных? Три аргумента.

<details><summary>Ответ</summary>

(1) Управляется докером: понятный жизненный цикл, `docker volume ls/inspect/rm`,
бэкап единообразный; (2) не зависит от структуры каталогов хоста — конфигурация переносима;
(3) корректные права (инициализируется из образа), нет UID-конфликтов; плюс поддержка
драйверов (NFS, cloud-диски) и лучшая производительность на Docker Desktop.

</details>

**A4.** Что происходит при монтировании **пустого** named volume в каталог, где в образе
уже есть файлы? А если том не пустой? А если это bind mount?

<details><summary>Ответ</summary>

Пустой named volume — докер **копирует** в него содержимое каталога из образа
вместе с правами. Непустой — копирования нет, содержимое образа скрывается. Bind mount —
копирования нет **никогда**: каталог хоста (даже пустой) полностью перекрывает содержимое
образа по этому пути.

</details>

**A5.** Почему `-v ./conf:/etc/conf` в `docker run` — ошибка, а в docker compose — нормально?

<details><summary>Ответ</summary>

В `docker run` источник, не начинающийся с `/` или `./`-разрешённого абсолютного пути,
трактуется как **имя тома**: получится named volume с именем `./conf` (или ошибка).
Docker Compose разворачивает относительные пути относительно файла compose и передаёт
абсолютные — поэтому там `./conf:/etc/conf` работает как bind mount.

</details>

**A6.** Зачем монтировать конфиги с `:ro`?

<details><summary>Ответ</summary>

Чтобы приложение (особенно работающее от root) не могло изменить конфиг:
защита от случайной порчи, от закрепления злоумышленника, и гарантия, что источник истины —
файл в git, а не то, что «подправили в контейнере».

</details>

**A7.** Что такое анонимный том, откуда он берётся и чем опасен?

<details><summary>Ответ</summary>

Том без имени, создаётся при `-v /path` без источника или при `VOLUME` в Dockerfile.
Опасен тем, что накапливается: имена случайные, понять, что внутри, невозможно,
место кончается незаметно. Удаляется `docker rm -v` или `docker volume prune`.

</details>

**A8.** Почему при bind mount часто возникает `Permission denied` и какие есть три решения?

<details><summary>Ответ</summary>

Владелец файлов на хосте (обычно UID 1000) не совпадает с UID процесса в контейнере
(например, 999 или 65534), а ядро сверяет **числовые** UID/GID, а не имена. Решения:
`--user $(id -u):$(id -g)`, `chown`/`setfacl` на хосте под нужный UID, использовать named volume
(наследует права из образа), либо собирать образ с нужным UID.

</details>

**A9.** Что делает `--read-only` и почему вместе с ним обычно нужен `--tmpfs`?

<details><summary>Ответ</summary>

`--read-only` делает корневую ФС контейнера доступной только для чтения — защита от
модификации приложения/подкладывания бинарников. Большинству приложений всё же нужно писать
во временные каталоги (`/tmp`, `/run`, кэши nginx), поэтому их подключают как tmpfs или volume.

</details>

**A10.** Как сделать бэкап named volume? Почему для БД это не лучший способ?

<details><summary>Ответ</summary>

`docker run --rm -v vol:/data:ro -v $PWD:/backup alpine tar czf /backup/vol.tgz -C /data .`
Для БД это «холодная» копия работающих файлов — возможна нецелостность (страницы в процессе
записи, WAL). Правильно: `pg_dump`/`mysqldump`/xtrabackup, либо остановить БД перед копированием,
либо снапшот ФС/тома.

</details>

**A11.** Чем `docker cp` отличается от bind mount? Когда что использовать?

<details><summary>Ответ</summary>

`docker cp` — разовое копирование в/из контейнера (снимок на момент выполнения),
работает и с остановленным контейнером. Bind mount — постоянная связь: изменения на хосте
видны внутри мгновенно. `cp` — для отладки и выгрузки артефактов, bind — для конфигов и разработки.

</details>

**A12.** Что такое stateless-приложение и почему к этому стремятся?

<details><summary>Ответ</summary>

Приложение не хранит состояние локально: любой экземпляр может обработать любой запрос,
контейнер можно убить и пересоздать без последствий. Состояние выносится в БД, кэш (Redis),
объектное хранилище. Это условие горизонтального масштабирования, rolling update и автолечения.

</details>

**A13.** Куда девать пользовательские загрузки (uploads) в контейнеризованном приложении?

<details><summary>Ответ</summary>

В объектное хранилище (S3/MinIO) — правильный вариант для нескольких реплик;
либо на общий сетевой том (NFS/CephFS); named volume годится только для одного экземпляра
на одном хосте. Хранить в writable-слое нельзя.

</details>

**A14.** Почему монтирование `/var/run/docker.sock` в контейнер опасно?

<details><summary>Ответ</summary>

Через сокет отдаётся полный контроль над демоном, работающим от root: можно запустить
`--privileged` контейнер с `-v /:/host` и получить весь хост, прочитать секреты, подменить
образы. Альтернативы: rootless-докер, buildah/rootless BuildKit для сборки (kaniko архивирован
в 2025), отдельный build-сервис, socket-proxy с ограничением API-эндпоинтов.

</details>

**A15.** Как посмотреть, сколько места занимают тома, и найти осиротевшие?

<details><summary>Ответ</summary>

`docker system df -v` (раздел VOLUMES), `docker volume ls -f dangling=true`,
`sudo du -sh /var/lib/docker/volumes/* | sort -h | tail`, `docker ps -s` для writable-слоёв.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  docker volume create pgdata
B2.  docker volume inspect pgdata --format '{{.Mountpoint}}'
B3.  docker run -d -v pgdata:/var/lib/postgresql/data postgres:16
B4.  docker run -d -v "$PWD/nginx.conf:/etc/nginx/nginx.conf:ro" nginx
B5.  docker run -d --mount type=bind,source="$PWD/html",target=/usr/share/nginx/html,readonly nginx
B6.  docker run --rm --tmpfs /tmp:rw,noexec,size=64m alpine df -h /tmp
B7.  docker run -d --read-only --tmpfs /var/cache/nginx --tmpfs /run nginx:alpine
B8.  docker volume ls -f dangling=true
B9.  docker volume prune
B10. docker rm -v mycontainer
B11. docker run --rm -v pgdata:/data:ro -v "$PWD":/b alpine tar czf /b/v.tgz -C /data .
B12. docker run --rm -v "$PWD/data:/data" --user "$(id -u):$(id -g)" alpine touch /data/x
B13. docker ps -s
B14. docker inspect web --format '{{json .Mounts}}'
```

**B1.** Создать named volume.
**B2.** Показать путь тома на хосте.
**B3.** Запустить postgres с данными в томе — данные переживут пересоздание контейнера.
**B4.** Подмонтировать свой конфиг nginx только для чтения.
**B5.** То же явным синтаксисом `--mount` (ошибётся, если источника нет — в отличие от `-v`).
**B6.** tmpfs на 64 МБ с запретом исполнения; `df -h` покажет его.
**B7.** nginx с неизменяемой корневой ФС и tmpfs для того, что ему нужно писать.
**B8.** Список томов, не подключённых ни к одному контейнеру.
**B9.** ⚠️ Удалить все неиспользуемые тома (потенциальная потеря данных).
**B10.** Удалить контейнер вместе с его **анонимными** томами (named не трогает).
**B11.** Сделать tar-бэкап тома через временный контейнер.
**B12.** Запустить с UID/GID текущего пользователя — типовое решение проблемы прав при bind mount.
**B13.** Размер writable-слоёв контейнеров.
**B14.** Все монтирования контейнера: тип, источник, назначение, режим.

**B15.** Чем отличается `-v myvol:/data` от `-v /home/user/data:/data`
с точки зрения того, что докер сделает при запуске?

<details><summary>Ответ</summary>

`-v myvol:/data` — если тома `myvol` нет, докер **создаст** его и при первом
монтировании скопирует туда содержимое `/data` из образа. `-v /home/user/data:/data` —
bind mount: докер возьмёт каталог хоста как есть (создаст, если отсутствует), содержимое
образа по этому пути будет скрыто, копирования не будет.

</details>

---

### Блок C. Практика

#### C1. 🔑 Данные переживают пересоздание (главное задание)

1. Запусти PostgreSQL **без** тома, создай таблицу с данными, пересоздай контейнер —
   покажи потерю данных.
2. Запусти с named volume, повтори — покажи сохранность.
3. Найди физический путь тома на хосте, посмотри содержимое.
4. Сделай логический бэкап (`pg_dump`) и файловый бэкап тома (tar).
5. «Уничтожь» том и восстанови базу из логического бэкапа.
6. Объясни, в каких случаях файловый бэкап тома опаснее логического.

<details><summary>Ответ</summary>

```bash
mkdir -p ~/docker-lab/07 && cd ~/docker-lab/07
docker run -d --name db0 -e POSTGRES_PASSWORD=pw postgres:16-alpine; sleep 8
docker exec db0 psql -U postgres -c "CREATE TABLE t(id int); INSERT INTO t VALUES (42);"
docker rm -f db0
docker run -d --name db0 -e POSTGRES_PASSWORD=pw postgres:16-alpine; sleep 8
docker exec db0 psql -U postgres -c "SELECT * FROM t;"      # ошибка: таблицы нет
docker rm -f db0

docker volume create pgdata
docker run -d --name db -e POSTGRES_PASSWORD=pw -v pgdata:/var/lib/postgresql/data postgres:16-alpine; sleep 8
docker exec db psql -U postgres -c "CREATE TABLE t(id int); INSERT INTO t VALUES (42);"
docker rm -f db
docker run -d --name db -e POSTGRES_PASSWORD=pw -v pgdata:/var/lib/postgresql/data postgres:16-alpine; sleep 8
docker exec db psql -U postgres -c "SELECT * FROM t;"       # 42 ✅
sudo ls $(docker volume inspect pgdata --format '{{.Mountpoint}}') | head -5

docker exec db pg_dump -U postgres postgres > dump.sql
docker run --rm -v pgdata:/data:ro -v "$PWD":/b alpine tar czf /b/pgdata.tgz -C /data .
docker rm -f db; docker volume rm pgdata
docker volume create pgdata
docker run -d --name db -e POSTGRES_PASSWORD=pw -v pgdata:/var/lib/postgresql/data postgres:16-alpine; sleep 8
docker exec -i db psql -U postgres < dump.sql >/dev/null
docker exec db psql -U postgres -c "SELECT * FROM t;"       # 42 ✅
# Файловый бэкап работающей БД опаснее: страницы могут копироваться в момент записи,
# WAL и файлы данных окажутся рассогласованными → «page corruption» при восстановлении.
```

</details>

#### C2. Nginx со своим конфигом и статикой (задание из роадмапа)

Подними nginx, не пересобирая образ:
- свой `nginx.conf`/`default.conf` через bind mount `:ro`;
- своя статика из каталога хоста;
- проброс порта 8080 → 80;
- эндпоинт `/health`, возвращающий 200.

Проверь:
1. Правка `index.html` на хосте видна сразу, без перезапуска.
2. Правка `nginx.conf` требует `docker exec nginx -s reload` или рестарта — объясни почему.
3. Изнутри контейнера записать в статику нельзя (`:ro`).

<details><summary>Ответ</summary>

```bash
mkdir -p html && echo '<h1>Моя статика</h1>' > html/index.html
cat > default.conf <<'EOF'
server {
    listen 80;
    root /usr/share/nginx/html;
    location / { try_files $uri $uri/ =404; }
    location /health { return 200 "ok\n"; add_header Content-Type text/plain; }
}
EOF
docker run -d --name web -p 8080:80 \
  -v "$PWD/default.conf:/etc/nginx/conf.d/default.conf:ro" \
  -v "$PWD/html:/usr/share/nginx/html:ro" nginx:alpine
curl -s localhost:8080; curl -s localhost:8080/health
echo '<h1>v2</h1>' > html/index.html && curl -s localhost:8080     # сразу видно
sed -i 's|"ok\\n"|"OK2\\n"|' default.conf
curl -s localhost:8080/health                                       # старый ответ
docker exec web nginx -s reload && curl -s localhost:8080/health    # новый
# Статика читается при каждом запросе, конфиг nginx — только при старте/reload.
docker exec web sh -c 'echo x > /usr/share/nginx/html/h.html' 2>&1 | head -1   # ro
docker rm -f web
```

</details>

#### C3. Перекрытие содержимого

1. Покажи, что монтирование каталога поверх существующего в образе полностью его скрывает.
2. Воспроизведи классическую проблему Node: `-v $PWD:/app` прячет `/app/node_modules` из образа.
3. Почини её «анонимным томом поверх» (`-v /app/node_modules`), объясни механику.

<details><summary>Ответ</summary>

```bash
docker run --rm alpine ls /etc | wc -l
docker run --rm -v "$PWD/html:/etc" alpine ls /etc          # только index.html
mkdir -p node_app && cd node_app
printf 'FROM node:22-alpine\nWORKDIR /app\nRUN npm init -y >/dev/null && npm i lodash >/dev/null\nCMD ["node","-e","console.log(require(\x27lodash\x27).VERSION)"]\n' > Dockerfile
docker build -q -t nodedemo . && docker run --rm nodedemo               # версия печатается
docker run --rm -v "$PWD:/app" nodedemo 2>&1 | head -2                  # Cannot find module 'lodash'
docker run --rm -v "$PWD:/app" -v /app/node_modules nodedemo            # снова работает ✅
cd ..
# Анонимный том поверх /app/node_modules «прикрывает» этот подкаталог, и в нём остаётся
# содержимое из образа, а не пустота с хоста.
```

</details>

#### C4. Права доступа

1. Создай на хосте каталог и файл от своего пользователя.
2. Запусти контейнер с `--user 1001:1001` и попробуй записать — получи `Permission denied`.
3. Реши проблему тремя способами: `--user $(id -u):$(id -g)`, `chown` на хосте,
   named volume вместо bind.
4. Покажи, как named volume наследует владельца из образа
   (например, том для postgres принадлежит UID 999).

<details><summary>Ответ</summary>

```bash
mkdir -p data && echo hello > data/file.txt
docker run --rm -v "$PWD/data:/data" --user 1001:1001 alpine sh -c 'echo x >> /data/file.txt' 2>&1 | head -1
docker run --rm -v "$PWD/data:/data" --user "$(id -u):$(id -g)" alpine sh -c 'echo ok >> /data/file.txt' && tail -1 data/file.txt
sudo chown -R 1001:1001 data && docker run --rm -v "$PWD/data:/data" --user 1001:1001 alpine sh -c 'echo ok2 >> /data/file.txt'
sudo chown -R "$(id -u):$(id -g)" data
docker run -d --name pg -e POSTGRES_PASSWORD=pw -v pgd:/var/lib/postgresql/data postgres:16-alpine; sleep 6
sudo ls -ld $(docker volume inspect pgd --format '{{.Mountpoint}}')     # владелец 999 — из образа
docker rm -f pg; docker volume rm pgd
```

</details>

#### C5. read-only контейнер

Запусти nginx с `--read-only`, добейся, чтобы он работал (подсказка: ему нужны
`/var/cache/nginx`, `/run`, `/tmp`). Докажи, что записать в `/etc` нельзя.
Зачем такая конфигурация в проде?

<details><summary>Ответ</summary>

```bash
docker run -d --name ro --read-only --tmpfs /var/cache/nginx --tmpfs /run --tmpfs /tmp -p 8080:80 nginx:alpine
sleep 2; curl -sI localhost:8080 | head -1
docker exec ro sh -c 'echo x > /etc/nginx/test' 2>&1 | head -1   # Read-only file system
docker exec ro sh -c 'echo x > /tmp/ok && echo tmp-ok'
docker rm -f ro
# В проде: приложение не может изменить свои бинарники/конфиги, злоумышленник не запишет
# веб-шелл или бэкдор; вся изменяемая область явно перечислена и контролируется.
```

</details>

#### C6. Мусор из анонимных томов

1. Запусти контейнер с `-v /data` (без имени) — найди появившийся том.
2. Удали контейнер обычным `docker rm` — том остался?
3. Повтори с `docker rm -v`.
4. Найди все осиротевшие тома и посчитай, сколько места они занимают.
5. Напиши безопасную процедуру их очистки (что проверить перед `prune`).

<details><summary>Ответ</summary>

```bash
docker run -d --name anon -v /data alpine sleep 300
docker volume ls | tail -2
docker rm -f anon; docker volume ls -f dangling=true | tail -2        # том остался
docker run -d --name anon2 -v /data alpine sleep 300 && docker rm -f anon2 >/dev/null
docker rm -v anon2 2>/dev/null
sudo du -sh /var/lib/docker/volumes/* 2>/dev/null | sort -h | tail -5
# Безопасная процедура: 1) docker volume ls -f dangling=true
# 2) для каждого — docker volume inspect + заглянуть внутрь (docker run --rm -v v:/x alpine ls /x)
# 3) убедиться, что это не данные БД остановленного сервиса
# 4) только потом docker volume rm <конкретные имена>, не prune вслепую.
docker volume prune -f
```

</details>

#### C7. Перенос данных между машинами

Сымитируй переезд: сделай бэкап тома в архив, удали том, восстанови его
под новым именем и подключи к новому контейнеру. Проверь целостность данных.

<details><summary>Ответ</summary>

```bash
docker volume create src && docker run --rm -v src:/d alpine sh -c 'echo важные-данные > /d/f.txt'
docker run --rm -v src:/d:ro -v "$PWD":/b alpine tar czf /b/src.tgz -C /d .
docker volume rm src
docker volume create dst
docker run --rm -v dst:/d -v "$PWD":/b alpine tar xzf /b/src.tgz -C /d
docker run --rm -v dst:/d alpine cat /d/f.txt        # важные-данные ✅
docker volume rm dst
```

</details>

#### C8. tmpfs

1. Смонтируй `/tmp` как tmpfs с лимитом 32 МБ.
2. Попробуй записать 50 МБ — что произойдёт?
3. Покажи, что после рестарта контейнера данные исчезли.
4. Назови два реальных применения tmpfs.

<details><summary>Ответ</summary>

```bash
docker run -d --name t --tmpfs /tmp:rw,size=32m alpine sleep 300
docker exec t df -h /tmp
docker exec t sh -c 'dd if=/dev/zero of=/tmp/big bs=1M count=50' 2>&1 | tail -1   # No space left
docker exec t sh -c 'echo data > /tmp/x'; docker restart t; sleep 1
docker exec t ls /tmp                                # пусто — tmpfs очистилась
docker rm -f t
# Применения: (1) секреты, которые не должны попасть на диск; (2) горячий кэш/временные файлы
# приложения, в паре с --read-only.
cd ~ && rm -rf ~/docker-lab/07
```

</details>

---

### Блок D. Инциденты

**D1.** После планового обновления образа БД все данные пропали. Что сделали не так
и как было правильно?

<details><summary>Ответ</summary>

Данные хранились в writable-слое контейнера (или в анонимном томе, который не
переподключили), и при пересоздании контейнера с новым образом всё пропало. Правильно:
named volume на каталог данных БД + регулярный логический бэкап + проверка восстановления;
обновление образа не должно затрагивать том.

</details>

**D2.** `docker compose down -v` на проде — что произойдёт? Чем `down` отличается от `down -v`
и от `stop`?

<details><summary>Ответ</summary>

`stop` — останавливает контейнеры; `down` — останавливает и удаляет контейнеры и сети,
**именованные тома остаются**; `down -v` — дополнительно **удаляет тома** проекта, то есть
все данные БД. На проде `down -v` — это потеря данных; такую команду в рантбуках не держат.

</details>

**D3.** Приложение пишет загрузки в `/app/uploads` внутри контейнера. При масштабировании
до 3 реплик пользователи «теряют» файлы: то видят, то нет. Диагноз и решение.

<details><summary>Ответ</summary>

Файлы пишутся в локальный writable-слой/локальный том каждой реплики, поэтому
пользователь видит файл только когда попадает на «свою» реплику. Решение: объектное хранилище
(S3/MinIO) или общий сетевой том (NFS/CephFS); приложение должно быть stateless.

</details>

**D4.** Диск забит: `/var/lib/docker/volumes` = 300 ГБ, при этом запущено 5 контейнеров.
Разбери причины и составь безопасный план очистки.

<details><summary>Ответ</summary>

Причины: тома от удалённых контейнеров (dangling), анонимные тома от частых
пересозданий, данные БД, логи/дампы внутри томов, бэкапы, забытые тестовые стенды.
План: `docker system df -v` → `docker volume ls -f dangling=true` → **осмотреть каждый**
(`docker run --rm -v v:/x alpine du -sh /x`) → удалить только заведомо мусорные по именам,
затем `docker container prune`, `docker image prune -a`, `docker builder prune`.
`docker volume prune` — в последнюю очередь и осознанно.

</details>

**D5.** Контейнер с приложением падает: `Permission denied: '/data/app.log'`.
В образе `USER app` (UID 999), на хосте каталог принадлежит `user:user` (1000).
Три способа починить, какой выберешь в проде и почему.

<details><summary>Ответ</summary>

(1) `chown -R 999:999` каталога на хосте — просто, но каталог становится
«привязан» к UID образа; (2) запускать контейнер `--user 1000:1000` — но тогда процесс
может не иметь прав на файлы из образа; (3) заменить bind mount на **named volume** —
докер сам выставит владельца из образа. В проде обычно (3) для данных и (1) для случаев,
когда путь на хосте обязателен. Дополнительно — согласовать UID при сборке образа.

</details>

**D6.** После монтирования `-v $PWD/config.yml:/app/config.yml` внутри контейнера
вместо файла оказался **каталог** `config.yml`. Почему?

<details><summary>Ответ</summary>

На хосте файла `config.yml` не существовало (опечатка в пути, другой рабочий каталог),
и докер создал вместо него **каталог** — старое поведение `-v`. Лечение: убедиться, что файл
есть, использовать `--mount type=bind,...` (падает с понятной ошибкой, если источника нет),
либо монтировать каталог целиком.

</details>

**D7.** Разработчик смонтировал `/var/run/docker.sock` в контейнер CI. Через неделю
на сервере обнаружили майнер. Объясни цепочку.

<details><summary>Ответ</summary>

Через сокет контейнер получил полный доступ к API демона (root). Уязвимость/
скомпрометированная зависимость в пайплайне позволила запустить свой контейнер
(`--privileged`, `-v /:/host`), закрепиться на хосте и развернуть майнер. Правильно:
не монтировать сокет; сборка через buildah/rootless BuildKit (kaniko архивирован в 2025);
при необходимости — socket-proxy с белым списком эндпоинтов и read-only доступом.

</details>

**D8.** Бэкап тома с MySQL восстановился, но база не стартует: «InnoDB: Database page
corruption». Что было сделано неправильно?

<details><summary>Ответ</summary>

Файлы данных копировались на **работающей** базе: часть страниц и журналов
оказалась несогласованной. Правильно: `mysqldump`/`xtrabackup` (горячий консистентный бэкап),
либо остановить контейнер БД перед tar-копией, либо снапшот тома/ФС с поддержкой
консистентности + проверка восстановления.

</details>

**D9.** На Docker Desktop (Mac) сборка и работа приложения с bind mount исходников
дико тормозит. Причины и что предложить.

<details><summary>Ответ</summary>

На macOS/Windows контейнеры работают в виртуальной машине, и bind mount ходит через
проброс ФС (gRPC-FUSE/VirtioFS) — это медленно, особенно на тысячах мелких файлов
(node_modules, .git). Решения: включить VirtioFS, держать зависимости в **named volume**
вместо bind, исключить тяжёлые каталоги из синхронизации, использовать
Dev Containers/удалённую разработку, на Linux-хосте проблема отсутствует.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как хранить данные в докере? Какие есть типы монтирования?

<details><summary>Ответ</summary>

Named volumes (управляет докер), bind mounts (путь хоста), tmpfs (память);
всё остальное — недолговечный writable-слой контейнера.

</details>

**2.** Чем volume отличается от bind mount?

<details><summary>Ответ</summary>

Volume лежит в области докера, переносим, с корректными правами, поддерживает драйверы;
bind — конкретный путь хоста, зависит от машины, удобен для конфигов и разработки.

</details>

**3.** Что произойдёт с данными при удалении контейнера?

<details><summary>Ответ</summary>

Всё, что не в volume, удаляется вместе с контейнером.

</details>

**4.** Как сделать бэкап данных контейнера с БД?

<details><summary>Ответ</summary>

Логический дамп родными средствами (`pg_dump`, `mysqldump`) через `docker exec`,
либо остановка БД и tar-копия тома, либо снапшот; обязательна регулярная проверка
восстановления.

</details>

**5.** Что такое анонимные тома и чем они плохи?

<details><summary>Ответ</summary>

Тома без имени, создаются при `-v /path` и `VOLUME` в Dockerfile; накапливаются,
непонятно, что внутри, занимают место.

</details>

**6.** Как решить проблему прав при bind mount?

<details><summary>Ответ</summary>

`--user` с нужным UID/GID, `chown` на хосте, named volume вместо bind, согласование UID
при сборке образа, ACL.

</details>

**7.** Что такое stateless-приложение?

<details><summary>Ответ</summary>

Приложение не хранит локальное состояние: любую реплику можно убить и пересоздать.
Нужно для масштабирования и безболезненных деплоев.

</details>

**8.** Можно ли запускать БД в контейнере? Что нужно учесть?

<details><summary>Ответ</summary>

Можно (особенно для dev/небольших нагрузок): нужны named volume, лимиты ресурсов,
бэкапы с проверкой восстановления, корректный graceful shutdown, мониторинг;
в кластере — StatefulSet + PV или managed-БД.

</details>

**9.** Зачем нужен `--read-only`?

<details><summary>Ответ</summary>

Делает корневую ФС контейнера неизменяемой: защита от подмены бинарников и записи
вредоносного кода; изменяемые каталоги подключают явно (tmpfs/volume).

</details>

**10.** Куда складывать пользовательские файлы в контейнеризованном приложении?

<details><summary>Ответ</summary>

В объектное хранилище (S3/MinIO) либо на общий сетевой том — но не в контейнер
и не в локальный том при нескольких репликах.

</details>

---

### 🎯 Чек-лист

- [ ] Данные БД у меня всегда в named volume, и я это проверил пересозданием
- [ ] Различаю поведение volume и bind mount при монтировании поверх содержимого образа
- [ ] Монтирую конфиги с `:ro`
- [ ] Умею чинить `Permission denied` тремя способами
- [ ] Сделал и **восстановил** бэкап тома и логический дамп БД
- [ ] Знаю, чем `down -v` отличается от `down`
- [ ] Не монтирую docker.sock
- [ ] Чищу анонимные тома осознанно, а не `prune` вслепую
- [ ] Понимаю, зачем `--read-only` + `--tmpfs`
