---
title: "09. Проверки (probes) и ресурсы"
description: "liveness/readiness/startup пробы, requests и limits, QoS-классы, LimitRange и ResourceQuota"
---

# 09. Проверки (probes) и ресурсы

> Роадмап → Практика: «**Поиграть с проверками** — добавить liveness и readiness probe.
> Сломать readiness — убедиться, что под выпадает из Service, но **не рестартует**.
> Сломать liveness — увидеть **рестарт**».
> **После темы ты умеешь:** настраивать проверки так, чтобы деплой был без ошибок,
> и объяснять разницу requests/limits и QoS-классы.

---

## 🗺️ Карта темы

```text:no-line-numbers
  ПРОВЕРКИ                                      РЕСУРСЫ
  ─────────────────────────────────────         ──────────────────────────────
  startupProbe   «приложение ещё стартует?»     requests — СКОЛЬКО ГАРАНТИРОВАНО
      │ пока идёт — остальные отключены                  (по ним планирует scheduler)
      ▼                                          limits  — ПОТОЛОК
  livenessProbe  «жив ли процесс?»                       CPU  → throttling
      │ провал → РЕСТАРТ контейнера                      RAM  → OOMKilled (137)
      ▼
  readinessProbe «готов принимать трафик?»       QoS: Guaranteed > Burstable > BestEffort
        провал → под ВЫПАДАЕТ ИЗ SERVICE                 (порядок вытеснения — обратный)
        рестарта НЕТ
```

---

## 1. Три вида проб ⭐

| Проба | Вопрос | Что делает при провале | Когда нужна |
|-------|--------|------------------------|-------------|
| **livenessProbe** | Процесс жив и не завис? | **Перезапускает контейнер** | Если приложение умеет «залипать» (deadlock, зависший event loop) |
| **readinessProbe** | Готов принимать запросы? | **Убирает под из Endpoints** (трафик не идёт), контейнер НЕ трогает | Практически всегда |
| **startupProbe** | Стартап завершён? | Перезапускает контейнер по исчерпании попыток; пока идёт — liveness и readiness не выполняются | Для медленно стартующих приложений (Java, миграции) |

> 🎤 **Вопрос собеса «в чём разница между liveness и readiness»:**
> liveness лечит зависание рестартом, readiness управляет трафиком.
> Сломанная readiness = под жив, но исключён из балансировки;
> сломанная liveness = бесконечные рестарты.

---

## 2. Способы проверки

```yaml
# HTTP — самый частый
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
    httpHeaders:
      - { name: X-Probe, value: kubelet }

# TCP — если HTTP нет
readinessProbe:
  tcpSocket: { port: 5432 }

# Exec — произвольная команда (дороже: запускает процесс в контейнере)
livenessProbe:
  exec:
    command: ["sh", "-c", "pg_isready -U postgres"]

# gRPC — для gRPC-сервисов со стандартным health-протоколом
readinessProbe:
  grpc: { port: 9000 }
```

Успех HTTP-пробы — код ответа **200-399**.

### Параметры (одинаковы для всех проб)

| Параметр | По умолчанию | Смысл |
|----------|--------------|-------|
| `initialDelaySeconds` | 0 | Пауза перед первой проверкой |
| `periodSeconds` | 10 | Как часто проверять |
| `timeoutSeconds` | 1 | ⚠️ Таймаут одной проверки — часто слишком мал |
| `successThreshold` | 1 | Сколько успехов подряд для «здоров» (для liveness всегда 1) |
| `failureThreshold` | 3 | Сколько провалов подряд до реакции |
| `terminationGracePeriodSeconds` | из пода | Может переопределяться на уровне liveness-пробы |

**Сколько времени до реакции:** `initialDelaySeconds + periodSeconds × failureThreshold`.
Например, `10 + 10 × 3 = 40` секунд до рестарта.

---

## 3. Рабочий пример

```yaml
spec:
  containers:
    - name: app
      image: myapp:1.5
      ports: [{ containerPort: 8080 }]

      startupProbe:                  # даём до 5 минут на старт
        httpGet: { path: /healthz, port: 8080 }
        periodSeconds: 5
        failureThreshold: 60         # 5 × 60 = 300 секунд

      livenessProbe:                 # редко и мягко
        httpGet: { path: /healthz, port: 8080 }
        periodSeconds: 20
        timeoutSeconds: 3
        failureThreshold: 3

      readinessProbe:                # часто и строго
        httpGet: { path: /ready, port: 8080 }
        periodSeconds: 5
        timeoutSeconds: 2
        failureThreshold: 2
```

