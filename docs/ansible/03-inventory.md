---
title: "03. Inventory — список серверов"
description: "INI и YAML форматы, group_vars/host_vars, паттерны выбора хостов, динамический inventory"
---

# 03. Inventory — список серверов

> Роадмап → 5. Ansible → Фундамент → **«Inventory — список серверов, на которых выполнять
> команды/плейбуки. INI-формат или YAML.»**
> **После темы ты умеешь:** описывать хосты и группы, раскладывать переменные по
> `group_vars`/`host_vars`, выбирать хосты паттернами и читать `ansible-inventory`.

---

## 🗺️ Карта темы

```text:no-line-numbers
                          INVENTORY
   ┌─────────────────────────────────────────────────────┐
   │  ХОСТЫ            ГРУППЫ              ПЕРЕМЕННЫЕ    │
   │  web1 ─┐                                            │
   │  web2 ─┼──► [web] ─┐                 group_vars/    │
   │  db1  ─┼──► [db]  ─┼──► [production]   all.yml      │
   │  db2  ─┘           │                   web.yml      │
   │                    └──► all (всегда)   production.yml│
   │                                       host_vars/     │
   │                                        web1.yml      │
   └─────────────────────────────────────────────────────┘
              │
              ▼
      ansible <ПАТТЕРН> -m module
      ansible-playbook site.yml --limit web
```

Две встроенные группы есть всегда:
- **`all`** — все хосты инвентаря;
- **`ungrouped`** — хосты, не попавшие ни в одну группу.

---

## 1. INI-формат — быстрый старт

```ini
# inventory.ini

# 1) хосты без группы
bastion.example.com

# 2) простая группа
[web]
web1.example.com
web2.example.com

# 3) переменные прямо у хоста
[db]
db1 ansible_host=10.0.0.21 ansible_user=postgres
db2 ansible_host=10.0.0.22

# 4) диапазоны (не надо писать 10 строк)
[workers]
worker[01:10].example.com
node-[a:f].local

# 5) переменные группы
[web:vars]
http_port=80
app_env=production

# 6) группа групп
[production:children]
web
db

[production:vars]
env_name=prod
```

**Диапазоны** экономят много строк: `web[01:05]` → `web01, web02, web03, web04, web05`
(с ведущими нулями, потому что в шаблоне `01`).

---

## 2. YAML-формат — так пишут в проектах

```yaml
# inventory.yml
all:
  vars:
    ansible_user: devops
    ansible_ssh_private_key_file: ~/.ssh/ansible_key
  children:
    web:
      hosts:
        web1:
          ansible_host: 10.0.0.11
        web2:
          ansible_host: 10.0.0.12
          http_port: 8080          # переменная конкретного хоста
      vars:
        http_port: 80              # переменная группы
    db:
      hosts:
        db1:
          ansible_host: 10.0.0.21
      vars:
        pg_version: 16
    production:
      children:
        web:
        db:
```

| | INI | YAML |
|---|-----|------|
| Читаемость мелкого инвентаря | ✅ проще | чуть многословнее |
| Вложенные структуры (списки, словари) | ❌ костыли | ✅ естественно |
| Единый стиль с плейбуками | ❌ | ✅ |
| Что выбрать | Лаба, 5-10 хостов | Реальный проект |

> 💡 Оба формата работают одинаково. Ansible определяет формат по содержимому,
> расширение файла роли не играет (но `.ini`/`.yml` полезны людям).

---

## 3. ⭐ Где хранить переменные: `group_vars` и `host_vars`

**Не пихай переменные в сам inventory** (кроме параметров подключения). Правильное место —
каталоги рядом с инвентарём:

```text:no-line-numbers
inventories/
└── prod/
    ├── hosts.yml
    ├── group_vars/
    │   ├── all.yml          # для всех хостов
    │   ├── web.yml          # для группы web
    │   ├── db.yml
    │   └── production.yml   # для группы-родителя
    └── host_vars/
        ├── web1.yml         # только для web1
        └── db1.yml
```

