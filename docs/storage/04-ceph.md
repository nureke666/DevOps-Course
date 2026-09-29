---
title: "04. Ceph: распределённое хранилище"
description: "Блок → Хранилища и stateful → тема 04. Опирается на 01storagebasics.md"
---

# 04. Ceph: распределённое хранилище

> Блок → Хранилища и stateful → тема 04. Опирается на [01_storage_basics.md](/storage/01-storage-basics)
> (репликация vs erasure coding, durability, консистентность), [02_lvm_filesystems.md](/storage/02-lvm-filesystems)
> (OSD создаются поверх LVM) и [03_nfs_minio.md](/storage/03-nfs-minio) (S3 и erasure coding в MinIO).
> Ceph в Kubernetes через Rook — в [05_k8s_stateful.md](/storage/05-k8s-stateful).
>
> **После темы ты умеешь:** объяснить, зачем Ceph и когда он не нужен; рассказать архитектуру
> (MON, MGR, OSD, MDS, RGW, RADOS, пулы, PG, CRUSH); выбрать `size/min_size` или EC-пул;
> поднять кластер из трёх нод через cephadm; читать `ceph -s` и `ceph health detail`, понимать
> состояния PG; выдать блочный том (RBD), файловую систему (CephFS) и S3 (RGW); знать
> эксплуатационные ограничения: 3+ ноды, сеть, recovery, заполнение не выше ~80%.

---

## 🗺️ Карта темы

```text
  КЛИЕНТЫ         ВМ/k8s-поды: RBD         поды/серверы: CephFS        приложения: S3
                        │ librbd/krbd              │ MDS (метаданные)       │ RGW (HTTP)
                        └──────────────┬───────────┴─────────────┬──────────┘
                                       ▼                         ▼
                               librados — клиент сам считает, где лежат данные
                                       │   объект → hash → PG → CRUSH → [osd.3, osd.7, osd.1]
  ┌────────────────────────────── RADOS (надёжное объектное ядро) ───────────────────────────┐
  │  MON ×3 (кворум, карты кластера)   MGR ×2 (метрики, dashboard, orchestrator)             │
  │  OSD — по одному на диск: хранит объекты (BlueStore), реплицирует, лечит, скрабит        │
  │  пул rbd (size 3)    пул cephfs_data (size 3)    пул default.rgw.buckets.data (EC 4+2)   │
  └──────────────────────────────────────────────────────────────────────────────────────────┘
        ceph1 (vdb)                  ceph2 (vdb)                  ceph3 (vdb)
```text
---

## 1. Зачем Ceph и когда он не нужен

**Ceph** — программно-определяемое хранилище: из обычных серверов с дисками получается
**одна** система, которая отдаёт блочные тома, файловую систему и S3, сама реплицирует данные
и сама восстанавливается после отказа диска или сервера.

| | Ceph | NAS/SAN (аппаратная СХД) | MinIO/SeaweedFS | Локальные диски + репликация в приложении |
|---|------|--------------------------|-----------------|--------------------------------------------|
| Что отдаёт | Блок + файл + объект | Блок (SAN) или файл (NAS) | Объект (S3) | То, что умеет приложение |
| Масштаб | Горизонтально, до петабайт | Упирается в контроллеры | Горизонтально | По приложению |
| Единая точка отказа | Нет (при 3+ нодах) | Контроллер/шасси (обычно дублированы) | Нет (distributed) | Нет |
| Сложность эксплуатации | ⚠️ Высокая | Низкая (вендор) | Средняя | Низкая |
| Где встречается | OpenStack, Proxmox, on-prem k8s (Rook), S3 в своих ЦОД | Банки, VMware | Бэкапы, артефакты | БД-кластеры, Kafka |

**Когда Ceph — хороший выбор:** свой ЦОД, десятки терабайт и больше, нужны сразу RWO-тома
для кубера/ВМ, RWX и S3, есть 3+ сервера с 10 Гбит/с сетью и люди, готовые его понимать.
**Когда нет:** один-два сервера, 1 Гбит/с сеть, «надо просто тома для пары баз» (local PV +
репликация БД проще и быстрее), нет времени учить. Ceph прощает мало ошибок в железе и сети.

---

## 2. Демоны кластера

| Демон | Сколько | Что делает | Ресурсы (прод) |
|-------|---------|------------|----------------|
| **MON** (monitor) | 3 или 5 (нечётно) | Хранит карты кластера (mon, osd, pg, crush), держит кворум по Paxos, выдаёт ключи cephx | ~5 ГБ RAM (растёт с кластером), быстрый диск под `/var/lib/ceph` |
| **MGR** (manager) | 2 (active + standby) | Метрики, модули: dashboard, prometheus, orchestrator (cephadm), balancer, pg_autoscaler | как MON |
| **OSD** (object storage daemon) | По одному на диск | Хранит объекты на своём диске, реплицирует, восстанавливает, скрабит, сообщает о соседях | ~4 ГБ RAM на OSD, 1–4 потока CPU |
| **MDS** (metadata server) | 1 active + standby на ФС | Метаданные CephFS (дерево каталогов, права). Для RBD и RGW не нужен | RAM под кэш метаданных |
| **RGW** (RADOS gateway) | 2+ за балансировщиком | S3/Swift-API поверх RADOS | CPU, сеть |

- Кворум MON — большинство: из 3 выдерживает потерю 1, из 5 — потерю 2. Без кворума кластер
  **стоит** (никто не знает актуальную карту), хотя данные на OSD целы.
- Данные **не проходят** через MON: клиент получает карты один раз и дальше ходит к OSD напрямую.

---

## 3. RADOS, пулы, PG и CRUSH

```text
 объект "rbd_data.1a2b.0000000000000017" (4 МиБ кусок RBD-тома)
      │  hash(имя) mod pg_num
      ▼
 PG 2.1f  (placement group — «корзина» объектов внутри пула 2)
      │  CRUSH(PG, карта кластера, правило пула)
      ▼
 acting set [osd.3, osd.7, osd.1]   ← первый — primary: принимает запись, рассылает репликам
```text
| Понятие | Смысл |
|---------|-------|
| **Пул** | Логический раздел: свой `size`, правило CRUSH, число PG, приложение (rbd/cephfs/rgw) |
| **PG** | Группа объектов, которая целиком живёт на одном наборе OSD. Кластер следит за PG, а не за миллиардами объектов |
| **CRUSH** | Детерминированный алгоритм: по карте и правилу вычисляет, на каких OSD лежит PG. Нет центральной таблицы «где что» |
| **Failure domain** | Уровень иерархии, по которому разносятся реплики: `host` (по умолчанию), `rack`, `datacenter` |
| **Device class** | `hdd` / `ssd` / `nvme` — назначается автоматически; правило может брать только SSD |

Иерархия CRUSH и правило под быстрые диски:
```text
root default
├── host ceph1 ── osd.0 (ssd)
├── host ceph2 ── osd.1 (ssd)
└── host ceph3 ── osd.2 (ssd)
```text
```bash
ceph osd tree                                              # иерархия и статус OSD
ceph osd crush rule create-replicated fast default host ssd   # реплики на разных host, только ssd
ceph osd pool set rbd crush_rule fast                      # пул переедет (пойдёт перемещение данных)
```text
**Сколько PG:** считать руками больше не нужно — `pg_autoscaler` (включён по умолчанию)
держит порядка 100 PG на OSD и степень двойки на пул. Смотреть: `ceph osd pool autoscale-status`.
Слишком мало PG — неравномерное заполнение OSD; слишком много — лишняя нагрузка на память и peering.

