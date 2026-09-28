---
title: "20. Траблшутинг кластера"
description: "Алгоритм разбора: под не стартует, падает, сервис не отвечает, нода NotReady, кластер не отвечает"
---

# 20. Траблшутинг кластера

> Роадмап → Продвинутые вещи → развилка → **«Траблшутинг на уровне кластера»**.
> **После темы ты умеешь:** за минуты локализовать проблему по алгоритму,
> а не перебирать команды наугад.

---

## 🗺️ Общий алгоритм

```text:no-line-numbers
       ЧТО СЛОМАНО?
            │
  ┌─────────┼──────────────┬───────────────────┬────────────────┐
  ▼         ▼              ▼                   ▼                ▼
Под не    Под работает,  Сервис не          Нода себя       Кластер
стартует  но падает      отвечает           странно ведёт   не отвечает
  │         │              │                   │                │
  ▼         ▼              ▼                   ▼                ▼
§1        §2             §3                  §4               §5
```

Три команды, с которых начинается всё:
```bash
kubectl get pods -o wide           # что вообще происходит
kubectl describe pod <pod>         # события внизу — главный источник правды
kubectl logs <pod> [--previous]    # что сказало приложение
```
И четвёртая, о которой забывают:
```bash
kubectl get events -A --sort-by=.lastTimestamp | tail -30
```

---

## 1. Под не стартует

### `Pending`
```bash
kubectl describe pod <pod> | tail -20      # ищем FailedScheduling
```

| Сообщение | Причина | Решение |
|-----------|---------|---------|
| `Insufficient cpu/memory` | Сумма `requests` не влезает | Уменьшить requests, добавить ноды |
| `didn't match Pod's node affinity/selector` | Нет нод с нужными метками | Проверить метки нод |
| `had untolerated taint` | Нет toleration | Добавить toleration |
| `didn't match pod anti-affinity rules` | Жёсткий anti-affinity | Смягчить правило |
| `didn't find available persistent volumes` | PVC не привязан / не та зона | См. тему про storage |
| `node(s) were unschedulable` | Нода в cordon | `kubectl uncordon` |

### `ContainerCreating` дольше минуты
```bash
kubectl describe pod <pod>       # события про том, сеть, образ
```
Причины: не монтируется том (CSI), не выдаётся IP (CNI), огромный образ,
отсутствует ConfigMap/Secret.

### `ImagePullBackOff` / `ErrImagePull`

| Причина | Проверка |
|---------|----------|
| Опечатка в имени или теге | `describe` → точное имя образа |
| Приватный реестр без секрета | `imagePullSecrets`, см. тему про ConfigMap/Secret |
| Нет сети до реестра с ноды | `crictl pull` на ноде |
| Лимит запросов Docker Hub | Сообщение `toomanyrequests` |

### `CreateContainerConfigError`
Не найден ConfigMap/Secret или ключ в них. `describe` укажет точное имя.

---

## 2. Под запускается и падает

### `CrashLoopBackOff` ⭐
```bash
kubectl logs <pod> --previous              # ⭐ логи предыдущего запуска
kubectl describe pod <pod> | grep -A6 "Last State"
```

| Exit Code / Reason | Смысл |
|--------------------|-------|
| `1` | Ошибка приложения (конфиг, зависимость, исключение при старте) |
| `137` + `OOMKilled` | Превышен `limits.memory` |
| `137` без OOMKilled | SIGKILL: не завершился за grace period |
| `143` | SIGTERM — штатная остановка |
| `126/127` | Команда не найдена или не исполняема |
| `Error` без логов | Падает раньше, чем что-то пишет; проверь `command`/`args` |

Частая и неочевидная причина: **liveness-проба** убивает контейнер, который просто
долго стартует. В событиях будет `Unhealthy` + `Killing`.

### `READY 0/1` при `Running`
Не проходит readinessProbe. Проверь путь, порт, таймауты и зависимости приложения.

### `OOMKilled`
```bash
kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}'
```
Поднять `limits.memory` или чинить потребление; посмотреть, не JVM ли это
без `-XX:MaxRAMPercentage`.

