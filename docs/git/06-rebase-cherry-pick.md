---
title: "06. Rebase и cherry-pick"
description: "Перенос коммитов между ветками: rebase, интерактивный rebase, cherry-pick, force-with-lease"
---

# 06. Rebase и cherry-pick: перенос коммитов между ветками

> Роадмап → 1. Git → Теория → команды `git rebase`, `git merge`.
> Роадмап → 3. Собесы: **«Как перенести коммиты из одной ветки в другую?»** — главный
> вопрос про git на собеседовании. Полный разбор — §7.
> **После темы ты умеешь:** объяснить, что rebase переписывает историю, перенести один
> коммит через cherry-pick, почистить свою ветку интерактивным rebase и не сломать
> при этом работу команды.

---

## 🗺️ Карта темы

```text:no-line-numbers
ИСХОДНОЕ СОСТОЯНИЕ                MERGE                        REBASE
 c1─c2─c3────c6 (main)      c1─c2─c3──c6────M (main)     c1─c2─c3──c6 (main)
      \                          \         ↗                       \
       c4─c5 (feature)            c4─c5 ──┘ (feature)               c4'─c5' (feature)
                                                                     ▲
  общий предок = c3          история «как было»            НОВЫЕ коммиты: другие хеши,
                             + merge-коммит                 другой родитель, линейно

CHERRY-PICK — перенести ОДИН коммит:
 c1─c2─c3──c6 (main)  ──git cherry-pick c5──►  c1─c2─c3──c6──c5' (main)
      \                                             \
       c4─c5 (feature)                               c4─c5 (feature)  ← остаётся на месте
```

---

## 1. Что такое rebase

**Rebase = сменить основание ветки.** Git берёт коммиты твоей ветки (те, которых нет
в целевой), «откладывает» их, перематывает ветку на вершину целевой и **применяет коммиты
заново, один за другим**.

```bash
git switch feature
git rebase main
```

Что происходит внутри:
1. Находится общий предок `main` и `feature` (merge base = c3).
2. Коммиты c4, c5 сохраняются как патчи.
3. `feature` переставляется на вершину `main` (c6).
4. Патчи применяются по очереди → создаются **новые коммиты** c4', c5'.

⚠️ c4' и c5' — **не те же самые коммиты**: у них другой родитель, другое время применения,
следовательно **другие хеши**. Старые c4, c5 становятся недостижимыми (живут в reflog).

```text:no-line-numbers
До:    c3 ──► c6 (main)            После:  c3 ──► c6 (main)
         \                                          \
          └► c4 ──► c5 (feature)                     └► c4' ──► c5' (feature)
```

---

## 2. ⭐ Золотое правило rebase

> **Не делай rebase коммитов, которые уже опубликованы и которые кто-то мог забрать.**

Потому что rebase создаёт новые коммиты вместо старых. Если коллега уже забрал старые,
то после твоего force-push у вас будут две несовместимые истории, и у него при pull
появятся дубликаты коммитов и «весёлые» конфликты.

**Можно:**
- rebase своей личной ветки, которую никто не тянул;
- rebase ветки, запушенной только тобой, с последующим `git push --force-with-lease`
  (норма для MR: «подтяни main под себя перед мержем»);
- интерактивный rebase для чистки своих коммитов **до** открытия MR.

**Нельзя:**
- rebase `main`/`master`/`develop` и любых общих веток;
- force-push в защищённую ветку (в нормальном репозитории это и технически запрещено).

---

## 3. Merge vs rebase: как выбрать

| | `git merge main` (в свою ветку) | `git rebase main` |
|---|---|---|
| История | Сохраняется как было + merge-коммит | Линейная, будто ветка началась сегодня |
| Хеши коммитов | Не меняются | **Меняются** (новые коммиты) |
| Безопасность для общих веток | ✅ Всегда безопасен | ⚠️ Только для личных веток |
| Читаемость `git log` | «Ромбы», шум от частых merge | Чистая прямая линия |
| Разрешение конфликтов | Один раз, разом | Может повторяться на каждом коммите |
| Видно ли реальную хронологию | ✅ | ❌ (история «причёсана») |

**Практическое правило команды:**
- в **свою ветку** подтягивать `main` — `rebase` (чисто) или `merge` (безопасно) —
  по соглашению команды;
- **ветку в main** вливать — `merge --no-ff` (виден факт задачи) или squash-merge;
- **`main` никогда не ребейзить**.

```bash
# ежедневная синхронизация своей ветки
git fetch origin
git rebase origin/main
# конфликты → правишь → git add → git rebase --continue
git push --force-with-lease        # своя ветка, уже запушенная
```

---

## 4. Управление процессом rebase

```bash
git rebase main                # перебазировать текущую ветку на main
git rebase origin/main
git rebase --continue          # после разрешения конфликта в текущем коммите
git rebase --skip              # пропустить коммит (если он стал пустым)
git rebase --abort             # ⭐ отменить всё, вернуть ветку как было
```

