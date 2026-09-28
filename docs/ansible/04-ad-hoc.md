---
title: "04. Ad-hoc команды"
description: "Разовые команды Ansible: command/shell/raw/script, полезные флаги, когда ad-hoc уместен, а когда нужен плейбук"
---

# 04. Ad-hoc команды

> Роадмап → 5. Ansible → 1. Теория → **Ad hoc**:
> «Это первое, с чем можно познакомиться. Ad-hoc команды — это возможность Ansible
> выполнять конкретные команды на целевых хостах. Самая база. Но…»
> **«Но»** — в реальной работе почти всё пишут плейбуками: ad-hoc не версионируется,
> не повторяется и не документирует себя. Его место — разовые операции и диагностика.
> **После темы ты умеешь:** одной строкой выполнять операции на десятках серверов.

---

## 🗺️ Анатомия команды

```text:no-line-numbers
ansible   <ПАТТЕРН>   -i inventory   -m <МОДУЛЬ>   -a "<АРГУМЕНТЫ>"   -b
   │          │             │             │               │            │
   │          │             │             │               │            └─ become (root)
   │          │             │             │               └─ аргументы модуля
   │          │             │             └─ какой модуль выполнить (по умолчанию command)
   │          │             └─ какой инвентарь (можно задать в ansible.cfg)
   │          └─ на каких хостах: all / web / web1 / 'web:!web2'
   └─ бинарник для разовых команд (для плейбуков — ansible-playbook)
```

```bash
ansible all -m ping
ansible web -m apt -a "name=nginx state=present" -b
ansible db1 -m service -a "name=postgresql state=restarted" -b
```

---

## 1. Самые нужные ad-hoc команды

### Проверка связи и диагностика
```bash
ansible all -m ping                                  # SSH + python работают?
ansible all -m command -a "uptime"                   # нагрузка
ansible all -m command -a "df -h /"                  # место на диске
ansible all -m command -a "free -m"                  # память
ansible all -m setup                                 # ВСЕ факты хоста
ansible all -m setup -a "filter=ansible_distribution*"   # только нужные
ansible all -m command -a "systemctl is-active nginx"
```

### Пакеты
```bash
ansible web -m apt -a "name=nginx state=present" -b
ansible web -m apt -a "name=nginx state=absent purge=yes" -b
ansible web -m apt -a "update_cache=yes cache_valid_time=3600" -b
ansible web -m apt -a "name=curl,git,htop state=present" -b
ansible web -m package -a "name=git state=present" -b      # универсально (apt/yum/dnf)
```

### Сервисы
```bash
ansible web -m service -a "name=nginx state=started enabled=yes" -b
ansible web -m service -a "name=nginx state=restarted" -b
ansible web -m systemd -a "name=nginx state=reloaded daemon_reload=yes" -b
```

### Файлы
```bash
ansible web -m copy -a "src=./nginx.conf dest=/etc/nginx/nginx.conf mode=0644 backup=yes" -b
ansible web -m copy -a 'content="hello\n" dest=/tmp/hello.txt'
ansible web -m file -a "path=/opt/app state=directory owner=deploy mode=0755" -b
ansible web -m file -a "path=/tmp/old.log state=absent" -b
ansible web -m fetch -a "src=/var/log/nginx/error.log dest=./logs/ flat=no"   # ЗАБРАТЬ с хостов
ansible web -m lineinfile -a 'path=/etc/hosts line="10.0.0.5 db1"' -b
```

### Пользователи и ключи
```bash
ansible all -m user -a "name=deploy state=present shell=/bin/bash groups=sudo append=yes" -b
ansible all -m user -a "name=olduser state=absent remove=yes" -b
ansible all -m authorized_key -a "user=deploy key='{{ lookup('file','~/.ssh/id_ed25519.pub') }}'" -b
```

### Произвольные команды
```bash
ansible all -m command -a "hostname -f"              # БЕЗ shell: нет |, >, $, &&
ansible all -m shell -a "ps aux | grep nginx | wc -l"   # через shell: можно всё
ansible all -m script -a "./check.sh"                # выполнить ЛОКАЛЬНЫЙ скрипт на хостах
ansible all -m raw -a "echo hi"                      # вообще без python (голые хосты)
```

