---
title: "09. Handler'ы и идемпотентность"
description: "notify/handlers, listen, flush_handlers, force_handlers, и практическая борьба за changed=0"
---

# 09. Handler'ы и идемпотентность

> Роадмап → 5. Ansible → Playbook → **«Handler'ы»**; плюс Фундамент → **«Идемпотентность —
> ключевое понятие»**. Оба входят в список популярных вопросов собеса:
> *«Что такое Handler?»* и *«Что такое идемпотентность?»*
> **После темы ты умеешь:** перезапускать сервисы только при реальных изменениях
> и писать плейбуки, дающие `changed=0` на повторе.

---

## 🗺️ Карта темы

```text:no-line-numbers
 ЗАДАЧА изменила файл?
        │
        ├─ НЕТ  →  ok       → handler НЕ вызывается → сервис НЕ трогаем
        │
        └─ ДА   →  changed  → notify: "reload nginx"
                                        │
                                        ▼
                          handler ставится в ОЧЕРЕДЬ (не выполняется сразу)
                                        │
                    (в конце play / при meta: flush_handlers)
                                        ▼
                            RUNNING HANDLER [reload nginx]
                            выполняется ОДИН раз, даже если позвали 10 задач
```

---

## 1. Handler — что это и зачем

> **Handler** — это задача, которая выполняется **только по вызову** (`notify`)
> и **только если** вызвавшая задача завершилась со статусом `changed`.
> Выполняется **один раз** в конце play, независимо от числа вызовов.

```yaml
- hosts: web
  become: true
  tasks:
    - name: Конфиг nginx
      ansible.builtin.template:
        src: nginx.conf.j2
        dest: /etc/nginx/nginx.conf
        validate: "nginx -t -c %s"
      notify: reload nginx            # ⭐ позвать handler, если файл изменился

    - name: Конфиг виртуального хоста
      ansible.builtin.template:
        src: site.conf.j2
        dest: /etc/nginx/conf.d/site.conf
      notify: reload nginx            # тот же handler

    - name: Сервис запущен
      ansible.builtin.service:
        name: nginx
        state: started
        enabled: true

  handlers:
    - name: reload nginx              # ⭐ имя должно ТОЧНО совпадать с notify
      ansible.builtin.service:
        name: nginx
        state: reloaded
```

**Зачем он нужен (ответ на собес):** чтобы **перезапускать сервис только тогда,
когда конфигурация действительно изменилась**. Без handler'а пришлось бы писать
`state: restarted` в обычной задаче — и сервис перезапускался бы при каждом прогоне,
что ломает идемпотентность и создаёт лишние обрывы соединений.

---

## 2. Правила работы handler'ов (то, что спрашивают)

| Правило | Пояснение |
|---------|-----------|
| Вызывается только на `changed` | Задача `ok` — handler молчит |
| Выполняется **один раз** | Десять `notify` одного handler'а = одно выполнение |
| Выполняется **в конце play** | Не сразу после задачи |
| Порядок — как в секции `handlers` | ⭐ **Не** в порядке `notify`! |
| Имя должно совпадать точно | Регистр и пробелы имеют значение |
| По умолчанию не выполняется при падении play | Лечится `force_handlers` |
| Handler может сам вызывать другой handler | Через `notify` внутри handler'а |
| Работает и в ролях | `roles/x/handlers/main.yml`; имена — глобальные в рамках play |

```yaml
handlers:
  - name: reload nginx        # выполнится ПЕРВЫМ, даже если его позвали последним
    ansible.builtin.service: { name: nginx, state: reloaded }
  - name: restart app
    ansible.builtin.service: { name: app, state: restarted }
```

---

## 3. `notify` нескольким handler'ам и `listen`

```yaml
# вызвать несколько handler'ов
- ansible.builtin.template:
    src: app.conf.j2
    dest: /etc/app/app.conf
  notify:
    - restart app
    - reload nginx
    - clear cache
```

```yaml
# listen — «тема», по которой откликается несколько handler'ов
tasks:
  - ansible.builtin.template:
      src: ssl.conf.j2
      dest: /etc/nginx/conf.d/ssl.conf
    notify: "ssl updated"          # вызываем ТЕМУ

handlers:
  - name: reload nginx
    listen: "ssl updated"
    ansible.builtin.service: { name: nginx, state: reloaded }

  - name: reload haproxy
    listen: "ssl updated"
    ansible.builtin.service: { name: haproxy, state: reloaded }

  - name: уведомить в чат
    listen: "ssl updated"
    ansible.builtin.uri: { url: "{{ chat_webhook }}", method: POST }
```
`listen` удобен в ролях: роль публикует «событие», а какие handler'ы на него подпишутся —
решает тот, кто роль использует.