Во время rebase ты находишься в **detached HEAD** — это нормально, git сам вернёт HEAD
на ветку в конце.

Помни про смену сторон при конфликте: `HEAD`/`ours` = целевая ветка (`main`),
`theirs` = твой переносимый коммит (тема 05, §3).

---

## 5. ⭐ Интерактивный rebase — чистка своей истории

```bash
git rebase -i HEAD~4          # последние 4 коммита
git rebase -i main            # все коммиты ветки относительно main
```

Откроется редактор:
```text:no-line-numbers
pick a1b2c3d добавил конфиг
pick e4f5g6h опечатка
pick i7j8k9l ещё опечатка
pick m1n2o3p дописал healthcheck

# p, pick   = взять коммит как есть
# r, reword = взять, но изменить сообщение
# e, edit   = остановиться и дать изменить сам коммит
# s, squash = объединить с предыдущим, сообщения объединить
# f, fixup  = объединить с предыдущим, сообщение выбросить
# d, drop   = выбросить коммит
# строки можно МЕНЯТЬ МЕСТАМИ — порядок коммитов изменится
```

Приводим к виду:
```text:no-line-numbers
pick   a1b2c3d добавил конфиг
fixup  e4f5g6h опечатка
fixup  i7j8k9l ещё опечатка
reword m1n2o3p дописал healthcheck
```
Результат: два аккуратных коммита вместо четырёх, второй — с исправленным сообщением.

Типичные применения:
- перед открытием MR схлопнуть «wip», «fix», «опять fix» в один осмысленный коммит;
- переписать сообщение коммита (`reword`);
- удалить коммит с случайно добавленным файлом (`drop`);
- разбить большой коммит на части (`edit` + `git reset HEAD^` + новые коммиты).

Помощник для «дописать в старый коммит»:
```bash
git commit --fixup=a1b2c3d       # создаёт коммит "fixup! ..."
git rebase -i --autosquash main  # сам расставит fixup в нужные места
```

---

## 6. `git cherry-pick` — взять один коммит

```bash
git switch main
git cherry-pick a1b2c3d              # применить коммит сюда (создаст НОВЫЙ коммит)
git cherry-pick a1b2c3d e4f5g6h      # несколько
git cherry-pick a1b2c3d..f9e8d7c     # диапазон (не включая первый)
git cherry-pick a1b2c3d^..f9e8d7c    # диапазон включительно
git cherry-pick -n a1b2c3d           # применить в индекс, не коммитить
git cherry-pick -x a1b2c3d           # ⭐ добавить в сообщение «(cherry picked from …)»
git cherry-pick --continue / --abort / --skip
```

Классический сценарий DevOps: **хотфикс в релизную ветку**.

```text:no-line-numbers
main:     ... c10 ─ c11 ─ c12(фикс бага) ─ c13 ─ c14
release/1.4: ... c9 ─ r1 ─ r2                     ← нужен ТОЛЬКО c12, без c13, c14

git switch release/1.4
git cherry-pick c12          → release/1.4: ... c9 ─ r1 ─ r2 ─ c12'
```

`-x` очень желателен: в сообщении остаётся ссылка на исходный коммит, и через полгода
понятно, откуда он приехал.

⚠️ Cherry-pick **дублирует** изменение: один и тот же фикс существует в двух ветках разными
коммитами. При последующем слиянии веток git обычно разбирается сам (изменения идентичны),
но при правках может дать конфликт.

---

## 7. ⭐⭐ Вопрос с собеса: «Как перенести коммиты из одной ветки в другую?»

Хороший ответ — **назвать несколько способов и сказать, когда какой**:

| Способ | Что делает | Когда применять |
|--------|-----------|-----------------|
| **`git cherry-pick <хеш>`** | Копирует один/несколько конкретных коммитов | Нужен именно конкретный фикс (бэкпорт в релизную ветку) |
| **`git rebase <ветка>`** | Переносит **все** коммиты ветки на новое основание | Актуализировать свою ветку под свежий `main` |
| **`git rebase --onto A B feature`** | Переносит часть ветки: коммиты после B — на A | Ветка создана не от той ветки; вырезать «лишнее» основание |
| **`git merge <ветка>`** | Вливает ветку целиком, сохраняя историю | Штатное слияние готовой задачи |
| **`git format-patch` + `git am`** | Патчи файлами | Между репозиториями, без общего remote (письмом/файлом) |
| **`git reset` + новая ветка** | Перевесить указатели | Коммитил не в ту ветку и ещё не пушил (тема 07) |

### `git rebase --onto` (стоит понимать)

```text:no-line-numbers
Было: main ─ c1 ─ c2
            \
       develop ─ d1 ─ d2
                      \
                  feature ─ f1 ─ f2     ← ветку случайно создали от develop

Нужно: feature должен расти из main

git rebase --onto main develop feature
        │        │      │       │
        │        │      │       └── что переносим
        │        │      └────────── старое основание (исключая его коммиты)
        │        └───────────────── куда переносим
Стало: main ─ c1 ─ c2 ─ f1' ─ f2'  (feature)
```

