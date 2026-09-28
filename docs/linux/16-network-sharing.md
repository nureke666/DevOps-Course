---
title: "16. Network Sharing"
description: "rsync, NFS, Samba, HTTP: как передавать и расшаривать файлы между серверами"
---

# 16. Network Sharing — rsync, NFS, Samba, HTTP

> Источник: `16_network_sharing.txt` (Networking Nomad, 5 уроков)
> **После темы ты умеешь:** копировать файлы между серверами, поднимать сетевые шары
> и быстро раздавать файлы по HTTP. `rsync` — один из самых используемых инструментов DevOps.

---

## 🗺️ Схема: чем передавать файлы

```text:no-line-numbers
                       НАДО ПЕРЕДАТЬ ФАЙЛЫ
                               │
      ┌────────────────────────┼────────────────────────┐
      ▼                        ▼                        ▼
  РАЗОВО / СКРИПТОМ      ПОСТОЯННЫЙ ДОСТУП        БЫСТРО ОТДАТЬ
  ┌──────────────┐       ┌────────────────┐      ┌──────────────┐
  │ scp  — просто│       │ NFS  — Linux↔  │      │ python3 -m   │
  │ rsync — умно │       │        Linux   │      │ http.server  │
  │ sftp — интер.│       │ Samba/CIFS —   │      │              │
  │              │       │        Windows │      │ nc / curl    │
  └──────────────┘       └────────────────┘      └──────────────┘
         │                        │
         └── для бэкапов          └── общие данные, домашние каталоги,
             и деплоя                 хранилище для нескольких серверов
```

---

## 1. File Sharing Overview

| Протокол | Порт | Для чего | Особенности |
|----------|------|----------|-------------|
| **SSH/SCP/SFTP** | 22 | Разовая передача, деплой | Шифрование, есть везде |
| **rsync** | 22 (через SSH) или 873 | Синхронизация, бэкапы | Передаёт **только изменения** |
| **NFS** | 2049 | Общий каталог Linux↔Linux | Родные права UNIX, быстро |
| **SMB/CIFS (Samba)** | 445 | Windows-совместимость | Своя аутентификация |
| **FTP** | 21 | Устарел | 🔴 Пароли открытым текстом — не использовать |
| **HTTP** | 80/8000 | Быстро раздать/скачать | Односторонне, просто |
| **S3/объектное хранилище** | 443 | Облачное хранение | Современный стандарт для бэкапов |

```bash
# scp — простое копирование
scp file.txt user@host:/path/            # туда
scp user@host:/path/file.txt ./          # оттуда
scp -r dir/ user@host:/path/             # рекурсивно
scp -P 2222 file user@host:/path/        # нестандартный порт (заглавная P!)
scp -i ~/.ssh/key file user@host:/path/

# sftp — интерактивно
sftp user@host
# get file / put file / ls / cd / bye
```

⚠️ У `scp` порт задаётся `-P`, у `ssh` — `-p`. Классическая путаница.
Начиная с OpenSSH 9, `scp` использует протокол SFTP под капотом; для новых скриптов
рекомендуют `sftp` или `rsync`.

---

## 2. rsync — главный инструмент темы

Ключевая идея: rsync передаёт **только различия** (delta-transfer), поэтому повторная
синхронизация 100 ГБ, где изменился один файл, занимает секунды.

```bash
rsync -avz /src/ user@host:/dst/
#      ││└─ z: сжатие при передаче
#      │└── v: подробный вывод
#      └─── a: archive = -rlptgoD (рекурсивно + права + владелец + время + симлинки)
```

Основные опции:

| Опция | Смысл |
|-------|-------|
| `-a` | Архивный режим: рекурсия, права, владелец, время, симлинки, устройства |
| `-v` / `-vv` | Подробность |
| `-z` | Сжатие в канале (полезно по сети, вредно для локального диска) |
| `-P` | = `--partial --progress`: прогресс + докачка при обрыве |
| `-h` | Человекочитаемые размеры |
| **`-n`** / `--dry-run` | **Пробный прогон** ← всегда делай первым |
| `--delete` | Удалить в приёмнике то, чего нет в источнике (🔴 опасно) |
| `--exclude='pattern'` | Исключить |
| `--exclude-from=file` | Список исключений из файла |
| `--bwlimit=10000` | Ограничить скорость (КБ/с) — чтобы не забить канал |
| `-e 'ssh -p 2222 -i key'` | Настроить транспорт |
| `--link-dest=DIR` | Инкрементальные бэкапы через жёсткие ссылки |
| `--checksum` | Сравнивать по контрольной сумме, а не по размеру/времени |
| `--stats` | Итоговая статистика |

🔴 **Самая важная деталь rsync — СЛЕШ в конце источника:**

```bash
rsync -av /src  /dst/      # → /dst/src/...   скопирует САМ каталог
rsync -av /src/ /dst/      # → /dst/...       скопирует СОДЕРЖИМОЕ каталога
```
Одна ошибка здесь + `--delete` = удалённые данные. Поэтому **всегда `--dry-run` первым**.

Боевые примеры:

