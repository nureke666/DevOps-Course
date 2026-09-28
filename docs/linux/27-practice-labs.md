---
title: "27. Практика: лабы"
description: "Семь сквозных лаб по блоку Linux: онбординг, свой сервис, диск полон, сервер тормозит, сеть, emergency mode, итоговый стенд"
---

# 27. Практические лабы — Linux целиком

> Роадмап → 2. Linux + Bash → **Практика**
>
> Семь сквозных лаб по всему блоку. Каждая — это не одна тема, а ситуация с работы:
> онбординг человека, свой сервис, «диск полон», «сервер тормозит», «сайт не открывается»,
> «сервер не загрузился», итоговый стенд со скриптом по расписанию. После каждой остаётся
> артефакт (конфиг, юнит, скрипт, журнал расследования), который можно показать на собеседовании.
>
> Стенд лаб 1-6: VM `learn-linux` ([00. Стенд: Vagrant + libvirt/KVM](/linux/00-vagrant)), `~/Projects/devops/stands/learn-linux`.
> Стенд лабы 7: две VM `web` + `app`, `~/Projects/devops/stands/net-lab`.
> **Перед каждой лабой:** `vagrant snapshot save before_lab<N>` — без исключений.

---

## 📋 Список лаб

| № | Лаба | Темы | Когда браться | Потом без подсказок |
|---|------|------|---------------|---------------------|
| 1 | Онбординг: пользователи, sudo, SSH-ключи, права и ACL | 05, 06 | после 06 (день 7) | инциденты 01, 02 |
| 2 | Свой сервис: systemd + таймер + journald + logrotate | 13, 14, 15 | после 15 (дни 13-14) | 02-nightshift, инцидент 06 |
| 3 | «Диск полон»: du vs df, удалённый-но-открытый файл, inode | 07, 09, 10, 14, 15 | после 15 | инцидент 05 |
| 4 | «Сервер тормозит»: охота на процессы | 07, 12, 14 | после 14 | инцидент 04 |
| 5 | «Сайт не открывается»: семь поломок сети на одной VM | 13, 17-22 | после 22 | инциденты 07, 08 |
| 6 | «Сервер не загрузился»: битый fstab → emergency mode → починка | 10, 11, 13, 15 | после 13 | — |
| 7 | **Итоговая лаба**: стенд web + app и бэкап-скрипт по systemd-таймеру | всё + 16, 23-26 | часть A — день 21 плана, часть B — после 25-26 | 02-nightshift, 01-logsleuth, инцидент 03 |

**Правила всех лаб:**
1. **Снапшот перед стартом.** Сломал так, что не понимаешь, что происходит, — `vagrant snapshot restore before_lab<N>`,
   и заново. Это не поражение, а нормальный цикл.
2. **Сначала диагностика, потом починка.** В разделах «Проверка» и «Сломай сам» главное —
   найти причину по выводу команд, а не вспомнить, что ты сам сломал.
3. **Веди журнал** (`labs.md` рядом со скриптами): команда → что увидел → вывод. Через месяц
   это готовые истории для собеса.
4. **Лаба → проект → инцидент.** Лаба — тренировка с подсказками. Проект из `~/Projects/devops` —
   то же самое с автопроверкой `check.sh`. Инцидент — только симптом, без подсказок.
   Решения из лабы в проект не копируй: у проекта свои требования.

---

## 🧪 Лаба 1. Онбординг: пользователи, sudo, SSH-ключи, права и ACL (темы 05, 06)

**Цель:** завести на сервер человека, CI-пользователя и сервис так, чтобы у каждого было
ровно столько прав, сколько нужно, и объяснить каждое решение.

**Стенд:** `learn-linux` · `vagrant snapshot save before_lab1`

### Шаги

1. **Пользователи и группы.**
   - группа `developers`;
   - `alice` — человек: домашний каталог, `bash`, в группе `developers`;
   - `deploy` — пользователь для CI: домашний каталог есть, **пароля нет**, вход только по ключу;
   - `shop` — системный пользователь для сервиса из лабы 2: `--system`, без домашнего каталога,
     shell `/usr/sbin/nologin`.

   Разбери, чем отличаются их строки в `/etc/passwd` и `/etc/shadow`.
2. **sudo.** Файл `/etc/sudoers.d/developers` — **только** через `visudo -f`. Группа `developers`
   может без пароля выполнять `systemctl restart shop.service` и `systemctl reload shop.service` и больше ничего.
   Логи `alice` читает без sudo — через группу `systemd-journal`.
   Юнита `shop` пока нет, он появится в лабе 2. Сейчас достаточно, что sudo пропускает команду:
   ошибка будет уже от `systemctl`, а не от sudo.
3. **SSH по ключу.** На хосте — ключ `ed25519` для `alice`. Публичный ключ — в VM
   (`vagrant upload ~/.ssh/learn_alice.pub /tmp/alice.pub`), затем в `~alice/.ssh/authorized_keys`.
   Права: `700` на `.ssh`, `600` на `authorized_keys`, владелец `alice`.
   Адрес VM для входа с хоста: `vagrant ssh-config | awk '/HostName/{print $2}'`.
4. **Закрыть пароли.** Drop-in `/etc/ssh/sshd_config.d/10-hardening.conf`: `PasswordAuthentication no`,
   `PermitRootLogin no`. Перед `systemctl reload ssh` — `sudo sshd -t`, и **держи вторую сессию открытой**,
   пока не проверил вход заново.
   Разбери, почему файл называется `10-…`, а не `99-…`. Подсказка: в sshd побеждает **первое**
   встреченное значение, а файл `50-cloud-init.conf` может разрешать пароли.
5. **Каталоги проекта:**
   ```text:no-line-numbers
   /srv/shop/                 root:developers  2775  + ACL для deploy (и default ACL)
   ├── releases/              наследует группу и ACL
   └── shared/uploads/        shop:developers  3770  (setgid + sticky)
   /etc/shop/shop.env         root:shop        0640  (сервис читает, разработчики — нет)
   ```
   - setgid на каталоге — новые файлы получают группу `developers`, а не группу автора;
   - sticky на `uploads` — писать может вся группа, удалять — только своё;
   - `deploy` **не** в группе `developers`, но пишет в `/srv/shop` через ACL
     (`setfacl -m u:deploy:rwX`, плюс `-d` для наследования новыми файлами);
   - default ACL `g:developers:rwX` — чтобы групповая запись не зависела от `umask` автора.

### Проверка результата

