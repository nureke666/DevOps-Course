---
title: "11. Загрузка системы"
description: "GRUB, initramfs, systemd PID 1, сброс пароля root, диагностика незагружающегося сервера — конспект и задачи"
---

# 11. Boot the System — процесс загрузки

> Источник: `11_boot_the_system.txt` (Journeyman, 5 уроков)
> **После темы ты умеешь:** объяснить загрузку по шагам, работать с GRUB, сбросить пароль root
> и чинить незагружающийся сервер. Вопрос «что происходит при включении компьютера?» —
> классика собеседований.

---

## 🗺️ Схема: полный путь от кнопки до логина

```text:no-line-numbers
 ┌──────────────────────────────────────────────────────────────────────┐
 │ 1. POWER ON → прошивка (BIOS или UEFI)                               │
 │    · POST — самопроверка железа                                      │
 │    · инициализация CPU, RAM, контроллеров                            │
 │    · выбор загрузочного устройства по boot order                     │
 └────────────────────────────┬─────────────────────────────────────────┘
                              ▼
 ┌──────────────────────────────────────────────────────────────────────┐
 │ 2. BOOTLOADER (GRUB2)                                                │
 │    BIOS: MBR (512 б) → stage 1.5 → stage 2                           │
 │    UEFI: /boot/efi/EFI/ubuntu/grubx64.efi  (читается прямо с FAT32)  │
 │    · показывает меню                                                 │
 │    · грузит в память ЯДРО (vmlinuz) и INITRAMFS                      │
 │    · передаёт ядру параметры (root=UUID=... ro quiet splash)          │
 └────────────────────────────┬─────────────────────────────────────────┘
                              ▼
 ┌──────────────────────────────────────────────────────────────────────┐
 │ 3. KERNEL                                                            │
 │    · распаковывается, инициализирует память, CPU, планировщик        │
 │    · монтирует INITRAMFS как временный корень                        │
 │    · initramfs подгружает драйверы (RAID/LVM/шифрование/NVMe)         │
 │    · монтирует НАСТОЯЩИЙ корень, делает switch_root                  │
 └────────────────────────────┬─────────────────────────────────────────┘
                              ▼
 ┌──────────────────────────────────────────────────────────────────────┐
 │ 4. INIT — PID 1 (systemd)                                            │
 │    · достигает default.target (обычно graphical/multi-user)          │
 │    · запускает сервисы по зависимостям, параллельно                  │
 │    · монтирует остальное из /etc/fstab, поднимает сеть               │
 └────────────────────────────┬─────────────────────────────────────────┘
                              ▼
                   5. LOGIN (getty / SSH / дисплей-менеджер)
```

Мнемоника: **BIOS → Bootloader → Kernel → Init → Login** (или «БББКИЛ»).

---

## 1. Boot Process Overview

Ключевое, что нужно понимать:
- Каждый этап **находит и запускает следующий**, поэтому поломка любого звена даёт свой характерный симптом.
- initramfs существует потому, что ядро должно **как-то** прочитать корневую ФС, а для этого нужны
  драйверы, которые лежат… на корневой ФС. Разрыв этого круга — временный корень в памяти.

**Симптом → где искать:**

| Что видишь | Этап | Типичная причина |
|-----------|------|------------------|
| Чёрный экран, нет POST | BIOS/UEFI | Железо, память, boot order |
| `No bootable device` | Bootloader | Слетел MBR/EFI-раздел, неверный boot order |
| GRUB rescue> | Bootloader | Повреждён `/boot`, изменились разделы |
| `Kernel panic - not syncing: VFS: Unable to mount root fs` | Kernel | Неверный `root=`, нет драйвера, битый initramfs |
| Загрузка «висит» на сервисе | Init | Проблема с сервисом, ожидание сети или fstab |
| `emergency mode` / `Give root password` | Init | Ошибка в `/etc/fstab`, недоступная ФС |

---

## 2. BIOS и UEFI

| | BIOS (Legacy) | UEFI (современный) |
|---|---|---|
| Возраст | 1980-е | 2000-е+ |
| Таблица разделов | MBR | GPT |
| Размер диска | до 2 ТБ | практически без ограничений |
| Загрузчик | код в MBR (512 байт) | `.efi`-файл на FAT32-разделе (ESP) |
| Secure Boot | нет | есть (проверка подписи ядра) |
| Интерфейс | текстовый | графический, мышь, сеть |

```bash
# Как понять, в каком режиме загружена система
[ -d /sys/firmware/efi ] && echo "UEFI" || echo "BIOS/Legacy"
ls /sys/firmware/efi/efivars 2>/dev/null | head
sudo efibootmgr -v            # порядок загрузки UEFI (только в UEFI-режиме)
```

**POST** (Power-On Self-Test) — проверка железа до всякой ОС. Сигналы (писки) кодируют
неисправность: память, видео, CPU.

⚠️ Практично: если сервер загрузился в Legacy, а система установлена под UEFI (или наоборот) —
он «не увидит» загрузчик. В облаке это проявляется при миграции образов между платформами.

---

## 3. Bootloader — GRUB2

Задача: найти ядро, загрузить его в память, передать параметры, отдать управление.