```bash
# Бэкап на удалённый сервер
rsync -avzP --delete /var/www/ backup@nas:/backups/www/

# Деплой с исключениями
rsync -avz --exclude='.git' --exclude='node_modules' --exclude='*.log' \
      ./app/ deploy@web:/opt/app/

# Через нестандартный порт и с ключом
rsync -avzP -e 'ssh -p 2222 -i ~/.ssh/deploy_key' ./dist/ deploy@host:/var/www/

# Ограничить скорость, чтобы не мешать проду
rsync -avz --bwlimit=5000 /data/ backup@nas:/backups/data/

# Инкрементальные бэкапы с дедупликацией (гениальный трюк)
rsync -av --delete --link-dest=/backup/latest /data/ /backup/$(date +%F)/
ln -sfn /backup/$(date +%F) /backup/latest
#   неизменённые файлы не копируются, а становятся ЖЁСТКИМИ ССЫЛКАМИ
#   → каждый бэкап выглядит полным, а места занимает как инкрементальный

# Только сравнить, что отличается
rsync -avn --delete /src/ /dst/
```

💼 `rsync` — основа простых бэкап-систем, деплой-скриптов, миграций серверов и синхронизации
статики. Знать его опции обязательно.

---

## 3. Simple HTTP Server — быстро раздать файлы

```bash
python3 -m http.server 8000                  # раздать текущий каталог
python3 -m http.server 8000 --bind 127.0.0.1 # только локально (безопаснее)
python3 -m http.server 8000 --directory /opt/files

# На клиенте
curl -O http://192.168.1.10:8000/file.tar.gz
wget http://192.168.1.10:8000/file.tar.gz
```

Другие быстрые способы:
```bash
# netcat: отправить файл (на приёмнике)
nc -l -p 9000 > received.tar.gz
# и на отправителе
nc 192.168.1.10 9000 < file.tar.gz

# Передать каталог одной командой
tar czf - /path/dir | ssh user@host 'tar xzf - -C /dst'
```

⚠️ `http.server` — **без аутентификации и шифрования**. Пригоден для локальной сети и
краткосрочных задач (закинуть бинарник на тестовый сервер), но не для прода и не для секретов.
Не забудь остановить (`Ctrl+C`) — забытый сервер, раздающий `/`, это инцидент безопасности.

---

## 4. NFS — Network File System

Родная сетевая ФС UNIX: каталог сервера монтируется на клиентах как локальный.

### Сервер

```bash
sudo apt install -y nfs-kernel-server
sudo mkdir -p /srv/nfs/shared
sudo chown nobody:nogroup /srv/nfs/shared

# Экспорт
sudo tee -a /etc/exports >/dev/null <<'EOF'
/srv/nfs/shared  192.168.56.0/24(rw,sync,no_subtree_check)
EOF

sudo exportfs -ra              # применить
sudo exportfs -v               # проверить, что экспортировано
sudo systemctl enable --now nfs-kernel-server
```

Опции экспорта:

| Опция | Смысл |
|-------|-------|
| `rw` / `ro` | Чтение-запись / только чтение |
| `sync` | Подтверждать запись после реальной записи (надёжно) |
| `async` | Быстрее, но риск потери данных при сбое |
| `no_subtree_check` | Рекомендуется (быстрее и надёжнее) |
| `root_squash` | **По умолчанию**: root клиента → `nobody` (безопасно) |
| `no_root_squash` | 🔴 root клиента = root сервера — почти всегда дыра |
| `all_squash` | Все пользователи → anonymous |

### Клиент

```bash
sudo apt install -y nfs-common
showmount -e 192.168.56.10                 # что экспортирует сервер
sudo mkdir -p /mnt/nfs
sudo mount -t nfs 192.168.56.10:/srv/nfs/shared /mnt/nfs
df -hT /mnt/nfs

# Постоянно — в /etc/fstab:
# 192.168.56.10:/srv/nfs/shared /mnt/nfs nfs defaults,_netdev,nofail,soft,timeo=30 0 0
```

⚠️ **Важные грабли NFS:**
- Права определяются **UID/GID**, а не именами: если на сервере `appuser` = 1001, а на клиенте
  1001 — это `postgres`, доступ получит не тот пользователь. Решение — синхронизировать UID
  (или использовать NFSv4 с idmapd/Kerberos).
- **`hard` (по умолчанию) vs `soft`:** при `hard` процессы, обратившиеся к упавшему NFS,
  зависают в состоянии `D` **навсегда** — отсюда «load 100, CPU простаивает».
  `soft` + `timeo` вернёт ошибку, но возможна потеря данных при записи.
- В fstab обязательно `_netdev` и `nofail`, иначе сервер не загрузится при недоступном NFS.

---

## 5. Samba — SMB/CIFS для Windows

```bash
sudo apt install -y samba
sudo mkdir -p /srv/samba/share
sudo chown -R nobody:nogroup /srv/samba/share

sudo tee -a /etc/samba/smb.conf >/dev/null <<'EOF'
[share]
   path = /srv/samba/share
   browseable = yes
   read only = no
   guest ok = no
   valid users = @sambashare
   create mask = 0664
   directory mask = 0775
EOF

sudo smbpasswd -a vagrant           # ОТДЕЛЬНЫЙ пароль Samba, не системный!
sudo systemctl restart smbd nmbd
testparm                            # проверить конфиг
smbclient -L localhost -U vagrant   # список шар
```

Клиент Linux:
```bash
sudo apt install -y cifs-utils
sudo mount -t cifs //192.168.56.10/share /mnt/smb -o username=vagrant,uid=1000,gid=1000
# в fstab лучше с файлом учётных данных:
# //server/share /mnt/smb cifs credentials=/root/.smbcred,_netdev,nofail 0 0
```

| | NFS | Samba/CIFS |
|---|-----|------------|
| Родная среда | UNIX/Linux | Windows |
| Права | UNIX UID/GID | Пользователи Samba/AD |
| Производительность | выше в Linux-среде | ниже |
| Аутентификация | по IP/Kerberos | логин/пароль, AD |
| Когда выбирать | Linux↔Linux | смешанная среда, Windows-клиенты |

