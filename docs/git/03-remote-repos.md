---
title: "03. Удалённые репозитории"
description: "clone, push, pull, fetch, SSH-ключи, origin/main и разбор git pull под капотом"
---

# 03. Удалённые репозитории: clone, push, pull, fetch

> Роадмап → 1. Git → Теория → **5 главных команд**: `git push` (отправить коммиты
> в репозиторий), `git pull` (забрать изменения из репозитория) + `git clone` из блока
> «что ещё стоит изучить».
> Роадмап → 3. Собесы: **«Как работает git pull (что под капотом)?»** — разбор в §6.
> **После темы ты умеешь:** подключить репозиторий к GitHub/GitLab по SSH, понимать
> `origin/main` vs `main`, объяснить разницу `fetch` и `pull` и разрулить `rejected` при push.

---

## 🗺️ Карта темы

```text:no-line-numbers
  ЛОКАЛЬНЫЙ РЕПОЗИТОРИЙ                                  УДАЛЁННЫЙ (origin)
 ┌──────────────────────────────────────────┐          ┌────────────────────────┐
 │ working tree                             │          │                        │
 │      ▲                                   │          │   refs/heads/main      │
 │      │ merge / rebase                    │          │        c1─c2─c3─c9     │
 │ main            c1─c2─c3─c4  ← мои       │          │                        │
 │ origin/main     c1─c2─c3     ← «снимок   │          └────────────────────────┘
 │  (remote-tracking)             чужого        ▲    │
 │                                состояния»    │    │
 └──────────────────────────────────────────┘   │    │
                              git fetch ─────────┘    │   (обновляет ТОЛЬКО origin/main)
                              git push ───────────────┘   (отправляет мои коммиты)

     git pull = git fetch  +  git merge origin/main   ← ⭐ вопрос с собеса
                          (или + git rebase, если pull.rebase=true)
```

---

## 1. Что такое remote

**Remote** — именованная ссылка на другой репозиторий (обычно на сервере).
Имя по умолчанию — **`origin`** (это просто соглашение, не ключевое слово).

```bash
git remote -v
# origin  git@gitlab.com:nurik/devops-notes.git (fetch)
# origin  git@gitlab.com:nurik/devops-notes.git (push)

git remote add origin git@gitlab.com:nurik/devops-notes.git
git remote add upstream https://github.com/original/project.git   # при работе с форком
git remote rename origin gitlab
git remote remove upstream
git remote show origin            # подробности: ветки, что с чем связано
git remote set-url origin git@gitlab.com:nurik/notes.git          # сменить адрес (https → ssh)
```

Remote'ов может быть несколько: типичный пример — зеркалирование в GitHub и GitLab
одновременно, или `origin` (твой форк) + `upstream` (оригинальный проект).

---

## 2. HTTPS или SSH

| | HTTPS | SSH |
|---|-------|-----|
| URL | `https://gitlab.com/nurik/notes.git` | `git@gitlab.com:nurik/notes.git` |
| Аутентификация | Логин + **токен** (пароли отменили) | Пара SSH-ключей |
| Проходит через прокси/фаервол | Обычно да | Иногда порт 22 закрыт (есть `ssh.github.com:443`) |
| Удобство | Нужен credential helper, иначе токен каждый раз | Один раз настроил — и забыл |
| Где применяют | CI-джобы (токен в переменной), закрытые сети | Рабочие машины разработчиков |

### Настройка SSH-ключа (делается один раз)

```bash
ssh-keygen -t ed25519 -C "kolbai@sofiasoft.kz"     # Enter, Enter (или задай пароль ключа)
cat ~/.ssh/id_ed25519.pub                          # ⬅ ЭТО копируем в веб-интерфейс
# GitHub:  Settings → SSH and GPG keys → New SSH key
# GitLab:  Preferences → SSH Keys → Add new key

ssh -T git@github.com      # проверка: "Hi nurik! You've successfully authenticated..."
ssh -T git@gitlab.com      # проверка: "Welcome to GitLab, @nurik!"
```

⚠️ В профиль загружается **только `.pub`**. Приватный ключ (`~/.ssh/id_ed25519`, права 600)
не покидает твою машину никогда.

Несколько аккаунтов/ключей — через `~/.ssh/config`:
```text:no-line-numbers
Host gitlab-work
    HostName gitlab.com
    User git
    IdentityFile ~/.ssh/id_ed25519_work
```
затем `git clone git@gitlab-work:company/infra.git`.

### HTTPS + токен

```bash
git config --global credential.helper store    # сохранит токен в ~/.git-credentials (в открытом виде!)
git config --global credential.helper cache --timeout=3600   # лучше: в памяти на час
# В CI: https://gitlab-ci-token:${CI_JOB_TOKEN}@gitlab.com/...
```

---

## 3. `git clone` — забрать репозиторий целиком

```bash
git clone git@gitlab.com:nurik/devops-notes.git
git clone <url> моя-папка               # в каталог с другим именем
git clone --branch develop <url>        # сразу переключиться на ветку
git clone --depth 1 <url>               # ⭐ shallow: только последний коммит (быстро, для CI)
git clone --single-branch --branch main <url>
git clone --bare <url>                  # голая копия (для зеркал)
```

