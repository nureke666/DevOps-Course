---
title: "02. SLI, SLO и error budget"
description: "Блок → SRE и Observability → тема 02. Продолжает"
---

# 02. SLI, SLO и error budget

> Блок → SRE и Observability → тема 02. Продолжает
> [../Left/02_Monitoring/07_what_to_monitor.md](/monitoring/07-what-to-monitor)
> (раздел «От SLO к порогам алертов») и опирается на
> [../Left/02_Monitoring/03_promql.md](/monitoring/03-promql) (recording rules).
>
> **После темы ты умеешь:** выбрать SLI для сервиса, обосновать SLO и окно, посчитать error
> budget в минутах и запросах, написать recording rules и multi-window multi-burn-rate алерты,
> собрать SLO-дашборд и объяснить, что генерируют Sloth и Pyrra.

---

## 🗺️ Карта темы

```text
 пользователь ──► что для него «хорошо»? ──► SLI = хорошие события / все валидные
                                                   │
                                                   ▼
                                          SLO: 99,9% за 30 дней
                                                   │
                      ┌────────────────────────────┼──────────────────────────┐
                      ▼                            ▼                          ▼
              error budget = 0,1%          burn rate алерты            error budget policy
              ≈ 43 мин простоя или         14,4× и 6× → страница       катим / осторожно / стоп
              1000 из 1 млн запросов       3× и 1×    → тикет
                      │                            │                          │
                      └──────────────── SLO-дашборд в Grafana ────────────────┘
```text
---

## 1. SLI, SLO, SLA — точнее, чем в блоке мониторинга

```text
SLI  =  хорошие события / валидные события        (всегда доля, от 0 до 1)
SLO  =  SLI ≥ цель за окно                         «99,9% запросов /checkout успешны за 30 дней»
SLA  =  SLO, записанный в договор, + последствия  «ниже 99,5% — возврат 10% оплаты»
```text
| | SLO | SLA |
|---|-----|-----|
| Для кого | Для своей команды | Для клиента, юридически |
| Строгость | Строже | Мягче: SLO 99,9% → SLA 99,5%, чтобы был запас |
| Нарушение | Срабатывает policy: чиним надёжность | Штрафы, кредиты, репутация |
| Есть ли у каждого сервиса | Должен быть у каждого важного | Только у того, что продаётся наружу |

> ⭐ SLA без внутреннего SLO — ловушка: о нарушении договора узнаёшь от клиента.

---

## 2. Как выбирать SLI

Начинают не с метрик, а с **критичных пользовательских сценариев** (critical user journeys):
вход, поиск, оформление заказа. Для каждого — 1–3 SLI.

| Тип сервиса | SLI | «Хорошее» событие |
|-------------|-----|-------------------|
| API / веб | **Availability** | Ответ не 5xx (и не таймаут) |
| API / веб | **Latency** | Ответ быстрее порога, например 300 мс |
| Пайплайн данных, батч | **Freshness** | Данные обновлены не позже N минут назад |
| Пайплайн данных | **Correctness / coverage** | Запись обработана верно / обработано ≥ X% входа |
| Хранилище | **Durability** | Записанный объект читается без потерь |

### Готовые SLI на PromQL

```promql
# Availability: доля не-5xx ответов /checkout
sum(rate(http_requests_total{job="shop-api",handler="/checkout",status!~"5.."}[5m]))
  / sum(rate(http_requests_total{job="shop-api",handler="/checkout"}[5m]))

# Latency: доля запросов быстрее 300 мс (корзина le="0.3" должна существовать!)
sum(rate(http_request_duration_seconds_bucket{job="shop-api",handler="/checkout",le="0.3"}[5m]))
  / sum(rate(http_request_duration_seconds_count{job="shop-api",handler="/checkout"}[5m]))

# Freshness: доля минут за 30 дней, когда данные были свежее 15 минут (subquery)
avg_over_time(((time() - pipeline_last_success_timestamp_seconds) < bool 900)[30d:1m])
```text
> ⚠️ Латентный SLI считают **через корзину гистограммы**, а не через `histogram_quantile`:
> «доля быстрых запросов» складывается и усредняется честно, а перцентили — нет.
> Порог SLO должен совпадать с границей корзины. В Prometheus 3 значения `le`
> нормализуются: `le="1"` превращается в `le="1.0"`, а `le="0.3"` остаётся как есть.

### Где измерять

| Точка | Плюсы | Минусы |
|-------|-------|--------|
| Логи/метрики балансировщика (Ingress) | Близко к пользователю, видит таймауты и 502 | Не видит сбои до балансировщика (DNS, CDN) |
| Метрики приложения | Просто, детально по эндпоинтам | Не видит запросы, которые до приложения не дошли |
| Синтетика (blackbox, k6 по расписанию) | Работает даже без трафика | Мало событий, проверяет «сценарий робота» |
| Клиент (RUM, мобильное приложение) | Ровно то, что видит пользователь | Шумно, сложно, данные приходят с задержкой |

Практика: SLI — с балансировщика или приложения, синтетика — как дополнение для
малотрафиковых сервисов ([../Left/02_Monitoring/04_exporters.md](/monitoring/04-exporters), blackbox).

### Что считать «валидным» событием

- **Исключать:** health checks, запросы мониторинга, трафик нагрузочных тестов.
- **4xx** обычно не ошибка сервиса (клиент прислал мусор) — но есть исключения:
  `429` от своего же rate limiter из-за нехватки мощности и массовые `404` после кривого
  релиза — это ваша проблема.
- **Таймауты клиента** (обрыв соединения) сервис может не увидеть вовсе — ещё один
  аргумент мерить на балансировщике.

---

## 3. Как выбрать число SLO

1. **Посмотри историю.** Какой SLI был за последние 4 недели? SLO ставят чуть ниже
   реального, чтобы появился бюджет, — и никогда выше того, что система умеет.
2. **Спроси бизнес.** Что пользователь терпит? Оплата и вход — строже, отчёты — мягче.
3. **Учти зависимости.** Синхронная цепочка из 99,9% × 99,9% даёт ~99,8%: выше не прыгнешь.
4. **Latency — несколько порогов:** «99% быстрее 300 мс» и «99,9% быстрее 1 с».
5. **Пересматривай раз в квартал.** SLO, который ни разу не нарушался и никого не будит, —
   возможно, слишком мягкий; который горит каждый месяц — нереалистичный.

> ⚠️ Нельзя: SLO по среднему времени ответа; SLO «на CPU»; SLO = 100%;
> SLO, который никто не согласовал с продуктом.

