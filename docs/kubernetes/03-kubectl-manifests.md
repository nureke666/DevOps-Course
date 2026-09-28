---
title: "03. kubectl и манифесты"
description: "Анатомия манифеста, императивно vs декларативно, labels и selectors, основные команды kubectl"
---

# 03. kubectl и манифесты

> Роадмап → 6. Kubernetes → 1. Теория → Основные сущности:
> «Здесь надо **сразу учить команды kubectl** и понимать, что для чего используется
> + как их писать».
> **После темы ты умеешь:** читать и писать манифесты руками, находить любую информацию
> об объекте и не бояться `kubectl` вообще.

---

## 🗺️ Карта темы

```text:no-line-numbers
        ~/.kube/config                 ЧТО ДЕЛАЕМ С ОБЪЕКТОМ
        (кластер + юзер + ns)   ┌──────────────────────────────────┐
              │                 │ get      — список/кратко         │
              ▼                 │ describe — подробно + СОБЫТИЯ    │
        kubectl ──── HTTPS ───► │ logs     — что пишет контейнер   │
              │        :6443    │ exec     — зайти внутрь          │
              │                 │ apply    — применить манифест    │
              │                 │ delete   — удалить               │
              │                 │ edit     — правка на лету        │
              │                 │ explain  — документация полей    │
              │                 └──────────────────────────────────┘
              ▼
        ЛЮБОЙ МАНИФЕСТ = 4 обязательных поля
        apiVersion / kind / metadata / spec
```

---

## 1. kubeconfig: к какому кластеру ты вообще подключён

```bash
kubectl config current-context          # ⭐ ПЕРВАЯ команда рабочего дня
kubectl config get-contexts             # все известные кластеры
kubectl config use-context prod         # переключиться
kubectl config set-context --current --namespace=myapp   # ns по умолчанию
kubectl config view --minify             # что реально используется сейчас
```

Структура `~/.kube/config`:

```yaml
clusters:   # адрес API server + CA
  - name: kind-devops
    cluster: { server: https://127.0.0.1:6443, certificate-authority-data: LS0t... }
users:      # кто ты: сертификат, токен, exec-плагин облака
  - name: kind-devops
    user: { client-certificate-data: LS0t..., client-key-data: LS0t... }
contexts:   # связка кластер + пользователь + namespace
  - name: kind-devops
    context: { cluster: kind-devops, user: kind-devops, namespace: default }
current-context: kind-devops
```

> ⚠️ **Самая дорогая ошибка новичка** — выполнить команду в проде, думая, что это dev.
> Ставь контекст в приглашение шелла (`kube-ps1`, `starship`) и приучись
> к `kubectl config current-context` перед любой опасной командой.

**Полезные инструменты:** `kubectx` / `kubens` — быстрое переключение кластера и namespace;
`k9s` — терминальный «дашборд», очень помогает на старте.

---

## 2. Анатомия манифеста ⭐

```yaml
apiVersion: apps/v1          # группа API и версия объекта
kind: Deployment             # тип объекта
metadata:                    # ИМЯ и метки — как объект найти
  name: web
  namespace: myapp
  labels:
    app: web
    env: dev
  annotations:               # произвольные данные для людей и инструментов
    description: "Основной фронт"
spec:                        # ЖЕЛАЕМОЕ состояние — то, что пишешь ты
  replicas: 3
  ...
status:                      # ФАКТИЧЕСКОЕ состояние — пишет кубер, руками НЕ трогаем
  readyReplicas: 3
```

| Поле | Кто заполняет | Замечание |
|------|---------------|-----------|
| `apiVersion` | ты | `v1` для core-объектов (Pod, Service, ConfigMap), `apps/v1` для Deployment/DaemonSet/StatefulSet, `batch/v1` для Job/CronJob |
| `kind` | ты | С заглавной буквы, ровно как в `kubectl api-resources` |
| `metadata.name` | ты | Уникально в пределах namespace и типа |
| `metadata.labels` | ты | ⭐ Через них всё связывается |
| `spec` | ты | Желаемое состояние |
| `status` | кубер | Только чтение |

Узнать `apiVersion` для типа:
```bash
kubectl api-resources | grep -i ingress
# NAME       SHORTNAMES   APIVERSION             NAMESPACED   KIND
# ingresses  ing          networking.k8s.io/v1   true         Ingress
```

---

## 3. Императивно vs декларативно

| Подход | Пример | Когда применять |
|--------|--------|-----------------|
| **Императивно** | `kubectl create deployment web --image=nginx` | Быстрый тест, демо, экзамен на скорость |
| **Декларативно** ⭐ | `kubectl apply -f deploy.yaml` | **Всегда в работе**: файл лежит в git, история изменений видна |

**Главный приём: генерировать YAML, а не писать с нуля.**

```bash
# каркас Deployment без создания объекта
kubectl create deployment web --image=nginx:1.25 --replicas=3 \
  --dry-run=client -o yaml > deploy.yaml

# каркас Service
kubectl create service clusterip web --tcp=80:8080 --dry-run=client -o yaml

# каркас пода (часто самый удобный старт)
kubectl run tmp --image=busybox --dry-run=client -o yaml -- sleep 3600
```

