---
title: "13. Практика: лабы"
description: "Семь практических лаб из роадмапа: репозиторий конспектов, командная работа, релизы, CI, спасательные операции"
---

# 13. Практика: лабы из роадмапа

> Роадмап → 1. Git → **2. Практика**:
> 1. Создать репозиторий
> 2. Пушить конспекты в `.md`
> 3. Регулярно коммитить во время изучения всего остального
>
> Лабы 1-3 — это буквально пункты роадмапа. Лабы 4-7 — то, что превращает «я умею коммитить»
> в «я умею работать с git в команде».

---

## 📋 Список лаб

| № | Лаба | Пункт роадмапа | Время |
|---|------|----------------|-------|
| 1 | 🔑 Репозиторий конспектов на хостинге | «Создать репозиторий» + «пушить конспекты» | 1-1.5 ч |
| 2 | 🔑 Привычка регулярных коммитов (7 дней) | «Регулярно коммитить» | 7 дней по 10 мин |
| 3 | 🔑 Командная работа на двух клонах | ветки, конфликты, pull/push | 1 ч |
| 4 | Релизный сценарий: теги, хотфикс, перенос коммитов | теги, cherry-pick, rebase, revert | 1 ч |
| 5 | Репозиторий приложения из блока Docker + CI по тегу | связка git ↔ CI/CD | 1.5 ч |
| 6 | Спасательная лаба: сломать и починить | reset, reflog, секрет в истории | 40 мин |
| 7 | Правила репозитория: protected main, CODEOWNERS, pre-commit | командные соглашения | 1 ч |

**Проверка готовности:**
```bash
git --version && git config --get user.name && git config --get user.email
ssh -T git@gitlab.com    # или git@github.com
git lg --version 2>/dev/null || git config --get alias.lg
```

---

## 🧪 Лаба 1. Репозиторий конспектов 🔑

*(практика роадмапа, пункты 1 и 2)*

### Что делаем
Публикуем свои конспекты (Linux, Docker, CI/CD, Ansible, Kubernetes, Git) как репозиторий
на GitLab или GitHub — с README, структурой и осмысленной историей.

### Требования
1. SSH-ключ сгенерирован и добавлен в профиль, `ssh -T` отвечает приветствием.
2. Репозиторий `devops-notes` создан **пустым** (без README на стороне хостинга).
3. В корне: `README.md`, `.gitignore`.
4. Каждый раздел — каталог с `00_INDEX.md`.
5. Первый коммит — осмысленный, не «init».
6. `git push -u origin main`, ветка `main` (не `master`).
7. README рендерится и содержит рабочие ссылки на разделы.

### Каркас
```bash
cd ~/Documents/Triple/Life/DevOps      # или где лежат конспекты
git status                             # уже репозиторий? тогда пропусти init

cat > .gitignore <<'EOF'
# Obsidian
.obsidian/workspace.json
.obsidian/cache
.trash/

# ОС и редакторы
.DS_Store
.idea/
.vscode/
*.swp

# временное
*.tmp
*.log
EOF

cat > README.md <<'EOF'
# DevOps: конспекты по роадмапу «Просто DevOps»

Личная база знаний: теория, команды, грабли и задачи с ответами по каждому блоку.
Каждая тема — два файла: конспект `NN_тема.md` и задачи `NN_тема_tasks.md`.

## Разделы

| Блок | Индекс | Статус |
|------|--------|--------|
| 1. Git | [Git/00_INDEX.md](Git/00_INDEX.md) | ✅ |
| 2. Linux | [Linux/00_INDEX.md](Linux/00_INDEX.md) | ✅ |
| 3. Docker | [Docker/00_INDEX.md](Docker/00_INDEX.md) | ✅ |
| 4. CI/CD | [CICD/00_INDEX.md](CICD/00_INDEX.md) | ✅ |
| 5. Ansible | [Ansible/00_INDEX.md](Ansible/00_INDEX.md) | ✅ |
| 6. Kubernetes | [Kubernetes/00_INDEX.md](Kubernetes/00_INDEX.md) | ✅ |

## Как я учусь
1. Читаю конспект, каждую команду выполняю руками на стенде.
2. Решаю задачи без подглядывания, сверяюсь с ответами.
3. Всё, что делаю, коммичу сюда же.

Источник роадмапа: канал «Просто DevOps».
EOF

git add README.md .gitignore
git commit -m "docs: добавлены README и .gitignore для репозитория конспектов"
git add .
git commit -m "docs: конспекты по Linux, Docker, CI/CD, Ansible, Kubernetes, Git"

git remote add origin git@gitlab.com:<логин>/devops-notes.git
git branch -M main
git push -u origin main
```

