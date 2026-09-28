---
title: "24. Жизненный цикл кластера"
description: "Обновления, version skew, устаревшие API, матрица аддонов, PDB и drain, бэкап etcd, сертификаты kubeadm, аудит, blue/green миграция"
---

# 24. ⭐ Жизненный цикл кластера: обновления, патчи, сертификаты, аудит

> Вне роадмапа — продолжение темы 16: кластер надо не только поставить, но и **держать**
> годами. Вопросы собеса: *«Как вы обновляете кластер?»*, *«Кто удалил deployment?»*
> **После темы ты умеешь:** спланировать обновление (skew, устаревшие API, совместимость
> аддонов), провести его по runbook с откатом, патчить ОС нод, следить за сертификатами
> и по аудит-логу ответить, кто и когда сделал изменение.
> Версии и даты — «проверь, сентябрь 2026».

---

## 🗺️ Карта темы

```text:no-line-numbers
  ВРЕМЯ ЖИЗНИ МИНОРНОЙ ВЕРСИИ ≈ 14 месяцев (12 стандарт + 2 maintenance)
  1.35 ────────────────┐ EOL 28.02.2027
  1.36 ───────────────────────────┐ EOL 28.06.2027
  1.37 ────────────────────────────────────┐ EOL 28.10.2027

  ОБНОВЛЕНИЕ = ПРОЕКТ, А НЕ КОМАНДА
   план ──► pre-checks ──► бэкап etcd ──► control plane ──► аддоны ──► ноды ──► post-checks
    │           │                             │                          │
    │           └ PDB, здоровье, сертификаты  └ kubeadm upgrade (16)     └ in-place или surge
    └ changelog, устаревшие API (pluto, метрика), матрица аддонов (Envoy Gateway ≤ 1.36!)
  ФОН ВСЕГДА:  патчи ОС нод ── kured · сертификаты ── kubeadm certs · аудит ── кто, что, когда
```

---

## 1. Релизный цикл и окно поддержки

~3 минорных в год (v1.36 — 22.04.2026, **v1.37 — 26.08.2026**), патчи примерно раз в месяц.
Каждая минорная живёт ~**14 месяцев**: 12 стандартных + 2 месяца maintenance mode
(только CVE и критичное). Официально поддерживаются три последние ветки (проверь, сентябрь 2026):

| Версия | Последний патч | Maintenance с | EOL |
|--------|----------------|---------------|-----|
| 1.37 | 1.37.0 | 28.08.2027 | 28.10.2027 |
| 1.36 | 1.36.4 | 28.04.2027 | 28.06.2027 |
| 1.35 | 1.35.8 | 28.12.2026 | 28.02.2027 |
| 1.34 | 1.34.11 | уже с 27.08.2026 | **27.10.2026** |

- **Отставание на 2+ минорные = меньше года до кластера без патчей безопасности.**
  Кластер на 1.34 в сентябре 2026 — срочное обновление. Норма — одна минорная раз в ~4 месяца.
- Managed живут по своему календарю: EKS — 14 месяцев standard + 12 extended (×6 к цене),
  Yandex — каналы и версии позже upstream (см. блок про облака).

---

## 2. ⭐ Version skew: кто насколько может отставать

Пример для kube-apiserver **1.37**:

| Компонент | Допустимо | Правило |
|-----------|-----------|---------|
| Другие kube-apiserver (HA) | 1.37, 1.36 | Между самым новым и самым старым — не больше 1 минорной |
| controller-manager, scheduler, CCM | 1.37, 1.36 | Не новее apiserver, старше максимум на 1 |
| **kubelet** | 1.37 … 1.34 | Не новее apiserver, старше максимум на **3** |
| kube-proxy | 1.37 … 1.34 | Старше apiserver максимум на 3; от kubelet — ±3 |
| **kubectl** | 1.38, 1.37, 1.36 | ±1 минорная от apiserver |

```text:no-line-numbers
  apiserver:    1.36 ─────► 1.37                    (сначала он — все остальные «догоняют»)
  cm/scheduler: 1.36 ───────────► 1.37              (сразу после apiserver)
  kubelet:      1.34 1.35 1.36 ──────────► 1.37     (последними; могут отставать на 3)
```

**Главные выводы:**
1. **Порядок фиксирован skew-политикой:** apiserver → controller-manager/scheduler/CCM →
   kubelet → kube-proxy. kubelet **не может** быть новее apiserver, поэтому ноды — последними.
2. Ноды могут отставать на 3 минорные — это запас на медленные node pool'ы,
   а не повод их не обновлять. Если kubelet на 1.34, apiserver дальше 1.37 не поднять.
3. kubectl в CI и у людей тоже обновляют: kubectl 1.35 с кластером 1.37 — вне поддержки.
   У managed бывают ограничения строже upstream (Yandex: группа узлов — до 2 минорных).

---

## 3. Планирование: что может сломаться

### 3.1. Changelog и «Deprecations and removals»

Перед каждой минорной читают три источника: пост релиза на kubernetes.io/blog
(секция **Deprecations and removals**), **Sneak Peek** за месяц до релиза и `CHANGELOG-1.xx.md`
(раздел **Urgent Upgrade Notes** — «прочитай до обновления»).

Что в v1.37 касается эксплуатации (пример того, что ищут в changelog):

| Изменение | Кого заденет |
|-----------|--------------|
| Static Pod больше не может ссылаться на Secret/ConfigMap (feature gate удалён) | Самописные static pod'ы с `envFrom`/`secretRef` |
| `kubectl run --filename/-f` объявлен устаревшим | Скрипты, где `run` запускали с `-f` |
| kube-proxy `ipvs` устарел: к v1.40 выключен по умолчанию, к v1.43 удалён | Кластеры с `mode: ipvs` — планировать nftables/iptables |
| cgroup v1: с v1.35 `failCgroupV1: true` — kubelet не стартует на cgroup v1 | Старые ОС нод (CentOS 7 и подобные) |

### 3.2. ⭐ Устаревшие API: найти до того, как их удалят

Жизнь API: `v1beta1` объявили устаревшим → через несколько релизов **удалили** →
`kubectl apply` старого манифеста падает с `no matches for kind "X" in version "Y"`.
Объекты, **уже лежащие в etcd**, apiserver конвертирует сам — ломаются клиенты:
манифесты в git, Helm-чарты, CI-скрипты, операторы со старыми клиентами.

| Способ | Что видит | Команда |
|--------|-----------|---------|
| ⭐ Метрика apiserver | **Реальные запросы** к устаревшим API за время жизни процесса (кто угодно: CI, операторы) | `kubectl get --raw /metrics \| grep apiserver_requested_deprecated_apis` |
| Аудит-лог | Кто именно ходит: аннотации `k8s.io/deprecated`, `k8s.io/removed-release` | §9 этой темы |
| Предупреждения kubectl | `Warning: ... is deprecated in v1.X+, unavailable in v1.Y+` | видно при `apply` |
| **pluto** (Fairwinds, v5.24.4 — 15.09.2026, живой) | Файлы, Helm-релизы, объекты в кластере | см. ниже |
| kubent (kube-no-trouble) | ⚠️ Фактически не поддерживается: правила до 1.32, только nightly-сборки | в старых гайдах; альтернатива — kubepug |

