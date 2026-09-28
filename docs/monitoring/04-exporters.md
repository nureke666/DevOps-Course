---
title: "04. Exporter'ы — откуда берутся метрики"
description: "Карта основных экспортеров, node_exporter, cAdvisor, blackbox_exporter, textfile collector, инструментирование приложения"
---

# 04. Exporter'ы — откуда берутся метрики

> Роадмап → Мониторинг → Prometheus: *«Основные `exporter`'ы»*.
>
> **После темы ты умеешь:** поставить и настроить основные экспортеры, понимать их ключевые
> метрики, добавлять собственные метрики через textfile collector и инструментировать
> приложение.

---

## 🗺️ Что такое exporter

```text:no-line-numbers
   ┌──────────────┐   читает состояние    ┌────────────┐   отдаёт по HTTP   ┌────────────┐
   │ система      │◄──────────────────────│  exporter  │───────────────────►│ Prometheus │
   │ (ОС, БД,     │  /proc, SQL-запросы,  │            │  GET /metrics      │            │
   │  очередь…)   │  API, файлы           │            │  текстовый формат  │            │
   └──────────────┘                       └────────────┘                    └────────────┘
```

Экспортер — переводчик: он знает, как спросить систему о её состоянии, и умеет
представить ответ в формате Prometheus. Если система умеет отдавать `/metrics` сама
(современные приложения, Traefik, etcd, Kubernetes) — экспортер не нужен.

---

## 1. Карта основных экспортеров

| Экспортер | Порт | Что мониторит |
|-----------|------|---------------|
| **node_exporter** | 9100 | ⭐ Linux-хост: CPU, RAM, диск, сеть, файловые системы, systemd |
| **windows_exporter** | 9182 | То же для Windows |
| **cAdvisor** | 8080 | ⭐ Контейнеры: CPU/RAM/сеть/диск по контейнерам |
| **blackbox_exporter** | 9115 | ⭐ Проверки снаружи: HTTP, TCP, ICMP, DNS, срок TLS-сертификата |
| **postgres_exporter** | 9187 | PostgreSQL (см. [раздел «Базы данных»](/databases/07-db-monitoring)) |
| **mysqld_exporter** | 9104 | MySQL/MariaDB |
| **redis_exporter** | 9121 | Redis |
| **mongodb_exporter** | 9216 | MongoDB |
| **nginx-prometheus-exporter** | 9113 | nginx (stub_status) |
| **kafka_exporter** | 9308 | Kafka: лаг консьюмер-групп |
| **elasticsearch_exporter** | 9114 | Elasticsearch |
| **Pushgateway** | 9091 | Приёмник метрик от короткоживущих задач |
| **snmp_exporter** | 9116 | Сетевое оборудование |
| **process-exporter** | 9256 | Отдельные процессы на хосте |

---

## 2. node_exporter — база всего

```bash
# systemd (прод)
useradd --no-create-home --shell /bin/false node_exporter
curl -sL https://github.com/prometheus/node_exporter/releases/download/v1.8.2/node_exporter-1.8.2.linux-amd64.tar.gz | tar xz
install node_exporter-*/node_exporter /usr/local/bin/
```
```ini
# /etc/systemd/system/node_exporter.service
[Unit]
Description=Node Exporter
[Service]
User=node_exporter
ExecStart=/usr/local/bin/node_exporter \
  --collector.textfile.directory=/var/lib/node_exporter/textfile \
  --collector.systemd \
  --no-collector.mdadm
[Install]
WantedBy=multi-user.target
```
```yaml
# docker (учебный стенд)
  node-exporter:
    image: prom/node-exporter:latest
    pid: host
    volumes: ['/:/host:ro,rslave']
    command: ['--path.rootfs=/host']
    ports: ['9100:9100']
```

### Ключевые метрики