### ✅ Критерии приёмки
- [ ] `git remote -v` показывает SSH-URL, `git push` проходит без ввода пароля.
- [ ] На странице репозитория виден отрендеренный README, ссылки кликаются.
- [ ] `git log --oneline` — минимум 2 осмысленных коммита, ни одного «init»/«fix».
- [ ] `git status` чистый; `.obsidian/workspace.json` не отслеживается
      (`git check-ignore -v .obsidian/workspace.json`).
- [ ] `git branch -vv` показывает связку `main → origin/main`.

### 🧠 Разбор
Типичные грабли: репозиторий создан с README на хостинге → `refusing to merge unrelated
histories` (лечится `--allow-unrelated-histories` или пересозданием пустого репозитория);
push по HTTPS просит пароль (нужен токен или переход на SSH); кириллица в именах файлов
ломает ссылки в вебе.

---

## 🧪 Лаба 2. Привычка регулярных коммитов 🔑

*(практика роадмапа, пункт 3)*

### Что делаем
Семь дней подряд коммитим учебный прогресс — так, чтобы история читалась как дневник.

### Требования
1. Каждый учебный день — минимум один коммит в `devops-notes`.
2. Сообщения по Conventional Commits: `docs(k8s): конспект по Ingress`,
   `chore(notes): шпаргалка по kubectl`.
3. Каждая тема — отдельная ветка + MR самому себе (см. лабу 7 про правила).
4. В конце недели — тег `notes-v1.0` и обновлённый прогресс в README.
5. Ни одного коммита с сообщением короче 15 символов.

### Каркас дня
```bash
git switch main && git pull
git switch -c docs/k8s-ingress

# ... пишешь конспект ...
git add Kubernetes/12_ingress.md
git commit -m "docs(k8s): конспект по Ingress: контроллеры, правила, TLS"

git push -u origin docs/k8s-ingress
# открыть MR → влить → удалить ветку
git switch main && git pull
```

Раз в неделю:
```bash
git tag -a notes-v1.0 -m "конспекты: закрыты блоки Linux, Docker, CI/CD, Ansible, k8s, Git"
git push origin notes-v1.0
git shortlog -sn
git log --since="1 week ago" --oneline | wc -l
```

### ✅ Критерии приёмки
- [ ] `git log --since="7 days ago" --oneline` — коммиты минимум в 5 днях из 7.
- [ ] Все сообщения соответствуют формату `тип(область): описание`.
- [ ] Есть хотя бы один тег.
- [ ] На графике активности профиля видна регулярность.

### 🧠 Разбор
Смысл пункта роадмапа не в «красивом профиле», а в моторике: `status → add → diff --staged →
commit → push` должно выполняться без раздумий, чтобы на работе git не отнимал внимание
от самой задачи.

---

## 🧪 Лаба 3. Командная работа на двух клонах 🔑

### Что делаем
Моделируем команду из двух человек на одной машине: два клона одного «сервера».
Проходим весь набор ситуаций: параллельные ветки, отклонённый push, конфликт, merge vs rebase.

### Каркас
```bash
mkdir -p ~/git-lab && cd ~/git-lab
git init --bare team.git
git clone team.git alice && git clone team.git bob

cd alice
git config user.name "Alice" && git config user.email "alice@example.com"
cat > config.yml <<'EOF'
service:
  replicas: 2
  timeout: 30
EOF
git add . && git commit -m "feat: initial config" && git push -u origin main

cd ../bob
git config user.name "Bob" && git config user.email "bob@example.com"
git pull
```

### Сценарии (выполнить все)
1. **Параллельные ветки.** Алиса: `feature/replicas` (replicas: 4). Боб: `feature/timeout`
   (timeout: 60). Обе запушить, слить по очереди в `main`.
2. **Отклонённый push.** Оба делают коммит в `main` и пытаются запушить.
   Второй получает `rejected` → `git pull` → push.
