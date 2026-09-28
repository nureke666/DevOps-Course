---
title: "03. Типы метрик и PromQL"
description: "Counter, gauge, histogram, summary; rate/irate/increase, агрегация, перцентили, recording rules"
---

# 03. Типы метрик и PromQL

> Роадмап → Мониторинг → Prometheus: *«Типы метрик (`counter`, `gauge` и др.), основы `PromQL`»*.
>
> **После темы ты умеешь:** отличать counter от gauge, писать `rate()`, агрегировать по
> лейблам, считать перцентили из гистограмм и выражать алерты на PromQL.

---

## 🗺️ Четыре типа метрик

```text:no-line-numbers
COUNTER — только растёт (сбрасывается в 0 при рестарте)
 ▲                          примеры: http_requests_total, node_cpu_seconds_total
 │      ╱╲                  ⚠️ само значение бесполезно: смотрят СКОРОСТЬ роста → rate()
 │  ╱╲╱   ╲ (рестарт)
 │╱        ╲____╱
 └──────────────────► t

GAUGE — может расти и падать
 ▲   ╱╲    ╱╲              примеры: node_memory_MemAvailable_bytes, queue_size, temperature
 │ ╱   ╲╱╲╱  ╲             смотрят ТЕКУЩЕЕ значение, rate() к нему НЕ применяют
 └──────────────────► t

HISTOGRAM — распределение по «корзинам» (buckets)
 http_request_duration_seconds_bucket{le="0.1"}  240     ⇒ перцентили считаются
 http_request_duration_seconds_bucket{le="0.5"}  480        НА СТОРОНЕ СЕРВЕРА
 http_request_duration_seconds_bucket{le="+Inf"} 500        histogram_quantile()
 http_request_duration_seconds_sum   123.4                 ⇒ можно агрегировать
 http_request_duration_seconds_count 500                      по нескольким инстансам

SUMMARY — перцентили, посчитанные КЛИЕНТОМ
 http_request_duration_seconds{quantile="0.95"} 0.42
 ⚠️ нельзя агрегировать между инстансами (среднее от перцентилей — бессмыслица)
```

| Тип | Когда выбирают | Главное правило |
|-----|----------------|-----------------|
| Counter | Количество событий: запросы, ошибки, байты | Имя заканчивается на `_total`, используется с `rate()` |
| Gauge | Текущее состояние: память, соединения, длина очереди | Берут значение как есть |
| Histogram | Длительности и размеры, нужны перцентили | ⭐ Дефолтный выбор для latency |
| Summary | Перцентили без нагрузки на сервер | Не агрегируется между инстансами |

---

## 1. Селекторы

```text:no-line-numbers
http_requests_total                                  # все ряды метрики
http_requests_total{job="api"}                       # точное совпадение
http_requests_total{status!="200"}                   # не равно
http_requests_total{status=~"5.."}                   # regex (полное совпадение строки)
http_requests_total{status!~"2..|3.."}               # regex-исключение
{__name__=~"node_cpu.*", cpu="0"}                    # выбор по имени метрики

http_requests_total{job="api"}[5m]                   # ⭐ range vector: все точки за 5 минут
http_requests_total offset 1h                        # значение час назад
```

```text:no-line-numbers
INSTANT VECTOR                       RANGE VECTOR
одно значение на ряд «сейчас»        набор значений за интервал
http_requests_total                  http_requests_total[5m]
   ▼                                    ▼
можно рисовать графиком              нельзя рисовать напрямую —
                                     сначала функция: rate/increase/avg_over_time
```

---

## 2. Функции для counter: `rate`, `irate`, `increase`

```text:no-line-numbers
rate(http_requests_total[5m])          # ⭐ средняя скорость в секунду за 5 минут
irate(http_requests_total[5m])         # мгновенная (по двум последним точкам) — дёргается
increase(http_requests_total[1h])      # прирост за час (== rate × 3600)
```

| Функция | Когда |
|---------|-------|
| `rate()` | 90% случаев: графики и алерты, сглаживает |
| `irate()` | Быстро меняющиеся значения, короткие графики; для алертов **не** годится |
| `increase()` | «Сколько всего произошло за период» — удобно для человека |

⭐ Правила, которые спрашивают на собесе:
1. `rate()` применяют **только к counter** (он умеет корректно обрабатывать сброс при рестарте).
2. Окно `[5m]` должно содержать **минимум 4 точки**: при `scrape_interval=15s` минимум `[1m]`,
   на практике берут ×4 от интервала.
