---
title: "09. Devices"
description: "Устройства, /dev, udev, sysfs и dd: имена дисков, стабильные UUID, побайтовое копирование"
---

# 09. Devices — устройства, /dev, udev, dd

> Источник: `09_devices.txt` (Journeyman, 7 уроков)
> **После темы ты умеешь:** читать `/dev`, находить диски и их имена, понимать udev
> и пользоваться `dd` не отстрелив себе ногу.

---

## 🗺️ Схема: путь от железа до файла в /dev

```text:no-line-numbers
   ФИЗИЧЕСКОЕ УСТРОЙСТВО (SSD, сетевая карта, USB-флешка)
                    │
                    ▼
   ┌────────────────────────────────────────────┐
   │  ЯДРО: драйвер обнаруживает устройство     │
   │  присваивает major:minor номера            │
   └────────────────────┬───────────────────────┘
                        │  событие uevent
          ┌─────────────┴──────────────┐
          ▼                            ▼
   ┌──────────────┐            ┌───────────────────┐
   │   /sys       │            │  udev (systemd-   │
   │  (sysfs)     │            │  udevd) читает    │
   │ информация   │            │  правила          │
   │ об устройстве│            └─────────┬─────────┘
   └──────────────┘                      │ создаёт
                                         ▼
                            ┌────────────────────────────┐
                            │  /dev/sda   /dev/null      │
                            │  /dev/disk/by-uuid/...     │  ← ФАЙЛЫ-устройства
                            └────────────────────────────┘
                                         │
                                         ▼
                          Программы работают с ними как с файлами:
                          open() / read() / write() / ioctl()
```

🔑 **«Всё есть файл»** — главный принцип UNIX. Диск, мышь, случайные числа, звуковая карта —
всё представлено файлами в `/dev`, и работать с ними можно обычными `cat`, `dd`, `>`.

---

## 1. /dev directory

```bash
ls -l /dev | head -30
```

```text:no-line-numbers
crw-rw-rw- 1 root root   1,  3 Sep 13 10:00 null
brw-rw---- 1 root disk   8,  0 Sep 13 10:00 sda
│           │      │     │  │
│           │      │     │  └─ MINOR: конкретное устройство/раздел
│           │      │     └──── MAJOR: какой драйвер обслуживает
│           │      └────────── группа-владелец (disk — поэтому доступ к дискам по группе)
│           └───────────────── владелец
└─ c = character device, b = block device
```

**Псевдоустройства, которые нужно знать наизусть:**

| Устройство | Что делает |
|-----------|-----------|
| `/dev/null` | «Чёрная дыра»: запись пропадает, чтение = EOF |
| `/dev/zero` | Бесконечный поток нулевых байтов |
| `/dev/random` | Криптослучайные байты (может блокироваться на старых ядрах) |
| `/dev/urandom` | Криптослучайные байты, **не блокируется** ← используй это |
| `/dev/full` | При записи всегда «диск полон» (для тестов) |
| `/dev/tty` | Текущий управляющий терминал |
| `/dev/stdin`, `/dev/stdout`, `/dev/stderr` | Потоки текущего процесса |
| `/dev/console` | Системная консоль |

```bash
command > /dev/null 2>&1                      # выбросить весь вывод
dd if=/dev/zero of=file bs=1M count=100       # файл из 100 МБ нулей
head -c 32 /dev/urandom | base64              # случайный пароль/ключ
echo "hi" > /dev/tty                          # написать прямо в терминал (в обход перенаправления)
```

💡 Трюк из практики: `/dev/tcp/host/port` (bash-встроенное, не настоящий файл) —
проверка порта без `nc`:
```bash
timeout 2 bash -c '</dev/tcp/8.8.8.8/53' && echo "порт открыт" || echo "закрыт"
```

---

## 2. Device Types — типы устройств

| Тип | Символ | Как работает | Примеры |
|-----|--------|--------------|---------|
| **Блочное** | `b` | Данные блоками фиксированного размера, **произвольный доступ**, буферизация ядром | `/dev/sda`, `/dev/nvme0n1`, `/dev/loop0` |
| **Символьное** | `c` | Поток байт, последовательный доступ, без буферизации | `/dev/tty`, `/dev/null`, `/dev/random` |
| **Сетевое** | — | **Нет файла в `/dev`!** Работа через сокеты | `eth0`, `ens3`, `lo` |
| **Псевдо** | `c` | Реализовано ядром, железа нет | `/dev/zero`, `/dev/null` |

⚠️ Частый вопрос на собеседовании: «как выглядит сетевая карта в `/dev`?» — **никак**.
Сетевые интерфейсы адресуются по имени через сокеты (`ip link`, `ss`), файла устройства у них нет.

```bash
ls -l /dev/sda /dev/null /dev/tty        # b, c, c
lsblk                                    # только блочные устройства — наглядно
```

---

## 3. Device Names — имена устройств

