---
title: "03. Application: синхронизация и здоровье"
description: "Устройство Application, sync- и health-статусы, automated/prune/selfHeal, sync waves и hooks, ignoreDifferences, откаты"
---

# 03. Application: синхронизация и здоровье ⭐

> Роадмап → GitOps: *«…подключить репу гита, задеплоить что-то»*.
>
> **После темы ты умеешь:** описать `Application`, управлять автоматической
> синхронизацией, self-heal и prune, читать статусы, откатывать релизы
> и разбирать типовые проблемы.

---

## 🗺️ Что такое `Application`

```text:no-line-numbers
 ┌──────────────────────────────────────────────────────────────────────┐
 │  Application = «ЧТО брать» + «КУДА разворачивать» + «КАК синхронизировать» │
 │                                                                      │
 │  source:      repoURL + path + targetRevision                        │
 │  destination: server (кластер) + namespace                           │
 │  syncPolicy:  вручную / автоматически (+ prune, selfHeal)            │
 └──────────────────────────────────────────────────────────────────────┘
```

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: demo
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io    # ⭐ удалять ресурсы при удалении Application
spec:
  project: default

  source:
    repoURL: https://gitlab.com/org/k8s-manifests.git
    path: apps/demo                              # каталог с манифестами
    targetRevision: main                         # ветка, тег или коммит

  destination:
    server: https://kubernetes.default.svc       # или name: prod-cluster
    namespace: demo

  syncPolicy:
    automated:
      prune: true        # ⭐ удалять из кластера то, чего больше нет в git
      selfHeal: true     # ⭐ возвращать состояние при ручных правках
      allowEmpty: false  # не синхронизировать, если манифестов не осталось
    syncOptions:
      - CreateNamespace=true
      - PrunePropagationPolicy=foreground
      - ServerSideApply=true
    retry:
      limit: 5
      backoff: { duration: 5s, factor: 2, maxDuration: 3m }
```

```bash
# то же самое через CLI
argocd app create demo \
  --repo https://gitlab.com/org/k8s-manifests.git \
  --path apps/demo --dest-server https://kubernetes.default.svc \
  --dest-namespace demo --sync-policy automated --auto-prune --self-heal
```

---

## 1. Два статуса, на которые смотрят каждый день ⭐

```text:no-line-numbers
 SYNC STATUS                         HEALTH STATUS
 ──────────                          ─────────────
 Synced     кластер = git            Healthy     всё работает
 OutOfSync  есть расхождение         Progressing идёт раскатка
 Unknown    не удалось сравнить      Degraded    ⚠️ что-то сломано
                                     Missing     ресурса нет
                                     Suspended   приостановлено
```

| Комбинация | Что значит |
|------------|-----------|
| Synced + Healthy | ✅ Норма |
| Synced + Degraded | Применено из git, но приложение не работает (падает под, не проходит проба) |
| OutOfSync + Healthy | Работает, но отличается от git: ручная правка или новый коммит |
| OutOfSync + Degraded | ⚠️ Плохой деплой: и расхождение, и поломка |
| Unknown | Проблема с репозиторием, доступом или рендерингом |

```bash
argocd app list
argocd app get demo                 # статусы, дерево ресурсов, последние события
argocd app diff demo                # ⭐ чем кластер отличается от git
argocd app sync demo                # синхронизировать вручную
argocd app sync demo --prune
argocd app history demo             # история синхронизаций
argocd app rollback demo 12         # откат на ревизию из истории
argocd app logs demo                # логи подов приложения
argocd app delete demo              # удалить Application (и ресурсы, если есть finalizer)
```

---

## 2. `automated`, `prune`, `selfHeal` — что включать

| Опция | Что делает | Когда включать |
|-------|-----------|----------------|
| `automated` | Синхронизировать без кнопки | dev/stage — сразу; prod — когда есть доверие к процессу |
| `prune: true` | Удалять ресурсы, исчезнувшие из git | ⭐ Нужен, иначе «мусор» копится; осторожно на старте |
| `selfHeal: true` | Возвращать ручные правки к состоянию из git | ⭐ Главная защита от дрейфа |
| `allowEmpty: false` | Не применять пустой набор манифестов | Защита от «удалили всё случайно» |

```text:no-line-numbers
Типичный сценарий внедрения:
 1. automated: off      — смотрим diff, синхронизируем руками, привыкаем
 2. automated: on       — автоматическая раскатка коммитов
 3. selfHeal: on        — запрещаем ручные правки де-факто
 4. prune: on           — приводим кластер в полное соответствие git
