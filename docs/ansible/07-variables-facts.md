---
title: "07. Переменные, приоритеты и facts"
description: "Где объявлять переменные, 22-уровневый порядок приоритетов, facts, register и set_fact, hostvars/groups"
---

# 07. Переменные, их приоритеты и facts

> Роадмап → 5. Ansible → Playbook → **«Переменные и их приоритеты»**, **«facts»**.
> ⭐ Приоритеты переменных — **один из трёх топ-вопросов роадмапа на собесе**.
> **После темы ты умеешь:** объявлять переменные в правильном месте, понимать, какое
> значение победит, и пользоваться фактами хоста.

---

## 🗺️ Карта темы

```text:no-line-numbers
 ОТКУДА берутся переменные                    КУДА применяются
 ┌────────────────────────────────┐          ┌────────────────────────┐
 │ role defaults/   (слабее всех) │          │ в задачах: {{ var }}   │
 │ inventory / group_vars         │          │ в шаблонах .j2         │
 │ host_vars                      │  ──────► │ в условиях when        │
 │ play vars / vars_files         │          │ в циклах loop          │
 │ role vars/                     │          │ в именах задач         │
 │ block/task vars                │          └────────────────────────┘
 │ set_fact / register            │
 │ -e extra vars    (сильнее всех)│
 └────────────────────────────────┘
                  ▲
                  │
        FACTS: собираются с хоста автоматически
        (ansible_distribution, ansible_default_ipv4, ...)
```

---

## 1. Где объявлять переменные

```yaml
# 1) в play
- hosts: web
  vars:
    http_port: 80
    app_name: myapp
  vars_files:
    - vars/common.yml
    - vars/secrets.yml         # возможно, зашифрован vault

# 2) в задаче
  tasks:
    - name: Пример
      ansible.builtin.debug:
        msg: "{{ greeting }}"
      vars:
        greeting: "привет"
```

```yaml
# 3) group_vars/web.yml  (рядом с инвентарём)
http_port: 80
nginx_workers: auto

# 4) host_vars/web1.yml
http_port: 8080

# 5) roles/nginx/defaults/main.yml  — «значения по умолчанию роли» (слабее всех)
nginx_port: 80

# 6) roles/nginx/vars/main.yml      — «внутренние константы роли» (сильные)
nginx_config_path: /etc/nginx/nginx.conf
```

```bash
# 7) при запуске (побеждает всё)
ansible-playbook site.yml -e "app_version=1.2.3"
ansible-playbook site.yml -e @vars/prod.yml
ansible-playbook site.yml -e '{"packages": ["nginx","git"]}'
```

### Имена переменных
```text:no-line-numbers
✅ app_port, nginx_worker_processes, db_host
❌ app-port (дефис), 2app (цифра в начале), app port (пробел)
```
Допустимы буквы, цифры и `_`; нельзя начинать с цифры и использовать зарезервированные
имена (`environment`, `hostvars`, `groups`, `ansible_*` — последние занимает сам Ansible).

> 💡 В ролях принят префикс по имени роли: `nginx_port`, `nginx_user`. Это спасает
> от коллизий, когда в одном play десяток ролей.

---

## 2. Использование переменных

```yaml
- name: Порт приложения — {{ app_port }}        # можно даже в name
  ansible.builtin.debug:
    msg: "{{ app_name }} слушает {{ app_port }}"

- ansible.builtin.template:
    src: app.conf.j2
    dest: "{{ app_dir }}/app.conf"              # ⭐ кавычки обязательны

- ansible.builtin.debug:
    var: app_config                             # вывести структуру целиком
```

```yaml
# вложенные структуры
app:
  name: myapp
  port: 8080
  db:
    host: db1
    port: 5432
```
```yaml
msg: "{{ app.port }}"          # точечная нотация
msg: "{{ app['port'] }}"       # скобочная (обязательна, если в ключе дефис)
msg: "{{ app.db.host }}"
```

### Фильтры (Jinja2) — подробнее в теме 10
```yaml
msg: "{{ app_port | default(8080) }}"           # ⭐ значение по умолчанию
msg: "{{ name | upper }}"
msg: "{{ items | length }}"
msg: "{{ items | join(', ') }}"
msg: "{{ raw | int }}"
msg: "{{ pwd | password_hash('sha512') }}"
msg: "{{ path | basename }}"
msg: "{{ var | default(omit) }}"                # не передавать параметр модулю вообще
```

---

## 3. ⭐⭐ Приоритеты переменных — главный вопрос собеса

**Официальный порядок (от слабого к сильному), 22 уровня:**

```text:no-line-numbers
 1. command line values (-u, -c) — не переменные, но задают поведение
 2. role defaults (roles/x/defaults/main.yml)        ← САМЫЙ СЛАБЫЙ
 3. inventory file / script group vars
 4. inventory group_vars/all
 5. playbook group_vars/all
 6. inventory group_vars/*
 7. playbook group_vars/*
 8. inventory file / script host vars
 9. inventory host_vars/*
10. playbook host_vars/*
11. host facts / cached set_facts
12. play vars
13. play vars_prompt
14. play vars_files
15. role vars (roles/x/vars/main.yml)
16. block vars (для задач внутри block)
17. task vars (для одной задачи)
18. include_vars
19. set_facts / registered vars
20. role (and include_role) params
21. include params
22. extra vars (-e)                                  ← ПОБЕЖДАЕТ ВСЕГДА
```

