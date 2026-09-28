---
title: "06. Жизненный цикл контейнера"
description: "Состояния контейнера, docker run/stop/exec/inspect, сигналы, PID 1, коды выхода"
---

# 06. Контейнеры: жизненный цикл и команды

> Роадмап → 3. Docker → Теория → Контейнеры → Команды
> `docker build · images · pull · push · tag · history · run · ps · stop · logs · exec · network`
> **После темы ты умеешь:** запустить, отладить, ограничить и корректно остановить контейнер,
> читать коды выхода и не бояться `docker run` с двадцатью флагами.

---

## 🗺️ Схема: жизненный цикл контейнера

```text:no-line-numbers
                   docker create
   [образ] ──────────────────────────► ┌─────────┐
      │                                │ created │
      │  docker run = create + start   └────┬────┘
      │                                docker start
      ▼                                     ▼
   ┌──────────────────────────────────────────────────────────┐
   │                        running                            │
   │   docker pause ──►  paused  ──► docker unpause            │
   └───┬──────────────────┬───────────────────────┬────────────┘
       │ docker stop      │ процесс завершился    │ docker kill
       │ (SIGTERM, ждём   │ сам (exit 0/N)        │ (SIGKILL сразу)
       │  10с, потом      │                       │
       │  SIGKILL)        ▼                       ▼
       └──────────────► ┌────────┐  docker start  ──► running
                        │ exited │  (данные writable-слоя СОХРАНЕНЫ)
                        └───┬────┘
                            │ docker rm
                            ▼
                        [удалён: writable-слой уничтожен]

   restart policy (always/on-failure/unless-stopped) автоматически возвращает в running
```

**Ключевое:** контейнер живёт ровно столько, сколько живёт его **главный процесс (PID 1)**.
Завершился процесс — контейнер в `exited`. Никакого «фонового режима» у контейнера нет.

---

## 1. `docker run` — главная команда

```bash
docker run [ОПЦИИ] ОБРАЗ [КОМАНДА] [АРГУМЕНТЫ]
```

### Опции, которые нужно знать наизусть

```bash
# Режим запуска
-d, --detach                 # в фоне, вернёт ID контейнера
-it                          # -i (stdin открыт) + -t (псевдо-tty) → интерактивная оболочка
--rm                         # удалить контейнер после остановки ← для одноразовых запусков
--name web                   # имя (иначе случайное типа "nostalgic_hopper")

# Сеть (тема 08)
-p 8080:80                   # порт хоста : порт контейнера
-p 127.0.0.1:8080:80         # публиковать только на localhost ⭐ безопаснее
-P                           # опубликовать все EXPOSE-порты на случайные порты
--network app-net            # подключить к сети
--network host               # сеть хоста (без изоляции)

# Данные (тема 07)
-v pgdata:/var/lib/postgresql/data        # named volume
-v $(pwd)/conf:/etc/nginx/conf.d:ro       # bind mount, только чтение
--tmpfs /tmp                              # в память

# Окружение
-e APP_ENV=prod -e DEBUG=0
--env-file .env
-w /app                      # рабочий каталог
-u 1000:1000                 # пользователь (перебивает USER из образа)
--entrypoint sh              # переопределить ENTRYPOINT

# Ресурсы (cgroups)
--memory=512m                # лимит RAM (превысил → OOM, код 137)
--memory-reservation=256m    # мягкий лимит
--cpus=1.5                   # квота CPU
--cpu-shares=512             # относительный вес при конкуренции
--pids-limit=100             # защита от fork-бомбы
--ulimit nofile=65535:65535

# Поведение
--restart unless-stopped     # политика перезапуска
--init                       # добавить init-процесс (tini) как PID 1 ⭐
--health-cmd / --health-interval    # healthcheck без Dockerfile
--stop-timeout 30            # сколько ждать перед SIGKILL
--read-only                  # ФС контейнера только для чтения (+ --tmpfs для записи)
--cap-drop ALL --cap-add NET_BIND_SERVICE
--security-opt no-new-privileges:true
--log-opt max-size=10m --log-opt max-file=3   # ротация логов
```

### Restart policy ⭐

| Политика | Поведение |
|----------|-----------|
| `no` (по умолчанию) | Не перезапускать |
| `on-failure[:N]` | Только при ненулевом коде выхода, максимум N попыток |
| `always` | Всегда, **включая** после перезагрузки демона/хоста; даже если остановил вручную — поднимется при рестарте докера |
| `unless-stopped` | Как `always`, но если остановил руками — после перезагрузки **не** поднимется ⭐ практичный выбор |

```bash
docker run -d --restart unless-stopped --name web nginx
docker update --restart=no web        # поменять на лету
docker inspect web --format '{{.HostConfig.RestartPolicy.Name}}'
```

---

## 2. Просмотр и управление

```bash
docker ps                        # работающие
docker ps -a                     # все, включая exited
docker ps -a --filter "status=exited" --filter "name=web"
docker ps -s                     # + размер writable-слоя
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Image}}'
docker ps -q                     # только ID (для скриптов)

docker stop web                  # SIGTERM → ждёт 10с → SIGKILL
docker stop -t 30 web            # ждать 30 секунд
docker kill web                  # SIGKILL сразу
docker kill -s HUP web           # послать произвольный сигнал (перечитать конфиг)
docker start web
docker restart web
docker pause web / docker unpause web     # заморозить процессы (cgroup freezer)

docker rm web                    # удалить остановленный
docker rm -f web                 # убить и удалить
docker rm -v web                 # + анонимные тома
docker container prune           # снести все остановленные
docker rename web web-old
docker update --memory=1g web    # менять лимиты на лету
```

---

## 3. Отладка: logs, exec, inspect ⭐

### `docker logs` — stdout/stderr главного процесса

```bash
docker logs web
docker logs -f web                    # следить (как tail -f)
docker logs --tail 100 web
docker logs --since 10m web
docker logs --since 2026-09-13T10:00:00 --until 2026-09-13T11:00:00 web
docker logs -t web                    # с временными метками
docker inspect web --format '{{.LogPath}}'   # где лежит json-файл на хосте
```

