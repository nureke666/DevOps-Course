---
title: "14. Практика: лабы из роадмапа"
description: "Пять лаб: базовый плейбук, роль nginx, деплой контейнера, репозиторий с vault, Ansible в GitLab CI"
---

# 14. Практика: лабы из роадмапа

> Роадмап → 5. Ansible → **2. Практика**:
> «**Написать плейбук**. **Написать роль**.
> Действительно инструмент простой, поэтому можно обойтись такой практикой,
> просто познакомиться с инструментом.»
> Здесь эти два задания разложены по шагам с критериями приёмки, плюс три лабы
> «для портфолио», которые связывают Ansible с блоками Linux, Docker и CI/CD.

---

## 📋 Список лаб

| № | Лаба | Что получишь | Темы |
|---|------|--------------|------|
| 1 | 🔑 **Написать плейбук** | Базовая настройка сервера одним прогоном | 05-10 |
| 2 | 🔑 **Написать роль** | Переиспользуемая роль `nginx` со всей структурой | 11 |
| 3 | 🔑 Деплой приложения из блока Docker | Плейбук выката контейнера с health-check | 05, 08, 10 |
| 4 | Полный репозиторий: два окружения + vault | То, что показывают на собесе | 03, 12, 13 |
| 5 | Ansible в GitLab CI | Деплой по кнопке из пайплайна | 13 + блок CI/CD |

**Что нужно до начала:**
- стенд из 3 хостов;
- рабочий `ansible.cfg` + инвентарь с группами `web` и `db`;
- приложение из блока Docker (с `Dockerfile` и эндпоинтом `/health`);
- аккаунт gitlab.com (для лабы 5).

```bash
# проверка готовности
ansible all -m ping
ansible-inventory --graph
```

---

## 🧪 Лаба 1. Написать плейбук 🔑

> Задание роадмапа: **написать плейбук**. Берём осмысленную задачу — базовая настройка
> сервера «с нуля до готовности принимать трафик».

### Что делаем
Плейбук `playbooks/base.yml`, который превращает чистую машину в настроенный веб-сервер.

### Требования
1. Обновление кэша пакетов (не чаще раза в час) и установка базового набора:
   `curl`, `git`, `htop`, `vim`, `unzip`, `ufw`.
2. Часовой пояс и локаль.
3. Пользователь `deploy`: shell `/bin/bash`, группы `sudo`, SSH-ключ через `authorized_key`.
4. Ужесточение SSH: `PermitRootLogin no`, `PasswordAuthentication no` —
   через `lineinfile` c `regexp` и `validate`, handler `restart sshd`.
5. Установка nginx, конфиг из шаблона (`worker_processes` = числу CPU),
   `validate: nginx -t -c %s`, handler `reload nginx`.
6. Страница `index.html` из шаблона: имя хоста, IP, ОС, память.
7. Firewall: разрешить 22 и 80, включить.
8. Проверка в `post_tasks`: `uri` на `http://localhost/` с `until`/`retries`.
9. Предусловия в `pre_tasks`: `assert` на поддерживаемую ОС и наличие переменных.

### Каркас

