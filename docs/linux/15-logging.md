---
title: "15. Логирование"
description: "journald, rsyslog, logrotate: куда текут логи в Linux, уровни severity, ротация, разбор инцидентов"
---

# 15. Logging — логи, journald, rsyslog, logrotate

> Источник: `15_logging.txt` (Journeyman, 6 уроков)
> **После темы ты умеешь:** быстро находить нужное в логах, работать с journald и rsyslog,
> настраивать ротацию и расследовать инциденты. Логи — главный источник правды при разборе аварии.

---

## 🗺️ Схема: куда текут логи в современном Linux

```text:no-line-numbers
  ПРИЛОЖЕНИЯ              ЯДРО                  systemd-юниты        SSH/sudo/PAM
   (nginx, app)        (dmesg, ring buffer)     (stdout/stderr)      (auth)
        │                      │                       │                  │
        │                      ▼                       ▼                  │
        │              ┌──────────────────────────────────────────────────▼──┐
        │              │        systemd-journald  (бинарный журнал)          │
        │              │   /run/log/journal (в памяти) или                    │
        │              │   /var/log/journal (постоянно, если каталог создан)  │
        │              └───────────────┬──────────────────────────────────────┘
        │                              │ пересылка
        ▼                              ▼
  ┌──────────────┐            ┌─────────────────┐
  │ Свои файлы   │            │    rsyslog      │ ──────► /var/log/syslog
  │ /var/log/    │            │ (текстовые логи)│ ──────► /var/log/auth.log
  │ nginx/*.log  │            └────────┬────────┘ ──────► /var/log/kern.log
  └──────┬───────┘                     │
         │                             └──────► удалённый лог-сервер (TCP/UDP 514)
         ▼
   ┌──────────────────────────────────────────────────────────┐
   │  logrotate — ротация, сжатие, удаление старых логов      │
   └──────────────────────────────────────────────────────────┘
```

**Главное:** в systemd-системах основной приёмник — **journald** (бинарный, с метаданными),
а **rsyslog** дублирует часть событий в привычные текстовые файлы `/var/log/*.log`.

---

## 1. System Logging — что где лежит

```bash
ls -lrt /var/log/          # ⭐ первое движение при инциденте: что менялось последним
```

| Файл | Что внутри |
|------|-----------|
| `/var/log/syslog` (Debian) / `messages` (RHEL) | Общий поток системных сообщений |
| `/var/log/auth.log` (Debian) / `secure` (RHEL) | **Аутентификация**: SSH, sudo, su, PAM |
| `/var/log/kern.log` | Сообщения ядра |
| `/var/log/dmesg` | Буфер ядра на момент загрузки |
| `/var/log/boot.log` | Процесс загрузки |
| `/var/log/dpkg.log`, `/var/log/apt/history.log` | Установка/удаление пакетов |
| `/var/log/nginx/{access,error}.log` | Веб-сервер |
| `/var/log/journal/` | Бинарный журнал systemd |
| `/var/log/wtmp`, `/btmp`, `/lastlog` | Входы (успешные/неуспешные) — **бинарные** |

⚠️ `wtmp`/`btmp` — бинарные, `cat` бесполезен. Читать через `last`, `lastb`, `lastlog`.

---

## 2. syslog — стандарт и уровни

**Facility** (источник) и **Severity** (важность) — классификация из RFC 5424.

Facility: `auth`, `authpriv`, `cron`, `daemon`, `kern`, `mail`, `syslog`, `user`, `local0`-`local7`.

**Severity — выучить обязательно:**

| № | Уровень | Когда |
|---|---------|-------|
| 0 | **emerg** | Система непригодна |
| 1 | **alert** | Нужно действие немедленно |
| 2 | **crit** | Критическая ситуация |
| 3 | **err** | Ошибка ← **отсюда обычно начинают смотреть** |
| 4 | **warning** | Предупреждение |
| 5 | notice | Нормальное, но значимое |
| 6 | **info** | Информация |
| 7 | **debug** | Отладка (в проде выключено) |

Мнемоника: «Every Awesome Chef Eats With Nice Idle Dishes» (emerg, alert, crit, err, warning,
notice, info, debug).

### rsyslog

```bash
cat /etc/rsyslog.conf
ls /etc/rsyslog.d/
sudo systemctl status rsyslog
```

Правила:
```text:no-line-numbers
auth,authpriv.*              /var/log/auth.log
*.*;auth,authpriv.none       -/var/log/syslog     # '-' = писать асинхронно (быстрее)
kern.*                       -/var/log/kern.log
mail.err                     /var/log/mail.err
local0.*                     /var/log/myapp.log   # свой канал для приложения
*.emerg                      :omusrmsg:*          # всем залогиненным пользователям
*.*                          @@logserver:514      # @@ = TCP, @ = UDP (централизация)
```

```bash
logger "тестовое сообщение"                        # отправить в syslog
logger -p local0.err -t myapp "ошибка подключения"  # с facility/severity/тегом
tail -5 /var/log/syslog
```
`logger` — правильный способ логировать из bash-скриптов: сообщение попадает в общий поток
с метаданными, а не в случайный файл.

---

## 3. General Logging — journald (главный инструмент)

