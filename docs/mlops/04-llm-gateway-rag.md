---
title: "04. LLM-шлюз, RAG и векторные базы"
description: "Блок → AI/MLOps-инфраструктура → тема 04. Вопросы собеса: «Зачем вам LLM-шлюз, если"
---

# 04. LLM-шлюз, RAG и векторные базы

> Блок → AI/MLOps-инфраструктура → тема 04. Вопросы собеса: *«Зачем вам LLM-шлюз, если
> у провайдера есть SDK?»*, *«Счёт за LLM-API вырос — как найти, кто тратит?»*,
> *«Как эксплуатировать pgvector?»*, *«Можно ли отправлять данные клиентов в OpenAI?»*
> **После темы ты умеешь:** поднять LiteLLM proxy с локальной моделью из
> [03_model_serving.md](/mlops/03-model-serving), раздать командам ключи с бюджетами и tpm/rpm,
> снять метрики токенов и денег; разложить RAG на инфраструктурные компоненты; эксплуатировать
> pgvector и Qdrant; посчитать стоимость LLM-фичи и объяснить, какие данные не выпускать из РК.
> Версии — «проверь, сентябрь 2026».

---

## 🗺️ Карта темы

```text
 команды / сервисы                     LLM-ШЛЮЗ (LiteLLM proxy, :4000)
 ─────────────────                     ──────────────────────────────────────────────
 support-bot ── key sk-sup… ──┐        1. аутентификация по виртуальному ключу
 search-api  ── key sk-srch… ─┼──────► 2. проверка: модель разрешена? бюджет? tpm/rpm?
 ноутбук DS  ── key sk-ds…  ──┘        3. кэш (Redis) ── попадание → ответ без провайдера
                                       4. маршрут: модель → деплой, ретраи, fallback
                                       5. учёт: токены × цена → spend в Postgres
                                       6. /metrics → Prometheus → Grafana; OTel-спаны → Collector
                          ┌────────────────────┴───────┐
                          ▼                            ▼
               локальная модель в РК          внешний провайдер за рубежом
               (llama.cpp / vLLM, тема 03)    (только разрешённые данные, §10)

 RAG:  документы ─► ingestion Job ─► чанки ─► embeddings ─► векторная БД (pgvector / Qdrant)
       вопрос ─► embedding ─► top-k похожих чанков ─► (rerank) ─► промпт + контекст ─► LLM
```text
---

## 1. Зачем компании один шлюз к LLM

Без шлюза каждая команда держит свой ключ провайдера в `.env` и зовёт API напрямую. Через полгода:
пять ключей, общий счёт без разбивки, ключ в чьём-то ноутбуке, неизвестно, какие данные ушли наружу.

| Проблема без шлюза | Что даёт шлюз |
|--------------------|---------------|
| Ключ провайдера у каждой команды и в каждом репозитории | ⭐ Ключ провайдера **один** и живёт только в шлюзе; командам — виртуальные ключи, которые можно отозвать за секунду |
| Счёт приходит одной суммой | Учёт токенов и денег по команде, ключу, модели |
| Один скрипт в цикле съел месячный бюджет за ночь | Бюджет на ключ/команду с периодом сброса, лимиты tpm/rpm |
| Провайдер лёг — лежит фича | Ретраи, fallback на другую модель или провайдера |
| Одинаковые вопросы оплачиваются снова и снова | Кэш ответов |
| Непонятно, кто что отправлял | Журнал запросов: кто, когда, какая модель, сколько токенов |
| Данные клиентов уходят за рубеж «по умолчанию» | ⭐ Контроль исходящих данных: ключ команды разрешает только определённые модели (например, только локальную) |
| Смена провайдера = правка кода во всех сервисах | Единый OpenAI-совместимый API: меняется конфиг шлюза, а не код |

> 💡 Шлюз — L7-прокси, который понимает токены и деньги: таймауты, ретраи, лимиты, TLS, HA — как у любого
> прокси ([../Network/18_modern_proxies.md](/network/18-modern-proxies)); новое — единица учёта **токен**.

---

## 2. Какие бывают шлюзы (проверь, сентябрь 2026)

| Шлюз | Что это | Лицензия и статус | Когда смотреть |
|------|---------|-------------------|----------------|
| **LiteLLM proxy** | Python-прокси с OpenAI-совместимым API к 100+ провайдерам; ключи, бюджеты, лимиты, кэш, fallback, Prometheus | MIT (кроме каталога enterprise; SSO и аудит-логи — платно). Стабильные релизы еженедельно, последняя стабильная — **v1.102.1** (23.09.2026). Нужен PostgreSQL | ⭐ Стандартный self-hosted старт — на нём лабы блока |
| **Agent Router** (бывший **Envoy AI Gateway**) | Контроллер поверх Envoy Gateway: CRD `AIGatewayRoute`, `AIServiceBackend`, лимиты по токенам, fallback, MCP-шлюз, OTel GenAI | v1.0.0 — 23.06.2026, **v1.1.0** — 21.08.2026; 10.09.2026 переименован и ушёл в Agentic AI Foundation («same code, same APIs») | Уже есть Envoy Gateway ([../Kubernetes/12_ingress.md](/kubernetes/12-ingress) §7), хочется k8s-native и CRD в GitOps |
| **Kong AI Gateway** | Набор AI-плагинов к Kong: AI Proxy, семантический кэш, prompt guard | Лимиты по токенам (**AI Rate Limiting Advanced**) — только в Enterprise | Компания уже живёт на Kong |
| **Portkey gateway** | TypeScript-шлюз: маршрутизация, ретраи, fallback, кэш, guardrails | Шлюз MIT; компанию купила Palo Alto Networks (сделка закрыта 29.05.2026) | Нужен лёгкий шлюз без БД; следи за дорожной картой после покупки |

Как выбирать — вопросы, а не бренды: **где работает и куда шлёт данные** (свой контур или
SaaS за рубежом, §10); **где состояние** (ключи и учёт — БД с бэкапами и HA); **что в бесплатной
версии** (лимиты по токенам, SSO, аудит часто платные); **как конфигурируется** (файл + API
или CRD в git); **цепочка поставок**. ⚠️ 24.03.2026 пакеты `litellm` **1.82.7 и 1.82.8** на PyPI около
40 минут содержали бэкдор (кража кредов, попытки двигаться по Kubernetes-кластеру) — токены
публикации утекли через скомпрометированный Trivy в CI проекта. Вывод для любого шлюза: он
держит ключи ко всем провайдерам, поэтому образ — по тегу **и digest**, обновления через
staging, сканирование и подпись ([../Security/04_vuln_management.md](/security/04-vuln-management)).

---

## 3. LiteLLM proxy: как устроен и как настроить

```text
 клиенты ──► litellm (stateless, N реплик) ──► провайдеры / локальные модели
             ├─► PostgreSQL: ключи, команды, бюджеты, spend
             └─► Redis: общий счётчик tpm/rpm и кэш (нужен при >1 реплике)
```text
- **PostgreSQL обязателен** для виртуальных ключей, команд и учёта денег (`DATABASE_URL`);
  без БД остаётся один мастер-ключ — это уже не шлюз, а прокси.
- `LITELLM_MASTER_KEY` (начинается с `sk-`) — админский ключ: создаёт команды и ключи.
- `LITELLM_SALT_KEY` — шифрует креды провайдеров, сохранённые в БД. ⚠️ Задаётся **один раз**:
  сменишь — сохранённые креды не расшифруются. Оба ключа — в Vault/ESO
  ([../Left/08_Vault/05_vault_integrations.md](/vault/05-vault-integrations) §2).
- Порт 4000, пробы: `/health/liveliness` (процесс жив) и `/health/readiness` (есть связь с БД).
- Helm-чарт: `oci://ghcr.io/berriai/litellm-helm` (проверь values перед установкой).

### Конфиг: локальная модель + внешняя (опционально)

