---
title: "11. ⭐ Service"
description: "Типы сервисов — ClusterIP, NodePort, LoadBalancer, headless, ExternalName — и главный инцидент «сервис есть, а не отвечает»"
---

# 11. ⭐ Service

> Роадмап → 6. Kubernetes → Сеть → Настройка через манифесты → **Service**.
> Вопрос собеса: *«Какие типы сервисов (Service) бывают в Kubernetes?»*
> **После темы ты умеешь:** выбрать тип сервиса под задачу, разобрать «сервис есть,
> а не отвечает» и объяснить, чем headless-сервис отличается от обычного.

---

## 🗺️ Карта темы

```text:no-line-numbers
         СНАРУЖИ                           ВНУТРИ КЛАСТЕРА
             │
   ┌─────────┴──────────┐
   │                    │
LoadBalancer        NodePort            ClusterIP ◄── по умолчанию, только внутри
(облачный LB)     (порт на каждой       (виртуальный IP + DNS-имя)
   │               ноде 30000-32767)         │
   └───────┬───────────┘                     │
           ▼                                 ▼
       NodePort ──────────► ClusterIP ──► поды (по селектору → EndpointSlice)

  Особые:
   headless (clusterIP: None)  — без балансировки, DNS отдаёт IP всех подов
   ExternalName                — CNAME на внешнее имя, без проксирования
```

**Иерархия:** LoadBalancer включает в себя NodePort, NodePort включает в себя ClusterIP.
Создавая LoadBalancer, ты автоматически получаешь и NodePort, и ClusterIP.

---

## 1. Зачем нужен Service

IP подов эфемерны: пересоздался под — адрес другой. Service даёт:

| Что даёт | Подробности |
|----------|-------------|
| **Стабильный адрес** | ClusterIP не меняется всё время жизни сервиса |
| **Стабильное имя** | `web.default.svc.cluster.local` через CoreDNS |
| **Балансировку** | Трафик распределяется между всеми готовыми подами |
| **Автообновление списка** | Под упал/появился — EndpointSlice обновился автоматически |
| **Точку входа снаружи** | NodePort и LoadBalancer |

---

## 2. ClusterIP — тип по умолчанию

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web
spec:
  type: ClusterIP              # можно не писать
  selector:
    app: web                   # ⭐ по этим меткам ищем поды
  ports:
    - name: http
      port: 80                 # порт САМОГО сервиса
      targetPort: 8080         # порт В КОНТЕЙНЕРЕ
      protocol: TCP
```

| Поле | Что значит |
|------|------------|
| `port` | По какому порту обращаются к сервису |
| `targetPort` | Куда перенаправлять в поде; можно имя порта из контейнера |
| `nodePort` | Только для NodePort/LoadBalancer |
| `selector` | ⭐ Метки подов; определяет содержимое EndpointSlice |

`targetPort` по имени — удобнее и надёжнее:
```yaml
# в контейнере
ports:
  - name: http
    containerPort: 8080
# в сервисе
targetPort: http
```

Доступ: только изнутри кластера — из подов, по ClusterIP или по DNS-имени.
Снаружи — через `kubectl port-forward` (для отладки), Ingress или другой тип сервиса.

---

## 3. NodePort

```yaml
spec:
  type: NodePort
  selector: { app: web }
  ports:
    - port: 80
      targetPort: 8080
      nodePort: 30080          # необязательно; иначе выберется из 30000-32767
```

```text:no-line-numbers
клиент → <IP ЛЮБОЙ ноды>:30080 → kube-proxy → ClusterIP → под
```

| Плюсы | Минусы |
|-------|--------|
| Работает без облака | Некрасивые порты 30000-32767 |
| Простой способ «показать наружу» | Нужен внешний балансировщик перед нодами |
| Основа для LoadBalancer и части Ingress-инсталляций | Один порт = один сервис на весь кластер |

**`externalTrafficPolicy`** — важный нюанс:

| Значение | Поведение |
|----------|-----------|
| `Cluster` (по умолчанию) | Трафик может быть переброшен на под на другой ноде; применяется SNAT — **реальный IP клиента теряется**, зато нагрузка ровнее |
| `Local` | Только поды на этой ноде; **IP клиента сохраняется**; если подов на ноде нет — соединение не проходит (это и используется для health-check балансировщика) |

---

## 4. LoadBalancer

```yaml
spec:
  type: LoadBalancer
  selector: { app: web }
  ports:
    - port: 80
      targetPort: 8080