> ⭐ Ключевая идея Ceph: клиент **сам** вычисляет расположение данных по CRUSH. Нет шлюза и
> нет базы метаданных на пути блочного I/O — поэтому Ceph масштабируется горизонтально.

---

## 4. Репликация (`size`/`min_size`) и EC-пулы

Путь записи в реплицируемый пул: клиент → primary OSD → параллельно на остальные OSD acting
set → **подтверждение клиенту после записи на все реплики**. Поэтому RADOS строго консистентен.

| Параметр | По умолчанию | Смысл |
|----------|--------------|-------|
| `size` | 3 | Сколько копий хранить |
| `min_size` | 2 | Минимум живых копий, при котором PG **принимает I/O**. Меньше — PG становится inactive, запись и чтение ждут |

```bash
ceph osd pool get rbd size; ceph osd pool get rbd min_size
ceph osd pool set rbd size 3
```text
Почему `min_size 2`, а не 1: при `min_size 1` запись принимается на единственную копию; умри
этот диск до восстановления — потеряны данные, которые уже подтвердили клиенту. `size 2 / min_size 1`
— классический путь к потере данных; в проде только `3/2`.

**Erasure coding** (теория — в [01_storage_basics.md](/storage/01-storage-basics)):
```bash
ceph osd erasure-code-profile set ec42 k=4 m=2 crush-failure-domain=host
ceph osd pool create ecpool erasure ec42
ceph osd pool set ecpool allow_ec_overwrites true          # нужно для RBD и CephFS
rbd create rbd/vol-ec --size 10G --data-pool ecpool        # метаданные — в реплицируемом rbd
```text
| | Replicated 3× | EC 4+2 | EC 2+1 |
|---|---------------|--------|--------|
| Полезная ёмкость | 33% | 67% | 67% |
| Переживает отказов | 2 | 2 | 1 |
| Минимум failure domain (host) | 3 | 6 | 3 |
| `min_size` по умолчанию | 2 | k+1 = 5 | k+1 = 3 ⚠️ |
| Мелкая случайная запись | ⭐ быстро | медленно (чтение-пересчёт-запись) | медленно |
| Где уместен | RBD под БД и ВМ, метаданные | RGW-данные, архив, крупные файлы | маленькие кластеры — осторожно |

> ⚠️ EC 2+1 на трёх хостах: `min_size = 3`, то есть потеря одного хоста **останавливает I/O**
> в пуле. «Экономия места» на маленьком кластере оборачивается простоем.

---

## 5. BlueStore — как OSD хранит данные

- OSD пишет **прямо на сырое устройство**, без файловой системы (`ceph-volume` создаёт на
  диске LVM-том — в `lsblk` он виден как `ceph--&lt;uuid&gt;-osd--block--&lt;uuid&gt;`).
- Метаданные объектов — в RocksDB на мини-ФС BlueFS. RocksDB (**DB**) и журнал (**WAL**) можно
  вынести на NVMe, а данные держать на HDD — сильно ускоряет HDD-кластеры.
- Контрольные суммы (crc32c) на все данные: порча обнаруживается при чтении и при **scrub**.
- **Scrub** (сверка метаданных реплик) — ежедневно, **deep-scrub** (чтение и сверка всех данных) —
  раз в неделю по умолчанию. Нашёл расхождение — PG `inconsistent`, лечится `ceph pg repair`.
- Сжатие на уровне пула (`compression_mode`), кэш в RAM — по `osd_memory_target` (4 ГиБ по
  умолчанию; ниже 2 ГБ не рекомендуется, cephadm подстраивает сам — autotune).

> Ceph хочет видеть **сами диски**: аппаратный RAID под OSD прячет ошибки дисков и ломает
> логику восстановления. Контроллер — в режиме HBA/JBOD. SSD — с защитой от потери питания (PLP).

---

## 6. Версии на сентябрь 2026

| Релиз | Версия | Выпущен | Статус |
|-------|--------|---------|--------|
| **Tentacle** | 20.2.4 | 2025-11-18 (20.2.0) | ⭐ Актуальный стабильный, EOL ~2027-06 |
| Squid | 19.2.6 | 2024-09-26 | Поддерживается до 2026-10-31 — планируй апгрейд |
| Reef | 18.2.8 | 2023 | Архивирован 2026-03-20 |
| Umbrella | 21.1.x | — | Release candidate, в прод рано |

Нумерация: `X.0.Z` — разработка, `X.1.Z` — release candidate, `X.2.Z` — стабильный. Мажор
выходит примерно раз в год и поддерживается около двух лет. Апгрейд поддерживается с двух
предыдущих релизов (на Tentacle — с Reef и Squid) и делается строго по release notes.

---

## 7. Развёртывание: cephadm

cephadm ставит все демоны **контейнерами** (Podman или Docker) под systemd и управляет ими
через orchestrator: описываешь, сколько чего и где, — он приводит кластер к описанию.

Требования к хостам: Python 3, systemd, Podman (3.x+ для Quincy и новее) или Docker, синхронное
время (chrony), `lvm2`. Стенд — `ceph-lab` из [00_INDEX.md](/storage/): ceph1..3 (192.168.61.11–13),
по 4 ГБ RAM и сырому диску `vdb` на 20G.

```bash
# на всех нодах
sudo apt-get install -y podman lvm2 chrony

# на ceph1 (root): cephadm нужной версии — одиночный исполняемый файл
CEPH_RELEASE=20.2.4
curl --silent --remote-name --location https://download.ceph.com/rpm-${CEPH_RELEASE}/el9/noarch/cephadm
install -m 0755 cephadm /usr/local/sbin/cephadm      # (apt install cephadm даст версию дистрибутива)

cephadm bootstrap --mon-ip 192.168.61.11 --skip-monitoring-stack
#   создаст MON + MGR на ceph1, ключи в /etc/ceph, SSH-ключ /etc/ceph/ceph.pub,
#   dashboard https://192.168.61.11:8443 — логин и пароль печатаются в конце (сохрани!)
#   --skip-monitoring-stack: без Prometheus/Grafana/Alertmanager — экономим RAM стенда
cephadm shell -- ceph -s                             # CLI внутри контейнера с конфигом кластера
```text
```bash
# добавить ноды: ключ cephadm → authorized_keys root на новых хостах
ssh-copy-id -f -i /etc/ceph/ceph.pub root@ceph2      # на Vagrant-VM пароля root нет — ключ
ssh-copy-id -f -i /etc/ceph/ceph.pub root@ceph3      # раздают через vagrant ssh (лаба 3)

cephadm shell                                        # дальше — внутри
ceph orch host add ceph2 192.168.61.12
ceph orch host add ceph3 192.168.61.13 --labels _admin   # _admin: копия ceph.conf и ключа в /etc/ceph
ceph orch host ls

# OSD
ceph orch device ls --refresh                        # AVAILABLE=Yes только у «чистых» дисков
ceph orch apply osd --all-available-devices          # декларативно: все подходящие диски → OSD
ceph orch daemon add osd ceph2:/dev/vdb              # …или точечно
ceph orch ps; ceph orch ls                           # демоны и сервисы
```text
Диск считается **available**, если на нём нет разделов, ФС, LVM, он не смонтирован и больше 5 ГБ.
`--all-available-devices` — это сервис `osd.all-available-devices`: он **продолжает** забирать
любой новый подходящий диск (в том числе после `zap`). Остановить: `ceph orch apply osd
--all-available-devices --unmanaged=true`.