Что делает `clone` (важно понимать, это четыре действия):
1. Создаёт папку и `git init` внутри.
2. Добавляет remote `origin` с указанным URL.
3. Скачивает **всю** историю: коммиты, ветки, теги.
4. Переключается на основную ветку и раскладывает файлы в рабочий каталог.

Поэтому `clone` ≠ «скачать файлы»: ты получаешь полноценный репозиторий с историей,
из которого можно работать офлайн.

---

## 4. ⭐ `origin/main` — что это за ветка

```bash
git branch          # локальные ветки:      main, feature/x
git branch -r       # удалённые (tracking): origin/main, origin/develop
git branch -a       # все
```

`origin/main` — **remote-tracking branch**: локальный «снимок» того, где была ветка `main`
на сервере **в момент последнего `fetch`/`pull`/`push`**. Это не живая ссылка на сервер:
пока ты не сделал `fetch`, git понятия не имеет, что коллеги что-то запушили.

```text:no-line-numbers
После fetch:      main (мой)      c1─c2─c3─c4
                  origin/main     c1─c2─c3─c9        ← видно расхождение

git status:  "Your branch and 'origin/main' have diverged,
              and have 1 and 1 different commits each"
```

**Upstream (tracking)** — связка «локальная ветка ↔ удалённая»:
```bash
git push -u origin main            # -u = --set-upstream, связать и запушить
git branch -vv                     # показать связки:  main abc123 [origin/main] сообщение
git branch --set-upstream-to=origin/main main
```
Когда связка есть, можно писать просто `git push` и `git pull` без аргументов.

---

## 5. `git push` — отправить коммиты

```bash
git push                          # если upstream настроен
git push origin main              # явно: куда и что
git push -u origin feature/login  # первый push новой ветки + связать
git push origin --tags            # отправить теги (они НЕ уходят с обычным push!)
git push origin --delete old-branch   # удалить ветку на сервере
git push --force-with-lease       # ⚠️ переписать историю на сервере (тема 06)
```

### Что происходит при push

