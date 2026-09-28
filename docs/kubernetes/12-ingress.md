---
title: "12. ⭐ Ingress и Ingress Controller"
description: "Ingress vs Ingress Controller, TLS, аннотации nginx, и переход на Gateway API (Envoy Gateway)"
---

# 12. ⭐ Ingress и Ingress Controller

> Роадмап → 6. Kubernetes → Сеть → Настройка через манифесты → **Ingress**.
> Вопрос собеса: *«В чём разница между Ingress и Ingress Controller?»*
> **После темы ты умеешь:** опубликовать несколько приложений на одном IP,
> настроить TLS и объяснить, где заканчивается Service и начинается Ingress;
> поднять тот же вход на Gateway API (Envoy Gateway) и спланировать миграцию
> с ретайрнутого ingress-nginx.

> ⚠️ **Статус на сентябрь 2026.** Контроллер `kubernetes/ingress-nginx` — EOL с 24.03.2026,
> репозиторий в архиве, финальный релиз `controller-v1.15.1` (чарт 4.15.1), исправлений CVE
> больше не будет. **Сам Ingress API не deprecated**: его по-прежнему реализуют Traefik,
> F5 NGINX Ingress Controller, HAProxy, облачные балансировщики, и он стоит в большинстве
> прод-кластеров и спрашивается на собесах — поэтому разделы 1–6 и 8 учим как есть.
> Новые стенды и проекты — на Gateway API (раздел 7).

---

## 🗺️ Карта темы

```text:no-line-numbers
     Интернет
        │  https://shop.example.com/api
        ▼
  ┌──────────────────────────┐
  │ LoadBalancer (один на    │  ← единственный платный балансировщик
  │ весь кластер)            │
  └────────────┬─────────────┘
               ▼
  ┌──────────────────────────────────────────────┐
  │  INGRESS CONTROLLER   (nginx/traefik — ПОДЫ) │  ← ПРОГРАММА, которая реально
  │  читает объекты Ingress и строит свой конфиг │     принимает и проксирует трафик
  └────────────┬─────────────────────────────────┘
               │ смотрит на правила
               ▼
  ┌──────────────────────────────────────────────┐
  │  INGRESS (объект API)  — ПРАВИЛА маршрутизации│ ← просто YAML, сам ничего не делает
  │  shop.example.com/api  → svc api:8080         │
  │  shop.example.com/     → svc web:80           │
  └────────────┬─────────────────────────────────┘
               ▼
          Service → поды

  То же на Gateway API (раздел 7): объект Ingress распадается на три —
  GatewayClass (какая реализация) → Gateway (порты, TLS, кому можно) → HTTPRoute (правила)
```

---

## 1. ⭐ Ingress vs Ingress Controller (вопрос собеса)

> «**Ingress** — это объект Kubernetes, набор правил: какой хост и путь ведут к какому
> сервису. Сам по себе он ничего не делает — это декларация.
> **Ingress Controller** — работающее в кластере приложение (обычно nginx или Traefik),
> которое следит за объектами Ingress, превращает их в свою конфигурацию
> и фактически принимает и проксирует трафик.
> Без контроллера объекты Ingress бесполезны: создать их можно, но работать они не будут».

| | Ingress | Ingress Controller |
|---|---|---|
| Что это | Объект API (YAML) | Поды (Deployment/DaemonSet) |
| Делает ли что-то сам | Нет | Да: слушает 80/443 и проксирует |
| Кто создаёт | Разработчик/DevOps на каждое приложение | Администратор кластера, один раз |
| Сколько в кластере | Много | Обычно один (может быть несколько классов) |
| Примеры | `kind: Ingress` | ingress-nginx (EOL), Traefik, HAProxy, Kong, F5 NGINX Ingress Controller, облачные LB |

**Самая частая ошибка новичка:** создать Ingress в кластере без контроллера
и удивляться, что «ничего не происходит». `ADDRESS` в `kubectl get ingress` останется пустым.

---

## 2. Зачем нужен Ingress

| Проблема без Ingress | Что даёт Ingress |
|----------------------|------------------|
| Каждое приложение = свой LoadBalancer = свой IP и счёт | Один вход на все приложения |
| Service работает на L4: нет маршрутизации по домену и пути | Маршрутизация по `host` и `path` |
| TLS надо терминировать в каждом приложении | Единая точка терминации TLS + cert-manager |
| Нет L7-возможностей | Редиректы, rewrite, лимиты, basic-auth, CORS, канареечный трафик |

---

## 3. Установка контроллера (legacy: ingress-nginx)