```text:no-line-numbers
/dev/sda     — SCSI/SATA/USB диск  (a = первый, b = второй…)
/dev/sda1    — первый раздел на нём
/dev/nvme0n1 — NVMe: контроллер 0, namespace 1
/dev/nvme0n1p1 — первый раздел NVMe (обрати внимание на 'p'!)
/dev/vda     — виртуальный диск (KVM/virtio) ← у тебя в Vagrant именно такой
/dev/xvda    — Xen (AWS старого поколения)
/dev/sr0     — CD/DVD
/dev/loop0   — loop-устройство (файл, смонтированный как диск)
/dev/mapper/vg-lv — LVM том
```

🔴 **Главная проблема: имена НЕ стабильны.** После перезагрузки или добавления диска `sda`
может стать `sdb`. Поэтому в `/etc/fstab` **никогда не пишут `/dev/sdX`** — только UUID.

**Стабильные идентификаторы** (создаёт udev):

```bash
ls -l /dev/disk/by-uuid/      # ← ГЛАВНЫЙ способ, используется в fstab
ls -l /dev/disk/by-label/     # по метке ФС
ls -l /dev/disk/by-id/        # по серийному номеру устройства
ls -l /dev/disk/by-path/      # по физическому расположению (порт/слот)
blkid                         # UUID, LABEL, TYPE всех блочных устройств
lsblk -f                      # то же в виде дерева ← удобнее всего
```

---

## 4. sysfs — /sys

`/sys` — виртуальная ФС, отражающая **модель устройств ядра**: что за устройство,
к какой шине подключено, какой драйвер, какие параметры.

```bash
ls /sys/                        # block class devices bus module kernel …
ls /sys/block/                  # все блочные устройства
cat /sys/block/vda/size         # размер в секторах по 512 байт
cat /sys/block/vda/queue/rotational   # 1 = HDD, 0 = SSD ← полезно для настройки планировщика
cat /sys/block/vda/queue/scheduler    # какой I/O-планировщик активен
cat /sys/class/net/eth0/address       # MAC-адрес
cat /sys/class/net/eth0/operstate     # up/down
cat /sys/class/thermal/thermal_zone0/temp   # температура (тысячные доли °C)
```

| Что | `/proc` | `/sys` |
|-----|---------|--------|
| Про что | процессы + разное состояние ядра | устройства, драйверы, шины |
| Структура | исторически сложившаяся, «свалка» | строгая иерархия |
| Появилось | изначально | ядро 2.6 |

Многие параметры можно **менять записью в файл**:
```bash
echo mq-deadline | sudo tee /sys/block/vda/queue/scheduler
```

---

## 5. udev — менеджер устройств

udev (`systemd-udevd`) слушает события ядра (uevent) и по правилам:
- создаёт файлы в `/dev` с нужными именами, правами и владельцем;
- создаёт стабильные симлинки (`/dev/disk/by-uuid/...`);
- запускает команды при подключении/отключении.

```bash
ls /lib/udev/rules.d/          # правила дистрибутива (не редактировать)
ls /etc/udev/rules.d/          # ТВОИ правила (имеют приоритет)

udevadm info --query=all --name=/dev/vda     # всё, что udev знает об устройстве
udevadm info -a --name=/dev/vda | head -40   # атрибуты для написания правил
udevadm monitor                              # события в реальном времени ← воткни флешку и смотри
sudo udevadm control --reload-rules          # перечитать правила
sudo udevadm trigger                         # применить к уже существующим устройствам
```

Пример своего правила `/etc/udev/rules.d/99-usb-backup.rules`:
```text:no-line-numbers
SUBSYSTEM=="block", ATTRS{idVendor}=="0781", ATTRS{idProduct}=="5583", SYMLINK+="backupdisk", MODE="0660", GROUP="backup"
```
Теперь конкретная флешка всегда появляется как `/dev/backupdisk`.

Практический смысл для DevOps: закрепление имён дисков в СХД, права на устройства для приложений
(GPU, TPM, последовательные порты), автозапуск при подключении оборудования.

---

## 6. lsusb, lspci, lsscsi, lsblk — инвентаризация железа

```bash
lsblk                       # дерево блочных устройств ← начинай отсюда
lsblk -f                    # + файловые системы, UUID, точки монтирования
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,UUID

lspci                       # PCI-устройства (сетевые карты, GPU, контроллеры)
lspci -v | less
lspci -nnk | grep -A3 -i ethernet    # какой драйвер обслуживает сетевую карту

lsusb                       # USB-устройства
lsusb -t                    # деревом

lsscsi                      # SCSI-устройства (нужен пакет lsscsi)
lshw -short                 # общая сводка по железу (нужен пакет lshw)
dmidecode -t system         # данные из BIOS/DMI: вендор, модель, серийник
hdparm -I /dev/sda          # детали диска
smartctl -a /dev/sda        # SMART: здоровье диска ← для мониторинга

dmesg | tail -30            # сообщения ядра: что подключилось/отвалилось
dmesg -T | grep -i error
journalctl -k -b            # сообщения ядра за текущую загрузку
```

💡 Рабочий сценарий: «добавили диск в ВМ, а его не видно» →
```bash
lsblk                                       # диска нет
echo "- - -" | sudo tee /sys/class/scsi_host/host0/scan   # пересканировать шину
lsblk                                       # появился
dmesg | tail
```