1. Git находит коммиты, которых нет на сервере.
2. Отправляет объекты (коммиты, деревья, blob'ы).
3. Просит сервер **передвинуть** `refs/heads/main` на новый коммит.

Шаг 3 выполняется, только если это **fast-forward** — то есть серверный коммит является
предком твоего. Иначе push отклоняется:

```text:no-line-numbers
! [rejected]        main -> main (fetch first)
error: failed to push some refs to 'gitlab.com:nurik/notes.git'
hint: Updates were rejected because the remote contains work that you do not have locally.
```

**Это не ошибка, а защита**: кто-то запушил раньше тебя, и твой push затёр бы их коммиты.
Правильный порядок действий:

```bash
git pull            # забрать чужое и слить со своим (или git pull --rebase)
# разрулить конфликты, если появились (тема 05)
git push            # теперь fast-forward, пройдёт
```

> ⚠️ `git push --force` в этой ситуации **уничтожит чужие коммиты**. Никогда не делай force
> в общую ветку. Если очень надо — только `--force-with-lease` и только в свою личную ветку
> (тема 06).

---

## 6. ⭐⭐ `git fetch` vs `git pull` — вопрос с собеседования

### `git fetch` — «посмотреть, что там нового»

```bash
git fetch                 # скачать изменения из origin
git fetch --all           # из всех remote'ов
git fetch --prune         # + удалить локальные origin/* веток, которых больше нет на сервере
```

Fetch **скачивает объекты и двигает `origin/*`**, но **не трогает твои локальные ветки
и рабочий каталог**. После fetch можно спокойно посмотреть, что прилетело:

```bash
git fetch
git log --oneline main..origin/main      # какие коммиты есть у них, но нет у меня
git diff main origin/main                # что изменится
git log --oneline origin/main..main      # какие коммиты есть у меня, но нет у них
```

### `git pull` = `git fetch` + `git merge`

```bash
git pull                     # = git fetch origin && git merge origin/main
git pull --rebase            # = git fetch origin && git rebase origin/main
git pull --ff-only           # ⭐ забрать, только если можно перемоткой; иначе — остановиться
```

Ровно это и есть ответ на вопрос «что под капотом у git pull»:

```text:no-line-numbers
git pull
   │
   ├─ 1. git fetch origin            → скачать новые объекты, передвинуть origin/main
   │
   └─ 2. git merge origin/main       → слить origin/main в текущую ветку
          ├─ история не разошлась  → fast-forward (просто перемотка указателя)
          ├─ история разошлась     → merge-коммит
          └─ конфликт              → остановка, разрешаешь руками (тема 05)
```

С `pull.rebase=true` второй шаг — `git rebase origin/main`: твои коммиты «переставляются»
поверх чужих, история остаётся линейной (тема 06).

| | fetch | pull |
|---|------|------|
| Трогает `origin/*` | ✅ | ✅ |
| Трогает локальную ветку | ❌ | ✅ |
| Трогает рабочий каталог | ❌ | ✅ |
| Может вызвать конфликт | ❌ | ✅ |
| Когда применять | «Посмотреть, что у коллег» | «Забрать и продолжить работу» |

> 🎤 **Формулировка для собеса:** «`git pull` — это составная команда: сначала `git fetch`,
> который скачивает новые объекты и обновляет remote-tracking ветки, затем `git merge`
> (или `git rebase` при `--rebase`), который вливает `origin/<ветка>` в мою текущую ветку.
> Поэтому pull может привести к merge-коммиту и к конфликту, а fetch — никогда.
> Если хочу безопасно посмотреть изменения перед вливанием, делаю fetch и смотрю
> `git log main..origin/main`.»

---

## 7. Первый репозиторий на хостинге: два пути

### Путь А. Репозиторий уже создан на GitLab/GitHub (проще)
```bash
git clone git@gitlab.com:nurik/devops-notes.git
cd devops-notes
# ... работаешь ...
git add . && git commit -m "add linux notes"
git push
```

### Путь Б. Локальная папка уже есть (типично для твоих конспектов)
```bash
cd ~/Documents/Triple/Life/DevOps
git init                                  # если ещё не репозиторий
git add .
git commit -m "initial: конспекты по Linux, Docker, CI/CD, Ansible, k8s"
# создаём ПУСТОЙ репозиторий в веб-интерфейсе (без README!)
git remote add origin git@gitlab.com:nurik/devops-notes.git
git branch -M main                        # переименовать текущую ветку в main
git push -u origin main
```

⚠️ Если при создании репозитория на хостинге поставить галочку «Add README», у сервера будет
свой коммит, и первый `push` отклонится. Лечение: `git pull --rebase origin main`, затем push.

---

## 8. Синхронизация в команде: типовой день

```bash
git switch main            # 1. на основную ветку
git pull                   # 2. забрать чужое
git switch -c feature/add-monitoring     # 3. своя ветка (тема 04)
# ... правки ...
git add . && git commit -m "feat: add prometheus scrape config"
git fetch && git rebase origin/main      # 4. подтянуть свежий main под себя (или merge)
git push -u origin feature/add-monitoring  # 5. отправить ветку
# 6. в веб-интерфейсе: открыть MR/PR (тема 11)
```

**Правило:** начинать день с `git pull` в основной ветке. Чем дольше ветка живёт без
синхронизации, тем больнее будут конфликты (тема 05).

---

## 9. Диагностика проблем с удалёнкой

```bash
git remote -v                       # правильный ли URL
git remote show origin              # что сервер думает о ветках
ssh -T git@gitlab.com               # работает ли SSH-аутентификация
ssh -vT git@github.com              # подробно: какой ключ предлагается
git ls-remote origin                # список веток и тегов на сервере (проверка доступа)
GIT_TRACE=1 GIT_CURL_VERBOSE=1 git push    # полный лог (для HTTPS-проблем)
git config --get remote.origin.url
```

| Ошибка | Причина | Лечение |
|--------|---------|---------|
| `Permission denied (publickey)` | Ключ не добавлен в профиль / не тот ключ / агент не запущен | `ssh -T`, `ssh-add -l`, добавить `.pub` в профиль |
| `remote: HTTP Basic: Access denied` | По HTTPS вводится пароль вместо токена | Создать Personal Access Token или перейти на SSH |
| `! [rejected] ... (fetch first)` | На сервере есть коммиты, которых нет у тебя | `git pull` (или `--rebase`), потом push |
| `! [rejected] ... (non-fast-forward)` | Твоя история разошлась с серверной | `git pull --rebase`; force — только в личную ветку |
| `fatal: refusing to merge unrelated histories` | Две независимые истории (локальная + README с сервера) | `git pull origin main --allow-unrelated-histories` |
| `Could not read from remote repository` | Неверный URL/нет прав/репозиторий удалён | `git remote -v`, проверить доступ в веб-интерфейсе |
| `Support for password authentication was removed` | GitHub больше не принимает пароль | Токен или SSH |

---

## 💼 Как это в DevOps

- **SSH-ключи** — база: у DevOps-инженера их обычно несколько (личный, рабочий, для CI-раннера,
  для деплой-ключей в репозиториях).
- **Deploy key** — SSH-ключ с доступом только к одному репозиторию (часто read-only);
  именно так серверы и ArgoCD ходят в git-репозиторий с манифестами.
- В CI клонирование почти всегда **shallow** (`--depth 1` / `GIT_DEPTH: 1` в GitLab CI) —
  это экономит минуты на больших репозиториях. Обратная сторона: `git describe` и история
  недоступны, иногда приходится увеличивать глубину.
- `git fetch --prune` стоит делать регулярно: после merge веток в MR они удаляются на сервере,
  а у тебя локально копятся десятки мёртвых `origin/feature/*`.
- Зеркала: `git push --mirror` в резервный хостинг — простейшая защита от «GitLab прилёг».
- Правило команды: **в `main` не пушат напрямую**, ветка защищена (protected branch),
  всё идёт через MR — тема 11.

---

## 📌 Шпаргалка

| Хочу | Как |
|------|-----|
| Скачать репозиторий | `git clone <url>` |
| Быстрый клон для CI | `git clone --depth 1 <url>` |
| Посмотреть remote'ы | `git remote -v` |
| Подключить хостинг к локальной папке | `git remote add origin <url>` |
| Сменить HTTPS на SSH | `git remote set-url origin git@...` |
| Проверить SSH-доступ | `ssh -T git@gitlab.com` |
| Первый push ветки | `git push -u origin <ветка>` |
| Отправить теги | `git push origin --tags` |
| Удалить ветку на сервере | `git push origin --delete <ветка>` |
| Посмотреть, что нового, не сливая | `git fetch` → `git log main..origin/main` |
| Забрать и слить | `git pull` |
| Забрать с перебазированием | `git pull --rebase` |
| Только перемотка, без merge-коммитов | `git pull --ff-only` |
| Почистить мёртвые origin/* | `git fetch --prune` |
| Показать связки веток | `git branch -vv` |

---

## 🧠 Что запомнить

1. **Remote** — именованная ссылка на другой репозиторий; `origin` — просто имя по умолчанию.
2. `clone` = init + remote add + скачать всю историю + checkout основной ветки.
3. **SSH-ключ**: в профиль кладётся только `.pub`, приватный не покидает машину;
   проверка — `ssh -T git@gitlab.com`.
4. `origin/main` — **снимок** состояния сервера на момент последнего fetch, а не живая ссылка.
5. `git push -u origin <ветка>` связывает локальную ветку с удалённой (upstream).
6. **Push проходит только fast-forward.** `rejected` = «сначала забери чужие коммиты».
7. ⭐ **`git pull` = `git fetch` + `git merge`** (или `+ rebase` с `--rebase`).
8. `fetch` безопасен: он не трогает твои ветки и рабочий каталог; `pull` — трогает.
9. `--force` в общую ветку уничтожает чужую работу; максимум — `--force-with-lease` в личной.
10. Теги не уходят обычным push — нужен `--tags` (тема 08).
11. День начинается с `git pull` в основной ветке; ветка, не синхронизированная неделю, —
    источник тяжёлых конфликтов.

---

## Задачи

> Стенд: аккаунт на GitLab.com и/или GitHub + песочница `~/git-lab`.
> Часть задач можно выполнить **без интернета**: «сервером» будет локальный bare-репозиторий
> (`git init --bare ~/git-lab/server.git`) — это полноценный origin.

---

### Блок A. Теория

**A1.** Что такое remote? Является ли слово `origin` ключевым для git?

<details><summary>Ответ</summary>

Remote — именованная ссылка (алиас) на URL другого репозитория. `origin` —
общепринятое имя по умолчанию, которое ставит `git clone`; ключевым словом не является,
remote можно назвать как угодно и иметь несколько.

</details>

**A2.** Перечисли четыре действия, которые выполняет `git clone`.

<details><summary>Ответ</summary>

(1) Создаёт каталог и инициализирует в нём репозиторий; (2) добавляет remote `origin`
с указанным URL; (3) скачивает всю историю — объекты, ветки, теги; (4) переключается
на основную ветку и раскладывает файлы в рабочий каталог.

</details>

**A3.** ⭐ Что такое `origin/main` и чем она отличается от `main`?

<details><summary>Ответ</summary>

`main` — твоя локальная ветка, которую ты двигаешь коммитами. `origin/main` —
remote-tracking ветка, локальный снимок того, где `main` находилась на сервере в момент
последнего `fetch`/`pull`/`push`. Двигать её вручную нельзя, обновляется только сетевыми
командами.

</details>

**A4.** Что такое upstream/tracking branch и что даёт связка веток?

<details><summary>Ответ</summary>

Upstream — привязка локальной ветки к удалённой. Даёт: `git push`/`git pull` без
аргументов, отображение «ahead/behind» в `git status`, корректную работу `git branch -vv`.
Устанавливается `git push -u origin <ветка>` или `git branch --set-upstream-to`.

</details>

**A5.** ⭐⭐ Что делает `git pull` «под капотом»? Ответь так, как отвечал бы на собесе.

<details><summary>Ответ</summary>

`git pull` = `git fetch` + `git merge` (по умолчанию). Fetch скачивает новые объекты
и обновляет `origin/<ветка>`; merge вливает `origin/<ветка>` в текущую локальную ветку —
перемоткой (fast-forward), если история не расходилась, или merge-коммитом, если расходилась;
при пересечении правок — конфликт. С `--rebase` вторым шагом выполняется `git rebase`,
и история остаётся линейной.

</details>

**A6.** ⭐ Чем `git fetch` отличается от `git pull`? Когда какой использовать?

<details><summary>Ответ</summary>

`fetch` только скачивает и обновляет `origin/*`; локальные ветки и рабочий каталог
не трогает. `pull` дополнительно сливает изменения в текущую ветку. Fetch — когда хочешь
сначала посмотреть; pull — когда готов принять изменения.

</details>

**A7.** Почему `git fetch` не может привести к конфликту, а `git pull` может?

<details><summary>Ответ</summary>

Fetch не изменяет твою ветку и рабочий каталог — он просто записывает объекты и двигает
служебные ссылки `origin/*`. Конфликт возникает только при слиянии (merge/rebase), то есть
на втором шаге pull.

</details>

**A8.** Что такое fast-forward и почему push проходит только в этом случае?

<details><summary>Ответ</summary>

Fast-forward — ситуация, когда текущий коммит ветки является предком целевого,
и указатель можно просто «перемотать» вперёд без создания merge-коммита. Push требует
fast-forward на стороне сервера, иначе отправка затёрла бы коммиты, которых у тебя нет.

</details>

**A9.** `! [rejected] main -> main (fetch first)` — что произошло и какой правильный порядок действий?

<details><summary>Ответ</summary>

На сервере появились коммиты, которых нет локально (кто-то запушил раньше).
Порядок: `git pull` (или `git pull --rebase`) → разрешить конфликты, если есть → `git push`.

</details>

**A10.** Почему `git push --force` в общую ветку — плохая идея? Чем `--force-with-lease` лучше?

<details><summary>Ответ</summary>

`--force` безусловно переписывает серверную ветку: коммиты коллег, о которых ты
не знаешь, исчезают из ветки. `--force-with-lease` проверяет, что удалённая ветка находится
там, где ты её видел при последнем fetch; если кто-то успел запушить — отказ. Это «force
с предохранителем», но и он не отменяет правила «не переписывать общие ветки».

</details>

**A11.** HTTPS или SSH: что выберешь для рабочего ноутбука, что — для CI-раннера и почему?

<details><summary>Ответ</summary>

Ноутбук — SSH: настроил ключ один раз, дальше без ввода паролей. CI-раннер — HTTPS
с токеном из переменной окружения (`CI_JOB_TOKEN`) либо SSH deploy key: секрет хранится
в переменных CI, легко ротируется и ограничен по правам.

</details>

**A12.** Какую часть SSH-ключа загружают в профиль GitHub/GitLab и где лежит вторая?

<details><summary>Ответ</summary>

В профиль — только публичная часть (`~/.ssh/id_ed25519.pub`). Приватный ключ
(`~/.ssh/id_ed25519`, права 600) остаётся на машине и никуда не отправляется.

</details>

**A13.** Что такое deploy key и зачем он нужен?

<details><summary>Ответ</summary>

SSH-ключ, привязанный не к пользователю, а к конкретному репозиторию, обычно
read-only. Используется серверами, CI и ArgoCD для доступа ровно к одному репозиторию —
компрометация такого ключа не даёт доступ ко всему аккаунту.

</details>

**A14.** Зачем в CI делают `git clone --depth 1`? Какой минус у этого?

<details><summary>Ответ</summary>

Чтобы не тянуть всю историю (на больших репозиториях это минуты и гигабайты) —
в CI нужен только последний коммит. Минусы: недоступна история, ломаются `git describe`,
`git log`, сравнение с предыдущими коммитами, поиск базы для diff'а MR; иногда приходится
увеличивать глубину.

</details>

**A15.** Что делает `git fetch --prune` и почему это стоит делать регулярно?

<details><summary>Ответ</summary>

Удаляет локальные remote-tracking ветки (`origin/*`), которых больше нет на сервере.
Регулярно — потому что после слияния MR ветки удаляют, и без prune у тебя копятся десятки
мёртвых ссылок, мешающих автодополнению и `git branch -r`.

</details>

**A16.** Уходят ли теги при обычном `git push`?

<details><summary>Ответ</summary>

Нет. Теги отправляются отдельно: `git push origin <tag>` или `git push --tags`
(и `--follow-tags` для аннотированных тегов при обычном push).

</details>

**A17.** Что означает `fatal: refusing to merge unrelated histories` и как это чаще всего получается?

<details><summary>Ответ</summary>

Git отказывается сливать две истории без общего предка. Типичный сценарий: репозиторий
на хостинге создан с README (свой коммит), а локально уже был `git init` со своим первым
коммитом. Решения: `git pull origin main --allow-unrelated-histories` (и разрешить конфликты)
или создать репозиторий на хостинге пустым.

</details>

---

### Блок B. «Что делает команда»

```bash
B1.  git clone git@gitlab.com:nurik/notes.git
B2.  git clone --depth 1 --branch main https://gitlab.com/nurik/notes.git
B3.  git remote -v
B4.  git remote add upstream https://github.com/original/project.git
B5.  git remote set-url origin git@github.com:nurik/notes.git
B6.  git remote show origin
B7.  git branch -vv
B8.  git branch -r
B9.  git push -u origin feature/monitoring
B10. git push origin --delete feature/old
B11. git push origin --tags
B12. git fetch --all --prune
B13. git log --oneline main..origin/main
B14. git log --oneline origin/main..main
B15. git pull --rebase
B16. git pull --ff-only
B17. git ls-remote origin
B18. ssh -T git@gitlab.com
```

<details><summary>Ответ</summary>

```text:no-line-numbers
B1.  Клонировать репозиторий по SSH в папку notes
B2.  Быстрый клон: только последний коммит ветки main по HTTPS
B3.  Показать список remote'ов и их URL (для fetch и push)
B4.  Добавить второй remote upstream (типично при работе с форком)
B5.  Сменить URL origin (например, перевести репозиторий с HTTPS на SSH)
B6.  Подробности об origin: ветки, связки, что устарело
B7.  Локальные ветки с их upstream-ветками и статусом ahead/behind
B8.  Список remote-tracking веток (origin/*)
B9.  Первый push ветки + установка upstream
B10. Удалить ветку feature/old на сервере
B11. Отправить на сервер все локальные теги
B12. Скачать изменения из всех remote'ов и удалить мёртвые origin/*
B13. Коммиты, которые есть на сервере, но нет у меня (что прилетит при pull)
B14. Коммиты, которые есть у меня, но нет на сервере (что уйдёт при push)
B15. Забрать изменения и перебазировать свои коммиты поверх них (линейная история)
B16. Забрать изменения, только если это перемотка; иначе — остановиться с ошибкой
B17. Показать ветки и теги на сервере, не скачивая объекты (проверка доступа)
B18. Проверить SSH-аутентификацию на GitLab
```

</details>

---

### Блок C. Практика

#### C1. 🔑 SSH-ключ и первый репозиторий на хостинге
1. Сгенерируй ключ: `ssh-keygen -t ed25519 -C "kolbai@sofiasoft.kz"`.
2. Добавь `~/.ssh/id_ed25519.pub` в профиль GitLab и/или GitHub.
3. Проверь: `ssh -T git@gitlab.com`.
4. Создай в веб-интерфейсе **пустой** репозиторий `devops-notes` (без README!).
5. Подключи локальную папку и запушь:
```bash
cd ~/git-lab/t02
git remote add origin git@gitlab.com:<логин>/devops-notes.git
git branch -M main
git push -u origin main
```
6. Проверь `git branch -vv` и `git remote -v`.

#### C2. Локальный «сервер» без интернета
```bash
cd ~/git-lab
git init --bare server.git
git clone server.git alice          # первый «разработчик»
git clone server.git bob            # второй «разработчик»
cd alice
echo "# Проект" > README.md && git add . && git commit -m "init"
git push -u origin main
cd ../bob && git pull               # ⭐ или сначала git fetch — посмотри разницу
ls
```
Этот стенд понадобится во всех следующих задачах и в темах 04-06.

#### C3. ⭐ fetch ≠ pull — увидеть своими глазами
```bash
cd ~/git-lab/alice
echo "строка от Алисы" >> README.md && git commit -am "alice: update readme" && git push

cd ~/git-lab/bob
git log --oneline           # коммита Алисы нет
git fetch
git log --oneline           # ⭐ его ВСЁ ЕЩЁ нет. Почему?
git log --oneline origin/main   # а тут есть
git status                  # что говорит про отставание?
git log --oneline main..origin/main
git diff main origin/main
git merge origin/main       # вот теперь влился (это и есть вторая половина pull)
git log --oneline
```
Запиши ответ: что именно поменял `fetch`, а что — `merge`.

<details><summary>Ответ</summary>

`fetch` скачал объекты и передвинул `origin/main`; локальная `main` и файлы
на диске не изменились, поэтому `git log` без аргументов коммита Алисы не показывает.
`git status` сообщает `behind 'origin/main' by 1 commit`. `merge origin/main` двигает
локальную `main` (здесь — fast-forward) и обновляет рабочий каталог.

</details>

#### C4. Push отклонён (самая частая ситуация в команде)
```bash
cd ~/git-lab/alice
echo "правка Алисы" >> README.md && git commit -am "alice: fix" && git push

cd ~/git-lab/bob
echo "правка Боба" >> notes.txt && git add . && git commit -m "bob: notes"
git push                      # ⛔ rejected — прочитай текст ошибки ЦЕЛИКОМ
git pull                      # забрать чужое
git log --oneline --graph     # ⭐ появился merge-коммит?
git push                      # теперь прошло
```

<details><summary>Ответ</summary>

Push Боба отклонён, потому что на сервере есть коммит Алисы, которого нет у Боба.
`git pull` создаёт merge-коммит (истории разошлись: у обоих по одному новому коммиту),
после чего push проходит.

</details>

#### C5. `pull --rebase` vs `pull`
Повтори C4, но вместо `git pull` сделай `git pull --rebase`. Сравни `git lg` в обоих случаях.
Где история линейная, а где «ромб»? (Подробно — тема 06.)

<details><summary>Ответ</summary>

С `pull` в графе появляется merge-коммит и «ромб»; с `pull --rebase` коммит Боба
переставляется поверх коммита Алисы, история линейная, merge-коммита нет.

</details>

#### C6. Работа с ветками на сервере
```bash
cd ~/git-lab/bob
git switch -c feature/docs
echo "docs" > docs.md && git add . && git commit -m "add docs"
git push                       # ⛔ что скажет git? прочитай подсказку
git push -u origin feature/docs
git branch -vv

cd ~/git-lab/alice
git fetch
git branch -r                  # видна ли ветка Боба?
git switch feature/docs        # git сам создаст локальную ветку — как?
```

<details><summary>Ответ</summary>

Обычный `git push` для новой ветки просит указать upstream — git печатает готовую
подсказку `git push --set-upstream origin feature/docs`. У Алисы после `git fetch` ветка видна
как `origin/feature/docs`; `git switch feature/docs` создаёт локальную ветку автоматически
(DWIM: имя совпадает ровно с одной remote-веткой).

</details>

#### C7. Уборка мёртвых веток
```bash
cd ~/git-lab/bob
git push origin --delete feature/docs
cd ~/git-lab/alice
git branch -r                  # ветка всё ещё видна!
git fetch --prune
git branch -r                  # а теперь?
```

<details><summary>Ответ</summary>

До `--prune` git хранит устаревшие ссылки локально — он не знает, что ветку удалили.
`git fetch --prune` синхронизирует список.

</details>

#### C8. Несколько remote'ов
```bash
cd ~/git-lab/bob
git init --bare ~/git-lab/mirror.git
git remote add mirror ~/git-lab/mirror.git
git push mirror main
git remote -v
git ls-remote mirror
```
Где это используется в реальной жизни?

<details><summary>Ответ</summary>

Несколько remote'ов используют для зеркалирования (резервный хостинг), для форков
(`origin` — твой форк, `upstream` — исходный проект), для публикации в разные окружения.

</details>

#### C9. Shallow clone
```bash
cd ~/git-lab
git clone --depth 1 server.git shallow-test
cd shallow-test
git log --oneline            # сколько коммитов видно?
git log --oneline --all
cat .git/shallow
git fetch --unshallow        # вернуть полную историю
git log --oneline
```

<details><summary>Ответ</summary>

В shallow-клоне виден 1 коммит, в `.git/shallow` — хеш «границы» истории.
`--unshallow` дотягивает всю историю.

</details>

#### C10. Диагностика
Выполни и объясни вывод:
```bash
git remote show origin
git ls-remote origin
ssh -vT git@gitlab.com 2>&1 | grep -E "Offering|Authenticated|debug1: Next"
git config --get remote.origin.url
```

---

### Блок D. Инциденты

**D1.** `git push` → `Permission denied (publickey)`. Пять шагов диагностики по порядку.

<details><summary>Ответ</summary>

(1) `ssh -T git@gitlab.com` — проходит ли аутентификация; (2) `git remote -v` —
точно ли SSH-URL, а не HTTPS; (3) `ssh-add -l` / запущен ли агент, добавлен ли нужный ключ;
(4) `ssh -vT` — какой ключ реально предлагается; (5) добавлен ли `.pub` именно в тот аккаунт
и есть ли у аккаунта права на репозиторий (плюс права 600 на приватный ключ).

</details>

**D2.** `git push` → `! [rejected] main -> main (fetch first)`. Коллега советует
`git push --force`. Что произойдёт и что нужно сделать вместо этого?

<details><summary>Ответ</summary>

`--force` перезапишет серверную ветку твоей историей, и коммиты коллег, которых
у тебя нет, исчезнут из ветки (восстанавливать придётся через reflog на чьей-то машине).
Правильно: `git pull` (или `--rebase`), разрешить конфликты, `git push`.

</details>

**D3.** Создал репозиторий на GitHub с галочкой «Add a README file», потом запушил локальный:
`fatal: refusing to merge unrelated histories`. Что произошло и два способа решения.

<details><summary>Ответ</summary>

На сервере коммит с README, локально — свой первый коммит; общего предка нет.
Решения: (1) `git pull origin main --allow-unrelated-histories`, разрешить конфликты, push;
(2) если серверный репозиторий пустой по смыслу — пересоздать его без README и запушить заново.

</details>

**D4.** `git pull` завершился сообщением `You have divergent branches and need to specify
how to reconcile them`. Что хочет git и какие есть варианты?

<details><summary>Ответ</summary>

Git не знает, как объединить разошедшиеся ветки, и требует явной стратегии:
`git pull --rebase` (линейно), `git pull --no-rebase` (merge-коммит) или `git pull --ff-only`
(только перемотка, иначе ошибка). Постоянный выбор задаётся `git config pull.rebase true|false`.

</details>

**D5.** В CI-джобе `git clone` занимает 4 минуты из 6 минут пайплайна. Что настроить?

<details><summary>Ответ</summary>

`GIT_DEPTH: 1` (GitLab) / `fetch-depth: 1` (GitHub Actions), `--single-branch`,
кэш репозитория на раннере, `GIT_STRATEGY: fetch` вместо clone, отключение подмодулей,
если не нужны.

</details>

**D6.** После `git pull` в рабочем каталоге появились файлы с маркерами `<<<<<<<`.
Что произошло и почему при `git fetch` такого не бывает?

<details><summary>Ответ</summary>

`pull` выполнил merge, и git не смог автоматически объединить изменения — это
merge conflict (тема 05). При `fetch` слияния не происходит вообще, поэтому конфликтов нет.

</details>

**D7.** `git push` по HTTPS требует пароль, а пароль не подходит:
`Support for password authentication was removed`. Что делать (два варианта)?

<details><summary>Ответ</summary>

(1) Создать Personal Access Token и использовать его вместо пароля (плюс
`credential.helper`); (2) перейти на SSH: `git remote set-url origin git@github.com:...`.

</details>

**D8.** Локально ветка `feature/x` есть, на сервере — нет; `git push` пишет
`fatal: The current branch feature/x has no upstream branch`. Команда-лечение.

<details><summary>Ответ</summary>

`git push -u origin feature/x` (он же `--set-upstream`).

</details>

**D9.** Коллега сделал force-push в `main`, твои утренние коммиты исчезли из истории.
Что проверить у себя и как вернуть?

<details><summary>Ответ</summary>

Проверить `git reflog` и `git log origin/main` у себя: твои коммиты, скорее всего,
ещё в локальном репозитории и в reflog. Восстановить ветку по хешу
(`git branch rescue <хеш>`), затем согласовать с командой, кто и что возвращает в `main`.
Профилактика — защищённые ветки с запретом force-push.

</details>

**D10.** GitLab «прилёг» на полдня, дедлайн сегодня. Можешь ли ты работать? Что именно
не сможешь сделать?

<details><summary>Ответ</summary>

Работать можно: коммиты, ветки, merge, просмотр истории — всё локально.
Нельзя: `push`, `pull`/`fetch`, открыть MR, запустить пайплайн, посмотреть чужие изменения.
Обмен — через вторую remote (зеркало), патчи (`git format-patch`) или bundle (`git bundle`).

</details>

**D11.** У тебя два аккаунта — личный и рабочий, оба на GitHub, разные SSH-ключи.
`git clone` рабочего репозитория ходит под личным ключом. Как настроить?

<details><summary>Ответ</summary>

Через `~/.ssh/config`: описать два хоста-алиаса с разными `IdentityFile`
(например, `github-work` и `github.com`) и клонировать рабочие репозитории по
`git@github-work:company/repo.git`; либо задать ключ per-repo:
`git config core.sshCommand "ssh -i ~/.ssh/id_ed25519_work"`.

</details>

---

### Блок E. Вопросы с собеседования

**1.** ⭐⭐ Как работает `git pull`? Что происходит под капотом?

<details><summary>Ответ</summary>

Составная команда: `git fetch` (скачать объекты, обновить `origin/*`) + `git merge`
(влить `origin/<ветка>` в текущую). При `--rebase` вместо merge — rebase.
Отсюда: pull может дать merge-коммит и конфликт.

</details>

**2.** ⭐ Чем `git fetch` отличается от `git pull`?

<details><summary>Ответ</summary>

`fetch` только скачивает и обновляет remote-tracking ветки; `pull` дополнительно сливает
изменения в рабочую ветку и меняет файлы на диске.

</details>

**3.** Что такое `origin`?

<details><summary>Ответ</summary>

Имя по умолчанию для удалённого репозитория, откуда сделан клон.

</details>

**4.** Что такое `origin/main` и чем отличается от `main`?

<details><summary>Ответ</summary>

`main` — локальная ветка, которую двигаешь ты; `origin/main` — снимок состояния ветки
на сервере на момент последней синхронизации.

</details>

**5.** Что делает `git clone`?

<details><summary>Ответ</summary>

Создаёт локальный репозиторий, прописывает `origin`, скачивает всю историю и выкладывает
рабочую копию основной ветки.

</details>

**6.** Почему push может быть отклонён и что делать?

<details><summary>Ответ</summary>

Потому что push разрешён только fast-forward: на сервере есть коммиты, которых нет у тебя.
Нужно `git pull`/`git pull --rebase`, разрешить конфликты и запушить снова.

</details>

**7.** Чем опасен `git push --force`? Что такое `--force-with-lease`?

<details><summary>Ответ</summary>

Он затирает серверную историю вместе с чужими коммитами. `--force-with-lease` отправляет
только если удалённая ветка не изменилась с момента твоего последнего fetch.

</details>

**8.** Как отправить теги на сервер?

<details><summary>Ответ</summary>

`git push origin <tag>` или `git push --tags`; обычный push теги не отправляет.

</details>

**9.** SSH или HTTPS — что и когда?

<details><summary>Ответ</summary>

SSH — для постоянных рабочих машин (удобно, без ввода секретов); HTTPS с токеном —
для CI, временных окружений и сетей, где закрыт 22-й порт.

</details>

**10.** Как посмотреть, какие изменения есть на сервере, ничего не сливая к себе?

<details><summary>Ответ</summary>

`git fetch`, затем `git log --oneline main..origin/main` и `git diff main origin/main`.

</details>
