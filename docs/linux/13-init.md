---
title: "13. Init: systemd"
description: "SysV, Upstart, systemd — юниты, unit-файлы, таргеты, таймеры, управление сервисами — конспект и задачи"
---

# 13. Init — SysV, Upstart и systemd

> Источник: `13_init.txt` (Journeyman, 7 уроков)
> **После темы ты умеешь:** управлять сервисами, писать собственные unit-файлы, разбираться
> в таргетах и таймерах. **Самая практичная тема всего курса** — этим занимаешься каждый день.

---

## 🗺️ Схема: init — PID 1

```text:no-line-numbers
   Ядро загрузилось, корень смонтирован
                 │
                 ▼
   ┌──────────────────────────────────────┐
   │  /sbin/init  →  PID 1                │  ← первый процесс в user space
   │  (сегодня это symlink на systemd)    │
   └──────────────────┬───────────────────┘
                      │ его задачи:
     ┌────────────────┼───────────────────┬────────────────────┐
     ▼                ▼                   ▼                    ▼
  запустить      монтировать        поднять сеть         усыновлять
   сервисы       fstab, tmpfs       и логирование        сирот, жать зомби
     │
     ▼
  ┌────────────────────────────────────────────────────────────┐
  │ SysV init (1983)  →  Upstart (2006)  →  systemd (2010→ )   │
  │ последовательно      события          зависимости+параллель │
  └────────────────────────────────────────────────────────────┘
```

---

## 1-2. System V init — как было

Классика: последовательный запуск скриптов по уровням выполнения (runlevels).

```text:no-line-numbers
/etc/init.d/           скрипты сервисов (обычный bash!)
/etc/rc0.d/ … rc6.d/   симлинки на них для каждого runlevel
                        S20nginx → start, порядок 20
                        K80nginx → kill,  порядок 80
```

| Runlevel | Значение |
|----------|----------|
| 0 | Выключение |
| 1 | Однопользовательский (rescue) |
| 2-4 | Многопользовательский (в Debian 2 — по умолчанию) |
| 5 | Многопользовательский + графика |
| 6 | Перезагрузка |

```bash
# Команды эпохи SysV (многие ещё работают как обёртки)
sudo service nginx start|stop|restart|status
sudo /etc/init.d/nginx start
sudo update-rc.d nginx defaults      # включить автозапуск (Debian)
sudo chkconfig nginx on              # RHEL
runlevel
sudo init 6                          # перезагрузка
```

**Проблемы SysV:** всё последовательно (долгая загрузка), нет отслеживания состояния процесса
(упал — никто не заметил), скрипты на bash со своей логикой в каждом пакете, нет зависимостей
кроме порядка номеров, нет надёжной остановки дочерних процессов.

## 3-4. Upstart — переходный этап

Ubuntu 2006-2014. Событийная модель: сервис стартует при наступлении события
(«появилась сеть», «примонтирована ФС»), а не по номеру.

```text:no-line-numbers
/etc/init/*.conf

start on runlevel [2345]
stop on runlevel [016]
respawn
exec /usr/sbin/myapp
```
```bash
initctl list
sudo start myapp / sudo stop myapp / sudo status myapp
```
Знать как исторический факт: параллельный запуск и авто-respawn появились здесь, но систему
вытеснил systemd. Сегодня встречается только на очень старых серверах (Ubuntu 14.04 и ранее).

---

## 5-6. systemd — современный стандарт

**Юнит (unit)** — описание управляемой сущности. Типы:

| Тип | Что описывает |
|-----|---------------|
| `.service` | Сервис/демон ← 90% работы |
| `.socket` | Сокет, по обращению к которому запускается сервис |
| `.timer` | Запуск по расписанию (замена cron) |
| `.mount` / `.automount` | Точка монтирования (генерируется из fstab) |
| `.target` | Группа юнитов (аналог runlevel) |
| `.path` | Реакция на появление/изменение файла |
| `.slice` / `.scope` | Группировка процессов по cgroups |
| `.device` | Устройство (от udev) |

Где живут юниты (порядок приоритета — важно!):

```text:no-line-numbers
/etc/systemd/system/      ← ТВОИ юниты и переопределения (наивысший приоритет)
/run/systemd/system/      ← временные, создаются на лету
/lib/systemd/system/      ← юниты из пакетов (не редактировать!)
```

### Основные команды (выучить наизусть)

```bash
# Управление
sudo systemctl start nginx
sudo systemctl stop nginx
sudo systemctl restart nginx          # полная перезагрузка процесса
sudo systemctl reload nginx           # перечитать конфиг БЕЗ разрыва соединений
sudo systemctl reload-or-restart nginx
sudo systemctl enable nginx           # автозапуск при загрузке
sudo systemctl disable nginx
sudo systemctl enable --now nginx     # включить автозапуск И запустить ← удобно
sudo systemctl mask nginx             # ЗАПРЕТИТЬ запуск полностью (даже вручную)
sudo systemctl unmask nginx

# Информация
systemctl status nginx                # состояние + последние строки лога ← первое движение
systemctl is-active nginx             # active / inactive (для скриптов)
systemctl is-enabled nginx
systemctl is-failed nginx
systemctl cat nginx                   # показать unit-файл целиком
systemctl show nginx                  # ВСЕ свойства (сотни)
systemctl list-units --type=service
systemctl list-units --state=failed   # ⭐ что упало
systemctl --failed
systemctl list-unit-files --state=enabled
systemctl list-dependencies nginx
systemctl list-timers                 # активные таймеры

# Конфигурация
sudo systemctl daemon-reload          # ⚠️ ОБЯЗАТЕЛЬНО после правки unit-файла
sudo systemctl edit nginx             # создать drop-in override ← ПРАВИЛЬНЫЙ способ править
sudo systemctl edit --full nginx      # переопределить юнит целиком
sudo systemctl revert nginx           # откатить изменения
```