---

## 7. dd — побайтовое копирование

```text:no-line-numbers
dd if=<источник> of=<приёмник> bs=<размер блока> count=<число блоков> status=progress
   │             │             │                 │
   │             │             │                 └─ сколько блоков (иначе — до конца)
   │             │             └─ размер блока (4M — хороший дефолт)
   │             └─ output file (файл ИЛИ устройство)
   └─ input file
```

Полезные применения:

```bash
# Файл нужного размера (тесты, swap, loop-устройства)
dd if=/dev/zero of=/tmp/test.img bs=1M count=100 status=progress

# Образ диска целиком (бэкап)
sudo dd if=/dev/vda of=/backup/disk.img bs=4M status=progress

# Записать ISO на флешку
sudo dd if=ubuntu.iso of=/dev/sdb bs=4M status=progress conv=fsync

# Только MBR (первые 512 байт)
sudo dd if=/dev/sda of=mbr_backup.bin bs=512 count=1

# Тест скорости записи
dd if=/dev/zero of=/tmp/testfile bs=1M count=1024 conv=fdatasync status=progress

# Затирание диска перед списанием
sudo dd if=/dev/urandom of=/dev/sdb bs=4M status=progress
```

🔴 **dd = «disk destroyer».** Ошибка в `of=` уничтожает данные без вопросов и без отката.

Правила безопасности:
1. **Трижды проверь `of=`.** Перепутал `if` и `of` — затёр источник.
2. Перед записью на диск — `lsblk` и `blkid`, убедись, что это нужное устройство.
3. `of=/dev/sda` — весь диск, `of=/dev/sda1` — раздел. Разница фатальна.
4. Целевой диск должен быть **размонтирован**.
5. Хорошие альтернативы: `cp`/`rsync` для файлов, `pv` для прогресса, `ddrescue` для сбойных дисков.

```bash
# Прогресс у работающего dd (если забыл status=progress)
sudo kill -USR1 $(pgrep -x dd)
```

---

## 💼 Как это в DevOps

- **Диски в облаке:** подключил EBS/диск → `lsblk` → разметка → ФС → монтирование по **UUID**.
- **fstab только по UUID** — иначе после перезагрузки сервер не поднимется (имена уехали).
- **Мониторинг дисков:** `smartctl`, `/sys/block/*/stat`, `iostat` — предсказание отказов.
- **Контейнеры:** `--device=/dev/nvidia0` для GPU, `/dev/fuse`, доступ к `/dev/kvm`.
- **Kubernetes:** device plugins для GPU, `hostPath` на устройства, CSI-драйверы.
- **Расследование:** `dmesg -T` — первое место, где видно отвалившийся диск или ошибки I/O.

---

## 🧪 Мини-лаба