---

## 4. Окно: rolling или календарное

| | Rolling 28/30 дней | Календарный месяц |
|---|--------------------|-------------------|
| Как считается | Всегда «последние N дней» | С 1-го числа, в начале месяца бюджет обнуляется |
| Плюсы | Нет «сброса», решения всегда по свежим данным | Удобно для отчётов и SLA |
| Минусы | Сложнее объяснить бизнесу | Стимул «дожечь бюджет в конце месяца» |
| Для чего | ⭐ Инженерные решения и алерты | Отчётность, договоры |

Почему часто берут **28 дней**: это ровно 4 недели, в каждом окне одинаковое число выходных,
и недельная сезонность не искажает SLI. Пороги burn rate в этом конспекте даны для
**30 дней** (как в SRE Workbook) — для 28 дней они почти такие же.

> Retention Prometheus должен покрывать окно: для 30-дневного SLO — минимум 30 дней
> (на стенде — `--storage.tsdb.retention.time=35d`).

---

## 5. Error budget: считаем

```text
по времени:    бюджет = (1 − SLO) × длительность окна
по запросам:   бюджет = (1 − SLO) × число валидных запросов за окно
```text
| SLO | день | неделя | 28 дней | 30 дней | квартал (90 д) | год (365 д) |
|-----|------|--------|---------|---------|----------------|-------------|
| 99% | 14 мин 24 с | 1 ч 40 мин 48 с | 6 ч 43 мин 12 с | 7 ч 12 мин | 21 ч 36 мин | 3 д 15 ч 36 мин |
| 99,5% | 7 мин 12 с | 50 мин 24 с | 3 ч 21 мин 36 с | 3 ч 36 мин | 10 ч 48 мин | 1 д 19 ч 48 мин |
| ⭐ 99,9% | 1 мин 26 с | 10 мин 5 с | 40 мин 19 с | 43 мин 12 с | 2 ч 9 мин 36 с | 8 ч 45 мин 36 с |
| 99,95% | 43 с | 5 мин 2 с | 20 мин 10 с | 21 мин 36 с | 1 ч 4 мин 48 с | 4 ч 22 мин 48 с |
| 99,99% | 8,6 с | 1 мин 0,5 с | 4 мин 2 с | 4 мин 19 с | 12 мин 58 с | 52 мин 34 с |
| 99,999% | 0,9 с | 6 с | 24 с | 26 с | 1 мин 18 с | 5 мин 15 с |

Проверка в уме: 30 дней = 43 200 минут; 0,1% от них = 43,2 минуты.

```text
По запросам: 10 млн запросов/мес × 0,1% = 10 000 «плохих» запросов в бюджете.
Частичный сбой: 10% ошибок в течение 2 часов = 0,1 × 120 мин = 12 «минут полного простоя»
               = 12 / 43,2 ≈ 28% месячного бюджета.
```text
> 💡 Бюджет по запросам честнее: 10 минут простоя в 3 ночи и 10 минут в час пик —
> это разное число пострадавших пользователей. SLI из этого конспекта — request-based.

Остаток бюджета на PromQL:
```promql
# доля ошибок за 30 дней
  sum(increase(http_requests_total{job="shop-api",handler="/checkout",status=~"5.."}[30d]))
/ sum(increase(http_requests_total{job="shop-api",handler="/checkout"}[30d]))

# остаток бюджета (1 = нетронут, 0 = исчерпан, < 0 = SLO нарушен)
1 - ( &lt;доля ошибок за 30d&gt; ) / 0.001
```text
---

## 6. Error budget policy

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ ERROR BUDGET POLICY — shop-api                         согласовано: CTO  │
├──────────────────────────────────────────────────────────────────────────┤
│ SLO: 99,9% успешных запросов /checkout, rolling 30 дней                  │
│                                                                          │
│ Остаток > 50%   релизы как обычно, разрешены рискованные изменения       │
│ Остаток 25–50%  релизы только с канарейкой и проверенным откатом         │
│ Остаток < 25%   только фиксы надёжности и безопасности; ревью SRE        │
│ Бюджет ≤ 0      заморозка фич до возврата SLI в норму за последние 7 дней│
│                                                                          │
│ Постмортем обязателен: инцидент съел > 20% бюджета или был SEV1/SEV2     │
│ Исключения: утверждает CTO письменно, с планом возврата надёжности       │
│ Сбои внешних зависимостей: считаются (пользователю всё равно), но ведут  │
│   к задачам на резервирование, а не к заморозке фич                      │
│ Пересмотр SLO и policy: раз в квартал                                    │
└──────────────────────────────────────────────────────────────────────────┘
```text
---

## 7. Burn rate — скорость сжигания бюджета

```text
burn rate = наблюдаемая доля ошибок / (1 − SLO)

время до исчерпания бюджета = окно / burn rate
доля бюджета, сгоревшая за время t = burn rate × t / окно
```text
| Burn rate | Доля ошибок при SLO 99,9% | Весь бюджет (30 д) сгорит за | За 1 час сгорает |
|-----------|---------------------------|------------------------------|------------------|
| 1 | 0,1% | 30 дней — ровно к концу окна | 0,14% |
| 3 | 0,3% | 10 дней | 0,42% |
| 6 | 0,6% | 5 дней | 0,83% |
| 14,4 | 1,44% | 50 часов (~2 дня) | 2% |
| 1000 | 100% (полный простой) | 43,2 минуты | весь |

> ⚠️ Частая путаница: burn rate 14,4 **не** означает «бюджет сгорит за 2 часа».
> За 1 час сгорает 2% бюджета, а весь — за 50 часов. Отсюда и число: 2% × 720 ч / 1 ч = 14,4.

---

## 8. Почему простые алерты не работают

Эволюция из SRE Workbook (глава «Alerting on SLOs»), кратко:

| Подход | Что не так |
|--------|------------|
| Доля ошибок > 0,1% за 10 минут | Шумно: будит из-за всплеска, съевшего 0,02% бюджета |
| Доля ошибок > 0,1% за 30 дней | Узнаёшь очень поздно и алерт горит ещё долго после починки |
| То же + `for: 1h` | 100% ошибок в течение 59 минут — молчит, а бюджет 43 минуты уже сгорел |
| Один burn rate 14,4 за 1 час | Не видит медленное горение: burn rate 5 съест бюджет за 6 дней без единого алерта |
| Несколько burn rate | Ловит и быстрое, и медленное горение, но долго не гаснет после починки |
| ⭐ **Multi-window multi-burn-rate** | Длинное окно — значимость, короткое — «ещё горит прямо сейчас» |

```text
Зачем короткое окно (reset time):
ошибки кончились ──►  ratio_rate1h ещё ~час выше порога (в окне хвост инцидента)
                      ratio_rate5m падает ниже порога через ~5 минут
                      алерт = long AND short ⇒ гаснет через ~5 минут, а не через час
