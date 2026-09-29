---
title: "02. KVM, QEMU и libvirt руками: virsh, cloud-init, qcow2, снапшоты"
description: "Блок → Виртуализация on-prem → тема 02. Опирается на 01virtualizationintro.md,"
---

# 02. KVM, QEMU и libvirt руками: virsh, cloud-init, qcow2, снапшоты

> Блок → Виртуализация on-prem → тема 02. Опирается на [01_virtualization_intro.md](/virtualization/01-virtualization-intro),
> [../Linux/00_vagrant.md](/linux/00-vagrant) (libvirt уже стоит, группа `libvirt` настроена),
> [../Linux/09_devices.md](/linux/09-devices) (имена дисков `vda`/`sda`) и
> [../Linux/10_the_filesystem.md](/linux/10-the-filesystem) (разделы, ФС, расширение).
>
> **После темы ты умеешь:** управлять VM через `virsh`, поднимать VM из облачного образа
> с cloud-init одной командой `virt-install`, работать с qcow2 и overlay-дисками через
> `qemu-img`, заводить storage pools, делать и откатывать снапшоты (и понимать их подводные
> камни), менять CPU/RAM, объяснять живую миграцию и пользоваться `qemu-guest-agent`.

---

## 🗺️ Карта темы

```text
  облачный образ noble-server-cloudimg-amd64.img  (qcow2, ~600 МБ, без пароля)
          │  sudo cp → /var/lib/libvirt/images/noble-base.qcow2   (read-only база)
          ▼
  virsh vol-create-as ... --backing-vol   ──►  vm1.qcow2 (overlay, пишутся только изменения)
          │
  user-data + meta-data ──► virt-install --cloud-init ──► ISO «cidata» на первый старт
          │
          ▼
  VM vm1 (XML в /etc/libvirt/qemu/vm1.xml)
     ├── virsh start/shutdown/destroy/console/edit      жизненный цикл
     ├── virsh snapshot-*                                 снапшоты (internal / external)
     ├── virsh setvcpus/setmem                            ресурсы
     ├── virsh migrate --live                             переезд на другой хост
     └── qemu-guest-agent  ◄── virtio-serial ──►  IP, fsfreeze, корректный shutdown
```text
---

## 1. Где что лежит

| Путь | Что там | Правило |
|------|---------|---------|
| `/etc/libvirt/qemu/&lt;vm&gt;.xml` | Постоянное описание VM | Не править руками — только `virsh edit` |
| `/etc/libvirt/qemu/networks/` | Сети libvirt (+ `autostart/` — симлинки) | `virsh net-edit` |
| `/etc/libvirt/storage/` | Описания storage pools | `virsh pool-edit` |
| `/var/lib/libvirt/images/` | Пул `default`: диски VM | Место кончается здесь первым |
| `/var/lib/libvirt/boot/` | ISO, которые загрузил virt-install | Чистить от старых |
| `/var/lib/libvirt/qemu/nvram/` | Переменные UEFI у VM с UEFI | Удаляется `undefine --nvram` |
| `/var/lib/libvirt/qemu/snapshot/&lt;vm&gt;/` | Метаданные снапшотов | — |
| `/var/lib/libvirt/dnsmasq/` | Аренды DHCP сетей libvirt | `virsh net-dhcp-leases` удобнее |
| `/var/log/libvirt/qemu/&lt;vm&gt;.log` | Лог QEMU: полная командная строка, ошибки старта | ⭐ первое место при «VM не стартует» |
| `/run/libvirt/qemu/` | Живое состояние запущенных VM | Только читать |

```bash
virsh uri                           # qemu:///system (см. тему 01)
virsh version                       # версии libvirt и QEMU
virsh nodeinfo                      # CPU и RAM хоста глазами libvirt
virsh capabilities | less           # что умеет хост: модели CPU, типы машин
```text
---

## 2. virsh: жизненный цикл VM

| Команда | Что делает |
|---------|-----------|
| `virsh list --all` | Все VM, включая выключенные |
| `virsh start vm1` | Запустить |
| `virsh shutdown vm1` | ⭐ Корректно выключить: ACPI-сигнал «нажата кнопка питания» (или агент) |
| `virsh destroy vm1` | ⭐ Выдернуть шнур: мгновенно убить процесс QEMU. Диск и XML **не удаляются** |
| `virsh reboot vm1` / `reset vm1` | Мягкая перезагрузка / жёсткий reset |
| `virsh suspend vm1` / `resume vm1` | Заморозить vCPU в памяти / разморозить |
| `virsh managedsave vm1` | Сохранить RAM на диск и выключить (как гибернация); `start` восстановит |
| `virsh autostart vm1` / `--disable` | Стартовать вместе с хостом |
| `virsh console vm1` | Серийная консоль; выход — `Ctrl+]` |
| `virsh dominfo vm1` / `domstate vm1` | Сводка / состояние |
| `virsh dumpxml vm1` | Полный XML |
| `virsh edit vm1` | Открыть XML в `$EDITOR`, проверить и применить (с перезапуска VM) |
| `virsh domifaddr vm1` | IP гостя (из аренд DHCP или от агента) |
| `virsh domiflist vm1` / `domblklist vm1` | Сетевые интерфейсы (vnetX) / диски |
| `virsh undefine vm1` | Удалить описание VM (диски остаются) |
| `virsh undefine vm1 --remove-all-storage --nvram` | Удалить VM вместе с дисками и UEFI-переменными |

```text
 shutdown  ─►  гость получает ACPI, сам останавливает службы, пишет буферы на диск   ✅
 destroy   ─►  процесс QEMU убит сразу: как выдернуть питание. Незаписанное — потеряно ⚠️
               используют, когда гость завис и на shutdown не реагирует
```text
> ⚠️ Слово `destroy` пугает, но VM не удаляет — просто жёстко выключает. Удаляет `undefine`.
> А вот `undefine --remove-all-storage` без снапшота/бэкапа — точка невозврата.

---

## 3. Первая VM из облачного образа за 2 минуты

**Облачный образ** (cloud image) — готовый установленный диск дистрибутива: без пароля,
с `cloud-init` внутри. Установщик не нужен: подсовываешь образу настройки (пользователь,
SSH-ключ, пакеты) — и через минуту VM готова. Так работают все облака.

### 3.1. Скачать и проверить образ

```bash
mkdir -p ~/labs/virt/images && cd ~/labs/virt/images
wget https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
wget https://cloud-images.ubuntu.com/noble/current/SHA256SUMS
sha256sum -c --ignore-missing SHA256SUMS        # noble-server-cloudimg-amd64.img: OK
qemu-img info noble-server-cloudimg-amd64.img   # file format: qcow2, virtual size: 3.5 GiB

sudo cp noble-server-cloudimg-amd64.img /var/lib/libvirt/images/noble-base.qcow2
virsh pool-refresh default                      # чтобы libvirt увидел файл
virsh vol-list default
```text
> 💡 Ubuntu 24.04 (noble) выбран потому, что его знает osinfo-db на хосте Ubuntu 24.04.
> Для 26.04 (resolute) образ лежит в `.../resolute/current/`, а в `--osinfo` при старой
> osinfo-db подставляй `linux2024`.

### 3.2. Диск VM — overlay поверх базы

```bash
virsh vol-create-as default vm1.qcow2 20G --format qcow2 \
  --backing-vol /var/lib/libvirt/images/noble-base.qcow2 --backing-vol-format qcow2
qemu-img info -U --backing-chain /var/lib/libvirt/images/vm1.qcow2
```text
Overlay весит килобайты, виртуальный размер — 20 ГБ. При первом старте cloud-init сам
растянет корневой раздел на весь диск (модуль `growpart`).

### 3.3. cloud-init: user-data и meta-data

