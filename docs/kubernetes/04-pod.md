---
title: "04. Pod — минимальная единица"
description: "Почему под, а не контейнер; фазы и статусы, жизненный цикл, init-контейнеры, sidecar-паттерны"
---

# 04. ⭐ Pod — минимальная единица

> Роадмап → 6. Kubernetes → Основные сущности → **Pod**.
> Здесь же живёт вопрос собеса: *«Почему именно под, а не контейнер считается
> минимальной единицей?»*
> **После темы ты умеешь:** объяснить устройство пода, читать его статусы и фазы,
> понимать, что происходит от `Pending` до `Terminating`.

---

## 🗺️ Карта темы

```text:no-line-numbers
                    ┌───────────────────── POD ─────────────────────┐
                    │  ОБЩИЕ для всех контейнеров пода:             │
                    │   • сетевой namespace → ОДИН IP, общий localhost
                    │   • тома (volumes)                            │
                    │   • IPC, (опционально) PID namespace          │
                    │   • жизненный цикл: планируется и умирает целиком
                    │                                               │
                    │  ┌────────────┐  ┌────────────┐  ┌──────────┐ │
                    │  │ init       │→ │ app        │  │ sidecar  │ │
                    │  │ container  │  │ container  │  │ (логи,   │ │
                    │  │ (до старта)│  │ (основной) │  │  прокси) │ │
                    │  └────────────┘  └────────────┘  └──────────┘ │
                    │        pause-контейнер держит namespace'ы     │
                    └───────────────────────────────────────────────┘
                                        │
                                 IP 10.244.1.7  ← эфемерный, меняется при пересоздании
```

---

## 1. ⭐ Почему под, а не контейнер (вопрос собеса)

**Короткий ответ:**
> «Под — это группа из одного или нескольких контейнеров с **общими сетевым namespace,
> томами и жизненным циклом**. Кубер планирует, перезапускает и адресует именно под.
> Так сделано потому, что часть задач требует нескольких процессов, работающих
> "как на одной машине": приложение и сборщик логов, приложение и прокси.
> Класть их в один контейнер неправильно (один контейнер — один процесс),
> а разносить по разным подам — нельзя, они потеряют общий localhost и файлы».

**Развёрнуто, по пунктам:**

| Причина | Что это даёт |
|---------|--------------|
| **Общая сеть** | Контейнеры пода видят друг друга по `localhost`, у пода один IP. Sidecar-прокси может перехватывать трафик приложения |
| **Общие тома** | Один контейнер пишет файл, другой его читает (классика: приложение пишет лог, сборщик отправляет) |
| **Атомарность планирования** | Всё, что в поде, гарантированно на одной ноде — иначе общий localhost был бы невозможен |
| **Единица масштабирования** | Реплицируется под целиком, а не отдельный контейнер |
| **Единая адресация** | Service балансирует по подам; endpoint — это IP пода |
| **Абстракция от runtime** | Кубер не привязан к Docker: под — понятие кубера, а не контейнерного движка |

**Техническая деталь для сильного ответа:** namespace'ы пода держит служебный
**pause-контейнер** (`infra container`). Он ничего не делает, только «удерживает»
сетевой и IPC namespace, чтобы контейнеры приложения могли перезапускаться,
не теряя IP пода.

> 💡 На практике 90 % подов содержат **один** контейнер. Это нормально: под нужен
> как единица абстракции, а не как повод пихать туда несколько процессов.

---

## 2. Минимальный под и что в нём есть

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: web
  labels:
    app: web
spec:
  containers:
    - name: nginx
      image: nginx:1.25
      ports:
        - containerPort: 80        # информационно: не открывает и не пробрасывает порт
      env:
        - name: ENV
          value: "dev"
      resources:                   # тема 09 — но привыкай писать сразу
        requests: { cpu: 100m, memory: 128Mi }
        limits:   { cpu: 500m, memory: 256Mi }
      volumeMounts:
        - name: cache
          mountPath: /var/cache/nginx
  volumes:
    - name: cache
      emptyDir: {}
  restartPolicy: Always
  terminationGracePeriodSeconds: 30
