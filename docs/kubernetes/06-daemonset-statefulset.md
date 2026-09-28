---
title: "06. DaemonSet и StatefulSet"
description: "Deployment vs StatefulSet vs DaemonSet, headless Service, volumeClaimTemplates, partition — конспект и задачи"
---

# 06. ⭐ DaemonSet и StatefulSet

> Роадмап → 6. Kubernetes → Основные сущности → **DaemonSet**, **StatefulSet**.
> Здесь живёт **вопрос собеса №1**: *«Чем отличаются Deployment, StatefulSet, DaemonSet?»*
> **После темы ты умеешь:** выбрать правильный контроллер под задачу и объяснить,
> почему базу данных не запускают Deployment'ом.

---

## 🗺️ Карта темы

```text:no-line-numbers
            ЧТО ЗАПУСКАЕМ?
                  │
    ┌─────────────┼──────────────────────────┐
    ▼             ▼                          ▼
Stateless     На КАЖДОЙ ноде             Stateful
приложение    (агент/демон)              (БД, очередь, кластер)
    │             │                          │
    ▼             ▼                          ▼
DEPLOYMENT    DAEMONSET                  STATEFULSET
web-7d8-abc   log-agent (по 1 на ноду)   db-0, db-1, db-2
случайные     новая нода → новый под     стабильные имена + свой том
имена,        удалили ноду → под ушёл    строгий порядок
любой под     ────────────────────       0 → 1 → 2 при создании
взаимозаменяем                           2 → 1 → 0 при удалении
```

---

## 1. ⭐ Таблица различий (учить наизусть)

| | **Deployment** | **StatefulSet** | **DaemonSet** |
|---|---|---|---|
| Зачем | Stateless-приложения | Приложения с состоянием и identity | Агент на каждой ноде |
| Имена подов | Случайный хеш: `web-7d8f-x2k9` | Порядковые: `db-0`, `db-1` | По ноде: `agent-x7k2p` |
| Стабильность имени | Нет | **Да** — имя переживает пересоздание | Нет (но нода фиксирована) |
| Сеть/DNS | Общий Service | **Своё DNS-имя** `db-0.db.ns.svc` (нужен headless Service) | Обычно `hostNetwork` или DaemonSet-сервис |
| Хранилище | Общий PVC или без него | **`volumeClaimTemplates`** — свой PVC у каждого пода | `hostPath` обычно |
| Порядок создания | Все параллельно | По очереди: 0 → 1 → 2 | По одному на ноду |
| Порядок удаления | Любой | Обратный: 2 → 1 → 0 | С уходом ноды |
| Сколько реплик | Сколько указал | Сколько указал | **Равно числу подходящих нод** |
| Масштабирование | `scale` | `scale` (с сохранением порядка) | Только через изменение числа нод |
| Обновление | RollingUpdate/Recreate | RollingUpdate с `partition`, OnDelete | RollingUpdate, OnDelete |
| Примеры | API, фронтенд, воркеры | PostgreSQL, Kafka, MongoDB, etcd, Elasticsearch | fluent-bit, node-exporter, CNI, kube-proxy, CSI |

**Формулировка для собеса (30 секунд):**
> «Deployment — для stateless-приложений: поды безымянные и взаимозаменяемые, обновляются
> плавно. StatefulSet — для приложений с состоянием: у подов стабильные имена, стабильные
> DNS-записи и персональные тома, создаются и удаляются строго по порядку.
> DaemonSet — гарантирует по одному поду на каждую ноду, используется для агентов:
> сбор логов, метрик, сетевые плагины».

---

## 2. DaemonSet

### Что это
Контроллер, который держит **по одному поду на каждой подходящей ноде**. Добавили ноду —
под появился автоматически. Убрали ноду — под исчез вместе с ней.

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: node-exporter
  namespace: monitoring
spec:
  selector:
    matchLabels: { app: node-exporter }
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1          # обновляем по одной ноде
  template:
    metadata:
      labels: { app: node-exporter }
    spec:
      hostNetwork: true           # часто нужен доступ к сети ноды
      hostPID: true
      tolerations:                # ⭐ чтобы попасть и на control-plane ноды
        - operator: Exists
      nodeSelector:               # или только на часть нод
        kubernetes.io/os: linux
      containers:
        - name: node-exporter
          image: prom/node-exporter:v1.7.0
          ports:
            - containerPort: 9100
              hostPort: 9100
          volumeMounts:
            - { name: proc, mountPath: /host/proc, readOnly: true }
            - { name: sys,  mountPath: /host/sys,  readOnly: true }
          resources:
            requests: { cpu: 50m, memory: 64Mi }
            limits:   { cpu: 200m, memory: 128Mi }
      volumes:
        - name: proc
          hostPath: { path: /proc }
        - name: sys
          hostPath: { path: /sys }