```bash
journalctl                       # всё с начала (в pager)
journalctl -e                    # сразу в конец
journalctl -f                    # follow (как tail -f)
journalctl -n 50                 # последние 50 строк
journalctl -r                    # в обратном порядке (свежие сверху)

# ФИЛЬТРЫ — это главное
journalctl -u nginx              # ⭐ по юниту
journalctl -u nginx -u php-fpm   # несколько юнитов
journalctl -p err                # по уровню: err и выше
journalctl -p warning..err       # диапазон
journalctl -k                    # только ядро
journalctl -b                    # текущая загрузка
journalctl -b -1                 # ⭐ предыдущая загрузка (после внезапного ребута)
journalctl --list-boots

# ВРЕМЯ
journalctl --since "2026-09-13 10:00" --until "2026-09-13 11:00"
journalctl --since "1 hour ago"
journalctl --since today
journalctl --since yesterday --until "03:00"

# ПРОЧЕЕ
journalctl _PID=1234
journalctl _UID=1000
journalctl /usr/sbin/sshd        # по исполняемому файлу
journalctl -u myapp -o json-pretty    # все метаданные записи
journalctl -o short-precise           # с микросекундами
journalctl -xe                   # ⭐ последние события + пояснения (при падении сервиса)
journalctl -u nginx --grep "502"      # поиск по regex (systemd 237+)

# ОБСЛУЖИВАНИЕ
journalctl --disk-usage
sudo journalctl --vacuum-size=200M    # ужать журнал до 200 МБ
sudo journalctl --vacuum-time=7d      # оставить только за 7 дней
journalctl --verify
```

**Сделать журнал постоянным** (по умолчанию в Ubuntu он может жить только в `/run` и теряться
при перезагрузке — это критично при разборе инцидентов):
```bash
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
sudo systemctl restart systemd-journald
# или в /etc/systemd/journald.conf:
#   Storage=persistent
#   SystemMaxUse=500M
#   MaxRetentionSec=1month
```

**Почему journald удобнее текстовых логов:** структурированные поля (можно фильтровать по юниту,
PID, UID, приоритету), единое время, автоматическая ротация, защита от подмены, единый интерфейс
для ядра, systemd и приложений.

---

## 4. Kernel Logging

```bash
dmesg                      # кольцевой буфер ядра
dmesg -T                   # ⭐ с человекочитаемым временем
dmesg -w                   # follow
dmesg -l err,crit          # по уровню
dmesg -H                   # с пейджером и цветом
dmesg | grep -i -E "error|fail|oom|i/o"

journalctl -k              # то же через journald
journalctl -k -b -1        # ядро предыдущей загрузки
cat /var/log/kern.log
```

Что ищем в dmesg при инцидентах:

| Строка | Значит |
|--------|--------|
| `Out of memory: Killed process` | Сработал OOM killer |
| `blk_update_request: I/O error` | Проблема с диском |
| `EXT4-fs error` | Повреждение ФС |
| `nf_conntrack: table full` | Переполнена таблица соединений |
| `TCP: request_sock_TCP: Possible SYN flooding` | SYN-флуд или маленький backlog |
| `Hardware Error` / `MCE` | Аппаратная ошибка (память, CPU) |
| `segfault at ... ip ...` | Падение приложения |

---

## 5. Authentication Logging — безопасность

```bash
sudo tail -50 /var/log/auth.log          # Debian/Ubuntu
sudo tail -50 /var/log/secure            # RHEL
journalctl -u ssh --since today
journalctl _COMM=sudo --since today

# Кто входил
last                      # успешные входы (wtmp)
last -n 20
last reboot               # история перезагрузок
lastb                     # НЕУДАЧНЫЕ попытки (btmp) ← только root
lastlog                   # последний вход каждого пользователя
who; w                    # кто сейчас
```

Боевые однострочники безопасности:
```bash
# Топ IP, брутфорсящих SSH
sudo grep "Failed password" /var/log/auth.log | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' \
  | sort | uniq -c | sort -rn | head

# Успешные входы: кто и откуда
sudo grep "Accepted" /var/log/auth.log | awk '{print $9, $11}' | sort | uniq -c | sort -rn

# Все команды через sudo за сегодня
sudo grep sudo /var/log/auth.log | grep COMMAND | tail -20

# Новые пользователи и изменения групп
sudo grep -E "useradd|usermod|groupadd" /var/log/auth.log
```

💼 Практика: `fail2ban` читает ровно эти логи и банит IP после N неудачных попыток.
Для прода — обязателен (плюс отключение парольной аутентификации в SSH).

---

## 6. Managing Log Files — logrotate

Без ротации логи заполнят диск. `logrotate` запускается по таймеру/cron и обслуживает логи.

```bash
cat /etc/logrotate.conf
ls /etc/logrotate.d/                 # по файлу на сервис
sudo logrotate -d /etc/logrotate.d/nginx      # ⭐ DEBUG: показать, что БЫ сделал
sudo logrotate -f /etc/logrotate.d/nginx      # принудительно прокрутить сейчас
cat /var/lib/logrotate/status                 # когда что ротировалось
systemctl status logrotate.timer
```

Своя конфигурация `/etc/logrotate.d/myapp`:
```text:no-line-numbers
/var/log/myapp/*.log {
    daily                 # частота: daily | weekly | monthly | size 100M
    rotate 14             # хранить 14 копий
    compress              # сжимать gzip
    delaycompress         # сжимать со второй ротации (файл ещё может писаться)
    missingok             # не ругаться, если файла нет
    notifempty            # не ротировать пустые
    create 0640 myapp myapp   # создать новый файл с такими правами
    sharedscripts         # postrotate выполнить один раз для всех файлов
    dateext               # имя вида myapp.log-20260913
    postrotate
        systemctl reload myapp >/dev/null 2>&1 || true
    endscript
}
```

