---
title: "12. Ядро Linux"
description: "User space vs kernel space, системные вызовы, strace, модули ядра, sysctl — конспект и задачи"
---

# 12. Kernel — ядро Linux

> Источник: `12_kernel.txt` (Journeyman, 6 уроков)
> **После темы ты умеешь:** объяснить user space vs kernel space, понимать системные вызовы,
> управлять модулями ядра и крутить параметры через `sysctl`.

---

## 🗺️ Схема: два мира — user space и kernel space

```text:no-line-numbers
┌─────────────────────────────────────────────────────────────────────┐
│  USER SPACE (кольцо 3, ограниченные права)                          │
│                                                                     │
│   nginx    python    bash    systemd    твой код                    │
│     │        │         │        │           │                       │
│     └────────┴─────────┴────────┴───────────┘                       │
│                       │                                             │
│                  glibc / libc  (обёртки над syscalls)               │
└───────────────────────┼─────────────────────────────────────────────┘
                        │  SYSTEM CALL  (единственная легальная дверь)
             ═══════════╪═══════════════  ГРАНИЦА ПРИВИЛЕГИЙ  ═══════
                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  KERNEL SPACE (кольцо 0, полный доступ)                             │
│                                                                     │
│  ┌────────────┬────────────┬───────────┬────────────┬────────────┐  │
│  │ Планировщик│  Управление│ Файловые  │  Сетевой   │  Драйверы  │  │
│  │    CPU     │   памятью  │  системы  │    стек    │ устройств  │  │
│  └────────────┴────────────┴───────────┴────────────┴────────────┘  │
└───────────────────────┬─────────────────────────────────────────────┘
                        ▼
                     ЖЕЛЕЗО
```

**Почему так:** приложение не может напрямую писать в память другого процесса, читать диск или
слать пакеты — иначе любая программа (или баг) уронила бы систему. Всё идёт через ядро,
которое проверяет права и изолирует процессы.

---

## 1. Overview of the Kernel — что делает ядро

| Подсистема | Ответственность |
|-----------|-----------------|
| **Планировщик (scheduler)** | Кто и когда получает CPU (CFS/EEVDF, приоритеты, cgroups) |
| **Управление памятью** | Виртуальная память, страницы, swap, OOM killer |
| **Файловые системы (VFS)** | Единый интерфейс поверх ext4/XFS/NFS/overlay |
| **Сетевой стек** | TCP/IP, маршрутизация, netfilter/iptables |
| **Драйверы устройств** | Работа с конкретным железом |
| **Безопасность** | UID/GID, capabilities, SELinux/AppArmor, seccomp |
| **IPC** | Каналы, сигналы, сокеты, разделяемая память |

Типы ядер (спрашивают на собеседованиях):

| Тип | Суть | Примеры |
|-----|------|---------|
| **Монолитное** | Всё в одном адресном пространстве ядра, быстро | Linux (**модульное** монолитное) |
| **Микроядро** | Минимум в ядре, драйверы в user space, надёжно, но медленнее | Minix, QNX, Hurd |
| **Гибридное** | Компромисс | Windows NT, XNU (macOS) |

Linux — **модульное монолитное**: код в одном пространстве, но драйверы можно догружать
и выгружать на лету как модули (`.ko`). Это даёт скорость монолита и гибкость микроядра.

---

## 2. Privilege Levels — кольца защиты

x86 имеет 4 кольца (ring 0-3); Linux использует два:

```text:no-line-numbers
 ┌───────────────────────────────────────┐
 │ Ring 0 — KERNEL MODE                  │  полный доступ к железу и памяти
 │   ядро, драйверы, модули              │  краш здесь = kernel panic
 ├───────────────────────────────────────┤
 │ Ring 3 — USER MODE                    │  ограниченный доступ
 │   все обычные программы               │  краш здесь = падает только процесс
 └───────────────────────────────────────┘
```

Отсюда следствия:
- **Segfault** приложения не роняет систему — это ring 3.
- **Kernel panic** (или oops) роняет всё — это ring 0. Поэтому баг в драйвере опаснее бага в приложении.
- Гипервизоры используют ring -1 (VT-x/AMD-V) — отсюда и работает виртуализация.

```bash
# Сколько времени процессы проводят в каждом режиме
top     # колонки us (user) и sy (system)
vmstat 1
time ./program     # real / user / sys — вот эти sys и есть время в ядре
```

Высокий `sy` (system time) = приложение делает много системных вызовов
(часто — мелкие read/write без буферизации, много fork, интенсивный I/O).

---

## 3. System Calls — системные вызовы

Syscall — единственный способ попросить ядро сделать что-то за тебя.

Основные группы:

| Группа | Примеры |
|--------|---------|
| Файлы | `open`, `openat`, `read`, `write`, `close`, `stat`, `unlink` |
| Процессы | `fork`, `clone`, `execve`, `exit`, `wait4`, `kill` |
| Память | `mmap`, `munmap`, `brk`, `mprotect` |
| Сеть | `socket`, `bind`, `listen`, `accept`, `connect`, `sendto` |
| Время | `clock_gettime`, `nanosleep` |
| IPC | `pipe`, `shmget`, `futex` |

```bash
man 2 open              # документация syscall (секция 2!)
man syscalls            # список всех
ausyscall --dump | head # номера syscall (пакет auditd)
```

### strace — увидеть syscalls своими глазами

