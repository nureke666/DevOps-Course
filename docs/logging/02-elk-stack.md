---
title: "02. ELK стек: Elasticsearch, Logstash, Kibana"
description: "Роли компонентов, модель данных Elasticsearch, Filebeat, Logstash/grok, ILM, ресурсы и эксплуатация"
---

# 02. ELK стек: Elasticsearch, Logstash, Kibana

> Роадмап → 7. Остальное → Логи → *«ELK стек: ElasticSearch, Logstash, Kibana»*.
> И там же: *«Этот стек можно изучать достаточно поверхностно… поднять ELK или Loki
> и потыкаться».*
>
> **После темы ты умеешь:** объяснить роль каждого компонента, поднять стек, понимать
> индексы, шарды и ILM, искать в Kibana и оценивать ресурсы.

---

## 🗺️ Из чего состоит стек

```text:no-line-numbers
 ┌──────────┐   ┌───────────┐   ┌─────────────────┐   ┌──────────┐
 │ источники│──►│ Beats /   │──►│   Logstash      │──►│Elastic-  │◄──┐
 │ логов    │   │ Fluent Bit│   │ (парсинг,       │   │search    │   │
 └──────────┘   │ (сбор)    │   │  обогащение)    │   │(хранение,│   │
                └───────────┘   └─────────────────┘   │ поиск)   │   │
                      │  (можно и напрямую, минуя Logstash) ▲         │
                      └─────────────────────────────────────┘         │
                                                                 ┌────┴────┐
                                                                 │ Kibana  │
                                                                 │(поиск,  │
                                                                 │ дашборды│
                                                                 └─────────┘
```

| Компонент | Роль | Ресурсы |
|-----------|------|---------|
| **Elasticsearch** | Хранение + полнотекстовый поиск (инвертированный индекс) | ⚠️ Самый прожорливый: RAM, CPU, диск |
| **Logstash** | Парсинг, обогащение, преобразование, маршрутизация | Тяжёлый (JVM); часто заменяют на Fluent Bit/Vector |
| **Kibana** | Интерфейс: поиск, дашборды, алерты | Лёгкий |
| **Beats** (Filebeat, Metricbeat…) | Лёгкие агенты сбора на хостах | Лёгкие |

> 💡 Сейчас чаще говорят «Elastic Stack»: Logstash в цепочке нередко отсутствует
> (Filebeat/Fluent Bit → Elasticsearch напрямую, парсинг — через ingest pipelines).
> Связку с заменой Logstash на Fluentd называют **EFK** — она популярна в Kubernetes.

---

## 1. Elasticsearch: модель данных

```text:no-line-numbers
Кластер
└── Индекс  logs-app-2026.09.13        ← аналог «таблицы»/«базы» за период
    ├── Шард 0 (primary)   ├── реплика 0      ← горизонтальное деление и отказоустойчивость
    ├── Шард 1 (primary)   └── реплика 1
    └── Документы (JSON)
        { "@timestamp": "...", "level": "error", "message": "...", "service": "billing" }
```

| Понятие | Смысл |
|---------|-------|
| Документ | JSON-запись (одна строка лога) |
| Индекс | Набор документов; логи бьют по дням/неделям |
| Шард | Часть индекса; определяет параллелизм и распределение по нодам |
| Реплика | Копия шарда на другой ноде: отказоустойчивость + чтение |
| Mapping | Схема полей (типы `keyword`, `text`, `date`, `long`) |
| Data stream | Современная абстракция над «пишем в текущий индекс, ротируем по правилам» |

⭐ Разница, которую спрашивают: `text` — поле анализируется (разбивается на токены,
подходит для полнотекстового поиска); `keyword` — хранится целиком (точное совпадение,
агрегации, сортировка). Поле `service` должно быть `keyword`, `message` — `text`.

Роли нод: master (управление кластером), data (хранение), ingest (предобработка),
coordinating (маршрутизация запросов). На маленьких инсталляциях всё совмещено.

