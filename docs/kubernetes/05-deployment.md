---
title: "05. Deployment и ReplicaSet"
description: "RollingUpdate, откат, история ревизий, canary и blue-green на голых манифестах — конспект и задачи"
---

# 05. ⭐ Deployment и ReplicaSet

> Роадмап → 6. Kubernetes → Основные сущности → **Deployment**.
> Плюс практика роадмапа: «Обновить версию образа, посмотреть **RollingUpdate**
> в реальном времени. Сделать **откат**. Масштабировать до 5 реплик, потом до 1».
> **После темы ты умеешь:** катить и откатывать релизы, читать историю, объяснять
> стратегии обновления и то, откуда берутся ReplicaSet'ы со странными именами.

---

## 🗺️ Карта темы

```text:no-line-numbers
   Deployment  (что хочу: образ, 3 реплики, стратегия)
        │  управляет версиями
        ▼
   ReplicaSet v2  (текущий)          ReplicaSet v1  (старый, replicas=0)
        │  держит число реплик             │  хранится для ОТКАТА
        ▼                                  ▼
   Pod  Pod  Pod                        (подов нет)

   kubectl set image ──► новый RS ──► постепенная замена подов ──► старый RS в 0
   kubectl rollout undo ──────────────► возвращаем старый RS обратно
```

---

## 1. Зачем нужен Deployment

Под сам по себе не переживает падение ноды, не обновляется и не масштабируется.
ReplicaSet добавляет «держать N реплик». Deployment добавляет **управление версиями**:
плавное обновление, история и откат.

| Объект | Что умеет |
|--------|-----------|
| Pod | работать |
| ReplicaSet | держать N одинаковых подов |
| **Deployment** | менять версии подов без даунтайма + откатывать |

> В работе **ReplicaSet руками не создают** — его создаёт Deployment. Знать его нужно,
> чтобы понимать вывод `kubectl get rs` и механику обновления.

---

## 2. Манифест ⭐

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  labels:
    app: web
spec:
  replicas: 3
  revisionHistoryLimit: 5          # сколько старых ReplicaSet хранить для отката
  minReadySeconds: 5               # сколько под должен быть Ready, чтобы считаться «хорошим»
  progressDeadlineSeconds: 600     # через сколько выкатку признают провалившейся
  selector:
    matchLabels:
      app: web                     # ⭐ КАКИМИ подами управляем. Менять нельзя!
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1                  # сколько подов можно создать СВЕРХ replicas
      maxUnavailable: 0            # сколько можно вывести из строя одновременно
  template:                        # ⬇ ШАБЛОН ПОДА — обычная спека пода
    metadata:
      labels:
        app: web                   # ⭐ должно совпадать с selector
    spec:
      containers:
        - name: app
          image: myapp:1.4.2
          ports:
            - containerPort: 8080
          resources:
            requests: { cpu: 100m, memory: 128Mi }
            limits:   { cpu: 500m, memory: 256Mi }
          readinessProbe:          # ⭐ без неё RollingUpdate вслепую
            httpGet: { path: /ready, port: 8080 }
            initialDelaySeconds: 5
            periodSeconds: 5
```

**Три вещи, которые надо запомнить про манифест:**
1. `spec.selector.matchLabels` **иммутабельно** — поменять нельзя, только пересоздать Deployment.
2. Метки в `template.metadata.labels` обязаны попадать под селектор.
3. Всё, что внутри `template`, — это спека пода из темы 04.

---

## 3. Как работает RollingUpdate ⭐

Deployment `replicas: 3`, `maxSurge: 1`, `maxUnavailable: 0`:

```text:no-line-numbers
 старт     RS-v1: ███  (3 пода v1)         RS-v2: —
 шаг 1     RS-v1: ███                      RS-v2: ▒        создаём 1 новый (сверх 3 — это maxSurge)
 шаг 2     RS-v1: ███                      RS-v2: █        новый стал Ready
 шаг 3     RS-v1: ██                       RS-v2: █        гасим один старый
 шаг 4     RS-v1: ██                       RS-v2: █▒
 ...
 финал     RS-v1: —   (replicas=0, объект жив)   RS-v2: ███