### Разное полезное
```bash
ansible all -m git -a "repo=https://github.com/user/app dest=/opt/app version=main" -b
ansible all -m get_url -a "url=https://example.com/f.tar.gz dest=/tmp/f.tar.gz" -b
ansible all -m unarchive -a "src=/tmp/f.tar.gz dest=/opt remote_src=yes" -b
ansible all -m reboot -b                             # перезагрузить и дождаться возврата
ansible all -m wait_for -a "port=80 timeout=60"
ansible all -m cron -a "name='backup' hour=3 minute=0 job='/opt/backup.sh'" -b
```

---

## 2. `command` vs `shell` vs `raw` vs `script`

| Модуль | Как выполняется | Есть `\|`, `>`, `$VAR`, `&&`? | Когда использовать |
|--------|-----------------|------------------------------|--------------------|
| `command` | Напрямую, **без шелла** | ❌ нет | По умолчанию: безопаснее, нет сюрпризов с экранированием |
| `shell` | Через `/bin/sh -c` | ✅ да | Когда нужны пайпы, редиректы, переменные окружения |
| `raw` | Прямо через SSH, **без python** | ✅ да | Голый хост без python, сетевое железо |
| `script` | Копирует локальный скрипт и выполняет | ✅ да | Есть готовый скрипт, который не хочется переписывать |

```bash
ansible web -m command -a "echo $HOME"        # выведет литерально или подставит ЛОКАЛЬНО
ansible web -m shell  -a 'echo $HOME'         # подставит на УДАЛЁННОМ хосте
```

> ⚠️ Все четыре **неидемпотентны**: Ansible не знает, что означает твоя команда,
> поэтому всегда рапортует `changed`. В плейбуках их применяют в последнюю очередь
> и обязательно с `creates:`/`removes:`/`changed_when:` (темы 05, 08).

---

## 3. Полезные флаги

| Флаг | Что делает |
|------|-----------|
| `-i FILE` | Инвентарь (можно зафиксировать в `ansible.cfg`) |
| `-m MODULE` | Модуль (по умолчанию `command`) |
| `-a "ARGS"` | Аргументы модуля |
| `-b` / `--become` | Выполнить от root |
| `--become-user=USER` | От конкретного пользователя |
| `-K` | Спросить пароль sudo |
| `-u USER` | Пользователь подключения |
| `-f N` / `--forks` | Параллелизм (по умолчанию 5) |
| `-l` / `--limit` | Ограничить хосты |
| `-C` / `--check` | Сухой прогон (если модуль поддерживает) |
| `-D` / `--diff` | Показать различия в файлах |
| `-o` | Однострочный вывод — удобно для `grep` |
| `-v` … `-vvvv` | Подробность |
| `--list-hosts` | Только показать, на какие хосты подействует |
| `-e "VAR=VAL"` | Передать переменную |
| `-B 300 -P 0` | Асинхронный запуск (fire-and-forget) |

```bash
# сравнение вывода со всех хостов «в одну строку»
ansible all -m command -a "uname -r" -o

# долгая операция без ожидания (background), затем проверка
ansible all -m apt -a "upgrade=dist" -b -B 1800 -P 0
```

---

## 4. Когда ad-hoc уместен, а когда нет

| ✅ Уместен | ❌ Неуместен |
|-----------|-------------|
| Диагностика: «у кого сколько места на диске» | Настройка сервера (нужен плейбук в git) |
| Разовая массовая операция: срочный патч безопасности | Любое повторяющееся действие |
| Сбор фактов и инвентаризация | Сложная логика: условия, циклы, handler'ы |
| Проверка гипотезы перед написанием плейбука | Деплой приложения |
| Экстренный рестарт сервиса на 50 хостах | То, что должно быть воспроизводимым и ревьюируемым |

