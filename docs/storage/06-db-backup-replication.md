---
title: "06. Бэкапы и репликация БД: PITR, Patroni, CloudNativePG"
description: "Блок → Хранилища и stateful → тема 06. Опирается на"
---

# 06. Бэкапы и репликация БД: PITR, Patroni, CloudNativePG

> Блок → Хранилища и stateful → тема 06. Опирается на
> [../Left/01_Databases/05_backup_restore.md](/databases/05-backup-restore) (pg_dump,
> pg_basebackup, PITR с `cp`, RPO/RTO, 3-2-1),
> [../Left/01_Databases/06_replication.md](/databases/06-replication) (streaming, слоты,
> sync/async, схема Patroni), [03_nfs_minio.md](/storage/03-nfs-minio) (MinIO, политики, lock) и
> [05_k8s_stateful.md](/storage/05-k8s-stateful) (операторы, тома).
>
> **После темы ты умеешь:** настроить непрерывный бэкап PostgreSQL в S3 (WAL-G или pgBackRest
> с MinIO), восстановить базу на момент времени после `DROP TABLE` — рядом с продом, а не
> поверх; выбрать retention и понять, как он сочетается с object lock; доказать, что бэкап
> восстанавливается; эксплуатировать Patroni через `patronictl`; поднять PostgreSQL в Kubernetes
> через CloudNativePG с бэкапом плагином barman-cloud; назвать RPO/RTO любой схемы.

---

## 🗺️ Карта темы

```text
 PostgreSQL (primary) ──archive_command──► WAL-сегменты ──┐
        │                                                 ├──► S3 (MinIO, бакет pg-backups)
        └── base backup: full / diff / incr / delta ──────┘     версии · lock · lifecycle
                                                                      │
      ┌─────────────────────────────── восстановление ────────────────┘
      ▼
 base backup + доигрывание WAL до recovery_target_time ──► PITR (в ОТДЕЛЬНЫЙ инстанс)
 ─────────────────────────────────────────────────────────────────────────────────────
 доступность: Patroni + etcd + HAProxy (VM)   ·   CloudNativePG (Kubernetes)
 доверие: мониторинг архивации · verify · регулярный restore-test · RPO/RTO замерены
```text
---

## 1. Что добавляем к блоку «Базы»

| Уже есть в [05_backup_restore](/databases/05-backup-restore) / [06_replication](/databases/06-replication) | Здесь |
|----------------------------------------------------|-------|
| PITR с `cp` в локальный каталог | WAL-G и pgBackRest → S3 (MinIO), шифрование, сжатие |
| «WAL-G: backup-push, backup-list, delete retain» | полный конфиг, права в бакете, delta, retention vs object lock |
| «проверяйте восстановление» | как именно: verify, checksums, restore-test с проверками |
| схема Patroni, promote, pg_rewind | `patroni.yml`, `patronictl`, DCS, watchdog, HAProxy, бэкапы в кластере Patroni |
| «операторы: CloudNativePG, Zalando» | CNPG: Cluster, плагин barman-cloud, ScheduledBackup, PITR новым кластером |

---

## 2. Непрерывный бэкап: как устроен

```text
 время ─────────────────────────────────────────────────────────────────────►
 full ●──────────── delta ● ──────── delta ● ─────────── full ● ─────────────
      └─ WAL ─ WAL ─ WAL ─ WAL ─ WAL ─ WAL ─ WAL ─ WAL ─ WAL ─ WAL ─ WAL ──►  (каждые ≤ archive_timeout)
      ▲ окно восстановления начинается с САМОГО СТАРОГО base backup, для которого есть все WAL
```text
| Тип | Что содержит | Восстановление |
|-----|--------------|----------------|
| full | все файлы PGDATA | только он + WAL |
| diff (pgBackRest) | изменения с последнего full | full + diff + WAL |
| incr (pgBackRest) / delta (WAL-G) | изменения с последнего любого бэкапа | цепочка + WAL |

- **RPO** такой схемы = неотправленный WAL: при `archive_timeout = 60` — до минуты, плюс
  текущий незакрытый сегмент при полной потере сервера. Хочешь почти ноль — синхронная реплика (раздел 12).
- **RTO** = скачать base backup + применить WAL с момента бэкапа. 500 ГБ через 1 Гбит/с —
  больше часа только на скачивание; поэтому full делают чаще, чем «раз в месяц».
- WAL удалять можно только вместе с base backup, которому они нужны — этим занимается
  retention инструмента, а не ручной `rm`.

---

## 3. WAL-G → MinIO (стенд: VM `stor1`)

Бакет и пользователь в MinIO (на хосте, клиент — из [03_nfs_minio.md](/storage/03-nfs-minio)):

```bash
mc mb --with-versioning local/pg-backups
mc admin user add local pg-backup 'pg-backup-secret-123'
cat > files/pg-backup-rw.json <<'EOF'
{ "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": ["arn:aws:s3:::pg-backups"] },
    { "Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": ["arn:aws:s3:::pg-backups/*"] } ] }
EOF
mc admin policy create local pg-backup-rw /files/pg-backup-rw.json
mc admin policy attach local pg-backup-rw --user pg-backup
```text
> ⚖️ **Права на удаление — осознанный выбор.** Без `s3:DeleteObject` взломанный сервер БД не
> уничтожит бэкапы, но и `wal-g delete retain` не сработает. Два рабочих варианта:
> (а) retention делает **сервер** — lifecycle-правило бакета (`mc ilm rule add … --expire-days`),
> срок строго больше «окна восстановления + интервал full», иначе lifecycle съест WAL, нужные
> живому бэкапу; (б) у сервера БД только запись, а `delete retain` запускается **отдельным**
> пользователем с правом удаления с другой машины (CI/админ-хост). Плюс versioning и object lock
> как последняя линия.

На `stor1` (PostgreSQL 16 из PGDG, как в блоке «Базы»):

```bash
curl -fsSLO https://github.com/wal-g/wal-g/releases/download/v3.0.9/wal-g-pg-ubuntu-22.04-amd64.tar.gz
tar xzf wal-g-pg-ubuntu-22.04-amd64.tar.gz
sudo install -m 0755 wal-g-pg-ubuntu-22.04-amd64 /usr/local/bin/wal-g   # имя файла внутри — проверь `tar tzf`
wal-g --version
```text
```json
// /var/lib/postgresql/.walg.json — $HOME пользователя postgres, WAL-G читает его по умолчанию
{
  "WALG_S3_PREFIX": "s3://pg-backups/stor1",
  "AWS_ENDPOINT": "http://192.168.121.1:9000",
  "AWS_S3_FORCE_PATH_STYLE": "true",
  "AWS_REGION": "us-east-1",
  "AWS_ACCESS_KEY_ID": "pg-backup",
  "AWS_SECRET_ACCESS_KEY": "pg-backup-secret-123",
  "WALG_COMPRESSION_METHOD": "zstd",
  "WALG_DELTA_MAX_STEPS": "6",
  "PGHOST": "/var/run/postgresql"
}
```text
```bash
sudo chown postgres:postgres /var/lib/postgresql/.walg.json && sudo chmod 600 /var/lib/postgresql/.walg.json
```text
```conf
# /etc/postgresql/16/main/conf.d/backup.conf
wal_level = replica
archive_mode = on                          # рестарт
archive_command = 'wal-g wal-push %p'
archive_timeout = 60                       # RPO ≈ минута при малой записи
```text
```bash
sudo systemctl restart postgresql@16-main
sudo -u postgres psql -c "SELECT pg_switch_wal();"            # форсировать сегмент
sudo -u postgres psql -xc "SELECT archived_count, failed_count, last_archived_wal, last_failed_wal FROM pg_stat_archiver;"
sudo -u postgres wal-g backup-push /var/lib/postgresql/16/main  # первый — full, дальше delta (до 6 подряд)
sudo -u postgres wal-g backup-list --detail
sudo -u postgres wal-g wal-verify integrity timeline            # нет ли дыр в цепочке WAL
```text
Полезное сверх базы: `WALG_LIBSODIUM_KEY` — шифрование на клиенте (ключ хранится **не** рядом
с бэкапом); `WALG_UPLOAD_CONCURRENCY` — параллельная загрузка; `wal-g backup-mark &lt;backup&gt;` —
«вечный» бэкап, который retention не тронет; `wal-g delete retain FULL 7` — без `--confirm`
только показывает, что удалит. Бэкап можно снимать с реплики — нагрузка уходит с primary.