```yaml
# group_vars/web.yml
http_port: 80
nginx_worker_processes: auto
app_domain: example.com

# host_vars/web1.yml
http_port: 8080              # ⭐ перекроет групповое значение
server_role: canary
```

Правила разрешения:
1. `group_vars/all` → самые общие значения;
2. переменные родительской группы перекрываются дочерней;
3. `host_vars` сильнее любой группы;
4. при равенстве «глубины» групп порядок определяется алфавитом или `ansible_group_priority`.

Большие наборы можно раскладывать каталогами (**все файлы внутри читаются**):
```text:no-line-numbers
group_vars/
└── web/
    ├── nginx.yml
    ├── app.yml
    └── vault.yml        # зашифрованный кусок (тема 12)
```

> ⚠️ `group_vars` ищется рядом с **инвентарём** и рядом с **плейбуком**. Если есть оба —
> применяются оба (вариант рядом с плейбуком приоритетнее). Это источник загадочных багов:
> держи переменные в одном месте — рядом с инвентарём.

Полная таблица приоритетов переменных — тема [07. Переменные и факты](/ansible/07-variables-facts).

---

## 4. Паттерны выбора хостов

```bash
ansible all -m ping                    # все хосты
ansible web -m ping                    # группа web
ansible web1 -m ping                   # один хост
ansible 'web*' -m ping                 # маска по имени
ansible 'web,db' -m ping               # объединение групп
ansible 'web:db' -m ping               # то же (двоеточие = ИЛИ)
ansible 'web:!web2' -m ping            # web, КРОМЕ web2
ansible 'web:&production' -m ping      # пересечение: и web, И production
ansible '~web\d+' -m ping              # регулярное выражение (начинается с ~)
ansible 'web[0]' -m ping               # первый хост группы (по индексу)
ansible 'web[0:1]' -m ping             # срез: первые два хоста
ansible localhost -m ping -c local     # локальная машина
```

```yaml
# в плейбуке
- hosts: web:!web2
  tasks: ...
```

```bash
# ограничить запуск, не меняя плейбук ⭐ самый частый флаг на практике
ansible-playbook site.yml --limit web1
ansible-playbook site.yml --limit 'web:!web2'
ansible-playbook site.yml --limit @retry_hosts.txt      # список из файла
```

> 💡 `--limit` — обязательный рефлекс перед прогоном на проде: сначала на одном хосте,
> потом на всех.

---

## 5. Несколько инвентарей и окружения

```bash
# несколько файлов сразу
ansible-playbook site.yml -i inventories/dev/hosts.yml -i inventories/common/hosts.yml

# каталог как инвентарь: Ansible прочитает ВСЕ файлы внутри
ansible-playbook site.yml -i inventories/prod/
```

**Классическая структура разделения окружений:**
```text:no-line-numbers
inventories/
├── dev/
│   ├── hosts.yml
│   └── group_vars/all.yml      # app_env: dev,  replicas: 1
└── prod/
    ├── hosts.yml
    └── group_vars/all.yml      # app_env: prod, replicas: 3
```
Один и тот же `site.yml` применяется к разным инвентарям — различия живут только
в переменных. Это и есть «build once, deploy many» из блока CI/CD, но для конфигурации.

> ⚠️ Никогда не держи dev и prod в одном файле с группами `dev`/`prod`: одна опечатка
> в `--limit` — и ты применил изменения на проде. Физическое разделение каталогов — защита.

---

## 6. Динамический inventory

Когда серверы создаются автоматически (облако, автоскейлинг), статический список устаревает
мгновенно. Решение — **inventory-плагины**, которые опрашивают API.

```yaml
# inventories/prod/aws_ec2.yml   ← имя файла ДОЛЖНО заканчиваться на aws_ec2.yml
plugin: amazon.aws.aws_ec2
regions:
  - eu-central-1
filters:
  tag:Environment: production
  instance-state-name: running
keyed_groups:
  - key: tags.Role                 # тег Role=web → группа tag_Role_web
    prefix: tag_Role
  - key: placement.availability_zone
    prefix: az
hostnames:
  - private-ip-address
compose:
  ansible_host: private_ip_address
```

