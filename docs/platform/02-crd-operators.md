---
title: "02. CRD и операторы: API платформы и паттерн контроллера"
description: "Блок → Platform Engineering → тема 02. Вопросы собеса: «Что такое оператор?»,"
---

# 02. CRD и операторы: API платформы и паттерн контроллера

> Блок → Platform Engineering → тема 02. Вопросы собеса: *«Что такое оператор?»*,
> *«Чем level-triggered отличается от edge-triggered?»*, *«Зачем finalizer и что делать,
> если namespace завис в Terminating?»*, *«Как версионировать CRD?»*
> **После темы ты умеешь:** написать CRD со структурной схемой, дефолтами, enum и
> CEL-правилами (неизменяемость, правила между полями); включить status и scale,
> колонки для `kubectl get`; объяснить версии и конверсию; описать reconcile loop,
> informers и идемпотентность; пользоваться owner references, finalizers и leader election;
> оценить готовый оператор по уровням зрелости; спроектировать API `LinkdApp`,
> который оператор из темы 03 будет реализовывать.
> Версии и статусы фич — «проверь, сентябрь 2026» (стенд — `kindest/node:v1.36.4`).

База «что такое CRD и оператор, зачем они» — [../Kubernetes/21_advanced_paths.md](/kubernetes/21-advanced-paths) §2.
Здесь — как делать **правильно**.

---

## 🗺️ Карта темы

```text
  команда пишет                API-сервер                      оператор (тема 03)
 ┌──────────────┐   apply   ┌──────────────────────────┐ watch ┌──────────────────────┐
 │ LinkdApp     │ ────────► │ CRD: схема + defaults    │ ────► │ informer → cache     │
 │ spec:        │           │ + CEL-правила (§2–3)     │       │   → очередь событий  │
 │  image, host │ ◄──────── │ отказ с понятным message │       │   → reconcile(name)  │
 │  replicas    │  ошибка   │ etcd: storage version    │       │ желаемое vs реальное │
 └──────────────┘           └────────────┬─────────────┘       └─────────┬────────────┘
        ▲                                │ status (§4)                   │ create/patch
        │  kubectl get la                │                               ▼
        │  READY REPLICAS URL (§5)       │           Deployment · Service · HTTPRoute
        └────────────────────────────────┘           ownerReferences → LinkdApp (§8)
   удаление: deletionTimestamp → finalizer (§9) → уборка внешнего → GC детей
```text
---

## 1. CRD — это публичный API платформы

Когда платформа даёт командам `LinkdApp`, это **контракт**: его будут писать в git,
на него завяжут CI и шаблоны Backstage. Сломать поле — как сломать публичный REST API.

Что CRD даёт бесплатно по сравнению со «своим REST-сервисом для деплоя»: **RBAC**
(`create linkdapps` — команде в её namespace, тема 17), **kubectl** (`explain` берёт описание
из схемы, `get -w`, `-o yaml`), **watch и resourceVersion** (события и оптимистичная
блокировка), **GitOps** (ArgoCD синхронизирует CR как любой YAML), **аудит, admission, квоты**.

> 💡 Альтернатива — **aggregated API server** (свой API-сервер за kube-apiserver, как metrics-server):
> когда нельзя хранить в etcd. Для платформенных API почти всегда хватает CRD.

---

## 2. Структурная схема: типы, дефолты, enum

В `apiextensions.k8s.io/v1` схема **обязательна** и должна быть **структурной**: у каждого
поля указан `type`, нет «угадываемых» полей. Всё, чего нет в схеме, API-сервер **вырезает**
при записи (pruning). `kubectl` по умолчанию просит строгую проверку полей
(`--validate=strict`, server-side field validation GA 1.27) и получит отказ `unknown field`;
клиент без неё (скрипт, чужой контроллер, `--validate=false`) — поле молча исчезнет.

| Ключ | Пример | Зачем |
|------|--------|-------|
| `type` | `string`, `integer`, `boolean`, `object`, `array`, `number` | Обязательно на каждом уровне |
| `required` | `required: [image, host]` | Без поля объект не создать |
| `default` | `default: 1` | Проставляется при записи и чтении; пишется в etcd |
| `enum` | `enum: [small, medium, large]` | Закрытый список значений |
| `minimum` / `maximum`, `pattern` | `minimum: 1`, `'^[a-z0-9-]+$'` | Диапазон чисел, регулярка для строки |
| `maxLength` / `maxItems` / `maxProperties` | `maxLength: 253` | ⭐ Ограничения размера — нужны и для стоимости CEL (§3) |
| `format`, `nullable` | `date-time`; `nullable: true` | Формат (проверяются не все); разрешить `null` |
| `x-kubernetes-preserve-unknown-fields` | `true` | Не вырезать неизвестные поля (для «произвольного» блока — осторожно) |
| `x-kubernetes-int-or-string` | `true` | Как `targetPort`: `8080` или `"http"` |
| `x-kubernetes-list-type` | `map` + `x-kubernetes-list-map-keys: [type]` | Список как словарь по ключу — нужно для server-side apply и conditions |

> ⚠️ `default` не работает внутри поля, которого нет: дефолт для `spec.db.size` сработает,
> только если объект `spec.db` передан (или у него самого есть `default: {}`).

---

## 3. CEL-правила: `x-kubernetes-validations`

Схема не выразит «если A, то B» или «нельзя менять после создания». Для этого — правила
на **CEL** прямо в CRD, без вебхука. **GA с Kubernetes 1.29.** Правило вешается на уровень
схемы: `self` — значение этого уровня, `oldSelf` — прежнее значение (только при update).

| Поле правила | Что задаёт |
|--------------|------------|
| `rule` | CEL-выражение, должно вернуть `true` |
| `message` | Текст ошибки |
| `messageExpression` | Текст ошибки, вычисляемый CEL (`"replicas " + string(self.replicas) + " > 5"`) |
| `reason` | Машинная причина: `FieldValueInvalid` (по умолчанию), `FieldValueForbidden`, `FieldValueRequired`, `FieldValueDuplicate` |
| `fieldPath` | Какое поле подсветить в ошибке (`.replicas`) |
| `optionalOldSelf` | `true` — правило с `oldSelf` вычисляется и при create (`oldSelf.hasValue()`) |

**Типовые правила:**

```yaml
# 1. Неизменяемое поле (правило на самом поле)
storageClass:
  type: string
  x-kubernetes-validations: [{ rule: "self == oldSelf", message: "storageClass нельзя менять после создания" }]

# 2. Переход только в одну сторону: включить можно, выключить — нет
database:
  type: boolean
  x-kubernetes-validations: [{ rule: "self || !oldSelf", message: "database нельзя выключить — данные будут потеряны" }]

# 3. Правила между полями — на общем родителе (spec); has() — задано ли поле
spec:
  type: object
  x-kubernetes-validations:
    - { rule: "self.minReplicas <= self.maxReplicas", message: "minReplicas > maxReplicas", fieldPath: .minReplicas }
    - { rule: "has(self.tls) == has(self.host)", message: "tls задаётся только вместе с host" }
    - { rule: "!has(oldSelf.owner) || has(self.owner)", message: "owner нельзя удалить" }

# 4. Списки: уникальность (maxItems обязателен — иначе правило слишком «дорогое»)
ports:
  type: array
  maxItems: 16
  items: { type: integer, minimum: 1, maximum: 65535 }
  x-kubernetes-validations: [{ rule: "self.all(p, self.exists_one(q, q == p))", message: "порты не должны повторяться" }]
```text
| Нюанс | Что знать |
|-------|-----------|
| Правила с `oldSelf` | ⭐ Вычисляются только на **update** и только если старое значение есть |
| Стоимость | API-сервер оценивает «цену» правила заранее; строка без `maxLength` или список без `maxItems` → правило с `all()` отклонят как слишком дорогое |
| Ratcheting (GA 1.33) | Если ужесточили схему, старые объекты можно обновлять, пока не трогаешь невалидные поля |
| Проверка | `kubectl apply --dry-run=server -f bad.yaml` — ошибка без записи |
| Когда CEL мало | Нужны внешние данные (есть ли такой образ в реестре, свободен ли host) → webhook (тема 04) |