```

Полезные поля контейнера (почти дословно из блока Docker):

| Поле | Docker-аналог | Замечание |
|------|---------------|-----------|
| `image` | `image` | Всегда указывай конкретный тег, не `latest` |
| `command` | `ENTRYPOINT` | ⚠️ Путаница: `command` — это **ENTRYPOINT** |
| `args` | `CMD` | |
| `env` / `envFrom` | `-e` / `--env-file` | Из ConfigMap и Secret — тема 08 |
| `workingDir` | `WORKDIR` | |
| `volumeMounts` | `-v` | |
| `imagePullPolicy` | — | `IfNotPresent` / `Always` / `Never` |
| `securityContext` | `--user`, capabilities | `runAsNonRoot`, `readOnlyRootFilesystem` |

> ⚠️ `containerPort` — **справочное поле**. Контейнер слушает порт независимо от него,
> и доступность извне определяется Service, а не этой записью.

---

## 3. Фазы и статусы ⭐

**Фаза пода** (`status.phase`) — всего пять значений:

| Фаза | Значение |
|------|----------|
| `Pending` | Объект принят, но контейнеры ещё не запущены: ждёт ноду, тянет образ, монтирует тома |
| `Running` | Под назначен на ноду, все контейнеры созданы, хотя бы один работает |
| `Succeeded` | Все контейнеры завершились с кодом 0 и не будут перезапускаться |
| `Failed` | Все контейнеры завершились, хотя бы один — с ошибкой |
| `Unknown` | Нет связи с нодой |

А вот то, что показывает `kubectl get pods` в колонке STATUS, — это чаще **причина
состояния контейнера**, а не фаза:

| STATUS | Что происходит | Куда смотреть |
|--------|----------------|---------------|
| `ContainerCreating` | Тянется образ, монтируются тома, настраивается сеть | `describe` → события |
| `ImagePullBackOff` / `ErrImagePull` | Образ не скачивается: нет тега, нет доступа, опечатка | `describe`, секрет реестра |
| `CrashLoopBackOff` | Контейнер стартует и падает по кругу | `logs --previous` |
| `CreateContainerConfigError` | Нет ConfigMap/Secret, указанного в спеке | `describe` |
| `RunContainerError` | Ошибка запуска: битый `command`, права | `describe` + логи |
| `OOMKilled` | Превышен лимит памяти (код 137) | `limits`, тема 09 |
| `Completed` | Отработал и вышел с 0 (нормально для Job) | — |
| `Error` | Вышел с ненулевым кодом | `logs` |
| `Terminating` | Идёт удаление, ждём graceful shutdown | `describe`, finalizers |
| `Evicted` | Вытеснен: на ноде кончились ресурсы/диск | `describe node` |
| `Pending` | Нет подходящей ноды (ресурсы, taints, PVC) | `describe` → `FailedScheduling` |

**Backoff** — механизм задержки повторного запуска: 10 с → 20 с → 40 с … до 5 минут.
Поэтому `CrashLoopBackOff` со временем «оживает» всё реже.

---

## 4. Жизненный цикл пода ⭐

```text:no-line-numbers
 kubectl apply
      │
      ▼
  [Pending] ── scheduler выбрал ноду ──► kubelet ноды
      │                                    │
      │                          ┌─────────┴─────────┐
      │                          │ CNI: IP для пода  │
      │                          │ тома: монтируем   │
      │                          │ CRI: pull образа  │
      │                          └─────────┬─────────┘
      ▼                                    ▼
  init-контейнеры (по очереди, каждый до успеха)
      │
      ▼
  postStart hook ──► основные контейнеры стартуют
      │
      ▼
  startupProbe → livenessProbe / readinessProbe (тема 09)
      │
  [Running] ──────────────────────────────────────┐
      │                                           │
   удаление                                       │ контейнер упал
      ▼                                           ▼
  preStop hook                             restartPolicy?
      │                                    Always → рестарт
  SIGTERM всем контейнерам                 OnFailure → рестарт если код != 0
      │  (параллельно: под убирают          Never → под Failed/Succeeded
      │   из Endpoints сервисов)
      │
   ждём terminationGracePeriodSeconds (по умолчанию 30 с)
      │
      ▼
  SIGKILL, если не завершился
      │
      ▼
  объект удалён из API
```

**Важнейшая практическая деталь (и хороший ответ на собесе):**
удаление из Endpoints и отправка SIGTERM происходят **одновременно и асинхронно**.
kube-proxy на нодах обновляет правила не мгновенно, поэтому несколько запросов
могут прилететь в уже завершающийся под. Лечение — `preStop` со сном:

```yaml
lifecycle:
  preStop:
    exec:
      command: ["sh", "-c", "sleep 5"]     # даём правилам разойтись по кластеру
terminationGracePeriodSeconds: 45
```

---

## 5. restartPolicy

| Значение | Поведение | Где применяется |
|----------|-----------|-----------------|
| `Always` (по умолчанию) | Перезапускать всегда | Deployment, StatefulSet, DaemonSet |
| `OnFailure` | Перезапускать только при ненулевом коде | Job |
| `Never` | Не перезапускать | Job, разовые задачи |

> ⚠️ Политика действует на **контейнеры внутри пода**, а не на под: под не «переезжает»
> сам. Перемещение на другую ноду делает контроллер, создавая **новый** под.
> Ещё одно следствие: Deployment **не разрешает** `restartPolicy` кроме `Always`.

---

## 6. Init-контейнеры

Выполняются **по очереди, до старта основных**, каждый должен завершиться успешно.

```yaml
spec:
  initContainers:
    - name: wait-for-db
      image: busybox:1.36
      command: ['sh', '-c', 'until nc -z postgres 5432; do echo waiting; sleep 2; done']
    - name: migrate
      image: myapp:1.4
      command: ['./migrate.sh']
  containers:
    - name: app
      image: myapp:1.4
```

Типичные задачи: дождаться зависимости, применить миграции, скачать конфиг,
подготовить права на томе, сгенерировать сертификат.

| Особенность | Значение |
|-------------|----------|
| Порядок | Строго последовательный |
| Отказ | Под перезапускает init-контейнер (при `restartPolicy: Always`), статус `Init:CrashLoopBackOff` |
| Ресурсы | Для планирования учитывается максимум из init-контейнеров, а не сумма |
| Логи | `kubectl logs POD -c wait-for-db` |
| Probe'ы | У init-контейнеров их нет |

---

## 7. Sidecar и другие паттерны нескольких контейнеров

| Паттерн | Суть | Пример |
|---------|------|--------|
| **Sidecar** | Дополняет основное приложение | Сборщик логов, прокси service mesh, обновление конфига |
| **Ambassador** | Прокси к внешнему миру | Локальный прокси к БД с пулом соединений |
| **Adapter** | Приводит вывод к нужному формату | Экспортёр метрик в формате Prometheus |

```yaml
spec:
  initContainers:
    - name: log-shipper           # ⭐ современный способ объявить sidecar
      image: fluent-bit:2.2
      restartPolicy: Always       # именно это делает init-контейнер сайдкаром
      volumeMounts:
        - { name: logs, mountPath: /var/log/app }
  containers:
    - name: app
      image: myapp:1.4
      volumeMounts:
        - { name: logs, mountPath: /var/log/app }
  volumes:
    - name: logs
      emptyDir: {}
