---
title: "05. Модули — готовые функции Ansible"
description: "Пакеты, файлы, сервисы, пользователи, git, Docker и служебные модули — что использовать вместо shell"
---

# 05. Модули — готовые функции Ansible

> Роадмап → 5. Ansible → Фундамент → **«Модули — готовые функции: `apt`, `yum`, `copy`,
> `template`, `file`, `service`, `user`, `docker_container`, `git`.»**
> **После темы ты умеешь:** подобрать модуль под задачу, прочитать его документацию
> и не писать `shell` там, где есть готовое решение.

---

## 🗺️ Карта темы

```text:no-line-numbers
            ЗАДАЧА                        МОДУЛЬ
 ─────────────────────────────────────────────────────────────
 поставить пакет              →  apt / yum / dnf / package / pip
 положить файл                →  copy / template / lineinfile / blockinfile
 каталог, права, симлинк      →  file
 управлять сервисом           →  service / systemd
 пользователь, группа, ключ   →  user / group / authorized_key
 забрать код                  →  git
 скачать/распаковать          →  get_url / unarchive
 контейнеры                   →  community.docker.docker_container / docker_compose_v2
 задание в cron               →  cron
 что-то своё                  →  command / shell / script / raw   ← ПОСЛЕДНИЙ выбор
 отладка и проверки           →  debug / assert / stat / uri / wait_for
```

**Правило выбора:** сначала ищи профильный модуль (`ansible-doc -l | grep ...`),
и только если его нет — `command`/`shell` с `creates`/`changed_when`.

---

## 1. Пакеты: `apt`, `yum`/`dnf`, `package`, `pip`

```yaml
- name: Пакеты для веб-сервера
  ansible.builtin.apt:
    name:
      - nginx
      - curl
      - git
    state: present            # present | absent | latest | build-dep
    update_cache: true        # аналог apt update
    cache_valid_time: 3600    # ⭐ не обновлять кэш, если он свежее часа
  become: true

- name: Полностью удалить пакет с конфигами
  ansible.builtin.apt:
    name: apache2
    state: absent
    purge: true
    autoremove: true

- name: Внешний .deb с диска/URL
  ansible.builtin.apt:
    deb: https://example.com/package.deb

- name: RHEL-семейство
  ansible.builtin.dnf:
    name: nginx
    state: present

- name: Универсально (сам выберет apt/dnf/...)
  ansible.builtin.package:
    name: git
    state: present

- name: Python-пакеты
  ansible.builtin.pip:
    name: [docker, requests]
    virtualenv: /opt/app/venv
```

| Ключ | Смысл |
|------|-------|
| `state: present` | Установлен (любая версия) — **предсказуемо** |
| `state: latest` | Всегда обновлять — даёт `changed` при выходе версии ⚠️ |
| `state: absent` | Удалён |
| `update_cache` + `cache_valid_time` | Обновить индексы, но не чаще, чем раз в N секунд |
| `purge`, `autoremove` | Снести конфиги и «осиротевшие» зависимости |

Репозитории и ключи (Debian):
```yaml
- ansible.builtin.apt_key:
    url: https://download.docker.com/linux/ubuntu/gpg
    keyring: /etc/apt/keyrings/docker.gpg
- ansible.builtin.apt_repository:
    repo: "deb [signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu {{ ansible_distribution_release }} stable"
    state: present
    filename: docker
```

---

## 2. Файлы: `copy`, `template`, `file`, `lineinfile`, `blockinfile`

### `copy` — положить готовый файл
```yaml
- ansible.builtin.copy:
    src: files/app.conf          # путь на УПРАВЛЯЮЩЕЙ машине
    dest: /etc/app/app.conf
    owner: root
    group: root
    mode: "0644"                 # ⭐ кавычки обязательны, иначе YAML съест ноль
    backup: true                 # сохранить прежнюю версию
    validate: "/usr/sbin/nginx -t -c %s"   # проверить ДО подмены
  notify: restart app

- ansible.builtin.copy:
    content: |                   # содержимое прямо в плейбуке
      Managed by Ansible
      Do not edit manually
    dest: /etc/motd
    mode: "0644"
```

### `template` — то же, но с подстановкой переменных (тема 10)
```yaml
- ansible.builtin.template:
    src: templates/nginx.conf.j2
    dest: /etc/nginx/nginx.conf
    mode: "0644"
    validate: "nginx -t -c %s"
  notify: reload nginx
```
**`copy` vs `template`:** если в файле есть хоть одна переменная — это `template`.
Статичный файл — `copy`.

