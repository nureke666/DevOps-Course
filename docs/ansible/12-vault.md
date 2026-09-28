---
title: "12. Ansible Vault — секреты в репозитории"
description: "Шифрование файлов и значений, vault-id для окружений, использование в плейбуках и CI, ограничения"
---

# 12. Ansible Vault — секреты в репозитории

> Роадмап → 5. Ansible → Роли → *«Дополнительно можно изучить ansible vault»*.
> **После темы ты умеешь:** хранить пароли и ключи в git в зашифрованном виде
> и подключать их в плейбуки и CI без утечек.

---

## 🗺️ Идея

```text:no-line-numbers
        БЕЗ vault                              С vault
 group_vars/prod/vault.yml            group_vars/prod/vault.yml
 db_password: SuperSecret123    →     $ANSIBLE_VAULT;1.1;AES256
        ▲                             62383966386437...
        │                                     ▲
   лежит в git открытым текстом        в git лежит шифротекст,
   = утечка при любом доступе          пароль — ВНЕ репозитория
                                       (файл вне git / CI-переменная / Vault)
```

Vault шифрует **файлы или отдельные значения** симметричным AES-256.
Ansible расшифровывает их в памяти в момент запуска — для плейбука это обычные переменные.

---

## 1. Базовые команды

```bash
# создать зашифрованный файл (откроет $EDITOR)
ansible-vault create group_vars/prod/vault.yml

# редактировать (расшифрует во временный файл, зашифрует после сохранения)
ansible-vault edit group_vars/prod/vault.yml

# посмотреть, не изменяя
ansible-vault view group_vars/prod/vault.yml

# зашифровать существующий файл
ansible-vault encrypt secrets.yml

# расшифровать НАВСЕГДА (осторожно!)
ansible-vault decrypt secrets.yml

# сменить пароль шифрования
ansible-vault rekey group_vars/prod/vault.yml

# зашифровать одно значение (для вставки в обычный YAML)
ansible-vault encrypt_string 'SuperSecret123' --name 'db_password'
```

Запуск плейбука с секретами:
```bash
ansible-playbook site.yml --ask-vault-pass                       # спросит пароль
ansible-playbook site.yml --vault-password-file ~/.vault_pass    # пароль из файла
ANSIBLE_VAULT_PASSWORD_FILE=~/.vault_pass ansible-playbook site.yml
```

```ini
# ansible.cfg — чтобы не писать каждый раз
[defaults]
vault_password_file = ~/.vault_pass
```
```bash
chmod 600 ~/.vault_pass
echo ".vault_pass" >> .gitignore      # ⭐ пароль НИКОГДА не в git
```

---

## 2. Два способа хранения

### A. Зашифрованный файл целиком (обычный выбор)

```text:no-line-numbers
inventories/prod/group_vars/all/
├── vars.yml          ← открытый текст: ссылки на секреты
└── vault.yml         ← зашифрован целиком
```

```yaml
# vault.yml (внутри, после расшифровки)
vault_db_password: SuperSecret123
vault_api_token: ghp_xxxxxxxxxxxx
```
```yaml
# vars.yml (в git открытым текстом)
db_password: "{{ vault_db_password }}"
api_token: "{{ vault_api_token }}"
```

> 💡 Это стандартный приём: в открытом файле видно, **какие** секреты используются
> и куда они идут, а значения лежат в зашифрованном файле. Так ревью остаётся осмысленным.

### B. Зашифрованная строка внутри обычного файла

```bash
ansible-vault encrypt_string 'SuperSecret123' --name 'db_password'
```
```yaml
# group_vars/prod.yml — файл обычный, зашифровано только значение
db_host: db1.example.com
db_user: app
db_password: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          62383966386437366236613...
          39333064363565626561...
```
Плюс: в diff видно, какие поля менялись. Минус: шумно при большом числе секретов.

---

## 3. Несколько паролей: `--vault-id`

Разные окружения — разные пароли (чтобы dev-инженер не расшифровал прод):