---

## 4. `meta: flush_handlers` — выполнить немедленно

Иногда ждать конца play нельзя:

```yaml
tasks:
  - name: Конфиг БД
    ansible.builtin.template: { src: pg.conf.j2, dest: /etc/postgresql/16/main/postgresql.conf }
    notify: restart postgresql

  - name: Применить handler'ы ПРЯМО СЕЙЧАС
    ansible.builtin.meta: flush_handlers        # ⭐

  - name: Миграции (нужен уже перезапущенный postgres)
    ansible.builtin.command: /opt/app/migrate.sh
```

Типичные сценарии: миграции после рестарта БД, проверка здоровья до продолжения,
раскатка с `serial`, где рестарт должен произойти внутри волны.

---

## 5. Handler'ы и ошибки

```yaml
- hosts: web
  force_handlers: true        # ⭐ выполнить накопленные handler'ы даже если play упал
```
```bash
ansible-playbook site.yml --force-handlers
```

Без этого: если после `notify` какая-то задача упала, handler **не выполнится** —
и получится состояние «конфиг новый, сервис на старом». Именно поэтому:
- критичные handler'ы вызывают через `flush_handlers` сразу после изменения;
- либо включают `force_handlers`.

> ⚠️ Handler, который сам упал, ведёт себя как обычная упавшая задача: хост выбывает из play.

---

## 6. Типовые ошибки с handler'ами

| Ошибка | Симптом | Лечение |
|--------|---------|---------|
| Имя в `notify` не совпадает с `name` handler'а | Тихо ничего не происходит (или ошибка в новых версиях) | Копировать имя посимвольно; вынести имена в константы-соглашения |
| Ожидание порядка «как в notify» | Handler'ы выполняются не так, как думал | Порядок = порядок объявления в `handlers` |
| Handler не выполнился, потому что задача `ok` | «Конфиг поменял руками — сервис не перезапустился» | Это правильное поведение: Ansible сравнивает с описанным состоянием |
| Handler не выполнился из-за падения play | Конфиг новый, сервис старый | `force_handlers` / `flush_handlers` |
| `restart` там, где хватает `reload` | Лишний даунтайм | `reloaded` для nginx/haproxy/postgres, `restarted` — когда иначе нельзя |
| Handler вызван в `--check` | Ничего не выполняется | Норма: в check mode handler'ы только «показываются» |
| Два handler'а с одинаковым именем в разных ролях | Выполнится не тот | Префиксовать именами ролей: `nginx : reload nginx` |

---

## 7. ⭐ Идемпотентность: как её добиваться на практике

**Критерий:** второй прогон плейбука даёт `changed=0`.

```bash
ansible-playbook site.yml           # 1-й прогон: changed=N
ansible-playbook site.yml           # 2-й прогон: changed=0  ← цель
```

### Чек-лист «почему у меня changed каждый раз»

| Причина | Как увидеть | Лечение |
|---------|-------------|---------|
| `command`/`shell` без ограничителей | Задача всегда `changed` | `creates:`/`removes:`, `changed_when:` |
| `state: latest` у пакетов | `changed` при обновлениях | `state: present` или фиксация версии |
| `service: state=restarted` в задаче | `changed` всегда | `state: started` + handler |
| Шаблон с меняющимися данными (дата, случайное) | `--diff` показывает отличие в одной строке | Убрать нестабильное из шаблона |
| `file` с `recurse: true` на большом дереве | `changed` из-за прав новых файлов | Точечные права, не рекурсивно |
| `get_url` без `checksum` | Перекачивает | `checksum:` + `creates:` |
| `unarchive` без `creates` | Распаковывает каждый раз | `creates:` |
| `lineinfile` без `regexp` | Добавляет дубли | `regexp:` |
| `git` с плавающей веткой | Подтягивает новые коммиты | Фиксированный тег/коммит |
| `pip`/`npm install` без проверки | Всегда `changed` | `creates:`, lock-файлы, `state: present` |

