---
title: "03. Kafka: эксплуатация"
description: "Поднять кластер, CLI для топиков и групп, мониторинг лага и ISR, безопасность, reassignment и алгоритм разбора инцидентов"
---

# 03. Kafka: эксплуатация

> Роадмап → Очереди → Kafka. Концепции разобраны в [«Kafka: концепции»](/queues/02-kafka-basics);
> здесь — то, что делает девопс руками.
>
> **После темы ты умеешь:** поднять кластер, управлять топиками и группами из CLI,
> следить за лагом и дисками, разбирать типовые инциденты.

---

## 🗺️ Что делает девопс вокруг Kafka

```text:no-line-numbers
 ┌────────────────────────────────────────────────────────────────┐
 │ РАЗВЁРТЫВАНИЕ   docker/k8s (Strimzi)/VM, KRaft, размер кластера│
 ├────────────────────────────────────────────────────────────────┤
 │ ТОПИКИ          создание, партиции, retention, репликация       │
 ├────────────────────────────────────────────────────────────────┤
 │ ДОСТУПЫ         SASL/TLS, ACL: кто пишет и читает                │
 ├────────────────────────────────────────────────────────────────┤
 │ НАБЛЮДЕНИЕ      ⭐ лаг групп, ISR, диски, throughput, ребалансы  │
 ├────────────────────────────────────────────────────────────────┤
 │ ЭКСПЛУАТАЦИЯ    расширение партиций, перебалансировка, апгрейды  │
 ├────────────────────────────────────────────────────────────────┤
 │ ИНЦИДЕНТЫ       лаг, отвалившиеся реплики, полный диск, ребаланс │
 └────────────────────────────────────────────────────────────────┘
```

---

## 1. Поднять кластер

**Учебный стенд (KRaft, без ZooKeeper)** — compose из 00_INDEX.md на официальном
образе `apache/kafka`: CLI-скрипты там лежат в `/opt/kafka/bin/` и в `PATH` не добавлены.

**Прод, ориентиры:**
| Параметр | Рекомендация |
|----------|--------------|
| Число брокеров | Минимум 3 (кворум + `replication.factor=3`) |
| Диски | Отдельные быстрые диски под данные; ⭐ не сетевые «медленные» |
| Память | JVM heap 6-8 ГБ; остальная RAM — под page cache (Kafka активно на него опирается) |
| Сеть | Отдельные интерфейсы/каналы для репликации при больших объёмах |
| Размещение | Брокеры в разных зонах доступности (`broker.rack` для rack awareness) |
| Kubernetes | Оператор **Strimzi** (или managed Kafka в облаке) |

```properties
# server.properties — ключевые параметры
num.partitions=3
default.replication.factor=3
min.insync.replicas=2
unclean.leader.election.enable=false        # ⭐ целостность важнее доступности
log.retention.hours=168                     # 7 дней
log.segment.bytes=1073741824
log.dirs=/data/kafka
auto.create.topics.enable=false             # ⭐ топики создаются осознанно
```

---

## 2. CLI: то, что используешь каждый день

