---
title: "08. Секреты и безопасность"
description: "Цель этапа: убрать из портфолио последние ручные kubectl create secret, свести"
---

# 08. Секреты и безопасность

> **Цель этапа:** убрать из портфолио последние ручные `kubectl create secret`, свести
> все секреты — ВМ, CI, кластер — в одну понятную схему на базе результатов 13-strongbox
> и 06-fleet и закрутить гайки: минимальные права, сетевые политики, non-root,
> проверки в CI.
>
> **После этапа у тебя есть:** `docs/secrets.md` (инвентаризация секретов), настройки
> Vault как код в `infra/vault/` (без значений), ExternalSecret'ы в `linkd-gitops` вместо
> ручных Secret, NetworkPolicy и Pod Security `restricted` в dev/prod, gitleaks и
> `trivy config` в CI, раздел «Безопасность» в README.
>
> **~время:** 3–5 часов (после проектов).

---

## 🧪 Откуда берём

| Проект | Что забираешь | Когда готово |
|--------|---------------|--------------|
| 🛠️ **13-strongbox** — секреты в Vault · `README` · `~/Projects/devops/13-strongbox` | структуру KV, политики, AppRole, пароль БД linkd из Vault, database secrets engine, k8s auth + ESO | `./check.sh` зелёный |
| 🛠️ **06-fleet** · `README` · `~/Projects/devops/06-fleet` | ansible-vault и файл пароля вне репо — для VM-трека | задача про секреты сделана |
| 🛠️ **05-conveyor** · `README` · `~/Projects/devops/05-conveyor` | «секреты не в репозитории», переменные CI | уже в этапе 03 |
| 🛠️ **04-shipyard** · `README` · `~/Projects/devops/04-shipyard` | «ни одного секрета в образе» | уже в этапе 02 |
| 🛠️ **07-orbit** · `README` · `~/Projects/devops/07-orbit` | NetworkPolicy из задачи «полный стек» | уже в этапе 05 |

---

## 🎯 Цель

Безопасность — не один инструмент, а слои (defense in depth):

| Слой | Угроза | Что в портфолио |
|------|--------|-----------------|
| Секреты | пароль в git, в CI-логе, в образе | Vault + ESO, ansible-vault, protected-переменные; в git — только ссылки |
| Доступ к кластеру | утёкший CI-токен = доступ к проду | GitOps: у CI нет kubeconfig; AppProject; RBAC |
| Сеть | взломанный под ходит куда угодно | NetworkPolicy: default deny + явные разрешения |
| Контейнер | побег, запись в ФС | non-root, read-only FS, drop ALL, seccomp, PSA `restricted` |
| Цепочка поставки | уязвимая библиотека, базовый образ | Trivy (образ + манифесты), gitleaks, пины версий |

Каждый проект закрывал свой кусок. Ценность портфолио — **одна картина**: где лежит
каждый секрет, кто его читает, как он доставляется и что делать при утечке.

---

## 🗺️ Что получится

```text
                        ┌──────────────── Vault ────────────────┐
                        │ KV: secret/&lt;env&gt;/linkd/…              │
                        │ database engine: креды PostgreSQL (13)│
                        │ auth: AppRole · kubernetes            │
                        └───────┬─────────────────────┬─────────┘
                    k8s auth    │                     │ AppRole
                                ▼                     ▼
  External Secrets ─► Secret ─► linkd, postgres,   скрипты и утилиты
                                backup-CronJob     (tools/, этап 09)

  ansible-vault ─► web1/web2/db1 (VM-трек)     GitLab CI Variables ─► токен gitops, registry

  NetworkPolicy в dev/prod:
    ingress-controller ──► linkd :порт ◄── monitoring (скрейп)
                             └──► postgres :5432 ◄── backup-джобы
    всё остальное — deny;  PSA: enforce=restricted
```text
---

## 🪜 Шаги

### 1. Проекты зелёные

```bash
cd ~/Projects/devops/13-strongbox && ./check.sh
```text
### 2. Инвентаризация секретов — `docs/secrets.md`

Главный артефакт этапа. Заполняется по всему портфолио, а не по одному проекту:

