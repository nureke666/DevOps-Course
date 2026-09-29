---
title: "05. Stateful в Kubernetes: CSI, StatefulSet, Rook-Ceph, снапшоты"
description: "Блок → Хранилища и stateful → тема 05. Опирается на"
---

# 05. Stateful в Kubernetes: CSI, StatefulSet, Rook-Ceph, снапшоты

> Блок → Хранилища и stateful → тема 05. Опирается на
> [../Kubernetes/14_storage.md](/kubernetes/14-storage) (PV/PVC/SC, access modes, reclaimPolicy),
> [../Kubernetes/06_daemonset_statefulset.md](/kubernetes/06-daemonset-statefulset) (гарантии
> StatefulSet, headless Service) и [04_ceph.md](/storage/04-ceph) (RBD, CephFS, pools).
> Базовые YAML и таблицы оттуда здесь не повторяются — идём глубже.
>
> **После темы ты умеешь:** объяснить, что делает каждый компонент CSI при создании и монтировании
> тома; читать жизненный цикл PV и возвращать `Released`-том; расширять тома StatefulSet;
> поднять Rook-Ceph на трёх нодах и выдать RWO/RWX-тома; снимать и восстанавливать
> VolumeSnapshot; разбирать «Pending PVC» и `Multi-Attach error`; аргументированно решать,
> где жить базе — в кластере под оператором или снаружи.

---

## 🗺️ Карта темы

```text
 PVC ──► external-provisioner ──CreateVolume──► хранилище (Ceph, LVM, облако, NFS)
  │                                                   │
  │  Bound ◄──────────── PV ◄─────────────────────────┘
  ▼
 scheduler выбрал ноду ──► external-attacher ──ControllerPublish──► VolumeAttachment
                                                                          │
 kubelet на ноде ──► CSI node plugin: NodeStage (форматировать, смонтировать глобально)
                                      NodePublish (bind-mount в каталог пода) ──► под пишет
 ───────────────────────────────────────────────────────────────────────────────────────
 вокруг: StatefulSet (свой PVC на под) · VolumeSnapshot · expansion · Rook-оператор
 инциденты: Pending PVC · Multi-Attach · Terminating PVC · «данные остались на мёртвой ноде»
```text
---

## 1. CSI изнутри: кто что делает

В [../Kubernetes/14_storage.md](/kubernetes/14-storage) CSI — это «controller + node».
Внутри controller-части — набор стандартных sidecar-контейнеров от kubernetes-csi, каждый
следит за своими объектами API и дёргает gRPC-метод драйвера:

| Компонент | Где | Следит за | Вызывает у драйвера |
|-----------|-----|-----------|---------------------|
| external-provisioner | controller (Deployment) | PVC | `CreateVolume` / `DeleteVolume` |
| external-attacher | controller | VolumeAttachment | `ControllerPublishVolume` / `Unpublish` |
| external-resizer | controller | PVC (рост `requests.storage`) | `ControllerExpandVolume` |
| external-snapshotter | controller | VolumeSnapshotContent | `CreateSnapshot` / `DeleteSnapshot` |
| node-driver-registrar | node (DaemonSet) | — | регистрирует драйвер в kubelet (`/var/lib/kubelet/plugins_registry`) |
| сам драйвер (node) | node | вызовы kubelet | `NodeStageVolume`, `NodePublishVolume`, `NodeExpandVolume` |

Общий для кластера **snapshot-controller** (не sidecar) превращает VolumeSnapshot
в VolumeSnapshotContent — без него снапшоты не работают вовсе (раздел 8).

```text
Путь тома на ноде (полезно при отладке «куда смонтировалось»):
/var/lib/kubelet/plugins/kubernetes.io/csi/&lt;driver&gt;/&lt;hash&gt;/globalmount   ← NodeStage (раз на ноду)
/var/lib/kubelet/pods/&lt;pod-uid&gt;/volumes/kubernetes.io~csi/&lt;pv&gt;/mount      ← NodePublish (на каждый под)
```text
Служебные объекты:

```bash
kubectl get csidrivers                    # attachRequired, podInfoOnMount, fsGroupPolicy
kubectl get csinode &lt;node&gt; -o yaml        # drivers[].allocatable.count — лимит томов на ноду
kubectl get volumeattachments             # какой PV к какой ноде прицеплен (ATTACHED true/false)
kubectl -n rook-ceph get deploy | grep -i rbd                     # controller-часть RBD-драйвера
kubectl -n rook-ceph logs deploy/&lt;rbd-ctrlplugin&gt; -c csi-provisioner   # логи конкретного sidecar
```text
> 💡 Ошибки в событиях PVC пишет provisioner, ошибки attach — attacher (в событиях пода
> `FailedAttachVolume`), ошибки mount — kubelet (`FailedMount`). По тексту события сразу
> понятно, в какую часть цепочки смотреть.

---

## 2. StorageClass: что важно сверх базовых полей

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: db-ssd
provisioner: rook-ceph.rbd.csi.ceph.com
parameters: { clusterID: rook-ceph, pool: replicapool, csi.storage.k8s.io/fstype: xfs }  # + secret-параметры, раздел 7
reclaimPolicy: Retain                   # для данных БД
allowVolumeExpansion: true
volumeBindingMode: WaitForFirstConsumer
mountOptions: [noatime]                 # драйвер должен их поддерживать, иначе FailedMount
allowedTopologies:                      # выдавать тома только в этих зонах/на этих нодах
  - matchLabelExpressions:
      - key: topology.kubernetes.io/zone
        values: [dc1-a, dc1-b]
```text
- `parameters`, `provisioner`, `reclaimPolicy`, `volumeBindingMode` **неизменяемы** — чтобы
  поменять, создают новый класс и переносят данные.
- `reclaimPolicy` копируется в PV в момент создания. Поменять у готового тома:
  `kubectl patch pv &lt;pv&gt; -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"&#125;&#125;'` — первое, что
  делают, когда «случайно поставили Delete для базы».
- Default-класс — аннотация `storageclass.kubernetes.io/is-default-class: "true"`. Если
  default-классов два, берётся самый свежий — источник сюрпризов после установки нового CSI.
- PVC без `storageClassName` получает default; `storageClassName: ""` — «только статический PV».

---

## 3. Жизненный цикл PV и PVC

```text
            создан/выделен            PVC удалён
 PV:  Available ──► Bound ─────────────────────────┬─► reclaimPolicy Delete: удалить том в хранилище
                     ▲                             │      (ошибка удаления ──► Failed)
                     │ PVC с volumeName            └─► reclaimPolicy Retain: Released
                     │                                    (данные целы, claimRef держит старый PVC)
                     └──────── убрать claimRef ◄──────────┘   ← ручное «переиспользование»
 PVC: Pending ──► Bound ──► (PV пропал) Lost
```text
Вернуть данные из `Released`-тома (например, после случайного `kubectl delete pvc`):

```bash
kubectl patch pv pvc-8f3a... --type json -p '[{"op":"remove","path":"/spec/claimRef"}]'   # → Available
```text
```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: data-restored, namespace: shop }
spec:
  storageClassName: db-ssd       # тот же класс, что у PV
  volumeName: pvc-8f3a...        # ⭐ привязать к конкретному PV
  accessModes: [ReadWriteOnce]
  resources: { requests: { storage: 10Gi } }   # не больше размера PV
```text
Защита от удаления «на ходу» — финализаторы:
`kubernetes.io/pvc-protection` (PVC используется подом — удаление ждёт, статус `Terminating`),
`kubernetes.io/pv-protection` (PV привязан). Это не баг, а страховка.

