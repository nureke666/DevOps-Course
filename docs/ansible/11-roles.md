---
title: "11. Роли — переиспользуемые модули конфигурации"
description: "Структура роли, defaults vs vars, подключение ролей, import/include, Ansible Galaxy"
---

# 11. Роли — переиспользуемые модули конфигурации

> Роадмап → 5. Ansible → 1. Теория → **Роли**:
> «Роли — это способ разбить конфигурацию на логические модули: роль для nginx,
> роль для PostgreSQL, роль для мониторинга. Каждая роль — переиспользуемая, тестируемая,
> с чёткой структурой. В реальных компаниях всё построено на ролях.
> **Обязательно знать структуру роли.**»
> **После темы ты умеешь:** разложить плейбук на роли, знать каждый каталог наизусть
> и подключать чужие роли из Galaxy.

---

## 🗺️ ⭐ Структура роли (учить наизусть)

```text:no-line-numbers
roles/nginx/
├── defaults/
│   └── main.yml        ← переменные по умолчанию (САМЫЙ НИЗКИЙ приоритет)
├── vars/
│   └── main.yml        ← внутренние переменные роли (ВЫСОКИЙ приоритет)
├── tasks/
│   └── main.yml        ← ⭐ точка входа: что роль делает
├── handlers/
│   └── main.yml        ← handler'ы роли (restart/reload)
├── templates/
│   └── nginx.conf.j2   ← Jinja2-шаблоны (src: пишется просто именем файла)
├── files/
│   └── ssl-params.conf ← статические файлы для copy/script
├── meta/
│   └── main.yml        ← зависимости роли, автор, лицензия, платформы
├── tests/
│   ├── inventory
│   └── test.yml        ← минимальный тестовый прогон
├── library/            ← свои модули (редко)
├── module_utils/       ← общий код для своих модулей (редко)
├── lookup_plugins/     ← свои плагины (редко)
└── README.md           ← ⭐ что делает роль и какие у неё переменные
```

**Как это запомнить (по смыслу):**

| Каталог | Ответ на вопрос |
|---------|-----------------|
| `tasks/` | **Что делать?** |
| `handlers/` | **Что делать в ответ на изменение?** |
| `templates/` | **Какие файлы генерировать?** |
| `files/` | **Какие файлы копировать как есть?** |
| `defaults/` | **Какие настройки может менять пользователь роли?** |
| `vars/` | **Какие константы менять нельзя?** |
| `meta/` | **От чего роль зависит?** |
| `tests/` | **Как проверить, что роль работает?** |

> ⚠️ Ansible ищет **`main.yml`** в каждом каталоге автоматически. Файл с другим именем
> подключается явно через `include_tasks`/`import_tasks`.

```bash
ansible-galaxy init roles/nginx        # создать скелет роли одной командой
```

---

## 1. Зачем роли

Плейбук на 400 строк с nginx, postgres, мониторингом и приложением:
- невозможно переиспользовать (нужен только nginx — тащи всё);
- невозможно ревьюить (MR на 200 строк diff);
- невозможно тестировать по частям;
- переменные перемешаны и конфликтуют.

Роли решают это как функции в коде:

```yaml
# было: 400 строк
# стало:
- hosts: web
  become: true
  roles:
    - common
    - nginx
    - app

- hosts: db
  become: true
  roles:
    - common
    - postgresql
```

**Правило разбиения:** одна роль = один сервис/одна ответственность.
`nginx`, `postgresql`, `docker`, `monitoring`, `common` (базовая настройка любого сервера).

---

## 2. Пример полной роли `nginx`

```yaml
# roles/nginx/defaults/main.yml  — ЭТО настраивают пользователи роли
nginx_package: nginx
nginx_service: nginx
nginx_user: www-data
nginx_worker_processes: "auto"
nginx_worker_connections: 1024
nginx_keepalive_timeout: 65
nginx_max_body_size: "10m"
nginx_port: 80
nginx_server_name: localhost
nginx_root: /var/www/html
nginx_vhosts: []
nginx_remove_default_vhost: true
```

```yaml
# roles/nginx/vars/main.yml  — константы, менять не предполагается
nginx_config_path: /etc/nginx/nginx.conf
nginx_confd_path: /etc/nginx/conf.d
nginx_default_vhost: /etc/nginx/sites-enabled/default
```

