---
title: "02. Три области и команды init/add/commit"
description: "Working tree, staging area, репозиторий — и команды init, add, commit, status, log, diff, .gitignore"
---

# 02. Три области и главные команды: init, add, commit

> Роадмап → 1. Git → Теория → **5 главных команд**: `git init` (инициализировать репозиторий),
> `git add` (добавить файлы для следующего коммита), `git commit` (зафиксировать изменения),
> `git push`, `git pull`.
> В этой теме — первые три (локальная работа). `push`/`pull` — в [теме 03](/git/03-remote-repos).
> **После темы ты умеешь:** объяснить, зачем нужен staging, сделать осмысленный коммит,
> читать `git status`/`git log`/`git diff` и настроить `.gitignore`.

---

## 🗺️ Карта темы

```text:no-line-numbers
  WORKING TREE            INDEX (staging)            РЕПОЗИТОРИЙ (.git/objects)
  файлы на диске          «черновик коммита»          история коммитов
 ┌──────────────┐        ┌──────────────────┐        ┌────────────────────────┐
 │ app.py   M   │        │                  │        │  c1 ──► c2 ──► c3      │
 │ Dockerfile   │ ──add──► app.py (готов    │─commit─►          (main) ▲      │
 │ secret.env ✗ │        │        к коммиту)│        │                HEAD    │
 └──────────────┘        └──────────────────┘        └────────────────────────┘
        ▲                         │                              │
        └──── git restore ────────┘                              │
        └──────────── git restore --source=HEAD ─────────────────┘
        └──── git restore --staged <файл>  (убрать из индекса) ──┘

  Статусы файла:
  untracked ──add──► staged ──commit──► tracked/unmodified ──правка──► modified ──add──► staged
     (git о нём                                                                   ↺
      не знает)                                                    (цикл обычной работы)
```

---

## 1. `git init` — создать репозиторий

```bash
mkdir my-notes && cd my-notes
git init
# Initialized empty Git repository in /home/nurik/my-notes/.git/
```

Что произошло: появился каталог `.git` (тема 01, §5). Файлы проекта не тронуты — git просто
начал «наблюдать» за папкой. Коммитов пока ноль.

```bash
git init                       # в текущей папке
git init my-project            # создать папку и репозиторий в ней
git init --bare repo.git       # ⭐ «голый» репозиторий: только .git, без рабочих файлов
```

**Bare-репозиторий** — то, что лежит на сервере GitHub/GitLab: в него пушат, из него клонируют,
в нём никто не редактирует файлы. Ты можешь сделать себе такой на любом сервере с SSH:

```bash
# на сервере
git init --bare /srv/git/notes.git
# на ноутбуке
git remote add origin user@server:/srv/git/notes.git
```

> 💡 Второй способ получить репозиторий — `git clone` (тема 03). `init` используется,
> когда проект начинается у тебя; `clone` — когда он уже существует.

---

## 2. ⭐ Три области — главная идея темы

Это то, чего нет в большинстве «облачных» систем и что сначала кажется лишним усложнением.

| Область | Что это | Команда «перенести дальше» |
|---------|---------|-----------------------------|
| **Working tree** (рабочий каталог) | Файлы, которые ты видишь и правишь | `git add` |
| **Index / Staging area** | Черновик следующего коммита | `git commit` |
| **Repository** (`.git/objects`) | Зафиксированная история | — |

### Зачем нужен staging (вопрос на собесе)

Ты правил пять файлов: три — по задаче «добавить healthcheck», два — «поправить опечатки
в README». Staging позволяет сделать **два осмысленных коммита** вместо одной свалки:

```bash
git add docker-compose.yml Dockerfile healthcheck.sh
git commit -m "add healthcheck to app container"

git add README.md docs/install.md
git commit -m "docs: fix typos"
```

Второй сценарий: `git add -p` — добавить **часть** изменений одного файла (см. §5).
Третий: перед коммитом посмотреть `git diff --staged` — «что именно я сейчас зафиксирую».

> 🎤 **Формулировка для собеса:** «Staging area — это промежуточная область, куда я собираю
> изменения для следующего коммита. Она нужна, чтобы коммит был атомарным и осмысленным:
> из кучи правок в рабочем каталоге я выбираю только относящиеся к одной задаче.»

---

## 3. `git status` — команда, которую жмут чаще всех

```bash
git status
```
```text:no-line-numbers
On branch main
Your branch is up to date with 'origin/main'.

Changes to be committed:          ← в INDEX, попадёт в коммит
  (use "git restore --staged <file>..." to unstage)
        new file:   healthcheck.sh

Changes not staged for commit:    ← изменено, но НЕ в индексе
  (use "git add <file>..." to update what will be committed)
        modified:   docker-compose.yml

Untracked files:                  ← git о них не знает вообще
  (use "git add <file>..." to include in what will be committed)
        .env
```