```bash
id alice; id deploy; getent passwd shop            # группы; у shop — nologin
sudo passwd -S deploy                              # L или NP — пароля нет
sudo -l -U alice                                   # только restart/reload shop
sudo -u alice sudo -n systemctl restart shop.service; echo $?   # sudo пропустил (ошибка от systemctl — ок)
sudo -u alice sudo -n cat /etc/shadow; echo $?     # отказ
sudo -u alice journalctl -n 3 --no-pager           # логи без sudo

# с хоста
ssh -i ~/.ssh/learn_alice alice@"$VM_IP" id        # вход по ключу
ssh -o PubkeyAuthentication=no alice@"$VM_IP"      # Permission denied (publickey)

# на VM
sudo sshd -T | grep -Ei '^(passwordauthentication|permitrootlogin)'   # no / no
sudo -u deploy mkdir /srv/shop/releases/r1 && ls -ld /srv/shop/releases/r1   # группа developers
getfacl /srv/shop/releases/r1                      # ACL унаследован
sudo -u alice cat /etc/shop/shop.env               # Permission denied
sudo -u shop  cat /etc/shop/shop.env               # читается
namei -l /etc/shop/shop.env                        # права на каждом шаге пути
```

- [ ] Каждому пользователю можешь объяснить, зачем ему именно эти права
- [ ] Вход по паролю закрыт, root по SSH не пускают, ты сам при этом не потерял доступ
- [ ] Новые файлы в `/srv/shop` сразу получают правильную группу и ACL, `chmod` руками не нужен

### 💥 Сломай сам

| Поломка | Что увидишь | Где искать причину |
|---------|-------------|--------------------|
| `chmod 664 ~alice/.ssh/authorized_keys` или `775` на домашний каталог | ключ не принимается | `journalctl -u ssh`: `bad ownership or modes` (StrictModes) |
| Синтаксическая ошибка в `sudoers.d`, файл правил **без** `visudo` | sudo сломан у всех, включая `vagrant` | чинить без sudo: консоль + `init=/bin/bash` (лаба 6), `pkexec` (если установлен), снапшот |
| `chmod o-x /srv` | `Permission denied` при правах 644 на файл | `namei -l`: нужен `x` на **каждом** каталоге пути |
| `chmod g-w` на файле с ACL | в `getfacl` появился `#effective:` меньше выданного | маска ACL — верхняя граница для групп и именованных пользователей |
| `chmod g-s /srv/shop/releases` | новые файлы с группой автора, коллеги не могут править | `ls -l`, `stat` |
| Убрать `alice` из группы, не перелогиниваясь | в открытой сессии права остались | группы процесса фиксируются при логине: `id` vs `id alice` |
| Разрешить в sudoers `systemctl status shop` или `journalctl` | **root-shell**: в пейджере `less` набрать `!sh` | вот почему в sudoers не дают команды с пейджером или редактором |

### 🔗 Связь
- Темы: [05. Управление пользователями](/linux/05-user-management) · [06. Права доступа](/linux/06-permissions) ·
  SSH глубже — тема 08 блока Network
- Без подсказок: инциденты **01-no-sudo** и **02-permission-path** — `./incident.sh start 01` / `start 02` на VM

---

## 🧪 Лаба 2. Свой сервис: systemd + таймер + journald + logrotate (темы 13, 14, 15)

**Цель:** превратить скрипт «запускается руками в терминале» в сервис: не под root,
поднимается сам, пишет логи куда надо, логи не съедают диск, за ним следит health-check по таймеру.

**Стенд:** `learn-linux` после лабы 1 (пользователи `shop`, `deploy`, каталоги) · `vagrant snapshot save before_lab2`

### Каркас приложения

Релиз кладёт `deploy`: `/srv/shop/releases/v1/app.py`, симлинк `/srv/shop/current → releases/v1`.

```python
#!/usr/bin/env python3
"""shop — учебный HTTP-сервис для лаб Linux-блока."""
import json, os, signal, sys, time
from http.server import HTTPServer, BaseHTTPRequestHandler

BIND = os.getenv("SHOP_BIND", "0.0.0.0")
PORT = int(os.getenv("SHOP_PORT", "8080"))
DATA = os.getenv("SHOP_DATA", "/var/lib/shop")
ACCESS_LOG = os.getenv("SHOP_ACCESS_LOG", "")        # пусто — лог только в stdout
START = time.time()
log_file = None

def open_log(*_):
    """Открыть (или переоткрыть по SIGHUP) файл access-лога."""
    global log_file
    if ACCESS_LOG:
        if log_file:
            log_file.close()
        log_file = open(ACCESS_LOG, "a", buffering=1)
        print(f"access log opened: {ACCESS_LOG}", flush=True)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body = "ok\n"
        else:
            with open(os.path.join(DATA, "hits.txt"), "a") as f:     # «данные» сервиса
                f.write(f"{time.time():.0f} {self.client_address[0]} {self.path}\n")
            body = json.dumps({"host": os.uname().nodename,
                               "uptime": round(time.time() - START, 1)}) + "\n"
        self.send_response(200); self.end_headers(); self.wfile.write(body.encode())

    def log_message(self, fmt, *args):
        line = f"{self.client_address[0]} {fmt % args}"
        print(line, flush=True)                                        # → journald
        if log_file:
            log_file.write(time.strftime("%Y-%m-%dT%H:%M:%S ") + line + "\n")

def stop(*_):
    print("SIGTERM: graceful shutdown", flush=True)
    sys.exit(0)

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGHUP, open_log)
open_log()
print(f"start bind={BIND} port={PORT} data={DATA}", flush=True)
HTTPServer((BIND, PORT), Handler).serve_forever()
```

### Требования

**Сервис `shop.service`**
- [ ] `User=shop`, `ExecStart=/usr/bin/python3 /srv/shop/current/app.py`
- [ ] Конфиг — в `/etc/shop/shop.env` через `EnvironmentFile=`, строки ровно
      `SHOP_BIND=0.0.0.0`, `SHOP_PORT=8080`, `SHOP_DATA=/var/lib/shop`,
      `SHOP_ACCESS_LOG=/var/log/shop/access.log` (лаба 5 будет править этот файл)
- [ ] Каталоги создаёт systemd: `StateDirectory=shop`, `LogsDirectory=shop`
- [ ] `Restart=on-failure`, `RestartSec=`; `WantedBy=multi-user.target`; `enable --now`
- [ ] Hardening: `NoNewPrivileges=yes`, `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`
- [ ] `ExecReload=/bin/kill -HUP $MAINPID` — переоткрыть лог без рестарта
- [ ] `systemd-analyze verify` без ошибок; `systemd-analyze security shop` — запиши оценку до и после hardening

**Health-check по таймеру**
- [ ] `shop-health.service` — `Type=oneshot`, проверяет `http://127.0.0.1:8080/health`
      (`curl -fsS --max-time 3`), при ошибке завершается с ненулевым кодом → юнит `failed`