```bash
# pluto: сразу против целевой версии
pluto detect-files -d k8s/ --target-versions k8s=v1.37.0
pluto detect-helm -o wide --target-versions k8s=v1.37.0        # манифесты в Helm-релизах
pluto detect-api-resources -o wide                             # объекты в кластере

# метрика: removed_release подскажет, в какой версии API исчезнет
kubectl get --raw /metrics | grep apiserver_requested_deprecated_apis
# apiserver_requested_deprecated_apis{group="...",removed_release="1.xx",resource="...",version="v1beta1"} 1

# kubectl convert — плагин; умеет только версии, чей код ещё в нём (HPA v2beta2 в 1.36 — уже руками)
curl -LO "https://dl.k8s.io/release/$(curl -Ls https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl-convert"
sudo install -o root -g root -m 0755 kubectl-convert /usr/local/bin/kubectl-convert
kubectl convert -f old-cronjob.yaml --output-version batch/v1 > cronjob.yaml
```

> ⚠️ Метрика видит запросы **с момента старта** apiserver, но не манифесты в git, которые ещё
> не применялись. Нужны оба способа: метрика (кто ходит) + pluto (что сломается при деплое).

### 3.3. ⭐ Матрица совместимости аддонов

Кубер обновить можно, а вот аддон на новой версии может не заработать. Правило: для
**каждого** аддона найти версию, которая поддерживает **и текущую, и целевую** минорную,
и обновить аддон **до** control plane.

| Аддон | Что проверять |
|-------|---------------|
| **Envoy Gateway** | v1.9 поддерживает 1.33–1.36 → ⛔ **блокирует переход на 1.37**, ждём релиз с 1.37 в матрице |
| CNI (Calico, Cilium) | Матрица версий k8s; обновление CNI — отдельное окно, это сеть всего кластера |
| CSI-драйверы | Совместимость с версией и с snapshot-controller |
| Cluster Autoscaler | Минорная CA **совпадает** с минорной кубера — обновляется вместе с кластером |
| KEDA | 2.21 поддерживает 1.34–1.36 → тоже ⛔ для 1.37 (тема 25 §6) |
| cert-manager, metrics-server, ArgoCD, операторы | Supported releases, версии CRD и клиентских библиотек |

Результат планирования — таблица «аддон → текущая → целевая → поддерживает ли обе».
Если хотя бы один аддон — ⛔, обновление кластера **ждёт**. И всегда сначала staging
с теми же версиями и аддонами: dev → staging → неделя наблюдения → prod.

---

## 4. ⭐ Порядок обновления

```text:no-line-numbers
 0. План: changelog, pluto, матрица аддонов, окно работ, ответственные
 1. Pre-checks: ноды Ready, поды здоровы, PDB позволяют drain, сертификаты, место на дисках
 2. Бэкап: снапшот etcd ВНЕ кластера + /etc/kubernetes (PKI, манифесты)
 3. Аддоны, которые иначе сломаются, — до версии, поддерживающей обе минорные
 4. Control plane: первый CP (kubeadm upgrade apply) → остальные CP (kubeadm upgrade node)
 5. Аддоны после CP: CoreDNS/kube-proxy (kubeadm сам), CNI, остальное по матрице
 6. Ноды: по одной (или партиями) — in-place или surge
 7. Post-checks: версии, поды, метрики ошибок, устаревшие API, смоук-тесты
```

### Ноды: in-place или surge (замена)

| | In-place | Surge / замена нод |
|---|----------|--------------------|
| Как | drain → обновить пакеты kubelet/kubeadm → restart → uncordon | Поднять новые ноды нужной версии → drain старых → удалить |
| Где | kubeadm/kubespray на своём железе | Managed node groups, ASG, Karpenter (drift), Cluster API |
| Ёмкость | На время — минус одна нода | Временно **плюс** ноды (нужна квота и деньги) |
| Откат ноды | Сложно (даунгрейд пакетов не поддерживается) | Легко: старые ноды ещё живы |
| Дрейф конфигурации | Копится годами | Ноды всегда «чистые» из образа |

---

## 5. Процесс вокруг команд kubeadm

Команды `kubeadm upgrade plan/apply/node` и смена репозитория pkgs.k8s.io — в
теме 16 («Эксплуатация»). Здесь — процесс вокруг них.

### Pre-checks

```bash
kubectl get nodes -o wide                                  # все Ready, версии kubelet
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
kubectl get --raw='/readyz?verbose' | tail -3              # readyz check passed
kubectl get pdb -A                                         # ⭐ ALLOWED DISRUPTIONS = 0 → drain зависнет
sudo kubeadm certs check-expiration                        # сертификаты
df -h /var/lib/etcd /var/lib/containerd                    # место (etcd и образы)
pluto detect-helm -o wide --target-versions k8s=v1.37.0
```

### PDB и drain

| Ситуация | Что будет при drain |
|----------|---------------------|
| 3 реплики, PDB `maxUnavailable: 1` | ✅ Вытесняет по одной, ждёт готовности замены |
| 1 реплика, PDB `minAvailable: 1` | ⛔ `Cannot evict pod as it would violate the pod's disruption budget` — **вечно** |
| Под без контроллера (голый Pod) | ⛔ drain откажется без `--force`, под будет потерян |
| Нет PDB | ⚠️ Вытеснит все реплики, если они на одной ноде |

> ⚠️ Зависший drain (`--timeout=10m`) разбирают через `kubectl get pdb -A -o wide`. Не лечи его
> `--disable-eviction` — он удаляет поды в обход PDB. Правильно: временно добавить реплику
> или договориться с владельцем сервиса.

### Откат: чего нет и что есть

**Даунгрейда кластера в kubeadm нет.** Что есть на самом деле:

| Уровень | Как откатываются |
|---------|------------------|
| Сбой во время `kubeadm upgrade apply` | kubeadm сам возвращает static pod манифесты; бэкапы — в `/etc/kubernetes/tmp/kubeadm-backup-manifests-*` и `kubeadm-backup-etcd-*` |
| Control plane обновился, но всё плохо | Восстановление **снапшота etcd** + старые манифесты и пакеты (тема 21 §4) — долго и страшно, репетировать заранее |
| ⭐ Надёжный откат | **Blue/green кластер** (§10): старый кластер жив, трафик возвращается переключением DNS |

> 💬 На собесе: «Откат обновления кластера — это не команда, а архитектура. Для мелких
> обновлений — снапшот etcd и репетиция на staging; для рискованных (несколько минорных,
> смена CNI) — второй кластер и переключение трафика».

---

## 6. Managed-обновления

Облако обновляет control plane, но **всё остальное — твоё**: устаревшие API, аддоны,
ноды, PDB, окна работ. Порядок тот же: CP → аддоны → ноды.

| | EKS | Yandex Managed Kubernetes |
|---|-----|---------------------------|
| Control plane | Ты запускаешь (консоль/Terraform `cluster_version`), по одной минорной | Канал `RAPID`/`REGULAR`/`STABLE`, окно обслуживания, автообновление патчей |
| Проверки перед | **Upgrade insights** (`aws eks list-insights`) — в т.ч. устаревшие API | Сам: pluto, метрика |
| Аддоны | EKS add-ons (`vpc-cni`, `coredns`, `kube-proxy`…) — версия под минорную | Встроенные обновляет облако, свои — ты |
| Ноды | Managed node group: rolling update с surge; Karpenter — drift; Auto Mode — сам | Группа узлов: отдельное обновление, может отставать на 2 минорные |
| Цена опоздания | Extended support ×6 к цене CP | Версия выпадает из поддержки канала |

---

## 7. Патчи ОС нод: kured

