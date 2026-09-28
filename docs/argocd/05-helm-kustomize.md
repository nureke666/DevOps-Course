---
title: "05. Helm, Kustomize и секреты в GitOps"
description: "Деплой Helm-чартов и Kustomize-оверлеев через ArgoCD, multi-source Application, секреты (SOPS, Sealed Secrets, External Secrets), обновление образов"
---

# 05. Helm, Kustomize и секреты в GitOps

> Роадмап → GitOps: *«…хелм чарты через арго»*.
>
> **После темы ты умеешь:** деплоить Helm-чарты и Kustomize-оверлеи через ArgoCD,
> управлять values для разных окружений и безопасно работать с секретами.

---

## 🗺️ Три способа описать приложение

```text:no-line-numbers
 ПРОСТЫЕ МАНИФЕСТЫ        KUSTOMIZE                    HELM
 ─────────────────        ─────────                    ────
 apps/demo/*.yaml         base/ + overlays/            chart + values.yaml
 просто и понятно         патчи без шаблонов           шаблоны, зависимости, релизы
 копипаста между          ⭐ «наложить отличия»         ⭐ готовые чарты сообщества
 окружениями              k8s-native                   свой язык шаблонов
```

ArgoCD `repo-server` умеет рендерить все три варианта — на выходе всегда обычные
манифесты, которые применяются к кластеру.

---

## 1. Helm-чарт через ArgoCD

```yaml
# чарт из своего репозитория
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: { name: billing, namespace: argocd }
spec:
  project: default
  source:
    repoURL: https://gitlab.com/org/gitops-repo.git
    targetRevision: main
    path: charts/billing              # каталог с Chart.yaml
    helm:
      releaseName: billing
      valueFiles:
        - values.yaml
        - values-prod.yaml            # ⭐ значения окружения
      parameters:
        - name: image.tag
          value: "1.4.2"              # то, что обновляет CI
      values: |                       # инлайн-переопределения
        ingress:
          host: billing.example.com
  destination: { server: https://kubernetes.default.svc, namespace: billing }
  syncPolicy: { automated: { prune: true, selfHeal: true }, syncOptions: [CreateNamespace=true] }
```

```yaml
# публичный чарт из Helm-репозитория
spec:
  source:
    repoURL: https://stefanprodan.github.io/podinfo
    chart: podinfo                     # ⭐ имя чарта, а не path
    targetRevision: 6.15.0             # ⭐ версия чарта (фиксируем!)
    helm:
      valueFiles: []
      values: |
        replicaCount: 2
        ui:
          message: "deployed by ArgoCD"
```

> ⚠️ В старых примерах здесь стоит `repoURL: https://charts.bitnami.com/bitnami` + `redis`.
> После того как Bitnami (Broadcom) в 2025 свернула бесплатный каталог (образы — в
> `bitnamilegacy` без обновлений, актуальные — в платных Bitnami Secure Images), такие
> чарты — не безопасный дефолт: берём чарты от авторов ПО (`prometheus-community`,
> `grafana`, CloudNativePG) или демо-чарт `podinfo`.

Комбинированный вариант (values в своём репозитории, чарт — внешний) — через
`sources` (multi-source Application):
```yaml
spec:
  sources:
    - repoURL: https://stefanprodan.github.io/podinfo
      chart: podinfo
      targetRevision: 6.15.0
      helm:
        valueFiles:
          - $values/envs/prod/podinfo-values.yaml   # ⭐ ссылка на второй источник
    - repoURL: https://gitlab.com/org/gitops-repo.git
      targetRevision: main
      ref: values
```

⚠️ Важное отличие от «обычного» Helm: ArgoCD **не создаёт Helm-релиз**
(`helm list` его не покажет). Он рендерит чарт и применяет манифесты сам,
а состоянием управляет через `Application`. Поэтому `helm rollback` не работает —
откат делается через git.

