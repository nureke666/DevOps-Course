---
title: "10. Template'ы: Jinja2 и модуль template"
description: "Синтаксис Jinja2, условия и циклы в шаблонах, фильтры, управление пробелами, отладка"
---

# 10. Template'ы: Jinja2 и модуль `template`

> Роадмап → 5. Ansible → Playbook → **«Template'ы (Jinja2) — модуль `template` + файлы `.j2`»**.
> **После темы ты умеешь:** генерировать конфиги под каждый хост из одного шаблона —
> именно это делает Ansible инструментом управления конфигурацией, а не «раскладчиком файлов».

---

## 🗺️ Как это работает

```text:no-line-numbers
  templates/nginx.conf.j2          переменные и факты
 ┌─────────────────────────┐      ┌──────────────────────┐
 │ worker_processes        │      │ ansible_processor_   │
 │   {{ workers }};        │  +   │   vcpus = 4          │
 │ server_name {{ domain }}│      │ domain = example.com │
 └───────────┬─────────────┘      └──────────┬───────────┘
             └───────────► Jinja2 ◄──────────┘
                             │
                             ▼  (рендер НА УПРАВЛЯЮЩЕЙ машине)
                  /etc/nginx/nginx.conf на КАЖДОМ хосте
                  (у каждого — свои значения)
```

```yaml
- name: Конфиг nginx
  ansible.builtin.template:
    src: templates/nginx.conf.j2      # .j2 — на control node
    dest: /etc/nginx/nginx.conf       # результат — на целевом хосте
    owner: root
    group: root
    mode: "0644"
    backup: true
    validate: "nginx -t -c %s"        # ⭐ проверить до подмены
  notify: reload nginx
```

---

## 1. Синтаксис Jinja2 — три конструкции

```jinja
{{ выражение }}      подставить значение
{% инструкция %}     логика: if, for, set
{# комментарий #}    не попадёт в результат
```

```jinja
# {{ ansible_managed }}     ← спецпеременная: "Ansible managed" + предупреждение
server {
    listen {{ http_port }};
    server_name {{ domain }};
    root {{ app_dir }}/public;
}
```

> 💡 <code v-pre>{{ ansible_managed }}</code> в первой строке каждого шаблона — хорошая практика:
> человек, открывший конфиг на сервере, сразу понимает, что править его руками бесполезно.
> Настраивается в `ansible.cfg`: `ansible_managed = Managed by Ansible, do not edit ({file})`.

---

## 2. Условия и циклы в шаблоне

```jinja
{% if app_env == "production" %}
    access_log /var/log/nginx/access.log combined;
    error_log  /var/log/nginx/error.log warn;
{% elif app_env == "staging" %}
    error_log  /var/log/nginx/error.log info;
{% else %}
    access_log off;
    error_log  /var/log/nginx/error.log debug;
{% endif %}

{% if ssl_enabled | default(false) %}
    listen 443 ssl http2;
    ssl_certificate     {{ ssl_cert }};
    ssl_certificate_key {{ ssl_key }};
{% endif %}
```

```jinja
{# upstream из всех хостов группы web #}
upstream backend {
{% for host in groups['web'] %}
    server {{ hostvars[host].ansible_default_ipv4.address }}:{{ app_port }}{% if host == inventory_hostname %} # это я{% endif %};
{% endfor %}
}

{# цикл по списку словарей #}
{% for vhost in vhosts %}
server {
    server_name {{ vhost.name }};
    root {{ vhost.root }};
}
{% endfor %}

{# цикл по словарю #}
{% for key, value in app_settings.items() %}
{{ key }}={{ value }}
{% endfor %}
```

Переменные цикла:
```jinja
{% for h in groups['web'] %}
server {{ h }};     {# {{ loop.index }} — с 1, {{ loop.index0 }} — с 0 #}
{% if loop.first %}# первый{% endif %}
{% if loop.last %}# последний{% endif %}
{% endfor %}
{# всего: {{ groups['web'] | length }} #}
```

---

## 3. Управление пробелами (частая боль)