🔑 **Ключевой нюанс — `copytruncate`:**
```text:no-line-numbers
copytruncate   # скопировать файл и ОБНУЛИТЬ оригинал (дескриптор сохраняется)
```
Нужен, если приложение не умеет переоткрывать лог по сигналу. Без этого после ротации
приложение продолжит писать в **удалённый** файл: логи пропадут, а место не освободится
(привет теме 10, `lsof +L1`).

Варианты корректной ротации:
1. Приложение умеет `SIGHUP`/`reload` → `postrotate ... reload`.
2. Не умеет → `copytruncate`.

---

## 🔧 Алгоритм разбора инцидента по логам

```text:no-line-numbers
1. Когда началось?               journalctl --since "X" --until "Y"
2. Что упало?                    systemctl --failed ; journalctl -p err -b
3. Логи конкретного сервиса      journalctl -u app --since "1 hour ago"
4. Ядро: OOM, диск, сеть         dmesg -T | tail -50 ; journalctl -k -b
5. Был ли ребут?                 journalctl --list-boots ; last reboot ; uptime
6. Кто что делал?                grep sudo /var/log/auth.log ; last
7. Что меняли?                   /var/log/apt/history.log ; find /etc -mmin -120
8. Корреляция по времени         сопоставить метки всех источников
```

---

## 💼 Как это в DevOps

- **Централизация логов обязательна**: ELK/OpenSearch, Loki + Promtail, или коммерческие решения.
  Логи на самом сервере пропадают вместе с сервером (особенно в автоскейлинге).
- **Структурированные логи (JSON)** — стандарт для приложений: удобно парсить и индексировать.
- **В контейнерах** приложение пишет в **stdout/stderr**, а не в файл: сбором занимается рантайм
  (`docker logs`, `kubectl logs`) и агент (fluent-bit/promtail).
- **Ротация** — обязательный пункт при выкатке любого сервиса, иначе диск кончится через месяц.
- `journalctl -u app --since` + `grep` — 80% реальной отладки на сервере.
- Логи аутентификации — источник для алертов безопасности и для расследований.

---

## 🧪 Мини-лаба

```bash
vagrant ssh

# 1. Обзор
ls -lrt /var/log/ | tail -20
sudo du -sh /var/log
journalctl --disk-usage

# 2. journald: фильтры
journalctl -n 20 --no-pager
journalctl -p err -b --no-pager | tail -20
journalctl -u ssh --since today --no-pager | tail -10
journalctl --list-boots
journalctl -k -b --no-pager | tail -10

# 3. Сделать журнал постоянным
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
sudo systemctl restart systemd-journald
journalctl --disk-usage

# 4. Свои сообщения через logger
logger "проверка связи из лабы"
logger -p local0.err -t mylab "искусственная ошибка"
sudo tail -5 /var/log/syslog
journalctl -t mylab --no-pager

# 5. Логи аутентификации
sudo tail -20 /var/log/auth.log
last -n 10
sudo lastb -n 10 2>/dev/null || echo "btmp пуст — неудачных входов не было"
sudo grep -c "Failed password" /var/log/auth.log || echo 0
sudo -u vagrant sudo ls /root >/dev/null 2>&1
sudo grep COMMAND /var/log/auth.log | tail -3

# 6. Ядро
dmesg -T | tail -20
dmesg -l err,warn | tail

# 7. logrotate — своя конфигурация
sudo mkdir -p /var/log/mylab
sudo bash -c 'for i in 1 2 3; do echo "line $i $(date)" >> /var/log/mylab/app.log; done'
sudo tee /etc/logrotate.d/mylab >/dev/null <<'EOS'
/var/log/mylab/*.log {
    daily
    rotate 5
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    dateext
}
EOS
sudo logrotate -d /etc/logrotate.d/mylab      # сухой прогон
sudo logrotate -f /etc/logrotate.d/mylab      # принудительно
ls -l /var/log/mylab/

# 8. Анализ: топ ошибок за сегодня
journalctl -p err --since today --no-pager | awk '{$1=$2=$3=""; print}' \
  | sort | uniq -c | sort -rn | head

# 9. Чистка журнала
sudo journalctl --vacuum-time=7d
journalctl --disk-usage

# 10. Уборка
sudo rm -f /etc/logrotate.d/mylab
sudo rm -rf /var/log/mylab
```

---

## 📌 Шпаргалка

| Задача | Команда |
|--------|---------|
| Что менялось в логах последним | `ls -lrt /var/log/` |
| Логи сервиса | `journalctl -u app -n 100` |
| Следить в реальном времени | `journalctl -u app -f` |
| Только ошибки | `journalctl -p err -b` |
| За период | `journalctl --since "1 hour ago" --until now` |
| Предыдущая загрузка | `journalctl -b -1` |
| Ядро | `journalctl -k` / `dmesg -T` |
| Разбор падения сервиса | `journalctl -xe` |
| Поиск по тексту | `journalctl -u app --grep "timeout"` |
| Размер журнала / чистка | `journalctl --disk-usage`, `--vacuum-size=200M` |
| Отправить в syslog | `logger -p local0.err -t tag "msg"` |
| Входы в систему | `last`, `lastb`, `lastlog`, `who` |
| Брутфорс SSH | `grep "Failed password" /var/log/auth.log` |
| Ротация: проверка | `logrotate -d /etc/logrotate.d/app` |
| Ротация: принудительно | `logrotate -f /etc/logrotate.d/app` |

---

## 🧠 Что запомнить

1. `ls -lrt /var/log/` и `journalctl -u <сервис>` — первые две команды при любом инциденте.
2. Уровни severity: **emerg, alert, crit, err, warning, notice, info, debug**. Смотреть с `-p err`.
3. `journalctl -b -1` — единственный способ увидеть, что было до внезапной перезагрузки
   (и он работает только при **persistent**-журнале).
