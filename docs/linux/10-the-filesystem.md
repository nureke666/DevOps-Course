---
title: "10. Файловая система"
description: "Разделы, монтирование, fstab, inode, ссылки, поиск места на диске — конспект и задачи"
---

# 10. The Filesystem — разделы, монтирование, inode

> Источник: `10_the_filesystem.txt` (Journeyman, 12 уроков)
> **После темы ты умеешь:** размечать диски, создавать ФС, монтировать вручную и через fstab,
> настраивать swap, искать пожирателей места и чинить ФС. Одна из самых «рабочих» тем.

---

## 🗺️ Схема: от диска до файла

```text:no-line-numbers
  ФИЗИЧЕСКИЙ ДИСК  /dev/vda
  ┌──────────────────────────────────────────────────────────────┐
  │ MBR/GPT │  раздел 1   │  раздел 2         │  раздел 3        │
  │ (табл.  │  /dev/vda1  │  /dev/vda2        │  /dev/vda3       │
  │ разделов)│  /boot      │   LVM PV          │  swap            │
  └──────────┴──────┬──────┴─────────┬─────────┴──────────────────┘
                    │                │
             mkfs.ext4         LVM: PV → VG → LV
                    │                │
                    ▼                ▼
          ФАЙЛОВАЯ СИСТЕМА     /dev/mapper/vg0-root
          (superblock, inode-таблица, блоки данных)
                    │
                    │  mount /dev/vda1 /boot
                    ▼
  ЕДИНОЕ ДЕРЕВО КАТАЛОГОВ:
  /
  ├── boot   ← смонтирован /dev/vda1
  ├── home   ← смонтирован /dev/mapper/vg0-home
  ├── var
  └── ...
```

🔑 В Linux **нет дисков C: и D:**. Всё встраивается в **одно дерево** от `/` через монтирование.

---

## 1. Filesystem Hierarchy (FHS)

```text:no-line-numbers
/            корень всего
├── bin      → /usr/bin   основные команды (ls, cp)
├── sbin     → /usr/sbin  административные команды (fdisk, ip)
├── boot     ядро (vmlinuz), initramfs, GRUB
├── dev      файлы устройств
├── etc      ⭐ КОНФИГИ системы (никаких бинарников!)
├── home     домашние каталоги пользователей
├── lib      → /usr/lib   библиотеки и модули ядра
├── media    автомонтирование съёмных носителей
├── mnt      ручное временное монтирование
├── opt      сторонние приложения целиком (/opt/app)
├── proc     ⭐ виртуальная ФС: процессы и ядро
├── root     домашний каталог root (не путать с /)
├── run      runtime-данные: pid-файлы, сокеты (в памяти, чистится при загрузке)
├── srv      данные, отдаваемые сервисами
├── sys      ⭐ виртуальная ФС: устройства и драйверы
├── tmp      временные файлы, чистится (sticky bit, 1777)
├── usr      ⭐ программы и данные ОС
│   ├── bin, sbin, lib, share (docs, иконки), local (собранное вручную)
└── var      ⭐ ИЗМЕНЯЮЩИЕСЯ данные
    ├── log     логи ← сюда смотришь при инцидентах
    ├── lib     состояние приложений (БД, docker)
    ├── cache   кэш
    ├── spool   очереди (cron, mail)
    └── tmp     временные, переживают перезагрузку
```

**Что реально нужно помнить девопсу:**

| Каталог | Зачем |
|---------|-------|
| `/etc` | Все конфиги. Бэкапить обязательно |
| `/var/log` | Логи. **Первое место при инциденте** |
| `/var/lib` | Данные приложений (`/var/lib/docker`, `/var/lib/postgresql`) — **растёт** |
| `/opt` | Свои приложения |
| `/usr/local/bin` | Свои скрипты и бинарники |
| `/tmp` vs `/var/tmp` | `/tmp` чистится при перезагрузке, `/var/tmp` — нет |
| `/run` | Сокеты и pid-файлы, живёт в RAM (tmpfs) |
| `/proc`, `/sys` | Виртуальные — места на диске не занимают |

💡 `man 7 hier` — официальное описание всей иерархии.

---

## 2. Filesystem Types

| ФС | Где применяется | Особенности |
|----|-----------------|-------------|
| **ext4** | дефолт в Ubuntu/Debian | Надёжна, журналируемая, проверена временем |
| **XFS** | дефолт в RHEL | Отлично на больших файлах и параллельной записи; **нельзя уменьшить** |
| **Btrfs** | SUSE, Fedora | Снапшоты, сжатие, RAID «из коробки» |
| **ZFS** | хранилища, FreeBSD | Снапшоты, контроль целостности, требует много RAM |
| **tmpfs** | `/run`, `/dev/shm` | В **оперативной памяти**, исчезает при перезагрузке |
| **vfat/exFAT** | флешки, EFI-раздел | Совместимость с Windows, нет прав UNIX |
| **NTFS** | диски Windows | Через `ntfs-3g` |
| **overlayfs** | Docker | Слои образов контейнеров |
| **NFS / CIFS** | сеть | Сетевые ФС ([тема 16](/linux/16-network-sharing)) |

**Журналирование (journaling)** — перед записью данных ФС пишет намерение в журнал.
При сбое питания система по журналу быстро приводит ФС в согласованное состояние вместо
многочасовой проверки всего диска.

```bash
df -T                      # какие ФС смонтированы и какого типа
mount | column -t | head
cat /proc/filesystems      # какие типы поддерживает ядро
lsblk -f
```

---

## 3. Anatomy of a Disk

```text:no-line-numbers
 ДИСК
 ┌────────────────────────────────────────────────────────┐
 │ Сектор 0: MBR или GPT — таблица разделов               │
 ├────────────────────────────────────────────────────────┤
 │ Раздел 1 ─ файловая система                            │
 │   ┌──────────────────────────────────────────────────┐ │
 │   │ SUPERBLOCK  — метаданные ФС (размер, тип, счётчики)│
 │   ├──────────────────────────────────────────────────┤ │
 │   │ INODE TABLE — метаданные каждого файла            │ │
 │   ├──────────────────────────────────────────────────┤ │
 │   │ DATA BLOCKS — сами данные                         │ │
 │   └──────────────────────────────────────────────────┘ │
 ├────────────────────────────────────────────────────────┤
 │ Раздел 2 …                                              │
 └────────────────────────────────────────────────────────┘
```

**MBR vs GPT** — обязательно знать разницу:

| | MBR (устаревший) | GPT (современный) |
|---|---|---|
| Максимальный диск | 2 ТБ | 9.4 ЗБ (практически без ограничений) |
| Разделов | 4 первичных (или 3 + extended) | 128 |
| Копия таблицы | нет | **есть** (в конце диска) |
| Контрольные суммы | нет | есть (CRC32) |
| Загрузка | BIOS | UEFI (и BIOS через BIOS boot partition) |