---

## 💼 Как это в DevOps

- **rsync** — деплой статики, бэкапы, миграция серверов, синхронизация артефактов. Must-know.
- **NFS** — общие данные между нодами (иногда как ReadWriteMany-том в Kubernetes), но это
  единая точка отказа и источник D-состояний: в современных системах предпочитают объектное
  хранилище (S3) или распределённые ФС (Ceph, GlusterFS).
- **Samba** — в основном legacy и интеграция с корпоративной Windows-средой.
- **`python3 -m http.server`** — быстро закинуть бинарник на тестовый хост; в проде — артефакт-репозиторий.
- Современный дефолт для бэкапов: `restic`/`borg` + S3 — дедупликация, шифрование, проверка целостности.

---

## 🧪 Мини-лаба

> Для полноценной практики нужны **две ВМ**. Готовый `Vagrantfile` — в конспекте
> [17. Network Basics](/linux/17-network-basics). Здесь — то, что можно сделать на одной ВМ.

```bash
vagrant ssh

# 1. rsync локально: понять слеш и --dry-run
mkdir -p ~/lab16/{src,dst} && cd ~/lab16
echo "file1" > src/a.txt; echo "file2" > src/b.txt; mkdir -p src/logs; echo "log" > src/logs/x.log

rsync -avn src  dst/          # ПРОБНЫЙ прогон: создаст dst/src/
rsync -avn src/ dst/          # ПРОБНЫЙ прогон: положит содержимое в dst/
rsync -av  src/ dst/
find dst -type f

# 2. Исключения
rm -rf dst/*
rsync -av --exclude='*.log' --exclude='logs/' src/ dst/
find dst -type f

# 3. --delete и почему нужен dry-run
echo "лишний" > dst/extra.txt
rsync -avn --delete src/ dst/      # покажет "deleting extra.txt"
rsync -av  --delete src/ dst/
ls dst/

# 4. Дельта-передача: rsync копирует только изменения
dd if=/dev/urandom of=src/big.bin bs=1M count=50 status=none
time rsync -av --stats src/ dst/ | tail -8      # первый раз — копирует всё
echo "изменение" >> src/a.txt
time rsync -av --stats src/ dst/ | tail -8      # второй раз — почти мгновенно

# 5. Инкрементальный бэкап с --link-dest
mkdir -p ~/lab16/backups
rsync -a --delete src/ ~/lab16/backups/2026-09-13/
ln -sfn ~/lab16/backups/2026-09-13 ~/lab16/backups/latest
echo "новое" > src/c.txt
rsync -a --delete --link-dest=$HOME/lab16/backups/latest src/ ~/lab16/backups/2026-09-14/
du -sh ~/lab16/backups/*                      # второй бэкап почти не занимает места
ls -li ~/lab16/backups/*/a.txt                # ОДИН inode — это жёсткие ссылки

# 6. rsync по SSH на себя же
rsync -avz -e ssh src/ vagrant@localhost:~/lab16/ssh_dst/
ls ~/lab16/ssh_dst/

# 7. HTTP-сервер
cd ~/lab16/src && python3 -m http.server 8000 --bind 127.0.0.1 &
sleep 1
curl -s http://127.0.0.1:8000/ | head
curl -sO http://127.0.0.1:8000/a.txt && cat a.txt
kill %1

# 8. Передача каталога через tar+ssh
tar czf - ~/lab16/src 2>/dev/null | ssh vagrant@localhost 'mkdir -p ~/lab16/tar_dst && tar xzf - -C ~/lab16/tar_dst'
find ~/lab16/tar_dst -type f | head

# 9. NFS на одной машине (сервер и клиент — локально)
sudo apt install -y nfs-kernel-server
sudo mkdir -p /srv/nfs/shared && sudo chown nobody:nogroup /srv/nfs/shared
echo "/srv/nfs/shared 127.0.0.1/32(rw,sync,no_subtree_check)" | sudo tee -a /etc/exports
sudo exportfs -ra && sudo exportfs -v
showmount -e 127.0.0.1
sudo mkdir -p /mnt/nfs && sudo mount -t nfs 127.0.0.1:/srv/nfs/shared /mnt/nfs
df -hT /mnt/nfs
echo "через NFS" | sudo tee /mnt/nfs/hello.txt
cat /srv/nfs/shared/hello.txt
sudo umount /mnt/nfs
sudo sed -i '\|/srv/nfs/shared|d' /etc/exports && sudo exportfs -ra
```

---

## 📌 Шпаргалка

| Задача | Команда |
|--------|---------|
| Скопировать файл | `scp file user@host:/path/` (порт — `-P`) |
| Синхронизировать | `rsync -avzP src/ user@host:/dst/` |
| **Пробный прогон** | `rsync -avn --delete src/ dst/` |
| Исключить | `rsync -av --exclude='.git' --exclude='*.log' src/ dst/` |
| Ограничить скорость | `rsync --bwlimit=5000 ...` |
| Инкрементальный бэкап | `rsync -a --delete --link-dest=/b/latest src/ /b/$(date +%F)/` |
| Нестандартный SSH | `rsync -av -e 'ssh -p 2222 -i key' src/ host:/dst/` |
| Быстро раздать по HTTP | `python3 -m http.server 8000 --bind 127.0.0.1` |
| Передать каталог | `tar czf - dir \| ssh host 'tar xzf - -C /dst'` |
| NFS сервер | `/etc/exports` + `exportfs -ra` |
| NFS клиент | `showmount -e SERVER`; `mount -t nfs SERVER:/path /mnt` |
| Samba | `smbpasswd -a user`; `smbclient -L host -U user` |

