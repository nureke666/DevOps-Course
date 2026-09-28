---
title: "04. App of Apps и ApplicationSet"
description: "Паттерн App of Apps, ApplicationSet и его генераторы, структура репозитория для нескольких окружений, порядок бутстрапа кластера"
---

# 04. App of Apps и ApplicationSet

> Роадмап → GitOps: *«App of Apps паттерн, хелм чарты через арго»*.
>
> **После темы ты умеешь:** управлять десятками приложений и несколькими окружениями,
> не создавая вручную каждый `Application`.

---

## 🗺️ Проблема, которую решают

```text:no-line-numbers
 5 приложений → создать 5 Application вручную — терпимо
 50 приложений × 3 окружения = 150 Application ⚠️ — невозможно поддерживать руками

 РЕШЕНИЕ 1: App of Apps      одно «корневое» приложение создаёт остальные
 РЕШЕНИЕ 2: ApplicationSet   контроллер ГЕНЕРИРУЕТ Application по шаблону
```

---

## 1. App of Apps ⭐

```text:no-line-numbers
        ┌──────────────────────────┐
        │ Application "root"       │   ← создаёшь руками ОДИН раз
        │ path: apps/              │
        └────────────┬─────────────┘
                     │ в каталоге apps/ лежат... другие Application!
     ┌───────────────┼────────────────┬──────────────────┐
     ▼               ▼                ▼                  ▼
 Application     Application      Application        Application
  "ingress"      "monitoring"     "billing"          "frontend"
     │               │                │                  │
  манифесты      Helm-чарт        манифесты          Helm-чарт
```

Структура репозитория:
```text:no-line-numbers
gitops-repo/
├── bootstrap/
│   └── root-app.yaml            ← единственный, что применяется руками
├── apps/                        ← ⭐ каталог с Application-манифестами
│   ├── ingress-nginx.yaml
│   ├── monitoring.yaml
│   ├── billing.yaml
│   └── frontend.yaml
└── manifests/
    ├── billing/
    └── frontend/
```

```yaml
# bootstrap/root-app.yaml — «корень»
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: root
  namespace: argocd
  finalizers: [resources-finalizer.argocd.argoproj.io]
spec:
  project: default
  source:
    repoURL: https://gitlab.com/org/gitops-repo.git
    path: apps                         # ⭐ здесь лежат другие Application
    targetRevision: main
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated: { prune: true, selfHeal: true }
```
```yaml
# apps/billing.yaml — обычный Application, который создаст root
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: billing
  namespace: argocd
spec:
  project: team-billing
  source:
    repoURL: https://gitlab.com/org/gitops-repo.git
    path: manifests/billing
    targetRevision: main
  destination: { server: https://kubernetes.default.svc, namespace: billing }
  syncPolicy: { automated: { prune: true, selfHeal: true }, syncOptions: [CreateNamespace=true] }
```

```bash
kubectl apply -f bootstrap/root-app.yaml    # ⭐ единственная ручная команда
# дальше добавление приложения = коммит нового файла в apps/
```

| Плюсы | Минусы |
|-------|--------|
| Одна точка входа: «бутстрап кластера» | Много почти одинаковых YAML в `apps/` |
| Прозрачно: видно все приложения в git | Копипаста при добавлении окружений |
| Легко воссоздать кластер с нуля | Сложнее динамика (списки кластеров, каталоги) |

---

## 2. ApplicationSet — генерация по шаблону ⭐

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: microservices
  namespace: argocd