| Поле | Зачем |
|------|-------|
| `valueFiles` | Файлы значений (в том числе по окружениям) |
| `parameters` | Точечные переопределения (`image.tag` из CI) |
| `values` | Инлайн YAML |
| `releaseName` | Имя релиза для шаблонов чарта |
| `skipCrds` | Не применять CRD из чарта |
| `ignoreMissingValueFiles` | Не падать, если файла значений нет |

---

## 2. Kustomize через ArgoCD

```text:no-line-numbers
manifests/billing/
├── base/
│   ├── deployment.yaml
│   ├── service.yaml
│   └── kustomization.yaml
└── overlays/
    ├── dev/
    │   ├── kustomization.yaml        # replicas: 1, другой host
    │   └── patch-deployment.yaml
    └── prod/
        ├── kustomization.yaml        # replicas: 3, ресурсы больше
        └── patch-deployment.yaml
```
```yaml
# Application на overlay
spec:
  source:
    repoURL: https://gitlab.com/org/gitops-repo.git
    path: manifests/billing/overlays/prod
    kustomize:
      images:
        - myregistry/billing:1.4.2     # ⭐ подмена тега образа (это правит CI)
      namePrefix: prod-
      commonLabels:
        env: prod
```
```yaml
# overlays/prod/kustomization.yaml
resources: [ ../../base ]
patches:
  - path: patch-deployment.yaml
images:
  - name: myregistry/billing
    newTag: 1.4.2
replicas:
  - name: billing
    count: 3
```

| Helm | Kustomize |
|------|-----------|
| Шаблоны и логика (`if`, `range`) | Только наложение патчей |
| Готовые чарты сообщества | Всё своё, но проще читать |
| Значения в одном месте | Отличия видны как патчи |
| Сложнее отлаживать (`helm template`) | `kubectl kustomize` показывает результат |

В реальных проектах часто сочетают: сторонние компоненты — чартами,
свои приложения — Kustomize (или наоборот; главное — единообразие).

---

## 3. ⭐ Секреты в GitOps

```text:no-line-numbers
 ПРОБЛЕМА: git — источник правды, но класть в него секреты открытым текстом нельзя.

 ТРИ РЕШЕНИЯ:
 1. ШИФРОВАНИЕ В GIT          SOPS (+ age/KMS/Vault), git-crypt
    зашифрованный файл в репозитории, ключ — вне репозитория
 2. ЗАПЕЧАТАННЫЕ СЕКРЕТЫ      Sealed Secrets (Bitnami)
    SealedSecret в git расшифровывает только контроллер в кластере
 3. ВНЕШНЕЕ ХРАНИЛИЩЕ ⭐       External Secrets Operator, Vault Agent, CSI-драйвер
    в git — только ССЫЛКА на секрет; значение берётся из Vault/облака
```

```yaml
# Sealed Secrets: в git лежит вот это — безопасно
apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata: { name: db-credentials, namespace: billing }
spec:
  encryptedData:
    password: AgBv7Q8... (шифротекст)
```
```bash
kubeseal --format yaml < secret.yaml > sealed-secret.yaml   # шифруем публичным ключом контроллера
```

```yaml
# External Secrets Operator: в git — ссылка, значение приезжает из Vault
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata: { name: db-credentials, namespace: billing }
spec:
  secretStoreRef: { name: vault-backend, kind: ClusterSecretStore }
  target: { name: db-credentials }
  data:
    - secretKey: password
      remoteRef: { key: secret/data/billing, property: db_password }
  refreshInterval: 1h
```

| Решение | Плюсы | Минусы |
|---------|-------|--------|
| **SOPS** | Гибко, работает и вне k8s, ключи в KMS/age | Нужен плагин рендеринга в ArgoCD, управление ключами |
| **Sealed Secrets** | Просто, k8s-native, безопасно хранить в git | Ключ контроллера — критичный артефакт; ротация непроста |
| **External Secrets** ⭐ | Секреты не в git вообще, централизованное хранилище, ротация | Нужен Vault/облачный сервис и ещё один оператор |