### Как это запомнить (рабочая версия для собеса)

```text:no-line-numbers
        САМЫЙ СЛАБЫЙ
   role defaults/           ← «рекомендация роли», её и надо переопределять
        ↓
   inventory / group_vars   ← настройки окружения
        ↓
   host_vars                ← настройки конкретного хоста
        ↓
   facts                    ← данные с самого хоста
        ↓
   play vars / vars_files   ← то, что написано в плейбуке
        ↓
   role vars/               ← «константы роли», переопределять не предполагается
        ↓
   block vars → task vars   ← чем ближе к задаче, тем сильнее
        ↓
   include_vars, set_fact, register
        ↓
   role params (roles: - role: x  var: y)
        ↓
   -e extra vars            ← ПОБЕЖДАЕТ ВСЕГДА
        САМЫЙ СИЛЬНЫЙ
```

**Два правила, которые закрывают 90% вопросов:**
1. **Чем ближе к месту использования — тем сильнее.** (defaults роли → … → task vars)
2. **`-e` побеждает всё.** Всегда. Даже `set_fact`.

**Третье правило (про роли), которое отличает сильный ответ:**
> `defaults/main.yml` — самый **низкий** приоритет (его задача — быть переопределённым),
> а `vars/main.yml` — **высокий** (его задача — не быть переопределённым случайно).
> Поэтому всё, что пользователь роли должен настраивать, кладут в `defaults`,
> а внутренние константы — в `vars`.

### Внутри одного уровня: группы

```text:no-line-numbers
group_vars/all.yml           слабее
      ↓
group_vars/<родительская>.yml
      ↓
group_vars/<дочерняя>.yml
      ↓
host_vars/<хост>.yml         сильнее
```
Если хост входит в две группы одного уровня — побеждает та, что **позже по алфавиту**;
изменить можно переменной `ansible_group_priority` (чем больше — тем приоритетнее;
задаётся у группы, не у хоста).

### Проверка на практике
```bash
ansible-inventory --host web1              # что даёт инвентарь
ansible web1 -m debug -a "var=http_port"   # что видно в рантайме
ansible-playbook site.yml -e "http_port=9999"   # проверить, что -e перебивает
```

---

## 4. Facts — данные, собранные с хоста

При старте play Ansible выполняет модуль `setup` и получает сотни переменных о хосте.

```bash
ansible web1 -m setup                                   # всё
ansible web1 -m setup -a "filter=ansible_distribution*"
ansible web1 -m setup -a "gather_subset=network"
```

### Самые используемые факты

| Факт | Пример значения | Зачем |
|------|-----------------|-------|
| `ansible_hostname` | `web1` | Короткое имя хоста |
| `ansible_fqdn` | `web1.example.com` | Полное имя |
| `ansible_distribution` | `Ubuntu` | Ветвление по ОС |
| `ansible_distribution_version` | `22.04` | Проверка версии |
| `ansible_distribution_release` | `jammy` | Кодовое имя (нужно в репозиториях apt) |
| `ansible_os_family` | `Debian` / `RedHat` | ⭐ Главный ключ для `when` |
| `ansible_default_ipv4.address` | `10.0.0.11` | IP основного интерфейса |
| `ansible_all_ipv4_addresses` | `[10.0.0.11, 172.17.0.1]` | Все адреса |
| `ansible_processor_vcpus` | `4` | Расчёт воркеров |
| `ansible_memtotal_mb` | `7947` | Расчёт лимитов памяти |
| `ansible_mounts` | список ФС | Проверка свободного места |
| `ansible_kernel` | `5.15.0-91-generic` | Версия ядра |
| `ansible_architecture` | `x86_64` | Выбор бинарника |
| `ansible_date_time.date` | `2026-09-13` | Метки в именах бэкапов |
| `ansible_env` | словарь env удалённого пользователя | Переменные окружения |
| `ansible_virtualization_type` | `kvm`, `docker` | Понять, где выполняемся |

```yaml
- name: Воркеров nginx = числу ядер
  ansible.builtin.template:
    src: nginx.conf.j2      # внутри: worker_processes {{ ansible_processor_vcpus }};
    dest: /etc/nginx/nginx.conf

- name: Только для Debian-семейства
  ansible.builtin.apt: { name: nginx, state: present }
  when: ansible_os_family == "Debian"
```

### Новый и старый стиль обращения
```jinja
{{ ansible_hostname }}                 # старый стиль (inject), работает по умолчанию
{{ ansible_facts['hostname'] }}        # новый стиль, всегда доступен
{{ ansible_facts.default_ipv4.address }}
```
Инъекцию `ansible_*` можно отключить (`inject_facts_as_vars = False` в `ansible.cfg`) —
тогда остаётся только `ansible_facts[...]`.