### `Evicted`
Нода выдавила под из-за нехватки памяти или диска.
```bash
kubectl get events -A --field-selector reason=Evicted
kubectl describe node <node> | grep -A5 Conditions
```

---

## 3. Сервис не отвечает ⭐

Повторим как чек-лист:

```bash
# 1. есть ли адреса за сервисом
kubectl get endpoints <svc>          # пусто → метки / readiness

# 2. отвечает ли сам под
kubectl run netshoot --rm -it --image=nicolaka/netshoot --restart=Never -- \
  curl -m 3 http://<POD_IP>:<PORT>   # нет → приложение / порт / 127.0.0.1

# 3. работает ли ClusterIP
  curl -m 3 http://<CLUSTER_IP>:<PORT>   # нет → kube-proxy / targetPort

# 4. работает ли DNS
  nslookup <svc>                     # нет → CoreDNS

# 5. не блокирует ли политика
kubectl get netpol -n <ns>

# 6. снаружи
kubectl -n ingress-nginx logs -l app.kubernetes.io/component=controller | tail
```

| Симптом | Обычно означает |
|---------|-----------------|
| Таймаут | Пакеты отбрасываются: NetworkPolicy, неверный порт, проблема CNI |
| `connection refused` | Адрес достижим, но никто не слушает: нет endpoints, не тот порт |
| Работает по IP, не работает по имени | DNS (CoreDNS, `ndots`) |
| Работает не со всех нод | CNI между нодами, kube-proxy, MTU |
| 502 через Ingress | Бэкенд не отвечает: `targetPort`, readiness |
| 503 через Ingress | Нет endpoints |
| Иногда медленно, иногда нет | `ndots:5`, DNS-таймауты, conntrack |

---

## 4. Нода ведёт себя странно

```bash
kubectl get nodes -o wide
kubectl describe node <node> | grep -A15 Conditions
kubectl top node <node>
# на ноде:
journalctl -u kubelet -n 200 --no-pager
crictl ps -a | head
df -h; free -m; dmesg | tail -30
```

| Condition | Значение |
|-----------|----------|
| `Ready=False` | kubelet не отчитывается или не готов |
| `MemoryPressure=True` | Мало памяти → начнётся вытеснение |
| `DiskPressure=True` | Мало места (логи, образы, `emptyDir`) |
| `PIDPressure=True` | Исчерпаны процессы |
| `NetworkUnavailable=True` | Не настроена сеть ноды (CNI) |

Типичные причины `NotReady`: упал kubelet, упал container runtime,
кончилось место, сломался CNI после обновления ядра, потеряна связь с control plane,
истёк сертификат kubelet.

Порядок действий: посмотреть Conditions → логи kubelet → место на диске →
состояние runtime → сеть до API server.

---

## 5. Кластер не отвечает

```bash
kubectl cluster-info
kubectl get --raw='/readyz?verbose'
kubectl get componentstatuses 2>/dev/null
# на control-plane ноде:
crictl ps | grep -E 'apiserver|etcd|scheduler|controller'
journalctl -u kubelet -n 100 --no-pager
```

| Симптом | Гипотеза |
|---------|----------|
| `Unable to connect to the server` | API server не работает, неверный контекст, сеть/VPN |
| `x509: certificate has expired` | Истекли сертификаты |
| API отвечает медленно/ошибками записи | Проблемы etcd: диск, кворум, размер базы |
| `etcdserver: mvcc: database space exceeded` | Нужны compaction и дефрагментация |
| Всё работает, но ничего не создаётся | Упал controller-manager или scheduler |

Важно помнить: **падение control plane не останавливает уже работающие поды**.
Сначала оцени, идёт ли трафик, — это меняет степень срочности.

---

## 6. Инструменты