```bash
mkdir -p ~/labs/virt/lab1 && cd ~/labs/virt/lab1
cat > user-data.yaml <&lt;EOF
#cloud-config
hostname: vm1
users:
  - name: devops
    groups: [sudo]
    shell: /bin/bash
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    ssh_authorized_keys:
      - $(cat ~/.ssh/id_ed25519.pub)
package_update: true
packages: [qemu-guest-agent]
runcmd:
  - [systemctl, start, qemu-guest-agent]
EOF

cat&gt; meta-data.yaml <&lt;EOF
instance-id: vm1-001
local-hostname: vm1
EOF
```text
- `user-data` — что сделать (первая строка **обязана** быть `#cloud-config`).
- `meta-data` — кто ты: `instance-id` (сменился → cloud-init считает VM новой и отработает
  заново), имя хоста. Подробно — тема 06.

### 3.4. virt-install

```bash
virt-install \
  --name vm1 \
  --memory 2048 --vcpus 2 \
  --osinfo ubuntu24.04 \
  --disk vol=default/vm1.qcow2,bus=virtio \
  --network network=virt-lab,model=virtio \
  --cloud-init user-data=user-data.yaml,meta-data=meta-data.yaml \
  --import \
  --graphics none --noautoconsole
```text
| Флаг | Зачем |
|------|-------|
| `--osinfo ubuntu24.04` | ⭐ Обязателен в virt-install 4.x: по нему выбираются правильные дефолты (q35, virtio). Список — `virt-install --osinfo list` |
| `--disk vol=pool/volume` | Взять готовый том из пула (или `path=/путь,format=qcow2`) |
| `--network network=virt-lab` | Сеть стенда из [00_INDEX.md](/virtualization/); без неё — `network=default` |
| `--cloud-init user-data=...,meta-data=...` | virt-install сам соберёт ISO `cidata` и подключит его только на первый старт |
| `--import` | Не устанавливать ОС, а загрузиться с готового диска (с `--cloud-init` подразумевается) |
| `--graphics none` | Без VNC/SPICE, только серийная консоль |
| `--noautoconsole` | Не подключаться к консоли, вернуть терминал сразу |

По умолчанию virt-install 4.x добавит `q35`, `<cpu mode='host-passthrough'/&gt;`, virtio-rng,
balloon и канал для guest agent — проверь в `virsh dumpxml vm1`.

```bash
virsh console vm1                       # смотреть загрузку; Ctrl+] — выйти
virsh domifaddr vm1                     # IP из аренды DHCP
ssh devops@&lt;IP&gt; cloud-init status --wait --long    # status: done, errors: []
ssh devops@&lt;IP&gt; 'lsblk; df -h /'        # vda растянут до 20G
```text
### 3.5. Вариант без `--cloud-init`: seed-ISO руками

Старые virt-install, Proxmox, VMware и любые гипервизоры понимают тот же формат NoCloud —
ISO с меткой тома `cidata`:
```bash
sudo apt install -y cloud-image-utils                 # даёт cloud-localds
cloud-localds seed.iso user-data.yaml meta-data.yaml  # + -N network-config.yaml при нужде
# или без cloud-localds:
# xorriso -as mkisofs -o seed.iso -V cidata -J -r user-data meta-data   (файлы строго с этими именами)
sudo cp seed.iso /var/lib/libvirt/images/vm1-seed.iso && virsh pool-refresh default

virt-install --name vm1 --memory 2048 --vcpus 2 --osinfo ubuntu24.04 \
  --disk vol=default/vm1.qcow2,bus=virtio \
  --disk /var/lib/libvirt/images/vm1-seed.iso,device=cdrom \
  --network network=virt-lab,model=virtio --import --graphics none --noautoconsole
```text
### 3.6. Убрать за собой

```bash
virsh destroy vm1
virsh undefine vm1 --remove-all-storage     # удалит vm1.qcow2, но НЕ базу noble-base.qcow2
```text
---

## 4. qcow2 и qemu-img

| | raw | qcow2 |
|---|-----|-------|
| Что это | Байт в байт как диск | Формат QEMU с метаданными |
| Тонкий (thin) | Только если ФС хоста поддерживает sparse | Да, растёт по мере записи |
| Backing files (overlay) | Нет | ⭐ Да |
| Встроенные снапшоты | Нет | Да (internal) |
| Сжатие, шифрование | Нет | Да |
| Скорость | Максимальная | Чуть ниже (на современных QEMU разница небольшая) |
| Где | LVM, Ceph RBD, высоконагруженные БД | Файловые хранилища, шаблоны, стенды |

### Backing files и overlay

```text
  noble-base.qcow2   (база, только чтение — НИКОГДА не запускать и не менять)
        ▲          ▲
        │          │
  vm1.qcow2    vm2.qcow2     ← overlay: только изменённые блоки конкретной VM
                              чтение: нет блока в overlay → читаем из базы
```text
Так в Proxmox работают linked clones, в OpenStack — диски из образов, в Vagrant — боксы.

```bash
qemu-img create -f qcow2 disk.qcow2 20G                                   # пустой тонкий диск
qemu-img create -f qcow2 -b noble-base.qcow2 -F qcow2 vm2.qcow2 20G       # overlay; -F обязателен
qemu-img info --backing-chain vm2.qcow2                                   # вся цепочка
qemu-img info -U vm1.qcow2               # -U (--force-share): читать диск работающей VM
qemu-img resize vm2.qcow2 +10G           # увеличить (VM выключена!)
qemu-img convert -O qcow2 vm2.qcow2 vm2-flat.qcow2        # «сплющить» цепочку в один файл
qemu-img convert -O qcow2 -c big.qcow2 small.qcow2        # сжать (шаблоны, передача)
qemu-img convert -f vmdk -O qcow2 app.vmdk app.qcow2      # ⭐ миграция с VMware
qemu-img check vm2.qcow2                  # проверить целостность (VM выключена)
```text
> ⚠️ `qemu-img create -b base.qcow2` без `-F qcow2` на современных QEMU — ошибка
> `Backing file specified without backing format`. Раньше формат угадывался, и это было
> дырой в безопасности.

После увеличения диска **внутри гостя** растяни раздел и ФС
(подробно — [../Linux/10_the_filesystem.md](/linux/10-the-filesystem)):
```bash
sudo growpart /dev/vda 1      # раздел 1 — на весь диск (пакет cloud-guest-utils)
sudo resize2fs /dev/vda1      # ext4; для XFS — sudo xfs_growfs /
```text
Онлайн, без выключения: `virsh blockresize vm1 vda 30G`, затем то же внутри гостя.

> 💡 `libguestfs-tools` — «швейцарский нож» для образов без запуска VM:
> `virt-customize -a img --install qemu-guest-agent`, `virt-sparsify`, `virt-cat`, `virt-df`.

---

## 5. Storage pools и volumes

**Пул** — место, где libvirt хранит диски: каталог, LVM, NFS, iSCSI, Ceph RBD, ZFS.
**Том (volume)** — диск в пуле. Работа через пулы даёт единый API: Terraform и virt-install
создают тома, не зная, что под ними — каталог или LVM.

| Тип пула | Что это | Когда |
|----------|---------|-------|
| `dir` | Каталог (`/var/lib/libvirt/images`) | Стенд, один хост |
| `logical` | Группа томов LVM | Быстро, без слоя ФС |
| `netfs` | NFS/CIFS | Общее хранилище → живая миграция без копирования дисков |
| `iscsi` / `iscsi-direct` | LUN с СХД | Энтерпрайз |
| `rbd` | Ceph | Распределённое хранилище |
| `zfs` | ZFS-пул | Снапшоты и сжатие на уровне ФС |

```bash
virsh pool-list --all --details
virsh pool-define-as vmstore dir --target /srv/vmstore    # описать пул-каталог
virsh pool-build vmstore                                  # создать каталог
virsh pool-start vmstore && virsh pool-autostart vmstore
virsh pool-autostart default                              # ⚠️ на стенде default мог быть без автостарта

virsh vol-create-as vmstore data1.qcow2 10G --format qcow2
virsh vol-list vmstore --details
virsh vol-info data1.qcow2 --pool vmstore
virsh vol-upload --pool vmstore data1.qcow2 ./local.qcow2 # залить файл в том (удалённый хост)
virsh vol-delete data1.qcow2 --pool vmstore
virsh pool-refresh default                                # после ручного cp в каталог пула

# подключить второй диск к работающей VM
virsh attach-disk vm1 /srv/vmstore/data1.qcow2 vdb --subdriver qcow2 --persistent
```text
---

