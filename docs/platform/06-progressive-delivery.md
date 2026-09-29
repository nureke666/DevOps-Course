---
title: "06. Progressive delivery: Argo Rollouts, анализ метрик, feature flags"
description: "Блок → Platform Engineering → безопасная выкатка. Стратегии (rolling, blue-green, canary)"
---

# 06. Progressive delivery: Argo Rollouts, анализ метрик, feature flags

> Блок → Platform Engineering → **безопасная выкатка**. Стратегии (rolling, blue-green, canary)
> на уровне идеи — [../CICD/03_pipeline_design.md](/cicd/03-pipeline-design) §7–8,
> обзор Rollouts/Flagger — [../Kubernetes/21_advanced_paths.md](/kubernetes/21-advanced-paths) §6,
> SLI и пороги — [../SRE/02_sli_slo_error_budget.md](/sre/02-sli-slo-error-budget).
> Вопросы собеса: *«Как вы выкатываете без простоя и страха?»*, *«Что будет, если canary плохая?»*,
> *«Чем деплой отличается от релиза?»*
> **После темы ты умеешь:** заменить Deployment на Rollout, вести canary через HTTPRoute
> плагином Gateway API на Envoy Gateway, написать AnalysisTemplate на Prometheus по метрикам
> linkd (доля успешных, p95), увидеть автооткат при росте 5xx, настроить blue-green
> с проверкой preview, подружить Rollouts с ArgoCD и отделить релиз фичи от деплоя флагом.
> Версии — «проверь, сентябрь 2026».

---

## 🗺️ Карта темы

```text
 git: linkd:2.1 ──► ArgoCD ──► Rollout (вместо Deployment) ──► новая ревизия шаблона пода
                                  │ Argo Rollouts: ReplicaSet stable + canary, шаги
                                  │ setWeight 20 → pause → 50 → analysis → 100
          плагин gatewayAPI ◄─────┴─────► AnalysisRun ──► Prometheus: доля не-5xx, p95 canary
                 ▼                                         │ провал
 HTTPRoute: stable 80 / canary 20 ◄── Envoy Gateway        ▼
                                           abort: веса 100/0, canary в 0, Rollout Degraded
 рядом: флаг OpenFeature + flagd включает функцию 5% пользователей независимо от деплоя
```text
---

## 1. Почему canary нужен анализ

Canary без автоматической проверки — **просто медленный деплой**: 10% пользователей получают
баг, а человек в это время смотрит на графики, отвлекается на чат и нажимает «продолжить».

| Вопрос | Ответ «на глаз» | Ответ платформы |
|--------|-----------------|-----------------|
| Когда смотреть? | «Пару минут после выкатки» | Непрерывно на каждом шаге, `interval: 30s` |
| Что считать плохим? | «Графики покраснели» | Порог из SLO: доля не-5xx < 99%, p95 > 250 мс |
| Сравнивать с чем? | С «обычным днём» | Canary-поды отдельно от stable (метка ReplicaSet) |
| Кто откатывает? | Дежурный, если заметил | Контроллер: веса → 100/0, canary → 0 подов, за секунды |
| Ночью? | Никто | Так же, как днём |

Хорошие метрики для анализа — те же SLI, что в SLO: **доля успешных ответов**, **латентность**
(p95/p99 или доля быстрых), насыщение (очередь, пул соединений), для важного — бизнес-метрика
(«ссылок создано в минуту»). Чем меньше доля canary, тем меньше событий и шумнее статистика:
при 2 RPS на canary 1% ошибок — это одна ошибка в минуту. Отсюда правило: сначала **достаточно
трафика**, потом решение.

---

## 2. Argo Rollouts: как устроен

**Argo Rollouts v1.10.0** (08.2026; проверь) — контроллер и CRD `argoproj.io/v1alpha1`:
`Rollout`, `AnalysisTemplate`, `ClusterAnalysisTemplate`, `AnalysisRun`, `Experiment`.

```text
 Rollout linkd (spec.template = шаблон пода, как у Deployment)
    ├── ReplicaSet linkd-6f7c9 (stable, ревизия 3)  ◄── Service linkd-stable (селектор + hash)
    └── ReplicaSet linkd-8d2b1 (canary, ревизия 4)  ◄── Service linkd-canary (селектор + hash)
               метка rollouts-pod-template-hash — её контроллер дописывает в селекторы Service
```text
- **Rollout заменяет Deployment**: те же `replicas`, `selector`, `template`, но вместо
  `strategy: RollingUpdate` — `canary` или `blueGreen`. ReplicaSet'ами управляет контроллер Rollouts.
- **Новая ревизия** появляется при изменении `spec.template` (образ, env, ресурсы). Изменение
  `replicas` — не выкатка.
- **`workloadRef`** — Rollout без своего шаблона ссылается на существующий Deployment
  (`scaleDown: never | onsuccess | progressively`): так мигрируют без переписывания чарта,
  но Deployment потом держат в 0.
- Контроллер сам меняет **селекторы** stable/canary Service и **веса** в маршруте; эти поля
  нельзя «держать» из git (§7).

```bash
kubectl create namespace argo-rollouts
kubectl apply -n argo-rollouts -f https://github.com/argoproj/argo-rollouts/releases/download/v1.10.0/install.yaml
# kubectl-плагин
curl -LO https://github.com/argoproj/argo-rollouts/releases/download/v1.10.0/kubectl-argo-rollouts-linux-amd64
install -m 755 kubectl-argo-rollouts-linux-amd64 ~/.local/bin/kubectl-argo-rollouts
kubectl argo rollouts version
```text
---

## 3. Canary: шаги

```yaml
strategy:
  canary:
    stableService: linkd-stable
    canaryService: linkd-canary
    trafficRouting: { ... }            # §4: без него вес = доля подов
    steps:
      - setWeight: 20                  # 20% трафика в canary
      - pause: { duration: 2m }        # подождать (анализ идёт фоном, §5)
      - setWeight: 50
      - pause: {}                      # бессрочная пауза — ждём человека: promote
      - analysis:                      # inline: шаг не пройдёт, пока анализ не завершится
          templates: [{ templateName: linkd-p95 }]
    # после последнего шага — 100% и canary становится stable
```text
| Шаг | Что делает |
|-----|------------|
| `setWeight: N` | Доля трафика в canary; с trafficRouting — вес в маршруте, без него — доля подов (5 реплик → шаг 20%) |
| `pause: {duration: 2m}` / `pause: {}` | Ждать время / ждать `promote` |
| `analysis` | Запустить AnalysisRun и ждать результата (inline) |
| `setCanaryScale` | Сколько подов canary держать независимо от веса (например, 1 под при весе 5%) |
| `setHeaderRoute` / `setMirrorRoute` / `experiment` | Трафик по заголовку / зеркало / временные baseline и canary для сравнения |

Без `trafficRouting` вес — доля **подов**: при 3 репликах «10%» = 1 из 3 = 33%. Нужен роутер трафика.

---

## 4. ⭐ Трафик через Gateway API: плагин и Envoy Gateway

Для Gateway API Rollouts использует **плагин** `argoproj-labs/rollouts-plugin-trafficrouter-gatewayapi`
(**v0.17.0**, 01.09.2026; проверь): он меняет `weight` у двух `backendRefs` одного правила HTTPRoute.
Работает с любой реализацией Gateway API, у которой есть веса, — в том числе с Envoy Gateway.