---

## 2. Поднять стенд

```yaml
services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:9.5.0
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false          # ⚠️ только для учебного стенда (с 8.x security включена по умолчанию)
      - ES_JAVA_OPTS=-Xms1g -Xmx1g            # heap ≤ 50% RAM и ≤ ~31 ГБ
    ulimits:
      memlock: { soft: -1, hard: -1 }
    volumes: [esdata:/usr/share/elasticsearch/data]
    ports: ["9200:9200"]

  kibana:
    image: docker.elastic.co/kibana/kibana:9.5.0
    environment:
      - ELASTICSEARCH_HOSTS=http://elasticsearch:9200
    ports: ["5601:5601"]

  filebeat:
    image: docker.elastic.co/beats/filebeat:9.5.0
    user: root
    volumes:
      - ./filebeat.yml:/usr/share/filebeat/filebeat.yml:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro

volumes: { esdata: {} }
```
```bash
sudo sysctl -w vm.max_map_count=262144        # ⭐ иначе Elasticsearch не стартует
curl localhost:9200                            # версия и имя кластера
curl localhost:9200/_cluster/health?pretty     # status: green/yellow/red
```

> ⚠️ `yellow` на одной ноде — это нормально: реплики некуда размещать.
> `red` — часть данных недоступна, это уже инцидент.

---

## 3. Filebeat: сбор логов контейнеров

```yaml
# filebeat.yml
filebeat.inputs:
  - type: filestream                # ⭐ в 9.x inputs `log`/`container` устарели — Filebeat с ними не стартует
    id: docker-containers           # уникальный id обязателен: без него риск дублей, повтор id — ошибка старта
    paths: ['/var/lib/docker/containers/*/*.log']
    parsers:
      - container:                  # разобрать JSON-обёртку docker: log, stream, time
          stream: all
      - multiline:
          type: pattern
          pattern: '^[[:space:]]|^Traceback|^\s+at '
          negate: false
          match: after

processors:
  - add_docker_metadata: ~          # подставит имя контейнера, образ, лейблы
  - drop_fields:
      fields: ['agent.ephemeral_id', 'ecs.version']
  - decode_json_fields:             # если приложение пишет JSON
      fields: ['message']
      target: ''
      overwrite_keys: true

output.elasticsearch:
  hosts: ['http://elasticsearch:9200']
  index: 'logs-%{[container.image.name]}-%{+yyyy.MM.dd}'

setup.ilm.enabled: false
setup.template.name: 'logs'
setup.template.pattern: 'logs-*'
```

> ⚠️ Грабли 9.x: `filestream` по умолчанию узнаёт файл по fingerprint (первые байты)
> и начинает читать его, только когда он дорос до **1 КБ**. У свежего «тихого»
> контейнера логи в Kibana появятся не сразу — это не поломка. Старое поведение из 8.x
> возвращается `file_identity.native: ~` + `prospector.scanner.fingerprint.enabled: false`.

---

## 4. Logstash и парсинг (когда он всё-таки нужен)

```ruby
# logstash.conf
input {
  beats { port => 5044 }
}

filter {
  if [message] =~ /^\{/ {
    json { source => "message" }                 # уже структурный лог
  } else {
    grok {                                        # разбор текстового формата
      match => { "message" => '%{IPORHOST:client} - - \[%{HTTPDATE:ts}\] "%{WORD:method} %{URIPATH:path}[^"]*" %{NUMBER:status:int} %{NUMBER:bytes:int}' }
    }
    date { match => ["ts", "dd/MMM/yyyy:HH:mm:ss Z"] }
  }
  mutate { remove_field => ["ts"] }
  if [status] and [status] >= 500 { mutate { add_tag => ["server_error"] } }
}

output {
  elasticsearch {
    hosts => ["http://elasticsearch:9200"]
    index => "logs-nginx-%{+YYYY.MM.dd}"
  }
}
```

