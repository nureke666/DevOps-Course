---
title: "08. Практика: 5 лаб по безопасности"
description: "Блок → Безопасность → практика."
---

# 08. Практика: 5 лаб по безопасности

> Блок → Безопасность → практика.
> Лабы делаются на стенде из [00_INDEX.md](/security/) и остаются в git. После них есть что
> показать на собесе: роль харденинга с отчётом Lynis до/после, security-стадия CI со SBOM,
> политики кластера, отчёт об аудите периметра и таймлайн учебного инцидента.
>
> ⚠️ Все «атаки», сканы и поломки — только на своём стенде: `sec01`, `rocky01`, edge на
> 127.0.0.1, kind `sec`, Vault dev. Перед лабами 1 и 5 — `vagrant snapshot save sec01 before_lab`.
> Версии в лабах — актуальные на сентябрь 2026 и запинены намеренно.

---

## 📋 Список лаб

| № | Лаба | Что закрепляет | Артефакт |
|---|------|----------------|----------|
| 1 | ⭐ Харденинг `sec01` Ansible-ролью, Lynis до/после | тема 02 | `ansible/roles/hardening/`, `reports/lynis-before.txt`, `lynis-after.txt` |
| 2 | ⭐ Security-стадия GitLab CI: gitleaks + Trivy fs/image + SBOM + gate | тема 04 | `ci/.gitlab-ci.yml`, `.trivyignore.yaml`, `local-scan.sh`, SBOM |
| 3 | kind: kube-bench, PSA restricted, Kyverno, Falco ловит `kubectl exec` | тема 06 | `k8s/policies/`, `falco-values.yaml`, отчёт kube-bench с триажем |
| 4 | Аудит своего периметра: nmap + testssl.sh, исправить находки | тема 03 | `edge/reports/before|after`, итоговый `app.conf` |
| 5 | Game day «утёк токен»: отзыв, аудит, ротация, таймлайн | темы 05, 07 | `ir/gameday/…/timeline.md`, playbook, постмортем |

---

## 🧪 Лаба 1. Харденинг `sec01` Ansible-ролью + Lynis до/после

### Что делаем
Снимаем «как есть» (Lynis, открытые порты, эффективный sshd), пишем роль `hardening` по
чек-листу темы 02, применяем, доказываем идемпотентность и сравниваем отчёты.

