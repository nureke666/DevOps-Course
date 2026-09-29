---
title: "02. GPU в Kubernetes: драйвер, device plugin, GPU Operator, разделение, DRA, метрики, деньги"
description: "Блок → AI/MLOps-инфраструктура → тема 02. GPU — самый дорогой ресурс кластера,"
---

# 02. GPU в Kubernetes: драйвер, device plugin, GPU Operator, разделение, DRA, метрики, деньги

> Блок → [AI/MLOps-инфраструктура](/mlops/) → тема 02. GPU — самый дорогой ресурс кластера,
> и он ведёт себя не как CPU: неделимый по умолчанию, со своим драйвером и своими поломками.
> Вопросы собеса: *«Как под получает GPU?»*, *«Time-slicing или MIG?»*, *«Что такое DRA?»*,
> *«Как не платить за простаивающие GPU-ноды?»*
>
> **После темы ты умеешь:** объяснить цепочку «драйвер → container toolkit → device plugin →
> `nvidia.com/gpu` → под»; поставить GPU Operator и знать, что он приносит; изолировать GPU-ноды
> taint'ами и выбирать GPU по меткам GFD; выбрать между time-slicing, MPS и MIG; объяснить DRA и его
> статус; собрать алерты на DCGM-метрики и XID; посчитать стоимость простоя и настроить пул с нулём нод;
> отработать GPU-планирование в kind **без GPU**. Версии — «проверь, сентябрь 2026».

---

## 🗺️ Карта темы

```text
  ┌─────────────────────────────── GPU-нода ────────────────────────────────┐
  │  GPU (VRAM 16–141 ГБ)                                                   │
  │    ▲ kernel-модуль nvidia  ◄── драйвер (на хосте или DaemonSet)         │
  │    ▲ libcuda, /dev/nvidia* ◄── NVIDIA Container Toolkit (runtime / CDI) │
  │  containerd ◄── kubelet ◄──gRPC── device plugin: «у меня 4 nvidia.com/gpu»
  │                   │                GFD: метки nvidia.com/gpu.product=…  │
  │                   │                DCGM exporter :9400/metrics ─────────┼──► Prometheus → Grafana, алерты
  │                   ▼                MIG manager: режет A100/H100 на части│
  │        node.status.allocatable: nvidia.com/gpu: 4                       │
  └───────────────────┼─────────────────────────────────────────────────────┘
                      ▼
  scheduler: под с limits nvidia.com/gpu: 1 + toleration + nodeAffinity по меткам GFD
                      │
  GPU Operator ставит и обновляет всё, что в рамке, одним Helm-чартом
  DRA (resource.k8s.io/v1): ResourceClaim «дай GPU ≥ 40 ГБ» — следующее поколение API
  Деньги: цена часа × часы простоя → пул с нулём нод (CA/Karpenter) + scale-to-zero сервинга
```text
---

## 1. GPU глазами эксплуатационщика

Девопсу важны четыре свойства GPU: **память** (модель + KV-кэш должны влезть — [01](/mlops/01-ml-systems-for-devops) §3),
**пропускная способность памяти** (для инференса LLM часто важнее «терафлопсов»), **поколение архитектуры**
(от него зависят версии CUDA и библиотек) и **поддержка MIG** (§6). NVLink — быстрая связь между GPU для
больших моделей и обучения.

| GPU | Память | Где встречается | Для чего обычно |
|-----|--------|-----------------|-----------------|
| T4 | 16 ГБ | AWS G4dn, Yandex `standard-v3-t4` | Недорогой инференс малых моделей |
| L4 / A10G | 24 ГБ | AWS G6 / G5 | Инференс 7–8B в INT8/INT4, эмбеддинги |
| L40S | 48 ГБ | AWS G6e | Инференс средних моделей |
| A100 | 40 / 80 ГБ | AWS P4d/P4de, Yandex `gpu-standard-v3` | Обучение и инференс, MIG |
| H100 / H200 | 80 / 141 ГБ | AWS P5 / P5e, P5en | Обучение, тяжёлый инференс, длинный контекст, MIG |

Первая команда на GPU-ноде — `nvidia-smi` (модель, драйвер, память, процессы; `-L` — список GPU и MIG-устройств с UUID).

---

## 2. Драйвер, CUDA и container toolkit

```text
  образ:  PyTorch / vLLM + CUDA runtime 12.x/13.x  ──►  libcuda.so, /dev/nvidia* (пробрасывает toolkit)
                                                   ──►  kernel-модуль nvidia на хосте (драйвер R580…R615)
```text
⭐ **Правило:** CUDA runtime живёт в образе, драйвер — на хосте, и **драйвер должен быть не старше
того, что требует CUDA образа**. Новый драйвер запускает приложения со старой CUDA; наоборот — нет
(кроме пакета forward compatibility для датацентровых GPU).

| Факт (проверь, сентябрь 2026) | |
|-------------------------------|---|
| Последний CUDA Toolkit | **13.4 Update 1**, ветка драйвера **R615** |
| Минимальный драйвер | CUDA 13.x — **≥ 580**; CUDA 12.x — **≥ 525** (minor version compatibility) |
| NVIDIA Container Toolkit | **v1.20.1** (19.09.2026): runtime `nvidia` для containerd/CRI-O, **CDI** (Container Device Interface — стандартное описание устройств для рантайма) |

```bash
nvidia-ctk runtime configure --runtime=containerd && systemctl restart containerd   # голая нода с драйвером
docker run --rm --gpus all nvidia/cuda:13.0.0-base-ubuntu24.04 nvidia-smi           # проверка (тег проверь)
```text
> ⚠️ Классика в логах: `CUDA driver version is insufficient for CUDA runtime version` — образ собран
> под CUDA новее, чем умеет драйвер ноды. Лечится драйвером или образом под старую CUDA, а не
> перезапуском пода. Версию CUDA образа записывают в паспорт модели.

---

## 3. ⭐ Как GPU попадает в под: device plugin и `nvidia.com/gpu`

**Device plugin** — DaemonSet, который регистрируется в kubelet по gRPC и сообщает: «на этой ноде
4 устройства `nvidia.com/gpu`». Kubelet добавляет их в `capacity`/`allocatable`, планировщик считает
их как любой ресурс, а при старте контейнера plugin говорит рантайму, какие GPU пробросить.
Версия **v0.20.1** (22.09.2026).

```yaml
apiVersion: v1
kind: Pod
metadata: { name: cuda-check }
spec:
  restartPolicy: Never
  containers:
    - name: cuda
      image: nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda12.5.0-ubuntu22.04
      resources:
        limits: { nvidia.com/gpu: 1 }    # ⭐ только limits; requests = limits автоматически
  tolerations: [{ key: nvidia.com/gpu, operator: Exists, effect: NoSchedule }]
  nodeSelector: { nvidia.com/gpu.product: NVIDIA-L4 }   # метка GFD (§5); точное значение — на ноде
```text
| Правило extended-ресурсов | Следствие |
|---------------------------|-----------|
| Только целые числа | `nvidia.com/gpu: 0.5` — ошибка валидации; дробить — только через §6 |
| **Нет overcommit** | Если указаны и requests, и limits — они обязаны быть равны |
| Устройство отдаётся контейнеру целиком | Под занял GPU и простаивает — GPU простаивает тоже |
| Считается в ResourceQuota | `requests.nvidia.com/gpu: "4"` на namespace ([../Kubernetes/09_probes_resources.md](/kubernetes/09-probes-resources) §7) |

```bash
kubectl describe node gpu-1 | grep -A8 -E "^Capacity|^Allocated"   # nvidia.com/gpu: 4 / занято 3
kubectl get nodes -o custom-columns='NODE:.metadata.name,GPU:.status.allocatable.nvidia\.com/gpu'
```text
> ⚠️ **Грабля безопасности** из README device plugin: под без запроса GPU из образа NVIDIA
> (`NVIDIA_VISIBLE_DEVICES=all`) на ноде с дефолтным runtime `nvidia` может увидеть **все GPU ноды**.
> Защита: taint, запрет выбора GPU через переменную (проверь `accept-nvidia-visible-devices-envvar-when-unprivileged`, `deviceListStrategy`), CDI.

---

## 4. ⭐ GPU Operator: весь стек одним чартом