```yaml
---
- name: Базовая настройка веб-сервера
  hosts: web
  become: true

  vars:
    base_packages: [curl, git, htop, vim, unzip, ufw]
    timezone: Europe/Almaty
    deploy_user: deploy
    nginx_port: 80

  pre_tasks:
    - name: Проверить поддерживаемую ОС
      ansible.builtin.assert:
        that: ansible_os_family == "Debian"
        fail_msg: "Плейбук рассчитан на Debian/Ubuntu, а тут {{ ansible_distribution }}"

  tasks:
    - name: Кэш пакетов и базовый набор
      ansible.builtin.apt:
        name: "{{ base_packages }}"
        state: present
        update_cache: true
        cache_valid_time: 3600

    - name: Часовой пояс
      community.general.timezone:
        name: "{{ timezone }}"

    - name: "Пользователь {{ deploy_user }}"
      ansible.builtin.user:
        name: "{{ deploy_user }}"
        shell: /bin/bash
        groups: sudo
        append: true
        create_home: true

    - name: "SSH-ключ для {{ deploy_user }}"
      ansible.posix.authorized_key:
        user: "{{ deploy_user }}"
        key: "{{ lookup('file', lookup('env','HOME') + '/.ssh/ansible_lab.pub') }}"
        state: present

    - name: Ужесточение sshd
      ansible.builtin.lineinfile:
        path: /etc/ssh/sshd_config
        regexp: "{{ item.regexp }}"
        line: "{{ item.line }}"
        validate: "/usr/sbin/sshd -t -f %s"
        backup: true
      loop:
        - { regexp: '^#?PermitRootLogin',        line: 'PermitRootLogin no' }
        - { regexp: '^#?PasswordAuthentication', line: 'PasswordAuthentication no' }
      loop_control:
        label: "{{ item.line }}"
      notify: restart sshd

    - name: nginx установлен
      ansible.builtin.apt: { name: nginx, state: present }

    - name: Конфиг nginx
      ansible.builtin.template:
        src: ../templates/nginx.conf.j2
        dest: /etc/nginx/nginx.conf
        mode: "0644"
        backup: true
        validate: "nginx -t -c %s"
      notify: reload nginx

    - name: Стартовая страница
      ansible.builtin.template:
        src: ../templates/index.html.j2
        dest: /var/www/html/index.html
        mode: "0644"

    - name: Firewall
      community.general.ufw:
        rule: allow
        port: "{{ item }}"
        proto: tcp
      loop: ["22", "{{ nginx_port }}"]

    - name: Включить firewall
      community.general.ufw:
        state: enabled
        policy: deny

    - name: nginx запущен и включён
      ansible.builtin.service:
        name: nginx
        state: started
        enabled: true

  post_tasks:
    - name: Сайт отвечает
      ansible.builtin.uri:
        url: "http://localhost:{{ nginx_port }}/"
        status_code: 200
      register: page
      until: page.status == 200
      retries: 10
      delay: 3
      changed_when: false

  handlers:
    - name: restart sshd
      ansible.builtin.service: { name: ssh, state: restarted }
    - name: reload nginx
      ansible.builtin.service: { name: nginx, state: reloaded }
```

```text:no-line-numbers
{# templates/index.html.j2 #}
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{{ inventory_hostname }}</title></head>
<body>
  <h1>{{ inventory_hostname }}</h1>
  <ul>
    <li>IP: {{ ansible_default_ipv4.address }}</li>
    <li>ОС: {{ ansible_distribution }} {{ ansible_distribution_version }}</li>
    <li>CPU: {{ ansible_processor_vcpus }}</li>
    <li>RAM: {{ ansible_memtotal_mb }} MB</li>
    <li>Настроено Ansible: {{ ansible_date_time.date }}</li>
  </ul>
</body></html>
```

### ✅ Критерии приёмки
```bash
ansible-playbook playbooks/base.yml --syntax-check      # ок
ansible-playbook playbooks/base.yml --check --diff      # без ошибок
ansible-playbook playbooks/base.yml                     # changed=N
ansible-playbook playbooks/base.yml                     # ⭐ changed=0
curl -s http://web1/ | grep web1                        # страница отдаётся
ssh root@web1                                           # отказ (PermitRootLogin no)
```
- [ ] Второй прогон даёт `changed=0`
- [ ] Ни одного `shell`/`command` без `changed_when`/`creates`
- [ ] У каждой задачи есть `name`
- [ ] Конфиги проверяются `validate`, рестарты — через handler
- [ ] `ansible-lint` не ругается

### 🧠 Разбор
- `assert` в `pre_tasks` — «ворота»: лучше упасть сразу, чем настроить половину сервера.
- `lineinfile` с `regexp` + `validate` — правильный способ править sshd: опечатка
  не отрежет тебе доступ, потому что задача упадёт до записи.
- Handler для sshd — важный нюанс: рестарт sshd не рвёт текущую сессию,
  но проверять доступ надо **до** выхода из неё (держи вторую сессию открытой).
- Страница из шаблона — наглядная демонстрация «один шаблон → разные конфиги».

---

## 🧪 Лаба 2. Написать роль 🔑

> Задание роадмапа: **написать роль**. Переносим nginx-часть лабы 1 в полноценную роль.

### Что делаем
Роль `roles/nginx` со всей структурой + роль `roles/common` для базовой настройки,
и тонкий `site.yml`.