### Анатомия unit-файла

```ini
[Unit]
Description=My Application API
Documentation=https://wiki.internal/myapp
After=network-online.target postgresql.service    # ПОРЯДОК запуска
Wants=network-online.target                        # мягкая зависимость
Requires=postgresql.service                        # жёсткая: упадёт БД — упадём мы
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple                  # simple | forking | oneshot | notify | idle
User=appuser                 # ⭐ НЕ root!
Group=appuser
WorkingDirectory=/opt/myapp
Environment="APP_ENV=production" "LOG_LEVEL=info"
EnvironmentFile=-/etc/myapp/env        # '-' = не падать, если файла нет
ExecStartPre=/opt/myapp/bin/migrate
ExecStart=/opt/myapp/bin/server --port 8080
ExecReload=/bin/kill -HUP $MAINPID
ExecStop=/bin/kill -TERM $MAINPID
Restart=on-failure           # no | always | on-failure | on-abnormal
RestartSec=5s
TimeoutStopSec=30s
KillMode=mixed
LimitNOFILE=65535            # ulimit для сервиса
StandardOutput=journal
StandardError=journal
SyslogIdentifier=myapp

# Безопасность (современные best practices)
NoNewPrivileges=yes
PrivateTmp=yes               # свой /tmp, изолированный
ProtectSystem=strict         # ФС только для чтения, кроме разрешённого
ProtectHome=yes
ReadWritePaths=/var/lib/myapp /var/log/myapp
CapabilityBoundingSet=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target   # куда «подключиться» при enable
```

**Type= — частая ошибка новичков:**

| Type | Когда использовать |
|------|--------------------|
| `simple` | Процесс **не** уходит в фон (дефолт). Большинство современных приложений |
| `exec` | Как simple, но systemd ждёт успешного `exec()` |
| `forking` | Процесс делает `fork()` и родитель завершается (классические демоны). Нужен `PIDFile=` |
| `oneshot` | Выполнил и завершился (скрипты, миграции). Часто с `RemainAfterExit=yes` |
| `notify` | Сам сообщает systemd о готовности (`sd_notify`) — идеально для health-check |
| `idle` | Запуск после всех остальных |

⚠️ Если приложение демонизируется, а ты указал `simple` — systemd решит, что сервис упал сразу
после старта, и будет бесконечно его перезапускать.

### Targets — замена runlevels

| Target | Аналог runlevel | Назначение |
|--------|-----------------|-----------|
| `poweroff.target` | 0 | Выключение |
| `rescue.target` | 1 | Однопользовательский |
| `multi-user.target` | 3 | **Сервер без графики** ← основной |
| `graphical.target` | 5 | С графикой |
| `reboot.target` | 6 | Перезагрузка |
| `emergency.target` | — | Минимальный аварийный |

```bash
systemctl get-default
sudo systemctl set-default multi-user.target
sudo systemctl isolate rescue.target     # переключиться на лету
systemctl list-dependencies multi-user.target
```

### Timers — современная замена cron

```ini
# /etc/systemd/system/backup.service
[Unit]
Description=Nightly backup
[Service]
Type=oneshot
ExecStart=/opt/scripts/backup.sh
```
```ini
# /etc/systemd/system/backup.timer
[Unit]
Description=Run backup daily at 02:00
[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true          # выполнить пропущенный запуск после включения машины
RandomizedDelaySec=300   # размазать нагрузку
[Install]
WantedBy=timers.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now backup.timer
systemctl list-timers --all
systemd-analyze calendar "*-*-* 02:00:00"     # проверить синтаксис расписания
```

Преимущества таймеров над cron: логи в journald, зависимости, изоляция и лимиты ресурсов,
`Persistent=` (не пропустит запуск, если машина была выключена), удобный статус.

---

## 7. Power States — питание

```bash
sudo systemctl poweroff          # выключить
sudo systemctl reboot            # перезагрузить
sudo systemctl suspend           # сон (RAM сохраняется, питание минимально)
sudo systemctl hibernate         # гибернация (память на диск/swap)
sudo systemctl hybrid-sleep      # и то, и другое

# Классические команды (сейчас — обёртки над systemctl)
sudo shutdown -h now             # выключить сейчас
sudo shutdown -r +5 "Плановый ребут"   # перезагрузка через 5 минут с оповещением
sudo shutdown -c                 # ОТМЕНИТЬ запланированное выключение
sudo reboot / sudo halt / sudo poweroff

# Информация
uptime
who -b                           # время последней загрузки
last reboot | head
systemd-analyze                  # сколько заняла загрузка
```

⚠️ На проде перед перезагрузкой: предупредить (`wall`), вывести из балансировки,
остановить сервисы корректно, проверить, что после ребута всё поднимется (`systemctl is-enabled`),
убедиться, что есть доступ к консоли, если сервер не вернётся.

---

## 🔍 journalctl — логи systemd (подробно в теме 15)

```bash
journalctl -u nginx              # логи конкретного юнита
journalctl -u nginx -f           # в реальном времени
journalctl -u nginx --since "10 min ago"
journalctl -u nginx -p err       # только ошибки
journalctl -xe                   # последние события с пояснениями ← при разборе падения
journalctl -b                    # текущая загрузка
```

---

## 🔧 Алгоритм «сервис не работает»

```text:no-line-numbers
1. systemctl status app          → active? failed? код выхода?
2. journalctl -u app -n 50 --no-pager   → что пишет само приложение
3. systemctl cat app             → правильный ли ExecStart, User, WorkingDirectory
4. sudo -u appuser /путь/к/бинарю --флаги   → запустить руками от того же юзера
5. ss -tulpn | grep <порт>       → не занят ли порт
6. ls -l /путь/к/файлам          → права, существование конфигов
7. systemd-analyze verify app.service   → синтаксис юнита
8. journalctl -u app --since "1 hour ago" | grep -iE 'error|fail'
```