Патчи ядра и glibc применяются **только после перезагрузки**; `unattended-upgrades` создаёт
`/var/run/reboot-required`, а аккуратно перезагрузить ноды по одной — работа **kured**
(KUbernetes REboot Daemon, CNCF sandbox; v1.23.0 — 30.06.2026, протестирован на 1.35/1.36).

```text:no-line-numbers
 kured (DaemonSet) раз в --period (1h) проверяет sentinel-файл
      │ есть /var/run/reboot-required
      ▼
 берёт лок (аннотация на DaemonSet) ──► cordon + drain (с PDB) ──► reboot ──► uncordon ──► снимает лок
                       └ одновременно только --concurrency нод (по умолчанию 1)
```

```bash
helm repo add kubereboot https://kubereboot.github.io/charts
helm install kured kubereboot/kured -n kube-system \
  --set configuration.startTime=02:00 --set configuration.endTime=05:00 \
  --set configuration.timeZone=Asia/Almaty \
  --set configuration.rebootDays="{mo,tu,we,th}"       # ключи values — проверь в чарте
```

| Флаг | Дефолт | Зачем |
|------|--------|-------|
| `--period` | `1h` | Как часто проверять sentinel |
| `--reboot-sentinel` | `/var/run/reboot-required` | Файл-признак (или `--reboot-sentinel-command`) |
| `--start-time` / `--end-time` / `--reboot-days` / `--time-zone` | весь день, все дни, UTC | ⭐ Окно перезагрузок |
| `--prometheus-url` + `--alert-filter-regexp` | — | Не перезагружать, пока горят алерты |
| `--blocking-pod-selector` | — | Не перезагружать, пока на ноде есть такие поды (батчи) |
| `--concurrency` | 1 | Сколько нод одновременно |

> 💡 Альтернатива kured — не патчить ноды, а **заменять** их свежим образом
> (Karpenter `expireAfter`, EKS Auto Mode, Talos/Flatcar с update-оператором).

---

## 8. Сертификаты kubeadm

