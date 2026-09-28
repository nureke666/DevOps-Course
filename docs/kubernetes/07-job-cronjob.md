---
title: "07. Job и CronJob"
description: "completions/parallelism/backoffLimit, CronJob и расписание, миграции БД как Job — конспект и задачи"
---

# 07. Job и CronJob

> Роадмап → 6. Kubernetes → Основные сущности → **Job**, **CronJob**.
> **После темы ты умеешь:** запускать разовые и периодические задачи, понимать
> `completions`/`parallelism`/`backoffLimit` и не разводить мусор из завершённых подов.

---

## 🗺️ Карта темы

```text:no-line-numbers
   JOB — «выполнить задачу до успешного завершения»
        │
        ├─ completions: 5     сколько успешных завершений нужно
        ├─ parallelism: 2     сколько подов работают одновременно
        ├─ backoffLimit: 4    сколько раз повторять при падении
        └─ ttlSecondsAfterFinished: 300   когда убрать за собой

   CRONJOB — «запускать Job по расписанию»
        │
        ├─ schedule: "*/5 * * * *"
        ├─ concurrencyPolicy: Allow | Forbid | Replace
        ├─ startingDeadlineSeconds
        └─ successfulJobsHistoryLimit / failedJobsHistoryLimit
```

---

## 1. Job

**Job** — контроллер, который создаёт под(ы) и следит, чтобы задача **успешно завершилась**.
В отличие от Deployment, цель не «работать всегда», а «доработать до конца».

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate
spec:
  backoffLimit: 3                 # сколько раз повторить при неудаче
  activeDeadlineSeconds: 600      # жёсткий таймаут всей задачи
  ttlSecondsAfterFinished: 3600   # удалить Job через час после завершения
  template:
    spec:
      restartPolicy: Never        # ⭐ обязательно Never или OnFailure
      containers:
        - name: migrate
          image: myapp:1.5.0
          command: ["./manage.py", "migrate"]
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef: { name: db-secret, key: url }
```

```bash
kubectl apply -f job.yaml
kubectl get jobs
# NAME         STATUS     COMPLETIONS   DURATION   AGE
# db-migrate   Complete   1/1           12s        1m

kubectl logs job/db-migrate
kubectl describe job db-migrate
kubectl delete job db-migrate
kubectl wait --for=condition=complete job/db-migrate --timeout=300s   # для скриптов
```

### Ключевые поля

| Поле | Смысл | Замечание |
|------|-------|-----------|
| `completions` | сколько подов должны успешно завершиться | по умолчанию 1 |
| `parallelism` | сколько подов работают одновременно | по умолчанию 1 |
| `backoffLimit` | сколько раз перезапускать под при неудаче | по умолчанию 6, задержка растёт экспоненциально |
| `activeDeadlineSeconds` | общий таймаут; по истечении Job помечается `Failed` и поды убиваются | ⭐ страховка от зависаний |
| `ttlSecondsAfterFinished` | автоудаление завершённого Job вместе с подами | ⭐ иначе поды копятся |
| `restartPolicy` | `Never` или `OnFailure` | `Always` запрещён |
| `completionMode` | `NonIndexed` (по умолчанию) или `Indexed` | Indexed даёт каждому поду номер в `JOB_COMPLETION_INDEX` |
| `suspend` | приостановить Job | удобно для «поставить в очередь» |

### `restartPolicy: Never` vs `OnFailure`

| | `Never` | `OnFailure` |
|---|---|---|
| Что делает при падении | создаётся **новый под** | перезапускается **контейнер в том же поде** |
| Логи прошлых попыток | сохраняются (поды остаются) | `kubectl logs --previous` |
| Когда лучше | нужен разбор каждой попытки | нужна экономия и быстрый повтор |

### Параллельные задачи

```yaml
spec:
  completions: 10          # всего 10 успешных завершений
  parallelism: 3           # по 3 одновременно
```
Типично для обработки очереди: 10 порций работы, 3 воркера одновременно.

```yaml
spec:
  completions: 5
  parallelism: 5
  completionMode: Indexed  # каждый под знает свой номер 0..4