---

## 🧠 Что запомнить

1. **Слеш в конце источника rsync меняет смысл команды.** `src` → создаст подкаталог, `src/` → положит содержимое.
2. **Всегда `--dry-run` перед `--delete`.** Это разница между бэкапом и инцидентом.
3. `rsync` передаёт только изменения — поэтому он, а не `scp`, для регулярной синхронизации.
4. `--link-dest` даёт «полные» бэкапы по цене инкрементальных (жёсткие ссылки).
5. NFS: права по **UID/GID** — синхронизируй идентификаторы между хостами.
6. NFS в fstab — обязательно `_netdev,nofail`; `hard`-монтирование при падении сервера
   вешает процессы в состояние `D`.
7. `no_root_squash` в exports — почти всегда дыра в безопасности.
8. `python3 -m http.server` — без аутентификации; только временно и лучше с `--bind 127.0.0.1`.
9. FTP не использовать — пароли открытым текстом.

Дальше — [17. Network Basics](/linux/17-network-basics).

---

## Задачи

> `vagrant snapshot save before_16 && vagrant ssh`
> Часть заданий удобнее делать на двухнодовом стенде (Vagrantfile — в теме 17),
> но всё основное работает и на одной ВМ через `localhost`.

---

### Блок A. Теория

**A1.** Чем `rsync` принципиально отличается от `scp`? Когда какой выбирать?

<details><summary>Ответ</summary>

`scp` копирует файлы целиком каждый раз. `rsync` сравнивает источник и приёмник и
передаёт **только различия** (алгоритм delta-transfer), умеет сохранять атрибуты, исключения,
докачку, ограничение скорости, удаление лишнего, dry-run. Для разовой передачи одного файла
проще `scp`; для регулярной синхронизации, бэкапов и деплоя — только `rsync`.

</details>

**A2.** 🔑 В чём разница между `rsync -av /src /dst/` и `rsync -av /src/ /dst/`?
Почему это самая частая ошибка?

<details><summary>Ответ</summary>

`/src` (без слеша) означает «скопировать сам каталог» → появится `/dst/src/…`.
`/src/` (со слешем) — «скопировать содержимое» → файлы лягут прямо в `/dst/`. Ошибка частая,
потому что визуально разница минимальна, а в сочетании с `--delete` приводит к удалению данных
в приёмнике.

</details>

**A3.** Что делает опция `-a` в rsync? Из каких опций она состоит?

<details><summary>Ответ</summary>

`-a` (archive) = `-rlptgoD`: рекурсивно (`r`), сохранять симлинки (`l`), права (`p`),
время (`t`), группу (`g`), владельца (`o`), устройства и спецфайлы (`D`).

</details>

**A4.** Чем опасен `--delete`? Как страховаться?

<details><summary>Ответ</summary>

`--delete` удаляет в приёмнике всё, чего нет в источнике. При неверном пути источника
(или пустой переменной) это удаляет данные в приёмнике безвозвратно. Страховка: всегда
`--dry-run` первым, проверка переменных в скрипте, `--backup --backup-dir=`,
снапшоты/версионирование на стороне приёмника.

</details>

**A5.** Как работает `--link-dest` и почему бэкапы с ним занимают мало места?

<details><summary>Ответ</summary>

`--link-dest=DIR` сравнивает файлы с предыдущим бэкапом: неизменённые файлы не копируются,
а создаются как **жёсткие ссылки** на те же inode. Каждый каталог выглядит полным бэкапом,
но реально место занимают только изменённые файлы.

</details>

**A6.** Когда `-z` (сжатие) в rsync вредит?

<details><summary>Ответ</summary>

При копировании по быстрому локальному каналу (локальный диск, 10 Гбит/с LAN) или когда
данные уже сжаты (архивы, видео, зашифрованные файлы) — сжатие тратит CPU и **замедляет** передачу.

</details>

**A7.** Чем NFS отличается от Samba? Когда что выбирать?

<details><summary>Ответ</summary>

NFS — родная для UNIX сетевая ФС, права по UID/GID, высокая производительность
в Linux-среде. Samba реализует протокол SMB/CIFS для совместимости с Windows, со своей
аутентификацией и интеграцией с AD. Linux↔Linux — NFS; смешанная среда или Windows-клиенты — Samba.

</details>

**A8.** Почему при работе с NFS важна согласованность UID/GID между серверами?

<details><summary>Ответ</summary>

NFS передаёт по сети **числовые** UID/GID, а не имена. Если один и тот же UID
соответствует разным пользователям на сервере и клиенте, доступ получит «не тот» пользователь.
Решения: единая схема UID (LDAP/SSSD), `all_squash` с фиксированными anonuid/anongid,
NFSv4 с idmapd/Kerberos.

</details>

**A9.** Что такое `root_squash` и почему `no_root_squash` опасен?

<details><summary>Ответ</summary>

`root_squash` (по умолчанию) отображает root клиента в `nobody`, чтобы администратор
чужой машины не получал root-права на данные сервера. `no_root_squash` отключает защиту:
любой, кто получил root на клиенте, становится root на экспортируемых данных — прямой путь
к компрометации.

</details>

**A10.** Чем `hard`-монтирование NFS отличается от `soft`? Какую проблему создаёт `hard`
при падении сервера?

<details><summary>Ответ</summary>

