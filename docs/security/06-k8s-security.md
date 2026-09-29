---
title: "06. Безопасность Kubernetes"
description: "Блок → Безопасность → тема 06. Опирается на"
---

# 06. Безопасность Kubernetes

> Блок → Безопасность → тема 06. Опирается на
> [../Kubernetes/17_rbac.md](/kubernetes/17-rbac) · [../Kubernetes/13_networkpolicy.md](/kubernetes/13-networkpolicy) ·
> [../Kubernetes/08_configmap_secret.md](/kubernetes/08-configmap-secret) ·
> [../Docker/10_security_best_practices.md](/docker/10-security-best-practices).
> RBAC, NetworkPolicy, Secret и «контейнер — не граница безопасности» там уже разобраны.
> Здесь — то, что превращает кластер из «работает» в «переживёт взломанный под».
>
> **После темы ты умеешь:** включить Pod Security Admission без аварии, написать прод-`securityContext`,
> отключить лишние токены ServiceAccount, писать CEL-политики (ValidatingAdmissionPolicy, Kyverno)
> с раскаткой Audit → Deny, проверять подписи образов, разобрать отчёт kube-bench, поймать Falco'м
> shell в контейнере и включить шифрование Secret в etcd.

---

## 🗺️ Карта темы

```text
 kubectl apply ──► kube-apiserver
                   │ 1. authn: кто ты (сертификат, токен SA, OIDC)
                   │ 2. authz: RBAC — можно ли (../Kubernetes/17_rbac.md)
                   │ 3. mutating admission:   Kyverno MutatingPolicy, MutatingAdmissionPolicy
                   │ 4. validating admission: Pod Security Admission, ValidatingAdmissionPolicy,
                   │                          Kyverno ValidatingPolicy / ImageValidatingPolicy
                   │ 5. etcd ◄── encryption at rest для Secret
                   │ ════ audit log: всё, что прошло через API (тема 07)
                   ▼
 scheduler ──► kubelet ──► containerd ──► контейнер: non-root, drop ALL, seccomp,
                                          read-only FS, без токена SA
                                                │ syscalls
                                                ▼
                                          Falco (eBPF) ──► алерт ──► Falcosidekick
 kube-bench ─── сверяет настройки нод и control plane с CIS Benchmark
 NetworkPolicy ─ ограничивает, куда сможет ходить взломанный под
```text
---

## 1. Модель 4C: где какие меры

Классика из документации Kubernetes и курса CKS: каждый слой защищает следующий,
и **внутренний слой не компенсирует дырявый внешний**.

| Слой | Что защищаем | Меры | Где в волте |
|------|--------------|------|-------------|
| **Cloud** (или ДЦ) | Аккаунт, сеть, ноды, managed control plane | IAM, приватные ноды, API только из VPN | [05_iam_access.md](/security/05-iam-access), [../Left/04_Cloud/03_network_vpc.md](/cloud/03-network-vpc) |
| **Cluster** | API, etcd, kubelet | RBAC, admission, audit, шифрование etcd, CIS | [../Kubernetes/17_rbac.md](/kubernetes/17-rbac), эта тема |
| **Container** | Образ и рантайм | Non-root, drop ALL, seccomp, подписи, скан | [../Docker/10_security_best_practices.md](/docker/10-security-best-practices), эта тема |
| **Code** | Приложение | Зависимости, секреты, TLS, валидация ввода | [04_vuln_management.md](/security/04-vuln-management), [03_web_edge_security.md](/security/03-web-edge-security) |

> 💡 Текущая страница «Cloud Native Security» в документации Kubernetes описывает то же через
> **фазы жизненного цикла** из CNCF whitepaper: *Develop* → *Distribute* (сборка, скан, подпись) →
> *Deploy* (admission) → *Runtime* (доступы, изоляция, детект). На собесе годится любая рамка —
> главное показать слои.

---

## 2. Pod Security Standards и Pod Security Admission

**PSS** — три уровня требований к поду. **PSA** — встроенный admission-контроллер, который
применяет их по меткам namespace (пришёл на смену PodSecurityPolicy).

| Уровень | Что запрещает | Для кого |
|---------|---------------|----------|
| `privileged` | Ничего | CNI, CSI, агенты мониторинга и Falco |
| `baseline` | Известные эскалации: `privileged`, `hostNetwork/PID/IPC`, `hostPath`, hostPort, лишние capabilities, seccomp `Unconfined` | Минимум для любых приложений |
| `restricted` | Всё из baseline + `runAsNonRoot: true`, `runAsUser` ≠ 0, `allowPrivilegeEscalation: false`, seccomp `RuntimeDefault`/`Localhost` (отсутствие профиля запрещено), `drop: [ALL]` (добавить можно только `NET_BIND_SERVICE`), тома только `configMap`, `csi`, `downwardAPI`, `emptyDir`, `ephemeral`, `persistentVolumeClaim`, `projected`, `secret` | ⭐ Цель для прикладных namespace |

> ⚠️ `readOnlyRootFilesystem` в PSS **не входит** даже в restricted — это best practice сверху.

| Режим (метка) | Что делает | На что действует |
|---------------|-----------|------------------|
| `enforce` | Отклоняет под | Только Pod |
| `audit` | Пишет нарушение в audit log | Pod и шаблоны workload'ов |
| `warn` | Предупреждение в ответе `kubectl` | Pod и шаблоны workload'ов |

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: app
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: v1.37   # зафиксировать правила при апгрейдах
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/audit: restricted
```text
```bash
# ⭐ СНАЧАЛА примерка: какие существующие поды нарушат уровень (ничего не меняет)
kubectl label --dry-run=server --overwrite ns app pod-security.kubernetes.io/enforce=restricted
# Warning: existing pods in namespace "app" violate the new PodSecurity enforce level ...
```text
Раскатка без аварии: **warn + audit = restricted, enforce = baseline** → чинишь манифесты
(раздел 3), пока предупреждений не станет ноль → **enforce = restricted** с зафиксированной версией.

> ⚠️ `enforce` действует **только на поды**: `kubectl apply` Deployment проходит (максимум warning),
> а подов нет. Причина — в ReplicaSet: `kubectl describe rs -n app` →
> `Error creating: pods "..." is forbidden: violates PodSecurity "restricted:latest": ...`.

**Исключения** (usernames, runtimeClassNames, namespaces) задаются только статически
в `AdmissionConfiguration` API-сервера. `kube-system` и namespace CNI/CSI/Falco оставляют
на `privileged` — осознанная зона доверия. Нужна гибкость тоньше namespace («этому DaemonSet'у
можно hostPath, остальным нет») — это уже Kyverno/VAP (разделы 5–6).

---

## 3. securityContext: прод-под целиком

```yaml
apiVersion: apps/v1
kind: Deployment
metadata: { name: api, namespace: app }
spec:
  replicas: 2
  selector: { matchLabels: { app: api } }
  template:
    metadata: { labels: { app: api } }
    spec:
      serviceAccountName: api
      automountServiceAccountToken: false         # API кубера приложению не нужен (раздел 4)
      securityContext:                             # уровень пода
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001                             # группа-владелец для томов
        seccompProfile: { type: RuntimeDefault }
      containers:
        - name: api
          image: registry.example.com/api@sha256:&lt;digest&gt;   # digest, а не тег (раздел 7)
          ports: [{ containerPort: 8080 }]         # > 1024 — NET_BIND_SERVICE не нужен
          securityContext:                         # уровень контейнера, перекрывает под
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: { drop: ["ALL"] }
          resources:
            requests: { cpu: 100m, memory: 128Mi }
            limits: { memory: 256Mi }
          volumeMounts: [{ name: tmp, mountPath: /tmp }]   # куда приложению можно писать
      volumes:
        - { name: tmp, emptyDir: { sizeLimit: 64Mi } }