> 💡 Правила в CRD — **для корректности API** (своё поле, свой объект). Правила
> «организации» (host только в домене команды, образы только из нашего registry) — политикой
> (VAP / Kyverno, тема 04): они меняются чаще и касаются разных типов.

---

## 4. Status, conditions и observedGeneration

`subresources: { status: {} }` делит объект на две части с **разными** путями API:
`/linkdapps/x` — для spec (пишет команда), `/linkdapps/x/status` — для status (пишет оператор).

Запись в основной путь **игнорирует** `status` (команда не «нарисует» себе Ready), запись
в `/status` игнорирует всё, кроме status (оператор не затрёт spec), RBAC — отдельно
(`linkdapps/status`), а ⭐ `metadata.generation` растёт **только** при изменении spec.

**Conditions** — стандартный формат статуса (тип `metav1.Condition`), его понимают
`kubectl wait`, ArgoCD, Backstage и kstatus:

| Поле | Пример | Правило |
|------|--------|---------|
| `type` | `Ready`, `DatabaseReady` | CamelCase; прилагательное или прошедшее время («Ready», «Failed») |
| `status` | `"True"` / `"False"` / `"Unknown"` | Строка, не boolean; отсутствие условия = Unknown |
| `reason` | `DeploymentUnavailable` | CamelCase-идентификатор для машин |
| `message` | `"1/2 реплик готовы: ImagePullBackOff"` | Для людей: что не так и что делать |
| `observedGeneration` | `3` | По какой версии spec поставлено |
| `lastTransitionTime` | `2026-09-28T10:00:00Z` | Когда **status** сменился (а не когда проверяли) |

```yaml
status:
  observedGeneration: 3            # ⭐ == metadata.generation → оператор видел последний spec
  replicas: 2
  readyReplicas: 2
  url: http://links.team-a.example.com/
  conditions:
    - { type: Ready, status: "True", reason: AllResourcesReady, observedGeneration: 3,
        message: "Deployment 2/2, HTTPRoute Accepted", lastTransitionTime: "2026-09-28T10:00:00Z" }
```text
> ⭐ **Правило:** оператор ставит условие **сразу**, даже `Unknown` («Reconciling»),
> и всегда пишет `observedGeneration`. Если `observedGeneration < generation` — статус
> устарел, верить `Ready=True` нельзя. CI ждёт так: `kubectl wait la/shortener
> --for=condition=Ready` **и** сверяет `generation` с `observedGeneration`.

---

## 5. Как CR выглядит в kubectl: колонки, scale, поиск

Всё это есть в полном CRD в §12 — здесь что за что отвечает:

| Где в CRD | Что даёт |
|-----------|----------|
| `spec.names.shortNames: [la]`, `categories: [platform]` | `kubectl get la`; `kubectl get platform` — все CR платформы разом |
| `versions[].additionalPrinterColumns` | Колонки `kubectl get` по `jsonPath`; `priority: 1` — только в `-o wide`; ⚠️ свои колонки убирают `AGE` — добавь явно |
| `versions[].subresources.scale` | `kubectl scale la/x --replicas=3` и HPA на CR; нужен `labelSelectorPath` (строка селектора в status) |
| `versions[].selectableFields` (GA 1.32) | `kubectl get la --field-selector spec.size=large` |

---

## 6. Версии и конверсия

API живёт годами, поэтому версии — сразу: `v1alpha1` (может ломаться) → `v1beta1`
(стабилизируется) → `v1` (обещание совместимости).

```yaml
versions:
  - name: v1alpha1
    served: true                 # API отвечает на этой версии
    storage: false
    deprecated: true             # kubectl покажет warning
    deprecationWarning: "platform.example.com/v1alpha1 LinkdApp устарел, используйте v1beta1"
  - { name: v1beta1, served: true, storage: true }   # ⭐ storage — ровно одна: так лежит в etcd
conversion:
  strategy: Webhook              # None — только если схемы версий совпадают полностью
  webhook:
    conversionReviewVersions: [v1]
    clientConfig: { service: { name: linkd-operator, namespace: platform, path: /convert } }
```text
| Изменение | Можно в той же версии? |
|-----------|------------------------|
| Новое **необязательное** поле с дефолтом | ✅ Да |
| Новое обязательное поле, переименование, смена типа | ❌ Новая версия + конверсия |
| Ужесточение валидации | ⚠️ Осторожно: ratcheting спасает старые объекты, но новые manifests в git могут перестать проходить |

**Удаление старой версии:** в `status.storedVersions` CRD перечислены версии, в которых
объекты **ещё лежат** в etcd. Пока там есть `v1alpha1`, убирать её из CRD нельзя: сначала
перезаписать все объекты в новой версии (storage version migration), потом убрать версию
из `storedVersions`. Встроенный `StorageVersionMigration` — **GA и включён по умолчанию
в 1.37**; в 1.35–1.36 — beta и **выключен** по умолчанию (проверь, сентябрь 2026). На
стенде 1.36 проще перезаписать объекты руками: `kubectl get la -A -o json | kubectl replace -f -`.

> ⚠️ Две ловушки, найденные на живом кластере (проект 20-foundry):
> - при `conversion: None` и **разных схемах** версий оператор, который ещё читает и пишет
>   `v1alpha1`, стирает новое поле своей же записью — сначала переведи оператор на новую версию;
> - оператор с таймером сам перезаписывает объекты в etcd в storage-версии, но
>   `status.storedVersions` от этого не чистится — его убирают отдельно, после проверки.

> ⚠️ Conversion webhook — в пути **каждого** чтения старой версии. Лёг вебхук — не читаются
> объекты, ArgoCD и kubectl получают ошибки. Для учебной платформы держись одной версии
> и меняй схему только добавлением необязательных полей.

---

## 7. Паттерн контроллера

Контроллер — бесконечный цикл: **наблюдать → сравнить желаемое с реальным → сделать шаг
к желаемому → записать статус**. Он не «выполняет команду создать», а **сводит мир** к spec.