4. `journalctl -xe` — разбор «почему сервис не стартовал».
5. `dmesg -T` — OOM, ошибки диска, аппаратные проблемы, segfault.
6. `/var/log/auth.log` — SSH, sudo, su; `last`/`lastb` — входы (файлы бинарные).
7. logrotate обязателен для любого нового лога; `copytruncate` — если приложение не переоткрывает файл.
8. Без ротации и без централизации логи однажды либо кончат диск, либо исчезнут вместе с сервером.
9. В контейнерах логи идут в **stdout/stderr**, файл внутри контейнера — анти-паттерн.

Дальше — [16. Network Sharing](/linux/16-network-sharing), начинается часть Networking Nomad.

---

## Задачи

> `vagrant snapshot save before_15 && vagrant ssh`

---

### Блок A. Теория

**A1.** Что такое journald и чем он отличается от rsyslog? Могут ли они работать одновременно?

<details><summary>Ответ</summary>

journald — служба systemd, пишущая **структурированный бинарный** журнал с метаданными
(юнит, PID, UID, приоритет, boot ID), с индексированием и фильтрацией через `journalctl`.
rsyslog — классический демон, пишущий **текстовые** файлы по правилам facility/severity и умеющий
пересылать логи по сети. Да, они работают одновременно: journald собирает всё и пересылает
в rsyslog, который раскладывает по `/var/log/*.log`.

</details>

**A2.** Перечисли уровни severity от самого критичного к самому подробному. С какого обычно
начинают разбор инцидента?

<details><summary>Ответ</summary>

emerg (0), alert (1), crit (2), err (3), warning (4), notice (5), info (6), debug (7).
Разбор обычно начинают с `-p err` (уровень 3 и выше по критичности).

</details>

**A3.** Что такое facility в syslog? Зачем нужны `local0`-`local7`?

<details><summary>Ответ</summary>

Facility — категория источника сообщения (`auth`, `cron`, `daemon`, `kern`, `mail` и др.),
позволяющая маршрутизировать логи в разные файлы. `local0`-`local7` зарезервированы для
пользовательских приложений — через них свой сервис получает отдельный канал и отдельный файл.

</details>

**A4.** Почему журнал journald по умолчанию может теряться при перезагрузке и как это исправить?

<details><summary>Ответ</summary>

Если каталога `/var/log/journal` нет, journald хранит журнал в `/run/log/journal`
(tmpfs, в памяти), и он исчезает при перезагрузке. Исправление: создать `/var/log/journal`
(и/или задать `Storage=persistent` в `/etc/systemd/journald.conf`), перезапустить journald.

</details>

**A5.** Какие логи лежат в `/var/log/syslog`, `/var/log/auth.log`, `/var/log/kern.log`?
Как эти файлы называются в RHEL?

<details><summary>Ответ</summary>

`/var/log/syslog` — общий поток системных сообщений; `/var/log/auth.log` — аутентификация
(SSH, sudo, su, PAM); `/var/log/kern.log` — сообщения ядра. В RHEL: `/var/log/messages`,
`/var/log/secure`, а сообщения ядра попадают в `messages` (плюс `dmesg`).

</details>

**A6.** Почему `cat /var/log/wtmp` выводит мусор? Чем читать этот файл?

<details><summary>Ответ</summary>

`wtmp` — бинарный файл фиксированных структур `utmp`, а не текст. Читать: `last`
(для `wtmp`), `lastb` (для `btmp`, неудачные входы), `lastlog` (последний вход каждого пользователя),
`who`/`w` (текущие сессии, `utmp`).

</details>

**A7.** Зачем нужен logrotate? Что произойдёт без него?

<details><summary>Ответ</summary>

logrotate периодически переименовывает, сжимает и удаляет старые логи. Без него файлы
растут неограниченно, заполняют раздел, замедляют работу с ними и в итоге кладут сервис
(«No space left on device»).

</details>

**A8.** Что делает `copytruncate` и когда он обязателен? Какая проблема возникает без него?

<details><summary>Ответ</summary>

`copytruncate` копирует текущий лог в архив и **обнуляет оригинальный файл**, не меняя
inode — поэтому процесс, держащий дескриптор, продолжает писать в тот же файл. Обязателен,
когда приложение не умеет переоткрывать лог по сигналу. Без него после переименования файла
приложение продолжит писать в удалённый inode: новые записи не видны, а место не освобождается.

</details>

**A9.** Что означает `delaycompress` и зачем он нужен?

<details><summary>Ответ</summary>

`delaycompress` откладывает сжатие на один цикл ротации: свежеротированный файл остаётся
несжатым, потому что процесс ещё может в него дописывать. Типично используется вместе с
`postrotate`-reload или `copytruncate`.

</details>

**A10.** Почему в контейнерах приложение должно писать в stdout/stderr, а не в файл?

<details><summary>Ответ</summary>

Контейнеры эфемерны: файл внутри исчезнет вместе с контейнером, и его никто не соберёт.
Вывод в stdout/stderr перехватывается рантаймом (`docker logs`, `kubectl logs`) и агентами сбора
(fluent-bit, promtail), обеспечивая единый конвейер, ротацию и централизацию.

</details>

**A11.** Зачем нужна централизация логов? Что произойдёт при автоскейлинге без неё?

<details><summary>Ответ</summary>

При автоскейлинге и в контейнерных средах инстансы создаются и уничтожаются; логи,
лежащие локально, исчезают вместе с ними — расследовать инцидент будет нечем. Централизация
даёт единый поиск по всему парку, корреляцию событий, долговременное хранение и алерты.

