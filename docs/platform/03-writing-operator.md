---
title: "03. Свой оператор на Python: kopf и LinkdApp"
description: "Блок → Platform Engineering → тема 03. Вопросы собеса: «Писали ли вы оператор?»,"
---

# 03. Свой оператор на Python: kopf и LinkdApp

> Блок → Platform Engineering → тема 03. Вопросы собеса: *«Писали ли вы оператор?»*,
> *«Как сделать reconcile идемпотентным?»*, *«Что будет, если кто-то удалит Deployment,
> который создал оператор?»*, *«Как оператор получает права и как его деплоят?»*
> **После темы ты умеешь:** написать оператор на kopf для CRD `LinkdApp` из темы 02:
> Deployment + Service + HTTPRoute для Envoy Gateway, owner references через `kopf.adopt`,
> server-side apply, status с conditions и `observedGeneration`, исправление дрейфа
> таймером, ошибки `TemporaryError`/`PermanentError`, finalizers; запустить его локально
> и в кластере с RBAC; покрыть тестами; прочитать reconcile на Go (kubebuilder) и выбрать
> инструмент под задачу.
> Версии — «проверь, сентябрь 2026»: **kopf 1.44.6** (03.06.2026), Python-клиент
> **kubernetes 36.0.3**, стенд `kindest/node:v1.36.4`, Envoy Gateway v1.9.1 (Gateway API v1.6.1).

Опирается на: CRD и паттерн контроллера — [02_crd_operators.md](/platform/02-crd-operators);
Gateway `web` в `infra` — [../Kubernetes/12_ingress.md](/kubernetes/12-ingress) §7;
RBAC — [../Kubernetes/17_rbac.md](/kubernetes/17-rbac); Python, venv, пакеты — [../Python/00_INDEX.md](/python/).

---

## 🗺️ Карта темы

```text
 kubectl apply shortener.yaml (LinkdApp)
        │ watch
        ▼
 ┌─────────────────────── linkd-operator (kopf) ───────────────────────────────┐
 │ on.create / on.update(spec) / on.resume ──┐                                 │
 │ timer каждые 30 с (дрейф, статус) ────────┼──► reconcile(body, spec, patch) │
 │                                           │     1. desired_children(spec)   │
 │ on.delete(optional) — только лог          │     2. kopf.adopt → ownerRefs   │
 │                                           │     3. server-side apply        │
 │ ошибки: TemporaryError → повтор с delay   │     4. статус детей → conditions│
 │         PermanentError → стоп + condition │     5. patch.status (+ observed-│
 └───────────────────────────────────────────┘        Generation)              │
        │ SSA, field manager "linkd-operator"                                   │
        ▼
 Deployment shortener ── Service shortener:80 ── HTTPRoute shortener ──► Gateway infra/web
   (probes /healthz /readyz, size → ресурсы, database → LINKD_DATABASE_URL из Secret)
 удаление LinkdApp → kopf останавливает таймер и снимает свой finalizer → GC удаляет детей
```text
---

## 1. Что строим и как разложен проект

Оператор реализует API из темы 02 §12: команда пишет 10 строк `LinkdApp`, оператор держит
в кластере три объекта и честный статус. Сервис — **linkd 2.0**: порт `8080` (`LINKD_PORT`),
`/healthz` (процесс жив), `/readyz` (база доступна), PostgreSQL через `LINKD_DATABASE_URL`,
без неё — SQLite (`LINKD_DB`).

```text
linkd-operator/
├── linkd_operator.py        # ⚠️ не operator.py — это имя модуля стандартной библиотеки
├── requirements.txt         # kopf==1.44.6, kubernetes==36.0.3, prometheus-client
├── Dockerfile
├── deploy/
│   ├── crd.yaml             # CRD LinkdApp из темы 02 §12
│   ├── rbac.yaml            # ServiceAccount, ClusterRole, ClusterRoleBinding
│   └── operator.yaml        # Deployment оператора
├── examples/shortener.yaml
└── tests/
    ├── test_children.py     # unit: чистая функция spec → манифесты, без кластера
    └── test_e2e.py          # KopfRunner против kind
```text
---

## 2. kopf за 10 минут

kopf сам делает informer, очередь, повторы и хранение прогресса; ты пишешь **обработчики**.

| Декоратор | Когда вызывается | Для чего у нас |
|-----------|------------------|----------------|
| `@kopf.on.create(...)` | Объект появился | Первый reconcile |
| `@kopf.on.update(..., field="spec")` | Изменился spec (status и служебные поля не считаются) | Reconcile после правки |
| `@kopf.on.resume(...)` | Оператор стартовал и нашёл уже существующий объект | Level-triggered: догнать то, что пропустили, пока лежали |
| `@kopf.on.delete(...)` | Объект удаляют | kopf **ставит finalizer**; `optional=True` — без него |
| `@kopf.timer(..., interval=30)` | Периодически, независимо от событий; ⚠️ kopf **ставит finalizer**, чтобы остановить таймер до удаления | Исправление дрейфа и обновление статуса |
| `@kopf.on.event(...)` | Любое событие watch, без учёта прогресса | Реакция на детей (альтернатива таймеру) |
| `@kopf.index(...)`, `@kopf.on.startup()` | Индекс объектов в памяти; один раз при старте | Дети без запросов к API; настройки, клиенты, метрики |

Обработчик получает всё через именованные аргументы: `body`, `spec`, `status`, `meta`,
`name`, `namespace`, `uid`, `patch`, `logger`, для update — `old`, `new`, `diff`. Бери нужное,
остальное — в `**_`.

**Как kopf хранит своё состояние.** Прогресс обработчиков и «последнюю обработанную
конфигурацию» (для `diff`) kopf по умолчанию пишет в аннотации и в `status`. У нас строгая
схема status (тема 02), поэтому всё, чего в ней нет, будет вырезано — настраиваем хранение
**только в аннотациях** со своим префиксом, а статус пишем явно через `patch.status`.
По той же причине **не возвращаем значения** из обработчиков: kopf положил бы их в
`status.&lt;id обработчика&gt;`, и их вырезал бы pruning.

**Ошибки:**

| Что бросить | Что сделает kopf |
|-------------|------------------|
| `kopf.TemporaryError("…", delay=60)` | Повторит через `delay` секунд (по умолчанию 60) |
| `kopf.PermanentError("…")` | Не будет повторять до следующего изменения объекта; для таймера — остановит его навсегда |
| Любое другое исключение | Повтор с `backoff` (настраивается в декораторе или в settings) |
| Параметры декоратора | `retries=`, `backoff=`, `timeout=` — ограничить повторы и время |

---

## 3. ⭐ Полный код оператора