### Частый подвопрос: «а если коммитил не в ту ветку?»

```bash
# был на main, сделал 3 коммита, которые должны быть в feature — и НЕ пушил
git switch -c feature        # ветка feature создана здесь же, коммиты уже в ней
git switch main
git reset --hard origin/main # main возвращается на состояние сервера
```
Подробно — [07. Отмена изменений и история](/git/07-undo-history).

> 🎤 **Формулировка для собеса:** «Зависит от того, что переносить. Один конкретный коммит —
> `git cherry-pick <хеш>`, желательно с `-x`, чтобы осталась ссылка на оригинал: так делают
> бэкпорт фикса в релизную ветку. Всю ветку поверх другой — `git rebase main`, при этом
> коммиты пересоздаются с новыми хешами, поэтому так делают только со своей неопубликованной
> веткой или с force-with-lease в свою ветку. Часть ветки — `git rebase --onto`.
> Если задача просто "влить готовую ветку" — это обычный `git merge`.»

---

## 8. `--force-with-lease` — как пушить после rebase

После rebase твоя локальная история разошлась с серверной, и обычный push отклонится.

```bash
git push --force-with-lease           # ⭐ так
git push --force                      # ⚠️ не так
```

`--force-with-lease` проверяет, что удалённая ветка находится ровно там, где ты её видел
при последнем fetch. Если коллега успел что-то запушить в эту ветку — push отклоняется,
и ты не затираешь чужую работу. `--force` затирает без вопросов.

```bash
git push --force-with-lease origin feature/login    # явно указывай ветку
```

Правило: **force только в свою ветку**, никогда — в `main`/`develop`/`release/*`.

---

## 9. Полезное рядом

```bash
git cherry -v main feature        # какие коммиты feature ещё не в main (сравнение по патчам)
git log --left-right --oneline main...feature    # кто на какой стороне
git range-diff main feature-old feature-new      # ⭐ сравнить ДВЕ версии ветки после rebase
git rebase --exec "make test" main               # прогнать команду после каждого коммита
git config --global rebase.autosquash true
git config --global rebase.autostash true        # авто-stash незакоммиченного перед rebase
git config --global pull.rebase true             # pull = fetch + rebase
```

`git range-diff` — отличная проверка «я ничего не потерял при rebase»:
сравнивает старую и новую версии ветки по содержанию коммитов.

---

## 💼 Как это в DevOps

- **Стандарт большинства команд:** своя ветка ребейзится на `main` перед мержем MR,
  чтобы в `main` попадала линейная история и CI проверял ровно тот код, который будет в main.
  В GitLab это кнопка «Rebase» и настройка «Fast-forward merge».
- **Cherry-pick — инструмент релиз-менеджмента**: фикс сделан в `main`, а на проде живёт
  `release/1.4` — переносим только нужный коммит. В GitLab есть кнопка «Cherry-pick» прямо
  в MR/коммите.
- **Интерактивный rebase — гигиена перед ревью.** Ревьюеру приятнее смотреть 3 осмысленных
  коммита, чем 17 «wip». Но не переусердствуй: переписывать историю ради красоты после
  ревью — плохая идея, ревьюер потеряет контекст.
- В защищённых ветках force-push запрещён на уровне хостинга — это правильно и защищает
  от «rebase главной ветки».
- Squash-merge (кнопка в GitLab/GitHub) — компромисс: разработчик коммитит как хочет,
  в `main` приезжает один аккуратный коммит на задачу.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Актуализировать ветку под main | `git fetch && git rebase origin/main` |
| Продолжить rebase после конфликта | `git rebase --continue` |
| Отменить rebase | `git rebase --abort` |
| Схлопнуть/переписать свои коммиты | `git rebase -i main` (`fixup`/`squash`/`reword`/`drop`) |
| Дописать в старый коммит | `git commit --fixup=<хеш>` + `git rebase -i --autosquash` |
| Перенести один коммит | `git cherry-pick <хеш>` (лучше `-x`) |
| Перенести диапазон | `git cherry-pick A^..B` |
| Перенести часть ветки на другое основание | `git rebase --onto main develop feature` |
| Запушить после rebase | `git push --force-with-lease` |
| Проверить, что rebase ничего не потерял | `git range-diff main old new` |
| Какие коммиты ветки ещё не в main | `git cherry -v main feature` |
| Автоматически прятать незакоммиченное | `git config --global rebase.autostash true` |

---

## 🧠 Что запомнить

