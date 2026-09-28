---
title: "08. Условия и циклы: when, loop, обработка ошибок"
description: "when, loop, loop_control, until/retries, ignore_errors/failed_when/changed_when, block/rescue/always"
---

# 08. Условия и циклы: `when`, `loop`, обработка ошибок

> Роадмап → 5. Ansible → Playbook → **«Условия и циклы — `when`, `loop`»**.
> **После темы ты умеешь:** выполнять задачи выборочно, повторять их по спискам,
> ждать готовности сервиса и корректно обрабатывать ошибки.

---

## 🗺️ Карта темы

```text:no-line-numbers
 УСЛОВИЯ                 ЦИКЛЫ                  ОШИБКИ И ПОВТОРЫ
 ┌───────────────┐      ┌────────────────┐     ┌────────────────────┐
 │ when          │      │ loop           │     │ ignore_errors      │
 │ when + facts  │      │ loop + dict    │     │ failed_when        │
 │ when + register│     │ loop_control   │     │ changed_when       │
 │ when + loop   │      │ with_* (legacy)│     │ until/retries/delay│
 └───────────────┘      └────────────────┘     │ block/rescue/always│
                                               └────────────────────┘
```

---

## 1. `when` — условное выполнение

```yaml
- name: Только для Debian-семейства
  ansible.builtin.apt: { name: nginx, state: present }
  when: ansible_os_family == "Debian"

- name: Только для RedHat-семейства
  ansible.builtin.dnf: { name: nginx, state: present }
  when: ansible_os_family == "RedHat"
```

> ⚠️ **В `when` фигурные скобки не нужны** — это уже выражение Jinja2.
> Неправильно: <code v-pre>when: {{ x }} == 1</code>; правильно `when: x == 1`.

### Операторы и проверки

```yaml
when: app_env == "production"
when: app_env != "dev"
when: app_port | int > 1024
when: ansible_memtotal_mb >= 2048
when: app_version is defined              # переменная существует
when: app_version is not defined
when: app_enabled                         # булево значение
when: not app_enabled
when: app_enabled | bool                  # строку "yes"/"true" привести к булеву
when: "'nginx' in installed_packages"     # вхождение в список
when: ansible_distribution in ['Ubuntu', 'Debian']
when: inventory_hostname == groups['web'][0]      # только первый хост группы
when: ansible_hostname is match("^web[0-9]+$")    # регулярка
when: result.rc == 0
when: result is succeeded                 # succeeded | failed | changed | skipped
when: cfg.stat.exists
when: ansible_check_mode                  # только в сухом прогоне
```

### Несколько условий

```yaml
# список = И (AND) — самый читаемый способ
when:
  - ansible_os_family == "Debian"
  - app_env == "production"
  - app_version is defined

# явные операторы
when: ansible_os_family == "Debian" and app_env == "production"
when: app_env == "staging" or app_env == "production"
when: not (app_env == "dev")
when: (a == 1 and b == 2) or c == 3
```

### Условие на несколько задач сразу — `block`

```yaml
- name: Всё для production
  when: app_env == "production"
  block:
    - name: Мониторинг
      ansible.builtin.apt: { name: node-exporter, state: present }
    - name: Бэкапы
      ansible.builtin.cron: { name: backup, hour: "3", job: /opt/backup.sh }
```

### `when` вместе с `loop`
Условие проверяется **для каждого элемента** отдельно:
```yaml
- name: Ставим только разрешённые пакеты
  ansible.builtin.apt: { name: "{{ item.name }}", state: present }
  loop: "{{ packages }}"
  when: item.enabled | bool
```

---

## 2. `loop` — циклы

```yaml
# простой список
- name: Установить пакеты
  ansible.builtin.apt: { name: "{{ item }}", state: present }
  loop: [nginx, git, curl, htop]

# список из переменной
- ansible.builtin.apt: { name: "{{ item }}", state: present }
  loop: "{{ packages }}"

# список словарей ⭐ самый частый рабочий вариант
- name: Создать пользователей
  ansible.builtin.user:
    name: "{{ item.name }}"
    groups: "{{ item.groups }}"
    shell: "{{ item.shell | default('/bin/bash') }}"
  loop:
    - { name: deploy,  groups: "docker,sudo" }
    - { name: monitor, groups: "docker", shell: /usr/sbin/nologin }
```

> 💡 Для пакетов цикл почти всегда **не нужен**: `apt`/`dnf` принимают список
> и ставят всё одной транзакцией — это быстрее.
> ```yaml
> - ansible.builtin.apt:
>     name: [nginx, git, curl]      # ✅ один вызов вместо трёх
>     state: present
> ```

