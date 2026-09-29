---
title: "06. GitOps: Argo CD собирает кластер из linkd-gitops"
description: "Цель этапа: перенести app-of-apps из 12-autopilot на публичный linkd-gitops,"
---

# 06. GitOps: Argo CD собирает кластер из linkd-gitops

> **Цель этапа:** перенести app-of-apps из 12-autopilot на публичный `linkd-gitops`,
> связать его с чартом из `linkd-platform` и с CI из этапа 03 — чтобы merge в `main`
> сам доезжал до dev, prod менялся через MR, а откат был `git revert`.
>
> **После этапа у тебя есть:** `linkd-gitops` с `bootstrap/` и деревом `apps/`,
> замкнутая цепочка «коммит → CI → gitops-коммит → Argo CD → кластер», замеренные
> «кластер с нуля» и «откат прода», раздел «Доставка» в README и ADR про два репозитория.
>
> **~время:** 3–5 часов (после проекта).

---

## 🧪 Откуда берём

| Проект | Что забираешь | Когда готово |
|--------|---------------|--------------|
| 🛠️ **12-autopilot** — GitOps с Argo CD · `README` · `~/Projects/devops/12-autopilot` | структуру app-of-apps, окружения dev/prod, AppProject'ы, настройки self-heal и sync waves, опыт отката через `git revert` | `./check.sh` зелёный |
| 🛠️ **05-conveyor** → этап 03 · `README` · `~/Projects/devops/05-conveyor` | bump-job, который коммитит тег в `envs/&lt;env&gt;/values.yaml` | этап 03 сделан |

---

## 🎯 Цель

```text
         push-модель                               pull-модель (GitOps)
 CI ──kubeconfig──► helm upgrade ──► кластер    CI ──git commit──► linkd-gitops
  • у CI полный доступ к кластеру                                    ▲   │
  • ручные правки в кластере никто не видит         Argo CD ─────────┘   │ сравнивает
  • «что сейчас задеплоено?» — неизвестно             │ sync ◄───────────┘ и применяет
                                                      ▼
                                                   кластер
```text
В 12-autopilot Argo CD читал Gitea внутри кластера — удобно для учёбы, но снаружи этого
никто не увидит. В портфолио источник правды — публичный `linkd-gitops`, и в нём
сходятся три вещи: чарт из `linkd-platform`, values окружений и тег, который пишет CI.

Три свойства, которые нужно уметь показать вживую:
1. **Кластер из git** — кластер удалён, создан заново, применён bootstrap — всё вернулось.
2. **Self-heal** — ручная правка в кластере откатывается к git.
3. **Откат = `git revert`** — история деплоев совпадает с историей git.

---

## 🗺️ Что получится

```text
 linkd-gitops/
 ├── bootstrap/                 root-приложение — единственное, что применяется руками
 ├── apps/
 │   ├── projects/              AppProject'ы: platform, linkd
 │   ├── platform/              ingress-controller; позже (07) мониторинг, (08) Vault + ESO
 │   ├── dev/                   linkd-data-dev (PostgreSQL), linkd-dev (чарт + envs/dev)
 │   └── prod/                  linkd-data-prod, linkd-prod
 ├── envs/{dev,prod}/values.yaml   ← сюда пишет CI (image.tag)
 ├── data/                      PostgreSQL из этапа 05
 └── platform/                  values сторонних чартов

 linkd-platform: merge в main ─► CI :&lt;sha&gt; ─► commit envs/dev ─► Argo sync dev
                 тег vX.Y.Z   ─► CI :X.Y.Z ─► MR envs/prod ─► ревью ─► Argo sync prod
```text
---

## 🪜 Шаги

### 1. Проект зелёный

```bash
cd ~/Projects/devops/12-autopilot && ./check.sh
```text
### 2. Перенос структуры

Дерево `apps/` и bootstrap из 12-autopilot → `linkd-gitops`. Все `repoURL`, указывавшие
на Gitea, — на публичный `linkd-gitops` на gitlab.com. Вариант «Gitea остаётся зеркалом
внутри кластера» тоже честный (кластер не зависит от интернета при sync) — выбери и
запиши в ADR.