3. `sum(rate(...))`, а **не** `rate(sum(...))` — сначала rate, потом агрегация.

```text:no-line-numbers
# запросов в секунду по всему сервису
sum(rate(http_requests_total[5m]))

# доля ошибок (0..1)
sum(rate(http_requests_total{status=~"5.."}[5m]))
  / sum(rate(http_requests_total[5m]))

# по инстансам
sum by (instance) (rate(http_requests_total[5m]))
```

---

## 3. Агрегация

```text:no-line-numbers
sum(...)      min(...)   max(...)   avg(...)   count(...)
stddev(...)   quantile(0.95, ...)   topk(5, ...)   bottomk(3, ...)
count_values("version", build_info)
```
```text:no-line-numbers
sum by (job, status) (rate(http_requests_total[5m]))     # сгруппировать ПО этим лейблам
sum without (instance) (rate(http_requests_total[5m]))   # сгруппировать, УБРАВ эти лейблы
topk(5, sum by (instance) (rate(node_network_receive_bytes_total[5m])))
```

```text:no-line-numbers
by    — оставить только перечисленные лейблы
without — оставить все, кроме перечисленных   (удобнее, когда лейблов много)
```

---

## 4. Функции для gauge и времени

```text:no-line-numbers
avg_over_time(node_load1[1h])            # среднее за час
max_over_time(node_load1[24h])           # пик за сутки
min_over_time(...)  sum_over_time(...)  quantile_over_time(0.95, ...)

delta(node_filesystem_avail_bytes[1h])   # изменение gauge за час (может быть отрицательным)
deriv(node_filesystem_avail_bytes[1h])   # скорость изменения gauge в секунду
predict_linear(node_filesystem_avail_bytes[6h], 4*3600)   # ⭐ прогноз на 4 часа вперёд

changes(process_start_time_seconds[1h])  # сколько раз менялось (рестарты)
resets(http_requests_total[1h])          # сколько раз counter сбрасывался

time() - node_boot_time_seconds          # аптайм
absent(up{job="api"})                    # ⭐ метрики вообще нет (таргет исчез)
absent_over_time(up{job="api"}[10m])
```

---

## 5. Гистограммы и перцентили

```text:no-line-numbers
# 95-й перцентиль времени ответа
histogram_quantile(0.95,
  sum by (le) (rate(http_request_duration_seconds_bucket[5m])))

# по эндпоинтам
histogram_quantile(0.95,
  sum by (le, path) (rate(http_request_duration_seconds_bucket[5m])))

# среднее время ответа (sum/count)
rate(http_request_duration_seconds_sum[5m])
  / rate(http_request_duration_seconds_count[5m])

# доля запросов быстрее 300 мс (для SLO)
sum(rate(http_request_duration_seconds_bucket{le="0.3"}[5m]))
  / sum(rate(http_request_duration_seconds_count[5m]))
```

> ⚠️ В `histogram_quantile` обязательно должен остаться лейбл `le` — поэтому `sum by (le)`.
> И помни: точность перцентиля ограничена границами корзин, заданными в приложении.

Почему перцентиль, а не среднее:
```text:no-line-numbers
100 запросов: 99 по 50 мс, 1 по 10 с
среднее = 149 мс   ← «всё хорошо»
p99     = 10 с     ← реальность для части пользователей
```

---

## 6. Операторы и сопоставление рядов

```text:no-line-numbers
node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes * 100   # проценты
node_filesystem_avail_bytes < 1e9                                   # фильтр по значению
up == 0
rate(x[5m]) > 100 and rate(y[5m]) < 5                               # логические операторы

# сопоставление с разным набором лейблов
sum by (instance) (rate(http_requests_total[5m]))
  / on (instance) group_left node_cpu_count
```

| Оператор | Смысл |
|----------|-------|
| `+ - * / % ^` | Арифметика (по совпадающим лейблам) |
| `== != > < >= <=` | Сравнение: фильтрует ряды (или даёт 0/1 с `bool`) |
| `and or unless` | Пересечение / объединение / исключение рядов |
| `on(...) / ignoring(...)` | По каким лейблам сопоставлять ряды |
| `group_left / group_right` | Сопоставление «многие к одному» |

---

## 7. Recording rules — предрассчитанные метрики