---

## 4. pgBackRest → MinIO (обязательно TLS)

pgBackRest 2.59.1 для S3 **всегда** использует TLS: MinIO по голому `http` не подойдёт.
`repo1-storage-verify-tls=n` отключает только проверку сертификата, а не сам TLS. На стенде —
самоподписанный сертификат MinIO (`--certs-dir`, [03_nfs_minio.md](/storage/03-nfs-minio)), в проде —
нормальный сертификат и `repo1-storage-ca-file`.

```ini
# /etc/pgbackrest/pgbackrest.conf
[global]
repo1-type=s3
repo1-s3-endpoint=192.168.121.1
repo1-storage-port=9000
repo1-s3-bucket=pg-backups
repo1-s3-region=us-east-1
repo1-s3-key=pg-backup
repo1-s3-key-secret=pg-backup-secret-123
repo1-s3-uri-style=path            # MinIO: адрес бакета в пути, а не в имени хоста
repo1-storage-verify-tls=n         # ⚠️ только стенд; старое имя — repo1-s3-verify-tls
repo1-path=/pgbackrest
repo1-retention-full=2             # хранить 2 полных (+ их diff/incr и WAL)
repo1-cipher-type=aes-256-cbc      # шифрование на клиенте
repo1-cipher-pass=long-random-passphrase
compress-type=zst
process-max=2
start-fast=y
archive-async=y                    # WAL уходят пачками из spool-path
log-level-console=info

[main]
pg1-path=/var/lib/postgresql/16/main
```text
```conf
archive_command = 'pgbackrest --stanza=main archive-push %p'
```text
```bash
sudo -u postgres pgbackrest --stanza=main stanza-create
sudo -u postgres pgbackrest --stanza=main check              # архивация и доступ к репозиторию
sudo -u postgres pgbackrest --stanza=main --type=full backup  # потом --type=diff / --type=incr
sudo -u postgres pgbackrest --stanza=main info
sudo -u postgres pgbackrest --stanza=main verify              # целостность файлов репозитория
```text
> ℹ️ Статус проекта: в апреле 2026 автор объявил о прекращении поддержки, в мае 2026 развитие
> продолжилось на деньги группы спонсоров (AWS, Supabase, Percona, Dalibo и др.). Для
> инструмента, которому доверяешь бэкапы, такие новости стоит отслеживать.

---

## 5. Что выбрать

| | WAL-G | pgBackRest | barman / barman-cloud |
|---|---|---|---|
| Язык, форма | Go, один бинарь | C, пакет | Python; barman-cloud — CLI для S3 |
| S3 по http | да | нет, только TLS | да |
| Инкременты | delta (по страницам) | diff + incr, блочный incr | инкрементов в облаке нет |
| Параллельность | загрузка/выгрузка | backup, restore, архивация (async) | ограниченно |
| Проверка | `wal-verify` | `verify`, checksums страниц при бэкапе | `barman check` |
| Где встречается | Zalando/Spilo, много self-hosted | Crunchy PGO, Percona Operator | CloudNativePG (плагин barman-cloud) |

Правило: бери то, что умеет твой оператор/платформа, и **одно** на всю компанию — тогда
runbook восстановления один.

---

## 6. PITR после `DROP TABLE` — рядом с продом

**Шаг 0. Найти момент.** Лучше всего — логи (`log_statement = 'ddl'` пишет время каждого DDL).
Если логов нет — WAL: скачай сегменты за нужный период и ищи коммит с удалёнными файлами
отношений:

```bash
sudo -u postgres wal-g wal-fetch 000000010000000000000023 /tmp/wal/000000010000000000000023
/usr/lib/postgresql/16/bin/pg_waldump /tmp/wal/000000010000000000000023 --rmgr=Transaction | grep 'rels:'
# … tx: 812 … desc: COMMIT 2026-09-27 14:37:02 +05; rels: base/16384/16390 …
```text
Точно по транзакции: `recovery_target_xid = '812'` + `recovery_target_inclusive = off` —
остановиться **перед** её коммитом. По времени — `recovery_target_time` на секунду раньше.

**Шаг 1–4. Восстановить во второй инстанс на той же VM** (порт 5433; прод работает):

```bash
sudo pg_createcluster 16 restore --port 5433          # каталоги …/16/restore, сервис postgresql@16-restore
sudo systemctl stop postgresql@16-restore
sudo -u postgres find /var/lib/postgresql/16/restore -mindepth 1 -delete   # ⚠️ именно restore, не main; каталог (0700) оставляем
sudo -u postgres wal-g backup-fetch /var/lib/postgresql/16/restore LATEST   # base backup ДО аварии
```text
```conf
# /etc/postgresql/16/restore/conf.d/recovery.conf
restore_command = 'wal-g wal-fetch %f %p'
recovery_target_time = '2026-09-27 14:37:01+05'
recovery_target_action = 'pause'   # встать на точке read-only и дать посмотреть
archive_mode = off                 # ⭐ иначе копия начнёт писать свои WAL в архив прода
```text
```bash
sudo -u postgres touch /var/lib/postgresql/16/restore/recovery.signal
sudo systemctl start postgresql@16-restore
sudo -u postgres psql -p 5433 -c "SELECT pg_is_in_recovery(), count(*) FROM orders;"
# данные есть → выгрузить таблицу и перенести в прод
sudo -u postgres pg_dump -p 5433 -d shop -t orders -Fc -f /tmp/orders.dump
sudo -u postgres pg_restore -p 5432 -d shop /tmp/orders.dump
```text
`LATEST` подходит, только если последний бэкап снят **до** аварии; иначе укажи имя из
`backup-list` (или `--target` сама выберет бэкап в pgBackRest). Промахнулся с точкой — копия
не promote'нута, можно пересоздать с другой целью.

С pgBackRest то же одной командой (он сам пропишет `restore_command` и `recovery.signal`):

```bash
sudo -u postgres pgbackrest --stanza=main --pg1-path=/var/lib/postgresql/16/restore --delta \
  --type=time "--target=2026-09-27 14:37:01+05" --target-action=pause --archive-mode=off restore
```text
**Таймлайны.** После promote восстановленная база начинает **новый timeline** (2, 3, …) и пишет
`.history`-файл. По умолчанию `recovery_target_timeline = 'latest'`. Если восстановленный
инстанс с `archive_mode = on` promote'нуть в тот же префикс — в архиве появятся ветки,
и следующее восстановление «на последний timeline» пойдёт не туда. Отсюда правило:
учебные и расследовательские копии архивацию не включают.

---

## 7. Retention и хранение

| Вопрос | Ответ |
|--------|-------|
| count или time? | `retention-full-type=count` (N полных) предсказуем по месту; `time` (дни) — по окну восстановления. Требование бизнеса обычно в днях |
| Что с WAL? | удаляются вместе с самым старым оставленным base backup |
| Lifecycle бакета или retention инструмента? | инструмент знает зависимости бэкапов; lifecycle — нет. Lifecycle — как страховка с большим запасом |
| Versioning | удаление инструментом ставит delete marker; реальную очистку старых версий делает lifecycle `--noncurrent-expire-days` |
| Object lock | срок lock ≤ retention: иначе инструмент не сможет удалить устаревшее, бакет будет расти |
| Долгое хранение | отдельный месячный full с `backup-mark` / отдельный репозиторий (`repo2` в pgBackRest) |

---

## 8. Как доказать, что бэкап рабочий

