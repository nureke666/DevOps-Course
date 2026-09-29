---
title: "05. Системные контейнеры: LXC, Incus, LXC в Proxmox"
description: "Блок → Виртуализация on-prem → тема 05. Опирается на"
---

# 05. Системные контейнеры: LXC, Incus, LXC в Proxmox

> Блок → Виртуализация on-prem → тема 05. Опирается на
> [../Docker/01_containers_intro.md](/docker/01-containers-intro) (namespaces, cgroups,
> capabilities — механизмы те же), [../Linux/12_kernel.md](/linux/12-kernel) (ядро, модули)
> и [04_proxmox.md](/virtualization/04-proxmox) (`pct`, хранилища, сеть).
>
> **После темы ты умеешь:** объяснить разницу системного контейнера и контейнера приложения,
> поднять LXC руками (privileged и unprivileged), понимать idmap и `/etc/subuid`, работать
> с Incus (и знать, откуда он взялся), создавать и настраивать контейнеры в Proxmox
> (unprivileged, nesting, bind mounts, idmap) и выбирать между LXC, VM и Docker.

---

## 🗺️ Карта темы

```text
                ОДНО ЯДРО ХОСТА (namespaces + cgroups + AppArmor/seccomp)
  ┌──────────────────────────────┬──────────────────────────────┬─────────────────────────┐
  │ СИСТЕМНЫЙ КОНТЕЙНЕР (LXC)    │ КОНТЕЙНЕР ПРИЛОЖЕНИЯ (Docker)│ VM (для сравнения)      │
  │ PID 1 = systemd              │ PID 1 = твой процесс         │ своё ядро               │
  │ sshd, cron, journald, apt    │ один сервис, образ-слои      │ любая ОС                │
  │ живёт годами, обновляют      │ пересоздают из образа        │ живёт годами            │
  │ «лёгкая VM»                  │ «упакованное приложение»     │ «железо в софте»        │
  └──────────────────────────────┴──────────────────────────────┴─────────────────────────┘
  Инструменты:  liblxc + lxc-* (LXC 7.0 LTS)   ·   Incus (форк LXD, контейнеры + VM)
                LXD (Canonical)                ·   Proxmox pct (своё управление поверх LXC)
  Безопасность: privileged (root = root хоста) ✗  →  unprivileged (root = UID 100000 хоста) ✓
```text
---

## 1. Системный контейнер против контейнера приложения

Механизмы изоляции у LXC и Docker одинаковые — namespaces, cgroups, capabilities, seccomp,
LSM (разобраны в [../Docker/01_containers_intro.md](/docker/01-containers-intro)).
Разная **модель использования**:

| | Системный (LXC/Incus/pct) | Приложения (Docker/Podman) |
|---|---------------------------|----------------------------|
| Что внутри | Полный дистрибутив: systemd, sshd, пакетный менеджер | Приложение и его зависимости |
| PID 1 | `systemd` (или другой init) | Процесс приложения |
| Сколько сервисов | Сколько угодно, как на сервере | Один процесс на контейнер |
| Жизненный цикл | Создали и обслуживаем: `apt upgrade`, конфиги, бэкапы | Иммутабельный образ: новая версия = новый контейнер |
| Данные | Прямо в rootfs (бэкапится целиком) | Volumes отдельно от образа |
| Управление | Как VM: SSH, Ansible | Как пакет: образ, registry, оркестратор |
| Поставка | Шаблон ОС | Образ из Dockerfile |

> 💡 Системный контейнер — это «VM без своего ядра». Для Ansible и мониторинга он выглядит
> как обычный сервер, но стартует за секунды и почти не ест лишней памяти.

---

## 2. Семейство LXC: кто есть кто

```text
 2008  LXC (liblxc + утилиты lxc-*) — низкоуровневый менеджер контейнеров
 2014  LXD (Canonical) — демон и REST API поверх LXC: удобный CLI, образы, кластеры, позже VM
 07.2023  Canonical забрала LXD из проекта linuxcontainers.org под своё крыло
 08.2023  Incus — community-форк LXD в linuxcontainers.org (ведут бывшие авторы LXD)
 12.2023  LXD перелицензирован в AGPLv3 с CLA; Incus остался на Apache 2.0
 04.2024  Incus 6.0 LTS (поддержка до июня 2029)
 весна 2026  LXC 7.0 LTS и Incus 7.0 LTS; дальше ветка 7.x
```text
| Инструмент | Что это | Когда встретишь |
|------------|---------|-----------------|
| **LXC** (`lxc-create`, `lxc-start`…) | Библиотека и утилиты, фундамент | Руками редко; внутри Proxmox и Incus |
| **Incus** (`incus`) | Демон + CLI: контейнеры **и VM** (QEMU) одним интерфейсом, образы, сети, кластеры | Новые установки «LXD-стиля», хостинги, лаборатории |
| **LXD** (`lxc` — да, CLI у LXD тоже называется `lxc`) | Продукт Canonical | Ubuntu-инфраструктура, snap |
| **Proxmox `pct`** | Своё управление поверх liblxc | ⭐ Самый частый LXC в on-prem |
| systemd-nspawn | Контейнеры из systemd | Сборка образов, простые песочницы |

> ⚠️ Путаница имён: команда `lxc` — это CLI **LXD**, а утилиты классического LXC называются
> `lxc-*` с дефисом. В Incus CLI называется `incus`.

---

## 3. LXC руками

```bash
sudo apt install -y lxc            # Ubuntu 24.04: LXC 5.0 + мост lxcbr0 (10.0.3.0/24) от службы lxc-net
lxc-checkconfig                    # ядро готово? namespaces, cgroups — всё «enabled»

# privileged-контейнер от root (для понимания; в проде так не делай)
sudo lxc-create -n c1 -t download -- -d debian -r trixie -a amd64
sudo lxc-start -n c1
sudo lxc-ls -f                     # NAME STATE AUTOSTART GROUPS IPV4 ...
sudo lxc-attach -n c1              # шелл внутри (без SSH)
sudo lxc-info -n c1                # PID init-процесса на хосте, IP, память
sudo lxc-stop -n c1 && sudo lxc-destroy -n c1
```text
Где что лежит: `/var/lib/lxc/c1/config` (конфиг), `/var/lib/lxc/c1/rootfs/` (файловая система —
обычный каталог на хосте), `/etc/lxc/default.conf` (дефолты для новых контейнеров).

```ini
# фрагмент /var/lib/lxc/c1/config
lxc.net.0.type = veth
lxc.net.0.link = lxcbr0             # veth-пара: один конец в контейнере, второй в мосте
lxc.net.0.flags = up
lxc.rootfs.path = dir:/var/lib/lxc/c1/rootfs
lxc.uts.name = c1
lxc.cgroup2.memory.max = 512M       # лимит памяти (cgroup v2)
lxc.cgroup2.cpu.max = 50000 100000  # не больше 0,5 CPU
lxc.start.auto = 1                  # автостарт с хостом
```text
Контейнер — это процессы хоста: `sudo lxc-info -n c1 -p` даёт PID, дальше
`ps -o pid,user,cmd --ppid &lt;PID&gt;` и `ls -l /proc/&lt;PID&gt;/ns/` — всё как с Docker.

