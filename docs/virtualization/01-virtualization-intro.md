---
title: "01. Виртуализация: зачем, как устроена, кто на рынке"
description: "Блок → Виртуализация on-prem → тема 01. Опирается на"
---

# 01. Виртуализация: зачем, как устроена, кто на рынке

> Блок → Виртуализация on-prem → тема 01. Опирается на
> [../Linux/12_kernel.md](/linux/12-kernel) (кольца защиты, модули ядра),
> [../Docker/01_containers_intro.md](/docker/01-containers-intro) (namespaces и cgroups)
> и стенд [../Linux/00_vagrant.md](/linux/00-vagrant) (libvirt/KVM уже стоит).
>
> **После темы ты умеешь:** объяснить, зачем бизнесу виртуализация, чем type-1 отличается
> от type-2, что делают VT-x/AMD-V и EPT/NPT, как делят работу KVM, QEMU и libvirt, что такое
> virtio, когда выбрать VM, LXC или Docker, и ориентироваться в рынке: VMware после Broadcom,
> Proxmox, OpenStack, Hyper-V, oVirt.

---

## 🗺️ Карта темы

```text
 ЖЕЛЕЗО: CPU с VT-x/AMD-V + EPT/NPT, IOMMU (VT-d/AMD-Vi), RAM, диски, NIC
    │
    ▼
 ЯДРО LINUX + модуль KVM (kvm.ko + kvm_intel/kvm_amd) ──► /dev/kvm
    │           «ядро становится гипервизором»
    ▼
 QEMU: один процесс qemu-system-x86_64 на каждую VM
    │    эмулирует устройства (диск, сеть, BIOS/UEFI), vCPU = потоки процесса
    │    быстрые устройства — virtio (паравиртуализация)
    ▼
 libvirt: API + XML-описание VM, сети, хранилища (libvirtd / virtqemud)
    │
    ├── virsh, virt-install, virt-manager      ← руками
    ├── Vagrant (vagrant-libvirt), Terraform    ← кодом
    └── OpenStack Nova, oVirt                   ← платформы
                                                    Proxmox VE ── свои qm/pct поверх KVM/QEMU и LXC,
                                                                  libvirt НЕ использует
```text
---

## 1. Зачем виртуализация

Один физический сервер под одно приложение — это простаивающее железо, долгая закупка
и «сервер умер — сервис умер». Гипервизор режет один сервер на много изолированных машин.

| Что даёт | Как выглядит на практике |
|----------|--------------------------|
| **Консолидация** | 20 VM на 2 серверах вместо 20 серверов: меньше железа, стоек, электричества |
| **Скорость** | Новая VM из шаблона — минуты, а не недели закупки |
| **Изоляция** | Упала/взломана одна VM — остальные живут (своё ядро у каждой) |
| **Снапшоты** | Откат после неудачного обновления за секунды (но это не бэкап — тема 02) |
| **Миграция и HA** | VM переезжает на другой хост без остановки; упал хост — VM перезапускаются на соседях |
| **Стенды** | Копия прода для тестов, учебные лабы — тот же Vagrant-стенд |
| **Разные ОС** | Windows и Linux на одном железе — у каждой VM своё ядро |

> 💡 Облако — это та же виртуализация, только чужая и с API. Когда создаёшь инстанс в облаке,
> под капотом гипервизор режет физический сервер провайдера
> ([../Left/04_Cloud/01_cloud_models.md](/cloud/01-cloud-models), IaaS).

---

## 2. Гипервизор: type-1 и type-2

**Гипервизор** (VMM, virtual machine monitor) — софт, который создаёт VM и делит между
ними CPU, память и устройства.

```text
      TYPE-1 (bare-metal)                      TYPE-2 (hosted)
 ┌────────┬────────┬────────┐          ┌────────┬────────┐
 │  VM 1  │  VM 2  │  VM 3  │          │  VM 1  │  VM 2  │
 ├────────┴────────┴────────┤          ├────────┴────────┤
 │       ГИПЕРВИЗОР         │          │  VirtualBox /   │ ← обычная программа
 ├──────────────────────────┤          │  Workstation    │
 │         ЖЕЛЕЗО           │          ├─────────────────┤
 └──────────────────────────┘          │   ОС хоста      │ ← Windows/macOS/Linux
                                       ├─────────────────┤
                                       │     ЖЕЛЕЗО      │
                                       └─────────────────┘
```text
| | Type-1 | Type-2 |
|---|--------|--------|
| Где работает | Прямо на железе | Как приложение внутри ОС |
| Примеры | VMware ESXi, Microsoft Hyper-V, Xen (XCP-ng), **KVM** | VirtualBox, VMware Workstation, Parallels |
| Для чего | Серверы, дата-центры, облака | Ноутбук разработчика, тесты |
| Накладные расходы | Минимальные | Больше: лишний слой ОС |

**Где KVM?** Формально спорно: KVM — модуль обычного ядра Linux, рядом крутятся другие
процессы. Но с загруженным модулем само ядро планирует vCPU и управляет памятью VM —
это работа type-1. На собесе отвечай: *«KVM превращает ядро Linux в гипервизор первого типа;
граница между типами размыта, важнее, что VM исполняется прямо на CPU с аппаратной поддержкой»*.

---

## 3. Аппаратная виртуализация: VT-x/AMD-V и EPT/NPT

Вспомни кольца защиты из [../Linux/12_kernel.md](/linux/12-kernel): ядро — ring 0,
программы — ring 3. Гостевое ядро тоже хочет ring 0, но ring 0 уже занят ядром хоста.

```text
 ДО 2005: программные трюки                ПОСЛЕ: аппаратная поддержка
 ────────────────────────────              ──────────────────────────────────────
 trap-and-emulate, binary translation      VT-x (Intel) / AMD-V (AMD):
 (VMware переписывала опасные              два режима CPU —
 инструкции гостя на лету) → медленно,     root (гипервизор) и non-root (гость).
 сложно                                    Гость живёт в «своём» ring 0 non-root;
                                           опасная инструкция → VM exit в гипервизор,
 Xen: паравиртуализация — гостевое         тот обрабатывает → VM entry обратно.
 ядро переписано под гипервизор
```text
**Память.** У гостя свои «физические» адреса, которые на самом деле — виртуальные адреса
хоста. Раньше гипервизор держал *shadow page tables* и перехватывал каждое изменение таблиц
страниц гостя — дорого. **EPT** (Intel) / **NPT** (AMD, он же RVI) — вторая аппаратная
таблица трансляции: гость сам управляет своими таблицами, CPU переводит адрес в два шага.

**Устройства.** **IOMMU** (Intel VT-d, AMD-Vi) — изоляция DMA: без неё нельзя безопасно
пробросить в VM реальное устройство (PCI passthrough GPU/NIC, SR-IOV).

### Проверить железо