```yaml
# litellm-config.yaml
model_list:
  - model_name: local-chat                      # имя, которое видят клиенты
    litellm_params:
      model: ollama_chat/qwen2.5:0.5b           # compose-стенд: Ollama, ollama_chat/ → /api/chat
      api_base: http://ollama:11434
      # в kind — llama.cpp из темы 03 (OpenAI-совместимый API):
      # model: openai/qwen2.5-0.5b, api_base: http://llm.llm.svc/v1, api_key: "none"
    model_info:
      input_cost_per_token: 0.0000001           # «внутренняя цена» локальной модели:
      output_cost_per_token: 0.0000004          # чтобы бюджеты и дашборды работали и для неё

  - model_name: local-embed                     # эмбеддинги для RAG (§7)
    litellm_params:
      model: ollama/bge-m3
      api_base: http://ollama:11434

  # внешний провайдер — ТОЛЬКО если есть ключ и разрешение на данные (§10):
  # - { model_name: external-chat, litellm_params: { model: "openai/&lt;модель&gt;",
  #     api_key: os.environ/OPENAI_API_KEY, rpm: 60 } }   # ⭐ секрет из env; rpm — квота деплоя

litellm_settings:
  callbacks: ["prometheus"]                     # /metrics на порту 4000 (по умолчанию — только с ключом)
  request_timeout: 60
  # fallbacks: [{"external-chat": ["local-chat"]}]  # внешний лёг или 429 → локальная
  cache: true
  cache_params:
    type: redis                                 # на стенде можно type: local
    ttl: 600
  turn_off_message_logging: true                # в логи и колбэки — без текста промптов (§6)

router_settings:
  num_retries: 2                                # ⭐ ретраи роутера: ответ приходит, как только бэкенд ожил
  redis_host: os.environ/REDIS_HOST             # общее состояние роутера между репликами
  redis_port: 6379

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
  store_prompts_in_spend_logs: false            # не хранить промпты в БД учёта
```text
`os.environ/NAME` — ссылка на переменную окружения: секрет не попадает в ConfigMap и git.

---

## 4. Ключи, команды, бюджеты, лимиты

Иерархия: **команда** (team) → **ключи** команды → запросы. Бюджет и лимиты вешаются
на команду и/или ключ, срабатывает самое строгое.

```bash
export GW=http://localhost:4000 MK="$LITELLM_MASTER_KEY"

# команда поддержки: только локальная модель, $20 в месяц, 20 000 токенов/мин
curl -s $GW/team/new -H "Authorization: Bearer $MK" -H 'Content-Type: application/json' \
  -d '{"team_alias":"support","models":["local-chat","local-embed"],
       "max_budget":20,"budget_duration":"30d","tpm_limit":20000,"rpm_limit":60}'
# → {"team_id":"…", …}

# ключ сервиса внутри команды — ещё строже
curl -s $GW/key/generate -H "Authorization: Bearer $MK" -H 'Content-Type: application/json' \
  -d '{"team_id":"&lt;team_id&gt;","key_alias":"support-bot-prod","models":["local-chat"],
       "max_budget":5,"budget_duration":"7d","rpm_limit":10,
       "metadata":{"owner":"support","env":"prod"&#125;&#125;'
# → {"key":"sk-…"}  ⭐ показывается один раз — сразу в Vault

# сколько потрачено
curl -s "$GW/key/info?key=sk-…"          -H "Authorization: Bearer $MK"
curl -s "$GW/team/info?team_id=&lt;team_id&gt;" -H "Authorization: Bearer $MK"
```text
| Ситуация | Ответ шлюза (проверь на своей версии) |
|----------|---------------------------------------|
| Превышен `rpm_limit` / `tpm_limit` | `429`, в v1.102.1 `"type": "throttling_error"`, заголовок `retry-after: 60` (проверено на живом шлюзе) |
| Кончился бюджет ключа или команды | Ошибка `budget_exceeded` (на v1.102.1 — `429`; в документации встречаются и 400 — зависит от уровня бюджета) |
| Модель не в списке `models` ключа | Отказ авторизации — ⭐ так и реализуется «этой команде — только локальная модель» |

---

## 5. Надёжность и кэш

**Ретраи и fallback.** `num_retries` — повтор на тот же деплой (ставь в `router_settings`: на живом стенде ретраи из `litellm_settings` после 36 с простоя бэкенда вернули ответ только через 142 с, а роутерные — через 4 с после его готовности); `fallbacks` — другая модель,
когда деплой не отвечает или упёрся в 429; `context_window_fallbacks` — модель с большим
окном, когда промпт не влез. Деплой, который падает, уходит в cooldown (`allowed_fails`,
`cooldown_time`). Правила ретраев — как в [../SRE/06_reliability_patterns.md](/sre/06-reliability-patterns):
ретраить только временные ошибки и в пределах общего таймаута.

> ⚠️ Fallback «внешний → локальный» безопасен, «локальный → внешний» может **вывести наружу
> данные**, которые разрешено обрабатывать только локально (§10): это решение о данных.

| Кэш ответов | Как работает | Риск |
|-----|--------------|------|
| Точный (`redis`, `local`) | Ключ = хеш модели и сообщений | Мало попаданий, если в промпте есть время, id пользователя |
| Семантический (`redis-semantic`, `qdrant-semantic`) | Похожий по смыслу вопрос → тот же ответ | ⚠️ «Похожий» ≠ «тот же»: чужой ответ, ответ другому клиенту |

Кэш — для FAQ и эмбеддингов одинаковых документов, не для персональных ответов; метрика —
**cache hit rate** (§11). Провайдеры ещё и сами кэшируют повторяющийся префикс промпта дешевле (видно в usage).

---

## 6. Наблюдаемость LLM-вызовов

### Метрики шлюза (Prometheus)

С `callbacks: ["prometheus"]` LiteLLM отдаёт `/metrics` (в OSS-версии). По умолчанию эндпоинт **требует ключ** (`require_auth_for_metrics_endpoint: true`) и редиректит `/metrics` → `/metrics/`: в ServiceMonitor нужны `bearerTokenSecret` и путь со слэшем. Полезный gauge — `litellm_in_flight_requests` (учитывает и сам скрейп):

| Метрика | Что показывает |
|---------|----------------|
| `litellm_input_tokens_metric`, `litellm_output_tokens_metric`, `litellm_total_tokens_metric` | Токены (метки `team`, `hashed_api_key`, `model`, `requested_model`, `api_provider`) |
| `litellm_spend_metric` | Деньги по той же разбивке |
| `litellm_proxy_total_requests_metric`, `litellm_proxy_failed_requests_metric` | Запросы и ошибки |
| `litellm_request_total_latency_metric`, `litellm_llm_api_latency_metric`, `litellm_llm_api_time_to_first_token_metric` | Полная задержка, задержка провайдера (разница = накладные шлюза), TTFT |
| `litellm_remaining_team_budget_metric`, `litellm_remaining_api_key_budget_metric` | ⭐ Остаток бюджета — готовый источник алерта |

```promql
# токены в минуту по командам (имя счётчика в Prometheus может получить суффикс _total — смотри /metrics)
sum by (team) (rate(litellm_total_tokens_metric_total[5m])) * 60
# деньги за сутки по командам
sum by (team) (increase(litellm_spend_metric_total[24h]))
# p95 полной задержки по моделям
histogram_quantile(0.95, sum by (le, model) (rate(litellm_request_total_latency_metric_bucket[5m])))
# алерт: у команды осталось меньше $2 бюджета
litellm_remaining_team_budget_metric < 2
```text
> ⚠️ `/metrics` не публикуй наружу через HTTPRoute — только ServiceMonitor изнутри кластера
> ([../Left/02_Monitoring/11_long_term_and_operator.md](/monitoring/11-long-term-and-operator)).

### OpenTelemetry GenAI semantic conventions

Единый словарь атрибутов для трейсов LLM-вызовов — чтобы спаны из шлюза, SDK и фреймворков
выглядели одинаково ([../SRE/03_tracing_opentelemetry.md](/sre/03-tracing-opentelemetry)).

| Факт (проверь, сентябрь 2026) | |
|-------------------------------|---|
| Статус и место | ⭐ **Development** — не stable, имена ещё меняются; живут в отдельном репозитории `open-telemetry/semantic-conventions-genai` (в основном semconv помечены «moved») |
| Переименование | `gen_ai.system` → **`gen_ai.provider.name`** (старое — deprecated) |
| Пример «ещё меняется» | Гистограмма `gen_ai.client.token.usage` с атрибутом `gen_ai.token.type` в main нового репозитория заменена счётчиками `gen_ai.client.inference.usage.input_tokens` / `.output_tokens` (+ `cache_read`, `reasoning`) |