```bash
# эфемерный контейнер в существующем поде (не требует shell в образе)
kubectl debug -it <pod> --image=nicolaka/netshoot --target=<container>

# копия пода с изменённой командой
kubectl debug <pod> --copy-to=debug-pod --container=app -- sh

# отладочный под прямо на ноде (доступ к её namespace)
kubectl debug node/<node> -it --image=busybox

# универсальный сетевой под
kubectl run netshoot --rm -it --image=nicolaka/netshoot --restart=Never -- bash

# все события кластера
kubectl get events -A --sort-by=.lastTimestamp | tail -40
kubectl get events -A --field-selector type=Warning

# что реально применено
kubectl get <kind> <name> -o yaml
kubectl describe <kind> <name>
```

Полезные утилиты: `k9s` (терминальный дашборд), `stern` (логи многих подов сразу),
`kubectl-trace`, `popeye` (аудит конфигураций), `kube-capacity` (ресурсы по нодам).

---

## 7. Шпаргалка «симптом → первая команда»

| Симптом | Первая команда |
|---------|----------------|
| Под `Pending` | `kubectl describe pod` → `FailedScheduling` |
| Под `CrashLoopBackOff` | `kubectl logs --previous` |
| Под `ImagePullBackOff` | `kubectl describe pod` → точное имя образа |
| `READY 0/1` | `kubectl describe pod` → readiness |
| Рестарты без причины | `describe` → `Last State` (OOMKilled?) |
| Сервис не отвечает | `kubectl get endpoints` |
| 502 через Ingress | логи ingress-контроллера + `get endpoints` |
| Не резолвится имя | `kubectl -n kube-system get pods -l k8s-app=kube-dns` |
| Нода `NotReady` | `kubectl describe node` → Conditions, `journalctl -u kubelet` |
| Деплой не катится | `kubectl describe deploy` → Conditions |
| PVC `Pending` | `kubectl describe pvc` |
| `Forbidden` | `kubectl auth can-i --as=...` |
| Кластер молчит | `kubectl cluster-info`, `get --raw /readyz?verbose` |

---

## 8. Три правила разбора инцидента

1. **Сначала восстанови сервис, потом ищи причину.** `rollout undo`,
   `helm rollback`, увеличение реплик — это нормальные первые действия.
2. **Иди по слоям, а не по догадкам.** Под → сервис → ingress → DNS → нода → кластер.
   Каждый шаг либо отсекает половину вариантов, либо подтверждает гипотезу.
3. **Фиксируй, что видел.** Скопируй события и логи до того, как под пересоздастся:
   через минуту `--previous` уже не покажет нужное.

---

## 💼 Как это в DevOps

- Этот алгоритм — то, что реально проверяют на собеседовании в формате
  «приложение не работает, твои действия». Отвечать надо по слоям.
- Заведи себе файл «инциденты»: симптом → что оказалось → как чинил.
  Через полгода это твоя самая ценная шпаргалка.
- Большинство инцидентов повторяются: OOM, забытая readiness, метки Service,
  DNS, кончившееся место на ноде, просроченные сертификаты.
- Логи стоит собирать централизованно (Loki/EFK): после пересоздания пода
  локальные логи недоступны.
- Алерты полезнее ручного мониторинга: рестарты подов, `Pending` дольше N минут,
  `NotReady` ноды, заполнение томов, срок сертификатов.

---

## 🧠 Что запомнить

1. Три команды: `get pods -o wide`, `describe pod`, `logs [--previous]`;
   четвёртая — `get events`.
2. `Pending` — это всегда планировщик: ресурсы, метки, taint'ы, тома.
3. `CrashLoopBackOff` разбирается через `logs --previous` и `Last State`.
4. 137 + OOMKilled — память; 143 — штатный SIGTERM; 126/127 — проблема с командой.
5. `READY 0/1` при `Running` — readiness, а не падение.
6. Сервис не отвечает → первым делом `kubectl get endpoints`.
7. Таймаут ≠ отказ соединения: первое чаще про политику/сеть, второе — про порт.
8. Нода `NotReady` → Conditions, логи kubelet, место на диске, runtime, CNI.
9. Падение control plane не останавливает работающие поды.
10. `kubectl debug` спасает, когда в образе нет shell.
11. Сначала восстановление, потом расследование.
12. Записывай инциденты — это лучший материал и для работы, и для собеса.

---

## Задачи