Руками на каждой ноде: драйвер, toolkit, настройка containerd, device plugin, мониторинг, MIG.
**GPU Operator** делает это DaemonSet'ами и держит версии в CRD `ClusterPolicy`.

| Компонент (**v26.7.1**, 23.09.2026) | Версия | Что делает |
|-------------------------------------|--------|------------|
| Node Feature Discovery | v0.19 | Метка `feature.node.kubernetes.io/pci-10de.present=true` на нодах с GPU NVIDIA |
| Driver DaemonSet | по умолчанию **595.91.07**; ветки R580–R615 | Ставит драйвер в контейнере — на хост ничего руками |
| Container Toolkit / Device Plugin | v1.20.1 / v0.20.1 | Runtime и CDI / `nvidia.com/gpu`, time-slicing, MPS, MIG-ресурсы |
| GPU Feature Discovery (GFD) | v0.20.1 | Метки ноды: модель, память, драйвер, CUDA |
| DCGM + DCGM Exporter | 4.6.1 / 4.6.1-4.8.4 | Метрики GPU для Prometheus (§8) |
| MIG Manager / Validator | v0.15.1 / — | Переразметка MIG по метке / проверка цепочки CUDA-тестом |
| DRA Driver (опционально, с 26.7.0) | v0.5.0 | Выдача GPU через DRA (§7) |

Поддержка: Kubernetes **1.33–1.37** (EKS, GKE, AKS, RKE2, k3s, OpenShift…), containerd 2.0–2.3,
Ubuntu 22.04–26.04, RHEL 8–10. Новое в 26.7.1: лимит памяти GPU на контейнер через
`NVIDIA_GPU_MEMORY_REQUEST` / `NVIDIA_GPU_MEMORY_LIMIT` (драйвер R615+) — проверь, прежде чем полагаться.

```bash
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia && helm repo update
kubectl create ns gpu-operator
kubectl label ns gpu-operator pod-security.kubernetes.io/enforce=privileged   # операнды привилегированные
helm install gpu-operator nvidia/gpu-operator --version v26.7.1 -n gpu-operator --wait
#  --set driver.enabled=false --set toolkit.enabled=false   ← если драйвер и toolkit уже в образе ноды
kubectl -n gpu-operator get pods                 # driver → toolkit → device-plugin → gfd → dcgm-exporter → validator
kubectl get clusterpolicy -o jsonpath='{.items[0].status.state}'   # ready
kubectl label node cpu-1 nvidia.com/gpu.deploy.operands=false       # не ставить операнды на эту ноду
```text
**Порядок старта новой ноды** (это часть холодного старта): NFD находит GPU → driver DaemonSet грузит
модуль (минуты, если драйвер ставится контейнером) → toolkit → device plugin публикует `nvidia.com/gpu`.
Поэтому в облаке берут образ ноды **с драйвером** и выключают `driver.enabled`.

**Managed-облака** (проверь): EKS — accelerated AMI с драйвером и toolkit (ставишь device plugin или
Operator без драйвера/toolkit), EKS Auto Mode — GPU из коробки; GKE — драйвер ставит сам и сам вешает taint
`nvidia.com/gpu`; Yandex Managed Kubernetes — группа узлов с GPU с драйверами и CUDA или без них (тогда —
GPU Operator); on-prem/kubeadm — GPU Operator целиком.

---

## 5. Планирование: taints, метки GFD, affinity, квоты

Рецепт тот же, что для любых выделенных нод ([../Kubernetes/19_scheduling.md](/kubernetes/19-scheduling)
§2, §5): **taint не пускает чужих, affinity притягивает своих.**

```bash
kubectl taint nodes gpu-1 nvidia.com/gpu=true:NoSchedule   # соглашение: ключ = имя ресурса
```text
⭐ Ключ `nvidia.com/gpu` выбран не случайно: admission-плагин **ExtendedResourceToleration** сам добавляет
toleration `nvidia.com/gpu:Exists:NoSchedule` каждому поду, который **запрашивает** `nvidia.com/gpu`.
В GKE он включён; в своём кластере — `--enable-admission-plugins=…,ExtendedResourceToleration` у kube-apiserver.

| Метка GFD | Пример | Для чего |
|-----------|--------|----------|
| `nvidia.com/gpu.product` | `NVIDIA-L4`, `A100-SXM4-80GB` | Выбрать модель GPU |
| `nvidia.com/gpu.memory` | `23034` (МиБ) | «Нужно ≥ 40 ГБ» через `Gt` |
| `nvidia.com/gpu.count`, `nvidia.com/gpu.family` | `8`, `hopper` | Многопроцессорные ноды, совместимость библиотек |
| `nvidia.com/cuda.driver-version.full` | `595.91.07` | Совместимость с CUDA образа (§2) |
| `nvidia.com/gpu.replicas`, `nvidia.com/mig.strategy` | `4`, `mixed` | Разделение GPU (§6) |

```yaml
# под сервинга: GPU с памятью больше 40 ГБ
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions: [{ key: nvidia.com/gpu.memory, operator: Gt, values: ["40000"] }]
---
apiVersion: v1
kind: ResourceQuota                     # команда: не больше 4 GPU на namespace
metadata: { name: gpu-quota, namespace: team-ml }
spec: { hard: { requests.nvidia.com/gpu: "4" } }
```text
Ещё: **PriorityClass** — прод-сервинг вытесняет эксперименты, а не наоборот; **очередь заданий**
обучения (например, Kueue) — Job ждёт свободной квоты, а не висит в `Pending`, будя автоскейлер.

---

## 6. ⭐ Разделение GPU: time-slicing, MPS, MIG

По умолчанию одна GPU = один контейнер. Маленькой модели на 2 ГБ целая H100 не нужна.

| | Time-slicing | MPS | MIG |
|---|--------------|-----|-----|
| Как работает | GPU по очереди отдаёт время процессам | Общий сервер CUDA-контекстов, процессы работают одновременно | GPU **аппаратно** режется на экземпляры |
| Изоляция памяти | ❌ один «съел» память — у соседей OOM | Частичная: равные доли памяти и вычислений | ✅ своя память, кэш, вычислители |
| Изоляция сбоев | ❌ | Слабая | ✅ |
| Какие GPU | Любые | Volta и новее; **не** вместе с MIG | A30, A100, H100, H200, B200 (не T4, L4, L40S, A10G) |
| DCGM-метрики по подам | ❌ не привязываются | Ограниченно | ✅ по MIG-устройствам |
| Гибкость | Любое число «реплик» | Число клиентов в конфиге | Фиксированные профили, переразметка — со сливом нагрузки |
| Когда | Dev, ноутбуки, CI, редкие запросы | Много мелких процессов инференса одной команды | Мультиарендный прод, предсказуемая задержка |

### Time-slicing — ConfigMap для device plugin

```yaml
apiVersion: v1
kind: ConfigMap
metadata: { name: time-slicing-config, namespace: gpu-operator }
data:
  any: |-
    version: v1
    flags:
      migStrategy: none
    sharing:
      timeSlicing:
        renameByDefault: false             # true → ресурс называется nvidia.com/gpu.shared
        failRequestsGreaterThanOne: false  # true → запрос 2 «долей» отклоняется (они не дают 2× мощности)
        resources:
          - name: nvidia.com/gpu
            replicas: 4                    # 1 физическая GPU → 4 nvidia.com/gpu
```text
```bash
kubectl patch clusterpolicies.nvidia.com/cluster-policy --type merge \
  -p '{"spec":{"devicePlugin":{"config":{"name":"time-slicing-config","default":"any"&#125;&#125;&#125;&#125;'
# без "default" конфиг выбирается меткой ноды nvidia.com/device-plugin.config=any
kubectl get node gpu-1 --show-labels | tr ',' '\n' | grep -E "gpu.replicas|gpu.product"
# nvidia.com/gpu.replicas=4, nvidia.com/gpu.product=NVIDIA-L4-SHARED; allocatable nvidia.com/gpu: 4
```text
MPS включается аналогично, секцией `sharing.mps` (`resources: [{name: nvidia.com/gpu, replicas: 10}]`).

### MIG — профили (проверь по документации NVIDIA для своей модели)

| GPU | Профили |
|-----|---------|
| A100 40GB | `1g.5gb`, `1g.10gb`, `2g.10gb`, `3g.20gb`, `4g.20gb`, `7g.40gb` |
| A100 80GB, H100 80GB | `1g.10gb`, `1g.20gb`, `2g.20gb`, `3g.40gb`, `4g.40gb`, `7g.80gb` |
| H200 141GB | `1g.18gb`, `1g.35gb`, `2g.35gb`, `3g.71gb`, `4g.71gb`, `7g.141gb` |