Правило: **новые системы — только GPT**.

---

## 4. Disk Partitioning

```bash
lsblk                        # что есть
sudo fdisk -l                # подробно
sudo parted -l

# Интерактивная разметка
sudo fdisk /dev/vdb          # для MBR и GPT (современный fdisk умеет оба)
#   n  новый раздел      p  вывести таблицу
#   d  удалить           t  сменить тип
#   w  ЗАПИСАТЬ и выйти  q  выйти БЕЗ записи ← безопасный выход

sudo gdisk /dev/vdb          # только GPT
sudo parted /dev/vdb         # скриптуемый вариант

# Неинтерактивно (для автоматизации)
sudo parted -s /dev/vdb mklabel gpt
sudo parted -s /dev/vdb mkpart primary ext4 1MiB 100%
sudo partprobe /dev/vdb      # сообщить ядру о новой таблице
```

⚠️ Разметка **уничтожает** данные. Перед изменением: бэкап, `lsblk` для проверки устройства,
и убедиться, что раздел размонтирован.

**LVM** (упомянуть обязательно — в проде встречается постоянно):
```text:no-line-numbers
Физические диски (PV) → Группа томов (VG) → Логические тома (LV) → файловая система
```
Преимущество: LV можно **расширить на лету**, добавив диск в VG. Именно поэтому в облаке и на
серверах почти всегда LVM.
```bash
sudo pvcreate /dev/vdb && sudo vgextend vg0 /dev/vdb
sudo lvextend -l +100%FREE /dev/vg0/root
sudo resize2fs /dev/vg0/root          # ext4 (для XFS: xfs_growfs /)
```

---

## 5. Creating Filesystems

```bash
sudo mkfs.ext4 /dev/vdb1
sudo mkfs.ext4 -L DATA /dev/vdb1          # с меткой
sudo mkfs.xfs /dev/vdb1
sudo mkfs.vfat -F32 /dev/vdb1
sudo mkswap /dev/vdb2                      # раздел подкачки

# Настройка параметров ext4
sudo tune2fs -l /dev/vdb1                  # посмотреть все параметры
sudo tune2fs -L NEWLABEL /dev/vdb1         # сменить метку
sudo tune2fs -m 1 /dev/vdb1                # зарезервировать для root 1% вместо 5%
```

💡 `tune2fs -m 1` на больших дисках с данными экономит десятки гигабайт: по умолчанию ext4
резервирует **5%** места «для root», что на диске 2 ТБ — 100 ГБ впустую.

---

## 6. mount и umount

```bash
mount                                  # что смонтировано (длинно)
findmnt                                # ← красивое дерево, читается намного лучше
findmnt /var
df -hT                                 # + свободное место

sudo mount /dev/vdb1 /mnt/data         # смонтировать
sudo mount -t ext4 /dev/vdb1 /mnt/data # явный тип
sudo mount -o ro /dev/vdb1 /mnt/data   # только чтение
sudo mount UUID=abc-123 /mnt/data      # по UUID
sudo mount -a                          # смонтировать всё из fstab ← проверка перед ребутом
sudo mount -o remount,rw /             # перемонтировать (например, в rescue-режиме)

sudo umount /mnt/data
sudo umount -l /mnt/data               # lazy: отцепить, когда освободится
```

Опции монтирования, которые надо знать:

| Опция | Смысл |
|-------|-------|
| `defaults` | rw,suid,dev,exec,auto,nouser,async |
| `ro` / `rw` | только чтение / чтение-запись |
| `noexec` | запретить запуск бинарников ← для `/tmp`, `/var` |
| `nosuid` | игнорировать SUID-биты ← безопасность |
| `nodev` | игнорировать файлы устройств |
| `noatime` | не обновлять время доступа → **ускоряет I/O** |
| `nofail` | не ронять загрузку, если устройства нет ← важно! |
| `_netdev` | сетевая ФС, монтировать после поднятия сети |
| `discard` | TRIM для SSD |

**«Device is busy» при umount** — классика:
```bash
sudo lsof +D /mnt/data          # кто держит файлы
sudo fuser -vm /mnt/data        # какие процессы
sudo fuser -km /mnt/data        # убить их (осторожно!)
sudo umount -l /mnt/data        # или lazy-отмонтирование
```
Частая причина — ты сам стоишь в этом каталоге (`cd /` решает проблему).

---

## 7. /etc/fstab — автомонтирование

```text:no-line-numbers
UUID=abc-123-def  /data  ext4  defaults,noatime  0  2
      │             │     │         │            │  │
      │             │     │         │            │  └─ 6: порядок fsck (0 не проверять, 1 корень, 2 остальные)
      │             │     │         │            └──── 5: dump (почти всегда 0)
      │             │     │         └───────────────── 4: опции монтирования
      │             │     └─────────────────────────── 3: тип ФС
      │             └───────────────────────────────── 2: точка монтирования
      └─────────────────────────────────────────────── 1: устройство (UUID!)
```

```bash
sudo blkid                                     # взять UUID
echo "UUID=$(sudo blkid -s UUID -o value /dev/vdb1) /data ext4 defaults,nofail 0 2" | sudo tee -a /etc/fstab
sudo mount -a                                  # ⚠️ ОБЯЗАТЕЛЬНО проверить ДО перезагрузки
findmnt /data
sudo systemctl daemon-reload                   # systemd генерирует юниты из fstab
```

🔴 **Ошибка в fstab = сервер не загрузится** (уйдёт в emergency mode). Поэтому:
1. Только **UUID**, не `/dev/sdX`.
2. Для некритичных ФС — **`nofail`** (и `x-systemd.device-timeout=10`).
3. **Всегда** `sudo mount -a` до перезагрузки.
4. Для сетевых ФС — `_netdev`.

---

## 8. Swap — подкачка

Swap — место на диске, куда ядро вытесняет редко используемые страницы памяти.

```bash
free -h
swapon --show
cat /proc/swaps

# Swap-ФАЙЛ (гибче раздела, можно менять размер)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile          # обязательно!
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

sudo swapoff /swapfile            # отключить
```

**Swappiness** — насколько охотно ядро вытесняет страницы (0-100, дефолт 60):
```bash
cat /proc/sys/vm/swappiness
sudo sysctl -w vm.swappiness=10          # для серверов БД обычно 1-10
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.d/99-swap.conf
```

⚠️ Swap **не заменяет RAM**: если система активно свопит — это диагноз «мало памяти»,
приложение будет тормозить в десятки раз. В Kubernetes swap исторически **отключают**
(kubelet требовал `--fail-swap-on`; поддержка swap появляется, но по умолчанию выключена).

---

## 9. Disk Usage — кто съел место

