---
title: "04. Инфраструктура: Terraform, Ansible и кластер одной командой"
description: "IaC: Terraform + Ansible, два трека деплоя"
---

# 04. Инфраструктура: Terraform, Ansible и кластер одной командой

> **Цель этапа:** собрать в `infra/` результаты 11-blueprint (Terraform) и 06-fleet
> (Ansible), связать их между собой и с остальным портфолио и показать разделение
> ответственности «ресурсы → ОС → кластер» прямо по каталогам.
>
> **После этапа у тебя есть:** `infra/terraform/`, `infra/ansible/` + `infra/vagrant/`,
> `infra/kind/`, единая точка входа в `Makefile`, VM-трек деплоя linkd 2.0 с PostgreSQL
> на `db1` (полная версия), раздел «Инфраструктура» в README и ADR.
>
> **~время:** 3–6 часов (после проектов).

---

## 🧪 Откуда берём

| Проект | Что забираешь | Когда готово |
|--------|---------------|--------------|
| 🛠️ **11-blueprint** — инфраструктура кодом · `README` · `~/Projects/devops/11-blueprint` | модули, окружения dev/prod, backend с state в MinIO, опыт import и drift | `./check.sh` зелёный |
| 🛠️ **06-fleet** — управление парком машин · `README` · `~/Projects/devops/06-fleet` | `Vagrantfile`, `ansible.cfg`, `inventories/{dev,prod}`, `group_vars/`, роли, плейбуки, ansible-vault | `./check.sh` зелёный |
| 🛠️ **07-orbit** / **12-autopilot** · `07` · `12` · `~/Projects/devops/07-orbit`, `~/Projects/devops/12-autopilot` | конфиг kind-кластера (порты под Ingress) | к этапам 05–06 |
| 🛠️ **02-nightshift** · `README` · `~/Projects/devops/02-nightshift` | требования к юниту (non-root, рестарт, hardening) — в шаблон роли | уже сделано в проекте |

Инциденты Linux и сети из `99-incidents`
(`~/Projects/devops/99-incidents`) — истории для журнала.

---

## 🎯 Цель

Главное здесь — не «ещё раз поднять инфраструктуру», а **разграничить ответственность**
и показать это в одном репозитории:

| | Terraform | Ansible | Argo CD (этап 06) |
|---|---|---|---|
| Уровень | Ресурсы | Внутри ОС | Внутри кластера |
| В linkd-platform | ресурсы стенда через docker provider, state в MinIO | ВМ web1/web2/db1: пакеты, пользователи, linkd под systemd, PostgreSQL | приложение, БД, мониторинг, секреты |
| Модель | декларативная, state | идемпотентные задачи | декларативная, git = state |
| Не делает | не лезет внутрь ВМ | не создаёт ресурсы | не трогает ОС и хост |

На собесе это звучит как *«Terraform или Ansible?»*. Ответ — «оба, у них разные слои»,
и в портфолио это видно по каталогам и README.

Второй сюжет этапа — **два трека деплоя одного сервиса**: классический (ВМ + Ansible +
systemd) и современный (Kubernetes + Helm + Argo CD). Работодатели с «железом» и
работодатели с кубером увидят каждый своё.

---

## 🗺️ Что получится

```text:no-line-numbers
 infra/
 ├── terraform/                 ← 11-blueprint
 │   ├── modules/
 │   ├── envs/{dev,prod}/       backend → MinIO, переменные окружений
 │   └── README.md              что принадлежит Terraform, как читать plan, drift, import
 ├── vagrant/Vagrantfile        ← 06-fleet: web1, web2, db1
 ├── ansible/                   ← 06-fleet
 │   ├── inventories/{dev,prod}/
 │   ├── group_vars/  roles/  playbooks/
 │   └── README.md              откуда берётся пароль vault (не из репо)
 └── kind/cluster.yaml          ← 07-orbit / 12-autopilot

 make infra   ─► terraform apply            ресурсы стенда вне кластера
 make vms     ─► vagrant up + ansible       VM-трек: nginx ─► linkd@web1/web2 ─► PostgreSQL@db1
 make cluster ─► kind create + bootstrap    k8s-трек (этапы 05–06)
```

