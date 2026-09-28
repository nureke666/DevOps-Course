---
title: "08. Packages"
description: "Пакеты и репозитории: apt, dpkg, tar/gzip, зависимости, сборка из исходников"
---

# 08. Packages — пакеты и репозитории

> Источник: `08_packages.txt` (Grasshopper, 7 уроков)
> **После темы ты умеешь:** ставить и удалять софт, чинить зависимости, работать с `apt` и `dnf`,
> распаковывать архивы и собирать программы из исходников.

---

## 🗺️ Схема: как софт попадает на сервер

```text:no-line-numbers
   Исходный код (GitHub)
          │  сборка (make / go build / cargo)
          ▼
   Бинарник + конфиги + docs + метаданные
          │  упаковка
          ▼
   ┌────────────┐         ┌────────────┐
   │  .deb      │         │  .rpm      │       ← ПАКЕТ = архив + метаданные
   └─────┬──────┘         └─────┬──────┘          (зависимости, скрипты, файлы)
         │                      │
         ▼                      ▼
   ┌────────────────────────────────────┐
   │        РЕПОЗИТОРИЙ (сервер)        │      ← индекс пакетов + подписи GPG
   └─────────────────┬──────────────────┘
                     │  apt update  (скачать индекс)
                     ▼
   ┌────────────────────────────────────┐
   │  apt / dnf  — высокий уровень      │      разрешает ЗАВИСИМОСТИ
   │       ↓                            │
   │  dpkg / rpm — низкий уровень       │      ставит ОДИН пакет
   └─────────────────┬──────────────────┘
                     ▼
        Файлы в /usr/bin, /etc, /var, /usr/share
```

---

## 1. Software Distribution — способы доставки софта

| Способ | Плюсы | Минусы | Когда |
|--------|-------|--------|-------|
| **Пакеты из репозитория** (`apt install`) | зависимости, обновления, подпись, удаление | версия может быть старой | 90% случаев |
| **Сторонний репозиторий / PPA** | свежие версии от вендора | доверие к источнику | Docker, Postgres, Grafana |
| **.deb/.rpm файл вручную** | точный контроль версии | зависимости вручную | вендорский софт |
| **Исходники** (`make install`) | любая версия, свои флаги | нет удаления/обновления | редкие/патченные случаи |
| **Бинарник из релизов** (tar.gz) | просто, быстро | обновлять руками | Go-утилиты: terraform, kubectl |
| **Snap / Flatpak / AppImage** | изолированность, свежесть | размер, медленный старт | десктоп |
| **Контейнер** (`docker run`) | изоляция, воспроизводимость | оверхед, нужен рантайм | современный дефолт для сервисов |
| **Языковые менеджеры** (pip, npm, go install) | экосистема языка | конфликты с системными пакетами | dev-инструменты (в venv!) |

⚠️ **Правило:** не смешивай системные пакеты и `pip install` глобально — сломаешь системный Python.
Используй `venv`, `pipx`, или ставь `python3-<пакет>` из репозитория.

---

## 2. Package Repositories — репозитории

Репозиторий = набор пакетов + индексные файлы + GPG-подписи.

### Debian/Ubuntu

```bash
cat /etc/apt/sources.list
ls /etc/apt/sources.list.d/          # сторонние репозитории — каждый отдельным файлом
```

Формат строки:
```text:no-line-numbers
deb http://archive.ubuntu.com/ubuntu jammy main restricted universe multiverse
│              │                       │                 │
│              │                       │                 └─ компоненты
│              │                       └─ кодовое имя релиза (jammy = 22.04)
│              └─ URL зеркала
└─ deb = бинарные пакеты (deb-src = исходники)
```

Компоненты Ubuntu:

| Компонент | Что |
|-----------|-----|
| `main` | Свободное ПО, поддерживается Canonical |
| `restricted` | Проприетарные драйверы, поддерживается Canonical |
| `universe` | Свободное ПО от сообщества |
| `multiverse` | Несвободное ПО, без поддержки |

Карманы (pockets): `jammy`, `jammy-updates`, `jammy-security`, `jammy-backports`.

```bash
sudo apt update                    # ОБНОВИТЬ ИНДЕКС (не пакеты!)
sudo add-apt-repository universe
sudo add-apt-repository ppa:deadsnakes/ppa    # PPA (личный репозиторий Launchpad)
apt policy nginx                   # откуда будет поставлен пакет и какие версии доступны
```

**Современный способ добавить вендорский репозиторий** (ключи в `apt-key` устарели):
```bash
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/docker.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu jammy stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update
```

### RHEL/Fedora

```bash
ls /etc/yum.repos.d/
dnf repolist
sudo dnf config-manager --add-repo https://.../repo.repo
```

🔐 **Безопасность:** каждый пакет подписан GPG-ключом репозитория. Если добавляешь чужой репозиторий —
ты доверяешь ему уровень root. Не добавляй случайные PPA на прод.

---

## 3. tar и gzip — архивы

`tar` **не сжимает**, он склеивает файлы в один (tape archive). Сжатие добавляет gzip/bzip2/xz.