```

Что происходит: cloud-controller-manager создаёт **реальный балансировщик** облака
и прописывает его адрес в `status.loadBalancer.ingress`.

```bash
kubectl get svc web
# NAME  TYPE          CLUSTER-IP     EXTERNAL-IP     PORT(S)
# web   LoadBalancer  10.96.0.42     203.0.113.10    80:30080/TCP
```

> ⚠️ **`EXTERNAL-IP: <pending>` навсегда** — значит, некому создать балансировщик:
> кластер не в облаке (kubeadm на своих серверах, kind, minikube).
> Решения: MetalLB, kube-vip, либо использовать NodePort/Ingress.

**Цена вопроса:** каждый LoadBalancer-сервис в облаке — это отдельный платный
балансировщик с собственным IP. Поэтому наружу обычно выставляют **один**
LoadBalancer для Ingress Controller, а все приложения публикуют через Ingress (тема 12).

---

## 5. Headless Service

```yaml
spec:
  clusterIP: None              # ⭐ вот и всё отличие
  selector: { app: postgres }
  ports: [{ port: 5432 }]
```

| Обычный ClusterIP | Headless |
|-------------------|----------|
| DNS отдаёт **один** виртуальный IP | DNS отдаёт **все IP подов** (A-записи) |
| Балансирует ядро ноды | Балансирует (или выбирает) сам клиент |
| Подходит для stateless | Нужен для StatefulSet, кластерных приложений |

```bash
nslookup web              # ClusterIP: один адрес 10.96.0.42
nslookup postgres         # headless: 10.244.1.5, 10.244.2.7, 10.244.1.9
nslookup postgres-0.postgres   # конкретный под StatefulSet
```

Применение: StatefulSet (тема 06), клиентская балансировка (gRPC), обнаружение
участников кластера (Kafka, etcd, Elasticsearch).

---

## 6. ExternalName

```yaml
spec:
  type: ExternalName
  externalName: db.prod.example.com
```
DNS-запрос к `mydb.default.svc.cluster.local` вернёт CNAME на внешнее имя.
Никакого проксирования и селекторов. Удобно, чтобы приложение всегда обращалось
к `mydb`, а куда именно — решалось на уровне окружения (в dev — под в кластере,
в prod — managed-БД).

---

## 7. Service без селектора (ручные Endpoints)

Иногда нужно завести сервис на внешний IP (например, на БД вне кластера):

```yaml
apiVersion: v1
kind: Service
metadata: { name: external-db }
spec:
  ports: [{ port: 5432 }]
---
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata:
  name: external-db-1
  labels:
    kubernetes.io/service-name: external-db
addressType: IPv4
ports: [{ port: 5432 }]
endpoints:
  - addresses: ["192.168.10.50"]
```
Приложение обращается к `external-db:5432`, не зная про внешний адрес.

---

## 8. ⭐ Главный инцидент: «сервис есть, а не отвечает»

```bash
kubectl get svc web                 # ClusterIP выдан
kubectl get endpoints web           # ← ГЛАВНАЯ ПРОВЕРКА
# ENDPOINTS: <none>                 ← вот в чём дело
```

| Причина | Как проверить | Лечение |
|---------|---------------|---------|
| Метки не совпали | `kubectl get pods --show-labels` vs `kubectl describe svc` | Привести в соответствие |
| Поды не Ready | `kubectl get pods` → `0/1` | Чинить readiness (тема 09) |
| Неверный `targetPort` | `kubectl describe svc` + реальный порт приложения | Исправить порт |
| Другой namespace | `kubectl get svc -A` | Сервис и поды в одном namespace |
| NetworkPolicy | `kubectl get netpol` | Разрешить трафик (тема 13) |
| Приложение слушает `127.0.0.1` | `kubectl exec -- ss -tlnp` | Слушать `0.0.0.0` |

Последний пункт — коварный: внутри пода `curl localhost:8080` работает, а через сервис — нет.

**Проверка по шагам:**
```bash
kubectl get endpoints web                                  # 1. есть ли адреса
kubectl exec -it netshoot -- curl http://<IP пода>:8080    # 2. под отвечает?
kubectl exec -it netshoot -- curl http://10.96.0.42:80     # 3. ClusterIP работает?
kubectl exec -it netshoot -- curl http://web:80            # 4. DNS работает?
```

---

## 9. Сессии и балансировка

```yaml
spec:
  sessionAffinity: ClientIP          # «липкие» сессии по IP клиента
  sessionAffinityConfig:
    clientIP: { timeoutSeconds: 10800 }
