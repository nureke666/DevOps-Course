---
title: "05. User Management"
description: "Пользователи, группы, root: /etc/passwd, /etc/shadow, /etc/group, sudo — управление доступом в Linux"
---

# 05. User Management — пользователи, группы, root

> Источник: `05_user_management.txt` (Grasshopper, 6 уроков)
> **После темы ты умеешь:** создавать пользователей и сервисные аккаунты, управлять группами,
> настраивать sudo и читать `/etc/passwd`, `/etc/shadow`, `/etc/group` как открытую книгу.

---

## 🗺️ Схема: кто ты для системы

```text:no-line-numbers
   ТЫ (человек)              СИСТЕМА видит только ЧИСЛА
   ────────────              ──────────────────────────
   vagrant         ───────▶  UID 1000,  GID 1000,  доп. группы: 27 (sudo), 4 (adm)
                                │
                                ▼
            ┌───────────────────────────────────────────┐
            │  При каждом действии ядро сравнивает      │
            │  UID/GID процесса с владельцем файла      │
            │  → allow / EACCES (Permission denied)     │
            └───────────────────────────────────────────┘

   Имена — это просто «человекочитаемая обёртка» из /etc/passwd.
   Удалишь пользователя — файлы останутся с его UID (и покажутся как «1001»).
```

Три файла, где живёт вся эта информация:

```text:no-line-numbers
/etc/passwd   — кто есть в системе (читаемый всем)
/etc/shadow   — пароли в виде хэшей (только root!)
/etc/group    — какие есть группы и кто в них состоит
/etc/gshadow  — пароли групп (редко используется)
```

---

## 1. Users and Groups

**Пользователь (user)** — учётная запись с уникальным **UID**.
**Группа (group)** — набор пользователей с общим **GID**; используется для совместного доступа к файлам.

Типы пользователей:

| Тип | UID | Примеры | Зачем |
|-----|-----|---------|-------|
| **root** | 0 | root | Полные права, обходит все проверки |
| **Системные / сервисные** | 1-999 | `www-data`, `nginx`, `postgres`, `sshd` | Под ними работают демоны. **Без права логина!** |
| **Обычные** | ≥1000 | `vagrant`, `nurik` | Люди |
| `nobody` | 65534 | nobody | Минимальные права, для изоляции |

Группы бывают:
- **Первичная (primary)** — одна, записана в `/etc/passwd`; её GID получают создаваемые файлы.
- **Вторичные (secondary)** — сколько угодно, записаны в `/etc/group`; дают дополнительные права.

```bash
id                 # uid=1000(vagrant) gid=1000(vagrant) groups=1000(vagrant),27(sudo)
id nurik
whoami             # текущее имя
groups             # список групп текущего пользователя
who                # кто сейчас залогинен
w                  # кто залогинен + что делает + load average
last                # история входов
lastlog            # когда каждый юзер входил последний раз
```

💡 Важные системные группы Ubuntu/Debian:

| Группа | Что даёт |
|--------|----------|
| `sudo` | Право выполнять команды от root через `sudo` (в RHEL — `wheel`) |
| `adm` | Чтение логов в `/var/log` |
| `docker` | Управление Docker → **фактически равно root!** |
| `www-data` | Доступ к файлам веб-сервера |
| `systemd-journal` | Чтение journald |

⚠️ **Добавить пользователя в группу `docker` = выдать ему root.** Через `docker run -v /:/host`
он смонтирует корень хоста. Знать и не раздавать бездумно.

---

## 2. root — суперпользователь

```bash
sudo command             # выполнить одну команду от root ← ПРАВИЛЬНЫЙ способ
sudo -i                  # интерактивный root-shell с его окружением
sudo -s                  # root-shell с твоим окружением
sudo -u postgres psql    # выполнить от имени ДРУГОГО пользователя
sudo -l                  # что мне разрешено через sudo
su -                     # переключиться в root (нужен пароль root)
su - username            # стать другим пользователем
exit                     # вернуться
```

`sudo` vs `su`:

| | `sudo` | `su` |
|---|--------|------|
| Пароль | **свой** | пароль целевого пользователя |
| Логирование | да, в `/var/log/auth.log` | минимальное |
| Гранулярность | можно разрешить конкретные команды | всё или ничего |
| В Ubuntu | по умолчанию | root-пароль вообще не задан |

**Почему не работают под root постоянно:**
1. Опечатка = катастрофа (`rm -rf / var/log`).
2. Нет разграничения — кто именно что сделал.
3. Скомпрометированный процесс сразу получает полный контроль.
4. `sudo` пишет в audit-лог — нужен для расследований и комплаенса.

### Настройка sudo — `/etc/sudoers`

🔴 **Редактировать ТОЛЬКО через `visudo`** — он проверяет синтаксис перед сохранением.
Ошибка в sudoers без visudo = ты навсегда потерял sudo на этой машине.