`Ng` — доля вычислителей из 7, `.XXgb` — память экземпляра; `1g` — до 7 экземпляров, `2g` — 3, `3g` — 2,
`4g` и `7g` — 1. Стратегия `migStrategy`: `single` — все экземпляры ноды одного профиля и выдаются как
`nvidia.com/gpu`; `mixed` — у каждого профиля свой ресурс (`nvidia.com/mig-1g.10gb: 1`).

```bash
# MIG Manager переразмечает GPU по метке ноды (нагрузку с GPU предварительно убирает)
kubectl label node gpu-1 nvidia.com/mig.config=all-1g.10gb --overwrite
kubectl get node gpu-1 -o jsonpath='{.metadata.labels.nvidia\.com/mig\.config\.state}'   # success
```text
---

## 7. DRA — Dynamic Resource Allocation

Device plugin умеет сказать только «на ноде 4 штуки». **DRA** — API в духе PVC для устройств: под
просит устройство **с нужными свойствами**, драйвер публикует, что есть на нодах, планировщик подбирает.

Объекты: **DeviceClass** (≈ StorageClass: класс `gpu.nvidia.com` и общие селекторы), **ResourceSlice**
(драйвер публикует устройства ноды с атрибутами — модель, память, NUMA), **ResourceClaim** (≈ PVC: заявка,
может быть общей для нескольких контейнеров), **ResourceClaimTemplate** (свой claim на каждый под).

```yaml
apiVersion: resource.k8s.io/v1
kind: ResourceClaimTemplate
metadata: { name: single-gpu, namespace: team-ml }
spec:
  spec:
    devices:
      requests:
        - name: gpu
          exactly: { deviceClassName: gpu.nvidia.com }   # + selectors на CEL по атрибутам драйвера
---
apiVersion: v1
kind: Pod
metadata: { name: trainer, namespace: team-ml }
spec:
  resourceClaims: [{ name: gpu, resourceClaimTemplateName: single-gpu }]
  containers:
    - name: main
      image: ubuntu:24.04
      command: ["sleep", "infinity"]
      resources: { claims: [{ name: gpu }] }            # вместо limits nvidia.com/gpu
  tolerations: [{ key: nvidia.com/gpu, operator: Exists, effect: NoSchedule }]
```text
| Версия Kubernetes | Статус DRA (проверь, сентябрь 2026) |
|-------------------|--------------------------------------|
| 1.34 (08.2025) | ⭐ Ядро — **GA**: `resource.k8s.io/v1` (DeviceClass, ResourceClaim, ResourceClaimTemplate, ResourceSlice), включено по умолчанию |
| 1.36 (04.2026) | **Prioritized list** — GA («дай H100, если нет — A100»); beta: extended resource support, partitionable devices (нарезка вроде MIG), device taints, binding conditions, health status |
| 1.37 (08.2026) | **Extended resource support — GA**: под с обычным `nvidia.com/gpu` может обслужить DRA-драйвер без device plugin; **device taints — GA**; partitionable devices — всё ещё beta; compatibility groups (MIG vs vGPU) — alpha |

**Драйвер NVIDIA для DRA** переехал в `kubernetes-sigs/dra-driver-nvidia-gpu`, версия **v0.5.0**
(19.08.2026); ставится отдельно или через GPU Operator 26.7 (Kubernetes ≥ 1.34.2, драйвер ≥ 580, CDI).
**ComputeDomains** (Multi-Node NVLink, системы GB200) — официально поддерживаются. **Выдача GPU** —
по README «можно попробовать, но официально не поддерживается»: GPU kubelet plugin в чарте выключен.

> 💡 Итог на сентябрь 2026: в проде — device plugin + time-slicing/MIG; DRA — изучать и пилотировать.
> Переход будет плавным: благодаря extended resource support манифесты с `nvidia.com/gpu: 1` менять не придётся.

---

## 8. ⭐ Мониторинг: DCGM exporter → Prometheus → Grafana

DCGM exporter (DaemonSet из GPU Operator, порт 9400) отдаёт метрики каждой GPU с метками `gpu`, `UUID`,
`modelName`, `Hostname`, а через kubelet PodResources API — `namespace`, `pod`, `container` (кроме time-slicing).

| Метрика (default-counters) | Что показывает | Как читать |
|----------------------------|----------------|------------|
| `DCGM_FI_DEV_GPU_UTIL` | % времени, когда работал хоть один kernel | ⚠️ 100% ≠ «загружена полностью»; для поиска простоя годится |
| `DCGM_FI_PROF_GR_ENGINE_ACTIVE` | Доля времени активности вычислительного движка | Точнее для «насколько занята» |
| `DCGM_FI_DEV_FB_USED` / `FB_FREE` | Память GPU, МиБ | vLLM резервирует память заранее — «90% занято» на нём норма |
| `DCGM_FI_DEV_GPU_TEMP`, `DCGM_FI_DEV_POWER_USAGE` | °C, Вт | Пороги — из спецификации модели GPU |
| `DCGM_FI_DEV_XID_ERRORS` | Код **последней** XID-ошибки (gauge) | ⭐ Любое изменение — событие для алерта |
| `DCGM_FI_DEV_UNCORRECTABLE_REMAPPED_ROWS`, `DCGM_FI_DEV_ROW_REMAP_FAILURE` | Деградация памяти | Кандидат на замену / тикет провайдеру |

```yaml
# PrometheusRule для kube-prometheus-stack (../Left/02_Monitoring/11_long_term_and_operator.md §7–9)
groups:
  - name: gpu
    rules:
      - alert: GPUIdleExpensive
        expr: avg_over_time(DCGM_FI_DEV_GPU_UTIL[2h]) < 5
        for: 1h
        annotations: { summary: "GPU &#123;&#123; $labels.gpu &#125;&#125; на &#123;&#123; $labels.Hostname &#125;&#125; простаивает — деньги горят" }
      - alert: GPUXidError
        expr: changes(DCGM_FI_DEV_XID_ERRORS[10m]) > 0
        annotations: { summary: "XID на &#123;&#123; $labels.Hostname &#125;&#125; — смотри таблицу XID" }
```text
| XID | Что значит (каталог NVIDIA) | Действие |
|-----|-----------------------------|----------|
| 13, 31 | Ошибка приложения / недопустимый доступ к памяти GPU | Перезапустить приложение; обычно баг кода или библиотек |
| 48, 64 | Некорректируемая ECC-ошибка / неудача переназначения строк памяти (63 — само переназначение, игнорировать) | Сброс GPU или перезагрузка, cordon ноды, в поддержку |
| 74 | Ошибка NVLink | В поддержку |
| **79** | GPU «отвалилась от шины» (недоступна по PCIe) | Перезагрузка машины: cordon + drain, тикет провайдеру |
| 94 / 95 | Ошибка памяти в одном приложении / затронуто несколько | 94 — перезапустить приложение; 95 — сброс GPU |

Дашборд Grafana — **12239** (NVIDIA DCGM Exporter). ServiceMonitor для exporter включается в values
GPU Operator (проверь ключ `dcgmExporter.serviceMonitor`) — с меткой `release`, которую ждёт Prometheus
([../Left/02_Monitoring/11_long_term_and_operator.md](/monitoring/11-long-term-and-operator) §9).
Деньги по GPU на команду — OpenCost ([../FinOps/04_kubecost_opencost.md](/finops/04-kubecost-opencost) §2).

---

## 9. ⭐ Деньги: стоимость простоя GPU