### Что должны отвечать эндпоинты ⭐

| Эндпоинт | Проверяет | НЕ проверяет |
|----------|-----------|--------------|
| `/healthz` (liveness) | только что процесс жив и не завис | зависимости! |
| `/ready` (readiness) | готовность обслуживать: соединение с БД, прогрев кэша, очередь | — |

> ⚠️ **Классическая ошибка:** liveness-проба ходит в базу. База недоступна →
> liveness падает → кубер перезапускает **все** поды приложения → нагрузка на базу растёт
> при старте → каскадный отказ. Зависимости проверяет **readiness**, не liveness.

---

## 4. Probes и rolling update

Без `readinessProbe` Deployment считает под доступным сразу после старта контейнера
и гасит старый — получается окно 502.
С `readinessProbe` замена идёт только после реальной готовности.

Проверить своими глазами (это и есть практика роадмапа):

```bash
# ломаем readiness внутри пода
kubectl exec -it web-xxx -- rm /usr/share/nginx/html/ready
kubectl get pod web-xxx          # READY 0/1, STATUS Running, RESTARTS 0
kubectl get endpoints web        # адрес пода ИСЧЕЗ из списка

# ломаем liveness
kubectl exec -it web-xxx -- rm /usr/share/nginx/html/healthz
kubectl get pod web-xxx -w       # RESTARTS растёт
kubectl describe pod web-xxx     # событие Unhealthy + Killing
```

---

## 5. requests и limits ⭐

```yaml
resources:
  requests:                   # ГАРАНТИЯ: по этим числам scheduler выбирает ноду
    cpu: 100m                 # 100 millicores = 0.1 ядра
    memory: 128Mi
  limits:                     # ПОТОЛОК
    cpu: 500m
    memory: 256Mi
```

| | CPU | Memory |
|---|---|---|
| Тип ресурса | сжимаемый (compressible) | несжимаемый |
| Превышение `limits` | **throttling** — процесс притормаживают | **OOMKilled**, код 137 |
| Превышение `requests` | можно, если на ноде есть свободное | можно, но при нехватке под вытеснят |
| Единицы | `1` = 1 ядро, `500m` = 0.5 ядра | `Mi`/`Gi` (степени 2), `M`/`G` (степени 10) |

**Главные следствия:**
1. `requests` влияет на **планирование**: сумма requests подов не может превышать
   Allocatable ноды. Именно поэтому под висит в `Pending`.
2. CPU-limit не убивает, но может сильно навредить: throttling даёт «необъяснимые»
   задержки. Для latency-чувствительных сервисов CPU-лимит иногда осознанно не ставят.
3. Memory-limit убивает контейнер немедленно при превышении.
4. Правило «на глаз»: requests = типичное потребление, limits = 2-4× requests
   для CPU и +30-50 % для памяти. Точные значения берут из метрик (VPA в режиме
   рекомендаций, `kubectl top`, Prometheus).

---

## 6. QoS-классы ⭐

Кубер сам присваивает поду класс — от него зависит порядок вытеснения при нехватке
ресурсов на ноде.

| Класс | Условие | Вытесняется |
|-------|---------|-------------|
| **Guaranteed** | `requests == limits` для **всех** контейнеров и по CPU, и по памяти | последним |
| **Burstable** | Есть requests, но они не равны limits | вторым |
| **BestEffort** | Нет ни requests, ни limits | **первым** |

```bash
kubectl get pod web -o jsonpath='{.status.qosClass}'
```

> 💡 Для критичных компонентов (БД, ingress-контроллер) ставят `Guaranteed`.
> Для фоновой обработки допустим `Burstable`. `BestEffort` в проде — плохая практика:
> такой под вылетит первым и без предупреждения.

---

## 7. Namespace-ограничения: LimitRange и ResourceQuota

```yaml
apiVersion: v1
kind: LimitRange
metadata: { name: defaults }
spec:
  limits:
    - type: Container
      default:            { cpu: 500m, memory: 256Mi }    # limits по умолчанию
      defaultRequest:     { cpu: 100m, memory: 128Mi }    # requests по умолчанию
      max:                { cpu: "2",  memory: 2Gi }
      min:                { cpu: 10m,  memory: 16Mi }
---
apiVersion: v1
kind: ResourceQuota
metadata: { name: team-quota }
spec:
  hard:
    requests.cpu: "10"
    requests.memory: 20Gi
    limits.cpu: "20"
    limits.memory: 40Gi
    pods: "50"
    persistentvolumeclaims: "10"
```