```text
 уровень 5  учения: восстановить прод целиком по runbook, замерить RTO        раз в квартал
 уровень 4  автоматический restore-test: последний бэкап → временный инстанс
            → pg_amcheck, count(*) ключевых таблиц, свежесть max(created_at)   раз в неделю
 уровень 3  проверка файлов: pgbackrest verify / wal-g wal-verify /
            pg_verifybackup (для pg_basebackup)                                ежедневно
 уровень 2  архивация идёт: pg_stat_archiver.failed_count, last_archived_time   алерт
 уровень 1  бэкап есть: возраст последнего УСПЕШНОГО бэкапа < 25 ч              алерт
```text
- `pg_verifybackup` (PG13+) сверяет бэкап `pg_basebackup` с его `backup_manifest` и проверяет
  WAL; в PG16 — только plain-формат, tar поддерживается с PG18.
- **Контрольные суммы данных**: `pg_checksums --check` (кластер остановлен) ловит битые
  страницы; в PG18 `initdb` включает checksums по умолчанию, в старых кластерах — `pg_checksums --enable` офлайн.
- `pg_amcheck -d shop` проверяет индексы и кучи на логическую порчу — хорошо в restore-test.
- Самая честная проверка — запрос приложения к восстановленной базе: «последний заказ за
  последние N минут существует».

---

## 9. Patroni: эксплуатация

```yaml
# /etc/patroni/patroni.yml (узел pg1; на pg2/pg3 меняются name и адреса)
scope: shop-pg
name: pg1
restapi: { listen: 0.0.0.0:8008, connect_address: 10.0.1.11:8008 }
etcd3:
  hosts: 10.0.1.21:2379,10.0.1.22:2379,10.0.1.23:2379
bootstrap:
  dcs:                                   # динамическая конфигурация, живёт в DCS
    ttl: 30                              # срок лидер-ключа
    loop_wait: 10
    retry_timeout: 10                    # loop_wait + 2 × retry_timeout ≤ ttl
    maximum_lag_on_failover: 1048576     # 1 МБ: реплика с бо́льшим лагом не станет лидером
    postgresql:
      use_pg_rewind: true
      use_slots: true
      parameters: { archive_mode: "on", archive_command: "wal-g wal-push %p", archive_timeout: 60 }
postgresql:
  listen: 0.0.0.0:5432
  connect_address: 10.0.1.11:5432
  data_dir: /var/lib/postgresql/16/main
  bin_dir: /usr/lib/postgresql/16/bin
  authentication:
    superuser: { username: postgres, password: "…" }
    replication: { username: repl, password: "…" }
watchdog: { mode: automatic, device: /dev/watchdog }
```text
Как принимается решение: лидер каждые `loop_wait` продлевает ключ в DCS с TTL. Ключ истёк —
реплики с лагом ≤ `maximum_lag_on_failover` устраивают гонку за ключ, победитель — promote,
новый timeline. Потерял связь с DCS сам лидер — он **demote'ится** в read-only (иначе
split-brain), если не включён `failsafe_mode`. Watchdog перезагружает узел, если Patroni
завис и не успел снять роль лидера.

```bash
patronictl -c /etc/patroni/patroni.yml list                              # роли, TL, лаг
patronictl -c /etc/patroni/patroni.yml switchover shop-pg --leader pg1 --candidate pg2 --force
patronictl -c /etc/patroni/patroni.yml failover shop-pg --candidate pg2  # когда лидера нет/болен
patronictl -c /etc/patroni/patroni.yml edit-config                       # параметры PG — только так
patronictl -c /etc/patroni/patroni.yml show-config
patronictl -c /etc/patroni/patroni.yml restart shop-pg pg2               # pending restart
patronictl -c /etc/patroni/patroni.yml reinit shop-pg pg3                # пересоздать реплику с нуля
patronictl -c /etc/patroni/patroni.yml pause                             # обслуживание без автo-failover
```text
```text
# haproxy.cfg: 5000 → только лидер, 5001 → реплики
listen primary
    bind *:5000
    option httpchk GET /primary
    http-check expect status 200
    default-server inter 3s fall 3 rise 2 on-marked-down shutdown-sessions
    server pg1 10.0.1.11:5432 check port 8008
    server pg2 10.0.1.12:5432 check port 8008
listen replicas
    bind *:5001
    option httpchk GET /replica
    server pg1 10.0.1.11:5432 check port 8008
    server pg2 10.0.1.12:5432 check port 8008
```text
(в Patroni 4.x эндпоинт `/master` убран — только `/primary`, `/leader`, `/replica`, `/health`.)

Бэкапы в кластере Patroni: `archive_command` одинаковый на всех узлах; с `archive_mode = on`
архивирует только текущий лидер, после failover — новый. Base backup — с реплики
(WAL-G на standby, в pgBackRest — `backup-standby=y`). Раз в квартал — плановый `switchover`
как учение.

---

## 10. CloudNativePG: PostgreSQL в Kubernetes

CNPG не использует Patroni: лидера выбирает сам оператор через API Kubernetes, реплики —
streaming replication, сервисы `&lt;name&gt;-rw` (primary), `-ro` (реплики), `-r` (любой).

```bash
kubectl apply --server-side -f \
  https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.30/releases/cnpg-1.30.1.yaml
kubectl rollout status deployment -n cnpg-system cnpg-controller-manager
# бэкапы — плагином (нужен cert-manager; в проде пинь версию)
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml
kubectl apply -f https://github.com/cloudnative-pg/plugin-barman-cloud/releases/download/v0.15.0/manifest.yaml
kubectl -n cnpg-system rollout status deploy/barman-cloud
```text
> ⚠️ Встроенный `spec.backup.barmanObjectStore` устарел с 1.26 и будет удалён в 1.31. Новые
> кластеры — сразу с плагином barman-cloud (ObjectStore CR), старые — мигрировать.

```yaml
apiVersion: barmancloud.cnpg.io/v1
kind: ObjectStore
metadata: { name: minio-store, namespace: db }
spec:
  retentionPolicy: "30d"
  configuration:
    destinationPath: s3://cnpg-backups/
    endpointURL: http://&lt;MINIO_IP&gt;:9000          # IP контейнера minio в сети kind
    s3Credentials:
      accessKeyId:     { name: minio-creds, key: ACCESS_KEY_ID }
      secretAccessKey: { name: minio-creds, key: ACCESS_SECRET_KEY }
    wal: { compression: gzip }
---
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata: { name: pg-main, namespace: db }
spec:
  instances: 3
  storage: { size: 2Gi, storageClass: standard }
  plugins:
    - name: barman-cloud.cloudnative-pg.io
      isWALArchiver: true
      parameters: { barmanObjectName: minio-store }
---
apiVersion: postgresql.cnpg.io/v1
kind: ScheduledBackup
metadata: { name: pg-main-daily, namespace: db }
spec:
  schedule: "0 0 2 * * *"                         # 6 полей: секунды первые
  backupOwnerReference: self
  cluster: { name: pg-main }
  method: plugin
  pluginConfiguration: { name: barman-cloud.cloudnative-pg.io }
```text
```bash
docker network connect kind minio
MINIO_IP=$(docker inspect -f '&#123;&#123;(index .NetworkSettings.Networks "kind").IPAddress&#125;&#125;' minio)
kubectl -n db create secret generic minio-creds \
  --from-literal=ACCESS_KEY_ID=cnpg --from-literal=ACCESS_SECRET_KEY='cnpg-secret-123'
kubectl cnpg status pg-main -n db                 # krew-плагин: роли, лаг, архивация WAL
kubectl cnpg backup pg-main -n db --method=plugin --plugin-name=barman-cloud.cloudnative-pg.io
kubectl -n db get backups
kubectl cnpg promote pg-main pg-main-2 -n db      # switchover на конкретный инстанс
```text
**PITR = новый кластер** из того же хранилища (исходный не трогаем):

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata: { name: pg-main-restore, namespace: db }
spec:
  instances: 1
  storage: { size: 2Gi }
  bootstrap:
    recovery:
      source: origin
      recoveryTarget: { targetTime: "2026-09-27T09:37:01Z" }
  externalClusters:
    - name: origin
      plugin:
        name: barman-cloud.cloudnative-pg.io
        parameters: { barmanObjectName: minio-store, serverName: pg-main }
