---
title: "06. Паттерны надёжности, нагрузка и chaos engineering"
description: "Блок → SRE и Observability → тема 06. Пробы и ресурсы в кубере — в"
---

# 06. Паттерны надёжности, нагрузка и chaos engineering

> Блок → SRE и Observability → тема 06. Пробы и ресурсы в кубере — в
> [../Kubernetes/09_probes_resources.md](/kubernetes/09-probes-resources), graceful shutdown пода —
> в [../Kubernetes/04_pod.md](/kubernetes/04-pod), rate limit в nginx — в [../Network/12_nginx.md](/network/12-nginx).
>
> **После темы ты умеешь:** выставлять таймауты и ретраи с exponential backoff и jitter,
> объяснить retry storm и idempotency, применить circuit breaker, bulkhead, rate limiting
> и graceful degradation, правильно гасить сервис, прикинуть ёмкость по закону Литтла,
> написать нагрузочный тест на k6 и провести простой chaos-эксперимент.

---

## 🗺️ Карта темы

```text
                    зависимость тормозит или падает
                                  │
   ┌──────────────┬───────────────┼────────────────┬─────────────────┐
   ▼              ▼               ▼                ▼                 ▼
 ТАЙМАУТ       РЕТРАЙ         CIRCUIT BREAKER    BULKHEAD        ДЕГРАДАЦИЯ
 не ждать      повторить      перестать звать    изолировать     отдать хоть что-то:
 вечно         (backoff +     больную зависи-    пулы, чтобы     кэш, заглушку,
               jitter,        мость, дать ей     одна беда не    read-only
               идемпотентно)  восстановиться     съела всё
                                  │
        на входе: RATE LIMITING / LOAD SHEDDING — не пускать больше, чем выдержим
        при выкатке: GRACEFUL SHUTDOWN + READINESS — не терять запросы
        проверка: НАГРУЗОЧНЫЕ ТЕСТЫ (k6) и CHAOS (game day) — до того, как сломает прод
```text
---

## 1. Таймауты

**Каждый сетевой вызов должен иметь таймаут.** Без него один зависший сервис держит
соединения, потоки и память вызывающего — и падает цепочкой.

```text
без таймаута:  payments завис → shop-api ждёт вечно → воркеры shop-api заняты →
               shop-api не отвечает никому → фронт ждёт shop-api → всё лежит
```text
| Правило | Пояснение |
|---------|-----------|
| Connect и read — отдельно | Connect короткий (0,5–1 с): «хост жив?»; read — по p99,9 зависимости + запас |
| Значение — из данных | Смотри p99/p99,9 латентности зависимости, а не «поставим 30 секунд» |
| Внешний таймаут ≥ суммы внутренних | Если шлюз ждёт 3 с, а сервис внутри ретраит 3 × 2 с — работа идёт впустую |
| Deadline propagation | Передавать оставшееся время вниз по цепочке (в gRPC — встроенные deadlines) |
| Дефолты библиотек опасны | Python `requests` по умолчанию ждёт **бесконечно**; у `httpx` — 5 секунд |

```python
import httpx
# 0,5 с на соединение, 2 с на остальное (чтение, запись, ожидание пула соединений)
client = httpx.AsyncClient(timeout=httpx.Timeout(2.0, connect=0.5))
```text
> ⚠️ Таймаут на стороне клиента не останавливает работу на стороне сервера. На стенде это
> видно под нагрузкой: shop-api сдаётся через 2 с и отдаёт 504, а payments продолжает
> обрабатывать очередь запросов, которые уже никто не ждёт, — полезная пропускная
> способность падает. Лечится deadline propagation и отбрасыванием «протухших» запросов.

---

## 2. Ретраи: exponential backoff + jitter

Ретраить можно **только**:
- временные ошибки: обрыв соединения, `502/503/504`, `429` (с учётом `Retry-After`);
- **идемпотентные** операции (GET, PUT, DELETE) или запросы с ключом идемпотентности.

Нельзя: `400/401/403/404/422` (повтор даст то же самое) и неидемпотентный `POST` без ключа
(двойное списание денег).

```text
exponential backoff:  0,1 → 0,2 → 0,4 → 0,8 с …  (растёт, но не больше cap)
+ jitter (full):      пауза = random(0, min(cap, base × 2^попытка))
без jitter:           1000 клиентов ретраят в одну и ту же миллисекунду → волны нагрузки
с jitter:             повторы размазаны во времени
```text
```python
import asyncio
import random
import httpx

RETRYABLE = {502, 503, 504}

async def get_with_retries(client: httpx.AsyncClient, url: str,
                           attempts: int = 3, base: float = 0.1, cap: float = 2.0):
    for attempt in range(attempts):
        try:
            r = await client.get(url)            # GET идемпотентен — повторять безопасно
            if r.status_code not in RETRYABLE:
                return r                         # успех или «неретраибельная» ошибка (4xx)
        except (httpx.ConnectError, httpx.ReadTimeout):
            if attempt == attempts - 1:
                raise
        if attempt < attempts - 1:
            await asyncio.sleep(random.uniform(0, min(cap, base * 2 ** attempt)))  # full jitter
    return r
```text
То же библиотекой `tenacity`:
```python
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

@retry(stop=stop_after_attempt(3),
       wait=wait_random_exponential(multiplier=0.1, max=2),
       retry=retry_if_exception_type(httpx.TransportError))
async def fetch_price(item_id: int): ...
```text
### Retry storm

```text
 клиент ─3 попытки─► API ─3 попытки─► payments ─3 попытки─► БД
 один запрос пользователя → до 3 × 3 × 3 = 27 запросов в базу
 база притормозила → все слои ретраят → нагрузка ×27 → база ложится окончательно
```text
| Защита | Как |
|--------|-----|
| Ретраи на одном уровне | Обычно ближе к краю (клиент/шлюз) или только у вызова самой зависимости |
| Retry budget | Ретраев не больше ~10% от числа запросов; сверх — не ретраить |
| Backoff + jitter | Всегда |
| Circuit breaker | Перестать звать зависимость, которая явно больна |
| Уважать `Retry-After` и 429 | Сервер сам говорит, когда приходить |

---

## 3. Идемпотентность

**Идемпотентная операция** даёт тот же результат при повторе. Без неё ретраи, таймауты
и доставка «at-least-once» из очередей превращаются в дубли.