```bash
grep -cE 'vmx|svm' /proc/cpuinfo        # > 0 — есть VT-x (vmx) или AMD-V (svm); 0 — выключено в BIOS
grep -owE 'ept|npt' /proc/cpuinfo | sort -u   # ept (Intel) или npt (AMD) — вторая трансляция памяти
lscpu | grep -i virtualization          # Virtualization: VT-x | AMD-V
ls -l /dev/kvm                          # устройство KVM, группа kvm
lsmod | grep kvm                        # kvm_intel или kvm_amd + kvm

kvm-ok                                  # Ubuntu, пакет cpu-checker
# INFO: /dev/kvm exists
# KVM acceleration can be used

virt-host-validate qemu                 # из libvirt, проверяет всё сразу
#   QEMU: Checking for hardware virtualization          : PASS
#   QEMU: Checking if device /dev/kvm exists            : PASS
#   QEMU: Checking if device /dev/vhost-net exists      : PASS
#   QEMU: Checking for cgroup 'devices' controller ...  : WARN   ← норм для cgroup v2
#   QEMU: Checking if IOMMU is enabled by kernel        : PASS / WARN
```text
> ⚠️ `grep vmx` пустой, а процессор современный → виртуализация выключена в BIOS/UEFI
> (Intel Virtualization Technology / SVM Mode). WARN про cgroup `devices` на cgroup v2 —
> не проблема: там доступ к устройствам управляется через eBPF, отдельного контроллера нет.

### Nested virtualization — VM внутри VM

Стенд блока: Proxmox VE сам гипервизор, а мы запустим его **внутри KVM-VM**. Для этого
гостю нужно увидеть флаги `vmx`/`svm`:

```bash
cat /sys/module/kvm_intel/parameters/nested   # Y или 1 — включено (Intel)
cat /sys/module/kvm_amd/parameters/nested     # 1 — включено (AMD)
```text
С ядра 4.20 nested включён по умолчанию для обоих модулей (дистрибутив может переопределить).
Если выключен:

```bash
echo "options kvm_intel nested=1" | sudo tee /etc/modprobe.d/kvm-nested.conf   # AMD: kvm_amd
# выгрузить модуль можно только при выключенных VM:
sudo modprobe -r kvm_intel && sudo modprobe kvm_intel
```text
И второе условие — **CPU mode `host-passthrough`** у VM-гипервизора: гость получает CPU
хоста как есть, со всеми флагами, включая `vmx`/`svm`. В XML libvirt это
`&lt;cpu mode='host-passthrough'/&gt;`, в virt-install — `--cpu host-passthrough`, в Vagrant —
`libvirt.cpu_mode = "host-passthrough"` + `libvirt.nested = true`. Цена — VM нельзя живьём
мигрировать на хост с другим процессором (тема 02).

---

## 4. Стек KVM + QEMU + libvirt

| Слой | Что это | Что делает | Где увидеть |
|------|---------|-----------|-------------|
| **KVM** | Модуль ядра (`kvm.ko` + `kvm_intel`/`kvm_amd`) | Исполняет код гостя на CPU через VT-x/AMD-V, управляет памятью (EPT/NPT) | `/dev/kvm`, `lsmod \| grep kvm` |
| **QEMU** | Процесс в user space, один на VM | Эмулирует «железо»: BIOS/UEFI, диски, сеть, USB, видео. Без KVM умеет эмулировать всё программно (TCG) — в десятки раз медленнее | `ps -ef \| grep qemu-system` |
| **libvirt** | Демон + библиотека + API | Хранит VM как XML, запускает QEMU с нужными параметрами, управляет сетями, хранилищами, снапшотами, миграцией | `virsh`, `/etc/libvirt/` |
| **Клиенты** | virsh, virt-install, virt-manager, Vagrant, Terraform, OpenStack Nova | Ходят в libvirt API | — |

```bash
# VM — это обычный процесс QEMU
ps -o pid,nlwp,rss,cmd -C qemu-system-x86_64 | cut -c1-150
#   PID NLWP   RSS CMD
#  4242   9  2.1G /usr/bin/qemu-system-x86_64 -name guest=vm1 ... -accel kvm ...
# NLWP — число потоков: по одному на каждый vCPU + потоки ввода-вывода

top -H -p 4242                  # потоки "CPU 0/KVM", "CPU 1/KVM" — это и есть vCPU
virsh list --all                # то же глазами libvirt
virsh qemu-monitor-command vm1 --hmp 'info kvm'   # kvm support: enabled
```text
**Почему это важно девопсу:** VM грузит хост как процесс. Её CPU видно в `top`, память —
в RSS, диск — в `iotop` по PID QEMU. Все инструменты из Linux-блока работают и для VM.

### Демоны и подключения libvirt

- `libvirtd` — классический монолитный демон (Ubuntu 24.04 по умолчанию).
  В новых Fedora/RHEL — **модульные демоны**: `virtqemud`, `virtnetworkd`, `virtstoraged` и т.д.
  Для тебя разница видна только в `systemctl status`.
- URI подключения:
  - `qemu:///system` — системные VM от root (стенд, прод). Нужна группа `libvirt`.
  - `qemu:///session` — VM текущего пользователя, без root, ограниченная сеть.
  - `qemu+ssh://admin@kvm02/system` — удалённый хост по SSH.
- `virsh uri` покажет, куда ты подключён. Без `LIBVIRT_DEFAULT_URI=qemu:///system`
  обычный пользователь попадает в `session` и видит пустой список VM.

---

## 5. virtio — паравиртуализированные устройства

Полная эмуляция «настоящей» сетевухи (e1000, rtl8139) или IDE-диска медленная: гость
пишет в регистры несуществующего железа, каждое обращение — VM exit. **virtio** —
стандарт устройств, *спроектированных для VM*: гость знает, что он в VM, и обменивается
с хостом через общие кольцевые буферы (virtqueues) — мало VM exit, почти нативная скорость.

| Устройство | Что делает | Замечание |
|------------|-----------|-----------|
| `virtio-net` | Сеть | С `vhost-net` данные идут через ядро хоста, минуя QEMU |
| `virtio-blk` | Диск `/dev/vda` | Простой и быстрый |
| `virtio-scsi` | SCSI-контроллер, диски `/dev/sda` | Много дисков, TRIM/discard; дефолт в Proxmox |
| `virtio-balloon` | «Надувает» память в госте | Хост забирает неиспользуемую RAM |
| `virtio-rng` | Энтропия из хоста | Нет зависания на старте из-за нехватки энтропии |
| `virtio-serial` | Канал хост ↔ гость | Через него работает `qemu-guest-agent` |
| `virtiofs` | Общая папка хост ↔ гость | Замена медленного 9p |

```bash
# внутри гостя
lspci | grep -i virtio          # Virtio network device, Virtio block device ...
lsmod | grep virtio             # virtio_net, virtio_blk, virtio_pci ...
ethtool -i enp1s0 | head -1     # driver: virtio_net
lsblk                           # vda — virtio-blk, sda — virtio-scsi/SATA (имена — ../Linux/09_devices.md)
```text
> 💡 Linux знает virtio из коробки. Windows — нет: при установке подключают ISO
> `virtio-win` с драйверами, иначе установщик не увидит virtio-диск.