### Ускорение: не собирать лишнего
```yaml
- hosts: web
  gather_facts: false          # совсем не собирать (если факты не нужны)

- hosts: web
  gather_facts: true
  gather_subset:
    - "!all"
    - "!min"
    - network                  # собрать только сетевые факты
```
```ini
# ansible.cfg — кэш фактов между прогонами
[defaults]
gathering = smart
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_facts
fact_caching_timeout = 7200
```

### Свои факты (custom facts)
```ini
# на хосте: /etc/ansible/facts.d/app.fact
[general]
version=1.2.3
role=frontend
```
```jinja
{{ ansible_local.app.general.version }}     # → 1.2.3
```

---

## 5. `register` — результат задачи как переменная

```yaml
- name: Проверить наличие конфига
  ansible.builtin.stat:
    path: /etc/app/app.conf
  register: cfg

- name: Показать результат
  ansible.builtin.debug:
    var: cfg

- name: Действовать по результату
  ansible.builtin.template:
    src: app.conf.j2
    dest: /etc/app/app.conf
  when: not cfg.stat.exists
```

Типовые поля результата:

| Поле | Смысл |
|------|-------|
| `rc` | Код возврата команды |
| `stdout` / `stderr` | Вывод (строкой) |
| `stdout_lines` | Вывод построчно (списком) ⭐ |
| `changed` | Было ли изменение |
| `failed` | Упала ли задача |
| `skipped` | Была ли пропущена |
| `results` | Список результатов, если была `loop` ⭐ |
| `msg` | Сообщение модуля |
| `attempts` | Сколько попыток заняло (`until`) |

```yaml
- name: Версия приложения
  ansible.builtin.command: /opt/app/bin/app --version
  register: ver
  changed_when: false          # ⭐ это чтение, а не изменение

- ansible.builtin.debug:
    msg: "Версия: {{ ver.stdout }}"
```

> ⚠️ Если задача пропущена по `when`, в `register` всё равно попадёт объект,
> но без `stdout` — обращение к полю упадёт. Защита: `when: ver is not skipped`
> или `ver.stdout | default('')`.

---

## 6. `set_fact` — вычислить переменную на лету

```yaml
- name: Собрать имя образа
  ansible.builtin.set_fact:
    image_full: "{{ registry }}/{{ app_name }}:{{ app_version }}"

- name: Вычислить размер пула
  ansible.builtin.set_fact:
    pool_size: "{{ (ansible_processor_vcpus | int) * 2 }}"
    cacheable: true            # сохранить в кэш фактов между прогонами
```
`set_fact` имеет очень высокий приоритет (выше play vars) и действует на **тот хост**,
где выполнен, до конца прогона.

---

## 7. Переменные других хостов: `hostvars`, `groups`

```yaml
- name: IP сервера БД в конфиге приложения
  ansible.builtin.debug:
    msg: "{{ hostvars['db1']['ansible_default_ipv4']['address'] }}"

- name: Все веб-хосты в конфиг балансировщика
  ansible.builtin.debug:
    msg: "{{ groups['web'] }}"

- name: Цикл по хостам группы с их IP
  ansible.builtin.debug:
    msg: "{{ item }} -> {{ hostvars[item].ansible_default_ipv4.address }}"
  loop: "{{ groups['web'] }}"
```

| Магическая переменная | Что даёт |
|-----------------------|----------|
| `inventory_hostname` | Имя текущего хоста **как в инвентаре** ⭐ |
| `inventory_hostname_short` | До первой точки |
| `ansible_host` | Адрес подключения |
| `groups` | Словарь: группа → список хостов |
| `group_names` | Список групп текущего хоста |
| `hostvars` | Переменные и факты всех хостов |
| `play_hosts` / `ansible_play_hosts` | Хосты текущего play (живые) |
| `ansible_play_batch` | Хосты текущей «волны» (`serial`) |
| `inventory_dir` | Каталог инвентаря |
| `playbook_dir` | Каталог плейбука |
| `role_path` | Путь текущей роли |
| `ansible_check_mode` | `true`, если запущено с `--check` |
| `ansible_version` | Версия Ansible |

> ⚠️ `hostvars['db1'].ansible_default_ipv4` доступен, только если факты с `db1`
> **уже собраны** в этом прогоне. Если `db1` не входит в play — добавь отдельный play
> с `gather_facts` или используй `delegate_to`/кэш фактов.

---

## 8. Отладка переменных

```bash
ansible-inventory --host web1                       # переменные инвентаря
ansible web1 -m debug -a "var=hostvars[inventory_hostname]" | less   # ВСЁ про хост
ansible web1 -m debug -a "var=app_port"
ansible-playbook site.yml -e "app_port=9999" -vvv   # откуда что приехало
```
```yaml
- name: Где определена переменная (отладка)
  ansible.builtin.debug:
    msg:
      - "app_port = {{ app_port | default('НЕ ОПРЕДЕЛЕНА') }}"
      - "группы хоста: {{ group_names }}"
      - "check mode: {{ ansible_check_mode }}"

- name: Жёсткая проверка обязательных переменных
  ansible.builtin.assert:
    that:
      - app_version is defined
      - app_port | int > 0
    fail_msg: "Не заданы обязательные переменные деплоя"
```

