---
title: "02. Установка, подключение по SSH, become, ansible.cfg"
description: "Установка Ansible, SSH-ключи, повышение привилегий, порядок поиска ansible.cfg, диагностика UNREACHABLE"
---

# 02. Установка, подключение по SSH, `become`, `ansible.cfg`

> Роадмап → 5. Ansible → Фундамент → **«Подключение — SSH по ключам»**.
> **После темы ты умеешь:** установить Ansible, настроить доступ по ключу, повышать права
> через `become`, понимать `ansible.cfg` и чинить `UNREACHABLE`.

---

## 🗺️ Карта темы

```text:no-line-numbers
 ┌──────────────── control node ─────────────────┐
 │ pipx install ansible                          │
 │ ~/.ssh/ansible_key  (приватный ключ)          │
 │ ansible.cfg  ← настройки по умолчанию         │
 │ inventory    ← кто, под кем, на каком порту   │
 └───────────────────────┬───────────────────────┘
                         │ SSH (ansible_user, ключ)
                         ▼
 ┌──────────────── managed node ─────────────────┐
 │ authorized_keys содержит публичный ключ       │
 │ python3 установлен                            │
 │ пользователь в sudoers (лучше NOPASSWD)       │
 │        become: true  →  выполнение от root    │
 └───────────────────────────────────────────────┘
```

---

## 1. Установка Ansible (только на control node)

```bash
# Рекомендуемый способ — pipx (изолированное окружение, не ломает системный python)
sudo apt update && sudo apt install -y pipx
pipx ensurepath
pipx install --include-deps ansible        # ansible + коллекции
# или только ядро:
pipx install ansible-core

# Альтернативы
sudo apt install -y ansible                # из репозитория дистрибутива (часто старая версия)
python3 -m pip install --user ansible      # напрямую pip
```

```bash
ansible --version
# ansible [core 2.17.x]
#   config file = /home/user/ansible-lab/ansible.cfg     ← какой конфиг реально используется
#   configured module search path = [...]
#   python version = 3.12.x
```

> ⚠️ Версия на control node важна: синтаксис плейбуков и набор модулей привязаны к ней.
> В команде фиксируют версию (например, в `requirements.txt` или образе CI-раннера),
> иначе «у меня работает, а в пайплайне падает».

---

## 2. SSH-ключи — правильный способ подключения

```bash
# 1. Отдельный ключ для автоматизации (не твой личный!)
ssh-keygen -t ed25519 -f ~/.ssh/ansible_key -C "ansible" -N ""

# 2. Разложить публичную часть на хосты
ssh-copy-id -i ~/.ssh/ansible_key.pub devops@10.0.0.11
#   или вручную:
cat ~/.ssh/ansible_key.pub | ssh devops@10.0.0.11 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'

# 3. Проверить БЕЗ Ansible — это всегда первый шаг диагностики
ssh -i ~/.ssh/ansible_key devops@10.0.0.11 'hostname; id'

# 4. Ansible
ansible all -i inventory.ini -m ping
```

### Переменные подключения (в inventory или group_vars)

| Переменная | Что задаёт |
|------------|-----------|
| `ansible_host` | Реальный адрес (если имя в inventory — просто алиас) |
| `ansible_port` | Порт SSH (по умолчанию 22) |
| `ansible_user` | Пользователь для подключения |
| `ansible_ssh_private_key_file` | Приватный ключ |
| `ansible_ssh_common_args` | Доп. аргументы ssh (ProxyJump, StrictHostKeyChecking) |
| `ansible_connection` | `ssh` (по умолчанию), `local`, `docker`, `kubectl`, `winrm` |
| `ansible_python_interpreter` | Путь к python на целевом хосте |
| `ansible_become` / `ansible_become_user` / `ansible_become_method` | Повышение привилегий |
| `ansible_become_password` | Пароль sudo (только из vault!) |

```ini
[web]
web1 ansible_host=10.0.0.11
web2 ansible_host=10.0.0.12 ansible_port=2222

[all:vars]
ansible_user=devops
ansible_ssh_private_key_file=~/.ssh/ansible_key
ansible_python_interpreter=/usr/bin/python3
```

### Доступ через bastion (частый случай в проде)

```ini
[db:vars]
ansible_ssh_common_args='-o ProxyJump=devops@bastion.example.com'
```
или в `~/.ssh/config` (Ansible использует его автоматически):
```text:no-line-numbers
Host 10.0.1.*
    ProxyJump bastion
    User devops
    IdentityFile ~/.ssh/ansible_key
```

### Пароли вместо ключей (иногда неизбежно)

```bash
sudo apt install -y sshpass
ansible all -m ping --ask-pass            # спросит SSH-пароль
```
Это временное решение для первого подключения к новой машине; дальше — ключи.