```bash
ansible-inventory -i inventories/prod/aws_ec2.yml --graph
ansible -i inventories/prod/aws_ec2.yml tag_Role_web -m ping
```

Популярные плагины: `amazon.aws.aws_ec2`, `google.cloud.gcp_compute`, `azure.azcollection.azure_rm`,
`community.docker.docker_containers`, `community.general.proxmox`, `kubernetes.core.k8s`.

**Свой динамический inventory** — любой исполняемый файл, который по `--list` печатает JSON:
```json
{
  "web": { "hosts": ["10.0.0.11", "10.0.0.12"], "vars": { "http_port": 80 } },
  "_meta": { "hostvars": { "10.0.0.11": { "role": "canary" } } }
}
```
```bash
chmod +x inventory.py
ansible -i ./inventory.py all -m ping
```

> 💡 Связка с Terraform: Terraform создаёт инстансы и проставляет теги → динамический
> inventory их находит по тегам → Ansible настраивает. Никаких ручных списков IP.

---

## 7. Инструмент `ansible-inventory` — проверяй, а не угадывай

```bash
ansible-inventory --list                       # весь инвентарь в JSON
ansible-inventory --graph                      # дерево групп и хостов
ansible-inventory --graph --vars               # то же + переменные
ansible-inventory --host web1                  # ИТОГОВЫЕ переменные конкретного хоста
ansible-inventory -i inventories/prod/ --list -y   # вывод в YAML
```

```text:no-line-numbers
@all:
  |--@ungrouped:
  |  |--bastion
  |--@production:
  |  |--@web:
  |  |  |--web1
  |  |  |--web2
  |  |--@db:
  |  |  |--db1
```

Плюс полезное:
```bash
ansible-playbook site.yml --list-hosts         # на какие хосты подействует
ansible all --list-hosts                       # то же для ad-hoc
ansible web -m debug -a "var=http_port"        # какое значение переменной реально приехало
```

---

## 8. Частые ошибки инвентаря

| Ошибка | Симптом | Лечение |
|--------|---------|---------|
| Хост описан в двух группах с разными значениями | Непредсказуемая переменная | `ansible-inventory --host` и явный приоритет через `host_vars` |
| Переменные в INI как YAML-структуры | Списки/словари не работают | Переезд на YAML или `group_vars` |
| `group_vars` лежит не рядом с инвентарём | «Переменная не подхватывается» | Держать `group_vars` рядом с инвентарём (или рядом с плейбуком — но выбрать одно) |
| Имя файла `group_vars/web.yaml` при группе `web-servers` | Тихо не применяется | Имя файла = **точное** имя группы |
| Дефис в имени группы + обращение `groups.web-servers` | Ошибка Jinja | Использовать `groups['web-servers']`, а лучше `_` вместо `-` |
| Один файл с dev и prod | Случайный прогон по проду | Разные каталоги инвентарей |
| Пробелы/табы в INI | `Unable to parse` | Проверить формат, `ansible-inventory --list` |

---

## 💼 Как это в DevOps

- Инвентарь — это **описание парка серверов**: часто первое, что просят показать на
  практическом собеседовании («покажи, как у вас организованы окружения»).
- Реальная структура почти всегда: `inventories/<env>/hosts.yml` + `group_vars/` + `host_vars/`,
  всё в git, прод — с ограниченным доступом.
- В облаках статический инвентарь уступает место динамическому: хосты появляются
  и исчезают, единственный надёжный источник правды — API/теги.