> Эта тема тренируется только практикой: **ломай сам и чини сам**.
> Блок C — 12 поломок, которые нужно устроить намеренно и разобрать по алгоритму.

---

### Блок A. Теория

**A1.** Назови три команды, с которых начинается любой разбор.

<details><summary>Ответ</summary>

`kubectl get pods -o wide`, `kubectl describe pod`, `kubectl logs [--previous]`.

</details>

**A2.** Почему `kubectl get events` часто полезнее логов?

<details><summary>Ответ</summary>

События пишут все компоненты — планировщик, kubelet, контроллеры,
и они объясняют, почему объект не дошёл до нужного состояния, даже если
приложение не успело ничего залогировать.

</details>

**A3.** ⭐ Что означает статус `Pending` и какие пять причин бывают?

<details><summary>Ответ</summary>

Под принят, но не запущен: нехватка ресурсов по requests, нет нод
с нужными метками, непротолерированные taint'ы, невозможность привязать PVC,
нода в cordon/unschedulable.

</details>

**A4.** Как отличить «под не влезает по ресурсам» от «нет подходящих нод по меткам»?

<details><summary>Ответ</summary>

По тексту события: `Insufficient cpu/memory` против
`didn't match Pod's node affinity/selector`.

</details>

**A5.** Что означает `ContainerCreating` дольше минуты?

<details><summary>Ответ</summary>

Проблема на этапе подготовки: не монтируется том, не выдаётся IP (CNI),
долго качается образ, отсутствует ConfigMap/Secret.

</details>

**A6.** Чем `ImagePullBackOff` отличается от `ErrImagePull`?

<details><summary>Ответ</summary>

`ErrImagePull` — конкретная неудачная попытка; `ImagePullBackOff` —
переход к повторам с задержкой после нескольких неудач.

</details>

**A7.** Что означает `CreateContainerConfigError`?

<details><summary>Ответ</summary>

Не удаётся создать контейнер из-за конфигурации: нет ConfigMap/Secret
или нужного ключа в них.

</details>

**A8.** ⭐ Как разбирать `CrashLoopBackOff`?

<details><summary>Ответ</summary>

`kubectl logs --previous`, затем `describe` → `Last State` (Exit Code,
Reason), затем проверка команды, конфигов, зависимостей и проб.

</details>

**A9.** Что означают коды 137, 143, 126, 127?

<details><summary>Ответ</summary>

137 — SIGKILL (чаще OOMKilled или истёк grace period);
143 — SIGTERM; 126 — команда не исполняема; 127 — команда не найдена.

</details>

**A10.** Как отличить OOMKilled от убийства по liveness-пробе?

<details><summary>Ответ</summary>

При OOM в `Last State` будет `Reason: OOMKilled`; при liveness —
событие `Unhealthy: Liveness probe failed` и `Killing` в описании пода.

</details>

**A11.** Что означает `READY 0/1` при статусе `Running`?

<details><summary>Ответ</summary>

Контейнер работает, но не прошёл readiness: трафик через Service
на него не идёт.

</details>

**A12.** Что такое `Evicted` и кто принимает это решение?

<details><summary>Ответ</summary>

Под вытеснен kubelet'ом из-за нехватки ресурсов ноды
(память, диск, inodes, PID).

</details>

**A13.** ⭐ Назови алгоритм разбора «сервис не отвечает» по шагам.

<details><summary>Ответ</summary>

Endpoints → прямой запрос к IP пода → запрос к ClusterIP →
проверка DNS → NetworkPolicy → проверка снаружи (Ingress), плюс сравнение
поведения с разных нод.

</details>

**A14.** Чем таймаут отличается от `connection refused` по смыслу?

<details><summary>Ответ</summary>

Таймаут — пакеты не доходят (политика, неверный порт, сеть);
`connection refused` — адрес достижим, но никто не слушает (нет endpoints,
не тот порт, приложение слушает localhost).

</details>

**A15.** Что проверить, если приложение доступно по IP, но не по имени?

<details><summary>Ответ</summary>

CoreDNS (поды, логи), `/etc/resolv.conf` пода, `ndots`, правильность
имени и namespace.