```bash
df -h                        # свободное место по ФС
df -hT                       # + тип ФС
df -i                        # ⭐ INODES — вторая причина «нет места»
df -h /var/log               # по конкретному пути

du -sh /var/log              # размер каталога
du -h --max-depth=1 /var | sort -rh | head -10     # ⭐ главная команда поиска
du -xh --max-depth=1 / | sort -rh | head           # -x = не уходить на другие ФС
ncdu /var                    # интерактивно (sudo apt install ncdu) ← удобнее всего

find / -xdev -type f -size +500M -printf '%s %p\n' 2>/dev/null | sort -rn | head
lsof +L1                     # удалённые, но открытые файлы ← место не освобождено
```

**Алгоритм «диск заполнен»:**
```text:no-line-numbers
1. df -h          → какая ФС заполнена
2. df -i          → не inode ли кончились
3. du -xh --max-depth=1 <точка монтирования> | sort -rh | head
4. спускаться вглубь по самому толстому каталогу
5. lsof +L1       → удалённые открытые файлы (нужен рестарт сервиса/truncate)
6. типовые виновники: /var/log, /var/lib/docker, /var/cache/apt, старые ядра, core dumps
```

```bash
# Быстрые победы
sudo journalctl --vacuum-size=200M
sudo apt clean && sudo apt autoremove --purge
docker system prune -a --volumes          # ⚠️ удалит неиспользуемые образы и тома
sudo truncate -s 0 /var/log/huge.log      # НЕ rm, если файл открыт процессом
```

---

## 10. Filesystem Repair

```bash
sudo umount /dev/vdb1            # ФС должна быть РАЗМОНТИРОВАНА!
sudo fsck /dev/vdb1
sudo fsck -y /dev/vdb1           # отвечать "yes" на все вопросы
sudo e2fsck -f /dev/vdb1         # принудительная проверка ext4
sudo xfs_repair /dev/vdb1        # для XFS (xfs_check устарел)

# Проверить корневую ФС при следующей загрузке
sudo touch /forcefsck
# или добавить fsck.mode=force в параметры ядра GRUB
```

🔴 **Никогда не запускай `fsck` на смонтированной ФС** — это гарантированное повреждение данных.
Для корня — загрузка в single-user/rescue или с live-образа.

Признаки проблем: `dmesg` с `EXT4-fs error`, ФС внезапно перешла в read-only, I/O errors.
Помни: `fsck` чинит **метаданные**, а не битые диски. Если диск умирает — сначала `ddrescue` образа.

---

## 11. Inodes — ключевая концепция

**Inode** — структура с метаданными файла. Имя файла в inode **не хранится**!

```text:no-line-numbers
 КАТАЛОГ (это тоже файл!)              INODE #12345              БЛОКИ ДАННЫХ
 ┌───────────────────┐              ┌──────────────────┐        ┌──────────┐
 │ "report.txt" → 12345│───────────▶│ права: 644       │───────▶│ содержимое│
 │ "backup.txt" → 12345│───────────▶│ владелец: nurik  │        │  файла    │
 │ "photo.jpg"  → 67890│            │ размер: 2048     │        └──────────┘
 └───────────────────┘              │ времена: a/m/c   │
                                    │ ссылок: 2        │
                                    │ указатели на блоки│
                                    └──────────────────┘
```

```bash
ls -i file.txt              # номер inode
stat file.txt               # всё содержимое inode
df -i                       # использование inode по ФС
find /var -xdev -printf '%h\n' | sort | uniq -c | sort -rn | head   # где много мелких файлов
```

**Что из этого следует (важные практические выводы):**
1. **Место кончилось, а `df -h` показывает свободное** → кончились inode (`df -i`).
   Типично: миллионы мелких файлов сессий/кэша.
2. Количество inode фиксируется **при создании ФС** и не меняется.
3. Файл реально удаляется, когда **и** число жёстких ссылок = 0, **и** ни один процесс его не открыл.
4. Переименование файла (`mv` в пределах ФС) не трогает данные — меняется только запись в каталоге.

---

## 12. Symlinks и hard links

```bash
ln -s /path/to/target linkname      # СИМВОЛИЧЕСКАЯ ссылка (symlink)
ln /path/to/target linkname         # ЖЁСТКАЯ ссылка (hard link)

ls -l                               # symlink показан как link -> target
readlink -f symlink                 # куда реально ведёт
```

| | Symlink (`ln -s`) | Hard link (`ln`) |
|---|---|---|
| Что хранит | **путь** к цели | ещё одно имя того же **inode** |
| Между ФС | ✅ можно | ❌ только в пределах одной ФС |
| На каталог | ✅ можно | ❌ нельзя |
| При удалении оригинала | ломается («битая ссылка») | данные живы, пока есть ссылки |
| Свой inode | да, отдельный | нет, тот же |
| Виден размер | длина пути | размер файла |

```bash
# Наглядный эксперимент
echo "data" > original.txt
ln    original.txt hard.txt
ln -s original.txt soft.txt
ls -li                       # у original и hard ОДИН inode и счётчик 2
rm original.txt
cat hard.txt                 # работает — данные живы
cat soft.txt                 # No such file or directory — ссылка битая
find . -xtype l              # найти все битые симлинки
```

💼 Где встречается в работе: `/etc/nginx/sites-enabled/site → ../sites-available/site`,
переключение версий (`/opt/app/current → /opt/app/releases/2026-09-13`) — это **основа
zero-downtime деплоя**: атомарно переключаешь симлинк.

---

## 💼 Как это в DevOps

- Подключил облачный диск → `lsblk` → `parted` → `mkfs` → `fstab` (UUID + `nofail`) → `mount -a`.
- `/var` на отдельном разделе: логи не смогут положить весь сервер.
- Мониторинг **обязан** следить за `df -h` **и** `df -i`.
- `/var/lib/docker` — главный пожиратель места; `docker system prune` в регламенте.
- Симлинк `current → releases/<timestamp>` — стандартный паттерн деплоя (Capistrano-style).
- Опции `noexec,nosuid,nodev` на `/tmp` — базовый hardening из CIS Benchmark.

---

## 🧪 Мини-лаба