```
Внутри пода номер доступен как переменная окружения `JOB_COMPLETION_INDEX` —
так делят датасет на части.

---

## 2. CronJob

**CronJob** создаёт Job по расписанию. Расписание — обычный cron из блока Linux.

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: backup
spec:
  schedule: "0 3 * * *"              # каждый день в 03:00
  timeZone: "Europe/Almaty"          # ⭐ иначе время UTC кластера
  concurrencyPolicy: Forbid
  startingDeadlineSeconds: 300
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  suspend: false
  jobTemplate:
    spec:
      backoffLimit: 2
      activeDeadlineSeconds: 3600
      ttlSecondsAfterFinished: 86400
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: backup
              image: postgres:16
              command: ["sh", "-c", "pg_dump -h postgres -U app app | gzip > /backup/$(date +%F).sql.gz"]
              env:
                - name: PGPASSWORD
                  valueFrom:
                    secretKeyRef: { name: db-secret, key: password }
              volumeMounts:
                - { name: backup, mountPath: /backup }
          volumes:
            - name: backup
              persistentVolumeClaim: { claimName: backup-pvc }
```

### Ключевые поля

| Поле | Смысл |
|------|-------|
| `schedule` | Cron-выражение: `мин час день месяц день-недели` |
| `timeZone` | ⭐ Часовой пояс расписания; без него — UTC |
| `concurrencyPolicy` | `Allow` (по умолчанию), `Forbid` (не запускать, если предыдущий ещё идёт), `Replace` (убить предыдущий и запустить новый) |
| `startingDeadlineSeconds` | сколько секунд «опоздания» допустимо; если контроллер лежал дольше — запуск пропускается |
| `successfulJobsHistoryLimit` / `failedJobsHistoryLimit` | сколько завершённых Job'ов хранить (по умолчанию 3 и 1) |
| `suspend` | `true` — временно отключить расписание |

```bash
kubectl get cronjobs
kubectl get jobs --watch
kubectl create job manual-backup --from=cronjob/backup     # ⭐ запустить прямо сейчас
kubectl patch cronjob backup -p '{"spec":{"suspend":true}}'  # выключить
kubectl logs job/backup-28374920
```

### Напоминание про cron-синтаксис

```text:no-line-numbers
 ┌───────── минута (0-59)
 │ ┌─────── час (0-23)
 │ │ ┌───── день месяца (1-31)
 │ │ │ ┌─── месяц (1-12)
 │ │ │ │ ┌─ день недели (0-6, 0=воскресенье)
 │ │ │ │ │
 * * * * *
```

| Выражение | Когда |
|-----------|-------|
| `*/5 * * * *` | каждые 5 минут |
| `0 * * * *` | каждый час |
| `0 3 * * *` | ежедневно в 03:00 |
| `0 3 * * 0` | по воскресеньям в 03:00 |
| `0 0 1 * *` | первого числа каждого месяца |

---

## 3. Типовые грабли

| Грабля | Симптом | Лечение |
|--------|---------|---------|
| Не задан `ttlSecondsAfterFinished` | Сотни `Completed`-подов в namespace | Поставить TTL или уменьшить `historyLimit` |
| `restartPolicy: Always` | Ошибка валидации | Только `Never`/`OnFailure` |
| Нет `activeDeadlineSeconds` | Job висит вечно на зависшем запросе | Поставить таймаут |
| `concurrencyPolicy: Allow` у долгой задачи | Наложение запусков, дубли, гонки | `Forbid` |
| Нет `timeZone` | Бэкап в 3:00 UTC вместо местного времени | Указать `timeZone` |
| `backoffLimit` слишком большой | Долго и дорого повторяем заведомо битую задачу | 2-4 достаточно |
| Задача неидемпотентна | Повтор делает двойную работу | Делать операции идемпотентными или ставить блокировку |
| Job в составе деплоя без hook'а | Миграции стартуют одновременно с новым кодом | Helm-hook `pre-upgrade` (тема 15) или init-контейнер |
| CronJob «пропустил» запуски | Контроллер лежал дольше `startingDeadlineSeconds` | Осознанно выбрать значение |