---

## 4. Unprivileged-контейнеры и idmap

**Проблема privileged:** root в контейнере = UID 0 на хосте. Его сдерживают только
capabilities, seccomp и AppArmor. Уязвимость в ядре или ошибка конфигурации — и это root
на хосте.

**Решение — user namespace:** UID внутри контейнера отображаются на диапазон «ничьих» UID хоста.

```text
   внутри контейнера              на хосте
   root      (UID 0)      ──►     UID 100000   (никто, прав на хосте нет)
   www-data  (UID 33)     ──►     UID 100033
   devops    (UID 1000)   ──►     UID 101000
   ...                            ... диапазон из 65536 UID: 100000–165535
```text
Диапазоны, которые пользователю разрешено отображать, выдаёт хост:
```bash
cat /etc/subuid /etc/subgid         # формат  user:start:count
# nurik:100000:65536
# root:100000:65536                 # в Proxmox — для root
```text
**Unprivileged-контейнер от обычного пользователя:**
```bash
echo "$(id -un) veth lxcbr0 10" | sudo tee -a /etc/lxc/lxc-usernet   # разрешить 10 veth в lxcbr0
mkdir -p ~/.config/lxc
cat > ~/.config/lxc/default.conf <<'EOF'
lxc.include = /etc/lxc/default.conf
lxc.idmap = u 0 100000 65536
lxc.idmap = g 0 100000 65536
EOF
# числа — из твоих строк /etc/subuid и /etc/subgid

systemd-run --user --scope -p "Delegate=yes" -- lxc-create -n u1 -t download -- -d debian -r trixie -a amd64
systemd-run --user --scope -p "Delegate=yes" -- lxc-start -n u1
lxc-attach -n u1 -- cat /proc/self/uid_map     #          0     100000      65536
ps -eo user:10,pid,cmd | grep -E '^100000' | head -3   # процессы контейнера на хосте — от UID 100000
ls -ln ~/.local/share/lxc/u1/rootfs/etc/passwd          # владелец 100000 — это «root» контейнера
```text
`systemd-run ... Delegate=yes` нужен, чтобы обычному пользователю выдали свою ветку cgroup v2.