</details>

**A12.** Чем `journalctl -xe` полезен при падении сервиса?

<details><summary>Ответ</summary>

`-e` переводит в конец журнала, `-x` добавляет пояснения (catalog messages) к сообщениям
systemd: что означает ошибка и куда смотреть. Это самый быстрый способ увидеть контекст падения
сервиса вместе с сопутствующими событиями.

</details>

**A13.** Что такое `logger` и когда его использовать в скриптах?

<details><summary>Ответ</summary>

`logger` отправляет сообщение в syslog/journald с указанием тега, facility и severity.
В скриптах он предпочтительнее `echo >> файл`: запись получает метаданные и время, попадает в
общий конвейер, ротируется и централизуется автоматически.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  ls -lrt /var/log/
B2.  journalctl -u nginx -n 50 --no-pager
B3.  journalctl -p err -b
B4.  journalctl -b -1
B5.  journalctl --since "2026-09-13 03:00" --until "2026-09-13 04:00"
B6.  journalctl -k | grep -i oom
B7.  journalctl -u app --grep "timeout"
B8.  journalctl --disk-usage
B9.  sudo journalctl --vacuum-time=7d
B10. logger -p local0.err -t backup "backup failed"
B11. last reboot | head
B12. sudo lastb -n 20
B13. sudo logrotate -d /etc/logrotate.d/nginx
B14. dmesg -T | grep -i "i/o error"
B15. journalctl -o json-pretty -n 1
```

- **B1.** Файлы `/var/log` по времени изменения — сразу видно, что «шевелилось» последним.
- **B2.** Последние 50 строк лога nginx без пейджера.
- **B3.** Ошибки (err и выше) за текущую загрузку.
- **B4.** Журнал предыдущей загрузки — ключ к разбору внезапного ребута.
- **B5.** Записи за указанный часовой интервал.
- **B6.** Сообщения ядра о срабатывании OOM killer.
- **B7.** Поиск по регулярному выражению внутри логов юнита.
- **B8.** Размер, занимаемый журналом на диске.
- **B9.** Удаляет записи журнала старше 7 дней.
- **B10.** Отправляет сообщение в syslog с facility `local0`, уровнем `err` и тегом `backup`.
- **B11.** История перезагрузок системы.
- **B12.** Последние 20 **неудачных** попыток входа (из `btmp`).
- **B13.** Сухой прогон ротации: покажет, что было бы сделано, ничего не меняя.
- **B14.** Ошибки ввода-вывода в сообщениях ядра с читаемым временем.
- **B15.** Последняя запись журнала со всеми метаданными в JSON.

**B16.** Чем `journalctl -f` отличается от `tail -f /var/log/syslog`? Когда что использовать?

<details><summary>Ответ</summary>

`journalctl -f` следит за **структурированным** журналом: доступны фильтры по юниту,
приоритету, PID, и он видит логи сервисов, которые вообще не пишут в файлы. `tail -f` работает
с конкретным текстовым файлом и ломается при ротации (нужен `-F`). Для systemd-сервисов —
`journalctl -u app -f`; для чужих файловых логов (nginx access) — `tail -F`.

</details>

---

### Блок C. Практика

**C1. Инвентаризация логов.** Ответь командами:
- какие файлы в `/var/log` изменялись последними (топ-10);
- сколько места занимает `/var/log` целиком и какие 5 файлов самые большие;
- сколько места занимает журнал journald;
- persistent ли журнал (проверь по наличию каталога и настройке).

<details><summary>Ответ</summary>

```bash
ls -lrt /var/log/ | tail -10
sudo du -sh /var/log
sudo du -ah /var/log | sort -rh | head -5
journalctl --disk-usage
ls -d /var/log/journal 2>/dev/null && echo persistent || echo volatile
grep -E '^\s*Storage' /etc/systemd/journald.conf
```

</details>

**C2. journald-фильтры.** Найди:
- все ошибки за текущую загрузку;
- все сообщения сервиса `ssh` за сегодня;
- сообщения ядра о дисках;
- сообщения от процесса с конкретным PID;
- события за последние 30 минут уровня warning и выше;
- все записи, содержащие слово `Failed`.

<details><summary>Ответ</summary>

```bash
journalctl -p err -b --no-pager
journalctl -u ssh --since today --no-pager
journalctl -k --no-pager | grep -iE 'sd[a-z]|vd[a-z]|nvme'
journalctl _PID=1 -n 20 --no-pager
journalctl -p warning --since "30 min ago" --no-pager
journalctl --grep "Failed" --no-pager | tail
```

</details>

**C3. Persistent-журнал.** Сделай журнал постоянным, задай ограничение 300 МБ
и хранение 30 дней через `/etc/systemd/journald.conf`. Проверь, что настройки применились
(команда для проверки эффективных лимитов).

<details><summary>Ответ</summary>

```bash
sudo mkdir -p /var/log/journal
sudo tee -a /etc/systemd/journald.conf >/dev/null <<'EOS'
Storage=persistent
SystemMaxUse=300M
MaxRetentionSec=1month
EOS
sudo systemctl restart systemd-journald
journalctl --disk-usage
systemd-analyze cat-config systemd/journald.conf | grep -E 'Storage|SystemMaxUse|MaxRetention'
```

</details>

**C4. Свой лог-канал.** Настрой так, чтобы сообщения приложения `mylab` через facility `local3`
попадали в отдельный файл `/var/log/mylab.log` (и **не** дублировались в `/var/log/syslog`):
1. правило в `/etc/rsyslog.d/`;
2. перезапуск rsyslog;
3. проверка через `logger`;
4. ротация этого файла через `logrotate` (7 дней, сжатие).

<details><summary>Ответ</summary>

```bash
echo 'local3.*    -/var/log/mylab.log' | sudo tee /etc/rsyslog.d/40-mylab.conf
# чтобы не дублировалось в syslog, добавить local3.none в правило *.* — правим 50-default.conf:
sudo sed -i 's|^\*\.\*;auth,authpriv.none|*.*;auth,authpriv.none;local3.none|' /etc/rsyslog.d/50-default.conf
sudo systemctl restart rsyslog
logger -p local3.info -t mylab "hello from local3"
sudo tail -2 /var/log/mylab.log
sudo grep -c mylab /var/log/syslog || echo "в syslog не дублируется — верно"
sudo tee /etc/logrotate.d/mylab >/dev/null <<'EOS'
/var/log/mylab.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    create 0640 syslog adm
    postrotate
        systemctl kill -s HUP rsyslog.service >/dev/null 2>&1 || true
    endscript
}
EOS
sudo logrotate -d /etc/logrotate.d/mylab
```

</details>

**C5. Логирование из скрипта.** Напиши `/usr/local/bin/backup_demo.sh`, который:
- логирует начало и конец работы через `logger` с тегом `backup`;
- при ошибке пишет с уровнем `err`;
- возвращает корректный exit code.
Запусти успешный и неуспешный сценарии и найди обе записи в journald.

<details><summary>Ответ</summary>

```bash
sudo tee /usr/local/bin/backup_demo.sh >/dev/null <<'EOS'
#!/usr/bin/env bash
TAG=backup
logger -t "$TAG" -p local0.info "backup started"
SRC="${1:-/etc/hostname}"
if [[ ! -e "$SRC" ]]; then
  logger -t "$TAG" -p local0.err "backup failed: $SRC not found"
  exit 1