| HTTP-метод | Идемпотентен? |
|------------|---------------|
| GET, HEAD, OPTIONS | ✅ (и безопасен — ничего не меняет) |
| PUT, DELETE | ✅ (повтор оставляет то же состояние) |
| POST | ❌ — нужен ключ идемпотентности |
| PATCH | Зависит от реализации |

Ключ идемпотентности: клиент генерирует UUID на операцию и шлёт `Idempotency-Key`;
сервер запоминает результат по ключу и на повтор возвращает сохранённый ответ.
```sql
CREATE TABLE payments (
  idempotency_key text PRIMARY KEY,
  order_id        bigint  NOT NULL,
  amount          numeric NOT NULL,
  created_at      timestamptz DEFAULT now()
);

INSERT INTO payments (idempotency_key, order_id, amount)
VALUES ('4f1c2a7e-…', 42, 1990.00)
ON CONFLICT (idempotency_key) DO NOTHING
RETURNING *;          -- пусто ⇒ это повтор: вернуть уже сохранённый платёж
```text
Для очередей: консьюмер хранит ID обработанных сообщений (или делает операцию
идемпотентной по бизнес-ключу) — доставка «ровно один раз» на практике строится как
«хотя бы один раз + идемпотентный обработчик».

---

## 4. Circuit breaker

```text
            N ошибок подряд / доля ошибок > порога
   CLOSED ───────────────────────────────────────► OPEN
 (пропускаем)                                    (сразу отказ, зависимость отдыхает)
      ▲                                               │ прошло reset_timeout
      │ пробные запросы успешны                        ▼
      └─────────────────────────────────────────  HALF-OPEN
                  проба неудачна → снова OPEN     (пропускаем немного на пробу)
```text
Зачем: не тратить таймауты и потоки на заведомо больную зависимость, отвечать быстро
(fail fast или деградация) и дать зависимости восстановиться без добивающей нагрузки.

```python
import time

class CircuitBreaker:
    """Упрощённо: в half-open пропускает запросы до первого результата пробы."""
    def __init__(self, failure_threshold: int = 5, reset_timeout: float = 30.0):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failures = 0
        self.opened_at: float | None = None          # None = CLOSED

    def allow(self) -> bool:
        if self.opened_at is None:
            return True                               # CLOSED
        return time.monotonic() - self.opened_at >= self.reset_timeout  # HALF-OPEN или OPEN

    def record_success(self) -> None:
        self.failures, self.opened_at = 0, None      # → CLOSED

    def record_failure(self) -> None:
        self.failures += 1
        if self.opened_at is not None or self.failures >= self.failure_threshold:
            self.opened_at = time.monotonic()         # → OPEN (или снова OPEN после пробы)
```text
```python
breaker = CircuitBreaker()

async def pay_or_degrade():
    if not breaker.allow():
        return {"status": "queued"}                   # деградация: оплатим позже из очереди
    try:
        r = await client.get(f"{PAYMENTS_URL}/pay")
        r.raise_for_status()
    except httpx.HTTPError:
        breaker.record_failure()
        raise
    breaker.record_success()
    return r.json()
```text
В проде берут готовое: resilience4j (Java), Polly (.NET), pybreaker (Python), gobreaker (Go) —
или делают это на уровне сети через service mesh:
```yaml
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata: { name: payments }
spec:
  host: payments
  trafficPolicy:
    connectionPool:                 # bulkhead: не больше N соединений/ожидающих запросов
      tcp:  { maxConnections: 100 }
      http: { http1MaxPendingRequests: 50 }
    outlierDetection:               # выкидывать больные инстансы из балансировки
      consecutive5xxErrors: 5
      interval: 10s
      baseEjectionTime: 30s
      maxEjectionPercent: 50
```text
---

## 5. Bulkhead — переборки

Как отсеки на корабле: пробоина в одном не топит весь корабль.

```text
БЕЗ ИЗОЛЯЦИИ                              С ПЕРЕБОРКАМИ
общий пул из 100 воркеров                 payments: 20   search: 30   прочее: 50
payments завис → все 100 ждут его  →      payments завис → заняты 20 его слотов,
сервис лежит целиком                      поиск и каталог работают
```text
Где применяют: отдельные пулы соединений/потоков на каждую зависимость, семафоры,
отдельные инстансы или node pool'ы для критичного и фонового трафика, лимиты
`connectionPool` в mesh, разные очереди для разных типов задач.

```python
PAYMENTS_SLOTS = asyncio.Semaphore(20)       # не больше 20 одновременных вызовов payments

async def call_payments():
    if PAYMENTS_SLOTS.locked():               # все слоты заняты — не копим очередь
        raise HTTPException(status_code=503, detail="payments busy")
    async with PAYMENTS_SLOTS:
        return await client.get(f"{PAYMENTS_URL}/pay")
```text
---

## 6. Rate limiting и load shedding

| Алгоритм | Как работает | Особенность |
|----------|--------------|-------------|
| **Token bucket** | Ведро пополняется N токенов/с, запрос тратит токен | Разрешает всплески до размера ведра — самый популярный |
| Leaky bucket | Запросы «вытекают» с постоянной скоростью | Сглаживает, всплесков нет |
| Fixed window | Счётчик на окно (например, минуту) | Прост, но «двойной всплеск» на границе окон |
| Sliding window | Скользящее окно | Точнее, чуть дороже |

```nginx
http {
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;   # 10 запросов/с с одного IP
    server {
        location /api/ {
            limit_req zone=api burst=20 nodelay;   # всплеск до 20 без задержки
            limit_req_status 429;                  # вместо 503 по умолчанию
            proxy_pass http://backend;
        }
    }
}
```text
- **Rate limiting** — квоты на клиента («не больше 100 запросов/мин на API-ключ»):
  защита от злоупотреблений и «шумных соседей».
- **Load shedding** — когда сервис перегружен **в целом**, он сам отбрасывает часть
  запросов (сначала менее важные), чтобы остальные обслужить быстро. Лучше быстро
  отказать 10% запросов, чем медленно отвечать всем 100%.
- Отказ — `429 Too Many Requests` (или `503`) с заголовком `Retry-After`.

---

## 7. Graceful degradation

Лучше отдать урезанный ответ, чем ошибку:

| Отказало | Деградация |
|----------|-----------|
| Сервис рекомендаций | Показываем популярные товары из кэша |
| Платёжный провайдер | Принимаем заказ, оплату ставим в очередь |
| Поиск (Elasticsearch) | Простой поиск по названию в основной БД с лимитом |
| Запись в основную БД | Режим read-only: каталог работает, заказы — «попробуйте позже» |
| Тяжёлая новая фича под нагрузкой | Выключаем feature flag |

Деградацию проектируют заранее и **проверяют** (chaos, game day): fallback, который
ни разу не срабатывал, скорее всего не сработает и в аварию.

---

## 8. Graceful shutdown и health checks

```text
Kubernetes удаляет под (деплой, скейл-даун, эвикция):
 1. под → Terminating; параллельно его убирают из Endpoints (это занимает секунды!)
 2. preStop (например, sleep 5) — ждём, пока балансировщики перестанут слать трафик
 3. SIGTERM → приложение перестаёт принимать новые запросы, дорабатывает текущие,
    закрывает соединения с БД, коммитит офсеты очереди
 4. через terminationGracePeriodSeconds (по умолчанию 30 с) — SIGKILL
```text
```yaml
spec:
  terminationGracePeriodSeconds: 30
  containers:
    - name: shop-api
      lifecycle:
        preStop:
          exec: { command: ["sleep", "5"] }   # в свежих Kubernetes есть и встроенное `sleep`
```text
Без этого каждый деплой — пачка 502 и съеденный кусок error budget.
Uvicorn на SIGTERM сам перестаёт принимать соединения и ждёт текущие запросы
(верхний предел — `--timeout-graceful-shutdown`). Приложение должно быть PID 1 или
получать сигнал (exec-форма `CMD`), иначе SIGTERM не дойдёт.

**Health checks** (подробно — [../Kubernetes/09_probes_resources.md](/kubernetes/09-probes-resources)):

| Проба | Отвечает на вопрос | Грабля |
|-------|--------------------|--------|
| liveness | «Процесс жив, не завис?» → рестарт | Проверять в ней БД: база моргнула — все поды рестартуют разом |
| readiness | «Готов принимать трафик?» → убрать из балансировки | Жёсткая проверка общей зависимости: все поды «не готовы» → ноль эндпоинтов |
| startup | «Ещё стартую?» | Без неё медленный старт убивает liveness |

Правило: liveness — только собственное состояние процесса; readiness — готовность
обслуживать (прогрев, дренаж при остановке); здоровье зависимостей — в метрики и алерты.

---

## 9. Capacity planning

**Закон Литтла:** `L = λ × W` — среднее число запросов в системе = поток × время обработки.

```text
Стенд: пул payments = 10 «соединений», обработка ~75 мс в среднем
  ёмкость ≈ 10 / 0,075 ≈ 133 запроса/с
  при 100 RPS: в работе ≈ 100 × 0,075 = 7,5 соединения — запас есть
  при 150 RPS: нужно 11,25 соединения из 10 → очередь растёт без предела,
               латентность уходит в секунды, после 2 с — 504
Реальный прогон k6 на стенде: «колено» около 120 RPS — p95 скачком с 0,19 до 1,9 с,
затем почти все ошибки — 504. Близко к расчёту, но ниже: свои накладные расходы у Python.
```text
```text
latency
   │                                  ╱  ← «колено»: очередь растёт быстрее,
   │                                 ╱      чем обслуживается
   │                              __╱
   │ ___________________________╱
   └──────────────────────────────────────► нагрузка (RPS)
         рабочая зона        запас    насыщение
```text
Практика:
- Знать пиковую нагрузку (и сезонность: распродажи, конец месяца) и ёмкость каждого звена.
- Держать запас: N+1 (выдержать потерю одного инстанса/зоны), целевая утилизация в пик
  ~50–70% для CPU-bound сервисов.
- Узкое место — часто не CPU, а пулы соединений, лимиты БД, квоты облака, внешние API.
- Прогноз роста раз в квартал + нагрузочный тест перед крупными событиями.
- Автомасштабирование ([../Kubernetes/18_hpa_autoscaling.md](/kubernetes/18-hpa-autoscaling))
  не спасает, если узкое место — база или внешний лимит.

---

## 10. Нагрузочное тестирование с k6

| Тип | Цель | Профиль |
|-----|------|---------|
| Smoke | Скрипт вообще работает | 1–2 VU, минута |
| Load (average) | Держим обычную нагрузку в SLO? | Типичный трафик, 10–30 мин |
| Stress | Как ведём себя выше нормы? | Ступенчато выше пика |
| Spike | Переживём резкий всплеск? | Мгновенный скачок ×5–10 |
| Soak | Утечки, деградация со временем | Обычная нагрузка, часы |
| Breakpoint | Где предел? | Рост до отказа |

**Открытая и закрытая модель.** «50 виртуальных пользователей в цикле» (closed model) —
когда сервис тормозит, пользователи сами замедляются, и нагрузка падает: тест прячет
проблему (coordinated omission). Для API правильнее **arrival-rate** (open model):
задаём RPS, и k6 держит его, как бы ни тормозил сервис.

```javascript
// k6/load.js (целиком — в лабе 3): главное — сценарий и thresholds
export const options = {
  scenarios: {
    ramp: {
      executor: 'ramping-arrival-rate',   // открытая модель: задаём RPS, а не число юзеров
      startRate: 10, timeUnit: '1s', preAllocatedVUs: 50, maxVUs: 500,
      stages: [{ target: 50, duration: '2m' }, { target: 100, duration: '3m' },
               { target: 200, duration: '5m' }, { target: 0, duration: '1m' }],
    },
  },
  thresholds: {
    http_req_failed: ['rate&lt;0.01'],                 // ≤ 1% ошибок
    http_req_duration: ['p(95)<300', 'p(99)<1000'], // латентность в мс
  },
};

export default function () {
  const res = http.get(`${BASE_URL}/checkout`, { tags: { name: 'checkout' } });
  check(res, { 'status 200': (r) =&gt; r.status === 200 });
}
```text
```bash
docker compose run --rm k6 run /scripts/load.js                             # итог в консоли
docker compose run --rm k6 run -o experimental-prometheus-rw /scripts/load.js  # + метрики k6_* в Prometheus
```text
Как читать результат:
- **thresholds** — критерии «прошёл/не прошёл» (k6 завершится с ненулевым кодом → удобно в CI).
- `http_req_failed`, `http_req_duration` p95/p99 — сравнивай с SLO, а не «на глаз».
- `dropped_iterations` > 0 — генератору не хватило VU, чтобы держать заданный RPS:
  запросы висят слишком долго. Это сигнал насыщения сервиса (или мало `maxVUs`).