- `--limit` + `--check` — стандартный ритуал перед применением на проде.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Посмотреть дерево групп | `ansible-inventory --graph` |
| Итоговые переменные хоста | `ansible-inventory --host web1` |
| На какие хосты подействует | `ansible-playbook site.yml --list-hosts` |
| Все хосты | `ansible all -m ping` |
| Группа минус хост | `ansible 'web:!web2' -m ping` |
| Пересечение групп | `ansible 'web:&production' -m ping` |
| По маске | `ansible 'web*' -m ping` |
| Ограничить прогон | `ansible-playbook site.yml --limit web1` |
| Несколько инвентарей | `-i inv1.yml -i inv2.yml` или `-i каталог/` |
| Диапазон хостов (INI) | `web[01:05].example.com` |
| Группа групп (INI) | `[prod:children]` |
| Переменные группы (INI) | `[web:vars]` |
| Переменные — правильно | `group_vars/<группа>.yml`, `host_vars/<хост>.yml` |
| Динамический инвентарь | inventory-плагин (`aws_ec2.yml`) или свой скрипт с `--list` |

---

## 🧠 Что запомнить

1. Inventory — список хостов и групп; форматы INI и YAML равнозначны, YAML удобнее для проектов.
2. Группы `all` и `ungrouped` существуют всегда.
3. `[группа:children]` (INI) / `children:` (YAML) строят иерархию групп.
4. Параметры подключения — в инвентаре; **прикладные переменные — в `group_vars`/`host_vars`**.
5. Имя файла в `group_vars` должно **точно** совпадать с именем группы.
6. `host_vars` сильнее `group_vars`; дочерняя группа сильнее родительской.
7. Паттерны: `:` — объединение, `:&` — пересечение, `:!` — исключение, `~` — регулярка.
8. `--limit` ограничивает прогон без правки плейбука — обязательный рефлекс для прода.
9. Окружения разделяют **каталогами инвентарей**, а не группами внутри одного файла.
10. В облаке — динамический inventory по тегам (плагины `aws_ec2`, `gcp_compute`…).
11. `ansible-inventory --graph/--host` отвечает на вопрос «что Ansible реально видит».

---

## Задачи

> Стенд: 3 хоста (web1, web2, db1) с рабочим SSH-доступом.

---

### Блок A. Теория

**A1.** Что такое inventory и что в нём хранится?

<details><summary>Ответ</summary>

Описание управляемого парка: хосты, их группировка и переменные (в первую очередь
параметры подключения). Это ответ на вопрос «на чём выполнять».

</details>

**A2.** Какие два формата поддерживаются? Когда какой выбирать?

<details><summary>Ответ</summary>

INI (компактный, хорош для небольших статических списков) и YAML (структурный,
поддерживает списки/словари, единый стиль с плейбуками — выбор для проектов).

</details>

**A3.** Какие две группы существуют всегда, независимо от содержимого файла?

<details><summary>Ответ</summary>

`all` (все хосты) и `ungrouped` (хосты вне групп).

</details>

**A4.** Как в INI и в YAML описать «группу групп»?

<details><summary>Ответ</summary>

INI: `[production:children]` со списком групп. YAML: ключ `children:` внутри группы.

</details>

**A5.** Чем `web1` в inventory отличается от `ansible_host=10.0.0.11`?

<details><summary>Ответ</summary>

`web1` — алиас (имя в инвентаре, по нему адресуются плейбуки и `host_vars`);
`ansible_host` — реальный адрес подключения. Без `ansible_host` имя должно резолвиться.

</details>

**A6.** Что означает запись `worker[01:10].example.com`?

<details><summary>Ответ</summary>

Диапазон: 10 хостов `worker01.example.com` … `worker10.example.com`
(ведущие нули сохраняются, потому что шаблон записан как `01`).

</details>

**A7.** ⭐ Где правильно хранить прикладные переменные и почему не в самом inventory?

<details><summary>Ответ</summary>

В `group_vars/` и `host_vars/` рядом с инвентарём. Причины: инвентарь остаётся
списком хостов, переменные удобно раскладывать по файлам/каталогам, их можно шифровать
vault'ом и осмысленно ревьюить в MR.

</details>

**A8.** Как должен называться файл в `group_vars` для группы `web-servers`?

<details><summary>Ответ</summary>

Ровно `group_vars/web-servers.yml` — имя файла должно точно совпадать с именем группы.