```

> 💡 Начиная с Kubernetes 1.29 «настоящие» sidecar'ы объявляются как init-контейнеры
> с `restartPolicy: Always`: они стартуют **до** основного контейнера и живут вместе с ним,
> а при завершении пода не мешают Job'у завершиться. Раньше сайдкар просто клали
> вторым контейнером в `containers` — так тоже работает и так написано в большинстве
> существующих манифестов.

**Когда НЕ надо делать несколько контейнеров:** если процессы можно масштабировать
независимо или они не обмениваются файлами/localhost — это разные поды.

---

## 8. Голые поды в проде — антипаттерн

```bash
kubectl run solo --image=nginx --restart=Never   # под без владельца
```

| Проблема | Следствие |
|----------|-----------|
| Нет контроллера | Нода умерла — под исчез навсегда |
| Нет обновления | Невозможен rolling update и откат |
| Нет масштабирования | `scale` неприменим |
| Нет описания в git | Никто не знает, откуда он взялся |

Поэтому в проде поды всегда создаёт контроллер: Deployment, StatefulSet, DaemonSet, Job.
Голый под — только для отладки (`kubectl run tmp --rm -it`).

---

## 9. Практическая диагностика пода

```bash
kubectl get pod web -o wide                       # IP, нода, статус
kubectl describe pod web                          # ⭐ события внизу — главное
kubectl logs web -c app --previous                # логи упавшего контейнера
kubectl get pod web -o jsonpath='{.status.containerStatuses[0].lastState}'
kubectl get pod web -o yaml | grep -A5 'state:'
kubectl exec -it web -- sh
kubectl debug -it web --image=busybox --target=app   # эфемерный контейнер (тема 20)
```

Что смотреть в `describe` по порядку:
1. `Node:` — попал ли на ноду вообще (если нет — проблема планирования);
2. `Status` / `Reason` — фаза и причина;
3. `Containers → State / Last State` — Exit Code, Reason (`OOMKilled`, `Error`);
4. `Events` — хронология: `Scheduled` → `Pulling` → `Pulled` → `Created` → `Started`.

| Exit code | Значение |
|-----------|----------|
| 0 | Штатное завершение |
| 1 | Ошибка приложения |
| 125-127 | Проблемы запуска команды в контейнере |
| **137** | SIGKILL — чаще всего **OOMKilled** или невыполненный graceful shutdown |
| **143** | SIGTERM — штатное завершение по сигналу |

(Это ровно те коды, что разбирались в блоке Linux, тема 07.)

---

## 💼 Как это в DevOps

- Читать `describe pod` быстрее, чем гуглить, — базовый навык дежурного.
- Приложение обязано корректно обрабатывать SIGTERM: без этого каждый деплой даёт
  оборванные запросы. Проверяется это ровно один раз — и потом работает годами.
- `preStop: sleep 5` — дешёвое лекарство от 502 при выкатке, которое ставят почти везде.
- Init-контейнер «дождись базы» лучше, чем ретраи в коде приложения при старте:
  логика ожидания вынесена из приложения в инфраструктуру.
- IP пода эфемерен — ни один конфиг не должен содержать IP пода. Только имена сервисов.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Создать одноразовый под | `kubectl run tmp --rm -it --image=busybox --restart=Never -- sh` |
| Каркас манифеста пода | `kubectl run web --image=nginx --dry-run=client -o yaml` |
| Узнать, почему Pending | `kubectl describe pod` → `FailedScheduling` |
| Узнать, почему CrashLoop | `kubectl logs POD --previous` |
| Узнать Exit Code | `kubectl describe pod` → `Last State` |
| Логи конкретного контейнера | `kubectl logs POD -c NAME` |
| Зайти в под | `kubectl exec -it POD -- sh` |
| Посмотреть IP и ноду | `kubectl get pod POD -o wide` |
| Удалить немедленно | `kubectl delete pod POD --grace-period=0 --force` ⚠️ |
| Дождаться готовности | `kubectl wait --for=condition=Ready pod/POD --timeout=60s` |

---

## 🧠 Что запомнить

1. Под — минимальная единица: 1+ контейнеров с **общими сетью, томами и жизненным циклом**.
2. ⭐ Почему не контейнер: нужны sidecar-паттерны с общим localhost и файлами,
   а планировать и адресовать удобнее одну неделимую единицу.
3. У пода **один IP** на все контейнеры; внутри они общаются через `localhost`.
4. IP пода эфемерный — никогда не прописывай его в конфигах.
5. Фаз всего пять: Pending, Running, Succeeded, Failed, Unknown; STATUS в `get pods` —
   это чаще причина состояния контейнера.
6. `CrashLoopBackOff` — не ошибка сама по себе, а цикл рестартов с растущей задержкой.
7. Init-контейнеры выполняются по очереди до основных; sidecar живёт рядом с приложением.
8. `restartPolicy` относится к контейнерам пода; переезд на другую ноду — это новый под.
9. При удалении: SIGTERM → `terminationGracePeriodSeconds` (30 с) → SIGKILL;
   `preStop` спасает от 502 во время выкатки.
10. Exit 137 = OOMKilled/SIGKILL, 143 = SIGTERM.
11. `command` — это ENTRYPOINT, `args` — это CMD. Не перепутай.
12. Голые поды в проде — антипаттерн: их никто не восстановит.

---

## Задачи

> ⭐ Здесь вопрос собеса: *«Почему именно под, а не контейнер считается минимальной
> единицей?»* — ответ надо проговорить вслух минимум трижды.

---

### Блок A. Теория

**A1.** ⭐ Что такое под? Дай определение одной фразой.

<details><summary>Ответ</summary>

Под — минимальная единица запуска в Kubernetes: один или несколько контейнеров
с общими сетевым namespace, томами и жизненным циклом, всегда на одной ноде.

</details>

**A2.** ⭐ Почему минимальная единица — под, а не контейнер? Назови пять аргументов.

<details><summary>Ответ</summary>

(1) Нужны паттерны из нескольких процессов с общим localhost и файлами
(sidecar, ambassador, adapter); (2) один контейнер — один процесс, поэтому склеивать
их в один образ неправильно; (3) планировать и перезапускать проще неделимую единицу;
(4) единый IP и единая точка адресации для Service; (5) под — абстракция самого кубера,
не зависящая от конкретного container runtime.

</details>

**A3.** Что общего у контейнеров внутри одного пода и что у них раздельное?

<details><summary>Ответ</summary>

Общее: сетевой namespace (IP, порты, localhost), тома, IPC, метки, нода,
жизненный цикл. Раздельное: файловая система из своего образа, процессы
(если не включён общий PID namespace), ресурсы и probe'ы, переменные окружения.

</details>

**A4.** Сколько IP-адресов у пода с тремя контейнерами? Как они общаются между собой?

<details><summary>Ответ</summary>

Один IP на под. Контейнеры общаются через `localhost` и должны занимать
разные порты.

</details>

**A5.** Что такое pause-контейнер и зачем он нужен?

<details><summary>Ответ</summary>

Служебный контейнер, который создаёт и удерживает сетевой и IPC namespace пода.
Благодаря ему контейнеры приложения можно перезапускать, не теряя IP пода.

</details>

**A6.** Может ли под быть запущен сразу на двух нодах? Почему?

<details><summary>Ответ</summary>

Нет. Под — атомарная единица планирования: все его контейнеры на одной ноде,
иначе общий localhost и общие тома были бы невозможны.

</details>

**A7.** Назови пять фаз пода и что каждая означает.

<details><summary>Ответ</summary>

`Pending` — принят, но не запущен; `Running` — назначен и хотя бы один контейнер
работает; `Succeeded` — все завершились с 0; `Failed` — хотя бы один завершился с ошибкой
и рестартов не будет; `Unknown` — нет связи с нодой.

</details>

**A8.** Чем `status.phase` отличается от того, что показывает колонка STATUS в `get pods`?

<details><summary>Ответ</summary>

`phase` — одно из пяти значений. Колонка STATUS показывает более точную причину
состояния контейнеров: `ContainerCreating`, `CrashLoopBackOff`, `ImagePullBackOff`,
`OOMKilled`, `Terminating`, `Evicted` и т. д.

</details>

**A9.** Что означает `CrashLoopBackOff` и как растёт задержка между попытками?

<details><summary>Ответ</summary>

Контейнер запускается и падает по кругу; kubelet увеличивает паузу между
попытками экспоненциально: 10, 20, 40 секунд и далее до максимума в 5 минут.

</details>

**A10.** Чем `ImagePullBackOff` отличается от `ErrImagePull`?

<details><summary>Ответ</summary>

`ErrImagePull` — первая неудачная попытка скачивания; `ImagePullBackOff` —
kubelet перешёл к повторам с задержкой после нескольких неудач. Причины одинаковые.

</details>

**A11.** Что означает `CreateContainerConfigError`?

<details><summary>Ответ</summary>

Контейнер не создать из-за ошибки конфигурации: отсутствует ConfigMap
или Secret, указанный в `env`/`envFrom`/`volumes`, либо нет нужного ключа.

</details>

**A12.** Что такое `Evicted` и кто вытесняет под?

<details><summary>Ответ</summary>

Под вытеснен kubelet'ом из-за нехватки ресурсов на ноде (память, эфемерный диск,
inodes). Вытесняет kubelet по eviction-порогам, порядок зависит от QoS-класса.

</details>

**A13.** ⭐ Опиши жизненный цикл пода от `apply` до `Running`.

<details><summary>Ответ</summary>

`apply` → API server → etcd → контроллер создаёт под → scheduler назначает ноду →
kubelet: CNI даёт IP, монтируются тома, CRI тянет образ → init-контейнеры по очереди →
основные контейнеры → probe'ы → `Running`/`Ready` → под попадает в Endpoints.

</details>

**A14.** ⭐ Что происходит при удалении пода? Опиши по шагам с сигналами и таймингами.

<details><summary>Ответ</summary>

Объект получает `deletionTimestamp` → параллельно: под убирают из Endpoints
и kubelet выполняет `preStop`, затем шлёт SIGTERM всем контейнерам → ждёт
`terminationGracePeriodSeconds` (30 с по умолчанию) → SIGKILL → объект удаляется из API.

</details>

**A15.** Почему при выкатке возможны 502-ошибки и как помогает `preStop`?

<details><summary>Ответ</summary>

Удаление из Endpoints и остановка контейнера происходят параллельно, а правила
kube-proxy обновляются на нодах не мгновенно — часть запросов успевает прийти в умирающий
под. `preStop` со сном 3-10 секунд даёт правилам разойтись до остановки приложения.

</details>

**A16.** Что такое `terminationGracePeriodSeconds` и каково значение по умолчанию?

<details><summary>Ответ</summary>

Время между SIGTERM и SIGKILL; по умолчанию 30 секунд.

</details>

**A17.** Какие значения принимает `restartPolicy` и где какое применяется?

<details><summary>Ответ</summary>

`Always` — всегда (Deployment/StatefulSet/DaemonSet); `OnFailure` — при ненулевом
коде (Job); `Never` — не перезапускать (Job, разовые задачи).

</details>

**A18.** Почему у Deployment нельзя поставить `restartPolicy: OnFailure`?

<details><summary>Ответ</summary>

Deployment рассчитан на постоянно работающие приложения и требует `Always`;
иначе понятия «нужное число живых реплик» не существует.

</details>

**A19.** Что такое init-контейнеры? В каком порядке выполняются и что будет при отказе?

<details><summary>Ответ</summary>

Контейнеры, выполняющиеся последовательно до старта основных, каждый должен
завершиться успешно. При отказе под остаётся в `Init:Error`/`Init:CrashLoopBackOff`
и init-контейнер перезапускается.

</details>

**A20.** Как считаются ресурсы init-контейнеров при планировании?

<details><summary>Ответ</summary>

Берётся максимум из требований init-контейнеров и сравнивается с суммой
требований основных; итоговое требование пода — большее из двух значений.

</details>

**A21.** Что такое sidecar? Приведи три реальных примера.

<details><summary>Ответ</summary>

Вспомогательный контейнер рядом с приложением: сборщик логов (fluent-bit),
прокси service mesh (Envoy), синхронизатор конфигов/секретов, экспортёр метрик.

</details>

**A22.** Как объявить sidecar «современным» способом и в чём преимущество?

<details><summary>Ответ</summary>

Объявить его в `initContainers` с `restartPolicy: Always` (с 1.29):
он стартует до основного контейнера, работает всё время жизни пода
и корректно завершается, не мешая Job'ам завершаться.

</details>

**A23.** Когда два процесса НЕ надо класть в один под?

<details><summary>Ответ</summary>

Если процессы масштабируются независимо, если им не нужен общий localhost
или общие файлы, если у них разный цикл релизов — это отдельные поды.

</details>

**A24.** Что такое голый под и почему это антипаттерн?

<details><summary>Ответ</summary>

Под, созданный без контроллера. Никто не восстановит его при падении ноды,
нет rolling update, нет масштабирования, нет источника правды в git.

</details>

**A25.** Что означает `containerPort` в манифесте? Открывает ли он порт?

<details><summary>Ответ</summary>

Это информационное поле (документирующее и используемое некоторыми
инструментами). Контейнер слушает порт независимо от него; доступ снаружи даёт Service.

</details>

**A26.** Чем `command` отличается от `args` и как это соотносится с Dockerfile?

<details><summary>Ответ</summary>

`command` переопределяет ENTRYPOINT, `args` — CMD. Частая ошибка — считать
`command` аналогом CMD.

</details>

**A27.** Что означают коды выхода 137 и 143?

<details><summary>Ответ</summary>

137 = 128+9, процесс убит SIGKILL (чаще всего OOMKilled или истёк grace period);
143 = 128+15, процесс завершён по SIGTERM.

</details>

**A28.** Какие поля есть у `securityContext` и зачем они?

<details><summary>Ответ</summary>

`runAsUser`, `runAsGroup`, `runAsNonRoot`, `fsGroup`, `readOnlyRootFilesystem`,
`allowPrivilegeEscalation`, `capabilities`, `seccompProfile`. Ограничивают права
контейнера — прямое продолжение темы прав из блока Linux и Docker.

</details>

**A29.** Что такое `emptyDir` и что с ним произойдёт при рестарте контейнера?
А при пересоздании пода?

<details><summary>Ответ</summary>

`emptyDir` — пустой каталог, создаваемый при запуске пода на ноде. Переживает
рестарт **контейнера**, но исчезает вместе с **подом**.

</details>

**A30.** Как дождаться готовности пода в скрипте?

<details><summary>Ответ</summary>

`kubectl wait --for=condition=Ready pod/NAME --timeout=60s`.

</details>

---

### Блок B. «Что произойдёт»

**B1.**
```yaml
spec:
  containers:
    - name: a
      image: busybox
      command: ["sh","-c","sleep 3600"]
    - name: b
      image: busybox
      command: ["sh","-c","wget -qO- http://localhost:8080"]
