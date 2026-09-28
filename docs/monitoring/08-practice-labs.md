---
title: "08. Практика: 6 лаб по мониторингу"
description: "Стек Prometheus + Grafana с нуля, RED-дашборд своего приложения, алерты в телеграм, blackbox, мониторинг как код, масштаб в Kubernetes"
---

# 08. Практика: 6 лаб по мониторингу

> Роадмап → 7. Остальное → Мониторинг.
> Лабы делаются руками и остаются в git. После них у тебя есть рабочий стек,
> который не стыдно показать на собесе.

---

## 📋 Список лаб

| № | Лаба | Что закрепляет | Артефакт |
|---|------|----------------|----------|
| 1 | Стек с нуля: Prometheus + node_exporter + Grafana | темы 02, 04, 06 | `docker-compose.yml` + дашборд |
| 2 | Приложение со своими метриками + RED-дашборд | темы 03, 04, 07 | код приложения + дашборд |
| 3 | ⭐ Алерты и уведомления в телеграм | тема 05 | `rules.yml` + `alertmanager.yml` + рунбуки |
| 4 | Мониторинг «снаружи»: blackbox + сертификаты | тема 04 | job blackbox + алерты |
| 5 | Всё как код: provisioning, git, CI-проверки | темы 02, 05, 06 | репозиторий мониторинга |
| 6 | Масштаб: VictoriaMetrics + kube-prometheus-stack + ServiceMonitor | тема 11 (сверх роадмапа) | `k8s/` в репозитории + дашборд «30 дней» |

---

## 🧪 Лаба 1. Стек мониторинга с нуля

### Что делаем
Поднимаем Prometheus + node_exporter + cAdvisor + Grafana и доводим до состояния
«вижу состояние своей машины на дашборде».

### Требования
- [ ] `docker-compose.yml` со всеми сервисами и именованными томами
- [ ] `prometheus.yml` написан руками, каждая строка объяснима
- [ ] Все таргеты зелёные на `/targets`
- [ ] Данные Prometheus и Grafana переживают `docker compose down && up`
- [ ] Импортирован дашборд 1860, разобраны 5 панелей
- [ ] Собран свой дашборд «Хост»: CPU, RAM, диск, сеть с единицами и порогами
- [ ] Пароль Grafana задан через переменную окружения, не `admin/admin`
- [ ] Retention выставлен осознанно, посчитан прогноз объёма диска

### Критерии приёмки
```bash
curl -s localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job:.labels.job, health}'
curl -s localhost:9090/api/v1/query?query=up | jq '.data.result | length'
docker compose down && docker compose up -d && sleep 20   # данные на месте
```

### Вопросы себе
- Что произойдёт, если `scrape_interval` поставить 1 секунду?
- Сколько рядов у меня сейчас и сколько это займёт за 30 дней?

---

## 🧪 Лаба 2. Приложение с метриками и RED-дашборд

### Что делаем
Пишем небольшой HTTP-сервис, который отдаёт `/metrics`, и строим по нему
дашборд по методу RED.

### Каркас (Python)
```python
from prometheus_client import Counter, Histogram, Gauge, start_http_server
from http.server import BaseHTTPRequestHandler, HTTPServer
import random, time

REQ = Counter('app_requests_total', 'Запросы', ['method', 'status'])
LAT = Histogram('app_request_duration_seconds', 'Время ответа', ['endpoint'],
                buckets=(.005,.01,.025,.05,.1,.25,.5,1,2.5,5))
QUEUE = Gauge('app_queue_size', 'Очередь задач')

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        start = time.time()
        status = '500' if random.random() < 0.05 else '200'
        time.sleep(random.expovariate(20))
        LAT.labels(endpoint='/').observe(time.time() - start)
        REQ.labels(method='GET', status=status).inc()
        QUEUE.set(random.randint(0, 50))
        self.send_response(int(status)); self.end_headers(); self.wfile.write(b'ok')

start_http_server(8000)          # метрики на :8000/metrics
HTTPServer(('', 8080), H).serve_forever()
```