```bash
vagrant ssh

# 1. Разведка
findmnt
df -hT
df -i
lsblk -f
du -xh --max-depth=1 / 2>/dev/null | sort -rh | head

# 2. Полный цикл: диск → раздел → ФС → монтирование (на loop-устройстве)
sudo dd if=/dev/zero of=/root/disk1.img bs=1M count=500 status=progress
sudo losetup -fP /root/disk1.img
LOOP=$(losetup -j /root/disk1.img | cut -d: -f1); echo "$LOOP"

sudo parted -s "$LOOP" mklabel gpt
sudo parted -s "$LOOP" mkpart primary ext4 1MiB 100%
sudo partprobe "$LOOP"; lsblk "$LOOP"

sudo mkfs.ext4 -L LABDATA "${LOOP}p1"
sudo mkdir -p /mnt/labdata
sudo mount "${LOOP}p1" /mnt/labdata
df -hT /mnt/labdata
echo "hello fs" | sudo tee /mnt/labdata/test.txt

# 3. fstab (безопасно — с nofail)
UUID=$(sudo blkid -s UUID -o value "${LOOP}p1"); echo "$UUID"
echo "UUID=$UUID /mnt/labdata ext4 defaults,nofail,noatime 0 2" | sudo tee -a /etc/fstab
sudo umount /mnt/labdata
sudo mount -a && findmnt /mnt/labdata      # ОБЯЗАТЕЛЬНАЯ проверка

# 4. Inodes
df -i /mnt/labdata
sudo bash -c 'for i in $(seq 1 1000); do touch /mnt/labdata/f$i; done'
df -i /mnt/labdata                          # посмотри, как выросло IUsed
sudo rm -f /mnt/labdata/f*

# 5. Ссылки
cd /tmp && echo "original data" > orig.txt
ln orig.txt hard.txt; ln -s orig.txt soft.txt
ls -li orig.txt hard.txt soft.txt
rm orig.txt; cat hard.txt; cat soft.txt      # вторая — ошибка
find /tmp -xtype l 2>/dev/null | head
rm -f hard.txt soft.txt

# 6. Swap-файл
free -h
sudo fallocate -l 512M /swapfile2 && sudo chmod 600 /swapfile2
sudo mkswap /swapfile2 && sudo swapon /swapfile2
swapon --show; free -h
sudo swapoff /swapfile2 && sudo rm -f /swapfile2

# 7. Заполнение диска и поиск виновника
sudo dd if=/dev/zero of=/mnt/labdata/big.bin bs=1M count=400 status=progress
df -h /mnt/labdata
du -xh --max-depth=1 /mnt/labdata | sort -rh
sudo rm /mnt/labdata/big.bin

# 8. Удалённый открытый файл
sudo bash -c 'dd if=/dev/zero of=/mnt/labdata/ghost.bin bs=1M count=200 status=none'
sudo tail -f /mnt/labdata/ghost.bin > /dev/null &
sudo rm /mnt/labdata/ghost.bin
df -h /mnt/labdata            # место НЕ освободилось
sudo lsof +L1 | head
sudo kill %1; df -h /mnt/labdata

# 9. fsck
sudo umount /mnt/labdata
sudo e2fsck -f "${LOOP}p1"

# 10. УБОРКА (обязательно, иначе fstab останется с несуществующим устройством!)
sudo sed -i "\|/mnt/labdata|d" /etc/fstab
grep labdata /etc/fstab || echo "fstab очищен"
sudo losetup -d "$LOOP"
sudo rm -f /root/disk1.img
sudo rmdir /mnt/labdata
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `lsblk -f` / `findmnt` / `df -hT` | Что есть, что смонтировано, сколько места |
| `df -i` | **Inodes** — вторая причина «нет места» |
| `du -xh --max-depth=1 DIR \| sort -rh \| head` | Кто съел место |
| `ncdu /var` | Интерактивный анализ места |
| `lsof +L1` | Удалённые, но открытые файлы |
| `parted -s DEV mklabel gpt` / `mkpart` | Разметка |
| `mkfs.ext4 -L LABEL DEV` | Создать ФС |
| `mount -o ro,noatime DEV DIR` / `umount [-l]` | Монтирование |
| `mount -a` | Проверить fstab **до** перезагрузки |
| `blkid` | UUID для fstab |
| `fallocate -l 2G /swapfile` + `mkswap` + `swapon` | Swap-файл |
| `fsck -y DEV` (только размонтированной!) | Проверка ФС |
| `ls -i` / `stat` | Inode файла |
| `ln -s target link` / `ln target link` | Symlink / hard link |
| `readlink -f` / `find . -xtype l` | Куда ведёт / битые ссылки |

---

## 🧠 Что запомнить

1. Одно дерево от `/`, диски встраиваются через **mount**. Никаких «дисков C:».
2. `/etc` — конфиги, `/var/log` — логи, `/var/lib` — данные приложений, `/tmp` чистится при ребуте.
3. **GPT вместо MBR** для новых дисков.
4. В `/etc/fstab` — **только UUID** + `nofail` + обязательная проверка `mount -a` до перезагрузки.
5. `df -h` **и** `df -i`: место может кончиться по inode при свободных гигабайтах.
6. `du -xh --max-depth=1 | sort -rh | head` — рабочая лошадка поиска места.
7. Удалённый, но открытый файл не освобождает место → `lsof +L1`, `truncate -s 0`, рестарт сервиса.
8. `fsck` **только на размонтированной** ФС.
9. Hard link — то же inode (в пределах одной ФС, не на каталог); symlink — путь, может «сломаться».
10. Симлинк `current → release` — основа атомарного деплоя.

➡️ Дальше: [11. Boot the System](/linux/11-boot-the-system)

---

## Задачи

> 🔴 Тема меняет разделы и fstab. **Обязательно** `vagrant snapshot save before_10`.
> Все упражнения — на **loop-устройствах**, не на системном диске.

---

### Блок A. Теория

**A1.** Почему в Linux нет дисков `C:` и `D:`? Как вместо этого устроен доступ к нескольким дискам?

<details><summary>Ответ</summary>

В UNIX-модели существует единое дерево каталогов с корнем `/`. Любое устройство встраивается
в это дерево операцией **mount** в произвольную точку (`/boot`, `/data`). Это даёт гибкость:
можно перенести `/var` на другой диск, и приложения этого не заметят.

</details>

**A2.** Для чего нужны каталоги `/etc`, `/var/log`, `/var/lib`, `/opt`, `/usr/local/bin`, `/run`?

<details><summary>Ответ</summary>

`/etc` — конфигурационные файлы системы и сервисов; `/var/log` — логи;
`/var/lib` — изменяемое состояние приложений (БД, docker, apt); `/opt` — сторонние приложения
целиком; `/usr/local/bin` — собственные бинарники и скрипты, не из пакетов;
`/run` — runtime-данные (pid-файлы, сокеты) в tmpfs, очищается при загрузке.

</details>

**A3.** Чем `/tmp` отличается от `/var/tmp`?

<details><summary>Ответ</summary>

`/tmp` очищается при перезагрузке (а в systemd — ещё и по времени через
`systemd-tmpfiles`); `/var/tmp` предназначен для временных файлов, которые должны пережить
перезагрузку. Оба обычно `1777` (sticky bit).

</details>

**A4.** Почему `/proc` и `/sys` не занимают места на диске?

<details><summary>Ответ</summary>

Это виртуальные ФС: содержимое генерируется ядром в момент чтения, на диске ничего не лежит.
Поэтому размер файлов там нулевой или условный, а `df` их не учитывает как занятое место.

</details>

**A5.** Что такое журналирование ФС и какую проблему оно решает?

<details><summary>Ответ</summary>

Перед изменением метаданных ФС записывает намерение в журнал. После сбоя питания система
проигрывает журнал и приводит ФС в согласованное состояние за секунды, вместо полной проверки
диска, которая на больших томах занимает часы. Журнал защищает **метаданные** (а при
`data=journal` — и данные).

</details>

**A6.** Чем GPT лучше MBR? Назови 3 отличия.

<details><summary>Ответ</summary>

(1) Поддержка дисков >2 ТБ и до 128 разделов против 4 первичных. (2) Дублирование таблицы
разделов в конце диска + контрольные суммы CRC32 — таблицу можно восстановить. (3) Штатная работа
с UEFI и GUID-идентификаторы разделов вместо номеров.

</details>

**A7.** Что такое суперблок, таблица inode и блоки данных?

<details><summary>Ответ</summary>

Суперблок — метаданные всей ФС (тип, размер, размер блока, число inode, состояние,
указатели на структуры); таблица inode — массив метаданных всех файлов; блоки данных — содержимое
файлов. Резервные копии суперблока хранятся в нескольких местах (`dumpe2fs` покажет их).

</details>

**A8.** Что хранится в inode, а что — нет? Где тогда лежит имя файла?

<details><summary>Ответ</summary>

В inode: тип, права, владелец/группа, размер, времена (atime/mtime/ctime), счётчик жёстких
ссылок, указатели на блоки данных. **Имени файла в inode нет** — имя хранится в каталоге как
запись «имя → номер inode». Поэтому один inode может иметь несколько имён (hard links).

</details>

**A9.** Почему может возникнуть ситуация «`df -h` показывает свободное место, но файл не создаётся»?
Назови две разные причины.

<details><summary>Ответ</summary>

(1) Закончились **inode** (`df -i`) — много мелких файлов. (2) Место занято **удалёнными,
но открытыми** файлами (`lsof +L1`) — оно освободится только при закрытии дескриптора.
Дополнительно: превышена квота пользователя, ФС смонтирована read-only, исчерпан лимит на размер
файла, либо свободное место занято зарезервированными для root 5%.

</details>

**A10.** Разбери строку fstab по всем 6 полям:
```text:no-line-numbers
UUID=abc-123 /data ext4 defaults,noatime,nofail 0 2
```

<details><summary>Ответ</summary>

`UUID=abc-123` — устройство; `/data` — точка монтирования; `ext4` — тип ФС;
`defaults,noatime,nofail` — опции; `0` — dump (не делать резервную копию утилитой dump);
`2` — порядок проверки fsck (1 — корень, 2 — остальные, 0 — не проверять).

</details>

**A11.** Почему в fstab пишут UUID, а не `/dev/sdb1`? Что такое `nofail` и когда он спасает?

<details><summary>Ответ</summary>

Имена `/dev/sdX` зависят от порядка обнаружения устройств и могут меняться, что приводит
к монтированию не того раздела или к невозможности загрузки. UUID привязан к самой ФС.
`nofail` разрешает системе загрузиться, даже если устройства нет — критично для дополнительных
дисков, сетевых ФС и всего, без чего сервер может работать.

</details>

**A12.** Чем hard link отличается от symlink? Приведи по сценарию использования для каждого.

<details><summary>Ответ</summary>

Hard link — дополнительное имя для того же inode: работает только внутри одной ФС, нельзя
на каталог, данные живут, пока есть хоть одно имя (используется, например, в бэкапах с дедупликацией,
`rsync --link-dest`). Symlink — отдельный файл, содержащий путь: работает между ФС и на каталоги,
ломается при удалении цели (используется для `current → release`, `sites-enabled`, переключения версий).

</details>

**A13.** Что произойдёт, если удалить файл, который открыт работающим процессом?

<details><summary>Ответ</summary>

Файл исчезает из каталога, но inode и блоки данных сохраняются, пока открыт хотя бы один
дескриптор. Процесс продолжает нормально читать и писать, место на диске **не освобождается**.
Содержимое доступно через `/proc/<pid>/fd/<n>`.

</details>

**A14.** Зачем нужен swap, если есть RAM? Что такое swappiness и почему в Kubernetes swap отключают?

<details><summary>Ответ</summary>

Swap позволяет вытеснить редко используемые страницы на диск, освободив RAM под активные
данные и страничный кэш, и защищает от мгновенного OOM при всплеске. `vm.swappiness` (0-100)
задаёт «охоту» ядра вытеснять анонимные страницы. В Kubernetes swap отключали, потому что он
ломает предсказуемость лимитов памяти и QoS-классов: под, превышающий лимит, должен быть убит,
а не незаметно деградировать в своп.

</details>

**A15.** Почему `fsck` нельзя запускать на смонтированной файловой системе?

<details><summary>Ответ</summary>

`fsck` работает напрямую с блоками устройства, а ядро в это время держит собственный кэш
метаданных и продолжает писать. Правки fsck и записи ядра конфликтуют → гарантированное
повреждение ФС. Поэтому проверять надо размонтированную ФС, а корень — из rescue/live-режима
или через `/forcefsck` при следующей загрузке.

</details>

---

### Блок B. «Что делает / что покажет»

Слева — команда, справа (сразу под ней) — что она делает.

```bash
B1.  findmnt /var
B2.  df -hT
B3.  df -i
B4.  du -xh --max-depth=1 /var | sort -rh | head
B5.  lsof +L1
B6.  mount -o remount,rw /
B7.  mount -a
B8.  blkid -s UUID -o value /dev/vda1
B9.  tune2fs -m 1 /dev/vdb1
B10. ls -li orig.txt hard.txt
B11. readlink -f /etc/nginx/sites-enabled/default
B12. find /etc -xtype l
B13. fuser -vm /mnt/data
B14. swapon --show
B15. truncate -s 0 /var/log/app.log
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Показывает, какое устройство смонтировано в /var, тип ФС и опции.
B2.  Свободное место с указанием типа каждой ФС.
B3.  Использование inode — второй показатель заполненности.
B4.  Топ каталогов /var по размеру, не пересекая границы ФС (-x).
B5.  Файлы, которые удалены, но ещё открыты процессами (держат место).
B6.  Перемонтирует корень на чтение-запись без размонтирования (спасение в rescue-режиме).
B7.  Монтирует всё из /etc/fstab — обязательная проверка корректности fstab перед ребутом.
B8.  Печатает только UUID раздела — удобно подставлять в скрипты и fstab.
B9.  Уменьшает зарезервированное для root место до 1% — на больших дисках возвращает десятки ГБ.
B10. Показывает номера inode: у оригинала и hard link они одинаковые, счётчик ссылок = 2.
B11. Разворачивает симлинк до конечного абсолютного пути.
B12. Находит «битые» симлинки (ведущие в никуда) в /etc.
B13. Показывает процессы, использующие смонтированную ФС, — почему не отмонтируется.
B14. Активные области подкачки, их тип, размер и использование.
B15. Обнуляет лог, СОХРАНЯЯ дескриптор: место освобождается сразу, а пишущий процесс
     продолжает работать (в отличие от rm).