```bash
sudo visudo                              # основной файл
sudo visudo -f /etc/sudoers.d/deploy     # отдельный файл ← ПРАВИЛЬНАЯ практика
```

Формат правила:
```text:no-line-numbers
пользователь ХОСТ=(КАК_КТО:КАК_ГРУППА) КОМАНДЫ

root     ALL=(ALL:ALL) ALL
%sudo    ALL=(ALL:ALL) ALL                 # % = группа
deploy   ALL=(ALL) NOPASSWD: /bin/systemctl restart myapp, /usr/bin/journalctl -u myapp
nurik    ALL=(www-data) /usr/bin/php
```

`NOPASSWD` — без запроса пароля (нужно для CI/автоматизации, но выдавай **только конкретные команды**).

⚠️ Анти-паттерн: `deploy ALL=(ALL) NOPASSWD: ALL` — это просто выдача root без пароля.
⚠️ Ещё анти-паттерн: `NOPASSWD: /bin/vim` — из vim можно выполнить `:!bash` и получить root-шелл.
То же с `less`, `find -exec`, `awk`, `tar --checkpoint-action`. Смотри GTFOBins.

---

## 3. /etc/passwd — кто есть в системе

Читается **всеми** (поэтому паролей там давно нет — только `x`).

```text:no-line-numbers
vagrant:x:1000:1000:Vagrant User,,,:/home/vagrant:/bin/bash
   │    │   │    │        │              │           │
   │    │   │    │        │              │           └─ 7. Shell при логине
   │    │   │    │        │              └───────────── 6. Домашний каталог
   │    │   │    │        └──────────────────────────── 5. GECOS (ФИО, телефон — комментарий)
   │    │   │    └───────────────────────────────────── 4. GID первичной группы
   │    │   └────────────────────────────────────────── 3. UID
   │    └────────────────────────────────────────────── 2. Пароль: 'x' = смотри /etc/shadow
   └─────────────────────────────────────────────────── 1. Имя пользователя
```

```bash
cat /etc/passwd
getent passwd vagrant        # ПРАВИЛЬНЫЙ способ (учитывает LDAP/SSSD, не только файл)
getent passwd 1000

# Только реальные пользователи (UID >= 1000)
awk -F: '$3 >= 1000 && $3 < 65534 {print $1, $3, $7}' /etc/passwd

# Кто может логиниться (shell не nologin/false)
grep -vE '(nologin|false)$' /etc/passwd | cut -d: -f1
```

💡 `/usr/sbin/nologin` или `/bin/false` в 7-м поле — **пользователь не может войти в систему**.
Так и должны выглядеть все сервисные аккаунты. Если у `postgres` вдруг `/bin/bash` — это повод разобраться.

---

## 4. /etc/shadow — хэши паролей

Права `640 root:shadow` — обычный пользователь прочитать не может. Это и есть защита.

```text:no-line-numbers
vagrant:$6$xyz...$abc...:19700:0:99999:7:::
   │           │            │   │   │   │││
   │           │            │   │   │   ││└─ 9. Зарезервировано
   │           │            │   │   │   │└── 8. Дата истечения аккаунта
   │           │            │   │   │   └─── 7. Дней неактивности после истечения пароля
   │           │            │   │   └─────── 6. За сколько дней предупредить (7)
   │           │            │   └─────────── 5. Максимум дней жизни пароля (99999 = не истекает)
   │           │            └─────────────── 4. Минимум дней между сменами (0)
   │           └──────────────────────────── 3. Дата последней смены (дней с 01.01.1970)
   └──────────────────────────────────────── 2. ХЭШ пароля
```

Формат хэша: `$id$salt$hash`

| id | Алгоритм |
|----|----------|
| `$1$` | MD5 — устарел, небезопасен |
| `$5$` | SHA-256 |
| `$6$` | SHA-512 ← стандарт |
| `$y$` | yescrypt ← современный дефолт в Ubuntu 22.04+/Debian 12 |

Спецзначения второго поля:
- `*` или `!` — вход по паролю **запрещён** (типично для сервисных аккаунтов);
- `!хэш` — аккаунт **заблокирован** (`passwd -l`), хэш сохранён;
- пустое поле — **вход без пароля** (🔴 критическая дыра).

```bash
sudo grep vagrant /etc/shadow
sudo chage -l vagrant             # политика пароля в читаемом виде
sudo chage -M 90 -W 14 nurik      # пароль жив 90 дней, предупреждать за 14
sudo passwd -l nurik              # заблокировать
sudo passwd -u nurik              # разблокировать
sudo passwd -e nurik              # потребовать смену пароля при следующем входе
```

---

## 5. /etc/group

```text:no-line-numbers
sudo:x:27:vagrant,nurik
 │   │  │        │
 │   │  │        └─ 4. Список членов (ВТОРИЧНЫХ!) через запятую
 │   │  └────────── 3. GID
 │   └───────────── 2. Пароль группы (x / пусто, почти не используется)
 └────────────────── 1. Имя группы
```

