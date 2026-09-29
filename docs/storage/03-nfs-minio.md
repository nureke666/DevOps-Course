---
title: "03. NFS и MinIO: файловое и объектное хранилище своими руками"
description: "Блок → Хранилища и stateful → тема 03. Опирается на"
---

# 03. NFS и MinIO: файловое и объектное хранилище своими руками

> Блок → Хранилища и stateful → тема 03. Опирается на
> [../Linux/16_network_sharing.md](/linux/16-network-sharing) (NFS-сервер и клиент, опции
> экспорта, `hard`/`soft`), [../Left/04_Cloud/04_s3_storage.md](/cloud/04-s3-storage)
> (S3: бакеты, политики, versioning, object lock, lifecycle) и
> [01_storage_basics.md](/storage/01-storage-basics) (block/file/object, erasure coding).
>
> **После темы ты умеешь:** выбрать версию NFS и опции монтирования, дать Kubernetes
> RWX-тома через csi-driver-nfs, поднять self-hosted S3 в docker compose, управлять им через
> `mc` (пользователи, политики, versioning, object lock, lifecycle, TLS), объяснить erasure
> coding MinIO и трезво оценить, что стало с MinIO Community в 2025–2026 и чем его заменить.

---

## 🗺️ Карта темы

```text
                    «нужно общее хранилище для нескольких серверов/подов»
                                         │
             ┌───────────────────────────┴────────────────────────────┐
             ▼                                                        ▼
   ФАЙЛОВОЕ: NFS (POSIX, mount)                          ОБЪЕКТНОЕ: S3 API (HTTP)
   общие каталоги, legacy-приложения,                     бэкапы, артефакты, медиа, логи,
   RWX-тома в k8s                                         Loki/Thanos/Velero/WAL-G
             │                                                        │
   csi-driver-nfs / nfs-subdir-                            MinIO / форк silo / AIStor
   external-provisioner                                    Ceph RGW · SeaweedFS · Garage
             │                                                        │
   ⚠️ один сервер = SPOF,                                  erasure coding, IAM-политики,
      размер PVC не ограничивается                         versioning + object lock + lifecycle
```text
---

## 1. NFS глазами девопса: что добавить к основам

Как поднять сервер и клиент, что значат `root_squash`, `sync` и `hard` — в
[../Linux/16_network_sharing.md](/linux/16-network-sharing). Ниже — то, о что спотыкаются в проде.

### Версии протокола

| | NFSv3 | NFSv4.0 | NFSv4.1 / 4.2 |
|---|-------|---------|---------------|
| Состояние | stateless | stateful (leases) | + sessions; 4.2: server-side copy, sparse files |
| Порты | 2049 + rpcbind 111 + mountd/statd/lockd (плавающие) | ⭐ только 2049/TCP | только 2049/TCP |
| Блокировки | отдельный протокол NLM (lockd) | встроены в протокол | встроены |
| Пользователи | UID/GID числами | имена через idmapd (или числа) | то же + Kerberos |
| `showmount -e` | работает | нужен mountd — на v4-only сервере не ответит | то же |

Правило: **NFSv4.1+**, если нет причин иначе. Один порт проще для firewall и Kubernetes,
блокировки надёжнее.

### Опции монтирования, которые реально крутят

```bash
sudo mount -t nfs -o vers=4.2,hard,timeo=600,retrans=2,rsize=1048576,wsize=1048576,nconnect=4,noatime \
  192.168.60.10:/srv/nfs/shared /mnt/nfs
nfsstat -m                  # какие опции РЕАЛЬНО применились (сервер мог урезать rsize/версию)
```text
| Опция | Смысл |
|-------|-------|
| `vers=4.2` | Явная версия: иначе клиент договаривается сам и может скатиться на v3 |
| `hard,timeo=600,retrans=2` | Дефолт для TCP: ждать сервер, не терять запись; `soft` — только для read-only |
| `rsize/wsize` | Размер блока чтения/записи; сервер урежет до своего максимума |
| `nconnect=4` | Несколько TCP-соединений к серверу (ядро 5.3+) — заметно быстрее на 10G |
| `actimeo=N` / `noac` | Кэш атрибутов; `noac` даёт свежесть ценой скорости в разы |

### Консистентность и блокировки

- NFS даёт **close-to-open consistency**: клиент B гарантированно увидит изменения клиента A,
  если A закрыл файл, а B открыл его после этого. До закрытия и в пределах кэша атрибутов
  (`actimeo`, по умолчанию до 60 с для каталогов) — может не увидеть.
- Отсюда классика: «файл загрузили на web1, а web2 отдаёт 404 ещё полминуты».
- **SQLite, PostgreSQL, Prometheus TSDB, Elasticsearch на NFS — антипаттерн.** Блокировки
  и `fsync` по сети ведут себя не так, как на локальном диске; итог — порча данных или
  «database is locked». Разработчики этих систем прямо пишут: не на NFS.

### Диагностика

```bash
rpcinfo -p 192.168.60.10         # какие RPC-сервисы живы (нужно для v3)
cat /proc/fs/nfsd/versions       # на сервере: какие версии включены (+4.2 +4.1 ...)
nfsstat -s / nfsstat -c          # счётчики сервера / клиента (retrans — плохой знак)
nfsiostat 5                      # задержка и throughput по каждому mount (пакет nfs-common)
```text
### Высокая доступность

Один NFS-сервер — **единая точка отказа**, а с `hard`-монтированием его падение вешает
процессы клиентов в `D`-состоянии. Варианты HA: Pacemaker + DRBD (active/passive),
NFS-Ganesha поверх CephFS (тема [04_ceph.md](/storage/04-ceph)), аппаратный NAS с кластерным
контроллером. Если HA нет — честно впиши NFS в список SPOF и в DR-план.

---

## 2. NFS в Kubernetes: RWX-тома

Встроенный тип тома `nfs:` умеет только **статические** PV. Для динамического выделения
(PVC → PV автоматически) нужен провижинер. Два популярных:

| | csi-driver-nfs ⭐ | nfs-subdir-external-provisioner |
|---|-------------------|---------------------------------|
| Проект | kubernetes-csi (официальный CSI-драйвер) | kubernetes-sigs |
| provisioner | `nfs.csi.k8s.io` | `k8s-sigs.io/nfs-subdir-external-provisioner` |
| Как работает | CSI: controller создаёт подкаталог, node-плагин монтирует | Под-провижинер создаёт подкаталог, PV — обычный in-tree `nfs` |
| Несколько NFS-серверов | Да: `server`/`share` в каждом StorageClass | Один сервер на установку (ставят несколько релизов) |
| На нодах нужен `nfs-common` | Утилиты монтирования внутри node-плагина | Да: монтирует kubelet |
| Когда брать | Новые установки | Уже стоит и работает; простые стенды |

```bash
helm repo add csi-driver-nfs https://raw.githubusercontent.com/kubernetes-csi/csi-driver-nfs/master/charts
helm install csi-driver-nfs csi-driver-nfs/csi-driver-nfs --namespace kube-system --version 4.13.4
kubectl get csidrivers                                     # nfs.csi.k8s.io
kubectl -n kube-system get pods -l app.kubernetes.io/instance=csi-driver-nfs
```text
```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: nfs-csi
provisioner: nfs.csi.k8s.io
parameters:
  server: 192.168.60.10          # NFS-сервер (на стенде — stor1 или хост)
  share: /srv/nfs/k8s            # экспорт; под каждый PV — свой подкаталог
reclaimPolicy: Retain            # данные важнее автоматической уборки
volumeBindingMode: Immediate     # NFS доступен с любой ноды — ждать под незачем
allowVolumeExpansion: true
mountOptions:
  - nfsvers=4.1
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: shared-uploads }
spec:
  accessModes: [ReadWriteMany]   # ⭐ ради этого NFS и берут
  storageClassName: nfs-csi
  resources: { requests: { storage: 5Gi } }
```text
Альтернатива для уже живущих кластеров:
```bash
helm repo add nfs-subdir-external-provisioner https://kubernetes-sigs.github.io/nfs-subdir-external-provisioner/
helm install nfs-subdir-external-provisioner nfs-subdir-external-provisioner/nfs-subdir-external-provisioner \
  --set nfs.server=192.168.60.10 --set nfs.path=/srv/nfs/k8s
```text
⚠️ Что важно знать про NFS в кубере:

1. **Размер PVC на NFS не ограничивается.** `storage: 5Gi` — это метка для планировщика,
   а не квота: под спокойно заполнит всю шару и уронит соседей. Квоты — на стороне сервера
   (отдельный экспорт/том на команду, project quotas XFS).
2. **Права.** Провижинер создаёт каталоги от root; при `root_squash` они становятся
   `nobody`, и под с `runAsUser: 1000` не может писать. `fsGroup` на NFS часто не помогает
   (chown упирается в тот же squash). Решения: параметр `mountPermissions` у csi-driver-nfs,
   `all_squash,anonuid=,anongid=` на экспорте, запуск приложения с нужным UID.
3. **Безопасность.** Экспорт открывай только на IP нод. Inline-том `nfs:` в поде разрешён
   профилем PSA `baseline` — любой, кто создаёт поды, смонтирует шару целиком. Для
   прикладных namespace — PSA `restricted` (там разрешены только PVC/CSI-тома).
4. **Отказ сервера** = все поды с этим томом зависают в `ContainerCreating`/`D`-state.

---

## 3. MinIO: что это и что с ним случилось в 2025–2026

MinIO — S3-совместимое объектное хранилище одним бинарём на Go. Годами было выбором по
умолчанию для self-hosted S3: стенды, CI, бэкапы, on-prem (в Казахстане — очень частый
случай). Знания о нём (S3 API, `mc`, IAM-политики, erasure coding) переносятся на любое
S3-хранилище. Но статус проекта поменялся — это надо знать до того, как тянуть его в прод.

| Когда | Что произошло |
|-------|---------------|
| Май 2021 | Лицензия Apache 2.0 → **AGPLv3** |
| Весна 2025 (релизы мая–июня) | Из консоли Community убрали администрирование: осталась только навигация по объектам; пользователи, политики, lifecycle — через `mc admin` |
| 2025-10-15 | Community — **source-only**: официальных бинарей и образов больше нет |
| Декабрь 2025 | Проект переведён в режим поддержки (maintenance mode) |
| Февраль 2026 | Репозиторий `minio/minio` заархивирован: «no longer maintained» |
| Июль 2026 | Заархивирован `minio/mc`; скачивание клиента с `dl.min.io` отвечает `410 Gone` |
| Сентябрь 2026 | Образ `minio/minio` удалён с Docker Hub (`pull access denied`), на quay.io анонимный pull закрыт |

Последние community-сборки содержат **неисправленные уязвимости** — например,
CVE-2026-40344 (обход аутентификации при записи объектов; исправлен только в AIStor
RELEASE.2026-04-11). Замораживать старый образ «навсегда» — плохая идея.

Что выбрать сегодня:

| Вариант | Что это | Когда |
|---------|---------|-------|
| **AIStor** | Коммерческий продукт MinIO Inc.; AIStor Free — одна нода, нужен файл лицензии, без поддержки и без шифрования at rest | Нужен «оригинальный» MinIO с вендором |
| **pgsty/silo** | Форк сообщества (до 2026-08-06 — `pgsty/minio`), AGPL; drop-in: те же `MINIO_*`, тот же формат `/data`, возвращена полная консоль; клиент — `mcli` | Стенды и self-hosted, где нужен привычный MinIO |
| Ceph RGW / SeaweedFS / Garage | Другие S3-хранилища (раздел 11) | Новые установки без привязки к MinIO |

> 💡 На стенде блока — форк `pgsty/silo`: команды те же, что в документации MinIO.
> Проекты волта, где в compose стоит `minio/minio`, нужно перепиннить на актуальный образ.

---

## 4. Архитектура MinIO: от одного диска до кластера

| Топология | Что это | Переживёт |
|-----------|---------|-----------|
| SNSD (single node, single drive) | Один процесс, один диск, без избыточности | Ничего. Dev и CI |
| SNMD (single node, multi drive) | Один сервер, erasure coding по дискам | Отказ дисков (до M), но не сервера |
| MNMD (distributed) ⭐ | N серверов × M дисков, erasure coding поверх всех | Отказ дисков и целых серверов |

**Erasure coding.** Диски пула делятся на **erasure sets** (2–16 дисков). Каждый объект режется
на K частей данных и M частей чётности: `N (размер set) = K + M`. Потерять можно до M частей.

```text
erasure set из 4 дисков, EC:2  →  K=2 данных + M=2 чётности
объект ──► [D1] [D2] [P1] [P2]        полезная ёмкость = K/N = 50%
             │    │    │    │
           disk1 disk2 disk3 disk4
чтение: нужно любых K = 2 части       запись: нужен кворум K (K+1, если K = M) = 3 диска
⇒ минус 2 диска: читать можно, писать уже нельзя
```text
| Параметр | Значение |
|----------|----------|
| Минимум для EC | 2 диска технически (EC:1); на практике — от 4, классические примеры документации — с 4+ |
| Парность по умолчанию | по размеру set: 2–3 диска → EC:1, 4–5 → EC:2, 6–7 → EC:3, 8–16 → EC:4 (максимум — половина set; смотри `mc admin info`) |
| Размер erasure set | Выбирается при первом старте и **не меняется** |
| Расширение | Только новым **server pool** той же схемы, диски в существующий set не добавить |
| Диски | Одинаковые по размеру и типу, XFS, монтирование по label/UUID; **без RAID и LVM снизу** — избыточность даёт EC |
| Целостность | Каждая часть с контрольной суммой: bitrot находится и лечится (healing) |

```bash
# распределённый кластер: 4 сервера × 4 диска = один пул из 16 дисков
minio server https://minio{1...4}.example.net/mnt/disk{1...4}
# расширение: второй пул дописывается в ту же команду на ВСЕХ нодах
minio server https://minio{1...4}.example.net/mnt/disk{1...4} https://minio{5...8}.example.net/mnt/disk{1...4}
```text
(В форке бинарь называется `silo`, аргументы те же.) Перед кластером — балансировщик
(nginx/HAProxy) на `/minio/health/live`, синхронное время, одинаковые env на всех нодах.

---

## 5. Стенд: MinIO в docker compose

```bash
mkdir -p ~/labs/storage/minio/files && cd ~/labs/storage/minio
```text
```yaml
# ~/labs/storage/minio/docker-compose.yml
services:
  minio:
    image: pgsty/silo:RELEASE.2026-09-16T00-00-00Z   # drop-in форк MinIO (AGPL)
    container_name: minio
    command: server /data{1...4} --console-address ":9001"
    environment:
      MINIO_ROOT_USER: admin
      MINIO_ROOT_PASSWORD: admin-secret-123
    ports: ["9000:9000", "9001:9001"]
    volumes:
      - d1:/data1
      - d2:/data2
      - d3:/data3
      - d4:/data4
      - ./files:/files          # файлы с хоста для mc cp/mirror
volumes: { d1: {}, d2: {}, d3: {}, d4: {} }
```text
```bash
docker compose up -d && docker compose logs minio | tail -20
alias mc='docker exec -i minio mcli'           # клиент mc в образе форка называется mcli
mc alias set local http://127.0.0.1:9000 admin admin-secret-123
mc admin info local                            # 4 drives online, строка EC:N — парность
# консоль: http://localhost:9001 (admin / admin-secret-123)
```text
Четыре тома в одном контейнере — это **один erasure set из 4 дисков**: удобно потрогать EC
руками (задача C2). Пути в `mc` — это пути **внутри** контейнера: файлы с хоста кладёшь в
`./files` и обращаешься к ним как к `/files/...`.