### Каркас
```ini
# ~/labs/security/ansible/inventory.ini
[lab]
sec01 ansible_host=192.168.56.30 ansible_user=vagrant ansible_ssh_private_key_file=~/labs/security/vagrant/.vagrant/machines/sec01/libvirt/private_key
```text
```yaml
# requirements.yml
collections:
  - name: ansible.posix
  - name: community.general

# harden.yml
- hosts: lab
  become: true
  roles: [hardening]
```text
```yaml
# roles/hardening/defaults/main.yml
hardening_ssh_group: ssh-users
hardening_ssh_members: [vagrant]                  # ⚠️ без себя в группе — потеряешь доступ
hardening_admin_nets:
  - 192.168.56.0/24                               # приватная сеть стенда
  - 192.168.121.0/24                              # management-сеть vagrant-libvirt (vagrant ssh)
hardening_packages: [auditd, audispd-plugins, apparmor-utils, unattended-upgrades, needrestart, ufw, fail2ban, lynis]
hardening_packages_absent: [telnet, rsh-client, ftp]
hardening_auto_reboot: false
hardening_sysctl:
  kernel.kptr_restrict: 2
  kernel.dmesg_restrict: 1
  kernel.unprivileged_bpf_disabled: 1
  kernel.yama.ptrace_scope: 1
  fs.protected_hardlinks: 1
  fs.protected_symlinks: 1
  fs.suid_dumpable: 0
  net.ipv4.conf.all.accept_redirects: 0
  net.ipv4.conf.all.send_redirects: 0
  net.ipv4.conf.all.accept_source_route: 0
  net.ipv4.conf.all.rp_filter: 1
  net.ipv4.conf.all.log_martians: 1
  net.ipv4.tcp_syncookies: 1

# roles/hardening/tasks/main.yml
- ansible.builtin.import_tasks: packages.yml
- ansible.builtin.import_tasks: ssh.yml
- ansible.builtin.import_tasks: sudo.yml
- ansible.builtin.import_tasks: sysctl.yml
- ansible.builtin.import_tasks: auditd.yml
- ansible.builtin.import_tasks: updates.yml
- ansible.builtin.import_tasks: firewall.yml

# roles/hardening/tasks/packages.yml
- name: Security packages present
  ansible.builtin.apt: { name: "&#123;&#123; hardening_packages &#125;&#125;", state: present, update_cache: true, cache_valid_time: 3600 }
- name: Legacy clients absent
  ansible.builtin.apt: { name: "&#123;&#123; hardening_packages_absent &#125;&#125;", state: absent, purge: true }

# roles/hardening/tasks/ssh.yml
- name: SSH group exists
  ansible.builtin.group: { name: "&#123;&#123; hardening_ssh_group &#125;&#125;", state: present }
- name: Admins are in SSH group
  ansible.builtin.user: { name: "&#123;&#123; item &#125;&#125;", groups: "&#123;&#123; hardening_ssh_group &#125;&#125;", append: true }
  loop: "&#123;&#123; hardening_ssh_members &#125;&#125;"
- name: sshd drop-in (читается первым)
  ansible.builtin.template:
    src: 00-hardening.conf.j2
    dest: /etc/ssh/sshd_config.d/00-hardening.conf
    mode: "0600"
    validate: /usr/sbin/sshd -t -f %s
  notify: reload ssh

# roles/hardening/tasks/sudo.yml
- name: sudo defaults
  ansible.builtin.copy:
    dest: /etc/sudoers.d/00-defaults
    mode: "0440"
    content: |
      Defaults use_pty
      Defaults logfile="/var/log/sudo.log"
    validate: /usr/sbin/visudo -cf %s

# roles/hardening/tasks/sysctl.yml
- name: Kernel hardening
  ansible.posix.sysctl:
    name: "&#123;&#123; item.key &#125;&#125;"
    value: "&#123;&#123; item.value &#125;&#125;"
    sysctl_file: /etc/sysctl.d/60-hardening.conf
    reload: true
  loop: "&#123;&#123; hardening_sysctl | dict2items &#125;&#125;"

# roles/hardening/tasks/auditd.yml
- name: Audit rules
  ansible.builtin.template: { src: 50-hardening.rules.j2, dest: /etc/audit/rules.d/50-hardening.rules, mode: "0640" }
  notify: load audit rules
- name: auditd running
  ansible.builtin.service: { name: auditd, state: started, enabled: true }

# roles/hardening/tasks/updates.yml
- name: Enable periodic updates
  ansible.builtin.copy:
    dest: /etc/apt/apt.conf.d/20auto-upgrades
    content: |
      APT::Periodic::Update-Package-Lists "1";
      APT::Periodic::Unattended-Upgrade "1";
- name: Local unattended-upgrades policy
  ansible.builtin.template: { src: 52unattended-upgrades-local.j2, dest: /etc/apt/apt.conf.d/52unattended-upgrades-local }

# roles/hardening/tasks/firewall.yml
- name: SSH only from admin networks
  community.general.ufw: { rule: allow, port: "22", proto: tcp, from_ip: "&#123;&#123; item &#125;&#125;" }
  loop: "&#123;&#123; hardening_admin_nets &#125;&#125;"
- name: Default deny incoming and enable        # ⭐ строго ПОСЛЕ allow
  community.general.ufw: { state: enabled, policy: deny, direction: incoming }

# roles/hardening/handlers/main.yml
- name: reload ssh
  ansible.builtin.service: { name: ssh, state: reloaded }
- name: load audit rules
  ansible.builtin.command: augenrules --load
  changed_when: true
```text
Шаблоны: `00-hardening.conf.j2` — drop-in из раздела 2 темы 02 (с `AllowGroups &#123;&#123; hardening_ssh_group &#125;&#125;`),
`50-hardening.rules.j2` — правила из раздела 7 (без `-e 2`), `52unattended-upgrades-local.j2` —
из раздела 4 (`Automatic-Reboot "&#123;&#123; hardening_auto_reboot | lower &#125;&#125;"`).

