---
title: "04. Сборщики логов: Fluentd, Fluent Bit, Filebeat, Grafana Alloy, Vector"
description: "Конвейер сборщика, сравнение агентов, буферизация, multiline, маскирование, мониторинг агента"
---

# 04. Сборщики логов: Fluentd, Fluent Bit, Filebeat, Grafana Alloy, Vector

> Роадмап → 7. Остальное → Логи → *«И инструментами, которые их собирают:
> Fluentd, Filebeat, FluentBit»*.
>
> **После темы ты умеешь:** выбрать сборщик под задачу, настроить чтение и парсинг,
> понимать буферизацию и не терять логи.

---

## 🗺️ Что делает сборщик

```text:no-line-numbers
 ┌────────────────────────────────────────────────────────────────────┐
 │ 1. INPUT      читать: файлы (tail), stdout контейнеров, journald,  │
 │               syslog, TCP/UDP, Windows Event Log, Kafka            │
 ├────────────────────────────────────────────────────────────────────┤
 │ 2. PARSE      разобрать строку: JSON, logfmt, regex/grok, multiline│
 ├────────────────────────────────────────────────────────────────────┤
 │ 3. FILTER     обогатить (метаданные пода/контейнера), выбросить    │
 │               лишнее, замаскировать секреты, переименовать поля    │
 ├────────────────────────────────────────────────────────────────────┤
 │ 4. BUFFER     ⭐ накопить при недоступности приёмника,             │
 │               ретраи, ограничение памяти/диска                     │
 ├────────────────────────────────────────────────────────────────────┤
 │ 5. OUTPUT     отправить: Loki, Elasticsearch, Kafka, S3, stdout    │
 └────────────────────────────────────────────────────────────────────┘
```

Это единый конвейер у всех сборщиков — различаются реализация, вес и экосистема.

---

## 1. Сравнение

| | **Fluent Bit** | **Fluentd** | **Filebeat** | **Grafana Alloy** | **Vector** |
|---|---------------|-------------|--------------|-------------------|------------|
| Язык | C | Ruby | Go | Go | Rust |
| Память | ~10-40 МБ ⭐ | 100-500 МБ | ~50-100 МБ | ~100 МБ+ (зависит от набора компонентов) | ~50 МБ |
| Плагины | ~100 (встроены) | 1000+ (gem) | Elastic-экосистема | Компоненты Loki / Prometheus / OpenTelemetry | Много, растёт |
| Куда пишет | Куда угодно | Куда угодно | В основном Elastic | Loki, Prometheus, OTLP (Tempo и др.) | Куда угодно |
| Сложные преобразования | Ограниченно | ⭐ Сильно | Средне | Средне (`loki.process`, OTel-процессоры) | ⭐ Сильно (VRL) |
| Типовая роль | Агент на ноде | Агрегатор | Агент для ELK | Агент для Loki и всего стека Grafana | Агент/агрегатор |
| Порог входа | Низкий | Средний | Низкий | Средний (свой синтаксис конфига) | Средний |

> ⚠️ **Promtail** (Go, ~50 МБ, умел писать только в Loki) — **EOL с 02.03.2026**, поэтому
> его нет в таблице. В новых проектах не ставится; в легаси встречается и мигрируется
> на Alloy командой `alloy convert` (см. [«Loki + Grafana», §3](/logging/03-loki-grafana)).

```text:no-line-numbers
Частая архитектура в больших инсталляциях:

  агент на каждой ноде          агрегатор (несколько штук)        хранилище
  Fluent Bit / Filebeat  ───►   Fluentd / Vector / Logstash  ───► ES / Loki / S3
  (лёгкий, быстрый)             (парсинг, маршрутизация, буфер)
```

> 💡 Правило выбора: **Loki → Alloy**, **Elastic → Filebeat**,
> **много источников и приёмников → Fluent Bit (+ Fluentd/Vector как агрегатор)**.

---

## 2. Fluent Bit