```bash
vagrant ssh

# 1. Инвентаризация
lsblk -f
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,UUID
sudo blkid
lspci | head
dmesg -T | tail -20

# 2. Типы устройств
ls -l /dev/vda /dev/null /dev/urandom /dev/tty
ls -l /dev/disk/by-uuid/
ls -l /dev/disk/by-id/ 2>/dev/null | head

# 3. sysfs
cat /sys/block/vda/size                    # в секторах по 512 байт
echo $(( $(cat /sys/block/vda/size) * 512 / 1024 / 1024 / 1024 ))" GB"
cat /sys/block/vda/queue/rotational
cat /sys/block/vda/queue/scheduler
cat /sys/class/net/eth0/address 2>/dev/null || cat /sys/class/net/*/address

# 4. udev
udevadm info --query=all --name=/dev/vda | head -20
sudo udevadm monitor --udev &     # в фоне
sudo modprobe loop                 # вызовет события
sleep 2; kill %1

# 5. Псевдоустройства
head -c 16 /dev/urandom | xxd
head -c 32 /dev/urandom | base64
echo "исчезнет" > /dev/null; echo $?

# 6. dd — безопасная практика на ФАЙЛАХ, не на дисках
dd if=/dev/zero of=/tmp/disk.img bs=1M count=100 status=progress
ls -lh /tmp/disk.img
dd if=/dev/zero of=/tmp/speed.test bs=1M count=512 conv=fdatasync status=progress
rm -f /tmp/speed.test

# 7. loop-устройство: файл как настоящий диск (мост к теме 10)
sudo losetup -fP /tmp/disk.img
losetup -a
LOOP=$(losetup -a | grep disk.img | cut -d: -f1)
sudo mkfs.ext4 "$LOOP"
sudo mkdir -p /mnt/looptest && sudo mount "$LOOP" /mnt/looptest
df -h /mnt/looptest
echo "работает" | sudo tee /mnt/looptest/hello.txt
sudo umount /mnt/looptest && sudo losetup -d "$LOOP"

# 8. Проверка порта без nc
timeout 2 bash -c '</dev/tcp/1.1.1.1/53' && echo OPEN || echo CLOSED
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `lsblk -f` | Блочные устройства + ФС + UUID ← начинай отсюда |
| `blkid` | UUID/LABEL/TYPE устройств |
| `ls -l /dev/disk/by-uuid/` | Стабильные имена дисков |
| `lspci -nnk` | PCI-устройства и драйверы |
| `lsusb -t` | USB-дерево |
| `lshw -short` / `dmidecode` | Сводка по железу |
| `dmesg -T \| tail` | Что ядро говорит об устройствах |
| `udevadm info --name=/dev/X` | Что udev знает об устройстве |
| `udevadm monitor` | События подключения в реальном времени |
| `cat /sys/block/X/queue/rotational` | SSD (0) или HDD (1) |
| `dd if= of= bs=4M status=progress` | Побайтовое копирование (⚠️) |
| `losetup -fP file` | Примонтировать файл как блочное устройство |
| `smartctl -a /dev/sda` | Здоровье диска |

---

## 🧠 Что запомнить

1. Всё есть файл: `b` — блочные (диски), `c` — символьные (терминалы, `/dev/null`),
   у **сетевых интерфейсов файла в `/dev` нет**.
2. `/dev/null` — выбросить, `/dev/zero` — нули, `/dev/urandom` — случайность.
3. Имена `/dev/sdX` **нестабильны** → в fstab и скриптах используй **UUID**.
4. `/sys` — про устройства и драйверы, `/proc` — про процессы и состояние ядра.
5. udev создаёт `/dev`-файлы и симлинки `by-uuid`, `by-id`; свои правила — в `/etc/udev/rules.d/`.
6. `lsblk -f` — команда №1 при работе с дисками; `dmesg -T` — команда №1 при проблемах с железом.
7. `dd` не задаёт вопросов: перепутал `of=` — потерял данные. Проверяй дважды.
8. Файл можно сделать «диском» через `losetup` — удобно тренироваться без риска.

---

## Задачи

> `vagrant snapshot save before_09 && vagrant ssh`
> ⚠️ В этой теме есть `dd`. Все упражнения — **на файлах и loop-устройствах**, не на реальных дисках.

### Блок A. Теория

**A1.** Что означает принцип «всё есть файл» применительно к устройствам?

<details><summary>Ответ</summary>

Устройства представлены специальными файлами в `/dev`, и работа с ними ведётся теми же
системными вызовами, что и с обычными файлами (`open`, `read`, `write`, `ioctl`). Поэтому к диску
применимы `dd`, `cat`, перенаправления, а права доступа к устройству задаются обычными `chmod`/`chown`.

</details>

**A2.** Чем блочное устройство отличается от символьного? Приведи по 2 примера каждого.

<details><summary>Ответ</summary>

Блочные: доступ порциями фиксированного размера, произвольный (random access), с буферизацией
ядром — `/dev/vda`, `/dev/nvme0n1`, `/dev/loop0`. Символьные: поток байтов, последовательный доступ,
без блочной буферизации — `/dev/tty`, `/dev/null`, `/dev/urandom`.

</details>

**A3.** Как выглядит сетевая карта в `/dev`? Объясни ответ.

<details><summary>Ответ</summary>

Никак — файла устройства у сетевой карты нет. Сетевые интерфейсы адресуются по имени
(`eth0`, `ens3`) через сокеты и netlink; смотреть их надо через `ip link`, `/sys/class/net/`.

</details>

**A4.** Что такое major и minor номера устройства? Где их увидеть?

<details><summary>Ответ</summary>

Major указывает, какой драйвер ядра обслуживает устройство; minor — конкретный экземпляр
(диск/раздел). Видны в `ls -l /dev` вместо размера файла: `brw-rw---- 1 root disk 8, 0 ... sda`.

</details>

**A5.** Назови 5 псевдоустройств и их назначение.

<details><summary>Ответ</summary>

`/dev/null` — выбросить вывод; `/dev/zero` — источник нулевых байтов; `/dev/urandom` —
криптослучайные байты без блокировки; `/dev/full` — эмуляция «диск полон» для тестов;
`/dev/tty` — текущий управляющий терминал.

</details>

**A6.** Почему имена `/dev/sda`, `/dev/sdb` считаются нестабильными? К чему это приводит на практике?

<details><summary>Ответ</summary>

Имена присваиваются в порядке обнаружения устройств, который зависит от времени отклика
контроллеров, порядка инициализации драйверов и наличия других дисков. После добавления диска или
перезагрузки `sdb` может стать `sda`. Последствие: система монтирует не тот раздел или не грузится.

</details>

**A7.** Какие есть стабильные способы адресации дисков? Какой используется в `/etc/fstab` и почему?

<details><summary>Ответ</summary>

UUID (`/dev/disk/by-uuid/`), LABEL (`by-label`), by-id (серийный номер), by-path
(физическое расположение). В `/etc/fstab` используют **UUID**: он привязан к самой файловой системе,
не меняется при перестановке дисков и уникален.

</details>

**A8.** Чем `/sys` отличается от `/proc`?

<details><summary>Ответ</summary>

`/proc` — информация о процессах и общее состояние ядра (исторически — «всё подряд»).
`/sys` (sysfs, с ядра 2.6) — строгая иерархия модели устройств: устройства, шины, драйверы, классы,
параметры блочных устройств и сетевых интерфейсов.

</details>

**A9.** Что делает udev? Что произойдёт, если его остановить?

<details><summary>Ответ</summary>

udev получает события от ядра (uevent) и по правилам создаёт файлы устройств в `/dev`
с нужными именами/правами/владельцем, формирует стабильные симлинки (`by-uuid`, `by-id`),
может запускать команды. Без udev `/dev` не наполняется динамически: новые устройства не появляются,
стабильных симлинков нет, права остаются дефолтными.

</details>

**A10.** Почему `dd` называют «disk destroyer»? Перечисли правила безопасности.

<details><summary>Ответ</summary>

Он побайтово и безоговорочно пишет в указанную цель: одна опечатка в `of=` уничтожает
раздел или диск без подтверждения и без возможности отката.
Правила: (1) проверять `of=` дважды, (2) `lsblk`/`blkid` до запуска, (3) помнить разницу
`/dev/sda` и `/dev/sda1`, (4) цель должна быть размонтирована, (5) для файлов использовать
`cp`/`rsync`, для сбойных дисков — `ddrescue`.

</details>

**A11.** Что такое loop-устройство и зачем оно нужно?

<details><summary>Ответ</summary>

Loop-устройство позволяет представить обычный файл как блочное устройство: на нём можно
создать файловую систему, разметить разделы, смонтировать. Используется для образов ISO, тестов,
swap-файлов, контейнерных образов и безопасной тренировки без реальных дисков.

</details>

**A12.** Как отличить SSD от HDD средствами системы?

<details><summary>Ответ</summary>

`cat /sys/block/<dev>/queue/rotational`: `0` — не вращается (SSD/NVMe), `1` — HDD.
Также `lsblk -d -o NAME,ROTA,MODEL` и `smartctl -i /dev/sda`.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  lsblk -f
B2.  blkid /dev/vda1
B3.  ls -l /dev/disk/by-uuid/
B4.  cat /sys/block/vda/queue/rotational
B5.  udevadm info --query=all --name=/dev/vda
B6.  udevadm monitor
B7.  dmesg -T | grep -i "I/O error"
B8.  lspci -nnk | grep -A3 -i ethernet
B9.  dd if=/dev/zero of=/tmp/f bs=1M count=10
B10. dd if=/dev/urandom bs=32 count=1 2>/dev/null | base64
B11. sudo losetup -fP /tmp/disk.img
B12. echo "- - -" | sudo tee /sys/class/scsi_host/host0/scan
B13. sudo kill -USR1 $(pgrep -x dd)
B14. timeout 2 bash -c '</dev/tcp/1.1.1.1/53'
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Дерево блочных устройств с типом ФС, меткой, UUID и точками монтирования.
B2.  UUID, TYPE и LABEL конкретного раздела.
B3.  Симлинки «UUID → устройство», созданные udev.
B4.  0 — SSD/виртуальный диск, 1 — вращающийся HDD.
B5.  Все свойства устройства, известные udev (пути, симлинки, атрибуты).
B6.  Поток событий подключения/отключения устройств в реальном времени.
B7.  Ошибки ввода-вывода с человекочитаемым временем — признак умирающего диска или проблем СХД.
B8.  Сетевые PCI-устройства и используемый драйвер/модуль ядра.
B9.  Создаёт файл 10 МБ из нулей.
B10. Печатает случайный 32-байтовый ключ в base64.
B11. Подключает файл-образ как loop-устройство, -P — создать устройства для разделов внутри.
B12. Заставляет ядро пересканировать SCSI-шину — так «находят» горячо добавленный диск.
B13. Просит работающий dd вывести текущий прогресс (если забыли status=progress).
B14. Проверяет TCP-порт 53 средствами bash, без nc/telnet; код возврата 0 = порт открыт.
```

