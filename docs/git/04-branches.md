---
title: "04. Ветки и слияние"
description: "branch, switch/checkout, merge, fast-forward и трёхстороннее слияние, detached HEAD"
---

# 04. Ветки и слияние: branch, switch/checkout, merge

> Роадмап → 1. Git → Теория → Концепции: **«Ветки (branches) — создание, переключение,
> слияние»**; команды `git checkout`, `git merge`.
> **После темы ты умеешь:** объяснить, что ветка — это указатель, создавать и переключать
> ветки, понимать разницу fast-forward и трёхстороннего слияния, выбираться из detached HEAD.

---

## 🗺️ Карта темы

```text:no-line-numbers
1. Создали ветку feature — это просто НОВЫЙ УКАЗАТЕЛЬ на текущий коммит:

   c1 ──► c2 ──► c3   ← main
                  ▲
                  └── feature        (HEAD → main)

2. Переключились (git switch feature) и сделали два коммита:

   c1 ──► c2 ──► c3   ← main
                   \
                    └► c4 ──► c5   ← feature   (HEAD → feature)

3a. main не менялся → git merge feature из main = FAST-FORWARD (просто перемотка):

   c1 ──► c2 ──► c3 ──► c4 ──► c5   ← main, feature

3b. main ушёл вперёд → ТРЁХСТОРОННЕЕ слияние, появляется merge-коммит M с ДВУМЯ родителями:

   c1 ──► c2 ──► c3 ──► c6 ──────► M   ← main
                   \               ↗
                    └► c4 ──► c5 ─┘    ← feature
```

---

## 1. Что такое ветка (ещё раз, потому что это главное)

**Ветка — файл с хешем коммита.** Проверь:

```bash
cat .git/refs/heads/main        # 40 символов — и всё
git branch                      # список локальных веток, * = текущая
```

Следствия, из которых растёт вся работа с ветками:
- создание ветки **мгновенно и бесплатно** (записать 41 байт);
- при коммите двигается **та ветка, на которую смотрит HEAD**;
- удаление ветки не удаляет коммиты — исчезает только указатель;
- «перенести ветку» = переписать в файле другой хеш (`git reset`, тема 07).

```text:no-line-numbers
HEAD ──► refs/heads/feature ──► c5 ──► c4 ──► c3 ──► ...
 «я здесь»     «ветка»        «коммиты»
```

---

## 2. Создание и переключение

Современные команды (git 2.23+) — `switch` и `restore`; старая универсальная — `checkout`.

```bash
git branch feature/login              # создать ветку, НЕ переключаясь
git switch feature/login              # переключиться
git switch -c feature/login           # ⭐ создать + переключиться (самое частое)
git switch -                          # вернуться на предыдущую ветку
git switch main

# старый стиль (встретишь в 90% статей и у коллег)
git checkout -b feature/login         # = git switch -c
git checkout main                     # = git switch main
```

| Команда | Что делает |
|---------|-----------|
| `git branch` | Список веток |
| `git branch -v` | + последний коммит каждой |
| `git branch -vv` | + upstream и ahead/behind |
| `git branch -a` | + удалённые (`origin/*`) |
| `git branch --merged` | Ветки, уже влитые в текущую (можно удалять) |
| `git branch --no-merged` | Ещё не влитые (осторожно с удалением) |
| `git branch -m новое-имя` | Переименовать текущую ветку |
| `git branch -d feature` | Удалить **влитую** ветку |
| `git branch -D feature` | ⚠️ Удалить принудительно (даже невлитую) |

### Что происходит при переключении

1. Git берёт снимок целевого коммита и **меняет файлы в рабочем каталоге**.
2. Двигает `HEAD` на новую ветку.

Незакоммиченные изменения при этом:
- если они не мешают — «переезжают» с тобой (git разрешит переключение);
- если мешают (файл различается в ветках) — git откажется:
  `error: Your local changes would be overwritten by checkout`.
  Варианты: закоммитить, спрятать (`git stash`, тема 07) или отменить правки.

### Именование веток (соглашение, но соблюдают все)

```text:no-line-numbers
feature/add-prometheus-scrape      функциональность
fix/nginx-upstream-timeout         исправление
hotfix/payment-500                 срочное исправление прода
release/1.4.0                      подготовка релиза
chore/bump-alpine-3.20             рутина
docs/update-runbook                документация
NURIK-123-add-healthcheck          если в команде трекер задач (Jira)
```
Не используй пробелы и кириллицу; слова — через дефис; префикс говорит о типе работы.