```yaml
# 1. подключить плагин — ConfigMap с фиксированным именем в ns контроллера
apiVersion: v1
kind: ConfigMap
metadata: { name: argo-rollouts-config, namespace: argo-rollouts }
data:
  trafficRouterPlugins: |-
    - name: "argoproj-labs/gatewayAPI"
      location: "https://github.com/argoproj-labs/rollouts-plugin-trafficrouter-gatewayapi/releases/download/v0.17.0/gatewayapi-plugin-linux-amd64"
```text
```bash
kubectl apply -f rollouts-plugin.yaml
# 2. права на маршруты (на services у контроллера права уже есть)
kubectl create clusterrole argo-rollouts-gatewayapi --verb=get,list,update,patch \
  --resource=httproutes.gateway.networking.k8s.io,grpcroutes.gateway.networking.k8s.io
kubectl create clusterrolebinding argo-rollouts-gatewayapi --clusterrole=argo-rollouts-gatewayapi \
  --serviceaccount=argo-rollouts:argo-rollouts
kubectl -n argo-rollouts rollout restart deploy/argo-rollouts
kubectl -n argo-rollouts logs deploy/argo-rollouts | grep -i "plugin"   # Downloading plugin ... Download complete
```text
> ⚠️ Контроллер **скачивает** плагин с GitHub при старте. В закрытом контуре — init-контейнер
> с образом `ghcr.io/argoproj-labs/rollouts-plugin-trafficrouter-gatewayapi:&lt;версия&gt;` и
> `location: file:///plugins/...` (значения Helm-чарта `controller.initContainers`, `trafficRouterPlugins`).

```yaml
# 3. маршрут приложения — ОДНО правило с двумя бэкендами
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata: { name: linkd, namespace: linkd }
spec:
  parentRefs: [{ name: web, namespace: infra }]
  hostnames: ["linkd.local"]
  rules:
    - backendRefs:
        - { name: linkd-stable, port: 80, weight: 100 }
        - { name: linkd-canary, port: 80, weight: 0 }
---
# 4. в Rollout
    trafficRouting:
      plugins:
        argoproj-labs/gatewayAPI:
          httpRoute: linkd             # или httpRoutes: [{ name: ... }] — несколько маршрутов
          namespace: linkd
```text
Во время выкатки плагин ставит на маршрут метку `rollouts.argoproj.io/gatewayapi-canary=in-progress`
(`kubectl get httproute -A -l rollouts.argoproj.io/gatewayapi-canary` — «где сейчас идут canary»).

> 💡 Тот же плагин управляет и **GAMMA**-маршрутом (HTTPRoute с `parentRefs` на Service) —
> canary для внутренних вызовов через mesh из [05_gateway_mesh.md](/platform/05-gateway-mesh).

---

## 5. ⭐ AnalysisTemplate на Prometheus

Чтобы мерить **только canary**, метрики должны нести метку ReplicaSet. Rollouts ставит на поды
`rollouts-pod-template-hash`; ServiceMonitor переносит её в метрики через `podTargetLabels`
(как устроен ServiceMonitor — [../Left/02_Monitoring/11_long_term_and_operator.md](/monitoring/11-long-term-and-operator) §8–9).

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata: { name: linkd, namespace: linkd, labels: { release: prometheus } }
spec:
  selector: { matchLabels: { app.kubernetes.io/name: linkd } }   # отдельный Service linkd-metrics
  podTargetLabels: [rollouts-pod-template-hash]   # → метка rollouts_pod_template_hash в метриках
  endpoints: [{ port: http, path: /metrics, interval: 15s }]
```text
```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata: { name: linkd-success-rate, namespace: linkd }
spec:
  args:
    - name: canary-hash
  metrics:
    - name: success-rate
      interval: 30s                    # мерить каждые 30 с (без interval — один замер)
      initialDelay: 30s                # дать подам прогреться и Prometheus — собрать данные
      failureLimit: 1                  # 2-й провал → анализ Failed → abort
      successCondition: result[0] >= 0.99
      provider:
        prometheus:
          address: http://prometheus-kube-prometheus-prometheus.monitoring.svc:9090
          query: |
            sum(rate(linkd_http_requests_total{namespace="linkd", code!~"5..",
                path!~"/healthz|/readyz|/metrics",
                rollouts_pod_template_hash="&#123;&#123;args.canary-hash&#125;&#125;"}[1m]))
            /
            sum(rate(linkd_http_requests_total{namespace="linkd",
                path!~"/healthz|/readyz|/metrics",
                rollouts_pod_template_hash="&#123;&#123;args.canary-hash&#125;&#125;"}[1m]))
---
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata: { name: linkd-p95, namespace: linkd }
spec:
  args: [{ name: canary-hash }]
  metrics:
    - name: p95-latency
      interval: 30s
      count: 4                         # ровно 4 замера → анализ завершается
      failureLimit: 0
      successCondition: result[0] < 0.25   # 250 мс; корзина 0.25 есть у linkd
      provider:
        prometheus:
          address: http://prometheus-kube-prometheus-prometheus.monitoring.svc:9090
          query: |
            histogram_quantile(0.95, sum by (le) (rate(linkd_request_duration_seconds_bucket{
              namespace="linkd", path="/r/:code", rollouts_pod_template_hash="&#123;&#123;args.canary-hash&#125;&#125;"}[2m])))
```text
| Поле | Смысл | По умолчанию |
|------|-------|--------------|
| `interval` | Как часто мерить | Нет — один замер |
| `count` | Сколько замеров всего | Бесконечно при `interval` (до конца выкатки) |
| `successCondition` / `failureCondition` | Выражение на `result` (язык expr) | — |
| `failureLimit` | Сколько провалов допустимо; `-1` — не проваливать | `0` — первый провал = Failed |
| `consecutiveErrorLimit` | Сколько **ошибок запроса** подряд (Prometheus недоступен) | `4` |
| `inconclusiveLimit` | Сколько неопределённых результатов → пауза и решение человека | `0` |
| `initialDelay` | Задержка перед первым замером | — |
| `dryRun` (в Rollout) | Метрика считается, но на выкатку не влияет — для настройки порогов | — |

Результат AnalysisRun: **Successful** → дальше; **Failed** → **abort**: веса 100/0, canary
масштабируется в 0 (после `abortScaleDownDelaySeconds`), Rollout `Degraded`; **Inconclusive**
→ пауза. Ошибки запроса (нет Prometheus, пустой вектор → `result[0]` не существует) копятся
до `consecutiveErrorLimit`.

> ⚠️ **NaN.** Нет трафика в canary → `0/0 = NaN` → любое сравнение ложно → замер Failed.
> Это правильно: «не смогли проверить» ≠ «всё хорошо». Прячь NaN (`isNaN(result[0]) || ...`)
> только если нулевой трафик действительно норма — и тогда добавь генератор нагрузки или
> проверку объёма (`sum(rate(...)) > 1` отдельной метрикой).

### Фоновый и inline-анализ

```yaml
strategy:
  canary:
    analysis:                          # ФОНОВЫЙ: идёт всю выкатку, начиная с шага 1
      templates: [{ templateName: linkd-success-rate }]
      startingStep: 1                  # шаги с 0: начать после setWeight 20, когда трафик уже идёт
      args:
        - name: canary-hash
          valueFrom: { podTemplateHashValue: Latest }   # hash новой ревизии; Stable — старой
    steps:
      - setWeight: 20
      - pause: { duration: 2m }
      - setWeight: 50
      - pause: { duration: 2m }
      - analysis:                      # INLINE: блокирует шаг до результата
          templates: [{ templateName: linkd-p95 }]
          args: [{ name: canary-hash, valueFrom: { podTemplateHashValue: Latest } }]
