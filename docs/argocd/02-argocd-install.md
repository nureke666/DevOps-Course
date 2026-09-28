---
title: "02. Установка и устройство ArgoCD"
description: "Компоненты ArgoCD, установка, доступ к UI, подключение репозиториев и кластеров, AppProject, RBAC, эксплуатация"
---

# 02. Установка и устройство ArgoCD

> Роадмап → GitOps: *«Поставить ArgoCD, подключить репу гита…»*.
>
> **После темы ты умеешь:** установить ArgoCD, разобраться в его компонентах,
> подключить git-репозиторий и кластеры, настроить доступы и проекты.

---

## 🗺️ Архитектура

```text:no-line-numbers
 ┌──────────────────────────── namespace argocd ────────────────────────────┐
 │                                                                          │
 │  ┌────────────────────┐   читает git, рендерит Helm/Kustomize            │
 │  │ repo-server        │◄──────────────── git-репозитории, Helm-репы      │
 │  └─────────┬──────────┘                                                  │
 │            │ манифесты                                                   │
 │  ┌─────────▼──────────┐   сравнивает желаемое и фактическое,             │
 │  │ application-        │   применяет изменения, следит за здоровьем      │
 │  │ controller         │──────────────────► Kubernetes API (свой и другие)│
 │  └─────────┬──────────┘                                                  │
 │            │ состояние                                                   │
 │  ┌─────────▼──────────┐   API + Web UI + gRPC для CLI, SSO, RBAC         │
 │  │ argocd-server      │◄──────── пользователи, argocd CLI, webhooks      │
 │  └────────────────────┘                                                  │
 │  ┌────────────────────┐   ┌──────────────┐  ┌────────────────────────┐   │
 │  │ redis (кэш)        │   │ dex (SSO)    │  │ applicationset-controller│  │
 │  └────────────────────┘   └──────────────┘  └────────────────────────┘   │
 └──────────────────────────────────────────────────────────────────────────┘
```

| Компонент | За что отвечает |
|-----------|-----------------|
| **argocd-server** | API, веб-интерфейс, аутентификация и RBAC |
| **application-controller** | ⭐ Сердце: сверка состояния, синхронизация, health-проверки |
| **repo-server** | Клонирует репозитории, рендерит Helm/Kustomize в обычные манифесты |
| **redis** | Кэш манифестов и состояний |
| **dex** | Интеграция с внешними провайдерами SSO (можно отключить) |
| **applicationset-controller** | Генерация Application по шаблонам (тема 04) |
| **notifications-controller** | Уведомления в чаты о событиях синхронизации |

---

## 1. Установка

```bash
# --- вариант 1: официальные манифесты (учебный стенд) ---
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl -n argocd rollout status deploy/argocd-server

# --- вариант 2: Helm (прод) ---
helm repo add argo https://argoproj.github.io/argo-helm
helm install argocd argo/argo-cd -n argocd --create-namespace \
  -f values-argocd.yaml          # ⭐ values в git, ставится один раз, дальше сам себя обновляет

# --- вариант 3: HA-манифесты для прода ---
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/ha/install.yaml
```

Первый вход:
```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo

kubectl -n argocd port-forward svc/argocd-server 8080:443
# UI: https://localhost:8080  (admin / <пароль>)

argocd login localhost:8080 --username admin --insecure
argocd account update-password           # ⭐ сразу сменить
```

⚠️ После настройки постоянного доступа (Ingress/SSO) секрет
`argocd-initial-admin-secret` удаляют, а локальный admin отключают.

---

## 2. Доступ к UI в проде

```yaml
# Ingress с TLS-терминацией на ingress-controller
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: argocd-server
  namespace: argocd
  annotations:
    nginx.ingress.kubernetes.io/backend-protocol: "HTTPS"   # argocd-server сам говорит по TLS
    cert-manager.io/cluster-issuer: letsencrypt
spec:
  ingressClassName: nginx
  rules:
    - host: argocd.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend: { service: { name: argocd-server, port: { name: https } } }
  tls:
    - hosts: [argocd.example.com]
      secretName: argocd-tls
```
Альтернатива — режим `--insecure` у argocd-server и TLS только на ingress
(параметр `server.insecure: "true"` в `argocd-cmd-params-cm`).