### `loop_control` — управление циклом

```yaml
- name: Разложить конфиги
  ansible.builtin.template:
    src: "{{ item.src }}"
    dest: "{{ item.dest }}"
  loop: "{{ configs }}"
  loop_control:
    loop_var: config          # переименовать item → config (нужно во вложенных циклах)
    label: "{{ item.dest }}"  # ⭐ что показывать в выводе вместо всего словаря
    index_var: idx            # доступен номер итерации
    pause: 2                  # пауза между итерациями, сек
```
`label` особенно полезен, когда в цикле есть секреты или огромные структуры —
в лог попадёт только метка.

### Полезные конструкции

```yaml
# словарь → список пар
- ansible.builtin.debug: { msg: "{{ item.key }} = {{ item.value }}" }
  loop: "{{ app_settings | dict2items }}"

# несколько списков попарно
- ansible.builtin.debug: { msg: "{{ item.0 }} -> {{ item.1 }}" }
  loop: "{{ names | zip(ports) | list }}"

# все комбинации (декартово произведение)
- ansible.builtin.debug: { msg: "{{ item.0 }}/{{ item.1 }}" }
  loop: "{{ ['web','db'] | product(['dev','prod']) | list }}"

# файлы по маске (на управляющей машине)
- ansible.builtin.copy: { src: "{{ item }}", dest: /etc/app/ }
  loop: "{{ lookup('fileglob', 'files/conf.d/*.conf', wantlist=True) }}"

# цикл по хостам группы
- ansible.builtin.debug: { msg: "{{ hostvars[item].ansible_default_ipv4.address }}" }
  loop: "{{ groups['web'] }}"

# вложенный цикл через include_tasks (у каждого уровня свой loop_var)
- ansible.builtin.include_tasks: user_dirs.yml
  loop: "{{ users }}"
  loop_control: { loop_var: user }
```

### `with_*` — устаревший синтаксис (читать уметь надо)

| Старое | Новое |
|--------|-------|
| `with_items` | `loop` (+ `flatten` для вложенных списков) |
| `with_dict` | <code v-pre>loop: "{{ d \| dict2items }}"</code> |
| `with_fileglob` | <code v-pre>loop: "{{ lookup('fileglob', ..., wantlist=True) }}"</code> |
| `with_nested` | <code v-pre>loop: "{{ a \| product(b) \| list }}"</code> |
| `with_together` | <code v-pre>loop: "{{ a \| zip(b) \| list }}"</code> |
| `with_sequence` | <code v-pre>loop: "{{ range(1, 6) \| list }}"</code> |
| `with_subelements` | <code v-pre>loop: "{{ x \| subelements('y') }}"</code> |

Новый код пишем на `loop`, старый — понимаем.

---

## 3. `register` + `loop`

```yaml
- name: Проверить сервисы
  ansible.builtin.command: "systemctl is-active {{ item }}"
  loop: [nginx, sshd, cron]
  register: svc
  changed_when: false
  failed_when: false

- name: Показать упавшие
  ansible.builtin.debug:
    msg: "НЕ РАБОТАЕТ: {{ item.item }}"
  loop: "{{ svc.results }}"        # ⭐ результаты цикла лежат в .results
  when: item.rc != 0
  loop_control:
    label: "{{ item.item }}"
```

---

## 4. `until` — повторять до успеха (ожидание готовности)

```yaml
- name: Ждём, пока приложение поднимется
  ansible.builtin.uri:
    url: "http://localhost:8080/health"
    status_code: 200
  register: health
  until: health.status == 200
  retries: 12
  delay: 5                       # 12 × 5 с = до минуты ожидания
  changed_when: false
```

```yaml
# альтернатива без HTTP
- ansible.builtin.wait_for:
    port: 5432
    host: "{{ db_host }}"
    delay: 2
    timeout: 60
    state: started
```

`until` — частый элемент деплоя: после рестарта сервис не готов мгновенно,
и без ожидания следующий шаг падает.

---

## 5. Ошибки: `ignore_errors`, `failed_when`, `changed_when`

```yaml
# 1) игнорировать падение
- ansible.builtin.command: /opt/optional-check.sh
  ignore_errors: true

# 2) сам решаю, что считать ошибкой
- ansible.builtin.command: /opt/check.sh
  register: r
  failed_when: r.rc not in [0, 2]          # rc=2 — это «предупреждение», не ошибка

- ansible.builtin.shell: grep ERROR /var/log/app.log
  register: g
  failed_when: false                        # grep без совпадений даёт rc=1 — это норма

# 3) сам решаю, что считать изменением
- ansible.builtin.command: /opt/status.sh
  register: st
  changed_when: false                       # ⭐ задача-проверка ничего не меняет

- ansible.builtin.command: /opt/apply.sh
  register: ap
  changed_when: "'APPLIED' in ap.stdout"    # changed только при реальном применении
```

