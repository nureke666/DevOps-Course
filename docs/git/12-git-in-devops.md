---
title: "12. Git в работе DevOps"
description: "Расследование, хуки, секреты, submodules/LFS, git в CI/CD — конспект и задачи"
---

# 12. Git в работе DevOps: расследование, хуки, секреты, CI

> Роадмап → 1. Git → «Что ещё стоит изучить?»: `git diff`, `git fetch`, `git revert` и прочее —
> плюс всё то, что не написано в роадмапе, но встречается на реальной работе.
> **После темы ты умеешь:** найти виновный коммит через `blame`/`bisect`, настроить хуки
> и сканер секретов, понимать submodules и LFS, знать, как git ведёт себя внутри пайплайна,
> и что делать, если секрет попал в историю.

---

## 🗺️ Карта темы

```text:no-line-numbers
 РАССЛЕДОВАНИЕ            ГИГИЕНА                 МАСШТАБ              CI/CD
 git blame                .gitattributes          submodule            shallow clone
 git log -S/-G            hooks (pre-commit)      subtree              deploy keys / токены
 git bisect               gitleaks/trufflehog     LFS                  CI-переменные
 git show / range-diff    git gc / maintenance    sparse-checkout      кэш и артефакты
                          filter-repo (секреты)   monorepo vs polyrepo GitOps-репозиторий
```

---

## 1. Расследование: «кто и когда это сломал»

### `git blame` — авторство каждой строки

```bash
git blame values.yaml                    # весь файл
git blame -L 40,60 values.yaml           # только строки 40-60
git blame -w -C values.yaml              # игнорировать пробелы и перемещения кода
git blame --since=3.months -- values.yaml
git show <хеш>                           # посмотреть тот самый коммит целиком
```

Читается так: хеш → автор → дата → строка. Дальше `git show <хеш>` даёт контекст:
сообщение коммита, MR, соседние изменения.

> 💡 Blame — инструмент **контекста**, а не поиска виноватых. Правильный вопрос —
> «что тогда происходило и почему так сделали», а не «кто накосячил».

### Поиск по содержимому

```bash
git log -S "memory: 512Mi" --oneline -p         # где появилось/исчезло значение
git log -G "resources:\s*$" --oneline           # то же, но регулярным выражением
git log --all --grep="OOM"                      # поиск по сообщениям
git log --diff-filter=D -- path/to/file         # кто удалил файл
git log --follow -p -- charts/app/values.yaml   # полная история файла
```

### ⭐ `git bisect` — бинарный поиск сломавшего коммита

Между «месяц назад работало» и «сейчас не работает» — 200 коммитов. Bisect найдёт нужный
за ~8 проверок.

```bash
git bisect start
git bisect bad                 # текущее состояние сломано
git bisect good v1.4.0         # на этом теге точно работало
# git переключает на середину диапазона — проверяешь и отвечаешь:
git bisect bad                 # или: git bisect good
# ... повторяешь ~log2(N) раз ...
# → "abc1234 is the first bad commit"
git bisect reset               # вернуться на исходную ветку
```

Автоматический режим — если проверка скриптуется:
```bash
git bisect start HEAD v1.4.0
git bisect run ./check.sh      # скрипт: exit 0 = хорошо, exit 1 = плохо
```

Для DevOps `check.sh` — это, например, «собрать образ и прогнать health-check»
или «применить манифест в kind-кластер и дождаться Ready».

---

## 2. Хуки (hooks) — автоматика на события git

Скрипты в `.git/hooks/` (локально, **не версионируются**):

| Хук | Когда срабатывает | Типичное применение |
|-----|-------------------|---------------------|
| `pre-commit` | перед созданием коммита | линтеры, форматирование, поиск секретов |
| `commit-msg` | после ввода сообщения | проверка Conventional Commits |
| `pre-push` | перед отправкой | тесты, запрет push в main |
| `post-merge` | после слияния | пересобрать зависимости |
| серверные (`pre-receive`) | на сервере при приёме | политики репозитория (в GitLab — push rules) |