- [ ] `shop-health.timer` — раз в минуту. Разбери разницу `OnCalendar=` (по часам) и
      `OnBootSec=` + `OnUnitActiveSec=` (интервал от прошлого запуска) и что будет, если оставить
      только `OnUnitActiveSec=`

**journald**
- [ ] Умеешь найти: логи `shop` за последние 10 минут, только ошибки `shop-health`,
      логи прошлой загрузки, вывод в JSON
- [ ] Журнал персистентный (`/var/log/journal` существует) и ограничен по размеру:
      drop-in `/etc/systemd/journald.conf.d/size.conf` с `SystemMaxUse=`

**logrotate**
- [ ] `/etc/logrotate.d/shop`: `daily`, `rotate 7`, `compress` + `delaycompress`, `missingok`, `notifempty`,
      `create 0640 shop shop`, в `postrotate` — `systemctl reload shop.service`
- [ ] После ротации приложение пишет в **новый** `access.log`, а не в `access.log.1`

### Проверка результата

```bash
systemctl is-enabled shop; systemctl is-active shop
ps -o user=,pid=,args= -C python3                          # shop, не root
curl -s localhost:8080/ && curl -s localhost:8080/health

# переживает убийство
sudo kill -9 "$(systemctl show -p MainPID --value shop)"; sleep 3
systemctl show -p NRestarts --value shop                   # ≥ 1
systemctl is-active shop                                   # active

# таймер и health-check
systemctl list-timers shop-health.timer
sudo systemctl stop shop; sleep 70; systemctl --failed     # shop-health.service failed
journalctl -u shop-health -n 5 --no-pager
sudo systemctl start shop

# журнал
journalctl -u shop --since "10 min ago" -o short-iso --no-pager | tail -5
journalctl --disk-usage

# ротация без потери строк
sudo logrotate -d /etc/logrotate.d/shop                     # сухой прогон
sudo logrotate -vf /etc/logrotate.d/shop && ls -l /var/log/shop/
curl -s localhost:8080/ >/dev/null; tail -1 /var/log/shop/access.log   # свежая строка — в новом файле
sudo ls -l /proc/"$(systemctl show -p MainPID --value shop)"/fd | grep access   # access.log, не .1

# переживает перезагрузку
sudo reboot     # потом: systemctl is-active shop shop-health.timer
```

### 💥 Сломай сам

| Поломка | Что увидишь | Где искать причину |
|---------|-------------|--------------------|
| Опечатка в пути `ExecStart` | `status=203/EXEC` | `systemctl status shop` |
| `User=` несуществующего пользователя | `status=217/USER` | `systemctl status`, `journalctl -u shop` |
| Убрать `StateDirectory=` при `ProtectSystem=strict` | `/health` работает, `/` — `curl: (52) Empty reply` | traceback `Read-only file system` в `journalctl -u shop` |
| `sys.exit(1)` в начале `app.py` | рестарт по кругу, потом `start-limit-hit` | `systemctl status`, `systemctl reset-failed shop` |
| Правка юнита без `daemon-reload` | предупреждение `changed on disk`, работает старая версия | `systemctl status`, `systemctl cat` |
| Убрать `postrotate` из logrotate | после ротации приложение пишет в `access.log.1`, а после `compress` — в удалённый файл | `ls -l /proc/PID/fd` — мостик в лабу 3 |
| `chmod 775 /var/log/shop` | logrotate пропускает файл: `insecure permissions` | `logrotate -d`; лечится директивой `su` или правами |
| health-check, который всегда возвращает 0 | таймер «зелёный», сервис лежит | коды выхода — это интерфейс (тема 23) |

### 🔗 Связь
- Темы: [13. init и systemd](/linux/13-init) · [14. Утилизация процессов](/linux/14-process-utilization) (cron vs таймеры) ·
  [15. Логирование](/linux/15-logging) · [05. Управление пользователями](/linux/05-user-management) (сервисные аккаунты)
- Без подсказок: 02-nightshift — то же самое для `linkd` с автопроверкой (уровень L1 и юнит «по-взрослому» из L3) ·
  инцидент 06 — `./incident.sh start 06`

---

## 🧪 Лаба 3. «Диск полон»: du vs df, удалённый-но-открытый файл, inode (темы 07, 09, 10, 14, 15)

**Цель:** за пять минут отвечать на «кончилось место», знать все причины, по которым `df` и `du`
показывают разное, и освобождать место без перезагрузки.

**Стенд:** `learn-linux` · `vagrant snapshot save before_lab3`.
Ломаем **отдельную** маленькую ФС на loop-устройстве, чтобы не уронить корень VM.

```bash
sudo truncate -s 300M /root/lab3.img
sudo mkfs.ext4 -q -F -N 4000 -L LAB3 /root/lab3.img     # -N — мало inode, специально
sudo mkdir -p /mnt/lab3 && sudo mount -o loop /root/lab3.img /mnt/lab3
df -h /mnt/lab3; df -i /mnt/lab3                         # запиши исходные цифры
```

### Шаги

**A. Кто съел место (обычный, но спрятанный файл)**
```bash
sudo mkdir -p /mnt/lab3/app/{releases/v1,cache/.tmp}
sudo fallocate -l 120M /mnt/lab3/app/cache/.tmp/core.12345
```
Найди его, как будто не знаешь, где он: `df -h` → `du -xh --max-depth=1 | sort -rh` уровень за уровнем →
`find -xdev -type f -size +50M`. Отметь, почему `ls` его не показал, а `du` нашёл. Удали.

**B. Удалён, но открыт**
```bash
sudo bash -c 'exec 3>/mnt/lab3/app/app.log; head -c 100M /dev/zero >&3; exec -a shop-worker sleep infinity' &
sleep 2; sudo rm /mnt/lab3/app/app.log
df -h /mnt/lab3; sudo du -sh /mnt/lab3                  # df: занято, du: пусто
```
Найди, кто держит место: `lsof -nP +L1` (файлы со счётчиком ссылок 0), `ls -l /proc/PID/fd`.
Освободи место **без убийства процесса**: `truncate -s 0 /proc/PID/fd/3`. Потом объясни, почему `rm`
не освободил место: inode освобождается, только когда нет ни одного имени **и** ни одного открытого дескриптора.

