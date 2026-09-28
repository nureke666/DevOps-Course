---
title: "13. Best practices, отладка, скорость и Ansible в CI/CD"
description: "Эталонная структура проекта, ansible-lint, molecule, производительность, отладка, безопасная эксплуатация прода"
---

# 13. Best practices, отладка, скорость и Ansible в CI/CD

> Тема сверх роадмапа, но именно она превращает «умею писать плейбуки» в «поддерживаю
> ansible-репозиторий команды». Здесь: структура проекта, `ansible-lint`, molecule,
> производительность, отладка и запуск из пайплайна.

---

## 1. 🗂️ Структура проекта (эталон)

```text:no-line-numbers
ansible/
├── ansible.cfg                  # настройки проекта
├── requirements.yml             # внешние роли и коллекции (с версиями!)
├── .gitignore                   # .vault_pass, *.retry, collections/, roles/external/
├── .ansible-lint                # правила линтера
├── README.md                    # как пользоваться репозиторием
│
├── site.yml                     # главный плейбук (обычно import_playbook)
├── playbooks/
│   ├── web.yml
│   ├── db.yml
│   └── deploy.yml
│
├── inventories/
│   ├── dev/
│   │   ├── hosts.yml
│   │   ├── group_vars/
│   │   │   ├── all/
│   │   │   │   ├── vars.yml
│   │   │   │   └── vault.yml        # зашифровано
│   │   │   └── web.yml
│   │   └── host_vars/
│   └── prod/
│       └── ... то же самое
│
└── roles/
    ├── common/
    ├── docker/
    ├── nginx/
    └── app/
```

**Принципы:**
1. Окружения — **разными каталогами инвентарей**, не группами в одном файле.
2. Плейбук — тонкий: список ролей, вся логика в ролях.
3. Переменные — в `group_vars` окружения; в ролях — только `defaults`.
4. Внешние роли не коммитим, а фиксируем в `requirements.yml`.
5. Секреты — только в vault-файлах.

```yaml
# site.yml
---
- import_playbook: playbooks/common.yml
- import_playbook: playbooks/db.yml
- import_playbook: playbooks/web.yml
```

---

## 2. ✅ Правила написания (то, что спросят на ревью)

```yaml
# ❌ плохо: нет имени, shell вместо модуля, неидемпотентно
- shell: apt-get install -y nginx
```
```yaml
# ✅ хорошо: имя, FQCN, декларативное состояние
- name: Установить nginx
  ansible.builtin.apt:
    name: nginx
    state: present
```

| Правило | Почему |
|---------|--------|
| `name:` у каждой задачи | Читаемый вывод и логи CI |
| FQCN (`ansible.builtin.apt`) | Однозначность, требование линтера |
| Модуль вместо `shell` | Идемпотентность и check mode |
| `state: present`, не `latest` | Предсказуемость на проде |
| `mode: "0644"` строкой | Иначе YAML исказит значение |
| Префиксы переменных роли | Нет конфликтов между ролями |
| Всё настраиваемое — в `defaults` | Роль можно переиспользовать |
| `validate:` на критичных конфигах | Битый конфиг не доедет до сервера |
| `notify` + handler вместо `restarted` | Идемпотентность, нет лишних рестартов |
| `changed_when: false` на проверках | `changed=0` на повторе |
| `no_log: true` рядом с секретами | Нет утечек в логи |
| Теги на логические блоки | Быстрая отладка и частичные прогоны |
| `--check --diff` проходит без ошибок | Признак аккуратного плейбука |
| Второй прогон = `changed=0` | Главный критерий качества |

---

## 3. 🧹 `ansible-lint` — автоматическая проверка

```bash
pipx install ansible-lint
ansible-lint                       # весь проект
ansible-lint site.yml roles/nginx
ansible-lint --list-rules
ansible-lint --write               # автоисправление части правил
```

```yaml
# .ansible-lint
---
profile: production        # null | min | basic | moderate | safety | shared | production
exclude_paths:
  - .cache/
  - collections/
  - roles/external/
skip_list:
  - yaml[line-length]      # отключай осознанно и с комментарием
warn_list:
  - experimental
```

Что ловит линтер: отсутствие `name`, короткие имена модулей, `shell` вместо модулей,
`state: latest`, права без кавычек, устаревший синтаксис (`with_items`, `include`),
пробелы и отступы, отсутствие `changed_when` у `command`.

