---
title: "22. Практика: лабы из роадмапа"
description: "Девять практических лаб: локальный кластер, манифесты руками, проверки, полный стек, Helm chart, отказоустойчивость, CI/CD, мониторинг, обновление кластера"
---

# 22. Практика: лабы из роадмапа

> Роадмап → 6. Kubernetes → **2. Практика**. Все пять заданий роадмапа разложены
> по шагам с критериями приёмки, плюс четыре лабы «для портфолио», связывающие
> Kubernetes с блоками Docker и CI/CD и с эксплуатацией кластера (лаба 9).

---

## 📋 Список лаб

| № | Лаба | Задание роадмапа | Что получишь | Темы |
|---|------|------------------|--------------|------|
| 1 | 🔑 Кластер локально | «Поставить кластер локально: Minikube, Kind или k3d» | Рабочий стенд с входом на Gateway API | 00, 03, 12 |
| 2 | 🔑 Деплой вручную | «Написать манифесты руками: Deployment + Service + ConfigMap. Обновить образ, посмотреть RollingUpdate, откатиться, скейл 5 → 1» | Манифесты в git | 03-05, 08 |
| 3 | 🔑 Проверки | «Добавить liveness и readiness. Сломать readiness — под выпадает из Service, но не рестартует. Сломать liveness — рестарт» | Понимание проб | 09 |
| 4 | 🔑 Полный стек | «Frontend + Backend + PostgreSQL, но базу не обязательно тащить в кластер» | Реальное приложение | 06, 08, 11, 12, 14 |
| 5 | 🔑 Helm chart | «Обернуть манифесты в chart, вынести в values replicas, image tag, resource limits, ingress host. values-dev и values-prod. Задеплоить в два namespace» | Главный артефакт блока | 15 |
| 6 | Отказоустойчивость | — | Приложение переживает падение ноды | 09, 19 |
| 7 | CI/CD → Kubernetes | — | Пайплайн катит релиз в кластер | 15 + блок CI/CD |
| 8 | Мониторинг и инциденты | — | Метрики, алерты, журнал поломок | 18, 20 |
| 9 | Репетиция обновления кластера | — | Runbook, PDB и drain, снапшот etcd, blue/green 1.35 → 1.36 | 16, 19, 21, 24 |

**Что нужно до начала:**
- kind/minikube (см. обзор темы → «Готовим локальный кластер»);
- приложение из блока Docker с эндпоинтами `/healthz` и `/ready`;
- `kubectl`, `helm`, репозиторий в git.

---

## 🧪 Лаба 1. Кластер локально 🔑

### Что делаем
Поднимаем кластер из трёх нод и базовую обвязку: вход через **Gateway API (Envoy Gateway)**,
metrics-server, удобства kubectl.

> ⚠️ Раньше здесь ставился ingress-nginx из ветки `main`. Проект в EOL с 24.03.2026
> (подробно — [12. Ingress](/kubernetes/12-ingress), §3 и §7), поэтому основной путь — Envoy Gateway,
> а Ingress остался необязательным legacy-шагом 6.

### Шаги
1. Создай `kind-cluster.yaml` (control-plane + 2 worker). `extraPortMappings` 80/443 и метка
   `ingress-ready=true` нужны только для legacy-шага 6 — конфиг в обзоре темы
   → «Готовим локальный кластер».
2. `kind create cluster --name devops --config kind-cluster.yaml`.
   Envoy Gateway v1.9.1 поддерживает Kubernetes 1.33–1.36: если `kubectl get nodes`
   показывает v1.37, пересоздай кластер с `--image kindest/node:v1.36.4`
   (тег — в release notes kind).
3. Поставь Envoy Gateway:
   ```bash
   helm install eg oci://docker.io/envoyproxy/gateway-helm --version v1.9.1 \
     -n envoy-gateway-system --create-namespace
   kubectl wait --timeout=5m -n envoy-gateway-system deployment/envoy-gateway --for=condition=Available
   ```