```ini
# fluent-bit.conf
[SERVICE]
    Flush         5
    Log_Level     info
    Parsers_File  parsers.conf
    storage.path  /var/log/flb-storage/     # буфер на диске
    storage.sync  normal

[INPUT]
    Name              tail
    Path              /var/log/containers/*.log
    Parser            docker
    Tag               kube.*
    Mem_Buf_Limit     50MB                  # ⭐ лимит буфера в памяти
    storage.type      filesystem            # ⭐ переполнение уходит на диск
    Refresh_Interval  10
    DB                /var/log/flb_kube.db  # позиции чтения (аналог registry)

[FILTER]
    Name                kubernetes
    Match               kube.*
    Merge_Log           On                  # разобрать JSON из поля log
    Keep_Log            Off
    K8S-Logging.Parser  On

[FILTER]
    Name    modify
    Match   *
    Remove  password
    Remove  token

[OUTPUT]
    Name       loki
    Match      kube.*
    Host       loki
    Port       3100
    Labels     job=fluentbit, cluster=prod
    Label_Keys $kubernetes['namespace_name'],$kubernetes['container_name']

[OUTPUT]
    Name   es
    Match  app.*
    Host   elasticsearch
    Index  logs
    Retry_Limit 5
```
Плюсы: очень лёгкий, стандарт для DaemonSet в Kubernetes, встроенный фильтр `kubernetes`
(добавляет namespace, pod, labels), поддержка десятков выходов.

---

## 3. Fluentd

```ruby
# fluent.conf
<source>
  @type tail
  path /var/log/app/*.log
  pos_file /var/log/td-agent/app.pos
  tag app.logs
  <parse>
    @type json
  </parse>
</source>

<filter app.**>
  @type record_transformer
  <record>
    env "prod"
    hostname "#{Socket.gethostname}"
  </record>
</filter>

<match app.**>
  @type elasticsearch
  host elasticsearch
  port 9200
  logstash_format true
  <buffer>
    @type file                       # ⭐ дисковый буфер
    path /var/log/td-agent/buffer
    flush_interval 10s
    retry_max_interval 30
    chunk_limit_size 8MB
    total_limit_size 8GB
    overflow_action block            # block | drop_oldest_chunk | throw_exception
  </buffer>
</match>
```
Плюсы: тысяча плагинов, сложная маршрутизация и агрегация, зрелость.
Минусы: Ruby, заметно тяжелее, требует внимания к настройке буферов.

---

## 4. Filebeat

```yaml
filebeat.inputs:
  - type: filestream
    id: app-logs
    paths: ['/var/log/app/*.log']
    parsers:
      - ndjson: { target: '', overwrite_keys: true }
      - multiline:
          type: pattern
          pattern: '^[[:space:]]'
          negate: false
          match: after

processors:
  - add_host_metadata: ~
  - drop_event:
      when: { contains: { message: 'healthcheck' } }

output.elasticsearch:
  hosts: ['http://elasticsearch:9200']
  index: 'logs-%{[agent.version]}-%{+yyyy.MM.dd}'
  bulk_max_size: 1600

queue.mem:
  events: 4096
  flush.min_events: 512
```
Плюсы: родной для Elastic Stack, модули для nginx/postgres/system из коробки
(`filebeat modules enable nginx`), простая настройка. Минус: за пределами Elastic
менее удобен.

---

## 5. Grafana Alloy (и легаси Promtail)

Конфигурация разобрана в [«Loki + Grafana»](/logging/03-loki-grafana).
Главное: что читать — `local.file_match` / `discovery.docker`, чтение —
`loki.source.file` / `loki.source.docker` / `loki.source.journal`, лейблы —
`discovery.relabel`, разбор — `loki.process` со стадиями `stage.*`, отправка —
`loki.write`; позиции чтения — в каталоге `--storage.path`.

| Где | Как ставят Alloy |
|-----|------------------|
| Docker / VM | Образ `grafana/alloy` или пакет + systemd; конфиг `/etc/alloy/config.alloy` |
| Kubernetes | Helm-чарт `grafana/alloy` DaemonSet'ом; поды — `discovery.kubernetes` + `loki.source.kubernetes` |
| Отладка | Веб-UI на `:12345`: граф компонентов, здоровье, текущие аргументы и экспорт каждого |

> ⚠️ **Promtail — EOL с 02.03.2026** (ни версий, ни исправлений безопасности). Его заменил
> **Alloy** — единый агент Grafana для метрик, логов, трейсов и профилей. Синтаксис
> другой (бывший River, HCL-подобный), идеи те же: `scrape_configs` → компоненты
> `loki.source.*`, `pipeline_stages` → `loki.process`, `positions.yaml` → `--storage.path`.
> Легаси-конфиг: `alloy convert --source-format=promtail --output=config.alloy promtail.yml`.