```bash
# в pre-commit
pipx install pre-commit
cat > .pre-commit-config.yaml <<'Y'
repos:
  - repo: https://github.com/ansible/ansible-lint
    rev: v24.9.2
    hooks: [{id: ansible-lint}]
  - repo: https://github.com/adrienverge/yamllint
    rev: v1.35.1
    hooks: [{id: yamllint}]
Y
pre-commit install
```

---

## 4. 🧪 Тестирование ролей: molecule

```bash
pipx install molecule
pipx inject molecule 'molecule-plugins[docker]' docker
cd roles/nginx && molecule init scenario -d docker
```

```yaml
# roles/nginx/molecule/default/molecule.yml
---
driver: { name: docker }
platforms:
  - name: ubuntu2204
    image: geerlingguy/docker-ubuntu2204-ansible:latest
    pre_build_image: true
    command: /lib/systemd/systemd
    privileged: true
provisioner: { name: ansible }
verifier: { name: ansible }
```

```yaml
# molecule/default/verify.yml
---
- name: Verify
  hosts: all
  tasks:
    - name: Сервис запущен
      ansible.builtin.service_facts:
    - ansible.builtin.assert:
        that: ansible_facts.services['nginx.service'].state == 'running'

    - name: Порт отвечает
      ansible.builtin.uri: { url: "http://localhost/", status_code: 200 }
```

```bash
molecule test        # create → converge → idempotence → verify → destroy
molecule converge    # применить роль и оставить контейнер
molecule login       # зайти внутрь и посмотреть глазами
molecule idempotence # ⭐ проверка второго прогона на changed=0
molecule destroy
```

> 💡 Шаг `idempotence` в molecule — автоматизация того самого критерия из темы 09.
> Для портфолио роль с molecule-тестами выглядит сильно убедительнее.

---

## 5. ⚡ Производительность

```ini
# ansible.cfg
[defaults]
forks = 30                       # параллельных хостов (по умолчанию 5)
gathering = smart                # не пересобирать факты без нужды
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_facts
fact_caching_timeout = 7200
callbacks_enabled = timer, profile_tasks

[ssh_connection]
pipelining = True                # ⭐ меньше SSH-операций на задачу
ssh_args = -o ControlMaster=auto -o ControlPersist=300s -o PreferredAuthentications=publickey
control_path = /tmp/ansible-%%h-%%p-%%r
```

| Приём | Эффект |
|-------|--------|
| `pipelining = True` | Часто самый большой выигрыш; нужен `!requiretty` в sudoers |
| `ControlPersist` | Переиспользование SSH-соединений |
| `forks` | Больше хостов одновременно (упирается в CPU/сеть control node) |
| `gather_facts: false` / `gather_subset` | Убирает самый долгий первый шаг |
| Кэш фактов | Факты берутся из файла/redis, а не с хостов |
| `strategy: free` | Хосты не ждут друг друга на каждой задаче |
| Список вместо `loop` у пакетов | Одна транзакция вместо N |
| `async` + `poll: 0` | Долгие операции в фоне |
| `serial` (обратный эффект) | Медленнее, но безопаснее для прода |
| Меньше `command`/`shell` | Модули быстрее и идемпотентны |

```yaml
- hosts: all
  strategy: free                 # каждый хост идёт своим темпом
  gather_facts: false
```

```bash
# найти, что тормозит
ANSIBLE_CALLBACKS_ENABLED=profile_tasks ansible-playbook site.yml
```

---

## 6. 🔍 Отладка

```bash
ansible-playbook site.yml --syntax-check
ansible-playbook site.yml --list-tasks
ansible-playbook site.yml --list-hosts
ansible-playbook site.yml --check --diff
ansible-playbook site.yml --start-at-task "Имя задачи"
ansible-playbook site.yml --step
ansible-playbook site.yml -vvv            # что и как выполняется
ansible-playbook site.yml -vvvv           # + детали SSH
ansible-inventory --graph --vars
ansible <host> -m setup | less
```

```yaml
# отладочные задачи
- ansible.builtin.debug: { var: my_var }
- ansible.builtin.debug: { msg: "{{ hostvars[inventory_hostname] | to_nice_json }}" }
- ansible.builtin.pause: { prompt: "Проверь состояние и нажми Enter" }
- ansible.builtin.assert: { that: app_port is defined }
```

