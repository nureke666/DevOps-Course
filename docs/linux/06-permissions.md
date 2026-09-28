---
title: "06. Permissions"
description: "Права доступа: chmod, chown, umask, setuid/setgid/sticky bit и диагностика Permission denied"
---

# 06. Permissions — права доступа

> Источник: `06_permissions.txt` (Grasshopper, 8 уроков)
> **После темы ты умеешь:** читать и выставлять права, понимать umask, setuid/setgid/sticky bit
> и за минуту чинить `Permission denied` — самую частую ошибку в жизни девопса.

---

## 🗺️ Схема: как ядро решает, пускать или нет

```text:no-line-numbers
       Процесс хочет открыть файл /var/www/index.html
                        │
                        ▼
     ┌──────────────────────────────────────────┐
     │ 1. UID процесса == UID владельца файла?  │──ДА──▶ применить права USER (rwx)
     └──────────────────┬───────────────────────┘              │
                        │ НЕТ                                  │
                        ▼                                      │
     ┌──────────────────────────────────────────┐              │
     │ 2. GID (или доп. группа) == группа файла?│──ДА──▶ применить права GROUP (r-x)
     └──────────────────┬───────────────────────┘              │
                        │ НЕТ                                  │
                        ▼                                      ▼
              применить права OTHER (r--)          ┌──────────────────────┐
                        │                          │ хватает? → доступ    │
                        └─────────────────────────▶│ нет → EACCES         │
                                                   └──────────────────────┘
```

🔑 **Проверка идёт по ПЕРВОМУ совпадению и дальше не идёт.**
Если ты владелец файла с правами `---rwxrwx`, ты **не сможешь** его прочитать, хотя группа может.
Это контринтуитивно и это любимый вопрос на собеседованиях.

---

## 1. File Permissions — как читать `ls -l`

```text:no-line-numbers
-rwxr-xr--  1 nurik developers 2048 Sep 13 10:30 deploy.sh
│└┬┘└┬┘└┬┘     │       │
│ │  │  │      │       └─ группа-владелец
│ │  │  │      └───────── пользователь-владелец
│ │  │  └─ other (все остальные):  r--  = 4
│ │  └──── group (члены developers): r-x = 5
│ └─────── user (nurik):            rwx = 7
└───────── тип файла
```

**Типы файлов** (первый символ):

| Символ | Тип |
|--------|-----|
| `-` | обычный файл |
| `d` | каталог |
| `l` | символическая ссылка |
| `c` | символьное устройство (`/dev/tty`) |
| `b` | блочное устройство (`/dev/sda`) |
| `s` | сокет (`/var/run/docker.sock`) |
| `p` | именованный канал (FIFO) |

**Три права и их числа:**

| Право | Символ | Число | Для ФАЙЛА | Для КАТАЛОГА |
|-------|--------|-------|-----------|--------------|
| read | `r` | 4 | читать содержимое | **посмотреть список имён** (`ls`) |
| write | `w` | 2 | изменять содержимое | **создавать/удалять файлы внутри** |
| execute | `x` | 1 | запускать как программу | **входить внутрь** (`cd`), обращаться к файлам по пути |

🔴 **Права на каталог — главный источник путаницы:**
- `r` без `x` → `ls` покажет имена, но любая операция с файлами вернёт ошибку.
- `x` без `r` → `ls` запрещён, но если знаешь точное имя — файл доступен (так делают «скрытые» каталоги).
- **Удаление файла зависит от прав на КАТАЛОГ, а не на файл!** Файл с правами `444` спокойно
  удаляется, если у тебя есть `w` на каталог. Это ловит абсолютно всех новичков.

### Восьмеричная запись

```text:no-line-numbers
r w x     4 2 1
─────     ─────
r w x  =  4+2+1 = 7      rwx
r w -  =  4+2   = 6      rw-
r - x  =  4  +1 = 5      r-x
r - -  =  4     = 4      r--
- - -  =  0     = 0      ---
```

| Режим | Симв. | Типовое применение |
|-------|-------|--------------------|
| `644` | `rw-r--r--` | обычные файлы, конфиги, HTML |
| `755` | `rwxr-xr-x` | скрипты, бинарники, **каталоги** |
| `600` | `rw-------` | приватное: `~/.ssh/id_rsa`, файлы с секретами |
| `700` | `rwx------` | приватный каталог: `~/.ssh` |
| `640` | `rw-r-----` | конфиг, доступный группе (`/etc/shadow`) |
| `775` | `rwxrwxr-x` | каталог для совместной работы группы |
| `777` | `rwxrwxrwx` | 🔴 **никогда в проде** |

---

## 2. Modifying Permissions — chmod

### Числовой режим (быстро, задаёт права целиком)

```bash
chmod 644 file.txt
chmod 755 script.sh
chmod 600 ~/.ssh/id_rsa
chmod -R 755 /var/www          # рекурсивно
```

### Символьный режим (точечно, меняет только указанное)

```text:no-line-numbers
chmod [кто][операция][права] файл
        u = user          + добавить        r
        g = group         - убрать          w
        o = other         = установить      x
        a = all                             X (x только для каталогов/уже исполняемых)
```

```bash
chmod +x script.sh          # добавить исполнение всем (учитывает umask)
chmod u+x script.sh         # только владельцу
chmod g-w file.txt          # забрать запись у группы
chmod o= file.txt           # снять ВСЕ права у остальных
chmod a+r file.txt          # чтение всем
chmod u=rw,g=r,o= file.txt  # комбинированно
chmod -R u+rwX,go-w dir/    # X = x только каталогам — правильный рекурсивный приём
```

