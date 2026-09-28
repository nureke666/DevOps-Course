---
title: "15. Helm — пакетный менеджер Kubernetes"
description: "Чарты, values, шаблоны, релизы, откаты, хуки, зависимости — практика: два окружения одним чартом"
---

# 15. ⭐ Helm — пакетный менеджер Kubernetes

> Роадмап → 6. Kubernetes → Теория → **Helm**: «Helm — пакетный менеджер Kubernetes.
> Как `apt` для Linux, только для кластера. Helm используется почти везде.
> Helm chart'ы, `values`'ы, `template`'ы и всё, что связано с командами хелма».
> Плюс практика: «Обернуть манифесты в chart, вынести в values `replicas`, `image tag`,
> `resource limits`, `ingress host`. Сделать `values-dev.yaml` и `values-prod.yaml`.
> Задеплоить в два namespace через Helm».
> **После темы ты умеешь:** написать свой чарт, параметризовать его и катить приложение
> одной командой в любое окружение.

---

## 🗺️ Карта темы

```text:no-line-numbers
  mychart/
  ├── Chart.yaml          ← метаданные: имя, версия чарта, версия приложения
  ├── values.yaml         ← ЗНАЧЕНИЯ ПО УМОЛЧАНИЮ (что можно настраивать)
  ├── templates/          ← манифесты с подстановками Go-шаблонов
  │   ├── deployment.yaml
  │   ├── service.yaml
  │   ├── ingress.yaml
  │   ├── _helpers.tpl    ← переиспользуемые куски (имена, метки)
  │   └── NOTES.txt       ← что показать после install
  └── charts/             ← зависимости (subcharts)

          values.yaml  +  values-prod.yaml  +  --set
                      ↓  (склеиваются, правый побеждает)
                 templates  →  РЕНДЕРИНГ  →  готовые манифесты  →  kubectl apply
                                                      ↓
                                                RELEASE (релиз с историей и версиями)
```

---

## 1. Зачем нужен Helm

| Проблема с голыми манифестами | Что даёт Helm |
|-------------------------------|---------------|
| Копипаста YAML для dev/stage/prod | Один чарт + разные `values` |
| Десятки файлов на приложение | Одна команда `helm upgrade --install` |
| Нет версий и отката целиком | Релизы с историей и `helm rollback` |
| Сложно ставить чужое ПО | `helm install prometheus prometheus-community/...` |
| Нет условной логики | `if`, `range`, функции в шаблонах |
| Нет связи объектов | Зависимости чартов, хуки, checksum-аннотации |

> Helm 3 не требует серверной части (Tiller из Helm 2 удалён): это обычный CLI,
> который общается с API-сервером под твоими правами, а состояние релиза хранит
> в Secret'ах в том же namespace.

---

## 2. Первые команды

```bash
# podinfo — маленькое демо-приложение, у чарта есть и Helm-репозиторий, и OCI
helm repo add podinfo https://stefanprodan.github.io/podinfo
helm repo update
helm search repo podinfo
helm show values podinfo/podinfo | head -50     # ⭐ что вообще можно настроить

helm install web podinfo/podinfo -n demo --create-namespace
helm list -A
helm status web -n demo
helm upgrade web podinfo/podinfo --set replicaCount=3 -n demo
helm history web -n demo
helm rollback web 1 -n demo
helm uninstall web -n demo

# тот же чарт из OCI-реестра — без helm repo add
helm install web oci://ghcr.io/stefanprodan/charts/podinfo -n demo --create-namespace
```

> ⚠️ В старых гайдах первой строкой идёт `helm repo add bitnami ...`. С августа–сентября 2025
> Bitnami (Broadcom) свернула бесплатный каталог: образы переехали в `bitnamilegacy`
> без обновлений, актуальные — только в платных Bitnami Secure Images. Поэтому
> bitnami-чарты больше не безопасный дефолт — берём чарты от авторов ПО
> (`prometheus-community`, `grafana`, CloudNativePG, `podinfo`), в том числе из `oci://`.

**Главная команда в CI:**
```bash
helm upgrade --install web ./chart \
  -n prod \
  -f values-prod.yaml \
  --set image.tag=$CI_COMMIT_SHORT_SHA \
  --atomic --timeout 5m
```

| Флаг | Зачем |
|------|-------|
| `--install` | установить, если релиза ещё нет — делает команду идемпотентной |
| `-f file` | файл значений (можно несколько, правый побеждает) |
| `--set k=v` | точечное переопределение (высший приоритет) |
| `--atomic` | ⭐ при неудаче автоматически откатить релиз |
| `--timeout` | сколько ждать готовности |
| `--wait` | дождаться готовности ресурсов (включён в `--atomic`) |
| `--dry-run` | не применять, только показать |
| `--create-namespace` | создать namespace, если нет |

---

## 3. Свой чарт

```bash
helm create mychart      # каркас с примерами
tree mychart
```