```text
| Поле | От чего защищает |
|------|------------------|
| `runAsNonRoot` / `runAsUser` ≠ 0 | Root в контейнере = root на хосте при побеге; права на смонтированные файлы |
| `allowPrivilegeEscalation: false` | SUID-бинарники: процесс не получит больше прав, чем у родителя (`no_new_privs`) |
| `capabilities.drop: [ALL]` | `NET_RAW` (спуфинг), `SYS_ADMIN` и прочие «ключи от хоста» |
| `seccompProfile: RuntimeDefault` | Редкие syscall'ы, через которые идут эксплойты ядра |
| `readOnlyRootFilesystem` | Докачка тулов атакующего, подмена бинарников приложения |
| `automountServiceAccountToken: false` | Украденный токен → доступ к API кластера |
| `resources.limits` | Майнер или утечка памяти кладёт ноду и соседей |

Типовые поломки при переходе на restricted:
- `container has runAsNonRoot and image has non-numeric user (app), cannot verify user is non-root` —
  в Dockerfile `USER app` по имени; нужен числовой `USER 10001` или `runAsUser` в манифесте.
- Официальный `nginx` слушает 80 и пишет в `/var/cache/nginx` — бери `nginxinc/nginx-unprivileged`
  (порт 8080) и emptyDir под кэш.
- `Read-only file system` в логах — найди, куда приложение пишет, и дай туда emptyDir.

---

## 4. ServiceAccount и его токен

Каждый под по умолчанию получает токен своего SA в `/var/run/secrets/kubernetes.io/serviceaccount/token`.
RCE в поде = у атакующего учётка в API с правами этого SA.

```yaml
apiVersion: v1
kind: ServiceAccount
metadata: { name: api, namespace: app }
automountServiceAccountToken: false     # дефолт для всех подов этого SA (под может переопределить)
```text
| Токен | Срок | Оценка |
|-------|------|--------|
| **Projected (bound)** — в поде через TokenRequest | Около часа, kubelet обновляет сам; привязан к поду | ✅ Норма, если под реально ходит в API |
| `kubectl create token api --duration=10m` | Задаёшь сам | ✅ Разовый доступ, отладка, CI |
| Secret типа `kubernetes.io/service-account-token` | **Бессрочный**, пока жив Secret | ⚠️ Утёк — действует вечно |

> ⚠️ В [../Kubernetes/17_rbac.md](/kubernetes/17-rbac) для CI создаётся именно бессрочный
> токен-Secret — для учёбы годится, в проде лучше: GitOps (у CI нет доступа к кластеру),
> OIDC-федерация CI → облако → managed-кластер ([05_iam_access.md](/security/05-iam-access)) или хотя бы
> `kubectl create token` с коротким сроком.

```bash
kubectl auth can-i --list --as=system:serviceaccount:app:api -n app       # что может SA
kubectl get secrets -A --field-selector type=kubernetes.io/service-account-token   # бессрочные токены
```text
---

## 5. Admission-политики: что выбрать

| Инструмент | Язык | Умеет | Когда |
|------------|------|-------|-------|
| **Pod Security Admission** | Метки | 3 готовых уровня на namespace | Всегда, база |
| **ValidatingAdmissionPolicy** (GA 1.30) | CEL | Валидация любых объектов, без вебхука | Простые правила без внешних компонентов |
| **MutatingAdmissionPolicy** (GA 1.36) | CEL | Мутации без вебхука | Дефолты: метки, securityContext |
| **Kyverno** | YAML + CEL | Validate, mutate, generate, подписи, отчёты, исключения, CLI | ⭐ Стандарт де-факто для платформенных политик |
| **OPA Gatekeeper** | Rego | Validate, mutate, аудит существующих объектов | Если в компании уже OPA |

ValidatingAdmissionPolicy — встроена в API-сервер, нет пода-вебхука, который может упасть:

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata: { name: deny-latest-tag }
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
      - { apiGroups: [""], apiVersions: ["v1"], operations: ["CREATE", "UPDATE"], resources: ["pods"] }
  validations:
    - expression: >-
        object.spec.containers.all(c, !c.image.endsWith(':latest') &&
          (c.image.contains('@sha256:') || c.image.lastIndexOf(':') > c.image.lastIndexOf('/')))
      message: "Образ должен быть с конкретным тегом или digest, не :latest"
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata: { name: deny-latest-tag }
spec:
  policyName: deny-latest-tag
  validationActions: [Warn, Audit]        # сначала мягко; потом [Deny] (Deny и Warn вместе нельзя)
  matchResources:
    namespaceSelector: { matchLabels: { policy.lab/enforce: "true" } }
```text
> `lastIndexOf(':') > lastIndexOf('/')` отличает тег от порта реестра (`localhost:5001/app` — без тега).
> Без binding'а политика ничего не делает.

---

## 6. Kyverno на CEL

```bash
helm repo add kyverno https://kyverno.github.io/kyverno/ && helm repo update
helm upgrade --install kyverno kyverno/kyverno -n kyverno --create-namespace
kubectl -n kyverno get pods        # по умолчанию 4 Deployment'а по 1 реплике
```text
> ⭐ С Kyverno 1.17 (февраль 2026) CEL-типы — стабильный `policies.kyverno.io/v1`: `ValidatingPolicy`,
> `MutatingPolicy`, `GeneratingPolicy`, `ImageValidatingPolicy`, `DeletingPolicy`, `PolicyException`.
> Старые `ClusterPolicy`/`Policy` (`kyverno.io/v1`) — deprecated, удаление запланировано в 1.20.