</details>

**A9.** Что сильнее: `group_vars/web.yml` или `host_vars/web1.yml`? А родительская группа
или дочерняя?

<details><summary>Ответ</summary>

`host_vars` сильнее `group_vars`; дочерняя группа сильнее родительской.

</details>

**A10.** Что произойдёт, если `group_vars` есть и рядом с инвентарём, и рядом с плейбуком?

<details><summary>Ответ</summary>

Читаются оба набора, но переменные рядом с плейбуком имеют более высокий приоритет.
Это частый источник путаницы — держи переменные в одном месте.

</details>

**A11.** Расшифруй паттерны: `web:db`, `web:!web2`, `web:&production`, `~web\d+`, `web[0]`.

<details><summary>Ответ</summary>

`web:db` — объединение групп; `web:!web2` — web без web2; `web:&production` —
пересечение (хосты, входящие в обе группы); `~web\d+` — выбор регулярным выражением;
`web[0]` — первый хост группы по индексу.

</details>

**A12.** Зачем нужен `--limit`, если можно поправить `hosts:` в плейбуке?

<details><summary>Ответ</summary>

`--limit` не требует правок кода и ревью: одна и та же проверенная конфигурация
применяется к подмножеству хостов. Правка `hosts:` — изменение кода, которое легко забыть
вернуть.

</details>

**A13.** Что такое динамический inventory и когда он нужен?

<details><summary>Ответ</summary>

Инвентарь, который формируется на лету из внешнего источника (API облака, CMDB,
docker). Нужен там, где хосты создаются и удаляются автоматически.

</details>

**A14.** Что должен вернуть самописный inventory-скрипт при запуске с `--list`?

<details><summary>Ответ</summary>

JSON: группы с `hosts`/`vars`/`children` и опциональный блок `_meta.hostvars`
с переменными хостов.

</details>

**A15.** Как проверить, какие переменные реально применятся к хосту `web1`?

<details><summary>Ответ</summary>

`ansible-inventory --host web1` (итоговые переменные инвентаря) и
`ansible web1 -m debug -a "var=имя"` (значение с учётом всех источников в момент выполнения).

</details>

**A16.** Как правильно разделять окружения dev/prod в инвентаре и почему именно так?

<details><summary>Ответ</summary>

Отдельными каталогами инвентарей (`inventories/dev`, `inventories/prod`) со своими
`group_vars`. Это исключает случайное применение прод-переменных или прогон по проду
из-за опечатки в паттерне.

</details>

**A17.** Можно ли указать несколько инвентарей одной командой? Как?

<details><summary>Ответ</summary>

Да: несколько `-i` подряд либо каталог, содержащий несколько файлов инвентаря.

</details>

---

### Блок B. «Что делает команда/конфиг»

```bash
B1.  ansible-inventory --graph
B2.  ansible-inventory --host web1
B3.  ansible-inventory -i inventories/prod/ --list -y
B4.  ansible 'web:&production' -m ping
B5.  ansible 'all:!db' -m command -a "uptime"
B6.  ansible-playbook site.yml --limit 'web1' --check
B7.  ansible web -m debug -a "var=groups"
B8.  ansible web1 -m debug -a "var=group_names"
B9.  ansible all --list-hosts
B10. ansible-playbook site.yml -i inventories/dev/ -i inventories/common/
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Показать дерево групп и хостов
B2.  Показать все переменные, которые инвентарь даёт хосту web1
B3.  Вывести весь инвентарь из каталога prod в YAML
B4.  Пропинговать хосты, входящие И в web, И в production
B5.  Выполнить uptime на всех хостах, кроме группы db
B6.  Сухой прогон плейбука только на web1
B7.  Показать словарь всех групп и их хостов
B8.  Показать, в какие группы входит web1
B9.  Перечислить все хосты инвентаря без выполнения задач
B10. Запустить плейбук, объединив два инвентаря
```

</details>

```ini
# B11
[web]
web[01:03].local

[web:vars]
http_port=80

[production:children]
web
```
Вопрос: сколько хостов в инвентаре, в каких они группах и какие переменные получат?