| Что | Срок | Кто продлевает |
|-----|------|----------------|
| Листовые (apiserver, etcd, front-proxy-client, kubeconfig'и CP) | **1 год** | `kubeadm upgrade` (автоматически) или `kubeadm certs renew` |
| CA (ca, etcd-ca, front-proxy-ca) | 10 лет | Только вручную, это отдельная процедура |
| Клиентский сертификат kubelet | ~1 год | kubelet ротирует сам |
| Serving-сертификат kubelet | самоподписанный | `serverTLSBootstrap: true` + одобрение CSR (`kubectl certificate approve`) |

```bash
sudo kubeadm certs check-expiration        # EXPIRES, RESIDUAL TIME по каждому
sudo kubeadm certs renew all
# ⭐ после renew перезапустить static pod'ы: вынести манифест и вернуть через ~20 с
sudo mkdir -p /tmp/m && sudo mv /etc/kubernetes/manifests/kube-apiserver.yaml /tmp/m/ \
  && sleep 20 && sudo mv /tmp/m/kube-apiserver.yaml /etc/kubernetes/manifests/
# так же для controller-manager, scheduler, etcd; затем обновить свой kubeconfig:
sudo cp /etc/kubernetes/admin.conf ~/.kube/config
```

> ⭐ **Кластер, который обновляют хотя бы раз в год, не упирается в сертификаты** —
> `upgrade apply/node` продлевает их заодно. «x509: certificate has expired» — признак
> кластера, который не обновляли. Алерт всё равно нужен: экспортер сертификатов, порог 30 дней.

---

## 9. ⭐ Аудит: кто, что и когда

Аудит пишет **kube-apiserver**: каждый запрос проходит через политику, и она решает,
что записать. Events (`kubectl get events`) на вопрос «кто» не отвечают — в них нет
пользователя, и живут они около часа.

| Уровень | Что пишется |
|---------|-------------|
| `None` | Ничего |
| `Metadata` | Кто, когда, откуда, глагол, ресурс, код ответа — **без тел** |
| `Request` | + тело запроса |
| `RequestResponse` | + тело ответа (самое подробное и тяжёлое) |

Стадии: `RequestReceived` → `ResponseStarted` (watch) → `ResponseComplete`, `Panic`; первую обычно исключают.

**Правила политики проверяются по порядку, срабатывает первое подходящее.**
Поэтому шумное и секретное — вверху, catch-all — внизу.

```yaml
# audit-policy.yaml
apiVersion: audit.k8s.io/v1
kind: Policy
omitStages: ["RequestReceived"]
rules:
  # 1. шум: watch kube-proxy, проверки здоровья, events
  - level: None
    users: ["system:kube-proxy"]
    verbs: ["watch"]
  - level: None
    nonResourceURLs: ["/healthz*", "/readyz*", "/livez*", "/version"]
  - level: None
    resources: [{ group: "", resources: ["events"] }]
  # 2. ⭐ секреты — ТОЛЬКО Metadata: на уровне Request тело секрета попадёт в лог
  - level: Metadata
    resources:
      - { group: "", resources: ["secrets", "configmaps"] }
      - { group: "authentication.k8s.io", resources: ["tokenreviews"] }
  # 3. изменения рабочих нагрузок и RBAC — подробно
  - level: RequestResponse
    verbs: ["create", "update", "patch", "delete", "deletecollection"]
    resources:
      - { group: "apps", resources: ["deployments", "statefulsets", "daemonsets"] }
      - { group: "rbac.authorization.k8s.io" }       # все ресурсы группы
  # 4. всё остальное — метаданные
  - level: Metadata
```

Бэкенды: **log** (файл JSON lines: `--audit-log-path`, `--audit-log-maxage`,
`--audit-log-maxbackup`, `--audit-log-maxsize`) и **webhook** (`--audit-webhook-config-file`,
отправка во внешнюю систему). Включается флагом `--audit-policy-file`.

Где взять: kubeadm — флаги apiserver + `extraVolumes`, лог в Loki/ELK/SIEM; EKS — control plane
logging типа `audit` в CloudWatch; Yandex — логи мастера в Cloud Logging.

### Ответ на «кто удалил deployment» (запрос `jq` — в мини-лабе ниже)

| Что в `user.username` | Как читать |
|-----------------------|------------|
| `kubernetes-admin`, человек из OIDC | Руками; смотри `sourceIPs`, `userAgent` (`kubectl/v1.36…`) |
| `system:serviceaccount:ci:deployer` | Пайплайн — ищи джобу по времени |
| `system:serviceaccount:argocd:argocd-application-controller` | GitOps `prune`: объект пропал из git → ищи коммит |
| Есть `impersonatedUser` | Действовали через `--as`: реальный автор — в `user` |
| `code: 403` | Пытались, но RBAC не пустил — тоже ценная находка |

---

## 🧪 Мини-лаба: аудит в kind и «кто удалил deployment»

> ⚠️ kind с Kubernetes 1.36+ генерирует конфиг kubeadm **v1beta4**: `extraArgs` —
> это **список** `name/value`, а не словарь, как в старых гайдах и в примере на сайте kind.

```bash
mkdir -p ~/lab-audit && cd ~/lab-audit
# 1. audit-policy.yaml — политика из §9 (скопируй блок целиком)

# 2. конфиг кластера
cat > kind-audit.yaml <<'YAML'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    image: kindest/node:v1.36.4
    kubeadmConfigPatches:
      - |
        apiVersion: kubeadm.k8s.io/v1beta4
        kind: ClusterConfiguration
        apiServer:
          extraArgs:
            - { name: audit-policy-file, value: /etc/kubernetes/policies/audit-policy.yaml }
            - { name: audit-log-path,    value: /var/log/kubernetes/kube-apiserver-audit.log }
            - { name: audit-log-maxage,  value: "7" }
            - { name: audit-log-maxsize, value: "100" }
          extraVolumes:
            - { name: audit-policies, hostPath: /etc/kubernetes/policies, mountPath: /etc/kubernetes/policies, readOnly: true,  pathType: DirectoryOrCreate }
            - { name: audit-logs,     hostPath: /var/log/kubernetes,      mountPath: /var/log/kubernetes,      readOnly: false, pathType: DirectoryOrCreate }
    extraMounts:
      - { hostPath: ./audit-policy.yaml, containerPath: /etc/kubernetes/policies/audit-policy.yaml, readOnly: true }
YAML
kind create cluster --name audit --config kind-audit.yaml       # запускать из ~/lab-audit

# 3. сценарий: SA пайплайна с правом удалять deployments
kubectl create namespace demo
kubectl -n demo create deployment web --image=nginx --replicas=2
kubectl -n demo create serviceaccount ci-bot
kubectl -n demo create role deployer --verb=get,list,watch,delete --resource=deployments
kubectl -n demo create rolebinding ci-bot --role=deployer --serviceaccount=demo:ci-bot

# 4. «злоумышленник» удаляет от имени SA через отдельный контекст с токеном
kubectl config set-credentials ci-bot --token="$(kubectl -n demo create token ci-bot)"
kubectl config set-context ci-bot --cluster=kind-audit --user=ci-bot --namespace=demo
kubectl --context ci-bot delete deployment web

# 5. и ещё одно удаление — через имперсонацию
kubectl -n demo create deployment api --image=nginx
kubectl -n demo delete deployment api --as=system:serviceaccount:demo:ci-bot

# 6. расследование (нужен jq на хосте)
docker exec audit-control-plane cat /var/log/kubernetes/kube-apiserver-audit.log \
  | jq -c 'select(.verb=="delete" and .objectRef.resource=="deployments")
      | {t: .requestReceivedTimestamp, user: .user.username, as: .impersonatedUser.username,
         name: .objectRef.name, ua: .userAgent, code: .responseStatus.code}'

kind delete cluster --name audit; kubectl config delete-context ci-bot; kubectl config delete-user ci-bot
```

**Что должно получиться:** для `web` — `user: system:serviceaccount:demo:ci-bot`,
для `api` — `user: kubernetes-admin` и `as: system:serviceaccount:demo:ci-bot`.
Дополнительно: создай и прочитай Secret, найди его `get` в логе — тела секрета там **нет**.

---

## 10. Blue/green миграция кластера с GitOps

Когда in-place слишком рискован: отставание на несколько минорных, смена CNI или ОС нод,
переезд в другой регион/облако, «кластер-снежинка», который страшно трогать.

```text:no-line-numbers
   git (GitOps-репозиторий: apps + addons + clusters/{blue,green})
        │                                │
        ▼                                ▼
   ArgoCD ──► BLUE 1.34 (прод)        GREEN 1.36 (новый) ◄── Terraform/kubeadm
        │          ▲                     │ 1. аддоны и приложения из того же git
        │          │                     │ 2. смоук-тесты, нагрузочный прогон
   DNS / глобальный LB ── 100% → blue    │ 3. вес трафика 10% → 50% → 100% на green
        │                                ▼
        └──────── откат = вернуть вес на blue (минуты, а не часы)
                  blue живёт N дней → удаляем
```

| Шаг | Детали |
|-----|--------|
| 1. Состояние вне кластера | БД — managed или отдельный кластер; stateful в кубере — Velero/репликация (тема Storage) |
| 2. Green из кода | Terraform + тот же GitOps-репозиторий; ApplicationSet с генератором кластеров |
| 3. Секреты | External Secrets из одного хранилища — не копировать руками |
| 4. Проверка | Смоук + сравнение метрик green и blue под одинаковым трафиком |
| 5. Переключение | Взвешенный DNS (Route 53 weighted, external-dns — тема 25) или глобальный LB; **TTL понизить заранее** |
| 6. Откат | Вес обратно на blue |
| 7. Уборка | Blue удаляется после периода наблюдения, иначе платишь за два кластера |

---

## 11. Шаблон runbook обновления

```markdown
# Обновление prod-cluster: v1.36.4 → v1.37.x
Окно: чт 02:00–05:00 (Asia/Almaty) · Исполнитель / второй: … · Канал: #ops-upgrade
## Подготовка (за неделю)
- [ ] Changelog и Urgent Upgrade Notes 1.37 разобраны
- [ ] pluto по git и Helm-релизам — 0; метрика deprecated API — 0
- [ ] Матрица аддонов: у каждого есть версия с 1.36 и 1.37 (Envoy Gateway!)
- [ ] Staging обновлён неделю назад без инцидентов; владельцы сервисов предупреждены
## Pre-checks → бэкап
- [ ] ноды Ready, `readyz` ok, в `get pdb -A` нет ALLOWED DISRUPTIONS = 0, сертификаты, диски
- [ ] снапшот etcd + /etc/kubernetes ВНЕ кластера, `etcdutl snapshot status` ok
## Выполнение → post-checks
- [ ] аддоны до совместимых → control plane → аддоны → ноды по одной (после каждой: Ready, ошибки не растут)
- [ ] всё на v1.37.x; смоук-тесты; 5xx и латентность в норме 30 минут
## Откат
- Условие: 5xx > 1% дольше 10 минут / CP не поднимается · Как: restore etcd (тема 21 §4) или трафик на blue
## Итог: сколько заняло, что пошло не так, что поменять в runbook
```

---

## 12. Грабли

| Грабля | Что происходит | Как избежать |
|--------|----------------|--------------|
| Прыжок через минорную | kubeadm не даст, managed не даст; в kubespray — сломанный кластер | Одна минорная за раз |
| Не проверили аддоны | После CP Gateway/CNI не стартует — лежит вход или сеть | Матрица аддонов до окна |
| PDB `minAvailable: 1` на одной реплике | drain висит бесконечно | Две реплики или `maxUnavailable: 1` |
| Удалённый API в чарте | Следующий `helm upgrade` падает уже после обновления | pluto по Helm-релизам |
| Renew сертификатов без рестарта | apiserver продолжает жить со старыми, через время — x509 | Перезапустить static pod'ы |
| Аудит на `RequestResponse` для всего | Гигабайты в час, apiserver ест память | Шум — в `None`, остальное — `Metadata` |
| `Request` для secrets | Пароли в открытом виде в лог-хранилище | Secrets — только `Metadata` |

---

## 💼 Как это в DevOps

- Обновление кластера — **регулярный процесс с календарём**: минорная раз в квартал-полгода,
  патчи ежемесячно. Кто обновляется «раз в два года», платит авариями и extended support.
- В резюме и на собесе ценится конкретика: «обновил 4 кластера с 1.33 до 1.36 по runbook,
  нашёл устаревшие API через pluto и метрику apiserver, простой — ноль».
- Самое частое реальное препятствие — не кубер, а **аддоны**: Gateway, CNI, операторы.
  Матрица совместимости — первый артефакт планирования.
- Аудит включают до инцидента, а не после: спросят «кто удалил» — ответ должен быть за минуты.
  В проде логи аудита уходят в SIEM и хранятся по требованиям безопасности.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Проверить skew | kubelet ≤ 3 минорных старше apiserver, kubectl ±1, CM/scheduler ≤ 1 |
| Найти устаревшие API в git/Helm | `pluto detect-files -d .` / `pluto detect-helm -o wide --target-versions k8s=v1.37.0` |
| Кто реально ходит в устаревшие API | `kubectl get --raw /metrics \| grep apiserver_requested_deprecated_apis` |
| Переписать манифест на новую версию API | `kubectl convert -f old.yaml --output-version apps/v1` |
| Проверить PDB перед drain | `kubectl get pdb -A` — ALLOWED DISRUPTIONS |
| Вывести ноду | `kubectl drain NODE --ignore-daemonsets --delete-emptydir-data --timeout=10m` |
| Сертификаты | `kubeadm certs check-expiration` / `renew all` + рестарт static pod'ов |
| Включить аудит | `--audit-policy-file` + `--audit-log-path` (+ `extraVolumes`) |
| Кто удалил объект | `jq 'select(.verb=="delete" and .objectRef.name=="web")' audit.log` |
| Надёжный откат обновления | Blue/green кластер + GitOps |

---

## 🧠 Что запомнить

1. Минорная версия живёт ~14 месяцев (12 + 2 maintenance); поддерживаются три последние.
2. ⭐ Skew: kubelet до 3 минорных старше apiserver и никогда не новее; kubectl ±1;
   controller-manager/scheduler — не новее и максимум на 1 старше.
3. Порядок: apiserver → CM/scheduler → kubelet → kube-proxy; поэтому ноды — последними.
4. Обновление — одна минорная за раз, как проект: план → pre-checks → бэкап → CP → аддоны → ноды.
5. ⭐ Устаревшие API ищут двумя способами: метрика `apiserver_requested_deprecated_apis`
   (кто ходит) и pluto по git/Helm (что сломается при деплое). kubent устарел.
6. Объекты в etcd конвертируются сами — ломаются манифесты, чарты и клиенты.
7. Матрица аддонов важнее всего: Envoy Gateway v1.9 (≤ 1.36) блокирует переход на 1.37.
8. PDB с `ALLOWED DISRUPTIONS = 0` вешает drain; single-replica + `minAvailable: 1` — вечно.
9. Даунгрейда нет: откат — снапшот etcd (долго) или blue/green кластер (быстро).
10. Managed обновляет control plane, но устаревшие API, аддоны и ноды — на тебе.
11. kured перезагружает ноды после патчей ядра по одной, в окно и с drain.
12. Сертификаты kubeadm живут год; `kubeadm upgrade` продлевает их; после `renew` —
    рестарт static pod'ов.
13. ⭐ Аудит пишет apiserver; первое совпавшее правило побеждает; секреты — только
    `Metadata`; ответ «кто удалил» — `user.username` + `impersonatedUser` + `userAgent`.
14. Blue/green кластер с GitOps превращает обновление из события в рутину.

---

## Задачи

> ⭐ Вопросы собеса: *«Как вы обновляете кластер?»* и *«Кто удалил deployment?»* —
> нужно показать процесс (план, проверки, откат), а не пересказать `kubeadm upgrade`.

---

### Блок A. Теория

**A1.** Сколько минорных релизов Kubernetes выходит в год и сколько живёт каждый?
Что такое maintenance mode?

<details><summary>Ответ</summary>

Около трёх минорных в год (примерно раз в 4 месяца). Каждая поддерживается
~14 месяцев: 12 месяцев стандартной поддержки и 2 месяца maintenance mode, когда
выпускают только исправления CVE, зависимостей и критичных ошибок.

</details>

**A2.** Какие ветки поддерживаются в сентябре 2026? Почему кластер на 1.34 — срочная задача?

<details><summary>Ответ</summary>

1.37, 1.36, 1.35 официально; 1.34 в maintenance mode до 27.10.2026. Кластер
на 1.34 через месяц останется без патчей безопасности, а обновляться до актуальной
придётся в несколько шагов по одной минорной.

</details>

**A3.** ⭐ Сформулируй version skew policy для kubelet, kubectl, controller-manager/scheduler
и для нескольких kube-apiserver в HA.

<details><summary>Ответ</summary>

kubelet и kube-proxy — не новее apiserver и старше максимум на 3 минорные;
controller-manager, scheduler, CCM — не новее apiserver и старше максимум на 1;
kubectl — ±1 минорная; между kube-apiserver в HA — не больше 1 минорной.

</details>

**A4.** ⭐ В каком порядке обновляются компоненты и почему ноды — последними?

<details><summary>Ответ</summary>

kube-apiserver → controller-manager/scheduler/CCM → kubelet → kube-proxy.
Ноды последние, потому что kubelet не может быть новее apiserver.

</details>

**A5.** Почему нельзя обновить кластер с 1.35 сразу на 1.37?

<details><summary>Ответ</summary>

kubeadm и managed разрешают только +1 минорную; к тому же apiserver между
соседними версиями должен уметь работать с данными и компонентами предыдущей.
1.35 → 1.36 → 1.37 — два отдельных обновления.

</details>

**A6.** Что читают перед обновлением минорной версии? Что такое Urgent Upgrade Notes?

<details><summary>Ответ</summary>

Пост релиза с разделом Deprecations and removals, Sneak Peek, CHANGELOG
минорной версии. Urgent Upgrade Notes — раздел changelog с изменениями, которые
требуют действий **до** обновления.

</details>

**A7.** ⭐ Почему удаление API ломает манифесты в git, но не объекты, уже лежащие в etcd?

<details><summary>Ответ</summary>

apiserver хранит объекты в своём формате и отдаёт их в любой поддерживаемой
версии API — после удаления старой версии объект просто читается через новую.
Клиенты же (манифесты, чарты, скрипты) явно запрашивают старую версию,
и apiserver отвечает, что такой версии нет.

</details>

**A8.** Что показывает метрика `apiserver_requested_deprecated_apis` и чего она не видит?

<details><summary>Ответ</summary>

Какие устаревшие группы/версии/ресурсы реально запрашивались с момента
старта apiserver и в какой версии их удалят (`removed_release`). Не видит манифесты
в git и Helm, которые давно не применялись, и не говорит, **кто** ходит (это — аудит).

</details>

**A9.** Что умеет pluto? Почему в старых гайдах советуют kubent, а сейчас — нет?

<details><summary>Ответ</summary>

pluto ищет устаревшие API в файлах, в манифестах Helm-релизов и в объектах
кластера против целевой версии (`--target-versions`). kubent фактически не поддерживается:
правила только до 1.32 и только nightly-сборки; как альтернативу называют kubepug.

</details>

**A10.** Зачем нужен `kubectl convert` и как его поставить?

<details><summary>Ответ</summary>

Переписать манифест со старой версии API на новую
(`kubectl convert -f old-cronjob.yaml --output-version batch/v1`). Это отдельный плагин:
бинарник `kubectl-convert` с dl.k8s.io кладут в `PATH`. Он умеет только версии, код
конвертации которых ещё есть в его сборке; давно удалённые (HPA `v2beta2` в 1.36) — руками.

</details>

**A11.** ⭐ Что такое матрица совместимости аддонов? Приведи пример аддона, который
блокирует обновление на 1.37.

<details><summary>Ответ</summary>

Таблица «аддон → текущая → целевая версия кубера → поддерживает ли обе».
Пример: Envoy Gateway v1.9 поддерживает 1.33–1.36 — пока нет версии с 1.37,
переход на 1.37 блокирован.

</details>

**A12.** Почему Cluster Autoscaler обновляют вместе с кластером?

<details><summary>Ответ</summary>

Минорная версия Cluster Autoscaler соответствует минорной Kubernetes: он
использует код планировщика той же версии, чтобы правильно предсказывать размещение.

</details>

**A13.** Чем обновление нод in-place отличается от surge (замены)? Где что применяют?

<details><summary>Ответ</summary>

In-place: drain → обновить пакеты на той же машине → uncordon (kubeadm,
kubespray, железо). Surge: поднять новые ноды нужной версии, перевезти поды и удалить
старые (managed node groups, Karpenter drift, Cluster API). Surge проще откатывать
и не копит дрейф, но временно требует лишней ёмкости.

</details>

**A14.** ⭐ Как PDB влияет на `kubectl drain`? Какая конфигурация PDB блокирует drain навсегда?

<details><summary>Ответ</summary>

drain вытесняет поды через Eviction API, который уважает PDB: если бюджет
не позволяет, вытеснение повторяется, пока не станет можно. Одна реплика
с `minAvailable: 1` (или `maxUnavailable: 0`) не позволит никогда.

</details>

**A15.** Почему `--disable-eviction` — плохой способ «протолкнуть» drain?

<details><summary>Ответ</summary>

Он удаляет поды напрямую, в обход PDB: можно одновременно положить все реплики
сервиса. Правильно — временно добавить реплику или согласовать простой.

</details>

**A16.** ⭐ Как откатить неудачное обновление кластера? Есть ли даунгрейд в kubeadm?

<details><summary>Ответ</summary>

Даунгрейда нет. При сбое во время `upgrade apply` kubeadm сам возвращает манифесты
(бэкапы — в `/etc/kubernetes/tmp`). Если обновление прошло, но всё плохо, — восстановление
снапшота etcd и старых версий компонентов (долго, репетировать заранее). Надёжный
способ — blue/green: вернуть трафик на старый кластер.

</details>

**A17.** Что берёт на себя облако при managed-обновлении, а что остаётся тебе?

<details><summary>Ответ</summary>

Облако обновляет control plane и свои встроенные компоненты. Тебе остаются
устаревшие API в манифестах, совместимость аддонов, обновление нод и node pool'ов,
PDB и окна работ.

</details>

**A18.** Что такое EKS extended support и почему его стоит избегать?

<details><summary>Ответ</summary>

Платное продление поддержки версии ещё на 12 месяцев после 14 стандартных;
control plane стоит $0.60/ч вместо $0.10/ч и включается по умолчанию. Это штраф
за необновлённый кластер.

</details>

**A19.** Зачем нужен kured и как он перезагружает ноды безопасно?

<details><summary>Ответ</summary>

Чтобы после патчей ядра ноды перезагружались автоматически и по одной.
kured проверяет sentinel-файл, берёт лок, делает cordon и drain с учётом PDB,
перезагружает, делает uncordon; уважает окно, дни недели и может ждать, пока горят алерты.

</details>

**A20.** Какие сертификаты kubeadm живут год, какие — 10 лет? Почему регулярно
обновляемый кластер не упирается в сертификаты?

<details><summary>Ответ</summary>

Год — листовые сертификаты (apiserver, etcd, front-proxy-client, kubeconfig'и
control plane); 10 лет — CA. `kubeadm upgrade apply/node` продлевает листовые
автоматически, поэтому кластер, обновляемый хотя бы раз в год, в срок не упирается.

</details>

**A21.** Что нужно сделать после `kubeadm certs renew all`?

<details><summary>Ответ</summary>

Перезапустить static pod'ы control plane (вынести манифест из
`/etc/kubernetes/manifests` и вернуть через ~20 секунд) и обновить свой kubeconfig
из `/etc/kubernetes/admin.conf`.