**C. Кончились inode**
```bash
sudo bash -c 'mkdir -p /mnt/lab3/sessions
  for i in $(seq 1 6000); do : > /mnt/lab3/sessions/sess_$i || break; done'
df -h /mnt/lab3; df -i /mnt/lab3                         # место есть, inode — 100%
```
Найди каталог с тысячами файлов (`find /mnt/lab3 -xdev -printf '%h\n' | sort | uniq -c | sort -rn | head`)
и почисти через `find … -delete`. Разбери, почему на миллионах файлов `rm sessions/*` падает
с `Argument list too long`.

**D. Спрятано под точкой монтирования**
```bash
sudo fuser -vm /mnt/lab3                                 # кто держит ФС (shop-worker из шага B)
# останови его, затем:
sudo umount /mnt/lab3
sudo fallocate -l 200M /mnt/lab3/hidden.bin              # пишем в каталог на КОРНЕВОЙ ФС
sudo mount -o loop /root/lab3.img /mnt/lab3              # и закрываем его сверху
df -h /; sudo du -xsh /                                  # сравни с цифрами до шага: df вырос на 200M, du — нет
```
Найди спрятанное через bind-mount корня: `mount --bind / /mnt/rootview` → `du` по `/mnt/rootview/mnt/lab3`.

**E. Боевой чек-лист на настоящем корне** (ничего не ломаем, только смотрим):
`journalctl --disk-usage`, `du -xh --max-depth=1 /var | sort -rh | head`, старые `*.gz` в `/var/log`,
`apt clean`, резерв root: `sudo tune2fs -l "$(findmnt -no SOURCE /)" | grep -i 'reserved block'`.

### Проверка результата

```bash
df -h /mnt/lab3; df -i /mnt/lab3                         # вернулись к исходным цифрам
sudo lsof -nP +L1 | grep lab3                            # пусто
pgrep -af shop-worker                                    # пусто

# уборка
sudo umount /mnt/rootview /mnt/lab3 && sudo rm -f /mnt/lab3/hidden.bin /root/lab3.img
df -h /                                                  # на корне тоже вернулось
```

- [ ] В журнале — все пять сценариев: симптом → команда, которая показала причину → починка
- [ ] Можешь назвать три причины расхождения `df` и `du` (удалённый-но-открытый файл, файлы под точкой
      монтирования, резерв root) и отдельно — нехватку inode
- [ ] Шаг B починил без перезапуска процесса и без перезагрузки

### 💥 Сломай сам

| Поломка | Что увидишь | Вывод |
|---------|-------------|-------|
| ⚠️ Со снапшотом: заполнить корень VM до конца (`sudo fallocate -l <свободно> /var/tmp/fill`) | составь список, что сломалось первым: heredoc в bash, `apt`, sudo, журнал, вход по SSH | почему алерт ставят на 80-85%, а не на 100% |
| Ротация лога без `postrotate`/`copytruncate` (лаба 2) + `compress` | место не освобождается после ротации | реальный источник сценария B в проде |
| `sudo tune2fs -m 0 /root/lab3.img` | `Avail` в `df` вырос | резерв 5% — место, где root сможет почистить систему; на дисках с данными его уменьшают |
| `: > file` вместо `rm file` для лога работающего процесса | место освобождается сразу | так чистят лог, который держит процесс |

### 🔗 Связь
- Темы: [10. Файловая система](/linux/10-the-filesystem) · [09. Устройства](/linux/09-devices) (loop-устройства) ·
  [07. Процессы](/linux/07-processes) (`/proc/PID/fd`) · [14. Утилизация процессов](/linux/14-process-utilization) (`lsof`, `fuser`) ·
  [15. Логирование](/linux/15-logging) (journald, logrotate)
- Без подсказок: инцидент 05 — `./incident.sh start 05`; инцидент 10 — позже, после блока баз данных

---

## 🧪 Лаба 4. «Сервер тормозит»: охота на процессы (темы 07, 12, 14)

**Цель:** по жалобе «всё медленно» найти каждого нарушителя, понять, что он делает и кто его запустил,
и убрать его с минимальным ущербом: не `kill -9` всему подряд.

**Стенд:** `learn-linux` · `vagrant snapshot save before_lab4`

### Каркас: четыре нарушителя

```bash
mkdir -p ~/lab4 && cd ~/lab4

cat > watchdog.sh <<'EOS'
#!/usr/bin/env bash
# «сторож»: перезапускает «отчёт», если его убили
while :; do
  bash -c 'while :; do :; done' &
  wait $!
  sleep 2
done
EOS

cat > cache.py <<'EOS'
import time
chunks = []
while len(chunks) < 50:                 # до ~500 МБ: по 10 МБ каждые 2 секунды
    chunks.append(b"x" * 10 * 1024 * 1024)
    time.sleep(2)
time.sleep(86400)
EOS

cat > sync.py <<'EOS'
open("/tmp/lab4.fifo").read()           # висит, пока в FIFO никто не напишет
EOS

cat > legacy.py <<'EOS'
import os, time
if os.fork() == 0:
    os._exit(0)                         # потомок сразу завершается...
time.sleep(86400)                       # ...а родитель не делает wait()
EOS

cat > start.sh <<'EOS'
#!/usr/bin/env bash
cd ~/lab4 && mkfifo /tmp/lab4.fifo 2>/dev/null || true
nohup bash -c 'exec -a report-watchdog bash ./watchdog.sh'  >/dev/null 2>&1 &
nohup bash -c 'exec -a cache-warmer python3 ./cache.py'     >/dev/null 2>&1 &
nohup bash -c 'exec -a sync-agent python3 ./sync.py'        >/dev/null 2>&1 &
nohup bash -c 'exec -a legacy-daemon python3 ./legacy.py'   >/dev/null 2>&1 &
echo "запущено. Выйди из VM, зайди заново и начни с uptime"
EOS
chmod +x start.sh && ./start.sh
```

### Шаги
1. **Общая картина:** `uptime` и `nproc` — насколько загружено и растёт ли; `vmstat 1 5` — где давление:
   `r` (очередь CPU), `b` и `wa` (I/O), `si/so` (swap).
2. **CPU:** `top` (сортировка `P`, по ядрам `1`), `ps -eo pid,ppid,stat,ni,%cpu,rss,etime,args --sort=-%cpu | head`.
   Убей нарушителя через SIGTERM — и посмотри, как он вернётся с новым PID. Найди, кто его перезапускает:
   `ps -o ppid= -p PID`, `pstree -p`. Прежде чем убивать, попробуй `renice +19`: иногда достаточно понизить приоритет.
   Разбери, что станет с потомком, если убить только «сторожа» (сирота → PID 1).
3. **Память:** `free -h` (смотри `available`, а не `free`), `top` → `M`, `ps --sort=-rss`.
   Растёт ли RSS со временем: `watch -n2 'ps -o pid,rss,args -C python3'`.