Размещение сервисов — тоже декларативно:
```bash
ceph orch apply mon --placement="3 ceph1 ceph2 ceph3"
ceph orch apply mgr --placement="2"
ceph orch upgrade start --ceph-version 20.2.4       # rolling-апгрейд всех демонов
ceph orch upgrade status
```text
> ⚠️ `ceph orch device zap HOST /dev/vdX --force` и `ceph orch osd rm … --zap` **стирают диск**.
> Только на доп. дисках учебных VM.

---

## 8. Здоровье кластера

```text
$ ceph -s
  cluster:
    id:     4f1c…
    health: HEALTH_WARN
            1 osds down
            Degraded data redundancy: 120/360 objects degraded (33.333%), 33 pgs degraded, 33 pgs undersized
  services:
    mon: 3 daemons, quorum ceph1,ceph2,ceph3 (age 2h)          ← кворум есть
    mgr: ceph1.xkqzvb(active, since 2h), standbys: ceph2.mtwpla
    osd: 3 osds: 2 up (since 40s), 3 in (since 1h)             ← один down, но ещё in
  data:
    pools:   2 pools, 33 pgs
    objects: 120 objects, 450 MiB
    usage:   1.4 GiB used, 59 GiB / 60 GiB avail
    pgs:     120/360 objects degraded (33.333%)
             33 active+undersized+degraded                      ← I/O идёт, избыточность снижена
```text
`HEALTH_OK` → `HEALTH_WARN` (проблема, данные доступны) → `HEALTH_ERR` (нужна реакция немедленно).
`ceph health detail` расшифровывает каждую проверку с кодом:

| Код | Что значит | Что делать |
|-----|-----------|------------|
| `OSD_DOWN` | OSD не отвечает соседям | `ceph osd tree`, `ceph orch ps`, логи демона, диск в `dmesg` |
| `PG_DEGRADED` | Копий меньше `size` (degraded / undersized) | Ждать recovery или вернуть OSD; при 3 хостах и `size 3` — вернуть хост |
| `PG_AVAILABILITY` | PG inactive / peering / down — **I/O стоит** | Вернуть OSD, чтобы набрать `min_size`; это авария |
| `OSD_NEARFULL` / `OSD_BACKFILLFULL` / `OSD_FULL` | OSD заполнен на 85% / 90% / 95% | Добавить OSD, удалить данные, `ceph osd df` — перекос? балансировщик |
| `MON_CLOCK_SKEW` | Часы MON расходятся больше 0,05 с | Чинить chrony/NTP на всех нодах |
| `RECENT_CRASH` | Демон падал за 2 недели | `ceph crash ls`, `ceph crash info ID`, после разбора `ceph crash archive-all` |
| `OSD_SCRUB_ERRORS` / `PG_DAMAGED` | Scrub нашёл расхождение реплик | `rados list-inconsistent-obj PGID`, проверить диск, `ceph pg repair PGID` |
| `POOL_NO_REDUNDANCY` | Пул с `size 1` | Поднять `size` (на стенде — осознанно заглушить) |
| `MON_DISK_LOW` | Мало места под базу MON | Освободить `/var/lib/ceph` |

Состояния PG, которые надо узнавать с первого взгляда:

| Состояние | Смысл | Опасно? |
|-----------|-------|---------|
| `active+clean` | Всё хорошо | — |
| `undersized` | В acting set меньше OSD, чем `size` | Да — избыточность снижена |
| `degraded` | Часть объектов имеет меньше копий, чем нужно | Да, но I/O идёт |
| `recovering` / `backfilling` | Досоздаются копии / переносятся PG целиком | Нагрузка на диски и сеть |
| `remapped` | PG временно живёт не там, где велит CRUSH | Нормально при изменениях |
| `peering` | OSD договариваются о состоянии PG | Кратко — норма; долго — проблема |
| `inactive` / `down` / `incomplete` | PG не обслуживает I/O / нет нужных OSD / нет полной истории | 🔴 Авария |
| `inconsistent` | Scrub нашёл расхождение | Разобраться с диском, `pg repair` |

```bash
ceph -s; ceph -w                   # статус и поток событий
ceph health detail
ceph osd tree; ceph osd df tree    # статус и заполнение OSD по хостам
ceph df                            # RAW и по пулам (STORED vs USED ≈ ×3)
ceph pg stat; ceph pg dump_stuck   # застрявшие PG
ceph osd perf                      # commit/apply latency по OSD — ищем медленный диск
```text
---

## 9. RBD — блочные тома

```bash
ceph osd pool create rbd && rbd pool init rbd
rbd create rbd/vol1 --size 2G
rbd ls rbd; rbd info rbd/vol1                # features, размер объекта 4 МиБ
rbd resize rbd/vol1 --size 4G                # растёт онлайн (ФС сверху — resize2fs/xfs_growfs)
rbd snap create rbd/vol1@before-upgrade      # снапшот (и основа клонов)
rbd snap ls rbd/vol1; rbd snap rollback rbd/vol1@before-upgrade

# клиент ядра (krbd): нужен ceph-common, ceph.conf и ключ
sudo rbd map rbd/vol1 && rbd showmapped      # → /dev/rbd0
sudo mkfs.xfs /dev/rbd0 && sudo mount /dev/rbd0 /mnt/rbd
sudo umount /mnt/rbd && sudo rbd unmap /dev/rbd0
```text
Кто пользуется RBD: CSI-драйвер в Kubernetes (Rook, ceph-csi), Proxmox, OpenStack Cinder,
libvirt (librbd напрямую, без `/dev/rbd`). Снапшоты RBD живут **в том же кластере** — это точка
отката, а не бэкап; вывезти можно `rbd export` / `rbd export-diff` или Velero data mover (тема 07).

---

## 10. CephFS — общая файловая система

```bash
ceph fs volume create cephfs               # пулы cephfs.cephfs.meta/.data + MDS через orchestrator
ceph fs status cephfs; ceph mds stat       # 1 active, standby
# монтирование ядром (ceph-common на клиенте; секрет mount.ceph возьмёт из keyring в /etc/ceph)
sudo mkdir -p /mnt/cephfs
sudo mount -t ceph 192.168.61.11:6789:/ /mnt/cephfs -o name=admin
ceph fs subvolume create cephfs team-a --size 10737418240   # так CSI выдаёт RWX-тома с квотой
```text
- Настоящая POSIX-ФС с одновременной записью с многих клиентов — основа **RWX** в k8s (`rook-cephfs`).
- MDS — узкое место метаданных: миллионы мелких файлов и `ls` по огромным каталогам его грузят;
  масштабируют несколькими active MDS (`max_mds`) и standby.
- Старые ядра хуже соблюдают квоты — для CSI рекомендуют ядро 4.17+.

---

## 11. RGW — S3 поверх Ceph

```bash
ceph orch apply rgw myrgw --placement="1 ceph1" --port=8080
radosgw-admin user create --uid=demo --display-name="Demo"   # выведет access_key и secret_key
# дальше любой S3-клиент: mc alias set ceph http://192.168.61.11:8080 &lt;access&gt; &lt;secret&gt;
```text
- Данные бакетов — обычно в EC-пуле (экономия места), индексы бакетов — в реплицируемом на SSD.
- Multisite — асинхронная репликация зон между кластерами (DR на вторую площадку).
- Для S3 без блочных томов Ceph избыточен: см. альтернативы в [03_nfs_minio.md](/storage/03-nfs-minio).

---

## 12. Эксплуатационные реалии