---

## 💼 Как это в DevOps

- **Любое своё приложение на сервере оформляется unit-файлом:** автозапуск, рестарт при падении,
  логи в journald, лимиты, запуск от непривилегированного пользователя.
- `Restart=on-failure` + `RestartSec` — базовая отказоустойчивость без внешнего супервизора.
- `systemctl reload` вместо `restart` там, где поддерживается — деплой без 5xx.
- Таймеры вместо cron в современных проектах (лучше логи и контроль).
- Ansible-модуль `systemd`, Docker-контейнеры под systemd-юнитом, `systemd-run` для разовых задач.
- Директивы безопасности (`ProtectSystem`, `PrivateTmp`, `NoNewPrivileges`) — дешёвый hardening.

---

## 🧪 Мини-лаба: свой сервис от начала до конца

```bash
vagrant ssh

# 1. Разведка
systemctl list-units --type=service --state=running | head -20
systemctl --failed
systemctl get-default
systemd-analyze blame | head -5

# 2. Приложение
sudo useradd --system --no-create-home --shell /usr/sbin/nologin myapp
sudo mkdir -p /opt/myapp /var/log/myapp
sudo tee /opt/myapp/server.sh >/dev/null <<'EOS'
#!/usr/bin/env bash
trap 'echo "$(date -Is) got SIGTERM, shutting down gracefully"; exit 0' TERM
trap 'echo "$(date -Is) got SIGHUP, reloading config"' HUP
echo "$(date -Is) myapp started, PID=$$, ENV=${APP_ENV:-none}"
while true; do
  echo "$(date -Is) heartbeat"
  sleep 5
done
EOS
sudo chmod +x /opt/myapp/server.sh
sudo chown -R myapp:myapp /opt/myapp /var/log/myapp

# 3. Unit-файл
sudo tee /etc/systemd/system/myapp.service >/dev/null <<'EOS'
[Unit]
Description=My Demo Application
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=myapp
Group=myapp
WorkingDirectory=/opt/myapp
Environment="APP_ENV=production"
ExecStart=/opt/myapp/server.sh
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal
SyslogIdentifier=myapp
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=/var/log/myapp

[Install]
WantedBy=multi-user.target
EOS

# 4. Запуск
sudo systemd-analyze verify /etc/systemd/system/myapp.service
sudo systemctl daemon-reload
sudo systemctl enable --now myapp
systemctl status myapp
journalctl -u myapp -n 20 --no-pager

# 5. Проверки
ps -o pid,user,cmd -C server.sh
systemctl show myapp -p MainPID,User,Restart,ExecStart
sudo systemctl reload myapp && journalctl -u myapp -n 5 --no-pager   # увидишь "reloading config"

# 6. Авто-восстановление после падения
PID=$(systemctl show -p MainPID --value myapp)
sudo kill -9 "$PID"
sleep 7; systemctl status myapp | head -5      # сервис поднялся сам

# 7. Drop-in override (правильная правка чужого юнита)
sudo systemctl edit myapp
#   вписать:
#   [Service]
#   Environment="LOG_LEVEL=debug"
sudo systemctl restart myapp
systemctl cat myapp          # видно основной файл + override
systemctl show myapp -p Environment

# 8. Таймер
sudo tee /etc/systemd/system/hello.service >/dev/null <<'EOS'
[Unit]
Description=Hello oneshot
[Service]
Type=oneshot
ExecStart=/bin/bash -c 'echo "hello from timer at $(date -Is)"'
EOS
sudo tee /etc/systemd/system/hello.timer >/dev/null <<'EOS'
[Unit]
Description=Run hello every minute
[Timer]
OnCalendar=*:*:00
Persistent=true
[Install]
WantedBy=timers.target
EOS
sudo systemctl daemon-reload && sudo systemctl enable --now hello.timer
systemctl list-timers --all | head
sleep 65; journalctl -u hello -n 5 --no-pager

# 9. Уборка
sudo systemctl disable --now myapp hello.timer
sudo rm -rf /etc/systemd/system/myapp.service /etc/systemd/system/myapp.service.d \
            /etc/systemd/system/hello.{service,timer}
sudo systemctl daemon-reload
sudo userdel myapp; sudo rm -rf /opt/myapp /var/log/myapp
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `systemctl status X` | Состояние + хвост лога ← начинай отсюда |
| `systemctl start\|stop\|restart\|reload X` | Управление |
| `systemctl enable --now X` | Автозапуск + старт |
| `systemctl disable X` / `mask X` | Убрать автозапуск / запретить полностью |
| `systemctl --failed` | Что упало |
| `systemctl cat X` / `show X` | Unit-файл / все свойства |
| `systemctl edit X` | Drop-in override (правильная правка) |
| `systemctl daemon-reload` | **После любой правки юнита** |
| `systemctl list-units --type=service` | Список сервисов |
| `systemctl list-timers` | Таймеры |
| `systemctl list-dependencies X` | Дерево зависимостей |
| `systemd-analyze verify X.service` | Проверить синтаксис |
| `journalctl -u X -f` / `-xe` | Логи сервиса |
| `systemctl isolate rescue.target` | Сменить режим |
| `systemctl reboot\|poweroff\|suspend` | Питание |

---

## 🧠 Что запомнить

1. systemd — **PID 1**: запускает сервисы параллельно по зависимостям, следит за ними, ведёт логи.
2. Свои юниты — в `/etc/systemd/system/`; пакетные (`/lib/systemd/system/`) **не правят** —
   для изменений `systemctl edit` (drop-in).
3. **`daemon-reload` после каждой правки** unit-файла, иначе systemd работает со старой версией.
4. `Type=simple` для процессов на переднем плане, `forking` — для классических демонов,
   `oneshot` — для скриптов.
5. `enable` ≠ `start`. `enable --now` делает оба.
6. `mask` — запрет даже ручного запуска (жёстче, чем `disable`).
7. `reload` (без разрыва соединений) предпочтительнее `restart` там, где поддерживается.
8. `Restart=on-failure` + `RestartSec` — бесплатная отказоустойчивость.
9. Сервис должен работать под **непривилегированным пользователем** (`User=`).
10. Таймеры systemd — современная замена cron: логи, зависимости, `Persistent=`.
11. Алгоритм отладки: `status` → `journalctl -u` → `systemctl cat` → запуск руками от того же юзера.

➡️ Дальше: [14. Process Utilization](/linux/14-process-utilization)

---

## Задачи

> `vagrant snapshot save before_13 && vagrant ssh`
> ⭐ Самая важная практическая тема. Задачи блока C делай обязательно — это ровно то,
> что просят на собеседовании и делают на работе каждый день.

---

### Блок A. Теория

**A1.** Что такое init и почему его PID всегда 1?

<details><summary>Ответ</summary>

init — первый процесс, который ядро запускает в user space после монтирования корня;
он получает PID 1, становится предком всех процессов, усыновляет сирот, «подбирает» зомби и
отвечает за запуск и остановку всей системы.

</details>

**A2.** Как работал SysV init? Что такое runlevel и что означают симлинки `S20nginx` / `K80nginx`?

<details><summary>Ответ</summary>

SysV запускал скрипты из `/etc/init.d/` в порядке номеров симлинков в каталоге текущего
runlevel. Runlevel — режим работы системы (0 — выключение, 1 — single, 3 — многопользовательский,
5 — графика, 6 — reboot). `S20nginx` — Start c приоритетом 20 (чем меньше номер, тем раньше),
`K80nginx` — Kill при выходе из уровня.

</details>

**A3.** Назови 4 проблемы SysV init, которые решил systemd.

<details><summary>Ответ</summary>

(1) Последовательный запуск → долгая загрузка; systemd стартует параллельно по
зависимостям. (2) Нет отслеживания состояния: если процесс упал, никто не заметит; systemd
следит и умеет перезапускать. (3) Логика разбросана по bash-скриптам в каждом пакете; у systemd —
декларативные unit-файлы. (4) Нет надёжного контроля дочерних процессов; systemd использует
cgroups и гарантированно останавливает всю группу. Плюс единое логирование (journald), таймеры,
сокет-активация, лимиты и sandboxing.

</details>

**A4.** Что такое unit? Назови 6 типов юнитов и для чего каждый.

<details><summary>Ответ</summary>

Unit — управляемая systemd сущность. `.service` — демон/процесс; `.socket` — сокет с
активацией по обращению; `.timer` — запуск по расписанию; `.mount` — точка монтирования;
`.target` — группа юнитов (аналог runlevel); `.path` — реакция на изменения файлов;
также `.device`, `.slice`, `.scope`.

</details>

**A5.** Три каталога юнитов systemd и их приоритет. Почему нельзя править файлы в `/lib/systemd/system/`?

<details><summary>Ответ</summary>

`/etc/systemd/system/` (наивысший приоритет, твои юниты и override),
`/run/systemd/system/` (временные, создаются на лету), `/lib/systemd/system/` (из пакетов).
Файлы в `/lib` перезаписываются при обновлении пакета — правки пропадут; поэтому изменения
делают через `systemctl edit` (drop-in в `/etc/systemd/system/<unit>.d/`).

</details>

**A6.** Чем `enable` отличается от `start`? А `disable` от `mask`?

<details><summary>Ответ</summary>

`start` запускает сервис **сейчас**, `enable` создаёт симлинк для автозапуска
**при загрузке** (но не запускает). `disable` убирает автозапуск, но вручную запустить можно.
`mask` делает симлинк на `/dev/null`: сервис невозможно запустить ни вручную, ни по зависимости.

</details>

**A7.** Чем `restart` отличается от `reload`? Когда какой использовать в проде?

<details><summary>Ответ</summary>

`restart` останавливает и запускает процесс заново — обрыв соединений и короткий простой.
`reload` посылает сервису сигнал (обычно SIGHUP) или выполняет `ExecReload`, и тот перечитывает
конфигурацию **без остановки**. В проде: `reload` для изменения конфигурации, `restart` —
для обновления бинарника или когда reload не поддерживается.

</details>

**A8.** Объясни разницу `Type=simple`, `Type=forking`, `Type=oneshot`, `Type=notify`.
Что произойдёт, если демонизирующееся приложение запустить с `Type=simple`?

<details><summary>Ответ</summary>

`simple` — процесс остаётся на переднем плане, systemd считает его запущенным сразу.
`forking` — процесс делает fork и родитель завершается; systemd ждёт выхода родителя и отслеживает
потомка (нужен `PIDFile=`). `oneshot` — выполняется и завершается (скрипты, миграции), обычно с
`RemainAfterExit=yes`. `notify` — приложение само сообщает о готовности через `sd_notify()`,
что даёт точный момент старта зависимых сервисов.
Если демонизирующееся приложение описать как `simple`, systemd увидит завершение родителя
и решит, что сервис упал: пометит `failed` и (при Restart=) начнёт бесконечно перезапускать.

</details>

**A9.** Чем `After=` отличается от `Requires=`? А `Wants=` от `Requires=`?

<details><summary>Ответ</summary>

`After=` задаёт только **порядок** запуска, не создавая зависимости: если указанный юнит
не запущен, наш всё равно стартует. `Requires=` — жёсткая зависимость: при невозможности
запустить или при остановке зависимости наш юнит тоже останавливается. `Wants=` — мягкая:
systemd попытается запустить зависимость, но её сбой не помешает нашему сервису.
Обычно используют `Wants=` + `After=`.

</details>

**A10.** Что делает `WantedBy=multi-user.target` в секции `[Install]`?

<details><summary>Ответ</summary>

При `systemctl enable` будет создан симлинк в `multi-user.target.wants/`, то есть
сервис будет автоматически запускаться при достижении этого target — обычной многопользовательской
загрузки сервера.

</details>

**A11.** Почему обязательно делать `systemctl daemon-reload` после правки юнита?

<details><summary>Ответ</summary>

systemd хранит конфигурацию юнитов в памяти. Без `daemon-reload` он продолжит использовать
старую версию файла, и изменения не применятся (systemctl обычно предупреждает
«Warning: The unit file … changed on disk»).

</details>

**A12.** Чем systemd-таймеры лучше cron? Что делает `Persistent=true`?

<details><summary>Ответ</summary>

У таймеров: логи запусков в journald, зависимости от других юнитов, ограничения ресурсов
и sandboxing, точный контроль через `systemctl list-timers`, календарные выражения с проверкой
(`systemd-analyze calendar`), `RandomizedDelaySec` для размазывания нагрузки.
`Persistent=true` означает, что пропущенный (пока машина была выключена) запуск будет выполнен
сразу после загрузки — cron так не умеет (для этого нужен anacron).

</details>

**A13.** Что означают опции `ProtectSystem=strict`, `PrivateTmp=yes`, `NoNewPrivileges=yes`?

<details><summary>Ответ</summary>

`ProtectSystem=strict` монтирует всю ФС только для чтения, кроме `/dev`, `/proc`, `/sys`
и путей из `ReadWritePaths=`. `PrivateTmp=yes` даёт сервису собственный изолированный `/tmp`
(защита от атак через временные файлы). `NoNewPrivileges=yes` запрещает процессу и его потомкам
получать новые привилегии (блокирует эксплуатацию SUID-бинарников).

</details>

**A14.** Как соотносятся targets и runlevels? Какой target по умолчанию на сервере?

<details><summary>Ответ</summary>

Targets — замена runlevels: `poweroff`=0, `rescue`=1, `multi-user`=3, `graphical`=5,
`reboot`=6. На сервере по умолчанию — `multi-user.target` (без графики).

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  systemctl status nginx
B2.  systemctl is-active nginx; echo $?
B3.  systemctl enable --now nginx
B4.  systemctl mask nginx
B5.  systemctl --failed
B6.  systemctl cat sshd
B7.  systemctl show nginx -p MainPID,Restart,User
B8.  systemctl list-dependencies nginx
B9.  systemctl edit nginx
B10. systemctl revert nginx
B11. systemd-analyze verify /etc/systemd/system/myapp.service
B12. systemctl list-timers --all
B13. systemd-analyze calendar "Mon *-*-* 03:30:00"
B14. systemctl isolate rescue.target
B15. journalctl -u myapp -p err --since today
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Состояние сервиса, PID, потребление ресурсов, cgroup и последние строки лога.
B2.  active/inactive и код возврата: 0 — работает, ненулевой — нет (для скриптов).
B3.  Включает автозапуск и сразу стартует сервис.
B4.  Делает запуск невозможным (симлинк на /dev/null), в том числе по зависимостям.
B5.  Список юнитов в состоянии failed.
B6.  Печатает содержимое unit-файла (и всех drop-in override).
B7.  Показывает выбранные свойства: PID главного процесса, политику рестарта, пользователя.
B8.  Дерево зависимостей юнита.
B9.  Открывает редактор для создания drop-in override в /etc/systemd/system/nginx.service.d/.
B10. Удаляет все override и возвращает юнит к версии из пакета.
B11. Проверяет unit-файл на синтаксические ошибки и неизвестные директивы.
B12. Все таймеры с временем следующего и последнего запуска.
B13. Разбирает календарное выражение и показывает ближайшие срабатывания — проверка расписания.
B14. Переключает систему в аварийный режим (остановит сеть и SSH!).
B15. Ошибки конкретного сервиса за сегодня.
```