```

| Факт | Пояснение |
|------|-----------|
| Балансировка по умолчанию | Случайная (iptables) — не round-robin |
| Уровень | L4 (TCP/UDP), не HTTP: нет маршрутизации по путям и заголовкам |
| Долгие соединения | Keep-alive и gRPC «прилипают» к одному поду: новые реплики не получают трафик, пока соединения не переустановятся |
| Решение для gRPC | Headless + клиентская балансировка, либо service mesh, либо L7-прокси |

---

## 💼 Как это в DevOps

- В типичном приложении: Deployment + ClusterIP-сервис + Ingress. NodePort и
  LoadBalancer напрямую используют редко — дорого и неудобно.
- `kubectl get endpoints` — первая команда при жалобе «сервис не работает».
  Экономит десятки минут.
- `externalTrafficPolicy: Local` ставят, когда нужен реальный IP клиента
  (антифрод, геоаналитика, rate-limit по IP).
- В bare-metal-кластере LoadBalancer появляется только вместе с MetalLB —
  это стандартная часть установки.
- Имя сервиса — часть контракта между командами: менять его больно, поэтому
  договариваются заранее.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Доступ внутри кластера | `type: ClusterIP` (по умолчанию) |
| Порт на каждой ноде | `type: NodePort` |
| Внешний балансировщик облака | `type: LoadBalancer` |
| Персональные DNS-имена подов | `clusterIP: None` (headless) |
| Алиас на внешнее имя | `type: ExternalName` |
| Сервис на внешний IP | Service без селектора + EndpointSlice вручную |
| Сохранить IP клиента | `externalTrafficPolicy: Local` |
| Липкие сессии | `sessionAffinity: ClientIP` |
| Быстро создать сервис | `kubectl expose deploy web --port=80 --target-port=8080` |
| Проверить, работает ли | `kubectl get endpoints web` |
| Пробросить локально | `kubectl port-forward svc/web 8080:80` |

---

## 🧠 Что запомнить

1. ⭐ Типы: **ClusterIP, NodePort, LoadBalancer, ExternalName** (+ headless как вариант ClusterIP).
2. LoadBalancer включает NodePort, NodePort включает ClusterIP.
3. `port` — порт сервиса, `targetPort` — порт в контейнере; лучше ссылаться по имени.
4. Связь с подами — только через **метки**; результат виден в EndpointSlice.
5. ⭐ Пустой `kubectl get endpoints` — метки не совпали или поды не Ready.
6. NodePort работает в диапазоне 30000-32767 на **каждой** ноде.
7. `EXTERNAL-IP: <pending>` без облака — нужен MetalLB или Ingress.
8. `externalTrafficPolicy: Local` сохраняет IP клиента, `Cluster` — балансирует ровнее.
9. Headless (`clusterIP: None`) отдаёт IP всех подов и обязателен для StatefulSet.
10. Service работает на L4: маршрутизации по URL и заголовкам нет — это Ingress.
11. Балансировка случайная, а не round-robin; keep-alive «прилипает» к поду.
12. Приложение должно слушать `0.0.0.0`, иначе сервис не будет отвечать.

---

## Задачи

> ⭐ Здесь вопрос собеса: *«Какие типы сервисов бывают в Kubernetes?»*
> И самый частый рабочий инцидент — «сервис есть, а не отвечает».

---

### Блок A. Теория

**A1.** ⭐ Зачем нужен Service, если у пода есть IP?

<details><summary>Ответ</summary>

IP подов эфемерны и меняются при каждом пересоздании. Service даёт стабильные
адрес и имя, балансировку между репликами и автоматическое обновление списка адресов.

</details>

**A2.** ⭐ Назови все типы Service и что каждый даёт.

<details><summary>Ответ</summary>

`ClusterIP` — доступ внутри кластера; `NodePort` — порт на каждой ноде;
`LoadBalancer` — внешний балансировщик облака; `ExternalName` — DNS-алиас
на внешнее имя; плюс headless (`clusterIP: None`) — без балансировки, с адресами подов.

</details>

**A3.** Как типы связаны между собой (что во что входит)?

<details><summary>Ответ</summary>

LoadBalancer создаёт NodePort, NodePort создаёт ClusterIP.

</details>

**A4.** В чём разница между `port`, `targetPort` и `nodePort`?

<details><summary>Ответ</summary>

`port` — порт сервиса; `targetPort` — порт в контейнере;
`nodePort` — порт, открываемый на нодах (30000-32767).

</details>

**A5.** Можно ли указать `targetPort` по имени? Зачем это делать?

<details><summary>Ответ</summary>

Да, по имени порта контейнера. Это устойчиво к изменению номера порта
в приложении: меняется только спека контейнера.

</details>

**A6.** Как Service находит свои поды?

<details><summary>Ответ</summary>

По меткам через `spec.selector`; контроллер формирует EndpointSlice
из подходящих и готовых подов.

</details>

**A7.** Что такое Endpoints/EndpointSlice и кто их обновляет?

<details><summary>Ответ</summary>

Объекты со списком адресов и портов подов за сервисом; обновляются
контроллером EndpointSlice в controller-manager.

</details>

**A8.** Попадёт ли под, не прошедший readiness, в Endpoints?

<details><summary>Ответ</summary>

Нет. Именно поэтому readiness управляет трафиком.

</details>

**A9.** Какой диапазон портов у NodePort и на скольких нодах открывается порт?

<details><summary>Ответ</summary>

30000-32767; порт открывается на **всех** нодах кластера, независимо
от наличия подов на них.

</details>

**A10.** ⭐ Что означает `EXTERNAL-IP: <pending>` у LoadBalancer?

<details><summary>Ответ</summary>

Некому создать облачный балансировщик: нет cloud-controller-manager
(bare-metal, kind, minikube) либо облако не смогло его выделить.

</details>

**A11.** Что делает cloud-controller-manager при создании LoadBalancer?

<details><summary>Ответ</summary>

Создаёт балансировщик в облаке, привязывает к нему ноды (обычно
по NodePort), настраивает health-check и записывает внешний адрес
в `status.loadBalancer`.

</details>

**A12.** Почему в проде не делают LoadBalancer на каждое приложение?

<details><summary>Ответ</summary>

Каждый такой сервис — отдельный платный балансировщик с собственным IP.
Дешевле один LoadBalancer для Ingress Controller и публикация приложений через Ingress.

</details>

**A13.** ⭐ Что такое headless Service и чем он отличается от ClusterIP?

<details><summary>Ответ</summary>

У него нет ClusterIP: DNS-запрос возвращает адреса всех подов,
балансировку выполняет клиент.

</details>

**A14.** Где headless обязателен?

<details><summary>Ответ</summary>

В StatefulSet — для персональных DNS-имён подов; а также для клиентской
балансировки и обнаружения участников кластерных приложений.

</details>

**A15.** Что делает ExternalName и когда он полезен?

<details><summary>Ответ</summary>

Возвращает CNAME на внешнее имя; полезен, чтобы приложение всегда
обращалось к одному имени, а фактический адрес зависел от окружения.

</details>

**A16.** Как сделать сервис, указывающий на внешний IP вне кластера?

<details><summary>Ответ</summary>

Service без `selector` плюс EndpointSlice (или Endpoints), созданный вручную
с нужными адресами.

</details>

**A17.** ⭐ Что означает `externalTrafficPolicy: Local` и какой у него побочный эффект?

<details><summary>Ответ</summary>

Трафик обслуживают только поды на той же ноде, куда он пришёл;
IP клиента сохраняется. Побочный эффект: ноды без подов не отвечают
(и исключаются health-check'ом балансировщика), возможна неравномерная нагрузка.

</details>

**A18.** Почему при `Cluster` теряется IP клиента?

<details><summary>Ответ</summary>

Пакет может быть переброшен на другую ноду, и чтобы ответ вернулся тем же
путём, применяется SNAT — адрес источника подменяется адресом ноды.

</details>

**A19.** На каком уровне модели OSI работает Service? Что из этого следует?

<details><summary>Ответ</summary>

На L4 (TCP/UDP). Значит, нет маршрутизации по URL, заголовкам и хостам,
нет TLS-терминации — это задачи Ingress.

</details>

**A20.** Какой алгоритм балансировки у Service по умолчанию?

<details><summary>Ответ</summary>

В режиме iptables — случайный выбор бэкенда (не round-robin);
в IPVS — настраиваемый алгоритм (по умолчанию round-robin).

</details>

**A21.** Почему gRPC и keep-alive плохо балансируются через ClusterIP?

<details><summary>Ответ</summary>

Балансировка происходит на уровне соединения: долгоживущее соединение
остаётся привязанным к одному поду, и новые реплики не получают нагрузки.

</details>

**A22.** Что такое `sessionAffinity` и когда его используют?

<details><summary>Ответ</summary>

Привязка клиента к одному поду по IP (`ClientIP`) на заданный таймаут.
Используется, когда приложение хранит состояние сессии локально.

</details>

**A23.** Что произойдёт, если приложение слушает `127.0.0.1`?

<details><summary>Ответ</summary>

Внутри пода всё работает, а снаружи — нет: трафик от Service приходит
на IP пода, а не на loopback. Нужно слушать `0.0.0.0`.

</details>

**A24.** Как обратиться к сервису из другого namespace?

<details><summary>Ответ</summary>

`service.namespace` (или полное имя `service.namespace.svc.cluster.local`).

</details>

**A25.** Чем `kubectl port-forward` отличается от NodePort?

<details><summary>Ответ</summary>

`port-forward` — это отладочный туннель через API server для одного
пользователя; NodePort — постоянная точка входа на всех нодах.

</details>

---

### Блок B. «Что произойдёт»

**B1.**
```yaml
kind: Service
spec:
  selector: { app: web, tier: front }