Дальше файл правится руками и уезжает в git. Это ровно то, что требует практика роадмапа:
«написать манифесты руками (не через Helm)».

**Три способа менять объект:**
```bash
kubectl apply -f deploy.yaml                     # ⭐ правильный: изменили файл → применили
kubectl edit deployment web                      # открыть в редакторе (для отладки)
kubectl patch deployment web -p '{"spec":{"replicas":5}}'   # точечно, удобно в скриптах
kubectl set image deployment/web nginx=nginx:1.26            # частный случай — смена образа
```

> ⚠️ `edit`/`patch`/`scale` создают **дрейф**: кластер не совпадает с git.
> Следующий `apply` может неожиданно откатить изменения. Правило: руками —
> только на время инцидента, потом сразу правим манифест.

---

## 4. Основные команды ⭐

### Смотреть

```bash
kubectl get pods                                  # в текущем namespace
kubectl get pods -A                               # во всех
kubectl get pods -o wide                          # + IP и нода
kubectl get pods -w                               # следить в реальном времени
kubectl get pod web-xxx -o yaml                   # полный объект
kubectl get pods -l app=web                       # по метке
kubectl get all                                   # основные типы разом (не буквально всё)
kubectl get pods --sort-by=.status.startTime
kubectl get pods -o jsonpath='{.items[*].spec.containers[*].image}'
kubectl get pods --field-selector status.phase=Running
```

### Разбираться

```bash
kubectl describe pod web-xxx          # ⭐ ГЛАВНАЯ команда отладки: спека + СОБЫТИЯ внизу
kubectl logs web-xxx                  # логи
kubectl logs web-xxx -c sidecar       # конкретный контейнер
kubectl logs web-xxx --previous       # ⭐ логи УПАВШЕГО контейнера — спасение при CrashLoop
kubectl logs -f -l app=web --tail=100 # поток по метке
kubectl get events --sort-by=.lastTimestamp
kubectl get events --field-selector type=Warning -A
```

### Вмешиваться

```bash
kubectl exec -it web-xxx -- sh                    # зайти внутрь
kubectl exec web-xxx -- env                       # выполнить и выйти
kubectl port-forward pod/web-xxx 8080:80          # проброс на локальную машину
kubectl port-forward svc/web 8080:80              # то же через сервис
kubectl cp web-xxx:/app/log.txt ./log.txt         # копирование файлов
kubectl debug -it web-xxx --image=busybox --target=app   # эфемерный контейнер (тема 20)
```

### Управлять

```bash
kubectl apply -f manifests/                       # каталог целиком
kubectl apply -k overlays/dev/                    # kustomize
kubectl delete -f deploy.yaml
kubectl delete pod web-xxx --grace-period=0 --force   # ⚠️ крайняя мера
kubectl scale deployment web --replicas=5
kubectl rollout restart deployment web            # ⭐ перезапуск всех подов без изменения образа
kubectl rollout status deployment web
```

### Диагностика кластера

```bash
kubectl top nodes                                 # нужен metrics-server
kubectl top pods -A --sort-by=memory
kubectl get nodes -o wide
kubectl describe node worker-1 | grep -A10 "Allocated resources"
kubectl api-resources
kubectl explain deployment.spec.strategy          # ⭐ документация прямо из кластера
kubectl explain pod.spec --recursive | head -40
```

---

## 5. Namespace'ы

```bash
kubectl get ns
kubectl create namespace myapp
kubectl -n myapp get pods
kubectl config set-context --current --namespace=myapp    # чтобы не писать -n каждый раз
kubectl delete namespace myapp                            # ⚠️ удалит ВСЁ содержимое
```

| Что знать | Подробности |
|-----------|-------------|
| Зачем | Разделение окружений/команд, уникальность имён, точка применения квот и RBAC |
| Namespaced vs cluster-scoped | Pod/Service/Deployment — в namespace; Node/PV/StorageClass/ClusterRole — общие |
| Проверить | `kubectl api-resources --namespaced=true` |
| Сеть | Namespace **не изолирует сеть** по умолчанию: под из `dev` достучится до `prod`. Изоляция — это NetworkPolicy (тема 13) |
| DNS | Полное имя сервиса: `svc.namespace.svc.cluster.local` |
| Системные | `default`, `kube-system`, `kube-public`, `kube-node-lease` |

---

## 6. ⭐ Labels и selectors — то, на чём держится весь кубер

```yaml
metadata:
  labels:
    app: web              # что за приложение
    env: prod             # окружение
    version: v2           # версия
    tier: frontend        # слой
```

```bash
kubectl get pods -l app=web
kubectl get pods -l 'env in (prod,staging)'
kubectl get pods -l app=web,env=prod            # И (AND)
kubectl get pods -l '!canary'                   # метки нет
kubectl label pod web-xxx canary=true           # добавить
kubectl label pod web-xxx canary-                # удалить (минус в конце)
kubectl get pods --show-labels
```

**Где селекторы работают:**

