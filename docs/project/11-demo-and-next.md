---
title: "11. Финальный прогон, демо и развитие"
description: "Цель этапа: доказать, что портфолио работает целиком и без подсказок: один"
---

# 11. Финальный прогон, демо и развитие

> **Цель этапа:** доказать, что портфолио работает **целиком и без подсказок**: один
> сквозной прогон от изменения кода до алерта, отката и проверки восстановления.
> Затем выбрать, куда развивать `linkd-platform` под конкретную вакансию.
>
> **После этапа у тебя есть:** отрепетированный демо-сценарий на 15 минут, запись экрана
> на 5–7 минут со ссылкой в README, пройденный финальный чек-лист и одно выбранное
> расширение в Issues.
>
> **~время:** 3–4 часа + расширения по желанию.

---

## 🧪 Откуда берём

| Источник | Что используется в демо |
|----------|-------------------------|
| Этапы 01–10 | всё собранное: пайплайн, gitops, наблюдаемость, секреты, бэкапы, README |
| Учебные фолты linkd 2.0 (`LINKD_FAULT_ERROR_RATE`, `LINKD_FAULT_LATENCY_MS`) | управляемый «инцидент» без правки кода |
| Сценарии k6 из 14-pulse · `README` · `~/Projects/devops/14-pulse` | живая нагрузка на графиках |
| 99-incidents · `README` · `~/Projects/devops/99-incidents` | тренировка «сузить область поиска» — то, что спросят после демо |

---

## 🎯 Цель

Этапы 01–10 проверялись по отдельности. Но на собесе (или в тестовом задании) могут
попросить: *«покажи, как это работает»*. Сквозной прогон ловит то, что не ловят
отдельные проверки: забытый ручной шаг, истёкший токен, алерт, который никто не
проверял после включения NetworkPolicy.

---

## 🗺️ Что получится

```text
 0:00  README: схема и два репозитория
 0:01  правка в linkd-platform ─► MR ─► пайплайн (test / build / scan)
 0:04  merge ─► CI коммитит тег ─► Argo синхронизирует dev ─► новая версия отвечает
 0:07  тег v0.X.0 ─► MR в linkd-gitops ─► merge ─► prod обновлён под нагрузкой без ошибок
 0:09  «битый релиз» ─► новый под не Ready, старые держат трафик ─► git revert
 0:11  фолт ошибок коммитом в values ─► burn-rate алерт в Telegram ─► дашборд ─► логи
       ─► revert ─► RESOLVED;  фолт задержки ─► медленный спан в Tempo
 0:14  self-heal + результат restore-test + таблица RPO/RTO
 0:15  вопросы
```text
---

## 🪜 Шаги

### 1. Предполётная проверка

```bash
DEV=http://linkd-dev.127.0.0.1.nip.io:8088   # адреса — как в README (порт — из kind-конфига)
PROD=http://linkd.127.0.0.1.nip.io:8088
argocd app list -o wide                                   # все Synced + Healthy
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
kubectl get externalsecret -A                             # SecretSynced
# с port-forward к Prometheus на :9090 — какие алерты горят (в норме только Watchdog)
curl -s localhost:9090/api/v1/alerts | jq -r '.data.alerts[] | select(.state=="firing") | .labels.alertname'
curl -s "$PROD/readyz"
```text
Плюс вне кластера: MinIO жив и в бакете есть свежий бэкап, токен CI → gitops не истёк,
Telegram-бот отвечает. Что-то красное — это находка, а не провал: почини и запиши в журнал.

### 2. Нагрузка на фоне

Сценарий k6 из `observability/load/` в отдельном терминале — графики живые, а счётчик
ответов по кодам показывает, были ли ошибки во время деплоя. Сценарий обязательно
ходит по `/r/<code>`: учебные фолты linkd действуют только там.

### 3. Сквозной сценарий

**3.1. Изменение → dev.** Видимая правка в `linkd-platform`: например, версия linkd
(константа `VERSION` в `app/linkd.py` + запись в CHANGELOG) — её отдают `/healthz` и
метрика `linkd_build_info`. MR, пайплайн; пока он идёт — открыть Grafana и Argo CD.

```bash
curl -s "$DEV/healthz"                                     # до: старая версия
argocd app wait linkd-dev --sync --health --timeout 600
curl -s "$DEV/healthz"                                     # после: новая
kubectl -n dev get deploy linkd -o jsonpath='{.spec.template.spec.containers[0].image}'; echo
```text
**3.2. Продвижение в prod.** Тег `v0.X.0` → retag в CI → MR в `linkd-gitops` → merge →
`argocd app wait linkd-prod ...`. В выводе k6 за время выкатки — ноль ошибок (или
единицы, и понятно почему).