💡 **Как правильно ставить права рекурсивно** (частая ошибка — сделать все файлы исполняемыми):

```bash
# ❌ плохо: все файлы станут исполняемыми
chmod -R 755 /var/www

# ✅ хорошо: каталогам 755, файлам 644
find /var/www -type d -exec chmod 755 {} +
find /var/www -type f -exec chmod 644 {} +
# или короче:
chmod -R u=rwX,go=rX /var/www
```

---

## 3. Ownership — chown / chgrp

```bash
sudo chown nurik file.txt              # сменить владельца
sudo chown nurik:developers file.txt   # владельца и группу
sudo chown :developers file.txt        # только группу
sudo chgrp developers file.txt         # то же
sudo chown -R www-data:www-data /var/www   # рекурсивно
sudo chown --reference=good.txt bad.txt    # скопировать владельца с другого файла
```

⚠️ Менять владельца может **только root**. Обычный пользователь не может «подарить» свой файл
другому (иначе можно было бы обойти дисковые квоты).

---

## 4. Umask — маска прав по умолчанию

При создании файла система берёт «базовые» права и **вычитает** маску:

```text:no-line-numbers
            ФАЙЛЫ            КАТАЛОГИ
База        666 (rw-rw-rw-)  777 (rwxrwxrwx)   ← у новых файлов НИКОГДА нет +x
umask   -   022              022
─────────────────────────────────────
Итог        644 (rw-r--r--)  755 (rwxr-xr-x)
```

```bash
umask              # 0022
umask -S           # u=rwx,g=rx,o=rx
umask 077          # приватный режим: файлы 600, каталоги 700
umask 002          # для групповой работы: файлы 664, каталоги 775
```

| umask | Файлы | Каталоги | Когда |
|-------|-------|----------|-------|
| `022` | 644 | 755 | по умолчанию в системе |
| `002` | 664 | 775 | совместная работа группы |
| `077` | 600 | 700 | максимальная приватность (серверы с секретами) |

Постоянно — в `~/.bashrc`, `~/.profile` или `/etc/profile`. Для systemd-сервиса — директива `UMask=`.

⚠️ Вычитание не арифметическое, а побитовое (снятие битов): `umask 023` для файла даёт `644`,
а не «643» — бит `x` в базе 666 и так отсутствует.

---

## 5-6. Setuid и Setgid — специальные биты

```text:no-line-numbers
  ┌───┬───┬───┬───┐
  │ 4 │ 2 │ 1 │   │   спецбиты: 4 = setuid, 2 = setgid, 1 = sticky
  └───┴───┴───┴───┘
    chmod 4755 file   → setuid
    chmod 2755 dir    → setgid
    chmod 1777 dir    → sticky
```

### SUID (4) — запуск от имени владельца файла

```bash
ls -l /usr/bin/passwd
# -rwsr-xr-x 1 root root ... /usr/bin/passwd
#    ↑ 's' вместо 'x' у владельца
```
Обычный пользователь запускает `passwd`, и процесс работает **с правами root** — иначе он не смог бы
записать в `/etc/shadow`. Это единственный способ контролируемо повысить привилегии.

```bash
chmod u+s file      # или chmod 4755 file
chmod u-s file      # снять
find / -perm -4000 -type f 2>/dev/null    # аудит: все SUID-файлы в системе
```

🔴 **SUID — главный вектор локального повышения привилегий.**
- SUID на shell-скрипт в Linux **игнорируется** (ядро не даёт — и правильно).
- SUID на `/bin/bash`, `cp`, `find`, `vim` = мгновенный root для любого пользователя.
- Свой софт с SUID — почти всегда ошибка проектирования. Альтернатива: `sudo` с точечным правилом
  или Linux capabilities (`setcap cap_net_bind_service=+ep /usr/bin/myapp`).

### SGID (2)

**На файле** — запуск с правами группы-владельца (реже, чем SUID).

**На каталоге** — 🔑 **новые файлы наследуют ГРУППУ каталога**, а не первичную группу создателя.
Это и есть правильный способ организовать общую папку команды:

```bash
sudo mkdir /srv/shared
sudo chgrp developers /srv/shared
sudo chmod 2775 /srv/shared        # 2 = setgid
ls -ld /srv/shared
# drwxrwsr-x 2 root developers ...
#       ↑ 's' в позиции group

# Теперь любой файл, созданный внутри, получит группу developers автоматически
```
Без setgid файл, созданный `nurik`, получит группу `nurik`, и коллеги его не прочитают —
классическая причина «у нас общая папка, но ничего не работает».

### Sticky bit (1) — защита от удаления

```bash
ls -ld /tmp
# drwxrwxrwt 10 root root ... /tmp
#          ↑ 't' в позиции other
```
В каталоге со sticky bit удалить/переименовать файл может **только его владелец** (или root),
даже если у всех есть `w` на каталог. Именно так `/tmp` остаётся общим и при этом безопасным.

```bash
chmod +t /shared/uploads     # или chmod 1777
```

### Как читать спецбиты в `ls -l`

| Вывод | Значение |
|-------|----------|
| `rws` (user) | setuid, `x` есть |
| `rwS` (user) | setuid, **`x` НЕТ** — обычно ошибка |
| `rws` (group) | setgid, `x` есть |
| `rwt` (other) | sticky, `x` есть |
| `rwT` (other) | sticky без `x` |