### Инструменты диагностики
```bash
ansible-playbook site.yml --diff | grep -B5 changed      # что именно меняется
ansible-playbook site.yml --check --diff                 # что собирается менять
ANSIBLE_CALLBACKS_ENABLED=profile_tasks ansible-playbook site.yml   # какие задачи «шумят»
```

### Как правильно сделать `shell` идемпотентным

```yaml
# ❌ шумит всегда
- ansible.builtin.shell: /opt/app/bin/setup.sh

# ✅ вариант 1 — маркерный файл
- ansible.builtin.command: /opt/app/bin/setup.sh
  args:
    creates: /opt/app/.setup_done

# ✅ вариант 2 — предварительная проверка
- ansible.builtin.stat: { path: /opt/app/.setup_done }
  register: marker
- ansible.builtin.command: /opt/app/bin/setup.sh
  when: not marker.stat.exists

# ✅ вариант 3 — интерпретация вывода
- ansible.builtin.command: /opt/app/bin/sync.sh
  register: sync
  changed_when: "'Updated' in sync.stdout"
  failed_when: sync.rc not in [0, 3]
```

> 🎤 **Формулировка для собеса:** «Идемпотентность — повторный запуск плейбука
> не меняет систему, если она уже в нужном состоянии. Модуль сначала проверяет
> текущее состояние и действует только при расхождении. Практический критерий —
> `changed=0` на втором прогоне. Ломают её обычно `command`/`shell` без `creates`
> и `changed_when`, `state: latest` и `restarted` вместо handler'а».

---

## 8. Полный пример: идемпотентный плейбук с handler'ами

```yaml
---
- name: Веб-сервер
  hosts: web
  become: true
  vars:
    nginx_packages: [nginx, curl]

  tasks:
    - name: Пакеты установлены
      ansible.builtin.apt:
        name: "{{ nginx_packages }}"
        state: present               # не latest
        update_cache: true
        cache_valid_time: 3600

    - name: Каталог приложения
      ansible.builtin.file:
        path: /var/www/app
        state: directory
        owner: www-data
        mode: "0755"

    - name: Основной конфиг
      ansible.builtin.template:
        src: nginx.conf.j2
        dest: /etc/nginx/nginx.conf
        mode: "0644"
        backup: true
        validate: "nginx -t -c %s"
      notify: reload nginx

    - name: Конфиг сайта
      ansible.builtin.template:
        src: site.conf.j2
        dest: /etc/nginx/conf.d/site.conf
        mode: "0644"
      notify: reload nginx

    - name: Проверка конфигурации (не меняет состояние)
      ansible.builtin.command: nginx -t
      changed_when: false            # ⭐ иначе вечный changed
      failed_when: false
      register: nginx_test

    - name: Сервис запущен и включён
      ansible.builtin.service:
        name: nginx
        state: started               # не restarted!
        enabled: true

  handlers:
    - name: reload nginx
      ansible.builtin.service:
        name: nginx
        state: reloaded
```

Проверка:
```text:no-line-numbers
1-й прогон: ok=5  changed=4   (+ RUNNING HANDLER reload nginx)
2-й прогон: ok=6  changed=0   ← handler не вызывался, сервис не трогали
```

---

## 💼 Как это в DevOps

- Handler — стандартный способ безопасно катить конфиги: 50 серверов, изменился конфиг
  на трёх — перезапустятся ровно три.
- `reload` вместо `restart` там, где сервис умеет: nginx, haproxy, postgres, sshd —
  это разница между «без обрывов» и «клиенты увидели ошибку».
- `flush_handlers` нужен в связке с `serial`: иначе при раскатке волнами рестарт
  произойдёт в самом конце для всех сразу — то есть общий даунтайм вместо rolling update.
- Идемпотентность — критерий приёмки на ревью: «запусти дважды, покажи `changed=0`».
- В CI прогон плейбука дважды (второй — проверка на `changed=0`) — дешёвый и очень
  показательный тест качества роли.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Перезапустить сервис при изменении конфига | `notify: restart svc` + секция `handlers` |