| Метрика | Смысл |
|---------|-------|
| `node_cpu_seconds_total{mode=...}` | Время CPU по режимам (counter) |
| `node_memory_MemAvailable_bytes` / `MemTotal_bytes` | Память |
| `node_filesystem_avail_bytes` / `size_bytes` | Диск (фильтруй tmpfs и overlay) |
| `node_filesystem_files_free` | Свободные inode ⭐ забывают, а диск «кончается» именно так |
| `node_disk_io_time_seconds_total` | Насыщение диска |
| `node_network_receive_bytes_total` / `transmit_` | Трафик |
| `node_load1/5/15` | Load average |
| `node_boot_time_seconds` | Аптайм (`time() - node_boot_time_seconds`) |
| `node_systemd_unit_state` | Состояние systemd-юнитов |
| `node_textfile_scrape_error` | Ошибка чтения своих метрик |

### ⭐ Textfile collector — свои метрики без программирования

```bash
mkdir -p /var/lib/node_exporter/textfile
```
```bash
#!/bin/bash
# /usr/local/bin/backup_metrics.sh — запускается по cron
set -euo pipefail
OUT=/var/lib/node_exporter/textfile/backup.prom
TMP=$(mktemp)
LAST=$(stat -c %Y /backup/latest.dump 2>/dev/null || echo 0)
{
  echo "# HELP backup_last_success_timestamp Время последнего успешного бэкапа"
  echo "# TYPE backup_last_success_timestamp gauge"
  echo "backup_last_success_timestamp $LAST"
} > "$TMP"
mv "$TMP" "$OUT"      # ⭐ атомарная замена: Prometheus не прочитает половину файла
```
```text:no-line-numbers
time() - backup_last_success_timestamp > 25*3600     # алерт «бэкапа не было сутки»
```
Так же экспортируют: срок действия сертификатов, версию приложения, результат
регламентных проверок — всё, что удобно посчитать скриптом.

---

## 3. cAdvisor — метрики контейнеров

```yaml
  cadvisor:
    image: gcr.io/cadvisor/cadvisor:latest
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    ports: ['8080:8080']
```
| Метрика | Смысл |
|---------|-------|
| `container_cpu_usage_seconds_total` | CPU контейнера |
| `container_memory_working_set_bytes` | ⭐ Память, по которой считается OOM |
| `container_spec_memory_limit_bytes` | Лимит памяти |
| `container_network_receive_bytes_total` | Сеть |
| `container_last_seen` | Когда контейнер был виден последний раз |

```text:no-line-numbers
# контейнер близок к лимиту памяти
container_memory_working_set_bytes / container_spec_memory_limit_bytes > 0.9
```

> ⚠️ cAdvisor даёт много рядов (лейблы по контейнерам и образам). На больших хостах
> его метрики фильтруют `metric_relabel_configs`. В Kubernetes cAdvisor встроен в kubelet.

---

## 4. blackbox_exporter — взгляд снаружи

Проверяет то, что видит пользователь: отвечает ли сайт, валиден ли сертификат, пингуется
ли хост.

```yaml
# blackbox.yml
modules:
  http_2xx:
    prober: http
    timeout: 5s
    http:
      valid_status_codes: [200]
      follow_redirects: true
      preferred_ip_protocol: ip4
  tcp_connect:
    prober: tcp
  icmp:
    prober: icmp
```
```yaml
# prometheus.yml — классический пример relabeling
  - job_name: blackbox-http
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets: ['https://example.com', 'https://api.example.com/health']
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target       # цель уходит параметром ?target=
      - source_labels: [__param_target]
        target_label: instance             # красивое имя в метриках
      - target_label: __address__
        replacement: blackbox:9115         # а скрейпим сам blackbox_exporter
```
| Метрика | Смысл |
|---------|-------|
| `probe_success` | 1/0 — доступен ли ресурс |
| `probe_duration_seconds` | Время проверки |
| `probe_http_status_code` | Код ответа |
| `probe_ssl_earliest_cert_expiry` | ⭐ Когда истекает сертификат |

```text:no-line-numbers
probe_success == 0
(probe_ssl_earliest_cert_expiry - time()) / 86400 < 14      # сертификат истекает через 2 недели
```

---

## 5. Метрики самого приложения (инструментирование)