```yaml
# rules/recording.yml
groups:
  - name: api_slo
    interval: 30s
    rules:
      - record: job:http_requests:rate5m
        expr: sum by (job) (rate(http_requests_total[5m]))

      - record: job:http_errors:ratio5m
        expr: |
          sum by (job) (rate(http_requests_total{status=~"5.."}[5m]))
            / sum by (job) (rate(http_requests_total[5m]))
```
Зачем: тяжёлые выражения считаются один раз, дашборды и алерты работают быстро.
Соглашение по именам: `уровень:метрика:операция` (`job:http_requests:rate5m`).

---

## 8. Готовые выражения на каждый день

```text:no-line-numbers
# --- хост ---
100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)   # CPU %
(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100           # RAM %
100 - (node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"}
        / node_filesystem_size_bytes * 100)                                       # диск %
rate(node_disk_io_time_seconds_total[5m])                                         # загрузка диска
node_load5 / count by (instance) (node_cpu_seconds_total{mode="idle"})            # load на ядро

# --- сервис ---
sum(rate(http_requests_total[5m]))                                                # RPS
sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))
up == 0
changes(process_start_time_seconds[1h]) > 3                                       # рестарты

# --- прогнозы и тренды ---
predict_linear(node_filesystem_avail_bytes{mountpoint="/"}[6h], 4*3600) < 0
delta(node_network_receive_bytes_total[1h])

# --- сравнение с прошлым ---
sum(rate(http_requests_total[5m]))
  / sum(rate(http_requests_total[5m] offset 1w))                                  # неделя к неделе
```

---

## 9. Грабли PromQL

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| `rate()` на gauge | Бессмысленный результат | Для gauge — `delta`, `deriv`, `*_over_time` |
| Значение counter напрямую | Растущая прямая, ничего не говорит | `rate()`/`increase()` |
| `rate(sum(...))` | Сумма ломает обработку сбросов | `sum(rate(...))` |
| Слишком маленькое окно `[15s]` | Мало точек → пусто или шум | Окно ≥ 4 × `scrape_interval` |
| Забыт `by (le)` в `histogram_quantile` | Ошибка/мусор | `sum by (le) (rate(..._bucket[5m]))` |
| Алерт на `irate` | Дёргается, ложные срабатывания | `rate()` + `for` |
| Среднее вместо перцентиля | Прячет хвост | `histogram_quantile(0.95/0.99, …)` |
| Нет проверки исчезновения метрики | Таргет пропал — алерт молчит | `absent()` / `up == 0` |
| Тяжёлое выражение в дашборде | Медленные графики, нагрузка | Recording rule |

---

## 💼 Как это в DevOps

- PromQL — рабочий язык на дежурстве: «покажи долю 5xx по сервисам за последний час»
  пишется за 20 секунд и отвечает быстрее, чем чтение логов.
- Алерты — это PromQL-выражения плюс `for`, `labels`, `annotations`. Умение писать
  выражения = умение делать нешумные алерты.
- Recording rules используют для SLO-метрик и тяжёлых дашбордов; имена по соглашению,
  файл в git.
- Типичный разбор инцидента: `rate` ошибок → `sum by (instance)` → сравнение с `offset 1d` →
  `histogram_quantile` по эндпоинтам → нашли виновника.
- На собесе почти всегда просят: «напиши запрос, который покажет процент ошибок»
  и «чем rate отличается от irate».

---

## 📌 Шпаргалка

| Хочу | PromQL |
|------|--------|
| Запросов в секунду | `sum(rate(http_requests_total[5m]))` |
| Доля ошибок | `sum(rate(...{status=~"5.."}[5m])) / sum(rate(...[5m]))` |
| Прирост за час | `increase(metric_total[1h])` |
| Текущее значение gauge | просто имя метрики |
| Среднее за период | `avg_over_time(metric[1h])` |
| Пик за сутки | `max_over_time(metric[24h])` |
| p95 времени ответа | `histogram_quantile(0.95, sum by (le) (rate(..._bucket[5m])))` |
| Среднее время ответа | `rate(..._sum[5m]) / rate(..._count[5m])` |
| Группировка по лейблу | `sum by (job) (...)` |
| Без лейбла | `sum without (instance) (...)` |
| Топ-5 | `topk(5, ...)` |
| CPU % | `100 - avg by (instance)(rate(node_cpu_seconds_total{mode="idle"}[5m]))*100` |
| RAM % | `(1 - node_memory_MemAvailable_bytes/node_memory_MemTotal_bytes)*100` |
| Диск закончится через N часов | `predict_linear(node_filesystem_avail_bytes[6h], N*3600) < 0` |
| Цель недоступна | `up == 0` |
| Метрика исчезла | `absent(up{job="api"})` |
| Сколько рестартов | `changes(process_start_time_seconds[1h])` |
| Сравнить с прошлой неделей | `... / ... offset 1w` |