---

## 6. Буферизация — то, из-за чего теряют логи

```text:no-line-numbers
приёмник недоступен (Loki/ES лежит, сеть моргнула)
        │
        ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ буфер в ПАМЯТИ     быстро, но теряется при рестарте агента   │
 │ буфер на ДИСКЕ ⭐  переживает рестарт, ограничен размером     │
 └──────────────────────────────────────────────────────────────┘
        │ буфер переполнился
        ▼
 стратегия: block (тормозим чтение) | drop (теряем логи) | throw (ошибка)
```

| Сборщик | Ключевые параметры |
|---------|--------------------|
| Fluent Bit | `Mem_Buf_Limit`, `storage.type filesystem`, `storage.total_limit_size` |
| Fluentd | `<buffer>`: `@type file`, `total_limit_size`, `overflow_action`, `retry_*` |
| Filebeat | `queue.mem`/`queue.disk`, `bulk_max_size`, ретраи бесконечные по умолчанию |
| Alloy (`loki.write`) | `batch_wait`, `batch_size`, ретраи `max_backoff_retries`/`max_backoff_period`; позиции — в `--storage.path` |
| Promtail (легаси) | `batchwait`, `batchsize`, ретраи в `clients`; позиции в `positions.yaml` |

> ⚠️ У Alloy очередь отправки в Loki — в памяти. Если Loki недоступен дольше, чем
> покрывают ретраи `loki.write` (по умолчанию 10 попыток с backoff до 5 минут), пачки
> отбрасываются и растёт `loki_write_dropped_entries_total` — позиции чтения к этому
> моменту уже сдвинуты, записи не вернуть. WAL для `loki.write` пока experimental,
> поэтому за этой метрикой следят и алертят.

⭐ Три файла/механизма, которые решают «дубли и потери»:
позиция чтения (`DB` у Fluent Bit, `pos_file` у Fluentd, `registry` у Filebeat,
каталог `--storage.path` у Alloy, `positions.yaml` у легаси Promtail). Если они лежат
внутри контейнера без тома — после рестарта агент перечитает файлы заново или потеряет
место остановки.

---

## 7. Парсинг, multiline и маскирование

```ini
# Fluent Bit: multiline для Java/Python стектрейсов
[INPUT]
    Name             tail
    Path             /var/log/app/*.log
    multiline.parser java, python
```
```yaml
# Filebeat: своё правило
parsers:
  - multiline:
      type: pattern
      pattern: '^\d{4}-\d{2}-\d{2}'   # новая запись начинается с даты
      negate: true
      match: after
```
```text:no-line-numbers
// Alloy: склейка и маскирование в loki.process
loki.process "app" {
  stage.multiline {
    firstline     = "^\\d{4}-\\d{2}-\\d{2}"    // новая запись начинается с даты
    max_wait_time = "3s"
  }
  stage.replace {                                 // маскирование: группа заменяется на ***
    expression = "password=(\\S+)"
    replace    = "***"
  }
  forward_to = [loki.write.local.receiver]
}
```

> ⭐ Маскирование в сборщике — вторая линия защиты. Первая — не писать секреты
> в лог вообще (см. [«Основы логирования»](/logging/01-logging-concepts)).

---

## 8. Эксплуатация сборщиков

| Вопрос | Практика |
|--------|----------|
| Мониторинг агента | У всех есть `/metrics`: Fluent Bit `:2020`, Alloy `:12345` (плюс UI), Filebeat monitoring |
| Ключевые метрики | Прочитано/отправлено записей, ошибки отправки, размер очереди, дропы |
| Алерты | Агент не работает, растут ошибки отправки, растёт буфер, логи не поступают (`absent`) |
| Ресурсы | На ноде агент ограничивают по CPU/памяти, чтобы он не мешал приложениям |
| Права | Доступ к каталогам логов и docker.sock — по минимуму (read-only) |
| Обновления | Форматы конфигов между мажорными версиями меняются — читать changelog |

```text:no-line-numbers
# полезные алерты по агентам
absent(up{job="alloy"}) == 1
rate(fluentbit_output_retries_failed_total[5m]) > 0
rate(loki_write_dropped_entries_total[5m]) > 0     # Alloy не смог доставить записи в Loki
```

---

## 9. Грабли