```bash
# зашифровать паролем с меткой prod
ansible-vault encrypt --vault-id prod@~/.vault_prod group_vars/prod/vault.yml
ansible-vault encrypt --vault-id dev@~/.vault_dev  group_vars/dev/vault.yml

# запуск: можно передать несколько
ansible-playbook site.yml --vault-id dev@~/.vault_dev --vault-id prod@prompt
```
`@prompt` — спросить интерактивно, `@~/путь` — файл, `@скрипт.py` — получить пароль
из внешнего источника (например, из HashiCorp Vault или менеджера паролей).

---

## 4. Использование в плейбуках

```yaml
- hosts: db
  become: true
  vars_files:
    - vars/vault.yml               # можно подключать зашифрованный файл напрямую
  tasks:
    - name: Пользователь БД
      community.postgresql.postgresql_user:
        name: app
        password: "{{ db_password }}"
      no_log: true                 # ⭐ ОБЯЗАТЕЛЬНО рядом с секретом

    - name: Конфиг с секретом
      ansible.builtin.template:
        src: env.j2
        dest: /opt/app/.env
        mode: "0600"               # ⭐ права только владельцу
        owner: app
      no_log: true
```

> ⚠️ Vault защищает секрет **в репозитории**, но не в выводе. Без `no_log: true`
> значение легко попадает в лог задачи (особенно при ошибке) и в артефакты CI.

Проверить, зашифрован ли файл:
```bash
head -1 group_vars/prod/vault.yml      # $ANSIBLE_VAULT;1.1;AES256 — зашифрован
grep -rl 'ANSIBLE_VAULT' .             # найти все зашифрованные файлы
```

---

## 5. Vault в CI/CD (как это делают по-настоящему)

```yaml
# .gitlab-ci.yml
deploy:prod:
  stage: deploy
  image: python:3.12-slim
  before_script:
    - pip install -q ansible-core
    - ansible-galaxy install -r requirements.yml
    - echo "$ANSIBLE_VAULT_PASSWORD" > /tmp/.vault_pass   # из CI/CD Variables (masked)
    - chmod 600 /tmp/.vault_pass
    - chmod 600 "$SSH_KEY"                                 # переменная типа File
  script:
    - ansible-playbook -i inventories/prod/ site.yml
        --vault-password-file /tmp/.vault_pass
        --private-key "$SSH_KEY"
  after_script:
    - rm -f /tmp/.vault_pass
  environment: { name: production }
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

Связь с блоком CI/CD (тема 06 там): пароль от vault — это **masked + protected**
переменная; SSH-ключ — переменная типа **File**. В репозитории нет ни того, ни другого.

---

## 6. Git-удобства

`ansible-vault` шифрует файл целиком, поэтому `git diff` бесполезен. Лечится
настройкой diff-драйвера:

```bash
# .gitattributes
echo '*vault.yml diff=ansible-vault merge=binary' >> .gitattributes

# ~/.gitconfig
git config --global diff.ansible-vault.textconv "ansible-vault view"
```
Теперь `git diff` покажет расшифрованное содержимое **локально** (у того, у кого есть пароль).

> ⚠️ Осторожно: расшифрованный diff может попасть в скроллбек терминала и в логи CI —
> в пайплайне такой драйвер не настраивают.

---

## 7. Чего vault НЕ делает (важно понимать ограничения)

| Ограничение | Последствие |
|-------------|-------------|
| Один пароль на файл/значение | Нет ролевого доступа «кто какой секрет видит» — только через `vault-id` по окружениям |
| Нет аудита | Неизвестно, кто и когда читал секрет |
| Нет ротации | Смена пароля = `rekey` вручную по всем файлам |
| Нет динамических секретов | В отличие от HashiCorp Vault, где выдаются временные креды |
| Секрет всё равно попадает на хост | В конфиге на сервере он лежит открытым текстом (защищай `mode: "0600"`) |
| Не спасает от утечки в лог | Нужен `no_log: true` |

**Когда перерастают ansible-vault:** большая команда, требования аудита, ротация ключей,
динамические доступы → HashiCorp Vault / AWS Secrets Manager / GCP Secret Manager,
а Ansible забирает секреты lookup-плагином:

```yaml
- name: Секрет из HashiCorp Vault
  ansible.builtin.debug:
    msg: "{{ lookup('community.hashi_vault.hashi_vault', 'secret=secret/data/app:password') }}"