| Объект | Что делает |
|--------|------------|
| **LimitRange** | Значения по умолчанию и границы для **одного контейнера/пода** |
| **ResourceQuota** | Суммарный лимит на **весь namespace** |

⚠️ Если в namespace есть ResourceQuota по `requests`/`limits`, то под **без** указанных
ресурсов будет отклонён admission-контроллером. LimitRange решает это, подставляя значения
по умолчанию.

---

## 8. Диагностика ресурсов

```bash
kubectl top nodes
kubectl top pods -A --sort-by=memory
kubectl describe node worker-1 | grep -A12 "Allocated resources"
kubectl get pod web -o jsonpath='{.status.qosClass}'
kubectl describe pod web | grep -A5 "Last State"      # OOMKilled?
kubectl get events --field-selector reason=Evicted -A
```

| Симптом | Вероятная причина |
|---------|-------------------|
| `Pending` + `Insufficient cpu/memory` | Сумма `requests` не помещается ни на одну ноду |
| `OOMKilled`, код 137 | Превышен `limits.memory` |
| Медленные ответы без ошибок | CPU throttling из-за низкого `limits.cpu` |
| `Evicted` | Нехватка памяти/диска на ноде, под BestEffort или превысил requests |
| Нода `NotReady` с `DiskPressure` | Кончился эфемерный диск (логи, образы, `emptyDir`) |

---

## 💼 Как это в DevOps

- `readinessProbe` — обязательна для всего, что обслуживает трафик. `livenessProbe` —
  по необходимости и всегда мягче readiness.
- Первая правка в чужом манифесте при ревью: «где probes и ресурсы?»
- Инцидент «после релиза выросли задержки» очень часто оказывается CPU-throttling'ом
  из-за скопированного откуда-то `limits.cpu: 100m`.
- В namespace команд обязательно ставят LimitRange + ResourceQuota — иначе один
  забытый под без лимитов выносит ноду.
- Подбор ресурсов — не разовая задача: метрики смотрят через месяц после запуска
  и корректируют.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Убрать под из балансировки при проблеме | `readinessProbe` |
| Перезапустить зависший процесс | `livenessProbe` |
| Дать приложению долго стартовать | `startupProbe` с большим `failureThreshold` |
| Проверка по HTTP | `httpGet: {path, port}` (успех — 200-399) |
| Проверка по TCP | `tcpSocket: {port}` |
| Проверка командой | `exec: {command: [...]}` |
| Гарантировать ресурсы | `requests` = `limits` (QoS Guaranteed) |
| Узнать QoS-класс | `kubectl get pod X -o jsonpath='{.status.qosClass}'` |
| Понять, почему Pending | `kubectl describe pod` → `Insufficient ...` |
| Понять, почему рестарт | `describe` → `Last State: OOMKilled` / событие `Unhealthy` |
| Значения по умолчанию в namespace | `LimitRange` |
| Ограничить namespace целиком | `ResourceQuota` |
| Посмотреть потребление | `kubectl top pods/nodes` |

---

## 🧠 Что запомнить

1. ⭐ liveness → **рестарт контейнера**; readiness → **исключение из Service**, без рестарта.
2. startupProbe нужен медленно стартующим приложениям; пока он идёт, остальные пробы молчат.
3. Liveness **не должна** проверять внешние зависимости — иначе каскадный отказ.
4. Успех HTTP-пробы — код 200-399; `timeoutSeconds: 1` по умолчанию часто мал.
5. Время до реакции = `initialDelay + period × failureThreshold`.
6. Без `readinessProbe` RollingUpdate даёт окно 502.
7. `requests` — то, по чему планирует scheduler; `limits` — потолок.
8. Превышение CPU-лимита = throttling; превышение памяти = OOMKilled (137).
9. QoS: Guaranteed (`requests == limits`), Burstable, BestEffort; вытесняют в обратном порядке.
10. `Pending` с `Insufficient cpu` — это про `requests`, а не про фактическое потребление.
11. LimitRange задаёт значения по умолчанию, ResourceQuota ограничивает namespace целиком.
12. Практика роадмапа: сломать readiness (под выпал из Service, рестарта нет)
    и сломать liveness (рестарт) — сделать это руками обязательно.

---

## Задачи

> 🔑 Блок C содержит **практику роадмапа**: сломать readiness и убедиться,
> что под выпал из Service без рестарта; сломать liveness и увидеть рестарт.