> Логи — это **то, что приложение пишет в stdout/stderr**. Если приложение пишет в файл
> внутри контейнера — `docker logs` пуст. Правило: **логи в stdout**, ротацию и сбор
> делает инфраструктура (json-file с `max-size`, или драйверы `journald`/`fluentd`/`loki`).

```json
// /etc/docker/daemon.json — иначе логи съедят диск (классический инцидент)
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
```

### `docker exec` — процесс внутри работающего контейнера

```bash
docker exec -it web bash              # или sh, если bash нет
docker exec -u root -it web bash      # зайти рутом в non-root контейнер
docker exec web ps aux
docker exec -e DEBUG=1 web env
docker exec -w /app web ls -la
```
> `exec` **не** работает у остановленного контейнера и у distroless/scratch (нет shell).
> Выход: `docker run --entrypoint sh -it образ`, `nsenter`, `docker debug` (Desktop),
> в k8s — ephemeral containers.

### `docker inspect` — полный JSON о контейнере

```bash
docker inspect web
docker inspect web --format '{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}'
docker inspect web --format '{{.NetworkSettings.IPAddress}}'
docker inspect web --format '{{json .Mounts}}' | jq .
docker inspect web --format '{{json .State.Health}}' | jq .
docker inspect web --format '{{.Config.Image}} {{.Config.Cmd}} {{.Config.Entrypoint}}'
```

### Остальной инструментарий

```bash
docker top web                   # процессы контейнера (как ps на хосте)
docker stats                     # CPU/RAM/сеть/IO в реальном времени
docker stats --no-stream
docker diff web                  # изменения ФС относительно образа
docker port web                  # проброшенные порты
docker events                    # ⭐ поток событий демона (start/die/oom/health_status)
docker cp web:/app/log.txt ./    # скопировать файл из контейнера
docker cp ./conf web:/etc/app/   # и обратно
docker attach web                # подключиться к stdout PID 1 (Ctrl-P Ctrl-Q для выхода!)
docker wait web                  # заблокироваться до завершения, вернуть код выхода
docker commit web myimg:debug    # сделать образ из контейнера (только для отладки!)
```

---

## 4. Сигналы, PID 1 и коды выхода ⭐

```text:no-line-numbers
docker stop
    │
    ├─► SIGTERM → PID 1 контейнера
    │      ├─ приложение обработало → закрыло соединения → exit 0     ✅ graceful
    │      └─ проигнорировало/не получило
    │                │  ждём --stop-timeout (по умолчанию 10 сек)
    │                ▼
    └─────────► SIGKILL → процесс убит принудительно → exit 137       ❌
```

| Код | Значение |
|-----|----------|
| `0` | Штатное завершение |
| `1` / `2` | Ошибка приложения / ошибка использования shell |
| `125` | Ошибка самого докера (неверный флаг) |
| `126` | Команда найдена, но не исполняется (нет прав, не тот формат) |
| `127` | Команда не найдена (опечатка в `CMD`, нет бинарника в образе) |
| `137` | 128+9 → **SIGKILL**: OOM-killer или таймаут `docker stop` |
| `139` | 128+11 → SIGSEGV |
| `143` | 128+15 → SIGTERM (процесс завершён сигналом, но без обработчика) |

```bash
docker inspect web --format '{{.State.ExitCode}} {{.State.OOMKilled}} {{.State.Error}}'
docker events --filter event=oom --filter event=die
```

**Проблема PID 1.** Внутри контейнера приложение — PID 1, а у PID 1 в Linux особое поведение:
для него нет обработчиков сигналов по умолчанию (SIGTERM просто игнорируется, если нет
явного хендлера) и он обязан «усыновлять» зомби-процессы.

```bash
# Три симптома одной проблемы:
#  1. docker stop всегда занимает ровно 10 секунд
#  2. код выхода 137 при штатной остановке
#  3. внутри копятся <defunct> процессы

docker run -d --init --name app myimg      # ⭐ докер подставит tini как PID 1
# или в Dockerfile: ENTRYPOINT ["/usr/bin/tini","--"] CMD ["node","app.js"]
# или в приложении: обработчик SIGTERM (правильный путь)
```

---

## 5. Один процесс на контейнер

```text:no-line-numbers
❌ nginx + php-fpm + cron в одном контейнере
   - падение одного не видно докеру (PID 1 жив → «всё ок»)
   - логи перемешаны в одном stdout
   - нельзя масштабировать по отдельности
   - обновление одного требует пересборки всего

✅ три контейнера, связанные сетью (тема 08) и описанные в compose (тема 09)
```
Исключение — вспомогательный процесс, неотделимый от главного (тогда `--init`
или supervisor, и это осознанное решение с оговорками).

---

## 💼 Как это в DevOps

- `docker logs` + `docker inspect` + `docker events` — 90% разбора инцидента с контейнером.
- **Лимиты обязательны** в проде: без `--memory` один контейнер утянет за собой весь хост.
- `--restart unless-stopped` (или systemd-юнит, или оркестратор) — иначе после перезагрузки
  сервера ничего не поднимется.
- **Ротация логов** через `daemon.json` — иначе `/var/lib/docker` забьёт диск за неделю.
- Контейнер — **одноразовый**: не чини его изнутри через `exec`, а исправь образ/конфиг
  и пересоздай. Всё, что сделано через `exec`, исчезнет при пересоздании и не воспроизводится.

---

## 🧪 Мини-лаба: жизненный цикл руками