По умолчанию `{% ... %}` оставляет после себя пустую строку.

```jinja
{%- if x %}     {# минус слева — убрать пробелы/перенос ДО блока #}
{% if x -%}     {# минус справа — убрать ПОСЛЕ блока #}
{%- for i in l -%} ... {%- endfor -%}
```

```yaml
# либо настройками модуля
- ansible.builtin.template:
    src: app.conf.j2
    dest: /etc/app.conf
    trim_blocks: true       # (по умолчанию true) убирать перенос после тега
    lstrip_blocks: false    # убирать пробелы слева от тега — часто удобно включить
```

---

## 4. Фильтры — то, чем шаблон отличается от «просто подстановки»

### Значения по умолчанию и проверки
```jinja
{{ app_port | default(8080) }}
{{ app_name | default('myapp', true) }}    {# true: заменять и пустую строку #}
{{ required_var | mandatory }}             {# упасть, если не задана #}
```

### Строки
```jinja
{{ name | upper }} {{ name | lower }} {{ name | capitalize }}
{{ text | trim }} {{ text | replace('a', 'b') }}
{{ path | basename }} {{ path | dirname }}
{{ s | regex_replace('^v', '') }}
{{ s | regex_search('[0-9]+') }}
{{ s | b64encode }} {{ s | b64decode }}
{{ s | quote }}                             {# безопасно для shell #}
{{ password | password_hash('sha512') }}
{{ text | hash('sha1') }}
```

### Списки и словари
```jinja
{{ items | length }}
{{ items | join(', ') }}
{{ items | first }} {{ items | last }}
{{ items | unique | sort | list }}
{{ items | select('match', '^web') | list }}
{{ users | map(attribute='name') | list }}
{{ users | selectattr('enabled') | list }}
{{ users | rejectattr('name', 'equalto', 'root') | list }}
{{ dict_a | combine(dict_b) }}              {# слить словари #}
{{ my_dict | dict2items }} {{ list | items2dict }}
{{ big_list | batch(3) | list }}
```

### Числа, типы, форматы
```jinja
{{ value | int }} {{ value | float }} {{ value | bool }} {{ value | string }}
{{ (ansible_memtotal_mb * 0.8) | int }}
{{ data | to_json }} {{ data | to_nice_json(indent=2) }}
{{ data | to_yaml }} {{ data | to_nice_yaml(indent=2) }}
{{ json_string | from_json }}
{{ size | human_readable }}
```

### Сетевые (нужна библиотека `netaddr`)
```jinja
{{ '10.0.0.0/24' | ansible.utils.ipaddr('network') }}
{{ ip | ansible.utils.ipaddr('netmask') }}
```

### Файлы и внешние источники — `lookup`
```jinja
{{ lookup('file', '/path/to/file') }}
{{ lookup('env', 'HOME') }}
{{ lookup('pipe', 'date +%Y') }}
{{ lookup('password', '/dev/null length=20') }}
{{ lookup('template', 'inner.j2') }}
```

---

## 5. Практичный пример: `nginx.conf.j2`

```jinja
# {{ ansible_managed }}
user  {{ nginx_user | default('www-data') }};
worker_processes  {{ nginx_workers | default(ansible_processor_vcpus) }};
pid /run/nginx.pid;

events {
    worker_connections {{ nginx_worker_connections | default(1024) }};
}

http {
    sendfile on;
    keepalive_timeout {{ nginx_keepalive | default(65) }};
    client_max_body_size {{ nginx_max_body | default('10m') }};

{% if app_env == 'production' %}
    access_log /var/log/nginx/access.log combined;
{% else %}
    access_log /var/log/nginx/access.log combined;
    error_log  /var/log/nginx/error.log debug;
{% endif %}

{% if backend_hosts | default([]) | length > 0 %}
    upstream backend {
{% for h in backend_hosts %}
        server {{ h }}:{{ app_port }} max_fails=3 fail_timeout=30s;
{% endfor %}
    }
{% endif %}

    server {
        listen {{ http_port | default(80) }};
        server_name {{ domain }};
        root {{ app_root }};

{% for loc in extra_locations | default([]) %}
        location {{ loc.path }} {
            {{ loc.directive }};
        }
{% endfor %}

        location /health {
            return 200 'ok';
            add_header Content-Type text/plain;
        }
    }
}
```