- Смотри одновременно на **сервер**: RED-дашборд, трейсы (где растёт время — `db.pool.acquire`?),
  ресурсы. Нагрузочный тест без наблюдаемости — просто генератор шума.

Правила: тестовая среда похожа на прод (данные, лимиты, версии); не бомбить сторонние API
и чужие сервисы; нагрузку на прод — только по согласованию и с кнопкой «стоп»; трафик
тестов исключают из SLI.

---

## 11. Chaos engineering и game day

Chaos engineering — **эксперименты** с контролируемыми отказами, чтобы проверить гипотезу
об устойчивости, а не «сломать что-нибудь и посмотреть».

```text
1. Steady state: как выглядит норма в метриках? (SLI: доля ошибок < 0,1%, p99 < 300 мс)
2. Гипотеза:     «если payments начнёт отвечать за 2 с, checkout деградирует до очереди,
                  SLI останется в норме, алерт придёт за 5 минут»
3. Эксперимент:  внести отказ, ограничив радиус поражения (staging, 1 инстанс, 5% трафика)
4. Наблюдение:   сравнить с гипотезой; условия досрочной остановки заданы заранее
5. Вывод:        баги, дыры в алертах и runbooks → задачи; повторять регулярно, автоматизировать
```text
| Что ломать | Как (стенд / Linux / Kubernetes) | Что проверяем |
|-----------|-----------------------------------|---------------|
| Процесс упал | `docker compose stop payments`, удалить под | Быстрый отказ, ретраи, readiness |
| Процесс завис | `docker compose pause payments` | Таймауты (зависание хуже падения!) |
| Задержка сети | `/chaos?delay_ms=500`, `tc qdisc add dev eth0 root netem delay 300ms 50ms` | Таймауты, circuit breaker, деградация |
| Ошибки зависимости | `/chaos?error_rate=0.3` | Ретраи, алерты, деградация |
| Кончился диск | Заполнить том | Алерты `predict_linear`, поведение БД |
| Потеря ноды / зоны | Drain ноды, выключить зону | N+1, PodDisruptionBudget, failover |
| DNS | Сломать резолвинг | Кэши, таймауты резолвера |

Инструменты: Chaos Mesh и LitmusChaos (Kubernetes), Toxiproxy (TCP-прокси с «токсинами»),
`tc netem` (Linux, нужны права `NET_ADMIN`), AWS Fault Injection Service; исторически —
Chaos Monkey в Netflix.

**Game day** — запланированные учения команды: сценарий отказа + проведение инцидента
по-настоящему (роли, канал, апдейты, runbook) + постмортем. Проверяет не только систему,
но и людей, алерты и документацию. Формат — в [07_practice_labs.md](/mlops/07-practice-labs), лаба 4.

---

## 12. Грабли

| Грабля | Последствие | Правильно |
|--------|-------------|-----------|
| Нет таймаута | Зависшая зависимость кладёт всех | Таймаут на каждый вызов, connect и read отдельно |
| Ретраи без jitter | Синхронные волны нагрузки | Full jitter |
| Ретраи на каждом уровне | Retry storm ×27 | Один уровень, retry budget |
| Ретрай неидемпотентного POST | Двойные списания | Ключ идемпотентности |
| Liveness проверяет БД | Массовые рестарты при моргании базы | Liveness — только сам процесс |
| Нет preStop/обработки SIGTERM | 502 на каждом деплое | preStop sleep + graceful shutdown |
| Общий пул на все зависимости | Одна медленная зависимость съедает всё | Bulkhead |
| Нагрузочный тест closed-моделью | Тест «зелёный», прод падает | Arrival-rate (open model) |
| Fallback ни разу не проверен | Не срабатывает в аварию | Chaos-эксперименты, game day |
| Chaos без steady state и стоп-условий | Реальный инцидент вместо эксперимента | Гипотеза, радиус, abort conditions |

---

## 💼 Как это в DevOps

- Часть паттернов живёт в коде (таймауты, ретраи, идемпотентность), часть — в инфраструктуре:
  таймауты и rate limit на Ingress/nginx, outlier detection и лимиты в service mesh,
  PodDisruptionBudget, preStop. Девопс настраивает вторую часть и ревьюит первую.
- Перед крупными событиями (распродажи, запуск) — нагрузочный тест k6 в CI или по расписанию
  с thresholds, привязанными к SLO; результат — отчёт о запасе ёмкости.
- Chaos начинают со staging и простых сценариев (убить под, добавить задержку), а game day
  проводят раз в квартал: он проверяет алерты, runbooks и готовность дежурных.
- Каждый постмортем с «зависимость тормозила — легли все» заканчивается задачами из этой темы:
  таймаут, breaker, bulkhead, деградация.
- На собесе спрашивают: «как правильно ретраить», «что такое circuit breaker», «чем liveness
  отличается от readiness», «как провести нагрузочное тестирование».

---

## 📌 Шпаргалка

| Паттерн | Суть одной строкой |
|---------|--------------------|
| Таймаут | Не ждать вечно; connect ~0,5–1 с, read по p99,9 + запас |
| Deadline propagation | Передавать оставшееся время вниз по цепочке |
| Ретрай | Только временные ошибки и идемпотентные операции, 2–3 попытки |
| Backoff + jitter | `sleep = random(0, min(cap, base × 2^attempt))` |
| Retry budget | Ретраев ≤ ~10% от запросов, ретраить на одном уровне |
| Идемпотентность | `Idempotency-Key` + уникальный ключ в БД, идемпотентные консьюмеры |
| Circuit breaker | CLOSED → OPEN (fail fast) → HALF-OPEN (проба) |
| Bulkhead | Отдельные пулы/семафоры/инстансы на зависимости и классы трафика |
| Rate limiting | Token bucket, `429` + `Retry-After`; nginx `limit_req` |
| Load shedding | При перегрузке отбрасывать менее важное, быстро отказывать |
| Деградация | Кэш, очередь, read-only, выключить фичу флагом |
| Graceful shutdown | preStop sleep → SIGTERM → дренаж → выход до grace period |
| Закон Литтла | `L = λ × W`: конкурентность = RPS × время обработки |
| k6 для API | `ramping-arrival-rate` + thresholds от SLO |
| Chaos | Steady state → гипотеза → эксперимент с малым радиусом → вывод |