---

## 3. `become` — повышение привилегий

```yaml
- name: Настройка веб-серверов
  hosts: web
  become: true                 # ⭐ все задачи play выполняются от root
  tasks:
    - name: Пакет nginx
      ansible.builtin.apt: { name: nginx, state: present }

    - name: Только эта задача — от пользователя postgres
      ansible.builtin.command: psql -c "SELECT 1"
      become: true
      become_user: postgres
```

```bash
ansible web -m apt -a "name=nginx state=present" -b        # -b = --become
ansible web -m command -a "whoami" -b --become-user=deploy
ansible web -m ping -b -K                                  # -K = спросить sudo-пароль
```

| Ключ | Смысл |
|------|-------|
| `become: true` | Повысить привилегии |
| `become_user: postgres` | До кого повышать (по умолчанию `root`) |
| `become_method: sudo` | `sudo` (по умолчанию), `su`, `doas`, `pbrun`, `runas` (Windows) |
| `become_flags` | Доп. флаги, например `-i` или `-H` |
| `-K` / `--ask-become-pass` | Спросить пароль sudo интерактивно |

**Правильная настройка на целевом хосте:**
```bash
# на managed node
sudo useradd -m -s /bin/bash devops
echo 'devops ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/devops
sudo chmod 440 /etc/sudoers.d/devops
sudo visudo -c                                   # проверка синтаксиса
```

> ⚠️ **Не подключайся напрямую под root.** Правильно: отдельный пользователь
> (`devops`/`ansible`) + ключ + `become`. Так видно в логах, кто что делал,
> и root-логин остаётся выключенным (`PermitRootLogin no`).

> 💡 Где `become` подводит: `become_user` из-под непривилегированного пользователя
> в другого непривилегированного ломается на правах к временным файлам.
> Лечится `ansible.cfg` → `allow_world_readable_tmpfiles=True` (компромисс)
> либо использованием `become: true` (root) + `become_user`.

---

## 4. `ansible.cfg` — конфиг проекта

Порядок поиска (**побеждает первый найденный, они НЕ складываются!**):

```text:no-line-numbers
1. $ANSIBLE_CONFIG              (переменная окружения — путь к файлу)
2. ./ansible.cfg                (в ТЕКУЩЕМ каталоге)  ← так делают в проектах
3. ~/.ansible.cfg
4. /etc/ansible/ansible.cfg
```

> ⚠️ Два важных нюанса:
> 1. Конфиги **не мержатся** — используется ровно один файл.
> 2. `ansible.cfg` из каталога, доступного на запись всем (world-writable), **игнорируется**
>    из соображений безопасности. Классическая ловушка с шаренными каталогами.
> Проверить, какой конфиг применяется: `ansible --version` (строка `config file`).

### Боевой минимум для учебного/рабочего проекта

```ini
[defaults]
inventory = ./inventories/dev/hosts.ini
remote_user = devops
private_key_file = ~/.ssh/ansible_key
host_key_checking = False           ; ⚠️ только для лабы! в проде — known_hosts
retry_files_enabled = False
forks = 20                          ; сколько хостов параллельно (по умолчанию 5)
stdout_callback = yaml              ; человекочитаемый вывод
callbacks_enabled = timer, profile_tasks
interpreter_python = auto_silent
roles_path = ./roles
collections_path = ./collections
deprecation_warnings = False
nocows = 1

[privilege_escalation]
become = True
become_method = sudo
become_user = root
become_ask_pass = False

[ssh_connection]
pipelining = True                   ; ⭐ заметно ускоряет (нужен !requiretty в sudoers)
ssh_args = -o ControlMaster=auto -o ControlPersist=60s -o PreferredAuthentications=publickey
control_path = /tmp/ansible-ssh-%%h-%%p-%%r
```

Любую настройку можно задать переменной окружения:
```bash
ANSIBLE_STDOUT_CALLBACK=yaml ANSIBLE_FORKS=50 ansible-playbook site.yml
ansible-config dump --only-changed      # что отличается от дефолтов
ansible-config list | head -40          # все параметры с описанием
```

---

## 5. Структура рабочего каталога (минимум с первого дня)

```text:no-line-numbers
ansible-lab/
├── ansible.cfg
├── inventories/
│   ├── dev/
│   │   ├── hosts.ini
│   │   ├── group_vars/
│   │   └── host_vars/
│   └── prod/
│       └── hosts.ini
├── roles/
├── playbooks/
│   └── site.yml
└── requirements.yml
```
Подробнее — тема 13. Но привычку «ansible.cfg рядом с inventory» заводи сразу:
она избавляет от `-i` в каждой команде.