```text
Архивацию у восстановленного кластера не включай в тот же `serverName` — оператор и так
проверяет, что WAL-архив назначения пуст, и откажется писать поверх чужого.

---

## 11. Другие stateful-системы

**Redis** (база — в [../Left/01_Databases/09_redis_mongo_clickhouse.md](/databases/09-redis-mongo-clickhouse)):
- AOF: `appendfsync everysec` (по умолчанию, теряешь до ~1 с), `always` (медленно), `no` (решает ОС).
  С `aof-use-rdb-preamble yes` переписанный AOF начинается с RDB-снимка — быстрый старт.
- `BGSAVE` и переписывание AOF делают `fork`: при активной записи copy-on-write может почти
  удвоить память — отсюда OOM «на ровном месте» и совет `vm.overcommit_memory = 1`.
- Бэкап = копия `dump.rdb` после успешного `BGSAVE` (`LASTSAVE`) в S3. Реплика не бэкап:
  `FLUSHALL` уедет и на неё. Сначала реши, кэш это (бэкап не нужен) или база.

**Kafka** ([../Left/05_Queues/03_kafka_ops.md](/queues/03-kafka-ops)): `retention.ms/bytes`
и compaction — это политика хранения, а не бэкап. Надёжность — `replication.factor=3`,
`min.insync.replicas=2`, `acks=all`; DR — второй кластер и MirrorMaker 2 (асинхронно, с
трансляцией offset'ов). Бэкапить отдельно стоит конфигурацию: топики, ACL, схемы.

---

## 12. RPO/RTO для БД

| Механизм | RPO | RTO | От чего защищает |
|----------|-----|-----|------------------|
| Ночной `pg_dump` | до 24 ч | часы (зависит от размера) | логические ошибки, потеря всего |
| Base backup + архив WAL в S3 | ≈ `archive_timeout` (минута) | скачать + доиграть WAL: десятки минут–часы | всё, включая `DROP TABLE` (PITR) |
| Асинхронная реплика + Patroni/CNPG | секунды (лаг) | ≈ 30–60 с автоматически | отказ узла; **не** ошибки людей |
| Синхронная реплика (`ANY 1 (…)`) | 0 | ≈ 30–60 с | отказ узла без потерь; **не** ошибки |
| Отложенная реплика (`recovery_min_apply_delay = '1h'`) | — | минуты (promote до точки) | ошибка, замеченная в пределах часа |
| Снапшот тома (LVM/CSI) | интервал снапшотов | минуты | быстрый откат; **не** потеря хранилища |

Прод обычно = реплика (доступность) + base backup/WAL в S3 вне площадки (ошибки и катастрофы)
+ restore-test (доверие).

---

## 13. Грабли

| Грабля | Последствие | Правильно |
|--------|-------------|-----------|
| pgBackRest на MinIO по http | `TLS error … wrong version number` | TLS на MinIO, verify-tls=n только на стенде |
| Нет `AWS_S3_FORCE_PATH_STYLE` у WAL-G | запросы на `pg-backups.192.168…` — ошибки DNS | path-style для MinIO |
| Восстановленная копия с `archive_mode = on` | чужие timeline в архиве прода | `archive_mode = off` / `--archive-mode=off` |
| `backup-fetch LATEST` после аварии | бэкап уже после `DROP` — таблицы нет | выбрать бэкап до точки |
| Lifecycle короче окна WAL | дыры в цепочке, PITR невозможен | lifecycle с запасом, `wal-verify` |
| Ключ шифрования в том же бакете | шифрование бессмысленно | ключ в Vault/менеджере секретов |
| Параметры PG правят в `postgresql.conf` на узле Patroni | Patroni перезапишет | `patronictl edit-config` |
| Нечётное число узлов забыли (2 узла etcd) | потеря одного — нет кворума, лидер demote | 3 или 5 узлов DCS |
| CNPG с `barmanObjectStore` в новых кластерах | миграция при апгрейде до 1.31 | сразу плагин barman-cloud |
| Бэкап «зелёный», restore-test нет | узнаешь в день аварии | уровни 1–5 из раздела 8 |

---

## 💼 Как это в DevOps

- Бэкап БД — сервис с SLO: «RPO ≤ 5 минут, RTO ≤ 1 часа, restore-test еженедельно зелёный».
  Цифры — в README и в `docs/dr.md` ([07_velero_dr.md](/storage/07-velero-dr)).
- Алерты: возраст последнего успешного бэкапа, `pg_stat_archiver.failed_count`, размер `pg_wal`,
  лаг реплик, статус restore-test. Все — с `runbook_url`.
- Права: сервер БД пишет, но не удаляет; retention и удаление — отдельная учётка; бакет
  с versioning и object lock; копия в другом месте (второй MinIO/облако) — off-site.
- Перед мажорным апгрейдом, миграцией схемы и апгрейдом оператора — свежий full и проверка,
  что точка восстановления есть (`backup-list`, `info`, `kubectl get backups`).
- Раз в квартал — `switchover` в Patroni/CNPG в рабочее время: приложение должно пережить
  смену лидера без ручных действий.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Архивация WAL-G | `archive_command = 'wal-g wal-push %p'` |
| Бэкап / список | `wal-g backup-push $PGDATA` / `wal-g backup-list --detail` |
| Цепочка WAL цела? | `wal-g wal-verify integrity timeline` |
| Retention WAL-G | `wal-g delete retain FULL 7` (+ `--confirm`) |
| pgBackRest: старт | `stanza-create` → `check` → `--type=full backup` → `info` |
| pgBackRest PITR | `restore --delta --type=time "--target=…" --target-action=pause` |
| Архивация идёт? | `SELECT * FROM pg_stat_archiver;` |
| Второй инстанс для restore | `pg_createcluster 16 restore --port 5433` |
| Остановиться перед транзакцией | `recovery_target_xid` + `recovery_target_inclusive = off` |
| Проверить pg_basebackup | `pg_verifybackup DIR` |
| Кластер Patroni | `patronictl -c … list` / `switchover` / `edit-config` |
| CNPG статус / бэкап | `kubectl cnpg status` / `kubectl cnpg backup … --method=plugin` |
| CNPG PITR | новый Cluster: `bootstrap.recovery` + `externalClusters[].plugin` |

---

## 🧠 Что запомнить

1. Непрерывный бэкап = base backup + архив WAL в S3; окно восстановления начинается с самого
   старого base backup, у которого есть все WAL.
2. RPO архива WAL ≈ `archive_timeout`, RTO = скачать бэкап + доиграть WAL — его замеряют, а не угадывают.
3. WAL-G работает с MinIO по http (path-style), pgBackRest — только по TLS.
4. Право на удаление у сервера БД — риск; retention — отдельной учёткой или lifecycle с запасом.
5. PITR — всегда во второй инстанс, с `archive_mode = off` и `recovery_target_action = 'pause'`.
6. Точку ищут по логам DDL или `pg_waldump`; `recovery_target_xid` + `inclusive = off` — «перед транзакцией».
7. Доверие к бэкапу строится уровнями: возраст → архивация → verify → restore-test → учения.
8. Patroni: лидер-ключ с TTL в DCS, потеря DCS → demote, параметры — через `edit-config`.
9. CNPG: бэкапы — плагином barman-cloud (встроенный устарел), PITR — новым кластером из ObjectStore.
10. Реплика — доступность, бэкап — ошибки и катастрофы; Redis/Kafka-репликация тоже не бэкап.

➡️ Дальше: [07_velero_dr.md](/storage/07-velero-dr) · задачи: 06_db_backup_replication_tasks.md


---

### Блок A. Теория


**A1.** Из чего состоит непрерывный бэкап PostgreSQL? С какого момента начинается окно восстановления?

<details><summary>Ответ</summary>

Base backup (копия PGDATA) + непрерывный архив WAL. Окно восстановления начинается с
самого старого base backup, для которого в архиве есть все последующие WAL, и заканчивается
последним заархивированным сегментом.

</details>

**A2.** ⭐ Чему равны RPO и RTO схемы «base backup + архив WAL в S3» и от чего они зависят?

<details><summary>Ответ</summary>

RPO ≈ неотправленный WAL: до `archive_timeout` (плюс незакрытый сегмент при полной потере
сервера). RTO = скачать base backup + применить WAL с момента бэкапа до цели: зависит от
размера базы, канала до S3 и объёма WAL (частоты full).

</details>

**A3.** Чем full, diff и incr/delta бэкапы отличаются по содержимому и по тому, что нужно для восстановления?

<details><summary>Ответ</summary>

Full — все файлы; diff (pgBackRest) — изменения с последнего full, восстановление = full +
diff + WAL; incr (pgBackRest) / delta (WAL-G) — изменения с последнего любого бэкапа,
восстановление = вся цепочка + WAL.

</details>

**A4.** Почему WAL нельзя удалять «по возрасту» отдельно от base backup'ов?

<details><summary>Ответ</summary>

WAL нужны тому base backup, после которого они записаны: удалишь «старые» WAL — самые
старые бэкапы станут бесполезны или появится дыра в цепочке. WAL удаляют только вместе с
устаревшим base backup — это делает retention инструмента.

</details>

**A5.** ⭐ Почему pgBackRest не работает с MinIO по `http`, а WAL-G работает? Что делает `repo1-storage-verify-tls=n`?

<details><summary>Ответ</summary>

pgBackRest для S3 всегда устанавливает TLS-соединение — plain HTTP не поддерживается;
WAL-G берёт схему из `AWS_ENDPOINT` и умеет http. `repo1-storage-verify-tls=n` лишь отключает
проверку сертификата (для самоподписанного на стенде), TLS остаётся.

</details>

**A6.** Зачем WAL-G параметр `AWS_S3_FORCE_PATH_STYLE`?

<details><summary>Ответ</summary>

По умолчанию SDK строит virtual-host адрес `bucket.endpoint`; для MinIO по IP это имя не
резолвится. Path-style — `endpoint/bucket/key`.

</details>

**A7.** Сервер БД не имеет права `s3:DeleteObject` в бакете бэкапов. Плюсы, минусы и два способа организовать retention.

<details><summary>Ответ</summary>

Плюс: взломанный сервер БД не удалит бэкапы. Минус: `wal-g delete retain` /
`pgbackrest expire` с сервера не работают. Способы: (а) retention делает lifecycle бакета со
сроком больше «окно восстановления + интервал full»; (б) удаление запускает отдельная учётка с
правом удаления с другой машины. Versioning и object lock — дополнительно.

</details>

**A8.** ⭐ Почему PITR делают во второй инстанс, а не поверх прода? Зачем в нём `archive_mode = off` и `recovery_target_action = 'pause'`?

<details><summary>Ответ</summary>

Поверх прода — потеря текущих данных и улик, нет второй попытки при промахе с целью.
Во втором инстансе прод продолжает работать, а нужное выгружается точечно. `archive_mode = off` —
чтобы копия не писала свои WAL/таймлайны в архив прода; `pause` — встать на точке read-only,
проверить данные и при промахе пересоздать без promote.

</details>

**A9.** Как найти точный момент `DROP TABLE`, если время известно только примерно? Что дают `recovery_target_xid` и `recovery_target_inclusive = off`?

<details><summary>Ответ</summary>

По логам (`log_statement = 'ddl'` пишет время DDL) или `pg_waldump` сегментов за период
(`--rmgr=Transaction`, коммит с удалёнными `rels:`). `recovery_target_xid` задаёт транзакцию,
`inclusive = off` — остановиться перед её коммитом, то есть ровно до DROP.

</details>

**A10.** Что такое timeline и чем опасен promote восстановленной копии с архивацией в тот же префикс?

<details><summary>Ответ</summary>

Timeline — ветка истории WAL; после promote восстановленной базы начинается новый
timeline и пишется `.history`. Если такая копия архивирует в тот же префикс, в архиве появляются
чужие ветки, и восстановление «на последний timeline» (по умолчанию `latest`) уйдёт в ветку копии.

</details>

**A11.** Как сочетаются retention инструмента, lifecycle бакета, versioning и object lock?

<details><summary>Ответ</summary>

Retention инструмента удаляет устаревшие бэкапы с учётом зависимостей; versioning
превращает удаление в delete marker, а реальную очистку старых версий делает lifecycle
`--noncurrent-expire-days`; object lock запрещает удаление до срока, поэтому срок lock ≤ retention,
иначе бакет растёт. Lifecycle на текущие объекты — только страховка с большим запасом.

</details>

**A12.** ⭐ Назови пять уровней проверки бэкапов — от алерта до учений.

<details><summary>Ответ</summary>

1) Возраст последнего успешного бэкапа (алерт); 2) архивация WAL идёт (`pg_stat_archiver`);

</details>

**A13.** Что проверяют `pg_verifybackup`, `pg_checksums`, `pg_amcheck`, `wal-g wal-verify`, `pgbackrest verify`?

<details><summary>Ответ</summary>

`pg_verifybackup` — бэкап `pg_basebackup` против `backup_manifest` и наличие нужного WAL;
`pg_checksums --check` — контрольные суммы страниц на остановленном кластере; `pg_amcheck` —
логическая целостность индексов и таблиц; `wal-verify` — непрерывность WAL и timeline в
хранилище WAL-G; `pgbackrest verify` — целостность файлов репозитория pgBackRest.

</details>

**A14.** Как Patroni выбирает лидера? Что делает лидер при потере связи с DCS и зачем watchdog?

<details><summary>Ответ</summary>

Лидер каждые `loop_wait` продлевает лидер-ключ в DCS с TTL; ключ истёк — реплики с лагом
не больше `maximum_lag_on_failover` соревнуются за ключ, победитель делает promote. Лидер,
потерявший DCS, demote'ится в read-only, чтобы не было двух лидеров (если не включён `failsafe_mode`).
Watchdog перезагружает узел, если Patroni завис и не успел снять роль лидера.

</details>

**A15.** Почему параметры PostgreSQL в кластере Patroni меняют через `patronictl edit-config`?

<details><summary>Ответ</summary>

Patroni управляет конфигурацией PostgreSQL: динамическая конфигурация хранится в DCS и
применяется ко всем узлам, а локальные правки перезаписываются. `edit-config` меняет её
централизованно и показывает, где нужен рестарт (`pending restart`).

</details>

**A16.** Чем CloudNativePG отличается от Patroni по устройству? Какие сервисы он создаёт?

<details><summary>Ответ</summary>

CNPG — оператор Kubernetes без Patroni: лидера выбирает сам оператор через API
Kubernetes, реплики — streaming replication, поды и PVC — его ресурсы. Сервисы: `&lt;name&gt;-rw`
(primary), `&lt;name&gt;-ro` (только реплики), `&lt;name&gt;-r` (любой инстанс).

</details>

**A17.** Что случилось со встроенным `barmanObjectStore` в CNPG и как теперь настраивают бэкапы?

<details><summary>Ответ</summary>

`spec.backup.barmanObjectStore` устарел с 1.26, удаление запланировано на 1.31. Теперь —
плагин barman-cloud (нужны CNPG ≥ 1.26 и cert-manager): ресурс ObjectStore
(`barmancloud.cnpg.io/v1`) с `configuration` и `retentionPolicy`, в Cluster — `spec.plugins`
с `isWALArchiver: true`, бэкапы с `method: plugin`, восстановление через `externalClusters[].plugin`.

</details>

**A18.** Почему репликация Redis и retention Kafka — не бэкап? Что у них бэкапить?

<details><summary>Ответ</summary>

Реплика Redis мгновенно повторит `FLUSHALL`, а retention Kafka — политика хранения,
удалённый топик на всех репликах исчезнет вместе с ним. Redis-базу бэкапят копией `dump.rdb`
после `BGSAVE`; у Kafka — конфигурацию (топики, ACL, схемы), а данные защищают вторым кластером
через MirrorMaker 2.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  # /etc/pgbackrest/pgbackrest.conf
```text
<details><summary>Ответ</summary>