**Ограничения unprivileged:**
- Нельзя монтировать большинство ФС изнутри (NFS/CIFS в контейнере — нет; монтируй на хосте
  и пробрасывай bind mount'ом).
- Нет доступа к устройствам хоста без явного проброса.
- Bind mount каталога хоста: файлы с владельцем UID 1000 на хосте внутри видны как
  `nobody` (65534) — они вне диапазона отображения. Лечится chown на UID со сдвигом
  (100000+), своим idmap или idmapped mounts (раздел 6).

### Что ещё держит контейнер

User namespace — главный барьер, но не единственный. Остальные слои те же, что у Docker:

| Слой | Как задаётся в LXC | Что даёт |
|------|--------------------|----------|
| Capabilities | `lxc.cap.drop = sys_module mac_admin ...` | Даже root контейнера не грузит модули ядра, не меняет время хоста |
| Seccomp | `lxc.seccomp.profile = ...` | Опасные системные вызовы запрещены (`kexec_load`, `open_by_handle_at` и др.) |
| AppArmor | `lxc.apparmor.profile = generated` | Запрет на запись в чувствительные места `/proc` и `/sys`, монтирования |
| cgroups | `lxc.cgroup2.*` | Лимиты CPU, памяти, PIDs — сосед не съест хост |
| lxcfs | ставится на хост | Контейнер видит в `/proc/meminfo`, `uptime` свои лимиты, а не хост |

```bash
# на хосте: к какому профилю AppArmor привязаны процессы контейнера
sudo cat /proc/$(sudo lxc-info -n c1 -p -H)/attr/current      # lxc-c1_</var/lib/lxc> (enforce)
grep -E 'Cap(Eff|Bnd)' /proc/$(sudo lxc-info -n c1 -p -H)/status   # урезанный набор capabilities
```text
> 💡 Для privileged-контейнера эти слои — **единственная** защита хоста. Поэтому Proxmox
> пишет в документации, что privileged-контейнеры — только для доверенных нагрузок.

---

## 5. Incus: «LXD по-человечески», контейнеры и VM

```bash
sudo apt install -y incus                 # Ubuntu 24.04: Incus 6.0 LTS; свежие версии — репозиторий Zabbly
sudo usermod -aG incus-admin "$USER"      # ⚠️ incus-admin = фактически root на хосте
newgrp incus-admin
incus admin init --minimal                # пул хранения (dir) + мост incusbr0 с NAT

incus launch images:debian/13 c1          # контейнер
incus launch images:ubuntu/24.04 v1 --vm  # VM на QEMU/KVM — тем же CLI
incus list
incus exec c1 -- bash
incus config set c1 limits.cpu=2 limits.memory=1GiB
incus config show c1
incus snapshot create c1 clean
incus snapshot restore c1 clean
incus stop c1 && incus delete c1
incus image list images: debian           # что есть на сервере образов
```text
- Контейнеры Incus по умолчанию **unprivileged** (`security.privileged=false`).
- `security.nesting=true` — если внутри нужен Docker или другие контейнеры.
- `cloud-init` работает и здесь: образы с суффиксом `/cloud` читают `cloud-init.user-data`
  из конфигурации инстанса.
- Есть провайдер Terraform (`lxc/incus`) и кластеризация — это полноценная платформа
  для небольших инсталляций.

> ⚠️ **Incus и Docker на одном хосте:** Docker ставит `iptables FORWARD DROP`, и контейнеры
> Incus теряют выход в сеть — та же история, что с бриджами VM
> ([03_virt_networking.md](/virtualization/03-virt-networking), раздел 3). Лечится правилами в `DOCKER-USER`
> или отдельными хостами.

---

## 6. LXC в Proxmox

```bash
pveam update
pveam available --section system | grep debian-13
pveam download local debian-13-standard_13.6-1_amd64.tar.zst

pct create 200 local:vztmpl/debian-13-standard_13.6-1_amd64.tar.zst \
  --hostname ct1 --cores 1 --memory 512 --swap 512 --rootfs local-lvm:8 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp,tag=20 \
  --unprivileged 1 --features nesting=1 \
  --ssh-public-keys /root/devops.pub --start 1
```text
```ini
# /etc/pve/lxc/200.conf
arch: amd64
cores: 1
features: nesting=1
hostname: ct1
memory: 512
net0: name=eth0,bridge=vmbr0,hwaddr=BC:24:11:3A:5C:0D,ip=dhcp,tag=20,type=veth
ostype: debian
rootfs: local-lvm:vm-200-disk-0,size=8G
swap: 512
unprivileged: 1
```text
| Команда | Что делает |
|---------|-----------|
| `pct enter 200` / `pct console 200` | Шелл внутри / консоль (getty) |
| `pct exec 200 -- apt update` | Команда внутри без входа |
| `pct push 200 ./app.conf /etc/app.conf` / `pct pull` | Скопировать файл внутрь / наружу |
| `pct set 200 --memory 1024 --cores 2` | Изменить ресурсы (на ходу) |
| `pct resize 200 rootfs +4G` | Увеличить диск |
| `pct snapshot 200 base` / `pct rollback 200 base` | Снапшот / откат |
| `pct migrate 200 pve2 --restart` | Миграция с перезапуском (живой миграции у LXC нет) |
| `pct config 200` | Конфиг |

**Privileged или unprivileged.** При создании через `pct` и интерфейс по умолчанию
`unprivileged: 1` — так и оставляй. Privileged — только для доверенных нагрузок, когда
без него никак (некоторые NFS-сценарии, старое ПО).

**Features:**
- `nesting=1` — доступ к `/proc` и `/sys` для вложенных namespaces: нужен современному
  systemd внутри и Docker в контейнере. Для unprivileged безопасно; в privileged — дыра.
- `keyctl=1` — системный вызов keyctl (нужен Docker/runc в unprivileged-контейнере).
- `fuse=1`, `mount=nfs;cifs` — осторожно, расширяют поверхность атаки.

**Bind mount** — каталог хоста внутри контейнера (не бэкапится vzdump'ом!):
```bash
mkdir -p /mnt/bindmounts/shared
pct set 200 -mp0 /mnt/bindmounts/shared,mp=/shared
```text
В unprivileged файлы хоста с UID 1000 видны внутри как `nobody`. Варианты:
1. `chown -R 101000:101000 /mnt/bindmounts/shared` — хостовый UID «со сдвигом» = UID 1000 внутри.
2. Классический idmap: пробросить один UID 1:1, остальное — как обычно.
   ```ini
   # /etc/pve/lxc/200.conf
   lxc.idmap: u 0 100000 1000
   lxc.idmap: g 0 100000 1000
   lxc.idmap: u 1000 1000 1
   lxc.idmap: g 1000 1000 1
   lxc.idmap: u 1001 101001 64535
   lxc.idmap: g 1001 101001 64535
   ```
   и разрешить root'у отображать UID 1000: строка `root:1000:1` в `/etc/subuid` и `/etc/subgid`.
3. В свежих версиях Proxmox VE 9 у точек монтирования появился параметр `idmap=` —
   отображение прямо в `mpN`, без правки общих `lxc.idmap`.

**Docker в LXC.** Работает (unprivileged + `nesting=1,keyctl=1`), но Proxmox официально
рекомендует запускать Docker в VM: сильнее изоляция, живая миграция, меньше сюрпризов
с обновлениями ядра и overlayfs. С 9.1 Proxmox умеет делать LXC прямо из OCI-образов —
удобно для простых сервисов, но это не замена Docker/Kubernetes.

---

## 7. LXC, VM или Docker

```text
 Нужна не-Linux ОС, своё ядро/модуль, сильная изоляция, живая миграция?   ── да ──► VM
        │ нет
 Это приложение, которое поставляют образом и масштабируют (CI/CD, k8s)?  ── да ──► Docker/k8s (в VM)
        │ нет
 Долгоживущий Linux-сервис «как сервер», важны плотность и скорость?      ── да ──► LXC (unprivileged)
```text
| Сценарий | Выбор | Почему |
|----------|-------|--------|
| Внутренний DNS, NTP, reverse proxy, Zabbix-прокси | LXC | Лёгкий сервис, живёт годами, почти без накладных расходов |
| PostgreSQL в проде | VM (или LXC для небольших) | Изоляция I/O и ядра, тюнинг sysctl, живая миграция |
| Kubernetes-ноды | VM | Нужны модули ядра, свои sysctl, изоляция |
| Микросервисы | Docker/k8s | Образы, пайплайны, оркестрация |
| Windows | VM | Другое ядро |
| Много однотипных тестовых окружений | LXC или Incus | Секунды на создание, минимум RAM |
| Недоверенный код | VM | Общее ядро — общий риск |

---

## 8. Грабли

| Симптом | Причина | Что делать |
|---------|---------|-----------|
| В bind mount все файлы `nobody:nogroup` | UID хоста вне idmap unprivileged-контейнера | chown со сдвигом 100000, idmap, `idmap=` у mp |
| `mount -t nfs` внутри контейнера: permission denied | Unprivileged не монтирует NFS | Смонтировать на хосте, пробросить bind mount |
| Docker в LXC не стартует (overlay, keyctl, `/proc/sys`) | Нет `nesting`/`keyctl` | `--features nesting=1,keyctl=1` — или Docker в VM |
| systemd-службы в контейнере падают со странными ошибками | Новому systemd нужен nesting | `nesting=1` для unprivileged |
| `free -h` в контейнере показывает всю память хоста | Нет lxcfs | В Proxmox/Incus lxcfs есть; в голом LXC — пакет `lxcfs` |
| Контейнер не мигрирует «вживую» | У LXC нет live migration | `pct migrate --restart` (короткий простой) или VM |
| Восстановили бэкап CT — данных нет | Данные были в bind mount | Данные в volume mount point (`mp0: local-lvm:...`) или отдельный бэкап |
| `lxc list` пишет что-то про snap/LXD | `lxc` — CLI LXD, а не LXC | Утилиты LXC — `lxc-*`, Incus — `incus` |
| Контейнеры Incus без интернета после установки Docker | `FORWARD DROP` от Docker | Правила `DOCKER-USER` или разные хосты |
| Модуль ядра «не грузится» в контейнере | Ядро общее, модулей у контейнера нет | `modprobe` на хосте или VM |

---

## 💼 Как это в DevOps

- **Proxmox + LXC** — дешёвая «VM» для инфраструктурной мелочи: DNS, прокси, раннеры
  мониторинга, jump-host. Ansible работает с ними как с обычными серверами.
- **Unprivileged по умолчанию** — требование безопасности: на аудите privileged-контейнер
  без обоснования — замечание.
- **Docker и Kubernetes — в VM, а не в LXC** — так рекомендует Proxmox и так проще
  поддерживать: обновления ядра хоста не ломают overlayfs и cgroups внутри.
- **Incus** встречается у хостингов и в лабораториях; понимать связку «LXD → Incus» полезно,
  чтобы не удивляться на собесе вопросу «чем Incus отличается от LXD».
- Механизмы изоляции одинаковы у LXC и Docker — знания из блока Docker переносятся напрямую.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Проверить ядро для LXC | `lxc-checkconfig` |
| Создать LXC (root) | `lxc-create -n c1 -t download -- -d debian -r trixie -a amd64` |
| Старт / список / шелл | `lxc-start -n c1`, `lxc-ls -f`, `lxc-attach -n c1` |
| Диапазоны UID | `cat /etc/subuid /etc/subgid` |
| idmap в конфиге | `lxc.idmap = u 0 100000 65536` (и `g`) |
| Проверить отображение | `cat /proc/self/uid_map` внутри |
| Лимит памяти (cgroup v2) | `lxc.cgroup2.memory.max = 512M` |
| Incus: контейнер / VM | `incus launch images:debian/13 c1` / `... --vm` |
| Incus: лимиты, снапшот | `incus config set c1 limits.memory=1GiB`, `incus snapshot create c1 s0` |
| Proxmox: шаблоны | `pveam update; pveam available --section system` |
| Proxmox: создать CT | `pct create ID local:vztmpl/&lt;tpl&gt; --unprivileged 1 --features nesting=1 ...` |
| Войти / выполнить | `pct enter ID`, `pct exec ID -- cmd` |
| Bind mount | `pct set ID -mp0 /mnt/bindmounts/x,mp=/x` |
| Снапшот / откат | `pct snapshot ID s`, `pct rollback ID s` |
| Миграция CT | `pct migrate ID node --restart` |

---

## 🧠 Что запомнить

1. Системный контейнер = полная Linux-система с systemd без своего ядра; контейнер приложения = один процесс из образа.
2. Механизмы у LXC и Docker одни: namespaces, cgroups, capabilities, seccomp, AppArmor.
3. `lxc-*` — классический LXC, `lxc` — CLI LXD, `incus` — Incus (community-форк LXD с 2023, Apache 2.0).
4. Privileged: root в контейнере = root хоста. Unprivileged: root → UID 100000 через user namespace — выбор по умолчанию.
5. Диапазоны отображения — `/etc/subuid` и `/etc/subgid`, в конфиге — `lxc.idmap`.
6. Bind mount в unprivileged: файлы хоста видны как `nobody` — лечится сдвигом UID или idmap; bind mount'ы не бэкапятся.
7. В Proxmox CT по умолчанию unprivileged; `nesting=1` нужен systemd и Docker, `keyctl=1` — Docker.
8. У LXC нет живой миграции (только с перезапуском) и нет своих модулей ядра.
9. Incus управляет и контейнерами, и VM одним CLI; с Docker на одном хосте конфликтует по iptables.
10. LXC — для лёгких долгоживущих Linux-сервисов, VM — для изоляции и другого ядра, Docker — для поставки приложений.

➡️ Дальше: [06_virt_automation.md](/virtualization/06-virt-automation) · задачи: 05_lxc_containers_tasks.md


---

### Блок A. Теория


**A1.** Назови пять отличий системного контейнера от контейнера приложения.

<details><summary>Ответ</summary>

PID 1 — systemd против процесса приложения; много сервисов против одного; обслуживают
как сервер (apt, конфиги) против пересоздания из образа; данные в rootfs против volumes;
поставка шаблоном ОС против образа из Dockerfile; управление через SSH/Ansible против
registry и оркестратора.

</details>

**A2.** Какие механизмы ядра общие у LXC и Docker? Что тогда отличает их на практике?

<details><summary>Ответ</summary>

Namespaces, cgroups, capabilities, seccomp, AppArmor/SELinux, user namespaces.
Отличает модель: LXC даёт полноценную ОС и долгоживущий «сервер», Docker — упакованное
иммутабельное приложение с образами, слоями и экосистемой (registry, Compose, Kubernetes).

</details>

**A3.** Кто есть кто: LXC, LXD, Incus, `pct`? Что произошло с LXD в 2023 году?

<details><summary>Ответ</summary>

LXC — библиотека и утилиты `lxc-*`; LXD — демон Canonical поверх LXC с CLI `lxc`;
Incus — community-форк LXD в linuxcontainers.org; `pct` — управление LXC в Proxmox. В июле 2023
Canonical забрала LXD под себя, в августе появился Incus; в декабре 2023 LXD перелицензировали
в AGPLv3 с CLA, Incus остался на Apache 2.0.

</details>

**A4.** Чем опасен privileged-контейнер? Что сдерживает root такого контейнера?

<details><summary>Ответ</summary>

Root в privileged-контейнере — UID 0 хоста. Его сдерживают только урезанные
capabilities, seccomp, AppArmor и cgroups. Любая дыра в этих слоях или ядре (или неосторожный
bind mount/устройство) — и это root на хосте.

</details>

**A5.** ⭐ Как устроен unprivileged-контейнер? Что хранится в `/etc/subuid` и что означает
строка `lxc.idmap = u 0 100000 65536`?

<details><summary>Ответ</summary>

Контейнер запускается в user namespace: UID внутри отображаются на диапазон UID хоста.
`/etc/subuid` (`user:start:count`) — какие диапазоны пользователю разрешено отображать.
`u 0 100000 65536` — UID 0…65535 внутри соответствуют 100000…165535 на хосте (`g` — то же
для GID). Root контейнера на хосте — бесправный UID 100000.

</details>

**A6.** ⭐ Почему файлы из bind mount в unprivileged-контейнере видны как `nobody`? Три способа
это исправить.

<details><summary>Ответ</summary>

UID 1000 хоста не входит в отображаемый диапазон (100000–165535), поэтому внутри
ядро показывает «неотображённый» UID как `nobody` (65534). Способы: chown на хосте в UID
со сдвигом (101000 = UID 1000 внутри); свой `lxc.idmap`, пробрасывающий UID 1000 1:1
(+ `root:1000:1` в `/etc/subuid` и `/etc/subgid`); idmapped mount (`idmap=` у mp в свежих PVE 9,
`shift` в Incus).

</details>

**A7.** Какие ограничения у unprivileged-контейнеров?

<details><summary>Ответ</summary>

Нельзя монтировать большинство ФС (NFS, CIFS, блочные устройства), нет доступа к
устройствам без проброса, часть sysctl и возможностей ядра недоступна, bind mount'ы требуют
возни с UID, некоторое старое ПО, ожидающее «настоящего root», не работает.

</details>

**A8.** Зачем при запуске unprivileged LXC от пользователя нужен
`systemd-run --user --scope -p "Delegate=yes"`?

<details><summary>Ответ</summary>

В cgroup v2 обычный пользователь не может создавать группы где попало: ему нужна
делегированная ветка cgroup. `systemd-run --user --scope -p Delegate=yes` создаёт scope
в пользовательском менеджере systemd и делегирует его — LXC создаёт там cgroup контейнера.

</details>

**A9.** Что дают `nesting=1` и `keyctl=1` в Proxmox и чем они рискованны?

<details><summary>Ответ</summary>

`nesting=1` открывает контейнеру `/proc` и `/sys` для создания вложенных namespaces:
нужен современному systemd и Docker внутри. `keyctl=1` разрешает системный вызов keyctl
(runc/Docker). В unprivileged это безопасно; в privileged `nesting` открывает содержимое
procfs/sysfs хоста — дыра. `keyctl` может мешать изоляции ключей между контейнерами.

</details>

**A10.** Почему у LXC в Proxmox нет живой миграции?

<details><summary>Ответ</summary>

Живая миграция требует сохранить и восстановить состояние процессов (CRIU), что для
контейнеров с systemd и сетью ненадёжно, поэтому Proxmox мигрирует CT с перезапуском
(`--restart`): остановка, перенос, старт — короткий простой.

</details>

**A11.** Чем Incus отличается от классического LXC?

<details><summary>Ответ</summary>

Incus — демон с REST API и удобным CLI поверх LXC: образы с сервера, профили, сети,
пулы хранения, снапшоты, кластеры, проекты, Terraform-провайдер, и тем же CLI управляет VM
на QEMU. Классический LXC — низкоуровневые утилиты и конфиг-файлы.

</details>

**A12.** Почему Proxmox рекомендует запускать Docker в VM, а не в LXC?

<details><summary>Ответ</summary>

VM даёт сильную изоляцию (своё ядро), живую миграцию и независимость от ядра хоста:
обновление ядра узла не ломает overlayfs/cgroups внутри. Docker в LXC требует `nesting` и
`keyctl`, периодически ломается на обновлениях и хуже изолирован.

</details>

**A13.** Что делает lxcfs?

<details><summary>Ответ</summary>

lxcfs — FUSE-ФС, которая подменяет в контейнере `/proc/meminfo`, `/proc/cpuinfo`,
`/proc/uptime` и др., чтобы `free`, `top`, `uptime` показывали лимиты и время контейнера,
а не хоста.

</details>

**A14.** ⭐ Как выбрать между LXC, VM и Docker?

<details><summary>Ответ</summary>

Нужна другая ОС, своё ядро или модули, сильная изоляция, живая миграция → VM.
Приложение поставляется образом и оркестрируется → Docker/k8s (на VM). Лёгкий долгоживущий
Linux-сервис, важна плотность → unprivileged LXC.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  $ lxc list
```text
<details><summary>Ответ</summary>

⚠️ `lxc` — это CLI LXD. У пакета `lxc` утилиты с дефисом: `lxc-ls -f`, `lxc-create`.

</details>

```text:no-line-numbers
     Command 'lxc' not found, but can be installed with:
```text
```text:no-line-numbers
     sudo snap install lxd
```text
```text:no-line-numbers
     # «я ведь поставил пакет lxc!»
```text
```text:no-line-numbers
B2.  # публичный веб-сервис с загрузкой файлов от пользователей
```text
<details><summary>Ответ</summary>

⚠️ Privileged для недоверенной нагрузки из интернета — взлом приложения + уязвимость
= root на хосте. Unprivileged-контейнер, а лучше VM.

</details>

```text:no-line-numbers
     pct create 300 ... --unprivileged 0
```text
```text:no-line-numbers
B3.  # unprivileged CT 200, pct set 200 -mp0 /srv/share,mp=/share
```text
<details><summary>Ответ</summary>

⚠️ UID хоста вне диапазона idmap — файлы показываются как `65534`. chown со сдвигом,
idmap 1:1 или `idmap=` у точки монтирования.

</details>

```text:no-line-numbers
     root@ct1:~# ls -ln /share
```text
```text:no-line-numbers
     -rw-r--r-- 1 65534 65534  120 Sep 27 10:00 report.csv
```text
```text:no-line-numbers
B4.  root@ct1:~# mount -t nfs 10.10.10.30:/srv/data /mnt      # unprivileged CT
```text
<details><summary>Ответ</summary>

⚠️ Unprivileged-контейнер не может монтировать NFS. Смонтировать NFS на хосте и
пробросить bind mount, либо хранилище NFS в Proxmox и volume mount point.

</details>

```text:no-line-numbers
     mount.nfs: Operation not permitted
```text
```text:no-line-numbers
B5.  # unprivileged CT без features
```text
<details><summary>Ответ</summary>

⚠️ Без `nesting=1,keyctl=1` Docker не сможет создать namespaces/overlay и упадёт
с ошибками прав. Включить features (CT перезапустить) или, лучше, Docker в VM.

</details>

```text:no-line-numbers
     root@ct1:~# apt install -y docker.io && docker run hello-world
```text
```text:no-line-numbers
B6.  # /etc/pve/lxc/200.conf: пробросили UID 1000 1:1 (lxc.idmap: u 1000 1000 1 и т.д.)
```text
<details><summary>Ответ</summary>

⚠️ Root'у не разрешено отображать UID/GID 1000 — CT не стартует (ошибка newuidmap/idmap).
Добавить `root:1000:1` в `/etc/subuid` и `/etc/subgid`.

</details>

```text:no-line-numbers
     # /etc/subuid и /etc/subgid не меняли
```text
```text:no-line-numbers
     root@pve1:~# pct start 200
```text
```text:no-line-numbers
B7.  root@pve1:~# pct migrate 200 pve2      # CT 200 работает, опций нет
```text
<details><summary>Ответ</summary>

⚠️ Работающий CT не мигрирует «вживую» — нужна `--restart` (короткий простой) или
остановка CT перед миграцией.

</details>

```text:no-line-numbers
B8.  root@ct1:~# modprobe wireguard
```text
<details><summary>Ответ</summary>

✅ Так и должно быть: ядро общее, модули — только у хоста. `modprobe wireguard` на хосте
(модуль станет доступен контейнеру) или VM.

</details>

```text:no-line-numbers
     modprobe: FATAL: Module wireguard not found in directory /lib/modules/7.0.x-pve
```text
```text:no-line-numbers
B9.  # голый LXC на хосте без lxcfs, у контейнера lxc.cgroup2.memory.max = 512M
```text
<details><summary>Ответ</summary>

⚠️ Без lxcfs `free` читает `/proc/meminfo` хоста и покажет всю его память, хотя лимит

</details>

```text:no-line-numbers
     root@c1:~# free -h | head -2
```text
```text:no-line-numbers
B10.  «Чтобы разработчикам было удобно, добавим всех в группу incus-admin на общем сервере»
```text
<details><summary>Ответ</summary>

⚠️ `incus-admin` — фактически root на хосте (можно создать privileged-контейнер и
смонтировать `/`). Для разработчиков — группа `incus` с ограниченными проектами или отдельные VM.

</details>

```text:no-line-numbers
B11.  $ cat /etc/subuid
```text
<details><summary>Ответ</summary>

⚠️ Отображение не совпадает с разрешённым диапазоном (200000, а в конфиге 100000) —
контейнер не запустится. Числа в `lxc.idmap` берут из `/etc/subuid`/`/etc/subgid`.

</details>

```text:no-line-numbers
     nurik:200000:65536
```text
```text:no-line-numbers
     $ cat ~/.config/lxc/default.conf
```text
```text:no-line-numbers
     lxc.idmap = u 0 100000 65536
```text
```text:no-line-numbers
     lxc.idmap = g 0 100000 65536
```text
```text:no-line-numbers
B12.  # privileged CT для «легаси-приложения», добавили --features nesting=1 «на всякий случай»
```text
<details><summary>Ответ</summary>

⚠️ `nesting` в privileged-контейнере даёт доступ к procfs/sysfs хоста — серьёзная
дыра. В privileged не включать; для легаси — VM.

</details>


---

### Блок C. Практика


### C1. 🔑 Privileged LXC руками
В `lxc-lab`:
**1.** `apt install lxc`, `lxc-checkconfig`, создай и запусти privileged `c1` (Debian 13).

<details><summary>Ответ</summary>

`sudo lxc-info -n c1 -p -H` → PID; ссылки `/proc/&lt;PID&gt;/ns/*` отличаются от
`/proc/1/ns/*` (кроме user и time в privileged). Файл лимита — например,
`/sys/fs/cgroup/lxc.payload.c1/memory.max` → `268435456`. При превышении OOM-killer убьёт
процесс внутри контейнера (`dmesg` на хосте: `Memory cgroup out of memory`), хост не пострадает.

</details>

**2.** Найди PID init-процесса контейнера на хосте, сравни `ls -l /proc/&lt;PID&gt;/ns/` с `/proc/1/ns/`.

<details><summary>Ответ</summary>

`uid_map` внутри — `0 100000 65536`; `ps` на хосте показывает процессы от UID 100000;
файлы rootfs принадлежат 100000. `mount -t tmpfs` внутри обычно работает (tmpfs разрешён в user
namespace), `mount -t nfs` — нет: монтирование сетевых и блочных ФС требует привилегий хоста.

</details>

**3.** Поставь лимит памяти 256M в конфиг, перезапусти. Найди файл `memory.max` этого контейнера
   в `/sys/fs/cgroup/` и проверь значение. Запусти внутри `stress --vm 1 --vm-bytes 400M`
   (или `python3 -c "a='x'*400_000_000"`) — что произойдёт?

<details><summary>Ответ</summary>

Контейнер готов за секунды и занимает десятки МБ сверх процессов; VM — десятки секунд
и сотни МБ (своё ядро, память под гостя). `incus config set c1 limits.cpu=1 limits.memory=512MiB`,
`incus snapshot create c1 s0`, `incus snapshot restore c1 s0`.

</details>

### C2. 🔑 Unprivileged от обычного пользователя
**1.** Настрой `lxc-usernet`, `~/.config/lxc/default.conf` по своим `/etc/subuid` и `/etc/subgid`.

<details><summary>Ответ</summary>

`sudo lxc-info -n c1 -p -H` → PID; ссылки `/proc/&lt;PID&gt;/ns/*` отличаются от
`/proc/1/ns/*` (кроме user и time в privileged). Файл лимита — например,
`/sys/fs/cgroup/lxc.payload.c1/memory.max` → `268435456`. При превышении OOM-killer убьёт
процесс внутри контейнера (`dmesg` на хосте: `Memory cgroup out of memory`), хост не пострадает.

</details>

**2.** Создай и запусти `u1` через `systemd-run`.

<details><summary>Ответ</summary>

`uid_map` внутри — `0 100000 65536`; `ps` на хосте показывает процессы от UID 100000;
файлы rootfs принадлежат 100000. `mount -t tmpfs` внутри обычно работает (tmpfs разрешён в user
namespace), `mount -t nfs` — нет: монтирование сетевых и блочных ФС требует привилегий хоста.

</details>

**3.** Докажи отображение: `uid_map` внутри, владелец процессов и файлов rootfs на хосте.

<details><summary>Ответ</summary>

Контейнер готов за секунды и занимает десятки МБ сверх процессов; VM — десятки секунд
и сотни МБ (своё ядро, память под гостя). `incus config set c1 limits.cpu=1 limits.memory=512MiB`,
`incus snapshot create c1 s0`, `incus snapshot restore c1 s0`.

</details>

**4.** Попробуй внутри `mount -t tmpfs none /mnt` и `mount -t nfs ...`. Что работает, что нет и почему?

<details><summary>Ответ</summary>

`pct push 200 ./index.html /var/www/html/index.html`, `pct set 200 --memory 1024`,
`pct resize 200 rootfs +4G` — применяются на ходу, внутри сразу видны новые лимиты (lxcfs) и
размер ФС. `pct snapshot 200 before`, `pct rollback 200 before`.

</details>

### C3. Incus: контейнер и VM одним CLI
В `lxc-lab` с nested (VM создана с `host-passthrough`):
**1.** Установи Incus, `incus admin init --minimal`.

<details><summary>Ответ</summary>

`sudo lxc-info -n c1 -p -H` → PID; ссылки `/proc/&lt;PID&gt;/ns/*` отличаются от
`/proc/1/ns/*` (кроме user и time в privileged). Файл лимита — например,
`/sys/fs/cgroup/lxc.payload.c1/memory.max` → `268435456`. При превышении OOM-killer убьёт
процесс внутри контейнера (`dmesg` на хосте: `Memory cgroup out of memory`), хост не пострадает.

</details>

**2.** Запусти `c1` (контейнер) и `v1` (`--vm`) из Debian 13. Засеки время до готовности и сравни
   потребление памяти на хосте (`free -m` до и после, `incus info`).

<details><summary>Ответ</summary>

`uid_map` внутри — `0 100000 65536`; `ps` на хосте показывает процессы от UID 100000;
файлы rootfs принадлежат 100000. `mount -t tmpfs` внутри обычно работает (tmpfs разрешён в user
namespace), `mount -t nfs` — нет: монтирование сетевых и блочных ФС требует привилегий хоста.

</details>

**3.** Лимиты `limits.cpu=1 limits.memory=512MiB` на `c1`, снапшот, поломка, откат.

<details><summary>Ответ</summary>

Контейнер готов за секунды и занимает десятки МБ сверх процессов; VM — десятки секунд
и сотни МБ (своё ядро, память под гостя). `incus config set c1 limits.cpu=1 limits.memory=512MiB`,
`incus snapshot create c1 s0`, `incus snapshot restore c1 s0`.

</details>

### C4. 🔑 LXC в Proxmox
**1.** Скачай шаблон Debian 13 через `pveam`, создай unprivileged CT с `nesting=1` в `vmbr0`.

<details><summary>Ответ</summary>

`sudo lxc-info -n c1 -p -H` → PID; ссылки `/proc/&lt;PID&gt;/ns/*` отличаются от
`/proc/1/ns/*` (кроме user и time в privileged). Файл лимита — например,
`/sys/fs/cgroup/lxc.payload.c1/memory.max` → `268435456`. При превышении OOM-killer убьёт
процесс внутри контейнера (`dmesg` на хосте: `Memory cgroup out of memory`), хост не пострадает.

</details>

**2.** Через `pct exec` поставь `nginx`, через `pct push` положи свою `index.html`.

<details><summary>Ответ</summary>

`uid_map` внутри — `0 100000 65536`; `ps` на хосте показывает процессы от UID 100000;
файлы rootfs принадлежат 100000. `mount -t tmpfs` внутри обычно работает (tmpfs разрешён в user
namespace), `mount -t nfs` — нет: монтирование сетевых и блочных ФС требует привилегий хоста.

</details>

**3.** Увеличь память и диск на ходу (`pct set`, `pct resize`). Проверь внутри `free -h` и `df -h`.

<details><summary>Ответ</summary>

Контейнер готов за секунды и занимает десятки МБ сверх процессов; VM — десятки секунд
и сотни МБ (своё ядро, память под гостя). `incus config set c1 limits.cpu=1 limits.memory=512MiB`,
`incus snapshot create c1 s0`, `incus snapshot restore c1 s0`.

</details>

**4.** Снапшот → сломай конфиг nginx → `pct rollback`.

<details><summary>Ответ</summary>

`pct push 200 ./index.html /var/www/html/index.html`, `pct set 200 --memory 1024`,
`pct resize 200 rootfs +4G` — применяются на ходу, внутри сразу видны новые лимиты (lxcfs) и
размер ФС. `pct snapshot 200 before`, `pct rollback 200 before`.

</details>

### C5. 🔑 Bind mount и idmap
**1.** На `pve1`: `mkdir -p /mnt/bindmounts/share`, создай файл от UID 1000 (`useradd -u 1000 app`,
   `sudo -u app touch ...`).

<details><summary>Ответ</summary>

`sudo lxc-info -n c1 -p -H` → PID; ссылки `/proc/&lt;PID&gt;/ns/*` отличаются от
`/proc/1/ns/*` (кроме user и time в privileged). Файл лимита — например,
`/sys/fs/cgroup/lxc.payload.c1/memory.max` → `268435456`. При превышении OOM-killer убьёт
процесс внутри контейнера (`dmesg` на хосте: `Memory cgroup out of memory`), хост не пострадает.

</details>

**2.** Подключи к CT (`-mp0`), посмотри `ls -ln` внутри — `65534`?

<details><summary>Ответ</summary>

`uid_map` внутри — `0 100000 65536`; `ps` на хосте показывает процессы от UID 100000;
файлы rootfs принадлежат 100000. `mount -t tmpfs` внутри обычно работает (tmpfs разрешён в user
namespace), `mount -t nfs` — нет: монтирование сетевых и блочных ФС требует привилегий хоста.

</details>

**3.** Способ 1: `chown -R 101000:101000` на хосте — внутри файл принадлежит UID 1000. Что теперь
   видит сервис на хосте, работающий от `app`?

<details><summary>Ответ</summary>

Контейнер готов за секунды и занимает десятки МБ сверх процессов; VM — десятки секунд
и сотни МБ (своё ядро, память под гостя). `incus config set c1 limits.cpu=1 limits.memory=512MiB`,
`incus snapshot create c1 s0`, `incus snapshot restore c1 s0`.

</details>

**4.** Способ 2: верни владельца 1000, настрой idmap 1:1 для UID/GID 1000 (конфиг CT +
   `/etc/subuid`, `/etc/subgid`), перезапусти CT. Проверь с обеих сторон.

<details><summary>Ответ</summary>

`pct push 200 ./index.html /var/www/html/index.html`, `pct set 200 --memory 1024`,
`pct resize 200 rootfs +4G` — применяются на ходу, внутри сразу видны новые лимиты (lxcfs) и
размер ФС. `pct snapshot 200 before`, `pct rollback 200 before`.

</details>

### C6. Docker в LXC против Docker в VM
**1.** В unprivileged CT с `nesting=1,keyctl=1` поставь Docker и запусти `nginx`.

<details><summary>Ответ</summary>

`sudo lxc-info -n c1 -p -H` → PID; ссылки `/proc/&lt;PID&gt;/ns/*` отличаются от
`/proc/1/ns/*` (кроме user и time в privileged). Файл лимита — например,
`/sys/fs/cgroup/lxc.payload.c1/memory.max` → `268435456`. При превышении OOM-killer убьёт
процесс внутри контейнера (`dmesg` на хосте: `Memory cgroup out of memory`), хост не пострадает.

</details>

**2.** Выпиши, какие features понадобились и что в `pct config` поменялось.

<details><summary>Ответ</summary>

`uid_map` внутри — `0 100000 65536`; `ps` на хосте показывает процессы от UID 100000;
файлы rootfs принадлежат 100000. `mount -t tmpfs` внутри обычно работает (tmpfs разрешён в user
namespace), `mount -t nfs` — нет: монтирование сетевых и блочных ФС требует привилегий хоста.

</details>

**3.** Сравни с VM из шаблона 9000: что проще обновлять, что можно мигрировать вживую,
   где сильнее изоляция?

<details><summary>Ответ</summary>

Контейнер готов за секунды и занимает десятки МБ сверх процессов; VM — десятки секунд
и сотни МБ (своё ядро, память под гостя). `incus config set c1 limits.cpu=1 limits.memory=512MiB`,
`incus snapshot create c1 s0`, `incus snapshot restore c1 s0`.

</details>

### C7. Выбери платформу
Для каждого — LXC, VM или Docker/k8s и одна фраза «почему»: Bind9/Unbound; GitLab (omnibus);
Prometheus + Grafana для команды; нода Kubernetes; WireGuard-шлюз; тестовые окружения для
**50.** студентов; 1С-сервер на Windows; Redis для кэша сессий в k8s-приложении.
---

### Блок D. Инциденты


**D1.** После обновления ядра на узле Proxmox Docker внутри нескольких LXC перестал стартовать
контейнеры (ошибки overlayfs/cgroup). В VM с Docker всё в порядке. Почему так и что делать
в долгую?

<details><summary>Ответ</summary>

Docker в LXC зависит от ядра хоста и его поведения (overlayfs, cgroup, AppArmor) —
обновление ядра узла меняет всё сразу во всех CT. В VM у Docker своё ядро. В долгую —
перенести Docker-нагрузки в VM; до переноса — откатить/закрепить ядро
(`proxmox-boot-tool kernel pin`) и тестировать обновления на одном узле.

</details>

**D2.** Privileged-контейнер с веб-приложением взломали (загрузили веб-шелл). Чем это грозит
хосту и что делать?

<details><summary>Ответ</summary>

Root в privileged-контейнере — root хоста при любой дыре в capabilities/seccomp/AppArmor
или ядре: доступ ко всем CT и VM узла. Действия: изолировать контейнер (отключить сеть),
снять форензику (снапшот/бэкап для анализа), проверить хост и соседей, пересобрать сервис
в unprivileged CT или VM, обновить приложение, закрыть уязвимость, постмортем.

</details>

**D3.** Голый LXC-хост: один контейнер съел всю память, хост ушёл в своп, пострадали все.
Что забыли и как исправить?

<details><summary>Ответ</summary>

Не заданы лимиты cgroup (`lxc.cgroup2.memory.max`, CPU, PIDs). Задать лимиты каждому
контейнеру, мониторить память хоста; в Proxmox/Incus лимиты задаются при создании
(`--memory`, `limits.memory`).

</details>

**D4.** Чтобы CT видел файлы, сделали `chown -R 101000:101000 /srv/share`. Теперь сломался
сервис на самом хосте, работающий от UID 1000 и пишущий туда же. Как сделать, чтобы работало
с обеих сторон?

<details><summary>Ответ</summary>

Вернуть владельца UID 1000 и сделать idmap 1:1 для UID/GID 1000 в конфиге CT
(+ `root:1000:1` в subuid/subgid) или idmapped mount (`idmap=` у mp). Тогда UID 1000 один и тот
же с обеих сторон.

</details>

**D5.** На сервере с Incus поставили Docker для CI — у всех контейнеров Incus пропал интернет.
Диагностика и решение.

<details><summary>Ответ</summary>

`sudo iptables -S FORWARD` → `-P FORWARD DROP` от Docker; трафик моста `incusbr0`
режется. Решение: `iptables -I DOCKER-USER -i incusbr0 -j ACCEPT` и
`iptables -I DOCKER-USER -o incusbr0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT`
(с сохранением), или разнести Incus и Docker по разным хостам/VM.

</details>

**D6.** Пользователь не может создать unprivileged-контейнер:
`newuidmap: uid range [0-65536) -> [100000-165536) not allowed`. Что проверить?

<details><summary>Ответ</summary>

Есть ли строка пользователя в `/etc/subuid` и `/etc/subgid` и совпадает ли диапазон
с `lxc.idmap`; установлен ли `uidmap` (newuidmap/newgidmap с setuid); `/etc/lxc/lxc-usernet`
для сети; запуск через `systemd-run --user --scope -p Delegate=yes`.

</details>

**D7.** Команда просит: «дайте LXC-контейнер под Kubernetes-ноду и чтобы там грузился модуль
`br_netfilter`». Что ответишь?

<details><summary>Ответ</summary>

Модули грузятся только в ядро хоста — это затронет все контейнеры узла; Kubernetes
в LXC — хрупкая схема (sysctl, cgroups, AppArmor, overlay). Ответ: дадим VM из шаблона
(лучше несколько для кластера) — там свои модули и sysctl.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Чем LXC отличается от Docker?

<details><summary>Ответ</summary>

Механизмы одни (namespaces, cgroups), разная модель: LXC — системный контейнер с init и
   полной ОС, живёт как сервер; Docker — контейнер приложения из образа, один процесс,
   пересоздаётся при обновлении.

</details>

**2.** Что такое privileged и unprivileged контейнеры?

<details><summary>Ответ</summary>

Privileged — root внутри = root хоста, сдерживают только capabilities/seccomp/AppArmor.
   Unprivileged — через user namespace root внутри отображается на бесправный UID хоста
   (100000+). Выбор по умолчанию — unprivileged.

</details>

**3.** Что такое user namespace и idmap?

<details><summary>Ответ</summary>

User namespace даёт процессу свой набор UID/GID; idmap — таблица соответствия UID внутри
   и снаружи (`lxc.idmap = u 0 100000 65536`), разрешённые диапазоны — в `/etc/subuid`/`subgid`.

</details>

**4.** Чем Incus отличается от LXD?

<details><summary>Ответ</summary>

Incus — community-форк LXD (2023) от бывших авторов в linuxcontainers.org под Apache 2.0;
   LXD развивает Canonical (AGPLv3 + CLA). Функционально близки, пути расходятся; образы
   linuxcontainers.org — для Incus.

</details>

**5.** Когда в Proxmox выбирать LXC, а когда VM?

<details><summary>Ответ</summary>

LXC — лёгкие Linux-сервисы (DNS, прокси, мониторинг), плотность и скорость. VM — другая ОС,
   модули ядра, Docker/k8s, сильная изоляция, живая миграция, недоверенные нагрузки.

</details>

**6.** Можно ли запустить Docker в LXC? Что для этого нужно?

<details><summary>Ответ</summary>

Можно: unprivileged CT с `nesting=1` и `keyctl=1`. Но Proxmox рекомендует Docker в VM —
   изоляция, миграция, устойчивость к обновлениям ядра.

</details>

**7.** Можно ли живьём мигрировать контейнер?

<details><summary>Ответ</summary>

VM — да. Контейнеры — в Proxmox только с перезапуском; технически есть CRIU, но для
   системных контейнеров это ненадёжно.

</details>

**8.** За счёт чего изолирован LXC-контейнер?

<details><summary>Ответ</summary>

Namespaces (что видно), cgroups (сколько ресурсов), user namespace (кто ты на хосте),
   capabilities, seccomp, AppArmor (что можно), lxcfs (что видно в `/proc`).

</details>

**9.** Почему в контейнере с bind mount бывают проблемы с правами?

<details><summary>Ответ</summary>

UID файлов хоста не входят в диапазон отображения unprivileged-контейнера — видны как
   `nobody`, запись запрещена. Лечится сдвигом UID, idmap или idmapped mounts.

</details>

**10.** Как ограничить ресурсы контейнера?

<details><summary>Ответ</summary>

cgroups: в LXC `lxc.cgroup2.memory.max`, `lxc.cgroup2.cpu.max`, `pids.max`; в Proxmox —
    `--memory`, `--cores`, `--cpulimit`; в Incus — `limits.memory`, `limits.cpu`.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Объясняю разницу системного контейнера и контейнера приложения
- [ ] Знаю, кто есть кто: LXC, LXD, Incus, `pct` — и историю 2023 года
- [ ] Поднимаю privileged LXC руками, нахожу его процессы, namespaces и cgroup на хосте
- [ ] ⭐ Поднимаю unprivileged LXC от пользователя и объясняю `/etc/subuid` и `lxc.idmap`
- [ ] Запускаю контейнер и VM через Incus, ставлю лимиты, делаю снапшоты
- [ ] ⭐ Создаю и обслуживаю CT в Proxmox (`pct`), знаю про `nesting` и `keyctl`
- [ ] ⭐ Решаю проблему прав в bind mount сдвигом UID и idmap
- [ ] Выбираю между LXC, VM и Docker и обосновываю