### `file` — каталоги, права, ссылки, удаление
```yaml
- ansible.builtin.file:
    path: /opt/app
    state: directory        # directory | file | link | hard | touch | absent
    owner: deploy
    group: deploy
    mode: "0755"
    recurse: true           # рекурсивно применить права (только для directory)

- ansible.builtin.file:
    src: /opt/app/releases/v2
    dest: /opt/app/current
    state: link             # симлинк — классика blue-green деплоя

- ansible.builtin.file:
    path: /tmp/old.lock
    state: absent           # удалить файл/каталог
```

### `lineinfile` — одна строка в существующем файле
```yaml
- ansible.builtin.lineinfile:
    path: /etc/ssh/sshd_config
    regexp: '^#?PermitRootLogin'      # ⭐ найти строку по шаблону
    line: 'PermitRootLogin no'        # и заменить/добавить
    state: present
    validate: '/usr/sbin/sshd -t -f %s'
    backup: true
  notify: restart sshd
```

### `blockinfile` — блок строк с маркерами
```yaml
- ansible.builtin.blockinfile:
    path: /etc/hosts
    marker: "# {mark} ANSIBLE MANAGED: app hosts"
    block: |
      10.0.0.11 web1
      10.0.0.12 web2
```
Ansible сам расставит `# BEGIN ...` / `# END ...` и при следующем прогоне заменит
содержимое между ними — идемпотентно.

> ⚠️ `lineinfile` без `regexp` при повторном изменении строки **добавит вторую**.
> Правило: `regexp` описывает «как найти старую строку», `line` — «как должно стать».
> Если правок в файле много — это уже `template`, а не десять `lineinfile`.

---

## 3. Сервисы: `service` и `systemd`

```yaml
- ansible.builtin.service:
    name: nginx
    state: started          # started | stopped | restarted | reloaded
    enabled: true           # автозапуск
  become: true

- ansible.builtin.systemd_service:     # ansible.builtin.systemd в старых версиях
    name: myapp
    state: restarted
    daemon_reload: true     # ⭐ после изменения unit-файла
    enabled: true
    scope: system
```

| | `service` | `systemd`/`systemd_service` |
|---|---|---|
| Init-система | Определяет сам (systemd, sysvinit, openrc) | Только systemd |
| `daemon_reload` | ❌ | ✅ |
| `masked`, `scope: user` | ❌ | ✅ |
| Когда брать | Обычный случай, переносимость | Нужны systemd-специфичные вещи |

> ⚠️ `state: restarted` в обычной задаче = рестарт при **каждом** прогоне.
> Рестарт должен жить в **handler** (тема 09), а в задаче — `state: started`.

---

## 4. Пользователи: `user`, `group`, `authorized_key`

```yaml
- ansible.builtin.group:
    name: deploy
    state: present

- ansible.builtin.user:
    name: deploy
    comment: "Deploy user"
    group: deploy
    groups: [docker, sudo]
    append: true                 # ⭐ БЕЗ append группы будут ПЕРЕЗАПИСАНЫ
    shell: /bin/bash
    home: /home/deploy
    create_home: true
    password: "{{ 'secret' | password_hash('sha512') }}"   # только хэш!
    state: present

- ansible.posix.authorized_key:
    user: deploy
    key: "{{ lookup('file', 'files/deploy.pub') }}"
    state: present
    exclusive: false             # true = удалить все остальные ключи

- ansible.builtin.user:
    name: olduser
    state: absent
    remove: true                 # снести домашний каталог
```

> ⚠️ Две классические ошибки: забытый `append: true` (пользователь теряет группы)
> и пароль открытым текстом (нужен хэш, а сам секрет — из vault).

---

## 5. Код и архивы: `git`, `get_url`, `unarchive`, `synchronize`

```yaml
- ansible.builtin.git:
    repo: https://github.com/user/app.git
    dest: /opt/app
    version: v1.2.3          # ветка, тег или коммит — ⭐ не 'main' на проде
    force: true              # затереть локальные изменения
    depth: 1                 # shallow clone (быстрее)
    accept_hostkey: true     # для ssh-репозиториев
  become: true
  become_user: deploy

- ansible.builtin.get_url:
    url: https://example.com/app-1.2.3.tar.gz
    dest: /tmp/app.tar.gz
    checksum: "sha256:ab12cd..."     # ⭐ обязательно для воспроизводимости
    mode: "0644"

- ansible.builtin.unarchive:
    src: /tmp/app.tar.gz
    dest: /opt/app
    remote_src: true         # архив УЖЕ на целевом хосте (иначе возьмёт локальный)
    creates: /opt/app/bin/app   # не распаковывать повторно

- ansible.posix.synchronize:   # обёртка над rsync
    src: ./dist/
    dest: /var/www/html/
    delete: true
```

---

## 6. Docker: `community.docker`

```bash
ansible-galaxy collection install community.docker
```

