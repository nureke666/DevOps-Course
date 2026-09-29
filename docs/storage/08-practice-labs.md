---
title: "08. Практика: 5 лаб по хранилищам и stateful"
description: "Блок → Хранилища и stateful → практика."
---

# 08. Практика: 5 лаб по хранилищам и stateful

> Блок → Хранилища и stateful → практика.
> Лабы делаются руками на стендах из [00_INDEX.md](/storage/) (раздел «Стенд») и остаются
> в git: Vagrantfile, compose, скрипты, заметки с замерами. После них есть что рассказать на
> собесе: «менял диск под нагрузкой через pvmove», «ронял OSD и смотрел recovery»,
> «восстанавливал базу на секунду раньше DROP TABLE», «восстанавливал namespace Velero'ом».
>
> Версии и флаги сверены с документацией на сентябрь 2026: Ceph Tentacle 20.2.4, Rook v1.20.7,
> Velero v1.18.3 + velero-plugin-for-aws v1.14.3, WAL-G v3.0.9, PostgreSQL 16 (PGDG),
> pgBackRest 2.59.1, MinIO-форк `pgsty/silo:RELEASE.2026-09-16T00-00-00Z`. Их и пинь.
>
> ⚠️ Всё разрушающее — только на доп. дисках учебных VM. Перед каждой лабой —
> `vagrant snapshot save &lt;vm&gt; before_labN`.

---

## 📋 Список лаб

| № | Лаба | Что закрепляет | Артефакт |
|---|------|----------------|----------|
| 1 | ⭐ LVM на 3 дисках: создать, расширить онлайн, снапшот, замена диска через pvmove, growpart; учения mdadm RAID1 | темы 01, 02 | `lab1/notes.md` с командами и выводами |
| 2 | MinIO для бэкапов: версии, lifecycle, object lock, пользователь без права удаления | тема 03 | compose, `policies/*.json`, `lab2/check.sh` |
| 3 | ⭐ Ceph из 3 нод (cephadm) → RBD → убить OSD/ноду → recovery (вариант: Rook на k3s) | темы 04, 05 | `lab3/notes.md`: таймлайн состояний `ceph -s` |
| 4 | ⭐ PostgreSQL + WAL-G → MinIO, PITR после «DROP TABLE» (бонус: pgBackRest с TLS) | темы 03, 06 | `.walg.json`, `lab4/pitr.md` с RPO/RTO |
| 5 | ⭐ Velero: namespace с PVC → MinIO → удалить namespace → restore | темы 05, 07 | манифесты, `restore-check.sh`, `docs/dr.md` |

---

## 🧪 Лаба 1. LVM на трёх дисках + учения mdadm RAID1

### Что делаем
На `stor1` собираем том LVM из двух дисков, работаем с ним под нагрузкой: расширяем онлайн,
делаем снапшот и откат, заменяем «стареющий» диск через `pvmove`, разбираем инцидент «диск
расширили, а места нет» в двух вариантах. Затем собираем RAID1 на mdadm и проводим учения
с отказом и заменой диска. Теория — [02_lvm_filesystems.md](/storage/02-lvm-filesystems).