```

### Что важно знать

| Факт | Подробности |
|------|-------------|
| Нет `replicas` | Число подов = число подходящих нод |
| Попадание на ноды | `nodeSelector` / `nodeAffinity` сужают; `tolerations` расширяют (control-plane) |
| Планирование | Поды DaemonSet планирует обычный scheduler, но с высоким приоритетом размещения |
| Обновление | `RollingUpdate` с `maxUnavailable` (по умолчанию 1) или `OnDelete` — обновление только при ручном удалении пода |
| Доступ к ноде | Почти всегда `hostPath`, часто `hostNetwork`/`hostPID` — поэтому требует привилегий |
| Кто так работает | `kube-proxy`, CNI-плагины, CSI-ноды, fluent-bit/vector, node-exporter, агенты безопасности |

```bash
kubectl get ds -A
kubectl -n monitoring rollout status ds/node-exporter
kubectl -n monitoring rollout restart ds/node-exporter
kubectl get pods -o wide -l app=node-exporter     # ровно по одному на ноду
```

> ⚠️ DaemonSet потребляет ресурсы на **каждой** ноде. В кластере на 200 нод лишние
> 200 Mi на под — это 40 Gi. Ресурсы у DaemonSet выставляют особенно аккуратно.

---

## 3. StatefulSet

### Что это
Контроллер для приложений, которым важна **идентичность**: имя, сетевое имя и собственный
диск, переживающие перезапуск.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: postgres                 # ⭐ headless Service — обязателен для StatefulSet
spec:
  clusterIP: None                # ⭐ именно None
  selector: { app: postgres }
  ports: [{ port: 5432, name: pg }]
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
spec:
  serviceName: postgres          # ⭐ ссылка на headless Service
  replicas: 3
  podManagementPolicy: OrderedReady   # или Parallel
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      partition: 0               # обновлять поды с порядковым номером >= partition
  selector:
    matchLabels: { app: postgres }
  template:
    metadata:
      labels: { app: postgres }
    spec:
      terminationGracePeriodSeconds: 60
      containers:
        - name: postgres
          image: postgres:16
          ports: [{ containerPort: 5432, name: pg }]
          env:
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef: { name: pg-secret, key: password }
            - name: PGDATA
              value: /var/lib/postgresql/data/pgdata
          volumeMounts:
            - name: data
              mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:          # ⭐ у КАЖДОГО пода будет свой PVC
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: standard
        resources:
          requests:
            storage: 10Gi
```

Что получится:

```text:no-line-numbers
Поды:   postgres-0        postgres-1        postgres-2
PVC:    data-postgres-0   data-postgres-1   data-postgres-2
DNS:    postgres-0.postgres.default.svc.cluster.local
        postgres-1.postgres.default.svc.cluster.local
        postgres-2.postgres.default.svc.cluster.local
```

### Гарантии StatefulSet ⭐

1. **Стабильное имя.** `postgres-0` пересоздался — он снова `postgres-0`.
2. **Стабильный DNS.** Каждый под адресуем персонально — нужно для кластеров,
   где реплики знают друг друга поимённо (Kafka, etcd, Patroni).
3. **Стабильное хранилище.** PVC привязан к порядковому номеру: пересоздался под —
   подключается **тот же** диск.
4. **Порядок.** Создание 0 → 1 → 2, каждый следующий после готовности предыдущего;
   удаление и обновление — в обратном порядке.
5. **Не более одного пода с данной identity** — отсюда осторожность с `--force`.

### Особенности эксплуатации

| Ситуация | Поведение |
|----------|-----------|
| Уменьшили `replicas` | Поды удаляются с конца, но **PVC остаются** (данные не теряются) |
| Удалили StatefulSet | PVC по умолчанию **остаются**; удалять надо отдельно |
| Нужен параллельный старт | `podManagementPolicy: Parallel` (когда поды независимы) |
| Постепенное обновление | `updateStrategy.rollingUpdate.partition: N` — обновятся только поды с номером ≥ N (канареечное обновление кластера БД) |
| Полностью ручное обновление | `updateStrategy.type: OnDelete` |
| Под завис в `Terminating` на мёртвой ноде | Новый под **не создастся** — кубер бережёт гарантию уникальности |

```bash
kubectl get sts
kubectl get pvc                                   # data-postgres-0, -1, -2
kubectl delete pod postgres-1                     # вернётся под тем же именем и с тем же PVC
kubectl scale sts postgres --replicas=2           # postgres-2 уйдёт, PVC останется
kubectl delete sts postgres --cascade=orphan      # удалить контроллер, оставив поды
```