</details>

**B16.** Что покажет `systemctl status` в поле `Active:` для сервиса, который:
запущен / остановлен вручную / упал / был замаскирован / является `oneshot` и завершился?

<details><summary>Ответ</summary>

Запущен — `active (running)`; остановлен вручную — `inactive (dead)`;
упал — `failed (Result: exit-code)` с указанием кода; замаскирован — `masked`
(и попытка старта даёт «Unit is masked»); завершившийся `oneshot` —
`inactive (dead)` или `active (exited)` при `RemainAfterExit=yes`.

</details>

---

### Блок C. Практика

#### C1. 🔑 Свой сервис с нуля (главное задание)

Напиши приложение и оформи его как systemd-сервис со следующими требованиями:

- приложение (`/opt/counter/app.sh`) пишет в лог строку со счётчиком раз в 3 секунды;
- работает под системным пользователем `counter` (без домашнего каталога и логина);
- корректно обрабатывает SIGTERM (пишет «shutting down» и выходит с кодом 0);
- по SIGHUP перечитывает «конфиг» (выводит сообщение);
- переменная окружения `INTERVAL` берётся из `/etc/counter/env`;
- автоматически перезапускается при падении через 5 секунд;
- логи идут в journald с идентификатором `counter`;
- лимит открытых файлов — 65535;
- включены `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, запись разрешена только в `/var/log/counter`;
- запускается автоматически при загрузке системы.

**Критерии приёмки:**
1. `systemctl status counter` — active (running), под юзером `counter`.
2. `journalctl -u counter -f` показывает строки.
3. `kill -9 <MainPID>` → через 5 секунд сервис снова работает.
4. `systemctl reload counter` → в логе сообщение о reload.
5. `systemctl stop counter` → в логе «shutting down», код выхода 0 (не 143!).
6. После `reboot` сервис поднялся сам.
7. `systemd-analyze verify` не выдаёт ошибок.

<details><summary>Ответ</summary>

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin counter
sudo mkdir -p /opt/counter /var/log/counter /etc/counter
echo 'INTERVAL=3' | sudo tee /etc/counter/env

sudo tee /opt/counter/app.sh >/dev/null <<'EOS'
#!/usr/bin/env bash
trap 'echo "$(date -Is) shutting down gracefully"; exit 0' TERM
trap 'echo "$(date -Is) config reloaded"' HUP
i=0
echo "$(date -Is) counter started, pid=$$, interval=${INTERVAL:-5}"
while true; do
  i=$((i+1))
  echo "$(date -Is) tick #$i"
  sleep "${INTERVAL:-5}"
done
EOS
sudo chmod +x /opt/counter/app.sh
sudo chown -R counter:counter /opt/counter /var/log/counter

sudo tee /etc/systemd/system/counter.service >/dev/null <<'EOS'
[Unit]
Description=Counter demo service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=counter
Group=counter
WorkingDirectory=/opt/counter
EnvironmentFile=-/etc/counter/env
ExecStart=/opt/counter/app.sh
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5s
TimeoutStopSec=15s
LimitNOFILE=65535
StandardOutput=journal
StandardError=journal
SyslogIdentifier=counter
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=/var/log/counter

[Install]
WantedBy=multi-user.target
EOS

sudo systemd-analyze verify /etc/systemd/system/counter.service
sudo systemctl daemon-reload
sudo systemctl enable --now counter
systemctl status counter
journalctl -u counter -n 10 --no-pager
sudo kill -9 "$(systemctl show -p MainPID --value counter)"; sleep 7; systemctl status counter | head -4
sudo systemctl reload counter && journalctl -u counter -n 3 --no-pager
sudo systemctl stop counter && journalctl -u counter -n 3 --no-pager
```