`changed_when: false` — самый частый приём для приведения плейбука к `changed=0`.

---

## 6. `block` / `rescue` / `always` — try/catch по-ансибловски

```yaml
- name: Деплой с откатом
  block:
    - name: Развернуть новую версию
      ansible.builtin.unarchive:
        src: "app-{{ app_version }}.tar.gz"
        dest: /opt/app/releases/

    - name: Переключить симлинк
      ansible.builtin.file:
        src: "/opt/app/releases/{{ app_version }}"
        dest: /opt/app/current
        state: link

    - name: Проверить здоровье
      ansible.builtin.uri: { url: "http://localhost:8080/health", status_code: 200 }
      retries: 10
      delay: 3
      register: h
      until: h.status == 200

  rescue:
    - name: Откат на предыдущую версию
      ansible.builtin.file:
        src: "/opt/app/releases/{{ previous_version }}"
        dest: /opt/app/current
        state: link

    - name: Сообщить о провале
      ansible.builtin.debug:
        msg: "Деплой {{ app_version }} провален, откатились на {{ previous_version }}"

    - name: Всё равно считать play неуспешным
      ansible.builtin.fail:
        msg: "Deploy failed, rolled back"

  always:
    - name: Убрать временные файлы
      ansible.builtin.file: { path: /tmp/deploy, state: absent }
```

| Секция | Когда выполняется |
|--------|-------------------|
| `block` | Всегда (основная логика) |
| `rescue` | Только если в `block` была ошибка |
| `always` | В любом случае (уборка, уведомления) |

Полезное внутри `rescue`: `ansible_failed_task.name` и `ansible_failed_result`
— что именно упало.

> ⚠️ Если `rescue` отработал без ошибок, play считается **успешным** (`rescued=1`).
> Хочешь всё равно провалить — добавь `fail:` в конце `rescue`.

Общие настройки для блока задаются один раз:
```yaml
- block: [...]
  become: true
  when: app_env == "production"
  tags: [deploy]
```

---

## 7. Явное управление: `fail`, `assert`, `meta`

```yaml
- name: Проверить предусловия
  ansible.builtin.assert:
    that:
      - app_version is defined
      - app_version is match('^\d+\.\d+\.\d+$')
      - ansible_memtotal_mb >= 1024
    fail_msg: "Некорректная версия или мало памяти"
    success_msg: "Предусловия выполнены"

- name: Упасть с понятным сообщением
  ansible.builtin.fail:
    msg: "Окружение {{ app_env }} не поддерживается"
  when: app_env not in ['dev', 'staging', 'production']

- name: Прервать play на этом хосте (остальные продолжат)
  ansible.builtin.meta: end_host
  when: not app_enabled

- name: Прервать play целиком
  ansible.builtin.meta: end_play

- name: Выполнить накопленные handler'ы прямо сейчас
  ansible.builtin.meta: flush_handlers
```

---

## 8. Практичный пример: всё вместе

```yaml
- name: Деплой приложения
  hosts: web
  become: true
  serial: 1
  vars:
    required_packages: [curl, git, python3-pip]

  pre_tasks:
    - name: Проверить входные данные
      ansible.builtin.assert:
        that:
          - app_version is defined
          - app_env in ['staging', 'production']
        fail_msg: "Не задана версия или неизвестное окружение"

  tasks:
    - name: Пакеты (одной транзакцией)
      ansible.builtin.apt:
        name: "{{ required_packages }}"
        state: present
        update_cache: true
        cache_valid_time: 3600

    - name: Дополнительные пакеты для production
      ansible.builtin.apt:
        name: [node-exporter, fail2ban]
        state: present
      when: app_env == "production"

    - name: Конфиги сервисов
      ansible.builtin.template:
        src: "{{ item.src }}"
        dest: "{{ item.dest }}"
        mode: "0644"
      loop:
        - { src: app.conf.j2,  dest: /etc/app/app.conf }
        - { src: logrotate.j2, dest: /etc/logrotate.d/app }
      loop_control:
        label: "{{ item.dest }}"
      notify: restart app

    - name: Деплой с откатом
      block:
        - ansible.builtin.service: { name: app, state: restarted }
        - name: Ждём здоровья
          ansible.builtin.uri: { url: "http://localhost:8080/health", status_code: 200 }
          register: h
          until: h.status == 200
          retries: 10
          delay: 3
          changed_when: false
      rescue:
        - ansible.builtin.debug: { msg: "Упало на: {{ ansible_failed_task.name }}" }
        - ansible.builtin.fail: { msg: "Деплой не прошёл health-check" }

  handlers:
    - name: restart app
      ansible.builtin.service: { name: app, state: restarted }
```