---

## 🧠 Что запомнить

1. Таймаут на каждом сетевом вызове; внешний таймаут не короче суммы внутренних попыток.
2. Ретраят только временные ошибки и идемпотентные операции — с exponential backoff и jitter.
3. ⭐ Ретраи на всех уровнях дают retry storm: повторы — на одном уровне и в пределах бюджета.
4. Идемпотентность через ключ и уникальное ограничение в БД делает ретраи безопасными.
5. Circuit breaker даёт fail fast и отдых зависимости; bulkhead не даёт одной беде съесть всё.
6. Лучше быстро отказать части запросов (429/503 + Retry-After), чем медленно отвечать всем.
7. Graceful shutdown (preStop + SIGTERM + дренаж) убирает 502 при каждом деплое.
8. Liveness проверяет только сам процесс; зависимости — в метриках, не в пробах.
9. Закон Литтла и нагрузочный тест находят «колено» — ёмкость планируют с запасом N+1.
10. Chaos — это эксперимент с гипотезой и стоп-условиями; game day проверяет и систему, и людей.

➡️ Дальше: [07_practice_labs.md](/mlops/07-practice-labs) · задачи: 06_reliability_patterns_tasks.md


---

### Блок A. Теория


**A1.** Почему у каждого сетевого вызова должен быть таймаут? Опиши каскадный отказ.

<details><summary>Ответ</summary>

Без таймаута зависшая зависимость держит соединения и воркеры вызывающего; они
заканчиваются, вызывающий перестаёт отвечать всем, и отказ поднимается по цепочке вверх.

</details>

**A2.** Чем connect timeout отличается от read timeout? Как выбрать значения?

<details><summary>Ответ</summary>

Connect — время установки соединения (короткий, 0,5–1 с: хост жив или нет). Read —
ожидание ответа: по p99/p99,9 латентности зависимости плюс запас.

</details>

**A3.** Почему внешний таймаут должен быть не короче суммы внутренних попыток?
Что такое deadline propagation?

<details><summary>Ответ</summary>

Иначе внешний уровень сдаётся, а внутренние продолжают попытки впустую, тратя ресурсы.
Deadline propagation — передача оставшегося времени вниз, чтобы каждый уровень знал,
сколько ему осталось, и не начинал работу, которую уже никто не ждёт.

</details>

**A4.** Какие ошибки и операции можно ретраить, а какие нельзя?

<details><summary>Ответ</summary>

Можно: временные ошибки (обрыв соединения, 502/503/504, 429 с учётом `Retry-After`)
для идемпотентных операций. Нельзя: 400/401/403/404/422 и неидемпотентные операции без ключа.

</details>

**A5.** ⭐ Что такое exponential backoff и jitter? Запиши формулу full jitter. Зачем jitter?

<details><summary>Ответ</summary>

Пауза растёт экспоненциально с ограничением сверху; jitter добавляет случайность:
`sleep = random(0, min(cap, base × 2^attempt))`. Без jitter клиенты ретраят синхронно
и создают волны нагрузки.

</details>

**A6.** ⭐ Что такое retry storm? Во сколько раз усилится нагрузка на базу, если четыре слоя
ретраят по 3 попытки?

<details><summary>Ответ</summary>

Каждый слой умножает попытки: 3⁴ = 81 запрос в базу на один запрос пользователя.
Именно когда база и так тормозит.

</details>

**A7.** Что такое retry budget?

<details><summary>Ответ</summary>

Лимит доли ретраев от общего числа запросов (например, 10%): при массовых ошибках
ретраи перестают множить нагрузку.

</details>

**A8.** Что такое идемпотентность? Какие HTTP-методы идемпотентны? Как сделать безопасным
повтор `POST /payments`?

<details><summary>Ответ</summary>

Повтор даёт тот же результат. Идемпотентны GET, HEAD, OPTIONS, PUT, DELETE; POST — нет.
Для POST — `Idempotency-Key`: сервер сохраняет результат по ключу (уникальное ограничение
в БД) и на повтор отдаёт сохранённый ответ.

</details>

**A9.** Почему консьюмер очереди должен быть идемпотентным?

<details><summary>Ответ</summary>

Очереди гарантируют доставку «хотя бы один раз»: при сбое консьюмера сообщение
придёт снова. Без идемпотентности — дубли (двойные письма, списания).

</details>

**A10.** ⭐ Опиши состояния circuit breaker и переходы между ними.

<details><summary>Ответ</summary>

CLOSED — пропускает, считает ошибки; при превышении порога → OPEN — сразу отказ
(fail fast) на время `reset_timeout`; затем HALF-OPEN — пропускает пробные запросы: успех →
CLOSED, неудача → снова OPEN.

</details>

**A11.** Что такое bulkhead? Приведи три примера.

<details><summary>Ответ</summary>

Изоляция ресурсов, чтобы отказ одной части не съел всё: отдельные пулы соединений
на зависимости, семафоры, отдельные инстансы/node pool'ы для критичного и фонового трафика,
лимиты `connectionPool` в mesh.

</details>

**A12.** Чем token bucket отличается от fixed window? Чем rate limiting отличается
от load shedding?

<details><summary>Ответ</summary>

Token bucket допускает всплески до размера ведра при средней скорости N/с; fixed window
считает запросы в окне и позволяет двойной всплеск на границе окон. Rate limiting — квоты
на клиента; load shedding — сброс части нагрузки при перегрузке сервиса в целом.

</details>

**A13.** Приведи четыре примера graceful degradation.

<details><summary>Ответ</summary>

Популярные товары вместо персональных рекомендаций, приём заказа с отложенной оплатой,
read-only режим, выключение тяжёлой фичи флагом, простой поиск вместо полнотекстового.

</details>