---

## 3. `HEAD` и detached HEAD

```bash
cat .git/HEAD          # ref: refs/heads/main   ← нормальное состояние
git switch --detach c3
cat .git/HEAD          # a1b2c3d…               ← detached HEAD: указывает на КОММИТ
```

Detached HEAD случается при `git checkout <хеш>`, `git checkout v1.0.0`, `git checkout origin/main`
или во время rebase/bisect. Ты можешь смотреть и даже коммитить, но **новые коммиты не
принадлежат ни одной ветке** — потеряешь указатель, потеряешь коммиты (спасает reflog, тема 07).

```text:no-line-numbers
   c1 ──► c2 ──► c3 ──► c4   ← main
                  ▲
                 HEAD          ← «вне веток»: коммит отсюда никуда не привяжется
```

Выход:
```bash
git switch main                 # просто уйти (если ничего не коммитил)
git switch -c experiment        # ⭐ сохранить сделанные коммиты в новую ветку
```

Git при входе в detached HEAD печатает подробное предупреждение — читай его, там ровно это.

---

## 4. ⭐ `git merge` — слияние

Слияние делается **в ту ветку, где ты стоишь**:

```bash
git switch main            # 1. перейти КУДА сливаем
git merge feature/login    # 2. указать, ЧТО сливаем
```

### Случай А. Fast-forward (перемотка)

Если `main` не двигалась с момента создания ветки, git просто **переставляет указатель**:

```text:no-line-numbers
до:    c1 ──► c2 ──► c3 (main) ──► c4 ──► c5 (feature)
после: c1 ──► c2 ──► c3 ──► c4 ──► c5 (main, feature)
```
```text:no-line-numbers
Updating c3..c5
Fast-forward
 login.py | 12 ++++++++++++
```
Нового коммита нет, история линейная. По графу потом не видно, что была ветка.

### Случай Б. Трёхстороннее слияние (3-way merge)

Если обе ветки ушли вперёд, git берёт **три точки**: общего предка (merge base) и вершины
обеих веток, объединяет изменения и создаёт **merge-коммит с двумя родителями**:

```text:no-line-numbers
  c3 ──► c6 ──────────► M (main)     M.parents = [c6, c5]
    \                  ↗
     └► c4 ──► c5 ────┘ (feature)
```
```text:no-line-numbers
Merge made by the 'ort' strategy.
 login.py | 12 ++++++++++++
```
Если правки пересеклись — **конфликт** (тема 05).

### Полезные флаги

```bash
git merge --no-ff feature        # ⭐ всегда создавать merge-коммит (видно, что была ветка)
git merge --ff-only feature      # только перемотка; иначе отказ (для «чистой» истории)
git merge --squash feature       # собрать все изменения ветки в ОДИН коммит (без merge-коммита)
git merge --abort                # отменить начатое слияние (при конфликте)
git merge --no-commit feature    # слить, но дать посмотреть перед коммитом
git merge -m "merge feature/login into main" feature
```

`--no-ff` — то, что делают кнопкой «Merge» в GitLab/GitHub по умолчанию для MR:
в истории остаётся явный след «здесь влили ветку с задачей».

```text:no-line-numbers
  --no-ff:                              --squash:
  c3 ──► c6 ──► M (main)                c3 ──► c6 ──► S (main)   ← S = один коммит со всеми
    \          ↗                          \                        изменениями ветки,
     └► c4 ─► c5 (feature)                 └► c4 ─► c5 (feature)   родитель ОДИН
```

---

## 5. Удаление веток

```bash
git branch -d feature/login            # безопасно: откажется, если не влита
git branch -D feature/login            # принудительно (коммиты останутся в reflog ~90 дней)
git push origin --delete feature/login # удалить на сервере
git fetch --prune                      # убрать мёртвые origin/* у себя
```

Уборка влитых веток пачкой:
```bash
git branch --merged main | grep -vE '^\*|main|master' | xargs -r git branch -d
```

> 💡 Удаление ветки не удаляет коммиты сразу: они становятся «недостижимыми» и живут
> до сборки мусора (`git gc`, по умолчанию ~90 дней для reflog). Вернуть — тема 07.

---

## 6. Полезные команды вокруг веток