### Требования
1. `ansible-galaxy init roles/nginx` — полная структура.
2. Все настраиваемые значения — в `defaults/main.yml` с префиксом `nginx_`
   (пакет, сервис, порт, `worker_processes`, `worker_connections`, `max_body_size`,
   `server_name`, `root`, список `nginx_vhosts`, флаг удаления дефолтного vhost).
3. Пути и константы — в `vars/main.yml`.
4. `tasks/main.yml`: assert по ОС → пакет → конфиг из шаблона с `validate` →
   виртуальные хосты циклом по `nginx_vhosts` с `loop_control.label` →
   удаление дефолтного vhost → сервис.
5. `handlers/main.yml`: `nginx reload` и `nginx restart` (с префиксом!).
6. `templates/nginx.conf.j2` и `templates/vhost.conf.j2`.
7. `meta/main.yml`: зависимость от `common`, платформы, описание.
8. `README.md` с таблицей переменных и примером подключения.
9. `tests/` или molecule-сценарий (по желанию).

### Проверка переиспользуемости
```yaml
# site.yml
---
- name: Все серверы
  hosts: all
  become: true
  roles: [common]

- name: Веб-серверы
  hosts: web
  become: true
  roles:
    - role: nginx
      nginx_server_name: "{{ inventory_hostname }}.local"
      nginx_vhosts:
        - { name: app,  server_name: app.local,  root: /var/www/app }
        - { name: blog, server_name: blog.local, root: /var/www/blog }
```

```yaml
# inventories/dev/group_vars/web.yml     — dev
nginx_worker_connections: 512
nginx_max_body_size: "10m"

# inventories/prod/group_vars/web.yml    — prod
nginx_worker_connections: 4096
nginx_max_body_size: "100m"
```

### ✅ Критерии приёмки
- [ ] `tree roles/nginx` показывает полную структуру
- [ ] Плейбук `site.yml` короче 25 строк
- [ ] Роль применяется к двум окружениям без правки кода роли — только переменными
- [ ] Второй прогон: `changed=0`
- [ ] `ansible-lint roles/nginx` чист
- [ ] В `README.md` есть таблица всех переменных
- [ ] Ни одного захардкоженного домена/пути/пароля внутри роли

### 🧠 Разбор
- Если пришлось лезть внутрь роли, чтобы поменять поведение для другого окружения —
  значит, переменная лежит не в `defaults`. Это главная ошибка новичков.
- Префиксы у handler'ов спасают, когда в play несколько ролей с «restart».
- Зависимость `common` в `meta` избавляет от необходимости помнить порядок ролей.

---

## 🧪 Лаба 3. Деплой приложения из блока Docker 🔑

> Связываем Ansible с блоком Docker: выкатываем контейнер из реестра на сервер.

### Что делаем
Роль `roles/app`, которая разворачивает приложение как docker-контейнер.

### Требования
1. Установка docker (своя роль `docker` или `geerlingguy.docker` из Galaxy).
2. Каталог `/opt/app` с владельцем `deploy`.
3. `docker-compose.yml` и `.env` из шаблонов (`mode: "0600"` для `.env`, `no_log: true`).
4. Логин в registry (`community.docker.docker_login`) с секретом из vault.
5. Подъём через `community.docker.docker_compose_v2` с `pull: always`.
6. Health-check: `uri` на `/health` с `until`/`retries`/`delay`.
7. `block`/`rescue`: при провале health-check — откат на предыдущий тег образа и `fail`.
8. Версия образа приходит переменной `app_version` (по умолчанию — из `defaults`).

### Ключевые куски

```yaml
- name: Деплой с откатом
  block:
    - name: compose-файл
      ansible.builtin.template:
        src: docker-compose.yml.j2
        dest: /opt/app/docker-compose.yml
        mode: "0644"

    - name: Переменные окружения
      ansible.builtin.template:
        src: env.j2
        dest: /opt/app/.env
        mode: "0600"
        owner: deploy
      no_log: true

    - name: Поднять сервисы
      community.docker.docker_compose_v2:
        project_src: /opt/app
        state: present
        pull: always

    - name: Проверка здоровья
      ansible.builtin.uri:
        url: "http://localhost:{{ app_port }}/health"
        status_code: 200
      register: health
      until: health.status == 200
      retries: 15
      delay: 4
      changed_when: false

  rescue:
    - name: Откат на предыдущую версию
      ansible.builtin.template:
        src: docker-compose.yml.j2
        dest: /opt/app/docker-compose.yml
      vars:
        app_version: "{{ app_previous_version }}"

    - community.docker.docker_compose_v2:
        project_src: /opt/app
        state: present
        pull: always

    - ansible.builtin.fail:
        msg: "Деплой {{ app_version }} провален, откатились на {{ app_previous_version }}"
```

