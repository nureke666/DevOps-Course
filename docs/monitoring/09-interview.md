---
title: "09. Вопросы с собеседований: мониторинг"
description: "8 главных вопросов о Prometheus и мониторинге, 49 дополнительных по темам блока, как отвечать на собесе"
---

# 09. Вопросы с собеседований: мониторинг

> Роадмап → 7. Остальное → Мониторинг: *«Стандарт в девопсерском наборе, знать обязательно.»*
> Мониторинг спрашивают почти на каждом собеседовании девопса — чаще, чем Ansible,
> и примерно так же часто, как Docker.

---

## 🎯 Часть 1. Восемь вопросов, которые задают почти всегда

### 1. Как работает Prometheus?

<details><summary>Ответ</summary>

> «Prometheus работает по pull-модели: сам ходит по HTTP на `/metrics` целей с заданным
> `scrape_interval` и складывает временные ряды в локальную TSDB. Цели берутся из
> service discovery — статически, из файлов (`file_sd`), из Kubernetes, из облаков.
> На тех же данных он вычисляет правила: recording rules сохраняют предрассчитанные
> метрики, alerting rules порождают алерты и отправляют их в Alertmanager.
> Визуализация — отдельно, в Grafana. Для долгого хранения ставят VictoriaMetrics
> или Thanos, потому что локальное хранилище и retention ограничены.»

</details>

### 2. Pull или push? В чём разница и что лучше?

<details><summary>Ответ</summary>

> «Prometheus — pull. Плюсы: сервер знает, что цель жива (метрика `up`), конфигурация
> целей в одном месте, любой экспортер можно проверить руками через `curl`.
> Минусы: нужен сетевой доступ от Prometheus к целям и проблема короткоживущих задач.
> Push (StatsD, remote write) удобнее за NAT и для задач, живущих секунды; для них
> в Prometheus есть Pushgateway, но это исключение, а не основной режим.
> "Лучше" зависит от задачи, а не абсолютно.»

</details>

### 3. Какие типы метрик и чем counter отличается от gauge?

<details><summary>Ответ</summary>

> «Counter только растёт и сбрасывается при рестарте — смотреть надо не значение,
> а скорость через `rate()`. Gauge меняется в обе стороны — смотрим текущее значение.
> Histogram считает корзины, перцентили вычисляются на сервере через `histogram_quantile`
> и агрегируются между инстансами. Summary считает перцентили в приложении — агрегировать
> их между инстансами нельзя. Для времени ответа берут histogram.»

</details>

### 4. Напиши запрос: процент ошибок / p95 latency

<details><summary>Ответ</summary>

```text:no-line-numbers
# доля 5xx
sum(rate(http_requests_total{status=~"5.."}[5m]))
  / sum(rate(http_requests_total[5m]))

# p95 времени ответа
histogram_quantile(0.95,
  sum by (le) (rate(http_request_duration_seconds_bucket[5m])))
```
⭐ Здесь проверяют три вещи: `rate` внутри `sum`, regex-матчер по статусу,
`by (le)` в гистограмме.

</details>

### 5. Что такое кардинальность и чем она опасна?

<details><summary>Ответ</summary>

> «Каждая уникальная комбинация имени метрики и лейблов — отдельный временной ряд.
> Если в лейбл попадает `user_id`, `request_id` или полный URL, число рядов растёт
> неограниченно: Prometheus упирается в память, замедляются запросы, растёт диск.
> Лечится правилами именования, `metric_relabel_configs` с `drop` и переносом
> детализации в логи и трейсы.»

</details>

### 6. Каким должен быть хороший алерт?

<details><summary>Ответ</summary>

> «Алертить нужно симптомы, которые чувствует пользователь: недоступность, долю ошибок,
> latency — а не "CPU 80%". У алерта обязательно есть `for`, чтобы не ловить всплески,
> честный severity (critical — только то, ради чего будят ночью), понятные аннотации
> и ссылка на рунбук. Пороги правильнее брать из SLO через burn rate, а не из головы.
> И обязательно нужны алерты на исчезновение метрик (`up == 0`, `absent()`) и watchdog
> на случай смерти самого мониторинга.»