Заглавная буква = бит установлен, а исполнения нет → почти всегда опечатка в chmod.

---

## 7. Process Permissions

У процесса есть несколько «личностей»:

| Идентификатор | Что это |
|---------------|---------|
| **RUID** (real) | кто запустил процесс |
| **EUID** (effective) | **чьи права реально проверяются** ядром |
| **SUID** (saved) | сохранённый, чтобы можно было временно сбросить и вернуть права |

Когда ты запускаешь `passwd`: RUID = 1000 (ты), EUID = 0 (root, из-за setuid-бита).

```bash
ps -eo pid,user,ruser,euser,comm | head
id -u    # реальный UID
id -ru   # real
id -eu   # effective
```

Процесс наследует UID/GID родителя. Поэтому демон, запущенный systemd от root с `User=appuser`,
сбрасывает привилегии до `appuser` — и дальше живёт с его правами.

**Capabilities** — современная альтернатива «всё или ничего»: root-права разбиты на ~40 кусочков.

```bash
getcap /usr/bin/ping
# /usr/bin/ping cap_net_raw=ep       ← вместо SUID root!
sudo setcap 'cap_net_bind_service=+ep' /opt/app/server   # разрешить слушать порт 80 без root
getcap -r /usr/bin 2>/dev/null
```
Это ровно то, что настраивают в `securityContext.capabilities` в Kubernetes.

---

## 8. Расширенные возможности (пригодится, но не в курсе)

**ACL** — права для конкретных пользователей сверх стандартной тройки:
```bash
getfacl file.txt
setfacl -m u:nurik:rw file.txt      # дать nurik rw
setfacl -m g:devs:rx dir/
setfacl -x u:nurik file.txt         # убрать
setfacl -b file.txt                 # снять все ACL
```
Наличие ACL видно по `+` в конце прав: `-rw-rw-r--+`.

**Атрибуты файловой системы:**
```bash
lsattr file.txt
sudo chattr +i /etc/resolv.conf     # immutable: НЕЛЬЗЯ изменить даже root
sudo chattr -i /etc/resolv.conf
sudo chattr +a /var/log/audit.log   # append-only
```
`chattr +i` — частая причина загадочного «root не может удалить файл».

---

## 🔧 Алгоритм «Permission denied» за 60 секунд

```text:no-line-numbers
1. Кто я?                 id
2. Чего касаюсь?          ls -l файл ; ls -ld каталог
3. Проверь ВЕСЬ путь:     namei -l /var/www/app/config.yml
                          (нужен x на КАЖДОМ каталоге пути!)
4. Реальная проверка:     sudo -u www-data test -r /path && echo OK || echo NO
5. Не ACL ли:             getfacl файл          (символ + в ls -l)
6. Не immutable ли:       lsattr файл
7. Не SELinux/AppArmor:   getenforce / aa-status ; dmesg | tail
8. Не переполнен ли диск: df -h ; df -i
```

⚠️ Пункт 3 — самая частая невидимая причина: у файла права `644`, но на родительском каталоге нет `x`.

---

## 💼 Как это в DevOps

- `chmod 600` на SSH-ключи — иначе `ssh` откажется их использовать (`UNPROTECTED PRIVATE KEY FILE`).
- Права в Docker: файлы в образе, volume, `USER` в Dockerfile, несовпадение UID хоста и контейнера.
- Kubernetes `securityContext`: `runAsUser`, `fsGroup`, `readOnlyRootFilesystem`, `capabilities`.
- CI/CD: `chmod +x deploy.sh` после `git clone` (git хранит только бит исполнения).
- Аудит безопасности: поиск SUID-файлов, `777`-каталогов, world-writable конфигов.
- `chmod 777` в качестве «решения» проблемы — красный флаг на код-ревью и на собеседовании.

---

## 🧪 Мини-лаба