Сырое блочное устройство вместо ФС — `volumeMode: Block` (Ceph OSD на PVC, некоторые БД):
в контейнере вместо `volumeMounts` пишут `volumeDevices: [{name: data, devicePath: /dev/xvda}]`.

---

## 4. StatefulSet: то, что не вошло в тему про контроллеры

**`volumeClaimTemplates` нельзя поменять** — у StatefulSet изменяемы только `replicas`,
`template`, `updateStrategy`, `persistentVolumeClaimRetentionPolicy`, `minReadySeconds`, `ordinals`.
Как увеличить диски всем репликам:

```bash
# 1. расширить каждый PVC (класс с allowVolumeExpansion: true)
for i in 0 1 2; do
  kubectl -n db patch pvc data-postgres-$i -p '{"spec":{"resources":{"requests":{"storage":"20Gi"&#125;&#125;&#125;&#125;'
done
# 2. пересоздать объект StatefulSet без удаления подов, уже с новым размером в шаблоне
kubectl -n db delete sts postgres --cascade=orphan
kubectl -n db apply -f postgres-sts.yaml        # volumeClaimTemplates …storage: 20Gi
```text
**Судьба PVC при удалении и уменьшении** (GA с 1.32):

```yaml
spec:
  persistentVolumeClaimRetentionPolicy:
    whenDeleted: Retain     # удалили StatefulSet → PVC остаются (по умолчанию)
    whenScaled: Retain      # scale 3→2 → data-postgres-2 остаётся (по умолчанию)
```text
`Delete` удобен для эфемерных кластеров (CI, тесты), но для БД — ловушка: scale down
удалит данные реплики, scale up создаст **пустой** том.

**Застрявший rollout.** С `podManagementPolicy: OrderedReady` сломанный шаблон (под не
становится Ready) останавливает обновление. Откат шаблона сам под не починит — это известное
поведение (forced rollback): верни шаблон и **удали сломанный под руками**, тогда контроллер
создаст его заново по исправленному шаблону.

**PodDisruptionBudget** для кластера БД обязателен: `maxUnavailable: 1`, иначе `kubectl drain`
при обслуживании нод может снять две реплики из трёх.

---

## 5. local-path и локальные тома

`local-path-provisioner` (v0.0.37) — не CSI-драйвер: он создаёт каталог на ноде
(`/opt/local-path-provisioner` в kind, `/var/lib/rancher/k3s/storage` в k3s) и PV, привязанный
к этой ноде через `nodeAffinity`.

| | `hostPath` (по умолчанию) | `local` |
|---|---|---|
| Как задать | ничего | аннотация PVC `volumeType: local` или аннотация SC `defaultVolumeType: local` |
| Как kubelet монтирует | путь ноды прямо в контейнер | bind-mount в каталог пода `/var/lib/kubelet/pods/...` |
| Velero FSB (Kopia) | ❌ не видит | ✅ работает ([07_velero_dr.md](/storage/07-velero-dr)) |

```bash
kubectl get pv &lt;pv&gt; -o jsonpath='{.spec.nodeAffinity}'; echo   # к какой ноде прибит том
```text
Следствия, которые надо проговаривать на собесе:
- умерла нода — умерли данные (реплик нет); под с этим PVC будет `Pending` с
  `volume node affinity conflict`, пока нода не вернётся или PVC не пересоздать;
- снапшотов и расширения нет;
- зато максимальная скорость — поэтому «локальный диск + репликация силами приложения»
  (раздел 11) — нормальная прод-схема, но через CSI-драйверы локальных томов
  (TopoLVM, OpenEBS LocalPV-LVM), а не через local-path.

---

## 6. Чем выдавать тома: варианты для кластера

| Решение | Что внутри | RWX | Снапшоты | Отказ ноды | Где уместно |
|---------|-----------|-----|----------|------------|-------------|
| local-path | каталог на ноде | нет | нет | данные недоступны | kind/k3s, dev |
| TopoLVM / OpenEBS LocalPV-LVM | локальный LVM через CSI, учёт свободного места | нет | в пределах ноды | данные недоступны | БД-операторы с собственной репликацией |
| Longhorn | распределённый блочный, реплики тома на других нодах | через NFS share-manager | да + бэкап в S3 | переживает | небольшой on-prem, простота |
| Rook-Ceph | Ceph RBD / CephFS / RGW | да (CephFS) | да | переживает | серьёзный on-prem, много данных |
| NFS CSI | каталоги на NFS-сервере | да | ограниченно | зависит от NFS (SPOF) | общие файлы, legacy ([03_nfs_minio.md](/storage/03-nfs-minio)) |
| CSI облака | диск провайдера | обычно нет | да | переподключится в той же зоне | облако |

---

## 7. Rook-Ceph: Ceph как оператор

```text
 Rook operator (Deployment) ──смотрит──► CephCluster CR
      │ создаёт и лечит
      ├─► mon-a/b/c (Deployment на разных нодах)   mgr   osd-0/1/2 (по OSD на диск)
      ├─► CSI (ceph-csi через ceph-csi-operator): rbdplugin, cephfsplugin
      └─► CephBlockPool / CephFilesystem / CephObjectStore CR ──► пулы в Ceph
 StorageClass rook-ceph-block ──► RBD-образ на каждый PVC (RWO)
 StorageClass rook-cephfs     ──► подкаталог CephFS на каждый PVC (RWX)
```text
**Требования (реалистично):** Kubernetes 1.31–1.37 (Rook v1.20.7), 3 ноды, на каждой **сырой
диск без разделов и ФС** (`lsblk -f` — пустой FSTYPE), модуль `rbd` (`modprobe rbd`), udev.
Память: 3 × 4 ГБ — минимум «на грани», 3 × 6 ГБ — комфортно (OSD по умолчанию целится в
4 ГиБ, плюс mon, mgr, CSI, сам k3s).

> ⚠️ Rook «съедает» подходящие диски. **Только на учебных VM** с отдельными дисками
> (`useAllDevices: false` + `deviceFilter`), никогда — на хосте с реальными данными.

Стенд — три VM из `~/Projects/devops/stands/ceph-lab` (ceph1..3, 192.168.61.11–13, `eth1`,
диск `vdb` 20G) с k3s:

```bash
# ceph1 — сервер
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server --node-ip=192.168.61.11 --flannel-iface=eth1" sh -
sudo cat /var/lib/rancher/k3s/server/node-token
# ceph2, ceph3 — агенты (--node-ip своей ноды)
curl -sfL https://get.k3s.io | K3S_URL=https://192.168.61.11:6443 K3S_TOKEN=&lt;token&gt; \
  INSTALL_K3S_EXEC="agent --node-ip=192.168.61.12 --flannel-iface=eth1" sh -
```text
Установка (манифесты; Helm — чарты `rook-release/rook-ceph` и `rook-release/rook-ceph-cluster`):