**Минимум три ноды.** Три MON для кворума и три failure domain для `size 3`. Но есть нюанс:

```text
 3 хоста, size 3, failure domain host — умер один хост:
   PG: active+undersized+degraded   → I/O идёт (2 ≥ min_size 2)
   recovery НЕКУДА: четвёртого хоста нет, третья копия не появится, пока хост не вернётся
 4+ хоста — умер один:
   через mon_osd_down_out_interval (600 с) OSD помечаются out → PG досоздаются на оставшихся
   ⇒ оставшимся хостам нужно СВОБОДНОЕ место под данные упавшего
```text
**Заполнение.** Пороги: `nearfull` 85%, `backfillfull` 90% (дальше recovery не пишет на OSD),
`full` 95% (запись в кластер **останавливается**). Если при потере хоста его данные переедут
на остальные, заполнение вырастет примерно в `N/(N−1)` раз: при 5 хостах 75% станет ~94%.
Отсюда правило **держать кластер ниже ~70–80%** и алертить на `OSD_NEARFULL` заранее.

**Сеть.** Минимум 10 Гбит/с в проде (лучше 25), можно разделить `public_network` (клиенты) и
`cluster_network` (репликация и recovery). Каждая запись клиента = ещё 2 записи по сети между
OSD; recovery после отказа хоста гонит по сети весь его объём.

**Recovery против клиентов.** Планировщик mClock (по умолчанию с Quincy) делит ресурсы OSD между
клиентским I/O и восстановлением. Профили: `balanced`, `high_client_ops`, `high_recovery_ops`:
```bash
ceph config set osd osd_mclock_profile high_client_ops    # днём: клиенты важнее
ceph config set osd osd_mclock_profile high_recovery_ops  # ночью: быстрее вернуть избыточность
```text
**Обслуживание.**
```bash
ceph osd set noout                     # плановая перезагрузка: не помечать OSD out и не гнать recovery
# … перезагрузили ноду …
ceph osd unset noout
ceph orch host maintenance enter ceph3 # то же, но cephadm остановит демоны хоста
ceph orch host maintenance exit ceph3

# замена умершего диска: OSD удалить с сохранением ID, новый диск подхватит спецификация
ceph orch osd rm 2 --replace --zap
ceph orch osd rm status
```text
**Мониторинг.** Модуль `prometheus` в MGR (`ceph mgr module enable prometheus`, порт 9283)
+ готовые дашборды и алерты (`ceph-mixin`): health, OSD down/out, nearfull, PG не `active+clean`,
latency OSD, clock skew. Часы — chrony на всех нодах, иначе `MON_CLOCK_SKEW` и странные таймауты.

---

## 13. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| `size 2 / min_size 1` «ради места» | Потеря данных, подтверждённых клиенту | `3/2` или EC с запасом |
| EC 2+1 на трёх хостах | Потеря хоста = I/O стоит (`min_size = 3`) | Replicated 3× или больше хостов |
| Кластер заполнен на 85%+ | Отказ хоста → backfillfull/full → запись встала | < 70–80%, алерт на nearfull |
| 1 Гбит/с сеть | Recovery часами, latency клиентов растёт | 10+ Гбит/с, отдельная cluster network |
| Аппаратный RAID под OSD | Ceph не видит ошибок дисков | HBA/JBOD, один OSD — один диск |
| Потребительские SSD без PLP | Медленный sync-write, риск при потере питания | SSD с PLP, DB/WAL на NVMe |
| Часы не синхронизированы | `MON_CLOCK_SKEW`, проблемы cephx | chrony везде |
| `--all-available-devices` включён, сделали zap «чтобы переразметить» | Диск тут же снова стал OSD | `--unmanaged=true` перед работами |
| Перезагрузка ноды без `noout` | Лишний recovery туда-сюда | `ceph osd set noout` / `host maintenance` |
| Снапшоты RBD как бэкап | Живут в том же кластере | `rbd export-diff`, Velero data mover |
| Ceph на двух нодах | Нет кворума и failure domain | Минимум 3 ноды |

---

## 💼 Как это в DevOps

- В on-prem Ceph чаще всего живёт под Proxmox/OpenStack или под Kubernetes через Rook
  ([05_k8s_stateful.md](/storage/05-k8s-stateful)). Девопс его не всегда строит, но **обязан** читать
  `ceph -s`, понимать, почему PVC тормозят при recovery, и не ронять кластер перезагрузками без `noout`.
- Ёмкость планируют с запасом на отказ хоста: «сколько будет занято, если один хост умрёт и его
  данные переедут» — вопрос из каждого capacity review.
- Апгрейды — через `ceph orch upgrade`, после чтения release notes, при `HEALTH_OK` и
  со свежим бэкапом того, что нельзя потерять. Squid поддерживается до конца октября 2026 — такие даты ставят в план заранее.
- Алерты от MGR prometheus + дашборды; на инцидент первым делом `ceph -s` и `ceph health detail`,
  потом `ceph osd tree` и `ceph osd perf`.
- Для баз данных с собственной репликацией часто выгоднее локальные NVMe, а Ceph оставляют под
  ВМ, RWX и S3: база × 3 реплики × Ceph `size 3` = 9 копий и лишняя сетевая latency.

---

## 📌 Шпаргалка

| Хочу | Команда |
|------|---------|
| Статус / детали | `ceph -s` / `ceph health detail` / `ceph -w` |
| OSD по хостам и заполнение | `ceph osd tree` / `ceph osd df tree` |
| Место по пулам | `ceph df` |
| Застрявшие PG | `ceph pg dump_stuck` |
| Медленный OSD | `ceph osd perf` |
| Bootstrap | `cephadm bootstrap --mon-ip IP [--skip-monitoring-stack]` |
| CLI кластера | `cephadm shell -- ceph …` |
| Добавить хост | `ssh-copy-id -f -i /etc/ceph/ceph.pub root@H` → `ceph orch host add H IP` |
| Диски и OSD | `ceph orch device ls --refresh` / `ceph orch apply osd --all-available-devices` |
| Заменить диск | `ceph orch osd rm ID --replace --zap` |
| Пул и RBD | `ceph osd pool create rbd && rbd pool init rbd` / `rbd create rbd/v --size 2G` |
| Подключить RBD | `rbd map rbd/v` → `/dev/rbd0` |
| CephFS | `ceph fs volume create cephfs` |
| S3 (RGW) | `ceph orch apply rgw NAME` + `radosgw-admin user create --uid=U --display-name=N` |
| EC-профиль | `ceph osd erasure-code-profile set ec42 k=4 m=2 crush-failure-domain=host` |
| Обслуживание | `ceph osd set noout` … `unset noout` |
| Приоритет recovery | `ceph config set osd osd_mclock_profile high_recovery_ops` |
| Падения демонов | `ceph crash ls` / `ceph crash archive-all` |
| Апгрейд | `ceph orch upgrade start --ceph-version X.Y.Z` |

---

## 🧠 Что запомнить