⚠️ pgBackRest будет устанавливать TLS с MinIO, говорящим по http: `TLS error … wrong
version number`. Нужен TLS на MinIO (`--certs-dir`), на стенде + `repo1-storage-verify-tls=n`.

</details>

```text:no-line-numbers
     repo1-s3-endpoint=192.168.121.1
```text
```text:no-line-numbers
     repo1-storage-port=9000          # MinIO запущен без TLS
```text
```text:no-line-numbers
B2.  # /var/lib/postgresql/.walg.json
```text
<details><summary>Ответ</summary>

⚠️ Нет `AWS_S3_FORCE_PATH_STYLE: "true"` — запросы пойдут на `pg-backups.192.168.121.1`,
ошибки DNS/подключения. Нет сжатия (`WALG_COMPRESSION_METHOD`) — мелочь.

</details>

```text:no-line-numbers
     { "WALG_S3_PREFIX": "s3://pg-backups/stor1", "AWS_ENDPOINT": "http://192.168.121.1:9000",
```text
```text:no-line-numbers
       "AWS_REGION": "us-east-1", "AWS_ACCESS_KEY_ID": "pg-backup", "AWS_SECRET_ACCESS_KEY": "…" }
```text
```text:no-line-numbers
B3.  mc ilm rule add local/pg-backups --expire-days 7
```text
<details><summary>Ответ</summary>