---

## 💼 Как это в DevOps

- `when: ansible_os_family == ...` — то, что делает роль переносимой между дистрибутивами;
  без этого роль «работает только у нас на Ubuntu».
- `until` + `retries` — обязательная часть деплоя: без ожидания готовности пайплайн
  «зелёный», а сервис лежит.
- `changed_when: false` на всех проверках — то, что превращает шумный плейбук
  в идемпотентный.
- `block/rescue` используют для деплоя с откатом: попытка → health-check → откат при провале.
- `loop_control: label` — способ не залить CI-лог гигантскими структурами и не светить секреты.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Условие | `when: ansible_os_family == "Debian"` |
| Несколько условий (И) | список под `when:` |
| ИЛИ | `when: a == 1 or b == 2` |
| Переменная определена | `when: var is defined` |
| Число из строки | `when: port \| int > 1024` |
| Задача упала/прошла | `when: r is failed` / `is succeeded` |
| Условие на группу задач | `block:` + `when:` |
| Цикл по списку | `loop: [a, b, c]` |
| Цикл по словарям | `loop:` со списком `{...}`, обращение `item.key` |
| Цикл по словарю | <code v-pre>loop: "{{ d \| dict2items }}"</code> |
| Красивый вывод цикла | <code v-pre>loop_control: label: "{{ item.name }}"</code> |
| Переименовать `item` | `loop_control: loop_var: my_item` |
| Повторять до успеха | `until:` + `retries:` + `delay:` |
| Игнорировать ошибку | `ignore_errors: true` |
| Своё определение ошибки | `failed_when: ...` |
| Убрать ложный `changed` | `changed_when: false` |
| try/catch | `block` / `rescue` / `always` |
| Упасть осознанно | `fail:` + `when:` |
| Проверить предусловия | `assert:` |
| Закончить play для хоста | `meta: end_host` |

---

## 🧠 Что запомнить

1. В `when` **не нужны** <code v-pre>{{ }}</code>.
2. Список под `when:` — это логическое И; для ИЛИ пишем `or` явно.
3. `when` вместе с `loop` проверяется для каждого элемента отдельно.
4. `loop` заменил `with_items` и компанию; старый синтаксис нужно уметь читать.
5. Для пакетов цикл не нужен — передавай список модулю (быстрее и одной транзакцией).
6. Результаты цикла лежат в `register.results`, у каждого элемента есть `item`.
7. `loop_control.label` укорачивает вывод и прячет лишнее.
8. `until` + `retries` + `delay` — штатное ожидание готовности сервиса.
9. `changed_when: false` — обязательный спутник задач-проверок.
10. `failed_when` переопределяет, что считать ошибкой (классика — `grep` с `rc=1`).
11. `block/rescue/always` = try/catch/finally; после успешного `rescue` play считается успешным.
12. `assert` и `fail` делают ошибки понятными: лучше упасть явно, чем настроить половину.

---

## Задачи

---

### Блок A. Теория

**A1.** ⭐ Почему в `when` не нужны фигурные скобки?

<details><summary>Ответ</summary>

Значение `when` уже интерпретируется как Jinja2-выражение, поэтому обрамление
<code v-pre>{{ }}</code> избыточно и приводит к предупреждениям или некорректному сравнению строк.

</details>

**A2.** Как записать «И» и как «ИЛИ» в условиях?

<details><summary>Ответ</summary>

«И» — список элементов под `when:` (или `and`); «ИЛИ» — только явным `or`.

</details>

**A3.** Как проверить, что переменная определена? А что она непустая?

<details><summary>Ответ</summary>

`when: var is defined`; непустая — `when: var is defined and var | length > 0`
(для строк/списков) или `when: var | default('') != ''`.

</details>

**A4.** Как сравнить переменную как число, если она пришла строкой?

<details><summary>Ответ</summary>

Фильтром `int`: `when: port | int > 1024`.

</details>

**A5.** Что делает `when` вместе с `loop` — проверяется один раз или на каждый элемент?

<details><summary>Ответ</summary>