---

## 6. Первое подключение и host key

При первом SSH-соединении сервер предъявляет свой ключ, и он должен попасть в `known_hosts`.
Три варианта:

```bash
# 1. ПРАВИЛЬНО: заранее собрать ключи хостов
ssh-keyscan -H 10.0.0.11 10.0.0.12 >> ~/.ssh/known_hosts

# 2. Компромисс: принимать при первом подключении (новые хосты — ок, подмена — заметна)
export ANSIBLE_HOST_KEY_CHECKING=False          # или ansible.cfg
# либо мягче:
ansible_ssh_common_args='-o StrictHostKeyChecking=accept-new'

# 3. Для эфемерных хостов (CI, контейнеры) — UserKnownHostsFile=/dev/null
```

> ⚠️ `host_key_checking = False` в проде — это отключение защиты от MITM.
> В лабе — норма, в проде — `ssh-keyscan` в процессе подготовки хоста.

---

## 7. 🔧 Диагностика подключения (алгоритм)

```text:no-line-numbers
ansible all -m ping   →   UNREACHABLE?
        │
        ├─ 1. Проверь ЧИСТЫМ ssh:  ssh -i ключ -p порт user@host -v
        │      Не работает ssh → проблема не в Ansible (сеть/sshd/ключ/firewall)
        │
        ├─ 2. Верный ли адрес/порт?  ansible-inventory --host web1
        │
        ├─ 3. Тот ли пользователь?   ansible_user / remote_user / -u
        │
        ├─ 4. Тот ли ключ?           ansible_ssh_private_key_file / ssh-add -l
        │
        ├─ 5. Права на хосте:        ~/.ssh 700, authorized_keys 600, владелец — тот же юзер
        │
        ├─ 6. Host key:              known_hosts / accept-new
        │
        └─ 7. Подробности:           ansible all -m ping -vvvv   (видна точная команда ssh)
```

Типовые ошибки и причины:

| Сообщение | Причина |
|-----------|---------|
| `Permission denied (publickey,password)` | Не тот пользователь/ключ, ключ не в `authorized_keys`, кривые права |
| `Host key verification failed` | Хоста нет в `known_hosts` (или ключ сменился — переустановка хоста) |
| `Connection timed out` | Firewall/Security Group, не тот IP, хост выключен |
| `/usr/bin/python3: not found` | На хосте нет python — ставить через `raw` или менять интерпретатор |
| `Missing sudo password` | Нужен `-K` или NOPASSWD в sudoers |
| `sudo: a password is required` | То же + проверь, что пользователь вообще в sudoers |
| `Failed to connect to the host via ssh: ... Too many authentication failures` | ssh-agent подсовывает много ключей — укажи `IdentitiesOnly=yes` |

```bash
# Полезные команды диагностики
ansible all -m ping -vvvv 2>&1 | grep "SSH: EXEC"     # какую ssh-команду реально запускает
ansible-inventory -i inventory.ini --list             # как Ansible видит хосты и переменные
ansible all -m setup -a "filter=ansible_python*"      # какой python нашёлся
ansible --version                                     # какой конфиг используется
```

---

## 8. Windows и локальный хост (коротко, для полноты)

```yaml
# Локальная машина — без SSH
- hosts: localhost
  connection: local
  gather_facts: false
  tasks:
    - ansible.builtin.debug: { msg: "Выполняюсь прямо здесь" }
```
```ini
# Windows: WinRM вместо SSH
[windows:vars]
ansible_connection=winrm
ansible_winrm_transport=ntlm
ansible_port=5985
```
В DevOps-практике Windows-хосты встречаются редко, но знать о существовании
`ansible_connection` полезно: он же используется для `docker`, `podman`, `kubectl`.

---

## 💼 Как это в DevOps

- Для автоматизации всегда заводят **отдельного пользователя и отдельный ключ**
  (`ansible`/`deploy`), с NOPASSWD только на нужные команды, если политика строгая.
- Приватный ключ в CI лежит в защищённой переменной типа **File** (блок CI/CD, тема 06)
  и никогда не коммитится.
- `ansible.cfg` лежит в репозитории рядом с inventory — тогда у всей команды и у пайплайна
  одинаковое поведение.