**A14.** ⭐ Опиши последовательность graceful shutdown пода в Kubernetes. Зачем `preStop: sleep`?

<details><summary>Ответ</summary>

Под → Terminating и параллельно удаляется из Endpoints; выполняется preStop;
SIGTERM — приложение перестаёт принимать новые запросы и дорабатывает текущие; после
`terminationGracePeriodSeconds` — SIGKILL. `preStop: sleep` нужен, потому что удаление
из Endpoints распространяется асинхронно: несколько секунд трафик ещё идёт на под.

</details>

**A15.** Чем liveness отличается от readiness? Почему нельзя проверять базу в liveness?

<details><summary>Ответ</summary>

Liveness решает «рестартовать ли контейнер», readiness — «слать ли трафик».
Если liveness проверяет базу, короткое моргание базы рестартует все поды разом —
маленький сбой превращается в большой.

</details>

**A16.** Сформулируй закон Литтла. Сколько соединений нужно пулу при 300 RPS и 40 мс
на запрос?

<details><summary>Ответ</summary>

`L = λ × W`: 300 × 0,04 = 12 одновременных запросов. С запасом на пики и разброс —

</details>

**A17.** Чем open model отличается от closed model в нагрузочном тесте? Что такое
coordinated omission?

<details><summary>Ответ</summary>

Closed: фиксированное число виртуальных пользователей в цикле — при тормозах сервиса
они отправляют меньше запросов, и тест «прячет» деградацию (coordinated omission).
Open: задаётся поток запросов (arrival rate), он держится независимо от ответов — как
реальный трафик API.

</details>

**A18.** Назови шесть типов нагрузочных тестов и цель каждого.

<details><summary>Ответ</summary>

Smoke (скрипт работает), load (обычная нагрузка в SLO), stress (выше нормы), spike
(резкий всплеск), soak (часы — утечки), breakpoint (найти предел).

</details>

**A19.** Из каких шагов состоит chaos-эксперимент? Что такое game day?

<details><summary>Ответ</summary>

Steady state → гипотеза → эксперимент с ограниченным радиусом и условиями остановки →
наблюдение → выводы и задачи. Game day — запланированные учения команды: отказ плюс
проведение инцидента по-настоящему и постмортем.

</details>

---

### Блок B. «Что произойдёт / что тут не так»


```text:no-line-numbers
B1.  requests.get("http://payments/pay")
```text
<details><summary>Ответ</summary>

⚠️ `requests` по умолчанию ждёт бесконечно — зависание payments повесит воркеры.
Нужен `timeout=(0.5, 2)`.

</details>

```text:no-line-numbers
B2.  for i in range(5):
```text
<details><summary>Ответ</summary>

⚠️ Ретрай неидемпотентного POST (двойные списания), ловится любое исключение,
фиксированная пауза без backoff и jitter, 5 попыток. Нужны `Idempotency-Key`, ретрай
только временных ошибок, backoff + jitter, 2–3 попытки.

</details>

```text:no-line-numbers
         try:
```text
```text:no-line-numbers
             requests.post(PAY_URL, json=order, timeout=2)
```text
```text:no-line-numbers
             break
```text
```text:no-line-numbers
         except Exception:
```text
```text:no-line-numbers
             time.sleep(1)
```text
```text:no-line-numbers
B3.  # ретраим любой статус >= 400, включая 400 Bad Request
```text
<details><summary>Ответ</summary>

⚠️ 4xx — ошибки запроса: повтор даст тот же ответ и лишнюю нагрузку.

</details>


```text:no-line-numbers
B4.  # клиент, API, payments и драйвер БД — каждый ретраит 3 раза
```text
<details><summary>Ответ</summary>

⚠️ Retry storm: 3⁴ = 81× на базу. Ретраи — на одном уровне, с бюджетом.

</details>

```text:no-line-numbers
B5.  livenessProbe:
```text
<details><summary>Ответ</summary>

⚠️ Моргнула база или Redis — рестарт всех подов. Зависимости — не в liveness.

</details>

```text:no-line-numbers
       httpGet: { path: /health, port: 8000 }   # /health проверяет Postgres и Redis
```text
```text:no-line-numbers
B6.  # Dockerfile
```text
<details><summary>Ответ</summary>

⚠️ Shell-форма запускает `/bin/sh -c`, SIGTERM получает shell, а не Python —
graceful shutdown не происходит, через 30 с SIGKILL. Нужна exec-форма:
`CMD ["python", "app.py"]`.

</details>

```text:no-line-numbers
     CMD python app.py              # shell-форма; terminationGracePeriodSeconds: 30
```text
```text:no-line-numbers
B7.  // «проверим, сколько RPS выдержит API»
```text
<details><summary>Ответ</summary>

⚠️ Closed model со `sleep(1)`: при тормозах сервиса нагрузка сама снижается,
тест не покажет предел. Нужен `ramping-arrival-rate`.

</details>

```text:no-line-numbers
     export const options = { vus: 50, duration: '10m' };
```text
```text:no-line-numbers
     export default function () { http.get(URL); sleep(1); }
```text
```text:no-line-numbers
B8.  circuit breaker: failure_threshold = 1, reset_timeout = 5 минут
```text
<details><summary>Ответ</summary>

⚠️ Одна случайная ошибка открывает breaker на 5 минут — сервис сам себе устраивает
отказ. Порог по доле ошибок на окне, `reset_timeout` — секунды или десятки секунд.

</details>

```text:no-line-numbers
B9.  limit_req zone=api;            # без burst; клиенты шлют пачки по 5 запросов разом
```text
<details><summary>Ответ</summary>

⚠️ Без `burst` лишние запросы пачки сразу получают отказ, хотя средняя скорость в норме.
Нужен `burst` (и `nodelay`, если не хочется задерживать).

</details>

```text:no-line-numbers
B10.  fallback «показывать закэшированные цены» написан год назад, ни разу не срабатывал
```text
<details><summary>Ответ</summary>

⚠️ Непроверенный fallback скорее всего не сработает. Проверить chaos-экспериментом.

</details>

```text:no-line-numbers
B11.  «Давайте в пятницу вечером убьём продовую базу и посмотрим, что будет»
```text
<details><summary>Ответ</summary>

⚠️ Нет гипотезы, радиуса, стоп-условий; прод и пятница. Начинать со staging,
в рабочее время, с ограниченным радиусом.

