---
title: "05. Gateway API глубже и service mesh"
description: "Блок → Platform Engineering → трафик. Основы Gateway API (GatewayClass → Gateway →"
---

# 05. Gateway API глубже и service mesh

> Блок → Platform Engineering → **трафик**. Основы Gateway API (GatewayClass → Gateway →
> HTTPRoute, веса, фильтры, ReferenceGrant, `allowedRoutes`) — в
> [../Kubernetes/12_ingress.md](/kubernetes/12-ingress) §7, здесь их не повторяем.
> Вопросы собеса: *«Как дать десяти командам один вход и не дать им сломать друг друга?»*,
> *«Зачем вам service mesh и что он стоит?»*, *«Чем ambient отличается от sidecar?»*
> **После темы ты умеешь:** разделить один Gateway между командами так, чтобы никто не угнал
> чужой домен, повесить на маршрут rate limit и авторизацию политиками Envoy Gateway,
> поднять Istio ambient в kind, увидеть mTLS между подами linkd и разделить трафик
> через HTTPRoute на Service, а главное — объяснить, когда mesh не нужен.
> Версии — «проверь, сентябрь 2026».

---

## 🗺️ Карта темы

```text
 клиенты ──► ns infra (платформа): GatewayClass eg ─► Gateway web, listener на домен команды
             политики на Gateway: ClientTrafficPolicy (real IP, таймауты), базовый rate limit
                    │ allowedRoutes по метке namespace (метку ставит платформа)
          ┌─────────┴──────────────┐
   ns linkd: HTTPRoute/GRPCRoute   ns shop: HTTPRoute, ReferenceGrant ◄── чужие ссылки
   свои BackendTrafficPolicy,      ListenerSet ── свой домен и сертификат
   SecurityPolicy (API-ключ)
          │ east-west: сервис → сервис
   MESH: sidecar (прокси в поде) или ambient (ztunnel на ноде: L4 + mTLS; waypoint: L7)
         → идентичность SPIFFE и mTLS, L7-политики, метрики без правки кода
```text
---

## 1. Что изменилось в Gateway API к v1.6

Gateway API выпускается отдельно от Kubernetes (нужен кластер 1.30+). С v1.5 — «поезд
релизов»: что готово к дате заморозки, то и едет. На стенде — **v1.6.1**, её ставит
Envoy Gateway v1.9.1 (проверь, сентябрь 2026).

| Версия (дата) | Что перешло в Standard (GA) |
|---------------|-----------------------------|
| v1.0 (10.2023) | GatewayClass, Gateway, HTTPRoute |
| v1.1 (05.2024) | ⭐ **GRPCRoute**, поддержка mesh (GAMMA: HTTPRoute с `parentRefs` на Service) |
| v1.2 (10.2024) | `timeouts` в HTTPRoute, `infrastructure` у Gateway, `appProtocol` |
| v1.3 (04.2025) | Зеркалирование по проценту (`requestMirror.percent` / `fraction`) |
| v1.4 (06.10.2025) | ⭐ **BackendTLSPolicy**, `supportedFeatures` в статусе GatewayClass, именованные правила (`rules[].name`) |
| v1.5 (27.02.2026) | ⭐ **ListenerSet**, TLSRoute, фильтр CORS, проверка клиентских сертификатов на Gateway, клиентский сертификат Gateway к бэкендам, **ReferenceGrant → v1** |
| v1.6 (30.06.2026) | **TCPRoute и UDPRoute → v1** (v1alpha2 объявлены устаревшими) |

Что **ещё экспериментальное** (канал Experimental, в проде — только если реализация явно
поддерживает): `retry` в HTTPRoute, session persistence, фильтр `ExternalAuth`,
«Gateway по умолчанию», `XBackendTrafficPolicy` (retry budget), **XMesh**, **XBackend** (v1.6).

> 💡 С v1.6 новые экспериментальные ресурсы — в **отдельной группе** `gateway.networking.x-k8s.io`
> с префиксом `X`; при переходе в Standard они переедут в `gateway.networking.k8s.io` без префикса.
> ⚠️ В [../Kubernetes/12_ingress.md](/kubernetes/12-ingress) TCPRoute/UDPRoute ещё экспериментальные,
> а ReferenceGrant — `v1beta1`: так было до v1.5/v1.6. Что умеет **твоя** реализация — в
> `status.supportedFeatures` у GatewayClass (v1.4+), а не в блогах.

---

## 2. ⭐ Мультитенантный Gateway: кто чем владеет

Модель платформы: **платформа** владеет GatewayClass, Gateway, сертификатами и базовыми
политиками (GitOps-репозиторий платформы). **Команда** владеет маршрутами и своими
политиками в своём namespace (рядом с чартом или LinkdApp).

Риски общего входа:

| Риск | Как выглядит | Защита |
|------|--------------|--------|
| **Угон домена** | Команда B создаёт HTTPRoute с `hostnames: [pay.example.com]` на listener `*.example.com` | Listener на домен команды + `allowedRoutes` только для её namespace; или VAP на `hostnames` (тема 04) |
| Самовыдача доступа | Команда сама ставит на свой namespace метку `gateway-access=true` | Метки namespace ставит платформа (namespace создаются через GitOps, у команд нет `patch namespaces`) или селектор по `kubernetes.io/metadata.name` |
| Конфликт маршрутов | Два HTTPRoute на один host + path | По спецификации побеждает **самый старый** маршрут (creationTimestamp), затем по алфавиту `namespace/name`; проигравший — всё равно `Accepted`, поэтому конфликт незаметен. Защита — один host = одна команда |
| Чужие типы маршрутов | Кто-то цепляет TCPRoute на HTTP-порт | `allowedRoutes.kinds` |
| Лимиты Envoy | Одна команда съедает соединения всех | Базовые лимиты на Gateway (§6), отдельный Gateway для «шумных» |

```yaml
# platform/gateway-web.yaml — ns infra, владелец: платформа
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: web
  namespace: infra
spec:
  gatewayClassName: eg
  allowedListeners:                    # v1.5: кто может приносить свои ListenerSet
    namespaces:
      from: Selector
      selector: { matchLabels: { platform.example.com/own-listeners: "true" } }
  listeners:
    - name: linkd                      # домен команды linkd — только её namespace
      protocol: HTTPS
      port: 443
      hostname: "*.linkd.example.com"
      tls: { mode: Terminate, certificateRefs: [{ name: wildcard-linkd, namespace: certs }] }
      allowedRoutes:
        kinds: [{ kind: HTTPRoute }, { kind: GRPCRoute }]
        namespaces:
          from: Selector
          selector: { matchLabels: { platform.example.com/team: linkd } }   # метку ставит платформа
    # listener shop — так же: hostname "*.shop.example.com", selector team: shop
```text
Маршрут команды не может выйти за свой listener: hostname маршрута должен пересекаться
с hostname listener'а, иначе `Accepted=False` (`NoMatchingListenerHostname`).

### ListenerSet (v1.5): команда приносит свой listener

Раньше новый домен = правка общего Gateway. **ListenerSet** — отдельный объект в namespace
команды со своими listeners и сертификатами; контроллер сливает их с Gateway, если его
`allowedListeners` пускает этот namespace. Бонус — больше 64 listeners на один Gateway.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: ListenerSet
metadata: { name: linkd-vanity, namespace: linkd }
spec:
  parentRef: { name: web, namespace: infra }
  listeners:                           # свой «красивый» домен; Secret — в ns linkd
    - { name: short-kz, protocol: HTTPS, port: 443, hostname: s.example.kz,
        tls: { certificateRefs: [{ name: s-example-kz }] } }