```

| Параметр | Смысл | Типичные значения |
|----------|-------|-------------------|
| `maxSurge` | сколько подов можно поднять сверх `replicas` | `1` или `25%` |
| `maxUnavailable` | сколько подов может быть недоступно | `0` — без просадки мощности; `1`/`25%` — быстрее |
| `minReadySeconds` | пауза после Ready перед «зачётом» пода | `5-30` для нервных приложений |
| `progressDeadlineSeconds` | таймаут всей выкатки | `600` по умолчанию |

**Комбинации:**

| Настройка | Эффект |
|-----------|--------|
| `maxSurge: 1, maxUnavailable: 0` | Без потери мощности, нужен запас ресурсов. ⭐ Дефолт здравого смысла |
| `maxSurge: 0, maxUnavailable: 1` | Не требует лишних ресурсов, но мощность на время просаживается |
| `maxSurge: 25%, maxUnavailable: 25%` | Значение по умолчанию — быстро и умеренно |
| `strategy.type: Recreate` | Убить все старые → поднять новые. **Даунтайм**, но нужен, если две версии несовместимы (общий том RWO, миграции БД) |

> ⚠️ **Без `readinessProbe` RollingUpdate опасен:** кубер считает под «хорошим», как только
> контейнер запустился, и гасит старый. Если приложение стартует 20 секунд — получишь
> окно недоступности. Probe'ы — тема 09, но правило запомни здесь.

---

## 4. Команды выкатки ⭐

```bash
# обновить образ (три способа)
kubectl set image deployment/web app=myapp:1.5.0            # быстро, руками
kubectl apply -f deploy.yaml                                # ⭐ правильно: через git
kubectl edit deployment web                                 # для отладки

# наблюдать
kubectl rollout status deployment/web                       # ⭐ блокируется до конца выкатки
kubectl get pods -w
kubectl get rs -w                                           # видно, как перетекают реплики

# история
kubectl rollout history deployment/web
kubectl rollout history deployment/web --revision=3

# откат ⭐
kubectl rollout undo deployment/web                         # на предыдущую ревизию
kubectl rollout undo deployment/web --to-revision=2         # на конкретную

# пауза и продолжение (для канареечных проверок)
kubectl rollout pause deployment/web
kubectl rollout resume deployment/web

# перезапуск без изменения образа
kubectl rollout restart deployment/web

# масштабирование
kubectl scale deployment/web --replicas=5
kubectl scale deployment/web --replicas=1
```

**Про историю ревизий:** чтобы в `rollout history` была видна причина изменения,
принято добавлять аннотацию:
```bash
kubectl annotate deployment/web kubernetes.io/change-cause="image 1.5.0, ticket OPS-431"
```

---

## 5. Почему у ReplicaSet имя вида `web-7d8f9c5b4`

Суффикс — хеш от **шаблона пода** (`pod-template-hash`). Изменил что угодно в `template`
(образ, env, ресурсы, аннотацию) → новый хеш → новый ReplicaSet → выкатка.
Изменил `replicas` → хеш тот же → просто меняется число подов, **без** выкатки.

```bash
kubectl get rs -l app=web
# NAME             DESIRED   CURRENT   READY   AGE
# web-7d8f9c5b4    3         3         3       2m     ← текущий
# web-5c9b8d7f6    0         0         0       1h     ← прошлый, для отката
```

Именно из этих «нулевых» ReplicaSet и делается `rollout undo`.
Сколько их хранить — `revisionHistoryLimit` (по умолчанию 10).

---

## 6. Что делать, когда выкатка «зависла»

```bash
kubectl rollout status deployment/web
# Waiting for deployment "web" rollout to finish: 1 out of 3 new replicas have been updated...
```

Алгоритм:

```bash
kubectl get pods -l app=web            # какие поды новые и в каком они статусе
kubectl describe pod <новый-под>       # события: ImagePull? Pending? Unhealthy?
kubectl logs <новый-под>
kubectl describe deployment web        # Conditions: Progressing / Available
```

| Условие в `describe deployment` | Значение |
|---------------------------------|----------|
| `Progressing=True, reason=NewReplicaSetAvailable` | выкатка завершена успешно |
| `Progressing=False, reason=ProgressDeadlineExceeded` | не уложились в `progressDeadlineSeconds` |
| `Available=False` | доступных реплик меньше требуемого минимума |

Если выкатка встала — **откатываемся, а потом разбираемся**:
```bash
kubectl rollout undo deployment/web
```

> 💡 `maxUnavailable: 0` защищает от самой опасной ситуации: сломанный образ просто
> не пройдёт дальше первого пода, старые реплики останутся работать.

---

## 7. Ручной canary и blue-green на голых манифестах

Полноценные стратегии делают Argo Rollouts / Flagger / service mesh, но понимать
принцип надо, и на собесе это спрашивают.

**Canary «на коленке»:** два Deployment с общей меткой, которую ловит Service:
```yaml
# stable: replicas: 9, labels: app=web, track=stable, image 1.4
# canary: replicas: 1, labels: app=web, track=canary, image 1.5
# Service selector: app=web  → 10 % трафика уходит в canary
```

**Blue-green:** два полных комплекта (`version: blue` / `version: green`),
переключение — правкой `selector` у Service:
```bash
kubectl patch svc web -p '{"spec":{"selector":{"app":"web","version":"green"}}}'
```
Переключение мгновенное, откат — обратный patch. Цена — двойной расход ресурсов.

---

## 8. Полный рабочий пример (пригодится в лабах)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  labels: { app: web }
  annotations:
    kubernetes.io/change-cause: "initial deploy 1.25"
spec:
  replicas: 3
  revisionHistoryLimit: 5
  strategy:
    type: RollingUpdate
    rollingUpdate: { maxSurge: 1, maxUnavailable: 0 }
  selector:
    matchLabels: { app: web }
  template:
    metadata:
      labels: { app: web }
    spec:
      terminationGracePeriodSeconds: 30
      containers:
        - name: nginx
          image: nginx:1.25
          ports: [{ containerPort: 80 }]
          resources:
            requests: { cpu: 50m, memory: 64Mi }
            limits:   { cpu: 200m, memory: 128Mi }
          readinessProbe:
            httpGet: { path: /, port: 80 }
            periodSeconds: 3
          livenessProbe:
            httpGet: { path: /, port: 80 }
            initialDelaySeconds: 10
          lifecycle:
            preStop:
              exec: { command: ["sh","-c","sleep 5"] }
---
apiVersion: v1
kind: Service
metadata:
  name: web
spec:
  selector: { app: web }
  ports: [{ port: 80, targetPort: 80 }]
```

