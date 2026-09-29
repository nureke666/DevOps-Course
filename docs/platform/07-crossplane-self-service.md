---
title: "07. Самообслуживание: Crossplane"
description: "Блок → Platform Engineering → инфраструктура по запросу. Terraform, стейт и модули —"
---

# 07. Самообслуживание: Crossplane

> Блок → Platform Engineering → **инфраструктура по запросу**. Terraform, стейт и модули —
> [../Left/06_Terraform/00_INDEX.md](/terraform/); CRD и reconcile —
> [02_crd_operators.md](/platform/02-crd-operators); облака — [../Left/04_Cloud/08_aws_deep.md](/cloud/08-aws-deep),
> [../Left/04_Cloud/09_yandex_cloud.md](/cloud/09-yandex-cloud).
> Вопросы собеса: *«Как команда получает базу без тикета?»*, *«Crossplane или Terraform?»*,
> *«Что изменилось в Crossplane v2?»*
> **После темы ты умеешь:** объяснить модель Crossplane v2 (providers, managed resources, XRD,
> Composition, функции, namespaced XR вместо Claim), описать API `LinkdDatabase` с ограничениями,
> поднять его в kind на CloudNativePG без облака, написать ту же композицию для AWS RDS и Yandex
> Managed PostgreSQL, доставлять всё через ArgoCD и честно сравнить Crossplane с Terraform.
> Версии — «проверь, сентябрь 2026».

---

## 🗺️ Карта темы

```text
 команда (ns team-a)                          платформа (GitOps-репо платформы)
 ┌──────────────────────────┐                 ┌──────────────────────────────────────┐
 │ LinkdDatabase shortener  │  ── XRD ──────► │ XRD: схема API, enum, дефолты, лимиты │
 │   size: small            │                 │ Composition (Pipeline):              │
 │   storageGB: 5           │  ◄── status ─── │   функция patch-and-transform/python │
 └────────────┬─────────────┘                 └──────────────────────────────────────┘
              │ Crossplane: функции → желаемые ресурсы → применяет и сверяет
     ┌────────┴──────────────────────────┬────────────────────────────────────┐
  kind: CloudNativePG Cluster      AWS: RDS Instance (MR)          Yandex: PostgresqlCluster (MR)
        + Secret shortener-db            → provider → AWS API              → provider → YC API (kz1)
              │
 LinkdApp shortener ──► Deployment linkd: LINKD_DATABASE_URL ← Secret shortener-db / url
```text
---

## 1. Зачем: «база по запросу»

| Как получают базу | Сколько ждать | Кто отвечает за стандарты |
|-------------------|---------------|---------------------------|
| Тикет DBA/девопсу | Дни–неделя | Человек в очереди |
| MR в инфраструктурный Terraform-репо | Часы–дни: ревью, `plan`, `apply` из CI | Ревьюер модуля |
| ⭐ Объект в API кластера (`LinkdDatabase`) | Минуты | Код композиции: размеры, бэкап, шифрование, теги |

Смысл Crossplane для платформы — **не «Terraform на YAML»**, а **свой API**: команда пишет пять
строк, а платформа решает, что за ними стоит (CNPG в dev, RDS в AWS, Managed PostgreSQL в Yandex),
с какими настройками безопасности и в каких пределах.

---

## 2. Модель Crossplane v2

| Понятие | Что это | Кто пишет |
|---------|---------|-----------|
| **Provider** | Пакет с контроллерами для внешнего API (AWS, Yandex, Helm, Kubernetes) | Ставит платформа |
| **Managed resource (MR)** | Один внешний объект как ресурс Kubernetes: `Instance` RDS, `Bucket` | Композиция (редко — руками) |
| **ProviderConfig / ClusterProviderConfig** | Креды и настройки провайдера (в namespace / на кластер) | Платформа |
| ⭐ **XRD** (CompositeResourceDefinition) | Схема нового API: группа, kind, OpenAPI, scope | Платформа |
| ⭐ **XR** (composite resource) | Экземпляр этого API — `LinkdDatabase shortener` | Команда |
| ⭐ **Composition** | Как из XR получить ресурсы: pipeline функций | Платформа |
| **Composition function** | Шаг pipeline: YAML-патчи, Go-шаблоны, Python, KCL, CEL | Платформа (или готовые) |
| Claim | v1: namespaced «заявка» на cluster-scoped XR | **В v2 не нужен** — XR сам namespaced |
| MRD, ManagedResourceActivationPolicy | Какие MR провайдера реально включать (вместо сотен CRD) | Платформа |
| Operations (alpha) | Разовые, по расписанию или по событию pipeline функций — «Job для Crossplane» | Платформа |

```text
 XR LinkdDatabase ──► Composition (mode: Pipeline)
                        step 1: function-patch-and-transform → Cluster CNPG
                        step 2: function-python              → Secret, ...
                     ◄── желаемое состояние (desired) ──┘
 Crossplane применяет desired, следит за observed, пишет status и условия Synced/Ready в XR
```text
| Факт (проверь, сентябрь 2026) | |
|-------------------------------|---|
| Crossplane | **v2.4.2** (22.09.2026); v2.0 — 14.08.2025; CNCF Graduated с 28.10.2025 |
| Поддержка v1 | v1.20 — последняя 1.x, EOL с выходом v2.5 (ноябрь 2026); обновляться только с 1.20 и по одной минорной |
| Функции | function-patch-and-transform v0.11.0, function-go-templating v0.13.0, function-python v0.6.0, function-kcl v0.12.3 |
| Провайдеры | provider-kubernetes v1.3.1, provider-helm v1.4.0, provider-upjet-aws v2.8.1, crossplane-provider-yc 0.15.0 (namespaced MR с 0.14), provider-terraform v1.2.0 |

---

## 3. ⭐ Что изменилось в v2 (чтобы читать старые статьи)

| Было в v1 | Стало в v2 |
|-----------|-----------|
| XR — cluster-scoped, команды создают **Claim** в namespace | XR **namespaced** по умолчанию (`scope: Namespaced`), Claim не нужен и не поддерживается новыми XR |
| MR — cluster-scoped | MR **namespaced**, группы с `.m.`: `rds.aws.m.upbound.io`, `mdb.yandex-cloud.m.jet.crossplane.io` |
| Компоновать можно только MR/XR; Deployment — через `Object` из provider-kubernetes | ⭐ Композиция создаёт **любой** ресурс Kubernetes (Deployment, CNPG Cluster) — нужен RBAC для Crossplane |
| Нативный patch & transform (`mode: Resources`) | Только **`mode: Pipeline`** с функциями (`crossplane beta convert pipeline-composition` из CLI 1.20) |
| Connection details у XR | Убраны: Secret для потребителя компонуешь **сам** |
| `spec.compositionRef` у XR | Вся «механика» — под `spec.crossplane` (`compositionRef`, `resourceRefs`) |
| XRD `apiextensions.crossplane.io/v1` | `v2` со `scope`; v1 → режим `LegacyCluster` (Claims работают) |
| ControllerConfig, внешние secret stores, реестр по умолчанию | Убраны: DeploymentRuntimeConfig, полные имена пакетов (`xpkg.crossplane.io/...`) |