### 3. Связать чарт и values

Чарт живёт в `linkd-platform`, values — в `linkd-gitops`. Способы связать:

| Способ | Как | Плюсы | Минусы |
|--------|-----|-------|--------|
| Чарт копией в gitops | `charts/linkd/` в `linkd-gitops` | просто, всё в одном месте | две копии чарта, легко разъехаться |
| Multi-source Application | чарт из `linkd-platform` по тегу, values из `linkd-gitops` | чарт версионируется вместе с кодом | версию чарта тоже надо двигать |
| Чарт как OCI-артефакт | CI публикует чарт в registry, Argo тянет по версии | самый «взрослый» вариант | ещё один артефакт в CI |

Для второго варианта связка выглядит так — это только фрагмент `spec` Application,
остальное (project, destination, syncPolicy) — как в 12-autopilot:

```yaml
sources:
  - repoURL: https://gitlab.com/&lt;you&gt;/linkd-platform.git   # чарт — рядом с кодом
    path: deploy/helm/linkd
    targetRevision: v0.3.0                                  # версия чарта зафиксирована
    helm:
      valueFiles: [$values/envs/dev/values.yaml]
  - repoURL: https://gitlab.com/&lt;you&gt;/linkd-gitops.git     # values окружения — здесь
    targetRevision: main
    ref: values
```text
### 4. Замкнуть цепочку CI → GitOps

Bump-job из этапа 03 пишет в тот самый `envs/dev/values.yaml`, который читает Argo.
Проверка — без рук:

1. видимая правка в `linkd-platform` (например, версия в логе старта), MR, merge;
2. CI публикует `:&lt;sha&gt;` и коммитит тег в `linkd-gitops`;
3. Argo замечает коммит (опрос или `argocd app get --refresh`) и катит dev;
4. в dev работает образ с этим SHA — видно в `kubectl get deploy -o wide` и в UI Argo.

Prod: тег `vX.Y.Z` → MR в gitops → ревью → merge → sync prod.

### 5. Секреты до этапа 08

Secret с `LINKD_DATABASE_URL` — пока руками в каждом namespace, **не** в git. Если
`linkd-gitops` приватный — креды репо для Argo тоже создаются руками. Этап 08 уберёт
оба ручных шага.

### 6. Проверки

- **кластер с нуля:** `kind delete` → `make cluster` → bootstrap → все приложения
  `Synced` + `Healthy`; время записано;
- **self-heal:** `kubectl scale` или удаление Service в dev откатывается за секунды;
- **откат прода:** `git revert` коммита с плохим тегом в `linkd-gitops`; время записано;
- **AppProject:** Application проекта `linkd` не может деплоить в чужой namespace;
- `helm list -A` пуст — Argo не создаёт Helm-релизы.

### 7. CI-коммит или Argo CD Image Updater

| | Коммит из CI (выбран) | Argo CD Image Updater |
|---|---|---|
| Кто узнаёт о новом образе | CI, сразу после push | контроллер, при опросе registry |
| Права | CI: запись в gitops-репо | Updater: чтение registry + запись в git |
| Прозрачность | коммит с SHA и ссылкой на пайплайн | коммит от бота (в режиме записи в git) |
| Минусы | токен в CI, возможны гонки (`resource_group` + retry) | ещё один компонент; без записи в git git перестаёт быть правдой |
| Когда | мало сервисов, хочется явности | много сервисов, стандартные теги |

### 8. README и ADR

- Раздел «Доставка»: схема, путь коммита до dev и до prod, как откатить.
- ADR-001 «Два репозитория и pull-модель» (шаблон — в [10_readme_resume.md](/project/10-readme-resume)).
- ADR «CI коммитит тег, а не Image Updater» и ADR про способ связи чарта и values.
- Скриншот дерева приложений Argo CD (root → дети).

### 9. Коммит