Переменные к нему:
```yaml
# group_vars/web.yml
domain: example.com
app_root: /var/www/app
app_port: 8080
http_port: 80
nginx_max_body: 50m
extra_locations:
  - { path: "/static/", directive: "alias /var/www/app/static/" }
backend_hosts: "{{ groups['app'] | default([]) }}"
```

---

## 6. `.env` и docker-compose из шаблона (частый прод-кейс)

```jinja
{# templates/env.j2 #}
# {{ ansible_managed }}
APP_ENV={{ app_env }}
APP_VERSION={{ app_version }}
DB_HOST={{ hostvars[groups['db'][0]].ansible_default_ipv4.address }}
DB_PASSWORD={{ vault_db_password }}
{% for key, value in extra_env | default({}) | dictsort %}
{{ key }}={{ value }}
{% endfor %}
```

```yaml
- ansible.builtin.template:
    src: env.j2
    dest: /opt/app/.env
    mode: "0600"          # ⭐ секреты — только владельцу
  no_log: true            # ⭐ не печатать содержимое в лог
  notify: restart app
```

---

## 7. Отладка шаблонов

```bash
# 1) посмотреть, что получится, не меняя файл
ansible-playbook site.yml --check --diff --tags config

# 2) отрендерить шаблон в /tmp и почитать глазами
ansible web1 -m template -a "src=templates/nginx.conf.j2 dest=/tmp/out.conf"
ansible web1 -m command -a "cat /tmp/out.conf"

# 3) проверить выражение без шаблона
ansible web1 -m debug -a "msg={{ groups['web'] | map('extract', hostvars, 'ansible_default_ipv4') | map(attribute='address') | list }}"

# 4) локально, без хостов
ansible localhost -m debug -a "msg={{ 'a,b,c'.split(',') | join(' | ') }}"
```

Частые ошибки:

| Ошибка | Причина |
|--------|---------|
| `'dict object' has no attribute 'x'` | Нет такого ключа/факта; спасает `default()` или `\| default({})` |
| `'X' is undefined` | Переменная не определена на этом хосте |
| Пустые строки в результате | Не используются `{%- -%}` / `lstrip_blocks` |
| `template not found` | Путь ищется в `templates/` роли или относительно плейбука |
| Число стало строкой | <code v-pre>"{{ x }}"</code> всегда строка → `\| int` |
| Конфиг сломан, сервис не стартует | Нет `validate:` |
| Шаблон даёт `changed` каждый раз | Внутри дата/случайное значение/несортированный словарь → `dictsort` |

> ⚠️ Порядок ключей словаря может «плавать» — из-за этого шаблон даёт ложный `changed`.
> Решение: `| dictsort` при обходе словаря.

---

## 8. Где Ansible ищет шаблоны

```text:no-line-numbers
роль:            roles/<role>/templates/<файл>.j2     ← можно писать просто src: файл.j2
плейбук:         ./templates/<файл>.j2
относительный:   src: ../shared/templates/x.j2
абсолютный:      src: /opt/templates/x.j2
```
Внутри роли принято указывать только имя файла — Ansible сам найдёт его в `templates/` роли.

---

## 💼 Как это в DevOps

- Шаблоны — то, ради чего Ansible вообще берут: **один шаблон → 50 разных конфигов**,
  различия описаны переменными, а не копиями файлов.
- `validate:` + `backup: true` + handler `reload` — стандартная тройка для конфигов сервисов.
- Генерация конфигов балансировщика/мониторинга из `groups[...]` и `hostvars[...]` —
  классическая задача: добавил сервер в инвентарь → он сам появился в upstream и в targets.