| Мягко перечитать конфиг | handler со `state: reloaded` |
| Вызвать несколько handler'ов | `notify:` списком |
| Одно событие → много handler'ов | `listen: "тема"` |
| Выполнить handler'ы немедленно | `ansible.builtin.meta: flush_handlers` |
| Выполнить handler'ы даже при падении | `force_handlers: true` / `--force-handlers` |
| Handler в роли | `roles/<role>/handlers/main.yml` |
| Убрать ложный `changed` | `changed_when: false` |
| Сделать `shell` идемпотентным | `creates:` / `changed_when:` / проверка через `stat` |
| Проверить идемпотентность | Запустить дважды, ждать `changed=0` |
| Посмотреть, что меняется | `--check --diff` |

---

## 🧠 Что запомнить

1. **Handler** — задача, вызываемая через `notify` и только при статусе `changed`.
2. Выполняется **один раз** и **в конце play**, даже если его позвали десять задач.
3. Порядок выполнения — как объявлено в секции `handlers`, а не как звали.
4. Имя в `notify` должно **точно** совпадать с `name` handler'а.
5. `listen` позволяет одному событию поднять несколько handler'ов (удобно в ролях).
6. `meta: flush_handlers` выполняет накопленные handler'ы немедленно.
7. При падении play handler'ы по умолчанию **не выполняются** — `force_handlers` спасает.
8. `state: restarted` в обычной задаче — антипаттерн; рестарт живёт в handler'е.
9. `reload` мягче `restart` — используй, если сервис поддерживает.
10. ⭐ Идемпотентность = повторный прогон ничего не меняет; критерий — `changed=0`.
11. Главные разрушители идемпотентности: `command`/`shell` без `creates`/`changed_when`,
    `state: latest`, `restarted`, нестабильные шаблоны, `get_url`/`unarchive` без ограничителей.
12. `changed_when: false` — обязательный спутник задач-проверок.

---

## Задачи

> ⭐ Здесь два вопроса из списка популярных на собесе: *«Что такое handler?»*
> и *«Что такое идемпотентность?»* — отвечай вслух.

---

### Блок A. Теория

**A1.** ⭐ Что такое handler и зачем он нужен? Ответь одним абзацем, как на собесе.

<details><summary>Ответ</summary>

Handler — специальная задача в секции `handlers`, которая выполняется только
по уведомлению `notify` и только если уведомившая задача завершилась со статусом `changed`.
Нужен, чтобы перезапускать/перечитывать сервисы исключительно при реальном изменении
конфигурации — это сохраняет идемпотентность и не создаёт лишних обрывов.

</details>

**A2.** При каком условии handler выполнится? А при каком — нет?

<details><summary>Ответ</summary>

Выполнится, если вызвавшая задача вернула `changed`. Не выполнится, если задача
`ok`/`skipped`/`failed`.

</details>

**A3.** Когда именно выполняются handler'ы?

<details><summary>Ответ</summary>

В конце play (после `tasks`; отдельно — после `pre_tasks`, после `roles`+`tasks`
и после `post_tasks`), либо немедленно по `meta: flush_handlers`.

</details>

**A4.** Сколько раз выполнится handler, если его вызвали пять задач?

<details><summary>Ответ</summary>

Один раз.

</details>

**A5.** ⭐ В каком порядке выполняются handler'ы: в порядке `notify` или в порядке объявления?

<details><summary>Ответ</summary>

В порядке **объявления** в секции `handlers`, а не в порядке `notify`.

</details>

**A6.** Что произойдёт, если имя в `notify` не совпадает с именем handler'а?

<details><summary>Ответ</summary>

В современных версиях — ошибка (`ERROR! The requested handler ... was not found`);
исторически — тихо игнорировалось, что было источником неприятных багов.

</details>

**A7.** Что делает `listen` и чем удобен в ролях?

<details><summary>Ответ</summary>

Позволяет привязать несколько handler'ов к одной «теме»: задача уведомляет тему,
а откликаются все подписанные. В ролях это даёт слабую связанность: роль публикует
событие, не зная, кто на него реагирует.

</details>

**A8.** Что делает `meta: flush_handlers` и когда это нужно?

<details><summary>Ответ</summary>

Выполняет все накопленные handler'ы немедленно. Нужно, когда последующие задачи
зависят от результата рестарта (миграции после перезапуска БД, health-check, раскатка
волнами).

</details>

**A9.** Выполнятся ли handler'ы, если play упал после `notify`? Как это изменить?

<details><summary>Ответ</summary>