```bash
git clone --single-branch --branch v1.20.7 https://github.com/rook/rook.git
cd rook/deploy/examples
kubectl create -f crds.yaml -f common.yaml -f csi-operator.yaml
kubectl create -f operator.yaml
kubectl -n rook-ceph get pod -w              # ждём rook-ceph-operator Running
```text
```yaml
# my-cluster.yaml — вместо cluster.yaml, ужатый под лабу
apiVersion: ceph.rook.io/v1
kind: CephCluster
metadata: { name: rook-ceph, namespace: rook-ceph }
spec:
  cephVersion:
    image: quay.io/ceph/ceph:v20.2.4       # Tentacle
  dataDirHostPath: /var/lib/rook           # конфиги и данные mon на нодах
  mon: { count: 3, allowMultiplePerNode: false }
  mgr: { count: 1 }
  dashboard: { enabled: true }
  storage:
    useAllNodes: true
    useAllDevices: false
    deviceFilter: "^vdb$"                  # ⭐ только учебный диск
  cephConfig:
    osd:
      osd_memory_target: "2147483648"      # 2 ГиБ — ниже Ceph не рекомендует; для 4-гиговых VM
```text
```bash
kubectl create -f my-cluster.yaml
kubectl -n rook-ceph get cephcluster -w      # PHASE Ready, HEALTH HEALTH_OK (5–15 минут)
kubectl create -f csi/rbd/storageclass.yaml  # CephBlockPool replicapool (size 3, host) + SC rook-ceph-block
kubectl create -f filesystem.yaml            # CephFilesystem myfs (+ MDS)
kubectl create -f csi/cephfs/storageclass.yaml   # SC rook-cephfs — RWX
kubectl create -f toolbox.yaml
kubectl -n rook-ceph exec -it deploy/rook-ceph-tools -- ceph status
kubectl -n rook-ceph exec -it deploy/rook-ceph-tools -- ceph osd tree
```text
Ключевые поля SC `rook-ceph-block`: `provisioner: rook-ceph.rbd.csi.ceph.com`, `clusterID: rook-ceph`,
`pool: replicapool`, `imageFormat: "2"`, `imageFeatures: layering`, секреты
`rook-csi-rbd-provisioner` (provisioner / controller-expand / controller-publish) и
`rook-csi-rbd-node` (node-stage) в namespace `rook-ceph`, `csi.storage.k8s.io/fstype: ext4`.
Пул — `failureDomain: host`, `replicated.size: 3`, `requireSafeReplicaSize: true`
(не даст создать пул с size 1).

> ⚠️ Удаление CephCluster **не** чистит диски. Полный снос: в CR
> `spec.cleanupPolicy.confirmation: "yes-really-destroy-data"`, удалить CR, затем на каждой
> ноде `rm -rf /var/lib/rook` и затереть учебный диск (`sgdisk --zap-all /dev/vdb`,
> `wipefs -a /dev/vdb`). Иначе следующий кластер не возьмёт диск: «has a filesystem».

---

## 8. VolumeSnapshots

Три объекта по аналогии с PVC/PV/SC: **VolumeSnapshot** (заявка, namespace) →
**VolumeSnapshotContent** (сам снапшот, кластер) ← **VolumeSnapshotClass** (драйвер, `deletionPolicy`).
CRD и snapshot-controller ставятся отдельно (если дистрибутив их не принёс —
`kubectl get crd | grep snapshot`), версии CRD и контроллера должны совпадать:

```bash
git clone --depth 1 --branch v8.5.0 https://github.com/kubernetes-csi/external-snapshotter.git
cd external-snapshotter
kubectl kustomize client/config/crd | kubectl create -f -
kubectl -n kube-system kustomize deploy/kubernetes/snapshot-controller | kubectl create -f -
```text
```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata: { name: csi-rbdplugin-snapclass }     # = csi/rbd/snapshotclass.yaml из Rook
driver: rook-ceph.rbd.csi.ceph.com
parameters:
  clusterID: rook-ceph
  csi.storage.k8s.io/snapshotter-secret-name: rook-csi-rbd-provisioner
  csi.storage.k8s.io/snapshotter-secret-namespace: rook-ceph
deletionPolicy: Delete            # Retain — снапшот переживёт удаление VolumeSnapshot
---
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata: { name: data-snap-1, namespace: app }
spec:
  volumeSnapshotClassName: csi-rbdplugin-snapclass
  source: { persistentVolumeClaimName: data }
---
apiVersion: v1                    # восстановление = новый PVC из снапшота
kind: PersistentVolumeClaim
metadata: { name: data-restored, namespace: app }
spec:
  storageClassName: rook-ceph-block
  dataSource: { name: data-snap-1, kind: VolumeSnapshot, apiGroup: snapshot.storage.k8s.io }
  accessModes: [ReadWriteOnce]
  resources: { requests: { storage: 5Gi } }    # не меньше исходного
```text
```bash
kubectl -n app get volumesnapshot     # READYTOUSE true, RESTORESIZE
kubectl get volumesnapshotcontent
```text
Клон без снапшота — `dataSource: {kind: PersistentVolumeClaim, name: data}` (тот же namespace и класс).

> ⚠️ CSI-снапшот **crash-consistent**: как выдернутый шнур. БД после такого восстановится
> (через WAL), но гарантий уровня приложения нет, а снапшот живёт **в том же хранилище** —
> умер Ceph, умерли и снапшоты. Это быстрый откат, а не бэкап. Бэкап — вынос в другое место
> ([06_db_backup_replication.md](/storage/06-db-backup-replication), [07_velero_dr.md](/storage/07-velero-dr)).

---

## 9. Расширение тома

```text
patch PVC 10Gi → 20Gi ──► external-resizer: ControllerExpandVolume (растёт RBD-образ/диск)
                      ──► kubelet: NodeExpandVolume (resize2fs / xfs_growfs) — онлайн, если драйвер умеет
kubectl get pvc -w        CAPACITY меняется после роста ФС; условия — в status.conditions
```text
- Уменьшить нельзя. С **1.34 (RecoverVolumeExpansionFailure, GA)** можно *понизить запрос*
  после неудачного расширения (попросили 100Ti, хранилище отказало — вернуть 30Gi), но не
  меньше исходного размера.
- Условие `FileSystemResizePending` — диск вырос, ФС ждёт монтирования/рестарта пода
  (у драйверов без онлайн-роста).
- Для StatefulSet — схема из раздела 4.

---

## 10. Инциденты: Pending PVC и Multi-Attach

```text
PVC Pending ──► kubectl describe pvc — что в Events?
 ├─ "waiting for first consumer to be created before binding" → норма для WaitForFirstConsumer
 ├─ "no persistent volumes available for this claim and no storage class is set" → нет default SC
 ├─ storageclass.storage.k8s.io "fast" not found → опечатка в storageClassName
 ├─ "waiting for a volume to be created ... by external provisioner" (долго)
 │        → provisioner лежит: kubectl get pods -A | grep csi; логи csi-provisioner
 ├─ ProvisioningFailed: quota / insufficient capacity / pool full → место, ResourceQuota
 └─ под Pending: "volume node affinity conflict" → локальный том на другой (мёртвой) ноде
```text
**`Multi-Attach error for volume ... Volume is already exclusively attached to one node`** —
RWO-том ещё числится за другой нодой:

| Причина | Что делать |
|---------|-----------|
| Deployment с RWO и `RollingUpdate`: новый под на другой ноде, старый ещё жив | `strategy: Recreate` или StatefulSet |
| Несколько реплик с одним RWO-томом | StatefulSet с `volumeClaimTemplates` или RWX |
| Нода умерла, VolumeAttachment висит | attach-detach controller сам сделает force detach через 6 минут (`maxWaitForUnmountDuration`); быстрее — убедиться, что нода **реально выключена**, и `kubectl taint nodes &lt;node&gt; node.kubernetes.io/out-of-service=nodeshutdown:NoExecute` (non-graceful shutdown, GA 1.28) |