> 💡 В заголовке [00_INDEX.md](/platform/) и в старых статьях «Claim на базу» — в v2 это
> просто namespaced XR `LinkdDatabase` в namespace команды. Слово «claim» ещё живёт в речи.

---

## 4. API платформы: XRD `LinkdDatabase`

Проектируем как публичный API ([02_crd_operators.md](/platform/02-crd-operators)): минимум полей,
**размеры вместо сырых параметров**, дефолты, пределы.

```yaml
apiVersion: apiextensions.crossplane.io/v2
kind: CompositeResourceDefinition
metadata: { name: linkddatabases.platform.example.com }
spec:
  scope: Namespaced
  group: platform.example.com
  names: { kind: LinkdDatabase, plural: linkddatabases }
  defaultCompositionRef: { name: linkddatabase-cnpg }     # в облачном кластере — другая
  versions:
    - name: v1alpha1
      served: true
      referenceable: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              properties:
                size:      { type: string, enum: [small, medium], default: small }
                storageGB: { type: integer, minimum: 1, maximum: 20, default: 5 }
                version:   { type: string, enum: ["16", "17"], default: "17" }
                backup:    { type: boolean, default: true }
            status:
              type: object
              properties:
                secretName: { type: string }             # контракт: Secret &lt;имя&gt;-db, ключ url
                endpoint:   { type: string }
```text
```yaml
# то, что пишет команда (рядом с LinkdApp из тем 02–03)
apiVersion: platform.example.com/v1alpha1
kind: LinkdDatabase
metadata: { name: shortener, namespace: team-a }
spec: { size: small, storageGB: 5 }
```text
**Контракт для приложения:** в namespace появляется Secret **`&lt;имя&gt;-db` с ключом `url`**
(`postgresql://linkd:pass@host:5432/linkd`) — ровно то, на что ссылается оператор LinkdApp
из [03_writing_operator.md](/platform/03-writing-operator) при `database: true` (`LINKD_DATABASE_URL`
через `secretKeyRef`). Одинаковый контракт во всех композициях — и приложению всё равно,
CNPG под ним или RDS.

---

## 5. Композиция для kind: CloudNativePG, без облака

В v2 XR напрямую компонует ресурс **CloudNativePG** `Cluster` (оператор CNPG v1.30.1) —
провайдеры не нужны, всё работает офлайн. Свой Secret CNPG назвал бы `&lt;cluster&gt;-app` (ключ `uri`),
но у нас контракт `&lt;имя&gt;-db` / `url`. Поэтому pipeline из двух шагов: **patch-and-transform**
описывает Cluster, **function-python** один раз генерирует пароль и компонует Secret `&lt;имя&gt;-db`;
CNPG берёт из него логин и пароль владельца базы (`bootstrap.initdb.secret`).

```bash
# CloudNativePG
kubectl apply --server-side -f \
  https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.30/releases/cnpg-1.30.1.yaml
kubectl -n cnpg-system rollout status deploy/cnpg-controller-manager
# Crossplane
helm repo add crossplane-stable https://charts.crossplane.io/stable && helm repo update
helm install crossplane crossplane-stable/crossplane -n crossplane-system --create-namespace
kubectl -n crossplane-system get pods                      # crossplane, crossplane-rbac-manager
```text
```yaml
# platform/crossplane-base.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole                                          # ⭐ пустить Crossplane к CNPG
metadata:
  name: cnpg:aggregate-to-crossplane
  labels: { rbac.crossplane.io/aggregate-to-crossplane: "true" }
rules:
  - { apiGroups: [postgresql.cnpg.io], resources: [clusters], verbs: ["*"] }
---
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata: { name: function-patch-and-transform }
spec: { package: xpkg.crossplane.io/crossplane-contrib/function-patch-and-transform:v0.11.0 }
---
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata: { name: function-python }
spec: { package: xpkg.crossplane.io/crossplane-contrib/function-python:v0.6.0 }
```text
```yaml
# platform/composition-cnpg.yaml
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: linkddatabase-cnpg
  labels: { provider: cnpg }
spec:
  compositeTypeRef: { apiVersion: platform.example.com/v1alpha1, kind: LinkdDatabase }
  mode: Pipeline
  pipeline:
    - step: postgres
      functionRef: { name: function-patch-and-transform }
      input:
        apiVersion: pt.fn.crossplane.io/v1beta1
        kind: Resources
        resources:
          - name: cluster
            base:
              apiVersion: postgresql.cnpg.io/v1
              kind: Cluster
              spec:
                instances: 1
                storage: { size: 5Gi }
                bootstrap: { initdb: { database: linkd, owner: linkd, secret: { name: "" } } }
            patches:
              - { type: FromCompositeFieldPath, fromFieldPath: metadata.name, toFieldPath: metadata.name }
              - type: FromCompositeFieldPath                 # логин/пароль владельца — из нашего Secret
                fromFieldPath: metadata.name
                toFieldPath: spec.bootstrap.initdb.secret.name
                transforms: [{ type: string, string: { type: Format, fmt: "%s-db" } }]
              - type: FromCompositeFieldPath                 # small → 1 экземпляр, medium → 2 (реплика)
                fromFieldPath: spec.size
                toFieldPath: spec.instances
                transforms: [{ type: map, map: { small: 1, medium: 2 } }]
              - type: FromCompositeFieldPath
                fromFieldPath: spec.storageGB
                toFieldPath: spec.storage.size
                transforms: [{ type: string, string: { type: Format, fmt: "%dGi" } }]
              - type: FromCompositeFieldPath
                fromFieldPath: spec.version
                toFieldPath: spec.imageName
                transforms: [{ type: string, string: { type: Format, fmt: "ghcr.io/cloudnative-pg/postgresql:%s" } }]
              - type: ToCompositeFieldPath                   # status XR ← данные CNPG
                fromFieldPath: metadata.name
                toFieldPath: status.secretName
                transforms: [{ type: string, string: { type: Format, fmt: "%s-db" } }]
              - { type: ToCompositeFieldPath, fromFieldPath: status.writeService, toFieldPath: status.endpoint }
            readinessChecks:
              - { type: MatchCondition, matchCondition: { type: Ready, status: "True" } }
    - step: secret
      functionRef: { name: function-python }
      input:
        apiVersion: python.fn.crossplane.io/v1beta1
        kind: Script
        script: |
          import base64, secrets

          def compose(req, rsp):
              name = req.observed.composite.resource["metadata"]["name"]
              password = None
              if "secret" in req.observed.resources:          # ⭐ уже создан — берём старый пароль
                  data = req.observed.resources["secret"].resource["data"]
                  password = base64.b64decode(data["password"]).decode()
              if not password:
                  password = secrets.token_urlsafe(24)       # генерируем ОДИН раз
              rsp.desired.resources["secret"].resource.update({
                  "apiVersion": "v1", "kind": "Secret",
                  "type": "kubernetes.io/basic-auth",         # такой тип ждёт CNPG для initdb.secret
                  "metadata": {"name": f"{name}-db"},
                  "stringData": {"username": "linkd", "password": password,
                                 "url": f"postgresql://linkd:{password}@{name}-rw:5432/linkd"},
              })
              rsp.desired.resources["secret"].ready = True
```text
> ⚠️ Функция вызывается на **каждом** reconcile: без чтения observed-состояния пароль менялся бы
> каждые пару минут. В observed Secret приходит с `data` (base64), а не `stringData`. API объектов
> запроса (`req.observed...`) сверь с README function-python своей версии и прогони `crossplane
> composition render` до выкатки.