## 6. Снапшоты

| | Internal | External |
|---|----------|----------|
| Где живёт | Внутри того же qcow2 | Новый файл-overlay; старый диск становится базой |
| Что сохраняет | Диск (+ RAM, если VM работает) | Диск (`--disk-only`) или диск + RAM (`--memspec`) |
| Формат диска | Только qcow2 | Любой (overlay всегда qcow2) |
| Удаление/откат в libvirt | Давно | Удаление — с libvirt 9.0, откат — с 9.9 |
| Минусы | VM замирает на время сохранения RAM; у VM с UEFI поддержаны только с libvirt 10.9 | Цепочки файлов; их надо сливать (blockcommit) |
| Кто использует | virsh по умолчанию для qcow2 | Бэкап-системы, oVirt, OpenStack |

```bash
# internal (по умолчанию): у работающей VM сохранится и память
virsh snapshot-create-as vm1 --name before-upgrade --description "перед apt full-upgrade"
virsh snapshot-list vm1 --tree
virsh snapshot-revert vm1 before-upgrade
virsh snapshot-delete vm1 before-upgrade

# external, только диск, с заморозкой ФС через guest agent
virsh snapshot-create-as vm1 --name pre-deploy --disk-only --atomic --quiesce
virsh domblklist vm1                 # VM теперь пишет в новый overlay-файл
virsh snapshot-delete vm1 pre-deploy # libvirt ≥ 9.0 сам сольёт overlay обратно

# ручное слияние (старые libvirt или «осиротевшие» overlay)
virsh blockcommit vm1 vda --active --pivot --verbose
virsh snapshot-delete vm1 pre-deploy --metadata   # убрать только запись о снапшоте
```text
**Подводные камни:**
- ⭐ **Снапшот — не бэкап.** Он лежит на том же хранилище: умер диск/массив — умерли и VM, и снапшоты.
- Длинная цепочка overlay замедляет I/O и раздувает место. Снапшот — на часы-дни, не на месяцы.
- Снапшот работающей БД без `--quiesce` (fsfreeze через агент) — это состояние «после
  выдернутого шнура»: БД восстановится по журналу, но лучше так не рассчитывать.
- Откат VM, которая часть распределённой системы (реплика БД, нода etcd/k8s, контроллер
  домена), ломает согласованность: остальные узлы «ушли вперёд».
- После отката на снапшот с памятью у гостя «прыгают» часы — нужен NTP/chrony.

---

## 7. CPU и RAM

```bash
virsh dominfo vm1                         # CPU(s), Max memory, Used memory
virsh vcpucount vm1                       # current/maximum, live/config
virsh setvcpus vm1 4 --config             # со следующего старта
virsh setvcpus vm1 4 --maximum --config   # поднять максимум → потом можно --live до него
virsh setmaxmem vm1 8G --config           # максимум памяти (VM выключена)
virsh setmem vm1 4G --live --config       # в пределах максимума, через balloon
virt-install ... --vcpus 4,sockets=1,cores=4,threads=1   # топология (важно для лицензий по сокетам)
```text
**CPU mode** — что гость видит вместо процессора:

| Режим | Что видит гость | Миграция | Когда |
|-------|-----------------|----------|-------|
| `host-passthrough` | Ровно CPU хоста | Только на идентичный CPU | Стенд, nested, максимум скорости |
| `host-model` | Похожая модель с флагами хоста | Между похожими хостами | Разумный дефолт для кластеров |
| `custom` (например, `x86-64-v2`) | Фиксированная модель | Между любыми хостами, которые её тянут | Разнородный кластер |

**Overcommit** — выделено больше, чем есть физически:
- **CPU** переподписывают спокойно (vCPU — поток, большинство простаивает). Признак
  перегруза — **steal time** в госте (`%st` в `top`, колонка `st` в `vmstat 1`): vCPU готов
  работать, но ждёт физическое ядро. Соотношение vCPU:ядро выбирают по нагрузке и мониторингу.
- **RAM** переподписывать опасно. Механизмы: balloon (хост просит гостя отдать память),
  KSM (слияние одинаковых страниц разных VM), swap хоста. Кончилась память — OOM-killer
  хоста убивает самый толстый процесс QEMU, и VM «сама выключилась».
- **Hugepages** (кратко): страницы по 2 МБ/1 ГБ вместо 4 КБ — меньше промахов TLB для
  больших VM (БД, NFV). `echo 2048 | sudo tee /proc/sys/vm/nr_hugepages` (4 ГБ из 2-МБ страниц)
  и в XML `&lt;memoryBacking&gt;&lt;hugepages/&gt;</memoryBacking>`. Память под них резервируется заранее.
- **NUMA:** на двухсокетном хосте большую VM держат в пределах одного сокета
  (`virsh vcpupin`, `virsh numatune`), иначе память «ходит» через межсокетную шину.

---

## 8. Живая миграция (live migration)

```text
 kvm01                                        kvm02
 ┌───────────┐  1. копируем всю RAM           ┌───────────┐
 │  vm1  ────┼───────────────────────────────►│  vm1'     │  (приёмник на паузе)
 │ работает  │  2. докопируем «грязные»       │           │
 │           │     страницы, пока их мало     │           │
 │  пауза ◄──┼── 3. стоп на миллисекунды, ────┼──► старт  │
 └───────────┘     последние страницы + CPU   └───────────┘
     диск: общий (NFS/Ceph/SAN) — не копируется;  локальный — --copy-storage-all (долго)
```text
```bash
virsh migrate --live --persistent --undefinesource --verbose \
  vm1 qemu+ssh://admin@kvm02/system
virsh domjobinfo vm1            # прогресс: сколько осталось, скорость, «грязные» страницы
# если VM пишет в память быстрее, чем сеть копирует: --auto-converge (притормаживает vCPU)
# или --postcopy (переключиться сразу, дотягивать страницы по требованию — рискованнее)
```text
Требования: libvirt/QEMU на обоих хостах, SSH/TLS между ними, **общее хранилище** или копия
дисков, та же сеть (VLAN/bridge с тем же именем), совместимый CPU (см. таблицу выше).
В Proxmox это `qm migrate 101 pve2 --online`, в VMware — vMotion.

---

## 9. qemu-guest-agent

Агент внутри гостя, который общается с хостом через virtio-serial
(канал `org.qemu.guest_agent.0` — virt-install добавляет его сам).

```bash
# в госте (у нас ставит cloud-init)
sudo apt install -y qemu-guest-agent && sudo systemctl start qemu-guest-agent

# на хосте
virsh qemu-agent-command vm1 '{"execute":"guest-ping"}'   # {"return":{&#125;&#125; — агент жив
virsh domifaddr vm1 --source agent       # IP от агента: все интерфейсы, любые сети
virsh guestinfo vm1 --os --hostname      # ОС, версия, имя
virsh domfsinfo vm1                      # смонтированные ФС гостя
virsh domfsfreeze vm1 && virsh domfsthaw vm1   # заморозить/разморозить ФС (так делает --quiesce)
virsh shutdown vm1 --mode agent          # выключить через агент, а не ACPI
virsh set-user-password vm1 devops 'NewPass!'   # сменить пароль без SSH
```text
Без агента: IP знаешь только из DHCP своей сети, снапшоты без fsfreeze, shutdown только
по ACPI. В Proxmox агент включают опцией `agent: 1`, в VMware его аналог — VMware Tools
(`open-vm-tools`).

---

## 10. Грабли