По умолчанию не выполнятся. Лечится `force_handlers: true` в play или
`--force-handlers`, а лучше — `flush_handlers` сразу после критичного изменения.

</details>

**A10.** Чем `reload` лучше `restart` и когда `restart` неизбежен?

<details><summary>Ответ</summary>

`reload` перечитывает конфигурацию без разрыва обслуживания; `restart` нужен,
когда меняются параметры, которые нельзя применить на лету (порты, unit-файл, версия
бинарника).

</details>

**A11.** Где объявляются handler'ы в роли?

<details><summary>Ответ</summary>

В `roles/<role>/handlers/main.yml`.

</details>

**A12.** Что произойдёт с handler'ами в режиме `--check`?

<details><summary>Ответ</summary>

Handler'ы в check mode не выполняются (сообщается, что были бы уведомлены),
потому что реальных изменений не происходит.

</details>

**A13.** ⭐ Дай определение идемпотентности и назови практический критерий.

<details><summary>Ответ</summary>

Свойство операции давать одинаковый результат при любом числе применений.
Критерий: второй прогон плейбука даёт `changed=0`.

</details>

**A14.** Почему `service: state=restarted` в обычной задаче ломает идемпотентность?

<details><summary>Ответ</summary>

`restarted` — это действие, а не состояние: оно выполняется при каждом прогоне,
поэтому `changed` никогда не станет нулём и сервис будет перезапускаться без причины.

</details>

**A15.** Назови шесть причин, по которым плейбук показывает `changed` при каждом прогоне.

<details><summary>Ответ</summary>

`command`/`shell` без `creates`/`changed_when`; `state: latest`; `restarted`
в задаче; нестабильные данные в шаблоне (дата, случайные значения); `get_url`/`unarchive`
без `checksum`/`creates`; `lineinfile` без `regexp`; `git` с плавающей веткой;
`file` с `recurse` на изменяющемся дереве.

</details>

**A16.** Как сделать задачу `shell` идемпотентной? Три способа.

<details><summary>Ответ</summary>

`creates`/`removes`; предварительная проверка через `stat` + `when`;
`changed_when` по результату (`register` + анализ вывода/кода возврата).

</details>

**A17.** Почему `state: latest` считают источником проблем на проде?

<details><summary>Ответ</summary>

Обновление приезжает в произвольный момент (когда мейнтейнеры выпустили новую
версию), то есть прогон плейбука может незапланированно изменить рабочую систему.

</details>

**A18.** Как проверить, что именно меняется при каждом прогоне?

<details><summary>Ответ</summary>

`ansible-playbook --check --diff` и обычный прогон с `--diff`: видно построчные
различия и какие задачи дают `changed`.

</details>

**A19.** Может ли handler вызвать другой handler?

<details><summary>Ответ</summary>

Да, внутри handler'а можно указать `notify` на другой handler (он выполнится
после текущего, если объявлен позже).

</details>

**A20.** Что произойдёт, если handler упадёт?

<details><summary>Ответ</summary>

Handler ведёт себя как обычная задача: хост считается упавшим и выбывает
из дальнейшего выполнения play.

</details>

---

### Блок B. «Что произойдёт»

```yaml
# B1
tasks:
  - ansible.builtin.template: { src: a.j2, dest: /etc/a.conf }
    notify: restart app
  - ansible.builtin.template: { src: b.j2, dest: /etc/b.conf }
    notify: restart app
handlers:
  - name: restart app
    ansible.builtin.service: { name: app, state: restarted }
```
Вопрос: сколько раз перезапустится app, если изменились оба файла? А если ни один?

<details><summary>Ответ</summary>

Один раз (если изменился хотя бы один файл); ноль раз, если ни один не изменился.

</details>

```yaml
# B2
handlers:
  - name: restart app
    ansible.builtin.service: { name: app, state: restarted }
  - name: reload nginx
    ansible.builtin.service: { name: nginx, state: reloaded }
tasks:
  - ansible.builtin.template: { src: n.j2, dest: /etc/nginx/nginx.conf }
    notify:
      - reload nginx
      - restart app
```
Вопрос: в каком порядке выполнятся handler'ы?

<details><summary>Ответ</summary>

Сначала `restart app`, потом `reload nginx` — порядок определяется объявлением
в секции `handlers`, а не порядком в `notify`.

</details>