> ⚠️ **StatefulSet не делает приложение кластерным.** Он даёт только имена, порядок и диски.
> Репликацию, выборы лидера и восстановление обеспечивает само приложение
> (Patroni для PostgreSQL, встроенные механизмы Kafka и т. д.). Это ключевая мысль
> и частый уточняющий вопрос на собесе.

---

## 4. Стоит ли тащить базу в кластер

Роадмап в практике прямо пишет: «базу не обязательно тащить в кластер». Это разумно.

| За | Против |
|----|--------|
| Единое описание всего стека | Нужен опыт: бэкапы, PITR, failover, обновления мажорных версий |
| Одинаковые окружения dev/prod | Дисковая производительность в кластере хуже прогнозируется |
| Удобно для dev/test-стендов | Инцидент с данными дороже любого простоя stateless-части |
| Операторы (Zalando, CNPG) многое умеют | Оператор — это ещё одна система, которую надо знать |

**Разумная позиция для собеса:** «Stateless — в кубер обязательно. Для БД на проде
беру managed-сервис, если он есть; если нет — только через зрелый оператор
с проверенным восстановлением из бэкапа. В dev/test держу БД в кластере
StatefulSet'ом — там цена ошибки нулевая».

---

## 5. Как выбрать контроллер: алгоритм

```text:no-line-numbers
Нужен ли под на КАЖДОЙ ноде (агент, сеть, логи)?
   └─ да → DaemonSet

Нужны ли подам стабильные имена, персональные диски или строгий порядок?
   └─ да → StatefulSet

Задача разовая или по расписанию?
   └─ да → Job / CronJob (тема 07)

Иначе → Deployment   ← 90 % случаев
```

---

## 💼 Как это в DevOps

- В типичном кластере: десятки Deployment'ов, 3-6 DaemonSet'ов (логи, метрики, CNI, CSI)
  и 1-3 StatefulSet'а (если что-то stateful вообще внутри).
- DaemonSet — первое, что проверяют при «странностях на одной ноде»: не обновился агент,
  не хватило ресурсов, taint не протолерирован.
- Обновление StatefulSet с БД — всегда отдельная процедура с бэкапом до начала,
  `partition` для постепенности и проверкой репликации между шагами.
- PVC от StatefulSet — самая частая причина «потерянных» дисков и счетов в облаке:
  контроллер удалили, а тома остались. Ставь напоминание чистить.
- `kubectl delete pod --force` для StatefulSet — почти всегда неправильно;
  сначала разбираются с нодой.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Агент на каждой ноде | DaemonSet |
| Агент и на control-plane | `tolerations: [{operator: Exists}]` |
| Обновить DaemonSet по одной ноде | `updateStrategy.rollingUpdate.maxUnavailable: 1` |
| БД с персональным диском | StatefulSet + `volumeClaimTemplates` |
| Персональные DNS-имена подов | headless Service (`clusterIP: None`) + `serviceName` |
| Стартовать поды параллельно | `podManagementPolicy: Parallel` |
| Канареечное обновление StatefulSet | `updateStrategy.rollingUpdate.partition: N` |
| Уменьшить БД-кластер, сохранив данные | `kubectl scale sts` — PVC останутся |
| Удалить контроллер, оставив поды | `kubectl delete sts X --cascade=orphan` |
| Посмотреть PVC подов | `kubectl get pvc` (имена вида `data-<sts>-N`) |

---

## 🧠 Что запомнить

1. ⭐ Deployment — stateless и взаимозаменяемые поды; StatefulSet — имена, порядок, диски;
   DaemonSet — по поду на ноду.
2. У StatefulSet поды называются `имя-0`, `имя-1`… и имена стабильны.
3. `volumeClaimTemplates` создаёт **персональный PVC на каждый под**.
4. StatefulSet требует **headless Service** (`clusterIP: None`) для персональных DNS-имён.
5. Создание StatefulSet — по порядку 0→1→2, удаление и обновление — в обратном.
6. Уменьшение реплик и удаление StatefulSet **не удаляют PVC** — чистить руками.
7. StatefulSet не реплицирует данные: репликация — задача самого приложения.
8. У DaemonSet нет `replicas`; число подов определяется числом подходящих нод.
9. Чтобы DaemonSet попал на control-plane ноды, нужны `tolerations`.
10. DaemonSet обычно требует `hostPath`/`hostNetwork` и щедрых привилегий — держи это в уме
    при разговоре о безопасности.
11. `partition` в StatefulSet — механизм постепенного обновления кластера БД.
12. Базу на проде — в managed или через зрелый оператор; в dev — StatefulSet'ом спокойно.

---

## Задачи