1. **Rebase = смена основания**: коммиты применяются заново поверх целевой ветки.
2. Пересозданные коммиты — **новые объекты с новыми хешами**; старые остаются в reflog.
3. ⭐ **Золотое правило:** не ребейзить опубликованные/общие ветки. `main` — никогда.
4. `merge` сохраняет историю и безопасен; `rebase` даёт линейную историю, но переписывает её.
5. При конфликте во время rebase **стороны меняются местами** (`ours` = main).
6. `git rebase -i` — чистка своей ветки: `pick/reword/edit/squash/fixup/drop` + перестановка.
7. `git cherry-pick` копирует конкретный коммит в текущую ветку (новый хеш); `-x` оставляет
   ссылку на оригинал.
8. Типовой кейс cherry-pick — **бэкпорт фикса в релизную ветку**.
9. `git rebase --onto A B feature` — перенести часть ветки; спрашивают на собесе как
   «продвинутый» вариант переноса.
10. После rebase пушить только `--force-with-lease` и только в свою ветку.
11. `git rebase --abort` спасает всегда; `git reflog` — если уже завершил и пожалел.

➡️ Дальше: [07. Отмена изменений и история](/git/07-undo-history)

---

## Задачи

> Стенд: `mkdir -p ~/git-lab/t06 && cd ~/git-lab/t06 && git init`
> Здесь ты переписываешь историю — делай это **только в песочнице**, пока не появится
> уверенность. Спасательный круг: `git rebase --abort` и `git reflog` (тема 07).

---

### Блок A. Теория

**A1.** ⭐ Что делает `git rebase main`, если объяснять по шагам?

<details><summary>Ответ</summary>

Находит общего предка текущей ветки и `main`; сохраняет коммиты ветки как патчи;
переставляет ветку на вершину `main`; последовательно применяет патчи, создавая новые коммиты.
При конфликте останавливается и ждёт `--continue`.

</details>

**A2.** Почему после rebase у коммитов другие хеши? Куда делись старые коммиты?

<details><summary>Ответ</summary>

Хеш коммита зависит от содержимого, включая хеш родителя и метаданные; после переноса
родитель другой → хеш другой. Старые коммиты становятся недостижимыми из веток, но остаются
в объектах и в `git reflog` до сборки мусора.

</details>

**A3.** ⭐⭐ Сформулируй золотое правило rebase и объясни, что произойдёт при его нарушении.

<details><summary>Ответ</summary>

«Не ребейзить коммиты, которые уже опубликованы и которые кто-то мог забрать».
Нарушение: после force-push у коллег остаётся старая версия истории; их `pull` даёт
расхождение, дубликаты коммитов и конфликты, а чужие коммиты, добавленные поверх старой
истории, можно потерять.

</details>

**A4.** Сравни merge и rebase по пяти признакам. Когда что выбирать?

<details><summary>Ответ</summary>

История (сохраняется / переписывается), хеши (не меняются / меняются), безопасность
для общих веток (да / нет), читаемость лога (ромбы / линия), конфликты (разом / возможно
на каждом коммите). Выбор: в свою ветку — rebase (или merge по соглашению), в main —
merge `--no-ff`/squash, общие ветки — никогда не rebase.

</details>

**A5.** Почему при конфликте в rebase `ours` — это не твоя ветка?

<details><summary>Ответ</summary>

Rebase применяет твои коммиты поверх целевой ветки, и в момент конфликта «текущим»
состоянием является целевая ветка (main) — она и есть `ours`, а применяемый твой коммит —
`theirs`.

</details>

**A6.** Что делают `pick`, `reword`, `edit`, `squash`, `fixup`, `drop` в интерактивном rebase?

<details><summary>Ответ</summary>

`pick` — взять как есть; `reword` — взять, изменив сообщение; `edit` — остановиться
для правки самого коммита; `squash` — слить с предыдущим, объединив сообщения;
`fixup` — слить с предыдущим, выбросив сообщение; `drop` — удалить коммит.

</details>

**A7.** Чем `squash` отличается от `fixup`?

<details><summary>Ответ</summary>

Оба объединяют коммит с предыдущим; `squash` открывает редактор и объединяет тексты
сообщений, `fixup` молча использует сообщение предыдущего коммита.

</details>

**A8.** ⭐ Что делает `git cherry-pick` и чем результат отличается от оригинального коммита?

<details><summary>Ответ</summary>

Применяет изменения указанного коммита к текущей ветке и создаёт **новый** коммит
с новым хешем (и новым временем коммита); исходный коммит остаётся на месте в своей ветке.

</details>

**A9.** Зачем нужен флаг `-x` у cherry-pick?

<details><summary>Ответ</summary>

Добавляет в сообщение строку `(cherry picked from commit <хеш>)` — сохраняется
связь с оригиналом, что критично при разборе «откуда в релизе этот фикс».

</details>

**A10.** ⭐⭐ Перечисли **пять** способов перенести коммиты из одной ветки в другую
и укажи, когда какой уместен.

<details><summary>Ответ</summary>

(1) `git cherry-pick` — конкретные коммиты (бэкпорт фикса); (2) `git rebase <ветка>` —
все коммиты своей ветки на новое основание; (3) `git rebase --onto A B feature` — часть ветки;
(4) `git merge` — влить готовую ветку целиком; (5) `git format-patch` + `git am` — перенос
патчами между репозиториями без общего remote. Дополнительно: `git reset` + новая ветка,
если коммитил не в ту ветку и ещё не пушил.