```bash
# 1. Состояния
docker create --name lc nginx:alpine && docker ps -a --filter name=lc   # Created
docker start lc  && docker ps --filter name=lc                          # Up
docker pause lc  && docker ps --filter name=lc                          # Up (Paused)
docker unpause lc
docker stop lc   && docker ps -a --filter name=lc                       # Exited (0)
docker start lc && docker rm -f lc

# 2. Контейнер живёт, пока жив PID 1
docker run -d --name short alpine sleep 3
docker ps --filter name=short; sleep 4; docker ps -a --filter name=short   # Exited (0)
docker rm short
docker run -d --name inst alpine echo hi     # завершится мгновенно
docker logs inst; docker rm inst

# 3. Сигналы и коды выхода
docker run -d --name shellform alpine sh -c 'sleep 300'
time docker stop shellform                     # ~10 секунд
docker inspect shellform --format 'exit={{.State.ExitCode}}'   # 137
docker rm shellform

docker run -d --name execform alpine sleep 300
time docker stop execform                      # мгновенно
docker inspect execform --format 'exit={{.State.ExitCode}}'    # 137 (sleep не ловит TERM)
docker rm execform

# приложение с обработчиком SIGTERM → код 0
cat > /tmp/graceful.sh <<'EOF'
#!/bin/sh
trap 'echo "SIGTERM получен, завершаюсь"; exit 0' TERM
echo "работаю"; while true; do sleep 1; done
EOF
chmod +x /tmp/graceful.sh
docker run -d --name grace -v /tmp/graceful.sh:/g.sh:ro alpine /g.sh
time docker stop grace
docker logs grace; docker inspect grace --format 'exit={{.State.ExitCode}}'   # 0 ✅
docker rm grace

# 4. Коды ошибок
docker run --rm alpine nosuchcommand ; echo "exit=$?"      # 127
docker run --rm --entrypoint /etc/hostname alpine ; echo "exit=$?"  # 126
docker run --rm --memory=20m python:3-alpine python -c "x=' '*99999999" ; echo "exit=$?"  # 137

# 5. Restart policy
docker run -d --name flaky --restart on-failure:3 alpine sh -c 'sleep 2; exit 1'
sleep 12; docker ps -a --filter name=flaky
docker inspect flaky --format 'restarts={{.RestartCount}} policy={{.HostConfig.RestartPolicy.Name}}'
docker rm -f flaky

# 6. Лимиты
docker run -d --name lim --memory=100m --cpus=0.5 --pids-limit=50 nginx:alpine
docker stats --no-stream lim
docker update --memory=200m --memory-swap=200m lim
docker inspect lim --format '{{.HostConfig.Memory}}'
docker rm -f lim

# 7. Отладка
docker run -d --name web -p 8080:80 nginx:alpine
curl -s localhost:8080 >/dev/null; docker logs --tail 5 web
docker exec web ls /usr/share/nginx/html
docker exec -it web sh -c 'echo "<h1>hi</h1>" > /usr/share/nginx/html/index.html'
curl -s localhost:8080
docker top web
docker diff web | head
docker port web
docker cp web:/etc/nginx/nginx.conf /tmp/nginx.conf && head -3 /tmp/nginx.conf
docker inspect web --format '{{.State.Status}} {{.NetworkSettings.IPAddress}}'

# ⚠️ доказательство одноразовости: правка через exec исчезает
docker rm -f web
docker run -d --name web -p 8080:80 nginx:alpine
curl -s localhost:8080 | head -3        # снова дефолтная страница — правки НЕТ

# 8. События демона в реальном времени (второй терминал)
docker events --since 5m --filter container=web | head -5

# 9. Уборка
docker rm -f web; rm -f /tmp/graceful.sh /tmp/nginx.conf
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `docker run -d --name N -p H:C IMG` | Запустить в фоне с пробросом порта |
| `docker run --rm -it IMG sh` | Разовый интерактивный контейнер |
| `docker ps [-a] [-s] [-q]` | Список: работающие / все / с размером / только ID |
| `docker start\|stop\|restart N` | Управление |
| `docker stop -t 30 N` | Остановить с таймаутом |
| `docker kill [-s SIG] N` | SIGKILL / произвольный сигнал |
| `docker rm [-f] [-v] N` | Удалить (принудительно / с анонимными томами) |
| `docker logs -f --tail 100 --since 10m N` | Логи |
| `docker exec -it [-u root] N sh` | Команда/оболочка внутри |
| `docker inspect N --format '…'` | Любое поле конфигурации и состояния |
| `docker top N` / `docker stats` | Процессы / потребление ресурсов |
| `docker diff N` | Изменения ФС относительно образа |
| `docker port N` | Проброшенные порты |
| `docker cp N:/path ./` | Копирование файлов |
| `docker events --filter event=die` | Поток событий демона |
| `docker update --memory=1g --restart=no N` | Изменить лимиты/политику на лету |
| `docker container prune` | Удалить все остановленные |
| `docker wait N` | Дождаться завершения и получить код |

---

## 🧠 Что запомнить

1. Контейнер живёт, **пока жив PID 1**. Нет процесса — нет контейнера.
2. `docker run` = `create` + `start`. `--rm` удаляет после выхода, `-d` — фон, `-it` — интерактив.
3. `docker stop` = SIGTERM → ждёт (10 с) → SIGKILL. `docker kill` = сразу SIGKILL.
4. **137** = SIGKILL (OOM или таймаут остановки), **143** = SIGTERM,
   **127** = команды нет, **126** = не исполняется, **125** = ошибка докера.
5. PID 1 не имеет дефолтных обработчиков сигналов → нужен обработчик в приложении,
   exec-форма, или `--init`/tini.
6. `--restart unless-stopped` — практичный выбор для одиночных контейнеров.
7. Логи — только из **stdout/stderr**; настраивай ротацию (`max-size`/`max-file`),
   иначе диск кончится.
8. Лимиты `--memory`, `--cpus`, `--pids-limit` в проде обязательны.
9. `exec` — для диагностики, а не для починки: изменения исчезнут при пересоздании.
10. Данные внутри контейнера временны: всё важное — в volume (тема 07).
11. Один процесс = один контейнер.
12. Порядок разбора инцидента: `docker ps -a` → `docker logs` → `docker inspect` →
    `docker events` → `docker stats`.

---

## Задачи

> Уборка: `docker rm -f $(docker ps -aq) 2>/dev/null; docker container prune -f`

---

### Блок A. Теория

**A1.** Нарисуй жизненный цикл контейнера: состояния и переходы между ними.

<details><summary>Ответ</summary>

`created` → (`start`) → `running` ⇄ `paused` (`pause`/`unpause`) → `exited`
(по `stop`/`kill` или когда завершился процесс) → (`start` вернёт в `running`) → (`rm`) → удалён.
`restarting` — промежуточное состояние при действии restart policy. `dead` — редкое состояние
при сбое удаления.

</details>

**A2.** Почему контейнер завершается сразу после запуска, если `CMD` был `echo hi`?

<details><summary>Ответ</summary>

Контейнер живёт, пока работает PID 1. `echo hi` печатает строку и завершается —
процесса больше нет, контейнер переходит в `exited (0)`. Это не ошибка, а нормальное поведение.

</details>

**A3.** Чем `docker run` отличается от `docker create` + `docker start`?

<details><summary>Ответ</summary>

`run` = `create` (создать контейнер из образа: writable-слой, конфиг, сеть) +
`start` (запустить процесс). `create` полезен, когда нужно подготовить контейнер заранее
или изменить что-то перед стартом.

</details>

**A4.** Чем `docker stop` отличается от `docker kill`? Что происходит по шагам?

<details><summary>Ответ</summary>

`stop`: посылает **SIGTERM** (или `STOPSIGNAL`) главному процессу, ждёт таймаут
(по умолчанию 10 с, меняется `-t`/`--stop-timeout`), если процесс не завершился — **SIGKILL**.
`kill`: сразу SIGKILL (или указанный `-s` сигнал), без ожидания.

</details>

**A5.** Что значат коды выхода 0, 125, 126, 127, 137, 139, 143?

<details><summary>Ответ</summary>

0 — успех; 125 — ошибка самого докера (неверные флаги/опции);
126 — команда найдена, но не может быть выполнена (нет `+x`, не тот формат);
127 — команда не найдена; 137 = 128+9 SIGKILL (OOM или таймаут stop);
139 = 128+11 SIGSEGV; 143 = 128+15 SIGTERM.

</details>

**A6.** Почему `docker stop` часто занимает ровно 10 секунд? Три причины и три решения.

<details><summary>Ответ</summary>

Причины: (1) команда в shell-форме → PID 1 это `sh`, который не пересылает сигнал;
(2) приложение не обрабатывает SIGTERM; (3) entrypoint-скрипт без `exec "$@"`, или PID 1 —
`npm`/`bash`-обёртка. Решения: exec-форма, обработчик SIGTERM в коде, `exec "$@"`,
`--init`/tini; при долгом завершении — увеличить `--stop-timeout`.

</details>

**A7.** В чём проблема PID 1 в контейнере? Что делает флаг `--init`?

<details><summary>Ответ</summary>

PID 1 в Linux не получает действий по умолчанию для сигналов: если у процесса нет
явного обработчика SIGTERM, сигнал просто игнорируется. Плюс PID 1 обязан «усыновлять»
осиротевшие процессы и вычитывать зомби, чего обычные приложения не делают. `--init`
подставляет минимальный init (tini) первым процессом: он корректно пересылает сигналы
и собирает зомби.

</details>

**A8.** Перечисли 4 политики перезапуска и разницу `always` vs `unless-stopped`.

<details><summary>Ответ</summary>

`no` — никогда; `on-failure[:N]` — только при ненулевом коде, не более N раз;
`always` — всегда, в том числе поднимается после рестарта демона/хоста, даже если контейнер
был остановлен вручную; `unless-stopped` — так же, но ручная остановка запоминается и после
перезагрузки контейнер не поднимется.

</details>

**A9.** Что делает `docker exec`? Почему изменения через него — плохая практика?

<details><summary>Ответ</summary>

Запускает **дополнительный** процесс внутри namespaces работающего контейнера.
Изменения живут в writable-слое конкретного контейнера: при пересоздании (новый образ, деплой,
рестарт ноды) они исчезнут, в git их нет, воспроизвести нельзя — конфигурационный дрейф.

</details>

**A10.** Откуда `docker logs` берёт данные? Что делать, если приложение пишет в файл?

<details><summary>Ответ</summary>

Из stdout/stderr главного процесса, которые демон пишет в файл
(`/var/lib/docker/containers/<id>/<id>-json.log` при json-file драйвере). Если приложение
пишет в файл внутри контейнера — переконфигурировать его на вывод в stdout (правильно),
либо временно читать через `docker exec tail -f`, либо примонтировать каталог логов наружу.

</details>

**A11.** Почему обязательно настраивать ротацию логов докера и где это делается?

<details><summary>Ответ</summary>

json-file по умолчанию **без ограничений** — активное приложение за неделю может
записать десятки гигабайт и забить диск. Настраивается глобально в `/etc/docker/daemon.json`
(`log-opts: max-size, max-file`) или на контейнер (`--log-opt`). Глобальная настройка
применяется к **новым** контейнерам после рестарта демона.

</details>

**A12.** Чем `docker pause` отличается от `docker stop`?

<details><summary>Ответ</summary>

`pause` замораживает процессы через cgroup freezer: они остаются в памяти,
соединения не рвутся (но и не обрабатываются), состояние сохраняется. `stop` посылает сигнал,
процесс завершается, контейнер переходит в `exited`.

</details>

**A13.** Что показывает `docker diff` и что означают буквы A, C, D?

<details><summary>Ответ</summary>

Изменения файловой системы контейнера относительно образа: `A` — файл добавлен,
`C` — изменён, `D` — удалён. Удобно понять, что приложение пишет внутрь контейнера
(и что стоит вынести в volume).

</details>

**A14.** Зачем нужен `docker events` и какие фильтры полезны при разборе инцидента?

<details><summary>Ответ</summary>

Поток событий демона в реальном времени: create/start/die/oom/health_status/destroy,
события образов, сетей, томов. Фильтры: `--filter event=die`, `--filter event=oom`,
`--filter container=NAME`, `--since/--until`. Позволяет увидеть, что происходило, даже если
контейнер уже удалён.

</details>

**A15.** Почему `-p 127.0.0.1:8080:80` безопаснее, чем `-p 8080:80`?

<details><summary>Ответ</summary>

`-p 8080:80` публикует порт на **всех** интерфейсах хоста (0.0.0.0) — сервис доступен
из внешней сети, и правила докера в iptables часто **обходят** UFW/firewalld.
`-p 127.0.0.1:8080:80` слушает только локально — доступ снаружи закрыт (типовой вариант
для админок и БД за reverse proxy).

</details>

**A16.** Что произойдёт с данными внутри контейнера при `docker stop` + `docker start`?
А при `docker rm` + `docker run`?

<details><summary>Ответ</summary>

`stop`+`start` — writable-слой сохраняется, данные на месте. `rm`+`run` — контейнер
(и его writable-слой) уничтожается, создаётся новый из образа: все изменения потеряны.
Поэтому важные данные должны жить в volume.

</details>

**A17.** Почему «один процесс на контейнер»? Четыре аргумента.

<details><summary>Ответ</summary>

(1) Докер следит только за PID 1 — падение второго процесса останется незамеченным;
(2) логи смешиваются в одном stdout; (3) нельзя масштабировать и перезапускать компоненты
независимо; (4) обновление одного компонента требует пересборки всего образа;
плюс health-check и лимиты ресурсов становятся бессмысленными.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  docker run -d --name web -p 127.0.0.1:8080:80 --restart unless-stopped nginx
B2.  docker run --rm -it alpine sh
B3.  docker run -d --init --memory=256m --cpus=0.5 --pids-limit=100 myapp
B4.  docker ps -a --filter "status=exited" --format '{{.Names}} {{.Status}}'
B5.  docker stop -t 30 web
B6.  docker kill -s HUP nginx
B7.  docker logs -f --since 15m --tail 50 -t web
B8.  docker exec -u root -it web bash
B9.  docker inspect web --format '{{.State.ExitCode}} {{.State.OOMKilled}}'
B10. docker update --memory=1g --restart=no web
B11. docker events --filter event=die --filter event=oom
B12. docker cp web:/etc/nginx/nginx.conf ./
B13. docker top web
B14. docker wait web; echo $?
B15. docker commit web debug:1
B16. docker run -d --restart on-failure:3 app
```