**Главное «но» из роадмапа:** ad-hoc-команды нигде не сохраняются. Через месяц никто
не вспомнит, что и где ты выполнял. Плейбук лежит в git, проходит ревью, повторяем
и самодокументирован. **Ad-hoc — это разведка, плейбук — это работа.**

> 💡 Рабочий приём: подобрал команду ad-hoc → убедился, что работает → **сразу перенёс
> в плейбук**. Так теория из ad-hoc естественно перетекает в тему 06.

```bash
# было (ad-hoc):
ansible web -m apt -a "name=nginx state=present" -b
```
```yaml
# стало (playbook, теперь это код в git):
- hosts: web
  become: true
  tasks:
    - name: nginx установлен
      ansible.builtin.apt:
        name: nginx
        state: present
```

---

## 5. Синтаксис аргументов `-a`

```bash
# key=value — основной вид
ansible web -m file -a "path=/opt/app state=directory mode=0755" -b

# значения с пробелами — в кавычках (следи за внешними кавычками!)
ansible web -m shell -a 'echo "hello world" > /tmp/a.txt'
ansible web -m copy -a 'content="line1\nline2\n" dest=/tmp/b.txt'

# JSON-форма — когда нужны списки/словари
ansible web -m apt -a '{"name": ["nginx","git"], "state": "present"}' -b

# переменные Jinja работают и здесь
ansible web -m debug -a "msg={{ ansible_default_ipv4.address }}"
```

Типичные ошибки экранирования:
```bash
ansible web -m shell -a "echo $USER"       # ❌ подставится ЛОКАЛЬНАЯ переменная
ansible web -m shell -a 'echo $USER'       # ✅ подставится на удалённом хосте
ansible web -m command -a "ls | wc -l"     # ❌ command не знает про |
ansible web -m shell -a "ls | wc -l"       # ✅
```

---

## 6. Вывод и как его читать

```text:no-line-numbers
web1 | CHANGED | rc=0 >>      ← состояние изменено
web2 | SUCCESS | rc=0 >>      ← всё уже как надо (ok)
db1  | FAILED! => {...}       ← задача упала (модуль отработал, результат — ошибка)
db2  | UNREACHABLE! => {...}  ← до хоста не достучались (SSH/сеть/ключ)
```

```bash
# сделать вывод читаемым
export ANSIBLE_STDOUT_CALLBACK=yaml
ansible web -m setup -a "filter=ansible_mounts"

# отобрать только нужное из фактов
ansible all -m setup -a "filter=ansible_memtotal_mb" -o
ansible all -m setup -a "gather_subset=network" | head -40
```

---

## 💼 Как это в DevOps

- Ad-hoc — инструмент дежурного инженера: «проверь на всех хостах версию ядра»,
  «где закончилось место», «перезапусти сервис на 30 машинах».
- Второй по частоте сценарий — **разведка перед плейбуком**: подобрать аргументы модуля
  на одном хосте, потом перенести в код.
- В зрелых командах массовые ad-hoc-операции по проду не приветствуются: они не оставляют
  следа в git. Если операция повторяется хотя бы дважды — её пишут плейбуком.
- `ansible all -m setup` — быстрый способ собрать инвентаризацию парка (ОС, версии, память).

---

## 📌 Шпаргалка

| Хочу | Команда |
|------|---------|
| Проверить связь | `ansible all -m ping` |
| Выполнить команду | `ansible all -m command -a "uptime"` |
| Команду с пайпом | `ansible all -m shell -a "ps aux \| grep nginx"` |
| Поставить пакет | `ansible web -m apt -a "name=nginx state=present" -b` |
| Перезапустить сервис | `ansible web -m service -a "name=nginx state=restarted" -b` |
| Скопировать файл | `ansible web -m copy -a "src=f dest=/etc/f mode=0644" -b` |
| Забрать файл с хостов | `ansible web -m fetch -a "src=/var/log/x.log dest=./logs/"` |
| Создать каталог | `ansible web -m file -a "path=/opt/app state=directory" -b` |
| Создать пользователя | `ansible all -m user -a "name=deploy state=present" -b` |
| Добавить SSH-ключ | `ansible all -m authorized_key -a "user=deploy key='...'" -b` |
| Посмотреть факты | `ansible web1 -m setup -a "filter=ansible_distribution*"` |
| Выполнить локальный скрипт | `ansible all -m script -a "./check.sh"` |
| На хосте без python | `ansible all -m raw -a "apt install -y python3"` |
| Однострочный вывод | добавить `-o` |
| Сухой прогон | добавить `-C --diff` |
| Быстрее | `-f 20` |

