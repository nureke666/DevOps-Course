---
title: "03. KV secret engine"
description: "KV v1 vs v2, версии и мягкое удаление, структура путей, работа через API, доставка секретов в приложения"
---

# 03. KV secret engine ⭐

> Роадмап → Vault: *«KV secret engine · Базовые команды»*.
>
> **После темы ты умеешь:** работать с KV v2 из CLI, API и UI, понимать версии
> и «мягкое» удаление, правильно строить структуру путей.

---

## 🗺️ Что такое secrets engine

```text:no-line-numbers
 Vault — это набор ДВИЖКОВ, смонтированных по путям:

   secret/     kv-v2        ⭐ статические секреты (пароли, токены)
   database/   database     динамические креды для БД (тема 05)
   pki/        pki          выпуск TLS-сертификатов
   transit/    transit      шифрование как сервис (Vault не хранит данные)
   aws/        aws          временные ключи доступа в облако
   ssh/        ssh          подписанные SSH-сертификаты
```
```bash
vault secrets list
vault secrets enable -path=kv kv-v2       # смонтировать KV v2 по пути kv/
vault secrets disable kv/                 # ⚠️ удалит все секреты по этому пути
```

KV — самый простой и самый используемый движок: «ключ → значение» по пути.

---

## 1. KV v1 vs KV v2

| | KV v1 | KV v2 ⭐ |
|---|-------|---------|
| Версии секретов | Нет | Есть (по умолчанию 10 последних) |
| Удаление | Сразу и навсегда | Мягкое (можно восстановить) + `destroy` |
| Пути API | `secret/app/db` | `secret/data/app/db`, `secret/metadata/app/db` |
| CAS (защита от гонок) | Нет | Есть (`-cas`) |
| Команды | `vault kv ...` (одинаковые) | `vault kv ...` |

```bash
vault kv metadata get secret/app/db     # если работает — это v2
vault secrets list -detailed            # видно options: version: 2
```

⭐ Именно из-за разных путей политики для v2 пишут на `secret/data/*`
и `secret/metadata/*` — самая частая ошибка при настройке доступа.

---

## 2. Базовые команды ⭐

```bash
# --- запись ---
vault kv put secret/app/db username=app password=s3cr3t host=db.internal
vault kv put secret/app/db @payload.json          # из файла
cat payload.json | vault kv put secret/app/db -   # из stdin (⭐ пароль не попадёт в history)

# --- чтение ---
vault kv get secret/app/db
vault kv get -format=json secret/app/db | jq -r .data.data.password
vault kv get -field=password secret/app/db        # ⭐ для скриптов

# --- обновление отдельного поля (не затирая остальные) ---
vault kv patch secret/app/db password=new-s3cr3t

# --- список ---
vault kv list secret/
vault kv list secret/app/

# --- удаление ---
vault kv delete secret/app/db                     # мягкое: версия помечена удалённой
vault kv undelete -versions=3 secret/app/db       # ⭐ восстановить
vault kv destroy -versions=3 secret/app/db        # уничтожить конкретную версию
vault kv metadata delete secret/app/db            # ⚠️ удалить секрет со всеми версиями
```

⚠️ `vault kv put` **перезаписывает весь секрет**: если положить только `password`,
поле `username` исчезнет. Для изменения одного поля — `vault kv patch`.

---

## 3. Версии и метаданные

```text:no-line-numbers
 secret/app/db
   ├── версия 1   password=old        (destroyed)
   ├── версия 2   password=mid        (deleted — можно восстановить)
   └── версия 3   password=new        ⭐ текущая
```

```bash
vault kv get -version=2 secret/app/db        # прочитать старую версию
vault kv metadata get secret/app/db          # все версии, время, кто создал

# настройки хранения версий
vault kv metadata put -max-versions=5 -delete-version-after=720h secret/app/db
vault write secret/config max_versions=5     # для всего движка
```

CAS (check-and-set) — защита от одновременной записи:
```bash
vault kv put -cas=3 secret/app/db password=new   # применится, только если текущая версия 3
vault write secret/config cas_required=true      # требовать -cas для всех записей
```

---

## 4. Структура путей ⭐