```bash
git -C ~/Projects/linkd-gitops add bootstrap apps && git -C ~/Projects/linkd-gitops commit -m "gitops: app-of-apps for linkd"
```text
---

## ✅ Критерии приёмки

- [ ] Кластер с нуля собирается командами из README; время полного разворачивания записано
- [ ] Все Application `Synced` + `Healthy`; платформа синхронизируется раньше приложений
- [ ] Merge в `main` `linkd-platform` доезжает до dev без ручных действий; видно, какой SHA работает
- [ ] Prod меняется только через MR в `linkd-gitops`
- [ ] Ручная правка в dev откатывается self-heal'ом
- [ ] Откат прода выполнен через `git revert`, время записано
- [ ] AppProject `linkd` не пускает в чужие namespace и в cluster-scoped ресурсы (кроме Namespace)
- [ ] В `linkd-gitops` нет секретов; способ связи чарта и values описан в ADR

---

## 🪤 Грабли

- **Вебхук не долетает до kind.** gitlab.com не видит ноутбук — Argo узнаёт о коммите
  по опросу (~3 минуты). Для демо — `argocd app get --refresh` или меньший интервал.
- **Остались ссылки на Gitea.** Часть приложений читает старый источник — в UI всё
  зелёное, а коммиты в `linkd-gitops` не доезжают.
- **CRD ещё нет на момент dry-run** у платформенных приложений (ServiceMonitor,
  ExternalSecret) — sync падает, пока не появится оператор.
- **`targetRevision: HEAD` у сторонних чартов** — однажды приедет мажорная версия.
  Версии пинятся.
- **Finalizer на data-приложении** — удаление Application удаляет StatefulSet.
  Рисковать данными ради удобства не стоит.
- **Revert не в том репозитории.** Для dev откат тега в gitops живёт до следующего
  merge в `linkd-platform`; баг исправляется revert'ом кода.
- **Аварийный `argocd app rollback`** при включённом auto-sync не выполняется, а
  root-приложение с self-heal вернёт настройки дочернего. После аварии git
  обязательно приводится в соответствие.
- **HPA и `replicas` в git** → вечный `OutOfSync`.
- **Правка в UI Argo** — тоже дрейф от git. Все изменения — коммитом.

---

## 🤔 Вопросы себе

1. Чем pull-модель GitOps отличается от push-деплоя из CI? Плюсы и минусы обеих.
2. Что такое app-of-apps и чем он отличается от ApplicationSet?
3. Что делают `prune` и `selfHeal`? Что будет, если включить `prune` и удалить файл из `apps/`?
4. Почему sync-wave между Application'ами может «не работать» и как это решено в 12-autopilot?
5. Как CI сообщает Argo о новой версии? Почему не `argocd app set --parameter image.tag=...`?
6. Как откатить прод за минуту и почему «правильный» откат — через git?
7. Где в этой схеме ревью и как продвигается версия dev → prod?
8. Что будет с кластером, если упадёт Argo CD? А если недоступен gitlab.com?
9. Почему чарт и values в разных репозиториях — и когда это перестаёт быть удобным?

---

## 📚 Теория в волте

- GitOps: [../Left/07_ArgoCD/01_gitops_concepts.md](/argocd/01-gitops-concepts),
  [../CICD/04_gitops.md](/cicd/04-gitops)
- Установка и устройство Argo CD: [../Left/07_ArgoCD/02_argocd_install.md](/argocd/02-argocd-install)
- Application, sync, self-heal, откат: [../Left/07_ArgoCD/03_application.md](/argocd/03-application)
- App of Apps и ApplicationSet: [../Left/07_ArgoCD/04_app_of_apps.md](/argocd/04-app-of-apps)
- Helm/Kustomize в Argo: [../Left/07_ArgoCD/05_helm_kustomize.md](/argocd/05-helm-kustomize)
- Откат изменений в git: [../../IT/Git/07_undo_history.md](/git/07-undo-history)
- Git в работе DevOps: [../../IT/Git/12_git_in_devops.md](/git/12-git-in-devops)

➡️ Следующий этап: [07_observability.md](/project/07-observability)