```bash
kubectl apply -f platform/crossplane-base.yaml
kubectl wait function/function-patch-and-transform --for=condition=Healthy --timeout=3m
kubectl apply -f platform/xrd-linkddatabase.yaml -f platform/composition-cnpg.yaml
kubectl get xrd                                  # ESTABLISHED True
kubectl create namespace team-a && kubectl apply -f shortener-db.yaml

kubectl -n team-a get linkddatabase shortener    # SYNCED True, READY False → True через 1–2 мин
kubectl -n team-a get clusters.postgresql.cnpg.io,pods,secret
kubectl -n team-a get secret shortener-db -o jsonpath='{.data.url}' | base64 -d; echo
crossplane resource trace linkddatabase shortener -n team-a   # дерево XR → ресурсы (в старых CLI — beta trace)
```text
Проверь самообслуживание целиком: LinkdApp `shortener` с `database: true` (или Deployment linkd
с `secretKeyRef: { name: shortener-db, key: url }`) → `/readyz` 200, `linkd_db_up 1`.

> 💡 **Без CNPG** — третья композиция той же XRD: function-python компонует StatefulSet
> `postgres:17` с PVC на `spec.storageGB`, Service `&lt;имя&gt;-rw` и тот же Secret `&lt;имя&gt;-db`.
> Команды разницы не заметят — в этом и смысл контракта.

---

## 6. Та же идея в облаке: AWS RDS и Yandex Managed PostgreSQL

XRD та же, меняется **композиция**. В облачном кластере — `defaultCompositionRef` на облачную
или выбор меткой: `spec.crossplane.compositionSelector.matchLabels: { provider: aws }` в XR.
Манифесты — для чтения (в kind не запустить).

```yaml
# фрагмент Composition linkddatabase-aws (step с function-patch-and-transform), provider-aws-rds
- name: rds
  base:
    apiVersion: rds.aws.m.upbound.io/v1beta1        # namespaced MR v2
    kind: Instance
    spec:
      forProvider:
        region: eu-central-1
        engine: postgres
        engineVersion: "17"
        instanceClass: db.t4g.micro
        allocatedStorage: 5
        dbName: linkd
        username: linkd
        autoGeneratePassword: true
        passwordSecretRef: { key: password }        # name — патчем ниже
        storageEncrypted: true                      # стандарт платформы, команда не выбирает
        backupRetentionPeriod: 7
        dbSubnetGroupName: platform-db              # сеть — зона платформы (Terraform)
        vpcSecurityGroupIds: [sg-0123456789abcdef0]
        skipFinalSnapshot: false
      managementPolicies: [Create, Observe, Update, LateInitialize]   # без Delete: удаление XR не удалит базу
      providerConfigRef: { kind: ClusterProviderConfig, name: default }
  patches:                                          # имена Secret'ов — от имени XR
    - type: FromCompositeFieldPath
      fromFieldPath: metadata.name
      toFieldPath: spec.writeConnectionSecretToRef.name   # endpoint, port, username, password
      transforms: [{ type: string, string: { type: Format, fmt: "%s-rds" } }]
    - type: FromCompositeFieldPath
      fromFieldPath: metadata.name
      toFieldPath: spec.forProvider.passwordSecretRef.name
      transforms: [{ type: string, string: { type: Format, fmt: "%s-rds-password" } }]
    - type: FromCompositeFieldPath
      fromFieldPath: spec.size
      toFieldPath: spec.forProvider.instanceClass
      transforms: [{ type: map, map: { small: db.t4g.micro, medium: db.t4g.medium } }]
    - { type: FromCompositeFieldPath, fromFieldPath: spec.storageGB, toFieldPath: spec.forProvider.allocatedStorage }
# step 2: function-python собирает Secret &lt;xr&gt;-db с ключом url из connection details &lt;xr&gt;-rds
```text
```yaml
# фрагмент Composition linkddatabase-yc, crossplane-provider-yc (регион Казахстан — kz1, одна зона)
- name: pg
  base:
    apiVersion: mdb.yandex-cloud.m.jet.crossplane.io/v1alpha1
    kind: PostgresqlCluster
    spec:
      forProvider:
        environment: PRODUCTION
        networkIdRef: { name: platform-net }
        config:
          - version: "17"
            resources: [{ resourcePresetId: s3-c2-m8, diskTypeId: network-ssd, diskSize: 10 }]
            backupRetainPeriodDays: 7
        host: [{ zone: kz1-a, subnetIdRef: { name: platform-kz1-a } }]
      providerConfigRef: { kind: ClusterProviderConfig, name: default }   # эндпоинты kz1 — *.yandexcloud.kz (проверь)
# + PostgresqlDatabase linkd и PostgresqlUser linkd (пароль из Secret) → Secret &lt;xr&gt;-db с url
```text
| | kind (CNPG) | AWS RDS | Yandex MDB (kz1) |
|---|-------------|---------|------------------|
| Кто исполняет | Оператор CNPG в кластере | provider-aws-rds → AWS API | crossplane-provider-yc → YC API |
| Где данные | PVC в кластере | Управляемый сервис | Управляемый сервис, данные в КЗ |
| Бэкап | `backup` CNPG (barman-плагин, S3/MinIO) | `backupRetentionPeriod` | `backupRetainPeriodDays` |
| Секрет `&lt;xr&gt;-db` / `url` | Функция: пароль один раз, CNPG берёт его для initdb | Функция из connection details RDS | Функция из пароля пользователя и хоста |