---

## 6. VM, системный контейнер (LXC) и контейнер приложения (Docker)

Как устроены namespaces и cgroups — в [../Docker/01_containers_intro.md](/docker/01-containers-intro).
Здесь — сравнение трёх вариантов, которые встретишь on-prem.

| | VM (KVM) | Системный контейнер (LXC) | Контейнер приложения (Docker) |
|---|----------|---------------------------|-------------------------------|
| Ядро | Своё у каждой VM | Общее с хостом | Общее с хостом |
| Внутри | Полная ОС: init, службы, sshd | Полная ОС без своего ядра: systemd, службы, sshd | Обычно один процесс приложения |
| Другая ОС | Да (Windows на Linux-хосте) | Только Linux | Только Linux (на Linux-хосте) |
| Старт | Десятки секунд | Секунды | Доли секунды — секунды |
| Накладные расходы | Память под ядро и ОС каждой VM | Небольшие | Минимальные |
| Изоляция | Аппаратная, сильная | Ядром (слабее); лучше unprivileged | Ядром (слабее) |
| Живая миграция | Да | Нет (в Proxmox — с перезапуском) | Нет, пересоздают |
| Жизненный цикл | «Питомец»: обновляют, чинят | «Питомец», как VM | «Скот»: иммутабельный образ, пересоздают |
| Типичное | БД, Windows, k8s-ноды, всё недоверенное | Лёгкие сервисы: DNS, мониторинг, reverse proxy | Микросервисы, CI, всё, что в k8s |

Правило большого пальца: **нужно своё ядро, другая ОС или сильная изоляция → VM;
нужна лёгкая «почти VM» с Linux → LXC; поставляешь приложение → Docker/k8s**
(обычно внутри VM). Подробно — тема 05.

---

## 7. Ландшафт: кто на рынке в 2026

| Платформа | Основа | Где встречается | Статус и нюансы |
|-----------|--------|-----------------|-----------------|
| **VMware vSphere** (ESXi + vCenter) | Свой type-1 | Банки, госсектор, крупный энтерпрайз — «легаси по умолчанию» | После покупки Broadcom — только подписка, бандлы, рост цен; массовые миграции (ниже) |
| **Proxmox VE** | Debian + KVM/QEMU + LXC | SMB, хостинги, всё чаще энтерпрайз как замена VMware | Open source (AGPLv3), подписка — за enterprise-репозиторий и поддержку. Ветка 9.x на Debian 13 |
| **OpenStack** | Nova + libvirt/KVM, Neutron, Cinder | Частные облака телекомов, провайдеры | Актуальный релиз — 2026.1 Gazpacho (апрель 2026). Мощно, но тяжело в эксплуатации |
| **Microsoft Hyper-V** | Свой type-1 | Windows-инфраструктура | Входит в Windows Server; на его основе работает Azure |
| **oVirt / RHV** | KVM + libvirt + веб-менеджер | Старые инсталляции | Red Hat Virtualization уходит (поддержка заканчивается в 2026), преемник — OpenShift Virtualization. oVirt жив как community-проект, но развивается медленно; для новых проектов его обычно не берут |
| **Nutanix AHV** | KVM | Гиперконвергентные кластеры | Коммерческая альтернатива VMware |
| **XCP-ng** | Xen | SMB, хостинги | Open source, управление через Xen Orchestra |
| **KubeVirt / OpenShift Virtualization / Harvester** | KVM внутри подов Kubernetes | Где уже есть k8s | VM как объект Kubernetes; путь «уйти с VMware в k8s» |

### VMware после Broadcom — что важно знать

```text
 22.11.2023  Broadcom закрыл сделку по VMware
 12.2023     конец продаж вечных лицензий → только подписка;
             сотни продуктов сведены в несколько бандлов (VCF, VVF и др.)
 02.2024     убран бесплатный ESXi
 2025        лицензирование по ядрам, минимум 16 ядер на процессор;
             дистрибьюторы сообщали о минимальном заказе 72 ядра — сведения об отмене
             противоречивы, в реальной сделке уточняй у партнёра
 04.2025     бесплатный ESXi вернули (8.0 Update 3e): без поддержки,
             нельзя подключить к vCenter, до 8 vCPU на VM
 06.2025     VMware Cloud Foundation 9.0
```text
Итог для рынка: у многих клиентов счёт за продление вырос в разы, и «миграция с VMware»
стала типовым проектом. По прогнозу Gartner, к 2028 году около 35% нынешних VMware-нагрузок
будут работать на других платформах. Куда уходят: Proxmox VE (в нём с 8.2 есть мастер
импорта VM прямо с ESXi), Nutanix, Hyper-V, OpenShift Virtualization, облака.

> 💡 Для собеса: VMware всё ещё в каждой второй вакансии крупных компаний. Понимать его на
> уровне терминов (vCenter, datastore, vMotion, DRS, HA) нужно даже без доступа к нему —
> обзор в теме 06.

### Облако = виртуализация внизу

| Облако | Гипервизор |
|--------|-----------|
| AWS | Nitro Hypervisor (основан на KVM); старые инстансы — Xen |
| Google Cloud | KVM |
| Azure | Hyper-V (доработанный) |
| Большинство локальных облаков СНГ | KVM/QEMU, часто OpenStack |

---

## 8. Где девопс встречает виртуализацию on-prem

В Казахстане банки, госсектор и телеком часто живут на своём железе: требования
регуляторов, локализация персональных данных, давно купленный VMware. Значит, облачного
«кнопкой создать инстанс» нет — есть гипервизор и заявки.

| Задача | Что нужно знать |
|--------|-----------------|
| Поднять VM под сервис/k8s-ноду из шаблона | Шаблоны, cloud-init, ресурсы (темы 02, 04, 06) |
| Попросить у сетевиков VLAN и «положить» VM в нужную сеть | Bridge, VLAN, bond на хосте (тема 03) |
| Снапшот перед обновлением, откат | Internal/external, почему снапшот — не бэкап (тема 02) |
| Разобраться, «почему VM тормозит» | Overcommit, steal time, диск, NUMA (тема 02) |
| Бэкапы и восстановление | vzdump, Proxmox Backup Server, тренировка restore (тема 04) |
| Лёгкие сервисы без полной VM | LXC (тема 05) |
| Создавать и настраивать VM кодом | Packer, Terraform, Ansible (тема 06) |
| Мигрировать с VMware | Форматы дисков (vmdk → qcow2), драйверы virtio, импорт в Proxmox |
| Мониторинг хостов | Загрузка CPU/RAM/диска хоста, место в хранилище, состояние кластера |

---

## 9. Грабли