4. Общий вход стенда — `GatewayClass eg` и `Gateway web` в namespace `infra`
   (им пользуются лабы 4-6). Файл `platform/gateway.yaml`:
   ```yaml
   apiVersion: gateway.networking.k8s.io/v1
   kind: GatewayClass
   metadata: { name: eg }
   spec:
     controllerName: gateway.envoyproxy.io/gatewayclass-controller
   ---
   apiVersion: gateway.networking.k8s.io/v1
   kind: Gateway
   metadata: { name: web, namespace: infra }
   spec:
     gatewayClassName: eg
     listeners:
       - name: http
         protocol: HTTP
         port: 80
         allowedRoutes:
           namespaces: { from: All }   # на стенде; в проде — Selector по метке (тема 12, §7.3)
   ```
   ```bash
   kubectl create namespace infra
   kubectl apply -f platform/gateway.yaml
   kubectl get gatewayclass,gateway -A
   ```
5. Смоук-тест: приложение → HTTPRoute → curl через port-forward. Файл `smoke/hello-route.yaml`:
   ```yaml
   apiVersion: gateway.networking.k8s.io/v1
   kind: HTTPRoute
   metadata: { name: hello }
   spec:
     parentRefs: [{ name: web, namespace: infra }]
     hostnames: ["hello.local"]
     rules:
       - backendRefs: [{ name: hello, port: 80 }]
   ```
   ```bash
   kubectl create deployment hello --image=nginx --port=80
   kubectl expose deployment hello --port=80
   kubectl apply -f smoke/hello-route.yaml
   kubectl describe httproute hello        # Accepted=True, ResolvedRefs=True

   export ENVOY_SERVICE=$(kubectl get svc -n envoy-gateway-system \
     --selector=gateway.envoyproxy.io/owning-gateway-namespace=infra,gateway.envoyproxy.io/owning-gateway-name=web \
     -o jsonpath='{.items[0].metadata.name}')
   kubectl -n envoy-gateway-system port-forward service/${ENVOY_SERVICE} 8888:80 &
   curl -H "Host: hello.local" localhost:8888/      # стартовая страница nginx
   ```
6. *(Необязательно, legacy)* то же на Ingress. ⚠️ ingress-nginx в EOL — только финальный тег,
   только для учёбы и чтения старых кластеров:
   ```bash
   kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.15.1/deploy/static/provider/kind/deploy.yaml
   kubectl -n ingress-nginx wait --for=condition=Ready pod \
     -l app.kubernetes.io/component=controller --timeout=120s
   kubectl create ingress hello --class=nginx --rule="hello.local/*=hello:80"
   curl -H "Host: hello.local" localhost/          # через extraPortMappings 80
   ```
7. Поставь metrics-server (команда — в обзоре темы → «Обвязка»).
8. Настрой `alias k=kubectl`, автодополнение, переменную `do`.

### Критерии приёмки
- [ ] `kubectl get nodes` — три ноды `Ready`
- [ ] `kubectl get pods -A` — все системные поды `Running`
- [ ] `kubectl get gatewayclass` — `eg` с `ACCEPTED True`; у HTTPRoute `hello` оба условия `True`
- [ ] `curl -H "Host: hello.local" localhost:8888/` отвечает через Gateway
- [ ] `kubectl top nodes` отвечает
- [ ] Умею объяснить, за что отвечает каждый под в `kube-system` и `envoy-gateway-system`
- [ ] Знаю, как снести и поднять кластер заново за две минуты

---

## 🧪 Лаба 2. Деплой приложения вручную 🔑

> Задание роадмапа: **написать манифесты руками, не через Helm**.

### Что делаем
Каталог `k8s/` с манифестами приложения из блока Docker.

### Требования
1. `namespace.yaml` — отдельный namespace `demo`.
2. `configmap.yaml` — минимум три параметра приложения и один конфиг-файл.
3. `deployment.yaml`:
   - 3 реплики, метки `app.kubernetes.io/*`;
   - `requests`/`limits`;
   - `envFrom` на ConfigMap;
   - `strategy: RollingUpdate` с `maxSurge: 1, maxUnavailable: 0`;
   - `terminationGracePeriodSeconds` и `preStop`.
4. `service.yaml` — ClusterIP, `targetPort` по имени порта.
5. Всё применяется одной командой: `kubectl apply -f k8s/`.