> ⚠️ Для персональных данных граждан РК важна локализация: регион `kz1` Yandex Cloud или
> казахстанские облака ([../Left/04_Cloud/10_kz_clouds.md](/cloud/10-kz-clouds)).
> Композиция — хорошее место зашить это правило: команда не выбирает регион вообще.

---

## 7. Ограждения: чтобы самообслуживание не стало самоуправством

| Ограждение | Как | Пример для LinkdDatabase |
|------------|-----|---------------------------|
| Разрешённые значения | `enum`, `minimum`/`maximum` в XRD | `size: small|medium`, `storageGB ≤ 20` |
| Дефолты | `default` в XRD | `backup: true`, `version: "17"` |
| Непереключаемые стандарты | Жёстко в композиции | Шифрование, бэкап 7 дней, регион, теги `team`, `cost-center` |
| Квоты | `ResourceQuota` на объекты и диски | `count/linkddatabases.platform.example.com: "2"`, `requests.storage: 40Gi` |
| Кто может создавать | RBAC на `linkddatabases` | Роль команды — только в своём namespace |
| Сложные правила | VAP/Kyverno ([04_admission_policy.md](/platform/04-admission-policy)) | `medium` — только в namespace с меткой `env=prod` |
| Защита от удаления | `managementPolicies` без `Delete`, `Prune=false` в ArgoCD | Удалили YAML — база осталась |
| Стоимость | Теги и отчёты FinOps | Сколько стоят базы команды в месяц |

```yaml
apiVersion: v1
kind: ResourceQuota
metadata: { name: platform-quota, namespace: team-a }
spec:
  hard:
    count/linkddatabases.platform.example.com: "2"   # квота на объекты CRD работает как на встроенные
    requests.storage: 40Gi                           # CNPG-тома тоже в неё попадают
```text
---

## 8. GitOps с ArgoCD

```text
 repo platform (App of Apps, ../Left/07_ArgoCD/04_app_of_apps.md)
   wave -2: Crossplane (Helm), CNPG, провайдеры, Functions
   wave -1: XRD, ClusterRole aggregate-to-crossplane, ProviderConfig
   wave  0: Compositions
 repo team-a
   LinkdDatabase shortener + LinkdApp shortener
```text
- XRD приносит CRD — ресурсы команды должны синхронизироваться **после** него: sync waves или
  `SkipDryRunOnMissingResource=true` на объектах команды.
- **Health.** Статус XR — условия `Synced` и `Ready`. Если ArgoCD не видит здоровье — Lua-проверка
  в `argocd-cm` (`resource.customizations.health.platform.example.com_LinkdDatabase`) по условию `Ready`.
- ⚠️ **Prune.** Удалили файл из git → ArgoCD удалит XR → Crossplane удалит базу. Для данных:
  `argocd.argoproj.io/sync-options: Prune=false` на XR и `managementPolicies` без `Delete` у MR.
- Секретов в git нет: пароль генерирует провайдер/функция, в git только «хочу базу размера small».

---

## 9. ⭐ Crossplane vs Terraform

| | Terraform / OpenTofu | Crossplane |
|---|----------------------|------------|
| Модель | `plan` → `apply` по запуску | Постоянный reconcile, как у любого контроллера |
| Состояние | Файл стейта в backend (S3 + lock) | Объекты в API Kubernetes (etcd) |
| Дрейф | Виден при следующем `plan` | Исправляется сам через интервал опроса |
| API для команд | Модули + MR в репозиторий + CI | ⭐ Свой kind в кластере + RBAC + квоты + GitOps |
| Предпросмотр | ⭐ `plan` — сильная сторона | `crossplane render` (локально), diff слабее |
| Провайдеры | Огромная экосистема | Многие сгенерированы Upjet **из** Terraform-провайдеров |
| Ошибка в коде | Ломает один `apply` | Контроллер будет упорно применять её везде, где есть XR |
| Порог входа | Низкий, HCL понятен | Kubernetes, CRD, функции, отладка контроллеров |
| Нужен кластер | Нет | Да — и его надо беречь: он управляет облаком |

**Мосты:** **provider-terraform** (v1.2.0) — MR `Workspace` запускает Terraform-модуль внутри
Crossplane (переиспользовать модули); **Tofu Controller** (flux-iac, v0.16.5) — OpenTofu/Terraform
как CRD под управлением Flux. **OpenTofu** (1.12) — открытый форк Terraform, подходит обоим.

Частая схема: **Terraform — фундамент** (VPC, кластер, IAM, DNS-зоны, сам Crossplane и его
креды), **Crossplane — ресурсы команд** (базы, бакеты, очереди) по API платформы.

**Когда Crossplane не нужен:**
- Одна-две команды, базы заводят раз в квартал — модуль Terraform и шаблон MR проще.
- Нет Kubernetes-компетенции или кластер нестабилен — он станет точкой отказа для облака.
- Нужен строгий ревью каждого изменения с `plan` (регулятор) — Terraform в CI с approve.
- Ресурсы долгоживущие и общие (сеть, кластеры) — их не надо «самообслуживать».

---

## 10. Грабли

| Грабля | Что происходит | Как избежать |
|--------|----------------|--------------|
| Статья про v1: Claim, `mode: Resources` | Манифесты не работают на v2 | Namespaced XR, `mode: Pipeline`, XRD `v2` |
| Нет RBAC на компонуемый kind | XR `Synced=False`: forbidden на `clusters.postgresql.cnpg.io` | ClusterRole с `aggregate-to-crossplane: "true"` |
| Composed-ресурс без фиксированного имени | Имя с суффиксом, Service `&lt;name&gt;-rw` в `url` не совпадёт | Патч `metadata.name` из XR |
| Пароль генерируется при каждом reconcile | Приложение теряет доступ каждые пару минут | Брать из observed, генерировать один раз |
| Удалили YAML из git | ArgoCD prune → удаление базы | `Prune=false`, `managementPolicies` без `Delete`, бэкапы |
| Сырые параметры в API (`instanceClass`) | Команды выбирают `db.r6g.4xlarge` | Размеры `small/medium` + map в композиции |
| Ресурсы команды раньше XRD | ArgoCD: «no matches for kind LinkdDatabase» | Sync waves, `SkipDryRunOnMissingResource` |
| Провайдер AWS ставит сотни CRD | Нагрузка на API server, память | MRD и ManagedResourceActivationPolicy — включать только нужное |
| Креды облака в Secret в git | Утечка ключей | IRSA/Pod Identity, workload identity, External Secrets |
| Обновление Crossplane «через версию» | Сломанный control plane | Только с 1.20, по одной минорной, последние патчи |

