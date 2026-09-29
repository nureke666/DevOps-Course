---
title: "03. Сервинг моделей: vLLM, llama.cpp, Ollama, KServe, холодный старт, метрики, автоскейлинг"
description: "Блок → AI/MLOps-инфраструктура → тема 03. Самая частая задача девопса в ML —"
---

# 03. Сервинг моделей: vLLM, llama.cpp, Ollama, KServe, холодный старт, метрики, автоскейлинг

> Блок → [AI/MLOps-инфраструктура](/mlops/) → тема 03. Самая частая задача девопса в ML —
> «выкатите модель». Это Deployment, но с образом на 10 ГБ, моделью на десятки ГБ, стартом в минуты
> и метриками, которых нет у обычного сервиса.
> Вопросы собеса: *«Чем вы сервите LLM?»*, *«Как бороться с холодным стартом?»*, *«По какой
> метрике скейлить инференс?»*, *«Что такое TTFT?»*
>
> **После темы ты умеешь:** выбрать сервер модели под задачу; объяснить, почему OpenAI-совместимый
> API стал стандартом; хранить и доставлять модель (PVC, init-контейнер из S3/MinIO, OCI);
> бороться с холодным стартом; объяснить continuous batching и квантизацию; снимать TTFT, tokens/s
> и очередь; скейлить по очереди, а не по CPU; настроить пробы для долгой загрузки; поднять модель
> на CPU в kind за Gateway API и замерить её. Версии — «проверь, сентябрь 2026».

---

## 🗺️ Карта темы

```text
 клиент (OpenAI SDK, curl)                                 модель: S3/MinIO, HF, OCI-образ
   │ POST /v1/chat/completions  (stream: SSE)                  │ init-контейнер / PVC-кэш / image volume
   ▼                                                           ▼
 Gateway (Envoy) ─ HTTPRoute ─► Service ─► Pod: сервер модели (vLLM / llama.cpp / Ollama)
   │   или InferencePool + Endpoint Picker                    │  веса в памяти GPU/RAM + KV-кэш
   │   (маршрут по загрузке KV-кэша, очереди)                 │  continuous batching
   ▼                                                           ▼  /metrics: TTFT, tokens/s, очередь
 LLM-шлюз компании (ключи, лимиты, учёт) — тема 04        Prometheus ──► KEDA ──► реплики 0…N
                                                                        (по очереди, не по CPU)
 Над всем этим может стоять KServe: InferenceService = образ + модель + скейлинг + canary одним CRD
```text
---

## 1. Чем сервить: варианты

| Сервер (проверь, сентябрь 2026) | Где работает | Сильные стороны | Для девопса важно |
|---------------------------------|--------------|-----------------|-------------------|
| ⭐ **vLLM** v0.30.0 (22.09.2026) | NVIDIA GPU (образ по умолчанию — CUDA 13.0), ROCm, Intel XPU, **CPU** (`vllm/vllm-openai-cpu`) | Де-факто стандарт для GPU: PagedAttention, continuous batching, prefix caching (включён по умолчанию), богатые метрики `vllm:*` | Образ 8–15 ГБ; по умолчанию занимает **92% памяти GPU** (`--gpu-memory-utilization 0.92`) |
| **SGLang** v0.5.20 | GPU | Альтернатива vLLM, сильна на структурированном выводе и агентах | Похожая модель эксплуатации |
| ⭐ **llama.cpp** `llama-server` (сборка b11206) | CPU, GPU (CUDA, Vulkan…), модели GGUF | Лёгкий, OpenAI API, `/metrics`, слоты и continuous batching | Лучший вариант для CPU и стенда |
| **Ollama** v0.34.4 (23.09.2026) | CPU, GPU, Apple | Проще всех: `ollama pull`, свой API + OpenAI `/v1` | По умолчанию **1 параллельный запрос** на модель, контекст 4096; встроенных Prometheus-метрик нет — это dev-инструмент |
| **Triton Inference Server** 2.72.0 (NGC 26.08) | GPU, CPU | Много фреймворков (TensorRT, ONNX, PyTorch, Python), ансамбли | Классическое ML и смешанные нагрузки |
| ~~TGI~~ (Hugging Face) | — | **Режим поддержки**, репозиторий в архиве (последний релиз v3.3.7, 12.2025) | Для новых проектов HF сам советует vLLM/SGLang |
| **KServe** v0.21.0 (25.09.2026) | Control plane над серверами | CRD `InferenceService` (runtime `huggingface` на vLLM), `LLMInferenceService` на базе llm-d, `storageUri` `hf://`, `s3://`, `oci://`, canary, KEDA | Платформа «модель одним манифестом» |
| **llm-d** v0.9.0 (CNCF sandbox), **NVIDIA Dynamo** v1.5.0 | Распределённый инференс | Маршрутизация по KV-кэшу, разделение prefill/decode | Большие модели и большой трафик |

**Как выбирать:** GPU и прод → vLLM (или SGLang); CPU, стенд, edge → llama.cpp; ноутбук разработчика →
Ollama; зоопарк классических моделей → Triton; много команд и моделей → KServe поверх vLLM.

---

## 2. ⭐ OpenAI-совместимый API — общий язык

vLLM, llama.cpp, Ollama, SGLang, KServe и почти все облачные провайдеры отдают один и тот же API:

| Эндпоинт | Что делает |
|----------|------------|
| `POST /v1/chat/completions` | Чат: `messages`, `max_tokens`, `temperature`, `stream: true` (SSE), tools |
| `POST /v1/completions` | «Сырое» продолжение текста |
| `POST /v1/embeddings` | Эмбеддинги для RAG ([04](/mlops/04-llm-gateway-rag)) |
| `GET /v1/models` | Какие модели обслуживает сервер |

```bash
curl -s http://llm:8080/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5-0.5b","messages":[{"role":"user","content":"Привет!"}],"max_tokens":50}' | jq .usage
# {"prompt_tokens": 31, "completion_tokens": 12, "total_tokens": 43}
```text
Что это даёт: приложение пишется **один раз** на OpenAI SDK, а бэкенд (провайдер, vLLM, llama.cpp)
меняется заменой `base_url` — через шлюз ([04](/mlops/04-llm-gateway-rag)) и без релиза кода. Что проверить:
- **имя модели** в запросе — `--served-model-name` у vLLM, `--alias` у llama.cpp: зафиксируй его,
  чтобы смена файла модели не ломала клиентов;
- **аутентификация**: у vLLM и llama.cpp есть `--api-key`, Ollama ключ игнорирует — доступ закрывают
  на шлюзе и NetworkPolicy, а не надеются на сервер;
- поддержка параметров и tool calls **различается** между серверами — «совместимый» не значит «идентичный».

> 💡 Проверено на llama.cpp b11206 (проект 22-oracle): с `--api-key` `/health` остаётся публичным (удобно для проб), а `/metrics` требует ключ. Без `-t` сервер берёт физические ядра (6 из 12 потоков), без `-c`/`-np` — 4 слота по 32768 токенов контекста, что на CPU-стенде съедает память: задавай их явно.

---

## 3. ⭐ Хранение и доставка модели

| Способ | Как | Плюсы | Минусы |
|--------|-----|-------|--------|
| Скачивать при старте с Hugging Face | vLLM сам качает в `HF_HOME` | Проще некуда | Интернет из прода, лимиты HF, токен для закрытых моделей, каждый старт — заново |
| ⭐ **Init-контейнер из S3/MinIO → PVC/emptyDir** | `mcli cp` / `aws s3 cp` / `hf download` в том | Модель во внутреннем хранилище, версия = путь | Время скачивания при каждом новом поде (с emptyDir) |
| ⭐ **PVC-кэш** (RWX: NFS, EFS, CephFS) | Job один раз кладёт модель, поды монтируют read-only | Старт без скачивания, общий на все реплики | Скорость сетевого диска = скорость загрузки весов |
| **OCI-образ с моделью** | KServe **ModelCar** (`storageUri: oci://…`); Kubernetes **image volume** (`volumes[].image`, **GA в 1.36**) | Кэш образов на ноде, реестр, подпись, те же права | Ещё один большой артефакт в реестре; нужен containerd с поддержкой |
| Запечь в образ сервинга | `COPY model/` | Для крошечных моделей | ⚠️ Антипаттерн для LLM ([01](/mlops/01-ml-systems-for-devops) §11) |