```text:no-line-numbers
/boot/
├── vmlinuz-5.15.0-91-generic       ← сжатое ядро
├── initrd.img-5.15.0-91-generic    ← initramfs
├── config-5.15.0-91-generic        ← конфиг, с которым собрано ядро
├── System.map-5.15.0-91-generic    ← таблица символов ядра
└── grub/
    ├── grub.cfg                    ← СГЕНЕРИРОВАННЫЙ конфиг (руками НЕ править!)
    └── ...
```

```bash
# ПРАВИЛЬНЫЙ путь настройки
sudo vim /etc/default/grub          # основные настройки
ls /etc/grub.d/                     # скрипты-генераторы (40_custom — для своих пунктов)
sudo update-grub                    # Debian/Ubuntu: пересобрать grub.cfg
sudo grub-mkconfig -o /boot/grub/grub.cfg   # универсальный вариант
sudo grub2-mkconfig -o /boot/grub2/grub.cfg # RHEL
```

Важные параметры `/etc/default/grub`:
```bash
GRUB_TIMEOUT=5                      # сколько секунд показывать меню
GRUB_DEFAULT=0                      # пункт по умолчанию
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"   # параметры ядра
GRUB_CMDLINE_LINUX=""
GRUB_DISABLE_RECOVERY="false"       # показывать recovery-пункты
```

💡 На сервере полезно убрать `quiet splash` — тогда на консоли видно, что происходит при загрузке.

**Полезные параметры ядра** (добавляются в строку `linux` при загрузке или в `GRUB_CMDLINE_LINUX`):

| Параметр | Что делает |
|----------|-----------|
| `single` / `1` | Однопользовательский режим |
| `systemd.unit=rescue.target` | Загрузка в rescue |
| `systemd.unit=emergency.target` | Минимальный режим (даже без монтирования fstab) |
| `init=/bin/bash` | Вместо systemd запустить shell ← **сброс пароля root** |
| `nomodeset` | Без графических драйверов (спасает при проблемах с видео) |
| `ro` / `rw` | Как монтировать корень |
| `fsck.mode=force` | Принудительная проверка ФС |
| `console=ttyS0,115200` | Вывод на serial-консоль ← важно для облаков и IPMI |

### 🔑 Сброс пароля root через GRUB (must-know)

```text:no-line-numbers
1. Перезагрузить, в меню GRUB нажать 'e' на нужном пункте
2. Найти строку, начинающуюся с 'linux'
3. В её конец дописать:   rw init=/bin/bash
   (rw — чтобы корень сразу монтировался на запись)
4. Ctrl+X (или F10) — загрузка
5. В полученном shell:
     mount -o remount,rw /          # если не помогло rw
     passwd root                    # задать новый пароль
     passwd username
     touch /.autorelabel            # если SELinux (RHEL)
     exec /sbin/init                # или: sync; reboot -f
```

🔐 Отсюда важный вывод по безопасности: **физический доступ (или доступ к консоли гипервизора)
= root**. Защита: пароль на GRUB (`grub-mkpasswd-pbkdf2` + `password_pbkdf2` в `/etc/grub.d/40_custom`),
шифрование диска (LUKS), Secure Boot, ограничение доступа к консоли в облаке.

---

## 4. Kernel — этап ядра

Что делает ядро при старте:
1. Распаковывается себя в память.
2. Инициализирует CPU, память, планировщик, базовые подсистемы.
3. Монтирует **initramfs** как временный корень (tmpfs в памяти).
4. Из initramfs загружает модули, нужные для доступа к реальному корню (LVM, RAID, LUKS, NVMe, iSCSI).
5. Монтирует реальный корень и выполняет `switch_root` на него.
6. Запускает `/sbin/init` (сейчас — systemd) как **PID 1**.

```bash
uname -r                          # текущее ядро
ls /boot/vmlinuz-*                # установленные ядра
cat /proc/cmdline                 # ⭐ с какими параметрами загружено ТЕКУЩЕЕ ядро
dmesg | head -50                  # ранние сообщения ядра
journalctl -k -b                  # сообщения ядра за текущую загрузку
journalctl -k -b -1               # за ПРЕДЫДУЩУЮ загрузку ← после внезапной перезагрузки

# initramfs
lsinitramfs /boot/initrd.img-$(uname -r) | head        # Debian/Ubuntu
sudo update-initramfs -u                               # пересобрать текущий
sudo update-initramfs -u -k all                        # для всех ядер
sudo dracut -f                                         # RHEL
```

⚠️ **Kernel panic: VFS: Unable to mount root fs** — классика: initramfs собран без нужного драйвера
(например, после добавления диска на LVM или смены контроллера) либо неверный `root=UUID=`.
Лечение — загрузиться со старого ядра/live-образа, `chroot`, пересобрать initramfs и grub.

**Несколько ядер** — страховка: после обновления всегда можно выбрать предыдущее в меню GRUB.
Не удаляй старые ядра «для места», пока новое не отработало.

---

## 5. Init — запуск системы

После `switch_root` ядро запускает PID 1 — systemd (подробно в [теме 13](/linux/13-init)).

