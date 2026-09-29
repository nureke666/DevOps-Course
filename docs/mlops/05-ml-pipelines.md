---
title: "05. Пайплайны и реестр моделей: MLflow, DVC, оркестраторы, CT/CD"
description: "Блок → AI/MLOps-инфраструктура → тема 05. Вопросы собеса: «Как модель попадает"
---

# 05. Пайплайны и реестр моделей: MLflow, DVC, оркестраторы, CT/CD

> Блок → AI/MLOps-инфраструктура → тема 05. Вопросы собеса: *«Как модель попадает
> из ноутбука дата-сайентиста в прод?»*, *«Как откатить модель?»*, *«Что версионируете,
> кроме кода?»*, *«Как понять, что модель в проде деградировала?»*
> **После темы ты умеешь:** поднять MLflow с PostgreSQL и S3 (MinIO-форк) в compose, залогировать
> и зарегистрировать игрушечную модель, управлять версиями через алиасы и загружать модель
> по алиасу; версионировать данные DVC; выбрать оркестратор; собрать CT/CD, где модель — это
> версия в конфиге, а не слой в образе; объяснить воспроизводимость и мониторинг дрейфа.
> Версии — «проверь, сентябрь 2026».

---

## 🗺️ Карта темы

```text
 ДАННЫЕ                ОБУЧЕНИЕ (оркестратор)             РЕЕСТР                ПРОД
 ──────                ───────────────────────            ──────                ────
 S3 / MinIO            prepare → train → evaluate        MLflow Registry        CI/GitOps:
 + DVC (версия   ──►   (Argo Workflows / KFP /     ──►   churn v1, v2, v3 ──►   model.version: 3
   датасета)            Airflow / CI-джоба)               алиасы:                  │
                             │                            @production → v3         ▼
                             ▼                            @staging    → v4      сервинг (тема 03)
                       MLflow Tracking:                        ▲                    │
                       параметры, метрики,                     │ gate: v4 лучше     ▼
                       артефакты, окружение                    │ чемпиона?      мониторинг:
                                                               │                latency, ошибки,
 триггер переобучения ◄────── дрейф данных / расписание / новый код ◄────────── дрейф предсказаний
```text
---

## 1. Чем CI/CD модели отличается от CI/CD сервиса

| | Сервис | Модель |
|---|--------|--------|
| Что версионируется | Код | ⭐ Код **+ данные + параметры + окружение + сама модель** |
| Результат сборки | Образ, детерминированно из коммита | Файл весов: тот же код на других данных даёт другую модель |
| Проверка перед продом | Тесты проходят / не проходят | Метрика качества **лучше текущей** модели (порог, сравнение с чемпионом) |
| Почему ломается в проде | Баг в коде, конфиг | ⭐ Мир изменился: данные на входе уже не те, что при обучении (дрейф) |
| Откат | Предыдущий образ | Предыдущая **версия модели** из реестра |
| Кто делает | Разработчик → CI | DS/ML-инженер обучает; девопс даёт трекинг, реестр, хранилище, пайплайн и деплой |

Термины: **CT** (continuous training) — автоматическое переобучение по триггеру; **CD модели** —
автоматическая выкладка новой версии после проверок. Роли и жизненный цикл — [01_ml_systems_for_devops.md](/mlops/01-ml-systems-for-devops).

---

## 2. MLflow: из чего состоит

MLflow — open-source платформа (Apache-2.0) для трекинга экспериментов, реестра моделей и,
в линейке 3.x, трейсинга и оценки GenAI-приложений. Версия **3.16.1** (16.09.2026).

```text
 python train.py ──(REST)──► mlflow server :5000 ──► backend store: PostgreSQL
 (MLFLOW_TRACKING_URI)        │  UI, API, Registry      (эксперименты, runs, параметры,
                              │                          метрики, реестр, пользователи)
                              └─ proxy артефактов ──► artifact store: S3 / MinIO
                                 (--artifacts-destination)  (веса, графики, окружение)
```text
| Компонент | Что хранит | Эксплуатация |
|-----------|------------|--------------|
| **Tracking** | Runs: параметры, метрики, теги, артефакты | Растёт постоянно: retention, чистка старых экспериментов |
| **Backend store** | Метаданные в SQL (PostgreSQL/MySQL) | Бэкапы как у любой БД ([../Left/01_Databases/05_backup_restore.md](/databases/05-backup-restore)); миграции схемы при обновлении — `mlflow db upgrade` |
| **Artifact store** | Файлы моделей и артефакты в S3 | Versioning и lifecycle бакета ([../Left/04_Cloud/04_s3_storage.md](/cloud/04-s3-storage) §4–5) |
| **Model Registry** | Зарегистрированные модели, версии, алиасы, теги | ⭐ Главный контракт между ML и эксплуатацией |

> 💡 С `--artifacts-destination` сервер **проксирует** артефакты: клиенты грузят файлы через
> MLflow и не получают ключи S3. Ключи есть только у сервера — меньше секретов на ноутбуках.

**Безопасность сервера (проверь на своей версии):**
- Без аутентификации любой в сети может удалить модели. Встроенная — `mlflow server
  --app-name basic-auth`: пароль админа из `MLFLOW_AUTH_ADMIN_PASSWORD` (не короче 12 символов,
  без него сервер не стартует), `MLFLOW_FLASK_SERVER_SECRET_KEY` одинаковый на всех репликах.
  В компании — SSO через прокси (oauth2-proxy и т.п.).
- ⚠️ Сервер проверяет заголовок `Host` (защита от DNS rebinding): по умолчанию разрешены
  localhost и частные IP. В compose и k8s по имени сервиса (`mlflow:5000`) запросы будут
  отклонены, пока не задашь `--allowed-hosts` (или `MLFLOW_SERVER_ALLOWED_HOSTS`).
- `MLFLOW_CREATE_MODEL_VERSION_SOURCE_VALIDATION_REGEX` — регистрировать версии только
  из доверенных бакетов.

---

## 3. Стенд: MLflow + PostgreSQL + MinIO-форк в compose

Официальные образы MinIO больше не публикуются — берём форк `pgsty/silo`
([../Storage/03_nfs_minio.md](/storage/03-nfs-minio) §3, §5). Образ MLflow — вариант
**`-full`** (с драйверами PostgreSQL и клиентом S3; базовый образ их не содержит, `-full` есть с 3.9.0).