**3.3. Битый релиз не проливается.** Коммит в `envs/dev/values.yaml`, который ломает
новые поды: несуществующий тег образа или неверное имя Secret'а.

```bash
kubectl -n dev get pods -w     # новый под не Ready, старый продолжает обслуживать
argocd app get linkd-dev       # Progressing → Degraded
```text
Исправление — `git revert` этого коммита. Для бага в коде revert делается в
`linkd-platform`, иначе следующий merge снова принесёт его в dev.

**3.4. Инцидент и алерт.** `LINKD_FAULT_ERROR_RATE` — коммитом в values prod (ручной
`kubectl set env` self-heal откатит, и это тоже стоит показать). Дальше:
- burn-rate алерт в Telegram — назвать, сколько прошло и почему столько;
- дашборд: всплеск ошибок; переход к логам за то же время;
- runbook по ссылке из алерта;
- revert фолта → `RESOLVED`.

По желанию — `LINKD_FAULT_LATENCY_MS` и медленный спан в Tempo.

**3.5. Self-heal и DR.**

```bash
kubectl -n dev delete svc linkd && sleep 10 && kubectl -n dev get svc linkd   # вернулся
kubectl -n prod create job --from=cronjob/&lt;restore-test&gt; demo-restore
kubectl -n prod logs -f job/demo-restore                                      # данные восстановлены
```text
И в конце — таблица RPO/RTO из README с замерами учений этапа 09.

### 4. Запись демо

- Терминал — `asciinema rec demo.cast` (текст, копируется, лёгкий), экран целиком —
  любой рекордер; 5–7 минут, ожидание пайплайна вырезается.
- Ссылка на запись — в README рядом со схемой. Страховка на случай, если на собесе
  нет времени или сети для живого показа.

### 5. Финальная уборка

```bash
gitleaks git --verbose .                                          # в обоих репозиториях
grep -rn "&lt;you&gt;\|TODO\|FIXME" --include='*.yaml' --include='*.md' .   # плейсхолдеры и хвосты
git ls-files | grep -E 'TASKS.md|check.sh|\.state/|\.env$|tfstate'    # следы практики и секретов
```text
Пройдись по README: версии, команды быстрого старта, ссылки, скриншоты — всё про
текущее состояние, фолты выключены.

### 6. Куда развивать

Выбирай по вакансиям — не всё сразу. Одно законченное расширение ценнее трёх начатых.

| Расширение | Что показывает | Опора в волте | Сложность |
|-----------|----------------|---------------|-----------|
| Перенос стенда в облако: Terraform-провайдер облака (сеть, firewall, ВМ, бакет), k3s через Ansible | работа с облаком, стоимость, переезд без правок чарта | [../Left/04_Cloud/03_network_vpc.md](/cloud/03-network-vpc), [../Kubernetes/16_cluster_deployment.md](/kubernetes/16-cluster-deployment) | 🔴 |
| Off-site бэкапы в облачный бакет | настоящий DR, а не «вне кластера» | [../Left/04_Cloud/04_s3_storage.md](/cloud/04-s3-storage) | 🟢 |
| CloudNativePG вместо своего StatefulSet: реплика, фейловер, PITR | операторы, HA БД, RPO в минутах | [../Left/01_Databases/06_replication.md](/databases/06-replication), [../Kubernetes/21_advanced_paths.md](/kubernetes/21-advanced-paths) | 🟡 |
| Canary через Argo Rollouts с анализом метрик | прогрессивная доставка, автооткат по SLO | [../Left/07_ArgoCD/03_application.md](/argocd/03-application) | 🔴 |
| Policy as code (Kyverno / OPA Gatekeeper): запрет `latest`, обязательные limits и пробы | guardrails для команды | [../Kubernetes/17_rbac.md](/kubernetes/17-rbac) | 🟡 |
| Подпись образов (cosign) и SBOM | supply chain security | [../CICD/13_quality_security.md](/cicd/13-quality-security) | 🟡 |
| Renovate: MR на обновление образов, чартов, провайдеров | гигиена версий без ручного труда | [../Docker/05_registry_tags.md](/docker/05-registry-tags) | 🟢 |
| ApplicationSet и preview-окружение на каждый MR | масштабирование GitOps | [../Left/07_ArgoCD/04_app_of_apps.md](/argocd/04-app-of-apps) | 🔴 |
| Terraform в CI: `plan` в MR, `apply` по кнопке | IaC-процесс как в команде | [../Left/06_Terraform/06_workflow_cicd.md](/terraform/06-workflow-cicd) | 🟡 |
| postgres_exporter и blackbox-пробы снаружи | мониторинг зависимостей и «взгляд пользователя» | [../Left/01_Databases/07_db_monitoring.md](/databases/07-db-monitoring), [../Left/02_Monitoring/04_exporters.md](/monitoring/04-exporters) | 🟢 |
| Очередь (RabbitMQ/Kafka) + worker, считающий переходы асинхронно | асинхронная архитектура, лаг консьюмеров | [../Left/05_Queues/00_INDEX.md](/queues/) | 🟡 |
| Velero: бэкап ресурсов и томов | DR на уровне кластера | [../Kubernetes/21_advanced_paths.md](/kubernetes/21-advanced-paths) | 🟡 |
| GitLab Runner в кластере (Kubernetes executor) | инфраструктура CI | [../CICD/09_gitlab_runner.md](/cicd/09-gitlab-runner) | 🟡 |
| Хаос-тесты по расписанию + проверка SLO | отказоустойчивость на деле | [../SRE/06_reliability_patterns.md](/sre/06-reliability-patterns) | 🟡 |