🔴 Lifecycle удалит full-бэкап через 7 дней, а delta и WAL после него станут бесполезны;
окно PITR сломано, дыры в цепочке. Lifecycle ≥ окно + интервал full (здесь больше 21 дня) или
retention инструментом.

</details>

```text:no-line-numbers
     # full бэкап — раз в две недели, delta — ежедневно, PITR «на 7 дней назад»
```text
```text:no-line-numbers
B4.  # восстановление после DROP TABLE в 14:37
```text
<details><summary>Ответ</summary>

⚠️ `LATEST` — бэкап 15:00, снятый уже после DROP: таблицы там нет, а доиграть «назад»
нельзя. Выбрать бэкап до 14:37 из `backup-list` по имени.

</details>

```text:no-line-numbers
     sudo -u postgres wal-g backup-fetch /var/lib/postgresql/16/restore LATEST
```text
```text:no-line-numbers
     # последний backup-push был в 15:00 по расписанию
```text
```text:no-line-numbers
B5.  # копия для расследования
```text
<details><summary>Ответ</summary>

🔴 Копия после promote начнёт архивировать свой timeline в префикс прода. `archive_mode = off`,
`recovery_target_action = 'pause'`.

</details>

```text:no-line-numbers
     archive_mode = on
```text
```text:no-line-numbers
     archive_command = 'wal-g wal-push %p'
```text
```text:no-line-numbers
     recovery_target_action = 'promote'
```text
```text:no-line-numbers
B6.  recovery_target_time = '2026-09-27 14:37:01'     # без часового пояса; сервер в UTC
```text
<details><summary>Ответ</summary>

⚠️ Время без пояса интерпретируется в часовом поясе сервера (`timezone`); если человек
имел в виду местные 14:37 (UTC+5), промах — 5 часов. Всегда явный пояс: `+05` или `UTC`.

</details>

```text:no-line-numbers
B7.  # WALG_LIBSODIUM_KEY лежит в файле в том же бакете pg-backups/keys/
```text
<details><summary>Ответ</summary>

🔴 Ключ шифрования рядом с шифротекстом — шифрование ничего не защищает, а при потере
бакета потерян и ключ. Ключ — в Vault/менеджере секретов, копия офлайн.

</details>

```text:no-line-numbers
B8.  # узел Patroni: правим руками /etc/postgresql/16/main/postgresql.conf: max_connections = 500
```text
<details><summary>Ответ</summary>

⚠️ Patroni перезапишет правку своей конфигурацией; к тому же `max_connections` на
репликах должен быть не меньше, чем на primary. Менять через `patronictl edit-config` + restart.

</details>

```text:no-line-numbers
B9.  # DCS Patroni: два узла etcd «для надёжности»
```text
<details><summary>Ответ</summary>

⚠️ Кворум двух узлов etcd — оба: потеря любого = нет кворума, лидер Patroni demote'ится,
база read-only. 3 или 5 узлов.

</details>

```text:no-line-numbers
B10.  # CNPG, новый кластер
```text
<details><summary>Ответ</summary>

⚠️ Встроенный механизм устарел и будет удалён в 1.31 — новый кластер сразу на плагине
barman-cloud (ObjectStore + `spec.plugins`).

</details>

```text:no-line-numbers
     spec:
```text
```text:no-line-numbers
       backup:
```text
```text:no-line-numbers
         barmanObjectStore:
```text
```text:no-line-numbers
           destinationPath: s3://cnpg-backups/
```text
```text:no-line-numbers
B11.  # ScheduledBackup CNPG
```text
<details><summary>Ответ</summary>

⚠️ У CNPG расписание из 6 полей (секунды первыми): `"0 0 2 * * *"`. 5 полей не соответствуют
формату.

</details>

```text:no-line-numbers
     schedule: "0 2 * * *"
```text
```text:no-line-numbers
B12.  # «у нас синхронная реплика, бэкапы не нужны»
```text
<details><summary>Ответ</summary>

🔴 Синхронная реплика защищает от отказа узла с RPO 0, но `DROP TABLE`, порча данных
приложением и шифровальщик мгновенно реплицируются. Бэкап с PITR нужен всегда.

</details>

```text:no-line-numbers
B13.  # Redis как основная БД сессий и корзин, persistence отключена, одна реплика
```text
<details><summary>Ответ</summary>

⚠️ Если это не кэш, а данные: рестарт мастера без persistence — пустая база, и реплика
синхронизируется с пустым мастером (при автоперезапуске). Включить AOF (`everysec`) и/или RDB,
бэкапить `dump.rdb`, запретить автоперезапуск мастера без данных или использовать Sentinel.

</details>

```text:no-line-numbers
B14.  # алерт на бэкапы: «backup job failed»
```text
<details><summary>Ответ</summary>

⚠️ Алерт на ошибку не сработает, если джоба не запускалась вовсе (suspend, сломан cron).
Алертить на отсутствие успеха: «последнему успешному бэкапу больше 25 часов».

</details>


---

### Блок C. Практика


### C1. 🔑 WAL-G → MinIO
**1.** Создай бакет `pg-backups` с версионированием, пользователя `pg-backup` с политикой без удаления.

<details><summary>Ответ</summary>

Команды — разделы 3 конспекта и лаба 4 ([08_practice_labs.md](/softskills/08-practice-labs)).
Признаки успеха: `archived_count` растёт, `failed_count = 0`; в `backup-list --detail` первый
`base_…` полный, следующие — с `_D_` в имени (delta от предыдущего); `wal-verify` —
`integrity: OK`, `timeline: OK`.

</details>

**2.** Поставь WAL-G v3.0.9 на `stor1`, настрой `.walg.json`, `archive_command`, `archive_timeout = 60`.

<details><summary>Ответ</summary>

Восстановление — раздел 6: `pg_createcluster 16 restore --port 5433`, очистка каталога,
`backup-fetch` бэкапа до аварии, `recovery.conf` с `restore_command`, `recovery_target_time`
(на секунду раньше, с `+05`), `pause`, `archive_mode = off`, `recovery.signal`, старт; проверка
`SELECT pg_is_in_recovery(), count(*), max(created_at) FROM orders`; `pg_dump -t orders -Fc` →
`pg_restore -p 5432`. RPO — строки между целью и DROP (при записи раз в секунду — около одной),
RTO — от решения восстанавливать до таблицы в проде.

</details>

**3.** Добейся `failed_count = 0` в `pg_stat_archiver`, сделай full, потом два delta. Покажи `backup-list --detail`.

<details><summary>Ответ</summary>