4. **Завис:** процесс не ест ничего, но «ничего не делает». `cat /proc/PID/status` (State),
   `cat /proc/PID/wchan` — где в ядре он спит; `sudo strace -p PID` — на каком системном вызове висит
   и с каким файлом. `ls -l /proc/PID/fd`, `ls -l /proc/PID/cwd`. Разблокируй **причину**, а не процесс.
5. **Зомби:** `ps -eo pid,ppid,stat,args | awk '$3 ~ /^Z/'`. Попробуй `kill -9` зомби — ничего не изменится.
   Разбери почему и что на самом деле надо сделать с его родителем.
6. **Системные вызовы:** `sudo timeout 5 strace -c -p PID` для «отчёта» и для `sync-agent`.
   Сравни: у бесконечного цикла syscalls почти нет (время в user space — `us` в top),
   у зависшего — один вызов, который не возвращается.

### Проверка результата

Таблица в журнал:

| PID | PPID | Что это | Каким ресурсом мешал | Чем нашёл | Что сделал и почему так |
|-----|------|---------|----------------------|-----------|-------------------------|

```bash
uptime                                              # через пару минут 1-мин LA → около 0
ps -eo stat= | grep -c '^Z'                         # 0
pgrep -af 'report-watchdog|cache-warmer|sync-agent|legacy-daemon'   # пусто
free -h                                             # available вернулся
```

- [ ] Нашёл все четыре нарушителя и родителя-«сторожа»
- [ ] `kill -9` использовал не больше одного раза и можешь объяснить, где он был оправдан
- [ ] Можешь объяснить, из чего сложился load average и почему он падает не мгновенно

### 💥 Сломай сам

| Эксперимент | Что увидишь | Вывод |
|-------------|-------------|-------|
| `kill -STOP` «отчёта», потом `kill -CONT` | состояние `T`, CPU отпустило, потом снова | остановить ≠ убить; так «ставят на паузу» |
| `sudo systemd-run --unit=lab4-oom -p MemoryMax=200M -p MemorySwapMax=0 python3 ~/lab4/cache.py` | юнит убит OOM, `Result: oom-kill` | `journalctl -k -g oom`, `systemctl status lab4-oom`; лимиты — это cgroups |
| ⚠️ Со снапшотом: `sudo systemd-run --scope -p TasksMax=100 bash -c ':(){ :\|:& };:'` | fork-бомба упирается в лимит, система жива | `systemctl stop run-*.scope`; вот зачем `TasksMax` и `pids`-лимиты в контейнерах |
| `nice -n 19` для одного «отчёта» и обычный второй рядом | `top`: доли CPU делятся неравно | nice — про очередь на CPU, а не про лимит |

### 🔗 Связь
- Темы: [07. Процессы](/linux/07-processes) · [14. Утилизация процессов](/linux/14-process-utilization)
  (алгоритм «сервер тормозит») · [12. Ядро](/linux/12-kernel) (syscalls, strace) · [13. init и systemd](/linux/13-init) (cgroups через systemd)
- Без подсказок: инцидент 04 — `./incident.sh start 04`

---

## 🧪 Лаба 5. «Сайт не открывается»: семь поломок сети на одной VM (темы 13, 17-22)

**Цель:** по симптому «не открывается» за 6 команд определить звено: процесс → адрес/порт → имя →
DNS → маршрут → файрвол. Различать `connection refused`, таймаут, `Could not resolve host`
и `Network is unreachable`.

**Стенд:** `learn-linux` с сервисом `shop` из лабы 2 · `vagrant snapshot save before_lab5`

### Подготовка

```bash
# на VM
IF=$(ip route show default | awk '{print $5; exit}')
IP=$(ip -4 -o addr show dev "$IF" | awk '{print $4}' | cut -d/ -f1)
echo "$IP shop.lab" | sudo tee -a /etc/hosts
curl -s http://shop.lab:8080/health                      # ok

# на хосте
cd ~/Projects/devops/stands/learn-linux
VM_IP=$(vagrant ssh-config | awk '/HostName/{print $2}')
curl -s -m 3 http://"$VM_IP":8080/health                 # ok — «снаружи»
```

Скрипт-«ломатель» (на VM, запускать через `sudo`):

```bash
cat > ~/lab5-break.sh <<'EOS'
#!/usr/bin/env bash
# Ломает одно звено из семи
set -euo pipefail
IF=$(ip route show default | awk '{print $5; exit}')
case $((RANDOM % 7 + 1)) in
  1) systemctl stop shop ;;                                                  # процесс
  2) sed -i 's/^SHOP_BIND=.*/SHOP_BIND=127.0.0.1/' /etc/shop/shop.env
     systemctl restart shop ;;                                               # адрес
  3) sed -i 's/^SHOP_PORT=.*/SHOP_PORT=8081/' /etc/shop/shop.env
     systemctl restart shop ;;                                               # порт
  4) sed -i 's/^[0-9.]* shop\.lab$/10.255.255.1 shop.lab/' /etc/hosts ;;     # имя
  5) resolvectl dns "$IF" 192.0.2.53 && resolvectl flush-caches ;;           # DNS
  6) ip route del default ;;                                                 # маршрут
  7) iptables -I INPUT -p tcp --dport 8080 ! -i lo -j DROP ;;                # файрвол
esac
echo "сломано, чини"
EOS
chmod +x ~/lab5-break.sh
```

> Скрипт ты пишешь сам, поэтому запускай его и **не смотри**, какой номер выпал. Починил → проверил
> все четыре клиента → снова `sudo ~/lab5-break.sh`. Пока не пройдёшь все семь.

### Шаги

1. Четыре «клиента», которыми проверяешь симптом:
   ```bash
   curl -sS -m 3 http://shop.lab:8080/health     # VM: по имени
   curl -sS -m 3 http://127.0.0.1:8080/health    # VM: локально
   curl -sSI -m 5 https://example.com | head -1  # VM: интернет
   curl -sS -m 3 http://"$VM_IP":8080/health     # хост: снаружи
   ```
   Уже по сочетанию «работает / не работает» и тексту ошибки половина вариантов отпадает — запиши гипотезу.
2. Иди по звеньям, **не перескакивая**:
   - процесс: `systemctl status shop`, `journalctl -u shop -n 20`;
   - адрес и порт: `ss -tlnp | grep python` — какой порт, `0.0.0.0` или `127.0.0.1`; `systemctl cat shop` — откуда конфиг;
   - имя: `getent hosts shop.lab` и `dig +short shop.lab` — почему ответы разные;
   - DNS: `resolvectl status`, `dig example.com`, `dig @1.1.1.1 example.com` — виноват резолвер или сеть;
   - маршрут: `ip route`, `ip route get 1.1.1.1`;
   - файрвол: `sudo iptables -L INPUT -n -v --line-numbers`, `sudo tcpdump -ni any port 8080`.