```yaml
- name: Python-библиотека docker на хосте (нужна модулям)
  ansible.builtin.pip:
    name: docker

- name: Контейнер приложения
  community.docker.docker_container:
    name: myapp
    image: "registry.example.com/myapp:{{ app_version }}"
    state: started
    restart_policy: unless-stopped
    pull: true
    ports: ["8080:8080"]
    env:
      APP_ENV: "{{ app_env }}"
      DB_HOST: "{{ db_host }}"
    volumes:
      - /opt/app/data:/data
    networks:
      - name: appnet
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      retries: 3

- community.docker.docker_image:
    name: myapp
    source: build
    build: { path: /opt/app }

- community.docker.docker_compose_v2:
    project_src: /opt/app
    state: present           # эквивалент docker compose up -d
    pull: always
```

> 💡 Самый частый прод-паттерн деплоя: `template` кладёт `docker-compose.yml` и `.env`
> → `docker_compose_v2` поднимает → `uri` проверяет `/health`. Это лаба 3 темы 14.

---

## 7. Проверки и служебные модули

```yaml
- ansible.builtin.debug:
    msg: "IP хоста: {{ ansible_default_ipv4.address }}"
- ansible.builtin.debug:
    var: app_config          # вывести переменную целиком

- ansible.builtin.assert:
    that:
      - app_version is defined
      - app_port | int > 1024
    fail_msg: "Не задана версия приложения или некорректный порт"

- ansible.builtin.stat:
    path: /opt/app/current
  register: app_dir
- ansible.builtin.debug:
    msg: "Каталога нет"
  when: not app_dir.stat.exists

- ansible.builtin.uri:              # HTTP-проверка (health-check)
    url: "http://localhost:8080/health"
    status_code: 200
    timeout: 5
  retries: 10
  delay: 3
  register: health
  until: health.status == 200

- ansible.builtin.wait_for:
    port: 5432
    host: "{{ db_host }}"
    timeout: 60
    state: started

- ansible.builtin.cron:
    name: "backup database"
    minute: "0"
    hour: "3"
    job: "/opt/scripts/backup.sh >> /var/log/backup.log 2>&1"
    user: root
```

---

## 8. Когда всё-таки `command`/`shell` — делай правильно

```yaml
# ✅ вариант 1: creates/removes — «не запускать, если уже сделано»
- ansible.builtin.command: /opt/app/bin/init-db
  args:
    creates: /var/lib/app/.db_initialized

# ✅ вариант 2: changed_when/failed_when — объяснить, что считать изменением
- ansible.builtin.shell: "systemctl is-enabled myapp"
  register: r
  changed_when: false            # это проверка, она ничего не меняет
  failed_when: r.rc not in [0, 1]

# ✅ вариант 3: сначала проверить, потом действовать
- ansible.builtin.stat: { path: /opt/app/current }
  register: cur
- ansible.builtin.command: /opt/app/bin/deploy
  when: not cur.stat.exists
```

| Ключ | Что даёт |
|------|----------|
| `creates: путь` | Пропустить задачу, если путь существует |
| `removes: путь` | Выполнить, только если путь существует |
| `chdir: путь` | Выполнить в каталоге |
| `changed_when:` | Условие, при котором считать `changed` |
| `failed_when:` | Условие ошибки |
| `warn: false` (устар.) | Убрать предупреждение «use the X module instead» |

---

## 9. `ansible-doc` — документация без интернета

```bash
ansible-doc -l                          # все модули
ansible-doc -l | grep -i docker         # найти по слову
ansible-doc ansible.builtin.copy        # полная документация
ansible-doc -s ansible.builtin.user     # краткий «скелет» задачи для копипаста
ansible-doc -t lookup -l                # плагины другого типа (lookup, filter, callback)
ansible-doc -t filter ansible.builtin.default
```

`-s` даёт готовый шаблон:
```yaml
- name: Manage user accounts
  ansible.builtin.user:
      name:                  # (required) Name of the user to create...
      state:                 # present/absent
      groups:
```

---

## 💼 Как это в DevOps

- Опытного инженера от новичка отличает **отсутствие `shell` в плейбуке**: почти для всего
  есть модуль, и ревьюер спросит, почему ты его не взял.
- `validate:` у `copy`/`template`/`lineinfile` спасает от «положили битый конфиг
  на 30 серверов и отвалился nginx».
- `backup: true` на конфигах — дешёвая страховка при массовых изменениях.
- Связка `get_url` + `checksum` + `unarchive` + `creates` — стандартный способ ставить
  бинарники (node_exporter, terraform, etc.) идемпотентно.
- Модули из коллекций (`community.docker`, `ansible.posix`) фиксируют в `requirements.yml`,
  чтобы у всех и в CI были одинаковые версии.

---

## 📌 Шпаргалка