</details>

**A11.** Разбери синтаксис `git rebase --onto main develop feature` — что означает каждый аргумент?

<details><summary>Ответ</summary>

`--onto main` — новое основание (куда); `develop` — старое основание (коммиты
до него включительно не переносятся); `feature` — какая ветка переносится. Итог: коммиты
`feature`, которых нет в `develop`, применяются поверх `main`.

</details>

**A12.** ⭐ Чем `--force-with-lease` лучше `--force`? В какие ветки force недопустим вообще?

<details><summary>Ответ</summary>

`--force-with-lease` отправляет, только если удалённая ветка находится там,
где ты её видел при последнем fetch: чужие коммиты не будут затёрты молча.
Force недопустим в `main`/`master`/`develop`/`release/*` и любых защищённых ветках.

</details>

**A13.** Что такое `git commit --fixup` + `--autosquash`?

<details><summary>Ответ</summary>

`git commit --fixup=<хеш>` создаёт коммит с сообщением `fixup! <сообщение того
коммита>`; `git rebase -i --autosquash` автоматически ставит его сразу после целевого коммита
с действием `fixup`, так что правка «вливается» в нужный коммит без ручной перестановки строк.

</details>

**A14.** Что делает `rebase.autostash` и почему это удобно?

<details><summary>Ответ</summary>

Автоматически прячет незакоммиченные изменения (`stash`) перед rebase и возвращает
после. Иначе rebase откажется стартовать при грязном рабочем каталоге.

</details>

**A15.** Как проверить, что при rebase ничего не потерялось?

<details><summary>Ответ</summary>

`git range-diff <база> <старая версия ветки> <новая>` — сравнивает наборы коммитов
по содержанию; `feature@{1}` из reflog даёт предыдущее состояние ветки. Также помогает
`git diff old-branch new-branch` (итоговое состояние должно совпасть).

</details>

**A16.** Почему squash-merge в GitLab/GitHub считают компромиссом между merge и rebase?

<details><summary>Ответ</summary>

Разработчик коммитит как удобно (десятки мелких коммитов), а в `main` приезжает один
аккуратный коммит на задачу: история линейная и читаемая, при этом никто не заставляет
переписывать историю вручную. Минус — теряется детализация шагов внутри задачи.

</details>

---

### Блок B. «Что делает команда»

Слева — команда, справа (сразу под ней) — что она делает.

```bash
B1.  git rebase main
B2.  git rebase origin/main
B3.  git rebase --continue
B4.  git rebase --abort
B5.  git rebase --skip
B6.  git rebase -i HEAD~5
B7.  git rebase -i --autosquash main
B8.  git rebase --onto main release/1.4 feature/x
B9.  git rebase --exec "yamllint ." main
B10. git cherry-pick 9a8b7c6
B11. git cherry-pick -x 9a8b7c6
B12. git cherry-pick -n 9a8b7c6
B13. git cherry-pick a1b2c3d^..f9e8d7c
B14. git cherry-pick --abort
B15. git commit --fixup=9a8b7c6
B16. git push --force-with-lease origin feature/login
B17. git range-diff main feature@{1} feature
B18. git cherry -v main feature
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Перебазировать текущую ветку на main
B2.  То же, но на свежее состояние сервера (origin/main)
B3.  Продолжить rebase после разрешения конфликта
B4.  Прервать rebase и вернуть ветку в исходное состояние
B5.  Пропустить текущий коммит (например, ставший пустым)
B6.  Интерактивно переписать последние 5 коммитов
B7.  Интерактивный rebase с автоматической расстановкой fixup!-коммитов
B8.  Перенести коммиты feature/x, которых нет в release/1.4, поверх main
B9.  Перебазировать и после каждого коммита запускать yamllint (проверка каждого шага)
B10. Скопировать коммит 9a8b7c6 в текущую ветку
B11. То же + записать в сообщение ссылку на оригинальный коммит
B12. Применить изменения коммита в индекс, коммит не создавать
B13. Скопировать диапазон коммитов включительно
B14. Прервать cherry-pick и вернуть состояние до него
B15. Создать коммит-исправление, привязанный к коммиту 9a8b7c6
B16. Запушить переписанную ветку безопасно (с проверкой, что её никто не двигал)
B17. Сравнить прошлое состояние ветки (до rebase) с текущим по содержанию коммитов
B18. Показать коммиты feature, которых нет в main (сравнение по изменениям, а не хешам)
```

</details>

---

### Блок C. Практика