```text
            ┌──────────────── API-сервер ────────────────┐
            │  LinkdApp, Deployment, Service, HTTPRoute  │
            └───────▲───────────────────┬────────────────┘
       create/patch │                   │ LIST один раз, потом WATCH (поток изменений)
                    │                   ▼
            ┌───────┴──────┐    ┌──────────────────┐
            │  reconcile   │    │ informer: кэш в  │  чтения — из кэша, а не из API
            │  (ns, name)  │    │ памяти + события │
            └───────▲──────┘    └────────┬─────────┘
                    │  ключ «team-a/shortener»   │ событие по LinkdApp или по ребёнку
            ┌───────┴──────────────────────────▼─┐   (через ownerReference → ключ родителя)
            │ очередь: дедупликация, rate limit,  │
            │ повтор с backoff при ошибке         │
            └─────────────────────────────────────┘
```text
| Понятие | Что это | Почему важно |
|---------|---------|--------------|
| **Level-triggered** | Реакция на **текущее состояние**, а не на событие | ⭐ Пропустил событие (рестарт, сеть) — следующий reconcile всё равно приведёт к нужному |
| Edge-triggered | Реакция на **факт изменения** «было → стало» | Пропущенное событие = потерянное действие навсегда |
| Informer и кэш | LIST + WATCH, локальная копия объектов | Не долбить API-сервер; кэш может чуть отставать |
| Очередь | Ключи объектов, а не события; 10 событий по одному объекту → 1 reconcile | Дедупликация и повторы |
| Resync | Периодический повторный reconcile всех объектов | Страховка от пропущенных событий и дрейфа |
| Requeue | «Проверь меня через 30 секунд» | Ждём внешнего: база ещё создаётся |
| ⭐ Идемпотентность | Повторный запуск с тем же входом даёт тот же результат | Reconcile вызовут много раз — «создать, если уже есть» не должно падать |
| Оптимистичная блокировка | Запись с устаревшим `resourceVersion` → 409 Conflict | Перечитать и повторить, а не затирать |

**Как писать reconcile (правила, общие для kopf и Go):**
1. Входные данные — только имя объекта; всё остальное **перечитать** (не хранить состояние в памяти).
2. Вычислить желаемых детей из spec целиком, а не из «что изменилось».
3. Создать или обновить (create-or-update / server-side apply) — одинаково при первом и сотом вызове.
4. Прочитать статус детей, записать `status` + `observedGeneration`.
5. Ошибка → вернуть ошибку (очередь повторит с backoff); ждём внешнего → requeue.

> ⚠️ Анти-паттерн: `on_create` создаёт Deployment, `on_update` что-то патчит, а если оператор
> лежал во время изменения — изменение потеряно. Правильно: один **reconcile**, вызываемый
> на любое событие и по таймеру. В kopf это выражается связкой handlers + timer (тема 03).

---

## 8. Owner references и сборка мусора

Каждый ребёнок (Deployment, Service, HTTPRoute) ссылается на родителя:

```yaml
metadata:
  ownerReferences:
    - apiVersion: platform.example.com/v1alpha1
      kind: LinkdApp
      name: shortener
      uid: 6f1c…              # ⭐ по UID: пересоздали родителя с тем же именем — это другой владелец
      controller: true        # главный владелец (может быть только один)
      blockOwnerDeletion: true  # при foreground-удалении родитель ждёт этого ребёнка
```text
| Правило | Суть |
|---------|------|
| Удалили родителя → GC удаляет детей | Оператору не нужно чистить свои Kubernetes-объекты |
| Namespaced-ребёнок | Владелец — в **том же** namespace или cluster-scoped |
| Cluster-scoped ребёнок | Владелец — только cluster-scoped |
| Cross-namespace ownerReference | ❌ Запрещено: GC считает ссылку неразрешимой (событие `OwnerRefInvalidNamespace`) |
| События детей → reconcile родителя | Контроллер находит родителя по `controller: true` и ставит его в очередь |

| `propagationPolicy` | `kubectl delete --cascade=` | Что происходит |
|---------------------|------------------------------|----------------|
| Background (по умолчанию) | `background` | Родитель удалён сразу, детей GC уберёт следом |
| Foreground | `foreground` | Родитель висит с `deletionTimestamp`, пока не удалены дети с `blockOwnerDeletion` |
| Orphan | `orphan` | Дети остаются без владельца — так «переносят» ресурсы из-под оператора |

---

## 9. Finalizers и зависшее удаление

Finalizer — строка в `metadata.finalizers`. Пока она есть, объект **не удаляется**:
API-сервер только ставит `deletionTimestamp`, и контроллер должен убрать за собой
и снять finalizer.

```text
kubectl delete la shortener
   │
   ▼ API-сервер: finalizers не пуст → ставит deletionTimestamp, объект остаётся
оператор видит deletionTimestamp → удаляет ВНЕШНЕЕ (база в облаке, DNS, бакет)
   │
   ▼ patch: убрать свой finalizer из списка
finalizers пуст → объект удалён → GC удаляет детей по ownerReferences
```text
**Нужен** — для внешних ресурсов (база в облаке, DNS-запись, бакет, запись в CMDB) и действий
перед удалением (бэкап). **Не нужен** — для детей-объектов кластера с ownerReference: их уберёт GC.

**Зависший finalizer — классический инцидент:**

| Симптом | Причина | Что делать |
|---------|---------|------------|
| CR висит с `deletionTimestamp` | Оператор не запущен, падает или не может удалить внешнее | Поднять оператор, смотреть его логи — **в первую очередь** |
| Namespace в `Terminating` навсегда | Внутри CR с finalizer, а оператор уже удалён; или недоступен APIService | `kubectl get ns x -o jsonpath='{.status.conditions}'` — там написано, что мешает |
| Удалили CRD раньше оператора | CR с finalizer держат CRD в удалении | Вернуть оператор, дать ему убрать CR, потом CRD |

```bash
# что держит namespace
kubectl get ns team-a -o jsonpath='{range .status.conditions[*]}{.type}: {.message}{"\n"}{end}'
kubectl api-resources --verbs=list --namespaced -o name \
  | xargs -n1 kubectl get -n team-a --ignore-not-found --show-kind -o name

# ⚠️ крайняя мера — снять finalizer руками (внешний ресурс останется сиротой!)
kubectl patch la shortener -n team-a --type=json \
  -p='[{"op":"remove","path":"/metadata/finalizers"}]'
```text
> ⚠️ Снять finalizer руками = признать, что уборки не будет: база в облаке продолжит
> работать и стоить денег. Сначала запиши, что осталось, и убери вручную.

---

## 10. Leader election

Две реплики оператора, которые обе делают reconcile, будут спорить и дублировать работу.
Решение — **leader election**: реплики соревнуются за объект `Lease`
(`coordination.k8s.io/v1`), работает только держатель аренды, остальные ждут.

```bash
kubectl get lease -n platform           # HOLDER — имя пода-лидера, RENEW — когда продлил
```text
В controller-runtime (Go) — `LeaderElection: true` в менеджере. В kopf — **peering**
(свои объекты `KopfPeering`/`ClusterKopfPeering`: работает экземпляр с высшим приоритетом,
тема 03). Одна реплика — тоже вариант: под перезапустится, а level-triggered reconcile ничего не потеряет.

---

## 11. Готовые операторы: уровни зрелости и как пользоваться правильно

**Уровни возможностей** (Operator Framework, проверь, сентябрь 2026):

```text
1 Basic Install      установить приложение, показать статус
2 Seamless Upgrades  обновлять версию приложения и себя
3 Full Lifecycle     бэкапы, восстановление, failover, масштабирование
4 Deep Insights      метрики, алерты, анализ состояния
5 Auto Pilot         сам тюнит, лечит, масштабирует (CloudNativePG расписывает возможности до этого уровня)
```text
Оператор LinkdApp из темы 03 — уровень 1–2. И это нормально: ценность в том, что
**платформенный** API короткий.

Примеры в волте: **CloudNativePG** (PostgreSQL: `Cluster`, бэкапы, PITR —
[../Storage/06_db_backup_replication.md](/storage/06-db-backup-replication) §10) и **cert-manager**
(`Certificate`, `ClusterIssuer` — [../Kubernetes/12_ingress.md](/kubernetes/12-ingress) §5).