---
kind: Pod
metadata:
  labels: { app: web }
```
Вопрос: попадёт ли под в Endpoints?

<details><summary>Ответ</summary>

Нет: селектор требует обе метки, а у пода только одна.

</details>

**B2.**
```yaml
kind: Service
spec:
  selector: { app: web }
  ports:
    - port: 80
      targetPort: 80
# контейнер слушает 8080
```
Вопрос: что увидит клиент?

<details><summary>Ответ</summary>

Соединение не установится (таймаут или отказ): DNAT направит трафик
на порт 80 пода, где никто не слушает.

</details>

**B3.**
```bash
kubectl get endpoints web
# NAME  ENDPOINTS
# web   <none>
kubectl get pods -l app=web
# web-xxx  0/1  Running
```
Вопрос: причина и лечение.

<details><summary>Ответ</summary>

Под не проходит readiness, поэтому исключён из Endpoints. Чинить пробу
или приложение.

</details>

**B4.**
```yaml
kind: Service
spec:
  type: LoadBalancer
# кластер поднят kubeadm на своих серверах
```
Вопрос: что будет в колонке EXTERNAL-IP и как получить доступ снаружи?

<details><summary>Ответ</summary>

`<pending>` — нет cloud-controller-manager. Доступ снаружи: NodePort,
MetalLB/kube-vip или Ingress Controller.

</details>

**B5.**
```yaml
kind: Service
spec:
  clusterIP: None
  selector: { app: db }
