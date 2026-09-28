---
title: "02. Архитектура кластера"
description: "Control plane, worker node, путь kubectl apply до работающего контейнера — вопрос №2 на собеседованиях"
---

# 02. ⭐ Архитектура кластера

> Роадмап → 6. Kubernetes → 1. Теория → **Архитектура**:
> «Здесь надо понимать, как кубер работает, из чего состоит:
> **Control Plane** — API Server, etcd, Scheduler, Controller manager, Cloud Controller manager;
> **Worker node** — kubelet, container runtime, kube-proxy».
> Это **вопрос №2 в списке популярных на собесе** — «Расскажи про архитектуру Kubernetes».
> **После темы ты умеешь:** нарисовать схему кластера по памяти и проследить путь
> от `kubectl apply` до запущенного контейнера.

---

## 🗺️ Карта темы

```text:no-line-numbers
                              ┌──────────────────────── CONTROL PLANE ────────────────────────┐
                              │                                                               │
   kubectl / CI / оператор ──►│  ┌─────────────┐    ┌──────┐                                  │
                              │  │ kube-api    │◄──►│ etcd │  единственный, кто ходит в etcd  │
                              │  │ server      │    └──────┘                                  │
                              │  └──┬───┬───┬──┘                                              │
                              │     │   │   │                                                 │
                              │     │   │   └──────────────┐                                  │
                              │     │   └──────┐           │                                  │
                              │     ▼          ▼           ▼                                  │
                              │ ┌────────┐ ┌──────────┐ ┌────────────────┐                    │
                              │ │scheduler│ │controller│ │cloud-controller│                   │
                              │ │        │ │ manager  │ │    manager     │                    │
                              │ └────────┘ └──────────┘ └────────────────┘                    │
                              └───────────────────────┬───────────────────────────────────────┘
                                                      │ (все общаются ТОЛЬКО через API server)
                     ┌────────────────────────────────┼────────────────────────────────┐
                     ▼                                ▼                                ▼
        ┌──────── WORKER NODE 1 ────────┐  ┌──────── WORKER NODE 2 ────────┐   ...
        │ kubelet ──► container runtime │  │ kubelet ──► container runtime │
        │    │           (containerd)   │  │    │                          │
        │    │        ┌─────┐ ┌─────┐   │  │    │        ┌─────┐           │
        │    └───────►│ POD │ │ POD │   │  │    └───────►│ POD │           │
        │             └─────┘ └─────┘   │  │             └─────┘           │
        │ kube-proxy  (правила сети)    │  │ kube-proxy                    │
        └───────────────────────────────┘  └───────────────────────────────┘
```

**Золотое правило архитектуры:** *все компоненты общаются только через API server.*
Ни scheduler, ни kubelet, ни controller manager не ходят в etcd и не ходят друг к другу.

---

## 1. Control Plane — «мозг» кластера

### 1.1 kube-apiserver ⭐

**Что это:** REST API кластера и единственная точка входа. Всё — `kubectl`, kubelet,
контроллеры, дашборды, CI — работает через него.

**Что делает с каждым запросом:**

```text:no-line-numbers
запрос ──► [Аутентификация] ──► [Авторизация RBAC] ──► [Admission] ──► [Валидация] ──► etcd
            кто ты?             можно ли тебе?        мутация/проверка   схема ок?    запись
            сертификат,         тема 17               LimitRange,
            токен SA, OIDC                            Pod Security,
                                                      webhooks
```

| Свойство | Значение |
|----------|----------|
| Протокол | HTTPS, порт **6443** |
| Состояние | **stateless** — поэтому легко масштабируется в несколько реплик за LB |
| Хранение | сам ничего не хранит, только etcd |
| Особенность | поддерживает `watch` — клиенты подписываются на изменения объектов |

> 🎤 На собесе: «API server — единственный компонент, который пишет в etcd; всё остальное
> ходит через него и подписывается на изменения через watch».

### 1.2 etcd ⭐

**Что это:** распределённое key-value хранилище на алгоритме Raft. Содержит **всё состояние
кластера**: объекты, их spec и status, секреты, ServiceAccount'ы.

| Свойство | Значение |
|----------|----------|
| Порт | 2379 (клиенты), 2380 (между членами кластера) |
| Кворум | нужно **большинство**: 3 узла переживают потерю 1, 5 узлов — потерю 2 |
| Почему нечётное число | чётное не даёт выигрыша в отказоустойчивости, но повышает риск split-brain |
| Чувствительность | к задержкам диска и сети — etcd любит быстрые SSD |
| Бэкап | `etcdctl snapshot save` — **единственный настоящий бэкап кластера** (тема 21) |

```bash
# посмотреть здоровье (на control-plane ноде)
ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint health
```

> ⚠️ Потерял etcd без бэкапа — потерял кластер: манифесты можно применить заново
> (если они в git), но не восстановить сам кластер как объект.

### 1.3 kube-scheduler ⭐

**Что делает:** находит поды с пустым полем `spec.nodeName` и решает, на какую ноду их
поставить. Сам он **не запускает** контейнеры — он только записывает решение (binding) в API.

**Два этапа:**

```text:no-line-numbers
Все ноды
   │
   ▼ FILTERING (предикаты) — «где вообще можно?»
   │   • хватает ли CPU/памяти по requests
   │   • nodeSelector / nodeAffinity
   │   • taints и tolerations
   │   • свободные порты, доступность томов (PV в нужной зоне)
   │
   ▼ SCORING (приоритеты) — «где лучше?»
   │   • меньше загружена
   │   • образ уже есть на ноде
   │   • pod anti-affinity / topology spread
   │
   ▼ BINDING — записывает pod.spec.nodeName = nodeX
```