> ⚠️ Taint `out-of-service` на ноде, которая на самом деле жива и пишет в том, — прямой путь
> к двум писателям на одном блочном устройстве и порче ФС. Сначала выключи ноду (IPMI,
> гипервизор), потом taint. То же с `kubectl delete pod --force` для StatefulSet.

Ещё два частых симптома: PVC висит в `Terminating` — его использует под (финализатор
`pvc-protection`), найди под: `kubectl get pods -A -o json | jq -r '.items[] | select(.spec.volumes[]?.persistentVolumeClaim.claimName=="data") | .metadata.name'`;
VolumeAttachment не удаляется после удаления ноды — смотри логи external-attacher, в крайнем
случае (нода точно мертва) снимают финализатор с VolumeAttachment.

---

## 11. База в Kubernetes: оператор или снаружи

Тема 06 контроллеров дала позицию «managed, иначе зрелый оператор». Здесь — как это решать
на практике.

```text
Есть managed-БД у провайдера и она устраивает? ──да──► managed
             │ нет (on-prem, требования к данным в стране — частый случай в KZ)
             ▼
Команда умеет эксплуатировать PostgreSQL (бэкап, PITR, failover, мажорный апгрейд)?
             │ нет ──► сначала навыки, иначе оператор просто спрячет проблему
             ▼ да
Оператор с бэкапом в S3, проверенным PITR, мониторингом и switchover ──► в кластер
Нужен предсказуемый I/O на выделенном железе, большие объёмы ──► VM/железо + Patroni
```text
**Shared-nothing — главный архитектурный довод.** Оператор (CloudNativePG, Zalando на Patroni)
сам держит 3 копии через репликацию PostgreSQL. Если под ними ещё и Ceph с `size: 3`:

```text
3 инстанса PG × 3 реплики Ceph = 9 копий данных, запись идёт по сети дважды,
латентность fsync = сеть + Ceph. Для БД-оператора лучше локальные тома (TopoLVM,
LocalPV-LVM, local PV на NVMe) + anti-affinity по нодам: копии даёт сама БД.
Сетевой том (Ceph/Longhorn) уместен для одиночного инстанса без своей репликации.
```text
| Оператор | Для чего | Бэкапы | Замечание |
|----------|----------|--------|-----------|
| CloudNativePG | PostgreSQL | barman-cloud (плагин) в S3 | без Patroni: failover делает сам оператор |
| Zalando postgres-operator | PostgreSQL | WAL-G (образ Spilo) | внутри Patroni |
| Crunchy PGO, Percona Operator | PostgreSQL | pgBackRest | Percona — Patroni внутри |
| Strimzi | Kafka | — (репликация + MirrorMaker 2) | см. [../Left/05_Queues/00_INDEX.md](/queues/) |

Чек-лист перед «тащим базу в кластер»: тест `fio` на выбранном StorageClass; PDB и
anti-affinity; `reclaimPolicy: Retain`; бэкап вне кластера и **проведённое** восстановление
в другой namespace/кластер; алерты на лаг, место и возраст бэкапа; процедура мажорного
апгрейда; кто дежурит.

---

## 12. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| SC для БД с `reclaimPolicy: Delete` | `delete pvc` / удаление namespace стирает данные | `Retain` + patch у существующих PV |
| Deployment + RWO + RollingUpdate | Multi-Attach при каждом релизе | `Recreate` или StatefulSet |
| Правка `volumeClaimTemplates` | API отклоняет изменение | patch PVC + `delete sts --cascade=orphan` |
| `whenScaled: Delete` у БД | scale down удалил данные реплики | `Retain` по умолчанию |
| Снапшоты вместо бэкапа | умер Ceph — умерли снапшоты | вынос в S3 вне кластера |
| local-path в «проде» | нода умерла — данных нет | реплицирующееся хранилище или репликация БД |
| Rook с `useAllDevices: true` на стенде с данными | OSD на чужом диске | `deviceFilter`, только VM |
| БД-оператор поверх Ceph size 3 | 9 копий, двойная сетевая запись | локальные тома + репликация БД |
| `out-of-service` на живой ноде | два писателя — порча ФС | сначала выключить ноду |
| Нет PDB у кластера БД | drain снял две реплики | PDB `maxUnavailable: 1` |

---

## 💼 Как это в DevOps

- Первый вопрос к любому stateful-сервису в кластере: «кто делает копии данных — хранилище или
  приложение, и где бэкап вне кластера?». Ответ определяет StorageClass.
- StorageClass для данных создают отдельно (`Retain`, `WaitForFirstConsumer`, expansion) и
  запрещают default-класс с `Delete` для namespace баз — политикой (Kyverno/Gatekeeper) или ревью.
- Расширение томов StatefulSet — отдельная процедура в runbook, а алерт на заполнение PVC
  (`kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes > 0.8`) — до того, как
  база встанет.
- Rook-Ceph в on-prem — это два сервиса на поддержке: Kubernetes и Ceph. Дежурному нужен и
  `kubectl`, и `ceph health detail` ([04_ceph.md](/storage/04-ceph)).
- Снапшот перед миграцией схемы/апгрейдом оператора — быстрый откат; бэкап в S3 — страховка.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Драйверы и лимиты томов | `kubectl get csidrivers`, `kubectl get csinode NODE -o yaml` |
| Кто к какой ноде прицеплен | `kubectl get volumeattachments` |
| Оставить данные у существующего PV | `kubectl patch pv PV -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"&#125;&#125;'` |
| Переиспользовать `Released` PV | убрать `spec.claimRef` + PVC с `volumeName` |
| Судьба PVC StatefulSet | `persistentVolumeClaimRetentionPolicy: {whenDeleted, whenScaled}` |
| Расширить тома StatefulSet | patch каждого PVC → `delete sts --cascade=orphan` → apply |
| local PV вместо hostPath (local-path) | аннотация PVC `volumeType: local` |
| Rook: статус | `kubectl -n rook-ceph get cephcluster`; toolbox → `ceph status` |
| Снапшот | VolumeSnapshotClass + VolumeSnapshot (`source.persistentVolumeClaimName`) |
| Восстановить из снапшота | PVC с `dataSource: {kind: VolumeSnapshot, ...}` |
| Почему PVC Pending | `kubectl describe pvc` → Events |
| Нода мертва, Multi-Attach | выключить ноду → taint `node.kubernetes.io/out-of-service=nodeshutdown:NoExecute` |
| Заполнение PVC | `kubelet_volume_stats_used_bytes / ..._capacity_bytes` |

---

## 🧠 Что запомнить

1. CSI — цепочка: provisioner (создать) → attacher (прицепить) → kubelet NodeStage/NodePublish
   (смонтировать); по событию понятно, какое звено сломалось.
2. `reclaimPolicy` копируется в PV при создании; у существующего тома его меняют patch'ем.
3. `Released` PV возвращают, убрав `claimRef` и создав PVC с `volumeName`.
4. `volumeClaimTemplates` неизменяемы: рост дисков StatefulSet = patch PVC + `--cascade=orphan`.
5. `persistentVolumeClaimRetentionPolicy` (GA 1.32) по умолчанию Retain/Retain — и для БД так и надо.
6. local-path — каталог на ноде: без реплик, снапшотов и расширения; `hostPath` не видит Velero FSB.
7. Rook — Ceph как оператор: CephCluster → mon/mgr/osd; RBD для RWO, CephFS для RWX; нужны сырые диски.
8. CSI-снапшот crash-consistent и живёт в том же хранилище — это откат, а не бэкап.
9. Multi-Attach на мёртвой ноде лечится выключением ноды и taint `out-of-service`, а не `--force`.
10. БД-оператор с собственной репликацией лучше ставить на локальные тома, а не на Ceph size 3.