### Сценарий проверки (ровно то, что просит роадмап)
```bash
kubectl apply -f k8s/
kubectl rollout status deploy/app -n demo

# 1. обновление версии + RollingUpdate в реальном времени
kubectl get pods -n demo -w                       # окно 1
kubectl set image deploy/app app=myapp:1.1 -n demo   # окно 2
while true; do curl -s -o /dev/null -w "%{http_code} " http://app.demo/; sleep 0.2; done  # окно 3

# 2. откат
kubectl rollout history deploy/app -n demo
kubectl rollout undo deploy/app -n demo

# 3. масштабирование
kubectl scale deploy/app --replicas=5 -n demo && kubectl get pods -n demo -o wide
kubectl scale deploy/app --replicas=1 -n demo
```

### Критерии приёмки
- [ ] Манифесты написаны руками и лежат в git
- [ ] Видел, как поды заменяются по одному при `maxUnavailable: 0`
- [ ] Зафиксировал число ошибок в curl-цикле при выкатке
- [ ] Откатился и подтвердил версию образа в подах
- [ ] Отмасштабировал 5 → 1 и понял, какие поды удаляются первыми
- [ ] Могу объяснить каждую строку своих манифестов

---

## 🧪 Лаба 3. Поиграть с проверками 🔑

> Задание роадмапа: *«Сломать readiness — убедиться, что под выпадает из Service,
> но не рестартует. Сломать liveness — увидеть рестарт»*.

### Шаги
1. Добавь в Deployment из лабы 2 `readinessProbe` (`/ready`) и `livenessProbe` (`/healthz`).
2. Подбери параметры так, чтобы понимать формулу
   `initialDelay + period × failureThreshold`.
3. **Ломаем readiness:**
   ```bash
   kubectl exec -n demo <pod> -- rm /usr/share/nginx/html/ready
   kubectl get pod -n demo <pod>          # READY 0/1, RESTARTS 0
   kubectl get endpoints -n demo app      # адрес исчез
   ```
4. **Ломаем liveness:**
   ```bash
   kubectl exec -n demo <pod> -- rm /usr/share/nginx/html/healthz
   kubectl get pod -n demo <pod> -w       # RESTARTS растёт
   kubectl describe pod -n demo <pod>     # Unhealthy + Killing
   ```
5. Добавь `startupProbe` и проверь, что при медленном старте рестартов нет.

### Критерии приёмки
- [ ] Сломанная readiness: под `Running`, `READY 0/1`, рестартов нет, из Endpoints исчез
- [ ] Сломанная liveness: рестарт с событием `Unhealthy`
- [ ] Замеренное время реакции совпадает с расчётом по формуле
- [ ] Понимаю, почему liveness не должна проверять базу
- [ ] Проверил, что трафик не идёт в «неготовый» под

---

## 🧪 Лаба 4. Полный стек приложения 🔑

> Задание роадмапа: *«Frontend + Backend + PostgreSQL, но базу не обязательно
> тащить в кластер»*.

### Архитектура
```text:no-line-numbers
   браузер → Gateway web (ns infra) ◄── HTTPRoute shop (shop.local)
                ├── /        → Service frontend → 2 пода
                └── /api     → Service backend  → 2 пода
                                     │
                                     ▼
                             Service postgres (в кластере: StatefulSet + PVC,
                                               либо ExternalName на внешнюю БД)
```

### Требования
1. Namespace `shop`.
2. **Frontend:** Deployment (2 реплики) + ClusterIP + правило `/` в HTTPRoute
   (на legacy-стенде — Ingress по `/`).
3. **Backend:** Deployment (2 реплики) + ClusterIP + правило `/api` в том же HTTPRoute;
   подключение к БД берётся из ConfigMap (хост, порт, база) и Secret (логин, пароль).
4. **PostgreSQL** — один из двух вариантов:
   - в кластере: StatefulSet, headless Service, `volumeClaimTemplates` на 2Gi;
   - вне кластера: Service типа `ExternalName` (или Service без селектора + EndpointSlice).
5. Init-контейнер у бэкенда: ждёт доступности БД.
6. Job с миграциями перед первым запуском.
7. `readinessProbe` у бэкенда проверяет соединение с БД, `livenessProbe` — нет.
8. Проверка: страница открывается, фронт получает данные из бэкенда, бэкенд — из БД.

### Критерии приёмки
- [ ] Всё поднимается из каталога манифестов одной командой
- [ ] Данные переживают удаление пода БД
- [ ] Пароль лежит только в Secret и не виден в `describe pod`
- [ ] HTTPRoute (или Ingress) маршрутизирует `/` и `/api` в разные сервисы;
  у маршрута `Accepted` и `ResolvedRefs` = `True`