---

## 💼 Как это в DevOps

- Платформа публикует **каталог API**: `LinkdDatabase`, `Bucket`, `Queue` — каждый с размерами,
  документацией и владельцем. Новый kind появляется, когда один и тот же запрос пришёл в третий раз.
- XRD — публичный контракт: версии (`v1alpha1` → `v1beta1`), совместимость, объявление об изменениях.
  Композиции можно менять, не трогая команды: переехали с CNPG на RDS — XR тот же.
- Crossplane-кластер (control plane) часто отдельный от рабочих: он управляет облаком, у него
  свои креды, бэкапы и SLO.
- В резюме хорошо звучит: «сделал self-service базы: XRD + композиции для dev (CNPG) и prod (RDS),
  квоты и дефолты, время получения базы — с 3 дней до 5 минут».

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Поставить Crossplane | `helm install crossplane crossplane-stable/crossplane -n crossplane-system --create-namespace` |
| Свой API | XRD `apiextensions.crossplane.io/v2`, `scope: Namespaced` |
| Реализация API | Composition `mode: Pipeline` + функции |
| YAML-патчи | `function-patch-and-transform`, `FromCompositeFieldPath` / `ToCompositeFieldPath` |
| Логика на Python | `function-python` (Script) или своя функция на SDK |
| Компоновать не-Crossplane ресурс | ClusterRole с меткой `rbac.crossplane.io/aggregate-to-crossplane: "true"` |
| Выбрать композицию | `defaultCompositionRef` в XRD или `spec.crossplane.compositionSelector` в XR |
| Посмотреть дерево | `crossplane resource trace &lt;kind&gt; &lt;name&gt; -n &lt;ns&gt;` |
| Проверить композицию без кластера | `crossplane composition render xr.yaml composition.yaml functions.yaml` |
| Не удалять облачный ресурс | `managementPolicies: [Create, Observe, Update, LateInitialize]` |
| Квота на объекты | `count/linkddatabases.platform.example.com` в ResourceQuota |
| Мигрировать P&T v1 | `crossplane beta convert pipeline-composition` (CLI 1.20) |

---

## 🧠 Что запомнить

1. ⭐ Crossplane для платформы — это свой API в кластере: команда пишет «хочу базу small», платформа решает как.
2. Provider → MR (внешний объект); XRD → схема API; XR → экземпляр; Composition → pipeline функций.
3. ⭐ v2: XR и MR namespaced, Claim не нужен; композиция создаёт любой ресурс Kubernetes;
   только `mode: Pipeline`; connection details XR убраны; механика — в `spec.crossplane`.
4. Обновление на v2 — только с 1.20 и по одной минорной; v1.20 EOL — ноябрь 2026.
5. Для kind без облака: XR компонует CloudNativePG `Cluster` напрямую, function-python — Secret `&lt;name&gt;-db` с `url`
   (пароль генерируется один раз); это контракт оператора LinkdApp.
6. Компоновать не-Crossplane kind — ClusterRole с `aggregate-to-crossplane`.
7. ⭐ Один XRD — разные композиции: CNPG в dev, RDS в AWS, Managed PostgreSQL в Yandex `kz1`;
   контракт Secret одинаковый.
8. Ограждения: enum/max/default в XRD, стандарты в композиции, ResourceQuota, RBAC, VAP.
9. Данные защищают от prune: `Prune=false` в ArgoCD и `managementPolicies` без `Delete`.
10. ⭐ Terraform — plan/apply и стейт, Crossplane — постоянный reconcile и API для команд;
    часто вместе: Terraform для фундамента, Crossplane для ресурсов команд.
11. Crossplane не нужен при малом числе команд, слабой Kubernetes-экспертизе и требовании ревью `plan`.

➡️ Дальше: [08_backstage.md](/platform/08-backstage) · Задачи: 07_crossplane_self_service_tasks.md


---

### Блок A. Теория


**A1.** ⭐ Какую задачу платформы решает Crossplane? Почему это «не Terraform на YAML»?

<details><summary>Ответ</summary>

Даёт командам самообслуживание через **собственный API** платформы в Kubernetes: команда
создаёт `LinkdDatabase` на пять строк, а платформа композицией решает реализацию, настройки
безопасности, размеры и пределы. Terraform — инструмент инженера (plan/apply), Crossplane —
постоянно работающий контроллер и API с RBAC, квотами и GitOps.

</details>

**A2.** Что такое Provider, managed resource и ProviderConfig? Чем ProviderConfig отличается
от ClusterProviderConfig?

<details><summary>Ответ</summary>

Provider — пакет с контроллерами для внешнего API; MR — один внешний объект как ресурс
Kubernetes (RDS Instance, Bucket); ProviderConfig — креды и настройки провайдера. В v2
ProviderConfig — namespaced (свои креды у namespace), ClusterProviderConfig — общий для кластера;
в MR указывается `providerConfigRef` с `kind` и `name`.

</details>

**A3.** ⭐ Что такое XRD, XR и Composition? Как они связаны?

<details><summary>Ответ</summary>

XRD — схема нового API (группа, kind, OpenAPI, scope); XR — экземпляр этого API; Composition —
как из XR получить ресурсы (pipeline функций). XR ссылается на XRD как на свой тип, Composition —
через `compositeTypeRef`.

</details>

**A4.** Что такое composition function? Назови четыре готовые функции и чем они отличаются.

<details><summary>Ответ</summary>

Шаг pipeline, который получает observed-состояние и возвращает desired-ресурсы.
function-patch-and-transform — YAML с патчами; function-go-templating — Go-шаблоны (как Helm);
function-python — скрипт на Python; function-kcl — KCL; ещё function-kro (YAML+CEL).

</details>

**A5.** ⭐ Назови главные изменения Crossplane v2 по сравнению с v1.

<details><summary>Ответ</summary>

Namespaced XR (без Claim), namespaced MR (группы `.m.`), композиция любых ресурсов Kubernetes,
только `mode: Pipeline`, убраны connection details XR, ControllerConfig, внешние secret stores и реестр
по умолчанию; механика XR — под `spec.crossplane`; XRD `v2` со `scope`; Operations (alpha), MRD.

</details>

**A6.** Что стало с Claim в v2? Как тогда команда «заявляет» ресурс в своём namespace?

