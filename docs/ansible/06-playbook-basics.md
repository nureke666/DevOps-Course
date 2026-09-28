---
title: "06. Playbook: структура и порядок выполнения"
description: "Анатомия playbook, ключи play и task, несколько play, теги, --check/--diff, обработка ошибок"
---

# 06. Playbook: структура и порядок выполнения

> Роадмап → 5. Ansible → 1. Теория → **Playbook**:
> «Playbook — это основная единица работы в Ansible. Если ad-hoc команды — это как команды
> в терминале, то playbook — это как bash-скрипт, только декларативный и идемпотентный.»
> Из списка «надо знать» эта тема закрывает **структуру playbook'а**; handler'ы — тема 09,
> переменные и facts — 07, условия и циклы — 08, шаблоны — 10.
> **После темы ты умеешь:** писать, запускать, отлаживать и безопасно применять плейбуки.

---

## 🗺️ Анатомия

```text:no-line-numbers
playbook (файл site.yml)
│
├── PLAY 1  ─ hosts: web            «кто»
│            become: true           «под кем»
│            vars: {...}            «с какими переменными»
│            pre_tasks: [...]       ① до ролей
│            roles: [...]           ② роли
│            tasks: [...]           ③ основные задачи
│            post_tasks: [...]      ④ после всего
│            handlers: [...]        ⑤ вызываются по notify
│
└── PLAY 2  ─ hosts: db
             tasks: [...]

Порядок внутри play:
 pre_tasks → (handlers) → roles → tasks → (handlers) → post_tasks → (handlers)
```

```yaml
---
- name: Настройка веб-серверов                # имя play
  hosts: web                                  # на каких хостах
  become: true                                # от root
  gather_facts: true                          # собрать факты (по умолчанию true)
  vars:
    http_port: 80
    app_user: deploy

  tasks:
    - name: Установить nginx                  # ⭐ имя задачи — всегда осмысленное
      ansible.builtin.apt:
        name: nginx
        state: present
        update_cache: true

    - name: Положить конфиг
      ansible.builtin.template:
        src: templates/nginx.conf.j2
        dest: /etc/nginx/nginx.conf
        validate: "nginx -t -c %s"
      notify: reload nginx                    # позвать handler, если файл изменился

    - name: Сервис запущен и в автозагрузке
      ansible.builtin.service:
        name: nginx
        state: started
        enabled: true

  handlers:
    - name: reload nginx
      ansible.builtin.service:
        name: nginx
        state: reloaded
```

```bash
ansible-playbook site.yml                    # inventory и become — из ansible.cfg
```

---

## 1. YAML — минимум, который обязан быть в пальцах

```yaml
---                       # начало документа (необязательно, но принято)
ключ: значение            # строка
число: 8080               # число
булево: true              # true/false (не yes/no — устаревающий стиль)
список:
  - первый
  - второй
словарь:
  ключ1: значение
  ключ2: значение
многострочный: |          # сохранить переносы
  строка 1
  строка 2
одна_строка: >            # склеить в одну строку
  этот текст
  станет одной строкой
```