**Чек-лист «ставим чужой оператор в прод»:**

| Вопрос | Почему |
|--------|--------|
| Матрица совместимости с версией Kubernetes | Оператор — ещё строка в плане обновления кластера ([../Kubernetes/24_cluster_lifecycle.md](/kubernetes/24-cluster-lifecycle)) |
| ⭐ Как обновляются CRD | Helm **не обновляет** CRD из каталога `crds/` при `upgrade` — у многих чартов отдельный шаг или флаг |
| Область: весь кластер или namespaces | Права ClusterRole на Secret во всех namespace — это серьёзно |
| Что будет, если оператор лежит | Работающие ресурсы живут? (у CNPG — да, база работает; failover — нет) |
| Finalizers и удаление | Как удалить оператор, не повесив namespace |
| HA, ресурсы, метрики | Реплики, leader election, requests/limits, PDB, `/metrics` и алерты |

> 💡 Правило: сначала **поставь и эксплуатируй** чужой оператор, потом пиши свой.
> Чужой научит, как выглядит хороший status, events и поведение при удалении.

---

## 12. ⭐ Проектируем API `LinkdApp`

**Принципы API платформы:**
1. Описывать **намерение**, а не реализацию: `database: true`, а не «StatefulSet postgres:17 с PVC 1Gi».
2. Минимум полей: всё, что можно, — дефолтами. Каждое поле — навсегда.
3. Валидация в CRD — чтобы ошибка была в `kubectl apply`, а не в логах оператора.
4. Status — для людей (message) и машин (conditions, observedGeneration).
5. Намеренно **не** даём: сырой pod template, любые аннотации Gateway — это escape hatch отдельным путём.

```yaml
# linkdapp-crd.yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: linkdapps.platform.example.com        # &lt;plural&gt;.&lt;group&gt;
spec:
  group: platform.example.com
  scope: Namespaced
  names: { kind: LinkdApp, listKind: LinkdAppList, plural: linkdapps, singular: linkdapp,
           shortNames: [la], categories: [platform] }
  versions:
    - name: v1alpha1
      served: true
      storage: true
      subresources:
        status: {}
        scale: { specReplicasPath: .spec.replicas, statusReplicasPath: .status.replicas,
                 labelSelectorPath: .status.selector }
      additionalPrinterColumns:
        - { name: Ready, type: string, jsonPath: '.status.conditions[?(@.type=="Ready")].status' }
        - { name: Replicas, type: integer, jsonPath: .status.readyReplicas }
        - { name: URL, type: string, jsonPath: .status.url }
        - { name: Image, type: string, jsonPath: .spec.image, priority: 1 }
        - { name: Age, type: date, jsonPath: .metadata.creationTimestamp }
      schema:
        openAPIV3Schema:
          type: object
          required: [spec]
          properties:
            spec:
              type: object
              required: [image, host]
              x-kubernetes-validations:
                - rule: "!self.database || self.replicas <= 5"
                  message: "с database: true — не больше 5 реплик (лимит подключений учебной базы)"
                  fieldPath: .replicas
              properties:
                image:
                  type: string
                  maxLength: 255
                  description: "Образ с тегом или digest, например registry.example.com/team-a/linkd:2.0.3"
                  x-kubernetes-validations:
                    - rule: "!self.endsWith(':latest')"
                      message: "тег :latest запрещён — укажи версию или digest"
                    - rule: "self.contains('@sha256:') || self.lastIndexOf(':') > self.lastIndexOf('/')"
                      message: "у образа должен быть тег или digest"
                replicas: { type: integer, minimum: 1, maximum: 10, default: 1 }
                host:
                  type: string
                  maxLength: 253
                  pattern: '^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)+$'
                path:
                  type: string
                  default: /
                  maxLength: 128
                  x-kubernetes-validations:
                    - { rule: "self.startsWith('/')", message: "path должен начинаться с /" }
                database:
                  type: boolean
                  default: false
                  x-kubernetes-validations:
                    - rule: "self || !oldSelf"
                      message: "database нельзя выключить — данные будут потеряны; удалите LinkdApp целиком"
                size: { type: string, enum: [small, medium, large], default: small }
            status:
              type: object
              properties:
                observedGeneration: { type: integer, format: int64 }
                replicas: { type: integer }
                readyReplicas: { type: integer }
                selector: { type: string }
                url: { type: string }
                conditions:
                  type: array
                  maxItems: 8
                  x-kubernetes-list-type: map
                  x-kubernetes-list-map-keys: [type]
                  items:
                    type: object
                    required: [type, status]
                    properties:
                      type: { type: string, maxLength: 64 }
                      status: { type: string, enum: ["True", "False", "Unknown"] }
                      observedGeneration: { type: integer, format: int64 }
                      lastTransitionTime: { type: string, format: date-time }
                      reason: { type: string, maxLength: 128 }
                      message: { type: string, maxLength: 1024 }
```text
```yaml
# shortener.yaml — всё, что пишет команда
apiVersion: platform.example.com/v1alpha1
kind: LinkdApp
metadata: { name: shortener, namespace: team-a }
spec:
  image: registry.example.com/team-a/linkd:2.0.3
  replicas: 2
  host: links.team-a.example.com
  database: true            # path и size — по умолчанию
```text
| Поле spec | Во что превращает оператор (тема 03) |
|-----------|--------------------------------------|
| `image`, `replicas`, `size` | Deployment: образ, реплики, requests/limits по пресету, probes на `/healthz` и `/readyz` linkd 2.0 |
| `host`, `path` | HTTPRoute к Gateway `web` в `infra` (Envoy Gateway, [../Kubernetes/12_ingress.md](/kubernetes/12-ingress) §7) |
| — | Service ClusterIP на порт приложения |
| `database: true` | PostgreSQL для linkd: в учебной версии — Secret + ссылка на базу; в лабах — LinkdDatabase через Crossplane (namespaced XR, тема 07) |

---

## 🧪 Мини-лаба: CRD с валидацией в kind

```bash
kind create cluster --name platform --image kindest/node:v1.36.4   # если ещё нет
kubectl apply -f linkdapp-crd.yaml
kubectl wait --for=condition=Established crd/linkdapps.platform.example.com
kubectl explain la.spec                    # описание из схемы
kubectl create namespace team-a
kubectl apply -f shortener.yaml
kubectl get la -n team-a                   # READY и REPLICAS пустые — оператора нет
kubectl get la shortener -n team-a -o yaml | grep -A4 'spec:'   # path: / и size: small — дефолты
```text
**Шаг 2. Сломай валидацию** (`kubectl apply --dry-run=server`): `image: …:latest`;
`image: localhost:5001/linkd` (почему `:5001` — не тег?); `replicas: 0` и `size: huge`;
`database: true` + `replicas: 7` (подсвечено `spec.replicas`); `database: false` у уже
созданного объекта (правило перехода); поле `repliсas: 3` с кириллической «с» — сначала
обычный `apply` (отказ `unknown field`), потом `--validate=false` и поиск в `-o yaml` (поля нет: pruning).

