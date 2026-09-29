---
title: "09. Практика: 5 лаб по Python для DevOps"
description: "Блок → Python для DevOps → практика."
---

# 09. Практика: 5 лаб по Python для DevOps

> Блок → **Python для DevOps** → практика.
> Лабы делаются руками и остаются в git — в одном репозитории `ops-tools`. После них у тебя
> есть набор рабочих утилит, которые не стыдно показать на собесе и не страшно запустить в проде.

---

## 📋 Список лаб

| № | Лаба | Что закрепляет | Артефакт |
|---|------|----------------|----------|
| 1 | ⭐ Бэкап с ротацией и выгрузкой в MinIO | темы 01, 03, 04, 07 (S3, textfile) | `backup.py` + systemd-таймер + метрики |
| 2 | Health-checker URL с алертом в Telegram | темы 04, 05 | `healthcheck.py` + конфиг + образ |
| 3 | Анализатор access.log с отчётом | темы 04, 06 | `top_nginx.py` + тесты парсера |
| 4 | ⭐ Kube-«уборщик» подов с dry-run | темы 04, 07 (k8s), 08 (образ) | `pod_janitor.py` + RBAC + CronJob |
| 5 | Свой exporter + упаковка и CI | темы 07 (prometheus), 08 | пакет `ops-exporter`, Dockerfile, `.gitlab-ci.yml` |

Стенд — в [00_INDEX.md](/python/), раздел «Стенд»: MinIO, kind, httpbin, по желанию Prometheus из блока мониторинга.

---

## 🧪 Лаба 1. Бэкап с ротацией и выгрузкой в MinIO

### Что делаем
Утилита, которая архивирует каталог (и по желанию дамп PostgreSQL), проверяет архив, выгружает
в S3-совместимое хранилище, чистит старые копии локально и в бакете и сообщает о результате метриками.

### Каркас конфига
```yaml
# backup.yaml
name: nginx-config
source: /etc/nginx
local_dir: /var/backups/nginx
keep_local: 3                  # последних архивов на диске
s3:
  endpoint: http://localhost:9000
  bucket: backups
  prefix: "{hostname}/nginx-config/"
  keep_days: 14
metrics_file: /var/lib/node_exporter/textfile/backup_nginx.prom
# ключи S3 — только из окружения: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
```text
### Требования
- [ ] Подкоманды: `run`, `list`, `restore KEY DST`, `rotate`; у `run` и `rotate` есть `--dry-run`
- [ ] Архив `tar.gz` собирается во временном каталоге (`tempfile`), имя с UTC-временем
- [ ] Рядом считается sha256; он же пишется в метаданные объекта S3
- [ ] После загрузки — проверка: `head_object` (размер и sha256 совпадают)
- [ ] Ротация локально (оставить N последних) и в бакете (старше `keep_days`, через paginator, `delete_objects`)
- [ ] Метрики через `write_to_textfile`: время последнего успеха, размер, длительность, код результата
- [ ] Настройки: дефолты → YAML → env → CLI; неизвестные ключи конфига — ошибка
- [ ] Логи через `logging` в stderr, `-v` для DEBUG; секреты не попадают в логи
- [ ] Коды выхода: 0 — успех, 1 — бэкап не удался, 2 — ошибка конфигурации
- [ ] Lock-файл: второй экземпляр не стартует
- [ ] `restore` распаковывает через `extractall(..., filter="data")`
- [ ] Запуск по расписанию: systemd-сервис `Type=oneshot` + таймер, venv в `/opt/backup`
- [ ] ⭐ Источник `pg:dbname` — `pg_dump -Fc` через `subprocess.run` с `timeout` и `PGPASSWORD` из env

