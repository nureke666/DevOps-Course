---
title: "05. Kubernetes и Helm: чарт linkd 2.0 и данные в кластере"
description: "Цель этапа: перенести чарт из 07-orbit в портфолио, довести его до linkd 2.0"
---

# 05. Kubernetes и Helm: чарт linkd 2.0 и данные в кластере

> **Цель этапа:** перенести чарт из 07-orbit в портфолио, довести его до linkd 2.0
> (новые пробы, PostgreSQL вместо SQLite, несколько реплик) и разложить так, чтобы на
> этапе 06 его подхватил Argo CD: чарт — рядом с кодом, values окружений — в gitops-репо.
>
> **После этапа у тебя есть:** `linkd-platform/deploy/helm/linkd/`,
> `linkd-gitops/envs/{dev,prod}/values.yaml`, PostgreSQL отдельно от чарта приложения,
> `docs/breakages.md`, проверенное поведение при rolling update и падении БД, раздел
> «Kubernetes» в README.
>
> **~время:** 3–5 часов (после проекта).

---

## 🧪 Откуда берём

| Проект | Что забираешь | Когда готово |
|--------|---------------|--------------|
| 🛠️ **07-orbit** — оркестрация · `README` · `~/Projects/devops/07-orbit` | `chart/` с `values-dev.yaml` и `values-prod.yaml`; PostgreSQL и NetworkPolicy из задачи «полный стек»; `BREAKAGES.md` | `./check.sh` зелёный, включая «десять поломок» |
| 🛠️ **09-ledger** · `README` · `~/Projects/devops/09-ledger` | что PostgreSQL нужно для жизни: версия, ресурсы, параметры | по ходу проекта |

Инциденты Kubernetes из `99-incidents`
(`~/Projects/devops/99-incidents`) — в журнал вместе с `BREAKAGES.md`.

---

## 🎯 Цель

Показать, что Kubernetes — это не «применить чужой YAML», а осознанные решения: почему
такие пробы, откуда цифры в requests/limits, что будет при drain ноды, почему БД живёт
отдельно от приложения. Каждая строка чарта должна быть объяснима.

Что меняется по сравнению с 07-orbit:

- пробы смотрят на `/healthz` и `/readyz` вместо общего `/health`;
- строка подключения к БД приходит из Secret, а не собирается в ConfigMap;
- данные в PostgreSQL — значит, в prod можно держать несколько реплик, и появляются
  PDB и распределение по нодам;
- values окружений уезжают в `linkd-gitops` — туда CI пишет тег образа (этап 03).

---

## 🗺️ Что получится

```text
 linkd-platform/deploy/helm/linkd/    ← chart/ из 07-orbit, обновлённый под 2.0
 linkd-gitops/envs/dev/values.yaml    ← values-dev.yaml   (image.tag пишет CI)
 linkd-gitops/envs/prod/values.yaml   ← values-prod.yaml
 linkd-gitops/data/                   ← PostgreSQL: своё приложение, свой жизненный цикл

 ns dev (1 реплика)                        ns prod (≥ 2 реплики, PDB, spread по нодам)
 Ingress linkd-dev.127.0.0.1.nip.io        Ingress linkd.127.0.0.1.nip.io
   └─► Service ─► linkd                      └─► Service ─► linkd  linkd
                    │                                          │
                    ▼                                          ▼
            postgres-0 (PVC)                           postgres-0 (PVC)
 Secret с LINKD_DATABASE_URL — пока руками (этап 08 заменит на Vault + ESO)
 NetworkPolicy: ingress-controller → linkd → postgres, остальное — deny
```text
---

## 🪜 Шаги

### 1. Проект зелёный

```bash
cd ~/Projects/devops/07-orbit && ./check.sh
```text
### 2. Перенос

- `chart/` → `linkd-platform/deploy/helm/linkd/`;
- `values-dev.yaml` / `values-prod.yaml` → `linkd-gitops/envs/{dev,prod}/values.yaml`;
- манифесты из `manifests/` не переносятся: это ступеньки обучения, чарт их заменяет;
- `BREAKAGES.md` → `linkd-platform/docs/breakages.md`.

До этапа 06 чарт ставится так же, как в проекте, только values берутся из соседнего
каталога `linkd-gitops`.

### 3. Что добавить поверх проекта

Требования к чарту — это список «что должно быть», а не шаблоны: как это сделать,
отработано в 07-orbit.

- **Пробы:** liveness → `/healthz`, readiness → `/readyz`. Нужна ли startupProbe —
  реши сам: по CHANGELOG linkd стартует быстро и не ждёт базу (схему создаёт в фоне).
- **БД:** чарт **не создаёт** Secret, а ссылается на существующий по имени из values;
  `LINKD_DATABASE_URL` приходит оттуда. Пароль не виден в `kubectl describe pod`.