| Плагин | Зачем |
|--------|-------|
| `grok` | Разбор неструктурированного текста по шаблонам |
| `json` | Разбор JSON-строки в поля |
| `date` | Правильное `@timestamp` из поля лога |
| `mutate` | Переименование, удаление, приведение типов |
| `geoip`, `useragent` | Обогащение по IP и User-Agent |
| `drop` | Выбросить ненужные события (экономия) |

> 💡 Альтернатива Logstash — **ingest pipelines** прямо в Elasticsearch: те же парсеры
> (`grok`, `dissect`, `date`), но без отдельного тяжёлого JVM-сервиса.

---

## 5. Kibana: поиск и дашборды

```text:no-line-numbers
Discover  → поиск по логам (KQL), просмотр полей, сохранение запросов
Dashboard → панели: динамика ошибок, топ сервисов, коды ответов
Alerting  → правила на основе запросов (в т.ч. «больше N ошибок за 5 минут»)
Dev Tools → консоль для прямых запросов к API Elasticsearch  ⭐ полезнее всего
Stack Management → индексы, ILM, шаблоны, роли и пользователи
```

Запросы в Discover (KQL):
```text:no-line-numbers
level: "error"
level: "error" and service: "billing"
status >= 500
message: *timeout*
not service: "healthcheck"
```

Прямые запросы к API (Dev Tools или curl):
```bash
GET /_cat/indices?v&s=store.size:desc      # какие индексы и сколько весят
GET /_cat/nodes?v                          # ноды и их нагрузка
GET /_cluster/health?pretty
GET /logs-*/_search { "query": { "match": { "level": "error" } }, "size": 5 }
DELETE /logs-app-2026.08.01                # удалить старый индекс (осторожно)
```

---

## 6. ILM — управление жизненным циклом индексов ⭐

Без ILM Elasticsearch однажды съедает весь диск. Политика описывает фазы:

```text:no-line-numbers
HOT (пишем и часто ищем)  →  WARM (только чтение, меньше реплик)
      7 дней                      23 дня
        │                             │
        ▼                             ▼
   COLD (редкий доступ, сжатие)  →  DELETE (удаление)
        30-90 дней                    через 90 дней
```
```json
PUT _ilm/policy/logs-policy
{
  "policy": {
    "phases": {
      "hot":    { "actions": { "rollover": { "max_size": "30gb", "max_age": "1d" } } },
      "warm":   { "min_age": "7d",  "actions": { "shrink": { "number_of_shards": 1 },
                                                 "forcemerge": { "max_num_segments": 1 } } },
      "delete": { "min_age": "30d", "actions": { "delete": {} } }
    }
  }
}
```

---

## 7. Ресурсы, эксплуатация и грабли

| Вопрос | Практика |
|--------|----------|
| Память | Heap = 50% RAM, но не больше ~31 ГБ; остальное — под файловый кэш ОС |
| Диск | Планировать ×2-3 от сырого объёма логов (индексы + реплики) |
| Шарды | Размер шарда 20-50 ГБ; «много мелких шардов» — типовая болезнь кластера |
| Отказоустойчивость | Минимум 3 master-eligible ноды (кворум), реплика ≥ 1 |
| Безопасность | С 8.x (и в 9.x) security включена по умолчанию: пользователи, роли, TLS |
| Бэкап | Snapshot в S3/NFS репозиторий (`_snapshot`) |
| Обновления | Rolling upgrade, внимательно с несовместимостями мажорных версий |

| Грабля | Симптом | Решение |
|--------|---------|---------|
| `vm.max_map_count` по умолчанию | ES не стартует | `sysctl -w vm.max_map_count=262144` |
| Heap больше 31 ГБ | Производительность падает | Ограничить heap |
| Нет ILM | Диск кончился | Политика ILM и rollover |
| Слишком много шардов | Кластер медленный, master перегружен | Меньше индексов, шард 20-50 ГБ |
| `status: red` | Часть данных недоступна | `_cluster/allocation/explain` |
| Mapping explosion | Динамические поля от JSON-логов плодят тысячи полей | Явные mapping'и, `dynamic: strict/false` |
| Один узел «всё в одном» | Потеря ноды = потеря логов | Кластер и реплики |
| Logstash «на всякий случай» | Лишние ресурсы и звено отказа | Filebeat/Fluent Bit + ingest pipeline |