```text:no-line-numbers
 secret/
 ├── prod/                           ⭐ разделение по окружениям — на верхнем уровне
 │   ├── billing/
 │   │   ├── db          username, password, host
 │   │   ├── redis
 │   │   └── api-keys
 │   └── frontend/
 ├── stage/
 ├── dev/
 └── shared/
     └── registry       креды реестра образов
```

Почему окружение первым сегментом: политика `secret/data/prod/*` мгновенно описывает
«доступ к прод-секретам», и его легко ограничить.

| Правило | Почему |
|---------|--------|
| Окружение → сервис → назначение | Простые и читаемые политики |
| Один секрет = одна сущность | Проще ротация и права |
| Не хранить конфигурацию | Адрес базы — не секрет (или хотя бы отдельный путь) |
| Именование `snake_case`, без пробелов | Удобство в скриптах и API |
| Общие секреты — в отдельном `shared/` | Видно, что используется многими |
| ⚠️ Не класть в один секрет пароли всех окружений | Утечка одного = утечка всех |

---

## 5. Работа через API и в скриптах

```bash
# чтение через HTTP API (так делают приложения)
curl -s -H "X-Vault-Token: $VAULT_TOKEN" \
  "$VAULT_ADDR/v1/secret/data/prod/billing/db" | jq -r .data.data.password

# запись
curl -s -H "X-Vault-Token: $VAULT_TOKEN" -X POST \
  -d '{"data":{"password":"s3cr3t"}}' \
  "$VAULT_ADDR/v1/secret/data/prod/billing/db"
```

```bash
# безопасный шаблон в bash
set -euo pipefail
DB_PASSWORD="$(vault kv get -field=password secret/prod/billing/db)"
export DB_PASSWORD               # ⭐ не печатать, не логировать
```

```text:no-line-numbers
Ответ KV v2 вложенный: .data.data.<field> — частая причина «почему jq возвращает null».
Для v1 путь был бы .data.<field>.
```

---

## 6. Как приложения получают секреты

| Способ | Комментарий |
|--------|-------------|
| Прямой запрос к API при старте | Просто; нужно уметь обновлять при ротации |
| Библиотека Vault для языка | Удобно, поддерживает renew лизов |
| **Vault Agent** | Сайдкар/демон: аутентифицируется сам, рендерит шаблоны в файлы ⭐ |
| **Agent Injector в Kubernetes** | Добавляет sidecar в под по аннотациям (тема 05) |
| **External Secrets Operator** | Превращает секрет Vault в обычный k8s Secret |
| `envconsul` / `vault agent template` | Подставляет секреты в окружение процесса |

```hcl
# пример шаблона Vault Agent
template {
  contents = <<EOT
DB_PASSWORD={{ with secret "secret/data/prod/billing/db" }}{{ .Data.data.password }}{{ end }}
EOT
  destination = "/etc/app/.env"
}
```

---

## 7. Грабли

| Грабля | Последствие | Решение |
|--------|-------------|---------|
| `kv put` вместо `kv patch` | Затёрты остальные поля секрета | `patch` для точечных изменений |
| Политика на `secret/app/*` при v2 | `permission denied` | `secret/data/*` + `secret/metadata/*` |
| `jq .data.password` для v2 | `null` | `.data.data.password` |
| Пароль в аргументах команды | Попадает в историю shell и логи | Ввод из stdin/файла |
| Секреты всех окружений в одном пути | Утечка масштабируется | Разделение `prod/stage/dev` |
| Хранение конфигурации в Vault | Раздувание, лишние зависимости | Конфиг — в git, секреты — в Vault |
| `vault secrets disable` вместо удаления секрета | Удалены все секреты пути | Осторожность с `disable` |
| Бесконечное число версий | Рост хранилища | `max-versions`, `delete-version-after` |
| Приложение читает секрет только при старте | Ротация требует рестарта | Agent/шаблоны или периодическое обновление |

---

## 💼 Как это в DevOps

- KV — «рабочая лошадка»: 90% повседневных задач это положить и прочитать секрет
  по понятному пути.
- Структура путей проектируется один раз и определяет, насколько простыми будут политики;
  переделывать её потом дорого.