> ⚠️ **ingress-nginx (`kubernetes/ingress-nginx`) снят с поддержки.** В ноябре 2025 SIG Network
> объявил о его retirement, 24.03.2026 проект достиг EOL, репозиторий переведён в архив.
> Финальный релиз — `controller-v1.15.1` (Helm-чарт 4.15.1): ни новых релизов, ни исправлений
> уязвимостей. А уязвимости у него были серьёзные: IngressNightmare (CVE-2025-1974, CVSS 9.8)
> и новые HIGH в феврале 2026
> ([kubernetes.io/blog](https://www.kubernetes.io/blog/2025/11/11/ingress-nginx-retirement/)).
> - **Учебный стенд в kind** — можно дальше учиться на нём, но только с зафиксированным
>   финальным тегом (ниже), не из `main`: объект Ingress одинаков у всех контроллеров,
>   а legacy-кластеры ещё долго придётся читать и мигрировать.
> - **Новый проект** — Gateway API (раздел 7) или поддерживаемый контроллер: Traefik,
>   HAProxy Ingress, Envoy Gateway, Cilium. Есть и NGINX Ingress Controller от F5, но это
>   другой проект с другими аннотациями.
> - **Прод на ingress-nginx** — планировать миграцию (раздел 7.8): аннотации из раздела 6
>   сами не переедут.

```bash
# ingress-nginx для kind — ⚠️ EOL, только для учёбы и чтения legacy-кластеров.
# Тег зафиксирован на финальном релизе: main архивного репозитория не ставим.
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.15.1/deploy/static/provider/kind/deploy.yaml

kubectl -n ingress-nginx get pods
kubectl get ingressclass
# NAME    CONTROLLER             PARAMETERS   AGE
# nginx   k8s.io/ingress-nginx   <none>       1m
```

> 💡 Манифест для kind сажает контроллер на ноду с меткой `ingress-ready=true` и слушает
> 80/443 через `hostPort` — поэтому в kind-конфиге из обзорного индекса блока Kubernetes есть
> `extraPortMappings`. Для Envoy Gateway (раздел 7) они не нужны.

Как контроллер получает трафик снаружи:

| Способ | Где применяется |
|--------|-----------------|
| `type: LoadBalancer` | облако: один LB на весь кластер |
| `hostNetwork: true` + DaemonSet | bare-metal: контроллер слушает 80/443 прямо на нодах |
| NodePort + внешний балансировщик | своя инфраструктура |
| `extraPortMappings` | kind (порты 80/443 проброшены на хост) |

---

## 4. Манифест Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: shop
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
spec:
  ingressClassName: nginx            # ⭐ какой контроллер обслуживает
  tls:
    - hosts: [shop.example.com]
      secretName: shop-tls           # секрет типа kubernetes.io/tls
  rules:
    - host: shop.example.com
      http:
        paths:
          - path: /api
            pathType: Prefix
            backend:
              service:
                name: api
                port:
                  number: 8080
          - path: /
            pathType: Prefix
            backend:
              service:
                name: web
                port:
                  number: 80
    - host: admin.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service: { name: admin, port: { number: 80 } }
```

### `pathType` — три значения

| Значение | Поведение |
|----------|-----------|
| `Prefix` | Совпадение по сегментам пути: `/api` совпадёт с `/api` и `/api/v1`, но не с `/apifoo` |
| `Exact` | Точное совпадение пути |
| `ImplementationSpecific` | На усмотрение контроллера (у nginx — регулярные выражения) |

При нескольких совпадениях приоритет у более длинного пути.

---

## 5. TLS

### Вручную (для лаборатории)
```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout tls.key -out tls.crt -subj "/CN=shop.local"
kubectl create secret tls shop-tls --cert=tls.crt --key=tls.key
```

### cert-manager (как в проде)
```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml
```
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata: { name: letsencrypt }
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: ops@example.com
    privateKeySecretRef: { name: letsencrypt-key }
    solvers:
      - http01:
          ingress: { class: nginx }
```
```yaml
# в Ingress достаточно аннотации:
metadata:
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt
spec:
  tls:
    - hosts: [shop.example.com]
      secretName: shop-tls        # cert-manager создаст и будет обновлять сам
```

> 💡 cert-manager закрывает всю боль с продлением сертификатов: выпускает,
> обновляет за 30 дней до истечения и кладёт в Secret. Это стандарт де-факто.
> С Gateway API он тоже работает — аннотация ставится на Gateway (раздел 7.5).

---

## 6. Полезные аннотации ingress-nginx

```yaml
annotations:
  nginx.ingress.kubernetes.io/rewrite-target: /$2         # переписать путь
  nginx.ingress.kubernetes.io/proxy-body-size: "100m"     # размер загрузки
  nginx.ingress.kubernetes.io/proxy-read-timeout: "300"   # долгие ответы
  nginx.ingress.kubernetes.io/ssl-redirect: "true"        # http → https
  nginx.ingress.kubernetes.io/backend-protocol: "HTTPS"   # бэкенд по HTTPS
  nginx.ingress.kubernetes.io/limit-rps: "20"             # rate limit
  nginx.ingress.kubernetes.io/enable-cors: "true"
  nginx.ingress.kubernetes.io/whitelist-source-range: "10.0.0.0/8"
  nginx.ingress.kubernetes.io/canary: "true"              # канареечный ingress
  nginx.ingress.kubernetes.io/canary-weight: "10"         # 10 % трафика
```

Пример rewrite:
```yaml
metadata:
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /$2
spec:
  rules:
    - host: example.com
      http:
        paths:
          - path: /app(/|$)(.*)
            pathType: ImplementationSpecific
            backend: { service: { name: app, port: { number: 80 } } }
# запрос /app/users → бэкенд получит /users
```

> ⚠️ Аннотации **специфичны для контроллера**: аннотации nginx не работают в Traefik.
> Это одна из причин появления Gateway API. И именно аннотации — основная ручная работа
> при миграции с ingress-nginx (раздел 7.8).

---

## 7. ⭐ Gateway API — что идёт на смену

Ingress ограничен: маршрутизация только HTTP, расширения — через аннотации,
нет разделения ролей между администратором и разработчиком, бэкенд — только
в своём namespace.

**Gateway API** — стандарт SIG Network (`gateway.networking.k8s.io`, CRD ставятся в кластер
отдельно), где вместо одного объекта несколько, и у каждого свой владелец. Спецификация одна,
реализаций много: Envoy Gateway, Istio, Cilium, NGINX Gateway Fabric, Traefik, kgateway,
облачные (GKE, AWS и др.). Ниже — на **Envoy Gateway**: он ставится одной командой в kind.

### 7.1 Роли: кто чем владеет

```text:no-line-numbers
  ЗОНА ПЛАТФОРМЫ                              ЗОНА КОМАНД ПРИЛОЖЕНИЙ
  ┌────────────────────────────┐
  │ GatewayClass  eg           │  «какой реализацией» — админ кластера, один раз
  │ controllerName: envoy…     │
  └─────────────┬──────────────┘
                ▼
  ┌────────────────────────────┐
  │ Gateway  web   (ns infra)  │  «порты, хосты, TLS и КТО может цепляться»
  │ listeners http:80 https:443│   (allowedRoutes) — платформа / сетевики
  └─────────────┬──────────────┘
                │  parentRefs ◄──────────────┬──────────────────────┐
                │                            │                      │
                ▼                    ┌───────┴──────┐       ┌───────┴──────┐
     Envoy-прокси (поды + Service)   │ HTTPRoute    │       │ HTTPRoute    │  «какой путь →
     принимает трафик                │ ns: shop     │       │ ns: blog     │   какой Service»
                                     └───────┬──────┘       └───────┬──────┘
                                             ▼ backendRefs          ▼
                                          Service → поды         Service → поды
```

| Объект | Область | Кто владеет | Что описывает | Аналог в мире Ingress |
|--------|---------|-------------|---------------|-----------------------|
| `GatewayClass` | кластер | админ кластера | какая реализация (`controllerName`) | `IngressClass` |
| `Gateway` | namespace | платформа / сетевики | точка входа: listeners (порт, протокол, hostname, TLS) и **кому можно цепляться** (`allowedRoutes`) | сам контроллер, его LoadBalancer и `spec.tls` |
| `HTTPRoute` (`GRPCRoute`, L4-маршруты) | namespace | команда приложения | хосты, пути, заголовки → какие Service, с весами и фильтрами | `rules` в Ingress + половина аннотаций |
| `ReferenceGrant` | namespace | владелец **целевого** namespace | разрешение ссылаться на его объекты из чужого namespace | — (в Ingress так нельзя) |

> 💡 Главная идея: платформа решает, **где** вход и **кто** может им пользоваться (Gateway),
> а команда сама пишет маршруты к своим сервисам (HTTPRoute) — без тикета на правку
> общего Ingress и без доступа к чужим namespace.

`GRPCRoute` — в стандартном канале; `TLSRoute` и `ReferenceGrant` перешли в стандартный канал в v1.5, `TCPRoute`/`UDPRoute` — в v1.6 (июнь 2026). Экспериментальные ресурсы с v1.6 живут в группе `gateway.networking.x-k8s.io` с префиксом X (проверь на момент чтения).
Что именно поддерживает конкретная реализация (и статус `TLSRoute`) — смотри её документацию.

### 7.2 Установка Envoy Gateway (kind)

```bash
# Envoy Gateway v1.9.1 (28.08.2026), собран с Gateway API v1.6.1; CRD Gateway API ставит сам
helm install eg oci://docker.io/envoyproxy/gateway-helm --version v1.9.1 \
  -n envoy-gateway-system --create-namespace
kubectl wait --timeout=5m -n envoy-gateway-system deployment/envoy-gateway --for=condition=Available

kubectl api-resources --api-group=gateway.networking.k8s.io   # gatewayclasses, gateways, httproutes…
```

> ⚠️ **Версии.** Envoy Gateway v1.9.1 поддерживает Kubernetes **1.33–1.36**. Свежий kind может
> поднять ноды на v1.37 — тогда пересоздай кластер с образом ноды 1.36
> (`kind create cluster --image kindest/node:v1.36.4`, точный тег — в release notes kind).

### 7.3 Платформа: GatewayClass и Gateway

```bash
kubectl create namespace infra                       # здесь живёт Gateway (зона платформы)
kubectl create namespace shop                        # здесь — приложение и его маршруты
kubectl label namespace shop gateway-access=true     # «этому namespace можно цепляться»
```

```yaml
# gateway.yaml — применяет платформа
apiVersion: gateway.networking.k8s.io/v1
kind: GatewayClass
metadata:
  name: eg
spec:
  controllerName: gateway.envoyproxy.io/gatewayclass-controller   # ⭐ кто обслуживает класс
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: web
  namespace: infra
spec:
  gatewayClassName: eg
  listeners:
    - name: http                     # имя listener'а — на него ссылаются через sectionName
      protocol: HTTP
      port: 80
      allowedRoutes:
        namespaces:
          from: Selector             # Same (по умолчанию) / All / Selector
          selector:
            matchLabels:
              gateway-access: "true"
```

| `allowedRoutes.namespaces.from` | Кто может прицепить маршрут |
|---------------------------------|-----------------------------|
| `Same` (**по умолчанию**) | только маршруты из namespace самого Gateway |
| `All` | любой namespace — удобно на стенде, опасно в общем кластере |
| `Selector` | namespace с нужной меткой — типовой прод-вариант |

> ⚠️ Дефолт `Same` — главная грабля первого запуска: Gateway в `infra`, HTTPRoute в `shop`,
> без `allowedRoutes` маршрут получит `Accepted=False` (`NotAllowedByListeners`), а трафик — 404.

На каждый Gateway Envoy Gateway создаёт в `envoy-gateway-system` Deployment с Envoy
и Service — это и есть «поды контроллера» из мира Ingress, только свои у каждого Gateway.

```bash
kubectl get gatewayclass
# NAME   CONTROLLER                                      ACCEPTED   AGE
# eg     gateway.envoyproxy.io/gatewayclass-controller   True       1m

kubectl get gateway -n infra
# NAME   CLASS   ADDRESS   PROGRAMMED   AGE
# web    eg                False        1m
# ↑ на kind без LoadBalancer внешний адрес не выдаётся: ADDRESS пустой, PROGRAMMED может
#   быть False (причина вида AddressNotAssigned). Трафику через port-forward (7.6) это
#   не мешает; с cloud-provider-kind или MetalLB адрес появится.

kubectl get pods,svc -n envoy-gateway-system         # Envoy-прокси и Service этого Gateway
```

### 7.4 Команда приложения: HTTPRoute

Тестовые бэкенды в `shop` — echo-сервер, который отвечает своим именем на любой путь:

```bash
kubectl -n shop create deployment web --image=hashicorp/http-echo -- /http-echo -text=web
kubectl -n shop expose deployment web --port=80 --target-port=5678
kubectl -n shop create deployment api --image=hashicorp/http-echo -- /http-echo -text=api
kubectl -n shop expose deployment api --port=8080 --target-port=5678
```

```yaml
# shop-route.yaml — применяет команда приложения в СВОЁМ namespace
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: shop
  namespace: shop
spec:
  parentRefs:                        # ⭐ к какому Gateway цепляемся (аналог ingressClassName)
    - name: web
      namespace: infra               # Gateway в чужом namespace — пускает его allowedRoutes
      sectionName: http              # конкретный listener; без него — ко всем подходящим
  hostnames: ["shop.example.com"]
  rules:
    - matches:
        - path: { type: PathPrefix, value: /api }
      backendRefs:
        - name: api                  # Service в namespace маршрута
          port: 8080                 # ⭐ порт СЕРВИСА (port), не targetPort
    - matches:
        - path: { type: PathPrefix, value: / }
      backendRefs:
        - name: web
          port: 80
```

| `path.type` | Поведение |
|-------------|-----------|
| `PathPrefix` | По сегментам, как `Prefix` в Ingress: `/api` ловит `/api/v1`, но не `/apifoo` |
| `Exact` | Точное совпадение |
| `RegularExpression` | Регулярка; синтаксис и сама поддержка — на усмотрение реализации |

Кроме пути в `matches` бывают `headers`, `queryParams` и `method`. При нескольких совпадениях
`Exact` важнее `PathPrefix`, длинный префикс важнее короткого, дальше — больше совпадений
по заголовкам и параметрам. Правило без `matches` означает `PathPrefix /`.

#### Канарейка весами — без второго объекта и аннотаций

```bash
kubectl -n shop create deployment web-v2 --image=hashicorp/http-echo -- /http-echo -text=web-v2
kubectl -n shop expose deployment web-v2 --port=80 --target-port=5678
```

```yaml
  rules:
    - matches:
        - path: { type: PathPrefix, value: / }
      backendRefs:
        - name: web                  # стабильная версия
          port: 80
          weight: 90
        - name: web-v2               # канарейка
          port: 80
          weight: 10                 # веса относительные; 0 — выключить, не удаляя
    - matches:                       # тестировщики всегда попадают в v2 — по заголовку
        - path: { type: PathPrefix, value: / }
          headers:
            - name: X-Canary
              value: "true"
      backendRefs:
        - name: web-v2
          port: 80
```

Второе правило специфичнее (путь + заголовок), поэтому с `X-Canary: true` оно побеждает.

#### Фильтры вместо аннотаций

```yaml
    - matches:
        - path: { type: PathPrefix, value: /app }
      filters:
        - type: URLRewrite           # аналог rewrite-target: /app/users → /users
          urlRewrite:
            path: { type: ReplacePrefixMatch, replacePrefixMatch: / }
      timeouts:
        request: 30s                 # аналог proxy-read-timeout (на весь запрос)
      backendRefs:
        - name: app
          port: 80
```

Ещё встроенные фильтры: `RequestRedirect`, `RequestHeaderModifier`, `ResponseHeaderModifier`,
`RequestMirror`. Всё, чего нет в ядре API (rate limit, IP allowlist, размер тела, внешняя
авторизация), реализации делают своими политиками — у Envoy Gateway это `BackendTrafficPolicy`,
`ClientTrafficPolicy`, `SecurityPolicy`.

### 7.5 HTTPS: TLS-listener и cross-namespace

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout tls.key -out tls.crt -subj "/CN=shop.example.com" \
  -addext "subjectAltName=DNS:shop.example.com"
kubectl -n infra create secret tls shop-tls --cert=tls.crt --key=tls.key   # ⭐ в namespace Gateway
```

```yaml
# добавляем в spec.listeners Gateway web
    - name: https
      protocol: HTTPS
      port: 443
      hostname: shop.example.com
      tls:
        mode: Terminate              # TLS снимается на Gateway, в Service идёт HTTP
        certificateRefs:
          - kind: Secret
            name: shop-tls           # Secret в namespace Gateway; из чужого — только через ReferenceGrant
      allowedRoutes:
        namespaces:
          from: Selector
          selector:
            matchLabels:
              gateway-access: "true"
```

Маршрут приложения переезжает на `https`, а на `http` остаётся только редирект:

```yaml
# в HTTPRoute shop меняем parentRefs:
  parentRefs:
    - { name: web, namespace: infra, sectionName: https }
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: shop-redirect
  namespace: shop
spec:
  parentRefs:
    - { name: web, namespace: infra, sectionName: http }
  hostnames: ["shop.example.com"]
  rules:
    - filters:
        - type: RequestRedirect      # аналог ssl-redirect
          requestRedirect:
            scheme: https
            statusCode: 301
```

> 💡 В проде Secret выпускает cert-manager: аннотация `cert-manager.io/cluster-issuer`
> ставится на **Gateway**, а не на маршрут. Поддержку Gateway API в cert-manager
> включают отдельно — как именно, смотри в его документации.

**Ссылка в чужой namespace — только с разрешения владельца цели.** Например, сертификаты
централизованно лежат в `certs`, а Gateway — в `infra`:

```yaml
apiVersion: gateway.networking.k8s.io/v1        # v1 — с Gateway API 1.5; на старых установках v1beta1 (kubectl api-resources | grep -i referencegrant)
kind: ReferenceGrant
metadata:
  name: allow-infra-gateways
  namespace: certs                   # ⭐ создаётся в namespace ЦЕЛИ
spec:
  from:
    - group: gateway.networking.k8s.io
      kind: Gateway
      namespace: infra
  to:
    - group: ""                      # core API
      kind: Secret
```

Так же HTTPRoute из `shop` может сослаться на Service в `payments` — если в `payments`
есть ReferenceGrant `from: HTTPRoute (ns shop)`, `to: Service`. В Ingress это невозможно вовсе.

### 7.6 Проверка: статусы и трафик

```bash
kubectl get gatewayclass,gateway -A
kubectl get httproute -A
# NAMESPACE   NAME   HOSTNAMES              AGE
# shop        shop   ["shop.example.com"]   1m

kubectl describe httproute shop -n shop       # ⭐ Status → Parents → Conditions
# Status:
#   Parents:
#     Conditions:
#       Reason:  Accepted
#       Status:  True
#       Type:    Accepted
#       Reason:  ResolvedRefs
#       Status:  True
#       Type:    ResolvedRefs
#     Controller Name:  gateway.envoyproxy.io/gatewayclass-controller
#     Parent Ref:       Name: web, Namespace: infra, Section Name: http

# компактно — условия по каждому родителю
kubectl get httproute shop -n shop \
  -o jsonpath='{range .status.parents[*].conditions[*]}{.type}={.status} {.reason}{"\n"}{end}'
```

| Объект | Условие | `False` обычно означает |
|--------|---------|-------------------------|
| GatewayClass | `Accepted` | нет контроллера с таким `controllerName` (опечатка, реализация не установлена) |
| Gateway | `Accepted` / `Programmed` | невалидный listener; прокси ещё не готов или нет внешнего адреса |
| listener Gateway | `ResolvedRefs` | Secret сертификата не найден (`InvalidCertificateRef`) или в чужом namespace без ReferenceGrant (`RefNotPermitted`) |
| HTTPRoute | `Accepted` | listener не пускает этот namespace (`NotAllowedByListeners`), хосты не пересекаются (`NoMatchingListenerHostname`), нет такого listener'а/порта (`NoMatchingParent`) |
| HTTPRoute | `ResolvedRefs` | Service не найден или у него нет такого порта, чужой namespace без ReferenceGrant (`RefNotPermitted`), неподдерживаемый `kind` (`InvalidKind`); точное имя причины зависит от реализации — читай `Message` |

> 💡 Нет `status.parents` вообще — маршрут не взял ни один контроллер: чаще всего
> опечатка в имени или namespace Gateway в `parentRefs`.

**Трафик на kind** — через port-forward к Service, который Envoy Gateway создал для Gateway:

```bash
export ENVOY_SERVICE=$(kubectl get svc -n envoy-gateway-system \
  --selector=gateway.envoyproxy.io/owning-gateway-namespace=infra,gateway.envoyproxy.io/owning-gateway-name=web \
  -o jsonpath='{.items[0].metadata.name}')
kubectl -n envoy-gateway-system port-forward service/${ENVOY_SERVICE} 8888:80 &

curl -H "Host: shop.example.com" localhost:8888/api     # → api
curl -H "Host: shop.example.com" localhost:8888/        # → web (после 7.5 — 301 на https)
curl -i -H "Host: other.example.com" localhost:8888/    # → 404: хост не совпал ни с одним маршрутом

# канарейка: 100 запросов и распределение
for i in $(seq 100); do curl -s -H "Host: shop.example.com" localhost:8888/; done | sort | uniq -c
#   91 web
#    9 web-v2        ← веса — вероятность, а не точный счётчик

# HTTPS: заголовка Host мало — нужен SNI, поэтому --resolve
kubectl -n envoy-gateway-system port-forward service/${ENVOY_SERVICE} 8443:443 &
curl -k --resolve shop.example.com:8443:127.0.0.1 https://shop.example.com:8443/
```

| Код от Envoy | Что значит |
|--------------|------------|
| **404** | не совпали hostname/путь, либо маршрут не `Accepted` и Envoy о нём не знает |
| **500** | правило есть, но `backendRef` невалиден (`ResolvedRefs=False`): нет Service, не тот порт, нет ReferenceGrant — так требует спецификация |
| **503** | Service в порядке, но нет готовых endpoints (`no healthy upstream`) |
| **504** | бэкенд не уложился в `timeouts` правила или таймаут политики |

### 7.7 Ingress → HTTPRoute: таблица соответствия

| Ingress / ingress-nginx | Gateway API |
|-------------------------|-------------|
| `IngressClass` | `GatewayClass` |
| Контроллер + его LoadBalancer, порты 80/443 | `Gateway` и его `listeners` |
| `ingressClassName: nginx` | `parentRefs` на Gateway (+ `sectionName`) |
| `rules[].host` | `hostnames` |
| `path` + `pathType: Prefix` / `Exact` | `matches[].path` с `type: PathPrefix` / `Exact` |
| `ImplementationSpecific` + regex | `type: RegularExpression` (поддержка — на усмотрение реализации) |
| `backend.service.name` / `port.number` | `backendRefs[].name` / `port` |
| `spec.tls` + `secretName` в namespace Ingress | `listeners[].tls.certificateRefs` на Gateway (в его namespace или через ReferenceGrant) |
| `ssl-redirect` | фильтр `RequestRedirect` (`scheme: https`) |
| `rewrite-target` | фильтр `URLRewrite` (`ReplacePrefixMatch`), групп захвата нет |
| `canary` + `canary-weight` (второй Ingress) | `weight` у `backendRefs` в одном правиле |
| `canary-by-header` | `matches[].headers` |
| `proxy-read-timeout` | `timeouts.request` / `timeouts.backendRequest` |
| Настройка заголовков (`more_set_headers` в snippet) | фильтры `RequestHeaderModifier` / `ResponseHeaderModifier` |
| `limit-rps`, `whitelist-source-range`, `proxy-body-size`, `auth-url`, `enable-cors` | в ядре API нет → политики реализации (Envoy Gateway: `BackendTrafficPolicy`, `ClientTrafficPolicy`, `SecurityPolicy`) |
| `configuration-snippet`, `server-snippet` | эквивалента нет — разбирать и переписывать руками |
| Бэкенд только в своём namespace | `backendRefs` в чужой namespace + ReferenceGrant |
| Аннотация cert-manager на Ingress | аннотация cert-manager на Gateway |

### 7.8 Миграция с ingress-nginx: ingress2gateway

**ingress2gateway 1.0** — инструмент SIG Network (релиз 20.03.2026): читает объекты Ingress
и печатает эквивалентные ресурсы Gateway API; понимает 30+ аннотаций ingress-nginx.

```bash
# 0. инвентаризация: сколько Ingress и какие аннотации реально используются
kubectl get ingress -A
kubectl get ingress -A -o json \
  | jq -r '.items[].metadata.annotations // {} | keys[]' | sort | uniq -c | sort -rn

# 1. конвертация — схема использования (проверь флаги в README своей версии)
ingress2gateway print --providers=ingress-nginx -A > gateway-api.yaml       # из текущего кластера
ingress2gateway print --providers=ingress-nginx --input-file ingress.yaml   # из файла / helm template
```

**План миграции:**
1. Инвентаризация (выше): список Ingress'ов, аннотаций и глобальных настроек контроллера.
2. Реализацию Gateway API ставим **рядом** с ingress-nginx: у Gateway свой Service/LB и свой IP,
   старый вход продолжает работать.
3. `ingress2gateway print` → ревью в git как обычного кода → дописываем руками то,
   что не переехало (таблица ниже).
4. Применяем, у каждого маршрута проверяем `Accepted`/`ResolvedRefs`, гоняем смоук-тесты
   на новый IP: `curl --resolve shop.example.com:443:<новый IP> https://shop.example.com/`.
5. Заранее понижаем TTL DNS, переключаем запись (или веса на внешнем балансировщике)
   на новый IP, смотрим 4xx/5xx.
6. Старый контроллер держим как путь отката на время окна наблюдения, потом удаляем
   Ingress'ы и сам ingress-nginx.

**Что само не переедет:**

| Что | Почему | Что делать |
|-----|--------|------------|
| `configuration-snippet`, `server-snippet`, `auth-snippet` | Это сырой nginx-конфиг, в Gateway API эквивалента нет (а snippets ещё и давняя проблема безопасности ingress-nginx) | Разобрать, зачем каждый; переписать фильтрами/политиками или унести в приложение |
| Аннотации без аналога в ядре API: rate limit, IP allowlist, размер тела, `auth-url`, ModSecurity/WAF | Ядро Gateway API их не описывает | Политики реализации (у Envoy Gateway — `SecurityPolicy`, `ClientTrafficPolicy`, `BackendTrafficPolicy`) |
| Regex-пути (`use-regex`) и `rewrite-target` с группами `$1`/`$2` | Другая семантика: `RegularExpression` зависит от реализации, у `URLRewrite` нет групп захвата | Переписать и покрыть тестами |
| Глобальный ConfigMap контроллера (таймауты, заголовки, real IP, формат логов) | Инструмент конвертирует объекты Ingress, а не настройки самого контроллера | Сверить руками, перенести в настройки/политики новой реализации |
| Обвязка вокруг Ingress: cert-manager, external-dns, дашборды и алерты по метрикам nginx | Завязаны на Ingress-объекты и метрики ingress-nginx | Перевести на Gateway (оба умеют Gateway API), пересобрать мониторинг |

> 💡 ingress2gateway — генератор черновика, а не кнопка «мигрировать». Вывод читают глазами,
> прогоняют через `kubectl apply --dry-run=server` и сравнивают поведение тестами до и после.
> Особенно негативными: запрос не из офисной сети по-прежнему должен получать 403.

Для собеса достаточно: «Ingress API стабилен и не deprecated, но развивается Gateway API.
Самый популярный контроллер, ingress-nginx, с 24 марта 2026 в EOL: репозиторий в архиве,
CVE не чинят. Поэтому новые проекты начинаю с Gateway API — например, на Envoy Gateway,
а существующие на ingress-nginx мигрирую: инвентаризация аннотаций → ingress2gateway →
ручная доработка → параллельный запуск → переключение DNS».

---

## 8. Диагностика

```bash
kubectl get ingress
# NAME   CLASS   HOSTS              ADDRESS        PORTS     AGE
# shop   nginx   shop.example.com   203.0.113.10   80, 443   5m

kubectl describe ingress shop
kubectl -n ingress-nginx logs -l app.kubernetes.io/component=controller -f
kubectl -n ingress-nginx exec -it <controller-pod> -- cat /etc/nginx/nginx.conf | grep -A10 shop
curl -H "Host: shop.example.com" http://<IP контроллера>/    # проверка без DNS
```

```bash
# Gateway API (Envoy Gateway) — сначала статусы, потом логи
kubectl get gatewayclass,gateway -A                         # ACCEPTED / PROGRAMMED
kubectl describe httproute <name> -n <ns>                   # Accepted / ResolvedRefs + Reason
kubectl -n envoy-gateway-system logs deploy/envoy-gateway   # контроллер: почему не принял объект
kubectl -n envoy-gateway-system logs -c envoy \
  -l gateway.envoyproxy.io/owning-gateway-name=web          # access-логи Envoy-прокси
```

| Симптом | Причина |
|---------|---------|
| `ADDRESS` пустой | Нет контроллера, либо не указан `ingressClassName` |
| **404** от nginx | Не совпал `host` или `path`; запрос попал в default-backend |
| **502 Bad Gateway** | Сервис существует, но бэкенд не отвечает: неверный `targetPort`, под не Ready |
| **503 Service Unavailable** | Нет доступных endpoints у сервиса |
| **504** | Бэкенд отвечает дольше `proxy-read-timeout` |
| TLS-ошибка | Секрет не найден, не того типа или не в том namespace |
| Работает по IP, но не по домену | DNS не указывает на адрес контроллера |

Симптомы и коды Gateway API — в разделе 7.6.

> ⚠️ **Ingress и Service должны быть в одном namespace.** Ingress не может
> ссылаться на сервис из другого namespace (в Gateway API это решено:
> `backendRefs` в чужой namespace + ReferenceGrant, раздел 7.5).

---

## 9. Грабли

| Грабля | Симптом | Лечение |
|--------|---------|---------|
| ingress-nginx из `main` или без версии | Неповторяемый стенд; на проде — EOL-софт без CVE-фиксов | Стенд — тег `controller-v1.15.1`; прод — миграция (7.8) |
| «ingress-nginx умер — значит, Ingress deprecated» | Паника и переписывание всего за неделю | Ingress API жив, меняется контроллер; мигрировать планово, начав с инвентаризации |
| Ingress без контроллера или без `ingressClassName` | `ADDRESS` пустой | Поставить контроллер, указать класс |
| Секрет TLS не в namespace Ingress | TLS-ошибка, сертификат-заглушка контроллера | Секрет — рядом с Ingress |
| Аннотации nginx на другом контроллере | Настройки молча игнорируются | Переписать под реализацию или на Gateway API |
| Gateway в одном namespace, HTTPRoute в другом, `allowedRoutes` по умолчанию | `Accepted=False` (`NotAllowedByListeners`), 404 | `from: Selector` (или `All` на стенде) на listener'е |
| `hostnames` маршрута не пересекаются с `hostname` listener'а | `Accepted=False` (`NoMatchingListenerHostname`) | Согласовать хосты |
| Опечатка в `parentRefs` (имя, namespace, `sectionName`) | `status.parents` пустой или `NoMatchingParent` | Сверить с `kubectl get gateway -A` и именами listener'ов |
| В `backendRefs.port` указан `targetPort` вместо порта Service | `ResolvedRefs=False`, запросы получают 500 | Указывать `port` Service |
| Service или Secret в чужом namespace без ReferenceGrant | `ResolvedRefs=False` (`RefNotPermitted`) | ReferenceGrant в namespace **цели** |
| Проверка HTTPS через `curl -H "Host: …"` | TLS-ошибка или чужой сертификат: Host не задаёт SNI | `curl --resolve host:порт:IP https://host:порт/` |
| Envoy Gateway на неподдерживаемой версии кластера | Непредсказуемые ошибки контроллера | EG v1.9.1 — Kubernetes 1.33–1.36; на kind — образ ноды 1.36 |
| Вывод ingress2gateway применили не глядя | Часть поведения пропала молча: snippets, IP-ограничения, глобальные настройки | Ревью, чек-лист «аннотация → чем заменена», тесты до/после |
| Одна реплика контроллера или Envoy-прокси | Весь вход пропадает при обновлении ноды | ≥ 2 реплики, anti-affinity, PDB (у Envoy Gateway — через ресурс `EnvoyProxy`) |

---

## 💼 Как это в DevOps

- Типовая схема прода: один LoadBalancer → ingress-контроллер → десятки Ingress'ов
  приложений; сертификаты выпускает cert-manager. Исторически контроллером почти всегда
  был ingress-nginx; с 2026 его меняют на поддерживаемый контроллер или Gateway API.
- В кластерах 2026 года часто живут оба мира сразу: старые Ingress'ы и новые HTTPRoute
  на отдельном Gateway. Переезд идёт по одному приложению, с откатом на старый вход.
- Gateway API ложится на платформенную команду: GatewayClass и Gateway лежат в GitOps-репо
  платформы, HTTPRoute — рядом с чартом приложения. `allowedRoutes` и ReferenceGrant —
  это «кто кому что разрешил», их ревьюят так же строго, как RBAC.
- Ingress — то место, где живут «мелкие требования»: размер загрузки, таймауты,
  редиректы, ограничения по IP. Знать десяток аннотаций полезнее, чем кажется —
  хотя бы чтобы при миграции не потерять ни одной.
- Ingress Controller — критичный компонент: его разворачивают минимум в двух репликах
  с anti-affinity и PodDisruptionBudget, иначе при обновлении ноды упадёт весь вход.
  С Envoy-прокси за Gateway ровно то же самое.
- Канареечные аннотации ingress-nginx — самый дешёвый способ пустить 5 % трафика
  на новую версию без service mesh. В Gateway API то же самое делают веса `backendRefs`
  в `HTTPRoute`, без аннотаций.
- Логи ingress-контроллера (или access-логи Envoy) — часто самый быстрый способ понять,
  доходит ли запрос до кластера вообще. В Gateway API до логов смотрят статусы:
  половина проблем видна в `Accepted`/`ResolvedRefs`.
- Миграция с ingress-nginx — типовая задача 2026 года и сильная строчка в резюме:
  «инвентаризация аннотаций, ingress2gateway, параллельный запуск, переключение DNS
  без даунтайма».

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Опубликовать приложение по домену | `kind: Ingress` с `host` и `ingressClassName` |
| Несколько приложений на одном IP | Несколько `rules` или несколько Ingress'ов |
| Маршрутизация по пути | `paths` с `pathType: Prefix` |
| HTTPS | `spec.tls` + секрет `kubernetes.io/tls` |
| Автоматические сертификаты | cert-manager + аннотация `cert-manager.io/cluster-issuer` |
| Редирект на HTTPS | `nginx.ingress.kubernetes.io/ssl-redirect: "true"` |
| Разрешить большие загрузки | `proxy-body-size` |
| Канареечный трафик | `canary: "true"` + `canary-weight` |
| Проверить без DNS | `curl -H "Host: app.example.com" http://<IP>` |
| Посмотреть, что сгенерировал nginx | `exec` в под контроллера → `nginx.conf` |
| Понять, доходит ли запрос | логи пода контроллера |
| Ingress-nginx на учебном kind | только `controller-v1.15.1` (EOL) |
| Поставить Envoy Gateway | `helm install eg oci://docker.io/envoyproxy/gateway-helm --version v1.9.1 -n envoy-gateway-system --create-namespace` |
| Вход на Gateway API | GatewayClass → Gateway (`listeners`) → HTTPRoute (`parentRefs`) |
| Пустить маршруты из других namespace | `allowedRoutes.namespaces.from: Selector` на listener'е |
| Канарейка без аннотаций | `weight` у `backendRefs` |
| Редирект / rewrite в Gateway API | фильтры `RequestRedirect` / `URLRewrite` |
| HTTPS в Gateway API | listener `protocol: HTTPS` + `tls.certificateRefs` |
| Сослаться на Service/Secret в чужом namespace | `ReferenceGrant` в namespace цели |
| Понять, почему маршрут не работает | `kubectl describe httproute` → `Accepted` / `ResolvedRefs` |
| Проверить Gateway на kind | `port-forward` к Service Envoy + `curl -H "Host: …" localhost:8888` |
| Мигрировать с ingress-nginx | `ingress2gateway print --providers=ingress-nginx` + ручная доработка |

---

## 🧠 Что запомнить

1. ⭐ **Ingress — правила (YAML), Ingress Controller — программа, которая их исполняет.**
2. Без контроллера Ingress не работает; `ADDRESS` останется пустым.
3. Ingress работает на L7: маршрутизация по хосту и пути, TLS, редиректы.
4. `ingressClassName` указывает, какой контроллер обслуживает правило.
5. `pathType`: `Prefix` (по сегментам), `Exact`, `ImplementationSpecific`.
6. TLS — через Secret типа `kubernetes.io/tls`; в проде его выпускает cert-manager.
7. Аннотации зависят от контроллера: nginx и Traefik несовместимы между собой.
8. Ingress и Service должны быть в одном namespace.
9. 404 — не совпали правила; 502 — бэкенд не отвечает; 503 — нет endpoints.
10. Один LoadBalancer + Ingress дешевле, чем LoadBalancer на каждое приложение.
11. Ingress Controller — критичный компонент: реплики, anti-affinity, PDB.
12. ⭐ ingress-nginx — EOL с 24.03.2026 (финал `controller-v1.15.1`), CVE не чинят;
    Ingress API при этом жив и не deprecated.
13. Gateway API: GatewayClass (реализация) → Gateway (вход, TLS, кому можно) → HTTPRoute
    (правила команды) — разделение ролей и без «аннотационного ада».
14. `allowedRoutes` по умолчанию `Same`; чужие Service и Secret — только через ReferenceGrant
    в namespace цели.
15. Маршрут читают по условиям: `Accepted` — прицепился к Gateway, `ResolvedRefs` — бэкенды
    найдены. Невалидный бэкенд в Gateway API — это 500.
16. Миграция: инвентаризация аннотаций → ingress2gateway → ручная доработка (snippets,
    политики) → параллельный запуск → переключение DNS.

---

## Задачи

> ⭐ Вопрос собеса: *«В чём разница между Ingress и Ingress Controller?»*
> Практический результат темы: два приложения на одном IP, одно из них по HTTPS —
> сначала на Ingress (legacy ingress-nginx), потом то же на Gateway API (Envoy Gateway).

---

### Блок A. Теория

**A1.** ⭐ В чём разница между Ingress и Ingress Controller?

<details><summary>Ответ</summary>

Ingress — объект API с правилами маршрутизации (хост, путь, сервис).
Ingress Controller — приложение в кластере (nginx, Traefik и др.), которое читает
эти объекты, генерирует свою конфигурацию и реально принимает и проксирует трафик.

</details>

**A2.** Что произойдёт, если создать Ingress в кластере без контроллера?

<details><summary>Ответ</summary>

Ничего: объект создастся, `ADDRESS` останется пустым, трафик обрабатывать
некому.

</details>

**A3.** Назови четыре реализации Ingress Controller.

<details><summary>Ответ</summary>

ingress-nginx (EOL с 24.03.2026), Traefik, HAProxy Ingress, Kong,
F5 NGINX Ingress Controller; также роль контроллера могут выполнять Istio Gateway
и облачные реализации.

</details>

**A4.** Зачем нужен Ingress, если есть Service типа LoadBalancer?

<details><summary>Ответ</summary>

Чтобы не платить за отдельный балансировщик на каждое приложение
и получить L7-возможности: маршрутизацию по хосту и пути, TLS, редиректы, лимиты.

</details>

**A5.** На каком уровне работает Ingress и что из этого следует?

<details><summary>Ответ</summary>

На L7 (HTTP/HTTPS): можно маршрутизировать по домену, пути и заголовкам,
терминировать TLS. Произвольные TCP/UDP-протоколы штатно не поддерживаются.

</details>

**A6.** Как контроллер получает трафик снаружи? Назови три способа.

<details><summary>Ответ</summary>

Через Service типа LoadBalancer; через `hostNetwork`/`hostPort` на нодах
(DaemonSet); через NodePort с внешним балансировщиком.

</details>

**A7.** Что такое `ingressClassName` и что будет, если его не указать?

<details><summary>Ответ</summary>

Указывает, какой контроллер обслуживает этот Ingress. Если не указан,
используется IngressClass, помеченный как default; если такого нет — Ingress
никем не обслуживается.

</details>

**A8.** ⭐ Какие бывают `pathType` и чем они отличаются?

<details><summary>Ответ</summary>

`Prefix` — совпадение по сегментам пути; `Exact` — точное совпадение;
`ImplementationSpecific` — трактовка на усмотрение контроллера (у nginx —
регулярные выражения).

</details>

**A9.** Совпадёт ли `path: /api` с `pathType: Prefix` для запроса `/apifoo`?

<details><summary>Ответ</summary>

Нет: `Prefix` сравнивает по сегментам, а `/apifoo` — другой сегмент.

</details>

**A10.** Как настроить TLS в Ingress? Какого типа должен быть секрет?

<details><summary>Ответ</summary>

Секцией `spec.tls` с указанием хостов и `secretName`; секрет должен быть
типа `kubernetes.io/tls` и лежать в том же namespace, что и Ingress.

</details>

**A11.** Что делает cert-manager и зачем он нужен?

<details><summary>Ответ</summary>

Автоматически выпускает и продлевает сертификаты (в том числе Let's Encrypt)
и кладёт их в Secret; следит за сроком и обновляет заранее.

</details>

**A12.** Что такое ClusterIssuer и чем отличается от Issuer?

<details><summary>Ответ</summary>

`Issuer` действует в пределах namespace, `ClusterIssuer` — на весь кластер.

</details>

**A13.** Почему аннотации Ingress считаются проблемой?

<details><summary>Ответ</summary>

Они не типизированы и зависят от конкретного контроллера: конфигурация
не переносится между реализациями и не валидируется схемой API.

</details>

**A14.** Может ли Ingress ссылаться на сервис в другом namespace?

<details><summary>Ответ</summary>

Нет: бэкенд-сервис должен быть в том же namespace. Это одно из ограничений,
снятых в Gateway API.

</details>

**A15.** Как проверить работу Ingress, если DNS ещё не настроен?

<details><summary>Ответ</summary>

Обратиться по IP контроллера, подставив заголовок:
`curl -H "Host: app.example.com" http://<IP>/`.

</details>

**A16.** Что означает 404 от ingress-nginx?

<details><summary>Ответ</summary>

Запрос не подошёл ни под одно правило (не тот хост или путь)
и попал в default-backend.

</details>

**A17.** Что означает 502? А 503? А 504?

<details><summary>Ответ</summary>

502 — бэкенд не отвечает или отвечает некорректно (неверный `targetPort`,
приложение упало); 503 — нет доступных endpoints; 504 — бэкенд не уложился
в таймаут проксирования.

</details>

**A18.** Почему `ADDRESS` у Ingress может быть пустым?

<details><summary>Ответ</summary>

Нет контроллера; не указан класс; контроллер не смог получить внешний адрес
(нет LoadBalancer в bare-metal).

</details>

**A19.** Как сделать канареечный выпуск средствами ingress-nginx?

<details><summary>Ответ</summary>

Вторым Ingress с теми же хостом и путём и аннотациями `canary: "true"`
и `canary-weight: "N"` (либо по заголовку/куке).

</details>

**A20.** Зачем Ingress Controller нужны несколько реплик и PDB?

<details><summary>Ответ</summary>

Через него проходит весь внешний трафик: одна реплика означает полную
недоступность при обновлении ноды или пода. PDB не даёт вытеснить сразу все реплики.

</details>

**A21.** Что такое Gateway API и какие объекты в него входят?

<details><summary>Ответ</summary>

Новый стандарт маршрутизации: `GatewayClass` (реализация),
`Gateway` (точка входа), `HTTPRoute`/`GRPCRoute`/`TCPRoute` (правила),
`ReferenceGrant` (разрешение ссылок между namespace).

</details>

**A22.** Какие проблемы Ingress решает Gateway API?

<details><summary>Ответ</summary>

Аннотационный «ад» и непереносимость конфигураций, отсутствие разделения
ролей между администратором и командой приложения, ограничение только HTTP,
невозможность ссылаться на сервисы из других namespace.

</details>

**A23.** Как посмотреть итоговую конфигурацию nginx, сгенерированную контроллером?

<details><summary>Ответ</summary>

`kubectl -n ingress-nginx exec -it <pod> -- cat /etc/nginx/nginx.conf`.

</details>

**A24.** Как ограничить доступ к приложению по IP через Ingress?

<details><summary>Ответ</summary>

Аннотацией `nginx.ingress.kubernetes.io/whitelist-source-range`
с перечислением разрешённых CIDR.

</details>

**A25.** Где терминируется TLS в схеме «LB → контроллер → сервис → под»?

<details><summary>Ответ</summary>

На Ingress Controller: дальше внутри кластера трафик обычно идёт по HTTP
(если не настроен backend-protocol HTTPS или mTLS через mesh).

</details>

**A26.** ⭐ Контроллер ingress-nginx ретайрнут. Означает ли это, что Ingress API deprecated?
Что делать с кластером, где он стоит?

<details><summary>Ответ</summary>

Нет. Ретайрнут только контроллер `kubernetes/ingress-nginx`: EOL 24.03.2026,
репозиторий в архиве, финальный релиз `controller-v1.15.1`, CVE больше не чинят.
Ingress API (`networking.k8s.io/v1`) стабилен, его реализуют Traefik, F5 NGINX Ingress
Controller, HAProxy, облачные LB. С кластером: инвентаризация Ingress'ов и аннотаций →
выбор цели (Gateway API или поддерживаемый Ingress-контроллер) → ingress2gateway как
черновик → ручная доработка → параллельный запуск → переключение DNS. До конца миграции —
сузить поверхность атаки: admission webhook доступен только API server'у, NetworkPolicy.

</details>

**A27.** Кто владеет GatewayClass, Gateway и HTTPRoute? Что описывает каждый объект?

<details><summary>Ответ</summary>

`GatewayClass` — админ кластера: какая реализация (`controllerName`).
`Gateway` — платформа/сетевики: listeners (порт, протокол, hostname, TLS) и `allowedRoutes`.
`HTTPRoute` — команда приложения, в своём namespace: хосты, `matches`, `backendRefs`, фильтры.

</details>

**A28.** Что задаёт `allowedRoutes` у listener'а и какое у него значение по умолчанию?

<details><summary>Ответ</summary>

Какие маршруты могут прицепиться к listener'у: `namespaces.from` = `Same`
(по умолчанию), `All` или `Selector` по меткам namespace; плюс `kinds` — типы маршрутов.
Из-за дефолта `Same` маршрут из другого namespace без настройки не принимается.

</details>

**A29.** Зачем нужен ReferenceGrant и в каком namespace его создают?

<details><summary>Ответ</summary>

Разрешает ссылку на объект в чужом namespace: HTTPRoute → Service, Gateway → Secret.
Создаётся в namespace **цели** её владельцем — без его согласия подключиться к чужому
сервису или сертификату нельзя.

</details>

**A30.** Что означают условия `Accepted` и `ResolvedRefs` в статусе HTTPRoute?

<details><summary>Ответ</summary>

`Accepted` — родитель (Gateway/listener) принял маршрут, маршрут прицепился
(иначе `NotAllowedByListeners`, `NoMatchingListenerHostname`, `NoMatchingParent`).
`ResolvedRefs` — все ссылки разрешены: Service существуют, порты есть, cross-namespace
разрешён (иначе `BackendNotFound`, `RefNotPermitted`, `InvalidKind`). Смотрят в
`status.parents[].conditions` через `kubectl describe httproute`.

</details>

---

### Блок B. «Что произойдёт»

**B1.**
```yaml
kind: Ingress
spec:
  rules:
    - host: app.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: web, port: { number: 80 } } }
# ingressClassName не указан, контроллер установлен и помечен default
```
Вопрос: будет ли работать?

<details><summary>Ответ</summary>

Да: при наличии IngressClass по умолчанию контроллер подхватит правило.

</details>

**B2.**
```bash
kubectl get ingress
# NAME  CLASS  HOSTS             ADDRESS   PORTS  AGE
# app   nginx  app.example.com             80     10m
```
Вопрос: почему пустой ADDRESS и что проверить?

<details><summary>Ответ</summary>

Контроллер не установлен, не обслуживает этот класс, либо не получил внешний
адрес. Проверить поды в `ingress-nginx`, `kubectl get ingressclass` и `describe ingress`.

</details>

**B3.**
```bash
curl -H "Host: app.example.com" http://<ingress-ip>/
# 502 Bad Gateway
kubectl get pods -l app=web
# web-xxx  1/1  Running
```
Вопрос: где искать проблему?

<details><summary>Ответ</summary>

Сервис и его endpoints: неверный `targetPort`, приложение слушает не тот порт
или не `0.0.0.0`, под не Ready. Плюс логи контроллера.

</details>

**B4.**
```bash
curl http://<ingress-ip>/
# 404 Not Found (nginx)
```
Вопрос: почему, если Ingress создан?

<details><summary>Ответ</summary>

Запрос без нужного заголовка `Host` не совпал ни с одним правилом
и ушёл в default-backend.

</details>

**B5.**
```yaml
spec:
  tls:
    - hosts: [app.example.com]
      secretName: app-tls
# секрет создан в namespace ingress-nginx
```
Вопрос: заработает ли HTTPS?

<details><summary>Ответ</summary>

Нет: секрет должен быть в namespace самого Ingress.

</details>

**B6.**
```yaml
paths:
  - path: /api
    pathType: Exact
```
Вопрос: сработает ли запрос `/api/users`?

<details><summary>Ответ</summary>

Нет: `Exact` требует точного совпадения пути.

</details>

**B7.**
```text:no-line-numbers
# два Ingress с одинаковым host и path, разные сервисы
```
Вопрос: что произойдёт?

<details><summary>Ответ</summary>

Поведение зависит от контроллера: обычно применяется более раннее
по времени создания правило, второе игнорируется (в логах контроллера появится
предупреждение о конфликте).

</details>

**B8.**
```bash
curl https://app.example.com/
# SSL certificate problem: self signed certificate
```
Вопрос: что это значит и как проверить в лаборатории?

<details><summary>Ответ</summary>

Сертификат самоподписанный и не доверен системой. В лаборатории
проверять с `curl -k`, в проде использовать cert-manager с Let's Encrypt.

</details>

**B9.**
```yaml
# Gateway web в namespace infra, listener http БЕЗ allowedRoutes
# HTTPRoute в namespace shop:
spec:
  parentRefs: [{ name: web, namespace: infra }]
  hostnames: ["shop.local"]
  rules:
    - backendRefs: [{ name: web, port: 80 }]
```
Вопрос: примет ли Gateway маршрут? Что покажет `kubectl describe httproute`?

<details><summary>Ответ</summary>

Нет: по умолчанию `allowedRoutes.namespaces.from: Same`, и маршрут из `shop`
к listener'у Gateway в `infra` не прицепится. В `describe httproute`: `Accepted=False`,
`Reason: NotAllowedByListeners`; запросы — 404.

</details>

**B10.**
```yaml
backendRefs:
  - name: web-v1
    port: 80
    weight: 3
  - name: web-v2
    port: 80
    weight: 1
```
Вопрос: как распределится трафик? Что будет, если у `web-v2` поставить `weight: 0`?

<details><summary>Ответ</summary>

Веса относительные: 3:1 — около 75 % в `web-v1` и 25 % в `web-v2`.
`weight: 0` — трафик в `web-v2` не идёт, но бэкенд остаётся в маршруте: канарейку
можно выключить и включить обратно одной цифрой.

</details>

**B11.**
```bash
# listener https: hostname: shop.local, маршрут Accepted, по HTTP с тем же Host всё отвечает
kubectl -n envoy-gateway-system port-forward service/$ENVOY_SERVICE 8443:443 &
curl -k -H "Host: shop.local" https://localhost:8443/
# curl: (35) ... TLS handshake: соединение сброшено
```
Вопрос: почему HTTPS не отвечает и как проверить правильно?

<details><summary>Ответ</summary>

`-H "Host"` меняет только HTTP-заголовок, а TLS-рукопожатие идёт с SNI `localhost`;
listener с `hostname: shop.local` такое соединение не принимает. Правильно:
`curl -k --resolve shop.local:8443:127.0.0.1 https://shop.local:8443/` — SNI и Host совпадут.

</details>

---

### Блок C. Практика

#### C1. 🔑 Установить контроллер
1. Поставь ingress-nginx в свой kind-кластер — **только** финальный тег `controller-v1.15.1`
   из конспекта (§3): проект в EOL с 24.03.2026, это учебный стенд для legacy-Ingress.
2. Проверь `kubectl -n ingress-nginx get pods` и `kubectl get ingressclass`.
3. Найди, каким способом контроллер получает трафик (LoadBalancer / hostPort / NodePort).

#### C2. 🔑 Первое приложение через Ingress
Опубликуй Deployment+Service из темы 05 по хосту `web.local`.
1. Примени Ingress.
2. Проверь: `curl -H "Host: web.local" http://localhost/`.
3. Добавь запись в `/etc/hosts` и открой в браузере.

#### C3. 🔑 Два приложения на одном IP
Подними второе приложение и опубликуй его:
1. По другому хосту (`api.local`).
2. По пути `/api` того же хоста.
Проверь оба варианта. Запиши, какой подход в каких случаях удобнее.

#### C4. pathType
Сделай три правила: `Exact /health`, `Prefix /api`, `Prefix /`.
Проверь запросы: `/health`, `/health/`, `/api`, `/api/v1/users`, `/`, `/anything`.
Заполни таблицу «запрос → какой бэкенд».

<details><summary>Ответ</summary>

`/health` → Exact-правило; `/health/` → уже не Exact, уйдёт в `Prefix /`;
`/api` и `/api/v1/users` → Prefix `/api`; `/` и `/anything` → Prefix `/`.

</details>

#### C5. rewrite-target
Настрой так, чтобы запрос `/app/users` приходил в бэкенд как `/users`.
Проверь по логам приложения, какой путь оно реально получило.

#### C6. 🔑 TLS вручную
1. Сгенерируй самоподписанный сертификат для `web.local`.
2. Создай секрет `kubernetes.io/tls`.
3. Добавь секцию `tls` в Ingress.
4. Проверь `curl -k https://web.local/` и посмотри детали сертификата (`curl -kv`).

#### C7. Редирект на HTTPS
Включи `ssl-redirect` и убедись, что HTTP отдаёт 308 на HTTPS.
Потом отключи и сравни.

#### C8. Ограничения и таймауты
1. Поставь `proxy-body-size: 1m` и попробуй загрузить файл 5 МБ — получишь 413.
2. Поставь `proxy-read-timeout: 5` и сделай медленный бэкенд — получишь 504.
Запиши коды ошибок: это готовые ответы на вопросы «что означает 413/504».

<details><summary>Ответ</summary>

413 — превышен `proxy-body-size`; 504 — превышен `proxy-read-timeout`.

</details>

#### C9. Ограничение по IP
Добавь `whitelist-source-range` с диапазоном, не включающим твой адрес,
и убедись, что получаешь 403. Верни обратно.

#### C10. Канареечный Ingress
Сделай два Ingress с одним хостом: основной и канареечный
(`canary: "true"`, `canary-weight: "20"`) на другую версию приложения.
Сделай 100 запросов и посчитай распределение.

#### C11. Что сгенерировал nginx
```bash
kubectl -n ingress-nginx exec -it <pod> -- cat /etc/nginx/nginx.conf | grep -B3 -A15 "web.local"
```
Найди свой `server`-блок, `upstream` и список бэкендов. Сопоставь с Endpoints сервиса.

<details><summary>Ответ</summary>

В `upstream`-блоке будут адреса подов — те же, что в EndpointSlice сервиса:
ingress-nginx по умолчанию ходит напрямую в поды, минуя ClusterIP.

</details>

#### C12. Логи контроллера
Включи поток логов контроллера и сделай несколько запросов: успешный, 404, 502.
Разбери формат строки лога: какие поля есть и что означают.

#### C13. cert-manager (со звёздочкой)
Установи cert-manager и выпусти самоподписанный сертификат через `Issuer`
типа `selfSigned`. Пройди путь Certificate → Secret → Ingress.
Опиши, что изменится при использовании Let's Encrypt.

#### C14. Отказ контроллера
1. Масштабируй контроллер в 0 реплик.
2. Проверь доступность приложения снаружи и изнутри кластера (через ClusterIP).
3. Сформулируй, почему контроллеру нужны реплики и PDB.

<details><summary>Ответ</summary>

Снаружи приложение недоступно, внутри кластера по ClusterIP работает —
значит, точка отказа именно контроллер.

</details>

#### C15. 🔑 Gateway API: тот же вход на Envoy Gateway
1. Поставь Envoy Gateway v1.9.1 (конспект §7.2) и дождись `Available`.
2. Платформа: namespace `infra`, `GatewayClass eg`, `Gateway web` с listener'ом `http`
   и `allowedRoutes` по метке namespace (`from: Selector`).
3. Команда: в namespace приложения — HTTPRoute для двух приложений из C3
   (по хосту и по пути).
4. Проверь `kubectl get gatewayclass,gateway -A` и `kubectl describe httproute`:
   `Accepted=True`, `ResolvedRefs=True`.
5. Найди Service Envoy по меткам `gateway.envoyproxy.io/owning-gateway-*`, сделай
   `port-forward` на 8888 и повтори curl'ы из C3.
6. Положи рядом Ingress из C3 и свой HTTPRoute и сравни: где что описано и кто
   каким файлом владеет.

<details><summary>Ответ</summary>

`gatewayclass eg` — `ACCEPTED True`, у маршрута оба условия `True`, через
port-forward запросы из C3 отвечают так же, как через Ingress. Разница в чтении:
в Ingress всё в одном объекте (плюс класс и аннотации), в Gateway API вход (порты, TLS,
кто может цепляться) отделён от правил приложения и живёт в другом namespace/репозитории.

</details>

#### C16. Канарейка весами и по заголовку
1. Подними `web-v2`, который отвечает своей версией.
2. В HTTPRoute поставь веса 90/10, сделай 100 запросов и посчитай распределение
   (`sort | uniq -c`).
3. Добавь правило: заголовок `X-Canary: true` → всегда `web-v2`. Проверь.
4. Переведи веса 50/50 → 0/100 и сравни с канареечным Ingress из C10: сколько объектов
   и аннотаций понадобилось там.

<details><summary>Ответ</summary>

Из 100 запросов около 90/10 (веса — вероятность, 85/15 тоже норма).
Правило с заголовком специфичнее и побеждает: `X-Canary: true` всегда даёт v2.
В Ingress для того же понадобился второй объект с `canary`, `canary-weight`
и `canary-by-header`; здесь — одно правило с весами и одно с `headers`.

</details>

#### C17. HTTPS-listener, редирект и ReferenceGrant
1. Создай self-signed сертификат для `shop.local`, Secret — в namespace Gateway.
2. Добавь listener `https` (`mode: Terminate`), маршрут приложения повесь на `sectionName: https`.
3. На listener `http` — отдельный HTTPRoute с фильтром `RequestRedirect` на https.
4. Проверь `curl -i -H "Host: shop.local" localhost:8888/` (ожидаешь 301)
   и `curl -k --resolve shop.local:8443:127.0.0.1 https://shop.local:8443/`.
5. Перенеси Secret в namespace `certs` и посмотри на статус listener'а в `describe gateway`.
   Почини через ReferenceGrant.

<details><summary>Ответ</summary>

По HTTP — `301` с `Location: https://shop.local/`. После переноса Secret в `certs`
у listener'а `https` — `ResolvedRefs=False` (`RefNotPermitted`), HTTPS перестаёт работать.
Чинит ReferenceGrant в namespace `certs`: `from` — Gateway из `infra`, `to` — Secret.

</details>

#### C18. Миграция через ingress2gateway
1. Собери свои Ingress'ы из C3–C10 в файл: `kubectl get ingress -A -o yaml > ingress.yaml`.
2. Прогони `ingress2gateway print --providers=ingress-nginx` по кластеру или по файлу
   (флаги — проверь в README своей версии).
3. Составь таблицу «аннотация → во что превратилась / не переехала».
4. Примени результат на Envoy Gateway, дострой руками недостающее и проверь теми же
   curl'ами, что и до миграции (включая негативные: 403, 413).

<details><summary>Ответ</summary>

Хосты, пути, TLS и часть аннотаций (из списка поддержанных в README) переезжают
автоматически. Ожидаемо остаются: `whitelist-source-range`, `proxy-body-size`, `limit-rps`,
snippets и глобальный ConfigMap контроллера — их переносят политиками Envoy Gateway
(`SecurityPolicy`, `ClientTrafficPolicy`, `BackendTrafficPolicy`) или сознательно выбрасывают.
Негативные тесты (403 не из разрешённой сети, 413 на большой файл) ловят именно эти потери.

</details>

---

### Блок D. Инциденты

**D1.** Ingress создан неделю назад, `ADDRESS` пустой, сайт не открывается. Разбор.

<details><summary>Ответ</summary>

Нет контроллера или неверный `ingressClassName`; контроллер не получил
внешний адрес (bare-metal без MetalLB); DNS не указывает на нужный адрес.

</details>

**D2.** Приложение отдаёт 502 через Ingress, но работает через `port-forward`.
Что проверить?

<details><summary>Ответ</summary>

Service: `targetPort`, метки, readiness, Endpoints. `port-forward` идёт
напрямую в под и Service не проверяет.

</details>

**D3.** Сайт работает по HTTP, по HTTPS — ошибка сертификата. Три причины.

<details><summary>Ответ</summary>

Секрет не создан или не в том namespace; сертификат для другого домена
(SAN не совпадает); секрет не типа `kubernetes.io/tls`; истёк срок действия.

</details>

**D4.** После обновления приложения пользователи получают 413 при загрузке файлов.
Что изменилось и где чинить?

<details><summary>Ответ</summary>

Появились загрузки больших файлов, а `proxy-body-size` по умолчанию около 1 МБ.
Увеличить аннотацией на нужном Ingress.

</details>

**D5.** Один из двух Ingress'ов перестал работать после добавления второго
с тем же хостом. Что произошло?

<details><summary>Ответ</summary>

Конфликт правил: два Ingress с одинаковыми хостом и путём. Контроллер
выбирает одно правило и пишет предупреждение в лог.

</details>

**D6.** Сертификат Let's Encrypt не продлился, сайт отдаёт просроченный.
Куда смотреть (объекты cert-manager)?

<details><summary>Ответ</summary>

Объекты cert-manager: `Certificate`, `CertificateRequest`, `Order`,
`Challenge`; чаще всего не проходит HTTP-01 (закрыт путь `/.well-known/acme-challenge`
или домен не резолвится на кластер).

</details>

**D7.** Во время обновления нод весь внешний трафик пропал на две минуты.
Что не было настроено?

<details><summary>Ответ</summary>

Ingress Controller работал в одной реплике (или без PDB и anti-affinity):
при вытеснении пода вход в кластер исчез.

</details>

**D8.** В логах приложения все клиенты приходят с одного IP. Как вернуть реальный IP?

<details><summary>Ответ</summary>

Это адрес контроллера или ноды: приложение должно доверять заголовку
`X-Forwarded-For`; при необходимости сохранить IP на уровне L4 —
`externalTrafficPolicy: Local` на сервисе контроллера.

</details>

**D9.** Запросы к `/api` приходят в бэкенд с префиксом `/api`, хотя приложение
ожидает `/`. Что настроить?

<details><summary>Ответ</summary>

`rewrite-target` с группой захвата в пути (или поддержку префикса
на стороне приложения).

</details>

**D10.** Команда мигрировала с ingress-nginx на Traefik, и половина настроек
перестала работать. Почему?

<details><summary>Ответ</summary>

Аннотации специфичны для реализации: настройки ingress-nginx
не понимаются Traefik. Нужно переписывать конфигурацию (или переходить на Gateway API:
черновик даёт ingress2gateway, но аннотации без аналога переносятся руками).

</details>

**D11.** Команда перенесла приложение в новый namespace `payments`, HTTPRoute скопировала
без изменений — сайт отдаёт 404. В `kubectl describe httproute`:
`Accepted: False`, `Reason: NotAllowedByListeners`. Разбор: что это значит и кто должен чинить?

<details><summary>Ответ</summary>

Listener Gateway пускает маршруты только из разрешённых namespace (`allowedRoutes`:
`Same` по умолчанию или `Selector` по метке), а `payments` под правило не подходит.
Маршрут не прицепился, Envoy о нём не знает — отсюда 404. Чинит владелец Gateway
(платформа): метка на namespace (`gateway-access=true`) или правка селектора. Команда
обойти это со своей стороны не может — в этом и смысл разделения ролей. Профилактика:
метка ставится при создании namespace (шаблон онбординга, GitOps).

</details>

**D12.** После рефакторинга Service `api` слушает порт 80 вместо 8080 (targetPort прежний).
Через Gateway `/api` отвечает **500**, остальные пути работают. У маршрута `Accepted=True`,
`ResolvedRefs=False`. Почему 500, а не 502/503, как было на ingress-nginx, и где чинить?

<details><summary>Ответ</summary>

`backendRefs.port: 8080` ссылается на порт Service, которого больше нет, —
ссылка не разрешилась (`ResolvedRefs=False`, в `Message` — порт не найден). Спецификация
Gateway API требует отвечать **500** на запросы к невалидному бэкенду: это не «бэкенд
не ответил», а «маршрут сломан конфигурацией». Правило `/` работает, потому что его
ссылки валидны. Чинить: `port: 80` в HTTPRoute (или вернуть порт в Service); после
деплоя проверять статус маршрута, а не только `rollout status`.

</details>

**D13.** Миграция через ingress2gateway прошла, сайт открывается. Через неделю выяснилось:
админка доступна из интернета (раньше пускала только офисную сеть), а из ответов пропали
заголовки безопасности. Что потерялось и как такое ловить до переключения DNS?

<details><summary>Ответ</summary>

ingress2gateway перенёс маршрутизацию, но не аннотации без аналога в ядре
Gateway API: `whitelist-source-range` и `configuration-snippet` с `more_set_headers`.
Ограничение по IP в Envoy Gateway — `SecurityPolicy`, заголовки — фильтр
`ResponseHeaderModifier`. Ловить: инвентаризация аннотаций до миграции, чек-лист
«аннотация → чем заменена», негативные тесты (запрос не из офиса → 403, проверка
заголовков ответа) на новом IP до переключения DNS.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ В чём разница между Ingress и Ingress Controller? *(вопрос роадмапа)*

<details><summary>Ответ</summary>

Ingress — правила в виде объекта API; Ingress Controller — приложение,
которое их читает и реально проксирует трафик.

</details>

**2.** Зачем нужен Ingress, если есть Service?

<details><summary>Ответ</summary>

Service работает на L4 и не умеет маршрутизацию по доменам и путям;
Ingress даёт единый вход, TLS и L7-возможности.

</details>

**3.** Как настроить HTTPS в кубере?

<details><summary>Ответ</summary>

Секрет типа `kubernetes.io/tls` плюс секция `spec.tls`; в проде сертификаты
выпускает и продлевает cert-manager.

</details>

**4.** Что такое cert-manager?

<details><summary>Ответ</summary>

Контроллер, автоматизирующий выпуск и обновление сертификатов, в том числе
через ACME/Let's Encrypt.

</details>

**5.** Какие pathType бывают?

<details><summary>Ответ</summary>

`Prefix`, `Exact`, `ImplementationSpecific`.

</details>

**6.** Что означают 404, 502, 503 от ingress-nginx?

<details><summary>Ответ</summary>

404 — не совпало правило; 502 — бэкенд не отвечает; 503 — нет endpoints.

</details>

**7.** Как опубликовать несколько приложений на одном IP?

<details><summary>Ответ</summary>

Один Ingress Controller и несколько правил по хостам и путям.

</details>

**8.** Как сделать канареечный релиз через Ingress?

<details><summary>Ответ</summary>

Второй Ingress с аннотациями `canary` и `canary-weight`
(или маршрутизация по заголовку/куке).

</details>

**9.** Может ли Ingress ссылаться на сервис из другого namespace?

<details><summary>Ответ</summary>

Нет, только в пределах своего namespace.

</details>

**10.** Что такое Gateway API и зачем он появился?

<details><summary>Ответ</summary>

Развитие Ingress: типизированные ресурсы вместо аннотаций, разделение ролей,
поддержка не только HTTP и кросс-namespace маршрутов. После EOL ingress-nginx —
выбор по умолчанию для новых проектов.

</details>

**11.** ingress-nginx ретайрнут — что делать?

<details><summary>Ответ</summary>

Умер контроллер, а не Ingress API: EOL 24.03.2026, CVE не чинят. План:
инвентаризация аннотаций → цель (Gateway API, например Envoy Gateway, или
поддерживаемый Ingress-контроллер) → ingress2gateway как черновик → ручная доработка →
параллельный запуск → переключение DNS → удаление старого контроллера.

</details>

**12.** Чем Gateway API отличается от Ingress?

<details><summary>Ответ</summary>

Ingress — один объект: HTTP, хост/путь → Service, расширения аннотациями конкретного
контроллера, бэкенд только в своём namespace. Gateway API — роли (GatewayClass,
Gateway, HTTPRoute), веса, фильтры и заголовки типизированными полями, не только HTTP,
cross-namespace через `allowedRoutes` и ReferenceGrant, статусы `Accepted`/`ResolvedRefs`.

</details>

---

### 🎯 Чек-лист

- [ ] ⭐ Объясняю разницу Ingress и Ingress Controller одной фразой
- [ ] Установил контроллер и понимаю, как он получает внешний трафик
- [ ] Опубликовал два приложения на одном IP (по хосту и по пути)
- [ ] Разобрался с `pathType` на практике
- [ ] Настроил TLS вручную и знаю, что делает cert-manager
- [ ] Знаю значения 404 / 502 / 503 / 504 / 413 от контроллера
- [ ] Смотрел сгенерированный `nginx.conf` и логи контроллера
- [ ] Пробовал канареечные аннотации
- [ ] Понимаю, почему контроллеру нужны реплики и PDB
- [ ] Знаю, что такое Gateway API и зачем он появился
- [ ] Знаю, что ingress-nginx в EOL, и ставлю его только с тегом `controller-v1.15.1` для учёбы
- [ ] Поднял Envoy Gateway: GatewayClass → Gateway → HTTPRoute, читаю `Accepted`/`ResolvedRefs`
- [ ] Сделал канарейку весами и HTTPS-listener с редиректом
- [ ] Прогнал ingress2gateway и знаю, что не переезжает само