- `.env` и `docker-compose.yml` из шаблона — так деплоят контейнерные приложения на VM.
- Секретные шаблоны: `mode: "0600"`, `no_log: true`, значения — из vault (тема 12).

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Подставить значение | <code v-pre>{{ var }}</code> |
| Условие | `{% if %} … {% elif %} … {% else %} … {% endif %}` |
| Цикл | `{% for x in list %} … {% endfor %}` |
| Номер итерации | <code v-pre>{{ loop.index }}</code> / <code v-pre>{{ loop.index0 }}</code> |
| Первый/последний элемент | <code v-pre>{{ loop.first }}</code> / <code v-pre>{{ loop.last }}</code> |
| Комментарий | `{# … #}` |
| Убрать лишние переносы | `{%- … -%}` или `lstrip_blocks: true` |
| Значение по умолчанию | <code v-pre>{{ var \| default('x') }}</code> |
| Упасть, если не задано | <code v-pre>{{ var \| mandatory }}</code> |
| Число | <code v-pre>{{ var \| int }}</code> |
| Объединить список | <code v-pre>{{ list \| join(', ') }}</code> |
| Достать поле у списка словарей | <code v-pre>{{ users \| map(attribute='name') \| list }}</code> |
| Фильтр по условию | <code v-pre>{{ users \| selectattr('enabled') \| list }}</code> |
| Слить словари | <code v-pre>{{ a \| combine(b) }}</code> |
| Хэш пароля | <code v-pre>{{ pw \| password_hash('sha512') }}</code> |
| Содержимое файла | <code v-pre>{{ lookup('file', 'путь') }}</code> |
| IP другого хоста | <code v-pre>{{ hostvars['db1'].ansible_default_ipv4.address }}</code> |
| Все хосты группы | `{% for h in groups['web'] %}` |
| Проверить конфиг перед подменой | `validate: "nginx -t -c %s"` |
| Посмотреть результат | `--check --diff` или рендер в `/tmp` |

---

## 🧠 Что запомнить

1. `template` = `copy` + рендер Jinja2; шаблон рендерится **на управляющей машине**.
2. Три конструкции: <code v-pre>{{ }}</code> — значение, `{% %}` — логика, `{# #}` — комментарий.
3. <code v-pre>{{ ansible_managed }}</code> в шапке конфига — дешёвая защита от ручных правок.
4. Циклы по `groups[...]` + `hostvars[...]` — способ собрать конфиг из инвентаря.
5. `{%- -%}` и `lstrip_blocks` управляют лишними пробелами и переносами.
6. `default()` и `mandatory` — базовая защита от `undefined`.
7. `map`, `selectattr`, `join`, `combine`, `dict2items` закрывают почти все выборки.
8. `validate:` обязателен для критичных конфигов, `backup: true` — полезен.
9. Секретные шаблоны: `mode: "0600"` + `no_log: true` + значения из vault.
10. Ложный `changed` у шаблона = нестабильные данные внутри (дата, порядок словаря) →
    `dictsort` и никакой динамики.
11. В роли шаблоны лежат в `templates/`, и `src:` пишется просто именем файла.
12. Отладка: `--check --diff`, рендер в `/tmp`, `debug` с выражением.

---

## Задачи

> Все шаблоны складывай в `templates/`, результат проверяй через `--check --diff`.

---

### Блок A. Теория

**A1.** Чем `template` отличается от `copy`? Где рендерится шаблон — на control node
или на целевом хосте?

<details><summary>Ответ</summary>

`template` перед копированием обрабатывает файл движком Jinja2, подставляя
переменные и факты. Рендер происходит **на управляющей машине**, на хост уезжает готовый файл.

</details>

**A2.** Назови три конструкции Jinja2 и что каждая делает.

<details><summary>Ответ</summary>

<code v-pre>{{ }}</code> — вывод значения; `{% %}` — управляющие конструкции (if/for/set);
`{# #}` — комментарий, не попадающий в результат.

</details>

**A3.** Что такое <code v-pre>{{ ansible_managed }}</code> и зачем его добавляют в шапку конфига?

<details><summary>Ответ</summary>