```bash
sudo apt install -y strace

strace ls                              # все вызовы
strace -c ls                           # СВОДКА: сколько раз и сколько времени ← самое полезное
strace -e trace=openat,read ls         # только определённые
strace -f -p 1234                      # прицепиться к процессу и его потокам
strace -T -e trace=network curl -s example.com   # + время каждого вызова
strace -o /tmp/trace.log -f ./app      # в файл
```

💼 Реальный кейс: приложение стартует и падает с непонятной ошибкой →
`strace -f ./app 2>&1 | tail -50` покажет, какой файл оно не смогло открыть (`ENOENT`)
или куда не хватило прав (`EACCES`). Это часто быстрее чтения логов.

Родственные инструменты: `ltrace` (вызовы библиотек), `perf` (профилирование),
`bpftrace`/`eBPF` (современная трассировка без остановки процессов).

⚠️ `strace` **сильно замедляет** процесс (каждый syscall перехватывается) — на проде применять
точечно и недолго.

---

## 4-5. Kernel Installation и Location

```text:no-line-numbers
/boot/
├── vmlinuz-5.15.0-91-generic     ← само ядро (сжатое)
├── initrd.img-5.15.0-91-generic  ← initramfs
├── config-5.15.0-91-generic      ← с какими опциями собрано
└── System.map-5.15.0-91-generic  ← адреса символов ядра

/lib/modules/5.15.0-91-generic/   ← МОДУЛИ для этой версии ядра
/usr/src/                         ← исходники/заголовки (для сборки модулей, DKMS)
/proc/sys/                        ← параметры ядра в реальном времени (sysctl)
/sys/                             ← модель устройств
```

```bash
uname -r                                    # текущее ядро
uname -a
cat /proc/version
dpkg -l | grep linux-image                  # установленные ядра (Debian)
ls /boot/vmlinuz-*

# Обновление ядра
sudo apt update && sudo apt install linux-generic     # или конкретную версию
sudo apt install linux-image-5.15.0-92-generic
sudo reboot                                  # ядро применяется ТОЛЬКО после перезагрузки

# Удаление старых ядер (осторожно! оставь минимум одно запасное)
sudo apt autoremove --purge
dpkg -l 'linux-image-*' | grep '^ii'
```

Разбор версии `5.15.0-91-generic`:
- `5.15.0` — upstream-версия ядра;
- `-91` — сборка Ubuntu (бэкпорты патчей);
- `generic` — вариант (бывают `-aws`, `-azure`, `-kvm`, `-lowlatency`, `-realtime`).

**LTS-ядра** поддерживаются годами (5.15, 6.1, 6.6) — именно они и едут в серверные дистрибутивы.

Сборка своего ядра нужна редко (специфичное железо, патчи, встраиваемые системы):
`make menuconfig` → `make -j$(nproc)` → `make modules_install` → `make install` → `update-grub`.
На практике в 99% случаев берут готовое ядро дистрибутива.

💡 Обновление ядра требует перезагрузки. Альтернатива для «безостановочных» систем —
live patching: Ubuntu Livepatch, kpatch (RHEL) — накатывают security-патчи без ребута.

---

## 6. Kernel Modules — модули

Модуль (`.ko`, kernel object) — код, который можно загрузить в ядро на лету:
драйверы, файловые системы, сетевые протоколы.

```bash
lsmod                              # загруженные модули (читает /proc/modules)
lsmod | grep kvm
modinfo ext4                       # информация о модуле: описание, параметры, зависимости
modinfo -p e1000                   # какие параметры принимает

sudo modprobe nf_conntrack         # загрузить модуль (+ зависимости) ← ПРАВИЛЬНЫЙ способ
sudo modprobe -r nf_conntrack      # выгрузить
sudo insmod /path/module.ko        # загрузить конкретный файл БЕЗ зависимостей (редко)
sudo rmmod module                  # выгрузить (тоже без учёта зависимостей)

# Автозагрузка при старте
echo "br_netfilter" | sudo tee /etc/modules-load.d/k8s.conf

# Параметры модуля
cat /sys/module/<module>/parameters/<param>
echo "options e1000 debug=1" | sudo tee /etc/modprobe.d/e1000.conf

# Запретить загрузку модуля (hardening)
echo "blacklist usb_storage" | sudo tee /etc/modprobe.d/blacklist-usb.conf
sudo update-initramfs -u
```

💼 Где это реально нужно DevOps:
- Kubernetes требует модули `br_netfilter`, `overlay`, `nf_conntrack` — их прописывают в
  `/etc/modules-load.d/` при подготовке ноды.
- VPN/сеть: `wireguard`, `tun`, `ip_vs` (для IPVS-режима kube-proxy).
- Хранилища: `nfs`, `ceph`, `dm_crypt`.
- Hardening: blacklist ненужных модулей (firewire, usb-storage) по CIS Benchmark.

---

## 7. sysctl — настройка ядра на лету

`/proc/sys/` — параметры ядра в виде файлов. `sysctl` — удобный интерфейс к ним.

```bash
sysctl -a | head -30                       # все параметры (их тысячи)
sysctl net.ipv4.ip_forward                 # прочитать
sudo sysctl -w net.ipv4.ip_forward=1       # изменить ДО перезагрузки
echo 1 | sudo tee /proc/sys/net/ipv4/ip_forward   # то же самое напрямую

# ПОСТОЯННО
echo 'net.ipv4.ip_forward=1' | sudo tee /etc/sysctl.d/99-custom.conf
sudo sysctl --system                       # применить все файлы
sudo sysctl -p /etc/sysctl.d/99-custom.conf
```

Параметры, которые реально крутят в проде:

```bash
# Сеть
net.ipv4.ip_forward=1                      # маршрутизация (Docker/k8s включают сами)
net.core.somaxconn=65535                   # длина очереди соединений (highload)
net.ipv4.tcp_max_syn_backlog=65535
net.ipv4.tcp_tw_reuse=1                    # переиспользование TIME_WAIT
net.ipv4.ip_local_port_range="10240 65535" # диапазон исходящих портов
net.netfilter.nf_conntrack_max=524288      # таблица соединений (NAT)

# Память
vm.swappiness=10                           # реже свопить
vm.max_map_count=262144                    # требуется Elasticsearch
vm.overcommit_memory=1                     # требуется Redis

# Файлы
fs.file-max=2097152                        # максимум открытых файлов в системе
fs.inotify.max_user_watches=524288         # для файловых вотчеров (k8s, IDE)

# Безопасность
kernel.randomize_va_space=2                # ASLR
net.ipv4.conf.all.rp_filter=1              # защита от спуфинга
kernel.dmesg_restrict=1                    # dmesg только для root
```

⚠️ Разница между `sysctl -w` (до перезагрузки) и файлом в `/etc/sysctl.d/` (постоянно) —
частая причина «после ребута всё сломалось опять».

**ulimit** — лимиты на процесс (родственная тема):
```bash
ulimit -a                        # все лимиты текущего шелла
ulimit -n                        # максимум открытых файлов
ulimit -n 65535                  # изменить (в пределах hard limit)
cat /proc/<pid>/limits           # лимиты конкретного процесса
```
Постоянно — в `/etc/security/limits.conf` или (для сервисов) `LimitNOFILE=` в systemd-юните.
Классический инцидент: `Too many open files` под нагрузкой.

---

## 💼 Как это в DevOps

- **Тюнинг под нагрузку:** `somaxconn`, `file-max`, `nf_conntrack_max`, `LimitNOFILE` —
  типовые правки для highload-сервисов.
- **Подготовка ноды Kubernetes:** модули `overlay`/`br_netfilter` + sysctl
  `net.bridge.bridge-nf-call-iptables=1`, `net.ipv4.ip_forward=1` — без них кластер не заработает.
- **Контейнеры — это ядро:** namespaces (изоляция) + cgroups (лимиты) + capabilities + seccomp.
  Контейнер разделяет ядро с хостом, поэтому его уязвимости — общие.
- **Отладка:** `strace` для «почему не стартует», `dmesg`/`journalctl -k` для железа и OOM.
- **CVE ядра** → обновление ядра → перезагрузка (или livepatch). Это регулярная операционная задача.

---

## 🧪 Мини-лаба