```

---

## 8. Правила гигиены секретов

1. `~/.vault_pass` и любые файлы паролей — в `.gitignore`, права `600`.
2. Разные пароли для dev и prod (`--vault-id`).
3. `no_log: true` на всех задачах, где фигурирует секрет.
4. Файлы с секретами на хостах — `mode: "0600"` и правильный владелец.
5. Секрет нельзя «разшифровать обратно» из истории git: если он был закоммичен
   открытым текстом — **считай его скомпрометированным**, меняй сам секрет,
   а уже потом чисти историю.
6. Именуй переменные из vault с префиксом `vault_` — сразу видно, что это секрет
   и где он определён.
7. Не печатай секреты `debug`'ом, даже временно (лог остаётся в CI).

---

## 💼 Как это в DevOps

- Ansible-репозиторий почти всегда содержит `vault.yml` на окружение: пароли БД, токены
  реестра, ключи API, пароли мониторинга.
- Пароль от vault хранится в менеджере паролей команды + в CI/CD Variables;
  на ноутбуках — в файле с правами 600, который не в git.
- На ревью MR смотрят: не появилось ли открытых секретов, стоит ли `no_log`,
  правильные ли права у файлов с креденшелами.
- Инцидент «секрет в git» решается не `git revert`, а **ротацией самого секрета** —
  это стандартная процедура, которую полезно уметь описать на собесе.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Создать зашифрованный файл | `ansible-vault create f.yml` |
| Редактировать | `ansible-vault edit f.yml` |
| Посмотреть | `ansible-vault view f.yml` |
| Зашифровать существующий | `ansible-vault encrypt f.yml` |
| Расшифровать насовсем | `ansible-vault decrypt f.yml` |
| Сменить пароль | `ansible-vault rekey f.yml` |
| Зашифровать одно значение | `ansible-vault encrypt_string 'секрет' --name 'var'` |
| Запустить с паролем | `--ask-vault-pass` / `--vault-password-file ~/.vault_pass` |
| Разные пароли по окружениям | `--vault-id prod@~/.vault_prod` |
| Пароль по умолчанию | `vault_password_file` в `ansible.cfg` |
| Найти зашифрованные файлы | `grep -rl 'ANSIBLE_VAULT' .` |
| Скрыть секрет из вывода | `no_log: true` |
| Права на файл с секретом | `mode: "0600"` |
| Diff зашифрованных файлов | `.gitattributes` + `diff.ansible-vault.textconv` |

---

## 🧠 Что запомнить

1. Vault шифрует файлы (или отдельные значения) AES-256; расшифровка — в памяти при запуске.
2. Пароль от vault **никогда** не хранится в репозитории: файл вне git, CI-переменная,
   менеджер паролей.
3. Стандартная схема: `vault.yml` с `vault_*` значениями + открытый `vars.yml`,
   который на них ссылается.
4. `encrypt_string` шифрует одно значение — удобно, когда секретов немного.
5. `--vault-id` даёт разные пароли для разных окружений.
6. `vault_password_file` в `ansible.cfg` избавляет от ввода пароля каждый раз.
7. ⭐ Vault не заменяет `no_log: true`: без него секрет утечёт в лог.
8. Файлы с секретами на хостах — `mode: "0600"` и правильный владелец.
9. У vault нет аудита, ротации и ролевого доступа — для этого берут HashiCorp Vault
   и lookup-плагины.
10. Секрет, попавший в git открытым текстом, считается скомпрометированным:
    сначала ротация, потом чистка истории.

---

## Задачи

> ⚠️ Все упражнения — на учебных «секретах». Никогда не тренируйся на реальных паролях.

---

### Блок A. Теория

**A1.** Что такое Ansible Vault и какую задачу он решает?

<details><summary>Ответ</summary>

Встроенный механизм шифрования файлов и значений (AES-256), позволяющий держать
секреты в том же git-репозитории, что и код, но в зашифрованном виде.

</details>

**A2.** Что именно можно зашифровать: файл, значение, оба варианта?

<details><summary>Ответ</summary>

Оба: файл целиком (`encrypt`/`create`) и отдельное значение (`encrypt_string`).

</details>

**A3.** Где хранится пароль от vault и где его хранить нельзя?

<details><summary>Ответ</summary>

Хранится вне репозитория: файл с правами 600 на машине, CI/CD-переменная (masked),
менеджер паролей команды. Нельзя — в git, в чатах, в аргументах команды в истории shell.

</details>

**A4.** Опиши стандартную схему `vault.yml` + `vars.yml`. Зачем такое разделение?

<details><summary>Ответ</summary>

`vault.yml` содержит `vault_*` переменные с реальными значениями (зашифрован),
`vars.yml` — открытый файл, где обычные переменные ссылаются на `vault_*`. Так видно,
какие секреты используются и куда идут, при этом значения скрыты — ревью остаётся полезным.

</details>

**A5.** Чем `encrypt_string` удобнее шифрования файла целиком? А чем хуже?

<details><summary>Ответ</summary>

`encrypt_string` оставляет файл читаемым (видно структуру и что менялось в diff),
но при большом числе секретов файл превращается в простыню шифротекста.

</details>

**A6.** Что делает `ansible-vault rekey`?

<details><summary>Ответ</summary>

Меняет пароль шифрования файла (перешифровывает новым паролем).

</details>

**A7.** Зачем нужен `--vault-id` и как задать разные пароли для dev и prod?

<details><summary>Ответ</summary>

Позволяет использовать несколько паролей с метками: dev-инженер не может
расшифровать прод-секреты. Задаётся `--vault-id prod@~/.vault_prod` при шифровании и запуске.

</details>

**A8.** Как запустить плейбук с секретами тремя разными способами?

<details><summary>Ответ</summary>

`--ask-vault-pass`, `--vault-password-file <файл>`, переменная окружения
`ANSIBLE_VAULT_PASSWORD_FILE` (либо `vault_password_file` в `ansible.cfg`).

</details>

**A9.** Как проверить, зашифрован ли файл?

<details><summary>Ответ</summary>

Первая строка файла — `$ANSIBLE_VAULT;1.1;AES256`; массово — `grep -rl 'ANSIBLE_VAULT' .`.

</details>

**A10.** ⭐ Защищает ли vault от попадания секрета в лог? Что нужно дополнительно?

<details><summary>Ответ</summary>

Нет. Vault защищает секрет «на диске/в git», но в выводе задачи он может
появиться. Нужен `no_log: true` и аккуратность с `debug`.

</details>

**A11.** Какие права ставить на файл с секретами на целевом хосте и почему?

<details><summary>Ответ</summary>

`0600` (или `0640` с нужной группой) и владелец — сервисный пользователь:
иначе любой пользователь хоста прочитает пароль.

</details>

**A12.** Почему `git diff` бесполезен для vault-файлов и как это можно улучшить?

<details><summary>Ответ</summary>

Файл зашифрован целиком, diff показывает изменение шифротекста. Улучшается
настройкой `diff.ansible-vault.textconv` + `.gitattributes` (локально, не в CI).

</details>

**A13.** Назови четыре ограничения ansible-vault по сравнению с HashiCorp Vault.

<details><summary>Ответ</summary>

Нет ролевого доступа и аудита, нет автоматической ротации, нет динамических
(временных) секретов, один общий пароль на файл.

</details>

**A14.** Секрет был закоммичен открытым текстом и уже запушен. Каков правильный порядок
действий?

<details><summary>Ответ</summary>

Сначала **ротация** самого секрета (сменить пароль/токен везде, где он используется),
затем удаление из истории (`git filter-repo`/BFG) и форс-пуш, затем уведомление команды
и проверка, не утёк ли он дальше (логи, артефакты, форки).

</details>

**A15.** Зачем именовать переменные из vault с префиксом `vault_`?

<details><summary>Ответ</summary>

Чтобы сразу отличать секретные переменные от обычных и понимать, что они приходят
из зашифрованного файла; это упрощает ревью и поиск.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  ansible-vault create group_vars/prod/vault.yml
B2.  ansible-vault view group_vars/prod/vault.yml
B3.  ansible-vault edit group_vars/prod/vault.yml
B4.  ansible-vault encrypt_string 'p@ssw0rd' --name 'db_password'
B5.  ansible-vault rekey group_vars/prod/vault.yml
B6.  ansible-vault decrypt secrets.yml
B7.  ansible-playbook site.yml --vault-password-file ~/.vault_pass
B8.  ansible-playbook site.yml --vault-id prod@prompt
B9.  grep -rl 'ANSIBLE_VAULT' .
B10. ANSIBLE_VAULT_PASSWORD_FILE=~/.vault_pass ansible-playbook site.yml
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Создать новый зашифрованный файл (откроется редактор)
B2.  Показать расшифрованное содержимое, не изменяя файл
B3.  Открыть для редактирования с последующим перешифрованием
B4.  Зашифровать одно значение и вывести готовый YAML-блок для вставки
B5.  Сменить пароль шифрования файла
B6.  Расшифровать файл НАВСЕГДА (файл становится открытым)
B7.  Запустить плейбук, взяв пароль vault из файла
B8.  Запустить плейбук, интерактивно спросив пароль с меткой prod
B9.  Найти все зашифрованные vault-файлы в проекте
B10. То же, что B7, но через переменную окружения
```