Если ни одна нода не прошла фильтрацию — под остаётся `Pending`, а в событиях будет
`0/3 nodes are available: Insufficient cpu...` (самый частый инцидент, тема 20).

### 1.4 kube-controller-manager ⭐

**Что это:** один процесс, внутри которого крутятся десятки контроллеров — те самые циклы
сверки. Основные:

| Контроллер | За что отвечает |
|------------|-----------------|
| Deployment | управляет ReplicaSet'ами при обновлении |
| ReplicaSet | держит нужное число подов |
| Node | следит за heartbeat'ами нод, помечает `NotReady`, вытесняет поды |
| Job / CronJob | выполнение задач и расписание |
| EndpointSlice | поддерживает списки адресов за Service |
| ServiceAccount / Token | создаёт SA и токены |
| PersistentVolume | привязывает PVC к PV |
| Namespace | удаляет содержимое удаляемого namespace |

Работает в режиме **leader election**: при нескольких репликах активна одна.

### 1.5 cloud-controller-manager

**Что это:** часть, знающая про конкретное облако. Вынесена отдельно, чтобы ядро кубера
не зависело от провайдеров.

| Контроллер внутри | Что делает |
|-------------------|------------|
| Node | сверяет, существует ли ещё ВМ в облаке; удаляет объект Node, если ВМ снесли |
| Route | настраивает маршруты в сети облака |
| Service | создаёт **реальный облачный балансировщик** для `type: LoadBalancer` |

> На bare-metal и в kind его нет — поэтому `type: LoadBalancer` там висит в `<pending>`,
> пока не поставишь MetalLB или аналог. Это классический вопрос «почему у меня EXTERNAL-IP
> в pending».

---

## 2. Worker node — где реально живут контейнеры

### 2.1 kubelet ⭐

**Главный агент ноды.** Не является контейнером, работает как systemd-сервис на хосте.

| Что делает | Подробнее |
|------------|-----------|
| Получает список подов для своей ноды | через API server (watch по `nodeName`) |
| Запускает и останавливает контейнеры | через CRI → container runtime |
| Монтирует тома | тома, ConfigMap, Secret, projected-токены |
| Выполняет probe'ы | liveness / readiness / startup (тема 09) |
| Шлёт статус | состояние пода и ноды, heartbeat через Lease |
| Следит за ресурсами ноды | при нехватке — **eviction** подов (вытеснение) |
| Запускает статические поды | из `/etc/kubernetes/manifests` — так поднимается сам control plane |

```bash
systemctl status kubelet
journalctl -u kubelet -f          # первое место, куда смотрят, если нода "странная"
ls /etc/kubernetes/manifests/     # static pods: apiserver, etcd, scheduler, controller-manager
```

> ⚠️ kubelet — единственный компонент, который **обязан** работать на ноде, чтобы поды
> на ней жили. Умер kubelet → нода `NotReady` → через ~5 минут поды переедут.
> При этом уже запущенные контейнеры продолжают работать — их запускал runtime, не kubelet.

### 2.2 Container runtime ⭐

**Что это:** то, что реально запускает контейнеры. kubelet общается с ним по стандарту
**CRI** (Container Runtime Interface).

| Runtime | Комментарий |
|---------|-------------|
| **containerd** | де-факто стандарт сегодня |
| **CRI-O** | минималистичный, заточен под кубер |
| Docker | **не поддерживается напрямую с 1.24** — dockershim удалён из kubelet |

> 🎤 Частый вопрос: «Kubernetes отказался от Docker — что это значит?»
> Ответ: удалён dockershim — прослойка, позволявшая kubelet общаться с Docker Engine.
> Образы, собранные Docker'ом, работают как работали: это OCI-образы, их запускает containerd.
> Менять Dockerfile не нужно.

```bash
# на ноде (в kind: docker exec -it devops-worker bash)
crictl ps                  # контейнеры глазами CRI
crictl images
crictl logs <container-id>
```

### 2.3 kube-proxy ⭐

**Что делает:** реализует абстракцию Service на уровне сети ноды. Следит за Service
и EndpointSlice и настраивает правила, перенаправляющие трафик с ClusterIP на конкретные поды.

| Режим | Как работает |
|-------|--------------|
| **iptables** | режим по умолчанию; цепочки NAT, выбор бэкенда случайный по вероятностям |
| **IPVS** | ядерный балансировщик, лучше на тысячах сервисов, есть алгоритмы (rr, lc) |
| **nftables** | более новая реализация, замена iptables-режиму |
| **eBPF** (Cilium) | kube-proxy может быть **полностью заменён** CNI-плагином |

> ⚠️ Важное для собеса: kube-proxy **не пропускает через себя трафик**. Он только
> программирует ядро. Данные идут напрямую через netfilter/IPVS. Подробности — тема 10.

### 2.4 Что ещё есть на ноде

- **CNI-плагин** (Calico/Cilium/Flannel) — даёт подам IP и связность (тема 10).
- **CoreDNS** — технически обычный Deployment в `kube-system`, но по смыслу часть
  инфраструктуры: резолвит имена сервисов.
- **CSI-драйверы** — подключение томов (тема 14).

---

## 3. ⭐ Путь `kubectl apply` → работающий контейнер

Это **лучший способ ответить на вопрос об архитектуре**: не перечислять компоненты,
а провести их через сценарий.