На каждый элемент отдельно: условие вычисляется для каждой итерации.

</details>

**A6.** Как применить одно условие сразу к десяти задачам?

<details><summary>Ответ</summary>

Обернуть их в `block` и повесить `when` на блок.

</details>

**A7.** Чем `loop` отличается от `with_items`? Нужно ли переписывать старый код?

<details><summary>Ответ</summary>

`loop` — современный синтаксис, `with_items` — устаревший (и «разворачивает»
вложенные списки). Переписывать существующий рабочий код не обязательно, но новый
пишут на `loop`; читать `with_*` нужно уметь.

</details>

**A8.** Зачем нужен `loop_control.label`? Приведи два сценария.

<details><summary>Ответ</summary>

(1) Скрыть большие структуры/секреты из вывода; (2) сделать лог читаемым —
видно имя пользователя/путь вместо всего словаря.

</details>

**A9.** Когда нужен `loop_control.loop_var`?

<details><summary>Ответ</summary>

Когда есть вложенные циклы (`include_tasks` с собственным `loop`) или когда
`item` конфликтует с переменной из внешнего контекста.

</details>

**A10.** Почему для установки пакетов цикл — плохая идея?

<details><summary>Ответ</summary>

Каждая итерация — отдельный вызов менеджера пакетов (медленно, много блокировок).
Модуль умеет принимать список и ставить всё одной транзакцией.

</details>

**A11.** Где лежат результаты задачи, выполненной в цикле?

<details><summary>Ответ</summary>

В `<register>.results` — список, где каждый элемент содержит `item`, `rc`,
`stdout`, `changed` и т.д.

</details>

**A12.** Что делают `until`, `retries`, `delay`? Сколько всего будет попыток?

<details><summary>Ответ</summary>

`until` — условие успеха, `retries` — число повторов, `delay` — пауза между ними.
Всего попыток — `retries` (первая попытка входит в это число).

</details>

**A13.** Чем `until` отличается от `wait_for`?

<details><summary>Ответ</summary>

`until` повторяет **любую** задачу до выполнения условия; `wait_for` — специальный
модуль ожидания порта/файла/строки в файле. Для TCP-порта проще `wait_for`, для HTTP —
`uri` + `until`.

</details>

**A14.** ⭐ Чем отличаются `ignore_errors`, `failed_when` и `changed_when`?

<details><summary>Ответ</summary>

`ignore_errors` — не считать падение фатальным (но задача остаётся `failed`
в отчёте как `ignored`); `failed_when` — переопределяет, что считать ошибкой;
`changed_when` — переопределяет, что считать изменением.

</details>

**A15.** Зачем `changed_when: false` и как это связано с идемпотентностью?

<details><summary>Ответ</summary>

Задачи-проверки ничего не меняют, но `command`/`shell` всегда рапортуют `changed`.
`changed_when: false` убирает этот шум, и повторный прогон честно показывает `changed=0`.

</details>

**A16.** Опиши `block`/`rescue`/`always`. Когда выполняется каждая секция?

<details><summary>Ответ</summary>

`block` — основные задачи; `rescue` — выполняется при ошибке в блоке;
`always` — выполняется всегда (уборка).

</details>

**A17.** Если `rescue` отработал успешно — play считается упавшим или успешным?
Как это изменить?

<details><summary>Ответ</summary>

Успешным (`rescued=N`). Чтобы всё же провалить — добавить `fail:` в конце `rescue`.

</details>

**A18.** Чем `fail` отличается от `assert`?

<details><summary>Ответ</summary>

`fail` — безусловное падение с сообщением (обычно с `when`); `assert` — проверка
списка условий `that:` с `fail_msg`/`success_msg`, читается как набор требований.

</details>

**A19.** Что делают `meta: end_host` и `meta: end_play`?

<details><summary>Ответ</summary>

`end_host` завершает play для текущего хоста (остальные продолжают);
`end_play` завершает play целиком.

</details>

**A20.** Что такое `ansible_failed_task` и где он доступен?

<details><summary>Ответ</summary>

Переменная с описанием упавшей задачи, доступна внутри `rescue`
(вместе с `ansible_failed_result`).

</details>

---

### Блок B. «Что делает задача»

```yaml
# B1
- ansible.builtin.apt: { name: nginx, state: present }
  when: ansible_os_family == "Debian"
```

<details><summary>Ответ</summary>

Ставит nginx только на Debian/Ubuntu, на остальных — skipped.

</details>

```yaml
# B2
- ansible.builtin.debug: { msg: "ok" }
  when:
    - app_env == "production"
    - app_version is defined
```