### Каркас
```bash
vagrant snapshot save stor1 before_lab1 && vagrant ssh stor1
lsblk -o NAME,SIZE,SERIAL,TYPE,MOUNTPOINTS     # vdb/vdc/vdd = lvm-a/b/c, vde/vdf/vdg = raid-a/b/c
sudo apt-get install -y lvm2 xfsprogs mdadm cloud-guest-utils fio

# ⚠️ дальше — только доп. диски учебной VM
# 1. PV → VG → LV → ФС → fstab
sudo pvcreate /dev/vdb /dev/vdc
sudo vgcreate data /dev/vdb /dev/vdc
sudo lvcreate -n app -L 3G data
sudo mkfs.xfs /dev/data/app
sudo mkdir -p /srv/app
echo "UUID=$(sudo blkid -s UUID -o value /dev/data/app) /srv/app xfs defaults,noatime,nofail 0 2" \
  | sudo tee -a /etc/fstab
sudo systemctl daemon-reload && sudo mount -a && findmnt /srv/app

# 2. фоновая «нагрузка» на всё время лабы (второй терминал)
while true; do sudo dd if=/dev/urandom of=/srv/app/f$((RANDOM%50)) bs=1M count=20 status=none; sleep 1; done

# 3. расширение онлайн
sudo lvextend -r -L +2G data/app && df -h /srv/app

# 4. снапшот и откат
echo "до ошибки" | sudo tee /srv/app/important.txt
sudo lvcreate -s -n app_snap -L 1G data/app
sudo rm /srv/app/important.txt                                # «ошибка оператора»
sudo mkdir -p /mnt/snap && sudo mount -o ro,nouuid /dev/data/app_snap /mnt/snap
cat /mnt/snap/important.txt                                   # файл есть в снапшоте
sudo lvs -o lv_name,lv_size,origin,data_percent data          # Data% снапшота растёт от нагрузки

# 5. замена диска онлайн: vdb «стареет», уходим с него на vdd
sudo pvcreate /dev/vdd && sudo vgextend data /dev/vdd
sudo pvmove /dev/vdb                  # экстенты уезжают на свободные PV, том смонтирован
sudo vgreduce data /dev/vdb && sudo pvremove /dev/vdb

# 6а. «расширили диск в гипервизоре»: PV на целом диске (vdd)
#     на хосте: sudo virsh blockresize storage-lab_stor1 vdd 8G
sudo dmesg | tail -3                  # capacity change
sudo pvresize /dev/vdd && sudo lvextend -r -l +100%FREE data/app

# 6б. тот же инцидент, но PV в разделе: освободившийся vdb размечаем «не на весь диск»
sudo parted -s /dev/vdb mklabel gpt mkpart lvm 1MiB 3GiB
sudo pvcreate /dev/vdb1 && sudo vgextend data /dev/vdb1
sudo growpart /dev/vdb 1              # раздел до конца диска
sudo pvresize /dev/vdb1 && sudo vgs data

# 7. RAID1 на mdadm
sudo mdadm --create /dev/md0 --level=1 --raid-devices=2 /dev/vde /dev/vdf   # на вопрос — y
cat /proc/mdstat
sudo mkfs.ext4 /dev/md0 && sudo mkdir -p /srv/raid && sudo mount /dev/md0 /srv/raid
sudo dd if=/dev/urandom of=/srv/raid/blob bs=1M count=500 status=none && sha256sum /srv/raid/blob
sudo mdadm --detail --scan | sudo tee -a /etc/mdadm/mdadm.conf && sudo update-initramfs -u

# 8. учения: отказ и замена
sudo mdadm /dev/md0 --fail /dev/vdf
cat /proc/mdstat && sudo mdadm --detail /dev/md0      # [U_], degraded
sudo mdadm /dev/md0 --remove /dev/vdf
sudo mdadm /dev/md0 --add /dev/vdg                    # «новый диск»
watch -n1 cat /proc/mdstat                            # recovery = 37.5% …
```text
### Требования
- [ ] Перед каждой разрушающей командой — `lsblk` со SERIAL; ни одна команда не тронула `vda`
- [ ] Том расширен онлайн **под нагрузкой**; объяснено, что делает `-r` и почему для XFS нельзя `resize2fs`
- [ ] Удалённый файл достан из снапшота; откат всего тома через `lvconvert --merge` сделан и объяснён (когда применится, если origin смонтирован)
- [ ] Снапшот намеренно переполнен (маленький `-L 100M` + запись) — видно, что он стал invalid; вывод записан
- [ ] `pvmove` выполнен без размонтирования; `pvs` до и после показывает, где лежат экстенты
- [ ] Оба варианта «диск расширили, а места нет» пройдены: целый диск (`pvresize`) и раздел (`growpart` → `pvresize`)
- [ ] RAID1 пережил `--fail`; rebuild на новый диск завершён; `sha256sum` совпала; после `reboot` массив собрался сам (`/dev/md0` из mdadm.conf)
- [ ] Бонус: thin pool с overcommit (том 10G в пуле 3G), заполни пул и опиши, что увидел приложение