`hard` — клиент бесконечно повторяет запросы до восстановления сервера; процессы
уходят в непрерываемый сон `D`, их нельзя убить даже `kill -9`, растёт load average, `umount`
не работает. `soft` — после `timeo`/`retrans` возвращается ошибка ввода-вывода: процессы живут,
но при записи возможна потеря данных. Часто используют `hard` + `intr`(устар.)/`nointr`,
а для некритичных данных — `soft` с разумным таймаутом.

</details>

**A11.** Почему в fstab для сетевых ФС обязательны `_netdev` и `nofail`?

<details><summary>Ответ</summary>

`_netdev` говорит systemd, что ФС сетевая, и монтировать её нужно **после** поднятия
сети (иначе монтирование провалится на раннем этапе загрузки). `nofail` не даёт системе уйти
в emergency, если сервер недоступен. Полезно добавить `x-systemd.mount-timeout=`.

</details>

**A12.** Почему `python3 -m http.server` нельзя использовать в проде? Для чего он тогда годится?

<details><summary>Ответ</summary>

Нет аутентификации, нет TLS, нет контроля доступа и логирования, однопоточный,
раздаёт всё дерево от текущего каталога. Годится для локальной сети и коротких задач:
перекинуть бинарник, отдать артефакт коллеге, отладка. Для прода — nginx, артефакт-репозиторий, S3.

</details>

**A13.** Почему FTP считается устаревшим и небезопасным?

<details><summary>Ответ</summary>