```yaml
# фрагмент пода: модель из MinIO (стенд — форк pgsty/silo, ../Storage/03_nfs_minio.md §3–5) или S3
initContainers:
  - name: fetch-model
    image: amazon/aws-cli:2.37.4                            # S3-клиент; тег проверь
    command: ["sh", "-c"]
    args:
      - test -s /models/model.gguf && exit 0;               # уже в кэше — не качаем
        aws s3 cp --endpoint-url "$S3_URL" s3://models/qwen2.5-0.5b/v1/model.gguf /models/model.gguf
    envFrom: [{ secretRef: { name: model-store } }]         # AWS_ACCESS_KEY_ID/SECRET — из Vault/ESO
    volumeMounts: [{ name: models, mountPath: /models }]
---
# вариант с image volume (Kubernetes 1.36+): модель — отдельный OCI-образ, монтируется read-only
volumes:
  - name: models
    image: { reference: registry.example.com/models/qwen2.5-0.5b:1.0, pullPolicy: IfNotPresent }
```text
> 💡 У `huggingface_hub` 2.0 (24.09.2026) удалена команда `huggingface-cli` — только `hf download`.
> Старые скрипты init-контейнеров с `huggingface-cli download` сломаются при обновлении образа.

---

## 4. ⭐ Холодный старт и как с ним бороться

```text
 новый под на новой ноде (самый плохой случай):
   нода из пула (ВМ + драйвер GPU)   1–5 мин   ← тема 02 §4, §9
 + pull образа сервинга 8–15 ГБ      1–5 мин
 + скачивание модели                 от секунд до десятков минут (размер / скорость сети)
 + загрузка весов в память GPU/RAM   секунды–минуты
 + прогрев (CUDA graphs, компиляция) секунды–минуты
 = первый токен через 5–30 минут — порядок величины, меряй у себя
```text
| Мера | Что срезает |
|------|-------------|
| Минимум реплик > 0 в рабочие часы (cron-триггер KEDA) | Весь холодный старт для пользователей |
| Образ ноды с драйвером, предзагрузка образа (DaemonSet «pre-puller»), ленивое скачивание образов (SOCI в AWS, image streaming в GKE) | Драйвер и pull |
| PVC-кэш / image volume вместо скачивания | Скачивание модели |
| Быстрое хранилище рядом с нодой (локальный NVMe, тот же регион/зона S3) | Скачивание и загрузку весов |
| Квантизованная модель меньшего размера (§6) | Всё, что зависит от размера |
| Запас «тёплой» ёмкости: overprovisioning-поды с низким PriorityClass | Ожидание новой ноды |
| Кэш весов у самого сервера (в vLLM 0.30 — демон кэша весов в памяти GPU, `--load-format ipc_cache`; проверь зрелость) | Повторную загрузку при рестарте движка |

### Пробы для долгой загрузки

```yaml
startupProbe:              # ⭐ пока модель грузится, liveness и readiness не проверяются
  httpGet: { path: /health, port: 8080 }  # llama-server: 503 «Loading model» → 200 {"status":"ok"}
  periodSeconds: 10
  failureThreshold: 60     # до 10 минут на загрузку — подбери по замеру
readinessProbe:            # готов принимать трафик
  httpGet: { path: /health, port: 8080 }
  periodSeconds: 10
livenessProbe:             # ⚠️ лёгкая и терпеливая: длинная генерация не должна считаться «зависанием»
  httpGet: { path: /health, port: 8080 }
  periodSeconds: 30
  timeoutSeconds: 10
  failureThreshold: 5
```text
У vLLM — те же `/health` и порт 8000. Основы проб — [../Kubernetes/09_probes_resources.md](/kubernetes/09-probes-resources) §1–4.
Без `startupProbe` liveness убьёт под на середине загрузки весов — и так по кругу (`CrashLoopBackOff`).

---

## 5. ⭐ Батчинг: почему один GPU обслуживает десятки запросов

Генерация идёт **токен за токеном**: каждый шаг — проход по всем весам модели. Узкое место —
чтение весов из памяти, поэтому обработать за шаг 32 запроса почти так же дёшево, как один.

```text
 статический батчинг:   [A A A A A A A A]  ждём, пока допишет самый длинный ответ,
                        [B B B . . . . .]  освободившиеся места простаивают,
                        [C C C C C . . .]  новые запросы ждут следующего батча

 ⭐ continuous batching: на каждом шаге готовые запросы уходят, новые встают на их место
                        [A A A A A A A A]
                        [B B B D D D D E]   ← D и E зашли, как только освободилось место
                        [C C C C C F F F]
```text
| Сервер | Параллелизм | Что крутить |
|--------|-------------|-------------|
| vLLM | Continuous batching + PagedAttention (KV-кэш блоками, без фрагментации) | `--max-num-seqs`, `--max-model-len`, `--gpu-memory-utilization` |
| llama.cpp | Слоты (`-np`), continuous batching включён по умолчанию | `-np N` — N одновременных запросов; контекст `-c` делится между слотами |
| Ollama | `OLLAMA_NUM_PARALLEL` (**по умолчанию 1**), очередь `OLLAMA_MAX_QUEUE` (512, дальше — 503) | Память растёт как `NUM_PARALLEL × CONTEXT_LENGTH` |

**Память под KV-кэш — пример расчёта** (Llama-3.1-8B: 32 слоя, 8 KV-голов, размер головы 128, FP16):
`2 (K и V) × 32 × 8 × 128 × 2 байта ≈ 128 КиБ на токен` → контекст 8K ≈ **1 ГиБ на один запрос**.
16 одновременных запросов по 8K — ещё ~16 ГиБ поверх 16 ГБ весов. Вот почему «модель влезла» ≠
«сервис выдержит нагрузку», и почему vLLM сразу резервирует почти всю память GPU.

---

## 6. Квантизация: память против качества

| Формат | Байт на параметр | Где | Компромисс |
|--------|------------------|-----|------------|
| FP16 / BF16 | 2 | Любые GPU; BF16 на CPU для vLLM | Эталон качества |
| FP8 | 1 | GPU Hopper (H100) и новее | Почти без потерь, вдвое меньше памяти |
| INT8 (GGUF `Q8_0`) | ~1 | GPU, CPU | Потери обычно малы |
| INT4 (AWQ, GPTQ для GPU; GGUF `Q4_K_M` для llama.cpp) | ~0,5–0,6 | GPU, CPU | Вчетверо меньше FP16; качество падает заметнее, особенно у малых моделей |

Правила большого пальца (проверяй на своём eval-наборе, [01](/mlops/01-ml-systems-for-devops) §5):
`Q4_K_M` — популярный баланс для llama.cpp; для малых моделей (0,5–3B) квантизация бьёт по качеству
сильнее, чем для больших; квантизованная большая модель часто лучше неквантизованной маленькой того же размера.

---

## 7. ⭐ Метрики LLM-сервинга