Сценарий из практики роадмапа целиком:
```bash
kubectl apply -f web.yaml
kubectl rollout status deploy/web

# 1. Обновляем версию и смотрим RollingUpdate в реальном времени
kubectl get pods -w &                     # в соседнем окне
kubectl set image deploy/web nginx=nginx:1.26 && kubectl rollout status deploy/web

# 2. Откат
kubectl rollout history deploy/web
kubectl rollout undo deploy/web
kubectl get pods -o jsonpath='{.items[*].spec.containers[0].image}'

# 3. Масштабирование
kubectl scale deploy/web --replicas=5 && kubectl get pods -o wide
kubectl scale deploy/web --replicas=1 && kubectl get pods
```

---

## 💼 Как это в DevOps

- Deployment — 90 % рабочих нагрузок в любом кластере. StatefulSet и DaemonSet — остальные 10 %.
- Пайплайн из блока CI/CD заканчивается ровно этим: `kubectl set image` / `helm upgrade` +
  `kubectl rollout status` с таймаутом. Ненулевой код `rollout status` — сигнал джобе упасть
  и откатиться.
- `revisionHistoryLimit` стоит уменьшать (3-5): десятки старых ReplicaSet мусорят в списках.
- `maxUnavailable: 0` — стандартная настройка для пользовательских сервисов;
  `Recreate` — для приложений с общим RWO-томом или несовместимыми схемами БД.
- Аннотация `change-cause` (или связь ревизии с коммитом) экономит время в 3 часа ночи.
- Важное следствие для миграций БД: во время RollingUpdate **одновременно живут две версии**
  приложения. Схема БД должна быть совместима с обеими (backward-compatible миграции).

---

## 📌 Шпаргалка

| Хочу | Команда |
|------|---------|
| Создать каркас | `kubectl create deploy web --image=nginx --dry-run=client -o yaml` |
| Обновить образ | `kubectl set image deploy/web app=img:tag` |
| Дождаться выкатки | `kubectl rollout status deploy/web` |
| История | `kubectl rollout history deploy/web` |
| Откат | `kubectl rollout undo deploy/web [--to-revision=N]` |
| Перезапуск подов | `kubectl rollout restart deploy/web` |
| Пауза/продолжить | `kubectl rollout pause|resume deploy/web` |
| Масштабировать | `kubectl scale deploy/web --replicas=N` |
| Посмотреть ReplicaSet'ы | `kubectl get rs -l app=web` |
| Почему не катится | `kubectl describe deploy web` → Conditions |
| Записать причину изменения | `kubectl annotate deploy/web kubernetes.io/change-cause="..."` |

---

## 🧠 Что запомнить

1. Deployment управляет ReplicaSet'ами, ReplicaSet управляет подами. Руками создают только Deployment.
2. `spec.selector` иммутабелен; метки шаблона должны ему соответствовать.
3. Новый ReplicaSet создаётся при любом изменении **шаблона пода**; изменение `replicas`
   выкатку не вызывает.
4. RollingUpdate управляется `maxSurge` и `maxUnavailable`; `maxUnavailable: 0` —
   безопасный дефолт.
5. `Recreate` = даунтайм, но нужен при несовместимых версиях или RWO-томе.
6. Без `readinessProbe` плавное обновление превращается в лотерею.
7. Старые ReplicaSet хранятся ради `rollout undo`; их количество — `revisionHistoryLimit`.
8. `kubectl rollout status` возвращает ненулевой код при провале — на этом строится
   проверка в пайплайне.
9. `rollout restart` перезапускает поды штатным rolling-способом.
10. Во время выкатки в кластере одновременно работают две версии приложения —
    учитывай это в миграциях и API.
11. `rollout undo` — первое действие при неудачном релизе; разбор — после.
12. Практика роадмапа — обновить образ, посмотреть RollingUpdate, откатиться,
    отмасштабировать 5 → 1 — должна выполняться «на автомате».

---