**B1.** nginx в фоне, порт опубликован только на localhost хоста, автоподъём после
перезагрузки, но не после ручной остановки.
**B2.** Разовая интерактивная оболочка, контейнер удалится при выходе.
**B3.** Запуск с init-процессом и лимитами памяти, CPU и числа процессов.
**B4.** Только остановленные контейнеры в компактном формате.
**B5.** Остановка с ожиданием 30 секунд до SIGKILL.
**B6.** Послать SIGHUP (для nginx — мягкая перезагрузка конфига без простоя).
**B7.** Следить за логами за последние 15 минут, последние 50 строк, с метками времени.
**B8.** Оболочка внутри контейнера от root, даже если в образе `USER app`.
**B9.** Код выхода и признак OOM — первое, что смотрят у упавшего контейнера.
**B10.** Изменить лимит памяти и политику рестарта без пересоздания.
**B11.** Поток событий: завершения контейнеров и OOM-события.
**B12.** Скопировать файл из контейнера на хост.
**B13.** Процессы контейнера глазами хоста (работает даже без `ps` внутри образа).
**B14.** Заблокироваться до завершения контейнера и получить его код выхода.
**B15.** Сделать образ из текущего состояния контейнера (только для отладки — так не собирают образы).
**B16.** Перезапускать до 3 раз при ненулевом коде выхода.