Частые ошибки:

| Ошибка | Причина |
|--------|---------|
| `'app_port' is undefined` | Переменная не определена на этом уровне/хосте → `default()` или `assert` |
| Значение «не то, что ожидал» | Перебито более приоритетным источником → смотри §3 |
| `dict object has no attribute 'stdout'` | Задача была пропущена/в check mode → `default('')` |
| Переменная в `when` не подставляется | В `when` **не нужны** <code v-pre>{{ }}</code> |
| Строка вместо числа | <code v-pre>"{{ x }}"</code> всегда строка → `\| int` |
| Переменная в `group_vars` не видна | Имя файла ≠ имя группы, либо каталог не рядом с инвентарём |

---

## 💼 Как это в DevOps

- Приоритеты переменных — то, из-за чего реально теряют часы: «почему на проде порт 80,
  хотя в `host_vars` стоит 8080». Умение быстро пройти цепочку приоритетов — рабочий навык.
- Каноническая раскладка: **всё настраиваемое — в `defaults` роли**, окружение —
  в `group_vars/<env>`, исключения — в `host_vars`, динамика (версия релиза) — через `-e`
  из CI.
- Факты используют для универсальности ролей: одна роль работает и на Ubuntu, и на Rocky
  благодаря `ansible_os_family`.
- Кэш фактов заметно ускоряет большие прогоны, где факты нужны только части play.
- `no_log: true` + vault — обязательная пара для переменных с секретами (тема 12).

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Значение по умолчанию | <code v-pre>{{ var \| default('x') }}</code> |
| Не передавать параметр модулю | <code v-pre>{{ var \| default(omit) }}</code> |
| Переменная из CLI | `-e "key=value"` (высший приоритет) |
| Переменные из файла | `-e @vars/prod.yml` или `vars_files:` |
| Настройки роли | `roles/<role>/defaults/main.yml` |
| Константы роли | `roles/<role>/vars/main.yml` |
| Переменная окружения (env) | `group_vars/<env>.yml` |
| Переменная одного хоста | `host_vars/<host>.yml` |
| Вычислить на лету | `set_fact` |
| Сохранить результат задачи | `register` |
| Посмотреть факты | `ansible <host> -m setup` |
| Все переменные хоста | `ansible <host> -m debug -a "var=hostvars[inventory_hostname]"` |
| IP другого хоста | `hostvars['db1'].ansible_default_ipv4.address` |
| Список хостов группы | `groups['web']` |
| Имя текущего хоста | `inventory_hostname` |
| Проверить обязательные переменные | `assert` |
| Ускорить сбор фактов | `gather_facts: false` / `gather_subset` / кэш |

---

## 🧠 Что запомнить

1. ⭐ Порядок приоритетов: **role defaults → inventory/group_vars → host_vars → facts →
   play vars → role vars → block/task vars → set_fact/register → role params → `-e`**.
2. Два правила: «чем ближе к задаче — тем сильнее» и «`-e` побеждает всегда».
3. `defaults/main.yml` — слабейший уровень (его и переопределяют), `vars/main.yml` —
   сильный (внутренние константы роли).
4. Внутри групп: `all` → родительская → дочерняя → `host_vars`; ничья решается алфавитом
   или `ansible_group_priority`.
5. Facts — автоматически собранные данные хоста; ключевые: `ansible_os_family`,
   `ansible_default_ipv4.address`, `ansible_processor_vcpus`, `ansible_distribution*`.
6. `gather_facts: false`, `gather_subset` и кэш фактов — способы ускорить прогон.
7. `register` сохраняет результат задачи (`rc`, `stdout`, `stdout_lines`, `results`, `changed`).
8. `set_fact` вычисляет переменную в рантайме и имеет очень высокий приоритет.
9. `hostvars`, `groups`, `inventory_hostname` — доступ к данным других хостов и групп.
10. В `when` фигурные скобки <code v-pre>{{ }}</code> не нужны; в путях и значениях — обязательны кавычки.
11. `| default()` и `assert` — защита от `undefined variable` в проде.
12. Отладка: `ansible-inventory --host`, `debug var=`, `-vvv`.

---

## Задачи

> ⭐ Блок E этой темы — один из трёх топ-вопросов роадмапа. Проговори ответы вслух.

---

### Блок A. Теория

**A1.** Перечисли все места, где можно объявить переменную (минимум восемь).

<details><summary>Ответ</summary>

`roles/*/defaults/main.yml`, инвентарь (`[группа:vars]`), `group_vars/`, `host_vars/`,
play `vars`, `vars_prompt`, `vars_files`, `roles/*/vars/main.yml`, `block`/`task vars`,
`include_vars`, `set_fact`, `register`, параметры роли, `-e` (extra vars), а также факты.

</details>