---

### Блок A. Теория

**A1.** ⭐ Чем liveness-проба отличается от readiness-пробы?

<details><summary>Ответ</summary>

Liveness отвечает на вопрос «жив ли процесс» и при провале перезапускает
контейнер; readiness отвечает «готов ли принимать трафик» и при провале исключает
под из Endpoints, не трогая контейнер.

</details>

**A2.** Что произойдёт при провале readiness? А при провале liveness?

<details><summary>Ответ</summary>

Readiness: под остаётся `Running`, но `READY 0/1`, трафик через Service
не идёт, рестарта нет. Liveness: kubelet убивает контейнер и запускает заново,
счётчик `RESTARTS` растёт.

</details>

**A3.** Зачем нужна startupProbe и что происходит с другими пробами, пока она идёт?

<details><summary>Ответ</summary>

Для приложений с долгим стартом. Пока startupProbe не прошла успешно,
liveness и readiness не выполняются — это защищает от рестартов «не успел стартовать».

</details>

**A4.** Какие способы проверки бывают? Назови четыре.

<details><summary>Ответ</summary>

`httpGet`, `tcpSocket`, `exec`, `grpc`.

</details>

**A5.** Какой HTTP-код считается успехом пробы?

<details><summary>Ответ</summary>

Любой код от 200 до 399 включительно.

</details>

**A6.** Перечисли параметры пробы и значения по умолчанию.

<details><summary>Ответ</summary>

`initialDelaySeconds: 0`, `periodSeconds: 10`, `timeoutSeconds: 1`,
`successThreshold: 1`, `failureThreshold: 3`.

</details>

**A7.** Через сколько секунд контейнер перезапустится при
`initialDelaySeconds: 10, periodSeconds: 5, failureThreshold: 3`?

<details><summary>Ответ</summary>

Примерно через 10 + 5×3 = 25 секунд после старта контейнера.

</details>

**A8.** ⭐ Почему liveness не должна проверять базу данных?

<details><summary>Ответ</summary>

Потому что недоступность базы — не повод перезапускать приложение.
Рестарты всех реплик усилят нагрузку на восстанавливающуюся базу и вызовут
каскадный отказ. Зависимости — дело readiness.

</details>

**A9.** Что должен проверять `/healthz`, а что `/ready`?

<details><summary>Ответ</summary>

`/healthz` — жив ли процесс (простая проверка без внешних вызовов);
`/ready` — готов ли обслуживать: подключение к БД, прогретые кэши, наличие миграций.

</details>

**A10.** Почему `timeoutSeconds: 1` часто оказывается проблемой?

<details><summary>Ответ</summary>

Одна секунда — жёсткий лимит: под нагрузкой или при сборке мусора ответ
может задержаться, проба провалится и вызовет ненужный рестарт.

</details>

**A11.** ⭐ Как отсутствие readiness-пробы влияет на RollingUpdate?

<details><summary>Ответ</summary>

Без неё Deployment считает под готовым сразу после запуска контейнера
и гасит старую реплику раньше времени — появляется окно ошибок.

</details>

**A12.** Может ли `successThreshold` быть больше 1 у liveness-пробы?

<details><summary>Ответ</summary>

Нет, для liveness и startup `successThreshold` может быть только 1.

</details>

**A13.** ⭐ В чём разница между `requests` и `limits`?

<details><summary>Ответ</summary>

`requests` — гарантированный минимум, по которому планируется под;
`limits` — верхняя граница потребления.

</details>

**A14.** По каким значениям scheduler выбирает ноду?

<details><summary>Ответ</summary>

По `requests` (сумма requests подов на ноде против её Allocatable).

</details>

**A15.** Что означает `500m` CPU? А `1`?

<details><summary>Ответ</summary>

`500m` — половина ядра, `1` — одно ядро.

</details>

**A16.** Что произойдёт при превышении `limits.cpu`? А `limits.memory`?

<details><summary>Ответ</summary>

CPU: throttling (процесс притормаживают). Память: контейнер убивается
(`OOMKilled`, код 137).

</details>

**A17.** Чем `Mi` отличается от `M`?

<details><summary>Ответ</summary>

`Mi` — 2^20 байт (мебибайт), `M` — 10^6 байт (мегабайт). В кубере обычно
используют `Mi`/`Gi`.

</details>

**A18.** ⭐ Назови три QoS-класса и условия их получения.

<details><summary>Ответ</summary>