<details><summary>Ответ</summary>

Выводит сообщение только если окружение production И задана версия.

</details>

```yaml
# B3
- ansible.builtin.user: { name: "{{ item.name }}", groups: "{{ item.groups }}", append: true }
  loop: "{{ users }}"
  loop_control:
    label: "{{ item.name }}"
```

<details><summary>Ответ</summary>

Создаёт пользователей из списка, не затирая их группы; в выводе — только имена.

</details>

```yaml
# B4
- ansible.builtin.uri: { url: "http://localhost:8080/health", status_code: 200 }
  register: h
  until: h.status == 200
  retries: 10
  delay: 6
  changed_when: false
```

<details><summary>Ответ</summary>

Дёргает health-эндпоинт до получения 200, до 10 попыток с паузой 6 с, без ложного changed.

</details>

```yaml
# B5
- ansible.builtin.shell: grep -c ERROR /var/log/app.log
  register: errs
  failed_when: false
  changed_when: false
```

<details><summary>Ответ</summary>

Считает ошибки в логе; не падает, если совпадений нет, и не показывает changed.

</details>

```yaml
# B6
- ansible.builtin.command: /opt/report.sh
  register: rep
  changed_when: "'CHANGED' in rep.stdout"
```

<details><summary>Ответ</summary>

Считает задачу изменившей состояние, только если в выводе есть CHANGED.

</details>

```yaml
# B7
- block:
    - ansible.builtin.command: /opt/migrate.sh
  rescue:
    - ansible.builtin.command: /opt/rollback.sh
  always:
    - ansible.builtin.file: { path: /tmp/lock, state: absent }
```

<details><summary>Ответ</summary>

Миграция с откатом при ошибке и гарантированным снятием lock-файла.

</details>

```yaml
# B8
- ansible.builtin.meta: end_host
  when: ansible_distribution_version is version('20.04', '<')
```

<details><summary>Ответ</summary>

Прекращает выполнение play для хостов со слишком старой версией ОС.

</details>

```yaml
# B9
- ansible.builtin.debug: { msg: "{{ item.key }}={{ item.value }}" }
  loop: "{{ settings | dict2items }}"
```

<details><summary>Ответ</summary>

Перебирает словарь настроек как пары ключ-значение.

</details>

```yaml
# B10
- ansible.builtin.debug: { msg: "{{ hostvars[item].ansible_default_ipv4.address }}" }
  loop: "{{ groups['web'] }}"
```

<details><summary>Ответ</summary>

Выводит IP каждого хоста группы web (требует собранных фактов этих хостов).

</details>

---

### Блок C. Практика

#### C1. 🔑 Кроссплатформенный плейбук

Напиши плейбук, который ставит nginx и на Debian-семействе (`apt`), и на RedHat-семействе
(`dnf`), и выводит понятное сообщение, если ОС неизвестна (`fail`).
Проверь на своём стенде и объясни, как проверить вторую ветку без RHEL-хоста.

<details><summary>Ответ</summary>

Ветвление по `ansible_os_family` + завершающий `fail` в `else`-ветке
(`when: ansible_os_family not in ['Debian','RedHat']`). Проверить вторую ветку без RHEL
можно, временно подменив факт через `-e "ansible_os_family=RedHat"` (задача станет
выбираться, хотя модуль упадёт) или подняв контейнер `rockylinux`.

</details>

#### C2. Условия по фактам

Напиши задачи, которые выполняются:
1. только на хостах с памятью ≥ 2 ГБ;
2. только на хостах группы `web`;
3. только на первом хосте группы (`groups['web'][0]`);
4. только в check mode;
5. только если существует `/opt/app` (через `stat` + `register`).

#### C3. 🔑 Циклы

1. Создай четырёх пользователей списком словарей (имя, группы, shell) с `label` в выводе.
2. Разложи три конфига циклом по списку `{src, dest}`.
3. Создай пять каталогов через `range`.
4. Выведи пары «имя → порт» через `zip`.

#### C4. Цикл vs список

Сравни два варианта установки пяти пакетов:
```yaml
- apt: { name: "{{ item }}", state: present }
  loop: [nginx, git, curl, htop, jq]
# и
- apt: { name: [nginx, git, curl, htop, jq], state: present }
```
Замерь время (`profile_tasks`) и объясни разницу.

<details><summary>Ответ</summary>

Вариант со списком быстрее в разы: один вызов apt вместо пяти, один lock,
один пересчёт зависимостей.

</details>

#### C5. `register` + `loop`

Проверь статус трёх сервисов циклом, собери результаты и выведи отдельным сообщением
только те, что не запущены.