| Атрибут | Пример | Зачем девопсу |
|---------|--------|---------------|
| `gen_ai.operation.name` | `chat`, `embeddings`, `retrieval`, `execute_tool` | Тип операции; имя спана — `{operation} {model}` |
| `gen_ai.provider.name` | `openai`, `anthropic`, `aws.bedrock` | Разбивка по провайдерам |
| `gen_ai.request.model` / `gen_ai.response.model` | `gpt-4` / `gpt-4-0613` | Какую просили и какая ответила (важно при fallback) |
| `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` | `1520`, `310` | Токены на спане → стоимость запроса |
| `gen_ai.response.finish_reasons` | `["stop"]`, `["length"]` | `length` — ответ обрезан лимитом токенов |
| `error.type`, `server.address` | `timeout`, `api.example.com` | Ошибки и куда реально ушёл запрос |
| `gen_ai.input.messages`, `gen_ai.output.messages` | тексты | ⚠️ **Opt-in**: по умолчанию не пишутся — там могут быть ПДн |

Метрики: `gen_ai.client.operation.duration`, `gen_ai.server.time_to_first_token`,
`gen_ai.server.time_per_output_token` (histogram, секунды). 💡 Закрепи версию конвенций
в дашбордах и читай release notes инструментаций — переименование атрибута молча ломает панели.

### Промпты в логах и приватность

Промпт — данные пользователя: вопрос в поддержку содержит ИИН, телефон, диагноз. Логировать
тексты «для отладки» = складывать ПДн в Loki/Tempo без маскирования и с долгим retention.

| Уровень | Что делаем |
|---------|------------|
| По умолчанию | Метаданные без текста: модель, токены, задержка, команда, `finish_reasons` |
| В шлюзе | `turn_off_message_logging: true`; для OTel-колбэка `callback_settings.otel.message_logging: false`; `store_prompts_in_spend_logs: false` |
| В коллекторе | Процессоры `attributes`/`transform` удаляют `gen_ai.input.messages`/`output.messages` (как чистка PII в SRE/03 §7) |
| Если тексты нужны (оценка качества) | Отдельное хранилище с доступом по ролям, коротким retention, маскированием, в контуре РК |

**Langfuse** — open-source трейсинг и оценка LLM-приложений: MIT (кроме каталогов `ee/`),
self-hosted = web + worker + PostgreSQL + **ClickHouse** + Redis/Valkey + S3 (подойдёт MinIO-форк
из [../Storage/03_nfs_minio.md](/storage/03-nfs-minio)). Актуальна **v4** (август 2026),
v3 — security-патчи до января 2027; с января 2026 проект принадлежит ClickHouse. Для девопса это
ещё одна stateful-система — оцени стоимость эксплуатации до того, как пообещать её ML-команде.

---

## 7. RAG как инфраструктура

RAG (retrieval-augmented generation): модель отвечает по найденным фрагментам твоих документов,
а не «из головы». Для девопса это **пайплайн данных + база + сервис**.

```text
 ИНДЕКСАЦИЯ (Job / CronJob)                     ЗАПРОС (онлайн-сервис)
 ──────────────────────────                     ─────────────────────────────────────
 источник (git, wiki, S3)                       вопрос пользователя
   → загрузка изменившихся файлов (по хешу)       → embedding вопроса (та же модель!)
   → очистка, разбиение на чанки                  → поиск top-k в векторной БД
   → embedding каждого чанка                        + фильтр по метаданным (права!)
   → upsert в векторную БД                         → (rerank: точнее переупорядочить k)
     + метаданные: путь, заголовок,               → промпт: инструкция + чанки + вопрос
       версия, права доступа, хеш                  → LLM через шлюз → ответ со ссылками
```text
| Компонент | Что решает девопс |
|-----------|-------------------|
| **Ingestion** | Job/CronJob или событие (push в git, объект в S3); идемпотентность по хешу чанка; удаление чанков удалённых документов; метрики: сколько документов, лаг индексации, ошибки |
| **Чанкинг** (концепция) | Документ режут на куски по 200–800 токенов с перекрытием; markdown — по заголовкам. Размер чанка влияет на качество **и** на стоимость: каждый найденный чанк — входные токены |
| **Модель эмбеддингов** | ⭐ Одна и та же при индексации и запросе. Размерность фиксирована (`bge-m3` — 1024). Сменил модель — **переиндексация всего**, старые векторы несовместимы. Версию модели храни в метаданных |
| **Векторная БД** | pgvector (§8) или Qdrant (§9): индексы, память, бэкапы, мониторинг |
| **Retrieval и reranking** | top-k (обычно 3–10), порог похожести, фильтры по метаданным; rerank — отдельная модель (cross-encoder) переупорядочивает кандидатов: точнее, но + задержка и ещё один сервис |
| **Права доступа** | ⚠️ RAG «сливает» документы, если индексирует всё подряд: фильтр по ACL пользователя — на этапе поиска, а не в промпте «не показывай секретное» |

---

## 8. pgvector в эксплуатации

Расширение PostgreSQL: векторы — обычная колонка, рядом с метаданными, транзакциями, бэкапами
и всем, что ты знаешь из [../Left/01_Databases/](/databases/).
Версия **0.8.6** (29.07.2026), PostgreSQL 13+; образ `pgvector/pgvector:0.8.6-pg17` (проверь).

```sql
CREATE EXTENSION IF NOT EXISTS vector;          -- в managed-базах — через разрешённые расширения

CREATE TABLE chunks (
  id bigserial PRIMARY KEY, doc_path text NOT NULL, heading text, content text NOT NULL,
  content_sha text NOT NULL UNIQUE,             -- идемпотентный upsert при повторной индексации
  embed_model text NOT NULL DEFAULT 'bge-m3', embedding vector(1024) NOT NULL);

SET maintenance_work_mem = '1GB';               -- ⭐ граф HNSW должен влезть в память
SET max_parallel_maintenance_workers = 2;       -- по умолчанию 2 (+ лидер)
CREATE INDEX CONCURRENTLY chunks_embedding_hnsw
  ON chunks USING hnsw (embedding vector_cosine_ops);   -- m=16, ef_construction=64 по умолчанию

-- поиск: <=> косинусное расстояние, <-> L2, <#> отрицательное скалярное произведение
SET hnsw.ef_search = 40;                        -- по умолчанию 40: больше — точнее и медленнее
SELECT doc_path, heading, 1 - (embedding <=> $1) AS similarity
FROM chunks ORDER BY embedding <=> $1 LIMIT 5;
```text
⚠️ Оператор в запросе должен совпадать с классом индекса (`vector_cosine_ops` ↔ `<=>`),
иначе индекс не используется и идёт полный перебор — проверяй `EXPLAIN`.

| | **HNSW** | **IVFFlat** |
|---|----------|-------------|
| Как устроен | Многослойный граф соседей | Кластеры (`lists`), поиск в ближайших `probes` |
| Точность/скорость запроса | ⭐ Лучше | Хуже при той же скорости |
| Построение | Медленнее, много памяти | Быстрее, меньше памяти |
| Пустая таблица | Можно создать сразу | ⚠️ Строить **после** загрузки данных — центры кластеров берутся из них |
| Параметры | `m`, `ef_construction`; в запросе `hnsw.ef_search` | `lists` ≈ строки/1000 (до 1M), √строк (больше 1M); `ivfflat.probes` (по умолчанию 1, старт ≈ √lists) |
| Выбор | По умолчанию | Очень большие наборы, дорогая память, редкие перестроения |

**Память и размер.** `vector(1024)` — 4 байта × 1024 ≈ **4 КБ на строку**; 1 млн чанков ≈ 4 ГБ
данных + индекс HNSW сопоставимого размера. Индекс должен жить в RAM (`shared_buffers` +
page cache, [../Left/01_Databases/04_postgresql_conf.md](/databases/04-postgresql-conf) §2),
иначе поиск упирается в диск. `halfvec` (2 байта на число) вдвое меньше; для индекса
`vector` — до 2000 измерений, `halfvec` — до 4000. Сообщение «hnsw graph no longer fits into
maintenance_work_mem» при построении — сигнал поднять память, иначе сборка сильно замедлится.

**Фильтры.** `WHERE team = 'support' ORDER BY embedding <=> $1 LIMIT 5` с HNSW может вернуть
меньше 5 строк: индекс нашёл ближайших, фильтр их отсеял. С 0.8 есть итеративный поиск
`SET hnsw.iterative_scan = relaxed_order` (лимит — `hnsw.max_scan_tuples`, по умолчанию 20 000).