Git сам подсказывает следующую команду — читай эти подсказки, это лучшая документация.

```bash
git status -s          # короткий формат
```
```text:no-line-numbers
 M docker-compose.yml     # правый столбец = working tree
M  Dockerfile             # левый столбец = index
MM app.py                 # и там, и там (добавил, потом ещё поправил)
A  healthcheck.sh         # добавлен в индекс
?? .env                   # untracked
D  old.txt                # удалён
R  a.txt -> b.txt         # переименован
```

---

## 4. `git add` — положить в индекс

```bash
git add file.txt              # конкретный файл
git add src/                  # каталог рекурсивно
git add .                     # всё из текущего каталога и ниже
git add -A                    # всё по репозиторию, включая удаления
git add '*.yml'               # по маске (кавычки — чтобы маску раскрыл git, а не shell)
git add -u                    # только уже отслеживаемые (не добавит новые файлы)
```

### ⚠️ Грабли `git add .`

`git add .` — самая частая причина случайно закоммиченных секретов, `node_modules/`,
логов и артефактов сборки. Правильный рефлекс: **сначала `git status`, потом `add`,
потом `git diff --staged`, только потом `commit`**.

```bash
git status                     # что вообще есть
git add .
git diff --staged --stat       # что реально уйдёт в коммит
git commit -m "..."
```

### `git add -p` — интерактивно, по кускам

```bash
git add -p app.py
```
Git показывает изменения «ханками» и спрашивает: `y` — взять, `n` — пропустить,
`s` — разбить на более мелкие, `q` — выйти. Так из одного файла с двумя разными правками
делают два коммита. Полезно и как самопроверка: ты просматриваешь свой диff перед коммитом.

---

## 5. `git commit` — зафиксировать

```bash
git commit -m "add healthcheck to app container"
git commit                      # откроет редактор (полезно для длинного описания)
git commit -am "fix typo"       # ⚠️ add + commit ТОЛЬКО для отслеживаемых файлов
git commit --amend              # поправить последний коммит (тема 07)
```

Что происходит:
1. Из индекса собирается объект `tree` (снимок).
2. Создаётся объект `commit`: tree + parent (текущий HEAD) + автор + дата + сообщение.
3. Ветка, на которую смотрит HEAD, **переставляется на новый коммит**.

```text:no-line-numbers
до:    c1 ──► c2 (main ← HEAD)
после: c1 ──► c2 ──► c3 (main ← HEAD)
```

### ⭐ Хорошее сообщение коммита

Плохо: `fix`, `.`, `asdf`, `правки`, `работает!!!`, `коммит`.
Хорошо: **что сделано и зачем**, в повелительном наклонении, первая строка ≤ 50-72 символов.

```text:no-line-numbers
add readiness probe to payment deployment

Без probe трафик приходил в под до готовности БД,
первые 5-10 секунд после деплоя отдавали 502.
Closes #1423
```

Структура: **заголовок** → пустая строка → **тело** (зачем, а не как) → ссылки на задачи.

Стандарт, который любят в CI (Conventional Commits, подробно в [теме 11](/git/11-collaboration)):
```text:no-line-numbers
feat(api): add /healthz endpoint
fix(ci): pin docker image to 24.0
docs: update ansible runbook
chore(deps): bump alpine to 3.20
```

> 💡 Проверка качества сообщения: через полгода ты ищешь, откуда взялся странный таймаут.
> Твоё сообщение поможет или будет написано «fix»?

### Размер коммита

Одна логическая мысль = один коммит. Не «рабочий день = коммит» и не «каждая строка = коммит».
Признак хорошего коммита: его можно **откатить целиком**, и проект останется работоспособным.

---

## 6. `git log` — читать историю

```bash
git log                                  # полный вывод
git log --oneline                        # по строке на коммит
git log --oneline --graph --all --decorate   # ⭐ граф (алиас git lg)
git log -5                               # последние 5
git log --stat                           # + какие файлы и сколько строк
git log -p                               # + полный дифф каждого коммита
git log --author="Nurdaulet"
git log --since="2 weeks ago" --until="yesterday"
git log --grep="healthcheck"             # поиск по СООБЩЕНИЯМ
git log -S "timeout=30"                  # ⭐ поиск по СОДЕРЖИМОМУ: где появилась строка
git log -- path/to/file.yml              # история одного файла
git log --follow -- file.yml             # + история до переименования
git log --format="%h %an %ar %s"         # свой формат
git shortlog -sn                         # кто сколько коммитов сделал
```