```bash
# стенд: заходим в контейнер, скрипты — в /opt/kafka/bin (в PATH их нет)
docker exec -it kafka bash
KB=localhost:9092
# на VM с Kafka из tarball то же самое лежит в <каталог kafka>/bin/

# ---- топики ----
/opt/kafka/bin/kafka-topics.sh --bootstrap-server $KB --list
/opt/kafka/bin/kafka-topics.sh --bootstrap-server $KB --create --topic orders \
  --partitions 3 --replication-factor 3 \
  --config retention.ms=604800000 --config min.insync.replicas=2   # на одноузловом стенде: RF 1, ISR 1
/opt/kafka/bin/kafka-topics.sh --bootstrap-server $KB --describe --topic orders     # ⭐ лидеры, ISR
/opt/kafka/bin/kafka-topics.sh --bootstrap-server $KB --alter --topic orders --partitions 6  # только увеличение
/opt/kafka/bin/kafka-topics.sh --bootstrap-server $KB --delete --topic orders

# ---- конфигурация ----
/opt/kafka/bin/kafka-configs.sh --bootstrap-server $KB --entity-type topics --entity-name orders --describe
/opt/kafka/bin/kafka-configs.sh --bootstrap-server $KB --entity-type topics --entity-name orders \
  --alter --add-config retention.ms=86400000

# ---- продюсер / консьюмер ----
/opt/kafka/bin/kafka-console-producer.sh --bootstrap-server $KB --topic orders
/opt/kafka/bin/kafka-console-producer.sh --bootstrap-server $KB --topic orders \
  --property parse.key=true --property key.separator=:        # ключ:значение

/opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server $KB --topic orders --from-beginning
/opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server $KB --topic orders \
  --group billing --property print.key=true --property print.partition=true

# ---- группы и лаг ⭐ ----
/opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server $KB --list
/opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server $KB --describe --group billing
/opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server $KB --describe --group billing --members --verbose

# перемотка (группа должна быть остановлена)
/opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server $KB --group billing --topic orders \
  --reset-offsets --to-earliest --execute
/opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server $KB --group billing --topic orders \
  --reset-offsets --to-datetime 2026-09-13T00:00:00.000 --execute
/opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server $KB --group billing --topic orders \
  --reset-offsets --shift-by -1000 --execute

# ---- нагрузочное тестирование ----
/opt/kafka/bin/kafka-producer-perf-test.sh --topic orders --num-records 1000000 \
  --record-size 512 --throughput -1 --producer-props bootstrap.servers=$KB
/opt/kafka/bin/kafka-consumer-perf-test.sh --bootstrap-server $KB --topic orders --messages 1000000
```

Вывод `--describe` группы — то, что смотрят при инциденте:
```text:no-line-numbers
GROUP    TOPIC   PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG   CONSUMER-ID
billing  orders  0          15234           15240           6     consumer-1-...
billing  orders  1          8110            29500           21390 consumer-2-...   ← проблема тут
billing  orders  2          9902            9902            0     consumer-3-...
```

---

## 3. Мониторинг ⭐

| Что смотреть | Метрика/источник | Алерт |
|--------------|------------------|-------|
| **Лаг групп** | `kafka_consumergroup_lag` (kafka_exporter) | Растёт N минут подряд |
| Под-реплицированные партиции | `UnderReplicatedPartitions` | `> 0` дольше 5 минут ⭐ |
| Партиции без лидера | `OfflinePartitionsCount` | `> 0` — critical |
| ISR shrink/expand | `IsrShrinksPerSec` | Частые изменения |
| Активные контроллеры | `ActiveControllerCount` | Должен быть ровно 1 |
| Диски брокеров | node_exporter | `< 20%` свободного |
| Пропускная способность | `BytesInPerSec` / `BytesOutPerSec` | Аномалии и рост |
| Ребалансы | Логи групп, `RebalanceRate` | Частые ребалансы |
| Размер топиков | `kafka_log_size` | Рост против ожиданий |

```yaml
# exporter в compose
  kafka-exporter:
    image: danielqsj/kafka-exporter:latest
    command: ["--kafka.server=kafka:19092"]     # внутренний листенер стенда (см. 00_INDEX)
    ports: ["9308:9308"]
```
```text:no-line-numbers
# суммарный лаг группы
sum by (consumergroup, topic) (kafka_consumergroup_lag)

# лаг растёт последние 10 минут
deriv(sum by (consumergroup) (kafka_consumergroup_lag)[10m:]) > 0

# под-реплицированные партиции
kafka_cluster_partition_underreplicated > 0
```
Готовый дашборд Grafana: **7589** (Kafka Exporter Overview).

---

## 4. Безопасность

| Механизм | Зачем |
|----------|-------|
| **TLS** | Шифрование трафика клиент↔брокер и между брокерами |
| **SASL** (`SCRAM-SHA-512`, `PLAIN`, Kerberos, OAuth) | Аутентификация клиентов |
| **ACL** | Кто в какой топик может писать/читать и в какой группе состоять |
| Сетевая изоляция | Kafka во внутренней подсети, доступ через security groups |
| Отдельные учётки на сервис | Ротация и точечный отзыв доступа |