- Приложения в Kubernetes обычно не ходят в Vault напрямую: используют Agent Injector
  или External Secrets — это снимает работу с разработчиков.
- CI читает секреты по AppRole/OIDC и никогда не хранит их в переменных «навечно».
- Версионирование KV v2 спасает при ошибочной перезаписи: секрет можно откатить,
  но ротацию всё равно придётся выполнить, если старое значение утекло.

---

## 📌 Шпаргалка

| Хочу | Команда |
|------|---------|
| Включить KV v2 | `vault secrets enable -path=kv kv-v2` |
| Записать секрет | `vault kv put secret/prod/app/db user=app password=...` |
| Записать из файла/stdin | `vault kv put secret/... @file.json` / `... -` |
| Прочитать | `vault kv get secret/prod/app/db` |
| Только поле | `vault kv get -field=password secret/prod/app/db` |
| Обновить одно поле | `vault kv patch secret/prod/app/db password=...` |
| Список путей | `vault kv list secret/prod/` |
| Старая версия | `vault kv get -version=2 secret/...` |
| Метаданные и версии | `vault kv metadata get secret/...` |
| Мягкое удаление | `vault kv delete secret/...` |
| Восстановить | `vault kv undelete -versions=N secret/...` |
| Уничтожить версию | `vault kv destroy -versions=N secret/...` |
| Удалить полностью | `vault kv metadata delete secret/...` |
| Ограничить версии | `vault kv metadata put -max-versions=5 secret/...` |
| Защита от гонок | `vault kv put -cas=N ...` |
| Через API | `GET /v1/secret/data/<path>` → `.data.data` |

---

## 🧠 Что запомнить

1. Vault — набор движков, смонтированных по путям; KV — самый частый.
2. ⭐ KV v2 хранит версии и поддерживает мягкое удаление; API-пути — `secret/data/...`
   и `secret/metadata/...`.
3. Политики для KV v2 пишут на `data`/`metadata`, иначе будет `permission denied`.
4. `kv put` перезаписывает секрет целиком; для одного поля — `kv patch`.
5. В ответе API значения лежат в `.data.data` — частая причина `null` в `jq`.
6. Структура путей: окружение → сервис → назначение; это делает политики простыми.
7. Секреты разных окружений не смешивают в одном пути.
8. Версии ограничивают (`max-versions`), иначе хранилище растёт.
9. Пароли не передают аргументами команды — только через stdin/файл.
10. Приложения получают секреты через Agent/ESO, а не «человек скопировал и вставил».

---

## Задачи

> Стенд: Vault в dev-режиме (`VAULT_ADDR`, `VAULT_TOKEN` экспортированы).

---

### Блок A. Теория

**A1.** Что такое secrets engine? Назови пять движков и их назначение.

<details><summary>Ответ</summary>

Движок — компонент, монтируемый по пути и реализующий работу с секретами:
`kv` (хранение), `database` (динамические креды), `pki` (сертификаты),
`transit` (шифрование как сервис), `aws`/`ssh` (временные доступы).

</details>

**A2.** ⭐ Чем KV v2 отличается от KV v1?

<details><summary>Ответ</summary>

KV v2 добавляет версионирование, мягкое удаление с восстановлением,
защиту CAS и раздельные API-пути `data`/`metadata`.

</details>

**A3.** Как понять, какая версия KV смонтирована?

<details><summary>Ответ</summary>

`vault secrets list -detailed` (видно `version: 2`) или наличие
`vault kv metadata get` для этого пути.

</details>

**A4.** Какие API-пути использует KV v2 и почему это важно для политик?

<details><summary>Ответ</summary>

Данные — `secret/data/<path>`, метаданные и версии — `secret/metadata/<path>`.
Политики пишутся на API-пути, поэтому указывать надо именно их.

</details>

**A5.** Чем `kv put` отличается от `kv patch`?

<details><summary>Ответ</summary>

`put` заменяет весь набор полей секрета, `patch` изменяет только переданные,
сохраняя остальные.

</details>

**A6.** Что происходит при `kv delete`? Чем это отличается от `destroy`
и `metadata delete`?

<details><summary>Ответ</summary>