`git log -S` — недооценённая команда: «когда и кто добавил в конфиг эту строку» находится
за секунды, даже если файл с тех пор переименовали.

---

## 7. `git diff` — что именно изменилось

```bash
git diff                  # working tree ↔ index  (что НЕ добавлено в индекс)
git diff --staged         # index ↔ HEAD          (что уйдёт в коммит)  (= --cached)
git diff HEAD             # working tree ↔ HEAD   (всё вместе)
git diff main..feature    # разница между ветками
git diff HEAD~3           # с коммитом трёхдавностной давности
git diff --stat           # только сводка по файлам
git diff --word-diff      # по словам — удобно для текста и .md
git diff -- file.yml      # только этот файл
```

Читаем вывод:
```diff
diff --git a/app.py b/app.py
index 83db48f..bf269f4 100644
--- a/app.py          ← «было» (a/)
+++ b/app.py          ← «стало» (b/)
@@ -12,7 +12,7 @@ def main():      ← с 12-й строки, 7 строк было / 7 стало
-    timeout = 30
+    timeout = 60
```

---

## 8. `.gitignore` — что git не должен видеть

Файл в корне репозитория (можно и в подкаталогах) со списком масок:

```text:no-line-numbers
# секреты — НИКОГДА не в репозиторий
.env
*.pem
*.key
secrets.yml
id_rsa*

# зависимости и артефакты сборки
node_modules/
__pycache__/
*.pyc
target/
dist/
build/

# логи и временные файлы
*.log
*.tmp
tmp/

# состояние инструментов
.terraform/
*.tfstate
*.tfstate.backup
.vagrant/
*.retry

# IDE и ОС
.idea/
.vscode/
.DS_Store

# ИСКЛЮЧЕНИЕ из исключения
!.vscode/settings.json     # этот файл всё-таки версионируем
```

Правила:
- `foo/` — только каталог; `foo` — и файл, и каталог;
- `*.log` — по маске; `/foo.txt` — только в корне репозитория;
- `!файл` — исключение из предыдущего правила;
- пустые каталоги git не хранит вообще (кладут файл-заглушку `.gitkeep`).

### ⚠️ Главные грабли `.gitignore`

**`.gitignore` не действует на уже отслеживаемые файлы.** Если ты закоммитил `.env`,
а потом добавил его в `.gitignore` — файл продолжит отслеживаться:

```bash
git rm --cached .env          # убрать из индекса, оставить на диске
echo ".env" >> .gitignore
git commit -m "stop tracking .env"
```
И помни: **из истории он при этом не исчезнет** — секрет считается скомпрометированным
и подлежит смене (тема 12).

Полезное:
```bash
git check-ignore -v путь/к/файлу     # какое правило игнорирует этот файл
git status --ignored                 # показать проигнорированное
```

Готовые шаблоны: `https://github.com/github/gitignore` (Python.gitignore, Terraform.gitignore…).

---

## 9. Работа с файлами через git

```bash
git rm file.txt                # удалить файл и записать удаление в индекс
git rm --cached file.txt       # ⭐ перестать отслеживать, файл оставить на диске
git rm -r --cached .           # перестать отслеживать всё (после правки .gitignore)
git mv old.txt new.txt         # переименовать (= mv + git add обоих)
```

Git не хранит «переименование» как операцию — он видит, что blob тот же, а имя в дереве
другое, и показывает это как rename (`R` в `status`).

---

## 10. Типичный цикл работы (заучить руками)

```bash
git status                       # 1. что у меня происходит
git diff                         # 2. что я наменял
git add файлы                    # 3. собрать коммит
git diff --staged                # 4. проверить, что именно уйдёт
git commit -m "осмысленно"       # 5. зафиксировать
git log --oneline -3             # 6. убедиться
```

Этот цикл повторяется десятки раз в день, и через неделю выполняется на автомате.

---

## 💼 Как это в DevOps

- Первое, что делают с новым конфигом/скриптом: `git init` (если репозитория ещё нет) или
  ветка в существующем. Файлов «просто на сервере» в нормальной практике не существует.
- `.gitignore` для DevOps-репозитория — вопрос безопасности: `*.tfstate` (содержит секреты
  в открытом виде), `*.pem`, `.env`, `kubeconfig`, `*.retry`, `.vault_pass`.
- Осмысленные сообщения коммитов — это не эстетство: при разборе инцидента в 3 часа ночи
  ты читаешь `git log` продового репозитория и ищешь, какое изменение всё сломало.
- Атомарность коммитов = возможность `git revert` одного изменения без сноса соседних.
  В GitOps-репозитории это буквально кнопка «откатить прод».