⚠️ **Тонкость, на которой ловят на собеседованиях:** пользователь, для которого эта группа
**первичная**, в 4-м поле **не указывается** — связь идёт через GID в `/etc/passwd`.
Поэтому «правда» о группах — это `id username`, а не `grep group /etc/group`.

```bash
getent group sudo
groups nurik
id -nG nurik                  # имена всех групп
lid -g docker                 # кто в группе (если установлен)
getent group | awk -F: '$3 >= 1000 {print $1, $3}'   # пользовательские группы
```

---

## 6. User Management Tools

### Создание пользователя

Два семейства команд — знать разницу спрашивают на собесе:

| | `useradd` (низкоуровневая) | `adduser` (Debian-скрипт) |
|---|---|---|
| Домашний каталог | только с `-m` | создаёт сам |
| Пароль | отдельно `passwd` | спрашивает интерактивно |
| Shell | из `/etc/default/useradd` | спрашивает/дефолт разумный |
| Где есть | **везде** | Debian/Ubuntu |
| Для скриптов | ✅ да | ❌ интерактивная |

```bash
# Человек (интерактивно, Ubuntu)
sudo adduser nurik
sudo usermod -aG sudo nurik

# Человек (портируемо, для скриптов/Ansible)
sudo useradd -m -s /bin/bash -c "Nurdaulet, DevOps" nurik
sudo passwd nurik
sudo usermod -aG sudo,adm nurik

# СЕРВИСНЫЙ аккаунт для приложения ← частая задача DevOps
sudo useradd --system --no-create-home --shell /usr/sbin/nologin appuser
# или в Debian-стиле:
sudo adduser --system --group --no-create-home --shell /usr/sbin/nologin appuser
id appuser
```

Основные опции `useradd`:

| Опция | Смысл |
|-------|-------|
| `-m` | Создать домашний каталог |
| `-d /path` | Свой путь домашнего каталога |
| `-s /bin/bash` | Shell (`/usr/sbin/nologin` для сервисов) |
| `-g group` | Первичная группа |
| `-G g1,g2` | Вторичные группы |
| `-u 1500` | Задать UID вручную |
| `-c "текст"` | GECOS-комментарий |
| `-e 2026-12-31` | Дата истечения аккаунта |
| `-r` / `--system` | Системный пользователь (UID < 1000) |

### Изменение

```bash
sudo usermod -aG docker nurik     # ДОБАВИТЬ в группу (-a обязательно!)
sudo usermod -G docker nurik      # 🔴 ЗАМЕНИТЬ все вторичные группы — потеряешь sudo!
sudo usermod -s /usr/sbin/nologin nurik   # сменить shell
sudo usermod -l newname oldname   # переименовать
sudo usermod -d /new/home -m nurik  # переместить домашний каталог
sudo usermod -L nurik             # заблокировать (= passwd -l)
sudo usermod -U nurik             # разблокировать
sudo usermod -e 2026-12-31 nurik  # срок действия аккаунта
```

🔴 **Самая частая ошибка новичка:** `usermod -G` без `-a`. Флаг `-a` (append) = добавить.
Без него список вторичных групп **перезаписывается**, и пользователь вылетает из `sudo`.
Мнемоника: **«-aG всегда вместе»**.

### Удаление

```bash
sudo userdel nurik              # удалить юзера, домашний каталог ОСТАЁТСЯ
sudo userdel -r nurik           # удалить вместе с домашним каталогом и почтой
sudo deluser --remove-home nurik      # Debian-вариант
sudo deluser nurik sudo               # убрать из группы sudo

# Найти "бесхозные" файлы после удаления
sudo find / -nouser -o -nogroup 2>/dev/null
```

### Группы

```bash
sudo groupadd developers
sudo groupadd -g 5000 deploy         # с конкретным GID
sudo groupmod -n devs developers     # переименовать
sudo groupdel developers
sudo gpasswd -a nurik developers     # добавить в группу
sudo gpasswd -d nurik developers     # удалить из группы
newgrp developers                    # временно сменить первичную группу в текущем шелле
```

⚠️ **Изменения групп применяются только при новом логине.** Добавил себя в `docker` — сделай
`exit` и зайди заново (или `newgrp docker`), иначе `docker ps` будет ругаться на права.

### Пароли

```bash
passwd                      # сменить свой
sudo passwd nurik           # сменить чужой
echo "nurik:NewPass123" | sudo chpasswd   # массово/в скриптах
sudo passwd -S nurik        # статус: P = пароль есть, L = заблокирован, NP = нет пароля
```

---

## 💼 Как это в DevOps

- **Сервисные аккаунты:** каждое приложение работает под своим непривилегированным юзером.
  `User=appuser` в systemd-юните — прямое следствие этой темы.
- **Принцип наименьших привилегий:** приложение не должно ходить под root, даже в контейнере
  (`USER appuser` в Dockerfile, `runAsNonRoot: true` в Kubernetes).