**Шаг 3. Status руками — как это будет делать оператор:**
```bash
kubectl patch la shortener -n team-a --subresource=status --type=merge -p \
 '{"status":{"observedGeneration":1,"readyReplicas":2,"url":"http://links.team-a.example.com/",
   "conditions":[{"type":"Ready","status":"True","reason":"Manual","message":"проставлено руками",
   "lastTransitionTime":"2026-09-28T10:00:00Z"}]&#125;&#125;'
kubectl get la -n team-a                   # READY True, REPLICAS 2, URL
kubectl wait la/shortener -n team-a --for=condition=Ready --timeout=5s
kubectl patch la shortener -n team-a --type=merge -p '{"spec":{"replicas":3&#125;&#125;'
kubectl get la shortener -n team-a -o jsonpath='{.metadata.generation} {.status.observedGeneration}{"\n"}'  # generation больше observedGeneration
```text
**Шаг 4. Зависший finalizer:** добавь `metadata.finalizers: ["platform.example.com/cleanup"]`
(`kubectl patch --type=merge`), удали LinkdApp и namespace с `--wait=false`, найди
`deletionTimestamp` у CR и причину в `status.conditions` namespace (команды — в §9),
сними finalizer и убедись, что namespace исчез.

**Проверь себя:** почему `kubectl patch ... -p '{"status":...}'` без `--subresource=status`
ничего не меняет? Что увидит CI, который ждёт `Ready`, если оператор ещё не обработал
новую generation? Зачем finalizer оператору LinkdApp, если все дети — объекты кластера?

---

## 13. Грабли

| Грабля | Что происходит | Как избежать |
|--------|----------------|--------------|
| `x-kubernetes-preserve-unknown-fields: true` на весь spec | Опечатки молча принимаются, валидации нет | Полная схема; «произвольное» — только в отдельном поле |
| Строки и списки без `maxLength`/`maxItems` | CEL-правило отклоняют как слишком дорогое | Ограничивай размеры всегда |
| Нет status subresource | Команда может сама записать себе Ready; generation растёт от статуса | `subresources.status: {}` с первого дня |
| Нет `observedGeneration` | CI видит старый `Ready=True` и считает выкатку успешной | Писать его в status и в каждое условие |
| Reconcile «по событиям» (edge) | Пропущенное событие — потерянное изменение | Level-triggered reconcile + периодическая сверка |
| Cross-namespace ownerReference | Дети не удаляются или удаляются неожиданно | Дети в namespace родителя; иначе — метки и finalizer |
| Удалить оператор раньше его CR | Namespace висят в Terminating | Сначала CR, потом оператор, потом CRD |
| Helm `upgrade` и CRD в `crds/` | CRD остались старыми, новые поля вырезаются | Обновлять CRD отдельным шагом |

---

## 💼 Как это в DevOps

- CRD — главный способ дать самообслуживание «в стиле Kubernetes»: его понимают GitOps,
  RBAC, политики и портал. Короткий CR вместо чарта на 300 строк — golden path из темы 01.
- Чаще, чем писать свои операторы, DevOps **эксплуатирует чужие**: CloudNativePG,
  cert-manager, Prometheus Operator, Argo Rollouts, Crossplane. Понимание reconcile,
  conditions и finalizers — то, что отличает «перезапустил под» от «понял, почему завис».
- «Namespace висит в Terminating» и «CR не удаляется» — частые вопросы на собесах и в
  реальных инцидентах. Правильный ответ начинается с «посмотреть, кто держит», а не «снять finalizer».

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Дефолт и enum | `default: 1`, `enum: [small, medium, large]` |
| Поле нельзя менять | `x-kubernetes-validations: [{rule: "self == oldSelf"}]` на поле |
| Правило между полями | Правило на родителе (`spec`), `fieldPath` для подсветки |
| Проверить без записи | `kubectl apply --dry-run=server -f cr.yaml` |
| Отделить status | `subresources.status: {}`; писать `--subresource=status` |
| Понять, обработан ли spec | `metadata.generation == status.observedGeneration` |
| Ждать готовности | `kubectl wait la/x --for=condition=Ready` |
| Колонки в `kubectl get` | `additionalPrinterColumns` (+ `Age` явно) |
| Сменить схему несовместимо | Новая версия + conversion webhook + миграция хранения |
| Что держит namespace | `kubectl get ns x -o jsonpath='{.status.conditions}'` |
| Кто лидер | `kubectl get lease -n &lt;ns&gt;` |

---

## 🧠 Что запомнить

1. ⭐ CRD — публичный API платформы: версии, валидация и дефолты с первого дня.
2. Схема структурная, неизвестные поля вырезаются (pruning); ограничивай размеры строк и списков.
3. ⭐ CEL-правила в CRD (GA 1.29): `self`/`oldSelf`, неизменяемость, переходы, правила между полями;
   `oldSelf` — только на update; ratcheting (GA 1.33) щадит старые объекты.
4. Правила корректности своего API — в CRD; правила организации — в политиках (тема 04).
5. ⭐ Status subresource: spec и status пишут разные субъекты; generation растёт только от spec;
   `observedGeneration` показывает, что статус актуален.
6. Conditions: `type/status/reason/message/observedGeneration/lastTransitionTime`; status — строка.
7. Версии: одна storage-версия; несовместимые изменения — новая версия и конверсия; старую
   убирают только после миграции хранения (`StorageVersionMigration` — GA в 1.37).
8. ⭐ Контроллер level-triggered: сводит реальное к желаемому, reconcile идемпотентен,
   состояние — в API, а не в памяти.
9. Informer = LIST + WATCH + кэш; очередь дедуплицирует ключи и повторяет с backoff.
10. Owner references: GC удаляет детей; только тот же namespace; `controller: true` — один.
11. ⭐ Finalizer — для внешних ресурсов; зависший — сначала чинить оператор, снимать руками —
    крайняя мера с уборкой вручную. Leader election — Lease (Go) или peering (kopf).
12. Чужой оператор: матрица версий, обновление CRD отдельно от Helm, область прав, поведение при падении.
13. `LinkdApp`: image, replicas, host, path, database, size → Deployment + Service + HTTPRoute (+ база).

➡️ Дальше: [03_writing_operator.md](/platform/03-writing-operator) · Задачи: 02_crd_operators_tasks.md


---

### Блок A. Теория


**A1.** ⭐ Что такое CRD и что такое оператор? Чем CR отличается от ConfigMap с тем же YAML?

<details><summary>Ответ</summary>

CRD добавляет в API новый тип объектов; оператор — контроллер, который обслуживает
этот тип и кодирует знания администратора. CR — полноценный объект API: своя схема и
валидация, RBAC на тип, watch, status, printer columns; ConfigMap — просто данные без типа
и валидации, контроллер не может отличить «свой» объект.

</details>

**A2.** Что CRD даёт «бесплатно» по сравнению со своим REST-сервисом для деплоя?

<details><summary>Ответ</summary>

RBAC на тип и namespace, kubectl (`explain`, `get -w`), watch и оптимистичная
блокировка, GitOps без доработок, аудит, admission-политики и квоты.

</details>

**A3.** Что такое структурная схема? Что происходит с полями, которых нет в схеме?

<details><summary>Ответ</summary>

Схема, где у каждого поля указан тип и нет неоднозначностей. Поля, которых нет
в схеме, API-сервер вырезает при записи (pruning), если не стоит
`x-kubernetes-preserve-unknown-fields`.

</details>

**A4.** Когда `default` у вложенного поля не сработает?

<details><summary>Ответ</summary>

Когда не передан родительский объект: дефолт `spec.db.size` не проставится, если
нет `spec.db` (решается `default: {}` у самого `db`).

</details>