```bash
git switch -c feature/x origin/main       # ветка от свежего состояния сервера
git branch feature/y c3                   # ветка от конкретного коммита
git log --oneline main..feature           # что есть в feature, но нет в main
git log --oneline feature..main           # и наоборот
git diff main...feature                   # ⭐ изменения ветки относительно ТОЧКИ ВЕТВЛЕНИЯ
git merge-base main feature               # где ветки разошлись
git branch --contains c4                  # в каких ветках есть этот коммит
git log --graph --oneline --all --decorate
```

Три точки в `git diff main...feature` — частый вопрос: `..` сравнивает две вершины,
`...` сравнивает ветку с **общим предком** (именно это показывает MR в GitLab).

---

## 7. Зачем ветки в DevOps-репозитории

```text:no-line-numbers
main ──────────●──────────●──────────●────────►   ← то, что в проде / применяется ArgoCD
                \        ↗ \        ↗
   feature/add-hpa ─────┘   \      /
                  fix/pin-image-tag ───┘
```

- **`main` защищён**: прямой push запрещён, изменения — только через MR с ревью и CI.
- Каждая задача — своя ветка: можно параллельно править манифесты, пайплайн и роли Ansible,
  не мешая друг другу.
- Ветка = единица ревью и единица отката. Слили `--no-ff` → в истории видно границы задачи →
  `git revert -m 1 <merge-коммит>` откатывает её целиком.
- В GitOps ветка соответствует окружению или изменению: MR с изменением манифеста и есть
  «заявка на изменение прода», а merge — её применение.

---

## 💼 Как это в DevOps

- Правило «одна задача — одна ветка» экономит нервы при инциденте: нужно срочно откатить
  одно изменение, а не разбирать, что ещё приехало вместе с ним.
- Долгоживущие ветки — главный источник ад-конфликтов. Норма: ветка живёт 1-3 дня,
  регулярно подтягивает `main` (`git merge main` или `git rebase main`).
- Названия веток попадают в пайплайны: по `$CI_COMMIT_REF_NAME` часто строятся правила
  (например, деплой на stage только из `release/*`), поэтому соглашение об именовании —
  не косметика.
- `git branch --merged` перед уборкой — рутина техдолга: в живом репозитории через полгода
  сотни мёртвых веток.
- На собесе часто просят нарисовать граф до и после merge — потренируйся рисовать
  fast-forward и 3-way на бумаге.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Список веток | `git branch` / `-a` / `-vv` |
| Создать и перейти | `git switch -c feature/x` (старое: `git checkout -b`) |
| Перейти | `git switch main` |
| Вернуться на предыдущую | `git switch -` |
| Ветка от удалённой | `git switch -c feature/x origin/main` |
| Переименовать текущую | `git branch -m new-name` |
| Влить ветку в текущую | `git merge feature/x` |
| Влить всегда с merge-коммитом | `git merge --no-ff feature/x` |
| Влить одним коммитом | `git merge --squash feature/x` + `git commit` |
| Отменить начатое слияние | `git merge --abort` |
| Удалить влитую ветку | `git branch -d feature/x` |
| Удалить ветку на сервере | `git push origin --delete feature/x` |
| Где ветки разошлись | `git merge-base main feature/x` |
| Что в ветке нового | `git log --oneline main..feature/x` |
| Изменения ветки как в MR | `git diff main...feature/x` |
| Выйти из detached HEAD с сохранением | `git switch -c rescue` |

---

## 🧠 Что запомнить

1. **Ветка — указатель на коммит**; создание бесплатно, поэтому ветвятся на каждую задачу.
2. `HEAD` указывает на текущую ветку; коммит двигает именно её.
3. `git switch -c <имя>` — создать и перейти; `checkout` делает то же, но перегружен смыслами.
4. **Detached HEAD** — HEAD смотрит на коммит, а не на ветку; коммиты здесь не привязаны
   ни к чему. Спасение — `git switch -c <имя>`.
5. Слияние выполняется **в текущую ветку**: сначала `switch` куда, потом `merge` что.
6. **Fast-forward** — перемотка указателя, когда целевая ветка не двигалась; merge-коммита нет.
7. **3-way merge** — общий предок + две вершины → merge-коммит с двумя родителями.
8. `--no-ff` сохраняет в истории факт существования ветки; `--squash` схлопывает её в один коммит.
9. `git branch -d` удаляет только влитую ветку, `-D` — любую; коммиты при этом не пропадают сразу.
10. `git diff main...feature` (три точки) показывает ровно то, что показывает MR.
11. Долгоживущая ветка = тяжёлые конфликты; синхронизируйся с `main` каждый день.