```
Вопрос: увидит ли контейнер `b` сервис, слушающий 8080 в контейнере `a`? Почему?

<details><summary>Ответ</summary>

Увидит: контейнеры одного пода делят сетевой namespace, поэтому `localhost:8080`
из `b` попадёт в `a`.

</details>

**B2.**
```yaml
spec:
  containers:
    - name: app
      image: busybox
      command: ["sh","-c","echo done"]
  restartPolicy: Always
```
Вопрос: что будет с подом через минуту? Какой статус увидишь?

<details><summary>Ответ</summary>

Контейнер завершится с кодом 0, но `restartPolicy: Always` заставит kubelet
запускать его снова; под уйдёт в `CrashLoopBackOff`, хотя ошибки нет.

</details>

**B3.**
```yaml
spec:
  restartPolicy: Never
  containers:
    - name: app
      image: busybox
      command: ["sh","-c","exit 1"]
```
Вопрос: какая будет фаза пода? Перезапустится ли контейнер?

<details><summary>Ответ</summary>

Фаза `Failed`, контейнер не перезапускается, `RESTARTS` остаётся 0.

</details>

**B4.**
```yaml
spec:
  initContainers:
    - name: wait
      image: busybox
      command: ["sh","-c","until nc -z db 5432; do sleep 2; done"]
  containers:
    - name: app
      image: myapp:1.0
