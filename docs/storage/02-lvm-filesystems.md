---
title: "02. LVM, файловые системы и RAID на Linux"
description: "Блок → Хранилища и stateful → тема 02. Опирается на"
---

# 02. LVM, файловые системы и RAID на Linux

> Блок → Хранилища и stateful → тема 02. Опирается на
> [../Linux/10_the_filesystem.md](/linux/10-the-filesystem) (разделы, `mkfs`, `mount`, поля
> `/etc/fstab`, `df`/`du`, inode, `fsck` — там LVM упомянут в три строки, здесь — всерьёз)
> и [01_storage_basics.md](/storage/01-storage-basics) (уровни RAID, write penalty, rebuild).
>
> **После темы ты умеешь:** собрать LVM из нескольких дисков, расширить том онлайн одной
> командой, понимать, когда уменьшать нельзя; делать и откатывать снапшоты и объяснять, почему
> это не бэкап; работать с thin provisioning и не переполнить пул; заменить диск без простоя
> через `pvmove`; выбрать между ext4 и XFS; разобрать инцидент «диск расширили, а места нет»;
> собрать RAID1 на mdadm и провести учения с отказом диска; рассказать про ZFS.

---

## 🗺️ Карта темы

```text
 /dev/vdb   /dev/vdc   /dev/vdd          /dev/vde  /dev/vdf
    │          │          │                  └──┬──┘
    │  (раздел, если нужен: growpart)       mdadm RAID1 → /dev/md0
    ▼          ▼          ▼                     │
   PV         PV         PV  ◄──────────────────┘ (md0 тоже может быть PV)
    └──────────┼──────────┘
               ▼
        VG "data" (пул экстентов по 4 МиБ)
        ├── LV app   (обычный)      → xfs  → /srv/app
        ├── LV app_snap (снапшот)
        └── thin-pool "pool" → thin LV thin1 (виртуально больше, чем есть)
                                         → ext4 → /srv/thin
 рост:    lvextend -r  (LV + ФС онлайн)
 замена:  vgextend → pvmove → vgreduce → pvremove
```text
---

## 0. Стенд

VM `stor1` из [00_INDEX.md](/storage/): диски добавлены в `Vagrantfile` провайдера libvirt —
```ruby
v.storage :file, size: "5G", serial: "lvm-a"    # /dev/vdb
v.storage :file, size: "5G", serial: "lvm-b"    # /dev/vdc
v.storage :file, size: "5G", serial: "lvm-c"    # /dev/vdd
v.storage :file, size: "3G", serial: "raid-a"   # /dev/vde   (+ raid-b, raid-c → vdf, vdg)
```text
```bash
vagrant snapshot save stor1 before_02
vagrant ssh stor1
lsblk -o NAME,SIZE,SERIAL,TYPE,MOUNTPOINTS      # ⚠️ сверяй перед КАЖДОЙ разрушающей командой
ls -l /dev/disk/by-id/ | grep virtio            # virtio-lvm-a → ../../vdb и т.д.
```text
> ⚠️ Все `pvcreate`, `mkfs`, `wipefs`, `mdadm --create`, `zpool create` в теме — только на
> дополнительных дисках учебной VM. Буквы `vdX` могут сдвинуться; серийник в `by-id` — нет.

---

## 1. LVM: модель

| Слой | Что это | Команды «посмотреть» |
|------|---------|----------------------|
| **PV** (physical volume) | Диск или раздел, размеченный под LVM | `pvs`, `pvdisplay -m` |
| **VG** (volume group) | Пул из PV, нарезанный на экстенты (PE, по умолчанию 4 МиБ) | `vgs`, `vgdisplay` |
| **LV** (logical volume) | «Виртуальный диск» из экстентов VG, на нём ФС | `lvs`, `lvs -a -o +devices` |

```bash
sudo apt install -y lvm2
sudo pvcreate /dev/vdb /dev/vdc
sudo vgcreate data /dev/vdb /dev/vdc              # VG из двух дисков ≈ 10G
sudo lvcreate -n app -L 3G data                    # -L — точный размер
sudo lvcreate -n logs -l 50%FREE data              # -l — в экстентах или процентах
sudo mkfs.xfs /dev/data/app && sudo mkfs.ext4 /dev/data/logs
sudo mkdir -p /srv/app /srv/logs
sudo mount /dev/data/app /srv/app && sudo mount /dev/data/logs /srv/logs
sudo pvs; sudo vgs; sudo lvs -a -o +devices        # на каких PV лежит каждый LV
```text
Путь к тому стабилен: `/dev/data/app` = `/dev/mapper/data-app` (дефис в имени VG/LV в mapper
удваивается: `my-vg` → `my--vg`).

LVM умеет и больше: RAID-тома (`lvcreate --type raid1 -m 1`), кэш на SSD (`lvmcache`),
striping. В проде чаще встречаются «LVM поверх аппаратного RAID/mdadm» и «LVM на облачных
дисках» — ради гибкости размеров.

---

## 2. Расширение онлайн — главная суперсила

```bash
sudo lvextend -r -L +1G data/app                   # ⭐ LV + ФС за один шаг, без размонтирования
sudo lvextend -r -l +100%FREE data/logs            # всё свободное место VG
df -h /srv/app /srv/logs
```text
`-r` (`--resizefs`) вызывает `fsadm`, а тот — нужную утилиту ФС:

| ФС | Чем растёт | Что передать | Онлайн |
|----|-----------|--------------|--------|
| ext4 | `resize2fs` | устройство: `resize2fs /dev/data/logs` | ✅ |
| XFS | `xfs_growfs` | **точку монтирования**: `xfs_growfs /srv/app` | ✅ (только смонтированная) |

Место в VG кончилось — добавь диск:
```bash
sudo pvcreate /dev/vdd && sudo vgextend data /dev/vdd
sudo lvextend -r -L +3G data/app
```text
> ⚠️ Классическая ошибка — `lvextend` без `-r`: LV стал больше, а `df` показывает старый размер.
> Лечится вторым шагом: `resize2fs`/`xfs_growfs`.

---

## 3. Уменьшение — осторожно

| ФС | Уменьшить | Как |
|----|-----------|-----|
| ext4 | Только **offline** | размонтировать → `e2fsck -f` → уменьшить ФС → уменьшить LV |
| XFS | **Никак** | новый LV меньшего размера + перенос данных (`rsync -aHAX`, `xfsdump`/`xfsrestore`) |

```bash
# ext4: сначала бэкап. Всегда.
sudo umount /srv/logs
sudo e2fsck -f /dev/data/logs
sudo lvreduce -r -L 2G data/logs     # -r: fsadm сначала уменьшит ФС, потом LV
sudo mount /dev/data/logs /srv/logs
```text
> 🔴 Уменьшить LV **раньше** ФС (без `-r`) = отрезать конец файловой системы с данными.
> Порядок при уменьшении: ФС → LV. При увеличении: LV → ФС. `-r` делает правильно сам.

---

## 4. Замена диска без простоя: `pvmove`

Диск стареет (SMART), переезжаешь на новый — сервис продолжает работать:
```bash
sudo pvcreate /dev/vdd && sudo vgextend data /dev/vdd     # 1. новый диск в VG
sudo pvmove /dev/vdb                                      # 2. экстенты с vdb → на свободные PV
sudo pvmove /dev/vdb /dev/vdd                             #    …или явно, куда
sudo vgreduce data /dev/vdb                               # 3. выкинуть старый PV из VG
sudo pvremove /dev/vdb                                    # 4. снять метку LVM
```text
- `pvmove` зеркалирует экстенты во временный LV и переключает — данные доступны всё время.
- Долго и нагружает диски; прерванный `pvmove` продолжается командой `sudo pvmove` без аргументов.
- `sudo pvmove -n app /dev/vdb` — перенести только экстенты одного LV.
- До шага 3 проверь: `sudo pvs` — у `/dev/vdb` `PFree` = `PSize` (пустой).