- **Деплой-пользователь:** отдельный юзер с SSH-ключом и точечным sudo только на нужные команды.
- **UID/GID в контейнерах:** проблема прав на volume — это несовпадение UID внутри и снаружи.
- **Ansible:** модули `user`, `group`, `authorized_key` делают ровно то, что ты делаешь руками.
- **Аудит:** `last`, `/var/log/auth.log`, `sudo -l` — база для расследования инцидентов.

---

## 🧪 Мини-лаба

```bash
vagrant ssh
sudo -i     # для удобства (в проде так не привыкай)

# 1. Разведка
id; groups; who; last | head
awk -F: '$3 >= 1000 && $3 < 65534' /etc/passwd

# 2. Создать человека
useradd -m -s /bin/bash -c "Test Developer" devuser
passwd devuser            # задай пароль
id devuser
ls -la /home/devuser

# 3. Группы
groupadd developers
usermod -aG developers devuser
id devuser
getent group developers

# 4. Сервисный аккаунт для приложения
useradd --system --no-create-home --shell /usr/sbin/nologin appsvc
id appsvc
grep appsvc /etc/passwd          # смотри shell и UID < 1000
su - appsvc                      # должно НЕ пустить — это правильно

# 5. Общий каталог для группы
mkdir -p /srv/shared
chown root:developers /srv/shared
chmod 2770 /srv/shared           # setgid — про него в теме 06
ls -ld /srv/shared

# 6. Политика пароля
chage -l devuser
chage -M 90 -W 7 devuser
chage -l devuser

# 7. Точечный sudo
visudo -f /etc/sudoers.d/devuser
#   devuser ALL=(ALL) NOPASSWD: /bin/systemctl restart nginx
# проверка:
su - devuser -c "sudo -l"

# 8. Блокировка и удаление
passwd -l devuser; passwd -S devuser
passwd -u devuser
userdel -r devuser
groupdel developers
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `id [user]` | UID, GID, все группы — **источник правды** |
| `whoami` / `groups` / `who` / `w` | Кто я / мои группы / кто в системе |
| `getent passwd\|group [имя]` | Данные с учётом LDAP, а не только файла |
| `useradd -m -s /bin/bash user` | Создать (скриптово) |
| `adduser user` | Создать (интерактивно, Debian) |
| `useradd --system --shell /usr/sbin/nologin svc` | Сервисный аккаунт |
| `usermod -aG group user` | **Добавить** в группу (не забудь `-a`!) |
| `userdel -r user` | Удалить с домашним каталогом |
| `groupadd` / `groupdel` / `gpasswd -a\|-d` | Группы |
| `passwd [-l\|-u\|-S\|-e] user` | Пароли |
| `chage -l user` | Политика пароля |
| `sudo -l` / `sudo -u user cmd` | Что можно / выполнить от другого |
| `visudo [-f /etc/sudoers.d/x]` | Безопасная правка sudoers |
| `last` / `lastlog` | История входов |

---

## 🧠 Что запомнить

1. Система работает с **UID/GID**, имена — обёртка. Удалённый юзер оставляет файлы с «сиротским» UID.
2. `/etc/passwd` (все читают) · `/etc/shadow` (только root, хэши) · `/etc/group`.
3. **`usermod -aG`, всегда с `-a`.** Без `-a` затираются все вторичные группы.
4. Членство в группах обновляется **после нового логина**.
5. Сервисные аккаунты: `--system`, без домашнего каталога, shell `nologin`.
6. `sudo` вместо `su`; правка sudoers — только `visudo`, лучше в `/etc/sudoers.d/`.
7. Группа `docker` ≈ root. Выдавать осознанно.
8. `id user` — правда о группах; `/etc/group` не показывает первичную.

---

## Задачи

> 🔴 Тема меняет систему — **обязательно** `vagrant snapshot save before_05` перед началом.

---

### Блок A. Теория

**A1.** Что такое UID и GID? Почему система оперирует числами, а не именами? Что произойдёт с файлами
пользователя после `userdel`?

<details><summary>Ответ</summary>

UID/GID — числовые идентификаторы пользователя и группы. Ядро проверяет права, сравнивая
числа; имена нужны только людям и берутся из `/etc/passwd`. После `userdel` файлы остаются, но
владелец отображается числом (имени больше нет). Если создать нового пользователя с тем же UID,
он **унаследует** доступ к этим файлам — классическая дыра.

</details>

**A2.** Чем первичная группа отличается от вторичной? Где хранится каждая?

<details><summary>Ответ</summary>

Первичная указана в 4-м поле `/etc/passwd` (GID), она присваивается новым файлам пользователя;
она одна. Вторичные перечислены в `/etc/group` и дают дополнительный доступ; их может быть много.

</details>

**A3.** Разбери по полям строку:
```text:no-line-numbers
appuser:x:113:119:App Service,,,:/nonexistent:/usr/sbin/nologin
```
Это человек или сервис? Как ты это понял (два признака)?

<details><summary>Ответ</summary>

`appuser` — имя; `x` — пароль в shadow; `113` — UID; `119` — GID; `App Service,,,` — GECOS;
`/nonexistent` — домашний каталог; `/usr/sbin/nologin` — shell.
Это **сервис**: (1) UID < 1000, (2) shell `nologin` и отсутствующий домашний каталог.

</details>

**A4.** Почему в `/etc/passwd` вместо пароля стоит `x`? Какие права у `/etc/shadow` и почему именно такие?

<details><summary>Ответ</summary>

Исторически хэши хранились в `/etc/passwd`, который обязан быть читаемым всем (чтобы `ls -l`
мог показывать имена). Это позволяло любому пользователю брутфорсить хэши. Поэтому хэши вынесли в
`/etc/shadow` с правами `640 root:shadow`, а в passwd оставили заглушку `x`.

</details>

**A5.** Что означают в `/etc/shadow` значения второго поля: `$6$...`, `*`, `!$6$...`, пустое?

<details><summary>Ответ</summary>

`$6$...` — SHA-512-хэш пароля (вход возможен); `*` — вход по паролю невозможен (обычно
сервисный аккаунт, никогда не имел пароля); `!$6$...` — аккаунт заблокирован (`passwd -l`), хэш
сохранён и восстановим; пустое поле — **вход без пароля**, критическая уязвимость.

</details>

**A6.** Чем `sudo` лучше `su` с точки зрения эксплуатации и безопасности (3 аргумента)?

<details><summary>Ответ</summary>

(1) Каждое действие логируется с указанием реального пользователя (`/var/log/auth.log`) —
есть аудит. (2) Не нужно раздавать общий root-пароль, каждый вводит свой. (3) Права гранулярны:
можно разрешить только конкретные команды и отозвать доступ у одного человека, не меняя ничего у остальных.

</details>

**A7.** Почему `/etc/sudoers` правят только через `visudo`?

<details><summary>Ответ</summary>

`visudo` блокирует файл от параллельной правки и **проверяет синтаксис** перед сохранением.
Синтаксическая ошибка в sudoers делает sudo полностью неработоспособным, и, если root-пароля нет,
восстановление возможно только через single-user/rescue-режим.

</details>

**A8.** Что не так с правилом `deploy ALL=(ALL) NOPASSWD: /usr/bin/vim`?

<details><summary>Ответ</summary>

Из `vim` можно выполнить `:!/bin/bash` — получится root-shell. Таким образом правило
«только vim» равносильно полному root. Аналогично опасны `less`, `more`, `find`, `awk`, `tar`,
`systemctl` (через pager). Справочник таких обходов — GTFOBins.

</details>

**A9.** Чем `useradd` отличается от `adduser`? Какой использовать в скрипте и почему?

<details><summary>Ответ</summary>

`useradd` — низкоуровневая утилита, есть во всех дистрибутивах, ничего не делает «за тебя»
(нужны `-m`, `-s`). `adduser` — высокоуровневый интерактивный Perl-скрипт Debian/Ubuntu.
В скриптах — **только `useradd`**: он неинтерактивен и переносим.

</details>

**A10.** Почему добавление пользователя в группу `docker` фактически равно выдаче root?

<details><summary>Ответ</summary>

Демон Docker работает от root, а членство в группе `docker` даёт полный доступ к его сокету.
Команда `docker run -v /:/host -it alpine chroot /host` даёт root-шелл на хосте. Никакого
дополнительного повышения привилегий не требуется.

</details>

**A11.** Пользователь есть в `/etc/group` в строке `developers`, но `id` не показывает эту группу
в текущей сессии. Почему?

<details><summary>Ответ</summary>

Членство во вторичных группах вычисляется при **входе в систему** и записывается в
credentials процесса. Текущая сессия ничего не знает об изменении — нужен новый логин
(`exit` + вход) или `newgrp developers` для текущего шелла.

</details>

**A12.** В `/etc/group` в строке `devuser:x:1001:` список членов пуст, но `id devuser` показывает
группу `devuser`. Противоречие? Объясни.

<details><summary>Ответ</summary>

Противоречия нет: в 4-м поле `/etc/group` перечисляются только **вторичные** члены.
Для `devuser` группа `devuser` является **первичной** и указана через GID в `/etc/passwd`.
Поэтому источник правды — `id`, а не `/etc/group`.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  id
B2.  id -nG nurik
B3.  getent passwd 1000
B4.  awk -F: '$3 >= 1000 && $3 < 65534 {print $1}' /etc/passwd
B5.  grep -vE '(nologin|false)$' /etc/passwd | cut -d: -f1
B6.  sudo passwd -S devuser
B7.  sudo chage -l devuser
B8.  usermod -aG docker nurik
B9.  usermod -G docker nurik
B10. sudo -u postgres psql -c '\l'
B11. sudo find / -nouser 2>/dev/null
B12. echo "devuser:Str0ngPass" | sudo chpasswd
B13. newgrp developers
B14. last -n 5
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  UID, GID и все группы текущего пользователя.
B2.  Только имена всех групп пользователя nurik.
B3.  Запись пользователя с UID 1000 (через NSS: файл, LDAP, SSSD).
B4.  Имена «человеческих» пользователей (UID 1000-65533).
B5.  Пользователи, у которых shell не nologin/false — то есть кто может войти.
B6.  Статус пароля: P — установлен, L — заблокирован, NP — пароля нет.
B7.  Политика пароля: даты последней смены, истечения, предупреждения.
B8.  Добавляет nurik в группу docker, сохраняя остальные группы.
B9.  Заменяет все вторичные группы на одну docker — пользователь теряет sudo и остальные.
B10. Выполняет psql -c '\l' от имени пользователя postgres (типовой способ работы с БД).
B11. Ищет файлы, у которых нет владельца в системе, — «сироты» после удаления пользователей.
B12. Неинтерактивно задаёт пароль (используется в скриптах/Ansible; помни про историю команд).
B13. Запускает новый шелл с первичной группой developers — применяет членство без перелогина.
B14. Последние 5 записей о входах в систему.
```