Специальная переменная с пометкой «файл управляется Ansible». Ставится в шапку,
чтобы никто не правил конфиг руками (правки затрутся при следующем прогоне).

</details>

**A4.** Как в шаблоне сделать ветвление по окружению?

<details><summary>Ответ</summary>

`{% if app_env == 'production' %} … {% else %} … {% endif %}`.

</details>

**A5.** Как пройти циклом по всем хостам группы и взять их IP?

<details><summary>Ответ</summary>

<code v-pre>{% for h in groups['web'] %}{{ hostvars[h].ansible_default_ipv4.address }}{% endfor %}</code>.

</details>

**A6.** Что такое `loop.index`, `loop.first`, `loop.last`?

<details><summary>Ответ</summary>

Номер итерации с 1, признак первой итерации, признак последней.

</details>

**A7.** Зачем нужны `{%-` и `-%}`? Что делают `trim_blocks` и `lstrip_blocks`?

<details><summary>Ответ</summary>

Управляют удалением пробелов и переносов вокруг тегов. `trim_blocks` убирает
перенос строки сразу после тега, `lstrip_blocks` — пробелы слева от тега.

</details>

**A8.** Чем `default('x')` отличается от `default('x', true)`?

<details><summary>Ответ</summary>

`default('x')` подставляет значение только если переменная не определена;
`default('x', true)` — ещё и если она определена, но пустая/ложная.

</details>

**A9.** Что делает фильтр `mandatory` и когда он полезнее `default`?

<details><summary>Ответ</summary>

`mandatory` заставляет рендер упасть, если переменная не задана. Полезен
для обязательных параметров: лучше явная ошибка, чем конфиг с пустым значением.

</details>

**A10.** Как получить список значений одного поля из списка словарей?

<details><summary>Ответ</summary>

<code v-pre>{{ users | map(attribute='name') | list }}</code>.

</details>

**A11.** Как отфильтровать список словарей по признаку?

<details><summary>Ответ</summary>

<code v-pre>{{ users | selectattr('enabled') | list }}</code> (или `rejectattr` для обратного).

</details>

**A12.** Как слить два словаря?

<details><summary>Ответ</summary>

<code v-pre>{{ a | combine(b) }}</code> (рекурсивно — `combine(b, recursive=True)`).

</details>

**A13.** Что делает `lookup('file', ...)` и где он выполняется?

<details><summary>Ответ</summary>

Читает содержимое файла; выполняется **на управляющей машине** (это важно:
файл должен лежать рядом с плейбуком, а не на целевом хосте).

</details>

**A14.** ⭐ Зачем нужен `validate:` и как он работает (что такое `%s`)?

<details><summary>Ответ</summary>

Проверяет корректность сгенерированного файла до подмены: Ansible кладёт
результат во временный файл и подставляет его путь вместо `%s` в указанную команду.
Если команда вернула ненулевой код — задача падает, а рабочий файл остаётся нетронутым.

</details>

**A15.** Почему шаблон может давать `changed` при каждом прогоне? Две причины.

<details><summary>Ответ</summary>

(1) В шаблоне есть меняющиеся данные (дата, случайное значение);
(2) нестабильный порядок обхода словаря — лечится `dictsort`.

</details>

**A16.** Где Ansible ищет файл, указанный в `src:` внутри роли?

<details><summary>Ответ</summary>

В `roles/<role>/templates/`; поэтому внутри роли достаточно указать имя файла.

</details>

**A17.** Как безопасно положить шаблон с секретами?

<details><summary>Ответ</summary>

`mode: "0600"`, владелец — сервисный пользователь, `no_log: true` на задаче,
значения — из ansible-vault.

</details>

**A18.** Как посмотреть результат рендера, не меняя файл на сервере? Два способа.

<details><summary>Ответ</summary>

(1) `--check --diff`; (2) отрендерить во временный файл
(`ansible host -m template -a "src=... dest=/tmp/out"`) и прочитать.

</details>

---

### Блок B. «Что выведет шаблон»