```bash
systemctl get-default                   # текущая цель по умолчанию
sudo systemctl set-default multi-user.target   # сервер без графики
systemctl list-units --type=target

systemd-analyze                         # общее время загрузки
systemd-analyze blame                   # ⭐ какие юниты тормозят загрузку
systemd-analyze critical-chain          # критическая цепочка зависимостей
systemd-analyze plot > boot.svg         # визуализация

systemctl --failed                      # что не стартовало
journalctl -b -p err                    # ошибки текущей загрузки
journalctl --list-boots                 # список загрузок
```

**Аварийные режимы:**

| Режим | Что доступно |
|-------|--------------|
| `rescue.target` (single) | Корень смонтирован, базовые сервисы, локальный вход |
| `emergency.target` | Только корень в read-only, минимум — когда даже rescue не стартует |
| `init=/bin/bash` | Голый shell без systemd вообще |

```bash
sudo systemctl rescue          # перейти на лету
sudo systemctl emergency
sudo systemctl isolate multi-user.target   # вернуться
```

---

## 💼 Как это в DevOps

- **Сервер не поднялся после перезагрузки** — умение зайти в GRUB/rescue и починить fstab или
  загрузчик отличает джуна от «позвоните админу».
- **Облака:** serial console (AWS EC2 Serial Console, GCP, Yandex Cloud) — тот же GRUB,
  поэтому `console=ttyS0,115200` в параметрах ядра критичен.
- **Время загрузки** важно для автоскейлинга: `systemd-analyze blame` помогает срезать минуты.
- **Обновление ядра** = перезагрузка; live patching (kpatch, Ubuntu Livepatch) — альтернатива.
- **Безопасность:** физический/консольный доступ = root, если нет пароля GRUB и шифрования диска.
- **Immutable-инфраструктура:** вместо починки загрузки часто проще пересоздать инстанс из образа —
  но понимать, что сломалось, всё равно надо.

---

## 🧪 Мини-лаба

```bash
vagrant ssh

# 1. Как загружена система
[ -d /sys/firmware/efi ] && echo UEFI || echo BIOS
cat /proc/cmdline
uname -r
ls -lh /boot/

# 2. Анализ загрузки
systemd-analyze
systemd-analyze blame | head -15
systemd-analyze critical-chain
systemctl get-default
systemctl --failed

# 3. Логи загрузки
journalctl --list-boots
journalctl -b -p err --no-pager | head -30
journalctl -k -b | head -40

# 4. GRUB
cat /etc/default/grub
ls /etc/grub.d/
sudo grep -c menuentry /boot/grub/grub.cfg

# 5. Безопасное изменение параметров GRUB
sudo cp /etc/default/grub /etc/default/grub.bak
sudo sed -i 's/GRUB_TIMEOUT=0/GRUB_TIMEOUT=5/' /etc/default/grub
sudo update-grub
grep TIMEOUT /etc/default/grub

# 6. initramfs
lsinitramfs /boot/initrd.img-$(uname -r) | head -20
lsinitramfs /boot/initrd.img-$(uname -r) | grep -c .

# 7. Аварийные режимы (ОСТОРОЖНО — ВМ станет недоступна по SSH!)
#    Делать только если можешь зайти через `virsh console` или готов к
#    `vagrant halt && vagrant up`. Сначала: vagrant snapshot save before_rescue
# sudo systemctl rescue
# systemctl isolate multi-user.target

# 8. ТРЕНИРОВКА СБРОСА ПАРОЛЯ (самое ценное упражнение темы)
#    Требует доступа к консоли ВМ:
#    virsh list --all
#    virsh console <имя_домена>        (выход: Ctrl+])
#    затем vagrant reload и в момент показа меню GRUB нажать 'e'
```

---

## 📌 Шпаргалка

| Команда | Действие |
|---------|----------|
| `cat /proc/cmdline` | С какими параметрами загружено текущее ядро |
| `[ -d /sys/firmware/efi ] && echo UEFI` | Режим загрузки |
| `sudo efibootmgr -v` | Порядок загрузки UEFI |
| `ls /boot/` | Ядра и initramfs |
| `vim /etc/default/grub` + `update-grub` | Правильная настройка GRUB |
| `systemd-analyze blame` | Кто тормозит загрузку |
| `systemctl --failed` | Что не стартовало |
| `journalctl -b -1 -p err` | Ошибки **прошлой** загрузки |
| `journalctl -k -b` | Сообщения ядра |
| `update-initramfs -u -k all` | Пересобрать initramfs |
| `systemctl get-default` / `set-default` | Цель загрузки |
| `init=/bin/bash` (в GRUB) | Сброс root-пароля |
| `systemd.unit=rescue.target` | Аварийная загрузка |

---

## 🧠 Что запомнить

1. Порядок: **BIOS/UEFI → GRUB → ядро (+initramfs) → systemd (PID 1) → login**.
2. **initramfs** нужен, чтобы ядро смогло смонтировать корень (драйверы LVM/RAID/LUKS/NVMe).
3. `grub.cfg` **не редактируют руками** — правят `/etc/default/grub` и делают `update-grub`.
4. Сброс пароля: в GRUB `e` → в строку `linux` дописать `rw init=/bin/bash` → `passwd`.
5. Отсюда: **физический/консольный доступ = root**, если нет пароля GRUB и шифрования.
6. `cat /proc/cmdline` — быстрый способ узнать, с чем реально загружено ядро.
7. `emergency mode` после перезагрузки — почти всегда `/etc/fstab` (см. тему 10, `nofail`).
8. `journalctl -b -1` — единственный способ узнать причину внезапной перезагрузки.
9. Старые ядра в меню GRUB — твоя страховка после неудачного обновления.