Экспортеры показывают инфраструктуру; бизнес-логику приложение отдаёт само.

```python
# Python, prometheus_client
from prometheus_client import Counter, Histogram, Gauge, start_http_server

REQUESTS = Counter('app_requests_total', 'Всего запросов', ['method', 'status'])
LATENCY  = Histogram('app_request_duration_seconds', 'Время обработки', ['endpoint'])
QUEUE    = Gauge('app_queue_size', 'Размер очереди задач')

@LATENCY.labels(endpoint='/api/orders').time()
def handle():
    REQUESTS.labels(method='GET', status='200').inc()

start_http_server(8000)      # /metrics на :8000
```

Правила именования (их спрашивают):
```text:no-line-numbers
app_requests_total            counter → суффикс _total
app_request_duration_seconds  единицы в имени: _seconds, _bytes, _ratio
app_queue_size                gauge без суффикса
```
| Делать | Не делать |
|--------|-----------|
| Базовые единицы (секунды, байты) | Миллисекунды и мегабайты в имени |
| Лейблы с малым числом значений | `user_id`, `request_id`, полный URL |
| Гистограммы для длительностей | Только среднее |
| Метрику «версия сборки» (`app_build_info`) | Метрики-логи с уникальными строками |

---

## 6. Pushgateway — для короткоживущих задач

```bash
# в конце cron/CI-задачи
printf 'backup_duration_seconds 42\nbackup_success 1\nbackup_last_success_timestamp %s\n' "$(date +%s)" \
  | curl --data-binary @- http://pushgateway:9091/metrics/job/db_backup/instance/db1

# удалить залипшую группу метрик
curl -X DELETE http://pushgateway:9091/metrics/job/db_backup/instance/db1
```
| Плюс | Минус |
|------|-------|
| Ловит метрики задач, которые живут секунды | Метрики «залипают» навсегда, пока их не удалить |
| Не нужен доступ от Prometheus к задаче | Не отражает, жив ли источник (`up` относится к самому Pushgateway) |

Правила: пушить только итог задачи (успех, длительность, время завершения),
чистить устаревшие группы, не использовать как общий приёмник метрик сервисов.

> 💡 Для регулярных задач на хосте textfile collector обычно удобнее Pushgateway:
> метрика исчезает вместе с файлом и привязана к конкретному хосту.

---

## 7. Эксплуатация экспортеров

| Вопрос | Практика |
|--------|----------|
| Доступ | Экспортеры слушают внутренний интерфейс; наружу не публикуются |
| Учётные данные | Для БД — отдельная роль только на чтение статистики (`pg_monitor`) |
| Версии | Обновляются вместе со стеком; имена метрик между мажорными версиями меняются |
| Нагрузка | Смотри `scrape_duration_seconds`: тяжёлые экспортеры могут не укладываться в интервал |
| Фильтрация | Лишние коллекторы выключают флагами `--no-collector.*` |
| Дублирование | Одна метрика от двух экспортеров = двойной учёт |

Проверка вручную — всегда первый шаг диагностики:
```bash
curl -s localhost:9100/metrics | head
curl -s localhost:9187/metrics | grep -c '^pg_'
curl -s 'localhost:9115/probe?target=https://example.com&module=http_2xx' | grep probe_success
```

---

## 💼 Как это в DevOps

- Минимальный набор на любом проекте: node_exporter на всех хостах, cAdvisor там, где
  контейнеры, blackbox для внешних проверок, экспортер под каждую базу, `/metrics`
  у приложений.
- Экспортеры ставятся той же автоматикой, что и всё остальное (Ansible-роль, DaemonSet
  в k8s), а не руками по SSH.
- Textfile collector — универсальный «клей»: бэкапы, сертификаты, бизнес-проверки,
  результаты регламентных скриптов.
- blackbox-проверка сертификатов закрывает целый класс инцидентов «сайт лёг, потому что
  протух сертификат».
- Разработчиков просят инструментировать приложение сразу: без метрик приложения
  инфраструктурные графики отвечают только «сервер жив», но не «сервис работает».

---

## 📌 Шпаргалка