</details>

### 7. Что такое SLI, SLO, error budget?

<details><summary>Ответ</summary>

> «SLI — измеряемый показатель качества, например доля успешных запросов.
> SLO — внутренняя цель по этому показателю, например 99,9% за 30 дней.
> SLA — внешнее обязательство с санкциями. Error budget — разрешённый объём неуспеха:
> для 99,9% это около 43 минут в месяц. Бюджет даёт объективное правило: пока он есть,
> катим релизы; сгорел — переключаемся на надёжность. И из него же выводятся пороги
> алертов через burn rate.»

</details>

### 8. Что бы ты мониторил у нового сервиса?

<details><summary>Ответ</summary>

Отвечать методом, а не списком:
> «RED для самого сервиса: rate, доля ошибок, latency по перцентилям.
> USE для его ресурсов: CPU, память, диск с inode, сеть — и saturation важнее utilization.
> Зависимости: база (соединения, лаг, место), кэш, очереди (лаг консьюмеров).
> Взгляд снаружи: blackbox-проверка и срок TLS-сертификата.
> Регламент: возраст бэкапа, рестарты, версия сборки.
> Плюс минимальный набор алертов и дашборд по схеме "обзор → золотые сигналы →
> ресурсы → зависимости".»

</details>

---

## 📚 Часть 2. 49 вопросов по темам

### Основы

**1. Метрики vs логи vs трейсы?**

<details><summary>Ответ</summary>

Что/когда, почему, где именно.

</details>

**2. Что такое observability?**

<details><summary>Ответ</summary>

Способность отвечать на новые вопросы о системе по её выходным данным.

</details>

**3. Из чего состоит метрика?**

<details><summary>Ответ</summary>

Имя + лейблы + значение + метка времени.

</details>

**4. Что такое временной ряд?**

<details><summary>Ответ</summary>

Уникальная комбинация имени и набора лейблов.

</details>

**5. Зачем метрика `up`?**

<details><summary>Ответ</summary>

Показывает результат самого сбора — основа алерта о недоступности.

</details>

**6. Что такое exporter?**

<details><summary>Ответ</summary>

Переводчик состояния системы в формат Prometheus.

</details>

### Prometheus

**7. Разделы `prometheus.yml`?**

<details><summary>Ответ</summary>

`global`, `scrape_configs`, `rule_files`, `alerting`, `remote_write`.

</details>

**8. Как добавить цели без правки конфига?**

<details><summary>Ответ</summary>

`file_sd_configs` (файл обновляет Ansible), k8s SD, Consul.

</details>

**9. Что такое relabeling?**

<details><summary>Ответ</summary>

Преобразование лейблов целей (`relabel_configs`) и метрик (`metric_relabel_configs`).

</details>

**10. Как Prometheus хранит данные?**

<details><summary>Ответ</summary>

Локальная TSDB: WAL + блоки по 2 часа + компакция.

</details>

**11. Retention по умолчанию?**

<details><summary>Ответ</summary>

15 дней; меняется флагами.

</details>

**12. Как оценить объём диска?**

<details><summary>Ответ</summary>

Ряды × частота точек × срок × 1-2 байта.

</details>

**13. Как масштабировать?**

<details><summary>Ответ</summary>

Federation (устарело), `remote_write` в VictoriaMetrics/Thanos/Mimir, шардирование по job'ам.

</details>

**14. HA Prometheus?**

<details><summary>Ответ</summary>

Две одинаковые инсталляции + кластер Alertmanager.

</details>

**15. Как перечитать конфиг?**

<details><summary>Ответ</summary>

`POST /-/reload` при `--web.enable-lifecycle` или SIGHUP.

</details>

