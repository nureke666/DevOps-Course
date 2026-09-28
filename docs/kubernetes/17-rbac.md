---
title: "17. ⭐ RBAC"
description: "Субъекты, Role/ClusterRole, RoleBinding/ClusterRoleBinding, проверка прав, минимальные привилегии для CI"
---

# 17. ⭐ RBAC

> Роадмап → 6. Kubernetes → **Продвинутые вещи**: «Важно, база продвинутых вещей: **RBAC**, HPA».
> **После темы ты умеешь:** выдать права приложению и человеку по принципу минимальных
> привилегий и разобраться, почему «доступ запрещён».

---

## 🗺️ Карта темы

```text:no-line-numbers
   КТО (субъект)              ЧТО МОЖНО (права)            СВЯЗЬ
  ┌────────────────┐        ┌──────────────────┐      ┌──────────────────┐
  │ ServiceAccount │        │ Role             │      │ RoleBinding      │
  │ (для подов)    │        │ (в namespace)    │◄────►│ (в namespace)    │
  ├────────────────┤        ├──────────────────┤      ├──────────────────┤
  │ User / Group   │        │ ClusterRole      │◄────►│ ClusterRoleBinding│
  │ (для людей и CI)│       │ (весь кластер)   │      │ (весь кластер)   │
  └────────────────┘        └──────────────────┘      └──────────────────┘

  Права = глаголы (verbs) над ресурсами:
     get, list, watch, create, update, patch, delete, deletecollection, exec
```

---

## 1. Как API-сервер решает, можно ли

```text:no-line-numbers
запрос → [Аутентификация: кто ты?] → [Авторизация: RBAC] → [Admission] → etcd
```

| Этап | Что проверяется |
|------|-----------------|
| Аутентификация | Сертификат, токен ServiceAccount, OIDC, exec-плагин облака |
| **Авторизация (RBAC)** | Есть ли правило, разрешающее субъекту глагол над ресурсом |
| Admission | Политики, квоты, мутации |

**Ключевое свойство RBAC: разрешений по умолчанию нет.** Всё запрещено, пока
не выдано явно. Запрещающих правил не существует — только разрешающие
(как и в NetworkPolicy).

---

## 2. Субъекты

| Субъект | Для кого | Где создаётся |
|---------|----------|---------------|
| **ServiceAccount** | Поды и контроллеры внутри кластера | Объект кубера, в namespace |
| **User** | Люди | Внешняя система: сертификат, OIDC. Объекта `User` в кубере нет |
| **Group** | Группы людей | Из сертификата (`O=`) или от провайдера OIDC |

```bash
kubectl create serviceaccount ci-deployer -n prod
kubectl get sa
```

У каждого пода есть ServiceAccount (по умолчанию — `default` в его namespace),
токен монтируется в `/var/run/secrets/kubernetes.io/serviceaccount/`.

```yaml
spec:
  serviceAccountName: ci-deployer
  automountServiceAccountToken: false   # ⭐ отключить, если поду API не нужен
```

> С версии 1.24 токены SA не создаются автоматически в виде Secret'ов: в под
> монтируется короткоживущий projected-токен. Долгоживущий токен можно создать
> явно (Secret с аннотацией `kubernetes.io/service-account.name`) — так делают
> для внешних систем, например для доступа CI к кластеру.

---

## 3. Права: Role и ClusterRole

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: prod
  name: pod-reader
rules:
  - apiGroups: [""]                       # "" = core API (pods, services, configmaps)
    resources: ["pods", "pods/log"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "watch", "update", "patch"]
  - apiGroups: [""]
    resources: ["pods/exec"]              # ⚠️ вход в контейнер — фактически root в поде
    verbs: ["create"]
```

| | Role | ClusterRole |
|---|---|---|
| Область | один namespace | весь кластер |
| Может описывать | ресурсы этого namespace | в том числе `nodes`, `pv`, `storageclasses`, non-resource URL (`/healthz`) |

**Глаголы:**

| Глагол | Что разрешает |
|--------|---------------|
| `get` | получить один объект |
| `list` | получить список (⚠️ по сути даёт чтение всех) |
| `watch` | подписка на изменения |
| `create`, `update`, `patch`, `delete` | изменение |
| `deletecollection` | удалить пачкой |
| `*` | всё |

Подресурсы указываются через слэш: `pods/log`, `pods/exec`, `pods/portforward`,
`deployments/scale`.

---

## 4. Связывание: RoleBinding и ClusterRoleBinding

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: read-pods
  namespace: prod
subjects:
  - kind: ServiceAccount
    name: ci-deployer
    namespace: prod
  - kind: User
    name: nurik@example.com
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role                 # или ClusterRole
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io
```