1. Ceph — одна система для блока (RBD), файла (CephFS) и объекта (RGW) поверх RADOS.
2. MON держат кворум и карты (3 или 5), MGR — метрики и orchestrator, OSD — по одному на диск, MDS — только для CephFS.
3. Объект → PG → CRUSH → набор OSD; клиент сам вычисляет, куда писать, — без центрального шлюза.
4. ⭐ `size 3 / min_size 2`: запись подтверждается после всех реплик; меньше `min_size` копий — I/O стоит.
5. EC экономит место, но медленнее на мелкой записи и требует k+m failure domain; `min_size = k+1`.
6. BlueStore пишет на сырой диск, считает контрольные суммы; scrub и deep-scrub ловят порчу.
7. ⭐ `ceph -s` и `ceph health detail` — первое на любом инциденте; `active+clean` — норма, `inactive`/`down` — авария.
8. Три хоста при `size 3` переживают потерю одного, но восстанавливаться некуда; с 4+ хостами нужен запас места.
9. Держи заполнение ниже ~70–80%: пороги nearfull 85%, backfillfull 90%, full 95% (запись встаёт).
10. Нужны 10+ Гбит/с сеть, синхронное время, HBA вместо RAID, `noout` на время обслуживания.
11. Актуальный релиз — Tentacle 20.2.x; Squid поддерживается до 2026-10-31.

➡️ Дальше: [05_k8s_stateful.md](/storage/05-k8s-stateful) · задачи: 04_ceph_tasks.md


---

### Блок A. Теория


**A1.** Какие три интерфейса отдаёт Ceph и на каком общем ядре они построены?

<details><summary>Ответ</summary>

Блок (RBD), файл (CephFS), объект (RGW, S3/Swift). Все три построены на RADOS —
распределённом объектном хранилище из OSD, которыми управляют MON.

</details>

**A2.** Назови демоны Ceph и роль каждого. Какие из них не нужны, если используешь только RBD?

<details><summary>Ответ</summary>

MON — кворум и карты кластера; MGR — метрики, dashboard, orchestrator, autoscaler;
OSD — хранение объектов на дисках, репликация, recovery, scrub; MDS — метаданные CephFS;
RGW — S3-шлюз. Для одного RBD не нужны MDS и RGW.

</details>

**A3.** ⭐ Почему MON должно быть нечётное число? Что происходит с кластером без кворума MON?

<details><summary>Ответ</summary>

Кворум — большинство MON: из 3 выдерживает потерю 1, из 5 — 2; чётное число не добавляет
устойчивости (4 MON тоже выдерживают только 1 отказ) и повышает риск split-brain-ничьей. Без
кворума нельзя обновить карты — кластер перестаёт обслуживать изменения и новые подключения,
I/O встаёт, хотя данные на OSD целы.

</details>

**A4.** Как объект попадает на конкретные OSD? Объясни цепочку объект → PG → CRUSH → acting set.

<details><summary>Ответ</summary>

Имя объекта хэшируется, `hash mod pg_num` даёт PG в пуле; CRUSH по карте кластера и
правилу пула вычисляет упорядоченный набор OSD (acting set), первый — primary. Клиент считает
это сам и пишет на primary, тот рассылает репликам.

</details>

**A5.** Зачем нужны placement groups, если можно раскладывать сами объекты? Что будет при слишком малом и слишком большом числе PG?

<details><summary>Ответ</summary>

Объектов миллиарды — следить за каждым (peering, recovery, статистика) невозможно; PG
группируют объекты и делают учёт и восстановление управляемыми. Мало PG — неравномерное
заполнение OSD и медленный параллелизм recovery; много — лишняя память и нагрузка на peering.
Autoscaler держит порядка 100 PG на OSD.

</details>

**A6.** Что такое failure domain и device class в CRUSH? Приведи пример правила.

<details><summary>Ответ</summary>

Failure domain — уровень иерархии CRUSH (host, rack, datacenter), по которому реплики
разносятся так, чтобы отказ одного элемента не унёс две копии. Device class — hdd/ssd/nvme.
Пример: `ceph osd crush rule create-replicated fast default host ssd` — реплики на разных хостах
и только на SSD.

</details>

**A7.** ⭐ Что означают `size` и `min_size`? Почему `size 2 / min_size 1` опасен?

<details><summary>Ответ</summary>

`size` — число копий, `min_size` — минимум живых копий, при котором PG принимает I/O.
`2/1` принимает запись на единственную копию: если её диск умрёт до восстановления второй —
данные, подтверждённые клиенту, потеряны. В проде — `3/2`.

</details>

**A8.** Сравни реплицируемый пул 3× и EC 4+2: ёмкость, отказоустойчивость, скорость, минимум хостов.

<details><summary>Ответ</summary>

3×: ёмкость 33%, переживает 2 отказа, быстрая мелкая запись, минимум 3 хоста. EC 4+2:
ёмкость 67%, переживает 2 отказа, медленнее на мелкой случайной записи и дороже по CPU/сети при
recovery, нужно минимум 6 хостов при failure domain host, `min_size = 5`.

</details>

**A9.** Что такое BlueStore? Где хранятся метаданные, зачем выносить DB/WAL на NVMe?

<details><summary>Ответ</summary>

BlueStore — движок OSD, пишущий данные прямо на сырое устройство (через LVM-том
ceph-volume), метаданные — в RocksDB на BlueFS. DB/WAL на NVMe ускоряют метаданные и мелкие
синхронные записи — особенно в HDD-кластерах. Есть контрольные суммы всех данных и сжатие.

</details>

**A10.** Чем scrub отличается от deep-scrub? Что значит PG `inconsistent`?

<details><summary>Ответ</summary>

Scrub сверяет метаданные и размеры объектов между репликами (ежедневно), deep-scrub
читает и сверяет содержимое по контрольным суммам (еженедельно). `inconsistent` — найдено
расхождение между копиями: проверить диск, `rados list-inconsistent-obj`, затем `ceph pg repair`.

</details>

**A11.** Какие условия должны выполняться, чтобы cephadm счёл диск «available» для OSD?

<details><summary>Ответ</summary>

Нет разделов, нет ФС, нет LVM, не смонтирован, размер больше 5 ГБ (и не занят другим
демоном). Причины отказа видны в колонке REJECT REASONS `ceph orch device ls`.

</details>

**A12.** Чем опасен сервис `osd.all-available-devices` при работах с дисками?

<details><summary>Ответ</summary>

Это декларативная спецификация: любой подходящий диск, включая только что затёртый
(`zap`), тут же станет OSD. Перед работами — `ceph orch apply osd --all-available-devices --unmanaged=true`.

</details>

**A13.** ⭐ Расшифруй состояния PG: `active+clean`, `active+undersized+degraded`, `backfilling`, `peering`, `inactive`.

<details><summary>Ответ</summary>

`active+clean` — всё в норме; `active+undersized+degraded` — копий меньше `size`, но не
меньше `min_size`, I/O идёт; `backfilling` — PG целиком копируется на новые OSD; `peering` —
OSD согласуют историю PG (кратко — норма); `inactive` — PG не обслуживает I/O (копий меньше
`min_size` или нет нужных OSD) — авария.

</details>

**A14.** Какие пороги заполнения есть в Ceph и почему кластер держат ниже ~70–80%?

<details><summary>Ответ</summary>

`nearfull` 85% (предупреждение), `backfillfull` 90% (на OSD не идёт backfill),
`full` 95% (запись в кластер останавливается). При отказе хоста его данные переезжают на
остальные и заполнение растёт примерно в N/(N−1) раз — без запаса кластер упрётся в пороги
именно во время аварии.

</details>

**A15.** Что будет в кластере из трёх хостов с `size 3` и failure domain `host`, если один хост умер навсегда? А если хостов пять?

<details><summary>Ответ</summary>

Три хоста: PG станут `active+undersized+degraded`, I/O идёт, но досоздать третью копию
некуда — избыточность снижена до возвращения/замены хоста. Пять хостов: через 600 секунд
(`mon_osd_down_out_interval`) OSD пометятся out, недостающие копии досоздадутся на четырёх
оставшихся — нужна свободная ёмкость.