#### C1. 🔑 Первый rebase
```bash
mkdir -p ~/git-lab/t06 && cd ~/git-lab/t06 && git init
echo "base" > app.txt && git add . && git commit -m "c1: base"

git switch -c feature
echo "f1" >> app.txt && git commit -am "c2: feature step 1"
echo "f2" >> app.txt && git commit -am "c3: feature step 2"

git switch main
echo "m1" > main.txt && git add . && git commit -m "c4: main moved"

git lg                        # ⭐ нарисуй граф на бумаге
git log --format="%h %s" feature
git switch feature
git rebase main
git lg                        # что изменилось в графе?
git log --format="%h %s" feature   # ⭐ сравни хеши с предыдущим выводом
git reflog | head -8          # где старые коммиты?
```

<details><summary>Ответ</summary>

После rebase в графе одна линия: `c1 → c4 → c2' → c3'`. Хеши коммитов feature
изменились. `git reflog` показывает и старые хеши — из них можно восстановить прежнее
состояние (`git reset --hard feature@{1}`).

</details>

#### C2. Rebase с конфликтом
```bash
git switch main
echo "ГЛАВНАЯ ВЕРСИЯ" > shared.txt && git add . && git commit -m "main: shared"
git switch -c feature2 HEAD~1
echo "ВЕРСИЯ ФИЧИ" > shared.txt && git add . && git commit -m "feature2: shared"

git rebase main               # конфликт
cat shared.txt                # ⭐ что под HEAD?
# разреши, оставив обе строки
git add shared.txt
git rebase --continue
git lg
```

<details><summary>Ответ</summary>

При конфликте под `<<<<<<< HEAD` — версия из `main` («ГЛАВНАЯ ВЕРСИЯ»), ниже —
твой переносимый коммит. После `git add` и `--continue` rebase завершится, ветка встанет
поверх main.

</details>

#### C3. `--abort`
Повтори C2, но вместо разрешения конфликта выполни `git rebase --abort`.
Проверь `git lg` и `cat shared.txt` — вернулось ли всё как было?

<details><summary>Ответ</summary>

`--abort` возвращает ветку и файлы в состояние до rebase — как будто команду
не запускали.

</details>

#### C4. ⭐ Интерактивный rebase: чистим ветку перед MR
```bash
git switch main && git switch -c feature/messy
echo "1" > f.txt && git add . && git commit -m "wip"
echo "2" >> f.txt && git commit -am "опечатка"
echo "3" >> f.txt && git commit -am "ещё опечатка"
echo "4" >> f.txt && git commit -am "готово"
git log --oneline

git rebase -i main
# приведи к виду:
#   pick   ... wip                → reword на "feat: добавлен f.txt"
#   fixup  ... опечатка
#   fixup  ... ещё опечатка
#   fixup  ... готово
git log --oneline                 # сколько коммитов осталось?
git show --stat HEAD
```

<details><summary>Ответ</summary>

Остаётся один коммит с сообщением, которое ты задал в `reword`; `git show --stat`
показывает суммарные изменения всех четырёх шагов.

</details>

#### C5. Перестановка и удаление коммитов
```bash
git switch main && git switch -c feature/order
echo "a" > a.txt && git add . && git commit -m "A"
echo "b" > b.txt && git add . && git commit -m "B"
echo "c" > c.txt && git add . && git commit -m "C"
git rebase -i main        # поменяй местами A и C, коммит B пометь drop
git log --oneline
ls                        # какие файлы остались?
```

<details><summary>Ответ</summary>

Файлы `a.txt` и `c.txt` есть, `b.txt` нет — коммит удалён из истории ветки.
Порядок коммитов в логе изменён согласно перестановке строк.

</details>

#### C6. `--fixup` + `--autosquash`
```bash
git switch main && git switch -c feature/fixup
echo "конфиг" > cfg.yml && git add . && git commit -m "feat: add cfg"
echo "код" > code.py && git add . && git commit -m "feat: add code"
echo "забытая строка" >> cfg.yml
git commit -am "$(echo)"  2>/dev/null || true
git reset --soft HEAD 2>/dev/null || true
git add cfg.yml
git commit --fixup=$(git log --format=%h --grep="add cfg" -1)
git log --oneline
git rebase -i --autosquash main      # ⭐ git сам расставил fixup — просто сохрани файл
git log --oneline
```

#### C7. 🔑 Cherry-pick: бэкпорт фикса в релиз
```bash
git switch main
echo "v1" > release.txt && git add . && git commit -m "release base"
git switch -c release/1.4
git switch main
echo "фикс бага" > bugfix.txt && git add . && git commit -m "fix: critical bug"
echo "новая фича" > feature.txt && git add . && git commit -m "feat: new feature"

FIX=$(git log --format=%h --grep="critical bug" -1)
git switch release/1.4
git cherry-pick -x $FIX
git log --oneline                  # ⭐ есть ли здесь "new feature"?
git show HEAD | head -8            # что добавил флаг -x?
ls
```

<details><summary>Ответ</summary>

В `release/1.4` попадает только `bugfix.txt`; `feature.txt` отсутствует.
В сообщении коммита появилась строка `(cherry picked from commit <хеш>)`.

</details>