| Задача | Модуль |
|--------|--------|
| Пакет (Debian) | `ansible.builtin.apt` |
| Пакет (RHEL) | `ansible.builtin.dnf` / `yum` |
| Пакет кроссплатформенно | `ansible.builtin.package` |
| Файл как есть | `ansible.builtin.copy` |
| Файл с переменными | `ansible.builtin.template` |
| Каталог/права/симлинк/удаление | `ansible.builtin.file` |
| Одна строка в конфиге | `ansible.builtin.lineinfile` |
| Блок строк | `ansible.builtin.blockinfile` |
| Сервис | `ansible.builtin.service` / `systemd_service` |
| Пользователь / группа / ключ | `user` / `group` / `ansible.posix.authorized_key` |
| Репозиторий кода | `ansible.builtin.git` |
| Скачать файл | `ansible.builtin.get_url` (+`checksum`) |
| Распаковать | `ansible.builtin.unarchive` (+`remote_src`, `creates`) |
| Контейнер | `community.docker.docker_container` |
| docker compose | `community.docker.docker_compose_v2` |
| Задание cron | `ansible.builtin.cron` |
| HTTP-проверка | `ansible.builtin.uri` |
| Ждать порт | `ansible.builtin.wait_for` |
| Проверить файл | `ansible.builtin.stat` |
| Вывести значение | `ansible.builtin.debug` |
| Проверить условие и упасть | `ansible.builtin.assert` |
| Документация | `ansible-doc [-s] <модуль>` |

---

## 🧠 Что запомнить

1. Модуль — готовая идемпотентная функция; сначала ищи модуль, потом думай про `shell`.
2. `copy` — статичный файл, `template` — файл с переменными.
3. `mode: "0644"` всегда в кавычках, иначе YAML превратит значение в другое число.
4. `validate:` проверяет конфиг **до** подмены — обязательный приём для nginx/sshd/sudoers.
5. `lineinfile` без `regexp` плодит дубли; много правок в одном файле → `template`.
6. `state: restarted` в задаче ломает идемпотентность — рестарт живёт в handler'е.
7. `user` без `append: true` затирает дополнительные группы.
8. `state: latest` для пакетов — источник неожиданных обновлений на проде.
9. `get_url` без `checksum` и `unarchive` без `creates` — потенциальная неидемпотентность.
10. Для контейнеров — коллекция `community.docker` (+ python-библиотека `docker` на хосте).
11. `command`/`shell` спасают `creates`, `removes`, `changed_when`, `failed_when`.
12. `ansible-doc -s <модуль>` — быстрый способ вспомнить параметры без интернета.

---

## Задачи

> Стенд: 3 хоста. Часть заданий удобно делать ad-hoc, часть — коротким плейбуком.

---

### Блок A. Теория

**A1.** Что такое модуль в Ansible и где он выполняется?

<details><summary>Ответ</summary>

Готовая единица работы (обычно python-код), которая копируется на целевой хост
и выполняется там; возвращает JSON с результатом (`changed`, `failed`, данные).

</details>

**A2.** ⭐ Чем `copy` отличается от `template`? Когда что выбирать?

<details><summary>Ответ</summary>

`copy` кладёт файл как есть; `template` перед копированием обрабатывает его Jinja2,
подставляя переменные и факты. Есть переменные — `template`, нет — `copy`.

</details>

**A3.** Чем `copy` отличается от `fetch`?

<details><summary>Ответ</summary>

`copy` — на хосты, `fetch` — с хостов на управляющую машину.

</details>

**A4.** Что делает параметр `validate:` и у каких модулей он есть? Приведи пример пользы.

<details><summary>Ответ</summary>

Проверяет валидность файла перед установкой на место (`%s` — временный файл).
Есть у `copy`, `template`, `lineinfile`, `blockinfile`. Польза: битый `nginx.conf`
не попадёт на сервер, задача упадёт до подмены.

</details>

**A5.** Почему `mode: 0644` без кавычек — ошибка?

<details><summary>Ответ</summary>

YAML прочитает `0644` как число (восьмеричное/десятичное в зависимости от версии),
и права окажутся не те. Всегда строкой: `"0644"`.

</details>

**A6.** В чём разница `state: present` и `state: latest` для пакетов? Что выбрать для прода?

<details><summary>Ответ</summary>

`present` — «установлен любой версии», `latest` — «обновляй до последней».
Для прода — `present` (или фиксированная версия): предсказуемость важнее свежести.

</details>

**A7.** Что делают `purge` и `autoremove` у модуля `apt`?

<details><summary>Ответ</summary>

`purge` удаляет конфигурационные файлы пакета, `autoremove` — зависимости,
которые больше никому не нужны.

</details>

**A8.** Зачем `cache_valid_time` и что он экономит?