```text
HTTPRoute цепляется к нему через `parentRefs: [{ kind: ListenerSet, name: linkd-vanity }]`.
Статус ListenerSet (`Accepted`, `Programmed`, по listener'ам) показывает, принял ли его Gateway.

> ⚠️ ListenerSet — это делегирование TLS и доменов. Кто может создать ListenerSet, тот
> может заявить любой hostname. Для этого и нужны `allowedListeners` по метке и политика
> (VAP/Kyverno) «namespace X может заявлять только домены из своего списка».

---

## 3. ReferenceGrant: ссылки через namespace

С v1.5 — `gateway.networking.k8s.io/v1`. Принцип «рукопожатия»: ссылающийся объект указывает
чужой namespace, **владелец цели** разрешает это ReferenceGrant'ом в своём namespace.

| Кто ссылается | На что | Что нужно |
|---------------|--------|-----------|
| HTTPRoute (ns team) → Gateway (ns infra) | `parentRefs` | `allowedRoutes` на listener'е, ReferenceGrant **не нужен** |
| Gateway (ns infra) → Secret (ns certs) | `certificateRefs` | ReferenceGrant в `certs`: from Gateway/infra, to Secret |
| HTTPRoute (ns linkd) → Service (ns auth) | `backendRefs` | ReferenceGrant в `auth`: from HTTPRoute/linkd, to Service |
| ListenerSet (ns team) → Secret (свой ns) | `certificateRefs` | Ничего |

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: ReferenceGrant
metadata: { name: linkd-to-auth, namespace: auth }   # ⭐ namespace ЦЕЛИ
spec:
  from: [{ group: gateway.networking.k8s.io, kind: HTTPRoute, namespace: linkd }]
  to: [{ group: "", kind: Service, name: auth-api }]   # name сужает до одного Service
```text
Без ReferenceGrant маршрут получает `ResolvedRefs=False` с причиной `RefNotPermitted`,
а Envoy отвечает **500** на это правило. Удаление ReferenceGrant отзывает доступ сразу —
это такой же объект безопасности, как RoleBinding, и его ревьюит владелец цели.

---

## 4. Маршруты глубже

### Совпадения, именованные правила, зеркалирование, таймауты

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata: { name: linkd, namespace: linkd }
spec:
  parentRefs: [{ name: web, namespace: infra, sectionName: linkd }]
  hostnames: ["go.linkd.example.com"]
  rules:
    - name: api-write                  # v1.4: имя правила — для статуса, метрик и политик
      matches:
        - path: { type: PathPrefix, value: /api/links }
          method: POST
      timeouts: { request: 5s, backendRequest: 2s }   # весь запрос / одна попытка до бэкенда
      backendRefs: [{ name: linkd, port: 80 }]
    - name: beta-testers               # ?beta=1 или заголовок — в новую версию
      matches:
        - path: { type: PathPrefix, value: /r/ }
          queryParams: [{ name: beta, value: "1" }]
        - path: { type: PathPrefix, value: /r/ }
          headers: [{ name: X-Linkd-Beta, value: "true" }]   # matches между собой — ИЛИ
      backendRefs: [{ name: linkd-v2, port: 80 }]
    - name: redirects
      matches: [{ path: { type: PathPrefix, value: /r/ } }]
      filters:
        - type: RequestMirror          # тень: копия 10% запросов в v2, ответ v2 выбрасывается
          requestMirror:
            backendRef: { name: linkd-v2, port: 80 }
            percent: 10
      backendRefs: [{ name: linkd, port: 80 }]
```text
- Внутри одного `matches[]` условия объединяются через **И**, элементы списка — через **ИЛИ**.
- Зеркалирование проверяет новую версию на реальном трафике без риска для пользователя —
  но только для **идемпотентных** запросов: зеркальный `POST /api/links` создаст ссылку
  второй раз (в другой базе — полбеды, в той же — дубли).
- `timeouts.request` ≥ `backendRequest`; при превышении Envoy отвечает **504**.
- **Ретраи**: поле `retry` в HTTPRoute пока Experimental. В Envoy Gateway ретраи задают
  `BackendTrafficPolicy` (§6). Ретраи + таймауты считают вместе, иначе retry storm —
  [../SRE/06_reliability_patterns.md](/sre/06-reliability-patterns).

### GRPCRoute

gRPC — это HTTP/2 с путём `/&lt;package.Service&gt;/&lt;Method&gt;`, но матчить его HTTPRoute'ом
неудобно. GRPCRoute (GA с v1.1) матчит по сервису и методу:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: GRPCRoute
metadata: { name: stats, namespace: linkd }
spec:
  parentRefs: [{ name: web, namespace: infra, sectionName: linkd }]
  hostnames: ["grpc.linkd.example.com"]
  rules:
    - matches:
        - method: { service: linkd.stats.v1.Stats, method: TopLinks }   # type: Exact по умолчанию
          headers: [{ name: x-tenant, value: kz }]
      backendRefs: [{ name: linkd-stats-grpc, port: 9090 }]
    - matches: [{ method: { service: linkd.stats.v1.Stats } }]          # весь сервис
      backendRefs: [{ name: linkd-stats-grpc, port: 9090 }]
```text
У Service бэкенда укажи `appProtocol: kubernetes.io/h2c` (gRPC без TLS) — иначе реализация
может ходить к нему по HTTP/1.1. HTTPRoute и GRPCRoute с пересекающимися hostnames
на одном listener'е спецификация разрешает реализации **отклонить**: тот маршрут, что
прицепился вторым, получит `Accepted=False`. Нужны REST и gRPC на одном домене — оба на HTTPRoute.

Ещё из Standard: фильтр **CORS** (v1.5) вместо политики реализации, **TLSRoute** (v1.5) — маршрут
по SNI с `Passthrough` или `Terminate`, **TCPRoute/UDPRoute** (v1.6) — L4-вход, например PostgreSQL
для внешнего BI через listener `protocol: TCP`.

---

## 5. BackendTLSPolicy: TLS от Gateway до пода

По умолчанию Gateway снимает TLS, и до пода идёт открытый HTTP. Если бэкенд сам слушает
HTTPS (требование регулятора, legacy-сервис), нужна **BackendTLSPolicy** (GA с v1.4):

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: BackendTLSPolicy
metadata: { name: billing-tls, namespace: billing }
spec:
  targetRefs:
    - { group: "", kind: Service, name: billing, sectionName: https }   # порт Service по имени
  validation:
    caCertificateRefs: [{ group: "", kind: ConfigMap, name: billing-ca }]   # или wellKnownCACertificates: System
    hostname: billing.billing.svc     # SNI и проверка сертификата пода
```text
Если сертификатом управляет mesh (§7), BackendTLSPolicy не нужна: mTLS делает сам mesh.
Клиентский сертификат Gateway к бэкенду (mTLS «наверх») — `spec.tls.backend.clientCertificateRef`
у Gateway (v1.5).

---

## 6. ⭐ Policy attachment и расширения Envoy Gateway

Всё, чего нет в ядре API, реализации добавляют **политиками**: отдельными CRD, которые
цепляются к Gateway, listener'у, маршруту или правилу через `targetRefs` (+ `sectionName`).
Объект маршрута не меняется, а владельцем политики может быть другая команда.

| CRD Envoy Gateway (`gateway.envoyproxy.io/v1alpha1`) | Куда цепляется | Что задаёт |
|--------------------------|----------------|------------|
| ⭐ `ClientTrafficPolicy` | Gateway, listener, ListenerSet | Сторона клиента: таймауты и keepalive, определение реального IP (`clientIPDetection`), TLS-настройки, HTTP/3, лимиты соединений |
| ⭐ `BackendTrafficPolicy` | Gateway, HTTPRoute, GRPCRoute, правило | Сторона бэкенда: **rate limit**, ретраи, circuit breaker, балансировка, health checks, таймауты |
| ⭐ `SecurityPolicy` | Gateway, HTTPRoute, GRPCRoute, правило | JWT, OIDC, basic auth, **API-ключи**, extAuth, **authorization** (IP, JWT-claims), CORS, CSRF (v1.9) |
| `EnvoyExtensionPolicy` | Gateway, маршрут | Wasm, ext_proc, Lua (с v1.9 Lua выключен по умолчанию, `enableLua`) |
| `EnvoyPatchPolicy` | Gateway | Сырой патч xDS — последнее средство, ломается при обновлении |
| `EnvoyProxy` | GatewayClass / Gateway (`infrastructure.parametersRef`) | Сами поды Envoy: реплики, ресурсы, PDB, тип Service |

**Приоритет** (для BackendTrafficPolicy, у других похоже — проверь): правило маршрута
(`sectionName`) → маршрут → listener → Gateway. Без `mergeType` берётся **только самая
конкретная** политика, остальные не применяются; с `mergeType` маршрутная политика
дополняет базовую. ⚠️ Политика цепляется **только к объектам своего namespace** — поэтому
платформа ставит базовые политики на Gateway в `infra`, а команды — на свои маршруты.

```yaml
# платформа, ns infra: реальный IP клиента и таймауты для всех
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: ClientTrafficPolicy
metadata: { name: web-defaults, namespace: infra }
spec:
  targetRefs: [{ group: gateway.networking.k8s.io, kind: Gateway, name: web }]
  clientIPDetection:
    xForwardedFor: { numTrustedHops: 1 }   # v1.9: ровно один из xForwardedFor / customHeader / directSourceIP
  timeout: { http: { requestReceivedTimeout: 30s } }