```text:no-line-numbers
1. kubectl apply -f deploy.yaml
        │  HTTPS :6443
        ▼
2. API server: аутентификация → RBAC → admission → валидация
        │
        ▼
3. Объект Deployment записан в etcd.  kubectl получил "created" — НА ЭТОМ ЕГО РОЛЬ ВСЁ
        │
        ▼
4. Deployment-контроллер (watch) видит новый объект → создаёт ReplicaSet
        │
        ▼
5. ReplicaSet-контроллер видит "надо 3, есть 0" → создаёт 3 объекта Pod
        │                                          (pod.spec.nodeName ПУСТОЙ)
        ▼
6. Scheduler видит поды без ноды → фильтрация + скоринг → записывает nodeName
        │
        ▼
7. kubelet НУЖНОЙ ноды видит "появился под для меня"
        │
        ├──► CNI: выдать IP, подключить сетевой namespace
        ├──► тома: смонтировать PVC/ConfigMap/Secret
        └──► CRI: containerd → pull образа → запуск контейнеров
        │
        ▼
8. kubelet шлёт status: ContainerCreating → Running; probe'ы → Ready
        │
        ▼
9. EndpointSlice-контроллер добавляет IP пода за Service
        │
        ▼
10. kube-proxy на КАЖДОЙ ноде обновляет правила → трафик пошёл
```

Проверить это вживую:
```bash
kubectl get events --sort-by=.lastTimestamp -w
# Scheduled → Pulling → Pulled → Created → Started
```

---

## 4. Отказы компонентов: что сломается

Любимый вопрос на собесе: «что будет, если умрёт X?»

| Умер компонент | Что перестаёт работать | Что продолжает работать |
|----------------|------------------------|-------------------------|
| **API server** | kubectl, любые изменения, watch'и, новые поды | Уже запущенные контейнеры работают; трафик идёт |
| **etcd** (потеря кворума) | API становится read-only/падает | Запущенные поды работают |
| **scheduler** | Новые поды висят `Pending` | Существующие поды не трогаются |
| **controller-manager** | Не создаются реплики, не обновляются endpoints, нода-контроллер не вытесняет | Существующее живёт |
| **cloud-controller** | Не создаются LB, не чистятся удалённые ноды | Всё остальное |
| **kubelet** на ноде | Нода `NotReady`, поды на ней не управляются, через ~5 мин пересоздаются на других | Контейнеры на ноде продолжают работать (runtime жив) |
| **kube-proxy** на ноде | Ломается доступ к Service **с этой ноды** | Прямые обращения по IP пода работают |
| **CoreDNS** | Не резолвятся имена сервисов — «всё лежит» | Обращение по IP работает |
| **CNI** | Новые поды не получают сеть, остаются `ContainerCreating` | Старые поды работают |

> 🧠 Вывод, который стоит озвучить: **control plane отвечает за управление, а не за трафик**.
> Кластер без control plane продолжает обслуживать запросы, но перестаёт реагировать
> на изменения и падения.

---

## 5. HA control plane

```text:no-line-numbers
                 ┌──── LB (VIP / HAProxy / облачный) :6443 ────┐
                 │                 │                │
           ┌─────▼─────┐     ┌─────▼─────┐    ┌─────▼─────┐
           │ master-1  │     │ master-2  │    │ master-3  │
           │ api, sched│     │ api, sched│    │ api, sched│
           │ ctrl-mgr  │     │ ctrl-mgr  │    │ ctrl-mgr  │
           │ etcd      │     │ etcd      │    │ etcd      │  ← stacked etcd
           └───────────┘     └───────────┘    └───────────┘
                   кворум etcd: 2 из 3
```

- **API server** — активен на всех репликах (stateless, за балансировщиком).
- **scheduler** и **controller-manager** — работают в режиме **leader election**:
  активен один, остальные ждут.
- **etcd**: два варианта — *stacked* (на тех же нодах, проще) и *external*
  (отдельный кластер etcd, надёжнее и рекомендуется для крупных инсталляций).
- Минимум для HA — **3 control-plane ноды**: кворум 2 из 3 переживает потерю одной.

---

## 6. Порты и файлы, которые полезно знать

| Порт | Компонент |
|------|-----------|
| 6443 | kube-apiserver |
| 2379 / 2380 | etcd клиенты / между членами |
| 10250 | kubelet API (`logs`, `exec` идут сюда) |
| 10256 | kube-proxy healthz |
| 30000-32767 | диапазон NodePort |

| Путь | Что там |
|------|---------|
| `/etc/kubernetes/manifests/` | статические поды control plane |
| `/etc/kubernetes/pki/` | сертификаты кластера (срок жизни — 1 год!) |
| `/var/lib/kubelet/` | состояние kubelet, смонтированные тома |
| `/var/lib/etcd/` | данные etcd |
| `/etc/cni/net.d/` | конфиг CNI |
| `~/.kube/config` | доступ клиента к кластеру |

```bash
kubeadm certs check-expiration      # частая причина «внезапно всё сломалось через год»
```

---

## 7. Смотрим архитектуру в своём кластере

```bash
kubectl get pods -n kube-system -o wide
kubectl -n kube-system get pod -l component=kube-apiserver -o yaml | head -40
kubectl get componentstatuses          # устарело, но иногда встречается
kubectl get --raw='/readyz?verbose'    # здоровье API server: список проверок
kubectl get nodes -o json | jq '.items[].status.nodeInfo'   # runtime, версия kubelet, ядро
kubectl get leases -n kube-system      # видно leader election и heartbeat'ы нод
```

---

## 💼 Как это в DevOps

