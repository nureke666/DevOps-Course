---
title: "14. Хранилище: PV, PVC, StorageClass"
description: "PV, PVC, StorageClass, Access Modes (RWO/ROX/RWX/RWOP), reclaimPolicy, CSI, расширение тома"
---

# 14. ⭐ Хранилище: PV, PVC, StorageClass, Access Modes

> Роадмап → 6. Kubernetes → Теория → **Хранилище**: «Тоже важная тема: PV, PVC,
> StorageClass, а также виды доступа (Access Mode)».
> **После темы ты умеешь:** подключить постоянный диск к поду, объяснить разницу
> статического и динамического выделения и не потерять данные при пересоздании пода.

---

## 🗺️ Карта темы

```text:no-line-numbers
     РАЗРАБОТЧИК                        АДМИНИСТРАТОР / ОБЛАКО
          │                                      │
   ┌──────▼──────┐   «хочу 10Gi RWO»    ┌────────▼─────────┐
   │     PVC     │ ───── запрос ──────► │   StorageClass   │  ← как создавать диски
   │ (заявка)    │                      │  (provisioner)   │
   └──────┬──────┘                      └────────┬─────────┘
          │  привязка (Bound)                    │ динамически создаёт
          │                              ┌───────▼────────┐
          └─────────────────────────────►│       PV       │  ← сам диск
                                         │ (ресурс)       │
   ┌─────────┐                           └───────┬────────┘
   │   POD   │ монтирует PVC ────────────────────┘
   └─────────┘

   Аналогия: PVC — заказ («нужен диск 10 ГБ»), PV — сам диск,
             StorageClass — «поставщик», умеющий выдавать диски по заказу.
```

---

## 1. Зачем: эфемерность файловой системы

Файловая система контейнера живёт ровно столько, сколько контейнер.
Рестарт контейнера — данные ещё на месте (том пода жив); пересоздание пода —
всё, что не на постоянном томе, исчезло.

| Тип тома | Живёт | Применение |
|----------|-------|------------|
| Файловая система контейнера | до рестарта контейнера | временные файлы, ничего важного |
| `emptyDir` | до удаления **пода** | кэш, обмен файлами между контейнерами пода |
| `hostPath` | на конкретной ноде | DaemonSet-агенты; ⚠️ для приложений — антипаттерн |
| `configMap` / `secret` | вместе с подом (read-only) | конфигурация |
| **PVC → PV** | **независимо от пода** | ⭐ базы, загрузки, состояние |

---

## 2. PV, PVC, StorageClass ⭐

| Объект | Кто создаёт | Область | Смысл |
|--------|-------------|---------|-------|
| **PersistentVolume (PV)** | администратор или provisioner | кластер | сам ресурс хранения: диск, NFS-шара, том облака |
| **PersistentVolumeClaim (PVC)** | разработчик | namespace | заявка: сколько, с каким режимом доступа, какого класса |
| **StorageClass (SC)** | администратор | кластер | «профиль» хранилища: какой драйвер, параметры, политика |

**Два сценария выделения:**

| | Статический | Динамический ⭐ |
|---|---|---|
| Как | Админ заранее создал PV, PVC к нему привязывается | PVC создаётся → StorageClass сам создаёт PV |
| Где встречается | on-prem, NFS, заранее нарезанные диски | облака и современные CSI-хранилища |
| Плюсы | Полный контроль | Не нужно участие человека |
| Минусы | Ручная работа | Нужен рабочий provisioner |

---

## 3. Практика: PVC и под

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: standard        # "" — без класса (статический PV)
  resources:
    requests:
      storage: 5Gi
---
apiVersion: apps/v1
kind: Deployment
metadata: { name: app }
spec:
  replicas: 1                        # ⚠️ с RWO — только одна реплика
  selector: { matchLabels: { app: app } }
  template:
    metadata: { labels: { app: app } }
    spec:
      containers:
        - name: app
          image: myapp:1.0
          volumeMounts:
            - name: data
              mountPath: /var/lib/app
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: data
```

```bash
kubectl get pvc
# NAME  STATUS  VOLUME       CAPACITY  ACCESS MODES  STORAGECLASS  AGE
# data  Bound   pvc-8f3a...  5Gi       RWO           standard      10s