### Критерии приёмки
```bash
sudo pvs; sudo vgs; sudo lvs -a -o lv_name,lv_size,devices data   # vdb (целый) нет в VG, vdd и vdb1 есть
df -hT /srv/app                                                  # xfs, размер вырос
findmnt --verify                                                 # fstab без ошибок
cat /proc/mdstat                                                 # md0 : active raid1 vdg[2] vde[0] … [UU]
sudo mdadm --detail /dev/md0 | grep -E 'State|Active|Failed'     # clean, 2 active, 0 failed
sha256sum /srv/raid/blob                                         # совпадает с записанной
```text
### Вопросы себе
- Почему `pvmove` можно делать под нагрузкой, а `lvreduce` для XFS нельзя вовсе?
- Что будет с приложением, если thin pool заполнится на 100%? А обычный снапшот?
- Почему снапшот LVM на тех же дисках — не бэкап, даже если его сделать консистентным?
- Сколько займёт rebuild RAID1 из дисков по 16 ТБ при 150 МБ/с и что всё это время под угрозой?

---

## 🧪 Лаба 2. MinIO для бэкапов: версии, lifecycle, lock, минимальные права

### Что делаем
Поднимаем MinIO из [00_INDEX.md](/storage/), готовим бакет `pg-backups` так, как готовят
хранилище бэкапов: версионирование, lifecycle для старых версий, отдельный пользователь, который
может писать и читать, но не может удалять; плюс бакет `locked` с object lock. Теория —
[03_nfs_minio.md](/storage/03-nfs-minio).

### Каркас
```json
// ~/labs/storage/minio/files/pg-backup-rw.json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": ["arn:aws:s3:::pg-backups"] },
    { "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject"],
      "Resource": ["arn:aws:s3:::pg-backups/*"] }
  ]
}
```text
```bash
cd ~/labs/storage/minio && docker compose up -d
alias mc='docker exec -i minio mcli'
mc alias set local http://127.0.0.1:9000 admin admin-secret-123
mc admin info local

# бакет бэкапов
mc mb --with-versioning local/pg-backups
mc ilm rule add local/pg-backups --noncurrent-expire-days 7 --expire-delete-marker
mc ilm rule ls local/pg-backups

# пользователь бэкапов
mc admin user add local pg-backup 'pg-backup-secret-123'
mc admin policy create local pg-backup-rw /files/pg-backup-rw.json
mc admin policy attach local pg-backup-rw --user pg-backup
mc alias set pgb http://127.0.0.1:9000 pg-backup 'pg-backup-secret-123'

# проверки
echo v1 > files/test.txt && mc cp /files/test.txt pgb/pg-backups/test.txt
echo v2 > files/test.txt && mc cp /files/test.txt pgb/pg-backups/test.txt
mc ls --versions local/pg-backups/test.txt       # две версии
mc rm pgb/pg-backups/test.txt                    # ожидаем Access Denied

# бакет с блокировкой
mc mb --with-lock local/locked
mc retention set --default GOVERNANCE "1d" local/locked
mc cp /files/test.txt local/locked/test.txt
mc ls --versions local/locked/test.txt
```text
### Требования
- [ ] `pg-backups`: версионирование включено, правила lifecycle — удалять неактуальные версии через 7 дней и одинокие delete marker'ы
- [ ] Пользователь `pg-backup` пишет и читает, но `mc rm` (и удаление конкретной версии) даёт Access Denied
- [ ] Перезапись объекта создаёт версию; предыдущая версия восстановлена (`mc cp --version-id …` или `mc undo`)
- [ ] В `locked` объект с retention GOVERNANCE не удаляется даже админом без `--bypass`; объяснено отличие от COMPLIANCE
- [ ] Объяснено письменно, почему lifecycle «удалять объекты старше 30 дней» опасен для архива WAL (цепочка базовый бэкап + WAL)
- [ ] `mc admin info local` показывает 4 диска и EC:2; объяснено, сколько «дисков» можно потерять без потери чтения и записи
- [ ] Бонус: «умер диск» — `docker exec minio sh -c 'rm -rf /data4/* /data4/.minio.sys'`, объекты читаются, диск залечен (`mc admin info`, `mc admin heal local`)
- [ ] Бонус: TLS — самоподписанный сертификат с SAN в `./certs/{public.crt,private.key}`, `--certs-dir /certs`, доступ по `https://` (понадобится pgBackRest в лабе 4)