⭐ **Четыре комбинации — любимый вопрос собеса:**

| Binding | Role | Результат |
|---------|------|-----------|
| RoleBinding | Role | Права в одном namespace |
| **RoleBinding** | **ClusterRole** | ⭐ Права ClusterRole, но **только в этом namespace** — самый частый приём |
| ClusterRoleBinding | ClusterRole | Права во всём кластере |
| ClusterRoleBinding | Role | ❌ Невозможно |

Второй вариант позволяет описать роль один раз и переиспользовать её
в десятках namespace.

---

## 5. Встроенные ClusterRole

```bash
kubectl get clusterroles | head -20
```

| Роль | Что даёт |
|------|----------|
| `view` | Чтение большинства ресурсов, **без** секретов |
| `edit` | `view` + изменение объектов (без прав на RBAC) |
| `admin` | `edit` + управление ролями **внутри namespace** |
| `cluster-admin` | ⚠️ Всё и везде. Выдавать людям не следует |

Типичная выдача:
```bash
kubectl create rolebinding dev-team --clusterrole=edit --group=developers -n dev
kubectl create rolebinding prod-view --clusterrole=view --group=developers -n prod
```

---

## 6. Проверка прав ⭐

```bash
kubectl auth can-i create deployments -n prod
kubectl auth can-i delete pods -n prod --as=system:serviceaccount:prod:ci-deployer
kubectl auth can-i --list -n prod --as=system:serviceaccount:prod:ci-deployer
kubectl auth can-i '*' '*' --as=alice          # проверка на cluster-admin

kubectl describe clusterrole view
kubectl get rolebinding,clusterrolebinding -A -o wide | grep ci-deployer
```

`--as` (impersonation) — лучший способ проверить, что права выданы ровно те,
что нужно, не заводя отдельный kubeconfig.

**Типичная ошибка доступа:**
```text:no-line-numbers
Error from server (Forbidden): pods is forbidden:
User "system:serviceaccount:prod:ci-deployer" cannot list resource "pods"
in API group "" in the namespace "prod"
```
Здесь сразу видно: субъект, глагол, ресурс, API-группа, namespace —
всё, что нужно, чтобы написать правило.

---

## 7. Права приложению: практический пример

Приложение (или контроллер) должно читать ConfigMap и перезапускать Deployment:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata: { name: config-watcher, namespace: app }
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: { name: config-watcher, namespace: app }
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: { name: config-watcher, namespace: app }
subjects:
  - kind: ServiceAccount
    name: config-watcher
    namespace: app
roleRef:
  kind: Role
  name: config-watcher
  apiGroup: rbac.authorization.k8s.io
---
apiVersion: apps/v1
kind: Deployment
metadata: { name: watcher, namespace: app }
spec:
  selector: { matchLabels: { app: watcher } }
  template:
    metadata: { labels: { app: watcher } }
    spec:
      serviceAccountName: config-watcher     # ⭐ иначе будет default без прав
      containers:
        - name: app
          image: mywatcher:1.0
```

---

## 8. Доступ для CI и для людей

### CI (пайплайн из блока CI/CD)

Порядок выбора, от лучшего к худшему:

| Способ | Что хранится в CI | Когда |
|--------|-------------------|-------|
| **GitOps** (Argo CD) | Ничего: CI пушит в git, Argo CD внутри кластера сам применяет | ⭐ по умолчанию |
| **OIDC**: `id_tokens` GitLab CI → API-сервер доверяет издателю | Ничего долгоживущего: токен живёт минуты | Push-деплой, если API-сервер можно настроить |
| `kubectl create token gitlab-deployer --duration=1h` | Токен на час, сам истекает | Разовый доступ, отладка, выдача токена на одну джобу |
| Secret типа `service-account-token` (ниже) | **Бессрочный** токен | Только если ничего другого нельзя |

```bash
kubectl create serviceaccount gitlab-deployer -n prod
kubectl create rolebinding gitlab-deployer \
  --clusterrole=edit \
  --serviceaccount=prod:gitlab-deployer -n prod