#### C6. `until` — ожидание готовности

1. Останови nginx.
2. Сделай задачу: запустить nginx, затем `uri`-проверка с `until`/`retries`/`delay`.
3. Намеренно оставь сервис выключенным и посмотри, как задача исчерпывает попытки.
4. Зафиксируй, сколько времени заняло и что в `attempts`.

<details><summary>Ответ</summary>

При неудаче задача выполнит `retries` попыток и упадёт с сообщением, где видно
число попыток; в `register` будет `attempts`.

</details>

#### C7. Тихие проверки

Сделай три задачи-проверки (`df`, `systemctl is-active`, `grep` в логе) так,
чтобы плейбук на повторном прогоне показывал `changed=0`. Используй
`changed_when: false` и `failed_when`.

#### C8. 🔑 `block/rescue/always`

Реализуй сценарий:
1. `block`: положить новый конфиг nginx (заведомо битый) и перезапустить сервис;
2. `rescue`: вернуть предыдущий конфиг из бэкапа, перезапустить, вывести сообщение
   с `ansible_failed_task.name`;
3. `always`: удалить временный файл.
Проверь оба пути (с битым конфигом и с рабочим). Посмотри `rescued` в RECAP.

<details><summary>Ответ</summary>

В RECAP появится `rescued=1`, а play останется успешным, если в `rescue` нет `fail`.

</details>

#### C9. `assert` как ворота

Добавь в `pre_tasks` проверку: `app_version` задана и соответствует `^\d+\.\d+\.\d+$`,
`app_env` из списка допустимых, памяти ≥ 1 ГБ. Проверь падение с понятным сообщением.

#### C10. `meta: end_host`

Сделай плейбук, который пропускает хосты со старой версией ОС, но продолжает работу
на остальных. Проверь по RECAP, что остальные хосты отработали.

#### C11. Вложенные циклы (со звёздочкой)

Для каждого пользователя создай три каталога (`logs`, `tmp`, `data`) с правильным владельцем.
Реализуй через `include_tasks` + `loop_control.loop_var` и через `product`.
Сравни читаемость.

<details><summary>Ответ</summary>

Через `product`: <code v-pre>loop: "{{ users | product(['logs','tmp','data']) | list }}"</code>,
обращение `item.0` / `item.1`. Через `include_tasks` читается лучше при сложной логике.

</details>

#### C12. Рефакторинг

Дано:
```yaml
- shell: systemctl is-active nginx
  ignore_errors: true
- shell: systemctl is-active sshd
  ignore_errors: true
- shell: systemctl is-active cron
  ignore_errors: true
```
Перепиши в один цикл с корректной обработкой ошибок и понятным выводом.

<details><summary>Ответ</summary>

Ожидаемый вид:
```yaml
- name: Статус сервисов
  ansible.builtin.command: "systemctl is-active {{ item }}"
  loop: [nginx, sshd, cron]
  register: svc
  changed_when: false
  failed_when: false
  loop_control: { label: "{{ item }}" }

- name: Не запущены
  ansible.builtin.debug: { msg: "НЕ РАБОТАЕТ: {{ item.item }}" }
  loop: "{{ svc.results }}"
  when: item.rc != 0
  loop_control: { label: "{{ item.item }}" }
```

</details>

---

### Блок D. Инциденты

**D1.** <code v-pre>when: {{ app_env }} == "prod"</code> даёт предупреждение/ошибку. Что не так?

<details><summary>Ответ</summary>

Двойные скобки в `when` не нужны — выражение и так вычисляется как Jinja2.

</details>

**D2.** Задача с `when: app_port > 1024` работает не так, как ожидалось. Почему?

<details><summary>Ответ</summary>

Переменная приходит строкой; сравнение строки с числом даёт неожиданный результат.
Нужен `| int`.

</details>

**D3.** `'dict object' has no attribute 'stdout'` в задаче после `register`. Причина?

<details><summary>Ответ</summary>

Задача с `register` была пропущена (`when`, тег, check mode), поэтому в результате
нет `stdout`. Защита: `when: r is not skipped` или `r.stdout | default('')`.

</details>

**D4.** Плейбук показывает `changed` на пяти задачах-проверках при каждом прогоне.
Что добавить?

<details><summary>Ответ</summary>

`changed_when: false` на всех задачах-проверках.

</details>

**D5.** Задача `grep` в логах валит весь плейбук, хотя «ничего не найдено» — это норма.
Как исправить?

<details><summary>Ответ</summary>