</details>

#### C2. Type= на практике

Напиши два скрипта: один остаётся на переднем плане,
второй демонизируется (`&` + выход родителя). Оформи оба юнитами, специально укажи
неправильный `Type=` и посмотри, что произойдёт. Затем исправь.

<details><summary>Ответ</summary>

Демонизирующийся скрипт с `Type=simple` даёт `Active: failed` или бесконечный рестарт,
потому что systemd считает завершение родителя падением сервиса. Исправление — `Type=forking`
(и желательно `PIDFile=`), либо запретить демонизацию (`--foreground`, `-D FOREGROUND` и т.п.) —
для контейнеров и systemd это предпочтительный путь.

</details>

#### C3. Зависимости

Создай два сервиса: `db-fake` и `app-fake`, где `app-fake`:
- запускается **после** `db-fake`;
- **требует** его (при падении `db-fake` должен останавливаться и `app-fake`).

Проверь поведение: останови `db-fake` и посмотри, что стало с `app-fake`.
Затем замени `Requires=` на `Wants=` и повтори — объясни разницу.

<details><summary>Ответ</summary>

При `Requires=db-fake.service` + `After=db-fake.service` остановка `db-fake`
(`systemctl stop db-fake`) останавливает и `app-fake`. При `Wants=` `app-fake` продолжит работать —
зависимость «желательная», её сбой не влияет на наш сервис.