| Метрика | Что это | Почему важна |
|---------|---------|--------------|
| **TTFT** (time to first token) | От запроса до первого токена: очередь + prefill (обработка промпта) | То, что пользователь ощущает как «тормозит» |
| **ITL / TPOT** (inter-token latency) | Время между токенами при генерации | «Скорость печати» ответа |
| E2E latency | Весь ответ | ≈ TTFT + ITL × число выходных токенов |
| **Tokens/s** | На запрос и на весь сервер (throughput) | Ёмкость: сколько пользователей выдержит реплика |
| **Очередь** | Сколько запросов ждёт свободного места в батче | ⭐ Главный сигнал для автоскейлинга |
| KV-кэш | Заполненность памяти под контекст | Близко к 100% — вытеснения и очередь |
| GPU/CPU | Загрузка устройства | Тема 02 §8; для скейлинга — плохой сигнал |

| | vLLM (`/metrics`, порт 8000) | llama.cpp (`/metrics`, нужен флаг `--metrics`) |
|---|------------------------------|-----------------------------------------------|
| Очередь | `vllm:num_requests_waiting` | `llamacpp:requests_deferred` |
| В работе | `vllm:num_requests_running` | `llamacpp:requests_processing` |
| TTFT | `vllm:time_to_first_token_seconds` (histogram) | — (есть `timings.prompt_ms` в ответе) |
| Между токенами | `vllm:inter_token_latency_seconds` | — (`timings.predicted_per_token_ms`) |
| Токены | `vllm:prompt_tokens_total`, `vllm:generation_tokens_total` | `llamacpp:prompt_tokens_total`, `llamacpp:tokens_predicted_total` |
| Скорость | из счётчиков через `rate()` | `llamacpp:predicted_tokens_seconds` (средняя, gauge) |
| KV-кэш | `vllm:kv_cache_usage_perc` | `llamacpp:n_busy_slots_per_decode` (косвенно) |
| Время в очереди / E2E | `vllm:request_queue_time_seconds`, `vllm:e2e_request_latency_seconds` | — |

```promql
histogram_quantile(0.95, sum by (le) (rate(vllm:time_to_first_token_seconds_bucket[5m])))   # TTFT p95
sum(rate(vllm:generation_tokens_total[5m]))                                                 # токенов/с на сервис
sum(vllm:num_requests_waiting)                                                              # очередь
```text
SLO формулируют в этих терминах (пример, не стандарт): «TTFT p95 < 2 с, ITL p95 < 100 мс» —
[../SRE/02_sli_slo_error_budget.md](/sre/02-sli-slo-error-budget). Стоимость ответа =
GPU-секунды (или токены провайдера) на запрос — [../FinOps/01_finops_intro.md](/finops/01-finops-intro) §4.

---

## 8. ⭐ Автоскейлинг: по очереди, а не по CPU

**Почему HPA по CPU бесполезен:** на GPU-сервинге CPU почти не загружен — нагрузка растёт на GPU,
а HPA молчит. На CPU-сервинге (llama.cpp) наоборот: **один** запрос занимает все выделенные потоки,
CPU = 100% и при одном пользователе, и при ста. Правильный сигнал — **очередь** (и задержка).

```yaml
# KEDA 2.21 (../Kubernetes/25_ecosystem.md §6): скейлинг сервинга по очереди из Prometheus
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata: { name: llm, namespace: llm }
spec:
  scaleTargetRef: { name: llm }
  minReplicaCount: 1                   # 0 — только если клиенты переживут холодный старт (§4)
  maxReplicaCount: 4
  cooldownPeriod: 300
  advanced:
    horizontalPodAutoscalerConfig:
      behavior: { scaleDown: { stabilizationWindowSeconds: 600 } }   # не гасить реплику, прогретую 5 минут назад
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus-kube-prometheus-prometheus.monitoring:9090
        query: sum(llamacpp:requests_deferred{namespace="llm"})       # для vLLM — vllm:num_requests_waiting
        threshold: "2"                 # 2 ждущих запроса на реплику
        activationThreshold: "0"
```text
| Scale-to-zero | Когда да | Когда нет |
|---------------|----------|-----------|
| ✅ | Батч-инференс из очереди, dev/stage, редкие внутренние инструменты | — |
| ⚠️ | — | Пользовательский чат: первый запрос после нуля ждёт минуты (§4); у Service нет буфера |

Для HTTP со scale-to-zero нужен буфер запросов: **KEDA HTTP add-on** (v0.16.0, статус beta) или
очередь перед моделью. В Kubernetes 1.37 **HPA умеет scale-to-zero** (beta, включено по умолчанию,
только с object/external-метриками) — но буфера оно тоже не даёт. На стенде блока (1.36) — KEDA.
Полная лаба «скейлинг по очереди и засыпание» — лаба 2 в [07_practice_labs.md](/mlops/07-practice-labs).

---

## 9. Маршрутизация: почему round-robin плох для LLM

Запросы к LLM различаются в сотни раз: «привет» и «перескажи 30 страниц» стоят совершенно по-разному.
Round-robin Service/Envoy отправит тяжёлый запрос на уже забитую реплику, пока соседняя простаивает;
к тому же реплика, у которой в KV-кэше уже есть общий префикс промпта, ответит быстрее.

**Gateway API Inference Extension** (kubernetes-sigs, v1.6.2, 17.09.2026):
- **InferencePool** (`inference.networking.k8s.io/v1`) — группа подов с моделью; HTTPRoute ссылается
  на неё как на backend вместо Service;
- **Endpoint Picker (EPP)** — ext-proc-сервис рядом с Envoy, который для каждого запроса выбирает под
  по очереди, заполненности KV-кэша и префиксу; с v1.6 полноценный EPP живёт в проекте **llm-d**
  (`llm-d-router`), в самом расширении — API InferencePool, лёгкий EPP для conformance-тестов и тесты;
- реализации шлюза: Envoy Gateway (через Envoy AI Gateway), kgateway, GKE Gateway — проверь документацию своей.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata: { name: llm, namespace: llm }
spec:
  parentRefs: [{ name: web, namespace: infra }]
  rules:
    - backendRefs:
        - { group: inference.networking.k8s.io, kind: InferencePool, name: qwen-pool }   # вместо Service
```text
> 💡 На одной-двух репликах разницы не заметишь; Inference Extension окупается на десятках реплик
> GPU-сервинга. На стенде блока — обычный HTTPRoute → Service.

---

## 10. KServe: модель одним манифестом

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata: { name: qwen-llm, namespace: kserve-test }
spec:
  predictor:
    model:
      modelFormat: { name: huggingface }         # runtime на vLLM (fallback — transformers)
      args: ["--model_name=qwen"]
      storageUri: "hf://Qwen/Qwen2.5-0.5B-Instruct"   # или s3://…, pvc://…, oci://… (ModelCar)
      resources:
        requests: { cpu: "1", memory: 4Gi, nvidia.com/gpu: "1" }
        limits:   { cpu: "2", memory: 6Gi, nvidia.com/gpu: "1" }
# OpenAI API: http://qwen-llm.kserve-test/openai/v1/chat/completions
```text
KServe берёт на себя: storage initializer (скачивание по `storageUri`), Deployment и Service, маршрут,
canary (`canaryTrafficPercent`), автоскейлинг (в т.ч. KEDA). Для GenAI документация рекомендует режим
**Standard** (без Knative). Для распределённого инференса — отдельный CRD `LLMInferenceService`
(v1alpha2, на базе llm-d и InferencePool). ModelCar (`oci://`) включается в ConfigMap `inferenceservice-config`
(`storageInitializer.enableModelcar: true`); тег модели — конкретный, не `latest`, иначе кэш ноды не работает.
Путь «модель из registry → InferenceService через CI» — тема [05](/mlops/05-ml-pipelines).

---

## 🧪 Мини-лаба: модель на CPU в kind за Gateway API