➡️ Дальше: [12. Kernel](/linux/12-kernel)

---

## Задачи

> 🔴 `vagrant snapshot save before_11` — обязательно: часть заданий может сделать ВМ недоступной по SSH.
> Для заданий с консолью пригодится: `virsh list --all` и `virsh console <домен>` (выход — `Ctrl+]`).

---

### Блок A. Теория

**A1.** Перечисли все этапы загрузки от нажатия кнопки до приглашения логина. По одному предложению
на каждый этап.

<details><summary>Ответ</summary>

(1) Прошивка (BIOS/UEFI) проверяет железо и выбирает загрузочное устройство.
(2) Загрузчик GRUB читает конфигурацию, грузит ядро и initramfs в память, передаёт параметры.
(3) Ядро инициализирует оборудование, монтирует initramfs, подгружает драйверы.
(4) Монтируется настоящий корень, выполняется `switch_root`, стартует PID 1 (systemd).
(5) systemd поднимает юниты до default.target, запускается getty/SSH — появляется логин.

</details>

**A2.** Что такое POST и на каком этапе он происходит?

<details><summary>Ответ</summary>

Power-On Self-Test — самопроверка железа (CPU, память, базовые контроллеры), выполняется
прошивкой сразу после подачи питания, до всякой загрузки ОС.

</details>

**A3.** Чем UEFI отличается от BIOS? Назови 4 отличия. Как определить, в каком режиме загружена система?

<details><summary>Ответ</summary>

(1) UEFI работает с GPT и дисками >2 ТБ, BIOS — с MBR и лимитом 2 ТБ.
(2) UEFI грузит `.efi`-файл с FAT32-раздела ESP, BIOS исполняет код из 512-байтного MBR.
(3) UEFI поддерживает Secure Boot (проверка подписи загрузчика/ядра).
(4) UEFI имеет собственные переменные загрузки (`efibootmgr`), графический интерфейс, сетевой стек.
Определение: `[ -d /sys/firmware/efi ] && echo UEFI || echo BIOS`.

</details>

**A4.** Что делает загрузчик? Почему GRUB для BIOS разбит на stage 1 / 1.5 / 2?

<details><summary>Ответ</summary>

Загрузчик находит ядро на диске, загружает его и initramfs в память, передаёт параметры
командной строки и управление. Разбиение на стадии — из-за ограничения MBR в 512 байт: туда
помещается только минимальный код (stage 1), который умеет загрузить более крупный stage 1.5
с пониманием файловой системы, а тот — полноценный stage 2 из `/boot/grub`.

</details>

**A5.** **Зачем нужен initramfs?** Объясни «проблему курицы и яйца», которую он решает.

<details><summary>Ответ</summary>

Чтобы смонтировать корневую ФС, ядру нужны драйверы (LVM, RAID, LUKS, NVMe, iSCSI,
модуль самой ФС), но они лежат **на этой же** корневой ФС. initramfs — временная корневая ФС
в памяти, загружаемая GRUB вместе с ядром; в ней есть нужные модули и скрипты, которые
подготавливают и монтируют настоящий корень.

</details>

**A6.** Что такое `switch_root` и когда он происходит?

<details><summary>Ответ</summary>

`switch_root` — переключение корневой ФС с initramfs на настоящую: новая ФС становится `/`,
initramfs освобождается из памяти, и запускается настоящий `/sbin/init`.

</details>

**A7.** Почему `/boot/grub/grub.cfg` нельзя править вручную? Как правильно менять настройки GRUB?

<details><summary>Ответ</summary>

`grub.cfg` генерируется автоматически скриптами из `/etc/grub.d/` и настройками из
`/etc/default/grub`; любое обновление ядра или пакета grub перезапишет его, и ручные правки
пропадут. Правильно: менять `/etc/default/grub` или добавлять свои пункты в `/etc/grub.d/40_custom`,
затем `update-grub` (или `grub-mkconfig -o ...`).

</details>

**A8.** Что означает `root=UUID=...` в параметрах ядра? Что будет, если UUID неверный?

<details><summary>Ответ</summary>

Это указание ядру, какое устройство монтировать как корень, идентифицированное по UUID
файловой системы (устойчиво к переименованию `/dev/sdX`). Неверный UUID → ядро не найдёт корень →
`Kernel panic: VFS: Unable to mount root fs` или падение в initramfs-shell.

</details>

**A9.** Чем `rescue.target` отличается от `emergency.target`?

<details><summary>Ответ</summary>

`rescue.target` (аналог single-user): корень смонтирован на чтение-запись, базовая
инициализация выполнена, но сетевые и прикладные сервисы не стартуют — годится для починки конфигов.
`emergency.target` — минимум: только корень (часто read-only), никаких сервисов и монтирований из
fstab; используется, когда даже rescue не поднимается.

</details>

**A10.** Почему физический доступ к серверу фактически означает root-доступ? Какие есть способы защиты?

<details><summary>Ответ</summary>

