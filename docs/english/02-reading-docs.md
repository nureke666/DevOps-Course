---
title: "02. Чтение документации, ошибок и issues"
description: "Блок → Английский для IT → тема 02. Опирается на систему из"
---

# 02. Чтение документации, ошибок и issues

> Блок → Английский для IT → тема 02. Опирается на систему из
> [01_level_and_system.md](/english/01-level-and-system): чтение — главный input DevOps-инженера,
> и его можно тренировать прямо на рабочих задачах. Лексика отдельных областей —
> в [03_vocabulary.md](/english/03-vocabulary).
>
> **После темы ты умеешь:** выбирать режим чтения под задачу (skimming, scanning,
> intensive); ориентироваться в структуре любой документации; понимать типовые фразы доков
> (*deprecated*, *as of*, *defaults to*, *opt-in*); читать MUST/SHOULD/MAY по RFC 2119;
> разбирать `man` и `--help`; читать issue, changelog и release notes перед обновлением;
> разбирать сообщение об ошибке и stack trace по частям.

---

## 🗺️ Карта темы

```text
 ЧТО ЧИТАЕШЬ              РЕЖИМ          ГЛАВНЫЙ ВОПРОС
 ─────────────────────────────────────────────────────────────────────────────
 новая дока           ─► skimming   ─►  «это вообще то, что мне нужно?»
 флаг, дефолт, версия ─► scanning   ─►  Ctrl+F: defaults to, since, required
 настройка прода      ─► intensive  ─►  каждое предложение + пример руками
 release notes        ─► scanning   ─►  breaking, deprecated, removed, action required
 ошибка               ─► разбор     ─►  кто · что делал · с чем · почему
 stack trace          ─► разбор     ─►  последняя строка / последний «Caused by»
 issue на 40 сообщений ─► skim + scan ─► первый пост, конец, мейнтейнер, workaround
```text
---

## 1. Почему только оригинал

- **Версии.** Перевод и статьи отстают: читаешь про v1.24, а в кластере v1.33.
- **Точность.** *May* и *must*, *deprecated* и *removed* — в переводе часто одно и то же,
  а для прода это разные вещи.
- **Ошибки и логи** — всегда на английском и дословно совпадают с текстом в доке и issues.
- **Поиск.** Английский запрос находит ответ в разы чаще.

> ⭐ Цель — не «перевести страницу», а **понять, что делать**. Переводчик на всю страницу
> решает задачу сегодня, но не учит ничему: завтра снова нужен переводчик.

---

## 2. Три режима чтения

| Режим | Цель | Как | Когда в DevOps |
|-------|------|-----|----------------|
| **Skimming** (просмотр) | Общий смысл за 1–2 минуты | Заголовки, первые предложения абзацев, код, блоки Note/Warning | Понять, о чём страница; выбрать инструмент; пробежать release notes |
| **Scanning** (поиск) | Найти конкретный факт | Ctrl+F, взгляд по ключевым словам и цифрам | Значение по умолчанию, флаг, версия, лимит |
| **Intensive** (вдумчиво) | Понять полностью | Каждое предложение, пример — руками | То, что пойдёт в прод: RBAC, миграция, сеть, бэкапы |

Слова, по которым удобно сканировать: *default*, *required*, *optional*, *since*,
*deprecated*, *removed*, *must*, *note*, *warning*, *limit*, *example*.

---

## 3. Как устроена документация

Почти любая документация делится на одни и те же части:

```text
 Overview / Introduction    что это и зачем              → решить, нужно ли
 Quickstart / Get started   рабочий пример за 10 минут    → потрогать руками
 Concepts / Architecture    как устроено, модель          → понять, почему так
 Tasks / How-to guides      как сделать конкретную вещь   → решить задачу
 Tutorials                  обучение по шагам             → освоить с нуля
 Reference                  все поля, флаги, API          → уточнить деталь
 Troubleshooting / FAQ      типовые проблемы              → починить
 Release notes / Changelog  что изменилось в версии       → обновиться без сюрпризов
```text
Это деление описывает фреймворк **Diátaxis** (diataxis.fr): tutorials, how-to guides,
reference, explanation. В документации Kubernetes разделы так и называются: Getting
started, Concepts, Tasks, Tutorials, Reference.

**Порядок чтения нового инструмента:** Overview → Quickstart (руками) → Concepts →
нужный How-to → Reference по мере надобности. Начинать с Reference — как учить язык
по словарю.

**Типовая страница задачи** (Kubernetes Tasks и похожие):

| Раздел | Что там |
|--------|---------|
| *Before you begin* / *Prerequisites* | Что должно быть заранее: версия, доступы, инструменты |
| Шаги | Команды и манифесты по порядку |
| *Cleaning up* / *Clean up* | Как удалить созданное |
| *What's next* | Куда читать дальше |

Блоки-предупреждения (admonitions): **Note** — полезно знать; **Tip** — совет;
**Caution** / **Warning** — можно потерять данные или сломать; читать всегда.

---

## 4. Типовые фразы документации

### Жизненный цикл и версии

| Фраза | Значение | 🇬🇧 Пример |
|-------|----------|-----------|
| **deprecated** | Устарело: пока работает, но будет удалено | *The `--foo` flag is deprecated and will be removed in a future release.* |
| **removed** | Удалено, больше не работает | *PodSecurityPolicy was removed in v1.25.* |
| **obsolete** | Устарело и больше не используется | *The top-level `version` element is obsolete.* |
| **legacy** | Старое, оставлено для совместимости | *Legacy tokens are no longer created automatically.* |
| **as of v1.29** | Начиная с версии 1.29 (или «на момент»: *as of today*) | *As of v1.29, this feature is enabled by default.* |
| **since / starting with v1.29** | С версии 1.29 | *Available since v1.29.* |
| **prior to v1.29** | До версии 1.29 | *Prior to v1.29, you had to enable it manually.* |
| **alpha / beta / stable (GA)** | Стадии зрелости: эксперимент → почти готово → стабильно | *This feature is in beta and may change.* |
| **feature gate** | Переключатель, которым включают фичу | *Enable the `Foo` feature gate to use this field.* |
| **breaking change** | Ломает обратную совместимость | *This release contains breaking changes.* |
| **backward compatible** | Старое продолжает работать | *The new API is backward compatible.* |