```bash
cd ~/labs/security/ansible && mkdir -p reports
ansible-galaxy collection install -r requirements.yml
# ДО: Lynis, порты, sshd
ansible sec01 -i inventory.ini -b -m apt -a 'name=lynis state=present update_cache=true'
ansible sec01 -i inventory.ini -b -m shell -a 'lynis audit system --quick --no-colors >/dev/null 2>&1;
  grep -E "^(hardening_index|warning\[\])" /var/log/lynis-report.dat' > reports/lynis-before.txt
ansible sec01 -i inventory.ini -b -m shell -a 'ss -tulpn; sshd -T | grep -Ei "permitroot|passwordauth|allowgroups"' > reports/surface-before.txt
# ПРИМЕНИТЬ
ansible-playbook -i inventory.ini harden.yml --check --diff
ansible-playbook -i inventory.ini harden.yml
ansible-playbook -i inventory.ini harden.yml | tee reports/second-run.txt     # changed=0
# ПОСЛЕ
ansible sec01 -i inventory.ini -b -m shell -a 'lynis audit system --quick --no-colors >/dev/null 2>&1;
  grep -E "^(hardening_index|warning\[\])" /var/log/lynis-report.dat' > reports/lynis-after.txt
```text
### Требования
- [ ] Снапшот `before_lab` сделан, вторая SSH-сессия была открыта при первом прогоне
- [ ] Роль покрывает: пакеты, SSH (drop-in `00-…`, `AllowGroups`), sudo, sysctl, auditd, автообновления, ufw
- [ ] Все шаблоны с `validate` там, где конфиг может сломать доступ (sshd, sudoers)
- [ ] `--check --diff` просмотрен до применения; второй прогон — `changed=0`
- [ ] `vagrant ssh` и Ansible продолжают работать после ufw
- [ ] Пользователь вне `ssh-users` не входит (проверено), root по SSH не входит
- [ ] auditd ловит изменение `/etc/passwd` и root-команды (найдено через `ausearch -k`)
- [ ] `lynis-before.txt` и `lynis-after.txt` сравнены: индекс и ушедшие warnings
- [ ] Для 3 оставшихся suggestions записано «почему не делаю» (осознанные исключения)
- [ ] Бонус: та же роль применена к `rocky01` (ветвление по `ansible_os_family`, `dnf-automatic`, firewalld)

### Критерии приёмки
```bash
ansible-playbook -i inventory.ini harden.yml | grep -E 'changed=0.*failed=0'
ssh sec01 'sudo sshd -T | grep -Ei "^(permitrootlogin|passwordauthentication|allowgroups)"'
#   permitrootlogin no · passwordauthentication no · allowgroups ssh-users
ssh sec01 'sudo auditctl -l | grep -c "key="; sudo ufw status | head -5; sysctl kernel.kptr_restrict'
diff <(grep hardening_index reports/lynis-before.txt) <(grep hardening_index reports/lynis-after.txt)
ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no vagrant@192.168.56.30 true   # → Permission denied
```text
### Вопросы себе
- Что сломается, если кто-то вручную поправит `sshd_config` на сервере, и как роль это обнаружит?
- Почему ufw-правило для SSH идёт до `ufw enable`, а не после?
- Какие пункты Lynis «не про этот сервер», и почему индекс нельзя делать KPI?
- Что из роли нельзя применять к Docker/k8s-узлу без исключений?

---

## 🧪 Лаба 2. ⭐ Security-стадия GitLab CI

### Что делаем
Демо-репозиторий с намеренно старыми зависимостями и фейковым токеном. Строим стадию:
gitleaks по всей истории → Trivy fs (зависимости) → сборка → Trivy image → SBOM → gate с
исключениями. Гоняем локально теми же образами и на gitlab.com.