---

## 💼 Как это в DevOps

- ELK живёт там, где нужен мощный полнотекстовый поиск и богатая аналитика по логам,
  и где готовы платить за ресурсы: это самый «тяжёлый» компонент наблюдаемости.
- Типовая современная схема: **Filebeat/Fluent Bit → Elasticsearch (ingest pipeline) →
  Kibana**, Logstash — только если нужны сложные преобразования.
- Девопс отвечает за ILM, размер шардов, снапшоты, обновления и доступы; за поисковые
  запросы — пользователи (разработчики, поддержка, безопасность).
- В Kubernetes стек чаще называют EFK (Fluent Bit/Fluentd вместо Logstash) и ставят
  Helm-чартом; Elasticsearch — через ECK-оператора.
- Знание ELK «обзорно» на собесе — норма для джуна: важно понимать роли компонентов,
  что такое индекс/шард/ILM и чем стек отличается от Loki.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Проверить, жив ли ES | `curl localhost:9200/_cluster/health?pretty` |
| Список индексов и размеры | `GET /_cat/indices?v&s=store.size:desc` |
| Состояние нод | `GET /_cat/nodes?v` |
| Почему шард не размещён | `GET /_cluster/allocation/explain` |
| Найти ошибки | Discover: `level: "error" and service: "billing"` |
| Прямой поиск | `GET /logs-*/_search {"query":{"match":{"level":"error"}}}` |
| Удалить старый индекс | `DELETE /logs-app-2026.08.01` |
| Настроить жизненный цикл | Политика ILM + rollover |
| Парсить текстовые логи | `grok` в Logstash или ingest pipeline |
| Разобрать JSON из поля | `decode_json_fields` (Filebeat) / `json` (Logstash) |
| Склеить стектрейс | `multiline.*` в Filebeat |
| Снять бэкап | `_snapshot` репозиторий в S3 |
| Не дать ES упасть при старте | `vm.max_map_count=262144`, heap ≤ 50% RAM |

---

## 🧠 Что запомнить

1. Elasticsearch хранит и ищет, Logstash парсит и обогащает, Kibana показывает,
   Beats собирают.
2. Elasticsearch индексирует **содержимое** логов — отсюда мощный поиск и высокая цена
   по ресурсам.
3. Данные лежат в индексах, разбитых на шарды с репликами; `yellow` на одной ноде — норма.
4. `keyword` — точные значения и агрегации, `text` — полнотекстовый поиск.
5. ⭐ Без ILM индексы съедят диск: rollover + фазы warm/cold/delete обязательны.
6. Размер шарда держат в диапазоне 20-50 ГБ; много мелких шардов ломают кластер.
7. Heap — не более 50% RAM и не более ~31 ГБ; `vm.max_map_count` нужно поднять.
8. Logstash часто не нужен: Filebeat/Fluent Bit + ingest pipeline дешевле.
9. В Kubernetes аналог называют EFK; ставят Helm-чартом или ECK-оператором.
10. Бэкап Elasticsearch — снапшоты в объектное хранилище, а не копирование каталога данных.

---

## Задачи

> ⚠️ Стенд требует минимум 4 ГБ RAM. Поднимай отдельно от других стендов
> и гаси после занятий (`docker compose down`).

---

### Блок A. Теория

**A1.** Из каких компонентов состоит ELK и за что отвечает каждый?

<details><summary>Ответ</summary>

Elasticsearch — хранение и полнотекстовый поиск; Logstash — приём, парсинг
и обогащение; Kibana — интерфейс поиска, дашбордов и алертов; Beats — лёгкие агенты
сбора на хостах.

</details>