</details>

**A16.** Какие Conditions бывают у ноды и что означает каждое?

<details><summary>Ответ</summary>

`Ready` (готовность ноды), `MemoryPressure`, `DiskPressure`,
`PIDPressure`, `NetworkUnavailable`.

</details>

**A17.** Назови пять причин `NotReady` у ноды.

<details><summary>Ответ</summary>

Упал kubelet; упал container runtime; кончилось место на диске;
сломался CNI; потеряна связь с API server; истекли сертификаты kubelet.

</details>

**A18.** Что продолжает работать при падении control plane?

<details><summary>Ответ</summary>

Уже запущенные контейнеры и сетевой трафик через Service:
правила ядра уже настроены, kubelet продолжает следить за подами локально.

</details>

**A19.** Как понять, что проблема в etcd?

<details><summary>Ответ</summary>

API отвечает медленно или ошибками записи, в логах apiserver ошибки
работы с etcd, `etcdctl endpoint health/status` показывает проблемы,
характерные сообщения про размер базы или кворум.

</details>

**A20.** Что делает `kubectl debug` и когда он незаменим?

<details><summary>Ответ</summary>

Запускает эфемерный контейнер в существующем поде (или копию пода,
или под на ноде). Незаменим для образов без shell и утилит (distroless).

</details>

**A21.** Как посмотреть логи всех подов приложения сразу?

<details><summary>Ответ</summary>

`kubectl logs -f -l app=web --all-containers --max-log-requests=10`
или утилитой `stern`.

</details>

**A22.** Почему логи нужно собирать централизованно?

<details><summary>Ответ</summary>

После пересоздания пода его логи недоступны: `--previous` хранит
только последний завершённый экземпляр.

</details>

**A23.** ⭐ Какие три правила разбора инцидента?

<details><summary>Ответ</summary>

Сначала восстановить сервис; идти по слоям, а не по догадкам;
фиксировать наблюдения до того, как объекты пересоздадутся.

</details>

**A24.** Почему «сначала восстановить, потом разбираться» — правильный порядок?

<details><summary>Ответ</summary>

Задача дежурного — минимизировать время недоступности; причины
можно искать по сохранённым логам и событиям уже после восстановления.

</details>

**A25.** Какие алерты стоит настроить, чтобы не разбирать инциденты вручную?

<details><summary>Ответ</summary>

Рестарты подов и `CrashLoopBackOff`; `Pending` дольше N минут;
`NotReady` ноды; заполнение дисков и томов; истечение сертификатов;
отсутствие успешных CronJob; рост 5xx и времени ответа; отсутствие
свободных ресурсов в кластере.

</details>

---

### Блок B. «Что произойдёт»

```bash
# B1
kubectl get pods
# app-xxx  0/1  Pending  0  15m
kubectl describe pod app-xxx | tail -3
# Warning  FailedScheduling  0/3 nodes are available: 3 Insufficient memory.
```
Вопрос: что менять и где?

<details><summary>Ответ</summary>

Не хватает памяти под `requests`: уменьшить `requests.memory`,
освободить место на нодах или добавить ноды.

</details>

```bash
# B2
# app-xxx  0/1  CrashLoopBackOff  8 (1m ago)
kubectl logs app-xxx
# Error from server (BadRequest): container "app" in pod "app-xxx" is waiting to start
```
Вопрос: какой командой получить логи?

<details><summary>Ответ</summary>

`kubectl logs app-xxx --previous`.

</details>

```bash
# B3
kubectl describe pod app | grep -A4 "Last State"
#   Last State:  Terminated
#     Reason:    Error
#     Exit Code: 143
```
Вопрос: что произошло?

<details><summary>Ответ</summary>

Контейнер был штатно остановлен сигналом SIGTERM (например, вытеснение,
завершение пода, рестарт по liveness с корректным завершением).

</details>

```bash
# B4
kubectl describe pod app | grep -i unhealthy
#   Warning  Unhealthy  Liveness probe failed: HTTP probe failed with statuscode: 500
```
Вопрос: почему под перезапускается и что чинить?