Дано:
```yaml
app_env: production
http_port: 8080
domain: example.com
users:
  - { name: alice, enabled: true }
  - { name: bob,   enabled: false }
settings: { c: 3, a: 1, b: 2 }
```

```jinja
{# B1 #}
listen {{ http_port | default(80) }};
server_name {{ domain }};
```

<details><summary>Ответ</summary>

```text:no-line-numbers
listen 8080;  server_name example.com;
```

</details>

```jinja
{# B2 #}
{% if app_env == 'production' %}debug off;{% else %}debug on;{% endif %}
```

<details><summary>Ответ</summary>

```text:no-line-numbers
debug off;
```

</details>

```jinja
{# B3 #}
{% for u in users %}{{ loop.index }}. {{ u.name }}
{% endfor %}
```

<details><summary>Ответ</summary>

```text:no-line-numbers
1. alice
2. bob
```

</details>

```jinja
{# B4 #}
{{ users | selectattr('enabled') | map(attribute='name') | join(', ') }}
```

<details><summary>Ответ</summary>

```text:no-line-numbers
alice
```

</details>

```jinja
{# B5 #}
{% for k, v in settings | dictsort %}{{ k }}={{ v }}
{% endfor %}
```

<details><summary>Ответ</summary>

```text:no-line-numbers
a=1
b=2
c=3
```

</details>

```jinja
{# B6 #}
{{ missing_var | default('нет значения') }}
{{ http_port | int * 2 }}
```

<details><summary>Ответ</summary>

```text:no-line-numbers
нет значения
16160
```

</details>

```jinja
{# B7 #}
{% for h in groups['web'] %}
server {{ hostvars[h].ansible_default_ipv4.address }}:{{ http_port }};
{% endfor %}
```

<details><summary>Ответ</summary>

По строке "server &lt;IP&gt;:8080;" на каждый хост группы web
(требует собранных фактов этих хостов).

</details>

```yaml
# B8
- ansible.builtin.template:
    src: app.conf.j2
    dest: /etc/app/app.conf
    mode: "0600"
    validate: "/usr/sbin/app --test-config %s"
  no_log: true
  notify: restart app
```

<details><summary>Ответ</summary>

Кладёт конфиг только владельцу (0600), предварительно проверив его командой,
не печатает содержимое в лог и перезапускает приложение при изменении.

</details>

---

### Блок C. Практика

#### C1. 🔑 Первый шаблон

Сделай `templates/index.html.j2`, который выводит имя хоста, IP, ОС и версию,
число CPU и память. Разложи на оба web-хоста и открой в браузере/curl.
Убедись, что содержимое разное.

#### C2. 🔑 nginx.conf из шаблона

1. Возьми реальный `nginx.conf` с хоста.
2. Замени в нём на переменные: `worker_processes`, `worker_connections`,
   `keepalive_timeout`, `client_max_body_size`, `server_name`, `root`.
3. Положи переменные в `group_vars/web.yml`, а `client_max_body_size` — в `host_vars/web1.yml`.
4. Примени с `validate` и handler'ом `reload nginx`.
5. Сравни полученные конфиги на двух хостах.

#### C3. Условия в шаблоне

Добавь в шаблон блок, который включает подробное логирование только при
`app_env != 'production'`, и блок SSL только при `ssl_enabled: true`.
Проверь оба варианта, переключая переменную через `-e`.

#### C4. 🔑 Upstream из инвентаря

Сгенерируй `upstream backend { ... }` из всех хостов группы `web` с их IP.
1. Проверь, что при добавлении хоста в инвентарь конфиг меняется сам.
2. Разберись, почему нужен сбор фактов со всех хостов, и почини, если упало.

<details><summary>Ответ</summary>

Если хост не участвует в текущем play, его фактов нет — падает `undefined`.
Решения: отдельный play `hosts: all` со сбором фактов, кэш фактов или хранение IP
в переменных инвентаря.

</details>

#### C5. Пробелы

Сделай шаблон с циклом и `if` без управления пробелами, посмотри на результат
(пустые строки). Затем добавь `{%-`/`-%}` и `lstrip_blocks: true`. Сравни файлы.