```text
 потери = цена GPU-ноды в час × часы простоя × число нод        (цены — порядок величины, us-east-1, проверь в калькуляторе)

 g6.xlarge (1 × L4)     ≈ $0,8/ч on-demand. Dev-нода 24/7, нужна 40 ч в неделю →
                          128 ч простоя × $0,8 ≈ $100 в неделю ≈ $440 в месяц — за одну ноду
 p5.48xlarge (8 × H100) ≈ $55/ч on-demand (spot заметно дешевле, но прерывается) →
                          24/7 ≈ $40 000 в месяц; одна забытая ночь (12 ч) ≈ $660
```text
| Рычаг | Как | Где подробнее |
|-------|-----|---------------|
| Пул GPU-нод с минимумом **0** | CA: min 0 у GPU-группы; Karpenter: отдельный NodePool с taint | [../FinOps/03_autoscaling_cost.md](/finops/03-autoscaling-cost) §4 |
| Scale-to-zero сервинга | KEDA по очереди → нода пустеет → автоскейлер её удаляет | [03](/mlops/03-model-serving), [../Kubernetes/25_ecosystem.md](/kubernetes/25-ecosystem) §6 |
| Разделение GPU для dev/CI | Time-slicing или MIG вместо GPU на каждого | §6 |
| Spot для обучения, расписание non-prod | Чекпоинты + retry Job; выключать ночью | [../FinOps/03_autoscaling_cost.md](/finops/03-autoscaling-cost) §5–6 |
| Правильный размер, квоты, showback | L4/L40S вместо H100 для малых моделей; ResourceQuota; отчёт по командам | §1, §5, [../FinOps/04_kubecost_opencost.md](/finops/04-kubecost-opencost) |

```yaml
# Karpenter: отдельный пул GPU-нод, который сам уходит в ноль
apiVersion: karpenter.sh/v1
kind: NodePool
metadata: { name: gpu-inference }
spec:
  template:
    spec:
      nodeClassRef: { group: karpenter.k8s.aws, kind: EC2NodeClass, name: gpu }   # AMI с драйвером
      requirements: [{ key: karpenter.k8s.aws/instance-family, operator: In, values: ["g6", "g6e"] }]
      taints: [{ key: nvidia.com/gpu, value: "true", effect: NoSchedule }]
  limits: { nvidia.com/gpu: "8" }             # потолок пула в GPU (проверь для своей версии)
  disruption: { consolidationPolicy: WhenEmpty, consolidateAfter: 10m }   # пустую GPU-ноду — удалить
```text
> ⚠️ Karpenter не считает ноду готовой, пока на ней не заработал **device plugin** (или GPU Operator):
> без него ноды создаются, а поды остаются `Pending`. Холодный старт новой GPU-ноды — ВМ + драйвер +
> образ на 10 ГБ + модель — это минуты ([03](/mlops/03-model-serving)).

---

## 10. GPU в облаках: AWS и Yandex Cloud

**AWS** (семейства с сайта AWS, сентябрь 2026): **G4dn** — T4; **G5** — A10G; **G6** — L4 (⭐ старт для
экспериментов); **G6e** — L40S; **G7 / G7e** — RTX PRO 4500 / 6000 Blackwell; **P4d / P4de** — A100
40 / 80 ГБ; **P5** — H100; **P5e / P5en** — H200; **P6 / P6e** — Blackwell (B200, B300) / GB200 NVL72;
**Inf2 / Trn2** — собственные чипы AWS (Inferentia2 / Trainium2) со своим SDK Neuron, не CUDA.

> ⚠️ У новых аккаунтов квоты на GPU-инстансы (Service Quotas для семейств G и P) обычно минимальные —
> запрашивай увеличение заранее. Региона AWS в Казахстане нет — [../Left/04_Cloud/08_aws_deep.md](/cloud/08-aws-deep) §10.

**Yandex Cloud** (документация Compute, проверь): `gpu-standard-v1`/`v2` — V100 32 ГБ; `gpu-standard-v3`/`v3i`
— A100 80 ГБ; `standard-v3-t4` / `standard-v3-t4i` — T4 16 ГБ / T4i 24 ГБ; `gpu-standard-v4` — платформа
со 141 ГБ на GPU. В Managed Kubernetes — группы узлов с GPU с драйверами или без (под GPU Operator);
есть пример time-slicing `yandex-cloud-examples/yc-mk8s-gpu-time-slicing`.

⚠️ Стартовый грант в РК GPU **не покрывает** ([../Left/04_Cloud/09_yandex_cloud.md](/cloud/09-yandex-cloud) §10),
а доступность GPU-платформ в `kz1` проверяй в консоли: в документации ru-kz перечислены зоны `kz1-a`
и `kz1-b`, хотя в регионе одна зона — похоже на шаблон. Из казахстанских провайдеров GPU Cloud заявляет
Kazteleport — [../Left/04_Cloud/10_kz_clouds.md](/cloud/10-kz-clouds) §3.

---

## 🧪 Мини-лаба: GPU-планирование в kind без GPU

Настоящей GPU нет, но планировщику всё равно: он видит только число в `allocatable`. Отрабатываем
taint'ы, метки, квоты и отказы по ресурсу — то, что в проде ломается чаще всего.

```yaml
# ~/labs/mlops/02/kind-gpu.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
  - role: worker                       # обычная нода
  - role: worker                       # «GPU-нода»
    labels: { nvidia.com/gpu.product: NVIDIA-L4, nvidia.com/gpu.memory: "23034" }
```text
```bash
mkdir -p ~/labs/mlops/02 && cd ~/labs/mlops/02
kind create cluster --name gpu --image kindest/node:v1.36.4 --config kind-gpu.yaml
kubectl taint nodes gpu-worker2 nvidia.com/gpu=true:NoSchedule
# «device plugin руками»: объявляем 4 GPU через статус ноды (способ из документации Kubernetes)
kubectl proxy --port 8001 &
curl -s -H "Content-Type: application/json-patch+json" -X PATCH \
  --data '[{"op":"add","path":"/status/capacity/nvidia.com~1gpu","value":"4"}]' \
  http://localhost:8001/api/v1/nodes/gpu-worker2/status >/dev/null
kubectl get nodes -o custom-columns='NODE:.metadata.name,GPU:.status.allocatable.nvidia\.com/gpu'
```text
```yaml
# gpu-pod.yaml
apiVersion: v1
kind: Pod
metadata: { name: gpu-ok }
spec:
  containers: [{ name: c, image: busybox:1.36, command: ["sleep", "3600"], resources: { limits: { nvidia.com/gpu: 1 } } }]
  tolerations: [{ key: nvidia.com/gpu, operator: Exists, effect: NoSchedule }]
  nodeSelector: { nvidia.com/gpu.product: NVIDIA-L4 }
```text
```bash
kubectl apply -f gpu-pod.yaml
sed -e 's/gpu-ok/gpu-too-many/' -e 's/gpu: 1/gpu: 5/' gpu-pod.yaml | kubectl apply -f -
sed -e 's/gpu-ok/gpu-no-tol/' -e '/tolerations/d' gpu-pod.yaml | kubectl apply -f -
kubectl run web --image=busybox:1.36 -- sleep 3600      # обычный под — на GPU-ноду попасть не должен
kubectl get pods -o wide                                 # gpu-ok → gpu-worker2, web → gpu-worker, два Pending
kubectl describe pod gpu-no-tol | tail -3                # untolerated taint {nvidia.com/gpu: true}
kubectl describe pod gpu-too-many | tail -3              # Insufficient nvidia.com/gpu
kubectl describe node gpu-worker2 | grep -A6 "Allocated resources"   # nvidia.com/gpu 1 1
```text
**Шаг 2 — квота.** Namespace `team-ml` с ResourceQuota `requests.nvidia.com/gpu: "2"` (§5): создай
там три пода по 1 GPU. Какой не создастся и что ответит API?

**Шаг 3 (по желанию) — fake-gpu-operator** Run:ai (v0.2.0, 01.07.2026): свой device plugin, метки,
Prometheus-метрики и даже DRA. Сними ручной ресурс (PATCH с `"op":"remove"`), повесь метку
`run.ai/simulated-gpu-node-pool=default` на `gpu-worker2` и поставь чарт
`oci://ghcr.io/run-ai/fake-gpu-operator/fake-gpu-operator --version 0.2.0` (проверь). Посмотри метки ноды и `/metrics`.

**Проверь себя:** почему `gpu-ok` запустился, хотя GPU нет? Что изменит ExtendedResourceToleration? Уборка: `kill %1; kind delete cluster --name gpu`.

---

## 11. Грабли