> ⭐ Здесь **вопрос собеса №1**: *«Чем отличаются Deployment, StatefulSet, DaemonSet?»*
> Задача-минимум по этой теме: отвечать на него без единой паузы.

---

### Блок A. Теория

**A1.** ⭐ Назови три отличия Deployment от StatefulSet.

<details><summary>Ответ</summary>

Имена подов (случайные vs порядковые и стабильные); хранилище (общее/без него
vs персональный PVC на под); порядок создания, удаления и обновления (произвольный
vs строгий). Плюс персональные DNS-имена у StatefulSet.

</details>

**A2.** ⭐ Назови три отличия DaemonSet от Deployment.

<details><summary>Ответ</summary>

Число подов (задаётся `replicas` vs равно числу подходящих нод);
привязка к нодам (любая нода vs ровно по одному на ноду); реакция на добавление ноды
(ничего vs автоматически новый под).

</details>

**A3.** ⭐ Сформулируй ответ на вопрос «чем отличаются Deployment, StatefulSet, DaemonSet»
за 30 секунд.

<details><summary>Ответ</summary>

См. формулировку в конспекте, §1: stateless и взаимозаменяемые поды —
Deployment; идентичность, порядок и персональные диски — StatefulSet;
по одному поду на каждой ноде для агентов — DaemonSet.

</details>

**A4.** Как называются поды StatefulSet и почему это важно?

<details><summary>Ответ</summary>

`<имя>-0`, `<имя>-1`, … Порядковый номер связывает под с его PVC и DNS-именем,
поэтому пересозданный под получает тот же диск и то же имя.

</details>

**A5.** Что такое `volumeClaimTemplates` и что он создаёт?

<details><summary>Ответ</summary>

Шаблон PVC: для каждого пода StatefulSet создаётся собственный PVC
с именем `<имя тома>-<имя sts>-<номер>`.

</details>

**A6.** Что такое headless Service и зачем он StatefulSet'у?

<details><summary>Ответ</summary>

Service с `clusterIP: None`: он не балансирует, а возвращает адреса всех подов
и создаёт DNS-записи для каждого пода. Без него у подов не будет персональных имён.

</details>

**A7.** Какое DNS-имя будет у второго пода StatefulSet `kafka` в namespace `data`?

<details><summary>Ответ</summary>

`kafka-1.kafka.data.svc.cluster.local` (при `serviceName: kafka`).

</details>

**A8.** В каком порядке создаются и удаляются поды StatefulSet?

<details><summary>Ответ</summary>

Создаются по возрастанию (0, 1, 2), каждый следующий — после готовности
предыдущего; удаление и обновление — по убыванию.

</details>

**A9.** Что делает `podManagementPolicy: Parallel` и когда это уместно?

<details><summary>Ответ</summary>

Запускает и удаляет поды параллельно, не дожидаясь готовности соседей.
Уместно, когда поды не зависят друг от друга (например, шардированное хранилище
без кворума при старте).

</details>

**A10.** Что произойдёт с PVC при `kubectl scale sts db --replicas=1`?

<details><summary>Ответ</summary>

PVC остаются: кубер не удаляет данные при уменьшении числа реплик.
Если снова увеличить реплики, поды подключат прежние тома.

</details>

**A11.** Что произойдёт с PVC при удалении StatefulSet?

<details><summary>Ответ</summary>

Тоже остаются (если не настроена политика удаления PVC в новых версиях API).
Удалять надо явно: `kubectl delete pvc -l app=db`.

</details>

**A12.** ⭐ Обеспечивает ли StatefulSet репликацию данных между подами?

<details><summary>Ответ</summary>

Нет. Он даёт только identity, порядок и персональные тома. Репликация,
выборы лидера и восстановление — задача приложения или оператора.

</details>

**A13.** Что такое `partition` в `updateStrategy` и зачем он нужен?

<details><summary>Ответ</summary>

Номер, начиная с которого поды обновляются. Позволяет обновить только часть
кластера (канареечно) и проверить результат до полной выкатки.

</details>

**A14.** Что делает `updateStrategy.type: OnDelete`?

<details><summary>Ответ</summary>

Отключает автоматическое обновление: под обновится только после того,
как его вручную удалят. Применяется там, где момент рестарта критичен.

</details>

**A15.** Почему у DaemonSet нет поля `replicas`?

<details><summary>Ответ</summary>

Потому что желаемое состояние — «по одному поду на каждой подходящей ноде»,
и число подов определяется числом нод, а не пользователем.

</details>

**A16.** Как заставить DaemonSet запуститься на control-plane нодах?

<details><summary>Ответ</summary>

Добавить `tolerations`, соответствующие taint'ам control-plane
(`node-role.kubernetes.io/control-plane:NoSchedule`), либо `operator: Exists`
для терпимости ко всем taint'ам.