#### C8. Cherry-pick диапазона и конфликт
```bash
git switch main && git switch -c donor
for i in 1 2 3; do echo "line$i" >> multi.txt; git add .; git commit -m "donor step $i"; done
git switch main
git cherry-pick $(git log --format=%h donor -3 | tail -1)^..donor
git log --oneline -4
```

#### C9. `rebase --onto`
```bash
git switch main && git switch -c develop
echo "d1" > d.txt && git add . && git commit -m "develop only"
git switch -c feature/wrong-base
echo "f1" > wf.txt && git add . && git commit -m "feature 1"
echo "f2" >> wf.txt && git commit -am "feature 2"
git lg

git rebase --onto main develop feature/wrong-base
git lg                       # ⭐ остался ли коммит "develop only" в ветке?
git log --oneline main..feature/wrong-base
```

<details><summary>Ответ</summary>

Коммит «develop only» в ветку не переносится: `--onto` отрезает старое основание.
В `main..feature/wrong-base` остаются только два коммита фичи.

</details>

#### C10. merge vs rebase — сравни графы
Сделай два одинаковых сценария в разных ветках: в одном подтяни main через `git merge main`,
в другом — через `git rebase main`. Сравни `git lg` и `git log --oneline`.
Запиши, чем отличаются истории и что ты выберешь для рабочего репозитория.

#### C11. Force-push после rebase (на стенде из темы 03)
```bash
cd ~/git-lab/bob
git switch -c feature/force
echo "x" > fx.txt && git add . && git commit -m "step 1"
git push -u origin feature/force
git commit --amend -m "step 1 (исправленное сообщение)"
git push                                   # ⛔ отклонён — почему?
git push --force-with-lease
git lg
```

<details><summary>Ответ</summary>

Push отклонён, потому что `--amend` переписал коммит: локальная и удалённая истории
разошлись. `--force-with-lease` проходит, так как ветку никто больше не двигал.

</details>

#### C12. `range-diff` — проверка после rebase
```bash
git switch feature
git range-diff main feature@{1} feature
```
Что показывает вывод и зачем это нужно перед force-push?

<details><summary>Ответ</summary>

`range-diff` показывает попарное соответствие старых и новых коммитов и различия
между ними. Перед force-push это проверка «я перенёс именно то, что хотел, и ничего не потерял».

</details>

---

### Блок D. Инциденты

**D1.** Ты сделал `git rebase main` в ветке `develop`, которую тянут пятеро,
и запушил с `--force`. Что произошло у коллег и как чинить?

<details><summary>Ответ</summary>

У коллег осталась старая история; их `git pull` покажет расхождение, появятся дубликаты
коммитов, а коммиты, сделанные ими поверх старой истории, рискуют потеряться.
Чинить: договориться остановить работу, выбрать эталонную версию (у тебя или взять старую
из чьего-то reflog/бэкапа), восстановить ветку (`git reset --hard <хеш>` + push с согласия),
остальным сделать `git fetch && git reset --hard origin/develop` (предварительно сохранив
свои коммиты в отдельные ветки). Профилактика — запрет force-push в защищённых ветках.

</details>

**D2.** Rebase идёт уже 15 коммитов, конфликты повторяются в одном и том же файле.
Что включить и что сделать сейчас?

<details><summary>Ответ</summary>

Включить `git config rerere.enabled true` (решения запомнятся и применятся повторно),
рассмотреть `git rebase --abort` и слияние через `git merge` разом, а на будущее — чаще
синхронизировать ветку и дробить задачи.

</details>

**D3.** После `git rebase -i` пропал коммит с важной правкой. Как найти и вернуть?

<details><summary>Ответ</summary>

`git reflog` — найти хеш состояния до rebase (`feature@{N}`), затем либо
`git reset --hard <хеш>` (вернуть всю ветку), либо `git cherry-pick <хеш коммита>`
(вернуть только нужный коммит). `git fsck --lost-found` — если reflog не помог.

</details>

**D4.** `git push` после rebase → `rejected (non-fast-forward)`. Коллега советует `--force`.
Что сделаешь ты?

<details><summary>Ответ</summary>

Проверю, моя ли это ветка и не тянул ли её кто-то (`git log origin/<ветка>`,
спросить в чате). Если ветка личная — `git push --force-with-lease`. Если ветка общая —
force не делаю: подтяну изменения (`git pull --rebase`) и запушу обычным образом.

</details>

**D5.** Cherry-pick фикса в релизную ветку дал конфликт. Порядок действий?

<details><summary>Ответ</summary>

Разрешить конфликт (`git status` → правка → `git add`), затем `git cherry-pick
--continue`; если стало ясно, что коммит переносить нельзя — `git cherry-pick --abort`.
Проверить, что фикс в релизной ветке действительно работает (собрать/прогнать тесты).

</details>

**D6.** После cherry-pick одно и то же изменение есть в `main` и в `release/1.4` разными
коммитами. Будут ли проблемы при слиянии веток?

<details><summary>Ответ</summary>