```text
| | Фоновый (`strategy.canary.analysis`) | Inline (шаг `analysis`) |
|---|------------------------------|--------------------------|
| Когда идёт | Параллельно шагам, до конца выкатки | Только на этом шаге |
| Нужен `count` | Нет (бесконечный с `interval`) | Да — иначе шаг не закончится |
| Для чего | «Сторож»: ошибки не должны расти ни на каком шаге | «Ворота»: перед 100% убедиться в латентности |

Пороги берут из SLO: если SLO 99,9% успешных, canary-порог 99% — это «явно сломано»,
а не «чуть хуже». Сравнение canary со stable в одном запросе (`canary_error_rate <
stable_error_rate * 1.5`) точнее фиксированного порога, но шумнее при малом трафике.

---

## 6. Blue-green с preview и проверкой до переключения

```yaml
strategy:
  blueGreen:
    activeService: linkd-active        # на него смотрит HTTPRoute пользователей
    previewService: linkd-preview      # новая версия, доступна только тестам
    autoPromotionEnabled: false        # переключение — после анализа и/или promote
    prePromotionAnalysis:              # ДО переключения: смоук-тест preview
      templates: [{ templateName: linkd-smoke }]
    postPromotionAnalysis:             # ПОСЛЕ: метрики на боевом трафике; провал → откат
      templates: [{ templateName: linkd-success-rate }]
      args: [{ name: canary-hash, valueFrom: { podTemplateHashValue: Latest } }]
    scaleDownDelaySeconds: 60          # старую версию держим минуту — мгновенный откат
```text
`linkd-smoke` — AnalysisTemplate с провайдером **`job`**: анализ успешен, если Job завершился
с кодом 0. Внутри — `curlimages/curl`: `curl -fsS http://linkd-preview.linkd/readyz` и `POST /api/links`
на preview. Так проверяют версию, на которую ещё не идёт пользовательский трафик.

| | Canary | Blue-green |
|---|--------|-----------|
| Трафик на новую версию | Постепенно, с анализом | Сразу 100% после проверки preview |
| Ресурсы | +1 под на шаг | ×2 на время выкатки |
| Откат | Веса → 0 | Переключить селектор active обратно (секунды, пока жива старая версия) |
| Когда | Stateless API с трафиком для статистики | Нужен мгновенный откат, мало трафика, миграции «всё сразу» |

---

## 7. Rollouts и ArgoCD

- **Health.** ArgoCD понимает Rollout из коробки: `Progressing` во время шагов,
  `Suspended` на паузе, `Healthy` после выкатки, `Degraded` после abort. Приложение
  в ArgoCD на паузе canary — «Suspended», это норма.
- **Действия** в UI ArgoCD на ресурсе Rollout: `resume`, `promote-full`, `abort`, `retry`,
  `restart`. Есть UI-расширение Rollouts для ArgoCD (проверь установку для своей версии).
- **Дрейф.** Плагин меняет веса в HTTPRoute, контроллер — селекторы Service. Иначе ArgoCD
  с `selfHeal` вернёт 100/0 посреди canary:

```yaml
# Application linkd
spec:
  ignoreDifferences:
    - group: gateway.networking.k8s.io
      kind: HTTPRoute
      jqPathExpressions: [".spec.rules[].backendRefs[].weight"]
  syncPolicy:
    syncOptions: [RespectIgnoreDifferences=true]   # не затирать при sync
```text
- ⭐ **Откат в GitOps.** После abort кластер снова на stable, но в git по-прежнему плохой образ:
  ArgoCD `Synced`, Rollout `Degraded`. Настоящий откат — `git revert` коммита с образом;
  `kubectl argo rollouts undo` в GitOps — временная мера, ArgoCD её перезапишет.
- Уведомления о шагах и провалах — Argo Rollouts notifications (Slack, Telegram webhook).

Подробно про Application и sync — [../Left/07_ArgoCD/03_application.md](/argocd/03-application).

---

## 🧪 Мини-лаба: canary linkd с анализом и автооткатом

Стенд: кластер `platform` из [00_INDEX.md](/platform/), Envoy Gateway и Gateway `web`
в `infra` с `allowedRoutes: All` ([../Kubernetes/12_ingress.md](/kubernetes/12-ingress) §7.3),
kube-prometheus-stack релизом `prometheus` в `monitoring`, образ `linkd:2.0.0` в kind (см. тему 05),
Argo Rollouts + плагин + RBAC (§2, §4).

**Шаг 1. Приложение.** Файл `rollout-lab.yaml`: namespace `linkd`; Services `linkd-stable`,
`linkd-canary` (селектор `app: linkd`, порт 80 → 8080) и `linkd-metrics` (тот же селектор,
метка `app.kubernetes.io/name: linkd`, порт с именем `http`); HTTPRoute из §4; ServiceMonitor
и оба AnalysisTemplate из §5; Rollout:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata: { name: linkd, namespace: linkd }
spec:
  replicas: 5
  revisionHistoryLimit: 3
  selector: { matchLabels: { app: linkd } }
  template:
    metadata: { labels: { app: linkd } }
    spec:
      volumes: [{ name: data, emptyDir: {} }]
      containers:
        - name: linkd
          image: linkd:2.0.0
          imagePullPolicy: Never
          ports: [{ name: http, containerPort: 8080 }]
          readinessProbe: { httpGet: { path: /readyz, port: 8080 } }
          volumeMounts: [{ name: data, mountPath: /var/lib/linkd }]
  strategy:
    canary:
      stableService: linkd-stable
      canaryService: linkd-canary
      trafficRouting:
        plugins: { argoproj-labs/gatewayAPI: { httpRoute: linkd, namespace: linkd } }
      analysis: { ... }                # фоновый success-rate — из §5
      steps: [...]                     # шаги и inline-analysis — из §5 «Фоновый и inline-анализ»
```text
```bash
kubectl apply -f rollout-lab.yaml
kubectl argo rollouts get rollout linkd -n linkd --watch      # держи в отдельном окне
```text
**Шаг 2. Нагрузка** — ~20 RPS через Gateway (404 на несуществующий код — это не ошибка сервиса):

```bash
ENVOY=$(kubectl get svc -n envoy-gateway-system \
  -l gateway.envoyproxy.io/owning-gateway-namespace=infra,gateway.envoyproxy.io/owning-gateway-name=web \
  -o jsonpath='{.items[0].metadata.name}')
kubectl -n linkd run load --image=curlimages/curl --command -- sh -c \
  "while true; do curl -s -o /dev/null -H 'Host: linkd.local' http://$ENVOY.envoy-gateway-system/r/nope; sleep 0.05; done"