---
# команда linkd, ns linkd: лимит на создание ссылок
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: BackendTrafficPolicy
metadata: { name: linkd-write-limit, namespace: linkd }
spec:
  targetRefs:
    - { group: gateway.networking.k8s.io, kind: HTTPRoute, name: linkd, sectionName: api-write }
  rateLimit:
    local: { rules: [{ limit: { requests: 20, unit: Minute } }] }   # на каждый под Envoy, без Redis
  retry:
    numRetries: 2
    perRetry: { timeout: 1s, backOff: { baseInterval: 100ms, maxInterval: 1s } }
    retryOn: { triggers: [connect-failure, reset] }    # не ретраим 5xx на POST
---
# команда linkd: API-ключ на запись
apiVersion: gateway.envoyproxy.io/v1alpha1
kind: SecurityPolicy
metadata: { name: linkd-write-auth, namespace: linkd }
spec:
  targetRefs:
    - { group: gateway.networking.k8s.io, kind: HTTPRoute, name: linkd, sectionName: api-write }
  apiKeyAuth:
    credentialRefs: [{ group: "", kind: Secret, name: linkd-api-keys }]   # ключи Secret = client-id, значения = ключи
    extractFrom: [{ headers: [x-api-key] }]
```text
Ответы Envoy: **429** + `x-envoy-ratelimited: true` — rate limit; **401** — нет или неверный
ключ/JWT/пароль; **403** — запретил `authorization` (IP, claim).

- `local` rate limit считается **на под Envoy и на маршрут**: 3 реплики Envoy × 20 = до 60 в минуту.
  Точный общий лимит («100 запросов в минуту на пользователя») — `global` с Redis
  (`rateLimit.global` + настройка rate limit-сервиса в EnvoyGateway).
- Basic auth — Secret с ключом `.htpasswd`; IP-allowlist — `authorization.defaultAction: Deny`
  + `principal.clientCIDRs`, и без правильного `clientIPDetection` он видит IP балансировщика.

> 💡 Политики привязаны к реализации: `BackendTrafficPolicy` не переедет в Istio или Cilium.
> Для платформы это аргумент **обернуть** их в свой API: в LinkdApp (тема 03) поле
> `rateLimit: 20/min`, а оператор создаёт политику нужной реализации.

---

## 7. Service mesh: что он добавляет

Gateway закрывает **north-south** (клиент → кластер). Mesh — про **east-west**
(сервис → сервис внутри кластера). Обзор — [../Kubernetes/21_advanced_paths.md](/kubernetes/21-advanced-paths) §3,
устройство Envoy — [../Network/18_modern_proxies.md](/network/18-modern-proxies) §3.

| Что даёт | Как | Без mesh |
|----------|-----|----------|
| ⭐ **Идентичность и mTLS** | Каждому ServiceAccount — сертификат SPIFFE (`spiffe://cluster.local/ns/linkd/sa/linkd`), ротация автоматически | TLS в каждом приложении, свой CA, ротация руками |
| Авторизация по идентичности | «В `linkd-db` можно только от `sa/linkd`» — на L4 или L7 | NetworkPolicy по IP/меткам, без криптографии |
| L7-трафик | Ретраи, таймауты, веса, зеркало для вызовов внутри кластера | Библиотеки в коде каждого сервиса |
| ⭐ Телеметрия | «Золотые» метрики (RPS, ошибки, задержка) и карта сервисов **без правки кода** | Метрики в каждом сервисе, OpenTelemetry |

**GAMMA** — Gateway API для mesh: тот же HTTPRoute, но `parentRefs` указывает на **Service**,
а не на Gateway. Маршрут действует на трафик **к этому Service** изнутри кластера.
Istio, Linkerd и Cilium понимают один и тот же YAML — это ровно то, что нужно canary в теме 06.

---

## 8. Sidecar, ambient, sidecarless

| Модель | Как устроено | Плюсы | Минусы |
|--------|--------------|-------|--------|
| **Sidecar** (Istio classic, Linkerd) | Прокси-контейнер в каждом поде, iptables/CNI заворачивают трафик | Изоляция на под, зрелость, полный L7 везде | Память × число подов, рестарт подов при включении и обновлении, порядок старта с Job'ами |
| ⭐ **Ambient** (Istio) | **ztunnel** — DaemonSet на ноде (Rust): L4 + mTLS по протоколу HBONE (порт 15008); **waypoint** — Envoy на namespace или Service, только если нужен L7 | Включение меткой namespace **без рестарта подов**, платишь за L7 только там, где он нужен | Моложе, L7 — лишний хоп через waypoint, ztunnel — общий для всех подов ноды |
| **Sidecarless на eBPF** (Cilium Service Mesh) | eBPF в ядре + Envoy на ноде для L7 | Нет прокси в поде, если Cilium уже CNI | Привязка к CNI, mTLS-модель отличается |

| Факт (проверь, сентябрь 2026) | |
|-------------------------------|---|
| Istio | **1.31** (27.08.2026), патч 1.31.1; Kubernetes **1.32–1.36**; ambient — GA с 1.24 (11.2024); ставит Gateway API v1.6.0; с 1.31 артефакты не на gcr.io, а на Docker Hub / `ghcr.io/istio/release/charts` |
| Linkerd | **2.20** (23.06.2026); open source выпускает **только edge-релизы** (`edge-YY.M.N`, последний edge-26.9.3), stable-сборки с февраля 2024 — у вендоров (Buoyant Enterprise for Linkerd, по лицензии) |
| Linkerd 2.20 и стенд | Официально Kubernetes 1.31–1.35 и Gateway API 1.2.1–1.5.1 — а на стенде 1.36 и Gateway API 1.6.1 от Envoy Gateway. Поэтому лаба — на **Istio ambient** |

---

## 🧪 Мини-лаба: Istio ambient + linkd в kind

Стенд: кластер `platform` (`kindest/node:v1.36.4`) с Envoy Gateway из [00_INDEX.md](/platform/);
образ `linkd:2.0.0` собран в `12-autopilot/app` (`docker build -t linkd:2.0.0 -f ../04-shipyard/docker/Dockerfile .`)
и загружен `kind load docker-image linkd:2.0.0 --name platform`. Нужно ~1,5 ГБ RAM сверх стенда.

**Шаг 1. Две версии linkd**, v2 — «плохая»: каждый ответ на `/r/*` — 500 (учебный сбой из CHANGELOG linkd).