kubectl get pv
kubectl describe pvc data
kubectl get storageclass
```

**Статусы PVC:**

| Статус | Значение |
|--------|----------|
| `Pending` | Нет подходящего PV, нет provisioner'а, либо ждём первого пода (`WaitForFirstConsumer`) |
| `Bound` | Привязан к PV, можно монтировать |
| `Lost` | PV исчез (удалили или сломалось хранилище) |

---

## 4. ⭐ Access Modes (виды доступа) — отдельный пункт роадмапа

| Режим | Сокращение | Что означает |
|-------|------------|--------------|
| **ReadWriteOnce** | RWO | Монтируется на чтение и запись **с одной ноды**. На этой ноде том могут использовать несколько подов |
| **ReadOnlyMany** | ROX | Только чтение, с многих нод |
| **ReadWriteMany** | RWX | Чтение и запись **с многих нод** одновременно |
| **ReadWriteOncePod** | RWOP | Только **один под** во всём кластере (строже RWO) |

**Что важно понимать:**

1. RWO ограничивает **ноду**, а не под. Два пода на одной ноде могут использовать
   один RWO-том; на разных нодах — нет.
2. **Блочные диски облаков (EBS, Persistent Disk, сетевые диски) поддерживают только RWO.**
   Это главная причина, почему нельзя просто сделать `replicas: 3` с общим томом.
3. RWX требует файловой системы с сетевым доступом: NFS, CephFS, GlusterFS,
   Azure Files, EFS. Отдельная инфраструктура.
4. RWOP полезен, когда даже двух подов на одной ноде допускать нельзя
   (строгие блокировки данных).

| Хочу | Решение |
|------|---------|
| Одна реплика с диском | RWO |
| Несколько реплик, у каждой свои данные | **StatefulSet + volumeClaimTemplates** (RWO у каждого) |
| Несколько реплик с общим каталогом | RWX-хранилище (NFS/CephFS) или объектное хранилище (S3) вместо диска |
| Раздать статику только на чтение | ROX или (лучше) вшить в образ / CDN |

> 🎤 На собесе после вопроса про access mode часто идёт уточнение:
> «Почему нельзя три реплики Deployment с одним RWO-томом?» — потому что тома
> хватит только подам на одной ноде, остальные останутся в `Pending`
> с ошибкой `Multi-Attach error`.

---

## 5. StorageClass

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: ebs.csi.aws.com          # CSI-драйвер
parameters:
  type: gp3
  iops: "3000"
  encrypted: "true"
reclaimPolicy: Delete                  # Delete | Retain
allowVolumeExpansion: true             # можно ли расширять
volumeBindingMode: WaitForFirstConsumer
```

| Поле | Смысл |
|------|-------|
| `provisioner` | Какой драйвер создаёт тома (CSI) |
| `parameters` | Параметры конкретного провайдера (тип диска, IOPS, шифрование) |
| `reclaimPolicy` | Что делать с PV после удаления PVC |
| `allowVolumeExpansion` | Можно ли увеличить размер PVC на лету |
| `volumeBindingMode` | `Immediate` — создать диск сразу; **`WaitForFirstConsumer`** — дождаться пода и создать диск в правильной зоне/на нужной ноде |

> ⚠️ `WaitForFirstConsumer` — почти всегда правильный выбор в облаке: диск создаётся
> в той зоне доступности, где будет под. При `Immediate` возможна классическая ошибка:
> диск в зоне `a`, под планируется в зону `b`, и под навсегда `Pending`.

### reclaimPolicy

| Значение | Что происходит при удалении PVC |
|----------|--------------------------------|
| `Delete` | PV и реальный диск удаляются — **данные пропадают** |
| `Retain` | PV остаётся в статусе `Released`, данные сохранены; переиспользовать вручную |
| `Recycle` | Устарело, не используется |

Для баз данных и всего важного ставят `Retain` — это дешёвая страховка от
случайного `kubectl delete pvc`.

---

## 6. CSI — как это работает под капотом

**CSI (Container Storage Interface)** — стандарт, по которому кубер общается
с системами хранения. Драйвер обычно состоит из двух частей:

| Часть | Где работает | Что делает |
|-------|--------------|------------|
| Controller | Deployment | создаёт, удаляет, расширяет, снимает снапшоты |
| Node | DaemonSet | подключает и монтирует том на конкретной ноде |

```bash
kubectl get csidrivers
kubectl get pods -n kube-system | grep csi
kubectl get volumeattachments
```