```text
**Шаг 3. Хороший релиз.** Меняем шаблон пода — новая ревизия:

```bash
# kubectl set env с CRD не работает — правим шаблон патчем (в жизни — коммит в git)
kubectl -n linkd patch rollout linkd --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/env","value":[{"name":"LINKD_LOG_FORMAT","value":"json"}]}]'
kubectl get httproute linkd -n linkd -o jsonpath='{.spec.rules[0].backendRefs[*].weight}{"\n"}'   # 80 20
kubectl -n linkd get analysisrun                          # Running → Successful
```text
Через ~6 минут ревизия 2 — stable, веса снова `100 0`, метка `in-progress` с маршрута снята.

**Шаг 4. Плохой релиз — 30% ответов 500 на `/r/*`:**

```bash
kubectl -n linkd patch rollout linkd --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/env/-","value":{"name":"LINKD_FAULT_ERROR_RATE","value":"0.3"&#125;&#125;]'
```text
Смотри в окне `--watch`: canary получает 20%, через 30–90 с `success-rate` проваливается
(≈ 0,7 < 0,99), AnalysisRun `Failed`, Rollout — `Degraded`, веса `100 0`, canary-поды уходят.
Ошибки видели ~20% запросов в течение минуты-двух — это и есть **радиус поражения** canary.

```bash
kubectl -n linkd describe analysisrun $(kubectl -n linkd get analysisrun -o name | tail -1 | cut -d/ -f2) | grep -A5 "Measurements"
kubectl argo rollouts status linkd -n linkd               # Degraded: RolloutAborted
```text
**Шаг 5. Починка.** Убери `LINKD_FAULT_ERROR_RATE` из шаблона (в жизни — `git revert`), выкатка
пойдёт заново. Попробуй `kubectl argo rollouts promote linkd -n linkd` на паузе и
`promote --full` — чем они отличаются?

**Проверь себя:** почему при `setWeight: 20` и 5 репликах canary-под один, а трафика 20%?
Что будет, если убрать нагрузку из шага 2 и выкатить плохой релиз? Сколько времени прошло
от выкатки до abort и из чего оно сложилось (`initialDelay`, `interval`, окно `rate`, `failureLimit`)?

Уборка: `kubectl delete ns linkd`; `kubectl delete -n argo-rollouts -f &lt;install.yaml&gt;`.

---

## 8. Команды kubectl-плагина

| Команда | Что делает |
|---------|------------|
| `kubectl argo rollouts get rollout linkd -w` | Дерево ревизий, ReplicaSet'ов, AnalysisRun и шагов в реальном времени |
| `kubectl argo rollouts status linkd` | Коротко: Healthy / Paused / Degraded (удобно в CI с `--timeout`) |
| `kubectl argo rollouts set image linkd linkd=linkd:2.1` | Новый образ = новая ревизия |
| `kubectl argo rollouts promote linkd` | Пройти текущую паузу |
| `kubectl argo rollouts promote linkd --full` | Пропустить все шаги и анализы — сразу 100% |
| `kubectl argo rollouts abort linkd` | Прервать: веса 100/0, canary в 0 |
| `kubectl argo rollouts retry rollout linkd` | Повторить прерванную выкатку |
| `kubectl argo rollouts undo linkd` | Откат на предыдущую ревизию (в GitOps — временно) |
| `kubectl argo rollouts dashboard` | Локальный UI на :3100 |

---

## 9. Flagger — альтернатива

**Flagger v1.45.0** (01.09.2026; проверь) — проект экосистемы Flux (`fluxcd/flagger`).

| | Argo Rollouts | Flagger |
|---|---------------|---------|
| Что пишет команда | Rollout **вместо** Deployment (или `workloadRef`) | Обычный Deployment + CRD `Canary` рядом |
| Как устроено | Контроллер ведёт ReplicaSet'ы и веса по шагам | Создаёт копию `&lt;name&gt;-primary`, гоняет трафик между primary и canary, в конце копирует шаблон в primary |
| Шаги | Явный список `steps` | `stepWeight`, `maxWeight`, `interval`, `threshold` |
| Метрики | AnalysisTemplate: Prometheus, Datadog, CloudWatch, Job, Web, плагины | Встроенные `request-success-rate`/`request-duration` для провайдеров + `MetricTemplate` |
| Трафик | Istio, SMI, ALB, NGINX, Traefik, Gateway API (плагин) и др. | Istio, Linkerd, Contour, Gloo, NGINX, Gateway API и др. |
| Нагрузка и ворота | Job-анализ, `pause: {}` | Webhooks: `flagger-loadtester`, ручные ворота |
| UI и GitOps | Dashboard, интеграция с ArgoCD | Интеграция с Flux, UI нет |

Выбор обычно следует за GitOps-инструментом: ArgoCD → Argo Rollouts, Flux → Flagger.

---

## 10. Feature flags: деплой ≠ релиз

Canary проверяет **бинарник**: не падает ли новая сборка. Флаг проверяет **функцию**:
новая логика в коде уже на проде, но включена для 0%, 5% или только для сотрудников.

| | Деплой (canary) | Релиз (флаг) |
|---|-----------------|--------------|
| Что меняется | Версия кода на подах | Поведение для части пользователей |
| Откат | Выкатка назад, минуты | Выключить флаг, секунды, без деплоя |
| Кто управляет | Платформа, пайплайн | Продукт, команда |
| Цель | Не сломать сервис | Проверить гипотезу, выпустить к дате, kill switch |

**OpenFeature** (CNCF, Incubating с 21.11.2023) — стандартный API флагов для разных языков;
провайдеры — flagd, Unleash, Flagsmith, LaunchDarkly, GO Feature Flag. Код зависит от API,
а не от вендора. **flagd** (v0.17.0, 25.09.2026; проверь) — эталонный open source-бэкенд:
читает флаги из файла, ConfigMap, HTTP или gRPC-источника.

```json
{
  "$schema": "https://flagd.dev/schema/v0/flags.json",
  "flags": {
    "linkd-readable-codes": {
      "state": "ENABLED",
      "variants": { "on": true, "off": false },
      "defaultVariant": "off",
      "targeting": {
        "if": [
          { "ends_with": [{ "var": "email" }, "@example.kz"] }, "on",
          { "fractional": [["on", 5], ["off", 95]] }
        ]
      }
    }
  }
}
```text
```python
# linkd: pip install openfeature-sdk openfeature-provider-flagd
from openfeature import api
from openfeature.contrib.provider.flagd import FlagdProvider
from openfeature.evaluation_context import EvaluationContext

api.set_provider(FlagdProvider(host="flagd.linkd.svc", port=8013))   # RPC-режим
flags = api.get_client()

def new_code(user_id: str, email: str) -> str:
    ctx = EvaluationContext(targeting_key=user_id, attributes={"email": email})
    if flags.get_boolean_value("linkd-readable-codes", False, ctx):   # False — если flagd недоступен
        return readable_code()
    return random_code()
```text
Локально: `docker run --rm -p 8013:8013 -v $(pwd):/etc/flagd ghcr.io/open-feature/flagd:latest
start --uri file:./etc/flagd/flags.json`, проверка — `POST localhost:8013/flagd.evaluation.v2.Service/ResolveBoolean`
с телом `{"flagKey":"linkd-readable-codes","context":{"targetingKey":"u42"&#125;&#125;`.

- `fractional` делит по хешу `targetingKey`: пользователь стабильно в одной группе.
- Дефолт в коде (`False`) — поведение при недоступном flagd: безопасный вариант.
- В Kubernetes flagd ставят sidecar'ом через OpenFeature Operator или отдельным Deployment;
  флаги — в git рядом с сервисом (GitOps для флагов).
- ⚠️ **Долг флагов**: каждый флаг — ветка в коде. У флага есть владелец и дата удаления,
  иначе через год никто не знает, что будет при выключении `new-checkout-v2`.

---

## 11. Грабли

| Грабля | Что происходит | Как избежать |
|--------|----------------|--------------|
| Canary без trafficRouting | «10%» = 1 под из 3 = 33% трафика | Роутер (плагин Gateway API) или `setCanaryScale` |
| Метрики без метки ReplicaSet | Анализ смотрит на смесь stable + canary, ошибки canary размыты | `podTargetLabels: [rollouts-pod-template-hash]` + `podTemplateHashValue: Latest` |
| Нет трафика на canary | NaN → Failed (или «успех», если спрятали NaN) | Генератор нагрузки, проверка объёма, `pause` до набора событий |
| Inline-анализ без `count` | Шаг никогда не закончится | `count` или `interval` без бесконечности |
| Окно `rate[5m]` при `interval: 30s` | Анализ видит прошлые 5 минут stable — реагирует поздно | Окно ~2× scrape interval, `initialDelay` |
| ArgoCD `selfHeal` без `ignoreDifferences` | Веса возвращаются в 100/0 посреди выкатки | `ignoreDifferences` на `weight` + `RespectIgnoreDifferences` |
| Abort — и всё, «откатили» | В git плохой образ, следующий sync снова начнёт выкатку | `git revert`, алерт на `Degraded` |
| Плагин не скачался (нет интернета) | Rollout завис, в логах контроллера ошибка загрузки | init-контейнер с образом плагина |
| Миграция БД ломает stable | Canary 20%, но новая схема уже сломала старую версию | Expand/contract-миграции ([../Left/01_Databases/13_schema_migrations.md](/databases/13-schema-migrations)) |

---

## 💼 Как это в DevOps

- Платформа даёт canary **по умолчанию**: поле `delivery: canary` в LinkdApp, оператор создаёт
  Rollout, Services, HTTPRoute и стандартные `ClusterAnalysisTemplate` (успешность, p95 из SLO);
  команда меняет только пороги аргументами. Анализ и SLO — одни и те же PromQL.
- Первое внедрение — с `dryRun` на метриках: неделю смотрим, как бы решал анализ, подбираем
  пороги, и только потом включаем автооткат.
- Deploy ≠ release: рискованные функции прячут за флагом, выкатка идёт canary, релиз —
  флагом по сегментам. Инцидент чинится выключением флага, а не ночным деплоем.
- На собесе ценят цепочку: «canary 20% → анализ по доле 5xx и p95 из Prometheus на
  canary-подах → abort за 1–2 минуты → алерт → `git revert`».

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Поставить Rollouts | `kubectl apply -n argo-rollouts -f .../v1.10.0/install.yaml` |
| Canary через Gateway API | ConfigMap `argo-rollouts-config` + `trafficRouting.plugins.argoproj-labs/gatewayAPI.httpRoute` |
| Мерить только canary | `podTargetLabels` + `podTemplateHashValue: Latest` в args |
| Анализ всю выкатку | `strategy.canary.analysis` + `startingStep` |
| Ворота перед 100% | Шаг `analysis` с `count` |
| Подобрать пороги без риска | `dryRun` в Rollout |
| Смоук preview в blue-green | `prePromotionAnalysis` с провайдером `job` |
| Посмотреть выкатку | `kubectl argo rollouts get rollout linkd -w` |
| Пройти паузу / всё сразу / прервать | `promote` / `promote --full` / `abort` |
| ArgoCD не трогает веса | `ignoreDifferences` на `.spec.rules[].backendRefs[].weight` |
| Выпустить функцию 5% пользователей | Флаг OpenFeature + flagd `fractional` |

---

## 🧠 Что запомнить

1. ⭐ Canary без автоматического анализа — медленный деплой; нужны метрики, пороги и автооткат.
2. Rollout заменяет Deployment (или ссылается через `workloadRef`), выкатка — при изменении шаблона пода.
3. Шаги: `setWeight`, `pause` (с `duration` или бессрочно), `analysis`, `setCanaryScale`, `experiment`.
4. ⭐ Без trafficRouting вес = доля подов; с плагином Gateway API — веса двух `backendRefs` в HTTPRoute.
5. Плагин подключается ConfigMap `argo-rollouts-config` в `argo-rollouts` и требует прав на HTTPRoute.
6. ⭐ AnalysisTemplate: `interval`, `count`, `successCondition`, `failureLimit` (0 по умолчанию),
   `consecutiveErrorLimit` (4); Failed → abort, Inconclusive → пауза.
7. Мерить надо canary отдельно: метка `rollouts-pod-template-hash` в метриках и `podTemplateHashValue: Latest`.
8. NaN и пустой ответ — «не смогли проверить», а не успех; нужен трафик на canary.
9. Фоновый анализ — сторож всей выкатки, inline — ворота на шаге (с `count`).
10. Blue-green: active/preview, `prePromotionAnalysis` до переключения, `postPromotionAnalysis` после,
    `scaleDownDelaySeconds` для мгновенного отката.
11. ⭐ ArgoCD: health Rollout из коробки, `ignoreDifferences` на веса; настоящий откат — `git revert`.
12. Flagger — то же для мира Flux, работает рядом с Deployment через `-primary`.
13. ⭐ Deploy ≠ release: OpenFeature + flagd включают функцию сегменту без деплоя; у флага есть срок жизни.

➡️ Дальше: [07_crossplane_self_service.md](/platform/07-crossplane-self-service) · Задачи: 06_progressive_delivery_tasks.md


---

### Блок A. Теория


**A1.** ⭐ Почему canary без автоматического анализа называют «медленным деплоем»?

<details><summary>Ответ</summary>

Трафик идёт на новую версию постепенно, но решение «хорошо или плохо» принимает человек
по графикам — поздно, субъективно, а ночью никто. Без метрик, порогов и автоотката canary лишь
растягивает выкатку, не снижая риска.

</details>

**A2.** Какие метрики годятся для анализа canary? Почему важен объём трафика на canary?

<details><summary>Ответ</summary>

SLI: доля успешных ответов, латентность (p95/p99 или доля быстрых), насыщение, для важного —
бизнес-метрика. При малом трафике на canary статистика шумная: одна ошибка меняет долю на проценты,
поэтому нужен минимальный объём событий до решения.

</details>

**A3.** Какие CRD приносит Argo Rollouts и для чего каждый?

<details><summary>Ответ</summary>

`Rollout` — нагрузка со стратегией; `AnalysisTemplate`/`ClusterAnalysisTemplate` — шаблон
проверки (в namespace / на кластер); `AnalysisRun` — запущенная проверка; `Experiment` —
временные ReplicaSet'ы для сравнения (baseline vs canary).

</details>

**A4.** ⭐ Чем Rollout отличается от Deployment? Что запускает новую ревизию, а что — нет?

<details><summary>Ответ</summary>

Тот же шаблон пода, `replicas`, `selector`, но стратегия `canary`/`blueGreen` с шагами,
анализом и управлением трафиком; ReplicaSet'ами управляет контроллер Rollouts. Ревизию создаёт
изменение `spec.template`; изменение `replicas` — нет.

</details>

**A5.** Что такое `workloadRef` и когда он полезен?

<details><summary>Ответ</summary>

Rollout ссылается на существующий Deployment вместо своего шаблона; `scaleDown` определяет,
когда гасить Deployment. Полезно для миграции без переписывания чартов.

</details>

**A6.** Что контроллер Rollouts меняет в Service stable и canary и зачем?

<details><summary>Ответ</summary>

Дописывает в селекторы метку `rollouts-pod-template-hash` нужного ReplicaSet: stable Service
смотрит только на stable-поды, canary — только на canary. Иначе веса в маршруте ничего бы не значили.

</details>

**A7.** Перечисли шаги canary и что делает каждый.

<details><summary>Ответ</summary>

`setWeight` — доля трафика; `pause` — время или до `promote`; `analysis` — inline-проверка;
`setCanaryScale` — число canary-подов независимо от веса; `setHeaderRoute`/`setMirrorRoute` —
маршрут по заголовку/зеркало; `experiment` — сравнение временных ReplicaSet'ов.

</details>

**A8.** ⭐ Что будет с распределением трафика без `trafficRouting` при 3 репликах и `setWeight: 10`?

<details><summary>Ответ</summary>

Вес станет долей подов: 1 canary из 3–4 подов — фактически ~25–33% трафика, а не 10%.

</details>

**A9.** Как подключается плагин Gateway API к Argo Rollouts? Какие права ему нужны?

<details><summary>Ответ</summary>

ConfigMap `argo-rollouts-config` в namespace `argo-rollouts` с `trafficRouterPlugins`
(имя `argoproj-labs/gatewayAPI` и `location` бинарника), рестарт контроллера. Права: `get/list/update/patch`
на `httproutes` (и `grpcroutes` и т. п., если нужны), `get` на services.

</details>

**A10.** Как плагин меняет HTTPRoute? Какая метка появляется на маршруте во время выкатки?

<details><summary>Ответ</summary>

Меняет `weight` у двух `backendRefs` (stable и canary) в правиле HTTPRoute. На маршрут
ставится метка `rollouts.argoproj.io/gatewayapi-canary=in-progress`, снимается после 100% stable.

</details>

**A11.** ⭐ Как в AnalysisTemplate мерить только canary-поды, а не смесь со stable?

<details><summary>Ответ</summary>

Перенести метку пода `rollouts-pod-template-hash` в метрики (`podTargetLabels` в ServiceMonitor)
и фильтровать запрос по аргументу `valueFrom.podTemplateHashValue: Latest`.

</details>

**A12.** Что значат `interval`, `count`, `failureLimit`, `consecutiveErrorLimit`, `inconclusiveLimit`,
`initialDelay`? Какие у них значения по умолчанию?

<details><summary>Ответ</summary>

`interval` — период замеров (без него — один замер); `count` — число замеров (по умолчанию
бесконечно при `interval`); `failureLimit` — допустимые провалы (0 — первый же провал = Failed;
`-1` — не проваливать); `consecutiveErrorLimit` — подряд ошибок запроса к провайдеру (4);
`inconclusiveLimit` — неопределённых результатов до паузы (0); `initialDelay` — задержка перед первым замером.

</details>

**A13.** Чем заканчивается AnalysisRun в состояниях Successful, Failed, Inconclusive?

<details><summary>Ответ</summary>

Successful — выкатка идёт дальше; Failed — abort; Inconclusive — пауза до решения человека.

</details>

**A14.** ⭐ Что происходит при abort?

<details><summary>Ответ</summary>

Веса возвращаются 100% в stable, canary-ReplicaSet масштабируется в 0 (после
`abortScaleDownDelaySeconds`), Rollout становится `Degraded` с причиной `RolloutAborted`; шаблон
пода в spec остаётся новым — повторить можно `retry`.

</details>

**A15.** Почему NaN в результате анализа — это провал, и когда NaN допустимо считать успехом?

<details><summary>Ответ</summary>

Сравнение с NaN ложно → `successCondition` не выполнено → замер Failed. Это правильно:
проверить не удалось. Считать NaN успехом (`isNaN(result[0]) || ...`) можно, только если нулевой
трафик действительно норма, и тогда нужна отдельная проверка объёма.

</details>

**A16.** ⭐ Чем фоновый анализ отличается от inline? Когда какой?

<details><summary>Ответ</summary>

Фоновый (`strategy.canary.analysis`) идёт всю выкатку параллельно шагам — «сторож»,
обычно без `count`. Inline (шаг `analysis`) блокирует шаг до результата — «ворота», нужен `count`.
Фоновый — для доли ошибок, inline — для проверок перед переходом на 100%.

</details>

**A17.** Зачем в латентном анализе корзина гистограммы должна совпадать с порогом?

<details><summary>Ответ</summary>

Доля быстрых запросов и перцентиль точнее считаются по границам корзин; `histogram_quantile`
интерполирует внутри корзины, и порог «между корзинами» даёт неточный результат.

</details>

**A18.** Как устроен blue-green в Rollouts? Чем `prePromotionAnalysis` отличается от `postPromotionAnalysis`?

<details><summary>Ответ</summary>

Две Service: `activeService` (боевой трафик) и `previewService` (новая версия). После
готовности новой версии — `prePromotionAnalysis` (до переключения, обычно смоук по preview),
затем переключение active (автоматически или `promote`), `postPromotionAnalysis` — на боевом
трафике, провал → откат. Старая версия живёт `scaleDownDelaySeconds`.

</details>

**A19.** Что такое провайдер `job` в анализе?

<details><summary>Ответ</summary>

Анализ, где измерение — Job: успешное завершение пода = успех. Для смоук- и интеграционных
тестов по preview или canary.

</details>

**A20.** ⭐ Как Rollouts дружит с ArgoCD: health, действия, дрейф?

<details><summary>Ответ</summary>

ArgoCD знает health Rollout (`Progressing`, `Suspended`, `Healthy`, `Degraded`), даёт
действия `resume`, `promote-full`, `abort`, `retry`, `restart`. Веса в HTTPRoute и селекторы
Service меняет контроллер — нужны `ignoreDifferences` и `RespectIgnoreDifferences=true`.

</details>

**A21.** ⭐ Почему после abort в GitOps нужно делать `git revert`?

<details><summary>Ответ</summary>

Abort вернул трафик на stable, но желаемое состояние в git — плохой образ. Следующий sync
или изменение запустят выкатку снова; `undo` из CLI ArgoCD перезапишет. Правду нужно вернуть в git.

</details>

**A22.** Чем Flagger отличается от Argo Rollouts по модели работы?

<details><summary>Ответ</summary>

Flagger оставляет обычный Deployment и CRD `Canary` рядом, создаёт копию `&lt;name&gt;-primary`,
гоняет трафик между primary и canary и в конце копирует шаблон в primary. Метрики — встроенные для
провайдеров + `MetricTemplate`, ворота и нагрузка — webhooks. Argo Rollouts заменяет Deployment
на Rollout со списком шагов и интегрирован с ArgoCD.

</details>

**A23.** ⭐ Чем деплой отличается от релиза? Что даёт feature flag, чего не даёт canary?

<details><summary>Ответ</summary>

Деплой меняет версию кода на подах, релиз — поведение для пользователей. Флаг включает
функцию сегменту (5%, сотрудникам) и выключается за секунды без деплоя; canary проверяет только
то, что новая сборка не ломает сервис.

</details>

**A24.** Что такое OpenFeature и flagd? Что будет в коде, если flagd недоступен?

<details><summary>Ответ</summary>

OpenFeature — вендор-нейтральный API флагов с SDK для языков и провайдерами; flagd —
эталонный open source-бэкенд, флаги из файла/ConfigMap/HTTP. При недоступном flagd SDK вернёт
значение по умолчанию из вызова — поэтому дефолт должен быть безопасным.

</details>

**A25.** Что такое «долг флагов» и как с ним борются?

<details><summary>Ответ</summary>

Каждый флаг — ветка в коде и неизвестное поведение при выключении. У флага — владелец
и срок удаления, удаление — в definition of done, регулярная чистка по отчёту «флаги старше N дней».

</details>

---

### Блок B. «Что произойдёт»


```text:no-line-numbers
# B1
```text
```text:no-line-numbers
replicas: 4
```text
```text:no-line-numbers
strategy:
```text
```text:no-line-numbers
  canary:
```text
```text:no-line-numbers
    steps: [{ setWeight: 10 }, { pause: {} }]
```text
```text:no-line-numbers
# trafficRouting не задан
```text
Вопрос: сколько подов canary и какая доля трафика на паузе?

```text:no-line-numbers
# B2 — изменили только replicas: 5 → 8
```text
Вопрос: начнётся ли canary с шагами?

```text:no-line-numbers
# B3 — анализ
```text
```text:no-line-numbers
interval: 30s
```text
```text:no-line-numbers
failureLimit: 2
```text
```text:no-line-numbers
successCondition: result[0] >= 0.99
```text
```text:no-line-numbers
# замеры: 0.995, 0.97, 0.99, 0.96, 0.98
```text
Вопрос: на каком замере анализ провалится?

```text:no-line-numbers
# B4
```text
```text:no-line-numbers
successCondition: result[0] >= 0.99
```text
```text:no-line-numbers
# canary получает 0 запросов: Prometheus возвращает NaN
```text
Вопрос: что будет с замером? А если запрос вернул пустой вектор?

```text:no-line-numbers
# B5 — inline-шаг
```text
```text:no-line-numbers
- analysis:
```text
```text:no-line-numbers
    templates: [{ templateName: linkd-p95 }]
```text
```text:no-line-numbers
# в шаблоне: interval: 30s, count не задан
```text
Вопрос: что будет с выкаткой?

```text:no-line-numbers
# B6 — анализ без метки ReplicaSet, 5 реплик, canary 1 под при 20% трафика
```text
```text:no-line-numbers
sum(rate(linkd_http_requests_total{code=~"5.."}[1m])) / sum(rate(linkd_http_requests_total[1m]))
```text
```text:no-line-numbers
# canary отдаёт 30% ошибок, stable — 0%
```text
Вопрос: что покажет запрос и заметит ли анализ проблему с порогом «ошибок < 5%»?

```text:no-line-numbers
# B7 — ArgoCD Application linkd: selfHeal: true, ignoreDifferences не задан
```text
```text:no-line-numbers
# идёт canary, плагин поставил веса 80/20
```text
Вопрос: что будет через минуту?

```text:no-line-numbers
# B8 — анализ провалился, Rollout Degraded, в git остался образ linkd:2.1
```text
```text:no-line-numbers
argocd app sync linkd
```text
Вопрос: что случится?

```text:no-line-numbers
# B9 — blue-green
```text
```text:no-line-numbers
autoPromotionEnabled: false
```text
```text:no-line-numbers
prePromotionAnalysis: { templates: [{ templateName: linkd-success-rate }] }
```text
```text:no-line-numbers
# success-rate считает долю не-5xx у preview-подов по боевому трафику
```text
Вопрос: почему анализ, скорее всего, провалится или будет бессмысленным?

```text:no-line-numbers
// B10 — flagd
```text
```text:no-line-numbers
"targeting": { "fractional": [["on", 5], ["off", 95]] }
```text
```text:no-line-numbers
// в коде: get_boolean_value("f", False, EvaluationContext())  — без targeting_key
```text
Вопрос: будет ли пользователь стабильно в одной группе?

---

### Блок C. Практика


### C1. 🔑 Rollouts и плагин
Поставь Argo Rollouts v1.10.0, kubectl-плагин и плагин Gateway API v0.17.0 на стенд.
Найди в логах контроллера строку о загрузке плагина. Проверь права:
`kubectl auth can-i patch httproutes --as=system:serviceaccount:argo-rollouts:argo-rollouts -n linkd`.

### C2. 🔑 Canary с весами
Разверни linkd как Rollout из мини-лабы без анализа (только шаги). Выкати новую ревизию
и на каждом шаге проверь веса в HTTPRoute и число подов canary. Пройди паузу `promote`.

### C3. Без роутера
Удали `trafficRouting`, поставь 3 реплики и `setWeight: 10`. Посчитай curl'ом долю ответов
новой версии (отличи версии переменной `LINKD_FAULT_LATENCY_MS=200` и `time_total`).

### C4. 🔑 Анализ и автооткат
Добавь ServiceMonitor с `podTargetLabels`, AnalysisTemplate success-rate и нагрузку.
Выкати ревизию с `LINKD_FAULT_ERROR_RATE=0.3`. Запиши: время от выкатки до abort,
замеры AnalysisRun, долю ошибок, которую видели клиенты.

### C5. Латентность
Выкати ревизию с `LINKD_FAULT_LATENCY_MS=400` и inline-анализом p95 < 250 мс. Проверь, что
success-rate проходит, а p95 — нет. Объясни, почему для порога 250 мс важно наличие корзины `0.25`.

### C6. dryRun
Включи `dryRun` для метрики success-rate и повтори C4. Что изменилось в поведении и в статусе
AnalysisRun?

### C7. 🔑 Blue-green
Переведи linkd на blue-green с `previewService`, `prePromotionAnalysis` через провайдер `job`
(smoke: `/readyz` + `POST /api/links`) и `postPromotionAnalysis` на success-rate. Сломай
preview так, чтобы smoke провалился (например, `LINKD_DATABASE_URL` на несуществующий хост),
и убедись, что переключения не было.

### C8. ArgoCD
Положи манифесты лабы в git-репозиторий (Gitea из 12-autopilot подойдёт), создай Application.
Проверь health на паузе (`Suspended`) и после abort (`Degraded`). Добавь `ignoreDifferences`
на веса и объясни, что происходило без него.

### C9. Feature flag
Подними flagd с флагом `linkd-readable-codes` (5% + все `@example.kz`). Напиши на Python
функцию, которая возвращает вариант для 1000 случайных `targeting_key`, и посчитай долю `on`.
Выключи флаг в файле и проверь, что поведение меняется без рестарта.

### C10. Сравнение с Flagger (со звёздочкой)
Опиши, как тот же canary linkd выглядел бы во Flagger: какие объекты создаёт команда,
какие создаёт Flagger, где задаются метрики и пороги.

---

### Блок D. Инциденты


**D1.** Rollout завис на первом шаге, AnalysisRun `Running` уже 20 минут, замеров нет. Где искать?

<details><summary>Ответ</summary>

Статус AnalysisRun и `Message`: недоступен Prometheus (адрес, DNS, NetworkPolicy), ошибка
в запросе, `initialDelay` слишком большой, аргументы не подставились (`&#123;&#123;args...&#125;&#125;` в запросе).
Логи контроллера Rollouts.

</details>

**D2.** Canary прошёл анализ, после 100% начались 5xx у 10% пользователей. Почему анализ пропустил?

<details><summary>Ответ</summary>

Анализ смотрел не туда или не так: смесь stable и canary, пути здоровья в знаменателе,
слишком маленький трафик на canary, не та метрика (ошибки на конкретном эндпоинте, которого не было
в трафике), проблема проявилась под нагрузкой 100% (пул соединений, память). Добавить
`postPromotionAnalysis`/анализ на последнем шаге и метрики насыщения.

</details>

**D3.** Каждый canary проваливается на первом замере, хотя версия исправна. Гипотезы?

<details><summary>Ответ</summary>

Замер до прогрева или до первых scrape: нет `initialDelay`, NaN при нулевом трафике;
порог строже, чем реальный уровень ошибок stable; окно `rate` слишком короткое.

</details>

**D4.** После включения Rollouts ArgoCD показывает приложение `OutOfSync` каждые несколько минут. Причина?

<details><summary>Ответ</summary>

ArgoCD видит изменённые контроллером веса HTTPRoute и селекторы Service. Нужны
`ignoreDifferences` на поля, которыми владеет Rollouts.

</details>

**D5.** Контроллер Rollouts после рестарта не может работать с Gateway API, в логах ошибка
загрузки плагина. Кластер в закрытом контуре. Что делать?

<details><summary>Ответ</summary>

Контроллер скачивает плагин по URL. В закрытом контуре — init-контейнер с образом плагина
из внутреннего реестра и `location: file:///plugins/...` или зеркало бинарника во внутреннем HTTP.

</details>

**D6.** Canary 20% новой версии сломал **stable**: у старой версии тоже посыпались ошибки. Как так?

<details><summary>Ответ</summary>

Общие зависимости: миграция схемы БД, несовместимая со старой версией, изменение формата
в общем кэше/очереди, новая версия перегрузила БД. Лечится expand/contract-миграциями и обратной
совместимостью форматов.

</details>

**D7.** Выключили флаг, а новая функция продолжает работать у части пользователей. Гипотезы?

<details><summary>Ответ</summary>

Кэш значений в приложении, другой `targeting_key` у части запросов, флаг читается
в нескольких местах, в одном — старое имя, провайдер в файловом режиме с задержкой опроса,
у части подов старая конфигурация flagd.

</details>

**D8.** Команда жалуется: «canary слишком медленный, выкатка идёт 40 минут». Что предложишь?

<details><summary>Ответ</summary>

Сократить паузы там, где анализ быстро набирает статистику; убрать бессрочные паузы;
больше веса раньше при хорошем трафике; анализ фоном вместо длинных inline; для низкорисковых
сервисов — меньше шагов. Время выкатки — компромисс с радиусом поражения.

</details>

---

### Блок E. Вопросы с собеседования


**1.** ⭐ Расскажи, как устроен canary с автоматическим анализом.

<details><summary>Ответ</summary>

Rollout вместо Deployment, шаги 20 → 50 → 100 с паузами; трафик — веса в HTTPRoute через плагин
   Gateway API; фоновый анализ доли не-5xx на canary-подах из Prometheus, inline p95 перед 100%;
   провал → abort за 1–2 минуты, алерт, `git revert`.

</details>

**2.** Как Argo Rollouts управляет трафиком? Что такое плагин Gateway API?

<details><summary>Ответ</summary>

Через trafficRouting: встроенные роутеры (Istio, ALB, NGINX…) или плагины; плагин Gateway API
   меняет веса двух `backendRefs` в HTTPRoute, работает с любой реализацией с весами.

</details>

**3.** ⭐ Какие метрики и пороги вы берёте для анализа и откуда?

<details><summary>Ответ</summary>

SLI из SLO: доля успешных и латентность по корзине; порог «явно сломано» ниже SLO; мерить
   canary отдельно; для старта — `dryRun` неделю.

</details>

**4.** Canary или blue-green — когда что?

<details><summary>Ответ</summary>

Canary — трафик есть, нужна статистика и малый радиус; blue-green — мгновенный откат,
   мало трафика, проверка до переключения, ×2 ресурсов.

</details>

**5.** Что происходит при abort и как откатиться в GitOps?

<details><summary>Ответ</summary>

Веса 100/0, canary в 0, `Degraded`; в GitOps — `git revert` коммита с образом.

</details>

**6.** Argo Rollouts или Flagger?

<details><summary>Ответ</summary>

Следовать за GitOps: ArgoCD → Rollouts, Flux → Flagger; Rollouts — явные шаги и UI,
   Flagger — рядом с Deployment и webhooks.

</details>

**7.** ⭐ Deploy vs release: зачем feature flags, если есть canary?

<details><summary>Ответ</summary>

Canary ловит поломку сборки, флаг управляет функцией по сегментам и выключается без деплоя;
   вместе: код катится canary, функция включается флагом.

</details>

**8.** Как не ломать stable миграциями БД при canary?

<details><summary>Ответ</summary>

Expand/contract: сначала совместимое расширение схемы, потом код, потом удаление старого.

</details>

**9.** Как внедрить автоматический анализ, не боясь ложных откатов?

<details><summary>Ответ</summary>

`dryRun` и сравнение решений анализа с реальностью, пороги из SLO, `failureLimit` > 0,
   `initialDelay`, достаточный трафик, отдельная проверка объёма.

</details>

**10.** Как платформа даёт canary командам, которые про него ничего не знают?

<details><summary>Ответ</summary>

Canary по умолчанию в API платформы: поле в LinkdApp/чарте, стандартные ClusterAnalysisTemplate,
    ServiceMonitor с `podTargetLabels`, `ignoreDifferences` в шаблоне Application.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Объясняю, почему canary нужен анализ, и какие метрики брать
- [ ] Пишу Rollout с шагами и понимаю, что создаёт новую ревизию
- [ ] ⭐ Подключил плагин Gateway API и видел веса в HTTPRoute на каждом шаге
- [ ] ⭐ Пишу AnalysisTemplate на Prometheus только по canary-подам; знаю дефолты лимитов
- [ ] Видел автооткат при росте 5xx и знаю, сколько времени он занимает
- [ ] Различаю фоновый и inline-анализ, знаю про NaN и `count`
- [ ] Настраивал blue-green с `prePromotionAnalysis` через Job
- [ ] Подружил Rollouts с ArgoCD: health, `ignoreDifferences`, откат через git
- [ ] Сравниваю Argo Rollouts и Flagger
- [ ] ⭐ Объясняю deploy ≠ release и использовал OpenFeature + flagd