</details>

Оцени фрагменты:

```yaml
# B11
- ansible.builtin.template:
    src: env.j2
    dest: /opt/app/.env
```

<details><summary>Ответ</summary>

Нет `mode`/`owner` и `no_log` — секрет окажется в файле с правами по умолчанию
и может попасть в лог.

</details>

```yaml
# B12
- ansible.builtin.debug:
    msg: "Пароль БД: {{ db_password }}"
```

<details><summary>Ответ</summary>

Прямая утечка секрета в вывод и в логи CI. Так делать нельзя (даже временно).

</details>

```yaml
# B13
- community.postgresql.postgresql_user:
    name: app
    password: "{{ vault_db_password }}"
  no_log: true
```

<details><summary>Ответ</summary>

Корректно: значение из vault + `no_log: true`.

</details>

```yaml
# B14  group_vars/prod.yml (в git)
db_password: "SuperSecret123"
```

<details><summary>Ответ</summary>

Открытый секрет в git — утечка; нужен vault (файл или `encrypt_string`).

</details>

---

### Блок C. Практика

#### C1. 🔑 Первый зашифрованный файл

1. Создай `~/.vault_pass` с паролем, поставь права 600, добавь в `.gitignore`.
2. `ansible-vault create inventories/dev/group_vars/all/vault.yml` с парой `vault_*` переменных.
3. Посмотри файл обычным `cat` — что видишь?
4. Посмотри через `ansible-vault view`.