---

## 🧠 Что запомнить

1. Формат: `ansible <паттерн> -m <модуль> -a "<аргументы>"`; модуль по умолчанию — `command`.
2. `-b` — become, `-K` — пароль sudo, `-o` — однострочный вывод, `-C --diff` — сухой прогон.
3. `command` — без шелла (нет `|`, `>`, `$VAR`), `shell` — через шелл, `raw` — без python,
   `script` — выполнить локальный скрипт на хостах.
4. Одинарные кавычки — чтобы переменная раскрылась **на удалённом** хосте, а не локально.
5. `setup` — модуль сбора фактов; `filter=` спасает от километрового вывода.
6. `fetch` тянет файлы **с** хостов, `copy` — **на** хосты.
7. Все ad-hoc-операции с `command`/`shell` неидемпотентны — рапортуют `changed` всегда.
8. Ad-hoc не версионируется и не воспроизводится: это разведка и разовые операции.
9. Повторяется дважды → должно стать плейбуком.
10. Читай статусы: `CHANGED` / `SUCCESS` / `FAILED!` / `UNREACHABLE!` — последнее
    почти всегда про SSH, а не про задачу.

---

## Задачи

> Стенд: 3 хоста, `ansible.cfg` с инвентарём (чтобы не писать `-i` каждый раз).

---

### Блок A. Теория

**A1.** Что такое ad-hoc команда и из каких частей она состоит?

<details><summary>Ответ</summary>

Разовая команда без плейбука: `ansible <паттерн> -m <модуль> -a "<аргументы>"`
плюс флаги (`-b`, `-i`, `-f`, `--limit`).

</details>

**A2.** Какой модуль используется, если не указать `-m`?

<details><summary>Ответ</summary>

`command`.

</details>

**A3.** ⭐ Чем `command` отличается от `shell`? Приведи пример, где разница видна.

<details><summary>Ответ</summary>

`command` выполняется без шелла — нет пайпов, редиректов, подстановки переменных
и `&&`. `shell` выполняется через `/bin/sh -c`. Видно на `ls | wc -l`: `command` попытается
передать `|` как аргумент `ls` и упадёт, `shell` отработает.

</details>

**A4.** Когда нужен `raw` и чем он принципиально отличается от `command`?

<details><summary>Ответ</summary>

`raw` выполняет команду прямо через SSH, не доставляя python-модуль. Нужен, когда
на хосте нет python (bootstrap) или это сетевое устройство.

</details>

**A5.** Что делает модуль `script` и чем он удобнее, чем `copy` + `shell`?

<details><summary>Ответ</summary>

`script` сам копирует локальный скрипт на хост, выполняет и убирает за собой —
одна операция вместо двух и не нужно думать о каталоге и правах.

</details>

**A6.** Почему `command`/`shell` всегда показывают `changed`?

<details><summary>Ответ</summary>

Модуль не знает семантики произвольной команды и не может сравнить состояния
«до» и «после», поэтому любой запуск считается изменением. Управляется `creates`/`removes`/
`changed_when`.

</details>

**A7.** Чем `copy` отличается от `fetch`?

<details><summary>Ответ</summary>

`copy` кладёт файл **на** управляемые хосты, `fetch` забирает файл **с** них
на управляющую машину.

</details>

**A8.** Что делает флаг `-o` и когда он удобен?

<details><summary>Ответ</summary>

Печатает результат каждого хоста одной строкой — удобно для сравнения вывода
по парку и для `grep`.

</details>

**A9.** Что делает `-B 300 -P 0` и в каком случае это нужно?