</details>

**B15.** В чём разница между `su - nurik` и `su nurik` (с дефисом и без)?

<details><summary>Ответ</summary>

`su - nurik` — **login shell**: загружает окружение целевого пользователя
(`$HOME`, `$PATH`, профили, переход в его домашний каталог). `su nurik` — сохраняет текущее
окружение и каталог, что часто приводит к странным ошибкам («команда не найдена», запись в чужой `$HOME`).
Правило: всегда с дефисом.

</details>

---

### Блок C. Практика

**C1. Разведка.** Ответь командами:
- сколько «человеческих» пользователей в системе (UID ≥ 1000)?
- кто может логиниться (имеет настоящий shell)?
- кто входит в группу `sudo`?
- когда последний раз входил пользователь `vagrant`?

<details><summary>Ответ</summary>

```bash
awk -F: '$3>=1000 && $3<65534 {print $1}' /etc/passwd
grep -vE '(nologin|false)$' /etc/passwd | cut -d: -f1
getent group sudo
last vagrant | head -3
```

</details>

**C2. Создай человека.** Пользователь `devuser`:
- домашний каталог создан;
- shell `/bin/bash`;
- комментарий «Developer User»;
- входит в группы `sudo` и `adm`;
- пароль установлен и должен быть сменён при первом входе.