3. **Конфликт.** Оба меняют строку `timeout` по-разному → разрешить осознанно.
4. **merge vs rebase.** Повторить сценарий 2 через `git pull --rebase` и сравнить `git lg`.
5. **Уборка.** Удалить влитые ветки локально и на сервере, `git fetch --prune` во втором клоне.
6. **Ревью «вслепую».** Боб смотрит изменения Алисы: `git fetch && git log -p main..origin/main`.

### ✅ Критерии приёмки
- [ ] В `git lg` виден и merge-«ромб», и линейный участок после rebase.
- [ ] Конфликт разрешён осмысленно (обе правки учтены), маркеров в файле нет:
      `grep -rn '^<<<<<<<' . --exclude-dir=.git` → пусто.
- [ ] `git branch -a` в обоих клонах не содержит мёртвых веток.
- [ ] Ты можешь объяснить каждую строку графа.

---

## 🧪 Лаба 4. Релизный сценарий

### Что делаем
Проигрываем жизнь релиза: версия на проде, срочный фикс, перенос коммитов, откат.

### Шаги
```bash
cd ~/git-lab && rm -rf release-lab && mkdir release-lab && cd release-lab && git init
echo "v1" > app.txt && git add . && git commit -m "feat: app v1"
git tag -a v1.0.0 -m "release 1.0.0"

# разработка продолжается
echo "новая фича" >> app.txt && git commit -am "feat: новая фича (в следующий релиз)"
echo "ещё фича" >> app.txt && git commit -am "feat: ещё фича"

# на проде v1.0.0 — нашли баг
git switch -c hotfix/1.0.1 v1.0.0
echo "фикс" >> app.txt && git commit -am "fix: критический баг оплаты"
git tag -a v1.0.1 -m "hotfix 1.0.1"

# фикс должен попасть и в main
git switch main
git cherry-pick -x $(git log --format=%h --grep="критический баг" -1 hotfix/1.0.1)

# релиз 1.1.0
git tag -a v1.1.0 -m "release 1.1.0"
git log --oneline v1.0.1..v1.1.0
git lg
```

Дополнительно:
7. Сделать `git revert` одного из коммитов фичи и объяснить, почему не `reset`.
8. Показать, что изменилось между релизами: `git diff --stat v1.0.0 v1.1.0`.
9. Получить «версию» произвольного коммита: `git describe --tags`.

### ✅ Критерии приёмки
- [ ] Теги `v1.0.0`, `v1.0.1`, `v1.1.0` на правильных коммитах (`git log --oneline --decorate`).
- [ ] Фикс присутствует и в `hotfix/1.0.1`, и в `main` (разными хешами, с пометкой
      `cherry picked from`).
- [ ] Ты можешь объяснить, почему хотфикс делался от тега, а не от `main`.

---

## 🧪 Лаба 5. Репозиторий приложения + CI по тегу

*(связка с блоками Docker и CI/CD)*

### Что делаем
Берём приложение из блока Docker и делаем из него нормальный репозиторий: `.gitignore`,
README, ветки, теги, пайплайн, который собирает образ по тегу.

### Требования
1. Репозиторий `demo-app` с `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.gitignore`.
2. В `.gitignore` — `.env`, `*.log`, артефакты сборки; в репозитории — `.env.example`.
3. README: быстрый старт, переменные окружения таблицей, как собрать образ.
4. `.gitlab-ci.yml`: джобы `lint` (на любой ветке), `build` (на `main`),
   `release` (только по тегу `v*`, образ с тегом версии).
5. Ветка `feature/healthcheck` → MR → merge → тег `v1.0.0` → релизный пайплайн.

### Ключевые куски
```yaml
# .gitlab-ci.yml
stages: [lint, build, release]

lint:
  stage: lint
  image: hadolint/hadolint:latest-debian
  script: [hadolint Dockerfile]

build:
  stage: build
  image: docker:29
  services: [docker:29-dind]
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

release:
  stage: release
  image: docker:29
  services: [docker:29-dind]
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker build -t $CI_REGISTRY_IMAGE:${CI_COMMIT_TAG#v} .
    - docker push $CI_REGISTRY_IMAGE:${CI_COMMIT_TAG#v}
  rules:
    - if: $CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/
```