| Грабля | Симптом | Решение |
|--------|---------|---------|
| Позиции чтения внутри контейнера | Дубли/потери после рестарта | Вынести на том |
| Только буфер в памяти | Потеря логов при рестарте агента | Дисковый буфер |
| Нет лимита буфера | Агент съедает память ноды | `Mem_Buf_Limit`, `total_limit_size` |
| Не настроен multiline | Стектрейс развален | Правила multiline |
| Агент читает свои же логи | Бесконечный цикл | Исключить путь агента |
| Логи не парсятся | «Сырые» строки в хранилище | Проверить парсер и порядок фильтров |
| Слишком много лейблов из метаданных | Взрыв кардинальности в Loki | Оставить только нужные |
| Агент без мониторинга | Тихо умер, логов нет | Метрики + алерт `absent` |

---

## 💼 Как это в DevOps

- В Kubernetes агент ставится DaemonSet'ом (Fluent Bit или Alloy; в легаси — Promtail), читает
  `/var/log/containers/*.log` и обогащает записи метаданными подов — это стандарт.
- На классических VM — systemd-сервис агента, раскатанный Ansible-ролью, плюс logrotate
  для локальных файлов.
- Выбор сборщика почти всегда определяется приёмником: Elastic → Filebeat,
  Loki → Alloy, «зоопарк» → Fluent Bit.
- Promtail в легаси — плановая миграция: `alloy convert`, ревью конфига, замена по нодам.
- Буферы и позиции — первое, что проверяют при жалобах «логи теряются» или «логи дублируются».
- Сам агент — такой же сервис, за которым надо следить: метрики, алерты, лимиты ресурсов.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Лёгкий агент на ноду | Fluent Bit |
| Сложная маршрутизация и обработка | Fluentd / Vector / Logstash |
| Стек Elastic | Filebeat (+ модули) |
| Стек Loki | Grafana Alloy (Promtail — EOL, мигрировать `alloy convert`) |
| Не терять логи при недоступности приёмника | Дисковый буфер + ретраи |
| Не потерять место чтения | `DB` / `pos_file` / `registry` / `--storage.path` Alloy на томе |
| Склеить стектрейс | `multiline.parser` / `multiline` / `stage.multiline` |
| Замаскировать секрет | `modify`/`record_transformer`/`stage.replace` |
| Выбросить шум | `drop_event`, `stage.drop`, фильтр по содержимому |
| Метрики агента | Fluent Bit `:2020/api/v1/metrics/prometheus`, Alloy `:12345/metrics` |
| Проверить конфиг | `fluent-bit -c file --dry-run`, `filebeat test config`, `alloy fmt config.alloy` |
| Посмотреть, что реально шлётся | Временный вывод в `stdout` |

---

## 🧠 Что запомнить

1. Любой сборщик — это конвейер: input → parse → filter → buffer → output.
2. Fluent Bit — лёгкий агент (C), Fluentd — мощный агрегатор (Ruby), Filebeat — для Elastic,
   Grafana Alloy — для Loki и всего стека Grafana (Promtail — EOL), Vector — универсальный на Rust.
3. Типовая архитектура для больших инсталляций: лёгкий агент на ноде + агрегатор.
4. ⭐ Дисковый буфер и лимиты — то, что отделяет «логи доехали» от «логи потеряли».
5. Файл позиций чтения должен жить на томе, иначе рестарт даёт дубли или потери.
6. Multiline настраивается в сборщике, иначе стектрейсы бесполезны.
7. Маскирование секретов в сборщике — вторая линия защиты после приложения.
8. Обогащение метаданными (namespace, pod, container) делает логи в k8s осмысленными.
9. Агент — сервис, за которым следят: метрики, алерты `absent`, лимиты CPU/памяти.
10. Выбор сборщика чаще всего диктует приёмник, а не личные предпочтения.

---

## Задачи

> Стенд: Loki-стек (для Alloy/Fluent Bit) и/или ELK-стенд (для Filebeat).

---

### Блок A. Теория

**A1.** Из каких пяти этапов состоит конвейер любого сборщика?

<details><summary>Ответ</summary>

Input (чтение), parse (разбор), filter (обогащение/фильтрация/маскирование),
buffer (накопление и ретраи), output (отправка).

</details>

**A2.** Сравни Fluent Bit, Fluentd, Filebeat, Grafana Alloy и Vector: язык, вес, типовая роль.