```bash
/opt/kafka/bin/kafka-acls.sh --bootstrap-server $KB --add \
  --allow-principal User:billing --operation Read \
  --topic orders --group billing
/opt/kafka/bin/kafka-acls.sh --bootstrap-server $KB --list --topic orders
```

---

## 5. Эксплуатационные операции

```bash
# посмотреть распределение партиций и переназначить (например, после добавления брокера)
/opt/kafka/bin/kafka-reassign-partitions.sh --bootstrap-server $KB --generate \
  --topics-to-move-json-file topics.json --broker-list "1,2,3,4"
/opt/kafka/bin/kafka-reassign-partitions.sh --bootstrap-server $KB --execute --reassignment-json-file plan.json
/opt/kafka/bin/kafka-reassign-partitions.sh --bootstrap-server $KB --verify --reassignment-json-file plan.json

# вернуть лидерство «предпочитаемым» репликам после восстановления брокера
/opt/kafka/bin/kafka-leader-election.sh --bootstrap-server $KB --election-type preferred --all-topic-partitions
```

| Операция | Нюанс |
|----------|-------|
| Добавление брокера | Данные **не переезжают сами** — нужен reassignment |
| Увеличение партиций | Только вверх; ломает привязку ключей к партициям ⚠️ |
| Удаление топика | Требует `delete.topic.enable=true`; необратимо |
| Обновление версии | Rolling restart по одному брокеру, следя за ISR |
| Изменение retention | Применяется к сегментам; место освобождается не мгновенно |
| Перенос в другой кластер | MirrorMaker 2 |

---

## 6. Алгоритм разбора «лаг растёт»

```text:no-line-numbers
1. kafka-consumer-groups --describe --group X
     ├─ лаг на ВСЕХ партициях?     → потребители не справляются/лежат
     └─ лаг на ОДНОЙ партиции?     → «горячий» ключ или зависший потребитель
2. Есть ли живые участники группы? (--members)
     └─ нет → потребители не запущены/не могут подключиться
3. Идут ли постоянные ребалансы? (логи приложения)
     └─ да → max.poll.interval.ms / долгая обработка / частые рестарты
4. Число партиций vs число потребителей
     └─ потребителей больше → лишние простаивают; меньше → мало параллелизма
5. Внешние зависимости обработчика (БД, API) — не там ли узкое место?
6. Ресурсы брокеров: диски, CPU, сеть, ISR
7. Вырос ли входной поток? (BytesInPerSec, сравнение с прошлой неделей)
```

---

## 7. Грабли эксплуатации

| Грабля | Последствие | Решение |
|--------|-------------|---------|
| `auto.create.topics.enable=true` | Топики плодятся опечатками, без нужных настроек | Отключить, создавать явно |
| `replication.factor=1` | Потеря данных при отказе брокера | 3 реплики, `min.insync.replicas=2` |
| Диски забиты | Брокер падает, партиции offline | Retention, мониторинг, компрессия |
| Нет мониторинга лага | Узнаёшь от бизнеса | kafka_exporter + алерты |
| Добавили брокер и ждут «само» | Новый брокер простаивает | `kafka-reassign-partitions` |
| Увеличили партиции на «ключевом» топике | Поехал порядок | Планировать заранее |
| Мелкие сообщения без батчинга | Низкая пропускная способность | `linger.ms`, `batch.size`, компрессия |
| Kafka на медленных сетевых дисках | Задержки и отваливающиеся реплики | Быстрые локальные диски |
| Один брокер «на посмотреть» в проде | Нет отказоустойчивости | Минимум 3 |

---

## 💼 Как это в DevOps

- Топики создаются не руками, а декларативно: через Terraform-провайдер, Strimzi
  `KafkaTopic` или скрипты в репозитории — тогда настройки воспроизводимы и проходят ревью.
- Лаг консьюмер-групп — метрика №1 этого блока; на неё вешают алерты с понятным
  рунбуком («проверить потребителей → ребалансы → зависимости → масштабировать»).
- В Kubernetes стандарт — оператор Strimzi; в облаке — managed Kafka, которая снимает
  большую часть эксплуатации (см. раздел Cloud → managed-сервисы).