**A2.** ⭐⭐ Расставь по приоритету от слабого к сильному: `host_vars`, `-e`, role `defaults`,
play `vars`, `set_fact`, role `vars`, `group_vars`, task `vars`.

<details><summary>Ответ</summary>

role `defaults` → `group_vars` → `host_vars` → play `vars` → role `vars` →
task `vars` → `set_fact` → `-e`.

</details>

**A3.** ⭐ Почему `defaults/main.yml` роли слабее, чем `vars/main.yml`? В чём смысл такого решения?

<details><summary>Ответ</summary>

`defaults` — «предложение по умолчанию», рассчитанное на переопределение
пользователем роли (через `group_vars`, play vars, параметры роли). `vars` — внутренние
константы роли, которые не должны случайно перебиваться инвентарём. Отсюда и разный приоритет.

</details>

**A4.** Какой уровень побеждает всегда, что бы ни было объявлено в других местах?

<details><summary>Ответ</summary>

Extra vars (`-e`).

</details>

**A5.** Что сильнее: `group_vars/all.yml` или `group_vars/web.yml`? А `host_vars/web1.yml`?

<details><summary>Ответ</summary>

`group_vars/web.yml` сильнее `group_vars/all.yml`; `host_vars/web1.yml` сильнее обоих.

</details>

**A6.** Хост входит в две группы одного уровня с одинаковой переменной. Какое значение
победит и как это изменить?

<details><summary>Ответ</summary>

Побеждает группа, которая позже по алфавиту. Управляется `ansible_group_priority`
(больше = приоритетнее), задаётся в переменных группы.

</details>

**A7.** Что такое facts и как они собираются?

<details><summary>Ответ</summary>

Данные о хосте, которые Ansible собирает модулем `setup` в начале play:
ОС, сеть, железо, ФС, окружение.

</details>

**A8.** Назови пять самых полезных фактов и объясни, зачем каждый.

<details><summary>Ответ</summary>

`ansible_os_family` (ветвление apt/dnf), `ansible_default_ipv4.address`
(адрес для конфигов), `ansible_processor_vcpus` (расчёт воркеров),
`ansible_memtotal_mb` (лимиты памяти), `ansible_distribution_release`
(кодовое имя для apt-репозиториев).

</details>

**A9.** Чем `ansible_os_family` отличается от `ansible_distribution`?

<details><summary>Ответ</summary>

`ansible_distribution` — конкретный дистрибутив (`Ubuntu`, `Rocky`), `ansible_os_family` —
семейство (`Debian`, `RedHat`). Для выбора пакетного менеджера нужен именно `os_family`.

</details>

**A10.** Как ускорить прогон, если факты почти не нужны? Три способа.

<details><summary>Ответ</summary>

`gather_facts: false`; `gather_subset` с нужным подмножеством; кэш фактов
(`fact_caching = jsonfile/redis`) + `gathering = smart`.

</details>

**A11.** Что такое кэш фактов и когда он оправдан?

<details><summary>Ответ</summary>

Хранилище собранных фактов между прогонами. Оправдан на больших парках и когда
плейбуки часто обращаются к фактам хостов, не входящих в текущий play.

</details>

**A12.** Что такое custom facts и где они лежат на хосте?

<details><summary>Ответ</summary>

Собственные факты хоста: файлы `*.fact` (INI или JSON) в `/etc/ansible/facts.d/`,
доступны как `ansible_local.<файл>.<секция>.<ключ>`.

</details>

**A13.** Что делает `register` и какие поля обычно есть в результате?

<details><summary>Ответ</summary>

Сохраняет результат задачи в переменную. Типовые поля: `rc`, `stdout`,
`stdout_lines`, `stderr`, `changed`, `failed`, `skipped`, `msg`, `results` (при `loop`),
`attempts` (при `until`).

</details>

**A14.** Чем `set_fact` отличается от `vars`? Какой у него приоритет?

<details><summary>Ответ</summary>

`set_fact` вычисляет переменную в момент выполнения задачи и привязывает её
к хосту до конца прогона; приоритет очень высокий (выше play vars, но ниже `-e`).
`vars` — статическое объявление.

</details>

**A15.** Что такое `hostvars` и `groups`? Приведи пример использования.

<details><summary>Ответ</summary>

`hostvars` — словарь переменных и фактов всех хостов; `groups` — словарь
«группа → список хостов». Пример: сгенерировать upstream-блок nginx из `groups['web']`
и их IP через `hostvars`.

</details>

**A16.** Чем `inventory_hostname` отличается от `ansible_hostname`?

<details><summary>Ответ</summary>

`inventory_hostname` — имя хоста, как он записан в инвентаре (алиас);
`ansible_hostname` — реальное короткое имя хоста, полученное из фактов.

</details>

**A17.** Зачем нужен фильтр `default(omit)`?

<details><summary>Ответ</summary>

`omit` убирает параметр из вызова модуля целиком: модуль применит собственное
значение по умолчанию вместо получения `None`/пустой строки.

</details>

**A18.** Почему в `when` не нужны фигурные скобки?