---

## 5. Снапшоты LVM

```bash
sudo lvcreate -s -n app_snap -L 500M data/app      # COW-снапшот: 500M под ИЗМЕНЕНИЯ
sudo lvs data                                       # Origin=app, Data% — заполненность
sudo mkdir -p /mnt/snap
sudo mount -o ro,nouuid /dev/data/app_snap /mnt/snap   # XFS: nouuid обязателен (тот же UUID)
```text
Как работает классический (thick) снапшот:
```text
 до изменения блока:   снапшот ссылается на блок оригинала (места не тратит)
 запись в оригинал:    старый блок КОПИРУЕТСЯ в область снапшота, потом перезаписывается
                       → каждая первая запись в блок = 2 операции (COW-penalty)
 область заполнилась:  Data% = 100 → снапшот INVALID, его можно только удалить
```text
Откат к снапшоту:
```bash
sudo umount /mnt/snap /srv/app
sudo lvconvert --merge data/app_snap               # слить снапшот обратно в оригинал
# если оригинал был открыт — слияние произойдёт при следующей активации:
sudo lvchange -an data/app && sudo lvchange -ay data/app
sudo mount /dev/data/app /srv/app
```text
Автоматическое расширение снапшота — в `/etc/lvm/lvm.conf` (секция `activation`):
`snapshot_autoextend_threshold = 70`, `snapshot_autoextend_percent = 20` (нужен мониторинг
`dmeventd`, включён по умолчанию).

### Почему снапшот LVM — не бэкап

| Снапшот LVM | Бэкап |
|-------------|-------|
| На тех же дисках, в том же VG | На другом носителе, лучше — на другой площадке |
| Умер диск/VG — умер и снапшот | Переживает потерю сервера |
| Переполнился — стал invalid | Не зависит от нагрузки на оригинал |
| Живёт часы, замедляет запись | Хранится по retention неделями |

Правильная роль снапшота — **точка отката перед рискованной операцией** (апгрейд, миграция)
и **источник для консистентного бэкапа**: снял снапшот → скопировал его в S3 → удалил снапшот.

### Консистентность снапшота

- При создании снапшота device-mapper на мгновение приостанавливает устройство и замораживает
  ФС — снапшот консистентен **на уровне ФС** («как после внезапного выключения», crash-consistent).
- Для приложения это «выдернули питание». PostgreSQL такое переживает, **если весь PGDATA
  вместе с `pg_wal` на одном LV**; иначе — `pg_backup_start()`/`pg_backup_stop()` или
  физический бэкап штатными средствами ([06_db_backup_replication.md](/storage/06-db-backup-replication)).
- `fsfreeze -f /srv/app … fsfreeze -u /srv/app` нужен, когда снапшот делает не LVM, а гипервизор
  или СХД: они про ФС внутри ВМ ничего не знают.

---

## 6. Thin provisioning

```bash
sudo lvcreate --type thin-pool -L 3G -n pool data                     # реальный пул 3G
sudo lvcreate --type thin -V 10G --thinpool pool -n thin1 data        # виртуальный том 10G!
sudo mkfs.ext4 /dev/data/thin1
sudo lvs -o lv_name,lv_size,pool_lv,data_percent,metadata_percent data
```text
```text
 thick LV:  место выделяется сразу, целиком
 thin LV:   место берётся из пула по мере записи → можно выдать больше, чем есть (overcommit)
 thin-снапшот: без -L, общий пул, почти бесплатный, цепочки снапшотов без COW-penalty
```text
```bash
sudo lvcreate -s -n thin1_snap data/thin1           # размер не нужен
sudo lvchange -ay -K data/thin1_snap                # у thin-снапшотов стоит флаг «не активировать» — -K
```text
> 🔴 **Главная опасность — переполнение пула.** Пул на 100% → запись во **все** thin-тома пула
> встаёт в очередь (по умолчанию до 60 секунд), затем получает ошибки ввода-вывода; ФС уходят
> в read-only, базы падают. Защита:
> - алерт на `data_percent` и `metadata_percent` > 80%;
> - автоувеличение: `thin_pool_autoextend_threshold = 80`, `thin_pool_autoextend_percent = 20`
>   в `lvm.conf` (сработает, только если в VG есть свободное место);
> - `discard`/`fstrim` внутри thin-томов, чтобы удалённые файлы возвращали место в пул.

Thin — это то, как работают облака и гипервизоры (qcow2 тоже «тонкий»), Docker devicemapper
в прошлом, TopoLVM/OpenEBS LVM в Kubernetes ([05_k8s_stateful.md](/storage/05-k8s-stateful)).

---

## 7. ext4 vs XFS

| | ext4 | XFS |
|---|------|-----|
| Дефолт в | Ubuntu, Debian | RHEL, Rocky, Alma |
| Рост онлайн | ✅ `resize2fs DEV` | ✅ `xfs_growfs MOUNTPOINT` |
| Уменьшение | Только offline | ❌ невозможно |
| Inode | Фиксируются при `mkfs` (могут кончиться — [../Linux/10_the_filesystem.md](/linux/10-the-filesystem)) | Выделяются динамически |
| Сильные стороны | Универсальна, проверена, умеет уменьшаться | Большие файлы, параллельная запись, большие тома |
| Проверка/ремонт | `e2fsck` | `xfs_repair` (на размонтированной) |
| Инфо | `tune2fs -l`, `dumpe2fs -h` | `xfs_info /mount` |
| Монтирование снапшота | обычное | нужен `-o nouuid` |

Выбор на практике: берут дефолт дистрибутива. XFS — под большие тома с данными (БД, Ceph
раньше, логи, медиа); ext4 — когда может понадобиться уменьшение. Резерв 5% под root у ext4
и `tune2fs -m` — в [../Linux/10_the_filesystem.md](/linux/10-the-filesystem).

---

## 8. Монтирование и fstab — то, чего нет в Linux/10

Поля fstab, UUID и `nofail` разобраны в [../Linux/10_the_filesystem.md](/linux/10-the-filesystem).
Сверху — то, что встречается на серверах с данными:

| Опция | Зачем |
|-------|-------|
| `noatime` | Не писать время доступа на каждое чтение (по умолчанию `relatime` — уже щадяще) |
| `nofail` | Не ронять загрузку без этого диска (данные, не корень) |
| `x-systemd.device-timeout=10s` | Не ждать отсутствующий диск 90 секунд по умолчанию |
| `x-systemd.automount` | Монтировать при первом обращении (сетевые и медленные ФС) |
| `errors=remount-ro` (ext4) | При ошибке ФС — в read-only, а не продолжать портить |
| `discard` | Онлайн-TRIM на каждое удаление: удобно, но может добавлять latency |
| — (вместо `discard`) | ⭐ `fstrim.timer` раз в неделю: `systemctl status fstrim.timer` |
| `_netdev` | Сетевой диск (iSCSI, NFS): монтировать после сети |

```bash
# UUID для LV тоже есть, но и /dev/data/app стабилен (имя device-mapper)
echo "UUID=$(sudo blkid -s UUID -o value /dev/data/app) /srv/app xfs defaults,noatime,nofail 0 0" \
  | sudo tee -a /etc/fstab
sudo findmnt --verify              # ⭐ проверка fstab: синтаксис, существование устройств, типы ФС
sudo mount -a && findmnt /srv/app  # и боевая проверка до перезагрузки
```text
> 💡 Для XFS шестое поле (`fsck`) ставят 0: `fsck.xfs` ничего не делает, XFS восстанавливается
> по журналу при монтировании.

---

## 9. Инцидент: «расширили диск, а места не прибавилось» ⭐