| Объект | Что выбирает |
|--------|--------------|
| Deployment/ReplicaSet | какими подами управляет (`spec.selector.matchLabels`) |
| Service | на какие поды слать трафик (`spec.selector`) |
| NetworkPolicy | к каким подам применяется правило |
| PodAffinity / topologySpread | относительно каких подов размещать |
| `kubectl` | фильтр вывода |

> ⚠️ **Классическая ошибка:** метки в `Service.spec.selector` не совпали с метками
> подов → Endpoints пуст → «сервис есть, а не отвечает». Проверка:
> `kubectl get endpoints <svc>` — если пусто, ищи расхождение в метках.

**Labels vs annotations:** по меткам ищут и выбирают (они индексируются),
в аннотациях хранят произвольные данные для инструментов
(`kubectl.kubernetes.io/last-applied-configuration`, настройки ingress-контроллера,
чексуммы конфигов). Искать по аннотациям нельзя.

**Рекомендованные метки** (`app.kubernetes.io/...`) — общепринятое соглашение,
их же проставляет Helm:
```yaml
labels:
  app.kubernetes.io/name: web
  app.kubernetes.io/instance: web-prod
  app.kubernetes.io/version: "1.2.3"
  app.kubernetes.io/component: frontend
  app.kubernetes.io/managed-by: Helm
```

---

## 7. Несколько объектов в одном файле

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  replicas: 2
  selector:
    matchLabels: { app: web }
  template:
    metadata:
      labels: { app: web }       # ⭐ должно совпадать с selector
    spec:
      containers:
        - name: nginx
          image: nginx:1.25
          ports:
            - containerPort: 80
---
apiVersion: v1
kind: Service
metadata:
  name: web
spec:
  selector: { app: web }         # ⭐ должно совпадать с метками ПОДОВ
  ports:
    - port: 80
      targetPort: 80