```

</details>

**B16.** В чём разница между `du -sh /var` и `df -h /var`? Почему их значения могут не совпадать?

<details><summary>Ответ</summary>

`du` считает суммарный размер файлов в каталоге, `df` — занятость **файловой системы**.
Расхождения: удалённые открытые файлы (df больше), sparse-файлы и hard links (du может считать
иначе), зарезервированные для root блоки, разные ФС внутри одного пути, права доступа
(du без sudo не видит часть файлов).

</details>

---

### Блок C. Практика

#### C1. Полный цикл работы с диском (главное упражнение темы)

На loop-устройстве пройди путь целиком:
1. Создай файл-образ 600 МБ.
2. Подключи как loop-устройство.
3. Создай GPT-таблицу и **два** раздела: 400 МБ и остаток.
4. На первом — ext4 с меткой `DATA01`, на втором — swap.
5. Смонтируй первый раздел в `/mnt/data01`, включи swap со второго.
6. Проверь: `lsblk -f`, `df -hT`, `swapon --show`, `free -h`.
7. Пропиши оба в `/etc/fstab` **по UUID** с `nofail`.
8. Проверь fstab, **не перезагружаясь**.
9. Убери всё за собой (включая строки в fstab!).

*Критерий приёмки:* после шага 8 `findmnt /mnt/data01` показывает точку монтирования,
а `mount -a` отрабатывает без ошибок.

<details><summary>Ответ</summary>

```bash
sudo dd if=/dev/zero of=/root/lab10.img bs=1M count=600 status=progress
sudo losetup -fP /root/lab10.img
L=$(losetup -j /root/lab10.img | cut -d: -f1); echo "$L"