**Бэкапы.** Всё из [../Left/01_Databases/05_backup_restore.md](/databases/05-backup-restore)
работает, но `pg_dump` хранит только **определение** индекса: при восстановлении HNSW на
миллионах строк строится **часами** — это входит в RTO. Для больших баз — физический бэкап
и PITR (WAL-G, pgBackRest); «пересчитать эмбеддинги из исходников» тоже стоит денег и времени.
Обновление: новый образ → `ALTER EXTENSION vector UPDATE;` на каждой базе. Мониторинг — как
у любой базы ([../Left/01_Databases/07_db_monitoring.md](/databases/07-db-monitoring)) +
размер индекса и длительность индексации.

---

## 9. Qdrant — отдельная векторная база

Qdrant — специализированная векторная БД на Rust (Apache-2.0), **v1.19.1** (04.09.2026),
образ `qdrant/qdrant:v1.19.1`, порты 6333 (REST) и 6334 (gRPC). Коллекции с векторами
и payload, фильтры по payload, квантизация, шардирование и репликация.

```bash
# снапшот коллекции (tar-архив в каталоге snapshots ноды)
curl -X POST http://qdrant:6333/collections/docs/snapshots
curl http://qdrant:6333/collections/docs/snapshots               # список
# восстановление из снапшота по URL или пути; priority: replica | snapshot | no_sync
curl -X PUT http://qdrant:6333/collections/docs/snapshots/recover \
  -H 'Content-Type: application/json' \
  -d '{"location":"http://backup-host/docs-2026-09-28.snapshot","priority":"snapshot"}'
```text
- ⚠️ В кластере снапшот делается **на каждой ноде** отдельно; файлы уносит в S3 твоя CronJob.
- Кластер (Raft для метаданных): `shard_number`, `replication_factor` (копий шарда),
  `write_consistency_factor` (сколько реплик подтверждают запись; живых меньше — запись падает).
  Для отказоустойчивости — от 3 нод и `replication_factor: 2`. В k8s — Helm-чарт, StatefulSet с PVC.

| | pgvector | Qdrant |
|---|----------|--------|
| Плюсы | Одна база, SQL, транзакции, JOIN с метаданными, привычные бэкапы и HA | Быстрее на больших объёмах, фильтры и квантизация «из коробки», горизонтальное шардирование |
| Минусы | Масштаб упирается в одну ноду Postgres; индексы тяжелы для RAM и перестроения | Новый стек: бэкапы снапшотами, мониторинг, обновления, on-call |
| Когда | ⭐ До миллионов векторов, команда уже умеет Postgres | Десятки миллионов+, высокие требования к задержке, нужен шардинг |

---

## 10. Какие данные могут уйти из Казахстана

Каждый запрос во внешний LLM-API — это **передача данных провайдеру** за рубеж. Требования
закона РК о ПДн (локализация баз с ПДн, меры защиты, уведомление об утечке за один рабочий
день) — в [../Security/07_security_incidents_compliance.md](/security/07-security-incidents-compliance) §7.
Считается ли конкретный сценарий трансграничной передачей, нужна ли отдельная правовая
основа, согласие или договор — **уточни у юриста**. Задача девопса — сделать так, чтобы
решение юриста исполнялось технически.

| Класс данных (пример классификации) | Внешний API | Локальная модель в РК |
|-------------------------------------|-------------|-----------------------|
| Публичные (документация продукта, открытый код) | Да | Да |
| Внутренние (архитектура, runbook без секретов) | По политике компании и условиям провайдера | Да |
| Конфиденциальные (код, договоры, финансы) | Только с одобрения безопасности и по договору с провайдером | Да |
| ⭐ ПДн клиентов (ФИО, ИИН, телефон, обращения) | ❌ По умолчанию нет — только по решению юриста и после обезличивания | Да, с мерами защиты |
| ПДн ограниченного доступа (биометрия, медданные) | ❌ | Только в системах в РК с шифрованием (Security/07 §7) |
| Секреты (ключи, пароли, токены) | ❌ Никогда | ❌ Не место в промпте вообще |

Как исполнить технически:
1. **Класс данных** у каждого сервиса и команды; **ключ = класс**: у команды с ПДн в `models`
   только локальные модели, fallback наружу не настраивается.
2. **Обезличивание** до шлюза или в нём (guardrails, свой сервис): ИИН, телефоны, e-mail;
   регулярки ловят не всё — это снижение риска, а не гарантия.
3. **Egress:** поды не ходят в интернет напрямую — NetworkPolicy/egress-прокси пускают
   к провайдерам только шлюз.
4. **Условия провайдера** (хранит ли запросы, учится ли на них, где обрабатывает) — договор,
   а не галочка в консоли; читать вместе с юристом.

---

## 11. Сколько это стоит

```text
 стоимость = Σ (входные токены × цена входа + выходные токены × цена выхода)
 с кэшем:  стоимость × (1 − cache hit rate)            ← попадание не идёт к провайдеру
```text
Пример (цены условные, для расчёта: **$0,50 за 1M входных, $2 за 1M выходных**; реальные —
в прайсе провайдера, проверь):

| Шаг | Расчёт | Итог |
|-----|--------|------|
| Бот поддержки: 20 000 запросов/день, 1 500 входных (вопрос + 4 чанка RAG) и 300 выходных | вход 30M × $0,50 = $15; выход 6M × $2 = $12 | **$27/день ≈ $810/мес** |
| RAG берёт 10 чанков по ~300 токенов вместо 4 | вход 3 300 токенов → 66M × $0,50 = $33 + $12 | $45/день — ⭐ **+67%** от одной настройки top-k |
| Кэш FAQ, hit rate 30% (исходный вариант) | $810 × 0,7 | ≈ $567/мес |
| Своя модель на GPU-ноде $2/час круглосуточно | 2 × 730 | $1 460/мес при **любой** нагрузке ([02_gpu_kubernetes.md](/mlops/02-gpu-kubernetes)) |

Выводы: главный рычаг — **входные токены** (контекст RAG, история, системный промпт), а не число
запросов; своя модель выгодна при высокой ровной загрузке или когда данные нельзя выпускать;
бюджеты и алерт на остаток — обязательны. Методика — [../FinOps/00_INDEX.md](/finops/).

---

## 🧪 Мини-лаба: LiteLLM + Ollama в compose, ключ с лимитом

Полная версия в kind с двумя командами и Grafana — лаба 3 в [07_practice_labs.md](/mlops/07-practice-labs).

```yaml
# ~/labs/mlops/gw/docker-compose.yml — образы проверь, сентябрь 2026
services:
  db:
    image: postgres:17
    environment: { POSTGRES_DB: litellm, POSTGRES_USER: llm, POSTGRES_PASSWORD: llm-pass }
  ollama: { image: "ollama/ollama:0.34.4", volumes: ["ollama:/root/.ollama"] }  # модель — один раз
  litellm:
    image: ghcr.io/berriai/litellm:v1.102.1         # в проде — ещё и @sha256:…
    command: ["--config", "/app/config.yaml", "--port", "4000"]
    ports: ["4000:4000"]
    environment:
      DATABASE_URL: postgresql://llm:llm-pass@db:5432/litellm
      LITELLM_MASTER_KEY: sk-master-lab-only
      LITELLM_SALT_KEY: sk-salt-lab-only
    volumes: ["./litellm-config.yaml:/app/config.yaml:ro"]
    depends_on: [db, ollama]
volumes: { ollama: {} }
```text
```bash
cd ~/labs/mlops/gw   # рядом — litellm-config.yaml из §3 (cache: type: local)
docker compose up -d && docker compose exec ollama ollama pull qwen2.5:0.5b
curl -s localhost:4000/health/readiness                       # БД подключена

# ключ: только local-chat, 3 запроса в минуту
KEY=$(curl -s localhost:4000/key/generate -H 'Authorization: Bearer sk-master-lab-only' \
  -H 'Content-Type: application/json' \
  -d '{"models":["local-chat"],"rpm_limit":3,"max_budget":0.01}' | jq -r .key)

for i in 1 2 3 4; do
  curl -s -o /dev/null -w "%{http_code}\n" localhost:4000/v1/chat/completions \
    -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
    -d '{"model":"local-chat","messages":[{"role":"user","content":"Что такое DevOps? Одной фразой."}]}'
done                                                           # 200 200 200 429

curl -s localhost:4000/v1/embeddings -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' -d '{"model":"local-embed","input":"тест"}'   # отказ: модели нет в ключе
curl -s -H "Authorization: Bearer $LITELLM_MASTER_KEY" localhost:4000/metrics/ | grep -E '^litellm_(total_tokens|spend)' | head
```text
**Проверь себя:** почему четвёртый запрос — 429, а эмбеддинг отклонён другой ошибкой? Откуда
шлюз взял цену локальной модели (`/key/info`)? Что будет с лимитом при двух контейнерах litellm
без Redis? Уборка: `docker compose down -v`.