```yaml
# roles/nginx/tasks/main.yml
---
- name: Проверить поддерживаемую ОС
  ansible.builtin.assert:
    that: ansible_os_family in ['Debian', 'RedHat']
    fail_msg: "Роль nginx не поддерживает {{ ansible_os_family }}"

- name: Установить nginx
  ansible.builtin.package:
    name: "{{ nginx_package }}"
    state: present
  notify: restart nginx

- name: Удалить дефолтный виртуальный хост
  ansible.builtin.file:
    path: "{{ nginx_default_vhost }}"
    state: absent
  when: nginx_remove_default_vhost | bool
  notify: reload nginx

- name: Основной конфиг
  ansible.builtin.template:
    src: nginx.conf.j2               # ищется в roles/nginx/templates/
    dest: "{{ nginx_config_path }}"
    owner: root
    mode: "0644"
    backup: true
    validate: "nginx -t -c %s"
  notify: reload nginx

- name: Виртуальные хосты
  ansible.builtin.template:
    src: vhost.conf.j2
    dest: "{{ nginx_confd_path }}/{{ item.name }}.conf"
    mode: "0644"
  loop: "{{ nginx_vhosts }}"
  loop_control:
    label: "{{ item.name }}"
  notify: reload nginx

- name: Сервис запущен и в автозагрузке
  ansible.builtin.service:
    name: "{{ nginx_service }}"
    state: started
    enabled: true
```

```yaml
# roles/nginx/handlers/main.yml
---
- name: restart nginx
  ansible.builtin.service:
    name: "{{ nginx_service }}"
    state: restarted

- name: reload nginx
  ansible.builtin.service:
    name: "{{ nginx_service }}"
    state: reloaded
```

```yaml
# roles/nginx/meta/main.yml
---
galaxy_info:
  role_name: nginx
  author: nurik
  description: Установка и настройка nginx
  license: MIT
  min_ansible_version: "2.14"
  platforms:
    - name: Ubuntu
      versions: [focal, jammy]
  galaxy_tags: [web, nginx]

dependencies:
  - role: common            # ⭐ выполнится ПЕРЕД этой ролью
```

```markdown
<!-- roles/nginx/README.md -->
# Роль nginx
Устанавливает и настраивает nginx.

## Переменные
| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| nginx_port | 80 | Порт прослушивания |
| nginx_vhosts | [] | Список виртуальных хостов |

## Пример
    - hosts: web
      roles:
        - role: nginx
          nginx_port: 8080
```

---

## 3. Подключение ролей

```yaml
# 1) простой список
- hosts: web
  roles: [common, nginx, app]

# 2) с параметрами (высокий приоритет — выше group_vars!)
- hosts: web
  roles:
    - role: nginx
      nginx_port: 8080
      nginx_server_name: example.com
    - role: app
      app_version: "1.2.3"

# 3) с условием и тегами
- hosts: web
  roles:
    - role: monitoring
      when: app_env == "production"
      tags: [monitoring]
```

### `roles:` vs `import_role` vs `include_role`

```yaml
tasks:
  - name: Статически (разворачивается при парсинге)
    ansible.builtin.import_role:
      name: nginx

  - name: Динамически (решение принимается в рантайме)
    ansible.builtin.include_role:
      name: nginx
      tasks_from: install.yml     # ⭐ подключить не main.yml, а конкретный файл
    when: install_nginx | bool
```

| | `roles:` | `import_role` | `include_role` |
|---|---|---|---|
| Когда обрабатывается | При парсинге | При парсинге (статически) | В рантайме (динамически) |
| Работает с `loop` | ❌ | ❌ | ✅ |
| `when` применяется | Ко всем задачам роли | Ко всем задачам роли | К самому подключению |
| Виден в `--list-tasks` | ✅ | ✅ | ❌ (до выполнения) |
| Порядок относительно `tasks` | До `tasks` | В месте вызова | В месте вызова |
| Теги наследуются задачами | ✅ | ✅ | Только на include |

**Практика:** обычный случай — секция `roles:`. Нужно подключить роль в середине задач —
`import_role`. Нужен цикл или условие, известное только в рантайме — `include_role`.

---

## 4. Порядок выполнения с ролями

```yaml
- hosts: web
  pre_tasks:  [...]     # ①
  roles:      [...]     # ② (внутри: зависимости из meta → сама роль)
  tasks:      [...]     # ③
  post_tasks: [...]     # ④
```
Handler'ы выполняются после каждого блока, если были уведомлены.

Зависимости из `meta/main.yml` выполняются **перед** ролью и по умолчанию
**только один раз**, даже если их указали несколько ролей
(изменяется `allow_duplicates: true` в `meta` зависимой роли).

---

## 5. Переменные роли: `defaults` vs `vars` (⭐ вопрос собеса)

```text:no-line-numbers
defaults/main.yml  →  САМЫЙ НИЗКИЙ приоритет
                      «предложение роли», рассчитано на переопределение
                      ЗДЕСЬ должно лежать всё, что пользователь настраивает

vars/main.yml      →  ВЫСОКИЙ приоритет
                      внутренние константы; переопределить можно только
                      task vars, set_fact, параметрами роли или -e
```