`Guaranteed` — у всех контейнеров requests равны limits по CPU и памяти;
`Burstable` — заданы requests (или limits), но равенства нет;
`BestEffort` — ресурсы не заданы вовсе.

</details>

**A19.** В каком порядке кубер вытесняет поды при нехватке памяти на ноде?

<details><summary>Ответ</summary>

Сначала BestEffort, затем Burstable (в первую очередь превысившие requests),
в последнюю очередь Guaranteed.

</details>

**A20.** Как узнать QoS-класс пода?

<details><summary>Ответ</summary>

`kubectl get pod NAME -o jsonpath='{.status.qosClass}'`.

</details>

**A21.** Что такое LimitRange и что такое ResourceQuota? В чём разница?

<details><summary>Ответ</summary>

LimitRange задаёт значения по умолчанию и допустимые границы для отдельных
контейнеров/подов в namespace; ResourceQuota ограничивает суммарное потребление
и количество объектов в namespace.

</details>

**A22.** Что произойдёт с подом без ресурсов в namespace, где есть ResourceQuota
по requests?

<details><summary>Ответ</summary>

Он будет отклонён при создании: admission-контроллер требует явных
requests/limits, если квота по ним задана. LimitRange решает это подстановкой значений.

</details>

**A23.** Почему под может быть `Pending`, хотя на ноде «памяти полно»?

<details><summary>Ответ</summary>

Планирование идёт по `requests`, а не по фактическому потреблению:
сумма requests уже занятых подов может не оставлять места, даже если реальная
загрузка низкая.

</details>

**A24.** Что такое CPU throttling и как он выглядит со стороны пользователя?

<details><summary>Ответ</summary>

Принудительное ограничение процессорного времени по CFS-квоте: приложение
не падает, но отвечает медленнее; видно по метрике `container_cpu_cfs_throttled_seconds`.

</details>

**A25.** Как подобрать значения requests и limits для нового приложения?

<details><summary>Ответ</summary>

Запустить под нагрузкой без жёстких лимитов в тестовой среде, снять метрики
(`kubectl top`, Prometheus, VPA в режиме рекомендаций), взять requests ≈ p50-p80
потребления, limits — с запасом к пику; пересматривать через месяц эксплуатации.

</details>

---

### Блок B. «Что произойдёт»

**B1.**
```yaml
livenessProbe:
  httpGet: { path: /health, port: 8080 }
  initialDelaySeconds: 1
  periodSeconds: 2
# приложение стартует 40 секунд
```
Вопрос: что произойдёт с подом?

<details><summary>Ответ</summary>

Проба начнёт стучаться через секунду, приложение ещё не отвечает,
после трёх провалов контейнер перезапустится — и так по кругу
(`CrashLoopBackOff` по вине пробы). Нужен startupProbe или больший `initialDelaySeconds`.

</details>

**B2.**
```yaml
livenessProbe:
  exec:
    command: ["sh","-c","curl -f http://postgres:5432 || exit 1"]
# база недоступна 5 минут
```
Вопрос: что случится со всеми репликами приложения?

<details><summary>Ответ</summary>

Все реплики будут перезапускаться, пока база недоступна: каскадный отказ
и дополнительная нагрузка на базу в момент восстановления.

</details>

**B3.**
```yaml
readinessProbe:
  httpGet: { path: /ready, port: 8080 }
  failureThreshold: 2
  periodSeconds: 5
# /ready начал отдавать 503
```
Вопрос: через сколько секунд под выпадет из Endpoints? Будет ли рестарт?

<details><summary>Ответ</summary>

Примерно через 10 секунд (2 провала × 5 секунд) адрес исчезнет
из Endpoints. Рестарта не будет.

</details>

**B4.**
```yaml
resources:
  requests: { cpu: 2, memory: 4Gi }
# в кластере три ноды по 2 CPU и 4Gi
```
Вопрос: запустится ли под?

<details><summary>Ответ</summary>

Нет: запрос 2 CPU и 4Gi не помещается на ноду, у которой часть ресурсов
уже занята системными подами; под останется `Pending` с `Insufficient cpu/memory`.

</details>

**B5.**
```yaml
resources:
  limits: { memory: 128Mi }
# приложение потребляет 200Mi
```
Вопрос: что произойдёт и какой будет Exit Code?

<details><summary>Ответ</summary>

Контейнер будет убит ядром: `OOMKilled`, Exit Code 137, затем рестарт
по `restartPolicy`.

</details>