<details><summary>Ответ</summary>

Fluent Bit — C, ~10-40 МБ, лёгкий агент; Fluentd — Ruby, сотни МБ, мощный
агрегатор с тысячей плагинов; Filebeat — Go, агент экосистемы Elastic с готовыми модулями;
Grafana Alloy — Go, агент для Loki и всего стека Grafana (метрики, трейсы; Promtail —
его EOL-предшественник); Vector — Rust, универсальный агент/агрегатор с языком
преобразований VRL.

</details>

**A3.** Какая архитектура применяется в больших инсталляциях и зачем нужен агрегатор?

<details><summary>Ответ</summary>

Лёгкий агент на каждой ноде + агрегатор в нескольких экземплярах. Агрегатор
снимает нагрузку парсинга с нод, централизует маршрутизацию и буферизацию, уменьшает
число подключений к хранилищу.

</details>

**A4.** Как выбрать сборщик под конкретный проект?

<details><summary>Ответ</summary>

По приёмнику и задачам: Elastic → Filebeat, Loki → Alloy,
много источников/приёмников и ограниченные ресурсы → Fluent Bit,
сложные преобразования → Fluentd/Vector.

</details>

**A5.** ⭐ Что такое буферизация и чем дисковый буфер отличается от буфера в памяти?

<details><summary>Ответ</summary>

Накопление записей до подтверждения приёмником. Память — быстро, но теряется
при рестарте агента и ограничена; диск — переживает рестарт, вмещает больше,
но медленнее и требует места.

</details>

**A6.** Что происходит при переполнении буфера? Какие стратегии бывают?

<details><summary>Ответ</summary>

Стратегии: блокировать чтение (backpressure), отбрасывать старые/новые записи,
завершаться с ошибкой. Выбор зависит от того, что важнее — полнота логов или
работоспособность агента.

</details>

**A7.** Зачем нужен файл позиций чтения и что будет, если он потеряется?

<details><summary>Ответ</summary>

Хранит смещение, на котором остановилось чтение каждого файла.
Без него после рестарта агент либо читает файлы заново (дубли), либо начинает с конца
(потери).

</details>

**A8.** Почему файл позиций нельзя держать внутри контейнера без тома?

<details><summary>Ответ</summary>

Потому что при пересоздании контейнера файл исчезает — гарантированные дубли
или потери. Его монтируют на том/hostPath.

</details>

**A9.** Что такое multiline и как он настраивается в трёх разных сборщиках?

<details><summary>Ответ</summary>

Склейка многострочных записей. Fluent Bit — `multiline.parser java, python`;
Filebeat — `parsers.multiline` с pattern/negate/match; Alloy — `stage.multiline`
с `firstline` в `loki.process`.

</details>

**A10.** Как маскировать секреты в сборщике? Почему это только вторая линия защиты?

<details><summary>Ответ</summary>

Фильтрами: `modify`/`record_transformer`/`stage.replace` с регулярками.
Вторая линия — потому что секрет уже попал в файл на диске ноды, и лучше не писать
его вовсе.

</details>

**A11.** Зачем обогащать логи метаданными Kubernetes и какие поля обычно добавляют?

<details><summary>Ответ</summary>

Чтобы логи были осмысленными: namespace, pod, container, node, labels
приложения. Без этого неясно, кто написал строку.

</details>

**A12.** Какие метрики самого агента нужно мониторить?

<details><summary>Ответ</summary>

Прочитанные и отправленные записи, ошибки и ретраи отправки, размер очереди/буфера,
число дропнутых записей, использование памяти.

</details>

**A13.** Какие алерты настроишь по агенту сбора логов?

<details><summary>Ответ</summary>

Агент не работает (`up == 0` / `absent`), растут ошибки отправки,
растут дропы, логи от источника не поступают (`absent_over_time` по потоку).

</details>

**A14.** Почему агенту ограничивают CPU и память на ноде?

<details><summary>Ответ</summary>

Чтобы всплеск логов не «съел» ресурсы ноды и не повлиял на приложения;
в k8s это `requests/limits` у DaemonSet.

</details>

**A15.** Как проверить конфиг сборщика до применения?

<details><summary>Ответ</summary>

`fluent-bit -c fluent-bit.conf --dry-run`, `filebeat test config` и
`filebeat test output`, `alloy fmt config.alloy`, `fluentd --dry-run -c fluent.conf`.