**Validate** — разрешённые реестры. Раскатка: `Audit` → отчёты → `Deny`.
```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata: { name: allowed-registries }
spec:
  validationActions: [Audit]              # этап 1: только отчёты
  evaluation: { background: { enabled: true } }   # проверить и уже запущенные поды
  matchConstraints:
    resourceRules:
      - { apiGroups: [""], apiVersions: ["v1"], operations: ["CREATE", "UPDATE"], resources: ["pods"] }
  variables:
    - name: allContainers
      expression: "object.spec.containers + object.spec.?initContainers.orValue([])"
  validations:
    - expression: >-
        variables.allContainers.all(c, c.image.startsWith('registry.example.com/') ||
          c.image.startsWith('ghcr.io/kyverno/'))
      message: "Образы только из registry.example.com"
```text
```bash
kubectl get policyreport -A                              # кто нарушает, по namespace
kubectl get policyreport -n app -o yaml | grep -B3 -A6 'result: fail'
# нарушений ноль (или все объяснены исключениями) → validationActions: [Deny]
```text
**Mutate** — проставить seccomp, если забыли. Мутация идёт *до* валидации, поэтому под
после неё проходит и PSA:
```yaml
apiVersion: policies.kyverno.io/v1
kind: MutatingPolicy
metadata: { name: default-seccomp }
spec:
  matchConstraints:
    resourceRules:
      - { apiGroups: [""], apiVersions: ["v1"], operations: ["CREATE"], resources: ["pods"] }
  matchConditions:
    - name: no-seccomp
      expression: "!has(object.spec.securityContext) || !has(object.spec.securityContext.seccompProfile)"
  mutations:
    - patchType: ApplyConfiguration
      applyConfiguration:
        expression: >
          Object{
            spec: Object.spec{
              securityContext: Object.spec.securityContext{
                seccompProfile: Object.spec.securityContext.seccompProfile{ type: "RuntimeDefault" }
              }
            }
          }
```text
**Исключение** вместо «выключим политику для всех». PolicyException по умолчанию выключены:
нужен флаг `enablePolicyException=true` и `exceptionNamespace` — где их можно создавать.
```yaml
apiVersion: policies.kyverno.io/v1
kind: PolicyException
metadata: { name: legacy-billing, namespace: kyverno-exceptions }
spec:
  policyRefs: [{ name: allowed-registries, kind: ValidatingPolicy }]
  matchConditions:
    - name: only-legacy-billing
      expression: "object.metadata.namespace == 'billing' && object.metadata.name.startsWith('legacy-')"
```text
**Ты встретишь это в старых чартах и статьях** — legacy-синтаксис, мигрируй на CEL:
```yaml
apiVersion: kyverno.io/v1        # deprecated с 1.17, удаление в 1.20
kind: ClusterPolicy
spec:
  rules:
    - name: check-registry
      match: { any: [{ resources: { kinds: [Pod] } }] }
      validate: { failureAction: Audit, pattern: { spec: { containers: [{ image: "registry.example.com/*" }] } } }
```text
**В CI** политики проверяют до кластера: `kyverno apply policies/ --resource manifests/`
(и `kyverno test` для тест-кейсов) — нарушение ломает MR, а не деплой.

> ⚠️ Вебхуки Kyverno по умолчанию `failurePolicy: Fail`: Kyverno лёг — поды в затронутых
> namespace не создаются. Для прода — 3 реплики admission-контроллера, PDB, алерт на доступность.
> `Ignore` бережёт доступность, но упавший Kyverno = выключенная защита.

---

## 7. Подписи образов: пускать только своё

Как подписать (`cosign sign --key` или keyless) — уже в
[../Docker/10_security_best_practices.md](/docker/10-security-best-practices) и
[../CICD/13_quality_security.md](/cicd/13-quality-security). Здесь — проверка при деплое
на публичном тестовом образе Kyverno (теги `:signed`, `:unsigned`, `:signed-by-someone-else`):

```yaml
apiVersion: policies.kyverno.io/v1
kind: ImageValidatingPolicy
metadata: { name: verify-test-image }
spec:
  validationActions: [Deny]
  webhookConfiguration: { timeoutSeconds: 30 }
  evaluation: { background: { enabled: false } }
  matchConstraints:
    resourceRules:
      - { apiGroups: [""], apiVersions: ["v1"], operations: ["CREATE", "UPDATE"], resources: ["pods"] }
  matchImageReferences:
    - glob: "ghcr.io/kyverno/test-verify-image*"
  attestors:
    - name: cosign
      cosign:
        key:
          data: |
            -----BEGIN PUBLIC KEY-----
            MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE8nXRh950IZbRj8Ra/N9sbqOPZrfM
            5/KAQN0/KjHcorm/J5yctVd7iEcnessRQjU917hmKO6JWVGHpDguIyakZA==
            -----END PUBLIC KEY-----
        ctlog: { insecureIgnoreTlog: true }   # тестовая подпись без записи в Rekor
  validations:
    - expression: >-
        images.containers.map(image, verifyImageSignatures(image, [attestors.cosign])).all(e, e > 0)
      message: "Подпись образа не прошла проверку"
```text
```bash
kubectl run signed   --image=ghcr.io/kyverno/test-verify-image:signed     # создан
kubectl run unsigned --image=ghcr.io/kyverno/test-verify-image:unsigned   # отклонён
```text
| Приём | Зачем |
|-------|-------|
| Деплой по digest (`@sha256:…`) | Тег можно перезаписать, digest — нет; подписывается именно digest |
| Keyless: подпись идентичностью CI (OIDC → Fulcio, запись в Rekor) | Нет приватного ключа, который можно украсть; в политике — `issuer` + `subject` пайплайна |
| Проверка attestations (SBOM, SLSA provenance) | «Собрано нашим CI из нашего репо», а не просто «кем-то подписано» |
| Cosign v3 | По умолчанию новый формат bundle — проверь, что твоя версия Kyverno его понимает |

---

## 8. kube-bench: CIS Kubernetes Benchmark

CIS Benchmark — сотни проверок конфигурации API-сервера, etcd, kubelet, прав на файлы и политик.
kube-bench прогоняет их прямо на нодах.

```bash
# node-проверки: Job с hostPID и hostPath → только в namespace БЕЗ PSA restricted (default)
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job.yaml
kubectl wait --for=condition=complete job/kube-bench --timeout=120s
kubectl logs job/kube-bench > kube-bench-node.txt
# control plane: nodeSelector/tolerations под control-plane, --targets master
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job-master.yaml
kubectl logs job/kube-bench-master > kube-bench-master.txt
grep -E '^\[(FAIL|WARN)\]' kube-bench-*.txt | head -30
```text
```text
[PASS] &lt;номер&gt; &lt;что проверено&gt; (Automated)   ← проверка прошла
[FAIL] &lt;номер&gt; &lt;что проверено&gt; (Automated)   ← не соответствует — смотри Remediations
[WARN] &lt;номер&gt; &lt;что проверено&gt; (Manual)      ← проверить руками (политики, процессы)
== Remediations master ==                    ← что поправить: манифест, флаг, права на файл
== Summary total ==                          ← N checks PASS / FAIL / WARN / INFO
```text
| Итог по пункту | Действие |
|----------------|----------|
| FAIL, применимо | Исправить в IaC (kubeadm config, Terraform managed-кластера), перепрогнать |
| FAIL, не применимо / принятый риск | Задокументировать исключение: причина, владелец, срок пересмотра |
| WARN (Manual) | Закрыть процессом: RBAC-ревью, PSA на namespace, NetworkPolicy |

- На kind часть FAIL ожидаема: это kubeadm с настройками «для разработки» (типичный пример —
  `--profiling` у API-сервера). Разбирай пункт, а не «чини всё подряд».
- В managed-кластерах (EKS/GKE/AKS, Yandex Managed Kubernetes) control plane недоступен:
  проверяешь ноды и провайдер-специфичные бенчмарки (`job-eks.yaml`, `job-gke.yaml`, `job-aks.yaml`
  в репозитории kube-bench); остальное — зона провайдера.
- Для хоста с Docker — `docker-bench-security`, для ОС — Lynis ([02_linux_hardening.md](/security/02-linux-hardening)).

---

## 9. Falco: runtime-детект

Всё выше — **профилактика**. Falco ловит то, что уже происходит: читает syscalls и сверяет с правилами.