### Критерии приёмки
```bash
mc version info local/pg-backups                  # versioning is enabled
mc ilm rule ls local/pg-backups                   # NoncurrentVersionExpiration 7 days, delete marker
mc admin user info local pg-backup                # PolicyName: pg-backup-rw
mc rm pgb/pg-backups/test.txt; echo "exit=$?"     # Access Denied, exit≠0
mc retention info local/locked/test.txt           # GOVERNANCE, до …
mc admin info local | tail -2                     # 4 drives online, 0 drives offline, EC:2
```text
### Вопросы себе
- Кто удаляет старые бэкапы, если у пользователя бэкапов нет права удаления? Чем это лучше?
- Что увидит WAL-G, если его учётка не может удалять, а ты запустишь `wal-g delete retain`?
- Почему object lock включается только при создании бакета?
- Чем этот MinIO на одном хосте всё ещё не off-site копия?

---

## 🧪 Лаба 3. Ceph из трёх нод: RBD и отказ OSD

### Что делаем
На `ceph-lab` поднимаем Ceph Tentacle через cephadm, создаём RBD-том, монтируем, пишем данные
и проводим учения: остановка одного OSD, потеря ноды, потеря двух нод из трёх. Смотрим, как
меняются состояния PG и что происходит с записью. Теория — [04_ceph.md](/storage/04-ceph).

### Каркас
```bash
# на хосте: ключ root@ceph1 раздадим позже через vagrant
cd ~/Projects/devops/stands/ceph-lab && vagrant up && vagrant snapshot save before_lab3

# на КАЖДОЙ ноде (vagrant ssh cephN)
sudo apt-get update && sudo apt-get install -y podman lvm2 chrony
timedatectl | grep synchronized                      # часы синхронны — иначе MON_CLOCK_SKEW

# на ceph1
sudo -i
CEPH_RELEASE=20.2.4
curl --silent --remote-name --location https://download.ceph.com/rpm-${CEPH_RELEASE}/el9/noarch/cephadm
install -m 0755 cephadm /usr/local/sbin/cephadm
cephadm bootstrap --mon-ip 192.168.61.11 --skip-monitoring-stack   # сохрани пароль дашборда
cephadm shell -- ceph -s
cat /etc/ceph/ceph.pub                               # этот ключ — в authorized_keys root на ceph2/3
```text
```bash
# на хосте: раздать ключ cephadm на ceph2 и ceph3
PUB=$(vagrant ssh ceph1 -c 'sudo cat /etc/ceph/ceph.pub' | tr -d '\r')
for n in ceph2 ceph3; do
  vagrant ssh $n -c "sudo mkdir -p /root/.ssh && echo '$PUB' | sudo tee -a /root/.ssh/authorized_keys"
done
```text
```bash
# на ceph1, внутри: cephadm shell
ceph orch host add ceph2 192.168.61.12
ceph orch host add ceph3 192.168.61.13
ceph orch device ls --refresh                        # /dev/vdb Available=Yes на трёх нодах
ceph orch apply osd --all-available-devices
ceph -s; ceph osd tree                               # 3 osds: 3 up, 3 in; по OSD на хост

ceph osd pool create rbd
rbd pool init rbd
rbd create rbd/vol1 --size 2G
ceph osd pool get rbd size; ceph osd pool get rbd min_size   # 3 и 2
```text
```bash
# на ceph1 вне контейнера: клиент ядра
exit                                                 # из cephadm shell
apt-get install -y ceph-common                       # клиент 17.x из Ubuntu — для krbd достаточно
rbd map rbd/vol1 && rbd showmapped                   # /dev/rbd0
mkfs.xfs /dev/rbd0 && mkdir -p /mnt/rbd && mount /dev/rbd0 /mnt/rbd
dd if=/dev/urandom of=/mnt/rbd/blob bs=1M count=500 status=none && sha256sum /mnt/rbd/blob
while true; do date >> /mnt/rbd/writes.log; sync; sleep 1; done &   # «приложение пишет»
```text
```bash
# учения (в cephadm shell на ceph1; в отдельном окне: watch -n2 ceph -s)
ceph orch daemon stop osd.2                  # 1) один OSD
ceph health detail                           # OSD_DOWN, PG_DEGRADED (undersized+degraded)
ceph orch daemon start osd.2                 #    вернули → recovery → HEALTH_OK

# 2) потеря ноды: на хосте  vagrant halt ceph3 ; ждём > 10 минут (mon_osd_down_out_interval)
# 3) две ноды из трёх:      vagrant halt ceph2 ceph3  → что с writes.log? (min_size 2)
#    вернуть: vagrant up ceph2 ceph3 ; наблюдать peering → active+clean
```text
**Вариант с Rook на k3s** (вместо cephadm, на пересозданных VM с 6 ГБ): k3s на трёх нодах
(`--node-ip`, `--flannel-iface=eth1`), Rook v1.20.7 из `deploy/examples` (`crds.yaml`,
`common.yaml`, `csi-operator.yaml`, `operator.yaml`, `cluster.yaml` с `deviceFilter: "^vdb$"`),
пул `replicapool` + SC `rook-ceph-block`, toolbox для `ceph -s`. Под с PVC, удаление пода
`rook-ceph-osd-N` и наблюдение recovery. Подробно — [05_k8s_stateful.md](/storage/05-k8s-stateful).