*Критерии приёмки:* `id devuser` показывает обе группы, `ls -ld /home/devuser` существует,
`sudo chage -l devuser` показывает, что смена пароля требуется.

<details><summary>Ответ</summary>

```bash
sudo useradd -m -s /bin/bash -c "Developer User" -G sudo,adm devuser
sudo passwd devuser
sudo passwd -e devuser          # потребовать смену при первом входе
id devuser && sudo chage -l devuser
```

</details>

**C3. Сервисный аккаунт.** Создай `appsvc` для приложения так, чтобы:
- UID был системным (< 1000);
- **не было** домашнего каталога;
- вход в систему был невозможен.

*Проверка:* `su - appsvc` должен отказать; `grep appsvc /etc/passwd` показывает `nologin`.

<details><summary>Ответ</summary>

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin appsvc
grep appsvc /etc/passwd
sudo su - appsvc                # "This account is currently not available"
```

</details>

**C4. Групповая работа.** Создай группу `developers`, добавь в неё `devuser` и `vagrant`.
Создай каталог `/srv/project`, владелец `root:developers`, чтобы:
- члены группы могли создавать там файлы;
- посторонние не могли даже заглянуть внутрь.

*Проверка:* от `devuser` создать файл получается, от `nobody` — `ls` падает с Permission denied.

<details><summary>Ответ</summary>

```bash
sudo groupadd developers
sudo usermod -aG developers devuser
sudo usermod -aG developers vagrant
sudo mkdir -p /srv/project
sudo chown root:developers /srv/project
sudo chmod 2770 /srv/project     # 2 = setgid: новые файлы наследуют группу
ls -ld /srv/project
sudo -u devuser touch /srv/project/test.txt   # должно сработать
sudo -u nobody ls /srv/project                # Permission denied
```

</details>

**C5. Ошибка и восстановление.** Специально выполни `sudo usermod -G developers devuser`
(без `-a`). Посмотри `id devuser` — что пропало? Восстанови корректно.
**Этот пункт обязателен: нужно увидеть последствия своими глазами.**

<details><summary>Ответ</summary>

```bash
sudo usermod -G developers devuser
id devuser                        # пропали sudo и adm!
sudo usermod -aG sudo,adm devuser # восстановление
id devuser
```

</details>

**C6. Политика паролей.** Для `devuser` установи: пароль живёт 90 дней, минимум 1 день между сменами,
предупреждение за 14 дней. Покажи результат через `chage -l`.

<details><summary>Ответ</summary>

```bash
sudo chage -M 90 -m 1 -W 14 devuser
sudo chage -l devuser
```

</details>

**C7. Точечный sudo.** Создай `/etc/sudoers.d/deploy` так, чтобы `devuser` мог **без пароля**
выполнять только `systemctl restart nginx` и `systemctl status nginx`, и ничего больше.
*Проверка:* `sudo -u devuser sudo -l` показывает только эти команды; попытка `sudo -u devuser sudo cat /etc/shadow` — отказ.

<details><summary>Ответ</summary>

```bash
sudo visudo -f /etc/sudoers.d/deploy
# содержимое:
#   devuser ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart nginx, /usr/bin/systemctl status nginx
sudo chmod 0440 /etc/sudoers.d/deploy
sudo -u devuser sudo -l
```

</details>

**C8. Блокировка.** Заблокируй `devuser`, проверь статус, попробуй войти, разблокируй.
Покажи, как изменилось второе поле в `/etc/shadow`.

<details><summary>Ответ</summary>

```bash
sudo passwd -l devuser
sudo passwd -S devuser                  # L
sudo grep devuser /etc/shadow           # хэш начинается с '!'
sudo passwd -u devuser
sudo passwd -S devuser                  # P
```

</details>

**C9. Аудит.** Напиши скрипт `/vagrant/user_audit.sh`, который выводит:
```text:no-line-numbers
=== USER AUDIT ===
Human users (UID>=1000): devuser, vagrant
Users with shell access: root, devuser, vagrant
Sudo members: vagrant, devuser
Users with NO password set: (none)
Locked accounts: appsvc
UID 0 accounts: root            <-- красный флаг, если больше одного
```

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "=== USER AUDIT ==="
printf 'Human users (UID>=1000): %s\n' \
  "$(awk -F: '$3>=1000 && $3<65534 {print $1}' /etc/passwd | paste -sd', ')"
printf 'Users with shell access: %s\n' \
  "$(grep -vE '(nologin|false)$' /etc/passwd | cut -d: -f1 | paste -sd', ')"
printf 'Sudo members: %s\n' "$(getent group sudo | cut -d: -f4)"
printf 'Users with NO password set: %s\n' \
  "$(sudo awk -F: '$2 == "" {print $1}' /etc/shadow | paste -sd', ' || echo '(none)')"
printf 'Locked accounts: %s\n' \
  "$(sudo awk -F: '$2 ~ /^!/ {print $1}' /etc/shadow | paste -sd', ')"
printf 'UID 0 accounts: %s\n' "$(awk -F: '$3==0 {print $1}' /etc/passwd | paste -sd', ')"
```