```yaml
# B3
tasks:
  - ansible.builtin.template: { src: pg.j2, dest: /etc/postgresql/postgresql.conf }
    notify: restart postgres
  - ansible.builtin.meta: flush_handlers
  - ansible.builtin.command: /opt/migrate.sh
```
Вопрос: зачем здесь `flush_handlers`?

<details><summary>Ответ</summary>

Чтобы postgres перезапустился **до** миграций; без `flush_handlers` handler
выполнился бы в конце play, и миграции пошли бы на старой конфигурации.

</details>

```yaml
# B4
tasks:
  - ansible.builtin.template: { src: a.j2, dest: /etc/a.conf }
    notify: restart app
  - ansible.builtin.command: /bin/false
handlers:
  - name: restart app
    ansible.builtin.service: { name: app, state: restarted }
```
Вопрос: перезапустится ли app? Что добавить, чтобы перезапустился?

<details><summary>Ответ</summary>

Не перезапустится: play упал до выполнения handler'ов. Добавить
`force_handlers: true` (или `meta: flush_handlers` сразу после изменения конфига).

</details>

```yaml
# B5
- ansible.builtin.service: { name: nginx, state: restarted }
```
Вопрос: что не так и как правильно?

<details><summary>Ответ</summary>

Рестарт при каждом прогоне — неидемпотентно. Правильно: `state: started`
в задаче + рестарт в handler'е по `notify`.

</details>

```yaml
# B6
- ansible.builtin.shell: docker pull myapp:latest && docker restart myapp
```
Вопрос: перечисли все проблемы этой задачи.

<details><summary>Ответ</summary>

`shell` вместо модулей; `latest` — непредсказуемая версия; `docker restart`
безусловный (каждый прогон); нет проверки успешности pull; нет health-check;
задача всегда `changed`. Правильно: `community.docker.docker_container` с конкретным
тегом образа.

</details>

```yaml
# B7
- ansible.builtin.command: nginx -t
  changed_when: false
  failed_when: false
  register: t
```
Вопрос: зачем оба ключа?

<details><summary>Ответ</summary>

`changed_when: false` — проверка не меняет систему; `failed_when: false` —
результат проверки обрабатывается дальше вручную, а не валит плейбук.

</details>

---

### Блок C. Практика

#### C1. 🔑 Первый handler

Напиши плейбук: шаблон `nginx.conf.j2` → `/etc/nginx/nginx.conf` с `notify: reload nginx`
и handler с `state: reloaded`.
1. Запусти — handler выполнился?
2. Запусти ещё раз — выполнился?
3. Измени шаблон, запусти — выполнился?
4. Измени конфиг **на сервере руками**, запусти — что произошло и почему это правильно?

#### C2. Порядок handler'ов

Объяви два handler'а (`A`, `B`) в секции в порядке A, B. В задаче вызови их
`notify: [B, A]`. Проверь порядок в выводе. Запиши вывод.

<details><summary>Ответ</summary>

В выводе сначала A, потом B — вопреки порядку в `notify`.

</details>

#### C3. Один handler — много вызовов

Сделай три задачи, меняющие три файла, все с `notify: restart app`.
Убедись по выводу, что `RUNNING HANDLER` был один раз.

#### C4. `listen`

Сделай тему `"certs updated"`, на которую подписаны два handler'а (перезагрузка nginx
и вывод сообщения). Вызови тему одной задачей.

#### C5. 🔑 `flush_handlers`

1. Сделай задачу, меняющую конфиг БД с `notify: restart db`.
2. Сразу после — задачу, которая требует уже перезапущенной БД.
3. Запусти без `flush_handlers` — что произошло?
4. Добавь `meta: flush_handlers` и сравни.

<details><summary>Ответ</summary>

Без `flush_handlers` задача, требующая перезапущенной БД, отработает на старой
конфигурации (или упадёт); с `flush_handlers` — после рестарта.

</details>

#### C6. Падение после notify

1. Добавь после `notify` задачу `command: /bin/false`.
2. Запусти — выполнился ли handler?
3. Добавь `force_handlers: true` в play и повтори.
4. Сформулируй, чем опасно состояние «конфиг новый, сервис старый».

<details><summary>Ответ</summary>

Без `force_handlers` handler пропускается; с ним — выполняется даже после падения.
Опасность состояния «конфиг новый, сервис старый»: следующий рестарт (например,
по перезагрузке сервера) применит непроверенную конфигурацию в неожиданный момент.