### Требования
- [ ] Кластер из 3 нод: 3 MON, 1–2 MGR, 3 OSD по одному на хост; `ceph -s` — HEALTH_OK
- [ ] Объяснено, почему `--all-available-devices` взял только `vdb` (что делает диск «available»)
- [ ] RBD-том смонтирован, записан blob, контрольная сумма сохранена
- [ ] Отказ одного OSD: записан таймлайн состояний PG (`active+undersized+degraded` → recovery → `active+clean`) и время до HEALTH_OK
- [ ] Потеря ноды на > 10 минут: объяснено, почему при 3 хостах, `size 3` и failure domain `host` данные **не** перераспределяются, а PG остаются undersized
- [ ] Потеря двух нод: запись в `writes.log` встала — объяснено через `min_size 2`; после возврата нод запись продолжилась, blob совпал по sha256
- [ ] `ceph osd set noout` перед плановым выключением ноды и `unset` после — объяснено, зачем
- [ ] Бонус: CephFS (`ceph fs volume create cephfs`) смонтирован на двух нодах одновременно; RGW + `mc` к нему как к S3

### Критерии приёмки
```bash
cephadm shell -- ceph -s                    # HEALTH_OK, 3 mons, 3 osds: 3 up, 3 in, pgs active+clean
cephadm shell -- ceph osd tree              # 3 host, у каждого osd up
cephadm shell -- ceph df                    # пул rbd, USED ≈ 3 × данные
cephadm shell -- ceph orch ps --daemon-type osd
rbd showmapped && sha256sum /mnt/rbd/blob   # совпадает
```text
### Вопросы себе
- Почему в `ceph df` пул занимает втрое больше, чем записано, и сколько места останется при EC 2+1?
- Что было бы при `min_size 1` в сценарии «две ноды из трёх» и чем это опасно?
- Почему в проде кластер не заполняют выше ~70–80%, особенно при 4+ хостах?
- Что делал бы кластер, если бы часы на ceph3 ушли на секунду?

---

## 🧪 Лаба 4. PostgreSQL + WAL-G → MinIO, PITR после «DROP TABLE»

### Что делаем
На `stor1` ставим PostgreSQL 16, настраиваем непрерывную архивацию WAL и базовые бэкапы WAL-G в
бакет `pg-backups` из лабы 2, создаём «продовую» нагрузку, удаляем таблицу и восстанавливаем
базу **рядом с продом** на секунду раньше аварии. Теория —
[06_db_backup_replication.md](/storage/06-db-backup-replication), основа PITR —
[../Left/01_Databases/05_backup_restore.md](/databases/05-backup-restore).