<details><summary>Ответ</summary>

Не даёт обновлять индексы apt чаще, чем раз в N секунд: экономит время прогона
и трафик, особенно когда `update_cache` встречается в нескольких ролях.

</details>

**A9.** Чем `service` отличается от `systemd_service`? Когда нужен второй?

<details><summary>Ответ</summary>

`service` — универсальная обёртка (systemd, sysvinit, openrc); `systemd_service` —
только systemd, зато умеет `daemon_reload`, `masked`, `scope: user`.

</details>

**A10.** Почему `service: state=restarted` в обычной задаче — плохая идея?

<details><summary>Ответ</summary>

`restarted` — императивное действие: сервис будет перезапускаться при каждом
прогоне, что ломает идемпотентность и может вызвать лишний даунтайм. Рестарт — в handler.

</details>

**A11.** ⭐ Что случится, если в модуле `user` указать `groups: docker` без `append: true`?

<details><summary>Ответ</summary>

Пользователь будет состоять **только** в `docker` (плюс первичная группа) —
остальные дополнительные группы будут удалены. Нужен `append: true`.

</details>

**A12.** Как правильно задать пароль пользователя через Ansible?

<details><summary>Ответ</summary>

Передавать хэш: <code v-pre>password: "{{ pass | password_hash('sha512') }}"</code>,
сам пароль хранить в vault. Открытым текстом пароль в `password:` не работает
(поле ожидает хэш) и небезопасно.

</details>

**A13.** Чем `lineinfile` отличается от `blockinfile`? Когда пора переходить на `template`?

<details><summary>Ответ</summary>

`lineinfile` управляет одной строкой, `blockinfile` — блоком строк между маркерами.
Когда правок больше 2-3 или файл целиком «наш» — переходим на `template`.

</details>

**A14.** Зачем `lineinfile` нужен `regexp`, если есть `line`?

<details><summary>Ответ</summary>

`regexp` говорит, **какую существующую строку** заменить. Без него модуль ищет
точное совпадение с `line`, и при изменении значения появится вторая строка.

</details>

**A15.** Что делает `creates:` у `command`? А `removes:`?

<details><summary>Ответ</summary>

`creates: путь` — пропустить задачу, если путь уже существует;
`removes: путь` — выполнить задачу только если путь существует.

</details>

**A16.** Как сделать `shell`-задачу, которая никогда не показывает `changed`?

<details><summary>Ответ</summary>

Добавить `changed_when: false` (для проверок) — задача будет отображаться как `ok`.

</details>

**A17.** Что нужно на целевом хосте, чтобы работал `community.docker.docker_container`?

<details><summary>Ответ</summary>

Установленный docker, python-библиотека `docker` (`pip: name=docker`)
и коллекция `community.docker` на control node.

</details>

**A18.** Зачем `checksum` у `get_url` и `creates` у `unarchive`?

<details><summary>Ответ</summary>

`checksum` гарантирует, что скачан ожидаемый файл (и даёт идемпотентность
при повторных прогонах); `creates` не даёт распаковывать архив каждый раз.

</details>

**A19.** Как найти нужный модуль и посмотреть его параметры без интернета?

<details><summary>Ответ</summary>

`ansible-doc -l | grep <слово>` — найти; `ansible-doc <модуль>` — документация;
`ansible-doc -s <модуль>` — краткий скелет задачи.

</details>

**A20.** Что такое `ansible.posix` и `community.general`? Как их установить?

<details><summary>Ответ</summary>

Коллекции: `ansible.posix` (POSIX-модули: `authorized_key`, `sysctl`, `mount`,
`synchronize`), `community.general` (большой сборник). Ставятся
`ansible-galaxy collection install <имя>` и фиксируются в `requirements.yml`.

</details>

---

### Блок B. «Что делает задача» + «идемпотентно ли»

Для каждого фрагмента: что делает и есть ли проблема?

```yaml
# B1
- ansible.builtin.apt:
    name: nginx
    state: latest
    update_cache: true
```

<details><summary>Ответ</summary>

Обновляет кэш и ставит **последнюю** версию nginx. Проблема: `latest` даёт `changed`
при выходе обновлений и неконтролируемые апгрейды на проде.

</details>

```yaml
# B2
- ansible.builtin.copy:
    src: nginx.conf
    dest: /etc/nginx/nginx.conf
    mode: 0644
```

<details><summary>Ответ</summary>

Копирует конфиг, но `mode: 0644` без кавычек → неверные права (типичный баг).

</details>

```yaml
# B3
- ansible.builtin.lineinfile:
    path: /etc/ssh/sshd_config
    line: "PermitRootLogin no"
```

<details><summary>Ответ</summary>

Добавит строку; при изменении значения в файле появится дубль. Нужен `regexp`
и `validate`.