| Кто ходит в MinIO | Endpoint |
|-------------------|----------|
| Хост | `http://127.0.0.1:9000` |
| Vagrant-VM (libvirt) | `http://192.168.121.1:9000` — шлюз сети `default` |
| Поды kind | `docker network connect kind minio`, затем IP: `docker inspect -f '&#123;&#123;(index .NetworkSettings.Networks "kind").IPAddress&#125;&#125;' minio` |

---

## 6. Клиент `mc`: основное

```bash
mc mb local/demo                               # создать бакет
mc cp /files/report.pdf local/demo/docs/       # загрузить
mc cp -r /files/site/ local/demo/site/         # рекурсивно
mc ls -r local/demo                            # список
mc cat local/demo/docs/report.pdf | wc -c      # прочитать в stdout
mc du local/demo                               # сколько занимает
mc mirror /files/site local/demo/site          # синхронизация каталога → бакет
mc mirror --overwrite --remove /files/site local/demo/site   # точное зеркало ⚠️ удаляет лишнее
mc mirror --watch /files/inbox local/demo/inbox              # следить и досылать
mc mirror local/demo remote/demo-copy          # бакет → бакет (между кластерами)
mc anonymous set download local/demo/public    # публичное чтение префикса (осознанно!)
mc admin trace -v local                        # живой трейс S3-запросов — отладка клиентов
```text
> ⚠️ `mc mirror --remove` — аналог `rsync --delete`: сначала прогон без флага, проверь,
> что источник и приёмник не перепутаны. `mc mirror` — синхронизация, а **не бэкап**:
> удаление в источнике с `--remove` приедет и в копию.

---

## 7. Пользователи и политики

Модель — как IAM в AWS: пользователь (access key + secret key) → политики (JSON в формате
AWS IAM) → действия над ресурсами `arn:aws:s3:::бакет/ключ`. Встроенные политики:
`readonly`, `readwrite`, `writeonly`, `diagnostics`, `consoleAdmin`. Root (`MINIO_ROOT_USER`)
используй только для администрирования.

Пользователь для бэкапов PostgreSQL (он же будет в [06_db_backup_replication.md](/storage/06-db-backup-replication)):
пишет и читает, но **не удаляет**.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": ["arn:aws:s3:::pg-backups"]
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:AbortMultipartUpload"],
      "Resource": ["arn:aws:s3:::pg-backups/*"]
    }
  ]
}
```text
```bash
cat > files/pg-backup-rw.json      # вставь JSON выше (файл на хосте → /files в контейнере)
mc mb --with-versioning local/pg-backups
mc admin policy create local pg-backup-rw /files/pg-backup-rw.json
mc admin user add local pg-backup 'pg-backup-secret-123'
mc admin policy attach local pg-backup-rw --user pg-backup
mc admin user info local pg-backup             # политики пользователя

# проверка от имени пользователя
mc alias set pgb http://127.0.0.1:9000 pg-backup 'pg-backup-secret-123'
mc cp /files/pg-backup-rw.json pgb/pg-backups/test.json    # ok
mc rm pgb/pg-backups/test.json                             # Access Denied — так и задумано
mc ls pgb                                                  # тоже отказ: нет s3:ListAllMyBuckets
```text
Почему это защищает бэкапы:
- **Versioning** на бакете: перезапись создаёт новую версию, старая остаётся.
- Обычный `DELETE` в бакете с версиями не удаляет данные, а ставит **delete marker**;
  по-настоящему удалить версию может только тот, у кого есть `s3:DeleteObjectVersion`.
- У `pg-backup` нет ни `DeleteObject`, ни `DeleteObjectVersion`: украденный ключ с прод-сервера
  не уничтожит историю. Старые бэкапы удаляет **сервер** по lifecycle-правилам (раздел 8).
- Группы: `mc admin group add local backup-writers pg-backup` +
  `mc admin policy attach local pg-backup-rw --group backup-writers` — права на группу, а не
  на каждого.

---

## 8. Versioning, object lock, lifecycle — на практике

Концепции — в [../Left/04_Cloud/04_s3_storage.md](/cloud/04-s3-storage). Здесь — как это
выглядит в `mc` и где подвохи.

```bash
# --- versioning ---
mc version enable local/demo                  # или сразу: mc mb --with-versioning
mc version info local/demo
echo v1 > files/note.txt && mc cp /files/note.txt local/demo/
echo v2 > files/note.txt && mc cp /files/note.txt local/demo/
mc rm local/demo/note.txt                     # delete marker, данные живы
mc ls --versions local/demo                   # видны v1, v2 и DEL
mc undo local/demo/note.txt                   # откатить последнюю операцию (снять delete marker)
mc rm --versions --newer-than 1h local/demo/note.txt   # ⚠️ откат: удалить версии моложе часа

# --- object lock (WORM) ---
mc mb --with-lock local/locked                # lock включается ТОЛЬКО при создании (+ versioning)
mc retention set --default GOVERNANCE "1d" local/locked
mc cp /files/note.txt local/locked/
mc ls --versions local/locked                 # запомни version id
mc rm --version-id &lt;VID&gt; local/locked/note.txt    # отказ: объект под WORM
mc legalhold set local/locked/note.txt        # бессрочная блокировка до снятия (legalhold clear)

# --- lifecycle ---
mc ilm rule add local/pg-backups --expire-days 30
mc ilm rule add local/pg-backups --noncurrent-expire-days 7 --expire-delete-marker
mc ilm rule ls local/pg-backups
```text
| Подвох | Что знать |
|--------|-----------|
| Object lock не мешает delete marker | Обычный `rm` «удаляет» объект из листинга, но заблокированная версия цела |
| GOVERNANCE vs COMPLIANCE | GOVERNANCE обходят пользователи с `s3:BypassGovernanceRetention`; COMPLIANCE не снимет никто, даже root, до конца срока. ⚠️ На стенде — только GOVERNANCE и короткие сроки |
| Lock нельзя включить потом | Нужен новый бакет и перенос данных |
| Lifecycle не мгновенный | Правила применяет фоновый сканер: объект исчезнет не ровно в полночь |
| Lifecycle vs lock | Версию под retention lifecycle не удалит, пока срок не истёк |
| `--expire-delete-marker` | Отдельным правилом: чистит «осиротевшие» delete marker'ы после удаления версий |
| Retention бэкапов | Срок lock ≥ срок, за который ты гарантированно заметишь взлом, и ≤ срока lifecycle |

---

## 9. Уведомления бакета (кратко)

MinIO умеет слать событие при `put`/`delete` объекта: webhook, Kafka, AMQP, NATS, Redis,
PostgreSQL, Elasticsearch.

```bash
mc admin config set local notify_webhook:primary endpoint="http://10.0.0.5:8080/hook"
mc admin service restart local
mc event add local/demo arn:minio:sqs::primary:webhook --event put,delete
mc event ls local/demo
```text
Зачем девопсу: «появился новый бэкап → запустить restore-test», аудит удалений,
обработка загруженных файлов (превью, антивирус) без поллинга бакета.

---

## 10. TLS

Без TLS ключи и данные идут открытым текстом. Минимум для стенда — самоподписанный сертификат:

```bash
cd ~/labs/storage/minio && mkdir -p certs
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout certs/private.key -out certs/public.crt -subj "/CN=minio" \
  -addext "subjectAltName=DNS:minio,DNS:localhost,IP:127.0.0.1,IP:192.168.121.1"