---

## 🧠 Что запомнить

1. Counter только растёт — смотрят `rate()`; gauge смотрят как есть.
2. Histogram позволяет считать перцентили на сервере и агрегировать по инстансам;
   summary — нет.
3. ⭐ `sum(rate(x[5m]))`, а не `rate(sum(x)[5m])`.
4. Окно в `rate()` — минимум 4 интервала сбора (обычно `[5m]` при 15 с).
5. `irate` — только для графиков, в алертах используют `rate` + `for`.
6. В `histogram_quantile` обязателен `by (le)`.
7. Перцентили честнее среднего: среднее прячет «хвост» медленных запросов.
8. `predict_linear` даёт алерты «до того, как сломалось» (диск, память).
9. `absent()` и `up == 0` ловят исчезновение таргета — без них «тишина» выглядит как норма.
10. Тяжёлые выражения выносят в recording rules с именами вида `job:metric:op`.

---

## Задачи

> Стенд: Prometheus + node_exporter. Для гистограмм удобно добавить любое приложение
> с `/metrics` (например, сам Prometheus отдаёт `prometheus_http_request_duration_seconds_bucket`).

---

### Блок A. Теория

**A1.** Назови четыре типа метрик и по два примера каждого.

<details><summary>Ответ</summary>

Counter (`http_requests_total`, `node_cpu_seconds_total`), gauge
(`node_memory_MemAvailable_bytes`, `queue_size`), histogram
(`http_request_duration_seconds_bucket`), summary (`..._seconds{quantile="0.95"}`).

</details>

**A2.** Почему нельзя смотреть на «голое» значение counter?

<details><summary>Ответ</summary>

Это накопленная сумма с момента старта процесса: её абсолютная величина ничего
не говорит о текущем поведении. Смысл имеет скорость роста.

</details>

**A3.** Что происходит с counter при рестарте приложения и как это учитывает `rate()`?

<details><summary>Ответ</summary>

При рестарте counter сбрасывается в 0. `rate()` распознаёт сброс (значение
уменьшилось) и корректно учитывает его, не давая отрицательных значений.

</details>

**A4.** Чем histogram отличается от summary? Что выбрать для времени ответа и почему?

<details><summary>Ответ</summary>

Histogram считает корзины на стороне приложения, а перцентили вычисляются в
Prometheus — их можно агрегировать между инстансами. Summary считает перцентили в самом
приложении — агрегировать нельзя. Для времени ответа берут histogram.

</details>

**A5.** Что такое instant vector и range vector?

<details><summary>Ответ</summary>

Instant vector — по одному значению на ряд в конкретный момент.
Range vector — набор значений за интервал (`metric[5m]`), его нельзя нарисовать напрямую.

</details>

**A6.** ⭐ Чем `rate` отличается от `irate` и от `increase`? Что использовать в алертах?

<details><summary>Ответ</summary>

`rate` — усреднённая скорость за окно (сглаживает, используется в алертах);
`irate` — мгновенная по двум последним точкам (дёргается, только для графиков);
`increase` — суммарный прирост за период (то же, что `rate × длительность`).

</details>

**A7.** Почему окно `rate()` должно быть не меньше 4 интервалов сбора?

<details><summary>Ответ</summary>

Чтобы функция имела достаточно точек для расчёта и переживала пропуск одного
сбора; иначе результат пустой или шумный.

</details>

**A8.** Почему `sum(rate(x[5m]))` правильно, а `rate(sum(x)[5m])` — нет?

<details><summary>Ответ</summary>

`rate` должен применяться к каждому ряду отдельно, чтобы корректно обработать
сбросы counter при рестартах. Если сначала сложить ряды, сбросы «смешаются» и результат
будет неверным. Кроме того, `rate(sum(...)[5m])` синтаксически требует подзапроса.

</details>

**A9.** Чем `by` отличается от `without`?