---

## 4. Миграции БД как Job — типовой рецепт

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: migrate-1-5-0            # ⭐ уникальное имя на релиз: Job иммутабелен
spec:
  backoffLimit: 1
  activeDeadlineSeconds: 900
  ttlSecondsAfterFinished: 86400
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: myapp:1.5.0     # тот же образ, что у приложения
          command: ["alembic", "upgrade", "head"]
          envFrom:
            - secretRef: { name: db-secret }
```

В пайплайне:
```bash
kubectl apply -f migrate-job.yaml
kubectl wait --for=condition=complete job/migrate-1-5-0 --timeout=900s || {
  kubectl logs job/migrate-1-5-0
  exit 1
}
kubectl set image deploy/app app=myapp:1.5.0
```

> ⚠️ **Job почти иммутабелен:** нельзя поменять `template` у существующего Job.
> Поэтому в имя включают версию/хеш коммита, либо удаляют старый Job перед созданием
> (в Helm это решается хуками с политикой `before-hook-creation`).

---

## 💼 Как это в DevOps

- Job — стандартный способ выполнить миграции, прогрев кэша, разовую починку данных.
- CronJob заменяет crontab на серверах: бэкапы, отчёты, чистка, синхронизации.
  Плюс в том, что расписание лежит в git и выполняется в кластере, а не «на той машине».
- Мониторить CronJob обязательно: молчащий сломанный бэкап хуже отсутствующего.
  Минимум — алерт на `kube_job_status_failed` и на «давно не было успешного запуска».
- `ttlSecondsAfterFinished` — то, о чём забывают все и всегда; потом чистят вручную.
- Для сложных пайплайнов задач (DAG, зависимости, ретраи) берут Argo Workflows
  или Airflow — CronJob для них слишком прост.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Разовая задача | `kind: Job` |
| Задача по расписанию | `kind: CronJob` |
| Запустить CronJob сейчас | `kubectl create job manual --from=cronjob/NAME` |
| Временно выключить CronJob | `kubectl patch cronjob NAME -p '{"spec":{"suspend":true}}'` |
| Логи задачи | `kubectl logs job/NAME` |
| Дождаться завершения | `kubectl wait --for=condition=complete job/NAME --timeout=300s` |
| Не копить поды | `ttlSecondsAfterFinished` + `historyLimit` |
| Не допускать наложения | `concurrencyPolicy: Forbid` |
| Ограничить время выполнения | `activeDeadlineSeconds` |
| Параллельная обработка | `completions` + `parallelism` |
| Номер порции внутри пода | `completionMode: Indexed` → `$JOB_COMPLETION_INDEX` |

---

## 🧠 Что запомнить

1. Job — «выполнить до успешного завершения», Deployment — «работать всегда».
2. `restartPolicy` у Job только `Never` или `OnFailure`; `Always` запрещён.
3. `completions` — сколько успехов нужно, `parallelism` — сколько подов одновременно.
4. `backoffLimit` ограничивает число повторов; задержка между ними растёт.
5. `activeDeadlineSeconds` — единственная защита от вечно висящей задачи.
6. `ttlSecondsAfterFinished` убирает завершённые Job'ы; без него копится мусор.
7. CronJob создаёт Job по расписанию; без `timeZone` расписание идёт по UTC.
8. `concurrencyPolicy: Forbid` спасает от наложения долгих запусков.
9. Запустить CronJob вручную: `kubectl create job --from=cronjob/NAME`.
10. Job практически иммутабелен — включай версию в имя.
11. Задача должна быть идемпотентной: повтор обязан быть безопасным.
12. Сломанный CronJob незаметен без мониторинга — ставь алерт на отсутствие успехов.

---

## Задачи

> Практический смысл темы: перенести crontab с серверов в кластер и научиться
> запускать миграции так, чтобы они не ломали деплой.

---

### Блок A. Теория

**A1.** Чем Job отличается от Deployment по цели?

<details><summary>Ответ</summary>

Job выполняет задачу до успешного завершения и останавливается;
Deployment поддерживает постоянно работающее приложение.

</details>

**A2.** Какие значения `restartPolicy` допустимы у Job и почему `Always` запрещён?

<details><summary>Ответ</summary>

`Never` и `OnFailure`. `Always` означал бы бесконечный перезапуск,
что противоречит идее «задача завершается».

</details>

**A3.** ⭐ Что делают `completions` и `parallelism`? Приведи пример пары значений.

<details><summary>Ответ</summary>

`completions` — сколько подов должны успешно завершиться,
`parallelism` — сколько выполняется одновременно. Например, `completions: 10`,
`parallelism: 3` — десять порций работы тремя воркерами.

</details>

**A4.** Что такое `backoffLimit` и что произойдёт при его исчерпании?

<details><summary>Ответ</summary>

Максимальное число неудачных попыток. При исчерпании Job помечается
`Failed`, новые поды не создаются.

</details>

**A5.** Зачем нужен `activeDeadlineSeconds`?

<details><summary>Ответ</summary>

Ограничивает общее время выполнения: по истечении поды убиваются,
Job переходит в `Failed`. Защита от зависших задач.

</details>

**A6.** Что делает `ttlSecondsAfterFinished` и что будет без него?

<details><summary>Ответ</summary>

Удаляет завершённый Job (и его поды) через указанное время.
Без него завершённые объекты остаются навсегда и засоряют namespace.

</details>

**A7.** Чем `restartPolicy: Never` отличается от `OnFailure` на практике?

<details><summary>Ответ</summary>

`Never` создаёт новый под на каждую попытку (видны все попытки отдельно);
`OnFailure` перезапускает контейнер в том же поде (логи прошлого — через `--previous`).

</details>

**A8.** Что такое `completionMode: Indexed` и какая переменная появляется в поде?

<details><summary>Ответ</summary>

Каждый под получает уникальный индекс от 0 до `completions-1`;
он доступен в переменной `JOB_COMPLETION_INDEX` и в аннотации пода.

</details>

**A9.** Как посмотреть логи задачи, не зная имени пода?

<details><summary>Ответ</summary>

`kubectl logs job/NAME` (возьмёт один из подов задачи).

</details>

**A10.** Как дождаться завершения Job в скрипте?

<details><summary>Ответ</summary>

`kubectl wait --for=condition=complete job/NAME --timeout=300s`.

</details>

**A11.** ⭐ Что такое CronJob и что он создаёт при срабатывании?

<details><summary>Ответ</summary>

Контроллер, создающий Job по расписанию; каждое срабатывание —
это новый объект Job со своими подами.

</details>

**A12.** Какие значения принимает `concurrencyPolicy` и что каждое означает?

<details><summary>Ответ</summary>

`Allow` — разрешить параллельные запуски; `Forbid` — пропустить запуск,
если предыдущий ещё идёт; `Replace` — остановить текущий и запустить новый.

</details>

**A13.** Зачем нужен `startingDeadlineSeconds`?

<details><summary>Ответ</summary>

Задаёт, сколько секунд опоздания допустимо. Если контроллер был недоступен
дольше, пропущенный запуск не выполняется (иначе после простоя накопится шквал задач).

</details>

**A14.** В каком часовом поясе выполняется расписание по умолчанию и как это изменить?

<details><summary>Ответ</summary>

По умолчанию — UTC (время контроллера). Изменяется полем `timeZone`.

</details>

**A15.** Что делают `successfulJobsHistoryLimit` и `failedJobsHistoryLimit`?

<details><summary>Ответ</summary>

Сколько успешных и неуспешных Job'ов хранить в истории (по умолчанию 3 и 1).

</details>

**A16.** Как временно отключить CronJob, не удаляя его?

<details><summary>Ответ</summary>

`spec.suspend: true` (например, через `kubectl patch`).

</details>

**A17.** Как запустить CronJob немедленно, вне расписания?

<details><summary>Ответ</summary>

`kubectl create job NAME --from=cronjob/CRONJOB_NAME`.

</details>

**A18.** Расшифруй: `*/10 * * * *`, `0 2 * * 1-5`, `30 23 1 * *`.

<details><summary>Ответ</summary>

Каждые 10 минут; в 02:00 с понедельника по пятницу; в 23:30 первого числа
каждого месяца.

</details>

**A19.** Почему Job считается почти иммутабельным и как с этим жить в пайплайне?

<details><summary>Ответ</summary>

Шаблон пода у созданного Job менять нельзя. В пайплайне создают Job
с уникальным именем (версия/хеш коммита) или удаляют старый перед применением.

</details>

**A20.** Почему задача в Job должна быть идемпотентной?

<details><summary>Ответ</summary>

Кубер может перезапустить под (падение, вытеснение, повтор по `backoffLimit`),
поэтому задача должна безопасно переживать повторный запуск.

</details>

**A21.** Как правильно выполнять миграции БД при деплое? Три варианта.

<details><summary>Ответ</summary>

(1) Отдельный Job перед обновлением Deployment; (2) Helm-хук `pre-upgrade`;
(3) init-контейнер приложения с блокировкой (одна реплика применяет, остальные ждут).
Главное — не запускать миграции параллельно из всех реплик.

</details>

**A22.** Как мониторить, что ночной бэкап отработал?

<details><summary>Ответ</summary>

Алерт по метрикам kube-state-metrics: время последнего успешного запуска
(`kube_cronjob_status_last_successful_time`) и число неудачных Job'ов;
плюс проверка самого артефакта (размер и свежесть файла бэкапа).

</details>

**A23.** Когда CronJob уже недостаточно и нужен Argo Workflows/Airflow?

<details><summary>Ответ</summary>

Когда нужны зависимости между шагами (DAG), передача артефактов,
условные ветки, сложные ретраи и визуализация пайплайна.

</details>

**A24.** Что произойдёт, если под Job вытеснят с ноды (eviction)?

<details><summary>Ответ</summary>

Job создаст новый под (в пределах `backoffLimit`), и задача выполнится ещё раз —
ещё один аргумент в пользу идемпотентности.

</details>

**A25.** Может ли Job иметь несколько контейнеров? Когда это оправдано?

<details><summary>Ответ</summary>

Да. Оправдано, когда задаче нужен sidecar (прокси к БД, доступ к секретам);
при этом важно, чтобы sidecar не мешал поду завершиться — для этого и придуманы
init-контейнеры с `restartPolicy: Always`.

</details>

---

### Блок B. «Что произойдёт»

**B1.**
```yaml
kind: Job
spec:
  template:
    spec:
      restartPolicy: Always