| Хочу | Чем |
|------|-----|
| Метрики Linux-хоста | node_exporter :9100 |
| Метрики контейнеров | cAdvisor :8080 |
| Проверить сайт снаружи | blackbox_exporter :9115, `probe_success` |
| Следить за сертификатом | `probe_ssl_earliest_cert_expiry` |
| Метрики PostgreSQL | postgres_exporter :9187, роль с `pg_monitor` |
| Метрики Redis / Mongo / Kafka | redis_exporter :9121 / mongodb_exporter :9216 / kafka_exporter :9308 |
| Метрики nginx | nginx-prometheus-exporter :9113 + `stub_status` |
| Свою метрику из скрипта | textfile collector + атомарный `mv` |
| Метрики cron/CI-задачи | Pushgateway :9091 |
| Метрики приложения | Клиентская библиотека, `/metrics` |
| Проверить экспортер руками | `curl -s localhost:PORT/metrics` |
| Отключить лишний коллектор | `--no-collector.<name>` |
| Свободные inode | `node_filesystem_files_free` |
| Память контейнера для OOM | `container_memory_working_set_bytes` |

---

## 🧠 Что запомнить

1. Экспортер — переводчик состояния системы в формат Prometheus; современные сервисы
   часто отдают `/metrics` сами.
2. node_exporter — база на каждом хосте; cAdvisor — для контейнеров.
3. ⭐ blackbox_exporter показывает то, что видит пользователь, и следит за сроком сертификатов.
4. Для баз — специализированные экспортеры и отдельная роль только на чтение статистики.
5. Textfile collector позволяет отдавать любые метрики из shell-скрипта; файл подменяют
   атомарно через `mv`.
6. Pushgateway — только для короткоживущих задач; метрики оттуда не исчезают сами.
7. Приложение инструментируют клиентской библиотекой: counter, gauge, histogram.
8. Имена метрик — в базовых единицах, с суффиксом `_total` у counter.
9. Лейблы с уникальными значениями запрещены: это убивает Prometheus.
10. При «нет метрик» первым делом `curl` до экспортера, а потом уже конфиги.

---

## Задачи

> Стенд: compose из индекса раздела + добавляем экспортеры по ходу задач.

---

### Блок A. Теория

**A1.** Что такое exporter и когда он не нужен?

<details><summary>Ответ</summary>

Промежуточный сервис, который читает состояние системы и отдаёт его в формате
Prometheus по `/metrics`. Не нужен, если приложение или сервис умеет отдавать метрики сам.

</details>

**A2.** Назови восемь экспортеров и что мониторит каждый.

<details><summary>Ответ</summary>

node_exporter (хост), cAdvisor (контейнеры), blackbox (внешние проверки),
postgres/mysqld/redis/mongodb_exporter (базы), nginx-exporter, kafka_exporter (лаг групп),
elasticsearch_exporter, snmp_exporter (сетевое оборудование), Pushgateway (короткие задачи).

</details>

**A3.** Какие ключевые метрики даёт node_exporter? Назови минимум семь.

<details><summary>Ответ</summary>

CPU по режимам, память (Available/Total), файловые системы (avail/size/inode),
дисковый IO, сетевой трафик, load average, uptime, состояние systemd-юнитов,
ошибки textfile-коллектора.

</details>

**A4.** Почему при мониторинге диска важны не только байты, но и inode?

<details><summary>Ответ</summary>

Файловая система может иметь свободные байты, но исчерпать inode — новые файлы
создать нельзя, приложение падает с `No space left on device`. Классика для каталогов
с миллионами мелких файлов.

</details>

**A5.** ⭐ Что такое textfile collector и в каких задачах он незаменим?

<details><summary>Ответ</summary>

Механизм node_exporter: он читает `*.prom` файлы из каталога и отдаёт их содержимое
как метрики. Незаменим для метрик из shell-скриптов: бэкапы, сертификаты, регламентные
проверки, версии.

</details>

**A6.** Почему файл с метриками подменяют через `mv`, а не пишут напрямую?