</details>

#### C4. Drop-in override

Не трогая оригинальный unit-файл `ssh`:
- измени `Restart=` на `always`;
- добавь переменную окружения;
- покажи результат через `systemctl cat ssh`;
- откати изменения одной командой.

<details><summary>Ответ</summary>

```bash
sudo systemctl edit ssh
# [Service]
# Restart=always
# Environment="DEBUG_LEVEL=1"
sudo systemctl daemon-reload
systemctl cat ssh
sudo systemctl revert ssh
```

</details>

#### C5. Таймер вместо cron

Сделай задачу, которая каждые 2 минуты пишет в лог размер `/var/log`:
1. `.service` типа `oneshot`;
2. `.timer` с `OnCalendar` и `Persistent=true`;
3. проверь через `systemctl list-timers`;
4. убедись, что записи появляются в journald;
5. покажи, как выполнить задачу немедленно, не дожидаясь таймера.

<details><summary>Ответ</summary>

```bash
sudo tee /etc/systemd/system/logsize.service >/dev/null <<'EOS'
[Unit]
Description=Report /var/log size
[Service]
Type=oneshot
ExecStart=/bin/bash -c 'echo "/var/log size: $(du -sh /var/log | cut -f1)"'
EOS
sudo tee /etc/systemd/system/logsize.timer >/dev/null <<'EOS'
[Unit]
Description=Run logsize every 2 minutes
[Timer]
OnCalendar=*:0/2
Persistent=true
[Install]
WantedBy=timers.target
EOS
sudo systemctl daemon-reload && sudo systemctl enable --now logsize.timer
systemctl list-timers logsize.timer
sudo systemctl start logsize.service       # выполнить немедленно
journalctl -u logsize -n 5 --no-pager
```

</details>

#### C6. Отладка сломанного сервиса

Создай юнит с **тремя** ошибками
(неверный путь в `ExecStart`, несуществующий `User`, отсутствующий `WorkingDirectory`).
Запусти и почини по одной, каждый раз фиксируя, **как именно** ошибка проявилась в
`systemctl status` и `journalctl`.

<details><summary>Ответ</summary>