</details>

**A17.** Как ограничить DaemonSet частью нод?

<details><summary>Ответ</summary>

Через `nodeSelector` или `nodeAffinity` по меткам нод.

</details>

**A18.** Что произойдёт с DaemonSet при добавлении новой ноды в кластер?

<details><summary>Ответ</summary>

Контроллер автоматически создаст на ней под — это и есть смысл DaemonSet.

</details>

**A19.** Назови пять реальных применений DaemonSet.

<details><summary>Ответ</summary>

Сбор логов (fluent-bit, vector), метрики ноды (node-exporter), сетевые плагины
(Calico, Cilium), `kube-proxy`, CSI node-плагины, агенты безопасности и мониторинга.

</details>

**A20.** Почему у DaemonSet особенно важно аккуратно задавать `requests`/`limits`?

<details><summary>Ответ</summary>

Ресурсы умножаются на число нод: лишние 100 Mi на 200 нодах — это 20 Gi
суммарно, которые вычитаются из ёмкости кластера.

</details>

**A21.** Что такое `hostPath`, `hostNetwork`, `hostPID` и почему они нужны DaemonSet'ам?

<details><summary>Ответ</summary>

Доступ к файловой системе ноды, к её сетевому и PID namespace. Нужны агентам,
которые обязаны видеть саму ноду: логи контейнеров, метрики ядра, сетевые правила.

</details>

**A22.** Почему `kubectl delete pod --force` особенно опасен для StatefulSet?

<details><summary>Ответ</summary>

Форс удаляет объект из API, не убедившись, что процесс остановлен. Для
StatefulSet это нарушает гарантию «одна identity — один под»: новый под подключит
тот же том, пока старый процесс, возможно, ещё пишет в него.

</details>

**A23.** Под StatefulSet завис в `Terminating` на упавшей ноде. Почему новый под
не создаётся автоматически?

<details><summary>Ответ</summary>

Кубер не может подтвердить, что под действительно остановлен (нода недоступна),
и не создаёт замену, чтобы не получить два экземпляра с одним томом. Решение —
восстановить ноду или удалить объект Node/под осознанно.

</details>

**A24.** Какой контроллер выбрать: сборщик логов; фронтенд; Kafka; ночной отчёт;
CSI-драйвер; API-сервис?

<details><summary>Ответ</summary>

Сборщик логов — DaemonSet; фронтенд — Deployment; Kafka — StatefulSet
(лучше через оператор); ночной отчёт — CronJob; CSI-драйвер — DaemonSet (+Deployment
для контроллерной части); API-сервис — Deployment.

</details>

**A25.** Стоит ли держать прод-БД в кластере? Ответь как на собесе.

<details><summary>Ответ</summary>

Stateless — однозначно в кубер. Для прод-БД предпочтительнее managed-сервис;
если его нет — зрелый оператор, проверенные бэкапы и отработанное восстановление.
В dev/test держать БД в кластере нормально.

</details>

---

### Блок B. «Что произойдёт»

**B1.**
```bash
kubectl get pods
# db-0   1/1   Running
# db-1   1/1   Running
kubectl delete pod db-0
kubectl get pods
```
Вопрос: как будет называться новый под и какой PVC он подключит?

<details><summary>Ответ</summary>

Новый под снова `db-0` и подключит тот же PVC `data-db-0` со всеми данными.

</details>

**B2.**
```bash
kubectl scale sts db --replicas=5
kubectl get pods -w
```
Вопрос: в каком порядке появятся поды? Сколько PVC будет в итоге?

<details><summary>Ответ</summary>

Последовательно: `db-2`, затем `db-3`, затем `db-4` (каждый после готовности
предыдущего). PVC станет пять.

</details>

**B3.**
```bash
kubectl scale sts db --replicas=2
kubectl get pvc
```
Вопрос: сколько PVC останется и почему?

<details><summary>Ответ</summary>

Останутся все пять: уменьшение реплик не удаляет тома.

</details>

**B4.**
```yaml
kind: StatefulSet
spec:
  serviceName: db
  replicas: 3
# Service с clusterIP: None не создан
```
Вопрос: что сломается?

<details><summary>Ответ</summary>

Поды создадутся, но не получат персональных DNS-имён; приложения, которые
находят друг друга по именам (кластерные БД, Kafka), работать не будут.

</details>

**B5.**
```bash
kubectl get ds -n kube-system kube-proxy
# DESIRED  CURRENT  READY  UP-TO-DATE  AVAILABLE  NODE SELECTOR
#    3        3       3        3           3      kubernetes.io/os=linux
# добавили в кластер 2 новые ноды
```
Вопрос: что покажет команда через минуту?