FTP передаёт учётные данные и содержимое **открытым текстом**, использует отдельные
каналы управления и данных (проблемы с NAT/firewall), не обеспечивает целостности.
Замены: SFTP/SCP (поверх SSH), FTPS, HTTPS, объектное хранилище.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  rsync -avzP /src/ user@host:/dst/
B2.  rsync -avn --delete /src/ /dst/
B3.  rsync -av --exclude='.git' --exclude='node_modules' ./ host:/opt/app/
B4.  rsync -av --bwlimit=5000 /data/ backup@nas:/backups/
B5.  rsync -a --link-dest=/backup/latest /data/ /backup/2026-09-13/
B6.  rsync -avz -e 'ssh -p 2222 -i ~/.ssh/id_ed25519' ./dist/ deploy@host:/var/www/
B7.  scp -P 2222 -r dir/ user@host:/opt/
B8.  showmount -e 192.168.56.10
B9.  sudo exportfs -ra && sudo exportfs -v
B10. mount -t nfs -o soft,timeo=30 server:/srv/data /mnt/data
B11. python3 -m http.server 8000 --bind 127.0.0.1 --directory /opt/files
B12. tar czf - /opt/app | ssh host 'tar xzf - -C /backup'
B13. smbclient -L localhost -U vagrant
B14. rsync -av --checksum /src/ /dst/
```

- **B1.** Синхронизация со сжатием, прогрессом и докачкой на удалённый хост.
- **B2.** Пробный прогон с показом, что было бы удалено в приёмнике; ничего не меняет.
- **B3.** Деплой каталога с исключением `.git` и `node_modules`.
- **B4.** Копирование с ограничением скорости 5 МБ/с, чтобы не забить канал.
- **B5.** Инкрементальный бэкап: неизменённые файлы становятся жёсткими ссылками на предыдущий.
- **B6.** Синхронизация через SSH на нестандартном порту с конкретным ключом.
- **B7.** Рекурсивное копирование каталога по SSH на порт 2222 (заглавная `-P`!).
- **B8.** Показывает, какие каталоги экспортирует NFS-сервер.
- **B9.** Перечитывает `/etc/exports` и показывает текущие экспорты с опциями.
- **B10.** Монтирует NFS в «мягком» режиме с таймаутом 3 секунды (timeo в децисекундах).
- **B11.** Раздаёт `/opt/files` по HTTP только на локальном интерфейсе.
- **B12.** Передаёт каталог потоком через SSH без промежуточного файла.
- **B13.** Список общих ресурсов Samba на локальном сервере.
- **B14.** Сравнение файлов по контрольным суммам, а не по размеру и времени (медленнее, надёжнее).

**B15.** Что означает опция `-P` в rsync и почему она важна при передаче больших файлов
по нестабильному каналу?

<details><summary>Ответ</summary>

`-P` = `--partial --progress`: показывает прогресс и **сохраняет частично переданные
файлы**, поэтому после обрыва передача продолжится с места разрыва, а не начнётся заново.

</details>

---

### Блок C. Практика

**C1. Слеш и dry-run (обязательное упражнение).**
Создай `~/lab16/src` с тремя файлами и подкаталогом. Выполни четыре команды **с `-n`**
и запиши, что произойдёт в каждом случае:
```bash
rsync -avn src   dst/
rsync -avn src/  dst/
rsync -avn src   dst
rsync -avn src/* dst/
```
Затем выполни ту, которая копирует **содержимое**, и проверь результат.

<details><summary>Ответ</summary>

```bash
mkdir -p ~/lab16/{src,dst} && cd ~/lab16
echo a > src/a.txt; echo b > src/b.txt; mkdir -p src/sub; echo c > src/sub/c.txt
rsync -avn src   dst/     # создаст dst/src/...
rsync -avn src/  dst/     # содержимое прямо в dst/
rsync -avn src   dst      # dst не существует как каталог-приёмник → создастся dst/ как копия src
rsync -avn src/* dst/     # раскрытие глоба шеллом: скрытые файлы НЕ попадут
rsync -av src/ dst/ && find dst -type f
```

</details>

**C2. Исключения.** Синхронизируй каталог проекта, исключив `.git`, `node_modules`, `*.log`
и `.env`. Сделай это двумя способами: через несколько `--exclude` и через `--exclude-from=файл`.

<details><summary>Ответ</summary>

```bash
rsync -av --exclude='.git' --exclude='node_modules' --exclude='*.log' --exclude='.env' src/ dst/
printf '.git\nnode_modules\n*.log\n.env\n' > ~/lab16/exclude.txt
rsync -av --exclude-from=$HOME/lab16/exclude.txt src/ dst/
```

</details>

**C3. Дельта-передача.** Создай файл 100 МБ, синхронизируй, замерь время.
Измени в нём 1 КБ, синхронизируй повторно и замерь снова. Объясни разницу,
используя вывод `--stats` (обрати внимание на `Total transferred file size` vs `Literal data`).

<details><summary>Ответ</summary>

```bash
dd if=/dev/urandom of=src/big.bin bs=1M count=100 status=none
time rsync -a --stats src/ dst/ | grep -E 'Total transferred|Literal|Matched'
printf 'x%.0s' {1..1024} >> src/big.bin
time rsync -a --stats src/ dst/ | grep -E 'Total transferred|Literal|Matched'
```
Во второй раз `Literal data` (реально переданные байты) будет в тысячи раз меньше
`Total transferred file size` — это и есть delta-transfer.

</details>

**C4. Инкрементальный бэкап.** Реализуй схему из 3 бэкапов подряд:
```text:no-line-numbers
/backup/2026-09-13/
/backup/2026-09-14/
/backup/2026-09-15/
/backup/latest -> 2026-09-15
```
- каждый бэкап должен выглядеть как полный;
- неизменённые файлы не должны занимать место повторно;
- докажи это через `du -sh` и `ls -li` (одинаковые inode).

<details><summary>Ответ</summary>

```bash
mkdir -p ~/lab16/backup
rsync -a --delete src/ ~/lab16/backup/2026-09-13/
ln -sfn ~/lab16/backup/2026-09-13 ~/lab16/backup/latest
echo new1 > src/n1.txt
rsync -a --delete --link-dest=$HOME/lab16/backup/latest src/ ~/lab16/backup/2026-09-14/
ln -sfn ~/lab16/backup/2026-09-14 ~/lab16/backup/latest
echo new2 > src/n2.txt
rsync -a --delete --link-dest=$HOME/lab16/backup/latest src/ ~/lab16/backup/2026-09-15/
ln -sfn ~/lab16/backup/2026-09-15 ~/lab16/backup/latest
du -sh ~/lab16/backup/2026-*
ls -li ~/lab16/backup/2026-*/a.txt        # один и тот же inode
```

</details>

**C5. Скрипт бэкапа.** Напиши `/usr/local/bin/backup.sh`, который:
- принимает источник и каталог бэкапов;
- делает инкрементальный бэкап с `--link-dest`;
- обновляет симлинк `latest` **атомарно**;
- удаляет бэкапы старше 7 дней;
- логирует результат через `logger` и возвращает корректный exit code;
- защищён `flock` от параллельного запуска.

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
set -euo pipefail
SRC="${1:?usage: backup.sh <src> <backup-root>}"
ROOT="${2:?usage: backup.sh <src> <backup-root>}"
TAG=backup
DATE=$(date +%F_%H%M)
DST="$ROOT/$DATE"

[[ -d "$SRC" ]] || { logger -t "$TAG" -p local0.err "source $SRC not found"; exit 1; }
mkdir -p "$ROOT"

LINK=()
[[ -e "$ROOT/latest" ]] && LINK=(--link-dest="$(readlink -f "$ROOT/latest")")

logger -t "$TAG" -p local0.info "backup started: $SRC -> $DST"
if rsync -a --delete "${LINK[@]}" "$SRC/" "$DST/"; then
  ln -sfn "$DST" "$ROOT/.latest.tmp" && mv -T "$ROOT/.latest.tmp" "$ROOT/latest"
  find "$ROOT" -maxdepth 1 -type d -name '20*' -mtime +7 -exec rm -rf {} +
  logger -t "$TAG" -p local0.info "backup finished OK: $DST"
else
  logger -t "$TAG" -p local0.err "backup FAILED: $SRC"
  exit 2
fi
```
Запуск из cron: `0 2 * * * /usr/bin/flock -n /tmp/backup.lock /usr/local/bin/backup.sh /data /backup >> /var/log/backup.log 2>&1`

</details>

**C6. Деплой через rsync.** Сымитируй деплой:
1. Каталог `~/app_src` с «приложением».
2. Выкатка в `/opt/app/releases/<timestamp>/` через rsync с исключениями.
3. Атомарное переключение `/opt/app/current`.
4. Хранить только 3 последних релиза.

<details><summary>Ответ</summary>

```bash
TS=$(date +%Y%m%d-%H%M%S)
sudo mkdir -p /opt/app/releases/$TS
sudo rsync -a --exclude='.git' --exclude='*.log' ~/app_src/ /opt/app/releases/$TS/
sudo ln -sfn /opt/app/releases/$TS /opt/app/current.tmp
sudo mv -T /opt/app/current.tmp /opt/app/current
ls -1dt /opt/app/releases/* | tail -n +4 | sudo xargs -r rm -rf
readlink -f /opt/app/current
```

</details>

**C7. HTTP-раздача.** Подними `http.server` на порту 8000 **только на localhost**,
скачай через `curl` файл, покажи в логе сервера запрос. Затем объясни, как проверить,
что сервер не доступен снаружи (командой).

<details><summary>Ответ</summary>