```bash
vagrant ssh
mkdir -p ~/lab06 && cd ~/lab06

# 1. Базовые эксперименты
touch file.txt && ls -l file.txt        # 644 (umask 022)
chmod 600 file.txt && ls -l file.txt
chmod u+x,g+w file.txt && ls -l file.txt
chmod 755 file.txt; stat -c '%a %A %U %G %n' file.txt

# 2. umask
umask
umask 077; touch private.txt; mkdir privdir; ls -l private.txt; ls -ld privdir
umask 022

# 3. ПРАВА НА КАТАЛОГ — проведи эксперимент до конца
mkdir testdir && echo "secret" > testdir/data.txt
chmod 744 testdir                       # есть r, НЕТ x
sudo -u nobody ls testdir               # имена видны
sudo -u nobody cat testdir/data.txt     # Permission denied!
chmod 711 testdir                       # НЕТ r, есть x
sudo -u nobody ls testdir               # Permission denied
sudo -u nobody cat testdir/data.txt     # работает! (знаем точное имя)
chmod 755 testdir

# 4. Удаление зависит от каталога, а не от файла
chmod 444 testdir/data.txt
rm -f testdir/data.txt                  # удалился, хотя файл read-only!
echo "secret" > testdir/data.txt

# 5. SUID в системе
ls -l /usr/bin/passwd /usr/bin/sudo
find /usr/bin -perm -4000 2>/dev/null

# 6. SGID — общая папка
sudo groupadd -f devs
sudo usermod -aG devs vagrant
sudo mkdir -p /srv/shared
sudo chgrp devs /srv/shared
sudo chmod 2775 /srv/shared
ls -ld /srv/shared
newgrp devs <<'EOS'
touch /srv/shared/from_vagrant.txt
ls -l /srv/shared
EOS

# 7. Sticky bit
ls -ld /tmp
mkdir -p ~/lab06/public && chmod 1777 ~/lab06/public
ls -ld ~/lab06/public

# 8. Capabilities вместо SUID
getcap /usr/bin/ping
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `ls -l` / `ls -ld` | Права файла / **каталога** |
| `stat -c '%a %A %U %G' f` | Права в числах и символах + владелец |
| `chmod 644 f` / `chmod u+x f` | Числовой / символьный режим |
| `chmod -R u=rwX,go=rX dir` | Правильный рекурсивный chmod |
| `chown user:group f` | Владелец и группа |
| `umask [077]` | Маска по умолчанию |
| `chmod 4755 f` / `u+s` | SUID |
| `chmod 2775 dir` / `g+s` | SGID (наследование группы) |
| `chmod 1777 dir` / `+t` | Sticky bit |
| `find / -perm -4000` | Аудит SUID |
| `namei -l /path/to/file` | Права на **весь путь** |
| `getfacl` / `setfacl -m` | ACL |
| `lsattr` / `chattr +i` | Атрибуты ФС (immutable) |
| `getcap` / `setcap` | Capabilities |

**Числа наизусть:** 7=rwx, 6=rw-, 5=r-x, 4=r--, 0=---. Каталоги 755, файлы 644, секреты 600.

---

## 🧠 Что запомнить

1. Проверка прав — по **первому совпадению**: user → group → other, дальше не идёт.
2. Для каталога: `r` = видеть имена, `w` = создавать/удалять, **`x` = входить**.
3. **Удаление файла определяется правами на каталог**, а не на файл.
4. Нужен `x` на **каждом** каталоге пути — проверяй через `namei -l`.
5. umask вычитается: 666-022=644 для файлов, 777-022=755 для каталогов; `x` файлам не даётся никогда.
6. SUID (4) — запуск от владельца, SGID (2) на каталоге — наследование группы, sticky (1) — только
   владелец удаляет.
7. `chmod 777` — не решение, а инцидент. Разбирайся, кому реально нужен доступ.
8. `chmod 600 ~/.ssh/id_rsa` — иначе ssh откажется работать.
9. Современная замена SUID — capabilities (`setcap`).

---

## Задачи

> `vagrant snapshot save before_06 && vagrant ssh`

### 🔧 Подготовка

```bash
mkdir -p ~/lab06 && cd ~/lab06
touch app.conf deploy.sh secret.key
mkdir -p public private shared
echo "db_password=hunter2" > secret.key
echo "#!/bin/bash"$'\n'"echo deploying" > deploy.sh
sudo groupadd -f devs
sudo usermod -aG devs vagrant
ls -la
```

---

### Блок A. Теория

**A1.** Разбери строку по частям:
```text:no-line-numbers
-rwxr-x---  1 nurik developers 1024 Sep 13 10:00 deploy.sh
```
Кто и что может делать с этим файлом?

<details><summary>Ответ</summary>

Обычный файл. Владелец `nurik`: чтение, запись, выполнение (`rwx` = 7).
Группа `developers`: чтение и выполнение, без записи (`r-x` = 5). Остальные: ничего (`---` = 0).
Режим `750`.

</details>

**A2.** Переведи в числа: `rw-r--r--`, `rwxr-xr-x`, `rw-------`, `rwxrwx---`.
И обратно: `640`, `750`, `600`, `2775`, `1777`.

<details><summary>Ответ</summary>

`rw-r--r--` = 644, `rwxr-xr-x` = 755, `rw-------` = 600, `rwxrwx---` = 770.
Обратно: `640` = `rw-r-----`, `750` = `rwxr-x---`, `600` = `rw-------`,
`2775` = `rwxrwsr-x` (SGID), `1777` = `rwxrwxrwt` (sticky).

</details>

**A3.** Что означают `r`, `w`, `x` для **каталога**? Объясни каждое отдельно.

<details><summary>Ответ</summary>

`r` — можно получить список имён (`ls`). `w` — можно создавать, удалять и переименовывать
записи внутри (вместе с `x`). `x` — можно «войти» в каталог и обращаться к файлам по полному пути
(traverse). Полезен только вместе: `r` без `x` почти бесполезен.

</details>

**A4.** У файла права `444` (`r--r--r--`), владелец root. Ты — обычный пользователь.
Можешь ли ты его удалить? От чего это зависит?

<details><summary>Ответ</summary>

Да, можешь — если у тебя есть `w` **и** `x` на каталоге, где лежит файл, и на каталоге не
стоит sticky bit. Права самого файла на удаление не влияют — удаление это изменение каталога.

</details>

**A5.** Файл имеет права `---rwxrwx`, владелец — ты, группа — `devs`, ты состоишь в `devs`.
Сможешь ли ты прочитать файл? Почему?

<details><summary>Ответ</summary>

**Нет.** Ты владелец, значит применяется только блок `user` = `---`. Проверка останавливается
на первом совпадении и к группе не переходит. Классический вопрос-ловушка.

</details>

**A6.** Как из umask `022` получаются права `644` для файла и `755` для каталога?
Почему у нового файла никогда нет бита `x`?

<details><summary>Ответ</summary>

База для файлов 666 (`rw-rw-rw-`), для каталогов 777. Маска снимает биты:
666 & ~022 = 644, 777 & ~022 = 755. Бит `x` файлам не выдаётся никогда — это защита от того,
чтобы любой загруженный файл автоматически становился исполняемым.

</details>

**A7.** Что делает SUID-бит? Почему `/usr/bin/passwd` обязан его иметь?

<details><summary>Ответ</summary>

SUID заставляет процесс выполняться с EUID **владельца файла**, а не запустившего.
`passwd` должен записать новый хэш в `/etc/shadow` (права `640 root:shadow`), что доступно только
root, при этом менять пароль должен уметь любой пользователь.

</details>

**A8.** Почему SUID на bash-скрипте не работает в Linux?

<details><summary>Ответ</summary>

Из-за состояния гонки (race condition) между открытием файла интерпретатором и запуском:
классическая уязвимость подмены скрипта. Поэтому ядро Linux **игнорирует** SUID у скриптов —
работает только на бинарниках. Для скриптов используют `sudo` с точечным правилом.

</details>

**A9.** Что делает SGID на **каталоге** и какую практическую задачу это решает?

<details><summary>Ответ</summary>

Новые файлы и подкаталоги внутри наследуют **группу каталога**, а не первичную группу
создателя (подкаталоги наследуют и сам SGID). Решает задачу общей папки команды: файлы, созданные
разными людьми, остаются доступными всей группе.

</details>

**A10.** Зачем `/tmp` имеет права `1777`? Что случилось бы без sticky bit?

<details><summary>Ответ</summary>

`/tmp` доступен на запись всем (`777`), иначе программы не смогли бы создавать временные
файлы. Без sticky bit любой пользователь мог бы удалить или подменить чужие временные файлы —
это и DoS, и вектор атаки (подмена файла между проверкой и использованием).

</details>

**A11.** Чем `rwS` отличается от `rws` в выводе `ls -l`? Это нормально?

<details><summary>Ответ</summary>

`rws` — SUID установлен, и бит `x` есть (файл исполняемый — рабочая ситуация).
`rwS` — SUID установлен, а `x` **нет**: файл не исполняется, бит бессмысленен. Почти всегда это
ошибка вроде `chmod 4644`.

</details>

**A12.** Что такое RUID и EUID? Какие они у процесса `passwd`, запущенного обычным пользователем?

<details><summary>Ответ</summary>

RUID — реальный владелец процесса (кто запустил), EUID — идентификатор, по которому ядро
проверяет права. Для `passwd`, запущенного пользователем 1000: RUID = 1000, EUID = 0.

</details>

**A13.** Что такое capabilities и почему `ping` больше не SUID-программа в современных дистрибутивах?

<details><summary>Ответ</summary>

Capabilities — разбиение всемогущества root на отдельные привилегии (~40 штук).
`ping` нужен только `CAP_NET_RAW` (создание raw-сокета), поэтому вместо SUID root ему выдают
`setcap cap_net_raw=ep` — при компрометации атакующий получает одну возможность, а не весь root.

</details>

**A14.** У файла в `ls -l` в конце прав стоит `+`. Что это значит и как посмотреть детали?

<details><summary>Ответ</summary>

У файла есть ACL (расширенные права). Детали: `getfacl file`.

</details>

---

### Блок B. «Что произойдёт»

**B1.** `chmod 755 deploy.sh` → какие права в символьном виде?

<details><summary>Ответ</summary>

`rwxr-xr-x`.

</details>

**B2.** `chmod u+s deploy.sh` → что покажет `ls -l`?

<details><summary>Ответ</summary>

`-rwsr-xr-x` — появился SUID (заметь `s` вместо `x` у владельца).

</details>

**B3.** `chmod -R 777 /var/www` → чем это плохо (3 причины)?

<details><summary>Ответ</summary>

(1) Любой пользователь и любой скомпрометированный процесс может изменить файлы сайта
(внедрение веб-шелла). (2) Файлы становятся исполняемыми, что расширяет вектор атаки.
(3) Ломается модель доступа — непонятно, кто и зачем реально должен иметь доступ; аудит и
комплаенс это отметят как нарушение.

</details>

**B4.** `umask 077; touch new.txt` → какие права у `new.txt`?

<details><summary>Ответ</summary>

`600` (`rw-------`).

</details>

**B5.** `umask 002; mkdir newdir` → какие права у `newdir`?

<details><summary>Ответ</summary>

`775` (`rwxrwxr-x`).

</details>

**B6.** `chmod 2775 shared` → что изменится при создании файлов внутри?

<details><summary>Ответ</summary>

Новые файлы внутри получают группу-владельца каталога, подкаталоги наследуют SGID.

</details>

**B7.** `chmod 1777 public` → кто сможет удалить чужой файл внутри?

<details><summary>Ответ</summary>

Только владелец файла (и root) — остальные не смогут, несмотря на `w` у каталога.

</details>

**B8.** `chown :devs app.conf` → что изменится?

<details><summary>Ответ</summary>

Сменится только группа-владелец на `devs`, пользователь-владелец останется прежним.

</details>

**B9.** `chmod -R u=rwX,go=rX dir/` → чем это лучше `chmod -R 755 dir/`?

<details><summary>Ответ</summary>

`X` (заглавная) даёт `x` **только каталогам** и файлам, у которых `x` уже был.
`chmod -R 755` сделал бы исполняемыми все обычные файлы (конфиги, картинки) — это и мусор, и риск.

</details>

**B10.** `sudo chattr +i app.conf; rm app.conf` → что произойдёт?

<details><summary>Ответ</summary>

Файл получает атрибут immutable — `rm` вернёт `Operation not permitted` **даже для root**,
пока не снять `chattr -i`.

</details>

**B11.** `find / -perm -4000 -type f 2>/dev/null` → что ищем и зачем?

<details><summary>Ответ</summary>

Поиск всех SUID-файлов: базовая проверка на локальное повышение привилегий и бэкдоры.

</details>

**B12.** `namei -l /var/www/html/index.html` → зачем эта команда?

<details><summary>Ответ</summary>

Показывает права на **каждый элемент пути** — быстро находит каталог без `x`,
из-за которого недоступен файл с корректными правами.

</details>

---

### Блок C. Практика

**C1. Базовое.** Выставь права:
- `app.conf` → читать может владелец и группа, писать — только владелец, остальные ничего;
- `deploy.sh` → владелец может всё, группа может читать и выполнять, остальные — ничего;
- `secret.key` → доступен **только** владельцу.

Сделай двумя способами: числовым и символьным. Проверь `stat -c '%a %A %n'`.

<details><summary>Ответ</summary>

```bash
chmod 640 app.conf     ;  chmod u=rw,g=r,o= app.conf
chmod 750 deploy.sh    ;  chmod u=rwx,g=rx,o= deploy.sh
chmod 600 secret.key   ;  chmod u=rw,go= secret.key
stat -c '%a %A %n' app.conf deploy.sh secret.key
```

</details>

**C2. Эксперимент с каталогом (обязательно выполнить!).**
Создай `~/lab06/testdir` с файлом `data.txt` внутри. Последовательно проверь от имени `nobody`:

| Права каталога | `ls testdir` | `cat testdir/data.txt` | Твоё объяснение |
|----------------|--------------|------------------------|-----------------|
| `744` (r без x) | ? | ? | |
| `711` (x без r) | ? | ? | |
| `755` | ? | ? | |
| `700` | ? | ? | |

Заполни таблицу результатами реальных команд.

<details><summary>Ответ</summary>

```bash
mkdir -p ~/lab06/testdir && echo secret | sudo tee ~/lab06/testdir/data.txt >/dev/null
sudo chmod 755 ~/lab06 ~/lab06/testdir
for m in 744 711 755 700; do
  chmod $m ~/lab06/testdir
  echo "--- mode $m"
  sudo -u nobody ls ~/lab06/testdir 2>&1 | head -1
  sudo -u nobody cat ~/lab06/testdir/data.txt 2>&1 | head -1