```text
 контейнер ──syscalls──► ядро ──modern eBPF──► Falco (правила) ──► stdout / gRPC
                                                    └──► Falcosidekick ──► Slack, Telegram,
                                                                           Loki, Alertmanager
```text
```bash
helm repo add falcosecurity https://falcosecurity.github.io/charts && helm repo update
helm install falco falcosecurity/falco -n falco --create-namespace \
  --set driver.kind=modern_ebpf --set tty=true
kubectl logs -n falco -l app.kubernetes.io/name=falco -c falco -f | grep -i shell
```text
Стандартное правило, которое ловит `kubectl exec -it … -- sh`:
```yaml
- rule: Terminal shell in container
  condition: >
    spawned_process and container and shell_procs and proc.tty != 0
    and container_entrypoint and not user_expected_terminal_shell_in_container_conditions
  output: A shell was spawned in a container with an attached terminal | user=%user.name ...
  priority: NOTICE
  tags: [maturity_stable, container, shell, mitre_execution, T1059]
```text
Своё правило — через values чарта `customRules` (попадает в `/etc/falco/rules.d`):
```yaml
customRules:
  custom-rules.yaml: |-
    - list: pkg_mgmt_bins
      items: [apt, apt-get, dpkg, apk, yum, dnf, pip, pip3, npm]
    - rule: Package manager in container
      desc: Контейнеры неизменяемы — пакетный менеджер в рантайме = докачка тулов
      condition: spawned_process and container and proc.name in (pkg_mgmt_bins)
      output: >
        Package manager in container (cmd=%proc.cmdline user=%user.name
        image=%container.image.repository ns=%k8s.ns.name pod=%k8s.pod.name)
      priority: WARNING
      tags: [container, software_mgmt, custom]
      exceptions:
        - name: build_images
          fields: container.image.repository
          comps: in
          values: [registry.example.com/ci-builder]
```text
```bash
helm upgrade falco falcosecurity/falco -n falco --reuse-values -f falco-values.yaml
```text
Борьба с шумом: в алертинг — `priority` ≥ WARNING, остальное — в логи; легитимное поведение —
через `exceptions` или `override` (`condition: append`), а не выключением правила; раз в неделю —
разбор топа сработок. Falco **детектирует, но не блокирует**: реакция — по playbook
([07_security_incidents_compliance.md](/security/07-security-incidents-compliance)) или автоматикой
(Falco Talon, свой webhook).

---

## 10. Шифрование Secret в etcd

Secret — это base64 ([../Kubernetes/08_configmap_secret.md](/kubernetes/08-configmap-secret)), и без
настройки etcd хранит его открытым текстом: бэкап etcd или диск control plane = все пароли.

```yaml
# /etc/kubernetes/enc/enc.yaml на control plane
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources: ["secrets"]
    providers:
      - aescbc:                      # первый провайдер ШИФРУЕТ новые записи
          keys:
            - name: key1
              secret: &lt;base64 от 32 случайных байт&gt;   # head -c 32 /dev/urandom | base64
      - identity: {}                 # остальные только ЧИТАЮТ (старые незашифрованные)
```text
```bash
# kube-apiserver: --encryption-provider-config=/etc/kubernetes/enc/enc.yaml (+ volume в static pod)
kubectl get secrets --all-namespaces -o json | kubectl replace -f -   # перешифровать старые
ETCDCTL_API=3 etcdctl get /registry/secrets/app/db-pass | hexdump -C | head   # → k8s:enc:aescbc:v1:key1
```text
| Провайдер | Оценка |
|-----------|--------|
| `identity` | Без шифрования (по умолчанию) |
| `aescbc`, `aesgcm`, `secretbox` | Ключ лежит на диске control plane — защищает бэкапы etcd, но не взлом ноды |
| ⭐ `kms` v2 (stable с 1.29) | Envelope encryption: ключ шифрования ключей — во внешнем KMS/HSM |

> В managed-кластерах это параметр «шифровать секреты ключом KMS». Шифрование в etcd **не**
> защищает от того, у кого есть `get secrets` через API, — это по-прежнему RBAC. На kind включается
> как аудит в стенде: `extraMounts` с конфигом + `kubeadmConfigPatches` (`encryption-provider-config`, `extraVolumes`).

---

## 11. Аудит и сеть: без них защита слепая

- **Audit log API-сервера** включён в стенде (`k8s/audit-policy.yaml`): тела Secret не пишутся
  (уровень `Metadata`), `pods/exec` фиксируется. Разбор — в [07_security_incidents_compliance.md](/security/07-security-incidents-compliance).
- **NetworkPolicy default deny** ([../Kubernetes/13_networkpolicy.md](/kubernetes/13-networkpolicy)) —
  взломанный под не дойдёт до базы и соседей. В облаке закрой egress к `169.254.169.254`:
  через SSRF оттуда воруют IAM-креды ноды ([05_iam_access.md](/security/05-iam-access)).
- **API-сервер** — только из приватной сети/VPN, люди — через OIDC, а не общий admin-kubeconfig.

---

## 12. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| `enforce=restricted` сразу на все namespace | Встали CNI, мониторинг, Falco | Системные — `privileged`, прикладные — warn/audit → enforce |
| «Deployment применился, а подов нет» | enforce режет поды в ReplicaSet | `kubectl describe rs`, примерка `--dry-run=server` |
| `USER app` по имени | `runAsNonRoot` не может проверить UID | Числовой `USER 10001` |
| `readOnlyRootFilesystem` без emptyDir | Приложение падает на записи в `/tmp` | emptyDir на пути записи |
| Kyverno 1 реплика, `failurePolicy: Fail` | Упал Kyverno — поды не создаются | 3 реплики, PDB, алерт |
| Политики вечно в `Audit` | Отчёты никто не читает, защиты нет | Срок на Audit → Deny + PolicyException |
| Новые политики на `ClusterPolicy` | Deprecated, удаление в 1.20 | `policies.kyverno.io/v1` на CEL |
| Подпись проверяется, а деплой по тегу | Тег перезаписали после подписи | Digest в манифестах |
| Все алерты Falco в Telegram | Alert fatigue, реальную сработку пропустят | Приоритеты, exceptions, разбор шума |
| Бессрочный токен SA для CI | Утёк — действует годами | GitOps, OIDC, `kubectl create token` |
| «Secret зашифрован в etcd — значит, в безопасности» | Через API читается открыто | RBAC на `secrets`, ESO/Vault |
| «Починили весь kube-bench» на managed | Половина проверок — зона провайдера | Провайдер-специфичный бенчмарк |

---

## 💼 Как это в DevOps

- Namespace «из шаблона»: PSA-метки, default deny NetworkPolicy, ResourceQuota, RBAC — одним
  чартом/Terraform-модулем, а не руками.
- Политики Kyverno — в git как платформенное Argo-приложение, `kyverno apply` в CI, раскатка
  Audit → Deny с отчётом командам; исключения — PolicyException с владельцем и сроком.
- kube-bench — по расписанию и после апгрейда кластера; FAIL превращаются в тикеты или
  задокументированные исключения.