- Обновления и обслуживание — rolling restart с контролем `UnderReplicatedPartitions`:
  следующий брокер трогают только когда ISR восстановился.
- Частый реальный инцидент — не «Kafka сломалась», а «потребитель не справляется»:
  умение быстро это различить экономит часы.

---

## 📌 Шпаргалка

| Хочу | Команда |
|------|---------|
| Список топиков | `/opt/kafka/bin/kafka-topics.sh --bootstrap-server $KB --list` |
| Создать топик | `--create --topic X --partitions 3 --replication-factor 3` |
| Детали топика (ISR, лидеры) | `--describe --topic X` |
| Увеличить партиции | `--alter --topic X --partitions 6` |
| Изменить retention | `/opt/kafka/bin/kafka-configs.sh ... --alter --add-config retention.ms=...` |
| Записать в топик | `/opt/kafka/bin/kafka-console-producer.sh --topic X` |
| Прочитать с начала | `/opt/kafka/bin/kafka-console-consumer.sh --topic X --from-beginning` |
| Список групп | `/opt/kafka/bin/kafka-consumer-groups.sh --list` |
| ⭐ Лаг группы | `/opt/kafka/bin/kafka-consumer-groups.sh --describe --group G` |
| Участники группы | `--describe --group G --members --verbose` |
| Перемотать группу | `--reset-offsets --to-earliest|--to-datetime|--shift-by --execute` |
| Перераспределить партиции | `/opt/kafka/bin/kafka-reassign-partitions.sh` |
| Вернуть лидеров | `/opt/kafka/bin/kafka-leader-election.sh --election-type preferred` |
| Права | `/opt/kafka/bin/kafka-acls.sh --add --allow-principal User:X --operation Read --topic Y` |
| Нагрузочный тест | `/opt/kafka/bin/kafka-producer-perf-test.sh` |
| Метрики | kafka_exporter :9308, дашборд Grafana 7589 |

---

## 🧠 Что запомнить

1. Минимальный прод-кластер — 3 брокера, `replication.factor=3`, `min.insync.replicas=2`,
   `unclean.leader.election=false`.
2. `auto.create.topics.enable` отключают: топики создаются осознанно и декларативно.
3. ⭐ `kafka-consumer-groups --describe` — главная команда при разборе инцидентов.
4. Лаг смотрят по партициям: лаг на одной партиции и на всех — разные проблемы.
5. `kafka-topics --describe` показывает лидеров и ISR — первое при подозрении
   на проблемы кластера.
6. `UnderReplicatedPartitions > 0` и `OfflinePartitionsCount > 0` — критические алерты.
7. Партиции можно только увеличивать, и это ломает привязку ключей.
8. При добавлении брокера данные не переезжают сами — нужен reassignment.
9. Kafka опирается на page cache: память и быстрые диски важнее «большого heap».
10. Обновления — rolling restart с ожиданием восстановления ISR между брокерами.

---

## Задачи

> Стенд: Kafka (лучше 3 брокера для заданий про репликацию) + kafka-exporter + Prometheus.
> В образе `apache/kafka` CLI-скрипты лежат в `/opt/kafka/bin/` (не в `PATH`):
> `docker exec -it kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list`.
> Короткие имена в тексте (`kafka-consumer-groups --describe`) — это те же скрипты.

---

### Блок A. Теория

**A1.** Каковы ориентиры для прод-кластера: число брокеров, репликация, диски, память?

<details><summary>Ответ</summary>

Минимум 3 брокера (кворум и `replication.factor=3`), быстрые локальные диски
под данные, JVM heap 6-8 ГБ и много свободной RAM под page cache, размещение
по разным зонам доступности, отключённое автосоздание топиков.

</details>

**A2.** Почему Kafka сильно зависит от page cache и что это значит для настройки памяти?

<details><summary>Ответ</summary>

Kafka пишет последовательно и отдаёт данные, как правило, из страничного кэша ОС;
большой JVM heap не помогает и даже вредит (паузы GC). Поэтому память отдают ОС,
а heap держат умеренным.

</details>

**A3.** Зачем отключают `auto.create.topics.enable`?

<details><summary>Ответ</summary>