```yaml
# ~/labs/mlops/mlflow/docker-compose.yml — теги проверь, сентябрь 2026
services:
  db:
    image: postgres:17
    environment: { POSTGRES_DB: mlflow, POSTGRES_USER: mlflow, POSTGRES_PASSWORD: mlflow-pass }
    volumes: ["pgdata:/var/lib/postgresql/data"]
  minio:
    image: pgsty/silo:RELEASE.2026-09-16T00-00-00Z
    command: server /data --console-address ":9001"
    environment: { MINIO_ROOT_USER: admin, MINIO_ROOT_PASSWORD: admin-secret-123 }
    ports: ["9000:9000", "9001:9001"]
    volumes: ["s3:/data"]
  mlflow:
    image: ghcr.io/mlflow/mlflow:v3.16.1-full
    depends_on: [db, minio]
    ports: ["5000:5000"]
    environment:
      MLFLOW_S3_ENDPOINT_URL: http://minio:9000        # S3-совместимое хранилище, не AWS
      AWS_ACCESS_KEY_ID: admin                          # на стенде root; в проде — свой ключ с политикой на бакет
      AWS_SECRET_ACCESS_KEY: admin-secret-123
    command: >
      mlflow server --host 0.0.0.0 --port 5000
      --backend-store-uri postgresql://mlflow:mlflow-pass@db:5432/mlflow
      --artifacts-destination s3://mlflow
      --allowed-hosts "localhost:*,127.0.0.1:*,mlflow:*"
volumes: { pgdata: {}, s3: {} }
```text
```bash
cd ~/labs/mlops/mlflow && docker compose up -d
docker compose exec minio mcli alias set local http://127.0.0.1:9000 admin admin-secret-123
docker compose exec minio mcli mb local/mlflow            # бакет для артефактов
docker compose logs mlflow | tail -5                      # слушает :5000, таблицы созданы
# UI: http://localhost:5000
```text
---

## 4. Трекинг: игрушечная модель

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install "mlflow==3.16.1" "scikit-learn==1.9.1"        # ⭐ версии зафиксированы
export MLFLOW_TRACKING_URI=http://localhost:5000
```text
```python
# train.py — «отток клиентов» на синтетических данных, без скачиваний
import sys
import mlflow, mlflow.sklearn
from mlflow.models import infer_signature
from sklearn.datasets import make_classification
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split

C = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
SEED = 42                                                 # ⭐ воспроизводимость (§9)

mlflow.set_experiment("churn")
X, y = make_classification(n_samples=2000, n_features=8, random_state=SEED)
X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=SEED)

with mlflow.start_run():
    model = LogisticRegression(C=C, max_iter=200, random_state=SEED).fit(X_tr, y_tr)
    pred = model.predict(X_te)
    mlflow.log_params({"C": C, "seed": SEED, "dataset": "make_classification-2000-v1"})
    mlflow.log_metrics({"accuracy": accuracy_score(y_te, pred), "f1": f1_score(y_te, pred)})
    info = mlflow.sklearn.log_model(
        model, name="model",                              # MLflow 3: name вместо artifact_path
        signature=infer_signature(X_tr, model.predict(X_tr)),   # схема входа/выхода
        input_example=X_tr[:2],
        registered_model_name="churn",                    # сразу регистрирует новую версию
    )
    print("model_uri:", info.model_uri)
```text
```bash
python train.py 1.0 && python train.py 0.01               # две версии: churn v1 и v2
```text
Что появилось: в UI — эксперимент `churn` с двумя runs (параметры, метрики); в **Logged Models** —
две модели; в **Models** — `churn` версии 1 и 2; в бакете `mlflow` — файлы модели,
`MLmodel`, `requirements.txt`/`conda.yaml` (окружение, в котором модель обучена).

> ⚠️ Отличия MLflow 3 от старых туториалов: `log_model(..., name=...)` вместо
> `artifact_path=`; модели — отдельные сущности (LoggedModel), артефакты лежат в
> `experiments/&lt;id&gt;/models/&lt;model_id&gt;/artifacts`; `runs:/&lt;run_id&gt;/model` — устаревший путь,
> используй `info.model_uri` или `models:/…`.

---

## 5. Model Registry: версии и алиасы

**Версия** — неизменяемый номер (v1, v2, …) с ссылкой на артефакты. **Алиас** — изменяемое
имя, указывающее на одну версию: `@production`, `@staging` (или `@champion`/`@challenger`).
**Стадии** (`Staging`/`Production`/`Archived`) **устарели с MLflow 2.9** и будут удалены
в будущем мажоре — в старых статьях встречаются, в новом коде не используй.

| | Стадии (deprecated) | ⭐ Алиасы |
|---|---------------------|----------|
| Сколько | 4 фиксированных | Сколько угодно, свои имена |
| URI | `models:/churn/Production` | `models:/churn@production` |
| Смысл | Жизненный цикл + окружение в одном поле | Именованная ссылка; окружения — отдельными алиасами или реестрами |

```python
# promote.py — назначить алиасы и загрузить по алиасу
import numpy as np
import mlflow.pyfunc
from mlflow import MlflowClient

c = MlflowClient()
c.set_registered_model_alias("churn", "staging", "2")
c.set_registered_model_alias("churn", "production", "1")
c.set_model_version_tag("churn", "1", "validation_status", "approved")

mv = c.get_model_version_by_alias("churn", "production")
print("production ->", mv.version, mv.tags)
model = mlflow.pyfunc.load_model("models:/churn@production")
print(model.predict(np.array([[0.1] * 8])))
```text
**Сервинг встроенным сервером** (для стенда и простых моделей; прод-варианты — [03_model_serving.md](/mlops/03-model-serving)):

```bash
mlflow models serve -m "models:/churn@production" --env-manager local -h 0.0.0.0 -p 5001
curl -s localhost:5001/invocations -H 'Content-Type: application/json' \
  -d '{"inputs": [[0.1, -0.2, 0.3, 0.0, 1.1, -0.5, 0.2, 0.7]]}'      # → {"predictions": [1]}
```text
> ⚠️ Алиас резолвится **в момент загрузки**. Перевели `@production` на v2 — работающий
> сервер продолжает отдавать v1, пока его не перезапустят; а два пода, стартовавшие до и после
> переключения, отдают **разные** модели. Поэтому в деплое фиксируют номер версии (§8).

---

## 6. Данные: версионирование с DVC

Модель = код + **данные**. Git не хранит гигабайты; DVC хранит в git маленький файл-указатель
(хеш), а сами данные — в S3. Версия **3.67.1** (31.03.2026); с ноября 2025 проект принадлежит
lakeFS (лицензия Apache-2.0 сохранена).

```bash
pip install "dvc[s3]==3.67.1"
git init && dvc init                                      # .dvc/ в git
dvc remote add -d storage s3://dvc
dvc remote modify storage endpointurl http://localhost:9000
dvc remote modify --local storage access_key_id admin              # --local → .dvc/config.local,
dvc remote modify --local storage secret_access_key admin-secret-123   # не попадает в git
docker compose exec minio mcli mb local/dvc