Дополнительно CSI даёт снапшоты:
```yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata: { name: db-snap-2026-09-13 }
spec:
  volumeSnapshotClassName: csi-snapclass
  source:
    persistentVolumeClaimName: data
```
Из снапшота можно создать новый PVC — удобно для быстрого восстановления и клонирования.

---

## 7. Расширение тома

```bash
kubectl patch pvc data -p '{"spec":{"resources":{"requests":{"storage":"20Gi"}}}}'
kubectl get pvc data -w
```
Условия: `allowVolumeExpansion: true` в StorageClass; файловая система расширяется
при следующем монтировании (часто нужен рестарт пода). **Уменьшить том нельзя.**

---

## 8. Типовые проблемы

| Симптом | Причина | Лечение |
|---------|---------|---------|
| PVC `Pending` | Нет StorageClass по умолчанию; нет подходящего PV; provisioner не работает | `kubectl describe pvc`, `kubectl get sc` |
| PVC `Pending` при `WaitForFirstConsumer` | Ждёт первого пода — это норма | Создать под |
| Под `Pending`, `FailedAttachVolume` / `Multi-Attach error` | RWO-том уже смонтирован на другой ноде | StatefulSet или RWX |
| Под `ContainerCreating` долго | Проблема монтирования, CSI, сети хранилища | события пода, логи CSI-node |
| Данные пропали после удаления PVC | `reclaimPolicy: Delete` | `Retain` для важного |
| Нет прав на запись в том | Приложение работает не под root | `securityContext.fsGroup` |
| Место кончилось, а расширить нельзя | `allowVolumeExpansion: false` | Новый класс, миграция данных |
| PV в статусе `Released` не переиспользуется | Осталась ссылка `claimRef` | Убрать `claimRef` вручную |

```yaml
securityContext:
  fsGroup: 1000            # ⭐ кубер сменит группу-владельца тома при монтировании
  runAsUser: 1000
```

---

## 9. Локальный кластер: local-path

В kind/minikube динамическое выделение обеспечивает `local-path-provisioner`:
том — это просто каталог на ноде.

```bash
kubectl get sc
# NAME                 PROVISIONER             RECLAIMPOLICY  VOLUMEBINDINGMODE
# standard (default)   rancher.io/local-path   Delete         WaitForFirstConsumer
```

> ⚠️ Важное следствие для экспериментов: том привязан к ноде.
> Переехал под на другую ноду — данных там нет. В kind это заметно не всегда
> (часто одна нода), но в реальном кластере с `hostPath`-подобным хранилищем
> это источник инцидентов.

---

## 💼 Как это в DevOps

- Первое правило: stateless-приложениям тома не нужны. Если появился PVC —
  спроси, точно ли состояние должно жить в кластере.
- Для БД используют StatefulSet с `volumeClaimTemplates` и класс с `Retain`.
- PVC не удаляются вместе со StatefulSet — регулярно проверяй «осиротевшие» тома,
  иначе счёт за облако растёт незаметно.
- Снапшот CSI — не бэкап: это моментальный снимок диска в том же хранилище.
  Настоящий бэкап — логический дамп или Velero с выгрузкой в объектное хранилище.
- Для файлов пользователей (аватары, документы) в кубере почти всегда правильнее
  объектное хранилище S3, а не RWX-том: дешевле, проще, масштабируемо.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Постоянный диск поду | PVC + `volumes.persistentVolumeClaim` |
| Посмотреть классы хранилищ | `kubectl get sc` |
| Понять, почему PVC Pending | `kubectl describe pvc NAME` |
| Персональные диски репликам | StatefulSet + `volumeClaimTemplates` |
| Общий доступ с разных нод | RWX-хранилище (NFS/CephFS) |
| Не терять данные при удалении PVC | `reclaimPolicy: Retain` |
| Создать диск в нужной зоне | `volumeBindingMode: WaitForFirstConsumer` |
| Расширить диск | `allowVolumeExpansion: true` + patch PVC |
| Починить права на томе | `securityContext.fsGroup` |
| Временный том | `emptyDir: {}` |
| Найти брошенные тома | `kubectl get pvc -A` и сверить с нагрузками |

---

## 🧠 Что запомнить