Облако или гипервизор расширили диск с 20 до 40 ГБ, `df -h` показывает всё те же 20.
Проверяй по слоям снизу вверх — где размер «застрял»:

```text
 lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS
 ┌─────────────────────────┐
 │ 1. ДИСК стал 40G?        │── нет → ядро не узнало: rescan (SCSI) / проверить в консоли облака
 │ 2. РАЗДЕЛ стал больше?   │── нет → growpart /dev/vda 3
 │ 3. PV стал больше?       │── нет → pvresize /dev/vda3            (pvs → PSize)
 │ 4. LV стал больше?       │── нет → lvextend -l +100%FREE          (vgs → VFree)
 │ 5. ФС стала больше?      │── нет → resize2fs / xfs_growfs         (df -h)
 └─────────────────────────┘
```text
```bash
# 1. ядро видит новый размер? (virtio обычно само: dmesg | grep -i capacity)
echo 1 | sudo tee /sys/class/block/sda/device/rescan     # для SCSI-дисков (sdX)
# 2. раздел
sudo apt install -y cloud-guest-utils                    # здесь живёт growpart
sudo growpart /dev/vda 3                                 # ⚠️ пробел: диск и НОМЕР раздела
# 3–5. LVM и ФС
sudo pvresize /dev/vda3
sudo lvextend -r -l +100%FREE /dev/ubuntu-vg/ubuntu-lv
df -h /
```text
| Раскладка | Шаги |
|-----------|------|
| Раздел → PV → LV → ФС (типичный сервер) | `growpart` → `pvresize` → `lvextend -r` |
| PV на **весь диск**, без раздела | `pvresize /dev/vdb` → `lvextend -r` |
| Раздел → ФС, без LVM (облачные образы) | `growpart` → `resize2fs /dev/vda1` или `xfs_growfs /` |
| Диск → ФС, без раздела и LVM | сразу `resize2fs /dev/vdb` / `xfs_growfs /mnt` |

На стенде расширить диск «как в облаке» можно с хоста, не выключая VM:
```bash
virsh blockresize storage-lab_stor1 vdd 8G     # на хосте; в госте: dmesg | tail → новый размер vdd
```text
---

## 10. Программный RAID: mdadm

```bash
sudo apt install -y mdadm
sudo mdadm --create /dev/md0 --level=1 --raid-devices=2 /dev/vde /dev/vdf
#   спросит про metadata в начале диска → y. Для RAID5: --level=5 --raid-devices=3
cat /proc/mdstat
#   md0 : active raid1 vdf[1] vde[0]
#         3142656 blocks super 1.2 [2/2] [UU]            ← [UU] — оба диска живы
sudo mdadm --detail /dev/md0                          # State: clean, список дисков

sudo mkfs.ext4 /dev/md0 && sudo mkdir -p /srv/raid && sudo mount /dev/md0 /srv/raid

# ⭐ без этого после ребута массив может собраться как /dev/md127
sudo mdadm --detail --scan | sudo tee -a /etc/mdadm/mdadm.conf
sudo update-initramfs -u
```text
Учения: отказ и замена диска
```bash
sudo mdadm /dev/md0 --fail /dev/vdf          # имитация отказа
cat /proc/mdstat                             # [2/1] [U_], у vdf пометка (F)
sudo mdadm /dev/md0 --remove /dev/vdf        # вынуть из массива
sudo mdadm /dev/md0 --add /dev/vdg           # добавить «новый» диск → пошёл rebuild
watch -n1 cat /proc/mdstat                   # recovery = 37.5% ... finish=0.2min
```text
- Hot spare: `--spare-devices=1` при создании или `--add` в здоровый массив — rebuild начнётся
  сам в момент отказа.
- Скорость rebuild ограничивают `/proc/sys/dev/raid/speed_limit_min` и `speed_limit_max` (КБ/с):
  подними min, чтобы rebuild не растянулся из-за нагрузки, или опусти max, чтобы он не убил прод.
- RAID + LVM: `/dev/md0` — обычный кандидат в PV (`pvcreate /dev/md0`).

Мониторинг — обязателен, иначе RAID молча живёт в `[U_]`:
- `mdmonitor` (`mdadm --monitor`) шлёт письма на `MAILADDR` из `mdadm.conf`;
- node_exporter: алерт `node_md_disks{state="failed"} > 0` и
  `node_md_disks_required - node_md_disks{state="active"} > 0`.

Уборка после учений:
```bash
sudo umount /srv/raid && sudo mdadm --stop /dev/md0
sudo mdadm --zero-superblock /dev/vde /dev/vdf /dev/vdg      # ⚠️ стирает метку md
sudo sed -i '/^ARRAY \/dev\/md0/d' /etc/mdadm/mdadm.conf && sudo update-initramfs -u
```text
---

## 11. ZFS — обзор

ZFS — файловая система и менеджер томов в одном: RAID, снапшоты, сжатие и контрольные суммы
всех данных.

```bash
sudo apt install -y zfsutils-linux
sudo zpool create tank mirror /dev/disk/by-id/virtio-raid-a /dev/disk/by-id/virtio-raid-b
zpool status tank                              # vdev mirror-0, состояние дисков
sudo zfs create -o compression=lz4 tank/data   # dataset — «ФС» внутри пула, монтируется в /tank/data
sudo zfs snapshot tank/data@before             # мгновенный CoW-снапшот
zfs list -t snapshot
sudo zfs rollback tank/data@before             # откат
sudo zfs send tank/data@s1 | ssh backup sudo zfs receive backup/data             # полная копия
sudo zfs send -i tank/data@s1 tank/data@s2 | ssh backup sudo zfs receive backup/data   # инкремент
sudo zpool scrub tank                          # проверка всех данных по контрольным суммам
```text
| Понятие | Смысл |
|---------|-------|
| pool / vdev | Пул из виртуальных устройств: `mirror`, `raidz1/2/3` (аналог RAID5/6/«7»), special, log, cache |
| dataset | Отдельная ФС или zvol (блочное устройство) со своими свойствами |
| snapshot + send/receive | Снапшоты и их передача (инкрементально) на другой хост — готовая репликация и основа бэкапа |
| scrub | Периодическая проверка контрольных сумм, лечит «тихую порчу» из избыточности |
| ARC | Кэш в RAM: по умолчанию занимает большую часть свободной памяти (ограничивают `zfs_arc_max`) |

Нюансы: лицензия CDDL несовместима с GPL — ZFS не в основном ядре, ставится модулем
(`zfsutils-linux` в Ubuntu, DKMS в других дистрибутивах); любит память; vdev нельзя «уменьшить»,
расширение raidz на один диск появилось только в OpenZFS 2.3. **Btrfs** — CoW-ФС в ядре со
снапшотами и подтомами; RAID1/10 в ней рабочие, RAID5/6 до сих пор не рекомендуются.

---

## 12. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| `lvextend` без `-r` | LV вырос, `df` — нет | `lvextend -r` или второй шаг `resize2fs`/`xfs_growfs` |
| `xfs_growfs /dev/data/app` | Старые версии хотят точку монтирования | `xfs_growfs /srv/app` |
| `lvreduce` без `-r` на ext4 | Отрезан конец ФС с данными | `umount` → `e2fsck -f` → `lvreduce -r` |
| Попытка уменьшить XFS | Невозможно | Новый LV + перенос данных |
| Снапшот LVM «на неделю» | Переполнился → invalid; вся неделя — COW-penalty | Снапшот на время операции, потом удалить |
| Снапшот как бэкап | Умер VG — умерли оба | Копия снапшота в другое хранилище |
| XFS-снапшот не монтируется | Дубликат UUID | `-o ro,nouuid` |
| Thin-пул без алертов | 100% → I/O ошибки у всех томов пула | Алерт > 80%, autoextend, `fstrim` |
| Нет `mdadm.conf` + `update-initramfs` | После ребута `md127` или массив не собран | `mdadm --detail --scan >> mdadm.conf` |
| RAID без мониторинга | Живёт в `[U_]` месяцами | `mdmonitor` + node_exporter алерт |
| `growpart /dev/vda3` | Неверный синтаксис | `growpart /dev/vda 3` |
| Расширили раздел, забыли `pvresize` | `vgs` не видит места | `pvresize` после `growpart` |
| `/dev/sdX` или `/dev/vdX` в скриптах и fstab | Имена сдвигаются | UUID, `/dev/disk/by-id`, `/dev/VG/LV` |
| `pvcreate` на «пустой» диск без проверки | Затёрт чужой диск | `lsblk -f`, `wipefs -n` (dry-run) перед работой |

