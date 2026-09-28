---
title: "05. Алерты и Alertmanager"
description: "Правило алерта, жизненный цикл, маршрутизация, группировка, inhibit, silence, dead man's switch"
---

# 05. Алерты и Alertmanager

> Роадмап → Мониторинг → Prometheus: *«`Alertmanager`»*.
>
> **После темы ты умеешь:** написать правило алерта, объяснить его жизненный цикл,
> настроить маршрутизацию и группировку уведомлений, подключить телеграм и ставить silence.

---

## 🗺️ Разделение ролей

```text:no-line-numbers
 ┌───────────────────────────────┐        ┌──────────────────────────────────┐
 │ PROMETHEUS                    │        │ ALERTMANAGER                      │
 │ • хранит метрики              │ алерты │ • ГРУППИРУЕТ (20 хостов = 1 письмо)│
 │ • каждые evaluation_interval  │───────►│ • МАРШРУТИЗИРУЕТ (кому и куда)     │
 │   считает правила             │  HTTP  │ • ПОДАВЛЯЕТ (inhibition)           │
 │ • решает: firing или нет      │        │ • ГЛУШИТ на время (silence)        │
 │                               │        │ • ПОВТОРЯЕТ (repeat_interval)      │
 └───────────────────────────────┘        └───────────────┬──────────────────┘
                                                          ▼
                                     Telegram · почта · Slack · PagerDuty · webhook
```

⭐ Типичный вопрос на собесе: *«Кто решает, что алерт сработал?»* — **Prometheus**.
Alertmanager только доставляет, группирует и подавляет.

---

## 1. Правило алерта

```yaml
# /etc/prometheus/rules/alerts.yml
groups:
  - name: infra
    interval: 30s
    rules:
      - alert: InstanceDown
        expr: up == 0
        for: 2m                            # ⭐ условие должно держаться 2 минуты
        labels:
          severity: critical
          team: infra
        annotations:
          summary: "Инстанс {{ $labels.instance }} недоступен"
          description: "Job {{ $labels.job }} не отвечает более 2 минут."
          runbook: "https://wiki.internal/runbooks/instance-down"

      - alert: DiskWillFillIn4Hours
        expr: |
          predict_linear(node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"}[6h], 4*3600) < 0
          and node_filesystem_avail_bytes / node_filesystem_size_bytes < 0.3
        for: 10m
        labels: { severity: warning }
        annotations:
          summary: "Диск {{ $labels.mountpoint }} на {{ $labels.instance }} заполнится за 4 часа"
          description: "Свободно {{ $value | humanize1024 }}B."

      - alert: HighErrorRate
        expr: |
          sum by (job) (rate(http_requests_total{status=~"5.."}[5m]))
            / sum by (job) (rate(http_requests_total[5m])) > 0.05
        for: 5m
        labels: { severity: critical }
        annotations:
          summary: "{{ $labels.job }}: {{ $value | humanizePercentage }} ошибок"
```

| Поле | Зачем |
|------|-------|
| `alert` | Имя (в CamelCase, по нему группируют и ищут) |
| `expr` | PromQL: если вернул непустой результат — алерт «горит» |
| `for` | Сколько условие должно держаться до отправки (гасит дребезг) |
| `labels` | Метаданные для маршрутизации: `severity`, `team`, `env` |
| `annotations` | Текст для человека: `summary`, `description`, `runbook` |

Переменные в шаблонах: <code v-pre>{{ $labels.X }}</code>, <code v-pre>{{ $value }}</code>,
функции `humanize`, `humanizePercentage`, `humanizeDuration`, `humanize1024`.

### Жизненный цикл

```text:no-line-numbers
      условие ложно            условие истинно        держится for
 ┌──────────────┐  ────────►  ┌──────────┐  ───────►  ┌─────────┐  ──► Alertmanager
 │   INACTIVE   │             │ PENDING  │            │ FIRING  │
 └──────────────┘  ◄────────  └──────────┘  ◄───────  └─────────┘
                    условие снова ложно (resolved)
```
Смотреть: UI Prometheus → `/alerts` (видны состояния) и `/rules` (ошибки вычисления).

---

## 2. Конфигурация Alertmanager