### Поведение и настройки

| Фраза | Значение | 🇬🇧 Пример |
|-------|----------|-----------|
| **defaults to** / **by default** | По умолчанию | *`replicas` defaults to 1.* |
| **if omitted / if unset / if not specified** | Если не указать | *If omitted, the current namespace is used.* |
| **required / optional** | Обязательно / необязательно | *`image` is required.* |
| **out of the box** | Сразу, без настройки | *Metrics work out of the box.* |
| **opt-in** | Выключено, нужно включить самому | *Telemetry is opt-in.* |
| **opt-out** | Включено, можно выключить | *Telemetry is opt-out: set `DISABLE_TELEMETRY=1`.* |
| **takes precedence over** / **overrides** | Имеет приоритет | *Command-line flags take precedence over environment variables.* |
| **falls back to** | Переходит к запасному варианту | *If the file is missing, it falls back to the defaults.* |
| **mutually exclusive** | Нельзя указать одновременно | *`--all` and `--name` are mutually exclusive.* |
| **is subject to** | Подлежит, может быть изменено или ограничено | *Alpha APIs are subject to change. Requests are subject to rate limits.* |
| **scoped to** / **cluster-wide** | Действует в пределах / на весь кластер | *Roles are scoped to a namespace.* |
| **idempotent** | Повторный запуск даёт тот же результат | *The module is idempotent: running it twice changes nothing.* |
| **best-effort** | «Постараемся», без гарантий | *Delivery is best-effort.* |
| **eventually consistent** | Данные сойдутся со временем, не сразу | *The list is eventually consistent.* |
| **under the hood** | Внутри, как устроено | *Under the hood, it uses iptables.* |
| **caveat** | Оговорка, подвох | *One caveat: this does not work with IPv6.* |
| **at your own risk** | На свой страх и риск | *Use this flag at your own risk.* |

### Навигация и сокращения

| Фраза | Значение |
|-------|----------|
| *See …* / *Refer to …* / *For more information, see …* | Ссылка на другой раздел |
| *e.g.* | Например (*for example*) — ⚠️ не путать с *i.e.* |
| *i.e.* | То есть (*that is*) |
| *etc.*, *vs.*, *cf.* | И так далее; против; сравни |
| *N/A* | Неприменимо |
| *placeholder*, *replace `&lt;name&gt;` with …* | Подставь своё значение |

---

## 5. MUST, SHOULD, MAY: RFC 2119

В спецификациях, API-конвенциях и стандартах (в том числе в спецификации Conventional
Commits) слова в **ВЕРХНЕМ РЕГИСТРЕ** имеют строгий смысл по **RFC 2119**:

| Слово | Значение | Нарушил — что будет |
|-------|----------|---------------------|
| **MUST** / **REQUIRED** / **SHALL** | Обязательно | Не соответствует спецификации, может не работать |
| **MUST NOT** / **SHALL NOT** | Запрещено | То же |
| **SHOULD** / **RECOMMENDED** | Рекомендуется: отступить можно, если есть веская причина и ты понимаешь последствия | Работает, но на свой риск |
| **SHOULD NOT** / **NOT RECOMMENDED** | Не рекомендуется | То же |
| **MAY** / **OPTIONAL** | По желанию | Ничего |

**RFC 8174** уточняет: особый смысл у этих слов только в верхнем регистре. *Should*
строчными — обычное английское «следует».

🇬🇧 Пример (внутренняя спецификация):
```text
Health check endpoint, v2
- The service MUST expose GET /healthz on the main port.
- The endpoint MUST NOT require authentication.
- The response SHOULD complete within 100 ms.
- The response body MAY include build information (version, commit).
```text
Прочтение: `/healthz` без авторизации — обязательно; 100 мс — цель, но 150 мс не нарушение
спецификации; версия в ответе — по желанию.

---

## 6. `man` и `--help`

**Разделы man-страницы:** *NAME* (что это одной строкой) → *SYNOPSIS* (синтаксис) →
*DESCRIPTION* → *OPTIONS* → *EXIT STATUS* → *ENVIRONMENT* → *FILES* → *EXAMPLES* →
*SEE ALSO*. Для быстрого старта — сразу `/EXAMPLES`.

**Как читать SYNOPSIS:**

| Запись | Значение |
|--------|----------|
| `[OPTION]` | Необязательно |
| `...` | Можно повторить |
| `FILE`, `&lt;file&gt;`, *курсив* | Подставь своё значение |
| `a\|b` | Одно из двух |
| `(a \| b)` | Обязательная группа: выбери одно |
| **жирный** текст | Пишется буквально |

```text
cp [OPTION]... [-T] SOURCE DEST
kubectl scale [--resource-version=version] [--current-replicas=count] --replicas=COUNT (-f FILENAME | TYPE NAME)
```text
Прочтение второй строки: `--replicas` обязателен; дальше **либо** `-f файл`, **либо**
тип и имя ресурса; остальное — по желанию.

Навигация в `man`: `/pattern` — поиск, `n` — следующее совпадение, `q` — выход;
`man -k keyword` — найти команду по слову; секции: 1 — команды, 5 — форматы файлов,
8 — команды администратора (`man 5 crontab`). Короткие примеры — `tldr &lt;команда&gt;`.

---

## 7. GitHub issues, changelog, release notes

### Как читать issue на 40 сообщений

1. **Заголовок и первый пост:** та же ли версия, окружение, симптом?
2. **Конец треда:** текущий статус — *fixed in v2.3.1*, *closed as not planned*, открыто.
3. **Комментарии мейнтейнеров** (плашки *Member*, *Maintainer*, *Collaborator*) важнее
   десяти «+1».