- `git log -S "строка"` — рабочий инструмент расследования: «откуда взялся этот лимит памяти».
- В команде почти всегда есть соглашение о формате сообщений (Conventional Commits) и линтер
  сообщений в CI — тема 11.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Создать репозиторий | `git init` |
| Голый репозиторий для сервера | `git init --bare repo.git` |
| Что происходит | `git status` / `git status -s` |
| Добавить файл в индекс | `git add file` |
| Добавить всё | `git add -A` (сначала `git status`!) |
| Добавить кусками | `git add -p` |
| Убрать из индекса | `git restore --staged file` |
| Отменить правки в файле | `git restore file` (⚠️ без возврата) |
| Зафиксировать | `git commit -m "сообщение"` |
| Добавить+зафиксировать отслеживаемые | `git commit -am "сообщение"` |
| Поправить последний коммит | `git commit --amend` |
| История кратко / графом | `git log --oneline` / `git lg` |
| История файла | `git log --follow -- file` |
| Найти, где появилась строка | `git log -S "строка"` |
| Разница (не в индексе / в индексе) | `git diff` / `git diff --staged` |
| Перестать отслеживать файл | `git rm --cached file` |
| Почему файл игнорируется | `git check-ignore -v file` |

---

## 🧠 Что запомнить

1. `git init` создаёт `.git` — репозиторий; второй способ получить его — `git clone`.
2. **Три области**: working tree → (`add`) → index → (`commit`) → репозиторий.
3. **Staging нужен для атомарных коммитов**: из всех правок собираешь относящиеся к одной задаче.
4. `git status` — команда №1; она же подсказывает следующую.
5. `git add .` без предварительного `status` — путь к закоммиченным секретам.
6. Коммит = снимок + родитель + автор + сообщение; ветка после коммита двигается вперёд.
7. **Сообщение коммита пишется для будущего себя**: что сделано и зачем, а не «fix».
8. `git log -S` ищет по содержимому изменений — лучший инструмент расследования.
9. `git diff` (не в индексе) vs `git diff --staged` (уйдёт в коммит) — путают постоянно.
10. `.gitignore` **не действует на уже отслеживаемые файлы** — нужен `git rm --cached`.
11. Секреты в `.gitignore` — обязательная гигиена; попавший в историю секрет меняют, а не прячут.

---

## Задачи

> Стенд: `mkdir -p ~/git-lab/t02 && cd ~/git-lab/t02 && git init`
> Правило темы: после каждой команды — `git status` и `git lg`.

---

### Блок A. Теория

**A1.** ⭐ Назови три области git и команды перехода между ними.

<details><summary>Ответ</summary>

Working tree (файлы на диске) → `git add` → Index/staging (черновик коммита) →
`git commit` → репозиторий (история в `.git/objects`). Обратно: `git restore --staged` (из
индекса в рабочий каталог), `git restore` (откатить правку в рабочем каталоге).

</details>

**A2.** ⭐ Зачем нужен staging area? Приведи два сценария, где без него было бы хуже.

<details><summary>Ответ</summary>

(1) В рабочем каталоге правки от двух разных задач — staging позволяет собрать
и закоммитить их раздельно, атомарными коммитами. (2) Перед фиксацией можно просмотреть
`git diff --staged` — ровно то, что попадёт в коммит, и убрать лишнее (`git add -p` позволяет
взять даже часть файла).

</details>

**A3.** В чём разница между `untracked`, `modified`, `staged`, `unmodified`?

<details><summary>Ответ</summary>

`untracked` — git о файле не знает; `modified` — отслеживаемый файл изменён, но
изменения не в индексе; `staged` — изменения добавлены в индекс и уйдут в следующий коммит;
`unmodified` — файл отслеживается и совпадает с HEAD.

</details>

**A4.** Что делает `git init --bare` и где такие репозитории используются?

<details><summary>Ответ</summary>

Создаёт репозиторий без рабочего каталога (только содержимое `.git`). Такие лежат
на серверах: в них пушат и из них клонируют, редактировать файлы в них нельзя.
Именно так устроены репозитории на GitHub/GitLab.

</details>

**A5.** Чем `git add .` отличается от `git add -A` и от `git add -u`?

<details><summary>Ответ</summary>

`git add .` — всё из текущего каталога и ниже (в современных версиях включая удаления);
`git add -A` — всё по всему репозиторию независимо от текущего каталога; `git add -u` — только
уже отслеживаемые файлы (изменения и удаления), новые файлы не добавит.

</details>

**A6.** Что делает `git commit -am "..."` и в каком случае это сработает не так, как ты ждёшь?

<details><summary>Ответ</summary>

`-a` автоматически добавляет в индекс изменения и удаления **отслеживаемых** файлов.
Новые (untracked) файлы не попадут — их нужно добавить явным `git add`.