**B17.** Чем отличается `docker attach web` от `docker exec -it web sh`?
Чем опасен первый вариант?

<details><summary>Ответ</summary>

`attach` подключается к stdin/stdout **существующего PID 1**, а не создаёт новый
процесс. Опасность: `Ctrl+C` уйдёт главному процессу и остановит контейнер; выходить надо
`Ctrl-P Ctrl-Q`. `exec -it … sh` запускает отдельный процесс — безопасно.

</details>

---

### Блок C. Практика

#### C1. 🔑 Корректная остановка приложения (главное задание)

Напиши приложение (любой язык), которое:
- пишет в stdout строку раз в секунду;
- по SIGTERM выводит «graceful shutdown», закрывает «соединения» (спит 2 сек) и выходит с кодом 0;
- по SIGHUP печатает «config reloaded».

Оберни его в контейнер и докажи:
1. `docker stop` укладывается в ~2-3 секунды (а не 10), код выхода **0**, а не 137.
2. `docker kill -s HUP` вызывает перечитывание конфига без остановки.
3. Если запустить то же самое shell-формой (`CMD app.sh` вместо `CMD ["./app.sh"]`),
   всё ломается — покажи разницу в `docker top` (кто PID 1) и во времени остановки.
4. Почини сломанный вариант через `--init`, покажи PID 1 = `docker-init`.
5. Подбери `--stop-timeout`, если приложению нужно 20 секунд на завершение.

<details><summary>Ответ</summary>

```bash
mkdir -p ~/docker-lab/06 && cd ~/docker-lab/06
cat > app.sh <<'EOF'
#!/bin/sh
trap 'echo "graceful shutdown"; sleep 2; echo "готово"; exit 0' TERM
trap 'echo "config reloaded"' HUP
echo "started pid=$$"
while true; do echo "tick $(date +%T)"; sleep 1; done
EOF
chmod +x app.sh

printf 'FROM alpine:3.20\nCOPY app.sh /app.sh\nCMD ["/app.sh"]\n'  > Dockerfile.exec
printf 'FROM alpine:3.20\nCOPY app.sh /app.sh\nCMD /app.sh\n'      > Dockerfile.shell
docker build -q -f Dockerfile.exec  -t lc:exec  .
docker build -q -f Dockerfile.shell -t lc:shell .

docker run -d --name ok lc:exec
docker top ok                                   # PID 1 = /bin/sh /app.sh (наш скрипт)
docker kill -s HUP ok; docker logs ok | grep reloaded
time docker stop ok                             # ~2-3 сек
docker inspect ok --format 'exit={{.State.ExitCode}}'    # 0 ✅
docker logs ok | tail -3; docker rm ok

docker run -d --name bad lc:shell
docker top bad                                  # PID 1 = /bin/sh -c /app.sh → скрипт ДОЧЕРНИЙ
time docker stop bad                            # 10 секунд
docker inspect bad --format 'exit={{.State.ExitCode}}'   # 137 ❌
docker rm bad

docker run -d --init --name fixed lc:shell
docker top fixed                                # PID 1 = /sbin/docker-init (tini)
time docker stop fixed                          # быстро
docker rm fixed

docker run -d --name slow --stop-timeout 20 lc:exec   # запас для долгого завершения
docker inspect slow --format '{{.Config.StopTimeout}}'; docker rm -f slow
```