<details><summary>Ответ</summary>

Три хоста: `web01.local`, `web02.local`, `web03.local`. Они в группе `web`,
которая является дочерней для `production`, плюс всегда в `all`. Переменная `http_port=80`
достаётся всем трём.

</details>

```yaml
# B12
all:
  children:
    web:
      hosts:
        web1:
          http_port: 8080
      vars:
        http_port: 80
```
Вопрос: какой `http_port` окажется у `web1` и почему?

<details><summary>Ответ</summary>

`8080` — переменная хоста сильнее переменной группы.

</details>

```text:no-line-numbers
# B13
inventories/prod/
├── hosts.yml            # группа web: web1, web2
├── group_vars/
│   ├── all.yml          # app_env: prod, log_level: info
│   └── web.yml          # log_level: debug
└── host_vars/
    └── web2.yml         # log_level: warning
```
Вопрос: какой `log_level` будет у `web1` и какой у `web2`?

<details><summary>Ответ</summary>

`web1` → `debug` (из `group_vars/web.yml`, перекрывает `all`);
`web2` → `warning` (из `host_vars`, сильнее всех групп).

</details>

---

### Блок C. Практика

#### C1. 🔑 INI-инвентарь

Опиши три хоста: группа `web` (web1, web2), группа `db` (db1), группа-родитель `production`,
переменные подключения в `[all:vars]`, `http_port=80` для группы `web`.
Проверь `ansible-inventory --graph` и `ansible all -m ping`.

#### C2. 🔑 Тот же инвентарь на YAML

Перепиши C1 в `inventory.yml`. Убедись, что `ansible-inventory --graph` даёт тот же результат.
Сравни читаемость и выпиши, что тебе удобнее.

#### C3. Диапазоны

Опиши группу `workers` из 10 хостов одной строкой в INI. Проверь `--list-hosts`
(без реального подключения).

#### C4. 🔑 Переменные по местам

Создай структуру:
```text:no-line-numbers
inventories/dev/{hosts.yml,group_vars/{all.yml,web.yml},host_vars/web1.yml}
```
Положи `app_env` в `all.yml`, `http_port` в `web.yml`, переопредели `http_port` в `host_vars/web1.yml`.
Проверь `ansible-inventory --host web1` и `--host web2`. Совпало с ожиданием?

#### C5. Иерархия групп

Сделай `production` родителем `web` и `db`, положи `group_vars/production.yml` с `env_name: prod`.
Убедись, что `env_name` виден на всех трёх хостах, а `http_port` — только на web.

#### C6. Конфликт групп (важный эксперимент)

Помести `web1` дополнительно в группу `canary` и задай `http_port` в обеих группах
(`web.yml` и `canary.yml`) разными значениями. Какое победит? Проверь
`ansible-inventory --host web1`. Затем добавь `ansible_group_priority` и проверь снова.

<details><summary>Ответ</summary>

При равной «глубине» групп побеждает та, что позже по алфавиту (`web` > `canary`),
поэтому без настроек выиграет `web`. `ansible_group_priority: 10` у `canary` делает её
приоритетнее. Надёжный способ избежать неоднозначности — `host_vars`.

</details>

#### C7. Паттерны

Выполни и объясни результат каждой команды:
```bash
ansible all --list-hosts
ansible web --list-hosts
ansible 'web:!web1' --list-hosts
ansible 'web:&production' --list-hosts
ansible '~web\d+' --list-hosts
ansible 'all:!web:!db' --list-hosts
```

<details><summary>Ответ</summary>

`all:!web:!db` даст хосты, не входящие ни в web, ни в db (например, bastion
или `ungrouped`).

</details>

#### C8. Два окружения

Создай `inventories/dev/` и `inventories/prod/` с одинаковыми группами, но разными
значениями `app_env` и `replicas`. Напиши плейбук, который печатает обе переменные,
и запусти его с обоими инвентарями. Убедись, что плейбук не менялся.