---

## Задачи

> Стенд: `mkdir -p ~/git-lab/t04 && cd ~/git-lab/t04 && git init`
> Правило темы: **после каждой команды — `git lg`**. Рисуй граф на бумаге и сверяй.

---

### Блок A. Теория

**A1.** ⭐ Что такое ветка в git с точки зрения `.git`? Почему создание ветки «ничего не стоит»?

<details><summary>Ответ</summary>

Файл в `.git/refs/heads/<имя>` с хешем коммита (41 байт). Ничего не копируется —
поэтому создание мгновенно, в отличие от VCS, где ветка была копией дерева.

</details>

**A2.** Что происходит с веткой и HEAD при `git commit`?

<details><summary>Ответ</summary>

Создаётся коммит, родителем которого становится текущий; ссылка ветки, на которую
указывает HEAD, переставляется на новый коммит; HEAD продолжает указывать на ту же ветку.

</details>

**A3.** Чем `git switch` отличается от `git checkout`? Почему появились `switch`/`restore`?

<details><summary>Ответ</summary>

`checkout` перегружен: он и переключает ветки, и восстанавливает файлы, и отвязывает
HEAD. В 2.23 его разделили: `switch` — только ветки, `restore` — только файлы. Логика
не изменилась, `checkout` работает и остаётся в документации/статьях.

</details>

**A4.** ⭐ Что такое detached HEAD? Как в него попасть (три способа) и как выйти, сохранив коммиты?

<details><summary>Ответ</summary>

Состояние, когда HEAD указывает прямо на коммит, а не на ветку. Способы попасть:
`git checkout <хеш>`, `git checkout v1.0.0` (тег), `git checkout origin/main`,
`git switch --detach`, а также внутри rebase/bisect. Выход с сохранением работы:
`git switch -c <новая-ветка>` (коммиты остаются). Если уже ушёл — найти хеш в `git reflog`.

</details>

**A5.** Что произойдёт с незакоммиченными изменениями при переключении ветки?

<details><summary>Ответ</summary>

Если файлы, которые ты правил, не различаются между ветками — изменения «переезжают»
вместе с тобой. Если различаются — git откажет с `Your local changes would be overwritten`.
Тогда: закоммитить, `git stash`, либо отменить правки.

</details>

**A6.** ⭐ Объясни разницу fast-forward и трёхстороннего слияния. Нарисуй граф для каждого.

<details><summary>Ответ</summary>

Fast-forward: целевая ветка не двигалась с точки ветвления → git просто переставляет
указатель на вершину сливаемой ветки, нового коммита нет, история линейная.
3-way: обе ветки ушли вперёд → git берёт общего предка и две вершины, объединяет изменения
и создаёт merge-коммит с двумя родителями.
```text:no-line-numbers
FF:   c1─c2─c3(main)─c4─c5(feature)   →   c1─c2─c3─c4─c5(main,feature)
3way: c3─c6(main)  и  c3─c4─c5(feature) →  c6 и c5 → M(main), M.parents=[c6,c5]
```

</details>

**A7.** Что такое merge base и как её найти командой?

<details><summary>Ответ</summary>

Общий предок сливаемых веток — точка, от которой они разошлись.
`git merge-base main feature`.

</details>

**A8.** Сколько родителей у обычного коммита, у merge-коммита, у самого первого коммита?

<details><summary>Ответ</summary>

Обычный — один родитель; merge-коммит — два (бывает и больше, «octopus merge»);
самый первый коммит репозитория — ноль.

</details>

**A9.** Зачем нужен `--no-ff`, если git и так может слить перемоткой?

<details><summary>Ответ</summary>

Чтобы в истории остался явный след «здесь была ветка с задачей»: видны границы задачи,
её можно откатить одним `git revert -m 1 <merge>`, и по графу читается процесс.
При fast-forward эта информация теряется.

</details>

**A10.** Что делает `git merge --squash` и чем результат отличается от обычного merge?

<details><summary>Ответ</summary>