#### C2. Схема vault + vars

Сделай рядом `vars.yml` (в открытом виде), который ссылается на значения из `vault.yml`.
Напиши плейбук, который выводит длину пароля (не сам пароль!) через `debug`.
Объясни, почему это удобнее, чем одно зашифрованное значение.

#### C3. `encrypt_string`

Зашифруй одно значение и вставь его в обычный `group_vars/dev.yml`.
Проверь, что плейбук его читает. Сравни читаемость `git diff` для обоих подходов.

#### C4. 🔑 Секрет в конфиге приложения

1. Сделай `templates/env.j2` с <code v-pre>DB_PASSWORD={{ db_password }}</code>.
2. Разложи его с `mode: "0600"`, владельцем `app` и `no_log: true`.
3. Проверь права и владельца на хосте.
4. Убери `no_log`, спровоцируй ошибку задачи и посмотри, попадает ли секрет в вывод.

<details><summary>Ответ</summary>

С `no_log: true` в выводе будет `the output has been hidden due to the fact that
'no_log: true' was specified`; без него при ошибке содержимое параметров (включая пароль)
печатается.

</details>

#### C5. Два окружения — два пароля

1. Создай `~/.vault_dev` и `~/.vault_prod` с разными паролями.
2. Зашифруй `inventories/dev/.../vault.yml` первым, `prod` — вторым (`--vault-id`).
3. Запусти плейбук для dev, затем для prod.
4. Попробуй запустить prod с dev-паролем — какая ошибка?