```yaml
# alertmanager.yml
global:
  resolve_timeout: 5m

route:
  receiver: default                       # куда по умолчанию
  group_by: ['alertname', 'cluster']      # ⭐ что считать одним инцидентом
  group_wait: 30s                         # подождать «соседей» перед первым письмом
  group_interval: 5m                      # как часто слать обновления группы
  repeat_interval: 4h                     # как часто напоминать о незакрытом алерте
  routes:
    - matchers: ['severity = critical']
      receiver: telegram-oncall
      group_wait: 10s
      repeat_interval: 1h
    - matchers: ['team = db']
      receiver: telegram-db
    - matchers: ['severity = info']
      receiver: 'null'                    # не уведомлять вообще

receivers:
  - name: default
    email_configs:
      - to: devops@example.com

  - name: telegram-oncall
    telegram_configs:
      - bot_token_file: /etc/alertmanager/tg_token
        chat_id: -1001234567890
        parse_mode: HTML
        message: |
          <b>{{ .Status | toUpper }}</b> {{ .CommonLabels.alertname }}
          {{ range .Alerts }}• {{ .Annotations.summary }}
          {{ end }}

  - name: telegram-db
    telegram_configs:
      - bot_token_file: /etc/alertmanager/tg_token
        chat_id: -1009876543210

  - name: 'null'

inhibit_rules:
  # если инстанс лежит целиком — не спамить алертами про его диски и сервисы
  - source_matchers: ['alertname = InstanceDown']
    target_matchers: ['severity =~ "warning|info"']
    equal: ['instance']
```

```bash
amtool check-config alertmanager.yml            # ⭐ проверка синтаксиса
amtool config routes test severity=critical team=db    # куда уйдёт такой алерт
```

---

## 3. Группировка, подавление, silence — три механизма против шума

```text:no-line-numbers
ГРУППИРОВКА (group_by)
20 серверов упали одновременно → 1 уведомление со списком, а не 20 сообщений

ПОДАВЛЕНИЕ (inhibit_rules)
InstanceDown (critical) подавляет DiskSpaceLow (warning) на том же инстансе
⇒ в мессенджер уходит причина, а не 15 следствий

SILENCE (временное глушение, вручную)
"Плановые работы на db1 с 02:00 до 04:00" → алерты по db1 не приходят
```

```bash
# silence из командной строки
amtool silence add instance=db1 --duration=2h --comment="Плановый апгрейд" --author=nurik
amtool silence query                       # список активных
amtool silence expire <id>                 # снять досрочно
```
Silence ставят **до** начала работ и всегда с комментарием и автором — иначе
через месяц никто не вспомнит, почему алерты молчат.

---

## 4. Severity и маршрутизация

| Severity | Что означает | Куда |
|----------|--------------|------|
| `critical` | Пользователи страдают прямо сейчас | Звонок/пейджер/телеграм дежурному, 24/7 |
| `warning` | Скоро станет плохо, есть время | Чат команды, рабочее время |
| `info` | Для сведения, действий не требует | Дашборд/лог, часто `receiver: 'null'` |

```text:no-line-numbers
Проверка здравого смысла для critical:
«Разбудил бы я этим человека в 3 часа ночи?»
Нет → это не critical.
```

Типовая схема маршрутизации:
```text:no-line-numbers
route
├── severity=critical  → телеграм дежурного + повтор каждый час
├── team=db            → чат DBA
├── team=frontend      → чат фронтенда
├── env=stage          → чат разработки (никогда не будит людей)
└── default            → общий чат devops
```

---

## 5. Правила хороших алертов (то, за что скажут спасибо)

1. **Алертим симптом.** «Доля 5xx > 5%», «p99 > 2 с», «сервис недоступен» —
   а не «CPU 80%» и не «мало свободной памяти».
2. **Каждому алерту — рунбук.** Ссылка в аннотации: что проверить, какие команды,
   когда эскалировать.
3. **`for` обязателен.** Без него ловишь одиночные всплески.
4. **Пороги — из SLO**, а не «на глаз» (см. тему «Что мониторить»).
5. **Про исчезновение метрик тоже алерт:** `up == 0`, `absent()`.
6. **Dead man's switch:** правило, которое всегда `firing`, и внешняя система,
   которая шумит, если это уведомление **перестало** приходить. Так ловят «мониторинг умер».