fi
cp "$SRC" /tmp/ && logger -t "$TAG" -p local0.info "backup finished OK" || {
  logger -t "$TAG" -p local0.err "backup failed: copy error"; exit 2; }
EOS
sudo chmod +x /usr/local/bin/backup_demo.sh
backup_demo.sh /etc/hostname ; echo "rc=$?"
backup_demo.sh /nope        ; echo "rc=$?"
journalctl -t backup -n 10 --no-pager
```

</details>

**C6. Анализ логов аутентификации.** Сгенерируй несколько неудачных попыток входа
(например, `ssh wronguser@localhost` несколько раз), затем:
- посчитай количество неудачных попыток;
- найди топ IP-адресов и имён пользователей;
- покажи успешные входы за сегодня;
- покажи все команды, выполненные через `sudo`.

<details><summary>Ответ</summary>

```bash
for i in 1 2 3; do ssh -o BatchMode=yes -o ConnectTimeout=3 wronguser@localhost true 2>/dev/null; done
sudo grep -c "Failed password\|Invalid user" /var/log/auth.log
sudo grep -E "Failed password|Invalid user" /var/log/auth.log | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | sort | uniq -c | sort -rn | head
sudo grep "Invalid user" /var/log/auth.log | awk '{print $8}' | sort | uniq -c | sort -rn | head
sudo grep "Accepted" /var/log/auth.log | tail -5
sudo grep COMMAND /var/log/auth.log | tail -10
```

</details>

**C7. logrotate с нуля.** Создай `/var/log/demo/app.log`, наполни его данными и настрой ротацию:
- ежедневно, хранить 7 копий, сжимать;
- `copytruncate`;
- суффикс с датой;
- не ротировать пустые файлы.
Проверь через `-d` (сухой прогон), затем выполни принудительно 3 раза подряд и покажи результат.

<details><summary>Ответ</summary>

```bash
sudo mkdir -p /var/log/demo
sudo bash -c 'for i in $(seq 1 500); do echo "$(date -Is) line $i" >> /var/log/demo/app.log; done'
sudo tee /etc/logrotate.d/demo >/dev/null <<'EOS'
/var/log/demo/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    dateext
}
EOS
sudo logrotate -d /etc/logrotate.d/demo
for i in 1 2 3; do sudo logrotate -f /etc/logrotate.d/demo; sleep 1; done
ls -l /var/log/demo/
```

</details>

**C8. Проблема удалённого лога.** Воспроизведи классическую ошибку ротации:
1. Запусти процесс, который пишет в лог-файл в цикле.
2. Переименуй/удали файл (имитация ротации без `copytruncate` и без reload).
3. Покажи, что новые записи пропали, а место не освободилось.
4. Покажи два способа решения проблемы.

<details><summary>Ответ</summary>

```bash
sudo bash -c 'while true; do echo "$(date -Is) tick" >> /var/log/demo/live.log; sleep 1; done' &
W=$!
sleep 3
sudo mv /var/log/demo/live.log /var/log/demo/live.log.1     # ротация "без copytruncate"
sleep 3
sudo ls -l /var/log/demo/           # новый live.log не создан
sudo lsof -p "$(pgrep -f 'while true' | head -1)" | grep live
```
Решения: (1) `copytruncate` в конфиге logrotate; (2) `postrotate`-секция, посылающая приложению
`SIGHUP`/`systemctl reload`, чтобы оно переоткрыло файл. (Для процесса из примера — просто
перезапустить: `sudo kill $W`.)

</details>

**C9. Скрипт анализа логов.** Напиши `/vagrant/log_analyzer.sh`, который выводит:
```text:no-line-numbers
=== LOG ANALYSIS (last 24h) ===
Total errors: 12
Top error sources:
   5  systemd
   4  kernel