Поскольку `.git/hooks` не попадает в репозиторий, командой пользуются **фреймворком**
[pre-commit](https://pre-commit.com):

```yaml
# .pre-commit-config.yaml — ЭТОТ файл коммитится
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-merge-conflict        # ⭐ маркеры конфликта (тема 05)
      - id: detect-private-key          # ⭐ приватные ключи
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.4
    hooks:
      - id: gitleaks                    # ⭐ секреты
  - repo: https://github.com/adrienverge/yamllint
    rev: v1.35.1
    hooks:
      - id: yamllint
```

```bash
pipx install pre-commit
pre-commit install                # поставить хуки в .git/hooks
pre-commit run --all-files        # прогнать по всему репозиторию
```

Те же проверки дублируют в CI: локальный хук можно обойти (`git commit --no-verify`),
пайплайн — нет.

---

## 3. ⭐ Секреты в репозитории

### Профилактика

```text:no-line-numbers
.env
*.pem
*.key
id_rsa*
kubeconfig
*.tfstate
*.tfvars           # кроме example
.vault_pass
```
+ `gitleaks` в pre-commit и отдельной джобой в CI
+ хранение секретов там, где положено: CI-переменные (masked/protected), Vault,
SOPS/`git-crypt`/`sealed-secrets`, Ansible Vault.

### Если секрет уже в истории

**Порядок действий:**
1. **СМЕНИТЬ СЕКРЕТ.** Он скомпрометирован — это главное действие, всё остальное вторично.
2. Сообщить команде и безопасности.
3. Вычистить историю (по необходимости) — командами ниже.
4. Проверить, нет ли копий: форки, зеркала, кэши CI, артефакты, образы в registry.

```bash
pipx install git-filter-repo
git filter-repo --path .env --invert-paths          # выкинуть файл из всей истории
git filter-repo --replace-text secrets.txt          # заменить строки на ***REMOVED***
# затем: force-push (с согласованием), все делают СВЕЖИЙ клон
```
⚠️ `git filter-repo` переписывает **все** хеши: это разовая, согласованная с командой
операция. `git rm` и `revert` от утечки не спасают.

---

## 4. Большие файлы и специальные форматы

### `.gitattributes`

```text:no-line-numbers
* text=auto eol=lf              # единые окончания строк (лечит «конфликт всего файла»)
*.sh   text eol=lf
*.bat  text eol=crlf
*.png  binary
*.jpg  binary
package-lock.json merge=ours    # не сливать вручную
*.md   diff=markdown
```

### Git LFS — для бинарников

```bash
git lfs install
git lfs track "*.zip" "*.iso" "*.psd"     # запишется в .gitattributes
git add .gitattributes && git commit -m "chore: track binaries via LFS"
git lfs ls-files
```
В репозиторий попадает указатель, содержимое — в LFS-хранилище. Помни: LFS требует поддержки
на сервере, а клиенты без `git-lfs` получат «файлы-указатели».

**Правило DevOps:** образы, дампы, архивы и артефакты сборки — не в git, а в registry
или S3/Nexus. LFS — компромисс для дизайнерских/медийных файлов.

---

## 5. Несколько репозиториев в одном

### Submodule — «репозиторий внутри репозитория»

```bash
git submodule add git@gitlab.com:team/ansible-roles.git roles/common
git commit -m "chore: add roles/common submodule"

git clone --recurse-submodules <url>          # ⭐ иначе каталог будет пустым
git submodule update --init --recursive       # если уже склонировал без флага
git submodule update --remote roles/common    # подтянуть свежие изменения
```
Родительский репозиторий хранит **точный коммит** субмодуля — это плюс (фиксация версии)
и минус (постоянные «грязные» состояния и забытые `--recurse-submodules`).

### Subtree — альтернатива попроще

```bash
git subtree add --prefix=vendor/lib https://github.com/x/lib.git main --squash
git subtree pull --prefix=vendor/lib https://github.com/x/lib.git main --squash
```
Код физически лежит в репозитории, клонирующему ничего знать не нужно.

### Monorepo vs polyrepo (вопрос архитектуры)

| | Monorepo | Polyrepo |
|---|---------|----------|
| Общие изменения | Один MR на всё | Несколько MR, сложная синхронизация |
| CI | Нужны правила `changes:`/`rules` | Простой пайплайн на репозиторий |
| Права доступа | Сложнее ограничить | Естественно раздельные |
| Размер клона | Растёт | Маленький |

Для DevOps типично: `infra` как монорепозиторий (terraform + ansible + манифесты)
и отдельные репозитории сервисов.

### `sparse-checkout` — забрать часть большого репозитория

```bash
git clone --filter=blob:none --sparse <url> && cd repo
git sparse-checkout set k8s/ charts/
```

---

## 6. Git внутри CI/CD

Что делает раннер, когда запускается джоба:

```bash
git clone --depth 1 --branch $CI_COMMIT_REF_NAME $CI_REPOSITORY_URL
# или: git fetch + git checkout $CI_COMMIT_SHA  (GIT_STRATEGY: fetch — быстрее)
```

| Параметр | GitLab | GitHub Actions |
|----------|--------|----------------|
| Глубина клона | `GIT_DEPTH: 1` | `fetch-depth: 1` |
| Полная история | `GIT_DEPTH: 0` | `fetch-depth: 0` |
| Стратегия | `GIT_STRATEGY: fetch\|clone\|none` | — |
| Субмодули | `GIT_SUBMODULE_STRATEGY: recursive` | `submodules: recursive` |
| Токен доступа | `$CI_JOB_TOKEN` | <code v-pre>${{ secrets.GITHUB_TOKEN }}</code> |

Практические следствия:
- `git describe`, `git log`, сравнение с предыдущим коммитом **не работают** при `depth: 1` —
  ставь `GIT_DEPTH: 0`, если нужна история (например, для `semantic-release`);
- когда пайплайн сам пушит (бамп версии, CHANGELOG) — нужен отдельный токен/deploy key
  с правом записи, `CI_JOB_TOKEN` обычно только на чтение;
- чтобы пуш бота не запускал пайплайн повторно — `[skip ci]` в сообщении коммита;
- переменные, доступные в джобе: `$CI_COMMIT_SHA`, `$CI_COMMIT_TAG`, `$CI_COMMIT_BRANCH`,
  `$CI_COMMIT_MESSAGE` — из них строят теги образов и правила запуска (темы 08-09).

**Deploy key** — SSH-ключ на конкретный репозиторий (обычно read-only): так ходят в git
серверы, ArgoCD и раннеры, не получая доступ ко всему аккаунту.

---

## 7. Обслуживание репозитория

```bash
git count-objects -vH             # сколько занимает
git gc                            # упаковать объекты, подчистить
git maintenance start             # фоновое обслуживание (git 2.30+)
git fsck                          # проверка целостности
git remote prune origin           # убрать мёртвые origin/*
git reflog expire --expire=90.days --all
```

Диагностика «почему клон весит 3 ГБ»:
```bash
git rev-list --objects --all \
  | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' \
  | awk '$1=="blob"' | sort -k3 -n -r | head -20
```

---

## 💼 Как это в DevOps

- **Разбор инцидента** почти всегда начинается в git: `git log` за период, `git blame`
  по строке конфига, `git bisect` между «хорошим» тегом и текущим состоянием.
- **pre-commit + gitleaks** в инфраструктурном репозитории — базовая гигиена: один утёкший
  ключ облака стоит дороже, чем настройка хука.
- **GitOps-репозиторий** — отдельный репозиторий с манифестами: ArgoCD/Flux следят за веткой
  и приводят кластер к её состоянию. Тогда `git revert` = откат прода, а история git =
  журнал изменений инфраструктуры.
- **Submodules** в инфраструктуре встречаются часто (общие роли Ansible, общие CI-шаблоны)
  и так же часто становятся болью — многие переходят на версионирование через
  `requirements.yml`/`include:` из другого репозитория.
- В пайплайнах важно помнить про shallow clone: половина странных ошибок
  (`fatal: No names found`, «пустой diff») лечится увеличением глубины.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Кто написал строку | `git blame -L 10,20 file` |
| Где появилось значение | `git log -S "строка" -p` |
| Кто удалил файл | `git log --diff-filter=D -- path` |
| Найти сломавший коммит | `git bisect start` → `bad`/`good` → `git bisect run ./check.sh` |
| Поставить хуки команде | `.pre-commit-config.yaml` + `pre-commit install` |
| Проверить на секреты | `gitleaks git .` (история) · `gitleaks dir .` (файлы) |
| Убрать файл из всей истории | `git filter-repo --path secret --invert-paths` |
| Единые окончания строк | `.gitattributes`: `* text=auto eol=lf` |
| Большие бинарники | `git lfs track "*.zip"` (а лучше — не в git) |
| Клон с субмодулями | `git clone --recurse-submodules <url>` |
| Часть большого репозитория | `git clone --filter=blob:none --sparse` + `sparse-checkout set` |
| История в CI | `GIT_DEPTH: 0` / `fetch-depth: 0` |
| Размер и уборка | `git count-objects -vH`, `git gc`, `git remote prune origin` |

---

## 🧠 Что запомнить

1. `git blame` + `git show` дают контекст изменения; `git log -S` находит, когда появилось
   значение; `git bisect` — бинарный поиск сломавшего коммита (в том числе автоматический).
2. **Хуки** автоматизируют проверки: локально через `pre-commit`, а в CI — те же проверки
   повторяются, потому что локальные хуки обходятся `--no-verify`.
3. ⭐ Секрет в истории = **смена секрета** в первую очередь; чистка истории
   (`git filter-repo`) — вторым шагом и по согласованию с командой.
4. `.gitattributes` (`* text=auto eol=lf`) лечит «конфликты всего файла» и проблемы CRLF/LF.
5. Большие бинарники — не в git: registry, S3, артефакт-хранилище; LFS — компромисс.
6. **Submodule фиксирует конкретный коммит** зависимости; клонировать нужно
   `--recurse-submodules`, иначе каталог пустой.
7. Monorepo vs polyrepo — вопрос процессов и прав, а не вкуса; для инфраструктуры часто
   удобен монорепозиторий.
8. В CI по умолчанию **shallow clone**: `git describe` и история недоступны, лечится
   `GIT_DEPTH: 0` / `fetch-depth: 0`.
9. Пушу из пайплайна нужен отдельный токен/deploy key с правом записи и `[skip ci]`,
   чтобы не зациклить пайплайн.
10. **Deploy key** — доступ к одному репозиторию, обычно read-only: так ходят серверы,
    ArgoCD и раннеры.
11. В GitOps `git revert` — это откат прода, а история репозитория — журнал изменений
    инфраструктуры.

---

## Задачи

> Стенд: `mkdir -p ~/git-lab/t12 && cd ~/git-lab/t12 && git init`
> Часть задач требует `pipx install pre-commit git-filter-repo` и `gitleaks`
> (или `docker run --rm -v $PWD:/repo zricethezav/gitleaks:latest detect --source /repo`).

---

### Блок A. Теория

**A1.** Что показывает `git blame` и почему это инструмент контекста, а не поиска виноватых?

<details><summary>Ответ</summary>

Показывает, каким коммитом и каким автором была внесена каждая строка файла.
Инструмент контекста: по хешу открываешь коммит и MR и понимаешь, зачем так сделали —
это важнее, чем «кто виноват», тем более что строку мог «перенести» рефакторинг
(поэтому `-w -C`).

</details>

**A2.** Чем `git log -S` отличается от `git log -G` и от `git log --grep`?

<details><summary>Ответ</summary>

`-S` ищет коммиты, где изменилось **количество вхождений** строки (появилась/исчезла);
`-G` ищет коммиты, где diff соответствует регулярному выражению; `--grep` ищет по тексту
**сообщений** коммитов.

</details>

**A3.** ⭐ Как работает `git bisect`? Сколько проверок нужно на 1000 коммитов?

<details><summary>Ответ</summary>

Бинарный поиск по истории: ты задаёшь заведомо «хороший» и «плохой» коммиты, git
переключает тебя на середину диапазона, ты сообщаешь `good`/`bad`, диапазон сокращается
вдвое. Для 1000 коммитов — примерно 10 проверок (log₂1000 ≈ 10).

</details>

**A4.** Что делает `git bisect run` и как выглядит скрипт проверки для DevOps-задачи?

<details><summary>Ответ</summary>

Запускает скрипт на каждом шаге автоматически: `exit 0` → good, `exit 1` (или другой
ненулевой, кроме 125) → bad. Для DevOps скрипт может собирать образ и дёргать health-check,
применять манифест в kind и ждать Ready, прогонять smoke-тест.

</details>

**A5.** Где лежат хуки git? Почему они не версионируются и как это обходят?

<details><summary>Ответ</summary>

В `.git/hooks/` — это часть служебного каталога, не отслеживаемая git, поэтому
хуки не распространяются на команду. Обходят фреймворком `pre-commit`: конфиг
`.pre-commit-config.yaml` коммитится, а разработчик выполняет `pre-commit install`.

</details>

**A6.** Назови четыре полезных pre-commit хука для инфраструктурного репозитория.

<details><summary>Ответ</summary>

`check-yaml` (валидный YAML), `check-merge-conflict` (маркеры конфликта),
`detect-private-key`/`gitleaks` (секреты), `end-of-file-fixer`/`trailing-whitespace`,
плюс `yamllint`, `terraform fmt`, `ansible-lint`, `shellcheck`.

</details>

**A7.** Почему проверки из pre-commit обязательно дублируют в CI?

<details><summary>Ответ</summary>

Локальный хук обходится (`git commit --no-verify`), может быть не установлен
или отключён; CI — единственная гарантированная точка проверки, через которую проходит
каждое изменение.

</details>

**A8.** ⭐ Секрет попал в историю и запушен. Назови порядок действий и объясни,
почему `git rm` и `git revert` не решают проблему.

<details><summary>Ответ</summary>

(1) Сменить/отозвать секрет — он уже скомпрометирован; (2) уведомить команду
и безопасность; (3) при необходимости переписать историю (`git filter-repo`) и заставить
всех переклонировать; (4) проверить копии (форки, зеркала, кэши CI, образы).
`git rm` убирает файл только из будущих коммитов, `revert` добавляет обратный коммит —
в обоих случаях старый коммит с секретом остаётся в истории и у всех, кто клонировал.

</details>

**A9.** Что делает `git filter-repo` и какие последствия у его применения для команды?

<details><summary>Ответ</summary>

Переписывает историю репозитория (удаляет пути, заменяет текст, меняет авторов).
Последствия: меняются **все** хеши после точки изменения, требуется force-push и свежий
клон у всех, ломаются ссылки на коммиты в задачах/MR, старые теги надо пересоздавать.
Делается разово и по согласованию.

</details>

**A10.** Зачем нужен `.gitattributes`? Приведи три полезные строки.

<details><summary>Ответ</summary>

Файл правил обработки путей: `* text=auto eol=lf` (единые окончания строк),
`*.png binary` (не пытаться сливать), `package-lock.json merge=ours` (не сливать вручную),
`*.sh text eol=lf`, настройки LFS.

</details>

**A11.** Что такое Git LFS и что стоит хранить в нём, а что — вообще не в git?

<details><summary>Ответ</summary>

Механизм хранения больших файлов: в git попадает указатель, содержимое —
в отдельном хранилище. Разумно для медиа/дизайна. Образы, дампы БД, архивы и артефакты
сборки лучше не хранить в git вообще — им место в registry, S3, Nexus.

</details>

**A12.** ⭐ Что такое submodule? Что именно хранит родительский репозиторий?

<details><summary>Ответ</summary>

Вложенный репозиторий внутри родительского. Родитель хранит путь, URL (`.gitmodules`)
и **конкретный коммит** субмодуля — то есть фиксирует версию зависимости.

</details>

**A13.** Чем subtree отличается от submodule?

<details><summary>Ответ</summary>

Subtree физически включает содержимое чужого репозитория в твой: клонирующему
ничего дополнительно делать не нужно, но обновления сложнее и история больше.
Submodule хранит только ссылку: легче обновлять и фиксировать версию, но требует
`--recurse-submodules` и даёт больше «сюрпризов».

</details>

**A14.** Monorepo или polyrepo: назови по два аргумента за каждый для инфраструктуры.

<details><summary>Ответ</summary>

Monorepo: сквозное изменение одним MR (например, обновить версию образа во всех
сервисах), общий стандарт и шаблоны CI. Polyrepo: раздельные права доступа
(не все должны иметь доступ к terraform прода), маленькие клоны и простые пайплайны.

</details>

**A15.** ⭐ Почему в CI по умолчанию shallow clone и какие проблемы это создаёт?

<details><summary>Ответ</summary>

Чтобы ускорить джобы: полная история больших репозиториев тянется долго.
Проблемы: не работают `git describe`, `git log`, сравнение с предыдущими коммитами,
инструменты вроде `semantic-release`; лечится `GIT_DEPTH: 0` / `fetch-depth: 0`
или `git fetch --unshallow`.

</details>

**A16.** Что такое deploy key и чем он лучше личного SSH-ключа на сервере?

<details><summary>Ответ</summary>

SSH-ключ, привязанный к одному репозиторию (обычно read-only). Личный ключ
на сервере даёт доступ ко всем репозиториям пользователя и «уходит» вместе с человеком;
deploy key ограничен, легко ротируется и не связан с учёткой сотрудника.

</details>

**A17.** Зачем пайплайну `[skip ci]` и в каком случае это нужно?

<details><summary>Ответ</summary>

Чтобы коммит, сделанный самим пайплайном (бамп версии, CHANGELOG, обновление
тега образа в GitOps-репозитории), не запускал новый пайплайн и не создавал бесконечный цикл.

</details>

**A18.** Что делает `git gc` и когда о нём вспоминают?

<details><summary>Ответ</summary>

Упаковывает объекты в packfile, удаляет недостижимые объекты по истечении срока,
чистит reflog. Вспоминают при разрастании `.git`, тормозах и после массового удаления веток;
в новых версиях — `git maintenance start` в фоне.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  git blame -L 40,60 -w -C charts/app/values.yaml
B2.  git log -S "memory: 512Mi" --oneline -p
B3.  git log -G "replicas:\s*[0-9]+" --oneline
B4.  git log --diff-filter=D -- k8s/old-deploy.yaml
B5.  git bisect start && git bisect bad && git bisect good v1.4.0
B6.  git bisect run ./check.sh
B7.  git bisect reset
B8.  pre-commit install
B9.  pre-commit run --all-files
B10. gitleaks git --verbose .
B11. git filter-repo --path .env --invert-paths
B12. git lfs track "*.iso"
B13. git submodule add git@gitlab.com:team/roles.git roles/common
B14. git clone --recurse-submodules git@gitlab.com:team/infra.git
B15. git submodule update --init --recursive
B16. git clone --filter=blob:none --sparse <url>
B17. git sparse-checkout set k8s/ charts/
B18. git count-objects -vH
B19. git remote prune origin
B20. git fsck
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Кто автор строк 40-60 values.yaml, игнорируя пробелы и перемещения кода
B2.  Найти коммиты, где появлялось/исчезало значение memory: 512Mi, с диффами
B3.  Найти коммиты, чей diff соответствует регулярке (replicas: число)
B4.  Найти коммит, в котором файл был удалён
B5.  Начать бинарный поиск: текущее состояние плохое, тег v1.4.0 — хороший
B6.  Автоматически прогнать bisect скриптом проверки
B7.  Завершить bisect и вернуться на исходную ветку
B8.  Установить хуки pre-commit в текущий репозиторий
B9.  Прогнать все хуки по всем файлам (а не только по изменённым)
B10. Просканировать репозиторий на секреты
B11. Удалить файл .env из всей истории репозитория (переписав хеши)
B12. Отслеживать .iso через Git LFS (запись в .gitattributes)
B13. Добавить внешний репозиторий как субмодуль в roles/common
B14. Клонировать репозиторий вместе с содержимым субмодулей
B15. Доинициализировать субмодули в уже склонированном репозитории
B16. Клонировать без содержимого файлов и с частичной выкладкой
B17. Выложить в рабочий каталог только каталоги k8s/ и charts/
B18. Показать количество объектов и занимаемое место
B19. Удалить remote-tracking ветки, которых больше нет на сервере
B20. Проверить целостность объектов и связность графа
```

</details>

---

### Блок C. Практика

#### C1. 🔑 blame-расследование
```bash
mkdir -p ~/git-lab/t12 && cd ~/git-lab/t12 && git init
cat > values.yaml <<'EOF'
replicas: 2
resources:
  limits:
    memory: 256Mi
EOF
git add . && git commit -m "feat: initial values"
sed -i 's/memory: 256Mi/memory: 512Mi/' values.yaml && git commit -am "fix: raise memory limit"
sed -i 's/replicas: 2/replicas: 4/' values.yaml && git commit -am "feat: scale to 4 replicas"

git blame values.yaml
git log -S "512Mi" --oneline -p
git log --oneline -- values.yaml
git show $(git log -S "512Mi" --format=%h -1)
```

#### C2. ⭐ bisect вручную
```bash
cd ~/git-lab && rm -rf t12-bisect && mkdir t12-bisect && cd t12-bisect && git init
echo "ok" > app.sh && chmod +x app.sh && git add . && git commit -m "c0 good"
for i in $(seq 1 5); do echo "# change $i" >> app.sh; git commit -am "c$i"; done
echo "СЛОМАНО" > app.sh && git commit -am "c6 сломал"
for i in $(seq 7 12); do echo "# change $i" >> app.sh; git commit -am "c$i"; done

git bisect start
git bisect bad
git bisect good $(git log --format=%h | tail -1)
# на каждом шаге: grep -q СЛОМАНО app.sh && git bisect bad || git bisect good
git bisect log
git bisect reset
```

#### C3. bisect автоматический
```bash
cat > check.sh <<'EOF'
#!/usr/bin/env bash
grep -q "СЛОМАНО" app.sh && exit 1 || exit 0
EOF
chmod +x check.sh
git bisect start HEAD $(git log --format=%h | tail -1)
git bisect run ./check.sh
git bisect reset
```
Сколько шагов потребовалось? Сравни с ручным перебором 13 коммитов.

<details><summary>Ответ (C2/C3)</summary>

Ручной bisect на 13 коммитах занимает ~4 шага (log₂13), автоматический — ту же
логику, но без участия человека; `git bisect log` показывает протокол поиска.

</details>

#### C4. 🔑 pre-commit + gitleaks
```bash
cd ~/git-lab/t12
cat > .pre-commit-config.yaml <<'EOF'
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-merge-conflict
      - id: detect-private-key
EOF
pipx install pre-commit 2>/dev/null || pip install --user pre-commit
pre-commit install
pre-commit run --all-files

# проверим, что хук ловит
printf -- "-----BEGIN OPENSSH PRIVATE KEY-----\nfake\n" > id_rsa
git add id_rsa && git commit -m "упс"          # ⭐ что произошло?
git commit -m "упс" --no-verify                 # ⚠️ а так?
```
Вывод: почему проверку нужно дублировать в CI?

<details><summary>Ответ</summary>

Хук `detect-private-key` не даёт закоммитить приватный ключ: коммит прерывается
с ошибкой. С `--no-verify` коммит проходит — именно поэтому нужен тот же сканер в CI,
где обойти проверку нельзя.

</details>

#### C5. Секрет в истории
```bash
cd ~/git-lab && rm -rf t12-secret && mkdir t12-secret && cd t12-secret && git init
echo "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG" > .env
git add . && git commit -m "add env"
echo "код" > app.py && git add . && git commit -m "add app"
git rm --cached .env && echo ".env" > .gitignore && git add . && git commit -m "remove env"

git log --all --oneline -- .env          # ⭐ файл «удалён», но…
git show $(git log --format=%h --all -- .env | tail -1):.env    # секрет достаётся

pipx install git-filter-repo 2>/dev/null || pip install --user git-filter-repo
git filter-repo --path .env --invert-paths --force
git log --all --oneline
git show $(git log --format=%h | tail -1) --stat
```
Запиши: что изменилось с хешами коммитов? что нужно было сделать с самим ключом?

<details><summary>Ответ</summary>

До `filter-repo` секрет достаётся из старого коммита (`git show <хеш>:.env`),
несмотря на `git rm --cached`. После `filter-repo` файла в истории нет, но **все хеши
коммитов изменились** — репозиторий фактически новый; в реальности это требует force-push
и свежих клонов у всех. Сам ключ нужно было немедленно отозвать и перевыпустить.

</details>

#### C6. .gitattributes и окончания строк
```bash
cd ~/git-lab/t12
printf 'line1\r\nline2\r\n' > windows.txt
git add windows.txt && git commit -m "файл с CRLF"
echo '* text=auto eol=lf' > .gitattributes
git add .gitattributes && git commit -m "chore: normalize line endings"
git add --renormalize . && git commit -m "chore: renormalize"
file windows.txt
git diff HEAD~1 --stat
```

#### C7. Submodule
```bash
cd ~/git-lab && git init --bare roles.git
git clone roles.git roles-work && cd roles-work
echo "роль nginx" > nginx.yml && git add . && git commit -m "init role" && git push
cd ~/git-lab/t12
git submodule add ~/git-lab/roles.git roles/common
git status && cat .gitmodules
git commit -m "chore: add submodule"
cd ~/git-lab && git clone t12 t12-clone && ls t12-clone/roles/common     # ⭐ пусто?
cd t12-clone && git submodule update --init --recursive && ls roles/common
```

<details><summary>Ответ</summary>

В свежем клоне `roles/common` пуст: родитель хранит только ссылку и коммит.
После `git submodule update --init --recursive` появляется содержимое. Именно поэтому
клонировать нужно с `--recurse-submodules` (и настраивать `GIT_SUBMODULE_STRATEGY` в CI).

</details>

#### C8. Размер репозитория
```bash
cd ~/git-lab/t12
dd if=/dev/urandom of=big.bin bs=1M count=20 2>/dev/null
git add big.bin && git commit -m "добавил большой файл"
git count-objects -vH
git rm big.bin && git commit -m "удалил большой файл"
git count-objects -vH                    # ⭐ размер уменьшился?
git rev-list --objects --all \
  | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' \
  | awk '$1=="blob"' | sort -k3 -n -r | head -5
```
Объясни результат и назови правильное решение для больших файлов.

<details><summary>Ответ</summary>

После `git rm` размер `.git` не уменьшается: blob остаётся в истории. Правильное
решение — не коммитить такие файлы (LFS/S3/registry), а уже попавшие убирать переписыванием
истории (`git filter-repo`) с последующим `git gc --prune=now`.

</details>

#### C9. CI-поведение (shallow clone)
```bash
cd ~/git-lab && git clone --depth 1 t12 t12-shallow && cd t12-shallow
git log --oneline
git describe --tags 2>&1 | head -2
git fetch --unshallow && git log --oneline | wc -l
```
Как это выглядит в `.gitlab-ci.yml` и когда нужно `GIT_DEPTH: 0`?

<details><summary>Ответ</summary>

В shallow-клоне доступен один коммит, `git describe` не находит тегов.
В GitLab: `variables: GIT_DEPTH: 0` (или `GIT_DEPTH: 50`), в GitHub Actions —
`actions/checkout` с `fetch-depth: 0`. Нужно, когда требуется история: версионирование,
changelog, diff с предыдущим коммитом, `git bisect`.

</details>

#### C10. Проверки в CI
Напиши джобу, которая:
- запускает `gitleaks git`;
- проверяет отсутствие маркеров конфликта;
- гоняет `pre-commit run --all-files`.

<details><summary>Ответ</summary>

Ориентир:
```yaml
security-checks:
  stage: test
  image: python:3.12-alpine
  before_script:
    - pip install pre-commit
  script:
    - grep -rn '^<<<<<<<\|^>>>>>>>' . --exclude-dir=.git && exit 1 || true
    - pre-commit run --all-files
    - docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:latest detect --source /repo --no-git
```

</details>

---

### Блок D. Инциденты

**D1.** Прод сломался «где-то на прошлой неделе», между тегами 180 коммитов.
План действий по шагам.

<details><summary>Ответ</summary>

Зафиксировать симптом и способ проверки (скрипт/команда); найти «хороший» ориентир
(тег последнего рабочего релиза); `git bisect start` → `bad` (сейчас) → `good <тег>`;
по возможности `git bisect run ./check.sh`; найденный коммит изучить (`git show`, MR),
откатить `git revert` и добавить проверку в CI, чтобы не повторилось.

</details>

**D2.** `gitleaks` в CI нашёл ключ в коммите трёхмесячной давности. Порядок действий.

<details><summary>Ответ</summary>

Немедленно отозвать ключ; проверить логи использования (не воспользовались ли им);
уведомить безопасность; принять решение о чистке истории (filter-repo + force-push
+ переклонирование) и обязательно добавить сканер в pre-commit и CI, если его не было
на момент утечки.

</details>

**D3.** Клон репозитория весит 4 ГБ, `git status` тормозит. Диагностика и варианты лечения.

<details><summary>Ответ</summary>

`git count-objects -vH`, поиск крупнейших blob'ов (команда из конспекта),
`git rev-list --objects --all | grep <путь>`. Лечение: убрать большие файлы из истории
(`git filter-repo`), перейти на LFS/внешнее хранилище, `git gc --prune=now`,
для CI — shallow/partial clone, для разработчиков — `--filter=blob:none`.

</details>

**D4.** В CI `semantic-release` падает с `fatal: No names found, cannot describe anything`.
Причина и решение.

<details><summary>Ответ</summary>

Shallow-клон без тегов: `semantic-release` не может определить последнюю версию.
Решение: `GIT_DEPTH: 0` / `fetch-depth: 0` (и `fetch --tags`).

</details>

**D5.** Джоба пайплайна пушит бамп версии в `main`, и это запускает пайплайн заново — цикл.
Как разорвать?

<details><summary>Ответ</summary>

Добавить `[skip ci]` в сообщение коммита бота, либо в `workflow:rules` исключить
коммиты от бота (`$CI_COMMIT_AUTHOR`), либо использовать отдельную ветку/тег для
релизных коммитов.

</details>

**D6.** После клонирования репозитория каталог с общими ролями пустой, плейбуки падают.
Что забыли?

<details><summary>Ответ</summary>

Клонировали без `--recurse-submodules`; нужно `git submodule update --init --recursive`
(в CI — `GIT_SUBMODULE_STRATEGY: recursive`).

</details>

**D7.** Разработчики жалуются: `pre-commit` замедляет коммит на 30 секунд, все ставят
`--no-verify`. Что делать?

<details><summary>Ответ</summary>

Ускорить: оставить в pre-commit только быстрые проверки (форматирование, секреты,
YAML), тяжёлые (полный lint, тесты) перенести в CI; кэшировать окружения хуков;
запускать хуки только по изменённым файлам. Плюс объяснить, что `--no-verify` не спасёт —
CI всё равно поймает.

</details>

**D8.** На Windows-машине коллеги весь файл показывается как изменённый, хотя он правил
одну строку. Причина и лечение.

<details><summary>Ответ</summary>

Разные окончания строк (CRLF на Windows против LF в репозитории) или автоформаттер.
Лечение: `.gitattributes` с `* text=auto eol=lf`, у коллеги `core.autocrlf true`,
затем `git add --renormalize .` одним коммитом.

</details>

**D9.** ArgoCD не может подтянуть репозиторий с манифестами после ротации ключей.
Что именно нужно заменить?

<details><summary>Ответ</summary>

Deploy key репозитория (публичную часть — в настройках репозитория, приватную —
в секрете ArgoCD) либо токен доступа в репозиторном секрете; после ротации нужно обновить
именно этот ключ/секрет, а не личные ключи инженеров.

</details>

**D10.** Джоба в CI пушит в репозиторий, но получает `403`. `CI_JOB_TOKEN` есть.
В чём дело?

<details><summary>Ответ</summary>

`CI_JOB_TOKEN` по умолчанию даёт доступ на чтение; для push нужен токен с правом
записи (Project Access Token / Deploy Token с `write_repository`) или SSH deploy key
с включённой записью, прописанный в переменных CI. Плюс push должен идти по правильному URL
(с токеном) и в незащищённую ветку или с соответствующими правами.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Как найти, кто и когда изменил конкретную строку в конфиге?

<details><summary>Ответ</summary>

`git blame -L <строки> <файл>`, затем `git show <хеш>` для контекста; если строку
переносили — `git blame -w -C` или `git log -S "текст" -p`.

</details>

**2.** ⭐ Как найти коммит, который сломал сборку, если их сотни?

<details><summary>Ответ</summary>

`git bisect`: задать «хороший» и «плохой» коммиты, git бинарным поиском сузит диапазон;
при скриптуемой проверке — `git bisect run ./check.sh` (около log₂N проверок).

</details>

**3.** Что такое git hooks? Приведи примеры использования.

<details><summary>Ответ</summary>

Скрипты, которые git запускает на события (`pre-commit`, `commit-msg`, `pre-push`,
серверные `pre-receive`). Применение: линтеры, проверка формата сообщений, поиск секретов,
запрет push в main. Командой распространяют через `pre-commit`.

</details>

**4.** ⭐ Что делать, если в репозиторий попал секрет?

<details><summary>Ответ</summary>

Сменить секрет (он скомпрометирован), уведомить команду, при необходимости вычистить
историю `git filter-repo`/BFG с force-push и переклонированием, добавить сканер
секретов в pre-commit и CI.

</details>

**5.** Как в git хранить большие файлы?

<details><summary>Ответ</summary>

Через Git LFS (в git — указатель, содержимое в хранилище) либо вообще вне git:
registry, S3, Nexus, артефакты CI.

</details>

**6.** Что такое submodule и какие с ним проблемы?

<details><summary>Ответ</summary>

Вложенный репозиторий, зафиксированный на конкретном коммите. Проблемы: забытый
`--recurse-submodules`, «грязные» состояния, сложность обновления, лишние шаги в CI.

</details>

**7.** Зачем в CI `--depth 1` и когда он мешает?

<details><summary>Ответ</summary>

Чтобы ускорить клонирование в джобе. Мешает, когда нужна история: `git describe`,
changelog, сравнение с предыдущими коммитами, bisect — тогда `GIT_DEPTH: 0`.

</details>

**8.** Что такое deploy key?

<details><summary>Ответ</summary>

SSH-ключ с доступом к одному репозиторию (обычно только на чтение), используемый
серверами, CI и ArgoCD вместо личного ключа сотрудника.

</details>

**9.** Как git используется в GitOps?

<details><summary>Ответ</summary>

Репозиторий с манифестами — источник правды: агент (ArgoCD/Flux) следит за веткой
и приводит кластер в соответствие. Изменение прода = MR в репозиторий, откат = `git revert`.

</details>

**10.** Как уменьшить размер репозитория?

<details><summary>Ответ</summary>

Убрать большие файлы из истории (`git filter-repo`), перевести их в LFS/внешнее
хранилище, выполнить `git gc --prune=now`, использовать shallow/partial clone
и регулярно удалять мёртвые ветки.

</details>