dvc add data/train.csv            # → data/train.csv.dvc (хеш md5) + data/train.csv в .gitignore
git add data/train.csv.dvc data/.gitignore && git commit -m "data: train v1"
dvc push                          # данные → s3://dvc
# позже: git checkout &lt;старый коммит&gt; && dvc checkout   → вернулись те же данные
```text
Пайплайн DVC (`dvc.yaml`) описывает стадии с входами и выходами; `dvc repro` пересчитывает
только то, у чего изменились зависимости, `dvc.lock` фиксирует хеши — «make для данных».

| Инструмент | Когда |
|------------|-------|
| **DVC** | Команда ML, датасеты до сотен ГБ, workflow «как git» |
| **lakeFS** | Озеро данных целиком: ветки и коммиты поверх S3, петабайты |
| Табличные форматы (Iceberg, Delta) | Time travel по снапшотам таблиц в дата-платформе |
| Минимум без инструментов | Неизменяемые пути `s3://data/churn/2026-09-28/` + versioning бакета + путь в параметрах run |

---

## 7. Оркестраторы пайплайнов (кратко)

| | **Kubeflow Pipelines** | **Argo Workflows** | **Airflow** |
|---|------------------------|--------------------|-------------|
| Версия (проверь) | 2.17.2 (04.09.2026) | 4.1.4 (18.09.2026) | 3.3.2 (17.09.2026) |
| Что это | Платформа ML-пайплайнов: Python SDK (`@dsl.component`, `@dsl.pipeline`) → IR YAML; UI с артефактами и сравнением запусков | Общий движок DAG на Kubernetes: CRD `Workflow`, шаг = под | Оркестратор ETL и расписаний: DAG на Python, сотни интеграций |
| Где исполняется | open-source бэкенд — поверх Argo Workflows (KFP 2.17: Argo v3.7 и v4.0; 3.x не будет в KFP 3.0) | Kubernetes | Где угодно; в k8s — `KubernetesExecutor`, `KubernetesPodOperator` |
| Ставится | Отдельно (standalone) или в составе Kubeflow; нужен MySQL | Helm-чарт, лёгкий | Helm-чарт; scheduler, API-сервер, БД метаданных |
| ⭐ Когда | ML-команда хочет «свою» платформу с UI экспериментов | Девопс-команде нужен k8s-native движок: ML, CI, batch | Data-команда уже на Airflow: переобучение — ещё один DAG |

Для одной-двух моделей часто хватает **CI-джобы по расписанию** (GitLab CI / GitHub Actions)
с MLflow — без новой платформы. Argo Workflows v4.0 убрал Python SDK из репозитория и
singular `mutex`/`semaphore` — старые примеры могут не работать.

```yaml
# retrain-wf.yaml — Argo Workflows: три шага, каждый — под (образ и команды — твои)
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata: { generateName: churn-retrain-, namespace: ml }
spec:
  entrypoint: main
  serviceAccountName: ml-pipeline            # права — минимальные (Security/06)
  templates:
    - name: main
      steps:
        - [{ name: prepare,  template: run, arguments: { parameters: [{ name: cmd, value: "python prepare.py" }] } }]
        - [{ name: train,    template: run, arguments: { parameters: [{ name: cmd, value: "python train.py 1.0" }] } }]
        - [{ name: evaluate, template: run, arguments: { parameters: [{ name: cmd, value: "python evaluate.py" }] } }]
    - name: run
      inputs: { parameters: [{ name: cmd }] }
      container:
        image: registry.example.com/ml/churn-train:1.4.0@sha256:…   # окружение обучения, pinned
        command: [sh, -c]
        args: ["&#123;&#123;inputs.parameters.cmd&#125;&#125;"]
        env: [{ name: MLFLOW_TRACKING_URI, value: "http://mlflow.ml.svc:5000" }]
        resources: { requests: { cpu: "1", memory: 2Gi } }
```text
---

## 8. CT/CD: путь модели в прод

```text
 1. ТРИГГЕР     расписание (раз в неделю) │ новые данные │ алерт дрейфа │ изменился код
 2. ОБУЧЕНИЕ    пайплайн: prepare → train → log в MLflow → новая версия churn v8
 3. GATE        evaluate.py: v8 на отложенной выборке vs текущий @production (v7)
                 + проверки: схема входа, размер артефакта, латентность на тестовом наборе
                 не лучше → стоп, v8 остаётся без алиаса
 4. ПРОДВИЖЕНИЕ @staging → v8 (автоматически); @production → v8 — после одобрения человека
 5. ДЕПЛОЙ      CI резолвит @production → 8, коммитит в gitops-репо model.version: 8
                 → ArgoCD синхронизирует → сервинг при старте качает модель v8
 6. КОНТРОЛЬ    canary / shadow, метрики сервиса и модели; плохо → revert коммита
```text
⭐ **Модель — это конфиг, а не слой образа.** Образ сервинга содержит рантайм (Python,
библиотеки нужных версий), а номер модели приходит из values/env; модель скачивается
при старте (init-контейнер или сам сервер) из реестра или S3 и кэшируется на PVC —
как в [03_model_serving.md](/mlops/03-model-serving).

| Способ | Плюсы | Минусы |
|--------|-------|--------|
| Модель запечена в образ (`mlflow models build-docker`) | Всё в одном артефакте | Образ пересобирается на каждую модель; гигабайтные слои; сложнее откатить только модель |
| Сервинг сам читает `@production` при старте | Просто | ⚠️ Невоспроизводимо: что в проде, видно только в реестре; поды могут разойтись |
| ⭐ Номер версии в git (`model.version: 8`), CI резолвит алиас | В git видно, что в проде; откат = `git revert`; ArgoCD показывает дрейф | Нужен шаг в CI |

```yaml
# .github/workflows/promote-model.yml — идея; синтаксис Actions — ../CICD/16_github_actions.md
on: { workflow_dispatch: {} }                  # запуск после одобрения @production
jobs:
  bump:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with: { repository: my-org/ml-gitops, token: "$&#123;&#123; secrets.GITOPS_TOKEN &#125;&#125;" }
      - uses: actions/setup-python@v7
        with: { python-version: "3.12" }
      - run: pip install "mlflow==3.16.1"
      - env:
          MLFLOW_TRACKING_URI: $&#123;&#123; vars.MLFLOW_URI &#125;&#125;
          MLFLOW_TRACKING_USERNAME: ci-promoter                 # basic-auth; права — только чтение реестра
          MLFLOW_TRACKING_PASSWORD: $&#123;&#123; secrets.MLFLOW_PASSWORD &#125;&#125;
        run: |
          V=$(python -c "from mlflow import MlflowClient as C; print(C().get_model_version_by_alias('churn','production').version)")
          yq -i ".model.version = \"$V\"" apps/churn/values-prod.yaml
          git config user.name ci-bot && git config user.email ci-bot@example.com
          git commit -am "churn: model v$V" && git push
```text
Дальше — обычный GitOps: [../Left/07_ArgoCD/03_application.md](/argocd/03-application),
[../CICD/04_gitops.md](/cicd/04-gitops). Кто может двигать `@production` — решают права
в MLflow и review в gitops-репозитории, а не «у кого есть пароль админа».

---

## 9. Воспроизводимость

«Обучи ту же модель ещё раз» должно давать ту же модель (или объяснимо близкую).