- `pipelining = True` и `forks` — первое, что крутят, когда «ансибл медленный».
- 90% проблем новичка — это не Ansible, а SSH. Отсюда правило: **сначала проверь чистым ssh**.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Поставить Ansible | `pipx install --include-deps ansible` |
| Сгенерировать ключ | `ssh-keygen -t ed25519 -f ~/.ssh/ansible_key -N ""` |
| Разложить ключ | `ssh-copy-id -i ~/.ssh/ansible_key.pub user@host` |
| Проверить связь | `ansible all -m ping` |
| Выполнить от root | добавить `-b` (`become: true`) |
| Спросить sudo-пароль | `-K` |
| Спросить SSH-пароль | `--ask-pass` (нужен sshpass) |
| Другой пользователь | `-u username` |
| Другой ключ | `--private-key ~/.ssh/other` |
| Посмотреть, какой конфиг применяется | `ansible --version` |
| Изменённые настройки конфига | `ansible-config dump --only-changed` |
| Через бастион | `ansible_ssh_common_args='-o ProxyJump=user@bastion'` |
| Максимальная отладка | `-vvvv` |
| Ускорить | `pipelining = True`, `forks = 20` |

---

## 🧠 Что запомнить

1. Ansible ставится **только на control node**; на хостах — SSH, python3, sudo.
2. Подключение — **по ключам**, отдельным ключом для автоматизации, под отдельным пользователем.
3. Не логинься под root: `become: true` + sudo NOPASSWD для пользователя автоматизации.
4. `-b` = become, `-K` = спросить sudo-пароль, `--ask-pass` = спросить SSH-пароль.
5. `ansible.cfg` ищется в порядке `ANSIBLE_CONFIG` → `./ansible.cfg` → `~/.ansible.cfg` →
   `/etc/ansible/ansible.cfg`, **файлы не складываются**, world-writable каталог игнорируется.
6. `ansible --version` показывает, какой конфиг реально используется, — проверяй это первым.
7. `host_key_checking=False` допустим в лабе; в проде — `ssh-keyscan` или `accept-new`.
8. Любая проблема подключения сначала воспроизводится **чистым `ssh -v`**.
9. `-vvvv` показывает точную ssh-команду — главный инструмент отладки `UNREACHABLE`.
10. `pipelining = True` и `forks` — базовое ускорение (требует отсутствия `requiretty`).

---

## Задачи

> Стенд: 3 хоста с SSH + управляющая машина с установленным Ansible.

---

### Блок A. Теория

**A1.** Где нужно устанавливать Ansible и где НЕ нужно? Почему?

<details><summary>Ответ</summary>

Только на control node (ноутбук, bastion, CI-раннер). На целевых хостах Ansible
не нужен — они управляются по SSH, агент не ставится.

</details>

**A2.** Перечисли требования к целевому хосту для работы Ansible.

<details><summary>Ответ</summary>

SSH-доступ, Python 3, достаточные права (обычно sudo). Для Windows — WinRM вместо SSH.

</details>

**A3.** Зачем для автоматизации заводят отдельный SSH-ключ и отдельного пользователя?

<details><summary>Ответ</summary>

Чтобы ограничить радиус поражения и разделить ответственность: ключ автоматизации
можно отозвать отдельно, он не привязан к человеку, его можно ограничить в `authorized_keys`
(`from=`, `command=`), а действия автоматизации видны в логах отдельно от действий людей.

</details>

**A4.** Что делают переменные `ansible_host`, `ansible_port`, `ansible_user`,
`ansible_ssh_private_key_file`?

<details><summary>Ответ</summary>

`ansible_host` — реальный адрес хоста; `ansible_port` — SSH-порт; `ansible_user` —
пользователь подключения; `ansible_ssh_private_key_file` — приватный ключ для этого хоста.

</details>

**A5.** В чём разница между именем хоста в inventory и `ansible_host`?

<details><summary>Ответ</summary>

Имя в inventory — это **алиас** (метка), по нему хост адресуется в плейбуках
и `host_vars`. Реальное подключение идёт по `ansible_host`; если он не задан — по имени
(значит, имя должно резолвиться в DNS/hosts).

</details>

**A6.** Что такое `become`? Чем `become_user` отличается от `remote_user`?

<details><summary>Ответ</summary>

`become` — повышение привилегий на целевом хосте (обычно sudo до root).
`remote_user` — под кем **подключаемся по SSH**; `become_user` — в кого **переключаемся**
после подключения.

</details>

**A7.** Чем отличаются флаги `-b`, `-K`, `--ask-pass`, `-u`?

<details><summary>Ответ</summary>

`-b` — become (выполнять от root); `-K` — спросить пароль sudo;
`--ask-pass` — спросить пароль SSH; `-u` — задать пользователя подключения.

</details>

**A8.** Почему не рекомендуется подключаться напрямую под root?

<details><summary>Ответ</summary>

Root-логин по SSH обычно выключен политикой; под root теряется персонализация
действий в логах; любая ошибка в плейбуке выполняется с максимальными правами.
Правильно: непривилегированный пользователь + `become`.

</details>

**A9.** ⭐ Перечисли порядок поиска `ansible.cfg`. Складываются ли найденные файлы?