</details>

**A16.** Зачем `ceph osd set noout` перед плановой перезагрузкой ноды?

<details><summary>Ответ</summary>

Чтобы OSD перезагружаемой ноды не пометились out через 10 минут и кластер не начал
тяжёлое перераспределение данных, которое после возврата ноды пойдёт обратно.

</details>

**A17.** Какие версии Ceph актуальны на сентябрь 2026 и что из этого следует для кластера на Squid?

<details><summary>Ответ</summary>

Tentacle 20.2.x — актуальный стабильный, Squid 19.2.6 поддерживается до 2026-10-31,
Reef архивирован, Umbrella 21 — RC. Кластер на Squid нужно планово обновить до Tentacle до
конца октября: прочитать release notes, проверить клиентов (ядра, ceph-csi/Rook), обновиться в тесте.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  ceph osd pool create data && ceph osd pool set data size 2 && ceph osd pool set data min_size 1
```text
<details><summary>Ответ</summary>

🔴 `2/1` — запись подтверждается при одной живой копии; отказ второго диска в окне
восстановления = потеря подтверждённых данных. `size 3`, `min_size 2`.

</details>

```text:no-line-numbers
B2.  ceph osd erasure-code-profile set ec21 k=2 m=1 crush-failure-domain=host
```text
<details><summary>Ответ</summary>

⚠️ У EC-пула `min_size = k+1 = 3`: потеря одного хоста из трёх переводит PG в inactive —
I/O стоит. Данные целы, но сервис лежит. Нужен replicated 3× или 4+ хостов с `min_size` k+1.

</details>

```text:no-line-numbers
     ceph osd pool create ecdata erasure ec21           # кластер из трёх хостов
```text
```text:no-line-numbers
     # «потеряем хост — ничего страшного, m=1»
```text
```text:no-line-numbers
B3.  ceph osd erasure-code-profile set ec42 k=4 m=2 crush-failure-domain=host
```text
<details><summary>Ответ</summary>

⚠️ Для 4+2 с failure domain host нужно 6 хостов; при трёх PG не смогут разместиться
(CRUSH не найдёт 6 разных хостов) — пул не станет `active+clean`.

</details>

```text:no-line-numbers
     ceph osd pool create ec42pool erasure ec42         # хостов три
```text
```text:no-line-numbers
B4.  # кластер из 3 MON; два MON-хоста выключили на обслуживание одновременно
```text
<details><summary>Ответ</summary>

🔴 Из трёх MON остался один — кворума нет, кластер встанет. Обслуживать MON по одному,
дожидаясь возвращения в кворум.

</details>

```text:no-line-numbers
B5.  ceph orch device zap ceph2 /dev/vdb --force       # хотим «переразметить» диск,
```text
<details><summary>Ответ</summary>

⚠️ Затёртый диск снова «available» — сервис тут же создаст на нём OSD. Сначала
`--unmanaged=true` для сервиса OSD.

</details>

```text:no-line-numbers
     # сервис osd.all-available-devices включён
```text
```text:no-line-numbers
B6.  # сервер ceph3 перезагружают для обновления ядра, флаги не ставили; ребут занял 15 минут
```text
<details><summary>Ответ</summary>

⚠️ Через 10 минут OSD ceph3 пометятся out, начнётся перераспределение (на 4+ хостах), а
после возврата — обратное. Лишняя нагрузка и риск. Нужно `ceph osd set noout` или
`ceph orch host maintenance enter ceph3`.

</details>

```text:no-line-numbers
B7.  # ceph df: RAW USED 82%; в кластере 4 хоста; «до 95% ещё далеко»
```text
<details><summary>Ответ</summary>

⚠️ При отказе хоста заполнение вырастет примерно до 82% × 4/3 ≈ 109% — не влезет,
OSD упрутся в backfillfull/full, запись встанет. Расширять кластер уже сейчас.

</details>

```text:no-line-numbers
B8.  # OSD развёрнуты на логических дисках RAID5 аппаратного контроллера
```text
<details><summary>Ответ</summary>

⚠️ Ceph не видит отдельных дисков и их ошибок, двойная избыточность (RAID5 + реплики)
и write penalty. Контроллер в HBA/JBOD, один OSD на диск.

</details>

```text:no-line-numbers
B9.  # health: HEALTH_WARN clock skew detected on mon.ceph3
```text
<details><summary>Ответ</summary>

⚠️ Часы ceph3 расходятся больше чем на 0,05 с. Чинить chrony/NTP (`chronyc tracking`),
иначе нестабильный кворум и проблемы cephx.

</details>

```text:no-line-numbers
B10.  rbd snap create rbd/pgdata@nightly     # «это наш ночной бэкап базы»
```text
<details><summary>Ответ</summary>

⚠️ Снапшот RBD лежит в том же кластере и в том же пуле — умер кластер, умер и «бэкап».
К тому же он crash-consistent без PITR. Бэкап БД — инструментами БД; том — `rbd export-diff`
или Velero data mover в другое хранилище.

</details>

```text:no-line-numbers
B11.  # сеть кластера 1 Гбит/с, один хост с 8 × 16 ТБ HDD умер
```text
<details><summary>Ответ</summary>

⚠️ Надо перекопировать ~128 ТБ по сети 1 Гбит/с (~125 МБ/с) — это больше десяти суток
при идеальных условиях, всё это время избыточность снижена и клиенты страдают. 10–25 Гбит/с,
отдельная cluster network, более мелкие хосты.

</details>

```text:no-line-numbers
B12.  cephadm bootstrap --mon-ip 192.168.61.11
```text
<details><summary>Ответ</summary>

⚠️ Без IP cephadm будет резолвить имя через DNS — не найдёт хост. Указывать IP явно:
`ceph orch host add ceph2 192.168.61.12` (и разложить ключ `/etc/ceph/ceph.pub`).

</details>

```text:no-line-numbers
     ceph orch host add ceph2                # DNS для ceph2 не настроен, IP не указан
```text
```text:no-line-numbers
B13.  ceph osd pool create rbd
```text
<details><summary>Ответ</summary>

⚠️ Пул не помечен приложением `rbd` — будет предупреждение `POOL_APP_NOT_ENABLED`, а
`rbd pool init` ещё и инициализирует служебные объекты. Выполнить `rbd pool init rbd`.

</details>

```text:no-line-numbers
     rbd create rbd/vol1 --size 2G           # rbd pool init не выполняли