# ⚠️ edit даёт и чтение Secret'ов в namespace — для CI лучше своя Role:
#    deployments, services, configmaps, ingresses, без secrets

# короткий токен (TokenRequest API): истечёт сам
kubectl -n prod create token gitlab-deployer --duration=1h

# ⚠️ legacy: бессрочный токен для внешней системы — только если иначе нельзя
cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Secret
metadata:
  name: gitlab-deployer-token
  namespace: prod
  annotations:
    kubernetes.io/service-account.name: gitlab-deployer
type: kubernetes.io/service-account-token
EOF

kubectl -n prod get secret gitlab-deployer-token -o jsonpath='{.data.token}' | base64 -d
```
Бессрочный токен кладут в protected + masked CI-переменную, из неё собирают kubeconfig.
Он действует, пока жив Secret: утёк — значит, у атакующего доступ на годы. Если без него
никак: права только на один namespace и без `secrets`, ротация (удалить Secret и создать
заново) по расписанию и сразу при подозрении на утечку. Найти такие токены в кластере:
`kubectl get secrets -A --field-selector type=kubernetes.io/service-account-token`.
Подробнее — в разделах по безопасности Kubernetes и IAM-доступу из CI (OIDC).

### Люди
Правильный путь — OIDC (Keycloak, Google, Azure AD): пользователь аутентифицируется
у провайдера, кубер получает группы из токена, права выдаются группам.
Клиентские сертификаты работают, но их нельзя отозвать (только перевыпуском CA)
и неудобно ротировать.

---

## 9. Практика минимальных привилегий

| Правило | Почему |
|---------|--------|
| Никаких `cluster-admin` людям | Один неверный `delete` — и кластера нет |
| По namespace на команду/окружение | Ошибка не выходит за границу |
| Прод — только чтение, изменения через пайплайн | Аудит и воспроизводимость |
| `automountServiceAccountToken: false` | Большинству подов API не нужен |
| Не выдавать `secrets: list` без надобности | Это доступ ко всем паролям namespace |
| Помнить, что `pods/exec` ≈ права контейнера | Через exec читают секреты из ФС |
| Права описывать в git | RBAC — тоже код |
| Регулярно проверять `can-i --list` | Права имеют свойство накапливаться |

**Что ещё стоит знать рядом:**
Pod Security Admission (`enforce=baseline|restricted` метками на namespace) —
пришёл на смену PodSecurityPolicy и ограничивает уже не доступ к API,
а то, какие поды можно запускать.

```bash
kubectl label ns app pod-security.kubernetes.io/enforce=baseline
```

---

## 💼 Как это в DevOps

- RBAC настраивают один раз при заведении команды/окружения и потом почти не трогают —
  но именно на нём ловят «почему мой сервис не может читать секрет».
- Сообщение `Forbidden` содержит всё нужное: субъект, глагол, ресурс, namespace.
  Читать его — навык, экономящий часы.
- В managed-кластере поверх RBAC стоит IAM облака: сначала облако решает,
  пускать ли к API, потом кубер решает, что можно.
- Пайплайну дают минимально необходимые права в конкретном namespace,
  а не `cluster-admin` «чтобы точно работало».
- RBAC-манифесты живут рядом с приложением: контроллеру нужны свои права,
  и это часть его чарта.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Создать SA | `kubectl create serviceaccount NAME -n NS` |
| Дать права в namespace | Role + RoleBinding |
| Дать права на весь кластер | ClusterRole + ClusterRoleBinding |
| Переиспользовать роль в namespace | ClusterRole + **RoleBinding** |
| Быстро выдать стандартные права | `--clusterrole=view/edit/admin` |
| Проверить свои права | `kubectl auth can-i VERB RESOURCE -n NS` |
| Проверить чужие права | `... --as=system:serviceaccount:NS:NAME` |
| Список всех прав субъекта | `kubectl auth can-i --list --as=...` |
| Привязать SA к поду | `spec.serviceAccountName` |
| Отключить токен в поде | `automountServiceAccountToken: false` |
| Найти биндинги субъекта | `kubectl get rolebinding,clusterrolebinding -A -o wide \| grep NAME` |

---

## 🧠 Что запомнить

1. RBAC = **кто** (субъект) + **что можно** (Role/ClusterRole) + **связь** (Binding).
2. По умолчанию не разрешено ничего; запрещающих правил не бывает.
3. Субъекты: ServiceAccount (поды), User и Group (люди и внешние системы).
   Объекта `User` в кубере нет.
4. Role — в namespace, ClusterRole — на весь кластер и на ресурсы уровня кластера.
5. ⭐ RoleBinding + ClusterRole = права роли, ограниченные одним namespace.
6. ClusterRoleBinding + Role невозможно.
7. Встроенные роли: `view`, `edit`, `admin`, `cluster-admin`.
8. `kubectl auth can-i ... --as=...` — главный инструмент проверки.
9. Под без явного SA использует `default` из своего namespace.
10. `pods/exec` и `secrets` — самые опасные права; выдавать осознанно.
11. Токены SA с 1.24 короткоживущие; долгоживущий создаётся явным Secret'ом — для CI это худший вариант (лучше GitOps, OIDC или `kubectl create token`).
12. Pod Security Admission ограничивает, какие поды можно запускать, —
    это дополнение к RBAC, а не замена.

---

## Задачи

> Практическая цель темы: выдать пайплайну ровно те права, что нужны,
> и уметь за минуту ответить на вопрос «почему Forbidden».

---

### Блок A. Теория

**A1.** ⭐ Из каких четырёх типов объектов состоит RBAC?

<details><summary>Ответ</summary>

Role, ClusterRole (права), RoleBinding, ClusterRoleBinding (связи);
плюс субъекты — ServiceAccount, User, Group.

</details>

**A2.** Что разрешено субъекту по умолчанию?

<details><summary>Ответ</summary>

Ничего: доступ разрешается только явными правилами.

</details>

**A3.** Существуют ли запрещающие правила?

<details><summary>Ответ</summary>

Нет, RBAC только разрешает. «Запрет» — это отсутствие разрешения.

</details>

**A4.** Какие бывают субъекты? Чем User отличается от ServiceAccount?

<details><summary>Ответ</summary>

ServiceAccount — объект кубера для подов и автоматизации; User и Group —
внешние идентичности (сертификат, OIDC), объектов в кубере не имеют.

</details>

**A5.** Почему в кубере нет объекта `User`?

<details><summary>Ответ</summary>

Кубер не управляет учётными записями людей: аутентификация делегирована
внешним системам, а RBAC оперирует именем из предъявленного удостоверения.

</details>

**A6.** Что происходит с запросом на этапах аутентификации, авторизации и admission?

<details><summary>Ответ</summary>

Аутентификация определяет, кто запрашивает; авторизация (RBAC) — можно ли
ему выполнить глагол над ресурсом; admission — соответствует ли объект политикам
(квоты, PSA, webhooks) и при необходимости изменяет его.

</details>

**A7.** ⭐ Чем Role отличается от ClusterRole?

<details><summary>Ответ</summary>

Role действует в пределах namespace; ClusterRole — на весь кластер
и может описывать ресурсы уровня кластера и non-resource URL.

</details>

**A8.** Какие ресурсы можно описать только в ClusterRole?

<details><summary>Ответ</summary>

Node, PersistentVolume, StorageClass, Namespace, ClusterRole/Binding, CRD,
а также пути вроде `/healthz`, `/metrics`.

</details>

**A9.** Назови основные глаголы RBAC.

<details><summary>Ответ</summary>

`get`, `list`, `watch`, `create`, `update`, `patch`, `delete`,
`deletecollection`, `*`.

</details>

**A10.** Что такое подресурсы и приведи три примера.

<details><summary>Ответ</summary>

Части объекта с отдельными правами: `pods/log`, `pods/exec`,
`pods/portforward`, `deployments/scale`.

</details>

**A11.** ⭐ Какие четыре комбинации Role/ClusterRole и Binding возможны и что означает каждая?

<details><summary>Ответ</summary>

RoleBinding+Role — права в namespace; RoleBinding+ClusterRole — права
роли, ограниченные этим namespace; ClusterRoleBinding+ClusterRole — права во всём
кластере; ClusterRoleBinding+Role — невозможно.

</details>

**A12.** Какая комбинация невозможна и почему?

<details><summary>Ответ</summary>

ClusterRoleBinding с Role: Role привязана к своему namespace,
её нельзя «расширить» на весь кластер.

</details>

**A13.** Зачем связывать ClusterRole через RoleBinding?

<details><summary>Ответ</summary>

Чтобы описать набор прав один раз и выдавать его в разных namespace
без дублирования объектов Role.

</details>

**A14.** Назови встроенные ClusterRole и что они дают.

<details><summary>Ответ</summary>

`view` — чтение без секретов; `edit` — изменение объектов;
`admin` — управление namespace, включая роли в нём; `cluster-admin` — полный доступ.

</details>

**A15.** Чем `edit` отличается от `admin`?

<details><summary>Ответ</summary>

`admin` дополнительно позволяет управлять RBAC внутри своего namespace
(создавать роли и биндинги), `edit` — нет.

</details>

**A16.** Какой SA использует под, если не указан явно?

<details><summary>Ответ</summary>

ServiceAccount `default` своего namespace.

</details>

**A17.** Где внутри пода лежит токен ServiceAccount?

<details><summary>Ответ</summary>

`/var/run/secrets/kubernetes.io/serviceaccount/` (файлы `token`, `ca.crt`,
`namespace`).

</details>

**A18.** Что изменилось с токенами SA начиная с версии 1.24?

<details><summary>Ответ</summary>

Токены стали короткоживущими projected-токенами с автоматической ротацией;
Secret'ы с токенами больше не создаются автоматически.

</details>

**A19.** Как дать доступ к кластеру внешней системе (CI)? Как создать долгоживущий токен и почему это худший вариант?

<details><summary>Ответ</summary>

Лучше всего GitOps (у CI вообще нет доступа к кластеру), затем OIDC из CI или
короткий токен `kubectl create token <sa> --duration=1h`. Долгоживущий токен — Secret типа
`kubernetes.io/service-account-token` с аннотацией `kubernetes.io/service-account.name`.
Он бессрочный, пока жив Secret: утёк — действует годами. Если без него никак: узкая Role,
ротация пересозданием Secret.

</details>

**A20.** Что делает `automountServiceAccountToken: false` и зачем это нужно?

<details><summary>Ответ</summary>

Не монтировать токен в под. Нужно приложениям, которым API не требуется:
меньше поверхность атаки при компрометации контейнера.

</details>

**A21.** ⭐ Как проверить права другого субъекта, не заводя его kubeconfig?

<details><summary>Ответ</summary>

`kubectl auth can-i VERB RESOURCE --as=system:serviceaccount:NS:NAME`
(и `--as-group` для групп), а также `kubectl auth can-i --list`.

</details>

**A22.** Как прочитать сообщение `Forbidden`? Какие пять фактов в нём есть?

<details><summary>Ответ</summary>

Кто (субъект), какой глагол, какой ресурс, какая API-группа,
какой namespace.

</details>

**A23.** Почему `pods/exec` — опасное право?

<details><summary>Ответ</summary>

`exec` даёт выполнение команд внутри контейнера: чтение смонтированных
секретов и переменных окружения, доступ к сети пода и к его правам.

</details>

**A24.** Почему `secrets: list` опаснее, чем кажется?

<details><summary>Ответ</summary>

Список секретов возвращает и их содержимое — фактически это доступ
ко всем паролям и токенам namespace.

</details>

**A25.** Что такое Pod Security Admission и чем отличается от RBAC?

<details><summary>Ответ</summary>

RBAC регулирует доступ к API; PSA ограничивает, какие поды разрешено
запускать (привилегированность, hostPath, capabilities) на уровне namespace.

</details>

---

### Блок B. «Что произойдёт»

```yaml
# B1
kind: Role
metadata: { namespace: dev }
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list"]
---
kind: RoleBinding
metadata: { namespace: dev }
subjects: [{ kind: ServiceAccount, name: app, namespace: dev }]
roleRef: { kind: Role, name: pod-reader, apiGroup: rbac.authorization.k8s.io }
```
Вопрос: сможет ли SA `app` читать поды в namespace `prod`?

<details><summary>Ответ</summary>

Нет: Role и RoleBinding действуют только в namespace `dev`.

</details>

```yaml
# B2
kind: RoleBinding
metadata: { namespace: dev }
roleRef: { kind: ClusterRole, name: edit }
```
Вопрос: где действуют права?

<details><summary>Ответ</summary>

Только в namespace `dev`: биндинг ограничивает область действия
ClusterRole своим namespace.

</details>

```yaml
# B3
kind: ClusterRoleBinding
roleRef: { kind: Role, name: pod-reader }
```
Вопрос: что ответит API?

<details><summary>Ответ</summary>

Ошибку: ClusterRoleBinding может ссылаться только на ClusterRole.

</details>

```bash
# B4
kubectl auth can-i list secrets -n prod --as=system:serviceaccount:prod:app
# no
```
Вопрос: что нужно добавить, чтобы стало `yes`?

<details><summary>Ответ</summary>

Правило с `resources: ["secrets"]` и глаголом `list` (Role в prod
плюс соответствующий RoleBinding) — и стоит подумать, действительно ли это нужно.

</details>

```yaml
# B5
spec:
  containers: [...]