Failed SSH attempts: 34 (top IP: 10.0.0.5 = 21)
Sudo commands: 8
Reboots: 1 (last: 2026-09-13 08:15)
OOM kills: 0
Disk errors: 0
Largest log files:
   120M /var/log/journal
   45M  /var/log/syslog
```

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
echo "=== LOG ANALYSIS (last 24h) ==="
echo "Total errors: $(journalctl -p err --since '24 hours ago' --no-pager -q | wc -l)"
echo "Top error sources:"
journalctl -p err --since '24 hours ago' --no-pager -q -o short |
  awk '{print $5}' | sed 's/\[[0-9]*\]:$//; s/:$//' | sort | uniq -c | sort -rn | head -5
fails=$(sudo grep -c "Failed password" /var/log/auth.log 2>/dev/null || echo 0)
topip=$(sudo grep "Failed password" /var/log/auth.log 2>/dev/null |
        grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | sort | uniq -c | sort -rn | head -1)
echo "Failed SSH attempts: $fails (top: ${topip:-none})"
echo "Sudo commands: $(sudo grep -c COMMAND /var/log/auth.log 2>/dev/null || echo 0)"
echo "Reboots: $(last reboot --no-hostname | grep -c '^reboot') (last: $(last -1 reboot --no-hostname | head -1 | awk '{print $5,$6,$7}'))"
echo "OOM kills: $(journalctl -k --since '24 hours ago' --no-pager -q | grep -ci 'out of memory' || echo 0)"
echo "Disk errors: $(journalctl -k --since '24 hours ago' --no-pager -q | grep -ci 'i/o error' || echo 0)"
echo "Largest log files:"
sudo du -ah /var/log 2>/dev/null | sort -rh | head -5
```

</details>

**C10. Разбор инцидента.** Сымитируй инцидент и разбери его по логам:
1. Создай и запусти сервис, который падает через 10 секунд с ненулевым кодом.
2. Через 30 секунд «расследуй»: когда начались проблемы, сколько было рестартов,
   какой код выхода, что писало приложение перед падением.
3. Оформи вывод в виде короткого post-mortem: симптом → диагностика → причина → фикс.

<details><summary>Ответ</summary>

```bash
sudo tee /etc/systemd/system/flaky.service >/dev/null <<'EOS'
[Unit]
Description=Flaky demo service
[Service]
Type=simple
ExecStart=/bin/bash -c 'echo "starting"; sleep 10; echo "fatal: cannot reach database" >&2; exit 7'
Restart=on-failure
RestartSec=3
[Install]
WantedBy=multi-user.target
EOS
sudo systemctl daemon-reload && sudo systemctl start flaky
sleep 40
systemctl status flaky | head -8
journalctl -u flaky --since "2 min ago" --no-pager | tail -20
journalctl -u flaky --no-pager | grep -c "starting"      # число рестартов
sudo systemctl stop flaky; sudo rm /etc/systemd/system/flaky.service; sudo systemctl daemon-reload
```
Post-mortem: **симптом** — сервис в состоянии activating/failed, рестарты каждые 13 секунд;
**диагностика** — `systemctl status` (код выхода 7), `journalctl -u flaky` (`fatal: cannot reach
database`); **причина** — недоступна БД; **фикс** — восстановить доступ к БД, добавить
`After=`/`Requires=` на зависимость, health-check и ограничение `StartLimitBurst`,
чтобы сервис не рестартовал бесконечно.

</details>

---

### Блок D. Инциденты

**D1.** Диск заполнен, `/var/log` занимает 40 ГБ. Что делаешь по шагам
и как не допустить повторения?

<details><summary>Ответ</summary>

```bash
sudo du -ah /var/log | sort -rh | head -20
journalctl --disk-usage && sudo journalctl --vacuum-size=200M
sudo find /var/log -name "*.gz" -mtime +30 -delete
sudo truncate -s 0 /var/log/<огромный_файл>.log      # НЕ rm, если файл открыт
sudo lsof +L1 | head
```
Профилактика: logrotate для **каждого** лога (включая приложения), лимиты journald
(`SystemMaxUse`), отдельный раздел под `/var/log`, снижение уровня логирования приложения,
централизация логов, алерт мониторинга на 80% заполнения.

</details>

**D2.** После ротации логов приложение перестало писать в лог, хотя работает.
`lsof` показывает, что оно держит файл `app.log.1 (deleted)`. Что произошло и как чинить?

<details><summary>Ответ</summary>

Ротация переименовала файл, а приложение продолжает писать в старый inode
(дескриптор открыт). Немедленно: перезапустить/перезагрузить конфиг приложения
(`systemctl reload app`) — оно переоткроет лог. Постоянно: добавить в конфиг logrotate
`postrotate`-секцию с reload либо `copytruncate`.

</details>

**D3.** Сервер перезагрузился ночью. `journalctl -b -1` выдаёт
`Specifying boot ID or boot offset has no effect, no persistent journal was found`.
Что это значит и что ты уже потерял? Как настроить, чтобы такого больше не было?

<details><summary>Ответ</summary>

Журнал хранился только в памяти (`/run/log/journal`) и был потерян при перезагрузке —
логи предыдущей загрузки недоступны, причину ребута из journald узнать нельзя.
Что ещё посмотреть: `/var/log/syslog*` и `/var/log/kern.log*` (если rsyslog пишет файлы),
`last -x`, `sar` за нужный день. Настройка на будущее: создать `/var/log/journal`,
`Storage=persistent` + `SystemMaxUse=`, перезапустить journald.

</details>

**D4.** В `auth.log` тысячи строк `Failed password for invalid user admin from 45.x.x.x`.
Что это, насколько опасно и что делать (краткосрочно и долгосрочно)?