### Критерии приёмки
```bash
./backup.py --config backup.yaml run --dry-run          # план без изменений
./backup.py --config backup.yaml run; echo "код: $?"
./backup.py --config backup.yaml list | tail -3
./backup.py --config backup.yaml restore &lt;key&gt; /tmp/restore && diff -r /etc/nginx /tmp/restore/nginx
cat /var/lib/node_exporter/textfile/backup_nginx.prom
AWS_SECRET_ACCESS_KEY=wrong ./backup.py --config backup.yaml run; echo "код: $?"   # 1, понятная ошибка
systemctl list-timers | grep backup
```text
### Вопросы себе
- Что будет, если выгрузка оборвётся на середине? Не удалит ли ротация последнюю хорошую копию?
- Как я узнаю, что бэкап не делался трое суток, если скрипт вообще перестал запускаться?
- Почему ротацию в бакете в проде лучше отдать lifecycle-правилам?

---

## 🧪 Лаба 2. Health-checker URL с алертом в Telegram

### Что делаем
Проверяльщик доступности: параллельно опрашивает список URL, хранит состояние и пишет в Telegram
только при смене статуса — «упало» и «восстановилось» с длительностью простоя.

### Каркас конфига
```yaml
# targets.yaml
defaults:
  timeout: 5
  expect_status: 200
targets:
  - name: httpbin
    url: http://localhost:8080/status/200
  - name: slow-api
    url: http://localhost:8080/delay/3
    timeout: 2
  - name: public-site
    url: https://example.com
    expect_text: "Example Domain"
```text
### Требования
- [ ] Параллельная проверка (`ThreadPoolExecutor`), таймаут на каждую цель
- [ ] Проверки: код ответа, опционально подстрока в теле, время ответа
- [ ] Одна повторная проверка перед объявлением DOWN — защита от флапа
- [ ] Состояние в JSON-файле (атомарная запись): статус, с какого момента, последний алерт
- [ ] Уведомления только при смене статуса; напоминание о долгом простое — не чаще раза в N минут
- [ ] Telegram: HTML-разметка, `html.escape` для внешних данных, токен и chat_id из env, токен не попадает в логи
- [ ] Режимы: `--once` (для cron/CI) и `--interval 60` (демон с корректной остановкой по SIGTERM)
- [ ] Код выхода `--once`: 1, если есть недоступные цели
- [ ] JSON-логи (`--log-format json`)
- [ ] Образ: slim, non-root; запуск `docker run -d --restart unless-stopped` с конфигом через volume

### Критерии приёмки
```bash
./healthcheck.py --config targets.yaml --once; echo "код: $?"
docker stop httpbin      # через ≤ 2 интервала — сообщение DOWN в Telegram, одно
docker start httpbin     # сообщение RECOVERED с длительностью простоя
docker stop -t 30 healthcheck && docker logs healthcheck | tail -3   # остановка за секунду, «остановлен» в логе
```text
### Вопросы себе
- Чем мой скрипт хуже связки blackbox_exporter + Alertmanager и когда пора на неё переходить?
- Что будет с уведомлениями, если упадёт сам health-checker? Кто проверит проверяющего?

---

## 🧪 Лаба 3. Анализатор access.log с отчётом

### Что делаем
Утилита разбора логов nginx, которая за минуту отвечает на вопросы разбора инцидента:
сколько было ошибок, где, у кого и насколько медленно.

### Требования
- [ ] Вход: файлы (включая `.gz` и ротированные) или stdin
- [ ] Парсер `combined` + `$request_time`, нераспознанные строки считаются, а не роняют скрипт
- [ ] Отчёт: всего запросов, коды, доля 5xx, топ IP, топ нормализованных путей, p50/p95/p99,
      самые медленные эндпоинты по p95, число 5xx по минутам с «пиковой» минутой
- [ ] Подозрительные клиенты: IP с долей 4xx > 50% или с аномальным числом запросов
- [ ] `--since 15m|2h|1d` — окно по времени (aware-даты)
- [ ] Форматы: text (таблица + гистограмма по часам символами `█`), `--json`, `--csv`
- [ ] `--max-error-rate` — код выхода 1 при превышении (для проверки после деплоя)
- [ ] Тесты парсера: не меньше 10 случаев, включая мусорные строки
- [ ] Замер: 1 млн строк синтетического лога — время и пиковая память (`/usr/bin/time -v`)