| Симптом | Причина | Что делать |
|---------|---------|-----------|
| `Cannot access storage file ... Permission denied` | Диск в `$HOME`, куда `libvirt-qemu`/AppArmor не пускают | Держать диски в пуле (`/var/lib/libvirt/images`) |
| VM из облачного образа: логин не пускает | В образе нет пароля, cloud-init не получил данные | Проверить `--cloud-init`/seed-ISO, первую строку `#cloud-config`, лог `/var/log/cloud-init.log` |
| cloud-init «не применил» новый user-data | `instance-id` тот же — VM считается старой | Сменить `instance-id` или `cloud-init clean` в госте |
| `Backing file specified without backing format` | Нет `-F qcow2` | `qemu-img create -b base -F qcow2 ...` |
| Все VM разом сломались после «обновил базовый образ» | Изменили backing file, от которого зависят overlay | База — только чтение; новый образ = новый файл |
| `qemu-img: Failed to get shared "write" lock` | Диск используется работающей VM | Читать с `-U`; менять — только выключив VM |
| Место на хосте тает | Тонкие диски растут, снапшоты и overlay копятся | `virsh vol-list --details`, чистить снапшоты, `virt-sparsify` |
| `virsh shutdown` ничего не делает | В госте нет ACPI-обработчика или гость завис | `--mode agent`, подождать, в крайнем случае `destroy` |
| `domifaddr` пустой | Не та сеть (bridge без DHCP libvirt) или нет агента | `--source agent`, `virsh net-dhcp-leases &lt;сеть&gt;` |
| Миграция: `unsupported configuration: ... CPU` | `host-passthrough` на разных процессорах | `host-model` или общая модель CPU |

---

## 💼 Как это в DevOps

- **VM из облачного образа + cloud-init** — базовый паттерн везде: libvirt, Proxmox, OpenStack,
  VMware, облака. Один `user-data` работает на всех платформах.
- **Шаблон (база) + overlay/linked clone** — так раздают десятки одинаковых VM за секунды.
  Базу обновляют выпуском нового образа (тема 06), а не правкой старого.
- **Перед рискованной операцией** (обновление ОС, миграция БД) — снапшот, после проверки —
  удалить. Бэкап при этом делается отдельно и проверяется восстановлением.
- **«VM тормозит»** — смотри по слоям: steal time и память в госте → нагрузка хоста
  (`top` по процессам QEMU, `iostat`) → хранилище → соседи по хосту.
- `virsh` и `qemu-img` нужны даже в Proxmox: там те же QEMU и qcow2, и при авариях дело
  часто доходит до `qemu-img info/convert` руками.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Все VM | `virsh list --all` |
| Корректно / жёстко выключить | `virsh shutdown vm` / `virsh destroy vm` |
| Автостарт | `virsh autostart vm` |
| Консоль | `virsh console vm` (выход `Ctrl+]`) |
| XML / правка | `virsh dumpxml vm` / `virsh edit vm` |
| IP гостя | `virsh domifaddr vm [--source agent]` |
| VM из облачного образа | `virt-install --import --osinfo ... --cloud-init user-data=...,meta-data=...` |
| Overlay-диск | `virsh vol-create-as default vm.qcow2 20G --format qcow2 --backing-vol BASE --backing-vol-format qcow2` |
| Инфо о диске | `qemu-img info [-U] --backing-chain disk.qcow2` |
| Увеличить диск | `qemu-img resize disk +10G` (выкл.) / `virsh blockresize vm vda 30G` (вкл.), в госте `growpart` + `resize2fs` |
| vmdk → qcow2 | `qemu-img convert -f vmdk -O qcow2 in.vmdk out.qcow2` |
| Снапшот / откат | `virsh snapshot-create-as vm --name X` / `virsh snapshot-revert vm X` |
| External снапшот | `virsh snapshot-create-as vm --name X --disk-only --atomic --quiesce` |
| Изменить vCPU/RAM | `virsh setvcpus vm N --config`, `virsh setmem vm 4G --live --config` |
| Живая миграция | `virsh migrate --live --persistent --undefinesource vm qemu+ssh://host/system` |
| Проверить агента | `virsh qemu-agent-command vm '{"execute":"guest-ping"}'` |
| Удалить VM с дисками | `virsh undefine vm --remove-all-storage --nvram` |
| Лог старта VM | `/var/log/libvirt/qemu/&lt;vm&gt;.log` |

---

## 🧠 Что запомнить

1. VM в libvirt = XML (`/etc/libvirt/qemu/`) + диски в пуле; правят через `virsh edit`, не руками.
2. `shutdown` — вежливо через ACPI, `destroy` — выдернуть шнур, `undefine` — удалить описание.
3. Облачный образ + cloud-init (`user-data` + `meta-data`) = готовая VM без установщика.
4. `virt-install --import --cloud-init ... --osinfo ...` — одна команда на VM; `--osinfo` обязателен.
5. qcow2 = тонкий диск + backing files; база только для чтения, изменения — в overlay.
6. `qemu-img`: `info --backing-chain`, `resize`, `convert` (в том числе vmdk → qcow2), `-F` при `-b`.
7. Снапшот — не бэкап; internal живёт в qcow2, external — отдельный overlay, который надо сливать.
8. CPU переподписывают умеренно (следи за steal time), RAM — нельзя без запаса (OOM убьёт VM).
9. Живая миграция: общее хранилище, та же сеть, совместимый CPU (`host-passthrough` мешает).
10. `qemu-guest-agent` даёт IP, fsfreeze для снапшотов и корректный shutdown — ставь в каждый шаблон.

➡️ Дальше: [03_virt_networking.md](/virtualization/03-virt-networking) · задачи: 02_kvm_qemu_libvirt_tasks.md


---

### Блок A. Теория


**A1.** Где libvirt хранит описание VM? Почему его не правят в редакторе напрямую?

<details><summary>Ответ</summary>

В `/etc/libvirt/qemu/&lt;vm&gt;.xml`. Демон держит конфигурацию в памяти и не перечитывает
файл: правка руками не применится, а при следующей записи libvirt её затрёт. `virsh edit`
проверяет XML и сохраняет через API.

</details>

**A2.** ⭐ Чем отличаются `virsh shutdown`, `virsh destroy` и `virsh undefine`?

<details><summary>Ответ</summary>

`shutdown` — корректное выключение: ACPI-сигнал (или агент), гость сам
останавливает службы. `destroy` — мгновенно убить процесс QEMU, как выдернуть питание;
диск и описание остаются. `undefine` — удалить описание VM (с `--remove-all-storage` — и диски).

</details>

**A3.** Что такое облачный образ? Чем он отличается от установочного ISO?

<details><summary>Ответ</summary>

Облачный образ — уже установленная система (qcow2/raw) без пароля, с cloud-init,
который при первом старте берёт настройки из источника данных. ISO — установщик: нужно
пройти установку. Облачный образ поднимается за минуту и одинаково на всех платформах.

</details>

**A4.** Зачем cloud-init два файла — `user-data` и `meta-data`? Какую роль играет `instance-id`?

<details><summary>Ответ</summary>

`user-data` — что сделать (пользователи, ключи, пакеты, команды). `meta-data` —
сведения об экземпляре: `instance-id`, имя хоста. По `instance-id` cloud-init понимает, первый
ли это запуск этого экземпляра: сменился — модули «на экземпляр» выполнятся заново.

</details>

**A5.** Зачем virt-install флаг `--osinfo`? Что будет, если его не указать?

<details><summary>Ответ</summary>

По `--osinfo` virt-install выбирает дефолты под ОС: тип машины (q35), virtio-устройства,
объём памяти по умолчанию, UEFI и т.д. В virt-install 4.x без него (если ОС не определилась по
носителю) — фатальная ошибка с подсказкой `--osinfo detect=on,require=off`.

</details>

**A6.** Сравни raw и qcow2. Когда что выбирать?

<details><summary>Ответ</summary>

raw — диск байт в байт: максимальная скорость, но без backing files и встроенных
снапшотов; для LVM, Ceph RBD, нагруженных БД. qcow2 — тонкий, с backing files, снапшотами,
сжатием; для файловых хранилищ, шаблонов, стендов.

</details>

**A7.** ⭐ Что такое backing file и overlay? Почему базовый образ должен быть только для чтения?