**A5.** Зачем в схеме `maxLength` и `maxItems`, если размер объекта и так ограничен?

<details><summary>Ответ</summary>

Чтобы API-сервер мог оценить стоимость CEL-правил заранее: без ограничений правило
с перебором списка или строки считается потенциально слишком дорогим и отклоняется. Плюс
защита от мусора и огромных объектов.

</details>

**A6.** ⭐ Что такое `x-kubernetes-validations`? С какой версии Kubernetes это GA? Что такое
`self` и `oldSelf`?

<details><summary>Ответ</summary>

Расширение схемы CRD с CEL-правилами валидации; GA с 1.29. `self` — значение того
уровня схемы, где висит правило; `oldSelf` — прежнее значение при update.

</details>

**A7.** Как запретить менять поле после создания? Как разрешить переход только `false → true`?

<details><summary>Ответ</summary>

Неизменяемость — `rule: "self == oldSelf"` на поле. Переход только `false → true` —
`rule: "self || !oldSelf"`: при старом `true` новое обязано быть `true`.

</details>

**A8.** Когда вычисляются правила с `oldSelf`? Что меняет `optionalOldSelf: true`?

<details><summary>Ответ</summary>

Только при update и только если старое значение существует. `optionalOldSelf: true`
заставляет вычислять правило и при create: `oldSelf` становится optional-значением,
проверяют через `oldSelf.hasValue()`.

</details>

**A9.** Что такое validation ratcheting и зачем он?

<details><summary>Ответ</summary>

Если схему ужесточили, старые невалидные объекты можно обновлять, пока не трогаешь
невалидные части (GA с 1.33). Иначе после ужесточения нельзя было бы даже снять finalizer
или поменять метку.

</details>

**A10.** Какие правила лучше держать в CRD, а какие — в политиках (VAP/Kyverno)?

<details><summary>Ответ</summary>

В CRD — корректность самого API: типы, диапазоны, связи полей, неизменяемость.
В политиках — правила организации, которые меняются и касаются разных типов: домены команд,
разрешённые реестры, обязательные метки.

</details>

**A11.** ⭐ Что даёт status subresource? Как ведёт себя `metadata.generation` с ним?

<details><summary>Ответ</summary>

Отдельный путь `/status`: основной путь игнорирует status, `/status` игнорирует
остальное, RBAC раздельный. `metadata.generation` увеличивается только при изменении spec
(не status и не metadata).

</details>

**A12.** ⭐ Какие поля у стандартного condition? Почему `status` — строка?

<details><summary>Ответ</summary>

`type`, `status`, `reason`, `message`, `observedGeneration`, `lastTransitionTime`.
`status` — строка `True/False/Unknown`: трёхзначная логика, `Unknown` — «ещё не знаю».

</details>

**A13.** Зачем `observedGeneration` и как по нему понять, что статус актуален?

<details><summary>Ответ</summary>

Показывает, по какой generation spec посчитан статус. Если `observedGeneration`
совпадает с `metadata.generation`, статус актуален; если меньше — оператор ещё не обработал
последний spec.

</details>

**A14.** Для чего `additionalPrinterColumns`, `shortNames`, `categories`, `selectableFields`?

<details><summary>Ответ</summary>

Колонки `kubectl get` из jsonPath; короткое имя (`kubectl get la`); группа для
`kubectl get platform`; поля для `--field-selector` (GA 1.32).

</details>

**A15.** Что нужно для того, чтобы на CR работал `kubectl scale` и HPA?

<details><summary>Ответ</summary>

Scale subresource: `specReplicasPath`, `statusReplicasPath` и `labelSelectorPath`
(строка селектора в status — её использует HPA).

</details>

**A16.** Что такое served и storage версии? Сколько может быть storage-версий?

<details><summary>Ответ</summary>

Served — API отвечает на версии; storage — в ней объект хранится в etcd. Storage-версия
ровно одна.

</details>

**A17.** Какие изменения схемы можно делать в той же версии, а какие требуют новой?

<details><summary>Ответ</summary>

В той же версии — новые необязательные поля (с дефолтом). Новая версия с конверсией —
новые обязательные поля, переименование, смена типа, удаление полей.

</details>

**A18.** Что такое `status.storedVersions` у CRD и почему старую версию нельзя просто удалить?
Какой статус у `StorageVersionMigration` в 1.36 и 1.37?

<details><summary>Ответ</summary>

Список версий, в которых объекты ещё лежат в etcd. Пока в нём старая версия,
её нельзя убрать из CRD: объекты надо перезаписать в новой storage-версии и обновить
`storedVersions`. `StorageVersionMigration` — beta и выключен по умолчанию в 1.35–1.36,
GA и включён по умолчанию в 1.37.

</details>

**A19.** Чем опасен conversion webhook?

<details><summary>Ответ</summary>

Он вызывается при каждом чтении и записи в неstorage-версии: упал вебхук —
объекты не читаются, ломаются kubectl, ArgoCD, сам оператор.

</details>

**A20.** ⭐ Объясни reconcile loop. Чем level-triggered отличается от edge-triggered?

<details><summary>Ответ</summary>

Контроллер наблюдает объекты, сравнивает желаемое (spec) с реальным и делает шаг
к желаемому, затем пишет статус; повторяет на каждое событие и периодически. Level-triggered —
реагирует на текущее состояние, поэтому пропущенное событие не страшно; edge-triggered
реагирует на факт изменения, и пропуск события теряет действие.

</details>

**A21.** Что такое informer, кэш и рабочая очередь? Зачем дедупликация?

<details><summary>Ответ</summary>

Informer делает LIST, затем WATCH, держит локальный кэш объектов и шлёт события.
Обработчик кладёт в очередь ключ объекта (`ns/name`); очередь схлопывает повторы, ограничивает
частоту и повторяет с backoff. Дедупликация: 10 событий по объекту — один reconcile.

</details>

**A22.** ⭐ Что такое идемпотентность reconcile и почему она обязательна?

<details><summary>Ответ</summary>

Повторный запуск с тем же входом даёт тот же результат и не падает, если всё уже
создано. Обязательна, потому что reconcile вызывают много раз: события, resync, повторы
после ошибок, рестарты.

</details>

**A23.** Что будет при записи объекта с устаревшим `resourceVersion`?

<details><summary>Ответ</summary>

409 Conflict: кто-то изменил объект раньше. Нужно перечитать и повторить,
а не затирать чужие изменения.

</details>

**A24.** Как работают owner references? Что значат `controller: true` и `blockOwnerDeletion`?

<details><summary>Ответ</summary>

Ребёнок хранит ссылку на владельца (apiVersion, kind, name, uid). GC удаляет детей
после удаления владельца. `controller: true` — главный владелец (только один), по нему
контроллер находит родителя. `blockOwnerDeletion: true` — при foreground-удалении владелец
ждёт удаления этого ребёнка.

</details>

**A25.** Какие ограничения на namespace у owner references?

<details><summary>Ответ</summary>

Namespaced-ребёнок — владелец в том же namespace или cluster-scoped; cluster-scoped
ребёнок — только cluster-scoped владелец; cross-namespace ссылки недопустимы.

</details>

**A26.** Чем отличаются политики удаления Background, Foreground и Orphan?

<details><summary>Ответ</summary>

Background — владелец удаляется сразу, дети следом; Foreground — владелец висит
с `deletionTimestamp`, пока не удалены блокирующие дети; Orphan — дети остаются.

</details>

