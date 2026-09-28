---
title: "11. Troubleshooting и обслуживание"
description: "Методика диагностики контейнеров: коды выхода, OOM, сеть, ресурсы, пропавшие данные, место на диске"
---

# 11. Troubleshooting и обслуживание

> Роадмап: «Тут самое главное — КАЖДУЮ непонятную вещь разбирать» + «Докер открывает дверь
> в мир экспериментов: поднимать — ломать — тестировать».
> **После темы ты умеешь:** быстро локализовать проблему по методике, а не наугад,
> и держать хост в порядке (диск, логи, кэш).

---

## 🗺️ Схема: методика разбора

```text:no-line-numbers
   ЧТО ИМЕННО НЕ РАБОТАЕТ?
        │
        ├─ Образ НЕ СОБИРАЕТСЯ ───────► §1  (ошибки build)
        ├─ Контейнер НЕ ЗАПУСКАЕТСЯ ──► §2  (exited сразу, коды выхода)
        ├─ Контейнер ПАДАЕТ/РЕСТАРТИТ ► §3  (OOM, сигналы, зависимости)
        ├─ Приложение НЕ ОТВЕЧАЕТ ────► §4  (сеть, порты, 0.0.0.0)
        ├─ ТОРМОЗИТ ──────────────────► §5  (ресурсы, I/O, лимиты)
        ├─ ДАННЫЕ пропали/не видны ───► §6  (тома, монтирования, права)
        └─ МЕСТО на диске кончилось ──► §7  (образы, логи, кэш, тома)

   Универсальный старт (в таком порядке, всегда):
   docker ps -a  →  docker logs  →  docker inspect  →  docker events  →  docker stats
```

---

## §1. Образ не собирается

```bash
docker build --progress=plain --no-cache -t app .    # видеть каждую команду и её вывод
docker build --target builder -t dbg . && docker run --rm -it dbg sh   # зайти в стадию
```

| Ошибка | Причина / решение |
|--------|-------------------|
| `COPY failed: file not found in build context` | Файл вне контекста, исключён `.dockerignore`, неверный путь, регистр |
| `forbidden path outside the build context` | `COPY ../file` — выйти за контекст нельзя; собирай с контекстом выше |
| `E: Unable to locate package` | Stale cache: `update` и `install` в разных `RUN`; пересобрать `--no-cache` |
| `exec /bin/sh: exec format error` | Образ под другую архитектуру; `--platform` / buildx |
| `returned a non-zero code: N` | Смотри вывод команды выше; отладь через `--target` и ручной запуск |
| `no space left on device` | Кэш сборки/образы забили диск → `docker builder prune`, `docker system df` |
| Зависает на `transferring context` | Огромный контекст → `.dockerignore` |

**Приём:** упала инструкция — собери до предыдущей и выполни команду руками:
```bash
docker build --target <стадия> -t dbg .          # или временно закомментируй хвост Dockerfile
docker run --rm -it dbg sh
# и вводишь упавшую команду вручную, смотришь реальную ошибку
```

---

## §2. Контейнер не запускается / сразу Exited

```bash
docker ps -a --filter name=app
docker logs app                       # ⭐ 80% ответов здесь
docker inspect app --format '{{.State.Status}} exit={{.State.ExitCode}} err={{.State.Error}} oom={{.State.OOMKilled}}'
docker events --since 30m --filter container=app
```

| Код / симптом | Причина |
|---------------|---------|
| `Exited (0)` сразу | Главный процесс завершился штатно: команда отработала и вышла (`echo`, скрипт без цикла) — это не ошибка |
| `Exited (1)` | Ошибка приложения — читай логи |
| `Exited (125)` | Ошибка самого докера: неверные флаги, конфликт опций |
| `Exited (126)` | Файл найден, но не исполняется: нет `+x`, CRLF в скрипте, не тот интерпретатор |
| `Exited (127)` | Команды нет: опечатка в `CMD`, бинарника нет в образе (частая ситуация с `scratch`/distroless) |
| `Exited (137)` | SIGKILL: OOM или таймаут `docker stop` |
| `Exited (139)` | SIGSEGV — падение приложения |
| `standard_init_linux.go: exec format error` | Не та архитектура или скрипт без shebang / с CRLF |
| `port is already allocated` | Порт хоста занят |
| `no such file or directory` при старте | Бинарник слинкован с glibc, а база alpine (musl) — классика |

```bash
# Проверка «а что вообще внутри»
docker run --rm -it --entrypoint sh myapp
docker inspect myapp --format '{{.Config.Entrypoint}} {{.Config.Cmd}} {{.Config.WorkingDir}} {{.Config.User}}'
docker run --rm myapp ls -la /app
file ./entrypoint.sh                 # проверить CRLF: "with CRLF line terminators"
```

---

## §3. Контейнер падает или бесконечно перезапускается

```bash
docker ps -a                                      # Restarting (1) 5 seconds ago
docker inspect app --format 'restarts={{.RestartCount}} oom={{.State.OOMKilled}} exit={{.State.ExitCode}}'
docker logs --tail 200 app
sudo dmesg -T | grep -i -E "killed process|oom"   # подтверждение OOM от ядра
docker events --filter event=oom --filter event=die --since 1h

# остановить цикл, чтобы спокойно разобраться
docker update --restart=no app && docker stop app
docker run --rm -it --entrypoint sh <образ>       # руками воспроизвести старт
```

Типовые причины: OOM (мало `--memory` или утечка), отсутствующая зависимость
(БД ещё не готова), ошибка конфигурации/переменных окружения, падение из-за прав,
неверный healthcheck, приложение не переживает SIGTERM.

---

## §4. Приложение не отвечает