</details>

```text:no-line-numbers
B12.  пул соединений 200 на каждом из 20 подов; у PostgreSQL max_connections = 100
```text
<details><summary>Ответ</summary>

⚠️ 20 × 200 = 4000 соединений при лимите 100. Пулы считать от лимита БД
(с учётом всех подов и HPA) или ставить PgBouncer.

</details>

```text:no-line-numbers
B13.  таймаут shop-api → payments 10 с, таймаут Ingress — 5 с
```text
<details><summary>Ответ</summary>

⚠️ Ingress сдаётся через 5 с, а shop-api ждёт payments ещё 5 с впустую.
Внутренний таймаут должен быть меньше внешнего.

</details>


---

### Блок C. Практика


### C1. 🔑 Падение против зависания
**1.** `docker compose pause payments`, сделай два запроса к `/checkout` с
   `curl -s -o /dev/null -w "%{http_code} %{time_total}s\n"`.

<details><summary>Ответ</summary>

`pause`: 504 примерно через 2 с — процесс заморожен, соединение принимается ядром,
ответа нет, срабатывает read timeout. `stop`: 502 за десятки миллисекунд — имя `payments`
не резолвится, ошибка мгновенная. Зависание хуже: каждый запрос держит ресурсы до таймаута.

</details>

**2.** `docker compose unpause payments && docker compose stop payments` — повтори.

<details><summary>Ответ</summary>

На стенде колено обычно около 110–130 RPS (при расчётных ~133): p95 скачком уходит
с ~0,2 с в секунды, затем основная масса ошибок — 504 (таймаут shop-api → payments), часть —

</details>

**3.** Сравни коды и время. Почему зависание хуже падения? Не забудь `docker compose start payments`.

<details><summary>Ответ</summary>

Прогноз: 20 / 0,075 ≈ 267 RPS. На практике упрёшься раньше — в CPU единственного
процесса uvicorn в shop-api или payments (накладные расходы Python и инструментации).
Узкое место переехало из пула в CPU.

</details>

### C2. 🔑 Найти «колено» k6
**1.** Запусти `load.js` с выводом в Prometheus.

<details><summary>Ответ</summary>

`pause`: 504 примерно через 2 с — процесс заморожен, соединение принимается ядром,
ответа нет, срабатывает read timeout. `stop`: 502 за десятки миллисекунд — имя `payments`
не резолвится, ошибка мгновенная. Зависание хуже: каждый запрос держит ресурсы до таймаута.

</details>

**2.** По графикам RPS и p95 `/checkout` найди нагрузку, на которой латентность резко растёт.

<details><summary>Ответ</summary>

На стенде колено обычно около 110–130 RPS (при расчётных ~133): p95 скачком уходит
с ~0,2 с в секунды, затем основная масса ошибок — 504 (таймаут shop-api → payments), часть —

</details>

**3.** Какие коды ошибок появились? Есть ли `dropped_iterations`? Что показывает спан
   `db.pool.acquire` в медленных трейсах?

<details><summary>Ответ</summary>

Прогноз: 20 / 0,075 ≈ 267 RPS. На практике упрёшься раньше — в CPU единственного
процесса uvicorn в shop-api или payments (накладные расходы Python и инструментации).
Узкое место переехало из пула в CPU.

</details>

### C3. Закон Литтла
Посчитай ожидаемую ёмкость payments при `POOL_SIZE=20` (среднее время обработки ~75 мс).
Поменяй в compose, перезапусти, повтори C2. Совпал ли прогноз? Если нет — что стало
следующим узким местом?

### C4. Ретраи с jitter
**1.** Оберни вызов payments в `/checkout` функцией `get_with_retries` из конспекта.

<details><summary>Ответ</summary>

`pause`: 504 примерно через 2 с — процесс заморожен, соединение принимается ядром,
ответа нет, срабатывает read timeout. `stop`: 502 за десятки миллисекунд — имя `payments`
не резолвится, ошибка мгновенная. Зависание хуже: каждый запрос держит ресурсы до таймаута.

</details>

**2.** Включи `error_rate=0.3`. Сравни долю ошибок `/checkout` и RPS на payments с ретраями
   и без. Посчитай теоретические значения заранее.

<details><summary>Ответ</summary>

На стенде колено обычно около 110–130 RPS (при расчётных ~133): p95 скачком уходит
с ~0,2 с в секунды, затем основная масса ошибок — 504 (таймаут shop-api → payments), часть —

</details>

### C5. Circuit breaker
Добавь `CircuitBreaker` с fallback `{"status": "queued"}`. Сделай `pause payments`
под фоновым трафиком. Как изменились латентность и коды ответов после срабатывания breaker?

### C6. Bulkhead
Ограничь одновременные вызовы payments семафором на 20 с быстрым отказом `503`.
Прогони `load.js`. Сравни распределение латентности и кодов с C2.

### C7. Rate limiting
Поставь перед shop-api контейнер nginx с `limit_req` (10 r/s, burst 20). Дай всплеск k6.
Какая доля ответов — `429`? Что увидит клиент в заголовках?

### C8. Graceful shutdown
Под постоянной нагрузкой (`constant-arrival-rate`, 30 RPS) сделай `docker compose restart shop-api`.
Сколько запросов упало? Что понадобилось бы в Kubernetes, чтобы деплой проходил без ошибок?

### C9. 🔑 Chaos-эксперимент по правилам
Для сценария «payments отвечает на 500 мс дольше» запиши: steady state (SLI), гипотезу,
радиус поражения, условия остановки. Проведи (`/chaos?delay_ms=500`), сравни с гипотезой,
оформи выводы как action items.

---

### Блок D. Инциденты


**D1.** После каждого деплоя — всплеск 502 примерно на 20 секунд.

<details><summary>Ответ</summary>

Нет graceful shutdown: под получает трафик после SIGTERM или умирает с запросами
в работе. `preStop: sleep 5–10`, обработка SIGTERM (exec-форма CMD), readiness,
`maxUnavailable: 0`, достаточный `terminationGracePeriodSeconds`.

</details>

**D2.** База притормозила на минуту, а сервис лежит 40 минут и сам не поднимается.

<details><summary>Ответ</summary>