| Грабля | Что происходит | Как избежать |
|--------|----------------|--------------|
| GPU-нода без taint | Обычные поды занимают дорогую ноду, автоскейлер поднимает GPU-ноды под веб | Taint `nvidia.com/gpu` + toleration только у GPU-подов |
| Образ под CUDA новее драйвера | `CUDA driver version is insufficient…` | Драйвер ≥ требуемого (13.x → ≥ 580), CUDA в паспорте модели |
| Под без запроса GPU видит все GPU | Образ NVIDIA + дефолтный runtime `nvidia` | Taint, запрет выбора GPU через env, CDI |
| Time-slicing в проде для разных команд | Один под съел память — у соседей OOM; метрики не по подам | MIG или отдельные GPU |
| Драйвер ставится контейнером на каждой новой ноде | Холодный старт ноды — минуты | Образ ноды с драйвером, `driver.enabled=false` |
| Алерт `GPU_UTIL > 90%` как «перегрузка» | Шум (для инференса норма), а простой не ловится | Алерт на простой и XID; нагрузку — по очереди и TTFT |
| DRA-драйвер NVIDIA для GPU в проде «потому что GA» | GA — у API Kubernetes, выдача GPU драйвером не поддерживается официально | Device plugin в проде, DRA — пилот |

---

## 💼 Как это в DevOps

- GPU-пулы — отдельная «страна» в кластере: ноды с taint, образ с драйвером, квоты, алерты, своя строка
  в бюджете. GPU Operator — стандарт для своего железа; в managed-облаках не поставь драйвер второй раз.
- Частые вопросы ML-команды: «почему под в `Pending`» (нет свободной GPU, taint, квота), «почему упало
  с CUDA error» (драйвер/образ), «почему так дорого» (простой).
- DRA спросят на собесе в 2026-м: «ядро GA с 1.34, extended resources GA с 1.37, драйвер NVIDIA для
  GPU ещё не официальный» — показывает, что следишь за темой.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Дать поду GPU | `resources.limits: { nvidia.com/gpu: 1 }` + toleration + nodeSelector/affinity |
| Не пустить обычные поды | `kubectl taint nodes &lt;n&gt; nvidia.com/gpu=true:NoSchedule` |
| Выбрать GPU по памяти / ограничить команду | Affinity `nvidia.com/gpu.memory Gt 40000` / ResourceQuota `requests.nvidia.com/gpu` |
| Поставить весь стек | `helm install gpu-operator nvidia/gpu-operator --version v26.7.1 -n gpu-operator` |
| 4 пода на одну GPU | Time-slicing ConfigMap `replicas: 4` → ClusterPolicy `devicePlugin.config` |
| Аппаратная нарезка | MIG: метка `nvidia.com/mig.config=all-1g.10gb`, ресурс `nvidia.com/mig-1g.10gb` |
| Найти простой / аппаратную беду | `avg_over_time(DCGM_FI_DEV_GPU_UTIL[2h]) < 5` / `changes(DCGM_FI_DEV_XID_ERRORS[10m]) > 0` |
| Пул GPU с нулём нод | Karpenter NodePool с taint и `consolidationPolicy: WhenEmpty` / CA min 0 |
| Потренироваться без GPU | PATCH `/status/capacity/nvidia.com~1gpu` или fake-gpu-operator |

---

## 🧠 Что запомнить

1. ⭐ Цепочка: драйвер на хосте → container toolkit пробрасывает устройства и библиотеки →
   device plugin объявляет `nvidia.com/gpu` → kubelet → планировщик → под.
2. CUDA — в образе, драйвер — на хосте; драйвер не старше, чем требует CUDA (13.x → ≥ 580, 12.x → ≥ 525).
3. ⭐ `nvidia.com/gpu` — extended resource: только целые, без overcommit, в limits, считается в ResourceQuota;
   GPU отдаётся контейнеру целиком.
4. GPU Operator 26.7.1 ставит NFD, драйвер, toolkit, device plugin, GFD, DCGM exporter, MIG manager, validator.
5. ⭐ Изоляция GPU-нод: taint `nvidia.com/gpu` + toleration + affinity по меткам GFD;
   ExtendedResourceToleration сам добавит toleration подам, запросившим GPU.
6. ⭐ Time-slicing — любые GPU, без изоляции памяти и сбоев; MPS — одновременная работа с долями;
   MIG — аппаратная изоляция на A30/A100/H100/H200/B200, фиксированные профили.
7. ⭐ DRA — «PVC для устройств» (DeviceClass, ResourceSlice, ResourceClaim): ядро GA с 1.34, prioritized
   list GA с 1.36, extended resource support и device taints GA с 1.37.
8. NVIDIA DRA-драйвер (v0.5.0): ComputeDomains поддерживаются, выдача GPU — пока не официально.
9. ⭐ DCGM: простой — `GPU_UTIL`, занятость — `PROF_GR_ENGINE_ACTIVE`, память — `FB_USED/FB_FREE`,
   беда — `XID_ERRORS` (79 — GPU отвалилась, 48/95 — сброс GPU).
10. ⭐ Деньги: цена часа × часы простоя; рычаги — пул с нулём нод, scale-to-zero сервинга, разделение
    GPU для dev, spot для обучения, правильный размер, квоты и showback.
11. AWS: G4dn (T4), G5 (A10G), G6 (L4), G6e (L40S), P4d (A100), P5 (H100), P5e/P5en (H200), P6 (Blackwell);
    Yandex: V100, A100, T4, 141 ГБ; грант РК без GPU. Без GPU учатся на планировании (PATCH / fake-gpu-operator).

➡️ Дальше: [03_model_serving.md](/mlops/03-model-serving) · Задачи: 02_gpu_kubernetes_tasks.md


---

### Блок A. Теория


**A1.** ⭐ Опиши цепочку от GPU на ноде до процесса в контейнере: какие компоненты участвуют и что делает каждый?

<details><summary>Ответ</summary>

Драйвер (kernel-модуль) на хосте управляет GPU; NVIDIA Container Toolkit настраивает runtime и
пробрасывает в контейнер `/dev/nvidia*` и `libcuda`; device plugin по gRPC сообщает kubelet число устройств
`nvidia.com/gpu` и при старте контейнера говорит, какие именно GPU отдать; kubelet публикует ресурс
в `allocatable`; планировщик ставит под на ноду со свободным ресурсом; процесс в контейнере работает
через CUDA runtime из образа.

</details>

**A2.** Что живёт в образе, а что на хосте: CUDA runtime, драйвер, libcuda? Какое правило совместимости
и какой минимальный драйвер нужен для CUDA 12.x и 13.x?

<details><summary>Ответ</summary>

CUDA runtime и библиотеки (PyTorch, vLLM) — в образе; драйвер и kernel-модуль — на хосте;
`libcuda` приходит от драйвера через toolkit. Драйвер должен быть не старше, чем требует CUDA образа;
новый драйвер запускает старую CUDA. Минимум: CUDA 12.x — ≥ 525, CUDA 13.x — ≥ 580; CUDA 13.4 — ветка R615.

</details>

**A3.** Что делает NVIDIA Container Toolkit? Что такое CDI?

<details><summary>Ответ</summary>

Настраивает runtime `nvidia` в containerd/CRI-O и при старте контейнера монтирует устройства и
библиотеки драйвера. CDI (Container Device Interface) — стандартный формат описания устройств для
рантаймов: какие файлы, устройства и переменные нужны контейнеру.

</details>

**A4.** ⭐ Что делает device plugin и как `nvidia.com/gpu` появляется в `allocatable` ноды?

<details><summary>Ответ</summary>

DaemonSet регистрируется в kubelet через сокет device plugin API, отдаёт список устройств и их
здоровье (ListAndWatch); kubelet добавляет `nvidia.com/gpu: N` в `capacity`/`allocatable` ноды. При старте
контейнера kubelet вызывает Allocate, и plugin возвращает, какие устройства пробросить.

</details>

**A5.** ⭐ Какие правила действуют для extended-ресурсов вроде `nvidia.com/gpu`? Почему нельзя запросить 0,5 GPU?

<details><summary>Ответ</summary>

Только целые числа, нет overcommit (requests = limits, если указаны оба; поэтому пишут только
limits — requests выставятся равными), устройство целиком
отдаётся одному контейнеру, ресурс учитывается в квотах. 0,5 нельзя, потому что API extended-ресурсов
не умеет дробные значения; делят GPU механизмами time-slicing, MPS или MIG, которые объявляют больше
«устройств».

</details>

**A6.** ⭐ Какие компоненты ставит GPU Operator? Зачем в нём NFD и validator?

<details><summary>Ответ</summary>