---

## 3. Подключение git-репозитория ⭐

```bash
# HTTPS + токен (для приватных репозиториев)
argocd repo add https://gitlab.com/org/k8s-manifests.git \
  --username gitops-bot --password "$TOKEN"

# SSH + deploy key (рекомендуется)
argocd repo add git@gitlab.com:org/k8s-manifests.git \
  --ssh-private-key-path ~/.ssh/argocd_deploy_key

# Helm-репозиторий как источник чартов
argocd repo add https://prometheus-community.github.io/helm-charts --type helm --name prometheus-community

argocd repo list
```

Декларативный вариант (⭐ правильный — сам ArgoCD настраивается через git):
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: repo-k8s-manifests
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  type: git
  url: git@gitlab.com:org/k8s-manifests.git
  sshPrivateKey: |
    -----BEGIN OPENSSH PRIVATE KEY-----
    ...                      # ⚠️ в git — только через SOPS/Sealed Secrets/ESO
```

Ускорение реакции: webhook из GitLab/GitHub на `https://argocd.example.com/api/webhook`
вместо опроса раз в 3 минуты.

---

## 4. Подключение кластеров

```bash
# зарегистрировать внешний кластер (контекст из kubeconfig)
argocd cluster add prod-cluster --name prod
argocd cluster list
```
```text:no-line-numbers
Один ArgoCD может управлять несколькими кластерами:
   argocd (в management-кластере) ──► dev-кластер
                                  ──► stage-кластер
                                  ──► prod-кластер
Плюс: единая точка обзора. Минус: единая точка отказа и более широкие права.
Альтернатива: свой ArgoCD в каждом кластере.
```

---

## 5. Проекты (`AppProject`) — границы и безопасность ⭐

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-billing
  namespace: argocd
spec:
  description: Приложения команды биллинга
  sourceRepos:
    - git@gitlab.com:org/billing-manifests.git      # только свои репозитории
  destinations:
    - server: https://kubernetes.default.svc
      namespace: billing-*                          # только свои namespace
  clusterResourceWhitelist: []                      # нельзя создавать кластерные ресурсы
  namespaceResourceBlacklist:
    - group: ""
      kind: ResourceQuota
  roles:
    - name: developer
      policies:
        - p, proj:team-billing:developer, applications, sync, team-billing/*, allow
        - p, proj:team-billing:developer, applications, get,  team-billing/*, allow
```

| Что ограничивает проект | Зачем |
|-------------------------|-------|
| `sourceRepos` | Из каких репозиториев можно деплоить |
| `destinations` | В какие кластеры и namespace |
| `clusterResourceWhitelist/Blacklist` | Можно ли трогать кластерные ресурсы (CRD, ClusterRole) |
| `roles` | Кто что может делать с приложениями проекта |
| `syncWindows` | Окна, когда синхронизация разрешена/запрещена (например, не деплоить в пятницу вечером) |

Проект `default` создаётся автоматически и разрешает всё — ⭐ в проде его сужают
или не используют.

---

## 6. Пользователи, SSO и RBAC

```yaml
# argocd-cm: локальные пользователи (для небольших команд)
apiVersion: v1
kind: ConfigMap
metadata: { name: argocd-cm, namespace: argocd }
data:
  accounts.alice: apiKey, login
  url: https://argocd.example.com
```
```yaml
# argocd-rbac-cm: роли
data:
  policy.default: role:readonly            # ⭐ по умолчанию только чтение
  policy.csv: |
    p, role:devops, applications, *, */*, allow
    p, role:devops, clusters, get, *, allow
    g, alice, role:devops
    g, gitlab-group:sre, role:devops       # маппинг групп из SSO
