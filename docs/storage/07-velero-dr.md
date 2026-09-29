---
title: "07. Velero и disaster recovery"
description: "Блок → Хранилища и stateful → тема 07. Опирается на"
---

# 07. Velero и disaster recovery

> Блок → Хранилища и stateful → тема 07. Опирается на
> [../Kubernetes/21_advanced_paths.md](/kubernetes/21-advanced-paths) (раздел «Бэкап etcd и DR»:
> снапшот etcd, таблица «etcd vs Velero»), [../Project/09_backup_dr.md](/project/09-backup-dr)
> (бэкап linkd в MinIO, учения, RPO/RTO) и [../SRE/05_postmortems.md](/sre/05-postmortems).
> Бэкапы БД — в [06_db_backup_replication.md](/storage/06-db-backup-replication), тома и снапшоты CSI —
> в [05_k8s_stateful.md](/storage/05-k8s-stateful), MinIO — в [03_nfs_minio.md](/storage/03-nfs-minio).
>
> **После темы ты умеешь:** построить стратегию бэкапов (3-2-1-1-0, RPO/RTO по слоям), поставить
> Velero с MinIO, бэкапить namespace вместе с томами (CSI-снапшоты, data mover, Kopia),
> восстановить его в другой namespace или кластер, написать DR-план и провести учения —
> и назвать типовые причины, по которым «бэкап есть, а восстановить нельзя».

---

## 🗺️ Карта темы

```text
        что теряем?                       чем закрываем                   куда кладём
 ─────────────────────────       ──────────────────────────────      ──────────────────────
 объекты k8s (манифесты)   ──►   git (GitOps) + Velero          ──┐
 данные томов (PVC)        ──►   Velero: CSI-снапшот / Kopia    ──┼──►  MinIO/S3 вне кластера
 базы данных               ──►   WAL-G / pgBackRest / CNPG (06) ──┤     версии + object lock
 состояние кластера (etcd) ──►   etcd snapshot                  ──┤     копия вне площадки
 секреты и ключи           ──►   Vault snapshot / офлайн-копия  ──┘
                                        │
                                        ▼
                  DR-план (кто, что, в каком порядке, за сколько)
                                        │
                                        ▼
                  учения: восстановили и ЗАМЕРИЛИ фактические RPO/RTO
```text
---

## 1. Стратегия: от 3-2-1 к 3-2-1-1-0

Правило 3-2-1 уже есть в [../Left/01_Databases/05_backup_restore.md](/databases/05-backup-restore).
Против шифровальщиков и собственных ошибок его расширяют:

```text
3  копии данных (прод + 2 бэкапа)
2  разных носителя/системы (Ceph в кластере + MinIO на другом железе)
1  копия вне площадки (другой ЦОД / облачный бакет)
1  копия неизменяемая или офлайн (object lock COMPLIANCE, лента, отключённый диск)
0  ошибок при проверке восстановления (restore-test прошёл, а не «бэкап-джоба зелёная»)
```text
| Угроза | Что спасает | Что НЕ спасает |
|--------|-------------|----------------|
| Умер диск/нода | Репликация (Ceph size 3, реплика БД) | — |
| `DROP TABLE`, кривая миграция | PITR из бэкапа | Реплика, RAID, снапшот после ошибки |
| `kubectl delete ns prod` | Velero + бэкап БД; GitOps для манифестов | Реплика БД внутри того же namespace |
| Шифровальщик с правами прода | Immutable-копия (object lock), отдельные учётки | Бэкап, который прод может удалить |
| Потеря площадки (пожар, отключение ЦОД) | Off-site копия + DR-план + второй кластер | Всё, что в той же стойке |
| Утечка/потеря ключей шифрования | Отдельное хранение ключей и паролей репозиториев | Зашифрованный бэкап без ключа |

> ⭐ Бэкап защищает от **ошибок и злого умысла**, репликация — от **отказов железа**.
> Нужны оба; путать их — источник половины инцидентов с данными.

---

## 2. Бэкап, репликация, снапшот

| | Бэкап | Репликация | Снапшот |
|---|-------|-----------|---------|
| Что это | Независимая копия на другом носителе | Непрерывная копия изменений | Мгновенный снимок состояния тома в той же системе |
| Защита от отказа железа | Да (медленно, RTO часы) | ⭐ Да (быстро, RTO минуты) | Нет — живёт на тех же дисках |
| Защита от удаления/порчи | ⭐ Да (точка в прошлом) | Нет — ошибка реплицируется | Да, пока жива система хранения |
| RPO | От минут (WAL) до суток | Секунды / 0 для синхронной | Момент снапшота |
| Хранение | Недели/месяцы, retention | Только «сейчас» | Часы/дни, копятся и тормозят |
| Примеры | WAL-G, pgBackRest, Velero + Kopia | Streaming replication, Ceph size 3, RAID 1 | LVM snapshot, VolumeSnapshot CSI, ZFS snapshot |

Снапшот становится бэкапом, только когда его **вывезли** в другое хранилище (`zfs send`,
Velero data mover, `rbd export`). Об этом раздел 7.

---

## 3. RPO/RTO по слоям

Термины RPO/RTO — в [../Left/01_Databases/05_backup_restore.md](/databases/05-backup-restore).
Для платформы их задают **по слоям**, потому что восстанавливаются слои по-разному:

| Слой | Механизм | Типичный RPO | Типичный RTO | От чего зависит RTO |
|------|----------|--------------|--------------|---------------------|
| Манифесты, чарты | git + Argo CD | 0 (всё в git) | 10–30 мин | Скорость bootstrap кластера |
| Объекты вне git (CR операторов, ручные секреты) | Velero, расписание раз в час | ≤ 1 ч | 5–15 мин | Порядок: CRD → операторы → CR |
| Тома приложений (PVC) | Velero Kopia / CSI + data mover | 1–24 ч | Объём ÷ пропускная способность | Размер данных, канал до S3 |
| PostgreSQL | basebackup + WAL (WAL-G/CNPG) | ≤ 5 мин | 30 мин – часы | Размер базы + объём WAL для доигрывания |
| Секреты и ключи | Vault snapshot / офлайн-копия | часы | минуты | Есть ли ключи распечатки и у кого |
| Объектное хранилище | Репликация бакета на вторую площадку | минуты | минуты | DNS/эндпоинт приложения |

> 💡 RTO «всего сервиса» = сумма последовательных шагов, а не максимум из таблицы:
> кластер (20 мин) + секреты (10) + база (60) + приложения (10) + DNS (5) ≈ 1 ч 45 мин.
> Поэтому DR-учения почти всегда показывают RTO хуже, чем «в голове».

---

## 4. Velero: как устроен

