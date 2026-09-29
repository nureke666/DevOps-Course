---
title: "09. Практика: мини-платформа в kind"
description: "Блок → Platform Engineering → практика. Шесть лаб собирают из тем 01–08 одну платформу:"
---

# 09. Практика: мини-платформа в kind

> Блок → Platform Engineering → **практика**. Шесть лаб собирают из тем 01–08 одну платформу:
> команда пишет LinkdApp или жмёт кнопку в портале — и получает сервис с маршрутом, базой,
> ограждениями и canary с автооткатом. Здесь **требования и проверки**, а не готовые решения:
> код и манифесты пишешь сам, опираясь на конспекты. Сервис — linkd 2.0 из проектов
> `07-orbit` (чарт и kind),
> `12-autopilot` (ArgoCD, образ linkd 2.0)
> и `08-observatory` (метрики и дашборды).

---

## 📋 Список лаб

| № | Лаба | Что получишь | Темы |
|---|------|--------------|------|
| 1 | 🔑 Оператор LinkdApp деплоит linkd | Оператор в кластере с RBAC и метриками обслуживает две команды | 02, 03, 05 |
| 2 | 🔑 Guardrails | VAP и Kyverno отклоняют плохие объекты с понятным сообщением, webhook ставит дефолты | 04 |
| 3 | 🔑 Canary с анализом | Rollout linkd, веса в HTTPRoute, анализ по Prometheus, автооткат при 5xx | 05, 06 |
| 4 | База по запросу | `database: true` → LinkdDatabase → CloudNativePG → linkd с PostgreSQL | 03, 07 |
| 5 | Портал → git → ArgoCD | Шаблон Backstage создаёт репозиторий и Application, сервис в каталоге | 08 + ArgoCD |
| 6 | 🔑 Итоговый golden path | Путь «от кнопки до URL» целиком, README платформы, замер time to first deploy | 01–08 |

**Что нужно до начала:**
- 16 ГБ RAM на машине (кластер ~8 ГБ); Docker, kind, kubectl, Helm 4 (Helm 3 — до 10.02.2027),
  Python 3.12+, Node 22/24 для Backstage;
- образ `linkd:2.0.0`: Dockerfile из 04-shipyard + `app/` из 12-autopilot, `kind load` в кластер;
- всё, что пишешь, — в git-репозитории `platform-lab` (каталоги `operator/`, `policies/`,
  `delivery/`, `crossplane/`, `portal/`, `docs/`), каждая лаба — отдельный MR/PR с описанием.

### 🧰 Общий стенд

```bash
kind create cluster --name platform --image kindest/node:v1.36.4   # EG 1.9 и KEDA 2.21 — до 1.36
helm install eg oci://docker.io/envoyproxy/gateway-helm --version v1.9.1 \
  -n envoy-gateway-system --create-namespace                       # ставит Gateway API v1.6.1
```text
| Компонент | Когда ставить | Откуда |
|-----------|---------------|--------|
| Envoy Gateway + Gateway `web` в `infra` | Лаба 1 | [../Kubernetes/12_ingress.md](/kubernetes/12-ingress) §7, [05_gateway_mesh.md](/platform/05-gateway-mesh) §2 |
| kube-prometheus-stack (релиз `prometheus`, ns `monitoring`) | Лаба 1 (метрики оператора), обязательно к лабе 3 | [../Left/02_Monitoring/11_long_term_and_operator.md](/monitoring/11-long-term-and-operator) §7 |
| Kyverno | Лаба 2 | [04_admission_policy.md](/platform/04-admission-policy) |
| Argo Rollouts v1.10 + плагин Gateway API v0.17 | Лаба 3 | [06_progressive_delivery.md](/platform/06-progressive-delivery) |
| CloudNativePG 1.30 + Crossplane v2.4 | Лаба 4 | [07_crossplane_self_service.md](/platform/07-crossplane-self-service) |
| ArgoCD | Лаба 5 | [../Left/07_ArgoCD/02_argocd_install.md](/argocd/02-argocd-install) |
| Backstage | Лаба 5 (локально, не в кластере) | [08_backstage.md](/platform/08-backstage) |