spec:
  generators:
    - git:                                     # генератор: каталоги в репозитории
        repoURL: https://gitlab.com/org/gitops-repo.git
        revision: main
        directories:
          - path: manifests/*
  template:
    metadata:
      name: '{{path.basename}}'               # имя = имя каталога
    spec:
      project: default
      source:
        repoURL: https://gitlab.com/org/gitops-repo.git
        targetRevision: main
        path: '{{path}}'
      destination:
        server: https://kubernetes.default.svc
        namespace: '{{path.basename}}'
      syncPolicy:
        automated: { prune: true, selfHeal: true }
        syncOptions: [CreateNamespace=true]
```
Добавили каталог `manifests/payments/` → появилось приложение `payments`.
Ничего создавать руками не нужно.

### Генераторы

| Генератор | Что перебирает | Типовой случай |
|-----------|----------------|----------------|
| `list` | Заданный список значений | Два-три окружения |
| `git.directories` | Каталоги в репозитории | ⭐ «каталог = приложение» |
| `git.files` | Файлы конфигурации (`config.json`) | Параметры на окружение |
| `cluster` | Зарегистрированные в ArgoCD кластеры | ⭐ Одно приложение во все кластеры |
| `matrix` | Декартово произведение двух генераторов | Приложения × окружения |
| `merge` | Объединение с переопределением | Общие настройки + исключения |
| `scmProvider`/`pullRequest` | Репозитории организации / PR | Превью-окружения на каждый PR |

```yaml
# matrix: все приложения во всех кластерах
  generators:
    - matrix:
        generators:
          - git: { repoURL: ..., directories: [{ path: manifests/* }] }
          - clusters: { selector: { matchLabels: { env: prod } } }
```

```yaml
# list: окружения с разными параметрами
  generators:
    - list:
        elements:
          - env: dev
            replicas: "1"
            cluster: https://kubernetes.default.svc
          - env: prod
            replicas: "3"
            cluster: https://prod.example.com
```

---

## 3. Структура репозиториев для нескольких окружений

```text:no-line-numbers
gitops-repo/
├── bootstrap/
│   ├── dev/root-app.yaml
│   └── prod/root-app.yaml
├── apps/
│   ├── dev/            ← Application'ы окружения dev
│   └── prod/
├── base/               ← общие манифесты (Kustomize base)
│   └── billing/
└── overlays/
    ├── dev/billing/    ← отличия окружения
    └── prod/billing/
```

Три распространённых подхода к окружениям:
| Подход | Как | Комментарий |
|--------|-----|-------------|
| Каталоги на окружение | `overlays/dev`, `overlays/prod` | ⭐ Прозрачно, легко ревьюить |
| Ветки на окружение | ветка `dev`, ветка `prod` | Соблазнительно, но приводит к дрейфу веток |
| ApplicationSet + values | Один шаблон, разные values | Меньше дублирования, сложнее читать |

⚠️ Подход «ветка на окружение» популярен у новичков и почти всегда заканчивается
расхождением веток и мучительными merge; рекомендуемый путь — каталоги/overlay.

---

## 4. Порядок бутстрапа кластера

```text:no-line-numbers
sync-wave -3  namespaces, CRD
sync-wave -2  cert-manager, ingress-controller, storage
sync-wave -1  мониторинг, логирование, секрет-менеджер
sync-wave  0  приложения команд
```
```yaml
metadata:
  annotations:
    argocd.argoproj.io/sync-wave: "-2"
```
Так «пустой» кластер разворачивается одной командой `kubectl apply -f bootstrap/root-app.yaml`
— и это лучший способ проверить, что GitOps действительно работает.

---

## 5. Грабли

| Грабля | Последствие | Решение |
|--------|-------------|---------|
| `prune: true` у root-app без внимания | Удаление приложения из `apps/` сносит всё его хозяйство | Понимать каскад; `finalizer` и ревью |
| ApplicationSet без ограничений | Случайный каталог порождает приложение в проде | Фильтры генераторов, `AppProject` |
| Ветки вместо overlay | Дрейф окружений | Каталоги/overlay |
| Одинаковые имена приложений в разных окружениях | Конфликт имён | Суффикс окружения в шаблоне |
| Всё в одном проекте `default` | Нет границ между командами | `AppProject` на команду |
| Слишком «умные» шаблоны | Никто не понимает, что задеплоится | Простота важнее компактности |
| Нет `sync-wave` при бутстрапе | Приложения стартуют раньше CRD/ingress | Волны синхронизации |

---

## 💼 Как это в DevOps

- App of Apps — стандартный способ «бутстрапа» кластера: одна команда — и кластер
  наполняется платформой и приложениями.
- ApplicationSet используют, когда приложений много или их набор динамический
  (каталоги, кластеры, PR-превью).
- Превью-окружения на каждый merge request через `pullRequest`-генератор —
  популярный и эффектный сценарий.
- Структура репозитория обсуждается на старте: она определяет, насколько просто
  будет добавлять сервисы и окружения через год.
- Проверка зрелости: можно ли поднять новый кластер и получить рабочую платформу,
  применив один манифест?

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Управлять всеми приложениями из git | App of Apps: корневой Application на каталог с Application'ами |
| Бутстрап кластера одной командой | `kubectl apply -f bootstrap/root-app.yaml` |
| Приложение на каждый каталог | ApplicationSet + `git.directories` |
| Приложение во все кластеры | ApplicationSet + `clusters` |
| Приложения × окружения | ApplicationSet + `matrix` |
| Разные параметры окружений | `list`-генератор или `git.files` |
| Превью на каждый PR | `pullRequest`-генератор |
| Порядок разворачивания | аннотация `sync-wave` |
| Границы команд | `AppProject` + отдельные пути в репозитории |

---

## 🧠 Что запомнить

1. ⭐ App of Apps: один корневой `Application` указывает на каталог с другими
   `Application` — добавление сервиса становится коммитом.
2. Бутстрап кластера сводится к применению одного манифеста.
3. ApplicationSet генерирует приложения по шаблону из генераторов: list, git,
   clusters, matrix, merge, pullRequest.
4. `git.directories` даёт правило «каталог = приложение»; `clusters` — «приложение
   во все кластеры».
5. Превью-окружения на PR делаются `pullRequest`-генератором.
6. Окружения разделяют каталогами/overlay, а не ветками — ветки расходятся.
7. `sync-wave` задаёт порядок: CRD и платформа раньше приложений.
8. `prune` на корневом приложении означает каскадное удаление — это мощно и опасно.
9. Границы команд задают `AppProject` и структура каталогов.
10. Простая и предсказуемая структура репозитория важнее компактных «умных» шаблонов.

---

## Задачи

> Стенд: ArgoCD + репозиторий со структурой `bootstrap/`, `apps/`, `manifests/`.

---

### Блок A. Теория

**A1.** Какую проблему решают App of Apps и ApplicationSet?

<details><summary>Ответ</summary>

Ручное создание десятков и сотен `Application` для множества сервисов
и окружений не масштабируется и не воспроизводится.

</details>

**A2.** ⭐ Как устроен паттерн App of Apps? Что применяется руками?

<details><summary>Ответ</summary>

Один корневой `Application` указывает на каталог репозитория, в котором лежат
манифесты других `Application`. Руками применяется только корневой.

</details>

**A3.** Что лежит в каталоге, на который смотрит корневое приложение?

<details><summary>Ответ</summary>

Манифесты `Application` (и, при необходимости, `AppProject`), описывающие
остальные приложения.

</details>

**A4.** Плюсы и минусы App of Apps.

<details><summary>Ответ</summary>

Плюсы: одна точка входа, всё видно в git, кластер воссоздаётся одной командой.
Минусы: много почти одинаковых файлов, копипаста при добавлении окружений,
ограниченная динамика.

</details>

**A5.** Что такое ApplicationSet и чем он отличается от App of Apps?

<details><summary>Ответ</summary>

ApplicationSet — контроллер, который **генерирует** `Application` по шаблону
из источников (генераторов), вместо того чтобы хранить их файлами.

</details>

**A6.** Назови пять генераторов ApplicationSet и типовой сценарий для каждого.

<details><summary>Ответ</summary>

`list` (фиксированный набор окружений), `git.directories` (каталог = приложение),
`git.files` (параметры из файлов), `clusters` (во все кластеры), `matrix`
(произведение), `merge`, `pullRequest` (превью на MR), `scmProvider` (репозитории
организации).

</details>

**A7.** Как сделать «каталог = приложение»?

<details><summary>Ответ</summary>

ApplicationSet с генератором `git` и `directories: [{ path: manifests/* }]`,
где имя и путь берутся из <code v-pre>{{path.basename}}</code> и <code v-pre>{{path}}</code>.

</details>

**A8.** Как задеплоить одно приложение во все кластеры?

<details><summary>Ответ</summary>

Генератором `clusters` (с селектором по меткам кластеров).

</details>

**A9.** Что делает `matrix`-генератор?

<details><summary>Ответ</summary>

Создаёт декартово произведение двух генераторов, например «все приложения ×
все кластеры/окружения».

</details>

**A10.** Как сделать превью-окружение на каждый pull request?

<details><summary>Ответ</summary>

Генератором `pullRequest`: на каждый открытый PR создаётся приложение
во временном namespace, после закрытия оно удаляется.

</details>

**A11.** ⭐ Три подхода к окружениям — какой предпочтителен и почему?

<details><summary>Ответ</summary>

Каталоги/overlay, ветки, шаблоны с параметрами. Предпочтительны каталоги
(overlay): изменения видны в одном diff, нет расхождения веток, легко ревьюить.

</details>

**A12.** Почему ветки на окружение считаются плохой практикой?

<details><summary>Ответ</summary>

Ветки начинают жить своей жизнью: изменения попадают в одну и «забываются»
в другой, merge становится конфликтным, а окружения перестают быть сопоставимыми.

</details>

**A13.** Как задать порядок разворачивания платформы и приложений?

<details><summary>Ответ</summary>

Аннотацией `argocd.argoproj.io/sync-wave` (меньшие значения применяются раньше):
namespace и CRD, затем платформа, затем приложения.

</details>

**A14.** Чем опасен `prune` на корневом приложении?

<details><summary>Ответ</summary>

При удалении файла приложения из каталога корневое приложение удалит сам
`Application`, а при наличии finalizer — и все его ресурсы в кластере (каскад).

</details>

**A15.** Как проверить, что GitOps «настоящий»?

<details><summary>Ответ</summary>

Попробовать развернуть новый кластер, применив один манифест из git,
и получить рабочую платформу и приложения без ручных шагов.

</details>

---

### Блок B. «Оцени решение»

```text:no-line-numbers
B1.  Каждый Application создаётся вручную через UI, их 40
```

<details><summary>Ответ</summary>

Не масштабируется и не воспроизводится.

</details>

```text:no-line-numbers
B2.  Корневой Application смотрит на каталог apps/, новые сервисы добавляются коммитом
```

<details><summary>Ответ</summary>

Правильный паттерн.

</details>

```text:no-line-numbers
B3.  ApplicationSet с git.directories на manifests/*
```

<details><summary>Ответ</summary>

Хороший вариант для множества однотипных сервисов.

</details>

```text:no-line-numbers
B4.  ApplicationSet без фильтров на весь репозиторий, включая тестовые каталоги
```

<details><summary>Ответ</summary>

Без фильтров в прод попадут тестовые каталоги.

</details>

```text:no-line-numbers
B5.  Окружения разделены ветками dev/stage/prod, изменения мержатся между ветками
```

<details><summary>Ответ</summary>

Ветки на окружение — источник дрейфа.

</details>

```text:no-line-numbers
B6.  Окружения разделены каталогами overlays/{dev,stage,prod}
```

<details><summary>Ответ</summary>

Рекомендуемый подход.

</details>

```text:no-line-numbers
B7.  Все приложения в проекте default, у всех команд полный доступ
```

<details><summary>Ответ</summary>

Отсутствие границ между командами.

</details>

```text:no-line-numbers
B8.  Платформенные компоненты и приложения имеют одинаковый sync-wave
```

<details><summary>Ответ</summary>

Платформенные компоненты должны применяться раньше приложений.

</details>

```text:no-line-numbers
B9.  Имена приложений в dev и prod совпадают, оба в одном ArgoCD
```

<details><summary>Ответ</summary>

Конфликт имён; нужен суффикс окружения.

</details>

```text:no-line-numbers
B10. pullRequest-генератор создаёт окружение на каждый MR и удаляет после закрытия
```

<details><summary>Ответ</summary>

Отличная практика превью-окружений.

</details>

```text:no-line-numbers
B11. Корневое приложение с prune: true, кто-то удалил файл из apps/ по ошибке
```

<details><summary>Ответ</summary>

Каскадное удаление по ошибке — нужен процесс ревью и понимание последствий.

</details>

```text:no-line-numbers
B12. Bootstrap кластера: 15 ручных команд kubectl и helm
```

<details><summary>Ответ</summary>

Ручной бутстрап противоречит GitOps и не воспроизводится.

</details>

---

### Блок C. Практика

#### C1. 🔑 App of Apps
1. Создай структуру `bootstrap/root-app.yaml`, `apps/*.yaml`, `manifests/*`.
2. Примени корневое приложение одной командой.
3. Убедись, что дочерние приложения создались автоматически.
4. Добавь новый сервис коммитом и проверь, что он появился сам.

#### C2. Каскадное удаление
1. Удали файл приложения из `apps/` и закоммить.
2. Посмотри, что произойдёт при `prune: true` у корневого приложения.
3. Верни обратно. Сделай выводы о рисках.

<details><summary>Ответ</summary>

При `prune: true` удаление файла приводит к удалению `Application`,
а с finalizer — и его ресурсов.

</details>

#### C3. ApplicationSet: git.directories
Замени содержимое `apps/` на один ApplicationSet, генерирующий приложения
по каталогам `manifests/*`. Добавь новый каталог и проверь автоматическое появление.

#### C4. ApplicationSet: list
Сделай генератор на два окружения (`dev`, `prod`) с разным числом реплик
и разными namespace.

#### C5. Matrix
Сделай `matrix` из каталогов приложений и списка окружений.
Посчитай, сколько Application получилось.

<details><summary>Ответ</summary>

Число приложений = каталоги × окружения.

</details>

#### C6. 🔑 Порядок бутстрапа
1. Добавь namespace, CRD и платформенный компонент с `sync-wave: -2`.
2. Приложения оставь на `0`.
3. Снеси всё и разверни заново с нуля — проверь порядок по событиям.

<details><summary>Ответ</summary>

По событиям видно, что ресурсы с меньшими волнами применяются раньше,
и следующая волна начинается после готовности предыдущей.

</details>

#### C7. Окружения через overlay
Организуй `base/` + `overlays/{dev,prod}` (Kustomize) и подключи их двумя
Application. Сравни удобство с разделением по веткам.

#### C8. Границы команд
Создай два `AppProject` и раздели приложения между ними. Проверь, что приложение
одной команды не может деплоиться в чужой namespace.

#### C9. Превью-окружения (со звёздочкой)
Настрой `pullRequest`-генератор (GitHub/GitLab), создай MR и проверь появление
временного окружения.

#### C10. Проверка зрелости
Удали кластер целиком, создай новый и разверни всё одной командой из git.
Замерь время и запиши, чего не хватило.

<details><summary>Ответ</summary>

Типичные пробелы: секреты, данные в PVC, внешние зависимости (DNS,
сертификаты, облачные ресурсы), ручные шаги регистрации кластера.

</details>

---

### Блок D. Инциденты

**D1.** Удалили файл из `apps/` — пропало приложение вместе с данными. Что произошло
и как защититься?

<details><summary>Ответ</summary>

Каскадное удаление: корневое приложение с `prune` удалило дочернее вместе
с ресурсами. Защита: ревью MR, `prevent`-практики (отдельный проект для критичных
приложений), бэкапы данных, отказ от `prune` на корне до зрелости процесса.

</details>

**D2.** ApplicationSet создал приложение из тестового каталога в проде. Что настроить?

<details><summary>Ответ</summary>

Фильтры в генераторе (исключить пути), отдельный репозиторий/каталог для тестов,
ограничения `AppProject`.

</details>

**D3.** После добавления нового кластера приложения там не появились. Гипотезы?

<details><summary>Ответ</summary>

Кластер не зарегистрирован в ArgoCD или не имеет нужных меток для селектора,
ошибки в шаблоне, нет прав, приложения не проходят валидацию проекта.

</details>

**D4.** Имена приложений конфликтуют между окружениями. Как исправить?

<details><summary>Ответ</summary>

Добавить суффикс окружения в шаблон имени (<code v-pre>{{path.basename}}-{{env}}</code>)
или использовать разные namespace ArgoCD/инстансы.

</details>

**D5.** Приложения стартовали раньше, чем ingress-controller и CRD. Что добавить?

<details><summary>Ответ</summary>

`sync-wave` для CRD, namespace и платформенных компонентов.

</details>

**D6.** Ветки dev и prod разошлись так, что merge невозможен. Как выйти из ситуации?

<details><summary>Ответ</summary>

Перейти на overlay-структуру: выделить `base` и различия, перенести окружения
в каталоги, дальше вести изменения через один поток.

</details>

**D7.** Превью-окружения не удаляются после закрытия MR. Где искать проблему?

<details><summary>Ответ</summary>

Настройки `pullRequest`-генератора (условия закрытия), права токена,
webhook, TTL/политика удаления, ошибки контроллера ApplicationSet.

</details>

**D8.** Корневое приложение постоянно OutOfSync, хотя дочерние в порядке. Причины?

<details><summary>Ответ</summary>

В каталоге `apps/` есть изменения, которые не применены (например, ручные
правки в кластере, отличия в полях Application, `metadata` от контроллеров),
либо приложения создаются другим способом и дублируются.

</details>

**D9.** Новому сервису нужно попасть в прод, но команда не имеет прав. Как организовать
self-service?

<details><summary>Ответ</summary>

Self-service через шаблон: команда добавляет каталог/файл по правилам,
ApplicationSet создаёт приложение в их проекте и namespace; ревью выполняет владелец
платформы.

</details>

**D10.** Восстановление кластера заняло сутки, хотя «всё в git». Что было упущено?

<details><summary>Ответ</summary>

В git не было части состояния: секреты, конфигурация внешних систем,
данные, регистрация кластера, DNS и сертификаты; плюс не был отрепетирован сценарий
восстановления.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое App of Apps?

<details><summary>Ответ</summary>

Паттерн, при котором корневой Application создаёт остальные Application из каталога
в git.

</details>

**2.** Чем ApplicationSet отличается от App of Apps?

<details><summary>Ответ</summary>

ApplicationSet генерирует приложения по шаблону из генераторов, а App of Apps
хранит их файлами.

</details>

**3.** Какие генераторы ApplicationSet знаешь?

<details><summary>Ответ</summary>

list, git (directories/files), clusters, matrix, merge, pullRequest, scmProvider.

</details>

**4.** Как управлять несколькими окружениями?

<details><summary>Ответ</summary>

Каталогами/overlay с разными Application (или генератором по списку окружений).

</details>

**5.** Почему не стоит делать ветку на окружение?

<details><summary>Ответ</summary>

Ветки расходятся, изменения теряются, окружения становятся несопоставимыми.

</details>

**6.** Как задать порядок разворачивания компонентов?

<details><summary>Ответ</summary>

Аннотацией `sync-wave`.

</details>

**7.** Как сделать превью-окружение на каждый PR?

<details><summary>Ответ</summary>

Генератором `pullRequest` с временным namespace и автоматическим удалением.

</details>

**8.** Как разграничить команды в ArgoCD?

<details><summary>Ответ</summary>

Через `AppProject`, RBAC и структуру каталогов репозитория.

</details>

**9.** Как быстро развернуть новый кластер?

<details><summary>Ответ</summary>

Применить корневой Application из bootstrap-каталога и дождаться разворачивания.

</details>

**10.** Чем опасен prune на корневом приложении?

<details><summary>Ответ</summary>

Удаление файла приложения приводит к удалению приложения и его ресурсов каскадом.

</details>

---

### 🎯 Чек-лист

- [ ] ⭐ Настроил App of Apps и добавляю сервисы коммитом
- [ ] Понимаю риски каскадного удаления
- [ ] Пробовал ApplicationSet с генератором каталогов
- [ ] Сделал генерацию по списку окружений и `matrix`
- [ ] Развёл окружения через overlay, а не ветки
- [ ] Настроил порядок бутстрапа через sync-wave
- [ ] Разделил команды через AppProject
- [ ] Пробовал превью-окружения на PR
- [ ] Развернул кластер с нуля одной командой
- [ ] Знаю, чего не хватает в git для полного восстановления