```text
 velero CLI ──► создаёт CR в namespace velero
                   Backup · Restore · Schedule · BackupStorageLocation (BSL)
                   VolumeSnapshotLocation (VSL) · BackupRepository · DataUpload/PodVolumeBackup
                      │
                      ▼
 Deployment velero (сервер) ── плагины (velero-plugin-for-aws — любой S3, включая MinIO)
   │  1. читает объекты через API server (фильтры: ns, labels, resources)
   │  2. складывает их JSON в tar.gz → BSL (бакет velero/backups/&lt;имя&gt;/)
   │  3. тома: CSI VolumeSnapshot  или  задание для node-agent
   ▼
 DaemonSet node-agent (Kopia) ── читает данные томов с ноды (/var/lib/kubelet/pods)
                                 → дедуплицированный, зашифрованный репозиторий в том же бакете
```text
| Объект | Зачем |
|--------|-------|
| `BackupStorageLocation` | Куда класть: бакет, префикс, endpoint, `accessMode: ReadWrite/ReadOnly` |
| `VolumeSnapshotLocation` | Где снапшоты дисков через плагин провайдера (облачные диски); для CSI не нужен |
| `Backup` / `Restore` | Разовая операция |
| `Schedule` | Cron + шаблон Backup + TTL |
| `BackupRepository` | Kopia-репозиторий на namespace; Velero сам делает maintenance (GC, компактизацию) |

Версии на сентябрь 2026: **Velero v1.18.3** (репозиторий переехал в организацию `velero-io`),
**velero-plugin-for-aws v1.14.x** (пара для 1.18.x; для 1.17 — 1.13.x).
Restic как uploader устарел: в 1.17–1.18 новые бэкапы через restic отключены (старые ещё
восстанавливаются), с 1.19 restic убирают полностью. Всё новое — **Kopia**.

---

## 5. Установка с MinIO

Пользователь и политика в MinIO (клиент `mc` — из [03_nfs_minio.md](/storage/03-nfs-minio)):

```json
// files/velero-policy.json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation", "s3:ListBucketMultipartUploads"],
      "Resource": ["arn:aws:s3:::velero"] },
    { "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject",
                 "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"],
      "Resource": ["arn:aws:s3:::velero/*"] }
  ]
}
```text
```bash
mc mb --with-versioning local/velero          # версии: удаление Velero'ом ≠ потеря навсегда
mc admin user add local velero 'velero-secret-123'
mc admin policy create local velero-rw /files/velero-policy.json
mc admin policy attach local velero-rw --user velero
```text
> Velero **нужно** право `DeleteObject`: он сам удаляет бэкапы по TTL. Защиту от «удалил
> взломщик» даёт версионирование + lifecycle на старые версии, а для off-site копии —
> отдельный бакет с object lock, куда Velero не пишет напрямую (репликация бакета).

CLI и установка в кластер (kind `devops`, MinIO подключён к сети kind — см. [00_INDEX.md](/storage/)):

```bash
curl -fsSL -o /tmp/velero.tgz \
  https://github.com/velero-io/velero/releases/download/v1.18.3/velero-v1.18.3-linux-amd64.tar.gz
tar -xzf /tmp/velero.tgz -C /tmp && sudo install /tmp/velero-v1.18.3-linux-amd64/velero /usr/local/bin/
velero version --client-only

docker network connect kind minio 2>/dev/null || true
MINIO_IP=$(docker inspect -f '&#123;&#123;(index .NetworkSettings.Networks "kind").IPAddress&#125;&#125;' minio)

cat > credentials-velero <<'EOF'
[default]
aws_access_key_id = velero
aws_secret_access_key = velero-secret-123
EOF

velero install \
  --provider aws \
  --plugins velero/velero-plugin-for-aws:v1.14.3 \
  --bucket velero \
  --secret-file ./credentials-velero \
  --use-volume-snapshots=false \
  --backup-location-config region=minio,s3ForcePathStyle="true",s3Url=http://${MINIO_IP}:9000 \
  --use-node-agent \
  --wait

velero backup-location get          # PHASE должна быть Available
kubectl -n velero get pods          # velero-… и node-agent-… на каждой ноде
```text
| Флаг | Зачем |
|------|-------|
| `s3ForcePathStyle="true"` | MinIO работает с path-style URL; без этого загрузка проходит, а скачивание падает |
| `s3Url` | Endpoint S3-совместимого хранилища |
| `--use-volume-snapshots=false` | Не создавать VSL — облачных снапшотов дисков у нас нет |
| `--use-node-agent` | Поставить DaemonSet node-agent для файловых бэкапов томов (Kopia) и data mover |
| `--features=EnableCSI` | Включить интеграцию с CSI-снапшотами (нужно при CSI-хранилище, раздел 7) |
| `--default-volumes-to-fs-backup` | Все тома по умолчанию — через Kopia (opt-out вместо opt-in) |

> ⚠️ Пароль шифрования Kopia-репозиториев лежит в секрете `velero-repo-credentials`
> (ключ `repository-password`) и по умолчанию **одинаковый у всех установок**. Поменяй его
> **до первого бэкапа** (после — старые бэкапы станут нечитаемыми) и сохрани вне кластера:
> без него восстановление в новый кластер невозможно.

---

## 6. Backup, Restore, Schedule

```bash
# разовый бэкап namespace
velero backup create shop-20260927 --include-namespaces shop --wait
velero backup describe shop-20260927 --details     # что попало, тома, ошибки/предупреждения
velero backup logs shop-20260927 | grep -iE 'error|warn'
velero backup get

# фильтры
velero backup create shop-db --include-namespaces shop --selector app=postgres
velero backup create infra --include-resources configmaps,secrets --include-namespaces infra
velero backup create all --exclude-namespaces kube-system,velero

# расписание: каждую ночь в 02:00, хранить 14 дней
velero schedule create shop-nightly --schedule="0 2 * * *" \
  --include-namespaces shop --ttl 336h0m0s
velero schedule get
velero backup create --from-schedule shop-nightly   # внеплановый запуск по шаблону

# восстановление
velero restore create --from-backup shop-20260927 --wait
velero restore describe &lt;restore-name&gt; --details
velero restore logs &lt;restore-name&gt;
```text
Что важно знать о restore:
- Velero **не перезаписывает** существующие объекты: пропускает их с предупреждением.
  Обновить — `--existing-resource-policy=update` (не для всех типов; PVC с данными не «откатит»).
- Порядок восстановления встроенный: сначала CRD, namespace, PV/PVC, потом рабочие нагрузки.
- Статусы: `Completed`, `PartiallyFailed` (читай логи!), `Failed`. `PartiallyFailed` — это
  «данные могли не восстановиться», а не «почти хорошо».
- TTL по умолчанию — 30 дней (`720h`). Истёкшие бэкапы удаляет GC вместе с данными в бакете.

**Хуки** — команды в контейнере до/после бэкапа, чтобы данные на томе были консистентны:

```yaml
# аннотации пода (в шаблоне Deployment/StatefulSet)
metadata:
  annotations:
    pre.hook.backup.velero.io/container: app
    pre.hook.backup.velero.io/command: '["/sbin/fsfreeze", "--freeze", "/data"]'
    post.hook.backup.velero.io/container: app
    post.hook.backup.velero.io/command: '["/sbin/fsfreeze", "--unfreeze", "/data"]'
```text
Для БД правильнее не замораживать ФС, а бэкапить базу её инструментами (тема 06) или
хуком делать дамп на том перед бэкапом. `fsfreeze` требует привилегий в контейнере.

---

## 7. Тома: три способа