<details><summary>Ответ</summary>

`by` оставляет только перечисленные лейблы, `without` — все, кроме перечисленных.

</details>

**A10.** Как посчитать 95-й перцентиль и почему обязателен `by (le)`?

<details><summary>Ответ</summary>

`histogram_quantile(0.95, sum by (le) (rate(..._bucket[5m])))`.
Лейбл `le` (граница корзины) — обязательный вход функции: без него она не сможет
восстановить распределение.

</details>

**A11.** Почему перцентиль информативнее среднего? Приведи пример с числами.

<details><summary>Ответ</summary>

Среднее прячет хвост: 99 запросов по 50 мс и один на 10 с дают среднее 149 мс,
а p99 = 10 с. Пользователи из хвоста видят именно 10 секунд.

</details>

**A12.** Что делают `predict_linear`, `changes`, `absent`, `offset`?

<details><summary>Ответ</summary>

`predict_linear` — линейный прогноз значения через N секунд;
`changes` — сколько раз менялось значение (рестарты); `absent` — 1, если рядов нет вовсе;
`offset` — сдвиг запроса в прошлое.

</details>

**A13.** Какие функции применимы к gauge, а какие — только к counter?

<details><summary>Ответ</summary>

К counter — `rate`, `irate`, `increase`, `resets`. К gauge — `delta`, `deriv`,
`predict_linear`, `*_over_time`, `changes`. Агрегации применимы к обоим.

</details>

**A14.** Что такое recording rule и когда его заводят?

<details><summary>Ответ</summary>

Правило, которое периодически вычисляет выражение и сохраняет результат как новую
метрику. Заводят для тяжёлых выражений, SLO-метрик и часто используемых дашбордов.

</details>

**A15.** Как построить запрос «сравнить нагрузку с этим же временем неделю назад»?

<details><summary>Ответ</summary>

`sum(rate(m[5m])) / sum(rate(m[5m] offset 1w))` — отношение текущей нагрузки
к нагрузке неделю назад.

</details>

---

### Блок B. «Что вернёт запрос / что тут не так»

```text:no-line-numbers
B1.  http_requests_total
B2.  rate(http_requests_total[5m])
B3.  rate(node_memory_MemAvailable_bytes[5m])
B4.  sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m]))
B5.  increase(http_requests_total[1h])
B6.  irate(http_requests_total[5m]) > 100
B7.  histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))
B8.  histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))
B9.  rate(http_requests_total[15s])          # scrape_interval = 15s
B10. avg(http_request_duration_seconds{quantile="0.95"})
B11. up == 0
B12. absent(up{job="api"})
B13. predict_linear(node_filesystem_avail_bytes{mountpoint="/"}[6h], 4*3600) < 0
B14. 100 - (avg by (instance)(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)
B15. topk(5, sum by (instance) (rate(node_network_receive_bytes_total[5m])))
B16. sum(rate(http_requests_total[5m])) / sum(rate(http_requests_total[5m] offset 1w))
```

<details><summary>Ответ</summary>

**B1.** Накопленные значения counter — растущая линия, практической пользы нет.
**B2.** Запросов в секунду за 5-минутное окно по каждому ряду.
**B3.** ⚠️ Ошибка: `rate` к gauge. Нужны `delta`/`deriv`/`avg_over_time`.
**B4.** Доля 5xx от всех запросов (0..1) — корректный и самый используемый запрос.
**B5.** Сколько запросов пришло за час.
**B6.** ⚠️ `irate` в алерте — будет дёргаться; нужен `rate` и `for`.
**B7.** ⚠️ Без `sum by (le)` результат по каждому ряду отдельно и обычно некорректен
при нескольких инстансах.
**B8.** Правильный расчёт p95.
**B9.** ⚠️ Окно равно интервалу сбора — точек не хватает, результат пустой.
**B10.** ⚠️ Усреднение перцентилей summary между инстансами — математически бессмысленно.
**B11.** Цели, которые недоступны.
**B12.** 1, если рядов `up{job="api"}` нет вообще (job исчез из конфига/SD).
**B13.** Диск закончится в ближайшие 4 часа по линейному тренду.
**B14.** Использование CPU в процентах по инстансам.
**B15.** Топ-5 инстансов по входящему трафику.
**B16.** Отношение текущей нагрузки к нагрузке неделю назад.

</details>

---

### Блок C. Практика