```
Вопрос: что произойдёт, если сервиса `db` не существует? Какой статус у пода?

<details><summary>Ответ</summary>

Init-контейнер будет крутиться в ожидании; под останется в статусе `Init:0/1`
неограниченно долго. В событиях ничего страшного не будет — это самая «тихая» поломка.

</details>

**B5.**
```text:no-line-numbers
kubectl get pod app
# NAME  READY  STATUS    RESTARTS  AGE
# app   0/1    Running   0         2m
```
Вопрос: контейнер работает или нет? Идёт ли на него трафик через Service?

<details><summary>Ответ</summary>

Контейнер работает (`Running`), но не готов: не прошёл `readinessProbe`.
Трафик через Service на него **не идёт** — под исключён из Endpoints.

</details>

**B6.**
```text:no-line-numbers
kubectl describe pod app | grep -A3 "Last State"
#     Last State:     Terminated
#       Reason:       OOMKilled
#       Exit Code:    137
```
Вопрос: что произошло и что надо поменять?

<details><summary>Ответ</summary>

Контейнер превысил `limits.memory` и был убит ядром. Нужно либо поднять лимит,
либо чинить потребление памяти приложением; заодно проверить `requests`.

</details>

**B7.**
```yaml
spec:
  containers:
    - name: app
      image: nginx
      ports:
        - containerPort: 8080