</details>

#### C7. 🔑 Охота на `changed`

Возьми свой плейбук из темы 06 и приведи его к `changed=0` на втором прогоне.
Для каждой «шумной» задачи запиши: причина → что исправил.

#### C8. Ломаем идемпотентность намеренно

Создай пять заведомо неидемпотентных задач (по одной на каждую причину из конспекта),
запусти дважды, зафиксируй `changed`, затем почини каждую и снова проверь.

#### C9. `shell` тремя способами

Сделай задачу `shell: /opt/init.sh` идемпотентной:
1. через `creates`;
2. через `stat` + `when`;
3. через `changed_when` по выводу.
Сравни, какой вариант читается лучше и почему.

<details><summary>Ответ</summary>

`creates` — самый читаемый и декларативный; `stat` + `when` — когда условие
сложнее файла; `changed_when` — когда скрипт сам сообщает, менял ли он что-то.

</details>

#### C10. `reload` vs `restart`

1. Запусти `watch -n0.5 curl -s -o /dev/null -w "%{http_code}\n" http://web1/` в соседнем окне
   (или в цикле).
2. Выполни handler с `restarted` и посмотри, были ли ошибки.
3. Повтори с `reloaded`.
Сделай вывод.

<details><summary>Ответ</summary>

При `restart` в цикле проверок обычно видны единичные ошибки соединения;
при `reload` — нет.

</details>

#### C11. Идемпотентность в CI (со звёздочкой)

Напиши джобу `.gitlab-ci.yml`, которая прогоняет плейбук дважды и падает,
если во втором прогоне `changed != 0` (подсказка: разбор вывода или `--check`
после первого прогона).

#### C12. Handler'ы и `serial`

Сделай play с `serial: 1`, конфигом через шаблон и handler'ом рестарта.
Убедись, что рестарт происходит **внутри волны** для каждого хоста, а не в конце для всех.

<details><summary>Ответ</summary>

С `serial: 1` handler'ы выполняются в конце play **для каждой волны**,
то есть для каждого хоста отдельно — именно это и даёт rolling update.

</details>

---

### Блок D. Инциденты

**D1.** Изменили шаблон, прогнали плейбук — конфиг обновился, а сервис работает
со старой конфигурацией. Три возможные причины.

<details><summary>Ответ</summary>

(1) Задача не уведомляет handler (`notify` забыт); (2) handler не выполнился
из-за падения play (нет `force_handlers`); (3) имя в `notify` не совпадает
с именем handler'а; плюс вариант — сервис требует `restart`, а делается `reload`.

</details>

**D2.** Handler не выполняется, ошибок нет. Что проверить в первую очередь?

<details><summary>Ответ</summary>

Совпадение имён `notify` и `name` handler'а, а также статус задачи —
если она `ok`, handler и не должен выполняться.

</details>

**D3.** Плейбук перезапускает nginx при каждом прогоне, хотя ничего не меняется.
Где искать?

<details><summary>Ответ</summary>

Ищем задачу, которая всегда `changed`: чаще всего шаблон с нестабильными данными
или `command`/`shell` без `changed_when`, либо `state: restarted` прямо в задаче.

</details>

**D4.** При раскатке на 30 хостов с `serial: 5` сервисы перезапустились все разом
в конце прогона. Что не так?

<details><summary>Ответ</summary>

Handler'ы выполняются в конце play; при `serial` они срабатывают в конце каждой
волны — если рестарт случился «в конце для всех», значит `serial` не применён
(или задачи разнесены по разным play). Проверить конфигурацию play и при необходимости
использовать `flush_handlers`.

</details>

**D5.** Ревьюер вернул MR с комментарием «плейбук неидемпотентен». Как проверить
и что показать в ответ?

<details><summary>Ответ</summary>

Запустить плейбук дважды и показать PLAY RECAP второго прогона с `changed=0`;
если `changed != 0` — пройтись по чек-листу причин и исправить.

</details>

**D6.** Плейбук упал на 8-й задаче, конфиг уже подменён, handler не отработал.
Сервис в рассинхроне. Как избежать в будущем (два механизма)?

<details><summary>Ответ</summary>

(1) `meta: flush_handlers` сразу после критичного изменения;
(2) `force_handlers: true` (или `--force-handlers`). Дополнительно — `validate:`,
чтобы битый конфиг вообще не доехал.