⚠️ Чего делать нельзя: класть `Secret` с base64 в git («base64 — не шифрование»),
хранить пароли в values-файлах, передавать секреты параметрами в `Application`.

---

## 4. Обновление версии образа

```text:no-line-numbers
 CI собрал образ myapp:1.4.2
        │
        ├─ вариант A (⭐ прозрачный): CI коммитит новый тег в git
        │     kustomize edit set image myapp=myapp:1.4.2   (или yq по values)
        │     git commit -m "deploy myapp 1.4.2" && git push
        │
        └─ вариант B: Argo CD Image Updater сам следит за registry
              аннотации на Application, автоматический коммит или запись в Application
```

```yaml
# аннотации для Image Updater
metadata:
  annotations:
    argocd-image-updater.argoproj.io/image-list: myapp=myregistry/myapp
    argocd-image-updater.argoproj.io/myapp.update-strategy: semver
    argocd-image-updater.argoproj.io/write-back-method: git
```

Рекомендация: для прода — вариант A (видно в истории git, проходит ревью),
для dev-окружений допустим B.

---

## 5. Грабли

| Грабля | Последствие | Решение |
|--------|-------------|---------|
| `targetRevision: "*"` у публичного чарта | Обновление чарта прилетает само | Фиксировать версию |
| Ожидание `helm list`/`helm rollback` | Их нет: релизом управляет Argo | Откат через git |
| Секрет в values в git | Утечка | SOPS / Sealed Secrets / ESO |
| `Secret` с base64 в git | То же самое, base64 не шифрует | См. выше |
| Разные подходы (Helm+Kustomize+manifests) без правил | Хаос в репозитории | Договориться о единообразии |
| Значения окружений внутри чарта | Прод меняется вместе с чартом | Values-файлы по окружениям |
| Тег `latest` | Непредсказуемый деплой, нет отката | Конкретные версии |
| CRD из чарта и порядок применения | Ошибки при первом деплое | `skipCrds`/`sync-wave`, отдельные приложения |
| Image Updater пишет в прод автоматически | Неконтролируемые релизы | Ручной коммит и ревью для прода |

---

## 💼 Как это в DevOps

- Сторонние компоненты (ingress, cert-manager, мониторинг) обычно ставят чартами
  с зафиксированной версией; свои приложения — Kustomize-оверлеями или собственным чартом.
- Values по окружениям лежат в конфиг-репозитории рядом с `Application` — так видно,
  чем отличается прод.
- Секреты — почти всегда либо Sealed Secrets (проще), либо External Secrets + Vault
  (зрелее); выбор фиксируют на уровне платформы.
- CI обновляет только тег образа, остальное меняют люди через MR: это разделение
  «что катим» и «как настроено».
- На собеседовании достаточно объяснить: Argo рендерит чарт сам, релизов Helm нет,
  секреты в git — только зашифрованные или по ссылке.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Деплой своего чарта | `source.path` + `helm.valueFiles` |
| Деплой публичного чарта | `repoURL` Helm-репозитория + `chart` + `targetRevision` |
| Values из другого репозитория | multi-source `sources` + `$values` |
| Переопределить одно значение | `helm.parameters` |
| Kustomize-оверлей | `source.path` на overlay + `kustomize.images` |
| Подменить тег образа | `kustomize.images` или `helm.parameters` |
| Посмотреть результат рендеринга | `helm template` / `kubectl kustomize` |
| Секрет в git безопасно | Sealed Secrets (`kubeseal`) или SOPS |
| Секрет вне git | External Secrets + Vault |
| Автообновление образов | Argo CD Image Updater (осторожно с продом) |
| Не применять CRD из чарта | `helm.skipCrds: true` |

---

## 🧠 Что запомнить

1. ArgoCD рендерит Helm и Kustomize сам: в кластер уходят обычные манифесты.
2. ⭐ Helm-релизов ArgoCD не создаёт: `helm list`/`helm rollback` не работают,
   откат — через git.