**B6.**
```yaml
resources:
  requests: { cpu: 100m, memory: 128Mi }
  limits:   { cpu: 100m, memory: 128Mi }
```
Вопрос: какой QoS-класс у пода?

<details><summary>Ответ</summary>

`Guaranteed`.

</details>

**B7.**
```yaml
resources: {}
```
Вопрос: какой QoS-класс и чем это опасно?

<details><summary>Ответ</summary>

`BestEffort`: такой под первым вытеснят при нехватке ресурсов, и он может
«съесть» ноду, мешая соседям.

</details>

**B8.**
```yaml
resources:
  limits: { cpu: 100m }
# приложение при старте компилирует шаблоны и хочет 1 CPU
```
Вопрос: что увидит пользователь?

<details><summary>Ответ</summary>

Долгий старт и возможные провалы проб: приложение упирается в 0.1 ядра
и стартует в разы дольше; со стороны — «приложение не поднимается».

</details>

**B9.**
```bash
kubectl get pod app
# app  0/1  Running  0  10m
kubectl get endpoints app-svc
# ENDPOINTS: <none>
```
Вопрос: что происходит и что чинить?

<details><summary>Ответ</summary>

Под не проходит readiness и исключён из Endpoints. Чинить: проверить путь
и порт пробы, реальную готовность приложения, таймауты и зависимости.

</details>

---

### Блок C. Практика

#### C1. 🔑 Добавить пробы *(практика роадмапа)*
Возьми Deployment из темы 05 и добавь liveness и readiness пробы по HTTP.
Для nginx удобно использовать файлы:
```bash
# внутри пода
echo ok > /usr/share/nginx/html/healthz
echo ok > /usr/share/nginx/html/ready
```
и пробы на `/healthz` и `/ready`.

#### C2. 🔑 Сломать readiness *(практика роадмапа)*
1. Удали файл `/usr/share/nginx/html/ready` в одном поде.
2. Смотри `kubectl get pods` — что стало с колонкой READY?
3. Смотри `kubectl get endpoints` — исчез ли адрес пода?
4. Проверь `RESTARTS` — изменился ли?
5. Верни файл и убедись, что под вернулся в Endpoints.
**Запиши вывод: под выпал из балансировки, но не перезапустился.**

<details><summary>Ответ</summary>

Ожидаемый результат: `READY 0/1`, `STATUS Running`, `RESTARTS 0`,
адрес пода исчез из `kubectl get endpoints`.

</details>

#### C3. 🔑 Сломать liveness *(практика роадмапа)*
1. Удали файл `/usr/share/nginx/html/healthz`.
2. Смотри `kubectl get pods -w` и `kubectl describe pod`.
3. Засеки, через сколько секунд произошёл рестарт, и сверь с формулой.
4. Найди событие `Unhealthy` и `Killing` в `describe`.

<details><summary>Ответ</summary>

Рестарт происходит примерно через `initialDelay + period × failureThreshold`
секунд; в событиях — `Unhealthy: Liveness probe failed` и `Killing`.

</details>

#### C4. Трафик во время сломанной readiness
Пока readiness сломана у одного из трёх подов, погоняй запросы в цикле
и убедись, что ни один не попал в «нездоровый» под (можно отдавать имя пода в ответе).

#### C5. startupProbe
Сделай приложение, которое «стартует» 60 секунд (`sleep 60 && touch /tmp/ready`).
1. Настрой только liveness с `initialDelaySeconds: 5` — получишь бесконечные рестарты.
2. Добавь startupProbe и убедись, что под спокойно дождался старта.
3. Сформулируй правило, когда нужен startupProbe.

<details><summary>Ответ</summary>

Правило: если время старта непредсказуемо или велико, ставь startupProbe
с большим `failureThreshold`, а liveness делай мягкой.

</details>

#### C6. Пробы и rolling update
1. Сделай образ, который отвечает на `/ready` только через 20 секунд после старта.
2. Выкати обновление **без** readiness-пробы, гоняя curl в цикле — посчитай ошибки.
3. Добавь readiness-пробу и повтори. Сравни числа.

#### C7. 🔑 requests и Pending
1. Поставь `requests.cpu: 4` (больше, чем есть на ноде).
2. Посмотри статус и событие `FailedScheduling`.
3. Посмотри `kubectl describe node` → `Allocated resources`.
4. Уменьши requests и убедись, что под запустился.

<details><summary>Ответ</summary>