```
Вопрос: на каком порту будет доступен nginx внутри кластера?

<details><summary>Ответ</summary>

На 80: `containerPort` ничего не меняет, nginx слушает то, что настроено в образе.
Поле лишь документирует намерение.

</details>

**B8.**
```text:no-line-numbers
kubectl delete pod app
# под завис в Terminating на 5 минут
```
Вопрос: назови три причины.

<details><summary>Ответ</summary>

Приложение не реагирует на SIGTERM и ждёт grace period; на поде висит финализатор;
нода недоступна (`NotReady`), и kubelet не подтверждает удаление; том не отмонтируется.

</details>

**B9.**
```yaml
spec:
  containers:
    - name: app
      image: myapp
      command: ["python"]
      args: ["app.py", "--port=8080"]
```
Вопрос: что здесь ENTRYPOINT, а что CMD в терминах Dockerfile?

<details><summary>Ответ</summary>

`command: ["python"]` — ENTRYPOINT, `args: ["app.py","--port=8080"]` — CMD.

</details>

---

### Блок C. Практика

#### C1. 🔑 Первый под руками
Напиши `pod.yaml` вручную (не генератором): nginx:1.25, метка `app=web`, `containerPort: 80`,
requests/limits. Примени, проверь статус, IP и ноду. Зайди внутрь и проверь,
что nginx отвечает через `localhost`.

#### C2. 🔑 Общий localhost
Сделай под с двумя контейнерами:
- `web` — nginx;
- `client` — busybox с `sleep 3600`.

Из `client` выполни `wget -qO- http://localhost`. Объясни результат.
Потом разнеси эти же контейнеры по двум подам и повтори — что изменилось?

<details><summary>Ответ</summary>

В одном поде `wget http://localhost` работает; в разных подах — нет,
нужно обращаться по IP пода или через Service.

</details>

#### C3. Общий том
В том же поде добавь `emptyDir`, смонтированный в оба контейнера.
1. Создай файл из первого контейнера.
2. Прочитай его из второго.
3. Перезапусти контейнер (убей процесс) и проверь, остался ли файл.
4. Удали под, создай заново — остался ли файл?

<details><summary>Ответ</summary>

Файл переживает рестарт контейнера (том живёт на ноде, пока жив под),
но исчезает при удалении и пересоздании пода.

</details>

#### C4. Init-контейнер
Сделай под, который ждёт сервис `db`:
1. Примени — под в `Init:0/1`.
2. Посмотри логи init-контейнера.
3. Создай сервис `db` (можно `kubectl create service clusterip db --tcp=5432:5432`).
4. Убедись, что под пошёл дальше. Замерь, сколько это заняло.

#### C5. 🔑 CrashLoopBackOff своими руками
```bash
kubectl run crasher --image=busybox --restart=Always -- sh -c 'echo start; sleep 2; exit 1'
```
1. Наблюдай `kubectl get pods -w` и записывай интервалы между рестартами.
2. Получи логи предыдущего запуска.
3. Найди Exit Code в `describe`.
4. Объясни, почему `RESTARTS` растёт, а под не удаляется.

<details><summary>Ответ</summary>

Интервалы примерно 10, 20, 40, 80 секунд и далее до 5 минут. Под не удаляется,
потому что контроллер обязан держать нужное число реплик, а kubelet — перезапускать
контейнер согласно `restartPolicy`.

</details>

#### C6. ImagePullBackOff
Запусти под с несуществующим образом `nginx:nosuchtag`.
1. Посмотри статус и события.
2. Найди точное сообщение об ошибке.
3. Исправь образ через `kubectl set image` или пересоздание.