| Что зафиксировать | Как |
|-------------------|-----|
| Код | Коммит — тег run в MLflow (`mlflow.source.git.commit` пишется автоматически при запуске из git) |
| Данные | DVC-хеш или неизменяемый путь в S3 — параметр run |
| Зависимости | Pinned-версии (`requirements.txt` с `==`, lock-файл), образ обучения по digest |
| Случайность | Seed для библиотек (`random_state`, `numpy`, фреймворк) |
| Параметры | Все гиперпараметры — `log_params` |
| Окружение модели | MLflow сохраняет `requirements.txt`/`conda.yaml` рядом с моделью — сервинг ставит **те же** версии |
| Железо | ⚠️ На GPU часть операций недетерминирована — «ровно те же веса» не гарантированы; фиксируй тип GPU и версии драйвера/CUDA в тегах |

> 💡 Тест воспроизводимости в CI: перезапусти обучение прошлой версии из её параметров
> и сравни метрику с записанной в реестре (допуск, а не равенство).

---

## 10. Мониторинг модели в проде

Слой 1 — **как у любого сервиса** (SLO, RED, насыщение, [../SRE/02_sli_slo_error_budget.md](/sre/02-sli-slo-error-budget)):
латентность, ошибки, RPS, память, время загрузки модели. Слой 2 — **модель**:

| Что | Как увидеть | Сложность |
|-----|-------------|-----------|
| **Дрейф данных** (data drift) | Распределение входных признаков в проде ≠ в обучающей выборке: сравнение гистограмм, PSI | Средняя: нужен эталон из обучения |
| **Дрейф предсказаний** | Доля классов / распределение скоров сместилось | ⭐ Проще всего: гистограмма предсказаний в Prometheus |
| **Концептуальный дрейф** | Связь «вход → правильный ответ» изменилась; качество падает | Правильные ответы приходят с задержкой (отток — через месяц) |
| **Качество** | Метрика на размеченных данных из прода | Зависит от разметки |

**PSI** (population stability index): `Σ (доля_прод − доля_эталон) × ln(доля_прод / доля_эталон)`
по корзинам признака. Эмпирическое правило: < 0,1 — стабильно, 0,1–0,25 — присмотреться,
> 0,25 — существенный сдвиг.

```promql
# доля предсказаний «уйдёт» за час — сервинг экспортирует счётчик с меткой класса
sum(rate(model_predictions_total{model="churn", class="1"}[1h]))
  / sum(rate(model_predictions_total{model="churn"}[1h]))
```text
Алерт дрейфа — **триггер переобучения и повод для разбора**, а не автоматическая выкатка:
новая модель всё равно проходит gate (§8). Специализированные библиотеки считают дрейф
по признакам (например, Evidently — проверь); девопс даёт хранилище логов предсказаний
(без ПДн, [04_llm_gateway_rag.md](/mlops/04-llm-gateway-rag) §6), расписание и алерты.

---

## 11. Feature store — одним абзацем

Feature store (например, **Feast**, 0.66.0) хранит **признаки** для моделей в двух видах:
offline (история в хранилище/озере — для обучения с точной привязкой ко времени, без
«подглядывания в будущее») и online (последние значения в Redis/БД с малой задержкой —
для инференса). Главная польза — одинаковый расчёт признаков при обучении и в проде
(нет training-serving skew). Для девопса это ещё Redis/БД, джобы материализации и мониторинг
их задержки; нужен, когда моделей и признаков много и их считают несколько команд.

---

## 🧪 Мини-лаба: версия → алиас → сервинг по алиасу

Стенд из §3 и `train.py` из §4 (полная лаба с деплоем через CI — лаба 5 в [07_practice_labs.md](/mlops/07-practice-labs)).

1. `python train.py 1.0 && python train.py 0.01` — в реестре `churn` v1 и v2. Сравни `f1` в UI.
2. Назначь `@production` версии с лучшим `f1`, `@staging` — второй (`promote.py`).
3. Запусти `mlflow models serve -m "models:/churn@production" … -p 5001`, отправь запрос.
4. Переназначь `@production` на другую версию. Ответ сервера изменился? Перезапусти сервер — а теперь?
5. Посмотри в MinIO (`mcli ls -r local/mlflow`), где лежат файлы версий; найди `requirements.txt` модели.
6. Останови PostgreSQL (`docker compose stop db`) и попробуй загрузить модель по алиасу. Что сломалось и почему?

**Проверь себя:** почему в деплое пишут номер версии, а не алиас? Где хранится «какая модель
в проде» в твоей схеме? Уборка: `docker compose down -v`.

---

## 12. Грабли

| Грабля | Что происходит | Как избежать |
|--------|----------------|--------------|
| MLflow без аутентификации в общей сети | Любой удаляет модели и эксперименты | `basic-auth` или SSO-прокси, сеть только внутренняя |
| Базовый образ `mlflow` вместо `-full` | Нет драйвера PostgreSQL/клиента S3 — сервер не стартует | `-full` или свой образ с нужными пакетами |
| Не задан `--allowed-hosts` в compose/k8s | Запросы по имени сервиса отклоняются | Явный список хостов |
| `artifact_path=` и `runs:/…/model` из старых статей | Предупреждения, в будущем — ошибки | `name=`, `info.model_uri`, `models:/…` |
| Стадии `Production`/`Staging` в новом коде | Устаревший API | Алиасы |
| Сервинг читает `@production` на лету | Поды отдают разные модели, откат не виден в git | Номер версии в git, CI резолвит алиас |
| Модель в образе | Гигабайтные сборки на каждую версию | Образ = рантайм, модель — из реестра/S3 при старте |
| Данные «лежат где-то в S3» и перезаписываются | Модель не воспроизвести | DVC или неизменяемые пути + versioning бакета |
| `requirements.txt` без версий | Модель обучена на одной версии sklearn, сервинг на другой — ошибки или тихо другие ответы | Pinned-зависимости, окружение из артефактов модели |
| Автопромоушен по одной метрике | Модель «лучше» по accuracy, хуже по делу | Gate с несколькими проверками + одобрение человека для `@production` |
| Алерт дрейфа сразу выкатывает переобученную модель | Мусор на входе → мусорная модель в проде | Дрейф = триггер обучения, выкатка — только через gate |
| Бэкапят только PostgreSQL MLflow | Метаданные есть, файлов моделей нет (или наоборот) | Бэкап БД **и** бакета, согласованные по времени |

---

## 💼 Как это в DevOps

- MLflow в компании — платформенный сервис: HA-реплики за Gateway, PostgreSQL с бэкапами,
  бакет с versioning, SSO, мониторинг; обновление — с `mlflow db upgrade` на копии базы сначала.
- Девопс не выбирает модель, но строит **дорогу**: шаблон пайплайна обучения, gate, промоушен
  через алиас с одобрением, деплой через GitOps, откат `git revert`.