### ✅ Критерии приёмки
- [ ] Пайплайн на ветке — только `lint`; на `main` — `lint` + `build`; по тегу — `release`.
- [ ] В registry лежит образ с тегом `1.0.0`, совпадающим с git-тегом `v1.0.0`.
- [ ] `.env` не в репозитории, `.env.example` — есть.
- [ ] По образу из registry можно найти коммит (тег/SHA в имени).

---

## 🧪 Лаба 6. Спасательная лаба: сломать и починить

### Что делаем
Намеренно устраиваем четыре аварии и чиним их. Цель — убрать страх перед git.

```bash
cd ~/git-lab && rm -rf rescue && mkdir rescue && cd rescue && git init
for i in 1 2 3 4 5; do echo "line $i" >> work.txt; git add .; git commit -m "работа $i"; done
```

**Авария 1. `reset --hard` снёс три коммита.**
```bash
git reset --hard HEAD~3 && git log --oneline
# почини через reflog
```

**Авария 2. Удалена ветка с работой.**
```bash
git switch -c important && echo "важное" > important.txt && git add . && git commit -m "важная работа"
git switch main && git branch -D important
# найди коммит и восстанови ветку
```

**Авария 3. Коммиты ушли в detached HEAD.**
```bash
git switch --detach HEAD~2 && echo "эксперимент" > exp.txt && git add . && git commit -m "эксперимент"
git switch main
# верни коммит
```

**Авария 4. Секрет в истории.**
```bash
echo "DB_PASSWORD=SuperSecret123" > .env && git add . && git commit -m "конфиг"
echo "код" > app.py && git add . && git commit -m "приложение"
git rm --cached .env && echo ".env" > .gitignore && git add . && git commit -m "убрал .env"
# 1. достань секрет из истории (докажи, что он там)
# 2. вычисти историю git filter-repo
# 3. напиши, что нужно было сделать с самим паролем в реальной жизни
```

### ✅ Критерии приёмки
- [ ] Все четыре аварии устранены, работа не потеряна.
- [ ] Ты можешь назвать команду-спасатель для каждой ситуации, не подглядывая.
- [ ] По аварии 4 сформулирован правильный порядок действий (сначала смена секрета).

---

## 🧪 Лаба 7. Правила репозитория

### Что делаем
Превращаем свой `devops-notes` в репозиторий, который выглядит как рабочий.

### Требования
1. **Protected `main`**: запрет прямого push и force-push; изменения — через MR.
2. **CODEOWNERS** с распределением по каталогам.
3. **Шаблон MR** (`.gitlab/merge_request_templates/default.md` или
   `.github/PULL_REQUEST_TEMPLATE.md`): Что / Зачем / Как проверить / Риски / Чек-лист.
4. **`.pre-commit-config.yaml`**: `check-yaml`, `check-merge-conflict`, `end-of-file-fixer`,
   `trailing-whitespace`, `detect-private-key`, `markdownlint` (по желанию).
5. **CI-джоба** `docs-lint`, проверяющая markdown и отсутствие маркеров конфликта.
6. **CONTRIBUTING.md**: соглашение о ветках, коммитах и мерже (твоя стратегия из темы 09).

### Проверка
```bash
git switch main && echo "тест" >> README.md && git commit -am "test: прямой push" && git push
# ожидаем отказ сервера — правило работает
git reset --hard origin/main

pre-commit run --all-files
```

### ✅ Критерии приёмки
- [ ] Прямой push в `main` отклоняется сервером.
- [ ] Открытый MR автоматически получает шаблон описания и ревьюера из CODEOWNERS.
- [ ] `pre-commit run --all-files` проходит без ошибок.
- [ ] `CONTRIBUTING.md` описывает твой процесс на одну страницу.

---

## 🏁 Что должно остаться после блока

1. Публичный репозиторий `devops-notes` с README, историей регулярных коммитов и тегом.
2. Репозиторий `demo-app` с релизами по тегам и пайплайном, собирающим образ версии.
3. Личный «спасательный» чек-лист: что делать при reset/detached HEAD/секрете в истории.
4. Настроенные правила (protected main, CODEOWNERS, pre-commit) — можно показать на собесе.
5. Умение проговорить процесс «задача → ветка → MR → ревью → merge → тег → деплой».