</details>

**A7.** Что именно происходит внутри git при `git commit` (три шага)?

<details><summary>Ответ</summary>

(1) Из индекса собирается объект `tree` — снимок; (2) создаётся объект `commit`
(tree + parent = текущий HEAD + автор + дата + сообщение); (3) ссылка текущей ветки
переставляется на новый коммит (HEAD едет вместе с ней).

</details>

**A8.** ⭐ Разница между `git diff`, `git diff --staged` и `git diff HEAD`?

<details><summary>Ответ</summary>

`git diff` — working tree против индекса (что ещё не добавлено);
`git diff --staged` — индекс против HEAD (что уйдёт в коммит);
`git diff HEAD` — working tree против последнего коммита (всё вместе).

</details>

**A9.** Как найти коммит, в котором в конфиге появилась строка `timeout: 300`?

<details><summary>Ответ</summary>

`git log -S "timeout: 300" --oneline -p` — поиск по изменению содержимого
(pickaxe). Альтернатива для регулярок: `git log -G "timeout:\s*300"`.

</details>

**A10.** Как посмотреть историю только одного файла, включая период до переименования?

<details><summary>Ответ</summary>

`git log --follow -- путь/к/файлу` (и `-p`, если нужны диффы).

</details>

**A11.** ⭐ Ты добавил `.env` в `.gitignore`, но git продолжает его отслеживать. Почему и что делать?

<details><summary>Ответ</summary>

`.gitignore` действует только на untracked-файлы; уже отслеживаемый файл продолжает
отслеживаться. Нужно `git rm --cached .env` и коммит. Сам секрет из истории при этом не
исчезнет — его нужно считать скомпрометированным и сменить.

</details>

**A12.** Как git хранит пустой каталог? А если очень нужно?

<details><summary>Ответ</summary>

Никак: git версионирует файлы, пустые каталоги не попадают в дерево. Обходной приём —
положить внутрь `.gitkeep` (пустой файл-заглушка, соглашение, а не фича git).

</details>

**A13.** Что означает строка `MM app.py` в выводе `git status -s`?

<details><summary>Ответ</summary>

Левый столбец — состояние в индексе, правый — в рабочем каталоге. `MM` = файл изменён,
добавлен в индекс, а затем изменён ещё раз; в коммит уйдёт только первая версия изменений.

</details>

**A14.** Чем `git rm file` отличается от `rm file` и от `git rm --cached file`?

<details><summary>Ответ</summary>

`rm file` — удалить с диска (git увидит `deleted`, нужно ещё `git add`);
`git rm file` — удалить с диска и сразу записать удаление в индекс;
`git rm --cached file` — перестать отслеживать, файл остаётся на диске.

</details>

**A15.** Какое сообщение коммита хорошее и почему? Сформулируй правило одной фразой.

<details><summary>Ответ</summary>

Хорошее: заголовок до ~50-72 символов, повелительное наклонение, суть изменения,
при необходимости — тело с объяснением «зачем». Правило: **сообщение объясняет причину,
а не пересказывает дифф**.

</details>

**A16.** Что такое «атомарный коммит» и почему это важно для отката?

<details><summary>Ответ</summary>

Коммит, содержащий одно логически законченное изменение. Важно, потому что
`git revert` откатывает коммит целиком: если в нём смешаны три задачи, откатить одну
без остальных нельзя, а история перестаёт быть читаемой.

</details>

**A17.** Пять файлов из `.gitignore`, которые обязаны быть в любом DevOps-репозитории.

<details><summary>Ответ</summary>

`.env`, `*.pem`/`*.key`/`id_rsa*`, `*.tfstate*`, `node_modules/`(или `venv/`,
`__pycache__/`), `*.log`, `.terraform/`, `kubeconfig`, `.vault_pass`.

</details>

---

### Блок B. «Что делает команда»

Слева — команда, справа (сразу под ней) — что она делает.