<details><summary>Ответ</summary>

При неверном пароле — `ERROR! Decryption failed` для соответствующего файла.

</details>

#### C6. `rekey`

Смени пароль у одного из vault-файлов и убедись, что старый больше не подходит,
а новый работает. Опиши, как бы ты делал ротацию в команде из пяти человек.

#### C7. Поиск секретов в репозитории

```bash
grep -rl 'ANSIBLE_VAULT' .
grep -rEn '(password|token|secret|api_key)\s*[:=]' --include='*.yml' . | grep -v ANSIBLE_VAULT
```
Разбери результаты второй команды: есть ли открытые секреты? Почини найденное.

#### C8. Vault в CI (со звёздочкой)

Напиши джобу GitLab CI, которая:
1. ставит ansible и роли из `requirements.yml`;
2. пишет пароль vault из masked-переменной во временный файл с правами 600;
3. запускает плейбук с `--vault-password-file`;
4. удаляет файл в `after_script`.
Объясни, почему пароль не стоит передавать через аргумент командной строки.

<details><summary>Ответ</summary>

Аргумент командной строки виден в списке процессов (`ps`) и может попасть
в логи раннера; переменная окружения/файл с правами 600 безопаснее.

</details>

#### C9. Diff для vault

Настрой `.gitattributes` и `diff.ansible-vault.textconv`, измени секрет и посмотри `git diff`.
Затем объясни, почему в CI так делать не нужно.

#### C10. Инцидент: секрет в истории (тренировка)

В учебном репозитории закоммить «секрет» открытым текстом, запушить в свой личный репо
и отработать порядок действий: ротация (смена значения) → удаление из истории → форс-пуш →
уведомление команды. Запиши чек-лист.

<details><summary>Ответ</summary>

Чек-лист: (1) сменить сам секрет; (2) обновить его в vault/CI; (3) убрать
из истории git; (4) форс-пуш и уведомление команды; (5) проверить артефакты и логи,
где он мог сохраниться.

</details>

---

### Блок D. Инциденты

**D1.** `ERROR! Attempting to decrypt but no vault secrets found`. Причина и три решения.

<details><summary>Ответ</summary>

Плейбук использует зашифрованные данные, а пароль не передан. Решения:
`--ask-vault-pass`, `--vault-password-file`, `vault_password_file` в `ansible.cfg`
(или переменная окружения).

</details>

**D2.** `ERROR! Decryption failed` при правильном на вид пароле. Что могло случиться?

<details><summary>Ответ</summary>

Файл зашифрован другим паролем/`vault-id`; пароль в файле содержит лишний
перенос строки или пробел; файл был повреждён при мерже.

</details>

**D3.** После `ansible-vault decrypt` файл случайно закоммитили. Порядок действий.

<details><summary>Ответ</summary>

Считать секрет скомпрометированным: ротация значения, затем удаление файла
из истории, форс-пуш, уведомление, повторное шифрование vault'ом.

</details>

**D4.** В CI-логе видно содержимое `.env` с паролем. Что добавить в задачу?

<details><summary>Ответ</summary>

`no_log: true` на задаче; плюс права `0600` и отсутствие `debug` с секретами.

</details>

**D5.** Разработчик положил `.vault_pass` в репозиторий «чтобы у всех работало».
Объясни, почему это обесценивает vault, и предложи правильную схему.

<details><summary>Ответ</summary>

Пароль в репозитории = шифротекст расшифровывает каждый, у кого есть доступ
к репозиторию, то есть vault перестаёт защищать. Правильно: пароль в менеджере паролей
команды, у каждого локально в файле с правами 600, в CI — masked-переменная.

</details>

**D6.** Пароль vault утёк в общий чат. Что делать по шагам?

<details><summary>Ответ</summary>

Ротация: `ansible-vault rekey` всех файлов новым паролем, обновление пароля
в CI и у команды, ротация самих секретов внутри (пароли БД, токены) — потому что
их мог получить любой, у кого был доступ к репозиторию.

</details>

**D7.** Файл `vault.yml` в MR показывает только «кашу» — ревьюер не понимает, что изменилось.
Два способа сделать ревью осмысленным.