---

## 🪜 Шаги

### 1. Проекты зелёные

```bash
cd ~/Projects/devops/11-blueprint && ./check.sh
cd ~/Projects/devops/06-fleet && ./check.sh
```

### 2. Перенос и `.gitignore`

Раскладка — как в схеме. До первого коммита в `.gitignore`: `*.tfstate*`, `.terraform/`,
`*.tfvars` с секретами, файл пароля ansible-vault, сгенерированные inventory и
kubeconfig, `.vagrant/`. **Коммитится** `.terraform.lock.hcl` — он фиксирует версии
провайдеров.

Проверка, что ничего лишнего не уехало: `git status --ignored` и глазами по `git diff --cached`.

### 3. Что добавить поверх проектов

**Terraform — границы и выходы.** В `infra/terraform/README.md` запиши, какие ресурсы
стенда принадлежат Terraform (всё, что создаёт 11-blueprint) и что из них используют
другие части портфолио: бакет state, бакет бэкапов для этапа 09, адреса сервисов.
Имена и адреса другие части берут из `terraform output`, а не копипастой по файлам —
тогда переименование бакета не ломает бэкапы молча.

**Ansible — linkd 2.0 вместо 1.x (полная версия).** Роль из 06-fleet ставит linkd 1.x
с SQLite. В портфолио:
- `db1` получает PostgreSQL (как его настраивать — из 09-ledger);
- `web1`/`web2` получают `LINKD_DATABASE_URL`, указывающий на `db1`;
- пароль БД — в ansible-vault, файл пароля — вне репо;
- шаблон юнита несёт требования из 02-nightshift: не root, автоперезапуск, ограничения
  (`systemd-analyze security` — ниже порога из проекта);
- nginx из роли `web` балансирует на обе реплики, которые теперь делят одну БД.

**Единая точка входа.** Цели `Makefile` — таблицей в README:

| Цель | Что делает | Слой |
|------|-----------|------|
| `make infra` | `terraform init/plan/apply` для окружения | ресурсы |
| `make vms` | `vagrant up` + `ansible-playbook` | ОС и сервис на ВМ |
| `make vms-check` | `ansible-playbook --check --diff` | сухой прогон |
| `make cluster` | kind + bootstrap Argo CD (этап 06) | кластер |
| `make destroy` | всё обратно | — |

### 4. Доказательства для README

То, что в проектах проверял `check.sh`, в портфолио показывается артефактами:

- вывод `terraform plan` после `apply` — `No changes`;
- сценарий drift: ресурс изменён руками → `plan` показывает расхождение → `apply` возвращает;
- что и зачем было импортировано (import) — пара строк в README Terraform;
- второй прогон Ansible — `changed=0`;
- время `make cluster` от нуля до `kubectl get nodes` `Ready`.

### 5. CI

Job'ы из этапа 03 для `infra/`: `terraform fmt -check` и `validate` без backend,
`ansible-lint` или хотя бы `--syntax-check`. Запускаются только при изменениях в `infra/`.
`apply` из CI не делается: стенд локальный, и это честно написано в README.

### 6. README и ADR

- Раздел «Инфраструктура»: таблица трёх слоёв, схема из «Что получится», цели `Makefile`.
- ADR «Terraform с docker provider вместо облака»: деньги, воспроизводимость, чем
  пришлось заплатить, как выглядел бы переезд (расширение — в [11. Финальный прогон, демо и развитие](/project/11-demo-and-next)).
- ADR «Два трека деплоя»: зачем в портфолио и ВМ, и кластер.

### 7. Коммит

```bash
git add infra Makefile README.md docs/adr .gitignore
git commit -m "infra: terraform, ansible VM track and kind cluster config"
```

---

## ✅ Критерии приёмки

- [ ] State Terraform — в MinIO, локального `terraform.tfstate` нет; `.terraform.lock.hcl` в git
- [ ] `terraform plan` после `apply` — `No changes`; dev и prod отличаются только переменными
- [ ] Другие части портфолио берут имена и адреса из `terraform output`
- [ ] Второй прогон Ansible — `changed=0`; `--check --diff` ничего не ломает
- [ ] В `inventories/` и `group_vars/` нет паролей открытым текстом; пароль vault — вне репо
- [ ] (полная) linkd 2.0 на web1/web2 работает с PostgreSQL на db1, через nginx отвечает `/readyz`
- [ ] Кластер создаётся одной командой, время записано
- [ ] Цели `Makefile` и три слоя описаны в README, ADR лежат в `docs/adr/`