<details><summary>Ответ</summary>

Автоматизированный брутфорс SSH — фоновый шум интернета, но опасен при слабых паролях.
Краткосрочно: убедиться, что `PasswordAuthentication no` и `PermitRootLogin no`, поставить
`fail2ban`, ограничить доступ по IP/Security Group, при необходимости сменить порт (это не защита,
а снижение шума). Долгосрочно: доступ только по ключам, бастион/VPN, MFA, мониторинг и алерты
на аномалии, регулярный аудит `lastb`.

</details>

**D5.** Приложение пишет 500 МБ логов в час на уровне debug. Что предложишь команде разработки
и что настроишь со своей стороны?

<details><summary>Ответ</summary>

Разработке: уменьшить уровень до `info`/`warn` в проде, убрать логирование в горячих циклах,
перейти на структурированный JSON и сэмплирование, не логировать секреты и тела запросов.
Со своей стороны: агрессивная ротация (`size 100M`, `rotate 5`, `compress`), лимиты journald,
отдельный том под логи, ограничение размера логов Docker
(`log-opts: max-size=50m, max-file=3`), фильтрация на этапе сбора, алерт на скорость роста логов.

</details>

**D6.** Нужно понять, кто и когда удалил файл конфигурации на сервере, где работают 5 человек.
Какие источники проверишь?

<details><summary>Ответ</summary>

`/var/log/auth.log` (кто входил и какие команды выполнял через sudo),
`journalctl _COMM=sudo`, `last`/`lastlog`, история shell (`~/.bash_history` каждого пользователя —
ненадёжно, но полезно), `/var/log/apt/history.log` (если удаление связано с пакетом),
время изменения каталога (`stat`), бэкапы/снапшоты, git-история конфигов. По-хорошему такие
вопросы решает **auditd** (`auditctl -w /etc/nginx -p wa -k nginx_changes`) — его и стоит
настроить после инцидента.

</details>

**D7.** Лог-файл `access.log` растёт, а logrotate его не ротирует. Как диагностировать?

<details><summary>Ответ</summary>

Проверить: `sudo logrotate -d /etc/logrotate.d/<конфиг>` (увидеть решение и ошибки),
`cat /var/lib/logrotate/status` (когда ротировался последний раз), запускается ли таймер
(`systemctl status logrotate.timer`, `journalctl -u logrotate`), нет ли синтаксической ошибки
в **любом** файле `/etc/logrotate.d/` (одна ошибка ломает весь прогон), совпадает ли маска пути
с реальным файлом, соответствуют ли права/владелец, не мешает ли `su`-директива или SELinux.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Где смотреть логи в Linux?

<details><summary>Ответ</summary>

`/var/log/` (syslog/messages, auth.log/secure, kern.log, логи приложений) и journald
(`journalctl`). Плюс `dmesg` для ядра и специализированные логи сервисов.

</details>

**2.** Чем journald отличается от syslog?

<details><summary>Ответ</summary>

journald хранит бинарный структурированный журнал с метаданными и фильтрацией; syslog/rsyslog —
текстовые файлы с маршрутизацией по facility/severity и пересылкой по сети. Обычно работают вместе.

</details>

**3.** Как посмотреть логи конкретного сервиса за последний час?

<details><summary>Ответ</summary>

`journalctl -u <сервис> --since "1 hour ago"` (добавить `-p err` для ошибок, `-f` для слежения).

</details>

**4.** Как узнать, почему сервер перезагрузился?

<details><summary>Ответ</summary>

`journalctl --list-boots`, `journalctl -b -1 -p err`, `journalctl -k -b -1`, `last -x`,
`dmesg -T`; искать kernel panic, OOM, аппаратные ошибки или штатное выключение.

</details>

**5.** Что такое logrotate и как его настроить для своего приложения?

<details><summary>Ответ</summary>

Утилита ротации логов. Создать файл в `/etc/logrotate.d/app` с `daily`/`size`, `rotate N`,
`compress`, `missingok`, `notifempty` и либо `copytruncate`, либо `postrotate` с reload;
проверить `logrotate -d`.

</details>

**6.** Как найти попытки взлома SSH?

<details><summary>Ответ</summary>

`grep "Failed password" /var/log/auth.log`, `lastb`, агрегация по IP и пользователям;
поставить fail2ban и отключить парольную аутентификацию.

</details>

**7.** Куда должно логировать приложение в контейнере?

<details><summary>Ответ</summary>

В **stdout/stderr** — сбор берёт на себя рантайм и агент логирования; файл внутри контейнера
исчезнет вместе с ним.

</details>

**8.** Что делать, если логи заняли весь диск?

<details><summary>Ответ</summary>

Найти крупные файлы (`du -ah /var/log | sort -rh | head`), почистить journald
(`--vacuum-size`), обнулить активные логи через `truncate` (не `rm`), проверить `lsof +L1`,
затем настроить ротацию и лимиты, чтобы не повторялось.

</details>

---

### 🎯 Чек-лист

- [ ] `journalctl -u <сервис> --since` и `-p err` — на автомате
- [ ] Знаю все уровни severity и с какого начинать разбор
- [ ] Сделал журнал persistent и понимаю, почему это критично
- [ ] Умею писать в syslog из скриптов через `logger`
- [ ] Настроил свой logrotate и понимаю `copytruncate`/`delaycompress`
- [ ] Воспроизвёл проблему «лог ротировали, а приложение пишет в никуда»
- [ ] Могу найти брутфорс SSH и посмотреть историю sudo
- [ ] Написал `log_analyzer.sh`