Практическое правило:
> Если переменную может захотеть поменять тот, кто подключает роль — она в `defaults`.
> Если её изменение сломает роль — она в `vars`.

**Префиксы обязательны:** `nginx_port`, а не `port` — иначе роли начнут перетирать
переменные друг друга в одном play.

Кроссплатформенность через `vars/` + `include_vars`:
```yaml
# roles/nginx/vars/Debian.yml → nginx_package: nginx
# roles/nginx/vars/RedHat.yml → nginx_package: nginx  (и другие пути)
- name: Переменные под ОС
  ansible.builtin.include_vars: "{{ ansible_os_family }}.yml"
```

---

## 6. Разбиение `tasks/` на файлы

```text:no-line-numbers
roles/app/tasks/
├── main.yml
├── install.yml
├── configure.yml
├── deploy.yml
└── Debian.yml / RedHat.yml
```

```yaml
# roles/app/tasks/main.yml
---
- ansible.builtin.import_tasks: install.yml
  tags: [install]

- ansible.builtin.import_tasks: configure.yml
  tags: [config]

- ansible.builtin.include_tasks: "{{ ansible_os_family }}.yml"

- ansible.builtin.include_tasks: deploy.yml
  when: deploy_enabled | bool
  tags: [deploy]
```

`import_tasks` — статически (теги и `--list-tasks` работают полноценно);
`include_tasks` — динамически (можно в цикле и по условию, известному в рантайме).

---

## 7. Ansible Galaxy — чужие роли и коллекции

```bash
ansible-galaxy search nginx
ansible-galaxy role info geerlingguy.nginx
ansible-galaxy role install geerlingguy.nginx
ansible-galaxy role install -r requirements.yml -p roles/
ansible-galaxy collection install -r requirements.yml
ansible-galaxy role list
```

```yaml
# requirements.yml — фиксируем зависимости проекта
---
roles:
  - name: geerlingguy.nginx
    version: "3.1.4"                       # ⭐ всегда фиксируй версию
  - name: internal.app
    src: git+ssh://git@gitlab.com/team/ansible-role-app.git
    version: v1.2.0
    scm: git

collections:
  - name: community.docker
    version: ">=3.4.0"
  - name: ansible.posix
```

```bash
# в CI перед прогоном
ansible-galaxy install -r requirements.yml
```

> ⚠️ Чужую роль перед использованием на проде читают глазами: она выполняется с root
> на твоих серверах. Смотри `tasks/main.yml`, `defaults/main.yml` и наличие внешних загрузок.

---

## 8. Как разложить существующий плейбук на роли

```text:no-line-numbers
1. Сгруппируй задачи по сервисам: всё про nginx → одна группа, про app → другая.
2. Для каждой группы:  ansible-galaxy init roles/<имя>
3. Перенеси задачи в tasks/main.yml, шаблоны в templates/, файлы в files/.
4. Вынеси все «магические значения» (порты, пути, версии) в defaults/main.yml
   с префиксом роли.
5. Handler'ы — в handlers/main.yml.
6. Зависимости (например, common) — в meta/main.yml.
7. В плейбуке оставь только список ролей.
8. Прогони дважды: changed=0 — значит, ничего не потерял.
9. Напиши README.md с таблицей переменных.
```

Итоговая структура проекта (подробнее — тема 13):
```text:no-line-numbers
ansible/
├── ansible.cfg
├── requirements.yml
├── site.yml
├── inventories/{dev,prod}/{hosts.yml,group_vars/,host_vars/}
└── roles/
    ├── common/
    ├── nginx/
    ├── docker/
    └── app/
```

---

## 9. Хорошая роль — чек-лист

- [ ] Делает **одну** вещь (один сервис).
- [ ] Все настраиваемые значения — в `defaults/main.yml` с префиксом имени роли.
- [ ] Работает как минимум на своей ОС; `assert` ловит неподдерживаемые платформы.
- [ ] Идемпотентна: второй прогон — `changed=0`.
- [ ] Handler'ы с уникальными именами (`nginx reload`, а не просто `reload`).
- [ ] Нет хардкода IP, доменов, паролей.
- [ ] Секреты — только через переменные (vault), `no_log: true` где нужно.
- [ ] Теги на логические блоки (`install`, `config`, `deploy`).
- [ ] `README.md` с таблицей переменных и примером подключения.
- [ ] Проходит `ansible-lint`.
- [ ] Есть `tests/test.yml` (или molecule — тема 13).

---