```yaml
      - alert: Watchdog
        expr: vector(1)
        labels: { severity: none }
        annotations: { summary: "Мониторинг жив" }
```
7. **Регулярный аудит.** Раз в квартал: какие алерты сработали, какие были ложными,
   какие никто не чинил. Ложные и бесполезные — удалять.

---

## 6. Эксплуатация

| Вопрос | Практика |
|--------|----------|
| Отказоустойчивость | Alertmanager собирают в кластер (`--cluster.peer`), Prometheus отправляет во все узлы, дублирующиеся уведомления дедуплицируются |
| Секреты | Токены — через `*_file` (файл/секрет), не в конфиге в git |
| Проверка | `promtool check rules` + `amtool check-config` в CI |
| Тест доставки | `amtool` или тестовый алерт через API `/api/v2/alerts` |
| Уведомления о восстановлении | `send_resolved: true` в receiver |
| Тишина по расписанию | `time_intervals` + `mute_time_intervals` (например, не будить по ночам warning'ами) |

```yaml
time_intervals:
  - name: nights
    time_intervals:
      - times: [{ start_time: '22:00', end_time: '08:00' }]
        location: 'Asia/Almaty'
route:
  routes:
    - matchers: ['severity = warning']
      receiver: telegram-team
      mute_time_intervals: [nights]
```

---

## 7. Грабли

| Грабля | Последствие | Решение |
|--------|-------------|---------|
| Нет `for` | Шум от кратковременных всплесков | `for: 5m` и больше |
| Всё `critical` | Дежурный перестаёт реагировать | Честная градация severity |
| Нет группировки | 50 сообщений об одном инциденте | `group_by` + `group_wait` |
| Нет inhibit-правил | Уведомления о следствиях вместо причины | Подавление по `instance`/`cluster` |
| Silence без срока и комментария | Алерты молчат месяцами | Всегда `--duration` и `--comment` |
| Алерт без рунбука | «Пришло, а что делать?» | Ссылка в аннотации |
| Правила не проверяются в CI | Сломанный файл — и алертов нет вообще | `promtool check rules` |
| Токен бота в git | Утечка канала уведомлений | `bot_token_file` + секрет |
| Нет watchdog | Мониторинг умер — тишина воспринимается как «всё хорошо» | Dead man's switch |

---

## 💼 Как это в DevOps

- Правила алертов лежат в git рядом с конфигом Prometheus, проходят `promtool check rules`
  в CI и ревью — так же, как код.
- На каждый алерт заводится рунбук (даже на три строчки): это то, что реально экономит
  время в 4 утра.
- Дежурство строится вокруг severity: critical будит, warning ждёт до утра, info не шлётся.
- Плановые работы всегда сопровождаются silence с указанием автора и срока.
- Постмортем инцидента почти всегда добавляет или убирает алерт: либо «мы узнали поздно»,
  либо «нас разбудили зря».
- Хороший признак зрелости: число алертов за месяц уменьшается, а время реакции — падает.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Написать алерт | `alert/expr/for/labels/annotations` в `rules/*.yml` |
| Проверить правила | `promtool check rules rules/*.yml` |
| Посмотреть состояния | UI Prometheus → `/alerts` (pending/firing) |
| Проверить конфиг AM | `amtool check-config alertmanager.yml` |
| Узнать, куда уйдёт алерт | `amtool config routes test severity=critical` |
| Сгруппировать уведомления | `group_by: ['alertname','cluster']` |
| Подавить следствия | `inhibit_rules` с `equal: ['instance']` |
| Заглушить на время работ | `amtool silence add instance=db1 --duration=2h --comment='…'` |
| Не будить ночью warning'ами | `time_intervals` + `mute_time_intervals` |
| Уведомлять о восстановлении | `send_resolved: true` |
| Поймать «мониторинг умер» | Watchdog-алерт + внешняя проверка |
| Не потерять токен | `bot_token_file`, а не токен в конфиге |
| Повторять напоминание | `repeat_interval` |
| Отключить уведомления по классу | `receiver: 'null'` |

---

## 🧠 Что запомнить

1. Prometheus решает, что алерт сработал; Alertmanager группирует, маршрутизирует
   и доставляет.
2. Алерт = `expr` + `for` + `labels` + `annotations`; состояния — inactive → pending → firing.
3. ⭐ `for` обязателен: без него алерты дребезжат.
4. `labels` нужны для маршрутизации, `annotations` — для человека; в аннотациях
   всегда ссылка на рунбук.
5. Три механизма против шума: группировка, подавление (inhibit), silence.
6. Severity честная: critical — только то, ради чего будят ночью.
7. Алертить нужно симптомы, а пороги брать из SLO.
8. `up == 0` и `absent()` ловят исчезновение целей; watchdog ловит смерть мониторинга.
9. Silence всегда со сроком, автором и комментарием.
10. Правила проверяются `promtool`, конфиг — `amtool`, оба в CI; токены — через файлы-секреты.

---

## Задачи

> Стенд: Prometheus + Alertmanager из индекса раздела. Для практики удобно завести
> телеграм-бота (@BotFather) и тестовый чат.

---

### Блок A. Теория

**A1.** Кто решает, что алерт сработал: Prometheus или Alertmanager? За что отвечает каждый?

<details><summary>Ответ</summary>

Prometheus: вычисляет правила и определяет состояние алерта.
Alertmanager: принимает уже «горящие» алерты, группирует, подавляет, маршрутизирует,
глушит и доставляет уведомления.

</details>

**A2.** Из каких полей состоит правило алерта?

<details><summary>Ответ</summary>

`alert` (имя), `expr` (PromQL), `for` (длительность условия), `labels`
(метаданные для маршрутизации), `annotations` (текст для человека).

</details>

**A3.** ⭐ Зачем нужен `for` и что будет без него?

<details><summary>Ответ</summary>

Чтобы условие считалось проблемой, только если держится заданное время.
Без `for` любой единичный всплеск или пропуск сбора порождает уведомление.

</details>

**A4.** Опиши жизненный цикл алерта. Где посмотреть текущее состояние?

<details><summary>Ответ</summary>

`inactive` → `pending` (условие истинно, идёт отсчёт `for`) → `firing`
(отправляется в Alertmanager) → обратно в `inactive` (resolved).
Смотреть на странице `/alerts` Prometheus.

</details>

**A5.** Чем `labels` отличаются от `annotations`?

<details><summary>Ответ</summary>

`labels` — машинные метки (severity, team, env), по ним работает маршрутизация
и группировка. `annotations` — человекочитаемый текст: что случилось, что делать, ссылка
на рунбук.

</details>

**A6.** Что делает `group_by` и как выбрать правильные лейблы для группировки?

<details><summary>Ответ</summary>

Объединяет алерты в одно уведомление по указанным лейблам. Группировать надо
по тому, что делает инциденты «одинаковыми»: обычно `alertname` и `cluster`/`env`;
добавление `instance` разбивает группу на отдельные уведомления.

</details>

**A7.** Чем отличаются `group_wait`, `group_interval` и `repeat_interval`?

<details><summary>Ответ</summary>

`group_wait` — пауза перед первым уведомлением новой группы (чтобы собрать
«соседей»); `group_interval` — как часто отправлять обновления по изменившейся группе;
`repeat_interval` — как часто напоминать о всё ещё горящем алерте.

</details>

**A8.** Что такое inhibit rules? Приведи пример полезного подавления.

<details><summary>Ответ</summary>

Правила подавления: при наличии одного алерта не отправлять другие.
Пример: `InstanceDown` подавляет все warning'и на том же `instance`, чтобы приходила
причина, а не десяток следствий.

</details>

**A9.** Что такое silence и какие обязательные атрибуты у него должны быть?

<details><summary>Ответ</summary>

Временное глушение уведомлений по матчерам. Обязательны срок (`--duration`),
автор и комментарий — иначе алерты молчат «непонятно почему».

</details>

**A10.** Как организовать маршрутизацию по командам и severity?

<details><summary>Ответ</summary>

Через дерево `route` с `matchers` по лейблам: отдельные ветки для critical,
для команд (`team=db`, `team=frontend`), для окружения (`env=stage` — никогда не будит),
плюс default.

</details>

**A11.** Какие критерии у алерта уровня `critical`?

<details><summary>Ответ</summary>

Пользователи страдают сейчас, требуется немедленное действие, есть рунбук,
и на вопрос «разбудил бы этим человека в 3 ночи» ответ — да.

</details>

**A12.** Что такое dead man's switch (watchdog) и зачем он нужен?

<details><summary>Ответ</summary>

Постоянно срабатывающий алерт (`vector(1)`), который доезжает до внешней системы;
если уведомления перестали приходить — значит, умер Prometheus, Alertmanager или канал
доставки.

</details>

**A13.** Как сделать так, чтобы warning'и не будили ночью?

<details><summary>Ответ</summary>

`time_intervals` с ночным окном и `mute_time_intervals` на маршруте для `warning`;
маршрут critical остаётся без mute.

</details>

**A14.** Как обеспечить отказоустойчивость Alertmanager?

<details><summary>Ответ</summary>

Несколько экземпляров Alertmanager в кластере (`--cluster.peer`), Prometheus
шлёт алерты во все; кластер дедуплицирует уведомления. Плюс HA-пара Prometheus.

</details>

**A15.** Как проверять правила и конфигурацию в CI?

<details><summary>Ответ</summary>

`promtool check rules rules/*.yml` и `amtool check-config alertmanager.yml`
как обязательные шаги пайплайна, плюс тесты правил (`promtool test rules`).

</details>

---

### Блок B. «Оцени правило»

```yaml
B1.  - alert: HighCPU
       expr: node_load1 > 4
       labels: { severity: critical }
```

<details><summary>Ответ</summary>

Причина, а не симптом; нет `for`; `critical` не оправдан; нет аннотаций и рунбука.

</details>

```yaml
B2.  - alert: InstanceDown
       expr: up == 0
       for: 2m
       labels: { severity: critical }
       annotations: { summary: "{{ $labels.instance }} недоступен", runbook: "…" }
```

<details><summary>Ответ</summary>

Хороший алерт: симптом, разумный `for`, аннотации и рунбук.

</details>

```yaml
B3.  - alert: HighErrorRate
       expr: rate(http_requests_total{status=~"5.."}[5m]) > 0
       for: 1m
```

<details><summary>Ответ</summary>

Порог «больше нуля» — любая единичная ошибка поднимет алерт. Нужна доля ошибок.

</details>

```yaml
B4.  - alert: DiskSpaceLow
       expr: node_filesystem_avail_bytes < 10737418240
       for: 5m
```

<details><summary>Ответ</summary>

Абсолютное значение вместо доли: 10 ГБ — это много для диска на 20 ГБ и мало
для диска на 4 ТБ. Нужен процент (+ `predict_linear`).

</details>

```yaml
B5.  - alert: MemoryUsage
       expr: node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes < 0.1
       for: 15m
       labels: { severity: warning }
```

<details><summary>Ответ</summary>

Корректный алерт: относительный порог, длинный `for`, адекватная severity.

</details>

```yaml
B6.  - alert: Watchdog
       expr: vector(1)
       labels: { severity: none }
```

<details><summary>Ответ</summary>

Watchdog — правильный приём; severity специально нейтральная, маршрут отдельный.

</details>

```yaml
B7.  route: { group_by: ['...'], group_wait: 30s, repeat_interval: 5m }
```

<details><summary>Ответ</summary>

`repeat_interval: 5m` — слишком часто, превратится в спам.

</details>

```yaml
B8.  route: { group_by: ['alertname','instance','pod','container'] }
```

<details><summary>Ответ</summary>

Слишком детальная группировка: каждый под/контейнер даст своё уведомление.

</details>

```yaml
B9.  receivers:
       - name: tg
         telegram_configs:
           - bot_token: "123456:AAH..."      # прямо в конфиге в git
```

<details><summary>Ответ</summary>

Токен в конфиге в git — утечка; нужен `bot_token_file` и секрет.

</details>

```yaml
B10. inhibit_rules:
       - source_matchers: ['severity = critical']
         target_matchers: ['severity = warning']
         # equal не указан
```

<details><summary>Ответ</summary>

Без `equal` подавление применится глобально: critical в одном месте погасит
warning'и по всей инфраструктуре.

</details>

---

### Блок C. Практика

#### C1. 🔑 Первый алерт
1. Создай `rules/alerts.yml` с правилом `InstanceDown` (`up == 0`, `for: 2m`).
2. Проверь `promtool check rules`, перезагрузи конфиг.
3. Останови экспортер и понаблюдай переходы pending → firing на `/alerts`.
4. Запусти обратно — посмотри resolved.

<details><summary>Ответ</summary>

На `/alerts` видно состояние и время до перехода в firing.

</details>

#### C2. Подключить телеграм
1. Создай бота, узнай `chat_id`.
2. Настрой receiver с `bot_token_file`, проверь доставку.
3. Включи `send_resolved: true` и убедись, что приходит уведомление о восстановлении.

#### C3. Аннотации и шаблоны
Добавь в алерты `summary`, `description` с <code v-pre>{{ $labels }}</code> и <code v-pre>{{ $value | humanize }}</code>,
а также ссылку на рунбук. Проверь, как это выглядит в сообщении.

#### C4. Группировка
1. Подними 3 экспортера, останови все три.
2. Сравни поведение при `group_by: ['alertname']` и `group_by: ['alertname','instance']`.
3. Поиграй с `group_wait` (5s vs 60s) и опиши разницу.

<details><summary>Ответ</summary>

С `group_by: ['alertname']` придёт одно сообщение со списком инстансов;
с добавлением `instance` — три отдельных.

</details>

#### C5. Маршрутизация
Настрой три маршрута: critical → «дежурный» чат, `team=db` → другой чат,
`severity=info` → `null`. Проверь через `amtool config routes test`.

#### C6. Inhibit
1. Заведи алерты `InstanceDown` (critical) и `DiskSpaceLow` (warning) на одном инстансе.
2. Настрой подавление по `equal: ['instance']`.
3. Урони инстанс и убедись, что пришёл только один алерт.

<details><summary>Ответ</summary>

При правильном `equal: ['instance']` warning будет подавлен только на упавшем хосте.

</details>

#### C7. Silence
1. Поставь silence на инстанс на 10 минут через UI и через `amtool`.
2. Проверь, что уведомления не приходят.
3. Сними silence досрочно.

#### C8. 🔑 Набор алертов для своего стенда
Напиши минимум 8 правил: доступность, диск (порог + `predict_linear`), память, CPU-saturation,
доля ошибок, latency p99, рестарты процессов, watchdog. К каждому — рунбук в одну-две строки.

<details><summary>Ответ</summary>

Хороший набор: `InstanceDown`, `DiskSpaceLow`, `DiskWillFillIn4Hours`,
`MemoryLow`, `CPUSaturation`, `HighErrorRate`, `HighLatencyP99`, `TooManyRestarts`,
`Watchdog`, плюс `absent()` на ключевые job'ы.

</details>

#### C9. Ночная тишина
Настрой `time_intervals` так, чтобы `warning` не приходили с 22:00 до 08:00,
а `critical` приходили всегда. Проверь логикой маршрутов.

#### C10. Аудит алертов
Возьми получившийся набор и для каждого ответь: симптом или причина? разбудил бы ночью?
есть ли действие? Удали или понизь severity у тех, что не проходят проверку.

<details><summary>Ответ</summary>

Обычно после аудита набор сокращается на треть — это нормально и правильно.

</details>

---

### Блок D. Инциденты

**D1.** Ночью пришло 120 уведомлений об одном инциденте. Что настроить?

<details><summary>Ответ</summary>

Группировку (`group_by`, `group_wait`), inhibit-правила, адекватный
`repeat_interval`, а также пересмотр самих правил (возможно, алертов-следствий слишком много).

</details>

**D2.** Алерт `firing` в Prometheus, но уведомление не пришло. Где искать?

<details><summary>Ответ</summary>

Логи Prometheus (отправка в Alertmanager), `prometheus_notifications_dropped_total`,
логи Alertmanager, активные silence, маршрут (`amtool config routes test`),
доступность канала доставки (токен, chat_id, сеть).

</details>

**D3.** После планового обслуживания алерты продолжают приходить. Что забыли?

<details><summary>Ответ</summary>

Поставить silence на время работ (или он истёк раньше окончания работ).

</details>

**D4.** Дежурный не отреагировал на critical, потому что «их слишком много». Что делать системно?

<details><summary>Ответ</summary>

Системно: аудит и сокращение алертов, честная severity, группировка и подавление,
рунбуки, разделение каналов, регулярный разбор ложных срабатываний.

</details>

**D5.** Prometheus перезапустили, и все `for`-таймеры начались заново. Чем это опасно?

<details><summary>Ответ</summary>

После рестарта состояние `pending` начинается заново, поэтому алерты с большим
`for` могут задержаться. Опасно при частых рестартах Prometheus — проблема будет
обнаруживаться позже; лечится стабильностью Prometheus и HA-парой.

</details>

**D6.** Мониторинг лежал 6 часов, никто не заметил. Как предотвратить?

<details><summary>Ответ</summary>

Watchdog + внешняя система (Healthchecks.io, второй Prometheus, blackbox
со стороны), алерты на сам Prometheus и Alertmanager.

</details>

**D7.** Алерт про базу ушёл во фронтенд-чат. Что поправить?

<details><summary>Ответ</summary>

Лейблы алерта (`team=db`) и матчеры в маршрутах; проверить
`amtool config routes test team=db`.

</details>

**D8.** Уведомления приходят, но в них нет ни инстанса, ни значения. Что добавить?

<details><summary>Ответ</summary>

Аннотации с <code v-pre>{{ $labels.instance }}</code>, <code v-pre>{{ $value }}</code>, шаблон сообщения в receiver.

</details>

**D9.** Токен телеграм-бота утёк в публичный репозиторий. Действия?

<details><summary>Ответ</summary>

Немедленно отозвать/пересоздать токен у BotFather, удалить из истории репозитория,
перевести на `bot_token_file` с секретом, проверить, не использовался ли чат посторонними.

</details>

**D10.** После релиза правил алерты вообще перестали работать. Как это можно было поймать заранее?

<details><summary>Ответ</summary>

`promtool check rules` и `promtool test rules` в CI плюс smoke-проверка:
после деплоя правил убедиться, что watchdog продолжает приходить.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как работает алертинг в Prometheus?

<details><summary>Ответ</summary>

Prometheus периодически вычисляет правила; при выполнении условия дольше `for`
алерт переходит в firing и отправляется в Alertmanager.

</details>

**2.** Что делает Alertmanager?

<details><summary>Ответ</summary>

Группирует, подавляет, глушит по silence, маршрутизирует и доставляет уведомления,
дедуплицирует при кластере.

</details>

**3.** Зачем нужен параметр `for`?

<details><summary>Ответ</summary>

Чтобы отсечь кратковременные всплески и дребезг.

</details>

**4.** Как не получить 50 уведомлений об одном инциденте?

<details><summary>Ответ</summary>

Группировкой (`group_by`), подавлением следствий и разумными `group_wait`/`repeat_interval`.

</details>

**5.** Что такое inhibit rules?

<details><summary>Ответ</summary>

Правила, при которых один алерт подавляет другие (обычно причина подавляет следствия).

</details>

**6.** Что такое silence и как его ставить?

<details><summary>Ответ</summary>

Временное отключение уведомлений по матчерам; ставится через UI или `amtool`
со сроком, автором и комментарием.

</details>

**7.** Как маршрутизировать алерты по командам?

<details><summary>Ответ</summary>

Через лейблы алертов и дерево маршрутов с матчерами.

</details>

**8.** Какие алерты ты считаешь обязательными?

<details><summary>Ответ</summary>

Доступность сервиса, ошибки и latency (симптомы), место на диске с прогнозом,
память, лаг репликации, возраст бэкапа, watchdog.

</details>

**9.** Как понять, что сам мониторинг умер?

<details><summary>Ответ</summary>

Dead man's switch: постоянный алерт, отсутствие которого во внешней системе означает
поломку мониторинга.

</details>

**10.** Как бороться с alert fatigue?

<details><summary>Ответ</summary>

Аудит правил, честная severity, группировка и подавление, рунбуки, удаление
бесполезных алертов.

</details>

---

### 🎯 Чек-лист

- [ ] Написал правила алертов с `for`, labels и annotations
- [ ] Понимаю разделение ролей Prometheus / Alertmanager
- [ ] Настроил доставку в телеграм с токеном из файла
- [ ] Настроил группировку и проверил её эффект
- [ ] ⭐ Настроил inhibit-правила с `equal`
- [ ] Ставил silence через UI и `amtool`
- [ ] Сделал маршрутизацию по severity и командам
- [ ] Завёл watchdog и понимаю, зачем он
- [ ] К каждому алерту есть рунбук
- [ ] Правила и конфиг проверяются `promtool`/`amtool` в CI