Событие `FailedScheduling: 0/3 nodes are available: Insufficient cpu`.
В `describe node` видно, что запрошенные ресурсы превышают Allocatable.

</details>

#### C8. 🔑 OOMKilled
Запусти под с `limits.memory: 64Mi` и стресс-нагрузкой на 200Mi.
Найди в `describe` `Reason: OOMKilled` и Exit Code 137. Подними лимит и повтори.

#### C9. CPU throttling
1. Запусти нагрузочный под с `limits.cpu: 100m`.
2. Замерь время выполнения CPU-задачи внутри (например, подсчёт хешей).
3. Подними лимит до `1` и замерь снова.
4. Запиши разницу — это и есть throttling.

#### C10. QoS-классы
Создай три пода: без ресурсов, с requests < limits, с requests == limits.
Проверь `status.qosClass` у каждого. Запиши таблицу.

#### C11. Вытеснение (со звёздочкой)
На ноде с ограниченной памятью запусти BestEffort-под и Guaranteed-под,
затем создай давление на память. Посмотри, кого вытеснит первым
(`kubectl get events --field-selector reason=Evicted`).

#### C12. LimitRange
1. Создай namespace `limited` и LimitRange с `defaultRequest`/`default`.
2. Создай под **без** ресурсов.
3. Посмотри `kubectl get pod -o yaml` — откуда взялись ресурсы?

#### C13. ResourceQuota
1. Добавь ResourceQuota на 2 CPU и 2Gi в тот же namespace.
2. Попробуй создать Deployment на 5 реплик по 1 CPU.
3. Посмотри, что произойдёт и где будет видно ошибку
   (подсказка: `kubectl describe rs`, а не `describe pod`).

<details><summary>Ответ</summary>

Поды не создаются, ошибка видна в событиях ReplicaSet
(`exceeded quota: ...`), а не в подах — подов просто нет.

</details>

#### C14. Подбор ресурсов по метрикам (со звёздочкой)
Сними `kubectl top pods` за несколько минут нагрузки, посчитай пик и среднее,
предложи значения requests/limits и обоснуй их.

---

### Блок D. Инциденты

**D1.** После релиза приложение стало отвечать медленно, ошибок нет, CPU-графики
упираются в полку. Гипотеза и проверка.

<details><summary>Ответ</summary>

CPU throttling из-за `limits.cpu`. Проверить метрику
`container_cpu_cfs_throttled_periods`/`_seconds`, сравнить с лимитом,
поднять лимит или убрать его для latency-критичных сервисов.

</details>

**D2.** Все поды приложения одновременно ушли в рестарты, когда упала база. Почему?

<details><summary>Ответ</summary>

Liveness-проба проверяла доступность базы. Нужно перенести эту проверку
в readiness и оставить в liveness только признак «процесс жив».

</details>

**D3.** Под перезапускается каждые 40 секунд, в логах ничего подозрительного.
Куда смотреть?

<details><summary>Ответ</summary>

События пода: `Unhealthy` от liveness; либо `OOMKilled` в `Last State`.
Проверить пороги пробы, таймауты и потребление памяти.

</details>

**D4.** Поды приложения периодически `Evicted` ночью. Что происходит и как чинить?

<details><summary>Ответ</summary>

Нехватка памяти или места на диске ноды в часы пиков/ротации логов.
Задать корректные requests, повысить QoS до Guaranteed для важных подов,
ограничить `emptyDir`, настроить ротацию логов и мониторинг ноды.

</details>

**D5.** Приложение с Java стартует 90 секунд и постоянно рестартует. Что добавить?

<details><summary>Ответ</summary>

startupProbe с большим `failureThreshold` (или увеличить
`initialDelaySeconds` liveness), а также достаточный CPU-лимит на время старта.

</details>

**D6.** Во время деплоя пользователи получали 502, хотя `maxUnavailable: 0`.
Как связано с пробами?

<details><summary>Ответ</summary>

Readiness отвечает «готов» раньше, чем приложение реально готово,
либо её нет вовсе; плюс отсутствует `preStop`-пауза при завершении старых подов.

</details>

**D7.** Под `Running 0/1` уже час, приложение отвечает вручную через `port-forward`.
Где ошибка?

<details><summary>Ответ</summary>

Readiness-проба не проходит: неверный путь/порт, отвечает другой контейнер,
слишком строгий таймаут, приложение отдаёт 503 из-за зависимости.

</details>

**D8.** В namespace команда не может создать ни одного пода:
«exceeded quota». Что проверить и что объяснить команде?