## 💼 Как это в DevOps

- «В реальных компаниях всё построено на ролях» — это правда: типичный ansible-репозиторий
  это `site.yml` на 20 строк и каталог `roles/` с 10-30 ролями.
- Часть ролей — свои (внутренние стандарты компании), часть — из Galaxy
  (`geerlingguy.*` — самый известный набор).
- Роли версионируют: внутренние роли часто живут в отдельных git-репозиториях
  и подключаются через `requirements.yml` с тегом версии.
- На собеседовании просят: «расскажи структуру роли» и «что положишь в defaults,
  а что в vars» — это отсеивает тех, кто роли только видел.
- Роль — единица ревью и тестирования: MR трогает одну роль, molecule тестирует одну роль.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Создать скелет роли | `ansible-galaxy init roles/nginx` |
| Точка входа роли | `roles/<role>/tasks/main.yml` |
| Настраиваемые переменные | `roles/<role>/defaults/main.yml` |
| Константы роли | `roles/<role>/vars/main.yml` |
| Handler'ы | `roles/<role>/handlers/main.yml` |
| Шаблоны | `roles/<role>/templates/` (в `src:` — просто имя файла) |
| Статические файлы | `roles/<role>/files/` |
| Зависимости | `roles/<role>/meta/main.yml` → `dependencies:` |
| Подключить роль | `roles: [nginx]` в play |
| Роль с параметрами | `- role: nginx` + переменные ниже |
| Роль в середине задач | `import_role` |
| Роль по условию/в цикле | `include_role` |
| Отдельный файл задач роли | `include_role: { tasks_from: install.yml }` |
| Установить чужую роль | `ansible-galaxy role install geerlingguy.nginx` |
| Зафиксировать зависимости | `requirements.yml` + `ansible-galaxy install -r` |
| Разбить задачи на файлы | `import_tasks` / `include_tasks` |

---

## 🧠 Что запомнить

1. ⭐ Структура роли: `tasks/ handlers/ templates/ files/ defaults/ vars/ meta/ tests/`
   (+ `README.md`), точка входа — `tasks/main.yml`.