</details>

```yaml
# B4
- ansible.builtin.user:
    name: deploy
    groups: docker
```

<details><summary>Ответ</summary>

Перезапишет дополнительные группы пользователя. Нужен `append: true`.

</details>

```yaml
# B5
- ansible.builtin.service:
    name: nginx
    state: restarted
```

<details><summary>Ответ</summary>

Рестарт при каждом прогоне — неидемпотентно; нужен `state: started` + handler.

</details>

```yaml
# B6
- ansible.builtin.shell: |
    cd /opt/app && git pull && npm install && systemctl restart app
```

<details><summary>Ответ</summary>

Неидемпотентно и непрозрачно: `git pull` каждый раз, `npm install` всегда `changed`,
рестарт всегда. Разложить на `git`, `npm`/`command` с `creates`, `service` + handler.

</details>

```yaml
# B7
- ansible.builtin.file:
    path: /opt/app
    state: directory
    owner: deploy
    mode: "0755"
```

<details><summary>Ответ</summary>

Корректно и идемпотентно (права строкой, состояние описано).

</details>

```yaml
# B8
- ansible.builtin.git:
    repo: https://github.com/user/app.git
    dest: /opt/app
    version: main
```

<details><summary>Ответ</summary>

Работает, но `version: main` = «неизвестно, что приедет». Для прода — тег/коммит.

</details>

```yaml
# B9
- ansible.builtin.command: /opt/app/install.sh
  args:
    creates: /opt/app/.installed
```

<details><summary>Ответ</summary>

Корректно: скрипт выполнится один раз благодаря `creates`.

</details>

```yaml
# B10
- ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
    validate: "nginx -t -c %s"
  notify: reload nginx
```

<details><summary>Ответ</summary>

Эталон: шаблон + проверка конфига до подмены + перезагрузка сервиса через handler.

</details>

---

### Блок C. Практика

#### C1. 🔑 Базовый набор модулей

Напиши плейбук `base.yml` для группы `web`, который:
1. обновляет кэш apt (не чаще раза в час);
2. ставит `nginx`, `curl`, `git`, `htop`;
3. создаёт группу `deploy` и пользователя `deploy` с шеллом bash;
4. кладёт публичный ключ пользователю `deploy`;
5. создаёт каталог `/opt/app` с владельцем `deploy` и правами 0755;
6. запускает nginx и включает автозагрузку.
Запусти дважды, добейся `changed=0` во втором прогоне.

#### C2. `copy` vs `template`

1. Положи статичный `index.html` через `copy` в `/var/www/html/`.
2. Сделай `index.html.j2` с <code v-pre>{{ inventory_hostname }}</code> и <code v-pre>{{ ansible_default_ipv4.address }}</code>,
   положи через `template`.
3. Открой страницу с обоих web-хостов. В чём разница результата?

#### C3. `validate` спасает прод

1. Намеренно сломай `nginx.conf.j2` (убери `;`).
2. Прогони плейбук **без** `validate` — что произошло с nginx после рестарта?
3. Верни рабочий конфиг, добавь `validate: "nginx -t -c %s"`, снова сломай и прогони.
4. Сравни последствия. Сформулируй правило.

<details><summary>Ответ</summary>

Без `validate` битый конфиг попадает на сервер, и рестарт роняет nginx.
С `validate` задача падает **до** подмены — конфиг остаётся рабочим. Правило: критичные
конфиги только с `validate` (и желательно `backup: true`).

</details>

#### C4. `lineinfile` как надо и как не надо

1. Добавь в `/etc/ssh/sshd_config` строку `PermitRootLogin no` **без** `regexp` —
   запусти, поменяй значение на `yes`, запусти снова. Что в файле?
2. Перепиши с `regexp: '^#?PermitRootLogin'` и повтори эксперимент.
3. Добавь `validate: '/usr/sbin/sshd -t -f %s'` и проверь, что произойдёт при опечатке.

<details><summary>Ответ</summary>

Без `regexp` в файле окажутся обе строки (`no` и `yes`) — sshd возьмёт первую,
поведение станет неочевидным. С `regexp` строка заменяется на месте.

</details>

#### C5. `blockinfile`

Добавь в `/etc/hosts` блок с адресами всех хостов инвентаря (пока просто статично).
Запусти дважды. Измени блок, запусти снова. Посмотри маркеры в файле.

#### C6. Файлы и права

Через модуль `file`:
1. создай `/opt/releases/v1` и `/opt/releases/v2`;
2. сделай симлинк `/opt/app/current` → `v1`;
3. переключи симлинк на `v2` (что показывает Ansible?);
4. удали `/opt/releases/v1` целиком.

<details><summary>Ответ</summary>