- Вопрос «расскажи архитектуру» — фильтр на первом же собеседовании. Рассказывать надо
  **через путь пода**, а не списком: это сразу показывает понимание, а не зубрёжку.
- В managed-кластере (EKS/GKE/Yandex/VK) control plane тебе не виден, но в инцидентах
  всё равно рассуждаешь этими терминами: «под Pending — значит, scheduler не нашёл ноду».
- `journalctl -u kubelet` и `crictl ps` — то, чем реально чинят «ноду, которая странная».
- Просроченные сертификаты `/etc/kubernetes/pki` — реальный годовой инцидент на
  самосборных кластерах. Ставь напоминание.
- Бэкап etcd — главный пункт DR-плана. Проверять надо не наличие снапшота, а **восстановление**.

---

## 📌 Шпаргалка

| Компонент | Где | Одной строкой |
|-----------|-----|---------------|
| kube-apiserver | CP | Точка входа, единственный клиент etcd |
| etcd | CP | Всё состояние кластера, Raft, кворум |
| kube-scheduler | CP | Выбирает ноду: фильтрация → скоринг → binding |
| controller-manager | CP | Циклы сверки желаемого и фактического |
| cloud-controller-manager | CP | Интеграция с облаком: LB, ноды, маршруты |
| kubelet | Node | Агент ноды: запускает поды, probe'ы, статус |
| container runtime | Node | containerd/CRI-O — реально запускает контейнеры |
| kube-proxy | Node | Правила сети для Service (iptables/IPVS) |
| CNI | Node | IP и связность подов |
| CoreDNS | Add-on | DNS-имена сервисов |

---

## 🧠 Что запомнить

1. Control plane: **API server, etcd, scheduler, controller manager, cloud-controller-manager**.
2. Worker node: **kubelet, container runtime, kube-proxy** (+ CNI).
3. Все компоненты общаются **только через API server**; в etcd пишет только он.
4. Scheduler выбирает ноду (фильтрация → скоринг) и **не запускает** контейнеры.
5. Controller manager — набор reconciliation-циклов; при HA работает leader election.
6. kubelet — единственный агент, обязательный на ноде; читает и статические поды.
7. Docker не нужен: kubelet общается с runtime по **CRI**, стандарт — containerd.
8. kube-proxy не пропускает трафик через себя — он программирует iptables/IPVS.
9. Падение control plane не останавливает уже работающие поды и трафик.
10. etcd требует нечётного числа узлов и кворума; его снапшот — единственный бэкап кластера.
11. `type: LoadBalancer` без cloud-controller (bare-metal, kind) остаётся `<pending>`.
12. Отвечая про архитектуру, **веди рассказ по пути `kubectl apply` → контейнер**.

---

## Задачи

> ⭐ Здесь живёт вопрос собеса №2 — *«Расскажи про архитектуру Kubernetes»*.
> Главное задание блока: **нарисовать схему по памяти** и **рассказать путь пода вслух**.

---

### Блок A. Теория

**A1.** ⭐ Перечисли компоненты Control Plane и назначение каждого одной строкой.

<details><summary>Ответ</summary>

**kube-apiserver** — REST API и единственная точка входа, пишет в etcd;
**etcd** — хранилище всего состояния кластера; **kube-scheduler** — выбирает ноду
для подов; **kube-controller-manager** — набор циклов сверки желаемого и фактического;
**cloud-controller-manager** — интеграция с облаком (LB, ноды, маршруты).

</details>

**A2.** ⭐ Перечисли компоненты Worker node и назначение каждого одной строкой.

<details><summary>Ответ</summary>

**kubelet** — агент ноды, запускает поды и шлёт статус; **container runtime**
(containerd/CRI-O) — реально запускает контейнеры; **kube-proxy** — программирует
правила сети для Service. Плюс **CNI-плагин** для сети подов.

</details>

**A3.** Какой компонент — единственный, кто пишет в etcd?

<details><summary>Ответ</summary>

kube-apiserver.

</details>

**A4.** Через какие этапы проходит запрос в API server, прежде чем объект попадёт в etcd?

<details><summary>Ответ</summary>

Аутентификация → авторизация (RBAC) → admission-контроллеры (мутирующие,
затем валидирующие) → валидация схемы → запись в etcd.

</details>

**A5.** Почему API server легко масштабируется в несколько реплик, а etcd — нет?

<details><summary>Ответ</summary>

API server stateless: любой запрос можно обслужить любой репликой.
etcd хранит состояние и требует консенсуса Raft — добавление узлов увеличивает
стоимость согласования, а не производительность записи.

</details>

**A6.** Почему нод etcd должно быть нечётное число? Сколько выдержит кластер из 5?

<details><summary>Ответ</summary>

Кворум — большинство; 4 узла переживают отказ одного так же, как 3,
но вероятность отказа выше. Кластер из 5 выдерживает потерю 2 узлов.

</details>

**A7.** ⭐ Что делает scheduler и что он **не** делает?

<details><summary>Ответ</summary>

Выбирает ноду для подов с пустым `nodeName` и записывает решение в API.
Не запускает контейнеры, не качает образы, не следит за работой подов.

</details>

**A8.** Опиши два этапа работы scheduler'а и приведи по три примера критериев на каждом.

<details><summary>Ответ</summary>

**Filtering**: хватает ли ресурсов по `requests`, nodeSelector/affinity,
taints/tolerations, доступность томов, свободные hostPort'ы.
**Scoring**: наименьшая загрузка, наличие образа на ноде, anti-affinity/topology spread,
приоритет распределения.

</details>

**A9.** Что записывает scheduler в объект пода, приняв решение?

<details><summary>Ответ</summary>