```text
---

### Блок C. Практика


### C1. 🔑 Кластер из трёх нод
Подними Ceph Tentacle 20.2.4 через cephadm на ceph1..3 (`--skip-monitoring-stack`), добавь хосты,
создай OSD на всех `vdb`. Добейся `HEALTH_OK`. Покажи `ceph -s`, `ceph osd tree`, `ceph orch ps`.
Как ты раздал SSH-ключ cephadm на Vagrant-VM без пароля root?

### C2. 🔑 RBD-том
Создай пул `rbd`, том `vol1` на 2G, смонтируй его на ceph1 с XFS, запиши 500 МБ, посчитай
`sha256sum`. Увеличь том до 4G онлайн и дорасти ФС. Сделай снапшот и откати к нему.

### C3. 🔑 Отказ OSD
Останови `osd.2` (`ceph orch daemon stop osd.2`) и в соседнем окне смотри `watch -n2 ceph -s`.
Запиши, какие коды появились в `ceph health detail` и какие состояния PG. Верни OSD и засеки время
до `HEALTH_OK`.

### C4. Потеря хоста и двух хостов
**1.** `vagrant halt ceph3`, подожди больше 10 минут. OSD помечен out? Идёт ли recovery? Почему?

<details><summary>Ответ</summary>

Команды — раздел 7 конспекта и лаба 3 в [08_practice_labs.md](/softskills/08-practice-labs).
Ключ: `PUB=$(vagrant ssh ceph1 -c 'sudo cat /etc/ceph/ceph.pub' | tr -d '\r')`, затем для
ceph2/ceph3 `vagrant ssh cephN -c "echo '$PUB' | sudo tee -a /root/.ssh/authorized_keys"`
(sshd в Ubuntu по умолчанию разрешает root вход по ключу — `PermitRootLogin prohibit-password`).
Итог: `mon: 3 daemons, quorum ceph1,ceph2,ceph3`, `osd: 3 osds: 3 up, 3 in`, `HEALTH_OK`.

</details>

**2.** Выключи ещё ceph2. Что происходит с записью на `/mnt/rbd`? С кворумом MON?

<details><summary>Ответ</summary>

```bash
ceph osd pool create rbd && rbd pool init rbd && rbd create rbd/vol1 --size 2G
sudo apt-get install -y ceph-common            # на ceph1 вне контейнера
sudo rbd map rbd/vol1 && sudo mkfs.xfs /dev/rbd0 && sudo mkdir -p /mnt/rbd && sudo mount /dev/rbd0 /mnt/rbd
sudo dd if=/dev/urandom of=/mnt/rbd/blob bs=1M count=500 status=none && sha256sum /mnt/rbd/blob
sudo rbd resize rbd/vol1 --size 4G && sudo xfs_growfs /mnt/rbd
sudo rbd snap create rbd/vol1@s1
# откат: размонтировать и отключить, потом rollback
sudo umount /mnt/rbd && sudo rbd unmap /dev/rbd0 && sudo rbd snap rollback rbd/vol1@s1
```text
</details>

**3.** Верни обе ноды, дождись `active+clean`, сверь `sha256sum`.

<details><summary>Ответ</summary>

) После `vagrant up` — кворум, peering, recovery, `active+clean`; sha256 совпадает.

</details>

### C5. Плановое обслуживание
Перезагрузи ceph2 «правильно»: с `noout` или `ceph orch host maintenance`. Сравни с C4.1: что не
произошло и почему это важно на больших кластерах?

### C6. CRUSH и пулы
**1.** Посмотри device class OSD (`ceph osd tree`, колонка CLASS). Создай правило `fast` только для
   этого класса с failure domain `host` и назначь его пулу `rbd`.

<details><summary>Ответ</summary>

Команды — раздел 7 конспекта и лаба 3 в [08_practice_labs.md](/softskills/08-practice-labs).
Ключ: `PUB=$(vagrant ssh ceph1 -c 'sudo cat /etc/ceph/ceph.pub' | tr -d '\r')`, затем для
ceph2/ceph3 `vagrant ssh cephN -c "echo '$PUB' | sudo tee -a /root/.ssh/authorized_keys"`
(sshd в Ubuntu по умолчанию разрешает root вход по ключу — `PermitRootLogin prohibit-password`).
Итог: `mon: 3 daemons, quorum ceph1,ceph2,ceph3`, `osd: 3 osds: 3 up, 3 in`, `HEALTH_OK`.

</details>

**2.** Выведи `ceph osd pool autoscale-status` и объясни колонки PG_NUM и NEW PG_NUM.

<details><summary>Ответ</summary>

```bash
ceph osd pool create rbd && rbd pool init rbd && rbd create rbd/vol1 --size 2G
sudo apt-get install -y ceph-common            # на ceph1 вне контейнера
sudo rbd map rbd/vol1 && sudo mkfs.xfs /dev/rbd0 && sudo mkdir -p /mnt/rbd && sudo mount /dev/rbd0 /mnt/rbd
sudo dd if=/dev/urandom of=/mnt/rbd/blob bs=1M count=500 status=none && sha256sum /mnt/rbd/blob
sudo rbd resize rbd/vol1 --size 4G && sudo xfs_growfs /mnt/rbd
sudo rbd snap create rbd/vol1@s1
# откат: размонтировать и отключить, потом rollback
sudo umount /mnt/rbd && sudo rbd unmap /dev/rbd0 && sudo rbd snap rollback rbd/vol1@s1
```text
</details>

### C7. CephFS и RGW
**1.** Создай CephFS, смонтируй на ceph1 и ceph2 одновременно, запиши файл с одной ноды, прочитай с другой.

<details><summary>Ответ</summary>

Команды — раздел 7 конспекта и лаба 3 в [08_practice_labs.md](/softskills/08-practice-labs).
Ключ: `PUB=$(vagrant ssh ceph1 -c 'sudo cat /etc/ceph/ceph.pub' | tr -d '\r')`, затем для
ceph2/ceph3 `vagrant ssh cephN -c "echo '$PUB' | sudo tee -a /root/.ssh/authorized_keys"`
(sshd в Ubuntu по умолчанию разрешает root вход по ключу — `PermitRootLogin prohibit-password`).
Итог: `mon: 3 daemons, quorum ceph1,ceph2,ceph3`, `osd: 3 osds: 3 up, 3 in`, `HEALTH_OK`.

</details>

**2.** Разверни RGW на ceph1:8080, создай пользователя, подключись к нему `mc` с хоста и создай бакет.

<details><summary>Ответ</summary>

```bash
ceph osd pool create rbd && rbd pool init rbd && rbd create rbd/vol1 --size 2G
sudo apt-get install -y ceph-common            # на ceph1 вне контейнера
sudo rbd map rbd/vol1 && sudo mkfs.xfs /dev/rbd0 && sudo mkdir -p /mnt/rbd && sudo mount /dev/rbd0 /mnt/rbd
sudo dd if=/dev/urandom of=/mnt/rbd/blob bs=1M count=500 status=none && sha256sum /mnt/rbd/blob
sudo rbd resize rbd/vol1 --size 4G && sudo xfs_growfs /mnt/rbd
sudo rbd snap create rbd/vol1@s1
# откат: размонтировать и отключить, потом rollback
sudo umount /mnt/rbd && sudo rbd unmap /dev/rbd0 && sudo rbd snap rollback rbd/vol1@s1
```text
</details>

### C8. Здоровье и crash
Найди в кластере (или спровоцируй `kill -9` процесса OSD внутри контейнера) `RECENT_CRASH`.
Покажи `ceph crash ls`, `ceph crash info`, закрой предупреждение. Что обязательно сделать до `archive-all`?

### C9. Ёмкость «с запасом на отказ»
Кластер: 5 хостов по 40 ТБ сырых, реплики 3×, занято 60% сырого. Посчитай полезную ёмкость,
сколько данных хранится и каким будет заполнение после смерти одного хоста и восстановления.
Пройдёт ли кластер через это без `backfillfull`?

---

### Блок D. Инциденты


**D1.** `HEALTH_ERR`: `1 full osd(s)`, приложения не могут писать на RBD-тома.

<details><summary>Ответ</summary>

OSD достиг 95% — кластер остановил запись. Срочно освободить место или добавить OSD;
временно можно поднять порог (`ceph osd set-full-ratio 0.96`) только чтобы удалить данные и
дать recovery пройти, потом вернуть. Проверить перекос `ceph osd df` (balancer, reweight).
Разбор: почему не сработал алерт на nearfull.

</details>

**D2.** После работ в стойке `ceph -s`: `33 pgs inactive`, у пользователей зависают операции записи.

<details><summary>Ответ</summary>

Не хватает копий до `min_size` или нужные OSD недоступны — I/O стоит, это авария.
`ceph health detail`, `ceph pg dump_stuck inactive`, `ceph pg &lt;pgid&gt; query` (что ждёт peering),
`ceph osd tree` — какие OSD/хосты down после работ в стойке (питание, сеть, cluster network).
Вернуть OSD — PG станут active.

</details>

**D3.** PVC на Rook-Ceph резко стали медленными днём, в `ceph -s` — `recovering`, `backfilling`.

<details><summary>Ответ</summary>

Recovery/backfill конкурируют с клиентским I/O. Днём — `osd_mclock_profile
high_client_ops`, ночью — `high_recovery_ops`; найти причину recovery (упавший OSD, добавленный
диск, изменённое правило CRUSH) и не делать таких изменений в пик.

</details>

**D4.** `ceph health detail`: `1 scrub errors`, `Possible data damage: 1 pg inconsistent`.

<details><summary>Ответ</summary>

Scrub нашёл расхождение копий. `rados list-inconsistent-obj &lt;pgid&gt; --format=json-pretty`
— какие объекты и на каком OSD ошибка; проверить диск (SMART, `dmesg`); если виноват диск —
заменить OSD; затем `ceph pg repair &lt;pgid&gt;`. Повторяющиеся ошибки на одном OSD — выводить диск.

</details>

**D5.** Один OSD постоянно флапает (up/down), в `ceph osd perf` у него latency в 20 раз выше соседей.

<details><summary>Ответ</summary>

Умирающий или перегруженный диск (или сеть ноды): соседи отмечают его down, он
возвращается — флапы вызывают постоянный peering. Проверить SMART, `dmesg`, сеть; вывести OSD
(`ceph osd out osd.N`), дождаться recovery и заменить диск (`ceph orch osd rm N --replace --zap`).

</details>

**D6.** `MON_CLOCK_SKEW` после миграции VM на другой гипервизор, плюс странные ошибки аутентификации.

<details><summary>Ответ</summary>

Часы на новом гипервизоре не синхронизированы (или chrony не работает в VM). Настроить
chrony на всех нодах с одним источником, проверить `chronyc tracking`; cephx чувствителен ко
времени (тикеты с временем жизни) — после синхронизации ошибки уйдут.

</details>

**D7.** Коллега удалил OSD с «пустого» диска на ceph2, чтобы использовать диск под другое, а через
минуту на этом диске снова появился OSD.

<details><summary>Ответ</summary>

Сервис `osd.all-available-devices` в managed-режиме: диск после zap снова подходит и
был подхвачен. Удалить OSD, перевести спецификацию в `--unmanaged=true` (или сузить её
фильтрами), потом zap и использовать диск.

</details>

**D8.** Кластер на Squid 19.2, сейчас сентябрь 2026. Что делать и в каком порядке?

<details><summary>Ответ</summary>

Squid поддерживается до 2026-10-31. План: прочитать release notes Tentacle, проверить
совместимость клиентов (ядра для krbd/CephFS, версии ceph-csi/Rook, OpenStack/Proxmox), обновить
тестовый кластер, убедиться в `HEALTH_OK` и свежих бэкапах, `ceph orch upgrade start
--ceph-version 20.2.4`, следить за `ceph orch upgrade status`, после — проверка клиентов.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Что такое Ceph и из каких компонентов он состоит?

<details><summary>Ответ</summary>

Программно-определяемое хранилище, отдающее блок (RBD), файл (CephFS) и объект (RGW) поверх
   RADOS. Демоны: MON (кворум, карты), MGR (метрики, orchestrator), OSD (по одному на диск),
   MDS (метаданные CephFS), RGW (S3).

</details>

**2.** Как Ceph решает, где хранить данные? Что такое CRUSH и PG?

<details><summary>Ответ</summary>

Объект хэшируется в PG пула, CRUSH по карте кластера и правилу вычисляет набор OSD с учётом
   failure domain. Клиент считает сам — нет центральной таблицы и шлюза на пути данных.

</details>

**3.** Что такое `size` и `min_size`? Какие значения ставишь в проде?

<details><summary>Ответ</summary>

Число копий и минимум копий для приёма I/O. В проде `3/2`: переживает отказ одной копии
   без остановки и не принимает запись на единственную копию.

</details>

**4.** Репликация или erasure coding — когда что?

<details><summary>Ответ</summary>

Репликация — для RBD под БД и ВМ, метаданных, мелкой случайной записи. EC — для крупных
   объектов, архива, данных RGW, когда важна ёмкость и хостов достаточно (k+m и больше).

</details>

**5.** Почему для Ceph минимум три ноды?

<details><summary>Ответ</summary>

Кворум MON (большинство из 3) и три failure domain для трёх копий. Реально лучше 4–5 хостов,
   чтобы после отказа было куда восстанавливать.

</details>

**6.** Как читать `ceph -s`? Что будешь делать при `HEALTH_WARN`?

<details><summary>Ответ</summary>

`health` + коды, кворум MON, OSD up/in, состояния PG, заполнение. При WARN — `ceph health
   detail`, дальше по коду: OSD down → `ceph osd tree` и диск; nearfull → место; clock skew →
   chrony; degraded → смотреть, идёт ли recovery.

</details>

**7.** Почему нельзя заполнять Ceph до 95%?

<details><summary>Ответ</summary>

На 95% запись останавливается; при отказе хоста данные переезжают на остальные и
   заполнение растёт — нужен запас. Держат ниже ~70–80%.

</details>

**8.** Что происходит при отказе диска и при отказе целого сервера?

<details><summary>Ответ</summary>

Отказ диска: OSD down → через 10 минут out → копии досоздаются на других OSD. Отказ сервера:
   то же для всех его OSD — нужен свободный объём на других хостах; при 3 хостах и size 3
   восстанавливаться некуда, кластер живёт в degraded.

</details>

**9.** Как вывести ноду на обслуживание?

<details><summary>Ответ</summary>

`ceph osd set noout` (или `ceph orch host maintenance enter`), работы, возврат, `unset noout`,
   дождаться `active+clean` перед следующей нодой.

</details>

**10.** Когда Ceph — плохой выбор?

<details><summary>Ответ</summary>

Мало серверов и слабая сеть, небольшие объёмы, нет компетенций; базы с собственной
    репликацией (лучше локальные NVMe); нужен только S3 (проще MinIO-подобные решения).

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Объясняю архитектуру: MON, MGR, OSD, MDS, RGW, RADOS
- [ ] ⭐ Объясняю цепочку объект → PG → CRUSH → OSD и роль failure domain
- [ ] Знаю `size/min_size`, почему `3/2`, и ограничения EC (`min_size = k+1`, k+m хостов)
- [ ] Кластер из трёх нод поднят cephadm, HEALTH_OK
- [ ] RBD смонтирован, расширен, снапшот откачен
- [ ] ⭐ Пережил отказ OSD, хоста и двух хостов; объясняю, что происходило с PG и записью
- [ ] Вывожу ноду на обслуживание с `noout`
- [ ] Читаю `ceph -s` и `ceph health detail`, знаю основные коды и состояния PG
- [ ] Считаю ёмкость с запасом на отказ хоста
- [ ] Поднимал CephFS и RGW, знаю, когда Ceph — плохой выбор