<details><summary>Ответ</summary>

Прямая запись может быть прочитана в момент, когда файл записан наполовину —
экспортер получит битые данные. `mv` в пределах одной ФС атомарен.

</details>

**A7.** Что показывает cAdvisor и какая его метрика связана с OOM?

<details><summary>Ответ</summary>

Использование CPU, памяти, сети и диска по контейнерам. С OOM связана
`container_memory_working_set_bytes` — именно её сравнивают с лимитом.

</details>

**A8.** Зачем нужен blackbox_exporter, если есть метрики самого приложения?

<details><summary>Ответ</summary>

Он проверяет сервис «снаружи», как пользователь: доступность через балансировщик,
DNS, TLS, сеть. Метрики приложения не покажут, что до него не доходит трафик.

</details>

**A9.** Разбери relabeling для blackbox: зачем три правила и что делает каждое?

<details><summary>Ответ</summary>

Первое правило кладёт адрес цели в параметр `__param_target` (blackbox ждёт
`?target=`), второе делает из этого читаемый лейбл `instance`, третье подменяет адрес
скрейпа на сам blackbox_exporter.

</details>

**A10.** Какие метрики blackbox используешь для алертов?

<details><summary>Ответ</summary>

`probe_success` (доступность), `probe_duration_seconds` (время ответа),
`probe_http_status_code` (код), `probe_ssl_earliest_cert_expiry` (срок сертификата).

</details>

**A11.** Как инструментировать приложение и какие типы метрик выбрать для запросов,
времени ответа и длины очереди?

<details><summary>Ответ</summary>

Клиентской библиотекой (prometheus_client и аналоги): запросы — counter,
время ответа — histogram, длина очереди — gauge.

</details>

**A12.** Правила именования метрик: какие суффиксы и единицы приняты?

<details><summary>Ответ</summary>

Базовые единицы (секунды, байты), единицы в имени (`_seconds`, `_bytes`),
counter с суффиксом `_total`, имена в snake_case с префиксом приложения.

</details>

**A13.** Когда нужен Pushgateway и в чём его главный недостаток?

<details><summary>Ответ</summary>

Для задач, которые живут меньше интервала сбора (cron, CI). Недостаток —
метрики остаются в Pushgateway навсегда, пока их не удалить, и не отражают живость источника.

</details>

**A14.** Чем textfile collector лучше Pushgateway для задач на хосте?

<details><summary>Ответ</summary>

Метрика привязана к хосту, исчезает вместе с файлом, не требует отдельного сервиса
и не «залипает».

</details>

**A15.** Что проверяешь, если экспортер добавлен, а метрик в Prometheus нет?

<details><summary>Ответ</summary>

`curl` до `/metrics` с самого хоста Prometheus, состояние на `/targets`,
правильность порта и `metrics_path`, сеть/firewall, не отфильтрованы ли метрики relabeling'ом.

</details>

---

### Блок B. «Что делает / что тут не так»

```bash
B1.  curl -s localhost:9100/metrics | grep node_filesystem_avail_bytes
```

<details><summary>Ответ</summary>

Показывает свободное место по файловым системам.

</details>

```bash
B2.  curl -s 'localhost:9115/probe?target=https://example.com&module=http_2xx'
```

<details><summary>Ответ</summary>

Выполняет одиночную проверку URL и печатает метрики пробы.

</details>

```bash
B3.  node_exporter --collector.textfile.directory=/var/lib/node_exporter/textfile
```

<details><summary>Ответ</summary>

Запуск экспортера с включённым textfile-коллектором.

</details>

```bash
B4.  echo "my_metric 1" > /var/lib/node_exporter/textfile/my.prom
```

<details><summary>Ответ</summary>

⚠️ Прямая запись в `.prom` — риск прочитать файл наполовину; нужен `mv`.

</details>

```bash
B5.  curl -X DELETE http://pushgateway:9091/metrics/job/db_backup
```

<details><summary>Ответ</summary>

Удаляет залипшую группу метрик из Pushgateway.

</details>