```

⚠️ `prune` без аккуратности может удалить ресурсы, созданные другими инструментами
в том же namespace. Поэтому namespace приложений разделяют, а чужие ресурсы
помечают `argocd.argoproj.io/sync-options: Prune=false`.

---

## 3. Порядок применения: sync waves и hooks

```yaml
# ресурсы применяются волнами: сначала меньшие номера
metadata:
  annotations:
    argocd.argoproj.io/sync-wave: "-1"      # например, CRD и namespace
```
```yaml
# hook: миграция БД перед синхронизацией
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate
  annotations:
    argocd.argoproj.io/hook: PreSync            # PreSync | Sync | PostSync | SyncFail
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec: { template: { spec: { restartPolicy: Never, containers: [ ... ] } } }
```

| Hook | Когда выполняется |
|------|-------------------|
| `PreSync` | До применения манифестов (миграции БД) ⭐ |
| `Sync` | Вместе с основными ресурсами |
| `PostSync` | После успешного применения (прогрев кэша, уведомление) |
| `SyncFail` | При неудачной синхронизации (откат, оповещение) |

---

## 4. Полезные `syncOptions` и аннотации

| Опция | Зачем |
|-------|-------|
| `CreateNamespace=true` | Создать namespace, если его нет |
| `ServerSideApply=true` | Применять на стороне сервера — спасает от «too long» и конфликтов полей |
| `PrunePropagationPolicy=foreground` | Корректный порядок удаления |
| `Replace=true` | `kubectl replace` вместо apply (для проблемных ресурсов) |
| `ApplyOutOfSyncOnly=true` | Применять только изменившиеся ресурсы (ускоряет большие приложения) |
| `RespectIgnoreDifferences=true` | Учитывать блок `ignoreDifferences` при синхронизации |

```yaml
# не считать расхождением поля, которыми управляет кластер/HPA
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas          # ⭐ если реплики меняет HPA
```
```yaml
# отдельный ресурс исключить из prune
metadata:
  annotations:
    argocd.argoproj.io/sync-options: Prune=false
```

---

## 5. Health-проверки

ArgoCD знает, как проверять здоровье стандартных ресурсов (Deployment, StatefulSet,
Service, Ingress, Job), и считает приложение `Healthy`, когда здоровы все его ресурсы.

Для своих CRD пишут проверку на Lua в `argocd-cm`:
```yaml
data:
  resource.customizations.health.example.com_MyKind: |
    hs = {}
    if obj.status ~= nil and obj.status.phase == "Ready" then
      hs.status = "Healthy"; hs.message = "ok"
    else
      hs.status = "Progressing"; hs.message = "waiting"
    end
    return hs
```

---

## 6. Откаты и история

```text:no-line-numbers
 ПРАВИЛЬНЫЙ ОТКАТ (GitOps)              БЫСТРЫЙ ОТКАТ (аварийный)
 ─────────────────────────              ─────────────────────────
 git revert <commit> && git push        argocd app rollback demo <ID>
        │                                      │
 Argo применит предыдущее состояние      применит прошлую синхронизацию,
 git и кластер согласованы ✅             но git остался «сломанным» ⚠️
                                         ⇒ после инцидента обязательно
                                            зафиксировать откат в git
```

```bash
argocd app history demo
argocd app rollback demo 12
```
⚠️ При `selfHeal: true` откат через `rollback` будет тут же «вылечен» обратно к git —
поэтому в GitOps аварийный откат почти всегда сопровождается коммитом.

---

## 7. Разбор типовых проблем

```text:no-line-numbers
Приложение OutOfSync
 ├─ argocd app diff demo         ← что именно отличается
 ├─ поле меняет кластер/HPA?     ← ignoreDifferences
 ├─ кто-то правил руками?        ← selfHeal вернёт, дрейф устранён
 └─ новый коммит не применён?    ← automated выключен или sync failed