```bash
vagrant ssh

# 1. Разведка ядра
uname -a; uname -r
cat /proc/version
ls -lh /boot/vmlinuz-* /boot/initrd.img-*
dpkg -l | grep -c linux-image

# 2. Параметры сборки текущего ядра
grep -E 'CONFIG_EXT4_FS=|CONFIG_OVERLAY_FS=|CONFIG_BRIDGE=' /boot/config-$(uname -r)

# 3. Модули
lsmod | head -20
lsmod | wc -l
modinfo ext4 | head
sudo modprobe dummy && lsmod | grep dummy
sudo modprobe -r dummy && lsmod | grep dummy || echo "выгружен"

# 4. Системные вызовы
sudo apt install -y strace
strace -c ls /etc > /dev/null
strace -e trace=openat ls /etc 2>&1 | head -20
echo "test" > /tmp/t.txt
strace -e trace=openat,read,write,close cat /tmp/t.txt 2>&1 | tail -15

# 5. Что происходит при ошибке доступа
strace -e trace=openat cat /etc/shadow 2>&1 | grep shadow    # увидишь EACCES

# 6. sysctl
sysctl -a 2>/dev/null | wc -l
sysctl net.ipv4.ip_forward vm.swappiness fs.file-max
sudo sysctl -w vm.swappiness=10
cat /proc/sys/vm/swappiness
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-lab.conf
sudo sysctl --system | tail -5

# 7. Лимиты
ulimit -a
ulimit -n
cat /proc/self/limits | head

# 8. Время в user vs kernel
time dd if=/dev/zero of=/tmp/x bs=1k count=100000 2>/dev/null   # много sys
time bash -c 'for i in $(seq 1 200000); do :; done'             # много user
rm -f /tmp/x

# 9. Сообщения ядра
dmesg -T | tail -20
journalctl -k -b | tail -20

# Уборка
sudo rm -f /etc/sysctl.d/99-lab.conf
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `uname -r` / `cat /proc/version` | Версия ядра |
| `lsmod` / `modinfo X` | Загруженные модули / информация |
| `modprobe X` / `modprobe -r X` | Загрузить / выгрузить модуль |
| `/etc/modules-load.d/*.conf` | Автозагрузка модулей |
| `/etc/modprobe.d/*.conf` | Параметры и blacklist |
| `sysctl -a` / `sysctl -w k=v` | Параметры ядра: показать / изменить |
| `/etc/sysctl.d/99-x.conf` + `sysctl --system` | Постоянные параметры |
| `strace -c cmd` | Сводка системных вызовов |
| `strace -f -p PID` | Трассировка живого процесса |
| `ulimit -a` / `/proc/PID/limits` | Лимиты |
| `dmesg -T` / `journalctl -k` | Сообщения ядра |
| `grep X /boot/config-$(uname -r)` | С какими опциями собрано ядро |

---

## 🧠 Что запомнить

1. Два мира: **user space (ring 3)** и **kernel space (ring 0)**; единственная дверь между ними —
   **системный вызов**.
2. Падение приложения = segfault (умирает процесс); падение ядра = kernel panic (умирает всё).
3. Linux — **модульное монолитное** ядро: драйверы можно догружать на лету (`.ko`).
4. `strace -c` / `strace -f` — быстрый способ понять, почему приложение не работает.
5. `sysctl -w` — до перезагрузки; `/etc/sysctl.d/*.conf` + `sysctl --system` — навсегда.
6. Модули: `modprobe` (с зависимостями) вместо `insmod`; автозагрузка — `/etc/modules-load.d/`.
7. Обновление ядра требует **перезагрузки** (или livepatch).
8. `ulimit -n` / `LimitNOFILE` — лечение `Too many open files`.
9. Контейнеры — это namespaces + cgroups + seccomp, то есть **фичи ядра**, а не виртуализация.

➡️ Дальше: [13. Init](/linux/13-init) — systemd, самая практичная тема Journeyman.

---

## Задачи

> `vagrant snapshot save before_12 && vagrant ssh`
> Понадобится: `sudo apt install -y strace`

---

### Блок A. Теория

**A1.** Что такое user space и kernel space? Почему нужна эта граница?

<details><summary>Ответ</summary>

User space — пространство, где работают обычные программы с ограниченными правами;
kernel space — привилегированное пространство ядра с полным доступом к железу и памяти.
Граница нужна для изоляции: баг или вредоносный код в приложении не может напрямую повредить
систему или другие процессы; все привилегированные операции проходят через контролируемый
интерфейс системных вызовов.

</details>

**A2.** Что такое кольца защиты? Какие использует Linux и почему только два?

<details><summary>Ответ</summary>

Аппаратные уровни привилегий CPU (x86: ring 0-3). Linux использует ring 0 (ядро) и
ring 3 (приложения), потому что промежуточные кольца не поддерживаются одинаково на всех
архитектурах, а двух уровней достаточно для модели «ядро/пользователь» — это упрощает и
ускоряет ядро и делает его переносимым.

</details>

**A3.** Почему падение приложения не роняет систему, а падение драйвера — роняет?

<details><summary>Ответ</summary>

Приложение работает в ring 3, его память изолирована; при обращении к чужой памяти ядро
шлёт SIGSEGV и завершает только этот процесс. Драйвер/модуль работает в ring 0 с полным доступом:
повреждение структур ядра приводит к panic/oops, и восстановить согласованность невозможно.

</details>

**A4.** Что такое системный вызов? Назови 5 из разных групп.

<details><summary>Ответ</summary>

Запрос от программы к ядру на привилегированную операцию через специальный механизм
(инструкция `syscall`). Примеры: `openat` (файлы), `clone`/`execve` (процессы), `mmap` (память),
`socket`/`connect` (сеть), `clock_gettime` (время).

</details>

**A5.** Что происходит при выполнении `cat file.txt` на уровне syscalls (укажи 4-5 ключевых вызовов)?

<details><summary>Ответ</summary>

Примерно: `execve("/bin/cat")` → `openat("file.txt", O_RDONLY)` → `fstat()` →
цикл `read()`/`write(1, ...)` → `close()` → `exit_group()`. Плюс вначале несколько `openat`
на загрузку `ld.so` и `libc`.

</details>

**A6.** Чем монолитное ядро отличается от микроядра? К какому типу относится Linux и почему
его называют «модульным монолитным»?

<details><summary>Ответ</summary>

Монолитное — все подсистемы (планировщик, ФС, сеть, драйверы) исполняются в одном
адресном пространстве ядра: быстро, но сбой в любой части фатален. Микроядро — в ядре только
минимум (IPC, планирование), остальное в user space: надёжнее и изолированнее, но медленнее
из-за переключений контекста. Linux — монолитное, но **модульное**: код можно динамически
загружать/выгружать в виде `.ko`, не пересобирая ядро.

</details>

**A7.** Что означает высокий показатель `sy` (system time) в `top`? Что обычно за этим стоит?

<details><summary>Ответ</summary>

Процессы много времени проводят внутри ядра. Причины: интенсивный ввод-вывод, огромное
число мелких `read/write` без буферизации, частые `fork/exec`, активная работа с сетью, много
переключений контекста, контекстные блокировки. Диагностика: `strace -c`, `perf top`, `vmstat 1`.

</details>

**A8.** Что такое модуль ядра? Чем `modprobe` лучше `insmod`?

<details><summary>Ответ</summary>

Модуль — объектный файл `.ko` с кодом, выполняющимся в ядре (драйвер, ФС, протокол).
`modprobe` находит модуль по имени в `/lib/modules/$(uname -r)`, автоматически подгружает
**зависимости** и учитывает настройки `/etc/modprobe.d/`; `insmod` принимает конкретный путь
и ничего о зависимостях не знает.

</details>

**A9.** Где лежат модули текущего ядра? Как сделать так, чтобы модуль загружался при старте?

<details><summary>Ответ</summary>

`/lib/modules/$(uname -r)/`. Автозагрузка: файл в `/etc/modules-load.d/имя.conf`
с именем модуля в строке (или запись в `/etc/modules`). Параметры — в `/etc/modprobe.d/*.conf`.

</details>

**A10.** Чем `sysctl -w` отличается от записи в `/etc/sysctl.d/`?

<details><summary>Ответ</summary>

`sysctl -w` меняет значение в работающем ядре и теряется при перезагрузке;
файл в `/etc/sysctl.d/*.conf` применяется при каждой загрузке (и по команде `sysctl --system`),
то есть сохраняется постоянно. Правильная практика — делать оба действия.

</details>

**A11.** Что такое `ulimit -n` и какую ошибку он вызывает при исчерпании?

<details><summary>Ответ</summary>

Максимальное число открытых файловых дескрипторов на процесс. При исчерпании системные
вызовы возвращают `EMFILE`, что проявляется как `Too many open files` — сервис перестаёт принимать
соединения (каждый сокет — тоже дескриптор).

</details>

**A12.** Почему обновление ядра требует перезагрузки? Какая есть альтернатива?

<details><summary>Ответ</summary>

Ядро загружается в память один раз при старте, заменить его на лету нельзя: меняются
структуры данных, ABI модулей, код. Альтернатива — live patching (Ubuntu Livepatch, kpatch),
который накладывает ограниченные security-патчи на работающее ядро без перезагрузки.

</details>

**A13.** Разбери `5.15.0-91-generic` по частям.

<details><summary>Ответ</summary>

`5` major, `15` minor, `0` patchlevel (upstream-версия); `-91` — номер сборки дистрибутива
с бэкпортами; `generic` — вариант сборки (бывают `aws`, `kvm`, `lowlatency`, `realtime`).

</details>

**A14.** Контейнер — это виртуальная машина? Какие возможности ядра лежат в основе контейнеров?

<details><summary>Ответ</summary>

Нет. ВМ имеет собственное ядро и виртуальное железо (гипервизор), контейнер **разделяет
ядро с хостом**. В основе контейнеров — возможности ядра: **namespaces** (изоляция PID, сети,
точек монтирования, users), **cgroups** (лимиты CPU/памяти/IO), capabilities, seccomp, LSM
(AppArmor/SELinux), overlayfs. Отсюда и следствие: уязвимость ядра — общая для всех контейнеров хоста.

</details>

---

### Блок B. «Что делает / что покажет»

```bash
B1.  uname -r
B2.  lsmod | wc -l
B3.  modinfo overlay
B4.  sudo modprobe br_netfilter
B5.  sysctl net.ipv4.ip_forward
B6.  sudo sysctl -w vm.swappiness=10
B7.  sudo sysctl --system
B8.  strace -c ls /etc
B9.  strace -e trace=openat cat /etc/hostname
B10. strace -f -p 1234
B11. cat /proc/self/limits
B12. grep CONFIG_OVERLAY_FS /boot/config-$(uname -r)
B13. dmesg -T | grep -i "out of memory"
B14. echo "br_netfilter" | sudo tee /etc/modules-load.d/k8s.conf
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Версия работающего ядра.
B2.  Количество загруженных модулей.
B3.  Информация о модуле overlay: описание, зависимости, параметры, лицензия.
B4.  Загружает модуль bridge netfilter (нужен для Kubernetes/Docker).
B5.  Показывает текущее значение параметра (0 — маршрутизация выключена).
B6.  Меняет swappiness до перезагрузки.
B7.  Применяет все файлы из /etc/sysctl.d/, /run/sysctl.d/, /etc/sysctl.conf.
B8.  Сводная статистика системных вызовов: количество, ошибки, затраченное время.
B9.  Показывает все openat, то есть какие файлы пытается открыть команда.
B10. Трассирует живой процесс 1234 и его потоки/дочерние процессы.
B11. Лимиты текущего процесса (nofile, nproc, stack и др.).
B12. Проверяет, собрано ли ядро с поддержкой overlayfs (=y встроено, =m модулем).
B13. Ищет в сообщениях ядра срабатывания OOM killer.
B14. Настраивает автозагрузку модуля при старте системы.
```

</details>

**B15.** Чем `/proc/sys/net/ipv4/ip_forward` отличается от `sysctl net.ipv4.ip_forward`?

<details><summary>Ответ</summary>

Это один и тот же параметр: `/proc/sys/...` — файловый интерфейс, `sysctl` — утилита,
которая читает/пишет те же файлы, но принимает имена через точку и умеет применять файлы
конфигурации. Разница только в удобстве и в том, что `sysctl --system` умеет массово применять
настройки.

</details>

---

### Блок C. Практика

#### C1. Паспорт ядра

Собери:
- версию ядра и архитектуру;
- сколько ядер установлено в системе;
- количество загруженных модулей;
- включена ли поддержка overlayfs, ext4, bridge (из `/boot/config-*`);
- размер файла ядра и initramfs.

<details><summary>Ответ</summary>

```bash
uname -r; uname -m
ls /boot/vmlinuz-* | wc -l
lsmod | tail -n +2 | wc -l
grep -E 'CONFIG_OVERLAY_FS=|CONFIG_EXT4_FS=|CONFIG_BRIDGE=' /boot/config-$(uname -r)
ls -lh /boot/vmlinuz-$(uname -r) /boot/initrd.img-$(uname -r)
```

</details>

#### C2. strace — базовое исследование

1. Запусти `strace -c ls /etc` и определи три самых частых системных вызова.
2. Через `strace` найди **все** файлы, которые открывает `cat /etc/hostname`.
3. Через `strace` определи, какие конфигурационные файлы читает `bash` при старте
   (подсказка: `strace -f -e trace=openat bash -lc exit 2>&1 | grep -v ENOENT`).

<details><summary>Ответ</summary>

```bash
strace -c ls /etc 2>&1 | head -15
strace -e trace=openat cat /etc/hostname 2>&1 | grep -v ENOENT
strace -f -e trace=openat bash -lc exit 2>&1 | grep -v ENOENT | grep -E 'bashrc|profile'
```

</details>

#### C3. strace — диагностика ошибок (ключевое упражнение)

1. Создай файл, забери у него права чтения, попробуй прочитать под `nobody` через strace —
   найди конкретный syscall и код ошибки.
2. Попробуй прочитать несуществующий файл — какой код ошибки вернётся?
3. Сформулируй: как по выводу strace за 10 секунд понять, почему приложение не стартует?

<details><summary>Ответ</summary>

```bash
echo secret | sudo tee /tmp/nope.txt >/dev/null && sudo chmod 600 /tmp/nope.txt
sudo -u nobody strace -e trace=openat cat /tmp/nope.txt 2>&1 | grep nope
#   openat(AT_FDCWD, "/tmp/nope.txt", O_RDONLY) = -1 EACCES (Permission denied)
strace -e trace=openat cat /tmp/missing.txt 2>&1 | grep missing
#   = -1 ENOENT (No such file or directory)
```

Метод: `strace -f ./app 2>&1 | grep -E 'ENOENT|EACCES|ECONNREFUSED' | tail -20` — почти всегда
сразу видно отсутствующий файл, нехватку прав или недоступный сокет/порт.

</details>

#### C4. Модули

1. Выведи 10 модулей с наибольшим числом использующих их модулей (колонка `Used by`).
2. Загрузи модуль `dummy`, убедись, что появился сетевой интерфейс, выгрузи его.
3. Посмотри параметры какого-нибудь модуля через `modinfo -p`.
4. Настрой автозагрузку модуля `br_netfilter` при старте системы и проверь конфигурацию.
5. Забанируй (blacklist) модуль `usb_storage` и объясни, зачем это делают.

<details><summary>Ответ</summary>

```bash
lsmod | sort -k3 -rn | head -10
sudo modprobe dummy && ip link show | grep dummy
sudo modprobe -r dummy
modinfo -p e1000 2>/dev/null || modinfo -p dummy
echo br_netfilter | sudo tee /etc/modules-load.d/k8s.conf
sudo systemctl restart systemd-modules-load && lsmod | grep br_netfilter
echo "blacklist usb_storage" | sudo tee /etc/modprobe.d/blacklist-usb.conf
```

Blacklist делают для hardening: физически подключённая флешка не будет автоматически
распознана и смонтирована — снижает риск утечки данных и загрузки вредоносного кода
(типовой пункт CIS Benchmark).

</details>

#### C5. sysctl-тюнинг

Настрой ноду «как под Kubernetes»:
```text:no-line-numbers
net.ipv4.ip_forward = 1
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
```
Сделай это **постоянно**, применив без перезагрузки. Убедись, что параметры применились.
Затем откати изменения.

<details><summary>Ответ</summary>

```bash
cat <<'EOF' | sudo tee /etc/sysctl.d/99-k8s.conf
net.ipv4.ip_forward = 1
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
EOF
sudo modprobe br_netfilter
sudo sysctl --system
sysctl net.ipv4.ip_forward net.bridge.bridge-nf-call-iptables
sudo rm /etc/sysctl.d/99-k8s.conf && sudo sysctl --system >/dev/null
```

</details>

#### C6. sysctl под highload

Найди текущие значения и увеличь:
- `net.core.somaxconn`;
- `fs.file-max`;
- `net.ipv4.ip_local_port_range`;
- `fs.inotify.max_user_watches`.

Объясни своими словами, на что влияет каждый параметр.

<details><summary>Ответ</summary>

```bash
sysctl net.core.somaxconn fs.file-max net.ipv4.ip_local_port_range fs.inotify.max_user_watches
sudo sysctl -w net.core.somaxconn=65535
sudo sysctl -w fs.file-max=2097152
sudo sysctl -w net.ipv4.ip_local_port_range="10240 65535"
sudo sysctl -w fs.inotify.max_user_watches=524288
```

`somaxconn` — максимальная длина очереди установленных, но ещё не принятых `accept()`
соединений; при нехватке клиенты получают отказы под всплеском нагрузки.
`fs.file-max` — общесистемный лимит открытых файлов.
`ip_local_port_range` — диапазон эфемерных портов для исходящих соединений; узкий диапазон
приводит к исчерпанию портов на прокси/балансировщике.
`inotify.max_user_watches` — сколько файлов можно «наблюдать»; упирается в это kubelet, IDE, watchers.

</details>

#### C7. Лимиты

1. Посмотри текущий `ulimit -n` и hard limit.
2. Подними soft limit до hard limit в текущей сессии.
3. Сделай лимит 65535 постоянным для пользователя `vagrant` через `/etc/security/limits.conf`.
4. Покажи, как задать лимит для systemd-сервиса (напиши фрагмент юнита).
5. Проверь лимиты работающего процесса через `/proc`.

<details><summary>Ответ</summary>

```bash
ulimit -n; ulimit -Hn
ulimit -n "$(ulimit -Hn)"
cat <<'EOF' | sudo tee -a /etc/security/limits.conf
vagrant soft nofile 65535
vagrant hard nofile 65535
EOF
# для systemd-сервиса (limits.conf на сервисы НЕ действует!):
#   [Service]
#   LimitNOFILE=65535
cat /proc/$$/limits | grep -i "open files"
```

</details>

#### C8. User vs kernel time

Напиши два скрипта: один нагружает CPU вычислениями,
другой — интенсивным I/O. Измерь оба через `time` и объясни разницу в `user` и `sys`.

<details><summary>Ответ</summary>

```bash
cat > /tmp/cpu.sh <<'EOF'
#!/bin/bash
s=0; for ((i=0;i<3000000;i++)); do ((s+=i)); done; echo $s
EOF
cat > /tmp/io.sh <<'EOF'
#!/bin/bash
for i in $(seq 1 20000); do echo "line $i" >> /tmp/io_test.txt; done
rm -f /tmp/io_test.txt
EOF
chmod +x /tmp/cpu.sh /tmp/io.sh
time /tmp/cpu.sh     # большой user, маленький sys
time /tmp/io.sh      # заметно больший sys — время в ядре на write/openat
```

</details>

#### C9. Скрипт kernel-аудита

Напиши `/vagrant/kernel_report.sh`:
```text:no-line-numbers
=== KERNEL REPORT ===
Version: 5.15.0-91-generic (x86_64)
Installed kernels: 2
Uptime: 3 days
Loaded modules: 98
Key sysctl:
  net.ipv4.ip_forward = 0
  vm.swappiness = 60
  fs.file-max = 9223372036854775807
Limits: nofile soft=1024 hard=1048576
Recent kernel errors: 0
Modules loaded at boot: br_netfilter
```

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
echo "=== KERNEL REPORT ==="
echo "Version: $(uname -r) ($(uname -m))"
echo "Installed kernels: $(ls /boot/vmlinuz-* 2>/dev/null | wc -l)"
echo "Uptime: $(uptime -p)"
echo "Loaded modules: $(lsmod | tail -n +2 | wc -l)"
echo "Key sysctl:"
for k in net.ipv4.ip_forward vm.swappiness fs.file-max net.core.somaxconn; do
  printf '  %s = %s\n' "$k" "$(sysctl -n "$k" 2>/dev/null)"
done
echo "Limits: nofile soft=$(ulimit -Sn) hard=$(ulimit -Hn)"
echo "Recent kernel errors: $(journalctl -k -p err -b --no-pager -q | wc -l)"
echo "Modules loaded at boot: $(cat /etc/modules-load.d/*.conf 2>/dev/null | grep -v '^#' | paste -sd', ' || echo none)"
```

</details>

#### C10. Обновление ядра (безопасно)

Проверь, доступно ли обновление ядра
(`apt list --upgradable | grep linux-image`). Не устанавливая, опиши по шагам,
как ты бы обновлял ядро на проде: что проверить до, что после, как откатиться.

<details><summary>Ответ</summary>

Порядок обновления ядра на проде:
**До:** проверить доступные версии (`apt list --upgradable | grep linux-image`), убедиться в
наличии свободного места в `/boot`, снять снапшот/бэкап, проверить наличие как минимум одного
рабочего резервного ядра, узнать про DKMS-модули (драйверы NVIDIA, VirtualBox — пересобираются
под новое ядро), вывести ноду из балансировки, согласовать окно.
**Установка:** `apt install linux-image-<version> linux-headers-<version>`, `update-initramfs -u -k all`,
`update-grub`.
**После:** reboot → `uname -r` → `systemctl --failed` → `journalctl -b -p err` → проверить сервисы,
сеть, диски → вернуть в балансировку.
**Откат:** перезагрузиться, выбрать предыдущее ядро в меню GRUB, при необходимости зафиксировать
его (`GRUB_DEFAULT`) и удалить проблемное.

</details>

---

### Блок D. Инциденты

**D1.** Приложение падает при старте с `Exit code 1` и пустым логом. Как за 2 минуты
выяснить причину через `strace`?

<details><summary>Ответ</summary>

```bash
strace -f -o /tmp/tr.log ./app; tail -50 /tmp/tr.log
grep -E 'ENOENT|EACCES|ECONNREFUSED|EADDRINUSE' /tmp/tr.log | tail -20
```

Чаще всего сразу видно: не найден конфиг/библиотека (`ENOENT`), нет прав на файл или сокет
(`EACCES`), занят порт (`EADDRINUSE`), недоступна БД (`ECONNREFUSED`).

</details>

**D2.** Под нагрузкой в логах nginx: `socket() failed (24: Too many open files)`.
Что это, как починить срочно и как — правильно?

<details><summary>Ответ</summary>

Исчерпан лимит открытых дескрипторов рабочего процесса nginx.
**Срочно:** `prlimit --pid <pid> --nofile=65535:65535` (поднять на лету), затем перезапуск.
**Правильно:** в юните nginx `LimitNOFILE=65535` (drop-in
`/etc/systemd/system/nginx.service.d/limits.conf`), в `nginx.conf` — `worker_rlimit_nofile 65535;`
и адекватный `worker_connections`; проверить общесистемный `fs.file-max`. Заодно убедиться,
что нет утечки дескрипторов: `ls -l /proc/<pid>/fd | wc -l`, `lsof -p <pid> | wc -l`.

</details>

**D3.** На ноде Kubernetes поды не могут ходить в сеть друг к другу. Node описана как «свежая ВМ».
Какие два класса настроек ядра надо проверить в первую очередь?

<details><summary>Ответ</summary>

(1) Модули ядра: `overlay`, `br_netfilter` (и `ip_vs*`, если kube-proxy в режиме IPVS) —
прописать в `/etc/modules-load.d/`. (2) sysctl: `net.ipv4.ip_forward=1`,
`net.bridge.bridge-nf-call-iptables=1`, `net.bridge.bridge-nf-call-ip6tables=1` — в `/etc/sysctl.d/`.
Дополнительно: отключённый swap, корректный `nf_conntrack_max`, отсутствие конфликтующих
правил firewall.

</details>

**D4.** В `dmesg` регулярно появляется:
```text:no-line-numbers
nf_conntrack: table full, dropping packet
```
Что это значит и как лечить?

<details><summary>Ответ</summary>

Переполнена таблица отслеживания соединений netfilter — новые пакеты отбрасываются
(проявляется как случайные таймауты и обрывы). Лечение: увеличить
`net.netfilter.nf_conntrack_max` (и соответственно `nf_conntrack_buckets`), уменьшить таймауты
(`nf_conntrack_tcp_timeout_time_wait`), исключить лишний трафик из conntrack правилом `NOTRACK`,
проверить, нет ли DDoS/скан-трафика. Мониторить `nf_conntrack_count` против `max`.

</details>

**D5.** После перезагрузки сервер «забыл» настройку `net.ipv4.ip_forward=1`,
которую вчера включили, и маршрутизация перестала работать. Что сделали неправильно?

<details><summary>Ответ</summary>

Параметр изменили только командой `sysctl -w` (или записью в `/proc`), но не сохранили
в `/etc/sysctl.d/*.conf`. Настройка действовала до перезагрузки. Правильно — и применить на лету,
и записать в файл, а затем проверить `sudo sysctl --system`.

</details>

**D6.** Сервер внезапно перезагрузился, в логах предыдущей загрузки:
```text:no-line-numbers
Out of memory: Killed process 1234 (java) total-vm:8000000kB
```
Кто убил процесс, почему и какие есть варианты решения?

<details><summary>Ответ</summary>

Процесс убил **OOM killer** — подсистема ядра, освобождающая память, когда её не хватает.
Она выбирает жертву по `oom_score` (обычно самый «жирный» процесс). Варианты решения:
увеличить RAM; ограничить потребление приложения (для JVM — `-Xmx`, для контейнера — `limits`);
настроить cgroups/`MemoryMax` в systemd; добавить/настроить swap; понизить `oom_score_adj`
критичным процессам; устранить утечку памяти в приложении. Диагностика: `dmesg -T | grep -i oom`,
`journalctl -k -b -1`, метрики памяти на момент сбоя.

</details>

**D7.** После обновления ядра сервер не загружается, а сетевая карта «не определяется»
на новом ядре. Что делать сейчас и как предотвращать?

<details><summary>Ответ</summary>

Сейчас: загрузиться со старого ядра из меню GRUB (оно должно остаться), убедиться,
что сеть работает, и зафиксировать рабочее ядро. Затем разобраться: скорее всего, драйвер
собирался через DKMS и не пересобрался, или модуль отсутствует в новом ядре —
`dkms status`, `modinfo <driver>`, `update-initramfs -u -k <новое>`.
Предотвращение: тестировать обновление ядра на стенде/канарейке, держать резервное ядро,
иметь доступ к serial-консоли, снимать снапшот перед обновлением.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое системный вызов? Приведи примеры.

<details><summary>Ответ</summary>

Механизм обращения программы к ядру за привилегированной операцией: `open`, `read`, `write`,
`fork`, `execve`, `socket`, `mmap`. Смотреть — `strace`.

</details>

**2.** Чем user space отличается от kernel space?

<details><summary>Ответ</summary>

User space — ограниченный режим для приложений (ring 3); kernel space — привилегированный
режим ядра (ring 0) с прямым доступом к железу. Переход — только через syscall.

</details>

**3.** Как посмотреть, что делает зависший процесс?

<details><summary>Ответ</summary>

`strace -f -p PID` (что делает сейчас), `cat /proc/PID/stack`, `cat /proc/PID/wchan`,
`ls -l /proc/PID/fd`, `gdb -p PID` для стека приложения; для D-состояния — смотреть I/O.

</details>

**4.** Как изменить параметр ядра навсегда?

<details><summary>Ответ</summary>

Записать в файл `/etc/sysctl.d/99-name.conf` и применить `sudo sysctl --system`.

</details>

**5.** Что такое модуль ядра и как его загрузить?

<details><summary>Ответ</summary>

Код, подгружаемый в ядро на лету (драйвер, ФС, протокол). Загрузка — `modprobe <имя>`
(с зависимостями), автозагрузка — `/etc/modules-load.d/`.

</details>

**6.** Контейнер — это виртуалка? Объясни разницу.

<details><summary>Ответ</summary>

Нет: контейнер использует ядро хоста и изолирован средствами namespaces/cgroups, а ВМ имеет
собственное ядро поверх гипервизора. Отсюда: контейнеры легче и быстрее, но изоляция слабее.

</details>

**7.** Что делать при `Too many open files`?

<details><summary>Ответ</summary>

Поднять лимит (`LimitNOFILE` в юните, `limits.conf` для пользователя, `prlimit` на лету),
проверить `fs.file-max`, и обязательно убедиться, что нет утечки дескрипторов в приложении.

</details>

**8.** Как обновить ядро и нужна ли перезагрузка?

<details><summary>Ответ</summary>

`apt install linux-image-<version>` (или `linux-generic`), затем `update-initramfs`/`update-grub`
и **перезагрузка** — без неё новое ядро не применится. Без перезагрузки — только livepatch
для security-фиксов.

</details>

---

### 🎯 Чек-лист

- [ ] Объясняю границу user/kernel space и роль syscalls
- [ ] Умею читать `strace -c` и находить `ENOENT`/`EACCES`
- [ ] Управляю модулями через `modprobe` и настраиваю автозагрузку
- [ ] Знаю разницу `sysctl -w` и `/etc/sysctl.d/`
- [ ] Помню типовые sysctl для highload и Kubernetes
- [ ] Умею чинить `Too many open files` тремя способами
- [ ] Понимаю, что контейнер — это namespaces + cgroups, а не ВМ