### Chart.yaml
```yaml
apiVersion: v2
name: mychart
description: Моё приложение
type: application
version: 0.1.0          # ⭐ версия ЧАРТА (меняется при правке шаблонов)
appVersion: "1.5.0"     # ⭐ версия ПРИЛОЖЕНИЯ (тег образа)
dependencies:
  - name: cluster                  # чарт CloudNativePG: Postgres-кластер (подробно — раздел 9)
    alias: postgresql
    version: "0.8.x"
    repository: https://cloudnative-pg.github.io/charts
    condition: postgresql.enabled
```

### values.yaml — то, что требует практика роадмапа
```yaml
replicaCount: 2

image:
  repository: registry.example.com/myapp
  tag: "1.5.0"
  pullPolicy: IfNotPresent

resources:
  requests: { cpu: 100m, memory: 128Mi }
  limits:   { cpu: 500m, memory: 256Mi }

ingress:
  enabled: true
  className: nginx
  host: app.example.com
  tls:
    enabled: false
    secretName: ""

env:
  LOG_LEVEL: info

config:
  featureNewUI: "false"
```

### templates/deployment.yaml
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "mychart.fullname" . }}
  labels:
    {{- include "mychart.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      {{- include "mychart.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      annotations:
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
      labels:
        {{- include "mychart.selectorLabels" . | nindent 8 }}
    spec:
      containers:
        - name: {{ .Chart.Name }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - containerPort: 8080
          env:
            {{- range $k, $v := .Values.env }}
            - name: {{ $k }}
              value: {{ $v | quote }}
            {{- end }}
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
```

### templates/ingress.yaml — условный блок
```yaml
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "mychart.fullname" . }}
spec:
  ingressClassName: {{ .Values.ingress.className }}
  {{- if .Values.ingress.tls.enabled }}
  tls:
    - hosts: [{{ .Values.ingress.host | quote }}]
      secretName: {{ .Values.ingress.tls.secretName }}
  {{- end }}
  rules:
    - host: {{ .Values.ingress.host | quote }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ include "mychart.fullname" . }}
                port:
                  number: 80
{{- end }}
```

---

## 4. Синтаксис шаблонов — необходимый минимум

| Конструкция | Что делает |
|-------------|------------|
| <code v-pre>{{ .Values.x }}</code> | значение из values |
| <code v-pre>{{ .Release.Name }}</code> | имя релиза |
| <code v-pre>{{ .Release.Namespace }}</code> | namespace |
| <code v-pre>{{ .Chart.Name }}</code> / <code v-pre>{{ .Chart.Version }}</code> | из Chart.yaml |
| <code v-pre>{{ .Values.x \| default "y" }}</code> | значение по умолчанию |
| <code v-pre>{{ .Values.x \| quote }}</code> | обернуть в кавычки |
| <code v-pre>{{ toYaml .Values.resources \| nindent 12 }}</code> | вставить блок YAML с отступом |
| <code v-pre>{{- if .Values.enabled }} … {{- end }}</code> | условие |
| <code v-pre>{{- range $k, $v := .Values.env }} … {{- end }}</code> | цикл |
| <code v-pre>{{ include "chart.fullname" . }}</code> | вызов хелпера |
| <code v-pre>{{ required "нужен image.tag" .Values.image.tag }}</code> | обязательное значение |
| <code v-pre>{{- }}</code> / <code v-pre>{{ -}}</code> | убрать пробелы/перенос слева/справа |

**`_helpers.tpl`:**
```text:no-line-numbers
{{- define "mychart.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "mychart.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
```

> ⚠️ Отступы в YAML — главная боль шаблонов. Правило: `nindent N` вместо `indent N`
> там, где нужен перенос строки, и всегда проверяй результат через `helm template`.

---

## 5. Приоритет значений ⭐

```text:no-line-numbers
values.yaml чарта  <  values родительского чарта  <  -f my-values.yaml
   <  -f second.yaml (следующий -f)  <  --set  <  --set-string / --set-file
```
Побеждает то, что правее. Проверить итог:
```bash
helm get values web -n prod            # что задано пользователем
helm get values web -n prod --all      # ВСЕ значения, включая умолчания
```

---

## 6. Отладка чартов ⭐

```bash
helm lint ./mychart                                  # синтаксис и типичные ошибки
helm template myrel ./mychart -f values-prod.yaml    # ⭐ отрендерить локально, без кластера
helm template myrel ./mychart --debug                # показать ошибки шаблонов
helm install myrel ./mychart --dry-run --debug       # рендер + валидация на сервере
helm diff upgrade myrel ./mychart -f values.yaml     # плагин helm-diff: что изменится
helm get manifest myrel -n prod                      # что реально применено
```

`helm template` — самый частый инструмент: он отвечает на вопрос «что вообще
получится из моего чарта», не трогая кластер.

---

## 7. Релизы, история и откат

```bash
helm list -n prod
helm history web -n prod
# REVISION  UPDATED   STATUS      CHART        APP VERSION  DESCRIPTION
# 1         ...       superseded  mychart-0.1  1.4.0        Install complete
# 2         ...       deployed    mychart-0.2  1.5.0        Upgrade complete

helm rollback web 1 -n prod
helm uninstall web -n prod --keep-history
```

Где хранится состояние: в Secret'ах типа `helm.sh/release.v1` в namespace релиза.
```bash
kubectl -n prod get secret -l owner=helm
```

| Статус релиза | Значение |
|---------------|----------|
| `deployed` | текущий рабочий |
| `superseded` | заменён более новой ревизией |
| `failed` | установка/обновление не удались |
| `pending-upgrade` | ⚠️ зависшее обновление (часто из-за прерванного CI) |

---

## 8. Хуки — миграции и подготовка

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "mychart.fullname" . }}-migrate
  annotations:
    "helm.sh/hook": pre-upgrade,pre-install
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          command: ["./migrate.sh"]
```

| Хук | Когда выполняется |
|-----|-------------------|
| `pre-install` / `post-install` | до/после первой установки |
| `pre-upgrade` / `post-upgrade` | до/после обновления |
| `pre-delete` / `post-delete` | до/после удаления |
| `test` | по команде `helm test` |

Это решение задачи «миграции до деплоя» из темы 07, встроенное в Helm.

---

## 9. Зависимости (subcharts)

```yaml
# Chart.yaml
dependencies:
  - name: cluster                       # чарт CloudNativePG: создаёт ресурс Cluster (Postgres)
    alias: postgresql                   # ⭐ в values обращаемся под этим именем
    version: "0.8.x"
    repository: https://cloudnative-pg.github.io/charts
    condition: postgresql.enabled       # в prod выключаем — там managed-база
```
```bash
helm dependency update ./mychart     # скачает в charts/ и создаст Chart.lock
```
```yaml
# values.yaml — значения для subchart'а под его именем (alias)
postgresql:
  enabled: true
  cluster:
    instances: 1
    storage:
      size: 10Gi
    initdb:
      database: myapp
```

> 💡 Чарт `cluster` только описывает базу (CR `Cluster`), а поднимает и обслуживает её
> оператор CloudNativePG. Для Postgres в Kubernetes это и есть нормальная схема —
> оператор + CR, а не StatefulSet «из коробки чарта». Оператор ставят в кластер один раз,
> отдельно от приложения:

```bash
helm repo add cnpg https://cloudnative-pg.github.io/charts
helm upgrade --install cnpg cnpg/cloudnative-pg -n cnpg-system --create-namespace
```

---

## 10. 🔑 Практика роадмапа: два окружения

```yaml
# values-dev.yaml
replicaCount: 1
image: { tag: "dev-latest" }
resources:
  requests: { cpu: 50m, memory: 64Mi }
  limits:   { cpu: 200m, memory: 128Mi }
ingress:
  host: app.dev.local
env: { LOG_LEVEL: debug }
```
```yaml
# values-prod.yaml
replicaCount: 4
image: { tag: "1.5.0" }
resources:
  requests: { cpu: 200m, memory: 256Mi }
  limits:   { cpu: "1",  memory: 512Mi }
ingress:
  host: app.example.com
  tls: { enabled: true, secretName: app-tls }
env: { LOG_LEVEL: info }
```
```bash
helm upgrade --install app ./mychart -n dev  -f values-dev.yaml  --create-namespace
helm upgrade --install app ./mychart -n prod -f values-prod.yaml --create-namespace
helm list -A
```

Одно приложение, один чарт, два окружения, отличающиеся только значениями —
ровно то, ради чего Helm и существует.

---

## 11. Helm vs Kustomize

| | Helm | Kustomize |
|---|---|---|
| Подход | Шаблоны + значения | Патчи поверх базовых манифестов |
| Установка стороннего ПО | ⭐ Огромная экосистема чартов | Нужны готовые манифесты |
| Читаемость | Шаблоны могут быть громоздкими | Обычный YAML |
| Версии и откат | Релизы, история, rollback | Нет своего понятия релиза |
| Встроен в kubectl | Нет | Да (`kubectl apply -k`) |

На практике часто используют оба: чужое ПО ставят Helm'ом, свои манифесты
описывают Kustomize'ом — либо всё Helm'ом ради единообразия.

---

## 💼 Как это в DevOps

- Деплой из пайплайна — это почти всегда одна строка `helm upgrade --install`
  с тегом образа из переменной CI и `--atomic`.
- В репозитории приложения лежит `chart/` рядом с кодом; значения окружений —
  либо там же, либо в отдельном репозитории конфигураций (GitOps, тема 21).
- Секреты в `values` не кладут: только ссылки на Secret, созданный ESO/SOPS.
- `helm template` в CI на каждом MR — дешёвая проверка, что чарт вообще рендерится;
  плюс `helm lint` и `kubeconform` для валидации схем.
- Знать чужой чарт (`helm show values`) важнее, чем писать свой: половина работы —
  правильно настроить готовый чарт Prometheus, ingress-nginx или PostgreSQL.

---

## 📌 Шпаргалка

| Хочу | Команда |
|------|---------|
| Добавить репозиторий | `helm repo add NAME URL && helm repo update` |
| Посмотреть настройки чужого чарта | `helm show values repo/chart` |
| Установить/обновить | `helm upgrade --install REL ./chart -n NS -f values.yaml` |
| Откатить при ошибке автоматически | `--atomic --timeout 5m` |
| Посмотреть, что получится | `helm template REL ./chart -f values.yaml` |
| Проверить чарт | `helm lint ./chart` |
| Список релизов | `helm list -A` |
| История | `helm history REL -n NS` |
| Откат | `helm rollback REL N -n NS` |
| Что применено сейчас | `helm get manifest REL -n NS` |
| Какие значения активны | `helm get values REL -n NS --all` |
| Удалить | `helm uninstall REL -n NS` |
| Обновить зависимости | `helm dependency update ./chart` |
| Создать каркас | `helm create mychart` |

---

## 🧠 Что запомнить

1. Helm — пакетный менеджер: **чарт** (шаблоны + значения) → **релиз** в кластере.
2. Структура чарта: `Chart.yaml`, `values.yaml`, `templates/`, `charts/`, `_helpers.tpl`.
3. `version` — версия чарта, `appVersion` — версия приложения. Это разные вещи.
4. Приоритет значений: `values.yaml` → `-f` (по порядку) → `--set`.
5. ⭐ `helm upgrade --install` + `--atomic` — стандартная команда деплоя в CI.
6. `helm template` отвечает на вопрос «что получится» без обращения к кластеру.
7. Состояние релиза хранится в Secret'ах namespace, а не на сервере (Tiller'а нет).
8. `helm rollback` откатывает **весь релиз** целиком, включая ConfigMap и Service.
9. Хуки (`pre-upgrade`) — штатное место для миграций БД.
10. checksum-аннотация на ConfigMap перезапускает поды при изменении конфигурации.
11. Секреты в `values.yaml` не хранят — только ссылки на внешние Secret'ы.
12. 🔑 Практика роадмапа: свой чарт + `values-dev.yaml`/`values-prod.yaml` + деплой
    в два namespace.

---

## Задачи

> 🔑 Блок C — **главная практика роадмапа**: обернуть свои манифесты в chart,
> вынести в values `replicas`, `image tag`, `resource limits`, `ingress host`,
> сделать `values-dev.yaml` и `values-prod.yaml` и задеплоить в два namespace.

---

### Блок A. Теория

**A1.** Что такое Helm и какую задачу он решает?

<details><summary>Ответ</summary>

Пакетный менеджер Kubernetes: упаковывает набор манифестов в параметризуемый
чарт, устанавливает его как релиз, ведёт историю версий и умеет откатывать.

</details>

**A2.** ⭐ Что такое chart, release и values?

<details><summary>Ответ</summary>

Chart — пакет с шаблонами и значениями по умолчанию; release — установленный
в кластер экземпляр чарта с именем и историей; values — значения, подставляемые
в шаблоны.

</details>

**A3.** Из каких файлов и каталогов состоит чарт?

<details><summary>Ответ</summary>

`Chart.yaml` (метаданные), `values.yaml` (значения по умолчанию),
`templates/` (шаблоны манифестов, `_helpers.tpl`, `NOTES.txt`),
`charts/` (зависимости), опционально `Chart.lock`, `.helmignore`, `crds/`.

</details>

**A4.** ⭐ Чем `version` отличается от `appVersion` в Chart.yaml?

<details><summary>Ответ</summary>

`version` — версия самого чарта (меняется при изменении шаблонов);
`appVersion` — версия упакованного приложения (обычно совпадает с тегом образа).

</details>

**A5.** Где Helm 3 хранит состояние релиза? Чем это отличается от Helm 2?

<details><summary>Ответ</summary>

В Secret'ах типа `helm.sh/release.v1` в namespace релиза. В Helm 2
состояние хранил серверный компонент Tiller, которого больше нет.

</details>

**A6.** Что делает `helm upgrade --install` и почему так пишут в CI?

<details><summary>Ответ</summary>

Устанавливает релиз, если его нет, и обновляет, если есть. Делает команду
идемпотентной — можно запускать из пайплайна без проверок.

</details>

**A7.** Что делает `--atomic` и почему это важно?

<details><summary>Ответ</summary>

При неуспешном обновлении автоматически откатывает релиз к предыдущей
рабочей ревизии (включает ожидание готовности ресурсов).

</details>

**A8.** ⭐ Каков приоритет значений: `values.yaml`, `-f`, `--set`?

<details><summary>Ответ</summary>

`values.yaml` чарта → значения родительского чарта → файлы `-f`
в порядке указания → `--set` (и его варианты). Побеждает более поздний.

</details>

**A9.** Как посмотреть все действующие значения релиза?

<details><summary>Ответ</summary>

`helm get values RELEASE -n NS --all`.

</details>

**A10.** ⭐ Что делает `helm template` и чем отличается от `--dry-run`?

<details><summary>Ответ</summary>

`helm template` рендерит шаблоны локально, не обращаясь к кластеру;
`--dry-run` отправляет результат на сервер, где он проходит валидацию и admission,
но не применяется.

</details>

**A11.** Зачем нужен `helm lint`?

<details><summary>Ответ</summary>

Проверяет структуру чарта и типичные ошибки: отсутствующие поля,
некорректный YAML, проблемы в значениях.

</details>

**A12.** Как посмотреть, какие настройки поддерживает чужой чарт?

<details><summary>Ответ</summary>

`helm show values repo/chart` (а также `helm show readme`, `helm show chart`).

</details>

**A13.** Что делает `helm rollback` и что именно откатывается?

<details><summary>Ответ</summary>

Возвращает релиз к указанной ревизии целиком: все объекты, входящие
в чарт, приводятся к состоянию той ревизии.

</details>

**A14.** Какие статусы релиза бывают и что означает `pending-upgrade`?

<details><summary>Ответ</summary>

`deployed`, `superseded`, `failed`, `pending-install`, `pending-upgrade`,
`uninstalling`. `pending-upgrade` означает прерванное обновление — чаще всего
пайплайн убили по таймауту.

</details>

**A15.** Что такое `_helpers.tpl` и зачем он нужен?

<details><summary>Ответ</summary>

Файл с определениями шаблонов (`define`), которые переиспользуются:
формирование имён, наборы меток, вспомогательная логика.

</details>

**A16.** Что делает `toYaml ... | nindent N`?

<details><summary>Ответ</summary>

Превращает структуру из values в YAML и вставляет с переносом строки
и отступом N пробелов.

</details>

**A17.** Чем `indent` отличается от `nindent`?

<details><summary>Ответ</summary>

`indent` добавляет отступ, но не переносит строку; `nindent` сначала
делает перенос, затем отступ. При вставке блока после ключа нужен `nindent`.

</details>

**A18.** Что делают <code v-pre>{{-</code> и <code v-pre>-}}</code>?

<details><summary>Ответ</summary>

Убирают пробельные символы и перенос строки слева (<code v-pre>{{-</code>) или справа
(<code v-pre>-}}</code>) от выражения — иначе в YAML появляются лишние пустые строки и отступы.

</details>

**A19.** Как сделать обязательное значение, без которого рендер упадёт?

<details><summary>Ответ</summary>

Функцией `required "сообщение" .Values.x` — рендер завершится ошибкой
с этим сообщением.

</details>

**A20.** Что такое хуки Helm и какие бывают?

<details><summary>Ответ</summary>

Объекты, выполняемые на определённых этапах жизненного цикла релиза:
`pre-install`, `post-install`, `pre-upgrade`, `post-upgrade`, `pre-delete`,
`post-delete`, `test`. Управляются аннотациями `helm.sh/hook*`.

</details>

**A21.** Как выполнить миграции БД до обновления приложения средствами Helm?

<details><summary>Ответ</summary>

Job с аннотацией `helm.sh/hook: pre-upgrade` (и `pre-install`),
с политикой удаления `before-hook-creation,hook-succeeded`.

</details>

**A22.** Что такое subchart и как подключить зависимость?

<details><summary>Ответ</summary>

Чарт-зависимость, объявленная в `Chart.yaml`; скачивается
`helm dependency update` в каталог `charts/`.

</details>

**A23.** Как передать значения в subchart?

<details><summary>Ответ</summary>

В `values.yaml` родителя — блоком, названным по имени subchart'а
(например, `postgresql: { ... }`); глобальные значения — через `global`.

</details>

**A24.** ⭐ Как одним чартом задеплоить в dev и prod с разными настройками?

<details><summary>Ответ</summary>

Один чарт и разные файлы значений: `helm upgrade --install app ./chart
-n dev -f values-dev.yaml` и то же самое с `-n prod -f values-prod.yaml`.

</details>

**A25.** Почему секреты не хранят в `values.yaml` и что делать вместо этого?

<details><summary>Ответ</summary>

Файлы значений лежат в git и видны всем, у кого есть доступ к репозиторию.
Правильно: создавать Secret отдельно (SOPS, Sealed Secrets, External Secrets)
и ссылаться на него из чарта.

</details>

**A26.** Чем Helm отличается от Kustomize?

<details><summary>Ответ</summary>

Helm использует шаблоны и понятие релиза с историей и откатом;
Kustomize накладывает патчи на обычные манифесты и встроен в kubectl,
но не имеет собственных релизов.

</details>

**A27.** Как заставить поды перезапуститься при изменении ConfigMap средствами Helm?

<details><summary>Ответ</summary>

Аннотацией в шаблоне пода с хешем файла ConfigMap
(`sha256sum` от результата рендеринга) — изменение конфига меняет шаблон пода
и вызывает выкатку.

</details>

**A28.** Что произойдёт, если в чарте оставить `replicas`, а приложением управляет HPA?

<details><summary>Ответ</summary>

При каждом `helm upgrade` число реплик будет возвращаться к значению
из values, перетирая решение HPA. Поле `replicas` в таком случае не задают.

</details>

---

### Блок B. «Что произойдёт»

**B1.**
```bash
helm install web ./chart -n prod
helm install web ./chart -n prod
```
Вопрос: что ответит вторая команда? Как надо было?

<details><summary>Ответ</summary>

Ошибку `cannot re-use a name that is still in use`. Нужно было
`helm upgrade --install`.

</details>

**B2.**
```bash
helm upgrade web ./chart -f values-prod.yaml --set replicaCount=5
# в values-prod.yaml: replicaCount: 3
# в values.yaml: replicaCount: 1
```
Вопрос: сколько будет реплик?

<details><summary>Ответ</summary>

Пять: `--set` имеет наивысший приоритет.

</details>

**B3.**
```bash
helm upgrade --install web ./chart --atomic --timeout 2m
# новый образ не стартует
```
Вопрос: что произойдёт через 2 минуты?

<details><summary>Ответ</summary>

Helm дождётся таймаута, признает обновление неудачным и автоматически
откатит релиз к предыдущей ревизии; команда вернёт ненулевой код.

</details>

**B4.**
```yaml
replicas: {{ .Values.replicaCount }}
# в values.yaml нет ключа replicaCount
```
Вопрос: что получится при рендеринге?

<details><summary>Ответ</summary>

Значение отрендерится как пустое (`replicas:`), и манифест, скорее всего,
не пройдёт валидацию. Защита — `default` или `required`.

</details>

**B5.**
```yaml
resources:
  {{ toYaml .Values.resources | indent 12 }}
```
Вопрос: почему здесь, скорее всего, сломается YAML?

<details><summary>Ответ</summary>

`indent` не переносит строку: первый элемент блока окажется на строке
с ключом `resources:` и отступ собьётся. Нужен `nindent`.

</details>

**B6.**
```bash
helm list -n prod
# NAME  REVISION  STATUS           CHART
# web   7         pending-upgrade
```
Вопрос: что произошло и что делать?

<details><summary>Ответ</summary>

Прерванное обновление (обычно убитый пайплайн). Лечение: дождаться
или выполнить `helm rollback` на последнюю рабочую ревизию; в крайнем случае —
удалить «залипший» Secret релиза.

</details>

**B7.**
```bash
helm uninstall web -n prod
kubectl get pvc -n prod
# data-web-0  Bound
```
Вопрос: почему PVC остался?

<details><summary>Ответ</summary>

Helm не удаляет PVC, созданные `volumeClaimTemplates` StatefulSet:
их жизненным циклом управляет контроллер, а не Helm.

</details>

**B8.**
```bash
helm rollback web 3
helm history web
```
Вопрос: какой номер ревизии появится после отката?

<details><summary>Ответ</summary>

Откат создаёт **новую** ревизию (например, 8) с содержимым ревизии 3 —
история не переписывается.

</details>

**B9.**
```yaml
image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
# tag не задан
```
Вопрос: что получится и как защититься?

<details><summary>Ответ</summary>

Получится `repo:` без тега; лучше использовать
`.Values.image.tag | default .Chart.AppVersion` или `required`.

</details>

---

### Блок C. Практика

#### C1. Чужой чарт
1. Добавь репозиторий podinfo (`https://stefanprodan.github.io/podinfo`) или возьми
   OCI-вариант `oci://ghcr.io/stefanprodan/charts/podinfo`.
2. Посмотри `helm show values podinfo/podinfo` и найди, как поменять число реплик
   и ресурсы.
3. Установи с двумя изменёнными параметрами через `--set`.
4. Проверь `helm get values` и `kubectl get deploy`.
5. Удали релиз.

#### C2. 🔑 Свой чарт из манифестов *(практика роадмапа)*
Возьми манифесты из тем 05, 08, 09, 12 (Deployment + Service + ConfigMap + Ingress)
и собери из них чарт:
1. `helm create mychart`, затем удали лишние примеры.
2. Перенеси свои манифесты в `templates/`.
3. Вынеси в `values.yaml`: `replicaCount`, `image.repository`, `image.tag`,
   `resources`, `ingress.enabled`, `ingress.host`.
4. Проверь `helm lint` и `helm template`.
5. Установи в namespace `dev`.

#### C3. 🔑 Два окружения *(практика роадмапа)*
1. Сделай `values-dev.yaml` (1 реплика, малые ресурсы, хост `app.dev.local`).
2. Сделай `values-prod.yaml` (4 реплики, большие ресурсы, TLS, хост `app.local`).
3. Задеплой в namespace `dev` и `prod` одной и той же командой с разными `-f`.
4. Проверь `helm list -A`, `kubectl get deploy -A`, `kubectl get ingress -A`.
5. Зафиксируй: что отличается в результате и почему.

<details><summary>Ответ</summary>

Ожидаемый результат: два релиза одного чарта в разных namespace
с разным числом реплик, ресурсами, хостами Ingress и TLS.

</details>

#### C4. helm template как основной инструмент
Отрендери чарт с обоими файлами значений и сравни:
```bash
helm template app ./mychart -f values-dev.yaml > /tmp/dev.yaml
helm template app ./mychart -f values-prod.yaml > /tmp/prod.yaml
diff /tmp/dev.yaml /tmp/prod.yaml
```
Разбери каждое отличие.

#### C5. Приоритет значений
Проверь на практике цепочку: `values.yaml` → `-f dev` → `-f extra` → `--set`.
Для каждого шага запиши итоговое значение одного и того же ключа.

<details><summary>Ответ</summary>

Итоговое значение всегда берётся из самого «правого» источника:
`--set` перебивает файлы, последний `-f` перебивает предыдущий.

</details>

#### C6. Хелперы
1. Посмотри `_helpers.tpl` в сгенерированном чарте.
2. Добавь свой хелпер (например, полное имя с окружением).
3. Используй его в нескольких шаблонах.
4. Проверь через `helm template`.

#### C7. Условия и циклы
1. Сделай `ingress.enabled: false` и убедись, что Ingress не рендерится.
2. Сделай блок `env` в `values.yaml` и отрендери его циклом `range`.
3. Добавь <code v-pre>{{ required "image.tag обязателен" .Values.image.tag }}</code> и проверь,
   что без тега рендер падает.

#### C8. 🔑 checksum-аннотация
1. Добавь в шаблон пода аннотацию с `sha256sum` от ConfigMap.
2. Задеплой, запиши имена подов.
3. Измени значение конфига в `values` и обнови релиз.
4. Убедись, что поды пересозданы. Сравни с поведением без аннотации.

<details><summary>Ответ</summary>

Без аннотации поды не пересоздаются и продолжают работать со старой
конфигурацией; с аннотацией меняется шаблон пода и запускается выкатка.

</details>

#### C9. Откат
1. Обнови релиз с заведомо битым образом.
2. Посмотри `helm history` и статус.
3. Откатись на предыдущую ревизию.
4. Повтори обновление с `--atomic` и убедись, что откат произошёл сам.

#### C10. Хук миграций
Добавь Job с `helm.sh/hook: pre-upgrade` (может просто печатать «migrating» и спать
10 секунд). Обнови релиз и проследи порядок: сначала Job, потом обновление подов.

#### C11. Зависимости
Добавь в `Chart.yaml` зависимость от чарта `cluster` CloudNativePG
(`repository: https://cloudnative-pg.github.io/charts`, `alias: postgresql`) с `condition`.
Оператор CNPG поставь в кластер заранее (`cnpg/cloudnative-pg`, см. конспект, раздел 9).
1. `helm dependency update`.
2. Включи через `postgresql.enabled: true` в dev и выключи в prod.
3. Проверь, что в prod база не разворачивается.

#### C12. Деплой из пайплайна (связка с блоком CI/CD)
Напиши джобу:
```yaml
deploy:
  script:
    - helm upgrade --install app ./chart -n $ENV -f values-$ENV.yaml
        --set image.tag=$CI_COMMIT_SHORT_SHA --atomic --timeout 5m
```
Добавь предварительные шаги `helm lint` и `helm template`.

#### C13. Отладка сломанного чарта
Намеренно сломай отступы в шаблоне и разбери ошибку через
`helm template --debug`. Запиши, как выглядит типичное сообщение
и как быстро находить строку.

<details><summary>Ответ</summary>

Типичная ошибка — `error converting YAML to JSON: did not find expected key`
с указанием строки отрендеренного результата; искать надо в шаблоне,
сопоставив с выводом `helm template`.

</details>

#### C14. helm-diff (со звёздочкой)
Поставь плагин `helm-diff` и посмотри, что изменится перед обновлением.
Объясни, чем это полезнее `--dry-run`.

#### C15. Аудит чужого чарта (со звёздочкой)
Возьми чарт ingress-nginx, найди в его `values.yaml`, как задать:
число реплик контроллера, ресурсы, `externalTrafficPolicy`, метрики Prometheus.
Это типичная рабочая задача.

---

### Блок D. Инциденты

**D1.** `helm upgrade` завис, релиз в `pending-upgrade`, повторный запуск ругается.
Что делать?

<details><summary>Ответ</summary>

Проверить `helm history`, дождаться завершения операции или откатиться
(`helm rollback` на последнюю `deployed`-ревизию). В запущенных случаях —
удалить Secret зависшей ревизии. Профилактика: `--atomic` и `--timeout`.

</details>

**D2.** После обновления релиза приложение упало, а откат «не помог»:
поды прежние. Возможные причины?

<details><summary>Ответ</summary>

Откат вернул манифесты, но образ с тем же тегом уже изменился;
миграция БД необратима; часть состояния лежит вне чарта (ConfigMap/Secret,
созданные вручную); откатывали не тот релиз или не тот namespace.

</details>

**D3.** В CI деплой «успешен», но приложение не работает. Какого флага не хватало?

<details><summary>Ответ</summary>

`--wait`/`--atomic`: без них Helm считает успехом сам факт применения
манифестов, не дожидаясь готовности подов.

</details>

**D4.** Релиз задеплоен, но ConfigMap не применился к подам. Что забыли в чарте?

<details><summary>Ответ</summary>

checksum-аннотацию на шаблоне пода: без неё изменение ConfigMap
не перезапускает поды.

</details>

**D5.** Разработчик положил пароль БД в `values-prod.yaml` в репозитории.
Что объяснишь и что предложишь?

<details><summary>Ответ</summary>

Значения в git доступны всем, кто имеет доступ к репозиторию,
и попадают в историю. Предложить SOPS/Sealed Secrets/External Secrets
и ссылку на Secret в чарте.

</details>

**D6.** Один и тот же чарт в dev работает, в prod падает на рендеринге.
С чего начать разбор?

<details><summary>Ответ</summary>

Сравнить значения: `helm template` с prod-файлом локально,
`helm get values --all` для рабочего релиза; искать отсутствующие ключи
и различия в структуре.

</details>

**D7.** `helm upgrade` перетёр число реплик, выставленное HPA. Как правильно?

<details><summary>Ответ</summary>

Убрать `replicas` из шаблона (или сделать его условным при выключенном HPA),
оставив управление числом реплик автоскейлеру.

</details>

**D8.** После `helm uninstall` остались PVC и пара объектов. Почему?

<details><summary>Ответ</summary>

Helm не удаляет объекты, созданные не им: PVC от StatefulSet,
ресурсы с аннотацией `helm.sh/resource-policy: keep`, CRD.

</details>

**D9.** Чарт обновили, версия в `Chart.yaml` не изменилась. Чем это грозит
в GitOps-подходе?

<details><summary>Ответ</summary>

В GitOps версия чарта — единица изменения: без её увеличения сложно
отследить, что именно и когда изменилось, и повторно воспроизвести состояние.

</details>

**D10.** `helm template` выдаёт корректный YAML, а `helm install` падает
с ошибкой валидации. Почему такое возможно?

<details><summary>Ответ</summary>

`helm template` не проходит серверную валидацию: неизвестные поля,
отсутствующие CRD, admission-контроллеры (квоты, политики безопасности)
проверяются только на сервере.

</details>

**D11.** Два инженера одновременно катят один релиз. Что произойдёт?

<details><summary>Ответ</summary>

Второй получит ошибку «операция уже выполняется» либо релиз зависнет
в `pending-upgrade`. Деплой должен идти из одного источника — пайплайна.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Что такое Helm и зачем он нужен?

<details><summary>Ответ</summary>

Пакетный менеджер Kubernetes: шаблоны плюс значения, релизы с историей и откатом,
огромная экосистема готовых чартов.

</details>

**2.** Что такое chart, release, values?

<details><summary>Ответ</summary>

Chart — пакет; release — установленный экземпляр; values — значения для шаблонов.

</details>

**3.** Как устроен чарт изнутри?

<details><summary>Ответ</summary>

`Chart.yaml`, `values.yaml`, `templates/` (в том числе `_helpers.tpl`), `charts/`.

</details>

**4.** Чем version отличается от appVersion?

<details><summary>Ответ</summary>

`version` — версия чарта, `appVersion` — версия приложения.

</details>

**5.** Как деплоят через Helm в CI? Какие флаги важны?

<details><summary>Ответ</summary>

`helm upgrade --install` с `-f` для окружения, `--set image.tag=$SHA`,
`--atomic` и `--timeout`.

</details>

**6.** Как откатить релиз?

<details><summary>Ответ</summary>

`helm rollback RELEASE N`; откат создаёт новую ревизию.

</details>

**7.** Где Helm 3 хранит состояние?

<details><summary>Ответ</summary>

В Secret'ах namespace релиза; Tiller в Helm 3 отсутствует.

</details>

**8.** Каков приоритет values?

<details><summary>Ответ</summary>

`values.yaml` → `-f` по порядку → `--set`.

</details>

**9.** Как сделать один чарт для нескольких окружений?

<details><summary>Ответ</summary>

Один чарт и разные файлы значений, разные namespace, одна команда деплоя.

</details>

**10.** Как выполнять миграции БД при деплое через Helm?

<details><summary>Ответ</summary>

Job с хуком `pre-upgrade`/`pre-install` и политикой удаления хука.

</details>

**11.** Чем Helm отличается от Kustomize?

<details><summary>Ответ</summary>

Helm — шаблоны и релизы; Kustomize — патчи поверх манифестов, встроен в kubectl.

</details>

**12.** Как безопасно хранить секреты при использовании Helm?

<details><summary>Ответ</summary>

Не хранить в values: создавать Secret через SOPS/Sealed Secrets/External Secrets
и ссылаться на него.

</details>

---

### 🎯 Чек-лист

- [ ] 🔑 Собрал свой чарт из ранее написанных манифестов
- [ ] 🔑 Вынес в values `replicas`, `image.tag`, `resources`, `ingress.host`
- [ ] 🔑 Сделал `values-dev.yaml` и `values-prod.yaml` и задеплоил в два namespace
- [ ] Использую `helm template` до каждого применения
- [ ] Знаю приоритет значений и проверяю через `helm get values --all`
- [ ] Деплою командой `helm upgrade --install ... --atomic`
- [ ] Откатывал релиз и понимаю, что откат создаёт новую ревизию
- [ ] Сделал checksum-аннотацию для ConfigMap
- [ ] Пробовал хук `pre-upgrade` для миграций
- [ ] Знаю, почему секреты не живут в values