```python
"""linkd-operator: LinkdApp (platform.example.com/v1alpha1) → Deployment + Service + HTTPRoute.

Локально:   kopf run --standalone -n team-a --verbose linkd_operator.py
В кластере: см. Dockerfile (--all-namespaces, --liveness, --log-format=json)
"""
import datetime
import logging
import os

import kopf
from kubernetes import config, dynamic
from kubernetes.client import ApiClient
from kubernetes.dynamic.exceptions import NotFoundError, ResourceNotFoundError
from prometheus_client import Counter, start_http_server

LA = ("platform.example.com", "v1alpha1", "linkdapps")
MANAGER = "linkd-operator"                                   # field manager для server-side apply
PREFIX = "linkd.platform.example.com"
PORT = 8080
GATEWAY = {"name": os.getenv("GATEWAY_NAME", "web"),
           "namespace": os.getenv("GATEWAY_NAMESPACE", "infra"),
           "sectionName": os.getenv("GATEWAY_LISTENER", "http")}
SIZES = {   # команда выбирает size, а не пишет requests/limits руками
    "small":  {"requests": {"cpu": "50m", "memory": "64Mi"}, "limits": {"memory": "128Mi"&#125;&#125;,
    "medium": {"requests": {"cpu": "200m", "memory": "128Mi"}, "limits": {"memory": "256Mi"&#125;&#125;,
    "large":  {"requests": {"cpu": "500m", "memory": "256Mi"}, "limits": {"memory": "512Mi"&#125;&#125;,
}
RECONCILES = Counter("linkd_operator_reconcile_total", "Запуски reconcile", ["result"])
dyn = None


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_):
    global dyn
    try:
        config.load_incluster_config()                       # под в кластере: токен ServiceAccount
    except config.ConfigException:
        config.load_kube_config()                            # локально: ~/.kube/config
    dyn = dynamic.DynamicClient(ApiClient())
    settings.persistence.finalizer = f"{PREFIX}/finalizer"
    settings.persistence.progress_storage = kopf.AnnotationsProgressStorage(prefix=PREFIX)
    settings.persistence.diffbase_storage = kopf.AnnotationsDiffBaseStorage(
        prefix=PREFIX, key="last-handled-configuration")
    settings.posting.level = logging.WARNING                 # в Events объекта — только проблемы
    start_http_server(9090)                                  # /metrics для Prometheus


def labels(name):
    return {"app.kubernetes.io/name": "linkd", "app.kubernetes.io/instance": name,
            "app.kubernetes.io/managed-by": MANAGER}


def desired_children(name, namespace, spec):
    """Чистая функция: spec → манифесты детей. Тестируется без кластера."""
    selector = {"app.kubernetes.io/instance": name}
    env = [{"name": "LINKD_PORT", "value": str(PORT)}, {"name": "LINKD_LOG_FORMAT", "value": "json"}]
    volumes, mounts = [], []
    if spec.get("database"):
        env.append({"name": "LINKD_DATABASE_URL",
                    "valueFrom": {"secretKeyRef": {"name": f"{name}-db", "key": "url"&#125;&#125;})
    else:                                                    # учебный режим: SQLite у каждой реплики своя
        env.append({"name": "LINKD_DB", "value": "/data/linkd.db"})
        volumes = [{"name": "data", "emptyDir": {&#125;&#125;]
        mounts = [{"name": "data", "mountPath": "/data"}]

    def probe(path):
        return {"httpGet": {"path": path, "port": "http"}, "periodSeconds": 10}

    container = {
        "name": "linkd", "image": spec["image"],
        "ports": [{"name": "http", "containerPort": PORT}],
        "env": env, "volumeMounts": mounts, "resources": SIZES[spec.get("size", "small")],
        "livenessProbe": probe("/healthz"), "readinessProbe": probe("/readyz"),
        "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                            "capabilities": {"drop": ["ALL"]&#125;&#125;,
    }
    deployment = {
        "apiVersion": "apps/v1", "kind": "Deployment",
        "metadata": {"name": name, "namespace": namespace, "labels": labels(name)},
        "spec": {"replicas": spec["replicas"], "selector": {"matchLabels": selector},
                 "template": {"metadata": {"labels": labels(name)},
                              "spec": {"securityContext": {"runAsNonRoot": True, "runAsUser": 10001,
                                                           "seccompProfile": {"type": "RuntimeDefault"&#125;&#125;,
                                       "containers": [container], "volumes": volumes&#125;&#125;},
    }
    service = {
        "apiVersion": "v1", "kind": "Service",
        "metadata": {"name": name, "namespace": namespace, "labels": labels(name)},
        "spec": {"selector": selector, "ports": [{"name": "http", "port": 80, "targetPort": "http"}]},
    }
    route = {
        "apiVersion": "gateway.networking.k8s.io/v1", "kind": "HTTPRoute",
        "metadata": {"name": name, "namespace": namespace, "labels": labels(name)},
        "spec": {"parentRefs": [GATEWAY], "hostnames": [spec["host"]],
                 "rules": [{"matches": [{"path": {"type": "PathPrefix", "value": spec.get("path", "/")&#125;&#125;],
                            "backendRefs": [{"name": name, "port": 80}]}]},
    }
    return [deployment, service, route]


def apply(obj, owner):
    """Идемпотентно: server-side apply от одного field manager. Чужой объект не перехватываем."""
    kopf.adopt(obj, owner=owner)                             # ownerReferences + namespace (+ метки владельца)
    meta = obj["metadata"]
    try:
        res = dyn.resources.get(api_version=obj["apiVersion"], kind=obj["kind"])
    except ResourceNotFoundError:
        raise kopf.TemporaryError(f"нет API {obj['apiVersion']}/{obj['kind']}: Gateway API не установлен?", delay=60)
    try:
        current = dyn.get(res, name=meta["name"], namespace=meta["namespace"]).to_dict()
        owners = [ref["uid"] for ref in current["metadata"].get("ownerReferences", [])]
        if owner["metadata"]["uid"] not in owners:
            raise kopf.PermanentError(f"{obj['kind']} {meta['name']} уже существует и не принадлежит этому LinkdApp")
    except NotFoundError:
        pass                                                 # объекта нет — SSA его создаст
    return dyn.server_side_apply(res, body=obj, name=meta["name"], namespace=meta["namespace"],
                                 field_manager=MANAGER, force_conflicts=True).to_dict()


def condition(old, type_, status, reason, message, generation):
    prev = next((c for c in old if c.get("type") == type_), None)
    changed = prev is None or prev.get("status") != status   # время перехода — только при смене статуса
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {"type": type_, "status": status, "reason": reason, "message": message,
            "observedGeneration": generation,
            "lastTransitionTime": now if changed else prev.get("lastTransitionTime", now)}


def reconcile(body, spec, name, namespace, status, meta, patch, logger, **_):
    gen, old = meta["generation"], (status or {}).get("conditions", [])
    try:
        dep, _svc, route = [apply(obj, body) for obj in desired_children(name, namespace, spec)]
    except kopf.PermanentError as e:
        patch.status["conditions"] = [condition(old, "Ready", "False", "NameConflict", str(e), gen)]
        RECONCILES.labels("permanent_error").inc()
        raise
    ready = (dep.get("status") or {}).get("readyReplicas", 0)
    accepted = any(c["type"] == "Accepted" and c["status"] == "True"
                   for p in (route.get("status") or {}).get("parents", []) for c in p.get("conditions", []))
    if ready >= spec["replicas"] and accepted:
        ready_c = ("True", "AllResourcesReady", f"Deployment {ready}/{spec['replicas']}, HTTPRoute Accepted")
    elif ready < spec["replicas"]:
        hint = f"; проверь Secret {name}-db (ключ url)" if spec.get("database") else ""
        ready_c = ("False", "DeploymentNotReady", f"готово {ready}/{spec['replicas']} реплик{hint}")
    else:
        ready_c = ("False", "RouteNotAccepted",
                   f"HTTPRoute не принят Gateway {GATEWAY['namespace']}/{GATEWAY['name']}: "
                   f"есть ли у namespace метка gateway-access=true?")
    for key, value in {
        "observedGeneration": gen,
        "replicas": (dep.get("status") or {}).get("replicas", 0),
        "readyReplicas": ready,
        "selector": f"app.kubernetes.io/instance={name}",
        "url": f"http://{spec['host']}{spec.get('path', '/')}",
        "conditions": [condition(old, "Ready", *ready_c, gen),
                       condition(old, "RouteAccepted", "True" if accepted else "False",
                                 "Accepted" if accepted else "Pending", "по status.parents HTTPRoute", gen)],
    }.items():
        patch.status[key] = value
    RECONCILES.labels("ok").inc()
    logger.debug(f"reconciled: ready={ready}/{spec['replicas']} accepted={accepted}")


@kopf.on.resume(*LA)
@kopf.on.create(*LA)
@kopf.on.update(*LA, field="spec")
def on_change(**kwargs):
    reconcile(**kwargs)


@kopf.timer(*LA, interval=30, initial_delay=10)
def resync(logger, **kwargs):
    """Level-triggered страховка: вернуть удалённое/изменённое руками и обновить статус."""
    try:
        reconcile(logger=logger, **kwargs)
    except kopf.PermanentError as e:                         # таймер не останавливаем — ждём исправления
        logger.warning(f"пропускаю до исправления: {e}")


@kopf.on.delete(*LA, optional=True)          # этому обработчику finalizer не нужен (таймеру выше — нужен)
def on_delete(name, namespace, logger, **_):
    logger.info(f"LinkdApp {namespace}/{name} удалён: детей уберёт garbage collector")
```text
---