#### C6. Фильтры

Напиши шаблон, который:
1. выводит список включённых пользователей через запятую;
2. считает их количество;
3. выводит имена в верхнем регистре;
4. выводит 80% от памяти хоста в мегабайтах целым числом;
5. печатает словарь настроек как `key=value`, отсортированный по ключу.

#### C7. `.env` для приложения

Сделай `templates/env.j2` с `APP_ENV`, `APP_VERSION`, `DB_HOST` (из `hostvars` хоста БД)
и `DB_PASSWORD` (пока обычная переменная). Разложи с `mode: "0600"` и `no_log: true`.
Проверь права на файле.

#### C8. `validate` в деле

1. Специально сломай шаблон nginx (убери `;`).
2. Прогони с `validate` — что произошло? Изменился ли файл на сервере?
3. Убери `validate`, прогони — что с сервисом?
4. Восстанови и сделай вывод.

#### C9. Ложный `changed`

1. Добавь в шаблон строку с <code v-pre>{{ ansible_date_time.iso8601 }}</code>.
2. Прогони дважды — что в RECAP?
3. Убери и добавь обход словаря **без** `dictsort`, прогони несколько раз.
4. Почини оба случая.

<details><summary>Ответ</summary>

Дата даёт `changed` каждый прогон; несортированный словарь — иногда.
Лечение: убрать динамические данные, использовать `| dictsort`.

</details>

#### C10. Отладка

Отрендери шаблон в `/tmp/out.conf` ad-hoc командой и прочитай его.
Затем проверь пару сложных выражений через `debug` (например, список IP группы web
одной строкой).

#### C11. systemd unit из шаблона

Сделай `templates/app.service.j2` с переменными (`ExecStart`, `User`, `WorkingDirectory`,
`Environment`), положи в `/etc/systemd/system/app.service`, сделай handler
с `daemon_reload: true` и запуском сервиса.

<details><summary>Ответ</summary>

Handler должен содержать `daemon_reload: true`, иначе systemd не увидит
изменённый unit.

</details>

#### C12. Шаблон для мониторинга (со звёздочкой)

Сгенерируй `targets.json` для Prometheus из всех хостов инвентаря с их группами
в качестве лейблов. Используй `to_nice_json`.

<details><summary>Ответ</summary>

Полезная конструкция: <code v-pre>{{ groups | dict2items }}</code> либо обход `groups` c фильтрацией
служебных групп (`all`, `ungrouped`), вывод через `to_nice_json`.

</details>

---

### Блок D. Инциденты

**D1.** `AnsibleUndefinedVariable: 'app_port' is undefined` при рендере шаблона.
Три способа решения.

<details><summary>Ответ</summary>

`| default(...)`, объявить переменную в `defaults`/`group_vars`, либо `assert`
в `pre_tasks` (для обязательных — предпочтительно явное падение).

</details>

**D2.** `'dict object' has no attribute 'ansible_default_ipv4'` в цикле по `groups['web']`.
Причина и решение.

<details><summary>Ответ</summary>

Факты этого хоста не собраны (он не входит в play или `gather_facts: false`).
Решение: собрать факты на `all` отдельным play или включить кэш фактов.

</details>

**D3.** В результате шаблона куча пустых строк. Что настроить?

<details><summary>Ответ</summary>

`trim_blocks`/`lstrip_blocks` и `{%- -%}` в самом шаблоне.

</details>

**D4.** `Could not find or access 'nginx.conf.j2'`. Где Ansible ищет шаблон?

<details><summary>Ответ</summary>

В роли — `roles/<role>/templates/`; в плейбуке — `./templates/` рядом с плейбуком;
либо указывать относительный/абсолютный путь.

</details>

**D5.** Конфиг приехал, nginx упал, сайт лежит. Что нужно было добавить в задачу?

<details><summary>Ответ</summary>

`validate:` (и желательно `backup: true`), плюс handler `reload` вместо `restart`.

</details>

**D6.** Шаблон каждый раз `changed`, хотя переменные не менялись. Две причины и лечение.