**A2.** Что такое EFK и почему в Kubernetes чаще встречается именно он?

<details><summary>Ответ</summary>

EFK — тот же стек, но вместо Logstash используется Fluentd/Fluent Bit.
В Kubernetes они легче, ставятся DaemonSet'ом, умеют читать логи контейнеров
и обогащать их метаданными подов.

</details>

**A3.** Что такое индекс, шард, реплика, документ и mapping в Elasticsearch?

<details><summary>Ответ</summary>

Документ — JSON-запись; индекс — набор документов; шард — часть индекса
(единица распределения и параллелизма); реплика — копия шарда; mapping — описание
типов полей.

</details>

**A4.** ⭐ Чем тип `keyword` отличается от `text`? Для каких полей какой выбрать?

<details><summary>Ответ</summary>

`text` анализируется (разбивается на токены) и годится для полнотекстового поиска,
но не для точных совпадений и агрегаций. `keyword` хранит значение целиком: точный поиск,
агрегации, сортировка. `service`, `level`, `env` — `keyword`; `message` — `text`.

</details>

**A5.** Почему логи разбивают на индексы по дням/неделям, а не хранят в одном?

<details><summary>Ответ</summary>

Чтобы удалять старое одним удалением индекса (дёшево), управлять retention через
ILM, ограничивать размер шардов и ускорять запросы по времени.

</details>

**A6.** Что означают статусы кластера green, yellow, red?

<details><summary>Ответ</summary>

green — все шарды (в т.ч. реплики) размещены; yellow — primary размещены,
часть реплик нет; red — часть primary недоступна, данные потеряны или не восстановлены.

</details>

**A7.** Почему на одной ноде статус yellow — это нормально?

<details><summary>Ответ</summary>

Реплику нельзя разместить на той же ноде, что и primary, — значит, она остаётся
неназначенной, и кластер честно сообщает yellow.

</details>

**A8.** Зачем нужен `vm.max_map_count` и почему heap не делают больше 31 ГБ?

<details><summary>Ответ</summary>

Elasticsearch активно использует memory-mapped файлы, и лимит областей памяти
по умолчанию слишком мал — процесс не стартует. Heap больше ~31 ГБ теряет сжатые указатели
(compressed oops), что ухудшает производительность; остальную память лучше отдать
файловому кэшу ОС.

</details>

**A9.** Что такое ILM и из каких фаз состоит типовая политика?

<details><summary>Ответ</summary>

Index Lifecycle Management — автоматическое управление индексами по фазам:
hot (запись и активный поиск), warm (только чтение, уменьшение шардов и сегментов),
cold (редкий доступ), delete (удаление).

</details>

**A10.** Что такое rollover и по каким условиям он срабатывает?

<details><summary>Ответ</summary>

Создание нового индекса при достижении условий: размер (например, 30 ГБ),
возраст (1 день) или число документов. Пишем всегда в алиас, он указывает на текущий индекс.

</details>

**A11.** Какой размер шарда считается нормальным и чем плохо «много мелких шардов»?

<details><summary>Ответ</summary>

20-50 ГБ. Много мелких шардов = избыточные накладные расходы на heap мастера
и на каждый поиск, деградация всего кластера.

</details>

**A12.** Когда Logstash нужен, а когда его можно не ставить?

<details><summary>Ответ</summary>

Нужен для сложных преобразований, маршрутизации в несколько мест, обогащения
из внешних источников, буферизации между сборщиками и ES. Не нужен, когда логи уже
структурные или достаточно ingest pipeline.

</details>

**A13.** Что такое grok и ingest pipeline?

<details><summary>Ответ</summary>

`grok` — парсер текстовых строк по шаблонам (набор именованных регулярок);
ingest pipeline — конвейер обработки документов внутри самого Elasticsearch
(grok, dissect, date, rename), заменяющий простые случаи Logstash.

</details>

**A14.** Как делают бэкап Elasticsearch?

<details><summary>Ответ</summary>