`pg_waldump … --rmgr=Transaction | grep 'rels:'` → xid коммита с удалёнными файлами;
в recovery-конфиге `recovery_target_xid = '&lt;xid&gt;'`, `recovery_target_inclusive = off`. Результат
точнее: восстановлены все транзакции до DROP, включая закоммиченные в ту же секунду, которые
цель по времени на секунду раньше отбросила бы.

</details>

**4.** Проверь цепочку WAL `wal-verify`.

<details><summary>Ответ</summary>

Команда падает с `AccessDenied` на удалении объектов. Вариант (а): lifecycle
`mc ilm rule add local/pg-backups --expire-days 30 --noncurrent-expire-days 7` при full раз в неделю
и окне PITR 14 дней (30 > 14 + 7). Вариант (б): отдельная учётка `pg-retention` с `DeleteObject`,
`wal-g delete retain FULL 3 --confirm` с админ-хоста с другим `.walg.json`. Доказательство:
`backup-list` содержит бэкап старше окна, `wal-verify` без дыр, пробный PITR на глубину окна.

</details>

### C2. 🔑 PITR после DROP TABLE
**1.** Создай `shop.orders`, пиши строку в секунду.

<details><summary>Ответ</summary>

Команды — разделы 3 конспекта и лаба 4 ([08_practice_labs.md](/softskills/08-practice-labs)).
Признаки успеха: `archived_count` растёт, `failed_count = 0`; в `backup-list --detail` первый
`base_…` полный, следующие — с `_D_` в имени (delta от предыдущего); `wal-verify` —
`integrity: OK`, `timeline: OK`.

</details>

**2.** Засеки время, выполни `DROP TABLE orders`, `SELECT pg_switch_wal()`.

<details><summary>Ответ</summary>

Восстановление — раздел 6: `pg_createcluster 16 restore --port 5433`, очистка каталога,
`backup-fetch` бэкапа до аварии, `recovery.conf` с `restore_command`, `recovery_target_time`
(на секунду раньше, с `+05`), `pause`, `archive_mode = off`, `recovery.signal`, старт; проверка
`SELECT pg_is_in_recovery(), count(*), max(created_at) FROM orders`; `pg_dump -t orders -Fc` →
`pg_restore -p 5432`. RPO — строки между целью и DROP (при записи раз в секунду — около одной),
RTO — от решения восстанавливать до таблицы в проде.

</details>

**3.** Восстанови во второй кластер на порту 5433 на секунду раньше, проверь данные в режиме pause,
   перенеси таблицу в прод. Посчитай фактические RPO (потерянные строки) и RTO.

<details><summary>Ответ</summary>

`pg_waldump … --rmgr=Transaction | grep 'rels:'` → xid коммита с удалёнными файлами;
в recovery-конфиге `recovery_target_xid = '&lt;xid&gt;'`, `recovery_target_inclusive = off`. Результат
точнее: восстановлены все транзакции до DROP, включая закоммиченные в ту же секунду, которые
цель по времени на секунду раньше отбросила бы.

</details>

### C3. Точка по транзакции
Повтори C2, но цель найди через `pg_waldump` и восстанови по `recovery_target_xid` с
`recovery_target_inclusive = off`. Сравни результат с восстановлением по времени.

### C4. Retention без права удаления
Покажи, что `wal-g delete retain FULL 1 --confirm` от имени `pg-backup` падает. Настрой
retention одним из двух способов из конспекта и докажи, что PITR на глубину окна остаётся возможен.

### C5. 🔑 Restore-test скриптом
Напиши `restore-test.sh`: разворачивает последний бэкап во временный кластер (порт 5434), ждёт
окончания recovery, проверяет `pg_amcheck`, `count(*)` и свежесть `max(created_at)` (не старше
N минут от времени бэкапа), удаляет кластер и возвращает ненулевой код при любой проблеме.

### C6. pgBackRest с TLS (бонус)
Включи TLS на MinIO (самоподписанный сертификат с SAN `IP:192.168.121.1`), настрой pgBackRest,
сделай `stanza-create`, `check`, full и `restore --type=time` в отдельный кластер. Что покажет
`check` без TLS на MinIO?

### C7. 🔑 CloudNativePG с бэкапом в MinIO
**1.** В kind поставь CNPG 1.30.1, cert-manager и plugin-barman-cloud v0.15.0.

<details><summary>Ответ</summary>

Команды — разделы 3 конспекта и лаба 4 ([08_practice_labs.md](/softskills/08-practice-labs)).
Признаки успеха: `archived_count` растёт, `failed_count = 0`; в `backup-list --detail` первый
`base_…` полный, следующие — с `_D_` в имени (delta от предыдущего); `wal-verify` —
`integrity: OK`, `timeline: OK`.

</details>

**2.** Создай пользователя `cnpg` и бакет `cnpg-backups` в MinIO, секрет `minio-creds`, ObjectStore
   с `retentionPolicy: "30d"`, Cluster из 3 инстансов с плагином-архиватором.

<details><summary>Ответ</summary>

Восстановление — раздел 6: `pg_createcluster 16 restore --port 5433`, очистка каталога,
`backup-fetch` бэкапа до аварии, `recovery.conf` с `restore_command`, `recovery_target_time`
(на секунду раньше, с `+05`), `pause`, `archive_mode = off`, `recovery.signal`, старт; проверка
`SELECT pg_is_in_recovery(), count(*), max(created_at) FROM orders`; `pg_dump -t orders -Fc` →
`pg_restore -p 5432`. RPO — строки между целью и DROP (при записи раз в секунду — около одной),
RTO — от решения восстанавливать до таблицы в проде.

</details>

**3.** Сделай on-demand бэкап и ScheduledBackup; покажи `kubectl cnpg status` и `kubectl get backups`.

<details><summary>Ответ</summary>

`pg_waldump … --rmgr=Transaction | grep 'rels:'` → xid коммита с удалёнными файлами;
в recovery-конфиге `recovery_target_xid = '&lt;xid&gt;'`, `recovery_target_inclusive = off`. Результат
точнее: восстановлены все транзакции до DROP, включая закоммиченные в ту же секунду, которые
цель по времени на секунду раньше отбросила бы.

</details>

**4.** Сделай PITR новым кластером `pg-main-restore` на момент до удаления таблицы.

<details><summary>Ответ</summary>

Команда падает с `AccessDenied` на удалении объектов. Вариант (а): lifecycle
`mc ilm rule add local/pg-backups --expire-days 30 --noncurrent-expire-days 7` при full раз в неделю
и окне PITR 14 дней (30 > 14 + 7). Вариант (б): отдельная учётка `pg-retention` с `DeleteObject`,
`wal-g delete retain FULL 3 --confirm` с админ-хоста с другим `.walg.json`. Доказательство:
`backup-list` содержит бэкап старше окна, `wal-verify` без дыр, пробный PITR на глубину окна.

</details>

### C8. Switchover в CNPG
Выполни `kubectl cnpg promote` на другой инстанс, пока в цикле идут запросы через сервис
`pg-main-rw`. Сколько запросов упало? Что должно уметь приложение, чтобы не заметить switchover?

### C9. Patroni на бумаге
Для трёх узлов PostgreSQL и трёх узлов etcd нарисуй схему с HAProxy (порты 5000/5001), опиши,
что произойдёт при: падении лидера; потере связи лидера с etcd; падении двух узлов etcd из трёх.

---

### Блок D. Инциденты


**D1.** `pg_wal` на primary вырос до 90% диска, в логах `archive command failed with exit code 1`.

<details><summary>Ответ</summary>

Архивация падает — WAL не удаляются, `pg_wal` растёт, скоро кончится диск и база встанет.
Смотреть `last_failed_wal` в `pg_stat_archiver` и лог: сеть до MinIO, ключи, права, место в
бакете, TLS. Чинить причину — архив догонит сам. Не удалять WAL руками. На будущее — алерты на
`failed_count` и размер `pg_wal`.

</details>