</details>

**B15.** Чем опасна разница между `of=/dev/sda` и `of=/dev/sda1`?

<details><summary>Ответ</summary>

`/dev/sda` — **весь диск** (включая таблицу разделов), `/dev/sda1` — один раздел.
Запись образа в `/dev/sda1` вместо `/dev/sda` даст неработающую флешку, а запись в `/dev/sda`
вместо файла — уничтожение таблицы разделов и всех данных диска.

</details>

---

### Блок C. Практика

**C1. Инвентаризация стенда.** Собери «паспорт железа» ВМ:
- все блочные устройства с размерами, типом ФС, UUID и точками монтирования;
- тип виртуализации;
- PCI-устройства;
- размер диска, вычисленный **из `/sys`** (в ГБ), а не из `lsblk`;
- SSD это или HDD с точки зрения ядра.

<details><summary>Ответ</summary>

```bash
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,UUID
hostnamectl | grep -i virtualization
lspci | head
echo "$(( $(cat /sys/block/vda/size) * 512 / 1024**3 )) GB"
cat /sys/block/vda/queue/rotational      # 0 = SSD/виртуальный
```

</details>

**C2. Типы устройств.** Выведи `ls -l` для `/dev/vda`, `/dev/null`, `/dev/urandom`, `/dev/tty`.
Для каждого укажи: тип (b/c), major, minor, владельца и группу. Объясни, почему у `/dev/vda`
группа `disk`.