1. **PVC — заявка, PV — диск, StorageClass — поставщик дисков.**
2. Динамическое выделение — норма: PVC создаёт PV автоматически через provisioner.
3. ⭐ Access modes: **RWO** (одна нода), **ROX** (много нод, чтение),
   **RWX** (много нод, запись), **RWOP** (один под).
4. RWO ограничивает **ноду**, а не под; блочные диски облаков — только RWO.
5. Три реплики Deployment с одним RWO-томом не запустятся (`Multi-Attach error`).
6. Нескольким репликам с состоянием нужен StatefulSet с `volumeClaimTemplates`.
7. `reclaimPolicy: Delete` удаляет данные вместе с PVC; для важного — `Retain`.
8. `WaitForFirstConsumer` создаёт диск там, где будет под, — спасает от зонных ошибок.
9. Тома расширяются при `allowVolumeExpansion: true`; уменьшить нельзя.
10. Права на томе чинятся через `securityContext.fsGroup`.
11. CSI-драйвер состоит из controller-части и node-части; он же даёт снапшоты.
12. Снапшот — не бэкап; PVC после удаления StatefulSet остаются и стоят денег.

---

## Задачи

> ⭐ Отдельный пункт роадмапа — **виды доступа (Access Mode)**: их спрашивают
> и в теории, и в виде задачи «почему три реплики не стартуют».

---

### Блок A. Теория

**A1.** Что произойдёт с файлами контейнера при его рестарте? А при пересоздании пода?

<details><summary>Ответ</summary>

При рестарте контейнера файловая система пересоздаётся из образа
(данные в ней теряются, но тома пода остаются). При пересоздании пода теряется всё,
что не на постоянном томе, включая `emptyDir`.

</details>

**A2.** Чем `emptyDir` отличается от PVC по времени жизни?

<details><summary>Ответ</summary>

`emptyDir` живёт вместе с подом; PVC — независимый объект, переживающий
и под, и его пересоздание.

</details>

**A3.** Почему `hostPath` для приложений — антипаттерн?

<details><summary>Ответ</summary>

Данные привязаны к конкретной ноде: при переезде пода их там не будет;
кроме того, это дыра в безопасности (доступ к файловой системе ноды).

</details>

**A4.** ⭐ Объясни связку PV, PVC и StorageClass своими словами.

<details><summary>Ответ</summary>

PVC — заявка на хранилище от приложения; PV — фактический ресурс хранения;
StorageClass — описание того, как и чем создавать такие ресурсы автоматически.

</details>

**A5.** Кто создаёт PV при динамическом выделении?

<details><summary>Ответ</summary>

Provisioner (CSI-драйвер), указанный в StorageClass.

</details>

**A6.** Чем статическое выделение отличается от динамического?

<details><summary>Ответ</summary>

При статическом администратор заранее создаёт PV, и PVC подбирает
подходящий; при динамическом PV создаётся под конкретный PVC автоматически.

</details>

**A7.** В каком namespace живёт PVC? А PV?

<details><summary>Ответ</summary>

PVC — в namespace; PV и StorageClass — объекты уровня кластера.

</details>

**A8.** Какие статусы бывают у PVC и что каждый означает?

<details><summary>Ответ</summary>

`Pending` — не привязан (нет PV/класса или ждём первого пода);
`Bound` — привязан; `Lost` — соответствующий PV утрачен.

</details>

**A9.** ⭐ Перечисли все access modes и объясни каждый.

<details><summary>Ответ</summary>

RWO — чтение и запись с одной ноды; ROX — только чтение со многих нод;
RWX — чтение и запись со многих нод; RWOP — доступ только для одного пода.

</details>

**A10.** ⭐ RWO ограничивает под или ноду? Почему это важно?

<details><summary>Ответ</summary>

Ноду. Несколько подов на одной ноде могут пользоваться RWO-томом,
а под на другой ноде — нет. Это объясняет и `Multi-Attach error`, и поведение
при переезде подов.

</details>

**A11.** Почему облачные блочные диски поддерживают только RWO?

<details><summary>Ответ</summary>

Потому что это виртуальные блочные устройства: их нельзя безопасно
подключить к нескольким виртуальным машинам на запись — файловая система
не рассчитана на конкурентный доступ.

</details>

**A12.** Что нужно для RWX и какие технологии это дают?

<details><summary>Ответ</summary>

Сетевая файловая система с поддержкой конкурентного доступа:
NFS, CephFS, GlusterFS, а также облачные EFS/Azure Files.