Интерактивный отладчик:
```yaml
- hosts: web
  debugger: on_failed          # always | never | on_failed | on_unreachable | on_skipped
```
При падении откроется `(debug)`: <code v-pre>p task_vars</code>, `p result`,
<code v-pre>task.args['name'] = 'nginx'</code>, `redo`, `continue`, `quit`.

```ini
# логирование прогонов
[defaults]
log_path = ./ansible.log
```

---

## 7. 🔁 Ansible в CI/CD (связка с блоком CI/CD)

```yaml
# .gitlab-ci.yml
stages: [lint, check, deploy]

default:
  image: python:3.12-slim
  before_script:
    - pip install -q ansible-core ansible-lint
    - ansible-galaxy install -r requirements.yml

lint:
  stage: lint
  script:
    - ansible-lint
    - ansible-playbook site.yml --syntax-check
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

check:dev:
  stage: check
  script:
    - echo "$ANSIBLE_VAULT_PASSWORD" > /tmp/.vp && chmod 600 /tmp/.vp
    - ansible-playbook -i inventories/dev/ site.yml --check --diff --vault-password-file /tmp/.vp
  after_script: ["rm -f /tmp/.vp"]
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

deploy:prod:
  stage: deploy
  script:
    - echo "$ANSIBLE_VAULT_PASSWORD" > /tmp/.vp && chmod 600 /tmp/.vp
    - chmod 600 "$SSH_KEY"
    - ansible-playbook -i inventories/prod/ site.yml
        --vault-password-file /tmp/.vp --private-key "$SSH_KEY"
        -e "app_version=$CI_COMMIT_TAG"
  after_script: ["rm -f /tmp/.vp"]
  environment: { name: production }
  resource_group: production          # ⭐ два деплоя одновременно не пойдут
  rules:
    - if: $CI_COMMIT_TAG
      when: manual
```

**Что важно в пайплайне:**
- `ansible-lint` + `--syntax-check` на каждый MR — дешёвая проверка качества;
- `--check --diff` на dev-инвентаре показывает ревьюеру, что изменится;
- прод — `when: manual` + `resource_group`;
- версия приложения приходит из CI через `-e`;
- секреты — из CI/CD Variables (masked/File), `known_hosts` — через `ssh-keyscan`;
- прогон плейбука дважды в staging = автотест идемпотентности.

---

## 8. 🚀 Безопасная эксплуатация прода

```text:no-line-numbers
1. Изменение → MR → ansible-lint + --syntax-check в CI
2. Ревью diff (роль, переменные, что затрагивает)
3. --check --diff на dev/staging
4. Реальный прогон на staging
5. Прод: --check --diff --limit один_хост
6. Прод: реальный прогон --limit один_хост → проверка сервиса
7. Прод: остальные хосты, по возможности serial + health-check
8. Второй прогон для контроля: changed=0
```

Полезные привычки:
- `backup: true` на конфигах, `validate:` где возможно;
- `serial: 1` (или процент) + `max_fail_percentage` на раскатках;
- окно обслуживания для операций с рестартом БД;
- логи прогонов (`log_path`) и уведомление в чат из `post_tasks`;
- отдельный deploy-пользователь с минимальными правами, прод-инвентарь — отдельно.

---

## 9. 🧩 Ansible рядом с другими инструментами

| Инструмент | Как сочетается |
|------------|----------------|
| **Terraform** | Terraform создаёт VM и теги → динамический inventory → Ansible настраивает |
| **Docker** | Ansible ставит docker, кладёт `compose.yml` из шаблона, поднимает сервисы |
| **Kubernetes** | Ansible готовит ноды (kubespray), а рабочие нагрузки — манифестами/Helm |
| **GitLab CI** | Джоба деплоя запускает `ansible-playbook`; секреты — CI/CD Variables |
| **Prometheus** | Ansible раскладывает exporters и генерирует targets из инвентаря |
| **AWX / AAP** | Веб-интерфейс, RBAC, расписания и логи прогонов поверх тех же плейбуков |

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Проверить качество кода | `ansible-lint` |
| Проверить синтаксис | `ansible-playbook site.yml --syntax-check` |
| Посмотреть, что изменится | `--check --diff` |
| Найти медленные задачи | `callbacks_enabled = timer, profile_tasks` |
| Ускорить | `pipelining`, `forks`, кэш фактов, `strategy: free` |
| Тестировать роль | `molecule test` |
| Проверить идемпотентность | второй прогон или `molecule idempotence` |
| Логи прогонов | `log_path` в `ansible.cfg` |
| Отладчик при падении | `debugger: on_failed` |
| Пауза для ручной проверки | модуль `pause` |
| Раскатка волнами | `serial` + `max_fail_percentage` |
| Зафиксировать зависимости | `requirements.yml` |
| Один деплой одновременно (CI) | `resource_group` в GitLab CI |