- Секреты: ключи S3 — только у сервера MLflow (proxy артефактов), токены CI — в Vault
  ([../Left/08_Vault/05_vault_integrations.md](/vault/05-vault-integrations)).
- Оркестратор выбирают по тому, что уже есть в компании: Airflow у дата-инженеров — ещё DAG;
  k8s-платформа — Argo Workflows; большая ML-команда — Kubeflow Pipelines.
- Мониторинг модели делят: латентность и ошибки — девопс/SRE, дрейф и качество — ML-команда,
  общий алерт и runbook «модель деградирует» — вместе.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Сервер MLflow | `mlflow server --backend-store-uri postgresql://… --artifacts-destination s3://… --allowed-hosts …` |
| S3-совместимое хранилище | `MLFLOW_S3_ENDPOINT_URL=http://minio:9000` + ключи у сервера |
| Куда писать клиенту | `MLFLOW_TRACKING_URI=http://mlflow:5000` |
| Залогировать и зарегистрировать | `mlflow.sklearn.log_model(model, name="model", registered_model_name="churn")` |
| Назначить алиас | `MlflowClient().set_registered_model_alias("churn", "production", "3")` |
| Узнать версию по алиасу | `get_model_version_by_alias("churn", "production").version` |
| Загрузить по алиасу | `mlflow.pyfunc.load_model("models:/churn@production")` |
| Поднять REST | `mlflow models serve -m models:/churn/3 --env-manager local -p 5001` → `POST /invocations` |
| Версия данных | `dvc add` → `git commit *.dvc` → `dvc push`; назад — `git checkout` + `dvc checkout` |
| Пересчитать пайплайн данных | `dvc repro` |
| Обновить схему БД MLflow | `mlflow db upgrade &lt;db-uri&gt;` (после бэкапа) |

---

## 🧠 Что запомнить

1. ⭐ У модели версионируется всё: код, данные, параметры, окружение и сами веса.
2. MLflow = tracking + backend store (PostgreSQL) + artifact store (S3) + Model Registry;
   3.16.1, образ `-full` для PostgreSQL и S3.
3. `--artifacts-destination` — сервер проксирует артефакты: ключи S3 не нужны клиентам.
4. Защита сервера: `basic-auth`/SSO, `--allowed-hosts` (без него compose и k8s по имени
   сервиса не работают), доверенные источники версий.
5. ⭐ Стадии устарели с 2.9 — используй алиасы: `models:/churn@production`.
6. MLflow 3: `log_model(name=…)`, модели — отдельные сущности, `info.model_uri` вместо `runs:/…`.
7. Алиас резолвится при загрузке — в деплое фиксируй номер версии в git, CI резолвит алиас.
8. ⭐ Модель — конфиг, а не слой образа: образ = рантайм, модель скачивается при старте.
9. DVC: указатель в git, данные в S3, `dvc repro` пересчитывает изменившееся; проект теперь у lakeFS.
10. Оркестратор: KFP (ML-платформа поверх Argo), Argo Workflows (k8s-native DAG),
    Airflow (ETL и расписания); для малого — CI по расписанию.
11. ⭐ CT/CD: триггер → обучение → gate против чемпиона → алиас (прод — с одобрением) →
    GitOps → canary → откат `git revert`.
12. Воспроизводимость: коммит, версия данных, pinned-зависимости, seed, параметры, окружение;
    GPU может быть недетерминирован.
13. Мониторинг: сначала как сервис, затем дрейф данных и предсказаний; дрейф — триггер
    переобучения, а не автодеплой.

➡️ Дальше: [06_ai_in_devops_work.md](/mlops/06-ai-in-devops-work) · Лаба 5: [07_practice_labs.md](/mlops/07-practice-labs) · Задачи: 05_ml_pipelines_tasks.md


---

### Блок A. Теория


**A1.** ⭐ Чем CI/CD модели отличается от CI/CD обычного сервиса? Назови минимум четыре отличия.

<details><summary>Ответ</summary>

Версионируются ещё данные, параметры, окружение и веса; результат недетерминирован от
коммита; проверка — сравнение качества с текущей моделью, а не только тесты; модель ломается
из-за изменения мира (дрейф); откат — на версию из реестра; обучение делает DS, дорогу строит девопс.

</details>

**A2.** Что такое CT и чем он отличается от CD модели?

<details><summary>Ответ</summary>

CT — автоматическое переобучение по триггеру (расписание, новые данные, дрейф). CD модели —
автоматическая выкладка новой версии после проверок. CT создаёт кандидатов, CD доставляет прошедших gate.

</details>

**A3.** Из каких компонентов состоит MLflow? Что хранится в backend store, а что — в artifact store?

<details><summary>Ответ</summary>

Tracking server (API, UI), backend store — SQL-база с экспериментами, runs, параметрами,
метриками, реестром и пользователями; artifact store — S3 с файлами моделей и артефактами;
Model Registry — модели, версии, алиасы, теги.

</details>

**A4.** ⭐ Что даёт `--artifacts-destination` и почему это хорошо для безопасности?

<details><summary>Ответ</summary>

Сервер сам пишет артефакты в S3 и отдаёт их клиентам — клиенты работают только по HTTP
с MLflow и не получают ключи S3. Ключи хранятся в одном месте, их проще ротировать и ограничить.

</details>

**A5.** Чем образ `ghcr.io/mlflow/mlflow:&lt;версия&gt;` отличается от `&lt;версия&gt;-full`?

<details><summary>Ответ</summary>

Базовый — только ядро MLflow, без драйверов БД и клиентов облачных хранилищ; `-full`
(с 3.9.0) — с драйверами PostgreSQL/MySQL/SQL Server, S3/Azure/GCS и GenAI-зависимостями.

</details>

**A6.** Зачем MLflow проверяет заголовок `Host` и что из-за этого нужно настроить в compose и k8s?

<details><summary>Ответ</summary>

Защита от DNS rebinding: сервер отвечает только на разрешённые `Host`. По умолчанию —
localhost и частные IP, поэтому запросы по имени сервиса (`mlflow:5000`, `mlflow.ml.svc`)
отклоняются — нужен `--allowed-hosts` или `MLFLOW_SERVER_ALLOWED_HOSTS`.

</details>

**A7.** Как включить встроенную аутентификацию MLflow и какие переменные для неё нужны?

<details><summary>Ответ</summary>

`mlflow server --app-name basic-auth`; `MLFLOW_AUTH_ADMIN_PASSWORD` (≥ 12 символов,
без него сервер не стартует), `MLFLOW_FLASK_SERVER_SECRET_KEY` (одинаковый на всех репликах).
Клиенты — `MLFLOW_TRACKING_USERNAME`/`MLFLOW_TRACKING_PASSWORD`.

</details>

**A8.** Что изменилось в `log_model` в MLflow 3? Почему `runs:/&lt;run_id&gt;/model` — плохой URI для нового кода?

<details><summary>Ответ</summary>