# serviceAccountName не указан
```
Вопрос: под какими правами приложение обращается к API?

<details><summary>Ответ</summary>

Под использует SA `default` своего namespace, у которого по умолчанию
почти нет прав.

</details>

```bash
# B6
Error from server (Forbidden): deployments.apps is forbidden:
User "system:serviceaccount:ci:deployer" cannot patch resource "deployments"
in API group "apps" in the namespace "prod"
```
Вопрос: какое правило нужно написать?

<details><summary>Ответ</summary>

В namespace `prod`: Role с `apiGroups: ["apps"]`, `resources: ["deployments"]`,
`verbs: ["patch"]` (плюс get/update по необходимости) и RoleBinding на SA `ci:deployer`.

</details>

```yaml
# B7
rules:
  - apiGroups: ["*"]
    resources: ["*"]
    verbs: ["*"]
```
Вопрос: чему это эквивалентно и чем опасно?

<details><summary>Ответ</summary>

Эквивалент `cluster-admin` в пределах области действия биндинга;
опасно тем, что позволяет всё, включая удаление и изменение прав.

</details>

```bash
# B8
kubectl create rolebinding x --clusterrole=view --serviceaccount=dev:app -n dev
kubectl auth can-i get secrets -n dev --as=system:serviceaccount:dev:app
```
Вопрос: что ответит команда и почему?

<details><summary>Ответ</summary>

`no`: роль `view` намеренно не даёт доступа к секретам.

</details>

---

### Блок C. Практика

#### C1. 🔑 Role + RoleBinding для ServiceAccount
1. Создай namespace `rbac-lab` и SA `reader`.
2. Дай ему право читать поды (get, list, watch).
3. Проверь через `kubectl auth can-i --as=...`.
4. Убедись, что читать секреты он не может.

#### C2. 🔑 Проверка изнутри пода
Запусти под с этим SA и обратись к API прямо из контейнера:
```bash
TOKEN=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
curl -sk -H "Authorization: Bearer $TOKEN" \
  https://kubernetes.default.svc/api/v1/namespaces/rbac-lab/pods | head
