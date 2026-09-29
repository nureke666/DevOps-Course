---
title: "04. Admission и политики: ограждения, а не шлагбаумы"
description: "Блок → Platform Engineering → тема 04. Вопросы собеса: «Чем ValidatingAdmissionPolicy"
---

# 04. Admission и политики: ограждения, а не шлагбаумы

> Блок → Platform Engineering → тема 04. Вопросы собеса: *«Чем ValidatingAdmissionPolicy
> отличается от вебхука?»*, *«Что будет, если admission webhook упадёт?»*, *«Как раскатить
> политику, не сломав команды?»*, *«Kyverno или Gatekeeper?»*
> **После темы ты умеешь:** провести запрос по цепочке admission; писать
> ValidatingAdmissionPolicy на CEL с параметрами (limits, домен команды в HTTPRoute) и
> MutatingAdmissionPolicy; написать validating + mutating webhook на Python (FastAPI,
> AdmissionReview v1, JSONPatch, TLS); настроить `failurePolicy`, `timeoutSeconds`,
> селекторы; поднять кластер, который «положил» вебхук; использовать Kyverno как платформа
> (validate, mutate, generate, отчёты, Audit → Deny); выбрать инструмент и писать сообщения,
> по которым разработчик сам исправит ошибку.
> Всё YAML и код темы проверены в kind (сентябрь 2026). Версии — «проверь, сентябрь 2026»:
> VAP — GA 1.30, MAP — GA 1.36, **Kyverno 1.19.1** (чарт 3.9.1), FastAPI 0.141, uvicorn 0.54.

Со стороны **безопасности** (PSA, выбор VAP/Kyverno/Gatekeeper, `:latest`, подписи, Falco) —
[../Security/06_k8s_security.md](/security/06-k8s-security) §2, §5–7. Здесь — со стороны **платформы**:
как ограждения помогают командам ехать по golden path ([01_platform_engineering.md](/platform/01-platform-engineering) §3).

---

## 🗺️ Карта темы

```text
 kubectl apply ─► authn ─► authz (RBAC) ─► [defaulting схемы]
                                              │
             ┌────────────────────────────────▼───────────────────────────────┐
             │ MUTATING: MutatingAdmissionPolicy (CEL, §3) + mutating webhooks │ по очереди,
             │   Kyverno MutatingPolicy, наш /mutate (метки, дефолты)          │ reinvocation
             └────────────────────────────────┬───────────────────────────────┘
                                   валидация схемы (+ CEL в CRD, тема 02)
             ┌────────────────────────────────▼───────────────────────────────┐
             │ VALIDATING: VAP (CEL, §2) + validating webhooks                 │ параллельно
             │   require-limits, домен HTTPRoute, Kyverno ValidatingPolicy,    │
             │   наш /validate (host не занят — нужен внешний контекст)        │
             └────────────────────────────────┬───────────────────────────────┘
                                             etcd ──► Kyverno GeneratingPolicy (фоном):
                                                      NetworkPolicy, ResourceQuota в namespace
 отказ ─► сообщение: ЧТО не так + КАК исправить + ССЫЛКА на доки (§8)
```text
---

## 1. Цепочка admission: что важно платформе

Путь запроса через API-сервер — [../Kubernetes/02_architecture.md](/kubernetes/02-architecture) §1.1.
Для платформенного инженера важны пять фактов:

| Факт | Следствие |
|------|-----------|
| **Дефолты схемы** проставляются **до** admission | Под с одними `limits` приходит в политику уже с `requests = limits` — проверено: условие «нет requests» не сработало |
| Mutating идёт **до** validating | Дефолт, проставленный мутацией, проходит валидацию и PSA |
| Mutating — последовательно, validating — параллельно | Порядок мутаций важен (`reinvocationPolicy: IfNeeded`), порядок валидаций — нет |
| Валидация по **любому** отказу = отказ всего запроса | Одна сломанная политика блокирует деплой, даже если остальные «за» |
| Вебхуки **не вызываются** для объектов `ValidatingWebhookConfiguration`/`MutatingWebhookConfiguration` и политик VAP/MAP | ⭐ Сломанный вебхук всегда можно удалить — на этом держится восстановление (§5). Проверено: мёртвый вебхук на `admissionregistration.k8s.io/*` не помешал ни VAP, ни патчу самого себя |

Корректность **своего** API — в CRD (тема 02); правила организации — VAP/MAP, Kyverno
или свой webhook, выбор — в §7.

---

## 2. ValidatingAdmissionPolicy (GA 1.30)

Три объекта: **политика** (что проверять), **binding** (где и как строго), **параметры**
(необязательно: ConfigMap или свой CRD). Внутри CEL доступны `object`, `oldObject`, `request`,
`params`, ⭐ `namespaceObject` (namespace объекта с его метками), `authorizer`, `variables`.

**Пример 1 — limits у всех контейнеров, и у подов, и у контроллеров.** Отказ на Deployment
разработчик увидит сразу в `kubectl apply`; отказ только на Pod — лишь в Events ReplicaSet.

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata: { name: require-limits }
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
      - { apiGroups: [""], apiVersions: [v1], operations: [CREATE, UPDATE], resources: [pods] }
      - { apiGroups: [apps], apiVersions: [v1], operations: [CREATE, UPDATE],
          resources: [deployments, statefulsets, daemonsets] }
  variables:
    - name: containers          # у пода — spec.containers, у контроллеров — spec.template.spec.containers
      expression: "has(object.spec.template) ? object.spec.template.spec.containers : object.spec.containers"
    - name: noLimits
      expression: >-
        variables.containers.filter(c, !has(c.resources) || !has(c.resources.limits) ||
          !('memory' in c.resources.limits)).map(c, c.name)
  validations:
    - expression: "size(variables.noLimits) == 0"
      messageExpression: >-
        object.kind + ' ' + object.metadata.name + ': у контейнеров ' + variables.noLimits.join(', ') +
        ' нет resources.limits.memory. Пример и дефолты: https://platform.example.com/docs/resources'
      reason: Invalid
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata: { name: require-limits }
spec:
  policyName: require-limits
  validationActions: [Deny]            # раскатка: [Warn, Audit] → [Deny]; Deny и Warn вместе нельзя
  matchResources:
    namespaceSelector:                 # только namespace команд — kube-system и платформа не трогаем
      matchExpressions: [{ key: platform.example.com/team, operator: Exists }]
```text
```text
$ kubectl -n team-a create deployment nolim --image=nginx:1.27-alpine
error: failed to create deployment: deployments.apps "nolim" is forbidden: ValidatingAdmissionPolicy
'require-limits' with binding 'require-limits' denied request: Deployment nolim: у контейнеров nginx
нет resources.limits.memory. Пример и дефолты: https://platform.example.com/docs/resources
```text
**Пример 2 — `:latest` запрещён** — готовая политика в [../Security/06_k8s_security.md](/security/06-k8s-security) §5.

**Пример 3 — HTTPRoute только в домене своей команды (binding с параметрами).** Домены —
в ConfigMap **платформы** (в namespace команды его нельзя: команда сама себе поменяла бы домен),
команда — из метки namespace, которую ставит платформа.

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata: { name: route-team-domain }
spec:
  failurePolicy: Fail
  paramKind: { apiVersion: v1, kind: ConfigMap }
  matchConstraints:
    resourceRules:
      - { apiGroups: [gateway.networking.k8s.io], apiVersions: [v1], operations: [CREATE, UPDATE], resources: [httproutes] }
  variables:
    - name: team
      expression: "namespaceObject.metadata.?labels[?'platform.example.com/team'].orValue('')"
    - name: domain
      expression: "variables.team in params.data ? params.data[variables.team] : ''"
  validations:
    - expression: "variables.domain != ''"
      messageExpression: >-
        'для команды "' + variables.team + '" не задан домен в ConfigMap platform/route-domains — обратитесь в #platform'
    # без hostnames маршрут перехватывает ВСЕ домены listener'а — такое запрещаем явно
    - expression: "has(object.spec.hostnames) && size(object.spec.hostnames) > 0"
      message: "укажи spec.hostnames: маршрут без имён забирает все домены Gateway"
    - expression: "!has(object.spec.hostnames) || object.spec.hostnames.all(h, h == variables.domain || h.endsWith('.' + variables.domain))"
      messageExpression: >-
        'hostnames ' + object.spec.hostnames.join(', ') + ' вне домена команды ' + variables.domain +
        '. Как выбрать имя: https://platform.example.com/docs/routes'
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata: { name: route-team-domain }
spec:
  policyName: route-team-domain
  validationActions: [Deny]
  paramRef: { name: route-domains, namespace: platform, parameterNotFoundAction: Deny }
  matchResources:
    namespaceSelector:
      matchExpressions: [{ key: platform.example.com/team, operator: Exists }]
---
apiVersion: v1
kind: ConfigMap
metadata: { name: route-domains, namespace: platform }
data: { team-a: team-a.example.com, team-b: team-b.example.com }
```text
HTTPRoute от LinkdApp (тема 03) проверяется тем же правилом: оператор создаёт маршрут
в namespace команды, и чужой домен в `spec.host` будет отклонён уже на детях.