Берёт суммарные изменения ветки, кладёт их в индекс и ждёт обычного `git commit` —
получается **один** коммит с одним родителем. Связи с исходными коммитами ветки нет,
merge-коммита нет, git не считает ветку влитой (`branch -d` будет ругаться).

</details>

**A11.** ⭐ Разница между `git diff main..feature` и `git diff main...feature`?

<details><summary>Ответ</summary>

`main..feature` — разница между двумя вершинами (включая изменения, которые
появились в main после ветвления, — с обратным знаком). `main...feature` — разница между
общим предком и вершиной feature, то есть «что сделала ветка». Именно `...` показывает MR/PR.

</details>

**A12.** В какую ветку попадёт результат `git merge feature`, если ты стоишь на `main`?

<details><summary>Ответ</summary>

В `main` — merge всегда вливает указанную ветку в текущую.

</details>

**A13.** Почему `git branch -d` иногда отказывается удалять ветку? Чем отличается `-D`?

<details><summary>Ответ</summary>

`-d` отказывается, если в ветке есть коммиты, отсутствующие в текущей ветке
(их можно потерять). `-D` удаляет принудительно.

</details>

**A14.** Удаляются ли коммиты при удалении ветки?

<details><summary>Ответ</summary>

Нет. Удаляется только указатель. Коммиты становятся недостижимыми и живут
до сборки мусора; найти их можно через `git reflog` (обычно ~90 дней).

</details>

**A15.** Как узнать, какие ветки уже влиты в `main` и можно удалить?

<details><summary>Ответ</summary>

`git branch --merged main` (влитые, безопасно удалять) и `git branch --no-merged main`.

</details>

**A16.** Как создать ветку от конкретного старого коммита? От состояния сервера?

<details><summary>Ответ</summary>

`git branch feature/x <хеш>` / `git switch -c feature/x <хеш>`;
от сервера: `git fetch && git switch -c feature/x origin/main`.

</details>

**A17.** Почему долгоживущие ветки — проблема? Что с этим делают?

<details><summary>Ответ</summary>