Механизмом снапшотов: регистрируется репозиторий (S3, NFS), снимаются
инкрементальные снапшоты, восстановление — `_restore`. Копировать каталог данных нельзя.

</details>

**A15.** Что такое mapping explosion и как его предотвратить?

<details><summary>Ответ</summary>

Неконтролируемый рост числа полей из-за динамического маппинга (например,
когда ключи JSON — идентификаторы). Предотвращается явными шаблонами маппинга,
`dynamic: false/strict`, нормализацией логов на стороне приложения.

</details>

---

### Блок B. «Что делает / что тут не так»

```bash
B1.  curl localhost:9200/_cluster/health?pretty
B2.  curl 'localhost:9200/_cat/indices?v&s=store.size:desc'
B3.  curl -X DELETE localhost:9200/logs-app-2026.08.01
B4.  curl 'localhost:9200/logs-*/_search?q=level:error&size=5&pretty'
B5.  sysctl -w vm.max_map_count=262144
```

<details><summary>Ответ (команды)</summary>

**B1.** Здоровье кластера: статус, число нод, неназначенные шарды.
**B2.** Список индексов, отсортированный по размеру, — первое, что смотрят при нехватке места.
**B3.** Удаляет индекс целиком (необратимо).
**B4.** Быстрый поиск ошибок по всем индексам `logs-*`.
**B5.** Поднимает лимит memory-mapped областей — требование Elasticsearch.

</details>

```text:no-line-numbers
B6.  ES_JAVA_OPTS=-Xms48g -Xmx48g          # на сервере 64 ГБ
B7.  xpack.security.enabled=false          # на проде
B8.  Индексы создаются по часам: logs-app-2026.09.13-14
B9.  Нет ILM, логи хранятся с 2023 года
B10. Один узел Elasticsearch, реплик нет, снапшотов нет
B11. Filebeat отправляет логи напрямую в Elasticsearch без Logstash
B12. Logstash стоит в цепочке, но фильтров в нём нет
B13. Приложение пишет JSON с произвольными ключами (id клиента как имя поля)
B14. Kibana опубликована в интернет без аутентификации
```

<details><summary>Ответ (оцени решения)</summary>

**B6.** Heap 48 ГБ: выше порога сжатых указателей и не оставляет памяти файловому кэшу.
**B7.** Отключённая безопасность на проде — открытый доступ к данным и управлению кластером.
**B8.** Почасовые индексы порождают слишком много мелких шардов.
**B9.** Без ILM — гарантированное заполнение диска и деградация.
**B10.** Одна нода без реплик и снапшотов: отказ = потеря всех логов.
**B11.** Нормальная современная схема (парсинг — в ingest pipeline).
**B12.** Лишнее звено: ресурсы и точка отказа без пользы.
**B13.** Прямой путь к mapping explosion.
**B14.** Kibana без аутентификации — утечка логов и управление кластером посторонними.

</details>

---

### Блок C. Практика

#### C1. 🔑 Поднять стек
1. Подними Elasticsearch + Kibana в compose (не забудь `vm.max_map_count`).
2. Проверь `_cluster/health`, объясни статус.
3. Открой Kibana, зайди в Dev Tools и выполни первый запрос.

<details><summary>Ответ</summary>

На одной ноде ожидается `yellow` — это корректно.

</details>

#### C2. Первые документы
Через Dev Tools создай индекс и положи в него несколько документов вручную:
```text:no-line-numbers
POST /test-logs/_doc
{ "@timestamp": "2026-09-13T14:03:22Z", "level": "error", "service": "billing",
  "message": "db timeout" }
```
Затем найди их через `_search` и через Discover.

#### C3. Filebeat
1. Добавь Filebeat, собирающий логи контейнеров.
2. Проверь, что индексы появляются (`_cat/indices`).
3. Настрой `add_docker_metadata` и убедись, что появились поля с именем контейнера.