#### C7. OOMKilled
Запусти под с `limits.memory: 64Mi` и командой, съедающей память:
```bash
kubectl run oom --image=polinux/stress --restart=Never \
  --limits='memory=64Mi' -- stress --vm 1 --vm-bytes 200M --vm-hang 1
```
1. Дождись падения.
2. Найди `OOMKilled` и Exit Code.
3. Подними лимит и убедись, что под живёт.

<details><summary>Ответ</summary>

В `describe` увидишь `Last State: Terminated`, `Reason: OOMKilled`, `Exit Code: 137`.

</details>

#### C8. 🔑 Graceful shutdown
Сделай под с приложением, которое ловит SIGTERM (например, `sh -c 'trap "echo SIGTERM; sleep 10; exit 0" TERM; while true; do sleep 1; done'`).
1. Удали под и засеки время до исчезновения.
2. Поставь `terminationGracePeriodSeconds: 5` и повтори.
3. Сделай контейнер, который **игнорирует** SIGTERM, и замерь, через сколько придёт SIGKILL.

<details><summary>Ответ</summary>

С обработкой SIGTERM под исчезнет примерно через 10 секунд; с
`terminationGracePeriodSeconds: 5` — через 5 (SIGKILL прервёт sleep). Контейнер,
игнорирующий SIGTERM, будет убит ровно по истечении grace period.

</details>

#### C9. preStop
Добавь `preStop` со `sleep 5`. Замерь, как изменилось время удаления пода.
Объясни, зачем это нужно во время rolling update.

#### C10. Статусы-зоопарк
Создай по одному поду на каждый статус и запиши симптомы:
`Pending` (запроси 100 CPU), `ImagePullBackOff`, `CrashLoopBackOff`,
`CreateContainerConfigError` (сошлись на несуществующий ConfigMap), `Completed`.

#### C11. Sidecar
Сделай под: приложение пишет строки в `/var/log/app/app.log` (на `emptyDir`),
sidecar `busybox` делает `tail -f` этого файла в stdout.
Проверь `kubectl logs POD -c sidecar`. Объясни, зачем так делают в реальности.

#### C12. Голый под vs Deployment
1. Создай под напрямую и Deployment.
2. Удали под в обоих случаях.
3. Останови ноду, на которой живут оба (kind: `docker stop`).
4. Запиши разницу в поведении. Это ответ на вопрос «почему голые поды — антипаттерн».

<details><summary>Ответ</summary>

Голый под после удаления не возвращается, а при остановке ноды исчезает
навсегда; под Deployment'а пересоздаётся сразу и переезжает на живую ноду.

</details>

#### C13. command и args
Запусти `busybox` с `command: ["echo"]` и `args: ["hello"]`. Потом поменяй местами
и посмотри, что сломается. Сопоставь с ENTRYPOINT/CMD из блока Docker.

#### C14. securityContext (со звёздочкой)
Запусти под с `runAsNonRoot: true`, `runAsUser: 1000`, `readOnlyRootFilesystem: true`.
1. Что сломается у nginx и почему?
2. Как починить, оставив rootfs только для чтения?

<details><summary>Ответ</summary>

nginx не сможет писать в `/var/cache/nginx` и `/var/run` и упадёт. Лечение —
подмонтировать `emptyDir` в эти каталоги (и использовать образ `nginx-unprivileged`,
слушающий порт выше 1024).

</details>

#### C15. wait и автоматизация
Напиши bash-скрипт: применить манифест → дождаться `condition=Ready` →
вывести IP пода → удалить. Используй `kubectl wait` и `jsonpath`.

---

### Блок D. Инциденты

**D1.** Под висит `Pending` 10 минут. Приведи алгоритм разбора из четырёх шагов.

<details><summary>Ответ</summary>

(1) `kubectl describe pod` → событие `FailedScheduling` с причиной;
(2) ресурсы: `requests` против `Allocatable` нод; (3) ограничения размещения:
nodeSelector/affinity/taints; (4) тома: привязан ли PVC, есть ли PV в нужной зоне.

</details>

**D2.** Под `Running 0/1` уже полчаса, приложение вроде работает. Что происходит?

<details><summary>Ответ</summary>

Не проходит `readinessProbe`: путь, порт, таймауты или приложение действительно
не готово (долгая инициализация, недоступная зависимость). Смотреть `describe` и логи.

</details>

**D3.** После деплоя часть запросов получает 502 ровно в момент выкатки. Причина и лечение.

<details><summary>Ответ</summary>

Под удаляется из Endpoints одновременно с получением SIGTERM, правила
на нодах обновляются с задержкой. Лечение: `preStop: sleep 5-10`, корректная обработка
SIGTERM, `readinessProbe`, разумные `maxSurge`/`maxUnavailable`.

</details>

**D4.** Приложение перезапускается раз в 20 минут, в логах ничего. Что смотришь в первую
очередь и какой Exit Code ожидаешь увидеть?

<details><summary>Ответ</summary>

`kubectl describe pod` → `Last State`: ожидаемо `OOMKilled` с кодом 137
(либо liveness-проба убивает контейнер — тогда в событиях будет `Unhealthy`).

</details>

**D5.** Разработчик прописал в конфиге IP пода базы, через день всё сломалось. Объясни.

<details><summary>Ответ</summary>

IP пода эфемерный: при пересоздании пода он меняется. Нужно обращаться
к Service по DNS-имени.

</details>

**D6.** Под удаляется 30 секунд, хотя приложение останавливается мгновенно. Почему
и как ускорить корректно?

<details><summary>Ответ</summary>