---

## 💼 Как это в DevOps

- Сервер с данными размечают так: система отдельно, данные — на LVM (часто поверх
  RAID-контроллера или mdadm), `/var/lib/&lt;сервис&gt;` на своём LV. Тогда «кончилось место»
  лечится `vgextend` + `lvextend -r` без простоя.
- «Диск расширили, а места нет» — один из самых частых тикетов в облаке и на VMware; лестница
  «диск → раздел → PV → LV → ФС» решает его за минуту. Её же автоматизируют в Ansible
  (модули `community.general.lvol`, `filesystem` с `resizefs: true`).
- Перед рискованной операцией на VM без облачных снапшотов — LVM-снапшот, после — удалить.
- Замена диска по SMART-предупреждению на сервере с LVM — `pvmove` в рабочее время, без окна.
- Метрики: заполнение ФС (`node_filesystem_avail_bytes`), thin-пулов (textfile collector из
  `lvs --reportformat json`), состояние md (`node_md_*`), SMART (smartctl_exporter).

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Посмотреть LVM | `pvs`, `vgs`, `lvs -a -o +devices` |
| Создать | `pvcreate DEV` → `vgcreate VG DEV…` → `lvcreate -n LV -L 3G VG` |
| Расширить онлайн | `lvextend -r -L +1G VG/LV` / `-l +100%FREE` |
| Добавить диск в VG | `pvcreate DEV && vgextend VG DEV` |
| Уменьшить ext4 | `umount` → `e2fsck -f` → `lvreduce -r -L 2G VG/LV` |
| Заменить диск | `vgextend` → `pvmove OLD` → `vgreduce VG OLD` → `pvremove OLD` |
| Снапшот / откат | `lvcreate -s -n SNAP -L 500M VG/LV` / `lvconvert --merge VG/SNAP` |
| Thin-пул и том | `lvcreate --type thin-pool -L 3G -n pool VG` / `lvcreate --type thin -V 10G --thinpool pool -n t1 VG` |
| Заполненность thin | `lvs -o lv_name,data_percent,metadata_percent VG` |
| Вырастить ФС | ext4: `resize2fs DEV`; XFS: `xfs_growfs MOUNTPOINT` |
| Проверить fstab | `findmnt --verify` и `mount -a` |
| «Место не прибавилось» | `lsblk` → `growpart DISK N` → `pvresize PART` → `lvextend -r -l +100%FREE` |
| RAID1 | `mdadm --create /dev/md0 --level=1 --raid-devices=2 A B` |
| Состояние RAID | `cat /proc/mdstat`, `mdadm --detail /dev/md0` |
| Заменить диск в RAID | `--fail` → `--remove` → `--add` |
| Сохранить конфиг RAID | `mdadm --detail --scan >> /etc/mdadm/mdadm.conf && update-initramfs -u` |
| ZFS: пул, снапшот, отправка | `zpool create tank mirror A B`, `zfs snapshot`, `zfs send -i … \| zfs receive` |

---

## 🧠 Что запомнить

1. LVM: PV → VG → LV; ФС живёт на LV, путь `/dev/VG/LV` стабилен.
2. ⭐ `lvextend -r` расширяет LV и ФС онлайн одной командой; без `-r` — только LV.
3. Увеличение: LV → ФС. Уменьшение: ФС → LV, ext4 — только offline, XFS — никогда.
4. `pvmove` меняет диск под работающим сервисом: `vgextend` → `pvmove` → `vgreduce` → `pvremove`.
5. Снапшот LVM — точка отката и источник для бэкапа, но не бэкап: те же диски, переполнение = invalid.
6. Снапшот crash-consistent; БД переживёт его, только если все её файлы (включая WAL) на одном LV.
7. Thin provisioning даёт overcommit; переполненный пул роняет все его тома — алерт и autoextend обязательны.
8. ext4 — универсальна и уменьшается offline; XFS — для больших томов, не уменьшается.
9. ⭐ «Места не прибавилось»: диск → раздел (`growpart`) → PV (`pvresize`) → LV → ФС.
10. mdadm: `/proc/mdstat`, `--fail/--remove/--add`; `mdadm.conf` + `update-initramfs`; без мониторинга RAID бесполезен.
11. ZFS = ФС + тома + RAID + снапшоты + контрольные суммы; `send/receive` — готовая репликация; любит RAM, не в основном ядре.

➡️ Дальше: [03_nfs_minio.md](/storage/03-nfs-minio) · задачи: 02_lvm_filesystems_tasks.md


---

### Блок A. Теория


**A1.** Что такое PV, VG, LV и физический экстент (PE)? Какой размер PE по умолчанию?

<details><summary>Ответ</summary>

PV — диск или раздел с меткой LVM; VG — пул из PV, нарезанный на экстенты; LV —
логический том из экстентов VG, на нём ФС. PE — единица выделения, по умолчанию 4 МиБ.

</details>

**A2.** Чем `lvcreate -L 3G` отличается от `lvcreate -l 50%FREE`?

<details><summary>Ответ</summary>

`-L` — точный размер (3G); `-l` — в экстентах или процентах (`50%FREE` — половина
свободного места VG, `100%VG`, `+100%FREE` при расширении).

</details>

**A3.** ⭐ Что делает флаг `-r` у `lvextend`? Какие утилиты он вызывает для ext4 и XFS и что им передаётся?

<details><summary>Ответ</summary>

`-r` (`--resizefs`) после изменения LV вызывает `fsadm`, который растит ФС: для ext4 —
`resize2fs` с **устройством**, для XFS — `xfs_growfs` с **точкой монтирования** (ФС должна быть
смонтирована). Итог — LV и ФС за одну команду, онлайн.

</details>

**A4.** В каком порядке меняют размеры LV и ФС при увеличении и при уменьшении? Почему?

<details><summary>Ответ</summary>

Увеличение: LV → ФС (ФС не может занять место, которого ещё нет). Уменьшение: ФС → LV
(иначе конец ФС с данными окажется за границей тома). `-r` соблюдает порядок сам.

</details>

**A5.** Можно ли уменьшить ext4? А XFS? Как «уменьшают» XFS на практике?

<details><summary>Ответ</summary>

ext4 — только offline: `umount` → `e2fsck -f` → `lvreduce -r`. XFS уменьшить нельзя:
создают новый LV нужного размера, переносят данные (`rsync -aHAX` или `xfsdump`/`xfsrestore`),
переключают точку монтирования, старый LV удаляют.

</details>

**A6.** ⭐ Как заменить диск в VG без остановки сервиса? Перечисли команды по порядку.

<details><summary>Ответ</summary>

`pvcreate NEW` → `vgextend VG NEW` → `pvmove OLD` (экстенты переезжают, том смонтирован)
→ проверить `pvs` (у OLD `PFree = PSize`) → `vgreduce VG OLD` → `pvremove OLD` → физически убрать диск.

</details>

**A7.** Как работает классический COW-снапшот LVM? Откуда у него штраф на запись и что будет при `Data% = 100`?