done
```
Ожидаемо: `744` — `ls` работает, `cat` — Permission denied (нет `x`);
`711` — `ls` запрещён, `cat` работает (знаем имя);
`755` — работает всё; `700` — не работает ничего (для `nobody`).

</details>

**C3. Удаление read-only файла.** Создай файл с правами `444` в своём каталоге и удали его.
Получилось? Объясни. Затем добейся того, чтобы файл **нельзя** было удалить, не меняя его права
(два способа).

<details><summary>Ответ</summary>

```bash
touch ro.txt && chmod 444 ro.txt && rm -f ro.txt      # удалился: решают права каталога
```
Чтобы запретить удаление, не трогая права файла:
(1) снять `w` с каталога: `chmod a-w ~/lab06`;
(2) поставить sticky bit на каталог и владеть файлом от другого пользователя (`chmod +t`);
(3) бонус — `sudo chattr +i ro.txt` (immutable).

</details>

**C4. umask.** Установи `umask 077`, создай файл и каталог, запиши права.
Затем `umask 002` — повтори. Объясни разницу и когда какой режим нужен.
Сделай `umask 027` постоянным для своего пользователя.

<details><summary>Ответ</summary>

```bash
umask 077; touch f1; mkdir d1; stat -c '%a %n' f1 d1     # 600, 700
umask 002; touch f2; mkdir d2; stat -c '%a %n' f2 d2     # 664, 775
echo 'umask 027' >> ~/.bashrc
```

</details>

**C5. Общая папка команды.** Настрой `/srv/team` так, чтобы:
- члены группы `devs` могли создавать и редактировать файлы друг друга;
- все новые файлы автоматически получали группу `devs`;
- удалять файл мог только его создатель;
- посторонние не имели доступа вообще.

*Критерий:* назови режим каталога одним числом и объясни каждую цифру.

<details><summary>Ответ</summary>

```bash
sudo mkdir -p /srv/team
sudo chgrp devs /srv/team
sudo chmod 3770 /srv/team        # 3 = 2(setgid) + 1(sticky), 770 = группе всё, чужим ничего
ls -ld /srv/team                 # drwxrws--T
```
Разбор `3770`: `2` — setgid (наследование группы), `1` — sticky (удаляет только владелец),
`7` — владелец rwx, `7` — группа rwx, `0` — остальным ничего.

</details>

**C6. Веб-каталог.** Настрой `/var/www/site` по best practice:
- владелец `www-data`, группа `www-data`;
- каталоги `755`, файлы `644`;
- каталог `uploads` доступен веб-серверу на запись.

*Критерий:* использовать `find -exec`, не ставить `777`.

<details><summary>Ответ</summary>

```bash
sudo mkdir -p /var/www/site/uploads
sudo chown -R www-data:www-data /var/www/site
sudo find /var/www/site -type d -exec chmod 755 {} +
sudo find /var/www/site -type f -exec chmod 644 {} +
sudo chmod 775 /var/www/site/uploads     # запись веб-серверу через группу
ls -lR /var/www/site
```

</details>

**C7. SSH-ключи.** Сгенерируй ключ `ssh-keygen -t ed25519 -f ~/lab06/testkey -N ""`.
Посмотри права. Специально сломай их (`chmod 644`), попробуй использовать ключ — увидь ошибку.
Восстанови правильные права на ключ и на каталог.

<details><summary>Ответ</summary>

```bash
ssh-keygen -t ed25519 -f ~/lab06/testkey -N ""
stat -c '%a %n' ~/lab06/testkey          # 600
chmod 644 ~/lab06/testkey
ssh -i ~/lab06/testkey localhost         # WARNING: UNPROTECTED PRIVATE KEY FILE
chmod 600 ~/lab06/testkey
chmod 700 ~/.ssh                          # каталог тоже важен
```

</details>

**C8. Аудит безопасности.** Напиши скрипт `/vagrant/perm_audit.sh`, который выводит:
- все SUID-файлы;
- все SGID-файлы;
- все world-writable файлы (кроме `/proc`, `/sys`, `/tmp`);
- все каталоги `777` без sticky bit;
- файлы без владельца.

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
echo "=== SUID files ==="
find / -xdev -perm -4000 -type f 2>/dev/null
echo "=== SGID files ==="
find / -xdev -perm -2000 -type f 2>/dev/null
echo "=== World-writable files ==="
find / -xdev -type f -perm -0002 2>/dev/null | grep -vE '^/(proc|sys|tmp)'
echo "=== 777 dirs without sticky bit ==="
find / -xdev -type d -perm -0002 ! -perm -1000 2>/dev/null
echo "=== Files without owner ==="
find / -xdev \( -nouser -o -nogroup \) 2>/dev/null
```