Обычно нет: при слиянии git видит идентичные изменения и не конфликтует (а `git cherry`
покажет коммит как уже применённый). Проблемы возможны, если после cherry-pick изменение
правили по-разному в двух ветках — тогда будет обычный конфликт.

</details>

**D7.** `git rebase --continue` пишет `No changes - did you forget to use git add?`.
Что произошло и какие есть варианты?

<details><summary>Ответ</summary>

Изменения коммита уже присутствуют в целевой ветке (например, этот фикс был
cherry-pick'нут ранее) — патч стал пустым. Варианты: `git rebase --skip` (пропустить)
или `git commit --allow-empty` (оставить пустой коммит), если он нужен как маркер.

</details>

**D8.** Ты случайно сделал `git rebase` вместо `git merge` в своей ветке, уже открыт MR.
Что увидит ревьюер и что делать?

<details><summary>Ответ</summary>

Ревьюер увидит, что ветка force-push'нута: комментарии к старым коммитам могут
«оторваться», а diff MR пересчитается. Ничего страшного, если rebase был на свежий `main`;
в GitLab/GitHub есть сравнение версий MR. Хорошая практика — предупредить ревьюера
и не переписывать историю в середине ревью.

</details>

**D9.** Тимлид требует линейную историю в `main`, но команда часто мержит MR.
Какие настройки хостинга это обеспечивают?

<details><summary>Ответ</summary>

В GitLab: «Fast-forward merge» + обязательный rebase перед мержем, либо
«Squash commits when merging» (обязательный). В GitHub: разрешить только «Rebase and merge»
или «Squash and merge», запретить merge-коммиты. Плюс защита ветки от прямого push.

</details>

**D10.** Ты хочешь поправить сообщение коммита трёхдневной давности, который уже в `main`.
Можно ли и что будет?

<details><summary>Ответ</summary>

Технически можно (`git rebase -i` + `reword` + force-push), но коммит уже
опубликован в общей ветке: это нарушение золотого правила, у всех разъедется история,
а в защищённой ветке force-push и вовсе запрещён. Правильный путь — оставить как есть;
если формулировка критична, добавить уточнение в описание MR/issue.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐⭐ Как перенести коммиты из одной ветки в другую?

<details><summary>Ответ</summary>

`cherry-pick` для отдельных коммитов, `rebase` для переноса всей ветки на новое основание,
`rebase --onto` для части ветки, `merge` для штатного вливания, `format-patch`+`am`
для переноса между репозиториями. Выбор зависит от того, нужен ли один фикс, вся ветка
или её часть.

</details>

**2.** ⭐ Что делает `git rebase` и чем отличается от `git merge`?

<details><summary>Ответ</summary>

Rebase переносит коммиты ветки поверх другой, создавая новые коммиты и линейную историю;
merge объединяет ветки merge-коммитом, сохраняя исходные коммиты и хронологию.

</details>

**3.** Почему rebase «переписывает историю»?

<details><summary>Ответ</summary>

Потому что применяет коммиты заново поверх другого родителя: содержимое коммита меняется
(другой parent), значит меняется хеш — это новые объекты, а старые становятся недостижимыми.

</details>

**4.** Что такое золотое правило rebase?

<details><summary>Ответ</summary>

Не делать rebase коммитов, которые уже опубликованы и которые могли забрать другие.

</details>

**5.** Что такое `git cherry-pick` и когда его применяют?

<details><summary>Ответ</summary>

Копирует конкретный коммит в текущую ветку. Классика — бэкпорт фикса из `main`
в релизную ветку без переноса остальных изменений.

</details>

**6.** Что такое интерактивный rebase и зачем он нужен?

<details><summary>Ответ</summary>

`git rebase -i` позволяет переписать набор своих коммитов: объединить, удалить,
переставить, изменить сообщения. Нужен, чтобы привести ветку в порядок перед ревью.

</details>

**7.** Чем `squash` отличается от `fixup`?

<details><summary>Ответ</summary>

`squash` объединяет коммит с предыдущим и даёт отредактировать общее сообщение;
`fixup` делает то же, но сообщение коммита выбрасывает.

</details>

**8.** Как безопасно запушить ветку после rebase?

<details><summary>Ответ</summary>

`git push --force-with-lease` — отправит, только если ветку на сервере никто не двигал
с момента последнего fetch. И только в свою ветку.

</details>

**9.** Что произойдёт, если сделать force-push в общую ветку?

<details><summary>Ответ</summary>

Серверная история перезапишется, коммиты коллег из этой ветки исчезнут, у всех
разойдутся истории; восстанавливать придётся через reflog у тех, кто успел их забрать.

</details>

**10.** Что делать, если rebase пошёл не так?

<details><summary>Ответ</summary>

`git rebase --abort` — если rebase ещё идёт; `git reflog` + `git reset --hard <хеш>` —
если уже завершён; `git range-diff` — чтобы понять, что именно изменилось.

</details>