```text:no-line-numbers
1. docker ps                           контейнер вообще работает?
2. docker logs                         стартовало приложение?
3. docker exec c ss -tlnp              слушает ли — и НА КАКОМ адресе?
                                       127.0.0.1 внутри = снаружи недоступно ⭐
4. docker port c                       порт реально опубликован?
5. docker exec c curl -s localhost:PORT   отвечает изнутри?
6. curl 127.0.0.1:HOSTPORT             отвечает с хоста?
7. docker run --rm --network NET nicolaka/netshoot curl http://svc:PORT   из сети?
8. docker exec c getent hosts other    DNS резолвится?
9. sudo iptables -t nat -L DOCKER -n   правила публикации на месте?
```

| Симптом | Обычно это |
|---------|-----------|
| Изнутри работает, снаружи нет | Слушает `127.0.0.1` вместо `0.0.0.0`, или порт не опубликован |
| `connection refused` к соседнему сервису | В конфиге `localhost` вместо имени сервиса; разные сети |
| `bad address` / `Name or service not known` | Контейнеры в дефолтной bridge (нет DNS) или в разных сетях |
| Работает по IP, не работает по имени | Дефолтная сеть вместо пользовательской |
| Периодические таймауты после простоя | conntrack/keepalive (см. тему 08) |
| 502 от nginx | Бэкенд не поднялся/неверный upstream/не в той сети |

---

## §5. Тормозит

```bash
docker stats                                   # CPU%, MEM USAGE/LIMIT, BLOCK I/O, NET I/O
docker top app
docker exec app sh -c 'cat /sys/fs/cgroup/memory.max; cat /sys/fs/cgroup/cpu.max'
docker inspect app --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}'

# Хост
htop; iostat -x 2; vmstat 1
df -h; sudo du -sh /var/lib/docker/*
```

| Что видно | Диагноз |
|-----------|---------|
| `MEM USAGE` вплотную к `LIMIT` | Мало памяти → своп/OOM; увеличить лимит или искать утечку |
| CPU% упирается в `--cpus` | Троттлинг по квоте cgroups |
| Большой BLOCK I/O | Запись в writable-слой (CoW) вместо тома; логи; неоптимальные запросы |
| Приложение видит ресурсы хоста | `free`/`nproc` не cgroup-aware → JVM/Node строят пулы по хосту (тема 01, D4) |
| Медленные bind mount на Mac | Виртуализация ФС — использовать named volume |

---

## §6. Данные пропали / не видно файлов

```bash
docker inspect app --format '{{json .Mounts}}' | jq .     # что и куда смонтировано
docker volume ls; docker volume inspect <vol>
docker exec app ls -la /path
docker diff app                                           # что писалось в writable-слой
```

Частые причины: данные писались **не в том** каталоге (том смонтирован в другой путь);
контейнер пересоздан без тома; `docker compose down -v`; переименован каталог проекта
(сменилось имя проекта → другие тома); bind mount перекрыл содержимое образа;
права/UID не дают увидеть или записать.

---

## §7. Место на диске (самый частый инцидент)

```bash
docker system df            # сводка
docker system df -v         # детально: какой образ/том/кэш сколько
df -h /var/lib/docker
sudo du -sh /var/lib/docker/* | sort -h
sudo du -sh /var/lib/docker/containers/*/*.log | sort -h | tail   # логи
sudo du -sh /var/lib/docker/volumes/* | sort -h | tail            # тома
```

```bash
# Безопасная последовательность очистки
docker container prune                     # остановленные контейнеры
docker image prune                         # только dangling
docker builder prune --filter until=168h   # кэш сборок старше недели
docker image prune -a --filter until=336h  # образы, не используемые 2 недели
docker network prune

# ⚠️ ОСТОРОЖНО — данные:
docker volume ls -f dangling=true          # СНАЧАЛА посмотреть глазами
docker run --rm -v <vol>:/x alpine du -sh /x   # что внутри
docker volume rm <конкретный том>          # только явно, не prune вслепую

# ☠️ снести вообще всё неиспользуемое, включая тома
docker system prune -a --volumes           # НИКОГДА на проде «на автомате»
```

**Профилактика:**
```json
// /etc/docker/daemon.json
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
```
+ отдельный раздел под `/var/lib/docker`, мониторинг места, регулярный `builder prune` по cron,
retention в registry.

> Логи работающего контейнера нельзя удалять через `rm` (файл открыт демоном) —
> используй `truncate -s 0 <logfile>` либо пересоздай контейнер.

---

## 🧰 Инструменты

```bash
docker events --since 1h                         # что происходило
docker run --rm --network container:app nicolaka/netshoot   # сетевой тулкит
sudo nsenter -t $(docker inspect -f '{{.State.Pid}}' app) -a sh   # внутрь без shell в образе
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  -v /:/rootfs:ro --pid host --privileged justincormack/nsenter1  # доступ к VM (Docker Desktop)
ctop                                             # top для контейнеров
dive myimage:1.0                                 # послойный анализ образа
docker-bench-security                            # аудит по CIS
lazydocker                                       # TUI для докера
```

---

## 🧪 Мини-лаба: сломай и почини