---

## 🧠 Что запомнить

1. Структура: `ansible.cfg`, `site.yml`, `inventories/<env>/`, `roles/`, `requirements.yml`.
2. Окружения — отдельными каталогами инвентарей; плейбуки тонкие, логика в ролях.
3. `ansible-lint` + `yamllint` в pre-commit и в CI — дешёвый способ держать качество.
4. molecule тестирует роль в контейнере и проверяет идемпотентность автоматически.
5. Скорость: `pipelining`, `ControlPersist`, `forks`, кэш фактов, `gather_subset`,
   `strategy: free`, меньше `shell`.
6. `profile_tasks` показывает, какие задачи тормозят, — оптимизируй по данным.
7. Отладка: `--syntax-check` → `--list-tasks` → `--check --diff` → `-vvv` →
   `--start-at-task`/`--step` → `debugger`.
8. В CI: lint и `--check` на MR, прод — вручную, с `resource_group` и секретами
   из CI/CD Variables.
9. На проде: сначала один хост, потом `serial` с health-check; `backup` и `validate` — всегда.
10. Ansible живёт в связке: Terraform создаёт, Ansible настраивает, CI запускает,
    Kubernetes забирает рабочие нагрузки.

---

## Задачи

> Многое здесь пересекается с блоком CI/CD.

---

### Блок A. Теория

**A1.** Опиши эталонную структуру ansible-репозитория и объясни каждый каталог.

<details><summary>Ответ</summary>

`ansible.cfg` (настройки), `site.yml` и `playbooks/` (тонкие плейбуки),
`inventories/<env>/` (хосты + `group_vars`/`host_vars`, включая vault),
`roles/` (вся логика), `requirements.yml` (внешние зависимости), `.gitignore`,
`.ansible-lint`, `README.md`.

</details>

**A2.** Почему окружения разделяют каталогами инвентарей, а не группами?

<details><summary>Ответ</summary>

Физическое разделение исключает случайное применение прод-переменных
или прогон по проду из-за опечатки в паттерне, и позволяет раздавать доступ
к прод-секретам отдельно.

</details>

**A3.** Почему внешние роли не коммитят в репозиторий?

<details><summary>Ответ</summary>

Чтобы фиксировать версии централизованно, не тащить чужой код в свою историю
и обновлять зависимости управляемо (`requirements.yml` + установка в CI).

</details>

**A4.** Назови десять правил хорошего плейбука.

<details><summary>Ответ</summary>

`name` у задач, FQCN, модули вместо `shell`, `present` вместо `latest`,
`mode` строкой, префиксы переменных, `defaults` для настроек, `validate`,
handler вместо `restarted`, `changed_when: false` на проверках, `no_log` для секретов,
теги, `--check` без ошибок, `changed=0` на повторе.

</details>

**A5.** Что проверяет `ansible-lint`? Назови пять типовых замечаний.

<details><summary>Ответ</summary>

Отсутствие `name`, короткие имена модулей вместо FQCN, `shell`/`command`
без `changed_when`, `state: latest`, права без кавычек, устаревшие конструкции
(`with_items`, `include`), проблемы форматирования YAML.

</details>

**A6.** Что такое профили в `.ansible-lint` и зачем `skip_list`?

<details><summary>Ответ</summary>

Профиль — набор правил по строгости (`min` … `production`). `skip_list` отключает
конкретные правила; отключать нужно осознанно и с комментарием, иначе линтер
превращается в декорацию.

</details>

**A7.** Что такое molecule и какие шаги выполняет `molecule test`?

<details><summary>Ответ</summary>

Фреймворк тестирования ролей. `molecule test`: create → prepare → converge →
idempotence → side_effect → verify → destroy.

</details>

**A8.** Как molecule проверяет идемпотентность?

<details><summary>Ответ</summary>

Прогоняет роль второй раз и проверяет, что нет задач со статусом `changed`.