- [ ] Могу нарисовать схему движения запроса от браузера до БД
- [ ] Понимаю, где в этой схеме DNS, Service, Endpoints, kube-proxy

---

## 🧪 Лаба 5. Helm chart для своего приложения 🔑 — главная лаба блока

> Задание роадмапа: *«Обернуть манифесты в chart, вынести в values: replicas,
> image tag, resource limits, ingress host. Сделать values-dev.yaml и values-prod.yaml.
> Задеплоить в два namespace через Helm»*.

### Шаги
1. `helm create chart` и очистка каркаса от примеров.
2. Перенос манифестов лабы 2-4 в `templates/`.
3. Параметризация (строго по списку роадмапа):
   ```yaml
   replicaCount: 2
   image: { repository: myapp, tag: "1.0.0", pullPolicy: IfNotPresent }
   resources:
     requests: { cpu: 100m, memory: 128Mi }
     limits:   { cpu: 500m, memory: 256Mi }
   # «ingress host» из роадмапа: хост живёт в values; основной шаблон — HTTPRoute
   httpRoute: { enabled: true, gateway: { name: web, namespace: infra }, host: app.local }
   ingress:   { enabled: false, className: nginx, host: app.local, tls: { enabled: false } }  # legacy
   ```
4. `_helpers.tpl` с именами и метками.
5. checksum-аннотация на ConfigMap.
6. `values-dev.yaml` и `values-prod.yaml`.
7. Деплой в два namespace:
   ```bash
   helm upgrade --install app ./chart -n dev  -f values-dev.yaml  --create-namespace
   helm upgrade --install app ./chart -n prod -f values-prod.yaml --create-namespace
   helm list -A
   ```

### Дополнительно (сильно повышает ценность чарта)
- `helm lint` и `helm template` проходят без ошибок;
- хук `pre-upgrade` с Job миграций;
- `--atomic` при обновлении, проверка отката;
- `NOTES.txt` с адресом приложения после установки.

### Критерии приёмки
- [ ] Один чарт, два окружения, отличия только в values
- [ ] `helm template` с обоими файлами даёт ожидаемый diff
- [ ] Обновление тега образа через `--set image.tag=...` работает
- [ ] Изменение ConfigMap вызывает пересоздание подов (checksum)
- [ ] `helm rollback` возвращает предыдущую версию
- [ ] Чарт лежит в git и его можно показать на собеседовании

---

## 🧪 Лаба 6. Отказоустойчивость (сверх роадмапа)

### Шаги
1. Добавь в чарт: 3 реплики, `podAntiAffinity` (preferred) по `hostname`,
   `topologySpreadConstraints`, PodDisruptionBudget с `maxUnavailable: 1`.
2. Настрой `tolerationSeconds: 30` для `not-ready`/`unreachable`.
3. Проверь:
   ```bash
   kubectl get pods -o wide                 # реплики на разных нодах
   docker stop devops-worker                # «падение» ноды
   while true; do curl -s -o /dev/null -w "%{http_code} " -H "Host: app.local" localhost:8888/; sleep 0.2; done
   ```
   > ⚠️ `port-forward` из лабы 1 держится за один под Envoy. Если он жил на остановленной
   > ноде, цикл оборвётся — это падение входа, а не приложения: проверь
   > `kubectl -n envoy-gateway-system get pods -o wide`, перезапусти port-forward и сделай
   > вывод, почему прокси входа тоже нужны реплики на разных нодах.
4. Отдельно проверь плановое обслуживание: `kubectl drain` с PDB.

### Критерии приёмки
- [ ] Реплики разложены по разным нодам
- [ ] При падении ноды сервис остаётся доступен (посчитай долю ошибок)
- [ ] `drain` проходит без простоя благодаря PDB
- [ ] Замерил, через сколько поды переехали, и понимаю, чем это задаётся

---

## 🧪 Лаба 7. Пайплайн CI/CD → Kubernetes (сверх роадмапа)

### Что делаем
Связываем блок CI/CD с этим блоком: коммит → образ → деплой в кластер.