<details><summary>Ответ</summary>

```bash
ls -l /dev/vda /dev/null /dev/urandom /dev/tty
```
`/dev/vda` принадлежит группе `disk`, чтобы можно было выдавать доступ к блочным устройствам
через членство в группе, не раздавая root (например, для программ бэкапа).

</details>

**C3. Псевдоустройства на практике.**
1. Создай файл ровно 50 МБ из нулей и проверь размер.
2. Сгенерируй случайный пароль из 24 символов (только буквы и цифры).
3. Сгенерируй base64-ключ длиной 32 байта.
4. Покажи, что запись в `/dev/null` не занимает места на диске.
5. Напиши строку напрямую в терминал, чтобы она **не** попала в файл при перенаправлении вывода.

<details><summary>Ответ</summary>

```bash
dd if=/dev/zero of=/tmp/50mb.img bs=1M count=50 status=progress && ls -lh /tmp/50mb.img
tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 24; echo
head -c 32 /dev/urandom | base64
df -h /tmp; yes | head -c 100M > /dev/null; df -h /tmp      # размер не изменился
echo "видно только в терминале" > /dev/tty
```

</details>

**C4. sysfs-исследование.** Найди через `/sys`:
- MAC-адрес сетевого интерфейса;
- состояние интерфейса (up/down);
- активный I/O-планировщик диска;
- размер диска в секторах и в ГБ;
- количество прочитанных/записанных секторов (`/sys/block/vda/stat`).

<details><summary>Ответ</summary>

```bash
cat /sys/class/net/eth0/address 2>/dev/null || cat /sys/class/net/en*/address
cat /sys/class/net/eth0/operstate 2>/dev/null || cat /sys/class/net/en*/operstate
cat /sys/block/vda/queue/scheduler
cat /sys/block/vda/size
cat /sys/block/vda/stat
```

</details>

**C5. udev-наблюдение.** Запусти `udevadm monitor` в фоне и вызови событие устройства
(например, `sudo modprobe loop` или создание/удаление loop-устройства). Опиши, какие события
пришли: `KERNEL` и `UDEV` — в чём разница между ними?

<details><summary>Ответ</summary>

```bash
sudo udevadm monitor &
sudo modprobe loop ; sleep 2 ; kill %1
```
`KERNEL[...]` — «сырое» событие от ядра сразу при обнаружении устройства.
`UDEV[...]` — событие после того, как udev применил правила (создал ноды и симлинки).
Между ними и происходит вся магия именования и прав.

</details>

**C6. Loop-диск с нуля (ключевое упражнение темы).**
1. Создай файл-образ на 200 МБ.
2. Подключи его как loop-устройство.
3. Создай на нём файловую систему ext4 с меткой `LAB09`.
4. Смонтируй в `/mnt/lab09`.
5. Запиши туда файл, проверь `df -h` и `lsblk -f`.
6. Найди UUID нового устройства двумя способами.
7. Корректно размонтируй и отключи loop.

*Критерий:* на шаге 6 UUID из `blkid` и из `/dev/disk/by-uuid/` совпадают.

<details><summary>Ответ</summary>

```bash
dd if=/dev/zero of=/tmp/lab09.img bs=1M count=200 status=progress
sudo losetup -fP /tmp/lab09.img
LOOP=$(losetup -j /tmp/lab09.img | cut -d: -f1); echo "$LOOP"
sudo mkfs.ext4 -L LAB09 "$LOOP"
sudo mkdir -p /mnt/lab09 && sudo mount "$LOOP" /mnt/lab09
echo hello | sudo tee /mnt/lab09/test.txt
df -h /mnt/lab09 ; lsblk -f | grep -A1 loop
sudo blkid "$LOOP"
ls -l /dev/disk/by-uuid/ | grep "$(basename "$LOOP")"
sudo umount /mnt/lab09 && sudo losetup -d "$LOOP"
```

</details>

**C7. Тест скорости диска.** Измерь скорость последовательной записи через `dd`
с `conv=fdatasync` (объясни, зачем этот флаг) на 512 МБ. Затем измерь скорость чтения,
предварительно сбросив кэш (`sync; echo 3 | sudo tee /proc/sys/vm/drop_caches`).
Сравни результаты с кэшем и без.

<details><summary>Ответ</summary>

```bash
dd if=/dev/zero of=/tmp/speed.test bs=1M count=512 conv=fdatasync status=progress
sync; echo 3 | sudo tee /proc/sys/vm/drop_caches >/dev/null
dd if=/tmp/speed.test of=/dev/null bs=1M status=progress          # чтение с диска
dd if=/tmp/speed.test of=/dev/null bs=1M status=progress          # повтор — из кэша, намного быстрее
rm -f /tmp/speed.test
```
`conv=fdatasync` заставляет `dd` дождаться реальной записи на диск перед выходом; без него
измеряется скорость записи в страничный кэш памяти, а не на диск.

</details>