</details>

**A9.** ⭐ Назови шесть способов ускорить Ansible.

<details><summary>Ответ</summary>

`pipelining`, `ControlPersist`, увеличение `forks`, отключение/сужение сбора фактов,
кэш фактов, `strategy: free`, список вместо `loop` у пакетов, `async` для долгих задач,
меньше `command`/`shell`.

</details>

**A10.** Что делает `pipelining` и какое условие нужно на целевом хосте?

<details><summary>Ответ</summary>

Передаёт модуль в уже открытую SSH-сессию, уменьшая число операций на задачу.
Требует отсутствия `requiretty` в sudoers.

</details>

**A11.** Чем `strategy: free` отличается от `linear`? Когда он опасен?

<details><summary>Ответ</summary>

`linear` — все хосты синхронно переходят к следующей задаче; `free` — каждый
хост идёт своим темпом. `free` опасен, когда между хостами есть зависимости
(например, БД должна быть готова раньше приложения) — порядок не гарантируется.

</details>

**A12.** Что делает кэш фактов и когда он оправдан?

<details><summary>Ответ</summary>

Сохраняет собранные факты между прогонами (файл/redis). Оправдан на больших парках
и когда фактов нужно много, а хосты меняются редко.

</details>

**A13.** Как найти самые медленные задачи?

<details><summary>Ответ</summary>

Колбэками `timer` и `profile_tasks`.

</details>

**A14.** Опиши порядок отладки падающего плейбука.

<details><summary>Ответ</summary>

`--syntax-check` → `--list-tasks`/`--list-hosts` → `--check --diff` →
`-vvv`/`-vvvv` → `--start-at-task`/`--step` → `debug`/`assert` → `debugger: on_failed`.

</details>

**A15.** Что делает `debugger: on_failed`?

<details><summary>Ответ</summary>

Включает интерактивный отладчик при падении задачи: можно посмотреть переменные
и результат, изменить аргументы и повторить задачу (`redo`).

</details>

**A16.** Опиши порядок безопасного применения изменений на проде.

<details><summary>Ответ</summary>

MR + линт в CI → ревью → `--check --diff` на dev → прогон на staging →
`--check --limit` на одном прод-хосте → реальный прогон на нём → остальные хосты
(`serial` + health-check) → контрольный прогон на `changed=0`.

</details>

**A17.** Что должно быть в CI-пайплайне для ansible-репозитория?

<details><summary>Ответ</summary>

Установка зависимостей (`requirements.yml`), `ansible-lint` и `--syntax-check`
на MR, `--check --diff` на dev, деплой staging автоматически, прод — вручную
с `environment` и `resource_group`, секреты — из CI/CD Variables.

</details>

**A18.** Как Ansible сочетается с Terraform? А с Kubernetes?

<details><summary>Ответ</summary>

Terraform создаёт инфраструктуру и теги, Ansible настраивает ОС
(часто через динамический inventory). С Kubernetes: Ansible готовит ноды и вспомогательные
VM, а рабочие нагрузки описываются манифестами/Helm.

</details>

**A19.** Что такое AWX и зачем он нужен?

<details><summary>Ответ</summary>

Веб-платформа поверх Ansible: запуск плейбуков по кнопке и расписанию,
RBAC, хранение креденшелов, логи и аудит прогонов. AWX — бесплатный upstream,
AAP — коммерческая версия.

</details>

**A20.** Зачем в CI-джобе деплоя `resource_group`?

<details><summary>Ответ</summary>

Чтобы два прогона деплоя не выполнялись одновременно и не портили состояние.

</details>

---

### Блок B. «Что не так»

```text:no-line-numbers
# B1
ansible/
├── site.yml
├── hosts.ini          # dev и prod в одном файле, группы dev_web и prod_web
├── group_vars/
└── roles/
```

<details><summary>Ответ</summary>

dev и prod в одном инвентаре — риск случайного применения на прод;
нужны отдельные каталоги `inventories/dev` и `inventories/prod` со своими `group_vars`.

</details>

```yaml
# B2
- hosts: all
  tasks:
    - shell: apt-get update && apt-get install -y nginx
    - shell: systemctl restart nginx
    - shell: echo "server_name example.com;" > /etc/nginx/conf.d/app.conf
```

<details><summary>Ответ</summary>