</details>

**A13.** Чем RWOP отличается от RWO?

<details><summary>Ответ</summary>

RWOP допускает только один под во всём кластере, даже если поды
на одной ноде; RWO ограничивает лишь ноду.

</details>

**A14.** ⭐ Почему нельзя сделать Deployment на 3 реплики с одним RWO-томом?
Какая ошибка будет?

<details><summary>Ответ</summary>

Том может быть смонтирован только на одной ноде: поды, запланированные
на другие ноды, останутся в `Pending` с `Multi-Attach error` /
`FailedAttachVolume`. Если все поды окажутся на одной ноде, они запустятся,
но это не гарантируется.

</details>

**A15.** Как дать каждой реплике свой диск?

<details><summary>Ответ</summary>

StatefulSet с `volumeClaimTemplates`.

</details>

**A16.** Что такое `reclaimPolicy` и какие значения бывают?

<details><summary>Ответ</summary>

Политика утилизации PV после удаления PVC: `Delete`, `Retain`
(и устаревший `Recycle`).

</details>

**A17.** Что произойдёт с данными при удалении PVC с `Delete`? С `Retain`?

<details><summary>Ответ</summary>

При `Delete` PV и реальный диск удаляются вместе с данными;
при `Retain` PV остаётся в статусе `Released`, данные сохраняются.

</details>

**A18.** ⭐ Что делает `volumeBindingMode: WaitForFirstConsumer` и какую проблему решает?

<details><summary>Ответ</summary>

Откладывает создание и привязку тома до появления пода, которому он нужен.
Решает проблему зон доступности: диск создаётся там, где действительно
будет запущен под.

</details>

**A19.** Как расширить том? Можно ли уменьшить?

<details><summary>Ответ</summary>

Изменить `spec.resources.requests.storage` в PVC при
`allowVolumeExpansion: true`. Уменьшить размер нельзя.

</details>

**A20.** Что такое CSI и из каких частей состоит драйвер?

<details><summary>Ответ</summary>

Стандартный интерфейс между кубером и системами хранения. Драйвер состоит
из controller-части (создание/удаление/расширение/снапшоты) и node-части
(подключение и монтирование на ноде).

</details>

**A21.** Что такое VolumeSnapshot и можно ли считать его бэкапом?

<details><summary>Ответ</summary>

Моментальный снимок тома средствами хранилища. Бэкапом его считать нельзя:
он хранится в той же системе, зависит от её доступности и не проверяется
на восстановление логической целостности.

</details>

**A22.** Как починить проблему «нет прав на запись в том»?

<details><summary>Ответ</summary>

Через `securityContext.fsGroup` (кубер сменит группу-владельца
смонтированного тома) и корректные `runAsUser`/`runAsGroup`.

</details>

**A23.** Что произойдёт с PVC при удалении StatefulSet?

<details><summary>Ответ</summary>

Остаются: их нужно удалять вручную, иначе они продолжают занимать место
и стоить денег.

</details>

**A24.** Почему в локальном кластере (kind) данные «теряются» при переезде пода?

<details><summary>Ответ</summary>

Потому что local-path создаёт том как каталог на конкретной ноде:
при переезде пода на другую ноду данных там нет.

</details>

**A25.** Когда для пользовательских файлов лучше S3, а не PVC?

<details><summary>Ответ</summary>

Практически всегда для пользовательских файлов: S3 дешевле, не требует
RWX-хранилища, масштабируется и доступен из любого пода без монтирования.

</details>

---

### Блок B. «Что произойдёт»

**B1.**
```yaml
kind: Deployment
spec:
  replicas: 3
  template:
    spec:
      volumes:
        - name: data
          persistentVolumeClaim: { claimName: data }   # RWO
```
Вопрос: сколько подов запустится и что будет с остальными?

<details><summary>Ответ</summary>

Запустятся поды, попавшие на ноду, где том смонтирован (часто один);
остальные останутся в `Pending` с `Multi-Attach error`.

</details>

**B2.**
```bash
kubectl get pvc
# NAME  STATUS   VOLUME  CAPACITY  STORAGECLASS
# data  Pending                    standard
kubectl get sc
# standard (default)  rancher.io/local-path  Delete  WaitForFirstConsumer
```
Вопрос: это поломка или нормальное поведение?