`name=` вместо `artifact_path=`, модель — отдельная сущность LoggedModel, можно логировать
без run; артефакты — в `experiments/&lt;id&gt;/models/&lt;model_id&gt;/artifacts`. Путь через run устарел
и будет удалён — используют `info.model_uri`, `models:/&lt;model_id&gt;` или `models:/&lt;имя&gt;/&lt;версия&gt;`.

</details>

**A9.** ⭐ Чем версия модели отличается от алиаса? Почему стадии больше не используют?

<details><summary>Ответ</summary>

Версия — неизменяемый номер с артефактами; алиас — изменяемая ссылка на одну версию.
Стадии (4 фиксированных) устарели с 2.9: негибкие, смешивали жизненный цикл и окружение,
не давали разграничить права.

</details>

**A10.** Как загрузить модель по алиасу и как узнать, на какую версию он указывает?

<details><summary>Ответ</summary>

`mlflow.pyfunc.load_model("models:/churn@production")`; версия —
`MlflowClient().get_model_version_by_alias("churn", "production").version`.

</details>

**A11.** ⭐ Почему в деплое фиксируют номер версии, а не алиас?

<details><summary>Ответ</summary>

Алиас резолвится в момент загрузки: разные поды могут загрузить разные версии, а в git
не видно, что в проде. Номер версии в git делает деплой воспроизводимым, откат — `git revert`,
ArgoCD видит дрейф.

</details>

**A12.** Что делает `mlflow models serve` и в каком формате принимает запросы?

<details><summary>Ответ</summary>

Поднимает REST-сервер для pyfunc-модели; `POST /invocations` с JSON: `dataframe_split`,
`dataframe_records`, `inputs` (тензоры/массивы) или `instances`.

</details>

**A13.** Зачем версионировать данные? Как DVC хранит данные и что попадает в git?

<details><summary>Ответ</summary>

Модель = код + данные: без версии данных не воспроизвести обучение и не понять, почему
модель изменилась. DVC кладёт данные в кэш и remote (S3), в git — маленький `.dvc`-файл с хешем.

</details>

**A14.** Что делают `dvc push`, `dvc checkout`, `dvc repro`? Что такое `dvc.lock`?

<details><summary>Ответ</summary>

`dvc push` — выгрузить данные в remote; `dvc checkout` — привести рабочую копию данных
к версиям из текущих `.dvc`/`dvc.lock`; `dvc repro` — пересчитать стадии пайплайна с изменившимися
зависимостями. `dvc.lock` — зафиксированные хеши входов и выходов стадий.

</details>

**A15.** Где хранить креды DVC-remote, чтобы они не попали в git?

<details><summary>Ответ</summary>

`dvc remote modify --local …` — в `.dvc/config.local`, который в `.gitignore`; в CI — переменные
окружения или роль без ключей.

</details>

**A16.** Чем DVC отличается от lakeFS? Когда достаточно «неизменяемых путей в S3»?

<details><summary>Ответ</summary>

DVC — «git для данных» проекта, указатели в git; lakeFS — ветки и коммиты поверх всего
озера данных в S3. Неизменяемых путей с датой + versioning бакета + путь в параметрах run хватает
для небольших команд и простых датасетов.

</details>

**A17.** ⭐ Kubeflow Pipelines, Argo Workflows, Airflow — чем отличаются и когда что брать?

<details><summary>Ответ</summary>

KFP — ML-платформа с Python SDK и UI артефактов, тяжелее в установке; Argo Workflows —
лёгкий k8s-native движок DAG для любых задач; Airflow — оркестратор ETL и расписаний с интеграциями.
Выбор — по тому, что уже есть и кто владелец: ML-платформа → KFP, k8s-команда → Argo, дата-команда → Airflow.

</details>

**A18.** На чём исполняется open-source бэкенд Kubeflow Pipelines? Какие версии Argo он поддерживает?

<details><summary>Ответ</summary>

Поверх Argo Workflows; KFP 2.17 — Argo v3.7 и v4.0, поддержка 3.x уйдёт в KFP 3.0 (проверь).

</details>

**A19.** Что изменилось в Argo Workflows v4.0 такого, что может сломать старые примеры?

<details><summary>Ответ</summary>

Из репозитория убран Python SDK; удалены singular `mutex`/`semaphore` (нужны множественные
`mutexes`/`semaphores`) и старое поле расписания CronWorkflow; изменения в Go-клиенте и поведении containerSet.

</details>

**A20.** ⭐ Опиши CT/CD модели по шагам: от триггера до отката.

<details><summary>Ответ</summary>

Триггер → пайплайн обучения → логирование и регистрация версии → gate против чемпиона →
`@staging` автоматически → `@production` после одобрения → CI резолвит версию и коммитит
в gitops-репо → ArgoCD → сервинг скачивает модель → canary/shadow и мониторинг → при проблемах `git revert`.

</details>

**A21.** Что проверяет evaluation gate, кроме «метрика выросла»?

<details><summary>Ответ</summary>

Схему входа/выхода (signature), латентность и размер модели, работу на эталонном наборе
«трудных» примеров, отсутствие деградации на важных сегментах, совместимость окружения.

</details>

**A22.** ⭐ Почему «модель — это конфиг, а не слой образа»? Какие есть три способа доставить модель
в сервинг и их плюсы/минусы?

<details><summary>Ответ</summary>

Образ — рантайм, модель — версия в конфиге: не пересобираем гигабайты, откат модели
не трогает код. Способы: запечь в образ (один артефакт, но тяжёлые сборки), читать алиас при
старте (просто, но невоспроизводимо), номер версии в git + CI резолвит алиас (видно и откатываемо).

</details>

**A23.** Что нужно зафиксировать для воспроизводимости обучения?

<details><summary>Ответ</summary>

Коммит кода, версию данных, pinned-зависимости и образ по digest, seeds, все параметры,
окружение модели; тип железа и версии драйверов.

</details>

**A24.** Почему обучение на GPU может быть не бит-в-бит воспроизводимым и что с этим делать?

<details><summary>Ответ</summary>

Часть GPU-операций (параллельные редукции, некоторые ядра cuDNN) недетерминирована по
порядку вычислений. Включать детерминированные режимы фреймворка там, где можно, фиксировать железо
и версии, сравнивать метрики с допуском, а не веса.

</details>

**A25.** ⭐ Чем data drift отличается от concept drift? Какой дрейф увидеть проще всего?

<details><summary>Ответ</summary>

Data drift — изменилось распределение входных данных; concept drift — изменилась
зависимость правильного ответа от входа. Проще всего увидеть дрейф предсказаний и входов —
для этого не нужны правильные ответы.

</details>

**A26.** Что такое PSI и какие у него эмпирические пороги?

<details><summary>Ответ</summary>

Индекс стабильности распределения: `Σ (p − q) × ln(p / q)` по корзинам. < 0,1 — стабильно,

</details>

**A27.** Что такое feature store и какую проблему он решает?