3. Версии публичных чартов фиксируют; `targetRevision` — это версия чарта.
4. Values по окружениям хранят отдельными файлами; CI меняет только тег образа.
5. Multi-source позволяет брать чарт из одного репозитория, а values — из своего.
6. Kustomize проще для своих приложений: базовые манифесты + патчи окружений.
7. Секреты в git — только зашифрованные (SOPS, Sealed Secrets) или по ссылке (ESO).
8. `base64` в `Secret` — не шифрование; такой файл в git недопустим.
9. Порядок CRD и приложений решают `sync-wave` или отдельные Application.
10. Автообновление образов удобно для dev, но прод лучше обновлять коммитом с ревью.

---

## Задачи

> Стенд: ArgoCD + репозиторий с чартом и Kustomize-оверлеями.

---

### Блок A. Теория

**A1.** Какие три способа описания приложения умеет рендерить ArgoCD?

<details><summary>Ответ</summary>

Обычные манифесты YAML, Kustomize-оверлеи и Helm-чарты
(плюс плагины вроде jsonnet и кастомные генераторы манифестов).

</details>

**A2.** ⭐ Создаёт ли ArgoCD Helm-релиз? Что это значит на практике?

<details><summary>Ответ</summary>

Нет: ArgoCD рендерит чарт и применяет получившиеся манифесты сам.
Практически это значит, что `helm list` не покажет приложение, `helm rollback`
не работает, а история и откат живут в git и в истории синхронизаций Argo.

</details>

**A3.** Что означает `targetRevision` для публичного Helm-чарта?

<details><summary>Ответ</summary>

Версию Helm-чарта в репозитории чартов (а не ветку git).

</details>

**A4.** Чем `valueFiles`, `parameters` и `values` отличаются друг от друга?

<details><summary>Ответ</summary>

`valueFiles` — файлы значений; `parameters` — точечные переопределения
отдельных ключей (удобно для `image.tag` из CI); `values` — инлайн-YAML
в самом Application.

</details>

**A5.** Что такое multi-source Application и зачем он нужен?

<details><summary>Ответ</summary>

Application с несколькими источниками: например, чарт из публичного
репозитория и файл значений из своего (`$values`). Позволяет не форкать чужие чарты.

</details>

**A6.** Как подменить тег образа в Helm и в Kustomize?

<details><summary>Ответ</summary>

В Helm — `helm.parameters` (`image.tag`) или values-файл;
в Kustomize — секция `images` (или `kustomize edit set image`).

</details>

**A7.** Сравни Helm и Kustomize: по три плюса каждому.

<details><summary>Ответ</summary>

Helm: шаблоны и логика, готовые чарты сообщества, единая точка значений.
Kustomize: нет шаблонного языка (проще читать), k8s-native патчи, легко посмотреть
результат `kubectl kustomize`.

</details>

**A8.** ⭐ Почему нельзя класть `Secret` с base64 в git?

<details><summary>Ответ</summary>

base64 — это кодирование, а не шифрование: любой, у кого есть доступ
к репозиторию, читает секрет одной командой.

</details>

**A9.** Как работает Sealed Secrets?

<details><summary>Ответ</summary>

Контроллер в кластере имеет пару ключей; `kubeseal` шифрует секрет публичным
ключом, в git лежит `SealedSecret`, который может расшифровать только этот контроллер
(по умолчанию — с привязкой к namespace и имени).

</details>

**A10.** Как работает External Secrets Operator?

<details><summary>Ответ</summary>

Оператор читает значения из внешнего хранилища (Vault, облачный secret manager)
по описанию `ExternalSecret` и создаёт обычный `Secret` в кластере, периодически
обновляя его.

</details>

**A11.** Что такое SOPS и в чём его особенность для ArgoCD?

<details><summary>Ответ</summary>

SOPS шифрует файлы (values, манифесты) ключами age/KMS/Vault; в git лежит
шифротекст. Для ArgoCD требуется плагин рендеринга (например, `argocd-vault-plugin`
или kustomize-плагин), чтобы расшифровывать при сборке манифестов.

</details>