3. Почини **причину** так, чтобы починка пережила `systemctl restart shop` (для 2, 3, 4, 7)
   и переподключение сети (для 5, 6). Если потерялся — `vagrant snapshot restore before_lab5`.

> ⚠️ Не выключай интерфейс управления (`ip link set "$IF" down`) — потеряешь `vagrant ssh`.
> Поломки L1-L2 — на стенде из двух VM в блоке Network (практические лабы).

### Проверка результата

Таблица в журнал, по строке на каждую из семи поломок:

| Что сломано (нашёл сам) | По имени | Локально | Интернет | Снаружи | Команда, которая показала причину | Починка |
|-------------------------|----------|----------|----------|---------|-----------------------------------|---------|

- [ ] Каждую поломку нашёл не больше чем за 6 команд
- [ ] По тексту ошибки `curl` сразу называешь класс проблемы: refused → никто не слушает;
      таймаут соединения → пакеты теряются или уходят не туда; `Could not resolve host` / `Resolving timed out` →
      имя или DNS; `Network is unreachable` → маршрут
- [ ] Объясняешь, почему при поломке 2 сайт открывается только по `127.0.0.1`, а при поломке 7 — с самой VM
      по любому адресу, но не с хоста, и почему ошибки у хоста в этих двух случаях разные
- [ ] ⭐ После тем 23-24: `sitecheck.sh URL` — сам проходит звенья по порядку и говорит, где проблема

### 💥 Сломай сам
- Добавь в скрипт ещё две поломки на выбор: опечатка в имени в `/etc/hosts`, `REJECT` вместо `DROP`,
  `iptables -A OUTPUT -p udp --dport 53 -j DROP` (исходящий DNS). Опиши, чем их симптомы отличаются от уже пройденных.
- Сделай поломку 7 «постоянной» через `netfilter-persistent`, перезагрузи VM и найди её уже после ребута.

### 🔗 Связь
- Темы: [17. Основы сети](/linux/17-network-basics) · [19. Маршрутизация](/linux/19-routing) · [20. Настройка сети](/linux/20-network-config) ·
  [21. Диагностика](/linux/21-troubleshooting) (алгоритм «сайт не открывается») · [22. DNS](/linux/22-dns) · [13. init и systemd](/linux/13-init) (`EnvironmentFile`)
- Без подсказок: инциденты **07** (после 22) и **08** (полностью — после тем 04 и 11 блока Network)
- Глубже: весь блок Network — он следующий после Linux

---

## 🧪 Лаба 6. «Сервер не загрузился»: битый fstab → emergency mode → починка (темы 10, 11, 13, 15)

**Цель:** один раз своими руками поднять сервер, который не грузится, — пока это учебная VM,
а не прод в три часа ночи. Понять, зачем `nofail` и почему fstab проверяют **до** перезагрузки.

**Стенд:** `learn-linux` · **обязательно** `vagrant snapshot save before_lab6` — без него не начинать.

### Подготовка: доступ к консоли (до того, как ломать!)

SSH в emergency mode не работает — нужна консоль VM.
1. На хосте: `virsh -c qemu:///system list --all` — имя домена (обычно `learn-linux_learn-linux`).
2. Консоль: **virt-manager** → VM → *Open* (графическая консоль, работает всегда) или
   `virsh -c qemu:///system console <домен>` — только если в `cat /proc/cmdline` есть `console=ttyS0`.
3. Меню GRUB должно быть видно: в `/etc/default/grub` — `GRUB_TIMEOUT_STYLE=menu`, `GRUB_TIMEOUT=5`,
   затем `sudo update-grub` (тема 11, мини-лаба).
4. Есть ли у root пароль: `sudo passwd -S root`. `L` — заблокирован (типично для Ubuntu):
   emergency shell тебя **не пустит**, будет сценарий Б. Для сценария А задай root временный пароль.
5. Журнал персистентный: `ls /var/log/journal` — иначе после починки не увидишь логи сломанной загрузки.

### Шаги

1. **Поломка 1 — диска нет.** Добавь в `/etc/fstab` строку с несуществующим UUID и **без** `nofail`:
   ```bash
   sudo cp /etc/fstab /etc/fstab.bak
   echo 'UUID=deadbeef-0000-4000-8000-000000000000 /mnt/data ext4 defaults 0 2' | sudo tee -a /etc/fstab
   sudo findmnt --verify          # посмотри: проверка это ловит — в проде на этом всё и заканчивается
   sudo systemctl daemon-reload && sudo reboot
   ```
2. В консоли смотри на загрузку: полторы минуты `A start job is running for /dev/disk/by-uuid/...`,
   потом `Dependency failed for Local File Systems` → emergency mode.
3. **Сценарий А (у root есть пароль):** войди → `journalctl -xb | grep -iE 'timed out|dependency failed'`
   → если `/` только для чтения — `mount -o remount,rw /` → закомментируй строку в `/etc/fstab` →
   `systemctl daemon-reload` → `mount -a` (ошибок нет) → `systemctl default` или `reboot`.
4. **Сценарий Б (root заблокирован, как в облаке):** `Cannot open access to console, the root account is locked`.
   Перезагрузи VM из virt-manager, в меню GRUB нажми `e`, в конец строки `linux …` допиши `init=/bin/bash`,
   `Ctrl+X` → root-shell без пароля → `mount -o remount,rw /` → почини fstab → `sync` → `reboot -f`
   (systemd здесь не PID 1, поэтому `systemctl` не работает). Разбери, почему это же — способ сбросить пароль root
   и почему консольный доступ к серверу = root.
5. **Поломка 2 — опечатка в опциях.** Настоящий файл-диск, но `defualts` вместо `defaults`:
   ```bash
   sudo truncate -s 100M /root/lab6.img && sudo mkfs.ext4 -q -F /root/lab6.img && sudo mkdir -p /mnt/lab6
   echo '/root/lab6.img /mnt/lab6 ext4 loop,defualts 0 2' | sudo tee -a /etc/fstab
   sudo systemctl daemon-reload && sudo reboot
   ```
   Почини вторым сценарием, которым ещё не пользовался. Найди в журнале **точную** строку с ошибкой монтирования.
6. **Как надо:** верни строку с несуществующим UUID, но с `nofail,x-systemd.device-timeout=10s`, перезагрузи.
   Система поднялась через ~10 секунд ожидания, `/mnt/data` не смонтирован (`findmnt /mnt/data` пуст),
   а в `journalctl -b` видно, что устройство не дождались. Это и есть правильное поведение для дисков с данными:
   сервер жив и доступен, проблему видно в журнале и мониторинге.