```
Вопрос: что ответит `kubectl apply`?

<details><summary>Ответ</summary>

Ошибка валидации: для Job допустимы только `Never` и `OnFailure`.

</details>

**B2.**
```yaml
kind: Job
spec:
  completions: 6
  parallelism: 2
```
Вопрос: сколько подов будет работать одновременно и сколько всего успешных завершений нужно?

<details><summary>Ответ</summary>

Одновременно два пода, всего требуется шесть успешных завершений.

</details>

**B3.**
```yaml
kind: Job
spec:
  backoffLimit: 2
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: fail
          image: busybox
          command: ["sh","-c","exit 1"]
```
Вопрос: сколько подов будет создано и в каком состоянии окажется Job?

<details><summary>Ответ</summary>

Три пода (первая попытка плюс два повтора), Job в состоянии `Failed`
с причиной `BackoffLimitExceeded`.

</details>

**B4.**
```yaml
kind: CronJob
spec:
  schedule: "*/1 * * * *"
  concurrencyPolicy: Allow
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - command: ["sh","-c","sleep 300"]
```
Вопрос: сколько задач будет работать одновременно через 5 минут?

<details><summary>Ответ</summary>

Задача длится 5 минут, запускается каждую минуту, наложение разрешено —
к пятой минуте будет примерно пять одновременно работающих Job'ов.

</details>

**B5.**
```yaml
spec:
  concurrencyPolicy: Forbid