```bash
cd ~/lab16/src && python3 -m http.server 8000 --bind 127.0.0.1 &
curl -sO http://127.0.0.1:8000/a.txt && echo OK
ss -tulpn | grep 8000                      # видно 127.0.0.1:8000, а не 0.0.0.0:8000
curl -s --max-time 3 http://$(hostname -I | awk '{print $1}'):8000/ || echo "снаружи недоступен — верно"
kill %1
```

</details>

**C8. NFS на localhost.** Настрой NFS-экспорт и примонтируй его локально:
- каталог `/srv/nfs/data`, доступ на чтение-запись;
- проверь через `showmount` и `df -hT`;
- создай файл через точку монтирования и убедись, что он появился в исходном каталоге;
- посмотри, под каким владельцем создался файл, и объясни почему;
- добавь монтирование в fstab **правильно** (какие опции обязательны?), проверь `mount -a`;
- убери всё за собой.

<details><summary>Ответ</summary>

```bash
sudo apt install -y nfs-kernel-server
sudo mkdir -p /srv/nfs/data && sudo chown nobody:nogroup /srv/nfs/data
echo "/srv/nfs/data 127.0.0.1/32(rw,sync,no_subtree_check)" | sudo tee -a /etc/exports
sudo exportfs -ra && sudo exportfs -v && showmount -e 127.0.0.1
sudo mkdir -p /mnt/nfs && sudo mount -t nfs 127.0.0.1:/srv/nfs/data /mnt/nfs
df -hT /mnt/nfs
sudo touch /mnt/nfs/test.txt && ls -l /srv/nfs/data/
```
Файл, созданный под root через NFS, принадлежит `nobody:nogroup` из-за `root_squash`.
Строка fstab: `127.0.0.1:/srv/nfs/data /mnt/nfs nfs defaults,_netdev,nofail,x-systemd.mount-timeout=10 0 0`,
проверка — `sudo mount -a`. Уборка: `sudo umount /mnt/nfs`, удалить строки из fstab и exports,
`sudo exportfs -ra`.

</details>

**C9. Проверка сетевого доступа.** Без `nc` и `telnet` проверь доступность:
- порта 2049 (NFS) на localhost;
- порта 22;
- несуществующего порта 9999.
Затем покажи, кто слушает эти порты.

<details><summary>Ответ</summary>

```bash
for p in 2049 22 9999; do
  timeout 2 bash -c "</dev/tcp/127.0.0.1/$p" 2>/dev/null && echo "$p OPEN" || echo "$p CLOSED"
done
ss -tulpn | grep -E ':(22|2049|9999)\b'
```

</details>

**C10. Сравнение методов передачи.** Передай каталог 200 МБ тремя способами
(`scp -r`, `rsync -az`, `tar | ssh`) на `localhost` и сравни время. Сделай вывод,
когда какой способ выгоднее.

<details><summary>Ответ</summary>

```bash
mkdir -p ~/lab16/big && dd if=/dev/urandom of=~/lab16/big/data.bin bs=1M count=200 status=none
time scp -r ~/lab16/big vagrant@localhost:~/t1
time rsync -az ~/lab16/big/ vagrant@localhost:~/t2/
time tar czf - -C ~/lab16 big | ssh vagrant@localhost 'mkdir -p ~/t3 && tar xzf - -C ~/t3'
```
Вывод: на **первой** передаче все три сопоставимы (`tar|ssh` часто быстрее на множестве мелких
файлов, так как один поток вместо множества операций); на **повторной** синхронизации rsync
выигрывает на порядки. Сжатие (`-z`, `czf`) бесполезно для уже случайных/сжатых данных.

</details>

---

### Блок D. Инциденты

**D1.** Скрипт бэкапа выполнил `rsync -av --delete /data /backup/` (без слеша), и теперь
в `/backup` лежит `/backup/data/...`, а прежнее содержимое `/backup` удалено.
Что произошло и как избежать?

<details><summary>Ответ</summary>

Отсутствие слеша превратило команду в «скопировать сам каталог `data` внутрь `/backup`»,
а `--delete` удалил всё, что в `/backup` не соответствовало источнику — то есть прежние бэкапы.
Избежать: `--dry-run` в тестах, слеш в конце источника, выделенный каталог-приёмник, никогда
не указывать корень бэкапов как приёмник с `--delete`, плюс версионирование/снапшоты на приёмнике.

</details>

**D2.** После обновления сервера все процессы, работающие с `/mnt/nfs`, зависли в состоянии `D`,
load average 80, CPU простаивает, `umount` не работает. Диагноз и варианты действий.

<details><summary>Ответ</summary>

NFS-сервер недоступен, а монтирование выполнено в режиме `hard`: процессы ждут
бесконечно в состоянии `D`, сигналы не доставляются. Действия: проверить доступность сервера
(`ping`, `showmount -e`, порт 2049), восстановить сервер — процессы «оживут» сами.
Если сервер не вернуть: `umount -f -l /mnt/nfs` (force + lazy), в крайнем случае перезагрузка.
Профилактика: `soft` + `timeo` для некритичных данных, `_netdev,nofail`, мониторинг NFS,
отказ от NFS в пользу объектного хранилища там, где возможно.

</details>

**D3.** Файлы, созданные приложением на NFS-шаре, на сервере принадлежат `nobody:nogroup`,
и другой сервис не может их прочитать. Причины (две разные) и решения.

<details><summary>Ответ</summary>