### Каркас
```python
# ~/labs/security/ci/app.py
from flask import Flask, jsonify

app = Flask(__name__)

@app.get("/healthz")
def healthz():
    return jsonify(status="ok")
```text
```text
# requirements.txt — ⚠️ намеренно старые версии, чтобы сканеру было что найти
flask==2.2.2
werkzeug==2.2.2
requests==2.25.1
```text
```dockerfile
# Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
RUN useradd -u 10001 -r -s /usr/sbin/nologin app
USER 10001
EXPOSE 8080
CMD ["python", "-m", "flask", "--app", "app", "run", "--host", "0.0.0.0", "--port", "8080"]
```text
```bash
cd ~/labs/security/ci && git init -q
# фейковый токен в истории — проверим, что gitleaks смотрит историю, а не только текущие файлы
echo "GITLAB_TOKEN=glpat-$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 20)" > deploy.env
git add . && git commit -qm "init with leaked token" && git rm -q deploy.env && git commit -qm "remove token"
```text
```yaml
# .gitlab-ci.yml
stages: [lint, build, scan]

variables:
  TRIVY_IMAGE: aquasec/trivy:0.74.0@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969
  IMAGE: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  TRIVY_CACHE_DIR: .trivycache/

.trivy:
  image: { name: $TRIVY_IMAGE, entrypoint: [""] }
  cache: { key: trivy-db, paths: [.trivycache/] }

secrets:gitleaks:
  stage: lint
  image: { name: "zricethezav/gitleaks:v8.30.1", entrypoint: [""] }   # в проде — тоже по digest
  variables: { GIT_DEPTH: "0" }            # ⭐ вся история, а не последние коммиты
  script:
    - gitleaks git --redact --verbose --report-format sarif --report-path gitleaks.sarif .
  artifacts: { when: always, paths: [gitleaks.sarif], expire_in: 30 days }

deps:trivy-fs:
  extends: .trivy
  stage: lint
  script:
    - trivy fs --scanners vuln,misconfig --format json -o fs-report.json .          # полный отчёт
    - trivy fs --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1
        --ignorefile .trivyignore.yaml --show-suppressed .                           # gate по зависимостям
  artifacts: { when: always, paths: [fs-report.json], expire_in: 30 days }

build:
  stage: build
  image: docker:29                         # сборка — как в ../CICD/07_gitlab_ci_docker.md (dind)
  services: [docker:29-dind]
  variables: { DOCKER_TLS_CERTDIR: "/certs" }
  script:
    - echo "$CI_REGISTRY_PASSWORD" | docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
    - docker build --pull -t "$IMAGE" .
    - docker push "$IMAGE"

scan:image:
  extends: .trivy
  stage: scan
  needs: [build]
  variables:                               # только read-доступ к registry, никаких deploy-секретов
    TRIVY_USERNAME: $CI_REGISTRY_USER
    TRIVY_PASSWORD: $CI_REGISTRY_PASSWORD
  script:
    - trivy image --scanners vuln --format json -o image-report.json "$IMAGE"
    - trivy image --format cyclonedx -o sbom.cdx.json "$IMAGE"
    - trivy image --scanners vuln --pkg-types os --severity CRITICAL --ignore-unfixed --exit-code 1
        --ignorefile .trivyignore.yaml --show-suppressed "$IMAGE"                    # gate по ОС
  artifacts:
    when: always
    paths: [image-report.json, sbom.cdx.json]
    expire_in: 1 year                      # SBOM живёт столько же, сколько образ в проде
```text
```bash
# ci/local-scan.sh — то же самое локально, теми же образами
set -euo pipefail
TRIVY="docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v trivy-cache:/root/.cache -v $PWD:/src -w /src aquasec/trivy:0.74.0"
docker run --rm -v "$PWD":/repo zricethezav/gitleaks:v8.30.1 git --redact --verbose /repo || echo "gitleaks: FAIL"
$TRIVY fs --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 --ignorefile .trivyignore.yaml . || echo "deps gate: FAIL"
docker build --pull -t lab/app:dev .
$TRIVY image --format cyclonedx -o sbom.cdx.json lab/app:dev
$TRIVY image --scanners vuln --pkg-types os --severity CRITICAL --ignore-unfixed --exit-code 1 lab/app:dev || echo "os gate: FAIL"
```text
### Требования
- [ ] gitleaks находит токен **в истории** (в текущих файлах его нет); `GIT_DEPTH: "0"` объяснён
- [ ] Trivy fs находит HIGH в старых зависимостях, gate по зависимостям красный
- [ ] Зависимости обновлены до версий без находок (Renovate-конфиг из темы 04 добавлен в репо), gate зелёный
- [ ] Gate по ОС: CRITICAL с фиксом; полный отчёт — артефакт; `--show-suppressed` в логе
- [ ] Одно исключение в `.trivyignore.yaml` с `purls`/`paths`, `expired_at`, `statement` (тикет + владелец)
- [ ] Проверено: исключение с датой в прошлом снова роняет gate
- [ ] SBOM (CycloneDX) — артефакт; через `jq` найдены версии `flask` и `openssl`; SBOM пересканирован `trivy sbom`
- [ ] Образ сканера запинен по digest; scan-джобы не видят deploy-переменных
- [ ] Фейковый токен «ротирован» (в реальности — отзыв в GitLab) и история почищена `git filter-repo`
- [ ] Бонус: `pre-commit`-хук с gitleaks не даёт закоммитить новый токен