**A12.** Сравни три подхода к секретам: плюсы, минусы, когда что выбирать.

<details><summary>Ответ</summary>

SOPS — гибко и вне k8s, но нужен плагин и управление ключами.
Sealed Secrets — просто и k8s-native, но ключ контроллера критичен и ротация непроста.
External Secrets — секретов в git нет вовсе и есть ротация, но нужен Vault/облачный
сервис и ещё один оператор. Для зрелых платформ обычно выбирают ESO.

</details>

**A13.** Какие есть способы обновления тега образа и какой предпочтителен для прода?

<details><summary>Ответ</summary>

Коммит нового тега из CI (прозрачно, проходит ревью) или Argo CD Image Updater
(автоматически). Для прода предпочтителен коммит.

</details>

**A14.** Зачем нужен `skipCrds` и как ещё решают проблему порядка CRD?

<details><summary>Ответ</summary>

`skipCrds` не применяет CRD из чарта (когда ими управляют отдельно);
альтернативы — отдельное Application для CRD и `sync-wave`.

</details>

**A15.** Почему тег `latest` несовместим с GitOps?

<details><summary>Ответ</summary>

`latest` не фиксирует версию: нельзя воспроизвести состояние, нельзя откатиться,
кластер может «сам» обновиться при перезапуске пода.

</details>

---

### Блок B. «Оцени конфигурацию»

```yaml
B1.  source: { repoURL: https://stefanprodan.github.io/podinfo, chart: podinfo, targetRevision: "*" }
```

<details><summary>Ответ</summary>

Незафиксированная версия чарта — обновление прилетит само.

</details>

```yaml
B2.  source: { repoURL: https://stefanprodan.github.io/podinfo, chart: podinfo, targetRevision: 6.15.0 }
```

<details><summary>Ответ</summary>

Правильно.

</details>

```yaml
B3.  helm: { values: "postgresPassword: SuperSecret123" }
```

<details><summary>Ответ</summary>

Пароль в values в git — утечка.

</details>

```text:no-line-numbers
B4.  В git лежит Secret с data.password: cGFzc3dvcmQ= (base64)
```

<details><summary>Ответ</summary>

base64 не защищает — фактически открытый секрет.

</details>

```text:no-line-numbers
B5.  В git лежит SealedSecret с encryptedData
```

<details><summary>Ответ</summary>

Безопасно.

</details>

```text:no-line-numbers
B6.  В git лежит ExternalSecret со ссылкой на Vault
```

<details><summary>Ответ</summary>

Безопасно и предпочтительно.

</details>

```yaml
B7.  kustomize: { images: [ myapp:latest ] }
```

<details><summary>Ответ</summary>

`latest` — непредсказуемость и отсутствие отката.

</details>

```yaml
B8.  kustomize: { images: [ myapp:1.4.2 ] }, тег обновляет CI коммитом
```

<details><summary>Ответ</summary>

Правильный процесс.

</details>

```text:no-line-numbers
B9.  values-prod.yaml лежит внутри чарта в репозитории разработчиков
```

<details><summary>Ответ</summary>

Значения окружений внутри чарта разработчиков смешивают «что» и «как настроено».

</details>

```text:no-line-numbers
B10. values-prod.yaml лежит в конфиг-репозитории рядом с Application
```

<details><summary>Ответ</summary>

Правильное размещение.

</details>

```text:no-line-numbers
B11. Image Updater обновляет прод автоматически при появлении нового тега
```

<details><summary>Ответ</summary>

Автоматический выкат в прод без ревью — риск.

</details>

```text:no-line-numbers
B12. Команда использует одновременно Helm, Kustomize и голые манифесты без правил
```

<details><summary>Ответ</summary>

Отсутствие единообразия усложняет ревью и поддержку.

</details>

---

### Блок C. Практика

#### C1. 🔑 Публичный чарт
1. Задеплой через ArgoCD публичный чарт (например, `podinfo` или `grafana/grafana`)
   с зафиксированной версией.
2. Переопредели пару значений через `helm.values`.
3. Измени версию чарта и посмотри план изменений в UI.