```bash
mkdir -p ~/docker-lab/11 && cd ~/docker-lab/11

# --- Поломка 1: команда не найдена (127)
docker run --name b1 alpine nosuchbinary 2>/dev/null
docker inspect b1 --format 'exit={{.State.ExitCode}}'; docker logs b1; docker rm b1

# --- Поломка 2: скрипт без прав / с CRLF (126)
printf '#!/bin/sh\r\necho hi\r\n' > crlf.sh && chmod +x crlf.sh
printf 'FROM alpine:3.20\nCOPY crlf.sh /crlf.sh\nCMD ["/crlf.sh"]\n' > Dockerfile.crlf
docker build -q -f Dockerfile.crlf -t br:crlf .
docker run --name b2 br:crlf 2>&1 | head -2
docker inspect b2 --format 'exit={{.State.ExitCode}}'; docker rm b2
# Починка:
sed -i 's/\r$//' crlf.sh && docker build -q -f Dockerfile.crlf -t br:crlf . && docker run --rm br:crlf

# --- Поломка 3: OOM (137)
docker run --name b3 --memory=30m python:3-alpine python -c "b=bytearray(200*1024*1024)" 2>/dev/null
docker inspect b3 --format 'exit={{.State.ExitCode}} oom={{.State.OOMKilled}}'
sudo dmesg -T | grep -i "killed process" | tail -1; docker rm b3

# --- Поломка 4: слушает 127.0.0.1
docker run -d --name b4 -p 8080:8000 python:3.12-alpine python -m http.server 8000 --bind 127.0.0.1
sleep 2
curl -s --max-time 3 localhost:8080 || echo "снаружи недоступно"
docker exec b4 wget -qO- http://127.0.0.1:8000 >/dev/null && echo "изнутри работает → диагноз: не тот bind"
docker rm -f b4

# --- Поломка 5: нет DNS в дефолтной сети
docker run -d --name db5 alpine sleep 600
docker run --rm alpine ping -c1 -W1 db5 2>&1 | head -1
docker network create fix5 && docker rm -f db5
docker run -d --name db5 --network fix5 alpine sleep 600
docker run --rm --network fix5 alpine ping -c1 db5 | head -1      # ✅
docker rm -f db5; docker network rm fix5

# --- Поломка 6: бесконечный рестарт
docker run -d --name b6 --restart always alpine sh -c 'sleep 2; exit 3'
sleep 12
docker ps -a --filter name=b6
docker inspect b6 --format 'restarts={{.RestartCount}} exit={{.State.ExitCode}}'
docker update --restart=no b6 && docker stop b6 && docker rm -f b6

# --- Поломка 7: диск съели логи
docker run -d --name b7 alpine sh -c 'while :; do head -c 50000 /dev/urandom | base64; done'
sleep 8
LOG=$(docker inspect b7 --format '{{.LogPath}}'); sudo ls -lh $LOG
sudo truncate -s 0 $LOG && sudo ls -lh $LOG        # правильный способ (не rm!)
docker rm -f b7

# --- Поломка 8: нет shell в образе
docker run -d --name b8 gcr.io/distroless/static-debian12 2>/dev/null || \
  docker run -d --name b8 nginx:alpine
docker exec b8 bash 2>&1 | head -1                 # executable file not found
sudo nsenter -t $(docker inspect -f '{{.State.Pid}}' b8) -a sh -c 'ls /' 2>/dev/null | head -3
docker run --rm --network container:b8 nicolaka/netshoot ss -tlnp | head -3
docker rm -f b8

# --- Уборка места
docker system df
docker container prune -f; docker image prune -f; docker builder prune -f
docker system df
cd ~ && rm -rf ~/docker-lab/11
```

---

## 📌 Шпаргалка диагностики

| Вопрос | Команда |
|--------|---------|
| Что вообще запущено/упало | `docker ps -a` |
| Почему упало | `docker logs --tail 200 c` |
| Код выхода, OOM, ошибка | <code v-pre>docker inspect c --format '{{.State.ExitCode}} {{.State.OOMKilled}} {{.State.Error}}'</code> |
| Что происходило | `docker events --since 1h --filter container=c` |
| Что ест ресурсы | `docker stats`, `docker top c` |
| Что слушает приложение | `docker exec c ss -tlnp` |
| Куда проброшены порты | `docker port c` |
| Сети и IP | <code v-pre>docker inspect c --format '{{json .NetworkSettings.Networks}}'</code> |
| Монтирования | <code v-pre>docker inspect c --format '{{json .Mounts}}'</code> |
| Что писалось внутрь | `docker diff c` |
| Правила публикации | `sudo iptables -t nat -L DOCKER -n` |
| OOM в ядре | `sudo dmesg -T \| grep -i "killed process"` |
| Место | `docker system df -v`, `du -sh /var/lib/docker/*` |
| Внутрь без shell | <code v-pre>sudo nsenter -t $(docker inspect -f '{{.State.Pid}}' c) -a sh</code> |
| Сетевой тулкит | `docker run --rm --network container:c nicolaka/netshoot` |
| Отладка сборки | `docker build --progress=plain --no-cache`, `--target` |

---

## 🧠 Что запомнить

1. Порядок всегда один: **`ps -a` → `logs` → `inspect` → `events` → `stats`**.
2. Код выхода — половина диагноза: 0 (штатно), 1, 125 (докер), 126 (не исполняется),
   127 (нет команды), 137 (SIGKILL/OOM), 139 (SIGSEGV), 143 (SIGTERM).
3. `Exited (0)` сразу после старта — это **нормальное поведение**, а не ошибка:
   процесс отработал и вышел.
4. «Изнутри работает, снаружи нет» = слушает `127.0.0.1` или порт не опубликован.
5. «bad address» между контейнерами = дефолтная сеть или разные сети.
6. Бесконечный рестарт: сними политику (`docker update --restart=no`), чтобы спокойно разобраться.
7. Ошибка сборки — воспроизводи руками в контейнере предыдущей стадии (`--target` + `sh`).
8. Нет shell в образе — `nsenter` с хоста или netshoot в его namespace.
9. Место на диске: `docker system df -v` → prune **по частям**, тома — только осознанно.
10. Логи работающего контейнера чистить `truncate -s 0`, а не `rm`.
11. Ротация логов в `daemon.json` и мониторинг `/var/lib/docker` — обязательная профилактика.
12. Не чини контейнер изнутри: исправь Dockerfile/compose и пересоздай.

---

## Задачи

> Формат этой темы особый: **сначала ломаешь сам, потом чинишь**. Это и есть
> «поднимать — ломать — тестировать» из роадмапа.

---

### Блок A. Теория

**A1.** Назови универсальный порядок диагностики любой проблемы с контейнером.

<details><summary>Ответ</summary>

`docker ps -a` (в каком состоянии и код выхода) → `docker logs` (что сказало приложение)
→ `docker inspect` (конфигурация, OOM, сети, монтирования) → `docker events` (что происходило)
→ `docker stats`/`top` (ресурсы). Дальше — по симптому: сеть, диск, права.