```yaml
# linkd-v1.yaml
apiVersion: apps/v1
kind: Deployment
metadata: { name: linkd-v1, namespace: linkd }
spec:
  selector: { matchLabels: { app: linkd, version: v1 } }
  template:
    metadata: { labels: { app: linkd, version: v1 } }
    spec:
      volumes: [{ name: data, emptyDir: {} }]
      containers:
        - { name: linkd, image: "linkd:2.0.0", imagePullPolicy: Never, ports: [{ containerPort: 8080 }],
            readinessProbe: { httpGet: { path: /readyz, port: 8080 } },
            volumeMounts: [{ name: data, mountPath: /var/lib/linkd }] }
```text
```bash
kubectl create namespace linkd && kubectl create namespace client
kubectl apply -f linkd-v1.yaml
sed 's/linkd-v1/linkd-v2/; s/version: v1/version: v2/g' linkd-v1.yaml | kubectl apply -f -
kubectl -n linkd set env deploy/linkd-v2 LINKD_FAULT_ERROR_RATE=1
# linkd — «общий» Service для клиентов, linkd-v1/-v2 — по версиям
for s in "linkd:app=linkd" "linkd-v1:app=linkd,version=v1" "linkd-v2:app=linkd,version=v2"; do
  kubectl -n linkd create service clusterip "${s%%:*}" --tcp=80:8080 --dry-run=client -o yaml \
    | kubectl set selector --local -f - "${s#*:}" -o yaml | kubectl -n linkd apply -f -
done
kubectl -n client run curl --image=curlimages/curl --command -- sleep infinity
```text
**Шаг 2. Istio ambient и mesh без рестарта подов.**

```bash
curl -L https://istio.io/downloadIstio | ISTIO_VERSION=1.31.1 sh -
export PATH=$PWD/istio-1.31.1/bin:$PATH
istioctl install --set profile=ambient --skip-confirmation   # istiod + istio-cni + ztunnel (DaemonSet)

kubectl label namespace linkd client istio.io/dataplane-mode=ambient
kubectl -n linkd get pods                                     # AGE не сбросился, контейнеров 1/1
istioctl ztunnel-config workloads | grep -E "linkd|curl"      # PROTOCOL = HBONE
kubectl -n client exec curl -- curl -s linkd.linkd/healthz
kubectl -n istio-system logs ds/ztunnel --tail=20 | grep linkd
# ... src.identity="spiffe://cluster.local/ns/client/sa/default"
#     dst.identity="spiffe://cluster.local/ns/linkd/sa/default" direction="outbound"
```text
**Шаг 3. Строгий mTLS.**

```bash
kubectl apply -f - <<'YAML'
apiVersion: security.istio.io/v1
kind: PeerAuthentication
metadata: { name: strict, namespace: linkd }
spec: { mtls: { mode: STRICT } }
YAML
kubectl -n client exec curl -- curl -s -o /dev/null -w "%{http_code}\n" linkd.linkd/healthz   # 200
kubectl run outsider --image=curlimages/curl --rm -it --restart=Never -- \
  curl -s -m 3 linkd.linkd/healthz; echo "exit=$?"    # default вне mesh → соединение сброшено
```text
> ⚠️ Envoy Gateway (`envoy-gateway-system`) тоже вне mesh: после `STRICT` вход через Gateway
> в linkd сломается. Добавь namespace Gateway в ambient и проверь curl'ом через port-forward.

**Шаг 4. Waypoint, L7-авторизация и 90/10 через HTTPRoute на Service (GAMMA).**

```bash
istioctl waypoint apply -n linkd --enroll-namespace --wait    # Gateway класса istio-waypoint
```text
```yaml
# l7.yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata: { name: linkd-split, namespace: linkd }
spec:
  parentRefs: [{ group: "", kind: Service, name: linkd, port: 80 }]   # ⭐ родитель — Service
  rules:
    - backendRefs: [{ name: linkd-v1, port: 80, weight: 90 }, { name: linkd-v2, port: 80, weight: 10 }]
---
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy                      # исполняет waypoint: кто и какими методами
metadata: { name: linkd-l7, namespace: linkd }
spec:
  targetRefs: [{ kind: Service, group: "", name: linkd }]
  action: ALLOW
  rules:
    - from: [{ source: { principals: ["cluster.local/ns/client/sa/default"] } }]
      to: [{ operation: { methods: ["GET"] } }]
```text
```bash
kubectl apply -f l7.yaml
kubectl -n client exec curl -- sh -c \
  'for i in $(seq 200); do curl -s -o /dev/null -w "%{http_code}\n" linkd.linkd/r/nope; done' | sort | uniq -c
#  ~180 404   ← v1: такого кода нет
#   ~20 500   ← v2: учебный сбой
kubectl -n client exec curl -- curl -s -X POST -d '{"url":"https://kz"}' linkd.linkd/api/links  # RBAC: access denied (403)
```text
**Шаг 5. Золотые метрики без кода и цена.**

```bash
kubectl apply -f istio-1.31.1/samples/addons/prometheus.yaml && istioctl dashboard prometheus &
```text
```promql
# ошибки по версиям считает waypoint — linkd о mesh ничего не знает
sum by (destination_workload, response_code) (rate(istio_requests_total{destination_service_namespace="linkd"}[1m]))
# L4 от ztunnel: соединения с mutual_tls
sum by (source_workload, connection_security_policy) (rate(istio_tcp_connections_opened_total[5m]))
```text
`kubectl top pods -n istio-system` и `kubectl top pods -n linkd`: запиши память ztunnel,
istiod и waypoint и сравни с памятью самого linkd.

**Проверь себя:** почему после шага 2 поды не перезапустились, а в sidecar-модели пришлось бы?
Почему без waypoint HTTPRoute на Service не делит трафик? Что станет с L4-политикой
«только от `sa/default` из client» на подах linkd после появления waypoint?

Уборка: `istioctl uninstall --purge -y && kubectl delete ns istio-system linkd client`.

> 💬 **Вариант на Linkerd** (если сходится матрица, `linkerd check --pre`): CLI через
> `https://run.linkerd.io/install-edge`, затем `linkerd install --crds | kubectl apply -f -` и
> `linkerd install | kubectl apply -f -`; `kubectl annotate ns linkd linkerd.io/inject=enabled`
> + `rollout restart` (sidecar!); метрики — `linkerd viz install`, `linkerd viz stat deploy -n linkd`.

---

## 9. Цена mesh

| Статья | Что это значит | Ориентир (проверь на своём стенде) |
|--------|----------------|------------------------------------|
| Память и CPU | Sidecar: прокси в каждом поде; ambient: ztunnel на ноду + waypoint'ы | Envoy-sidecar — десятки МБ на под, linkerd2-proxy — заметно меньше; ztunnel — один на ноду |
| Задержка | Лишний хоп и TLS-рукопожатия | Единицы миллисекунд на запрос на p99, waypoint — ещё хоп |
| Обновления | Control plane + data plane; в sidecar-модели — рестарт **всех** подов | Istio: поддержка минорной версии ~6 месяцев (до N+2 + 6 недель) — обновляться два раза в год |
| Отладка | «503 UF», «connection reset» — ещё один слой, где может быть причина | Нужны люди, которые читают `istioctl proxy-config`/`ztunnel-config` |
| Сертификаты | Корневой CA mesh — ещё один секрет с ротацией | Для multi-cluster — общий корень доверия |
| Совместимость | CNI, NetworkPolicy, Job'ы, init-контейнеры, не-HTTP протоколы | В sidecar-модели Job не завершается, пока жив прокси (native sidecar помогает) |

---

## 10. Когда mesh НЕ нужен

- Сервисов < 10–15 у одной-двух команд — ретраи и таймауты в коде, метрики RED из приложения
  (linkd их уже отдаёт), NetworkPolicy между namespace.
- Нет требования шифровать трафик **внутри** кластера (регулятор, PCI DSS, zero trust) — а это
  главный честный повод для mesh.
- Нужна только canary — хватит Gateway API на входе (тема 06); только телеметрия — OpenTelemetry
  ([../SRE/03_tracing_opentelemetry.md](/sre/03-tracing-opentelemetry)).