Имея консоль, можно отредактировать параметры ядра в GRUB и загрузиться с `init=/bin/bash`,
получив root-shell без пароля, либо загрузиться с внешнего носителя и смонтировать диск.
Защита: пароль на GRUB (`password_pbkdf2` + `superusers`), шифрование диска (LUKS), Secure Boot,
пароль на BIOS/UEFI и ограничение boot order, физическая безопасность и контроль доступа к
serial/IPMI/консоли гипервизора.

</details>

**A11.** Зачем на сервере параметр ядра `console=ttyS0,115200`?

<details><summary>Ответ</summary>

Чтобы весь вывод загрузки и консоль были доступны через последовательный порт — это
единственный способ увидеть, что происходит с сервером, когда сеть/SSH недоступны
(serial console в облаках, IPMI/iDRAC/iLO в железных серверах).

</details>

**A12.** Почему не стоит удалять старые ядра сразу после обновления?

<details><summary>Ответ</summary>

Старое ядро — страховка: если новое не загрузится (несовместимый драйвер, сломанный
initramfs), можно выбрать предыдущее в меню GRUB. Удалять стоит только после успешной загрузки
и проверки, и оставлять минимум одно резервное.

</details>

---

### Блок B. «Что делает / что покажет»

```bash
B1.  cat /proc/cmdline
B2.  [ -d /sys/firmware/efi ] && echo UEFI || echo BIOS
B3.  sudo efibootmgr -v
B4.  systemd-analyze blame | head
B5.  systemd-analyze critical-chain
B6.  systemctl get-default
B7.  systemctl --failed
B8.  journalctl --list-boots
B9.  journalctl -b -1 -p err
B10. journalctl -k -b
B11. lsinitramfs /boot/initrd.img-$(uname -r) | head
B12. sudo update-initramfs -u -k all
B13. sudo update-grub
B14. ls /boot/vmlinuz-*
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Полная строка параметров, с которыми загружено текущее ядро.
B2.  Печатает UEFI или BIOS в зависимости от режима загрузки.
B3.  Записи загрузки UEFI, их порядок и пути к .efi-файлам (работает только в UEFI).
B4.  Юниты, отсортированные по времени инициализации — кандидаты на оптимизацию.
B5.  Критическая цепочка: последовательность зависимостей, определившая общее время загрузки.
B6.  Целевой режим по умолчанию (multi-user.target / graphical.target).
B7.  Юниты, завершившиеся с ошибкой.
B8.  Список сохранённых загрузок с их идентификаторами и временем.
B9.  Ошибки ПРЕДЫДУЩЕЙ загрузки — ключевая команда после внезапного ребута.
B10. Сообщения ядра текущей загрузки (аналог dmesg, но с фильтрами journald).
B11. Содержимое initramfs: какие модули и утилиты в нём есть.
B12. Пересобирает initramfs для всех установленных ядер.
B13. Перегенерирует /boot/grub/grub.cfg из /etc/default/grub и /etc/grub.d/.
B14. Список установленных ядер.
```

</details>

**B15.** Что означают эти параметры ядра: `single`, `init=/bin/bash`,
`systemd.unit=emergency.target`, `nomodeset`, `fsck.mode=force`, `ro`?

<details><summary>Ответ</summary>

`single` — однопользовательский режим (rescue); `init=/bin/bash` — вместо systemd
запустить shell (сброс пароля); `systemd.unit=emergency.target` — минимальный аварийный режим;
`nomodeset` — не использовать KMS-драйверы видео (спасает при чёрном экране);
`fsck.mode=force` — принудительная проверка ФС при загрузке; `ro` — монтировать корень только
для чтения (стандартно на раннем этапе, позже перемонтируется в rw).

</details>

---

### Блок C. Практика

#### C1. Паспорт загрузки

Собери и запиши:
- режим загрузки (UEFI/BIOS);
- полную строку параметров текущего ядра;
- версию ядра и список всех установленных ядер;
- цель загрузки по умолчанию;
- общее время загрузки и топ-5 самых медленных юнитов;
- были ли ошибки при последней загрузке.

<details><summary>Ответ</summary>

```bash
[ -d /sys/firmware/efi ] && echo UEFI || echo BIOS
cat /proc/cmdline
uname -r; ls /boot/vmlinuz-*
systemctl get-default
systemd-analyze; systemd-analyze blame | head -5
journalctl -b -p err --no-pager | head
```

</details>

#### C2. Анализ загрузки

Выполни `systemd-analyze blame` и `critical-chain`.
Объясни разницу между ними: почему юнит из топа `blame` может не быть в `critical-chain`?

#### C3. Безопасная правка GRUB

1. Сделай бэкап `/etc/default/grub`.
2. Установи `GRUB_TIMEOUT=10`.
3. Убери `quiet splash`, чтобы видеть процесс загрузки на консоли.
4. Добавь `console=ttyS0,115200` для serial-консоли.
5. Примени изменения и проверь, что они попали в `grub.cfg`.
6. Перезагрузись и убедись, что система поднялась.

*Критерий:* после перезагрузки `cat /proc/cmdline` содержит твои параметры.

<details><summary>Ответ</summary>