sudo parted -s "$L" mklabel gpt
sudo parted -s "$L" mkpart primary ext4 1MiB 400MiB
sudo parted -s "$L" mkpart primary linux-swap 400MiB 100%
sudo partprobe "$L"; lsblk "$L"

sudo mkfs.ext4 -L DATA01 "${L}p1"
sudo mkswap "${L}p2"

sudo mkdir -p /mnt/data01
sudo mount "${L}p1" /mnt/data01
sudo swapon "${L}p2"
lsblk -f "$L"; df -hT /mnt/data01; swapon --show; free -h

U1=$(sudo blkid -s UUID -o value "${L}p1")
U2=$(sudo blkid -s UUID -o value "${L}p2")
echo "UUID=$U1 /mnt/data01 ext4 defaults,nofail,noatime 0 2" | sudo tee -a /etc/fstab
echo "UUID=$U2 none swap sw,nofail 0 0" | sudo tee -a /etc/fstab

sudo umount /mnt/data01 && sudo swapoff "${L}p2"
sudo mount -a && sudo swapon -a
findmnt /mnt/data01 && swapon --show

# уборка
sudo umount /mnt/data01; sudo swapoff "${L}p2"
sudo sed -i "\|$U1|d; \|$U2|d" /etc/fstab
sudo losetup -d "$L"; sudo rm -f /root/lab10.img; sudo rmdir /mnt/data01
```

</details>

#### C2. Опции монтирования

Смонтируй раздел с `ro` — попробуй создать файл (ожидаемая ошибка).
Перемонтируй в `rw` без размонтирования. Затем смонтируй с `noexec` и убедись, что скрипт
внутри не запускается, хотя у него есть бит `x`.

<details><summary>Ответ</summary>

```bash
sudo mount -o ro "${L}p1" /mnt/data01
sudo touch /mnt/data01/x            # Read-only file system
sudo mount -o remount,rw /mnt/data01
sudo touch /mnt/data01/x            # теперь работает
printf '#!/bin/bash\necho hi\n' | sudo tee /mnt/data01/s.sh >/dev/null
sudo chmod +x /mnt/data01/s.sh
sudo mount -o remount,noexec /mnt/data01
/mnt/data01/s.sh                     # Permission denied, хотя x стоит
```

</details>

#### C3. Inodes

На своём тестовом разделе:
- посмотри общее число inode и сколько свободно;
- создай 5000 пустых файлов, посмотри, как изменились `df -h` и `df -i`;
- объясни разницу в поведении двух показателей;
- удали файлы.

<details><summary>Ответ</summary>

```bash
df -i /mnt/data01
sudo bash -c 'for i in $(seq 1 5000); do : > /mnt/data01/f$i; done'
df -h /mnt/data01; df -i /mnt/data01
sudo rm -f /mnt/data01/f*
```

`df -h` почти не изменится (пустые файлы не занимают блоков данных), а `IUse%` в `df -i`
вырастет заметно — это и есть механизм «кончились inode при свободном месте».

</details>

#### C4. Заполни диск до конца

На тестовом разделе создай файл, занимающий всё место.
Посмотри, что покажет `df -h`. Попробуй создать ещё файл. Затем освободи место.
Обрати внимание на зарезервированные 5% для root — проверь через `tune2fs -l`.

<details><summary>Ответ</summary>

```bash
sudo dd if=/dev/zero of=/mnt/data01/fill.bin bs=1M count=1000 status=progress   # упрётся
df -h /mnt/data01
sudo touch /mnt/data01/another           # No space left on device
sudo tune2fs -l "${L}p1" | grep -i reserved
sudo rm /mnt/data01/fill.bin
```

</details>

#### C5. Удалённый открытый файл

Воспроизведи ситуацию: большой файл удалён, но место не вернулось.
Найди виновника через `lsof +L1`, покажи **два** способа освободить место
(без перезагрузки сервера).

<details><summary>Ответ</summary>

```bash
sudo dd if=/dev/zero of=/mnt/data01/ghost.bin bs=1M count=200 status=none
sudo tail -f /mnt/data01/ghost.bin >/dev/null &
sudo rm /mnt/data01/ghost.bin
df -h /mnt/data01                # место не вернулось
sudo lsof +L1 | grep ghost
# Способ 1: обнулить через /proc
sudo truncate -s 0 /proc/$(pgrep -f 'tail -f /mnt/data01')/fd/3 2>/dev/null
# Способ 2: завершить держащий процесс
sudo kill %1
df -h /mnt/data01
```

(Для реального сервиса вместо `kill` используют `systemctl reload`/`restart` или
`truncate -s 0 /var/log/app.log` **до** удаления, а в logrotate — `copytruncate`.)

</details>

#### C6. Ссылки

Проведи эксперимент:
- создай файл, на него hard link и symlink;
- покажи inode всех трёх и счётчик ссылок;
- удали оригинал; проверь, что работает, а что нет;
- найди битые симлинки в каталоге;
- попробуй создать hard link на каталог и на файл в другой ФС — объясни ошибки.

<details><summary>Ответ</summary>

```bash
cd /tmp && echo "data" > orig.txt
ln orig.txt hard.txt; ln -s orig.txt soft.txt
ls -li orig.txt hard.txt soft.txt     # inode совпадают у orig и hard, Links = 2
rm orig.txt
cat hard.txt   # работает
cat soft.txt   # No such file or directory
find /tmp -maxdepth 1 -xtype l
ln /tmp /tmp/dirlink        # "hard link not allowed for directory"
ln /tmp/hard.txt /mnt/data01/x   # "Invalid cross-device link"
```

</details>

#### C7. Деплой через симлинк

Воспроизведи паттерн zero-downtime деплоя:
```text:no-line-numbers
/opt/app/releases/2026-09-13-1000/
/opt/app/releases/2026-09-13-1200/
/opt/app/current -> releases/2026-09-13-1200
```
Покажи, как **атомарно** переключить `current` на другой релиз (подсказка: `ln -sfn` + `mv -T`)
и почему обычный `rm && ln -s` — плохо.

<details><summary>Ответ</summary>

```bash
sudo mkdir -p /opt/app/releases/{2026-09-13-1000,2026-09-13-1200}
sudo ln -s /opt/app/releases/2026-09-13-1000 /opt/app/current
ls -l /opt/app/current
# атомарное переключение:
sudo ln -sfn /opt/app/releases/2026-09-13-1200 /opt/app/current.tmp
sudo mv -T /opt/app/current.tmp /opt/app/current
readlink -f /opt/app/current
```

`rm current && ln -s new current` оставляет окно в несколько миллисекунд, когда пути `current`
не существует — запросы в этот момент получают 500. `mv -T` заменяет симлинк **атомарно**
(системный вызов `rename()`), окна нет.

</details>

#### C8. Поиск места

Напиши скрипт `/vagrant/disk_usage.sh`, который выводит:
```text:no-line-numbers
=== DISK USAGE REPORT ===
[!] /        : 78% used (12G free)   inodes: 23%
[OK] /boot   : 45% used ...
--- TOP 10 DIRS in / ---
2.1G /var
...
--- TOP 10 FILES ---
--- DELETED BUT OPEN FILES ---
--- WARNINGS ---
[!] /var/log/app.log is 1.2G
```
Скрипт должен подсвечивать ФС, заполненные более чем на 80% (по месту **или** по inode).

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
echo "=== DISK USAGE REPORT ==="
df -hPT -x tmpfs -x devtmpfs | awk 'NR>1 {gsub("%","",$6); print $7, $6, $5}' |
while read -r mnt usep avail; do
  inode=$(df -iP "$mnt" | awk 'NR==2 {gsub("%","",$5); print $5}')
  flag="[OK]"; (( usep > 80 || inode > 80 )) && flag="[!]"
  printf '%-5s %-20s : %s%% used (%s free)  inodes: %s%%\n' "$flag" "$mnt" "$usep" "$avail" "$inode"
done

echo "--- TOP 10 DIRS in / ---"
du -xh --max-depth=2 / 2>/dev/null | sort -rh | head -10
echo "--- TOP 10 FILES ---"
find / -xdev -type f -printf '%s %p\n' 2>/dev/null | sort -rn | head -10 |
  awk '{printf "%.1fM %s\n", $1/1048576, $2}'
echo "--- DELETED BUT OPEN FILES ---"
lsof +L1 2>/dev/null | head -10
echo "--- WARNINGS ---"
find /var/log -type f -size +500M 2>/dev/null | while read -r f; do
  echo "[!] $f is $(du -h "$f" | cut -f1)"
done
```