**A27.** ⭐ Что такое finalizer, как проходит удаление объекта с ним? Когда finalizer нужен,
а когда нет?

<details><summary>Ответ</summary>

Строка в `metadata.finalizers`. При удалении API-сервер ставит `deletionTimestamp`,
объект остаётся; контроллер делает уборку и снимает finalizer; когда список пуст, объект
удаляется, затем GC убирает детей. Нужен для внешних ресурсов и действий перед удалением;
не нужен для детей-объектов кластера с ownerReference.

</details>

**A28.** Зачем leader election и как он устроен? Что вместо него в kopf?

<details><summary>Ответ</summary>

Чтобы работала одна реплика и они не спорили. Реплики соревнуются за Lease
в `coordination.k8s.io`, лидер продлевает аренду. В kopf — peering через объекты
`KopfPeering`/`ClusterKopfPeering` с приоритетами.

</details>

**A29.** Назови уровни возможностей операторов (Operator Framework).

<details><summary>Ответ</summary>

Basic Install, Seamless Upgrades, Full Lifecycle, Deep Insights, Auto Pilot.

</details>

**A30.** Что проверить, прежде чем ставить чужой оператор в прод?

<details><summary>Ответ</summary>

Совместимость с версией Kubernetes, как обновляются CRD (Helm их не обновляет
из `crds/`), область прав (ClusterRole на Secret), поведение при падении оператора,
finalizers и порядок удаления, HA и ресурсы, метрики и алерты.

</details>

---

### Блок B. «Что произойдёт»


```text:no-line-numbers
# B1 — CRD без status subresource
```text
```text:no-line-numbers
subresources: {}
```text
```text:no-line-numbers
# команда делает: kubectl apply -f la.yaml, где в файле есть status.conditions Ready=True
```text
Вопрос: что будет со статусом? А если subresource включён?

```text:no-line-numbers
# B2
```text
```text:no-line-numbers
spec:
```text
```text:no-line-numbers
  properties:
```text
```text:no-line-numbers
    replicas: { type: integer, default: 1 }
```text
```text:no-line-numbers
# команда прислала: spec: { replcas: 3 }
```text
Вопрос: сколько реплик будет у объекта и что увидит команда?

```text:no-line-numbers
# B3 — правило на поле storageClass
```text
```text:no-line-numbers
x-kubernetes-validations: [{ rule: "self == oldSelf" }]
```text
```text:no-line-numbers
# объект создаётся впервые с storageClass: fast
```text
Вопрос: пройдёт ли создание? Что будет при смене на `slow`?

```text:no-line-numbers
# B4 — правило на spec
```text
```text:no-line-numbers
x-kubernetes-validations: [{ rule: "self.tags.all(t, t.size() < 64)" }]
```text
```text:no-line-numbers
properties:
```text
```text:no-line-numbers
  tags: { type: array, items: { type: string } }
```text
Вопрос: что ответит API-сервер при `kubectl apply` этого CRD?

```text:no-line-numbers
# B5
```text
```text:no-line-numbers
metadata.generation: 7
```text
```text:no-line-numbers
status.observedGeneration: 5
```text
```text:no-line-numbers
status.conditions: [{type: Ready, status: "True"}]
```text
Вопрос: можно ли считать, что последняя версия spec выкачена?

```text:no-line-numbers
# B6 — ребёнок в другом namespace
```text
```text:no-line-numbers
# Deployment в ns shared, ownerReference → LinkdApp в ns team-a
```text
Вопрос: что будет при удалении LinkdApp?

```text:no-line-numbers
# B7
```text
```text:no-line-numbers
kubectl delete la shortener --cascade=orphan
```text
Вопрос: что станет с Deployment, Service и HTTPRoute? Что сделает оператор, если LinkdApp
создать заново с тем же именем?

```text:no-line-numbers
# B8 — оператор удалили helm uninstall; в кластере 12 LinkdApp с finalizer
```text
```text:no-line-numbers
kubectl delete ns team-a
```text
Вопрос: что увидишь и почему?

```text:no-line-numbers
# B9 — CRD
```text
```text:no-line-numbers
versions:
```text
```text:no-line-numbers
  - { name: v1alpha1, served: true, storage: false }
```text
```text:no-line-numbers
  - { name: v1beta1,  served: true, storage: true }
```text
```text:no-line-numbers
# status.storedVersions: ["v1alpha1", "v1beta1"]
```text
Вопрос: можно ли сейчас удалить `v1alpha1` из CRD? Что сделать сначала?

```text:no-line-numbers
# B10 — две реплики оператора без leader election
```text
Вопрос: что будет происходить с Deployment и status LinkdApp?

---

### Блок C. Практика


### C1. 🔑 CRD LinkdApp
Пройди мини-лабу: примени CRD из §12, создай `shortener`, проверь дефолты (`path`, `size`),
`kubectl explain la.spec`, колонки `kubectl get la` и `-o wide`.

### C2. 🔑 Сломай валидацию
Добейся по очереди каждой ошибки: `:latest`, образ без тега (`localhost:5001/linkd`),
`replicas: 0`, `size: huge`, `database: true` + `replicas: 7`, выключение `database`.
Запиши точный текст каждой ошибки. Какая из них пришла от схемы, какая — от CEL?

### C3. Pruning
Добавь в spec поле с опечаткой и примени обычным `kubectl apply`, затем с `--validate=false`.
Что ответил API-сервер в первом случае и куда делось поле во втором? Сравни с тем, что будет,
если в CRD на spec поставить `x-kubernetes-preserve-unknown-fields: true`.

### C4. 🔑 Status и generation
Проставь status руками через `--subresource=status`, убедись, что `kubectl wait
--for=condition=Ready` проходит. Измени spec и покажи, что `generation` ушёл вперёд
`observedGeneration`. Попробуй записать status без `--subresource` — что вышло?

### C5. Новое CEL-правило
Добавь в CRD поле `spec.env` (map строк, `maxProperties: 20`) и правило: ключи — только
`[A-Z_][A-Z0-9_]*`, и нельзя задавать `DATABASE_URL` (его ставит оператор). Проверь
`--dry-run=server`. Подсказка: для map — `self.all(k, …)` перебирает ключи.

### C6. Правило с messageExpression
Перепиши правило «не больше 5 реплик с базой» так, чтобы сообщение содержало фактическое
число реплик. Проверь.

### C7. Ratcheting
Создай LinkdApp с `replicas: 8`. Ужесточи схему до `maximum: 5`. Попробуй: (а) поменять
`image`, не трогая `replicas`; (б) поменять `replicas` на 7. Объясни результат.

### C8. 🔑 Owner references руками
Создай Deployment с ownerReference на свой LinkdApp (UID возьми из `kubectl get la -o
jsonpath='{.metadata.uid}'`). Удали LinkdApp и посмотри, что стало с Deployment. Повтори
с `--cascade=orphan` и `--cascade=foreground` (посмотри `deletionTimestamp` у родителя).

### C9. Зависший namespace
Воспроизведи шаг 4 мини-лабы. Запиши, какие условия (`type`) и сообщения показывает
namespace. Найди все объекты, которые его держат, одной командой.

### C10. Версия v1beta1 (со звёздочкой)
Добавь в CRD версию `v1beta1` с той же схемой (`conversion.strategy: None`), сделай её
storage. Посмотри `status.storedVersions`. Перезапиши объекты, чтобы в etcd остались только
`v1beta1`, и убери `v1alpha1` из `storedVersions`. Какая команда меняет `storedVersions`?