➡️ Дальше: [06_db_backup_replication.md](/storage/06-db-backup-replication) · задачи: 05_k8s_stateful_tasks.md


---

### Блок A. Теория


**A1.** Какие sidecar-контейнеры входят в controller-часть CSI-драйвера и что делает каждый?

<details><summary>Ответ</summary>

external-provisioner (PVC → `CreateVolume`/`DeleteVolume`), external-attacher
(VolumeAttachment → `ControllerPublish`/`Unpublish`), external-resizer (рост PVC →
`ControllerExpandVolume`), external-snapshotter (VolumeSnapshotContent → `CreateSnapshot`/`DeleteSnapshot`),
обычно ещё livenessprobe. На нодах — node-driver-registrar и node-часть драйвера.

</details>

**A2.** Чем `NodeStageVolume` отличается от `NodePublishVolume`? Где на ноде искать смонтированный том?

<details><summary>Ответ</summary>

`NodeStage` готовит устройство один раз на ноду (подключить, при необходимости
отформатировать, смонтировать в `…/plugins/kubernetes.io/csi/&lt;driver&gt;/&lt;hash&gt;/globalmount`).
`NodePublish` делает bind-mount в каталог конкретного пода:
`/var/lib/kubelet/pods/&lt;uid&gt;/volumes/kubernetes.io~csi/&lt;pv&gt;/mount`.

</details>

**A3.** Что хранит объект VolumeAttachment, кто его создаёт и кто обрабатывает?

<details><summary>Ответ</summary>

Факт «PV X должен быть прицеплен к ноде Y» и статус `attached`. Создаёт attach-detach
controller в kube-controller-manager, обрабатывает external-attacher (вызов `ControllerPublish`).
Для драйверов с `attachRequired: false` объект не нужен.

</details>

**A4.** Какие поля StorageClass неизменяемы? Как поменять `reclaimPolicy` у уже созданного PV?

<details><summary>Ответ</summary>

`provisioner`, `parameters`, `reclaimPolicy`, `volumeBindingMode` (менять — новый класс
и перенос данных). У PV: `kubectl patch pv PV -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"&#125;&#125;'`.

</details>

**A5.** Опиши фазы PV и PVC. Когда PV становится `Released` и что с ним происходит дальше?

<details><summary>Ответ</summary>

PV: `Available` → `Bound` → после удаления PVC `Released` (Retain) или удаление тома
(Delete); `Failed` — не удалось автоматически освободить. PVC: `Pending` → `Bound` → `Lost`, если
PV пропал. `Released` PV держит `claimRef` на старый PVC, новый PVC к нему сам не привяжется.

</details>

**A6.** ⭐ Как вернуть данные из `Released` PV после случайного `kubectl delete pvc`?

<details><summary>Ответ</summary>

Убедиться, что PV `Released` и данные на месте; снять `spec.claimRef`
(`kubectl patch pv … --type json -p '[{"op":"remove","path":"/spec/claimRef"}]'`) — PV станет
`Available`; создать PVC с `volumeName: &lt;pv&gt;`, тем же классом, режимом доступа и размером
не больше PV.

</details>

**A7.** Зачем нужны финализаторы `kubernetes.io/pvc-protection` и `kubernetes.io/pv-protection`?

<details><summary>Ответ</summary>

Не дать удалить PVC, пока он смонтирован в поде, и PV, пока он привязан. Удаление
откладывается (`Terminating`) до освобождения — защита от потери данных «на ходу».

</details>

**A8.** Какие поля StatefulSet можно менять? Как увеличить тома у StatefulSet из трёх реплик?

<details><summary>Ответ</summary>

`replicas`, `template`, `updateStrategy`, `persistentVolumeClaimRetentionPolicy`,
`minReadySeconds`, `ordinals`. Тома: patch каждого PVC (класс с `allowVolumeExpansion`), затем
`kubectl delete sts NAME --cascade=orphan` и apply с новым размером в `volumeClaimTemplates` —
поды не перезапускаются, новые реплики получат новый размер.

</details>

**A9.** Что делает `persistentVolumeClaimRetentionPolicy` и почему для БД оставляют Retain/Retain?

<details><summary>Ответ</summary>

Задаёт, удалять ли PVC при удалении StatefulSet (`whenDeleted`) и при уменьшении числа
реплик (`whenScaled`). Для БД `Delete` опасен: scale down удалит данные реплики, а случайное
удаление объекта — все данные.

</details>

**A10.** Чем PV типа `hostPath` от local-path отличается от PV типа `local`? Почему это важно для Velero?

<details><summary>Ответ</summary>

`hostPath` kubelet пробрасывает путь ноды прямо в контейнер; `local` монтируется
bind-mount'ом в каталог пода в `/var/lib/kubelet/pods`. Velero File System Backup читает тома из
каталога подов, поэтому `hostPath` пропускает, а `local` бэкапит. Включается аннотацией PVC
`volumeType: local` (или аннотацией класса `defaultVolumeType: local`).

</details>

**A11.** Что нужно Rook, чтобы создать OSD на ноде? Какие ресурсы реально нужны для лабы?

<details><summary>Ответ</summary>

Сырой диск/раздел/LV без ФС и разделов (или PVC в режиме Block), модуль `rbd`, udev,
`lvm2` — если шифрование, metadata-устройство или несколько OSD на диск. Для лабы: 3 ноды,
по диску, минимум 3 × 4 ГБ RAM, комфортно 3 × 6 ГБ; Kubernetes 1.31–1.37 для Rook v1.20.

</details>

**A12.** Какие три объекта участвуют в CSI-снапшотах? Зачем отдельный snapshot-controller?

<details><summary>Ответ</summary>

VolumeSnapshot (заявка в namespace), VolumeSnapshotContent (сам снапшот, уровень
кластера), VolumeSnapshotClass (драйвер, параметры, `deletionPolicy`). snapshot-controller
связывает VolumeSnapshot с Content (как PV-контроллер для PVC); без него sidecar
external-snapshotter не получает работы, и снапшот не создаётся.

</details>

**A13.** ⭐ Почему CSI-снапшот не является бэкапом?

<details><summary>Ответ</summary>

Он crash-consistent и хранится в том же хранилище: авария Ceph, потеря пула, ошибка
администратора или шифровальщик на кластере уносят и том, и снапшоты. Бэкап — копия в другом
месте (S3 вне кластера), с retention и проверенным восстановлением.

</details>

**A14.** Что даёт RecoverVolumeExpansionFailure (GA 1.34)? Можно ли им уменьшить том?

<details><summary>Ответ</summary>

Если расширение не удалось (например, запросили больше, чем есть), можно понизить
`requests.storage` до значения, которое хранилище осилит, и квота вернётся. Уменьшить том ниже
исходного размера нельзя.

</details>

**A15.** ⭐ Почему БД-оператор с собственной репликацией не стоит класть на Ceph с `size: 3`?

<details><summary>Ответ</summary>

Оператор уже держит 3 копии через репликацию PostgreSQL; Ceph `size: 3` превратит это
в 9 копий, каждая запись пойдёт по сети дважды, а `fsync` будет ждать сеть и Ceph. Лучше
локальные тома (TopoLVM, LocalPV-LVM, local PV на NVMe) и anti-affinity по нодам.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  # Deployment, replicas: 1, стратегия по умолчанию (RollingUpdate), PVC RWO на rook-ceph-block.
```text
<details><summary>Ответ</summary>

⚠️ `Multi-Attach error`: новый под на другой ноде не может подключить RWO-том, пока
старый жив (RollingUpdate сначала создаёт новый). Нужен `strategy: Recreate` или StatefulSet.

</details>

```text:no-line-numbers
     # Релиз: новый под запланирован на другую ноду.