```bash
sudo cp /etc/default/grub /etc/default/grub.bak
sudo sed -i 's/^GRUB_TIMEOUT=.*/GRUB_TIMEOUT=10/' /etc/default/grub
sudo sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT=.*/GRUB_CMDLINE_LINUX_DEFAULT="console=ttyS0,115200 console=tty0"/' /etc/default/grub
sudo update-grub
grep -E 'GRUB_TIMEOUT|CMDLINE' /etc/default/grub
sudo grep -m1 'linux.*vmlinuz' /boot/grub/grub.cfg
sudo reboot
# после перезагрузки:
cat /proc/cmdline
```

</details>

#### C4. Свой пункт меню GRUB

Создай в `/etc/grub.d/40_custom` дополнительный пункт,
который грузит то же ядро, но с `systemd.unit=rescue.target`. Пересобери конфиг
и убедись, что пункт появился в `grub.cfg` (считать `menuentry`).

<details><summary>Ответ</summary>

```bash
sudo tee -a /etc/grub.d/40_custom >/dev/null <<'EOS'
menuentry 'Ubuntu (rescue mode - custom)' {
    set root='hd0,gpt1'
    linux /boot/vmlinuz-$(uname -r) root=UUID=REPLACE_ME ro systemd.unit=rescue.target
    initrd /boot/initrd.img-$(uname -r)
}
EOS
sudo update-grub
sudo grep -c menuentry /boot/grub/grub.cfg
```

(В реальном файле `$(uname -r)` и UUID надо подставить значениями — GRUB не исполняет bash.)

</details>

#### C5. Логи загрузок

Найди:
- сколько загрузок сохранено в journald;
- все ошибки (`-p err`) предыдущей загрузки;
- сообщения ядра о дисках при текущей загрузке;
- была ли последняя перезагрузка штатной (подсказка: ищи `Shutting down` / `reboot`).

<details><summary>Ответ</summary>

```bash
journalctl --list-boots
journalctl -b -1 -p err --no-pager
journalctl -k -b | grep -iE 'sd[a-z]|vd[a-z]|nvme|ext4|xfs'
journalctl -b -1 --no-pager | tail -20     # видно ли "Shutting down" / "Reached target Shutdown"
```

</details>

#### C6. 🔑 Сброс пароля root (главное упражнение темы)

1. Установи пароль пользователю `vagrant` (`sudo passwd vagrant`), запиши его.
2. Подключись к консоли ВМ (`virsh console` или GUI virt-manager).
3. Перезагрузи, войди в меню GRUB (`Shift`/`Esc` при загрузке).
4. Нажми `e`, дополни строку `linux` параметром `rw init=/bin/bash`, запусти `Ctrl+X`.
5. Смени пароль `vagrant` на другой.
6. Корректно выйди (`exec /sbin/init` или `sync; reboot -f`).
7. Проверь, что новый пароль работает.

*Критерий:* ты **сам** прошёл весь путь и понимаешь каждый шаг.

#### C7. Защита GRUB паролем

Настрой пароль на редактирование пунктов меню:
- сгенерируй хэш через `grub-mkpasswd-pbkdf2`;
- добавь `set superusers` и `password_pbkdf2` в `/etc/grub.d/40_custom`;
- разреши загрузку по умолчанию без пароля, но потребуй пароль при нажатии `e`
  (подсказка: `--unrestricted`);
- пересобери конфиг и проверь.

<details><summary>Ответ</summary>

```bash
grub-mkpasswd-pbkdf2      # получить grub.pbkdf2.sha512....
sudo tee -a /etc/grub.d/40_custom >/dev/null <<'EOS'
set superusers="admin"
password_pbkdf2 admin grub.pbkdf2.sha512.10000.XXXX...
EOS
# чтобы обычная загрузка не требовала пароля:
sudo sed -i 's/^CLASS="--class gnu-linux/CLASS="--unrestricted --class gnu-linux/' /etc/grub.d/10_linux
sudo update-grub
```

</details>

#### C8. Тренировка аварийного режима

Сломай систему **контролируемо** и почини:
1. Добавь в `/etc/fstab` строку с несуществующим устройством **без** `nofail`.
2. Перезагрузись — система уйдёт в emergency.
3. Через консоль войди, перемонтируй корень на запись, исправь fstab, загрузись.
4. Повтори, но уже с `nofail` — убедись, что система грузится нормально.

<details><summary>Ответ</summary>

```bash
echo "/dev/sdzz1 /nonexistent ext4 defaults 0 2" | sudo tee -a /etc/fstab
sudo reboot                     # уйдёт в emergency
# на консоли:
mount -o remount,rw /
sed -i '/nonexistent/d' /etc/fstab
systemctl daemon-reload
reboot
# вариант с nofail:
echo "/dev/sdzz1 /nonexistent ext4 defaults,nofail 0 2" | sudo tee -a /etc/fstab
sudo reboot                     # система грузится нормально
sudo sed -i '/nonexistent/d' /etc/fstab
```

</details>

#### C9. Скрипт boot-аудита