</details>

**A2.** Что означают коды выхода 0, 1, 125, 126, 127, 137, 139, 143?

<details><summary>Ответ</summary>

0 — штатно; 1 — ошибка приложения; 125 — ошибка докера (флаги/опции);
126 — команда найдена, но не исполняется (нет `+x`, CRLF, не тот формат);
127 — команды нет; 137 — SIGKILL (OOM или таймаут stop); 139 — SIGSEGV;
143 — SIGTERM без обработчика.

</details>

**A3.** Контейнер сразу `Exited (0)`. Это ошибка? Как понять причину?

<details><summary>Ответ</summary>

Нет, это нормальное поведение: главный процесс завершился штатно (команда выполнилась
и вышла, скрипт без бесконечного цикла, отсутствует «фоновый» сервис — демон ушёл в фон
и PID 1 завершился). Смотреть `docker logs` и <code v-pre>docker inspect --format '{{.Config.Cmd}}'</code>;
если приложение демонизируется — запускать его в форграунде (`nginx -g "daemon off;"`).

</details>

**A4.** Как отличить «приложение не слушает» от «порт не опубликован» от «файрвол»?

<details><summary>Ответ</summary>

`docker exec c ss -tlnp` — слушает ли и на каком адресе (`0.0.0.0` vs `127.0.0.1`);
`docker port c` / `docker ps` — опубликован ли порт; `curl` с самого хоста на
`127.0.0.1:<порт>` — если работает локально, но не снаружи, дело в файрволе/security group
(проверить `iptables`, `ufw status`, облачные правила).

</details>

**A5.** Как остановить бесконечный цикл перезапусков, не удаляя контейнер?

<details><summary>Ответ</summary>

`docker update --restart=no <c>` затем `docker stop <c>`. После этого можно спокойно
изучать логи и запускать образ вручную с переопределённым entrypoint.

</details>

**A6.** Как отладить упавшую инструкцию `RUN` в Dockerfile?

<details><summary>Ответ</summary>

`docker build --progress=plain --no-cache` покажет полный вывод; затем собрать
до предыдущей стадии/инструкции (`--target`, или временно обрезать Dockerfile), запустить
`docker run --rm -it <образ> sh` и выполнить упавшую команду вручную, наблюдая реальную ошибку.

</details>

**A7.** Как попасть внутрь контейнера, если в образе нет shell?

<details><summary>Ответ</summary>

`nsenter` с хоста в namespaces процесса контейнера
(<code v-pre>sudo nsenter -t $(docker inspect -f '{{.State.Pid}}' c) -a sh</code>), либо запустить тулкит
в его namespace (`docker run --rm --network container:c nicolaka/netshoot`), либо
`docker cp` для файлов, `docker inspect`/`docker top` для метаданных и процессов;
в Docker Desktop — `docker debug`, в Kubernetes — ephemeral containers.

</details>

**A8.** Как понять, что контейнер убил OOM-killer? Три независимых подтверждения.

<details><summary>Ответ</summary>

(1) Код выхода 137; (2) <code v-pre>docker inspect --format '{{.State.OOMKilled}}'</code> → `true`;
(3) `sudo dmesg -T | grep -i "killed process"` или `journalctl -k | grep -i oom` —
сообщение ядра с именем процесса и cgroup. Дополнительно — событие `oom` в `docker events`.

</details>

**A9.** Из чего складывается занятое место в `/var/lib/docker`?

<details><summary>Ответ</summary>

Образы (`overlay2`), writable-слои контейнеров, тома, build cache, логи контейнеров
(`containers/<id>/<id>-json.log`), временные файлы и содержимое `tmp`. Разложить:
`docker system df -v` и `sudo du -sh /var/lib/docker/*`.

</details>

**A10.** Почему логи работающего контейнера нельзя удалять через `rm`?

<details><summary>Ответ</summary>

Файл открыт демоном: после `rm` место не освобождается, пока дескриптор жив,
а докер продолжит писать в удалённый inode. Правильно — `truncate -s 0 <logfile>`
или пересоздать контейнер; системно — включить ротацию.

</details>

**A11.** Чем `docker system prune -a --volumes` опасен на проде?

<details><summary>Ответ</summary>

Он удаляет **все** неиспользуемые образы, сети, кэш и, с `--volumes`, тома —
включая тома остановленных на момент запуска сервисов (например, БД, которую как раз
перезапускали). Восстановление возможно только из бэкапа.

</details>

**A12.** Что покажет `docker diff` и как это помогает в диагностике?

<details><summary>Ответ</summary>

Разницу файловой системы контейнера с образом (`A`/`C`/`D`). Помогает понять,
что приложение пишет внутрь контейнера (и должно бы писать в том), найти неожиданные
изменения конфигов, обнаружить подозрительные файлы.

</details>

**A13.** Зачем нужен `docker events` и когда он незаменим?

<details><summary>Ответ</summary>

Поток событий демона (start/die/oom/health_status/destroy и др.). Незаменим,
когда контейнер уже удалён или пересоздан, и логов не осталось: по событиям видно,
когда и почему он умирал, кто его останавливал, срабатывал ли healthcheck.

</details>

**A14.** Приложение внутри контейнера видит 64 ГБ памяти хоста при лимите 512 МБ.
Почему и чем это грозит?

<details><summary>Ответ</summary>

`free`, `/proc/meminfo`, `nproc` читаются из procfs хоста — namespaces их не
подменяют. Приложение (JVM, Node, Go-пулы, nginx `worker_processes auto`) строит
расчёты по ресурсам хоста и выходит за cgroup-лимит → OOM. Лечение: cgroup-aware
рантаймы и явные настройки (`-XX:MaxRAMPercentage`), lxcfs, передача лимитов
переменными окружения.

</details>

**A15.** Что такое `exec format error` и три его причины?

<details><summary>Ответ</summary>