```yaml
stages: [build, deploy]

build:
  stage: build
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA

deploy:
  stage: deploy
  script:
    - helm lint ./chart
    - helm template app ./chart -f values-$ENV.yaml > /dev/null
    - helm upgrade --install app ./chart -n $ENV -f values-$ENV.yaml
        --set image.tag=$CI_COMMIT_SHORT_SHA
        --atomic --timeout 5m
  environment:
    name: $ENV
```

### Требования
1. ServiceAccount с минимальными правами в namespace (тема 17), не `cluster-admin`.
2. Kubeconfig с токеном SA — в защищённой CI-переменной.
3. Деплой в dev автоматически, в prod — по кнопке (`when: manual`).
4. Проверка успеха через `--atomic` (или `kubectl rollout status`) и автоматический откат.

### Критерии приёмки
- [ ] Коммит в main приводит к новой версии в dev без ручных действий
- [ ] Прод катится по кнопке
- [ ] Битый образ не «проливается»: деплой падает и откатывается
- [ ] Пайплайн не имеет прав больше, чем нужно
- [ ] Могу показать пайплайн и объяснить каждый шаг

---

## 🧪 Лаба 8. Мониторинг и журнал инцидентов (сверх роадмапа)

### Шаги
1. Поставь kube-prometheus-stack (Helm).
2. Добавь `ServiceMonitor` для своего приложения, открой Grafana.
3. Настрой три алерта: рестарты подов, `Pending` дольше 5 минут, рост 5xx.
4. Устрой 10 поломок из задач темы 20 и заведи файл `INCIDENTS.md`:

```markdown
## 2026-09-13 — приложение отдавало 503
**Симптом:** ingress отвечал 503, поды Running
**Первая команда:** kubectl get endpoints app
**Причина:** readinessProbe на /health вместо /ready
**Лечение:** исправлен путь пробы
**Профилактика:** проверять пробы в helm template перед мержем
```

### Критерии приёмки
- [ ] Метрики приложения видны в Grafana
- [ ] Алерты срабатывают на реальной поломке
- [ ] В `INCIDENTS.md` минимум 10 записей
- [ ] По каждой записи могу рассказать историю на собеседовании

---

## 🧪 Лаба 9. Репетиция обновления кластера: runbook, PDB, etcd, blue/green (сверх роадмапа)

> Теория — [24. Жизненный цикл кластера](/kubernetes/24-cluster-lifecycle). kind не умеет обновлять ноды
> на месте (ноды — контейнеры из готового образа), поэтому репетируем то, что в проде
> важнее самих команд: runbook, pre-checks, drain с PDB, бэкап и **обновление через второй
> кластер**. Команды `kubeadm upgrade` — в теме 16.

### Что делаем
Кластер `blue` на 1.35 (как будто прод) и `green` на 1.36 (целевой). Приложение из лабы 5
катим в оба из одного git, проверяем и «переключаем трафик».

### Шаги
1. **Runbook.** Скопируй шаблон из темы 24 §11 в `upgrade/RUNBOOK.md` и заполни для
   1.35 → 1.36: окно, критерии отката, матрица аддонов (Envoy Gateway v1.9.1 — 1.33–1.36 ✅,
   metrics-server, KEDA — если ставил).
2. **Кластеры.** Конфиг без `extraPortMappings` (два кластера не могут занять 80/443):
   ```bash
   cat > kind-3nodes.yaml <<'YAML'
   kind: Cluster
   apiVersion: kind.x-k8s.io/v1alpha4
   nodes: [{ role: control-plane }, { role: worker }, { role: worker }]
   YAML
   # теги — из release notes kind v0.33 (там же digest'ы)
   kind create cluster --name blue  --image kindest/node:v1.35.8 --config kind-3nodes.yaml
   kind create cluster --name green --image kindest/node:v1.36.4 --config kind-3nodes.yaml
   kubectl --context kind-blue get nodes; kubectl --context kind-green get nodes
   ```
3. **Blue = прод.** В `kind-blue`: Envoy Gateway и `platform/gateway.yaml` (лаба 1), чарт
   из лабы 5 с `values-prod.yaml` (3 реплики, PDB `maxUnavailable: 1` из лабы 6).