#### C2. Свой чарт
Создай минимальный чарт (`helm create`) в конфиг-репозитории, задеплой его через Argo,
добавь `values-dev.yaml` и `values-prod.yaml` и два Application.

#### C3. Helm-релизы
1. Выполни `helm list -A` в кластере — увидишь ли приложение, задеплоенное Argo?
2. Попробуй `helm rollback` — объясни результат.
3. Сделай корректный откат через git.

<details><summary>Ответ</summary>

`helm list -A` не покажет приложение: Argo не создаёт релиз;
`helm rollback` завершится ошибкой «release not found».

</details>

#### C4. 🔑 Kustomize
1. Сделай `base/` и два overlay (`dev`, `prod`) с разными replicas и ресурсами.
2. Проверь локально `kubectl kustomize overlays/prod`.
3. Создай два Application на оверлеи.

#### C5. Подмена образа
1. Обнови тег образа через `kustomize edit set image` и закоммить.
2. Проверь, что Argo применил изменение.
3. Повтори то же самое для чарта через `helm.parameters`.

#### C6. Multi-source
Настрой Application, где чарт берётся из публичного репозитория,
а values — из твоего конфиг-репозитория (`$values`).

#### C7. ⭐ Sealed Secrets
1. Установи контроллер Sealed Secrets (через Argo, разумеется).
2. Запечатай секрет `kubeseal`, закоммить SealedSecret.
3. Проверь, что в кластере появился обычный Secret.
4. Попробуй применить тот же SealedSecret в другом namespace — объясни результат.

<details><summary>Ответ</summary>

SealedSecret по умолчанию привязан к namespace и имени: в другом namespace
он не расшифруется (если не использован scope `cluster-wide`).

</details>

#### C8. External Secrets (со звёздочкой)
Подними Vault в dev-режиме (см. тему про Vault), установи ESO, настрой
`ClusterSecretStore` и `ExternalSecret`, проверь появление Secret и его обновление.

#### C9. Проверка на секреты
Добавь в CI конфиг-репозитория проверку `gitleaks`/`trufflehog`, чтобы открытый
секрет не мог попасть в git. Проверь на тестовом коммите.

<details><summary>Ответ</summary>

`gitleaks` в CI — дешёвая и эффективная защита от случайного коммита секрета.

</details>

#### C10. Единообразие
Опиши для своего проекта правила: что описываем чартами, что Kustomize,
где лежат values, как работаем с секретами, кто и как обновляет теги образов.

---

### Блок D. Инциденты

**D1.** После обновления публичного чарта сломался прод. Что было настроено неверно?

<details><summary>Ответ</summary>

Не зафиксирована версия чарта (`targetRevision`), обновление приехало
автоматически; плюс, вероятно, не было проверки на stage.

</details>

**D2.** `helm rollback` не работает для приложения, задеплоенного Argo. Почему?

<details><summary>Ответ</summary>

ArgoCD не создаёт Helm-релиз; откат делается через git (или `argocd app rollback`).

</details>

**D3.** В репозитории обнаружен Secret с реальным паролем. Порядок действий.

<details><summary>Ответ</summary>

Считать секрет скомпрометированным и ротировать; удалить из истории репозитория;
внедрить Sealed Secrets/ESO; добавить сканер секретов в CI.

</details>

**D4.** SealedSecret не расшифровывается в кластере. Причины?

<details><summary>Ответ</summary>

Секрет запечатан для другого namespace/имени, контроллер пересоздан
с новым ключом, версия контроллера несовместима, неверный публичный ключ при
`kubeseal`.

</details>

**D5.** ExternalSecret создан, но Secret пустой. Что проверить?

<details><summary>Ответ</summary>

Доступность и права `SecretStore`/`ClusterSecretStore`, корректность пути
и property в `remoteRef`, аутентификация оператора в Vault, логи ESO, статус
`ExternalSecret`.

</details>

**D6.** Приложение задеплоилось, но конфигурация от dev попала в prod. Как так вышло?