| Секрет | Где хранится | Кто читает | Как доставляется | Ротация | При утечке |
|--------|--------------|-----------|------------------|---------|-----------|
| пароль БД linkd (prod) | Vault KV или database engine | linkd, backup | ESO → Secret → env | … | … |
| пароль БД на ВМ | ansible-vault | Ansible | шаблон env-файла юнита | … | … |
| токен CI → gitops | GitLab CI Variables | bump-job | protected + masked | срок токена | отозвать, выпустить новый |
| ключи MinIO для бэкапов | Vault KV | backup-CronJob | ESO | … | … |
| токен Telegram-бота | Vault KV | Alertmanager | ESO | … | … |
| пароль admin Grafana | Vault KV | Grafana | ESO | … | … |
| пароль ansible-vault | файл вне репо / менеджер паролей | человек | — | … | перешифровать |
| root-токен / unseal Vault | менеджер паролей | человек | — | … | … |

### 3. Перенос настроек Vault

Из 13-strongbox → `infra/vault/`: политики, включение auth-методов и секрет-движков,
скрипт первичного наполнения. Значения секретов в репозиторий **не** попадают — скрипт
читает их из файла вне git (путь описан в README, пример файла — `*.example` без значений).

### 4. Ручные Secret → ExternalSecret

- всё, что на этапах 05–07 создавалось `kubectl create secret`, теперь создаёт ESO;
  манифесты SecretStore/ExternalSecret — в `linkd-gitops` (как в 13-strongbox, но
  под namespace'ы и имена портфолио);
- имя итогового Secret совпадает с тем, на которое уже ссылается чарт, — переезд без
  правок чарта;
- Vault и ESO — платформенные Argo-приложения с ранней волной синхронизации;
- **VM-трек:** ansible-vault из 06-fleet или AppRole из 13-strongbox — выбери и запиши в ADR.

Если в 13-strongbox доведены динамические креды PostgreSQL — опиши в README, как linkd
их получает и что происходит по истечении TTL. Если нет — статический пароль в KV
плюс процедура ротации в `docs/secrets.md`.

### 5. Гигиена кластера (поверх проектов)

Требования — проверяются командами, манифесты пишутся по знаниям из 07-orbit и теории:

- **NetworkPolicy:** default deny на входящий трафик в dev/prod и явные разрешения —
  ingress-controller → linkd, monitoring → linkd (скрейп), linkd и backup → postgres,
  ESO → Vault. Проверка — **запретом**: посторонний под не достучится до PostgreSQL.
- **Pod Security Admission:** `enforce: restricted` на namespace'ах приложения;
  привилегированный под отклоняется.
- **RBAC:** у ServiceAccount linkd нет прав на API (`automountServiceAccountToken: false`);
  `kubectl auth can-i --list` для него — пусто по существу.

### 6. Проверки в CI

- gitleaks по **всей истории** обоих репозиториев;
- `trivy config` по чарту с prod-values и по манифестам в `linkd-gitops`;
- локально — pre-commit хук с gitleaks, чтобы секрет не попал даже в локальный коммит.

### 7. README и ADR

- Раздел «Безопасность»: таблица слоёв, короткая выжимка из `docs/secrets.md`,
  что проверяется в CI.
- ADR «Режим Vault»: dev-режим (данные в памяти, пропадают при рестарте) или standalone
  с хранилищем и unseal — осознанный компромисс.
- ADR «ESO, а не Sealed Secrets или Agent Injector».

### 8. Коммит

```bash
git -C ~/Projects/linkd-platform add infra/vault docs README.md .gitlab-ci.yml
git -C ~/Projects/linkd-platform commit -m "security: vault config, secrets inventory, CI checks"
git -C ~/Projects/linkd-gitops add apps data platform
git -C ~/Projects/linkd-gitops commit -m "security: external secrets, network policies, PSA restricted"
```text
---

## ✅ Критерии приёмки

- [ ] gitleaks по обоим репозиториям (вся история) — чисто
- [ ] `docs/secrets.md` покрывает все секреты портфолио: ВМ, CI, кластер, человек
- [ ] Все Secret в кластере создаются ESO; `kubectl create secret` больше не нужен
- [ ] Удалённый вручную Secret восстанавливается ESO
- [ ] Роль Vault для dev не читает prod-пути (проверено)
- [ ] Посторонний под не достучится до PostgreSQL; linkd, Prometheus и бэкап работают
- [ ] Namespace'ы приложения в `enforce: restricted`, все поды запущены
- [ ] CI проверяет чарт, манифесты и историю на секреты
- [ ] Можешь объяснить, что будет при рестарте Vault в выбранном режиме и как это чинится

---

## 🪤 Грабли

- **Смена пароля в Vault не меняет пароль в БД.** `POSTGRES_PASSWORD` официального
  образа читается только при первой инициализации. Ротация = смена роли в БД + новое
  значение в Vault + рестарт клиентов.
- **Secret обновился — под не заметил.** Переменные окружения не обновляются в
  запущенном контейнере; нужен рестарт (или контроллер вроде Reloader).
- **Рестарт Vault в dev-режиме** — после пересоздания кластера секретов нет вообще.
  Скрипт наполнения — часть runbook'а восстановления (этап 09).
- **Адрес Kubernetes API для k8s auth указан «с ноутбука».** Vault ходит в API изнутри
  кластера.
- **NetworkPolicy «не работает»** — CNI её не поддерживает, политики молча игнорируются.
  Проверяй запрет, а не только разрешение.
- **Default deny сломал забытое:** скрейп Prometheus, бэкап-джобы, ESO → Vault.
- **Порт в NetworkPolicy — порт контейнера**, а не Service.
- **Egress deny без DNS** — ломается резолвинг вообще всего.
- **PSA `restricted` и образ PostgreSQL** — без числового UID и seccomp под отклоняется.
  Перед включением — `kubectl label --dry-run=server`.
- **Секрет в выводе CI:** `set -x`, отладочный `echo`, `helm template` с секретами в values.
- **Секрет попал в историю git** — удалить мало, его нужно **ротировать**.

---

## 🤔 Вопросы себе

1. Почему Secret в Kubernetes — не шифрование? Что такое encryption at rest для etcd?
2. Как под linkd получает пароль из Vault — по шагам, включая аутентификацию?
3. Чем External Secrets отличается от Sealed Secrets и от Vault Agent Injector?
4. Как ротировать пароль БД без простоя? Чем здесь помогают динамические креды?
5. Что такое default deny и почему политики пишут «разрешающими»?
6. Зачем Pod Security Admission, если securityContext уже прописан в чарте?
7. Что сможет злоумышленник, укравший токен CI для gitops-репо? А kubeconfig?
8. Что делать, если секрет всё-таки попал в git?
9. Чем ansible-vault отличается от HashiCorp Vault и где уместен каждый?

---

## 📚 Теория в волте

- Проблема секретов: [../Left/08_Vault/01_secrets_problem.md](/vault/01-secrets-problem)
- Vault, KV, auth methods: [../Left/08_Vault/02_vault_intro.md](/vault/02-vault-intro),
  [../Left/08_Vault/03_kv_engine.md](/vault/03-kv-engine),
  [../Left/08_Vault/04_auth_methods.md](/vault/04-auth-methods)
- Vault + Kubernetes/ESO: [../Left/08_Vault/05_vault_integrations.md](/vault/05-vault-integrations)
- Секреты в GitOps (SOPS/Sealed/ESO): [../Left/07_ArgoCD/05_helm_kustomize.md](/argocd/05-helm-kustomize)
- Secret в Kubernetes: [../Kubernetes/08_configmap_secret.md](/kubernetes/08-configmap-secret)
- NetworkPolicy: [../Kubernetes/13_networkpolicy.md](/kubernetes/13-networkpolicy)
- RBAC: [../Kubernetes/17_rbac.md](/kubernetes/17-rbac)
- Безопасность контейнеров: [../Docker/10_security_best_practices.md](/docker/10-security-best-practices)
- Сканеры и секреты в CI: [../CICD/13_quality_security.md](/cicd/13-quality-security)
- Секреты в истории git: [../../IT/Git/12_git_in_devops.md](/git/12-git-in-devops)
- Ansible Vault: [../Ansible/12_vault.md](/ansible/12-vault)

➡️ Следующий этап: [09_backup_dr.md](/project/09-backup-dr)