```bash
# Создать
tar -cvf archive.tar dir/              # без сжатия
tar -czvf archive.tar.gz dir/          # + gzip (быстро)      ← самое частое
tar -cjvf archive.tar.bz2 dir/         # + bzip2 (компактнее)
tar -cJvf archive.tar.xz dir/          # + xz (максимум сжатия, медленно)

# Распаковать
tar -xzvf archive.tar.gz               # в текущий каталог
tar -xzvf archive.tar.gz -C /opt/      # в указанный каталог
tar -xzvf archive.tar.gz path/inside   # только один файл из архива

# Посмотреть, НЕ распаковывая  ← ВСЕГДА делай это первым
tar -tzvf archive.tar.gz | head

# Исключить
tar -czvf backup.tar.gz --exclude='*.log' --exclude='node_modules' /opt/app
```

Мнемоника флагов: **c**reate, e**x**tract, lis**t**, **v**erbose, **f**ile, **z**=gzip, **j**=bzip2, **J**=xz.
Современный `tar` определяет тип сжатия сам: `tar -xvf file.tar.gz` тоже сработает.

```bash
gzip file.txt            # → file.txt.gz (оригинал удаляется!)
gunzip file.txt.gz
gzip -k file.txt         # сохранить оригинал
zcat file.gz             # посмотреть без распаковки
zgrep "error" log.gz     # ГРЕПАТЬ сжатый лог ← используешь постоянно
zless archive.log.gz
```

⚠️ **Tar-бомба:** архив, распаковывающийся не в подкаталог, а прямо в текущий (сотни файлов).
Поэтому сначала `tar -tzvf`, а распаковывать — в отдельный каталог с `-C`.

| Формат | Скорость | Сжатие | Применение |
|--------|----------|--------|-----------|
| `.tar.gz` | быстро | среднее | стандарт де-факто |
| `.tar.bz2` | медленно | хорошее | почти вытеснен |
| `.tar.xz` | очень медленно | отличное | дистрибутивы, релизы |
| `.zst` | очень быстро | хорошее | современный выбор (Arch, Fedora) |

---

## 4. Package Dependencies — зависимости

Пакет объявляет, что ему нужно:

| Тип | Смысл |
|-----|-------|
| **Depends** | Обязательная зависимость |
| **Recommends** | Обычно ставится (можно отключить `--no-install-recommends`) |
| **Suggests** | Полезно, но не ставится |
| **Conflicts** | Несовместим с другим пакетом |
| **Provides** | «Я умею быть таким-то» (виртуальный пакет) |
| **Replaces** | Заменяет другой пакет |

```bash
apt-cache depends nginx           # от чего зависит
apt-cache rdepends nginx          # кто зависит ОТ него
apt show nginx                    # полная карточка пакета
dnf repoquery --requires nginx
```

**Dependency hell** — когда пакет A требует libX v1, а пакет B — libX v2.
Как решают сейчас: контейнеры (у каждого приложения своё окружение), статическая линковка (Go),
Snap/Flatpak, языковые venv.

💡 В Docker `--no-install-recommends` — стандартная практика: образ меньше, CVE меньше.

---

## 5. rpm и dpkg — низкий уровень (один пакет)

```bash
# Debian
sudo dpkg -i package.deb          # установить (зависимости НЕ подтянет!)
sudo dpkg -r package              # удалить (конфиги останутся)
sudo dpkg -P package              # удалить полностью (purge)
dpkg -l                           # список всех установленных
dpkg -l | grep nginx
dpkg -L nginx                     # какие ФАЙЛЫ принёс пакет  ← очень полезно
dpkg -S /usr/sbin/nginx           # какому пакету принадлежит файл ← и это тоже
dpkg -s nginx                     # статус и метаданные
dpkg --get-selections             # для переноса списка пакетов на другую машину

# RHEL
sudo rpm -ivh package.rpm         # install verbose hash
sudo rpm -Uvh package.rpm         # upgrade
sudo rpm -e package               # erase
rpm -qa                           # все установленные
rpm -ql nginx                     # файлы пакета
rpm -qf /usr/sbin/nginx           # чей файл
rpm -qi nginx                     # информация
rpm -V nginx                      # ПРОВЕРКА целостности (изменённые файлы) ← для аудита
```

🔧 Классическая ситуация: `dpkg -i` упал из-за зависимостей →
```bash
sudo apt install -f        # "fix broken" — доустановит недостающее
```

---

## 6. apt и dnf — высокий уровень

```bash
# === ПОИСК И ИНФОРМАЦИЯ ===
apt search nginx
apt show nginx
apt list --installed
apt list --upgradable
apt policy nginx             # версии и приоритеты репозиториев

# === УСТАНОВКА ===
sudo apt update                          # ОБНОВИТЬ ИНДЕКС (делай всегда перед install)
sudo apt install nginx
sudo apt install nginx=1.18.0-0ubuntu1   # конкретная версия
sudo apt install -y --no-install-recommends nginx
sudo apt install ./local.deb             # локальный файл С зависимостями

# === ОБНОВЛЕНИЕ ===
sudo apt upgrade                 # обновить пакеты, НЕ удаляя ничего
sudo apt full-upgrade            # может удалять пакеты ради разрешения зависимостей
sudo apt dist-upgrade            # то же (старое имя)

# === УДАЛЕНИЕ ===
sudo apt remove nginx            # удалить, конфиги оставить
sudo apt purge nginx             # удалить вместе с конфигами
sudo apt autoremove              # убрать осиротевшие зависимости
sudo apt clean                   # очистить кэш скачанных .deb

# === ФИКСАЦИЯ ВЕРСИИ ===
sudo apt-mark hold nginx         # запретить обновление
sudo apt-mark unhold nginx
apt-mark showhold
```