<details><summary>Ответ</summary>

Нормальное поведение: при `WaitForFirstConsumer` том создаётся
только когда появляется под, который его использует.

</details>

**B3.**
```bash
kubectl get pvc
# data  Pending
kubectl get sc
# No resources found
```
Вопрос: причина?

<details><summary>Ответ</summary>

Нет ни одного StorageClass (и нет подходящего PV): некому создать том.

</details>

**B4.**
```yaml
kind: PersistentVolumeClaim
spec:
  storageClassName: ""
  accessModes: [ReadWriteOnce]
  resources: { requests: { storage: 5Gi } }
```
Вопрос: что означает пустой `storageClassName`?

<details><summary>Ответ</summary>

Отключение динамического выделения: PVC будет искать подходящий
заранее созданный PV, а не создавать новый.

</details>

**B5.**
```bash
kubectl delete pvc data       # StorageClass с reclaimPolicy: Delete
```
Вопрос: что стало с данными?

<details><summary>Ответ</summary>

PV и реальный диск удалены вместе с данными.

</details>

**B6.**
```bash
kubectl delete sts postgres
kubectl get pvc
# data-postgres-0  Bound
# data-postgres-1  Bound
```
Вопрос: это ошибка? Что делать?

<details><summary>Ответ</summary>

Не ошибка: PVC намеренно переживают StatefulSet. Удалить вручную,
если данные больше не нужны.

</details>

**B7.**
```bash
kubectl describe pod app
# Warning  FailedAttachVolume  Multi-Attach error for volume "pvc-123"
```
Вопрос: что произошло?

<details><summary>Ответ</summary>

Том RWO уже подключён к другой ноде; под на новой ноде не может
его примонтировать.

</details>

**B8.**
```yaml
securityContext: {}
# приложение работает под UID 1000, том примонтирован
# ошибка: Permission denied при записи
```
Вопрос: что добавить?

<details><summary>Ответ</summary>

`securityContext.fsGroup: 1000` (и при необходимости `runAsGroup`).

</details>

**B9.**
```bash
kubectl patch pvc data -p '{"spec":{"resources":{"requests":{"storage":"2Gi"}}}}'
# было 10Gi
```
Вопрос: что ответит API?

<details><summary>Ответ</summary>

Ошибку: уменьшение размера PVC не поддерживается.

</details>

---

### Блок C. Практика

#### C1. 🔑 Первый PVC
1. Посмотри `kubectl get sc` — какой класс по умолчанию.
2. Создай PVC на 1Gi и посмотри статус.
3. Создай под, монтирующий его, и проверь статус PVC снова.
4. Объясни, почему статус изменился именно в этот момент.

<details><summary>Ответ</summary>

При `WaitForFirstConsumer` PVC переходит в `Bound` в момент создания пода,
который его монтирует.

</details>

#### C2. 🔑 Данные переживают под
1. Запиши файл в смонтированный каталог.
2. Удали под (Deployment пересоздаст).
3. Проверь, что файл на месте.
4. Теперь сделай то же самое с `emptyDir` и сравни.

#### C3. Эфемерность контейнера
1. Создай файл **вне** тома (например, в `/tmp`).
2. Убей процесс в контейнере, чтобы он перезапустился (`kubectl exec -- kill 1`).
3. Проверь файл. Потом удали под и проверь снова.
4. Запиши разницу «рестарт контейнера» vs «пересоздание пода».

#### C4. 🔑 RWO и три реплики *(ключевой эксперимент темы)*
1. Сделай Deployment с `replicas: 3` и одним RWO-PVC.
2. Посмотри статусы подов и события.
3. Найди `Multi-Attach error` (в многонодовом кластере).
4. Переделай на StatefulSet с `volumeClaimTemplates` и убедись, что всё работает.

<details><summary>Ответ</summary>

В многонодовом кластере часть подов зависнет в `Pending` с
`Multi-Attach error`; StatefulSet решает проблему персональными томами.

</details>

#### C5. StatefulSet и персональные тома
Повтори лабу из темы 06 и проверь:
```bash
kubectl get pvc
kubectl get pv
```
Сопоставь имена PVC с именами подов.

#### C6. reclaimPolicy
1. Посмотри политику у класса по умолчанию.
2. Создай PVC, запиши данные, удали PVC, проверь `kubectl get pv`.
3. Создай StorageClass с `Retain`, повтори опыт и сравни.
4. Попробуй переиспользовать `Released`-PV (подсказка: убрать `claimRef`).