</details>

#### C9. Swap

Создай swap-файл на 512 МБ, включи, проверь. Измени `swappiness` на 10
временно и постоянно. Затем корректно всё отключи и удали.

<details><summary>Ответ</summary>

```bash
sudo fallocate -l 512M /swapfile2 && sudo chmod 600 /swapfile2
sudo mkswap /swapfile2 && sudo swapon /swapfile2
swapon --show; free -h
sudo sysctl -w vm.swappiness=10                       # временно
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-swap.conf   # постоянно
sudo sysctl --system | grep swappiness
sudo swapoff /swapfile2 && sudo rm -f /swapfile2
```

</details>

#### C10. fsck

На тестовом разделе: размонтируй, запусти принудительную проверку,
посмотри отчёт. Затем попробуй запустить `fsck` на **смонтированном** разделе и объясни,
почему утилита предупреждает (и что будет, если проигнорировать).

<details><summary>Ответ</summary>

```bash
sudo umount /mnt/data01
sudo e2fsck -f "${L}p1"
sudo mount "${L}p1" /mnt/data01
sudo e2fsck -f "${L}p1"     # предупреждение: WARNING!!! ... mounted filesystem
```

</details>

---

### Блок D. Инциденты

**D1.** Мониторинг: «/ заполнен на 98%». У тебя 5 минут. Напиши последовательность команд
и типовых виновников по убыванию вероятности.

<details><summary>Ответ</summary>

```bash
df -h; df -i                                  # какая ФС и по чему кончилось
du -xh --max-depth=1 / 2>/dev/null | sort -rh | head
du -xh --max-depth=1 /var | sort -rh | head
journalctl --disk-usage && sudo journalctl --vacuum-size=200M
du -sh /var/lib/docker && docker system df
sudo apt clean; sudo apt autoremove --purge
find / -xdev -type f -size +500M 2>/dev/null | head
lsof +L1 | head
```

Типовые виновники по убыванию: `/var/log` (не настроен logrotate), `/var/lib/docker`,
кэш пакетов, старые ядра, core dumps, удалённые открытые файлы, дампы БД в `/tmp`.

</details>

**D2.** `df -h` показывает 45% занято, но приложение падает с `No space left on device`.
Диагностика?

<details><summary>Ответ</summary>

Проверить `df -i` (кончились inode) и `lsof +L1` (удалённые открытые файлы).
Также: приложение пишет в другой раздел (`df -h /путь`), ФС в read-only (`mount | grep ' / '`),
квоты (`repquota -a`), лимит `ulimit -f`, или это отдельный контейнерный слой/volume.

</details>

**D3.** Сервер не загрузился после добавления строки в `/etc/fstab`. На консоли emergency mode.
Как войти, как починить, какие два флага предотвратили бы проблему?

<details><summary>Ответ</summary>

Вход: на консоли ввести root-пароль (или загрузиться с `init=/bin/bash` из GRUB —
[тема 11](/linux/11-boot-the-system)).
Далее `mount -o remount,rw /`, исправить `/etc/fstab`, `systemctl daemon-reload`, `mount -a`,
`reboot`. Предотвратили бы: опция **`nofail`** (плюс `x-systemd.device-timeout=10`) и обязательная
проверка `mount -a` до перезагрузки. Плюс UUID вместо `/dev/sdX`.

</details>

**D4.** `umount /mnt/backup` выдаёт `target is busy`. Три способа разобраться, какой безопаснее.

<details><summary>Ответ</summary>