---

## 🪤 Грабли

- **State в git** или без версионирования — секреты открытым текстом и нет отката
  испорченного state.
- **Бакет для state создаётся тем же Terraform**, который в нём хранит state, — курица
  и яйцо. Бакет state живёт отдельно, и в README написано, откуда он берётся.
- **`*.tfvars` с паролями в git** — «временно» не бывает, история помнит всё.
- **`output` с секретом** без `sensitive = true` печатается в консоль и в логи CI.
- **Пароль ansible-vault в истории shell** (`--vault-password ...` в командной строке).
  Только файл вне репо с правами `600`.
- **Hardening SSH или firewall отрезал доступ.** Держи вторую сессию открытой, а перед
  экспериментами — `vagrant snapshot save`.
- **Ресурсы машины.** Три ВМ (~2,3 ГБ), kind-кластер и стек мониторинга одновременно
  могут не влезть. Треки поднимаются по очереди, в README написано, сколько RAM нужно каждому.
- **Terraform делает работу Ansible** (длинные `remote-exec`) — неидемпотентно и
  неподдерживаемо. Terraform создаёт, Ansible настраивает.
- **Сгенерированный inventory закоммичен** — через неделю он врёт.

---

## 🤔 Вопросы себе

1. Чем Terraform отличается от Ansible и почему в портфолио используются оба?
2. Что такое state, зачем remote backend и блокировка, что будет при двух параллельных `apply`?
3. Что произойдёт, если удалить ресурс руками, а потом сделать `terraform plan`?
4. Когда нужен `terraform import`, а когда проще пересоздать ресурс?
5. Что такое drift и как его обнаружить регулярно, а не случайно?
6. Что такое идемпотентность и почему второй прогон Ansible обязан давать `changed=0`?
7. Что поменяется в `infra/terraform/`, если перенести стенд с docker provider в облако?
8. Почему kind подходит для учёбы, но не для прода? Что даёт managed Kubernetes?

---

## 📚 Теория в волте

- IaC и Terraform vs Ansible: [Terraform: 01. Infrastructure as Code](/terraform/01-iac-intro),
  [Ansible: 01. Введение в Ansible](/ansible/01-ansible-intro)
- Terraform: [Terraform: 02. Terraform: основы](/terraform/02-terraform-basics),
  [Terraform: 03. State и backend](/terraform/03-state-backend),
  [Terraform: 04. Переменные и outputs](/terraform/04-variables-outputs),
  [Terraform: 05. Модули](/terraform/05-modules),
  [Terraform: 06. Workflow и CI/CD](/terraform/06-workflow-cicd)
- S3 и объектные хранилища: [Облака: 04. S3 и объектное хранилище](/cloud/04-s3-storage)
- Ansible: [Ansible: 03. Inventory](/ansible/03-inventory),
  [Ansible: 09. Handlers и идемпотентность](/ansible/09-handlers-idempotency),
  [Ansible: 11. Роли](/ansible/11-roles),
  [Ansible: 12. Ansible Vault](/ansible/12-vault),
  [Ansible: 13. Best practices, отладка, CI/CD](/ansible/13-best-practices)
- systemd-юниты: [Linux: 13. Init: systemd](/linux/13-init)
- PostgreSQL на сервере: [Базы данных: 02. PostgreSQL: установка и устройство](/databases/02-pg-install),
  [Базы данных: 03. Доступ: pg_hba.conf, роли и права](/databases/03-pg-hba-access)
- SSH и hardening: [Сети: 08. SSH](/network/08-ssh)
- Способы развернуть кластер: [Kubernetes: 16. Развёртывание кластера](/kubernetes/16-cluster-deployment)

➡️ Следующий этап: [05. Kubernetes и Helm: чарт linkd 2.0 и данные в кластере](/project/05-kubernetes-helm)