<details><summary>Ответ</summary>

При `Delete` PV исчезает вместе с PVC; при `Retain` остаётся в `Released`
и для повторного использования нужно очистить `spec.claimRef`.

</details>

#### C7. WaitForFirstConsumer
1. Посмотри `volumeBindingMode` у своего класса.
2. Создай PVC без пода и посмотри статус.
3. Создай под и проследи момент перехода в `Bound`.
4. Опиши, какую проблему это решает в облаке с зонами доступности.

#### C8. Расширение тома
Если класс позволяет — увеличь PVC с 1Gi до 2Gi и проверь размер внутри пода
(`df -h`). Запиши, потребовался ли рестарт пода.

#### C9. fsGroup
1. Запусти под с `runAsUser: 1000` и томом — получишь ошибку прав.
2. Добавь `fsGroup: 1000`.
3. Проверь `ls -ln` на каталоге тома до и после.

<details><summary>Ответ</summary>

До `fsGroup` владелец каталога — root и запись невозможна; после —
группа-владелец меняется на указанную, и приложение получает доступ.

</details>

#### C10. Статический PV (со звёздочкой)
Создай PV вручную (`hostPath` на ноде) и PVC, который к нему привяжется
(через `storageClassName: ""` и совпадающие параметры). Опиши, чем это отличается
от динамического выделения.

#### C11. PostgreSQL с постоянным диском
1. Подними PostgreSQL со StatefulSet и PVC.
2. Создай таблицу и данные.
3. Удали под — проверь данные.
4. Удали StatefulSet, создай заново — проверь данные.
5. Удали PVC — и вот теперь данных нет. Запиши цепочку выводов.

<details><summary>Ответ</summary>

Данные переживают удаление пода и StatefulSet, но исчезают
вместе с PVC (при `reclaimPolicy: Delete`).

</details>

#### C12. Снапшот (со звёздочкой)
Если CSI поддерживает — сделай `VolumeSnapshot`, удали данные,
восстанови новый PVC из снапшота. Если не поддерживает — опиши процедуру письменно.

#### C13. Аудит томов
```bash
kubectl get pvc -A
kubectl get pv
```
Найди тома, не используемые ни одним подом. Напиши однострочник, который
выводит PVC без потребителей (подсказка: `kubectl describe pvc` → `Used By`).

---

### Блок D. Инциденты

**D1.** PVC висит в `Pending` уже 20 минут. Алгоритм разбора из четырёх шагов.

<details><summary>Ответ</summary>

(1) `kubectl describe pvc` — событие и причина; (2) `kubectl get sc` —
есть ли класс по умолчанию; (3) режим привязки (`WaitForFirstConsumer` —
ждём под); (4) работает ли provisioner (логи CSI-контроллера), хватает ли
квоты и места в хранилище.

</details>

**D2.** Под в `Pending` с `FailedAttachVolume`. Причина и решение.

<details><summary>Ответ</summary>

RWO-том занят другой нодой либо том «завис» после нештатного завершения
пода. Решение: дождаться отмонтирования, проверить `volumeattachments`,
перейти на StatefulSet или RWX.

</details>

**D3.** После удаления namespace пропала база данных. Что произошло и как
не допустить впредь?

<details><summary>Ответ</summary>

Удаление namespace удалило PVC, а класс имел `reclaimPolicy: Delete`.
Профилактика: `Retain` для важных данных, отдельные namespace для stateful,
бэкапы и ограничение прав на удаление.

</details>

**D4.** В облаке обнаружены 60 неприкреплённых дисков. Откуда они и что делать?

<details><summary>Ответ</summary>

Это PV/PVC, оставшиеся после удалённых StatefulSet и уменьшения реплик.
Провести аудит: сопоставить тома с активными нагрузками, забрать бэкап
и удалить ненужные.

</details>

**D5.** Приложение пишет «read-only file system» после переезда пода. Гипотезы?

<details><summary>Ответ</summary>

Том смонтирован как `readOnly`, закончилось место, файловая система
перешла в режим только для чтения из-за ошибок диска, либо включён
`readOnlyRootFilesystem` без нужного тома.

</details>

**D6.** Место на томе кончилось, приложение упало. Пошаговый план действий.