---

## 12. Грабли

| Грабля | Что происходит | Как избежать |
|--------|----------------|--------------|
| Несколько реплик шлюза без Redis | Лимиты tpm/rpm фактически умножаются | Общий Redis для лимитов и кэша: `litellm_settings.cache: true` + `cache_params.type: redis`. Одного `router_settings.redis_host` мало — на v1.102.1 лимиты остались на каждую реплику (проверено: 6 из 6 при rpm 3) |
| Сменили `LITELLM_SALT_KEY` | Сохранённые в БД креды провайдеров не расшифровываются | Salt задаётся один раз, хранится в Vault |
| `…:main-stable` / `pip install litellm` без версии | Внезапные изменения; история с PyPI 24.03.2026 | Тег + digest, обновление через staging |
| Логирование промптов «для отладки» | ПДн в Loki/Tempo на месяцы | Метаданные без текста, opt-in, чистка в коллекторе |
| Fallback «локальная → внешняя» для команды с ПДн | Данные уходят за рубеж при сбое | Для таких ключей — только локальные модели |
| Сменили модель эмбеддингов без переиндексации | Поиск возвращает мусор | Версия модели в метаданных, полный reindex |
| Оператор не совпадает с классом индекса / IVFFlat на пустой таблице | Полный перебор или плохая точность | `vector_cosine_ops` ↔ `<=>`, `EXPLAIN`; IVFFlat — после загрузки |
| RAG проиндексировал всё, фильтр прав — «в промпте» | Утечка документов через ответы | ACL в метаданных и фильтр на этапе поиска |

---

## 💼 Как это в DevOps

- Шлюз к LLM — платформенный сервис, как Ingress или Vault: HA, мониторинг, бэкап БД,
  runbook «провайдер лёг» и «утёк ключ»; ключ команде — с владельцем, бюджетом, списком
  моделей и классом данных, хранится в Vault, отзывается за минуту.
- FinOps-отчёт по LLM — из метрик шлюза: деньги по командам, тренд, алерт на остаток бюджета
  и аномальный рост (скрипт в цикле видно за час, а не в конце месяца).
- Векторную базу начинают с pgvector в существующем PostgreSQL; к Qdrant переходят, упёршись
  в объём или задержку, — и тогда это отдельный сервис с on-call.
- На вопрос «можно ли отправить это в ChatGPT» правильный ответ девопса: «какой класс данных?
  вот политика, вот ключ с нужными моделями, вот контакт юриста».

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Поднять шлюз | LiteLLM + PostgreSQL, `LITELLM_MASTER_KEY`, `LITELLM_SALT_KEY`, `--config` |
| Подключить локальную модель | `model: ollama_chat/&lt;модель&gt;`, `api_base: http://ollama:11434` |
| Цена для локальной модели | `model_info.input_cost_per_token` / `output_cost_per_token` |
| Команда с бюджетом | `POST /team/new` с `models`, `max_budget`, `budget_duration`, `tpm_limit`, `rpm_limit` |
| Ключ сервиса | `POST /key/generate` с `team_id`, `models`, лимитами, `metadata` |
| Сколько потрачено | `GET /key/info?key=…`, `GET /team/info?team_id=…`, `litellm_spend_metric` |
| Fallback и кэш | `fallbacks: [{"a": ["b"]}]` (помни про данные); `cache: true`, `cache_params.type: redis` |
| Не логировать промпты | `turn_off_message_logging: true`, `store_prompts_in_spend_logs: false` |
| Метрики и трейсы | `callbacks: ["prometheus"]` → `/metrics`; атрибуты `gen_ai.provider.name`, `gen_ai.usage.*` |
| Векторы и индекс | `CREATE EXTENSION vector`; `vector(1024)`; `USING hnsw (embedding vector_cosine_ops)` + `maintenance_work_mem` |
| Бэкап Qdrant | `POST /collections/&lt;c&gt;/snapshots` на каждой ноде → S3 |

---

## 🧠 Что запомнить

1. ⭐ Шлюз к LLM даёт: один ключ провайдера, виртуальные ключи командам, бюджеты, tpm/rpm,
   fallback, кэш, учёт токенов и денег, журнал и контроль исходящих данных.
2. LiteLLM proxy: OpenAI-совместимый API, конфиг `model_list`; **PostgreSQL обязателен**
   для ключей и учёта, Redis — для лимитов и кэша на нескольких репликах.
3. Альтернативы: Agent Router (бывший Envoy AI Gateway, CRD поверх Envoy Gateway), Kong AI
   Gateway (лимиты по токенам — Enterprise), Portkey (MIT). ⚠️ Шлюз держит все ключи — образ
   по digest: компрометация `litellm` 1.82.7/1.82.8 на PyPI 24.03.2026 — реальный пример.
4. Fallback и кэш — решения и о данных: не выпускай ПДн наружу через fallback, не отдавай
   персональные ответы из семантического кэша.
5. ⭐ OTel GenAI conventions — Development: `gen_ai.provider.name` (вместо `gen_ai.system`),
   `gen_ai.usage.input_tokens/output_tokens`; тексты сообщений — opt-in, по умолчанию не логируй.
6. RAG = ingestion job + чанкинг + эмбеддинги + векторная БД + retrieval (+ rerank);
   модель эмбеддингов одна для индексации и запроса, смена = полная переиндексация.
7. ⭐ pgvector: HNSW по умолчанию, IVFFlat — после загрузки; оператор = класс индекса; индекс
   в RAM; `maintenance_work_mem` для построения; после `pg_restore` HNSW строится часами — это RTO.
8. Qdrant — когда pgvector мал: шарды, реплики, `write_consistency_factor`; снапшоты
   на каждой ноде и вывоз в S3 — твоя задача.
9. ⭐ Данные граждан РК во внешний API — по умолчанию нет; классификация, ключ с разрешёнными
   моделями, обезличивание, egress только через шлюз; правовые вопросы — уточни у юриста.
10. Стоимость = токены × цена; главный рычаг — входные токены (контекст RAG), кэш снижает
    счёт на долю попаданий, своя GPU-модель стоит денег и без нагрузки.

➡️ Дальше: [05_ml_pipelines.md](/mlops/05-ml-pipelines) · Лабы 3–4: [07_practice_labs.md](/mlops/07-practice-labs) · Задачи: 04_llm_gateway_rag_tasks.md


---

### Блок A. Теория


**A1.** ⭐ Перечисли, что даёт компании единый шлюз к LLM. Какие три пункта ты назовёшь первыми?

<details><summary>Ответ</summary>

Один ключ провайдера и виртуальные ключи командам, учёт токенов и денег, бюджеты
и лимиты tpm/rpm, ретраи и fallback, кэш, журнал запросов, контроль исходящих данных, единый
OpenAI-совместимый API. Первыми — ключи и отзыв, учёт денег с лимитами, контроль данных.

</details>

**A2.** Чем виртуальный ключ шлюза отличается от ключа провайдера? Почему ключ провайдера
не должен покидать шлюз?

<details><summary>Ответ</summary>

Виртуальный ключ выдаёт шлюз: у него свои модели, бюджет, лимиты, владелец, его можно
отозвать, не трогая провайдера. Ключ провайдера даёт доступ ко всему аккаунту и счёту;
если он у команд — нет ни учёта, ни быстрого отзыва, и растёт шанс утечки.

</details>

**A3.** Зачем LiteLLM proxy PostgreSQL? Что останется от шлюза без БД?

<details><summary>Ответ</summary>

Для виртуальных ключей, команд, пользователей, бюджетов и учёта трат (spend logs).
Без БД — только мастер-ключ и проксирование: ни ключей по командам, ни бюджетов.

</details>