</details>

**C9. Capabilities.** Посмотри capabilities у `/usr/bin/ping`. Скопируй `/bin/cat` в `~/lab06/mycat`,
выдай ему `cap_dac_read_search` и проверь, что он теперь может читать `/etc/shadow` без root.
Потом убери capability.
*Осторожно: это демонстрация того, как легко создать дыру.*

<details><summary>Ответ</summary>

```bash
getcap /usr/bin/ping
cp /bin/cat ~/lab06/mycat
sudo setcap cap_dac_read_search+ep ~/lab06/mycat
~/lab06/mycat /etc/shadow | head -2       # читает без root!
sudo setcap -r ~/lab06/mycat
```

</details>

**C10. ACL.** Дай пользователю `nobody` право читать `secret.key`, **не меняя** группу и обычные права.
Проверь через `getfacl` и реальным чтением. Затем убери ACL.

<details><summary>Ответ</summary>

```bash
sudo setfacl -m u:nobody:r ~/lab06/secret.key
getfacl ~/lab06/secret.key
ls -l ~/lab06/secret.key                  # видно '+'
sudo -u nobody cat ~/lab06/secret.key
sudo setfacl -x u:nobody ~/lab06/secret.key
```

</details>

---

### Блок D. Инциденты

**D1.** Nginx отдаёт `403 Forbidden` на `/var/www/site/index.html`. Права файла `644 www-data:www-data`.
Назови 4 возможные причины и команды для проверки каждой.