### Критерии приёмки
```bash
cd ~/labs/security/ci
docker run --rm -v "$PWD":/repo zricethezav/gitleaks:v8.30.1 git /repo; echo "exit=$?"   # 1 до чистки, 0 после
bash local-scan.sh 2>&1 | grep -E 'FAIL|Total' ; echo "---"
jq -r '.components[] | select(.name|test("^(flask|openssl|werkzeug)$")) | "\(.name) \(.version)"' sbom.cdx.json
yq '.["scan:image"].image.name' .gitlab-ci.yml 2>/dev/null || grep -n 'sha256:' .gitlab-ci.yml
```text
### Вопросы себе
- Почему токен, удалённый следующим коммитом, всё равно считается утёкшим?
- Почему gate по ОС только на CRITICAL с фиксом, а по зависимостям — на HIGH?
- Что произошло бы с этим пайплайном 19–20 марта 2026, если бы образ сканера был `:latest`?
- Где хранить SBOM и сколько, если образ живёт в проде год?

---

## 🧪 Лаба 3. kind: kube-bench, PSA, Kyverno, Falco

### Что делаем
На кластере `sec` с аудитом: снимаем CIS-картину kube-bench, переводим прикладной namespace на
PSA restricted, раскатываем Kyverno-политики Audit → Deny, проверяем подписи и ловим Falco'м
`kubectl exec` и пакетный менеджер. Всё — манифестами в `k8s/policies/`.

### Каркас
```bash
cd ~/labs/security/k8s
kind create cluster --config kind-config.yaml          # из 00_INDEX: аудит включён
mkdir -p reports policies
# 1. kube-bench (в default: ему нужны hostPID и hostPath)
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job.yaml
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job-master.yaml
kubectl wait --for=condition=complete job/kube-bench job/kube-bench-master --timeout=180s
kubectl logs job/kube-bench > reports/kube-bench-node.txt
kubectl logs job/kube-bench-master > reports/kube-bench-master.txt
# 2. приложение и PSA
kubectl create ns app
kubectl -n app create deployment web --image=nginx --replicas=2
kubectl label --dry-run=server --overwrite ns app pod-security.kubernetes.io/enforce=restricted
kubectl label ns app pod-security.kubernetes.io/warn=restricted pod-security.kubernetes.io/audit=restricted
# ... чинишь манифест (раздел 3 темы 06), затем:
kubectl label --overwrite ns app pod-security.kubernetes.io/enforce=restricted pod-security.kubernetes.io/enforce-version=v1.37
# 3. Kyverno
helm repo add kyverno https://kyverno.github.io/kyverno/ && helm repo update
helm upgrade --install kyverno kyverno/kyverno -n kyverno --create-namespace \
  --set features.policyExceptions.enabled=true --set features.policyExceptions.namespace=kyverno-exceptions
kubectl apply -f policies/          # allowed-registries (Audit), default-seccomp, verify-test-image
# 4. Falco
helm repo add falcosecurity https://falcosecurity.github.io/charts && helm repo update
helm install falco falcosecurity/falco -n falco --create-namespace \
  --set driver.kind=modern_ebpf --set tty=true -f falco-values.yaml
```text
Манифесты политик — из разделов 5–7 темы [06_k8s_security.md](/security/06-k8s-security); `falco-values.yaml` —
`customRules` с правилом «Package manager in container» из раздела 9.

### Требования
- [ ] kube-bench: summary записан, 3 FAIL разобраны («исправить» / «особенность kind» / «принятый риск» с причиной)
- [ ] `app`: примерка показала нарушения, `web` починен (non-root образ, securityContext, emptyDir), enforce=restricted с версией
- [ ] Привилегированный под в `app` отклоняется (сообщение PSA сохранено)
- [ ] Kyverno `allowed-registries`: Audit → PolicyReport с нарушением → Deny; одна PolicyException в `kyverno-exceptions`
- [ ] MutatingPolicy проставляет `seccompProfile: RuntimeDefault` поду без securityContext
- [ ] ImageValidatingPolicy пускает `test-verify-image:signed` и режет `:unsigned`
- [ ] VAP `deny-latest-tag` с binding: `[Warn, Audit]` → `[Deny]`
- [ ] Falco ловит `kubectl exec -it … -- sh` и своё правило на `apk add`/`apt-get`
- [ ] В аудит-логе найдены: exec, чтение Secret, отклонённый PSA-под
- [ ] Kyverno admission-контроллер с 3 репликами (или записано, почему на стенде 1 и чем это грозит)