`kv delete` помечает версию удалённой (восстанавливается `undelete`);
`destroy` уничтожает данные конкретной версии безвозвратно;
`metadata delete` удаляет секрет со всеми версиями и метаданными.

</details>

**A7.** Как прочитать конкретную версию секрета?

<details><summary>Ответ</summary>

`vault kv get -version=N <path>`.

</details>

**A8.** Что такое `max-versions` и `delete-version-after`?

<details><summary>Ответ</summary>

Максимальное число хранимых версий и время, после которого версия
автоматически удаляется; задаются для движка или конкретного секрета.

</details>

**A9.** Что такое CAS и от чего он защищает?

<details><summary>Ответ</summary>

Check-and-set: запись применяется, только если текущая версия совпадает
с указанной. Защищает от перезаписи чужих изменений при одновременной работе.

</details>

**A10.** ⭐ Как проектировать структуру путей и почему окружение ставят первым сегментом?

<details><summary>Ответ</summary>

Окружение → сервис → назначение. Окружение первым сегментом позволяет
одной политикой описать доступ ко всем секретам окружения и надёжно изолировать прод.

</details>

**A11.** Почему не стоит хранить в Vault обычную конфигурацию?

<details><summary>Ответ</summary>

Конфигурация не требует защиты и версионируется в git; хранение её в Vault
раздувает хранилище, усложняет доступ и делает Vault лишней зависимостью.

</details>

**A12.** Где в JSON-ответе KV v2 лежит значение поля?

<details><summary>Ответ</summary>

В `.data.data.<field>` (в KV v1 было `.data.<field>`).

</details>

**A13.** Как передать пароль в команду, не оставляя его в истории shell?

<details><summary>Ответ</summary>

Читать из файла (`@file.json`) или из stdin (`... -`), использовать
`read -s`, либо задавать через переменные окружения без печати.

</details>

**A14.** Какие есть способы доставки секретов в приложение?

<details><summary>Ответ</summary>

Прямой запрос к API, клиентская библиотека, Vault Agent с шаблонами,
Agent Injector в Kubernetes, External Secrets Operator, `envconsul`.

</details>

**A15.** Что делает Vault Agent с шаблонами?

<details><summary>Ответ</summary>

Аутентифицируется в Vault, получает секреты и рендерит их в файлы по шаблону,
обновляя при изменении и продлевая лизы.

</details>

---

### Блок B. «Что делает команда / что тут не так»

```bash
B1.  vault secrets enable -path=kv kv-v2
```

<details><summary>Ответ</summary>

Монтирует KV v2 по пути `kv/`.

</details>

```bash
B2.  vault kv put secret/prod/app/db user=app password=s3cr3t
```

<details><summary>Ответ</summary>

Создаёт секрет с двумя полями.

</details>

```bash
B3.  vault kv put secret/prod/app/db password=new        # ранее были user и host
```

<details><summary>Ответ</summary>

Перезапишет секрет: `user` и `host` исчезнут.

</details>

```bash
B4.  vault kv patch secret/prod/app/db password=new
```

<details><summary>Ответ</summary>

Изменит только пароль.

</details>

```bash
B5.  vault kv get -field=password secret/prod/app/db
```

<details><summary>Ответ</summary>

Вернёт только значение пароля — удобно для скриптов.

</details>

```bash
B6.  vault kv delete secret/prod/app/db
```

<details><summary>Ответ</summary>

Мягко удалит текущую версию.

</details>

```bash
B7.  vault kv undelete -versions=3 secret/prod/app/db
```

<details><summary>Ответ</summary>

Восстановит версию 3.

</details>

```bash
B8.  vault kv metadata delete secret/prod/app/db
```

<details><summary>Ответ</summary>

Удалит секрет со всеми версиями — необратимо.

</details>

```bash
B9.  vault secrets disable secret/
```

<details><summary>Ответ</summary>

⚠️ Отключит движок и удалит все секреты по пути.

</details>

```bash
B10. curl -H "X-Vault-Token: $T" $VAULT_ADDR/v1/secret/data/prod/app/db | jq .data.password
```

<details><summary>Ответ</summary>

Вернёт `null`: для v2 нужен `.data.data.password`.

</details>

```bash
B11. path "secret/app/*" { capabilities = ["read"] }      # KV v2
```