<details><summary>Ответ</summary>

(1) Нет `x` на одном из каталогов пути — `namei -l /var/www/site/index.html`.
(2) Nginx работает не под `www-data` — проверь `ps -o user -C nginx` и директиву `user` в конфиге.
(3) SELinux/AppArmor блокирует — `getenforce`, `aa-status`, `dmesg | tail`.
(4) В конфиге nginx нет прав на каталог/индекс не тот файл, либо `root` указывает не туда —
проверь `nginx -T | grep -A3 'server {'` и лог `/var/log/nginx/error.log` (там прямо пишется причина).

</details>

**D2.** Разработчик говорит: «приложение не может писать в `/var/log/myapp`». Ты видишь
`drwxr-xr-x root root`. Как правильно исправить (и почему не `chmod 777`)?

<details><summary>Ответ</summary>

```bash
sudo chown -R myapp:myapp /var/log/myapp     # владелец — сервисный пользователь приложения
sudo chmod 755 /var/log/myapp
```
`777` дал бы право писать в логи любому процессу в системе: подмена/затирание логов, сокрытие следов
атаки, заполнение диска. Правильный подход — конкретный владелец или группа, плюс `logrotate`.

</details>

**D3.** После `git clone` скрипт `deploy.sh` не запускается: `bash: ./deploy.sh: Permission denied`.
Почему и как чинить? Как сохранить исполняемость в git навсегда?

<details><summary>Ответ</summary>

Git хранит только бит исполнения; если файл закоммичен без него (или клонирован на ФС,
не поддерживающей права — например, через Windows/FAT), `x` теряется. Лечение: `chmod +x deploy.sh`.
Навсегда: `git update-index --chmod=+x deploy.sh && git commit`. В CI надёжнее вызывать `bash deploy.sh`.

</details>

**D4.** `ssh -i ~/.ssh/id_rsa server` выдаёт:
```text:no-line-numbers
Permissions 0644 for '/home/user/.ssh/id_rsa' are too open.
```
Что делать и какие права нужны на файл и на каталог?