### Критерии приёмки
```bash
grep -A4 '== Summary total ==' reports/kube-bench-node.txt
kubectl get ns app --show-labels | grep -o 'pod-security[^,]*'
kubectl -n app run bad --image=busybox --overrides='{"spec":{"containers":[{"name":"b","image":"busybox","securityContext":{"privileged":true&#125;&#125;]&#125;&#125;' 2>&1 | head -2
kubectl get validatingpolicies,mutatingpolicies,imagevalidatingpolicies 2>/dev/null
kubectl get policyreport -A
kubectl run unsigned --image=ghcr.io/kyverno/test-verify-image:unsigned 2>&1 | head -2
kubectl -n app exec -it deploy/web -- sh -c 'id' ; \
  kubectl logs -n falco -l app.kubernetes.io/name=falco -c falco --since=5m | grep -iE 'shell|package'
docker exec sec-control-plane cat /var/log/kubernetes/kube-apiserver-audit.log \
  | jq -c 'select(.objectRef.subresource=="exec") | {user: .user.username, pod: .objectRef.name}' | tail -3
```text
### Вопросы себе
- Почему Deployment применился, а подов не было, и где это видно?
- Что будет с кластером, если под Kyverno выселят при `failurePolicy: Fail`?
- Какие FAIL kube-bench — «особенность kind», а какие ты бы обязательно исправил в проде?
- Почему `kubectl -n app exec … -- sh -c id` ловится (или не ловится) правилом «Terminal shell in container»?
  (Подсказка: `-it` и `proc.tty`.)

---

## 🧪 Лаба 4. Аудит своего периметра: nmap + testssl.sh

### Что делаем
Смотрим на edge-стенд глазами внешнего сканера, фиксируем находки, исправляем по теме 03 и
доказываем результат повторным прогоном. Пишем короткий отчёт как для команды.

### Каркас
```bash
cd ~/labs/security/edge && mkdir -p reports/before reports/after
docker compose up -d                                   # стартовый (слабый) app.conf из 00_INDEX
# ДО
nmap -sV -p- 127.0.0.1 -oN reports/before/nmap.txt
nmap -p 8443 --script ssl-enum-ciphers 127.0.0.1 -oN reports/before/ciphers.txt
docker run --rm -t --network host -v "$PWD/certs":/certs:ro -v "$PWD/reports/before":/out \
  ghcr.io/testssl/testssl.sh:3.2 --ip 127.0.0.1 --add-ca /certs/ca.crt -p -S -h -U \
  --jsonfile /out/testssl.json https://app.lab.local:8443
curl -skI https://app.lab.local:8443/ > reports/before/headers.txt
curl -sI http://app.lab.local:8080/  >> reports/before/headers.txt
for i in $(seq 60); do curl -sk -o /dev/null -w '%{http_code}\n' https://app.lab.local:8443/; done \
  | sort | uniq -c > reports/before/ratelimit.txt
# ИСПРАВЛЕНИЯ: итоговый app.conf из раздела 7 темы 03 → nginx -t → reload
docker compose exec nginx nginx -t && docker compose exec nginx nginx -s reload
# WAF
docker compose --profile waf up -d waf
curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:8081/?id=1'%20OR%20'1'='1"
# ПОСЛЕ — те же команды в reports/after/
```text
```markdown
<!-- reports/summary.md -->
| # | Находка | Риск | Исправление | Проверка после |
|---|---------|------|-------------|----------------|
| 1 | Версия nginx в заголовке Server | Low | server_tokens off | curl -I |
| 2 | Нет HSTS/CSP/nosniff | Medium | сниппет заголовков с always | curl -I, testssl -h |
| … |
```text
### Требования
- [ ] Отчёты «до»: nmap (порты, версии), шифры, testssl JSON, заголовки, распределение кодов под нагрузкой
- [ ] Все порты стенда слушают только 127.0.0.1; с `sec01` они не видны (проверено nmap с `sec01`)
- [ ] HTTP → 301 на HTTPS; `server_tokens off`; свои error pages (при остановленном `app` — своя 502)
- [ ] TLS только 1.2/1.3, ECDHE+AEAD; testssl «после» без предупреждений по протоколам и шифрам
- [ ] HSTS (короткий `max-age` на стенде), CSP, nosniff, Referrer-Policy, Permissions-Policy — и на ответах 4xx/5xx
- [ ] Rate limit отвечает 429 (не 503), `/login` — отдельный лимит; ловушка `X-Forwarded-For` проверена
- [ ] WAF: DetectionOnly → найдены `ruleId` → одно исключение для ложного срабатывания → On, атаки → 403
- [ ] `reports/summary.md`: 6+ находок с риском, исправлением и доказательством