<details><summary>Ответ</summary>

Backing file — базовый образ, overlay — qcow2, который хранит только изменённые блоки
и читает остальное из базы. Если база изменится, данные overlay начнут указывать на чужие
блоки — все зависимые VM испортятся. Поэтому база только для чтения, а обновление — новый файл.

</details>

**A8.** Зачем нужны storage pools, если можно просто указать путь к файлу?

<details><summary>Ответ</summary>

Пул даёт единый API к разным хранилищам (каталог, LVM, NFS, iSCSI, Ceph): тома создают,
загружают и удаляют одинаково — virt-install, Terraform, virsh. Плюс учёт места и автостарт.

</details>

**A9.** Чем internal-снапшот отличается от external? Какие ограничения у каждого?

<details><summary>Ответ</summary>

Internal живёт внутри того же qcow2 и может включать RAM; просто, но только qcow2,
VM замирает на время сохранения памяти, у UEFI-VM поддержка только с libvirt 10.9.
External создаёт новый overlay, старый файл становится базой; работает с любым форматом, но
цепочку надо сливать (`blockcommit`); удаление поддержано с libvirt 9.0, откат — с 9.9.

</details>

**A10.** ⭐ Почему снапшот — не бэкап? Назови ещё три подводных камня снапшотов.

<details><summary>Ответ</summary>

Снапшот лежит на том же хранилище — погибнет вместе с ним; к тому же он не
переносится и не хранится отдельно. Камни: длинные цепочки тормозят I/O и едят место;
снапшот БД без fsfreeze — это состояние «после выдернутого шнура»; откат узла распределённой
системы ломает согласованность; после отката прыгают часы.

</details>

**A11.** Какие бывают CPU mode у VM и как они влияют на живую миграцию?

<details><summary>Ответ</summary>

`host-passthrough` — гость видит CPU хоста как есть; миграция только на идентичный
CPU. `host-model` — модель, похожая на CPU хоста; миграция между похожими хостами. `custom`
(конкретная модель, например `x86-64-v2`) — работает на любом хосте, который её поддерживает,
удобно в разнородном кластере.

</details>

**A12.** Почему CPU переподписывают, а RAM — осторожно? Что такое steal time?

<details><summary>Ответ</summary>

vCPU — поток, который большую часть времени спит, поэтому ядра можно делить. RAM
занята, пока занята: закончилась — своп на хосте (всё тормозит) или OOM-killer убивает VM.
Steal time — время, когда vCPU готов работать, но гипервизор не дал ему физическое ядро
(видно в госте как `%st`).

</details>

**A13.** Как устроена живая миграция (pre-copy)? Какие требования к хостам?

<details><summary>Ответ</summary>

Копируется вся память на приёмник, пока VM работает; затем итерациями докопируются
изменённые («грязные») страницы; когда их мало — VM на миллисекунды замирает, передаются
остаток памяти и состояние CPU/устройств, VM стартует на приёмнике. Нужны: libvirt/QEMU на
обоих, связь SSH/TLS, общее хранилище (или копирование дисков), та же сеть, совместимый CPU.

</details>

**A14.** Что умеет `qemu-guest-agent`? Что ты теряешь без него?

<details><summary>Ответ</summary>

Сообщает IP всех интерфейсов, ОС и имя хоста; замораживает ФС для согласованных
снапшотов/бэкапов; выключает гостя; меняет пароль; выполняет команды. Без него IP — только из
DHCP своей сети, снапшоты без fsfreeze, выключение только по ACPI.

</details>

**A15.** Что такое hugepages и для каких VM их включают?

<details><summary>Ответ</summary>

Страницы памяти 2 МБ или 1 ГБ вместо 4 КБ — меньше записей в таблицах страниц и
промахов TLB. Включают для больших VM с интенсивной работой с памятью: БД, NFV, in-memory
кэши. Память под hugepages резервируется заранее и не переподписывается.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  $ qemu-img create -f qcow2 -b noble-base.qcow2 vm2.qcow2 20G
```text
<details><summary>Ответ</summary>

⚠️ Нет `-F qcow2` — современный qemu-img откажется: `Backing file specified without
backing format`. Нужно `-b noble-base.qcow2 -F qcow2`.

</details>

```text:no-line-numbers
B2.  $ virt-install --name vm2 --memory 2048 --disk vol=default/vm2.qcow2 --import
```text
<details><summary>Ответ</summary>

⚠️ Фатальная ошибка «--os-variant/--osinfo OS name is required». Указать `--osinfo
ubuntu24.04` (или `linux2024`). Заодно не хватает `--cloud-init` — войти будет нечем.

</details>

```text:no-line-numbers
     # (без --osinfo)
```text
```text:no-line-numbers
B3.  # user-data.yaml
```text
<details><summary>Ответ</summary>

⚠️ Нет первой строки `#cloud-config` — cloud-init не распознает файл как cloud-config
и ничего не применит. Плюс у пользователя нет `sudo` и `shell`.

</details>

```text:no-line-numbers
     hostname: vm2
```text
```text:no-line-numbers
     users:
```text
```text:no-line-numbers
       - name: devops
```text
```text:no-line-numbers
         ssh_authorized_keys: [ssh-ed25519 AAAA...]
```text
```text:no-line-numbers
B4.  «Я сделал virsh destroy prod-db — всё, базу удалил, восстанавливаем из бэкапа?»
```text
<details><summary>Ответ</summary>

✅ `destroy` только жёстко выключил VM, диск на месте. `virsh start prod-db`, проверить
журнал БД — она восстановится как после отключения питания.

</details>

```text:no-line-numbers
B5.  $ virt-install ... --disk path=/home/nurik/vms/vm2.qcow2 ...
```text
<details><summary>Ответ</summary>

⚠️ QEMU работает от `libvirt-qemu` и под AppArmor, в домашний каталог его не пускают.
Держать диски в пуле `/var/lib/libvirt/images` (или завести пул в `/srv`).

</details>

```text:no-line-numbers
     ERROR  Cannot access storage file '/home/nurik/vms/vm2.qcow2' (as uid:64055, gid:994): Permission denied
```text
```text:no-line-numbers
B6.  # «обновим пакеты в базе, чтобы все VM стали свежее»
```text
<details><summary>Ответ</summary>

⚠️ База изменилась под существующими overlay — все VM на ней будут испорчены.
Правильно: новый файл базы (или Packer, тема 06), новые VM — от новой базы.

</details>

```text:no-line-numbers
     $ virt-install --name base-upd --disk path=/var/lib/libvirt/images/noble-base.qcow2 --import ...
```text
```text:no-line-numbers
     $ ssh ... sudo apt full-upgrade
```text
```text:no-line-numbers
B7.  $ virsh list
```text
<details><summary>Ответ</summary>

⚠️ Менять диск работающей VM через qemu-img нельзя (qemu-img откажется из-за
блокировки, а с принуждением — испортит образ). Онлайн — `virsh blockresize vm1 vda &lt;размер&gt;`.

</details>

```text:no-line-numbers
      Id   Name   State
```text
```text:no-line-numbers
      3    vm1    running
```text
```text:no-line-numbers
     $ sudo qemu-img resize /var/lib/libvirt/images/vm1.qcow2 +10G
```text
```text:no-line-numbers
B8.  # реплика PostgreSQL в кластере Patroni
```text
<details><summary>Ответ</summary>

⚠️ Реплика «уехала» на неделю назад, её данные разошлись с лидером; Patroni/PostgreSQL
её не примет или она сломает репликацию. Реплику пересоздают с лидера (`pg_basebackup`/reinit),
а не откатывают снапшотом.

</details>

```text:no-line-numbers
     $ virsh snapshot-revert pg-replica-2 week-ago
```text
```text:no-line-numbers
B9.  $ virsh setvcpus vm1 8 --live
```text
<details><summary>Ответ</summary>

⚠️ На ходу нельзя превысить максимум vCPU, заданный в конфигурации. Выключить VM,
`virsh setvcpus vm1 8 --maximum --config`, запустить, потом `--live` до максимума.