```

Разделитель `---`. Применяется одной командой: `kubectl apply -f app.yaml`.
Порядок в файле для кубера не важен (он сам досоздаст связи), но для читаемости
принято: Namespace → ConfigMap/Secret → Deployment → Service → Ingress.

---

## 8. Чтение вывода `get`

```text:no-line-numbers
NAME                   READY   STATUS             RESTARTS       AGE
web-7d8f9c5b4-abcde    1/1     Running            0              5m
web-7d8f9c5b4-fghij    0/1     CrashLoopBackOff   5 (2m ago)     8m
web-7d8f9c5b4-klmno    0/1     Pending            0              8m
```

| Колонка | Что означает |
|---------|--------------|
| `READY 1/1` | готовых контейнеров / всего в поде (готов = прошёл readinessProbe) |
| `STATUS` | `Running`, `Pending`, `ContainerCreating`, `CrashLoopBackOff`, `ImagePullBackOff`, `Completed`, `Error`, `Terminating`, `Evicted` |
| `RESTARTS` | сколько раз kubelet перезапускал контейнер, в скобках — когда последний |
| `AGE` | возраст объекта пода |

Правило: `READY 0/1` + `Running` = контейнер работает, но **не готов** (readinessProbe).
`Pending` = ещё не назначена нода или нет ресурсов. Разбор — тема 20.

---

## 9. Форматы вывода и выборки

```bash
kubectl get pods -o json | jq '.items[] | {name:.metadata.name, node:.spec.nodeName}'
kubectl get pods -o custom-columns='NAME:.metadata.name,IMAGE:.spec.containers[0].image'
kubectl get pod web-xxx -o jsonpath='{.status.podIP}'
kubectl get deploy web -o yaml > backup.yaml      # выгрузить объект
kubectl get pods -o name                          # pod/web-xxx — удобно для xargs
```

Быстрый способ узнать, какие поля вообще существуют:
```bash
kubectl explain deployment.spec.template.spec.containers.livenessProbe
```

---

## 10. Сокращения, которые сэкономят часы

| Полное | Короткое |
|--------|----------|
| pods | `po` |
| deployments | `deploy` |
| services | `svc` |
| namespaces | `ns` |
| configmaps | `cm` |
| persistentvolumeclaims | `pvc` |
| statefulsets | `sts` |
| daemonsets | `ds` |
| ingresses | `ing` |
| replicasets | `rs` |
| serviceaccounts | `sa` |
| nodes | `no` |

```bash
alias k=kubectl
source <(kubectl completion bash)
complete -o default -F __start_kubectl k
export do="--dry-run=client -o yaml"     # трюк с экзамена CKAD
k create deploy web --image=nginx $do > d.yaml
```

---

## 💼 Как это в DevOps

- В рабочем репозитории лежат манифесты или чарт; `kubectl apply` из консоли на проде —
  повод для вопроса «почему не через пайплайн?».
- `kubectl describe` + `kubectl logs --previous` закрывают процентов семьдесят инцидентов.
- Доступ на прод обычно read-only через RBAC (тема 17), а изменения — только через MR.
- `kubectl get events` — первое, что смотрят при «странном» поведении, потому что
  туда пишут все компоненты: scheduler, kubelet, контроллеры.
- Привычка проверять контекст перед командой ценится дороже, чем знание редких флагов.

---

## 📌 Шпаргалка

| Хочу | Команда |
|------|---------|
| Проверить, куда подключён | `kubectl config current-context` |
| Сменить namespace по умолчанию | `kubectl config set-context --current --namespace=X` |
| Каркас манифеста | `kubectl create deploy web --image=nginx --dry-run=client -o yaml` |
| Применить | `kubectl apply -f file.yaml` (или каталог) |
| Посмотреть подробности и события | `kubectl describe pod NAME` |
| Логи упавшего контейнера | `kubectl logs NAME --previous` |
| Зайти в контейнер | `kubectl exec -it NAME -- sh` |
| Пробросить порт локально | `kubectl port-forward svc/web 8080:80` |
| Перезапустить все поды | `kubectl rollout restart deployment web` |
| Найти по метке | `kubectl get pods -l app=web` |
| Все события с предупреждениями | `kubectl get events -A --field-selector type=Warning` |
| Документация по полю | `kubectl explain pod.spec.containers` |
| Удалить всё из файла | `kubectl delete -f file.yaml` |

---

## 🧠 Что запомнить

1. Любой манифест = `apiVersion` + `kind` + `metadata` + `spec`; `status` пишет кубер.
2. `spec` — желаемое, `status` — фактическое. Руками правим только `spec`.
3. В работе — **декларативно**: `apply -f` и файл в git. Императив — только для черновиков.
4. Каркасы генерируй через `--dry-run=client -o yaml`, не пиши YAML с нуля.
5. `kubectl describe` показывает **события** — главный источник правды при отладке.
6. `kubectl logs --previous` — логи контейнера **до** рестарта.
7. Метки связывают всё: Service→поды, Deployment→поды, политики→поды.
8. Пустой `kubectl get endpoints svc` почти всегда означает несовпадение меток.
9. Namespace изолирует имена и права, но **не изолирует сеть**.
10. Проверяй `current-context` до опасных команд — это дешевле любого инцидента.
11. `kubectl explain` — офлайн-документация, соответствующая версии твоего кластера.
12. `kubectl rollout restart` перезапускает поды без правки образа — очень частая команда.

---

## Задачи

> Роадмап требует «сразу учить команды kubectl» — поэтому блок C здесь самый большой.
> Цель: довести `describe`, `logs`, `apply`, `explain` до автоматизма.

---

### Блок A. Теория

**A1.** Назови четыре обязательных поля любого манифеста.

<details><summary>Ответ</summary>

`apiVersion`, `kind`, `metadata` (как минимум `name`), `spec`
(у некоторых типов вместо `spec` — `data`, например у ConfigMap/Secret).

</details>

**A2.** ⭐ В чём разница между `spec` и `status`? Какое поле правишь ты?

<details><summary>Ответ</summary>

`spec` — желаемое состояние, его пишет пользователь; `status` — фактическое,
его пишет кубер. Руками правится только `spec`.

</details>

**A3.** Какой `apiVersion` у Pod, Service, Deployment, Job, Ingress?

<details><summary>Ответ</summary>

Pod — `v1`; Service — `v1`; Deployment — `apps/v1`; Job — `batch/v1`;
Ingress — `networking.k8s.io/v1`.

</details>

**A4.** Как узнать `apiVersion` и `kind` для незнакомого типа объекта?

<details><summary>Ответ</summary>

`kubectl api-resources` (колонки APIVERSION и KIND), плюс `kubectl explain <kind>`.

</details>

**A5.** Чем императивный подход отличается от декларативного? Когда какой уместен?

<details><summary>Ответ</summary>

Императивный — команда, описывающая действие (`create`, `expose`, `scale`);
декларативный — файл с желаемым состоянием и `apply`. В работе используется декларативный:
он версионируется в git и воспроизводим.

</details>

**A6.** Что делает `--dry-run=client -o yaml` и зачем это нужно?

<details><summary>Ответ</summary>

Генерирует YAML локально, не обращаясь к кластеру с созданием объекта.
Позволяет получить корректный каркас и не писать манифест с нуля.

</details>

**A7.** Чем `kubectl apply` отличается от `kubectl create`?

<details><summary>Ответ</summary>

`create` создаёт объект и падает, если он уже есть. `apply` создаёт или обновляет,
сохраняя аннотацию последней применённой конфигурации, — поэтому повторное применение
безопасно и умеет удалять исчезнувшие поля.

</details>

**A8.** Что такое дрейф конфигурации и как его создают `edit`, `patch` и `scale`?

<details><summary>Ответ</summary>

Дрейф — расхождение между состоянием кластера и описанием в git. `edit`, `patch`,
`scale` меняют объект в кластере, но не файл; следующий `apply` вернёт значения из файла.

</details>

**A9.** ⭐ Что показывает `kubectl describe pod`, чего нет в `kubectl get pod -o yaml`?

<details><summary>Ответ</summary>

Читаемую сводку и главное — **события** (`Events`), а также агрегированную
информацию о томах, probe'ах, ресурсах и причинах отказов.

</details>

**A10.** Зачем нужен `kubectl logs --previous`?

<details><summary>Ответ</summary>

Чтобы получить логи предыдущего (упавшего) экземпляра контейнера, когда текущий
уже перезапущен — основной инструмент при `CrashLoopBackOff`.

</details>

**A11.** Что означает `READY 0/1` при статусе `Running`?

<details><summary>Ответ</summary>

Контейнер запущен, но не прошёл `readinessProbe` (или ещё не успел) — трафик
через Service на него не идёт.

</details>

**A12.** Что означает колонка `RESTARTS` и что в скобках рядом с числом?

<details><summary>Ответ</summary>

Сколько раз kubelet перезапускал контейнеры пода; в скобках — сколько времени
прошло с последнего рестарта.

</details>

**A13.** ⭐ Что такое label и что такое selector? Где селекторы используются?

<details><summary>Ответ</summary>

Label — пара ключ-значение в `metadata`; selector — выражение выборки по меткам.
Используются в Deployment/ReplicaSet (какими подами управлять), Service (куда слать трафик),
NetworkPolicy, affinity, topologySpreadConstraints и в самом `kubectl`.

</details>

**A14.** Чем labels отличаются от annotations?

<details><summary>Ответ</summary>

По меткам ищут и выбирают, они индексируются и ограничены по формату.
Аннотации — произвольные данные (в том числе большие) для инструментов и людей;
по ним нельзя делать выборку.

</details>

**A15.** Как удалить метку с объекта?

<details><summary>Ответ</summary>

`kubectl label pod NAME key-` (ключ с минусом на конце).

</details>

**A16.** Что такое namespace и что он изолирует? Что он **не** изолирует?

<details><summary>Ответ</summary>

Логический раздел кластера: изолирует имена объектов, задаёт область действия
RBAC и квот. **Не** изолирует сеть (для этого NetworkPolicy) и не изолирует ноды.

</details>

**A17.** Какие объекты не принадлежат namespace'у? Приведи четыре примера.

<details><summary>Ответ</summary>

Node, PersistentVolume, StorageClass, ClusterRole/ClusterRoleBinding,
Namespace, CustomResourceDefinition.

</details>

**A18.** Что произойдёт при `kubectl delete namespace myapp`?

<details><summary>Ответ</summary>

Удалятся все объекты внутри namespace. Namespace переходит в `Terminating`
и исчезает после того, как отработают все финализаторы.

</details>

**A19.** Что делает `kubectl rollout restart deployment web` и чем отличается
от `kubectl delete pod -l app=web`?

<details><summary>Ответ</summary>

`rollout restart` меняет аннотацию в шаблоне пода, из-за чего Deployment
запускает **штатное rolling-обновление**: поды заменяются постепенно с учётом
readiness и maxUnavailable. Прямое удаление подов делает это резко и без контроля.

</details>

**A20.** Как устроен `~/.kube/config`: какие три списка в нём есть и как они связаны?

<details><summary>Ответ</summary>

`clusters` (куда), `users` (кто), `contexts` (связка кластер + пользователь +
namespace); `current-context` указывает активную связку.

</details>

**A21.** Зачем `kubectl port-forward` и чем он отличается от Service?

<details><summary>Ответ</summary>

`port-forward` пробрасывает порт пода/сервиса на локальную машину через API server —
это отладочный инструмент для одного человека. Service — штатный способ доступа
внутри кластера и снаружи.

</details>

**A22.** Что делает `kubectl explain` и откуда берёт данные?

<details><summary>Ответ</summary>

Показывает описание полей объекта; данные берёт из OpenAPI-схемы конкретного
API-сервера, то есть всегда соответствует версии твоего кластера.

</details>

**A23.** Как в одном файле описать несколько объектов?

<details><summary>Ответ</summary>

Разделять объекты строкой `---`.

</details>

**A24.** Что показывает `kubectl get all` и что он на самом деле пропускает?

<details><summary>Ответ</summary>

Основные типы в текущем namespace (pods, services, deployments, replicasets,
statefulsets, daemonsets, jobs, cronjobs). Пропускает ConfigMap, Secret, Ingress, PVC,
ServiceAccount, NetworkPolicy и другие — то есть «all» здесь обманчиво.

</details>

**A25.** Чем опасен `kubectl delete pod --grace-period=0 --force`?

<details><summary>Ответ</summary>

API сразу удаляет объект пода, не дожидаясь подтверждения от kubelet.
Процесс может продолжать работать, а для StatefulSet это грозит запуском второго
экземпляра с тем же томом и identity — то есть повреждением данных.

</details>

---

### Блок B. «Что произойдёт»

**B1.**
```bash
kubectl apply -f deploy.yaml
kubectl edit deployment web       # руками поменяли replicas 3 → 10
kubectl apply -f deploy.yaml      # файл не менялся
```
Вопрос: сколько реплик останется и почему?

<details><summary>Ответ</summary>

Останется 3: `apply` вернёт значение из файла, перетерев ручное изменение
(так как `replicas` присутствует в манифесте). Это и есть дрейф.

</details>

**B2.**
```yaml
kind: Deployment
spec:
  selector:
    matchLabels: { app: web }
  template:
    metadata:
      labels: { app: frontend }