<details><summary>Ответ</summary>

Политика не сработает для KV v2 — нужен `secret/data/app/*`.

</details>

```bash
B12. vault kv put secret/all/passwords prod=... stage=... dev=...
```

<details><summary>Ответ</summary>

Все окружения в одном секрете: утечка одного значения раскрывает все.

</details>

---

### Блок C. Практика

#### C1. 🔑 Основные операции
1. Запиши секрет с тремя полями.
2. Прочитай целиком, затем одно поле.
3. Обнови одно поле через `put` и убедись, что остальные исчезли.
4. Восстанови и повтори через `patch`.

<details><summary>Ответ</summary>

После `put` с одним полем остальные исчезают — это самая частая ошибка новичка.

</details>

#### C2. Версии
1. Сделай пять последовательных записей.
2. Посмотри `vault kv metadata get`.
3. Прочитай версию 2.
4. Ограничь число версий тремя и проверь результат.

#### C3. Мягкое удаление
1. Удали секрет (`kv delete`), попробуй прочитать.
2. Восстанови (`undelete`).
3. Уничтожь конкретную версию (`destroy`) и убедись, что она невосстановима.
4. Удали секрет целиком (`metadata delete`).

<details><summary>Ответ</summary>

После `destroy` данные версии не восстанавливаются, в метаданных остаётся
запись `destroyed: true`.

</details>

#### C4. CAS
1. Включи `cas_required` для движка.
2. Попробуй записать без `-cas` — получи ошибку.
3. Запиши с правильной версией, затем с устаревшей — сравни поведение.

<details><summary>Ответ</summary>

Без `-cas` при `cas_required` запись вернёт ошибку; с устаревшей версией —
ошибку конфликта.

</details>

#### C5. 🔑 Структура путей
Спроектируй и создай структуру для трёх окружений и трёх сервисов.
Заполни тестовыми значениями. Нарисуй дерево в README.

#### C6. Политики и пути KV v2
1. Напиши политику на чтение только `secret/data/dev/*`.
2. Проверь, что чтение prod запрещено.
3. Добавь `list` на `secret/metadata/dev/*` и проверь `vault kv list`.

<details><summary>Ответ</summary>

Для `vault kv list` нужны права `list` на `secret/metadata/...`.

</details>

#### C7. Работа через API
Прочитай и запиши секрет через `curl`, разбери структуру JSON.
Напиши однострочник, возвращающий только пароль.

#### C8. Безопасный ввод
Запиши секрет так, чтобы он не попал в историю shell (stdin/файл).
Проверь `history | grep password`.

<details><summary>Ответ</summary>

Правильный результат — пароля нет в истории shell.

</details>

#### C9. Vault Agent (со звёздочкой)
Настрой Vault Agent с шаблоном, который рендерит `.env` файл с паролем,
и проверь автоматическое обновление после изменения секрета.

<details><summary>Ответ</summary>

Vault Agent перерендерит файл после изменения секрета и может выполнить
команду перезагрузки приложения.

</details>

#### C10. Скрипт выкладки
Напиши скрипт, который получает секреты из Vault и передаёт их приложению
через переменные окружения, не печатая их в лог.

---

### Блок D. Инциденты

**D1.** После записи секрета приложение перестало подключаться к базе:
пропало поле `username`. Что произошло?

<details><summary>Ответ</summary>

Использовали `kv put` вместо `kv patch` — секрет перезаписан целиком.

</details>

**D2.** Политика выглядит верно, но `vault kv get` возвращает `permission denied`. Причина?

<details><summary>Ответ</summary>

Политика написана на неверные пути (без `data`), токен не содержит политику,
другой mount/namespace, действует `deny`, истёк токен.

</details>

**D3.** `vault kv list` не работает, хотя чтение секретов работает. Чего не хватает?

<details><summary>Ответ</summary>

Прав `list` на `secret/metadata/<path>`.

</details>

**D4.** `jq` возвращает `null` при чтении секрета через API. Что не так?

<details><summary>Ответ</summary>

Для KV v2 значение лежит в `.data.data`, а не в `.data`.

</details>

**D5.** Секрет случайно перезаписан. Как восстановить и что делать дальше?