```
Вопрос: как изменится картина из B4?

<details><summary>Ответ</summary>

С `Forbid` новые запуски будут пропускаться, пока идёт предыдущий:
одновременно всегда один Job.

</details>

**B6.**
```yaml
spec:
  schedule: "0 3 * * *"
# кластер в UTC, разработчик в Almaty (UTC+5)
```
Вопрос: во сколько по местному времени сработает задача и как починить?

<details><summary>Ответ</summary>

Сработает в 08:00 по Алматы (03:00 UTC). Лечение — поле `timeZone`
(или пересчёт расписания в UTC).

</details>

**B7.**
```bash
kubectl get pods
# backup-28374-abc   0/1   Completed   0   3d
# backup-28375-def   0/1   Completed   0   3d
# ... 150 подобных строк
```
Вопрос: что не настроено?

<details><summary>Ответ</summary>

Не задан `ttlSecondsAfterFinished` (и/или слишком большие historyLimit'ы).

</details>

**B8.**
```bash
kubectl apply -f job.yaml      # меняли только образ в существующем Job
# The Job "migrate" is invalid: spec.template: Invalid value: ... field is immutable
```
Вопрос: почему и как правильно?

<details><summary>Ответ</summary>

`spec.template` у Job иммутабелен. Правильно — создавать Job с новым именем
на каждый релиз или удалять старый перед применением.

</details>

**B9.**
```yaml
kind: CronJob
spec:
  schedule: "0 * * * *"
  startingDeadlineSeconds: 100