#### C4. JSON-логи
1. Запусти контейнер, пишущий JSON-логи в stdout.
2. Включи `decode_json_fields` и проверь, что поля разложились.
3. Сравни поиск по полю и поиск по подстроке в `message`.

<details><summary>Ответ</summary>

Поиск по полю (`service: "billing"`) быстрее и точнее, чем подстрока в `message`.

</details>

#### C5. Multiline
Сгенерируй стектрейс, настрой `multiline` в Filebeat, убедись, что трейс приходит
одной записью.

#### C6. Kibana Discover
Освой запросы KQL: по уровню, по сервису, диапазон статусов, исключение,
поиск по подстроке. Сохрани три полезных запроса.

#### C7. Дашборд
Собери дашборд: динамика ошибок по времени, топ сервисов по числу ошибок,
распределение уровней, таблица последних ERROR.

#### C8. 🔑 ILM
1. Создай политику с rollover и удалением через 7 дней.
2. Привяжи её к шаблону индекса.
3. Проверь `GET /_ilm/explain` для индекса.
4. Объясни, что произойдёт с индексами через неделю.

<details><summary>Ответ</summary>

`GET /_ilm/explain/<index>` покажет текущую фазу и время до следующего перехода.

</details>

#### C9. Размеры и шарды
Посмотри `_cat/indices` и `_cat/shards`: сколько шардов, какого размера.
Посчитай, какой объём получится за месяц при текущем темпе.

#### C10. Снапшот
Настрой файловый репозиторий снапшотов, сними снапшот индекса, удали индекс,
восстанови из снапшота.

<details><summary>Ответ</summary>

Репозиторий нужно объявить в `path.repo` и смонтировать в контейнер,
иначе регистрация репозитория завершится ошибкой.

</details>

---

### Блок D. Инциденты

**D1.** Elasticsearch не стартует, в логах `max virtual memory areas vm.max_map_count`.
Что делать?

<details><summary>Ответ</summary>

Выполнить `sysctl -w vm.max_map_count=262144` и зафиксировать в
`/etc/sysctl.d/`; в docker-окружении это делается на хосте.

</details>

**D2.** Кластер в статусе red. Порядок разбора.

<details><summary>Ответ</summary>

`GET /_cluster/health`, `GET /_cat/shards?v` (какие шарды unassigned),
`GET /_cluster/allocation/explain` (почему), проверить ноды, диски (watermark),
восстановление из снапшота при потере данных.

</details>

**D3.** Диск под Elasticsearch заполнен на 95%, индексы стали read-only. Что произошло
и как чинить?

<details><summary>Ответ</summary>

Сработал disk watermark (flood stage): индексы переводятся в read-only.
Освободить место (удалить старые индексы, снять снапшот), затем снять блокировку
`index.blocks.read_only_allow_delete: null`, настроить ILM.

</details>

**D4.** Kibana показывает «No results match your search criteria», хотя логи идут.
Гипотезы?

<details><summary>Ответ</summary>

Неверный временной диапазон, не тот data view/индекс-паттерн, логи попадают
в другой индекс, `@timestamp` неправильный, фильтры KQL, права доступа.

</details>

**D5.** Поиск стал очень медленным. Что проверишь?

<details><summary>Ответ</summary>

Число и размер шардов, нагрузку на heap и GC, диски, тяжёлые запросы
(wildcard по `text`), отсутствие фильтра по времени, количество полей.

</details>

**D6.** После добавления нового сервиса в кластере стало 12 000 шардов. Чем это грозит?

<details><summary>Ответ</summary>

Перегрузка master-ноды, большой расход heap, медленные запросы, риск нестабильности
кластера. Решение — укрупнить индексы, уменьшить число шардов, использовать rollover.

</details>

**D7.** В индексе 4000 полей, mapping разрастается. Причина и решение.

<details><summary>Ответ</summary>

Mapping explosion из-за динамических полей. Решение — явные маппинги,
`dynamic: false`, нормализация структуры логов, вынос переменных ключей в значения полей.

</details>