Всё через `shell`: неидемпотентно, не работает `--check`, нет `name`,
конфиг пишется редиректом вместо `template`, рестарт безусловный. Переписать на
`apt`, `template` (+`validate`), `service` + handler.

</details>

```yaml
# B3
- name: Deploy
  hosts: prod
  tasks:
    - ansible.builtin.apt: { name: nginx, state: latest }
    - ansible.builtin.copy: { src: nginx.conf, dest: /etc/nginx/nginx.conf, mode: 0644 }
    - ansible.builtin.service: { name: nginx, state: restarted }
```

<details><summary>Ответ</summary>

`latest` непредсказуем, `mode: 0644` без кавычек, `restarted` вместо handler,
нет `name`, деплой сразу на всю группу prod без `serial`/`--limit`.

</details>

```ini
# B4
[defaults]
host_key_checking = False
forks = 5
```

<details><summary>Ответ</summary>

`host_key_checking = False` в общем конфиге — отключение защиты от MITM;
`forks = 5` мало для большого парка. Плюс не задан `pipelining`.

</details>

```yaml
# B5  .gitlab-ci.yml
deploy:
  script:
    - ansible-playbook -i inventories/prod/ site.yml --vault-password-file <(echo "$VAULT_PASS")
  rules:
    - if: $CI_COMMIT_BRANCH
```

<details><summary>Ответ</summary>

Пароль передаётся через подстановку процесса — он может попасть в логи/`ps`;
деплой на прод запускается на любой ветке без ручного подтверждения, нет `environment`
и `resource_group`. Правильно: временный файл с правами 600, `when: manual`, ограничение
по ветке/тегу.

</details>

```yaml
# B6
- hosts: all
  strategy: free
  serial: 1
  tasks:
    - ansible.builtin.command: /opt/migrate-shared-db.sh
```

<details><summary>Ответ</summary>

`strategy: free` вместе с `serial: 1` и общей БД: порядок не гарантирован,
а миграция общей БД будет запущена с каждого хоста. Нужно `run_once: true`
и `strategy: linear`.

</details>

---

### Блок C. Практика

#### C1. 🔑 Привести проект к эталонной структуре
Перестрой свой учебный каталог: `ansible.cfg`, `site.yml`, `playbooks/`,
`inventories/{dev,prod}/` с `group_vars`/`host_vars`, `roles/`, `requirements.yml`,
`.gitignore`, `README.md`. Проверь, что `ansible-playbook site.yml -i inventories/dev/`
работает.

#### C2. 🔑 `ansible-lint`
```bash
pipx install ansible-lint
ansible-lint
```
1. Зафиксируй, сколько нашлось замечаний.
2. Исправь их (FQCN, `name`, `mode` в кавычках, `latest` → `present`, `shell` → модули).
3. Добейся чистого прогона.
4. Создай `.ansible-lint` с профилем и осознанным `skip_list` (с комментариями).

#### C3. pre-commit
Настрой `pre-commit` с `ansible-lint` и `yamllint`. Сделай коммит с намеренной ошибкой
и убедись, что он не проходит.

#### C4. Замер производительности

<details><summary>Ответ</summary>

Типичный выигрыш: `pipelining` — десятки процентов на плейбуках с многими задачами;
`cache_valid_time` убирает повторные `apt update`; `forks` помогает при многих хостах.

</details>

```bash
ANSIBLE_CALLBACKS_ENABLED=profile_tasks ansible-playbook site.yml
```
1. Выпиши три самые долгие задачи.
2. Включи `pipelining`, увеличь `forks`, добавь `cache_valid_time` для apt.
3. Замерь снова и посчитай выигрыш в процентах.

#### C5. Кэш фактов
Включи `fact_caching = jsonfile`, прогони плейбук дважды, посмотри содержимое
каталога кэша. Замерь время Gathering Facts до и после.

#### C6. `strategy: free`

<details><summary>Ответ</summary>

`free` обычно быстрее, вывод перемешан; нельзя использовать там, где между хостами
есть зависимости по порядку.

</details>

Прогони один и тот же плейбук с `linear` и `free` на трёх хостах, где задачи занимают
разное время. Сравни общее время и порядок вывода. Когда `free` использовать нельзя?

#### C7. Отладка падения
1. Внеси в плейбук ошибку (несуществующий пакет).
2. Пройди цепочку: `--syntax-check` → `--list-tasks` → `-vvv` → `--start-at-task`.
3. Включи `debugger: on_failed`, поймай ошибку и поиграй с командами отладчика.