## Задачи

> 🔑 Блок C содержит **практику роадмапа целиком**: обновить образ, посмотреть
> RollingUpdate вживую, откатиться, отмасштабировать до 5 и обратно до 1.

---

### Блок A. Теория

**A1.** ⭐ Зачем нужен Deployment, если есть ReplicaSet?

<details><summary>Ответ</summary>

ReplicaSet умеет только держать N одинаковых подов. Deployment добавляет
управление версиями: создаёт новый ReplicaSet при изменении шаблона, плавно переводит
на него трафик, хранит историю и умеет откатывать.

</details>

**A2.** Кто создаёт ReplicaSet и кто создаёт поды?

<details><summary>Ответ</summary>

Deployment создаёт ReplicaSet; ReplicaSet создаёт поды.

</details>

**A3.** Почему ReplicaSet не создают руками?

<details><summary>Ответ</summary>

Он не умеет обновляться: смена образа в ReplicaSet не приведёт к плавной замене
подов и не даст отката. Это внутренний объект механики Deployment.

</details>

**A4.** Что означает суффикс в имени `web-7d8f9c5b4`?

<details><summary>Ответ</summary>

`pod-template-hash` — хеш шаблона пода. Он же добавляется меткой на поды,
чтобы ReplicaSet'ы разных версий не перепутали своих подов.

</details>

**A5.** ⭐ Какие изменения в Deployment вызывают новую выкатку, а какие нет?

<details><summary>Ответ</summary>