(1) Образ собран под другую архитектуру (arm64 на amd64 и наоборот);
(2) скрипт без shebang или с CRLF-переводами строк; (3) бинарник несовместим с libc базы
(glibc-бинарник в alpine/musl) или это вообще не исполняемый формат.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  docker inspect app --format '{{.State.ExitCode}} {{.State.OOMKilled}} {{.State.Error}}'
B2.  docker events --since 1h --filter container=app
B3.  docker update --restart=no app
B4.  docker build --progress=plain --no-cache -t app .
B5.  docker build --target builder -t dbg . && docker run --rm -it dbg sh
B6.  docker run --rm -it --entrypoint sh myapp
B7.  sudo nsenter -t $(docker inspect -f '{{.State.Pid}}' app) -a sh
B8.  docker run --rm --network container:app nicolaka/netshoot ss -tlnp
B9.  sudo dmesg -T | grep -i "killed process"
B10. docker system df -v
B11. sudo truncate -s 0 $(docker inspect app --format '{{.LogPath}}')
B12. docker builder prune --filter until=168h -f
B13. docker diff app
B14. docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}'
B15. docker exec app cat /sys/fs/cgroup/memory.max
```

<details><summary>Ответ</summary>

**B1.** Код выхода, признак OOM и текст ошибки запуска — минимальный набор для диагноза.
**B2.** Все события, связанные с контейнером, за последний час.
**B3.** Снять политику перезапуска, чтобы прервать цикл рестартов.
**B4.** Полная пересборка с подробным выводом каждой команды.
**B5.** Собрать промежуточную стадию и зайти в неё для ручной отладки.
**B6.** Запустить образ с shell вместо его entrypoint — посмотреть, что внутри.
**B7.** Войти во все namespaces контейнера с хоста (работает без shell в образе).
**B8.** Посмотреть открытые сокеты в сетевом namespace контейнера сторонним тулкитом.
**B9.** Найти в журнале ядра подтверждение убийства процесса OOM-killer'ом.
**B10.** Детальная раскладка занятого докером места.
**B11.** Обнулить файл логов работающего контейнера, освободив место.
**B12.** Удалить кэш сборок старше недели.
**B13.** Показать изменения ФС контейнера относительно образа.
**B14.** Компактная сводка потребления памяти и CPU по контейнерам.
**B15.** Реальный лимит памяти из cgroup (в отличие от `free`).

</details>

**B16.** Почему `docker logs` может быть пустым, даже если приложение точно что-то печатает?
Три причины.

<details><summary>Ответ</summary>

(1) Приложение пишет в файл внутри контейнера, а не в stdout/stderr;
(2) вывод буферизуется (нет `PYTHONUNBUFFERED`/`-u`, буферизация при отсутствии tty);
(3) используется несовместимый log-driver (например, `journald`/`fluentd` — тогда
`docker logs` может не работать), либо логи уже ротированы/усечены.

</details>

---

### Блок C. Практика — «сломай и почини»

> Для каждого пункта: **1)** воспроизведи поломку, **2)** зафиксируй симптом (какая команда что
> показала), **3)** поставь диагноз, **4)** почини, **5)** запиши, как избежать в будущем.

#### C1. 🔑 Полигон из 10 поломок (главное задание)

1. `Exited (127)` — команды нет в образе.
2. `Exited (126)` — скрипт с CRLF или без `+x`.
3. `Exited (137)` — OOM при `--memory=30m`.
4. `docker stop` длится 10 секунд и даёт 137 — shell-форма CMD.
5. Приложение слушает `127.0.0.1` — снаружи недоступно.
6. Два контейнера в дефолтной сети не видят друг друга по имени.
7. Бесконечный рестарт с `--restart always`.
8. Логи контейнера съели место — почини без удаления контейнера.
9. Данные пропали после пересоздания контейнера (не было тома).
10. `port is already allocated`.

<details><summary>Ответ</summary>

```bash
mkdir -p ~/docker-lab/11c1 && cd ~/docker-lab/11c1

# 1) 127
docker run --name p1 alpine nosuchbinary 2>/dev/null
docker inspect p1 --format '1) exit={{.State.ExitCode}}'; docker rm p1 >/dev/null
# фикс: проверить наличие бинарника: docker run --rm <img> which <cmd>

# 2) 126
printf '#!/bin/sh\r\necho hi\r\n' > s.sh; chmod +x s.sh
printf 'FROM alpine:3.20\nCOPY s.sh /s.sh\nCMD ["/s.sh"]\n' > D2
docker build -q -f D2 -t p:2 . >/dev/null
docker run --name p2 p:2 2>&1 | head -1; docker inspect p2 --format '2) exit={{.State.ExitCode}}'
docker rm p2 >/dev/null; sed -i 's/\r$//' s.sh; docker build -q -f D2 -t p:2 . >/dev/null
docker run --rm p:2                 # фикс: убрать CRLF (.gitattributes / dos2unix)

# 3) 137 OOM
docker run --name p3 --memory=30m python:3-alpine python -c "b=bytearray(200*1024*1024)" 2>/dev/null
docker inspect p3 --format '3) exit={{.State.ExitCode}} oom={{.State.OOMKilled}}'; docker rm p3 >/dev/null
# фикс: поднять лимит / починить утечку / настроить рантайм под лимит

# 4) медленный stop
docker run -d --name p4 alpine sh -c 'trap "" TERM; sleep 300' >/dev/null
time docker stop p4; docker inspect p4 --format '4) exit={{.State.ExitCode}}'; docker rm p4 >/dev/null
# фикс: exec-форма, обработчик SIGTERM, --init

# 5) bind 127.0.0.1
docker run -d --name p5 -p 8080:8000 python:3.12-alpine python -m http.server 8000 --bind 127.0.0.1 >/dev/null
sleep 2; curl -s --max-time 2 localhost:8080 >/dev/null || echo "5) снаружи недоступно"
docker exec p5 wget -qO- http://127.0.0.1:8000 >/dev/null && echo "   изнутри работает → bind"
docker rm -f p5 >/dev/null      # фикс: --bind 0.0.0.0