</details>

**A22.** ⭐ Какие уровни аудита бывают и как проверяются правила политики?

<details><summary>Ответ</summary>

`None`, `Metadata`, `Request`, `RequestResponse`. Правила проверяются сверху
вниз, применяется первое совпавшее — поэтому исключения и секреты вверху, catch-all внизу.

</details>

**A23.** Почему для Secret нельзя ставить уровень `Request` или `RequestResponse`?

<details><summary>Ответ</summary>

Тело запроса и ответа для Secret содержит сами секреты (в base64), и они окажутся
в лог-хранилище, куда доступ шире, чем к кластеру.

</details>

**A24.** Почему `kubectl get events` не отвечает на вопрос «кто удалил»?

<details><summary>Ответ</summary>

В events нет пользователя, они описывают действия контроллеров
и хранятся около часа.

</details>

**A25.** Что такое blue/green миграция кластера и когда она лучше in-place обновления?

<details><summary>Ответ</summary>

Поднимается новый кластер целевой версии из кода, в него из того же GitOps-репозитория
раскатываются аддоны и приложения, трафик постепенно переключается DNS или балансировщиком.
Лучше, когда нужно прыгнуть через несколько минорных, сменить CNI/ОС/регион или
иметь быстрый откат.

</details>

---

### Блок B. «Что произойдёт»