<details><summary>Ответ</summary>

Новые XR (`Namespaced`, `Cluster`) Claims не поддерживают — XR сам создаётся в namespace
команды. Claims остаются для legacy XR (`LegacyCluster`).

</details>

**A7.** Что такое `scope: LegacyCluster` и когда он появляется?

<details><summary>Ответ</summary>

При XRD API `apiextensions.crossplane.io/v1`: поведение как в v1 — cluster-scoped XR,
поддержка Claims, без `spec.crossplane`.

</details>

**A8.** Как в v2 скомпоновать ресурс, который не является MR (Deployment, CNPG Cluster)?
Что для этого нужно настроить?

<details><summary>Ответ</summary>

Просто описать его в композиции (без `Object` provider-kubernetes) и дать Crossplane права:
ClusterRole с меткой `rbac.crossplane.io/aggregate-to-crossplane: "true"` на этот API.

</details>

**A9.** Почему в v2 у XR больше нет connection details и что делать вместо них?

<details><summary>Ответ</summary>

Убрали как лишнюю магию. Потребителю компонуют свой Secret явно: либо его создаёт
функция (function-python) с паролем, сгенерированным один раз, либо Secret из connection details MR.

</details>

**A10.** Как правильно обновляться с Crossplane 1.x на 2.x?

<details><summary>Ответ</summary>

Только с 1.20, по одной минорной с последними патчами (1.20 → 2.0 → 2.1 …); заранее
`crossplane beta upgrade check` из CLI 1.20, перевод P&T на Pipeline, ControllerConfig на
DeploymentRuntimeConfig, полные имена пакетов.

</details>

**A11.** Какие поля ты бы дал в API `LinkdDatabase` и почему «размеры», а не сырые параметры?

<details><summary>Ответ</summary>

`size` (enum small/medium), `storageGB` (1–20), `version` (enum), `backup` (true по умолчанию).
Размеры скрывают детали облака и цены, их проще ограничивать и менять реализацию; сырые параметры
(`instanceClass`) привязывают команды к облаку и открывают дорогие варианты.

</details>

**A12.** Что такое «контракт Secret» и зачем он одинаковый во всех композициях?

<details><summary>Ответ</summary>

Соглашение: в namespace появляется Secret `&lt;имя&gt;-db` с ключом `url`. Приложение и оператор
LinkdApp зависят от контракта, а не от реализации — композицию можно менять (CNPG → RDS), не трогая команды.

</details>

**A13.** Как XR выбирает композицию? Как сделать одну XRD с разными реализациями для dev и prod?

<details><summary>Ответ</summary>

По `spec.crossplane.compositionRef`, `compositionSelector` (метки) или `defaultCompositionRef`
в XRD. В каждом кластере свой набор Composition (или своя по умолчанию): в kind — CNPG, в AWS — RDS.

</details>

**A14.** Что делают патчи `FromCompositeFieldPath` и `ToCompositeFieldPath`? Приведи по примеру.

<details><summary>Ответ</summary>

`FromCompositeFieldPath` — из XR в компонуемый ресурс (`spec.storageGB` → `spec.storage.size`
с форматом `%dGi`); `ToCompositeFieldPath` — обратно в XR (`status.writeService` → `status.endpoint`).

</details>

**A15.** Почему генерация пароля в функции должна быть идемпотентной?

<details><summary>Ответ</summary>

Функция вызывается при каждом reconcile. Новый пароль при каждом вызове меняет Secret
и ломает приложение и базу. Генерировать один раз, дальше читать из observed-состояния.

</details>

**A16.** ⭐ Какие ограждения ставят на самообслуживание? Назови не меньше пяти.

<details><summary>Ответ</summary>

Enum/min/max в XRD; дефолты; стандарты, зашитые в композицию (шифрование, бэкап, регион, теги);
ResourceQuota на число объектов и диски; RBAC на kind; VAP/Kyverno для сложных правил;
защита от удаления; учёт стоимости.

</details>

**A17.** Как защитить базу от случайного удаления через GitOps?

<details><summary>Ответ</summary>

`argocd.argoproj.io/sync-options: Prune=false` на XR, `managementPolicies` без `Delete` на MR
облачной базы, бэкапы, отдельный процесс удаления с подтверждением.

</details>

**A18.** Что такое `managementPolicies` и какие комбинации бывают?

<details><summary>Ответ</summary>

Какие действия Crossplane может выполнять над внешним ресурсом: `Create`, `Update`, `Delete`,
`Observe`, `LateInitialize`, `*` — всё. Без `Delete` — не удалит при удалении MR; только `Observe` —
«импорт» существующего ресурса на чтение; пустой список — пауза.

</details>

**A19.** Как доставлять Crossplane и API платформы через ArgoCD? В каком порядке?

<details><summary>Ответ</summary>

App of Apps платформы: сначала Crossplane, CNPG, провайдеры и функции, затем XRD, RBAC
и ProviderConfig, затем Compositions; ресурсы команд — после XRD (waves или
`SkipDryRunOnMissingResource`). Health XR — по условию `Ready` (при необходимости Lua-проверка).

</details>

**A20.** ⭐ Сравни Crossplane и Terraform по модели, состоянию, дрейфу и API для команд.

<details><summary>Ответ</summary>

Terraform: plan/apply по запуску, стейт в файле, дрейф виден при следующем plan, API для
команд — модули и MR в репо. Crossplane: постоянный reconcile, состояние в API Kubernetes, дрейф
исправляется сам, API для команд — свой kind с RBAC, квотами и GitOps. У Terraform сильнее
предпросмотр и порог входа ниже; Crossplane требует Kubernetes и бережного кластера.

</details>

**A21.** Что такое provider-terraform и Tofu Controller? Когда они полезны?

<details><summary>Ответ</summary>

provider-terraform — MR `Workspace`, который исполняет Terraform-модуль внутри Crossplane:
переиспользовать готовые модули под API платформы. Tofu Controller — OpenTofu/Terraform как CRD
под Flux: GitOps для Terraform без Crossplane.

</details>

**A22.** ⭐ Когда Crossplane не нужен?

<details><summary>Ответ</summary>

Мало команд и редкие запросы; нет Kubernetes-экспертизы или стабильного кластера;
требуется ревью каждого `plan`; ресурсы общие и долгоживущие (сеть, кластеры).

</details>

**A23.** Зачем MRD и ManagedResourceActivationPolicy?

<details><summary>Ответ</summary>

Провайдер может принести сотни CRD; MRD и ManagedResourceActivationPolicy позволяют
включить только нужные MR и не нагружать API server.

</details>