```text
---

## 9. Multi-window multi-burn-rate: пороги

Рекомендация SRE Workbook для SLO с окном 30 дней:

| Severity | Длинное окно | Короткое окно | Burn rate | Сгорит бюджета | Порог доли ошибок при 99,9% |
|----------|--------------|---------------|-----------|----------------|-----------------------------|
| page (critical) | 1 ч | 5 мин | 14,4 | 2% | 1,44% |
| page (critical) | 6 ч | 30 мин | 6 | 5% | 0,6% |
| ticket (warning) | 1 д | 2 ч | 3 | 10% | 0,3% |
| ticket (warning) | 3 д | 6 ч | 1 | 10% | 0,1% |

Короткое окно = 1/12 длинного. Проверка: 14,4 × 1 ч / 720 ч = 0,02 = 2%; 6 × 6 / 720 = 5%;
3 × 24 / 720 = 10%; 1 × 72 / 720 = 10%.

Как быстро сработает страница (порог 1,44% на окне 1 час):
```text
полный простой (100% ошибок):  0,0144 × 60 мин ≈ 52 секунды
5% ошибок:                      0,0144 / 0,05 × 60 мин ≈ 17 минут
```text
---

## 10. Recording rules и алерты

```yaml
# rules/slo-shop-api.yml
groups:
  - name: slo-shop-api-recordings
    interval: 30s
    rules:
      - record: job:slo_errors_per_request:ratio_rate5m
        expr: |
          sum by (job) (rate(http_requests_total{job="shop-api",handler="/checkout",status=~"5.."}[5m]))
          / sum by (job) (rate(http_requests_total{job="shop-api",handler="/checkout"}[5m]))
      - record: job:slo_errors_per_request:ratio_rate30m
        expr: |
          sum by (job) (rate(http_requests_total{job="shop-api",handler="/checkout",status=~"5.."}[30m]))
          / sum by (job) (rate(http_requests_total{job="shop-api",handler="/checkout"}[30m]))
      - record: job:slo_errors_per_request:ratio_rate1h
        expr: |
          sum by (job) (rate(http_requests_total{job="shop-api",handler="/checkout",status=~"5.."}[1h]))
          / sum by (job) (rate(http_requests_total{job="shop-api",handler="/checkout"}[1h]))
      - record: job:slo_errors_per_request:ratio_rate2h
        expr: |
          sum by (job) (rate(http_requests_total{job="shop-api",handler="/checkout",status=~"5.."}[2h]))
          / sum by (job) (rate(http_requests_total{job="shop-api",handler="/checkout"}[2h]))
      - record: job:slo_errors_per_request:ratio_rate6h
        expr: |
          sum by (job) (rate(http_requests_total{job="shop-api",handler="/checkout",status=~"5.."}[6h]))
          / sum by (job) (rate(http_requests_total{job="shop-api",handler="/checkout"}[6h]))
      - record: job:slo_errors_per_request:ratio_rate1d
        expr: |
          sum by (job) (rate(http_requests_total{job="shop-api",handler="/checkout",status=~"5.."}[1d]))
          / sum by (job) (rate(http_requests_total{job="shop-api",handler="/checkout"}[1d]))
      - record: job:slo_errors_per_request:ratio_rate3d
        expr: |
          sum by (job) (rate(http_requests_total{job="shop-api",handler="/checkout",status=~"5.."}[3d]))
          / sum by (job) (rate(http_requests_total{job="shop-api",handler="/checkout"}[3d]))

  - name: slo-shop-api-alerts
    rules:
      - alert: ShopApiErrorBudgetBurnFast
        expr: |
          (
            job:slo_errors_per_request:ratio_rate1h{job="shop-api"} > (14.4 * 0.001)
            and
            job:slo_errors_per_request:ratio_rate5m{job="shop-api"} > (14.4 * 0.001)
          )
          or
          (
            job:slo_errors_per_request:ratio_rate6h{job="shop-api"} > (6 * 0.001)
            and
            job:slo_errors_per_request:ratio_rate30m{job="shop-api"} > (6 * 0.001)
          )
        labels:
          severity: critical
          slo: shop-api-availability
        annotations:
          summary: "shop-api быстро сжигает error budget (SLO 99,9%)"
          runbook_url: "https://wiki.example.com/runbooks/shop-api-slo"

      - alert: ShopApiErrorBudgetBurnSlow
        expr: |
          (
            job:slo_errors_per_request:ratio_rate1d{job="shop-api"} > (3 * 0.001)
            and
            job:slo_errors_per_request:ratio_rate2h{job="shop-api"} > (3 * 0.001)
          )
          or
          (
            job:slo_errors_per_request:ratio_rate3d{job="shop-api"} > (1 * 0.001)
            and
            job:slo_errors_per_request:ratio_rate6h{job="shop-api"} > (1 * 0.001)
          )
        labels:
          severity: warning
          slo: shop-api-availability
        annotations:
          summary: "shop-api медленно сжигает error budget (SLO 99,9%)"
          runbook_url: "https://wiki.example.com/runbooks/shop-api-slo"
```text
Разбор решений:
- Доля ошибок за окно считается как `rate(ошибок[окно]) / rate(всех[окно])` по сырым
  счётчикам, а **не** как `avg_over_time` от 5-минутной доли: среднее от долей даёт
  тихим ночным часам тот же вес, что и пиковым.
- `for` не нужен: роль «подтверждения» играет короткое окно. Можно добавить `for: 2m`
  от дребезга.
- Когда горят оба алерта, warning подавляют inhibit-правилом по лейблу `slo`
  ([../Left/02_Monitoring/05_alertmanager.md](/monitoring/05-alertmanager)).
- Латентный SLO (99% быстрее 300 мс) — такие же правила с
  `1 - bucket{le="0.3"} / count` и порогами от бюджета 1%: `14.4 * 0.01` и т.д.

Проверка правил — `promtool check rules`, а поведение алертов — unit-тестом:
```yaml
# tests/slo-shop-api_test.yml
rule_files: [../rules/slo-shop-api.yml]
evaluation_interval: 1m
tests:
  - interval: 1m
    input_series:
      - series: 'http_requests_total{job="shop-api",handler="/checkout",status="200"}'
        values: '0+980x180'          # 980 успешных в минуту, 3 часа
      - series: 'http_requests_total{job="shop-api",handler="/checkout",status="500"}'
        values: '0+20x180'           # 20 ошибок в минуту → 2% > 1,44%
    alert_rule_test:
      - eval_time: 70m
        alertname: ShopApiErrorBudgetBurnFast
        exp_alerts:
          - exp_labels: { job: shop-api, severity: critical, slo: shop-api-availability }
            exp_annotations:
              summary: "shop-api быстро сжигает error budget (SLO 99,9%)"
              runbook_url: "https://wiki.example.com/runbooks/shop-api-slo"