# контроллер был недоступен 3 часа
```
Вопрос: сколько запусков состоится после восстановления?

<details><summary>Ответ</summary>

Один: пропущенные запуски старше `startingDeadlineSeconds` не выполняются,
а выполняется только ближайший подходящий.

</details>

---

### Блок C. Практика

#### C1. 🔑 Первый Job
Напиши Job, который выводит дату и завершается. Проверь:
`kubectl get jobs`, `kubectl get pods`, `kubectl logs job/NAME`.
Запиши, что происходит с подом после завершения.

#### C2. Падающий Job
Сделай Job с `exit 1`, `backoffLimit: 2`, `restartPolicy: Never`.
1. Посчитай, сколько подов создалось.
2. Посмотри условия в `kubectl describe job`.
3. Повтори с `restartPolicy: OnFailure` и сравни поведение.

<details><summary>Ответ</summary>

При `Never` создаётся по новому поду на попытку (видно все три);
при `OnFailure` под один, растёт счётчик рестартов контейнера.

</details>

#### C3. 🔑 Параллельная обработка
Job с `completions: 6`, `parallelism: 2`, контейнер спит случайное время и выводит
номер. Наблюдай `kubectl get pods -w`. Зафиксируй, как поды сменяют друг друга.

#### C4. Indexed Job
Сделай `completionMode: Indexed`, `completions: 4`, и пусть каждый под печатает
`$JOB_COMPLETION_INDEX`. Объясни, как это использовать для деления датасета.

#### C5. Таймаут
Job со `sleep 600` и `activeDeadlineSeconds: 30`. Дождись результата,
посмотри причину в `describe`. Запиши, что стало с подом.

<details><summary>Ответ</summary>

Job переходит в `Failed` с причиной `DeadlineExceeded`, под убивается.

</details>

#### C6. TTL
Job с `ttlSecondsAfterFinished: 60`. Дождись завершения и проверь через минуту,
что объект исчез сам. Сравни с Job без TTL.

#### C7. 🔑 CronJob каждую минуту
CronJob `*/1 * * * *`, который пишет дату.
1. Понаблюдай 5 минут: сколько Job'ов и подов накопилось?
2. Проверь `successfulJobsHistoryLimit` в действии.
3. Выключи через `suspend`, убедись, что новые не появляются.
4. Включи обратно.

<details><summary>Ответ</summary>

Останется столько завершённых Job'ов, сколько указано в
`successfulJobsHistoryLimit` (по умолчанию 3); остальные удаляются контроллером.

</details>

#### C8. concurrencyPolicy
CronJob `*/1 * * * *` с задачей на 3 минуты.
1. Запусти с `Allow` — посчитай одновременные задачи.
2. Переключи на `Forbid` — что изменилось?
3. Переключи на `Replace` — что происходит со старой задачей?

<details><summary>Ответ</summary>

`Allow` — задачи накапливаются; `Forbid` — работает всегда одна;
`Replace` — старая задача убивается, стартует новая.

</details>

#### C9. Ручной запуск
```bash
kubectl create job manual-$(date +%s) --from=cronjob/backup
```
Проверь логи. Объясни, когда это нужно (подсказка: отладка и «перезапустить ночной
бэкап днём»).

#### C10. 🔑 Миграции перед деплоем
Собери мини-пайплайн локально:
1. Job `migrate-<версия>` с уникальным именем.
2. `kubectl wait --for=condition=complete` с таймаутом.
3. При успехе — `kubectl set image` для Deployment.
4. При неудаче — вывести логи и выйти с ошибкой.
Оформи как bash-скрипт; он пригодится в лабе по CI/CD.

#### C11. Бэкап БД по расписанию
CronJob, который делает `pg_dump` базы из темы 06 на PVC.
1. Проверь, что файл появился.
2. Сломай доступ (неверный пароль) и убедись, что Job падает.
3. Настрой `failedJobsHistoryLimit` так, чтобы видеть неудачи.

#### C12. Часовой пояс
Поставь `schedule: "*/2 * * * *"` и `timeZone: "Europe/Almaty"`.
Сверь фактическое время запуска с локальным. Потом убери `timeZone` и сравни.

#### C13. Идемпотентность (со звёздочкой)
Напиши задачу, которая добавляет строку в файл на PVC. Запусти её три раза.
Перепиши так, чтобы повторный запуск не дублировал данные. Сформулируй правило.

<details><summary>Ответ</summary>

Правило: результат повторного запуска должен совпадать с результатом
однократного. Способы: проверка «уже сделано» перед действием, уникальные ключи
и upsert вместо insert, файлы-маркеры, блокировки.

</details>

#### C14. Мониторинг CronJob (со звёздочкой)
Придумай, как алертить о том, что бэкап не отрабатывал 26 часов.
Какие метрики нужны (подсказка: kube-state-metrics, `kube_cronjob_status_last_schedule_time`,
`kube_job_status_failed`)?

---

### Блок D. Инциденты

**D1.** В namespace 400 подов в статусе `Completed`. Кластер жалуется на лимиты.
Причина и лечение.

<details><summary>Ответ</summary>

Не настроены `ttlSecondsAfterFinished` и history-лимиты. Лечение:
задать их, удалить накопившееся (`kubectl delete job --field-selector status.successful=1`).

</details>

**D2.** Ночной бэкап не выполнялся две недели, никто не заметил. Что настроить,
чтобы это стало невозможно?

<details><summary>Ответ</summary>

Мониторинг: алерт на отсутствие успешного запуска дольше N часов,
алерт на неудачные Job'ы, проверка свежести и размера артефакта бэкапа,
и — обязательно — регулярные тестовые восстановления.

</details>

**D3.** CronJob каждую минуту запускает задачу, которая идёт 10 минут. Через час
кластер забит подами. Что не так?

<details><summary>Ответ</summary>

`concurrencyPolicy: Allow` при задаче длиннее интервала. Нужны `Forbid`
(или `Replace`), плюс `activeDeadlineSeconds`.

</details>

**D4.** Job с миграциями запустился одновременно в трёх копиях и повредил схему.
Как такое возможно и как предотвратить?

<details><summary>Ответ</summary>

Миграции запускались из init-контейнера всех реплик (или Job был запущен
несколько раз). Нужен один Job с уникальным именем либо блокировка на уровне БД.

</details>

**D5.** Задача зависла на HTTP-запросе к недоступному сервису и висит третьи сутки.
Чего не хватает в манифесте?

<details><summary>Ответ</summary>

`activeDeadlineSeconds` (а также разумный `backoffLimit` и таймауты
в самом приложении).

</details>

**D6.** Бэкап выполняется в 3:00, но данные в нём от 22:00 предыдущего дня.
Что стоит проверить в первую очередь?

<details><summary>Ответ</summary>

Логику самой задачи: возможно, дамп снимается с реплики с отставанием,
либо путь/файл переиспользуется, либо время формирования имени файла в UTC.

</details>

**D7.** После обновления приложения деплой прошёл, но приложение падает:
миграции не применились. Как надо было организовать порядок?

<details><summary>Ответ</summary>

Миграции должны выполняться отдельным шагом до обновления образа
и блокировать деплой при неудаче (`kubectl wait` с проверкой кода возврата).

</details>

**D8.** `kubectl apply` на существующий Job выдаёт ошибку иммутабельности.
Что делать в пайплайне?

<details><summary>Ответ</summary>

Генерировать имя Job с хешем коммита либо удалять предыдущий Job
перед применением; в Helm — хуки с `hook-delete-policy`.

</details>

**D9.** CronJob пропустил запуск после недоступности control plane.
Как это регулируется и что выбрать для бэкапов?

<details><summary>Ответ</summary>

Полем `startingDeadlineSeconds`. Для бэкапов обычно лучше выполнить запуск
с опозданием, чем пропустить: значение ставят достаточно большим и осознанно.

</details>

**D10.** Под Job был вытеснен с ноды, и задача выполнилась дважды.
Какие требования это накладывает на задачу?

<details><summary>Ответ</summary>

Задача обязана быть идемпотентной и, по возможности, использовать
внешнюю блокировку или маркер завершения.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое Job и чем отличается от Deployment?

<details><summary>Ответ</summary>

Job выполняет конечную задачу до успеха и завершается; Deployment держит
постоянно работающее приложение.

</details>

**2.** Что такое CronJob и как задаётся расписание?

<details><summary>Ответ</summary>

Контроллер, создающий Job по cron-расписанию; расписание — стандартные пять полей,
плюс `timeZone`.

</details>

**3.** Что делают completions и parallelism?

<details><summary>Ответ</summary>

`completions` — сколько успешных завершений требуется, `parallelism` —
сколько подов работает одновременно.

</details>

**4.** Как ограничить число повторов и общее время выполнения?

<details><summary>Ответ</summary>

`backoffLimit` ограничивает повторы, `activeDeadlineSeconds` — общее время.

</details>

**5.** Как избежать наложения запусков?

<details><summary>Ответ</summary>

`concurrencyPolicy: Forbid` (или `Replace`), плюс адекватные интервалы и таймауты.

</details>

**6.** Как запустить CronJob вне расписания?

<details><summary>Ответ</summary>

`kubectl create job NAME --from=cronjob/NAME`.

</details>

**7.** Как правильно выполнять миграции БД в кубере?

<details><summary>Ответ</summary>

Отдельным Job до обновления образа (или Helm-хуком `pre-upgrade`),
с ожиданием завершения и блокировкой деплоя при неудаче; миграции — обратно совместимые.

</details>

**8.** Почему завершённые поды копятся и как это чинить?

<details><summary>Ответ</summary>

Не задан TTL и history-лимиты; задать `ttlSecondsAfterFinished`
и `successfulJobsHistoryLimit`.

</details>

**9.** Что такое идемпотентность задачи и почему она обязательна?

<details><summary>Ответ</summary>

Повторный запуск не должен менять результат: кубер имеет право перезапустить под,
поэтому неидемпотентная задача рано или поздно навредит.

</details>

**10.** Как мониторить регулярные задачи?

<details><summary>Ответ</summary>

Через kube-state-metrics: время последнего успешного запуска, счётчик неудач,
длительность; плюс проверка результата самой задачи.

</details>

---

### 🎯 Чек-лист

- [ ] Понимаю разницу Job и Deployment
- [ ] Запускал Job с `completions`/`parallelism` и наблюдал очередь подов
- [ ] Знаю про `backoffLimit`, `activeDeadlineSeconds`, `ttlSecondsAfterFinished`
- [ ] Настроил CronJob с `timeZone` и проверил фактическое время запуска
- [ ] Понимаю все три значения `concurrencyPolicy`
- [ ] Умею запускать CronJob вручную и приостанавливать его
- [ ] Собрал сценарий «миграции Job → деплой» с ожиданием и проверкой
- [ ] Знаю, почему завершённые поды копятся, и настроил TTL
- [ ] Продумал, как алертить о несработавшем бэкапе