**Цель:** llama.cpp с `qwen2.5:0.5b` (GGUF Q4_K_M, 491 МБ) в kind: PVC-кэш, init-контейнер, пробы,
HTTPRoute через Envoy Gateway, вызов по OpenAI API, замер TTFT и tokens/s, метрики.
Подготовка: кластер со стенда блока и Envoy Gateway + Gateway `web` в `infra` из
[../Kubernetes/12_ingress.md](/kubernetes/12-ingress) §7.2–7.3.

```bash
kind create cluster --name ml --image kindest/node:v1.36.4
helm install eg oci://docker.io/envoyproxy/gateway-helm --version v1.9.1 -n envoy-gateway-system --create-namespace
# + GatewayClass eg и Gateway web (ns infra, allowedRoutes по метке gateway-access=true) — из 12_ingress §7.3
kubectl create ns llm && kubectl label ns llm gateway-access=true
```text
```yaml
# llm.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: models, namespace: llm }
spec: { accessModes: [ReadWriteOnce], resources: { requests: { storage: 2Gi } } }   # kind: StorageClass standard
---
apiVersion: apps/v1
kind: Deployment
metadata: { name: llm, namespace: llm }
spec:
  replicas: 1
  strategy: { type: Recreate }          # RWO-том не смонтировать двум подам на разных нодах
  selector: { matchLabels: { app: llm } }
  template:
    metadata: { labels: { app: llm } }
    spec:
      initContainers:
        - name: fetch-model
          image: curlimages/curl:8.22.0                 # тег проверь
          securityContext: { runAsUser: 0 }             # только стенд: писать в том local-path; в проде — права тома
          command: ["sh", "-c", "test -s /models/model.gguf || curl -fL -o /models/model.gguf https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"]
          volumeMounts: [{ name: models, mountPath: /models }]
      containers:
        - name: server
          image: ghcr.io/ggml-org/llama.cpp:server-b11206   # пин сборки; проверь свежий тег
          args: ["-m", "/models/model.gguf", "--alias", "qwen2.5-0.5b", "--host", "0.0.0.0", "--port", "8080",
                 "-c", "4096", "-np", "2", "-t", "2", "--metrics"]
          ports: [{ name: http, containerPort: 8080 }]
          resources: { requests: { cpu: "2", memory: 1Gi }, limits: { memory: 2Gi } }
          startupProbe:   { httpGet: { path: /health, port: http }, periodSeconds: 5, failureThreshold: 60 }
          readinessProbe: { httpGet: { path: /health, port: http }, periodSeconds: 10 }
          volumeMounts: [{ name: models, mountPath: /models, readOnly: true }]
      volumes: [{ name: models, persistentVolumeClaim: { claimName: models } }]
---
apiVersion: v1
kind: Service
metadata: { name: llm, namespace: llm, labels: { app: llm } }
spec: { selector: { app: llm }, ports: [{ name: http, port: 80, targetPort: http }] }
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata: { name: llm, namespace: llm }
spec:
  parentRefs: [{ name: web, namespace: infra, sectionName: http }]
  hostnames: ["llm.example.com"]
  rules:
    - backendRefs: [{ name: llm, port: 80 }]
      timeouts: { request: 300s }       # длинные ответы не должны резаться
```text
```bash
kubectl apply -f llm.yaml
kubectl -n llm get pods -w                      # Init → Running, READY 0/1 → 1/1 (startupProbe)
kubectl -n llm logs deploy/llm -c fetch-model   # скачивание; при рестарте пода — пропуск (кэш на PVC)

export ENVOY_SERVICE=$(kubectl get svc -n envoy-gateway-system \
  --selector=gateway.envoyproxy.io/owning-gateway-namespace=infra,gateway.envoyproxy.io/owning-gateway-name=web \
  -o jsonpath='{.items[0].metadata.name}')
kubectl -n envoy-gateway-system port-forward service/${ENVOY_SERVICE} 8888:80 &

curl -s -H "Host: llm.example.com" localhost:8888/v1/models | jq '.data[].id'     # через Gateway
curl -s -H "Host: llm.example.com" localhost:8888/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5-0.5b","messages":[{"role":"user","content":"Что такое Kubernetes Service? 3 предложения."}]}' |
  jq '{answer: .choices[0].message.content, usage, prefill_ms: .timings.prompt_ms, tok_s: .timings.predicted_per_second}'
```text
```python
# ttft.py — python -m venv .venv && . .venv/bin/activate && pip install openai
# ходит прямо в Service: kubectl -n llm port-forward svc/llm 8081:80 &
import time
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8081/v1", api_key="no-key")
t0, first, chunks = time.perf_counter(), None, 0
stream = client.chat.completions.create(
    model="qwen2.5-0.5b", stream=True, max_tokens=200,
    messages=[{"role": "user", "content": "Объясни Kubernetes Deployment в 5 предложениях."}])
for chunk in stream:
    if chunk.choices and chunk.choices[0].delta.content:
        first = first or time.perf_counter()
        chunks += 1                                   # 1 чанк ≈ 1 токен (приближённо)
end = time.perf_counter()
print(f"TTFT {first - t0:.2f} с | ~{chunks / (end - first):.1f} токен/с | всего {end - t0:.1f} с")
```text
```bash
kubectl -n llm port-forward svc/llm 8081:80 &
python ttft.py                                        # 1 запрос: базовые TTFT и tokens/s
for i in $(seq 6); do python ttft.py & done; wait     # 6 запросов на 2 слота: TTFT растёт — очередь
curl -s localhost:8081/metrics | grep -E "requests_(deferred|processing)|tokens_predicted_total|predicted_tokens_seconds"
```text
**Шаг 2 — метрики в Prometheus.** С kube-prometheus-stack
([../Left/02_Monitoring/11_long_term_and_operator.md](/monitoring/11-long-term-and-operator) §7)
создай ServiceMonitor на Service `llm` (порт `http`, путь `/metrics`, метка `release: prometheus` — §9 той
темы) и построй в Grafana `rate(llamacpp:tokens_predicted_total[1m])` и `llamacpp:requests_deferred`.

**Шаг 3 — холодный старт.** `kubectl -n llm delete pod -l app=llm` и засеки время до READY 1/1 (модель
уже на PVC). Затем удали PVC и повтори — сколько добавило скачивание?

**Проверь себя:** почему `strategy: Recreate`? Что будет с 6 параллельными запросами при `-np 1`
и `-np 4` при тех же 2 CPU? Уборка: `kind delete cluster --name ml`.

---

## 11. Грабли

| Грабля | Что происходит | Как избежать |
|--------|----------------|--------------|
| Нет `startupProbe` | Liveness убивает под посреди загрузки весов — `CrashLoopBackOff` | startupProbe с запасом по времени загрузки |
| Строгая liveness с коротким таймаутом | Под убивают во время длинной генерации | Лёгкая `/health`, `timeoutSeconds` и `failureThreshold` с запасом |
| HPA по CPU | На GPU не скейлится; на CPU — «100%» при одном запросе | KEDA по очереди (`num_requests_waiting` / `requests_deferred`) |
| Scale-to-zero для чата | Первый пользователь утром ждёт минуты или получает 503 | min 1 в рабочие часы, HTTP add-on или очередь |
| Ollama в проде «как есть» | 1 параллельный запрос, нет метрик, контекст 4096 | vLLM / llama.cpp, или хотя бы `OLLAMA_NUM_PARALLEL` и метрики на шлюзе |
| Таймаут шлюза 15–60 с | Длинные и стриминговые ответы обрываются | `timeouts.request` в HTTPRoute, таймауты на всём пути |
| Тег образа `latest` / модель без версии | Разное поведение реплик, нет отката | Пин образа и версии модели (путь в S3, тег OCI) |
| vLLM «съел» 92% GPU | Второй процесс на той же GPU падает с OOM | Одна модель на GPU или `--gpu-memory-utilization` + MIG |
| RWO-PVC + RollingUpdate | Новый под `ContainerCreating`: том занят старым | `Recreate`, RWX-хранилище или image volume |
| `huggingface-cli` в init-контейнере | После обновления до `huggingface_hub` 2.0 — «command not found» | `hf download`, пин версии образа |