</details>

```text:no-line-numbers
     error: invalid argument: requested vcpus is greater than max allowable vcpus for the live domain: 8 > 2
```text
```text:no-line-numbers
B10.  # VM с UEFI, хост Ubuntu 24.04 (libvirt 10.0)
```text
<details><summary>Ответ</summary>

⚠️ Internal-снапшоты VM с UEFI (pflash NVRAM) поддержаны только с libvirt 10.9 —
на 10.0 будет ошибка. Делать external (`--disk-only`) или обновить libvirt.

</details>

```text:no-line-numbers
     $ virsh snapshot-create-as win-vm before-update
```text
```text:no-line-numbers
B11.  # kvm01 — свежий EPYC, kvm02 — EPYC на три поколения старше, у VM host-passthrough
```text
<details><summary>Ответ</summary>

⚠️ На старом CPU нет инструкций, которые гость уже видит и может использовать, —
миграция откажет или гость упадёт. Для кластера из разных CPU — `host-model` или общая
модель (`custom`).

</details>

```text:no-line-numbers
     $ virsh migrate --live app1 qemu+ssh://kvm02/system
```text
```text:no-line-numbers
B12.  $ virsh snapshot-list app1 | wc -l
```text
<details><summary>Ответ</summary>

⚠️ Каждое чтение идёт по цепочке из десятков файлов — I/O медленный, место растёт.
Слить снапшоты (`snapshot-delete` или `blockcommit`), снапшоты держать часы-дни, для
долгого хранения — бэкапы.

</details>

```text:no-line-numbers
     34
```text
```text:no-line-numbers
     # external-снапшоты «на всякий случай» копились полгода, VM стала медленной
```text
---

### Блок C. Практика


### C1. 🔑 VM из облачного образа
Повтори раздел 3 конспекта для `vm2` с другим пользователем и пакетами `nginx` и `htop`.
Докажи, что cloud-init отработал: имя хоста, пользователь и его sudo, установленные пакеты,
корень растянут до размера overlay, `cloud-init status --long` без ошибок. Где лежат логи
cloud-init в госте?

### C2. 🔑 Жизненный цикл
**1.** Засеки время `virsh shutdown vm2` и `virsh destroy vm2` (после старта). В чём разница для гостя?

<details><summary>Ответ</summary>

Логи: `/var/log/cloud-init.log` (подробный) и `/var/log/cloud-init-output.log` (вывод
команд). Проверки: `hostname`, `id devops`, `sudo -l`, `dpkg -l nginx htop`, `lsblk`/`df -h /`,
`cloud-init status --long`. Данные, которые получил cloud-init: `sudo cloud-init query --all`.

</details>

**2.** Включи автостарт, перезагрузи libvirt (`sudo systemctl restart libvirtd`) — VM не должны
   упасть. Почему?

<details><summary>Ответ</summary>

1) `shutdown` — секунды-десятки секунд, гость сам гасит службы; `destroy` — мгновенно,
гость ничего не успевает. 2) Запущенные VM — отдельные процессы QEMU, рестарт демона libvirt их
не трогает; `autostart` влияет на загрузку хоста. 3) `managedsave` сохраняет RAM в файл и
выключает VM; `virsh list --all --managed-save` показывает `saved`; после `start` процесс
`sleep` на месте — память восстановлена.

</details>

**3.** Сделай `managedsave`, посмотри `virsh list --all` и `--managed-save`, стартуй снова.
   Что сохранилось в памяти гостя (запусти перед этим `sleep 10000 &`)?

<details><summary>Ответ</summary>

`qemu-img create -f qcow2 -b /var/lib/libvirt/images/noble-base.qcow2 -F qcow2 ov-a.qcow2 20G`.
`ls -lh` показывает размер файла с «дырами» (для qcow2 — выделенные кластеры), `du` — реально
занятое место; `qemu-img info` показывает virtual size 20 GiB и disk size ~200 МБ + метаданные.
`qemu-img convert -O qcow2 ov-a.qcow2 flat.qcow2` — в `info` нет строки `backing file`,
файл самостоятельный и размером с базу + изменения.

</details>

### C3. 🔑 Overlay своими руками
**1.** Создай два overlay поверх базы: `ov-a.qcow2`, `ov-b.qcow2` (через `qemu-img` в отдельном
   каталоге, `sudo`).

<details><summary>Ответ</summary>

Логи: `/var/log/cloud-init.log` (подробный) и `/var/log/cloud-init-output.log` (вывод
команд). Проверки: `hostname`, `id devops`, `sudo -l`, `dpkg -l nginx htop`, `lsblk`/`df -h /`,
`cloud-init status --long`. Данные, которые получил cloud-init: `sudo cloud-init query --all`.

</details>

**2.** Запусти VM на `ov-a`, запиши внутри 200 МБ (`dd if=/dev/urandom of=/big bs=1M count=200`).

<details><summary>Ответ</summary>

1) `shutdown` — секунды-десятки секунд, гость сам гасит службы; `destroy` — мгновенно,
гость ничего не успевает. 2) Запущенные VM — отдельные процессы QEMU, рестарт демона libvirt их
не трогает; `autostart` влияет на загрузку хоста. 3) `managedsave` сохраняет RAM в файл и
выключает VM; `virsh list --all --managed-save` показывает `saved`; после `start` процесс
`sleep` на месте — память восстановлена.

</details>

**3.** Сравни размеры: `ls -lh`, `du -h`, `qemu-img info`. Почему `ls` и `du` показывают разное?

<details><summary>Ответ</summary>

`qemu-img create -f qcow2 -b /var/lib/libvirt/images/noble-base.qcow2 -F qcow2 ov-a.qcow2 20G`.
`ls -lh` показывает размер файла с «дырами» (для qcow2 — выделенные кластеры), `du` — реально
занятое место; `qemu-img info` показывает virtual size 20 GiB и disk size ~200 МБ + метаданные.
`qemu-img convert -O qcow2 ov-a.qcow2 flat.qcow2` — в `info` нет строки `backing file`,
файл самостоятельный и размером с базу + изменения.

</details>

**4.** Сплющи `ov-a` в самостоятельный файл через `qemu-img convert`, проверь, что backing file исчез.

<details><summary>Ответ</summary>

`virsh pool-define-as vmstore dir --target /srv/vmstore`, `pool-build`, `pool-start`,
`pool-autostart`; `virsh vol-create-as vmstore data.qcow2 5G --format qcow2`;
`virsh attach-disk vm1 /srv/vmstore/data.qcow2 vdb --subdriver qcow2 --persistent`.
В госте: `lsblk` → `vdb`, `parted`/`fdisk`, `mkfs.ext4`, запись в fstab по UUID с `nofail`.
Перед `detach-disk` отмонтировать и убрать строку из fstab.

</details>

### C4. Свой пул и второй диск
**1.** Создай пул-каталог `vmstore` в `/srv/vmstore` с автостартом.

<details><summary>Ответ</summary>

Логи: `/var/log/cloud-init.log` (подробный) и `/var/log/cloud-init-output.log` (вывод
команд). Проверки: `hostname`, `id devops`, `sudo -l`, `dpkg -l nginx htop`, `lsblk`/`df -h /`,
`cloud-init status --long`. Данные, которые получил cloud-init: `sudo cloud-init query --all`.

</details>

**2.** Создай том 5 ГБ, подключи к `vm1` как `vdb` на ходу.

<details><summary>Ответ</summary>

1) `shutdown` — секунды-десятки секунд, гость сам гасит службы; `destroy` — мгновенно,
гость ничего не успевает. 2) Запущенные VM — отдельные процессы QEMU, рестарт демона libvirt их
не трогает; `autostart` влияет на загрузку хоста. 3) `managedsave` сохраняет RAM в файл и
выключает VM; `virsh list --all --managed-save` показывает `saved`; после `start` процесс
`sleep` на месте — память восстановлена.

</details>