<details><summary>Ответ</summary>

Снапшот хранит только изменённые после его создания блоки: при первой записи в блок
оригинала старое содержимое копируется в область снапшота, потом блок перезаписывается —
две операции вместо одной (COW-penalty). При `Data% = 100` снапшот становится invalid и
годится только на удаление.

</details>

**A8.** ⭐ Назови три причины, по которым снапшот LVM — не бэкап. Для чего он тогда нужен?

<details><summary>Ответ</summary>

Лежит на тех же дисках и в той же VG (умер диск — умерли оба); переполняется и
становится invalid; живёт недолго и тормозит запись. Нужен как точка отката перед рискованной
операцией и как консистентный источник, с которого копируют бэкап на другой носитель.

</details>

**A9.** Почему снапшот LVM crash-consistent и при каком условии PostgreSQL переживёт восстановление из него?

<details><summary>Ответ</summary>

device-mapper на мгновение приостанавливает устройство и замораживает ФС, поэтому снимок
соответствует одному моменту — как после внезапного выключения. PostgreSQL восстановится по WAL,
если весь PGDATA вместе с `pg_wal` (и табличные пространства) на одном LV; иначе снапшоты
разных томов окажутся из разных моментов.

</details>

**A10.** Что такое thin provisioning и overcommit? Что происходит, когда thin-пул заполняется на 100%?

<details><summary>Ответ</summary>

Thin-том берёт место из пула по мере записи, поэтому можно выдать томов больше, чем
есть реально (overcommit). При 100% запись во все тома пула сначала встаёт в очередь (по
умолчанию до 60 с), затем получает I/O errors: ФС уходят в read-only, приложения падают.

</details>

**A11.** Зачем при монтировании снапшота XFS нужен `-o nouuid`?

<details><summary>Ответ</summary>

Снапшот содержит копию суперблока с тем же UUID, что у смонтированного оригинала, а XFS
не монтирует две ФС с одинаковым UUID. `nouuid` отключает эту проверку.

</details>

**A12.** Чем опция `discard` отличается от `fstrim.timer`? Что обычно выбирают?

<details><summary>Ответ</summary>

`discard` делает TRIM на каждое удаление онлайн (может добавлять задержки на запись);
`fstrim.timer` раз в неделю сообщает устройству о свободных блоках пачкой. Обычно выбирают
`fstrim.timer` (в Ubuntu включён по умолчанию).

</details>

**A13.** ⭐ «Диск расширили, а места нет»: перечисли слои, которые проверяешь, и команду для каждого.

<details><summary>Ответ</summary>

Диск (`lsblk`; нет — rescan для SCSI или проверка в облаке) → раздел (`growpart DISK N`)
→ PV (`pvresize PART`, смотреть `pvs`) → LV (`lvextend -l +100%FREE`, `vgs`) → ФС
(`resize2fs`/`xfs_growfs` или `-r`, `df -h`).

</details>

**A14.** Зачем после `mdadm --create` записывать массив в `mdadm.conf` и обновлять initramfs?

<details><summary>Ответ</summary>

Чтобы массив собирался под тем же именем при загрузке: без записи в `mdadm.conf` и
initramfs его соберут автоматически как `/dev/md127` (или не соберут до монтирования), и fstab
или приложение не найдут устройство.

</details>

**A15.** Что означают `[UU]`, `[U_]` и `(F)` в `/proc/mdstat`?

<details><summary>Ответ</summary>

`[UU]` — оба диска RAID1 в строю; `[U_]` — второй отсутствует, массив деградировал;
`(F)` — диск помечен как отказавший (faulty).

</details>

**A16.** Чем ZFS отличается от связки «mdadm + LVM + ext4»? Почему ZFS не входит в основное ядро Linux?

<details><summary>Ответ</summary>

ZFS объединяет RAID, менеджер томов и ФС: сквозные контрольные суммы всех данных с
самолечением при scrub, CoW-снапшоты без штрафа, сжатие, `send/receive` для репликации.
У связки mdadm + LVM + ext4 слои независимы и не знают о целостности данных друг друга.
ZFS под лицензией CDDL, несовместимой с GPL, поэтому ставится отдельным модулем.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  sudo lvextend -L +5G /dev/data/app && df -h /srv/app
```text
<details><summary>Ответ</summary>

⚠️ Без `-r` LV вырос, а ФС — нет: `df` покажет старый размер. Дорастить: `resize2fs` или
`xfs_growfs /srv/app` (или сразу `lvextend -r`).

</details>

```text:no-line-numbers
B2.  sudo xfs_growfs /dev/data/app          # XFS смонтирована в /srv/app
```text
<details><summary>Ответ</summary>

⚠️ `xfs_growfs` ожидает точку монтирования: `xfs_growfs /srv/app` (новые версии
принимают и устройство смонтированной ФС, но правило — mountpoint).

</details>

```text:no-line-numbers
B3.  sudo lvreduce -L 2G data/logs          # ext4, смонтирована, без -r
```text
<details><summary>Ответ</summary>

🔴 LV урезан раньше ФС: конец ext4 с данными отрезан, ФС повреждена. Правильно:
`umount` → `e2fsck -f` → `lvreduce -r -L 2G`. После такой ошибки — только восстановление из бэкапа
(иногда помогает немедленный `lvextend` обратно до прежнего размера, пока ничего не перезаписано).

</details>

```text:no-line-numbers
B4.  sudo lvcreate -s -n daily -L 200M data/app
```text
<details><summary>Ответ</summary>

⚠️ 200M под изменения за неделю активной записи — снапшот переполнится и станет invalid,
всё это время запись идёт с COW-штрафом. И это не бэкап: те же диски.

</details>

```text:no-line-numbers
     # «снапшот — наш ежедневный бэкап», его не удаляют неделю; на томе активная запись
```text
```text:no-line-numbers
B5.  sudo mount /dev/data/app_snap /mnt/snap          # XFS
```text
<details><summary>Ответ</summary>

⚠️ Дубликат UUID у XFS. `mount -o ro,nouuid /dev/data/app_snap /mnt/snap`.

</details>

```text:no-line-numbers
     # mount: wrong fs type, bad option, bad superblock …
```text
```text:no-line-numbers
B6.  sudo lvcreate --type thin-pool -L 5G -n pool data
```text
<details><summary>Ответ</summary>

⚠️ Выдано 20G виртуально при 5G реальных, без алертов. Когда пул дойдёт до 100%, все
четыре тома получат I/O errors. Нужны алерт на `data_percent`/`metadata_percent` > 80%,
autoextend в `lvm.conf` и свободное место в VG, `fstrim`.

</details>

```text:no-line-numbers
     for i in 1 2 3 4; do sudo lvcreate --type thin -V 5G --thinpool pool -n t$i data; done
```text
```text:no-line-numbers
     # мониторинга пула нет
```text
```text:no-line-numbers
B7.  sudo growpart /dev/vda3
```text
<details><summary>Ответ</summary>

⚠️ Синтаксис: `growpart /dev/vda 3` — диск и номер раздела через пробел.

</details>

```text:no-line-numbers
B8.  sudo growpart /dev/vda 3 && sudo lvextend -r -l +100%FREE /dev/ubuntu-vg/ubuntu-lv
```text
<details><summary>Ответ</summary>

⚠️ Пропущен `pvresize /dev/vda3`: раздел вырос, а PV о новом месте не знает, в VG `VFree = 0`.

</details>

```text:no-line-numbers
     # lvextend: «Insufficient free space»
```text
```text:no-line-numbers
B9.  # /etc/fstab
```text
<details><summary>Ответ</summary>

⚠️ `/dev/vdb1` может стать другим диском после добавления дисков; нет `nofail` — без
диска сервер не загрузится. Правильно: `UUID=… /srv/data ext4 defaults,nofail 0 2`.

</details>

```text:no-line-numbers
     /dev/vdb1  /srv/data  ext4  defaults  0 2