<details><summary>Ответ</summary>

`DESIRED 5`, и через некоторое время `CURRENT/READY 5` — контроллер сам
добавит поды на новые ноды.

</details>

**B6.**
```yaml
kind: DaemonSet
spec:
  template:
    spec:
      tolerations: []
```
Вопрос: попадёт ли под на control-plane ноду в кластере kubeadm?

<details><summary>Ответ</summary>

Нет: на control-plane нодах стоит taint `NoSchedule`, и без tolerations
под туда не попадёт.

</details>

**B7.**
```yaml
kind: StatefulSet
spec:
  replicas: 3
  updateStrategy:
    rollingUpdate: { partition: 2 }
# меняем образ
```
Вопрос: какие поды обновятся?

<details><summary>Ответ</summary>

Только `db-2` (номера ≥ partition). `db-0` и `db-1` останутся на старом образе.

</details>

**B8.**
```bash
kubectl delete sts db --cascade=orphan
kubectl get pods
```
Вопрос: что произойдёт с подами?

<details><summary>Ответ</summary>

Поды останутся работать, но станут «сиротами» — без контроллера, который
их восстановит. Иногда используется при миграциях.

</details>

**B9.**
```yaml
kind: Deployment
spec:
  replicas: 3
  template:
    spec:
      volumes:
        - name: data
          persistentVolumeClaim: { claimName: shared-pvc }   # accessMode RWO
```
Вопрос: смогут ли все три пода запуститься?

<details><summary>Ответ</summary>

Нет: том с `ReadWriteOnce` может быть смонтирован на запись только на одной
ноде. Если поды попали на разные ноды, лишние останутся в `Pending`/
`FailedAttachVolume`. Нужны либо RWX-том, либо StatefulSet с персональными томами.

</details>

---

### Блок C. Практика

#### C1. 🔑 StatefulSet с нуля
Напиши headless Service + StatefulSet на 3 реплики (можно `nginx` для простоты)
с `volumeClaimTemplates` на 1Gi.
1. Примени и наблюдай порядок создания подов (`kubectl get pods -w`).
2. Проверь имена подов и имена PVC.
3. Запиши, сколько времени занял старт каждого следующего пода.

#### C2. 🔑 Стабильность identity
1. Запиши в файл на томе пода `db-1` строку с его именем.
2. Удали под `db-1`.
3. Дождись пересоздания и проверь, что файл на месте.
4. Объясни, почему так работает, и чем это отличается от Deployment с общим PVC.

<details><summary>Ответ</summary>

Данные на месте, потому что PVC привязан к порядковому номеру пода.
В Deployment общий PVC означает, что все реплики пишут в один том (и то только
при поддержке RWX), — это принципиально другая модель.

</details>

#### C3. DNS подов
Из временного пода выполни:
```bash
nslookup db-0.db
nslookup db                  # headless — вернёт все адреса
```
Запиши разницу между обращением к конкретному поду и к сервису.

<details><summary>Ответ</summary>

`db-0.db` резолвится в IP конкретного пода; `db` (headless) возвращает
список всех IP подов без балансировки.

</details>

#### C4. Порядок удаления
`kubectl scale sts db --replicas=0` и наблюдай `kubectl get pods -w`.
Запиши порядок. Потом `--replicas=3` и снова запиши.

#### C5. PVC переживают всё
1. `kubectl scale sts db --replicas=1` → сколько PVC?
2. `kubectl delete sts db` → сколько PVC?
3. Создай StatefulSet заново с тем же именем — подключатся ли старые тома с данными?
4. Убери за собой PVC руками.

<details><summary>Ответ</summary>

PVC остаются во всех случаях; новый StatefulSet с тем же именем и тем же
`volumeClaimTemplates` подключит существующие PVC и увидит старые данные.

</details>

#### C6. podManagementPolicy
Сделай второй StatefulSet с `podManagementPolicy: Parallel` и сравни скорость старта
трёх подов с вариантом `OrderedReady`. Запиши время.

#### C7. 🔑 DaemonSet
Напиши DaemonSet с `busybox`, который просто спит, и проверь:
1. по одному ли поду на каждой ноде;
2. что произойдёт, если добавить ноду (`kind: docker` — можно пересоздать кластер
   с бóльшим числом нод или использовать `nodeSelector`, помечая ноды метками);
3. что произойдёт, если снять метку с ноды при использовании `nodeSelector`.

#### C8. DaemonSet на control-plane
1. Убедись, что под не попал на control-plane ноду.
2. Посмотри taint'ы: `kubectl describe node <cp> | grep -i taint`.
3. Добавь `tolerations` и проверь снова.

<details><summary>Ответ</summary>