<details><summary>Ответ</summary>

Liveness-проба получает 500 и kubelet перезапускает контейнер.
Чинить нужно приложение или саму пробу (путь, таймауты, отделение
проверки зависимостей в readiness).

</details>

```bash
# B5
kubectl get endpoints web
# web   <none>
kubectl get pods -l app=web
# web-xxx  1/1  Running
```
Вопрос: причина?

<details><summary>Ответ</summary>

Селектор сервиса не совпадает с метками подов (или под не готов —
но здесь он `1/1`, значит дело в метках).

</details>

```bash
# B6
curl http://myapp.local/
# 503 Service Temporarily Unavailable
```
Вопрос: где искать, если отвечает ingress-nginx?

<details><summary>Ответ</summary>

503 означает отсутствие endpoints у бэкенд-сервиса:
проверить сервис, метки и readiness подов.

</details>

```bash
# B7
kubectl get nodes
# worker-2  NotReady  <none>  30d  v1.31.0
```
Вопрос: три первых проверки?

<details><summary>Ответ</summary>

`kubectl describe node` (Conditions), логи kubelet на ноде,
свободное место и состояние container runtime.

</details>

```bash
# B8
kubectl get pods
# The connection to the server 10.0.0.10:6443 was refused
```
Вопрос: работает ли сейчас приложение? Что проверить?

<details><summary>Ответ</summary>

Приложение, скорее всего, продолжает работать — недоступен API server.
Проверить контекст kubeconfig, сеть/VPN, состояние control plane и сертификаты.

</details>

```bash
# B9
kubectl get events -A --field-selector reason=Evicted
# 12 подов Evicted на worker-3
```
Вопрос: что происходит на ноде?

<details><summary>Ответ</summary>

На ноде нехватка ресурсов (память или диск): смотреть Conditions ноды,
`df -h`, логи kubelet и потребление подов.

</details>

---

### Блок C. Практика: ломай и чини

> Для каждой поломки: устрой её, разберись **по алгоритму**, запиши в свой файл
> «инциденты»: симптом → первая команда → причина → лечение → как предотвратить.
> Засекай время — это отличная тренировка перед собесом.

#### C1. 🔑 Pending из-за ресурсов
Поставь `requests.cpu: 8`. Найди сообщение планировщика, почини.

#### C2. Pending из-за меток
Поставь `nodeSelector: {disktype: nvme}` без такой метки на нодах.

#### C3. Pending из-за taint
Навесь taint на все ноды и запусти под без toleration.

#### C4. 🔑 ImagePullBackOff
Укажи несуществующий тег. Найди точное сообщение в событиях.

#### C5. CreateContainerConfigError
Сошлись на несуществующий Secret в `envFrom`.

#### C6. 🔑 CrashLoopBackOff
Запусти контейнер с `command: ["sh","-c","echo boom; exit 1"]`.
Получи логи предыдущего запуска и Exit Code.

#### C7. 🔑 OOMKilled
`limits.memory: 32Mi` и приложение, потребляющее больше. Найди `Reason: OOMKilled`.

#### C8. Liveness убивает нормальное приложение
Поставь `livenessProbe` на несуществующий путь. Отличи это от настоящего падения.

#### C9. 🔑 Сервис без endpoints
Сломай метку в селекторе сервиса. Пройди все четыре шага алгоритма
и зафиксируй, на каком шаге стало ясно.

<details><summary>Ответ</summary>

Становится ясно на первом же шаге: `kubectl get endpoints` пуст.

</details>

#### C10. Неверный targetPort
Поставь `targetPort: 8081` при приложении на 8080. Сравни симптом с C9
(таймаут или отказ?).

<details><summary>Ответ</summary>

Неверный `targetPort` обычно даёт таймаут либо отказ в зависимости
от того, слушает ли кто-то этот порт; главное отличие от C9 — endpoints
при этом **не пусты**.

</details>

#### C11. Приложение на 127.0.0.1
Запусти `python3 -m http.server --bind 127.0.0.1 8080` в поде и обратись
через сервис. Найди проблему через `ss -tlnp` внутри пода.