Retry storm и «thundering herd»: после минуты тормозов все клиенты ретраят,
очереди забиты протухшими запросами, база не может выйти из перегрузки. Смягчение — сброс
нагрузки (rate limit, выключить ретраи/фичи), затем постепенный возврат трафика.
Долгосрочно: backoff + jitter, retry budget, circuit breaker, deadline propagation.

</details>

**D3.** Части пользователей дважды списали деньги за один заказ.

<details><summary>Ответ</summary>

Неидемпотентный POST ретраился (клиент, шлюз или код) после таймаута, когда первый
запрос уже прошёл. Ключ идемпотентности + уникальное ограничение в БД, ретраи POST только
с ключом.

</details>

**D4.** Медленный внешний сервис рекомендаций положил весь сайт.

<details><summary>Ответ</summary>

Нет таймаута или слишком большой, общий пул воркеров, нет деградации. Таймаут,
bulkhead для вызова рекомендаций, circuit breaker, fallback «популярное из кэша».

</details>

**D5.** Все поды одновременно ушли в рестарт, пока перезагружался Redis.

<details><summary>Ответ</summary>

Liveness проверяет Redis. Убрать зависимости из liveness, readiness — только
собственная готовность, здоровье Redis — в метриках и алертах.

</details>

**D6.** Нагрузочный тест в staging прошёл на 500 RPS, а прод упал на 300 RPS.

<details><summary>Ответ</summary>

Staging не похож на прод: меньше данных (индексы, кэши ведут себя иначе), другие
лимиты, нет фонового трафика, closed-модель теста, прогретые кэши, не учтены внешние API.
Приблизить данные и конфигурацию, open model, тестировать всю цепочку.

</details>

**D7.** После внедрения circuit breaker сервис «флапает»: open/closed каждые несколько секунд.

<details><summary>Ответ</summary>

Слишком низкий порог (по числу ошибок, а не доле), короткое окно, короткий
`reset_timeout`, неограниченный поток в half-open. Порог по доле на окне с минимальным
числом запросов, ограниченное число проб.

</details>

**D8.** HPA добавил подов под нагрузкой — стало только хуже, база легла по соединениям.

<details><summary>Ответ</summary>

Узкое место — база, а не CPU подов: больше подов — больше соединений и нагрузки на
базу. Считать соединения от лимита БД, PgBouncer, ограничить `maxReplicas`, масштабировать
по правильной метрике, оптимизировать запросы.

</details>

**D9.** k6 показывает `dropped_iterations` и p95 = 6 с при заданных 200 RPS.

<details><summary>Ответ</summary>

Сервис насыщен: запросы висят, VU заняты ожиданием, генератор не держит заданный RPS.
Колено уже пройдено — смотреть RED, трейсы (`db.pool.acquire`) и ресурсы. Если сервис в норме,
а растёт только `dropped_iterations`, — увеличить `maxVUs`.

</details>

---

### Блок E. Вопросы с собеседования


**1.** Как правильно делать ретраи?

<details><summary>Ответ</summary>

Только временные ошибки и идемпотентные операции (или с ключом), 2–3 попытки,
   exponential backoff с jitter, на одном уровне, с retry budget, уважая `Retry-After`.

</details>

**2.** Что такое exponential backoff и jitter?

<details><summary>Ответ</summary>

Пауза между попытками растёт экспоненциально с ограничением; jitter — случайная пауза
   в этих пределах, чтобы клиенты не ретраили синхронно.

</details>

**3.** Что такое идемпотентность и зачем она нужна?

<details><summary>Ответ</summary>

Повтор операции даёт тот же результат; делает безопасными ретраи и доставку «хотя бы один
   раз». Реализуется ключом идемпотентности и уникальным ограничением.

</details>

**4.** Что такое circuit breaker?

<details><summary>Ответ</summary>

Автомат с состояниями closed/open/half-open: при частых ошибках перестаёт звать зависимость
   и отвечает сразу (или fallback), периодически пробует восстановиться.

</details>

**5.** Что такое bulkhead?

<details><summary>Ответ</summary>

Изоляция ресурсов (пулы, семафоры, инстансы) по зависимостям и классам трафика, чтобы
   отказ одной части не съел всё.

</details>

**6.** Чем liveness отличается от readiness?

<details><summary>Ответ</summary>

Liveness — «жив ли процесс» (рестарт), readiness — «готов ли к трафику» (исключение
   из балансировки).

</details>

**7.** Как сделать graceful shutdown в Kubernetes?

<details><summary>Ответ</summary>

Обработка SIGTERM в приложении, `preStop: sleep`, readiness, достаточный grace period,
   rolling update с `maxUnavailable: 0`, PDB.

</details>

**8.** Как ты проведёшь нагрузочное тестирование сервиса?

<details><summary>Ответ</summary>

Цель и SLO → сценарий по реальному профилю → open model (arrival rate) в k6 → smoke,
   затем ступенчатый рост → thresholds от SLO → наблюдение за сервером (RED, трейсы,
   ресурсы) → поиск колена и узкого места → отчёт.

</details>

**9.** Что такое chaos engineering?

<details><summary>Ответ</summary>

Контролируемые эксперименты с отказами: steady state, гипотеза, малый радиус,
   условия остановки, выводы; game day — учения команды.

</details>

**10.** Как оценить, сколько ресурсов нужно сервису?

<details><summary>Ответ</summary>

Закон Литтла, профиль нагрузки и пики, нагрузочный тест до колена, запас N+1 и целевая
    утилизация, учёт узких мест вне CPU (пулы, лимиты БД, квоты).

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] Ставлю таймауты на все вызовы и объясняю каскадный отказ
- [ ] ⭐ Пишу ретраи с backoff + jitter и знаю, что ретраить нельзя
- [ ] Объясняю retry storm и считаю усиление
- [ ] Делаю POST безопасным для повторов ключом идемпотентности
- [ ] ⭐ Объясняю circuit breaker и bulkhead; простой breaker на стенде работает
- [ ] Знаю rate limiting, load shedding и варианты деградации
- [ ] Объясняю graceful shutdown в Kubernetes и liveness vs readiness
- [ ] Считаю ёмкость по закону Литтла
- [ ] k6-прогон на стенде показал «колено», узкое место найдено по трейсам
- [ ] Chaos-эксперимент проведён по правилам: steady state, гипотеза, стоп-условия