| Симптом | Причина | Что делать |
|---------|---------|-----------|
| `KVM acceleration can NOT be used` | VT-x/AMD-V выключены в BIOS или хост сам — VM без nested | Включить в BIOS; для VM — nested + `host-passthrough` |
| VM работает, но «как черепаха» | QEMU без KVM (TCG, программная эмуляция) | `virsh dumpxml vm \| grep "domain type"` → должно быть `type='kvm'` |
| `virsh list --all` пустой, хотя VM есть | Подключён к `qemu:///session` | `virsh uri`; `export LIBVIRT_DEFAULT_URI=qemu:///system` |
| `Permission denied` на `/dev/kvm` | Пользователь не в группе `kvm`/`libvirt` | `usermod -aG kvm,libvirt $USER` + перелогин |
| VirtualBox и KVM дерутся | Оба хотят VT-x одновременно | На стенде блока — только KVM |
| Windows-гость не видит диск при установке | Нет драйверов virtio | ISO `virtio-win` вторым CD-ROM или SATA на время установки |
| В Proxmox-внутри-VM: `KVM virtualisation configured, but not available` | У VM-гипервизора нет `vmx`/`svm` | На хосте: nested=1, у VM `host-passthrough` |
| Путают «VM» и «контейнер» на собесе | — | Ядро: своё у VM, общее у контейнеров |

---

## 💼 Как это в DevOps

- **On-prem ≈ «облако, которое ты делаешь сам».** Всё, что в облаке делает API провайдера —
  шаблоны, сети, диски, снапшоты, HA, — здесь делает гипервизор и ты.
- **Terraform и Ansible никуда не деваются:** у libvirt, Proxmox и vSphere есть провайдеры
  и inventory-плагины (тема 06). Руками кликают только первый раз.
- **Kubernetes on-prem почти всегда живёт на VM**, а не на голом железе: ноды — VM из
  шаблона, пересоздаются кодом. Понимание гипервизора объясняет «странности» нод:
  steal time, медленные диски, живые миграции.
- **Смена гипервизора — бизнес-проект, а не каприз.** Если компания уходит с VMware,
  девопс переносит шаблоны, пайплайны, мониторинг и бэкапы на новую платформу.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Есть ли VT-x/AMD-V | `grep -cE 'vmx\|svm' /proc/cpuinfo`, `lscpu \| grep -i virt` |
| Есть ли EPT/NPT | `grep -owE 'ept\|npt' /proc/cpuinfo \| sort -u` |
| Готов ли хост к KVM | `kvm-ok`, `virt-host-validate qemu` |
| Включён ли nested | `cat /sys/module/kvm_{intel,amd}/parameters/nested` |
| Модули KVM | `lsmod \| grep kvm` |
| Куда подключён virsh | `virsh uri` |
| Процессы VM на хосте | `ps -ef \| grep qemu-system`, `top -H -p &lt;pid&gt;` |
| Работает ли VM на KVM, а не TCG | `virsh dumpxml vm \| grep "domain type"` |
| Какие устройства virtio в госте | `lspci \| grep -i virtio`, `ethtool -i &lt;iface&gt;` |
| Отдать гостю CPU с флагами | `--cpu host-passthrough` / `&lt;cpu mode='host-passthrough'/&gt;` |

---

## 🧠 Что запомнить

1. Виртуализация = консолидация + скорость + изоляция + снапшоты + миграция/HA. Облако — та же виртуализация с API.
2. Type-1 работает на железе (ESXi, Hyper-V, Xen, KVM), type-2 — программа в ОС (VirtualBox).
3. VT-x/AMD-V дают гостю «свой ring 0» (root/non-root режимы), EPT/NPT — аппаратную трансляцию памяти, IOMMU — безопасный проброс устройств.
4. KVM исполняет гостя на CPU, QEMU эмулирует устройства (процесс на VM), libvirt управляет всем через XML и API.
5. vCPU — поток процесса QEMU: VM видна и измеряется обычными Linux-инструментами.
6. virtio — устройства для VM: быстрее эмуляции; Linux умеет из коробки, Windows нужен virtio-win.
7. VM — своё ядро и сильная изоляция; LXC — «почти VM» на общем ядре; Docker — упаковка приложения.
8. Nested = `nested=1` на хосте + `host-passthrough` у VM-гипервизора.
9. Proxmox VE — Debian + KVM/QEMU + LXC со своими инструментами, без libvirt.
10. После Broadcom VMware стал дорогим, и миграции на Proxmox/KVM — типовая задача 2025–2026.

➡️ Дальше: [02_kvm_qemu_libvirt.md](/virtualization/02-kvm-qemu-libvirt) · задачи: 01_virtualization_intro_tasks.md


---

### Блок A. Теория


**A1.** Назови пять причин, по которым бизнес виртуализирует серверы.

<details><summary>Ответ</summary>

Консолидация железа (меньше серверов, стоек, электричества); скорость выдачи серверов
(VM из шаблона за минуты); изоляция сервисов друг от друга; снапшоты и быстрый откат;
живая миграция и HA без простоя при обслуживании железа. Плюс стенды и разные ОС на одном хосте.

</details>

**A2.** Чем гипервизор type-1 отличается от type-2? По два примера. Куда отнести KVM и почему
это спорно?

<details><summary>Ответ</summary>

Type-1 работает прямо на железе (ESXi, Hyper-V, Xen, KVM), type-2 — приложение внутри
обычной ОС (VirtualBox, VMware Workstation). KVM — модуль ядра Linux: рядом работают обычные
процессы, как у type-2, но планирование vCPU и память VM ведёт само ядро, как у type-1.
Поэтому KVM обычно относят к type-1.

</details>

**A3.** Какую проблему решили VT-x/AMD-V? Что такое VM exit и VM entry?

<details><summary>Ответ</summary>

Гостевое ядро хочет ring 0, а он занят гипервизором. VT-x/AMD-V ввели режимы
root/non-root: гость исполняется в собственном ring 0 non-root прямо на CPU. VM exit —
выход из гостя в гипервизор, когда гость делает то, что нужно перехватить (ввод-вывод,
привилегированная инструкция). VM entry — возврат в гостя.

</details>

**A4.** ⭐ Зачем нужны EPT/NPT? Как гипервизоры обходились без них?

<details><summary>Ответ</summary>

У гостя свои таблицы страниц, а его «физическая» память — это виртуальная память
хоста. Без EPT/NPT гипервизор держал теневые таблицы (shadow page tables) и перехватывал
каждое их изменение — много VM exit. EPT/NPT — вторая аппаратная таблица: CPU сам переводит
гостевой физический адрес в физический адрес хоста.

</details>

**A5.** Что такое IOMMU (VT-d/AMD-Vi) и в каких задачах без неё не обойтись?

<details><summary>Ответ</summary>

IOMMU изолирует DMA устройств. Без неё проброшенное в VM устройство могло бы писать
DMA в память хоста и других VM. Нужна для PCI passthrough (GPU, NIC, HBA) и SR-IOV.

</details>

**A6.** ⭐ Распредели обязанности между KVM, QEMU и libvirt. Что сломается, если убрать каждый слой?

<details><summary>Ответ</summary>