# 6) DNS
docker run -d --name p6a alpine sleep 300 >/dev/null
docker run --rm alpine ping -c1 -W1 p6a 2>&1 | head -1
docker rm -f p6a >/dev/null      # фикс: своя сеть (docker network create)

# 7) рестарт-цикл
docker run -d --name p7 --restart always alpine sh -c 'sleep 2; exit 3' >/dev/null
sleep 10; docker inspect p7 --format '7) restarts={{.RestartCount}}'
docker update --restart=no p7 >/dev/null && docker rm -f p7 >/dev/null

# 8) логи съели место
docker run -d --name p8 alpine sh -c 'while :; do head -c 50000 /dev/urandom|base64; done' >/dev/null
sleep 6; L=$(docker inspect p8 --format '{{.LogPath}}'); sudo ls -lh $L | awk '{print "8) до:",$5}'
sudo truncate -s 0 $L; sudo ls -lh $L | awk '{print "   после:",$5}'
docker rm -f p8 >/dev/null       # фикс: log-opts в daemon.json

# 9) потеря данных
docker run -d --name p9 -e POSTGRES_PASSWORD=pw postgres:16-alpine >/dev/null; sleep 8
docker exec p9 psql -U postgres -c "CREATE TABLE t(x int);" >/dev/null
docker rm -f p9 >/dev/null
docker run -d --name p9 -e POSTGRES_PASSWORD=pw postgres:16-alpine >/dev/null; sleep 8
docker exec p9 psql -U postgres -c "SELECT * FROM t;" 2>&1 | head -1   # 9) таблицы нет
docker rm -f p9 >/dev/null       # фикс: -v pgdata:/var/lib/postgresql/data

# 10) занятый порт
docker run -d --name pA -p 8080:80 nginx:alpine >/dev/null
docker run -d --name pB -p 8080:80 nginx:alpine 2>&1 | tail -1        # port is already allocated
docker rm -f pA pB >/dev/null
# фикс: другой порт/адрес, ss -tlnp | grep 8080 чтобы найти занявшего
cd ~ && rm -rf ~/docker-lab/11c1
```

</details>

#### C2. Отладка сборки

1. Напиши Dockerfile, который падает на третьей инструкции.
2. Найди ошибку через `--progress=plain`.
3. Собери образ до предыдущей стадии и выполни упавшую команду руками.
4. Воспроизведи `COPY failed: file not found` тремя разными способами
   (нет файла, `.dockerignore`, путь вне контекста) и различи их по сообщению.

<details><summary>Ответ</summary>

```bash
printf 'FROM alpine:3.20\nRUN echo step1\nRUN echo step2\nRUN exit 7\nRUN echo never\n' > Dbad
docker build --progress=plain --no-cache -f Dbad -t bad . 2>&1 | tail -5
printf 'FROM alpine:3.20\nRUN echo step1\nRUN echo step2\n' > Dpart
docker build -q -f Dpart -t part . && docker run --rm -it part sh -c 'exit 7'; echo "код: $?"
# COPY failed, три варианта:
printf 'FROM alpine\nCOPY nofile /x\n' > Dc1;  docker build -f Dc1 . 2>&1 | tail -1
printf 'FROM alpine\nCOPY s.sh /x\n'  > Dc2; echo "s.sh" > .dockerignore
docker build -f Dc2 . 2>&1 | tail -1; rm -f .dockerignore
printf 'FROM alpine\nCOPY ../outside /x\n' > Dc3; docker build -f Dc3 . 2>&1 | tail -1
```

</details>

#### C3. Сеть: полная цепочка проверок

Собери неработающую связку «nginx → app» (специально с ошибкой: разные сети, или
`proxy_pass http://localhost:8000`, или app слушает 127.0.0.1) и пройди все 9 шагов
методики из конспекта, записывая результат каждого. Найди, на каком шаге ломается.

<details><summary>Ответ</summary>

```bash
docker network create n-front >/dev/null; docker network create n-back >/dev/null
docker run -d --name svc --network n-back python:3.12-alpine \
  sh -c 'echo ok > index.html; python -m http.server 8000 --bind 0.0.0.0' >/dev/null
printf 'server { listen 80; location / { proxy_pass http://svc:8000; } }\n' > px.conf
docker run -d --name prx --network n-front -p 8080:80 -v "$PWD/px.conf:/etc/nginx/conf.d/default.conf:ro" nginx:alpine >/dev/null
sleep 2
curl -s -o /dev/null -w "1) код с хоста: %{http_code}\n" localhost:8080       # 502
docker logs prx 2>&1 | tail -1                                               # host not found
docker exec prx getent hosts svc || echo "2) DNS не резолвится → разные сети"
docker network connect n-back prx && docker exec prx nginx -s reload; sleep 1
curl -s -o /dev/null -w "3) после фикса: %{http_code}\n" localhost:8080       # 200
docker rm -f prx svc >/dev/null; docker network rm n-front n-back >/dev/null
```

</details>

#### C4. Ресурсы

1. Запусти контейнер с лимитом памяти 128 МБ и нагрузи его до 120 МБ —
   покажи `docker stats` и cgroup-лимит изнутри.
2. Ограничь CPU до 0.25 и покажи троттлинг.
3. Покажи, что `free -m` внутри контейнера врёт, и найди правильный источник лимита.
4. Найди контейнер, который больше всех пишет на диск (`BLOCK I/O`), и объясни,
   как это связано с CoW.

<details><summary>Ответ</summary>

```bash
docker run -d --name r1 --memory=128m alpine sh -c 'tail -f /dev/null' >/dev/null
docker exec r1 cat /sys/fs/cgroup/memory.max 2>/dev/null || docker exec r1 cat /sys/fs/cgroup/memory/memory.limit_in_bytes
docker exec r1 free -m | head -2        # врёт: показывает память ХОСТА
docker stats --no-stream r1
docker rm -f r1 >/dev/null
docker run -d --name r2 --cpus=0.25 alpine sh -c 'while :; do :; done' >/dev/null
docker stats --no-stream r2; docker rm -f r2 >/dev/null
docker stats --no-stream --format 'table {{.Name}}\t{{.BlockIO}}'
```