<details><summary>Ответ</summary>

`chmod 600 ~/.ssh/id_rsa` и `chmod 700 ~/.ssh`. Публичный ключ может быть `644`.
ssh намеренно отказывается использовать ключ, читаемый другими, потому что это равносильно утечке.

</details>

**D5.** root выполняет `rm /etc/resolv.conf` и получает `Operation not permitted`. Как такое возможно?

<details><summary>Ответ</summary>

На файле установлен атрибут immutable: `lsattr /etc/resolv.conf` покажет `----i---------`.
Снять: `sudo chattr -i /etc/resolv.conf`. (В Ubuntu этот файл часто ещё и симлинк на systemd-resolved.)

</details>

**D6.** В контейнере приложение падает с `Permission denied` при записи в примонтированный volume.
На хосте каталог принадлежит `1000:1000`, в контейнере процесс работает под UID `101`.
Три варианта решения.

<details><summary>Ответ</summary>

(1) Привести UID: запускать контейнер с `--user 1000:1000` (или `runAsUser: 1000` в k8s).
(2) Поменять владельца каталога на хосте: `chown -R 101:101 /data`.
(3) В Kubernetes использовать `fsGroup` — kubelet выставит группу на volume; для hostPath/NFS —
`supplementalGroups` или init-container, делающий `chown`. Вариант `chmod 777` — не решение.

</details>

**D7.** Аудит нашёл `/usr/local/bin/backup` с правами `-rwsr-xr-x root root`.
Почему это критично? Как проверить, обоснованно ли это, и чем заменить?

<details><summary>Ответ</summary>

SUID root означает, что любой пользователь запускает `backup` с правами root; если внутри
есть вызов внешних команд, обработка путей из `$PATH`, `tar --checkpoint-action`, или просто
возможность указать произвольный путь для записи — это прямое повышение привилегий.
Проверка: `ls -l`, `file`, `strings`/исходники, `getcap`, `dpkg -S` (пакетный ли файл).
Замена: убрать SUID (`chmod u-s`) и дать доступ через `sudo`-правило либо выдать точечную capability.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что означают цифры в `chmod 755`?

<details><summary>Ответ</summary>

Восьмеричные права для user/group/other: 7 = rwx (владелец), 5 = r-x (группа), 5 = r-x (остальные).

</details>

**2.** Чем `chmod 777` опасен?

<details><summary>Ответ</summary>

Любой пользователь или процесс может изменить и выполнить файл: подмена кода, веб-шелл,
потеря контроля над тем, кто имеет доступ. Это нарушение принципа наименьших привилегий и
стандартный пункт в чек-листах безопасности.

</details>

**3.** Как дать группе доступ к каталогу так, чтобы новые файлы наследовали группу?

<details><summary>Ответ</summary>

`chgrp devs dir && chmod 2775 dir` — SGID на каталоге обеспечивает наследование группы.

</details>

**4.** Что такое sticky bit и где он используется?

<details><summary>Ответ</summary>

Sticky bit (`+t`, `1xxx`) — в каталоге, доступном на запись всем, удалять/переименовывать файл
может только его владелец. Используется в `/tmp`, `/var/tmp`, каталогах загрузок.

</details>

**5.** Как найти все SUID-файлы в системе и зачем это делать?

<details><summary>Ответ</summary>

`find / -perm -4000 -type f 2>/dev/null`. Нужно для поиска путей локального повышения привилегий
и бэкдоров; список должен соответствовать эталонному набору дистрибутива.

</details>

**6.** Что такое umask и как он влияет на создаваемые файлы?

<details><summary>Ответ</summary>

Маска, снимающая биты при создании файлов: итог = база (666/777) минус маска.
Влияет на все создаваемые процессом файлы; задаётся в профиле или в `UMask=` у systemd-юнита.

</details>

**7.** Пользователь не может прочитать файл с правами `644`. Какие могут быть причины?

<details><summary>Ответ</summary>

Нет `x` на каком-то каталоге пути; файл на ФС, смонтированной `noexec`/`ro`; ACL или SELinux;
файл — симлинк на недоступный объект; у пользователя нет нужной группы в текущей сессии.

</details>

**8.** Чем ACL отличается от обычных прав?

<details><summary>Ответ</summary>

ACL позволяет задать права **конкретным** пользователям и группам сверх модели user/group/other,
а также права по умолчанию для новых файлов в каталоге (`setfacl -d`). Наличие видно по `+` в `ls -l`.

</details>

**9.** Может ли обычный пользователь сменить владельца своего файла?

<details><summary>Ответ</summary>

Нет. `chown` доступен только root — иначе можно было бы обходить дисковые квоты и «подбрасывать»
файлы другим пользователям. Сменить **группу** на одну из своих пользователь может (`chgrp`).

</details>

---

### 🎯 Чек-лист

- [ ] Перевожу права из символов в числа и обратно мгновенно
- [ ] Помню, что `x` на каталоге = «войти», и что удаление зависит от каталога
- [ ] Знаю про остановку проверки на первом совпадении (user → group → other)
- [ ] Понимаю umask и умею выставить его постоянно
- [ ] Настроил общую папку с SGID + sticky
- [ ] Могу за минуту продиагностировать `Permission denied` (включая `namei -l`)
- [ ] Написал `perm_audit.sh` и понимаю, зачем ищут SUID