KVM исполняет код гостя на CPU и управляет памятью; QEMU эмулирует устройства и
является процессом VM; libvirt хранит конфигурацию в XML и управляет VM, сетями,
хранилищами через API. Без KVM QEMU уйдёт в программную эмуляцию (TCG) — медленно. Без QEMU
нечем эмулировать диски, сеть, BIOS — VM не запустить. Без libvirt всё работает, но
запускать QEMU придётся длинными командами руками, без virsh, Vagrant и Terraform.

</details>

**A7.** Что такое TCG в QEMU и когда QEMU им пользуется?

<details><summary>Ответ</summary>

TCG (Tiny Code Generator) — программный транслятор инструкций гостя в инструкции
хоста. QEMU использует его, когда KVM недоступен или эмулируется другая архитектура
(ARM-гость на x86-хосте). Работает в разы и десятки раз медленнее KVM.

</details>

**A8.** Что такое virtio и почему это быстрее эмуляции e1000/IDE? Назови четыре virtio-устройства.

<details><summary>Ответ</summary>

virtio — стандарт паравиртуализированных устройств: гость знает, что работает в VM,
и обменивается с хостом через общие очереди в памяти (virtqueues), вместо того чтобы
«дёргать регистры» эмулированного железа, где каждое обращение — VM exit. Устройства:
virtio-net, virtio-blk, virtio-scsi, virtio-balloon, virtio-rng, virtio-serial, virtiofs.

</details>

**A9.** Чем `qemu:///system` отличается от `qemu:///session`?

<details><summary>Ответ</summary>

`system` — системный демон, VM от root, полноценные сети и хранилища; для серверов
и стенда. `session` — VM текущего пользователя без root: свои файлы в домашнем каталоге,
урезанная сеть. Это разные списки VM.

</details>

**A10.** ⭐ Что нужно для nested virtualization? Чем расплачиваешься за `host-passthrough`?

<details><summary>Ответ</summary>

Модуль KVM хоста с `nested=1` и CPU гостя с флагами `vmx`/`svm` — надёжнее всего
`host-passthrough`. Цена: VM привязана к модели CPU хоста — живая миграция на хост с другим
процессором невозможна или рискованна.

</details>

**A11.** Сравни VM, LXC и Docker по ядру, изоляции, времени старта и типичным задачам.

<details><summary>Ответ</summary>

VM — своё ядро, аппаратная изоляция, старт десятки секунд; БД, Windows, k8s-ноды,
недоверенный код. LXC — общее ядро, полная Linux-система внутри, старт секунды; лёгкие
долгоживущие сервисы. Docker — общее ядро, обычно один процесс, старт доли секунды;
приложения, микросервисы, CI.

</details>

**A12.** Что изменилось в лицензировании VMware после покупки Broadcom? Назови 4 факта.

<details><summary>Ответ</summary>

Сделка закрыта в ноябре 2023; конец продаж вечных лицензий — только подписка;
продукты сведены в несколько бандлов (VCF, VVF и др.); лицензирование по ядрам с минимумом

</details>

**A13.** Каков статус oVirt и Red Hat Virtualization? Стоит ли выбирать oVirt для нового проекта?

<details><summary>Ответ</summary>

Red Hat Virtualization (коммерческий oVirt) уходит: поддержка заканчивается в 2026,
преемник — OpenShift Virtualization. oVirt остался community-проектом с медленным развитием.
Для нового проекта обычно выбирают Proxmox VE, OpenStack или KubeVirt, а oVirt — только если
он уже есть.

</details>

**A14.** Из чего состоит Proxmox VE и чем его стек отличается от «virsh + libvirt»?

<details><summary>Ответ</summary>

Debian + ядро с KVM + QEMU (управление `qm`) + LXC (`pct`) + веб-интерфейс и REST API +
кластер (corosync, pmxcfs в `/etc/pve`) + плагины хранилищ (LVM-thin, ZFS, Ceph, NFS) + бэкапы
(vzdump, PBS). libvirt не использует: VM описываются своими конфигами
`/etc/pve/qemu-server/&lt;vmid&gt;.conf`, а не XML libvirt.

</details>

**A15.** На каких гипервизорах работают AWS, Google Cloud и Azure?

<details><summary>Ответ</summary>

AWS — Nitro Hypervisor на базе KVM (старые инстансы — Xen); Google Cloud — KVM;
Azure — доработанный Hyper-V.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  # новый сервер, свежий Xeon
```text
<details><summary>Ответ</summary>

⚠️ Флагов нет, значит, виртуализация выключена в BIOS/UEFI (Intel Virtualization
Technology). Включить и перезагрузить; проверить `kvm-ok`.

</details>

```text:no-line-numbers
     $ grep -cE 'vmx|svm' /proc/cpuinfo
```text
```text:no-line-numbers
     0
```text
```text:no-line-numbers
B2.  $ virsh list --all
```text
<details><summary>Ответ</summary>

⚠️ virsh подключён к `qemu:///session`, а virt-manager — к `qemu:///system`.
`virsh uri`, затем `virsh -c qemu:///system list --all` или `LIBVIRT_DEFAULT_URI`.

</details>

```text:no-line-numbers
      Id   Name   State
```text
```text:no-line-numbers
     --------------------
```text
```text:no-line-numbers
     # а в virt-manager видны три работающие VM
```text
```text:no-line-numbers
B3.  $ virsh dumpxml web1 | grep "domain type"
```text
<details><summary>Ответ</summary>

⚠️ VM работает на TCG без KVM — медленно. Причины: нет `/dev/kvm` (модуль, BIOS,
nested) или VM так создали (`--virt-type qemu`). Поправить в `virsh edit` на `type='kvm'`,
предварительно починив KVM.

</details>

```text:no-line-numbers
     &lt;domain type='qemu'&gt;
```text
```text:no-line-numbers
B4.  # хост: cat /sys/module/kvm_intel/parameters/nested → N
```text
<details><summary>Ответ</summary>

⚠️ Без nested на хосте у pve1 нет `vmx` — Proxmox не даст запустить VM с KVM
(«KVM virtualisation configured, but not available»). Включить nested, дать pve1
`host-passthrough`, перезапустить pve1.

</details>

```text:no-line-numbers
     # VM pve1: &lt;cpu mode='host-model'/&gt;
```text
```text:no-line-numbers
     # в Proxmox внутри pve1 запускают VM с настройками по умолчанию
```text
```text:no-line-numbers
B5.  «Поставим Windows Server 2025 в LXC-контейнер на Proxmox, так легче»
```text
<details><summary>Ответ</summary>

⚠️ Контейнер использует ядро хоста — Linux. Windows в LXC невозможен, нужна VM.

</details>

```text:no-line-numbers
B6.  # у VM 8 vCPU; на хосте в top:
```text
<details><summary>Ответ</summary>

✅ Это не авария: 790% = почти 8 полностью загруженных ядер, то есть гость грузит все

</details>

```text:no-line-numbers
       PID USER          %CPU  COMMAND
```text
```text:no-line-numbers
      4242 libvirt+     790.0  qemu-system-x86
```text
```text:no-line-numbers
B7.  # установка Windows в VM с диском bus=virtio:
```text
<details><summary>Ответ</summary>