Характерные проявления:
- неверный путь в `ExecStart` → `status=203/EXEC`, в логе «Failed to locate executable»;
- несуществующий `User=` → `status=217/USER`;
- отсутствующий `WorkingDirectory=` → `status=200/CHDIR`.
Именно по этим кодам и ищут проблему; `systemd-analyze verify` ловит часть ошибок заранее.

</details>

#### C7. Targets

Выясни:
- текущий target по умолчанию;
- какие юниты входят в `multi-user.target`;
- сколько юнитов в системе всего, сколько включено, сколько упало;
- переключись в `rescue.target` и вернись обратно (⚠️ только если есть доступ к консоли ВМ!).

<details><summary>Ответ</summary>

```bash
systemctl get-default
systemctl list-dependencies multi-user.target | head -30
systemctl list-units --all --no-legend | wc -l
systemctl list-unit-files --state=enabled --no-legend | wc -l
systemctl --failed --no-legend | wc -l
```

</details>

#### C8. Анализ загрузки

Найди 5 самых медленных сервисов при загрузке, определи,
какие из них можно безопасно отключить на сервере, и отключи один из них.
Перезагрузись и сравни время загрузки до/после.

<details><summary>Ответ</summary>

```bash
systemd-analyze blame | head -5
systemd-analyze critical-chain
sudo systemctl disable --now snapd.service snapd.socket    # пример: часто не нужен на сервере
systemd-analyze                                            # сравнить до/после ребута
```

</details>

#### C9. Скрипт мониторинга сервисов

Напиши `/vagrant/service_report.sh`:
```text:no-line-numbers
=== SERVICE REPORT ===
Running: 42   Failed: 1   Enabled: 38
--- FAILED UNITS ---
myapp.service  (exit code 203/EXEC)
--- CRITICAL SERVICES ---
ssh        : active   enabled
cron       : active   enabled
systemd-journald : active  static
--- RECENTLY RESTARTED (last 1h) ---
--- TIMERS NEXT RUN ---
```

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
echo "=== SERVICE REPORT ==="
run=$(systemctl list-units --type=service --state=running --no-legend | wc -l)
fail=$(systemctl --failed --no-legend | wc -l)
en=$(systemctl list-unit-files --state=enabled --no-legend | wc -l)
echo "Running: $run   Failed: $fail   Enabled: $en"
echo "--- FAILED UNITS ---"
systemctl --failed --no-legend || echo "none"
echo "--- CRITICAL SERVICES ---"
for s in ssh cron systemd-journald systemd-timesyncd; do
  printf '%-20s : %-8s %s\n' "$s" "$(systemctl is-active "$s" 2>/dev/null)" "$(systemctl is-enabled "$s" 2>/dev/null)"