#### C12. 🔑 DNS
Масштабируй CoreDNS в 0. Проверь обращение по имени и по ClusterIP.
Верни обратно.

<details><summary>Ответ</summary>

По имени — ошибка резолва, по ClusterIP — работает: классическая
картина «упал DNS».

</details>

#### C13. kube-proxy
Временно убери kube-proxy с одной ноды (через `nodeSelector` в DaemonSet)
и сравни поведение подов на разных нодах.

#### C14. NetworkPolicy
Примени default-deny без разрешения DNS. Разбери симптом, как будто не знаешь причину.

#### C15. 🔑 Нода NotReady
Останови kubelet на worker-ноде (`docker exec ... systemctl stop kubelet`).
Замерь тайминги: NotReady, переезд подов. Восстанови.

<details><summary>Ответ</summary>

Ориентиры: `NotReady` примерно через 40 секунд, вытеснение подов —
примерно через 5 минут после этого.

</details>

#### C16. DiskPressure (со звёздочкой)
Забей диск ноды большим файлом (например, `fallocate`) и посмотри,
как появляются Conditions и вытеснение подов. Освободи место.

#### C17. kubectl debug
Возьми образ без shell (distroless или `gcr.io/distroless/static`)
и подключись к поду эфемерным контейнером netshoot.

#### C18. 🔑 Слепой тест
Попроси коллегу (или напиши скрипт, выбирающий случайную поломку из списка выше)
сломать что-то в твоём кластере. Найди причину по алгоритму и засеки время.

---

### Блок D. Инциденты (разбор без кластера)

**D1.** Приложение отвечает 502 через Ingress. Опиши все проверки по порядку.

<details><summary>Ответ</summary>

Логи ingress-контроллера → правило Ingress (host, path, класс) →
Service (`get endpoints`, `targetPort`) → под (readiness, логи) →
NetworkPolicy → наконец само приложение.

</details>

**D2.** После деплоя половина запросов падает, половина работает.
Какие гипотезы и как проверить каждую?

<details><summary>Ответ</summary>

Часть подов новой версии сломана; часть подов не прошла readiness,
но осталась в балансировке из-за её отсутствия; проблема на одной ноде;
несовместимость версий при выкатке. Проверять по подам и по нодам,
сравнивая ответы.

</details>

**D3.** Ночью приложение перезапустилось 40 раз, утром работает нормально.
Где искать следы?

<details><summary>Ответ</summary>

События (они хранятся около часа — поэтому лучше алерты и Prometheus),
метрики рестартов, централизованные логи, `describe` с `Last State`,
метрики потребления памяти.

</details>

**D4.** Разработчик жалуется: «в кубере всё тормозит». Как перевести это
в проверяемые гипотезы?

<details><summary>Ответ</summary>

Уточнить: что именно, откуда, когда началось. Проверить CPU throttling,
задержки DNS, время ответа зависимостей, состояние нод, сетевые потери,
загрузку дисков.

</details>

**D5.** Кластер не даёт создавать поды: «exceeded quota». Что проверить?

<details><summary>Ответ</summary>

`kubectl describe quota -n NS` и `kubectl get resourcequota`;
проверить, заданы ли requests/limits (при наличии квоты они обязательны),
и не исчерпан ли лимит на число объектов.

</details>

**D6.** После обновления кластера часть манифестов перестала применяться.
Что случилось и как проверять заранее?

<details><summary>Ответ</summary>

Удалены устаревшие версии API. Проверять заранее утилитами
(`kubent`, `pluto`), читать release notes и тестировать на staging.

</details>

**D7.** Под работает, но не видит переменных окружения из ConfigMap.

<details><summary>Ответ</summary>

Переменные из ConfigMap читаются при старте: под создан до изменения
конфигурации. Нужен `rollout restart` или checksum-аннотация;
также проверить имя ConfigMap и namespace.

</details>

**D8.** Сервис доступен из одного namespace и недоступен из другого.

<details><summary>Ответ</summary>

Обращение по короткому имени вместо `svc.namespace`; NetworkPolicy;
сервис действительно существует только в одном namespace.