Новая выкатка — при любом изменении `spec.template` (образ, env, ресурсы,
метки, аннотации, probe'ы). Не вызывают выкатку: `replicas`, `revisionHistoryLimit`,
`strategy`, `minReadySeconds`, метаданные самого Deployment.

</details>

**A6.** Почему `spec.selector` нельзя изменить?

<details><summary>Ответ</summary>

Селектор определяет владение подами; его изменение оставило бы старые поды
без владельца и сломало бы связь с существующими ReplicaSet'ами. Поле иммутабельно
с версии apps/v1.

</details>

**A7.** Что произойдёт, если метки в `template` не совпадают с `selector`?

<details><summary>Ответ</summary>

Ошибка валидации: `selector does not match template labels` — объект не создастся.

</details>

**A8.** ⭐ Что такое `maxSurge` и `maxUnavailable`? Что означает пара `1/0`?

<details><summary>Ответ</summary>

`maxSurge` — сколько подов разрешено поднять сверх `replicas`;
`maxUnavailable` — сколько реплик может быть недоступно одновременно.
`1/0` означает: сначала поднимаем новый под, и только после его готовности гасим старый —
мощность не проседает.

</details>

**A9.** Какие значения `maxSurge`/`maxUnavailable` по умолчанию?

<details><summary>Ответ</summary>

По 25 % от `replicas` для обоих.

</details>

**A10.** Чем `RollingUpdate` отличается от `Recreate` и когда нужен `Recreate`?

<details><summary>Ответ</summary>

RollingUpdate заменяет поды постепенно (без даунтайма); Recreate сначала
удаляет все старые, затем создаёт новые (даунтайм). Recreate нужен при несовместимых
версиях, при общем томе с `ReadWriteOnce` и при миграциях, требующих монопольного доступа.

</details>

**A11.** Зачем нужен `minReadySeconds`?

<details><summary>Ответ</summary>

Задаёт, сколько секунд под должен быть Ready, прежде чем считаться доступным.
Защищает от «мигающих» подов, которые проходят probe и падают через секунду.

</details>

**A12.** Что делает `progressDeadlineSeconds` и что произойдёт по его истечении?

<details><summary>Ответ</summary>

Максимальное время без прогресса; по истечении Deployment получает
`Progressing=False` с `ProgressDeadlineExceeded`, а `kubectl rollout status` возвращает ошибку.
Автоматического отката при этом **не происходит**.

</details>

**A13.** Зачем нужен `revisionHistoryLimit` и что будет, если поставить 0?

<details><summary>Ответ</summary>

Сколько старых ReplicaSet хранить для отката (по умолчанию 10). При 0 откат
станет невозможен.

</details>

**A14.** ⭐ Как откатиться на предыдущую версию? А на конкретную ревизию?

<details><summary>Ответ</summary>

`kubectl rollout undo deployment/web`; на конкретную —
`kubectl rollout undo deployment/web --to-revision=N`.

</details>

**A15.** Почему откат возможен вообще — где хранится «предыдущая версия»?

<details><summary>Ответ</summary>

В старых ReplicaSet'ах, оставленных с `replicas: 0`: у них сохранён шаблон пода.

</details>

**A16.** Как записать причину изменения, чтобы она была видна в истории?

<details><summary>Ответ</summary>

Аннотация `kubernetes.io/change-cause` на Deployment (или через
`kubectl annotate ... --record`-подход в старых версиях).

</details>

**A17.** Что делает `kubectl rollout pause` и зачем это нужно?

<details><summary>Ответ</summary>

Останавливает выкатку: изменения копятся, но новые поды не создаются.
Используется для канареечной проверки и для внесения нескольких изменений одной выкаткой.

</details>

**A18.** Чем `rollout restart` отличается от удаления подов вручную?

<details><summary>Ответ</summary>

`rollout restart` меняет аннотацию шаблона и запускает **штатное** rolling-обновление
с соблюдением `maxUnavailable` и readiness. Ручное удаление подов делает это
без контроля доступности.

</details>

**A19.** Почему `readinessProbe` критична для RollingUpdate?

<details><summary>Ответ</summary>

Без неё под считается доступным сразу после запуска контейнера, и старая реплика
гасится раньше, чем новая реально готова обслуживать трафик.

</details>

**A20.** Сколько версий приложения одновременно работает во время выкатки?
Какие из этого следуют требования к миграциям БД?

<details><summary>Ответ</summary>

Две (а при неудачной выкатке — обе долго). Значит, миграции должны быть
обратно совместимыми: сначала расширяем схему, потом выкатываем код, потом удаляем старые
поля отдельным релизом.

</details>

**A21.** Что покажет `kubectl get rs` через месяц активных релизов?

<details><summary>Ответ</summary>

Много ReplicaSet'ов с `DESIRED 0` — по одному на каждую ревизию, вплоть
до `revisionHistoryLimit`.

</details>

**A22.** Как в пайплайне понять, что деплой провалился?

<details><summary>Ответ</summary>

По коду возврата `kubectl rollout status --timeout=...` (ненулевой = провал)
и по последующей проверке здоровья; при провале — `kubectl rollout undo`.

</details>

**A23.** Чем отличаются `kubectl apply` и `kubectl set image` с точки зрения git?

<details><summary>Ответ</summary>

`apply` берёт состояние из файла в git — источник правды сохраняется.
`set image` меняет объект мимо репозитория и создаёт дрейф.

</details>

**A24.** Как реализовать canary без дополнительных инструментов?

<details><summary>Ответ</summary>

Два Deployment с общей меткой, которую выбирает Service: доля трафика
задаётся соотношением числа реплик.

</details>

**A25.** Как сделать blue-green на голых манифестах и в чём его цена?

<details><summary>Ответ</summary>

Два полных комплекта подов с разными метками версии и переключение
`selector` у Service. Цена — двойной расход ресурсов на время переключения.

</details>

---

### Блок B. «Что произойдёт»

**B1.**
```bash
kubectl scale deployment web --replicas=5
kubectl get rs
```
Вопрос: появится ли новый ReplicaSet? Почему?

<details><summary>Ответ</summary>

Нет: шаблон пода не изменился, хеш тот же — меняется только число реплик.

</details>

**B2.**
```bash
kubectl set image deployment/web app=myapp:1.5
kubectl get rs
```
Вопрос: сколько ReplicaSet'ов увидишь и в каком состоянии?

<details><summary>Ответ</summary>

Два: новый с `DESIRED 3` и старый с `DESIRED 0` (он остаётся для отката).

</details>

**B3.**
```yaml
spec:
  replicas: 4
  strategy:
    rollingUpdate: { maxSurge: 0, maxUnavailable: 1 }
```
Вопрос: сколько подов максимум и минимум будет во время выкатки?

<details><summary>Ответ</summary>

Максимум 4 пода (surge = 0), минимум 3 доступных (unavailable = 1).

</details>

**B4.**
```yaml
spec:
  replicas: 3
  strategy:
    rollingUpdate: { maxSurge: 1, maxUnavailable: 0 }
  template:
    spec:
      containers:
        - name: app
          image: myapp:broken       # образа не существует
```
Вопрос: что произойдёт с приложением? Будет ли даунтайм?

<details><summary>Ответ</summary>

Новый под уйдёт в `ImagePullBackOff`, выкатка остановится, старые 3 пода
продолжат работать. Даунтайма не будет — в этом и смысл `maxUnavailable: 0`.

</details>

**B5.**
```bash
kubectl rollout status deployment/web
# error: deployment "web" exceeded its progress deadline
```
Вопрос: что это значит, работает ли приложение и что делать?

<details><summary>Ответ</summary>

Выкатка не уложилась в `progressDeadlineSeconds`. Старые поды, скорее всего,
работают, приложение доступно. Нужно разобрать причину (`describe`/`logs` новых подов)
и откатиться.

</details>

**B6.**
```yaml
spec:
  strategy:
    type: Recreate
```
Вопрос: как пройдёт обновление и что увидят пользователи?

<details><summary>Ответ</summary>

Сначала удаляются все старые поды, потом создаются новые: несколько секунд
(или десятков секунд) полной недоступности.

</details>

**B7.**
```bash
kubectl rollout undo deployment/web
kubectl rollout undo deployment/web
```
Вопрос: что произойдёт после второй команды?

<details><summary>Ответ</summary>

Вторая команда вернёт на предыдущую ревизию — то есть туда, откуда только что
откатились. `undo` работает как «поменять местами», а не как «шаг назад по истории».

</details>

**B8.**
```yaml
spec:
  selector:
    matchLabels: { app: web }
  template:
    metadata:
      labels: { app: web, version: v2 }
```
Вопрос: применится ли такой манифест?

<details><summary>Ответ</summary>

Да: селектор требует `app: web`, у шаблона эта метка есть, лишние метки разрешены.

</details>

**B9.**
```bash
kubectl delete rs web-7d8f9c5b4
```
Вопрос: что произойдёт с подами и с Deployment?

<details><summary>Ответ</summary>

Deployment немедленно создаст новый ReplicaSet и восстановит поды; кратковременно
приложение может потерять часть реплик.

</details>

**B10.**
```bash
kubectl apply -f deploy.yaml      # replicas: 3 в файле
# ранее кто-то сделал kubectl scale --replicas=10
```
Вопрос: сколько будет подов? А если бы Deployment был под управлением HPA?

<details><summary>Ответ</summary>

Будет 3 — `apply` возвращает значение из файла. Если Deployment управляется HPA,
такой apply схлопнет реплики до 3, и HPA потом снова их поднимет; правильное решение —
убрать `replicas` из манифеста, когда включён HPA.

</details>

---

### Блок C. Практика

#### C1. 🔑 Базовый Deployment руками
Напиши манифест: 3 реплики nginx:1.25, метки, ресурсы, `readinessProbe`,
`strategy` с `maxSurge: 1, maxUnavailable: 0`. Примени, дождись `rollout status`.

#### C2. 🔑 RollingUpdate в реальном времени *(практика роадмапа)*
1. В одном окне: `kubectl get pods -w`
2. В другом: `kubectl set image deploy/web nginx=nginx:1.26`
3. Запиши последовательность: сколько подов появилось, в каком порядке гасли старые.
4. Повтори с `maxSurge: 0, maxUnavailable: 1` и сравни картину.
5. Повтори с `strategy: Recreate` и зафиксируй момент, когда подов нет вообще.

<details><summary>Ответ</summary>

При `1/0` сначала появляется четвёртый под, и только после его `Ready` гасится
первый старый. При `0/1` сначала гасится старый, потом создаётся новый. При `Recreate`
в середине процесса подов нет вообще.

</details>

#### C3. 🔑 Проверка даунтайма
Пока идёт выкатка, в третьем окне гоняй:
```bash
while true; do curl -s -o /dev/null -w "%{http_code} " http://<svc>/; sleep 0.2; done
```
Сравни три стратегии по числу ошибок. Это самый убедительный эксперимент темы.

#### C4. 🔑 Откат *(практика роадмапа)*
1. Выкати заведомо битый образ (`nginx:nosuchtag`).
2. Посмотри `kubectl get pods` и `kubectl rollout status`.
3. Убедись, что старые поды продолжают обслуживать трафик (при `maxUnavailable: 0`).
4. Откатись: `kubectl rollout undo`.
5. Проверь образ в подах после отката.

#### C5. 🔑 Масштабирование *(практика роадмапа)*
```bash
kubectl scale deploy/web --replicas=5
kubectl get pods -o wide       # как распределились по нодам?
kubectl scale deploy/web --replicas=1
kubectl get pods
```
Запиши: какие поды кубер удалил и на какой ноде остался последний.

<details><summary>Ответ</summary>

При уменьшении реплик первыми удаляются поды не в `Ready`, самые новые
и находящиеся на нодах с наибольшим числом реплик этого приложения.

</details>

#### C6. История ревизий
1. Сделай три выкатки с разными образами, каждую с `kubernetes.io/change-cause`.
2. Посмотри `kubectl rollout history`.
3. Посмотри детали второй ревизии.
4. Откатись на первую по номеру.

#### C7. ReplicaSet'ы и хеш шаблона
1. Запиши имя текущего RS.
2. Поменяй только `replicas` → проверь имя RS.
3. Поменяй переменную окружения в шаблоне → проверь имя RS.
4. Сформулируй правило про `pod-template-hash`.

<details><summary>Ответ</summary>

Правило: имя ReplicaSet зависит только от содержимого `spec.template`.
Изменение `replicas` его не меняет, изменение любой строки шаблона — меняет.

</details>

#### C8. revisionHistoryLimit
Поставь `revisionHistoryLimit: 2`, сделай пять выкаток, посмотри `kubectl get rs`.
Попробуй откатиться на пятую ревизию назад — что получится?

<details><summary>Ответ</summary>

При `revisionHistoryLimit: 2` доступны только последние ревизии; откат
на пятую назад вернёт ошибку — соответствующего ReplicaSet уже нет.

</details>

#### C9. Пауза выкатки
1. Начни выкатку и сразу поставь `kubectl rollout pause deploy/web`.
2. Посмотри, сколько подов новой версии успело появиться.
3. Проверь новую версию через `port-forward` на конкретный под.
4. Либо `resume`, либо `undo`. Опиши, как это соотносится с канареечным релизом.

#### C10. Зависшая выкатка
Поставь `progressDeadlineSeconds: 60` и выкати образ, который не стартует.
Дождись `ProgressDeadlineExceeded`, посмотри `kubectl describe deploy web` → Conditions.

<details><summary>Ответ</summary>

В `describe deploy` появится условие `Progressing=False` с причиной
`ProgressDeadlineExceeded`; поды новой версии останутся в проблемном статусе,
старые продолжат работать.

</details>

#### C11. rollout restart
1. Поменяй данные в ConfigMap, подключённом к подам (тема 08 — забеги вперёд).
2. Убедись, что поды не перезапустились.
3. Сделай `kubectl rollout restart` и проверь, что новая конфигурация подхватилась.

#### C12. Canary руками
Сделай два Deployment (`stable` 9 реплик и `canary` 1 реплика) с общей меткой `app=web`
и один Service. Проверь распределение запросов (например, отдавая версию в заголовке
или в теле ответа). Посчитай долю канареечных ответов на 100 запросов.

#### C13. Blue-green руками
Два Deployment (`version: blue`, `version: green`) и Service, указывающий на blue.
Переключи Service на green одним `patch`, замерь время переключения и откатись обратно.

#### C14. Деплой из пайплайна (связка с блоком CI/CD)
Напиши джобу `.gitlab-ci.yml`:
```yaml
deploy:
  script:
    - kubectl set image deploy/web app=$IMAGE:$CI_COMMIT_SHORT_SHA
    - kubectl rollout status deploy/web --timeout=120s
  # при провале — откат
```
Добавь `after_script` или `on_failure`-джобу с `rollout undo`.

#### C15. Две версии одновременно (со звёздочкой)
Во время выкатки собери ответы сервиса в цикле и убедись, что отвечают и старая,
и новая версия. Сформулируй, какие требования это накладывает на API и на схему БД.

<details><summary>Ответ</summary>

API новой версии должно понимать запросы, сформированные старой, и наоборот;
миграции БД — только совместимые в обе стороны на время выкатки.

</details>

---

### Блок D. Инциденты

**D1.** После `kubectl apply` ничего не изменилось: поды прежние, RS тот же.
Назови три причины.

<details><summary>Ответ</summary>

Манифест идентичен текущему состоянию (`unchanged`); изменения внесены в другой
namespace или кластер; тег образа не изменился (например, `latest`), поэтому шаблон
не поменялся.

</details>

**D2.** Выкатка идёт 15 минут и не завершается. Алгоритм разбора.

<details><summary>Ответ</summary>

`kubectl get pods -l app=...` → статусы новых подов; `describe pod` — события
(ImagePull, Pending, Unhealthy); `logs` нового пода; `describe deploy` — Conditions;
проверить квоты и ресурсы кластера.

</details>

**D3.** Новый релиз сломал прод. Что делаешь первым действием и что — вторым?

<details><summary>Ответ</summary>

Первое — `kubectl rollout undo` (вернуть сервис), второе — разбор причины
по логам и событиям уже на спокойную голову.

</details>

**D4.** После отката приложение всё равно работает по-новому. Почему это возможно?
(Подсказка: тег `latest`, миграции БД, внешний конфиг.)

<details><summary>Ответ</summary>

Тег вроде `latest` указывает на тот же новый образ; миграция БД уже применена
и необратима; конфигурация лежит вне Deployment (ConfigMap/внешний сервис)
и не откатилась вместе с ним.

</details>

**D5.** Во время выкатки пользователи получали 502, хотя `maxUnavailable: 0`. Причины?

<details><summary>Ответ</summary>

Приложение не обрабатывает SIGTERM; нет `preStop`-паузы, и запросы приходят
в под, уже удаляемый из Endpoints; `readinessProbe` отвечает «готов» раньше,
чем приложение действительно готово; долгие keep-alive соединения.

</details>

**D6.** Деплой прошёл, `rollout status` зелёный, но приложение не отвечает.
Где проблема, если не в Deployment?

<details><summary>Ответ</summary>

Ищем дальше по цепочке: Service (селектор, `targetPort`), Endpoints, Ingress,
DNS, NetworkPolicy, сама логика приложения и его зависимости.

</details>

**D7.** `kubectl get rs` показывает 27 ReplicaSet'ов одного приложения. Это нормально?
Что настроить?

<details><summary>Ответ</summary>

Ненормально: не настроен `revisionHistoryLimit`. Поставить 3-5 и удалить лишние.

</details>

**D8.** Два инженера одновременно сделали `set image` с разными тегами. Что произойдёт?

<details><summary>Ответ</summary>

Победит последний применённый шаблон: кубер начнёт катить его, а промежуточный
ReplicaSet останется с нулём реплик. Лечится дисциплиной деплоя через пайплайн.

</details>

**D9.** HPA держит 8 реплик, а в git `replicas: 3`. После деплоя из пайплайна
приложение просело. В чём ошибка конфигурации?

<details><summary>Ответ</summary>

В манифесте оставлено поле `replicas`, и `apply` перетирает решение HPA.
Нужно убрать `replicas` из манифеста (или из-под управления Helm через `values`),
оставив число реплик за HPA.

</details>

**D10.** Приложение при старте применяет миграции БД. При RollingUpdate на 5 реплик
миграции запустились параллельно и упали. Как правильно?

<details><summary>Ответ</summary>

Миграции выносят в отдельный шаг: init-контейнер с блокировкой, Job перед
деплоем (в Helm — hook `pre-upgrade`) или отдельная джоба пайплайна. Параллельный
запуск миграций из реплик недопустим.

</details>

**D11.** Кто-то удалил ReplicaSet, поды исчезли, приложение легло на 30 секунд.
Что произошло и почему восстановилось?

<details><summary>Ответ</summary>

Удаление ReplicaSet удалило и его поды (через ownerReference), но Deployment
тут же создал новый ReplicaSet и восстановил реплики — reconciliation loop в действии.

</details>

**D12.** В Deployment поменяли `selector` и получили ошибку. Как выйти из положения
без даунтайма?

<details><summary>Ответ</summary>

Селектор иммутабелен: нужно создать новый Deployment с другим именем
и новым селектором, дождаться готовности его подов, переключить Service,
затем удалить старый Deployment.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Что такое Deployment и чем отличается от ReplicaSet?

<details><summary>Ответ</summary>

Deployment управляет ReplicaSet'ами и версиями приложения: плавное обновление,
история, откат. ReplicaSet только поддерживает заданное число одинаковых подов.

</details>

**2.** Как работает RollingUpdate? Что такое maxSurge и maxUnavailable?

<details><summary>Ответ</summary>

Постепенная замена подов новой версией: `maxSurge` — насколько можно превысить
число реплик, `maxUnavailable` — сколько реплик может быть недоступно.

</details>

**3.** Как откатить релиз и за счёт чего это возможно?

<details><summary>Ответ</summary>

`kubectl rollout undo` — благодаря сохранённым ReplicaSet'ам прошлых ревизий.

</details>

**4.** Какие стратегии обновления бывают и когда нужен Recreate?

<details><summary>Ответ</summary>

RollingUpdate и Recreate. Recreate — когда две версии не могут работать одновременно
(общий RWO-том, несовместимая схема, лицензия на один экземпляр).

</details>

**5.** Что произойдёт, если изменить только число реплик?

<details><summary>Ответ</summary>

Изменится только число подов: шаблон прежний, новая ревизия не создаётся.

</details>

**6.** Почему readinessProbe важна при обновлении?

<details><summary>Ответ</summary>

Она определяет момент, когда новый под можно считать готовым и гасить старый;
без неё возможна недоступность при выкатке.

</details>

**7.** Как реализовать canary/blue-green в кубере?

<details><summary>Ответ</summary>

Canary — два Deployment с общей меткой и разным числом реплик (или Argo Rollouts,
Flagger, mesh); blue-green — два комплекта и переключение селектора Service.

</details>

**8.** Как в CI понять, что деплой неудачный?

<details><summary>Ответ</summary>

По коду возврата `kubectl rollout status --timeout`; при ошибке — автоматический
`rollout undo` и падение джобы.

</details>

**9.** Что будет, если во время выкатки две версии приложения несовместимы по схеме БД?

<details><summary>Ответ</summary>

Часть запросов пойдёт в старую версию, часть — в новую: нужны обратно совместимые
миграции (expand-contract) и совместимые контракты API.

</details>

**10.** Почему нельзя менять селектор Deployment?

<details><summary>Ответ</summary>

Он определяет владение подами и связь с ReplicaSet'ами; поле иммутабельно,
изменение потребовало бы пересоздания объекта.

</details>

---

### 🎯 Чек-лист

- [ ] 🔑 Выполнил практику роадмапа: обновление образа, RollingUpdate вживую, откат, 5 → 1
- [ ] Понимаю связку Deployment → ReplicaSet → Pod
- [ ] Знаю, какие изменения вызывают новую выкатку
- [ ] Объясняю `maxSurge`/`maxUnavailable` на пальцах и подбираю значения осознанно
- [ ] Видел разницу RollingUpdate и Recreate по числу ошибок в curl-цикле
- [ ] Умею читать `rollout history` и откатываться на нужную ревизию
- [ ] Знаю, почему селектор иммутабелен
- [ ] Настроил `revisionHistoryLimit` и понимаю его влияние на откат
- [ ] Умею проверять успех деплоя в пайплайне и откатывать автоматически