</details>

**A16.** Что случилось с Promtail и что делать, если он стоит в проекте?

<details><summary>Ответ</summary>

Promtail — EOL с 02.03.2026: без новых версий и исправлений безопасности.
Преемник — Grafana Alloy. Легаси-конфиг переводят `alloy convert --source-format=promtail`,
проверяют результат (отчёт `--report`, UI Alloy) и меняют агент по нодам.

</details>

---

### Блок B. «Что делает / что тут не так»

```ini
B1.  [INPUT]
     Name tail
     Path /var/log/containers/*.log
     DB   /var/log/flb_kube.db
     Mem_Buf_Limit 50MB
     storage.type filesystem

B2.  [INPUT]
     Name tail
     Path /var/log/*.log
     # ни DB, ни storage.type, ни Mem_Buf_Limit

B3.  [FILTER]
     Name modify
     Match *
     Remove password

B4.  [OUTPUT]
     Name loki
     Match *
     Labels job=fluentbit
     Label_Keys $trace_id
```

<details><summary>Ответ (Fluent Bit)</summary>

**B1.** Корректная конфигурация: есть позиции, лимит памяти и дисковый буфер.
**B2.** Нет позиций и лимитов — дубли/потери и риск съесть память.
**B3.** Удаление поля `password` — правильная практика маскирования.
**B4.** ⚠️ `trace_id` как лейбл Loki — взрыв кардинальности.

</details>

```yaml
B5.  # Fluentd
     <buffer>
       @type memory
       overflow_action drop_oldest_chunk
     </buffer>

B6.  # Filebeat
     parsers:
       - multiline: { type: pattern, pattern: '^\d{4}-\d{2}-\d{2}', negate: true, match: after }

B7.  # Alloy в compose
     command: [run, --storage.path=/tmp/alloy, /etc/alloy/config.alloy]   # /tmp без тома

B8.  # Alloy, loki.process
     stage.json {
       expressions = {request_id = "request_id"}
     }
     stage.labels {
       values = {request_id = ""}
     }

B9.  # Fluent Bit агент читает /var/log/*.log, включая собственный лог

B10. # Агент без лимитов ресурсов на ноде с приложениями

B11. # Новый кластер, агент для Loki: DaemonSet с образом grafana/promtail
```

<details><summary>Ответ (разные сборщики)</summary>

**B5.** Буфер в памяти + отбрасывание старых чанков: при недоступности приёмника логи
теряются. Для важных логов нужен файловый буфер.
**B6.** Корректное правило multiline: новая запись начинается с даты.
**B7.** Позиции в `/tmp` контейнера — потеряются при пересоздании.
**B8.** `request_id` в лейблах — недопустимо.
**B9.** Самочтение логов агента порождает лавину; путь агента надо исключить.
**B10.** Без лимитов агент может помешать приложениям на ноде.
**B11.** ⚠️ Promtail — EOL с 02.03.2026; в новый кластер ставят Alloy (чарт `grafana/alloy`).

</details>

---

### Блок C. Практика

#### C1. Alloy: файлы и позиции
1. Настрой чтение `/var/log/*.log` (`local.file_match` + `loki.source.file`), проверь логи в Grafana.
2. Найди файл позиций в каталоге `--storage.path` (подкаталог с именем компонента,
   например `loki.source.file.system/`), посмотри содержимое.
3. Удали его, перезапусти агент — что произошло с логами?
4. Вынеси `--storage.path` на том и повтори эксперимент.

<details><summary>Ответ</summary>

После удаления файла позиций агент перечитает файлы согласно настройкам —
типично это приводит к дублям.

</details>

#### C2. 🔑 Fluent Bit вместо Alloy
1. Подними Fluent Bit, настрой `tail` + вывод в Loki.
2. Сравни потребление памяти с Alloy (`docker stats`).
3. Добавь второй `OUTPUT` в stdout и посмотри, что реально отправляется.

<details><summary>Ответ</summary>

Fluent Bit обычно потребляет заметно меньше памяти, чем Alloy и Filebeat.

</details>

#### C3. Парсинг
Настрой разбор JSON-логов приложения и logfmt-логов (например, от Loki/Grafana).
Убедись, что поля доступны для фильтрации.

#### C4. Multiline
Сгенерируй Java/Python стектрейс. Настрой склейку в Fluent Bit (или Filebeat/Alloy),
проверь, что запись одна.