```bash
ansible-playbook playbooks/deploy.yml -e "app_version=1.2.3" --limit web1
```

### ✅ Критерии приёмки
- [ ] Приложение отвечает на `/health` после прогона
- [ ] Повторный прогон с той же версией: `changed=0`
- [ ] Смена `app_version` пересоздаёт контейнер
- [ ] Пароль реестра не виден в выводе (`no_log`) и лежит в vault
- [ ] Заведомо битая версия вызывает откат и красный статус
- [ ] `.env` на сервере имеет права `0600`

---

## 🧪 Лаба 4. Полный репозиторий: два окружения + vault

### Что делаем
Собираем всё в структуру, которую не стыдно показать на собеседовании.

```text:no-line-numbers
ansible/
├── ansible.cfg
├── requirements.yml
├── site.yml
├── .gitignore              # .vault_pass, *.retry, ansible.log
├── .ansible-lint
├── README.md
├── playbooks/{base.yml,deploy.yml}
├── inventories/
│   ├── dev/{hosts.yml,group_vars/{all/{vars.yml,vault.yml},web.yml}}
│   └── prod/{hosts.yml,group_vars/{all/{vars.yml,vault.yml},web.yml}}
└── roles/{common,docker,nginx,app}/
```

### Требования
1. Два инвентаря с одинаковыми группами, но разными переменными
   (`app_env`, размеры пулов, домены, версии).
2. Секреты (пароль БД, токен реестра) — в `vault.yml`, пароль vault — вне git.
3. `requirements.yml` с внешней ролью и коллекциями (с версиями).
4. `README.md`: как запустить, что где лежит, какие переменные важны.
5. Один и тот же `site.yml` работает с обоими инвентарями.

### ✅ Критерии приёмки
```bash
ansible-playbook -i inventories/dev/  site.yml --check --diff
ansible-playbook -i inventories/prod/ site.yml --check --diff --limit web1
grep -rEn '(password|token|secret)\s*:' inventories/ | grep -v ANSIBLE_VAULT   # пусто
ansible-lint                                                                   # чисто
```

---

## 🧪 Лаба 5. Ansible в GitLab CI

### Что делаем
Пайплайн, который проверяет и применяет конфигурацию (связка с блоком CI/CD).

```yaml
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
    - chmod 600 "$SSH_KEY"
    - ansible-playbook -i inventories/dev/ site.yml --check --diff
        --vault-password-file /tmp/.vp --private-key "$SSH_KEY"
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
        -e "app_version=${CI_COMMIT_TAG}"
  after_script: ["rm -f /tmp/.vp"]
  environment: { name: production }
  resource_group: production
  rules:
    - if: $CI_COMMIT_TAG
      when: manual
```

### ✅ Критерии приёмки
- [ ] MR запускает lint и `--check --diff`, результат виден в логе джобы
- [ ] Прод деплоится только по тегу и только по кнопке
- [ ] Секреты — в CI/CD Variables (masked/protected/File), в репозитории их нет
- [ ] Два деплоя одновременно невозможны (`resource_group`)
- [ ] В логе нет ни пароля vault, ни содержимого `.env`

---

## 🏁 Что должно остаться после лаб

1. **Плейбук базовой настройки** — лаба 1 (задание роадмапа).
2. **Роль `nginx`** с полной структурой и README — лаба 2 (задание роадмапа).
3. **Роль деплоя контейнера** с health-check и откатом — лаба 3.
4. **Репозиторий с двумя окружениями и vault** — лаба 4.
5. **Пайплайн GitLab CI** для этого репозитория — лаба 5.

Этого набора хватает и для резюме, и для практического задания на собеседовании.