<details><summary>Ответ</summary>

Оценить, что занимает место (`du` внутри пода), при возможности
расширить PVC (`allowVolumeExpansion`), почистить лишнее, добавить мониторинг
заполнения томов и ротацию данных.

</details>

**D7.** После пересоздания пода данных нет, хотя PVC `Bound`.
Что могло произойти в кластере с local-path?

<details><summary>Ответ</summary>

Под переехал на другую ноду: local-path хранит данные в каталоге ноды,
и на новой ноде каталог пуст.

</details>

**D8.** Разработчик просит RWX-том для трёх реплик, чтобы «класть загруженные файлы».
Какие альтернативы предложишь?

<details><summary>Ответ</summary>

Объектное хранилище (S3/MinIO) вместо тома; при необходимости —
отдельный сервис загрузок; RWX-хранилище только если без него нельзя.

</details>

**D9.** Снапшоты делаются каждый день, но восстановить базу не удалось.
Почему снапшот — не бэкап?

<details><summary>Ответ</summary>

Снапшот хранится в той же системе хранения и не проверяется на
восстановимость; нужен внешний бэкап (логический дамп, Velero, выгрузка в S3)
и регулярные тестовые восстановления.

</details>

**D10.** PV в статусе `Released` не используется новым PVC. Как переиспользовать?

<details><summary>Ответ</summary>

Очистить `spec.claimRef` у PV (или создать новый PV из тех же данных)
и убедиться, что параметры совпадают с новым PVC.

</details>

**D11.** Под с БД перезапустился на другой ноде и не смог смонтировать том.
Что проверить (три пункта)?

<details><summary>Ответ</summary>

Отмонтировался ли том со старой ноды (`volumeattachments`), доступность
хранилища и зоны (диск и нода в одной зоне), состояние CSI node-плагина
на новой ноде.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Что такое PV, PVC и StorageClass?

<details><summary>Ответ</summary>

PV — ресурс хранения, PVC — заявка приложения, StorageClass — описание того,
как автоматически создавать PV.

</details>

**2.** Чем статическое выделение отличается от динамического?

<details><summary>Ответ</summary>

Статическое требует заранее созданных PV; динамическое создаёт их по запросу
через provisioner.

</details>

**3.** ⭐ Какие бывают access modes?

<details><summary>Ответ</summary>

RWO, ROX, RWX, RWOP.

</details>

**4.** Почему нельзя дать трём репликам один RWO-том?

<details><summary>Ответ</summary>

Том RWO монтируется только на одной ноде; остальные поды не смогут его получить.

</details>

**5.** Как дать каждой реплике свой диск?

<details><summary>Ответ</summary>

StatefulSet с `volumeClaimTemplates`.

</details>

**6.** Что такое reclaimPolicy и что выбрать для базы?

<details><summary>Ответ</summary>

Политика удаления PV; для базы — `Retain`.

</details>

**7.** Что делает WaitForFirstConsumer?

<details><summary>Ответ</summary>

Откладывает создание тома до планирования пода, чтобы диск появился
в нужной зоне/на нужной ноде.

</details>

**8.** Что такое CSI?

<details><summary>Ответ</summary>

Стандартный интерфейс подключения хранилищ; драйверы состоят из controller-
и node-частей.

</details>

**9.** Что произойдёт с PVC при удалении StatefulSet?

<details><summary>Ответ</summary>

PVC остаются; их удаляют вручную.

</details>

**10.** Снапшот — это бэкап?

<details><summary>Ответ</summary>

Нет: это снимок в той же системе хранения, бэкап должен быть внешним
и проверяться восстановлением.

</details>

---

### 🎯 Чек-лист

- [ ] Понимаю связку PVC → PV → StorageClass
- [ ] ⭐ Знаю все access modes и что RWO про ноду, а не про под
- [ ] Воспроизвёл `Multi-Attach error` и починил через StatefulSet
- [ ] Проверил, что данные переживают пересоздание пода
- [ ] Знаю разницу `Delete` и `Retain` и проверил обе на практике
- [ ] Понимаю, зачем `WaitForFirstConsumer`
- [ ] Чинил права на томе через `fsGroup`
- [ ] Расширял PVC
- [ ] Знаю, что PVC переживают StatefulSet и стоят денег
- [ ] Могу объяснить, почему снапшот — не бэкап