| Нюанс VAP | Что знать |
|-----------|-----------|
| Без binding | Политика ничего не делает |
| `failurePolicy` | Что делать при **ошибке вычисления** (нет поля, ошибка типов, нет параметра): `Fail` по умолчанию |
| `parameterNotFoundAction` | `Deny` или `Allow`, если параметр не найден — обязателен в `paramRef` |
| `status.typeChecking` | API-сервер проверяет типы выражений против схемы и пишет предупреждения сюда |
| `auditAnnotations` | Добавить в аудит-лог данные (например, число реплик) |
| Проверка | `kubectl apply --dry-run=server` — политика отработает без записи |

---

## 3. MutatingAdmissionPolicy (GA 1.36)

Мутации на CEL **внутри API-сервера**, без вебхука: alpha в 1.32, beta в 1.34–1.35 (нужны были
feature gate и runtime-config), **GA и включены по умолчанию в 1.36** (`admissionregistration.k8s.io/v1`,
проверь, сентябрь 2026). На нашем стенде 1.36 работает без флагов.

Пример — проставить на Deployment метку команды из namespace (для FinOps-отчётов и каталога):

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: MutatingAdmissionPolicy
metadata: { name: team-label }
spec:
  failurePolicy: Fail
  reinvocationPolicy: IfNeeded           # вызвать снова, если позже объект поменяла другая мутация
  matchConstraints:
    resourceRules:
      - { apiGroups: [apps], apiVersions: [v1], operations: [CREATE, UPDATE], resources: [deployments] }
  mutations:
    - patchType: ApplyConfiguration       # «кусок объекта», сливается как server-side apply
      applyConfiguration:
        expression: >-
          Object{ metadata: Object.metadata{ labels: {
            "platform.example.com/team": namespaceObject.metadata.labels["platform.example.com/team"] } } }
---
apiVersion: admissionregistration.k8s.io/v1
kind: MutatingAdmissionPolicyBinding
metadata: { name: team-label }
spec:
  policyName: team-label
  matchResources:
    namespaceSelector:
      matchExpressions: [{ key: platform.example.com/team, operator: Exists }]
```text
| Нюанс MAP | Что знать |
|-----------|-----------|
| `patchType` | `ApplyConfiguration` — слияние как SSA (удобно для полей и map); `JSONPatch` — точечные операции над списками |
| ⚠️ `namespaceObject` в `matchConditions` | Недоступен (проверено: ошибка `no such key: metadata`). Фильтр по namespace — в binding (`namespaceSelector`) или в `variables` |
| ⚠️ HTTPRoute без `hostnames` | Забирает все домены listener'а. Фильтр `has(object.spec.hostnames)` в `matchConditions` такой маршрут просто пропускает мимо проверки — запрещай его явно в `validations` (проверено в проекте 20-foundry) |
| Идемпотентность | Мутация может вызываться повторно (reinvocation) — результат должен быть тем же |
| Против вебхука | Нет пода, TLS и сетевого вызова — нечему «упасть»; но только CEL и только данные запроса |

---

## 4. Свой webhook на Python (FastAPI)

Когда VAP/MAP и Kyverno **мало**: нужен внешний контекст (другие объекты кластера, реестр,
CMDB, квоты в биллинге) или сложная логика. Пример: `host` у LinkdApp должен быть **уникален
во всём кластере** — VAP видит только текущий объект и не может перечислить другие.

**AdmissionReview v1:** API-сервер шлёт POST с `request` (`uid`, `operation`, `userInfo`,
`namespace`, `object`, `oldObject`, `dryRun`), ждёт `response` с тем же `uid`, `allowed`,
при отказе — `status.message`, при мутации — `patchType: JSONPatch` и `patch` в **base64**,
по желанию — `warnings` (kubectl покажет `Warning: …`).

```python
"""linkd-webhook: mutating + validating admission webhook для LinkdApp на FastAPI.

Запуск: uvicorn webhook:app --host 0.0.0.0 --port 8443 \
          --ssl-keyfile /tls/tls.key --ssl-certfile /tls/tls.crt
"""
import base64
import json
import re

from fastapi import FastAPI
from kubernetes import client, config

app = FastAPI()
DOCS = "https://platform.example.com/docs/linkdapp"
_api = None


def api() -> client.CustomObjectsApi:
    global _api
    if _api is None:
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        _api = client.CustomObjectsApi()
    return _api


def review(req: dict, allowed: bool, message: str = "", patch: list | None = None,
           warnings: list | None = None) -> dict:
    """Ответ AdmissionReview v1: uid из запроса обязателен."""
    resp: dict = {"uid": req["uid"], "allowed": allowed}
    if not allowed:
        resp["status"] = {"code": 403, "message": message}
    if patch:
        resp["patchType"] = "JSONPatch"
        resp["patch"] = base64.b64encode(json.dumps(patch).encode()).decode()
    if warnings:
        resp["warnings"] = warnings                    # kubectl покажет «Warning: …»
    return {"apiVersion": "admission.k8s.io/v1", "kind": "AdmissionReview", "response": resp}