### Каркас
```bash
vagrant snapshot save stor1 before_lab4 && vagrant ssh stor1
sudo apt-get install -y postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
sudo apt-get install -y postgresql-16

mkdir -p /tmp/walg && curl -fsSL -o /tmp/walg.tgz \
  https://github.com/wal-g/wal-g/releases/download/v3.0.9/wal-g-pg-ubuntu-22.04-amd64.tar.gz
tar -xzf /tmp/walg.tgz -C /tmp/walg && sudo install -m 0755 /tmp/walg/wal-g* /usr/local/bin/wal-g
wal-g --version
```text
```json
// /var/lib/postgresql/.walg.json  (владелец postgres, права 600)
{
  "WALG_S3_PREFIX": "s3://pg-backups/stor1",
  "AWS_ENDPOINT": "http://192.168.121.1:9000",
  "AWS_S3_FORCE_PATH_STYLE": "true",
  "AWS_REGION": "us-east-1",
  "AWS_ACCESS_KEY_ID": "pg-backup",
  "AWS_SECRET_ACCESS_KEY": "pg-backup-secret-123",
  "WALG_COMPRESSION_METHOD": "zstd",
  "PGHOST": "/var/run/postgresql"
}
```text
```conf
# /etc/postgresql/16/main/conf.d/wal-g.conf
wal_level = replica
archive_mode = on                         # требует рестарта
archive_command = 'wal-g wal-push %p'
archive_timeout = 60                      # на стенде — сегмент минимум раз в минуту
```text
```bash
sudo systemctl restart postgresql@16-main
sudo -u postgres psql -c "CREATE DATABASE shop"
sudo -u postgres psql shop -c "CREATE TABLE orders (id bigserial PRIMARY KEY, created_at timestamptz DEFAULT now(), amount int)"
sudo -u postgres wal-g backup-push /var/lib/postgresql/16/main
sudo -u postgres wal-g backup-list --detail

# нагрузка: заказ каждую секунду (второй терминал)
while true; do sudo -u postgres psql -q shop -c "INSERT INTO orders(amount) VALUES ($RANDOM)"; sleep 1; done

# авария: засеки время ДО и выполни
sudo -u postgres psql shop -c "SELECT now(), count(*) FROM orders"
sudo -u postgres psql shop -c "DROP TABLE orders"
sudo -u postgres psql -c "SELECT pg_switch_wal()"         # чтобы сегмент с DROP ушёл в архив
sudo -u postgres psql -c "SELECT last_archived_wal, failed_count FROM pg_stat_archiver"
```text
```bash
# восстановление РЯДОМ: отдельный кластер pitr на порту 5433
sudo pg_createcluster 16 pitr -p 5433
sudo -u postgres find /var/lib/postgresql/16/pitr -mindepth 1 -delete   # ⚠️ именно pitr, не main
sudo -u postgres wal-g backup-fetch /var/lib/postgresql/16/pitr LATEST
sudo tee /etc/postgresql/16/pitr/conf.d/recovery.conf >/dev/null <<'EOF'
restore_command = 'wal-g wal-fetch %f %p'
recovery_target_time = '2026-09-27 14:36:59+05'           # ← на секунду раньше DROP
recovery_target_action = 'pause'                        # встать на точке read-only: проверить и выгрузить
archive_mode = off                                         # ⚠️ не писать WAL в тот же префикс
EOF
sudo -u postgres touch /var/lib/postgresql/16/pitr/recovery.signal
sudo systemctl start postgresql@16-pitr
sudo tail -f /var/log/postgresql/postgresql-16-pitr.log   # «recovery stopping before commit …»
sudo -u postgres psql -p 5433 shop -c "SELECT max(created_at), count(*) FROM orders"

# вернуть таблицу в прод
sudo -u postgres pg_dump -p 5433 -t orders shop | sudo -u postgres psql -p 5432 shop
```text
> Часовой пояс в `recovery_target_time` — явно (`+05` для Казахстана с марта 2024 года,
> или `UTC`). Промахнулся — удали `pitr`, разверни копию заново и повтори с другой целью.

**Бонус: pgBackRest.** pgBackRest ходит в S3 **только по TLS** — сначала TLS для MinIO (лаба 2,
бонус). Конфиг `/etc/pgbackrest/pgbackrest.conf` (как в теме 06): `repo1-type=s3`, `repo1-s3-endpoint=192.168.121.1`,
`repo1-storage-port=9000`, `repo1-s3-bucket=pg-backups`, `repo1-s3-region=us-east-1`,
`repo1-s3-uri-style=path`, `repo1-storage-verify-tls=n` (или `repo1-storage-ca-file`),
`repo1-path=/pgbackrest`, `repo1-retention-full=2`, секция `[main]` с `pg1-path`. Дальше
`stanza-create` → `check` → `--type=full backup` → `restore --delta --type=time "--target=…"
--target-action=pause --archive-mode=off` в кластер `pitr`.