Приложение Degraded
 ├─ argocd app get demo          ← какой ресурс болеет
 ├─ kubectl describe pod ...     ← ImagePullBackOff, OOMKilled, пробы
 ├─ argocd app logs demo         ← логи приложения
 └─ ресурсы/лимиты/квоты namespace

Sync failed
 ├─ ошибка валидации манифеста   ← kubectl apply --dry-run=server
 ├─ нет прав у ArgoCD            ← RBAC в целевом кластере / AppProject
 ├─ конфликт полей               ← ServerSideApply=true
 └─ hook (Job) упал              ← логи Job
```

---

## 8. Грабли

| Грабля | Последствие | Решение |
|--------|-------------|---------|
| `targetRevision: HEAD`/`main` на проде | Прод меняется от любого коммита | Теги или отдельная ветка релиза |
| Нет `finalizer` | Удалили Application — ресурсы остались в кластере | `resources-finalizer.argocd.argoproj.io` |
| `prune` в общем namespace | Удалены чужие ресурсы | Отдельные namespace, `Prune=false` |
| `selfHeal` не включён | Ручные правки живут вечно | Включить и объяснить команде |
| HPA + фиксированные replicas в git | Вечный OutOfSync | `ignoreDifferences` на `/spec/replicas` |
| Секреты в манифестах открыто | Утечка | SOPS/Sealed Secrets/ESO (тема 05) |
| Миграции БД в обычном манифесте | Гонки при раскатке | PreSync-hook |
| Откат только через `rollback` | Git и кластер расходятся | Откат коммитом |
| Одно Application на весь кластер | Непрозрачно, тяжело | Разделение по приложениям и командам |

---

## 💼 Как это в DevOps

- Каждый сервис — отдельный `Application`; платформенные компоненты — тоже,
  но в своём проекте и namespace.
- На проде часто `targetRevision` указывает на тег или релизную ветку, чтобы
  коммит в `main` не уезжал в прод автоматически.
- `selfHeal` и `prune` — то, ради чего внедряют GitOps; но включают их постепенно,
  начиная с dev.
- Уведомления о `Degraded`/`SyncFailed` в чат команды — обязательная часть эксплуатации.
- Миграции БД делают PreSync-хуком или отдельным шагом, а не «внутри деплоя приложения».

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Создать приложение | `Application` (декларативно) или `argocd app create` |
| Смотреть состояние | `argocd app get NAME`, UI |
| Увидеть расхождение | `argocd app diff NAME` |
| Синхронизировать | `argocd app sync NAME [--prune]` |
| Включить автосинхронизацию | `syncPolicy.automated` |
| Лечить ручные правки | `selfHeal: true` |
| Удалять исчезнувшее из git | `prune: true` |
| Создать namespace автоматически | `syncOptions: CreateNamespace=true` |
| Игнорировать поле | `ignoreDifferences` |
| Исключить ресурс из prune | аннотация `sync-options: Prune=false` |
| Порядок применения | аннотация `sync-wave` |
| Миграция перед деплоем | hook `PreSync` |
| История и откат | `argocd app history` / `argocd app rollback` |
| Удалить ресурсы вместе с Application | `finalizers: resources-finalizer...` |
| Логи приложения | `argocd app logs NAME` |

---

## 🧠 Что запомнить

1. `Application` = источник (repo/path/revision) + назначение (кластер/namespace) +
   политика синхронизации.
2. ⭐ Два независимых статуса: sync (`Synced`/`OutOfSync`) и health
   (`Healthy`/`Progressing`/`Degraded`).
3. `automated` включает автосинхронизацию, `selfHeal` лечит ручные правки,
   `prune` удаляет исчезнувшее из git.
4. `prune` требует аккуратности: отдельные namespace и `Prune=false` для чужих ресурсов.
5. `ignoreDifferences` спасает от вечного `OutOfSync` там, где поля меняет кластер (HPA).
6. Порядок применения задают `sync-wave`, а миграции — хуками `PreSync`.
7. Правильный откат — коммит в git; `argocd app rollback` — аварийный вариант,
   который нужно потом зафиксировать в репозитории.
8. `finalizer` определяет, удалятся ли ресурсы вместе с `Application`.
9. На проде `targetRevision` лучше указывать на тег/релизную ветку, а не на `main`.
10. Разбор проблем: `diff` → `get` → `describe`/логи → права и валидация манифестов.

---

## Задачи

> Стенд: ArgoCD + свой репозиторий с манифестами демо-приложения.

---

### Блок A. Теория

**A1.** Из каких трёх частей состоит `Application`?

<details><summary>Ответ</summary>

`source` (откуда брать манифесты), `destination` (куда разворачивать),
`syncPolicy` (как синхронизировать).

</details>

**A2.** Что означают `repoURL`, `path`, `targetRevision`?

<details><summary>Ответ</summary>

Адрес репозитория, путь к каталогу с манифестами/чартом и ревизия
(ветка, тег или коммит).

</details>

**A3.** ⭐ Какие бывают sync-статусы и health-статусы? Что означает каждая комбинация?

<details><summary>Ответ</summary>

Sync: `Synced`, `OutOfSync`, `Unknown`. Health: `Healthy`, `Progressing`,
`Degraded`, `Missing`, `Suspended`. Synced+Healthy — норма; Synced+Degraded —
применено, но не работает; OutOfSync+Healthy — работает, но отличается от git;
OutOfSync+Degraded — плохой деплой; Unknown — проблема с доступом/рендерингом.

</details>

**A4.** Что делает `syncPolicy.automated`?

<details><summary>Ответ</summary>

Включает автоматическую синхронизацию при изменении в git (без ручного `sync`).

</details>

**A5.** Что делает `prune` и чем он опасен?

<details><summary>Ответ</summary>

Удаляет из кластера ресурсы, которых больше нет в git. Опасен тем, что может
удалить ресурсы, созданные вне ArgoCD в том же namespace.

</details>

**A6.** Что делает `selfHeal` и какую проблему решает?

<details><summary>Ответ</summary>

Возвращает состояние ресурсов к описанному в git при ручных изменениях —
автоматически устраняет дрейф.

</details>

**A7.** Зачем нужен `allowEmpty: false`?

<details><summary>Ответ</summary>

Защищает от применения пустого набора манифестов (например, когда каталог
случайно опустел или сломался рендеринг) и, как следствие, от массового удаления.

</details>

**A8.** Что делает `finalizer` у Application?

<details><summary>Ответ</summary>

`resources-finalizer.argocd.argoproj.io` заставляет ArgoCD удалить управляемые
ресурсы при удалении Application (каскадное удаление).

</details>

**A9.** Зачем нужен `CreateNamespace=true`?

<details><summary>Ответ</summary>

Чтобы ArgoCD создал целевой namespace, если его нет.

</details>

**A10.** Когда включают `ServerSideApply=true`?

<details><summary>Ответ</summary>

Когда возникают конфликты владения полями или ошибки из-за размера аннотации
`last-applied-configuration` (большие CRD), а также при совместном управлении ресурсом.

</details>

**A11.** Что такое `ignoreDifferences` и типовой пример его использования?

<details><summary>Ответ</summary>

Список полей, расхождения по которым не считаются дрейфом. Классика —
`/spec/replicas` у Deployment при включённом HPA.

</details>

**A12.** Что такое sync waves и зачем они?

<details><summary>Ответ</summary>

Аннотация `argocd.argoproj.io/sync-wave` задаёт порядок применения ресурсов:
меньшие номера применяются раньше (namespace, CRD, конфигурация — до приложений).

</details>

**A13.** Какие бывают hooks и для чего используется `PreSync`?

<details><summary>Ответ</summary>

`PreSync`, `Sync`, `PostSync`, `SyncFail`. `PreSync` используют для миграций
БД и подготовительных задач до применения основных манифестов.

</details>

**A14.** ⭐ Как правильно откатить релиз в GitOps и чем плох `argocd app rollback`
без коммита?

<details><summary>Ответ</summary>

Правильный откат — `git revert` и синхронизация: git и кластер снова
согласованы. `argocd app rollback` меняет только кластер; при `selfHeal` состояние
вернётся к «сломанному» git, а без него возникнет дрейф.

</details>

**A15.** Опиши алгоритм разбора приложения в статусе `Degraded`.

<details><summary>Ответ</summary>

`argocd app get` (какой ресурс нездоров) → `kubectl describe`/события →
логи подов (`argocd app logs`) → проверка ресурсов, лимитов и квот → проверка проб
и образов → при необходимости откат.

</details>

---

### Блок B. «Оцени конфигурацию»

```yaml
B1.   spec: { source: { targetRevision: main }, destination: { namespace: prod } }
      # прод-приложение