Чтобы опечатка в имени топика не создавала новый топик с настройками
по умолчанию (часто с одной репликой), и чтобы все топики имели осознанные параметры.

</details>

**A4.** Какие параметры топика задают при создании и почему?

<details><summary>Ответ</summary>

Число партиций (параллелизм), `replication-factor` (надёжность),
`min.insync.replicas` (гарантия записи), `retention.ms`/`retention.bytes`
(сколько хранить), `cleanup.policy` (delete/compact), компрессия.

</details>

**A5.** ⭐ Какая команда показывает лаг группы и что означают её колонки?

<details><summary>Ответ</summary>

`kafka-consumer-groups.sh --describe --group <G>`: колонки GROUP, TOPIC,
PARTITION, CURRENT-OFFSET (закоммичено), LOG-END-OFFSET (конец партиции),
LAG (разница), CONSUMER-ID/HOST.

</details>

**A6.** Чем отличается ситуация «лаг на всех партициях» от «лаг на одной партиции»?

<details><summary>Ответ</summary>

Лаг на всех партициях — потребители в целом не справляются или не работают.
Лаг на одной партиции — «горячий» ключ, неравномерное распределение или зависший
конкретный потребитель.

</details>

**A7.** Как перемотать группу на начало, на время, на N сообщений назад?
Какое обязательное условие?

<details><summary>Ответ</summary>

`--reset-offsets` с `--to-earliest`, `--to-datetime`, `--shift-by`
и обязательным `--execute`. Условие: группа должна быть неактивна (нет живых участников).

</details>

**A8.** Что показывает `kafka-topics --describe` и на что там смотреть в первую очередь?

<details><summary>Ответ</summary>

Число партиций, для каждой — лидер, список реплик и ISR. Смотрят, все ли реплики
в ISR и равномерно ли распределены лидеры.

</details>

**A9.** Что такое `UnderReplicatedPartitions` и `OfflinePartitionsCount`?

<details><summary>Ответ</summary>

`UnderReplicatedPartitions` — партиции, у которых не все реплики синхронны
(риск потери при следующем отказе). `OfflinePartitionsCount` — партиции без лидера:
запись и чтение по ним невозможны.

</details>

**A10.** Сколько должно быть активных контроллеров и почему это метрика?

<details><summary>Ответ</summary>

Ровно один: если контроллеров 0 — кластер без управления метаданными,
если больше одного — split-brain в управлении.

</details>

**A11.** Что произойдёт при добавлении нового брокера в кластер?

<details><summary>Ответ</summary>

Ничего автоматически не произойдёт: новый брокер не получит существующие
партиции, пока не выполнить `kafka-reassign-partitions`.

</details>

**A12.** Как выполняется обновление версии Kafka без простоя?

<details><summary>Ответ</summary>

Rolling restart: обновляют по одному брокеру, дожидаясь возврата всех реплик
в ISR и отсутствия under-replicated партиций, с учётом совместимости версий протокола
и форматов.

</details>

**A13.** Какие механизмы безопасности есть у Kafka?

<details><summary>Ответ</summary>

TLS для шифрования, SASL (SCRAM, Kerberos, OAuth) для аутентификации,
ACL для авторизации по топикам и группам, сетевая изоляция и отдельные учётки на сервис.

</details>

**A14.** Как делают резервное копирование/репликацию между кластерами?

<details><summary>Ответ</summary>

MirrorMaker 2 для репликации между кластерами; для «бэкапа» также используют
выгрузку в объектное хранилище через Kafka Connect. Классического бэкапа, как у БД,
у Kafka нет — надёжность обеспечивается репликацией.

</details>

**A15.** Перечисли алгоритм разбора «лаг растёт» по шагам.

<details><summary>Ответ</summary>

Лаг по партициям → живы ли участники группы → ребалансы → соотношение
партиций и потребителей → внешние зависимости обработчика → ресурсы брокеров →
рост входного потока.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  /opt/kafka/bin/kafka-topics.sh --bootstrap-server $KB --describe --topic orders
```

<details><summary>Ответ</summary>

Детали топика: партиции, лидеры, реплики, ISR.

</details>

```bash
B2.  /opt/kafka/bin/kafka-topics.sh --bootstrap-server $KB --alter --topic orders --partitions 6
```

<details><summary>Ответ</summary>

Увеличение числа партиций (необратимо, влияет на привязку ключей).

</details>

```bash
B3.  /opt/kafka/bin/kafka-configs.sh --bootstrap-server $KB --entity-type topics --entity-name orders \
       --alter --add-config retention.ms=86400000