**A24.** Как проверить композицию без кластера? Как посмотреть дерево ресурсов XR?

<details><summary>Ответ</summary>

`crossplane composition render xr.yaml composition.yaml functions.yaml` (функции в Docker).
Дерево — `crossplane resource trace &lt;kind&gt; &lt;name&gt; -n &lt;ns&gt;`.

</details>

**A25.** Что такое Operations в Crossplane v2 и какого они статуса?

<details><summary>Ответ</summary>

Pipeline функций, который выполняется до завершения, как Job: `Operation` (разово),
`CronOperation` (по расписанию), `WatchOperation` (по изменению ресурсов). В v2 — alpha.

</details>

---

### Блок B. «Что произойдёт»


```text:no-line-numbers
# B1 — Crossplane v2.4, Composition из статьи 2023 года
```text
```text:no-line-numbers
spec:
```text
```text:no-line-numbers
  compositeTypeRef: { apiVersion: platform.example.com/v1alpha1, kind: LinkdDatabase }
```text
```text:no-line-numbers
  resources:
```text
```text:no-line-numbers
    - name: db
```text
```text:no-line-numbers
      base: { ... }
```text
Вопрос: что будет при применении?

```text:no-line-numbers
# B2 — Composition компонует postgresql.cnpg.io/v1 Cluster, отдельного ClusterRole нет
```text
Вопрос: какой статус получит XR?

```text:no-line-numbers
# B3 — патчей на metadata.name нет
```text
```text:no-line-numbers
- name: cluster
```text
```text:no-line-numbers
  base: { apiVersion: postgresql.cnpg.io/v1, kind: Cluster, ... }
```text
```text:no-line-numbers
# оператор LinkdApp ждёт Secret shortener-db (ключ url); url ведёт на Service &lt;имя кластера&gt;-rw
```text
Вопрос: запустится ли linkd?

```text:no-line-numbers
# B4 — XRD
```text
```text:no-line-numbers
storageGB: { type: integer, minimum: 1, maximum: 20, default: 5 }
```text
```text:no-line-numbers
# команда применяет storageGB: 100
```text
Вопрос: что ответит API server? А если команда создаст CNPG Cluster на 100Gi напрямую?

```text:no-line-numbers
# B5 — function-python
```text
```text:no-line-numbers
password = secrets.token_urlsafe(24)
```text
```text:no-line-numbers
rsp.desired.resources["secret"].resource.update({... "stringData": {"password": password&#125;&#125;)
```text
Вопрос: что будет с приложением через 10 минут?

```text:no-line-numbers
# B6 — ArgoCD Application team-a: prune: true
```text
```text:no-line-numbers
# разработчик удалил shortener-db.yaml из репозитория
```text
Вопрос: что случится с базой в kind (CNPG)? А с RDS при `managementPolicies: [Create, Observe, Update, LateInitialize]`?

```text:no-line-numbers
# B7 — ResourceQuota team-a: count/linkddatabases.platform.example.com: "2"
```text
```text:no-line-numbers
# в namespace уже 2 LinkdDatabase, команда создаёт третью
```text
Вопрос: что будет?

```text:no-line-numbers
# B8 — XR
```text
```text:no-line-numbers
spec:
```text
```text:no-line-numbers
  size: small
```text
```text:no-line-numbers
  crossplane:
```text
```text:no-line-numbers
    compositionSelector: { matchLabels: { provider: aws } }
```text
```text:no-line-numbers
# в кластере kind есть только Composition с меткой provider: cnpg
```text
Вопрос: что будет с XR?

```text:no-line-numbers
# B9 — ArgoCD синхронизирует один репозиторий: XRD и LinkdDatabase в одной волне
```text
Вопрос: какая ошибка может появиться и как её убрать?

```text:no-line-numbers
# B10 — Crossplane v1.18 в проде
```text
```text:no-line-numbers
helm upgrade crossplane crossplane-stable/crossplane --version 2.4.2
```text
Вопрос: чем это плохо?

---

### Блок C. Практика


### C1. 🔑 Установка
Поставь в kind CloudNativePG v1.30.1 и Crossplane v2.4.x. Проверь поды обоих и `kubectl get crd | grep -E "crossplane|cnpg"`.

### C2. 🔑 API LinkdDatabase
Напиши XRD `linkddatabases.platform.example.com` (`scope: Namespaced`, поля size, storageGB,
version, backup со значениями по умолчанию и пределами). Проверь: `kubectl explain` на новый kind,
отказ API server на `storageGB: 100` и на `size: huge`.

### C3. 🔑 Композиция на CNPG
Напиши Composition из двух шагов: function-patch-and-transform — CNPG Cluster с именем XR, `instances`
по размеру, `storage.size` из `storageGB`, `initdb.secret`, `status.secretName` и `status.endpoint`,
readiness по `Ready`; function-python — Secret `&lt;имя&gt;-db` (`username`, `password`, `url`).
Создай XR `shortener` в `team-a` и дождись `READY True`. Посмотри `crossplane resource trace`.

### C4. Самообслуживание целиком
Запусти linkd 2.0 (Deployment или LinkdApp из темы 03) с `LINKD_DATABASE_URL` из Secret
`shortener-db` / `url`. Проверь `/readyz`, создай ссылку, перезапусти под — ссылка на месте.

### C5. Изменение размера
Поменяй `size: medium`. Что изменилось в CNPG Cluster? Сколько подов PostgreSQL? Что будет,
если уменьшить `storageGB`?

### C6. Ограждения
Добавь ResourceQuota с `count/linkddatabases...: "2"` и `requests.storage: 20Gi`. Попробуй создать
третью базу и базу на 20 ГБ при уже занятых 10. Запиши сообщения об ошибках — понятны ли они команде?

### C7. Композиция без CNPG (со звёздочкой)
Сделай вторую композицию на function-python: Secret с паролем (генерируется **один раз**),
StatefulSet `postgres:17` с PVC и Service. Переключи XR на неё через `compositionSelector`.
Докажи идемпотентность: пароль в Secret не меняется за 10 минут.

### C8. render без кластера
Прогони обе композиции через `crossplane composition render` (нужен Docker) и сравни вывод
с тем, что создалось в кластере.

### C9. GitOps
Разложи всё по двум репозиториям (платформа и команда), подключи ArgoCD с sync waves.
Удали файл XR из git при `Prune=false` на XR и при обычном prune — сравни результат.

### C10. Облачная композиция на бумаге
Напиши Composition `linkddatabase-aws` (RDS Instance, namespaced MR) и `linkddatabase-yc`
(PostgresqlCluster в `kz1-a`) с тем же контрактом Secret. Отметь, какие поля задаёт команда,
какие — платформа, а какие приходят из Terraform (сеть, security groups).