## 4. Разбор решений

| Решение | Почему так |
|---------|------------|
| Один `reconcile` на create, update(spec), resume и таймер | ⭐ Level-triggered: всегда сводим к **полному** spec, а не применяем diff. Пропустили событие — догонит resume или таймер |
| `desired_children` — чистая функция | Вся логика «spec → YAML» тестируется `pytest` без кластера |
| **Server-side apply** с `field_manager` и `force_conflicts=True` | Идемпотентно: сотый вызов = первый. Сервер сам считает diff; поля, которые правит кто-то ещё (например, `replicas` от HPA, если убрать его из нашего манифеста), не затираются |
| Проверка владельца до apply | SSA с `force` молча перехватил бы чужой Deployment с тем же именем; вместо этого — `PermanentError` и понятный condition (проверено в kind: `NameConflict` в статусе, чужой Deployment не тронут) |
| `kopf.adopt(obj, owner=body)` | ownerReference с `controller: true` и `blockOwnerDeletion`, namespace родителя; при удалении LinkdApp детей уберёт GC (тема 02 §8) |
| Статус через `patch.status`, список conditions целиком | Мы единственный писатель conditions; `lastTransitionTime` меняется только при смене статуса; `observedGeneration` — в статусе и в каждом условии |
| Таймер 30 с | Дрейф: удалили Deployment руками — вернётся за ≤30 с; статус догоняет готовность подов без отдельного watch |
| `TemporaryError(delay=60)`, если нет API HTTPRoute | Внешняя зависимость ещё не готова — ждать, а не падать |
| `on.delete(optional=True)` | Внешних ресурсов нет → delete-обработчику finalizer не нужен. ⚠️ Но таймер его всё равно требует (проверено в kind: оператор остановлен → LinkdApp висит с `deletionTimestamp`, запустили — удалился) |
| Хранение прогресса в аннотациях, свой finalizer-префикс | Строгая схема status не вырезает служебное; видно, чьи это аннотации |

**Таймер или watch детей?** Альтернатива таймеру — `@kopf.on.event("apps", "v1", "deployments",
labels={"app.kubernetes.io/managed-by": MANAGER})`: реагировать на изменения детей сразу,
найти родителя по ownerReference и обновить его статус. Быстрее и **без finalizer** на LinkdApp,
но больше кода; таймер проще. Цена таймера — finalizer: пока оператор лежит, LinkdApp не удалить
(и namespace с ним). Для платформенного оператора с дежурством это приемлемо; иначе — watch детей.

**Когда нужен настоящий finalizer.** Если `database: true` создаёт базу **вне кластера**
(managed PostgreSQL в облаке через API провайдера), делаем `@kopf.on.delete(*LA)` без
`optional`: kopf поставит finalizer, вызовет обработчик при удалении и снимет finalizer только
после успеха. Упал обработчик — объект висит с `deletionTimestamp` (тема 02 §9). В нашей
платформе базу создаёт LinkdDatabase — namespaced XR Crossplane (тема 07), он сам — ребёнок с ownerReference.

**Про `database: true` в учебной версии.** Оператор не читает Secret (иначе ему нужны
права `get secrets` во **всех** namespace — это доступ ко всем паролям кластера). Он только
ссылается на Secret `&lt;имя&gt;-db` в `secretKeyRef`; нет Secret — поды в `CreateContainerConfigError`,
статус `DeploymentNotReady` с подсказкой.

> ⚠️ `kopf.adopt` копирует **метки владельца** в детей (если у них нет своих с тем же ключом).
> Если на LinkdApp стоит метка отслеживания ArgoCD (`app.kubernetes.io/instance` в режиме
> label-tracking), дети станут «принадлежать» Application и могут попасть под prune. Там, где
> это важно, — `kopf.append_owner_reference(obj, owner=body)` вместо `adopt`.

---

## 5. Запуск: локально и в кластере

**Локально** — оператор работает с твоим kubeconfig, удобно для отладки:

```bash
cd linkd-operator && python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
kubectl apply -f deploy/crd.yaml
kopf run --standalone -n team-a --verbose linkd_operator.py
```text
**В кластере:**

```dockerfile
# Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY linkd_operator.py .
# kopf на старте зовёт getpass.getuser(): UID без записи в /etc/passwd → KeyError и падение.
# Имя «operator» не бери — такая группа в python:3.12-slim уже есть.
RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin kopf
USER 10001
ENTRYPOINT ["kopf", "run", "--standalone", "--all-namespaces", "--log-format=json", \
            "--liveness=http://0.0.0.0:8080/healthz", "/app/linkd_operator.py"]
```text
```yaml
# deploy/rbac.yaml — минимально необходимое
apiVersion: v1
kind: ServiceAccount
metadata: { name: linkd-operator, namespace: platform }
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata: { name: linkd-operator }
rules:   # patch linkdapps — аннотации прогресса и finalizer kopf
  - { apiGroups: [platform.example.com], resources: [linkdapps], verbs: [get, list, watch, patch] }
  - { apiGroups: [platform.example.com], resources: [linkdapps/status], verbs: [get, patch] }
  # SSA = patch (+ create на первом apply); delete не нужен — детей удаляет GC
  - { apiGroups: [apps], resources: [deployments], verbs: [get, create, patch] }
  - { apiGroups: [""], resources: [services], verbs: [get, create, patch] }
  - { apiGroups: [gateway.networking.k8s.io], resources: [httproutes], verbs: [get, create, patch] }
  - { apiGroups: [""], resources: [events], verbs: [create] }                 # Events в объект
  - { apiGroups: [apiextensions.k8s.io], resources: [customresourcedefinitions], verbs: [list, watch] }
  - { apiGroups: [""], resources: [namespaces], verbs: [list, watch] }        # для --all-namespaces
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: { name: linkd-operator }
roleRef: { apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: linkd-operator }
subjects: [{ kind: ServiceAccount, name: linkd-operator, namespace: platform }]
```text
```yaml
# deploy/operator.yaml
apiVersion: apps/v1
kind: Deployment
metadata: { name: linkd-operator, namespace: platform }
spec:
  replicas: 1
  strategy: { type: Recreate }                  # ⭐ никогда два экземпляра одновременно
  selector: { matchLabels: { app: linkd-operator } }
  template:
    metadata: { labels: { app: linkd-operator } }
    spec:
      serviceAccountName: linkd-operator
      containers:
        - name: operator
          image: linkd-operator:0.1.0
          ports: [{ name: metrics, containerPort: 9090 }]
          livenessProbe: { httpGet: { path: /healthz, port: 8080 }, periodSeconds: 20 }
          resources: { requests: { cpu: 50m, memory: 128Mi }, limits: { memory: 256Mi } }
          securityContext: { allowPrivilegeEscalation: false, readOnlyRootFilesystem: true,
                             capabilities: { drop: [ALL] } }
```text
```bash
docker build -t linkd-operator:0.1.0 . && kind load docker-image linkd-operator:0.1.0 --name platform
kubectl create namespace platform
kubectl apply -f deploy/rbac.yaml -f deploy/operator.yaml
kubectl -n platform logs deploy/linkd-operator -f
kubectl auth can-i get secrets -A --as=system:serviceaccount:platform:linkd-operator   # no — и хорошо
```text
**Несколько экземпляров и peering.** В kopf нет классического leader election: есть
**peering** — объекты `ClusterKopfPeering`/`KopfPeering` (`kopf.dev/v1`, CRD ставятся отдельно).
Если peering-объект `default` есть, kopf использует его автоматически; работает экземпляр
с наибольшим `--priority`, остальные ставятся на паузу; при **равных** приоритетах все
предупреждают и замирают. Удобный приём: оператор в кластере с приоритетом 0, а локальный
`kopf run --dev` (приоритет 666) на время отладки забирает работу себе. Без peering —
`--standalone`, одна реплика и `Recreate`: под перезапустится, а reconcile ничего не потеряет.