**16. Что делать, если метрик нет?**

<details><summary>Ответ</summary>

`/targets` → ошибка сбора → `curl` до экспортера → сеть → путь/порт → relabeling.

</details>

### PromQL

**17. `rate` vs `irate` vs `increase`?**

<details><summary>Ответ</summary>

Среднее за окно / мгновенное / суммарный прирост.

</details>

**18. Почему `sum(rate())`, а не `rate(sum())`?**

<details><summary>Ответ</summary>

Rate должен применяться к каждому ряду, чтобы корректно обработать сбросы counter.

</details>

**19. Каким должно быть окно rate?**

<details><summary>Ответ</summary>

Не меньше 4 интервалов сбора.

</details>

**20. Как посчитать перцентиль?**

<details><summary>Ответ</summary>

`histogram_quantile(0.95, sum by (le) (rate(..._bucket[5m])))`.

</details>

**21. Как посчитать среднее время ответа?**

<details><summary>Ответ</summary>

`rate(_sum[5m]) / rate(_count[5m])`.

</details>

**22. Как сравнить с прошлой неделей?**

<details><summary>Ответ</summary>

`offset 1w`.

</details>

**23. Как предсказать заполнение диска?**

<details><summary>Ответ</summary>

`predict_linear(...[6h], 4*3600) < 0`.

</details>

**24. Как найти пропавшую метрику?**

<details><summary>Ответ</summary>

`absent()` / `absent_over_time()`.

</details>

**25. Что такое recording rules?**

<details><summary>Ответ</summary>

Предрассчитанные метрики для тяжёлых выражений и SLI.

</details>

### Exporters

**26. Что даёт node_exporter?**

<details><summary>Ответ</summary>

CPU, память, диски и inode, сеть, load, systemd, uptime.

</details>

**27. Как отдать свою метрику из скрипта?**

<details><summary>Ответ</summary>

Textfile collector + атомарный `mv`.

</details>

**28. Чем мониторить контейнеры?**

<details><summary>Ответ</summary>

cAdvisor; в k8s — метрики kubelet.

</details>

**29. Зачем blackbox_exporter?**

<details><summary>Ответ</summary>

Внешние проверки HTTP/TCP/ICMP и срок TLS-сертификата.

</details>

**30. Как мониторить cron/CI-задачи?**

<details><summary>Ответ</summary>

Pushgateway или textfile + алерт по времени последнего успеха.

</details>

**31. Как приложение отдаёт метрики?**

<details><summary>Ответ</summary>

Клиентская библиотека и эндпоинт `/metrics`.

</details>

**32. Правила именования?**

<details><summary>Ответ</summary>

Базовые единицы, единицы в имени, `_total` у counter, ограниченные лейблы.

</details>

### Alertmanager

**33. Кто решает, что алерт сработал?**

<details><summary>Ответ</summary>

Prometheus; Alertmanager только доставляет.

</details>

**34. Что делает `for`?**

<details><summary>Ответ</summary>

Требует, чтобы условие держалось заданное время.

</details>

**35. Как не получить 50 уведомлений?**

<details><summary>Ответ</summary>

`group_by`, `group_wait`, inhibit-правила.

</details>

**36. Что такое inhibition?**

<details><summary>Ответ</summary>

Подавление алертов-следствий при наличии алерта-причины.

</details>

**37. Что такое silence?**

<details><summary>Ответ</summary>

Временное глушение по матчерам, со сроком, автором и комментарием.

</details>

**38. Как маршрутизировать по командам?**

<details><summary>Ответ</summary>

Лейблы (`team`, `severity`) + дерево `route`.

</details>

**39. Как узнать, что мониторинг умер?**

<details><summary>Ответ</summary>

Watchdog-алерт + внешняя система проверки.

</details>

**40. Как бороться с alert fatigue?**

<details><summary>Ответ</summary>

Аудит правил, честная severity, группировка, подавление, рунбуки, удаление бесполезного.