</details>

**D9.** На одной ноде из пяти приложение работает медленнее. Гипотезы?

<details><summary>Ответ</summary>

Перегруженная нода (соседи), CPU throttling, проблемы с диском,
другой тип инстанса, сетевые потери, локальный том вместо сетевого.

</details>

**D10.** `kubectl` отвечает `Unable to connect to the server`, коллеги работают.
Что проверить у себя?

<details><summary>Ответ</summary>

Свой kubeconfig и контекст, VPN, часы (сертификаты), права,
доступность endpoint'а API с твоей машины.

</details>

**D11.** PVC привязался, под запустился, но каталог пуст. Что произошло?

<details><summary>Ответ</summary>

Смонтирован новый пустой том (новый PVC или другой StorageClass),
данные лежат в другом каталоге, либо `subPath` указывает не туда.

</details>

**D12.** Всё «легло» ровно в полночь. Три версии происходящего.

<details><summary>Ответ</summary>

Сработал CronJob (бэкап, очистка), закончилось место из-за ротации логов,
истёк срок сертификата или токена, сменился день в расписании автоскейлинга.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Приложение не работает в кубере. Твои действия по шагам?

<details><summary>Ответ</summary>

По слоям: под (статус, события, логи) → сервис (endpoints, порты) →
ingress → DNS → сеть и политики → нода → кластер. Сначала восстановление,
потом разбор.

</details>

**2.** Под в Pending — что проверишь?

<details><summary>Ответ</summary>

События планировщика: ресурсы, метки, taint'ы, тома, состояние нод.

</details>

**3.** Под в CrashLoopBackOff — как разбираешь?

<details><summary>Ответ</summary>

`logs --previous`, Exit Code и Reason, затем команда, конфиги, зависимости, пробы.

</details>

**4.** Как понять, что под убит по OOM?

<details><summary>Ответ</summary>

`Reason: OOMKilled` и Exit Code 137 в `Last State`.

</details>

**5.** Сервис не отвечает — алгоритм?

<details><summary>Ответ</summary>

Endpoints → IP пода → ClusterIP → DNS → NetworkPolicy → внешний вход.

</details>

**6.** Нода NotReady — что делаешь?

<details><summary>Ответ</summary>

Conditions ноды, логи kubelet, место на диске, состояние runtime и CNI;
при необходимости `drain` и обслуживание.

</details>

**7.** Как отлаживать под без shell в образе?

<details><summary>Ответ</summary>

`kubectl debug` с эфемерным контейнером (netshoot/busybox) и `--target`.

</details>

**8.** Что делать, если упал control plane?

<details><summary>Ответ</summary>

Оценить, идёт ли трафик; проверить API server, etcd, сертификаты, диски;
восстанавливать control plane, не трогая рабочие нагрузки.

</details>

**9.** Как посмотреть логи упавшего контейнера?

<details><summary>Ответ</summary>

`kubectl logs POD --previous` (при нескольких контейнерах — с `-c`).

</details>

**10.** Какие алерты обязательны для кластера?

<details><summary>Ответ</summary>

Рестарты и CrashLoop, Pending, NotReady ноды, заполнение дисков и томов,
сертификаты, ошибки 5xx и задержки, неуспешные Job, свободные ресурсы кластера.

</details>

---

### 🎯 Чек-лист

- [ ] Знаю алгоритм «под не стартует» и все типовые сообщения планировщика
- [ ] Разбираю CrashLoopBackOff через `--previous` и `Last State`
- [ ] Отличаю OOMKilled от убийства по liveness
- [ ] ⭐ Знаю алгоритм «сервис не отвечает» наизусть
- [ ] Понимаю разницу между таймаутом и отказом соединения
- [ ] Разбирал `NotReady` ноду и знаю тайминги
- [ ] Пользуюсь `kubectl debug` и netshoot
- [ ] Устроил и починил минимум 10 поломок из блока C
- [ ] Веду файл «инциденты» с симптомами и решениями
- [ ] Могу ответить на собесе «приложение не работает — твои действия»