```

<details><summary>Ответ</summary>

Прод на `main`: любой коммит уезжает в прод — рискованно.

</details>

```yaml
B2.   spec: { source: { targetRevision: v1.4.2 } }
```

<details><summary>Ответ</summary>

Прод на теге — предсказуемо.

</details>

```yaml
B3.   syncPolicy: { automated: { prune: true, selfHeal: true } }     # dev-окружение
```

<details><summary>Ответ</summary>

Нормально для dev.

</details>

```yaml
B4.   syncPolicy: {}                                                  # прод, синхронизация вручную
```

<details><summary>Ответ</summary>

Допустимо на старте внедрения, но теряется автоматическое устранение дрейфа.

</details>

```text:no-line-numbers
B5.   # нет finalizer, Application удаляют командой delete
```

<details><summary>Ответ</summary>

Без finalizer ресурсы останутся в кластере после удаления Application.

</details>

```yaml
B6.   syncOptions: [ CreateNamespace=true ]
```

<details><summary>Ответ</summary>

Удобно и безопасно.

</details>

```text:no-line-numbers
B7.   # Deployment с replicas: 3 в git + включённый HPA
```

<details><summary>Ответ</summary>

Конфликт: git задаёт replicas, HPA их меняет — вечный OutOfSync.

</details>

```yaml
B8.   ignoreDifferences: [{ group: apps, kind: Deployment, jsonPointers: [/spec/replicas] }]
```

<details><summary>Ответ</summary>

Правильное решение проблемы B7.

</details>

```text:no-line-numbers
B9.   # Job с миграцией БД лежит обычным манифестом рядом с Deployment
```

<details><summary>Ответ</summary>

Миграция без hook может выполниться параллельно с раскаткой новых подов.

</details>

```text:no-line-numbers
B10.  # Job с миграцией имеет аннотацию hook: PreSync
```

<details><summary>Ответ</summary>

Правильный подход.

</details>

```text:no-line-numbers
B11.  # Application деплоит в namespace, где другие инструменты создают ресурсы; prune: true
```

<details><summary>Ответ</summary>

`prune` в общем namespace может удалить чужие ресурсы.

</details>

```text:no-line-numbers
B12.  # секрет с паролем лежит в манифесте открытым текстом
```

<details><summary>Ответ</summary>

Секрет в git открытым текстом — утечка.

</details>

---

### Блок C. Практика

#### C1. 🔑 Первое приложение
1. Положи в репозиторий `apps/demo/` манифесты nginx (Deployment + Service).
2. Создай `Application` декларативно (YAML в `argocd` namespace).
3. Синхронизируй вручную, посмотри дерево ресурсов в UI.
4. Проверь `argocd app get demo` и `kubectl get all -n demo`.

#### C2. Статусы
1. Измени образ на несуществующий — доведи приложение до `Degraded`.
2. Верни обратно.
3. Измени манифест в git, но не синхронизируй — получи `OutOfSync`.
Запиши, как выглядит каждая комбинация статусов.

<details><summary>Ответ</summary>

Несуществующий образ даёт `ImagePullBackOff` и статус `Degraded` при `Synced`.

</details>

#### C3. ⭐ Auto-sync, self-heal, prune
1. Включи `automated` и проверь, что коммит применяется сам.
2. Измени число реплик через `kubectl scale` — посмотри поведение без и с `selfHeal`.
3. Удали манифест Service из git и проверь поведение без и с `prune`.

<details><summary>Ответ</summary>

Без `selfHeal` изменение реплик останется и приложение будет `OutOfSync`;
с `selfHeal` — вернётся к значению из git за секунды.

</details>

#### C4. `diff`
Внеси изменение в кластер вручную и выполни `argocd app diff demo`.
Разберись, как читать вывод.

#### C5. HPA и `ignoreDifferences`
1. Добавь HPA к демо-приложению.
2. Убедись, что приложение постоянно `OutOfSync` из-за `replicas`.
3. Добавь `ignoreDifferences` и проверь, что статус стал `Synced`.

<details><summary>Ответ</summary>

После добавления `ignoreDifferences` приложение перестаёт «дрожать» между
статусами.

</details>

#### C6. Sync waves
Добавь namespace и ConfigMap с `sync-wave: "-1"`, приложение — с `"0"`.
Проверь по событиям, что порядок соблюдён.

#### C7. PreSync hook
Добавь Job-миграцию с `hook: PreSync` и `hook-delete-policy: HookSucceeded`.
Сделай так, чтобы Job падал, и посмотри, что произойдёт с синхронизацией.

<details><summary>Ответ</summary>

Упавший PreSync-hook останавливает синхронизацию: основные манифесты не применяются.

</details>

#### C8. 🔑 Откаты
1. Сломай приложение коммитом.
2. Откатись через `argocd app rollback` — посмотри, что делает `selfHeal`.
3. Откатись правильно: `git revert` + синхронизация.
Запиши разницу.

<details><summary>Ответ</summary>

При `selfHeal` откат через `rollback` будет отменён следующей сверкой —
это и есть демонстрация, почему откат делают коммитом.

</details>

#### C9. Finalizer
Создай два Application: с finalizer и без. Удали оба и сравни, что осталось в кластере.

<details><summary>Ответ</summary>

Без finalizer после удаления Application ресурсы остаются «сиротами».

</details>

#### C10. Уведомления
Настрой `argocd-notifications` (или алерт в Prometheus) на события
`Degraded` и `SyncFailed`, проверь доставку.

---

### Блок D. Инциденты

**D1.** Приложение `Synced`, но `Degraded`. С чего начнёшь?

<details><summary>Ответ</summary>

`argocd app get` — найти нездоровый ресурс; затем `kubectl describe`,
события и логи; типичные причины — образ, пробы, ресурсы, конфигурация, зависимости.

</details>

**D2.** Приложение вечно `OutOfSync`, хотя никто ничего не менял. Причины?

<details><summary>Ответ</summary>

Поля меняет кластер или другой контроллер (HPA, mutating webhook, дефолты API),
несовпадение форматов, отсутствующие `ignoreDifferences`, `ServerSideApply`,
различия из-за Helm-рендеринга.

</details>

**D3.** Синхронизация падает с ошибкой валидации манифеста. Что проверить?

<details><summary>Ответ</summary>

Прогнать `kubectl apply --dry-run=server` на отрендеренных манифестах,
проверить версии API, наличие CRD, корректность чарта/kustomize.

</details>

**D4.** Синхронизация падает с ошибкой прав в целевом кластере. Куда смотреть?

<details><summary>Ответ</summary>

Права ServiceAccount ArgoCD в целевом кластере, ограничения `AppProject`
(разрешённые ресурсы и namespace), namespace-политики.

</details>

**D5.** После включения `prune` исчезли ресурсы, созданные другим инструментом.
Как предотвратить?

<details><summary>Ответ</summary>

Разделить namespace, пометить чужие ресурсы `Prune=false`, включать `prune`
поэтапно и наблюдать diff до включения.

</details>

**D6.** Разработчик поправил ConfigMap на проде, через минуту всё вернулось. Объясни
и предложи правильный процесс.

<details><summary>Ответ</summary>

Сработал `selfHeal`. Правильный процесс — изменение через MR в конфиг-репозиторий;
для аварийных случаев — отдельная процедура с обязательным последующим коммитом.

</details>

**D7.** Деплой прошёл, но миграция БД выполнилась после старта новых подов, приложение
падает. Что настроить?

<details><summary>Ответ</summary>

Вынести миграцию в `PreSync`-hook (Job), чтобы она выполнялась до применения
новых манифестов, и сделать её идемпотентной.

</details>

**D8.** `argocd app rollback` не помогает: состояние возвращается к сломанному. Почему?

<details><summary>Ответ</summary>

Включён `selfHeal`: контроллер возвращает состояние к git. Нужно исправлять
именно репозиторий.

</details>

**D9.** Приложение удалили, а поды остались. Что было не так?

<details><summary>Ответ</summary>

Не был указан finalizer — ArgoCD удалил только объект Application.

</details>

**D10.** В проде приложение обновилось само после чужого коммита в `main`.
Как выстроить процесс?

<details><summary>Ответ</summary>

Указать в `targetRevision` тег или релизную ветку, защитить ветку правилами,
деплой в прод — отдельным коммитом/тегом после ревью.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое Application в ArgoCD?

<details><summary>Ответ</summary>

Объект ArgoCD, описывающий, откуда брать манифесты, куда их разворачивать
и как синхронизировать.

</details>

**2.** Какие бывают статусы и что они значат?

<details><summary>Ответ</summary>

Sync (`Synced`/`OutOfSync`/`Unknown`) и health (`Healthy`/`Progressing`/`Degraded`/
`Missing`/`Suspended`).

</details>

**3.** Что делают `prune` и `selfHeal`?

<details><summary>Ответ</summary>

`prune` удаляет исчезнувшее из git, `selfHeal` возвращает ручные правки к git.

</details>

**4.** Как ArgoCD определяет здоровье приложения?

<details><summary>Ответ</summary>

По встроенным проверкам для стандартных ресурсов и пользовательским Lua-скриптам
для CRD.

</details>

**5.** Что такое sync waves и hooks?

<details><summary>Ответ</summary>

Порядок применения ресурсов (`sync-wave`) и задачи вокруг синхронизации
(`PreSync`/`Sync`/`PostSync`/`SyncFail`).

</details>

**6.** Как сделать миграцию БД перед деплоем?

<details><summary>Ответ</summary>

Job с аннотацией `hook: PreSync` и политикой удаления после успеха.

</details>

**7.** Как откатить релиз?

<details><summary>Ответ</summary>

Коммитом в git (`git revert`); аварийно — `argocd app rollback` с последующей
фиксацией в репозитории.

</details>

**8.** Как бороться с вечным OutOfSync при HPA?

<details><summary>Ответ</summary>

`ignoreDifferences` на `/spec/replicas` (или не задавать replicas в манифесте).

</details>

**9.** Что произойдёт при удалении Application?

<details><summary>Ответ</summary>

Если есть finalizer — удалятся и управляемые ресурсы; иначе останутся в кластере.

</details>

**10.** Как не дать коммиту в main уехать в прод?

<details><summary>Ответ</summary>

`targetRevision` на тег/релизную ветку, защита веток, ревью и отдельный шаг
выкатки в прод.

</details>

---

### 🎯 Чек-лист

- [ ] Создал Application декларативно и через CLI
- [ ] ⭐ Понимаю комбинации sync- и health-статусов
- [ ] Включал `automated`, `selfHeal`, `prune` и видел их эффект
- [ ] Пользуюсь `argocd app diff` при разборе расхождений
- [ ] Решил проблему вечного OutOfSync с HPA
- [ ] Применял sync waves и PreSync-hook для миграций
- [ ] Делал откат через git и понимаю ограничения `rollback`
- [ ] Знаю роль finalizer при удалении Application
- [ ] Настроил уведомления о Degraded/SyncFailed
- [ ] На проде использую тег/релизную ветку, а не `main`