```

SSO подключают через `dex` (GitLab/GitHub/LDAP) или напрямую по OIDC (Keycloak и др.):
в проде это стандарт, локальные пользователи остаются только для автоматизации.

```bash
# токен для CI
argocd account generate-token --account ci-bot
```

---

## 7. Эксплуатация

| Задача | Как |
|--------|-----|
| Обновление ArgoCD | Через тот же Helm-чарт/манифесты, зафиксированной версией |
| Бэкап | `argocd admin export > backup.yaml` (приложения, проекты, настройки) |
| Восстановление | `argocd admin import -` в новый инстанс |
| Мониторинг | Метрики Prometheus: `argocd_app_info`, `argocd_app_sync_total`, здоровье компонентов |
| Уведомления | `argocd-notifications`: сообщения в чат о `Degraded`, `SyncFailed` |
| Логи | `kubectl -n argocd logs deploy/argocd-application-controller` |
| Ресурсы | На больших инсталляциях узкое место — `application-controller` и `repo-server` |

```text:no-line-numbers
# полезные алерты
sum by (name) (argocd_app_info{health_status!="Healthy"}) > 0
sum by (name) (argocd_app_info{sync_status="OutOfSync"}) > 0
```

---

## 8. Грабли

| Грабля | Последствие | Решение |
|--------|-------------|---------|
| Пароль admin не сменён, UI наружу | Полный контроль над кластером у постороннего | Смена пароля, SSO, Ingress с TLS, отключение локального admin |
| Всё в проекте `default` | Любая команда может задеплоить куда угодно | `AppProject` с ограничениями |
| `policy.default: role:admin` | Все пользователи — администраторы | `role:readonly` по умолчанию |
| Ключ доступа к репозиторию в git открытым текстом | Утечка | SOPS/Sealed Secrets/ESO |
| ArgoCD настроен «руками» в UI | При переустановке всё потеряно | Декларативная конфигурация в git |
| Нет webhook | Изменения применяются с задержкой до 3 минут | Настроить webhook |
| Нет мониторинга приложений | Никто не замечает Degraded | Метрики + уведомления |
| Один ArgoCD на все кластеры без ограничений | Большой радиус поражения | Проекты, RBAC, отдельные инстансы |

---

## 💼 Как это в DevOps

- ArgoCD ставят Helm-чартом, а его собственные настройки (репозитории, проекты, RBAC,
  приложения) описывают в git — в идеале ArgoCD управляет сам собой («self-managed»).
- Доступ в UI — через Ingress с TLS и корпоративным SSO; локальный admin выключают.
- `AppProject` — основной инструмент мультиарендности: команда видит и деплоит только своё.
- Метрики и уведомления обязательны: без них `Degraded`-приложение может висеть сутками.
- Резервная копия — `argocd admin export`; но настоящая «резервная копия» —
  это git-репозиторий, из которого всё восстанавливается.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Установить | манифесты `install.yaml` или Helm `argo/argo-cd` |
| Узнать начальный пароль | secret `argocd-initial-admin-secret` |
| Открыть UI локально | `kubectl -n argocd port-forward svc/argocd-server 8080:443` |
| Войти из CLI | `argocd login <host> --username admin` |
| Сменить пароль | `argocd account update-password` |
| Подключить репозиторий | `argocd repo add <url> --ssh-private-key-path ...` |
| Подключить Helm-репозиторий | `argocd repo add <url> --type helm --name <name>` |
| Список репозиториев | `argocd repo list` |
| Подключить кластер | `argocd cluster add <context> --name prod` |
| Ограничить команду | `AppProject` с `sourceRepos`/`destinations`/`roles` |
| Роли и доступы | `argocd-rbac-cm` (`policy.csv`, `policy.default`) |
| Токен для CI | `argocd account generate-token --account ci-bot` |
| Бэкап настроек | `argocd admin export > backup.yaml` |
| Логи контроллера | `kubectl -n argocd logs deploy/argocd-application-controller` |

---

## 🧠 Что запомнить

1. Ключевые компоненты: `application-controller` (сверка и применение),
   `repo-server` (чтение git и рендер), `argocd-server` (API/UI/RBAC).
2. Установка — манифесты для стенда, Helm/HA-манифесты для прода.
3. ⭐ Первым делом меняют пароль admin и закрывают UI (Ingress + TLS + SSO).
4. Репозитории и кластеры подключают декларативно через секреты и манифесты в git,
   а не кликами в UI.
5. Ключи доступа к репозиториям хранят зашифрованными (SOPS/Sealed Secrets/ESO).
6. `AppProject` ограничивает, откуда и куда можно деплоить — основа мультиарендности.
7. RBAC по умолчанию должен быть `role:readonly`, права выдаются группам из SSO.
8. Webhook из git ускоряет реакцию по сравнению с периодическим опросом.
9. Метрики `argocd_app_info` и уведомления — обязательная часть эксплуатации.
10. Настоящий бэкап GitOps-инсталляции — сам git-репозиторий; `argocd admin export`
    дополняет его.

---

## Задачи

> Стенд: kind/minikube + ArgoCD + свой git-репозиторий с манифестами.

---

### Блок A. Теория

**A1.** Назови основные компоненты ArgoCD и задачу каждого.

<details><summary>Ответ</summary>

`argocd-server` (API, UI, RBAC), `application-controller` (сверка, синхронизация,
health), `repo-server` (чтение репозиториев и рендер Helm/Kustomize), `redis` (кэш),
`dex` (SSO), `applicationset-controller`, `notifications-controller`.

</details>

**A2.** ⭐ Какой компонент выполняет сверку состояния и применяет изменения?

<details><summary>Ответ</summary>

`application-controller`.

</details>

**A3.** Что делает `repo-server`?

<details><summary>Ответ</summary>

Клонирует репозитории, выполняет рендеринг шаблонов (Helm, Kustomize,
jsonnet) и отдаёт контроллеру готовые манифесты.

</details>

**A4.** Зачем ArgoCD нужен redis?

<details><summary>Ответ</summary>

Как кэш отрендеренных манифестов и состояний — снижает нагрузку на repo-server
и ускоряет работу UI.

</details>

**A5.** Чем отличается установка из `install.yaml` от `ha/install.yaml` и Helm-чарта?

<details><summary>Ответ</summary>

`install.yaml` — одиночные экземпляры компонентов (стенд); `ha/install.yaml` —
несколько реплик и HA-redis; Helm — параметризуемая установка, удобная для GitOps
и обновлений.

</details>

**A6.** Где взять первоначальный пароль администратора и что с ним делать дальше?

<details><summary>Ответ</summary>

В секрете `argocd-initial-admin-secret`; после первого входа пароль меняют,
настраивают SSO, а секрет удаляют.

</details>

**A7.** Как правильно открыть UI наружу?

<details><summary>Ответ</summary>

Через Ingress с TLS (и корректной аннотацией backend-protocol), корпоративный
SSO, ограничение доступа сетью; не оставлять port-forward и дефолтные креды.

</details>

**A8.** Какие способы подключения git-репозитория есть и какой предпочтителен?

<details><summary>Ответ</summary>

HTTPS с токеном или SSH с deploy-key; предпочтительнее SSH-ключ с правами
только на чтение, хранящийся в зашифрованном виде.

</details>

**A9.** Почему репозитории и проекты лучше описывать декларативно?

<details><summary>Ответ</summary>

Чтобы конфигурация ArgoCD восстанавливалась из git, проходила ревью
и не терялась при переустановке.

</details>

**A10.** Как ускорить реакцию ArgoCD на коммит?

<details><summary>Ответ</summary>

Настроить webhook из git-хостинга; по умолчанию опрос выполняется
с интервалом около трёх минут.

</details>

**A11.** Может ли один ArgoCD управлять несколькими кластерами? Плюсы и минусы.

<details><summary>Ответ</summary>

Да: кластеры регистрируются и указываются в `destination`. Плюс — единая точка
обзора; минус — единая точка отказа и более широкие права; альтернатива — отдельный
ArgoCD в каждом кластере.

</details>

**A12.** ⭐ Что такое `AppProject` и что он ограничивает?

<details><summary>Ответ</summary>

Логическая группа приложений с ограничениями: из каких репозиториев,
в какие кластеры и namespace можно деплоить, какие ресурсы разрешены, какие роли
и окна синхронизации действуют.

</details>

**A13.** Как устроен RBAC в ArgoCD и каким должен быть `policy.default`?

<details><summary>Ответ</summary>

Через `argocd-rbac-cm`: политики в `policy.csv` и значение по умолчанию
`policy.default`. По умолчанию должно быть `role:readonly`.

</details>

**A14.** Как выдать доступ CI-системе?

<details><summary>Ответ</summary>

Создать сервисный аккаунт (`accounts.ci-bot` в `argocd-cm`), выдать ему
минимальные права и сгенерировать токен `argocd account generate-token`.

</details>

**A15.** Как делать бэкап ArgoCD и что на самом деле является главной резервной копией?

<details><summary>Ответ</summary>

`argocd admin export/import` для настроек; но основная «резервная копия» —
git-репозиторий с приложениями и конфигурацией, из которого всё разворачивается заново.

</details>

---

### Блок B. «Оцени конфигурацию»

```text:no-line-numbers
B1.  UI ArgoCD доступен из интернета, пароль admin по умолчанию
```

<details><summary>Ответ</summary>

Критическая дыра: доступ к UI = управление кластером.

</details>

```text:no-line-numbers
B2.  UI за Ingress с TLS, вход через корпоративный SSO, локальный admin отключён
```

<details><summary>Ответ</summary>

Правильная конфигурация.

</details>

```text:no-line-numbers
B3.  policy.default: role:admin
```

<details><summary>Ответ</summary>

Все пользователи получают полные права.

</details>

```text:no-line-numbers
B4.  policy.default: role:readonly, права выдаются группам SSO
```

<details><summary>Ответ</summary>

Правильный подход.

</details>

```text:no-line-numbers
B5.  Все приложения в проекте default
```

<details><summary>Ответ</summary>

Отсутствие границ между командами.

</details>

```text:no-line-numbers
B6.  У каждой команды свой AppProject с ограничением репозиториев и namespace
```

<details><summary>Ответ</summary>

Правильная мультиарендность.

</details>

```text:no-line-numbers
B7.  Deploy-key репозитория закоммичен в git в открытом виде
```

<details><summary>Ответ</summary>

Утечка доступа к репозиторию.

</details>

```text:no-line-numbers
B8.  Секрет репозитория зашифрован SOPS и лежит в git
```

<details><summary>Ответ</summary>

Приемлемо при корректном управлении ключами SOPS.

</details>

```text:no-line-numbers
B9.  Репозитории добавлены через UI, нигде не зафиксированы
```

<details><summary>Ответ</summary>

Настройки потеряются при переустановке, нет ревью.

</details>

```text:no-line-numbers
B10. ArgoCD управляет сам собой: его Helm-values лежат в git как Application
```

<details><summary>Ответ</summary>

Хорошая практика (self-managed ArgoCD).

</details>

```text:no-line-numbers
B11. Webhook не настроен, ждут синхронизацию по таймеру
```

<details><summary>Ответ</summary>

Задержки в применении изменений.

</details>

```text:no-line-numbers
B12. Мониторинга приложений нет, статусы смотрят глазами в UI
```

<details><summary>Ответ</summary>

Проблемы замечают поздно; нужны метрики и уведомления.

</details>

---

### Блок C. Практика

#### C1. 🔑 Установка
1. Подними kind-кластер, установи ArgoCD.
2. Дождись готовности подов, посмотри, какие компоненты появились.
3. Получи пароль, зайди в UI и через CLI, смени пароль.

#### C2. Разобрать компоненты
Для каждого пода в namespace `argocd` определи по логам и описанию, что он делает.
Останови `repo-server` и посмотри, что перестанет работать.

<details><summary>Ответ</summary>

Без `repo-server` ArgoCD не сможет получать и рендерить манифесты: приложения
перестанут синхронизироваться, в UI появятся ошибки сравнения.

</details>

#### C3. Подключение репозитория
1. Создай публичный репозиторий с манифестами.
2. Подключи его через CLI, затем удали и подключи декларативно (Secret с меткой).
3. Проверь `argocd repo list`.

#### C4. Приватный репозиторий
Создай deploy-key, подключи приватный репозиторий по SSH.
Опиши, где будет храниться ключ в реальном проекте.

#### C5. Webhook
Настрой webhook из GitHub/GitLab на ArgoCD (через `ngrok` или локальный адрес,
если возможно). Сравни скорость реакции с опросом.

#### C6. 🔑 AppProject
1. Создай проект `team-a`: только один репозиторий, только namespace `team-a-*`.
2. Попробуй создать приложение из другого репозитория — должно быть запрещено.
3. Добавь `syncWindows`, запрещающее синхронизацию в определённый интервал.

<details><summary>Ответ</summary>

При нарушении ограничений проекта ArgoCD вернёт ошибку вида
«application destination is not permitted in project».

</details>

#### C7. RBAC
1. Поставь `policy.default: role:readonly`.
2. Создай локального пользователя и выдай ему права только на одно приложение.
3. Проверь, что он не может синхронизировать чужие приложения.

<details><summary>Ответ</summary>

После `policy.default: role:readonly` новый пользователь сможет только смотреть.

</details>

#### C8. Токен для CI
Создай сервисный аккаунт и токен, выполни `argocd app list` этим токеном.

#### C9. Мониторинг
Подключи метрики ArgoCD к Prometheus, построй панель со статусами приложений
и настрой алерт на `health_status != Healthy`.

#### C10. Бэкап и восстановление
1. Сделай `argocd admin export > backup.yaml`.
2. Снеси ArgoCD полностью и установи заново.
3. Восстанови настройки импортом и сравни с вариантом «просто применить манифесты из git».

<details><summary>Ответ</summary>

Восстановление через git обычно быстрее и надёжнее: приложения создаются заново
из репозитория.

</details>

---

### Блок D. Инциденты

**D1.** ArgoCD не видит изменения в репозитории. Алгоритм проверки.

<details><summary>Ответ</summary>

Проверить: подключён ли репозиторий и с какими кредами, правильные ли `repoURL`,
`path`, `targetRevision`, есть ли ошибки в `repo-server`, настроен ли webhook,
не кэшируется ли ревизия, состояние приложения (`argocd app get`).

</details>

**D2.** Приложение не создаётся: ошибка про запрещённый destination. Что смотреть?

<details><summary>Ответ</summary>

Ограничения `AppProject` (`destinations`, `sourceRepos`), namespace, кластер,
права пользователя.

</details>

**D3.** `repo-server` постоянно перезапускается по OOM. Причины и решения.

<details><summary>Ответ</summary>

Большие репозитории, много приложений и тяжёлый рендеринг Helm; увеличить
лимиты памяти и число реплик, включить кэш, разделить репозитории, использовать
`--parallelismlimit`.

</details>

**D4.** Забыт пароль администратора, SSO ещё не настроен. Что делать?

<details><summary>Ответ</summary>

Сбросить пароль администратора через патч секрета `argocd-secret`
(поле `admin.password` с bcrypt-хешем) и перезапуск `argocd-server`.

</details>

**D5.** После обновления ArgoCD перестали работать некоторые Application. Действия?

<details><summary>Ответ</summary>

Смотреть changelog версии, логи контроллера, изменения в CRD и в схеме
`Application`; откатить версию ArgoCD при необходимости и обновлять по инструкции.

</details>

**D6.** Пользователь видит чужие приложения. Что настроено неверно?

<details><summary>Ответ</summary>

Слишком широкие RBAC-политики или отсутствие разделения по проектам.

</details>

**D7.** Кластер `prod` отвалился из списка. Как проверить подключение?

<details><summary>Ответ</summary>

`argocd cluster list`, доступность API-сервера, срок действия токена сервисного
аккаунта в целевом кластере, сетевой доступ, сертификаты.

</details>

**D8.** ArgoCD полностью удалили вместе с namespace. Что потеряно, а что нет?

<details><summary>Ответ</summary>

Потеряны только собственные настройки ArgoCD (если они не в git); нагрузки
в кластере продолжают работать. После переустановки состояние восстанавливается
из репозитория.

</details>

**D9.** Deploy-key скомпрометирован. Порядок действий.

<details><summary>Ответ</summary>

Отозвать ключ в git-хостинге, выпустить новый, обновить секрет (через SOPS/ESO),
проверить историю доступа, при подозрении на утечку данных — разобрать инцидент.

</details>

**D10.** Синхронизации выполняются медленно, приложений 300. Что оптимизировать?

<details><summary>Ответ</summary>

Увеличить ресурсы и реплики контроллера и repo-server, настроить sharding
контроллера по кластерам, уменьшить частоту опроса и включить webhook, разделить
инсталляции по командам/кластерам, оптимизировать репозитории.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Из каких компонентов состоит ArgoCD?

<details><summary>Ответ</summary>

argocd-server, application-controller, repo-server, redis, dex,
applicationset-controller, notifications-controller.

</details>

**2.** Как ставят ArgoCD в проде?

<details><summary>Ответ</summary>

Helm-чартом или HA-манифестами, с доступом через Ingress и SSO, конфигурацией в git.

</details>

**3.** Как подключают репозитории и кластеры?

<details><summary>Ответ</summary>

Через CLI или декларативно секретами с меткой `argocd.argoproj.io/secret-type`;
кластеры — `argocd cluster add`.

</details>

**4.** Что такое AppProject?

<details><summary>Ответ</summary>

Логическая группа приложений с ограничениями по репозиториям, кластерам,
namespace, ресурсам и ролям.

</details>

**5.** Как устроен RBAC?

<details><summary>Ответ</summary>

Через `argocd-rbac-cm`: политики и роли, маппинг групп SSO, значение по умолчанию.

</details>

**6.** Как ArgoCD узнаёт об изменениях в git?

<details><summary>Ответ</summary>

Периодическим опросом репозитория и/или webhook из git-хостинга.

</details>

**7.** Может ли ArgoCD управлять несколькими кластерами?

<details><summary>Ответ</summary>

Да, регистрируя дополнительные кластеры; либо ставят отдельный ArgoCD в каждый.

</details>

**8.** Как защитить доступ к ArgoCD?

<details><summary>Ответ</summary>

TLS, SSO, отключение локального admin, RBAC, сетевые ограничения, проекты.

</details>

**9.** Как делают бэкап конфигурации ArgoCD?

<details><summary>Ответ</summary>

`argocd admin export`; плюс основная гарантия — сам git-репозиторий.

</details>

**10.** Что мониторите у ArgoCD?

<details><summary>Ответ</summary>

Статусы приложений (`Healthy`/`Synced`), ошибки синхронизации, состояние компонентов,
ресурсы controller и repo-server.

</details>

---

### 🎯 Чек-лист

- [ ] Установил ArgoCD и вошёл в UI и CLI
- [ ] Сменил пароль и понимаю, как закрыть доступ в проде
- [ ] Знаю роль каждого компонента
- [ ] Подключил репозиторий через CLI и декларативно
- [ ] Подключил приватный репозиторий по SSH
- [ ] ⭐ Создал `AppProject` с ограничениями и проверил их
- [ ] Настроил RBAC с `role:readonly` по умолчанию
- [ ] Создал токен для CI
- [ ] Подключил метрики и алерты
- [ ] Понимаю, что главный бэкап — это git