---

## 6. Логи, метрики, тесты

**Логи.** `logger` в обработчике — логгер конкретного объекта: сообщения уровня из
`settings.posting.level` и выше kopf дублирует в **Events** LinkdApp (`kubectl describe la`).
`--log-format=json` — для Loki. **Метрики.** Встроенных Prometheus-метрик у kopf нет
(проверь) — добавляем `prometheus_client`: счётчик reconcile по результату; алерт на рост
`result="permanent_error"`. **Liveness** — `--liveness` + `@kopf.on.probe` для своих проверок.

**Unit-тест** — без кластера и без kopf-рантайма:
```python
# tests/test_children.py
from linkd_operator import desired_children

SPEC = {"image": "linkd:2.0.0", "replicas": 2, "host": "links.team-a.example.com",
        "path": "/", "database": True, "size": "small"}

def test_database_uses_secret():
    dep, svc, route = desired_children("shortener", "team-a", SPEC)
    env = {e["name"]: e for e in dep["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["LINKD_DATABASE_URL"]["valueFrom"]["secretKeyRef"]["name"] == "shortener-db"
    assert "LINKD_DB" not in env

def test_route_points_to_service():
    _, svc, route = desired_children("shortener", "team-a", SPEC)
    assert route["spec"]["rules"][0]["backendRefs"][0] == {"name": svc["metadata"]["name"], "port": 80}
    assert route["spec"]["hostnames"] == ["links.team-a.example.com"]
```text
**E2E** — `kopf.testing.KopfRunner` запускает оператор в фоне против **текущего** кластера
(kind в CI):
```python
# tests/test_e2e.py
import subprocess, time
from kopf.testing import KopfRunner

def test_creates_children():
    with KopfRunner(["run", "--standalone", "-n", "team-a", "linkd_operator.py"]) as runner:
        subprocess.run("kubectl apply -f examples/shortener.yaml", shell=True, check=True)
        time.sleep(15)
        out = subprocess.run("kubectl -n team-a get deploy,svc,httproute shortener -o name",
                             shell=True, check=True, capture_output=True, text=True).stdout
        subprocess.run("kubectl delete -f examples/shortener.yaml", shell=True, check=True)
    assert runner.exit_code == 0 and runner.exception is None
    assert "deployment.apps/shortener" in out and "httproute" in out
```text
В CI: kind-кластер с `kindest/node:v1.36.4` → Envoy Gateway → CRD → `pytest`.

---

## 7. Как это выглядит на Go: kubebuilder

Отраслевой стандарт — Go: **kubebuilder** (v4.16.0 — 10.09.2026, controller-runtime v0.24,
Kubernetes 1.36, Go 1.26 — проверь) и **Operator SDK** (v1.42.x, надстройка над kubebuilder
плюс OLM, Helm- и Ansible-операторы). Писать не учим — учим **читать**.

```bash
kubebuilder init --domain example.com --repo github.com/me/linkd-operator
kubebuilder create api --group platform --version v1alpha1 --kind LinkdApp   # types + controller
make manifests    # controller-gen: CRD и RBAC из маркеров в комментариях
make install run  # CRD в кластер, контроллер локально
```text
```go
// api/v1alpha1/linkdapp_types.go — схема CRD из Go-структур и маркеров
type LinkdAppSpec struct {
    // +kubebuilder:validation:XValidation:rule="!self.endsWith(':latest')",message="тег :latest запрещён"
    Image string `json:"image"`
    // +kubebuilder:validation:Minimum=1
    // +kubebuilder:default=1
    Replicas int32 `json:"replicas,omitempty"`
    // ... Host, Path, Database, Size; над типом LinkdApp: +kubebuilder:subresource:status, +kubebuilder:printcolumn
}

// internal/controller/linkdapp_controller.go
// +kubebuilder:rbac:groups=platform.example.com,resources=linkdapps,verbs=get;list;watch;patch
// +kubebuilder:rbac:groups=platform.example.com,resources=linkdapps/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch
func (r *LinkdAppReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
    var app platformv1alpha1.LinkdApp
    if err := r.Get(ctx, req.NamespacedName, &app); err != nil {
        return ctrl.Result{}, client.IgnoreNotFound(err)       // удалён — делать нечего
    }
    dep := &appsv1.Deployment{ObjectMeta: metav1.ObjectMeta{Name: app.Name, Namespace: app.Namespace&#125;&#125;
    _, err := controllerutil.CreateOrUpdate(ctx, r.Client, dep, func() error {
        dep.Spec.Replicas = &app.Spec.Replicas                   // «желаемое» внутри mutate-функции
        // ... selector, template, image
        return controllerutil.SetControllerReference(&app, dep, r.Scheme)   // ownerReference
    })
    if err != nil {
        return ctrl.Result{}, err                                // ошибка → повтор с backoff
    }
    meta.SetStatusCondition(&app.Status.Conditions, metav1.Condition{
        Type: "Ready", Status: metav1.ConditionTrue, Reason: "AllResourcesReady",
        ObservedGeneration: app.Generation})
    app.Status.ObservedGeneration = app.Generation
    if err := r.Status().Update(ctx, &app); err != nil {
        return ctrl.Result{}, err
    }
    return ctrl.Result{RequeueAfter: 30 * time.Second}, nil      // как наш таймер
}

func (r *LinkdAppReconciler) SetupWithManager(mgr ctrl.Manager) error {
    return ctrl.NewControllerManagedBy(mgr).
        For(&platformv1alpha1.LinkdApp{}).    // события по LinkdApp
        Owns(&appsv1.Deployment{}).           // события по детям → reconcile владельца
        Complete(r)
}
```text
**Как читать:** `Reconcile` получает только имя (`req`) — всё перечитывает сам;
`CreateOrUpdate` — идемпотентное «создай или приведи»; `SetControllerReference` — наш
`kopf.adopt`; `Owns()` — наш таймер, только событийный; маркеры `+kubebuilder:rbac` →
ClusterRole, `+kubebuilder:validation` → схема CRD. Leader election включается флагом
менеджера, finalizers — `controllerutil.AddFinalizer/RemoveFinalizer`.

---

## 8. Чем писать оператор

| | kopf (Python) | kubebuilder (Go) | Operator SDK | Metacontroller | shell-operator |
|---|---------------|------------------|--------------|----------------|----------------|
| Модель | Обработчики событий + таймеры | Reconcile + informers/кэш controller-runtime | То же + OLM, Helm/Ansible-операторы | Ты пишешь webhook «родитель → желаемые дети» на любом языке, он применяет | Скрипты (bash, Python) по подпискам на события |
| Порог входа | Низкий для питониста | Go, генерация кода | Как kubebuilder | Низкий: HTTP-сервис на чём угодно | Самый низкий |
| Масштаб | Сотни–тысячи объектов, один экземпляр | Тысячи+, шардирование, кэш | Как kubebuilder | Средний | Небольшой |
| Экосистема | Меньше; мало готовых примеров | ⭐ Стандарт: CNPG, cert-manager, Crossplane | Red Hat, OperatorHub | Нишевая | Flant (Deckhouse) |
| Когда брать | Платформенный «клей» у Python-команды, быстрый прототип | Серьёзный оператор надолго, публикация наружу | Нужен OLM/OpenShift | Простые композиции без своего контроллера | Реакция на события без логики состояния |