<details><summary>Ответ</summary>

`$ANSIBLE_CONFIG` → `./ansible.cfg` → `~/.ansible.cfg` → `/etc/ansible/ansible.cfg`.
**Не складываются**: применяется первый найденный целиком.

</details>

**A10.** Почему `ansible.cfg` может быть «проигнорирован», хотя он лежит в текущем каталоге?

<details><summary>Ответ</summary>

Если каталог world-writable (права 777), Ansible игнорирует лежащий в нём
`ansible.cfg` из соображений безопасности — иначе любой пользователь системы мог бы
подменить настройки выполнения.

</details>

**A11.** Как узнать, какой конфиг реально используется прямо сейчас?

<details><summary>Ответ</summary>

`ansible --version` — строка `config file`.

</details>

**A12.** Что делает `host_key_checking = False` и чем это опасно?

<details><summary>Ответ</summary>

Отключает проверку ключа хоста в `known_hosts`: удобно для эфемерных хостов,
но снимает защиту от подмены сервера (MITM). В проде используют `ssh-keyscan`
или `StrictHostKeyChecking=accept-new`.

</details>

**A13.** Что делает `pipelining = True` и какое требование к sudoers с ним связано?

<details><summary>Ответ</summary>

Уменьшает число SSH-операций на задачу (модуль передаётся в уже открытую сессию,
без отдельной записи файла). Требует, чтобы в sudoers не было `requiretty`.

</details>

**A14.** Что задаёт `forks` и как понять, что его пора увеличить?

<details><summary>Ответ</summary>

Число хостов, обрабатываемых параллельно (по умолчанию 5). Увеличивать,
когда хостов много и прогон долгий; ограничение — ресурсы control node и нагрузка на сеть.

</details>

**A15.** Как подключиться к хостам через bastion? Два способа.

<details><summary>Ответ</summary>

(1) `ansible_ssh_common_args='-o ProxyJump=user@bastion'` в inventory/group_vars;
(2) настройка `ProxyJump`/`ProxyCommand` в `~/.ssh/config` — Ansible использует его сам.

</details>

**A16.** Что такое `ansible_connection` и какие значения ты знаешь?

<details><summary>Ответ</summary>

Плагин транспорта: `ssh` (по умолчанию), `local`, `docker`, `podman`, `kubectl`,
`winrm`, `network_cli`. Позволяет управлять не только «обычными» серверами.

</details>

**A17.** Как заставить play выполняться на самой управляющей машине?

<details><summary>Ответ</summary>

`hosts: localhost` + `connection: local` (и обычно `gather_facts: false`),
либо `delegate_to: localhost` для отдельной задачи.

</details>

**A18.** Зачем `ansible_python_interpreter` и что такое `auto_silent`?

<details><summary>Ответ</summary>

Задаёт путь к python на целевом хосте. `auto_silent` — автоопределение интерпретатора
без предупреждений (рекомендуемое значение для смешанного парка ОС).

</details>

---

### Блок B. «Что делает команда/конфиг»

```bash
B1.  ssh-keygen -t ed25519 -f ~/.ssh/ansible_key -N "" -C "ansible"
B2.  ssh-copy-id -i ~/.ssh/ansible_key.pub devops@10.0.0.11
B3.  ansible all -m ping -vvvv
B4.  ansible web -m command -a "whoami" -b
B5.  ansible web -m ping -u root --private-key ~/.ssh/other
B6.  ansible-config dump --only-changed
B7.  ansible-inventory -i inventory.ini --list
B8.  ssh-keyscan -H 10.0.0.11 >> ~/.ssh/known_hosts
B9.  ANSIBLE_STDOUT_CALLBACK=yaml ansible-playbook site.yml
B10. ansible all -m setup -a "filter=ansible_python*"
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Создать ed25519-ключ без парольной фразы с комментарием "ansible"
B2.  Скопировать публичный ключ в authorized_keys пользователя devops на хосте
B3.  Пропинговать все хосты с максимальной отладкой (видна ssh-команда и работа модуля)
B4.  Выполнить whoami на группе web от root (become)
B5.  Пропинговать web под пользователем root с указанным приватным ключом
B6.  Показать только те настройки, что отличаются от значений по умолчанию
B7.  Показать в JSON, как Ansible видит инвентарь: хосты, группы, переменные
B8.  Добавить ключ хоста в known_hosts заранее (без интерактивного подтверждения)
B9.  Запустить плейбук с человекочитаемым YAML-выводом (настройка через переменную окружения)
B10. Показать, какой python обнаружен на хостах
```

</details>

```ini
# B11
[defaults]
inventory = ./inventories/prod/hosts.ini
forks = 50
host_key_checking = False

[privilege_escalation]
become = True
```
Вопрос: что здесь хорошо, а что опасно для прод-окружения?