- Нет людей, готовых дежурить по mesh и обновлять его два раза в год.

**Когда нужен:** десятки сервисов нескольких команд, требование mTLS и авторизации по
идентичности, canary/зеркало для внутренних вызовов, единая телеметрия без правки кода
в сервисах на разных языках. Начинай с ambient только-L4 (mTLS) и добавляй waypoint точечно.

---

## 11. Грабли

| Грабля | Что происходит | Как избежать |
|--------|----------------|--------------|
| Один listener `*.example.com` с `from: All` | Любая команда заявляет чужой домен | Listener на домен команды, метки ставит платформа, VAP на `hostnames` |
| Команды сами метят namespace | Сами себе выдают доступ к Gateway | Namespace через GitOps платформы, RBAC без `patch namespaces` |
| Два маршрута на один host+path | Молча побеждает старший, второй `Accepted` | Один host — одна команда, проверка в CI/VAP |
| Маршрутная BackendTrafficPolicy без `mergeType` | Базовый лимит платформы перестаёт действовать для маршрута | `mergeType` или дублировать базу |
| `local` rate limit считают глобальным | Лимит × число подов Envoy | Помнить множитель или `global` с Redis |
| HTTPRoute и GRPCRoute на одном hostname | Второй маршрут может получить `Accepted=False` | Разные hostnames или оба на HTTPRoute |
| Linkerd на Gateway API новее своей матрицы | Трудноуловимые ошибки маршрутизации | Сверять `bundle-version` CRD с таблицей совместимости |
| `STRICT` mTLS, а Gateway вне mesh | Вход в сервис ломается | Gateway в mesh или исключение для его принципала |
| L4-политика с `selector` после появления waypoint | ztunnel видит источником `sa/waypoint` — клиентам отказ | L4 — «только от waypoint», проверка клиента — на waypoint через `targetRefs` |
| Mesh «на всякий случай» | Память, задержка, ещё одна система для обновлений | Сначала требования (§10) |

---

## 💼 Как это в DevOps

- Gateway — общий ресурс платформы, как DNS-зона: объекты в GitOps-репозитории платформы,
  `allowedRoutes`, ListenerSet и ReferenceGrant ревьюят как RBAC.
- Команды не пишут политики реализации руками: поля `rateLimit`, `auth`, `timeout` в LinkdApp
  или чарте, оператор генерирует `BackendTrafficPolicy`/`SecurityPolicy`. Смена реализации —
  задача платформы, а не всех команд.
- Базовый набор на Gateway в первый день: реальный IP клиента, таймауты, лимит на IP,
  запрет старого TLS, ≥ 2 реплики Envoy с PDB (через `EnvoyProxy`).
- Mesh внедряют по требованию mTLS или когда сервисов много и языки разные. Путь 2026 года —
  Istio ambient: сначала только ztunnel (mTLS, L4-авторизация), waypoint — точечно.
- Честное «mesh нам пока не нужен, вот почему» на собесе ценится выше списка фич Istio.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Узнать, что умеет реализация | `kubectl get gatewayclass eg -o jsonpath='{.status.supportedFeatures}'` |
| Пустить в listener только namespace команды | `allowedRoutes.namespaces.from: Selector` + метка, которую ставит платформа |
| Команда приносит свой домен и сертификат | `ListenerSet` + `allowedListeners` на Gateway |
| Маршрут на Service в чужом namespace | `backendRefs.namespace` + `ReferenceGrant` в namespace цели |
| Тень трафика | Фильтр `RequestMirror` с `percent` |
| gRPC по сервису и методу | `GRPCRoute` + `matches[].method` |
| Rate limit | `BackendTrafficPolicy.rateLimit.local.rules[].limit` |
| API-ключ / IP-allowlist | `SecurityPolicy.apiKeyAuth` / `authorization.rules[].principal.clientCIDRs` |
| Включить mesh для namespace | `kubectl label ns linkd istio.io/dataplane-mode=ambient` |
| Проверить mTLS | `istioctl ztunnel-config workloads` (HBONE), логи ztunnel `src.identity` |
| L7 в ambient | `istioctl waypoint apply -n linkd --enroll-namespace` |
| Canary внутри кластера | HTTPRoute с `parentRefs: [{group: "", kind: Service, name: linkd}]` |

---

## 🧠 Что запомнить

1. Gateway API v1.6: в Standard — GRPCRoute, BackendTLSPolicy, ListenerSet, TLSRoute, CORS,
   ReferenceGrant v1, TCPRoute/UDPRoute v1; ретраи в HTTPRoute — ещё Experimental.
2. Новые экспериментальные ресурсы — в группе `gateway.networking.x-k8s.io` с префиксом `X`.
3. ⭐ Мультитенантность: платформа владеет Gateway и метками namespace, команда — маршрутами;
   listener на домен команды защищает от угона hostname.
4. Конфликт маршрутов решает возраст объекта — один host должен принадлежать одной команде.
5. ⭐ ReferenceGrant создаёт владелец **цели** в своём namespace; для `parentRefs` он не нужен —
   там работает `allowedRoutes`.
6. ListenerSet — делегирование listener'ов и сертификатов командам через `allowedListeners`.
7. ⭐ Policy attachment: `targetRefs` + `sectionName`; у Envoy Gateway — ClientTrafficPolicy,
   BackendTrafficPolicy, SecurityPolicy; самая конкретная политика побеждает, цель — только в своём namespace.
8. `local` rate limit — на каждый под Envoy; точный общий лимит — `global` с Redis.
9. ⭐ Mesh = идентичность и mTLS + L7-политики + телеметрия без кода; GAMMA — HTTPRoute
   с родителем-Service.
10. Ambient: ztunnel на ноде (L4, mTLS, HBONE), waypoint — только для L7; включается меткой
    namespace без рестарта подов.
11. Linkerd OSS — только edge-релизы, stable — у Buoyant; сверяй матрицу Kubernetes и Gateway API.
12. ⭐ Mesh стоит памяти, задержки, обновлений и отладки; без требования mTLS и десятков
    сервисов он чаще не нужен.

➡️ Дальше: [06_progressive_delivery.md](/platform/06-progressive-delivery) · Задачи: 05_gateway_mesh_tasks.md


---

### Блок A. Теория


**A1.** ⭐ Какие ресурсы и фичи Gateway API перешли в Standard в версиях 1.4, 1.5 и 1.6?

<details><summary>Ответ</summary>

v1.4 — BackendTLSPolicy, `supportedFeatures` в статусе GatewayClass, именованные правила.
v1.5 — ListenerSet, TLSRoute, CORS-фильтр, проверка клиентских сертификатов на Gateway,
клиентский сертификат Gateway к бэкендам, ReferenceGrant v1. v1.6 — TCPRoute и UDPRoute v1.

</details>

**A2.** Что изменилось в v1.6 с экспериментальными ресурсами? Как отличить экспериментальный
ресурс от стабильного по одному `apiVersion`?

<details><summary>Ответ</summary>

Новые экспериментальные ресурсы живут в группе `gateway.networking.x-k8s.io` и имеют
префикс `X` (`XMesh`, `XBackend`). Стабильные — в `gateway.networking.k8s.io`. Группа в `apiVersion`
сразу говорит, на что можно опираться.

</details>

**A3.** Где посмотреть, какие фичи Gateway API поддерживает конкретная реализация?

<details><summary>Ответ</summary>

В `status.supportedFeatures` у GatewayClass (Standard с v1.4) и в отчёте о conformance
реализации.

</details>

**A4.** ⭐ Кто в мультитенантной модели владеет GatewayClass, Gateway, HTTPRoute, ReferenceGrant
и политиками? Почему именно так?

<details><summary>Ответ</summary>

GatewayClass и Gateway (listeners, сертификаты, `allowedRoutes`, базовые политики) —
платформа: это общая инфраструктура, ошибка ломает всех. HTTPRoute и маршрутные политики —
команда в своём namespace: она лучше знает свои пути, и ей не нужен тикет. ReferenceGrant —
владелец namespace **цели**: разрешать доступ к своим объектам может только их хозяин.