<details><summary>Ответ</summary>

`when` — это уже Jinja-выражение: скобки добавлять не нужно (и они приводят
к предупреждениям/ошибкам).

</details>

**A19.** Как проверить, что обязательные переменные заданы, до начала работы?

<details><summary>Ответ</summary>

Модулем `assert` в `pre_tasks` (или в начале роли) с понятным `fail_msg`.

</details>

**A20.** Как посмотреть **все** переменные, доступные конкретному хосту?

<details><summary>Ответ</summary>

`ansible <host> -m debug -a "var=hostvars[inventory_hostname]"`
(и `ansible-inventory --host <host>` для переменных инвентаря).

</details>

---

### Блок B. «Какое значение победит»

Для каждого случая ответь: чему равна переменная и почему.

```yaml
# B1
# roles/app/defaults/main.yml:  app_port: 8080
# group_vars/web.yml:           app_port: 80
# запуск: ansible-playbook site.yml
```

<details><summary>Ответ</summary>

`80` — `group_vars` сильнее role `defaults`.

</details>

```yaml
# B2
# group_vars/web.yml:   app_port: 80
# host_vars/web1.yml:   app_port: 8080
# вопрос про хост web1
```

<details><summary>Ответ</summary>

`8080` — `host_vars` сильнее `group_vars`.

</details>

```yaml
# B3
# host_vars/web1.yml:   app_port: 8080
# запуск: ansible-playbook site.yml -e "app_port=9999"
```

<details><summary>Ответ</summary>

`9999` — extra vars побеждают всё.

</details>

```yaml
# B4
# roles/app/defaults/main.yml: app_port: 8080
# roles/app/vars/main.yml:     app_port: 3000
```

<details><summary>Ответ</summary>

`3000` — role `vars` сильнее role `defaults`.

</details>

```yaml
# B5
- hosts: web
  vars:
    app_port: 80
  tasks:
    - ansible.builtin.debug: { var: app_port }
      vars:
        app_port: 8080
```

<details><summary>Ответ</summary>

`8080` — task vars сильнее play vars.

</details>

```yaml
# B6
- hosts: web
  vars:
    app_port: 80
  tasks:
    - ansible.builtin.set_fact:
        app_port: 9090
    - ansible.builtin.debug: { var: app_port }
```

<details><summary>Ответ</summary>

`9090` — `set_fact` сильнее play vars.

</details>

```yaml
# B7
- hosts: web
  roles:
    - role: app
      app_port: 7070
# roles/app/defaults/main.yml: app_port: 8080
# group_vars/web.yml:          app_port: 80
```

<details><summary>Ответ</summary>

`7070` — параметры роли (role params) сильнее и `defaults`, и `group_vars`.

</details>

```yaml
# B8
# group_vars/all.yml:         log_level: info
# group_vars/production.yml:  log_level: warning     (production — родитель web)
# group_vars/web.yml:         log_level: debug
# вопрос про хост из группы web
```

<details><summary>Ответ</summary>

`debug` — дочерняя группа (`web`) сильнее родительской (`production`) и `all`.

</details>

---

### Блок C. Практика

#### C1. 🔑 Эксперимент с приоритетами (делай руками — так запоминается)

1. Создай роль `demo` с `defaults/main.yml`: `test_var: "from_defaults"`.
2. Добавь `group_vars/web.yml`: `test_var: "from_group_vars"`.
3. Добавь `host_vars/web1.yml`: `test_var: "from_host_vars"`.
4. Добавь в play `vars`: `test_var: "from_play"`.
5. Добавь `roles/demo/vars/main.yml`: `test_var: "from_role_vars"`.
6. Добавь `set_fact` в задаче.
7. Запусти с `-e "test_var=from_cli"`.
После **каждого** шага запускай плейбук с `debug` и записывай, что победило.
Составь итоговую таблицу — это твой ответ на собесе.

<details><summary>Ответ</summary>

Ожидаемая итоговая таблица (что побеждает на каждом шаге):
defaults → group_vars → host_vars → play vars → role vars → set_fact → extra vars.

</details>

#### C2. Группы и приоритет

Помести `web1` в группы `web` и `canary` с разными значениями одной переменной.
Проверь результат, затем добавь `ansible_group_priority: 10` в `group_vars/canary.yml`
и проверь снова.

<details><summary>Ответ</summary>

Без приоритета побеждает `web` (позже по алфавиту, чем `canary`);
с `ansible_group_priority: 10` у `canary` — побеждает `canary`.

</details>

#### C3. Facts: инвентаризация

Собери в таблицу для всех хостов: ОС и версию, ядро, память, число CPU, IP, архитектуру,
тип виртуализации. Используй `debug` с несколькими фактами в одном сообщении.

#### C4. Факты в шаблоне

Сделай `nginx.conf.j2`, где `worker_processes` = числу ядер, а `worker_connections`
вычисляется как `ansible_memtotal_mb / 4`. Примени и проверь результат на хостах
с разными ресурсами.

#### C5. `gather_facts` и скорость