</details>

#### C5. Диск

1. Доведи `docker system df` до заметных цифр (насобирай образов, контейнеров, кэша).
2. Составь таблицу: что занимает место и сколько.
3. Освободи место **по шагам**, показывая эффект каждой команды.
4. Найди осиротевшие тома и проверь, что внутри, **прежде** чем удалять.
5. Настрой ротацию логов глобально и проверь, что новые контейнеры её получают.

<details><summary>Ответ</summary>

```bash
docker system df
docker system df -v | head -25
docker container prune -f; docker system df | head -3
docker image prune -f;     docker system df | head -3
docker builder prune -f;   docker system df | head -3
for v in $(docker volume ls -qf dangling=true); do
  echo "== $v"; docker run --rm -v "$v":/x alpine du -sh /x 2>/dev/null
done
sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
EOF
sudo systemctl restart docker
docker run -d --name lg alpine sleep 30 >/dev/null
docker inspect lg --format '{{json .HostConfig.LogConfig}}'; docker rm -f lg >/dev/null
```

</details>

#### C6. Контейнер без shell

Возьми distroless-образ (или nginx без bash) и:
1. Покажи, что `docker exec sh` не работает.
2. Посмотри процессы, сеть и файлы внутри через `nsenter` и netshoot.
3. Вытащи файл из контейнера через `docker cp`.
4. Посмотри переменные окружения и команду запуска через `inspect`.

<details><summary>Ответ</summary>

```bash
docker run -d --name ns nginx:alpine >/dev/null
docker exec ns bash 2>&1 | head -1
PID=$(docker inspect -f '{{.State.Pid}}' ns)
sudo nsenter -t $PID -a sh -c 'ps aux | head -3' 2>/dev/null || sudo nsenter -t $PID -m -p -u -n sh -c 'ls /'
docker run --rm --network container:ns nicolaka/netshoot ss -tlnp | head -3
docker cp ns:/etc/nginx/nginx.conf ./nginx.conf && head -2 nginx.conf
docker inspect ns --format '{{json .Config.Env}} {{.Config.Cmd}}'
docker rm -f ns >/dev/null
```

</details>

#### C7. Инцидент «сайт лежит»

Смоделируй и разбери за 5 минут: подними nginx + app, затем «сломай» одним из способов
(останови app, поменяй сеть, закончи память, сломай конфиг nginx) — **попроси коллегу/
себя-через-час** не знать, что именно сломано, и пройди методику до нахождения причины.
Зафиксируй время.

---

### Блок D. Инциденты (без подсказок — ставь диагноз)

**D1.** `docker compose up -d` отработал, но `docker compose ps` показывает `app` как `Exit 1`,
в логах — `psycopg2.OperationalError: could not connect to server`. БД в `running`. Диагноз?

<details><summary>Ответ</summary>

Контейнер БД в `running`, но ещё **не готов** принимать соединения (инициализация
кластера занимает секунды). `depends_on` без `condition: service_healthy` не ждёт готовности.
Починка: healthcheck (`pg_isready`) + `condition: service_healthy` и retry-логика
в приложении. Проверить также имя хоста (`db`, а не `localhost`), пароль/пользователя,
сеть.

</details>

**D2.** Сервер не отвечает по SSH, в мониторинге — 100% CPU. После перезагрузки видно,
что один контейнер породил тысячи процессов. Что произошло и что настроить?

<details><summary>Ответ</summary>

Fork-бомба или неконтролируемое порождение процессов в контейнере без `--pids-limit`:
исчерпание PID и CPU на хосте. Настроить: `--pids-limit` (или `pids_limit` в compose)
и лимиты CPU/памяти для всех контейнеров, мониторинг числа процессов, `ulimit`,
не запускать непроверенный код без ограничений.

</details>

**D3.** После обновления образа приложение выдаёт 502 через nginx. `docker ps` — оба Up.
Порядок проверки?

<details><summary>Ответ</summary>

`docker logs app` (стартовало ли приложение, нет ли ошибок миграции),
`docker exec app ss -tlnp` (слушает ли и на каком порту/адресе — возможно, поменялся порт
в новом образе), `docker logs nginx` (что именно пишет: connection refused / host not found),
проверка сети (`getent hosts app` из nginx), сверка `proxy_pass` с реальным портом,
healthcheck. Часто причина — новый образ слушает другой порт или требует переменную,
которой нет.

</details>

**D4.** CI-раннер падает: `no space left on device`, при этом `df -h /` показывает 40% занято.
Где искать?

<details><summary>Ответ</summary>

Место занято не в `/`, а в другом разделе или исчерпаны **inode**:
`df -h /var/lib/docker` (может быть отдельный диск), `df -i` (inodes),
плюс переполнение `/var/lib/docker` при монтировании его на отдельный том.
Дальше — `docker system df -v`, логи контейнеров, build cache.

</details>

**D5.** Контейнер работает, но `docker logs` пуст, а приложение точно пишет логи. Три причины.

<details><summary>Ответ</summary>

См. B16: пишет в файл, а не в stdout; буферизация вывода; несовместимый log-driver
или уже отротированные/усечённые логи. Дополнительно: смотрят логи не того контейнера
(пересоздан — новый ID) или процесс пишет в stderr дочернего процесса, который не подключён
к stdout PID 1.

</details>

**D6.** На хосте 30 контейнеров, один из них периодически «съедает» весь I/O,
и тормозит вся система. Как найти виновника и что сделать?

<details><summary>Ответ</summary>