```

<details><summary>Ответ</summary>

Изменение retention топика на сутки.

</details>

```bash
B4.  /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server $KB --describe --group billing
```

<details><summary>Ответ</summary>

Лаг и участники группы.

</details>

```bash
B5.  /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server $KB --group billing --topic orders \
       --reset-offsets --to-earliest --execute
```

<details><summary>Ответ</summary>

Перемотка группы на начало топика.

</details>

```bash
B6.  /opt/kafka/bin/kafka-reassign-partitions.sh --bootstrap-server $KB --execute --reassignment-json-file plan.json
```

<details><summary>Ответ</summary>

Выполнение плана перераспределения партиций.

</details>

```bash
B7.  /opt/kafka/bin/kafka-leader-election.sh --bootstrap-server $KB --election-type preferred --all-topic-partitions
```

<details><summary>Ответ</summary>

Возврат лидерства предпочитаемым репликам после восстановления брокеров.

</details>

```bash
B8.  /opt/kafka/bin/kafka-acls.sh --bootstrap-server $KB --add --allow-principal User:billing \
       --operation Read --topic orders --group billing
```

<details><summary>Ответ</summary>

Выдача прав на чтение топика и участие в группе.

</details>

```bash
B9.  /opt/kafka/bin/kafka-producer-perf-test.sh --topic orders --num-records 1000000 --record-size 512 \
       --throughput -1 --producer-props bootstrap.servers=$KB