---

## 💼 Как это в DevOps

- Сервинг модели — это обычный Deployment с тремя особенностями: **большие артефакты** (модель отдельно,
  кэш, OCI), **долгий старт** (startupProbe, тёплые реплики) и **свои метрики** (очередь, TTFT, tokens/s).
- OpenAI-совместимый API — контракт между приложением и инфраструктурой: бэкенд меняется за шлюзом,
  код приложения — нет.
- Типовой стек 2026: vLLM на GPU-пуле + KEDA по очереди + Envoy Gateway (с Inference Extension на больших
  масштабах) + LLM-шлюз перед всем этим; KServe — когда моделей и команд много.
- Для CPU и стендов — llama.cpp: GGUF, мало памяти, те же API и метрики. Ollama — у разработчиков на ноутбуках.
- Первое, что спросит ML-команда: «почему первый ответ долгий» (холодный старт, prefill длинного промпта)
  и «почему тормозит под нагрузкой» (очередь, KV-кэш, нет реплик).

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| LLM на GPU в проде | vLLM `vllm serve &lt;model&gt; --served-model-name X`, порт 8000, `/health`, `/metrics` |
| LLM на CPU / стенд | `llama-server -m model.gguf --alias X --host 0.0.0.0 -c 4096 -np 2 --metrics` (порт 8080) |
| Вызвать любую модель | `POST /v1/chat/completions` с `model`, `messages`, `stream` |
| Доставить модель | Init-контейнер из S3/MinIO на PVC; PVC-кэш; image volume / ModelCar `oci://` |
| Пережить долгую загрузку | `startupProbe` на `/health` с `failureThreshold × periodSeconds` > времени загрузки |
| Посчитать KV-кэш | `2 × слои × KV-головы × размер головы × байт × токены` |
| Меньше памяти | Квантизация: FP8 / INT8 / INT4 (AWQ, GPTQ, GGUF `Q4_K_M`) |
| Метрика для скейлинга | `vllm:num_requests_waiting` / `llamacpp:requests_deferred` → KEDA prometheus |
| TTFT p95 | `histogram_quantile(0.95, sum by (le) (rate(vllm:time_to_first_token_seconds_bucket[5m])))` |
| Умная балансировка | Gateway API Inference Extension: InferencePool + EPP (llm-d) |
| Модель одним CRD | KServe `InferenceService` с `modelFormat: huggingface` и `storageUri` |

---

## 🧠 Что запомнить

1. ⭐ Выбор: GPU и прод — vLLM (или SGLang); CPU и стенд — llama.cpp; ноутбук — Ollama; классическое ML —
   Triton; платформа для многих команд — KServe. TGI — в режиме поддержки, для нового не брать.
2. ⭐ OpenAI-совместимый API (`/v1/chat/completions`, `/v1/models`, `/v1/embeddings`) — общий язык:
   бэкенд меняется без изменения кода; имя модели и аутентификацию фиксирует инфраструктура.
3. ⭐ Модель — отдельно от образа: init-контейнер из S3/MinIO, PVC-кэш, OCI (ModelCar, image volume — GA в 1.36).
4. Холодный старт = нода + драйвер + образ + скачивание + загрузка весов + прогрев; лечат тёплыми
   репликами, кэшами, предзагрузкой, быстрым хранилищем и меньшей моделью.
5. ⭐ `startupProbe` обязателен для моделей: без него liveness убьёт под посреди загрузки.
6. ⭐ Continuous batching: запросы входят и выходят из батча на каждом шаге — один GPU обслуживает десятки
   запросов; в Ollama по умолчанию 1 параллельный запрос.
7. KV-кэш ≈ 2 × слои × KV-головы × размер головы × байт на токен: для 8B — ~1 ГиБ на запрос с контекстом 8K;
   «модель влезла» ≠ «нагрузку выдержит».
8. Квантизация (FP8, INT8, INT4/GGUF) меняет память на качество; проверяется на eval-наборе.
9. ⭐ Метрики: TTFT, ITL, E2E, tokens/s, очередь, KV-кэш; у vLLM — `vllm:time_to_first_token_seconds`,
   `vllm:num_requests_waiting`, у llama.cpp — `llamacpp:requests_deferred` (флаг `--metrics`).
10. ⭐ Скейлинг — по очереди через KEDA, не по CPU; scale-to-zero — для батча и dev, для чата нужен буфер
    (HTTP add-on); HPA scale-to-zero — beta в 1.37.
11. Round-robin плох для LLM; Gateway API Inference Extension (InferencePool v1 + EPP из llm-d) выбирает под
    по очереди и KV-кэшу.
12. KServe: `InferenceService` с `storageUri` (`hf://`, `s3://`, `oci://`), OpenAI API по `/openai/v1/…`,
    canary и автоскейлинг; для распределённого — `LLMInferenceService`.

➡️ Дальше: [04_llm_gateway_rag.md](/mlops/04-llm-gateway-rag) · Лабы: [07_practice_labs.md](/mlops/07-practice-labs) · Задачи: 03_model_serving_tasks.md


---

### Блок A. Теория


**A1.** ⭐ Какие серверы моделей ты знаешь и когда какой выбрать: vLLM, SGLang, llama.cpp, Ollama, Triton, KServe?

<details><summary>Ответ</summary>

vLLM — GPU и прод (continuous batching, PagedAttention, метрики, OpenAI API); SGLang — альтернатива
vLLM для GPU; llama.cpp — CPU, edge, стенды, GGUF; Ollama — ноутбук разработчика; Triton — зоопарк
классических моделей и разных фреймворков; KServe — control plane над серверами для многих команд и моделей.

</details>

**A2.** Что случилось с TGI и что из этого следует для новых проектов?

<details><summary>Ответ</summary>

TGI переведён в режим поддержки, репозиторий заархивирован (последний релиз v3.3.7, декабрь 2025);
Hugging Face рекомендует vLLM и SGLang. Для новых проектов TGI не брать, существующие планировать к миграции.

</details>

**A3.** ⭐ Почему OpenAI-совместимый API стал стандартом? Какие эндпоинты он включает?

<details><summary>Ответ</summary>

Его отдают почти все провайдеры и серверы, приложение пишется один раз на OpenAI SDK, а бэкенд
меняется заменой `base_url` за шлюзом. Эндпоинты: `/v1/chat/completions`, `/v1/completions`,
`/v1/embeddings`, `/v1/models`, стриминг через SSE.

</details>

**A4.** Что нужно зафиксировать инфраструктуре, чтобы смена модели или сервера не ломала клиентов?

<details><summary>Ответ</summary>

Имя модели в API (`--served-model-name`, `--alias`) независимо от файла, адрес за шлюзом/Service,
версию модели и образа (пин), контракт параметров и лимит контекста.

</details>

**A5.** Почему нельзя полагаться на аутентификацию самого сервера модели? Где закрывают доступ?

<details><summary>Ответ</summary>

У части серверов (Ollama) аутентификации нет, у других — один статический ключ без лимитов и учёта.
Доступ закрывают на LLM-шлюзе (ключи, лимиты, учёт) и NetworkPolicy (пускать к серверу только шлюз).

</details>

**A6.** ⭐ Назови способы доставки модели в под и их плюсы и минусы.

<details><summary>Ответ</summary>