`failed_when: false` (или `|| true`), потому что `grep` возвращает `rc=1`,
когда ничего не нашёл.

</details>

**D6.** Цикл по 200 пакетам выполняется 8 минут. Что изменить?

<details><summary>Ответ</summary>

Передать список пакетов модулю одной задачей вместо цикла.

</details>

**D7.** В логе CI видны пароли из `loop` по списку пользователей. Что добавить?

<details><summary>Ответ</summary>

`no_log: true` на задаче и/или `loop_control.label` без чувствительных полей.

</details>

**D8.** После `rescue` пайплайн зелёный, хотя деплой провалился и откатился.
Почему и как исправить?

<details><summary>Ответ</summary>

После успешного `rescue` play считается успешным. Нужно завершать `rescue`
задачей `fail:` — тогда джоба в CI станет красной.

</details>

**D9.** `until` никогда не завершается успехом, хотя сервис поднялся. Что проверить в условии?

<details><summary>Ответ</summary>

Условие `until` ссылается не на то поле (`h.status` vs `h.status_code`),
либо не сброшен `failed_when`/`status_code`, либо проверяется не тот адрес/порт.
Смотреть `register` через `debug`.

</details>

**D10.** Вложенный цикл через два `loop` не работает. Как правильно?

<details><summary>Ответ</summary>

У задачи может быть только один `loop`. Вложенность делают через
`include_tasks` с собственным `loop` и `loop_var`, либо через `product`/`subelements`.

</details>

**D11.** `ignore_errors: true` стоит на задаче установки пакета, и плейбук «успешен»,
хотя приложение не работает. В чём опасность такого подхода?

<details><summary>Ответ</summary>

`ignore_errors` маскирует реальные ошибки: плейбук «успешен», а система
в неконсистентном состоянии. Правильнее — `failed_when` с точным условием,
`block/rescue` или честное падение.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как в Ansible сделать условное выполнение задачи?

<details><summary>Ответ</summary>

Ключом `when` с Jinja-выражением; для группы задач — `block` + `when`.

</details>

**2.** Как организовать цикл? Что такое `loop` и `with_items`?

<details><summary>Ответ</summary>

`loop` (современный) со списком/переменной; `with_items` — устаревший аналог.

</details>

**3.** Как выполнить задачу только на определённой ОС?

<details><summary>Ответ</summary>

`when: ansible_os_family == "Debian"` (или `ansible_distribution`).

</details>

**4.** Что делает `register` и как использовать результат в условии?

<details><summary>Ответ</summary>

`register` сохраняет результат задачи; далее `when: r.rc == 0`, `r is failed`,
`r.stdout is search('...')`.

</details>

**5.** Как дождаться, пока сервис станет доступен?

<details><summary>Ответ</summary>

`uri` + `until`/`retries`/`delay` для HTTP или `wait_for` для порта.

</details>

**6.** Чем отличаются `ignore_errors`, `failed_when`, `changed_when`?

<details><summary>Ответ</summary>

См. ответ на A14.

</details>

**7.** Что такое `block`/`rescue`/`always`?

<details><summary>Ответ</summary>

Аналог try/catch/finally: основная логика, обработка ошибки, гарантированная уборка.

</details>

**8.** Как реализовать откат при неудачном деплое?

<details><summary>Ответ</summary>

`block` с деплоем и health-check, `rescue` с откатом (переключение симлинка/предыдущий
образ) и финальным `fail`, `always` — уборка.

</details>

**9.** Как проверить обязательные параметры перед запуском?

<details><summary>Ответ</summary>

`assert` в `pre_tasks` с перечислением условий и понятным `fail_msg`.

</details>

**10.** Как сделать так, чтобы задача-проверка не отображалась как `changed`?

<details><summary>Ответ</summary>

`changed_when: false`.

</details>

---

### 🎯 Чек-лист

- [ ] Пишу `when` без <code v-pre>{{ }}</code> и знаю про `| int`, `is defined`, `is failed`
- [ ] Применяю условие к группе задач через `block`
- [ ] Свободно пишу `loop` со списками словарей и `loop_control.label`
- [ ] Не делаю цикл там, где модуль принимает список
- [ ] Разбираю `register.results` после цикла
- [ ] Использую `until`/`retries`/`delay` для ожидания готовности
- [ ] Ставлю `changed_when: false` на все проверки
- [ ] Написал деплой с `block`/`rescue`/`always` и проверил оба пути
- [ ] Помню, что после `rescue` play успешен, и добавляю `fail` при необходимости
- [ ] Защищаю плейбук `assert`'ом в `pre_tasks`