Версии (проверь, сентябрь 2026): Operator SDK v1.42.x, Metacontroller v4.17.x, shell-operator v1.20.6.

> 💡 Для типовой платформенной композиции («по CR создать 3–5 объектов») сначала проверь,
> не хватит ли **Crossplane Composition** (тема 07) или Helm-чарта через ArgoCD. Свой код —
> когда нужна логика, которую декларативно не выразить.

---

## 🧪 Мини-лаба: оператор LinkdApp в kind

**Подготовка** (стенд блока): kind `platform` на `kindest/node:v1.36.4`, Envoy Gateway v1.9.1,
GatewayClass `eg` и Gateway `web` в `infra` с `allowedRoutes` по метке `gateway-access=true`
([../Kubernetes/12_ingress.md](/kubernetes/12-ingress) §7.2–7.3), CRD из темы 02.

```bash
# образ linkd 2.0: Dockerfile из 04-shipyard + app/ из 09-ledger (как в 12-autopilot);
# тег явный — CRD запрещает :latest
docker build -t linkd:2.0.0 -f &lt;Dockerfile из 04-shipyard&gt; ~/Projects/devops/12-autopilot
kind load docker-image linkd:2.0.0 --name platform
kubectl create namespace team-a && kubectl label namespace team-a gateway-access=true
kopf run --standalone -n team-a --verbose linkd_operator.py      # отдельный терминал
```text
```yaml
# examples/shortener.yaml
apiVersion: platform.example.com/v1alpha1
kind: LinkdApp
metadata: { name: shortener, namespace: team-a }
spec: { image: "linkd:2.0.0", replicas: 2, host: links.team-a.example.com }
```text
```bash
kubectl apply -f examples/shortener.yaml
kubectl -n team-a get la,deploy,svc,httproute          # READY True через ~20–30 с
kubectl -n team-a get deploy shortener -o jsonpath='{.metadata.ownerReferences[0].kind}{"\n"}'
curl -H "Host: links.team-a.example.com" localhost:8888/healthz   # port-forward — §7.6 темы 12
```text
**Шаги проверки:**
1. **Дрейф:** `kubectl -n team-a delete deploy shortener` — через ≤30 с Deployment вернулся
   (таймер). `kubectl -n team-a scale deploy shortener --replicas=5` — вернулось 2.
2. **Update:** `kubectl -n team-a patch la shortener --type=merge -p '{"spec":{"replicas":3&#125;&#125;'` —
   сравни `generation` и `status.observedGeneration` до и после.
3. **Рестарт:** останови оператор (Ctrl+C), поменяй `size: medium`, запусти снова — сработал
   `on.resume`/update, ресурсы пода изменились.
4. **База:** `database: true` без Secret → `Ready=False`, подсказка в message; создай
   `kubectl -n team-a create secret generic shortener-db --from-literal=url=postgresql://…`
   (учебная PostgreSQL — любая из [../Storage/06_db_backup_replication.md](/storage/06-db-backup-replication)).
5. **Конфликт:** создай руками `kubectl -n team-a create deploy blog --image=nginx`, затем LinkdApp
   `blog` → `NameConflict` в статусе, чужой Deployment не тронут.
6. **Удаление:** `kubectl -n team-a delete la shortener` — дети исчезли (GC). Теперь останови
   оператор, создай и удали LinkdApp снова: объект висит с `deletionTimestamp` и finalizer
   `linkd.platform.example.com/finalizer` (его требует таймер); запусти оператор — удалился.
7. **В кластер:** собери образ, примени `deploy/`, проверь `kubectl auth can-i` для SA.

**Проверь себя:** что будет, если запустить локальный `kopf run --standalone` одновременно
с оператором в кластере? Почему мы не читаем Secret базы? Что вернёт reconcile, если
Gateway API ещё не установлен?

---

## 9. Грабли

| Грабля | Что происходит | Как избежать |
|--------|----------------|--------------|
| Файл `operator.py` | Конфликт со стандартным модулем `operator`, странные ошибки импорта | `linkd_operator.py` |
| Логика в `on.create`, а `on.update` «только diff» | Пропущенные события теряются, дрейф не лечится | Один reconcile + resume + таймер |
| Возвращать значения из обработчиков при строгой схеме status | kopf пишет их в `status.&lt;id&gt;`, pruning вырезает, «статус не обновляется» | Явно `patch.status[...]` |
| `create` без проверки существования | 409 AlreadyExists, дубли с `generateName` | Server-side apply с фиксированным именем |
| SSA с `force` без проверки владельца | Оператор перехватил чужой объект с тем же именем | Сверять ownerReferences, иначе `PermanentError` |
| `PermanentError` в таймере | Таймер для объекта остановлен навсегда | Ловить в таймере, писать condition |
| Две реплики без peering | Оба экземпляра применяют и спорят | `replicas: 1` + `Recreate` или peering с приоритетами |
| Оператору `get secrets` во всех namespace | Доступ ко всем паролям кластера | Ссылаться на Secret, а не читать его |
| `kopf.adopt` и метки ArgoCD на CR | Дети попадают в Application и под prune | `append_owner_reference` или аннотационный tracking в ArgoCD |
| Non-optional `on.delete` без нужды; забыли, что таймер/демон = finalizer | Зависшее удаление при упавшем операторе | `optional=True`; дрейф через watch детей, если finalizer недопустим |

---

## 💼 Как это в DevOps

- Свой оператор в платформенной команде — обычно **клей на 200–500 строк**: CR команды →
  стандартные объекты + политики + метки. Python и kopf хватает, пока объектов сотни, а не
  десятки тысяч; публичный или «тяжёлый» оператор пишут на Go.
- На собесе ценят не «написал оператор», а ответы на вопросы: идемпотентность, что при
  рестарте, откуда права, как удалить без зависаний, как тестируете.
- Читать reconcile на Go нужно даже без Go: при инциденте с CloudNativePG или cert-manager
  ответ часто в их контроллере — `Reconcile`, `Owns`, условия статуса.

---

## 📌 Шпаргалка

| Хочу | Как (kopf) |
|------|-----------|
| Реагировать на создание/изменение/рестарт | `@kopf.on.create` + `@kopf.on.update(field="spec")` + `@kopf.on.resume` на одну функцию |
| Лечить дрейф | `@kopf.timer(..., interval=30)` вызывает тот же reconcile |
| Owner reference | `kopf.adopt(obj, owner=body)` |
| Идемпотентно применить | `dyn.server_side_apply(res, body=obj, field_manager="…", force_conflicts=True)` |
| Записать статус | `patch.status["conditions"] = [...]`, плюс `observedGeneration` |
| Подождать внешнее | `raise kopf.TemporaryError("…", delay=60)` |
| Сдаться до исправления | `raise kopf.PermanentError("…")` |
| Без finalizer | `@kopf.on.delete(..., optional=True)` **и** без таймеров/демонов |
| Запуск локально | `kopf run --standalone -n team-a --verbose linkd_operator.py` |
| В кластере | 1 реплика, `Recreate`, `--all-namespaces --liveness=… --log-format=json` |
| Тест | pytest на чистую функцию; `kopf.testing.KopfRunner` против kind |
| Читать Go | `Reconcile(ctx, req)`, `CreateOrUpdate`, `SetControllerReference`, `Owns()`, маркеры |

---

## 🧠 Что запомнить

1. ⭐ Один идемпотентный reconcile на все события + resume + таймер = level-triggered на kopf.
2. `desired_children(spec)` — чистая функция: основная логика тестируется без кластера.
3. ⭐ Server-side apply с одним field manager делает «создай или приведи» идемпотентным;
   владельца проверяй до `force`.