### Критерии приёмки
```bash
python3 gen_log.py 1000000 > access.log && gzip -k access.log
/usr/bin/time -v ./top_nginx.py access.log.gz 2>&1 | grep -E 'Elapsed|Maximum resident'
./top_nginx.py access.log --since 15m --json | jq '.error_rate, .latency'
zcat access.log.gz | ./top_nginx.py --csv > report.csv && head -3 report.csv
./top_nginx.py access.log --max-error-rate 0.01; echo "код: $?"
pytest -q tests/test_parser.py
```text
### Вопросы себе
- Как поменяется код, если перевести nginx на JSON-лог? Что станет проще?
- Где граница, после которой разбирать логи скриптом — неправильно, и нужен Loki/ELK?

---

## 🧪 Лаба 4. ⭐ Kube-«уборщик» подов с dry-run

### Что делаем
Утилита, которая находит мусор и проблемы в кластере: `Failed`/`Evicted` поды старше N часов
(удаляет) и поды в `CrashLoopBackOff` с большим числом рестартов (сообщает, по флагу — перезапускает).
Работает и с ноутбука, и как CronJob внутри кластера.

### Требования
- [ ] Конфигурация: `load_incluster_config()` → иначе `load_kube_config(context=...)`; контекст/кластер — в логе первой строкой
- [ ] Dry-run **по умолчанию**; реальные действия только с `--apply`
- [ ] Перед удалением — серверный `dry_run="All"`, затем удаление
- [ ] Удаляются только поды с `owner_references` (кроме `Failed`/`Evicted` — их можно всегда)
- [ ] Фильтры: `--namespace`/все, `--exclude-ns kube-system,monitoring`, `--min-restarts`, `--older-than 6h`
- [ ] Лимит `--max-deletions` за запуск — защита от массового удаления из-за ошибки в фильтре
- [ ] Для CrashLoopBackOff — последние 3 события пода в отчёте
- [ ] Итоговая сводка (найдено / удалено / пропущено и почему); `--json`
- [ ] Уведомление в Telegram со сводкой (функция из лабы 2), если были действия
- [ ] Образ (slim, non-root), ServiceAccount + ClusterRole (pods: get/list/delete, events: list) + CronJob
- [ ] Тесты функций отбора подов на фейковых объектах (`V1Pod(...)` или простые `SimpleNamespace`)

### Манифесты
```yaml
apiVersion: v1
kind: ServiceAccount
metadata: {name: pod-janitor, namespace: ops}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata: {name: pod-janitor}
rules:
  - apiGroups: [""]
    resources: [pods]
    verbs: [get, list, delete]
  - apiGroups: [""]
    resources: [events]
    verbs: [list]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata: {name: pod-janitor}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: pod-janitor}
subjects:
  - {kind: ServiceAccount, name: pod-janitor, namespace: ops}
---
apiVersion: batch/v1
kind: CronJob
metadata: {name: pod-janitor, namespace: ops}
spec:
  schedule: "*/15 * * * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      backoffLimit: 0
      template:
        spec:
          serviceAccountName: pod-janitor
          restartPolicy: Never
          containers:
            - name: janitor
              image: pod-janitor:dev
              imagePullPolicy: IfNotPresent
              args: ["--exclude-ns", "kube-system", "--min-restarts", "5", "--older-than", "6h"]
```text
### Критерии приёмки
```bash
kubectl --context kind-py create deployment crash --image=busybox -- sh -c 'sleep 5; exit 1'
kubectl --context kind-py run bare --image=busybox --restart=Never -- sh -c 'exit 1'   # «голый» Failed-под
./pod_janitor.py --context kind-py                       # только отчёт
./pod_janitor.py --context kind-py --apply --max-deletions 2
docker build -t pod-janitor:dev . && kind load docker-image pod-janitor:dev --name py
kubectl --context kind-py create namespace ops && kubectl --context kind-py apply -f k8s/
kubectl --context kind-py -n ops create job --from=cronjob/pod-janitor manual-1
kubectl --context kind-py -n ops logs job/manual-1
kubectl --context kind-py auth can-i delete pods --as=system:serviceaccount:ops:pod-janitor -A
```text
### Вопросы себе
- Что произойдёт, если в фильтре ошибка и под него попадают все поды? Что меня остановит?
- Почему перезапуск пода в CrashLoopBackOff почти никогда не лечит причину? Что должен делать человек?
- Чем мой уборщик отличается от встроенного GC подов в kube-controller-manager (`terminated-pod-gc-threshold`)?