4. **Ctrl+F:** *workaround*, *fixed in*, *regression*, *duplicate of*, номер своей версии.
5. **Связанные PR** (*linked pull requests*, *fixed by #1234*) — что именно поменяли.

### Сокращения в issues, ревью и чатах

| Сокращение | Расшифровка | Значение |
|------------|-------------|----------|
| LGTM | looks good to me | Одобряю |
| PTAL | please take a look | Посмотри, пожалуйста |
| WIP | work in progress | Не готово, не мержить |
| TL;DR | too long; didn't read | Коротко, суть |
| IIRC | if I recall correctly | Если правильно помню |
| AFAIK | as far as I know | Насколько я знаю |
| IMO / IMHO | in my (humble) opinion | По-моему |
| FWIW | for what it's worth | Если это поможет; к слову |
| FYI | for your information | К сведению |
| repro | reproduction / reproduce | Воспроизведение: *I can't repro it on v2.3* |
| nit | nitpick | Мелочь, необязательно |
| ETA | estimated time of arrival | Когда будет готово |
| TBD | to be determined | Ещё не решено |
| OOO | out of office | Нет на месте, в отпуске |
| EOD / EOW | end of day / end of week | К концу дня / недели |

**Метки** (labels): *bug*, *enhancement* / *feature request*, *good first issue*,
*help wanted*, *duplicate*, *wontfix*, *needs-triage*, *stale* (давно без активности —
скоро закроют бот). В Kubernetes — с префиксами: `kind/bug`, `priority/important-soon`,
`lifecycle/stale`.

### Changelog и release notes

Многие проекты ведут changelog по формату **Keep a Changelog** (keepachangelog.com):
разделы *Added*, *Changed*, *Deprecated*, *Removed*, *Fixed*, *Security*. Версии —
по **SemVer** (semver.org): `MAJOR.MINOR.PATCH`, где MAJOR ломает совместимость.

В release notes ищи разделы *Breaking changes*, *Deprecations*, *Upgrade notes*,
*Known issues*, *Action required*. В changelog Kubernetes есть раздел *Urgent Upgrade
Notes* с подзаголовком *(No, really, you MUST read this before you upgrade)* — это
не шутка.

**Алгоритм перед обновлением:**
```text
 1. Выписать все версии между текущей и целевой (1.30 → 1.33 = три changelog'а, не один)
 2. Ctrl+F в каждом: breaking · deprecat · removed · action required · migration
 3. Сверить со своим: какие API, флаги, поля реально используются
 4. Итог — в описание MR: «Breaking changes: none that affect us» или список
```text
---

## 8. Сообщение об ошибке: разбор по частям

Почти любую ошибку можно разложить на четыре вопроса: **кто** сообщает (компонент),
**что** пытались сделать (операция), **с чем** (ресурс, файл, адрес), **почему** не вышло.

🇬🇧 kubectl:
```text
Error from server (Forbidden): pods is forbidden: User "dev" cannot list resource "pods"
in API group "" in the namespace "prod"
```text
| Вопрос | Ответ |
|--------|-------|
| Кто | *from server* — API-сервер, а не kubectl |
| Почему | *Forbidden* — пользователь известен, но прав нет (≠ *Unauthorized*) |
| Кто действует | `User "dev"` |
| Что и где | `list` `pods` в namespace `prod`; `API group ""` — core API |
| Куда смотреть | Role/RoleBinding в `prod`; проверка: `kubectl auth can-i list pods -n prod --as dev` |

🇬🇧 Docker:
```text
permission denied while trying to connect to the Docker daemon socket at
unix:///var/run/docker.sock: ...
```text
Кто: клиент `docker`. Что: подключиться к сокету демона. Почему: *permission denied* —
у пользователя нет прав на сокет. Куда: группа `docker` или `sudo` (и помнить, что группа
`docker` — фактически root).

🇬🇧 Terraform:
```text
Error: Error acquiring the state lock
...
Lock Info:
  Operation: OperationTypeApply
  Who:       daniyar@laptop
```text
Кто: Terraform. Что: взять блокировку state. Почему: её держит другой `apply` —
`Who` говорит, чей. Не бежать за `force-unlock`: сначала спросить Данияра, идёт ли у него
`apply`.

### Слова в ошибках

| Слово | Что значит | Куда смотреть |
|-------|------------|---------------|
| *denied*, *forbidden* | Нет прав: ты известен, но нельзя | RBAC, IAM, права на файл |
| *unauthorized* (HTTP 401) | Не аутентифицирован: нет токена или он неверный | Креды, срок токена |
| *connection refused* | Хост ответил, но порт никто не слушает | Сервис не запущен, не тот порт |
| *timed out*, *deadline exceeded* | Ответа не дождались | Сеть, файрвол, перегрузка |
| *no route to host*, *unreachable* | Пакеты не доходят | Маршрутизация, сеть |
| *not found*, *no such file*, *no such host* | Не существует | Путь, имя, DNS |
| *already exists*, *conflict* | Уже есть или конфликт версий | Имя, повторный create |
| *invalid*, *malformed* | Неверный формат | YAML, JSON, схема |
| *immutable* | Нельзя изменить после создания | Пересоздать ресурс |
| *exceeded* (*quota exceeded*) | Превышен лимит | Квоты, лимиты |
| *mismatch* | Не совпадает | Версии, checksum, имя в сертификате |
| *unexpected* (*unexpected EOF*) | Парсер не ожидал: оборванный файл или соединение | Синтаксис, сеть |
| *back-off* (*CrashLoopBackOff*) | Повторы с растущей паузой | Логи, `describe`, образ |
| *OOMKilled* | Убит за превышение памяти | `limits`, утечки |

Уровни: *warning* — предупреждение, работа идёт; *error* — операция не выполнена;
*fatal* / *panic* — процесс завершился.

---

## 9. Stack trace: где искать причину

| Язык | Где главное | Подсказка |
|------|-------------|-----------|
| Python | **Внизу**: последняя строка — тип и текст исключения | *Traceback (most recent call last)* — последний вызов внизу |
| Java | Первая строка — исключение; причина — **последний** *Caused by* | Ищи первые кадры из своего пакета |
| Go | Первая строка *panic: …*; ниже — стек горутины | Первый кадр из своего кода |

🇬🇧 Python:
```text
Traceback (most recent call last):
  File "/app/main.py", line 12, in &lt;module&gt;
    run()
  File "/app/main.py", line 8, in run
    conn = psycopg2.connect(DB_URL)
  ...
psycopg2.OperationalError: connection to server at "db" (10.0.0.5), port 5432 failed:
Connection refused
```text
Читаем снизу: БД на `db:5432` отказала в соединении (порт не слушают) → проблема не
в коде, а в БД или сети. Строка 8 `main.py` — где это случилось в нашем коде.

🇬🇧 Java:
```text
Exception in thread "main" java.lang.IllegalStateException: Failed to load config
    at com.example.App.loadConfig(App.java:42)
    at com.example.App.main(App.java:15)
Caused by: java.io.FileNotFoundException: /etc/app/config.yml (No such file or directory)
```text
Верхнее исключение — обёртка, причина — в *Caused by*: нет файла конфига. В Kubernetes —
проверить, смонтирован ли ConfigMap по этому пути.

Слова: *raise* / *throw* (выбросить исключение), *catch* / *handle* (поймать, обработать),
*unhandled* (необработанное), *propagate* (пробросить выше), *wrap* (обернуть).

---

## 10. Как читать страницу доки за 10–15 минут

```text
 1. Skim, 1–2 мин     заголовки, первые предложения, код, Note/Warning
 2. Решить            это Concepts, How-to или Reference? нужная ли страница?
 3. Intensive         нужный раздел; незнакомое слово → догадка по контексту →
                      если слово ключевое — словарь (Cambridge Dictionary)
 4. Руками            выполнить пример на стенде
 5. Anki              3 слова или сочетания в cloze-карточки
```text
Переводчик — на **одно предложение**, когда не помогли контекст и словарь, а не на всю
страницу. Сложное предложение сначала разбери сам: найди подлежащее и сказуемое, выкинь
вводные части.

---

## 11. Грабли

| Грабля | Последствие | Как правильно |
|--------|-------------|---------------|
| Переводить всю страницу | Понял сегодня, завтра снова нужен переводчик | Skim → нужный раздел → словарь по ключевым словам |
| Начинать с Reference | Утонул в полях, не понял модель | Overview → Quickstart → Concepts → How-to |
| *Deprecated* = *removed* | Паника зря или, наоборот, пропущенное удаление | Deprecated работает до удаления; ищи, в какой версии *removed* |
| *Should* как «можно не делать» | Нарушил рекомендацию без причины | SHOULD = делай, если нет веской причины |
| Читать только один changelog | Пропустил breaking change из промежуточной версии | Все версии между текущей и целевой |
| Пропускать Warning | Потерял данные | Admonitions читать всегда |
| Читать stack trace сверху (Python) | Ищешь причину в обёртке | Python — снизу, Java — последний *Caused by* |
| Искать ошибку по-русски | Мало ответов | Английская локаль, запрос дословно |
| Верить первому комментарию в issue | Устаревший workaround | Конец треда и комментарии мейнтейнеров |
| Путать *e.g.* и *i.e.* | Список примеров принял за полный список | e.g. — например, i.e. — то есть |

---

## 💼 Как это в DevOps

- Обновление кластера, чарта или провайдера Terraform начинается с чтения release notes
  всех промежуточных версий. Итог — строчка в описании MR.
- В инциденте первое, что ты видишь, — английская ошибка. Умение за 30 секунд разобрать
  её на «кто · что · с чем · почему» экономит минуты простоя.
- Решение редкой проблемы почти всегда лежит в GitHub issue, а не в документации.
- В спецификациях API, Helm-чартов и внутренних стандартах MUST/SHOULD/MAY решают,
  что обязательно проверять на ревью.
- На собесе просят «прочитать и объяснить» ошибку или кусок доки — это проверка
  и английского, и понимания.

---

## 📌 Шпаргалка

| Вопрос | Ответ |
|--------|-------|
| Режимы | Skimming — суть; scanning — факт; intensive — всё, что идёт в прод |
| Порядок чтения | Overview → Quickstart → Concepts → How-to → Reference |
| deprecated / removed | Работает, но удалят / уже не работает |
| as of v1.29 | Начиная с версии 1.29 |
| opt-in / opt-out | Выключено, включи сам / включено, можно выключить |
| defaults to | По умолчанию |
| MUST / SHOULD / MAY | Обязательно / рекомендуется / по желанию (RFC 2119, только ВЕРХНИЙ регистр) |
| SYNOPSIS | `[ ]` — необязательно, `...` — повтор, `(a \| b)` — одно из |
| Перед обновлением | Все changelog'и: breaking, deprecat, removed, action required |
| Разбор ошибки | Кто · что делал · с чем · почему |
| Forbidden vs Unauthorized | Нет прав vs не аутентифицирован |
| Stack trace | Python — снизу; Java — последний *Caused by* |

---

## 🧠 Что запомнить

1. ⭐ Цель чтения — понять, что делать, а не перевести страницу.
2. Режим чтения — под задачу: skim, scan, intensive.
3. Документация везде устроена одинаково: Overview, Quickstart, Concepts, How-to, Reference.
4. ⭐ *Deprecated* ещё работает, *removed* — уже нет; *as of* — «начиная с».
5. MUST, SHOULD, MAY в верхнем регистре — термины RFC 2119, а не просто слова.
6. В SYNOPSIS квадратные скобки — необязательное, `...` — повтор.
7. ⭐ Перед обновлением — changelog каждой промежуточной версии.
8. Issue читают с начала и с конца, верят мейнтейнерам, ищут *workaround* и *fixed in*.
9. ⭐ Ошибка = кто · что · с чем · почему; *Forbidden* ≠ *Unauthorized*.
10. Python-traceback читают снизу, в Java ищут последний *Caused by*.

➡️ Дальше: [03_vocabulary.md](/english/03-vocabulary) · задачи: 02_reading_docs_tasks.md


---

### Блок A. Теория


**A1.** ⭐ Чем skimming отличается от scanning и intensive reading? Приведи по примеру
из работы DevOps-инженера.

<details><summary>Ответ</summary>

Skimming — общий смысл за минуту: заголовки, первые предложения (понять, о чём
release notes). Scanning — найти факт: Ctrl+F по *default*, *since* (какой дефолтный
таймаут). Intensive — каждое предложение и пример руками (настройка RBAC для прода).

</details>

**A2.** Назови типовые разделы документации. В каком порядке читать новый инструмент
и почему не с Reference?

<details><summary>Ответ</summary>

Overview, Quickstart, Concepts, Tasks / How-to, Tutorials, Reference, Troubleshooting,
Release notes. Порядок: Overview → Quickstart → Concepts → How-to → Reference. Reference —
справочник по полям: без модели из Concepts он не складывается в картину.

</details>

**A3.** Что обычно лежит в разделах *Before you begin*, *Cleaning up* и *What's next*?

<details><summary>Ответ</summary>

*Before you begin* — что нужно заранее (версия, доступы, инструменты). *Cleaning up* —
как удалить созданное. *What's next* — ссылки на следующие темы.

</details>

**A4.** ⭐ Чем *deprecated* отличается от *removed* и *obsolete*? Что значит *as of v1.29*?

<details><summary>Ответ</summary>

*Deprecated* — работает, но будет удалено; пора планировать замену. *Removed* —
уже удалено, не работает. *Obsolete* — устарело и больше не используется (часто
игнорируется с предупреждением). *As of v1.29* — начиная с версии 1.29.

</details>

**A5.** Объясни *opt-in* и *opt-out* на примере телеметрии.

<details><summary>Ответ</summary>

Opt-in — выключено по умолчанию, включаешь сам: телеметрия не отправляется, пока
не согласишься. Opt-out — включено по умолчанию, можно выключить: отправляется, пока
не отключишь.

</details>

**A6.** Что значат *defaults to*, *if omitted*, *takes precedence over*, *falls back to*?

<details><summary>Ответ</summary>

*Defaults to* — значение по умолчанию; *if omitted* — если не указать; *takes
precedence over* — имеет приоритет (флаг сильнее переменной окружения); *falls back to* —
переходит к запасному варианту, если основной недоступен.

</details>

**A7.** ⭐ Что значат MUST, SHOULD и MAY по RFC 2119? Что уточняет RFC 8174?

<details><summary>Ответ</summary>

MUST — обязательно; SHOULD — рекомендуется, отступить можно при веской причине
и понимании последствий; MAY — по желанию. RFC 8174: особый смысл только у слов
в верхнем регистре.

</details>

**A8.** Как читать SYNOPSIS в `man`: что значат `[ ]`, `...`, `(a | b)`, слова в верхнем
регистре?

<details><summary>Ответ</summary>

`[ ]` — необязательно; `...` — можно повторить; `(a | b)` — обязательная группа,
выбрать одно; слова в верхнем регистре (или в угловых скобках, курсивом) — подставить
своё значение.

</details>

**A9.** Как быстро прочитать issue на 40 сообщений? Кому верить в треде?

<details><summary>Ответ</summary>

Первый пост (версия, окружение, симптом) → конец треда (статус) → комментарии
мейнтейнеров → Ctrl+F: *workaround*, *fixed in*, своя версия → связанные PR. Верить
мейнтейнерам и связанным PR, а не первому «у меня сработало».

</details>

**A10.** Расшифруй: LGTM, PTAL, WIP, IIRC, AFAIK, FWIW, nit, repro, ETA, TBD.

<details><summary>Ответ</summary>

Looks good to me; please take a look; work in progress; if I recall correctly;
as far as I know; for what it's worth; мелкое замечание (nitpick); воспроизведение;
estimated time of arrival (когда будет); to be determined (ещё не решено).

</details>

**A11.** ⭐ Что искать в release notes перед обновлением? Почему не хватает changelog'а
одной целевой версии?

<details><summary>Ответ</summary>

Breaking changes, deprecations, removed, action required, upgrade notes, known
issues. Breaking change мог прийти в промежуточной версии: при 1.30 → 1.33 нужно
прочитать changelog'и 1.31, 1.32 и 1.33.

</details>

**A12.** ⭐ На какие четыре вопроса раскладывается сообщение об ошибке?

<details><summary>Ответ</summary>

Кто сообщает (компонент), что пытались сделать (операция), с чем (ресурс, файл,
адрес), почему не вышло (причина).

</details>

**A13.** Чем *Forbidden* отличается от *Unauthorized*, а *connection refused* — от
*timed out*?

<details><summary>Ответ</summary>

*Forbidden* (403) — тебя узнали, но прав нет; *Unauthorized* (401) — не узнали:
нет токена или он неверный. *Connection refused* — хост ответил, но порт никто не слушает;
*timed out* — ответа нет вообще (файрвол, сеть, перегрузка).

</details>

**A14.** Где искать причину в Python traceback, в Java stack trace и в Go panic?

<details><summary>Ответ</summary>

Python — внизу, последняя строка: тип и текст исключения. Java — последний
*Caused by* и первые кадры из своего пакета. Go — первая строка *panic: …* и первый кадр
из своего кода.

</details>

---

### Блок B. «Что тут не так»


Каждый пункт: фрагмент доки или вывода и то, что написал по нему коллега. Найди ошибки
понимания и ошибки английского, перепиши сообщение.

**B1.** Дока: 🇬🇧 *The `--short` flag is deprecated as of v1.28 and will be removed in a
future release.* Коллега: 🇬🇧 *The `--short` flag was removed in v1.28, so our scripts is
broken now.*

<details><summary>Ответ</summary>

⚠️ *Deprecated* ≠ *removed*: флаг работает, скрипты не сломаны. Ошибка английского:
*scripts is* → *scripts are*. ✓ *The `--short` flag has been deprecated since v1.28 and
will be removed later. Our scripts still work, but we should replace it before the next
upgrade.*

</details>

**B2.** Дока: 🇬🇧 *Clients SHOULD use TLS 1.3.* Коллега: 🇬🇧 *Docs says TLS 1.3 is
optional, so we can skip it and use plain HTTP.*

<details><summary>Ответ</summary>

⚠️ SHOULD — не «optional», а «делай, если нет веской причины»; и речь о версии
TLS, а не о том, включать ли TLS вообще: plain HTTP — это отказ от TLS. *Docs says* →
*The docs say* (docs — множественное). ✓ *The docs say clients should use TLS 1.3.
We'll keep TLS and switch to 1.3 unless something blocks it.*

</details>

**B3.** Дока: 🇬🇧 *As of v2.0, the INI config format is no longer supported.* Коллега:
🇬🇧 *As of v2.0 the INI format is supported, so we don't need migrate anything.*

<details><summary>Ответ</summary>

⚠️ Смысл перевёрнут: *no longer supported* — больше не поддерживается, мигрировать
нужно. *need migrate* → *need to migrate*. ✓ *As of v2.0, the INI format is no longer
supported, so we need to migrate our configs to the new format before upgrading.*

</details>

**B4.** Дока: 🇬🇧 *Anonymous usage statistics are opt-in.* Коллега: 🇬🇧 *The tool sends
our statistics by default, we must to disable it before installing.*

<details><summary>Ответ</summary>

⚠️ *Opt-in* — по умолчанию выключено, ничего отключать не нужно. *must to* →
*must*. ✓ *Usage statistics are opt-in, so nothing is sent unless we enable it.*

</details>

**B5.** Вывод:

<details><summary>Ответ</summary>

⚠️ *Forbidden* — токен рабочий, пользователь опознан, не хватает прав на `get
secrets` в `payments`. *login* (сущ.) → *log in* (глагол). ✓ *ci-bot is authenticated,
but it doesn't have permission to read secrets in the payments namespace. We need
to check its Role and RoleBinding.*

</details>

```text:no-line-numbers
Error from server (Forbidden): secrets is forbidden: User "ci-bot" cannot get resource
```text
```text:no-line-numbers
"secrets" in API group "" in the namespace "payments"
```text
Коллега: 🇬🇧 *The token of ci-bot is expired, I need to login again.*

**B6.** Traceback заканчивается строкой `KeyError: 'DATABASE_URL'`, а первая строка
стека — `File "/app/app.py", line 3, in &lt;module&gt;`. Коллега: 🇬🇧 *The bug is in app.py
line 3, the import is broken.*

<details><summary>Ответ</summary>

⚠️ Python-traceback читают снизу: `KeyError: 'DATABASE_URL'` — нет переменной
окружения. `app.py` line 3 — лишь начало цепочки (импорт конфига). ✓ *The app crashes
at startup because the DATABASE_URL environment variable isn't set.*

</details>

**B7.** 🇬🇧 *I have read the changelog of v1.33 and there are no breaking changes, so we
can upgrade the cluster from v1.30 to v1.33 directly.*

<details><summary>Ответ</summary>

⚠️ Прочитан один changelog из трёх (1.31 и 1.32 пропущены). Кроме того, control
plane Kubernetes обновляют по одной минорной версии за раз: 1.30 → 1.31 → 1.32 → 1.33.
*I have read* → *I've read* — допустимо, но суть не в этом. ✓ *I've read the changelog
for v1.33. Before we upgrade, I'll also check 1.31 and 1.32, and we'll go one minor
version at a time.*

</details>

**B8.** Дока: 🇬🇧 *Supported backends include object storage services, e.g. S3 and GCS.*
Коллега: 🇬🇧 *So only S3 and GCS is supported, Azure Blob isn't.*

<details><summary>Ответ</summary>

⚠️ *e.g.* — примеры, а *include* — неполный список: Azure может поддерживаться,
надо проверить. *S3 and GCS is* → *are*. ✓ *S3 and GCS are just examples. I'll check
the full list to see if Azure Blob Storage is supported.*

</details>

**B9.** SYNOPSIS: `backupctl restore [--dry-run] [--target DIR] SNAPSHOT_ID`. Коллега:
🇬🇧 *`--target` is required and snapshot ID is optional, it takes the last one.*

<details><summary>Ответ</summary>

⚠️ Наоборот: `SNAPSHOT_ID` без скобок — обязателен, `--target DIR` в скобках —
необязателен. ✓ *The snapshot ID is required; `--target` is optional.*

</details>

**B10.** Дока: 🇬🇧 *`timeout` defaults to 30s and can be overridden by the `APP_TIMEOUT`
environment variable.* Коллега: 🇬🇧 *This option defaults 30 seconds and it can be override
by env variable.*

<details><summary>Ответ</summary>

⚠️ *defaults to*, а не *defaults*; после *can be* — третья форма *overridden*;
*env variable* лучше *an environment variable*. ✓ *This option defaults to 30 seconds
and can be overridden by an environment variable.*

</details>

**B11.** У issue статус *Closed as not planned*, последний комментарий бота: 🇬🇧 *This
issue has been automatically closed because it has not had recent activity.* Коллега:
🇬🇧 *Good news, the issue is closed, so the bug is fixed.*

<details><summary>Ответ</summary>

⚠️ *Closed as not planned* ботом за неактивность — баг не исправлен, issue
просто закрыли. ✓ *The issue was closed automatically because of inactivity. The bug
isn't fixed, so we still need the workaround.*

</details>

**B12.** Дока: 🇬🇧 *This feature is alpha. Alpha features are disabled by default, may be
buggy, and are subject to change without notice.* Коллега: 🇬🇧 *Let's enable it on
production, it's a new feature so it should be better.*

<details><summary>Ответ</summary>

⚠️ Alpha: выключено по умолчанию, может быть с багами и измениться без
предупреждения — не для прода. ✓ *This feature is still alpha and may change without
notice. Let's try it on staging first and wait for beta before using it in production.*

</details>

---

### Блок C. Практика


### C1. 🔑 Фрагмент в стиле Kubernetes API reference
🇬🇧
```text:no-line-numbers
maxUnavailable (optional)
```text
```text:no-line-numbers
The maximum number of pods that can be unavailable during the update. The value can be
```text
```text:no-line-numbers
an absolute number (for example, 5) or a percentage of desired pods (for example, 10%).
```text
```text:no-line-numbers
The absolute number is calculated from the percentage by rounding down. This field
```text
```text:no-line-numbers
cannot be 0 if maxSurge is 0. Defaults to 25%.
```text
**1.** Что будет, если поле не указать?

<details><summary>Ответ</summary>

1) 25%. 2) 25% от 10 = 2,5 → округление вниз → 2 пода. 3) Нет: при обоих
нулях выкатка не может ни убрать старый под, ни добавить новый. 4) «Абсолютное число
вычисляется из процента с округлением вниз. Поле не может быть равно 0, если maxSurge
равен 0. По умолчанию — 25%».