4. `kopf.adopt` ставит ownerReference (и копирует метки владельца) — детей удаляет GC.
5. Статус пишем явно через `patch.status`; conditions с `observedGeneration` и честным
   `lastTransitionTime`; при строгой схеме не возвращаем значения из обработчиков.
6. `TemporaryError` — ждём внешнего; `PermanentError` — нужен человек; в таймере её ловим.
7. ⭐ Finalizer kopf ставит при non-optional `on.delete` **и при любом таймере или демоне**;
   значит, упавший оператор блокирует удаление CR.
8. В кластере: ServiceAccount + минимальная ClusterRole (без чтения Secret), 1 реплика, `Recreate`;
   peering — приоритеты, а не выборы (при равных — все замирают).
9. kopf хранит прогресс в аннотациях/статусе — настрой префикс и хранение под свою схему.
10. Go-оператор читается так: `Reconcile` → `CreateOrUpdate` + `SetControllerReference` →
    `Status().Update` → `RequeueAfter`; `Owns()` — события детей; маркеры → CRD и RBAC.
11. Выбор: kopf — клей и прототип, kubebuilder — серьёзный оператор надолго, Metacontroller
    и shell-operator — простые случаи, Crossplane Composition — если хватает декларатива.

➡️ Дальше: [04_admission_policy.md](/platform/04-admission-policy) · Задачи: 03_writing_operator_tasks.md


---

### Блок A. Теория


**A1.** Какие части контроллера kopf делает за тебя, а что пишешь ты?

<details><summary>Ответ</summary>

kopf: watch и кэш, очередь по объектам, повторы и backoff, хранение прогресса,
finalizers для delete-обработчиков и таймеров, Events, peering, liveness. Ты: обработчики —
что считать желаемым состоянием, как применять и какой статус писать.

</details>

**A2.** ⭐ Зачем вешать один reconcile сразу на `on.create`, `on.update` и `on.resume`?
Что будет, если оставить только `on.create` и `on.update`?

<details><summary>Ответ</summary>

Чтобы reconcile был level-triggered: при любом событии и после рестарта сводить к
полному spec. Без `on.resume` изменения, сделанные пока оператор лежал, не применятся
до следующего изменения объекта.

</details>

**A3.** Что делает `@kopf.on.resume` и когда он срабатывает?

<details><summary>Ответ</summary>

Срабатывает при старте оператора для объектов, которые уже существовали (и обычно
были обработаны раньше). Нужен, чтобы «догнать» то, что изменилось, пока оператор лежал.

</details>

**A4.** Зачем в `@kopf.on.update` параметр `field="spec"`? Сработает ли update-обработчик,
когда оператор сам патчит `status`?

<details><summary>Ответ</summary>

Реагировать только на изменения spec, а не меток и аннотаций. Изменения `status`
kopf не считает «существенными» для update — патч статуса не вызывает update-обработчик.

</details>

**A5.** ⭐ Зачем оператору таймер, если есть обработчики событий? Какая у таймера «цена»?

<details><summary>Ответ</summary>

Лечить дрейф (кто-то удалил или поменял ребёнка) и обновлять статус по готовности
подов без отдельного watch. Цена — kopf ставит finalizer, чтобы остановить таймер до удаления:
пока оператор лежит, CR не удалить; плюс нагрузка на API при тысячах объектов.

</details>

**A6.** Где kopf по умолчанию хранит прогресс обработчиков и «последнюю обработанную
конфигурацию»? Почему мы переводим хранение в аннотации?

<details><summary>Ответ</summary>

По умолчанию — в аннотациях и в `status` (smart-хранилище), diffbase — в аннотации
`kopf.zalando.org/last-handled-configuration`. При строгой схеме status поля kopf в status
вырезаются pruning, поэтому явно выбираем аннотации со своим префиксом.

</details>

**A7.** Почему в нашем операторе обработчики ничего не возвращают?

<details><summary>Ответ</summary>

kopf сохранил бы возвращённое значение в `status.&lt;id обработчика&gt;`, а строгая схема
его вырезала бы. Статус пишем явно через `patch.status`.

</details>

**A8.** ⭐ Что делает `kopf.adopt`? Какой у него побочный эффект, о котором стоит помнить?

<details><summary>Ответ</summary>

Ставит ownerReference (`controller: true`, `blockOwnerDeletion: true`) на текущего
владельца, выставляет namespace владельца и выравнивает имя; побочный эффект — копирует
метки владельца в детей (без `forced` — только отсутствующие ключи). Метки ArgoCD на CR
могут «переехать» на детей.

</details>

**A9.** ⭐ Почему мы применяем детей через server-side apply, а не `create` + `patch`?
Зачем `field_manager` и `force_conflicts`?

<details><summary>Ответ</summary>

SSA идемпотентен: одинаковый запрос при первом и сотом вызове, сервер сам считает
изменения и ведёт владение полями. `field_manager` — имя владельца полей (видно в
`managedFields`); `force_conflicts` — забрать поле, если им владел другой менеджер
(например, после ручного `kubectl edit`), иначе 409 Conflict.

</details>

**A10.** Зачем проверять ownerReferences перед server-side apply?

<details><summary>Ответ</summary>

SSA с `force` без проверки молча «перехватит» чужой объект с тем же именем.
Проверка ownerReferences превращает это в явную ошибку `NameConflict`.

</details>

**A11.** Чем отличаются `TemporaryError`, `PermanentError` и обычное исключение в kopf?

<details><summary>Ответ</summary>

`TemporaryError` — повторить через `delay`; `PermanentError` — не повторять до
следующего изменения объекта (для таймера — остановить навсегда); обычное исключение —
повтор с backoff по настройкам (`retries`, `backoff`, `timeout`).

</details>

**A12.** Почему в таймере мы ловим `PermanentError`, а в change-обработчике — нет?

<details><summary>Ответ</summary>

В таймере `PermanentError` остановит таймер для объекта навсегда — пропадёт лечение
дрейфа даже после устранения конфликта. В change-обработчике она означает «ждём, пока человек
исправит объект», и при следующем изменении обработчик запустится снова.

</details>

**A13.** Как правильно выставлять `lastTransitionTime` у condition?

<details><summary>Ответ</summary>

Менять только при смене `status` условия; если статус тот же — сохранять прежнее
время. Иначе время «прыгает» каждый reconcile и теряет смысл.

</details>

**A14.** Почему `desired_children` — отдельная чистая функция?

<details><summary>Ответ</summary>

Вся логика «spec → манифесты» проверяется pytest без кластера и без kopf-рантайма;
обработчики остаются тонкими.

</details>

**A15.** ⭐ Когда kopf ставит finalizer на объект? Что значит `optional=True` у `on.delete`?

<details><summary>Ответ</summary>

При наличии non-optional `on.delete` и при любом таймере или демоне для этого
ресурса. `optional=True` — delete-обработчик вызывается «по возможности» и сам finalizer
не требует (но таймер его всё равно потребует).

</details>

**A16.** В каком случае оператору LinkdApp нужен «настоящий» delete-обработчик без `optional`?

<details><summary>Ответ</summary>

Когда `database: true` создаёт ресурс вне кластера (managed PostgreSQL через API
облака), который нужно удалить или забэкапить до удаления CR.

</details>

**A17.** Почему оператор не читает Secret базы, а только ссылается на него?

<details><summary>Ответ</summary>

Чтение Secret в любом namespace требует `get secrets` на весь кластер — это доступ
ко всем паролям. Ссылка через `secretKeyRef` не требует прав у оператора.

</details>

**A18.** Какие права нужны оператору и почему нет `delete` на Deployment?

<details><summary>Ответ</summary>

get/list/watch/patch на LinkdApp (patch — аннотации и finalizer), get/patch на
status, get/create/patch на детей (SSA), create на events, list/watch на CRD и namespaces
для kopf. Delete не нужен: детей удаляет GC по ownerReferences.