`spec.nodeName` (через объект binding).

</details>

**A10.** Что такое controller-manager? Назови шесть контроллеров внутри него.

<details><summary>Ответ</summary>

Deployment, ReplicaSet, Node, Job/CronJob, EndpointSlice, ServiceAccount/Token,
PersistentVolume, Namespace.

</details>

**A11.** Что такое leader election и какие компоненты его используют?

<details><summary>Ответ</summary>

Механизм выбора активного экземпляра через объект Lease: scheduler
и controller-manager при нескольких репликах работают «активный + резервные».

</details>

**A12.** Зачем вынесли cloud-controller-manager отдельно?

<details><summary>Ответ</summary>

Чтобы ядро Kubernetes не зависело от кода конкретных облаков: провайдеры
развивают свои контроллеры отдельно, а кубер остаётся провайдер-независимым.

</details>

**A13.** Почему в kind/bare-metal `type: LoadBalancer` остаётся в `<pending>`?

<details><summary>Ответ</summary>

Некому создать внешний балансировщик: cloud-controller-manager отсутствует.
Нужен MetalLB, kube-vip или обращение через NodePort/Ingress.

</details>

**A14.** ⭐ Что делает kubelet? Назови шесть его обязанностей.

<details><summary>Ответ</summary>

Получает список подов для своей ноды; запускает/останавливает контейнеры через CRI;
монтирует тома, ConfigMap и Secret; выполняет probe'ы; отправляет статус пода и ноды;
вытесняет поды при нехватке ресурсов; запускает статические поды.

</details>

**A15.** Что такое статические поды и где лежат их манифесты?

<details><summary>Ответ</summary>

Поды, которыми управляет kubelet напрямую из каталога `/etc/kubernetes/manifests/`,
без участия API server. Так поднимаются apiserver, etcd, scheduler, controller-manager.

</details>

**A16.** Что такое CRI и почему «кубер отказался от Docker»?

<details><summary>Ответ</summary>

CRI — стандартный gRPC-интерфейс между kubelet и runtime. Из kubelet удалили
dockershim — прослойку для Docker Engine; поддерживаются runtime с CRI (containerd, CRI-O).

</details>

**A17.** Нужно ли переписывать Dockerfile после перехода на containerd? Почему?

<details><summary>Ответ</summary>

Нет. Образы формата OCI, containerd запускает их без изменений.
Docker по-прежнему можно использовать для сборки.

</details>

**A18.** ⭐ Что делает kube-proxy? Проходит ли трафик через его процесс?

<details><summary>Ответ</summary>

Следит за Service/EndpointSlice и настраивает правила ядра (iptables/IPVS/nftables),
которые перенаправляют трафик с ClusterIP на поды. Трафик через процесс kube-proxy
**не проходит** — работает ядро.

</details>

**A19.** Какие режимы работы kube-proxy бывают и чем IPVS лучше iptables?

<details><summary>Ответ</summary>

iptables (по умолчанию), IPVS, nftables, а также полная замена на eBPF (Cilium).
IPVS лучше масштабируется: хеш-таблицы вместо длинных цепочек правил, есть алгоритмы
балансировки (rr, lc, sh).

</details>

**A20.** Что произойдёт, если на ноде умрёт kubelet? А если умрёт container runtime?

<details><summary>Ответ</summary>

Умер kubelet: нода `NotReady`, поды на ней неуправляемы, примерно через 5 минут
пересоздаются на других нодах; уже запущенные контейнеры продолжают работать.
Умер runtime: контейнеры останавливаются, нода тоже уходит в `NotReady`.

</details>

**A21.** Что перестанет работать при падении API server, а что продолжит?

<details><summary>Ответ</summary>

Перестают работать kubectl, изменения, создание/пересоздание подов, watch'и.
Продолжают: работающие контейнеры, сетевой трафик через Service (правила уже
настроены), DNS внутри кластера.

</details>

**A22.** Какой порт у API server, у kubelet, у etcd? Какой диапазон у NodePort?

<details><summary>Ответ</summary>

API server — 6443; kubelet — 10250; etcd — 2379/2380; NodePort — 30000-32767.

</details>

**A23.** Что лежит в `/etc/kubernetes/pki` и почему это причина «внезапной» годовой аварии?

<details><summary>Ответ</summary>

Сертификаты кластера (CA, apiserver, kubelet-client и др.). По умолчанию
срок жизни — год; истекают тихо, и в этот момент перестаёт работать управление кластером.
Лечение: `kubeadm certs renew all` и перезапуск control plane; в норме — обновление
кластера раз в несколько месяцев, оно продлевает сертификаты автоматически.

</details>

**A24.** Чем stacked etcd отличается от external etcd?

<details><summary>Ответ</summary>

Stacked: etcd работает на тех же нодах, что и control plane (проще, меньше машин).
External: отдельный кластер etcd (надёжнее, изолирует нагрузку, сложнее в эксплуатации).

</details>

**A25.** Сколько control-plane нод минимально нужно для HA и почему?

<details><summary>Ответ</summary>

Три: кворум etcd 2 из 3 переживает потерю одной ноды. Две ноды HA не дают —
потеря одной убивает кворум.

</details>

---

### Блок B. «Что произойдёт»

**B1.**
```bash
kubectl apply -f deployment.yaml
# Ответ: deployment.apps/web created
```
Вопрос: что к этому моменту уже произошло в кластере, а что ещё нет?

<details><summary>Ответ</summary>