</details>

**2.** Сколько подов может быть недоступно при 10 репликах и значении по умолчанию?

<details><summary>Ответ</summary>

1) *Forces a new resource* — Terraform удалит бакет и создаст новый: без бэкапа
данные пропадут (в плане — `must be replaced`). 2) `force_destroy` по умолчанию `false`:
удаление непустого бакета завершится ошибкой, объекты не удалятся. 3) Блок пока работает,
но deprecated: перенести настройку в отдельный ресурс `example_bucket_versioning`
отдельным MR, проверив план — без замены бакета.

</details>

**3.** Можно ли поставить `maxUnavailable: 0` и `maxSurge: 0` одновременно? Почему?

<details><summary>Ответ</summary>

) Нет: код 0 — не ошибка, `on-failure` перезапускает только при ненулевом коде.

</details>

**4.** Переведи на русский последние два предложения.

<details><summary>Ответ</summary>

🇬🇧
```text
</details>

### C2. 🔑 Фрагмент в стиле Terraform provider docs
🇬🇧
```text:no-line-numbers
Argument Reference
```text
```text:no-line-numbers
The following arguments are supported:
```text
```text:no-line-numbers
* name - (Required) The name of the bucket. Changing this forces a new resource
```text
```text:no-line-numbers
  to be created.