</details>

#### C2. Коды выхода — собери коллекцию

Получи своими руками контейнеры с кодами 0, 1, 126, 127, 137 (OOM), 137 (таймаут stop), 143.
Для каждого покажи, как ты определил причину по `docker inspect`.

<details><summary>Ответ</summary>

```bash
docker run --name e0  --rm alpine true;  echo "0:   $?"
docker run --name e1  --rm alpine false; echo "1:   $?"
docker run --rm --entrypoint /etc/hostname alpine; echo "126: $?"
docker run --rm alpine nosuchcmd 2>/dev/null; echo "127: $?"
docker run --name oom --memory=50m python:3-alpine python -c "b=bytearray(300*1024*1024)" 2>/dev/null
echo "137(oom): $?"; docker inspect oom --format 'OOMKilled={{.State.OOMKilled}}'; docker rm oom
docker run -d --name t137 alpine sh -c 'trap "" TERM; sleep 300'
docker stop t137 >/dev/null; docker inspect t137 --format '137(timeout): {{.State.ExitCode}}'; docker rm t137
docker run -d --name t143 alpine sleep 300
docker kill t143 -s TERM >/dev/null; sleep 1
docker inspect t143 --format '143: {{.State.ExitCode}}'; docker rm t143
```

</details>

#### C3. Restart policy

1. Запусти контейнер, который падает раз в 3 секунды, с `on-failure:3`.
   Посчитай `RestartCount`, дождись остановки попыток.
2. Запусти с `always` и с `unless-stopped`, останови оба руками,
   перезапусти демон (`sudo systemctl restart docker`) — какой поднялся, какой нет?
3. Какую политику выберешь для БД на одиночном сервере и почему?

<details><summary>Ответ</summary>

```bash
docker run -d --name flaky --restart on-failure:3 alpine sh -c 'sleep 3; exit 1'
sleep 20; docker ps -a --filter name=flaky
docker inspect flaky --format 'RestartCount={{.RestartCount}}'; docker rm -f flaky

docker run -d --name p-always  --restart always         alpine sleep 3600
docker run -d --name p-unless  --restart unless-stopped alpine sleep 3600
docker stop p-always p-unless
sudo systemctl restart docker; sleep 3
docker ps -a --filter name=p-           # p-always снова Up, p-unless остался Exited
docker rm -f p-always p-unless
# Для БД на одиночном сервере: unless-stopped — автоподъём после перезагрузки,
# но если инженер остановил базу намеренно (обслуживание), она не поднимется сама.
```

</details>

#### C4. Лимиты ресурсов

1. Запусти контейнер с `--memory=100m`, заставь съесть 300 МБ — покажи OOM в трёх местах
   (код выхода, `docker inspect`, `dmesg`).
2. Запусти CPU-нагрузку с `--cpus=0.25` и без — сравни `docker stats`.
3. Запусти fork-бомбу c `--pids-limit=50` (безопасно!) и покажи, что хост выжил.
4. Измени лимит памяти работающему контейнеру без пересоздания.

<details><summary>Ответ</summary>

```bash
docker run --name m --memory=100m python:3-alpine python -c "b=bytearray(300*1024*1024)"
echo "exit=$?"; docker inspect m --format '{{.State.OOMKilled}}'; sudo dmesg -T | tail -3; docker rm m

docker run -d --name cpu-free  alpine sh -c 'while :; do :; done'
docker run -d --name cpu-limit --cpus=0.25 alpine sh -c 'while :; do :; done'
docker stats --no-stream cpu-free cpu-limit; docker rm -f cpu-free cpu-limit

docker run -d --name bomb --pids-limit=50 alpine sh -c ':(){ :|:& };:' 2>/dev/null
sleep 3; docker logs bomb 2>&1 | tail -2; docker stats --no-stream bomb; docker rm -f bomb
# хост жив: cgroup pids не дал расплодиться

docker run -d --name upd --memory=100m alpine sleep 3600
docker update --memory=200m --memory-swap=200m upd
docker inspect upd --format '{{.HostConfig.Memory}}'; docker rm -f upd
```

</details>

#### C5. Отладка «чёрного ящика»

Запусти `nginx`, затем, не заглядывая в документацию образа, выясни только командами докера:
1. Какой процесс PID 1 и с какими аргументами.
2. Куда пишутся логи доступа и ошибок.
3. Какие порты слушает контейнер (изнутри и снаружи).
4. Какой IP у контейнера и в какой он сети.
5. Какие точки монтирования у него есть.
6. Какие переменные окружения заданы.
7. Изменялась ли его ФС относительно образа.

<details><summary>Ответ</summary>

```bash
docker run -d --name web -p 8080:80 nginx:alpine
docker top web                                                   # 1) PID 1 и аргументы
docker exec web ls -l /var/log/nginx/                            # 2) симлинки на /dev/stdout
docker exec web sh -c 'ss -tlnp 2>/dev/null || netstat -tlnp'    # 3) изнутри
docker port web                                                  #    снаружи
docker inspect web --format '{{range $n,$c := .NetworkSettings.Networks}}{{$n}} {{$c.IPAddress}}{{end}}'  # 4)
docker inspect web --format '{{json .Mounts}}' | jq .            # 5)
docker inspect web --format '{{json .Config.Env}}' | jq .        # 6)
docker diff web                                                  # 7)
```