У control-plane ноды taint `node-role.kubernetes.io/control-plane:NoSchedule`;
после добавления tolerations под появляется и там.

</details>

#### C9. Обновление DaemonSet
Поменяй образ в DaemonSet и наблюдай обновление при `maxUnavailable: 1`.
Запиши, по сколько подов обновляется за раз. Потом попробуй `OnDelete`
и убедись, что поды не обновляются, пока их не удалишь.

#### C10. partition
На StatefulSet из трёх подов поставь `partition: 2`, обнови образ, проверь,
какие поды обновились. Потом опусти `partition` до 0 и посмотри, что произойдёт.

<details><summary>Ответ</summary>

При `partition: 2` обновится только `db-2`; после `partition: 0` —
оставшиеся, в порядке убывания номеров.

</details>

#### C11. 🔑 PostgreSQL в StatefulSet
Разверни PostgreSQL StatefulSet'ом (1 реплика, PVC 2Gi, пароль из Secret).
1. Подключись `kubectl exec -it db-0 -- psql -U postgres`.
2. Создай таблицу и запись.
3. Удали под, дождись пересоздания, проверь, что данные на месте.
4. Удали StatefulSet и создай заново — данные всё ещё на месте?

#### C12. Выбор контроллера
Для каждой задачи напиши контроллер и одну строку обоснования:
сборщик логов; веб-API; Redis-кластер; ночная выгрузка; экспортёр метрик ноды;
воркер очереди; MinIO; агент безопасности.

#### C13. Ломаем гарантию (со звёздочкой)
Останови ноду, на которой живёт под StatefulSet'а.
1. Посмотри, появился ли новый под.
2. Объясни поведение кубера.
3. Найди в документации, какие действия оператор должен выполнить вручную.

<details><summary>Ответ</summary>

Новый под не создастся, пока старый числится живым: кубер защищает гарантию
уникальности identity. Оператору нужно убедиться, что нода действительно мертва,
и удалить объект Node (или под) осознанно.

</details>

#### C14. Ресурсы DaemonSet (со звёздочкой)
Посчитай, сколько памяти и CPU суммарно съест твой DaemonSet в кластере на 50 нод
при текущих `requests`. Сравни с суммарной ёмкостью и сделай вывод.

---

### Блок D. Инциденты

**D1.** На одной ноде не собираются логи, на остальных всё в порядке. Куда смотришь?

<details><summary>Ответ</summary>

Под DaemonSet на этой ноде: `kubectl get pods -o wide`, его статус и события;
проверить taint'ы ноды и tolerations, ресурсы ноды, доступность `hostPath`,
не отвалился ли kubelet.

</details>

**D2.** После добавления трёх нод в кластер `node-exporter` появился только на двух.
Причины?

<details><summary>Ответ</summary>

У третьей ноды есть taint без соответствующей toleration; не подходит
`nodeSelector`/`nodeAffinity`; не хватает ресурсов; нода `NotReady`.

</details>

**D3.** `postgres-1` не стартует, `postgres-2` не создаётся вообще. Объясни связь.

<details><summary>Ответ</summary>

StatefulSet создаёт поды по порядку: пока `postgres-1` не станет Ready,
`postgres-2` не начнёт создаваться. Чинить надо `postgres-1`.

</details>

**D4.** В облаке обнаружили 40 неиспользуемых дисков со счётом за хранение.
Откуда они взялись?

<details><summary>Ответ</summary>

Это PVC от StatefulSet'ов, оставшиеся после удаления контроллеров или
уменьшения реплик. Тома не удаляются автоматически.

</details>

**D5.** Разработчик сделал Deployment с `replicas: 3` и общим PVC `ReadWriteOnce`.
Два пода в `Pending`. Объясни и предложи решение.

<details><summary>Ответ</summary>

RWO-том монтируется только на одну ноду: поды на других нодах не могут его
подключить. Решения: StatefulSet с персональными томами; RWX-хранилище (NFS,
CephFS); вынести состояние из приложения.

</details>

**D6.** Кластер Kafka переехал на новые ноды и «потерял» брокеров.
Какие гарантии StatefulSet были нарушены и почему?

<details><summary>Ответ</summary>

Скорее всего, были потеряны персональные тома или изменились имена/DNS:
брокеры Kafka идентифицируют себя по стабильным именам и данным на диске.

</details>

**D7.** Под `db-0` завис в `Terminating` после падения ноды. Дежурный сделал
`--force --grace-period=0`. Чем это может закончиться?

<details><summary>Ответ</summary>

Возможен запуск второго экземпляра с тем же томом: повреждение данных,
расхождение реплик. Правильный путь — убедиться, что нода мертва, и только затем
осознанно удалять объекты.