<code v-pre>docker stats --format 'table {{.Name}}\t{{.BlockIO}}'</code> и `iotop`/`pidstat -d` на хосте,
сопоставление PID с контейнером через `/proc/<pid>/cgroup`. Причины: запись в writable-слой
(CoW), логи, БД без тома, отсутствие индексов. Меры: вынести данные в том, ограничить
`--blkio-weight`/`--device-write-bps`, включить ротацию логов, отделить нагруженные сервисы.

</details>

**D7.** `docker exec` в контейнер отвечает мгновенно, а само приложение не отвечает
ни на один HTTP-запрос. `docker stats` показывает 0% CPU. Что это может быть и как проверить?

<details><summary>Ответ</summary>

Приложение зависло (deadlock, исчерпан пул потоков/соединений, ждёт внешний сервис,
GC-пауза) — процесс жив, поэтому `exec` работает, но CPU не потребляется, так как все
потоки блокированы. Проверить: `docker exec c ss -tan | head` (накопились ли соединения),
дамп потоков (`jstack`, `py-spy dump`, `kill -QUIT`), логи, зависимости (БД, внешние API),
healthcheck. Это ровно та ситуация, для которой нужен liveness-probe/healthcheck.

</details>

**D8.** После `docker system prune -a` на dev-сервере перестали работать все проекты:
образы качаются заново по часу. Что сделали не так и как быть аккуратнее?

<details><summary>Ответ</summary>

`prune -a` удалил все образы, на которые не ссылались запущенные контейнеры,
включая базовые образы и кэш сборок. Аккуратнее: `docker image prune` (только dangling),
фильтры по возрасту (`--filter until=336h`), `docker builder prune --filter until=…`,
локальное зеркало/pull-through cache, чтобы повторное скачивание было быстрым, и
регулярная плановая очистка вместо разовой «под ноль».

</details>

**D9.** Приложение в контейнере периодически падает с 137, но `--memory` не задан,
и на хосте свободно 20 ГБ. Как такое возможно?

<details><summary>Ответ</summary>

Лимит может быть задан не флагом, а в compose (`deploy.resources.limits`) или
унаследован от systemd-слайса; либо процесс убил **хостовой** OOM-killer при общей
нехватке памяти в момент пика (20 ГБ свободно сейчас ≠ было свободно тогда); либо
процесс убит извне (`kill -9`, оркестратор, `docker stop` по таймауту) — тогда
`OOMKilled=false`. Проверить <code v-pre>docker inspect --format '{{.State.OOMKilled}}'</code>,
`dmesg -T | grep -i oom`, историю потребления в мониторинге.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Контейнер не запускается — твои действия?

<details><summary>Ответ</summary>

`docker ps -a` → код выхода → `docker logs` → `docker inspect` → запуск образа вручную
с `--entrypoint sh` → проверка команды, прав, переменных, зависимостей.

</details>

**2.** Как понять, почему контейнер упал?

<details><summary>Ответ</summary>

По коду выхода и логам; `inspect` даёт `ExitCode`, `OOMKilled`, `Error`;
`docker events` — историю, `dmesg` — подтверждение OOM.

</details>

**3.** Что означает 137 и как это проверить?

<details><summary>Ответ</summary>

128+9 (SIGKILL): чаще всего OOM. Проверка: <code v-pre>docker inspect --format '{{.State.OOMKilled}}'</code>
и `dmesg -T | grep -i "killed process"`.

</details>

**4.** Приложение в контейнере недоступно снаружи — что проверишь?

<details><summary>Ответ</summary>

Слушает ли приложение и на каком адресе (`ss -tlnp` внутри), опубликован ли порт
(`docker port`), работает ли изнутри (`curl localhost` в контейнере), сеть и DNS,
файрвол/iptables.

</details>

**5.** Как отладить сборку образа?

<details><summary>Ответ</summary>

`--progress=plain --no-cache`, сборка до стадии (`--target`) и ручной запуск упавшей
команды в контейнере, проверка контекста и `.dockerignore`.

</details>

**6.** Как попасть в контейнер без shell?

<details><summary>Ответ</summary>

`nsenter` с хоста, netshoot в его namespace, `docker cp`, `docker inspect`/`top`;
в k8s — ephemeral containers.

</details>

**7.** На сервере кончилось место из-за докера — что делать?

<details><summary>Ответ</summary>

`docker system df -v` → поэтапный prune (контейнеры → dangling-образы → build cache →
старые образы), логи (`truncate`), тома — только после осмотра; затем включить
ротацию логов и регулярную очистку.

</details>

**8.** Как диагностировать сетевую проблему между контейнерами?

<details><summary>Ответ</summary>

Проверить, в одной ли сети контейнеры, резолвится ли имя (`getent hosts`),
слушает ли целевой сервис, попробовать из третьего контейнера в той же сети (netshoot),
посмотреть `iptables -t nat -L DOCKER`.

</details>

**9.** Что такое `docker events` и зачем он?

<details><summary>Ответ</summary>

Поток событий демона; нужен, когда контейнер уже пересоздан или удалён и надо
восстановить хронологию (когда умер, был ли OOM, кто остановил).

</details>

**10.** Как ты обычно чинишь проблему в контейнере на проде?

<details><summary>Ответ</summary>

Не чиню внутри контейнера: локализую причину, исправляю Dockerfile/compose/конфиг,
выкатываю новый образ и пересоздаю контейнер; временные обходы фиксирую в задаче,
чтобы они не остались «навсегда».

</details>

---

### 🎯 Чек-лист

- [ ] Диагностирую по методике, а не наугад
- [ ] Читаю коды выхода и понимаю, что делать дальше
- [ ] Прошёл все 10 поломок из C1 руками
- [ ] Умею отлаживать сборку через `--target` и ручной запуск
- [ ] Залезаю в контейнер без shell (nsenter/netshoot)
- [ ] Чищу диск по шагам и не трогаю тома вслепую
- [ ] Настроил ротацию логов и мониторинг места
- [ ] Понимаю, что чинить надо образ/конфиг, а не контейнер