Приложение не обрабатывает SIGTERM, поэтому ждём полный grace period.
Правильно — добавить обработчик сигнала в приложение (и только затем, при необходимости,
уменьшить `terminationGracePeriodSeconds`).

</details>

**D7.** Под застрял в `Terminating` навсегда. Что проверить и почему `--force` —
плохой первый шаг?

<details><summary>Ответ</summary>

Проверить финализаторы (`kubectl get pod -o yaml`), состояние ноды, зависшие тома.
`--force` лишь удаляет запись в API, процесс может остаться живым — для StatefulSet
это риск двух экземпляров с одним томом.

</details>

**D8.** Под с двумя контейнерами: один упал, второй работает. Что покажет `READY`
и будет ли под получать трафик через Service?

<details><summary>Ответ</summary>

`READY 1/2`; под не считается готовым и исключается из Endpoints,
трафик на него не идёт.

</details>

**D9.** Init-контейнер отработал успешно, но основной падает с ошибкой «нет файла»,
который init создавал. Что забыли?

<details><summary>Ответ</summary>

Init-контейнер писал в свою файловую систему: нужен общий том (`emptyDir`),
смонтированный в оба контейнера.

</details>

**D10.** На ноде закончилась память, кубер вытеснил поды. Какие поды он вытеснит
первыми и почему? (Ответ связан с QoS, тема 09.)

<details><summary>Ответ</summary>

Сначала `BestEffort` (без requests/limits), затем `Burstable` с потреблением
выше requests, в последнюю очередь `Guaranteed`. Подробности — тема 09.

</details>

**D11.** Под получает SIGTERM, но приложение (PID 1 = shell-скрипт) его не видит.
Классическая проблема из блока Docker — в чём она?

<details><summary>Ответ</summary>

Shell как PID 1 не пересылает сигналы дочерним процессам; нужно
`exec` в скрипте или запуск приложения напрямую, либо init-процесс вроде `tini`.

</details>

**D12.** После обновления образа под не перезапустился, хотя тег тот же (`latest`).
Почему и что делать правильно?

<details><summary>Ответ</summary>

Тег не изменился, спека пода осталась прежней — Deployment не видит изменений.
Правильно: уникальный тег на каждую сборку (например, с SHA коммита) плюс
`imagePullPolicy: IfNotPresent`; временный обход — `kubectl rollout restart`.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Что такое под и почему он, а не контейнер, минимальная единица? *(вопрос роадмапа)*

<details><summary>Ответ</summary>

Под — минимальная единица запуска: один или несколько контейнеров с общими сетью,
томами и жизненным циклом. Нужен, чтобы поддерживать паттерны с несколькими
процессами и планировать/адресовать неделимую единицу.

</details>

**2.** Что общего у контейнеров в поде?

<details><summary>Ответ</summary>

Сетевой namespace и IP, тома, IPC, метки, нода, жизненный цикл.

</details>

**3.** Какие бывают фазы пода?

<details><summary>Ответ</summary>

Pending, Running, Succeeded, Failed, Unknown.

</details>

**4.** Что такое CrashLoopBackOff и как отлаживать?

<details><summary>Ответ</summary>

Цикл падений с экспоненциальной задержкой; отладка: `logs --previous`, Exit Code
и Reason в `describe`, события, затем проверка команды, конфигов и зависимостей.

</details>

**5.** Что происходит при удалении пода? Какие сигналы и тайминги?

<details><summary>Ответ</summary>

Удаление из Endpoints + `preStop` + SIGTERM, ожидание grace period (30 с),
затем SIGKILL и удаление объекта.

</details>

**6.** Что такое init-контейнер и sidecar?

<details><summary>Ответ</summary>

Init-контейнер выполняется до основных и завершается; sidecar работает рядом
с приложением всё время жизни пода.

</details>

**7.** Что такое restartPolicy и как она сочетается с Deployment?

<details><summary>Ответ</summary>

Политика перезапуска контейнеров пода; Deployment требует `Always`,
`OnFailure`/`Never` используются в Job.

</details>

**8.** Почему нельзя запускать поды без контроллера?

<details><summary>Ответ</summary>

Некому восстановить под при падении ноды, нет обновлений и масштабирования,
состояние не описано в git.

</details>

**9.** Что означает Exit Code 137?

<details><summary>Ответ</summary>

Процесс убит SIGKILL: чаще всего превышение лимита памяти (OOMKilled).

</details>

**10.** Как приложение должно завершаться, чтобы деплой был без ошибок?

<details><summary>Ответ</summary>

Обрабатывать SIGTERM: прекратить приём новых запросов, дождаться текущих, закрыть
соединения и выйти; плюс `preStop`-пауза и корректная `readinessProbe`.

</details>

---

### 🎯 Чек-лист

- [ ] ⭐ Объясняю вслух, почему минимальная единица — под, а не контейнер
- [ ] Знаю все пять фаз и десяток типовых STATUS'ов
- [ ] Видел своими глазами CrashLoopBackOff, ImagePullBackOff, OOMKilled, Pending
- [ ] Читаю Exit Code и Reason из `describe`
- [ ] Понимаю цепочку удаления пода: Endpoints + preStop + SIGTERM + grace + SIGKILL
- [ ] Делал под с двумя контейнерами и проверял общий localhost и общий том
- [ ] Делал init-контейнер и понимаю, зачем он нужен
- [ ] Знаю, почему голые поды не используют в проде
- [ ] Не путаю `command`/`args` с ENTRYPOINT/CMD