DNF-эквиваленты:

| Задача | apt | dnf |
|--------|-----|-----|
| Обновить индекс | `apt update` | (автоматически) |
| Установить | `apt install X` | `dnf install X` |
| Удалить | `apt remove X` | `dnf remove X` |
| Обновить всё | `apt upgrade` | `dnf upgrade` |
| Поиск | `apt search X` | `dnf search X` |
| Инфо | `apt show X` | `dnf info X` |
| Какому пакету принадлежит файл | `dpkg -S файл` | `dnf provides файл` |
| Файлы пакета | `dpkg -L X` | `rpm -ql X` |
| История | `/var/log/apt/history.log` | `dnf history` |
| Откат | ❌ (вручную) | `dnf history undo N` ✅ |

⚠️ **`apt update` ≠ `apt upgrade`.** Первое обновляет **список** пакетов, второе — сами пакеты.
Классическая ошибка новичка — сделать `apt install` без `update` и получить «404 Not Found».

💡 `apt` — для интерактивной работы, `apt-get` — для **скриптов** (стабильный вывод и флаги).
В Dockerfile всегда `apt-get`:
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
```

**Unattended upgrades** (автоматические security-обновления):
```bash
sudo apt install unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
cat /etc/apt/apt.conf.d/50unattended-upgrades
```

---

## 7. Compile Source Code — сборка из исходников

Классический цикл:

```bash
# 1. Зависимости для сборки
sudo apt install build-essential          # gcc, g++, make, libc-dev
sudo apt build-dep nginx                  # зависимости конкретного пакета

# 2. Скачать и распаковать
wget https://nginx.org/download/nginx-1.24.0.tar.gz
tar -xzvf nginx-1.24.0.tar.gz && cd nginx-1.24.0

# 3. Configure — проверить окружение и сформировать Makefile
./configure --prefix=/usr/local/nginx --with-http_ssl_module
#   --prefix   куда ставить
#   --help     список всех опций

# 4. Собрать
make -j$(nproc)         # -j = параллельно по числу ядер

# 5. Установить
sudo make install