7. **После каждой починки:** `journalctl -b -1 -p err` — ошибки прошлой (сломанной) загрузки;
   `systemd-analyze` и `systemd-analyze blame | head` — сколько стоила поломка.

### Проверка результата

```bash
systemctl is-system-running        # running (если degraded — объясни, что упало)
systemctl --failed
sudo findmnt --verify              # без ошибок
diff /etc/fstab.bak /etc/fstab     # в fstab только то, что ты оставил сознательно
journalctl --list-boots | tail -5  # видны сломанные загрузки
```

- [ ] Поднял VM обоими сценариями — с паролем root и без
- [ ] Можешь пересказать инструкцию «сервер ушёл в emergency» по шагам, не глядя
- [ ] Объясняешь разницу `nofail` и `x-systemd.device-timeout` и когда какой нужен

### 💥 Сломай сам

| Поломка | Что увидишь | Как выбраться |
|---------|-------------|---------------|
| В `init=/bin/bash` сохранить fstab, не сделав remount | `Read-only file system` | `mount -o remount,rw /` |
| Только `x-systemd.device-timeout=10s` без `nofail` | emergency, но через 10 секунд | таймаут ускоряет падение, а не отменяет его |
| `sudo systemctl set-default rescue.target` + reboot | `vagrant ssh` не работает, в консоли rescue | `systemctl set-default multi-user.target` |
| Одноразово в GRUB (`e`) дописать `init=/nonexistent` | `Kernel panic - not syncing: No working init found` | просто перезагрузись: правка через `e` не сохраняется |
| `mount -a` после правки fstab без `daemon-reload` | предупреждение про изменённый fstab | systemd строит mount-юниты из fstab генератором |

### 🔗 Связь
- Темы: [10. Файловая система](/linux/10-the-filesystem) (fstab, UUID, `nofail`) · [11. Загрузка системы](/linux/11-boot-the-system)
  (GRUB, `init=/bin/bash`, emergency) · [13. init и systemd](/linux/13-init) (таргеты) · [15. Логирование](/linux/15-logging) (`journalctl -b -1`) ·
  [00. Стенд: Vagrant](/linux/00-vagrant) (снапшоты)
- Без подсказок: инцидент 06 — ещё один сценарий «после перезагрузки не поднялось», уже про сервис

---

## 🧪 Лаба 7. Итоговая: стенд web + app и бэкап-скрипт по systemd-таймеру (весь блок)

**Цель:** собрать всё из блока на двух машинах и закончить скриптом, который можно без стыда
оставить работать по ночам. Это «Итоговая лаба» дня 21 плана (часть A)
и мини-проекты оттуда же: 2 и 3 — в части A, 4 и 6 — в части B, ⭐ 1 — дополнительно в части B.

**Стенд:** `~/Projects/devops/stands/net-lab` — `web` 192.168.56.10 и `app` 192.168.56.11.
`vagrant up && vagrant snapshot save before_lab7` (в мульти-VM без имени машины снапшот делается для всех VM).

> В конспекте темы 17 VM названы `web01`/`db01` (.10/.20). В `Vagrantfile` стенда —
> `web`/`app` (.10/.11): ориентируйся на `Vagrantfile`. Роль «db-ноды» здесь играет `app`:
> на ней живут данные сервиса (`/var/lib/shop`).

### Часть A — стенд (день 21, после тем 01-22)

**Роли**
```text:no-line-numbers
хост ──► web (192.168.56.10)  nginx :80 ── статика /var/www/shop
                                   └── /api/ ──► app:8080
          app (192.168.56.11)  shop.service (лаба 2) на 192.168.56.11:8080, данные в /var/lib/shop
```

**Требования**
- [ ] Имена: `web` и `app` находят друг друга по имени через `/etc/hosts` (тема 22), проверка — `getent hosts`
- [ ] Время: одна таймзона и синхронизированный NTP на обеих (`timedatectl`), иначе логи двух машин не сопоставить
- [ ] Пользователи из лабы 1 на обеих: `alice` с ключом и узким sudo, вход по паролю закрыт, root по SSH не пускают
- [ ] На `web` — пользователь `backup` с входом только по ключу и каталогом `/srv/backups/app` (для части B)
- [ ] На `app` — `shop` как systemd-сервис из лабы 2, слушает **только** `192.168.56.11:8080`;
      health-check поправлен на этот адрес. Разбери, зачем `Wants=` + `After=network-online.target`,
      когда сервис слушает конкретный IP (подсказка: `Cannot assign requested address` при загрузке)
- [ ] На `web` — nginx из apt со своим сайтом, `nginx -t` перед каждым `reload`
- [ ] Логи: access.log nginx на `web` разбираешь однострочником (топ IP, коды ответов — темы 03-04),
      `journalctl -u shop` на `app`; ⭐ `web` отправляет syslog на `app` по TCP (тема 15, `@@app:514`)
- [ ] Всё переживает `vagrant reload`

Минимальный конфиг nginx (подробно nginx — в блоке Network, тема 12):
```nginx
# /etc/nginx/sites-available/shop  (+ симлинк в sites-enabled, default — убрать)
server {
    listen 80;
    server_name _;
    root /var/www/shop;
    location / { try_files $uri $uri/ =404; }
    location /api/ {
        proxy_pass http://app:8080/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**Проверка части A**
```bash
# с хоста
curl -s http://192.168.56.10/                    # статика
curl -s http://192.168.56.10/api/                # ответ shop: "host": "app"
ssh -i ~/.ssh/learn_alice alice@192.168.56.10 'sudo -n systemctl restart nginx && echo ok'
ssh -o PubkeyAuthentication=no alice@192.168.56.11   # Permission denied (publickey)

# на app
ss -tlnp | grep 8080                              # 192.168.56.11:8080, не 0.0.0.0
# на web
getent hosts app
sudo awk '{print $9}' /var/log/nginx/access.log | sort | uniq -c | sort -rn

# с хоста: перезагрузка обеих и повтор проверок
vagrant reload
```

### Часть B — бэкап-скрипт по таймеру (после тем 23-25, лучше после 26)

`shop-backup.sh` на `app` архивирует данные и конфиг сервиса и увозит их на `web`.
Бэкап, который лежит на той же машине, — не бэкап.

**Скрипт**
- [ ] `#!/usr/bin/env bash`, `set -euo pipefail`, кавычки вокруг всех переменных
- [ ] `getopts`: `-d host:path` (куда), `-k N` (сколько копий хранить, по умолчанию 7), `-n` (dry-run —
      только печатает, что сделал бы), `-h` (usage); неизвестная опция → usage и код 2