</details>

### Grafana

**41. Хранит ли Grafana метрики?**

<details><summary>Ответ</summary>

Нет, только дашборды и настройки.

</details>

**42. Зачем переменные?**

<details><summary>Ответ</summary>

Один дашборд вместо десятков; `label_values`, multi-value с `=~`.

</details>

**43. Как дашборды попадают в git?**

<details><summary>Ответ</summary>

Экспорт JSON + provisioning, `allowUiUpdates: false`.

</details>

**44. Что такое `$__rate_interval`?**

<details><summary>Ответ</summary>

Автоматическое окно rate под масштаб графика.

</details>

**45. Как связать деплой и графики?**

<details><summary>Ответ</summary>

Аннотации из CI/CD через API.

</details>

### Zabbix, долгое хранение, Operator

**46. Zabbix или Prometheus?**

<details><summary>Ответ</summary>

Железо, сеть по SNMP, VM и эскалации из коробки — Zabbix; Kubernetes и метрики
приложений — Prometheus; в гибриде оба под общей Grafana (см. [10. Zabbix](/monitoring/10-zabbix)).

</details>

**47. Passive vs active проверки в Zabbix?**

<details><summary>Ответ</summary>

Passive — сервер спрашивает агента на 10050; active — агент сам шлёт на 10051,
работает через NAT и лучше масштабируется; `Hostname` агента должен совпадать
с именем хоста.

</details>

**48. Как хранить метрики год и не получить двойные данные от HA-пары?**

<details><summary>Ответ</summary>

Prometheus — оперативка, `remote_write` в VictoriaMetrics/Thanos/Mimir,
`external_labels` обязательны; дедупликация под модель хранилища: Thanos —
по лейблу реплики на чтении, VM — одинаковые ряды + `-dedup.minScrapeInterval`
(см. [11. Долгое хранение и Kubernetes-оператор](/monitoring/11-long-term-and-operator)).

</details>

**49. ServiceMonitor создан, таргета нет?**

<details><summary>Ответ</summary>

Проверить лейбл `release` под `serviceMonitorSelector`, лейблы **Service**, имя порта,
namespace, Ready-эндпоинты, `/service-discovery` и логи оператора.

</details>

---

## 🧠 Как отвечать: практические приёмы

1. **Показывай метод, а не список.** «Что мониторить?» → RED/USE/4 сигнала.
   Так видно, что ты справишься с незнакомой системой.
2. **Пиши PromQL уверенно.** Два запроса (доля ошибок и перцентиль) стоит довести
   до автоматизма — их просят чаще всего.
3. **Называй свои цифры.** «У меня на стенде 40 тысяч рядов, retention 15 дней,
   это ~6 ГБ» — сразу видно, что руками делал.
4. **Про алерты говори через боль.** Расскажи, как убирал шум и что дал рунбук:
   это опыт, а не теория.
5. **Не бойся сказать «в проде не эксплуатировал».** Достаточно честно отделить
   «поднимал на стенде» от «дежурил с этим».
6. **Вопросы с подвохом** («давай алерт на каждую метрику», «CPU 90% — критично?»,
   «зачем `for`?») — это проверка на понимание. Возражай аргументированно.

---

## ✅ Финальный самоконтроль

- [ ] Объясню архитектуру Prometheus и pull-модель без подсказок
- [ ] Напишу с ходу запрос доли ошибок и p95
- [ ] Объясню кардинальность и приведу пример катастрофы
- [ ] Расскажу про типы метрик и когда какой брать
- [ ] Сформулирую критерии хорошего алерта
- [ ] Объясню SLI/SLO/error budget и burn rate
- [ ] Расскажу, что мониторю у нового сервиса, методом RED/USE
- [ ] Объясню роль Alertmanager: группировка, inhibition, silence
- [ ] Расскажу, как дашборды и правила живут в git
- [ ] Назову, как понять, что умер сам мониторинг