NFD, драйвер (DaemonSet), container toolkit, device plugin, GFD, DCGM и DCGM exporter, MIG manager,
validator; опционально DRA-драйвер. NFD находит ноды с GPU NVIDIA (метка `pci-10de.present`), чтобы
операнды ставились только туда; validator проверяет, что цепочка реально работает (CUDA-тест), и только
после этого нода считается готовой.

</details>

**A7.** Когда GPU Operator ставят с `driver.enabled=false` и `toolkit.enabled=false`?

<details><summary>Ответ</summary>

Когда драйвер и toolkit уже есть в образе ноды: EKS accelerated AMI, группы узлов Yandex с
предустановленными драйверами, свои образы. Иначе оператор поставит второй драйвер и они будут конфликтовать.

</details>

**A8.** Как устроен старт новой GPU-ноды с GPU Operator и почему это важно для холодного старта?

<details><summary>Ответ</summary>

NFD находит GPU → driver DaemonSet собирает/загружает модуль → toolkit настраивает runtime →
device plugin публикует ресурс → validator проверяет → GFD и DCGM exporter. Установка драйвера контейнером
занимает минуты — это прибавляется к холодному старту ноды при автоскейлинге.

</details>

**A9.** ⭐ Как изолировать GPU-ноды от обычных подов? Почему одного taint мало?

<details><summary>Ответ</summary>

Taint `nvidia.com/gpu=true:NoSchedule` не пускает поды без toleration; toleration только разрешает,
но не притягивает — поэтому GPU-подам нужен ещё nodeSelector/affinity (или сам запрос `nvidia.com/gpu`,
который есть только на GPU-нодах). Плюс квоты и PriorityClass.

</details>

**A10.** Что делает admission-плагин ExtendedResourceToleration? Почему ключ taint обычно `nvidia.com/gpu`?

<details><summary>Ответ</summary>

Если под запрашивает extended-ресурс, плагин добавляет ему toleration с ключом, равным имени
ресурса (`nvidia.com/gpu`, `Exists`, `NoSchedule`). Поэтому taint с ключом `nvidia.com/gpu` автоматически
пропускает только поды, запросившие GPU.

</details>

**A11.** Какие метки ставит GPU Feature Discovery и как ими пользоваться в affinity?

<details><summary>Ответ</summary>

`nvidia.com/gpu.product`, `gpu.memory` (МиБ), `gpu.count`, `gpu.family`, `cuda.driver-version.*`,
`cuda.runtime-version.*`, `gpu.replicas`, `mig.strategy` и др. В affinity: `nvidia.com/gpu.product In [...]`,
`nvidia.com/gpu.memory Gt 40000`, по семейству — ради совместимости библиотек.

</details>

**A12.** Как ограничить число GPU на команду? Как защитить прод-сервинг от экспериментов?

<details><summary>Ответ</summary>

ResourceQuota `requests.nvidia.com/gpu` на namespace; PriorityClass с высоким приоритетом для
прод-сервинга и низким для экспериментов (прод вытесняет эксперименты); отдельные пулы для обучения
и сервинга; очередь заданий (Kueue).

</details>

**A13.** ⭐ Сравни time-slicing, MPS и MIG: изоляция памяти и сбоев, поддерживаемые GPU, случаи применения.

<details><summary>Ответ</summary>

Time-slicing: любые GPU, поочерёдное время, без изоляции памяти и сбоев, метрики не по подам —
dev, CI, редкие запросы. MPS: Volta+, одновременная работа, доли памяти и вычислений, слабая изоляция
сбоев, не вместе с MIG — много мелких процессов одной команды. MIG: A30/A100/H100/H200/B200, аппаратная
изоляция памяти, кэша и вычислителей, фиксированные профили — мультиарендный прод.

</details>

**A14.** Что делают `replicas`, `renameByDefault` и `failRequestsGreaterThanOne` в конфиге time-slicing?

<details><summary>Ответ</summary>

`replicas` — сколько «устройств» объявить на одну физическую GPU; `renameByDefault: true` —
объявлять их как `nvidia.com/gpu.shared`, чтобы поды явно выбирали разделяемый ресурс;
`failRequestsGreaterThanOne: true` — отклонять запрос больше одной доли, потому что две доли не дают
двойной мощности.

</details>

**A15.** Что значат MIG-профили `1g.10gb`, `3g.40gb`, `7g.80gb`? Сколько экземпляров `1g` можно сделать на A100?

<details><summary>Ответ</summary>

`Ng` — N седьмых вычислителей GPU, `XXgb` — память экземпляра: `1g.10gb` — 1/7 вычислителей и 10 ГБ,
`3g.40gb` — 3/7 и 40 ГБ, `7g.80gb` — вся GPU. На A100 — до 7 экземпляров `1g`.

</details>

**A16.** Чем MIG-стратегия `single` отличается от `mixed`? Как выглядит ресурс в каждой?

<details><summary>Ответ</summary>

`single`: все MIG-экземпляры ноды одного профиля и выдаются как обычный `nvidia.com/gpu`.
`mixed`: разные профили на одной ноде, каждый — отдельный ресурс `nvidia.com/mig-&lt;профиль&gt;`.

</details>

**A17.** ⭐ Что такое DRA? Назови его объекты и аналоги из мира хранилищ.

<details><summary>Ответ</summary>

API для устройств по модели «заявка → подбор»: DeviceClass (≈ StorageClass), ResourceSlice
(что драйвер нашёл на ноде, с атрибутами), ResourceClaim (≈ PVC), ResourceClaimTemplate (≈ volumeClaimTemplates).
Под ссылается на claim в `spec.resourceClaims` и `resources.claims`.

</details>

**A18.** ⭐ Какой статус у DRA в Kubernetes 1.34, 1.36 и 1.37? Что даёт extended resource support?

<details><summary>Ответ</summary>

1.34 — ядро `resource.k8s.io/v1` GA и включено по умолчанию. 1.36 — prioritized list GA; beta:
extended resource support, partitionable devices, device taints, binding conditions, health status.

</details>

**A19.** Можно ли в сентябре 2026 выдавать GPU в проде через DRA-драйвер NVIDIA? Почему?

<details><summary>Ответ</summary>

Нет, если нужна официальная поддержка: в README драйвера (v0.5.0) выдача GPU помечена как
«можно попробовать, но не поддерживается официально», GPU kubelet plugin выключен по умолчанию;
официально поддерживаются ComputeDomains. В проде — device plugin, DRA — пилот.

</details>

**A20.** ⭐ Какие DCGM-метрики важны девопсу и как их читать? Почему `GPU_UTIL = 100%` не значит «загружена полностью»?

<details><summary>Ответ</summary>

`DCGM_FI_DEV_GPU_UTIL` — доля времени, когда работал хоть один kernel (ловит простой, но 100%
бывает и при слабой нагрузке); `DCGM_FI_PROF_GR_ENGINE_ACTIVE` — точнее о занятости; `FB_USED/FB_FREE` —
память (vLLM занимает её заранее); `GPU_TEMP`, `POWER_USAGE`; `XID_ERRORS` — аппаратные и драйверные
сбои; remapped rows — деградация памяти.

</details>

**A21.** Что такое XID-ошибки? Что делать при XID 79, 48, 94 и 95?

<details><summary>Ответ</summary>

Коды ошибок драйвера NVIDIA в журнале ядра. 79 — GPU недоступна по PCIe: cordon + drain,
перезагрузка машины, тикет провайдеру. 48 — некорректируемая ECC: сброс GPU или перезагрузка, cordon.

</details>

**A22.** ⭐ Как посчитать стоимость простоя GPU-ноды? Назови 5 рычагов экономии.

<details><summary>Ответ</summary>

Цена ноды в час × часы простоя × число нод. Рычаги: пул с минимумом 0 нод, scale-to-zero
сервинга (KEDA), разделение GPU для dev/CI, spot для обучения с чекпоинтами, расписание non-prod,
правильный размер GPU, квоты и showback по командам.

</details>

**A23.** Как сделать пул GPU-нод, который уходит в ноль? Что нужно, чтобы Karpenter считал GPU-ноду готовой?

<details><summary>Ответ</summary>

Отдельная группа/NodePool с минимумом 0, taint `nvidia.com/gpu`, consolidation пустых нод
(Karpenter `WhenEmpty`) или scale-down у CA; нагрузка сама уходит в ноль (KEDA). Karpenter считает ноду
инициализированной, только когда на ней работает device plugin (или GPU Operator) и ресурс появился.