Переключение симлинка даёт `changed`; повторный прогон — `ok`. Это основа
blue-green/релизных каталогов.

</details>

#### C7. Пользователи

1. Создай пользователя `appuser` с группами `deploy` и `docker`.
2. Добавь его ещё в группу `sudo` **без потери** предыдущих.
3. Проверь `id appuser` ad-hoc'ом.
4. Повтори без `append: true` — что произошло? Восстанови.

<details><summary>Ответ</summary>

Без `append: true` пользователь останется только в последней указанной группе —
чинится повторным запуском с полным списком и `append: true`.

</details>

#### C8. `git` + `creates`

1. Склонируй любой небольшой публичный репозиторий в `/opt/demo` с `version` = конкретный тег.
2. Запусти дважды — что показывает Ansible?
3. Измени файл в репозитории на хосте руками и прогони снова с `force: true` и без него.

<details><summary>Ответ</summary>

Повторный прогон при неизменном `version` даёт `ok`. Если файл изменён руками:
без `force` задача упадёт или останется `ok` с локальными изменениями, с `force: true` —
изменения затрутся (`changed`).

</details>

#### C9. Скачивание бинарника идемпотентно

Напиши задачи: скачать архив `node_exporter` с `checksum`, распаковать в `/opt`
с `creates`, создать симлинк в `/usr/local/bin`, положить systemd unit из шаблона,
`daemon_reload` и запуск сервиса. Проверь идемпотентность.

#### C10. Docker-модули

1. Установи коллекцию `community.docker` и python-библиотеку `docker` на хост.
2. Подними контейнер `nginx:alpine` на порту 8081 с `restart_policy: unless-stopped`.
3. Проверь `docker ps` ad-hoc'ом.
4. Поменяй тег образа и прогони снова — что сделает модуль?
5. Останови и удали контейнер через `state: absent`.

<details><summary>Ответ</summary>

При смене тега модуль пересоздаст контейнер (`changed`), потому что фактическое
состояние не совпадает с описанным.

</details>

#### C11. Проверки

Напиши плейбук, который:
1. `assert`'ом проверяет, что переменная `app_port` определена и > 1024;
2. `stat`'ом проверяет наличие `/opt/app/current`;
3. `uri`'ем дёргает `http://localhost/` с ретраями до `status 200`;
4. `debug`'ом печатает итог.

#### C12. Заменяем `shell` на модули (рефакторинг)

Дан «плейбук»:
```yaml
- shell: apt-get update && apt-get install -y nginx
- shell: echo "server_name example.com;" > /etc/nginx/conf.d/app.conf
- shell: useradd -m deploy || true
- shell: mkdir -p /opt/app && chown deploy /opt/app
- shell: systemctl restart nginx && systemctl enable nginx
- shell: curl -s http://localhost | grep -q nginx
```
Перепиши каждую строку на профильный модуль. Запусти дважды, добейся `changed=0`.

<details><summary>Ответ</summary>

Ожидаемый результат: `apt`, `template`/`copy`, `user`, `file`, `service` + handler,
`uri`. Второй прогон — `changed=0`.

</details>

---

### Блок D. Инциденты

**D1.** После прогона плейбука пользователь `deploy` потерял доступ к docker. Что произошло?

<details><summary>Ответ</summary>

В задаче `user` не было `append: true` — дополнительные группы (включая `docker`)
были перезаписаны.

</details>

**D2.** `template` положил конфиг, nginx не стартует, сайт лежит. Как надо было и как чинить?

<details><summary>Ответ</summary>

Нужен `validate:` у `template` (+ `backup: true`), тогда битый конфиг не доедет.
Чинить: откатить из бэкапа/git и прогнать заново; при массовом инциденте — `--limit`
по волнам.

</details>

**D3.** Права на файле получились `0420` вместо `0644`. Почему?

<details><summary>Ответ</summary>

`mode` задан без кавычек: YAML интерпретировал число иначе, чем ожидалось.

</details>

**D4.** `docker_container` падает с `Failed to import the required Python library (Docker SDK)`.
Что сделать?

<details><summary>Ответ</summary>

Установить python-библиотеку `docker` на целевом хосте (`pip: name=docker`)
и убедиться, что коллекция `community.docker` установлена на control node.

</details>

**D5.** Задача `apt: state=latest` в пятницу вечером обновила пакет и сломала приложение.
Как избежать в будущем?

<details><summary>Ответ</summary>

Использовать `state: present` или фиксировать версию (`name: nginx=1.24.*`),
обновления проводить осознанно и отдельным плейбуком с окном обслуживания.

</details>

**D6.** `unarchive` каждый раз показывает `changed`, хотя файлы те же. Причина и решение.

<details><summary>Ответ</summary>