(1) `lsof +D /mnt/backup` / `fuser -vm /mnt/backup` — узнать, кто держит, и корректно
завершить процессы — **самый безопасный** путь. (2) `umount -l` (lazy) — отцепить сразу,
реально освободится позже; приемлемо, но данные могут ещё дописываться. (3) `fuser -km` —
принудительно убить все процессы — опасно, потеря данных. Не забудь простейшую причину: ты сам
находишься в этом каталоге — `cd /`.

</details>

**D5.** Файловая система внезапно перешла в read-only, приложение не может писать.
В `dmesg` — `EXT4-fs error`. Что произошло, что делать по шагам?

<details><summary>Ответ</summary>

Ядро обнаружило ошибку ФС или ввода-вывода и перевело ФС в read-only, чтобы не усугубить
повреждение. Шаги: `dmesg -T | tail -50` и `journalctl -k` (ошибка ФС или ошибки диска?),
`smartctl -a /dev/sdX` — проверить здоровье диска; предупредить о простое; размонтировать ФС
(для корня — rescue) и выполнить `fsck -y`; если проблема в железе — сначала снять образ
`ddrescue`, затем менять диск и восстанавливать из бэкапа.

</details>

**D6.** Разработчик просит «увеличить диск на сервере». Диск в облаке уже расширен до 100 ГБ,
но `df -h` показывает старые 50 ГБ. Что нужно сделать (для обычного раздела и для LVM)?

<details><summary>Ответ</summary>

Обычный раздел:
```bash
lsblk                              # диск уже 100G, раздел старый
sudo growpart /dev/vda 1           # расширить раздел
sudo resize2fs /dev/vda1           # ext4 (для XFS: sudo xfs_growfs /)
df -h
```
LVM:
```bash
sudo pvresize /dev/vda3
sudo lvextend -l +100%FREE /dev/vg0/root
sudo resize2fs /dev/vg0/root       # или xfs_growfs /
```
Всё делается онлайн, без перезагрузки. (Уменьшение — только офлайн и только для ext4; XFS
уменьшать нельзя вообще.)

</details>

**D7.** `/var/lib/docker` занимает 60 ГБ из 80. Как безопасно почистить и что делать,
чтобы не повторялось?

<details><summary>Ответ</summary>

```bash
docker system df                       # что именно занимает
docker image prune -a                  # неиспользуемые образы
docker container prune
docker builder prune                   # кэш сборки — часто самый толстый
docker volume ls -qf dangling=true     # осторожно: тома могут содержать данные!
docker system prune -a                 # всё сразу (⚠️ проверь тома)
```
Профилактика: `--rm` для одноразовых контейнеров, ограничение размера логов
(`log-opts: max-size/max-file` в `/etc/docker/daemon.json`), регулярный `prune` по cron,
отдельный раздел под `/var/lib/docker`, мониторинг.

</details>

**D8.** Приложение создаёт миллионы мелких файлов в `/var/spool/app`. `df -h` в норме,
но новые файлы не создаются. Что произошло и какие есть решения (краткосрочное и долгосрочное)?

<details><summary>Ответ</summary>

Кончились inode (`df -i` покажет 100%). Краткосрочно: удалить/заархивировать старые файлы
(`find /var/spool/app -type f -mtime +7 -delete`), освободив inode. Долгосрочно: пересоздать ФС
с большим числом inode (`mkfs.ext4 -N <count>` или `-i <bytes-per-inode>`), перейти на XFS
(динамическое выделение inode), изменить архитектуру приложения — складывать данные в БД/объектное
хранилище или упаковывать в архивы вместо миллионов мелких файлов.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что делать, если закончилось место на диске?

<details><summary>Ответ</summary>

`df -h` и `df -i` → `du -xh --max-depth=1` по подозрительным точкам → `lsof +L1` →
чистка логов/кэшей/docker → расширение диска. Не забыть про logrotate, чтобы не повторилось.

</details>

**2.** Как добавить новый диск в Linux? Опиши последовательность.

<details><summary>Ответ</summary>

`lsblk` → `parted mklabel gpt` + `mkpart` → `mkfs.ext4` → создать точку монтирования →
`mount` → добавить в `/etc/fstab` по UUID с `nofail` → `mount -a` для проверки.

</details>

**3.** Зачем в fstab UUID?

<details><summary>Ответ</summary>

Имена устройств нестабильны и меняются при добавлении/переподключении дисков; UUID привязан
к файловой системе и не меняется, что защищает от монтирования не того раздела и от падения
загрузки.

</details>

**4.** Что такое inode?

<details><summary>Ответ</summary>

Структура с метаданными файла (права, владелец, размер, времена, счётчик ссылок, указатели на
блоки). Имя файла хранится не в inode, а в каталоге.

</details>

**5.** Чем hard link отличается от symlink?

<details><summary>Ответ</summary>

Hard link — второе имя для того же inode, только внутри одной ФС, не для каталогов; данные живут,
пока есть ссылки. Symlink — отдельный файл с путём, работает между ФС и на каталоги, может стать
«битым».

</details>

**6.** Почему после удаления большого лога место не освободилось?

<details><summary>Ответ</summary>

Файл открыт процессом: пока есть дескриптор, блоки не освобождаются. `lsof +L1` покажет;
решается `truncate -s 0`, рестартом/reload сервиса или корректной ротацией.

</details>

**7.** Как посмотреть, какие ФС смонтированы и с какими опциями?

<details><summary>Ответ</summary>

`findmnt`, `mount`, `df -hT`, `cat /proc/mounts`.

</details>

**8.** Что такое swap и нужен ли он на сервере с 64 ГБ RAM?

<details><summary>Ответ</summary>

Область на диске для вытеснения страниц памяти. Даже при 64 ГБ RAM небольшой swap полезен как
буфер от резких всплесков и для вытеснения неиспользуемых страниц; но при этом важен низкий
`swappiness` и мониторинг — постоянный своп означает нехватку памяти. На нодах Kubernetes
его обычно отключают.

</details>

**9.** Как расширить файловую систему без перезагрузки?

<details><summary>Ответ</summary>

Расширить сам раздел (`growpart` / `pvresize` + `lvextend`), затем ФС: `resize2fs` для ext4,
`xfs_growfs` для XFS — обе работают на смонтированной ФС.

</details>

---

### 🎯 Чек-лист

- [ ] Прошёл полный цикл: диск → GPT → раздел → mkfs → mount → fstab → проверка
- [ ] Всегда делаю `mount -a` перед перезагрузкой и ставлю `nofail`
- [ ] Помню про `df -i` и умею объяснить «место есть, а файл не создаётся»
- [ ] Могу найти пожирателя места за 3 команды
- [ ] Понимаю inode, hard/symlink и атомарное переключение симлинка
- [ ] Знаю, как расширить ФС онлайн (обычный раздел и LVM)
- [ ] Никогда не запускаю fsck на смонтированной ФС