> 💡 Mesh из темы 05 в лабах не обязателен: Istio ambient снимай после мини-лабы темы
> (`istioctl uninstall --purge -y`), он съедает память, нужную Crossplane и Backstage.

---

## 🧪 Лаба 1. Оператор LinkdApp деплоит linkd 🔑

### Цель
Оператор из [03_writing_operator.md](/platform/03-writing-operator) работает **в кластере** (не `kopf run`
с ноутбука), обслуживает две команды на общем Gateway и сам сообщает о своём здоровье.

### Стенд
Общий стенд + CRD LinkdApp из [02_crd_operators.md](/platform/02-crd-operators) + kube-prometheus-stack.

### Требования
1. **Gateway для двух команд.** В `infra` — Gateway `web` с listeners на `*.team-a.example.com`
   и `*.team-b.example.com`, `allowedRoutes` по метке namespace, которую ставишь ты как платформа
   ([05_gateway_mesh.md](/platform/05-gateway-mesh) §2). Namespace `team-a`, `team-b` создаются из git,
   а не руками.
2. **Оператор в кластере.** Образ `linkd-operator:0.1.0`, Deployment в namespace `platform` (как в теме 03),
   ServiceAccount и ClusterRole по принципу минимальных прав: CRUD на Deployment/Service/HTTPRoute,
   `patch` статуса LinkdApp, **без** `get secrets`. Одна реплика или несколько с peering — объясни выбор.
3. **Две команды.** В каждом namespace — LinkdApp `shortener` (у команд одинаковое имя!) со своим
   `host`. Обе работают через Gateway.
4. **Метрики оператора.** `/metrics` оператора (prometheus-client) собирает Prometheus через
   ServiceMonitor; в Grafana — панель: число LinkdApp по состоянию `Ready`, длительность reconcile,
   ошибки.
5. **Документация API.** `docs/linkdapp.md`: поля, дефолты, пример, что делает оператор,
   какие условия бывают в `status` и что с ними делать.

### Проверки
```bash
kubectl auth can-i get secrets --as=system:serviceaccount:platform:linkd-operator -A   # no
kubectl get la -A                                   # обе READY True, URL в status
curl -H "Host: links.team-a.example.com" localhost:8888/healthz     # port-forward к Envoy
curl -H "Host: links.team-b.example.com" localhost:8888/healthz
kubectl -n team-a delete deploy shortener && sleep 40 && kubectl -n team-a get deploy shortener
```text
### Критерии приёмки
- [ ] Оператор запущен в кластере, `kubectl auth can-i` подтверждает минимальные права
- [ ] Две команды с одинаковым именем LinkdApp не мешают друг другу
- [ ] Удалённый или изменённый руками Deployment возвращается за ≤ 30–60 с
- [ ] У LinkdApp честный `status`: `Ready`, `observedGeneration`, понятный `message` при ошибке
- [ ] Панель метрик оператора в Grafana, алерт «оператор не reconcile'ит N минут»
- [ ] `docs/linkdapp.md` понятен человеку, который не читал код оператора

### Сломай сам
- Команда `team-b` указывает `host: links.team-a.example.com` — что говорит статус маршрута
  и чем это закончилось бы на `from: All`?
- Убери у оператора право на `httproutes` — что видно в `status` LinkdApp и в логах?
- Останови оператор (`scale --replicas=0`) и удали LinkdApp: объект висит с finalizer. Что ещё
  перестало работать? Почему это аргумент за алерт на оператор?

**Уборка:** `kubectl delete la --all -A`, затем `kubectl delete -f operator/deploy/`.

---

## 🧪 Лаба 2. Guardrails: ограждения, а не шлагбаумы 🔑

### Цель
Плохой объект не попадает в кластер, а человек сразу понимает, **почему и как правильно**;
безопасные дефолты проставляются сами; падение webhook не кладёт кластер.

### Стенд
Стенд лабы 1 + Kyverno + свой mutating webhook на Python (FastAPI) из [04_admission_policy.md](/platform/04-admission-policy).

### Требования
1. **VAP на LinkdApp** (CEL): образ с явным тегом и не `:latest`; `replicas` ≤ 3 в namespace
   с меткой `env=dev`; `host` оканчивается на домен команды из метки namespace
   (`platform.example.com/domain`). Каждое правило — своё `message` со ссылкой на `docs/linkdapp.md`.