```

<details><summary>Ответ</summary>

Нагрузочный тест продюсера.

</details>

Оцени конфигурации:
```text:no-line-numbers
B10. auto.create.topics.enable=true на проде
```

<details><summary>Ответ</summary>

Риск «случайных» топиков с дефолтными настройками.

</details>

```text:no-line-numbers
B11. default.replication.factor=1, min.insync.replicas=1
```

<details><summary>Ответ</summary>

Нет отказоустойчивости: потеря брокера = потеря данных.

</details>

```text:no-line-numbers
B12. unclean.leader.election.enable=true
```

<details><summary>Ответ</summary>

Возможна потеря подтверждённых сообщений при выборе отставшего лидера.

</details>

```text:no-line-numbers
B13. log.retention.hours=8760 (год) на топике с кликами, диски 500 ГБ
```

<details><summary>Ответ</summary>

Год хранения кликов почти наверняка переполнит диски; retention надо считать.

</details>

```text:no-line-numbers
B14. Kafka развёрнута на сетевых дисках с высокой задержкой
```

<details><summary>Ответ</summary>

Высокая задержка дисков ведёт к отставанию реплик и деградации.

</details>

```text:no-line-numbers
B15. Один брокер в проде, "нагрузка небольшая"
```

<details><summary>Ответ</summary>

Один брокер — единая точка отказа.

</details>

```text:no-line-numbers
B16. JVM heap 48 ГБ на сервере с 64 ГБ RAM
```

<details><summary>Ответ</summary>

Слишком большой heap: паузы GC и мало памяти под page cache.

</details>

---

### Блок C. Практика

#### C1. 🔑 Управление топиками
1. Создай топик с 3 партициями и заданным retention.
2. Посмотри `--describe`: лидеры, реплики, ISR.
3. Измени retention через `kafka-configs`, проверь применение.
4. Увеличь число партиций и объясни последствия.

<details><summary>Ответ</summary>

После увеличения партиций распределение ключей меняется — это надо проговаривать
с разработчиками заранее.

</details>

#### C2. Продюсер и консьюмер из CLI
Отправь сообщения с ключами, прочитай с выводом ключа и партиции.
Убедись, что распределение соответствует ключам.

#### C3. 🔑 Лаг и его разбор
1. Останови потребителей, залей 100 000 сообщений `kafka-producer-perf-test`.
2. Смотри `--describe --group` — зафиксируй лаг по партициям.
3. Запусти одного потребителя, потом трёх; сравни скорость сокращения лага.

<details><summary>Ответ</summary>

С тремя потребителями (при 3 партициях) лаг сокращается примерно втрое быстрее.

</details>

#### C4. Перемотка группы
Перемотай группу на начало, на конкретную дату и на `--shift-by -1000`.
Проверь результат каждый раз. Что будет, если группа активна?

<details><summary>Ответ</summary>

При активной группе команда вернёт ошибку: перемотка возможна только для
неактивной группы.

</details>

#### C5. Репликация и отказ брокера
1. Кластер из 3 брокеров, топик с `replication-factor=3`.
2. Останови один брокер, посмотри `--describe`: что стало с ISR и лидерами?
3. Верни брокер, выполни `kafka-leader-election --election-type preferred`.

<details><summary>Ответ</summary>

После остановки брокера часть реплик выпадет из ISR и, возможно, сменятся лидеры;
после возврата и `preferred election` лидерство восстановится.

</details>

#### C6. Гарантии записи
Поставь `min.insync.replicas=2`, останови два брокера, попробуй записать с `acks=all`,
зафиксируй ошибку. Верни кластер.

<details><summary>Ответ</summary>

Ожидаемая ошибка — `NOT_ENOUGH_REPLICAS` (или `NotEnoughReplicasAfterAppend`).

</details>

#### C7. Мониторинг
1. Подними kafka-exporter, добавь в Prometheus.
2. Импортируй дашборд 7589.
3. Найди метрики лага, под-реплицированных партиций, throughput.

#### C8. Алерты
Настрой три алерта: растущий лаг группы, `UnderReplicatedPartitions > 0`,
мало места на диске брокера. Спровоцируй первый.

#### C9. Диски и retention
1. Посмотри размер каталога данных и топиков.
2. Уменьши retention и проследи, как освобождается место (не мгновенно!).
3. Включи компрессию на продюсере и сравни объём.

<details><summary>Ответ</summary>

Место освобождается при удалении сегментов: неактивные сегменты удаляются
по расписанию, поэтому эффект не мгновенный.

</details>

#### C10. Рунбук
Напиши рунбук «Растёт лаг консьюмер-группы»: что проверить по шагам,
какие команды выполнить, когда эскалировать, что писать в постмортем.

---

### Блок D. Инциденты

**D1.** `OfflinePartitionsCount > 0`. Что это значит и что делать?

<details><summary>Ответ</summary>

Партиции без лидера: обычно упали брокеры, хранящие все их реплики,
или потеряны данные. Проверить состояние брокеров, диски, логи контроллера,
поднять брокеры; при полной потере — восстановление из другого кластера/переинициализация.

</details>

**D2.** `UnderReplicatedPartitions` держится на 40 уже час. Разбор.

<details><summary>Ответ</summary>

Один или несколько брокеров не успевают/недоступны: проверить их состояние,
диски и сеть, нагрузку, паузы GC, `IsrShrinks`; при необходимости разгрузить кластер
и восстановить репликацию.

</details>

**D3.** Диск брокера заполнен на 98%. Немедленные действия и последующие меры.

<details><summary>Ответ</summary>

Немедленно: уменьшить retention на самых больших топиках, удалить ненужные
топики, добавить диск; затем — мониторинг, планирование ёмкости, компрессия,
разумный retention.

</details>

**D4.** Продюсеры получают `NOT_ENOUGH_REPLICAS`. Причина и исправление.

<details><summary>Ответ</summary>

Число синхронных реплик меньше `min.insync.replicas`: вернуть брокеры в строй,
проверить ISR; временно снижать `min.insync.replicas` можно только осознанно,
это ослабляет гарантии.

</details>

**D5.** После рестарта брокера все лидеры остались на двух других. Как вернуть баланс?

<details><summary>Ответ</summary>

Выполнить `kafka-leader-election --election-type preferred --all-topic-partitions`
(и включить `auto.leader.rebalance.enable`).

</details>

**D6.** Добавили четвёртый брокер, нагрузка не перераспределилась. Что забыли?

<details><summary>Ответ</summary>

Перераспределение партиций (`kafka-reassign-partitions`): новые брокеры
не получают существующие данные автоматически.

</details>

**D7.** Группа `billing` имеет лаг 2 млн, потребители «работают». Алгоритм.

<details><summary>Ответ</summary>

Проверить участников группы и распределение партиций, ребалансы, время обработки
одного сообщения, зависимости потребителя, число партиций, ошибки в логах; далее —
масштабировать потребителей/партиции или оптимизировать обработку.

</details>

**D8.** Приложение постоянно ловит `CommitFailedException`. Что настроить?

<details><summary>Ответ</summary>

Обработка дольше `max.poll.interval.ms`: увеличить лимит, уменьшить
`max.poll.records`, ускорить обработку, использовать асинхронную обработку с контролем
коммитов.

</details>

**D9.** Потребитель читает, но данных за прошлые сутки нет. Возможные причины?

<details><summary>Ответ</summary>

Данные удалены по retention; оффсеты сброшены на `latest`; читается другой
топик/партиции; сообщения писались в другой кластер; compaction удалил старые версии
по ключу.

</details>

**D10.** Разработчики просят топик с 200 партициями «на будущее». Твой ответ.

<details><summary>Ответ</summary>

200 партиций «на будущее» — это нагрузка на брокеры, дольше выборы лидеров,
больше файлов и памяти. Предложить расчёт от целевой пропускной способности,
начать с разумного числа и увеличивать при необходимости, обсудив последствия
для привязки ключей.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как поднимают Kafka в проде и сколько нужно брокеров?

<details><summary>Ответ</summary>

Минимум 3 брокера с репликацией 3 и `min.insync.replicas=2`, быстрые диски,
размещение по зонам; в k8s — Strimzi, в облаке — managed.

</details>

**2.** Как создать топик и какие параметры указать?

<details><summary>Ответ</summary>

`kafka-topics --create` с указанием партиций, репликации, retention,
`min.insync.replicas`, политики очистки.

</details>

**3.** Как посмотреть лаг консьюмер-группы?

<details><summary>Ответ</summary>

`kafka-consumer-groups --describe --group <G>`; в проде — через экспортер и Grafana.

</details>

**4.** Как перемотать группу на начало?

<details><summary>Ответ</summary>

`--reset-offsets --to-earliest --execute` при неактивной группе.

</details>

**5.** Что такое under-replicated partitions?

<details><summary>Ответ</summary>

Партиции, у которых часть реплик не синхронна с лидером — предвестник потери данных.

</details>

**6.** Что делать при заполнении дисков брокеров?

<details><summary>Ответ</summary>

Уменьшить retention, удалить лишние топики, расширить диски, включить компрессию,
настроить мониторинг и планирование ёмкости.

</details>

**7.** Как добавить брокер в кластер?

<details><summary>Ответ</summary>

Добавить брокер и выполнить перераспределение партиций.

</details>

**8.** Как обновлять Kafka без простоя?

<details><summary>Ответ</summary>

Rolling restart по одному брокеру с контролем ISR и совместимости версий.

</details>

**9.** Как настраивается безопасность в Kafka?

<details><summary>Ответ</summary>

TLS, SASL, ACL, сетевая изоляция, отдельные учётные записи на сервисы.

</details>

**10.** Что мониторишь у Kafka?

<details><summary>Ответ</summary>

Лаг групп, under-replicated и offline партиции, ISR, контроллеры, диски,
пропускную способность, ребалансы.

</details>

---

### 🎯 Чек-лист

- [ ] Умею создавать и настраивать топики из CLI
- [ ] ⭐ Смотрю лаг группы и понимаю каждую колонку вывода
- [ ] Умею перематывать оффсеты группы тремя способами
- [ ] Читаю `--describe` топика: лидеры, реплики, ISR
- [ ] Видел поведение кластера при отказе брокера
- [ ] Проверял `min.insync.replicas` на практике
- [ ] Поднял kafka-exporter и дашборд, настроил алерты
- [ ] Знаю, что делать при заполнении дисков
- [ ] Понимаю, что новый брокер требует reassignment
- [ ] Написал рунбук по растущему лагу