**A4.** Что такое `LITELLM_MASTER_KEY` и `LITELLM_SALT_KEY`? Что будет, если сменить salt?

<details><summary>Ответ</summary>

Master key — админский ключ (создаёт команды и ключи, начинается с `sk-`). Salt key
шифрует креды провайдеров в БД. Сменишь salt — сохранённые креды не расшифруются, их придётся
вводить заново.

</details>

**A5.** ⭐ Зачем Redis, когда у шлюза несколько реплик?

<details><summary>Ответ</summary>

Лимиты tpm/rpm и кэш должны быть общими: без Redis у каждой реплики свой счётчик,
реальный лимит = лимит × реплики, а кэш у каждой свой (меньше попаданий).

</details>

**A6.** Чем отличаются `max_budget` + `budget_duration`, `tpm_limit` и `rpm_limit`? Что
из этого защищает от «скрипта в цикле», а что — от квоты провайдера?

<details><summary>Ответ</summary>

Бюджет — деньги за период со сбросом (защищает от «скрипта в цикле» и перерасхода
за месяц). `tpm_limit` — токены в минуту, `rpm_limit` — запросы в минуту: защищают от всплесков
и помогают не упереться в квоту провайдера (для неё же — `rpm`/`tpm` на уровне деплоя в `model_list`).

</details>

**A7.** Как в LiteLLM задать «цену» локальной модели и зачем это делать, если она бесплатна?

<details><summary>Ответ</summary>

`model_info.input_cost_per_token` / `output_cost_per_token`. Своя модель не бесплатна:
GPU, ноды, люди. «Внутренняя цена» позволяет применять бюджеты, делать showback и сравнивать
с внешним провайдером на одном дашборде.

</details>

**A8.** Чем `num_retries` отличается от `fallbacks`? Что такое `context_window_fallbacks`?

<details><summary>Ответ</summary>

`num_retries` повторяет запрос на тот же деплой; `fallbacks` переключает на другую модель
после ошибки или 429; `context_window_fallbacks` — на модель с большим окном, если промпт не влез.

</details>

**A9.** ⭐ Почему fallback — это решение не только о надёжности, но и о данных?

<details><summary>Ответ</summary>

Fallback меняет получателя данных: если локальная модель легла и запрос ушёл во внешний
API, данные, которые можно обрабатывать только локально, оказались у провайдера за рубежом.
Для таких ключей fallback наружу не настраивают.

</details>

**A10.** Точный и семантический кэш: как работают и чем опасен семантический?

<details><summary>Ответ</summary>

Точный — хеш модели и сообщений, ответ отдаётся при полном совпадении. Семантический —
по близости эмбеддингов вопроса: похожий вопрос получает сохранённый ответ. Опасен тем, что
«похожий» может быть вопросом другого клиента о его данных — чужой ответ.

</details>

**A11.** Назови альтернативы LiteLLM и одно ограничение или особенность каждой.

<details><summary>Ответ</summary>

Agent Router (бывший Envoy AI Gateway): CRD поверх Envoy Gateway, k8s-native; переименован
в сентябре 2026 — следить за документацией. Kong AI Gateway: лимиты по токенам только
в Enterprise. Portkey gateway: MIT, лёгкий; компанию купила Palo Alto Networks — следить
за дорожной картой. LiteLLM: нужен PostgreSQL, SSO и аудит — платно.

</details>

**A12.** Что случилось с пакетом `litellm` на PyPI 24.03.2026 и какой вывод из этого для
любого шлюза?

<details><summary>Ответ</summary>

Версии 1.82.7 и 1.82.8 около 40 минут содержали бэкдор: кража кредов, попытки
распространиться по Kubernetes, закрепление в системе. Токены публикации утекли через
скомпрометированный Trivy в CI проекта. Вывод: шлюз держит ключи ко всем провайдерам — пиннить
версию и digest, обновлять через staging, сканировать, ограничивать egress самого шлюза.

</details>

**A13.** Какие метрики LiteLLM отдаёт в Prometheus? Какой из них сразу сделать алерт?

<details><summary>Ответ</summary>

Токены (input/output/total), траты, запросы и ошибки, полная задержка и задержка провайдера,
TTFT, остаток бюджета команды и ключа. Алерт — на остаток бюджета и на аномальный рост трат.

</details>

**A14.** ⭐ Что такое OpenTelemetry GenAI semantic conventions? Какой у них статус и что это
значит на практике?

<details><summary>Ответ</summary>

Общий словарь атрибутов, метрик и событий для трейсов вызовов моделей, агентов, инструментов
и MCP. Статус Development: имена ещё меняются (`gen_ai.system` → `gen_ai.provider.name`,
замена `gen_ai.client.token.usage` на отдельные счётчики). На практике — фиксировать версию
в инструментации и дашбордах, читать release notes.

</details>

**A15.** Назови пять ключевых атрибутов `gen_ai.*` для спана вызова модели.

<details><summary>Ответ</summary>

`gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`,
`gen_ai.response.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
`gen_ai.response.finish_reasons` (+ `error.type`, `server.address`).

</details>

**A16.** Почему тексты промптов по умолчанию не логируют? Какими настройками это обеспечить
в шлюзе и в коллекторе?

<details><summary>Ответ</summary>

В промптах — ПДн и конфиденциальные данные; логи и трейсы хранятся долго, доступны многим
и часто уходят в SaaS. Шлюз: `turn_off_message_logging: true`, `callback_settings.otel.message_logging:
false`, `store_prompts_in_spend_logs: false`. Коллектор: `attributes`/`transform` удаляют
`gen_ai.input.messages`/`gen_ai.output.messages`.

</details>

**A17.** Что такое Langfuse и из каких компонентов состоит self-hosted установка?

<details><summary>Ответ</summary>

Open-source платформа трейсинга, оценки и промпт-менеджмента LLM-приложений (MIT, кроме `ee/`).
Self-hosted: web, worker, PostgreSQL, ClickHouse, Redis/Valkey, S3-хранилище. Актуальна v4.

</details>

**A18.** ⭐ Из каких инфраструктурных компонентов состоит RAG? Что из этого — зона девопса?

<details><summary>Ответ</summary>

Ingestion job, чанкинг, модель эмбеддингов (сервинг), векторная БД, retrieval-сервис,
опционально reranker, LLM через шлюз. Зона девопса: джобы и расписание, сервинг эмбеддингов,
эксплуатация БД (индексы, память, бэкапы), переиндексация, метрики и права доступа.

</details>

**A19.** Почему модель эмбеддингов должна быть одна при индексации и запросе? Что будет при смене модели?

<details><summary>Ответ</summary>

Векторы разных моделей живут в разных пространствах (и часто разной размерности): сравнивать
их бессмысленно. Смена модели = полная переиндексация, лучше как blue/green: новая таблица/коллекция,
переключение после проверки.

</details>

**A20.** Как размер чанка и top-k влияют на качество и на стоимость?

<details><summary>Ответ</summary>

Мелкие чанки точнее, но теряют контекст; крупные — наоборот. Каждый найденный чанк — входные
токены: top-k 10 вместо 4 может увеличить счёт на десятки процентов и замедлить ответ.

</details>

**A21.** ⭐ Чем HNSW отличается от IVFFlat? Какой брать по умолчанию и почему IVFFlat нельзя
строить на пустой таблице?

<details><summary>Ответ</summary>

HNSW — граф: лучше соотношение скорость/точность, дольше и дороже по памяти строится,
можно создать на пустой таблице. IVFFlat — кластеры: быстрее строится, хуже точность; центры
кластеров вычисляются из данных, поэтому строить его надо после загрузки. По умолчанию — HNSW.

</details>

**A22.** Зачем `maintenance_work_mem` при построении индекса pgvector? Как прикинуть размер
данных для 1 млн векторов размерности 1024?

<details><summary>Ответ</summary>

Построение HNSW быстрое, пока граф помещается в `maintenance_work_mem`; иначе резко
замедляется (сообщение «hnsw graph no longer fits into maintenance_work_mem»). 1 млн × 1024 × 4 байта
≈ 4 ГБ данных плюс индекс сопоставимого размера.

</details>

**A23.** Почему бэкап pgvector через `pg_dump` влияет на RTO?

<details><summary>Ответ</summary>

Дамп хранит только определение индекса, при восстановлении HNSW строится заново — на
миллионах строк это часы. Это время входит в RTO; для больших баз — физический бэкап и PITR.

</details>

**A24.** Когда стоит перейти с pgvector на Qdrant? Что при этом добавляется в эксплуатацию?

<details><summary>Ответ</summary>

Когда pgvector упирается в одну ноду: десятки миллионов векторов, жёсткие требования
к задержке, нужен шардинг. Добавляется отдельная система: бэкапы снапшотами на каждой ноде,
мониторинг, обновления, on-call, своя модель консистентности.

</details>

**A25.** Что такое `replication_factor` и `write_consistency_factor` в Qdrant?

<details><summary>Ответ</summary>

`replication_factor` — сколько копий у каждого шарда; `write_consistency_factor` — сколько
реплик должны подтвердить запись. Если живых реплик меньше фактора, запись падает.

</details>

**A26.** ⭐ Как технически исполнить правило «ПДн клиентов не уходят во внешний LLM»?

<details><summary>Ответ</summary>

Классификация данных у сервисов; ключ команды с ПДн разрешает только локальные модели
и не имеет fallback наружу; маскирование до шлюза или в нём; egress из подов только через шлюз;
условия провайдера — договором; правовой статус — у юриста.

</details>

**A27.** Как посчитать стоимость LLM-фичи? Что обычно главный рычаг?

<details><summary>Ответ</summary>

Σ (входные × цена входа + выходные × цена выхода) × (1 − hit rate кэша). Главный рычаг —
входные токены: системный промпт, история, контекст RAG.

</details>

---

### Блок B. «Что произойдёт»


```text:no-line-numbers
# B1 — два пода litellm за Service, Redis не настроен
```text
```text:no-line-numbers
# ключ: rpm_limit: 10; клиент шлёт 18 запросов в минуту
```text
Вопрос: сколько запросов пройдёт?

```text:no-line-numbers
# B2
```text
```text:no-line-numbers
model_list:
```text
```text:no-line-numbers
  - model_name: chat