<details><summary>Ответ</summary>

Хорошо: явный inventory, `forks = 50` для скорости, `become = True` как дефолт.
Опасно: `host_key_checking = False` в проде — отключает защиту от MITM; и `become = True`
глобально означает, что **любая** задача пойдёт от root, включая те, где это не нужно.

</details>

```ini
# B12
[ssh_connection]
pipelining = True
ssh_args = -o ControlMaster=auto -o ControlPersist=60s
```
Вопрос: зачем это и что даст на 50 хостах?

<details><summary>Ответ</summary>

`pipelining` уменьшает количество SSH-операций на задачу, `ControlMaster/ControlPersist`
переиспользуют TCP-соединение между задачами. На 50 хостах это часто ускоряет прогон в разы.

</details>

```ini
# B13
[web]
web1 ansible_host=10.0.0.11 ansible_port=2222 ansible_user=ubuntu
```
Вопрос: по какому адресу, порту и под кем подключится Ansible к хосту `web1`?

<details><summary>Ответ</summary>

Подключится на `10.0.0.11:2222` под пользователем `ubuntu`; имя `web1` — только алиас
для плейбуков и `host_vars`.

</details>

---

### Блок C. Практика

#### C1. 🔑 Ключи и первый ping

1. Сгенерируй `~/.ssh/ansible_key` **без пароля**.
2. Разложи публичную часть на все три хоста.
3. Проверь чистым ssh, что вход без пароля работает.
4. Напиши `inventory.ini` и добейся `ansible all -m ping` → `SUCCESS` со всех.

#### C2. Ломаем и чиним подключение

Проведи четыре эксперимента, каждый раз фиксируя **текст ошибки**:
1. укажи неверный `ansible_user`;
2. укажи неверный путь к ключу;
3. поставь на хосте `chmod 777 ~/.ssh/authorized_keys`;
4. укажи неверный `ansible_port`.
Для каждого случая: какая ошибка и как ты понял причину?

<details><summary>Ответ</summary>

(1) `Permission denied (publickey)`; (2) `Permission denied` либо
`Could not open private key file`; (3) sshd отказывает из-за небезопасных прав —
в `-vvvv`/логах хоста видно `Authentication refused: bad ownership or modes`;
(4) `Connection refused`/`timed out`.

</details>

#### C3. `become` на практике

```bash
ansible web -m command -a "whoami"
ansible web -m command -a "whoami" -b
ansible web -m command -a "whoami" -b --become-user=nobody
```
Объясни каждый результат. Затем убери NOPASSWD из sudoers на одном хосте
и повтори — что изменится и как заставить работать?

<details><summary>Ответ</summary>

Без `-b` — `devops`; с `-b` — `root`; с `--become-user=nobody` — `nobody`.
Без NOPASSWD появится `Missing sudo password`; лечится `-K` интерактивно или
`ansible_become_password` из vault для автоматики.

</details>

#### C4. 🔑 Свой `ansible.cfg`

Создай в каталоге проекта `ansible.cfg` с: `inventory`, `remote_user`, `private_key_file`,
`host_key_checking=False`, `stdout_callback=yaml`, `become=True`.
Проверь, что теперь работает просто `ansible all -m ping` (без `-i` и `-u`).
Убедись через `ansible --version`, что применяется именно твой файл.

#### C5. Приоритет конфигов

1. Создай `~/.ansible.cfg` с `forks = 3`.
2. В проекте оставь `ansible.cfg` с `forks = 10`.
3. Выполни `ansible-config dump --only-changed` в проекте и вне его.
4. Затем `ANSIBLE_CONFIG=~/.ansible.cfg ansible-config dump --only-changed`.
Сделай вывод о приоритете и о том, мержатся ли конфиги.

<details><summary>Ответ</summary>

Побеждает `./ansible.cfg` в текущем каталоге; вне проекта применяется `~/.ansible.cfg`;
с `ANSIBLE_CONFIG` — указанный файл. Значения из разных файлов **не смешиваются**.

</details>

#### C6. World-writable ловушка

```bash
chmod 777 .              # каталог проекта
ansible --version        # смотри строку config file
chmod 755 .
ansible --version
```
Что изменилось и почему так сделано?

<details><summary>Ответ</summary>

При правах 777 строка `config file` меняется на другой конфиг (или `None`) —
проектный игнорируется как небезопасный.

</details>

#### C7. Замер pipelining

```bash
time ansible all -m command -a "echo test"
# включи pipelining = True в ansible.cfg
time ansible all -m command -a "echo test"
```
Зафиксируй разницу. Затем запусти плейбук из 5 задач и сравни ещё раз.