```text:no-line-numbers
B6.  node_filesystem_avail_bytes / node_filesystem_size_bytes < 0.1
```

<details><summary>Ответ</summary>

Осталось меньше 10% места — корректный алерт (лучше исключить tmpfs/overlay).

</details>

```text:no-line-numbers
B7.  node_filesystem_avail_bytes{fstype=~"tmpfs|overlay"} < 1e9
```

<details><summary>Ответ</summary>

⚠️ Мониторинг tmpfs и overlay — обычно шум, эти ФС фильтруют.

</details>

```text:no-line-numbers
B8.  container_memory_working_set_bytes / container_spec_memory_limit_bytes > 0.9
```

<details><summary>Ответ</summary>

Контейнер близок к лимиту памяти — кандидат на OOM.

</details>

```text:no-line-numbers
B9.  probe_success == 0
```

<details><summary>Ответ</summary>

Ресурс недоступен снаружи.

</details>

```text:no-line-numbers
B10. (probe_ssl_earliest_cert_expiry - time()) / 86400 < 14
```

<details><summary>Ответ</summary>

Сертификат истекает меньше чем через 14 дней.

</details>

```text:no-line-numbers
B11. time() - backup_last_success_timestamp > 25*3600
```

<details><summary>Ответ</summary>

Бэкап не делался больше 25 часов.

</details>

Оцени решения:

```text:no-line-numbers
B12. Метрика приложения: app_request_duration_milliseconds
```

<details><summary>Ответ</summary>

⚠️ Миллисекунды в имени: принято `_seconds`.

</details>

```text:no-line-numbers
B13. Метрика приложения: app_requests_total{url="/api/orders/17384"}
```

<details><summary>Ответ</summary>

⚠️ Идентификатор в лейбле — взрыв кардинальности; нужен шаблон пути.

</details>

```text:no-line-numbers
B14. postgres_exporter подключается к базе суперпользователем postgres
```

<details><summary>Ответ</summary>

⚠️ Избыточные права; нужна роль с `pg_monitor`.

</details>

```text:no-line-numbers
B15. node_exporter опубликован в интернет на 0.0.0.0:9100
```

<details><summary>Ответ</summary>

⚠️ Экспортер раскрывает данные о системе; доступ должен быть только внутренним.

</details>

```text:no-line-numbers
B16. Сервис пушит метрики в Pushgateway каждые 15 секунд вместо /metrics
```

<details><summary>Ответ</summary>

⚠️ Pushgateway не предназначен для постоянных сервисов — сервис должен отдавать `/metrics`.

</details>

```text:no-line-numbers
B17. Один и тот же хост скрейпится двумя job'ами с разными лейблами
```

<details><summary>Ответ</summary>

⚠️ Двойной учёт и дубли на дашбордах.

</details>

---

### Блок C. Практика

#### C1. node_exporter вглубь
1. Найди в выводе `/metrics` метрики CPU, памяти, диска, сети, load, uptime.
2. Посчитай в PromQL: CPU %, RAM %, диск % по каждому монтированию.
3. Отключи один коллектор флагом `--no-collector.*` и убедись, что метрики пропали.

#### C2. 🔑 Textfile collector
1. Включи коллектор, создай каталог.
2. Напиши скрипт, экспортирующий: возраст последнего бэкапа, число файлов в каталоге,
   версию приложения (`app_build_info{version="1.2.3"} 1`).
3. Поставь в cron каждую минуту, проверь метрики в Prometheus.
4. Сломай скрипт намеренно и посмотри `node_textfile_scrape_error`.

<details><summary>Ответ</summary>

Ошибки скрипта проявятся как `node_textfile_scrape_error 1`; это тоже повод
для алерта.

</details>

#### C3. cAdvisor
1. Добавь cAdvisor в compose, пропиши таргет.
2. Найди метрики своих контейнеров, построй график CPU и памяти по контейнеру.
3. Поставь контейнеру лимит памяти и построй выражение «близко к лимиту».
4. Посмотри, сколько рядов добавил cAdvisor (`count({__name__=~"container_.*"})`).