---

## 🧪 Лаба 5. Свой exporter + упаковка и CI

### Что делаем
Собираем код лаб 1-2 в пакет `ops-exporter`: он отдаёт метрики свежести бэкапов и доступности URL,
упакован, покрыт тестами, собирается в образ и проверяется в GitLab CI.

### Метрики
```text
ops_backup_last_object_timestamp_seconds{bucket, prefix}   время последнего объекта в префиксе
ops_backup_objects{bucket, prefix}                          число объектов
ops_probe_up{target}                                        1/0 по результату проверки
ops_probe_duration_seconds{target}                          время ответа
ops_exporter_errors_total{source}                           ошибки опроса (s3, http)
```text
### Требования
- [ ] src-layout, `pyproject.toml`, entry point `ops-exporter`, `uv.lock`
- [ ] Опрос S3 и URL в фоновом цикле (раз в 60 с), `/metrics` отдаёт кэш — scrape быстрый
- [ ] Лейблы только из конфига (бакеты, префиксы, имена целей) — никаких ключей объектов и URL запросов
- [ ] Ошибка источника не роняет exporter: растёт `ops_exporter_errors_total`, остальные метрики живы
- [ ] Корректная остановка по SIGTERM
- [ ] ruff (с правилами `S`) и `ruff format` — чисто
- [ ] pytest: логика расчёта метрик на фейковых данных, моки boto3 (`unittest.mock`) и HTTP (`responses`)
- [ ] Dockerfile: slim, зависимости отдельным слоем, non-root, exec-форма
- [ ] `.gitlab-ci.yml`: lint → test (junit) → build образа на основной ветке
- [ ] Job в Prometheus + два алерта: «бэкап старше 26 часов» и «цель недоступна 2 минуты»
      (стенд — [лабы блока мониторинга](/softskills/08-practice-labs))

### Критерии приёмки
```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
docker build -t ops-exporter:dev . && docker run -d --name ops-exporter -p 9101:9101 \
  -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY ops-exporter:dev
curl -s localhost:9101/metrics | grep '^ops_'
time curl -s localhost:9101/metrics > /dev/null        # быстро, без походов в S3 на каждый scrape
promtool check rules rules/ops.yml
docker stop ops-exporter                               # останавливается сразу
```text
### Вопросы себе
- Почему здесь фоновый цикл, а не custom collector с запросами в S3 на каждый scrape?
- Сколько временных рядов даёт мой exporter и как это число растёт с конфигом?

---

## 🏁 Что должно остаться после блока

```text
ops-tools/                          # один репозиторий, один pyproject, общий CI
├── src/ops_tools/
│   ├── backup.py                   # лаба 1: бэкап → MinIO, ротация, textfile-метрики
│   ├── healthcheck.py              # лаба 2: проверки URL, состояние, Telegram
│   ├── top_nginx.py                # лаба 3: анализ логов, text/json/csv, код выхода
│   ├── pod_janitor.py              # лаба 4: уборщик подов, dry-run по умолчанию
│   └── exporter.py                 # лаба 5: метрики бэкапов и проб
├── tests/                          # парсер, отбор подов, моки subprocess/HTTP/boto3
├── deploy/
│   ├── systemd/                    # backup.service + backup.timer
│   └── k8s/                        # RBAC + CronJob уборщика
├── Dockerfile
├── .gitlab-ci.yml                  # ruff → pytest → build
└── README.md                       # что делает каждая утилита, какие права и переменные нужны
```text
Это тот артефакт, который превращает на собесе ответ «ну, я немного пишу на Python» в
«вот мои утилиты: бэкапы с проверкой и метриками, уборщик подов с RBAC и dry-run, exporter, CI с тестами».

➡️ Дальше: [10_interview.md](/python/10-interview)