**3.** Внутри гостя: раздел, ext4, монтирование через fstab с `nofail`
   ([../Linux/10_the_filesystem.md](/linux/10-the-filesystem)).

<details><summary>Ответ</summary>

`qemu-img create -f qcow2 -b /var/lib/libvirt/images/noble-base.qcow2 -F qcow2 ov-a.qcow2 20G`.
`ls -lh` показывает размер файла с «дырами» (для qcow2 — выделенные кластеры), `du` — реально
занятое место; `qemu-img info` показывает virtual size 20 GiB и disk size ~200 МБ + метаданные.
`qemu-img convert -O qcow2 ov-a.qcow2 flat.qcow2` — в `info` нет строки `backing file`,
файл самостоятельный и размером с базу + изменения.

</details>

**4.** Отключи диск (`virsh detach-disk vm1 vdb --persistent`) и удали том.

<details><summary>Ответ</summary>

`virsh pool-define-as vmstore dir --target /srv/vmstore`, `pool-build`, `pool-start`,
`pool-autostart`; `virsh vol-create-as vmstore data.qcow2 5G --format qcow2`;
`virsh attach-disk vm1 /srv/vmstore/data.qcow2 vdb --subdriver qcow2 --persistent`.
В госте: `lsblk` → `vdb`, `parted`/`fdisk`, `mkfs.ext4`, запись в fstab по UUID с `nofail`.
Перед `detach-disk` отмонтировать и убрать строку из fstab.

</details>

### C5. 🔑 Снапшоты: сломать и откатить
**1.** Internal-снапшот `before-break`, затем в госте `sudo apt remove -y openssh-server`.

<details><summary>Ответ</summary>

Логи: `/var/log/cloud-init.log` (подробный) и `/var/log/cloud-init-output.log` (вывод
команд). Проверки: `hostname`, `id devops`, `sudo -l`, `dpkg -l nginx htop`, `lsblk`/`df -h /`,
`cloud-init status --long`. Данные, которые получил cloud-init: `sudo cloud-init query --all`.

</details>

**2.** Откатись, проверь SSH.

<details><summary>Ответ</summary>

1) `shutdown` — секунды-десятки секунд, гость сам гасит службы; `destroy` — мгновенно,
гость ничего не успевает. 2) Запущенные VM — отдельные процессы QEMU, рестарт демона libvirt их
не трогает; `autostart` влияет на загрузку хоста. 3) `managedsave` сохраняет RAM в файл и
выключает VM; `virsh list --all --managed-save` показывает `saved`; после `start` процесс
`sleep` на месте — память восстановлена.

</details>

**3.** External-снапшот `pre-deploy` c `--disk-only --atomic --quiesce`. Посмотри `domblklist`
   и `qemu-img info -U --backing-chain` активного файла.

<details><summary>Ответ</summary>

`qemu-img create -f qcow2 -b /var/lib/libvirt/images/noble-base.qcow2 -F qcow2 ov-a.qcow2 20G`.
`ls -lh` показывает размер файла с «дырами» (для qcow2 — выделенные кластеры), `du` — реально
занятое место; `qemu-img info` показывает virtual size 20 GiB и disk size ~200 МБ + метаданные.
`qemu-img convert -O qcow2 ov-a.qcow2 flat.qcow2` — в `info` нет строки `backing file`,
файл самостоятельный и размером с базу + изменения.

</details>

**4.** Удали снапшот через `snapshot-delete`, убедись, что цепочка схлопнулась.

<details><summary>Ответ</summary>

`virsh pool-define-as vmstore dir --target /srv/vmstore`, `pool-build`, `pool-start`,
`pool-autostart`; `virsh vol-create-as vmstore data.qcow2 5G --format qcow2`;
`virsh attach-disk vm1 /srv/vmstore/data.qcow2 vdb --subdriver qcow2 --persistent`.
В госте: `lsblk` → `vdb`, `parted`/`fdisk`, `mkfs.ext4`, запись в fstab по UUID с `nofail`.
Перед `detach-disk` отмонтировать и убрать строку из fstab.

</details>

### C6. CPU и RAM
**1.** Выключи `vm1`, подними максимум vCPU до 4 и памяти до 4 ГБ, текущие оставь 2/2.

<details><summary>Ответ</summary>

Логи: `/var/log/cloud-init.log` (подробный) и `/var/log/cloud-init-output.log` (вывод
команд). Проверки: `hostname`, `id devops`, `sudo -l`, `dpkg -l nginx htop`, `lsblk`/`df -h /`,
`cloud-init status --long`. Данные, которые получил cloud-init: `sudo cloud-init query --all`.

</details>

**2.** Запусти и добавь vCPU и память на ходу. Проверь в госте `nproc` и `free -h`.

<details><summary>Ответ</summary>

1) `shutdown` — секунды-десятки секунд, гость сам гасит службы; `destroy` — мгновенно,
гость ничего не успевает. 2) Запущенные VM — отдельные процессы QEMU, рестарт демона libvirt их
не трогает; `autostart` влияет на загрузку хоста. 3) `managedsave` сохраняет RAM в файл и
выключает VM; `virsh list --all --managed-save` показывает `saved`; после `start` процесс
`sleep` на месте — память восстановлена.

</details>

**3.** Дай `stress`/`yes` нагрузку в двух VM с 4 vCPU каждая на хосте с малым числом ядер
   (или временно ограничь хост). Найди steal time в `top` гостя.

<details><summary>Ответ</summary>

`qemu-img create -f qcow2 -b /var/lib/libvirt/images/noble-base.qcow2 -F qcow2 ov-a.qcow2 20G`.
`ls -lh` показывает размер файла с «дырами» (для qcow2 — выделенные кластеры), `du` — реально
занятое место; `qemu-img info` показывает virtual size 20 GiB и disk size ~200 МБ + метаданные.
`qemu-img convert -O qcow2 ov-a.qcow2 flat.qcow2` — в `info` нет строки `backing file`,
файл самостоятельный и размером с базу + изменения.

</details>

### C7. 🔑 Guest agent
**1.** `guest-ping`, `domifaddr --source agent`, `guestinfo --os --hostname`.

<details><summary>Ответ</summary>

Логи: `/var/log/cloud-init.log` (подробный) и `/var/log/cloud-init-output.log` (вывод
команд). Проверки: `hostname`, `id devops`, `sudo -l`, `dpkg -l nginx htop`, `lsblk`/`df -h /`,
`cloud-init status --long`. Данные, которые получил cloud-init: `sudo cloud-init query --all`.

</details>

**2.** Заморозь ФС (`domfsfreeze`) и попробуй в госте `touch /tmp/x`. Что происходит? Разморозь.

<details><summary>Ответ</summary>

1) `shutdown` — секунды-десятки секунд, гость сам гасит службы; `destroy` — мгновенно,
гость ничего не успевает. 2) Запущенные VM — отдельные процессы QEMU, рестарт демона libvirt их
не трогает; `autostart` влияет на загрузку хоста. 3) `managedsave` сохраняет RAM в файл и
выключает VM; `virsh list --all --managed-save` показывает `saved`; после `start` процесс
`sleep` на месте — память восстановлена.

</details>

**3.** Останови агент в госте и повтори п.1. Какие команды перестали работать?

<details><summary>Ответ</summary>

`qemu-img create -f qcow2 -b /var/lib/libvirt/images/noble-base.qcow2 -F qcow2 ov-a.qcow2 20G`.
`ls -lh` показывает размер файла с «дырами» (для qcow2 — выделенные кластеры), `du` — реально
занятое место; `qemu-img info` показывает virtual size 20 GiB и disk size ~200 МБ + метаданные.
`qemu-img convert -O qcow2 ov-a.qcow2 flat.qcow2` — в `info` нет строки `backing file`,
файл самостоятельный и размером с базу + изменения.

</details>

### C8. Увеличить диск без остановки
Увеличь диск `vm1` на 5 ГБ на ходу и растяни раздел и ФС внутри. Докажи `df -h`.