**C8. Скрипт-инвентаризация.** Напиши `/vagrant/disk_report.sh`:
```text:no-line-numbers
=== DISK REPORT ===
Device   Size    Type   FS      Mount        UUID
vda      64G     disk   -       -            -
vda1     63G     part   ext4    /            abc-123...
---
Rotational: no (SSD)
Scheduler: mq-deadline
Free space on /: 45G (28% used)
Inodes free on /: 3.8M
```

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
echo "=== DISK REPORT ==="
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,UUID
echo "---"
for d in /sys/block/[vsn]d*/ /sys/block/nvme*/; do
  [ -e "$d/queue/rotational" ] || continue
  name=$(basename "$d")
  rota=$(cat "$d/queue/rotational")
  [ "$rota" = 0 ] && t="no (SSD/virtual)" || t="yes (HDD)"
  echo "$name rotational: $t"
  echo "$name scheduler: $(cat "$d/queue/scheduler")"
done
echo "Free space on /: $(df -h / | awk 'NR==2 {print $4" ("$5" used)"}')"
echo "Inodes free on /: $(df -ih / | awk 'NR==2 {print $4}')"
```

</details>

**C9. Безопасный dd.** Напиши скрипт-обёртку `safe_dd.sh`, который перед выполнением:
- показывает `lsblk` целевого устройства;
- проверяет, что цель **не смонтирована**;
- требует явного подтверждения вводом имени устройства;
- только потом запускает `dd` с `status=progress`.

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
set -euo pipefail
SRC="${1:?usage: safe_dd.sh <src> <target-device>}"
DST="${2:?usage: safe_dd.sh <src> <target-device>}"

[[ -b "$DST" ]] || { echo "$DST не блочное устройство" >&2; exit 1; }
echo "--- ЦЕЛЬ ---"; lsblk "$DST"
if lsblk -no MOUNTPOINT "$DST" | grep -q .; then
  echo "ОШИБКА: устройство смонтировано, размонтируй сначала" >&2; exit 1
fi
read -rp "Все данные на $DST будут уничтожены. Введи имя устройства для подтверждения: " ans
[[ "$ans" == "$DST" ]] || { echo "отменено"; exit 1; }
dd if="$SRC" of="$DST" bs=4M status=progress conv=fsync
sync
```

</details>

**C10. Восстановление MBR (демонстрация).** На loop-устройстве:
сохрани первые 512 байт в файл, затри их нулями, убедись, что таблица разделов сломалась
(`fdisk -l`), восстанови из бэкапа и проверь, что всё вернулось.

<details><summary>Ответ</summary>

```bash
dd if=/dev/zero of=/tmp/mbr.img bs=1M count=100
sudo losetup -fP /tmp/mbr.img; L=$(losetup -j /tmp/mbr.img | cut -d: -f1)
echo -e "n\np\n1\n\n\nw" | sudo fdisk "$L"
sudo dd if="$L" of=/tmp/mbr_backup.bin bs=512 count=1
sudo fdisk -l "$L"
sudo dd if=/dev/zero of="$L" bs=512 count=1
sudo fdisk -l "$L"                           # разделов больше нет
sudo dd if=/tmp/mbr_backup.bin of="$L" bs=512 count=1
sudo partprobe "$L"; sudo fdisk -l "$L"      # раздел вернулся
sudo losetup -d "$L"
```

</details>

---

### Блок D. Инциденты

**D1.** Добавили диск в виртуалку «на горячую», но `lsblk` его не показывает. Что делать?

<details><summary>Ответ</summary>

Ядро не пересканировало шину. Проверить `dmesg -T | tail`, затем:
```bash
for h in /sys/class/scsi_host/host*; do echo "- - -" | sudo tee "$h/scan"; done
sudo partprobe; lsblk
```
Для virtio/NVMe обычно достаточно `echo 1 | sudo tee /sys/bus/pci/rescan`. Если не помогает —
диск не подключён на уровне гипервизора/облака.

</details>

**D2.** После перезагрузки сервер не поднялся, на консоли:
```text:no-line-numbers
Cannot open access to console, the root account is locked
... dependency failed for /data
```
В `/etc/fstab` записано `/dev/sdb1 /data ext4 defaults 0 2`. Что случилось и как правильно?

<details><summary>Ответ</summary>

Имя `/dev/sdb1` изменилось (диск переехал в другую позицию) либо диск не подключился.
Монтирование по `defaults` с `0 2` заставило systemd ждать устройство и уйти в emergency.
Правильно: монтировать по UUID и добавить `nofail` для некритичных ФС:
```text:no-line-numbers
UUID=xxxx-yyyy /data ext4 defaults,nofail,x-systemd.device-timeout=10 0 2
```
Восстановление: загрузиться в rescue, `blkid`, поправить fstab, `systemctl daemon-reload`, reboot.

</details>

**D3.** `dmesg` заполнен строками:
```text:no-line-numbers
blk_update_request: I/O error, dev sda, sector 1234567
```
Что это значит, насколько срочно и какие действия?

<details><summary>Ответ</summary>