</details>

#### C6. Логи и ротация

1. Запусти контейнер, который печатает много строк, посмотри размер файла логов на хосте.
2. Ограничь лог 1 МБ и 2 файлами через флаги запуска — проверь, что ротация работает.
3. Пропиши ротацию глобально в `/etc/docker/daemon.json`, перезапусти демон,
   убедись, что новые контейнеры её наследуют.
4. Запусти контейнер, который пишет логи в файл внутри себя — покажи, что `docker logs` пуст,
   и объясни, как это чинить правильно.

<details><summary>Ответ</summary>

```bash
docker run -d --name noisy alpine sh -c 'i=0; while :; do i=$((i+1)); echo "line $i $(head -c 200 /dev/zero|tr "\0" x)"; done'
sleep 5; sudo ls -lh $(docker inspect noisy --format '{{.LogPath}}'); docker rm -f noisy

docker run -d --name rot --log-opt max-size=1m --log-opt max-file=2 \
  alpine sh -c 'while :; do head -c 100000 /dev/urandom | base64; done'
sleep 10; sudo ls -lh $(docker inspect rot --format '{{.LogPath}}')*; docker rm -f rot

sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "3" } }
EOF
sudo systemctl restart docker
docker run -d --name check alpine sleep 60
docker inspect check --format '{{json .HostConfig.LogConfig}}'; docker rm -f check

docker run -d --name filelog alpine sh -c 'while :; do echo x >> /var/log/app.log; sleep 1; done'
docker logs filelog          # пусто
docker exec filelog tail -2 /var/log/app.log
docker rm -f filelog
# Правильно: настроить приложение писать в stdout, либо симлинк /var/log/app.log -> /dev/stdout
```

</details>

#### C7. Одноразовость контейнера

1. Запусти nginx, поправь `index.html` через `docker exec`.
2. Сделай `docker restart` — изменения на месте?
3. Сделай `docker rm -f` + `docker run` — изменения на месте?
4. Реализуй то же изменение правильно (два способа: свой образ и bind mount).

<details><summary>Ответ</summary>

```bash
docker run -d --name w -p 8080:80 nginx:alpine
docker exec w sh -c 'echo "<h1>patched</h1>" > /usr/share/nginx/html/index.html'
curl -s localhost:8080
docker restart w; curl -s localhost:8080          # правка ЖИВА (writable-слой на месте)
docker rm -f w && docker run -d --name w -p 8080:80 nginx:alpine
curl -s localhost:8080 | head -3                  # правка ИСЧЕЗЛА
docker rm -f w
# Правильно (1): свой образ
printf '<h1>patched</h1>\n' > index.html
printf 'FROM nginx:alpine\nCOPY index.html /usr/share/nginx/html/index.html\n' > Dockerfile.web
docker build -q -f Dockerfile.web -t web:1.0 . && docker run -d --name w -p 8080:80 web:1.0
curl -s localhost:8080; docker rm -f w
# Правильно (2): bind mount
docker run -d --name w -p 8080:80 -v "$PWD/index.html:/usr/share/nginx/html/index.html:ro" nginx:alpine
curl -s localhost:8080; docker rm -f w
cd ~ && rm -rf ~/docker-lab/06
```

</details>

---

### Блок D. Инциденты

**D1.** Контейнер в бесконечном цикле перезапусков: `Restarting (1) 5 seconds ago`.
Как диагностировать, если логи очищаются при каждом старте?

<details><summary>Ответ</summary>

Логи **не** очищаются при рестарте контейнера — `docker logs` хранит вывод всех
запусков, если контейнер не пересоздаётся. Смотреть: `docker logs --tail 100 <c>`,
<code v-pre>docker inspect &lt;c&gt; --format '{{.State.ExitCode}} {{.State.Error}} {{.RestartCount}}'</code>,
`docker events --filter container=<c>`. Чтобы поймать «живьём»: временно снять restart policy
(`docker update --restart=no`), затем запустить вручную с переопределённой командой
(`docker run --rm -it --entrypoint sh <образ>`) и выполнить команду приложения руками.

</details>

**D2.** `docker exec -it app bash` → `OCI runtime exec failed: exec: "bash": executable file not found`.
Что делать? Три варианта.

<details><summary>Ответ</summary>

(1) В образе нет bash — использовать `sh`; (2) образ distroless/scratch — зайти
нельзя вообще: использовать <code v-pre>nsenter -t $(docker inspect -f '{{.State.Pid}}' app) -a sh</code>
с хоста, отладочный вариант образа, или `docker run --entrypoint sh` для аналогичного образа
с shell; (3) контейнер не запущен — `exec` работает только у running.

</details>

**D3.** Приложение при деплое теряет соединения пользователей: балансировщик ещё шлёт трафик,
а контейнер уже умер. Что настроить со стороны докера и приложения?

<details><summary>Ответ</summary>

Со стороны докера: `--stop-timeout` достаточной длины, `STOPSIGNAL`, корректная
exec-форма. Со стороны приложения: обработчик SIGTERM, который сначала перестаёт принимать
новые соединения и отвечает `503`/снимается с балансировки (readiness), дорабатывает текущие
запросы, потом выходит. Плюс pre-stop-задержка (в k8s — `preStop` hook со `sleep`), чтобы
балансировщик успел убрать бэкенд.

</details>

**D4.** На сервере кончилось место. `du -sh /var/lib/docker/containers` = 90 ГБ.
Что произошло, как срочно починить и как предотвратить?

<details><summary>Ответ</summary>

Логи контейнеров без ротации (json-file без `max-size`). Срочно: найти самые толстые
файлы `sudo du -sh /var/lib/docker/containers/* | sort -h | tail`, при необходимости
`truncate -s 0 <logfile>` (не `rm` — файл открыт демоном) или пересоздать контейнер.
Предотвратить: `log-opts` в `/etc/docker/daemon.json` + рестарт демона, мониторинг диска,
внешний сборщик логов.

</details>

**D5.** Контейнер работает, `docker ps` показывает `Up 3 hours`, но приложение не отвечает.
Как отличить «процесс жив, но завис» от «процесс работает, проблема в сети»?