- [ ] `trap … EXIT` удаляет временный каталог (`mktemp -d`) при любом исходе; `INT`/`TERM` → коды 130/143
- [ ] `flock -n`: второй экземпляр сразу выходит с кодом 3 и понятным сообщением
- [ ] Архив `/var/lib/shop` + `/etc/shop` → `shop-YYYY-MM-DD_HHMMSS.tar.gz` + файл `.sha256`
- [ ] Доставка: `rsync` по SSH пользователем `backup` по ключу, `ssh -o BatchMode=yes` (скрипт никогда не ждёт ввода)
- [ ] Сетевые шаги — 3 попытки с экспоненциальной паузой (тема 26)
- [ ] Ротация на `web`: остаются последние N архивов
- [ ] Проверка: контрольная сумма на `web` совпала, иначе это ошибка, а не «успех»
- [ ] Сообщения с уровнем в stdout/stderr (под systemd они сами попадут в журнал); коды выхода перечислены в `-h`
- [ ] `shellcheck` — ноль замечаний

**systemd**
- [ ] `shop-backup.service`: `Type=oneshot`, свой пользователь, **не root**; читать `/var/lib/shop` и `/etc/shop`
      ему разрешено через группу или ACL (лаба 1)
- [ ] `shop-backup.timer`: `OnCalendar=*-*-* 03:00:00`, `Persistent=true`, `RandomizedDelaySec=`
- [ ] ⭐ `OnFailure=` → юнит-уведомление (запись в журнал с приоритетом `err`, `wall` или webhook через `curl`)
- [ ] ⭐ Мини-проект 1: `healthcheck.sh` (CPU, RAM, диск, сервисы → строка в журнал + код выхода)
      по тому же шаблону service + timer

**Восстановление и git**
- [ ] Восстановление проверено: `shop` остановлен, `/var/lib/shop` пуст → данные вернулись из архива с `web` → `shop` снова отвечает
- [ ] Всё в git-репозитории: `scripts/`, `systemd/`, `nginx/`, `README.md` (как поставить, коды выхода, как восстановить)

**Проверка части B**
```bash
# на app
shellcheck /usr/local/bin/shop-backup.sh          # пусто
shop-backup.sh -h; echo $?                         # usage, 0
shop-backup.sh -x; echo $?                         # usage, 2
sudo -u <пользователь-бэкапа> shop-backup.sh -n -d backup@web:/srv/backups/app   # dry-run: на web ничего не появилось
sudo systemctl start shop-backup.service
systemctl status shop-backup --no-pager            # status=0/SUCCESS
journalctl -u shop-backup -n 20 --no-pager         # понятный рассказ, что было сделано
systemctl list-timers shop-backup.timer            # следующий запуск ~03:00

# на web
ls -lt /srv/backups/app | head
cd /srv/backups/app && sha256sum -c "$(ls -t *.sha256 | head -1)"   # OK
ls /srv/backups/app/*.tar.gz | wc -l               # не больше N
```

### 💥 Сломай сам

| Поломка | Что должно произойти |
|---------|----------------------|
| Два запуска одновременно (руками и через `systemctl start`) | второй выходит с кодом 3, первый не пострадал |
| Удалить ключ `backup` или `known_hosts` на `app` | падение за секунды с понятной ошибкой в журнале; скрипт не висит на `yes/no` |
| Забить диск на `web` (лаба 3) | rsync падает → код ≠ 0 → юнит `failed` → сработал `OnFailure`; обрезанный архив не считается бэкапом |
| `kill -TERM` скрипта посреди архивации | `trap` убрал временный каталог, код 143 |
| Закомментировать `set -euo pipefail` и повторить поломки выше | посчитай, сколько из них внезапно стали «успехом» |
| Выключить `app` через 03:00 (`OnCalendar` на пару минут вперёд, `vagrant halt app`), потом включить | `Persistent=true` догнал пропущенный запуск: `journalctl -u shop-backup -b` |
| Остановить `shop` на `app` | `/api/` на `web` отдаёт `502 Bad Gateway`; найди строку в `/var/log/nginx/error.log` |
| Убрать `app` из `/etc/hosts` на `web` и перезапустить nginx | nginx не стартует: `host not found in upstream` — `nginx -t` сказал бы это заранее |

### 🔗 Связь
- Темы: [23. Основы bash](/linux/23-bash-basics) · [24. Условия и циклы](/linux/24-bash-control-flow) ·
  [25. Надёжный bash-скрипт](/linux/25-bash-robust) (шаблон боевого скрипта) · [26. Bash в DevOps](/linux/26-bash-devops-practice) (ретраи) ·
  [16. Сетевые шары](/linux/16-network-sharing) (rsync) · [13. init и systemd](/linux/13-init) (таймеры) · [15. Логирование](/linux/15-logging) ·
  [22. DNS](/linux/22-dns) · лабы 1-3 этого файла
- Без подсказок: 02-nightshift — ночной регламент для `linkd` (уровни L2-L3) · 01-logsleuth — разбор
  логов nginx и приложения по-взрослому · инцидент 03 — `./incident.sh start 03`

---

## 🏆 Что должно остаться после лаб

| Артефакт | Из лабы | Зачем |
|----------|---------|-------|
| `sudoers.d/developers`, `sshd_config.d/10-hardening.conf`, схема прав `/srv/shop` | 1 | доступы по принципу наименьших привилегий: вопрос почти любого собеса |
| `shop.service` с hardening, `shop-health.{service,timer}`, `logrotate.d/shop` | 2 | «напиши юнит для приложения» — самое частое практическое задание |
| Журнал «диск полон»: пять сценариев | 3 | готовый ответ на live-сценарий «нет места» |
| Таблица «процесс → чем мешал → как нашёл → что сделал» | 4 | готовый ответ на «сервер тормозит» |
| Таблица семи сетевых поломок | 5 | refused, таймаут, DNS и маршрут на реальных примерах |
| Инструкция «сервер ушёл в emergency mode» | 6 | ночной инцидент, который однажды случается у каждого |
| Репозиторий стенда: `scripts/`, `systemd/`, `nginx/`, `README.md` | 7 | портфолио: мини-проекты одним репозиторием |

> 💡 Журналы лаб — лучший материал для собеса: «однажды у меня `df` показывал 100%, а `du` — 20%…»
> звучит сильнее любого определения. Перед собесом перечитай их вместе с [28. Вопросы с собеседований](/linux/28-interview).

Дальше: [28. Вопросы с собеседований](/linux/28-interview) — проверь себя вопросами с собеседований и live-траблшутингом.