```bash
time ansible-playbook facts.yml                     # gather_facts: true
time ansible-playbook facts.yml                     # gather_facts: false
```
Затем включи кэш фактов (`jsonfile`) и замерь второй прогон. Объясни разницу.

<details><summary>Ответ</summary>

`gather_facts: false` убирает шаг Gathering Facts целиком; кэш фактов даёт эффект
со второго прогона (факты берутся из файла, а не с хоста).

</details>

#### C6. `register` на практике

1. Задача `command: df -h /` с `register: disk` и `changed_when: false`.
2. Выведи `disk.stdout_lines`.
3. Сделай `when`, который падает, если занято больше 80% (подсказка: `stat`/`command` +
   разбор строки, либо факт `ansible_mounts`).

<details><summary>Ответ</summary>

Через факт: `ansible_mounts | selectattr('mount','equalto','/') | first`
и сравнение `size_available / size_total`; либо разбор вывода `df`. Факт надёжнее.

</details>

#### C7. `register` + `loop`

Сделай цикл по трём пакетам с `register: results` и выведи `results.results | map(attribute='item') | list`.
Посмотри структуру результата целиком через `debug: var=results`.

<details><summary>Ответ</summary>

При `loop` результат — словарь с ключом `results`, где каждый элемент содержит
свой `item`, `changed`, `rc` и т.д.

</details>

#### C8. `set_fact`

Собери переменную `image_full` из `registry`, `app_name`, `app_version` и выведи её.
Затем добавь `cacheable: true` и посмотри, что появилось в кэше фактов.

#### C9. `hostvars` и `groups`

1. Выведи IP всех хостов группы `web` в одном сообщении.
2. В шаблоне `upstream.conf.j2` сгенерируй upstream-блок nginx со всеми web-хостами.
3. Убедись, что при отсутствии фактов у части хостов шаблон падает — и почини
   (отдельный play со сбором фактов или `gather_facts` на `all`).

<details><summary>Ответ</summary>

Если хост не участвует в play, его фактов нет. Решения: отдельный play
`hosts: all` с `gather_facts: true` перед основным, кэш фактов или `delegate_facts`.

</details>

#### C10. Защита от undefined

1. Используй необъявленную переменную — получи ошибку.
2. Добавь `| default('значение')`.
3. Добавь `assert` в `pre_tasks`, который падает с понятным сообщением.
4. Попробуй `| default(omit)` в параметре модуля и объясни разницу.

<details><summary>Ответ</summary>

`default('x')` подставляет значение; `default(omit)` убирает параметр из вызова
модуля — это разные вещи: первый задаёт значение, второй возвращает поведение «по умолчанию
для модуля».

</details>

#### C11. Отладка «почему не то значение»

Специально создай конфликт: переменная задана в `group_vars`, `host_vars` и `set_fact`.
Пройди цепочку диагностики: `ansible-inventory --host`, `debug var=`, `-vvv`.
Опиши алгоритм своими словами.

<details><summary>Ответ</summary>

Алгоритм: (1) `ansible-inventory --host` — что даёт инвентарь;
(2) `debug var=` в нужном месте плейбука — что видно в рантайме; (3) пройти список
приоритетов сверху вниз и найти самый сильный источник; (4) проверить `-e`,
`set_fact` и параметры роли.

</details>

#### C12. Custom facts (со звёздочкой)

Положи на хост `/etc/ansible/facts.d/app.fact` с секцией и парой значений.
Прочитай через `ansible_local.app.*` и используй в `when`.

---

### Блок D. Инциденты

**D1.** `The task includes an option with an undefined variable: 'app_version' is undefined`.
Три способа решения (и какой правильный для прода).

<details><summary>Ответ</summary>

(1) `| default('значение')`; (2) объявить в `defaults`/`group_vars`;
(3) `assert` с понятной ошибкой. Для прода правильно: обязательные переменные — `assert`
(лучше упасть сразу и явно), настраиваемые — `defaults` + `default()`.

</details>

**D2.** В `host_vars/web1.yml` стоит `app_port: 8080`, а применяется 80. Алгоритм разбора.

<details><summary>Ответ</summary>

`ansible-inventory --host web1` → если 8080, значит перебивают play vars,
role vars, `set_fact`, role params или `-e`; если 80 — файл `host_vars` лежит не рядом
с используемым инвентарём либо назван неверно.

</details>

**D3.** Роль перестала работать после того, как значение переехало из `defaults/` в `vars/`.
Почему пользователи роли больше не могут её настроить?

<details><summary>Ответ</summary>

`vars/` имеет высокий приоритет: значения из `group_vars`/play vars больше
не перебивают роль. Настраиваемые параметры должны жить в `defaults/`.

</details>

**D4.** Задача упала: `dict object has no attribute 'stdout'`. Что произошло?

<details><summary>Ответ</summary>

Задача, на которую ссылается `register`, была пропущена (`when`, check mode, тег),
поэтому в результате нет `stdout`. Лечение: `when: r is not skipped`, `r.stdout | default('')`,
`check_mode: false`.