⚠️ В установщике Windows нет драйверов virtio. Подключить ISO `virtio-win` и
загрузить драйвер `viostor` (virtio-blk) или `vioscsi`, либо ставить на SATA и потом переключить.

</details>

```text:no-line-numbers
     «Не найдено ни одного диска для установки»
```text
```text:no-line-numbers
B8.  «Контейнеры изолированы так же хорошо, как VM. Запустим код клиентов
```text
<details><summary>Ответ</summary>

⚠️ Контейнеры делят ядро: эксплойт ядра пробивает всех соседей. Для недоверенного
кода разных клиентов — отдельные VM или песочницы (Kata Containers, gVisor, Firecracker).

</details>

```text:no-line-numbers
      разных компаний в Docker на одном общем хосте»
```text
```text:no-line-numbers
B9.  $ sudo modprobe -r kvm_intel
```text
<details><summary>Ответ</summary>

⚠️ Модуль занят запущенными VM. Выключить все VM (и остановить то, что держит
`/dev/kvm`), потом выгружать. Быстрее — перезагрузить хост с новым файлом в `modprobe.d`.

</details>

```text:no-line-numbers
     modprobe: FATAL: Module kvm_intel is in use.
```text
```text:no-line-numbers
B10.  $ virt-host-validate qemu
```text
<details><summary>Ответ</summary>

⚠️ Неверный вывод. На cgroup v2 нет контроллера `devices` — доступом к устройствам
управляет eBPF, libvirt это умеет. Это WARN, а не FAIL.

</details>

```text:no-line-numbers
       QEMU: Checking for cgroup 'devices' controller support : WARN (...)
```text
```text:no-line-numbers
     # «хост не готов к виртуализации, нужно переустанавливать»
```text
```text:no-line-numbers
B11.  «Купим VMware по вечной лицензии, как в 2019-м, и пять лет не будем думать»
```text
<details><summary>Ответ</summary>

⚠️ Вечные лицензии VMware больше не продаются — только подписка с ежегодными
платежами. Бюджет считать на подписку и заодно сравнить с альтернативами.

</details>

```text:no-line-numbers
B12.  # на хосте с работающими KVM-VM запускают VirtualBox:
```text
<details><summary>Ответ</summary>

⚠️ VT-x уже занят KVM. Два гипервизора одновременно не работают: остановить KVM-VM
и выгрузить модуль или не использовать VirtualBox на этом хосте.

</details>

```text:no-line-numbers
     VT-x is being used by another hypervisor (VERR_VMX_IN_VMX_ROOT_MODE)
```text
---

### Блок C. Практика


### C1. 🔑 Паспорт хоста
Собери в заметку «паспорт» своего хоста: модель CPU, флаги `vmx`/`svm`, `ept`/`npt`,
состояние nested, модули KVM, права на `/dev/kvm`, вывод `virt-host-validate qemu`, версии
libvirt и QEMU (`virsh version`). Отметь каждый WARN и объясни, критичен ли он.

### C2. 🔑 VM — это процесс
**1.** Подними любую VM (`vagrant up` в `learn-linux` подойдёт).

<details><summary>Ответ</summary>

Команды: `lscpu`, `grep -cE 'vmx|svm' /proc/cpuinfo`, `grep -owE 'ept|npt' /proc/cpuinfo | sort -u`,
`cat /sys/module/kvm_*/parameters/nested`, `lsmod | grep kvm`, `ls -l /dev/kvm`,
`virt-host-validate qemu`, `virsh version`. Типичные WARN: cgroup `devices` (норма для v2),
IOMMU (нужен только для passthrough — `intel_iommu=on`/`amd_iommu` в параметрах ядра),
secure guest (SEV/TDX — не нужен для стенда).

</details>

**2.** Найди PID её процесса QEMU. Сколько у него потоков? Сопоставь с числом vCPU (`virsh vcpucount`).

<details><summary>Ответ</summary>

`pgrep -af qemu-system` или `ps -ef | grep qemu`; `ps -o nlwp -p &lt;PID&gt;` — потоков больше,
чем vCPU: плюс потоки ввода-вывода, главный цикл, vhost. В `top -H` видны `CPU 0/KVM`,
`CPU 1/KVM` — загораются под нагрузкой. RSS меньше выделенной памяти, потому что гость ещё не
тронул всю память (страницы выделяются при первом обращении), а balloon мог часть забрать.

</details>

**3.** В `top -H -p &lt;PID&gt;` найди потоки vCPU. Дай нагрузку внутри VM (`yes > /dev/null &` × 2)
   и посмотри, какие потоки загорелись.

<details><summary>Ответ</summary>

В провайдере libvirt: `v.nested = true`, `v.cpu_mode = "host-passthrough"`. Внутри:
`grep -cE 'vmx|svm' /proc/cpuinfo` > 0, `ls -l /dev/kvm` существует, `kvm-ok` — «can be used».
С дефолтным `host-model` флаги часто тоже есть (libvirt включает `vmx`/`svm`, если хост умеет
nested), но `host-passthrough` даёт гарантию и полный набор инструкций.

</details>

**4.** Сравни RSS процесса с памятью VM из `virsh dominfo`. Почему RSS может быть меньше?

<details><summary>Ответ</summary>

В госте: `lspci | grep -i virtio`, `lsmod | grep virtio`, `ethtool -i eth0` →
`driver: virtio_net`, `lsblk` → `vda`. В XML: `&lt;interface ...&gt;&lt;model type='virtio'/&gt;` и
`&lt;disk ...&gt;&lt;target dev='vda' bus='virtio'/&gt;`. Канал `org.qemu.guest_agent.0` —
virtio-serial для `qemu-guest-agent`: через него хост узнаёт IP гостя, корректно выключает
его, замораживает ФС перед снапшотом (тема 02).

</details>

### C3. Nested внутри Vagrant-VM
**1.** Проверь nested на хосте.

<details><summary>Ответ</summary>

Команды: `lscpu`, `grep -cE 'vmx|svm' /proc/cpuinfo`, `grep -owE 'ept|npt' /proc/cpuinfo | sort -u`,
`cat /sys/module/kvm_*/parameters/nested`, `lsmod | grep kvm`, `ls -l /dev/kvm`,
`virt-host-validate qemu`, `virsh version`. Типичные WARN: cgroup `devices` (норма для v2),
IOMMU (нужен только для passthrough — `intel_iommu=on`/`amd_iommu` в параметрах ядра),
secure guest (SEV/TDX — не нужен для стенда).

</details>

**2.** В `Vagrantfile` учебной VM добавь `v.nested = true` и `v.cpu_mode = "host-passthrough"`,
   выполни `vagrant reload`.

<details><summary>Ответ</summary>

`pgrep -af qemu-system` или `ps -ef | grep qemu`; `ps -o nlwp -p &lt;PID&gt;` — потоков больше,
чем vCPU: плюс потоки ввода-вывода, главный цикл, vhost. В `top -H` видны `CPU 0/KVM`,
`CPU 1/KVM` — загораются под нагрузкой. RSS меньше выделенной памяти, потому что гость ещё не
тронул всю память (страницы выделяются при первом обращении), а balloon мог часть забрать.