Ядро не смогло прочитать/записать сектор — сбойный диск, проблема кабеля/контроллера или
СХД. Срочность высокая. Действия: `smartctl -a /dev/sda` (Reallocated_Sector_Ct, Pending),
проверить RAID (`mdadm --detail`, контроллер), убедиться, что бэкапы свежие, запланировать замену
диска; при росте ошибок — вывести узел из эксплуатации.

</details>

**D4.** Приложение пишет, что «нет места на диске», при этом `df -h` показывает 40% занято.
Три гипотезы и команды проверки.

<details><summary>Ответ</summary>

(1) Кончились **inode**: `df -i` (много мелких файлов). (2) Место занято **удалёнными, но
открытыми** файлами: `lsof +L1`, лечится рестартом процесса или `truncate`. (3) Приложение упирается
в **другой раздел**, чем ты смотришь (`df -h /path/to/app`), либо в квоту (`quota -u user`),
либо файл превысил лимит `ulimit -f` / ФС смонтирована `ro` (`mount | grep ' / '`).

</details>

**D5.** Коллега записывал ISO на флешку и выполнил `dd if=/dev/sdb of=ubuntu.iso bs=4M`.
Что произошло? Как надо было и как проверить перед запуском?

<details><summary>Ответ</summary>

Он поменял местами источник и приёмник: прочитал флешку и **перезаписал ей файл ISO**
(ISO уничтожен, флешка цела). Правильно: `sudo dd if=ubuntu.iso of=/dev/sdb bs=4M status=progress conv=fsync`.
Перед запуском: `lsblk`, `blkid`, убедиться в размере и что устройство размонтировано;
безопаснее использовать `sudo cp ubuntu.iso /dev/sdb` или специализированные утилиты.

</details>

**D6.** В контейнере приложению нужен доступ к `/dev/ttyUSB0`, но устройство после перезагрузки
сервера иногда становится `/dev/ttyUSB1`. Как сделать имя стабильным?

<details><summary>Ответ</summary>

Написать правило udev, привязанное к серийному номеру устройства:
```text:no-line-numbers
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", ATTRS{serial}=="A1B2C3", SYMLINK+="ttyDEVICE", MODE="0660", GROUP="dialout"
```
Затем `udevadm control --reload-rules && udevadm trigger`, а в контейнер пробрасывать
`--device=/dev/ttyDEVICE`. Атрибуты для правила смотреть через `udevadm info -a -n /dev/ttyUSB0`.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое `/dev/null` и где ты его используешь?

<details><summary>Ответ</summary>

Псевдоустройство-«чёрная дыра»: всё записанное отбрасывается. Использую для подавления вывода
(`cmd > /dev/null 2>&1`) в cron-задачах, health-check и скриптах.

</details>

**2.** Чем блочное устройство отличается от символьного?

<details><summary>Ответ</summary>

Блочное — произвольный доступ порциями (диски), символьное — потоковый последовательный доступ
(терминалы, `/dev/null`, генераторы случайных чисел).

</details>

**3.** Почему в fstab указывают UUID, а не `/dev/sdb1`?

<details><summary>Ответ</summary>

Потому что имена `/dev/sdX` зависят от порядка обнаружения устройств и могут меняться при
добавлении диска или перезагрузке; UUID привязан к файловой системе и стабилен.

</details>

**4.** Что делает udev?

<details><summary>Ответ</summary>

Обрабатывает события ядра об устройствах: создаёт файлы в `/dev`, задаёт имена, права и владельца,
создаёт стабильные симлинки, может запускать команды при подключении.

</details>

**5.** Как понять, SSD у тебя или HDD?

<details><summary>Ответ</summary>

`cat /sys/block/<dev>/queue/rotational` (0 = SSD), `lsblk -d -o NAME,ROTA,MODEL`, `smartctl -i`.

</details>

**6.** Как записать образ на флешку из командной строки?

<details><summary>Ответ</summary>

`sudo dd if=image.iso of=/dev/sdX bs=4M status=progress conv=fsync` — предварительно проверив
устройство через `lsblk` и размонтировав его.

</details>

**7.** Как узнать, какой драйвер обслуживает сетевую карту?

<details><summary>Ответ</summary>

`lspci -nnk | grep -A3 -i ethernet` или `ethtool -i eth0`, также `/sys/class/net/eth0/device/driver`.

</details>

**8.** Как проверить, открыт ли порт, если на сервере нет `nc` и `telnet`?

<details><summary>Ответ</summary>

Средствами bash: `timeout 2 bash -c '</dev/tcp/HOST/PORT' && echo open`. Ещё варианты —
`ss -tulpn` (локальные порты), `curl -v telnet://host:port`, `/dev/udp/...` для UDP.

</details>

---

### 🎯 Чек-лист

- [ ] `lsblk -f` и `blkid` — на автомате
- [ ] Знаю, почему fstab пишут по UUID
- [ ] Различаю блочные/символьные, помню, что у сетевых карт файла нет
- [ ] Понимаю, что делает udev и где лежат правила
- [ ] Сделал loop-диск с ФС от начала до конца
- [ ] Умею пользоваться `dd` и знаю его правила безопасности
- [ ] Смотрю `dmesg -T` при любой проблеме с железом