Выполняй все запросы в UI Prometheus (вкладка Graph), смотри и таблицу, и график.

#### C1. Типы метрик глазами
1. Найди в `/metrics` node_exporter'а по одному примеру counter и gauge.
2. Построй график «голого» counter и его `rate()` — сравни.
3. Найди метрику типа histogram (`*_bucket`) и посмотри её ряды.

#### C2. 🔑 CPU, память, диск
Напиши и проверь:
1. Использование CPU в процентах по инстансам.
2. Использование памяти в процентах.
3. Свободное место на `/` в процентах.
4. Load average на ядро.

<details><summary>Ответ</summary>

Эталонные ответы есть в шпаргалке конспекта — сверься с ними после того,
как напишешь сам.

</details>

#### C3. `rate` vs `irate` vs `increase`
На одном графике сравни три выражения по одной метрике. Опиши разницу словами.

<details><summary>Ответ</summary>

`irate` заметно более «рваный», `rate` сглажен, `increase` даёт крупные числа
(суммарный прирост).

</details>

#### C4. Агрегации
1. `sum by (mode) (rate(node_cpu_seconds_total[5m]))`
2. `sum without (cpu) (rate(node_cpu_seconds_total[5m]))`
3. `topk(3, ...)`, `count by (job) (up)`
Объясни каждый результат.

#### C5. Гистограммы
1. Посчитай p50, p90, p99 для `prometheus_http_request_duration_seconds`.
2. Посчитай среднее (`_sum / _count`) и сравни с p99.
3. Посчитай долю запросов быстрее 100 мс.

<details><summary>Ответ</summary>

p99 будет значительно выше среднего — это и есть аргумент в пользу перцентилей.

</details>

#### C6. Прогнозы
1. `predict_linear` по свободному месту на диске.
2. Искусственно займи место (`fallocate -l 2G /tmp/big`), посмотри, как меняется прогноз.
3. Освободи и проверь.

#### C7. Пропажа метрик
1. Останови экспортер, проверь `up == 0` и `absent(up{job="node"})`.
2. Полностью убери job из конфига и посмотри, что теперь показывает `up` и `absent`.
3. Сделай вывод: какой из двух вариантов ловит «job удалили из конфига»?

<details><summary>Ответ</summary>

`up == 0` работает, пока job есть в конфиге; если job удалили, рядов не остаётся
вовсе — ловит только `absent()`.

</details>

#### C8. Сравнение с прошлым
Построй отношение текущей нагрузки к нагрузке сутки назад (`offset 1d`)
и неделю назад (`offset 1w`).

#### C9. Recording rules
1. Заведи два recording rule: RPS по job и доля ошибок.
2. Проверь на `/rules`, что они загрузились и считаются.
3. Замерь разницу во времени ответа дашборда до и после.

<details><summary>Ответ</summary>

Панель на recording rule отрисовывается заметно быстрее, особенно на больших
интервалах.

</details>

#### C10. Свой набор запросов
Собери файл `promql_cheatsheet.md` с 15 запросами, которые нужны именно твоему проекту,
и короткими комментариями «что покажет и когда пригодится».

---

### Блок D. Инциденты

**D1.** График `rate()` пустой, хотя метрика есть. Три причины.

<details><summary>Ответ</summary>

Метрика не counter (сброшенный/некорректный тип), окно меньше 4 интервалов сбора,
данных в окне нет (таргет недавно появился или лежал), опечатка в лейблах.

</details>

**D2.** Алерт на `irate(...) > 100` срабатывает и гаснет каждые 30 секунд. Что поменять?

<details><summary>Ответ</summary>

Перейти на `rate()` с окном 5 минут и добавить `for: 5m` — алерт перестанет
реагировать на одиночные всплески.

</details>

**D3.** Среднее время ответа 200 мс, но пользователи жалуются. Как показать проблему цифрами?

<details><summary>Ответ</summary>

Показать перцентили (p95/p99) и долю запросов медленнее порога:
`histogram_quantile` и отношение `_bucket{le="0.3"}` к `_count`.

</details>

**D4.** `histogram_quantile` возвращает `NaN`. Что проверишь?

<details><summary>Ответ</summary>

Нет `by (le)`, нет данных в окне, метрика не histogram, все корзины пустые
(нет трафика), неправильное имя метрики.

</details>

**D5.** После рестарта сервиса на графике `rate` резкий скачок вниз. Нормально ли это?