</details>

**3.** Внутри VM докажи, что KVM доступен: флаги CPU, `/dev/kvm`, `kvm-ok`.

<details><summary>Ответ</summary>

В провайдере libvirt: `v.nested = true`, `v.cpu_mode = "host-passthrough"`. Внутри:
`grep -cE 'vmx|svm' /proc/cpuinfo` > 0, `ls -l /dev/kvm` существует, `kvm-ok` — «can be used».
С дефолтным `host-model` флаги часто тоже есть (libvirt включает `vmx`/`svm`, если хост умеет
nested), но `host-passthrough` даёт гарантию и полный набор инструкций.

</details>

**4.** Верни `cpu_mode` по умолчанию и проверь снова. Что изменилось?

<details><summary>Ответ</summary>

В госте: `lspci | grep -i virtio`, `lsmod | grep virtio`, `ethtool -i eth0` →
`driver: virtio_net`, `lsblk` → `vda`. В XML: `&lt;interface ...&gt;&lt;model type='virtio'/&gt;` и
`&lt;disk ...&gt;&lt;target dev='vda' bus='virtio'/&gt;`. Канал `org.qemu.guest_agent.0` —
virtio-serial для `qemu-guest-agent`: через него хост узнаёт IP гостя, корректно выключает
его, замораживает ФС перед снапшотом (тема 02).

</details>

### C4. 🔑 virtio глазами гостя и хоста
**1.** Внутри VM найди все virtio-устройства (`lspci`, `lsmod`, `ethtool -i`, `lsblk`).

<details><summary>Ответ</summary>

Команды: `lscpu`, `grep -cE 'vmx|svm' /proc/cpuinfo`, `grep -owE 'ept|npt' /proc/cpuinfo | sort -u`,
`cat /sys/module/kvm_*/parameters/nested`, `lsmod | grep kvm`, `ls -l /dev/kvm`,
`virt-host-validate qemu`, `virsh version`. Типичные WARN: cgroup `devices` (норма для v2),
IOMMU (нужен только для passthrough — `intel_iommu=on`/`amd_iommu` в параметрах ядра),
secure guest (SEV/TDX — не нужен для стенда).

</details>

**2.** На хосте в `virsh dumpxml` найди, где задаются `model type='virtio'` для сети и `bus='virtio'`
   для диска.

<details><summary>Ответ</summary>

`pgrep -af qemu-system` или `ps -ef | grep qemu`; `ps -o nlwp -p &lt;PID&gt;` — потоков больше,
чем vCPU: плюс потоки ввода-вывода, главный цикл, vhost. В `top -H` видны `CPU 0/KVM`,
`CPU 1/KVM` — загораются под нагрузкой. RSS меньше выделенной памяти, потому что гость ещё не
тронул всю память (страницы выделяются при первом обращении), а balloon мог часть забрать.

</details>

**3.** Найди канал `org.qemu.guest_agent.0`. Для чего он?

<details><summary>Ответ</summary>

В провайдере libvirt: `v.nested = true`, `v.cpu_mode = "host-passthrough"`. Внутри:
`grep -cE 'vmx|svm' /proc/cpuinfo` > 0, `ls -l /dev/kvm` существует, `kvm-ok` — «can be used».
С дефолтным `host-model` флаги часто тоже есть (libvirt включает `vmx`/`svm`, если хост умеет
nested), но `host-passthrough` даёт гарантию и полный набор инструкций.

</details>

### C5. KVM против TCG своими глазами
Запусти ядро хоста в QEMU без диска (ядро дойдёт до паники «не могу смонтировать root» и выйдет)
и засеки время с KVM и без:
```text:no-line-numbers
sudo cp /boot/vmlinuz-$(uname -r) /tmp/vmlinuz && sudo chmod 644 /tmp/vmlinuz
```text
```text:no-line-numbers
time qemu-system-x86_64 -accel kvm -m 512 -nographic -no-reboot \
```text
```text:no-line-numbers
  -kernel /tmp/vmlinuz -append "console=ttyS0 panic=-1" 2>&1 | tail -3
```text
```text:no-line-numbers
time qemu-system-x86_64 -accel tcg -m 512 -nographic -no-reboot \
```text
```text:no-line-numbers
  -kernel /tmp/vmlinuz -append "console=ttyS0 panic=-1" 2>&1 | tail -3
```text
Во сколько раз отличается? Почему облачная VM без KVM была бы бесполезна?

### C6. 🔑 Выбери платформу
Для каждой нагрузки выбери VM, LXC или Docker и обоснуй одной фразой: прод-PostgreSQL;
Windows Server с Active Directory; GitLab Runner для сборки образов; внутренний DNS-резолвер;
**10.** микросервисов на Go; старое приложение, которому нужен свой модуль ядра; код, присланный
клиентами на проверку.
### C7. Рынок глазами вакансий
Найди 5 вакансий DevOps/SRE в Казахстане (hh.kz или LinkedIn) с on-prem. Выпиши, какие
платформы виртуализации упомянуты и какие задачи с ними связаны. Какие слова встречаются
чаще всего?

### C8. VMware против Proxmox по памяти
Составь таблицу без подсказок: управление (vCenter ↔ ?), живая миграция, HA, кластер,
бэкапы, контейнеры, лицензия. Потом сверься с темами 04 и 06.

---

### Блок D. Инциденты


**D1.** После обновления BIOS на хосте VM не стартуют:
`Could not access KVM kernel module: No such file or directory`. Что случилось и как проверить?

<details><summary>Ответ</summary>

Обновление BIOS сбросило настройки, VT-x/AMD-V выключились. `dmesg | grep -i kvm` —
«kvm: disabled by bios» (или похожее сообщение), `grep -c vmx /proc/cpuinfo` → 0. Включить
в BIOS, перезагрузить, проверить `kvm-ok`, запустить VM.

</details>

**D2.** После обновления ядра все VM на хосте стали работать в десятки раз медленнее.
`lsmod | grep kvm` — пусто. Твои действия?

<details><summary>Ответ</summary>

Модуль KVM не загрузился — VM (если вообще стартуют) ушли на TCG. Проверить:
`dmesg | grep -i kvm`, `modprobe kvm_intel` (или `kvm_amd`) и ошибку, нет ли модуля в
blacklist (`grep -r kvm /etc/modprobe.d/`), установлены ли модули для нового ядра
(`ls /lib/modules/$(uname -r)/kernel/arch/x86/kvm/`). Временно — загрузиться со старым ядром.
Потом проверить, что VM снова `type='kvm'`.

</details>

**D3.** Во вложенном Proxmox VM стартуют, но загружаются по 10 минут, а внутри всё медленно.
На хосте nested включён. Что проверить?

<details><summary>Ответ</summary>

В свойствах VM Proxmox (Options → KVM hardware virtualization) KVM выключен — VM
работают на TCG. Или у pve1 не `host-passthrough`, и Proxmox предложил выключить KVM, чтобы VM
вообще стартовала. Проверить `grep -cE 'vmx|svm' /proc/cpuinfo` внутри pve1 и `kvm: 1` в
конфиге VM.