```text
```yaml
    command: server /data{1...4} --console-address ":9001" --certs-dir /certs
    volumes:
      - ./certs:/certs:ro         # public.crt + private.key — имена фиксированы
```text
```bash
docker compose up -d
mc alias set local https://127.0.0.1:9000 admin admin-secret-123
mc --insecure admin info local       # самоподписанный: --insecure или CA в доверенные
```text
Кому TLS обязателен: **pgBackRest всегда ходит в S3 по TLS** (подробности — в
[06_db_backup_replication.md](/storage/06-db-backup-replication)); в проде — всем. SAN должен содержать
то имя/IP, по которому ходят клиенты, иначе ошибка проверки сертификата.

---

## 11. Альтернативы self-hosted S3

| | Лицензия | Архитектура | Когда |
|---|----------|-------------|-------|
| **Ceph RGW** | LGPL | S3/Swift-шлюз поверх RADOS | Ceph уже есть (блок + файл + объект в одной системе) — [04_ceph.md](/storage/04-ceph) |
| **SeaweedFS** | Apache-2.0 | master + volume-серверы + filer, S3-шлюз, FUSE | Много мелких файлов, нужна «разрешительная» лицензия |
| **Garage** | AGPL | Лёгкий, geo-distributed, работает на слабом железе | Несколько площадок, homelab, edge |
| **AIStor / pgsty/silo** | коммерческая / AGPL | Код MinIO | Совместимость с существующим MinIO |

Перед выбором проверь нужный тебе набор S3-фич: versioning, object lock, lifecycle,
presigned URL, multipart — поддержка у всех разная.

---

## 12. Грабли

| Грабля | Последствие | Правильно |
|--------|-------------|-----------|
| БД или SQLite на NFS | Порча данных, «database is locked» | Блочный том |
| NFS без `vers=` | Клиент скатился на v3, firewall режет плавающие порты | `vers=4.1`/`4.2` явно |
| PVC на NFS «на 5Gi» | Под заполнил всю шару | Квоты на сервере, отдельные экспорты |
| Экспорт `*(rw,no_root_squash)` | Любой под/хост = root на шаре | Экспорт на IP нод, squash, PSA restricted |
| `minio/minio:latest` в compose | С сентября 2026 не скачивается; старые образы с CVE | Пиннить актуальный образ форка или AIStor |
| RAID/LVM под MinIO | Двойная избыточность, EC не видит реальные диски | Сырые диски, XFS, EC |
| Root-ключ в приложениях и бэкап-скриптах | Утёк один ключ — потеряно всё | Пользователь на задачу, минимальные политики |
| Бэкап-пользователь с `DeleteObject*` | Шифровальщик удалит бэкапы тем же ключом | Без удаления + versioning + lock + lifecycle |
| Object lock COMPLIANCE на стенде | Место не освободить до конца срока | GOVERNANCE и короткие сроки |
| `mc mirror --remove` как «бэкап» | Удаление в источнике уехало в копию | Versioning на приёмнике или настоящий бэкап-инструмент |
| Самоподписанный TLS без нужного SAN | Клиенты падают на проверке сертификата | SAN = имена/IP клиентов |

---

## 💼 Как это в DevOps

- NFS в новых системах — «последнее средство»: для RWX его терпят, но файлы пользователей
  переносят в S3, а БД — на блочные тома. В DR-плане NFS-сервер — отдельная строка.
- Self-hosted S3 — «склад» on-prem инфраструктуры: бэкапы БД (WAL-G, pgBackRest, CNPG),
  Velero, Loki/Thanos/Mimir, артефакты CI, terraform state. Его падение ломает сразу всё
  перечисленное — мониторь `/minio/health/cluster` и заполненность дисков.
- Бакеты, пользователи, политики и lifecycle описывают кодом (Terraform-провайдер или
  скрипт на `mc` в git), а не кликают в консоли.
- Лицензии и статус проекта — часть технического решения: смена модели дистрибуции MinIO
  в 2025–2026 заставила многих переезжать. Перед выбором хранилища проверяй, кто его
  поддерживает, как выходят security-фиксы и откуда брать образы.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Проверить опции NFS-монтирования | `nfsstat -m` |
| Быстрый NFS-mount | `-o vers=4.2,hard,nconnect=4,rsize=1048576,wsize=1048576` |
| RWX-тома в k8s | csi-driver-nfs, `provisioner: nfs.csi.k8s.io` |
| Алиас к MinIO | `mc alias set local http://127.0.0.1:9000 USER PASS` |
| Состояние кластера и EC | `mc admin info local` |
| Бакет с версиями / с lock | `mc mb --with-versioning` / `mc mb --with-lock` |
| Версии объекта | `mc ls --versions local/b` |
| Снять delete marker | `mc undo local/b/key` |
| Срок WORM по умолчанию | `mc retention set --default GOVERNANCE "30d" local/b` |
| Удалять старое | `mc ilm rule add local/b --expire-days 30` |
| Чистить старые версии | `mc ilm rule add local/b --noncurrent-expire-days 7 --expire-delete-marker` |
| Пользователь + политика | `mc admin user add` · `mc admin policy create` · `mc admin policy attach --user` |
| Зеркалить каталог | `mc mirror [--overwrite] [--remove] SRC DST` |
| Отладить клиента | `mc admin trace -v local` |
| TLS | `--certs-dir /certs` (`public.crt`, `private.key`) |

---

## 🧠 Что запомнить

1. NFS — для RWX и legacy; бери v4.1+ (один порт 2049, встроенные блокировки) и помни про
   close-to-open consistency.
2. БД и всё с `fsync`/блокировками на NFS не кладут; один NFS-сервер — SPOF.
3. В k8s динамические NFS-тома даёт csi-driver-nfs; размер PVC на NFS не ограничивается.
4. MinIO Community с 2025 года урезан, с октября 2025 без бинарей, с февраля 2026 в архиве;
   сегодня — AIStor, форк `pgsty/silo` или другое S3-хранилище.
5. Erasure coding: `N = K + M`, читать можно при потере M частей, писать нужен кворум;
   erasure set не меняется после старта, расширение — новым пулом.
6. Под MinIO — сырые одинаковые диски с XFS, без RAID и LVM.
7. У каждого приложения свой пользователь и минимальная политика; root — только админам.
8. ⭐ Защита бэкапов: versioning + object lock + пользователь без `DeleteObject*` +
   lifecycle на стороне сервера.
9. Object lock включается только при создании бакета и не мешает delete marker'ам.
10. S3 без TLS — ключи открытым текстом; pgBackRest без TLS к S3 не подключится вовсе.

➡️ Дальше: [04_ceph.md](/storage/04-ceph) · задачи: 03_nfs_minio_tasks.md


---

### Блок A. Теория


**A1.** Чем NFSv3 отличается от NFSv4.1 по портам, блокировкам и состоянию? Почему для
Kubernetes и firewall проще v4?

<details><summary>Ответ</summary>

v3 — stateless, кроме 2049 нужны rpcbind (111), mountd, statd/lockd на плавающих портах,
блокировки — отдельный протокол NLM. v4.1 — stateful (leases, sessions), один порт 2049/TCP,
блокировки в протоколе. Один фиксированный порт легко открыть в firewall и NetworkPolicy.

</details>

**A2.** Что такое close-to-open consistency? Какую проблему «файл есть на web1, но нет на web2»
она объясняет?