#### C8. Логи
Включи `log_path = ./ansible.log`, прогони плейбук, найди в логе конкретную задачу
и её результат. Добавь `ansible.log` в `.gitignore`.

#### C9. 🔑 molecule (со звёздочкой, но очень полезно)

<details><summary>Ответ</summary>

Шаги: создание контейнера, подготовка, применение роли (`converge`), повторный
прогон для проверки идемпотентности, проверки (`verify`), удаление.

</details>

```bash
pipx install molecule && pipx inject molecule 'molecule-plugins[docker]' docker
cd roles/nginx && molecule init scenario -d docker
molecule test
```
1. Опиши, что произошло на каждом шаге.
2. Намеренно сделай роль неидемпотентной и убедись, что шаг `idempotence` падает.
3. Допиши `verify.yml`: сервис запущен, порт отвечает, конфиг содержит нужную строку.

#### C10. 🔑 Пайплайн для ansible-репозитория
Напиши `.gitlab-ci.yml` со стадиями:
1. `lint` — `ansible-lint` + `--syntax-check` (на MR);
2. `check` — `--check --diff` на dev-инвентаре (на MR);
3. `deploy:staging` — автоматически на main;
4. `deploy:prod` — вручную по тегу, с `resource_group` и `environment`.
Секреты — из CI/CD Variables.

#### C11. Тест идемпотентности в CI

<details><summary>Ответ</summary>

Простой вариант: сохранить вывод, найти строки `changed=` в PLAY RECAP
и упасть, если сумма не нулевая.

</details>

Добавь джобу, которая прогоняет плейбук на staging дважды и падает, если во втором
прогоне есть `changed`. Подсказка: разбор вывода `PLAY RECAP` или `--check` после прогона.

#### C12. Ритуал прода (репетиция)
Прогони по шагам процедуру из §8 конспекта на своём стенде, считая `web1` продом.
Запиши, что проверял на каждом шаге и сколько времени занял каждый.

---

### Блок D. Инциденты

**D1.** У разных инженеров плейбук ведёт себя по-разному. Что проверить в первую очередь?

<details><summary>Ответ</summary>

Какой `ansible.cfg` используется (`ansible --version`), какие версии
ansible-core и коллекций, какой инвентарь и какие переменные окружения
(`ansible-config dump --only-changed`).

</details>

**D2.** Прогон на 100 хостов занимает 40 минут. Три шага диагностики и четыре способа ускорить.

<details><summary>Ответ</summary>

Диагностика: `profile_tasks` (какие задачи долгие), доля Gathering Facts,
число `forks` и наличие `pipelining`. Ускорение: `pipelining` + `ControlPersist`,
больше `forks`, кэш фактов/`gather_subset`, списки вместо циклов, `async` для долгих задач.

</details>

**D3.** После включения `pipelining` задачи падают с `you must have a tty to run sudo`.
Причина и решение.

<details><summary>Ответ</summary>

`Defaults requiretty` в sudoers несовместим с pipelining. Убрать requiretty
(точечно для пользователя автоматизации) или отключить pipelining.

</details>

**D4.** `strategy: free` привёл к тому, что приложение стартовало раньше БД. Почему?

<details><summary>Ответ</summary>

При `free` хосты не синхронизируются на задачах: приложение на одном хосте
дошло до старта раньше, чем БД на другом. Нужен `linear` и разделение на play.

</details>

**D5.** MR с изменением роли прошёл ревью, но на проде всё сломалось. Каких шагов
не хватало в процессе?

<details><summary>Ответ</summary>

Не было `--check --diff` на dev/staging, прогона на одном прод-хосте
через `--limit`, health-check после деплоя и плана отката.

</details>

**D6.** `ansible-lint` в CI падает на легаси-плейбуках, которые никто не трогает.
Как быть (два варианта)?

<details><summary>Ответ</summary>

(1) `exclude_paths` для легаси + постепенное исправление; (2) прогон линтера
только по изменённым файлам в MR. Полное отключение — плохой вариант.

</details>

**D7.** В CI пароль vault виден в логе задачи. Как передавать правильно?

<details><summary>Ответ</summary>

Через masked-переменную, записанную во временный файл с правами 600
и `--vault-password-file`; файл удалять в `after_script`; не передавать пароль
аргументом командной строки.