<details><summary>Ответ</summary>

Проверить процессы (`docker top`, `docker stats` — ест ли CPU), зайти внутрь и
дёрнуть приложение локально (`docker exec c curl -s localhost:8080/health`). Если изнутри
отвечает, а снаружи нет — проблема в публикации портов/сети/адресе прослушивания
(`0.0.0.0` vs `127.0.0.1`), проверить `docker port`, `ss -tlnp` на хосте, iptables.
Если изнутри тоже не отвечает — приложение зависло: смотреть логи, треды/дампы,
healthcheck, deadlock, нехватку ресурсов.

</details>

**D6.** После перезагрузки сервера ни один контейнер не поднялся. Причина и решение
(два варианта).

<details><summary>Ответ</summary>

(1) У контейнеров не задана restart policy — задать `--restart unless-stopped`
или описать всё в compose с `restart:`; (2) сам сервис докера не включён в автозапуск —
`sudo systemctl enable --now docker`. Более надёжный путь для одиночного сервера —
systemd-юниты на compose-проект.

</details>

**D7.** Контейнер съел всю память хоста, из-за чего OOM-killer убил postgres на этом же сервере.
Что было сделано неправильно?

<details><summary>Ответ</summary>

У контейнера не был выставлен лимит `--memory`, поэтому cgroup не ограничил его,
и при нехватке памяти ядро выбрало жертву по своим правилам — ею оказался postgres.
Правильно: лимиты на все контейнеры, резервирование памяти для системных служб,
мониторинг, а БД лучше вообще держать отдельно от нагруженных приложений.

</details>

**D8.** `docker stop` вернул управление, но процесс приложения ещё виден в `ps` на хосте.
Как такое возможно?

<details><summary>Ответ</summary>

Возможные варианты: процесс всё ещё в состоянии завершения (zombie/D-state, ждёт I/O);
это другой процесс с похожим именем (например, от другого контейнера); контейнер был
перезапущен политикой restart; либо процесс был запущен через `nsenter`/на хосте и к контейнеру
не относится. Проверить: <code v-pre>docker inspect -f '{{.State.Pid}} {{.State.Status}}'</code>,
`cat /proc/<pid>/cgroup`.

</details>

**D9.** Разработчик «починил» прод через `docker exec`, поставив пакет внутрь контейнера.
Через неделю после планового рестарта всё сломалось снова. Объясни ему, что произошло.

<details><summary>Ответ</summary>

Установка через `exec` попадает только в writable-слой конкретного контейнера.
Любое пересоздание (деплой, `docker compose up` с новым образом, рестарт ноды, миграция)
даёт чистый контейнер из образа — изменения исчезают. Правильно: добавить пакет в Dockerfile,
собрать новый образ, запушить и передеплоить; изменения проходят ревью и воспроизводимы.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Опиши жизненный цикл контейнера.

<details><summary>Ответ</summary>

created → running (⇄ paused) → exited → удалён; переходы `create/start/pause/unpause/
stop/kill/rm`; restart policy автоматически возвращает в running.

</details>

**2.** Что происходит при `docker stop`? Чем отличается от `docker kill`?

<details><summary>Ответ</summary>

`stop` — SIGTERM, ожидание таймаута, затем SIGKILL; `kill` — сразу SIGKILL (или заданный сигнал).

</details>

**3.** Что означает код выхода 137?

<details><summary>Ответ</summary>

128+9 — процесс убит SIGKILL: чаще всего OOM (превышен `--memory`), реже — таймаут `docker stop`.

</details>

**4.** Почему контейнер сразу останавливается после запуска?

<details><summary>Ответ</summary>

Потому что главный процесс завершился. Контейнер существует ровно столько, сколько живёт PID 1.

</details>

**5.** Какие политики перезапуска бывают?

<details><summary>Ответ</summary>

`no`, `on-failure[:N]`, `always`, `unless-stopped`.

</details>

**6.** Как посмотреть логи контейнера и что делать, если их нет?

<details><summary>Ответ</summary>

`docker logs [-f --tail --since]`. Если пусто — приложение пишет в файл или буферизует вывод:
переключить на stdout/stderr, отключить буферизацию.

</details>

**7.** Как ограничить контейнеру ресурсы?

<details><summary>Ответ</summary>

Флагами cgroups: `--memory`, `--memory-reservation`, `--cpus`, `--cpu-shares`,
`--pids-limit`, `--ulimit`, `--blkio-weight`; менять на лету — `docker update`.

</details>

**8.** В чём проблема PID 1 и как её решают?

<details><summary>Ответ</summary>

У PID 1 нет обработчиков сигналов по умолчанию и он должен собирать зомби. Решения:
exec-форма + обработчик SIGTERM в приложении, `exec "$@"` в entrypoint, `--init`/tini.

</details>

**9.** Как отладить контейнер, в котором нет shell?

<details><summary>Ответ</summary>

`nsenter` с хоста в namespaces процесса, `docker run --entrypoint sh` у образа с shell,
`docker cp` для файлов, `docker debug`/ephemeral containers в k8s, логи и `docker inspect`.

</details>

**10.** Почему один процесс на контейнер?

<details><summary>Ответ</summary>

Докер следит за PID 1; независимое масштабирование, чистые логи, отдельные рестарты
и health-check, меньшие образы, понятная ответственность.

</details>

---

### 🎯 Чек-лист

- [ ] Понимаю, почему контейнер завершается, и умею это объяснить
- [ ] Добился graceful shutdown с кодом выхода 0
- [ ] Читаю коды 125/126/127/137/143 без гугла
- [ ] Знаю, когда `--init` спасает, а когда нужен обработчик сигналов
- [ ] Ставлю лимиты памяти/CPU/pids на все контейнеры
- [ ] Настроил ротацию логов в `daemon.json`
- [ ] Отлаживаю контейнер через logs → inspect → top → events → stats
- [ ] Никогда не «чиню» прод через `docker exec`
- [ ] Выбираю restart policy осознанно