```text:no-line-numbers
# B1
kube-apiserver: 1.37; kubelet на нодах: 1.33
```
Вопрос: поддерживается ли такая конфигурация? Что делать?

<details><summary>Ответ</summary>

Нет: kubelet может отставать максимум на 3 минорные (1.34–1.37). Нужно обновить
ноды хотя бы до 1.34, а лучше — довести до 1.37; и не пускать apiserver так далеко вперёд.

</details>

```text:no-line-numbers
# B2
kubectl в CI: 1.34; кластер обновили до 1.37
```
Вопрос: что может случиться?

<details><summary>Ответ</summary>

kubectl 1.34 вне поддерживаемого диапазона (±1): возможны ошибки `apply`,
непонимание новых полей, некорректный diff. Обновить kubectl в образе CI.

</details>

```bash
# B3
kubectl get pdb -n shop
# NAME   MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS
# api    1               N/A               0
kubectl get deploy api -n shop    # READY 1/1
kubectl drain node2 --ignore-daemonsets --delete-emptydir-data
```
Вопрос: чем закончится drain?

<details><summary>Ответ</summary>

drain будет бесконечно повторять вытеснение с ошибкой о нарушении disruption budget
(или упадёт по `--timeout`). Нужно поднять реплики до 2+ или договориться о простое.

</details>

```text:no-line-numbers
# B4
В git лежит HPA с apiVersion: autoscaling/v2beta2; кластер 1.36.
```
Вопрос: что будет при `kubectl apply`? А с объектом HPA, созданным пять лет назад?

<details><summary>Ответ</summary>

`apply` упадёт: `autoscaling/v2beta2` удалена в 1.26 — `no matches for kind`.
Старый объект HPA в кластере цел: apiserver отдаёт его через `autoscaling/v2`.

</details>

```text:no-line-numbers
# B5
Envoy Gateway v1.9.1 (поддерживает 1.33–1.36); кластер 1.36; план — 1.37 в пятницу.
```
Вопрос: что делать с планом?

<details><summary>Ответ</summary>

Перенести обновление: сначала дождаться версии Envoy Gateway с поддержкой 1.37,
обновить её на 1.36 и проверить; только потом — кластер.

</details>