</details>

**D4.** Новый коллега пишет: «Я в группе libvirt, `virsh list --all` пустой, а у тебя там
десять VM». В чём дело?

<details><summary>Ответ</summary>

Коллега подключается к `qemu:///session` — там свои пустые VM. Нужен
`virsh -c qemu:///system` или `export LIBVIRT_DEFAULT_URI=qemu:///system` в `~/.bashrc`.

</details>

**D5.** Хост с 128 ГБ RAM, VM суммарно выделено 150 ГБ. Ночью одна VM «сама выключилась»,
в её логе ничего нет. Где искать и что это было?

<details><summary>Ответ</summary>

Overcommit памяти: хост кончил RAM, и OOM-killer ядра хоста убил самый «толстый»
процесс — QEMU этой VM. В госте логов нет, потому что его просто выключили. Искать в
`journalctl -k | grep -i -E "oom|killed process"` на хосте и в `/var/log/libvirt/qemu/&lt;vm&gt;.log`.
Лечить: не переподписывать RAM, balloon/KSM осознанно, лимиты, мониторинг свободной памяти хоста.

</details>

**D6.** Финдиректор: «VMware прислал счёт на продление в три раза больше прошлогоднего. Какие
у нас варианты?» Составь план ответа.

<details><summary>Ответ</summary>

План: 1) инвентаризация — сколько хостов, ядер, VM, какие функции реально используются
(vMotion, HA, DRS, vSAN, NSX); 2) варианты — продлить (правильный бандл, торг с партнёром),
частичная миграция некритичного, полная миграция (Proxmox, Nutanix, Hyper-V, OpenShift
Virtualization, облако); 3) стоимость миграции — люди, обучение, бэкапы, мониторинг, риски
простоя; 4) пилот на Proxmox для некритичных VM; 5) сравнение совокупной стоимости на 3 года.

</details>

**D7.** Общий Docker-хост для сервисов нескольких клиентов. Выходит CVE с побегом из контейнера
через ядро. Чем это грозит и что менять в архитектуре?

<details><summary>Ответ</summary>

Побег из контейнера через ядро = доступ к хосту и ко всем контейнерам всех клиентов.
Срочно: обновить ядро, закрыть CVE. Архитектурно: изоляция клиентов через VM (отдельная VM
или нода на клиента), либо песочницы на микро-VM (Kata Containers, Firecracker), rootless,
seccomp, запрет привилегированных контейнеров.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Что такое гипервизор? Какие бывают типы?

<details><summary>Ответ</summary>

Гипервизор — софт, который создаёт VM и делит между ними ресурсы. Type-1 работает на железе
   (ESXi, Hyper-V, Xen, KVM), type-2 — приложение в ОС (VirtualBox, Workstation).

</details>

**2.** Как связаны KVM, QEMU и libvirt?

<details><summary>Ответ</summary>

KVM — модуль ядра, исполняет гостя на CPU через VT-x/AMD-V; QEMU — процесс на VM, эмулирует
   устройства; libvirt — API и XML-описание VM, сетей, хранилищ, им пользуются virsh,
   virt-manager, Vagrant, Terraform, OpenStack.

</details>

**3.** Чем виртуальная машина отличается от контейнера?

<details><summary>Ответ</summary>

У VM своё ядро и эмулированное железо — сильная изоляция, любая ОС, тяжелее. Контейнер —
   процесс хоста в namespaces и cgroups на общем ядре — лёгкий и быстрый, но изоляция слабее
   и только Linux на Linux.

</details>

**4.** Что такое virtio и паравиртуализация?

<details><summary>Ответ</summary>

Паравиртуализация — гость знает, что он в VM, и работает с гипервизором через специальный
   интерфейс. virtio — стандарт таких устройств (сеть, диск, balloon, serial): общие очереди
   в памяти вместо эмуляции регистров, поэтому почти нативная скорость.

</details>

**5.** Что такое nested virtualization и где она нужна?

<details><summary>Ответ</summary>

Запуск гипервизора внутри VM: стенды Proxmox/OpenStack, CI для образов VM, облачные
   инстансы с поддержкой вложенной виртуализации. Нужны `nested=1` на хосте и `host-passthrough`
   у VM. Производительность вложенных VM ниже.

</details>

**6.** Как проверить, что сервер поддерживает аппаратную виртуализацию?

<details><summary>Ответ</summary>

`grep -cE 'vmx|svm' /proc/cpuinfo`, `lscpu | grep Virtualization`, `kvm-ok`,
   `virt-host-validate qemu`, существует ли `/dev/kvm`; если флагов нет — BIOS.

</details>

**7.** Какие платформы виртуализации знаешь? Что происходит с VMware?

<details><summary>Ответ</summary>

VMware vSphere, Proxmox VE, OpenStack, Hyper-V, oVirt, Nutanix AHV, XCP-ng, KubeVirt.
   VMware после покупки Broadcom перешёл на подписку и бандлы, цены выросли — компании
   мигрируют на Proxmox и другие платформы.

</details>

**8.** Почему Kubernetes on-prem обычно ставят на VM, а не на голое железо?

<details><summary>Ответ</summary>

VM дают изоляцию и гибкость: ноду пересоздают из шаблона кодом, железо делится между
   кластерами и окружениями, есть снапшоты и миграции для обслуживания железа, проще
   масштабировать. Голое железо берут под высокую производительность (GPU, БД, сеть).

</details>

**9.** Что такое overcommit и чем он опасен?

<details><summary>Ответ</summary>

Выделено больше ресурсов, чем физически есть. CPU переподписывают умеренно (vCPU ждут
   очереди — steal time), RAM опасно: закончилась — своп на хосте или OOM-killer убивает VM.

</details>

**10.** Где заканчивается ответственность девопса и начинается работа админа гипервизора?

<details><summary>Ответ</summary>

Типично: админы/инфраструктура отвечают за железо, гипервизоры, СХД и сеть хостов;
    девопс — за VM из шаблонов, автоматизацию (Terraform/Ansible), сервисы внутри и их
    мониторинг. В маленьких компаниях девопс делает всё, поэтому гипервизор знать нужно.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Объясняю зачем виртуализация и разницу type-1 / type-2
- [ ] ⭐ Рассказываю, что делают VT-x/AMD-V, EPT/NPT и IOMMU
- [ ] ⭐ Раскладываю обязанности KVM, QEMU и libvirt и показываю VM как процесс на хосте
- [ ] Знаю, что такое virtio и нахожу virtio-устройства в госте
- [ ] Проверяю хост командами `kvm-ok`, `virt-host-validate`, `/proc/cpuinfo`
- [ ] Включаю nested и объясняю цену `host-passthrough`
- [ ] Выбираю VM / LXC / Docker для задачи и обосновываю
- [ ] Рассказываю про рынок: VMware после Broadcom, Proxmox, OpenStack, oVirt