<details><summary>Ответ</summary>

Хранилище признаков: offline для обучения с корректной привязкой ко времени и online
для быстрого инференса. Решает training-serving skew и дублирование расчёта признаков между командами.

</details>

---

### Блок B. «Что произойдёт»


```text:no-line-numbers
# B1 — compose
```text
```text:no-line-numbers
mlflow:
```text
```text:no-line-numbers
  image: ghcr.io/mlflow/mlflow:v3.16.1
```text
```text:no-line-numbers
  command: mlflow server --host 0.0.0.0 --backend-store-uri postgresql://mlflow:pass@db/mlflow
```text
Вопрос: что будет при старте?

```text:no-line-numbers
# B2 — сервис train в том же compose ходит в MLflow
```text
```text:no-line-numbers
export MLFLOW_TRACKING_URI=http://mlflow:5000
```text
```text:no-line-numbers
# сервер запущен без --allowed-hosts
```text
Вопрос: что увидит клиент?

```text:no-line-numbers
# B3
```text
```text:no-line-numbers
with mlflow.start_run() as run:
```text
```text:no-line-numbers
    mlflow.sklearn.log_model(model, name="model")
```text
```text:no-line-numbers
m = mlflow.sklearn.load_model(mlflow.get_artifact_uri("model"))
```text
Вопрос: загрузится ли модель в MLflow 3?

```text:no-line-numbers
B4 — в 10:00 @production → v5; под A стартовал в 09:50, под B — в 10:05
```text
```text:no-line-numbers
оба грузят models:/churn@production
```text
Вопрос: что отдают поды?

```text:no-line-numbers
B5 — в values-prod.yaml: model.version: 7
```text
```text:no-line-numbers
кто-то в UI MLflow перевёл @production на v8
```text
Вопрос: что в проде? Что покажет ArgoCD?

```text:no-line-numbers
# B6
```text
```text:no-line-numbers
dvc add data/train.csv
```text
```text:no-line-numbers
git add data/train.csv && git commit -m "data"
```text
Вопрос: что не так?

```text:no-line-numbers
# B7 — через месяц
```text
```text:no-line-numbers
git checkout v1.2.0      # коммит, на котором обучали модель v5
```text
```text:no-line-numbers
python train.py          # dvc checkout забыли
```text
Вопрос: на каких данных обучится модель?

```text:no-line-numbers
B8 — requirements.txt обучения: scikit-learn (без версии)
```text
```text:no-line-numbers
образ сервинга собран через 3 месяца
```text
Вопрос: чем рискуем?

```text:no-line-numbers
B9 — алерт: PSI признака "age" = 0,35 → автоматически запускается переобучение
```text
```text:no-line-numbers
и новая версия сразу получает @production
```text
Вопрос: что может пойти не так?

```text:no-line-numbers
B10 — бэкап MLflow: только pg_dump базы; бакет s3://mlflow без versioning,
```text
```text:no-line-numbers
кто-то удалил префикс experiments/3/
```text
Вопрос: что с моделями эксперимента 3?

```text:no-line-numbers
# B11 — Argo Workflows v4
```text
```text:no-line-numbers
spec:
```text
```text:no-line-numbers
  synchronization:
```text
```text:no-line-numbers
    mutex: { name: retrain }
```text
Вопрос: что будет?

---

### Блок C. Практика


### C1. 🔑 Стенд MLflow
Подними compose из конспекта: PostgreSQL + `pgsty/silo` + `ghcr.io/mlflow/mlflow:v3.16.1-full`
(теги проверь). Создай бакет, открой UI. Найди в PostgreSQL таблицы MLflow (`\dt`)
и объясни три из них.

### C2. 🔑 Два обучения — две версии
Запусти `train.py` с `C=1.0` и `C=0.01`. Сравни runs в UI, найди файлы модели в бакете
(`mcli ls -r`), открой `MLmodel` и `requirements.txt`. Что в них записано?

### C3. 🔑 Алиасы
Назначь `@production` и `@staging`, повесь тег `validation_status`. Загрузи модель по алиасу
в Python и через `mlflow models serve`. Переназначь алиас и объясни, когда ответ сервера изменился.

### C4. Сломай сервер
**1.** Замени образ на базовый (без `-full`) — что в логах?

<details><summary>Ответ</summary>

Например: `experiments`, `runs`, `metrics`, `params`, `registered_models`,
`model_versions`, `registered_model_aliases`, `logged_models`.

</details>

**2.** Убери `--allowed-hosts` и обратись к серверу из соседнего контейнера по имени `mlflow`.

<details><summary>Ответ</summary>

`MLmodel` — flavors (sklearn, python_function), сигнатура, версия MLflow, ссылки
на окружение; `requirements.txt` — зависимости модели с версиями.

</details>

**3.** Включи `--app-name basic-auth` без `MLFLOW_AUTH_ADMIN_PASSWORD`.
Запиши три симптома и три исправления.

<details><summary>Ответ</summary>

— сервер не стартует без пароля админа → задать `MLFLOW_AUTH_ADMIN_PASSWORD` (≥ 12 символов).

</details>

### C5. 🔑 DVC
В новом git-репозитории: `dvc init`, remote на MinIO (креды через `--local`), `dvc add`
CSV-файла, `dvc push`. Измени файл, закоммить вторую версию. Вернись на первый коммит
и восстанови данные. Проверь, что `.dvc/config.local` не в git.

### C6. Пайплайн DVC
Опиши в `dvc.yaml` две стадии: `prepare` (CSV → очищенный CSV) и `train` (→ `model.pkl`).
Запусти `dvc repro` дважды. Что пересчиталось во второй раз? Измени только `train.py` — что теперь?

### C7. Gate
Напиши `evaluate.py`: берёт последнюю версию `churn`, сравнивает её `f1` с версией
под `@production` и выходит с кодом 1, если новая хуже более чем на 0,01. Если лучше —
назначает `@staging`. Прогони для обоих исходов.

### C8. Argo Workflows (со звёздочкой)
Поставь Argo Workflows в kind (Helm, версию проверь), создай ServiceAccount с минимальными
правами и запусти `retrain-wf.yaml` из конспекта с образом, где есть `train.py`. Где смотреть
логи шага и что будет, если шаг `evaluate` упадёт?

### C9. Метрика дрейфа предсказаний
Добавь в сервинг (или в скрипт-эмулятор) счётчик `model_predictions_total{class}` и напиши
PromQL доли класса 1 за час и алерт «доля выросла вдвое относительно прошлой недели».

### C10. PSI руками
Для признака с корзинами эталона [0,25; 0,25; 0,25; 0,25] и прода [0,10; 0,20; 0,30; 0,40]
посчитай PSI. Какой вывод по эмпирическому правилу?

---

### Блок D. Инциденты


**D1.** После обновления MLflow сервер не стартует: ошибка про схему базы. Что делать и что
нужно было сделать до обновления?