</details>

**A19.** Почему у Deployment оператора `replicas: 1` и `strategy: Recreate`?

<details><summary>Ответ</summary>

Без peering два экземпляра работают одновременно и конфликтуют. `Recreate`
гарантирует, что при обновлении старый под остановится до старта нового.

</details>

**A20.** Что такое peering в kopf? Чем он отличается от leader election через Lease?
Что будет при равных приоритетах?

<details><summary>Ответ</summary>

Peering — объекты `KopfPeering`/`ClusterKopfPeering`, через которые экземпляры
видят друг друга; работает экземпляр с наибольшим приоритетом, остальные на паузе. Это
не выборы лидера через Lease: при равных приоритетах все экземпляры замирают с предупреждением.

</details>

**A21.** Как запустить оператор локально, чтобы не мешал оператору в кластере?

<details><summary>Ответ</summary>

С peering: оператор в кластере с приоритетом 0, локально `kopf run --dev`
(приоритет 666) — кластерный встаёт на паузу. Без peering — остановить кластерный
(`scale --replicas=0`) или работать в отдельном namespace/кластере.

</details>

**A22.** Как тестировать оператор: что проверяют unit-тесты, что — e2e через `KopfRunner`?

<details><summary>Ответ</summary>

Unit — чистые функции (`desired_children`, `condition`): ресурсы, env, маршруты.
E2E — `KopfRunner` запускает оператор против текущего кластера (kind в CI), тест
применяет CR и проверяет детей, статус, удаление.

</details>

**A23.** ⭐ Прочитай reconcile на Go: что делают `r.Get` + `IgnoreNotFound`,
`controllerutil.CreateOrUpdate`, `SetControllerReference`, `Status().Update`, `RequeueAfter`?

<details><summary>Ответ</summary>

`r.Get` читает объект по имени; `IgnoreNotFound` — если удалён, ошибки нет, делать
нечего. `CreateOrUpdate` читает ребёнка, вызывает mutate-функцию с желаемыми полями и
создаёт или обновляет — идемпотентно. `SetControllerReference` — ownerReference (аналог
`kopf.adopt`). `Status().Update` пишет status через subresource. `RequeueAfter` — вернуться
через время (аналог таймера).

</details>

**A24.** Что делают `For()` и `Owns()` в `SetupWithManager`? Какой аналог в нашем kopf-операторе?

<details><summary>Ответ</summary>

`For()` — основной тип, события по нему ставят его в очередь; `Owns()` — события
по детям ставят в очередь владельца по ownerReference. В нашем kopf-операторе аналог
`Owns()` — таймер (или `on.event` по Deployment с поиском родителя).

</details>

**A25.** Как в kubebuilder получаются CRD и RBAC? Что такое маркеры?

<details><summary>Ответ</summary>

controller-gen читает маркеры-комментарии (`+kubebuilder:validation`,
`+kubebuilder:subresource:status`, `+kubebuilder:rbac`) и генерирует CRD и ClusterRole
командой `make manifests`.

</details>

**A26.** Когда брать kopf, когда kubebuilder, когда Metacontroller, shell-operator или
Crossplane Composition?

<details><summary>Ответ</summary>

kopf — платформенный клей и прототип у Python-команды; kubebuilder/Operator SDK —
серьёзный долгоживущий оператор, большой масштаб, публикация; Metacontroller — простая
композиция через webhook на любом языке; shell-operator — реакция на события скриптом;
Crossplane Composition — если композицию можно описать декларативно.

</details>

---

### Блок B. «Что произойдёт»


```text:no-line-numbers
# B1
```text
```text:no-line-numbers
@kopf.on.create("platform.example.com", "v1alpha1", "linkdapps")
```text
```text:no-line-numbers
def create(spec, name, namespace, **_):
```text
```text:no-line-numbers
    apps.create_namespaced_deployment(namespace, build(name, spec))
```text
Вопрос: что будет при рестарте оператора посреди обработки? А при повторном событии?

```text:no-line-numbers
# B2 — строгая схема status из темы 02
```text
```text:no-line-numbers
@kopf.on.create(*LA)
```text
```text:no-line-numbers
def create(**_):
```text
```text:no-line-numbers
    return {"url": "http://links.example.com/"}
```text
Вопрос: где окажется `url`?

```text:no-line-numbers
# B3 — оператор остановлен (kubectl scale deploy linkd-operator --replicas=0)
```text
```text:no-line-numbers
kubectl -n team-a delete la shortener
```text
Вопрос: что увидишь? Что изменится после запуска оператора?

```text:no-line-numbers
# B4 — в namespace уже есть Deployment "blog" команды (без ownerReferences)
```text
```text:no-line-numbers
kubectl apply -f linkdapp-blog.yaml      # LinkdApp с именем blog
```text
Вопрос: что сделает наш оператор? А версия без проверки владельца (SSA с `force`)?

```text:no-line-numbers
# B5 — кто-то выполнил
```text
```text:no-line-numbers
kubectl -n team-a scale deploy shortener --replicas=5
```text
Вопрос: что будет через минуту? А после `kubectl -n team-a scale la shortener --replicas=5`?

```text:no-line-numbers
# B6 — Gateway API CRD в кластере не установлены
```text
```text:no-line-numbers
kubectl apply -f shortener.yaml
```text
Вопрос: что будет с LinkdApp и логами оператора?

```text:no-line-numbers
# B7 — две реплики оператора, peering-объект default есть, у обеих --priority=0
```text
Вопрос: кто работает?

```text:no-line-numbers
# B8
```text
```text:no-line-numbers
@kopf.timer(*LA, interval=30)
```text
```text:no-line-numbers
def resync(**kwargs):
```text
```text:no-line-numbers
    reconcile(**kwargs)          # без try/except
```text
```text:no-line-numbers
# у объекта NameConflict → reconcile бросает PermanentError
```text
Вопрос: что станет с таймером для этого объекта, когда конфликт устранят?

```text:no-line-numbers
# B9 — на LinkdApp есть метка app.kubernetes.io/instance=team-a-apps (ArgoCD label tracking)
```text
Вопрос: чем это может обернуться для детей?

```text:no-line-numbers
# B10 — локально запущен kopf run --standalone, в кластере работает тот же оператор
```text
Вопрос: что будет?

---

### Блок C. Практика


### C1. 🔑 Оператор в kind
Собери проект по §1, запусти оператор локально (`kopf run --standalone -n team-a`),
создай `shortener`. Покажи: три ребёнка с ownerReference, `kubectl get la` с READY и URL,
`generation == observedGeneration`, curl через Envoy Gateway.

### C2. 🔑 Дрейф и update
Удали Deployment руками, поменяй replicas у Deployment руками, поменяй `spec.size` у LinkdApp.
Для каждого случая запиши, через сколько секунд и каким обработчиком (update или таймер)
состояние вернулось. Подсказка: `--verbose` в логах показывает имя обработчика.

### C3. Рестарт и resume
Останови оператор, поменяй `spec.replicas`, запусти снова. Найди в логах, какой обработчик
сработал первым. Поменяй что-то при работающем операторе и сравни.

### C4. 🔑 Finalizer таймера
Останови оператор, удали LinkdApp. Запиши `deletionTimestamp` и `finalizers`. Запусти
оператор — объект удалился? Затем переделай оператор: убери таймер, добавь реакцию на
удаление детей через `@kopf.on.event` (или `@kopf.on.delete` на Deployment с фильтром по
метке `managed-by`) — пропал ли finalizer у новых объектов?

### C5. Status для Gateway
Сними с namespace метку `gateway-access`. Какой condition и message покажет LinkdApp?
Верни метку. Сколько ждать, пока `Ready` станет `True`, и почему?