curl -sk -H "Authorization: Bearer $TOKEN" \
  https://kubernetes.default.svc/api/v1/namespaces/rbac-lab/secrets | head
```
Запиши, что вернул каждый запрос.

<details><summary>Ответ</summary>

Запрос к подам вернёт список, запрос к секретам — ответ 403
с сообщением Forbidden.

</details>

#### C3. ClusterRole + RoleBinding
1. Создай ClusterRole `configmap-reader`.
2. Привяжи её через RoleBinding в двух разных namespace к одному SA.
3. Проверь, что в третьем namespace прав нет.
4. Сформулируй, зачем так делают.

#### C4. Встроенные роли
1. Выдай группе `developers` роль `edit` в `dev` и `view` в `prod`.
2. Проверь: `kubectl auth can-i delete deployments -n prod --as-group=developers --as=alice`.
3. Посмотри `kubectl describe clusterrole view` и найди, есть ли там секреты.

#### C5. 🔑 Права для пайплайна
Собери полный набор для деплоя из CI:
1. SA `deployer` в namespace `prod`.
2. Минимальные права: deployments (get/list/patch/update), pods (get/list),
   pods/log (get), configmaps, services.
3. Долгоживущий токен через Secret.
4. Собери kubeconfig с этим токеном и проверь, что `kubectl get pods -n prod` работает,
   а `kubectl get nodes` — нет.

<details><summary>Ответ</summary>

Проверка успешна, если `kubectl get pods -n prod` работает,
а `kubectl get nodes` возвращает Forbidden — значит, права ограничены namespace.

</details>

#### C6. Ломаем и чиним
1. Убери из роли глагол `patch`.
2. Попробуй `kubectl set image` этим SA.
3. Прочитай сообщение об ошибке и восстанови право по нему.

<details><summary>Ответ</summary>

Ошибка укажет ресурс `deployments`, группу `apps` и глагол `patch` —
ровно то, что нужно вернуть в правило.

</details>

#### C7. can-i --list
```bash
kubectl auth can-i --list -n prod --as=system:serviceaccount:prod:deployer
```
Выпиши таблицу прав и проверь, нет ли лишнего.

#### C8. Опасные права
1. Дай SA право `pods/exec`.
2. Зайди этим SA в под другого приложения и прочитай смонтированный секрет.
3. Сформулируй, почему exec — это фактически права контейнера.

<details><summary>Ответ</summary>

Через exec можно прочитать `/var/run/secrets/...` и переменные окружения
целевого пода, то есть получить его секреты и права.

</details>

#### C9. automountServiceAccountToken
1. Запусти под с `automountServiceAccountToken: false`.
2. Проверь, что каталог с токеном отсутствует.
3. Объясни, зачем это делают для приложений, не работающих с API.

#### C10. Аудит биндингов
```bash
kubectl get clusterrolebinding -o wide | grep cluster-admin
kubectl get rolebinding -A -o wide | head -30
```
Найди, кому выданы административные права. Составь список «кто может всё».

#### C11. Свой контроллер (со звёздочкой)
Напиши под, который раз в 30 секунд читает ConfigMap через API
(с `kubectl` внутри образа или через curl) и печатает значение. Подбери
минимальные права методом «дай меньше — прочитай ошибку — добавь ровно нужное».

#### C12. Pod Security Admission (со звёздочкой)
1. Навесь на namespace метку `pod-security.kubernetes.io/enforce=restricted`.
2. Попробуй запустить под с `privileged: true`.
3. Прочитай отказ и сформулируй разницу между RBAC и PSA.

<details><summary>Ответ</summary>

RBAC отвечает на вопрос «можно ли выполнить операцию в API»,
PSA — «допустим ли такой под в этом namespace».

</details>

---

### Блок D. Инциденты

**D1.** Приложение падает с `Forbidden ... cannot list resource "configmaps"`.
Алгоритм: что прочитать в ошибке и что создать?

<details><summary>Ответ</summary>

Прочитать в ошибке субъект, глагол, ресурс, группу и namespace; создать
Role с этим правилом и RoleBinding на нужный SA (или дополнить существующие).

</details>

**D2.** Разработчик не видит поды в своём namespace, хотя «права выдавали».
Что проверить (три пункта)?

<details><summary>Ответ</summary>

Namespace биндинга, правильность имени субъекта (включая namespace SA),
тип роли и её содержимое; заодно — под каким пользователем он реально ходит
(`kubectl auth whoami`, контекст kubeconfig).

</details>

**D3.** Пайплайн деплоит в prod с правами `cluster-admin`. Чем это плохо
и как исправить без остановки поставки?

<details><summary>Ответ</summary>

Избыточные права: любая ошибка или компрометация CI ведёт к потере
кластера. Исправление: завести отдельный SA с минимальным набором прав
в нужных namespace, проверить `can-i --list`, затем заменить токен в переменных CI.

</details>

**D4.** Сотрудник уволился, а его сертификат продолжает работать. Почему
и что с этим делать?

<details><summary>Ответ</summary>

Сертификаты нельзя отозвать без перевыпуска CA. Правильный путь —
OIDC с централизованным отключением учётной записи; временная мера — удалить
биндинги этого пользователя.

</details>

**D5.** Под неожиданно смог удалить объекты в чужом namespace. Как такое возможно?

<details><summary>Ответ</summary>

Ему выдан ClusterRoleBinding (или RoleBinding в чужом namespace),
либо использован SA с широкими правами, либо права получены через `pods/exec`
в поде с привилегиями.

</details>

**D6.** После обновления кластера перестал работать доступ CI: токен «протух».
Что произошло и как правильно?

<details><summary>Ответ</summary>

С 1.24 токены SA короткоживущие и ротируются; статический токен нужно
создавать явным Secret'ом либо переходить на получение токена
через `kubectl create token` с ограниченным сроком.

</details>

**D7.** Приложение не должно ходить в API, но токен смонтирован.
Чем это опасно и что настроить?

<details><summary>Ответ</summary>

Компрометация контейнера даёт злоумышленнику доступ к API с правами SA.
Настроить `automountServiceAccountToken: false`.

</details>

**D8.** Аудит показал 15 ClusterRoleBinding на `cluster-admin`. План действий.

<details><summary>Ответ</summary>

Составить список владельцев, выяснить обоснование каждого, заменить
на минимальные роли, оставить `cluster-admin` только для экстренного доступа
(и желательно с аудитом и отдельной процедурой получения).

</details>

**D9.** Права выданы через RoleBinding в namespace, а нужен доступ к нодам.
Почему не работает?

<details><summary>Ответ</summary>

Node — ресурс уровня кластера: для него нужны ClusterRole
и ClusterRoleBinding.

</details>

**D10.** Разработчику дали `view` в prod, но он смог прочитать пароли.
Как это могло случиться?

<details><summary>Ответ</summary>

Через `pods/exec` или логи, где печатаются секреты; либо ему дополнительно
выдали права на секреты другим биндингом; либо секреты лежат в ConfigMap.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Что такое RBAC и из чего состоит?

<details><summary>Ответ</summary>

Модель контроля доступа: субъекты (SA, User, Group), права (Role, ClusterRole)
и связи (RoleBinding, ClusterRoleBinding); по умолчанию запрещено всё.

</details>

**2.** Чем Role отличается от ClusterRole?

<details><summary>Ответ</summary>

Областью действия: namespace против всего кластера и ресурсов уровня кластера.

</details>

**3.** Какие комбинации Role/Binding возможны?

<details><summary>Ответ</summary>

RoleBinding+Role, RoleBinding+ClusterRole, ClusterRoleBinding+ClusterRole;
ClusterRoleBinding+Role невозможен.

</details>

**4.** Что такое ServiceAccount и зачем он нужен?

<details><summary>Ответ</summary>

Идентичность для подов и автоматизации; от его имени под обращается к API.

</details>

**5.** Как выдать права поду?

<details><summary>Ответ</summary>

Создать SA, описать Role/ClusterRole, связать биндингом и указать
`serviceAccountName` в спеке пода.

</details>

**6.** Как проверить, есть ли у субъекта право?

<details><summary>Ответ</summary>

`kubectl auth can-i VERB RESOURCE [-n NS] [--as=...]`, а также `can-i --list`.

</details>

**7.** Какие встроенные роли знаешь?

<details><summary>Ответ</summary>

`view`, `edit`, `admin`, `cluster-admin`.

</details>

**8.** Почему нельзя раздавать cluster-admin?

<details><summary>Ответ</summary>

Это полный доступ ко всему кластеру: ошибка или компрометация означает
потерю кластера и всех секретов.

</details>

**9.** Как дать доступ пайплайну к кластеру?

<details><summary>Ответ</summary>

Отдельный ServiceAccount с минимальными правами в нужных namespace,
токен в защищённой переменной CI, доступ только к тому, что нужно для деплоя.

</details>

**10.** Чем Pod Security Admission отличается от RBAC?

<details><summary>Ответ</summary>

PSA ограничивает допустимые параметры подов в namespace, RBAC —
доступ к операциям API.

</details>

---

### 🎯 Чек-лист

- [ ] Понимаю связку субъект → роль → биндинг
- [ ] ⭐ Знаю все четыре комбинации Role/ClusterRole и Binding
- [ ] Создавал SA и выдавал ему минимальные права
- [ ] Проверяю права через `auth can-i --as`
- [ ] Умею восстановить нужное правило из текста ошибки Forbidden
- [ ] Настроил доступ для пайплайна без `cluster-admin`
- [ ] Знаю, почему `pods/exec` и `secrets: list` — опасные права
- [ ] Отключал `automountServiceAccountToken`
- [ ] Провёл аудит: кто в кластере имеет административные права