</details>

**D5.** В `when: app_port > 1024` условие ведёт себя странно. Почему и как чинить?

<details><summary>Ответ</summary>

Значение переменной приходит строкой, а сравнение идёт со строкой/числом.
Нужно `when: app_port | int > 1024`.

</details>

**D6.** Плейбук работает на Ubuntu и падает на Rocky Linux. Как сделать роль универсальной?

<details><summary>Ответ</summary>

Ветвления по фактам: `when: ansible_os_family == "Debian"` / `"RedHat"`,
переменные пакетов через <code v-pre>vars/{{ ansible_os_family }}.yml</code> и `include_vars`,
модуль `package` там, где имена совпадают.

</details>

**D7.** Прогон на 200 хостах занимает 15 минут, из которых 6 — Gathering Facts. Что делать?

<details><summary>Ответ</summary>

Кэш фактов (`jsonfile`/`redis`) + `gathering = smart`, `gather_subset` только
нужных подмножеств, `gather_facts: false` в play, где факты не нужны, увеличить `forks`.

</details>

**D8.** В шаблоне используется `hostvars['db1'].ansible_default_ipv4.address`, и он падает
с `undefined`. Причина и два решения.

<details><summary>Ответ</summary>

Факты `db1` не собраны в текущем прогоне. Решения: отдельный play на `all`
со сбором фактов до основного, либо кэш фактов; в крайнем случае — задать нужные значения
явно в `group_vars`.

</details>

**D9.** Пароль из переменной засветился в выводе плейбука в CI. Что добавить?

<details><summary>Ответ</summary>

`no_log: true` на задаче (и не выводить секрет `debug`'ом); плюс хранение
секрета в vault.

</details>

**D10.** После добавления `-e @vars/prod.yml` перестали работать переопределения
в `host_vars`. Объясни почему.

<details><summary>Ответ</summary>

Файл, переданный через `-e @file.yml`, — это extra vars: он сильнее `host_vars`
и вообще всего. Переменные окружения так подключать не стоит — им место в `group_vars`.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐⭐ Расскажи про приоритеты переменных в Ansible. (топ-3 вопрос роадмапа)

<details><summary>Ответ</summary>

От слабого к сильному: role defaults → переменные инвентаря и `group_vars`
(all → родительские → дочерние) → `host_vars` → facts → play vars/vars_prompt/vars_files →
role vars → block vars → task vars → include_vars → set_fact/register → параметры роли →
extra vars (`-e`). Правило: чем ближе к задаче, тем выше приоритет; `-e` побеждает всегда.

</details>

**2.** Где можно объявлять переменные?

<details><summary>Ответ</summary>

См. ответ на A1.

</details>

**3.** Что приоритетнее: `group_vars` или `host_vars`?

<details><summary>Ответ</summary>

`host_vars`.

</details>

**4.** Чем `defaults` отличается от `vars` в роли?

<details><summary>Ответ</summary>

`defaults` — низший приоритет, предназначены для переопределения пользователем роли;
`vars` — высокий приоритет, внутренние константы роли.

</details>

**5.** Что такое extra vars и какой у них приоритет?

<details><summary>Ответ</summary>

Переменные, переданные при запуске (`-e`), максимальный приоритет.

</details>

**6.** Что такое facts? Как их собрать и как отключить сбор?

<details><summary>Ответ</summary>

Данные о хосте, собираемые модулем `setup`; отключаются `gather_facts: false`,
собрать вручную — задачей `setup` или ad-hoc.

</details>

**7.** Что делает `set_fact` и чем отличается от `register`?

<details><summary>Ответ</summary>

`set_fact` создаёт переменную из выражения в рантайме; `register` сохраняет результат
выполнения конкретной задачи.

</details>

**8.** Как получить переменную другого хоста?

<details><summary>Ответ</summary>

Через `hostvars['имя_хоста']['переменная']` (факты должны быть собраны или закэшированы).

</details>

**9.** Как задать значение по умолчанию для переменной?

<details><summary>Ответ</summary>

Фильтром `default()`; для обязательных — `assert`.

</details>

**10.** Как ускорить сбор фактов?

<details><summary>Ответ</summary>

Кэш фактов, `gather_subset`, `gather_facts: false`, больше `forks`, `pipelining`.

</details>

---

### 🎯 Чек-лист

- [ ] ⭐ Могу перечислить приоритеты переменных вслух, без подсказки
- [ ] Проверил приоритеты экспериментом C1 и записал результат
- [ ] Понимаю разницу `defaults/` и `vars/` в роли и когда что использовать
- [ ] Знаю, что `-e` побеждает всегда
- [ ] Умею пользоваться фактами и знаю топ-5 из них
- [ ] Ускорял прогон через `gather_facts: false` / `gather_subset` / кэш
- [ ] Использую `register` и понимаю структуру результата (включая `results` при `loop`)
- [ ] Применял `set_fact` и знаю его приоритет
- [ ] Получал данные другого хоста через `hostvars`/`groups`
- [ ] Защищаю плейбук `default()` и `assert`