```bash
B1.  git init --bare /srv/git/notes.git
B2.  git status -s
B3.  git add -p app.py
B4.  git add -u
B5.  git restore --staged config.yml
B6.  git restore config.yml
B7.  git commit -m "feat(ci): add lint stage"
B8.  git commit --amend --no-edit
B9.  git log --oneline --graph --all --decorate
B10. git log -S "timeout=30" --oneline
B11. git log --follow -- deploy/values.yaml
B12. git log --author="Nurdaulet" --since="1 week ago" --stat
B13. git diff --staged --stat
B14. git rm --cached .env
B15. git check-ignore -v secrets.yml
B16. git shortlog -sn
B17. git status --ignored
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Создать голый (серверный) репозиторий — без рабочего каталога
B2.  Короткий статус: две колонки (индекс / рабочий каталог)
B3.  Интерактивно добавить в индекс отдельные куски изменений файла
B4.  Добавить в индекс изменения и удаления только отслеживаемых файлов
B5.  Убрать config.yml из индекса, сохранив правки в рабочем каталоге
B6.  ⚠️ Откатить правки config.yml в рабочем каталоге до состояния индекса (без возврата)
B7.  Зафиксировать индекс с сообщением в формате Conventional Commits
B8.  Переписать последний коммит, оставив прежнее сообщение (обычно — «забыл файл»)
B9.  Граф всей истории по всем веткам с именами веток и тегов
B10. Найти коммиты, где появлялась/исчезала строка timeout=30
B11. История файла values.yaml, включая период до переименования
B12. Коммиты автора за неделю со статистикой по файлам
B13. Сводка изменений, которые уйдут в следующий коммит
B14. Перестать отслеживать .env, оставив файл на диске
B15. Показать, какое правило .gitignore прячет secrets.yml
B16. Число коммитов по авторам, по убыванию
B17. Статус вместе с проигнорированными файлами
```

</details>

---

### Блок C. Практика

#### C1. 🔑 Три области своими руками
```bash
mkdir -p ~/git-lab/t02 && cd ~/git-lab/t02 && git init
echo "версия 1" > file.txt
git status                 # какой статус у file.txt?
git add file.txt
git status                 # а теперь?
echo "версия 2" >> file.txt
git status                 # ⭐ ВНИМАНИЕ: файл в ДВУХ секциях сразу. Почему?
git diff                   # что покажет?
git diff --staged          # а что покажет это?
git commit -m "первая версия"
git status
```
Объясни письменно, что попало в коммит: «версия 1» или «версия 1 + версия 2»? Проверь:
`git show HEAD:file.txt`.

<details><summary>Ответ</summary>

В коммит попадает **«версия 1»** — то, что было в индексе на момент `git add`.
Вторая правка осталась в рабочем каталоге (`git status` покажет её как `modified`).
`git diff` покажет разницу «индекс vs диск» (добавленную «версию 2»), `git diff --staged` —
«индекс vs HEAD» (то есть «версию 1»). Это ключевая иллюстрация того, что индекс — снимок,
а не ссылка на файл.

</details>

#### C2. Атомарные коммиты из мешанины
Создай изменения «в кучу»:
```bash
echo "healthcheck" > healthcheck.sh
echo "# Мой проект" > README.md
echo "опечатка исправлена" >> README.md
echo "FROM alpine" > Dockerfile
```
Сделай **два** осмысленных коммита: один — про healthcheck и Dockerfile, второй — про README.
Проверь `git log --stat`.

#### C3. `git add -p`
```bash
printf "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\n" > app.py
git add app.py && git commit -m "add app.py"
sed -i '1s/.*/line1 ИЗМЕНЕНО/' app.py
sed -i '8s/.*/line8 ИЗМЕНЕНО/' app.py
git add -p app.py          # возьми ТОЛЬКО первое изменение (y, затем n)
git diff --staged          # убедись: в индексе одно изменение
git commit -m "fix line1"
git status                 # второе изменение осталось в рабочем каталоге
```

<details><summary>Ответ</summary>

После `y`/`n` в индексе окажется только первый ханк. `git diff --staged` покажет
изменение line1, `git diff` — оставшееся изменение line8.

</details>

#### C4. Читаем историю
Сделай 6-7 коммитов с разными файлами, затем:
```bash
git log --oneline
git log --stat -3
git log -p -1
git log --format="%h | %an | %ar | %s"
git shortlog -sn
git lg
```

#### C5. Поиск в истории
1. Добавь в `config.yml` строку `timeout: 30`, закоммить.
2. Через два коммита поменяй на `timeout: 300`, закоммить.
3. Найди оба коммита: `git log -S "timeout" --oneline -p`.
4. Найди коммит по слову в сообщении: `git log --grep="timeout"`.

#### C6. 🔑 .gitignore
```bash
cat > .gitignore <<'EOF'
.env
*.log
node_modules/
*.tfstate
EOF
touch .env app.log debug.log secret.tfstate
mkdir node_modules && touch node_modules/lib.js
git status                      # что видно, а что нет?
git status --ignored
git check-ignore -v app.log
git add . && git commit -m "add gitignore"
git ls-files                    # что реально отслеживается?
```