```text
```text:no-line-numbers
B10.  sudo mdadm --create /dev/md0 --level=1 --raid-devices=2 /dev/vde /dev/vdf
```text
<details><summary>Ответ</summary>

⚠️ Массив не записан в `mdadm.conf` и initramfs — после ребута он собрался как
`/dev/md127` (или позже), `/dev/md0` не существует, а без `nofail` загрузка падает в emergency.
Писать в fstab UUID ФС, добавить `nofail`, сохранить конфиг массива.

</details>

```text:no-line-numbers
     sudo mkfs.ext4 /dev/md0
```text
```text:no-line-numbers
     # в fstab: /dev/md0 /srv/raid ext4 defaults 0 2 ; ребут → emergency mode
```text
```text:no-line-numbers
B11.  sudo pvcreate /dev/vdc        # «диск же пустой»; lsblk не запускали
```text
<details><summary>Ответ</summary>

🔴 Без `lsblk -f`/`wipefs -n` можно затереть чужие данные («пустой» по мнению человека
диск может быть PV другой VG или ФС без точки монтирования). Сначала проверить сигнатуры.

</details>

```text:no-line-numbers
B12.  sudo vgreduce data /dev/vdb   # pvmove не делали; на vdb лежат экстенты LV app
```text
<details><summary>Ответ</summary>

⚠️ `vgreduce` откажется: на PV есть используемые экстенты. Сначала `pvmove /dev/vdb`.
(Если диск уже умер — `vgreduce --removemissing` с потерей данных LV, лежавших на нём.)

</details>

```text:no-line-numbers
B13.  # RAID5 из четырёх HDD по 16 ТБ, один диск умер, «заменим в понедельник»
```text
<details><summary>Ответ</summary>

🔴 RAID5 без одного диска не имеет избыточности: второй отказ или URE при rebuild
(на 48 ТБ оставшихся данных это вполне вероятно) — потеря массива. Менять сразу, держать hot
spare, для больших HDD — RAID6/RAID10, и бэкап актуален.

</details>

```text:no-line-numbers
B14.  sudo zpool create tank /dev/vde /dev/vdf      # «теперь данные защищены»
```text
<details><summary>Ответ</summary>

⚠️ Без `mirror` это stripe из двух дисков (аналог RAID0): отказ любого — потеря пула.
Правильно: `zpool create tank mirror /dev/disk/by-id/… /dev/disk/by-id/…`.

</details>


---

### Блок C. Практика


### C1. 🔑 LVM с нуля и расширение онлайн
**1.** Из `vdb` и `vdc` собери VG `data`, создай LV `app` на 3G (XFS) и `logs` на 50% свободного (ext4).

<details><summary>Ответ</summary>

```bash
sudo pvcreate /dev/vdb /dev/vdc && sudo vgcreate data /dev/vdb /dev/vdc
sudo lvcreate -n app -L 3G data && sudo lvcreate -n logs -l 50%FREE data
sudo mkfs.xfs /dev/data/app && sudo mkfs.ext4 /dev/data/logs
sudo mkdir -p /srv/app /srv/logs
echo "UUID=$(sudo blkid -s UUID -o value /dev/data/app)  /srv/app  xfs  defaults,noatime,nofail 0 0" | sudo tee -a /etc/fstab
echo "UUID=$(sudo blkid -s UUID -o value /dev/data/logs) /srv/logs ext4 defaults,noatime,nofail 0 2" | sudo tee -a /etc/fstab
sudo findmnt --verify && sudo systemctl daemon-reload && sudo mount -a
sudo lvextend -r -L +1G data/app && sudo lvextend -r -L +1G data/logs && df -h /srv/app /srv/logs
```text
</details>

**2.** Смонтируй через fstab по UUID с `nofail`, проверь `findmnt --verify` и `mount -a`.

<details><summary>Ответ</summary>

`sudo umount /srv/logs && sudo e2fsck -f /dev/data/logs && sudo lvreduce -r -L 1G data/logs
&& sudo mount /srv/logs`. Если бы сначала урезали LV — конец ФС с данными оказался бы за
границей тома: повреждение ФС. Для XFS — отказ: уменьшить нельзя, только новый LV меньшего
размера, перенос данных и переключение (с окном или через репликацию на уровне приложения).

</details>

**3.** Запусти фоновую запись в `/srv/app` и расширь оба тома на 1G онлайн. Покажи `df -h` до и после.

<details><summary>Ответ</summary>

) Лестница: `lsblk` (диск) → раздел → `pvs` → `vgs`/`lvs` → `df -h`.

</details>

### C2. Уменьшение ext4
Уменьши `logs` до 1G. Запиши последовательность и объясни, что было бы, если бы сначала уменьшил LV.
Что ответишь, если попросят то же самое для `app` (XFS)?

### C3. 🔑 Замена диска под нагрузкой
Добавь `vdd` в VG и переведи все экстенты с `vdb` на другие диски, не размонтируя тома. Докажи,
что `vdb` пуст, выведи его из VG и сними метку LVM. Сколько времени занял `pvmove` и что было
с латентностью записи (посмотри `iostat -x 1`)?

### C4. 🔑 Снапшот, восстановление файла и откат тома
**1.** Запиши `important.txt` в `/srv/app`, сними снапшот 500M, удали файл.

<details><summary>Ответ</summary>

```bash
sudo pvcreate /dev/vdb /dev/vdc && sudo vgcreate data /dev/vdb /dev/vdc
sudo lvcreate -n app -L 3G data && sudo lvcreate -n logs -l 50%FREE data
sudo mkfs.xfs /dev/data/app && sudo mkfs.ext4 /dev/data/logs
sudo mkdir -p /srv/app /srv/logs
echo "UUID=$(sudo blkid -s UUID -o value /dev/data/app)  /srv/app  xfs  defaults,noatime,nofail 0 0" | sudo tee -a /etc/fstab
echo "UUID=$(sudo blkid -s UUID -o value /dev/data/logs) /srv/logs ext4 defaults,noatime,nofail 0 2" | sudo tee -a /etc/fstab
sudo findmnt --verify && sudo systemctl daemon-reload && sudo mount -a
sudo lvextend -r -L +1G data/app && sudo lvextend -r -L +1G data/logs && df -h /srv/app /srv/logs
```text
</details>

**2.** Достань файл из снапшота (смонтируй read-only).

<details><summary>Ответ</summary>

`sudo umount /srv/logs && sudo e2fsck -f /dev/data/logs && sudo lvreduce -r -L 1G data/logs
&& sudo mount /srv/logs`. Если бы сначала урезали LV — конец ФС с данными оказался бы за
границей тома: повреждение ФС. Для XFS — отказ: уменьшить нельзя, только новый LV меньшего
размера, перенос данных и переключение (с окном или через репликацию на уровне приложения).

</details>

**3.** Верни весь том к состоянию снапшота через `lvconvert --merge`.

<details><summary>Ответ</summary>

) Лестница: `lsblk` (диск) → раздел → `pvs` → `vgs`/`lvs` → `df -h`.

</details>

**4.** Отдельно: сними снапшот на 100M и переполни его записью в оригинал. Что покажет `lvs`?

<details><summary>Ответ</summary>

```bash
echo "до ошибки" | sudo tee /srv/app/important.txt
sudo lvcreate -s -n app_snap -L 500M data/app && sudo rm /srv/app/important.txt
sudo mount -o ro,nouuid /dev/data/app_snap /mnt/snap && cat /mnt/snap/important.txt
sudo umount /mnt/snap /srv/app && sudo lvconvert --merge data/app_snap
sudo lvchange -an data/app && sudo lvchange -ay data/app && sudo mount /srv/app
ls /srv/app/important.txt            # файл вернулся
```text
Переполненный снапшот на 100M: в `lvs` `Data%` = 100 и атрибут `I` (invalid) в `lv_attr`
(`swi-I-s---`), в `dmesg` — сообщение device-mapper о том, что снапшот стал недействительным.

</details>

### C5. Thin provisioning
Создай thin-пул 3G и два thin-тома по 5G. Заполняй один из них, пока пул не подойдёт к 100%.
Что увидело приложение и `dmesg`? Как вернуть место после удаления файлов? Какой алерт поставишь?

### C6. 🔑 «Расширили диск, а места нет» — оба варианта
**1.** PV на целом диске: на хосте `sudo virsh blockresize storage-lab_stor1 vdd 8G`, в госте доведи
   новое место до ФС.

<details><summary>Ответ</summary>

```bash
sudo pvcreate /dev/vdb /dev/vdc && sudo vgcreate data /dev/vdb /dev/vdc
sudo lvcreate -n app -L 3G data && sudo lvcreate -n logs -l 50%FREE data
sudo mkfs.xfs /dev/data/app && sudo mkfs.ext4 /dev/data/logs
sudo mkdir -p /srv/app /srv/logs
echo "UUID=$(sudo blkid -s UUID -o value /dev/data/app)  /srv/app  xfs  defaults,noatime,nofail 0 0" | sudo tee -a /etc/fstab
echo "UUID=$(sudo blkid -s UUID -o value /dev/data/logs) /srv/logs ext4 defaults,noatime,nofail 0 2" | sudo tee -a /etc/fstab
sudo findmnt --verify && sudo systemctl daemon-reload && sudo mount -a
sudo lvextend -r -L +1G data/app && sudo lvextend -r -L +1G data/logs && df -h /srv/app /srv/logs
```text
</details>

**2.** PV в разделе: освободи `vdb`, создай GPT-раздел 1MiB–3GiB, сделай его PV и добавь в VG;
   затем расширь раздел до конца диска и доведи место до ФС.

<details><summary>Ответ</summary>

`sudo umount /srv/logs && sudo e2fsck -f /dev/data/logs && sudo lvreduce -r -L 1G data/logs
&& sudo mount /srv/logs`. Если бы сначала урезали LV — конец ФС с данными оказался бы за
границей тома: повреждение ФС. Для XFS — отказ: уменьшить нельзя, только новый LV меньшего
размера, перенос данных и переключение (с окном или через репликацию на уровне приложения).

</details>

**3.** Запиши лестницу проверок, которой пользовался.

<details><summary>Ответ</summary>

) Лестница: `lsblk` (диск) → раздел → `pvs` → `vgs`/`lvs` → `df -h`.

</details>

### C7. 🔑 RAID1 на mdadm и учения
**1.** Собери RAID1 из `vde` и `vdf`, создай ext4, запиши файл 300 МБ и его `sha256sum`.

<details><summary>Ответ</summary>

```bash
sudo pvcreate /dev/vdb /dev/vdc && sudo vgcreate data /dev/vdb /dev/vdc
sudo lvcreate -n app -L 3G data && sudo lvcreate -n logs -l 50%FREE data
sudo mkfs.xfs /dev/data/app && sudo mkfs.ext4 /dev/data/logs
sudo mkdir -p /srv/app /srv/logs
echo "UUID=$(sudo blkid -s UUID -o value /dev/data/app)  /srv/app  xfs  defaults,noatime,nofail 0 0" | sudo tee -a /etc/fstab
echo "UUID=$(sudo blkid -s UUID -o value /dev/data/logs) /srv/logs ext4 defaults,noatime,nofail 0 2" | sudo tee -a /etc/fstab
sudo findmnt --verify && sudo systemctl daemon-reload && sudo mount -a
sudo lvextend -r -L +1G data/app && sudo lvextend -r -L +1G data/logs && df -h /srv/app /srv/logs
```text
</details>

**2.** Сохрани конфиг массива так, чтобы он собирался после перезагрузки. Перезагрузись, проверь.

<details><summary>Ответ</summary>

`sudo umount /srv/logs && sudo e2fsck -f /dev/data/logs && sudo lvreduce -r -L 1G data/logs
&& sudo mount /srv/logs`. Если бы сначала урезали LV — конец ФС с данными оказался бы за
границей тома: повреждение ФС. Для XFS — отказ: уменьшить нельзя, только новый LV меньшего
размера, перенос данных и переключение (с окном или через репликацию на уровне приложения).

</details>

**3.** Проведи отказ `vdf`, замену на `vdg`, дождись окончания rebuild, сверь контрольную сумму.

<details><summary>Ответ</summary>

) Лестница: `lsblk` (диск) → раздел → `pvs` → `vgs`/`lvs` → `df -h`.

</details>

**4.** Напиши алерт для node_exporter на деградировавший массив.

<details><summary>Ответ</summary>

```bash
echo "до ошибки" | sudo tee /srv/app/important.txt
sudo lvcreate -s -n app_snap -L 500M data/app && sudo rm /srv/app/important.txt
sudo mount -o ro,nouuid /dev/data/app_snap /mnt/snap && cat /mnt/snap/important.txt
sudo umount /mnt/snap /srv/app && sudo lvconvert --merge data/app_snap
sudo lvchange -an data/app && sudo lvchange -ay data/app && sudo mount /srv/app
ls /srv/app/important.txt            # файл вернулся
```text
Переполненный снапшот на 100M: в `lvs` `Data%` = 100 и атрибут `I` (invalid) в `lv_attr`
(`swi-I-s---`), в `dmesg` — сообщение device-mapper о том, что снапшот стал недействительным.

</details>

### C8. ZFS: снапшот и send/receive
После уборки mdadm (`--zero-superblock`) создай пул `tank` mirror из `vde`+`vdf`, dataset
`tank/data` с lz4, сделай снапшоты `@s1` и `@s2` с изменениями между ними. Передай полный и
инкрементальный поток в файл (`zfs send … > file`) и восстанови его в `tank/restore`. Что
показывает `zpool status` после `zpool scrub`?

### C9. Уборка стенда
Верни `stor1` в исходное состояние без `snapshot restore`: размонтировать, убрать строки из
fstab, удалить LV/VG/PV, остановить и затереть md, уничтожить ZFS-пул, очистить сигнатуры.
Проверь, что после перезагрузки система грузится без ошибок.

---

### Блок D. Инциденты


**D1.** Облачный диск расширили с 50 до 100 ГБ, `df -h /` показывает 50 ГБ. Сервер: раздел
`vda3` → PV → `ubuntu-vg/ubuntu-lv` → ext4. Действия по шагам.

<details><summary>Ответ</summary>

`lsblk` — диск уже 100G? Для virtio (`vda`) и NVMe ядро обычно узнаёт само (`dmesg | grep -i capacity`);
для SCSI-диска `sdX` — rescan: `echo 1 | sudo tee /sys/class/block/sda/device/rescan`; если и так
не видно — проверить, завершилась ли операция в облаке. Затем
`sudo growpart /dev/vda 3` → `sudo pvresize /dev/vda3` → `sudo lvextend -r -l +100%FREE /dev/ubuntu-vg/ubuntu-lv`
→ `df -h /`. Всё онлайн. Перед операцией — снапшот диска в облаке.

</details>

**D2.** После перезагрузки сервер ушёл в emergency mode. Вчера добавляли диск под данные.

<details><summary>Ответ</summary>

Ошибка в fstab: диск указан как `/dev/sdX` (имена сдвинулись) или UUID неверный и нет
`nofail`. В emergency: `journalctl -xb` → какой mount упал, `mount -o remount,rw /`, поправить
fstab (UUID + `nofail`), `findmnt --verify`, `systemctl daemon-reload`, перезагрузка. На будущее —
`findmnt --verify` и `mount -a` до ребута.

</details>

**D3.** На сервере БД `/var/lib/postgresql` на 95%. VG свободного места нет, есть возможность
добавить диск. Как расширить без простоя?

<details><summary>Ответ</summary>

Добавить диск в VM, `pvcreate` → `vgextend` → `lvextend -r -L +N` на LV с PGDATA — онлайн.
Параллельно понять причину роста (WAL из-за сломанной архивации или слота репликации, bloat,
логи) — иначе через неделю снова.

</details>

**D4.** Приложение на thin-томе внезапно получило I/O errors, ФС ушла в read-only. Соседние
тома на той же VM тоже сломались.

<details><summary>Ответ</summary>

Переполнился thin-пул (или его метаданные), все thin-тома пула получили I/O errors.
Срочно: `lvs -o+data_percent,metadata_percent`, расширить пул (`lvextend -L +N VG/pool`,
для метаданных `--poolmetadatasize +N`) при наличии места в VG, иначе добавить PV;
затем `fsck` пострадавших ФС и перезапуск приложений. Потом — алерты, autoextend, fstrim, пересмотр overcommit.

</details>

**D5.** `cat /proc/mdstat` показывает `[U_]`. Когда это случилось — никто не знает.

<details><summary>Ответ</summary>

Сначала узнать, какой диск выпал и почему (`mdadm --detail`, `dmesg`, SMART), убедиться
в свежем бэкапе (избыточности нет!), заменить диск (`--remove`, `--add`), дождаться rebuild.
Причина «никто не знает» — нет мониторинга: `mdmonitor` с `MAILADDR` и алерт node_exporter на `node_md_disks`.

</details>

**D6.** После ребута массив называется `/dev/md127`, приложение не находит данные.

<details><summary>Ответ</summary>

Массив не записан в `mdadm.conf`/initramfs и собран автоматически с именем md127.
Сейчас: смонтировать по UUID ФС. Навсегда: `mdadm --detail --scan >> /etc/mdadm/mdadm.conf`
(убрать дубли), `update-initramfs -u`, в fstab — UUID ФС, а не `/dev/mdN`.

</details>

**D7.** Вечером сняли LVM-снапшот «на всякий случай» перед миграцией и забыли. Через три дня
жалобы на медленную запись, а снапшот в `lvs` помечен как invalid.

<details><summary>Ответ</summary>

Снапшот копил изменения три дня: запись шла с COW-штрафом, область переполнилась —
снапшот invalid, как точка отката бесполезен. Удалить `lvremove data/app_snap` — запись станет
нормальной. Правило: снапшот живёт только на время операции, есть автоудаление/алерт на
«старые» снапшоты, место под снапшот — с запасом или autoextend.

</details>

**D8.** SMART показывает растущие `Reallocated_Sector_Ct` на одном из дисков VG с LVM (без RAID).
Что делаешь?

<details><summary>Ответ</summary>

Диск деградирует, а избыточности нет. Сразу проверить бэкап; добавить новый диск в VG и
выполнить `pvmove` со старого (онлайн), `vgreduce` + `pvremove`, заменить диск. Если чтение уже
сыпет ошибками — `pvmove` может упасть на битых экстентах: восстанавливать эти LV из бэкапа.

</details>

**D9.** Во время `pvmove` VM перезагрузилась. Что с данными и как продолжить?

<details><summary>Ответ</summary>

`pvmove` использует временное зеркало и сохраняет прогресс в метаданных — данные не
потеряны. После загрузки `sudo pvmove` без аргументов продолжит перенос (или `pvmove --abort`
откатит); проверить `lvs -a` (временный LV `pvmove0`) и `pvs`.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Зачем нужен LVM? Что даёт по сравнению с обычными разделами?

<details><summary>Ответ</summary>

Гибкость: том из нескольких дисков, расширение онлайн, добавление и замена дисков без
   простоя (`pvmove`), снапшоты, thin provisioning. Разделы так не умеют.

</details>

**2.** Как расширить файловую систему на лету?

<details><summary>Ответ</summary>

`lvextend -r -L +NG VG/LV` — LV и ФС онлайн; без LVM — растёт раздел (`growpart`) и ФС
   (`resize2fs` для ext4, `xfs_growfs MOUNTPOINT` для XFS).

</details>

**3.** Можно ли уменьшить XFS? Что делать, если очень надо?

<details><summary>Ответ</summary>

Нельзя. Новый LV меньшего размера, перенос данных (`rsync -aHAX`, `xfsdump/xfsrestore`),
   переключение точки монтирования.

</details>

**4.** Диск в облаке расширили, а места не прибавилось. Что делаешь?

<details><summary>Ответ</summary>

Проверяю слои снизу вверх: диск (`lsblk`, rescan) → раздел (`growpart`) → PV (`pvresize`)
   → LV (`lvextend`) → ФС (`resize2fs`/`xfs_growfs` или `-r`). Всё онлайн.

</details>

**5.** Что такое снапшот LVM и почему это не бэкап?

<details><summary>Ответ</summary>

COW-снимок тома в той же VG: хранит изменённые блоки, при переполнении становится invalid,
   тормозит запись, умирает вместе с дисками. Это точка отката и источник для бэкапа, но
   бэкап — копия на другом носителе.

</details>

**6.** Что такое thin provisioning и чем он опасен?

<details><summary>Ответ</summary>

Том получает место из пула по мере записи, можно выдать больше, чем есть. Опасность —
   переполнение пула: I/O errors у всех томов. Нужны алерты, autoextend, fstrim.

</details>

**7.** ext4 или XFS — что выберешь и почему?

<details><summary>Ответ</summary>

Обычно дефолт дистрибутива: ext4 универсальна и уменьшается offline, XFS лучше на больших
   томах и параллельной записи, но не уменьшается. Под большие данные — XFS, если уменьшение
   не понадобится.

</details>

**8.** Как заменить диск без простоя?

<details><summary>Ответ</summary>

С LVM: `vgextend` новым диском → `pvmove` со старого → `vgreduce` → `pvremove`. С RAID:
   `--fail` → `--remove` → `--add` → rebuild.

</details>

**9.** Как устроен программный RAID в Linux и как понять, что он деградировал?

<details><summary>Ответ</summary>

mdadm собирает массив из дисков, состояние в `/proc/mdstat` и `mdadm --detail`, конфиг — в
   `mdadm.conf` + initramfs. Деградация — `[U_]`, `(F)`; ловят `mdmonitor` и алертом на
   `node_md_disks{state="failed"}`.

</details>

**10.** Что знаешь о ZFS?

<details><summary>Ответ</summary>

ФС + менеджер томов + RAID (mirror/raidz) в одном, контрольные суммы и scrub, CoW-снапшоты,
    сжатие, `send/receive` для репликации и бэкапа; требует RAM (ARC), лицензия CDDL — модуль
    вне основного ядра.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Собираю LVM из нескольких дисков и объясняю PV/VG/LV/PE
- [ ] ⭐ Расширяю LV и ФС онлайн одной командой, знаю разницу ext4 и XFS
- [ ] Уменьшаю ext4 в правильном порядке и объясняю, почему XFS не уменьшается
- [ ] ⭐ Меняю диск под нагрузкой через `pvmove`
- [ ] Делаю снапшот, достаю из него файл, откатываю том; объясняю, почему это не бэкап
- [ ] Понимаю thin provisioning и настраиваю защиту от переполнения пула
- [ ] ⭐ Прохожу лестницу «диск → раздел → PV → LV → ФС» в обоих вариантах
- [ ] Собираю RAID1, переживаю отказ диска, массив собирается после ребута, есть алерт
- [ ] Делаю ZFS-пул, снапшоты и send/receive
- [ ] Убираю за собой стенд так, что система грузится без ошибок