<details><summary>Ответ</summary>

Клиент гарантированно видит чужие изменения, только если писатель закрыл файл, а
читатель открыл его после этого; до этого клиент может отдавать данные и атрибуты из кэша
(`actimeo`). Поэтому web2 может не видеть только что загруженный на web1 файл секунды или
десятки секунд.

</details>

**A3.** ⭐ Почему PostgreSQL, SQLite и Prometheus не кладут на NFS?

<details><summary>Ответ</summary>

Им нужны честные `fsync`, атомарные rename и надёжные блокировки с предсказуемой
задержкой. По сети это работает иначе (кэш атрибутов, потерянные блокировки при сбоях,
задержки), итог — порча данных или «database is locked». Нужен блочный том.

</details>

**A4.** Зачем нужна опция `nconnect`? Что проверяет `nfsstat -m`?

<details><summary>Ответ</summary>

`nconnect=N` открывает несколько TCP-соединений к серверу и распараллеливает
запросы — прирост на быстрых сетях. `nfsstat -m` показывает фактически применённые опции
монтирования: версию, `rsize/wsize`, `hard/soft`, `timeo` — сервер мог урезать запрошенное.

</details>

**A5.** Чем csi-driver-nfs отличается от nfs-subdir-external-provisioner? Что выберешь для
нового кластера?

<details><summary>Ответ</summary>

csi-driver-nfs — официальный CSI-драйвер: controller создаёт подкаталог, node-плагин
монтирует, серверы задаются в каждом StorageClass. nfs-subdir — отдельный провижинер,
создаёт подкаталог и PV типа in-tree `nfs` (монтирует kubelet, на нодах нужен nfs-common),
один сервер на релиз. Для нового кластера — csi-driver-nfs.

</details>

**A6.** ⭐ Ограничивает ли `storage: 5Gi` в PVC на NFS реальный объём? Почему?

<details><summary>Ответ</summary>

Нет. NFS не знает о размере PVC: подкаталог на общей шаре без квоты, под может
заполнить весь экспорт. Ограничивать надо на сервере (отдельные экспорты/тома, квоты XFS).

</details>

**A7.** Перечисли топологии MinIO (SNSD, SNMD, MNMD) и что каждая переживает.

<details><summary>Ответ</summary>

SNSD — один диск, без избыточности, переживает ничего (dev/CI). SNMD — один сервер
с EC по дискам, переживает отказ дисков, но не сервера. MNMD — распределённый, переживает
отказ дисков и серверов в пределах парности.

</details>

**A8.** ⭐ Erasure set из 4 дисков, EC:2. Сколько полезной ёмкости? Сколько дисков можно
потерять для чтения и для записи?

<details><summary>Ответ</summary>

K=2, M=2 → полезно 50%. Для чтения нужно K=2 части — можно потерять 2 диска. Для
записи при K=M кворум K+1=3 — можно потерять только 1 диск.

</details>

**A9.** Почему под MinIO не ставят RAID и LVM? Что рекомендуют вместо этого?

<details><summary>Ответ</summary>

EC MinIO сам обеспечивает избыточность и лечение bitrot, ему нужно видеть реальные
диски; RAID/LVM снизу — двойные накладные расходы и маскировка отказов. Рекомендуют
одинаковые сырые диски с XFS, монтирование по label/UUID.

</details>

**A10.** Как расширить распределённый MinIO? Можно ли добавить диски в существующий
erasure set?

<details><summary>Ответ</summary>

Добавить новый server pool (ещё группу серверов/дисков) в команду запуска на всех
нодах. Диски в существующий erasure set не добавить: размер set выбирается при
инициализации и не меняется.

</details>

**A11.** Что случилось с MinIO Community в 2025–2026? Назови три варианта, что использовать сейчас.

<details><summary>Ответ</summary>

Лицензия AGPLv3 с 2021; весной 2025 из консоли Community убрали администрирование;
с 2025-10-15 только исходники без бинарей и образов; декабрь 2025 — maintenance mode; февраль

</details>

**A12.** Что происходит при обычном `DELETE` в бакете с включённым versioning? Какое
право нужно, чтобы удалить данные по-настоящему?

<details><summary>Ответ</summary>

Добавляется delete marker: объект пропадает из обычного листинга, но все версии
целы. Удалить данные можно удалением конкретной версии — нужно `s3:DeleteObjectVersion`.

</details>

**A13.** ⭐ Чем GOVERNANCE отличается от COMPLIANCE в object lock? Можно ли включить lock
на существующем бакете?

<details><summary>Ответ</summary>

GOVERNANCE обходят пользователи с правом `s3:BypassGovernanceRetention`; COMPLIANCE
не снимет никто, включая root, до истечения срока. Lock включается только при создании бакета
(`mc mb --with-lock`), для существующего — новый бакет и перенос данных.

</details>

**A14.** Почему lifecycle-правило «удалить через 30 дней» не удаляет объект ровно на 30-й день?

<details><summary>Ответ</summary>

Lifecycle применяет фоновый сканер, который обходит объекты с задержкой; объект
удаляется «после» срока, при следующем проходе. Плюс заблокированные версии не удаляются
до конца retention.

</details>

**A15.** Зачем бакету уведомления? Приведи два сценария для девопса.

<details><summary>Ответ</summary>

Чтобы реагировать на события без поллинга. Сценарии: новый бэкап → запуск
restore-test; удаление объекта → аудит/алерт; загрузка файла → обработка (превью, антивирус).

</details>

**A16.** Почему pgBackRest не подключится к MinIO на `http://`?

<details><summary>Ответ</summary>

pgBackRest всегда использует TLS для S3; `repo1-storage-verify-tls=n` отключает только
проверку сертификата, но не сам TLS. MinIO должен слушать https.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  # /etc/fstab на веб-серверах
```text
<details><summary>Ответ</summary>

⚠️ Нет `_netdev,nofail` — при недоступном сервере загрузка встанет; нет явной версии
(`vers=4.2`); `defaults` = `hard`: при падении сервера процессы висят в D. Добавить
`vers=4.2,_netdev,nofail`, осознанно выбрать `hard`.

</details>

```text:no-line-numbers
     10.0.0.5:/srv/uploads  /var/www/uploads  nfs  defaults  0 0
```text
```text:no-line-numbers
B2.  # /etc/exports
```text
<details><summary>Ответ</summary>

⚠️ Экспорт на весь мир с `no_root_squash`: любой хост (и любой под с inline `nfs:`)
получает root на шаре. Ограничить IP нод, убрать `no_root_squash` или компенсировать PSA
restricted.

</details>

```text:no-line-numbers
     /srv/nfs/k8s  *(rw,sync,no_subtree_check,no_root_squash)
```text
```text:no-line-numbers
B3.  # StatefulSet PostgreSQL
```text
<details><summary>Ответ</summary>

⚠️ БД на NFS — антипаттерн, да ещё RWX для StatefulSet бессмысленен (у каждого пода
свой PVC). Нужен блочный RWO-класс.

</details>

```text:no-line-numbers
     volumeClaimTemplates: [{ spec: { storageClassName: nfs-csi, accessModes: [ReadWriteMany] } }]
```text
```text:no-line-numbers
B4.  # docker-compose.yml, сентябрь 2026
```text
<details><summary>Ответ</summary>

⚠️ С сентября 2026 образ удалён с Docker Hub — `pull access denied`; до этого `latest`
застыл на старой сборке с уязвимостями. Пиннить конкретный тег поддерживаемого образа (форк
или AIStor).

</details>

```text:no-line-numbers
     image: minio/minio:latest