#### C7. ⚠️ Грабли: файл уже отслеживается
```bash
echo "SECRET=12345" > creds.env
git add creds.env && git commit -m "упс"     # СПЕЦИАЛЬНО коммитим
echo "creds.env" >> .gitignore
echo "SECRET=54321" > creds.env
git status                                   # ⭐ файл всё равно modified. Почему?
git rm --cached creds.env
git commit -m "stop tracking creds.env"
git status
git log -p --all -- creds.env                # ⭐ секрет ВСЁ ЕЩЁ в истории
```
Вывод сформулируй сам: что нужно было сделать с паролем `12345` в реальной жизни?

<details><summary>Ответ</summary>

Файл уже отслеживался, поэтому `.gitignore` на него не влияет. После `git rm --cached`
git перестаёт следить за ним, но коммит с `SECRET=12345` остаётся в истории и доступен
`git show`/`git log -p`. В реальной жизни пароль `12345` нужно **немедленно сменить/отозвать** —
он считается утёкшим; чистка истории (`git filter-repo`) — вторично.

</details>

#### C8. Переименование и удаление
```bash
git mv README.md DOCS.md
git status -s                 # какая буква?
git commit -m "rename README to DOCS"
git log --follow --oneline -- DOCS.md
git rm DOCS.md
git status -s
git commit -m "remove DOCS"
git show HEAD~1:DOCS.md       # файл удалён, но доступен из истории
```

<details><summary>Ответ</summary>

`git mv` даёт статус `R` (renamed). После `git rm` — `D`. Содержимое удалённого файла
достаётся из истории: `git show HEAD~1:DOCS.md`.

</details>

#### C9. Сообщения коммитов
Перепиши плохие сообщения в хорошие:
```text:no-line-numbers
1. "fix"
2. "изменения"
3. "добавил файл"
4. "не работает"
5. "final version 2 РАБОЧИЙ"
6. "up"
```

<details><summary>Ответ</summary>

Варианты: 1. `fix(nginx): correct upstream port 8080 → 8000`; 2. `refactor(ansible):
split webserver role into tasks files`; 3. `feat(ci): add trivy scan job`;
4. `fix(k8s): add readiness probe to payment deployment`; 5. `chore(release): prepare v2.0.0`;
6. `docs: update README with local setup steps`.

</details>

#### C10. Bare-репозиторий «как на сервере»
```bash
cd ~/git-lab
git init --bare server.git
ls server.git                          # где рабочие файлы?
cd t02 && git remote add origin ~/git-lab/server.git
git push -u origin main
cd ~/git-lab && git clone server.git clone-test && ls clone-test
```
Объясни, чем содержимое `server.git` отличается от `.git` в обычном репозитории.

<details><summary>Ответ</summary>

В `server.git` нет рабочих файлов — только то, что обычно лежит внутри `.git`:
`objects/`, `refs/`, `HEAD`, `config`. Поэтому в bare-репозиторий можно пушить любую ветку,
не боясь конфликтов с чьим-то рабочим каталогом.

</details>

---

### Блок D. Инциденты

**D1.** Ты сделал `git add .` и только потом заметил, что там `id_rsa` и `node_modules/`.
Коммита ещё не было. Как всё поправить?

<details><summary>Ответ</summary>

`git restore --staged .` (или `git rm --cached -r .`) — очистить индекс, затем добавить
нужное в `.gitignore` и делать `git add` выборочно. Файлы на диске не пострадают.

</details>

**D2.** Коммит сделан, но не запушен, и в нём лежит `.env` с паролем. Порядок действий?

<details><summary>Ответ</summary>

Коммит не запушен, значит история локальная: `git rm --cached .env`,
добавить в `.gitignore`, затем либо `git commit --amend` (если это последний коммит и он один),
либо `git reset --soft HEAD~1` и пересобрать коммит без секрета (тема 07).
Пароль всё равно лучше сменить — он побывал в объектах репозитория.

</details>

**D3.** Коммит запушен в общий репозиторий, в нём `AWS_SECRET_ACCESS_KEY`.
Что делать в первую очередь и почему «удалить файл новым коммитом» недостаточно?

<details><summary>Ответ</summary>

Первым делом — **отозвать и перевыпустить ключ** (в AWS: деактивировать access key).
Удаление файла новым коммитом не помогает: старый коммит остаётся в истории, и все, кто
клонировал/форкнул, уже имеют секрет. Далее — чистка истории (`git filter-repo`/BFG),
force-push, повторный клон у всех, включение сканера секретов в CI (тема 12).

</details>

**D4.** `git commit` открыл vim, и ты не знаешь, как выйти. Что нажимать?
Как сделать так, чтобы редактором был nano?

<details><summary>Ответ</summary>

В vim: `Esc`, затем `:wq` (сохранить и выйти) или `:q!` (отменить коммит).
Сменить редактор: `git config --global core.editor "nano"`.

</details>

**D5.** `git commit -am "fix"` не включил новый файл `newfile.py`. Почему?