Скачивание с HF при старте — просто, но интернет, лимиты и каждый раз заново. Init-контейнер из
S3/MinIO — внутреннее хранилище и версия в пути, но время скачивания на каждый новый под. PVC-кэш (RWX) —
старт без скачивания, но скорость сетевого диска. OCI (ModelCar, image volume) — кэш на ноде, реестр,
подписи, но ещё большой артефакт в реестре. Запекание в образ — только для крошечных моделей.

</details>

**A7.** Что такое KServe ModelCar и Kubernetes image volume? Какой статус у image volume?

<details><summary>Ответ</summary>

ModelCar — KServe: модель в OCI-образе запускается сидкаром, файлы доступны серверу через общий
process namespace; `storageUri: oci://…`. Image volume — нативный том Kubernetes, монтирующий OCI-образ
read-only (`volumes[].image`), GA в 1.36; нужен рантайм с поддержкой (containerd/CRI-O свежих версий).

</details>

**A8.** ⭐ Из чего складывается холодный старт LLM-пода на новой ноде? Как сократить каждую часть?

<details><summary>Ответ</summary>

Нода (ВМ + драйвер) → pull образа → скачивание модели → загрузка весов → прогрев. Сократить:
тёплые реплики и overprovisioning, образ ноды с драйвером, предзагрузка или ленивое скачивание образа,
PVC-кэш или image volume, быстрое хранилище рядом, меньшая/квантизованная модель.

</details>

**A9.** ⭐ Зачем модели `startupProbe`? Как подобрать её параметры?

<details><summary>Ответ</summary>

Пока модель грузится, liveness и readiness не проверяются, и kubelet не убивает под. Параметры:
`periodSeconds × failureThreshold` с запасом больше измеренного времени загрузки на самой медленной ноде.

</details>

**A10.** Какой должна быть liveness-проба сервера модели и почему не строгой?

<details><summary>Ответ</summary>

Лёгкая (`/health` без генерации), с большим `timeoutSeconds` и `failureThreshold`: под длинной
генерацией сервер может отвечать медленно, строгая liveness перезапустит его и потеряет все запросы в батче.

</details>

**A11.** ⭐ Что такое continuous batching и чем он лучше статического батчинга?

<details><summary>Ответ</summary>

Запросы входят в батч и выходят из него на каждом шаге генерации: закончивший ответ сразу освобождает
место для нового. Статический батч ждёт самый длинный ответ и держит пустые места, новые запросы ждут.
Итог — выше пропускная способность и ниже TTFT под нагрузкой.

</details>

**A12.** Почему генерация одного токена для 32 запросов стоит почти как для одного?

<details><summary>Ответ</summary>

Узкое место генерации — чтение весов из памяти GPU на каждом шаге; веса читаются один раз для всего
батча, а вычисления на 32 токена почти не добавляют времени, пока не упрёмся в вычисления или память KV-кэша.

</details>

**A13.** Как посчитать память под KV-кэш? Сколько выйдет для модели 8B с контекстом 8K?

<details><summary>Ответ</summary>