<details><summary>Ответ</summary>

Разница растёт с числом задач и хостов: на одной ad-hoc команде почти незаметна,
на плейбуке из 5+ задач — уже существенна.

</details>

#### C8. `-vvvv` как рентген

Запусти `ansible node1 -m ping -vvvv` и найди в выводе:
1. полную команду `ssh`;
2. путь временного каталога модуля;
3. строку запуска python;
4. итоговый JSON.
Выпиши их.

<details><summary>Ответ</summary>

В выводе видно строку `ssh -vvv -o ControlMaster=... -o Port=... -o User=...`,
затем `PUT /root/.ansible/tmp/... TO /home/devops/.ansible/tmp/ansible-tmp-*/AnsiballZ_ping.py`,
затем `EXEC /bin/sh -c '/usr/bin/python3 .../AnsiballZ_ping.py && sleep 0'`, затем JSON
с `"ping": "pong"`.

</details>

#### C9. Локальный play

Напиши плейбук на `hosts: localhost`, `connection: local`, который выводит
`ansible_hostname` и текущего пользователя. Запусти без inventory.

#### C10. Подключение к контейнеру без SSH (со звёздочкой)

```bash
ansible -i localhost, all -c local -m ping
ansible all -i "node1," -c docker -m ping      # требуется community.docker
```
Объясни, что такое connection-плагин и когда это нужно.

<details><summary>Ответ</summary>

Connection-плагин определяет, **как** доставлять и выполнять модули: по SSH,
локально, через `docker exec`, через `kubectl exec`. Нужно, когда до цели нет SSH
(контейнеры, поды) или он не нужен (localhost).

</details>

---

### Блок D. Инциденты

**D1.** `UNREACHABLE! => Permission denied (publickey)`, при этом `ssh -i key user@host`
из терминала работает. Назови три возможные причины.

<details><summary>Ответ</summary>

(1) Ansible подключается под другим пользователем (`remote_user` из cfg/inventory);
(2) используется другой ключ (в терминале сработал ssh-agent, а Ansible взял иной файл);
(3) другой хост/порт из-за `ansible_host`/`ansible_port`. Проверка: `-vvvv` и сравнение
реальной ssh-команды с той, что ты запускал руками.

</details>

**D2.** `Host key verification failed` после пересоздания виртуалки с тем же IP. Что произошло
и как правильно починить?

<details><summary>Ответ</summary>

Изменился host key, а в `known_hosts` осталась старая запись — защита от MITM
сработала штатно. Починить: `ssh-keygen -R <host>` и заново `ssh-keyscan -H <host> >>
~/.ssh/known_hosts` (не отключать проверку глобально).

</details>

**D3.** `Missing sudo password` при запуске плейбука из CI-пайплайна (неинтерактивно).
Два решения, какое правильнее?

<details><summary>Ответ</summary>

(1) NOPASSWD в sudoers для пользователя автоматизации — предпочтительно;
(2) `ansible_become_password` из ansible-vault/CI-переменной. Пароль в открытом виде
в репозитории — недопустимо.

</details>

**D4.** Плейбук работает у тебя и падает у коллеги с другим поведением — оказалось,
используются разные настройки. Как за 10 секунд выяснить причину?

<details><summary>Ответ</summary>

`ansible --version` (какой config file) и `ansible-config dump --only-changed`
у обоих — сразу видно расхождение настроек.

</details>

**D5.** После включения `pipelining = True` задачи начали падать с `sudo: sorry, you must have
a tty to run sudo`. Причина и лечение?

<details><summary>Ответ</summary>

В sudoers включён `requiretty`, несовместимый с pipelining. Лечение: убрать
`Defaults requiretty` (или `Defaults:devops !requiretty`), либо выключить pipelining.

</details>

**D6.** `Too many authentication failures` при подключении к части хостов. Причина?

<details><summary>Ответ</summary>

ssh-agent предлагает серверу слишком много ключей, и лимит попыток исчерпывается
до нужного. Лечение: `-o IdentitiesOnly=yes` в `ansible_ssh_common_args` + явный
`ansible_ssh_private_key_file`.

</details>

**D7.** На новом хосте `ping` даёт `/usr/bin/python3: not found`. Напиши play,
который это чинит.

<details><summary>Ответ</summary>

```yaml
- hosts: new
  gather_facts: false
  become: true
  tasks:
    - name: Поставить python3 без модулей (raw)
      ansible.builtin.raw: test -e /usr/bin/python3 || (apt-get update && apt-get install -y python3)
      changed_when: false
    - name: Теперь можно собирать факты
      ansible.builtin.setup:
```

</details>