| Способ | Как работает | Данные уезжают из кластера? | Требования |
|--------|--------------|-----------------------------|------------|
| **CSI snapshot** | Velero создаёт `VolumeSnapshot`, данные остаются в системе хранения | ❌ Нет (в том же Ceph) | CSI-драйвер со снапшотами, CRD + snapshot-controller, `--features=EnableCSI`, VolumeSnapshotClass с лейблом |
| **CSI + data mover** | Снапшот → временный PVC → node-agent (Kopia) заливает в S3 → снапшот удаляется | ✅ Да | То же + `--use-node-agent`; бэкап с `--snapshot-move-data` |
| **File System Backup (Kopia)** | node-agent читает файлы тома живого пода и заливает в S3 | ✅ Да | `--use-node-agent`; под запущен; том **не** hostPath |

```bash
# CSI (например, Rook-Ceph RBD из темы 05): пометить класс снапшотов для Velero
kubectl label volumesnapshotclass csi-rbdplugin-snapclass velero.io/csi-volumesnapshot-class=true
velero backup create shop-csi --include-namespaces shop --snapshot-move-data --wait
kubectl -n velero get datauploads                      # прогресс выгрузки снапшотов

# FSB: opt-in конкретного тома аннотацией пода …
kubectl -n shop annotate pod/postgres-0 backup.velero.io/backup-volumes=data
# … или все тома бэкапа
velero backup create shop-fs --include-namespaces shop --default-volumes-to-fs-backup --wait
kubectl -n velero get podvolumebackups
```text
> ⚠️ **local-path (kind/k3s) и FSB.** local-path-provisioner по умолчанию создаёт PV типа
> `hostPath`, а FSB hostPath-тома **не поддерживает** — том молча пропускается с
> предупреждением в логах бэкапа. Решение для стенда: PVC с аннотацией `volumeType: local`
> (PV типа `local` — поддерживается), см. [05_k8s_stateful.md](/storage/05-k8s-stateful). В проде —
> CSI-хранилище со снапшотами.

Консистентность: CSI-снапшот — crash-consistent (как выдернуть питание), FSB копирует
файлы **по очереди**, пока приложение пишет — без хуков это не crash-consistent вовсе.
Для файлов пользователей обычно терпимо, для БД — нет (раздел 6, тема 06).

---

## 8. Восстановление в другой namespace и другой кластер

```bash
# в тот же кластер, но в новый namespace — проверка бэкапа без риска для прода
velero restore create shop-check --from-backup shop-20260927 \
  --namespace-mappings shop:shop-restore-check --wait
```text
Другой кластер (DR или миграция):

```text
кластер A (прод) ──► бакет velero в MinIO/S3 ◄── кластер B (DR)
                                                  velero install с тем же bucket/prefix
                                                  BSL accessMode: ReadOnly  ← чтобы B ничего не удалил
                                                  тот же velero-repo-credentials!
```text
```bash
# в кластере B после velero install (с тем же бакетом)
kubectl -n velero patch backupstoragelocation default --type merge \
  -p '{"spec":{"accessMode":"ReadOnly"&#125;&#125;'
velero backup get                                   # бэкапы A видны через синхронизацию BSL
velero restore create --from-backup shop-20260927 --wait
```text
Что ломается при переезде и как чинить:

| Проблема | Решение |
|----------|---------|
| В B нет StorageClass `rook-ceph-block` | ConfigMap `change-storage-class-config` в ns velero с лейблами `velero.io/plugin-config: ""` и `velero.io/change-storage-class: RestoreItemAction`, `data: {rook-ceph-block: local-path}` |
| CR оператора, а оператора в B нет | Сначала оператор (GitOps), потом restore; или бэкап с CRD и восстановление по частям |
| Service `LoadBalancer`/Ingress с IP площадки A | Переопределить значения в B (values окружения), DNS переключить отдельно |
| CSI-снапшоты без data mover | В B данных нет — они остались в хранилище A. Для DR — только `--snapshot-move-data` или FSB |
| Другая версия k8s / удалённые API | Velero сохраняет объекты в предпочтительной версии API; нет её в B — объект не восстановится. Проверяй deprecated API заранее (или `--features=EnableAPIGroupVersions`) |
| Секреты зашифрованы (Sealed Secrets, SOPS) ключом из A | Ключ контроллера/age-ключ хранится вне кластера и восстанавливается первым |

---

## 9. etcd-снапшот как дополнение

Снапшот etcd и сравнение с Velero — в [../Kubernetes/21_advanced_paths.md](/kubernetes/21-advanced-paths).
Здесь — как они сочетаются:

| Ситуация | Чем восстанавливаться |
|----------|----------------------|
| Сломали control plane самосборного кластера (плохой апгрейд, порча etcd) | etcd-снапшот на тот же кластер |
| Удалили namespace / надо откатить одно приложение | Velero (etcd откатит **весь** кластер) |
| Потеряли кластер целиком | Новый кластер + GitOps + Velero + бэкапы БД; etcd-снапшот чужого кластера не переносится |
| Managed Kubernetes | etcd недоступен — только Velero + GitOps |

```bash
# k3s со встроенным etcd (server --cluster-init): снапшоты по расписанию есть по умолчанию
sudo k3s etcd-snapshot save --name pre-upgrade
sudo k3s etcd-snapshot ls
```text
> Снапшот etcd содержит **секреты кластера** в открытом виде (если не включено шифрование
> at rest). Храни его как секрет, а не как лог.

---

## 10. DR-план