</details>

**D8.** DaemonSet съел всю память на нодах после обновления образа.
Что не было настроено и как обновлять безопасно?

<details><summary>Ответ</summary>

Не были заданы `limits`/`requests` и не использовалось постепенное обновление.
Обновлять с `maxUnavailable: 1`, а на крупных кластерах — ещё аккуратнее,
предварительно проверив образ на одной ноде.

</details>

**D9.** После `kubectl delete sts db` данные остались, но новый StatefulSet
с тем же именем не видит старые тома. Что могло пойти не так?

<details><summary>Ответ</summary>

Имена PVC зависят от имени тома в `volumeClaimTemplates` и имени StatefulSet:
если изменилось хотя бы одно, создадутся новые пустые PVC. Плюс проверить namespace
и StorageClass.

</details>

**D10.** Обновили StatefulSet с PostgreSQL — все три пода обновились одновременно,
кластер лёг. Как надо было?

<details><summary>Ответ</summary>

Использовать `partition` и обновлять по одному поду, начиная с реплики,
а не с лидера; перед обновлением снять бэкап; между шагами проверять репликацию.
Для БД правильнее оператор, умеющий делать switchover.

</details>

**D11.** `kube-proxy` (DaemonSet) не запустился на новой ноде, и поды на ней
не видят сервисов. Как это выглядит для пользователя и где смотреть?

<details><summary>Ответ</summary>

На этой ноде не работают ClusterIP-сервисы: приложения получают таймауты
при обращении к другим сервисам, но работают по прямым IP подов. Смотреть под
`kube-proxy` на ноде, его логи и события.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Чем отличаются Deployment, StatefulSet и DaemonSet? *(вопрос роадмапа)*

<details><summary>Ответ</summary>

Deployment — stateless, взаимозаменяемые поды со случайными именами;
StatefulSet — стабильные имена, DNS и персональные тома, строгий порядок;
DaemonSet — по одному поду на каждой подходящей ноде.

</details>

**2.** Когда нужен StatefulSet и какие гарантии он даёт?

<details><summary>Ответ</summary>

Когда приложению нужны идентичность, персональный диск или порядок запуска:
кластерные БД, брокеры сообщений, хранилища.

</details>

**3.** Что такое headless Service?

<details><summary>Ответ</summary>

Service с `clusterIP: None`: не балансирует, а отдаёт адреса подов и создаёт
персональные DNS-записи.

</details>

**4.** Что такое volumeClaimTemplates?

<details><summary>Ответ</summary>

Шаблон, по которому каждому поду StatefulSet создаётся собственный PVC.

</details>

**5.** Что произойдёт с томами при удалении StatefulSet?

<details><summary>Ответ</summary>

Остаются: данные не удаляются вместе с контроллером, чистить нужно вручную.

</details>

**6.** Реплицирует ли StatefulSet данные?

<details><summary>Ответ</summary>

Нет, репликация — ответственность приложения или оператора.

</details>

**7.** Где применяется DaemonSet?

<details><summary>Ответ</summary>

Агенты уровня ноды: логи, метрики, сеть, CSI, безопасность.

</details>

**8.** Как обновить DaemonSet без просадки?

<details><summary>Ответ</summary>

`updateStrategy: RollingUpdate` с `maxUnavailable: 1`, при необходимости
предварительная проверка на одной ноде; для критичных агентов — `OnDelete`.

</details>

**9.** Можно ли запускать базы данных в Kubernetes? Твоё мнение и аргументы.

<details><summary>Ответ</summary>

Можно; вопрос в цене ошибки: managed — предпочтительно, иначе зрелый оператор
и проверенное восстановление; для dev-сред кубер подходит всегда.

</details>

**10.** Почему нельзя дать трём подам Deployment один RWO-том?

<details><summary>Ответ</summary>

`ReadWriteOnce` допускает монтирование на запись только с одной ноды;
нужны персональные тома (StatefulSet) или RWX-хранилище.

</details>

---

### 🎯 Чек-лист

- [ ] ⭐ Отвечаю на «чем отличаются Deployment/StatefulSet/DaemonSet» без пауз
- [ ] Поднял StatefulSet с `volumeClaimTemplates` и проверил стабильность данных
- [ ] Понимаю, зачем headless Service и как выглядит DNS-имя пода
- [ ] Знаю, что PVC переживают и scale, и удаление StatefulSet
- [ ] Помню, что StatefulSet не делает репликацию
- [ ] Поднял DaemonSet и добился запуска на control-plane через tolerations
- [ ] Понимаю `partition` и `OnDelete`
- [ ] Умею выбрать контроллер под задачу за пять секунд
- [ ] Сформулировал свою позицию про БД в кластере