**D8.** Ansible «подвисает» на 30 секунд на каждом хосте и затем `Connection timed out`.
Что проверить (три шага)?

<details><summary>Ответ</summary>

(1) Сетевую доступность порта (`nc -zv host 22`, security group/firewall);
(2) правильность `ansible_host`/`ansible_port` (`ansible-inventory --host`);
(3) жив ли sshd на хосте и не блокирует ли fail2ban твой IP.

</details>

**D9.** Ключ `~/.ssh/ansible_key` случайно закоммитили в репозиторий. Порядок действий?

<details><summary>Ответ</summary>

Считать ключ скомпрометированным: удалить его публичную часть из `authorized_keys`
на всех хостах, сгенерировать новый, разложить, обновить секрет в CI, затем чистить историю
git (`git filter-repo`/BFG) и форс-пушить, предупредив команду. Порядок важен: сначала
отзыв доступа, потом уборка истории.

</details>

**D10.** Инженер прописал `ansible_become_password` открытым текстом в `group_vars/all.yml`,
который лежит в git. Что не так и как правильно?

<details><summary>Ответ</summary>

Пароль sudo в открытом виде в git = утечка доступа к root на всех хостах.
Правильно: `ansible-vault` (или секрет из CI/Vault), файл с шифротекстом в git,
пароль от vault — вне репозитория; плюс `no_log: true` на задачах с секретами.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что нужно на целевом хосте, чтобы Ansible мог им управлять?

<details><summary>Ответ</summary>

SSH-доступ, Python 3, права (sudo). Агент не нужен.

</details>

**2.** Как Ansible аутентифицируется на хостах?

<details><summary>Ответ</summary>

Обычно по SSH-ключу от выделенного пользователя автоматизации; пароли — временный вариант
(`--ask-pass` + sshpass).

</details>

**3.** Что такое `become` и как его настраивают?

<details><summary>Ответ</summary>

Механизм повышения привилегий на целевом хосте (`become: true`, `become_user`,
`become_method`). Настраивается через sudoers, желательно NOPASSWD для пользователя
автоматизации.

</details>

**4.** Где лежит `ansible.cfg` и в каком порядке он ищется?

<details><summary>Ответ</summary>

`ANSIBLE_CONFIG` → `./ansible.cfg` → `~/.ansible.cfg` → `/etc/ansible/ansible.cfg`;
применяется первый найденный, файлы не мержатся.

</details>

**5.** Как ускорить Ansible?

<details><summary>Ответ</summary>

`forks`, `pipelining`, `ControlPersist`, отключение лишнего сбора фактов
(`gather_facts: false`/`gather_subset`), кэш фактов, стратегия `free`, меньше задач
`command`/`shell`, `async` для долгих операций.

</details>

**6.** Как подключиться к серверам за бастионом?

<details><summary>Ответ</summary>

`ProxyJump` через `ansible_ssh_common_args` или `~/.ssh/config`.

</details>

**7.** Как ты организуешь доступ Ansible к прод-серверам с точки зрения безопасности?

<details><summary>Ответ</summary>

Отдельный пользователь и ключ, доступ только с bastion/раннера, NOPASSWD ограниченно,
ключ в защищённой CI-переменной (тип File), прод-инвентарь отдельно, изменения —
через MR и `--check`, логирование прогонов.

</details>

**8.** Что делать, если на хосте нет Python?

<details><summary>Ответ</summary>

Поставить python через модуль `raw` в отдельном play с `gather_facts: false`,
либо указать другой интерпретатор через `ansible_python_interpreter`.

</details>

**9.** Как запустить задачу на самой control node?

<details><summary>Ответ</summary>

`hosts: localhost` + `connection: local`, либо `delegate_to: localhost`.

</details>

**10.** Как хранить пароль sudo для автоматизации?

<details><summary>Ответ</summary>

В `ansible-vault` или внешнем секрет-хранилище; в идеале — NOPASSWD и пароль вообще
не нужен.

</details>

---

### 🎯 Чек-лист

- [ ] Ansible установлен, `ansible --version` показывает мой конфиг
- [ ] Отдельный ключ автоматизации разложен по хостам, вход без пароля работает
- [ ] `ansible all -m ping` отвечает без `-i` и `-u` (всё в `ansible.cfg`)
- [ ] Понимаю `become`, `-b`, `-K`, `--ask-pass`, `-u`
- [ ] Знаю порядок поиска `ansible.cfg` и что файлы не мержатся
- [ ] Проверил на практике ловушку с world-writable каталогом
- [ ] Включил `pipelining` и замерил разницу
- [ ] Умею читать `-vvvv` и находить реальную ssh-команду
- [ ] Прошёл алгоритм диагностики `UNREACHABLE` на сломанном подключении