**D8.** Filebeat работает, но логи не доезжают. Алгоритм проверки по цепочке.

<details><summary>Ответ</summary>

Идти по цепочке: читает ли Filebeat файлы (логи самого Filebeat, `registry`),
доходит ли до выхода (ошибки подключения), принимает ли Elasticsearch (ошибки маппинга,
read-only, нехватка места), тот ли индекс смотрят в Kibana.

</details>

**D9.** Логи есть, но `@timestamp` — это время приёма, а не время события. Почему
и как исправить?

<details><summary>Ответ</summary>

Не настроен `date`-фильтр/ingest processor: время события не разобрано из строки.
Исправляется парсингом поля времени и присвоением `@timestamp`.

</details>

**D10.** Нужно сократить расходы на хранение логов вдвое. Какие пять шагов предложишь?

<details><summary>Ответ</summary>

Уровень INFO вместо DEBUG, отказ от дублирующих полей и лишних событий,
sampling, ILM с более коротким retention и переносом в cold/frozen, уменьшение числа
реплик для старых индексов, сжатие и архив в объектное хранилище.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое ELK и зачем каждый компонент?

<details><summary>Ответ</summary>

Elasticsearch (хранение и поиск), Logstash (парсинг/обогащение), Kibana (интерфейс),
плюс Beats для сбора.

</details>

**2.** Чем EFK отличается от ELK?

<details><summary>Ответ</summary>

Вместо Logstash — Fluentd/Fluent Bit; легче по ресурсам и удобнее в Kubernetes.

</details>

**3.** Что такое индекс и шард?

<details><summary>Ответ</summary>

Индекс — набор документов (обычно за период), шард — его часть, распределяемая
по нодам; реплики дают отказоустойчивость.

</details>

**4.** Чем `text` отличается от `keyword`?

<details><summary>Ответ</summary>

`text` анализируется для полнотекстового поиска, `keyword` хранится целиком
для точных совпадений и агрегаций.

</details>

**5.** Что такое ILM и зачем он нужен?

<details><summary>Ответ</summary>

Управление жизненным циклом индексов: rollover и фазы hot/warm/cold/delete;
без него диск заканчивается.

</details>

**6.** Сколько памяти давать Elasticsearch?

<details><summary>Ответ</summary>

Heap — половина RAM, но не больше ~31 ГБ; остальное — файловому кэшу.

</details>

**7.** Нужен ли Logstash?

<details><summary>Ответ</summary>

Не всегда: при структурных логах хватает Filebeat/Fluent Bit + ingest pipeline;
Logstash нужен для сложной обработки.

</details>

**8.** Как делается бэкап Elasticsearch?

<details><summary>Ответ</summary>

Снапшотами в репозиторий (S3/NFS), инкрементально; восстановление через `_restore`.

</details>

**9.** Почему кластер может быть yellow или red?

<details><summary>Ответ</summary>

Yellow — не размещены реплики (нормально для одной ноды), red — недоступны primary-шарды.

</details>

**10.** Чем ELK отличается от Loki?

<details><summary>Ответ</summary>

ELK индексирует содержимое (мощный поиск, дорого), Loki индексирует только лейблы
и хранит сжатые чанки (дёшево, поиск по потокам и grep-подобные фильтры).

</details>

---

### 🎯 Чек-лист

- [ ] Поднял Elasticsearch + Kibana и объясняю статус кластера
- [ ] Понимаю индекс, шард, реплику, mapping
- [ ] ⭐ Различаю `text` и `keyword`
- [ ] Настроил Filebeat и вижу логи контейнеров в Kibana
- [ ] Разобрал JSON-логи и настроил multiline
- [ ] Умею искать в Discover через KQL и в Dev Tools через API
- [ ] Настроил ILM с rollover и удалением
- [ ] Знаю правила по heap, шардам и `vm.max_map_count`
- [ ] Снял и восстановил снапшот
- [ ] Могу сравнить ELK и Loki по стоимости и возможностям