<details><summary>Ответ</summary>

Запускает задачу асинхронно с таймаутом 300 секунд и не ждёт её (`poll=0`).
Нужно для долгих операций (обновление системы, длинные миграции), чтобы не держать SSH.

</details>

**A10.** Как посмотреть все факты хоста и как отфильтровать нужные?

<details><summary>Ответ</summary>

`ansible host -m setup` — все факты; `-a "filter=ansible_distribution*"` —
по маске имени; `-a "gather_subset=network"` — только подмножество.

</details>

**A11.** Объясни разницу статусов `FAILED!` и `UNREACHABLE!`.

<details><summary>Ответ</summary>

`FAILED!` — до хоста достучались, модуль отработал, но результат — ошибка
(например, пакет не найден). `UNREACHABLE!` — не удалось подключиться: SSH, сеть, ключ, python.

</details>

**A12.** ⭐ Назови три ситуации, где ad-hoc уместен, и три, где нужен плейбук.

<details><summary>Ответ</summary>

Уместен: диагностика/инвентаризация, срочная разовая операция, проверка гипотезы
перед написанием плейбука. Нужен плейбук: настройка сервера, деплой, всё повторяющееся
и всё, что должно быть в git и проходить ревью.

</details>

**A13.** Почему `ansible web -m shell -a "echo $HOME"` может дать неожиданный результат?

<details><summary>Ответ</summary>

Двойные кавычки раскрывает **локальный** шелл, и на хосты уедет уже подставленное
значение с твоей машины. Нужны одинарные кавычки.

</details>

**A14.** Как передать модулю аргумент-список (например, несколько пакетов)?

<details><summary>Ответ</summary>

Через запятую (`name=nginx,git,curl`) или в JSON-форме аргументов:
`-a '{"name": ["nginx","git"], "state": "present"}'`.

</details>

**A15.** Работает ли `--check` с ad-hoc? От чего это зависит?

<details><summary>Ответ</summary>