### C11. Аудит чужого оператора
Поставь cert-manager (или CloudNativePG) и ответь по чек-листу §11: как обновляются CRD,
какие ClusterRole создаются, какие finalizers ставит оператор, есть ли leader election
(`kubectl get lease -A`), что будет с ресурсами, если оператор остановить.

---

### Блок D. Инциденты


**D1.** Namespace `team-b` три часа в `Terminating`. Порядок диагностики и исправления?

<details><summary>Ответ</summary>

`kubectl get ns team-b -o jsonpath='{.status.conditions}'` — что мешает; найти
оставшиеся объекты (`api-resources --namespaced` + `get`); посмотреть их finalizers; проверить,
жив ли оператор, который их снимает, и не недоступен ли какой-то APIService
(`kubectl get apiservice | grep False`). Починить оператор или APIService; снимать finalizer
руками — только после уборки внешнего вручную.

</details>

**D2.** LinkdApp не удаляется, висит с `deletionTimestamp`. Логи оператора: `permission denied`
при удалении базы в облаке. Что делать и что **не** делать?

<details><summary>Ответ</summary>

Дать оператору права на удаление (IAM/сервисный аккаунт) и дождаться, пока он
сам уберёт базу и снимет finalizer. Не снимать finalizer руками, пока база не удалена
(или сознательно не сохранена) — иначе база останется сиротой и будет стоить денег.

</details>

**D3.** После обновления CRD новое поле `spec.size` «пропадает» из объектов, хотя в git оно есть.
Обновление шло через `helm upgrade`. Причина?

<details><summary>Ответ</summary>

Helm не обновляет CRD из каталога `crds/` при `upgrade`: в кластере старая схема
без поля `size`, и оно вырезается при записи. Обновить CRD отдельным шагом (`kubectl apply
--server-side` или отдельный чарт с CRD).

</details>

**D4.** CI считает выкатку успешной по `Ready=True`, но на проде старая версия образа. Что
не так с проверкой?

<details><summary>Ответ</summary>

Проверяется только `Ready`, без сравнения `observedGeneration` и `generation`: оператор
ещё не обработал новый spec, а старый `Ready=True` остался. Ждать совпадения generation или
условие с `observedGeneration`, равным текущей generation.

</details>

**D5.** Оператор создаёт по три Deployment на каждый LinkdApp (`shortener`, `shortener-x7k`…).
Гипотезы?

<details><summary>Ответ</summary>

Неидемпотентное создание: `generateName` вместо фиксированного имени, или reconcile
создаёт без проверки существования; события приходят несколько раз — каждый раз новый объект.
Имя ребёнка должно быть детерминированным (`&lt;имя LinkdApp&gt;`), создание — create-or-update.

</details>

**D6.** После рестарта оператора часть изменений spec «не применилась», пока их не поменяли
ещё раз. Что сломано в дизайне?

<details><summary>Ответ</summary>

Логика edge-triggered: изменения обрабатывались только в on-update по diff, а пока
оператор лежал, событие потерялось. Нужен level-triggered reconcile: при старте (resume)
и по таймеру сводить всё к текущему spec.

</details>

**D7.** После выкатки conversion webhook ArgoCD показывает `Unknown` для всех LinkdApp,
`kubectl get la` иногда падает с ошибкой. Где смотреть?

<details><summary>Ответ</summary>

Логи и доступность conversion webhook (Service, Endpoints, сертификат, `caBundle`),
`kubectl get --raw /apis/platform.example.com/v1alpha1/linkdapps` для проверки. Пока не
починили — вернуть `strategy: None`, если схемы совместимы.

</details>

**D8.** Команда пожаловалась: «удалили LinkdApp, а через минуту Deployment снова появился».
Что может происходить?

<details><summary>Ответ</summary>

Deployment не принадлежит LinkdApp (нет ownerReference), и его создаёт кто-то ещё:
ArgoCD с selfHeal из git, другой контроллер или вторая копия оператора со старым кэшем.
Проверить `metadata.ownerReferences`, `managedFields` и метки `app.kubernetes.io/managed-by`.

</details>

---

### Блок E. Вопросы с собеседования


**1.** ⭐ Что такое оператор? Приведите пример, когда он нужен, а когда хватает Helm.

<details><summary>Ответ</summary>

Контроллер для своего типа, кодирующий операционные знания: failover БД, бэкапы,
   обновления. Helm хватает, когда нужно только разложить манифесты и нет постоянного ухода.

</details>

**2.** Что такое reconcile loop и почему он level-triggered?

<details><summary>Ответ</summary>

Цикл «наблюдать → сравнить → привести → записать статус»; level-triggered, чтобы
   пропущенные события и рестарты не теряли изменения.

</details>

**3.** ⭐ Как вы валидируете CR? Чем CEL в CRD лучше вебхука и когда его мало?

<details><summary>Ответ</summary>

Схема + CEL в CRD: быстро, без внешнего компонента и точек отказа; мало, когда нужны
   внешние данные или сложная логика — тогда webhook.

</details>

**4.** Зачем status subresource и observedGeneration?

<details><summary>Ответ</summary>

Разделить права и субъектов записи и понимать, актуален ли статус для текущего spec.

</details>

**5.** ⭐ Что такое finalizer? Namespace висит в Terminating — ваши действия?

<details><summary>Ответ</summary>

Защита уборки внешних ресурсов перед удалением. Смотреть условия namespace, кто держит,
   живы ли оператор и APIService; снимать руками — последнее средство.

</details>

**6.** Как работает garbage collection в Kubernetes?

<details><summary>Ответ</summary>

ownerReferences + GC-контроллер, политики Background/Foreground/Orphan, finalizers.

</details>

**7.** Как версионировать CRD и менять схему без простоя?

<details><summary>Ответ</summary>

Добавлять необязательные поля; несовместимое — новая версия, conversion webhook,
   миграция хранения, deprecation-предупреждения.

</details>

**8.** Как оператор переживает рестарт и две реплики?

<details><summary>Ответ</summary>

Состояние — в API и status, reconcile идемпотентный и level-triggered; несколько реплик —
   leader election.

</details>

**9.** Каким операторам вы доверили бы прод и что проверяете перед установкой?

<details><summary>Ответ</summary>

Зрелые проекты (CloudNativePG, cert-manager, Prometheus Operator); проверяю матрицу
   версий, обновление CRD, права, поведение при падении, finalizers, HA, метрики.

</details>

**10.** Спроектируйте CRD для «сервиса на платформе»: какие поля оставите командам и почему.

<details><summary>Ответ</summary>

Намерение, а не реализация: image, replicas, host, path, database, size; дефолты
    и валидация; status с conditions и URL; сырой pod template не отдаю.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Пишу CRD со структурной схемой, дефолтами, enum и ограничениями размера
- [ ] ⭐ Пишу CEL-правила: неизменяемость, переход в одну сторону, правило между полями
- [ ] Объясняю status subresource, generation и observedGeneration
- [ ] Знаю поля condition и как CI должен ждать готовности
- [ ] Настраиваю printer columns и scale subresource
- [ ] Объясняю версии CRD, конверсию и storedVersions
- [ ] ⭐ Объясняю reconcile loop, level-triggered, informers и идемпотентность
- [ ] Знаю правила owner references и политики удаления
- [ ] ⭐ Разбираю зависший finalizer и namespace в Terminating
- [ ] Оцениваю чужой оператор по чек-листу