#### C5. Маскирование
Залогируй строку с `password=secret123`. Настрой маскирование в сборщике,
убедись, что в хранилище приходит `password=***`.

#### C6. 🔑 Буферизация и потеря логов
1. Останови Loki (или Elasticsearch).
2. Продолжай генерировать логи 2-3 минуты.
3. Запусти приёмник обратно — доехали ли логи?
4. Повтори эксперимент с буфером только в памяти и с дисковым, сравни.

<details><summary>Ответ</summary>

С дисковым буфером логи доезжают после восстановления приёмника;
с памятью — теряются при рестарте агента или переполнении.

</details>

#### C7. Переполнение буфера
Ограничь буфер маленьким значением, создай большой поток логов при остановленном
приёмнике и посмотри, что происходит (дропы/блокировка) и что пишет агент.

#### C8. Метрики агента
Найди `/metrics` своего агента, определи метрики: прочитано, отправлено, ошибки, дропы.
Добавь агент как таргет в Prometheus и построй график.

<details><summary>Ответ</summary>

Fluent Bit отдаёт метрики на `:2020/api/v1/metrics/prometheus`,
Alloy — на `:12345/metrics` (там же веб-UI).

</details>

#### C9. Алерты по агенту
Настрой два алерта: агент недоступен (`absent`/`up==0`) и растут ошибки отправки.
Проверь их, остановив приёмник.

#### C10. Filebeat (если поднимал ELK)
Настрой Filebeat с модулем nginx, проверь, что поля разобраны (`http.response.status_code`),
и сравни удобство с ручным grok.

<details><summary>Ответ</summary>

Модули Filebeat сразу дают разобранные поля ECS — заметно удобнее ручного grok,
но менее гибко.

</details>

#### C11. Легаси: Promtail → Alloy (по желанию)
Возьми легаси `promtail.yml` с `positions`, `pipeline_stages.multiline` и `replace`
(можно из [«Loki + Grafana»](/logging/03-loki-grafana), §3, дописав стадии), сконвертируй
`alloy convert --source-format=promtail --report=report.txt --output=converted.alloy promtail.yml`
и найди в результате, во что превратились позиции, multiline и маскирование.

<details><summary>Ответ</summary>

Позиции уходят в каталог `--storage.path` (старый `positions.yaml` можно
подхватить аргументом `legacy_positions_file` у `loki.source.file`), `pipeline_stages` —
в `loki.process` со `stage.multiline` и `stage.replace`.

</details>

---

### Блок D. Инциденты

**D1.** После рестарта агента все логи пришли повторно. Причина?

<details><summary>Ответ</summary>

Потерян/не сохранён файл позиций (или он в контейнере без тома);
агент начал читать файлы с начала.

</details>

**D2.** После рестарта ноды часть логов потерялась. Что не было настроено?

<details><summary>Ответ</summary>

Буфер был только в памяти и/или логи писались локально без отправки;
нужен дисковый буфер и сбор из stdout.

</details>

**D3.** Агент съел 4 ГБ памяти и был убит OOM. Разбор.

<details><summary>Ответ</summary>

Не задан лимит буфера, приёмник был недоступен, логи копились в памяти.
Нужны `Mem_Buf_Limit`/`total_limit_size`, дисковый буфер и лимиты контейнера.

</details>

**D4.** Логи не доезжают, в логах агента — ошибки подключения к приёмнику.
Что проверить и что настроить, чтобы это не приводило к потерям?

<details><summary>Ответ</summary>

Доступность приёмника, сеть и DNS, лимиты приёма на стороне хранилища,
корректность адреса и аутентификации; настроить дисковый буфер и ретраи,
чтобы простой приёмника не приводил к потере.

</details>

**D5.** В хранилище приходят «сырые» строки без полей. Где ошибка?

<details><summary>Ответ</summary>

Не сработал парсер: неправильный порядок фильтров, не тот формат,
поле с логом называется иначе (`log` vs `message`), JSON внутри строки не раскрыт
(`Merge_Log`/`decode_json_fields`).

</details>

**D6.** Стектрейсы разваливаются, хотя multiline настроен. Что проверишь?

<details><summary>Ответ</summary>

Шаблон первой строки не совпадает с реальным форматом, лог уже разбит
на записи источником (docker json-file по строкам), таймаут склейки слишком мал,
несколько парсеров конфликтуют.