- Falco-алерты WARNING+ — в security-канал, у каждого правила есть runbook.
- Сертификация **CKS** (Certified Kubernetes Security Specialist) — ровно про эту тему.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Примерить PSA | `kubectl label --dry-run=server --overwrite ns app pod-security.kubernetes.io/enforce=restricted` |
| Почему нет подов | `kubectl describe rs -n app` → `violates PodSecurity` |
| Права SA | `kubectl auth can-i --list --as=system:serviceaccount:&lt;ns&gt;:&lt;sa&gt;` |
| Короткий токен | `kubectl create token &lt;sa&gt; --duration=10m` |
| Бессрочные токены | `kubectl get secrets -A --field-selector type=kubernetes.io/service-account-token` |
| Отчёты Kyverno | `kubectl get policyreport -A` |
| Политики в CI | `kyverno apply policies/ --resource manifests/` |
| CIS-проверка | `kubectl apply -f …/kube-bench/main/job.yaml && kubectl logs job/kube-bench` |
| Falco | `helm install falco falcosecurity/falco -n falco --create-namespace --set driver.kind=modern_ebpf` |
| Логи Falco | `kubectl logs -n falco -l app.kubernetes.io/name=falco -c falco` |
| Перешифровать Secret | `kubectl get secrets -A -o json \| kubectl replace -f -` |

---

## 🧠 Что запомнить

1. 4C: Cloud → Cluster → Container → Code; внутренний слой не спасает дырявый внешний.
2. PSA: `privileged` для системных namespace, `restricted` — цель для приложений;
   раскатка warn/audit → enforce, примерка `--dry-run=server`.
3. `enforce` режет только поды — ищи ошибку в ReplicaSet, а не в Deployment.
4. Прод-под: числовой non-root UID, `allowPrivilegeEscalation: false`, drop ALL,
   seccomp `RuntimeDefault`, read-only FS + emptyDir, без токена SA, с limits.
5. Токен SA монтируется по умолчанию — выключай; бессрочные токен-Secret'ы — долг.
6. VAP/MAP — встроенные CEL-политики без вебхука; Kyverno — полноценная платформа политик.
7. ⭐ Kyverno: новые политики — CEL `policies.kyverno.io/v1`; `ClusterPolicy` deprecated.
8. Любая политика: Audit → отчёты → исправления → Deny + PolicyException.
9. kube-bench показывает расхождения с CIS; FAIL — это вопрос, а не приказ.
10. Falco видит атаку в рантайме, но не блокирует; шифрование etcd не заменяет RBAC.

➡️ Дальше: [07_security_incidents_compliance.md](/security/07-security-incidents-compliance) · задачи: 06_k8s_security_tasks.md


---

### Блок A. Теория


**A1.** Назови слои модели 4C и что защищает каждый. Какой рамкой её заменила документация Kubernetes?

<details><summary>Ответ</summary>

Cloud (аккаунт, сеть, ноды, managed control plane), Cluster (API, etcd, kubelet: RBAC,
admission, audit, шифрование), Container (образ и рантайм: non-root, caps, seccomp, подписи),
Code (приложение: зависимости, секреты, валидация). Документация сейчас описывает фазы жизненного
цикла CNCF: Develop → Distribute → Deploy → Runtime.

</details>

**A2.** ⭐ Чем отличаются уровни PSS `privileged`, `baseline`, `restricted`? Требует ли `restricted`
`readOnlyRootFilesystem`?

<details><summary>Ответ</summary>

`privileged` — без ограничений (системные компоненты); `baseline` — запрет известных
эскалаций (privileged, host-namespaces, hostPath, hostPort, лишние capabilities, seccomp
Unconfined); `restricted` — ещё `runAsNonRoot`, `runAsUser` ≠ 0, `allowPrivilegeEscalation: false`,
обязательный seccomp `RuntimeDefault`/`Localhost`, drop ALL (можно добавить только
`NET_BIND_SERVICE`), ограниченный список типов томов. `readOnlyRootFilesystem` не требуется — это best practice.

</details>

**A3.** Что делают режимы PSA `enforce`, `audit`, `warn` и на какие объекты действует каждый?

<details><summary>Ответ</summary>

`enforce` отклоняет поды; `audit` пишет нарушение в audit log; `warn` возвращает
предупреждение клиенту. `enforce` действует только на Pod, `audit` и `warn` — ещё и на шаблоны
workload'ов (Deployment, Job…).

</details>

**A4.** ⭐ `kubectl apply` Deployment прошёл, а подов нет. Почему так бывает с PSA и где смотреть ошибку?

<details><summary>Ответ</summary>

`enforce` проверяет только Pod, а Deployment — нет: объект создан, но ReplicaSet не может
создать поды. Ошибка — в `kubectl describe rs -n &lt;ns&gt;` (`Error creating: … violates PodSecurity`)
и в событиях namespace.

</details>

**A5.** Как включить `restricted` на существующем namespace без аварии?

<details><summary>Ответ</summary>

Примерка `kubectl label --dry-run=server --overwrite ns …/enforce=restricted`; затем
`warn` и `audit` = restricted, `enforce` = baseline; чинить манифесты, пока предупреждений нет;
затем `enforce` = restricted с зафиксированной `enforce-version`.

</details>

**A6.** От чего защищают `runAsNonRoot`, `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`,
`seccompProfile: RuntimeDefault`, `readOnlyRootFilesystem`?

<details><summary>Ответ</summary>

Non-root — root в контейнере опасен при побеге и для смонтированных файлов;
`allowPrivilegeEscalation: false` — через SUID не получить больше прав (`no_new_privs`); drop ALL —
нет `NET_RAW`, `SYS_ADMIN` и других опасных capabilities; seccomp — отсекает редкие syscalls,
через которые идут эксплойты ядра; read-only FS — нельзя докачать тулы и подменить бинарники.

</details>

**A7.** Почему `USER app` в Dockerfile ломает под с `runAsNonRoot: true`?

<details><summary>Ответ</summary>

Kubelet не может по имени пользователя проверить, что UID ≠ 0 (он не читает `/etc/passwd`
образа): `container has runAsNonRoot and image has non-numeric user (app), cannot verify user is non-root`.
Нужен числовой `USER 10001` или `runAsUser` в манифесте.

</details>

**A8.** ⭐ Зачем выключать `automountServiceAccountToken`? Какие бывают токены SA и чем они отличаются?

<details><summary>Ответ</summary>

Токен монтируется в каждый под по умолчанию: RCE в поде = учётка в API с правами SA.
Projected (bound) — около часа, обновляется kubelet, привязан к поду; `kubectl create token` —
с заданным сроком; Secret типа `service-account-token` — бессрочный, пока жив Secret.

</details>

**A9.** Чем ValidatingAdmissionPolicy отличается от Kyverno и Gatekeeper? Что обязательно нужно,
чтобы VAP заработала?

<details><summary>Ответ</summary>

VAP — встроена в API-сервер, CEL, только валидация, без вебхука (нет компонента, который
может упасть). Kyverno — отдельный контроллер: validate, mutate, generate, подписи, отчёты,
исключения, CLI. Gatekeeper — OPA/Rego. VAP без ValidatingAdmissionPolicyBinding ничего не делает.

</details>

**A10.** ⭐ Какие типы политик есть в Kyverno на CEL и что стало с `ClusterPolicy`?

<details><summary>Ответ</summary>

`policies.kyverno.io/v1` (стабильны с 1.17): ValidatingPolicy, MutatingPolicy,
GeneratingPolicy, ImageValidatingPolicy, DeletingPolicy, PolicyException (+ Namespaced-варианты).
`ClusterPolicy`/`Policy` (`kyverno.io/v1`) — deprecated, удаление запланировано в 1.20.