</details>

**D7.** В роли два handler'а с именем `restart app` (своя роль и зависимость).
Что произойдёт и как правильно именовать?

<details><summary>Ответ</summary>

Имена handler'ов глобальны в рамках play, и при совпадении сработает не тот,
который ожидался. Именовать с префиксом роли: `nginx restart`, `app restart`,
или использовать `listen` с уникальными темами.

</details>

**D8.** Задача `git` с `version: main` даёт `changed` в половине прогонов.
Почему и как сделать предсказуемо?

<details><summary>Ответ</summary>

Ветка движется: новые коммиты → `changed`. Для предсказуемости — фиксировать
тег или SHA коммита.

</details>

**D9.** `--check` показывает, что handler «будет выполнен», но в реальном прогоне
он не выполняется. Объясни.

<details><summary>Ответ</summary>

В check mode изменения не применяются, значит задача может отчитаться `changed`
условно; в реальном прогоне файл уже совпадает с описанным состоянием, задача даёт `ok`
и handler не вызывается.

</details>

**D10.** После добавления `ignore_errors: true` к задаче с `notify` handler перестал
выполняться в части случаев. Почему?

<details><summary>Ответ</summary>

`ignore_errors` не делает упавшую задачу `changed`: если задача провалилась,
уведомления не будет. Уведомление отправляет только успешная задача со статусом `changed`.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Что такое handler? (популярный вопрос роадмапа)

<details><summary>Ответ</summary>

Задача, выполняемая по `notify` только при `changed` и только один раз за play;
типичное применение — перезапуск сервиса при изменении конфигурации.

</details>

**2.** Когда handler выполняется и сколько раз?

<details><summary>Ответ</summary>

При статусе `changed` уведомившей задачи; один раз в конце play (или по `flush_handlers`).

</details>

**3.** В каком порядке выполняются handler'ы?

<details><summary>Ответ</summary>

В порядке объявления в секции `handlers`.

</details>

**4.** Как заставить handler выполниться немедленно?

<details><summary>Ответ</summary>

`ansible.builtin.meta: flush_handlers`.

</details>

**5.** Что будет с handler'ами, если плейбук упадёт?

<details><summary>Ответ</summary>

По умолчанию не выполнятся; `force_handlers: true` или `--force-handlers` это меняет.

</details>

**6.** ⭐ Что такое идемпотентность? (популярный вопрос роадмапа)

<details><summary>Ответ</summary>

Повторное применение не меняет систему, если она уже в нужном состоянии; модуль
проверяет состояние и действует только при расхождении.

</details>

**7.** Как проверить, что плейбук идемпотентен?

<details><summary>Ответ</summary>

Запустить дважды и убедиться, что второй прогон даёт `changed=0`.

</details>

**8.** Почему `shell` ломает идемпотентность и как это чинить?

<details><summary>Ответ</summary>

`shell` выполняет команду без понимания состояния и всегда рапортует `changed`;
лечится `creates`/`removes`, `changed_when`, предварительной проверкой или
заменой на профильный модуль.

</details>

**9.** Почему нельзя писать `state: restarted` в обычной задаче?

<details><summary>Ответ</summary>

Потому что это действие, выполняемое каждый раз: ломается идемпотентность
и возникает лишний даунтайм. Рестарт — в handler.

</details>

**10.** Чем `reload` отличается от `restart` и что выбрать?

<details><summary>Ответ</summary>

`reload` перечитывает конфигурацию без разрыва соединений, `restart` полностью
перезапускает процесс. Выбираем `reload`, если сервис его поддерживает и изменение
применимо на лету.

</details>

---

### 🎯 Чек-лист

- [ ] ⭐ Объясняю handler вслух за 30 секунд
- [ ] ⭐ Объясняю идемпотентность вслух и называю критерий `changed=0`
- [ ] Знаю, что порядок handler'ов — по объявлению, а не по `notify`
- [ ] Пробовал `listen` и `flush_handlers`
- [ ] Проверил поведение при падении play и знаю про `force_handlers`
- [ ] Использую `reload` там, где это возможно
- [ ] Привёл свой плейбук к `changed=0` на втором прогоне
- [ ] Умею чинить `shell` тремя способами
- [ ] Знаю шесть причин «вечного changed» наизусть