### Критерии приёмки
```bash
curl -skI https://app.lab.local:8443/ | grep -ciE 'strict-transport|content-security|nosniff|referrer-policy|permissions-policy'   # 5
curl -skI https://app.lab.local:8443/ | grep -i '^server:'                                                            # без версии
curl -sI http://app.lab.local:8080/ | head -1                                                                         # 301
for i in $(seq 60); do curl -sk -o /dev/null -w '%{http_code}\n' https://app.lab.local:8443/; done | sort | uniq -c   # 200 и 429, без 503
jq -r '.[] | select(.id|test("^TLS1$|^TLS1_1$|^SSLv")) | "\(.id) \(.finding)"' reports/after/testssl.json          # not offered
curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:8081/?id=1'%20OR%20'1'='1"                                 # 403
```text
### Вопросы себе
- Что увидел бы внешний сканер, если бы порты были опубликованы на `0.0.0.0`?
- Почему HSTS на стенде — `max-age=300`, а в проде — год, и что будет, если перепутать?
- Какой из найденных `ruleId` CRS был ложным срабатыванием и как ты это доказал?
- Какие находки testssl.sh ты бы не стал исправлять и почему?

---

## 🧪 Лаба 5. Game day «утёк токен»

### Что делаем
Учения по playbook утечки секрета. Ведущий «теряет» токен Vault с доступом к прод-секретам в
git-репозиторий и использует его как атакующий. Команда (или ты в нескольких ролях) проходит
detect → contain → eradicate → recover → lessons и пишет таймлайн и постмортем.

### Подготовка (за день, ведущий)
```yaml
# ~/labs/security/ir/docker-compose.yml — ⚠️ dev-режим: только для учёбы
services:
  vault:
    image: hashicorp/vault:2.1
    cap_add: [IPC_LOCK]
    environment:
      VAULT_DEV_ROOT_TOKEN_ID: root
      VAULT_DEV_LISTEN_ADDRESS: 0.0.0.0:8200
    ports: ["127.0.0.1:8200:8200"]
```text
```bash
cd ~/labs/security/ir && docker compose up -d
export VAULT_ADDR=http://127.0.0.1:8200 VAULT_TOKEN=root
vault audit enable file file_path=/vault/logs/audit.log hmac_accessor=false   # accessor в логе открыто
vault kv put secret/prod/db username=linkd password="$(openssl rand -hex 16)"
vault kv put secret/prod/s3 access_key=lab secret_key="$(openssl rand -hex 20)"
vault policy write app-ro - <<'EOF'
path "secret/data/prod/*" { capabilities = ["read"] }
EOF
vault token create -policy=app-ro -ttl=720h -display-name=ci-deploy -format=json > /tmp/leak.json
jq -r .auth.accessor /tmp/leak.json > /tmp/leak.accessor      # ведущий держит у себя
# «утечка»: токен попадает в репозиторий
mkdir -p demo-repo && cd demo-repo && git init -q
echo "VAULT_TOKEN=$(jq -r .auth.client_token /tmp/leak.json)" > deploy.env
git add deploy.env && git commit -qm "add deploy config"
```text
- [ ] Роли: **ведущий** (утечка, «атакующий», следит за безопасностью учений), **IC**, **Ops**,
      **Comms**, **Scribe**. Соло — ведущий запускает «атаку» по таймеру со случайной задержкой
- [ ] Playbook из темы 07 (C1) и шаблон таймлайна (C8) под рукой
- [ ] Гипотеза записана: как обнаружим (gitleaks в CI? алерт?), за сколько минут, что сделаем первым
- [ ] Условия остановки: 60–90 минут, стенд не нужен для другого