2. **Kyverno на Deployment/Pod** в namespace команд: `requests` и `limits`, `runAsNonRoot`, запрет
   `:latest`. Сначала **Audit** — посмотри отчёты, потом **Enforce**.
3. **Mutating webhook на Python:** расширь webhook из темы 04 — пусть проставляет метки
   `platform.example.com/team` (из метки namespace) и `app.kubernetes.io/managed-by`, если их нет.
   Чтобы читать namespace, webhook-у нужен ServiceAccount с правом `get namespaces`; в теме 04
   ту же метку ставит MutatingAdmissionPolicy без кода — сравни оба подхода. Требования к надёжности: `failurePolicy: Ignore`,
   `timeoutSeconds` ≤ 3, `namespaceSelector` исключает `kube-system` и namespace самого webhook,
   ≥ 2 реплики, PDB, TLS (cert-manager или self-signed CA в `caBundle`).
4. **Исключения** — осознанные: PolicyException Kyverno для одного системного namespace
   с комментарием «почему и до какого числа».
5. **Документация:** `docs/policies.md` — таблица «правило → зачем → как исправить → кто владелец».

### Проверки
```bash
kubectl apply --dry-run=server -f bad/latest-image.yaml      # отказ: текст объясняет, как исправить
kubectl apply --dry-run=server -f bad/foreign-host.yaml      # отказ от VAP
kubectl get policyreport -A                                  # что нашёл Audit до Enforce
kubectl -n team-a get deploy shortener -o jsonpath='{.metadata.labels}'   # метки от webhook
```text
### Критерии приёмки
- [ ] Каждый отказ содержит причину и способ исправления, а не только «denied»
- [ ] Audit → Enforce сделан осознанно: есть список нарушений до включения
- [ ] Оператор из лабы 1 продолжает работать: его объекты проходят все политики
- [ ] Webhook выключен (0 реплик) — кластер работает, объекты создаются без меток
- [ ] `docs/policies.md` заполнен

### Сломай сам
- Поставь webhook `failurePolicy: Fail` без `namespaceSelector` и удали его поды. Что перестало
  работать (создание подов, в том числе самого webhook)? Как выбраться? Запиши runbook.
- Напиши политику, которая случайно блокирует Deployment оператора. Как это видно в `status` LinkdApp?
- Сделай CEL-выражение, которое падает с ошибкой на объекте без поля. Чем `failurePolicy`
  у VAP отличается от webhook?

**Уборка:** политики и webhook остаются — они нужны в лабах 3–6.

---

## 🧪 Лаба 3. Canary с анализом по Prometheus 🔑

### Цель
Новая версия linkd получает сначала 20% трафика, Argo Rollouts проверяет её по метрикам
и **сам** откатывает при росте 5xx или латентности.

### Стенд
Стенд лаб 1–2 + kube-prometheus-stack + Argo Rollouts v1.10 и плагин Gateway API v0.17
([06_progressive_delivery.md](/platform/06-progressive-delivery) §2, §4).

### Требования
1. **Базовый путь:** linkd как Rollout в `team-a` (руками, как в мини-лабе темы 06): Services
   stable/canary, HTTPRoute с двумя `backendRefs`, ServiceMonitor с `podTargetLabels`,
   фоновый анализ доли не-5xx (порог из SLO) и inline-анализ p95 перед 100%.
2. **Путь платформы (со звёздочкой):** поле `delivery: canary` в LinkdApp — оператор создаёт
   Rollout вместо Deployment и `ClusterAnalysisTemplate` с порогами по умолчанию. Команда
   может переопределить только порог, а не запрос.
3. **Нагрузка** — постоянный генератор ~20 RPS через Gateway (Deployment `load` в `team-a`).
4. **Уведомление** о провале анализа (Argo Rollouts notifications или алерт Prometheus
   на `Degraded`) в любой канал: webhook, Telegram, файл в логах.
5. **Отчёт** `delivery/REPORT.md`: время от выкатки до abort, доля ошибок, которую видели
   клиенты, из чего сложилось время (initialDelay, interval, окно rate, failureLimit), что поменяешь.