### C9. Миграция с VMware в миниатюре
Сконвертируй диск выключенной `vm2` в `vmdk`, затем обратно в `qcow2` в новый файл. Подними из
него VM `vm2-import` через `virt-install --import` (без cloud-init). Загрузилась ли VM? Какие
проблемы встретятся при настоящей миграции с ESXi?

---

### Блок D. Инциденты


**D1.** VM не стартует после переноса диска: `Cannot access storage file ... Permission denied`.
Путь существует, права `rw-r--r--`. Что проверить?

<details><summary>Ответ</summary>

Каталог выше не пускает (нет `x` для `libvirt-qemu`), AppArmor-профиль не разрешает
путь (`journalctl -k | grep -i apparmor` — DENIED), владелец файла/SELinux-контекст на
RHEL. Надёжно — перенести диск в пул `/var/lib/libvirt/images` и `pool-refresh`.

</details>

**D2.** Утром половина VM в состоянии `paused`, `virsh domstate vm --reason` →
`paused (I/O error)`. Что случилось и как вернуть в строй?

<details><summary>Ответ</summary>

Кончилось место на хранилище: тонкие диски не смогли вырасти, QEMU по умолчанию
ставит VM на паузу при ошибке записи (чтобы не испортить данные). `df -h /var/lib/libvirt/images`,
освободить место (старые снапшоты, ISO, ненужные тома), затем `virsh resume vm` для каждой.
Потом — мониторинг места и алерт заранее.

</details>

**D3.** Вчера «обновили базовый образ», сегодня все VM, созданные из него, не грузятся или
падают с ошибками ФС. Что произошло? Как правильно обновлять базу?

<details><summary>Ответ</summary>

Изменили backing file под существующими overlay — их блоки теперь ссылаются на другие
данные базы. Восстанавливать из бэкапа старую базу или VM. Правильно: база только для чтения;
обновление — выпуск нового образа (`noble-base-2026-10.qcow2`), новые VM — от него, старые
переводят на новые VM или живут со старой базой, пока не удалены.

</details>

**D4.** Из одного шаблона подняли три VM — все получили один и тот же IP от DHCP, и у всех
одинаковые SSH host keys. Почему и как чинить?

<details><summary>Ответ</summary>

Шаблон склонировали вместе с `/etc/machine-id` и SSH host keys. systemd-networkd строит
DHCP client ID из machine-id, поэтому DHCP выдаёт всем один IP. Лечить: при подготовке
шаблона `cloud-init clean --machine-id --logs` (или `truncate -s 0 /etc/machine-id`) и удалить
`/etc/ssh/ssh_host_*` — при первом старте сгенерируются новые (cloud-init делает это для новых
`instance-id`). Уже созданным VM — сгенерировать machine-id и ключи заново.

</details>

**D5.** `virsh shutdown app1` — прошло 10 минут, VM всё ещё `running`. Действия?

<details><summary>Ответ</summary>

Проверить, видит ли гость ACPI (`virsh console` — зависла загрузка или служба не
останавливается). Попробовать `virsh shutdown app1 --mode agent`. Если гость завис —
`virsh destroy app1` осознанно (как отключение питания), потом `start` и разбор, что держало
остановку (`journalctl -b -1` в госте).

</details>

**D6.** После перезагрузки хоста у VM сменился IP, мониторинг и Ansible-инвентарь сломались.
Как сделать адрес стабильным?

<details><summary>Ответ</summary>

Резервировать адрес в DHCP сети libvirt:
`virsh net-update virt-lab add ip-dhcp-host "&lt;host mac='52:54:00:..' name='app1' ip='10.10.10.50'/&gt;" --live --config`
(MAC — из `virsh domiflist`), либо статический адрес через cloud-init `network-config`.
Инвентарь лучше строить динамически (тема 06), а не списком IP.

</details>

**D7.** Снапшот работающей VM с MySQL откатили — MySQL стартует долго, в логах recovery. Почему?
Как делать снапшоты БД правильно?

<details><summary>Ответ</summary>

Снапшот без fsfreeze сохраняет диск «как при отключении питания» — MySQL применяет
redo log при старте (crash recovery). Правильно: снапшот с `--quiesce` (агент делает fsfreeze,
в идеале с хуком, который сбрасывает таблицы БД: `FLUSH TABLES WITH READ LOCK` на время
заморозки) или логический/физический бэкап средствами БД.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как быстро поднять VM с Linux из командной строки?

<details><summary>Ответ</summary>

Скачать облачный образ, сделать overlay (`virsh vol-create-as ... --backing-vol`), написать
   `user-data`/`meta-data` и выполнить `virt-install --import --osinfo ... --cloud-init
   user-data=...,meta-data=... --network ... --graphics none`. Через минуту — SSH по ключу.

</details>

**2.** Чем qcow2 отличается от raw?

<details><summary>Ответ</summary>

raw — байт в байт, быстрее, без функций; qcow2 — тонкий, backing files, снапшоты, сжатие.

</details>

**3.** Что такое backing file и linked clone?

<details><summary>Ответ</summary>

Backing file — базовый образ только для чтения; overlay/linked clone хранит только свои
   изменения и читает остальное из базы. Так делают десятки VM из одного шаблона за секунды.

</details>

**4.** Чем снапшот отличается от бэкапа?

<details><summary>Ответ</summary>

Снапшот — точка отката на том же хранилище, без отдельного хранения; бэкап — копия
   в другом месте с хранением по политике и проверенным восстановлением. Снапшот
   бэкап не заменяет.

</details>

**5.** Internal и external снапшоты — в чём разница?

<details><summary>Ответ</summary>

Internal хранится внутри qcow2 и может включать RAM; external — отдельный overlay-файл,
   базовый диск становится только для чтения, overlay потом сливают (blockcommit).

</details>

**6.** Как работает живая миграция и что для неё нужно?

<details><summary>Ответ</summary>

Память копируется на приёмник, пока VM работает, потом докопируются изменённые страницы,
   финальное переключение — миллисекунды. Нужны общее хранилище или копия дисков, та же сеть,
   совместимый CPU, связь между libvirt.

</details>

**7.** Что такое overcommit и steal time?

<details><summary>Ответ</summary>

Overcommit — выделено больше ресурсов, чем есть. CPU переподписывают умеренно, контроль —
   steal time в гостях; RAM — осторожно, иначе своп или OOM-killer на хосте.

</details>

**8.** Зачем нужен qemu-guest-agent?

<details><summary>Ответ</summary>

Узнать IP, ОС и ФС гостя, корректно выключить, заморозить ФС для консистентного снапшота
   или бэкапа, выполнить команду в госте. Proxmox и бэкап-системы на него опираются.

</details>

**9.** Как увеличить диск у работающей VM?

<details><summary>Ответ</summary>

`virsh blockresize vm vda &lt;размер&gt;` (в Proxmox — `qm disk resize`), затем в госте
   `growpart /dev/vda 1` и `resize2fs`/`xfs_growfs`. LVM внутри — ещё `pvresize` и `lvextend`.

</details>

**10.** Что будет при `virsh destroy`?

<details><summary>Ответ</summary>

Процесс QEMU мгновенно убивается — как выдернуть питание. Незаписанные данные гостя
    теряются, диск и описание VM остаются; `virsh start` поднимет её снова.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Поднимаю VM из облачного образа с cloud-init одной командой `virt-install`
- [ ] Управляю жизненным циклом через `virsh` и отличаю `shutdown` / `destroy` / `undefine`
- [ ] ⭐ Делаю overlay-диски, читаю цепочку через `qemu-img info --backing-chain`
- [ ] Увеличиваю диск VM (выключенной и на ходу) и растягиваю раздел в госте
- [ ] Завожу storage pool и подключаю второй диск
- [ ] ⭐ Делаю internal и external снапшоты, откатываюсь, сливаю цепочку; объясняю, почему это не бэкап
- [ ] Меняю vCPU/RAM, объясняю overcommit и steal time
- [ ] Объясняю живую миграцию и её требования
- [ ] Пользуюсь `qemu-guest-agent` (IP, fsfreeze, shutdown)