<details><summary>Ответ</summary>

Да: после рестарта counter начинается с нуля, а `rate` считает скорость —
кратковременное проседание нормально. Скачков вверх при этом быть не должно.

</details>

**D6.** Дашборд с 20 панелями грузится 30 секунд. Что делать?

<details><summary>Ответ</summary>

Вынести тяжёлые выражения в recording rules, уменьшить интервал/шаг запроса,
ограничить период по умолчанию, сократить число панелей и рядов на панель.

</details>

**D7.** Алерт «диск заполнен» приходит, когда диск уже полон. Как настроить заранее?

<details><summary>Ответ</summary>

Алерт на процент свободного места с запасом (15-20%) плюс `predict_linear`
на 4-6 часов вперёд.

</details>

**D8.** Запрос `sum(rate(...))` даёт значение в разы больше ожидаемого. Что могло пойти не так?

<details><summary>Ответ</summary>

Просуммированы ряды, которые не следовало (например, по всем окружениям),
или в выражении потерян фильтр по job/env; либо метрика дублируется двумя экспортерами.

</details>

**D9.** Метрики сервиса пропали, но ни один алерт не сработал. Что добавить?

<details><summary>Ответ</summary>

Алерты на `up == 0` и `absent()` для ключевых job'ов, а также dead man's switch.

</details>

**D10.** Нужно посчитать доступность сервиса за месяц в процентах. Как?

<details><summary>Ответ</summary>

Через долю успешных запросов за период:
`sum(increase(http_requests_total{status!~"5.."}[30d])) / sum(increase(http_requests_total[30d]))`.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Какие типы метрик есть в Prometheus?

<details><summary>Ответ</summary>

Counter, gauge, histogram, summary.

</details>

**2.** Чем counter отличается от gauge?

<details><summary>Ответ</summary>

Counter только растёт и сбрасывается при рестарте; gauge меняется в обе стороны.

</details>

**3.** Что такое `rate` и чем он отличается от `irate`?

<details><summary>Ответ</summary>

`rate` — средняя скорость роста counter за окно; `irate` — мгновенная по двум последним
точкам, годится только для графиков.

</details>

**4.** Как посчитать процент ошибок?

<details><summary>Ответ</summary>

`sum(rate(requests_total{status=~"5.."}[5m])) / sum(rate(requests_total[5m]))`.

</details>

**5.** Как посчитать 95-й перцентиль времени ответа?

<details><summary>Ответ</summary>

`histogram_quantile(0.95, sum by (le) (rate(duration_seconds_bucket[5m])))`.

</details>

**6.** Чем histogram отличается от summary?

<details><summary>Ответ</summary>

Histogram — корзины, перцентили считаются на сервере и агрегируются;
summary — перцентили считает клиент, агрегировать нельзя.

</details>

**7.** Что такое range vector?

<details><summary>Ответ</summary>

Набор значений метрики за интервал времени (`metric[5m]`), вход для `rate` и `*_over_time`.

</details>

**8.** Как узнать, что таргет пропал?

<details><summary>Ответ</summary>

`up == 0` (цель недоступна) и `absent()` (рядов нет вовсе).

</details>

**9.** Что такое recording rules и зачем они нужны?

<details><summary>Ответ</summary>

Предрассчитанные метрики для тяжёлых выражений; ускоряют дашборды и алерты,
именуются `уровень:метрика:операция`.

</details>

**10.** Как предсказать заполнение диска?

<details><summary>Ответ</summary>

`predict_linear(node_filesystem_avail_bytes[6h], N*3600) < 0`.

</details>

---

### 🎯 Чек-лист

- [ ] Отличаю counter, gauge, histogram, summary и знаю, что с каждым делать
- [ ] ⭐ Пишу `sum(rate(...))`, а не `rate(sum(...))`
- [ ] Знаю правило про окно ≥ 4 интервалов сбора
- [ ] Считаю долю ошибок и RPS без подсказок
- [ ] Считаю p95/p99 через `histogram_quantile` с `by (le)`
- [ ] Объясняю, почему перцентиль лучше среднего
- [ ] Пользуюсь `predict_linear` для алертов «заранее»
- [ ] Ловлю исчезновение метрик через `up == 0` и `absent()`
- [ ] Завёл recording rules для тяжёлых выражений
- [ ] Есть свой файл PromQL-шпаргалки под проект