</details>

**A5.** Что такое «угон домена» на общем Gateway и какими тремя способами от него защищаются?

<details><summary>Ответ</summary>

Команда заявляет в HTTPRoute чужой hostname, и общий listener с `from: All` его принимает.
Защита: listener на домен команды с `allowedRoutes` только для её namespace; метки namespace
ставит платформа; политика admission (VAP/Kyverno), проверяющая `hostnames` по списку домена команды.

</details>

**A6.** Почему метку namespace для `allowedRoutes` должна ставить платформа, а не команда?

<details><summary>Ответ</summary>

Метка — это пропуск. Если команда может менять свой namespace, она сама выдаст себе
доступ к любому listener'у. Namespace создаются через GitOps платформы, у команд нет `patch namespaces`,
либо селектор по неизменяемой `kubernetes.io/metadata.name`.

</details>

**A7.** Два HTTPRoute из разных namespace претендуют на один host и path. Кто победит и почему
конфликт трудно заметить?

<details><summary>Ответ</summary>

Побеждает маршрут с более ранним `creationTimestamp`, при равенстве — первый по алфавиту
`namespace/name`. Проигравший остаётся `Accepted=True`, поэтому конфликт виден только по трафику.

</details>

**A8.** Что такое ListenerSet, какую проблему он решает и что для него должен разрешить Gateway?

<details><summary>Ответ</summary>

Отдельный объект с listeners (и их сертификатами) в namespace команды, который контроллер
сливает с Gateway. Решает: правку общего Gateway ради каждого домена, делегирование TLS и лимит

</details>

**A9.** ⭐ В каких случаях нужен ReferenceGrant, а в каких — нет? В каком namespace он создаётся?

<details><summary>Ответ</summary>

Нужен, когда объект ссылается на объект **в другом namespace** через `backendRefs`
или `certificateRefs`: HTTPRoute → Service, Gateway → Secret. Не нужен для `parentRefs`
(маршрут → Gateway): это регулирует `allowedRoutes`. Создаётся в namespace цели.

</details>

**A10.** Как объединяются условия внутри одного элемента `matches` и между элементами списка?

<details><summary>Ответ</summary>

Внутри одного элемента (`path` + `headers` + `queryParams` + `method`) — И; между
элементами списка `matches` — ИЛИ.

</details>

**A11.** Чем `timeouts.request` отличается от `timeouts.backendRequest`?

<details><summary>Ответ</summary>

`request` — весь запрос от клиента, включая ретраи; `backendRequest` — одна попытка
до бэкенда. `request` ≥ `backendRequest`; при превышении — 504.

</details>

**A12.** Что делает фильтр `RequestMirror` с `percent`, и для каких запросов его опасно включать?

<details><summary>Ответ</summary>

Копирует долю запросов (например, 10%) во второй бэкенд; ответ зеркала выбрасывается.
Опасно для неидемпотентных запросов (`POST`, списания, письма): эффект случится дважды.

</details>

**A13.** Чем GRPCRoute удобнее HTTPRoute для gRPC? Что указать у Service бэкенда?

<details><summary>Ответ</summary>

Матчит по `service` и `method` gRPC, а не по сырым путям HTTP/2. У Service бэкенда —
`appProtocol: kubernetes.io/h2c` (или TLS), иначе реализация может говорить с ним по HTTP/1.1.

</details>

**A14.** Зачем нужна BackendTLSPolicy и когда она не нужна?

<details><summary>Ответ</summary>

Для TLS на участке Gateway → под: бэкенд слушает HTTPS, Gateway проверяет его сертификат
(CA из ConfigMap или системные) и hostname. Не нужна, если это шифрование обеспечивает mesh.

</details>

**A15.** ⭐ Что такое policy attachment? Назови три политики Envoy Gateway и что каждая задаёт.

<details><summary>Ответ</summary>

Расширение API отдельными CRD, которые цепляются к Gateway, listener'у, маршруту или
правилу через `targetRefs` + `sectionName`, не меняя сами объекты. Envoy Gateway:
ClientTrafficPolicy — сторона клиента (real IP, таймауты, TLS, HTTP/3); BackendTrafficPolicy —
сторона бэкенда (rate limit, ретраи, circuit breaker, LB, health checks); SecurityPolicy —
аутентификация и авторизация (JWT, OIDC, basic, API-ключи, extAuth, IP).

</details>

**A16.** Как Envoy Gateway выбирает BackendTrafficPolicy, если их несколько на разных уровнях?
Что меняет `mergeType`?

<details><summary>Ответ</summary>

Самая конкретная побеждает: правило маршрута → маршрут → listener → Gateway; при
равенстве — старшая по `creationTimestamp`, затем по имени. Без `mergeType` применяется только
одна политика; с `mergeType` маршрутная сливается с родительской.

</details>

**A17.** Почему платформа не может повесить BackendTrafficPolicy прямо на HTTPRoute команды?

<details><summary>Ответ</summary>

Политика Envoy Gateway может ссылаться только на объекты своего namespace. Поэтому
платформа задаёт базу на Gateway в `infra`, а маршрутные политики живут у команды.

</details>

**A18.** Чем `local` rate limit отличается от `global`?

<details><summary>Ответ</summary>

`local` — счётчик в каждом поде Envoy и на каждый маршрут: без внешних зависимостей,
но лимит умножается на число реплик. `global` — общий счётчик во внешнем rate limit-сервисе
с Redis: точный лимит на пользователя или ключ, но ещё один компонент.

</details>

**A19.** ⭐ Что добавляет service mesh к Kubernetes? Что из этого нельзя получить без mesh?

<details><summary>Ответ</summary>

Идентичность каждого сервиса и mTLS между ними, авторизацию по идентичности, L7-политики
для внутренних вызовов (ретраи, таймауты, веса, зеркало) и единые метрики без правки кода.
Без mesh не получить автоматическую криптографическую идентичность и шифрование без изменений
в приложениях; остальное можно собрать библиотеками, NetworkPolicy и OpenTelemetry — дороже в разработке.

</details>

**A20.** Что такое GAMMA? Чем HTTPRoute для mesh отличается от HTTPRoute для входа?

<details><summary>Ответ</summary>

Gateway API for Mesh Management and Administration: те же HTTPRoute/GRPCRoute, но
`parentRefs` — Service. Маршрут действует на трафик к этому Service изнутри кластера, а не на вход.

</details>

**A21.** ⭐ Чем отличаются sidecar, ambient и sidecarless-mesh? Что такое ztunnel и waypoint?

<details><summary>Ответ</summary>

Sidecar — прокси в каждом поде (Istio classic, Linkerd): изоляция и полный L7 везде,
но память × поды и рестарты. Ambient — ztunnel (DaemonSet на ноде, Rust) даёт L4 и mTLS по HBONE
(порт 15008), waypoint (Envoy на namespace/Service) — L7 только там, где нужен; включается меткой
без рестарта подов. Sidecarless на eBPF (Cilium) — логика в ядре + Envoy на ноде.

</details>

**A22.** Почему в лабе блока выбран Istio ambient, а не Linkerd? Как сейчас устроены релизы Linkerd?

<details><summary>Ответ</summary>

Linkerd 2.20 официально поддерживает Kubernetes до 1.35 и Gateway API до 1.5.1, а на
стенде 1.36 и 1.6.1; Istio 1.31 — 1.32–1.36 и Gateway API 1.6. Linkerd open source выпускает
только edge-релизы (`edge-YY.M.N`); stable с февраля 2024 — у вендоров, прежде всего Buoyant
Enterprise for Linkerd по лицензии.

</details>

**A23.** Что такое SPIFFE-идентичность и из чего она строится в Istio?

<details><summary>Ответ</summary>