Объект Deployment прошёл аутентификацию/авторизацию/admission и записан в etcd.
Подов ещё может не быть: ReplicaSet и поды создадут контроллеры асинхронно,
ноду выберет scheduler, контейнеры запустит kubelet.

</details>

**B2.**
```text:no-line-numbers
kubectl get pods
# NAME        READY   STATUS    AGE
# web-xxx     0/1     Pending   3m
kubectl describe pod web-xxx | tail -5
# Warning  FailedScheduling  0/3 nodes are available: 3 Insufficient cpu.
```
Вопрос: какой компонент сообщает об этом и на каком этапе застрял под?

<details><summary>Ответ</summary>

Сообщение от scheduler'а (`FailedScheduling`). Под застрял на этапе выбора ноды:
ни одна нода не проходит фильтрацию по `requests.cpu`.

</details>

**B3.**
```text:no-line-numbers
# scheduler остановлен (kubectl -n kube-system delete pod kube-scheduler-...)
kubectl create deployment test --image=nginx
kubectl get pods
```
Вопрос: что покажет статус? Что станет с уже работающими подами?

<details><summary>Ответ</summary>

Новые поды останутся `Pending` (некому назначить ноду). Уже работающие поды
не пострадают — ими занимается kubelet.

</details>

**B4.**
```text:no-line-numbers
# на worker-ноде: systemctl stop kubelet
kubectl get nodes
kubectl get pods -o wide
```
Вопрос: что произойдёт через 10 секунд, через 1 минуту, через 6 минут?
Продолжат ли работать контейнеры на этой ноде?

<details><summary>Ответ</summary>

Через ~10 секунд ничего заметного; примерно через 40 секунд нода станет `NotReady`;
примерно через 5 минут после этого поды будут вытеснены и пересозданы на других нодах.
Контейнеры на ноде продолжают работать — их держит runtime.

</details>

**B5.**
```text:no-line-numbers
# на worker-ноде: systemctl stop kube-proxy  (или удалить его под)
curl http://<ClusterIP сервиса>     # изнутри пода на ЭТОЙ ноде
curl http://<IP пода напрямую>
```
Вопрос: какой из запросов сработает и почему?

<details><summary>Ответ</summary>

Запрос по ClusterIP не сработает (правила не обновляются; если правила уже были,
они какое-то время продолжат работать, но новые Endpoints не появятся). Прямое обращение
по IP пода работает — это чистая работа CNI.

</details>

**B6.**
```text:no-line-numbers
kubectl -n kube-system delete pod -l k8s-app=kube-dns
kubectl exec -it app -- curl http://backend
kubectl exec -it app -- curl http://10.96.0.42
```
Вопрос: какой запрос упадёт и с какой ошибкой?

<details><summary>Ответ</summary>

Упадёт запрос по имени: `Could not resolve host` / `Name does not resolve`.
Обращение по ClusterIP работает — DNS и балансировка это разные механизмы.

</details>

**B7.**
```bash
kubectl get --raw='/readyz?verbose'
```
Вопрос: к какому компоненту идёт запрос и что означает вывод?

<details><summary>Ответ</summary>

К kube-apiserver: показывает список внутренних проверок готовности
(etcd, информеры, admission) и их статус. Удобно, когда «API живой, но странный».

</details>

**B8.**
```bash
kubectl get leases -n kube-system
```
Вопрос: что здесь видно и зачем эти объекты нужны?

<details><summary>Ответ</summary>

Объекты Lease: heartbeat'ы нод (`kube-node-lease`) и записи leader election
для scheduler/controller-manager. Видно, кто сейчас лидер и когда нода отмечалась.

</details>

---

### Блок C. Практика

#### C1. 🔑 Схема по памяти
Возьми лист бумаги. Нарисуй кластер: control plane, две ноды, все компоненты и стрелки
«кто с кем общается». Потом сверься с конспектом и отметь красным, что забыл.
Повтори через день. Это буквально репетиция собеседования.

#### C2. 🔑 Путь пода вслух
Запусти запись на телефоне и расскажи за 2 минуты путь от `kubectl apply` до работающего
контейнера, называя компоненты. Прослушай. Перескажи ещё раз без «э-э-э».

#### C3. Найти компоненты в своём кластере
```bash
kubectl get pods -n kube-system -o wide
```
Выпиши таблицу: под → компонент → на какой ноде → сколько реплик.
Отдельно отметь, какие компоненты есть **на каждой** ноде и почему.

#### C4. Статические поды
```bash
docker exec -it devops-control-plane bash     # для kind
ls -la /etc/kubernetes/manifests/
cat /etc/kubernetes/manifests/kube-apiserver.yaml | head -40
```
1. Найди в манифесте флаг `--etcd-servers`.
2. Найди, где заданы сертификаты.
3. Объясни: кто запускает эти поды, если API server ещё не работает?

<details><summary>Ответ</summary>

Статические поды запускает kubelet, читая каталог напрямую, — поэтому control plane
может подняться до того, как появится API server (иначе была бы курица и яйцо).

</details>

#### C5. Наблюдаем путь пода по событиям
```bash
kubectl get events -A --sort-by=.lastTimestamp -w      # в одном окне
kubectl create deployment ev --image=nginx             # в другом
```
Выпиши цепочку событий по порядку и подпиши напротив каждого, какой компонент его создал.

<details><summary>Ответ</summary>

Типичная цепочка: `Scheduled` (scheduler) → `Pulling`/`Pulled` (kubelet) →
`Created` → `Started` (kubelet через CRI). Если есть том — ещё `SuccessfulAttachVolume`.

</details>