```text
```text:no-line-numbers
B2.  # StorageClass для кластера PostgreSQL в двух зонах
```text
<details><summary>Ответ</summary>

⚠️ `Delete` сотрёт данные при удалении PVC/namespace; `Immediate` создаст диск в
случайной зоне, и под может стать непланируемым. Для БД — `Retain` + `WaitForFirstConsumer`.

</details>

```text:no-line-numbers
     reclaimPolicy: Delete
```text
```text:no-line-numbers
     volumeBindingMode: Immediate
```text
```text:no-line-numbers
B3.  kubectl -n db edit sts postgres     # меняем volumeClaimTemplates …storage: 10Gi → 20Gi
```text
<details><summary>Ответ</summary>

⚠️ API отклонит: `volumeClaimTemplates` неизменяемы (Forbidden: updates to statefulset
spec for fields other than …). Решение — A8.

</details>

```text:no-line-numbers
B4.  persistentVolumeClaimRetentionPolicy: { whenDeleted: Retain, whenScaled: Delete }
```text
<details><summary>Ответ</summary>

⚠️ При scale 3 → 1 PVC `data-postgres-1` и `-2` удалятся вместе с данными; при 1 → 3
реплики получат пустые тома и будут заново копировать данные с primary (если это умеет
приложение/оператор).

</details>

```text:no-line-numbers
     # у StatefulSet postgres на 3 реплики: scale 3 → 1, через час обратно 1 → 3
```text
```text:no-line-numbers
B5.  # PVC без статических PV в кластере
```text
<details><summary>Ответ</summary>

⚠️ `Pending` навсегда: пустой класс означает «только статический PV», а подходящих PV нет.

</details>

```text:no-line-numbers
     spec: { storageClassName: "", accessModes: [ReadWriteOnce], resources: { requests: { storage: 1Gi } } }
```text
```text:no-line-numbers
B6.  # CRD снапшотов поставили, snapshot-controller — нет; создали VolumeSnapshot
```text
<details><summary>Ответ</summary>

⚠️ VolumeSnapshot висит без статуса (`READYTOUSE` пусто), VolumeSnapshotContent не
создаётся — нет контроллера. Поставить snapshot-controller той же версии, что CRD.

</details>

```text:no-line-numbers
B7.  # исходный PVC 5Gi, восстановление из его снапшота
```text
<details><summary>Ответ</summary>

⚠️ Размер меньше `restoreSize` снапшота — provisioner откажет. Запросить ≥ 5Gi.

</details>

```text:no-line-numbers
     resources: { requests: { storage: 3Gi } }
```text
```text:no-line-numbers
     dataSource: { name: data-snap-1, kind: VolumeSnapshot, apiGroup: snapshot.storage.k8s.io }
```text
```text:no-line-numbers
B8.  # CephCluster на нодах, где кроме vdb есть пустой диск vdc «под будущий бэкап»
```text
<details><summary>Ответ</summary>

⚠️ Rook заберёт и `vdc` под OSD — «диск под бэкап» станет частью Ceph. Нужен
`useAllDevices: false` + `deviceFilter: "^vdb$"` (или явный список `nodes[].devices`).

</details>

```text:no-line-numbers
     storage: { useAllNodes: true, useAllDevices: true }
```text
```text:no-line-numbers
B9.  kubectl taint nodes worker2 node.kubernetes.io/out-of-service=nodeshutdown:NoExecute
```text
<details><summary>Ответ</summary>

⚠️ Kubernetes форсированно отцепит тома и перезапустит поды на других нодах, а старые
поды на изолированной, но живой ноде продолжат писать — два писателя на RWO-томе, риск порчи
ФС. Taint — только после гарантированного выключения ноды.

</details>

```text:no-line-numbers
     # worker2 не отвечает из-за сетевой изоляции, но VM работает
```text
```text:no-line-numbers
B10.  # Deployment на 3 реплики, общий каталог
```text
<details><summary>Ответ</summary>

⚠️ ceph-csi RBD не выдаёт RWX в режиме Filesystem (блочная ФС не кластерная) —
provisioning упадёт. Для общего каталога — `rook-cephfs`; RWX RBD возможен только с
`volumeMode: Block` и приложением, которое само координирует доступ.

</details>

```text:no-line-numbers
     storageClassName: rook-ceph-block
```text
```text:no-line-numbers
     accessModes: [ReadWriteMany]      # volumeMode по умолчанию Filesystem
```text
```text:no-line-numbers
B11.  # PVC на local-path создан и привязан к PV на ноде devops-worker;
```text
<details><summary>Ответ</summary>

⚠️ Под `Pending`: `volume node affinity conflict` — local-path PV прибит к
`devops-worker`, а nodeSelector требует `devops-worker2`.

</details>

```text:no-line-numbers
     # в поде добавили nodeSelector: kubernetes.io/hostname: devops-worker2