</details>

**A24.** Какие GPU-семейства есть в AWS и какие GPU за ними стоят? Что есть у Yandex Cloud?

<details><summary>Ответ</summary>

AWS: G4dn — T4, G5 — A10G, G6 — L4, G6e — L40S, G7/G7e — RTX PRO Blackwell, P4d/P4de — A100,
P5 — H100, P5e/P5en — H200, P6/P6e — Blackwell/GB200; Inf2/Trn2 — свои чипы AWS. Yandex: V100
(`gpu-standard-v1/v2`), A100 (`gpu-standard-v3/v3i`), T4 (`standard-v3-t4`), платформа на 141 ГБ
(`gpu-standard-v4`); стартовый грант в РК GPU не покрывает.

</details>

---

### Блок B. «Что произойдёт»


```text:no-line-numbers
# B1
```text
```text:no-line-numbers
resources:
```text
```text:no-line-numbers
  requests: { nvidia.com/gpu: 1 }
```text
```text:no-line-numbers
  limits:   { nvidia.com/gpu: 2 }
```text
Вопрос: что ответит API?

```text:no-line-numbers
# B2
```text
```text:no-line-numbers
resources:
```text
```text:no-line-numbers
  limits: { nvidia.com/gpu: 0.5 }
```text
Вопрос: что будет?

```text:no-line-numbers
# B3 — образ vllm/vllm-openai с CUDA 13.x, на ноде драйвер 550 (nvidia-smi: CUDA Version 12.4)
```text
Вопрос: что случится при старте?

```text:no-line-numbers
# B4 — GPU-нода с taint nvidia.com/gpu=true:NoSchedule
```text
```text:no-line-numbers
# под с toleration на этот taint, но без nodeSelector/affinity и без запроса nvidia.com/gpu
```text
Вопрос: куда попадёт под? А если запросить `nvidia.com/gpu: 1`?

```text:no-line-numbers
# B5 — 3 GPU-ноды по 1 GPU, taint'ов нет, CA с expander random, в кластере есть CPU-группа
```text
```text:no-line-numbers
Выкатили 20 реплик обычного веб-сервиса, CPU-нод не хватило.
```text
Вопрос: что может сделать автоскейлер и сколько это стоит?

```text:no-line-numbers
# B6 — time-slicing replicas: 4 на ноде с одной L4 (24 ГБ)
```text
```text:no-line-numbers
# четыре пода сервинга, каждый грузит модель на 8 ГБ
```text
Вопрос: что будет?

```text:no-line-numbers
# B7 — time-slicing, failRequestsGreaterThanOne: true
```text
```text:no-line-numbers
resources: { limits: { nvidia.com/gpu: 2 } }
```text
Вопрос: что ответит device plugin и почему это разумно?

```text:no-line-numbers
# B8 — на ноде с A100 80GB идут поды сервинга
```text
```text:no-line-numbers
kubectl label node gpu-1 nvidia.com/mig.config=all-1g.10gb --overwrite
```text
Вопрос: что произойдёт с работающими подами и что появится в allocatable?

```text:no-line-numbers
# B9 — MIG mixed, на ноде 7 экземпляров 1g.10gb
```text
```text:no-line-numbers
resources: { limits: { nvidia.com/gpu: 1 } }
```text
Вопрос: запланируется ли под?

```text:no-line-numbers
# B10 — кластер 1.37, DRA-драйвер NVIDIA с extended resource mapping на DeviceClass, device plugin удалён
```text
```text:no-line-numbers
resources: { limits: { nvidia.com/gpu: 1 } }
```text
Вопрос: будет ли работать старый манифест?

```text:no-line-numbers
# B11 — алерт
```text
```text:no-line-numbers
DCGM_FI_DEV_XID_ERRORS > 0
```text
Вопрос: чем плох такой алерт?

```text:no-line-numbers
# B12 — Karpenter NodePool для g6, device plugin не установлен
```text
Вопрос: что будет с GPU-подами и счётом?

---

### Блок C. Практика


### C1. 🔑 GPU-планирование в kind
Пройди мини-лабу: kind на `kindest/node:v1.36.4`, «GPU-нода» с taint и 4 `nvidia.com/gpu` через PATCH статуса.
Запиши для каждого из четырёх подов, где он оказался и какое событие видно в `describe`.

### C2. 🔑 Квоты и приоритеты
В `team-ml` поставь ResourceQuota `requests.nvidia.com/gpu: "2"`. Создай три пода по 1 GPU и запиши ошибку.
Затем создай PriorityClass `prod-serving` (value 100000) и `experiments` (1000): займи все 4 GPU
подами `experiments` и запусти под `prod-serving` на 1 GPU. Что произошло с экспериментами?

### C3. ExtendedResourceToleration
Выясни, включён ли плагин в kind (`kubectl -n kube-system get pod kube-apiserver-gpu-control-plane -o yaml | grep admission`).
Включи его через `kubeadmConfigPatches` в конфиге kind, пересоздай кластер и проверь: под с запросом
`nvidia.com/gpu` без toleration теперь получает toleration автоматически?

### C4. 🔑 Time-slicing на бумаге
Напиши ConfigMap time-slicing для двух типов нод: `l4-dev` — 8 реплик с `renameByDefault: true`,
`a100-prod` — без разделения. Как выбрать конфиг для конкретной ноды? Какой ресурс будут запрашивать поды
на `l4-dev`? Сколько `nvidia.com/gpu.shared` покажет нода с 2 × L4?

### C5. MIG-план
Команде нужно на одной H100 80GB: 2 сервиса по ~15 ГБ памяти модели и 3 эксперимента по ~8 ГБ.
Подбери профили MIG (из таблицы конспекта), проверь, что суммарно их можно разместить (не больше 7 долей
вычислителей), и напиши `limits` для каждого пода при стратегии `mixed`.

### C6. 🔑 DRA-манифесты
Напиши ResourceClaimTemplate и Pod по образцу конспекта; затем ResourceClaim (не шаблон), общий для двух
подов. В чём разница поведения? Попробуй применить в kind 1.36 — какие объекты создадутся без DRA-драйвера
и в каком состоянии будет под?

### C7. 🔑 Алерты на GPU
Напиши PrometheusRule: простой GPU (< 5% за 2 часа), XID-ошибка, память > 95% (с исключением для подов
vLLM по метке `container`), температура выше порога из спецификации. Для каждого — severity и что делает дежурный.

### C8. Калькулятор простоя
Возьми цены on-demand для g6.xlarge и p5.48xlarge из калькулятора AWS (регион, который ты бы выбрал для РК).
Посчитай месячные потери, если: (а) dev-нода g6 работает 24/7, а нужна 9:00–19:00 по будням; (б) одна p5
простаивает каждую ночь по 10 часов. Сколько сэкономит расписание или scale-to-zero?

### C9. Karpenter для GPU (на бумаге)
Напиши NodePool для обучения: spot, семейства `g6e` и `p4d`, taint `nvidia.com/gpu`, лимит 16 GPU,
consolidation только пустых нод. Объясни, что должно быть в EC2NodeClass и что — на ноде до того,
как Karpenter признает её готовой.

### C10. fake-gpu-operator (со звёздочкой)
Поставь fake-gpu-operator 0.2.0 в kind, посмотри, какие метки появились на ноде, какие метрики отдаёт
status-exporter и совпадают ли их имена с DCGM. Опиши, чему он учит, а чему — нет.

---

### Блок D. Инциденты


**D1.** Под сервинга в `Pending`: `0/5 nodes are available: 2 Insufficient nvidia.com/gpu, 3 node(s) had untolerated taint`.
Разбери сообщение и составь план.

<details><summary>Ответ</summary>

На двух нодах без taint нет свободных GPU (или ресурс не объявлен), три ноды с taint — у пода нет
toleration. План: проверить, кто занял GPU (`describe node`, поды с `nvidia.com/gpu`), нужен ли под на
tainted-нодах (добавить toleration или включить ExtendedResourceToleration), не пора ли увеличить пул.

</details>

**D2.** После обновления образа сервинга под падает с `CUDA driver version is insufficient for CUDA runtime version`.
Что произошло и какие два пути решения?

<details><summary>Ответ</summary>