```text
```bash
docker run --rm -v "$PWD":/w -w /w --entrypoint promtool prom/prometheus:latest \
  test rules tests/slo-shop-api_test.yml
```text
---

## 11. SLO-дашборд в Grafana

| Панель | Тип | Запрос |
|--------|-----|--------|
| SLI за 30 дней | Stat, порог 99,9% | `1 - (sum(increase(...{status=~"5.."}[30d])) / sum(increase(...[30d])))` |
| Остаток бюджета | Gauge 0–100% | `1 - (&lt;доля ошибок за 30d&gt;) / 0.001` |
| Burn rate 1h и 6h | Time series, линии порогов 14,4 и 6 | `job:slo_errors_per_request:ratio_rate1h{job="shop-api"} / 0.001` |
| Доля ошибок vs цель | Time series | `job:slo_errors_per_request:ratio_rate5m{job="shop-api"}` и константа `0.001` |
| Сгорание бюджета во времени | Time series за 30 дней | Recording rule `..._ratio_rate30d` c `interval: 5m`, иначе панель тяжёлая |
| Состояние алертов | Alert list | Фильтр по лейблу `slo` |

Приёмы из [../Left/02_Monitoring/06_grafana.md](/monitoring/06-grafana):
переменная `$service`, единицы `percentunit`, дашборд — в git через provisioning.

> ⚠️ Если 5xx ещё ни разу не было, рядов с `status=~"5.."` нет, и доля ошибок —
> «No data», а не 0. Лечится инициализацией счётчика ошибок нулём в коде приложения
> (так сделано в демо-сервисе стенда).

---

## 12. Инструменты: Sloth и Pyrra

Писать 7 recording rules на каждый SLO руками утомительно — их генерируют.

**Sloth** — CLI/оператор: из короткой спецификации генерирует recording rules для всех окон
и multi-window multi-burn-rate алерты.
```yaml
# slo/shop-api.yml
version: "prometheus/v1"
service: "shop-api"
labels:
  team: "shop"