```text
```text:no-line-numbers
* force_destroy - (Optional) When set to true, deleting the bucket also deletes all
```text
```text:no-line-numbers
  objects in it. Defaults to false.
```text
```text:no-line-numbers
* versioning - (Optional) A configuration block for object versioning. As of v5.0 of
```text
```text:no-line-numbers
  the provider, this block is deprecated. Use the separate example_bucket_versioning
```text
```text:no-line-numbers
  resource instead.
```text
**1.** Что произойдёт, если в коде переименовать бакет? Чем это опасно?

<details><summary>Ответ</summary>

1) 25%. 2) 25% от 10 = 2,5 → округление вниз → 2 пода. 3) Нет: при обоих
нулях выкатка не может ни убрать старый под, ни добавить новый. 4) «Абсолютное число
вычисляется из процента с округлением вниз. Поле не может быть равно 0, если maxSurge
равен 0. По умолчанию — 25%».

</details>

**2.** Что будет с объектами при `terraform destroy`, если `force_destroy` не указан?

<details><summary>Ответ</summary>

1) *Forces a new resource* — Terraform удалит бакет и создаст новый: без бэкапа
данные пропадут (в плане — `must be replaced`). 2) `force_destroy` по умолчанию `false`:
удаление непустого бакета завершится ошибкой, объекты не удалятся. 3) Блок пока работает,
но deprecated: перенести настройку в отдельный ресурс `example_bucket_versioning`
отдельным MR, проверив план — без замены бакета.

</details>

**3.** Что делать с блоком `versioning` при переходе на провайдер v5?

<details><summary>Ответ</summary>

) Нет: код 0 — не ошибка, `on-failure` перезапускает только при ненулевом коде.

</details>

### C3. Фрагмент в стиле Docker CLI reference
🇬🇧
```text:no-line-numbers
--restart
```text
```text:no-line-numbers
Restart policy to apply when a container exits. Defaults to "no".
```text
```text:no-line-numbers
  no                        Don't automatically restart the container.