Нет `creates:` (или архив каждый раз перекачивается). Добавить `creates`
на характерный файл и `checksum` у `get_url`.

</details>

**D7.** `lineinfile` добавил в `sudoers` строку с опечаткой, и теперь `sudo` не работает
на 10 хостах. Что предотвратило бы это?

<details><summary>Ответ</summary>

`validate: 'visudo -cf %s'` — проверка синтаксиса до записи; плюс `backup: true`,
`--check --diff` и прогон на одном хосте через `--limit`.

</details>

**D8.** `git` модуль падает с `Host key verification failed` для приватного репозитория.
Два решения.

<details><summary>Ответ</summary>

(1) `accept_hostkey: true` у модуля `git`; (2) заранее добавить ключ хоста
(`ssh-keyscan` → `known_hosts`) — надёжнее для прода. Плюс правильно настроенный
deploy-ключ/агент.

</details>

**D9.** `copy` с `src: /etc/app.conf` копирует не тот файл, который ожидали.
Откуда Ansible берёт `src`?

<details><summary>Ответ</summary>

`src` у `copy` — путь на **управляющей** машине (относительно каталога плейбука/роли,
подкаталог `files/`). Если нужно копировать файл, лежащий на целевом хосте, — `remote_src: true`.

</details>

**D10.** Плейбук показывает `changed` на задаче `file: state=directory` при каждом прогоне.
Возможные причины (две).

<details><summary>Ответ</summary>

(1) Права/владелец постоянно меняются кем-то ещё (или `recurse: true` затрагивает
новые файлы); (2) каталог создаётся не там, где проверяется (переменная пути меняется),
либо на пути есть симлинк.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое модуль в Ansible? Назови 10 модулей, которыми пользуешься.

<details><summary>Ответ</summary>

Готовая идемпотентная функция, выполняемая на целевом хосте. Типовой набор:
`apt/package`, `copy`, `template`, `file`, `lineinfile`, `service/systemd`, `user`,
`group`, `git`, `get_url`, `unarchive`, `cron`, `uri`, `stat`, `debug`, `docker_container`.

</details>

**2.** Чем `copy` отличается от `template`?

<details><summary>Ответ</summary>

`copy` — файл как есть, `template` — с подстановкой Jinja2-переменных.

</details>

**3.** Как управлять сервисами?

<details><summary>Ответ</summary>

Модулями `service`/`systemd_service`: `state: started/stopped/restarted/reloaded`,
`enabled`; перезапуск — через handler по `notify`.

</details>

**4.** Почему не стоит использовать `shell` без необходимости?

<details><summary>Ответ</summary>

Он неидемпотентен, не сообщает реального состояния, хуже читается и не проверяется
в check mode.

</details>

**5.** Как сделать `shell`-задачу идемпотентной?

<details><summary>Ответ</summary>

`creates`/`removes`, `changed_when`/`failed_when`, либо предварительная проверка
через `stat`/`register` + `when`.

</details>

**6.** Как установить пакет в разных дистрибутивах одной задачей?

<details><summary>Ответ</summary>

Модулем `package` (или `when: ansible_os_family == ...` с профильными модулями).

</details>

**7.** Как безопасно менять критичные конфиги (sshd, nginx, sudoers)?

<details><summary>Ответ</summary>

`validate:` + `backup: true` + `--check --diff` + прогон на одном хосте через `--limit`.

</details>

**8.** Как работать с Docker из Ansible?

<details><summary>Ответ</summary>

Коллекция `community.docker`: `docker_container`, `docker_image`, `docker_compose_v2`;
на хосте нужна python-библиотека `docker`.

</details>

**9.** Где посмотреть параметры модуля?

<details><summary>Ответ</summary>

`ansible-doc <модуль>` / `ansible-doc -s <модуль>`; список — `ansible-doc -l`.

</details>

**10.** Что такое коллекции и FQCN?

<details><summary>Ответ</summary>

Коллекция — пакет модулей/ролей/плагинов; FQCN — полное имя вида
`community.docker.docker_container`, устраняющее неоднозначность.

</details>

---

### 🎯 Чек-лист

- [ ] Знаю модуль под каждую типовую задачу и не тянусь к `shell`
- [ ] Понимаю `copy` vs `template` и `copy` vs `fetch`
- [ ] Пишу `mode: "0644"` строкой
- [ ] Использую `validate:` и `backup:` на критичных конфигах
- [ ] `lineinfile` пишу с `regexp`
- [ ] Помню про `append: true` у `user`
- [ ] Делал `shell` идемпотентным через `creates`/`changed_when`
- [ ] Поднимал контейнер через `community.docker`
- [ ] Пользуюсь `ansible-doc -s` вместо гугла
- [ ] Отрефакторил «плейбук из shell» в нормальные модули