<details><summary>Ответ</summary>

Новая версия требует миграции схемы: бэкап базы → `mlflow db upgrade &lt;uri&gt;` → старт.
До обновления: читать release notes, прогнать миграцию на копии базы, план отката (восстановление бэкапа).

</details>

**D2.** Дата-сайентисты жалуются: «модели логируются, но в бакете пусто, а в UI — ошибка
загрузки артефактов». Гипотезы?

<details><summary>Ответ</summary>

Сервер без `--artifacts-destination` (клиенты пишут напрямую и без ключей), неверный
`MLFLOW_S3_ENDPOINT_URL`, нет бакета, у ключа сервера нет прав на запись, проблемы с TLS/подписью S3.

</details>

**D3.** В проде одновременно работают две разные версии модели, хотя «деплоили одну». Причина?

<details><summary>Ответ</summary>

Сервинг загружает модель по алиасу: поды, стартовавшие до и после переключения, держат
разные версии. Номер версии — в конфиге деплоя.

</details>

**D4.** Новая версия модели после выкатки даёт ошибки `predict` у части запросов, хотя
на обучении всё было хорошо. Что проверить?

<details><summary>Ответ</summary>

Несовпадение схемы входа (новые/переименованные признаки), другая версия библиотек
в сервинге, типы данных, пропуски; `signature` модели и логи неудачных запросов.

</details>

**D5.** Модель в проде «тихо» деградировала за два месяца: ошибок нет, латентность в норме,
а бизнес-метрика падает. Как это можно было заметить раньше?

<details><summary>Ответ</summary>

Мониторинг дрейфа входов и предсказаний, сбор отложенной разметки и метрики качества,
дашборд бизнес-метрики рядом с моделью, алерт с runbook.

</details>

**D6.** Никто не может сказать, на каких данных обучена модель, которая сейчас в проде.
Что внедрить?

<details><summary>Ответ</summary>

DVC или неизменяемые пути данных + логирование версии данных и коммита в каждом run,
обязательные теги в реестре, запрет регистрировать версию без них.

</details>

**D7.** Кто-то удалил зарегистрированную модель `churn` в UI MLflow. Как восстановить и как
не допустить повторения?

<details><summary>Ответ</summary>

Из бэкапа базы MLflow (и бакета) или заново зарегистрировать версии по сохранённым
артефактам. Не допустить: аутентификация и права (удаление — только админам), бэкапы, аудит.

</details>

**D8.** Пайплайн переобучения каждую ночь занимает все CPU-ноды кластера, и утренние
деплои ждут в `Pending`. Что сделать?

<details><summary>Ответ</summary>

Отдельный пул нод или namespace с ResourceQuota для обучения, PriorityClass ниже
у пайплайнов, расписание вне часов деплоя, лимиты параллелизма в оркестраторе.

</details>

**D9.** Откат модели «на прошлую версию» занял 40 минут, потому что пересобирали образ.
Что изменить в схеме?

<details><summary>Ответ</summary>

Образ — рантайм, модель — версия в конфиге: откат = `git revert` строки `model.version`,
модель уже в кэше/реестре, пересборка не нужна.

</details>

**D10.** CI промоушена упал: «не могу получить версию по алиасу», хотя в UI алиас есть. Гипотезы?

<details><summary>Ответ</summary>

Не та `MLFLOW_TRACKING_URI` (другой сервер/окружение), нет прав у учётки CI на реестр,
опечатка в имени модели или алиаса, версия клиента MLflow без поддержки алиасов, сеть/`allowed-hosts`.

</details>

---

### Блок E. Вопросы с собеседования


**1.** ⭐ Расскажи путь модели от эксперимента до прода.

<details><summary>Ответ</summary>

Эксперимент логируется в MLflow → регистрация версии → gate против текущей → `@staging` →
   одобрение → `@production` → CI пишет номер версии в gitops-репо → ArgoCD → сервинг качает модель
   → canary и мониторинг.

</details>

**2.** Зачем нужен реестр моделей? Чем версия отличается от алиаса?

<details><summary>Ответ</summary>

Единый каталог версий с артефактами, окружением и метаданными; версия неизменна, алиас — ссылка.

</details>

**3.** ⭐ Как вы откатываете модель?

<details><summary>Ответ</summary>

`git revert` коммита с `model.version` (и перевод алиаса обратно); модель уже в реестре, образ
   не пересобираем.

</details>

**4.** Что вы версионируете в ML-проекте?

<details><summary>Ответ</summary>

Код, данные, параметры, окружение, модель; плюс версию образа обучения.

</details>

**5.** Kubeflow, Argo Workflows или Airflow — что выберешь и почему?

<details><summary>Ответ</summary>

По контексту: Airflow — если он уже есть у данных; Argo Workflows — k8s-native и лёгкий;
   KFP — если нужна ML-платформа с UI; для одной модели — CI по расписанию.

</details>

**6.** ⭐ Почему модель не стоит запекать в образ?

<details><summary>Ответ</summary>

Гигабайтные образы на каждую версию, медленные сборки и откаты, смешение кода и модели;
   лучше образ-рантайм и версия в конфиге.

</details>

**7.** Как обеспечить воспроизводимость обучения?

<details><summary>Ответ</summary>

Коммит, версия данных, pinned-зависимости, seeds, параметры, окружение; тест переобучения
   с допуском в CI.

</details>

**8.** ⭐ Как мониторить модель в проде?

<details><summary>Ответ</summary>

Слой сервиса (латентность, ошибки, ресурсы) и слой модели (дрейф входов и предсказаний,
   качество по отложенной разметке); алерты с runbook.

</details>

**9.** Что такое дрейф и что делать, когда он обнаружен?

<details><summary>Ответ</summary>

Изменение распределения данных или связи вход→ответ; разобраться в причине (источник данных?),
   переобучить, выкатывать только через gate.

</details>

**10.** Как защитить MLflow в компании?

<details><summary>Ответ</summary>

SSO/basic-auth, `--allowed-hosts`, только внутренняя сеть, ключи S3 только у сервера, права
    на реестр, бэкапы базы и бакета, аудит.

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Объясняю отличия CI/CD модели от сервиса и что такое CT
- [ ] Поднимал MLflow с PostgreSQL и S3 (форк MinIO), знаю про `-full` и `--allowed-hosts`
- [ ] ⭐ Логировал и регистрировал модель, назначал алиасы, грузил по алиасу
- [ ] Понимаю, почему в деплое номер версии, а не алиас
- [ ] Версионировал данные DVC с remote на MinIO, креды — через `--local`
- [ ] Знаю, чем отличаются KFP, Argo Workflows и Airflow
- [ ] ⭐ Рисую CT/CD модели с gate, одобрением и откатом
- [ ] Объясняю, почему модель — конфиг, а не слой образа
- [ ] Перечисляю, что нужно для воспроизводимости
- [ ] ⭐ Объясняю дрейф данных и предсказаний, считаю PSI