```text
```text:no-line-numbers
B5.  # MinIO на сервере с аппаратным RAID6 из 8 дисков, один том /dev/sdb → /data
```text
<details><summary>Ответ</summary>

⚠️ Один том поверх RAID6 — это SNSD: EC MinIO не работает, bitrot внутри RAID MinIO не
вылечит, а отказ контроллера убивает всё. Отдать 8 дисков напрямую: `minio server /data{1...8}`
(JBOD, XFS).

</details>

```text:no-line-numbers
     minio server /data
```text
```text:no-line-numbers
B6.  # политика бэкап-пользователя
```text
<details><summary>Ответ</summary>

⚠️ `s3:*` включает `DeleteObject`/`DeleteObjectVersion` — ключ с прод-сервера удалит
бэкапы. И `ListBucket` на `pg-backups/*` не сработает: это действие над бакетом (ресурс без `/*`).

</details>

```text:no-line-numbers
     { "Effect": "Allow", "Action": ["s3:*"], "Resource": ["arn:aws:s3:::pg-backups/*"] }
```text
```text:no-line-numbers
B7.  mc mb local/backups
```text
<details><summary>Ответ</summary>

⚠️ Retention требует бакета с lock — `mc retention set` на обычном бакете выдаст ошибку.
А COMPLIANCE на стенде заблокирует место на 30 дней без возможности удалить.

</details>

```text:no-line-numbers
     mc retention set --default COMPLIANCE "30d" local/backups
```text
```text:no-line-numbers
B8.  # «ночной бэкап» статики
```text
<details><summary>Ответ</summary>

⚠️ Это зеркало, а не бэкап: удалённый или испорченный файл через ночь исчезнет и в копии.
Нужны versioning на приёмнике (или датированные копии) и retention.

</details>

```text:no-line-numbers
     mc mirror --overwrite --remove /var/www/static local/static-backup
```text
```text:no-line-numbers
B9.  # стенд: 4 тома, EC:2; удалили содержимое двух томов
```text
<details><summary>Ответ</summary>

⚠️ Запись упадёт: при K=M=2 нужен кворум 3 диска, осталось 2. Чтение при этом работает.

</details>

```text:no-line-numbers
     mc cp /files/new.txt local/demo/
```text
```text:no-line-numbers
B10.  mc ilm rule add local/pg-backups --expire-days 30 --expire-delete-marker
```text
<details><summary>Ответ</summary>

⚠️ `ExpiredObjectDeleteMarker` нельзя сочетать с `Days` в одном Expiration по спецификации
S3 — разнести на два правила (`--expire-days` и `--noncurrent-expire-days` + `--expire-delete-marker`).

</details>

```text:no-line-numbers
B11.  # приложение в k8s ходит в MinIO с root-ключом из Secret
```text
<details><summary>Ответ</summary>

⚠️ Root-ключ в приложении: взлом пода = полный контроль над хранилищем, нельзя
ротировать без простоя всех. Отдельный пользователь с политикой на один бакет.

</details>

```text:no-line-numbers
     MINIO_ACCESS_KEY: admin
```text
```text:no-line-numbers
B12.  openssl req -x509 ... -subj "/CN=minio"      # без -addext subjectAltName
```text
<details><summary>Ответ</summary>

⚠️ Современные клиенты проверяют SAN, а не CN: сертификат не валиден для IP
`192.168.121.1`. Добавить `-addext "subjectAltName=...,IP:192.168.121.1"`.

</details>

```text:no-line-numbers
     # клиент ходит на https://192.168.121.1:9000
```text
---

### Блок C. Практика


### C1. 🔑 Стенд MinIO и первый бакет
**1.** Подними compose из конспекта, настрой алиас `mc` и `local`.

<details><summary>Ответ</summary>

`mc admin info local` покажет `4 drives online, 0 drives offline` и `EC:2` (для set из 4 дисков).
Файлы: `cp ~/file{1,2,3} ~/labs/storage/minio/files/`, затем `mc mb local/demo`,
`mc cp /files/file1 /files/file2 /files/file3 local/demo/`, `mc ls local/demo`, `mc du local/demo`.
В консоли видна навигация по объектам.

</details>

**2.** `mc admin info local`: сколько дисков, какой EC?

<details><summary>Ответ</summary>

После стирания `d4`: чтение и запись работают, `mc admin info` покажет проблему с
одним диском (offline/unformatted). После стирания `d3`: чтение работает (нужно K=2 части),
запись падает (кворум 3). После рестарта MinIO видит пустые диски как новые, форматирует
и лечит (heal) данные в фоне; `mc admin info` вернётся к 4 online.

</details>

**3.** Создай бакет `demo`, загрузи через `./files` 3 файла, выведи список и размер бакета.

<details><summary>Ответ</summary>

`mc mb --with-versioning local/pg-backups`, политика и пользователь — как в конспекте.
Загрузка и чтение проходят, `mc rm` → `Access Denied`, `mc ls pgb` → отказ (нет
`s3:ListAllMyBuckets`), `mc ls pgb/pg-backups` работает. Версии: `mc ls --versions local/pg-backups`
от имени `admin` покажет три версии файла.

</details>

**4.** Зайди в консоль `http://localhost:9001` и найди файлы.

<details><summary>Ответ</summary>

`mc version enable local/demo`; три `mc cp`; `mc rm local/demo/note.txt`;
`mc undo local/demo/note.txt` снимает delete marker — снова видна последняя версия. Первая
версия: `mc ls --versions local/demo/note.txt` → взять её ID →
`mc cp --version-id &lt;VID1&gt; local/demo/note.txt /files/note-v1.txt`.

</details>

### C2. 🔑 Erasure coding руками
**1.** Загрузи в `demo` файл `hello.txt`.

<details><summary>Ответ</summary>

`mc admin info local` покажет `4 drives online, 0 drives offline` и `EC:2` (для set из 4 дисков).
Файлы: `cp ~/file{1,2,3} ~/labs/storage/minio/files/`, затем `mc mb local/demo`,
`mc cp /files/file1 /files/file2 /files/file3 local/demo/`, `mc ls local/demo`, `mc du local/demo`.
В консоли видна навигация по объектам.

</details>

**2.** ⚠️ Сотри содержимое тома `d4` (только на стенде!):
   `docker run --rm -v minio_d4:/d alpine find /d -mindepth 1 -delete`.

<details><summary>Ответ</summary>

После стирания `d4`: чтение и запись работают, `mc admin info` покажет проблему с
одним диском (offline/unformatted). После стирания `d3`: чтение работает (нужно K=2 части),
запись падает (кворум 3). После рестарта MinIO видит пустые диски как новые, форматирует
и лечит (heal) данные в фоне; `mc admin info` вернётся к 4 online.

</details>

**3.** Прочитай `hello.txt`, загрузи новый файл. Что показывает `mc admin info local`?

<details><summary>Ответ</summary>

`mc mb --with-versioning local/pg-backups`, политика и пользователь — как в конспекте.
Загрузка и чтение проходят, `mc rm` → `Access Denied`, `mc ls pgb` → отказ (нет
`s3:ListAllMyBuckets`), `mc ls pgb/pg-backups` работает. Версии: `mc ls --versions local/pg-backups`
от имени `admin` покажет три версии файла.

</details>

**4.** Сотри ещё и `d3`. Что с чтением, что с записью? Почему?

<details><summary>Ответ</summary>

`mc version enable local/demo`; три `mc cp`; `mc rm local/demo/note.txt`;
`mc undo local/demo/note.txt` снимает delete marker — снова видна последняя версия. Первая
версия: `mc ls --versions local/demo/note.txt` → взять её ID →
`mc cp --version-id &lt;VID1&gt; local/demo/note.txt /files/note-v1.txt`.

</details>

**5.** `docker compose restart minio` и понаблюдай за восстановлением.

<details><summary>Ответ</summary>

`mc mb --with-lock local/locked`, `mc retention set --default GOVERNANCE "1d" local/locked`.
Удаление версии (`mc rm --version-id`) — отказ «WORM protected». Обычный `mc rm` проходит:
ставит delete marker, заблокированная версия цела (`mc ls --versions`). Legal hold
(`mc legalhold set`) — бессрочная блокировка без даты окончания, снимается явно
(`mc legalhold clear`) и действует независимо от retention.

</details>

### C3. 🔑 Бэкап-пользователь без права удаления
**1.** Создай бакет `pg-backups` с versioning.

<details><summary>Ответ</summary>

`mc admin info local` покажет `4 drives online, 0 drives offline` и `EC:2` (для set из 4 дисков).
Файлы: `cp ~/file{1,2,3} ~/labs/storage/minio/files/`, затем `mc mb local/demo`,
`mc cp /files/file1 /files/file2 /files/file3 local/demo/`, `mc ls local/demo`, `mc du local/demo`.
В консоли видна навигация по объектам.

</details>

**2.** Создай политику `pg-backup-rw` из конспекта и пользователя `pg-backup`.

<details><summary>Ответ</summary>

После стирания `d4`: чтение и запись работают, `mc admin info` покажет проблему с
одним диском (offline/unformatted). После стирания `d3`: чтение работает (нужно K=2 части),
запись падает (кворум 3). После рестарта MinIO видит пустые диски как новые, форматирует
и лечит (heal) данные в фоне; `mc admin info` вернётся к 4 online.

</details>

**3.** От его имени: загрузи файл, прочитай, попробуй удалить, попробуй `mc ls` без бакета.

<details><summary>Ответ</summary>

`mc mb --with-versioning local/pg-backups`, политика и пользователь — как в конспекте.
Загрузка и чтение проходят, `mc rm` → `Access Denied`, `mc ls pgb` → отказ (нет
`s3:ListAllMyBuckets`), `mc ls pgb/pg-backups` работает. Версии: `mc ls --versions local/pg-backups`
от имени `admin` покажет три версии файла.

</details>

**4.** Перезапиши файл дважды и найди все версии от имени `admin`.

<details><summary>Ответ</summary>

`mc version enable local/demo`; три `mc cp`; `mc rm local/demo/note.txt`;
`mc undo local/demo/note.txt` снимает delete marker — снова видна последняя версия. Первая
версия: `mc ls --versions local/demo/note.txt` → взять её ID →
`mc cp --version-id &lt;VID1&gt; local/demo/note.txt /files/note-v1.txt`.

</details>

### C4. Versioning и откат
В `demo` с versioning: загрузи `note.txt` трижды с разным содержимым, удали его,
восстанови последнюю версию, затем достань самую первую версию в отдельный файл.

### C5. Object lock
**1.** Создай `locked` с lock, retention по умолчанию GOVERNANCE 1d.

<details><summary>Ответ</summary>

`mc admin info local` покажет `4 drives online, 0 drives offline` и `EC:2` (для set из 4 дисков).
Файлы: `cp ~/file{1,2,3} ~/labs/storage/minio/files/`, затем `mc mb local/demo`,
`mc cp /files/file1 /files/file2 /files/file3 local/demo/`, `mc ls local/demo`, `mc du local/demo`.
В консоли видна навигация по объектам.

</details>

**2.** Загрузи файл, попробуй удалить его версию. Затем обычный `mc rm` — что изменилось?

<details><summary>Ответ</summary>

После стирания `d4`: чтение и запись работают, `mc admin info` покажет проблему с
одним диском (offline/unformatted). После стирания `d3`: чтение работает (нужно K=2 части),
запись падает (кворум 3). После рестарта MinIO видит пустые диски как новые, форматирует
и лечит (heal) данные в фоне; `mc admin info` вернётся к 4 online.

</details>

**3.** Поставь legal hold и объясни, чем он отличается от retention.

<details><summary>Ответ</summary>

`mc mb --with-versioning local/pg-backups`, политика и пользователь — как в конспекте.
Загрузка и чтение проходят, `mc rm` → `Access Denied`, `mc ls pgb` → отказ (нет
`s3:ListAllMyBuckets`), `mc ls pgb/pg-backups` работает. Версии: `mc ls --versions local/pg-backups`
от имени `admin` покажет три версии файла.

</details>

### C6. Lifecycle для бэкапов
Настрой на `pg-backups`: текущие объекты живут 30 дней, неактуальные версии — 7 дней,
осиротевшие delete marker'ы чистятся. Проверь правила и объясни, почему это два правила.

### C7. RWX-том через NFS в kind
**1.** На `stor1` экспортируй `/srv/nfs/k8s` для сети, из которой ходят ноды kind.

<details><summary>Ответ</summary>

`mc admin info local` покажет `4 drives online, 0 drives offline` и `EC:2` (для set из 4 дисков).
Файлы: `cp ~/file{1,2,3} ~/labs/storage/minio/files/`, затем `mc mb local/demo`,
`mc cp /files/file1 /files/file2 /files/file3 local/demo/`, `mc ls local/demo`, `mc du local/demo`.
В консоли видна навигация по объектам.

</details>

**2.** Установи csi-driver-nfs, создай StorageClass и PVC `ReadWriteMany`.

<details><summary>Ответ</summary>

После стирания `d4`: чтение и запись работают, `mc admin info` покажет проблему с
одним диском (offline/unformatted). После стирания `d3`: чтение работает (нужно K=2 части),
запись падает (кворум 3). После рестарта MinIO видит пустые диски как новые, форматирует
и лечит (heal) данные в фоне; `mc admin info` вернётся к 4 online.

</details>

**3.** Запусти Deployment из 2 реплик, которые пишут в общий файл своё имя пода. Убедись,
   что оба пишут, и найди подкаталог PV на сервере.

<details><summary>Ответ</summary>

`mc mb --with-versioning local/pg-backups`, политика и пользователь — как в конспекте.
Загрузка и чтение проходят, `mc rm` → `Access Denied`, `mc ls pgb` → отказ (нет
`s3:ListAllMyBuckets`), `mc ls pgb/pg-backups` работает. Версии: `mc ls --versions local/pg-backups`
от имени `admin` покажет три версии файла.

</details>

### C8. TLS для MinIO
Сгенерируй самоподписанный сертификат с SAN на `localhost`, `127.0.0.1` и
`192.168.121.1`, перезапусти MinIO с `--certs-dir`, подключись `mc` по https.

### C9. Уведомления
Подними простой приёмник (`python3 -m http.server` не подойдёт — нужен POST; используй
`nc -lk 8080` на хосте), настрой webhook и событие `put` на `demo`, загрузи файл и найди
событие в выводе.

---

### Блок D. Инциденты


**D1.** Ночью NFS-сервер перезагрузился. Утром на веб-серверах load average 80, CPU простаивает,
`ls /var/www/uploads` висит. Что происходит и как лечить?

<details><summary>Ответ</summary>

`hard`-монтирование: процессы, обратившиеся к недоступному серверу, в состоянии `D`
(считаются в load average, CPU не едят). Если сервер уже поднялся — они продолжат сами;
проверить `showmount`/`rpcinfo`, экспорт, firewall. Если сервер не вернётся — `umount -f -l`
и рестарт сервисов. Итоги: HA для NFS или перенос загрузок в S3, `_netdev,nofail`,
мониторинг NFS.

</details>

**D2.** После переезда NFS-сервера в другую подсеть клиенты монтируются, но `showmount -e`
ничего не показывает, а часть клиентов не монтирует вовсе.

<details><summary>Ответ</summary>

Клиенты, скорее всего, на NFSv4, а `showmount -e` — механизм v3 (mountd). Не
монтируются те, что по умолчанию пошли на v3 и упёрлись в firewall (rpcbind/mountd) или
в экспорт со старой подсетью. Исправить `/etc/exports` под новую подсеть, `exportfs -ra`,
монтировать явно `vers=4.2`.

</details>

**D3.** Под с PVC на nfs-csi в `ContainerCreating`: `mount.nfs: access denied by server`.

<details><summary>Ответ</summary>

Сервер отказал по экспорту: IP ноды не входит в разрешённую сеть (часто ноды
выходят через NAT/другой интерфейс), или экспорт не применён. Посмотреть на сервере
`exportfs -v` и лог `rpc.mountd`, какой IP стучится, поправить `/etc/exports`, `exportfs -ra`.

</details>

**D4.** Приложение в поде (`runAsUser: 1000`) пишет в RWX-том: `Permission denied`.

<details><summary>Ответ</summary>

Каталог PV создан от root, а при `root_squash` принадлежит `nobody`; `fsGroup` на NFS не
помогает. Варианты: `mountPermissions: "0777"`/`"0770"` в параметрах csi-driver-nfs,
`all_squash,anonuid=1000,anongid=1000` на экспорте, chown каталога на сервере под UID
приложения.

</details>

**D5.** CI упал: `Error response from daemon: pull access denied for minio/minio`.

<details><summary>Ответ</summary>

С сентября 2026 образ `minio/minio` удалён с Docker Hub. Быстро: перепиннить на
поддерживаемый образ (форк `pgsty/silo:RELEASE...` или AIStor) и завести зеркало образов
в своём registry, чтобы внешние изменения не роняли CI.

</details>

**D6.** Бэкапы в MinIO «пропали»: `mc ls local/pg-backups` пуст, хотя вчера там были файлы.
Бакет с versioning.

<details><summary>Ответ</summary>

Скорее всего, объекты «удалены» delete marker'ами (кто-то сделал `mc rm -r` или
отработал `mirror --remove`) — данные в версиях. Проверить `mc ls --versions local/pg-backups`,
восстановить `mc undo` или копированием нужных версий. Затем выяснить, чей ключ удалял
(`mc admin trace`, аудит-логи), и отобрать у него `DeleteObject`.

</details>

**D7.** WAL-G от пользователя `pg-backup` падает на загрузке больших файлов с `AccessDenied`,
маленькие проходят.

<details><summary>Ответ</summary>

Большие файлы грузятся multipart'ом: если политика не покрывает бакет/объекты
правильно или нет `s3:AbortMultipartUpload`/`s3:ListMultipartUploadParts`, отдельные вызовы
multipart получают отказ. Проверить `mc admin trace -v local` — какое действие отклонено —
и добавить его в политику.

</details>

**D8.** Диски MinIO заполнены на 95%, хотя lifecycle «удалять через 30 дней» настроен.

<details><summary>Ответ</summary>

Versioning: правило `--expire-days` для текущих объектов только ставит delete marker,
а неактуальные версии занимают место вечно. Нужно `--noncurrent-expire-days` (+ очистка
delete marker'ов). Ещё причины: object lock держит версии, сканер отстаёт, незавершённые
multipart-загрузки.

</details>

**D9.** После включения TLS клиенты в k8s пишут `x509: certificate is valid for minio, localhost,
not 10.96.14.2`.

<details><summary>Ответ</summary>

Клиенты ходят по ClusterIP, которого нет в SAN. Ходить по DNS-имени, включённому в
SAN (например, `minio.storage.svc`), или перевыпустить сертификат с нужными именами — лучше
через cert-manager.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Когда выберешь NFS, а когда S3?

<details><summary>Ответ</summary>

S3 — для бэкапов, артефактов, медиа, логов: HTTP API, дёшево, версии и lock. NFS — когда
   приложению нужна POSIX-папка на нескольких серверах (legacy, RWX); БД — ни туда, ни туда.

</details>

**2.** Какие проблемы у NFS в продакшене?

<details><summary>Ответ</summary>

Сервер — SPOF; `hard`-монтирование вешает клиентов в D; close-to-open consistency и кэш
   атрибутов; права по UID/GID и squash; нет квот на уровне PVC; плохо для БД.

</details>

**3.** Как дать RWX-том в Kubernetes on-prem?

<details><summary>Ответ</summary>

csi-driver-nfs с внешним NFS (или CephFS через Rook — тема 05): StorageClass
   `nfs.csi.k8s.io`, PVC `ReadWriteMany`, экспорт только на IP нод, квоты на сервере.

</details>

**4.** Что такое erasure coding и чем он лучше/хуже репликации?

<details><summary>Ответ</summary>

Объект режется на K частей данных и M чётности, можно потерять M. Экономнее репликации
   (4+2 — 67% полезных вместо 33% при 3 копиях), но больше CPU, сетевых операций и задержка
   на запись и восстановление.

</details>

**5.** Как устроен распределённый MinIO и как его расширять?

<details><summary>Ответ</summary>

N серверов × M дисков, диски делятся на erasure sets, объекты раскладываются по set
   хешированием; перед кластером — балансировщик. Расширение — новым server pool, set не меняется.

</details>

**6.** Как защитить бэкапы в объектном хранилище от шифровальщика?

<details><summary>Ответ</summary>

Отдельный бакет, versioning, object lock, у бэкап-пользователя нет `DeleteObject*`,
   удаление старого — lifecycle на сервере, копия вне площадки, мониторинг и restore-тесты.

</details>

**7.** Что такое object lock и чем GOVERNANCE отличается от COMPLIANCE?

<details><summary>Ответ</summary>

WORM-блокировка версий объекта на срок. GOVERNANCE обходится спецправом, COMPLIANCE — никем
   до конца срока; включается только при создании бакета.

</details>

**8.** Что произошло с MinIO и что бы ты выбрал сейчас для self-hosted S3?

<details><summary>Ответ</summary>

Community урезали, перевели на исходники, заархивировали, убрали образы. Выбор: при
   наличии Ceph — RGW; иначе SeaweedFS или Garage, а если нужна совместимость с MinIO — форк
   `pgsty/silo` или AIStor по подписке; решение — по лицензии, поддержке и выходу security-фиксов.

</details>

**9.** Как выдать приложению доступ к одному бакету?

<details><summary>Ответ</summary>

Отдельный пользователь (или access key), политика с `ListBucket` на бакет и нужными
   `Get/PutObject` на `бакет/*`, ключ — в Secret/Vault, ротация.

</details>

**10.** Какие альтернативы MinIO знаешь?

<details><summary>Ответ</summary>

Ceph RGW, SeaweedFS, Garage, AIStor, форк `pgsty/silo`, облачные S3-совместимые сервисы.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Выбираю NFSv4.1+ и объясняю close-to-open consistency
- [ ] Знаю, почему БД не кладут на NFS и почему NFS-сервер — SPOF
- [ ] Поднял csi-driver-nfs и RWX-том, объясняю, что размер PVC на NFS не квота
- [ ] Рассказываю про статус MinIO Community и варианты замены без эмоций, с датами
- [ ] ⭐ Считаю ёмкость и кворумы erasure coding, проверил отказ дисков на стенде
- [ ] Создаю пользователей и политики через `mc`, у бэкап-пользователя нет удаления
- [ ] Работаю с версиями: откат, delete marker, восстановление старой версии
- [ ] Настроил object lock (GOVERNANCE) и lifecycle из двух правил
- [ ] Включил TLS с правильным SAN
- [ ] Знаю альтернативы: Ceph RGW, SeaweedFS, Garage