<details><summary>Ответ</summary>

`-a` берёт только отслеживаемые файлы; `newfile.py` ещё untracked. Нужно `git add newfile.py`.

</details>

**D6.** Разработчик жалуется: «Я добавил файл в .gitignore, а он всё равно коммитится».
Диагностика в две команды.

<details><summary>Ответ</summary>

`git check-ignore -v путь` (покажет правило или ничего) и `git ls-files путь`
(покажет, что файл отслеживается). Если файл в `ls-files` — лечение `git rm --cached`.

</details>

**D7.** `git status` показывает `deleted: config.yml`, хотя файл на месте. Что произошло?

<details><summary>Ответ</summary>

Файл удалили и вернули не через git, либо удалили в индексе (`git rm --cached`),
либо файл на диске отличается регистром/это другой путь. Проверить `git status -s` и
`git diff --staged`; вернуть — `git restore --staged --worktree config.yml`.

</details>

**D8.** В репозиторий попал каталог `venv/` на 400 МБ. Коммит последний, не запушен.
Как убрать и как предотвратить повторение?

<details><summary>Ответ</summary>

`git reset --soft HEAD~1` (или `--mixed`), добавить `venv/` в `.gitignore`,
`git rm -r --cached venv`, закоммитить заново. Предотвращение: `.gitignore` из шаблона
до первого коммита, проверка `git status` перед `add`, `git diff --staged --stat` перед commit.

</details>

**D9.** `git log` показывает коммиты коллеги как `unknown <>`. Что у него не настроено?

<details><summary>Ответ</summary>

У него не заданы `user.name`/`user.email` (или заданы пустыми). Лечится
`git config --global user.name/…email`; уже сделанные коммиты правятся только переписыванием
истории.

</details>

**D10.** После `git restore file.py` пропали 40 минут работы. Можно ли вернуть? Что делать,
чтобы такое не повторялось?

<details><summary>Ответ</summary>

`git restore file.py` затирает незакоммиченные правки — git их не видел, вернуть
нельзя (только из бэкапа IDE/Local History). Профилактика: коммитить чаще, использовать
`git stash` вместо отката, а «черновые» состояния хранить в ветке-черновике.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Что такое staging area и зачем он нужен?

<details><summary>Ответ</summary>

Промежуточная область между рабочим каталогом и репозиторием: туда `git add` кладёт
изменения, которые попадут в следующий коммит. Нужна, чтобы коммиты были атомарными
и чтобы перед фиксацией можно было проверить ровно то, что уйдёт в историю.

</details>

**2.** Разница между `git add` и `git commit`?

<details><summary>Ответ</summary>

`add` кладёт изменения в индекс (готовит коммит), `commit` фиксирует содержимое индекса
в истории как новый коммит.

</details>

**3.** Что делает `git commit -a` и когда это не сработает?

<details><summary>Ответ</summary>

Автоматически добавляет изменения отслеживаемых файлов; не сработает для новых (untracked)
файлов — их нужно добавить явно.

</details>

**4.** Как отменить `git add`?

<details><summary>Ответ</summary>

`git restore --staged <файл>` (старый вариант — `git reset HEAD <файл>`). Изменения
останутся в рабочем каталоге.

</details>

**5.** Разница между `git diff` и `git diff --staged`?

<details><summary>Ответ</summary>

`git diff` — что изменено, но не добавлено в индекс; `git diff --staged` — что добавлено
в индекс и уйдёт в коммит.

</details>

**6.** Как посмотреть, кто и когда добавил конкретную строку в файл?

<details><summary>Ответ</summary>

`git blame файл` (кто автор каждой строки) и затем `git show <хеш>`; для поиска появления
строки — `git log -S "строка" -p`.

</details>

**7.** Что такое `.gitignore` и почему он не помогает для уже отслеживаемых файлов?

<details><summary>Ответ</summary>

Список масок файлов, которые git не должен отслеживать. На уже отслеживаемые файлы он
не влияет, потому что они уже в индексе — нужно `git rm --cached`.

</details>

**8.** Как перестать отслеживать файл, не удаляя его с диска?

<details><summary>Ответ</summary>

`git rm --cached <файл>` + запись в `.gitignore` + коммит.

</details>

**9.** Каким должно быть сообщение коммита?

<details><summary>Ответ</summary>

Заголовок в повелительном наклонении до ~50-72 символов, объясняющий суть; при необходимости
тело с причиной изменения и ссылкой на задачу. Часто по стандарту Conventional Commits.

</details>

**10.** Что такое атомарный коммит?

<details><summary>Ответ</summary>

Коммит с одним логически законченным изменением, который можно откатить целиком
без побочных эффектов.

</details>