Работает, если модуль поддерживает check mode (`copy`, `file`, `apt`, `lineinfile`
и т.п.). `command`/`shell` в check mode просто пропускаются (`skipped`).

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  ansible all -m ping
B2.  ansible web -m apt -a "name=nginx state=present update_cache=yes" -b
B3.  ansible web -m service -a "name=nginx state=started enabled=yes" -b
B4.  ansible all -m command -a "df -h /" -o
B5.  ansible all -m shell -a "ps aux | grep -c sshd"
B6.  ansible web -m copy -a "src=./app.conf dest=/etc/app.conf mode=0644 backup=yes" -b
B7.  ansible web -m fetch -a "src=/var/log/syslog dest=./logs/ flat=no" -b
B8.  ansible all -m setup -a "filter=ansible_mounts"
B9.  ansible all -m user -a "name=deploy state=present groups=sudo append=yes" -b
B10. ansible all -m file -a "path=/tmp/cache state=absent" -b
B11. ansible all -m apt -a "upgrade=dist" -b -B 1800 -P 0
B12. ansible 'web:!web1' -m command -a "uptime" -f 20
B13. ansible all -m raw -a "which python3 || apt-get install -y python3" -b
B14. ansible all -m script -a "./scripts/healthcheck.sh"
B15. ansible web -m lineinfile -a 'path=/etc/hosts line="10.0.0.5 db1" state=present' -b -C -D
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Проверить доступность всех хостов
B2.  Обновить кэш apt и установить nginx на группу web от root
B3.  Запустить nginx и включить автозапуск
B4.  Показать свободное место на корне, по одной строке на хост
B5.  Посчитать процессы sshd (через шелл, потому что есть пайп)
B6.  Скопировать конфиг с правами 0644, сделав резервную копию прежнего
B7.  Забрать syslog со всех web-хостов в ./logs/<хост>/... на управляющую машину
B8.  Показать факт с информацией о смонтированных ФС
B9.  Создать пользователя deploy и добавить его в группу sudo (не затирая другие группы)
B10. Удалить каталог /tmp/cache на всех хостах
B11. Запустить полное обновление системы в фоне, не дожидаясь завершения
B12. Выполнить uptime на web без web1 с параллелизмом 20
B13. Поставить python3 без использования python-модулей (bootstrap голого хоста)
B14. Скопировать и выполнить локальный скрипт healthcheck.sh на всех хостах
B15. Показать, какие изменения внесло бы добавление строки в /etc/hosts, ничего не меняя
```

</details>

---

### Блок C. Практика

#### C1. 🔑 Разведка парка

Одной командой на всех хостах собери и выпиши в таблицу:
1. версию ОС (`ansible_distribution`, `ansible_distribution_version`);
2. объём памяти (`ansible_memtotal_mb`);
3. число CPU (`ansible_processor_vcpus`);
4. IP основного интерфейса (`ansible_default_ipv4.address`);
5. аптайм (`uptime`).
Используй `-m setup -a "filter=..."` и `-o`.

#### C2. `command` vs `shell`

Выполни и объясни каждый результат:
```bash
ansible web -m command -a "ls -la /etc | wc -l"
ansible web -m shell   -a "ls -la /etc | wc -l"
ansible web -m command -a "echo $HOSTNAME"
ansible web -m shell   -a 'echo $HOSTNAME'
ansible web -m shell   -a "echo $HOSTNAME"
```

<details><summary>Ответ</summary>

`command` с пайпом упадёт (`|` уедет аргументом `ls`); `shell` посчитает строки.
`"echo $HOSTNAME"` в двойных кавычках раскроется локально (или окажется пустым);
`'echo $HOSTNAME'` — на удалённом хосте.

</details>

#### C3. 🔑 Установка и запуск сервиса

1. Поставь nginx на группу `web`.
2. Включи его и добавь в автозагрузку.
3. Проверь `systemctl is-active nginx` ad-hoc'ом.
4. Проверь curl'ом с управляющей машины (порт проброшен в стенде?).
5. Повтори п.1 — сравни `CHANGED`/`SUCCESS`.

#### C4. Файлы туда и обратно

1. Создай локально `motd.txt`, скопируй его в `/etc/motd` на все хосты с `backup=yes`.
2. Измени содержимое и скопируй ещё раз — что произошло с бэкапом?
3. Забери `/etc/motd` со всех хостов через `fetch` и посмотри структуру каталогов.
4. Повтори `fetch` с `flat=yes` — в чём разница?

<details><summary>Ответ</summary>

`backup=yes` создаёт копию вида `/etc/motd.12345.2026-09-13@12:00:00~` при каждом
изменении. `fetch` без `flat=yes` создаёт `./logs/<host>/etc/motd` — файлы не конфликтуют;
с `flat=yes` все хосты пишут в один путь и затирают друг друга (использовать только
с <code v-pre>dest=./logs/{{ inventory_hostname }}.log</code>).

</details>

#### C5. Пользователь и ключ

1. Создай пользователя `deploy` на всех хостах.
2. Положи ему свой публичный ключ через `authorized_key`.
3. Проверь `ssh deploy@<host>` напрямую.
4. Удали пользователя с `remove=yes` и убедись, что домашний каталог исчез.

#### C6. Идемпотентность ad-hoc

Выполни трижды каждую пару и объясни поведение:
```bash
ansible web -m shell -a 'echo "line" >> /tmp/test.txt'
ansible web -m lineinfile -a 'path=/tmp/test2.txt line="line" create=yes'
```

<details><summary>Ответ</summary>

`shell` допишет три строки; `lineinfile` создаст файл и добавит строку один раз,
далее `ok`.

</details>

#### C7. `--check` и `--diff`

```bash
ansible web -m copy -a "content='new\n' dest=/etc/motd" -b -C -D
ansible web -m command -a "rm -rf /tmp/x" -b -C
```
Что показал первый вызов? Что произошло со вторым и почему `command` ведёт себя иначе?

<details><summary>Ответ</summary>

`copy -C -D` покажет diff и ничего не изменит. `command` в check mode **пропускается**
(`skipped`), потому что модуль не умеет предсказывать результат — это важно помнить,
опасная команда просто не выполнится (что хорошо), но и проверки не будет.

</details>

#### C8. Параллелизм

```bash
time ansible all -m command -a "sleep 3" -f 1
time ansible all -m command -a "sleep 3" -f 10
```
Объясни разницу и посчитай ожидаемое время для 30 хостов при `-f 5`.

<details><summary>Ответ</summary>

`-f 1` — последовательно (≈9 с на трёх хостах), `-f 10` — параллельно (≈3 с).
Для 30 хостов при `-f 5` будет 6 «волн»: ≈18 с при задаче в 3 с.

</details>

#### C9. Асинхронная задача

Запусти долгую операцию в фоне и проверь статус:
```bash
ansible web -m shell -a "sleep 60; echo done > /tmp/async.txt" -B 120 -P 0
ansible web -m command -a "cat /tmp/async.txt"      # сразу
# подожди минуту и повтори
```
Зачем это нужно на практике?

<details><summary>Ответ</summary>

Асинхронный запуск нужен для операций, которые длиннее SSH-таймаута, и когда
не хочется держать соединение (обновление ОС, перезагрузка, долгие миграции).

</details>

#### C10. Сбор логов

Собери `/var/log/nginx/access.log` со всех web-хостов в локальный каталог `./logs/`
одной командой. Проверь, что файлы не перезаписали друг друга.

<details><summary>Ответ</summary>

`ansible web -m fetch -a "src=/var/log/nginx/access.log dest=./logs/" -b` —
без `flat=yes` файлы разложатся по каталогам с именами хостов.

</details>

#### C11. 🔑 Из ad-hoc в плейбук

Возьми последовательность из C3 (пакет → сервис → конфиг) и перепиши её в плейбук
`web.yml`. Запусти дважды, добейся `changed=0` во втором прогоне.
Сформулируй, что именно ты выиграл по сравнению с ad-hoc.

<details><summary>Ответ</summary>

Выигрыш: код в git и в ревью, идемпотентность, повторяемость, `--check`,
самодокументированность (`name:` у задач), возможность применить к другому окружению.

</details>

#### C12. Экстренная операция (сценарий из жизни)

«На всех серверах нужно срочно закрыть уязвимость в пакете `curl`».
Составь последовательность ad-hoc команд: проверить текущую версию → обновить →
проверить результат → убедиться, что сервисы живы.

---

### Блок D. Инциденты

**D1.** `ansible web -m command -a "systemctl restart nginx"` → `Interactive authentication
required`. Что забыли?

<details><summary>Ответ</summary>

Нет `-b` (become): без root systemctl требует авторизации.

</details>

**D2.** `ansible all -m shell -a "df -h | grep /dev/sda1"` возвращает `rc=1` и статус FAILED
на части хостов, хотя команда «работает». Почему и как это правильно обработать?

<details><summary>Ответ</summary>

`grep` возвращает `rc=1`, когда ничего не нашёл, а ненулевой код = `failed`.
Обрабатывается через `|| true`, `failed_when: false` (в плейбуке) или изменением условия.

</details>

**D3.** Команда с `>` не создаёт файл, ошибок нет. Какой модуль использован и что исправить?

<details><summary>Ответ</summary>

Использован `command`, который не знает про редирект. Нужен `shell`
(а лучше — `copy`/`template`/`lineinfile`).

</details>

**D4.** `ansible all -m apt -a "name=nginx state=present"` → `Permission denied`. Причина?

<details><summary>Ответ</summary>

Нет `-b`: установка пакетов требует root.

</details>

**D5.** Ad-hoc с `copy` перезаписал рабочий конфиг на 20 серверах. Как надо было
проверить заранее и как теперь восстановить?

<details><summary>Ответ</summary>

Заранее — `-C -D` (сухой прогон с diff) и `--limit` на один хост.
Восстановление — из бэкапа, если был `backup=yes` (файлы `*.~N~` рядом), иначе из git/
резервных копий. Вывод: `backup=yes` и `--check` — обязательная привычка.

</details>

**D6.** `ansible all -m setup` выводит гигантскую простыню, в которой невозможно найти нужное.
Три способа сузить вывод.

<details><summary>Ответ</summary>

(1) `filter=ansible_distribution*`; (2) `gather_subset=network`/`!all,!min,network`;
(3) `-o` или `| jq` по нужному ключу; плюс `-m debug -a "var=ansible_facts.memtotal_mb"`.

</details>

**D7.** Команда на 50 хостах выполняется 10 минут, хотя сама операция быстрая. Что настроить?

<details><summary>Ответ</summary>

Увеличить `forks` (`-f 30`), включить `pipelining` и `ControlPersist`,
не собирать факты без надобности (в ad-hoc они и так не собираются).

</details>

**D8.** `ansible all -m raw -a "apt install -y python3"` — коллега спрашивает, зачем `raw`,
если есть модуль `apt`. Объясни.

<details><summary>Ответ</summary>

Модуль `apt` — это python-код, который должен выполниться на хосте. Если python
на хосте нет, ни один обычный модуль не отработает; `raw` — единственный способ выполнить
команду и поставить python.

</details>

**D9.** После ad-hoc `service restart` на всех хостах сайт лёг целиком. Что стоило сделать
иначе (два варианта)?

<details><summary>Ответ</summary>

(1) Применять волнами: `--limit` по частям (аналог `serial` в плейбуке);
(2) использовать `reload` вместо `restart` там, где сервис это поддерживает;
плюс проверка health после каждой волны.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое ad-hoc команды в Ansible?

<details><summary>Ответ</summary>

Разовые команды без плейбука: `ansible <хосты> -m <модуль> -a "<аргументы>"`.
Годятся для диагностики и срочных операций.

</details>

**2.** В чём разница между `command` и `shell`?

<details><summary>Ответ</summary>

`command` — без шелла (нет пайпов, редиректов, переменных), `shell` — через `/bin/sh -c`.

</details>

**3.** Когда используют `raw`?

<details><summary>Ответ</summary>

Когда на хосте нет python (bootstrap) или это устройство без нормального окружения.

</details>

**4.** Как выполнить команду от root?

<details><summary>Ответ</summary>

Флаг `-b` (`--become`), при необходимости `-K` для пароля sudo.

</details>

**5.** Как посмотреть факты хоста?

<details><summary>Ответ</summary>

`ansible <host> -m setup`, с фильтром `-a "filter=..."`.

</details>

**6.** Чем ad-hoc хуже плейбука?

<details><summary>Ответ</summary>

Не версионируется, не воспроизводится, нет идемпотентной логики, handler'ов, ревью
и истории изменений.

</details>

**7.** Как забрать файлы с удалённых серверов?

<details><summary>Ответ</summary>

Модулем `fetch`.

</details>

**8.** Как ограничить выполнение одним хостом?

<details><summary>Ответ</summary>

`--limit <host>` или указанием хоста вместо группы.

</details>

**9.** Что такое `forks`?

<details><summary>Ответ</summary>

Количество хостов, обрабатываемых параллельно (по умолчанию 5).

</details>

**10.** Как выполнить долгую задачу, не дожидаясь её завершения?

<details><summary>Ответ</summary>

Асинхронный запуск: `-B <таймаут> -P 0` (в плейбуке — `async`/`poll`).

</details>

---

### 🎯 Чек-лист

- [ ] Свободно пишу `ansible <паттерн> -m <модуль> -a "..."`
- [ ] Понимаю разницу `command` / `shell` / `raw` / `script`
- [ ] Знаю, когда нужны одинарные кавычки, и почему
- [ ] Умею собирать факты с фильтром и читать `-o`
- [ ] Ставил пакет, управлял сервисом, копировал и забирал файлы ad-hoc'ом
- [ ] Проверял идемпотентность `shell` vs `lineinfile`
- [ ] Пробовал `-C --diff` и знаю, что `command` в check mode пропускается
- [ ] Замерил влияние `forks`
- [ ] Перенёс рабочую ad-hoc последовательность в плейбук