(1) Сработал `root_squash`: файлы создаются от root на клиенте и отображаются в
`nobody:nogroup`. (2) Несогласованные UID/GID между клиентом и сервером. Решения: создавать
файлы от обычного пользователя с согласованным UID; настроить единый источник учётных записей
(LDAP/SSSD); использовать `all_squash` с `anonuid`/`anongid`, указывающими на нужного
пользователя; в NFSv4 — idmapd/Kerberos.

</details>

**D4.** rsync по SSH прерывается на больших файлах с `connection reset`. Что добавить в команду
и что проверить в сети?

<details><summary>Ответ</summary>

Добавить `-P` (докачка и прогресс), `--timeout=60`, `--partial-dir=.rsync-partial`,
использовать `-e 'ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=6'`. Проверить сеть:
MTU/фрагментацию, состояние NAT/conntrack (таймауты сессий), потери (`mtr`), ограничения
firewall, стабильность канала. Также помогает `--bwlimit`, чтобы не вызывать перегрузку.

</details>

**D5.** Коллега оставил `python3 -m http.server 8000` запущенным в каталоге `/`
на сервере с публичным IP. Оцени риски и опиши немедленные действия.

<details><summary>Ответ</summary>

Публично раздаётся вся файловая система от `/`: ключи SSH, `/etc/passwd`, конфиги с
паролями, исходники, бэкапы — критическая утечка. Немедленно: убить процесс
(`pkill -f http.server`), закрыть порт в firewall/Security Group, проверить логи веб-доступа
и сетевые логи на предмет скачиваний, считать скомпрометированными все ключи и секреты
из доступной области (ротация!), провести разбор и запретить такой способ раздачи регламентом.

</details>

**D6.** Бэкап по rsync «кладёт» прод каждую ночь: сервис отвечает по 3 секунды.
Как исправить, не меняя расписание?

<details><summary>Ответ</summary>

Добавить `--bwlimit` (ограничить полосу) и запускать с пониженным приоритетом:
`nice -n 19 ionice -c3 rsync --bwlimit=20000 ...`. Дополнительно: делать бэкап с реплики/снапшота,
а не с боевой ФС; использовать `--link-dest` (меньше данных), исключить ненужные каталоги,
разбить на части. В systemd-юните — `IOSchedulingClass=idle`, `CPUWeight`, `IOWeight`.

</details>

**D7.** После добавления NFS в `/etc/fstab` сервер не загрузился и ушёл в emergency.
Что забыли и как правильно?

<details><summary>Ответ</summary>

Забыли `_netdev` и `nofail`: система пыталась смонтировать сетевую ФС до поднятия сети
и, не сумев, ушла в emergency. Правильная строка:
`server:/export /mnt/nfs nfs defaults,_netdev,nofail,x-systemd.mount-timeout=10,soft,timeo=30 0 0`,
и обязательная проверка `mount -a` до перезагрузки.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Чем rsync лучше scp?

<details><summary>Ответ</summary>

Передаёт только изменения, сохраняет атрибуты, умеет исключения, докачку, dry-run,
ограничение скорости и удаление лишнего — незаменим для синхронизации, бэкапов и деплоя.

</details>

**2.** Что означает слеш в конце пути в rsync?

<details><summary>Ответ</summary>

Слеш в конце источника означает «содержимое каталога»; без слеша копируется сам каталог
внутрь приёмника.

</details>

**3.** Как сделать инкрементальный бэкап, который выглядит как полный?

<details><summary>Ответ</summary>

`rsync -a --delete --link-dest=/backup/latest /data/ /backup/$(date +%F)/` — неизменённые
файлы становятся жёсткими ссылками, каждый каталог выглядит полным бэкапом.

</details>

**4.** Что такое NFS и какие у него подводные камни?

<details><summary>Ответ</summary>

Сетевая ФС UNIX: экспорт каталога на сервере и монтирование на клиентах. Подводные камни:
права по UID/GID, `hard`-монтирование и зависшие процессы в `D`, единая точка отказа,
необходимость `_netdev`/`nofail`, безопасность (`root_squash`, доступ по IP).

</details>

**5.** Как быстро передать файл между двумя серверами, если нет rsync?

<details><summary>Ответ</summary>

`scp`, `sftp`, `tar czf - dir | ssh host 'tar xzf - -C /dst'`, `python3 -m http.server` + `curl`,
`nc` — или через промежуточное объектное хранилище.

</details>

**6.** Как ограничить скорость передачи, чтобы не забить канал?

<details><summary>Ответ</summary>

`rsync --bwlimit=<КБ/с>`, `scp -l <Кбит/с>`, плюс `nice`/`ionice` и `tc` на уровне интерфейса.

</details>

**7.** Как исключить каталоги при синхронизации?

<details><summary>Ответ</summary>

`--exclude='pattern'` (можно несколько) или `--exclude-from=файл`; для включений — `--include`
перед `--exclude`.

</details>

**8.** Чем root_squash отличается от no_root_squash?

<details><summary>Ответ</summary>

`root_squash` отображает root клиента в непривилегированного `nobody` (безопасно, по умолчанию);
`no_root_squash` оставляет ему root-права на экспортированных данных — серьёзный риск.

</details>

---

### 🎯 Чек-лист

- [ ] Помню правило слеша в rsync и всегда делаю `--dry-run`
- [ ] Умею исключать каталоги и ограничивать скорость
- [ ] Сделал инкрементальный бэкап с `--link-dest` и доказал экономию места
- [ ] Написал скрипт бэкапа с flock, logger и ротацией
- [ ] Настроил NFS-экспорт и монтирование с правильными опциями fstab
- [ ] Понимаю риски `hard`-монтирования и `no_root_squash`
- [ ] Знаю, когда `python3 -m http.server` уместен, а когда это инцидент