### Проверки
```bash
kubectl argo rollouts get rollout shortener -n team-a -w
# хороший релиз: LINKD_LOG_FORMAT=json → доходит до 100%
# плохой релиз: LINKD_FAULT_ERROR_RATE=0.3 → AnalysisRun Failed → веса 100/0
# медленный релиз: LINKD_FAULT_LATENCY_MS=400 → проходит success-rate, падает на p95
kubectl get httproute -n team-a -o jsonpath='{.items[0].spec.rules[0].backendRefs[*].weight}{"\n"}'
```text
### Критерии приёмки
- [ ] Видел все три исхода: успешная выкатка, abort по ошибкам, abort по латентности
- [ ] Анализ меряет **только** canary-поды (доказано запросом в Prometheus)
- [ ] Время до автоотката ≤ 2 минут, и ты можешь объяснить, из чего оно складывается
- [ ] Уведомление о провале пришло
- [ ] Политики лабы 2 не мешают Rollout (или ты осознанно их поправил)

### Сломай сам
- Останови генератор нагрузки и выкати плохой релиз. Что сделал анализ и почему это правильно?
- Убери `podTargetLabels` — заметит ли анализ 30% ошибок на 20% трафика?
- Выкати релиз с миграцией, несовместимой со старой версией (эмуляция: v2 переименовывает
  таблицу в своей SQLite — подумай, почему с общей PostgreSQL это сломало бы stable).

**Уборка:** оставь Rollout — он пригодится в лабе 6; удали генератор нагрузки.

---

## 🧪 Лаба 4. База по запросу

### Цель
Команда пишет `database: true` в LinkdApp — и через пару минут linkd работает на своей PostgreSQL,
без тикета и без доступа команды к CNPG напрямую.

### Стенд
Стенд лаб 1–3 + CloudNativePG 1.30 + Crossplane v2.4 + функции patch-and-transform и python
([07_crossplane_self_service.md](/platform/07-crossplane-self-service) §5).

### Требования
1. **API:** XRD `LinkdDatabase` (namespaced) с `size`, `storageGB` (1–20), `version`, `backup`
   и дефолтами; композиция на CNPG с контрактом **Secret `&lt;имя&gt;-db`, ключ `url`**.
2. **Связка с оператором:** при `database: true` оператор создаёт `LinkdDatabase` с тем же именем
   (ownerReference на LinkdApp) и ждёт `Ready` — пока базы нет, у LinkdApp `Ready=False`
   с понятным `message`. Дай оператору права на `linkddatabases`, но не на секреты.
3. **Ограждения:** RBAC — команда может создавать `linkddatabases`, но **не** `clusters.postgresql.cnpg.io`;
   ResourceQuota (не больше 2 баз и 20 Gi на namespace); `size: medium` — только при `env=prod`
   (VAP из лабы 2).
4. **Данные переживают рестарт:** ссылка, созданная до `kubectl rollout restart`, открывается после.
5. **Решение про удаление:** что должно происходить с базой при удалении LinkdApp? Запиши решение
   в `docs/adr/0001-database-lifecycle.md` (варианты: каскад по ownerReference, отдельный объект
   без ownerReference, бэкап перед удалением) и реализуй выбранное.

### Проверки
```bash
kubectl -n team-a patch la shortener --type=merge -p '{"spec":{"database":true&#125;&#125;'
kubectl -n team-a get la,linkddatabase,clusters.postgresql.cnpg.io,secret -w
crossplane resource trace linkddatabase shortener -n team-a
kubectl -n team-a exec deploy/shortener -- python -c "import os; print(os.environ['LINKD_DATABASE_URL'].split('@')[1])"
kubectl auth can-i create clusters.postgresql.cnpg.io -n team-a --as=&lt;пользователь команды&gt;   # no
```text
### Критерии приёмки
- [ ] От `database: true` до `/readyz` 200 — меньше 3 минут без ручных действий
- [ ] `linkd_db_up 1`, данные переживают рестарт подов
- [ ] Пароль в Secret не меняется между reconcile (проверено за 10 минут)
- [ ] Команда не может создать CNPG Cluster напрямую и не может превысить квоту
- [ ] ADR про жизненный цикл базы написан и реализован