```
Вопрос: что вернёт `nslookup db` из пода?

<details><summary>Ответ</summary>

Список IP всех подов, подходящих под селектор (несколько A-записей),
а не один ClusterIP.

</details>

**B6.**
```bash
kubectl exec -it app -- curl http://web
# работает
kubectl exec -it app -- curl http://web.other-ns
# not resolved
```
Вопрос: в чём дело?

<details><summary>Ответ</summary>

Сервиса `web` нет в namespace `other-ns` (или имя namespace указано неверно).
Проверить `kubectl get svc -n other-ns`.

</details>

**B7.**
```yaml
spec:
  type: NodePort
  externalTrafficPolicy: Local
# на ноде node3 нет подов этого приложения
```
Вопрос: что произойдёт при запросе на `node3:30080`?

<details><summary>Ответ</summary>

Соединение не установится: при `Local` обслуживают только локальные поды,
а на `node3` их нет.

</details>

**B8.**
```bash
# внутри пода
curl http://localhost:8080     # работает
# из другого пода
curl http://web:80             # connection refused
```
Вопрос: наиболее вероятная причина?

<details><summary>Ответ</summary>

Приложение слушает только `127.0.0.1` — либо в сервисе указан неверный
`targetPort`.

</details>

**B9.**
```yaml
kind: Service
metadata: { name: mydb }
spec:
  type: ExternalName
  externalName: postgres.rds.amazonaws.com