### Требования
- [ ] Архивация работает: `pg_stat_archiver.failed_count = 0`, в бакете появляются сегменты WAL
- [ ] Базовый бэкап в `backup-list`; `wal-g wal-verify integrity timeline` — OK
- [ ] PITR в **отдельный** кластер `pitr`, прод не останавливался; в восстановленной таблице последняя строка — за секунду до DROP
- [ ] Посчитаны фактические RPO (сколько строк потеряно между целью и DROP) и RTO (от команды до данных в проде)
- [ ] Объяснено, почему в восстановленном кластере `archive_mode = off` и что было бы иначе (таймлайны в том же префиксе)
- [ ] Показано, что учётка `pg-backup` без права удаления: `wal-g delete retain FULL 1` без `--confirm` (dry run) и с ним — что произошло
- [ ] Записано, как проверять бэкапы регулярно (restore-test, `pg_verifybackup` для basebackup, `wal-verify`, row count)
- [ ] Бонус: тот же PITR через pgBackRest с TLS к MinIO

### Критерии приёмки
```bash
sudo -u postgres psql -c "SELECT archived_count, failed_count, last_archived_time FROM pg_stat_archiver"
sudo -u postgres wal-g backup-list --detail
sudo -u postgres wal-g wal-verify integrity timeline
mc ls --recursive local/pg-backups/stor1/ | head       # basebackups_005/ и wal_005/
sudo -u postgres psql -p 5432 shop -c "SELECT count(*) FROM orders"   # таблица вернулась в прод
pg_lsclusters                                           # main online, pitr online (потом — удалить)
```text
### Вопросы себе
- Почему реплика не спасла бы от `DROP TABLE`, а PITR спасает?
- Что будет с PITR, если `archive_command` неделю молча падал? Какой алерт это ловит?
- Сколько WAL придётся доиграть, если базовый бэкап раз в неделю, а авария в конце недели? Как это влияет на RTO?
- Где должны лежать ключи к `pg-backups`, чтобы шифровальщик на `stor1` не удалил бэкапы?

---

## 🧪 Лаба 5. Velero: namespace с PVC → MinIO → удалить → восстановить

### Что делаем
В kind-кластере `devops` поднимаем namespace с StatefulSet и томом, ставим Velero с MinIO,
бэкапим namespace вместе с данными тома (Kopia), удаляем namespace и восстанавливаем. Потом —
восстановление рядом (другой namespace) и расписание. Теория — [07_velero_dr.md](/storage/07-velero-dr).