2. Ansible автоматически подхватывает `main.yml` в каждом каталоге.
3. Одна роль = одна ответственность (один сервис).
4. ⭐ `defaults/` — низший приоритет (для переопределения), `vars/` — высокий (константы).
5. Все переменные роли — с префиксом имени роли.
6. `meta/main.yml` описывает зависимости; они выполняются перед ролью и один раз.
7. Порядок: `pre_tasks` → зависимости+роли → `tasks` → `post_tasks` (+ handler'ы).
8. Параметры роли (`- role: x` + переменные) имеют очень высокий приоритет.
9. `import_role`/`import_tasks` — статически, `include_role`/`include_tasks` — динамически
   (можно `loop` и рантайм-условия).
10. `ansible-galaxy init` создаёт скелет, `requirements.yml` фиксирует внешние роли
    и коллекции с версиями.
11. Чужие роли читают перед применением — они выполняются с root-правами.
12. Признаки хорошей роли: идемпотентность, `defaults`, README, теги, `ansible-lint` зелёный.

---

## Задачи

> ⭐ «Обязательно знать структуру роли» — роадмап. Блок A1 нарисуй по памяти.

---

### Блок A. Теория

**A1.** ⭐⭐ Нарисуй по памяти структуру роли и подпиши, за что отвечает каждый каталог.

<details><summary>Ответ</summary>

```text:no-line-numbers
roles/<name>/
├── tasks/main.yml       что делать (точка входа)
├── handlers/main.yml    реакции на изменения (restart/reload)
├── templates/           .j2-шаблоны
├── files/               статические файлы
├── defaults/main.yml    переменные по умолчанию (низший приоритет)
├── vars/main.yml        внутренние константы (высокий приоритет)
├── meta/main.yml        зависимости и метаданные
├── tests/               минимальный тестовый прогон
└── README.md            описание и таблица переменных
```

</details>

**A2.** Какой файл является точкой входа роли?

<details><summary>Ответ</summary>

`tasks/main.yml`.

</details>

**A3.** Почему Ansible находит `tasks/main.yml` без явного указания?

<details><summary>Ответ</summary>

Ansible по соглашению автоматически подключает `main.yml` из каждого стандартного
каталога роли.

</details>

**A4.** ⭐ Чем `defaults/main.yml` отличается от `vars/main.yml`? Что куда класть?

<details><summary>Ответ</summary>

`defaults` — низший приоритет, предназначены для переопределения пользователем роли
(туда кладут всё настраиваемое). `vars` — высокий приоритет, внутренние константы,
изменение которых сломает роль (пути, имена файлов).

</details>

**A5.** Зачем нужен `meta/main.yml`? Что в нём описывают?

<details><summary>Ответ</summary>

Метаданные роли (автор, лицензия, поддерживаемые платформы, минимальная версия
Ansible) и список зависимостей от других ролей.

</details>

**A6.** Когда выполняются зависимости из `meta` — до или после роли? Сколько раз?

<details><summary>Ответ</summary>

До самой роли; по умолчанию — один раз за play, даже если зависимость указали
несколько ролей (меняется `allow_duplicates: true`).

</details>

**A7.** Чем `files/` отличается от `templates/`?

<details><summary>Ответ</summary>

`files/` — файлы, копируемые как есть (`copy`, `script`); `templates/` — файлы,
проходящие через Jinja2 (`template`).

</details>

**A8.** Почему внутри роли в `src:` можно писать просто имя файла?

<details><summary>Ответ</summary>

Внутри роли пути ищутся относительно её каталогов: `templates/`, `files/`,
`tasks/`, `vars/`.

</details>

**A9.** Зачем переменным роли нужен префикс с её именем?

<details><summary>Ответ</summary>

Переменные в рамках play общие: без префикса роли начнут перезаписывать
переменные друг друга (`port`, `user`, `version` — самые опасные имена).

</details>

**A10.** Как подключить роль в плейбуке? Три способа.

<details><summary>Ответ</summary>

Секцией `roles:` (списком или с параметрами), `import_role` и `include_role`
в задачах.

</details>

**A11.** ⭐ Чем `import_role` отличается от `include_role`? Когда какой?

<details><summary>Ответ</summary>

`import_role` подключается статически при парсинге (теги и `--list-tasks`
работают, но нельзя использовать в цикле); `include_role` — динамически в рантайме
(можно `loop` и условия, но роль не видна заранее).

</details>

**A12.** Чем `import_tasks` отличается от `include_tasks`?

<details><summary>Ответ</summary>

Тот же принцип для файлов задач: `import_tasks` — статически, `include_tasks` —
динамически.

</details>

**A13.** Какой приоритет у параметров роли (`- role: x` + переменные)?

<details><summary>Ответ</summary>

Очень высокий: параметры роли сильнее `defaults`, `group_vars`, `host_vars`
и play vars; слабее только `-e`.

</details>

**A14.** В каком порядке выполняются `pre_tasks`, роли, `tasks`, `post_tasks`?

<details><summary>Ответ</summary>

`pre_tasks` → (handlers) → зависимости ролей и роли → `tasks` → (handlers) →
`post_tasks` → (handlers).

</details>

**A15.** Как подключить не `main.yml`, а другой файл задач роли?

<details><summary>Ответ</summary>

`include_role` с параметром `tasks_from: install.yml`.

</details>

**A16.** Что делает `ansible-galaxy init`?

<details><summary>Ответ</summary>

Создаёт скелет роли со всеми стандартными каталогами и заготовками файлов.

</details>

**A17.** Зачем нужен `requirements.yml` и что в нём фиксируют?

<details><summary>Ответ</summary>

Внешние роли и коллекции с версиями — чтобы у всей команды и в CI были
одинаковые зависимости; устанавливается `ansible-galaxy install -r requirements.yml`.

</details>

**A18.** Как сделать роль кроссплатформенной? Два механизма.

<details><summary>Ответ</summary>

(1) Ветвления по `ansible_os_family` через `when`; (2) файлы переменных под ОС
(`vars/Debian.yml`, `vars/RedHat.yml`) + <code v-pre>include_vars: "{{ ansible_os_family }}.yml"</code>;
плюс универсальный модуль `package`.

</details>

**A19.** На что смотреть перед использованием чужой роли из Galaxy?

<details><summary>Ответ</summary>

Прочитать `tasks/main.yml` и `defaults/main.yml`, проверить, не скачивает ли
роль что-то из интернета, оценить активность репозитория, зафиксировать версию.

</details>

**A20.** Назови пять признаков хорошей роли.

<details><summary>Ответ</summary>

Одна ответственность; настройки в `defaults` с префиксом; идемпотентность;
отсутствие хардкода и секретов; README и теги; проходит `ansible-lint`; есть тесты.

</details>

---

### Блок B. «Что здесь не так»

```yaml
# B1  roles/nginx/vars/main.yml
nginx_port: 80
nginx_server_name: localhost
nginx_max_body: 10m
```
Вопрос: почему это неправильное место для таких переменных?

<details><summary>Ответ</summary>

Это настраиваемые параметры — им место в `defaults`. В `vars` их невозможно
переопределить через `group_vars`/`host_vars`, и роль становится неприменимой в другом окружении.

</details>

```yaml
# B2  roles/nginx/defaults/main.yml
port: 80
user: www-data
```
Вопрос: в чём проблема с именами?

<details><summary>Ответ</summary>

Нет префикса роли: `port`/`user` конфликтуют с переменными других ролей.
Должно быть `nginx_port`, `nginx_user`.

</details>

```yaml
# B3  roles/app/tasks/main.yml
- ansible.builtin.copy:
    src: /home/nurik/projects/app/config.ini
    dest: /etc/app/config.ini
```
Вопрос: две проблемы.

<details><summary>Ответ</summary>

(1) Абсолютный путь с машины конкретного разработчика — роль не переносима;
файл должен лежать в `roles/app/files/`. (2) Конфиг с параметрами лучше делать шаблоном.

</details>

```yaml
# B4
- hosts: web
  roles:
    - nginx
  tasks:
    - ansible.builtin.debug: { msg: "после nginx" }
  pre_tasks:
    - ansible.builtin.debug: { msg: "до всего" }
```
Вопрос: в каком порядке выполнится вывод?

<details><summary>Ответ</summary>

«до всего» (pre_tasks) → задачи роли nginx → «после nginx» (tasks).
Порядок в YAML не важен — важен тип секции.

</details>

```yaml
# B5
- hosts: web
  tasks:
    - ansible.builtin.include_role:
        name: app
      loop: "{{ app_instances }}"
```
Вопрос: сработает ли это с `import_role`? Почему?

<details><summary>Ответ</summary>

С `import_role` не сработает: он статический и не поддерживает `loop`.
Для цикла нужен `include_role`.

</details>

```yaml
# B6  roles/app/handlers/main.yml
- name: restart
  ansible.builtin.service: { name: app, state: restarted }
```
Вопрос: чем опасно такое имя handler'а?

<details><summary>Ответ</summary>

Слишком общее имя: в play с несколькими ролями handler'ы с одинаковыми именами
конфликтуют. Нужно `app restart` / `restart app service`.

</details>

```yaml
# B7  requirements.yml
roles:
  - name: geerlingguy.nginx
```
Вопрос: чего не хватает и чем это грозит?

<details><summary>Ответ</summary>

Нет версии: `ansible-galaxy` поставит последнюю, и обновление автора может
сломать прод. Всегда фиксируй `version:`.

</details>

```yaml
# B8  roles/db/tasks/main.yml
- ansible.builtin.postgresql_user:
    name: app
    password: "SuperSecret123"
```
Вопрос: две проблемы и как правильно.

<details><summary>Ответ</summary>

Пароль захардкожен в роли и попадёт в git; плюс задача напечатает его в логе.
Правильно: переменная из vault + `no_log: true`.

</details>

---

### Блок C. Практика

#### C1. 🔑 Скелет роли

```bash
ansible-galaxy init roles/nginx
tree roles/nginx
```
Выпиши, что создалось, и удали каталоги, которые тебе не нужны (`library`, `module_utils`,
`lookup_plugins`). Объясни, почему их можно удалить.

#### C2. 🔑🔑 Роль `nginx` целиком (главное задание темы и роадмапа)

Сделай роль, которая:
1. проверяет ОС через `assert`;
2. ставит nginx;
3. кладёт `nginx.conf` из шаблона с `validate` и `backup`;
4. раскладывает виртуальные хосты циклом по `nginx_vhosts`;
5. удаляет дефолтный vhost;
6. запускает сервис и включает автозагрузку;
7. имеет handler'ы `nginx reload` и `nginx restart`;
8. все настройки — в `defaults/main.yml` с префиксом `nginx_`;
9. имеет `README.md` с таблицей переменных.
Проверь: плейбук из трёх строк, второй прогон — `changed=0`.

#### C3. Переопределение переменных

Проверь на практике цепочку: значение из `defaults` → перекрыто `group_vars` →
перекрыто `host_vars` → перекрыто параметром роли → перекрыто `-e`.
Составь таблицу результатов.

#### C4. `defaults` vs `vars`

Перенеси `nginx_port` из `defaults` в `vars` и попробуй переопределить его
через `group_vars`. Что произошло? Верни обратно и сформулируй правило.

<details><summary>Ответ</summary>

Из `vars` переменную не переопределить инвентарём — роль перестаёт настраиваться.
Правило: всё, что должен менять пользователь роли, живёт в `defaults`.

</details>

#### C5. 🔑 Роль `common`

Сделай роль базовой настройки сервера: часовой пояс, пакеты (curl, git, htop, vim),
пользователь `deploy` с ключом, настройка sshd (`PermitRootLogin no`, `PasswordAuthentication no`)
с `validate`, простейший firewall. Подключи её ко всем хостам.

#### C6. Зависимости

Сделай `nginx` зависимой от `common` через `meta/main.yml`. Убедись, что `common`
выполняется первой. Затем подключи обе роли явно в play и проверь, что `common`
не выполнилась дважды.

<details><summary>Ответ</summary>

При явном подключении обеих ролей `common` выполнится один раз (зависимости
не дублируются), если в её `meta` нет `allow_duplicates: true`.

</details>

#### C7. Разбиение задач на файлы

Разбей `tasks/main.yml` роли `app` на `install.yml`, `configure.yml`, `deploy.yml`,
подключи их с тегами. Проверь `--tags deploy` и `--list-tasks`.

#### C8. `include_role` в цикле

Сделай роль `vhost`, которая настраивает один виртуальный хост, и подключи её
циклом по списку из трёх сайтов через `include_role`. Затем попробуй `import_role`
и объясни ошибку.

<details><summary>Ответ</summary>

`import_role` в цикле даст ошибку (статическое подключение не поддерживает `loop`).

</details>

#### C9. Чужая роль из Galaxy

```bash
ansible-galaxy role install geerlingguy.docker -p roles/
```
1. Прочитай её `defaults/main.yml` и `tasks/main.yml`.
2. Подключи с параметрами (например, версия docker, пользователи в группе docker).
3. Выпиши три вещи, которые тебе понравились в оформлении этой роли.

#### C10. `requirements.yml`

Создай `requirements.yml` с одной ролью из Galaxy и двумя коллекциями с фиксированными
версиями. Проверь установку в чистом каталоге:
```bash
ansible-galaxy install -r requirements.yml -p roles/
ansible-galaxy collection install -r requirements.yml -p collections/
```

#### C11. 🔑 Рефакторинг плейбука в роли

Возьми свой плейбук из темы 06/08 (пакеты + конфиг + сервис + пользователи) и разложи
на роли `common`, `nginx`, `app` по алгоритму из §8 конспекта. `site.yml` должен
уместиться в 15 строк. Проверь идемпотентность.

#### C12. Кроссплатформенность (со звёздочкой)

Сделай роль, которая ставит nginx и на Debian, и на RedHat: `vars/Debian.yml`,
`vars/RedHat.yml`, <code v-pre>include_vars: "{{ ansible_os_family }}.yml"</code> и модуль `package`.
Проверь на контейнерах `ubuntu:22.04` и `rockylinux:9`.

#### C13. Тест роли

Создай `roles/nginx/tests/{inventory,test.yml}` и прогони роль на одном хосте
через этот мини-плейбук. Что проверяет такой тест, а что нет?

<details><summary>Ответ</summary>

Такой тест проверяет, что роль синтаксически корректна и отрабатывает
на чистом хосте; он не проверяет идемпотентность и результат (для этого — второй прогон
и проверки/molecule).

</details>

---

### Блок D. Инциденты

**D1.** Роль не видит свой шаблон: `Could not find or access 'nginx.conf.j2'`. Причины.

<details><summary>Ответ</summary>

Шаблон лежит не в `roles/<role>/templates/`, опечатка в имени, либо задача вызвана
вне роли (тогда путь ищется относительно плейбука).

</details>

**D2.** Две роли определяют переменную `port` — конфиг приложения получил порт от nginx.
Как чинить и как предотвращать?

<details><summary>Ответ</summary>

Переименовать переменные с префиксами ролей; предотвращать — соглашением
об именовании и `ansible-lint`.

</details>

**D3.** Handler из роли `app` перезапустил сервис роли `db`. Почему и как исправить?

<details><summary>Ответ</summary>

Имена handler'ов глобальны в рамках play: совпали имена. Лечится префиксами
(`app restart`) или темами `listen`.

</details>

**D4.** Переменную роли невозможно переопределить из `group_vars`. Где она объявлена?

<details><summary>Ответ</summary>

В `vars/main.yml` роли (высокий приоритет) — нужно перенести в `defaults/main.yml`.

</details>

**D5.** Роль `common` выполнилась дважды. Почему так может быть и как это контролировать?

<details><summary>Ответ</summary>

Если роль подключена и как зависимость, и явно, а в её `meta` стоит
`allow_duplicates: true`, либо она подключена в разных play. Контролируется
`allow_duplicates` и структурой плейбука.

</details>

**D6.** После обновления роли из Galaxy плейбук сломался на проде. Что не сделали заранее?

<details><summary>Ответ</summary>

Не зафиксировали версию роли в `requirements.yml` и не прогнали изменения
на dev/staging перед продом.

</details>

**D7.** Объясни разницу поведения `when` у `import_role` и `include_role`.

<details><summary>Ответ</summary>

У `import_role` условие `when` копируется на **каждую задачу** роли (проверяется
многократно, задачи видны в `--list-tasks`); у `include_role` оно проверяется **один раз**
при подключении — если ложно, роль не подключается вовсе.

</details>

**D8.** `--tags config` не запускает задачи внутри роли, подключённой через `include_role`.
Почему?

<details><summary>Ответ</summary>

При динамическом подключении Ansible не знает о задачах роли на этапе разбора
тегов; теги нужно указывать на самом `include_role` (`apply: tags:`) или использовать
`import_role`.

</details>

**D9.** Роль работает на Ubuntu и падает на Rocky на этапе установки пакета. Что поправить?

<details><summary>Ответ</summary>

Разные имена пакетов/путей: добавить `vars/<os_family>.yml` + `include_vars`,
использовать `package`, ветвления по `ansible_os_family`.

</details>

**D10.** В роли лежит `files/id_rsa` с приватным ключом. Что не так и как правильно?

<details><summary>Ответ</summary>

Приватный ключ в репозитории — утечка. Ключи передают через vault-переменные
или внешнее хранилище секретов, а в роль — через переменную с `no_log: true`.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Что такое роль в Ansible? (топ-вопрос роадмапа)

<details><summary>Ответ</summary>

Структурированный переиспользуемый набор задач, шаблонов, файлов, переменных
и handler'ов для одной ответственности (одного сервиса), подключаемый к плейбуку.

</details>

**2.** ⭐⭐ Расскажи структуру роли. (обязательно знать)

<details><summary>Ответ</summary>

См. ответ на A1 (обязательно назвать `tasks`, `handlers`, `templates`, `files`, `defaults`,
`vars`, `meta`, плюс `tests`/`README`).

</details>

**3.** Чем `defaults` отличается от `vars`?

<details><summary>Ответ</summary>

`defaults` — низший приоритет и место для настраиваемых значений; `vars` — высокий
приоритет и место для констант роли.

</details>

**4.** Что описывают в `meta/main.yml`?

<details><summary>Ответ</summary>

Метаданные (автор, лицензия, платформы, минимальная версия) и зависимости.

</details>

**5.** Как подключить роль к плейбуку?

<details><summary>Ответ</summary>

Секцией `roles:` в play, либо `import_role`/`include_role` в задачах.

</details>

**6.** Чем `import_role` отличается от `include_role`?

<details><summary>Ответ</summary>

Статическое подключение при парсинге против динамического в рантайме
(`include_role` умеет `loop` и рантайм-условия, но не виден в `--list-tasks`).

</details>

**7.** Как переопределить переменную роли?

<details><summary>Ответ</summary>

Через `group_vars`/`host_vars`, play vars, параметры роли или `-e` — при условии,
что переменная объявлена в `defaults`, а не в `vars`.

</details>

**8.** Что такое Ansible Galaxy?

<details><summary>Ответ</summary>

Публичный репозиторий ролей и коллекций + одноимённая CLI-утилита
(`ansible-galaxy init/install/search`).

</details>

**9.** Как организован ваш ansible-репозиторий? (частый практический вопрос)

<details><summary>Ответ</summary>

Ожидаемый ответ: `ansible.cfg`, `site.yml`, `inventories/<env>/` с `group_vars`,
каталог `roles/` (свои + внешние через `requirements.yml`), секреты в vault,
CI с `ansible-lint` и `--check`.

</details>

**10.** Как бы ты разбил на роли настройку веб-приложения с БД и мониторингом?

<details><summary>Ответ</summary>

Роли: `common` (база), `docker` или `postgresql`, `nginx`, `app`, `monitoring`;
порядок и зависимости — через play и `meta`, окружения — через инвентари и переменные.

</details>

---

### 🎯 Чек-лист

- [ ] ⭐ Рисую структуру роли по памяти и объясняю каждый каталог
- [ ] Сделал полноценную роль `nginx` с шаблонами, handler'ами и README
- [ ] Все настраиваемые переменные — в `defaults` с префиксом роли
- [ ] Понимаю разницу `defaults` и `vars` и проверил её экспериментом
- [ ] Использовал зависимости через `meta/main.yml`
- [ ] Знаю разницу `import_role` / `include_role` и когда какой
- [ ] Разбил `tasks/main.yml` на файлы с тегами
- [ ] Поставил и прочитал чужую роль из Galaxy
- [ ] Завёл `requirements.yml` с зафиксированными версиями
- [ ] Разложил свой старый плейбук на роли, `site.yml` стал коротким