**D2.** Нужно PITR на вчера 14:00, а `wal-g backup-fetch` находит только бэкапы за последние 3 дня
и `wal-verify` показывает дыру в WAL позавчера.

<details><summary>Ответ</summary>

Retention/lifecycle удалил старые бэкапы, а дыра в WAL делает PITR через неё невозможным:
точка вчера 14:00 доступна, только если есть base backup после дыры и до 14:00. Если нет —
восстановиться можно лишь на точку до дыры (если бэкап есть) или на ближайшую после. Причину
дыры (сбой архивации, lifecycle) — в постмортем; алерт на `wal-verify` и `failed_count`.

</details>

**D3.** После восстановления копии для расследования следующее PITR прода восстановилось «не
туда»: другие данные, другой timeline.

<details><summary>Ответ</summary>

Копия расследования была promote'нута с архивацией в тот же префикс — в архиве появился
новый timeline, и восстановление с `recovery_target_timeline = 'latest'` пошло по нему. Указать
нужный timeline явно, убрать чужие `.history`/сегменты (осторожно, с бэкапом бакета), впредь —
`archive_mode = off` в копиях.

</details>

**D4.** Patroni: после сетевого сбоя оба узла какое-то время считали себя лидером. Как такое возможно
и как защищаются?

<details><summary>Ответ</summary>

Split-brain: старый лидер не увидел потерю ключа (завис, долгий GC, сетевой раздел при
живой связи с клиентами), а новый уже promote'нут. Защита: demote при потере DCS, watchdog
(перезагрузка зависшего узла), корректные `ttl/loop_wait/retry_timeout`, HAProxy по `/primary`
с `on-marked-down shutdown-sessions`, fencing, синхронная репликация для критичных данных.

</details>

**D5.** Patroni-кластер ушёл в read-only: лидер demote'ился, новый не выбран.

<details><summary>Ответ</summary>

Нет кворума DCS или все реплики с лагом больше `maximum_lag_on_failover` (или в `pause`
режиме / теги `nofailover`). Смотреть `patronictl list`, здоровье etcd (`etcdctl endpoint health`),
логи Patroni. Восстановить кворум etcd; если реплики отстали — осознанный `patronictl failover
--candidate` с принятием потерь.

</details>

**D6.** CNPG: бэкапы перестали появляться, в статусе кластера ошибка архивации WAL.

<details><summary>Ответ</summary>

`kubectl cnpg status` и логи sidecar плагина: ключи/права в MinIO, сменившийся IP
контейнера MinIO в сети kind, заполненный бакет, не запущен деплой `barman-cloud`, проблема
cert-manager. Починить доступ — архивация продолжится; проверить, что свежий бэкап появился.

</details>

**D7.** Restore-test зелёный, но на учениях восстановление 400 ГБ заняло 5 часов при RTO 1 час.

<details><summary>Ответ</summary>

Restore-test проверяет «восстанавливается», а не «успевает». RTO = скачивание 400 ГБ +
доигрывание WAL. Сокращать: чаще full (меньше WAL), параллельная загрузка
(`WALG_DOWNLOAD_CONCURRENCY`, `process-max`), копия ближе к месту восстановления, delta-restore
поверх старой копии, а для RTO минуты — реплика в DR-площадке.

</details>

**D8.** Redis упал по OOM ровно во время ночного `BGSAVE`, данных в памяти было 6 ГБ из 8 ГБ RAM.

<details><summary>Ответ</summary>

`BGSAVE` делает `fork`; при активной записи copy-on-write копирует страницы — память
почти удваивается, 6 + до 6 ГБ > 8 ГБ. Решения: `vm.overcommit_memory = 1`, запас RAM
(`maxmemory` заметно ниже RAM), отключить THP, делать `BGSAVE` на реплике.

</details>

**D9.** Kafka-топик с событиями оплаты случайно удалили. «Там же retention 7 дней и RF=3».

<details><summary>Ответ</summary>

Retention и RF защищают от отказа брокеров и хранят данные ограниченное время, но
удаление топика удаляет его на всех репликах. Данные возвращаются только из второго кластера
(MirrorMaker 2) или из систем-источников (переотправка событий, outbox в БД). На будущее —
запрет удаления топиков (`delete.topic.enable`/ACL), IaC для топиков, DR-кластер.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как ты бэкапишь PostgreSQL в проде?

<details><summary>Ответ</summary>

Base backup + непрерывный архив WAL в S3 вне площадки (WAL-G/pgBackRest; в k8s — CNPG с
   barman-cloud), шифрование, сервер пишет без права удаления, алерты на возраст бэкапа и
   архивацию, еженедельный restore-test, учения раз в квартал.

</details>

**2.** Что такое PITR и как его сделать?

<details><summary>Ответ</summary>

Восстановление на момент времени: base backup до аварии + доигрывание WAL до
   `recovery_target_time`/`xid`. Делаю во второй инстанс с `archive_mode = off` и `pause`,
   проверяю и переношу нужное в прод.

</details>

**3.** Какие RPO и RTO у твоей схемы и как ты их проверил?

<details><summary>Ответ</summary>

RPO ≈ `archive_timeout` (минута), RTO — замер на учениях: скачивание + доигрывание WAL для
   нашего объёма; называю конкретные цифры со стенда или прода.

</details>

**4.** WAL-G или pgBackRest — что выберешь и почему?

<details><summary>Ответ</summary>

Что поддерживает платформа, и одно на компанию. WAL-G — один бинарь, http к S3, delta;
   pgBackRest — мощный retention, diff/incr, verify, параллельность, но S3 только по TLS.

</details>

**5.** Как проверяешь, что бэкапы рабочие?

<details><summary>Ответ</summary>

Уровнями: возраст успешного бэкапа, архивация WAL, verify файлов, автоматический
   restore-test с проверкой данных, учения с замером RTO.

</details>

**6.** Как защитить бэкапы от удаления (взлом, шифровальщик)?

<details><summary>Ответ</summary>

Сервер БД без права удаления, retention отдельной учёткой или lifecycle, versioning и object
   lock, копия в другом месте под другими учётками, ключи шифрования вне бакета.

</details>

**7.** Как работает Patroni? Что такое DCS и зачем нечётное число узлов?

<details><summary>Ответ</summary>

Лидер держит ключ с TTL в DCS (etcd/Consul/k8s); ключ истёк — реплики выбирают нового,
   потерявший DCS лидер demote'ится. Нечётное число узлов DCS нужно для кворума большинства.

</details>

**8.** Чем switchover отличается от failover?

<details><summary>Ответ</summary>

Switchover — плановая смена лидера на здоровом кластере без потерь (учения, обслуживание);
   failover — аварийная, когда лидер недоступен, возможна потеря неотправленных транзакций.

</details>

**9.** Стоит ли держать PostgreSQL в Kubernetes? Как с бэкапами в CloudNativePG?

<details><summary>Ответ</summary>

Можно через зрелый оператор при опыте команды и проверенном восстановлении; иначе — VM или
   managed. В CNPG бэкапы — плагин barman-cloud в S3, ScheduledBackup, PITR новым кластером.

</details>

**10.** Реплика — это бэкап?

<details><summary>Ответ</summary>

Нет: реплика защищает от отказа узла, а ошибки людей и приложения реплицирует. Нужны оба.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Объясняю base backup + WAL, окно восстановления, RPO и RTO этой схемы
- [ ] ⭐ WAL-G пишет в MinIO, архивация без ошибок, `wal-verify` зелёный
- [ ] ⭐ Сделал PITR после DROP TABLE во второй инстанс по времени и по xid
- [ ] Знаю, почему pgBackRest требует TLS к S3, и настроил его (бонус)
- [ ] Организовал retention без права удаления у сервера БД
- [ ] Есть restore-test скриптом с проверкой данных
- [ ] Объясняю Patroni: DCS, TTL, demote, watchdog, `patronictl`, HAProxy
- [ ] CNPG с плагином barman-cloud бэкапится в MinIO, PITR новым кластером сделан
- [ ] Называю RPO/RTO для дампа, WAL-архива, async/sync реплики, отложенной реплики, снапшота