```text
```text:no-line-numbers
  on-failure[:max-retries]  Restart only if the container exits with a non-zero status.
```text
```text:no-line-numbers
  always                    Always restart the container if it stops. If it's manually
```text
```text:no-line-numbers
                            stopped, it's restarted only when the Docker daemon restarts.
```text
```text:no-line-numbers
  unless-stopped            Like always, except that when the container is stopped
```text
```text:no-line-numbers
                            (manually or otherwise), it isn't restarted even after the
```text
```text:no-line-numbers
                            daemon restarts.
```text
**1.** Что значит запись `[:max-retries]`?

<details><summary>Ответ</summary>

1) 25%. 2) 25% от 10 = 2,5 → округление вниз → 2 пода. 3) Нет: при обоих
нулях выкатка не может ни убрать старый под, ни добавить новый. 4) «Абсолютное число
вычисляется из процента с округлением вниз. Поле не может быть равно 0, если maxSurge
равен 0. По умолчанию — 25%».

</details>

**2.** Какую политику выбрать для сервиса, который должен подниматься после перезагрузки
   сервера, но оставаться выключенным, если ты остановил его руками?

<details><summary>Ответ</summary>

1) *Forces a new resource* — Terraform удалит бакет и создаст новый: без бэкапа
данные пропадут (в плане — `must be replaced`). 2) `force_destroy` по умолчанию `false`:
удаление непустого бакета завершится ошибкой, объекты не удалятся. 3) Блок пока работает,
но deprecated: перенести настройку в отдельный ресурс `example_bucket_versioning`
отдельным MR, проверив план — без замены бакета.

</details>

**3.** Контейнер завершился с кодом 0. Перезапустит ли его `on-failure`?

<details><summary>Ответ</summary>

) Нет: код 0 — не ошибка, `on-failure` перезапускает только при ненулевом коде.

</details>

### C4. 🔑 Release notes → заметка в MR
🇬🇧

### Блок D. Инциденты


**D1.** Ночь, под `orders` в `CrashLoopBackOff`. В логах Java stack trace, последний
*Caused by*: `java.net.UnknownHostException: redis-master`. Напиши первое сообщение
в англоязычный канал инцидента.

<details><summary>Ответ</summary>

🇬🇧
```text
[SEV2] orders is down: pods are in CrashLoopBackOff since 02:10 UTC.
Root cause so far: the app can't resolve `redis-master` (UnknownHostException).
Checking the Redis Service and recent changes. Next update at 02:40 UTC.
```text
</details>

**D2.** В release notes Helm-чарта: 🇬🇧 *Action required: the `ingress.enabled` value
has been renamed to `ingress.create`. The old key is ignored.* Коллега спрашивает:
🇬🇧 *Anything we need to change before upgrading?* Ответь.

<details><summary>Ответ</summary>

🇬🇧
```text
Yes, one change: `ingress.enabled` was renamed to `ingress.create`, and the old key
is ignored. If we don't rename it in our values, the Ingress won't be created.
I'll update values.yaml in the same MR.
```text
</details>

**D3.** Коллега из соседней команды: 🇬🇧 *Per the API guidelines, the service MUST
return 429 when a client is rate limited, but yours returns 500. Can you check?*
Как понять, насколько это серьёзно, и что ответить?

<details><summary>Ответ</summary>

MUST — обязательное требование: 500 вместо 429 — нарушение, а не вкусовщина;
клиенты не поймут, что нужно подождать и повторить. 🇬🇧
```text
You're right, that's a bug on our side: we return 500 instead of 429 when a client
hits the rate limit. I've created OPS-456 and will fix it this week.
```text
</details>

**D4.** Ты нашёл в GitHub issue workaround, и он сработал. Напиши комментарий в issue
по-английски — полезный, а не «+1».

<details><summary>Ответ</summary>

🇬🇧
```text
The workaround from @user above worked for me on v3.14.2 (Ubuntu 24.04, containerd 2.0).
Steps: &lt;short list&gt;. Happy to test a fix if needed.
```text
«+1» не помогает мейнтейнерам; версия и окружение — помогают. Если нечего добавить —
реакция 👍 на первый пост.

</details>

**D5.** 18:55, `terraform apply` падает с *Error acquiring the state lock*, в `Who` —
коллега из Берлина. Напиши ему.

<details><summary>Ответ</summary>

🇬🇧
```text
Hi Jonas! My `terraform apply` for the network stack fails because the state is locked
by you (OperationTypeApply, started 17:40 UTC). Are you still running it? If it's
a stale lock, could you release it, or should I run `force-unlock`? No rush if you're
in the middle of an apply.
```text
</details>

**D6.** Ревьюер в твоём MR: 🇬🇧 *Is `--short` still supported? I think it was deprecated
in 1.27.* Как проверить и что ответить?

<details><summary>Ответ</summary>

Проверить release notes и `--help` той версии, что у нас. Если deprecated, но
работает: 🇬🇧 *Good catch. It's deprecated since 1.27 but still works in our version
(1.30). I'll replace it with `--output=json` in this MR to avoid surprises later.*

</details>

**D7.** Ты открыл issue в upstream-проекте. Мейнтейнер: 🇬🇧 *Can you share a minimal repro
and the output of `helm version`?* Что отправить и как ответить?

<details><summary>Ответ</summary>

Минимальный пример, который воспроизводит проблему (чарт или values на 10–20
строк), точные команды, ожидаемое и фактическое поведение, вывод `helm version`
и `kubectl version`. 🇬🇧
```text
Sure! Here's a minimal repro: &lt;link to a gist&gt;.
Steps: `helm install demo ./chart -f values.yaml`
Expected: the Service is created. Actual: install fails with &lt;error&gt;.
helm version: v3.x.y
```text
</details>

---

### Блок E. Вопросы с собеседования


**1.** 🇬🇧 *How do you approach documentation for a tool you've never used?*

<details><summary>Ответ</summary>

🇬🇧 *I start with the overview to see what problem it solves, then do the quickstart
   hands-on. After that, I read the Concepts section to understand the model, and I use
   the reference only when I need specific details.*

</details>

**2.** 🇬🇧 *What's the difference between "deprecated" and "removed"? How do you handle deprecations?*

<details><summary>Ответ</summary>

🇬🇧 *Deprecated means it still works but will be removed in a future version.
   Removed means it's gone. When I see a deprecation, I create a task to migrate before
   the version that removes it, and I check release notes before every upgrade.*

</details>

**3.** 🇬🇧 *You're upgrading a cluster from Kubernetes 1.30 to 1.33. What do you read first?*

<details><summary>Ответ</summary>

🇬🇧 *The changelogs for 1.31, 1.32, and 1.33, especially the Urgent Upgrade Notes and
   deprecations. I'd check the Deprecated API Migration Guide and scan our manifests with
   a tool like pluto or kubent. The control plane is upgraded one minor version at a time.*

</details>

**4.** 🇬🇧 *What does "Forbidden" mean in a kubectl error, compared to "Unauthorized"?*

<details><summary>Ответ</summary>

🇬🇧 *Forbidden means the API server knows who you are, but RBAC doesn't allow the action.
   Unauthorized means authentication failed: the token or certificate is missing, invalid,
   or expired.*

</details>

**5.** 🇬🇧 *How do you read a Python traceback or a Java stack trace?*

<details><summary>Ответ</summary>

🇬🇧 *A Python traceback shows the most recent call last, so I start from the bottom:
   the exception type and message, then the frames from our code. In Java, I look for the
   last "Caused by", because the top exception is often just a wrapper.*

</details>

**6.** 🇬🇧 *What's the difference between "connection refused" and "connection timed out"?*

<details><summary>Ответ</summary>

🇬🇧 *Connection refused means the host is reachable but nothing is listening on that
   port. A timeout means there's no response at all: a firewall drops the packets,
   the route is wrong, or the host is down or overloaded.*

</details>

**7.** 🇬🇧 *Where do you look when the documentation doesn't answer your question?*

<details><summary>Ответ</summary>

🇬🇧 *GitHub issues and discussions, release notes, and sometimes the source code.
   If nothing helps, I ask in the project's community channel or open an issue with
   a minimal repro.*

</details>

**8.** 🇬🇧 *What does "idempotent" mean, and why does it matter in automation?*

<details><summary>Ответ</summary>

🇬🇧 *An operation is idempotent if running it several times gives the same result
   as running it once. In automation, it means I can safely re-run a playbook or
   `kubectl apply` after a failure without breaking anything.*

---

</details>

---
---

---

### 🎯 Чек-лист

- [ ] ⭐ Выбираю режим чтения под задачу: skim, scan, intensive
- [ ] Читаю новый инструмент в порядке Overview → Quickstart → Concepts → How-to
- [ ] ⭐ Различаю *deprecated* / *removed*, *opt-in* / *opt-out*, понимаю *as of*, *defaults to*
- [ ] Читаю MUST / SHOULD / MAY как термины RFC 2119
- [ ] Разбираю SYNOPSIS в `man` и `--help`
- [ ] ⭐ Перед обновлением читаю changelog каждой промежуточной версии
- [ ] Разбираю ошибку по схеме «кто · что · с чем · почему»
- [ ] Нахожу причину в Python traceback и Java stack trace
- [ ] Написал резюме реального issue по-английски