### Требования
- [ ] Метрики именованы по правилам (`_total`, `_seconds`), без лишних лейблов
- [ ] Приложение добавлено в Prometheus как отдельный job
- [ ] Нагрузка генерируется (`while true; do curl -s localhost:8080 >/dev/null; done`)
- [ ] Дашборд RED: RPS, доля ошибок, p50/p95/p99, длина очереди
- [ ] Сверху ряд Stat-панелей с текущими значениями
- [ ] Панели используют `$__rate_interval` и переменные
- [ ] Посчитан и выведен SLI доступности за период

### Вопросы себе
- Почему p99 сильно выше p50 и что это значит для пользователей?
- Что будет с графиком latency, если доля ошибок вырастет до 50%?

---

## 🧪 Лаба 3. ⭐ Алерты и уведомления

### Что делаем
Доводим стек до состояния «мне сообщают о проблеме раньше, чем я её замечу».

### Требования
- [ ] Минимум 8 правил (см. чек-лист темы 07), проходят `promtool check rules`
- [ ] У каждого алерта: `for`, `severity`, `summary`, `description`, ссылка на рунбук
- [ ] Alertmanager доставляет в телеграм, токен — из файла-секрета
- [ ] Настроены `group_by`, `group_wait`, `repeat_interval`
- [ ] Есть inhibit-правило (InstanceDown подавляет warning'и того же инстанса)
- [ ] Есть watchdog-алерт
- [ ] `send_resolved: true` — приходят уведомления о восстановлении
- [ ] Проверены на практике минимум 3 алерта (остановка экспортера, заполнение диска,
      всплеск ошибок в приложении из лабы 2)
- [ ] Поставлен и снят silence через `amtool`
- [ ] На каждый алерт — рунбук в 3-5 строк в `runbooks/`

### Критерии приёмки
```bash
promtool check rules rules/*.yml
amtool check-config alertmanager.yml
amtool config routes test severity=critical
curl -s localhost:9090/api/v1/rules | jq '.data.groups[].rules[] | {name, state}'
```

### Вопросы себе
- Какой из моих алертов я бы отключил первым и почему?
- Что произойдёт, если упадёт сам Prometheus? Узнаю ли я об этом?

---

## 🧪 Лаба 4. Взгляд снаружи: blackbox и сертификаты

### Что делаем
Добавляем проверки, которые видят сервис так же, как пользователь.

### Требования
- [ ] blackbox_exporter в compose, модули `http_2xx`, `tcp_connect`, `icmp`
- [ ] Job с relabeling для 3+ URL (свой сервис + любые внешние)
- [ ] Алерты: `probe_success == 0`, медленный ответ, скорый конец сертификата
- [ ] Дашборд «Доступность»: статус, время ответа, дни до истечения сертификата
- [ ] Проверено: остановка приложения приводит к `probe_success == 0` и уведомлению
- [ ] Добавлена проверка TCP до базы и ICMP до шлюза

### Вопросы себе
- Чем `probe_success` отличается от `up` по смыслу?
- Какие проблемы видит blackbox и не видит внутренний мониторинг (и наоборот)?

---

## 🧪 Лаба 5. Мониторинг как код

### Что делаем
Приводим всё к состоянию «репозиторий разворачивает мониторинг с нуля».

### Структура репозитория
```text:no-line-numbers
monitoring/
├── docker-compose.yml
├── prometheus/
│   ├── prometheus.yml
│   ├── targets/                 # file_sd
│   └── rules/
│       ├── infra.yml
│       ├── app.yml
│       └── recording.yml
├── alertmanager/
│   ├── alertmanager.yml
│   └── templates/
├── grafana/
│   ├── provisioning/{datasources,dashboards}/
│   └── dashboards/*.json
├── runbooks/
│   ├── instance-down.md
│   ├── disk-space.md
│   └── high-error-rate.md
├── .gitlab-ci.yml  (или .github/workflows/ci.yml)
└── README.md
```

### Требования
- [ ] Источники и дашборды Grafana раскатываются provisioning'ом, `allowUiUpdates: false`
- [ ] Таргеты через `file_sd`, файлы целей в репозитории
- [ ] Recording rules для тяжёлых выражений и SLI
- [ ] CI проверяет: `promtool check config`, `promtool check rules`, `amtool check-config`,
      валидность JSON дашбордов
- [ ] `README.md` объясняет, как развернуть с нуля за 5 минут
- [ ] Проверено: удалил тома, развернул заново — всё на месте, включая дашборды
- [ ] Секреты (токен телеграм, пароли) не в git

### Вопросы себе
- Сколько времени займёт развернуть мой мониторинг на новом сервере?
- Что сломается, если завтра я уйду в отпуск и никто не знает, где что лежит?

---

## 🧪 Лаба 6. Масштаб: долгое хранение и Kubernetes (сверх роадмапа)

### Что делаем
Доводим стек до прод-схемы из [11. Долгое хранение и Kubernetes-оператор](/monitoring/11-long-term-and-operator):
Prometheus держит оперативку, история лежит в VictoriaMetrics, в kind работает
kube-prometheus-stack, linkd подключён ServiceMonitor'ом, правила приходят PrometheusRule'ом из git.

### Требования
- [ ] VictoriaMetrics в compose лабы 5, версия образа зафиксирована, `-retentionPeriod` осознанный
- [ ] `remote_write` с `write_relabel_configs` (в историю — только нужное), `external_labels`: `cluster`, `env`
- [ ] Алерт «remote_write отстаёт > 5 минут», проверен остановкой VM на 10 минут
- [ ] Grafana: VM вторым источником, дашборд «за 30 дней» читает из VM
- [ ] kind + kube-prometheus-stack, values и версия чарта — в `k8s/kps-values.yaml`
- [ ] ServiceMonitor и PrometheusRule для linkd в `k8s/`, таргет UP, группа правил видна на `/rules`
- [ ] Ловушка `release` воспроизведена и описана в README (симптом → команда → причина)
- [ ] `sampleLimit` у ServiceMonitor и `enforcedSampleLimit` у Prometheus
- [ ] Прогноз RAM/диска по правилу большого пальца сравнён с фактом
- [ ] Со звёздочкой: Prometheus из kind тоже пишет в ту же VM (`cluster: kind`; адрес хоста —
      шлюз docker-сети `kind`), дашборд показывает оба «кластера» с переменной `$cluster`
- [ ] Со звёздочкой: та же VM мониторится Zabbix-стендом из [10. Zabbix](/monitoring/10-zabbix) —
      в README абзац «что удобнее где»

### Критерии приёмки
```bash
curl -s 'localhost:8428/api/v1/query?query=count(up)by(cluster)' | jq '.data.result'
kubectl -n linkd get servicemonitor,prometheusrule --show-labels
promtool check rules <(yq '.spec' k8s/prometheusrule-linkd.yaml)
curl -s localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job|test("linkd")) | .health'
```

### Вопросы себе
- Что я потеряю, если VM пролежит 3 часа? А если Prometheus?
- Почему VictoriaMetrics, а не Thanos, — в двух предложениях для собеседования.

---

## 🏁 Что должно остаться после блока

```text:no-line-numbers
monitoring/                 # репозиторий, разворачивающий весь стек
├── рабочие дашборды: хост, приложение (RED), доступность
├── 8-12 осмысленных алертов с рунбуками
├── уведомления в телеграм с группировкой и подавлением
├── blackbox-проверки и контроль сертификатов
├── (сверх роадмапа) VictoriaMetrics + k8s/ с ServiceMonitor и PrometheusRule
└── README с инструкцией и схемой
```

Это ровно тот артефакт, который на собеседовании превращает ответ
«мониторинг — это Prometheus и Grafana» в «вот мой стек, вот алерты, вот рунбуки».