#### C9. `--limit` как страховка

Запусти плейбук с `--limit web1`, затем с `--limit 'web:!web1'`, затем без ограничения.
Сравни PLAY RECAP. Сформулируй правило для прода.

<details><summary>Ответ</summary>

Правило для прода: сначала `--check --diff --limit один_хост`, затем реальный прогон
на этом хосте, затем расширение на группу.

</details>

#### C10. Инвентарь из каталога

Положи два файла (`hosts_web.yml` и `hosts_db.yml`) в один каталог и укажи каталог
через `-i`. Проверь `--graph`: оба ли инвентаря прочитались?

<details><summary>Ответ</summary>

Оба файла прочитаются: каталог как источник инвентаря объединяет все файлы внутри.

</details>

#### C11. Динамический inventory (со звёздочкой)

Напиши скрипт `inventory.py`, который печатает JSON с группой `web` из двух твоих хостов
и `_meta.hostvars`. Сделай исполняемым и запусти `ansible -i ./inventory.py web -m ping`.

<details><summary>Ответ</summary>

Минимальный скрипт:
```python
#!/usr/bin/env python3
import json, sys
data = {
  "web": {"hosts": ["web1", "web2"], "vars": {"http_port": 80}},
  "_meta": {"hostvars": {
      "web1": {"ansible_host": "127.0.0.1", "ansible_port": 2201},
      "web2": {"ansible_host": "127.0.0.1", "ansible_port": 2202}}}
}
if "--list" in sys.argv: print(json.dumps(data))
elif "--host" in sys.argv: print(json.dumps({}))
```

</details>

#### C12. Docker как источник хостов (со звёздочкой)

```bash
ansible-galaxy collection install community.docker
cat > docker.yml <<'Y'
plugin: community.docker.docker_containers
docker_host: unix://var/run/docker.sock
Y
ansible-inventory -i docker.yml --graph
```
Что ты увидел и как это соотносится с твоим стендом?

---

### Блок D. Инциденты

**D1.** Переменная из `group_vars/web.yml` «не видна» в плейбуке. Три причины.

<details><summary>Ответ</summary>

(1) Имя файла не совпадает с именем группы; (2) `group_vars` лежит не рядом
с используемым инвентарём; (3) значение перекрыто более приоритетным источником
(`host_vars`, play vars, `-e`). Диагностика: `ansible-inventory --host` и `debug`.

</details>

**D2.** `ERROR! Unable to parse /path/inventory.ini as an inventory source`. Что проверять?

<details><summary>Ответ</summary>

Синтаксис (табы, лишние пробелы, незакрытые скобки), неверный путь, файл не является
инвентарём (например, это плейбук), у файла нет прав на чтение. Проверка —
`ansible-inventory -i файл --list`.

</details>

**D3.** Плейбук отработал на 40 хостах вместо 2. Что произошло и как страховаться?

<details><summary>Ответ</summary>

Паттерн захватил больше хостов, чем ожидалось (например, `web*` или группа-родитель),
либо использован не тот инвентарь. Страховка: `--list-hosts`, `--check`, `--limit`,
разделение окружений по каталогам.

</details>

**D4.** У `web1` переменная `http_port` внезапно равна 80, хотя в `host_vars/web1.yml` стоит 8080.
Алгоритм разбора.

<details><summary>Ответ</summary>

`ansible-inventory --host web1` → если там 8080, значит перекрывают play vars,
`set_fact`, role vars или `-e`. Если 80 — проблема в расположении/имени файла `host_vars`
(не рядом с тем инвентарём, который реально используется).

</details>

**D5.** В инвентаре есть группа `web-servers`, а в Jinja <code v-pre>{{ groups.web-servers }}</code> падает.
Причина и два решения.

<details><summary>Ответ</summary>

В Jinja дефис трактуется как минус. Решения: `groups['web-servers']` или переименовать
группу с подчёркиванием (`web_servers`) — предпочтительнее.

</details>

**D6.** После добавления нового сервера в облаке плейбук его не видит. Что не так
с подходом и что предложить?