Имя сервиса в формате SPIFFE: `spiffe://&lt;trust domain&gt;/ns/&lt;namespace&gt;/sa/&lt;ServiceAccount&gt;`.
Mesh выпускает на него короткоживущий сертификат и ротирует его сам; политики пишут по этому имени.

</details>

**A24.** ⭐ Назови статьи расходов на mesh.

<details><summary>Ответ</summary>

Память и CPU прокси, задержка (хоп и TLS), обновления control и data plane (в sidecar —
рестарт всех подов, у Istio минорная версия живёт ~6 месяцев), отладка ещё одного слоя, корневой CA,
совместимость с CNI, Job'ами, init-контейнерами.

</details>

**A25.** ⭐ Когда mesh не нужен? Чем его заменить?

<details><summary>Ответ</summary>

Мало сервисов и команд, нет требования mTLS внутри кластера, нужен только canary
(хватит Gateway API на входе) или только телеметрия (OpenTelemetry), некому сопровождать.
Замена: ретраи и таймауты в коде, NetworkPolicy, метрики RED из приложения, OTel.

</details>

---

### Блок B. «Что произойдёт»


```text:no-line-numbers
# B1 — Gateway в infra
```text
```text:no-line-numbers
listeners:
```text
```text:no-line-numbers
  - name: http
```text
```text:no-line-numbers
    protocol: HTTP
```text
```text:no-line-numbers
    port: 80
```text
```text:no-line-numbers
    hostname: "*.example.com"
```text
```text:no-line-numbers
    allowedRoutes: { namespaces: { from: All } }
```text
```text:no-line-numbers
# команда shop создаёт HTTPRoute с hostnames: ["pay.example.com"]
```text
Вопрос: примет ли Gateway маршрут? Чем это плохо?

```text:no-line-numbers
# B2 — listener linkd: hostname "*.linkd.example.com", selector team: linkd
```text
```text:no-line-numbers
# HTTPRoute в ns linkd:
```text
```text:no-line-numbers
hostnames: ["go.example.com"]
```text
Вопрос: какой статус получит маршрут?

```text:no-line-numbers
# B3 — HTTPRoute в ns linkd
```text
```text:no-line-numbers
backendRefs:
```text
```text:no-line-numbers
  - { name: auth-api, namespace: auth, port: 80 }
```text
```text:no-line-numbers
# ReferenceGrant в ns linkd: from HTTPRoute/linkd, to Service
```text
Вопрос: заработает ли? Что ответит Envoy?

```text:no-line-numbers
# B4
```text
```text:no-line-numbers
filters:
```text
```text:no-line-numbers
  - type: RequestMirror
```text
```text:no-line-numbers
    requestMirror: { backendRef: { name: linkd-v2, port: 80 }, percent: 100 }
```text
```text:no-line-numbers
# правило ловит POST /api/links; v1 и v2 смотрят в одну базу PostgreSQL
```text
Вопрос: что увидят пользователи и что будет в базе?

```text:no-line-numbers
# B5 — ns infra
```text
```text:no-line-numbers
kind: BackendTrafficPolicy
```text
```text:no-line-numbers
metadata: { name: base, namespace: infra }
```text
```text:no-line-numbers
spec:
```text
```text:no-line-numbers
  targetRefs: [{ kind: Gateway, name: web }]
```text
```text:no-line-numbers
  rateLimit: { local: { rules: [{ limit: { requests: 100, unit: Second } }] } }
```text
```text:no-line-numbers
---
```text
```text:no-line-numbers
# ns linkd
```text
```text:no-line-numbers
kind: BackendTrafficPolicy
```text
```text:no-line-numbers
metadata: { name: linkd-retry, namespace: linkd }
```text
```text:no-line-numbers
spec:
```text
```text:no-line-numbers
  targetRefs: [{ kind: HTTPRoute, name: linkd }]
```text
```text:no-line-numbers
  retry: { numRetries: 2 }
```text
Вопрос: действует ли базовый лимит на маршрут linkd?

```text:no-line-numbers
# B6
```text
```text:no-line-numbers
rateLimit: { local: { rules: [{ limit: { requests: 20, unit: Minute } }] } }
```text
```text:no-line-numbers
# у Gateway 3 реплики Envoy, балансировщик распределяет равномерно
```text
Вопрос: сколько запросов в минуту реально пройдёт?

```text:no-line-numbers
# B7 — ClientTrafficPolicy отсутствует; за Envoy стоит облачный L7-балансировщик
```text
```text:no-line-numbers
kind: SecurityPolicy
```text
```text:no-line-numbers
spec:
```text
```text:no-line-numbers
  authorization:
```text
```text:no-line-numbers
    defaultAction: Deny
```text
```text:no-line-numbers
    rules: [{ action: Allow, principal: { clientCIDRs: ["203.0.113.0/24"] } }]
```text
Вопрос: пустит ли офис из 203.0.113.0/24?

```text:no-line-numbers
# B8 — Istio ambient
```text
```text:no-line-numbers
kubectl label namespace linkd istio.io/dataplane-mode=ambient
```text
Вопрос: что будет с работающими подами linkd? А при `linkerd.io/inject=enabled`?

```text:no-line-numbers
# B9 — ns linkd в ambient, PeerAuthentication STRICT
```text
```text:no-line-numbers
# Envoy Gateway (ns envoy-gateway-system) не в mesh
```text
Вопрос: что будет с внешним трафиком через Gateway?

```text:no-line-numbers
# B10 — ambient, waypoint не создан
```text
```text:no-line-numbers
kind: HTTPRoute
```text
```text:no-line-numbers
spec:
```text
```text:no-line-numbers
  parentRefs: [{ group: "", kind: Service, name: linkd, port: 80 }]
```text
```text:no-line-numbers
  rules: [{ backendRefs: [{ name: linkd-v1, weight: 90 }, { name: linkd-v2, weight: 10 }] }]
```text
Вопрос: разделится ли трафик?

---

### Блок C. Практика


### C1. 🔑 Мультитенантный Gateway
Подними на стенде Gateway `web` в `infra` с двумя listeners: `*.linkd.example.com` для
namespace с меткой `platform.example.com/team: linkd` и `*.shop.example.com` для `team: shop`.
Разверни в обоих namespace echo-сервер и маршруты. Проверь: маршрут `shop` на `go.linkd.example.com`
получает `Accepted=False`; запросы по обоим доменам доходят до своих сервисов.

### C2. Защита меток
Создай для «команды» ServiceAccount с Role на HTTPRoute в своём namespace. Проверь
`kubectl auth can-i patch namespace shop --as=system:serviceaccount:shop:dev`. Объясни, почему
это проверяют в первую очередь.

### C3. 🔑 ReferenceGrant
Вынеси Service `auth-api` в namespace `auth`. Сошлись на него из HTTPRoute в `linkd` — посмотри
`ResolvedRefs` и код ответа. Добавь ReferenceGrant в правильный namespace, проверь снова,
затем удали его и засеки, через сколько доступ пропал.

### C4. Маршруты глубже
Для linkd: правило `POST /api/links` с таймаутами 5s/2s, правило «бета» по `?beta=1` или
заголовку `X-Linkd-Beta` в linkd-v2, зеркалирование 10% `/r/*` в linkd-v2. Проверь каждое
curl'ом; для зеркала — по логам linkd-v2.

### C5. 🔑 Политики Envoy Gateway
Повесь на правило `api-write` лимит 5 запросов в минуту и API-ключ. Получи 401 без ключа,
**201.** с ключом и 429 на шестом запросе. Проверь, как лимит зависит от числа реплик Envoy.
### C6. Порядок политик
Создай базовую BackendTrafficPolicy на Gateway (rate limit) и маршрутную (retry) без `mergeType`.
Проверь, действует ли базовый лимит на маршрут. Затем добавь `mergeType` и проверь снова.

### C7. 🔑 Мини-лаба ambient
Пройди мини-лабу конспекта: HBONE в `ztunnel-config`, идентичности в логах ztunnel,
STRICT и «чужой» под, waypoint, 90/10 по кодам ответа, L7-запрет POST.