```text
```text:no-line-numbers
    litellm_params: { model: ollama_chat/qwen2.5:0.5b, api_base: http://ollama:11434 }
```text
```text:no-line-numbers
  - model_name: chat-external
```text
```text:no-line-numbers
    litellm_params: { model: openai/&lt;модель&gt;, api_key: os.environ/OPENAI_API_KEY }
```text
```text:no-line-numbers
litellm_settings:
```text
```text:no-line-numbers
  fallbacks: [{"chat": ["chat-external"]}]
```text
```text:no-line-numbers
# команда support шлёт в "chat" обращения клиентов с ИИН; под ollama упал
```text
Вопрос: что произойдёт с данными?

```text:no-line-numbers
# B3 — ключ создан так:
```text
```text:no-line-numbers
{"models": ["local-chat"], "max_budget": 5}
```text
```text:no-line-numbers
# сервис вызывает model: "local-embed"
```text
Вопрос: что ответит шлюз?

```text:no-line-numbers
# B4
```text
```text:no-line-numbers
litellm_settings:
```text
```text:no-line-numbers
  cache: true
```text
```text:no-line-numbers
  cache_params: { type: redis-semantic, similarity_threshold: 0.8 }
```text
```text:no-line-numbers
# бот отвечает клиентам про статус ИХ заказов
```text
Вопрос: что может пойти не так?

```text:no-line-numbers
-- B5
```text
```text:no-line-numbers
CREATE INDEX ON chunks USING hnsw (embedding vector_l2_ops);
```text
```text:no-line-numbers
SELECT * FROM chunks ORDER BY embedding <=> $1 LIMIT 5;
```text
Вопрос: будет ли использован индекс?

```text:no-line-numbers
-- B6 — таблица пустая, данных ещё нет
```text
```text:no-line-numbers
CREATE INDEX ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```text
```text:no-line-numbers
-- потом загрузили 200 000 чанков
```text
Вопрос: что с качеством поиска и как правильно?

```text:no-line-numbers
-- B7 — HNSW, 50 000 чанков, из них у команды support 300
```text
```text:no-line-numbers
SELECT * FROM chunks WHERE team = 'support' ORDER BY embedding <=> $1 LIMIT 10;
```text
Вопрос: сколько строк вернётся и что настроить?

```text:no-line-numbers
B8 — индексация шла на bge-m3 (1024), вопрос эмбеддят nomic-embed-text (768)
```text
Вопрос: что произойдёт?

```text:no-line-numbers
B9 — pgvector: 3 млн чанков, HNSW; база упала, восстанавливают из pg_dump
```text
```text:no-line-numbers
RTO по договорённости — 1 час
```text
Вопрос: уложатся ли?

```text:no-line-numbers
B10 — Qdrant, 3 ноды, replication_factor: 2, write_consistency_factor: 2
```text
```text:no-line-numbers
одна нода упала; на ней была одна из двух реплик шарда 4
```text
Вопрос: что будет с записью в шард 4?

```text:no-line-numbers
# B11 — OTel-инструментация приложения
```text
```text:no-line-numbers
env:
```text
```text:no-line-numbers
  - { name: OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT, value: "true" }
```text
```text:no-line-numbers
# трейсы уходят в Tempo с retention 30 дней
```text
Вопрос: чем это опасно и что сделать? (Имя переменной у каждой инструментации своё — проверь.)

---

### Блок C. Практика


### C1. 🔑 Шлюз в compose
Пройди мини-лабу конспекта: PostgreSQL + Ollama + LiteLLM `v1.102.1` (проверь версию).
Проверь `/health/readiness`, вызови `local-chat` мастер-ключом и запиши TTFT и полное время ответа.

### C2. 🔑 Команды и ключи
Создай команды `support` (только `local-chat`, $1 на 7 дней, `rpm_limit: 5`) и `search`
(`local-chat` и `local-embed`, `tpm_limit: 2000`). Выпусти по ключу. Докажи тремя curl:
лимит rpm срабатывает, чужая модель запрещена, `/team/info` показывает расход.

### C3. Бюджет кончился
Поставь ключу `max_budget: 0.0001` и цену локальной модели из конспекта. Сколько запросов
пройдёт до `budget_exceeded`? Посчитай заранее по токенам из ответа (`usage`) и сравни с фактом.

### C4. Метрики
Открой `/metrics`, найди счётчики токенов и денег. Напиши PromQL: токены в минуту по командам,
деньги за час по ключам, p95 задержки. Объясни, откуда берётся разница между
`litellm_request_total_latency_metric` и `litellm_llm_api_latency_metric`.

### C5. 🔑 Промпты не в логах
Включи колбэк OTel на Collector из [../SRE/03_tracing_opentelemetry.md](/sre/03-tracing-opentelemetry)
с экспортером `debug`. Сравни спан с `turn_off_message_logging: false` и `true`: какие атрибуты
`gen_ai.*` есть, есть ли текст сообщения? Добавь в коллектор процессор, удаляющий
`gen_ai.input.messages` и `gen_ai.output.messages`.

### C6. 🔑 pgvector руками
Подними `pgvector/pgvector:0.8.6-pg17` (проверь тег), создай таблицу из конспекта, загрузи
**10.** 000 случайных векторов (`SELECT array_agg(random())::vector(1024) …` в `generate_series`).
Построй HNSW с `maintenance_work_mem = 64MB`, потом с `1GB` — сравни время и сообщения.
Проверь `EXPLAIN ANALYZE` запроса с правильным и неправильным оператором.
### C7. HNSW против IVFFlat
На тех же данных построй IVFFlat (`lists` по правилу из конспекта). Сравни время построения,
размер индекса (`pg_relation_size`) и время запроса при `ivfflat.probes` 1 и 10.

### C8. Qdrant и снапшот
Подними `qdrant/qdrant:v1.19.1`, создай коллекцию на 1024 измерения, залей 1 000 точек,
сделай снапшот, удали коллекцию и восстанови из снапшота. Запиши команды в runbook.

### C9. Расчёт стоимости
Сервис: 5 000 запросов/день, системный промпт 400 токенов, история диалога 800, RAG 5 чанков
по 250, ответ 200. Цены условные: $0,50 и $2 за 1M. Посчитай месяц. Потом: история
ограничена 300 токенами, hit rate кэша 20%. Во сколько раз изменился счёт?

### C10. Политика данных
Составь таблицу классов данных своей (или вымышленной) компании и для каждого — какие модели
разрешены, какой ключ выдаётся, какой fallback допустим. Отметь пункты «уточнить у юриста».

---

### Блок D. Инциденты


**D1.** Счёт провайдера за неделю вырос втрое. В шлюзе все ходят через виртуальные ключи.
Как найти виновника и остановить рост за 15 минут?

<details><summary>Ответ</summary>

Grafana/PromQL по `litellm_spend_metric` и токенам с разбивкой по `team` и `hashed_api_key`,
`/key/info` для подозрительного ключа. Остановить: временно снизить бюджет/`rpm_limit` ключа или
отключить его, связаться с владельцем. Потом — алерт на аномальный рост и бюджеты всем ключам.

</details>

**D2.** Утром все запросы к шлюзу падают с 5xx, `/health/liveliness` — OK, `/health/readiness` — нет.
Где искать?

<details><summary>Ответ</summary>

Readiness проверяет связь с БД: PostgreSQL недоступен, кончились соединения, сменился
пароль (ротация без обновления Secret), диск БД заполнен. Смотреть логи шлюза и БД.

</details>

**D3.** После обновления шлюза перестали работать ключи провайдеров, сохранённые через UI.
Что могло измениться?

<details><summary>Ответ</summary>

Сменился или не передан `LITELLM_SALT_KEY` (новый Secret, другой values) — креды в БД
не расшифровываются. Вернуть прежний salt из Vault.

</details>

**D4.** Команда жалуется: «лимит 60 rpm, а нас режут уже на 20». Гипотезы?

<details><summary>Ответ</summary>

Ограничение на уровне команды строже, чем у ключа; общий лимит деплоя (`rpm` в `model_list`)
делится между командами; ограничение провайдера (его 429 выглядит как лимит); неверные ожидания
про окно (лимит на минуту, а клиент шлёт пачками).

</details>

**D5.** Внешний провайдер отвечает 429 весь день, фича деградировала. Что сделать сейчас и что потом?

<details><summary>Ответ</summary>

Сейчас: fallback на другую модель или провайдера (если класс данных позволяет), снизить
параллелизм, кэш для повторяющихся запросов. Потом: запрос увеличения квоты, распределение
нагрузки по нескольким деплоям, лимиты на командах, чтобы одна не съедала квоту всех.

</details>

**D6.** Безопасность нашла в Loki тексты обращений клиентов с ИИН. Откуда они могли попасть
и что делать?

<details><summary>Ответ</summary>

Логирование сообщений в шлюзе, захват контента в OTel-инструментации, debug-логи приложения,
`store_prompts_in_spend_logs`. Выключить источник, удалить данные из Loki (или сократить retention),
оценить масштаб; это возможный инцидент с ПДн — подключить безопасность и юриста
([../Security/07_security_incidents_compliance.md](/security/07-security-incidents-compliance)).

</details>

**D7.** Поиск RAG стал возвращать нерелевантные куски после «небольшого обновления» сервиса
индексации. Что проверить?

<details><summary>Ответ</summary>

Не сменилась ли модель эмбеддингов или её версия, размерность, нормализация, чанкинг;
не смешались ли в базе векторы разных моделей; не поменялся ли оператор расстояния.

</details>

**D8.** Запросы к pgvector выросли с 20 мс до 2 с после того, как таблица выросла в 5 раз. Причины?

<details><summary>Ответ</summary>

Индекс перестал помещаться в RAM (чтение с диска), планировщик ушёл в Seq Scan (оператор,
фильтры, статистика — `ANALYZE`), индекс не перестроен после массовой загрузки, выросла конкурентность.

</details>

**D9.** RAG-бот ответил сотруднику цитатой из документа, к которому у него нет доступа. Что сломано
в архитектуре?

<details><summary>Ответ</summary>

Права проверяются не на этапе поиска: индексировали всё, а фильтра по ACL пользователя
в запросе к векторной БД нет. Нужны права в метаданных чанков и обязательный фильтр в retrieval.

</details>

**D10.** Нода Qdrant умерла вместе с диском, коллекция не восстанавливается. Что было не так
с бэкапами?

<details><summary>Ответ</summary>

Снапшоты лежали на диске той же ноды (или делались не на всех нодах), не было
`replication_factor` больше 1 и выгрузки снапшотов в S3; восстановление ни разу не проверяли.

</details>

---

### Блок E. Вопросы с собеседования


**1.** ⭐ Зачем компании LLM-шлюз? Что вы бы в него положили?

<details><summary>Ответ</summary>

Один ключ провайдера и виртуальные ключи командам, бюджеты и tpm/rpm, учёт денег, fallback,
   кэш, журнал и контроль того, какие данные уходят наружу.

</details>

**2.** Как вы считаете и ограничиваете траты на LLM по командам?

<details><summary>Ответ</summary>

Все вызовы через шлюз; `team` и ключ в метриках; бюджеты с периодом, алерт на остаток
   и на аномальный рост; «внутренняя цена» для локальных моделей.

</details>

**3.** ⭐ Как устроен fallback между провайдерами и какие у него риски?

<details><summary>Ответ</summary>

`fallbacks` в шлюзе по ошибкам и 429, cooldown для падающих деплоев; риски — другой получатель
   данных, другое качество ответов, каскадная нагрузка на запасной вариант.

</details>

**4.** Как вы наблюдаете LLM-вызовы? Какие метрики важны?

<details><summary>Ответ</summary>

Метрики шлюза (токены, деньги, задержка, TTFT, ошибки по командам и моделям), трейсы
   с атрибутами `gen_ai.*`, без текстов промптов по умолчанию.

</details>

**5.** Что такое OpenTelemetry GenAI conventions?

<details><summary>Ответ</summary>

Словарь OTel для LLM-вызовов: `gen_ai.operation.name`, `provider.name`, `usage.*`; статус
   Development — версии фиксируем.

</details>

**6.** ⭐ Как устроен RAG с точки зрения инфраструктуры?

<details><summary>Ответ</summary>

Ingestion job → чанки → эмбеддинги → векторная БД; запрос → эмбеддинг → top-k с фильтром прав
   → rerank → промпт → LLM через шлюз.

</details>

**7.** pgvector или отдельная векторная база?

<details><summary>Ответ</summary>

pgvector — пока хватает одной ноды Postgres и команда умеет его эксплуатировать; отдельная
   база — при десятках миллионов векторов и требованиях к задержке и шардированию.

</details>

**8.** ⭐ Как эксплуатировать pgvector: индексы, память, бэкапы?

<details><summary>Ответ</summary>

HNSW по умолчанию, оператор = класс индекса, индекс в RAM, `maintenance_work_mem` при построении,
   физические бэкапы для больших баз, мониторинг размера индекса и задержки поиска.

</details>

**9.** ⭐ Какие данные можно отправлять во внешний LLM-API?

<details><summary>Ответ</summary>

По классам данных: публичное — можно, ПДн — по умолчанию нет, только по решению юриста
   и после обезличивания; секреты — никогда. Техника — ключи с разрешёнными моделями и egress
   через шлюз.

</details>

**10.** Как оценить стоимость LLM-фичи до запуска?

<details><summary>Ответ</summary>

Токены на запрос (вход и выход) × запросы × цены, отдельно контекст RAG и история;
    кэш и лимиты истории; сравнить с локальной моделью по стоимости GPU-часа.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Объясняю, зачем компании LLM-шлюз, и называю его функции
- [ ] Поднимал LiteLLM с PostgreSQL и локальной моделью
- [ ] ⭐ Выпускал ключи командам с бюджетами и tpm/rpm, видел 429 и `budget_exceeded`
- [ ] Знаю, зачем Redis при нескольких репликах шлюза
- [ ] Понимаю, почему fallback и кэш — решения о данных
- [ ] Читаю метрики шлюза и пишу PromQL по токенам и деньгам
- [ ] ⭐ Знаю ключевые атрибуты OTel GenAI и их статус; промпты не попадают в логи
- [ ] Раскладываю RAG на компоненты и называю зону девопса
- [ ] ⭐ Строил HNSW и IVFFlat в pgvector, знаю про память, оператор и бэкапы
- [ ] Делал и восстанавливал снапшот Qdrant
- [ ] ⭐ Объясняю, какие данные нельзя отправлять во внешний API, и как это исполнить технически
- [ ] Считаю стоимость LLM-фичи и знаю главные рычаги