</details>

**C10. Уборка.** Удали `devuser` вместе с домашним каталогом, удали `appsvc` и группу `developers`.
Проверь, не осталось ли файлов без владельца.

<details><summary>Ответ</summary>

```bash
sudo userdel -r devuser
sudo userdel appsvc
sudo groupdel developers
sudo find / -nouser -o -nogroup 2>/dev/null | head
```

</details>

---

### Блок D. Инциденты

**D1.** Коллега выполнил `usermod -G docker admin` и вылетел из sudo. Сейчас в системе
никто не может получить root через sudo, root-пароль не задан. Что делать? (Подсказка: тема 11.)

<details><summary>Ответ</summary>

Нужен физический/консольный доступ: перезагрузка → в GRUB нажать `e` → добавить к строке
`linux` параметр `init=/bin/bash` (или `single`) → `Ctrl+X` → перемонтировать корень на запись
`mount -o remount,rw /` → `usermod -aG sudo admin` → `exec /sbin/init` или reboot.
В облаке альтернатива — rescue-режим/монтирование диска к другой ВМ или доступ через
serial console/cloud-init. Подробно — в теме [11](/linux/11-boot-the-system).

</details>

**D2.** Приложение на сервере работает под root. Тимлид требует перевести на отдельного пользователя.
Опиши шаги: что создать, что поменять в правах, что в systemd-юните, как проверить.