### Проведение
```text
T+0    ведущий «атакует» с другого контейнера, фиксирует время:
       docker run --rm --network ir_default -e VAULT_ADDR=http://vault:8200 \
         -e VAULT_TOKEN=&lt;токен из deploy.env&gt; hashicorp/vault:2.1 vault kv get secret/prod/db
T+?    detect:   gitleaks по demo-repo (правило vault-service-token) или «звонок исследователя»
       triage:   SEV, IC, закрытый канал/файл инцидента, первый апдейт
       contain:  ⭐ СНАЧАЛА отозвать токен: vault token revoke -accessor &lt;accessor&gt;
       scope:    что токен читал — Vault audit log по accessor, с каких адресов
       rotate:   всё, что он мог прочитать: secret/prod/db и secret/prod/s3 (новые значения)
       clean:    git filter-repo / новый репозиторий без истории; pre-commit gitleaks
T+end  ведущий раскрывает сценарий; 15 минут горячего разбора: гипотеза против факта
```text
```bash
# scope: что делал утёкший токен
docker compose exec vault cat /vault/logs/audit.log \
  | jq -c --arg a "$(cat /tmp/leak.accessor)" 'select(.auth.accessor==$a)
      | {time, type, path: .request.path, op: .request.operation, ip: .request.remote_address}'
```text
> 💡 Если gitleaks не нашёл токен — посмотри, под какой regex попадает `vault-service-token`
> (`gitleaks` config), и добавь своё правило в `.gitleaks.toml`. Это тоже результат учений.

### Требования
- [ ] Таймлайн в UTC: утечка, «атака», обнаружение, отзыв, ротация, чистка — с авторами действий
- [ ] ⭐ Первое действие после подтверждения — отзыв токена (не удаление файла из git)
- [ ] По audit log доказано, какие пути читал токен и с какого адреса; после отзыва — `permission denied`
- [ ] Ротированы **оба** секрета из зоны доступа токена, старые значения больше не работают
- [ ] История репозитория очищена; pre-commit с gitleaks блокирует повторную утечку
- [ ] Посчитаны MTTD и время от обнаружения до отзыва (MTTC); сравнены с гипотезой
- [ ] Отмечено, были ли затронуты «персональные данные» и нужно ли было бы уведомление (закон РК — 1 рабочий день)
- [ ] Постмортем по шаблону [../SRE/05_postmortems.md](/sre/05-postmortems) с 3–5 action items
      (хотя бы один — «убрать класс проблемы»: короткий TTL, AppRole/OIDC вместо статичного токена)

### Критерии приёмки
```text
ir/gameday/2026-10-xx/
├── plan.md            # роли, гипотеза, условия остановки
├── timeline.md        # UTC, события, решения, авторы
├── evidence/          # выдержки audit log + SHA256SUMS
├── updates.md         # статус-апдейты в закрытый канал
└── postmortem.md      # влияние, факторы, хорошо/плохо/повезло, action items
```text
```bash
VAULT_TOKEN=$(jq -r .auth.client_token /tmp/leak.json) vault token lookup 2>&1 | grep -i 'bad token\|permission denied'
docker run --rm -v "$PWD/demo-repo":/repo zricethezav/gitleaks:v8.30.1 git /repo; echo "exit=$?"   # 0
```text
### Вопросы себе
- Сколько времени токен был действующим после попадания в git и почему это главная метрика?
- Что изменилось бы, будь токен выдан с TTL 1 час или через AppRole/OIDC?
- Почему ротировали `secret/prod/s3`, если атакующий читал только `db`? (Или читал?)
- Как изменились бы шаги, если бы репозиторий был публичным?

---

## 🏁 Что должно остаться после блока

```text
~/labs/security/                   # репозиторий стенда
├── vagrant/Vagrantfile
├── ansible/roles/hardening/ + reports/lynis-{before,after}.txt
├── edge/nginx/conf.d/app.conf + reports/{before,after}/ + summary.md
├── ci/.gitlab-ci.yml, .trivyignore.yaml, renovate.json, local-scan.sh, docs/vuln-sla.md
├── k8s/kind-config.yaml, audit-policy.yaml, policies/, falco-values.yaml, reports/kube-bench-*.txt
├── ir/playbooks/, gameday/…/timeline.md, postmortem.md
└── docs/threat-model.md          # тема 01
```text
Это превращает «знаю про безопасность» в «вот threat model, вот роль харденинга с отчётом,
вот CI, который ловит токен в истории, вот политики кластера и таймлайн учебного инцидента».

➡️ Дальше: [09_interview.md](/softskills/09-interview)