---

### Блок D. Инциденты


**D1.** XR `LinkdDatabase` висит `SYNCED False`, в событиях `cannot apply composed resource ... forbidden`. Что делать?

<details><summary>Ответ</summary>

Нет прав у Crossplane на компонуемый kind: ClusterRole с `aggregate-to-crossplane`, проверить,
что rbac-manager агрегировал её в роль `crossplane`.

</details>

**D2.** База есть, XR `READY False` уже час. Где искать?

<details><summary>Ответ</summary>

`crossplane resource trace`: какой ресурс не Ready; readinessChecks композиции (не то условие,
не тот путь); условия самого ресурса (CNPG Cluster `Ready`), события и логи оператора CNPG.

</details>

**D3.** После обновления композиции у всех команд разом перезапустились базы. Почему и как
предотвратить в будущем?

<details><summary>Ответ</summary>

Изменение композиции сразу применяется ко всем XR (например, поменяли image или параметры,
требующие рестарта). Вводить изменения через ревизии композиций: `compositionUpdatePolicy: Manual`
и `compositionRevisionRef`, выкатывать на часть XR, тестировать `render`.

</details>

**D4.** Команда удалила namespace `team-a` — облачная база RDS осталась, а CNPG-база пропала. Объясни разницу.

<details><summary>Ответ</summary>

CNPG-база — ресурс Kubernetes в этом namespace и удаляется вместе с ним. RDS — внешний
ресурс; MR удалился, но без `Delete` в политиках (или при ошибке кредов) инстанс остался в AWS.

</details>

**D5.** API server тормозит, `kubectl get crd | wc -l` показывает 900+. Что случилось?

<details><summary>Ответ</summary>

Провайдеры (особенно AWS целиком) поставили сотни CRD. Ставить семейства провайдеров
(provider-aws-rds вместо монолита) и включать только нужные MR через MRD/активацию.

</details>

**D6.** linkd периодически теряет доступ к базе: «password authentication failed», через минуту всё работает. Гипотезы?

<details><summary>Ответ</summary>

Пароль в Secret меняется при reconcile (не идемпотентная функция) или ротация без перезапуска
приложения; ещё — два источника правды для пароля (Secret и пользователь в базе).

</details>

**D7.** После ручного изменения класса инстанса RDS в консоли AWS он через несколько минут
вернулся обратно. Это баг?

<details><summary>Ответ</summary>

Нет, это reconcile: Crossplane вернул желаемое состояние из MR. Менять через XR/композицию
или отключать `Update` в `managementPolicies`, если ручное управление осознанно.

</details>

**D8.** Разработчик создал XR с опечаткой в `compositionSelector`, XR висит без ресурсов,
ошибок в его namespace не видно. Как помочь ему быстрее?

<details><summary>Ответ</summary>

Статус и события XR (`kubectl describe`), `crossplane resource trace`. Лучше — ограждение:
VAP/Kyverno, проверяющий, что селектор совпадает с существующей композицией, и понятный
`status` с подсказкой.

</details>

---

### Блок E. Вопросы с собеседования


**1.** ⭐ Что такое Crossplane и зачем он платформенной команде?

<details><summary>Ответ</summary>

Контроллеры и API в Kubernetes для внешних ресурсов; платформе — свои kind'ы
   с композициями, чтобы команды заказывали базы и бакеты сами, в пределах ограждений.

</details>

**2.** Объясни XRD, XR, Composition и функции на примере.

<details><summary>Ответ</summary>

XRD `LinkdDatabase` (size, storageGB), XR `shortener` в namespace команды, Composition —
   pipeline: CNPG Cluster в dev или RDS в облаке, Secret `&lt;name&gt;-db` с `url`.

</details>

**3.** ⭐ Что изменилось в Crossplane v2?

<details><summary>Ответ</summary>

Namespaced XR и MR, без Claim; композиция любых ресурсов; только Pipeline; нет connection
   details XR; `spec.crossplane`; обновление только с 1.20.

</details>

**4.** ⭐ Crossplane или Terraform? Можно ли вместе?

<details><summary>Ответ</summary>

Terraform — фундамент и ревью plan; Crossplane — постоянный reconcile и API для команд;
   вместе: Terraform поднимает сеть, кластер и Crossplane, Crossplane — ресурсы команд;
   provider-terraform для переиспользования модулей.

</details>

**5.** Как вы ограничиваете, что команды могут заказать?

<details><summary>Ответ</summary>

Размеры вместо параметров, enum/max/default, стандарты в композиции, ResourceQuota, RBAC, VAP.

</details>

**6.** Как не удалить продовую базу через GitOps?

<details><summary>Ответ</summary>

`Prune=false` на XR, `managementPolicies` без `Delete`, бэкапы и процедура удаления.

</details>

**7.** Как тестировать композиции?

<details><summary>Ответ</summary>

`crossplane composition render` в CI, unit-тесты функций, e2e в kind (создать XR, дождаться Ready,
   проверить Secret), ревизии композиций с ручным переключением.

</details>

**8.** Как дать одну и ту же «базу по запросу» в dev-кластере и в облаке?

<details><summary>Ответ</summary>

Один XRD и контракт Secret, разные Composition по кластерам (`defaultCompositionRef`).

</details>

**9.** Какие риски у Crossplane в проде?

<details><summary>Ответ</summary>

Кластер — точка отказа для управления облаком; ошибка композиции применяется ко всем XR;
   креды облака в кластере; сложная отладка; сотни CRD.

</details>

**10.** Когда вы бы не стали внедрять Crossplane?

<details><summary>Ответ</summary>

Мало команд и запросов, нет Kubernetes-экспертизы, нужен строгий ревью plan, ресурсы общие.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Объясняю Provider, MR, XRD, XR, Composition и функции на примере «базы по запросу»
- [ ] ⭐ Знаю, что изменилось в Crossplane v2, и читаю старые статьи с поправкой
- [ ] Написал XRD `LinkdDatabase` с enum, пределами и дефолтами
- [ ] Композиция на CNPG работает в kind, linkd подключился через Secret `&lt;name&gt;-db`
- [ ] Понимаю RBAC `aggregate-to-crossplane` и идемпотентность функций
- [ ] Написал облачные композиции (RDS, Yandex `kz1`) с тем же контрактом
- [ ] Ставлю ограждения: квоты, RBAC, стандарты в композиции, защита от удаления
- [ ] Доставляю Crossplane и API через ArgoCD в правильном порядке
- [ ] ⭐ Сравниваю Crossplane и Terraform и знаю, когда Crossplane не нужен