<details><summary>Ответ</summary>

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin myapp
sudo chown -R myapp:myapp /opt/myapp /var/log/myapp /var/lib/myapp
# в unit-файле:
#   [Service]
#   User=myapp
#   Group=myapp
#   NoNewPrivileges=yes
#   ProtectSystem=strict
sudo systemctl daemon-reload && sudo systemctl restart myapp
ps -o user,pid,cmd -C myapp        # проверка: процесс от myapp, не root
```
Отдельно проверить: порт < 1024 требует root или `AmbientCapabilities=CAP_NET_BIND_SERVICE`.

</details>

**D3.** После `userdel appuser` вывод `ls -l /var/lib/app` показывает владельца `1002` вместо имени.
Что произошло и как исправить правильно?

<details><summary>Ответ</summary>

Пользователь удалён, но файлы остались с его UID; отображается число, потому что имя больше
не резолвится. Исправление: решить, кому файлы должны принадлежать, и сделать
`sudo chown -R newowner:newgroup /var/lib/app`. Опасность — создать нового пользователя с тем же UID:
он автоматически получит доступ к этим файлам. Поиск сирот: `find / -nouser -o -nogroup`.

</details>

**D4.** `sudo: /etc/sudoers.d/deploy: syntax error near line 2` — sudo вообще перестал работать.
Как чинить? Как было избежать?

<details><summary>Ответ</summary>

Если открыта хотя бы одна сессия с root (`sudo -i`) — просто удалить/исправить файл.
Если нет — загрузиться в single-user/rescue и поправить. Избежать: **только `visudo -f`**,
который бы не дал сохранить файл с ошибкой; плюс права `0440` на файлы в `sudoers.d`.

</details>

**D5.** Пользователь жалуется: «добавили в группу `docker`, но `docker ps` пишет permission denied».
`id user` действительно не показывает `docker`, хотя `getent group docker` его содержит. Диагноз?

<details><summary>Ответ</summary>

Изменение группы не применяется к уже открытой сессии. Нужно выйти и войти заново,
либо `newgrp docker`. Проверка после перелогина: `id | grep docker`.
Дополнительно проверить, что сервис docker запущен и сокет `/var/run/docker.sock` принадлежит группе `docker`.

</details>

**D6.** В `/etc/passwd` обнаружена строка `backup2:x:0:0::/root:/bin/bash`. Почему это критично?
Как найти такие аккаунты автоматически?

<details><summary>Ответ</summary>

UID 0 = полный root; аккаунт с другим именем, но UID 0 — классический бэкдор:
он не виден в списке членов группы sudo и не попадает в обычные проверки.
Поиск: `awk -F: '$3 == 0 {print $1}' /etc/passwd` — результат должен быть ровно `root`.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Чем отличаются `/etc/passwd`, `/etc/shadow`, `/etc/group`?

<details><summary>Ответ</summary>

`/etc/passwd` — учётные записи (имя, UID, GID, home, shell), читают все. `/etc/shadow` — хэши
паролей и политика их устаревания, только root. `/etc/group` — группы и их вторичные члены.

</details>

**2.** Как создать пользователя без возможности логина и зачем это нужно?

<details><summary>Ответ</summary>

`useradd --system --shell /usr/sbin/nologin svc`. Нужно для демонов: приложение получает
собственные права на файлы, но его учётку нельзя использовать для входа, даже если пароль утечёт.

</details>

**3.** В чём опасность `usermod -G` без `-a`?

<details><summary>Ответ</summary>

`-G` **заменяет** список вторичных групп, `-aG` добавляет. Без `-a` пользователь теряет `sudo`,
`adm`, `docker` и т.п.

</details>

**4.** Как дать пользователю право перезапускать один конкретный сервис без полного sudo?

<details><summary>Ответ</summary>

Файл в `/etc/sudoers.d/` с правилом
`user ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart myapp`, созданный через `visudo -f`.

</details>

**5.** Как узнать все группы пользователя? Почему `grep` по `/etc/group` — ненадёжный способ?

<details><summary>Ответ</summary>

`id user` / `id -nG user`. `grep` по `/etc/group` не покажет **первичную** группу и пропустит
пользователей из LDAP/SSSD — а `id` работает через NSS и видит все источники.

</details>

**6.** Что такое UID 0? Может ли в системе быть два пользователя с UID 0?

<details><summary>Ответ</summary>

UID 0 — суперпользователь; права определяются числом, а не именем. Два аккаунта с UID 0
технически возможны, и оба будут полноценным root — обычно это признак компрометации.

</details>

**7.** Как заблокировать учётную запись и чем это отличается от удаления?

<details><summary>Ответ</summary>

`passwd -l user` / `usermod -L user` — ставит `!` перед хэшем, вход по паролю невозможен,
но файлы, UID, cron и ключи остаются; операция обратима. Удаление (`userdel -r`) необратимо
и оставляет файлы с «осиротевшим» UID в других местах ФС.

</details>

**8.** Что произойдёт с процессами пользователя после его удаления?

<details><summary>Ответ</summary>

Процессы **продолжают работать** — ядро знает только UID. После завершения они уже не запустятся
через login, но cron-задания и сервисы могут ломаться. Правильный порядок: остановить сервисы,
снять cron, потом удалять пользователя.

</details>

---

### 🎯 Чек-лист

- [ ] Читаю строку `/etc/passwd` и `/etc/shadow` по полям без подсказок
- [ ] Создаю человека и сервисный аккаунт разными правильными командами
- [ ] Помню про `-aG` и про перелогин после смены групп
- [ ] Умею настраивать точечный sudo через `/etc/sudoers.d/` и `visudo -f`
- [ ] Знаю, чем `passwd -l` отличается от `userdel`
- [ ] Написал `user_audit.sh` и понимаю каждый его пункт
- [ ] Понимаю, почему `docker`-группа = root