- **PostgreSQL отдельно от чарта приложения** — своё приложение в `linkd-gitops/data/`
  (на этапе 06 — отдельный Application): у данных другой жизненный цикл, удаление релиза
  linkd не должно трогать БД. Варианты — таблица ниже.
- **Несколько реплик в prod** — PDB и `topologySpreadConstraints`; в dev PDB выключен.
  Помни, что linkd открывает подключение к PostgreSQL на каждый запрос: больше реплик
  и RPS — больше подключений к одной базе (`max_connections` из 09-ledger).
- **Наблюдаемость заранее:** `LINKD_LOG_FORMAT=json` через values; трейсы выключены
  по умолчанию и включаются values с `OTEL_EXPORTER_OTLP_ENDPOINT` (этап 07); порт
  назван — ServiceMonitor ссылается на имя порта.
- **Учебные фолты** — через дополнительные переменные окружения в values, по умолчанию
  пусто. Они понадобятся для демо и проверки алертов.
- **Адреса:** kind-конфиг из 07-orbit пробрасывает порт 80 кластера на `localhost:8088`,
  так что хосты — `linkd-dev.127.0.0.1.nip.io:8088` и `linkd.127.0.0.1.nip.io:8088`.
  TLS через cert-manager — по желанию (тогда пробрасывается и 443); выбранные адреса —
  одни и те же в values, README и демо.
- **Образ** — из GitLab Container Registry, тег только из values окружения.
- **securityContext:** числовой non-root UID из Dockerfile, `readOnlyRootFilesystem`,
  `drop: [ALL]`, seccomp `RuntimeDefault` — подготовка к Pod Security `restricted` (этап 08).
- **Лейблы** `app.kubernetes.io/*` одинаковые везде — на них опираются NetworkPolicy,
  ServiceMonitor и запросы в Grafana.

**Где жить PostgreSQL:**

| Вариант | Плюсы | Минусы | Когда |
|---------|-------|--------|-------|
| Свой StatefulSet (из 07-orbit) | всё видно и объяснимо: PVC, headless Service, пробы | нет автофейловера, реплик, PITR | pet-проект, обучение |
| Оператор (CloudNativePG) | реплики, фейловер, бэкапы и PITR декларативно | ещё один слой CRD и «магии» | расширение проекта ([11_demo_and_next.md](/project/11-demo-and-next)) |
| Готовый чарт | быстро | проверяй, откуда образы и обновляются ли они | если понятно, что внутри |
| Managed БД | бэкапы, обновления, HA у провайдера | деньги, vendor lock-in | прод |

### 4. Проверки

Сначала статически — для **обоих** окружений:

```bash
helm lint deploy/helm/linkd -f ../linkd-gitops/envs/dev/values.yaml
helm template linkd deploy/helm/linkd -f ../linkd-gitops/envs/prod/values.yaml \
  | kubectl apply --dry-run=server -f -
```text
Потом поведение — это то, о чём спросят на собесе:

- **rolling update под нагрузкой** (цикл `curl` или k6 из 14-pulse) — ноль ответов 5xx
  или единицы, и понятно откуда;
- **падение PostgreSQL** — поды linkd `NotReady`, но `RESTARTS` не растёт;
- **удаление пода PostgreSQL** — данные на месте;
- **drain ноды** в prod — PDB не даёт уронить все реплики разом;
- **посторонний под** не достучится до PostgreSQL.

Результаты — цифрами в README (сколько запросов, сколько ошибок, сколько длился rollout).

### 5. Журнал поломок

`docs/breakages.md` из 07-orbit — формат «симптом → как диагностировалось → причина».
Две-три самые интересные поломки — в `docs/journal.md` как истории для рассказа.

### 6. README и ADR

- Раздел «Kubernetes»: схема из «Что получится», чем dev отличается от prod (таблица из
  values), результаты проверок.
- ADR «PostgreSQL в своём StatefulSet» — с планом перехода на оператор.
- ADR «Чарт рядом с кодом, values в gitops» — можно отложить до этапа 06, там выбирается
  способ связать их.

### 7. Коммит — в оба репозитория

```bash
git -C ~/Projects/linkd-platform add deploy docs && git -C ~/Projects/linkd-platform commit -m "deploy: helm chart for linkd 2.0"
git -C ~/Projects/linkd-gitops add envs data && git -C ~/Projects/linkd-gitops commit -m "envs: dev/prod values and postgres"
```text
---

## ✅ Критерии приёмки