<details><summary>Ответ</summary>

`kubectl describe quota -n NS` и `kubectl get resourcequota`: команда упёрлась
в лимит namespace. Объяснить, что суммарные requests всех подов ограничены,
и либо оптимизировать ресурсы, либо запрашивать увеличение квоты.

</details>

**D9.** Под `Pending`, при этом `kubectl top nodes` показывает 30 % загрузки.
Объясни противоречие.

<details><summary>Ответ</summary>

`top` показывает фактическое потребление, а планирование идёт по requests.
Ноды «заняты» обещаниями, а не реальной нагрузкой.

</details>

**D10.** После добавления `limits.memory` приложение стало падать чаще,
хотя раньше работало. Почему это ожидаемо и что делать?

<details><summary>Ответ</summary>

Раньше приложение потребляло больше лимита, но никто не ограничивал;
теперь ядро убивает его при превышении. Нужно измерить реальное потребление
и поставить адекватный лимит (или чинить утечку).

</details>

**D11.** Разработчик поставил liveness с `periodSeconds: 1` и `failureThreshold: 1`.
Чем это грозит?

<details><summary>Ответ</summary>

Любая секундная задержка (GC, пик нагрузки) вызовет рестарт рабочего
приложения; пробы должны быть терпимее, чем реакция человека.

</details>

**D12.** На ноде `DiskPressure`, поды вытесняются. Какие каталоги проверить?

<details><summary>Ответ</summary>

Логи контейнеров (`/var/log/pods`, `/var/lib/docker` или
`/var/lib/containerd`), неиспользуемые образы, `emptyDir` больших подов,
переполненные тома на ноде.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Чем отличаются liveness и readiness пробы?

<details><summary>Ответ</summary>

Liveness — перезапуск зависшего контейнера; readiness — управление трафиком
через включение и исключение пода из Endpoints.

</details>

**2.** Зачем нужен startupProbe?

<details><summary>Ответ</summary>

Чтобы дать приложению долго стартовать, не рискуя рестартами от liveness.

</details>

**3.** Что будет, если liveness-проба проверяет базу данных?

<details><summary>Ответ</summary>

При недоступности базы перезапустятся все реплики — каскадный отказ.
Зависимости проверяет readiness.

</details>

**4.** ⭐ Что такое requests и limits? Как они влияют на планирование?

<details><summary>Ответ</summary>

`requests` — гарантированные ресурсы и основа планирования;
`limits` — потолок потребления. Scheduler смотрит только на requests.

</details>

**5.** Что произойдёт при превышении лимита CPU и лимита памяти?

<details><summary>Ответ</summary>

CPU — throttling, приложение замедляется; память — OOMKilled с кодом 137.

</details>

**6.** Какие QoS-классы бывают и как они назначаются?

<details><summary>Ответ</summary>

Guaranteed (requests == limits у всех контейнеров), Burstable (есть requests,
но не равны limits), BestEffort (ничего не задано).

</details>

**7.** Кого вытеснят первым при нехватке памяти на ноде?

<details><summary>Ответ</summary>

BestEffort, затем Burstable, превысившие requests; Guaranteed — последними.

</details>

**8.** Что такое LimitRange и ResourceQuota?

<details><summary>Ответ</summary>

LimitRange — значения по умолчанию и границы на контейнер/под в namespace;
ResourceQuota — суммарные ограничения на namespace.

</details>

**9.** Почему под в Pending, если ресурсы на нодах свободны?

<details><summary>Ответ</summary>

Планирование идёт по сумме requests, а не по фактическому потреблению.

</details>

**10.** Как подобрать значения ресурсов для приложения?

<details><summary>Ответ</summary>

По метрикам под реальной нагрузкой: requests около типичного потребления,
limits с запасом к пику; корректировать после накопления статистики.

</details>

---

### 🎯 Чек-лист

- [ ] 🔑 Сломал readiness и убедился: под выпал из Service, рестарта нет
- [ ] 🔑 Сломал liveness и увидел рестарт с событием `Unhealthy`
- [ ] Считаю время реакции пробы по формуле
- [ ] Понимаю, почему liveness не проверяет зависимости
- [ ] Настроил startupProbe для медленного приложения
- [ ] Видел `Pending` из-за requests и `OOMKilled` из-за limits
- [ ] Знаю три QoS-класса и порядок вытеснения
- [ ] Пробовал LimitRange и ResourceQuota
- [ ] Умею объяснить CPU throttling и найти его в метриках