Напиши `/vagrant/boot_report.sh`:
```text:no-line-numbers
=== BOOT REPORT ===
Firmware: BIOS
Kernel: 5.15.0-91-generic
Cmdline: BOOT_IMAGE=/vmlinuz-... root=UUID=... ro
Default target: multi-user.target
Boot time: 12.4s (kernel 3.1s, userspace 9.3s)
Slowest units:
  4.2s  snapd.service
  ...
Failed units: none
Errors in this boot: 2
Available kernels: 2
Last boot was: clean / unexpected
```

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
echo "=== BOOT REPORT ==="
[ -d /sys/firmware/efi ] && fw=UEFI || fw=BIOS
echo "Firmware: $fw"
echo "Kernel: $(uname -r)"
echo "Cmdline: $(cat /proc/cmdline)"
echo "Default target: $(systemctl get-default)"
echo "Boot time: $(systemd-analyze | head -1)"
echo "Slowest units:"; systemd-analyze blame 2>/dev/null | head -5
failed=$(systemctl --failed --no-legend | wc -l)
echo "Failed units: ${failed:-0}"
echo "Errors in this boot: $(journalctl -b -p err --no-pager -q | wc -l)"
echo "Available kernels: $(ls /boot/vmlinuz-* 2>/dev/null | wc -l)"
if journalctl -b -1 --no-pager -q 2>/dev/null | tail -5 | grep -qiE 'shutting down|reached target (shutdown|reboot)'; then
  echo "Last boot was: clean"
else
  echo "Last boot was: unexpected (проверь journalctl -b -1 -p err)"