</details>

**A11.** Как раскатывать политику Kyverno? Что такое PolicyReport и PolicyException?

<details><summary>Ответ</summary>

`Audit` → PolicyReport (результаты проверок по namespace, в т.ч. для уже запущенных
ресурсов при background) → исправления у команд → `Deny` + PolicyException для оправданных случаев.
PolicyException — объект-исключение для конкретных ресурсов; по умолчанию выключены, включаются
флагом с указанием namespace, где их можно создавать.

</details>

**A12.** Чем опасен `failurePolicy: Fail` у вебхуков Kyverno и чем — `Ignore`?

<details><summary>Ответ</summary>

`Fail`: Kyverno недоступен — поды в затронутых namespace не создаются (авария доступности).
`Ignore`: Kyverno упал — запросы проходят без проверок (защита молча выключена). Решение для прода:
`Fail` + 3 реплики, PDB, алерт на доступность вебхука.

</details>

**A13.** Зачем деплоить по digest, если образы подписаны? Что такое keyless-подпись?

<details><summary>Ответ</summary>

Подписывается digest; тег можно перезаписать после подписи — в прод попадёт другой
образ. Keyless: CI подписывает своей OIDC-идентичностью (сертификат Fulcio, запись в Rekor),
приватного ключа, который можно украсть, нет; в политике проверяются issuer и subject пайплайна.

</details>

**A14.** Что проверяет kube-bench? Как читать PASS/FAIL/WARN? Чем отличается проверка managed-кластера?

<details><summary>Ответ</summary>

Конфигурацию API-сервера, etcd, kubelet, прав на файлы и политик против CIS Kubernetes
Benchmark. PASS — соответствует; FAIL — нет, смотри Remediations; WARN — ручная проверка
(процессы, политики). В managed-кластере control plane недоступен: проверяешь ноды и
провайдер-специфичные бенчмарки, остальное — зона провайдера.

</details>

**A15.** ⭐ Как работает Falco? Что ловит правило «Terminal shell in container»? Блокирует ли Falco атаку?

<details><summary>Ответ</summary>

Читает системные вызовы через modern eBPF и сверяет с правилами (условие на полях
процесса, контейнера, k8s), пишет алерты в stdout/gRPC, дальше Falcosidekick. «Terminal shell in
container» — запуск shell с TTY в контейнере (типично `kubectl exec -it … -- sh`). Falco
детектирует, но не блокирует; реакция — playbook или автоматика.

</details>

**A16.** Какие провайдеры шифрования Secret в etcd бывают? От чего шифрование at rest не защищает?

<details><summary>Ответ</summary>

`identity` (нет шифрования), `aescbc`/`aesgcm`/`secretbox` (ключ на диске control plane),
`kms` v2 (envelope encryption с ключом во внешнем KMS). Не защищает от того, у кого есть
`get secrets` через API — это RBAC; и от взлома control plane при локальном ключе.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  kubectl label ns kube-system pod-security.kubernetes.io/enforce=restricted --overwrite
```text
<details><summary>Ответ</summary>

⚠️ Системные компоненты (CNI, kube-proxy, CoreDNS в некоторых сборках) требуют привилегий:
новые поды в kube-system перестанут создаваться, кластер деградирует. Системные namespace —
`privileged`.

</details>

```text:no-line-numbers
B2.  # Dockerfile: USER app
```text
<details><summary>Ответ</summary>

⚠️ Kubelet не проверит нечисловой USER → `CreateContainerConfigError`. `USER 10001` в
Dockerfile или `runAsUser: 10001`.

</details>

```text:no-line-numbers
     spec:
```text
```text:no-line-numbers
       securityContext: { runAsNonRoot: true }
```text
```text:no-line-numbers
B3.  securityContext: { readOnlyRootFilesystem: true }
```text
<details><summary>Ответ</summary>

⚠️ Приложение упадёт с `Read-only file system`. Добавить emptyDir на `/tmp`.

</details>

```text:no-line-numbers
     # приложение пишет временные файлы в /tmp, томов нет
```text
```text:no-line-numbers
B4.  # namespace с enforce=baseline
```text
<details><summary>Ответ</summary>

⚠️ baseline запрещает `privileged` и добавление `SYS_ADMIN` — под отклонён. Для отладки —
ephemeral debug-контейнер (`kubectl debug`) в рамках политики или отдельный namespace с осознанным
уровнем и доступом.

</details>

```text:no-line-numbers
     containers:
```text
```text:no-line-numbers
       - name: debug
```text
```text:no-line-numbers
         securityContext:
```text
```text:no-line-numbers
           privileged: true
```text
```text:no-line-numbers
           capabilities: { add: ["SYS_ADMIN"] }
```text
```text:no-line-numbers
B5.  apiVersion: admissionregistration.k8s.io/v1
```text
<details><summary>Ответ</summary>

⚠️ Без ValidatingAdmissionPolicyBinding политика не применяется ни к чему.

</details>

```text:no-line-numbers
     kind: ValidatingAdmissionPolicy
```text
```text:no-line-numbers
     metadata: { name: require-limits }
```text
```text:no-line-numbers
     spec: { ... validations: [...] }
```text
```text:no-line-numbers
     # binding не создавали, «политика не работает»
```text
```text:no-line-numbers
B6.  kind: ValidatingAdmissionPolicyBinding
```text
<details><summary>Ответ</summary>

⚠️ `Deny` и `Warn` вместе указывать нельзя — binding не пройдёт валидацию. `[Warn, Audit]`
на этапе примерки, потом `[Deny]` (можно с `Audit`).

</details>

```text:no-line-numbers
     spec:
```text
```text:no-line-numbers
       policyName: deny-latest-tag
```text
```text:no-line-numbers
       validationActions: [Deny, Warn]
```text
```text:no-line-numbers
B7.  # Kyverno ValidatingPolicy allowed-registries с validationActions: [Deny]
```text
<details><summary>Ответ</summary>

⚠️ Сразу `Deny` на весь кластер: сломаются системные поды и приложения с образами из других
реестров (Docker Hub, quay). Нужны Audit, отчёты, исключения для системных namespace, потом Deny.

</details>

```text:no-line-numbers
     # применили в понедельник на весь кластер, без Audit и без исключений
```text
```text:no-line-numbers
B8.  # ImageValidatingPolicy для registry.example.com/* включена,
```text
<details><summary>Ответ</summary>

⚠️ Деплой по тегу: подпись проверена для того, что тег указывал в момент проверки,
а тег можно перезаписать. Деплоить по digest (Kyverno умеет мутировать тег в digest —
`mutateDigest` в `validationConfigurations`).

</details>

```text:no-line-numbers
     # а в Deployment: image: registry.example.com/api:1.4
```text
```text:no-line-numbers
B9.  # Falco шумит «Terminal shell in container» от отладочных джоб CI →
```text
<details><summary>Ответ</summary>

⚠️ Выключив правило, ты перестанешь видеть и атакующего. Добавить exception для
CI-debug образов/namespace или override с `condition: append`, а правило оставить.

</details>

```text:no-line-numbers
     - rule: Terminal shell in container
```text
```text:no-line-numbers
       enabled: false