Чем дольше ветка живёт, тем сильнее расходится с `main` и тем больше конфликтов
при слиянии, причём разрешать их приходится в коде, который автор уже забыл. Лечение:
короткие ветки (1-3 дня), ежедневная синхронизация с `main` (`merge`/`rebase`),
дробление задач, feature-флаги вместо долгих веток.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  git branch
B2.  git branch -vv
B3.  git branch -a
B4.  git switch -c feature/add-hpa
B5.  git switch -
B6.  git switch --detach HEAD~2
B7.  git branch -m fix/typo
B8.  git branch feature/x 9a8b7c6
B9.  git switch -c feature/y origin/main
B10. git merge --no-ff feature/add-hpa
B11. git merge --ff-only origin/main
B12. git merge --squash feature/docs
B13. git merge --abort
B14. git branch --merged main
B15. git branch --no-merged main
B16. git branch --contains 9a8b7c6
B17. git merge-base main feature/x
B18. git log --oneline main..feature/x
B19. git diff main...feature/x
B20. git branch -D feature/dead
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Список локальных веток (* — текущая)
B2.  Локальные ветки + upstream + отставание/опережение
B3.  Все ветки, включая remote-tracking (origin/*)
B4.  Создать ветку feature/add-hpa и сразу переключиться
B5.  Вернуться на предыдущую ветку
B6.  Отвязать HEAD и встать на коммит «два назад» (detached HEAD)
B7.  Переименовать ТЕКУЩУЮ ветку в fix/typo
B8.  Создать ветку feature/x, указывающую на коммит 9a8b7c6
B9.  Создать ветку от состояния origin/main и переключиться
B10. Слить feature/add-hpa в текущую ветку, обязательно с merge-коммитом
B11. Влить origin/main только перемоткой; если не получится — ошибка, ничего не менять
B12. Взять суммарные изменения feature/docs в индекс, коммит сделать вручную
B13. Прервать начатое (конфликтное) слияние и вернуть состояние до merge
B14. Ветки, полностью влитые в main (кандидаты на удаление)
B15. Ветки, ещё не влитые в main
B16. В каких ветках присутствует коммит 9a8b7c6
B17. Найти общего предка main и feature/x
B18. Коммиты, которые есть в feature/x, но нет в main
B19. Изменения ветки feature/x относительно точки ветвления (как в MR)
B20. Принудительно удалить ветку feature/dead, даже если она не влита
```

</details>

---

### Блок C. Практика

#### C1. 🔑 Ветка — это указатель
```bash
mkdir -p ~/git-lab/t04 && cd ~/git-lab/t04 && git init
echo "v1" > app.txt && git add . && git commit -m "c1"
echo "v2" >> app.txt && git commit -am "c2"

git branch feature
cat .git/refs/heads/main
cat .git/refs/heads/feature      # ⭐ сравни хеши. Что видишь?
cat .git/HEAD
git lg
```
Запиши вывод: сколько «мест» в графе занимают две ветки?

<details><summary>Ответ</summary>

Хеши в `main` и `feature` **одинаковые** — обе ветки указывают на один коммит.
В графе это одна точка с двумя метками: `(HEAD -> main, feature)`.

</details>

#### C2. Коммит двигает ТЕКУЩУЮ ветку
```bash
git switch feature
echo "v3" >> app.txt && git commit -am "c3"
cat .git/refs/heads/main
cat .git/refs/heads/feature      # ⭐ теперь хеши разные — какая ветка уехала?
git lg
```

<details><summary>Ответ</summary>

Уехала `feature`, потому что HEAD указывал на неё. `main` осталась на c2.

</details>

#### C3. Fast-forward
```bash
git switch main
git merge feature                # что написал git?
git lg
cat .git/refs/heads/main .git/refs/heads/feature
```
Появился ли новый коммит? Сколько указателей на одном коммите?

<details><summary>Ответ</summary>

Нового коммита нет — `Fast-forward`. Обе ветки снова указывают на один и тот же
коммит c3.

</details>

#### C4. ⭐ Трёхстороннее слияние
```bash
git switch -c feature2
echo "фича" > feature.txt && git add . && git commit -m "c4 (feature2)"

git switch main
echo "мейн" > main.txt && git add . && git commit -m "c5 (main)"

git lg                            # граф разошёлся — нарисуй его на бумаге
git merge feature2                # редактор попросит сообщение merge-коммита
git lg
git log --format="%h %p %s" -3    # ⭐ смотри колонку родителей у merge-коммита
git cat-file -p HEAD | head -5    # две строки parent!
```

<details><summary>Ответ</summary>

Появляется merge-коммит; `git log --format="%h %p %s"` показывает у него **два**
родителя, `git cat-file -p HEAD` — две строки `parent`.

</details>

#### C5. `--no-ff` и разница в истории
```bash
git switch -c feature3
echo "ff" > ff.txt && git add . && git commit -m "c6"
git switch main
git merge --no-ff feature3 -m "merge feature3"
git lg
```
Сравни с C3: что изменилось в графе и почему в командах это предпочитают?

<details><summary>Ответ</summary>

При `--no-ff` создаётся merge-коммит даже там, где возможна перемотка: в графе
видна «петля» — факт существования ветки. Командам это нужно для читаемой истории задач
и отката целой задачи одним revert.

</details>

#### C6. `--squash`
```bash
git switch -c feature4
echo "1" > s.txt && git add . && git commit -m "шаг 1"
echo "2" >> s.txt && git commit -am "шаг 2"
echo "3" >> s.txt && git commit -am "шаг 3"
git switch main
git merge --squash feature4
git status                        # ⭐ что в индексе? коммит СОЗДАН?
git commit -m "feat: добавлен s.txt (3 шага схлопнуты)"
git lg
```
Сколько коммитов из feature4 попало в историю main?

<details><summary>Ответ</summary>

В `main` попадает **один** коммит вместо трёх; `git status` после `--squash`
показывает изменения в индексе, коммит не создан (его делаешь ты сам).

</details>

#### C7. Detached HEAD
```bash
git log --oneline
git switch --detach HEAD~2
cat .git/HEAD                     # ⭐ хеш вместо ref
echo "эксперимент" > exp.txt && git add . && git commit -m "коммит вне веток"
git lg                            # видно ли его из веток?
git log --oneline -1              # хеш запомни!
git switch main
git lg                            # коммит ПРОПАЛ из графа
git reflog | head -5              # но он тут
git branch rescue <хеш>           # спасаем
git lg
```

<details><summary>Ответ</summary>

Коммит, сделанный в detached HEAD, не принадлежит ни одной ветке: после `switch main`
он исчезает из `git lg`, но остаётся в `git reflog`. `git branch rescue <хеш>` возвращает его
в достижимую историю.

</details>

#### C8. Сравнение веток
```bash
git switch -c feature5
echo "a" > a.txt && git add . && git commit -m "a"
git switch main && echo "b" > b.txt && git add . && git commit -m "b"

git log --oneline main..feature5
git log --oneline feature5..main
git diff main..feature5 --stat
git diff main...feature5 --stat    # ⭐ сравни с предыдущей
git merge-base main feature5
```
Объясни разницу двух diff'ов своими словами.

<details><summary>Ответ</summary>

`main..feature5` = коммит «a»; `feature5..main` = коммит «b».
`git diff main..feature5` показывает разницу вершин (в том числе «удаление» b.txt),
`git diff main...feature5` — только то, что сделала ветка (добавление a.txt).

</details>

#### C9. Уборка веток
```bash
git branch --merged main
git branch --no-merged main
git branch -d feature5            # что скажет git?
git branch -D feature5
git reflog | head                 # коммиты ещё живы?
```

<details><summary>Ответ</summary>

`git branch -d` откажется, пока ветка не влита; `-D` удалит. Коммиты остаются
доступны через reflog до сборки мусора.

</details>

#### C10. Ветки на «сервере» (продолжение стенда из темы 03)
```bash
cd ~/git-lab/bob
git switch -c feature/from-bob
echo "x" > x.txt && git add . && git commit -m "bob feature"
git push -u origin feature/from-bob

cd ~/git-lab/alice
git fetch
git branch -r
git switch feature/from-bob        # откуда взялась локальная ветка?
git branch -vv
```

<details><summary>Ответ</summary>

Локальная ветка создаётся автоматически, потому что имя совпадает ровно с одной
remote-tracking веткой — git сам ставит upstream (`origin/feature/from-bob`).

</details>

#### C11. Имена веток
Придумай корректные имена веток для задач:
1. Добавить HPA для сервиса payment.
2. Срочно починить 500-е на проде в платежах.
3. Обновить документацию по деплою.
4. Поднять версию базового образа alpine до 3.20.
5. Подготовить релиз 2.3.0.

<details><summary>Ответ</summary>

Например: `feature/payment-hpa`, `hotfix/payment-500`, `docs/deploy-guide`,
`chore/bump-alpine-3.20`, `release/2.3.0`.

</details>

---

### Блок D. Инциденты

**D1.** `error: Your local changes to 'config.yml' would be overwritten by checkout`.
Три варианта действий и когда какой уместен.

<details><summary>Ответ</summary>

(1) Закоммитить — если работа осмысленная; (2) `git stash` — если хочешь отложить
и вернуться; (3) `git restore <файл>` — если правки не нужны (⚠️ без возврата).
Ещё вариант: `git switch -c temp` и коммит туда.

</details>

**D2.** Ты два часа коммитил, а потом понял, что находишься в detached HEAD.
Как не потерять работу?

<details><summary>Ответ</summary>

Не переключаться! Сначала `git switch -c rescue-branch` — коммиты станут частью ветки.
Если уже переключился — найти хеш в `git reflog` и `git branch rescue <хеш>`.

</details>

**D3.** `git branch -d feature/x` → `error: The branch 'feature/x' is not fully merged`.
Что это значит и как принять верное решение?

<details><summary>Ответ</summary>

В ветке есть коммиты, которых нет в текущей ветке — удаление потеряет их из
достижимой истории. Проверь `git log --oneline main..feature/x`: если это мусор — `-D`,
если работа — сначала слить или запушить ветку.

</details>

**D4.** Ты слил ветку и сразу удалил её, а потом выяснилось, что слил не туда.
Как найти коммиты ветки?

<details><summary>Ответ</summary>

`git reflog` (там есть последняя позиция ветки) или `git log --oneline --all --graph`,
`git fsck --lost-found` для недостижимых коммитов. По найденному хешу — `git branch restore <хеш>`.

</details>

**D5.** Коллега сделал `git merge main` в своей ветке, ты — `git rebase main` в своей.
Почему графы выглядят по-разному и кто «неправ»?

<details><summary>Ответ</summary>

Merge сохраняет обе линии и добавляет merge-коммит — граф «с ромбами»; rebase
переписывает коммиты поверх main — линия прямая. Оба варианта корректны; «правота»
определяется соглашением команды (тема 09), а не самим git.

</details>

**D6.** В репозитории 143 ветки, половина влита полгода назад. Как безопасно почистить
локально и на сервере?

<details><summary>Ответ</summary>

Локально: `git branch --merged main | grep -vE '^\*|main' | xargs -r git branch -d`.
На сервере — через веб-интерфейс (в GitLab есть «Stale branches») или
`git push origin --delete <ветка>` для проверенных, затем `git fetch --prune` у всех.
Ветки из `--no-merged` разбирать отдельно, вручную.

</details>

**D7.** `git merge feature` выдал `Already up to date`, хотя в `feature` точно есть коммиты.
Что могло произойти?

<details><summary>Ответ</summary>

Коммиты ветки уже есть в текущей ветке: ветку уже сливали, или ты стоишь не в той
ветке (`git branch` покажет), или ветка не двигалась с момента прошлого merge.
Проверка: `git log --oneline main..feature`.

</details>

**D8.** После merge пайплайн упал, нужно срочно вернуть `main` в состояние «до слияния».
Какие есть варианты и какой безопасен для уже запушенной ветки?

<details><summary>Ответ</summary>

Если ветка уже запушена — `git revert -m 1 <хеш merge-коммита>` (создаёт обратный
коммит, историю не переписывает). `git reset --hard` + force-push — только если ветка
личная и никто её не тянул (тема 07).

</details>

**D9.** Ты создал ветку от старой `main` (не сделав pull), доделал задачу, а при MR видишь
сотни чужих изменений. Что произошло и как исправить?

<details><summary>Ответ</summary>

Ветка создана от устаревшего `main`, поэтому в MR попала разница с текущим состоянием.
Лечение: `git fetch && git rebase origin/main` (или `git merge origin/main`) в своей ветке —
MR покажет только твои изменения.

</details>

**D10.** В `main` прямым push залили сломанный конфиг. Как предотвратить такое на уровне
процесса?

<details><summary>Ответ</summary>

Защитить ветку: запрет прямого push и force-push, обязательный MR с approve
и зелёным пайплайном, CODEOWNERS на критичные файлы (тема 11).

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐ Что такое ветка в git?

<details><summary>Ответ</summary>

Подвижный указатель на коммит; физически — файл с хешем в `.git/refs/heads/`.

</details>

**2.** Как создать ветку и переключиться на неё?

<details><summary>Ответ</summary>

`git switch -c <имя>` (или `git checkout -b <имя>`).

</details>

**3.** Что такое HEAD и detached HEAD?

<details><summary>Ответ</summary>

HEAD — указатель на текущую позицию, обычно на активную ветку. Detached HEAD — когда он
указывает прямо на коммит; новые коммиты не привязаны к ветке и легко теряются.

</details>

**4.** ⭐ Что такое fast-forward merge? Когда он происходит?

<details><summary>Ответ</summary>

Слияние перемоткой указателя, когда целевая ветка — прямой предок сливаемой;
merge-коммит не создаётся.

</details>

**5.** Как git сливает ветки, если обе ушли вперёд?

<details><summary>Ответ</summary>

Трёхсторонним слиянием: берёт общего предка и вершины веток, объединяет изменения,
создаёт merge-коммит с двумя родителями; при пересекающихся правках — конфликт.

</details>

**6.** Сколько родителей у merge-коммита?

<details><summary>Ответ</summary>

Два (у обычного — один, у первого коммита — ноль).

</details>

**7.** Зачем `--no-ff`?

<details><summary>Ответ</summary>

Чтобы явно фиксировать факт слияния ветки: читаемая история задач и возможность откатить
задачу одним `git revert -m 1`.

</details>

**8.** Чем `merge --squash` отличается от обычного merge?

<details><summary>Ответ</summary>

`--squash` кладёт все изменения ветки в индекс одним набором, коммит создаёшь ты сам:
получается один коммит без связи с историей ветки, и git не считает ветку влитой.

</details>

**9.** Как посмотреть, какие коммиты есть в ветке, но нет в main?

<details><summary>Ответ</summary>

`git log --oneline main..feature` (и `git diff main...feature` для изменений).

</details>

**10.** Удалятся ли коммиты, если удалить ветку?

<details><summary>Ответ</summary>

Нет, удаляется только указатель; коммиты становятся недостижимыми и восстанавливаются
через `git reflog` до сборки мусора.

</details>