```bash
# B6
sudo kubeadm certs renew all
# и больше ничего
```
Вопрос: что будет через некоторое время?

<details><summary>Ответ</summary>

Сертификаты на диске новые, но компоненты control plane продолжают использовать
старые, загруженные в память; когда старые истекут — ошибки x509. Нужен рестарт
static pod'ов и обновление kubeconfig.

</details>

```yaml
# B7
rules:
  - level: Metadata
  - level: None
    users: ["system:kube-proxy"]
    verbs: ["watch"]
```
Вопрос: будет ли подавлен шум от kube-proxy?

<details><summary>Ответ</summary>

Нет: первое правило `Metadata` совпадает со всем, до `None` дело не дойдёт.
Исключения ставят выше catch-all.

</details>

```json
// B8
{"verb":"delete","user":{"username":"kubernetes-admin"},
 "impersonatedUser":{"username":"system:serviceaccount:ci:deployer"},
 "objectRef":{"resource":"deployments","namespace":"prod","name":"api"},
 "responseStatus":{"code":200}}
```
Вопрос: кто удалил deployment?

<details><summary>Ответ</summary>

Запрос выполнил `kubernetes-admin` через имперсонацию сервисного аккаунта
`ci:deployer`. Реальный автор — владелец admin-учётки; нужно выяснить, кто ей пользовался
(`sourceIPs`, `userAgent`), и перестать раздавать admin.

</details>

```text:no-line-numbers
# B9
kured поставлен без настроек; во вторник в 14:00 вышел патч ядра.
```
Вопрос: что произойдёт?

<details><summary>Ответ</summary>

Без окна kured в течение часа начнёт перезагружать ноды прямо днём, по одной;
с PDB приложения должны пережить, но в пик это риск. Нужно задать окно и блокировку по алертам.

</details>

```text:no-line-numbers
# B10
EKS 1.33, сентябрь 2026; обновлять «некогда».
```
Вопрос: что видно в счёте и что будет дальше?

<details><summary>Ответ</summary>

Версия в extended support: control plane стоит в 6 раз дороже. После окончания
extended AWS обновит control plane принудительно, а ноды и аддоны останутся старыми —
авария вероятна.

</details>

---

### Блок C. Практика

#### C1. 🔑 Календарь версий
Открой kubernetes.io/releases и составь таблицу: ветка, последний патч, начало
maintenance, EOL. Отметь, до какой даты нужно уйти с 1.35.

#### C2. 🔑 Skew своими глазами
В kind-кластере посмотри версии компонентов: `kubectl version`,
`kubectl get nodes -o wide`, образы static pod'ов в `kube-system`.
Для каждого компонента запиши допустимый диапазон при apiserver 1.37.

#### C3. 🔑 Устаревшие API
1. Создай каталог `legacy/` с HPA `autoscaling/v2beta2` и CronJob `batch/v1beta1`.
2. Прогони `pluto detect-files -d legacy/ --target-versions k8s=v1.36.0`.
3. Попробуй `kubectl apply -f legacy/` — запиши ошибку.
4. Поставь `kubectl-convert`, переведи CronJob на `batch/v1`; то же с HPA `v2beta2` — если плагин
   откажется, перепиши руками по Deprecated API Migration Guide и объясни почему.

<details><summary>Ответ</summary>

Ошибка вида `no matches for kind "HorizontalPodAutoscaler" in version "autoscaling/v2beta2"`;
CronJob после `kubectl convert` применяется как `batch/v1`. Плагин 1.36 не знает
`autoscaling/v2beta2` (код конвертации удалён) — HPA переписывают руками на `autoscaling/v2`
(`metrics[].resource.target` вместо `targetAverageUtilization`).

</details>

#### C4. Метрика apiserver
Выполни `kubectl get --raw /metrics | grep apiserver_requested_deprecated_apis`.
Если пусто — объясни почему. Найди в метрике метку `removed_release`.

<details><summary>Ответ</summary>

Пусто, если никто не запрашивал устаревшие API с момента старта apiserver —
например, в свежем kind-кластере. После `apply` из C3 (до удаления версии) там появились бы строки.

</details>

#### C5. 🔑 Матрица аддонов
Для своего стенда (Envoy Gateway, metrics-server, KEDA, Calico/Cilium при наличии)
составь таблицу «аддон → текущая версия → поддерживаемые версии k8s → блокирует ли 1.37».

#### C6. 🔑 PDB и drain
1. Deployment с 1 репликой и PDB `minAvailable: 1` — попробуй `kubectl drain` воркера
   с `--timeout=60s`, запиши ошибку.
2. Переделай на 3 реплики и `maxUnavailable: 1`, повтори drain и понаблюдай за подами.
3. `kubectl uncordon` и проверь, что нода снова принимает поды.

<details><summary>Ответ</summary>

В первом случае — ошибка `Cannot evict pod as it would violate the pod's disruption
budget` и выход по таймауту; во втором поды вытесняются по одному.

</details>

#### C7. 🔑 Аудит в kind
Пройди мини-лабу из конспекта: включи аудит, удали deployment от имени SA
и через имперсонацию, найди оба события `jq`-запросом.

#### C8. Секреты в аудите
Создай Secret и прочитай его. Найди в логе события `get secrets` и убедись,
что тела секрета нет. Затем (только на стенде!) поменяй уровень для secrets на
`RequestResponse`, пересоздай кластер и посмотри, что попало в лог.

#### C9. etcd-снапшот в kind
Сними снапшот через под etcd:
```bash
kubectl -n kube-system exec etcd-devops-control-plane -- etcdctl \
  --endpoints=https://127.0.0.1:2379 --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt --key=/etc/kubernetes/pki/etcd/server.key \
  snapshot save /var/lib/etcd/snap.db
docker cp devops-control-plane:/var/lib/etcd/snap.db ./snap.db
```
Проверь его размер и объясни, почему бэкап внутри контейнера ноды — не бэкап.

<details><summary>Ответ</summary>

Снапшот лежит на той же «машине», что и etcd: потеря ноды — потеря бэкапа.
Бэкап должен уезжать вне кластера и проверяться восстановлением.

</details>

#### C10. 🔑 Runbook
Заполни шаблон runbook из конспекта для перехода своего стенда 1.35 → 1.36:
пункты подготовки, критерии отката, ответственные. Сохрани в git рядом с манифестами.

#### C11. Blue/green в kind (со звёздочкой)
Подними два кластера: `blue` на `kindest/node:v1.35.8` и `green` на `kindest/node:v1.36.4`.
Примени в оба одни и те же манифесты из git, сравни `kubectl get` и опиши, чем было бы
переключение трафика в проде.

#### C12. kured (со звёздочкой)
Прочитай values чарта kured и выпиши настройки окна перезагрузок, блокировки по
алертам и по подам. Объясни, почему в kind поставить его можно, а проверить по-настоящему — нет.

<details><summary>Ответ</summary>

kured в kind запустится, но перезагрузить «ноду»-контейнер как реальный сервер
он не может — проверяют его на ВМ или облачных нодах.

</details>

---

### Блок D. Инциденты

**D1.** После обновления control plane до 1.37 весь входящий трафик пропал,
поды приложений живы. Где искать?

<details><summary>Ответ</summary>

Аддон входа несовместим с новой версией: `kubectl -n envoy-gateway-system get pods`,
логи контроллера и прокси, условия Gateway/HTTPRoute. Решение — версия аддона
с поддержкой 1.37; урок — матрица аддонов до обновления.