### Сломай сам
- Удали ClusterRole `aggregate-to-crossplane` — что в условиях XR?
- Сделай функцию неидемпотентной (новый пароль каждый раз) и посмотри на linkd через 5 минут.
- Удали LinkdApp при каскадном удалении. Что стало с данными? Как защитился бы в проде
  (бэкап CNPG в MinIO, `Prune=false`, отсутствие ownerReference)?

**Уборка:** базы удали через свою процедуру из ADR, CNPG и Crossplane можно оставить.

---

## 🧪 Лаба 5. Шаблон Backstage → репозиторий → ArgoCD → сервис в каталоге

### Цель
Разработчик заполняет форму в портале — и через несколько минут у него репозиторий с кодом,
приложение в ArgoCD и работающий сервис на своей странице каталога.

### Стенд
Стенд лаб 1–4 + ArgoCD в kind + Backstage локально (`npx @backstage/create-app@latest`).
Git: GitHub (`publish:github` есть из коробки) или GitLab (модуль scaffolder'а). Для kind без
реестра образ сервиса — уже загруженный `linkd:2.0.0` (сборка в CI — со звёздочкой).

> ⚠️ Gitea из 12-autopilot подходит для ArgoCD, но `publish:gitea` требует HTTPS у Gitea —
> либо настрой TLS с доверенным CA (`NODE_EXTRA_CA_CERTS`), либо используй GitHub/GitLab.

### Требования
1. **GitOps-репозиторий** `platform-gitops`: ApplicationSet с git-генератором по каталогам
   `apps/*` — новый каталог = новое Application ([../Left/07_ArgoCD/04_app_of_apps.md](/argocd/04-app-of-apps) §2).
2. **Шаблон** `linkd-service` ([08_backstage.md](/platform/08-backstage) §4): форма (имя по regex,
   владелец из каталога, система, галочка «нужна база»); скелет с `app/`, Dockerfile, CI,
   `catalog-info.yaml`, `mkdocs.yml`; шаги: репозиторий сервиса → PR/MR в `platform-gitops`
   с `apps/&lt;имя&gt;/linkdapp.yaml` (и `linkddatabase` по галочке) → регистрация в каталоге.
3. **ArgoCD:** Application нового сервиса синхронизируется автоматически после мержа; для
   LinkdDatabase — `Prune=false` и порядок синхронизации после CRD.
4. **Каталог:** у сервиса владелец-группа, вкладки Kubernetes (поды из kind) и ArgoCD (статус sync)
   работают; TechDocs показывает `docs/index.md` из скелета.
5. **Права:** токены Backstage к git, ArgoCD и Kubernetes — отдельные, минимальные; запиши,
   какие права у каждого и почему.

### Проверки
- В портале: Create → `linkd-service` → `demo-links`, владелец `team-a`, база — да.
- В git: репозиторий `demo-links` со скелетом; PR в `platform-gitops` → мерж.
- `kubectl -n argocd get applications` — `demo-links` Synced/Healthy;
  `kubectl -n team-a get la demo-links` — `Ready True`.
- В каталоге: `demo-links` с `lifecycle: experimental`, поды и статус ArgoCD во вкладках.

### Критерии приёмки
- [ ] Путь «форма → работающий сервис» проходит без ручных `kubectl apply`
- [ ] Имя с ошибкой (`Demo_Links`) отклоняет форма, а не ArgoCD или кластер
- [ ] Созданный сервис сразу соответствует политикам лабы 2
- [ ] Во вкладках каталога видны поды и статус ArgoCD
- [ ] Права токенов описаны и минимальны

### Сломай сам
- Запусти шаблон с именем уже существующего сервиса — где упадёт и что увидит пользователь?
  Добавь шаг уборки `if: $&#123;&#123; failure() &#125;&#125;`.
- Укажи в скелете `owner` несуществующей группы — где это видно?
- Удали каталог `apps/demo-links` из gitops-репозитория: что удалит ArgoCD, а что нет (база)?

**Уборка:** удали тестовые репозитории и каталоги в `platform-gitops`, Backstage — `Ctrl+C`.

---

## 🧪 Лаба 6. Итоговый golden path, документация платформы и time to first deploy 🔑

### Цель
Собрать всё в один путь и проверить его **на человеке**: новый разработчик по README платформы
доходит от кнопки до работающего URL, а ты меряешь, сколько это заняло и где он спотыкался.

### Стенд
Всё из лаб 1–5 в одном кластере (или пересобранное с нуля по твоему README — это часть проверки).

### Требования
1. **Путь целиком:** шаблон Backstage → репозиторий → PR в gitops → ArgoCD → LinkdApp с
   `database: true` и `delivery: canary` → оператор → Deployment/Rollout, HTTPRoute, LinkdDatabase →
   Crossplane → CNPG → ограждения проверили всё по дороге → сервис в каталоге с метриками.
2. **Вторая выкатка** нового сервиса идёт canary с анализом (лаба 3), плохая — откатывается сама.
3. **README платформы** `docs/README.md` (он же в TechDocs):
   - что платформа даёт и чего **не** даёт (границы ответственности);
   - «первый сервис за 15 минут» — пошагово;
   - API: LinkdApp, LinkdDatabase — поля, пределы, примеры;
   - ограждения — ссылка на `docs/policies.md`;
   - как выкатывать и откатывать (canary, `git revert`);
   - что делать, если «не работает»: статусы, где логи, куда писать;
   - поддержка: кто дежурит по платформе, SLO платформы (например, «оператор reconcile'ит
     за 1 минуту в 99% случаев»), как просить новые возможности.
4. **Bootstrap с нуля:** `make platform-up` (или helmfile/скрипт) поднимает весь стенд
   в пустом kind; время подъёма — в README.
5. **Замер:** «time to first deploy» — от открытия README до первого `200` от нового сервиса.
   Минимум два прогона: ты и «новичок» (коллега, друг или ты через неделю, строго по README).
   Записывай каждый вопрос и каждую ручную правку.
6. **Отчёт** `docs/platform-report.md`: время прогонов, список трений (friction log),
   топ-3 улучшения, что из платформы оказалось лишним (честно — см. [01_platform_engineering.md](/platform/01-platform-engineering)).

### Проверки
```bash
make platform-up                        # или свой скрипт; засеки время
# прогон «новичка»: только README, ты молчишь и записываешь
kubectl get la,linkddatabase,rollout -A
kubectl argo rollouts get rollout &lt;сервис&gt; -n team-a
```text
### Критерии приёмки
- [ ] Весь путь проходит без ручных `kubectl apply` и без помощи автора
- [ ] Time to first deploy измерен дважды; у «новичка» ≤ 30–60 минут
- [ ] README отвечает на вопросы, которые возникли у «новичка» (или дополнен после прогона)
- [ ] Стенд поднимается с нуля одной командой, время записано
- [ ] Friction log и топ-3 улучшения записаны
- [ ] Можешь за 5 минут рассказать платформу на собесе: схема, решения, цифры

### Сломай сам
- **Учения «платформа лежит»:** останови оператор, Crossplane и ArgoCD по очереди. Что
  продолжает работать у команд (живые сервисы), а что нет (новые выкатки, базы)? Запиши
  в README раздел «что делать при отказе платформы».
- Попроси «новичка» сделать что-то вне golden path (свой Helm-чарт, базу MySQL). Платформа
  мешает или помогает? Есть ли у него понятный путь «в обход» — и нужно ли его давать?

**Уборка:** `kind delete cluster --name platform` — и проверь, что `make platform-up`
действительно поднимает всё заново.

---

## 🏁 Итоговый чек-лист блока

- [ ] Лаба 1: оператор LinkdApp в кластере, минимальные права, метрики, две команды
- [ ] Лаба 2: VAP и Kyverno с понятными сообщениями, webhook не кладёт кластер
- [ ] Лаба 3: canary с анализом по Prometheus, видел три исхода и автооткат
- [ ] Лаба 4: `database: true` даёт PostgreSQL через Crossplane, ограждения и ADR
- [ ] Лаба 5: шаблон Backstage → репозиторий → ArgoCD → сервис в каталоге
- [ ] Лаба 6: golden path целиком, README платформы, time to first deploy измерен
- [ ] Всё лежит в `platform-lab` с README, схемой и ADR — это готовый проект для резюме

➡️ Дальше: [10_interview.md](/python/10-interview) — вопросы с собеседований