```text
```text:no-line-numbers
B12.  kubectl -n app delete pvc data   # под app-0 всё ещё использует этот PVC
```text
<details><summary>Ответ</summary>

⚠️ PVC уйдёт в `Terminating` и будет висеть, пока под его использует (финализатор
`pvc-protection`); данные целы. После удаления пода PVC удалится, а с ним по `reclaimPolicy` — PV.

</details>


---

### Блок C. Практика


### C1. 🔑 Проследить CSI-цепочку (Rook)
Создай PVC на `rook-ceph-block` и под с ним. Найди по шагам: событие provisioner'а в PVC,
PV и его `spec.csi.volumeHandle` / `volumeAttributes.imageName`, RBD-образ в Ceph (toolbox:
`rbd ls replicapool`), VolumeAttachment, точку монтирования на ноде (globalmount и каталог пода).

### C2. 🔑 Спасение `Released` PV (kind)
**1.** Создай SC `standard-retain`: provisioner `rancher.io/local-path`, `reclaimPolicy: Retain`,
   `volumeBindingMode: WaitForFirstConsumer`.

<details><summary>Ответ</summary>

Порядок: `kubectl describe pvc` (Events: `Provisioning` → `ProvisioningSucceeded` от
`rook-ceph.rbd.csi.ceph.com`) → `kubectl get pv &lt;pv&gt; -o jsonpath='{.spec.csi.volumeAttributes.imageName}'`
(имя вида `csi-vol-…`) → в toolbox `rbd ls replicapool` и `rbd info replicapool/csi-vol-…` →
`kubectl get volumeattachments | grep &lt;pv&gt;` (ATTACHED true, нода) → на ноде
`findmnt | grep &lt;pv&gt;` и `lsblk` (устройство `/dev/rbd0`, globalmount и каталог пода).

</details>

**2.** PVC + под, запиши файл в том. Удали под и PVC.

<details><summary>Ответ</summary>

```bash
kubectl get pv                                    # PV standard-retain в статусе Released
kubectl patch pv &lt;pv&gt; --type json -p '[{"op":"remove","path":"/spec/claimRef"}]'
kubectl get pv &lt;pv&gt;                               # Available
# PVC data-restored: storageClassName standard-retain, volumeName &lt;pv&gt;, тот же размер/режим
```text
Под с `data-restored` должен попасть на ту же ноду (PV прибит `nodeAffinity`) — local-path
учтёт это сам. Файл на месте.

</details>

**3.** Верни данные в новый PVC `data-restored` и проверь файл.

<details><summary>Ответ</summary>

Проверь `kubectl get sc rook-ceph-block -o jsonpath='{.allowVolumeExpansion}'` = true;
patch `data-web-0/1/2` до 2Gi; дождись `CAPACITY 2Gi` (`kubectl get pvc -w`, RBD растит ФС
онлайн); `kubectl delete sts web --cascade=orphan`; поправь шаблон на 2Gi и `kubectl apply`;
`kubectl scale sts web --replicas=4` — `data-web-3` создастся на 2Gi.

</details>

### C3. 🔑 Расширить тома StatefulSet (Rook)
StatefulSet `web` на 3 реплики с `volumeClaimTemplates` 1Gi на `rook-ceph-block`. Увеличь
тома до 2Gi без удаления подов и так, чтобы новые реплики тоже получали 2Gi.

### C4. Retention policy на практике (kind)
StatefulSet на 3 реплики с `whenScaled: Delete`. Сделай scale 3 → 1 → 3, наблюдай
`kubectl get pvc -w`. Повтори с `Retain`. Что изменилось в данных реплик 1 и 2?

### C5. 🔑 RWO и RWX на Rook
**1.** Подними CephCluster, CephBlockPool + SC `rook-ceph-block`, CephFilesystem + SC `rook-cephfs`.

<details><summary>Ответ</summary>

Порядок: `kubectl describe pvc` (Events: `Provisioning` → `ProvisioningSucceeded` от
`rook-ceph.rbd.csi.ceph.com`) → `kubectl get pv &lt;pv&gt; -o jsonpath='{.spec.csi.volumeAttributes.imageName}'`
(имя вида `csi-vol-…`) → в toolbox `rbd ls replicapool` и `rbd info replicapool/csi-vol-…` →
`kubectl get volumeattachments | grep &lt;pv&gt;` (ATTACHED true, нода) → на ноде
`findmnt | grep &lt;pv&gt;` и `lsblk` (устройство `/dev/rbd0`, globalmount и каталог пода).

</details>

**2.** Deployment на 3 реплики с anti-affinity по нодам и общим PVC на `rook-cephfs` (RWX):
   каждая реплика дописывает свою строку в общий файл.

<details><summary>Ответ</summary>

```bash
kubectl get pv                                    # PV standard-retain в статусе Released
kubectl patch pv &lt;pv&gt; --type json -p '[{"op":"remove","path":"/spec/claimRef"}]'
kubectl get pv &lt;pv&gt;                               # Available
# PVC data-restored: storageClassName standard-retain, volumeName &lt;pv&gt;, тот же размер/режим
```text
Под с `data-restored` должен попасть на ту же ноду (PV прибит `nodeAffinity`) — local-path
учтёт это сам. Файл на месте.

</details>

**3.** То же с PVC RWO на `rook-ceph-block` — что увидишь?

<details><summary>Ответ</summary>

Проверь `kubectl get sc rook-ceph-block -o jsonpath='{.allowVolumeExpansion}'` = true;
patch `data-web-0/1/2` до 2Gi; дождись `CAPACITY 2Gi` (`kubectl get pvc -w`, RBD растит ФС
онлайн); `kubectl delete sts web --cascade=orphan`; поправь шаблон на 2Gi и `kubectl apply`;
`kubectl scale sts web --replicas=4` — `data-web-3` создастся на 2Gi.

</details>

### C6. Снапшот и восстановление (Rook)
Поставь CRD и snapshot-controller, VolumeSnapshotClass. Запиши данные → снапшот → испорти
данные → восстанови в новый PVC → смонтируй в под и сравни.

### C7. Зоопарк Pending PVC (kind)
Создай три «сломанных» PVC: с несуществующим классом, с `storageClassName: ""`, с `standard`
без пода. По Events каждого определи причину и что с ней делать.

### C8. Multi-Attach и мёртвая нода (Rook)
**1.** Deployment с RWO-томом; смени `nodeSelector` на другую ноду — поймай `Multi-Attach error`.
   Почини через `strategy: Recreate`.

<details><summary>Ответ</summary>

Порядок: `kubectl describe pvc` (Events: `Provisioning` → `ProvisioningSucceeded` от
`rook-ceph.rbd.csi.ceph.com`) → `kubectl get pv &lt;pv&gt; -o jsonpath='{.spec.csi.volumeAttributes.imageName}'`
(имя вида `csi-vol-…`) → в toolbox `rbd ls replicapool` и `rbd info replicapool/csi-vol-…` →
`kubectl get volumeattachments | grep &lt;pv&gt;` (ATTACHED true, нода) → на ноде
`findmnt | grep &lt;pv&gt;` и `lsblk` (устройство `/dev/rbd0`, globalmount и каталог пода).

</details>

**2.** Выключи VM с подом StatefulSet (`virsh destroy &lt;domain&gt;` на хосте). Замерь, когда под
   переедет; повтори с taint `out-of-service`.

<details><summary>Ответ</summary>

```bash
kubectl get pv                                    # PV standard-retain в статусе Released
kubectl patch pv &lt;pv&gt; --type json -p '[{"op":"remove","path":"/spec/claimRef"}]'
kubectl get pv &lt;pv&gt;                               # Available
# PVC data-restored: storageClassName standard-retain, volumeName &lt;pv&gt;, тот же размер/режим
```text
Под с `data-restored` должен попасть на ту же ноду (PV прибит `nodeAffinity`) — local-path
учтёт это сам. Файл на месте.

</details>

### C9. hostPath против local (kind)
Создай два PVC на `standard`: обычный и с аннотацией `volumeType: local`. Сравни `spec`
обоих PV и найди на ноде (`docker exec devops-worker …`), где смонтирован каждый том.

---

### Блок D. Инциденты


**D1.** После замены ноды `postgres-0` висит в `Pending`: `volume node affinity conflict`. Класс — local-path.

<details><summary>Ответ</summary>

local-path PV прибит к старой ноде (`nodeAffinity` по hostname), данных на новой ноде
нет. Варианты: вернуть старую ноду/диск; если данные есть в бэкапе или на других репликах
(Patroni/CNPG) — удалить PVC (и PV) `postgres-0`, под получит новый пустой том и заново
склонируется с primary или из бэкапа. Вывод: для прод-данных на локальных томах репликация
на уровне БД обязательна.

</details>

**D2.** На каждом релизе API 1–2 минуты лежит: новый под в `ContainerCreating` с
`Multi-Attach error`, старый долго в `Terminating`.

<details><summary>Ответ</summary>

RollingUpdate + RWO: новый под ждёт, пока старый освободит том, а старый завершается
долго (`terminationGracePeriodSeconds`, медленный shutdown). Решение — `strategy: Recreate`
с быстрым graceful shutdown, или вынести состояние (S3/БД) и сделать сервис stateless.

</details>

**D3.** Том БД заполнен на 100%, PostgreSQL остановился; у StorageClass `allowVolumeExpansion: false`.

<details><summary>Ответ</summary>

Быстро: освободить место внутри (старые логи, `pg_wal` от брошенного слота — см.
[../Left/01_Databases/06_replication.md](/databases/06-replication)), не удалять файлы
данных. Для роста: `allowVolumeExpansion` в существующем классе включить можно (это поле
изменяемо), если драйвер умеет расширение; иначе — новый класс, новый PVC большего размера,
перенос данных (pg_basebackup/restore из бэкапа) и переключение. После — алерт на 80% заполнения.

</details>

**D4.** Кто-то удалил namespace с базой. У StorageClass `reclaimPolicy: Delete`. Что можно сделать и
как не допустить повторения?

<details><summary>Ответ</summary>

Средствами Kubernetes — почти ничего: PVC удалены, PV с `Delete` удалены вместе
с дисками. Восстановление — из бэкапа вне кластера (06, 07). Если бы был `Retain`, PV остались
бы `Released` и их вернули бы по схеме A6. Профилактика: `Retain` для данных, RBAC без права
удалять namespace с БД, admission-политика, Velero/бэкапы БД в S3.

</details>

**D5.** Rook на VM по 4 ГБ: OSD-поды в цикле `OOMKilled`, кластер в `HEALTH_WARN`.

<details><summary>Ответ</summary>

OSD по умолчанию целится в `osd_memory_target` 4 ГиБ, а на VM ещё mon, mgr, CSI, k3s.
Решение: `cephConfig.osd.osd_memory_target: "2147483648"` (ниже 2 ГиБ Ceph не рекомендует),
лимиты ресурсов в `resources.osd`, больше RAM на VM (6 ГБ), меньше соседей (monitoring отключить).

</details>

**D6.** Базу восстановили из CSI-снапшота, снятого под нагрузкой. PostgreSQL стартовал с
сообщениями о recovery, а часть последних заказов пропала. Это баг?

<details><summary>Ответ</summary>

Не баг: снапшот crash-consistent. PostgreSQL проиграл WAL, который успел попасть на диск
к моменту снапшота, а всё после снапшота в него не попало по определению. RPO снапшота =
интервал между снапшотами. Для «до секунды» нужен PITR из базовой копии + WAL
([06_db_backup_replication.md](/storage/06-db-backup-replication)).

</details>

**D7.** После удаления namespace PVC несколько часов в `Terminating`, под — тоже `Terminating`
на ноде, которая выключена.

<details><summary>Ответ</summary>

Под не может завершиться — kubelet на выключенной ноде не подтверждает удаление, а PVC
держит `pvc-protection`. Убедиться, что нода выключена, и поставить taint
`node.kubernetes.io/out-of-service=nodeshutdown:NoExecute` (поды удалятся, тома отцепятся) или
удалить объект ноды; `delete pod --force` — только когда нода гарантированно мертва.

</details>

**D8.** Поставили Longhorn «попробовать» — и новые PVC сервисов, где класс не указан, поехали на
Longhorn вместо старого хранилища.

<details><summary>Ответ</summary>

Longhorn поставил свой класс default, и default-классов стало два — берётся самый
свежий. Снять аннотацию `storageclass.kubernetes.io/is-default-class` с лишнего класса; в
манифестах сервисов указывать `storageClassName` явно; уже созданные PVC перенести.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Что такое CSI и из чего состоит драйвер?

<details><summary>Ответ</summary>

Стандарт интерфейса между Kubernetes и хранилищем. Controller-часть (Deployment):
   драйвер + sidecar'ы provisioner, attacher, resizer, snapshotter; node-часть (DaemonSet):
   драйвер + node-driver-registrar. Объекты CSIDriver, CSINode, VolumeAttachment.

</details>

**2.** Что происходит от создания PVC до записи данных в под?

<details><summary>Ответ</summary>

PVC → external-provisioner вызывает `CreateVolume` → PV, `Bound` (при WaitForFirstConsumer —
   после выбора ноды) → attach-detach controller создаёт VolumeAttachment → external-attacher
   `ControllerPublish` → kubelet: `NodeStage` (форматирование, globalmount) и `NodePublish`
   (bind-mount в под) → контейнер пишет.

</details>

**3.** Как расширить диск у StatefulSet?

<details><summary>Ответ</summary>

Класс с `allowVolumeExpansion`; patch каждого PVC; дождаться роста ФС; `delete sts --cascade=orphan`
   и apply с новым размером в `volumeClaimTemplates` (он неизменяем).

</details>

**4.** Что будет с PVC при удалении StatefulSet и при scale down?

<details><summary>Ответ</summary>

По умолчанию PVC остаются в обоих случаях; с `persistentVolumeClaimRetentionPolicy`
   (GA 1.32) можно удалять — для БД не надо. Остатки PVC стоят денег — чистить осознанно.

</details>

**5.** Что такое VolumeSnapshot? Можно ли считать его бэкапом?

<details><summary>Ответ</summary>

Снимок тома через CSI (VolumeSnapshot/Content/Class), из него создают PVC. Не бэкап:
   crash-consistent и в том же хранилище; годится для быстрого отката и клонирования.

</details>

**6.** Как выдавать RWX-тома в on-prem кластере?

<details><summary>Ответ</summary>

CephFS через Rook (`rook-cephfs`), NFS через csi-driver-nfs, Longhorn (RWX через NFS
   share-manager). Но сначала спросить, не лучше ли объектное хранилище.

</details>

**7.** Что такое Rook и что ему нужно?

<details><summary>Ответ</summary>

Оператор, разворачивающий Ceph в Kubernetes через CRD (CephCluster, CephBlockPool,
   CephFilesystem, CephObjectStore) плюс ceph-csi. Нужны ≥ 3 ноды, сырые диски без ФС,
   модуль `rbd`, память (≈ 4 ГБ на OSD в проде), нормальная сеть.

</details>

**8.** PVC в `Pending` — как разбираешься?

<details><summary>Ответ</summary>

`kubectl describe pvc` → Events: WaitForFirstConsumer (норма), нет default-класса, опечатка в
   классе, provisioner лежит (поды CSI и логи sidecar), нет места/квоты, для локальных томов —
   node affinity. Дальше — `kubectl get sc`, логи CSI.

</details>

**9.** `Multi-Attach error` — причины и решение.

<details><summary>Ответ</summary>

RWO-том числится за другой нодой: RollingUpdate с RWO, несколько реплик с одним томом,
   мёртвая нода с висящим VolumeAttachment. Решения: `Recreate`/StatefulSet/RWX; для мёртвой
   ноды — выключить её и taint `out-of-service` (или ждать force detach 6 минут).

</details>

**10.** Базу — в Kubernetes или снаружи?

<details><summary>Ответ</summary>

Managed, если есть и подходит. Иначе в кластер — только через зрелый оператор (CNPG) с
    бэкапом в S3 вне кластера, проверенным PITR, мониторингом, PDB, локальными томами и
    anti-affinity; при больших объёмах и жёстких требованиях к I/O — VM + Patroni.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Рассказываю CSI-цепочку provisioner → attacher → NodeStage → NodePublish и нахожу том на ноде
- [ ] Меняю `reclaimPolicy` у готового PV и возвращаю данные из `Released`
- [ ] ⭐ Расширяю тома StatefulSet через patch PVC и `--cascade=orphan`
- [ ] Объясняю `persistentVolumeClaimRetentionPolicy` и почему для БД Retain/Retain
- [ ] Знаю ограничения local-path и разницу `hostPath` / `local`
- [ ] Поднял Rook-Ceph на трёх VM, выдал RWO (RBD) и RWX (CephFS)
- [ ] Снял VolumeSnapshot и восстановил из него PVC; объясняю, почему это не бэкап
- [ ] ⭐ Разбираю Pending PVC и `Multi-Attach error`, знаю taint `out-of-service` и его риск
- [ ] Аргументирую «база в кластере или снаружи» и довод про 9 копий