def pointer(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")  # JSON Pointer: «/» в ключе → «~1»


@app.post("/mutate")
def mutate(body: dict) -> dict:
    req = body["request"]
    meta = req["object"]["metadata"]
    user = re.sub(r"[^A-Za-z0-9_.-]", "_", req["userInfo"]["username"])[:63].strip("_.-")
    wanted = {"app.kubernetes.io/part-of": "linkd-platform",
              "platform.example.com/created-by": user or "unknown"}
    patch = [] if "labels" in meta else [{"op": "add", "path": "/metadata/labels", "value": {&#125;&#125;]
    for key, value in wanted.items():
        if meta.get("labels", {}).get(key) != value:
            patch.append({"op": "add", "path": f"/metadata/labels/{pointer(key)}", "value": value})
    return review(req, True, patch=patch)


@app.post("/validate")
def validate(body: dict) -> dict:
    req = body["request"]
    obj = req["object"]
    host, ns, name = obj["spec"]["host"], req["namespace"], obj["metadata"]["name"]
    # внешнее состояние — то, чего нет у VAP: не занят ли host другим LinkdApp в любом namespace
    items = api().list_cluster_custom_object("platform.example.com", "v1alpha1", "linkdapps",
                                             _request_timeout=2)["items"]
    taken = [f'{i["metadata"]["namespace"]}/{i["metadata"]["name"]}' for i in items
             if i["spec"].get("host") == host
             and (i["metadata"]["namespace"], i["metadata"]["name"]) != (ns, name)]
    if taken:
        return review(req, False, f"host {host} уже занят: {', '.join(taken)}. "
                                  f"Выберите другое имя — {DOCS}#host")
    warnings = []
    if obj["spec"].get("replicas", 1) < 2:
        warnings.append(f"replicas=1: при выкатке и падении ноды будет простой; для прода — 2+ ({DOCS}#replicas)")
    return review(req, True, warnings=warnings)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}
```text
Обработчики — обычные `def`: FastAPI выполнит их в пуле потоков, и синхронный вызов
Kubernetes API не заблокирует event loop. Список всех LinkdApp на каждый запрос годится
для сотен объектов; для тысяч — кэш через watch (informer) в фоне.

**Регистрация и TLS.** API-сервер ходит в вебхук **только по HTTPS** и проверяет сертификат
по `caBundle`. Проще всего — cert-manager: `Issuer` + `Certificate`, а CA в конфигурацию
вебхука проставит cainjector по аннотации.

```yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata: { name: selfsigned, namespace: platform }
spec: { selfSigned: {} }
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata: { name: linkd-webhook, namespace: platform }
spec:
  secretName: linkd-webhook-tls              # монтируется в под как /tls
  dnsNames: [linkd-webhook.platform.svc, linkd-webhook.platform.svc.cluster.local]
  issuerRef: { name: selfsigned, kind: Issuer }
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: linkd-webhook
  annotations: { cert-manager.io/inject-ca-from: platform/linkd-webhook }   # cainjector → caBundle
webhooks:
  - name: validate.linkdapps.platform.example.com
    admissionReviewVersions: [v1]
    sideEffects: None                        # вебхук ничего не меняет вовне → работает и dry-run
    failurePolicy: Fail                      # ⭐ осознанно: без проверки host возможны дубли
    timeoutSeconds: 3                        # по умолчанию 10, максимум 30
    clientConfig: { service: { name: linkd-webhook, namespace: platform, path: /validate, port: 443 } }
    rules: [{ apiGroups: [platform.example.com], apiVersions: [v1alpha1],
              operations: [CREATE, UPDATE], resources: [linkdapps] }]
    namespaceSelector:                       # ⭐ свои поды и kube-system — никогда через свой вебхук
      matchExpressions: [{ key: kubernetes.io/metadata.name, operator: NotIn, values: [kube-system, platform] }]
# MutatingWebhookConfiguration — так же: path /mutate, operations [CREATE],
# reinvocationPolicy: IfNeeded, failurePolicy: Ignore (метки — не повод блокировать деплой)
```text
Без cert-manager: `openssl req -x509 -newkey rsa:2048 -nodes -days 365 -keyout tls.key -out tls.crt
-subj "/CN=linkd-webhook" -addext "subjectAltName=DNS:linkd-webhook.platform.svc"`, Secret
типа `tls`, а `caBundle: $(base64 -w0 tls.crt)` — руками (и не забыть про срок действия).

**Под вебхука:** 2+ реплики, PDB `minAvailable: 1`, readiness на `/healthz`, requests/limits,
ServiceAccount с `list linkdapps` на весь кластер (ClusterRole), `priorityClassName` повыше.

```text
# проверено в kind: предупреждение, метки от /mutate и отказ от /validate
Warning: replicas=1: при выкатке и падении ноды будет простой; для прода — 2+ (…#replicas)
linkdapp.platform.example.com/wh1 created          # labels: part-of=linkd-platform, created-by=kubernetes-admin
Error from server: admission webhook "validate.linkdapps.platform.example.com" denied the request:
host wh.team-a.example.com уже занят: team-a/wh1. Выберите другое имя — …#host
```text
---

## 5. ⭐ Как вебхук кладёт кластер и как его поднять

| Настройка | Риск | Что делать |
|-----------|------|------------|
| `failurePolicy: Fail` (по умолчанию в v1) | Вебхук недоступен → **все** подходящие запросы отклоняются | `Fail` только там, где пропуск опасен; мутации-«удобства» — `Ignore` |
| `failurePolicy: Ignore` | Вебхук лёг → защита молча выключена | Алерт на ошибки вызова; для безопасности — `Fail` + HA |
| `timeoutSeconds` (по умолчанию 10) | Медленный вебхук × каждый запрос = тормозит весь API | 2–5 с; вебхук быстрый, без тяжёлых вызовов |
| Правила «все ресурсы, все namespace» | Вебхук перехватывает создание **своих же** подов и системных | Точные `rules`, `namespaceSelector` без kube-system и своего namespace, `matchConditions` |
| Cluster-scoped ресурсы | `namespaceSelector` на них **не действует** | `objectSelector` или `matchConditions` |

**Классический «кирпич»:** вебхук на `pods` во всех namespace с `Fail`, его поды упали
(OOM, сломанный образ, истёк сертификат). Новые поды не создаются нигде — в том числе
**поды самого вебхука**; CoreDNS или CNI после рестарта ноды не поднимаются, и кластер
деградирует. Как выглядит (проверено, вебхук остановлен):

```text
Error from server (InternalError): Internal error occurred: failed calling webhook
"mutate.linkdapps.platform.example.com": failed to call webhook: Post "https://…/mutate?timeout=3s":
dial tcp …:8443: connect: connection refused
```text
**Runbook восстановления:**
```bash
# 1. кто мешает: имя вебхука есть в тексте ошибки; список всех
kubectl get validatingwebhookconfigurations,mutatingwebhookconfigurations
# 2. вебхуки не вызываются для своих конфигураций — удалить/ослабить можно всегда
kubectl delete validatingwebhookconfiguration linkd-webhook
#    или мягче: failurePolicy → Ignore
kubectl patch validatingwebhookconfiguration linkd-webhook --type=json \
  -p='[{"op":"replace","path":"/webhooks/0/failurePolicy","value":"Ignore"}]'
# 3. починить вебхук (под, сертификат, Service), проверить, вернуть конфигурацию из git
# 4. при GitOps: сначала выключить selfHeal у Application, иначе ArgoCD вернёт сломанное
```text
**Профилактика:** исключения kube-system и своего namespace; HA + PDB; сертификаты с
автопродлением (cert-manager) и алерт за 14 дней до истечения; метрики API-сервера
`apiserver_admission_webhook_admission_duration_seconds` и `apiserver_admission_webhook_rejection_count`
(по `name` и `error_type`) — алерт на рост ошибок вызова; и главное — **если хватает VAP/MAP,
вебхук не нужен**.

---

## 6. Kyverno со стороны платформы

Установка, CEL-типы и legacy `ClusterPolicy` — [../Security/06_k8s_security.md](/security/06-k8s-security) §6.
Факты (проверь, сентябрь 2026): **Kyverno 1.19.1**, чарт `kyverno/kyverno` 3.9.1; CEL-типы
`ValidatingPolicy`, `MutatingPolicy`, `GeneratingPolicy`, `ImageValidatingPolicy`, `DeletingPolicy`
(плюс `Namespaced…` варианты) — в `policies.kyverno.io/v1` (хранятся пока в `v1beta1`,
переезд в 1.20); `ClusterPolicy`/`Policy` удаляют в **1.20** (ожидается ~ноябрь 2026).

**Validate с понятным сообщением + autogen для контроллеров:**
```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata: { name: require-probes }
spec:
  validationActions: [Audit]                  # этап 1: только отчёты; потом [Warn], затем [Deny]
  evaluation: { background: { enabled: true } }
  autogen:
    podControllers: { controllers: [deployments, statefulsets] }   # правило и для шаблонов подов
  matchConstraints:
    resourceRules:
      - { apiGroups: [""], apiVersions: [v1], operations: [CREATE, UPDATE], resources: [pods] }
    namespaceSelector:
      matchExpressions: [{ key: platform.example.com/team, operator: Exists }]
  variables:
    - { name: noProbe, expression: "object.spec.containers.filter(c, !has(c.readinessProbe)).map(c, c.name)" }
  validations:
    - expression: "size(variables.noProbe) == 0"
      messageExpression: >-
        'контейнеры без readinessProbe: ' + variables.noProbe.join(', ') +
        '. Без неё трафик идёт в неготовый под. Как настроить: https://platform.example.com/docs/probes'
```text
**Mutate — дефолтные requests** (для квоты и планировщика). ⚠️ Учти defaulting: если
заданы только `limits`, `requests.memory` уже равен лимиту — проверяем именно `cpu`:
```yaml
apiVersion: policies.kyverno.io/v1
kind: MutatingPolicy
metadata: { name: default-requests }
spec:
  matchConstraints:
    resourceRules:
      - { apiGroups: [""], apiVersions: [v1], operations: [CREATE], resources: [pods] }
    namespaceSelector:
      matchExpressions: [{ key: platform.example.com/team, operator: Exists }]
  matchConditions:
    - name: some-without-cpu-request
      expression: "object.spec.containers.exists(c, !has(c.resources.requests) || !('cpu' in c.resources.requests))"
  mutations:
    - patchType: ApplyConfiguration           # контейнеры сливаются по name, остальные поля не трогаются
      applyConfiguration:
        expression: >-
          Object{ spec: Object.spec{ containers: object.spec.containers
            .filter(c, !has(c.resources.requests) || !('cpu' in c.resources.requests))
            .map(c, Object.spec.containers{ name: c.name,
              resources: Object.spec.containers.resources{ requests: {
                "cpu": c.resources.?requests.?cpu.orValue("50m"),
                "memory": c.resources.?requests.?memory.orValue("64Mi") } } }) } }
```text
**Generate — базовый набор для каждого namespace команды** (NetworkPolicy + ResourceQuota):
```yaml
apiVersion: policies.kyverno.io/v1
kind: GeneratingPolicy
metadata: { name: team-namespace-baseline }
spec:
  evaluation:
    synchronize: { enabled: true }            # удалили или поправили руками — Kyverno вернёт
  matchConstraints:
    resourceRules:                            # UPDATE — чтобы сработало и при добавлении метки
      - { apiGroups: [""], apiVersions: [v1], operations: [CREATE, UPDATE], resources: [namespaces] }
  matchConditions:
    - name: is-team-namespace
      expression: "has(object.metadata.labels) && 'platform.example.com/team' in object.metadata.labels"
  variables:
    - { name: ns, expression: "object.metadata.name" }
    - name: downstream
      expression: >-
        [
          { "apiVersion": dyn("networking.k8s.io/v1"), "kind": dyn("NetworkPolicy"),
            "metadata": dyn({"name": "default-deny-ingress", "namespace": variables.ns}),
            "spec": dyn({"podSelector": {}, "policyTypes": ["Ingress"],
              "ingress": [{"from": [{"podSelector": {&#125;&#125;,
                {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "envoy-gateway-system"&#125;&#125;}]}]}) },
          { "apiVersion": dyn("v1"), "kind": dyn("ResourceQuota"),
            "metadata": dyn({"name": "team-quota", "namespace": variables.ns}),
            "spec": dyn({"hard": {"requests.cpu": "4", "requests.memory": "8Gi", "limits.memory": "16Gi", "pods": "50"&#125;&#125;) }
        ]
  generate:
    - expression: generator.Apply(variables.ns, variables.downstream)
---
# Kyverno нужны права создавать эти типы — агрегированная ClusterRole
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kyverno-generate-team-baseline
  labels:
    rbac.kyverno.io/aggregate-to-background-controller: "true"
    rbac.kyverno.io/aggregate-to-admission-controller: "true"
rules:
  - { apiGroups: [networking.k8s.io], resources: [networkpolicies], verbs: [get, list, watch, create, update, patch, delete] }
  - { apiGroups: [""], resources: [resourcequotas], verbs: [get, list, watch, create, update, patch, delete] }
```text
**Отчёты и раскатка.** Результаты — в `PolicyReport` (`wgpolicyk8s.io/v1alpha2`; формат
`openreports.io` — опционально, флаг `--openreportsEnabled`):
```bash
kubectl get policyreport -n team-a -o custom-columns=KIND:.scope.kind,NAME:.scope.name,PASS:.summary.pass,FAIL:.summary.fail
kubectl get policyreport -n team-a -o jsonpath='{range .items[*].results[?(@.result=="fail")]}{.policy}: {.message}{"\n"}{end}'
```text
```text
 Audit (2–4 недели)          Warn (1–2 недели)             Deny
 отчёты, список нарушителей → kubectl и CI показывают   → отказ; исключения — через
 по командам, MR с фиксами    предупреждение             PolicyException с владельцем и сроком
```text
Сроки — ориентир, а не правило: переходить, когда нарушений ноль или все объяснены.
В CI — `kyverno apply policies/ --resource manifests/` ломает MR раньше кластера.

---

## 7. Что выбрать

| | VAP / MAP | Kyverno | Свой webhook | OPA Gatekeeper |
|---|-----------|---------|--------------|----------------|
| Где работает | В API-сервере | Свои поды-вебхуки + фоновые контроллеры | Твой под | Свои поды-вебхуки |
| Язык | CEL | CEL (legacy — YAML-паттерны) | Любой | Rego |
| Точки отказа | Нет | Kyverno (HA обязательно) | Твой код, TLS, сеть | Gatekeeper |
| Validate / mutate | ✅ / ✅ (MAP с 1.36) | ✅ / ✅ | ✅ / ✅ | ✅ / ✅ |
| Generate ресурсов | ❌ | ✅ | Можно, но это уже контроллер | ❌ |
| Внешний контекст | Только namespace и params | Вызовы API/HTTP из CEL-библиотек Kyverno (проверь) | ✅ Любой | Синхронизация данных в кэш |
| Отчёты по существующим объектам | Аудит-лог | ✅ PolicyReport | Сам | ✅ Аудит |
| CLI для CI | `kubectl --dry-run=server` | ✅ `kyverno apply/test` | Свои тесты | `gator` |
| ⭐ Когда | Простые правила по одному объекту; минимум движущихся частей | Платформа с десятками правил, generate, отчёты, исключения | Уникальная логика с внешними данными | Уже есть OPA/Rego в компании |

> 💡 Практичный набор для платформы в 2026: PSA `restricted` как база + VAP/MAP для
> простых правил + Kyverno для generate и отчётов + свой webhook **только** для того, что не
> выразить иначе. Каждый вебхук — ещё один сервис с дежурством.

---

## 8. UX ограждений: сообщение — это интерфейс

Ограждение, которое говорит «denied», — шлагбаум. Ограждение, которое объясняет, — часть golden path.

**Анатомия хорошего отказа:** что именно (объект, контейнер, поле) → почему (риск в одной
фразе) → как исправить (пример или значение) → ссылка на доки → куда писать, если исключение.

| Плохо | Хорошо |
|-------|--------|
| `denied by require-limits` | `Deployment api: у контейнеров nginx нет resources.limits.memory. Пример: …/docs/resources` |
| `validation failed` | `hostnames evil.team-b.example.com вне домена команды team-a.example.com. Как выбрать имя: …/docs/routes` |
| Правило включили сразу в Deny | Audit → Warn → Deny с анонсом, отчётом по командам и датой |
| Исключение «напишите в личку» | `PolicyException` через MR с владельцем и сроком |

**Метрики ограждений:** число отказов по политикам и командам (рост после релиза шаблона —
сигнал бага в шаблоне), доля «повторных» отказов (сообщение непонятно), число исключений
и их возраст. Если одну политику постоянно обходят — чинить путь, а не ужесточать запрет.

---

## 🧪 Мини-лаба: ограждения для namespace команды

Стенд блока (kind 1.36, Envoy Gateway, CRD и оператор LinkdApp из тем 02–03).

```bash
kubectl create namespace platform
kubectl label namespace team-a platform.example.com/team=team-a --overwrite
kubectl apply -f vap-require-limits.yaml -f vap-route-team-domain.yaml -f map-team-label.yaml
kubectl -n team-a create deployment nolim --image=nginx:1.27-alpine --dry-run=server   # отказ с подсказкой
```text
**Шаги:**
1. **VAP:** HTTPRoute с `evil.team-b.example.com` → отказ; с `links.team-a.example.com` → проходит.
   Создай namespace `team-c` с меткой команды без записи в ConfigMap — прочитай сообщение.
2. **MAP:** создай Deployment в `team-a` и в `default` — где появилась метка `platform.example.com/team`?
3. **Kyverno:** `helm install kyverno kyverno/kyverno -n kyverno --create-namespace --version 3.9.1`,
   примени GeneratingPolicy и ClusterRole; создай namespace с меткой команды одним манифестом —
   появились NetworkPolicy и ResourceQuota? Удали квоту руками — вернулась?
4. **Отчёты:** примени `require-probes` в Audit, создай Deployment без readinessProbe,
   найди его в `PolicyReport`. Переведи в `[Warn]` — что показал kubectl?
5. **Webhook:** запусти `webhook.py` локально с самоподписанным сертификатом (IP шлюза сети
   kind в SAN: `docker network inspect kind`), зарегистрируй через `clientConfig.url`,
   создай два LinkdApp с одним host. Затем останови вебхук и попробуй создать LinkdApp.
6. **Восстановление:** по runbook §5 удали конфигурацию вебхука и убедись, что создание снова работает.

**Проверь себя:** почему политика `require-limits` смотрит и на Deployment, а не только на Pod?
Почему домены команд — в ConfigMap платформы, а не в namespace команды? Что сломается, если
вебхук на `pods` не исключает свой namespace?

---

## 9. Грабли

| Грабля | Что происходит | Как избежать |
|--------|----------------|--------------|
| Политика только на Pod | Разработчик видит «всё ок» при apply, а поды не создаются — отказ в Events ReplicaSet | Проверять и шаблоны контроллеров (VAP с двумя путями, Kyverno autogen) |
| Проверка «нет requests» | Не срабатывает: defaulting уже поставил `requests = limits` | Проверять конкретный ключ (`cpu`) |
| `namespaceObject` в matchConditions MAP | Ошибка вычисления → при `Fail` отказ всем | Фильтр в binding или `variables` |
| Параметры политики в namespace команды | Команда сама меняет себе ограничения | Параметры — в namespace платформы |
| Вебхук без исключения kube-system и своего namespace | «Кирпич» при падении вебхука | `namespaceSelector` с `NotIn` |
| `timeoutSeconds` по умолчанию (10 с) | Медленный вебхук тормозит весь API | 2–5 с, быстрый код, кэш |
| Сертификат вебхука истёк | Все подходящие запросы падают с TLS-ошибкой | cert-manager + алерт на срок |
| Сразу `Deny` | Массовые сломанные деплои, политику «временно» выключают навсегда | Audit → Warn → Deny |
| GeneratingPolicy только на CREATE; нет прав у Kyverno | Namespace без квоты; ничего не создаётся | CREATE + UPDATE (или `generateExisting`); агрегированная ClusterRole |
| ArgoCD selfHeal при аварийном удалении вебхука | ArgoCD возвращает сломанную конфигурацию | Сначала отключить selfHeal |

---

## 💼 Как это в DevOps

- Ограждения — вторая половина golden path: шаблон делает правильно по умолчанию,
  политика ловит отклонения **с объяснением**. Платформенная команда отвечает и за текст сообщений.
- На собесах про вебхуки спрашивают почти всегда: «что будет, если он ляжет» и «как поднять
  кластер». Ответ: `failurePolicy`, исключения, HA, и что конфигурации вебхуков сами под
  вебхуки не попадают.
- Тренд 2025–2026 — **меньше вебхуков**: CEL в CRD, VAP, MAP (GA 1.36) и CEL-типы Kyverno.
  Свой вебхук пишут, только когда без внешнего контекста не обойтись.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Простое правило без вебхука | VAP + binding, CEL, `messageExpression` |
| Правило по метке namespace | `namespaceObject.metadata.?labels[?'k'].orValue('')` |
| Параметры правила | `paramKind` + `paramRef {name, namespace, parameterNotFoundAction}` |
| Дефолт без вебхука | MutatingAdmissionPolicy (GA 1.36), `ApplyConfiguration` |
| Внешний контекст | Свой webhook: AdmissionReview v1, `uid`, `allowed`, `patch` base64 |
| TLS для вебхука | cert-manager `Certificate` + `cert-manager.io/inject-ca-from` |
| Не положить кластер | `namespaceSelector` без kube-system/своего ns, `timeoutSeconds: 3`, HA, PDB |
| Поднять кластер | `kubectl delete validatingwebhookconfiguration &lt;имя&gt;` |
| Ресурсы для каждого namespace | Kyverno `GeneratingPolicy` + `synchronize` + права через агрегацию |
| Кто нарушает | `kubectl get policyreport -A` |

---

## 🧠 Что запомнить

1. ⭐ Порядок: defaulting → mutating (по очереди) → схема → validating (параллельно) → etcd.
2. Конфигурации вебхуков сами под вебхуки не попадают — сломанный вебхук всегда можно удалить.
3. ⭐ VAP (GA 1.30): политика + binding (+ params); `namespaceObject`, `variables`,
   `messageExpression`; `Deny` и `Warn` вместе нельзя; `failurePolicy` — про ошибки вычисления.
4. Проверяй шаблоны контроллеров, а не только поды — иначе ошибка видна лишь в Events.
5. Параметры и метки, по которым решает политика, должны принадлежать платформе, а не команде.
6. ⭐ MutatingAdmissionPolicy — GA в 1.36; `ApplyConfiguration` или `JSONPatch`;
   `namespaceObject` недоступен в `matchConditions`.
7. Свой webhook — только для внешнего контекста; AdmissionReview v1: тот же `uid`,
   `patch` в base64, `warnings` для мягких подсказок; TLS по `caBundle`.
8. ⭐ `failurePolicy: Fail` + широкие правила + упавший вебхук = «кирпич»; защита — исключения,
   короткий таймаут, HA, cert-manager, алерты по метрикам admission.
9. Kyverno 1.19: validate с autogen, mutate дефолтов, generate NetworkPolicy/ResourceQuota
   с synchronize, PolicyReport; legacy `ClusterPolicy` уходит в 1.20.
10. Раскатка: Audit → Warn → Deny, исключения через MR с владельцем и сроком.
11. Сообщение отказа: что, почему, как исправить, ссылка — это интерфейс платформы.

➡️ Дальше: [05_gateway_mesh.md](/platform/05-gateway-mesh) · Задачи: 04_admission_policy_tasks.md


---

### Блок A. Теория


**A1.** ⭐ Назови порядок этапов, которые проходит запрос к API-серверу от аутентификации
до записи в etcd. Где в нём defaulting схемы?

<details><summary>Ответ</summary>

Аутентификация → авторизация (RBAC) → декодирование и defaulting схемы → mutating
admission (MAP и mutating webhooks) → валидация схемы (и CEL в CRD) → validating admission
(VAP и validating webhooks) → etcd. Defaulting — до admission: политики видят уже
проставленные дефолты.

</details>

**A2.** Почему мутации идут до валидации? Что это даёт политикам и PSA?

<details><summary>Ответ</summary>

Чтобы проверялся итоговый объект: дефолт, поставленный мутацией (seccomp, requests),
проходит валидацию и PSA, и не нужно дублировать логику.

</details>

**A3.** Чем отличается выполнение mutating и validating вебхуков (последовательно/параллельно)?
Зачем `reinvocationPolicy`?

<details><summary>Ответ</summary>

Mutating — последовательно, каждый видит результат предыдущего; validating —
параллельно. `reinvocationPolicy: IfNeeded` — вызвать мутацию повторно, если объект
поменяла более поздняя мутация.

</details>

**A4.** ⭐ Для каких объектов admission-вебхуки не вызываются и почему это важно для аварий?

<details><summary>Ответ</summary>

Для `ValidatingWebhookConfiguration`, `MutatingWebhookConfiguration` и объектов
политик admission (VAP/MAP и их binding). Поэтому сломанный вебхук всегда можно удалить
или ослабить — даже если он перехватывает «всё».

</details>

**A5.** Из каких объектов состоит ValidatingAdmissionPolicy? Что будет с политикой без binding?

<details><summary>Ответ</summary>

Политика (правила), binding (где и с какими действиями), параметры (опционально).
Без binding политика ничего не делает.

</details>

**A6.** Какие переменные доступны в CEL у VAP? Что такое `namespaceObject`?

<details><summary>Ответ</summary>

`object`, `oldObject`, `request`, `params`, `namespaceObject`, `authorizer`, `variables`.
`namespaceObject` — объект Namespace, в котором лежит проверяемый ресурс (с метками и
аннотациями); для cluster-scoped ресурсов его нет.

</details>

**A7.** Чем отличаются `validationActions` `Deny`, `Warn`, `Audit`? Какую комбинацию нельзя?

<details><summary>Ответ</summary>

Deny — отказ; Warn — предупреждение клиенту; Audit — запись в аудит-лог. Нельзя
`Deny` вместе с `Warn`.

</details>

**A8.** Что задаёт `failurePolicy` у VAP — в отличие от `failurePolicy` у вебхука?

<details><summary>Ответ</summary>

У VAP — поведение при ошибке **вычисления** (нет поля, ошибка типов, параметр
не найден и т.п.); у вебхука — при недоступности или ошибке **вызова** вебхука.

</details>

**A9.** Зачем `paramKind`/`paramRef`? Что делает `parameterNotFoundAction`?

<details><summary>Ответ</summary>

Вынести настраиваемые значения (лимиты, домены) из политики в объект-параметр.
`parameterNotFoundAction: Deny|Allow` — что делать, если параметр не найден.

</details>

**A10.** ⭐ Почему политику «limits обязательны» стоит проверять и на Deployment, а не только на Pod?

<details><summary>Ответ</summary>

Deployment применяет разработчик — отказ сразу в `kubectl apply` и в CI. Если
проверять только Pod, Deployment создастся, а отказ будет в Events ReplicaSet — «всё зелёное,
а подов нет».

</details>

**A11.** Почему домены команд для HTTPRoute хранятся в ConfigMap платформы, а не в namespace команды?

<details><summary>Ответ</summary>

Команда может править объекты своего namespace — она поменяла бы себе домен.
Параметры и метки, на которых держится политика, должна контролировать платформа.

</details>

**A12.** Какой статус у MutatingAdmissionPolicy в Kubernetes 1.36? Что было в 1.32–1.35?

<details><summary>Ответ</summary>

GA и включена по умолчанию в 1.36 (`admissionregistration.k8s.io/v1`). Alpha — 1.32,
beta — 1.34–1.35 (feature gate и runtime-config).

</details>

**A13.** Чем `ApplyConfiguration` отличается от `JSONPatch` в MAP?

<details><summary>Ответ</summary>

`ApplyConfiguration` — фрагмент объекта, сливается по правилам server-side apply
(удобно для полей, map и списков с ключом, например контейнеров по `name`). `JSONPatch` —
точечные операции add/replace/remove по пути, удобно для произвольных списков.

</details>

**A14.** Какая переменная недоступна в `matchConditions` MAP и как обойти?

<details><summary>Ответ</summary>

`namespaceObject` (ошибка `no such key: metadata`). Фильтровать по namespace
в binding (`matchResources.namespaceSelector`) или читать метку в `variables`.

</details>

**A15.** ⭐ Когда нужен свой admission webhook, если есть VAP, MAP и Kyverno?

<details><summary>Ответ</summary>

Нужен внешний контекст (другие объекты кластера, реестр, CMDB, биллинг) или логика,
которую CEL не выразит; например, уникальность host во всём кластере.

</details>

**A16.** Опиши AdmissionReview v1: что приходит в `request`, что должно быть в `response`?

<details><summary>Ответ</summary>

`request`: `uid`, `kind`, `resource`, `operation`, `userInfo`, `namespace`, `object`,
`oldObject`, `dryRun`. `response`: тот же `uid`, `allowed`; при отказе — `status` с
`message` (и `code`); при мутации — `patchType: JSONPatch` и `patch`; опционально `warnings`.

</details>

**A17.** Как передаётся мутация в ответе вебхука? Как экранировать ключ метки с `/` в JSONPatch?

<details><summary>Ответ</summary>

JSONPatch (RFC 6902) в поле `patch`, закодированный в base64, и `patchType: JSONPatch`.
В JSON Pointer `/` в ключе → `~1`, `~` → `~0`: `/metadata/labels/platform.example.com~1team`.

</details>

**A18.** Зачем в ответе `warnings`?

<details><summary>Ответ</summary>

Мягкая подсказка без отказа: kubectl печатает `Warning: …` — удобно для
рекомендаций (replicas=1) и этапа Warn при раскатке.

</details>

**A19.** Как API-сервер проверяет TLS вебхука? Как это автоматизирует cert-manager?

<details><summary>Ответ</summary>

По `caBundle` в `clientConfig`: сертификат вебхука должен быть подписан этим CA
и содержать имя Service (`svc.ns.svc`) в SAN. cert-manager выпускает сертификат, а cainjector
по аннотации `cert-manager.io/inject-ca-from` вписывает CA в конфигурацию и обновляет при ротации.

</details>

**A20.** ⭐ Что значат `failurePolicy`, `timeoutSeconds`, `sideEffects`, `namespaceSelector`,
`objectSelector`, `matchConditions` у вебхука? Какие у них значения по умолчанию или ограничения?

<details><summary>Ответ</summary>

`failurePolicy` — Fail (по умолчанию) или Ignore при недоступности; `timeoutSeconds` —
по умолчанию 10, от 1 до 30; `sideEffects` — обязателен, `None`/`NoneOnDryRun`, иначе dry-run
запросы отклоняются; `namespaceSelector` — по меткам namespace; `objectSelector` — по меткам
самого объекта; `matchConditions` — CEL-фильтры по запросу (object, oldObject, request, authorizer).

</details>

**A21.** Почему `namespaceSelector` не защищает от перехвата cluster-scoped ресурсов?

<details><summary>Ответ</summary>

У cluster-scoped объектов нет namespace, по которому фильтровать (для самих
Namespace селектор применяется к их меткам). Для остальных cluster-scoped — `objectSelector`
или `matchConditions`.

</details>

**A22.** ⭐ Как вебхук может «положить» кластер? Опиши сценарий по шагам.

<details><summary>Ответ</summary>

Вебхук на поды во всех namespace с `Fail`, без исключения своего namespace →
поды вебхука падают (OOM, образ, сертификат) → API отклоняет создание любых подов →
поды вебхука тоже не создаются → после рестарта нод не поднимаются CoreDNS, CNI, ingress →
кластер деградирует, а «починить деплоем» нельзя.

</details>

**A23.** Какие метрики API-сервера помогают увидеть проблемы с вебхуками?

<details><summary>Ответ</summary>

`apiserver_admission_webhook_admission_duration_seconds` (задержка по вебхукам)
и `apiserver_admission_webhook_rejection_count` (отказы и ошибки вызова по `name`,
`error_type`); плюс логи API-сервера и доступность эндпоинтов Service вебхука.

</details>

**A24.** Какие типы политик есть в Kyverno 1.19 на CEL? Что будет с `ClusterPolicy` в 1.20?

<details><summary>Ответ</summary>

`ValidatingPolicy`, `MutatingPolicy`, `GeneratingPolicy`, `ImageValidatingPolicy`,
`DeletingPolicy` и namespaced-варианты, `policies.kyverno.io/v1`. `ClusterPolicy`/`Policy`
deprecated и удаляются в 1.20.

</details>

**A25.** Что делает `autogen.podControllers` в ValidatingPolicy Kyverno?

<details><summary>Ответ</summary>

Автоматически применяет правило, написанное для Pod, к шаблонам подов в указанных
контроллерах (Deployment, StatefulSet…), чтобы отказ приходил на объект разработчика.

</details>

**A26.** Что делает `synchronize` в GeneratingPolicy? Почему нужны операции CREATE и UPDATE?

<details><summary>Ответ</summary>

Держит сгенерированные ресурсы синхронными с политикой и триггером: удалили или
поправили руками — вернёт; удалили триггер — уберёт. UPDATE нужен, чтобы сработало, когда
метку добавили существующему namespace (или `generateExisting`).

</details>

**A27.** Зачем Kyverno агрегированная ClusterRole для generate?

<details><summary>Ответ</summary>

Kyverno создаёт ресурсы от своего ServiceAccount; по умолчанию у него нет прав на
NetworkPolicy/ResourceQuota. Права добавляют ClusterRole с метками агрегации
`rbac.kyverno.io/aggregate-to-background-controller` (и admission-controller).

</details>

**A28.** Где смотреть результаты политик Kyverno? Какой API у отчётов?

<details><summary>Ответ</summary>

`PolicyReport`/`ClusterPolicyReport` в `wgpolicyk8s.io/v1alpha2`
(`kubectl get policyreport -A`); опционально — формат `openreports.io`.

</details>

**A29.** ⭐ Как раскатывать новую политику? Что должно быть готово до перехода в Deny?

<details><summary>Ответ</summary>

Audit → отчёты по командам и MR с исправлениями → Warn (видно в kubectl и CI) →
Deny. До Deny: нарушений ноль или все оформлены исключениями с владельцем и сроком, анонс
с датой, документация по исправлению, проверка в CI.

</details>

**A30.** Из каких частей состоит хорошее сообщение отказа?

<details><summary>Ответ</summary>

Что не так (объект, контейнер, поле) → почему (риск) → как исправить (пример) →
ссылка на доки → куда обращаться за исключением.

</details>

---

### Блок B. «Что произойдёт»


```text:no-line-numbers
# B1 — VAP на pods: у контейнеров должны быть requests
```text
```text:no-line-numbers
validations:
```text
```text:no-line-numbers
  - expression: "object.spec.containers.all(c, has(c.resources.requests))"
```text
```text:no-line-numbers
# разработчик применяет Deployment, где у контейнера только limits.memory: 256Mi
```text
Вопрос: пройдёт ли под? Почему?

```text:no-line-numbers
# B2 — binding
```text
```text:no-line-numbers
validationActions: [Deny, Warn]
```text
Вопрос: что ответит API-сервер?

```text:no-line-numbers
# B3 — VAP route-team-domain, у namespace team-x метка platform.example.com/team=team-x,
```text
```text:no-line-numbers
# в ConfigMap platform/route-domains нет ключа team-x
```text
Вопрос: что увидит команда при создании HTTPRoute?

```text:no-line-numbers
# B4 — MutatingAdmissionPolicy
```text
```text:no-line-numbers
matchConditions:
```text
```text:no-line-numbers
  - name: team-ns
```text
```text:no-line-numbers
    expression: "'platform.example.com/team' in namespaceObject.metadata.labels"
```text
```text:no-line-numbers
failurePolicy: Fail
```text
Вопрос: что случится с созданием Deployment?

```text:no-line-numbers
# B5 — вебхук
```text
```text:no-line-numbers
rules: [{ apiGroups: [""], apiVersions: [v1], operations: [CREATE], resources: [pods] }]
```text
```text:no-line-numbers
failurePolicy: Fail
```text
```text:no-line-numbers
# namespaceSelector не задан; поды вебхука — в namespace platform; нода с ними перезагрузилась
```text
Вопрос: что будет дальше?

```text:no-line-numbers
# B6 — тот же вебхук, но failurePolicy: Ignore; это вебхук, запрещающий privileged-поды
```text
Вопрос: чем это опасно?

```text:no-line-numbers
# B7 — ответ вебхука
```text
```text:no-line-numbers
return {"apiVersion": "admission.k8s.io/v1", "kind": "AdmissionReview",
```text
```text:no-line-numbers
        "response": {"allowed": True, "patchType": "JSONPatch", "patch": json.dumps(ops)&#125;&#125;
```text
Вопрос: найди две ошибки.

```text:no-line-numbers
// B8 — JSONPatch
```text
```text:no-line-numbers
[{"op": "add", "path": "/metadata/labels/platform.example.com/team", "value": "a"}]
```text
Вопрос: что не так?

```text:no-line-numbers
# B9 — Kyverno GeneratingPolicy: operations [CREATE] на namespaces
```text
```text:no-line-numbers
# namespace team-f создали без метки, через минуту добавили platform.example.com/team=team-f
```text
Вопрос: будет ли в team-f ResourceQuota?

```text:no-line-numbers
# B10 — Kyverno ValidatingPolicy сразу в validationActions: [Deny] на все namespace
```text
```text:no-line-numbers
# в кластере 40 сервисов, у 15 нет readinessProbe
```text
Вопрос: что случится при следующем релизе и узле, ушедшем на обслуживание?

---

### Блок C. Практика


### C1. 🔑 require-limits
Примени VAP `require-limits` из конспекта. Проверь: Deployment без limits → отказ в
`kubectl apply`; Pod без limits → отказ; Deployment с limits → проходит. Переведи binding
в `[Warn, Audit]` и посмотри, как выглядит предупреждение.

### C2. 🔑 Домен команды
Настрой `route-team-domain` с ConfigMap в `platform`. Проверь три случая: свой домен,
чужой домен, команда без записи в ConfigMap. Создай LinkdApp с чужим `host` — на каком
объекте и где ты увидишь отказ?

### C3. Своя VAP
Напиши VAP: у Deployment в namespace команд должна быть метка `app.kubernetes.io/name`,
а `replicas` не больше значения `maxReplicas` из ConfigMap-параметра. Сообщение — с фактическим
числом и лимитом (`messageExpression`).

### C4. MAP
Примени `team-label`. Затем напиши вторую MAP, которая ставит `revisionHistoryLimit: 3`,
если поле не задано. Проверь `--dry-run=server -o yaml`. Что будет, если поле задано?

### C5. 🔑 Webhook
Запусти `webhook.py` локально: самоподписанный сертификат с IP шлюза сети kind в SAN,
регистрация через `clientConfig.url` и `caBundle`. Проверь: метки от `/mutate`, отказ
при дубле host, предупреждение при `replicas: 1`.

### C6. Тесты вебхука
Напиши pytest-тесты с `fastapi.testclient.TestClient`: мутация экранирует ключ с `/`;
повторная мутация не даёт patch (идемпотентность); дубль host — `allowed: false`.
Подмени Kubernetes API фейком.

### C7. 🔑 Сломай и почини
При работающем вебхуке останови его и попробуй создать LinkdApp. Засеки время ответа
и запиши текст ошибки. Восстанови работу по runbook двумя способами: удалением конфигурации
и переводом `failurePolicy` в `Ignore`.

### C8. Kyverno generate
Поставь Kyverno 1.19, примени `team-namespace-baseline` и ClusterRole. Проверь: namespace
с меткой → NetworkPolicy и ResourceQuota; удалённая квота вернулась; namespace без метки —
ничего. Убери ClusterRole — что покажет статус политики?

### C9. Kyverno validate и отчёты
Примени `require-probes` в Audit. Найди нарушителей в `PolicyReport` одной командой.
Переведи в `[Warn]` и затем в `[Deny]`; проверь, что autogen сработал и отказ приходит
на Deployment, а не на Pod.

### C10. Сообщения
Возьми три своих политики и перепиши сообщения по анатомии «что — почему — как — ссылка».
Попроси коллегу (или представь новичка) исправить манифест только по сообщению.

### C11. Выбор инструмента (со звёздочкой)
Для каждого правила выбери VAP, MAP, Kyverno или webhook и объясни: (а) образы только из
`registry.example.com`; (б) host LinkdApp уникален в кластере; (в) в каждом namespace
команды — NetworkPolicy по умолчанию; (г) метка команды на всех Deployment; (д) нельзя
создать больше 3 LinkdApp с `size: large` на команду.

---

### Блок D. Инциденты


**D1.** Утром никто не может задеплоиться: `failed calling webhook ... x509: certificate has
expired`. Действия по шагам?

<details><summary>Ответ</summary>

Найти вебхук по имени из ошибки; снять блокировку (`failurePolicy: Ignore` или удалить
конфигурацию, при GitOps — отключить selfHeal); перевыпустить сертификат (cert-manager
`cmctl renew` или удалить Secret), проверить `caBundle`; вернуть конфигурацию; добавить
алерт на срок сертификата и автопродление.

</details>

**D2.** После установки нового вебхука все запросы к API стали медленнее на ~10 секунд,
kubectl подвисает. Что проверить?

<details><summary>Ответ</summary>

Вебхук медленный или недоступен и ждётся таймаут (по умолчанию 10 с): метрика
`apiserver_admission_webhook_admission_duration_seconds` по имени, логи и ресурсы пода
вебхука, широкие `rules`. Сузить правила, `timeoutSeconds: 2–5`, ускорить код.

</details>

**D3.** Разработчики жалуются: «Deployment применился, но поды не появляются». В Events
ReplicaSet — отказ политики. Что улучшить?

<details><summary>Ответ</summary>

Политика проверяет только Pod. Добавить проверку шаблонов контроллеров (VAP с двумя
путями или Kyverno autogen) и проверку в CI.

</details>

**D4.** Kyverno обновили, admission-контроллер не стартует, в затронутых namespace не
создаются поды. Как восстановиться и что изменить на будущее?

<details><summary>Ответ</summary>

Удалить или перевести в `Ignore` вебхуки Kyverno (`kubectl get validatingwebhookconfigurations
| grep kyverno`), откатить релиз Helm, поднять admission-контроллер; на будущее — 3 реплики,
PDB, исключение системных namespace, обновление сначала на staging, алерт на доступность.

</details>

**D5.** Политику «запретить `:latest`» включили в Deny, через час её «временно» выключили,
через полгода так и не включили. Разбор: что пошло не так?

<details><summary>Ответ</summary>

Не было Audit и Warn, списка нарушителей, анонса и помощи с миграцией, процесса
исключений. Сразу Deny сломал деплои, и «временное» выключение стало постоянным. Повторить
по правилам раскатки с датами и владельцем.

</details>

**D6.** ArgoCD каждые 3 минуты возвращает удалённую при аварии конфигурацию сломанного
вебхука. Что делать?

<details><summary>Ответ</summary>

Отключить `selfHeal`/auto-sync у Application с вебхуком, удалить конфигурацию,
починить в git (или исключить ресурс), затем вернуть auto-sync.

</details>

**D7.** После включения MAP с метками команда видит постоянный OutOfSync в ArgoCD для
Deployment. Почему и как исправить?

<details><summary>Ответ</summary>

Мутация добавляет метку, которой нет в git; ArgoCD видит разницу. Добавить метку
в манифесты, или настроить `ignoreDifferences` для этого поля, или включить
server-side diff в ArgoCD, чтобы учитывались поля, которыми владеет мутация.

</details>

---

### Блок E. Вопросы с собеседования


**1.** ⭐ Как устроена цепочка admission в Kubernetes?

<details><summary>Ответ</summary>

Аутентификация → авторизация → defaulting → mutating (последовательно) → схема →
   validating (параллельно) → etcd; вебхуки не вызываются для своих конфигураций.

</details>

**2.** ⭐ ValidatingAdmissionPolicy или admission webhook — как выбираете?

<details><summary>Ответ</summary>

VAP — если хватает CEL по объекту, namespace и параметрам: нет пода и точки отказа.
   Webhook — если нужен внешний контекст или сложная логика.

</details>

**3.** Что такое MutatingAdmissionPolicy и что она заменяет?

<details><summary>Ответ</summary>

Мутации на CEL в API-сервере (GA 1.36): заменяет простые mutating webhooks — метки,
   дефолты, securityContext.

</details>

**4.** ⭐ Что будет, если admission webhook недоступен? Как спроектировать, чтобы не положить кластер?

<details><summary>Ответ</summary>

Зависит от `failurePolicy`: Fail — запросы отклоняются, Ignore — проверка пропускается.
   Исключить kube-system и свой namespace, узкие правила, короткий таймаут, HA и PDB,
   cert-manager, алерты по метрикам admission.

</details>

**5.** Как восстановить кластер, если вебхук блокирует создание подов?

<details><summary>Ответ</summary>

Удалить или ослабить конфигурацию вебхука (она сама под вебхуки не попадает), при GitOps —
   сначала отключить selfHeal; починить; вернуть из git.

</details>

**6.** Kyverno, Gatekeeper или VAP — что бы вы поставили в новую платформу?

<details><summary>Ответ</summary>

PSA + VAP/MAP для простого, Kyverno для generate, отчётов и исключений; Gatekeeper —
   если в компании уже Rego.

</details>

**7.** Как раскатываете новые политики на работающий кластер?

<details><summary>Ответ</summary>

Audit → отчёты → Warn → Deny, исключения через MR с владельцем и сроком, CI-проверки.

</details>

**8.** Как сделать, чтобы политики помогали разработчикам, а не мешали?

<details><summary>Ответ</summary>

Понятные сообщения со ссылкой, предупреждения до запретов, дефолты мутацией вместо
   отказов, метрики отказов и разбор обходов.

</details>

**9.** Как проверять политики до кластера?

<details><summary>Ответ</summary>

`kubectl apply --dry-run=server`, `kyverno apply`/`kyverno test`, `gator` для Gatekeeper,
   unit-тесты вебхука.

</details>

**10.** Писали ли вы свой вебхук? Что в нём было сложного?

<details><summary>Ответ</summary>

Пример: вебхук уникальности host — AdmissionReview, JSONPatch с экранированием, TLS
    через cert-manager, `failurePolicy` и исключения, HA, тесты с фейковым API.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Называю порядок admission и помню, что defaulting — до него
- [ ] ⭐ Пишу VAP с `variables`, `namespaceObject`, `messageExpression` и параметрами
- [ ] Пишу MAP с `ApplyConfiguration` и знаю её статус в 1.36
- [ ] ⭐ Написал вебхук на FastAPI: AdmissionReview v1, JSONPatch, warnings, TLS
- [ ] Настраиваю `failurePolicy`, `timeoutSeconds`, селекторы и исключения
- [ ] ⭐ Поднимал кластер после «кирпича» от вебхука
- [ ] Использую Kyverno: validate с autogen, mutate дефолтов, generate с synchronize, отчёты
- [ ] Раскатываю политики Audit → Warn → Deny
- [ ] Выбираю между VAP, MAP, Kyverno и вебхуком
- [ ] Пишу сообщения отказа по схеме «что — почему — как — ссылка»