</details>

**D8.** Деплой запустили одновременно двое, состояние сервера «поехало».
Что настроить в пайплайне?

<details><summary>Ответ</summary>

`resource_group` в GitLab CI (и/или блокировка на уровне процесса деплоя),
плюс ручное подтверждение на прод.

</details>

**D9.** Роль работает у автора и падает у всех остальных: «нет модуля
`community.docker.docker_container`». Что забыли?

<details><summary>Ответ</summary>

Не установлены коллекции из `requirements.yml`
(`ansible-galaxy collection install -r requirements.yml`), и/или зависимости
не зафиксированы в репозитории.

</details>

**D10.** После обновления ansible-core часть плейбуков перестала работать
(`include` устарел, изменилось поведение). Как этого избежать в команде?

<details><summary>Ответ</summary>

Фиксировать версию ansible-core (в образе CI и в инструкции для команды),
обновляться осознанно, гонять линтер и тесты роли (molecule) перед обновлением,
читать changelog.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как организован ваш ansible-репозиторий?

<details><summary>Ответ</summary>

`ansible.cfg`, тонкий `site.yml`, `playbooks/`, `inventories/<env>/` с `group_vars`
и vault, `roles/`, `requirements.yml`, линтеры и CI.

</details>

**2.** Как вы тестируете роли?

<details><summary>Ответ</summary>

`ansible-lint` + `--syntax-check`, `--check --diff` на dev, molecule для ролей
(включая шаг idempotence), повторный прогон на staging.

</details>

**3.** Что такое `ansible-lint` и что он проверяет?

<details><summary>Ответ</summary>

Линтер плейбуков и ролей: стиль, устаревшие конструкции, отсутствие `name`,
`shell` вместо модулей, `latest`, права без кавычек и т.д.

</details>

**4.** Как ускорить выполнение плейбука?

<details><summary>Ответ</summary>

`pipelining`, `ControlPersist`, `forks`, кэш фактов и `gather_subset`,
`strategy: free`, списки вместо циклов, `async`, меньше `shell`.

</details>

**5.** Как отлаживать плейбук, который падает?

<details><summary>Ответ</summary>

`--syntax-check` → `--list-tasks` → `--check --diff` → `-vvv` →
`--start-at-task`/`--step` → `debug`/`assert` → `debugger: on_failed`.

</details>

**6.** Как вы применяете изменения на проде?

<details><summary>Ответ</summary>

Через MR и CI: линт, `--check` на dev, staging, затем прод — сначала один хост
(`--limit`), потом `serial` с health-check; `backup`/`validate` обязательны.

</details>

**7.** Как запускаете Ansible из CI/CD?

<details><summary>Ответ</summary>

Отдельная джоба деплоя: установка зависимостей, секреты из CI/CD Variables,
`--vault-password-file`, ключ типа File, `environment` и `resource_group`,
прод — `when: manual`.

</details>

**8.** Как хранить секреты в пайплайне?

<details><summary>Ответ</summary>

В masked/protected переменных CI и в ansible-vault; во временные файлы с правами 600,
с удалением после прогона; `no_log: true` в задачах.

</details>

**9.** Как Ansible сочетается с Terraform?

<details><summary>Ответ</summary>

Terraform создаёт ресурсы, Ansible настраивает ОС; связка через динамический inventory
по тегам.

</details>

**10.** Что такое AWX/Ansible Automation Platform?

<details><summary>Ответ</summary>

Платформа поверх Ansible: UI, RBAC, расписания, хранилище креденшелов, логи и аудит.

</details>

---

## 🎯 Чек-лист

- [ ] Проект приведён к эталонной структуре
- [ ] `ansible-lint` проходит чисто, есть `.ansible-lint`
- [ ] Настроен pre-commit с линтерами
- [ ] Замерил и ускорил прогон (`pipelining`, `forks`, кэш фактов)
- [ ] Знаю, когда `strategy: free` нельзя использовать
- [ ] Пользуюсь `profile_tasks` для поиска медленных задач
- [ ] Прошёл цепочку отладки падающего плейбука, включая `debugger`
- [ ] Написал CI-пайплайн: lint → check → staging → prod (manual)
- [ ] Секреты в пайплайне передаются безопасно
- [ ] Знаю порядок безопасного применения на проде и отрепетировал его