done
echo "--- RECENTLY RESTARTED (last 1h) ---"
journalctl --since "1 hour ago" -p info --no-pager -q | grep -i "Started\|Stopping" | tail -10
echo "--- TIMERS NEXT RUN ---"
systemctl list-timers --no-pager --no-legend | head -5
```

</details>

#### C10. Миграция с cron на systemd-timer

Возьми cron-задачу
`*/10 * * * * /opt/scripts/check.sh >> /var/log/check.log 2>&1`
и переведи её на systemd-таймер. Объясни, что изменится в логировании и как теперь смотреть
историю запусков.

<details><summary>Ответ</summary>

```ini
# /etc/systemd/system/check.service
[Unit]
Description=Periodic check
[Service]
Type=oneshot
ExecStart=/opt/scripts/check.sh
# /etc/systemd/system/check.timer
[Timer]
OnCalendar=*:0/10
Persistent=true
[Install]
WantedBy=timers.target
```

Изменения: вывод скрипта уходит **в journald**, а не в файл — смотреть `journalctl -u check`
(с фильтрами по времени и уровню, с автоматической ротацией). История запусков и следующий
запуск видны в `systemctl list-timers`; результат последнего выполнения — в
`systemctl status check.service`. Не нужно самому управлять перенаправлением и ротацией лога.

</details>

---

### Блок D. Инциденты

**D1.** `systemctl start myapp` завершается без ошибок, но `systemctl status myapp` показывает
`inactive (dead)` сразу после запуска. Приложение при этом руками стартует нормально. Диагноз?

<details><summary>Ответ</summary>

Приложение демонизируется (уходит в фон), а в юните `Type=simple`. systemd видит,
что главный процесс завершился, и считает сервис остановленным. Решение: `Type=forking` +
`PIDFile=`, либо запускать приложение в foreground-режиме.
Также проверить, что `ExecStart` не запускает обёртку, которая сразу завершается.

</details>

**D2.** Сервис в состоянии `activating (auto-restart)` и бесконечно перезапускается.
Как это диагностировать и как временно остановить цикл?

<details><summary>Ответ</summary>

`journalctl -u myapp -n 100` — смотреть причину падения; `systemctl status` — код выхода.
Временно остановить цикл: `systemctl stop myapp` (а если поднимается снова — `systemctl mask myapp`).
Для защиты от бесконечных рестартов в юните задают `StartLimitIntervalSec=`/`StartLimitBurst=`,
после превышения systemd переводит юнит в failed и прекращает попытки
(сброс — `systemctl reset-failed myapp`).

</details>

**D3.** В status видно: `Active: failed (Result: exit-code) status=203/EXEC`. Что означает 203?

<details><summary>Ответ</summary>

`203/EXEC` — systemd не смог выполнить файл из `ExecStart`: неверный путь, нет бита
исполнения, отсутствует интерпретатор в shebang, либо файл недоступен из-за sandbox-опций
(`ProtectSystem`). Проверить: `ls -l`, `file`, `head -1` (shebang), `systemctl cat`.

</details>

**D4.** Разработчик отредактировал `/lib/systemd/system/myapp.service`, всё заработало.
После `apt upgrade` настройки пропали. Объясни и предложи правильный подход.

<details><summary>Ответ</summary>

Файлы в `/lib/systemd/system/` принадлежат пакету и перезаписываются при обновлении.
Правильно: `systemctl edit myapp` (drop-in `/etc/systemd/system/myapp.service.d/override.conf`)
для частичных изменений или `systemctl edit --full myapp` — копия в `/etc/systemd/system/`,
которая имеет приоритет и переживает обновления.

</details>

**D5.** После деплоя приложение стартует до того, как поднялась сеть, и падает с
`bind: cannot assign requested address`. Как исправить средствами systemd?

<details><summary>Ответ</summary>

Добавить `After=network-online.target` **и** `Wants=network-online.target`
(одного `After=` мало — таргет должен быть затребован), убедиться, что включён
`systemd-networkd-wait-online`/`NetworkManager-wait-online`. Дополнительно помогают
`Restart=on-failure` с `RestartSec` и, если приложение умеет, `sysctl net.ipv4.ip_nonlocal_bind=1`
для привязки к ещё не поднятому адресу (в кластерных сценариях с VIP).

</details>

**D6.** `systemctl stop myapp` висит 90 секунд, потом сервис всё же останавливается.
В логах `Killing process ... with signal SIGKILL`. Что происходит и как починить?

<details><summary>Ответ</summary>

Приложение не обрабатывает SIGTERM и не завершается; systemd ждёт `TimeoutStopSec`
(по умолчанию 90 с) и добивает SIGKILL. Починка: реализовать обработчик SIGTERM в приложении
(graceful shutdown), задать разумный `TimeoutStopSec=`, при необходимости `KillMode=mixed`
и корректный `ExecStop=`. Заодно это лечит долгие деплои и 5xx при рестартах.

</details>

**D7.** Сервис работает от root, хотя в юните написано `User=appuser`.
Две возможные причины.

<details><summary>Ответ</summary>

(1) Не выполнен `daemon-reload` после правки, работает старая версия юнита.
(2) Правка внесена не в тот файл (например, есть drop-in или `--full` копия в `/etc`,
которая перекрывает). Проверить `systemctl cat myapp` и `systemctl show myapp -p User`.
Третий вариант — сервис запускает обёртку, которая сама делает `su`/`sudo` в root.

</details>

**D8.** После перезагрузки сервис не поднялся, хотя `systemctl start` работает вручную.
Что забыли?

<details><summary>Ответ</summary>

Забыли `systemctl enable myapp` — сервис не подключён к `multi-user.target`.
Проверить `systemctl is-enabled myapp` и наличие секции `[Install]` в юните
(без неё `enable` работать не будет).

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое systemd и чем он лучше SysV init?

<details><summary>Ответ</summary>

Система инициализации и менеджер сервисов, PID 1. Лучше SysV: параллельный запуск по
зависимостям, отслеживание состояния и авто-рестарт, декларативные unit-файлы вместо
bash-скриптов, cgroups для контроля процессов, единое логирование (journald), таймеры,
сокет-активация, sandboxing.

</details>

**2.** Как создать свой сервис? Опиши структуру unit-файла.

<details><summary>Ответ</summary>

Создать `/etc/systemd/system/name.service` с секциями `[Unit]` (описание, зависимости),
`[Service]` (Type, User, ExecStart, Restart), `[Install]` (WantedBy), затем
`daemon-reload` и `enable --now`.

</details>

**3.** Чем `enable` отличается от `start`?

<details><summary>Ответ</summary>

`start` — запустить сейчас; `enable` — включить автозапуск при загрузке. Вместе — `enable --now`.

</details>

**4.** Что делает `daemon-reload` и когда он нужен?

<details><summary>Ответ</summary>

Перечитывает unit-файлы с диска в память systemd. Нужен после создания или изменения любого юнита.

</details>

**5.** Как посмотреть логи конкретного сервиса?

<details><summary>Ответ</summary>

`journalctl -u <unit>` (+ `-f`, `-n 50`, `-p err`, `--since`).

</details>

**6.** Как настроить автоперезапуск при падении?

<details><summary>Ответ</summary>

`Restart=on-failure` (или `always`) и `RestartSec=5s`; ограничить частоту через
`StartLimitIntervalSec`/`StartLimitBurst`.

</details>

**7.** Что такое target и какой обычно используют на сервере?

<details><summary>Ответ</summary>

Target — группа юнитов, определяющая состояние системы (замена runlevel).
На сервере — `multi-user.target`.

</details>

**8.** Чем systemd-timer лучше cron?

<details><summary>Ответ</summary>

Логи в journald, зависимости от других юнитов, ограничения ресурсов и sandbox,
`Persistent=` для пропущенных запусков, точный контроль через `list-timers`,
проверяемые календарные выражения.

</details>

**9.** Как безопасно изменить unit-файл, установленный пакетом?

<details><summary>Ответ</summary>

Через `systemctl edit <unit>` — создаётся drop-in в `/etc/systemd/system/<unit>.d/override.conf`,
который переживает обновление пакета; полная копия — `systemctl edit --full`.

</details>

---

### 🎯 Чек-лист

- [ ] Написал рабочий unit-файл с нуля, включая User, Restart и sandbox-опции
- [ ] Помню про `daemon-reload` после каждой правки
- [ ] Понимаю `Type=simple` vs `forking` vs `oneshot`
- [ ] Знаю разницу `enable`/`start`/`mask` и `restart`/`reload`
- [ ] Правлю чужие юниты только через `systemctl edit`
- [ ] Умею читать коды 203/EXEC, 217/USER, 200/CHDIR
- [ ] Сделал systemd-таймер вместо cron
- [ ] Отлаживаю сервис по алгоритму status → journalctl → cat → запуск вручную