Как выбрать: в вакансии облака — перенос в облако и Terraform в CI; надёжность и SRE —
CloudNativePG, off-site бэкапы, хаос-тесты; безопасность — Kyverno и cosign; Kafka —
очередь и worker.

---

## ✅ Критерии приёмки

**Финальный чек-лист портфолио:**
- [ ] Кластер разворачивается из git с нуля, время известно
- [ ] «Коммит → dev» полностью автоматический; «тег → prod» — через MR
- [ ] Деплой под нагрузкой не даёт ошибок; битый релиз не попадает в трафик
- [ ] Инцидент обнаруживается алертом в Telegram, причина находится через дашборд, логи и трейс
- [ ] Откат выполняется через git, восстановление БД — по runbook'у, оба замерены
- [ ] В git нет секретов и файлов практики, поды non-root, сеть ограничена политиками
- [ ] README, ADR, скриншоты и запись демо соответствуют текущему состоянию
- [ ] Сквозной сценарий из шага 3 прогнан целиком минимум один раз без подсказок
- [ ] Выбрано и заведено в Issues одно расширение

---

## 🪤 Грабли

- **Живое демо без репетиции.** Пайплайн идёт минуты, Argo опрашивает git раз в ~3 —
  паузы убивают рассказ. Репетируй с таймером, запись держи запасным вариантом.
- **Демо зависит от внешнего:** gitlab.com, registry, Telegram, интернет в kind.
  Проверь всё за час до показа; токены с истекающим сроком — отдельный риск.
- **Фолт включён руками** — self-heal откатывает его посреди рассказа. Фолты — только коммитом.
- **Фолт забыт после демо** — назавтра горит бюджет ошибок.
- **Revert не в том репозитории** — баг кода возвращается со следующим merge.
- **README отстаёт от реальности** после расширений — проходись по нему после каждого
  заметного изменения.
- **Бесконечная доработка.** Законченная версия с честным списком ограничений лучше
  вечной стройки; расширения параллельно не доводятся ни одно.

---

## 🤔 Вопросы себе

1. Какой шаг сквозного сценария самый хрупкий и почему?
2. Сколько ручных команд нужно, чтобы поднять всё с нуля? Какие из них можно убрать?
3. Если бы этой платформой пользовалась команда из 5 человек — что сломалось бы первым?
4. Какое расширение лучше всего подходит к вакансиям, на которые идёт отклик?
5. Какие три истории «сложная проблема и её решение» есть в журнале?
6. Какие цифры изменились от проекта к портфолио (размер образа, время пайплайна, RTO)?

---

## 📚 Теория в волте

- Разбор инцидентов в кластере: [../Kubernetes/20_troubleshooting.md](/kubernetes/20-troubleshooting)
- Метрики DORA: [../CICD/01_cicd_concepts.md](/cicd/01-cicd-concepts)
- Self-heal и откаты в Argo CD: [../Left/07_ArgoCD/03_application.md](/argocd/03-application)
- Ведение инцидента: [../SRE/04_incident_management.md](/sre/04-incident-management)
- Что происходит при запросе от браузера до пода: [../Network/14_url_journey.md](/network/14-url-journey)
- Карты блоков для повторения: [../00_INDEX.md](./),
  [../Kubernetes/00_INDEX.md](/kubernetes/),
  [../Left/00_INDEX.md](./)

➡️ Портфолио собрано. Вернуться к карте — [00_INDEX.md](/project/)