```
Вопрос: что вернёт DNS-запрос `mydb` и пойдёт ли трафик через кластер?

<details><summary>Ответ</summary>

DNS вернёт CNAME на `postgres.rds.amazonaws.com`; трафик пойдёт напрямую
из пода, кластер его не проксирует.

</details>

---

### Блок C. Практика

#### C1. 🔑 ClusterIP
Создай Deployment (3 реплики) и ClusterIP-сервис вручную в манифесте.
1. Проверь `kubectl get endpoints` — три адреса.
2. Из временного пода сделай 20 запросов и посчитай, сколько раз ответил каждый под
   (отдай имя пода в ответе через `env` и `nginx`-конфиг или используй
   образ `hashicorp/http-echo`).
3. Сделай вывод о характере балансировки.

<details><summary>Ответ</summary>

Распределение будет неравномерным на малом числе запросов: выбор бэкенда
случайный, а не строго по кругу.

</details>

#### C2. 🔑 Ломаем метки *(главный инцидент темы)*
1. Поменяй селектор сервиса на несуществующую метку.
2. Проверь `kubectl get endpoints` и попытку запроса.
3. Запиши точный симптом (таймаут или connection refused — и почему именно такой).
4. Верни метку.

<details><summary>Ответ</summary>

При пустых Endpoints обращение к ClusterIP обычно даёт отказ соединения
(правило есть, бэкендов нет) — в отличие от таймаута, характерного для сетевых
блокировок и неверного порта.

</details>

#### C3. targetPort
Сделай сервис с неверным `targetPort` и посмотри, как выглядит ошибка.
Потом переделай на ссылку по имени порта.

#### C4. readiness и Endpoints
1. Сломай readiness одного пода (тема 09).
2. Следи за `kubectl get endpoints web -w`.
3. Убедись, что адрес исчез, и верни обратно.

#### C5. 🔑 NodePort
1. Создай NodePort-сервис.
2. Узнай порт и зайди с хоста на каждую ноду по очереди (в kind — через
   `docker exec` или проброс портов при создании кластера).
3. Убедись, что порт открыт на всех нодах, даже там, где нет подов.

#### C6. externalTrafficPolicy
1. Поставь `Cluster`, посмотри в логах приложения IP клиента.
2. Поставь `Local`, повтори.
3. Запиши разницу. Объясни, почему при `Local` часть нод перестаёт отвечать.

<details><summary>Ответ</summary>

При `Cluster` в логах виден IP ноды, при `Local` — реальный IP клиента;
при `Local` ноды без подов перестают отвечать.

</details>

#### C7. LoadBalancer
1. Создай LoadBalancer-сервис и убедись, что он в `<pending>`.
2. Установи MetalLB (или прочитай его документацию и опиши в заметке, как он работает).
3. Если ставил — получи настоящий EXTERNAL-IP и зайди по нему.

#### C8. 🔑 Headless
1. Создай headless-сервис для StatefulSet из темы 06.
2. Сравни `nslookup db` для headless и для обычного сервиса.
3. Сделай `nslookup db-0.db` и объясни результат.

<details><summary>Ответ</summary>

Для headless `nslookup` вернёт все адреса подов; `db-0.db` — адрес
конкретного пода StatefulSet.

</details>

#### C9. ExternalName
Создай `ExternalName`-сервис на `example.com` и проверь `nslookup` из пода.
Объясни, почему это «DNS-алиас», а не прокси.

#### C10. Service без селектора
Сделай сервис на внешний адрес (например, на IP своей хост-машины с поднятым nginx)
через ручной EndpointSlice. Проверь доступ из пода по имени сервиса.

#### C11. sessionAffinity
Включи `sessionAffinity: ClientIP` и повтори эксперимент из C1.
Запиши, как изменилось распределение.

#### C12. 🔑 Алгоритм разбора
Прогони четыре проверки подряд на рабочем сервисе и запиши вывод каждой:
```bash
kubectl get endpoints web
kubectl exec -it netshoot -- curl -s -o /dev/null -w "%{http_code}\n" http://<pod-ip>:8080
kubectl exec -it netshoot -- curl -s -o /dev/null -w "%{http_code}\n" http://<cluster-ip>:80
kubectl exec -it netshoot -- curl -s -o /dev/null -w "%{http_code}\n" http://web:80
```
Потом сломай что-нибудь и определи поломку только по этим четырём командам.

#### C13. Приложение на 127.0.0.1 (со звёздочкой)
Запусти приложение, слушающее только localhost (например,
`python3 -m http.server --bind 127.0.0.1 8080`), и убедись, что сервис не работает,
хотя внутри пода всё в порядке. Найди проблему через `ss -tlnp` внутри пода.

<details><summary>Ответ</summary>

`ss -tlnp` внутри пода покажет привязку к `127.0.0.1:8080` вместо
`0.0.0.0:8080` — это и есть причина.

</details>

#### C14. keep-alive и балансировка (со звёздочкой)
Сделай клиент с keep-alive (`curl --keepalive` в цикле или Go/Python-клиент)
и проверь, попадают ли запросы в разные поды. Сформулируй проблему для gRPC.

---

### Блок D. Инциденты

**D1.** «Сервис не работает». Назови четыре команды, которые выполнишь по порядку.

<details><summary>Ответ</summary>

`kubectl get endpoints svc` → `curl` по IP пода → `curl` по ClusterIP →
`nslookup`/`curl` по имени. Дальше — NetworkPolicy и проверка с разных нод.

</details>

**D2.** `kubectl get endpoints` пуст, поды `Running 1/1`. Причина?

<details><summary>Ответ</summary>

Метки в селекторе не совпадают с метками подов (или сервис в другом namespace).

</details>

**D3.** Запросы к сервису получают таймаут, а не connection refused.
О чём это говорит?

<details><summary>Ответ</summary>

Таймаут означает, что пакеты уходят «в никуда»: неверный `targetPort`,
блокировка NetworkPolicy или проблемы сети между нодами. Отказ соединения
обычно означает, что адрес достижим, но порт закрыт или бэкендов нет.

</details>

**D4.** После деплоя нового приложения сервис отвечает 502 через Ingress,
хотя под работает. Куда смотреть в контексте Service?

<details><summary>Ответ</summary>

Проверить `targetPort`, метки, readiness подов и Endpoints:
ingress-контроллер обращается к сервису так же, как любой под.

</details>

**D5.** Приложение работает, если зайти `kubectl port-forward pod/...`,
но не работает через сервис. Гипотезы?

<details><summary>Ответ</summary>

`port-forward` идёт напрямую в под, минуя Service: значит, проблема
в сервисе — селектор, `targetPort`, readiness или NetworkPolicy.

</details>

**D6.** Половина запросов проходит, половина — таймаут. Что проверить?

<details><summary>Ответ</summary>

Часть подов за сервисом неработоспособна, но остаётся в Endpoints
(нет readiness-пробы), либо часть нод имеет проблемы с сетью/kube-proxy.

</details>

**D7.** LoadBalancer в облаке создан, но трафик не идёт на половину нод.
Что стоит проверить в связке с `externalTrafficPolicy`?

<details><summary>Ответ</summary>

Вероятно, включён `externalTrafficPolicy: Local`, и на части нод нет подов:
балансировщик исключает их по health-check. Это ожидаемое поведение.

</details>

**D8.** После масштабирования с 2 до 10 реплик новые поды почти не получают трафик.
Что происходит?

<details><summary>Ответ</summary>

Долгоживущие соединения (keep-alive, gRPC) остаются на старых подах.
Нужны клиентская балансировка, ограничение времени жизни соединений или L7-прокси.

</details>

**D9.** Финансовый отдел прислал счёт за 30 облачных балансировщиков.
Что предложить?

<details><summary>Ответ</summary>

Свести к одному LoadBalancer для Ingress Controller и публиковать приложения
через Ingress с маршрутизацией по хостам и путям.

</details>

**D10.** Приложение логирует IP клиента как адрес ноды. Как вернуть реальный IP
(два варианта)?

<details><summary>Ответ</summary>

`externalTrafficPolicy: Local` или проксирование через Ingress
с корректной передачей `X-Forwarded-For` и доверием к нему на стороне приложения.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Какие типы Service бывают? *(вопрос роадмапа)*

<details><summary>Ответ</summary>

ClusterIP, NodePort, LoadBalancer, ExternalName; плюс headless как вариант
ClusterIP без виртуального адреса.

</details>

**2.** Чем ClusterIP отличается от NodePort и LoadBalancer?

<details><summary>Ответ</summary>

ClusterIP — только внутри кластера; NodePort — порт на каждой ноде;
LoadBalancer — внешний балансировщик облака поверх NodePort.

</details>

**3.** Что такое headless Service и зачем он нужен?

<details><summary>Ответ</summary>

Сервис без ClusterIP: DNS возвращает адреса подов. Нужен для StatefulSet
и клиентской балансировки.

</details>

**4.** Как Service узнаёт, куда слать трафик?

<details><summary>Ответ</summary>

По меткам подов; список адресов хранится в EndpointSlice и обновляется контроллером.

</details>

**5.** Что такое Endpoints/EndpointSlice?

<details><summary>Ответ</summary>

Объекты со списком адресов и портов готовых подов за сервисом.

</details>

**6.** Почему сервис может не отвечать при работающих подах?

<details><summary>Ответ</summary>

Несовпадение меток, неготовые поды, неверный `targetPort`, приложение слушает
localhost, блокирующая NetworkPolicy, разные namespace.

</details>

**7.** Что такое externalTrafficPolicy?

<details><summary>Ответ</summary>

Политика обработки внешнего трафика: `Cluster` (перебрасывать по кластеру, SNAT)
или `Local` (только локальные поды, IP клиента сохраняется).

</details>

**8.** На каком уровне работает Service и чего он не умеет?

<details><summary>Ответ</summary>

На L4; не умеет маршрутизацию по URL/хостам, TLS-терминацию и L7-политики.

</details>

**9.** Почему gRPC плохо балансируется обычным сервисом?

<details><summary>Ответ</summary>

Балансировка на уровне соединений, а gRPC держит одно долгое соединение —
оно остаётся на одном поде.

</details>

**10.** Что такое ExternalName?

<details><summary>Ответ</summary>

DNS-алиас на внешнее имя без проксирования трафика.

</details>

---

### 🎯 Чек-лист

- [ ] ⭐ Перечисляю все типы Service и их отличия без подсказок
- [ ] Понимаю разницу `port` / `targetPort` / `nodePort`
- [ ] Первая реакция на «сервис не работает» — `kubectl get endpoints`
- [ ] Ломал метки, readiness и `targetPort` и знаю симптом каждого случая
- [ ] Пробовал NodePort со всех нод
- [ ] Понимаю, почему LoadBalancer висит в `<pending>` без облака
- [ ] Делал headless-сервис и видел разницу в `nslookup`
- [ ] Знаю, что `externalTrafficPolicy: Local` сохраняет IP клиента
- [ ] Понимаю, почему gRPC/keep-alive балансируются плохо