```
Вопрос: что произойдёт при `apply`?

<details><summary>Ответ</summary>

Ошибка валидации: `selector` не соответствует меткам шаблона пода
(`selector does not match template labels`). Объект не будет создан.

</details>

**B3.**
```yaml
kind: Service
spec:
  selector: { app: web, env: prod }
---
kind: Pod
metadata:
  labels: { app: web }
```
Вопрос: попадёт ли под за сервис? Как проверить одной командой?

<details><summary>Ответ</summary>

Не попадёт: селектор сервиса требует обе метки, а у пода только одна.
Проверка: `kubectl get endpoints <svc>` — список будет пуст.

</details>

**B4.**
```text:no-line-numbers
kubectl get pods
# No resources found in default namespace.
kubectl get pods -n myapp
# web-xxx  1/1  Running
```
Вопрос: как сделать, чтобы `kubectl get pods` сразу показывал myapp?

<details><summary>Ответ</summary>

`kubectl config set-context --current --namespace=myapp`.

</details>

**B5.**
```text:no-line-numbers
kubectl logs web-xxx
# Error from server (BadRequest): a container name must be specified for pod web-xxx,
# choose one of: [app sidecar]
```
Вопрос: что это значит и как получить логи?

<details><summary>Ответ</summary>

В поде несколько контейнеров, нужно указать какой: `kubectl logs web-xxx -c app`
(или `--all-containers=true`).

</details>

**B6.**
```text:no-line-numbers
kubectl get pod web-xxx
# NAME     READY  STATUS             RESTARTS
# web-xxx  0/1    CrashLoopBackOff   7 (30s ago)
kubectl logs web-xxx
# (пусто)
```
Вопрос: почему логи пустые и какой командой их получить?

<details><summary>Ответ</summary>

Текущий экземпляр контейнера только что стартовал (или ждёт backoff), логи прежнего
уже не его. Нужно `kubectl logs web-xxx --previous`.

</details>

**B7.**
```text:no-line-numbers
kubectl delete pod web-7d8f9c5b4-abcde
kubectl get pods
# web-7d8f9c5b4-zzzzz   1/1   Running   0   3s
```
Вопрос: объясни, что произошло и кто создал новый под.

<details><summary>Ответ</summary>

Под был удалён, ReplicaSet восстановил число реплик и создал новый под
с новым суффиксом имени.

</details>

**B8.**
```text:no-line-numbers
kubectl apply -f app.yaml
# deployment.apps/web configured
# service/web unchanged
```
Вопрос: что означают слова `configured` и `unchanged`?

<details><summary>Ответ</summary>

`configured` — объект существовал и был изменён; `unchanged` — существовал
и полностью совпал с желаемым состоянием, изменений не потребовалось.

</details>

**B9.**
```bash
kubectl create deployment web --image=nginx
kubectl create deployment web --image=nginx
```
Вопрос: что ответит вторая команда? А если бы обе были `apply -f`?

<details><summary>Ответ</summary>

Вторая команда `create` вернёт ошибку `AlreadyExists`. `apply` в такой ситуации
сообщил бы `unchanged` или `configured` — в этом и есть его идемпотентность.

</details>

---

### Блок C. Практика

#### C1. 🔑 Контекст и namespace
1. Посмотри текущий контекст и список контекстов.
2. Создай namespace `lab`.
3. Сделай его namespace'ом по умолчанию для текущего контекста.
4. Убедись, что `kubectl get pods` теперь работает в `lab`.
5. Верни `default` обратно.

#### C2. 🔑 Каркас манифеста без единой строки вручную
```bash
kubectl create deployment web --image=nginx:1.25 --replicas=3 --dry-run=client -o yaml > deploy.yaml
```
1. Открой файл и удали всё, что кубер добавил «для себя» (`creationTimestamp`, `status`, пустой `strategy`).
2. Добавь `metadata.labels` с `app.kubernetes.io/name`.
3. Примени и убедись, что три пода работают.

#### C3. 🔑 Два объекта в одном файле
Собери `app.yaml`: Deployment (nginx, 2 реплики) + Service (ClusterIP, порт 80),
связанные метками. Примени одной командой. Проверь:
```bash
kubectl get endpoints web        # должны быть 2 IP
```

<details><summary>Ответ</summary>

В `kubectl get endpoints web` должны быть два адреса вида `10.244.x.y:80`.
Пусто — значит, метки не совпали.

</details>

#### C4. Ломаем метки намеренно
В `app.yaml` из C3 поменяй метку в `Service.spec.selector` на `app: web2`.
1. Примени.
2. Посмотри `kubectl get endpoints web`.
3. Попробуй обратиться к сервису из временного пода.
4. Почини и опиши симптом в своей заметке «инциденты».

<details><summary>Ответ</summary>

Симптом: сервис существует, ClusterIP выдан, но Endpoints пуст и запросы
не проходят (таймаут или connection refused). Это самая частая сетевая ошибка новичка.

</details>

#### C5. describe как основной инструмент
Для любого своего пода выпиши из `kubectl describe pod`:
- образ и его pull policy;
- на какой ноде запущен;
- какие тома смонтированы;
- последние пять событий;
- какие переменные окружения пришли извне.

#### C6. Логи
1. Запусти под, который пишет в stdout: `kubectl run logger --image=busybox -- sh -c 'i=0; while true; do echo "line $i"; i=$((i+1)); sleep 1; done'`
2. Посмотри логи в потоке (`-f`), последние 10 строк (`--tail`), за последнюю минуту (`--since=1m`).
3. Удали под.

#### C7. Логи упавшего контейнера
1. Запусти под, который падает: `kubectl run crasher --image=busybox --restart=Always -- sh -c 'echo "starting"; sleep 3; exit 1'`
2. Дождись `CrashLoopBackOff`.
3. Получи логи предыдущего запуска.
4. Посмотри в `describe`, какой был Exit Code и Reason.

<details><summary>Ответ</summary>

Exit Code 1, Reason `Error`, затем `CrashLoopBackOff` с растущей задержкой
(10 с, 20 с, 40 с… до 5 минут). Логи прежнего запуска — `--previous`.

</details>

#### C8. exec и port-forward
1. Зайди в под nginx и посмотри `/etc/nginx/nginx.conf`.
2. Подмени `index.html` через `kubectl exec`.
3. Пробрось порт локально и открой в браузере.
4. Объясни, почему подмена файла исчезнет после рестарта пода.

<details><summary>Ответ</summary>

Файловая система контейнера эфемерна: при рестарте под поднимается из образа,
ручные изменения теряются. Постоянные данные — только через тома (тема 14).

</details>

#### C9. Селекторы
```bash
kubectl get pods --show-labels
kubectl label pod <pod> tier=frontend
kubectl get pods -l tier=frontend
kubectl get pods -l 'tier in (frontend,backend)'
kubectl get pods -l '!tier'
kubectl label pod <pod> tier-
```
Выполни всё и запиши результаты.

#### C10. Форматы вывода
Получи:
1. только имена подов;
2. таблицу «имя + нода + образ» через `custom-columns`;
3. IP конкретного пода через `jsonpath`;
4. список подов, отсортированный по времени запуска;
5. все поды со статусом `Running` через `--field-selector`.

#### C11. explain вместо гугла
Через `kubectl explain` найди:
1. где задаётся политика скачивания образа;
2. какие поля есть у `livenessProbe`;
3. чем `command` отличается от `args`;
4. какие значения принимает `spec.restartPolicy` у пода.

#### C12. Патч и дрейф
1. `kubectl patch deployment web -p '{"spec":{"replicas":5}}'`
2. Проверь количество подов.
3. Сделай `kubectl apply -f deploy.yaml` (там 3 реплики).
4. Запиши, что произошло, и сформулируй правило про дрейф.

<details><summary>Ответ</summary>

После `apply` реплик снова 3: файл — источник правды. Правило: ручные изменения
допустимы только временно, потом их переносят в манифест.

</details>

#### C13. rollout restart
1. Запомни имена подов и их AGE.
2. `kubectl rollout restart deployment web`
3. Наблюдай `kubectl get pods -w`.
4. Объясни, чем это лучше, чем удалить поды вручную.

<details><summary>Ответ</summary>

`rollout restart` делает постепенную замену с соблюдением `maxUnavailable`
и readiness — приложение остаётся доступным; ручное удаление подов может убрать
все реплики одновременно.

</details>

#### C14. Уборка через файл
Удали всё, созданное в C3, одной командой через файл. Проверь, что ничего не осталось
(`kubectl get all -l app=web`).

#### C15. Свой «рабочий стол» (со звёздочкой)
Настрой у себя: алиас `k`, автодополнение, переменную `do`, отображение текущего
контекста в приглашении шелла. Поставь `k9s` и посмотри кластер через него.

---

### Блок D. Инциденты

**D1.** Коллега применил манифест, `kubectl get deploy` показывает `READY 0/3`,
а `kubectl get pods` — пусто. Что случилось и куда смотреть?

<details><summary>Ответ</summary>

Поды не создаются вовсе: смотреть `kubectl describe deployment` и события
ReplicaSet — обычно ошибка в шаблоне пода, запрет admission-контроллера (квоты,
Pod Security) или неверный selector.

</details>

**D2.** Service создан, поды работают, но запросы получают `connection refused`.
Первая команда, которую ты выполнишь, и почему.

<details><summary>Ответ</summary>

`kubectl get endpoints <svc>` — пустой список мгновенно объясняет проблему
(метки/readiness). Затем `describe svc` и проверка `targetPort`.

</details>

**D3.** «Я поменял конфиг в ConfigMap и сделал apply, но приложение работает по-старому».
Объясни и предложи решение (полное — в теме 08).

<details><summary>Ответ</summary>

ConfigMap, подключённый через `env`, читается только при старте процесса;
смонтированный как том обновляется, но приложение должно уметь перечитывать файл.
Решение — `rollout restart` или аннотация с чексуммой конфига в шаблоне пода.

</details>

**D4.** После `kubectl edit` изменения через сутки исчезли. Как такое возможно?

<details><summary>Ответ</summary>

Кто-то применил манифест из git (пайплайн, ArgoCD, коллега) — и он перетёр
ручное изменение. Это нормальная работа декларативного подхода.

</details>

**D5.** Разработчик запустил команду не в том кластере и удалил Deployment на проде.
Какие организационные и технические меры предотвратили бы это?

<details><summary>Ответ</summary>

Технически: разные kubeconfig'и для dev и prod, RBAC с read-only на прод,
доступ к изменениям только через пайплайн, отображение контекста в приглашении,
подтверждения в скриптах. Организационно: изменения на проде — только через MR.

</details>

**D6.** `kubectl logs` возвращает ошибку «container name must be specified».
Что это значит и что делать?

<details><summary>Ответ</summary>

В поде несколько контейнеров. Указать контейнер через `-c` или взять
`--all-containers`.

</details>

**D7.** `kubectl exec -it web -- bash` отвечает `executable file not found`.
Причина и обход.

<details><summary>Ответ</summary>

В образе нет `bash` (часто это Alpine или distroless). Использовать `sh`,
а для distroless — `kubectl debug` с эфемерным контейнером.

</details>

**D8.** Namespace `test` висит в статусе `Terminating` уже 20 минут. Что его держит?

<details><summary>Ответ</summary>

Финализаторы у объектов внутри namespace (часто у CRD или у объектов,
чей контроллер удалён). Смотреть `kubectl get namespace test -o yaml` и
`kubectl api-resources --verbs=list --namespaced -o name | xargs -n1 kubectl get -n test`.

</details>

**D9.** `kubectl apply -f .` применил 12 файлов из 14, два упали с ошибкой валидации.
В каком состоянии кластер и как правильно поступить?

<details><summary>Ответ</summary>

Кластер в промежуточном состоянии: часть объектов применена. Правильно —
починить манифесты и применить весь каталог заново (`apply` идемпотентен), а не
доводить руками. В пайплайне такую ситуацию ловят предварительной валидацией.

</details>

**D10.** После `kubectl delete pod --force --grace-period=0` у StatefulSet появились
проблемы с томом. Почему форс опасен?

<details><summary>Ответ</summary>

Форс удаляет объект из API, не дожидаясь фактической остановки контейнера.
У StatefulSet это нарушает гарантию «не более одного пода с данной identity»,
и новый под может начать писать в тот же том параллельно со старым.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Из каких обязательных полей состоит манифест?

<details><summary>Ответ</summary>

`apiVersion`, `kind`, `metadata`, `spec` (плюс `status`, который пишет кластер).

</details>

**2.** Чем `apply` отличается от `create`? Что такое декларативный подход?

<details><summary>Ответ</summary>

`create` создаёт и падает при существующем объекте, `apply` создаёт или обновляет
и идемпотентен; декларативный подход — описываем желаемое состояние в файлах под git.

</details>

**3.** Что такое labels и selectors, зачем они?

<details><summary>Ответ</summary>

Метки — пары ключ-значение на объектах; селекторы выбирают объекты по меткам.
На них держатся связи Service→поды, ReplicaSet→поды, политики и affinity.

</details>

**4.** Как отладить под, который не запускается? Назови команды по порядку.

<details><summary>Ответ</summary>

`kubectl get pods` → `kubectl describe pod` (события) → `kubectl logs [--previous]`
→ при необходимости `kubectl exec`/`kubectl debug` и просмотр `kubectl get events`.

</details>

**5.** Что такое namespace и что он изолирует?

<details><summary>Ответ</summary>

Логическая группировка объектов: уникальность имён, область RBAC и квот;
сеть не изолирует — это делает NetworkPolicy.

</details>

**6.** Как посмотреть логи упавшего контейнера?

<details><summary>Ответ</summary>

`kubectl logs POD --previous` (при нескольких контейнерах ещё и `-c`).

</details>

**7.** Чем `kubectl edit` опасен в проде?

<details><summary>Ответ</summary>

Он меняет объект мимо git: изменение не отражено в репозитории, следующий apply
его перетрёт, а причина изменений потеряна.

</details>

**8.** Как быстро сгенерировать манифест, не помня синтаксис наизусть?

<details><summary>Ответ</summary>

`kubectl create ... --dry-run=client -o yaml` и `kubectl explain` для полей.

</details>

---

### 🎯 Чек-лист

- [ ] Проверяю контекст перед каждой опасной командой
- [ ] Генерирую манифесты через `--dry-run=client -o yaml`
- [ ] Свободно читаю вывод `kubectl get pods` и понимаю каждую колонку
- [ ] `describe` и `logs --previous` — рефлекс при любой проблеме
- [ ] Понимаю связь меток и селекторов, проверяю через `get endpoints`
- [ ] Умею фильтровать по меткам и полям, выводить `custom-columns` и `jsonpath`
- [ ] Настроил алиас `k`, автодополнение и переменную `do`
- [ ] Знаю, чем `rollout restart` лучше удаления подов руками
- [ ] Понимаю, что такое дрейф и почему `edit` в проде — временная мера