`2 × слои × KV-головы × размер головы × байт × токены`. Для Llama-3.1-8B (32 слоя, 8 KV-голов,

</details>

**A14.** Как работает параллелизм в llama.cpp и Ollama? Какой у Ollama параллелизм по умолчанию?

<details><summary>Ответ</summary>

llama.cpp — слоты `-np N`, continuous batching включён, контекст `-c` делится между слотами.
Ollama — `OLLAMA_NUM_PARALLEL` (по умолчанию 1) и очередь `OLLAMA_MAX_QUEUE` (512, дальше 503); память
растёт как параллелизм × контекст.

</details>

**A15.** Что такое квантизация? Сравни FP16, FP8, INT8, INT4. Как понять, что качество не пострадало?

<details><summary>Ответ</summary>

Хранение весов в меньшей точности: FP16/BF16 — 2 байта, эталон; FP8 — 1 байт, почти без потерь на
Hopper+; INT8 — ~1 байт, небольшие потери; INT4 (AWQ, GPTQ, GGUF Q4_K_M) — ~0,5 байта, потери заметнее.
Проверка — прогон eval-набора до и после квантизации, а не «на глаз».

</details>

**A16.** ⭐ Что такое TTFT, ITL, E2E latency и tokens/s? Из чего складывается TTFT?

<details><summary>Ответ</summary>

TTFT — время до первого токена: очередь + prefill (обработка промпта). ITL — время между токенами.
E2E ≈ TTFT + ITL × число выходных токенов. Tokens/s — скорость генерации на запрос и суммарно на сервер.

</details>

**A17.** ⭐ Какие метрики отдают vLLM и llama.cpp? Назови метрику очереди у каждого.

<details><summary>Ответ</summary>

vLLM: `vllm:num_requests_waiting` (очередь), `num_requests_running`, `time_to_first_token_seconds`,
`inter_token_latency_seconds`, `e2e_request_latency_seconds`, `kv_cache_usage_perc`, счётчики токенов.
llama.cpp (с `--metrics`): `llamacpp:requests_deferred` (очередь), `requests_processing`,
`tokens_predicted_total`, `prompt_tokens_total`, `predicted_tokens_seconds`.

</details>

**A18.** ⭐ Почему HPA по CPU не подходит для GPU-сервинга? А для CPU-сервинга на llama.cpp?

<details><summary>Ответ</summary>

На GPU вычисления идут на GPU, CPU почти не растёт с нагрузкой — HPA не реагирует. На llama.cpp
один запрос занимает все выделенные потоки, CPU = 100% уже при одном пользователе — HPA скейлит «всегда»
и не видит реальной очереди. Сигнал — очередь и задержка.

</details>

**A19.** Как настроить KEDA для скейлинга по очереди? Какие параметры важны?

<details><summary>Ответ</summary>

ScaledObject с триггером `prometheus`: `query` — сумма очереди по сервису, `threshold` — допустимая
очередь на реплику, `activationThreshold` — когда просыпаться из нуля; `minReplicaCount`,
`maxReplicaCount`, `cooldownPeriod`, `behavior.scaleDown.stabilizationWindowSeconds` — чтобы не гасить
прогретые реплики; `fallback` на случай недоступности Prometheus.

</details>

**A20.** ⭐ Когда scale-to-zero для сервинга оправдан, а когда нет? Что нужно для HTTP со scale-to-zero?

<details><summary>Ответ</summary>

Оправдан для батч-инференса из очереди, dev/stage и редких внутренних инструментов. Не оправдан для
пользовательского чата: холодный старт — минуты, у Service нет буфера. Для HTTP нужен буфер — KEDA HTTP add-on
(beta) или очередь перед моделью; либо min 1 в рабочие часы.

</details>

**A21.** Что изменилось со scale-to-zero в HPA в Kubernetes 1.37?

<details><summary>Ответ</summary>

HPA scale-to-zero стало beta и включено по умолчанию: `minReplicas: 0` с object/external-метриками
(только ресурсные метрики API отклонит). Буфера запросов оно не даёт; KEDA 2.21 при этом поддерживает
Kubernetes только до 1.36.

</details>

**A22.** Почему round-robin плох для LLM? Что такое Gateway API Inference Extension, InferencePool и EPP?

<details><summary>Ответ</summary>

Запросы различаются по стоимости в сотни раз, round-robin отправит тяжёлый запрос на занятую реплику
и не учитывает кэш префиксов. Inference Extension: InferencePool (`inference.networking.k8s.io/v1`) — группа
подов модели, на которую ссылается HTTPRoute; EPP — ext-proc-сервис, выбирающий под по очереди, KV-кэшу
и префиксу (с v1.6 полноценный EPP — в llm-d).

</details>

**A23.** Что даёт KServe `InferenceService`? Чем `LLMInferenceService` отличается от него?

<details><summary>Ответ</summary>

InferenceService — модель одним манифестом: скачивание по `storageUri`, Deployment, Service, маршрут,
canary, автоскейлинг, OpenAI API по `/openai/v1/…`. LLMInferenceService — для распределённого инференса на
базе llm-d и InferencePool (маршрутизация по KV-кэшу, разделение prefill/decode).

</details>

**A24.** Почему при сервинге с RWO-PVC нужен `strategy: Recreate`?

<details><summary>Ответ</summary>

RWO-том монтируется только на одной ноде: при RollingUpdate новый под на другой ноде не сможет
смонтировать том, пока старый жив, — зависнет в `ContainerCreating`. Recreate сначала удаляет старый под.

</details>

---

### Блок B. «Что произойдёт»


```text:no-line-numbers
# B1 — под vLLM с моделью 15 ГБ, загрузка ~4 минуты
```text
```text:no-line-numbers
livenessProbe: { httpGet: { path: /health, port: 8000 }, initialDelaySeconds: 30, periodSeconds: 10, failureThreshold: 3 }
```text
```text:no-line-numbers
# startupProbe нет
```text
Вопрос: что будет с подом?

```text:no-line-numbers
# B2 — Ollama в проде
```text
```text:no-line-numbers
env: []            # всё по умолчанию
```text
```text:no-line-numbers
# пришло 20 одновременных запросов
```text
Вопрос: что увидят пользователи?

```text:no-line-numbers
# B3 — KEDA для llama.cpp
```text
```text:no-line-numbers
triggers:
```text
```text:no-line-numbers
  - type: cpu
```text
```text:no-line-numbers
    metadata: { type: Utilization, value: "70" }
```text
```text:no-line-numbers
# реплика: -t 4, requests cpu 4
```text
Вопрос: как будет вести себя скейлинг?

```text:no-line-numbers
# B4 — чат-бот поддержки
```text
```text:no-line-numbers
minReplicaCount: 0
```text
```text:no-line-numbers
cooldownPeriod: 300
```text
```text:no-line-numbers
# ночью запросов нет; первый клиент в 8:55
```text
Вопрос: что увидит первый клиент? А если это батч-инференс из очереди?

```text:no-line-numbers
# B5 — vLLM на GPU 24 ГБ, модель 8B FP16 (~16 ГБ), --gpu-memory-utilization по умолчанию
```text
```text:no-line-numbers
# на ту же GPU через time-slicing ставят второй под с моделью эмбеддингов на 1 ГБ
```text
Вопрос: что будет?

```text:no-line-numbers
# B6
```text
```text:no-line-numbers
spec:
```text
```text:no-line-numbers
  replicas: 2
```text
```text:no-line-numbers
  strategy: { type: RollingUpdate }
```text
```text:no-line-numbers
  # volumes: PVC models, accessModes: [ReadWriteOnce]
```text
Вопрос: что будет при выкатке новой версии, если поды на разных нодах?

```text:no-line-numbers
# B7 — HTTPRoute без timeouts, у Envoy Gateway таймаут по умолчанию, ответ модели стримится 90 секунд
```text
Вопрос: чего ожидать и что проверить?

```text:no-line-numbers
# B8 — init-контейнер на базе образа с huggingface_hub 2.0
```text
```text:no-line-numbers
huggingface-cli download Qwen/Qwen2.5-7B-Instruct --local-dir /models
```text
Вопрос: что произойдёт?

```text:no-line-numbers
# B9 — llama-server -c 8192 -np 4
```text
```text:no-line-numbers
Пользователь отправляет промпт на 3 000 токенов.
```text
Вопрос: влезет ли запрос? Почему?

```text:no-line-numbers
# B10 — модель в S3 лежит по пути s3://models/qwen/latest/model.gguf, init-контейнер качает её при каждом старте
```text
```text:no-line-numbers
Вчера DS перезалил «latest» новой версией.
```text
Вопрос: что будет в кластере?

```text:no-line-numbers
# B11 — 8 реплик vLLM за обычным Service, запросы от 20 до 20 000 токенов
```text
Вопрос: как распределится нагрузка и что улучшит Inference Extension?

```text:no-line-numbers
# B12 — KServe ModelCar, storageUri: oci://registry.example.com/models/qwen:latest
```text
Вопрос: что не так с тегом?

---

### Блок C. Практика


### C1. 🔑 Модель на CPU в kind
Пройди мини-лабу: llama.cpp + `qwen2.5-0.5b` (Q4_K_M) в kind, PVC, init-контейнер, пробы, HTTPRoute.
Запиши: время от `apply` до READY, размер модели на PVC, ответ `/v1/models`, `prefill_ms` и `tok_s` из `timings`.

### C2. 🔑 TTFT и tokens/s под нагрузкой
Запусти `ttft.py` 1, 2, 4, 8 раз параллельно при `-np 2`. Составь таблицу: число запросов → TTFT (мин/макс),
tokens/s на запрос, суммарные tokens/s. Повтори с `-np 4`. Объясни, что происходит с очередью.

### C3. Метрики
Во время нагрузки из C2 снимай `/metrics` каждые 2 секунды (`watch`). Найди моменты, когда
`llamacpp:requests_deferred > 0`. Заведи ServiceMonitor и построй в Grafana график очереди и
`rate(llamacpp:tokens_predicted_total[1m])`.

### C4. 🔑 Холодный старт
Замерь три сценария: (а) рестарт пода с моделью на PVC; (б) под с пустым PVC (скачивание);
(в) под на «новой» ноде (удали образ с ноды: `docker exec ml-control-plane crictl rmi &lt;образ&gt;` — имя ноды
посмотри в `kubectl get nodes`). Разложи время по этапам по событиям `kubectl describe pod`.

### C5. Пробы
Убери `startupProbe` и поставь строгую liveness (`failureThreshold: 1`, `periodSeconds: 2`,
`timeoutSeconds: 1`). Что происходит при загрузке модели? А при длинной генерации под нагрузкой?
Верни нормальные пробы и объясни каждое число.

### C6. 🔑 KEDA по очереди
Поставь KEDA 2.21 и kube-prometheus-stack, примени ScaledObject из конспекта (`maxReplicaCount: 3`,
`threshold: "2"`). Чтобы реплики могли жить на разных нодах, переведи модель на `emptyDir` + init-контейнер
(или image volume). Дай нагрузку из C2 и посмотри, как растёт число реплик. Полный вариант — лаба 2 в
[07_practice_labs.md](/mlops/07-practice-labs).

### C7. Ollama против llama.cpp
Подними Ollama (`ollama/ollama:0.34.4`) с той же моделью (`qwen2.5:0.5b`) в том же кластере.
Повтори C2 с `OLLAMA_NUM_PARALLEL=1` и `=2`. Сравни с llama.cpp и запиши, чего не хватает Ollama для прода.

### C8. Модель как OCI-образ (со звёздочкой)
Собери образ `FROM scratch` с `COPY model.gguf /model.gguf`, загрузи в kind (`kind load docker-image`)
и смонтируй через `volumes[].image` (Kubernetes 1.36). Сравни время старта с PVC и с init-контейнером.
Что будет, если тег образа — `latest`?

### C9. Расчёт KV-кэша
Найди в `config.json` модели Qwen2.5-7B-Instruct на Hugging Face `num_hidden_layers`, `num_key_value_heads`,
`hidden_size`, `num_attention_heads` и посчитай KV-кэш на токен в FP16. Сколько одновременных запросов
по 4K влезет на GPU 24 ГБ после весов в FP16? А в INT4?

### C10. KServe на бумаге
Напиши `InferenceService` для модели из MinIO (`s3://models/qwen/v3/`) с GPU, указанием `--max-model-len`,
секретом доступа к S3 через ServiceAccount и canary на 10%. Какие объекты KServe создаст в кластере?

---

### Блок D. Инциденты


**D1.** После выкатки новой модели поды в `CrashLoopBackOff`, в логах — загрузка весов обрывается
на середине без ошибки. Причина и исправление?

<details><summary>Ответ</summary>

Liveness убивает под во время загрузки новой (более тяжёлой) модели — нет startupProbe или её запаса
не хватает. Добавить/увеличить startupProbe по замеру.

</details>

**D2.** Пользователи жалуются: «первый ответ — 40 секунд, потом нормально». Метрики: TTFT p50 1,5 с,
p99 40 с. Гипотезы и что проверить?

<details><summary>Ответ</summary>

Холодные старты (новые реплики после скейлинга или scale-to-zero), prefill длинных промптов, очередь
в пиках. Проверить события скейлинга, `vllm:request_queue_time_seconds`, распределение `request_prompt_tokens`,
корреляцию с появлением новых подов.

</details>

**D3.** Под нагрузкой TTFT вырос с 1 до 15 секунд, ITL почти не изменился, GPU загружена на 60%.
Что происходит и что делать?

<details><summary>Ответ</summary>

Очередь: запросы ждут места в батче (TTFT = очередь + prefill), а начатые генерируются нормально.
GPU не на 100%, значит упёрлись в лимит батча или KV-кэш: поднять `--max-num-seqs` (если есть память),
добавить реплики по `num_requests_waiting`, ограничить длину промптов.

</details>

**D4.** vLLM под пиковой нагрузкой: `vllm:kv_cache_usage_perc` около 1, запросы вытесняются и
перезапускаются. Варианты решения?

<details><summary>Ответ</summary>

Меньше `--max-model-len` или `--max-num-seqs`, больше реплик, квантизация весов или KV-кэша (FP8),
GPU с большей памятью, роутинг по KV-кэшу, лимиты длины промпта на шлюзе.

</details>

**D5.** KEDA подняла 4 реплики, но TTFT не улучшился: новые поды в `Pending` 10 минут. Почему?

<details><summary>Ответ</summary>

Нет свободных GPU — ждут новую ноду (Karpenter/CA + драйвер + образ), либо квота/taint мешает.
Нужны запас тёплой ёмкости, быстрый старт нод, предзагрузка образа; иначе скейлинг опаздывает за пиком.

</details>

**D6.** Длинные ответы обрываются на 60-й секунде у всех клиентов. Где искать?

<details><summary>Ответ</summary>

Таймауты на пути: HTTPRoute `timeouts`, политика таймаутов шлюза, балансировщик облака, LLM-шлюз,
клиентский SDK. Искать то, что равно 60 секундам.

</details>

**D7.** После смены файла модели в S3 клиенты получают `model not found`. Почему?

<details><summary>Ответ</summary>

Имя модели в API берётся из файла/пути по умолчанию: новый файл — новое имя. Фиксировать
`--served-model-name`/`--alias`.

</details>

**D8.** Разработчики из другого namespace напрямую ходят в сервер модели в обход шлюза и лимитов.
Как закрыть?

<details><summary>Ответ</summary>

NetworkPolicy: в namespace сервинга пускать только поды шлюза; сервер слушает только внутри,
ключ сервера — только у шлюза; убрать лишние Service/маршруты.

</details>

**D9.** Каждый новый под скачивает 30 ГБ модели из S3, выкатка 10 реплик кладёт канал и стоит денег
за трафик. Что изменить?

<details><summary>Ответ</summary>

PVC-кэш (RWX) или image volume/ModelCar с кэшем на ноде, S3 в том же регионе/зоне через VPC endpoint,
предзагрузка на ноды, поэтапная выкатка (`maxSurge` поменьше).

</details>

**D10.** После обновления образа сервинга качество ответов заметно упало, хотя модель та же.
Что могло поменяться?

<details><summary>Ответ</summary>

Версия сервера (другие ядра, дефолты сэмплинга, шаблон чата), параметры (`--max-model-len`,
квантизация KV-кэша, dtype), шаблон промпта. Фиксировать версии и параметры, прогонять eval после любой смены
образа, не только модели.

</details>

---

### Блок E. Вопросы с собеседования


**1.** ⭐ Чем вы бы сервили LLM на GPU и на CPU? Почему?

<details><summary>Ответ</summary>

GPU — vLLM (метрики, continuous batching, OpenAI API, экосистема), CPU — llama.cpp (GGUF, мало памяти,
   `/metrics`); Ollama — только dev.

</details>

**2.** Что такое OpenAI-совместимый API и зачем он инфраструктуре?

<details><summary>Ответ</summary>

Единый контракт: приложение пишет под OpenAI SDK, инфраструктура меняет бэкенд за шлюзом; фиксируем имя
   модели, аутентификацию и таймауты.

</details>

**3.** ⭐ Где хранить модель и как доставлять её в под?

<details><summary>Ответ</summary>

S3/MinIO с версией в пути, реестр моделей (тема 05); доставка — init-контейнер, PVC-кэш, OCI-артефакт
   (ModelCar, image volume); не в образе.

</details>

**4.** ⭐ Как бороться с холодным стартом модели?

<details><summary>Ответ</summary>

Тёплые реплики и расписание, предзагрузка образов и моделей, быстрое хранилище, образ ноды с драйвером,
   меньшая модель, startupProbe.

</details>

**5.** Что такое continuous batching и KV-кэш?

<details><summary>Ответ</summary>

Continuous batching — запросы входят и выходят из батча на каждом шаге; KV-кэш — память под контекст
   каждого запроса, ограничивает число одновременных запросов.

</details>

**6.** ⭐ Какие метрики вы бы собирали для LLM-сервинга? Что такое TTFT?

<details><summary>Ответ</summary>

TTFT, ITL, E2E, tokens/s, очередь, KV-кэш, загрузка GPU, стоимость ответа; TTFT — время до первого токена
   (очередь + prefill).

</details>

**7.** ⭐ Как автоскейлить инференс? Почему не по CPU?

<details><summary>Ответ</summary>

KEDA по очереди из Prometheus (`num_requests_waiting`), плюс задержка; CPU не отражает нагрузку на GPU
   и насыщен уже одним запросом на CPU-сервинге.

</details>

**8.** Когда оправдан scale-to-zero для модели?

<details><summary>Ответ</summary>

Для батча из очереди, dev/stage и редких инструментов; для чата — только с буфером и принятием холодного старта.

</details>

**9.** Как балансировать трафик между репликами LLM?

<details><summary>Ответ</summary>

Обычный Service — round-robin, плох для разнородных запросов; Gateway API Inference Extension
   (InferencePool + EPP) — по очереди и KV-кэшу; на малых масштабах хватает Service.

</details>

**10.** Что даёт KServe по сравнению с обычным Deployment?

<details><summary>Ответ</summary>

Модель одним CRD: скачивание по `storageUri`, стандартные рантаймы, canary, автоскейлинг, OpenAI API,
    единая модель эксплуатации для многих команд.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Выбираю сервер модели под задачу и знаю статус TGI
- [ ] ⭐ Объясняю, зачем OpenAI-совместимый API, и знаю его эндпоинты
- [ ] ⭐ Знаю способы доставки модели в под и выбираю под ситуацию
- [ ] Раскладываю холодный старт по этапам и знаю, чем сокращать каждый
- [ ] ⭐ Пишу пробы для долгой загрузки модели
- [ ] Объясняю continuous batching и считаю KV-кэш
- [ ] Знаю компромисс квантизации и как проверять качество
- [ ] ⭐ Знаю TTFT, ITL, tokens/s и метрики vLLM и llama.cpp
- [ ] ⭐ Настраиваю KEDA по очереди и объясняю, почему не по CPU
- [ ] Объясняю Gateway API Inference Extension и KServe
- [ ] Прошёл мини-лабу: модель на CPU в kind, замерил TTFT и tokens/s