<details><summary>Ответ</summary>

cAdvisor добавляет тысячи рядов — это хороший повод потренировать
`metric_relabel_configs`.

</details>

#### C4. 🔑 blackbox_exporter
1. Подними blackbox, настрой модуль `http_2xx`.
2. Добавь job с relabeling для трёх внешних URL.
3. Проверь `probe_success`, `probe_duration_seconds`, `probe_http_status_code`.
4. Добавь проверку TCP до своей базы и ICMP до шлюза.
5. Построй выражение «сертификат истекает меньше чем через 30 дней».

<details><summary>Ответ</summary>

Если проверка падает, полезно посмотреть `debug=true`:
`curl 'localhost:9115/probe?target=...&module=http_2xx&debug=true'`.

</details>

#### C5. Экспортер базы
Подними postgres_exporter (или redis_exporter) с отдельной ролью только на чтение.
Найди пять метрик, которые реально будешь смотреть.

#### C6. Инструментирование приложения
Напиши маленький HTTP-сервис (Python/Go), который отдаёт `/metrics` с counter,
gauge и histogram. Подключи его к Prometheus, построй RPS и p95.

#### C7. Pushgateway
1. Добавь Pushgateway в стенд.
2. Из скрипта запушь метрики «бэкапа», проверь в Prometheus.
3. Останови скрипт и убедись, что метрики остались навсегда.
4. Удали группу через API.

<details><summary>Ответ</summary>

Метрики останутся в Pushgateway после остановки скрипта — это и есть его
главный недостаток.

</details>

#### C8. Нагрузка на сбор
Посмотри `scrape_duration_seconds` по всем job'ам. Найди самый «тяжёлый» экспортер
и подумай, что можно отключить.

<details><summary>Ответ</summary>

Тяжёлыми обычно оказываются экспортеры баз и cAdvisor; часть коллекторов
отключают или увеличивают интервал сбора для этого job.

</details>

#### C9. Фильтрация метрик
Через `metric_relabel_configs` выброси из cAdvisor метрики, которых не будет
на дашбордах. Сравни число рядов до и после.

#### C10. Инвентаризация
Составь таблицу для своего проекта: объект → экспортер → порт → ключевые метрики →
кто ставит. Это план внедрения мониторинга.

---

### Блок D. Инциденты

**D1.** node_exporter запущен, но метрик диска нет. Что проверишь?

<details><summary>Ответ</summary>

Запущен в контейнере без монтирования `/` и без `--path.rootfs`, отключён
коллектор, фильтрация метрик, смотришь не на тот инстанс.

</details>

**D2.** После добавления cAdvisor Prometheus стал есть вдвое больше памяти. Решение?

<details><summary>Ответ</summary>

Много рядов от контейнерных метрик: отфильтровать ненужные
`metric_relabel_configs`, увеличить интервал сбора, отключить лишние метрики cAdvisor.

</details>

**D3.** `probe_success == 0`, хотя сайт открывается в браузере. Гипотезы?

<details><summary>Ответ</summary>

Проверка идёт с другого адреса/сети (firewall, DNS), другой IP-протокол,
самоподписанный сертификат, редиректы, таймаут, код ответа не 200, требуется заголовок
или авторизация.

</details>

**D4.** Сертификат протух, алерт не сработал. Что нужно было настроить?

<details><summary>Ответ</summary>

blackbox-проверку HTTPS и алерт по `probe_ssl_earliest_cert_expiry`.

</details>

**D5.** Метрики из textfile collector «застыли» на старом значении. Причины?

<details><summary>Ответ</summary>

Скрипт перестал запускаться (cron), падает с ошибкой, пишет в другой каталог,
нет прав, файл не подменяется атомарно; проверить `node_textfile_scrape_error`
и время модификации файла.

</details>

**D6.** В Pushgateway висят метрики удалённого сервера. Почему и что делать?

<details><summary>Ответ</summary>

Pushgateway не удаляет метрики сам. Нужно удалять группу через API в конце
жизненного цикла сервера или ограничивать использование Pushgateway.

</details>