- [ ] `helm lint` и серверный dry-run без ошибок для dev и prod
- [ ] Один чарт, два окружения — отличия только в `envs/*/values.yaml`
- [ ] Пробы на `/healthz` и `/readyz`; при упавшей БД поды `NotReady`, но не перезапускаются
- [ ] Строка подключения — из Secret; в чарте и values нет ни одного секрета
- [ ] PostgreSQL развёрнут отдельно от релиза linkd, данные переживают удаление пода
- [ ] Во время rolling update поток запросов не получает 5xx (или единицы — и понятно почему)
- [ ] В prod ≥ 2 реплики, `drain` уважает PDB
- [ ] `docs/breakages.md` в репо, лучшие истории — в журнале
- [ ] Каждое число в requests/limits и пробах можно объяснить

---

## 🪤 Грабли

- **Пробы остались на `/health` из 07-orbit.** В 2.0 он ходит в базу и отвечает 500,
  когда её нет. Чем это кончится для liveness и для readiness — тот самый вопрос из
  07-orbit; в чарте портфолио пробы — на `/healthz` и `/readyz`.
- **В Secret нет `LINKD_DATABASE_URL`** (или опечатка в ключе) — linkd молча стартует
  на SQLite внутри пода, пробы зелёные, данные живут до первого рестарта. Проверка —
  `storage` в `/health`.
- **`replicas` в Deployment при включённом HPA** — каждый sync сбрасывает реплики,
  HPA возвращает: «пила». При HPA поле не рендерится.
- **HPA без `requests.cpu`** не может посчитать утилизацию: `&lt;unknown&gt;`.
- **CPU limit** даёт throttling даже на свободной ноде; limit по памяти — обязателен.
- **PDB при одной реплике** блокирует `drain` навсегда — в dev PDB выключен.
- **Secret создан после Deployment** → `CreateContainerConfigError`. Под поднимется сам,
  когда Secret появится, но в событиях это видно — не пугайся.
- **Изменился ConfigMap — поды не перезапустились.** Deployment не знает о смене
  конфига, пока не изменился pod template (отсюда checksum-аннотации).
- **`local-path` PV привязан к ноде.** Нода умерла — данные вместе с ней. Именно поэтому
  этап 09 не опционален.
- **Образ из kind, а не из registry.** `kind load` из 07-orbit удобен для учёбы; в
  портфолио кластер тянет образ из registry по тегу — иначе CI и gitops ни при чём.
- **Имя релиза.** Имена ресурсов зависят от него; одинаковое имя во всех окружениях
  упрощает PromQL, NetworkPolicy и runbook'и.

---

## 🤔 Вопросы себе

1. Чем отличаются startup, liveness и readiness probe? Что будет без startupProbe при медленном старте?
2. Что такое requests и limits, как они влияют на планирование и QoS-класс пода?
3. Почему PostgreSQL — StatefulSet и отдельное приложение, а linkd — Deployment?
4. Зачем headless Service у StatefulSet?
5. Как HPA считает нужное число реплик? Что делает `maxUnavailable` в стратегии обновления?
6. Что делает PDB и какие операции он защищает, а какие — нет?
7. Как запрос доходит от браузера до пода: DNS → Ingress → Service → Endpoints → под?
8. Почему чарт не создаёт Secret, а только ссылается на него?
9. Какая поломка из `BREAKAGES.md` была самой неочевидной и как она диагностировалась?

---

## 📚 Теория в волте

- Deployment, rolling update: [../Kubernetes/05_deployment.md](/kubernetes/05-deployment)
- StatefulSet: [../Kubernetes/06_daemonset_statefulset.md](/kubernetes/06-daemonset-statefulset)
- ConfigMap/Secret: [../Kubernetes/08_configmap_secret.md](/kubernetes/08-configmap-secret)
- Probes и ресурсы: [../Kubernetes/09_probes_resources.md](/kubernetes/09-probes-resources)
- Service и Ingress: [../Kubernetes/11_service.md](/kubernetes/11-service),
  [../Kubernetes/12_ingress.md](/kubernetes/12-ingress)
- NetworkPolicy: [../Kubernetes/13_networkpolicy.md](/kubernetes/13-networkpolicy)
- Хранилище: [../Kubernetes/14_storage.md](/kubernetes/14-storage)
- Helm: [../Kubernetes/15_helm.md](/kubernetes/15-helm)
- HPA: [../Kubernetes/18_hpa_autoscaling.md](/kubernetes/18-hpa-autoscaling)
- PDB, spread, affinity: [../Kubernetes/19_scheduling.md](/kubernetes/19-scheduling)
- Когда под не стартует: [../Kubernetes/20_troubleshooting.md](/kubernetes/20-troubleshooting)
- PostgreSQL в эксплуатации: [../Left/01_Databases/04_postgresql_conf.md](/databases/04-postgresql-conf)

➡️ Следующий этап: [06_gitops_argocd.md](/project/06-gitops-argocd)