### C6. База
Создай LinkdApp с `database: true` без Secret. Опиши, что видно в статусе, в `kubectl get pods`
и в Events. Подними учебную PostgreSQL, создай Secret `shortener-db` с ключом `url` и проверь,
что поды стали Ready, а `/readyz` отвечает 200.

### C7. 🔑 В кластер с RBAC
Собери образ, загрузи в kind, примени `deploy/`. Проверь `kubectl auth can-i` для SA:
`get secrets -A` (должно быть no), `patch linkdapps/status` (yes), `delete deployments` (no).
Убери из ClusterRole правило на `events` — что изменится в логах?

### C8. Метрики
Сделай `port-forward` на 9090 и посмотри `linkd_operator_reconcile_total`. Спровоцируй
`NameConflict` и найди рост `result="permanent_error"`. Напиши PromQL-алерт на это.

### C9. Тесты
Добавь unit-тест: при `size: large` у контейнера `limits.memory == 512Mi`; при `path: /api`
HTTPRoute матчит `PathPrefix /api`. Запусти e2e-тест из конспекта против kind.

### C10. Новое поле (со звёздочкой)
Добавь в CRD и оператор поле `spec.env` (map строк, запрет `LINKD_DATABASE_URL` CEL-правилом
из задач темы 02). Прокинь его в контейнер. Что произойдёт с уже созданными LinkdApp после
обновления CRD и оператора?

### C11. Прочитай Go
Открой контроллер cert-manager или CloudNativePG на GitHub, найди функцию `Reconcile` и
`SetupWithManager`. Выпиши: какие типы в `For`/`Owns`, где ставятся conditions, есть ли
`RequeueAfter`, как обрабатывается удаление (finalizer).

---

### Блок D. Инциденты


**D1.** Оператор в `CrashLoopBackOff`, в логах `403 Forbidden ... customresourcedefinitions`.
Что не так?

<details><summary>Ответ</summary>

В ClusterRole нет `list/watch` на `customresourcedefinitions` — kopf их сканирует
при старте. Добавить правило.

</details>

**D2.** После обновления оператора все LinkdApp показывают `Ready=False`, а поды работают.
В статусе старый `observedGeneration`. Где искать?

<details><summary>Ответ</summary>

Оператор не может записать status: нет `patch` на `linkdapps/status`, схема
отвергает поле (новый код пишет поле, которого нет в CRD — pruning), или обработчики падают.
Смотреть логи оператора, Events LinkdApp, `kubectl auth can-i patch linkdapps/status`.

</details>

**D3.** Команда удалила namespace, и он третий час в `Terminating`. Оператор LinkdApp
в это время обновлялся и был недоступен. Что произошло и как восстановить?

<details><summary>Ответ</summary>

LinkdApp с finalizer (таймер) не удалились без оператора → namespace ждёт. Поднять
оператор — он снимет finalizer. Если оператор не поднять — снять finalizer вручную
(`kubectl patch --type=json … remove /metadata/finalizers`), убедившись, что внешних
ресурсов нет.

</details>

**D4.** Два Deployment одного сервиса постоянно «перетягивают» `replicas`: оператор ставит 2,
что-то ставит 6. Гипотезы и решение?

<details><summary>Ответ</summary>

Два менеджера одного поля: HPA, второй оператор, ArgoCD или скрипт. С HPA — убрать
`replicas` из манифеста оператора (SSA не будет им владеть) или повесить HPA на LinkdApp
через scale subresource. Смотреть `managedFields`.

</details>

**D5.** Оператор медленно реагирует: изменения применяются через 1–2 минуты, в логах
много `Timer 'resync' succeeded`. Объектов 3000. Что улучшить?

<details><summary>Ответ</summary>

Таймер на 3000 объектов каждые 30 с — постоянный поток запросов. Увеличить
`interval`, добавить `idle`, реагировать на детей через `on.event`/index вместо опроса,
лимит параллельности (`settings.batching`), при таком масштабе — подумать о Go.

</details>

**D6.** После обновления kopf объекты получили второй finalizer и аннотации с другим префиксом.
Что случилось и чем это опасно?

<details><summary>Ответ</summary>

Изменились настройки хранения/finalizer (дефолтный префикс вместо своего или наоборот).
Старый finalizer никто не снимет → зависшее удаление. Мигрировать: снять старые finalizer
и аннотации скриптом, фиксировать `settings.persistence.*` явно.

</details>

**D7.** Разработчик запустил у себя `kopf run` против общего dev-кластера «на минутку»,
и у всех команд пересоздались Deployment с другими ресурсами. Как не допустить?

<details><summary>Ответ</summary>

Два оператора разных версий: локальный применил свой код. Защита: peering с
приоритетами и `--dev` локально, RBAC — разработчикам нельзя в общие CR операторские права,
отдельный dev-кластер или namespace для отладки.

</details>

---

### Блок E. Вопросы с собеседования


**1.** ⭐ Расскажите, как устроен ваш оператор: какие события, что создаёт, как пишет статус.

<details><summary>Ответ</summary>

LinkdApp → create/update/resume + таймер → SSA детей с ownerReference → status
   с conditions и observedGeneration; дрейф лечит таймер.

</details>

**2.** Как вы обеспечили идемпотентность?

<details><summary>Ответ</summary>

Детерминированные имена, SSA с одним field manager, reconcile по полному spec, проверка
   владельца.

</details>

**3.** ⭐ Что будет, если оператор упадёт посреди работы? А если его не будет час?

<details><summary>Ответ</summary>

Упал — перезапустится, resume и таймер догонят. Час без него — ресурсы работают, изменения
   и удаления CR ждут (finalizer), статус устаревает.

</details>

**4.** Как оператор узнаёт об изменениях дочерних объектов?

<details><summary>Ответ</summary>

Таймер и/или watch детей (`on.event`, index); в Go — `Owns()`.

</details>

**5.** Какие права у оператора и как вы их минимизировали?

<details><summary>Ответ</summary>

ClusterRole только на свои типы и детей, без delete и без чтения Secret; проверка
   `kubectl auth can-i`.

</details>

**6.** Как вы тестируете оператор?

<details><summary>Ответ</summary>

pytest на чистые функции, e2e через `KopfRunner` в kind в CI.

</details>

**7.** Почему Python, а не Go? Когда бы вы выбрали Go?

<details><summary>Ответ</summary>

Команда пишет на Python, оператор — клей на сотни строк; Go — для масштаба, экосистемы,
   публичного оператора.

</details>

**8.** ⭐ Объясните по шагам типичный `Reconcile` на controller-runtime.

<details><summary>Ответ</summary>

Get (IgnoreNotFound) → finalizer при необходимости → CreateOrUpdate детей
   с SetControllerReference → статус детей → SetStatusCondition + ObservedGeneration →
   Status().Update → Result/RequeueAfter или ошибка для повтора.

</details>

**9.** Как запустить две реплики оператора безопасно?

<details><summary>Ответ</summary>

Peering с разными приоритетами (kopf) или leader election через Lease (controller-runtime).

</details>

**10.** Чем свой оператор хуже Helm-чарта или Crossplane Composition?

<details><summary>Ответ</summary>

Больше кода, свой жизненный цикл, дежурство, finalizers; Helm и Composition декларативны
    и не требуют своего процесса.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Написал оператор на kopf: create/update/resume + таймер → один reconcile
- [ ] Применяю детей через server-side apply и проверяю владельца
- [ ] Пишу status с conditions и `observedGeneration`
- [ ] ⭐ Знаю, когда kopf ставит finalizer, и видел зависшее удаление при остановленном операторе
- [ ] Различаю `TemporaryError` и `PermanentError`
- [ ] Запустил оператор в кластере с минимальной ClusterRole
- [ ] Покрыл оператор unit- и e2e-тестами
- [ ] ⭐ Читаю `Reconcile` на controller-runtime
- [ ] Выбираю инструмент: kopf, kubebuilder, Metacontroller, shell-operator, Composition