4. **Устаревшие API.** Положи в `legacy/` CronJob `batch/v1beta1`, затем:
   ```bash
   kubectl config use-context kind-blue
   pluto detect-files -d legacy/ --target-versions k8s=v1.36.0
   pluto detect-helm -o wide --target-versions k8s=v1.36.0
   kubectl get --raw /metrics | grep apiserver_requested_deprecated_apis   # пусто? объясни почему
   kubectl convert -f legacy/cronjob.yaml --output-version batch/v1 > legacy/cronjob-v1.yaml
   ```
5. **Pre-checks и PDB.**
   ```bash
   kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
   kubectl get pdb -A
   kubectl drain blue-worker --ignore-daemonsets --delete-emptydir-data --timeout=120s   # ✅ проходит
   kubectl uncordon blue-worker
   # ломаем: одиночка с жёстким PDB
   kubectl -n prod create deployment lonely --image=nginx
   kubectl -n prod create pdb lonely --selector=app=lonely --min-available=1
   NODE=$(kubectl -n prod get pod -l app=lonely -o jsonpath='{.items[0].spec.nodeName}')
   kubectl drain "$NODE" --ignore-daemonsets --delete-emptydir-data --timeout=60s   # ⛔ таймаут
   ```
   Найди виновника через `kubectl get pdb -A`, почини правильно (2 реплики или
   `maxUnavailable: 1`), повтори drain, верни ноду `uncordon`.
6. **Бэкап etcd blue** (в etcd 3.6 `status`/`restore` — через `etcdutl`, проверь образ):
   ```bash
   kubectl -n kube-system exec etcd-blue-control-plane -- etcdctl \
     --endpoints=https://127.0.0.1:2379 --cacert=/etc/kubernetes/pki/etcd/ca.crt \
     --cert=/etc/kubernetes/pki/etcd/server.crt --key=/etc/kubernetes/pki/etcd/server.key \
     snapshot save /var/lib/etcd/snap.db
   mkdir -p backup && docker cp blue-control-plane:/var/lib/etcd/snap.db ./backup/etcd-blue-$(date +%F).db
   ```
7. **Green из того же git.** Те же команды шага 3 с `--kube-context kind-green`
   (или ArgoCD из темы 21, указывающий на тот же репозиторий). Никаких ручных правок в green.
8. **Смоук и «переключение».** Подними port-forward на Envoy каждого кластера
   (blue → 8888, green → 8889, селектор — лаба 1, шаг 5), сравни ответы. Запусти curl-цикл
   из лабы 6 на 8888, затем «переключи трафик»: останови port-forward blue и подними
   port-forward green на 8888. Посчитай ошибки за время переключения. Откат — наоборот.
9. **Post-checks на green:** `kubectl version`, поды, `pluto detect-helm`, метрика
   устаревших API. Через «период наблюдения» — `kind delete cluster --name blue`.
10. **Отчёт** в `upgrade/REPORT.md`: сколько заняло, что сломалось, что меняешь в runbook.

### Критерии приёмки
- [ ] Runbook заполнен до начала работ, в нём есть критерии отката
- [ ] pluto нашёл устаревший API, манифест переведён `kubectl convert`; результат метрики apiserver объяснён
- [ ] Видел drain, заблокированный PDB, и починил его без `--disable-eviction`
- [ ] Снапшот etcd лежит **вне** кластера
- [ ] Green поднят из того же git без ручных правок, смоук-тесты зелёные
- [ ] Посчитал ошибки при переключении и умею откатиться на blue
- [ ] Могу рассказать на собесе, чем репетиция в kind отличается от обновления прода kubeadm

---

## 🏁 Итоговый чек-лист блока

- [ ] Лаба 1: кластер поднят и умею пересоздавать
- [ ] Лаба 2: манифесты руками, RollingUpdate, откат, скейл 5 → 1
- [ ] Лаба 3: сломанные readiness и liveness проверены на практике
- [ ] Лаба 4: фронт + бэк + БД работают вместе
- [ ] Лаба 5: 🔑 свой чарт, два окружения, два namespace
- [ ] Лаба 6: приложение переживает падение ноды
- [ ] Лаба 7: пайплайн катит релиз и откатывает неудачный
- [ ] Лаба 8: метрики, алерты и журнал инцидентов
- [ ] Лаба 9: обновление отрепетировано по runbook — PDB, бэкап etcd, blue/green
- [ ] Всё лежит в git с README и схемой архитектуры