### Каркас
```yaml
# lab5/shop.yaml
apiVersion: v1
kind: Namespace
metadata: { name: shop }
---
apiVersion: v1
kind: Service
metadata: { name: web, namespace: shop }
spec:
  clusterIP: None
  selector: { app: web }
  ports: [{ port: 80, name: http }]
---
apiVersion: apps/v1
kind: StatefulSet
metadata: { name: web, namespace: shop }
spec:
  serviceName: web
  replicas: 1
  selector: { matchLabels: { app: web } }
  template:
    metadata: { labels: { app: web } }
    spec:
      containers:
        - name: web
          image: busybox:1.36
          command: ["sh", "-c", "sleep infinity"]
          volumeMounts: [{ name: data, mountPath: /data }]
  volumeClaimTemplates:
    - metadata:
        name: data
        annotations: { volumeType: local }     # PV типа local: FSB видит его, hostPath — нет
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: standard
        resources: { requests: { storage: 1Gi } }
```text
```bash
kubectl apply -f lab5/shop.yaml && kubectl -n shop wait --for=condition=Ready pod/web-0
kubectl get pv -o custom-columns=NAME:.metadata.name,LOCAL:.spec.local.path,HOSTPATH:.spec.hostPath.path
kubectl -n shop exec web-0 -- sh -c 'date > /data/stamp; head -c 50000000 /dev/urandom > /data/blob; sha256sum /data/blob' \
  | tee lab5/expected.txt

# MinIO: бакет и пользователь velero (политика — 07, раздел 5), сеть kind
mc mb --with-versioning local/velero
docker network connect kind minio 2>/dev/null || true
MINIO_IP=$(docker inspect -f '&#123;&#123;(index .NetworkSettings.Networks "kind").IPAddress&#125;&#125;' minio)

# Velero: установка — команда из 07, раздел 5 (--use-node-agent, s3Url=http://$MINIO_IP:9000)
velero backup-location get

velero backup create shop-1 --include-namespaces shop --default-volumes-to-fs-backup --wait
velero backup describe shop-1 --details | sed -n '/Pod Volume Backups/,$p'

kubectl delete ns shop
time velero restore create shop-r1 --from-backup shop-1 --wait
kubectl -n shop exec web-0 -- sha256sum /data/blob          # сравни с lab5/expected.txt

velero restore create shop-check --from-backup shop-1 --namespace-mappings shop:shop-check --wait
velero schedule create shop-hourly --schedule="0 * * * *" --include-namespaces shop --ttl 24h0m0s
```text
### Требования
- [ ] Пароль Kopia-репозитория (`velero-repo-credentials`) заменён **до** первого бэкапа и сохранён вне кластера
- [ ] BSL `Available`; бэкап `shop-1` — `Completed`, в `describe --details` том `data` в Pod Volume Backups
- [ ] После `kubectl delete ns shop` и restore данные на месте: sha256 совпала; время restore записано как RTO
- [ ] Восстановление в `shop-check` рядом с `shop`, проверка и удаление оформлены скриптом `restore-check.sh` с ненулевым кодом при расхождении
- [ ] Эксперимент без аннотации `volumeType: local`: бэкап «успешный», а данных нет — найдено предупреждение в `velero backup logs`
- [ ] Schedule создан; предложены два алерта: возраст последнего успешного бэкапа и неуспешные статусы
- [ ] `docs/dr.md` на одну страницу: сценарии, RPO/RTO (цель и замер), где пароль репозитория и ключи MinIO, порядок восстановления
- [ ] Бонус: второй kind-кластер `dr` с тем же бакетом, паролем и BSL `ReadOnly`; restore `shop-1` туда

### Критерии приёмки
```bash
velero backup-location get                         # default  Available
velero backup get                                  # shop-1  Completed
kubectl -n velero get podvolumebackups             # Completed для тома data
velero restore get                                 # shop-r1, shop-check  Completed
kubectl -n shop exec web-0 -- sha256sum /data/blob # = lab5/expected.txt
mc ls local/velero/                                # backups/  kopia/
./restore-check.sh shop-1; echo "exit=$?"          # exit=0
```text
### Вопросы себе
- Почему Velero'ом не бэкапят базу PostgreSQL как основной механизм?
- Что изменится, если хранилище — Rook-Ceph с CSI-снапшотами: какой флаг обязателен, чтобы данные уехали в MinIO?
- Что будет в DR-кластере, если оставить BSL в режиме ReadWrite?
- Какие шаги в `docs/dr.md` оказались самыми долгими и как их сократить?

---

## 🏁 Что должно остаться после блока

```text
storage-lab/                         # репозиторий стендов и лаб
├── stands/storage-lab/Vagrantfile   # stor1 с 6 доп. дисками
├── stands/ceph-lab/Vagrantfile      # ceph1..3 с сырыми дисками
├── minio/docker-compose.yml         # + policies/*.json, certs/ (без private.key в git!)
├── lab1/notes.md                    # LVM, pvmove, growpart, mdadm — команды и выводы
├── lab2/check.sh                    # проверки версий, lifecycle, прав
├── lab3/notes.md                    # таймлайн ceph -s при отказах
├── lab4/pitr.md                     # PITR: цель, фактические RPO/RTO
├── lab5/shop.yaml, restore-check.sh
└── docs/dr.md                       # DR-план с замерами
```text
Это превращает ответ «знаю, что такое LVM, Ceph и Velero» в «вот как я менял диск под
нагрузкой, вот таймлайн восстановления Ceph после отказа ноды, вот PITR с замеренным RPO
и restore namespace с проверкой контрольной суммы».

➡️ Дальше: [09_interview.md](/softskills/09-interview)