<details><summary>Ответ</summary>

(1) Схема `vault.yml` + открытый `vars.yml` — видно, какие переменные используются;
(2) `encrypt_string` для точечных значений; (3) локальный `diff.ansible-vault.textconv`
у ревьюера.

</details>

**D8.** Плейбук работает локально, но падает в CI на расшифровке. Что проверить?

<details><summary>Ответ</summary>

Наличие переменной с паролем в CI (masked), корректность записи файла
(лишний перенос строки), права 600, совпадение `vault-id`, установлен ли ansible
нужной версии.

</details>

**D9.** Секрет лежит на сервере в `/opt/app/.env` с правами `0644`. Чем это опасно
и как исправить?

<details><summary>Ответ</summary>

Любой пользователь на сервере прочитает секрет. Исправление: `mode: "0600"`,
владелец — сервисный пользователь, и прогнать плейбук заново (а секрет — ротировать,
если хост многопользовательский).

</details>

**D10.** Команда выросла до 15 человек, нужен аудит «кто смотрел прод-секреты».
Что предложить вместо ansible-vault?

<details><summary>Ответ</summary>

HashiCorp Vault (или облачный Secret Manager) с аудитом, политиками доступа,
ротацией и динамическими секретами; Ansible получает значения через lookup-плагин.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как хранить секреты в Ansible?

<details><summary>Ответ</summary>

В `ansible-vault` (файлы или значения), а пароль — вне репозитория; для зрелых команд —
внешние хранилища секретов.

</details>

**2.** Что такое ansible-vault и что он умеет?

<details><summary>Ответ</summary>

Шифрует и расшифровывает файлы/строки AES-256: `create`, `edit`, `view`, `encrypt`,
`decrypt`, `rekey`, `encrypt_string`.

</details>

**3.** Где хранится пароль от vault?

<details><summary>Ответ</summary>

Вне git: локальный файл с правами 600, CI/CD-переменная, менеджер паролей.

</details>

**4.** Как использовать разные пароли для разных окружений?

<details><summary>Ответ</summary>

Через `--vault-id метка@источник` — разные пароли для разных окружений.

</details>

**5.** Как запускать плейбуки с vault в CI/CD?

<details><summary>Ответ</summary>

Пароль — в masked CI-переменной, записывается во временный файл с правами 600,
передаётся `--vault-password-file`, файл удаляется после прогона.

</details>

**6.** Достаточно ли vault, чтобы секрет не утёк? (вопрос с подвохом)

<details><summary>Ответ</summary>

Нет: нужен ещё `no_log: true`, правильные права на файлы и отказ от печати секретов.

</details>

**7.** Что делать, если секрет попал в git?

<details><summary>Ответ</summary>

Ротировать секрет, затем чистить историю и уведомить команду.

</details>

**8.** Чем ansible-vault хуже HashiCorp Vault?

<details><summary>Ответ</summary>

Нет аудита, ролевого доступа, автоматической ротации и динамических секретов.

</details>

**9.** Как проверить, что в репозитории нет открытых секретов?

<details><summary>Ответ</summary>

`grep` по типичным ключам (`password`, `token`, `secret`) + инструменты
(`gitleaks`, `trufflehog`, GitLab Secret Detection) в CI.

</details>

**10.** Какие права должны быть у файла с секретами на сервере?

<details><summary>Ответ</summary>

`0600` (или `0640` с сервисной группой) и правильный владелец.

</details>

---

### 🎯 Чек-лист

- [ ] Создавал и редактировал зашифрованный файл
- [ ] Использую схему `vault.yml` + открытый `vars.yml`
- [ ] Пробовал `encrypt_string` и понимаю, когда он лучше
- [ ] Пароль лежит вне git, файл с правами 600, добавлен в `.gitignore`
- [ ] Настроил разные пароли для dev и prod через `--vault-id`
- [ ] ⭐ Ставлю `no_log: true` рядом с секретами
- [ ] Файлы с секретами на хостах — `mode: "0600"` и нужный владелец
- [ ] Знаю порядок действий при утечке секрета (сначала ротация!)
- [ ] Понимаю ограничения vault и знаю, чем его заменяют в больших командах