```text
```text:no-line-numbers
B10.  apiVersion: apiserver.config.k8s.io/v1
```text
<details><summary>Ответ</summary>

⚠️ Первый провайдер шифрует новые записи: с `identity` первым секреты пишутся
открытым текстом. `aescbc` первым, `identity` — последним (только чтение старых), затем перешифровать.

</details>

```text:no-line-numbers
     kind: EncryptionConfiguration
```text
```text:no-line-numbers
     resources:
```text
```text:no-line-numbers
       - resources: ["secrets"]
```text
```text:no-line-numbers
         providers:
```text
```text:no-line-numbers
           - identity: {}
```text
```text:no-line-numbers
           - aescbc: { keys: [{ name: key1, secret: <...> }] }
```text
```text:no-line-numbers
B11.  kubectl -n app apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job.yaml
```text
<details><summary>Ответ</summary>

⚠️ Job kube-bench использует `hostPID` и `hostPath` — PSA restricted его не пустит
(в ReplicaSet/Job-контроллере будет `violates PodSecurity`). Запускать в `default` или в namespace
с `privileged`.

</details>

```text:no-line-numbers
     # namespace app: enforce=restricted
```text
```text:no-line-numbers
B12.  # Kyverno установлен с одной репликой admission-контроллера,
```text
<details><summary>Ответ</summary>

⚠️ Drain выселит единственный под Kyverno, вебхук с `Fail` перестанет отвечать — новые
поды (включая выселенные) не создадутся. Нужны 3 реплики, PDB, anti-affinity.

</details>

```text:no-line-numbers
     # вебхук failurePolicy: Fail, на ноде с Kyverno начинается drain