**Правила, на которых спотыкаются все:**
1. **Только пробелы**, никаких табов. Отступ — 2 пробела.
2. Двоеточие + пробел: `name: value` (не `name:value`).
3. Значения с `:`, `{`, `#`, `*`, `%` — в кавычках: `msg: "time: 12:00"`.
4. `mode: "0644"` — в кавычках, иначе YAML превратит в число.
5. Значение, начинающееся с <code v-pre>{{</code> — в кавычках: <code v-pre>path: "{{ app_dir }}/bin"</code>.
6. Плейбук — это **список** play (начинается с `-`), задачи — тоже список.

```bash
ansible-playbook site.yml --syntax-check      # быстрый тест YAML и структуры
yamllint site.yml                             # более строгий линтер
```

---

## 2. Ключи play (шапка)

```yaml
- name: Понятное имя play
  hosts: web:!web3              # паттерн из темы 03
  become: true                  # повышение привилегий
  become_user: root
  gather_facts: true            # false ускоряет, но убирает ansible_* переменные
  vars:
    key: value
  vars_files:
    - vars/common.yml
    - vars/secrets.yml          # может быть зашифрован vault
  vars_prompt:
    - name: app_version
      prompt: "Какую версию деплоим?"
      private: false
  serial: 2                     # ⭐ выполнять волнами по 2 хоста (rolling update)
  max_fail_percentage: 20       # прервать, если упало больше 20% хостов
  any_errors_fatal: true        # ошибка на одном хосте останавливает весь play
  order: shuffle                # inventory | sorted | reverse_sorted | shuffle
  strategy: linear              # linear (по умолчанию) | free | host_pinned
  ignore_unreachable: false
  environment:                  # переменные окружения для всех задач play
    http_proxy: http://proxy:3128
  tags: [web]
  roles:
    - common
    - nginx
  pre_tasks: []
  tasks: []
  post_tasks: []
  handlers: []
```

Самые ценные на практике: `hosts`, `become`, `gather_facts`, `vars`/`vars_files`,
`serial`, `strategy`, `roles`.

---

## 3. Задача (task) и её ключи

```yaml
- name: Развернуть конфиг приложения        # ⭐ обязательно и осмысленно
  ansible.builtin.template:                  # модуль
    src: app.conf.j2                         # параметры модуля
    dest: /etc/app/app.conf
    mode: "0644"
  become: true                               # повышение привилегий для задачи
  when: app_enabled | bool                   # условие (тема 08)
  loop: "{{ app_configs }}"                  # цикл (тема 08)
  register: cfg_result                       # сохранить результат (тема 07)
  notify: restart app                        # позвать handler (тема 09)
  tags: [app, config]                        # метки для выборочного запуска
  ignore_errors: false
  changed_when: cfg_result.rc == 0
  failed_when: false
  no_log: true                               # не печатать (секреты!)
  delegate_to: localhost                     # выполнить на другом хосте
  run_once: true                             # выполнить один раз на весь play
  retries: 3                                 # с until (тема 08)
  delay: 5
  async: 300                                 # асинхронно
  poll: 0
  environment:
    APP_ENV: prod
```

> 💡 `name:` — не формальность: это то, что видно в выводе и в CI-логах. Плейбук
> без имён задач невозможно читать при инциденте.

---

## 4. Несколько play в одном плейбуке

```yaml
---
- name: Общая подготовка всех серверов
  hosts: all
  become: true
  roles: [common]

- name: Базы данных
  hosts: db
  become: true
  roles: [postgresql]

- name: Веб-серверы (после того, как поднялись БД)
  hosts: web
  become: true
  serial: 1                       # по одному — без даунтайма
  roles: [nginx, app]

- name: Проверка снаружи
  hosts: localhost
  connection: local
  gather_facts: false
  tasks:
    - name: Сайт отвечает
      ansible.builtin.uri:
        url: "https://{{ item }}/health"
        status_code: 200
      loop: "{{ groups['web'] }}"
```

**Play выполняются строго по очереди** — это и есть встроенная оркестрация:
сначала БД, потом приложение, потом проверка.

### `import_playbook` — собрать большой прогон из маленьких
```yaml
# site.yml
- import_playbook: playbooks/common.yml
- import_playbook: playbooks/db.yml
- import_playbook: playbooks/web.yml
```

---

## 5. `pre_tasks`, `roles`, `tasks`, `post_tasks` — порядок

```yaml
- hosts: web
  become: true
  pre_tasks:
    - name: Вывести хост из балансировщика
      ansible.builtin.uri: { url: "http://lb/api/disable/{{ inventory_hostname }}" }
      delegate_to: localhost

  roles:
    - nginx
    - app

  tasks:
    - name: Дополнительная настройка, не влезшая в роли
      ansible.builtin.lineinfile: { path: /etc/motd, line: "deployed by ansible" }

  post_tasks:
    - name: Вернуть хост в балансировщик
      ansible.builtin.uri: { url: "http://lb/api/enable/{{ inventory_hostname }}" }
      delegate_to: localhost
```

Порядок: **pre_tasks → handlers(если позвали) → roles → tasks → handlers → post_tasks → handlers**.
Типичное применение: `pre_tasks` — вывод из ротации/проверка предусловий,
`post_tasks` — возврат в ротацию, smoke-тест, уведомление.

---

## 6. Запуск и флаги (то, чем пользуешься каждый день)

```bash
ansible-playbook site.yml                          # обычный запуск
ansible-playbook site.yml -i inventories/prod/     # другой инвентарь
ansible-playbook site.yml --limit web1             # ⭐ только один хост
ansible-playbook site.yml --check --diff           # ⭐ сухой прогон + различия
ansible-playbook site.yml --tags nginx             # только задачи с тегом
ansible-playbook site.yml --skip-tags slow
ansible-playbook site.yml -e "app_version=1.2.3"   # переменная (высший приоритет)
ansible-playbook site.yml -e @vars/prod.yml        # переменные из файла
ansible-playbook site.yml --start-at-task "Положить конфиг"
ansible-playbook site.yml --step                   # спрашивать перед каждой задачей
ansible-playbook site.yml --list-tasks             # что будет выполняться
ansible-playbook site.yml --list-hosts             # где будет выполняться
ansible-playbook site.yml --list-tags
ansible-playbook site.yml --syntax-check
ansible-playbook site.yml -v / -vv / -vvv / -vvvv  # подробность
ansible-playbook site.yml -f 20                    # параллелизм
ansible-playbook site.yml -K                       # спросить sudo-пароль
```

### ⭐ `--check` и `--diff` — главная страховка

```bash
ansible-playbook site.yml --check --diff --limit web1
```
- `--check` — «сухой прогон»: модули сообщают, что бы они изменили, ничего не меняя.
- `--diff` — показывает построчные различия файлов (для `copy`/`template`/`lineinfile`).

Ограничения check mode (**важно понимать**):
- `command`/`shell` в check mode **пропускаются** (`skipped`) — их эффект не предсказывается;
- задачи, зависящие от результата пропущенных задач, могут ложно падать или пропускаться;
- чтобы задача всё же выполнялась в check mode: `check_mode: false` (например, безопасное чтение).

```yaml
- name: Узнать текущую версию (безопасно в check mode)
  ansible.builtin.command: /opt/app/bin/app --version
  register: ver
  changed_when: false
  check_mode: false
```

---

## 7. Теги — выборочный запуск

```yaml
tasks:
  - name: Установить пакеты
    ansible.builtin.apt: { name: nginx, state: present }
    tags: [install, packages]

  - name: Конфиг
    ansible.builtin.template: { src: nginx.conf.j2, dest: /etc/nginx/nginx.conf }
    tags: [config]

  - name: Долгая проверка
    ansible.builtin.command: /opt/check-all.sh
    tags: [never, slow]           # ⭐ never — только по явному указанию тега

  - name: Всегда проверять предусловия
    ansible.builtin.assert: { that: app_version is defined }
    tags: [always]                # ⭐ always — выполняется всегда
```

```bash
ansible-playbook site.yml --tags config          # только конфиги
ansible-playbook site.yml --tags "install,config"
ansible-playbook site.yml --skip-tags slow
ansible-playbook site.yml --tags slow            # запустит задачу с 'never'
ansible-playbook site.yml --list-tags
```

Специальные теги: `always` (всегда), `never` (только по явному вызову),
`tagged`/`untagged`/`all`.

> 💡 Практика: теги `config`, `deploy`, `packages` экономят минуты при отладке —
> не надо гонять весь плейбук ради одного конфига.

---

## 8. Вывод плейбука и PLAY RECAP

```text:no-line-numbers
PLAY [Настройка веб-серверов] **************************************

TASK [Gathering Facts] *********************************************
ok: [web1]
ok: [web2]

TASK [Установить nginx] ********************************************
changed: [web1]
ok: [web2]

TASK [Положить конфиг] *********************************************
changed: [web1]
changed: [web2]

RUNNING HANDLER [reload nginx] *************************************
changed: [web1]
changed: [web2]

PLAY RECAP *********************************************************
web1 : ok=4  changed=3  unreachable=0  failed=0  skipped=0  rescued=0  ignored=0
web2 : ok=4  changed=2  unreachable=0  failed=0  skipped=0  rescued=0  ignored=0
```

| Счётчик | Смысл |
|---------|-------|
| `ok` | Задача выполнена, изменений не потребовалось (или задача — проверка) |
| `changed` | Состояние изменено ⭐ на втором прогоне должно быть 0 |
| `unreachable` | Хост недоступен (SSH) |
| `failed` | Задача упала |
| `skipped` | Пропущена по `when`/тегам/check mode |
| `rescued` | Ошибка перехвачена блоком `rescue` (тема 08) |
| `ignored` | Ошибка проигнорирована (`ignore_errors: true`) |

Читаемый вывод и тайминги:
```ini
# ansible.cfg
[defaults]
stdout_callback = yaml
callbacks_enabled = timer, profile_tasks
```

---

## 9. Обработка ошибок: что происходит при падении

По умолчанию: **хост, на котором задача упала, выбывает из play**, остальные продолжают.

```yaml
- hosts: web
  any_errors_fatal: true         # ошибка на любом хосте → останавливаем весь play
  max_fail_percentage: 30        # или: прерваться, если упало > 30% хостов
  tasks:
    - name: Может упасть, и это нормально
      ansible.builtin.command: /opt/optional.sh
      ignore_errors: true

    - name: Ошибка не считается ошибкой при определённом выводе
      ansible.builtin.command: /opt/check.sh
      register: r
      failed_when: r.rc not in [0, 2]
```
Подробнее (`block`/`rescue`/`always`) — тема [08. Условия и циклы](/ansible/08-conditions-loops).

---

## 10. Как писать плейбуки, чтобы их не стыдно было показать

```yaml
# ✅ хорошо
---
- name: Развернуть веб-приложение
  hosts: web
  become: true
  vars_files:
    - vars/main.yml
  roles:
    - common
    - nginx
    - app
```
Правила:
1. У каждого play и задачи — понятный `name` (глаголом, по-русски или по-английски — но единообразно).
2. Модули — по FQCN (`ansible.builtin.apt`).
3. Никаких секретов в открытом виде (тема 12) и `no_log: true` на чувствительных задачах.
4. Всё, что длиннее ~50 задач, разбивается на **роли** (тема 11).
5. Переменные — в `group_vars`/`defaults`, не разбросаны по задачам.
6. `--check --diff` должен отрабатывать без ошибок — это признак аккуратного плейбука.
7. Идемпотентность проверяется вторым прогоном, а не на веру.
8. `ansible-lint` в CI (тема 13).

---

## 💼 Как это в DevOps

- Плейбук — артефакт, который живёт в git и проходит ревью. «Скинуть плейбук в личку» —
  антипаттерн ровно как «скинуть пайплайн в личку».
- Ритуал применения на проде: `--syntax-check` → `--check --diff --limit один_хост` →
  реальный прогон на одном хосте → прогон на группе (часто с `serial`).
- `serial: 1` + health-check в `post_tasks` — самый дешёвый rolling update без Kubernetes.
- Теги и `--start-at-task` экономят часы при отладке длинных прогонов.
- В CI плейбук запускают из джобы деплоя; секреты приезжают из CI/CD Variables
  (см. блок CI/CD, тема 06).

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Запустить | `ansible-playbook site.yml` |
| Проверить синтаксис | `--syntax-check` |
| Сухой прогон с различиями | `--check --diff` |
| Только один хост | `--limit web1` |
| Только часть задач | `--tags config` |
| Пропустить часть | `--skip-tags slow` |
| Передать переменную | `-e "app_version=1.2.3"` |
| Переменные из файла | `-e @vars/prod.yml` |
| Продолжить с задачи | `--start-at-task "Имя задачи"` |
| Пошаговый режим | `--step` |
| Посмотреть список задач | `--list-tasks` |
| Спросить sudo-пароль | `-K` |
| Волнами по N хостов | `serial: N` в play |
| Ошибка на одном = стоп всем | `any_errors_fatal: true` |
| Выполнить один раз | `run_once: true` |
| Выполнить на другом хосте | `delegate_to: localhost` |
| Скрыть секрет из вывода | `no_log: true` |

---

## 🧠 Что запомнить

1. Playbook — список **play**; play = «хосты + задачи»; задачи выполняются сверху вниз.
2. Порядок внутри play: `pre_tasks` → `roles` → `tasks` → `post_tasks`,
   handler'ы — после каждого блока.
3. Несколько play = встроенная оркестрация (сначала БД, потом приложение, потом проверка).
4. YAML: пробелы вместо табов, `key: value` с пробелом, `"0644"` и <code v-pre>"{{ var }}"</code> в кавычках.
5. `name:` у каждой задачи — иначе вывод нечитаем.
6. `--check --diff --limit` — обязательный ритуал перед прогоном на проде.
7. В check mode `command`/`shell` пропускаются; `check_mode: false` — для безопасных проверок.
8. Теги `always`/`never` и `--tags`/`--skip-tags` дают выборочный запуск.
9. `serial` — раскатка волнами, `any_errors_fatal`/`max_fail_percentage` — политика падений.
10. По умолчанию упавший хост выбывает из play, остальные продолжают.
11. PLAY RECAP — главный отчёт: `changed=0` на повторе = плейбук идемпотентен.
12. Длинный плейбук → роли (тема 11).

---

## Задачи

> Всё делаем в каталоге проекта с `ansible.cfg` и инвентарём из темы 03.

---

### Блок A. Теория

**A1.** Что такое playbook и чем он отличается от ad-hoc команды?

<details><summary>Ответ</summary>

Playbook — YAML-файл со списком play: описывает, что и на каких хостах привести
в нужное состояние. В отличие от ad-hoc он версионируется, повторяем, поддерживает
переменные, условия, циклы, handler'ы и роли.

</details>

**A2.** Что такое play? Из каких обязательных частей он состоит?

<details><summary>Ответ</summary>

Play — связка «хосты + задачи». Обязательны `hosts` и хотя бы одна секция
с работой (`tasks`/`roles`); остальное опционально.

</details>

**A3.** ⭐ Назови порядок выполнения секций внутри play.

<details><summary>Ответ</summary>

`pre_tasks` → handlers (если были уведомлены) → `roles` → `tasks` → handlers →
`post_tasks` → handlers.

</details>

**A4.** Зачем нужны `pre_tasks` и `post_tasks`? Приведи реальный пример каждого.

<details><summary>Ответ</summary>

`pre_tasks` — подготовка: проверка предусловий, вывод хоста из балансировщика,
снятие бэкапа. `post_tasks` — завершение: возврат в балансировщик, smoke-тест,
уведомление в чат.

</details>

**A5.** Может ли в одном файле быть несколько play? Зачем это нужно?

<details><summary>Ответ</summary>

Да. Это даёт оркестрацию: сначала настраиваются БД, затем приложения, затем
выполняется проверка — в одном прогоне и в нужном порядке.

</details>

**A6.** Что делает `import_playbook`?

<details><summary>Ответ</summary>

Подключает другой плейбук целиком (на уровне play) — способ собрать `site.yml`
из отдельных файлов.

</details>

**A7.** Что делает `gather_facts: false` и когда это оправдано?

<details><summary>Ответ</summary>

Отключает сбор фактов: прогон быстрее, но недоступны `ansible_*` переменные.
Оправдано, когда факты не нужны (простые операции, `localhost`, ad-hoc-подобные плейбуки).

</details>

**A8.** Что делает `serial: 2`? Как это связано с даунтаймом?

<details><summary>Ответ</summary>

Выполнять play волнами по 2 хоста: пока обновляются два, остальные продолжают
обслуживать трафик — базовый rolling update.

</details>

**A9.** Чем `any_errors_fatal: true` отличается от `max_fail_percentage: 30`?

<details><summary>Ответ</summary>

`any_errors_fatal: true` останавливает весь play при первой ошибке на любом хосте.
`max_fail_percentage` допускает ошибки, но прерывает, когда доля упавших хостов превысила порог.

</details>

**A10.** Что произойдёт по умолчанию, если задача упала на одном из пяти хостов?

<details><summary>Ответ</summary>

Этот хост исключается из дальнейших задач play; остальные продолжают выполнение.

</details>

**A11.** ⭐ Что делает `--check`? Какие задачи в этом режиме не выполняются и почему?

<details><summary>Ответ</summary>

Сухой прогон: модули сообщают, что бы изменили, но не меняют. `command`/`shell`
пропускаются, потому что Ansible не может предсказать их эффект.

</details>

**A12.** Что делает `--diff` и для каких модулей он информативен?

<details><summary>Ответ</summary>

Показывает построчные различия — информативен для `copy`, `template`, `lineinfile`,
`blockinfile`, `file` (права).

</details>

**A13.** Зачем `check_mode: false` у отдельной задачи?

<details><summary>Ответ</summary>

Чтобы задача выполнялась даже в check mode: обычно для безопасных «чтений»
(узнать версию, получить список), результат которых нужен следующим задачам.

</details>

**A14.** Как запустить только часть плейбука? Три способа.

<details><summary>Ответ</summary>

Теги (`--tags`/`--skip-tags`), `--start-at-task`, `--limit` (ограничение по хостам);
плюс `--step` для пошагового выбора.

</details>

**A15.** Что делают теги `always` и `never`?

<details><summary>Ответ</summary>

`always` — задача выполняется при любом наборе тегов; `never` — только если тег
указан явно (удобно для опасных/долгих операций).

</details>

**A16.** Что означают счётчики `rescued` и `ignored` в PLAY RECAP?

<details><summary>Ответ</summary>

`rescued` — сколько раз ошибка была перехвачена секцией `rescue`;
`ignored` — сколько ошибок проигнорировано через `ignore_errors: true`.

</details>

**A17.** Что делает `run_once: true`? А `delegate_to: localhost`?

<details><summary>Ответ</summary>

`run_once: true` — выполнить задачу один раз (на первом подходящем хосте),
результат доступен остальным. `delegate_to: localhost` — выполнить задачу на управляющей
машине, сохранив контекст текущего хоста (полезно для API балансировщика, DNS, уведомлений).

</details>

**A18.** Зачем `no_log: true`?

<details><summary>Ответ</summary>

Скрывает параметры и вывод задачи из логов — обязательно для задач с секретами.

</details>

**A19.** Почему `mode: 0644` и <code v-pre>path: {{ var }}</code> без кавычек — ошибки YAML?

<details><summary>Ответ</summary>

`0644` без кавычек YAML воспримет как число (и права получатся не те);
значение, начинающееся с <code v-pre>{{</code>, без кавычек YAML считает началом словаря — синтаксическая ошибка.

</details>

**A20.** Как выполнить плейбук, начиная с конкретной задачи?

<details><summary>Ответ</summary>

`--start-at-task "точное имя задачи"`.

</details>

---

### Блок B. «Что делает плейбук»

```yaml
# B1
---
- hosts: all
  gather_facts: false
  tasks:
    - ansible.builtin.ping:
```

<details><summary>Ответ</summary>

Проверить доступность всех хостов без сбора фактов (быстрый ping-плейбук).

</details>

```yaml
# B2
- hosts: web
  become: true
  serial: 1
  tasks:
    - ansible.builtin.service: { name: nginx, state: restarted }
```

<details><summary>Ответ</summary>

Перезапустить nginx на web-хостах по одному (волнами), чтобы не было общего даунтайма.

</details>

```yaml
# B3
- hosts: web
  tasks:
    - ansible.builtin.command: /opt/deploy.sh
      run_once: true
```

<details><summary>Ответ</summary>

Выполнить deploy.sh один раз на весь play (на первом хосте группы), а не на каждом.

</details>

```yaml
# B4
- hosts: web
  pre_tasks:
    - ansible.builtin.uri: { url: "http://lb/disable/{{ inventory_hostname }}" }
      delegate_to: localhost
  roles: [app]
  post_tasks:
    - ansible.builtin.uri: { url: "http://lb/enable/{{ inventory_hostname }}" }
      delegate_to: localhost
```

<details><summary>Ответ</summary>

Вывести хост из балансировщика, применить роль app, вернуть хост обратно;
запросы к LB идут с управляющей машины.

</details>

```yaml
# B5
- hosts: db
  any_errors_fatal: true
  tasks:
    - ansible.builtin.command: /opt/migrate.sh
```

<details><summary>Ответ</summary>

Выполнить миграции на db; при ошибке на любом хосте немедленно остановить весь play.

</details>

```yaml
# B6
- hosts: all
  tasks:
    - ansible.builtin.apt: { name: nginx, state: present }
      tags: [never, install]
```

<details><summary>Ответ</summary>

Задача не выполнится при обычном запуске — только при явном `--tags install`.

</details>

```bash
B7.  ansible-playbook site.yml --check --diff --limit web1
B8.  ansible-playbook site.yml --tags config --skip-tags slow
B9.  ansible-playbook site.yml -e "app_version=2.0.0" -e @vars/prod.yml
B10. ansible-playbook site.yml --start-at-task "Положить конфиг" --step
B11. ansible-playbook site.yml --list-tasks
B12. ansible-playbook site.yml -f 30 -K
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B7.  Сухой прогон с различиями на одном хосте
B8.  Запустить только задачи с тегом config, исключив slow
B9.  Передать переменную и подключить файл переменных (оба — высокий приоритет)
B10. Начать с указанной задачи и подтверждать каждую вручную
B11. Показать список задач, которые будут выполнены
B12. Запустить с параллелизмом 30 и запросом пароля sudo
```

</details>

---

### Блок C. Практика

#### C1. 🔑 Первый плейбук

Напиши `web.yml`: установить nginx, положить `index.html` через `copy`, запустить сервис
и включить автозагрузку. Запусти, затем запусти ещё раз. Приложи PLAY RECAP обоих прогонов
и объясни разницу.

#### C2. Ошибки YAML (тренировка глаза)

Найди и исправь пять ошибок:
```yaml
- hosts: web
  become: true
   vars:
    http_port:8080
    mode: 0644
  tasks:
  - name: Install
    apt:
      name: nginx
       state: present
```
Проверь `--syntax-check`.

<details><summary>Ответ</summary>

Ошибки: лишний отступ у `vars:`; `http_port:8080` без пробела; `mode: 0644`
без кавычек; лишний отступ у `state: present`; (пятая) модуль стоит писать по FQCN
и задачам нужны `name`. Правильный вариант:
```yaml
- hosts: web
  become: true
  vars:
    http_port: 8080
    mode: "0644"
  tasks:
    - name: Установить nginx
      ansible.builtin.apt:
        name: nginx
        state: present
```

</details>

#### C3. Несколько play

Напиши плейбук из трёх play: (1) `all` — базовые пакеты; (2) `db` — установка postgresql;
(3) `web` — nginx. Убедись по выводу, что play выполняются последовательно.

#### C4. `pre_tasks` / `post_tasks`

Добавь в плейбук `pre_tasks` с `debug` «начинаю деплой на» + <code v-pre>{{ inventory_hostname }}</code>
и `post_tasks` с `uri`-проверкой `http://localhost/`. Проверь порядок вывода.

#### C5. 🔑 `--check --diff`

1. Измени `index.html` локально.
2. Запусти `ansible-playbook web.yml --check --diff`.
3. Убедись, что файл на сервере не изменился.
4. Запусти без `--check` и сравни вывод.

#### C6. Ограничения check mode

Добавь задачу `command: /usr/bin/uptime` с `register` и следующую задачу с `debug`,
использующую этот результат. Запусти с `--check`. Что произошло? Почини через
`check_mode: false` и `changed_when: false`.

<details><summary>Ответ</summary>

В check mode `command` пропускается, `register` получает `skipped`, и следующая
задача падает при обращении к полю (`'dict object' has no attribute 'stdout'`).
Лечение — `check_mode: false` + `changed_when: false` для задачи-чтения
(и/или `when: not ansible_check_mode`).

</details>

#### C7. Теги

Разметь задачи плейбука тегами `packages`, `config`, `service`. Проверь:
```bash
ansible-playbook web.yml --list-tags
ansible-playbook web.yml --tags config
ansible-playbook web.yml --skip-tags packages
```
Добавь задачу с тегом `never` и убедись, что она запускается только явно.

#### C8. `serial` и rolling update

1. Сделай play с `serial: 1` и задачей рестарта nginx.
2. Запусти и посмотри, как выводится «волнами».
3. Добавь `post_tasks` с проверкой `uri` после рестарта каждого хоста.
4. Сформулируй, зачем это в проде.

#### C9. Поведение при ошибке

1. Добавь задачу `command: /bin/false` в середину плейбука.
2. Запусти — что произошло с остальными задачами на этом хосте? А на других хостах?
3. Добавь `ignore_errors: true` — что изменилось в RECAP?
4. Добавь `any_errors_fatal: true` в play и повтори.

<details><summary>Ответ</summary>

По умолчанию упавший хост выбывает, остальные идут дальше; `ignore_errors: true`
даёт `ignored=1` и продолжение; `any_errors_fatal: true` останавливает play для всех.

</details>

#### C10. Отладка длинного плейбука

Возьми плейбук из 6+ задач:
```bash
ansible-playbook web.yml --list-tasks
ansible-playbook web.yml --start-at-task "<имя 4-й задачи>"
ansible-playbook web.yml --step
```
Опиши, где это пригодится на практике.

#### C11. Читаемый вывод

Включи `stdout_callback = yaml` и `callbacks_enabled = timer, profile_tasks`.
Запусти плейбук и найди самую долгую задачу. Что можно с ней сделать?

<details><summary>Ответ</summary>

`profile_tasks` печатает время каждой задачи. Обычно самая долгая — `apt update`,
установка пакетов или `git`. Лечится `cache_valid_time`, `creates`, `async`, тегами.

</details>

#### C12. 🔑 Полный ритуал прода (репетиция)

Для плейбука из C1 выполни по порядку и зафиксируй результаты:
```bash
ansible-playbook web.yml --syntax-check
ansible-playbook web.yml --list-hosts
ansible-playbook web.yml --check --diff --limit web1
ansible-playbook web.yml --limit web1
ansible-playbook web.yml
ansible-playbook web.yml          # контроль идемпотентности
```

---

### Блок D. Инциденты

**D1.** `ERROR! We were unable to read either as JSON nor YAML`. Что проверять?

<details><summary>Ответ</summary>

Битый YAML: табы, неверные отступы, отсутствие пробела после двоеточия,
спецсимволы без кавычек. Проверять `--syntax-check` и `yamllint`.

</details>

**D2.** `ERROR! 'apt' is not a valid attribute for a Play`. Что со структурой?

<details><summary>Ответ</summary>

Задача написана на уровне play, а не внутри списка `tasks:` — типичная ошибка отступа.

</details>

**D3.** Плейбук отработал `ok`, но изменений на сервере нет. Забыли флаг — какой?

<details><summary>Ответ</summary>

Запуск был с `--check` (сухой прогон).

</details>

**D4.** После падения задачи на `web1` остальные задачи на нём не выполнились,
а `web2` дошёл до конца. Это баг или норма?

<details><summary>Ответ</summary>

Норма: по умолчанию упавший хост исключается из play, остальные продолжают.
Изменить поведение можно `any_errors_fatal` или `max_fail_percentage`.

</details>

**D5.** `--check` показывает ошибки, которых нет при обычном запуске. Почему так бывает?

<details><summary>Ответ</summary>

В check mode `command`/`shell` пропускаются, зависящие от них задачи получают
пустые `register`-результаты, условия ведут себя иначе. Лечится `check_mode: false`
на задачах-чтениях и защитой `when: not ansible_check_mode`.

</details>

**D6.** Плейбук выполняется 40 минут, из них 30 — на одной задаче. Как найти виновника
и что предпринять?

<details><summary>Ответ</summary>

Включить `profile_tasks`/`timer`, найти задачу по времени; варианты:
`cache_valid_time` для apt, `creates`/`checksum` вместо повторных скачиваний,
`async`+`poll: 0` для долгих операций, `gather_facts: false`/`gather_subset`,
кэш фактов, теги для отладки.

</details>

**D7.** Деплой на 20 хостов положил сайт целиком. Какие два ключа play это предотвратили бы?

<details><summary>Ответ</summary>

`serial: 1` (или процент) и проверка здоровья в `post_tasks` вместе с
`any_errors_fatal`/`max_fail_percentage` — раскатка остановится на первой волне.

</details>

**D8.** Задача с секретом напечатала пароль в лог CI. Что нужно было добавить?

<details><summary>Ответ</summary>

`no_log: true` на задаче (и не выводить секреты через `debug`).

</details>

**D9.** Коллега запустил плейбук без `--limit` и применил dev-конфиг на прод.
Как выстроить процесс, чтобы это стало невозможным?

<details><summary>Ответ</summary>

Разделить инвентари по каталогам, прод-инвентарь — с ограниченным доступом,
применение прода — только через CI-джобу с `when: manual` и обязательным `--limit`/`--check`
на предыдущем шаге, ревью изменений через MR.

</details>

**D10.** В плейбуке `hosts: all`, а надо было только web. Плейбук уже запущен.
Что делать сейчас и что изменить потом?

<details><summary>Ответ</summary>

Сейчас: прервать (Ctrl+C), оценить, что успело примениться, при необходимости
откатить конкретные хосты. Потом: фиксировать `hosts:` осмысленно, запускать с `--limit`
и `--check`, а плейбуки уровня «все хосты» держать отдельно.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Что такое playbook? (топ-вопрос роадмапа)

<details><summary>Ответ</summary>

YAML-файл со списком play, описывающий желаемое состояние группы хостов;
основная единица работы Ansible — декларативная, идемпотентная и версионируемая.

</details>

**2.** Чем playbook отличается от ad-hoc команды?

<details><summary>Ответ</summary>

Ad-hoc — одноразовая команда в терминале; playbook — код в репозитории с переменными,
условиями, циклами, handler'ами, ролями и возможностью повторного применения.

</details>

**3.** Из чего состоит play?

<details><summary>Ответ</summary>

`hosts` + параметры выполнения (`become`, `vars`, `serial`…) + секции работы
(`pre_tasks`, `roles`, `tasks`, `post_tasks`, `handlers`).

</details>

**4.** В каком порядке выполняются `pre_tasks`, `roles`, `tasks`, `post_tasks`?

<details><summary>Ответ</summary>

`pre_tasks` → handlers → `roles` → `tasks` → handlers → `post_tasks` → handlers.

</details>

**5.** Что такое `--check` и зачем он нужен?

<details><summary>Ответ</summary>

Сухой прогон: показывает, что изменилось бы, ничего не меняя; вместе с `--diff` —
основная проверка перед применением на проде.

</details>

**6.** Как выполнить только часть плейбука?

<details><summary>Ответ</summary>

Тегами, `--start-at-task`, `--limit`, `--step`.

</details>

**7.** Как сделать раскатку без даунтайма средствами Ansible?

<details><summary>Ответ</summary>

`serial` (волнами) + вывод/возврат в балансировщик в `pre_tasks`/`post_tasks` +
health-check и `any_errors_fatal`/`max_fail_percentage`.

</details>

**8.** Что происходит, если задача упала на одном из хостов?

<details><summary>Ответ</summary>

Хост выбывает из play, остальные продолжают; поведение настраивается.

</details>

**9.** Как передать переменную при запуске?

<details><summary>Ответ</summary>

`-e "key=value"` или `-e @file.yml` — это высший приоритет переменных.

</details>

**10.** Как отладить плейбук, который падает на середине?

<details><summary>Ответ</summary>

`--list-tasks`, `-vvv`, `--start-at-task`, `--step`, `profile_tasks`,
`debug`/`register`, прогон на одном хосте через `--limit`.

</details>

---

### 🎯 Чек-лист

- [ ] Написал плейбук, который на втором прогоне даёт `changed=0`
- [ ] Знаю порядок `pre_tasks` → roles → tasks → post_tasks → handlers
- [ ] Уверенно читаю PLAY RECAP и все его счётчики
- [ ] YAML-ошибки нахожу глазами и через `--syntax-check`
- [ ] `--check --diff --limit` — ритуал перед прогоном
- [ ] Понимаю ограничения check mode и знаю про `check_mode: false`
- [ ] Пользуюсь тегами, `--start-at-task` и `--step` при отладке
- [ ] Пробовал `serial` и понимаю, зачем он в проде
- [ ] Знаю, что происходит при падении задачи и как это менять