# 6. Удалить (если Makefile поддерживает)
sudo make uninstall
```

🔴 **Проблема `make install`:** пакетный менеджер о нём не знает. Нет обновлений, нет удаления,
нет зависимостей, нет отката. Такой софт «невидим» для аудита и CVE-сканеров.

✅ **Правильные альтернативы:**
- `checkinstall` — собирает `.deb` вместо прямой установки;
- `fpm` — превращает каталог в `.deb`/`.rpm`;
- ставить в `/usr/local` или `/opt` (чтобы не конфликтовать с системой);
- лучше всего — собрать **Docker-образ** и не трогать хост-систему.

**Куда что ставится** (важно понимать при отладке):

| Путь | Что |
|------|-----|
| `/usr/bin`, `/usr/lib` | Файлы из пакетов дистрибутива |
| `/usr/local/bin`, `/usr/local/lib` | Собранное вручную |
| `/opt/<name>` | Сторонние приложения целиком |
| `~/.local/bin` | Пользовательская установка (pip --user) |

---

## 💼 Как это в DevOps

- **Dockerfile**: `apt-get update && apt-get install -y --no-install-recommends … && rm -rf /var/lib/apt/lists/*`
  — одной командой, чтобы не раздувать слои и не кэшировать устаревший индекс.
- **Ansible**: модули `apt`/`dnf`/`package`, `apt_repository`, `apt_key`.
- **Воспроизводимость**: пиннинг версий (`nginx=1.18.0-…`, `apt-mark hold`) — чтобы dev и prod совпадали.
- **Безопасность**: `unattended-upgrades` для security-патчей, `apt list --upgradable` в мониторинге,
  сканеры (Trivy, Grype) читают именно базу пакетов.
- **Инвентаризация**: `dpkg -l` / `rpm -qa` — что реально стоит на сервере.
- **Расследование**: `/var/log/apt/history.log` — «кто и когда что поставил перед инцидентом».

---

## 🧪 Мини-лаба

```bash
vagrant ssh

# 1. Разведка репозиториев
cat /etc/apt/sources.list | grep -v '^#' | grep -v '^$'
ls /etc/apt/sources.list.d/
apt policy

# 2. Индекс и поиск
sudo apt update
apt search '^htop$'
apt show htop
apt policy htop

# 3. Установка и исследование
sudo apt install -y htop tree jq
dpkg -L htop | head -20
dpkg -S $(which htop)
dpkg -s htop | grep -E 'Version|Depends|Installed-Size'

# 4. Зависимости
apt-cache depends jq
apt-cache rdepends --installed jq | head

# 5. Что установлено и что можно обновить
dpkg -l | wc -l
apt list --upgradable

# 6. Архивы
mkdir -p ~/lab08/src && cd ~/lab08
echo "hello" > src/a.txt; echo "world" > src/b.txt; mkdir -p src/logs; echo "log" > src/logs/x.log
tar -czvf backup.tar.gz src/
tar -tzvf backup.tar.gz                 # СНАЧАЛА посмотреть
mkdir -p restore && tar -xzvf backup.tar.gz -C restore/
tar -czvf backup2.tar.gz --exclude='*.log' src/
tar -tzvf backup2.tar.gz
gzip -k src/a.txt && zcat src/a.txt.gz && zgrep hello src/a.txt.gz

# 7. Локальный .deb и починка зависимостей
apt download tree
sudo dpkg -r tree
sudo dpkg -i tree_*.deb
dpkg -l tree

# 8. История и откат
grep -A3 "Start-Date" /var/log/apt/history.log | tail -20
sudo apt-mark hold htop; apt-mark showhold; sudo apt-mark unhold htop

# 9. Уборка
sudo apt autoremove -y && sudo apt clean
```

---

## 📌 Шпаргалка

| Задача | Debian/Ubuntu | RHEL/Fedora |
|--------|---------------|-------------|
| Обновить индекс | `apt update` | (авто) |
| Установить | `apt install X` | `dnf install X` |
| Удалить + конфиги | `apt purge X` | `dnf remove X` |
| Обновить систему | `apt upgrade` | `dnf upgrade` |
| Поиск | `apt search X` | `dnf search X` |
| Информация | `apt show X` | `dnf info X` |
| Список установленных | `dpkg -l` | `rpm -qa` |
| Файлы пакета | `dpkg -L X` | `rpm -ql X` |
| Чей это файл | `dpkg -S /path` | `dnf provides /path` \| `rpm -qf` |
| Поставить локальный файл | `dpkg -i f.deb` + `apt install -f` | `rpm -ivh f.rpm` \| `dnf install ./f.rpm` |
| Зафиксировать версию | `apt-mark hold X` | `dnf versionlock X` |
| Осиротевшие пакеты | `apt autoremove` | `dnf autoremove` |
| История | `/var/log/apt/history.log` | `dnf history` |

**tar:** `czvf` — создать, `xzvf` — распаковать, `tzvf` — **посмотреть** (делай первым), `-C` — куда.

---

## 🧠 Что запомнить

1. `apt update` обновляет **индекс**, `apt upgrade` — **пакеты**. Всегда update перед install.
2. `dpkg`/`rpm` — один пакет без зависимостей; `apt`/`dnf` — с зависимостями из репозитория.
3. `dpkg -S файл` / `dpkg -L пакет` — две команды, которые спасают при отладке «откуда этот файл».
4. `apt install -f` чинит сломанные зависимости после `dpkg -i`.
5. `tar` не сжимает — сжимают gzip/bzip2/xz. Сначала `-tzvf`, потом `-xzvf -C dir`.
6. `zgrep`/`zcat` — работа со сжатыми логами без распаковки.
7. `make install` не отслеживается пакетным менеджером — предпочитай пакеты или контейнеры.
8. Репозиторий = доверие уровня root. Ключи GPG — в `/usr/share/keyrings` + `signed-by`.
9. В Dockerfile: `apt-get`, `-y --no-install-recommends`, и чистка `/var/lib/apt/lists/*`.

---

## Задачи

> `vagrant snapshot save before_08 && vagrant ssh`

### Блок A. Теория

**A1.** Что такое пакет? Чем он отличается от просто архива с бинарником?

<details><summary>Ответ</summary>

Пакет — архив файлов **плюс метаданные**: имя, версия, архитектура, зависимости, конфликты,
контрольные суммы, pre/post-скрипты установки, список конфигов. Благодаря метаданным система знает,
что установлено, умеет обновлять, удалять и проверять целостность. Просто архив ничего этого не даёт.

</details>

**A2.** В чём разница между `apt` и `dpkg`? Почему нужны оба уровня?

<details><summary>Ответ</summary>

`dpkg` — низкоуровневый: ставит/удаляет **один** конкретный `.deb`, ведёт базу установленного,
но не умеет скачивать и разрешать зависимости. `apt` — надстройка: работает с репозиториями, строит
граф зависимостей, скачивает нужное и вызывает `dpkg`. Разделение даёт гибкость: `dpkg` работает офлайн.

</details>

**A3.** `apt update` и `apt upgrade` — что делает каждая? Почему порядок важен?

<details><summary>Ответ</summary>

`apt update` скачивает **индексы** пакетов из репозиториев (какие версии существуют).
`apt upgrade` устанавливает более новые версии уже установленных пакетов. Без `update` система
работает со старым индексом: `404 Not Found` при скачивании или «пакет не найден».

</details>

**A4.** Чем `apt remove` отличается от `apt purge`? Когда нужен второй?

<details><summary>Ответ</summary>

`remove` удаляет файлы программы, но **оставляет конфиги** в `/etc` (чтобы при переустановке
настройки сохранились). `purge` удаляет и конфиги. `purge` нужен, когда хочешь начать с чистого листа
или пакет больше не нужен совсем.

</details>

**A5.** Что такое репозиторий и зачем пакеты подписывают GPG-ключами?

<details><summary>Ответ</summary>

Репозиторий — сервер с пакетами и индексными файлами. GPG-подпись гарантирует, что пакет
пришёл от владельца репозитория и не изменён по пути. Без проверки подписи MITM-атака позволила бы
подсунуть троянизированный пакет, который ставится с правами root.

</details>

**A6.** Что означает строка `deb http://archive.ubuntu.com/ubuntu jammy main restricted`?
Разбери по частям.

<details><summary>Ответ</summary>

`deb` — бинарные пакеты (не исходники); `http://archive.ubuntu.com/ubuntu` — URL репозитория;
`jammy` — кодовое имя релиза (Ubuntu 22.04); `main restricted` — компоненты репозитория.

</details>

**A7.** Чем отличаются компоненты `main`, `universe`, `restricted`, `multiverse` в Ubuntu?

<details><summary>Ответ</summary>

`main` — свободное ПО с поддержкой Canonical; `restricted` — несвободные драйверы с
поддержкой Canonical; `universe` — свободное ПО, поддерживаемое сообществом; `multiverse` —
несвободное ПО без поддержки. Для прода важно: security-обновления гарантированы только для
`main`/`restricted`.

</details>

**A8.** Что такое «dependency hell»? Какими современными способами эту проблему обходят?

<details><summary>Ответ</summary>

Конфликт версий библиотек: разным приложениям нужны разные несовместимые версии одной
зависимости. Обходят: контейнеризацией (изолированное окружение на приложение), статической
линковкой (Go, Rust), виртуальными окружениями (venv, nvm), Snap/Flatpak с бандлом зависимостей.

</details>

**A9.** Почему `tar` сам по себе не сжимает файлы? Что такое `.tar.gz` в реальности?

<details><summary>Ответ</summary>

Исторически `tar` (tape archive) создавался для последовательной записи файлов на ленту —
его задача склеить дерево файлов с метаданными в один поток. Сжатие — отдельная задача отдельных
программ (UNIX-философия). `.tar.gz` = tar-поток, пропущенный через gzip.

</details>

**A10.** Почему `make install` считается плохой практикой на продовом сервере? Три альтернативы.

<details><summary>Ответ</summary>

Пакетный менеджер не знает об этих файлах: нет обновлений и security-патчей, нет корректного
удаления, нет проверки зависимостей и целостности, сканеры уязвимостей такой софт не видят.
Альтернативы: `checkinstall`/`fpm` (собрать `.deb`/`.rpm`), установка в `/opt` с собственным
systemd-юнитом и учётом в конфиг-менеджменте, либо Docker-образ.

</details>

**A11.** Зачем в Dockerfile пишут `--no-install-recommends` и `rm -rf /var/lib/apt/lists/*`?

<details><summary>Ответ</summary>

`--no-install-recommends` не тянет «рекомендуемые» пакеты — образ меньше и меньше CVE.
`rm -rf /var/lib/apt/lists/*` удаляет кэш индексов (десятки МБ), который в образе бесполезен.
Обе команды должны быть **в том же слое** `RUN`, иначе данные останутся в предыдущем слое.

</details>

**A12.** Чем `apt` отличается от `apt-get` и какой использовать в скриптах?

<details><summary>Ответ</summary>

`apt` — удобный интерфейс для людей (прогресс-бары, цвета), его вывод и набор флагов
**не гарантированы стабильными** между версиями. `apt-get`/`apt-cache` — стабильный интерфейс для
скриптов. В скриптах и Dockerfile — `apt-get`.

</details>

**A13.** Как зафиксировать версию пакета, чтобы она не обновилась при `apt upgrade`?

<details><summary>Ответ</summary>

`sudo apt-mark hold <пакет>` (снять — `unhold`, посмотреть — `apt-mark showhold`).
В RHEL-семействе — `dnf versionlock`. Дополнительно можно закрепить версию через apt pinning
в `/etc/apt/preferences.d/`.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  apt policy nginx
B2.  dpkg -L nginx | head
B3.  dpkg -S /usr/sbin/nginx
B4.  apt-cache rdepends --installed libssl3
B5.  sudo apt install -f
B6.  apt list --upgradable
B7.  sudo apt-mark hold docker-ce
B8.  tar -tzvf backup.tar.gz
B9.  tar -xzvf app.tar.gz -C /opt/
B10. zgrep -c "ERROR" /var/log/syslog.2.gz
B11. sudo apt autoremove --purge
B12. dpkg --get-selections > packages.list
B13. rpm -V nginx
B14. apt download htop
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Показывает установленную и доступные версии nginx и приоритеты репозиториев-источников.
B2.  Первые файлы, установленные пакетом nginx.
B3.  Имя пакета, которому принадлежит файл /usr/sbin/nginx.
B4.  Установленные пакеты, зависящие от libssl3 — что сломается при её удалении/обновлении.
B5.  Доустанавливает недостающие зависимости и приводит базу dpkg в согласованное состояние.
B6.  Список пакетов, для которых доступны более новые версии.
B7.  Фиксирует текущую версию docker-ce: apt upgrade её не тронет.
B8.  Показывает содержимое архива без распаковки.
B9.  Распаковывает архив в /opt/, а не в текущий каталог.
B10. Считает строки с ERROR прямо в сжатом логе, не распаковывая его на диск.
B11. Удаляет автоматически установленные и больше не нужные пакеты вместе с их конфигами.
B12. Сохраняет список всех пакетов и их состояний — для переноса набора на другой сервер.
B13. Проверяет целостность установленного пакета: какие файлы изменены относительно эталона
     (размер, права, контрольная сумма) — важно при расследовании компрометации.
B14. Скачивает .deb-файл пакета в текущий каталог, ничего не устанавливая.
```

</details>

**B15.** Чем отличаются `tar -czvf`, `tar -xzvf` и `tar -tzvf`? Какую выполнять первой при работе
с незнакомым архивом и почему?

<details><summary>Ответ</summary>

`-c` create — создать, `-x` extract — извлечь, `-t` list — показать содержимое.
Первой всегда `-tzvf`: убедиться, что архив распакуется в подкаталог, а не «взорвётся» сотнями
файлов в текущем каталоге (tar-бомба), и что в нём нет абсолютных путей.

</details>

---

### Блок C. Практика

**C1. Разведка репозиториев.**
- Выведи все активные (не закомментированные) строки репозиториев.
- Покажи, сколько репозиториев подключено дополнительно (в `sources.list.d/`).
- Узнай, из какого репозитория будет установлен `nginx` и какие версии доступны.

<details><summary>Ответ</summary>

```bash
grep -vE '^\s*(#|$)' /etc/apt/sources.list
ls -1 /etc/apt/sources.list.d/ | wc -l
apt policy nginx
```

</details>

**C2. Установка и исследование.** Установи `htop`, `tree`, `jq`, `ncdu`. Затем для `jq` выясни:
- версию;
- какие файлы он принёс в систему;
- от каких пакетов зависит;
- сколько места занимает.

<details><summary>Ответ</summary>

```bash
sudo apt update && sudo apt install -y htop tree jq ncdu
dpkg -s jq | grep -E '^(Version|Depends|Installed-Size)'
dpkg -L jq
apt-cache depends jq
```

</details>

**C3. Обратный поиск.** Ответь командами:
- какому пакету принадлежит файл `/usr/bin/awk`?
- какому пакету принадлежит `/etc/ssh/sshd_config`?
- какие файлы конфигурации принёс пакет `openssh-server`?

<details><summary>Ответ</summary>

```bash
dpkg -S /usr/bin/awk
dpkg -S /etc/ssh/sshd_config
dpkg -L openssh-server | grep '^/etc'
```

</details>

**C4. Локальная установка.** Скачай `.deb` пакета `tree` (без установки), удали установленный `tree`,
поставь из скачанного файла через `dpkg`, убедись, что работает. Затем покажи, что делать,
если `dpkg -i` упал из-за зависимостей.

<details><summary>Ответ</summary>

```bash
apt download tree
sudo apt remove -y tree
sudo dpkg -i tree_*.deb
tree --version
# если упало по зависимостям:
sudo apt install -f          # доустановит недостающее и завершит настройку
```

</details>

**C5. Архивы.** Создай структуру:
```text:no-line-numbers
~/lab08/app/
├── bin/run.sh
├── conf/app.conf
├── logs/app.log
└── data/big.bin   (10 МБ, создать через dd)
```
Затем:
1. Заархивируй всё с gzip, замерь размер.
2. Заархивируй без `logs/` и без `*.bin`, сравни размеры.
3. Посмотри содержимое архива без распаковки.
4. Распакуй **только** `conf/app.conf` в `/tmp/restore/`.
5. Сравни степень сжатия gzip / bzip2 / xz на одном и том же каталоге (размер + время через `time`).

<details><summary>Ответ</summary>

```bash
mkdir -p ~/lab08/app/{bin,conf,logs,data} && cd ~/lab08
echo 'echo run' > app/bin/run.sh; echo 'key=value' > app/conf/app.conf
echo 'ERROR something' > app/logs/app.log
dd if=/dev/urandom of=app/data/big.bin bs=1M count=10 status=none

tar -czf full.tar.gz app/ && du -h full.tar.gz
tar -czf slim.tar.gz --exclude='logs' --exclude='*.bin' app/ && du -h slim.tar.gz
tar -tzvf full.tar.gz
mkdir -p /tmp/restore && tar -xzf full.tar.gz -C /tmp/restore app/conf/app.conf
find /tmp/restore -type f

time tar -czf t.gz  app/ ; du -h t.gz
time tar -cjf t.bz2 app/ ; du -h t.bz2
time tar -cJf t.xz  app/ ; du -h t.xz
```
(На случайных данных сжатие почти не работает — это тоже полезный вывод: бэкапить уже сжатые
данные архиватором бессмысленно.)

</details>

**C6. Работа со сжатыми логами.** Сожми `app.log`, затем:
- посчитай количество строк со словом ERROR, не распаковывая;
- выведи последние 5 строк сжатого файла;
- найди строки с контекстом ±2 в сжатом файле.

<details><summary>Ответ</summary>

```bash
gzip -k app/logs/app.log
zgrep -c ERROR app/logs/app.log.gz
zcat app/logs/app.log.gz | tail -5
zgrep -C2 ERROR app/logs/app.log.gz
```

</details>

**C7. Скрипт-инвентаризация.** Напиши `/vagrant/pkg_report.sh`:
```text:no-line-numbers
=== PACKAGE REPORT ===
Distro: Ubuntu 22.04.3 LTS
Package manager: apt
Installed packages: 623
Upgradable: 12
Security updates: 5
Held packages: none
Manually installed (top 10): ...
Last 5 apt operations: ...
```

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
set -uo pipefail
. /etc/os-release
echo "=== PACKAGE REPORT ==="
echo "Distro: $PRETTY_NAME"
echo "Package manager: apt"
echo "Installed packages: $(dpkg-query -f '.\n' -W | wc -l)"
upg=$(apt list --upgradable 2>/dev/null | grep -c upgradable || true)
echo "Upgradable: $upg"
echo "Security updates: $(apt list --upgradable 2>/dev/null | grep -c -- '-security' || true)"
hold=$(apt-mark showhold); echo "Held packages: ${hold:-none}"
echo "Manually installed (top 10):"; apt-mark showmanual | head -10
echo "Last 5 apt operations:"; grep '^Commandline' /var/log/apt/history.log | tail -5
```

</details>

**C8. Симуляция миграции сервера.** Сними список установленных пакетов в файл, затем покажи команду,
которая на новом сервере восстановит тот же набор (для Debian-семейства).

<details><summary>Ответ</summary>

```bash
dpkg --get-selections > ~/packages.list
# на новом сервере:
sudo dpkg --set-selections < packages.list && sudo apt-get dselect-upgrade
# современнее и надёжнее — Ansible/облачный образ, а не восстановление списка
```

</details>

**C9. Сборка из исходников.** Собери простейшую программу из исходников, чтобы пройти цикл:
```bash
sudo apt install -y build-essential
mkdir -p ~/lab08/hello && cd ~/lab08/hello
```
Напиши `hello.c`, скомпилируй через `gcc`, затем сделай простой `Makefile` с целями
`all`, `install` (в `/usr/local/bin`), `clean` и `uninstall`. Проверь все цели.
Объясни, почему такая установка «невидима» для `dpkg`.

<details><summary>Ответ</summary>

```bash
cat > hello.c <<'EOS'
#include <stdio.h>
int main(void) { printf("hello devops\n"); return 0; }
EOS
gcc -o hello hello.c && ./hello

cat > Makefile <<'EOS'
PREFIX ?= /usr/local
all: hello
hello: hello.c
	gcc -O2 -o hello hello.c
install: hello
	install -m 0755 hello $(PREFIX)/bin/hello
uninstall:
	rm -f $(PREFIX)/bin/hello
clean:
	rm -f hello
EOS
make && sudo make install && hello
dpkg -S /usr/local/bin/hello     # "no path found" — dpkg об этом файле не знает
sudo make uninstall && make clean
```
**Важно:** в Makefile отступы — **табы**, не пробелы, иначе `missing separator`.

</details>

**C10. Добавление вендорского репозитория.** Добавь официальный репозиторий Docker
современным способом (GPG-ключ в `/usr/share/keyrings`, `signed-by` в source-файле),
выполни `apt update` и покажи через `apt policy docker-ce`, что пакет доступен.
Устанавливать не обязательно.

<details><summary>Ответ</summary>

```bash
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release; echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update
apt policy docker-ce
```

</details>

---

### Блок D. Инциденты

**D1.** `sudo apt install nginx` выдаёт:
```text:no-line-numbers
E: Unable to locate package nginx
```
Три причины и как проверить каждую.

<details><summary>Ответ</summary>

(1) Не выполнен `apt update` — индекс пуст/устарел. (2) Пакета нет в подключённых
компонентах (нужен `universe`): `sudo add-apt-repository universe`. (3) Опечатка в имени или пакет
называется иначе в этой версии дистрибутива — проверить `apt search nginx`, `apt-cache search`.
Диагностика: `apt policy nginx`, `grep -r . /etc/apt/sources.list*`.

</details>

**D2.** `apt upgrade` выдаёт:
```text:no-line-numbers
The following packages have been kept back: docker-ce kubelet
```
Что это значит и что делать? Почему нельзя просто `full-upgrade` на проде?

<details><summary>Ответ</summary>

«Kept back» — новая версия требует **установки новых** или **удаления существующих** пакетов,
а `apt upgrade` этого делать не имеет права. Варианты: `apt install <пакет>` точечно (видно, что
именно изменится), либо `apt full-upgrade`. На проде `full-upgrade` опасен тем, что может **удалить**
пакеты ради разрешения зависимостей — сначала смотреть план (`-s`/`--dry-run`), делать на канарейке.

</details>

**D3.** После `dpkg -i app.deb` система в состоянии:
```text:no-line-numbers
dpkg: dependency problems prevent configuration of app
```
и теперь `apt install` любых пакетов тоже падает. Как выйти из положения?

<details><summary>Ответ</summary>

Пакет остался в состоянии «настроен наполовину» и блокирует операции:
```bash
sudo apt install -f                     # чаще всего достаточно
sudo dpkg --configure -a                # завершить настройку всех незаконченных
sudo dpkg -r --force-depends app        # если пакет битый — удалить принудительно
sudo apt update && sudo apt -f install
```
Правильный путь изначально — `sudo apt install ./app.deb`, который сам подтянет зависимости.

</details>

**D4.** На сервере кончилось место. Выяснилось, что `/var/cache/apt/archives` занимает 4 ГБ.
Как безопасно почистить и как не допустить повторения?

<details><summary>Ответ</summary>

```bash
du -sh /var/cache/apt/archives
sudo apt clean                 # удалить все скачанные .deb
sudo apt autoclean             # удалить только устаревшие
sudo apt autoremove --purge    # убрать осиротевшие пакеты
```
Профилактика: `apt clean` в конце provisioning-скриптов и Dockerfile, мониторинг `/var`,
периодический `autoremove`, вынесение `/var` на отдельный раздел.

</details>

**D5.** Приложение требует Python 3.11, на Ubuntu 20.04 есть только 3.8.
Разработчик сделал `sudo apt remove python3` — сервер «сломался», половина утилит не работает.
Что произошло и как надо было?

<details><summary>Ответ</summary>

В Ubuntu от `python3` зависят системные утилиты (`apt` частично, `ubuntu-advantage`,
`netplan`, `unattended-upgrades` и др.), и `apt remove python3` потянул за собой удаление десятков
пакетов. Надо было **не трогать системный Python**, а поставить рядом: PPA `deadsnakes`
(`python3.11` ставится параллельно), `pyenv`, или запускать приложение в контейнере
(`FROM python:3.11-slim`). Восстановление — `apt install` удалённых пакетов из
`/var/log/apt/history.log` или из снапшота/бэкапа.

</details>

**D6.** После обновления сломался сервис. Нужно понять, что именно обновилось за последние сутки,
и откатить конкретный пакет к предыдущей версии.

<details><summary>Ответ</summary>

```bash
grep -B1 -A3 "$(date -d yesterday +%Y-%m-%d)" /var/log/apt/history.log
zgrep -h "Upgrade:" /var/log/apt/history.log* | tail
apt policy <пакет>                            # какие версии доступны
sudo apt install <пакет>=<старая-версия>      # откат
sudo apt-mark hold <пакет>                    # чтобы не обновился обратно
```
В RHEL проще: `dnf history` и `dnf history undo <ID>`.

</details>

**D7.** Security-сканер нашёл уязвимость в `libssl`. Как проверить установленную версию,
понять, какие пакеты от неё зависят, и обновить только её?

<details><summary>Ответ</summary>

```bash
dpkg -s libssl3 | grep Version
apt policy libssl3
apt-cache rdepends --installed libssl3
sudo apt update && sudo apt install --only-upgrade libssl3
sudo systemctl restart nginx postgresql ...    # перезапустить зависящие сервисы
sudo apt install needrestart && sudo needrestart   # покажет, что требует рестарта
```

</details>

---

### Блок E. Вопросы с собеседования

**1.** Чем `apt` отличается от `dpkg`?

<details><summary>Ответ</summary>

`dpkg` ставит один локальный `.deb` без разрешения зависимостей; `apt` работает с репозиториями,
разрешает зависимости и вызывает `dpkg`.

</details>

**2.** Как узнать, какому пакету принадлежит файл?

<details><summary>Ответ</summary>

`dpkg -S /path/to/file` (Debian) или `rpm -qf /path` / `dnf provides /path` (RHEL).

</details>

**3.** Как установить конкретную версию пакета и запретить её обновление?

<details><summary>Ответ</summary>

`apt install nginx=1.18.0-0ubuntu1` затем `apt-mark hold nginx`.

</details>

**4.** Как посмотреть содержимое архива, не распаковывая его?

<details><summary>Ответ</summary>

`tar -tzvf archive.tar.gz` (или `less archive.tar.gz` для быстрого взгляда).

</details>

**5.** Что делать, если `dpkg -i` ругается на зависимости?

<details><summary>Ответ</summary>

`sudo apt install -f` — доустановит зависимости; правильнее сразу `apt install ./file.deb`.

</details>

**6.** Почему `make install` не рекомендуется в проде?

<details><summary>Ответ</summary>

Файлы не учитываются пакетным менеджером: нет обновлений и security-патчей, некорректное удаление,
невидимость для аудита и сканеров уязвимостей, сложность воспроизведения на другом сервере.

</details>

**7.** Как настроить автоматические security-обновления?

<details><summary>Ответ</summary>

`apt install unattended-upgrades` + `dpkg-reconfigure -plow unattended-upgrades`,
настройка в `/etc/apt/apt.conf.d/50unattended-upgrades` (только `-security` origin),
плюс `needrestart` для перезапуска затронутых сервисов.

</details>

**8.** Чем `.tar.gz` отличается от `.tar.xz` и когда что выбирать?

<details><summary>Ответ</summary>

Оба — tar-архивы с разным алгоритмом сжатия: gzip быстрее, xz сжимает заметно сильнее,
но медленнее и требует больше памяти. `.tar.gz` — для частых бэкапов и передачи,
`.tar.xz` — для дистрибутивов и редко обновляемых релизов.

</details>

**9.** Как перенести список установленных пакетов на другой сервер?

<details><summary>Ответ</summary>

`dpkg --get-selections > list` на исходном и `dpkg --set-selections < list && apt-get dselect-upgrade`
на целевом. В реальной работе так не делают — состав сервера описывают в Ansible/образе.

</details>

---

### 🎯 Чек-лист

- [ ] Не путаю `apt update` и `apt upgrade`
- [ ] Знаю `dpkg -L` и `dpkg -S` и применяю при отладке
- [ ] Умею починить сломанные зависимости (`apt install -f`, `dpkg --configure -a`)
- [ ] Всегда смотрю архив через `-tzvf` перед распаковкой
- [ ] Использую `zgrep`/`zcat` для сжатых логов
- [ ] Умею добавить вендорский репозиторий с `signed-by`
- [ ] Понимаю, почему `make install` — не для прода