<details><summary>Ответ</summary>

Неверный `valueFiles`/overlay в Application, перепутанные каталоги,
общий values без переопределения, ошибка в шаблоне ApplicationSet.

</details>

**D7.** CRD чарта не применились, ресурсы падают с ошибкой. Что настроить?

<details><summary>Ответ</summary>

Вынести CRD в отдельное приложение или задать им `sync-wave` раньше,
при необходимости `skipCrds` и управление CRD платформенной командой.

</details>

**D8.** Image Updater выкатил в прод неготовую версию. Что изменить в процессе?

<details><summary>Ответ</summary>

Отключить автообновление для прода, обновлять тег коммитом с ревью,
использовать стратегию обновления только для dev и подписанные/проверенные образы.

</details>

**D9.** После восстановления кластера секреты не восстановились. Почему и что делать?

<details><summary>Ответ</summary>

Секретов не было в git (и правильно), но не было и процедуры их восстановления:
нужны ESO с внешним хранилищем или бэкап ключа Sealed Secrets и самих секретов
в защищённом месте.

</details>

**D10.** Разные команды используют разные подходы, никто не может ревьюить чужие MR.
Что предложишь?

<details><summary>Ответ</summary>

Договориться о единых правилах платформы: где Helm, где Kustomize,
где лежат values, как работают с секретами; зафиксировать в README и шаблонах,
проверять в ревью.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как задеплоить Helm-чарт через ArgoCD?

<details><summary>Ответ</summary>

Создать Application с `path` на чарт (или `chart` + Helm-репозиторий) и указать values.

</details>

**2.** Создаёт ли ArgoCD Helm-релизы?

<details><summary>Ответ</summary>

Нет: он рендерит чарт и применяет манифесты, управляя состоянием через Application.

</details>

**3.** Как хранить values для разных окружений?

<details><summary>Ответ</summary>

Отдельными values-файлами по окружениям в конфиг-репозитории (или multi-source).

</details>

**4.** Чем Kustomize отличается от Helm?

<details><summary>Ответ</summary>

Kustomize накладывает патчи без шаблонов, Helm использует шаблоны и параметры;
у Helm — экосистема готовых чартов.

</details>

**5.** Как подменить тег образа?

<details><summary>Ответ</summary>

Через `kustomize.images` или `helm.parameters`/values; обновляет обычно CI.

</details>

**6.** Как хранить секреты при GitOps?

<details><summary>Ответ</summary>

Зашифрованными в git (SOPS, Sealed Secrets) или через внешнее хранилище (ESO + Vault).

</details>

**7.** Как работает Sealed Secrets?

<details><summary>Ответ</summary>

`kubeseal` шифрует секрет публичным ключом контроллера; расшифровать может только
контроллер в кластере.

</details>

**8.** Что такое External Secrets Operator?

<details><summary>Ответ</summary>

Оператор, который создаёт Secret в кластере по данным из внешнего хранилища
и поддерживает их в актуальном состоянии.

</details>

**9.** Как обновляются версии приложений в GitOps?

<details><summary>Ответ</summary>

Коммитом нового тега образа в конфиг-репозиторий (или Image Updater для dev).

</details>

**10.** Почему нельзя использовать тег latest?

<details><summary>Ответ</summary>

Тег не фиксирует версию: нет воспроизводимости, отката и предсказуемости.

</details>

---

### 🎯 Чек-лист

- [ ] Задеплоил публичный и собственный Helm-чарт через ArgoCD
- [ ] ⭐ Понимаю, что Helm-релизов нет и откат идёт через git
- [ ] Фиксирую версии чартов
- [ ] Храню values по окружениям в конфиг-репозитории
- [ ] Пробовал multi-source Application
- [ ] Сделал base + overlays на Kustomize
- [ ] Умею подменять тег образа обоими способами
- [ ] Настроил Sealed Secrets или External Secrets
- [ ] Никогда не кладу base64-секреты в git
- [ ] В CI есть проверка на утечку секретов