```text
---

### Блок C. Практика


### C1. 🔑 Namespace restricted и починка Deployment
**1.** Создай Deployment `web` из образа `nginx` в namespace `app`.

<details><summary>Ответ</summary>

Ошибка в ReplicaSet: `violates PodSecurity "restricted:v1.37": allowPrivilegeEscalation != false,
unrestricted capabilities, runAsNonRoot != true, seccompProfile …`. После исправления:
образ `nginxinc/nginx-unprivileged` (порт 8080), securityContext из раздела 3,
emptyDir на `/tmp` (у этого образа кэш и pid в `/tmp`). Проверка: `kubectl -n app get pods` — Running,
`kubectl -n app exec … -- id` — uid ≠ 0.

</details>

**2.** Примерь `kubectl label --dry-run=server --overwrite ns app pod-security.kubernetes.io/enforce=restricted`.

<details><summary>Ответ</summary>

В Audit под `busybox` создаётся, в `kubectl get policyreport -A` — `fail` по
`allowed-registries`. После `[Deny]` — `admission webhook … denied the request: Образы только из
registry.example.com`. Исключения: `helm upgrade kyverno kyverno/kyverno -n kyverno --reuse-values
--set features.policyExceptions.enabled=true --set features.policyExceptions.namespace=kyverno-exceptions`,
затем PolicyException из раздела 6 в `kyverno-exceptions`.

</details>

**3.** Включи `warn` и `audit` = restricted, `enforce` = restricted с `enforce-version`.

<details><summary>Ответ</summary>

В `kubectl get pod -o yaml` у пода появится `spec.securityContext.seccompProfile.type:
RuntimeDefault`. Порядок admission: сначала mutating (Kyverno, MAP), затем validating (PSA, VAP,
ValidatingPolicy) — поэтому мутированный под уже проходит проверки.

</details>

**4.** Удали под, найди ошибку в ReplicaSet, почини манифест: `nginxinc/nginx-unprivileged`,
   securityContext из раздела 3, emptyDir под `/tmp` и кэш. Под должен стать Running.

<details><summary>Ответ</summary>

`:signed` — создан; `:unsigned` — отклонён (подпись не найдена); `:signed-by-someone-else` —
отклонён (подпись не сходится с ключом). Для своего registry: `matchImageReferences` на свой
реестр, ключ из CI (`cosign.pub`, лучше из Secret/ConfigMap) или keyless с `issuer`/`subject`
пайплайна, без `insecureIgnoreTlog` в проде.

</details>

### C2. 🔑 Kyverno: Audit → отчёт → Deny
Установи Kyverno. Примени ValidatingPolicy `allowed-registries` в `Audit` (разрешены
`registry.example.com/` и `ghcr.io/kyverno/`). Запусти под `busybox` — он создастся. Найди нарушение
в `kubectl get policyreport -A`. Переключи на `Deny` и повтори. Сделай PolicyException для одного
пода в отдельном namespace (с включёнными исключениями в Helm).

### C3. MutatingPolicy: seccomp по умолчанию
Примени `default-seccomp` из раздела 6. Создай под без `securityContext` в namespace без PSA
и покажи через `kubectl get pod -o yaml`, что `seccompProfile: RuntimeDefault` появился. Объясни,
почему мутация срабатывает до PSA.

### C4. 🔑 Проверка подписи образа
Примени ImageValidatingPolicy из раздела 7. Запусти три пода: `:signed`, `:unsigned`,
`:signed-by-someone-else`. Запиши, какие прошли и с какими сообщениями. Как политика должна
выглядеть для твоего реального registry и подписи из CI?

### C5. VAP: запрет `:latest`
Примени ValidatingAdmissionPolicy и binding из раздела 5 с `[Warn, Audit]` для namespace с меткой
`policy.lab/enforce=true`. Проверь `kubectl run t --image=nginx:latest` (warning), затем переключи
на `[Deny]`. Найди событие в аудит-логе kind (аннотации validation policy).

### C6. Токены ServiceAccount
Запусти под с дефолтным SA, прочитай токен внутри (`cat /var/run/secrets/kubernetes.io/serviceaccount/token`)
и проверь `kubectl auth can-i --list --as=system:serviceaccount:app:default -n app`. Выключи
automount на SA и убедись, что в новом поде файла нет. Выпусти `kubectl create token` на 10 минут
и найди все бессрочные токен-Secret'ы в кластере.

### C7. 🔑 kube-bench и триаж
Запусти `job.yaml` и `job-master.yaml` в namespace `default`. Выпиши summary (PASS/FAIL/WARN).
Для трёх FAIL определи: применимо ли к kind, как исправить в kubeadm-конфиге, или почему это
принятый риск стенда.

### C8. 🔑 Falco ловит shell и пакетный менеджер
Установи Falco (modern eBPF). Сделай `kubectl exec -it &lt;pod&gt; -- sh` и найди алерт «Terminal shell
in container» в логах Falco. Добавь правило «Package manager in container» через `customRules`,
выполни в поде `apk add curl` (или `apt-get update`) и найди свой алерт с именем пода и namespace.

### C9. Шифрование Secret в etcd (по желанию)
На отдельном kind-кластере включи `EncryptionConfiguration` с `aescbc`: `extraMounts` с конфигом +
патч kubeadm (`encryption-provider-config` и `extraVolumes`). Создай Secret, покажи через `etcdctl`
в контейнере etcd префикс `k8s:enc:aescbc:v1:key1`, перешифруй старые Secret'ы.

---

### Блок D. Инциденты


**D1.** После установки Kyverno ночью обновляли ноды; утром новые поды ни в одном прикладном
namespace не создаются, в событиях — `failed calling webhook "…kyverno…"`.

<details><summary>Ответ</summary>

Под Kyverno выселен/не поднялся, вебхук `Fail` блокирует создание подов. Срочно: поднять
Kyverno (он в своём namespace, обычно исключён из вебхуков); в крайнем случае временно удалить
его webhook-конфигурации, записав это в таймлайн. Надолго: 3 реплики, PDB, алерт на доступность.

</details>

**D2.** В 03:00 Falco прислал «Terminal shell in container» в поде `payments` в prod, в audit log —
`pods/exec` от пользователя, которого нет в дежурстве.

<details><summary>Ответ</summary>

Security-инцидент: не удалять под. Audit log — кто сделал exec, откуда (sourceIPs),
какие ещё действия этого пользователя; отозвать его доступ/токены; изолировать под (NetworkPolicy
по метке), сохранить улики (тема 07), проверить секреты, доступные поду, и ротировать.

</details>

**D3.** В namespace `dev` нашёлся Deployment `kube-proxy-helper` с образом `xmrig`, CPU нод на 100%.

<details><summary>Ответ</summary>

Изолировать (scale 0 после сохранения манифеста и логов, NetworkPolicy), найти в audit log,
кто создал Deployment (user, SA, источник), отозвать этот доступ, проверить другие ресурсы этого
субъекта. Защита: Kyverno allowed-registries, PSA, ResourceQuota, Falco-правила на майнеры.

</details>

**D4.** После апгрейда кластера часть подов перестала создаваться с `violates PodSecurity
"restricted:latest"`, хотя манифесты не менялись.

<details><summary>Ответ</summary>

Метка `enforce-version: latest` — после апгрейда применились новые правила версии.
Временно закрепить `enforce-version` на прошлой версии, починить манифесты по `warn`, затем
поднять версию осознанно.

</details>

**D5.** Команда просит «выключить restricted в нашем namespace — образ вендора запускается от root
и пишет в свою ФС».

<details><summary>Ответ</summary>

Не выключать для всего namespace. Варианты: собрать образ-обёртку с non-root и emptyDir;
вынести вендорный компонент в отдельный namespace с baseline и NetworkPolicy; PolicyException
(для Kyverno-правил) с владельцем и сроком; требовать у вендора non-root.

</details>

**D6.** Ночью нужно срочно выкатить hotfix-образ, собранный вручную на ноутбуке, а ImageValidatingPolicy
его не пускает.

<details><summary>Ответ</summary>

Процедура break-glass для политики: PolicyException на конкретный образ/digest с
одобрением и сроком в часы (или подпись hotfix-образа ключом дежурного через CI-ветку hotfix).
После — разбор: почему hotfix собирался не в CI.

</details>

**D7.** Выяснилось, что бэкапы etcd полгода лежали в бакете с публичным чтением. Шифрование at rest
не включено.

<details><summary>Ответ</summary>

Считать все Secret скомпрометированными: ротировать пароли, токены, ключи, TLS-ключи
из Secret; закрыть бакет, проверить логи доступа к нему; включить шифрование at rest (лучше KMS v2)
и шифрование бэкапов; сертификаты кластера (PKI из бэкапа) — оценить и перевыпустить.

</details>

**D8.** Falco регулярно алертит «Package manager in container» в prod-поде `reports`: приложение
при старте делает `pip install`.

<details><summary>Ответ</summary>

Скорее всего, легитимно, но плохо: неизменяемость нарушена, зависимости тянутся в рантайме
(supply chain, недоступность PyPI = не стартует). Исправить образ (зависимости при сборке),
до тех пор — exception на этот образ с владельцем и сроком, а не выключение правила.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как бы ты защитил кластер Kubernetes? Назови уровни.

<details><summary>Ответ</summary>

Слоями: Cloud (IAM, приватный API, ноды), Cluster (RBAC, PSA, admission-политики, audit,
   шифрование etcd, CIS/kube-bench), Container (non-root, drop ALL, seccomp, подписи, сканы),
   Code; плюс NetworkPolicy и рантайм-детект (Falco).

</details>

**2.** Что такое Pod Security Standards и Pod Security Admission?

<details><summary>Ответ</summary>

PSS — три уровня требований к подам; PSA — встроенный контроллер, применяющий их по меткам
   namespace в режимах enforce/audit/warn.

</details>

**3.** Какой securityContext должен быть у прод-пода?

<details><summary>Ответ</summary>

Числовой non-root UID, `allowPrivilegeEscalation: false`, drop ALL, seccomp RuntimeDefault,
   read-only FS + emptyDir, без токена SA, с requests/limits, образ по digest.

</details>

**4.** Зачем отключать automount токена ServiceAccount?

<details><summary>Ответ</summary>

RCE в поде даёт атакующему токен с правами SA в API; большинству приложений API не нужен.

</details>

**5.** Что такое admission controller? Kyverno, Gatekeeper, ValidatingAdmissionPolicy — чем отличаются?

<details><summary>Ответ</summary>

Контроллеры, которые проверяют/меняют объекты до записи в etcd. VAP — встроенный CEL без
   вебхука; Kyverno — платформа политик на YAML+CEL с мутацией, подписями, отчётами; Gatekeeper — OPA/Rego.

</details>

**6.** Как проверять подписи образов при деплое?

<details><summary>Ответ</summary>

Подпись в CI (cosign, лучше keyless), деплой по digest, ImageValidatingPolicy Kyverno с ключом
   или identity пайплайна, плюс проверка аттестаций (SBOM, provenance).

</details>

**7.** Что такое kube-bench и CIS Benchmark для Kubernetes?

<details><summary>Ответ</summary>

CIS Benchmark — рекомендации по безопасной настройке компонентов; kube-bench прогоняет их
   на нодах и показывает PASS/FAIL/WARN с remediation.

</details>

**8.** Что такое Falco и что он может поймать?

<details><summary>Ответ</summary>

Рантайм-детект по syscalls: shell в контейнере, чтение `/etc/shadow`, пакетный менеджер,
   неожиданные сетевые соединения, запись в бинарные каталоги; алерты через Falcosidekick.

</details>

**9.** Secret в Kubernetes безопасен? Как защитить?

<details><summary>Ответ</summary>

Сам по себе нет: base64. Защита — RBAC на `secrets`, шифрование etcd (KMS), секреты вне git
   (SOPS/ESO/Vault), монтирование файлом, ротация.

</details>

**10.** Как внедрять политики, чтобы не сломать команды?

<details><summary>Ответ</summary>

Audit → отчёты командам → исправления → Deny с PolicyException; политики в git с `kyverno apply`
    в CI; системные namespace — отдельно.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Объясняю 4C и фазы жизненного цикла
- [ ] ⭐ Включил restricted на namespace через примерку и починил Deployment
- [ ] Пишу прод-securityContext и знаю, от чего защищает каждое поле
- [ ] Отключаю токены SA и знаю, где искать бессрочные
- [ ] ⭐ Kyverno-политика прошла путь Audit → PolicyReport → Deny с PolicyException
- [ ] Написал VAP с binding и понимаю `validationActions`
- [ ] Проверка подписи пускает `:signed` и режет `:unsigned`
- [ ] Прогнал kube-bench и разобрал FAIL по существу
- [ ] ⭐ Falco ловит `kubectl exec` и моё правило на пакетный менеджер