#### C6. Отключаем scheduler
```bash
docker exec devops-control-plane mv /etc/kubernetes/manifests/kube-scheduler.yaml /tmp/
kubectl create deployment noched --image=nginx
kubectl get pods                 # наблюдай
kubectl describe pod noched-...  # что в событиях?
docker exec devops-control-plane mv /tmp/kube-scheduler.yaml /etc/kubernetes/manifests/
kubectl get pods                 # через 30 секунд
```
Запиши, что видел. Это один из самых наглядных экспериментов блока.

<details><summary>Ответ</summary>

Под висит `Pending` без события `Scheduled`; после возврата манифеста scheduler
поднимается и под назначается на ноду в течение нескольких секунд.

</details>

#### C7. Ручной binding (со звёздочкой)
Создай под с явным `spec.nodeName: devops-worker` (без scheduler'а).
Убедись, что он запустился даже при выключенном scheduler'е. Объясни почему.

<details><summary>Ответ</summary>

Под запустится: kubelet ноды видит под с её `nodeName` и берёт его в работу.
Scheduler нужен только для тех подов, у кого `nodeName` пуст.

</details>

#### C8. Останавливаем kubelet
```bash
docker exec devops-worker systemctl stop kubelet
watch kubectl get nodes          # засеки время до NotReady
watch kubectl get pods -o wide   # засеки время до пересоздания
docker exec devops-worker systemctl start kubelet
```
Запиши оба тайминга и найди в документации, какие параметры их задают.

<details><summary>Ответ</summary>

Ориентиры: `NotReady` примерно через 40 секунд (`node-monitor-grace-period`),
вытеснение подов — примерно через 300 секунд (`tolerationSeconds` у taint'ов
`node.kubernetes.io/not-ready` и `unreachable`).

</details>

#### C9. Смотрим контейнеры глазами CRI
```bash
docker exec -it devops-worker bash
crictl ps
crictl pods
crictl images
crictl inspect <id> | head -40
```
Сравни вывод `crictl ps` с `kubectl get pods -o wide` по этой ноде.

#### C10. Логи kubelet
```bash
docker exec devops-worker journalctl -u kubelet --no-pager | tail -50
```
Найди строки про запуск пода, про probe и про монтирование томов.

#### C11. Сертификаты
```bash
docker exec devops-control-plane kubeadm certs check-expiration
```
Запиши дату истечения. Сформулируй, что произойдёт в этот день, если ничего не делать.

#### C12. Кто сколько нагружает control plane (со звёздочкой)
```bash
kubectl top pods -n kube-system
kubectl get --raw /metrics | grep apiserver_request_total | head
```
Объясни, почему `watch`-подписки дешевле, чем опрос в цикле.

---

### Блок D. Инциденты

**D1.** `kubectl get pods` висит и отваливается по таймауту. С чего начинаешь?
Назови три гипотезы в порядке проверки.

<details><summary>Ответ</summary>

(1) Доступность API server: `kubectl cluster-info`, порт 6443, статус статических
подов на control plane. (2) Здоровье etcd (кворум, диск). (3) Проблема клиента: неверный
контекст в kubeconfig, истёкший сертификат, сеть/VPN.

</details>

**D2.** Все поды работают, приложение обслуживает трафик, но `kubectl apply` не проходит.
Что сломано и насколько это критично прямо сейчас?

<details><summary>Ответ</summary>

Сломан control plane (API server или etcd). Прямо сейчас трафик обслуживается,
но кластер «заморожен»: нет деплоев, нет реакции на падения подов и нод. Чинить срочно,
но без паники «всё лежит».

</details>

**D3.** Новые поды висят `Pending` уже 20 минут, старые работают. Куда смотришь?

<details><summary>Ответ</summary>

Событие `FailedScheduling` у пода: не хватает ресурсов, не подходят
affinity/nodeSelector, есть taint'ы без tolerations, недоступен PVC. Плюс проверить,
жив ли сам scheduler.

</details>

**D4.** Один под застрял в `ContainerCreating` 10 минут. Три наиболее вероятные причины.

<details><summary>Ответ</summary>

Не выдаётся сеть (проблема CNI); не монтируется том (PVC не привязан, CSI-ошибка);
образ качается долго или не качается (`ImagePullBackOff` рядом); отсутствует
ConfigMap/Secret, указанный в спеке.

</details>

**D5.** Нода в статусе `NotReady`, но `docker ps`/`crictl ps` на ней показывает работающие
контейнеры. Объясни это состояние.

<details><summary>Ответ</summary>

Нода потеряла связь с control plane или на ней умер kubelet, но container runtime
и контейнеры живы. Управление потеряно, трафик может продолжать идти —
до момента вытеснения подов на другие ноды.

</details>

**D6.** После планового обновления ОС на ноде поды на ней перестали резолвить имена
сервисов, хотя по IP всё работает. Где искать?

<details><summary>Ответ</summary>

Под CoreDNS или сеть до него; на самой ноде — CNI-плагин после обновления ядра;
`/etc/resolv.conf` и параметры kubelet (`--cluster-dns`); правила iptables,
сброшенные при обновлении.

</details>

**D7.** Ровно через год после установки кластера `kubectl` начал отвечать
`x509: certificate has expired`. Что произошло и что делать?

<details><summary>Ответ</summary>

Истекли сертификаты `/etc/kubernetes/pki` (срок год). Нужно
`kubeadm certs renew all`, перезапуск статических подов control plane и обновление
kubeconfig'ов. Профилактика: регулярное обновление кластера и мониторинг срока
через `kubeadm certs check-expiration`.

</details>

**D8.** В кластере из 3 control-plane нод выключили две. Что стало с кластером и почему?

<details><summary>Ответ</summary>

Потерян кворум etcd (1 из 3) — кластер переходит в read-only/неработоспособное
состояние для записи, управление недоступно. Рабочие нагрузки продолжают работать.

</details>

**D9.** В облачном кластере удалили ВМ через консоль облака, но объект Node остался
в `kubectl get nodes` несколько минут. Какой компонент за это отвечает?

<details><summary>Ответ</summary>

cloud-controller-manager (node-контроллер): он сверяет объекты Node
с существующими ВМ провайдера и удаляет «осиротевшие».

</details>

**D10.** Сервис `type: LoadBalancer` уже час в `<pending>` на кластере, поднятом kubeadm
на своих серверах. Причина и варианты решения.

<details><summary>Ответ</summary>

Нет cloud-controller-manager, который создал бы внешний балансировщик.
Решения: MetalLB (L2/BGP), kube-vip, обращение через NodePort или через Ingress Controller,
опубликованный `hostNetwork`/NodePort.

</details>

**D11.** Диск на control-plane ноде заполнился, API server стал отвечать ошибками записи.
Какой компонент пострадал в первую очередь и чем это грозит?

<details><summary>Ответ</summary>

etcd: он крайне чувствителен к диску, при нехватке места переходит в режим
только для чтения (alarm NOSPACE) и кластер теряет управление. Лечение — очистка,
дефрагментация и compaction, затем снятие alarm'а.

</details>

**D12.** Сотрудник предлагает поднять etcd на 4 узлах «чтобы надёжнее». Что отвечаешь?

<details><summary>Ответ</summary>

Четвёртый узел не повышает отказоустойчивость (кворум 3 из 4 = выдерживает
один отказ, как и 3 узла), зато увеличивает стоимость согласования и вероятность отказа.
Нужны нечётные числа: 3, 5, реже 7.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Расскажи про архитектуру Kubernetes. *(вопрос роадмапа)*

<details><summary>Ответ</summary>

Отвечать по пути пода: kubectl → API server (аутентификация, RBAC, admission) → etcd →
Deployment-контроллер → ReplicaSet → поды без ноды → scheduler назначает ноду →
kubelet этой ноды через CRI запускает контейнеры, CNI даёт сеть →
EndpointSlice и kube-proxy подключают под к Service.

</details>

**2.** Что делает API server и почему он центральный?

<details><summary>Ответ</summary>

Единственная точка входа и единственный клиент etcd; выполняет аутентификацию,
авторизацию, admission и валидацию; отдаёт watch-поток изменений; stateless и масштабируем.

</details>

**3.** Что хранится в etcd и как его бэкапить?

<details><summary>Ответ</summary>

Все объекты кластера и их состояние. Бэкап — `etcdctl snapshot save`, регулярно,
с проверкой восстановления на тестовом стенде.

</details>

**4.** Как scheduler выбирает ноду?

<details><summary>Ответ</summary>

Фильтрация нод по жёстким условиям (ресурсы, affinity, taints, тома), затем скоринг
по предпочтениям, затем binding — запись `nodeName`.

</details>

**5.** Что такое controller manager и как он работает?

<details><summary>Ответ</summary>

Процесс с десятками контроллеров, каждый из которых в цикле сверяет желаемое
и фактическое состояние для своего типа объектов; при нескольких репликах — leader election.

</details>

**6.** Что делает kubelet?

<details><summary>Ответ</summary>

Агент ноды: запускает и останавливает поды через CRI, монтирует тома и конфиги,
выполняет probe'ы, отправляет статус, вытесняет поды при нехватке ресурсов,
обслуживает статические поды.

</details>

**7.** Что такое CRI и почему убрали dockershim?

<details><summary>Ответ</summary>

CRI — интерфейс между kubelet и runtime. Dockershim был прослойкой для Docker Engine,
его удалили в 1.24; образы и Dockerfile не меняются, работает containerd.

</details>

**8.** Что делает kube-proxy и в каких режимах работает?

<details><summary>Ответ</summary>

Программирует правила ядра для маршрутизации трафика Service → поды;
режимы iptables, IPVS, nftables; может быть заменён eBPF-реализацией CNI.

</details>

**9.** Что будет, если упадёт control plane? А если нода?

<details><summary>Ответ</summary>

Control plane: теряется управление, новые поды не создаются, но текущая нагрузка
работает. Нода: `NotReady` примерно через 40 секунд, поды пересоздаются на других
примерно через 5 минут.

</details>

**10.** Как сделать control plane отказоустойчивым?

<details><summary>Ответ</summary>

Минимум 3 control-plane ноды: API server за балансировщиком, scheduler
и controller-manager в leader election, etcd с кворумом (stacked или external),
плюс регулярные снапшоты etcd.

</details>

---

### 🎯 Чек-лист

- [ ] ⭐ Рисую схему кластера по памяти без подсказок
- [ ] ⭐ Рассказываю путь `kubectl apply` → контейнер за 2 минуты
- [ ] Знаю, кто пишет в etcd и почему это важно
- [ ] Знаю два этапа работы scheduler'а
- [ ] Отличаю «упал control plane» от «упала нода» по последствиям
- [ ] Отключал scheduler и kubelet и видел последствия своими глазами
- [ ] Умею смотреть контейнеры через `crictl` и логи через `journalctl -u kubelet`
- [ ] Знаю порты 6443 / 2379 / 10250 и диапазон NodePort
- [ ] Могу объяснить историю с dockershim без паники
- [ ] Знаю про сертификаты на год и `kubeadm certs check-expiration`