### C8. Вход через Gateway в mesh
После STRICT почини вход через Envoy Gateway в linkd. Опиши, какой вариант выбрал и почему.

### C9. Цена mesh в цифрах
Заполни таблицу: память istiod, ztunnel (на ноду), waypoint, linkd; p50/p99 задержки `curl`
к linkd без mesh, с ztunnel, с waypoint (100 запросов, `-w "%{time_total}"`).

### C10. Решение «нужен ли mesh» (со звёздочкой)
Опиши на полстраницы для компании из 8 сервисов, 2 команд и требования «шифровать трафик
внутри кластера к платёжному сервису». Что выберешь и почему?

---

### Блок D. Инциденты


**D1.** Команда жалуется: их новый HTTPRoute `Accepted=True`, но запросы идут в чужой сервис.
Что проверить?

<details><summary>Ответ</summary>

Нет ли более старого HTTPRoute на тот же host и path в другом namespace (он побеждает
молча); специфичность правил (Exact vs PathPrefix, заголовки); не пересекается ли listener.

</details>

**D2.** После переименования namespace `payments` в `billing` все маршруты, ссылающиеся на его
Service, начали отвечать 500. Почему?

<details><summary>Ответ</summary>

ReferenceGrant лежал в старом namespace и ссылался на старые имена; в `billing` его нет,
и маршруты получили `RefNotPermitted`. Плюс сами `backendRefs.namespace` нужно было поменять.

</details>

**D3.** После обновления Envoy Gateway до v1.9 ClientTrafficPolicy перестала применяться.
Где искать?

<details><summary>Ответ</summary>

В статусе политики (`kubectl get clienttrafficpolicy -o yaml` → conditions) и логах
контроллера: в v1.9 ужесточили валидацию — в `clientIPDetection` должен быть ровно один способ.

</details>

**D4.** Rate limit «не работает»: разработчик делает 30 запросов в минуту при лимите 20 и не
получает 429. Гипотезы?

<details><summary>Ответ</summary>

Несколько реплик Envoy (local-лимит на под); политика прицеплена к другому правилу или
не той `sectionName`; более конкретная политика перекрыла её без `mergeType`; `clientSelectors`
не совпадают; политика `Accepted=False`.

</details>

**D5.** После включения IP-allowlist все пользователи получают 403, включая офис. Почему?

<details><summary>Ответ</summary>

Envoy видит адрес балансировщика или NAT, а не клиента: нет или неверный
`clientIPDetection` (`numTrustedHops`). Проверить по access-логам Envoy, какой IP он считает клиентским.

</details>

**D6.** После включения Istio ambient в namespace перестали проходить health checks kubelet
для одного сервиса. Куда смотреть?

<details><summary>Ответ</summary>

Проверки kubelet в ambient не должны ломаться, но если включён STRICT или
AuthorizationPolicy запрещает всё — смотреть логи ztunnel и события пода, исключения для
проб; при sidecar-модели — переписывание проб и порядок старта.

</details>

**D7.** После создания waypoint часть сервисов стала получать отказы по AuthorizationPolicy,
хотя политики не менялись. Объясни.

<details><summary>Ответ</summary>

С waypoint трафик до пода идёт от идентичности waypoint, и L4-политики с `selector`
видят его, а не исходного клиента. Проверку клиента переносят на waypoint (`targetRefs`),
а на поды разрешают вход от waypoint.

</details>

**D8.** Job'ы в namespace с sidecar-mesh не завершаются и висят `Running`. Причина и лечение?

<details><summary>Ответ</summary>

Контейнер приложения завершился, а прокси-sidecar — нет, и под не переходит в `Completed`.
Лечение: native sidecar (init-контейнер с `restartPolicy: Always`, прокси поддерживает),
завершение прокси из Job (`/quitquitquit` у Istio, `linkerd-await --shutdown`) или ambient.

</details>

---

### Блок E. Вопросы с собеседования


**1.** ⭐ Как бы вы разделили один вход между десятью командами?

<details><summary>Ответ</summary>

Gateway и сертификаты у платформы в GitOps; listener на домен команды с `allowedRoutes`
   по метке namespace, которую ставит платформа; ListenerSet для своих доменов; политика на
   `hostnames`; маршруты и маршрутные политики — у команд; ReferenceGrant — у владельцев целей.

</details>

**2.** Что такое ReferenceGrant и зачем он нужен?

<details><summary>Ответ</summary>

Разрешение владельца namespace на ссылки из чужого namespace (Service, Secret); без него
   маршрут `RefNotPermitted`; создаётся в namespace цели.

</details>

**3.** Чем Gateway API лучше Ingress в мультитенантном кластере?

<details><summary>Ответ</summary>

Роли разделены по объектам, `allowedRoutes`, ссылки через namespace с ReferenceGrant,
   единая спецификация вместо аннотаций контроллера, статусы на каждом объекте.

</details>

**4.** ⭐ Как сделать rate limit и авторизацию на Gateway API?

<details><summary>Ответ</summary>

Ядро API — таймауты, заголовки, CORS; остальное — политики реализации: у Envoy Gateway
   BackendTrafficPolicy (rate limit, local/global) и SecurityPolicy (JWT, API-ключ, IP),
   плюс ClientTrafficPolicy для реального IP; платформа оборачивает их в свой API.

</details>

**5.** ⭐ Зачем service mesh? Что он даёт и что стоит?

<details><summary>Ответ</summary>

mTLS и идентичность, авторизация по ней, L7-политики внутри кластера, метрики без кода;
   цена — память, задержка, обновления, отладка.

</details>

**6.** Sidecar или ambient — что выберете и почему?

<details><summary>Ответ</summary>

Ambient для новых внедрений: без рестартов, L7 только где нужен, дешевле по памяти;
   sidecar — если нужен полный L7 везде или требования зрелости/совместимости.

</details>

**7.** Istio или Linkerd?

<details><summary>Ответ</summary>

Istio — мощнее, ambient, огромная экосистема; Linkerd — проще и легче, но OSS только
   edge, stable — у Buoyant. Решает матрица версий, нужные фичи и кто будет сопровождать.

</details>

**8.** ⭐ Когда вы бы отказались от mesh?

<details><summary>Ответ</summary>

Мало сервисов, нет требования mTLS, нужна только canary или только телеметрия, нет людей.

</details>

**9.** Как проверить, что трафик между сервисами действительно шифруется?

<details><summary>Ответ</summary>

`istioctl ztunnel-config workloads` (HBONE), идентичности в логах ztunnel,
   `connection_security_policy="mutual_tls"` в метриках, tcpdump на порт 15008, STRICT и
   проверка, что plaintext отвергается.

</details>

**10.** Как сделать canary для внутреннего вызова сервис → сервис?

<details><summary>Ответ</summary>

HTTPRoute с `parentRefs` на Service (GAMMA) и весами между Service версий; в ambient нужен
    waypoint; автоматизирует это Argo Rollouts (тема 06).

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Знаю, что вошло в Standard в Gateway API 1.4–1.6 и где ещё Experimental
- [ ] ⭐ Строю мультитенантный Gateway: listeners по доменам, `allowedRoutes`, метки от платформы
- [ ] Объясняю угон домена и конфликт маршрутов и как от них защищаются
- [ ] Знаю, когда нужен ReferenceGrant и где он создаётся
- [ ] Пишу HTTPRoute с совпадениями, таймаутами, зеркалом; GRPCRoute; BackendTLSPolicy
- [ ] ⭐ Настраивал rate limit и API-ключ политиками Envoy Gateway, понимаю их приоритет
- [ ] ⭐ Объясняю, что даёт mesh и сколько стоит; знаю sidecar vs ambient
- [ ] Поднимал Istio ambient в kind, видел mTLS и делил трафик HTTPRoute на Service
- [ ] Могу аргументированно отказаться от mesh