<details><summary>Ответ</summary>

Динамические данные в шаблоне; нестабильный порядок словаря. Лечение:
убрать динамику, `dictsort`, проверить `--diff` и увидеть, какая строка отличается.

</details>

**D7.** В CI-логе видно содержимое `.env` с паролем. Что добавить?

<details><summary>Ответ</summary>

`no_log: true` на задаче и права `0600` на файле; секрет — в vault.

</details>

**D8.** Число из шаблона сравнивается как строка (`"8080" > "999"` даёт неожиданный результат).
Почему и как чинить?

<details><summary>Ответ</summary>

Все значения Jinja по умолчанию строки: нужно `| int` перед сравнением
и арифметикой.

</details>

**D9.** Один и тот же шаблон нужен двум ролям. Как правильно организовать,
чтобы не копировать файл?

<details><summary>Ответ</summary>

Вынести общий шаблон в отдельную роль (или в общий каталог с явным путём `src:`),
и подключать её как зависимость; дублирование файлов — путь к рассинхрону.

</details>

**D10.** После добавления хоста в группу `web` конфиг балансировщика не обновился.
Что проверить?

<details><summary>Ответ</summary>

Факты/инвентарь: обновился ли инвентарь, входит ли хост в группу
(`ansible-inventory --graph`), собирались ли факты нового хоста, и была ли запущена
роль балансировщика после добавления.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое Jinja2 и где он используется в Ansible?

<details><summary>Ответ</summary>

Шаблонизатор, на котором работают файлы `.j2`, выражения в переменных, `when`,
`loop` и фильтры.

</details>

**2.** Чем `template` отличается от `copy`?

<details><summary>Ответ</summary>

`copy` кладёт файл как есть, `template` — с подстановкой переменных.

</details>

**3.** Где рендерится шаблон?

<details><summary>Ответ</summary>

На управляющей машине; на целевой хост уезжает уже готовый файл.

</details>

**4.** Как сделать условие или цикл в шаблоне?

<details><summary>Ответ</summary>

`{% if %}…{% endif %}` и `{% for %}…{% endfor %}`.

</details>

**5.** Как задать значение по умолчанию для переменной в шаблоне?

<details><summary>Ответ</summary>

Фильтром `default()`; для обязательных — `mandatory` или `assert`.

</details>

**6.** Как сгенерировать конфиг балансировщика из списка серверов?

<details><summary>Ответ</summary>

Циклом по `groups['web']` с обращением к `hostvars[host].ansible_default_ipv4.address`.

</details>

**7.** Как безопасно применять конфиги критичных сервисов?

<details><summary>Ответ</summary>

`validate:` + `backup: true` + handler `reload` + прогон с `--check --diff --limit`.

</details>

**8.** Как передать секрет в конфиг?

<details><summary>Ответ</summary>

Через переменную из ansible-vault, файл с `mode: "0600"`, задача с `no_log: true`.

</details>

**9.** Почему шаблон может показывать `changed` при каждом запуске?

<details><summary>Ответ</summary>

Внутри есть нестабильные данные (дата, случайные значения) или несортированный словарь.

</details>

**10.** Как отладить шаблон?

<details><summary>Ответ</summary>

`--check --diff`, рендер во временный файл, `debug` для проверки выражений.

</details>

---

### 🎯 Чек-лист

- [ ] Сделал конфиг nginx полностью из шаблона с переменными
- [ ] Использую <code v-pre>{{ ansible_managed }}</code> в шапке
- [ ] Умею писать `if`/`for` и управлять пробелами
- [ ] Генерирую upstream/targets из `groups` и `hostvars`
- [ ] Знаю фильтры `default`, `int`, `join`, `map`, `selectattr`, `combine`, `dictsort`
- [ ] Применяю `validate:` к критичным конфигам
- [ ] Секретные шаблоны кладу с `mode: "0600"` и `no_log: true`
- [ ] Победил ложный `changed` у шаблона
- [ ] Умею отрендерить шаблон в `/tmp` для отладки