DR-план — короткий документ, по которому **незнакомый с системой дежурный** восстановит
сервис ночью. Пишется заранее, лежит **вне** защищаемой системы (не только в wiki внутри
того же кластера).

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ DR-ПЛАН: shop (prod)                               владелец: platform team  │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Сценарии и цели                                                          │
│    потеря namespace      RPO 1 ч   RTO 30 мин   → Velero + WAL-G            │
│    порча данных БД       RPO 5 мин RTO 1 ч      → PITR (тема 06)            │
│    потеря кластера       RPO 1 ч   RTO 4 ч      → новый кластер + GitOps    │
│    потеря площадки       RPO 1 ч   RTO 8 ч      → DR-площадка, off-site S3  │
│ 2. Кто объявляет DR и кто исполняет (роли из инцидент-менеджмента)          │
│ 3. Где что лежит: бакеты, пароли репозиториев, ключи Vault/SOPS,            │
│    kubeconfig DR-кластера, доступ к DNS — и у кого копии офлайн             │
│ 4. Порядок восстановления (зависимости!):                                   │
│    кластер → CNI/ingress → секреты и ключи → операторы/CRD →                │
│    БД (PITR) → Velero restore приложений → проверки → DNS                   │
│ 5. Команды по шагам (копипастные, проверенные на учениях)                   │
│ 6. Проверка результата: smoke-тесты, число строк/объектов, SLI              │
│ 7. Коммуникация: шаблон статус-апдейта, кому сообщать                       │
│ 8. История учений: дата, сценарий, фактические RPO/RTO, что поправили       │
└─────────────────────────────────────────────────────────────────────────────┘
```text
---

## 11. DR-учения (game day)

Формат game day и роли — в [../SRE/07_practice_labs.md](/mlops/07-practice-labs) (лаба 4),
разбор — по [../SRE/05_postmortems.md](/sre/05-postmortems). Специфика DR:

| Уровень | Сценарий | Что проверяем | Как часто |
|---------|----------|---------------|-----------|
| 1 | Restore-test бэкапа в изолированный namespace/VM автоматически | Бэкап читается, данные на месте | Ежедневно/еженедельно (CronJob) |
| 2 | Восстановить одну таблицу/один namespace по runbook'у | Runbook актуален, права есть | Ежемесячно |
| 3 | «Потеряли кластер»: поднять с нуля в DR-кластере | Порядок зависимостей, ключи, фактический RTO | Раз в квартал |
| 4 | «Потеряли площадку»: переключить пользователей | DNS, off-site копии, коммуникация | Раз в полгода-год |

Правила учений:
- Засекай время **каждого шага** — это и есть фактический RTO, и видно, где узкое место.
- Восстанавливай **из той же копии**, что при реальной аварии (off-site, а не «локальная побыстрее»).
- Исполняет не автор runbook'а — так находятся «очевидные» пропущенные шаги.
- Итог — постмортем с action items, даже если «всё прошло хорошо».

---

## 12. «Бэкап есть, а восстановить нельзя»

| Провал | Как проявляется | Профилактика |
|--------|-----------------|--------------|
| Бэкап лежал в том же кластере/хранилище | Потеряли Ceph — потеряли и бэкапы | Бэкап вне кластера и площадки |
| Нет ключа шифрования | Kopia/WAL-G/pgBackRest-репозиторий не открывается | Пароли и ключи — в офлайн-хранилище, проверка на учениях |
| Бэкап «зелёный», но пустой | Том был hostPath и пропущен; фильтр не тот namespace | `describe --details`, restore-test проверяет данные, а не статус |
| Нет WAL между базовым бэкапом и аварией | PITR упирается в дыру в архиве | Алерт на `pg_stat_archiver.failed_count`, `wal-verify` |
| Версии не совпадают | Бэкап PG 16 не поднимается на PG 17; Velero-плагин не той версии | Версии инструментов фиксируются в DR-плане |
| Восстановили объекты без данных | CSI-снапшоты остались в хранилище умершего кластера | Data mover или FSB для off-site |
| Нет прав / доступов | Учётки к бакету, DNS, облаку — только у уволившегося | Break-glass доступы, проверка на учениях |
| Восстановление дольше RTO | Канал 100 Мбит/с, база 2 ТБ → ~2 суток | Считать RTO от объёма и канала, держать копию ближе |
| Retention удалил нужную точку | Порча обнаружена через 40 дней, хранили 30 | Retention от времени обнаружения проблем + месячные копии |
| Бэкап консистентен «частично» | Файлы БД скопированы на лету, база не стартует | Инструменты БД или хуки, а не копирование файлов |
| Бэкап удалил шифровальщик | Учётка прода имела DeleteObject | Object lock, отдельные учётки, off-site |
| Никто не знает порядок | Приложения поднялись раньше БД и секретов, всё в CrashLoop | DR-план с зависимостями |

---

## 13. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| «У нас Velero, значит, база в безопасности» | FSB копирует файлы БД на лету | БД — WAL-G/pgBackRest/CNPG, Velero — объекты и простые тома |
| Бэкап в бакет того же MinIO, что в кластере | Умер кластер — умер MinIO | MinIO/S3 на другом железе или в другой площадке |
| Не поменяли `velero-repo-credentials` | Общий статический ключ; забыли пароль — не восстановить | Свой пароль до первого бэкапа, копия вне кластера |
| `PartiallyFailed` считают успехом | Часть томов не забэкаплена | Алерт на статус ≠ `Completed`, чтение логов |
| DR-кластер с BSL `ReadWrite` | GC в DR-кластере удаляет бэкапы прода | `accessMode: ReadOnly` в DR |
| Restore поверх живого namespace | Существующее пропущено, получается смесь | Restore в новый namespace или после удаления |
| Только CSI-снапшоты без выгрузки | Это не off-site бэкап | `--snapshot-move-data` |
| Нет алерта на свежесть бэкапа | Schedule сломался месяц назад | Метрики Velero (`velero_backup_last_successful_timestamp`) → алерт |
| DR-план в wiki внутри того же кластера | Документ недоступен именно во время аварии | Копия вне площадки + офлайн |

---

## 💼 Как это в DevOps

- Velero ставят в каждый кластер как «страховку уровня Kubernetes», но основной бэкап
  данных БД делают инструментами БД. На собесе ценится именно это разделение.
- Метрики Velero снимает Prometheus (`/metrics` сервера): алерт «последний успешный бэкап
  старше 25 часов» и «бэкап PartiallyFailed/Failed» — обязательный минимум.
- Restore-test автоматизируют: CronJob/пайплайн раз в сутки восстанавливает последний
  бэкап в `restore-check-&lt;дата&gt;`, проверяет данные и удаляет namespace.
- В on-prem (частый случай в Казахстане) off-site — это второй ЦОД или хотя бы MinIO/NAS
  в другом здании; облачный бакет как off-site возможен не всегда из-за требований к данным —
  это решают с безопасниками заранее.
- DR-план и учения — это то, что отличает «мы делаем бэкапы» от «мы умеем восстанавливаться».
  После учений почти всегда правят и runbook, и RTO.

---

## 📌 Шпаргалка

| Хочу | Команда |
|------|---------|
| Проверить хранилище бэкапов | `velero backup-location get` |
| Бэкап namespace | `velero backup create NAME --include-namespaces NS --wait` |
| Что попало в бэкап | `velero backup describe NAME --details` |
| Логи бэкапа/restore | `velero backup logs NAME` / `velero restore logs NAME` |
| Тома через Kopia | `--default-volumes-to-fs-backup` или аннотация `backup.velero.io/backup-volumes=vol` |
| Снапшоты с выгрузкой в S3 | `--snapshot-move-data` (+ `--features=EnableCSI` при установке) |
| Расписание | `velero schedule create N --schedule="0 2 * * *" --ttl 336h0m0s --include-namespaces NS` |
| Восстановить | `velero restore create --from-backup NAME --wait` |
| В другой namespace | `--namespace-mappings old:new` |
| Обновить существующее | `--existing-resource-policy=update` |
| DR-кластер только читает | patch BSL `{"spec":{"accessMode":"ReadOnly"&#125;&#125;` |
| Сменить StorageClass при restore | ConfigMap с лейблом `velero.io/change-storage-class: RestoreItemAction` |
| Снапшот etcd (k3s) | `sudo k3s etcd-snapshot save --name pre-upgrade` |

---

## 🧠 Что запомнить

1. Бэкап — от ошибок и злого умысла, репликация — от отказов железа, снапшот — ни то ни другое, пока не вывезен.
2. 3-2-1-1-0: плюс неизменяемая копия и ноль ошибок на **проверенном** восстановлении.
3. RPO/RTO задают по слоям; RTO сервиса — сумма шагов восстановления в правильном порядке.
4. Velero бэкапит объекты k8s и тома; БД бэкапят инструментами БД.
5. Тома: CSI-снапшот (остаётся в хранилище), CSI + data mover и Kopia FSB (уезжают в S3).
6. FSB не видит hostPath-тома — local-path по умолчанию именно такой (`volumeType: local` для стенда).
7. Пароль Kopia-репозиториев (`velero-repo-credentials`) — поменять до первого бэкапа и хранить вне кластера.
8. DR-кластер подключает тот же бакет с BSL `ReadOnly`; StorageClass меняют ConfigMap'ом.
9. etcd-снапшот — для отката control plane того же кластера; для потери кластера — GitOps + Velero + бэкапы БД.
10. DR-план лежит вне защищаемой системы и проверяется учениями с замером каждого шага.

➡️ Дальше: [08_practice_labs.md](/softskills/08-practice-labs) · задачи: 07_velero_dr_tasks.md


---

### Блок A. Теория


**A1.** Чем бэкап отличается от репликации и от снапшота? От каких угроз защищает каждый?

<details><summary>Ответ</summary>

Бэкап — независимая копия на другом носителе с историей точек: защищает от удаления,
порчи, шифровальщика, потери площадки (если off-site). Репликация — непрерывная копия
«сейчас»: защищает от отказа железа, но реплицирует ошибки. Снапшот — мгновенный снимок в той
же системе хранения: защищает от логических ошибок, пока жива система, но не от её потери.

</details>

**A2.** Расшифруй 3-2-1-1-0. Зачем добавили «1» и «0»?

<details><summary>Ответ</summary>

3 копии, 2 разных носителя/системы, 1 вне площадки, 1 неизменяемая или офлайн,

</details>

**A3.** ⭐ Почему RPO/RTO задают по слоям (манифесты, тома, БД, секреты), а не «для кластера»?

<details><summary>Ответ</summary>

Слои восстанавливаются разными механизмами, с разной скоростью и из разных мест:
манифесты — из git за минуты, тома — со скоростью канала до S3, БД — с доигрыванием WAL,
секреты — только при наличии ключей. Общий RTO — сумма шагов в порядке зависимостей.

</details>

**A4.** Из каких компонентов состоит Velero? Что делают сервер, node-agent, плагин, BSL?

<details><summary>Ответ</summary>

Сервер (Deployment) обрабатывает CR Backup/Restore/Schedule, читает объекты через API
и пишет их в BSL. Node-agent (DaemonSet) читает данные томов на нодах через Kopia и выполняет
выгрузку снапшотов (data mover). Плагин (velero-plugin-for-aws) реализует работу с конкретным
хранилищем — любым S3-совместимым. BSL описывает бакет, префикс, endpoint и режим доступа.

</details>

**A5.** ⭐ Назови три способа, которыми Velero бэкапит тома. Какой из них не даёт off-site копии?

<details><summary>Ответ</summary>

CSI-снапшот (данные остаются в системе хранения — **не off-site**), CSI-снапшот
с data mover (`--snapshot-move-data`, данные уезжают в S3) и File System Backup через Kopia.

</details>

**A6.** Почему File System Backup не увидит том от local-path-provisioner по умолчанию? Как это обойти на стенде?

<details><summary>Ответ</summary>

Local-path по умолчанию создаёт PV типа `hostPath`; kubelet не монтирует его в
`/var/lib/kubelet/pods/&lt;uid&gt;/volumes`, а FSB читает именно оттуда и hostPath не поддерживает.
На стенде — PVC с аннотацией `volumeType: local` (или `defaultVolumeType: local` на классе):
PV типа `local` FSB поддерживает.

</details>

**A7.** Что хранится в секрете `velero-repo-credentials` и почему его меняют до первого бэкапа?

<details><summary>Ответ</summary>

Пароль шифрования Kopia-репозиториев (ключ `repository-password`). По умолчанию он
одинаковый у всех установок, а после создания репозитория смена пароля делает старые бэкапы
нечитаемыми. Его же нужно знать в DR-кластере, поэтому хранят вне кластера.

</details>

**A8.** Что делает Velero с объектом при restore, если такой объект уже есть в кластере?

<details><summary>Ответ</summary>

По умолчанию пропускает с предупреждением (не перезаписывает). С
`--existing-resource-policy=update` пытается обновить, но данные томов это не откатывает.

</details>

**A9.** Зачем в DR-кластере переводить BackupStorageLocation в `ReadOnly`?

<details><summary>Ответ</summary>

Чтобы DR-кластер не изменял бакет: его GC мог бы удалять бэкапы прода по TTL, а
случайный бэкап — смешать данные. ReadOnly — только чтение и восстановление.

</details>

**A10.** Как восстановить бэкап в кластер, где нет StorageClass из исходного кластера?

<details><summary>Ответ</summary>

ConfigMap в namespace velero с лейблами `velero.io/plugin-config: ""` и
`velero.io/change-storage-class: RestoreItemAction`, в `data` — пары «старый класс: новый».
Данные при этом должны быть в бэкапе (FSB или data mover), а не в CSI-снапшоте старого хранилища.

</details>

**A11.** Чем crash-consistent копия отличается от копии, которую делает FSB без хуков? Что это значит для БД?

<details><summary>Ответ</summary>

Crash-consistent — состояние на один момент времени, как после выдёргивания питания:
БД поднимется через recovery журнала. FSB копирует файлы последовательно, пока приложение
пишет, поэтому файлы БД могут оказаться из разных моментов — база может не стартовать.
Для БД — инструменты БД (тема 06) или дамп хуком.

</details>

**A12.** Когда восстанавливаться снапшотом etcd, а когда — Velero?

<details><summary>Ответ</summary>

etcd — когда сломан control plane того же самосборного кластера и нужно откатить
всё состояние целиком. Velero — для отдельных namespace/приложений, переноса в другой
кластер, managed Kubernetes и когда нужны данные томов.

</details>

**A13.** Что должно быть в DR-плане? Почему он должен лежать вне защищаемой системы?

<details><summary>Ответ</summary>

Сценарии и цели RPO/RTO, роли (кто объявляет и исполняет), где лежат бэкапы, ключи,
пароли и доступы, порядок восстановления с зависимостями, проверенные команды, критерии
проверки, коммуникация, история учений. Вне системы — потому что во время аварии wiki
в том же кластере недоступна.

</details>

**A14.** ⭐ Почему фактический RTO на учениях почти всегда хуже ожидаемого?

<details><summary>Ответ</summary>

Шаги последовательны и зависят друг от друга, а оценки делают по одному шагу;
всплывают забытые зависимости (ключи, DNS, операторы), скорость канала до off-site копии,
ручные действия и ожидание людей с доступами.

</details>

**A15.** Какие права в MinIO нужны пользователю Velero и почему без `DeleteObject` не обойтись?

<details><summary>Ответ</summary>

`ListBucket`/`GetBucketLocation` на бакет, `GetObject`, `PutObject`, `DeleteObject`,
`AbortMultipartUpload`, `ListMultipartUploadParts` на объекты. `DeleteObject` нужен, потому
что Velero сам удаляет истёкшие по TTL бэкапы и обслуживает Kopia-репозиторий. От злоупотребления
защищают версионирование и отдельная immutable-копия.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  velero install --provider aws --plugins velero/velero-plugin-for-aws:v1.14.3 \
```text
<details><summary>Ответ</summary>

⚠️ Нет `s3ForcePathStyle="true"`: SDK строит virtual-host URL (`velero.172.18.0.5`),
с MinIO загрузка может пройти, а скачивание/листинг — нет. Добавить параметр в BSL.

</details>

```text:no-line-numbers
       --bucket velero --secret-file ./credentials-velero \
```text
```text:no-line-numbers
       --backup-location-config region=minio,s3Url=http://172.18.0.5:9000
```text
```text:no-line-numbers
     # бэкапы создаются, а velero backup get в другом кластере их «не видит» / скачивание падает
```text
```text:no-line-numbers
B2.  velero install ... --plugins velero/velero-plugin-for-aws:v1.9.0   # Velero v1.18.3
```text
<details><summary>Ответ</summary>

⚠️ Плагин 1.9 — для Velero 1.13. Для 1.18.x нужен velero-plugin-for-aws 1.14.x;
несовместимая пара даёт ошибки плагина или странное поведение.

</details>

```text:no-line-numbers
B3.  velero backup create shop --include-namespaces shop
```text
<details><summary>Ответ</summary>

⚠️ Режим opt-in: без аннотации `backup.velero.io/backup-volumes` и без
`--default-volumes-to-fs-backup` том не бэкапится — в бэкапе только манифест PVC.
Плюс local-path hostPath FSB не поддерживает вовсе.

</details>

```text:no-line-numbers
     # PVC shop/data от local-path, node-agent установлен, аннотаций нет
```text
```text:no-line-numbers
B4.  velero backup create shop --include-namespaces shop --default-volumes-to-fs-backup
```text
<details><summary>Ответ</summary>

⚠️ `PartiallyFailed` — часть томов/объектов не сохранена. Читать `backup logs` и
`describe --details` (частая причина — hostPath-том или под не Running), чинить сразу,
алертить на любой статус, кроме `Completed`.

</details>

```text:no-line-numbers
     # статус PartiallyFailed; на следующий день — «ну почти же получилось»
```text
```text:no-line-numbers
B5.  # DR-кластер
```text
<details><summary>Ответ</summary>

⚠️ BSL в DR-кластере в режиме ReadWrite: GC удалит бэкапы прода по TTL, а бэкапы
DR-кластера смешаются с продовыми. Нужен `accessMode: ReadOnly` (или отдельный префикс для
своих бэкапов) и тот же пароль репозитория.

</details>

```text:no-line-numbers
     velero install ... --bucket velero ...     # тот же бакет, что у прода, BSL по умолчанию
```text
```text:no-line-numbers
B6.  velero restore create --from-backup shop-20260927
```text
<details><summary>Ответ</summary>

⚠️ Существующие объекты будут пропущены — «восстановления» не произойдёт, получится
смесь. Восстанавливать в новый namespace (`--namespace-mappings`) или после удаления.

</details>

```text:no-line-numbers
     # namespace shop существует и работает, Deployment с тем же именем уже есть
```text
```text:no-line-numbers
B7.  # Rook-Ceph, EnableCSI включён
```text
<details><summary>Ответ</summary>

⚠️ Без `--snapshot-move-data` данные томов остались CSI-снапшотами в умершем Ceph.
В бэкапе только ссылки на снапшоты. Для off-site — data mover или FSB.

</details>

```text:no-line-numbers
     velero backup create shop-csi --include-namespaces shop
```text
```text:no-line-numbers
     # через неделю кластер вместе с Ceph умер; в новом кластере restore «успешен», тома пустые
```text
```text:no-line-numbers
B8.  # MinIO для бэкапов запущен в том же кластере, в namespace minio, на томах Ceph
```text
<details><summary>Ответ</summary>

⚠️ Бэкапы живут в той же системе, от потери которой должны защищать: умер кластер
или Ceph — умерли и бэкапы. MinIO/S3 — вне кластера и на другом железе.

</details>

```text:no-line-numbers
B9.  velero schedule create shop-nightly --schedule="0 2 * * *" --include-namespaces shop
```text
<details><summary>Ответ</summary>

⚠️ Schedule может молча перестать работать (BSL Unavailable, ошибки, PartiallyFailed).
Нужны алерты на возраст последнего успешного бэкапа и на неуспешные статусы, плюс restore-test.

</details>

```text:no-line-numbers
     # алертов на бэкапы нет; «Schedule же есть»
```text
```text:no-line-numbers
B10.  # хук бэкапа для PostgreSQL
```text
<details><summary>Ответ</summary>

⚠️ Без post-хука ФС останется замороженной — база встанет на записи. К тому же
fsfreeze требует привилегий, а для PostgreSQL правильный путь — WAL-G/pgBackRest/CNPG.

</details>

```text:no-line-numbers
     pre.hook.backup.velero.io/command: '["/sbin/fsfreeze", "--freeze", "/var/lib/postgresql/data"]'
```text
```text:no-line-numbers
     # post-хука нет
```text
```text:no-line-numbers
B11.  # DR-план лежит в Confluence, развёрнутом в том же кластере, что и прод
```text
<details><summary>Ответ</summary>

⚠️ Во время аварии кластера план недоступен. Копия вне площадки + офлайн/печатная.

</details>

```text:no-line-numbers
B12.  # retention бэкапов БД — 7 дней; порчу данных заметили через 3 недели
```text
<details><summary>Ответ</summary>

⚠️ Retention должен покрывать время обнаружения проблем: нужной точки уже нет.
Добавить недельные/месячные копии (GFS-схема) и мониторинг целостности данных.

</details>


---

### Блок C. Практика


### C1. 🔑 Velero с MinIO
**1.** Создай в MinIO бакет `velero` с версионированием, пользователя `velero` и политику из конспекта.

<details><summary>Ответ</summary>

Команды — в разделе 5 конспекта. Пароль меняют до первого бэкапа:
`kubectl -n velero patch secret velero-repo-credentials -p '{"stringData":{"repository-password":"&lt;свой&gt;"&#125;&#125;'`
(или создать секрет до установки), копию — в менеджер паролей. Бэкапы появятся в
`velero/backups/&lt;имя&gt;/`, данные Kopia — в `velero/kopia/&lt;namespace&gt;/`.

</details>

**2.** Поставь Velero v1.18.3 с плагином v1.14.3, `--use-node-agent`.

<details><summary>Ответ</summary>

Манифест PVC-шаблона с `metadata.annotations: {volumeType: local}`; данные —
`kubectl exec web-0 -- sh -c 'date > /data/stamp; head -c 50M /dev/urandom > /data/blob; sha256sum /data/blob'`.
После restore: `kubectl -n shop exec web-0 -- sha256sum /data/blob` совпадает. Без аннотации
`volumeType: local` blob не восстановится (hostPath-том пропущен — видно в логах бэкапа).

</details>

**3.** Перед первым бэкапом поменяй пароль Kopia-репозитория и сохрани его вне кластера.

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
set -euo pipefail
BACKUP=${1:?backup name}; NS=shop-check-$(date +%s)
velero restore create "$NS" --from-backup "$BACKUP" --namespace-mappings shop:"$NS" --wait
kubectl -n "$NS" wait --for=condition=Ready pod/web-0 --timeout=300s
GOT=$(kubectl -n "$NS" exec web-0 -- sha256sum /data/blob | awk '{print $1}')
WANT=$(cat expected.sha256)
kubectl delete ns "$NS" --wait=false
[ "$GOT" = "$WANT" ] || { echo "restore-check FAILED"; exit 1; }
echo "restore-check OK"
```text
</details>

**4.** Добейся `Available` у BSL. Где в бакете появятся бэкапы?

<details><summary>Ответ</summary>

`velero schedule create shop-hourly --schedule="0 * * * *" --include-namespaces shop --ttl 24h0m0s`.
Алерты:
```promql
time() - velero_backup_last_successful_timestamp{schedule="shop-hourly"} > 2 * 3600
increase(velero_backup_failure_total[1h]) > 0 or increase(velero_backup_partial_failure_total[1h]) > 0
```text
</details>

### C2. 🔑 Namespace с томом: бэкап → удаление → восстановление
**1.** Создай namespace `shop`: StatefulSet `web` (1 реплика, busybox/nginx) с `volumeClaimTemplates`,
   PVC с аннотацией `volumeType: local`; запиши в том файл с датой и 50 МБ случайных данных,
   посчитай `sha256sum`.

<details><summary>Ответ</summary>

Команды — в разделе 5 конспекта. Пароль меняют до первого бэкапа:
`kubectl -n velero patch secret velero-repo-credentials -p '{"stringData":{"repository-password":"&lt;свой&gt;"&#125;&#125;'`
(или создать секрет до установки), копию — в менеджер паролей. Бэкапы появятся в
`velero/backups/&lt;имя&gt;/`, данные Kopia — в `velero/kopia/&lt;namespace&gt;/`.

</details>

**2.** `velero backup create shop-1 --include-namespaces shop --default-volumes-to-fs-backup --wait`.

<details><summary>Ответ</summary>

Манифест PVC-шаблона с `metadata.annotations: {volumeType: local}`; данные —
`kubectl exec web-0 -- sh -c 'date > /data/stamp; head -c 50M /dev/urandom > /data/blob; sha256sum /data/blob'`.
После restore: `kubectl -n shop exec web-0 -- sha256sum /data/blob` совпадает. Без аннотации
`volumeType: local` blob не восстановится (hostPath-том пропущен — видно в логах бэкапа).

</details>

**3.** `kubectl delete ns shop`, восстанови, сверь контрольную сумму.

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
set -euo pipefail
BACKUP=${1:?backup name}; NS=shop-check-$(date +%s)
velero restore create "$NS" --from-backup "$BACKUP" --namespace-mappings shop:"$NS" --wait
kubectl -n "$NS" wait --for=condition=Ready pod/web-0 --timeout=300s
GOT=$(kubectl -n "$NS" exec web-0 -- sha256sum /data/blob | awk '{print $1}')
WANT=$(cat expected.sha256)
kubectl delete ns "$NS" --wait=false
[ "$GOT" = "$WANT" ] || { echo "restore-check FAILED"; exit 1; }
echo "restore-check OK"
```text
</details>

**4.** Засеки время restore — это твой RTO для этого namespace.

<details><summary>Ответ</summary>

`velero schedule create shop-hourly --schedule="0 * * * *" --include-namespaces shop --ttl 24h0m0s`.
Алерты:
```promql
time() - velero_backup_last_successful_timestamp{schedule="shop-hourly"} > 2 * 3600
increase(velero_backup_failure_total[1h]) > 0 or increase(velero_backup_partial_failure_total[1h]) > 0
```text
</details>

### C3. Восстановление рядом с продом
Восстанови `shop-1` в namespace `shop-check`, не трогая `shop`. Проверь данные и удали
`shop-check`. Оформи это как скрипт `restore-check.sh`, который завершается ненулевым кодом,
если контрольная сумма не совпала.

### C4. 🔑 Расписание и алерт
**1.** Создай Schedule раз в час с TTL 24 часа.

<details><summary>Ответ</summary>

Команды — в разделе 5 конспекта. Пароль меняют до первого бэкапа:
`kubectl -n velero patch secret velero-repo-credentials -p '{"stringData":{"repository-password":"&lt;свой&gt;"&#125;&#125;'`
(или создать секрет до установки), копию — в менеджер паролей. Бэкапы появятся в
`velero/backups/&lt;имя&gt;/`, данные Kopia — в `velero/kopia/&lt;namespace&gt;/`.

</details>

**2.** Найди метрики Velero (`kubectl -n velero port-forward deploy/velero 8085:8085`, `/metrics`).

<details><summary>Ответ</summary>

Манифест PVC-шаблона с `metadata.annotations: {volumeType: local}`; данные —
`kubectl exec web-0 -- sh -c 'date > /data/stamp; head -c 50M /dev/urandom > /data/blob; sha256sum /data/blob'`.
После restore: `kubectl -n shop exec web-0 -- sha256sum /data/blob` совпадает. Без аннотации
`volumeType: local` blob не восстановится (hostPath-том пропущен — видно в логах бэкапа).

</details>

**3.** Напиши PromQL-алерт «последний успешный бэкап старше 2 часов» и алерт на неуспешные бэкапы.

<details><summary>Ответ</summary>

```bash
#!/usr/bin/env bash
set -euo pipefail
BACKUP=${1:?backup name}; NS=shop-check-$(date +%s)
velero restore create "$NS" --from-backup "$BACKUP" --namespace-mappings shop:"$NS" --wait
kubectl -n "$NS" wait --for=condition=Ready pod/web-0 --timeout=300s
GOT=$(kubectl -n "$NS" exec web-0 -- sha256sum /data/blob | awk '{print $1}')
WANT=$(cat expected.sha256)
kubectl delete ns "$NS" --wait=false
[ "$GOT" = "$WANT" ] || { echo "restore-check FAILED"; exit 1; }
echo "restore-check OK"
```text
</details>

### C5. Хуки консистентности
Добавь к поду `web` pre/post-хуки, которые делают `sync` и пишут в том файл-маркер
`backup-started` / удаляют его. Убедись по `velero backup describe --details`, что хуки
выполнились. Почему для настоящей БД такой хук не заменяет инструменты БД?

### C6. «Другой кластер»
Подними второй kind-кластер `dr`, поставь в него Velero с тем же бакетом и тем же паролем
репозитория, переведи BSL в `ReadOnly` и восстанови `shop-1`. Что было бы, если бы пароль
репозитория в `dr` оставили по умолчанию?

### C7. 🔑 DR-план на одну страницу
Напиши `docs/dr.md` для стенда: сценарии (потеря namespace, порча БД, потеря кластера),
RPO/RTO целевые и замеренные в C2/C6, где лежат ключи и пароли, порядок восстановления
с зависимостями, проверка результата.

### C8. Учения «потеряли кластер»
`kind delete cluster --name devops` → подними кластер заново → Velero → restore → проверка.
Засеки время каждого шага, найди самый долгий и предложи, как его сократить.

---

### Блок D. Инциденты


**D1.** Бэкапы Velero месяц подряд в статусе `Completed`, но при restore том пустой.

<details><summary>Ответ</summary>

Том не попадал в бэкап: opt-in без аннотации, hostPath-том (local-path) пропускался
с предупреждением, под был не Running. Проверить `describe --details` (раздел Pod Volume
Backups), логи на warnings; включить FSB правильно, restore-test с проверкой данных.

</details>

**D2.** `velero backup-location get` показывает `Unavailable`.

<details><summary>Ответ</summary>

Нет связи с endpoint (сеть kind ↔ MinIO, IP сменился после рестарта контейнера),
неверные ключи или нет прав, нет бакета, не тот `s3Url`/`region`, TLS с самоподписанным
сертификатом без `caCert`. Смотреть `kubectl -n velero logs deploy/velero` и проверять
доступ `mc` с теми же ключами.

</details>

**D3.** Restore завершился `PartiallyFailed`, приложение не стартует.

<details><summary>Ответ</summary>

`velero restore logs` и `describe --details`: какие объекты упали. Частое:
отсутствует CRD/оператор, нет StorageClass, конфликт с существующими объектами, ошибки
restore томов (Kopia, пароль). Чинить причину и повторить restore в чистый namespace.

</details>

**D4.** В DR-кластере после установки Velero пропали старые бэкапы прода из бакета.

<details><summary>Ответ</summary>

BSL в DR-кластере был ReadWrite с другим TTL/ретеншном — GC удалил «истёкшие»
бэкапы. Восстановить из версий бакета (versioning!), перевести BSL в ReadOnly.

</details>

**D5.** После restore в новый кластер поды висят в `Pending`: PVC не могут привязаться.

<details><summary>Ответ</summary>

В новом кластере нет StorageClass из бэкапа или нет default SC. Создать класс с тем
же именем или смапить через `change-storage-class-config` и повторить restore.

</details>

**D6.** Restore в новый кластер: Kopia пишет, что не может открыть репозиторий.

<details><summary>Ответ</summary>

Разный `repository-password` в кластерах. Установить секрет с паролем исходного
кластера, перезапустить velero/node-agent, повторить. Нет пароля — данные томов потеряны.

</details>

**D7.** Восстановление базы 1,5 ТБ из off-site бакета идёт уже 20 часов при RTO 4 часа.

<details><summary>Ответ</summary>

RTO не пересчитывали от объёма и канала: 1,5 ТБ через ~200 Мбит/с — это ~17 часов.
Сейчас — эскалация и коммуникация реального срока. На будущее: копия ближе к площадке
восстановления, реплика БД в DR-площадке (RTO минуты), инкрементальные схемы, замер на учениях.

</details>

**D8.** Шифровальщик получил kubeconfig и ключи MinIO прод-кластера. Что он может уничтожить
и что должно было выжить?

<details><summary>Ответ</summary>

С kubeconfig — удалить всё в кластере, с ключами MinIO прод-учётки — бэкапы в бакетах,
куда у неё есть `DeleteObject`, и текущие версии. Должны выжить: объекты под object lock
(COMPLIANCE), off-site копия, куда прод не имеет прав, git-репозитории, ключи вне кластера.

</details>

**D9.** Бэкап etcd сделан, а после восстановления кластера данные приложений «старые или пропали».

<details><summary>Ответ</summary>

etcd хранит только объекты k8s, а не данные томов и БД. Данные — из бэкапов томов
(Velero/data mover) и БД (PITR). Плюс снапшот etcd откатывает состояние на момент снапшота —
всё созданное позже (новые PVC, секреты) пропадает или рассинхронизируется с хранилищем.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как ты бэкапишь Kubernetes-кластер?

<details><summary>Ответ</summary>

Слоями: манифесты — в git (GitOps), объекты вне git и тома — Velero в S3 вне кластера
   (Kopia или CSI + data mover), БД — своими инструментами с PITR, etcd-снапшот для
   самосборного кластера, секреты и ключи — отдельно. Плюс алерты и restore-test.

</details>

**2.** Чем Velero отличается от снапшота etcd?

<details><summary>Ответ</summary>

Снапшот etcd — всё состояние кластера целиком на момент времени, только для того же
   кластера, без данных томов. Velero — выборочно (namespace, labels), с томами, в другой
   кластер, работает и в managed.

</details>

**3.** Как Velero бэкапит тома? Что выберешь для on-prem с Ceph?

<details><summary>Ответ</summary>

CSI-снапшоты, CSI + data mover, Kopia FSB. On-prem с Ceph: CSI-снапшоты RBD как быстрый
   локальный откат + `--snapshot-move-data` в MinIO на другом железе как настоящий бэкап.

</details>

**4.** Можно ли бэкапить базу данных Velero'ом?

<details><summary>Ответ</summary>

Как «ещё одну копию» — можно, но основной бэкап БД — WAL-G/pgBackRest/CNPG: FSB копирует
   файлы на лету, CSI-снапшот — crash-consistent без PITR.

</details>

**5.** Что такое RPO и RTO? Как их измерить, а не придумать?

<details><summary>Ответ</summary>

RPO — сколько данных теряем, RTO — сколько лежим. Измеряют на учениях: время каждого шага
   восстановления и возраст последней точки восстановления.

</details>

**6.** Что такое правило 3-2-1? Как защитить бэкапы от шифровальщика?

<details><summary>Ответ</summary>

3 копии, 2 носителя, 1 off-site (+1 immutable, 0 ошибок). От шифровальщика: object lock,
   прод без права удалять бэкапы, off-site под другими учётками, ключи вне кластера.

</details>

**7.** Как проверить, что бэкап рабочий?

<details><summary>Ответ</summary>

Регулярно восстанавливать — автоматически в изолированный namespace/VM с проверкой
   данных, и вручную на учениях; алертить на возраст и статус бэкапов.

</details>

**8.** Как перенести namespace в другой кластер?

<details><summary>Ответ</summary>

Velero: бэкап в общий бакет, в целевом кластере Velero с тем же бакетом и паролем
   репозитория, BSL ReadOnly, restore с `--namespace-mappings` и маппингом StorageClass.

</details>

**9.** Что такое DR-план и DR-учения?

<details><summary>Ответ</summary>

DR-план — документ с целями, ролями, порядком и командами восстановления, лежащий вне
   системы. DR-учения — регулярная проверка этого плана на практике с замером RTO/RPO и
   постмортемом.

</details>

**10.** Расскажи о случае (или гипотетическом), когда бэкап есть, а восстановиться нельзя.

<details><summary>Ответ</summary>

Пример ответа: «Бэкап Velero месяц был Completed, но том был hostPath и пропускался;
    нашли на restore-test, перевели на `local`-тома/CSI, добавили проверку данных и алерт
    на PartiallyFailed». Структура: что случилось, почему не заметили, что изменили.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Объясняю разницу бэкап / репликация / снапшот и 3-2-1-1-0
- [ ] Задаю RPO/RTO по слоям и считаю RTO как сумму шагов
- [ ] Velero с MinIO поставлен, BSL `Available`, пароль репозитория свой и сохранён вне кластера
- [ ] ⭐ Namespace с томом забэкаплен, удалён и восстановлен, данные сверены по sha256
- [ ] Знаю, почему local-path hostPath не бэкапится FSB, и как это обойти
- [ ] Восстанавливаю в другой namespace и другой кластер (ReadOnly BSL, маппинг классов)
- [ ] Есть алерты на возраст успешного бэкапа и неуспешные статусы
- [ ] ⭐ DR-план на одну страницу написан, учения «потеряли кластер» проведены и замерены
- [ ] Называю 5+ причин «бэкап есть, а восстановить нельзя»