fi
```

</details>

#### C10. Пересборка initramfs

Посмотри содержимое текущего initramfs, найди в нём модули
файловых систем. Пересобери initramfs для всех ядер и убедись, что дата файлов обновилась,
а система после перезагрузки поднялась.

<details><summary>Ответ</summary>

```bash
lsinitramfs /boot/initrd.img-$(uname -r) | grep -E 'ext4|xfs|lvm|raid' | head
ls -l /boot/initrd.img-*
sudo update-initramfs -u -k all
ls -l /boot/initrd.img-*
```

</details>

---

### Блок D. Инциденты

**D1.** Сервер после перезагрузки показывает:
```text:no-line-numbers
You are in emergency mode. After logging in, type "journalctl -xb" to view system logs...
Give root password for maintenance:
```
Root-пароль неизвестен. Твои действия по шагам?

<details><summary>Ответ</summary>

Emergency mode без root-пароля: перезагрузиться, в GRUB нажать `e`, в строку `linux`
дописать `rw init=/bin/bash`, `Ctrl+X`. В shell: `mount -o remount,rw /`, посмотреть
`journalctl -xb` (или `cat /etc/fstab`) — почти всегда виновата запись в fstab с недоступным
устройством. Исправить fstab (добавить `nofail` или убрать строку), затем `exec /sbin/init`.
Далее — сделать нормальный root-пароль/ключ и проверить `mount -a` перед будущими перезагрузками.

</details>

**D2.** При загрузке:
```text:no-line-numbers
Kernel panic - not syncing: VFS: Unable to mount root fs on unknown-block(0,0)
```
Три возможные причины и план восстановления.

<details><summary>Ответ</summary>

(1) Неверный `root=UUID=` (диск переименован, ФС пересоздана) — проверить `blkid` из
live-режима. (2) initramfs собран без модуля, нужного для доступа к корню (LVM/RAID/NVMe/LUKS) —
пересобрать `update-initramfs -u -k all` в chroot. (3) Повреждён initramfs или само ядро
(обрыв обновления, заполненный `/boot`). План: загрузиться с предыдущего ядра из меню GRUB, либо
с live-образа → смонтировать корень и `/boot` → `chroot` → пересобрать initramfs и grub → reboot.

</details>

**D3.** После обновления ядра сервер не грузится, старое ядро в меню тоже отсутствует.
Что произошло и как восстановиться с live-образа (общая последовательность с `chroot`)?

<details><summary>Ответ</summary>

Скорее всего `/boot` был переполнен и старые ядра удалены/новое записано частично,
либо `update-grub` отработал на неполном наборе файлов. Восстановление:
```bash
# с live-образа
sudo mount /dev/vda2 /mnt            # корень
sudo mount /dev/vda1 /mnt/boot       # при отдельном /boot
for d in dev proc sys run; do sudo mount --bind /$d /mnt/$d; done
sudo chroot /mnt
apt install --reinstall linux-image-$(uname -r)   # или нужную версию
update-initramfs -u -k all
update-grub
grub-install /dev/vda                # для BIOS; для UEFI — grub-install без указания диска
exit; sudo reboot
```

</details>

**D4.** В облаке инстанс «завис при загрузке», SSH не отвечает. Как посмотреть, что происходит,
не имея физического доступа? Что нужно было настроить заранее?

<details><summary>Ответ</summary>

Использовать serial console провайдера (AWS EC2 Serial Console, GCP serial port,
Yandex Cloud serial console) или снимок экрана инстанса; в железе — IPMI/iDRAC/iLO.
Заранее должно быть настроено: `console=ttyS0,115200` в параметрах ядра, включённый доступ к
serial console в настройках инстанса, заданный пароль для консольного входа (или ключ), а также
разрешённый вход в GRUB. Запасной вариант — отцепить диск и примонтировать к другой ВМ.

</details>

**D5.** Сервер грузится 4 минуты вместо 30 секунд. Как найти причину и что обычно виновато?

<details><summary>Ответ</summary>

`systemd-analyze` (kernel vs userspace), `systemd-analyze blame`, `critical-chain`,
`systemctl --failed`. Типовые виновники: ожидание сети (`systemd-networkd-wait-online`,
`NetworkManager-wait-online`), недоступные монтирования в fstab (лечится `nofail` +
`x-systemd.device-timeout`), медленные сервисы (`snapd`, `cloud-init`), долгий DNS в стартующих
сервисах, проверка ФС. Также стоит посмотреть `systemd-analyze plot > boot.svg`.

</details>

**D6.** Сервер внезапно перезагрузился ночью. Как понять — паника ядра, OOM, потеря питания
или штатный reboot?

<details><summary>Ответ</summary>

`journalctl --list-boots` → `journalctl -b -1 -e` (конец предыдущей загрузки):
наличие «Shutting down»/«Reached target Reboot» = штатная перезагрузка;
`journalctl -b -1 -p err` и `-k` покажут `Kernel panic`, `Out of memory: Killed process`,
`Hardware Error`/MCE; `last -x | head` покажет `shutdown`/`crash`; отсутствие каких-либо
записей перед обрывом = потеря питания или жёсткий ресет гипервизора/watchdog.
Дополнительно: `dmesg -T` и логи IPMI/SEL, метрики мониторинга на момент сбоя.

</details>

**D7.** После добавления второго диска сервер не загружается: `GRUB rescue>`.
Что произошло и как действовать?

<details><summary>Ответ</summary>

GRUB не нашёл свои модули или изменилась нумерация дисков/разделов (новый диск стал первым
в порядке загрузки, либо BIOS переключил boot order). Действия: в `grub rescue` выполнить `ls`,
найти раздел с `/boot/grub` (`ls (hd0,gpt2)/`), затем:
```text:no-line-numbers
set root=(hd0,gpt2)
set prefix=(hd0,gpt2)/boot/grub
insmod normal
normal
```
После загрузки — `sudo update-grub && sudo grub-install /dev/vda` и поправить boot order в BIOS/UEFI.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что происходит при включении компьютера? (Разверни по этапам.)

<details><summary>Ответ</summary>

Прошивка (POST, выбор устройства) → загрузчик GRUB (ядро + initramfs в память, параметры) →
ядро (инициализация, initramfs, драйверы, монтирование корня, switch_root) → systemd PID 1
(юниты до default.target) → getty/SSH/логин.

</details>

**2.** Зачем нужен initramfs?

<details><summary>Ответ</summary>

Чтобы ядро смогло смонтировать корневую ФС: во временном корне в памяти лежат модули и скрипты
для LVM, RAID, LUKS, NVMe, сетевых ФС, без которых до реального корня не добраться.

</details>

**3.** Как сбросить пароль root, если нет доступа?

<details><summary>Ответ</summary>

Через GRUB: `e` → добавить `rw init=/bin/bash` → `Ctrl+X` → `passwd root` → `exec /sbin/init`.
Альтернатива — загрузка с live-образа, `chroot` и `passwd`. В облаке — сброс через
провайдера/cloud-init или подключение диска к другой ВМ.

</details>

**4.** Чем UEFI отличается от BIOS?

<details><summary>Ответ</summary>

GPT и большие диски, `.efi`-загрузчик вместо кода в MBR, Secure Boot, собственные переменные
загрузки и более богатая прошивка.

</details>

**5.** Как посмотреть, почему сервер перезагрузился?

<details><summary>Ответ</summary>

`journalctl --list-boots`, `journalctl -b -1 -p err`, `journalctl -k -b -1`, `last -x`,
`dmesg -T`; искать kernel panic, OOM, аппаратные ошибки или штатный shutdown.

</details>

**6.** Как загрузиться в аварийный режим?

<details><summary>Ответ</summary>

В GRUB добавить `systemd.unit=rescue.target` (или `emergency.target`), либо на работающей
системе `systemctl rescue` / `systemctl emergency`.

</details>

**7.** Что такое GRUB и где его настройки?

<details><summary>Ответ</summary>

Загрузчик, который грузит ядро и initramfs. Настройки: `/etc/default/grub` и `/etc/grub.d/`,
сгенерированный конфиг — `/boot/grub/grub.cfg`, пересборка — `update-grub`/`grub-mkconfig`.

</details>

**8.** Как ускорить загрузку сервера?

<details><summary>Ответ</summary>

`systemd-analyze blame` и `critical-chain` → отключить ненужные сервисы (`systemctl disable`),
убрать ожидание сети, добавить `nofail`/таймауты в fstab, отключить лишние ждущие юниты
(`cloud-init`, `snapd` при ненадобности), уменьшить `GRUB_TIMEOUT`.

</details>

---

### 🎯 Чек-лист

- [ ] Рассказываю все 5 этапов загрузки без подсказок
- [ ] Понимаю, зачем нужен initramfs
- [ ] Правлю GRUB через `/etc/default/grub` + `update-grub`
- [ ] **Сам** сбросил пароль через `init=/bin/bash`
- [ ] Умею починить систему, ушедшую в emergency из-за fstab
- [ ] Знаю `journalctl -b -1` для разбора внезапных перезагрузок
- [ ] Понимаю, зачем `console=ttyS0` на сервере