<details><summary>Ответ</summary>

Прочитать предыдущую версию (`-version=N`) и записать её обратно
(или `undelete`, если было удаление); затем разобраться, почему запись прошла
без ревью, и при необходимости ротировать секрет.

</details>

**D6.** Кто-то выполнил `vault secrets disable secret/`. Последствия и действия.

<details><summary>Ответ</summary>

Удалены все секреты по этому пути. Восстановление — из снапшота Vault;
профилактика — ограничение прав на `sys/mounts` и аккуратность с административными
командами.

</details>

**D7.** Хранилище Vault растёт, хотя секретов немного. Возможные причины?

<details><summary>Ответ</summary>

Много версий секретов (не ограничен `max-versions`), большие значения,
частая перезапись, журнал аудита в том же томе, лизы и токены.

</details>

**D8.** Пароль виден в истории команд у нескольких инженеров. Что делать?

<details><summary>Ответ</summary>

Считать секрет скомпрометированным: ротировать, почистить историю на машинах,
перейти на ввод из stdin/файла, обучить команду.

</details>

**D9.** Приложение читает секрет только при старте, пароль ротировали — сервис упал.
Как правильно?

<details><summary>Ответ</summary>

Приложение должно уметь перечитывать секрет (через Agent/ESO, периодическое
обновление или сигнал), либо ротация выполняется с двумя активными учётками.

</details>

**D10.** В одном секрете лежат пароли всех окружений, произошла утечка dev-доступа.
Масштаб проблемы и как было бы правильно?

<details><summary>Ответ</summary>

Утечка dev-доступа раскрывает прод, так как всё лежит в одном секрете.
Правильно — разделять по окружениям и путям и выдавать разные политики.

</details>

---

### Блок E. Вопросы с собеседования

**1.** Что такое secrets engine?

<details><summary>Ответ</summary>

Компонент Vault, смонтированный по пути и отвечающий за конкретный тип секретов.

</details>

**2.** Чем KV v2 отличается от v1?

<details><summary>Ответ</summary>

Версионирование, мягкое удаление, CAS и раздельные пути `data`/`metadata`.

</details>

**3.** Какие пути использует KV v2 и почему это важно?

<details><summary>Ответ</summary>

`secret/data/...` и `secret/metadata/...`; политики пишутся именно на них.

</details>

**4.** Чем `put` отличается от `patch`?

<details><summary>Ответ</summary>

`put` перезаписывает весь секрет, `patch` изменяет отдельные поля.

</details>

**5.** Что происходит при удалении секрета?

<details><summary>Ответ</summary>

Версия помечается удалённой и может быть восстановлена; `destroy` уничтожает
данные, `metadata delete` — весь секрет.

</details>

**6.** Как восстановить предыдущую версию?

<details><summary>Ответ</summary>

`vault kv get -version=N` и повторная запись либо `vault kv undelete`.

</details>

**7.** Как структурировать пути секретов?

<details><summary>Ответ</summary>

Окружение → сервис → назначение, без смешения окружений.

</details>

**8.** Как приложение получает секрет из Vault?

<details><summary>Ответ</summary>

Через API, клиентскую библиотеку, Vault Agent, Agent Injector или External Secrets.

</details>

**9.** Как не «засветить» пароль при записи?

<details><summary>Ответ</summary>

Передавать из файла/stdin, не указывать в аргументах команды.

</details>

**10.** Что такое CAS?

<details><summary>Ответ</summary>

Check-and-set — запись только при совпадении ожидаемой версии.

</details>

---

### 🎯 Чек-лист

- [ ] Свободно пользуюсь `kv put/get/patch/list/delete`
- [ ] ⭐ Помню разницу `put` и `patch`
- [ ] Работал с версиями, `undelete` и `destroy`
- [ ] Ограничил число версий
- [ ] Понимаю пути `data`/`metadata` и пишу политики правильно
- [ ] Спроектировал структуру путей по окружениям и сервисам
- [ ] Читаю секреты через API и знаю про `.data.data`
- [ ] Ввожу секреты без попадания в историю shell
- [ ] Пробовал Vault Agent с шаблоном
- [ ] Приложение получает секреты без ручного копирования