</details>

**D2.** Через неделю после обновления кластера пайплайн падает с
`no matches for kind "X" in version "Y"`. Что случилось и как предотвратить?

<details><summary>Ответ</summary>

В чарте или манифесте используется удалённая версия API; при обновлении
кластера это не проверили. Исправить `apiVersion` (`kubectl convert`), добавить
`pluto detect-files` в CI и `pluto detect-helm` в pre-checks.

</details>

**D3.** `kubectl drain` висит 40 минут. Алгоритм разбора.

<details><summary>Ответ</summary>

`kubectl get pdb -A` — у кого `ALLOWED DISRUPTIONS = 0`; `kubectl get pods -o wide`
на ноде — какие поды остались; поды без контроллера, `emptyDir`, finalizers; вытесненный
под не может запланироваться из-за ресурсов/affinity. Решать по причине, а не
`--disable-eviction`.

</details>

**D4.** Утром `kubectl` отвечает `x509: certificate has expired or is not yet valid`,
кластер kubeadm не обновляли 13 месяцев. Что делать?

<details><summary>Ответ</summary>

Истекли листовые сертификаты: `kubeadm certs check-expiration` на control plane,
`kubeadm certs renew all`, рестарт static pod'ов, обновить `admin.conf` и kubeconfig'и.
Потом — обновить кластер и поставить алерт на срок сертификатов.

</details>

**D5.** После `kubeadm certs renew all` через пару дней часть компонентов
перестала общаться с apiserver. В чём ошибка?

<details><summary>Ответ</summary>

После renew не перезапустили static pod'ы control plane — они работали
со старыми сертификатами в памяти, пока те не истекли.

</details>

**D6.** В проде исчез deployment `payments`. Руководство спрашивает, кто это сделал.
Твои действия, если аудит включён? А если нет?

<details><summary>Ответ</summary>

С аудитом: `jq` по событиям `delete` с `objectRef.name=="payments"` —
`user.username`, `impersonatedUser`, `sourceIPs`, `userAgent`, время; если это
ArgoCD — искать коммит, убравший объект из git. Без аудита: history в GitOps и CI,
логи пайплайнов, bash history на бастионе — и включить аудит.

</details>

**D7.** Аудит-лог растёт на 20 ГБ в сутки, apiserver ест память. Что поправить в политике?

<details><summary>Ответ</summary>

Шум (watch системных компонентов, health-проверки, events) — в `None`;
`RequestResponse` — только для изменений важных ресурсов; остальное — `Metadata`;
`omitStages: ["RequestReceived"]`; ротация через `--audit-log-max*`.

</details>

**D8.** kured перезагрузил две ноды одновременно в пик трафика, часть сервисов
легла. Что было настроено не так?

<details><summary>Ответ</summary>

Не было окна (`--start-time/--end-time`), `--concurrency` больше 1
или два экземпляра kured; не было блокировки по алертам и PDB у сервисов.

</details>

**D9.** После обновления нод kubelet не стартует на части серверов с сообщением
о cgroup v1. Причина и варианты решения?

<details><summary>Ответ</summary>

С 1.35 kubelet по умолчанию отказывается работать на cgroup v1 (`failCgroupV1: true`).
Правильно — обновить ОС нод до cgroup v2; временно — `failCgroupV1: false` в конфиге kubelet.

</details>

**D10.** Обновление на 1.37 прошло, но через час выросли 5xx, причину быстро найти
не удаётся. Как откатываться в двух архитектурах: один кластер и blue/green?

<details><summary>Ответ</summary>

Один кластер: сначала попытаться исправить вперёд (аддоны, конфигурация);
если нельзя — восстановление снапшота etcd и старых версий компонентов по отрепетированному
плану. Blue/green: вернуть вес трафика на старый кластер за минуты и разбираться спокойно.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Как вы обновляете кластер Kubernetes? *(расскажи процесс целиком)*

<details><summary>Ответ</summary>

Регулярно, по одной минорной: читаю changelog, ищу устаревшие API (pluto + метрика),
проверяю матрицу аддонов, обновляю staging; в проде — pre-checks, снапшот etcd,
control plane, аддоны, ноды по одной с drain и PDB, post-checks; всё по runbook с
критериями отката.

</details>

**2.** Что такое version skew policy?

<details><summary>Ответ</summary>

Правила допустимой разницы версий: kubelet до 3 минорных старше apiserver,
kubectl ±1, controller-manager/scheduler — не новее и до 1 старше.

</details>

**3.** Как найти устаревшие API перед обновлением?

<details><summary>Ответ</summary>

Метрика `apiserver_requested_deprecated_apis`, аудит (`k8s.io/deprecated`),
pluto по git и Helm-релизам, предупреждения kubectl.

</details>

**4.** Что может заблокировать обновление, кроме самого кубера?

<details><summary>Ответ</summary>

Аддоны без поддержки целевой версии (Gateway, CNI, CSI, операторы), PDB, мешающие drain,
старые ОС нод (cgroup v1), устаревшие API в чартах.

</details>

**5.** Как обновить ноды без простоя?

<details><summary>Ответ</summary>

Несколько реплик с anti-affinity, PDB, drain по одной ноде (или surge-замена),
readiness-пробы и graceful shutdown у приложений.

</details>

**6.** ⭐ Как откатить неудачное обновление кластера?

<details><summary>Ответ</summary>

Даунгрейда нет: снапшот etcd и старые версии — долго; надёжно — blue/green кластер
с переключением трафика.

</details>

**7.** Чем отличается обновление managed-кластера от kubeadm?

<details><summary>Ответ</summary>

Control plane обновляет облако по кнопке или каналу; остальное — как у kubeadm:
API, аддоны, ноды, PDB; плюс ограничения и цена провайдера.

</details>

**8.** Как вы патчите ОС нод?

<details><summary>Ответ</summary>

`unattended-upgrades` + kured с окном и блокировками — или замена нод свежим образом
(Karpenter `expireAfter`, иммутабельные ОС).

</details>

**9.** Что будет, если не продлевать сертификаты kubeadm?

<details><summary>Ответ</summary>

Через год истекут листовые сертификаты, и control plane перестанет работать
(ошибки x509); регулярные `kubeadm upgrade` продлевают их автоматически.

</details>

**10.** ⭐ Как узнать, кто удалил объект в кластере?

<details><summary>Ответ</summary>

По аудит-логу apiserver: событие `delete` на объект, поля `user`, `impersonatedUser`,
`sourceIPs`, `userAgent`; при GitOps — дальше в историю git.

</details>

---

## 🎯 Чек-лист

- [ ] Знаю окно поддержки минорной (12 + 2 месяца) и текущие ветки
- [ ] ⭐ Могу по памяти рассказать version skew policy и порядок обновления компонентов
- [ ] Нахожу устаревшие API pluto и метрикой apiserver, умею `kubectl convert`
- [ ] Составил матрицу совместимости аддонов для своего стенда
- [ ] Видел, как PDB блокирует drain, и знаю, как это чинить правильно
- [ ] Знаю, чем откатывают обновление: снапшот etcd и blue/green
- [ ] Понимаю разницу managed и kubeadm-обновления, знаю про extended support
- [ ] Знаю, что делает kured и как настроить окно перезагрузок
- [ ] Умею проверить и продлить сертификаты kubeadm
- [ ] ⭐ Включал аудит в kind и находил, кто удалил deployment
- [ ] Заполнил runbook обновления для своего стенда