slos:
  - name: "checkout-availability"
    objective: 99.9
    description: "Доля не-5xx ответов /checkout"
    sli:
      events:
        error_query: sum(rate(http_requests_total{job="shop-api",handler="/checkout",status=~"5.."}[&#123;&#123;.window&#125;&#125;]))
        total_query: sum(rate(http_requests_total{job="shop-api",handler="/checkout"}[&#123;&#123;.window&#125;&#125;]))
    alerting:
      name: ShopApiCheckoutAvailability
      page_alert:
        labels: { severity: critical }
      ticket_alert:
        labels: { severity: warning }
```text
```bash
sloth generate -i slo/shop-api.yml > rules/slo-shop-api-generated.yml
```text
Что получится: recording rules `slo:sli_error:ratio_rate5m` … `ratio_rate3d` и `ratio_rate30d`,
служебные `slo:error_budget:ratio`, `slo:period_error_budget_remaining:ratio` и два алерта
(page и ticket) с теми же окнами и порогами 14,4 / 6 / 3 / 1, что в разделе 10.

**Pyrra** — оператор для Kubernetes (или режим с файлами) + веб-интерфейс со списком SLO
и графиками бюджета. Описание — CRD:
```yaml
apiVersion: pyrra.dev/v1alpha1
kind: ServiceLevelObjective
metadata: { name: shop-api-checkout, namespace: monitoring }
spec:
  target: "99.9"
  window: 4w
  indicator:
    ratio:
      errors: { metric: 'http_requests_total{job="shop-api",handler="/checkout",status=~"5.."}' }
      total:  { metric: 'http_requests_total{job="shop-api",handler="/checkout"}' }
```text
| | Руками | Sloth | Pyrra |
|---|--------|-------|-------|
| Понимание механики | ⭐ полное | Нужно для ревью | Нужно для ревью |
| Скорость заведения SLO | Медленно | Быстро | Быстро |
| UI | Свой дашборд | Готовый дашборд Grafana | Свой веб-интерфейс |
| Где жить | Любой Prometheus | CLI в CI или оператор | Kubernetes или файлы |

Сначала напиши правила руками (лаба 2), потом генерируй — и читай сгенерированное.

---

## 13. Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| SLO на CPU/память | Не отражает боль пользователя | SLI от запросов пользователя |
| SLO выше исторического SLI | Бюджет отрицательный с первого дня | Цель чуть ниже реального уровня |
| Латентный SLO через `histogram_quantile` | Перцентили нельзя усреднять и складывать | Доля запросов в корзине `le` |
| Порог SLO не совпадает с корзиной | Невозможно посчитать точно | Корзина ровно на пороге |
| `avg_over_time` от 5-минутных долей | Искажение: ночь весит как пик | `rate(ошибок[окно]) / rate(всех[окно])` |
| Retention меньше окна | SLI за 30 дней считается по 15 | Retention ≥ окна, или долгое хранилище |
| Малотрафиковый сервис | 1 ошибка из 10 запросов = 10% → страница | Синтетика, объединение сервисов, минимум запросов в условии |
| Health checks в SLI | SLI завышен | Исключать служебный трафик |
| Policy без подписи руководства | При первом конфликте «исключение» | Согласовать заранее, письменно |
| Считать, что 14,4 = «2 часа до конца» | Неверная срочность | 2% за час, весь бюджет — за 50 часов |

---

## 💼 Как это в DevOps

- SLO заводят вместе с продуктом: девопс приносит историю SLI и стоимость «девяток»,
  продукт — требования пользователей; решение фиксируют в репозитории рядом с правилами.
- Правила SLO живут в git, проходят `promtool check rules` и `promtool test rules` в CI —
  сломанный SLO-алерт хуже, чем никакого: он создаёт ложное чувство защищённости.
- На планировании смотрят остаток бюджета: «бюджета 20% — берём в спринт задачи
  надёжности». Это и есть работа error budget policy.
- Постмортем почти всегда начинается с «сколько бюджета съел инцидент» — это
  объективная мера ущерба.
- Для десятков сервисов правила генерируют (Sloth/Pyrra) из коротких спецификаций,
  а девопс ревьюит спецификации и сгенерированные пороги.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| SLI доступности | `sum(rate(req{status!~"5.."}[5m])) / sum(rate(req[5m]))` |
| SLI латентности | `sum(rate(dur_bucket{le="0.3"}[5m])) / sum(rate(dur_count[5m]))` |
| Бюджет в минутах | `(1 − SLO) × минуты окна`: 99,9% за 30 д = 43,2 мин |
| Бюджет в запросах | `(1 − SLO) × запросов за окно` |
| Burn rate | `доля ошибок / (1 − SLO)` |
| Время до исчерпания | `окно / burn rate` |
| Страница (быстро) | 1h & 5m > 14,4 × бюджет; 6h & 30m > 6 × бюджет |
| Тикет (медленно) | 1d & 2h > 3 × бюджет; 3d & 6h > 1 × бюджет |
| Имя recording rule | `job:slo_errors_per_request:ratio_rate1h` |
| Остаток бюджета | `1 - (доля ошибок за 30d) / (1 − SLO)` |
| Проверить правила | `promtool check rules rules/*.yml` |
| Протестировать алерт | `promtool test rules tests/*_test.yml` |
| Сгенерировать правила | `sloth generate -i slo.yml > rules.yml` |

---

## 🧠 Что запомнить

1. SLI — всегда доля «хороших» событий от валидных; начинается с пользовательского сценария.
2. SLO ставят чуть ниже исторического уровня и согласуют с продуктом; SLA мягче SLO.
3. Латентный SLI — доля запросов в корзине гистограммы, а не перцентиль.
4. Для решений — rolling-окно (28/30 дней), для отчётов — календарное.
5. ⭐ 99,9% за 30 дней = 43,2 минуты или 1 плохой запрос из 1000.
6. Burn rate = доля ошибок / (1 − SLO); весь бюджет сгорает за «окно / burn rate».
7. Пороги Workbook: 14,4 (1h/5m) и 6 (6h/30m) — страница; 3 (1d/2h) и 1 (3d/6h) — тикет.
8. Длинное окно отвечает за значимость, короткое — за быстрое срабатывание и быстрое затухание.
9. Правила SLO — в git, с `promtool check` и unit-тестами алертов.
10. Error budget policy превращает график в решения: без неё бюджет — просто красивая панель.

➡️ Дальше: [03_tracing_opentelemetry.md](/sre/03-tracing-opentelemetry) · задачи: 02_sli_slo_error_budget_tasks.md


---

### Блок A. Теория


**A1.** Дай определения SLI, SLO и SLA. Почему SLA обычно мягче SLO?

<details><summary>Ответ</summary>

SLI — измеримая доля хороших событий; SLO — внутренняя цель по SLI за окно;
SLA — SLO в договоре с последствиями. SLA мягче, чтобы внутренний SLO срабатывал раньше
и команда успевала починить до нарушения договора.

</details>

**A2.** Почему SLI — это всегда доля? Запиши общую формулу.

<details><summary>Ответ</summary>

Доля нормирует показатель на трафик и позволяет сравнивать сервисы и периоды:
`SLI = хорошие события / валидные события`.

</details>

**A3.** Какие SLI подходят для API, для пайплайна данных, для хранилища?

<details><summary>Ответ</summary>

API — доступность и латентность; пайплайн — свежесть, корректность, полнота;
хранилище — долговечность (durability), доступность, латентность.

</details>

**A4.** ⭐ Почему латентный SLI считают через корзину гистограммы, а не через
`histogram_quantile`?

<details><summary>Ответ</summary>

Доля запросов в корзине `le` — это отношение счётчиков: её можно честно суммировать
по инстансам и окнам. Перцентили нельзя складывать и усреднять, а `histogram_quantile`
ещё и интерполирует внутри корзины.

</details>

**A5.** Где можно измерять SLI? Сравни балансировщик и метрики приложения.

<details><summary>Ответ</summary>

Балансировщик ближе к пользователю и видит 502/504 и таймауты, но не видит проблемы
до себя (DNS, CDN). Приложение даёт детализацию по эндпоинтам, но не видит запросы,
которые до него не дошли.

</details>

**A6.** Какие запросы исключают из валидных? Когда 4xx — всё-таки ошибка сервиса?

<details><summary>Ответ</summary>

Исключают health checks, мониторинг, нагрузочные тесты. 4xx обычно не считают
ошибкой сервиса, но 429 от собственного лимитера из-за нехватки мощности и массовые

</details>

**A7.** Как выбрать число SLO для уже работающего сервиса?

<details><summary>Ответ</summary>

Взять исторический SLI за 4 недели, поставить цель чуть ниже, сверить с потребностями
пользователей и надёжностью зависимостей, согласовать с продуктом, пересматривать раз
в квартал.

</details>

**A8.** Чем rolling-окно отличается от календарного? Почему часто берут 28 дней?

<details><summary>Ответ</summary>

Rolling — всегда «последние N дней», без сброса; календарное — с 1-го числа, бюджет
обнуляется. 28 дней = 4 полные недели: одинаковое число выходных в каждом окне.

</details>

**A9.** ⭐ Посчитай бюджет в минутах для 99,9% и 99,95% за 30 дней.

<details><summary>Ответ</summary>

30 дней = 43 200 минут. 99,9% → 43,2 мин (43 мин 12 с); 99,95% → 21,6 мин (21 мин 36 с).

</details>

**A10.** Чем бюджет по запросам честнее бюджета по времени?

<details><summary>Ответ</summary>

Он учитывает, сколько пользователей пострадало: 10 минут простоя ночью и в пик —
разное число неудачных запросов.

</details>

**A11.** Что такое burn rate? Как по нему посчитать время до исчерпания бюджета?

<details><summary>Ответ</summary>

Burn rate = доля ошибок / (1 − SLO) — во сколько раз быстрее «нормы» тратится бюджет.
Время до исчерпания = окно / burn rate.

</details>

**A12.** ⭐ Откуда берётся число 14,4? Почему фраза «при 14,4 бюджет сгорит за 2 часа» неверна?

<details><summary>Ответ</summary>

Порог «2% бюджета за 1 час» при окне 720 часов: 0,02 × 720 / 1 = 14,4. При таком
burn rate весь бюджет сгорит за 720 / 14,4 = 50 часов, а не за 2.

</details>

**A13.** Зачем в алерте два окна — длинное и короткое? Что такое reset time?

<details><summary>Ответ</summary>

Длинное окно гарантирует, что сгорела значимая доля бюджета (мало ложных).
Короткое — что проблема идёт прямо сейчас; благодаря ему алерт гаснет через минуты после
починки (reset time), а не через час.

</details>

**A14.** Почему простой алерт «доля ошибок > 0,1%» с `for: 1h` опасен?

<details><summary>Ответ</summary>

Полный простой длиной 59 минут не вызовет алерта, а при 99,9% бюджет на месяц —

</details>

**A15.** Почему долю ошибок за 6 часов нельзя считать как `avg_over_time` от 5-минутной доли?

<details><summary>Ответ</summary>

Среднее от долей даёт каждому 5-минутному интервалу одинаковый вес, независимо от
трафика: тихий ночной интервал с одной ошибкой из 10 запросов весит как пиковый. Правильно —
отношение `rate` ошибок к `rate` всех за всё окно.

</details>

**A16.** Что генерирует Sloth? Чем от него отличается Pyrra?

<details><summary>Ответ</summary>

Sloth из короткой спецификации генерирует recording rules для всех окон
(5m … 3d, 30d), служебные метрики бюджета и два multi-window multi-burn-rate алерта
(page/ticket). Pyrra делает похожее, но как оператор с CRD и собственным веб-интерфейсом.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  # SLI латентности за 30 дней
```text
<details><summary>Ответ</summary>

⚠️ Перцентиль за 30 дней — не SLI: не даёт долю хороших запросов, не считает бюджет,
дорог по вычислению. Нужна доля `bucket{le="0.3"} / count`.

</details>

```text:no-line-numbers
     histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[30d]))) < 0.3
```text
```text:no-line-numbers
B2.  # SLO: «среднее время ответа < 200 мс»
```text
<details><summary>Ответ</summary>

⚠️ Среднее прячет хвост; SLO по среднему не отражает опыт пользователей.

</details>

```text:no-line-numbers
     rate(http_request_duration_seconds_sum[5m]) / rate(http_request_duration_seconds_count[5m]) < 0.2
```text
```text:no-line-numbers
B3.  # recording rule для 6-часового окна
```text
<details><summary>Ответ</summary>

⚠️ Среднее от долей искажает результат при неравномерном трафике — считать по сырым
счётчикам за 6 часов.

</details>

```text:no-line-numbers
     - record: job:slo_errors_per_request:ratio_rate6h
```text
```text:no-line-numbers
       expr: avg_over_time(job:slo_errors_per_request:ratio_rate5m[6h])
```text
```text:no-line-numbers
B4.  - alert: HighErrors
```text
<details><summary>Ответ</summary>

⚠️ Порог = весь бюджет на коротком окне: страница на любой всплеск, съевший доли
процента бюджета. Нужен multi-window multi-burn-rate.

</details>

```text:no-line-numbers
       expr: job:slo_errors_per_request:ratio_rate5m > 0.001
```text
```text:no-line-numbers
       for: 5m
```text
```text:no-line-numbers
       labels: { severity: critical }
```text
```text:no-line-numbers
B5.  - alert: BudgetBurn
```text
<details><summary>Ответ</summary>

⚠️ Без короткого окна алерт будет гореть ещё почти час после починки.
И нет второй пары (6h/30m) для медленных сбоев.

</details>

```text:no-line-numbers
       expr: job:slo_errors_per_request:ratio_rate1h > (14.4 * 0.001)
```text
```text:no-line-numbers
B6.  # SLI доступности
```text
<details><summary>Ответ</summary>

⚠️ 201, 204, 3xx и все 4xx считаются «плохими». Правильно: хорошие = `status!~"5.."`
(или явно определённый набор).

</details>

```text:no-line-numbers
     sum(rate(http_requests_total{status="200"}[5m])) / sum(rate(http_requests_total[5m]))
```text
```text:no-line-numbers
B7.  # SLO: «99% запросов быстрее 300 мс»
```text
<details><summary>Ответ</summary>

⚠️ Корзина не совпадает с порогом: считается «быстрее 250 мс» — SLI занижен.
Добавить корзину `0.3` в приложение.

</details>

```text:no-line-numbers
     sum(rate(http_request_duration_seconds_bucket{le="0.25"}[5m]))
```text
```text:no-line-numbers
       / sum(rate(http_request_duration_seconds_count[5m]))
```text
```text:no-line-numbers
B8.  # Prometheus: --storage.tsdb.retention.time=15d ; SLO: rolling 30 дней
```text
<details><summary>Ответ</summary>

⚠️ За 30 дней данных нет — SLI и остаток бюджета считаются по 15 дням. Увеличить
retention или использовать долгое хранилище.

</details>

```text:no-line-numbers
B9.  # SLO 99,99% у сервиса, который синхронно вызывает два внешних API с SLA 99,9%
```text
<details><summary>Ответ</summary>

⚠️ Две синхронные зависимости по 99,9% дают потолок ~99,8%. SLO 99,99% недостижим
без кэша, очередей или резервных провайдеров.

</details>

```text:no-line-numbers
B10.  # SLO 99,9%
```text
<details><summary>Ответ</summary>

⚠️ Бюджет взят от 99% (0,01), а не от 99,9% (0,001): алерт в 10 раз менее чувствителен.

</details>

```text:no-line-numbers
     job:slo_errors_per_request:ratio_rate1h > (14.4 * 0.01)
```text
```text:no-line-numbers
B11.  # recording rule без группировки, алерт с фильтром по job
```text
<details><summary>Ответ</summary>

⚠️ `sum` без `by (job)` теряет лейбл `job`: фильтр `{job="shop-api"}` ничего не найдёт,
алерт никогда не сработает. Плюс суммируются все сервисы сразу.

</details>

```text:no-line-numbers
     - record: job:slo_errors_per_request:ratio_rate1h
```text
```text:no-line-numbers
       expr: sum(rate(http_requests_total{status=~"5.."}[1h])) / sum(rate(http_requests_total[1h]))
```text
```text:no-line-numbers
     # alert: job:slo_errors_per_request:ratio_rate1h{job="shop-api"} > 0.0144
```text
```text:no-line-numbers
B12.  # time-based SLI: минута «плохая», если в ней упал хотя бы один запрос
```text
<details><summary>Ответ</summary>

⚠️ При большом трафике почти каждая минута станет «плохой» из-за единичных ошибок.
Time-based SLI задают через порог доли: «минута хорошая, если ошибок < 1%».

</details>


---

### Блок C. Практика


### C1. 🔑 SLI для shop-api
Опиши два SLI для сценария «оформить заказ» (`/checkout`): доступность и латентность.
Для каждого — спецификация («что считаем хорошим»), реализация (метрика и PromQL),
что исключаешь из валидных и почему.

### C2. 🔑 Бюджет руками
**1.** Без калькулятора посчитай бюджет для 99%, 99,5%, 99,9% за 28 и за 30 дней. Сверь с таблицей.

<details><summary>Ответ</summary>

Доступность: хорошие — не-5xx ответы `/checkout`, валидные — все ответы `/checkout`,
без health checks и нагрузочных тестов. Латентность: хорошие — ответы быстрее 300 мс
(корзина `le="0.3"`), валидные — все ответы `/checkout`.

</details>

**2.** Сервис обрабатывает 3 млн запросов в месяц. Сколько «плохих» запросов разрешено
   при каждом из трёх SLO?

<details><summary>Ответ</summary>

1) См. таблицу конспекта: 99% — 6 ч 43 мин 12 с / 7 ч 12 мин; 99,5% — 3 ч 21 мин 36 с /

</details>

**3.** 5% ошибок держались 90 минут. Какую долю 30-дневного бюджета при 99,9% это съело?

<details><summary>Ответ</summary>

) 0,05 × 90 = 4,5 минуты полного простоя → 4,5 / 43,2 ≈ 10,4% бюджета.

</details>

### C3. 🔑 Recording rules на стенде
**1.** Положи `rules/slo-shop-api.yml` из конспекта (пока только группу recordings).

<details><summary>Ответ</summary>

Доступность: хорошие — не-5xx ответы `/checkout`, валидные — все ответы `/checkout`,
без health checks и нагрузочных тестов. Латентность: хорошие — ответы быстрее 300 мс
(корзина `le="0.3"`), валидные — все ответы `/checkout`.

</details>

**2.** `promtool check rules`, затем `curl -X POST localhost:9090/-/reload`.

<details><summary>Ответ</summary>

1) См. таблицу конспекта: 99% — 6 ч 43 мин 12 с / 7 ч 12 мин; 99,5% — 3 ч 21 мин 36 с /

</details>

**3.** На `/rules` убедись, что все 7 правил считаются без ошибок; построй
   `job:slo_errors_per_request:ratio_rate5m` на графике.

<details><summary>Ответ</summary>

) 0,05 × 90 = 4,5 минуты полного простоя → 4,5 / 43,2 ≈ 10,4% бюджета.

</details>

### C4. Burn-rate алерты и unit-тесты
**1.** Добавь группу алертов из конспекта.

<details><summary>Ответ</summary>

Доступность: хорошие — не-5xx ответы `/checkout`, валидные — все ответы `/checkout`,
без health checks и нагрузочных тестов. Латентность: хорошие — ответы быстрее 300 мс
(корзина `le="0.3"`), валидные — все ответы `/checkout`.

</details>

**2.** Напиши `tests/slo-shop-api_test.yml` с двумя тестами: 2% ошибок → через 70 минут
   `ShopApiErrorBudgetBurnFast`; 0,05% ошибок → тишина.

<details><summary>Ответ</summary>

1) См. таблицу конспекта: 99% — 6 ч 43 мин 12 с / 7 ч 12 мин; 99,5% — 3 ч 21 мин 36 с /

</details>

**3.** Прогони `promtool test rules`. Специально сломай порог и убедись, что тест падает.

<details><summary>Ответ</summary>

) 0,05 × 90 = 4,5 минуты полного простоя → 4,5 / 43,2 ≈ 10,4% бюджета.

</details>

### C5. Латентный SLO
Заведи SLO «99% запросов /checkout быстрее 300 мс»: recording rules
`job:slo_slow_requests:ratio_rate*` и алерт с порогами от бюджета 1%. Проверь через
`POST /chaos?delay_ms=400` на payments.

### C6. SLO-дашборд
Собери дашборд из конспекта: SLI за 30 дней, остаток бюджета, burn rate 1h/6h с линиями
порогов, доля ошибок против цели, список алертов. Экспортируй JSON в git.

### C7. 🔑 Спровоцировать и измерить
**1.** Запусти фоновый трафик, затем `curl -X POST "localhost:8081/chaos?error_rate=0.3"`.

<details><summary>Ответ</summary>

Доступность: хорошие — не-5xx ответы `/checkout`, валидные — все ответы `/checkout`,
без health checks и нагрузочных тестов. Латентность: хорошие — ответы быстрее 300 мс
(корзина `le="0.3"`), валидные — все ответы `/checkout`.

</details>

**2.** Засеки, через сколько `ShopApiErrorBudgetBurnFast` станет pending/firing (`/alerts`).

<details><summary>Ответ</summary>

1) См. таблицу конспекта: 99% — 6 ч 43 мин 12 с / 7 ч 12 мин; 99,5% — 3 ч 21 мин 36 с /

</details>

**3.** Верни `error_rate=0` и засеки, через сколько алерт погаснет. Сравни с теорией.

<details><summary>Ответ</summary>

) 0,05 × 90 = 4,5 минуты полного простоя → 4,5 / 43,2 ≈ 10,4% бюджета.

</details>

### C8. Sloth против ручных правил
Сгенерируй правила Sloth для того же SLO. Сравни окна, пороги и имена метрик с ручными.
Что Sloth добавил сверх ручного варианта?

### C9. Сколько съел эксперимент
Посчитай по данным Prometheus, какую долю бюджета съел эксперимент из C7. Почему
на стенде (где трафик есть всего пару часов) это число сильно отличается от «настоящего»?

---

### Блок D. Инциденты


**D1.** Ночью пришла страница `ShopApiErrorBudgetBurnFast` и через 3 минуты сама погасла.
Это ложное срабатывание? Что проверить?

<details><summary>Ответ</summary>

Не обязательно ложное: за час сгорело ≥ 2% бюджета — например, минута почти
полного отказа во время деплоя. Проверить аннотации деплоев, ошибки в логах и трейсах
за эти минуты, сколько бюджета съедено. Если повторяется на каждом релизе — чинить
раскатку (readiness, graceful shutdown, канарейки).

</details>

**D2.** Пользователи массово жалуются на ошибки оплаты, а SLO-алерт молчит. Назови
пять возможных причин.

<details><summary>Ответ</summary>

SLI мерится в приложении, а ошибки — до него (Ingress 502/504, DNS); ошибка
возвращается со статусом 200 или 4xx; фильтр `handler` не включает эндпоинт оплаты;
после релиза поменялись имена лейблов и правило возвращает пустоту; правило не
вычисляется (ошибка на `/rules`); таргет пропал, а алерта на `absent()` нет.

</details>

**D3.** Панель «SLI за 30 дней» показывает «No data», хотя сервис работает.

<details><summary>Ответ</summary>

Рядов с 5xx ещё не было — доля ошибок пустая; recording rules не загружены;
несовпадение `job`. Лечится инициализацией счётчика ошибок нулём в приложении
и проверкой правил на `/rules`.

</details>

**D4.** Внутренний сервис получает 3 запроса в минуту; каждую ночь страница из-за одной ошибки.

<details><summary>Ответ</summary>

При малом трафике burn-rate алерты шумят. Варианты: синтетический трафик,
объединить несколько сервисов в один SLO, добавить условие минимального числа запросов
(`and sum by (job) (increase(http_requests_total{job="x"}[1h])) > 100`), оставить только
тикет-алерты, перейти на time-based SLI.

</details>

**D5.** Бюджет ушёл в минус из-за падения облачного провайдера. Замораживать фичи?

<details><summary>Ответ</summary>

Зависит от policy, поэтому её пишут заранее. Частая практика: сбой зависимости
учитывается в бюджете (пользователю всё равно), но вместо заморозки фич — задачи
на резервирование: мульти-AZ, fallback, второй провайдер.

</details>

**D6.** Ticket-алерт `...BurnSlow` горит неделю, никто не реагирует.

<details><summary>Ответ</summary>

Тикет-алерт без процесса бесполезен: автоматически заводить тикет с владельцем,
разбирать на еженедельном обзоре надёжности. Если сигнал никогда не приводит к действиям —
пересмотреть SLO или пороги.

</details>

**D7.** После обновления до Prometheus 3 латентный SLI с порогом 1 с стал возвращать пустоту.

<details><summary>Ответ</summary>

В Prometheus 3 `le="1"` нормализуется в `le="1.0"`. Исправить селекторы
(`le="1.0"`) во всех правилах и дашбордах, заодно проверить `quantile` у summary.

</details>

**D8.** Год подряд SLI = 99,99% при SLO 99,9%. Хорошо это или плохо?

<details><summary>Ответ</summary>

Бюджет не используется: либо SLO занижен и потребители уже привыкли к 99,99%
(и сломаются, если станет 99,9%), либо команда могла катить быстрее и рискованнее.
В книге Google SRE есть история про сервис Chubby: ему устраивали плановые простои,
чтобы зависимые сервисы не рассчитывали на надёжность выше SLO.

</details>

**D9.** Recording rules с окнами 1d и 3d заметно нагружают Prometheus.

<details><summary>Ответ</summary>

Вычислять тяжёлые группы реже (`interval: 1m`–`5m`), считать длинные окна из коротких:
`sum_over_time(job:slo_errors:rate5m[3d]) / sum_over_time(job:slo_requests:rate5m[3d])`
(сумма rate, а не среднее от долей), убрать лишние лейблы, долгие окна отдать
долговременному хранилищу (Thanos, Mimir, VictoriaMetrics).

</details>

---

### Блок E. Вопросы с собеседования


**1.** Чем SLI, SLO и SLA отличаются друг от друга?

<details><summary>Ответ</summary>

SLI — измеряемая доля хороших событий; SLO — внутренняя цель по SLI за окно; SLA —
   договор с клиентом с последствиями, мягче SLO.

</details>

**2.** Как выбрать SLI для сервиса?

<details><summary>Ответ</summary>

От пользовательских сценариев: что для пользователя «хорошо» — ответ без ошибки,
   быстрее порога, свежие данные. Мерить как можно ближе к пользователю, исключать
   служебный трафик.

</details>

**3.** Посчитай error budget для 99,9% за месяц.

<details><summary>Ответ</summary>

30 дней = 43 200 минут × 0,1% = 43,2 минуты; или 1 неудачный запрос из 1000.

</details>

**4.** Что такое burn rate?

<details><summary>Ответ</summary>

Отношение текущей доли ошибок к допустимой (1 − SLO): во сколько раз быстрее нормы
   тратится бюджет.

</details>

**5.** Объясни multi-window multi-burn-rate алерты.

<details><summary>Ответ</summary>

Алерт срабатывает, когда burn rate выше порога одновременно на длинном и коротком окне:

</details>

**6.** Почему плохо алертить просто на «доля ошибок > порога»?

<details><summary>Ответ</summary>

Либо шумно (всплески, съевшие доли процента бюджета), либо медленно (длинное окно,
   `for`); порог не связан с тем, сколько бюджета реально горит.

</details>

**7.** Что происходит, когда error budget исчерпан?

<details><summary>Ответ</summary>

Срабатывает error budget policy: заморозка фич и фокус на надёжности до восстановления,
   постмортем по крупным инцидентам.

</details>

**8.** Как задать SLO на латентность?

<details><summary>Ответ</summary>

Через долю запросов быстрее порога — корзину гистограммы, совпадающую с порогом;
   часто два порога (99% < 300 мс и 99,9% < 1 с).

</details>

**9.** Rolling-окно или календарное — что выбрать?

<details><summary>Ответ</summary>

Для инженерных решений и алертов — rolling (28/30 дней), для отчётов и SLA —
   календарное.

</details>

**10.** Какие инструменты для SLO знаешь?

<details><summary>Ответ</summary>

Prometheus recording rules руками, Sloth, Pyrra, спецификация OpenSLO; SLO-функции
    есть и в коммерческих системах наблюдаемости.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Отличаю SLI, SLO и SLA и объясняю, почему SLA мягче
- [ ] Выбираю SLI от пользовательского сценария и знаю, что исключать
- [ ] ⭐ Считаю бюджет в минутах и запросах: 99,9% за 30 дней = 43,2 мин
- [ ] Латентный SLI считаю через корзину `le`, а не через перцентиль
- [ ] ⭐ Объясняю burn rate и пороги 14,4 / 6 / 3 / 1 с окнами
- [ ] Recording rules на стенде считаются, `promtool check rules` проходит
- [ ] Unit-тесты алертов проходят, а сломанный порог их роняет
- [ ] SLO-дашборд собран и лежит в git
- [ ] Спровоцированный сбой поднимает алерт, время срабатывания и затухания замерено
- [ ] Могу прочитать и проверить правила, сгенерированные Sloth