</details>

**D7.** Число потоков в Loki выросло в 100 раз после правки конфига агента. Что случилось?

<details><summary>Ответ</summary>

В лейблы попало высококардинальное поле (`request_id`, `ip`, `pod` с хешем
или что-то подобное). Убрать лейбл, оставить значение в теле строки.

</details>

**D8.** Агент читает собственные логи и создаёт лавину записей. Как чинить?

<details><summary>Ответ</summary>

Исключить путь логов агента из input (`Exclude_Path`, отдельный путь),
либо писать логи агента в другое место/уровень.

</details>

**D9.** Часть нод не шлёт логи, остальные работают. Алгоритм разбора.

<details><summary>Ответ</summary>

Сравнить версии конфигов и агентов на нодах, проверить доступность приёмника
из этих нод (сеть, DNS, firewall), права на каталоги логов, метрики и логи самих агентов,
переполнение диска на этих нодах.

</details>

**D10.** Нужно отправлять одни логи в Loki, другие — в Elasticsearch и копию в S3.
Как построишь конвейер?

<details><summary>Ответ</summary>

Разные `OUTPUT`/`match` по тегам/лейблам: часть потоков — в Loki, часть —
в Elasticsearch, плюс отдельный выход в S3 (или через агрегатор Fluentd/Vector,
который дублирует поток).

</details>

---

### Блок E. Вопросы с собеседования

**1.** Какие сборщики логов знаешь и чем они отличаются?

<details><summary>Ответ</summary>

Fluent Bit, Fluentd, Filebeat, Grafana Alloy (преемник Promtail), Vector, Logstash — различаются весом,
экосистемой и возможностями преобразований.

</details>

**2.** Что такое Fluent Bit и почему его ставят агентом?

<details><summary>Ответ</summary>

Лёгкий агент на C: минимальное потребление, встроенный фильтр Kubernetes,
много выходов — идеален как DaemonSet.

</details>

**3.** Чем Fluentd отличается от Fluent Bit?

<details><summary>Ответ</summary>

Fluentd тяжелее (Ruby), но гибче: тысячи плагинов, сложная маршрутизация и буферизация;
часто используется как агрегатор, а Fluent Bit — как агент.

</details>

**4.** Как не потерять логи при недоступности хранилища?

<details><summary>Ответ</summary>

Дисковый буфер, ретраи, лимиты и backpressure; плюс мониторинг очереди и дропов.

</details>

**5.** Что такое файл позиций и зачем он нужен?

<details><summary>Ответ</summary>

Файл со смещениями чтения: защищает от повторной отправки и потерь после рестарта.

</details>

**6.** Как настроить склейку стектрейсов?

<details><summary>Ответ</summary>

Правилами multiline в сборщике (или записью стектрейса одним полем JSON
из приложения).

</details>

**7.** Как обогащают логи метаданными в Kubernetes?

<details><summary>Ответ</summary>

Фильтром Kubernetes: добавляются namespace, pod, container, labels, node.

</details>

**8.** Как маскировать секреты в логах?

<details><summary>Ответ</summary>

Фильтрами сборщика (удаление/замена по регулярке); главная защита — не писать
секреты в лог.

</details>

**9.** Как мониторить сам сборщик логов?

<details><summary>Ответ</summary>

По его же метрикам `/metrics` в Prometheus: отправленные записи, ошибки, очередь,
дропы; плюс алерт на отсутствие агента.

</details>

**10.** Как отправлять логи в несколько мест одновременно?

<details><summary>Ответ</summary>

Несколько выходов с маршрутизацией по тегам/лейблам либо агрегатор, который
дублирует поток в несколько приёмников.

</details>

---

### 🎯 Чек-лист

- [ ] Знаю конвейер input → parse → filter → buffer → output
- [ ] Могу выбрать сборщик под приёмник и задачу
- [ ] ⭐ Настроил дисковый буфер и проверил, что логи не теряются
- [ ] Файл позиций вынесен на том
- [ ] Настроил multiline и проверил на стектрейсе
- [ ] Настроил маскирование секретов
- [ ] Обогащаю логи метаданными контейнера/пода
- [ ] Агент отдаёт метрики, они в Prometheus
- [ ] Есть алерты на агента и ошибки отправки
- [ ] Умею отправлять логи в несколько приёмников