**D7.** postgres_exporter упал, но алерта не было. Чего не хватает?

<details><summary>Ответ</summary>

Алерта на `up == 0` для job экспортера (и/или `absent()`), а также
мониторинга самих экспортеров.

</details>

**D8.** Разработчики добавили метрику с лейблом `order_id`. Как объяснишь проблему
и что предложишь?

<details><summary>Ответ</summary>

Каждый заказ создаёт новый ряд — память и диск Prometheus растут неограниченно.
Предложить: убрать лейбл, считать агрегированно (counter по статусам), а детализацию
искать в логах/трейсах.

</details>

**D9.** Один и тот же сервер отображается дважды на дашборде. Что случилось?

<details><summary>Ответ</summary>

Хост попал в две группы целей (например, в `static_configs` и `file_sd`),
либо изменился лейбл `instance` — старые ряды остались в истории.

</details>

**D10.** Экспортер отдаёт метрики 30 секунд при `scrape_interval: 15s`. Последствия и решения.

<details><summary>Ответ</summary>

Сбор не успевает: появляются пропуски и ошибки `context deadline exceeded`.
Решения: увеличить `scrape_interval` для этого job, отключить тяжёлые коллекторы,
оптимизировать экспортер, вынести его ближе к источнику.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое exporter?

<details><summary>Ответ</summary>

Сервис-переводчик, отдающий состояние системы в формате Prometheus.

</details>

**2.** Какие экспортеры ты использовал?

<details><summary>Ответ</summary>

node_exporter, cAdvisor, blackbox, postgres_exporter, redis_exporter, kafka_exporter
и метрики самих приложений.

</details>

**3.** Что мониторит node_exporter?

<details><summary>Ответ</summary>

CPU, память, диски и inode, сеть, load, uptime, systemd, textfile-метрики.

</details>

**4.** Как замониторить то, для чего нет готового экспортера?

<details><summary>Ответ</summary>

Написать свои метрики через textfile collector, отдать `/metrics` из приложения
или написать небольшой экспортер на клиентской библиотеке.

</details>

**5.** Что такое blackbox_exporter и зачем он нужен?

<details><summary>Ответ</summary>

Экспортер внешних проверок HTTP/TCP/ICMP/DNS: показывает сервис глазами пользователя,
в том числе состояние TLS.

</details>

**6.** Как мониторить срок действия сертификатов?

<details><summary>Ответ</summary>

blackbox + `probe_ssl_earliest_cert_expiry` и алерт за 14-30 дней.

</details>

**7.** Как мониторить контейнеры?

<details><summary>Ответ</summary>

cAdvisor (в k8s — kubelet/cAdvisor), метрики CPU, памяти и сравнение с лимитами.

</details>

**8.** Как мониторить cron-задачи?

<details><summary>Ответ</summary>

Pushgateway или textfile collector + алерт по времени последнего успеха.

</details>

**9.** Как приложение отдаёт метрики?

<details><summary>Ответ</summary>

Клиентская библиотека регистрирует метрики и поднимает HTTP-эндпоинт `/metrics`.

</details>

**10.** Какие правила именования метрик знаешь?

<details><summary>Ответ</summary>

Базовые единицы, единицы в имени, `_total` у counter, snake_case, префикс приложения,
лейблы с ограниченным набором значений.

</details>

---

### 🎯 Чек-лист

- [ ] Поднял node_exporter и знаю его ключевые метрики
- [ ] Мониторю не только байты, но и inode
- [ ] ⭐ Экспортирую свои метрики через textfile collector с атомарным `mv`
- [ ] Поднял cAdvisor и умею сравнивать потребление с лимитами
- [ ] Настроил blackbox с relabeling и понимаю все три правила
- [ ] Слежу за сроком TLS-сертификатов
- [ ] Подключил экспортер базы с ролью только на чтение
- [ ] Инструментировал своё приложение (counter/gauge/histogram)
- [ ] Знаю, когда нужен Pushgateway и как чистить залипшие метрики
- [ ] Умею уменьшить число рядов через `metric_relabel_configs`