<details><summary>Ответ</summary>

Статический инвентарь не знает о новых машинах. Решение — динамический inventory
по тегам облака (`aws_ec2` и аналоги), а создание инстансов — Terraform'ом.

</details>

**D7.** Коллега положил `group_vars/` в корень репозитория, а инвентарь — в `inventories/prod/`.
Переменные применяются «через раз». Объясни.

<details><summary>Ответ</summary>

Ansible читает `group_vars` рядом с инвентарём и рядом с плейбуком. Файлы в корне
подхватываются только при запуске из корня/плейбуком из корня, отсюда «через раз».
Лечение — одно место хранения (рядом с инвентарём).

</details>

**D8.** Хост `db1` попал одновременно в `production` и `staging` (обе — родительские группы
с переменной `env_name`). Как обнаружить и как исправить?

<details><summary>Ответ</summary>

Обнаружить: `ansible-inventory --host db1` и `ansible db1 -m debug -a "var=group_names"`.
Исправить: убрать хост из лишней группы (окружения должны быть разделены каталогами
инвентарей, а не группами).

</details>

**D9.** В INI-инвентаре нужна переменная-список `packages: [nginx, git]`. Не получается.
Что делать?

<details><summary>Ответ</summary>

INI не поддерживает структуры. Вынести в `group_vars/web.yml` как обычный YAML-список
или перевести инвентарь на YAML.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое inventory?

<details><summary>Ответ</summary>

Список управляемых хостов с группировкой и переменными.

</details>

**2.** Какие форматы инвентаря бывают?

<details><summary>Ответ</summary>

INI и YAML; плюс динамические (плагины и скрипты).

</details>

**3.** Как задать переменные для группы хостов?

<details><summary>Ответ</summary>

`[группа:vars]` в INI, `vars:` в YAML, но правильнее — файл `group_vars/<группа>.yml`.

</details>

**4.** Чем `group_vars` отличается от `host_vars`? Что приоритетнее?

<details><summary>Ответ</summary>

`group_vars` — переменные для всех хостов группы, `host_vars` — для одного хоста;
`host_vars` приоритетнее.

</details>

**5.** Что такое динамический inventory и зачем он нужен?

<details><summary>Ответ</summary>

Инвентарь, который строится из внешнего источника (API облака). Нужен при динамической
инфраструктуре, где список хостов постоянно меняется.

</details>

**6.** Как запустить плейбук только на одном сервере из группы?

<details><summary>Ответ</summary>

`ansible-playbook site.yml --limit web1`.

</details>

**7.** Как организовать несколько окружений (dev/stage/prod)?

<details><summary>Ответ</summary>

Отдельные каталоги `inventories/<env>/` со своими `group_vars`; общий плейбук, различия —
только в переменных.

</details>

**8.** Как посмотреть, какие переменные применятся к конкретному хосту?

<details><summary>Ответ</summary>

`ansible-inventory --host <имя>`, для отладки в рантайме — `debug`.

</details>

**9.** Что такое группа `all`?

<details><summary>Ответ</summary>

Встроенная группа, содержащая все хосты инвентаря.

</details>

**10.** Как исключить хост из выполнения?

<details><summary>Ответ</summary>

Паттерном `!`: `--limit 'web:!web2'`.

</details>

---

### 🎯 Чек-лист

- [ ] Написал инвентарь в INI и в YAML, оба работают одинаково
- [ ] Использую группы, группы-родители и диапазоны
- [ ] Переменные лежат в `group_vars`/`host_vars`, а не в инвентаре
- [ ] Проверял приоритет группа → хост экспериментом
- [ ] Уверенно пользуюсь паттернами `:`, `:&`, `:!`, `~`
- [ ] `--limit` вошёл в привычку перед любым прогоном
- [ ] Разделил dev и prod разными каталогами инвентарей
- [ ] Умею читать `ansible-inventory --graph` и `--host`
- [ ] Понимаю, что такое динамический inventory и когда он нужен