Новый образ собран под CUDA новее, чем поддерживает драйвер нод. Пути: обновить драйвер
(через GPU Operator/образ ноды) или собрать/взять образ под нужную CUDA; на будущее — метка
`nvidia.com/cuda.driver-version.full` в affinity и проверка совместимости в CI.

</details>

**D3.** На GPU-ноде `kubectl describe node` показывает `nvidia.com/gpu: 0` в allocatable, хотя вчера было 4.
Где искать?

<details><summary>Ответ</summary>

Device plugin: жив ли под DaemonSet, логи (не нашёл устройств, ошибка NVML); драйвер (XID в
`dmesg`, `nvidia-smi` на ноде); не переразмечена ли GPU на MIG (ресурс сменил имя); GPU Operator
validator и `clusterpolicy` status; не перезапускался ли kubelet после обновления.

</details>

**D4.** В 3 часа ночи XID 79 на одной из GPU-нод, поды на ней висят. Действия дежурного?

<details><summary>Ответ</summary>

Cordon ноды, перенести нагрузку (drain), убедиться, что сервис жив на других нодах; перезагрузить
машину (XID 79 — GPU недоступна по PCIe); если повторяется — вывести ноду и завести тикет провайдеру/железу.
Утром — постмортем и алерт на XID.

</details>

**D5.** На ноде с time-slicing одна команда жалуется на случайные OOM на GPU, хотя «их модель маленькая».
Причина и решение?

<details><summary>Ответ</summary>

Time-slicing не изолирует память: соседний под на той же GPU занимает её (например, vLLM
резервирует почти всю). Решение: MIG или отдельные GPU для разных команд, лимиты памяти у сервинга,
на time-slicing — только dev/CI.

</details>

**D6.** Счёт за GPU за месяц вырос вдвое при той же нагрузке. Какие метрики и отчёты посмотреть?

<details><summary>Ответ</summary>

OpenCost/Kubecost по namespace и меткам команд, GPU-часы по нодам, `avg_over_time(DCGM_FI_DEV_GPU_UTIL)`
по нодам (простой), число GPU-нод во времени, пулы без минимума 0, забытые эксперименты, смена типа
инстанса автоскейлером.

</details>

**D7.** Новые GPU-ноды в EKS становятся Ready только через 8–10 минут, автоскейлинг сервинга не успевает за пиком.
Из чего складывается время и что ускорить?

<details><summary>Ответ</summary>

Создание ВМ + загрузка ОС + установка драйвера контейнером (минуты) + toolkit/device plugin +
pull образа сервинга (~10 ГБ) + загрузка модели. Ускорить: AMI с драйвером и `driver.enabled=false`,
кэш/предзагрузка образа, модель на быстром томе, запас тёплых реплик (min 1 в прод-часы).

</details>

**D8.** В Grafana DCGM-дашборд показывает GPU, но в разрезе подов метрик нет. Почему?

<details><summary>Ответ</summary>

Сопоставление метрик с подами идёт через kubelet PodResources API: либо exporter не имеет к нему
доступа, либо включён time-slicing (при нём DCGM не привязывает метрики к контейнерам), либо метки
переименованы при скрейпе (`exported_pod`).

</details>

**D9.** После включения MIG часть подов команды не планируется, хотя «GPU же стало больше». Почему?

<details><summary>Ответ</summary>

После MIG ресурсы стали называться `nvidia.com/mig-&lt;профиль&gt;` (при `mixed`), а поды просят
`nvidia.com/gpu`; или профили слишком малы для их моделей по памяти. Обновить манифесты или стратегию.

</details>

**D10.** Аудит нашёл: под из namespace `analytics`, который GPU не запрашивал, видел все 8 GPU ноды через `nvidia-smi`.
Как такое возможно и как закрыть?

<details><summary>Ответ</summary>

Образ NVIDIA с `NVIDIA_VISIBLE_DEVICES=all` на ноде, где `nvidia` — дефолтный runtime: toolkit
пробросил все GPU, хотя device plugin их не выделял. Закрыть: taint на GPU-нодах, запрет выбора GPU
через переменную окружения для непривилегированных контейнеров, CDI/volume-mounts стратегия, политика
(Kyverno/OPA), запрещающая эту переменную без запроса GPU.

</details>

---

### Блок E. Вопросы с собеседования


**1.** ⭐ Как под в Kubernetes получает GPU? Что такое device plugin?

<details><summary>Ответ</summary>

Драйвер → toolkit → device plugin объявляет `nvidia.com/gpu` → kubelet → планировщик → под с limits;
   device plugin — DaemonSet с gRPC API к kubelet, объявляет и выделяет устройства.

</details>

**2.** Что такое GPU Operator и зачем он, если есть device plugin?

<details><summary>Ответ</summary>

Оператор ставит и обновляет весь стек (драйвер, toolkit, plugin, GFD, DCGM, MIG manager, validator)
   на всех GPU-нодах одним чартом и CRD; device plugin — только одна часть.

</details>

**3.** ⭐ Как изолировать GPU-ноды и направить на них только нужные поды?

<details><summary>Ответ</summary>

Taint `nvidia.com/gpu` + toleration (ExtendedResourceToleration), affinity по меткам GFD, квоты,
   PriorityClass, отдельные пулы для обучения и сервинга.

</details>

**4.** ⭐ Time-slicing, MPS или MIG — что и когда?

<details><summary>Ответ</summary>

Time-slicing — dev/CI без изоляции; MPS — много мелких процессов одной команды; MIG — прод с аппаратной
   изоляцией на A100/H100/H200.

</details>

**5.** Что такое DRA и какой у него статус?

<details><summary>Ответ</summary>

«PVC для устройств»: DeviceClass, ResourceSlice, ResourceClaim; ядро GA с 1.34, extended resources
   и device taints GA с 1.37; драйвер NVIDIA для выдачи GPU — ещё не официальный.

</details>

**6.** ⭐ Какие метрики GPU вы бы мониторили и какие алерты поставили?

<details><summary>Ответ</summary>

Утилизация и занятость, память, температура и мощность, XID, remapped rows; алерты — простой,
   XID, деградация памяти; нагрузку сервинга — по очереди и TTFT (тема 03).

</details>

**7.** Как связаны версии драйвера и CUDA? Как не сломать сервинг при обновлении?

<details><summary>Ответ</summary>

Драйвер на хосте должен быть не старше, чем требует CUDA образа; обновлять драйвер раньше образов,
   пинить CUDA в образе, проверять совместимость по меткам GFD и на staging-пуле.

</details>

**8.** ⭐ Как сократить расходы на GPU в Kubernetes?

<details><summary>Ответ</summary>

Пулы с нулём нод, scale-to-zero, разделение GPU, spot для обучения, расписание, правильный размер,
   квоты и showback, алерт на простой.

</details>

**9.** Какие GPU-инстансы вы бы выбрали для инференса модели 8B и почему?

<details><summary>Ответ</summary>

L4 (G6) или A10G (G5) для 8B в INT8/INT4; L40S (G6e) для FP16 с запасом под KV-кэш и конкуренцию;
   H100 — только если нужна большая пропускная способность или модель крупнее.

</details>

**10.** Как бы вы протестировали GPU-манифесты и политики планирования без GPU?

<details><summary>Ответ</summary>

kind с объявленным через PATCH `nvidia.com/gpu` или fake-gpu-operator: taint'ы, affinity, квоты,
    приоритеты, DRA-объекты; политики — через `kubectl apply --dry-run=server` и тесты политик.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Объясняю цепочку «драйвер → toolkit → device plugin → `nvidia.com/gpu` → под»
- [ ] Знаю правило совместимости драйвера и CUDA и минимальные драйверы для CUDA 12.x и 13.x
- [ ] ⭐ Пишу манифест пода с GPU, taint и toleration; знаю правила extended-ресурсов
- [ ] Знаю, что ставит GPU Operator и когда отключать драйвер и toolkit
- [ ] Выбираю GPU по меткам GFD и ограничиваю команды квотами
- [ ] ⭐ Сравниваю time-slicing, MPS и MIG и выбираю под задачу
- [ ] ⭐ Объясняю DRA и его статус в 1.34–1.37
- [ ] Знаю ключевые DCGM-метрики и что делать при XID 79/48/95
- [ ] ⭐ Считаю стоимость простоя GPU-ноды и называю рычаги экономии
- [ ] Прошёл мини-лабу: GPU-планирование в kind без GPU
